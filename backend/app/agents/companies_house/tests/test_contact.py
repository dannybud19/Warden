"""Contact module tests: webmail, lookalike, RDAP age, phone scam reports (offline)."""

from typing import Any

import httpx
import pytest

from app.agents.companies_house import modules
from app.agents.companies_house.models import (
    FilterContext,
    KeptSnippet,
    QueryBudget,
    Snippet,
)
from app.agents.companies_house.modules import contact
from app.agents.companies_house.testing import TODAY, Router, fixture_json, no_sleep
from app.contracts import Case, FactKey
from app.core.agent import AgentContext
from app.core.search import FakeSearch, SearchResult

_ = modules


def _case(**kwargs: Any) -> Case:
    return Case.model_validate(
        {"case_id": "c1", "created_at": "2026-11-14T10:00:00", "student": {}, **kwargs}
    )


def _msg(i: int, sender: str, text: str, ev: str = "ev1") -> dict[str, Any]:
    return {"id": f"m{i}", "evidence_id": ev, "sender": sender, "channel": "email", "text": text}


def _agent_case(email: str, text: str | None = None) -> Case:
    return _case(messages=[_msg(1, "agent", text or f"Please write to {email} for the contract")])


async def _run(ctx: AgentContext, case: Case, budget: QueryBudget | None = None):
    return await contact.run(ctx, case, None, budget or QueryBudget(), today=TODAY, sleep=no_sleep)


def _ids(result: Any) -> list[str]:
    return [f.id for f in result.findings]


def _rdap_router(domain: str, reply: Any) -> Router:
    return Router({("GET", f"/domain/{domain}"): reply})


# --- pure rules ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("gmail.com", True),
        ("hotmail.co.uk", True),
        ("yahoo.co.uk", True),
        ("live.com", True),
        ("agency.co.uk", False),
    ],
)
def test_is_webmail(domain: str, expected: bool) -> None:
    assert contact.is_webmail(domain) is expected


def test_lookalike_brand_detects_fake_and_accepts_real() -> None:
    assert contact.lookalike_brand("rightmove-lettings.co.uk") == "rightmove"
    assert contact.lookalike_brand("rightmove.co.uk") is None
    assert contact.lookalike_brand("mail.rightmove.co.uk") is None
    assert contact.lookalike_brand("smithlets.co.uk") is None


def test_parse_registration_date_is_defensive() -> None:
    parsed = contact.parse_registration_date(fixture_json("contact", "rdap_new.json"))
    assert str(parsed) == "2026-10-25"
    assert contact.parse_registration_date({"events": [{"eventAction": "registration"}]}) is None
    assert contact.parse_registration_date({"events": "x"}) is None
    assert contact.parse_registration_date(["nope"]) is None
    bad = {"events": [{"eventAction": "registration", "eventDate": "garbage"}]}
    assert contact.parse_registration_date(bad) is None


# --- webmail and lookalike -------------------------------------------------------------------


async def test_webmail_gmail_is_low_suspicious(make_ctx) -> None:
    ctx = await make_ctx()
    result = await _run(ctx, _agent_case("lets.london@gmail.com"))
    assert _ids(result) == ["companies_house:webmail"]
    finding = result.findings[0]
    assert finding.severity == "low"
    assert finding.confidence == 0.5
    assert finding.supports == "suspicious"
    assert "lets.london@gmail.com" in (finding.evidence[0].quote or "")
    assert finding.evidence[0].evidence_id == "ev1"


async def test_webmail_hotmail_prefix_matches(make_ctx) -> None:
    ctx = await make_ctx()
    result = await _run(ctx, _agent_case("agent@hotmail.co.uk"))
    assert _ids(result) == ["companies_house:webmail"]


async def test_lookalike_domain_is_high(make_ctx) -> None:
    ctx = await make_ctx(_rdap_router("rightmove-lettings.co.uk", (404, "")))
    result = await _run(ctx, _agent_case("jo@rightmove-lettings.co.uk"))
    assert _ids(result) == ["companies_house:lookalike-domain"]
    finding = result.findings[0]
    assert finding.severity == "high"
    assert finding.confidence == 0.8
    assert "rightmove-lettings.co.uk" in (finding.evidence[0].quote or "")


async def test_real_brand_domain_gives_no_finding(make_ctx) -> None:
    ctx = await make_ctx(
        _rdap_router("mail.rightmove.co.uk", (200, fixture_json("contact", "rdap_old.json")))
    )
    result = await _run(ctx, _agent_case("noreply@mail.rightmove.co.uk"))
    assert result.findings == []


async def test_landlord_email_without_message_falls_back_to_landlord_evidence(make_ctx) -> None:
    ctx = await make_ctx()
    case = _case(landlord={"email": "Boss@Gmail.com"})
    result = await _run(ctx, case)
    ref = result.findings[0].evidence[0]
    assert (ref.evidence_id, ref.quote) == ("landlord", "boss@gmail.com")


# --- RDAP ------------------------------------------------------------------------------------


async def test_rdap_20_days_old_is_new_domain_medium(make_ctx) -> None:
    router = _rdap_router(
        "lets-london-homes.co.uk", (200, fixture_json("contact", "rdap_new.json"))
    )
    ctx = await make_ctx(router)
    result = await _run(ctx, _agent_case("hello@lets-london-homes.co.uk"))
    assert _ids(result) == ["companies_house:new-domain"]
    finding = result.findings[0]
    assert finding.severity == "medium"
    assert "20 days old" in finding.title
    assert finding.evidence[0].evidence_id == "rdap"
    assert finding.evidence[0].quote == "registration: 2026-10-25"
    assert "Source: https://rdap.org/domain/lets-london-homes.co.uk" in finding.detail
    assert result.failed_checks == []


async def test_rdap_old_domain_gives_no_finding(make_ctx) -> None:
    ctx = await make_ctx(
        _rdap_router("oldagency.co.uk", (200, fixture_json("contact", "rdap_old.json")))
    )
    result = await _run(ctx, _agent_case("info@oldagency.co.uk"))
    assert result.findings == []
    assert result.failed_checks == []


async def test_rdap_404_is_silent(make_ctx) -> None:
    router = _rdap_router("oldagency.co.uk", (404, ""))
    ctx = await make_ctx(router)
    result = await _run(ctx, _agent_case("info@oldagency.co.uk"))
    assert result.findings == []
    assert result.failed_checks == []
    assert len(router.requests) == 1


async def test_rdap_500_three_times_is_failed_check_not_finding(make_ctx) -> None:
    router = _rdap_router("oldagency.co.uk", (500, ""))
    ctx = await make_ctx(router)
    result = await _run(ctx, _agent_case("info@oldagency.co.uk"))
    assert result.findings == []
    assert len(router.requests) == 3
    assert len(result.failed_checks) == 1
    assert result.failed_checks[0].startswith("email domain age (RDAP: 500")


async def test_rdap_unreadable_body_is_a_failed_check_not_a_clean_result(make_ctx) -> None:
    router = _rdap_router("oldagency.co.uk", (200, "<html>Service unavailable</html>"))
    ctx = await make_ctx(router)
    result = await _run(ctx, _agent_case("info@oldagency.co.uk"))
    assert result.findings == []
    assert result.failed_checks == ["email domain age (RDAP: unreadable response)"]


async def test_rdap_not_called_for_webmail(make_ctx) -> None:
    router = Router()
    ctx = await make_ctx(router)
    await _run(ctx, _agent_case("x@gmail.com"))
    assert router.requests == []


async def test_rdap_follows_redirects(make_ctx) -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://rdap.example/domain/x.co.uk"})

    router = Router(
        {
            ("GET", "/domain/x.co.uk"): redirect,
            ("GET", "https://rdap.example/domain/x.co.uk"): (
                200,
                fixture_json("contact", "rdap_new.json"),
            ),
        }
    )
    ctx = await make_ctx(router)
    result = await _run(ctx, _agent_case("a@x.co.uk"))
    assert _ids(result) == ["companies_house:new-domain"]


# --- contacts and facts ----------------------------------------------------------------------


async def test_students_own_email_is_ignored(make_ctx) -> None:
    router = Router()
    ctx = await make_ctx(router)
    case = _case(messages=[_msg(1, "student", "my email is me@gmail.com")])
    result = await _run(ctx, case)
    assert result.findings == [] and result.facts == []
    assert router.requests == []


async def test_landlord_email_used_before_messages(make_ctx) -> None:
    ctx = await make_ctx()
    case = _case(
        landlord={"email": "owner@gmail.com"},
        messages=[_msg(1, "agent", "write to other@hotmail.com")],
    )
    result = await _run(ctx, case)
    assert [f.value for f in result.facts] == ["gmail.com"]
    assert result.facts[0].source == "landlord"


async def test_email_domain_fact_source_is_agent_message_evidence(make_ctx) -> None:
    ctx = await make_ctx(_rdap_router("oldagency.co.uk", (404, "")))
    case = _case(messages=[_msg(1, "agent", "mail info@oldagency.co.uk", ev="ev-wa-7")])
    result = await _run(ctx, case)
    assert len(result.facts) == 1
    fact = result.facts[0]
    assert fact.key == FactKey.EMAIL_DOMAIN
    assert (fact.value, fact.source, fact.agent) == (
        "oldagency.co.uk",
        "ev-wa-7",
        "companies_house",
    )


async def test_no_contacts_means_no_http_and_no_search(make_ctx) -> None:
    router = Router()
    search = FakeSearch()
    ctx = await make_ctx(router, search=search)
    result = await _run(ctx, _case(messages=[_msg(1, "agent", "Hello, viewing is Friday")]))
    assert result.findings == [] and result.facts == [] and result.failed_checks == []
    assert router.requests == [] and search.queries == []


# --- phone -----------------------------------------------------------------------------------

_PHONE_CASE = {"landlord": {"phone": "07911 123456"}}
_HIT = SearchResult(
    title="Scam number", url="https://forum.example/t/1", snippet="07911123456 took my deposit"
)


def _keep(label: str):
    async def fake(
        ctx: AgentContext, snippets: list[Snippet], context: FilterContext
    ) -> list[KeptSnippet]:
        assert context.subject == "phone" and context.phone == "07911123456"
        return [KeptSnippet(snippets[0], label, "took my deposit", False)]  # type: ignore[arg-type]

    return fake


async def test_phone_scam_report_gives_finding_with_source(make_ctx, monkeypatch) -> None:
    monkeypatch.setattr(contact, "filter_snippets", _keep("scam_report"))
    search = FakeSearch({"07911123456": [_HIT]})
    ctx = await make_ctx(search=search)
    result = await _run(ctx, _case(**_PHONE_CASE))
    assert search.queries == ['"07911123456" scam']
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.id.startswith("companies_house:phone-scam-")
    assert finding.severity == "high" and finding.confidence == 0.7 and not finding.hard_flag
    assert finding.evidence[0].evidence_id == "web"
    assert finding.evidence[0].quote == "took my deposit"
    assert "Source: https://forum.example/t/1" in finding.detail


async def test_phone_non_scam_label_is_ignored(make_ctx, monkeypatch) -> None:
    monkeypatch.setattr(contact, "filter_snippets", _keep("negative_review"))
    ctx = await make_ctx(search=FakeSearch({"07911123456": [_HIT]}))
    result = await _run(ctx, _case(**_PHONE_CASE))
    assert result.findings == []


async def test_phone_budget_exhausted_is_failed_check(make_ctx) -> None:
    search = FakeSearch()
    ctx = await make_ctx(search=search)
    result = await _run(ctx, _case(**_PHONE_CASE), QueryBudget(limit=0))
    assert result.findings == []
    assert result.failed_checks == ["phone scam reports (query budget)"]
    assert search.queries == []


async def test_phone_search_failure_is_failed_check_not_no_results(make_ctx) -> None:
    class Boom:
        async def search(self, query: str, *, depth: str = "standard") -> list[SearchResult]:
            raise RuntimeError("down")

    ctx = await make_ctx(search=Boom())  # type: ignore[arg-type]
    result = await _run(ctx, _case(**_PHONE_CASE))
    assert result.findings == []
    assert len(result.failed_checks) == 1
    assert result.failed_checks[0].startswith("phone scam reports (Linkup:")


# --- invariants ------------------------------------------------------------------------------


async def test_all_findings_follow_evidence_conventions(make_ctx, monkeypatch) -> None:
    monkeypatch.setattr(contact, "filter_snippets", _keep("scam_report"))
    router = _rdap_router(
        "rightmove-lettings.co.uk",
        (200, {"events": [{"eventAction": "registration", "eventDate": "2026-11-01T00:00:00Z"}]}),
    )
    ctx = await make_ctx(router, search=FakeSearch({"07911123456": [_HIT]}))
    case2 = _case(
        messages=[
            _msg(1, "agent", "email jo@rightmove-lettings.co.uk"),
            _msg(2, "agent", "call 07911 123456"),
        ]
    )
    result = await _run(ctx, case2)
    ids = _ids(result)
    assert {"lookalike-domain", "new-domain"} <= {i.split(":")[1] for i in ids}
    assert any(i.startswith("companies_house:phone-scam-") for i in ids)
    for finding in result.findings:
        assert finding.id.startswith("companies_house:")
        assert finding.evidence and all((e.quote or "").strip() for e in finding.evidence)
        assert not finding.hard_flag
        assert finding.check_id == "landlord_identity"
        if finding.evidence[0].evidence_id in {"rdap", "web"}:
            assert "Source: http" in finding.detail
    assert {f.key for f in result.facts} <= {FactKey.EMAIL_DOMAIN}

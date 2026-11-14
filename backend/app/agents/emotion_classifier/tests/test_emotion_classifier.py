import json
from datetime import UTC, datetime

import pytest

from app.agents.emotion_classifier import pricing, rules
from app.agents.emotion_classifier.agent import EmotionClassifierAgent
from app.agents.emotion_classifier.stub import EmotionClassifierStub
from app.contracts import AgentReport, AgentStatus, Case, Listing, Message, StudentContext
from app.core.agent import AgentContext, hash_slice
from app.core.llm import FakeLLM

PROMPT_KEY = "facts"  # appears in prompts/facts_vs_feelings.md


def with_llm(ctx: AgentContext, reply: dict | str) -> AgentContext:
    text = reply if isinstance(reply, str) else json.dumps(reply)
    return AgentContext(
        llm=FakeLLM({PROMPT_KEY: text}),
        search=ctx.search,
        http=ctx.http,
        settings=ctx.settings,
        log=ctx.log,
    )


def chat(
    *lines: str, rent: int | None = None, postcode: str | None = None, notes: str = ""
) -> Case:
    """`"a: text"` is an agent message, `"s: text"` a student one."""
    messages = [
        Message(
            id=f"msg_{i}",
            evidence_id="ev_1",
            sender="agent" if line.startswith("a:") else "student",
            channel="whatsapp",
            text=line[2:].strip(),
        )
        for i, line in enumerate(lines, 1)
    ]
    listing = Listing(rent_pcm=rent, postcode=postcode) if rent or postcode else None
    return Case(
        case_id="c1",
        created_at=datetime.now(UTC),
        messages=messages,
        listing=listing,
        student=StudentContext(notes=notes or None),
    )


def ids(report: AgentReport) -> dict:
    return {f.id.split(":")[1]: f for f in report.findings}


# ---------------------------------------------------------------- stub and fixtures


async def test_stub_returns_valid_report(fake_agency_case: Case, ctx: AgentContext) -> None:
    agent = EmotionClassifierStub()
    report = await agent.run(fake_agency_case, ctx)
    assert AgentReport.model_validate(report.model_dump()) == report
    assert report.agent == "emotion_classifier"
    assert report.version.endswith("-stub")
    assert report.input_hash == hash_slice(agent.input_slice(fake_agency_case))


async def test_fake_agency_pressure_is_split_from_facts(
    fake_agency_case: Case, ctx: AgentContext
) -> None:
    report = await EmotionClassifierAgent().run(fake_agency_case, ctx)
    assert report.status == AgentStatus.OK
    found = ids(report)
    assert found["pressure_scarcity"].evidence[0].quote == "Three other students want it."
    assert found["pressure_urgency"].severity == "medium"
    assert found["pressure_urgency"].check_id == "no_pressure"
    # the student's own pressure is shown, but never counts against the place
    assert found["student_desperation"].severity == "info"
    assert found["student_desperation"].evidence[0].evidence_id == "student_notes"


async def test_overseas_landlord_pressure(overseas_landlord_case: Case, ctx: AgentContext) -> None:
    found = ids(await EmotionClassifierAgent().run(overseas_landlord_case, ctx))
    assert {"pressure_urgency", "pressure_scarcity"} <= set(found)


async def test_genuine_flat_clears_pressure_and_price(
    genuine_flat_case: Case, ctx: AgentContext
) -> None:
    report = await EmotionClassifierAgent().run(genuine_flat_case, ctx)
    found = ids(report)
    assert found["no_pressure_stated"].supports == "cleared"
    assert found["rent_vs_area"].supports == "cleared"
    assert not any(f.supports == "suspicious" and f.severity != "info" for f in report.findings)


# ---------------------------------------------------------------- rules


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("a: Send the deposit today to hold it.", "urgency"),
        ("a: Please decide quickly.", "urgency"),
        ("a: Three other students want it.", "scarcity"),
        ("a: There has been a lot of interest in this one.", "scarcity"),
        ("s: I've already spent two weeks on this.", "sunk_cost"),
        ("s: Term starts on Monday and I'm desperate.", "desperation"),
    ],
)
def test_rule_patterns(line: str, kind: str) -> None:
    assert [h.kind for h in rules.rule_hits(chat(line))] == [kind]


@pytest.mark.parametrize(
    "line",
    [
        "a: Thanks for coming today.",
        "a: We have slots on Saturday at 10:30 or 12:00.",
        "a: The flat is available from 1 December.",
        "s: Three other students want it, apparently.",  # agent-side kinds never fire on students
    ],
)
def test_neutral_messages_are_not_pressure(line: str) -> None:
    assert rules.rule_hits(chat(line)) == []


async def test_three_kinds_raise_severity_to_high(ctx: AgentContext) -> None:
    case = chat("a: Three other students want it. Decide quickly.")
    reply = {
        "entries": [
            {
                "message_id": "msg_1",
                "influence": [
                    {"kind": "authority", "quote": "Three other students", "explanation": "x"}
                ],
            }
        ]
    }
    found = ids(await EmotionClassifierAgent().run(case, with_llm(ctx, reply)))
    assert {found[k].severity for k in ("pressure_urgency", "pressure_scarcity")} == {"high"}
    assert found["pressure_authority"].severity == "high"


async def test_reassurance_does_not_clear_when_there_is_pressure(ctx: AgentContext) -> None:
    case = chat("a: No rush at all.", "a: But three other people want it.")
    found = ids(await EmotionClassifierAgent().run(case, ctx))
    assert "no_pressure_stated" not in found and "pressure_scarcity" in found


# ---------------------------------------------------------------- LLM pass


async def test_llm_influence_is_validated(fake_agency_case: Case, ctx: AgentContext) -> None:
    reply = {
        "entries": [
            {
                "message_id": "msg_4",
                "facts": ["The agent says an in-person viewing is not possible."],
                "influence": [
                    {"kind": "authority", "quote": "I'm working abroad", "explanation": "Why."},
                    {"kind": "guilt", "quote": "this text is not in the message"},
                    {"kind": "desperation", "quote": "I can send a video"},  # wrong side
                    {"kind": "made_up", "quote": "I can send a video"},
                ],
            },
            {
                "message_id": "msg_6",
                "influence": [{"kind": "urgency", "quote": "I'd really like to see it first"}],
            },
            {"message_id": "msg_999", "influence": [{"kind": "urgency", "quote": "x"}]},
            {
                "message_id": "notes",
                "influence": [{"kind": "desperation", "quote": "running out of options"}],
            },
        ]
    }
    report = await EmotionClassifierAgent().run(fake_agency_case, with_llm(ctx, reply))
    found = ids(report)
    assert found["pressure_authority"].detail == "Why."
    assert "pressure_guilt" not in found
    assert [e.quote for e in found["pressure_urgency"].evidence] == [
        "Send the deposit today to hold it."
    ]
    facts = found["stated_facts"]
    assert facts.severity == "info" and "viewing is not possible" in facts.detail
    for f in report.findings:
        for ref in f.evidence:
            if ref.quote and ref.evidence_id not in ("student_notes", "listing"):
                assert any(ref.quote in m.text for m in fake_agency_case.messages)


async def test_llm_failure_falls_back_to_rules(fake_agency_case: Case, ctx: AgentContext) -> None:
    report = await EmotionClassifierAgent().run(fake_agency_case, with_llm(ctx, "not json"))
    assert report.status == AgentStatus.OK
    assert "pressure_scarcity" in ids(report)


# ---------------------------------------------------------------- pricing


@pytest.mark.parametrize(
    ("rent", "supports", "severity"),
    [
        (700, "suspicious", "medium"),  # 26% under the W12 room figure of 950
        (760, "suspicious", "low"),  # 20% under
        (850, "cleared", "info"),  # within 15%
        (1090, "cleared", "info"),
        (1300, "suspicious", "info"),  # above: shown, never moves the check
    ],
)
def test_price_thresholds(rent: int, supports: str, severity: str) -> None:
    f = pricing.price_finding(chat("a: hello", rent=rent, postcode="W12 8QT"))
    assert f is not None
    assert (f.supports, f.severity, f.check_id) == (supports, severity, "fair_price")
    assert "approximate" in f.detail


def test_whole_flat_is_compared_with_one_bed_figure() -> None:
    case = chat("a: It is a self-contained studio.", rent=1000, postcode="W12 8QT")
    f = pricing.price_finding(case)
    assert f is not None and f.severity == "medium" and "one-bed" in f.detail


def test_rent_and_postcode_can_come_from_the_chat() -> None:
    case = chat("s: Is the room at 12 Elm Road, W12 8QT free?", "a: Yes, £600 pcm.")
    f = pricing.price_finding(case)
    assert f is not None and f.severity == "medium"
    assert f.evidence[0].evidence_id == "ev_1" and f.evidence[0].quote == "£600 pcm"


def test_no_price_finding_without_rent_or_known_district() -> None:
    assert pricing.price_finding(chat("a: hello", postcode="W12 8QT")) is None
    assert pricing.price_finding(chat("a: hello", rent=900, postcode="ZZ1 1AA")) is None


def test_listing_changes_the_input_hash(fake_agency_case: Case) -> None:
    agent = EmotionClassifierAgent()
    before = hash_slice(agent.input_slice(fake_agency_case))
    assert fake_agency_case.listing is not None
    fake_agency_case.listing.rent_pcm = 600
    assert hash_slice(agent.input_slice(fake_agency_case)) != before

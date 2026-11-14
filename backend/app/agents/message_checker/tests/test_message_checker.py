import json

from app.agents.message_checker.agent import MessageCheckerAgent
from app.agents.message_checker.stub import MessageCheckerStub
from app.contracts import AgentReport, AgentStatus, Case, FactKey
from app.core.agent import AgentContext, hash_slice
from app.core.llm import FakeLLM

PROMPT_KEY = "rental scam signals"  # appears in prompts/extra_findings.md


def with_llm(ctx: AgentContext, reply: dict | str) -> AgentContext:
    text = reply if isinstance(reply, str) else json.dumps(reply)
    return AgentContext(
        llm=FakeLLM({PROMPT_KEY: text}),
        search=ctx.search,
        http=ctx.http,
        settings=ctx.settings,
        log=ctx.log,
    )


def ids(report: AgentReport) -> dict:
    return {f.id.split(":")[1]: f for f in report.findings}


async def test_stub_returns_valid_report(fake_agency_case: Case, ctx: AgentContext) -> None:
    agent = MessageCheckerStub()
    report = await agent.run(fake_agency_case, ctx)
    assert AgentReport.model_validate(report.model_dump()) == report
    assert report.agent == "message_checker"
    assert report.version.endswith("-stub")
    assert report.input_hash == hash_slice(agent.input_slice(fake_agency_case))


async def test_fake_agency_hits_a_hard_flag(fake_agency_case: Case, ctx: AgentContext) -> None:
    report = await MessageCheckerAgent().run(fake_agency_case, ctx)
    assert report.status == AgentStatus.OK
    found = ids(report)
    assert found["payment_before_viewing"].hard_flag
    assert {"landlord_abroad", "viewing_refused"} <= set(found)
    assert all(f.supports == "suspicious" for f in report.findings)
    facts = {f.key: f.value for f in report.facts}
    assert (
        facts[FactKey.BANK_ACCOUNT].endswith("1234") and "0000" not in facts[FactKey.BANK_ACCOUNT]
    )
    assert facts[FactKey.RENT_PCM] == "850"


async def test_overseas_landlord_hits_hard_flags(
    overseas_landlord_case: Case, ctx: AgentContext
) -> None:
    found = ids(await MessageCheckerAgent().run(overseas_landlord_case, ctx))
    assert found["untraceable_payment"].hard_flag
    assert found["payment_before_viewing"].hard_flag
    assert {"landlord_abroad", "viewing_refused"} <= set(found)


async def test_genuine_flat_only_clears(genuine_flat_case: Case, ctx: AgentContext) -> None:
    report = await MessageCheckerAgent().run(genuine_flat_case, ctx)
    assert set(ids(report)) == {
        "viewing_completed",
        "payment_after_viewing_via_portal",
        "deposit_scheme_named",
    }
    assert all(f.supports == "cleared" and not f.hard_flag for f in report.findings)
    assert {f.key: f.value for f in report.facts}[FactKey.DEPOSIT] == "1384"


async def test_every_finding_quotes_a_real_message(
    fake_agency_case: Case, overseas_landlord_case: Case, genuine_flat_case: Case, ctx: AgentContext
) -> None:
    for case in (fake_agency_case, overseas_landlord_case, genuine_flat_case):
        report = await MessageCheckerAgent().run(case, ctx)
        for f in report.findings:
            assert f.evidence
            for ref in f.evidence:
                assert any(ref.quote and ref.quote in m.text for m in case.messages)


async def test_llm_adds_findings_but_never_hard_flags(
    genuine_flat_case: Case, ctx: AgentContext
) -> None:
    reply = {
        "flags": [
            {
                "flag": "untraceable_payment",
                "message_id": "msg_4",
                "quote": "through our online portal",
                "explanation": "Test.",
                "confidence": 0.99,
            }
        ],
        "facts": [
            {"key": "landlord_name", "value": "Hannah", "message_id": "msg_2"},
            {"key": "landlord_name", "value": "Hannah Clarke", "message_id": "msg_2"},
            {"key": "rent_pcm", "value": "£1,200", "message_id": "msg_2"},
        ],
        "questions": ["Did you meet Hannah at the office?", "b", "c"],
    }
    report = await MessageCheckerAgent().run(genuine_flat_case, with_llm(ctx, reply))
    flag = ids(report)["untraceable_payment"]
    assert not flag.hard_flag and flag.confidence == 0.8
    # a real flag on payment_safety removes the payment clear
    assert "payment_after_viewing_via_portal" not in ids(report)
    facts = [(f.key, f.value) for f in report.facts]
    assert (FactKey.LANDLORD_NAME, "Hannah Clarke") in facts
    assert (FactKey.LANDLORD_NAME, "Hannah") not in facts
    assert (FactKey.RENT_PCM, "1200") in facts
    assert len(report.questions) == 2


async def test_llm_findings_without_a_real_quote_are_dropped(
    genuine_flat_case: Case, ctx: AgentContext
) -> None:
    reply = {
        "flags": [
            {"flag": "escrow_story", "message_id": "msg_2", "quote": "Airbnb will hold the money"},
            {"flag": "made_up_flag", "message_id": "msg_2", "quote": "Hello Alex"},
            {
                "flag": "refuses_details",
                "message_id": "msg_2",
                "quote": "Hello Alex",
                "confidence": 0.3,
            },
            {
                "flag": "other",
                "check_id": "no_pressure",
                "message_id": "msg_2",
                "quote": "Hello Alex",
                "explanation": "Pressure.",
            },
        ]
    }
    report = await MessageCheckerAgent().run(genuine_flat_case, with_llm(ctx, reply))
    assert all(f.supports == "cleared" for f in report.findings)


async def test_llm_does_not_repeat_a_rule_finding(
    fake_agency_case: Case, ctx: AgentContext
) -> None:
    reply = {
        "flags": [
            {"flag": "landlord_abroad", "message_id": "msg_4", "quote": "I'm working abroad"},
            {
                "flag": "other",
                "check_id": "right_to_let",
                "message_id": "msg_5",
                "quote": "My colleague will hand over the keys",
                "explanation": "A third party controls access.",
            },
        ]
    }
    report = await MessageCheckerAgent().run(fake_agency_case, with_llm(ctx, reply))
    assert [f.id for f in report.findings].count("message_checker:landlord_abroad") == 1
    other = ids(report)["other_right_to_let"]
    assert other.severity == "medium" and other.check_id == "right_to_let"


async def test_llm_failure_falls_back_to_rules(fake_agency_case: Case, ctx: AgentContext) -> None:
    report = await MessageCheckerAgent().run(fake_agency_case, with_llm(ctx, "not json at all"))
    assert report.status == AgentStatus.OK
    assert ids(report)["payment_before_viewing"].hard_flag

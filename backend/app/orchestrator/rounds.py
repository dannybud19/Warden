"""Pure helpers that turn one reply or one analysis into round notes and a `RoundInput`.

Kept apart from `service.py` so the service is only about locks, saves and event order.
"""

import re
from collections.abc import Iterable, Mapping

from app.contracts import (
    Action,
    ActionStatus,
    AgentReport,
    AgentStatus,
    Case,
    Check,
    CheckId,
    CheckState,
    EvidenceKind,
    ScoreResult,
    Severity,
)
from app.orchestrator.checks import SEVERITY_RANK
from app.orchestrator.composer import CheckMove, RoundInput, RoundNote, validate_recap
from app.orchestrator.conversation import ParseResult

# A flagged answer about money: ask for the message itself so an agent can quote it (decision 19).
PAYMENT_WORDS = re.compile(r"\b(pay|paid|paying|payment|deposit|bank|transfer)", re.IGNORECASE)
NOT_RUN_MARKER = ":not-run-"
MAX_GROUNDING = 14
MAX_GROUNDING_FINDINGS = 6
MAX_DETAIL_WORDS = 30
MAX_HISTORY_TURNS = 6
MAX_TURN_WORDS = 60

# How an evidence id reads in a finding's detail, e.g. "'950' (from the contract)".
EVIDENCE_WORDS: dict[EvidenceKind, str] = {
    EvidenceKind.CHAT_SCREENSHOT: "a chat screenshot",
    EvidenceKind.CHAT_EXPORT: "your chats",
    EvidenceKind.EMAIL: "an email",
    EvidenceKind.CALL_RECORDING: "a call recording",
    EvidenceKind.VIDEO: "the viewing video",
    EvidenceKind.DOCUMENT: "a document",
    EvidenceKind.CONTRACT: "the contract",
    EvidenceKind.LISTING: "the listing",
}
_EVIDENCE_ID = re.compile(r"\bev_[A-Za-z0-9]+\b")


def label(check_id: CheckId) -> str:
    """Human label of a check: `landlord_identity` becomes "landlord identity"."""
    return check_id.value.replace("_", " ")


# How a recorded answer reads to the composer, so its acknowledgement matches what was stored.
RECORDED: dict[str, str] = {
    "clears": "you confirmed it, counted in your favour",
    "flags": "noted as a concern",
    "neutral": "noted, it changes nothing yet",
}

# What each agent reads, in the student's words (`checked_lines`).
READS: dict[str, str] = {
    "message_checker": "your messages",
    "emotion_classifier": "the tone of your messages",
    "contract_checker": "the contract",
    "companies_house": "the agency's company record",
}
MAX_CHECKED_TITLES = 2


def reply_notes(
    result: ParseResult,
    dropped: list[str],
    text: str,
    checks: Mapping[str, CheckId] | None = None,
) -> list[RoundNote]:
    """What the next round message should say about this reply. `checks` maps an action id to
    its check, so an answered step can be named ("in person viewing step: ...")."""
    notes: list[RoundNote] = []
    for update in result.updates:
        if update.action_id in dropped or not checks or update.action_id not in checks:
            continue
        how = "skipped" if update.status != "done" else RECORDED[update.outcome]
        notes.append(RoundNote(kind="answered", text=f"{label(checks[update.action_id])}: {how}"))
    if result.unmatched:
        notes.append(RoundNote(kind="unmatched"))
    if dropped:
        notes.append(RoundNote(kind="dropped"))
    notes.extend(RoundNote(kind="field_invalid", text=label) for label in result.invalid_fields)
    if result.question:
        notes.append(RoundNote(kind="question", text=result.question))
    applied = [u for u in result.updates if u.action_id not in dropped]
    if any(u.outcome == "flags" and PAYMENT_WORDS.search(u.quote or text) for u in applied):
        notes.append(RoundNote(kind="upload_hint"))
    return notes


def moved_checks(before: Mapping[CheckId, CheckState], after: Iterable[Check]) -> list[CheckMove]:
    """Checks whose state changed this round, in check order."""
    return [
        CheckMove(check=label(c.id), before=before[c.id].value, after=c.state.value)
        for c in after
        if c.id in before and before[c.id] != c.state
    ]


def not_run(reports: Mapping[str, AgentReport]) -> list[str]:
    """Agents that failed this round, and checks they reported as not run."""
    out: list[str] = []
    for report in reports.values():
        if report.status == AgentStatus.ERROR:
            out.append(f"{report.agent} did not finish")
        out.extend(f.title for f in report.findings if NOT_RUN_MARKER in f.id)
    return out


def checked_lines(
    new_reports: Mapping[str, AgentReport], previous: Mapping[str, AgentReport]
) -> list[str]:
    """What was read this round and what it found, e.g. "the contract: nothing flagged".

    Without this a contract upload that changes no check gave the student no feedback at all.
    Only agents whose findings changed since their last report are listed, so a rerun that finds
    the same things is not announced again. Titles the message may not repeat are left out.
    """
    medium = SEVERITY_RANK[Severity.MEDIUM]
    lines: list[str] = []
    for name, source in READS.items():
        report = new_reports.get(name)
        if report is None or report.status != AgentStatus.OK:
            continue
        before = previous.get(name)
        known = (
            {f.id for f in before.findings} if before and before.status == AgentStatus.OK else None
        )
        if known == {f.id for f in report.findings}:
            continue
        concerns = [
            f.title
            for f in report.findings
            if f.supports == "suspicious"
            and SEVERITY_RANK[f.severity] >= medium
            and not validate_recap(f.title)
        ]
        if concerns:
            found = "flagged: " + "; ".join(concerns[:MAX_CHECKED_TITLES])
        else:
            found = "nothing flagged"
        lines.append(f"{source}: {found}")
    return lines


def grounding(case: Case) -> list[str]:
    """What the composer may use to answer a student's question: the case's own findings first
    (suspicious, medium or worse, most serious first, with their detail so it can say *how*,
    e.g. which sources disagree on the rent), then every check's state. Capped so the prompt
    stays small."""
    medium = SEVERITY_RANK[Severity.MEDIUM]
    serious = sorted(
        (
            f
            for r in case.reports.values()
            for f in r.findings
            if f.supports == "suspicious" and SEVERITY_RANK[f.severity] >= medium
        ),
        key=lambda f: SEVERITY_RANK[f.severity],
        reverse=True,
    )
    findings = [_finding_line(case, f.title, f.detail) for f in serious]
    checks = [f"{label(c.id)}: {c.state.value}" for c in case.checks]
    unique = list(dict.fromkeys(findings))[:MAX_GROUNDING_FINDINGS]
    return [*unique, *checks][:MAX_GROUNDING]


def _finding_line(case: Case, title: str, detail: str) -> str:
    """ "Title: detail", with evidence ids in plain words and the detail capped."""
    kinds = {e.id: EVIDENCE_WORDS.get(e.kind, "a document") for e in case.evidence}
    readable = _EVIDENCE_ID.sub(lambda m: kinds.get(m.group(0), "an upload"), detail)
    return f"{title}: {_cap_words(readable, MAX_DETAIL_WORDS)}" if readable.strip() else title


def history(case: Case) -> list[str]:
    """The last few chat turns, so the composer can tell what a follow-up question refers to
    ("how do they disagree?" after "Two sources disagree on the rent.")."""
    who = {"student": "student", "orchestrator": "you"}
    return [
        f"{who[t.role]}: {_cap_words(t.text, MAX_TURN_WORDS)}"
        for t in case.chat[-MAX_HISTORY_TURNS:]
    ]


def _cap_words(text: str, limit: int) -> str:
    words = text.split()
    return " ".join(words) if len(words) <= limit else " ".join(words[:limit]) + "…"


def round_input(
    *,
    score_before: ScoreResult | None,
    score_after: ScoreResult,
    states_before: Mapping[CheckId, CheckState],
    checks_after: Iterable[Check],
    new_reports: Mapping[str, AgentReport],
    fresh: list[Action],
    actions: list[Action],
    recap_sent: bool,
    notes: list[RoundNote],
    case_grounding: list[str] | None = None,
    case_history: list[str] | None = None,
    previous_reports: Mapping[str, AgentReport] | None = None,
) -> RoundInput:
    """Everything the composer needs about one analysis. `actions` already includes `fresh`.

    `case_grounding` is sent only when a note carries a student question; `case_history` is
    always sent, so the message can acknowledge what the student just told us.
    """
    asked = any(n.kind == "question" for n in notes)
    return RoundInput(
        score_before=round(score_before.score) if score_before else None,
        score_after=round(score_after.score),
        moved=tuple(moved_checks(states_before, checks_after)),
        not_run=tuple(not_run(new_reports)),
        checked=tuple(checked_lines(new_reports, previous_reports or {})),
        new_actions=len(fresh),
        open_actions=sum(a.status == ActionStatus.OPEN for a in actions),
        recap_sent=recap_sent,
        notes=tuple(notes),
        grounding=tuple(case_grounding or []) if asked else (),
        history=tuple(case_history or []),
    )

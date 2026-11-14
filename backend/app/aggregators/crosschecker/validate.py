"""Turn the LLM's disagreements into findings only when both quotes check out; clean the recap."""

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.aggregators.crosschecker.constants import AGENT, ID_PREFIX, NOT_RUN_ID, RULE_IDS
from app.aggregators.crosschecker.models import Inconsistency, ReviewOutput, Side
from app.aggregators.crosschecker.rule_recap import rule_topics
from app.aggregators.crosschecker.sources import STUDENT, Source, quotable
from app.contracts import Category, CheckId, EvidenceRef, FactKey, Finding, Severity

MAX_KEPT = 5  # V7
MIN_QUOTE_CHARS = 3  # V3
MAX_QUOTE_CHARS = 200  # V3: a longer "quote" is a pasted excerpt, not a claim
SLUG_MAX_CHARS = 40
COLLISION_SUFFIX = "-2"  # keeps an LLM id off a rule finding's or the not-run finding's id
CONF_VERIFIED = 0.7  # both quotes verified: enough to flip a check at medium severity or above
CONF_STUDENT = 0.5  # one side is what the student typed, which is often approximate
MAX_RECAP_WORDS = 80
RECAP_TEMPLATE = (
    "A few details don't match between your documents: {topics}. "
    "Before paying anything, ask the agent to confirm the correct terms in writing."
)
MAX_TEMPLATE_TOPICS = 3

FRIENDLY_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "companies_house": "Agency check",
        "message_checker": "Your messages",
        "contract_checker": "The contract",
        "emotion_classifier": "Pressure check",
        "video_analysis": "Video check",
        "upload": "Your upload",
        STUDENT: "What you entered",
    }
)

_SEVERITIES: Mapping[str, Severity] = MappingProxyType(
    {"low": Severity.LOW, "medium": Severity.MEDIUM, "high": Severity.HIGH}
)
_DERIVED_KINDS = frozenset({"quote", "fact"})  # cut from a finding, whose Source lines apply

# normalise(): curly quotes, dashes and non-breaking spaces to their plain forms.
_PLAIN_CHARS: Mapping[int, str] = MappingProxyType(
    str.maketrans(
        {
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2013": "-",
            "\u2014": "-",
            "\u00a0": " ",
            "\u202f": " ",
        }
    )
)
_POUND_SPACE = re.compile(r"£\s+")
_WHITESPACE = re.compile(r"\s+")
_QUOTE_WRAPPERS = "\"'\u201c\u201d\u2018\u2019"
_ELLIPSES = ("...", "\u2026")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_TRAILING_ZERO_DECIMALS = re.compile(r"\.0{1,2}$")
_SOURCE_LINE = re.compile(r"^Source: \S.*$", re.MULTILINE)
_SLUG_JUNK = re.compile(r"[^a-z0-9]+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_PAYMENT_WORDS = re.compile(r"\b(?:pay|paying|payment|payments|bank|transfer|transfers)\b")


def _words(pattern: str) -> re.Pattern[str]:
    """A whole-word, case-insensitive match for any alternative in `pattern`."""
    return re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE)


# V5: the fact key a rule finding compares, by the words an LLM topic would use for it.
_RULE_FAMILIES: Mapping[str, re.Pattern[str]] = MappingProxyType(
    {
        FactKey.ADDRESS.value: _words(r"address(?:es)?|postcodes?"),
        FactKey.LANDLORD_NAME.value: _words(r"landlords?|owners?"),
        FactKey.COMPANY_NUMBER.value: _words(r"compan(?:y|ies)"),
        FactKey.RENT_PCM.value: _words(r"rents?"),
        FactKey.DEPOSIT.value: _words(r"deposits?"),
    }
)
# clean_recap(): a recap may only talk about topics the kept or rule findings are about.
_RECAP_FAMILIES: Mapping[str, re.Pattern[str]] = MappingProxyType(
    {
        "utilities": _words(r"utilit(?:y|ies)|bills?|council tax"),
        "rent": _words(r"rents?"),
        "deposit": _words(r"deposits?"),
        "address": _words(r"address(?:es)?|postcodes?"),
        "landlord": _words(r"landlords?|owners?"),
        "company": _words(r"compan(?:y|ies)"),
        "dates": _words(r"move[- ]in|start date|starts|available (?:from|on)|availability"),
        "payment": _words(r"banks?|personal accounts?|account numbers?|transfers?|sort codes?"),
    }
)
# Verdict words and legal advice (golden rule 9). Whole words, so "unsafe" and "safety" pass.
_BANNED = _words(
    r"safe(?:r|st|ly)?|scam(?:s|mer|mers|med|ming)?|fraud(?:s|ulent|ster|sters)?"
    r"|legit(?:imate|imately|imacy)?|guarantee(?:s|d)?|illegal(?:ly)?|sue(?:s|d)?|suing"
    r"|lawyers?|genuine(?:ly)?|fake(?:s|d)?"
)


@dataclass(frozen=True)
class _Verified:
    """An inconsistency whose two sides passed V1 to V3 and V5."""

    inconsistency: Inconsistency
    source_a: Source
    source_b: Source
    quote_a: str  # cleaned quote, verified against source_a
    quote_b: str
    finding_id: str


def to_findings(
    output: ReviewOutput,
    sources: list[Source],
    rule_findings: list[Finding],
    *,
    log: logging.Logger | None = None,
) -> tuple[list[Finding], list[Inconsistency]]:
    """The consistency findings for the inconsistencies that pass V1 to V7, and those kept."""
    by_id = {source.id: source for source in sources}
    rules = [finding for finding in rule_findings if finding.id in RULE_IDS]
    verified: list[_Verified] = []
    for inconsistency in output.inconsistencies:
        result = _verify(inconsistency, by_id, sources, rules)
        if isinstance(result, str):
            reason = result
        elif any(v.finding_id == result.finding_id for v in verified):
            reason = "V6: same topic as an earlier disagreement"
        elif len(verified) >= MAX_KEPT:
            reason = f"V7: already kept {MAX_KEPT}"
        else:
            _log_payment_check(result, log)
            verified.append(result)
            continue
        if log:
            log.info("cross-checker dropped %r: %s", inconsistency.topic, reason)
    findings = [_finding(v, sources) for v in verified]
    return findings, [v.inconsistency for v in verified]


def clean_recap(recap: str, kept: list[Inconsistency], rule_findings: list[Finding]) -> str | None:
    """The LLM recap made fit to show, the template if it breaks a rule, None if nothing kept."""
    if not kept:
        return None
    topics = rule_topics([f for f in rule_findings if f.supports == "suspicious"])
    fallback = template_recap([*topics, *(i.topic for i in kept)])
    text = " ".join(recap.split())
    if not text or _BANNED.search(normalise(text)) or not _topics_allowed(text, kept, topics):
        return fallback
    return _within_words(text, MAX_RECAP_WORDS) or fallback


def template_recap(topics: Iterable[str]) -> str:
    """The fixed recap (plan Appendix B) naming `topics`, used when the LLM's recap fails."""
    unique = list(dict.fromkeys(t.strip().lower() for t in topics if t.strip()))
    return RECAP_TEMPLATE.format(topics=_join_topics(unique))


def normalise(text: str) -> str:
    """Text as quotes are compared: lower case, plain quotes and dashes, '£ 60' as '£60', one
    space between words."""
    plain = text.lower().translate(_PLAIN_CHARS)
    return _WHITESPACE.sub(" ", _POUND_SPACE.sub("£", plain)).strip()


def clean_quote(quote: str) -> str:
    """The quote without surrounding whitespace, wrapping quote marks or ellipses."""
    text = quote.strip()
    while True:
        before = text
        text = text.strip(_QUOTE_WRAPPERS)
        for ellipsis in _ELLIPSES:
            text = text.removeprefix(ellipsis).removesuffix(ellipsis)
        text = text.strip()
        if text == before:
            return text


def slug(topic: str) -> str:
    """The id part for a topic: lower-case a-z0-9 words joined by '-', at most 40 chars."""
    joined = _SLUG_JUNK.sub("-", topic.lower()).strip("-")
    return joined[:SLUG_MAX_CHARS].strip("-")


def friendly_name(agent: str) -> str:
    """How a source's agent is named to the student (plan Appendix D)."""
    return FRIENDLY_NAMES.get(agent) or agent.replace("_", " ").title()


def _verify(
    inconsistency: Inconsistency,
    by_id: Mapping[str, Source],
    sources: list[Source],
    rules: list[Finding],
) -> _Verified | str:
    """The verified inconsistency, or why it is dropped (V1, V2, V3, verdict words, empty slug,
    V5)."""
    source_a, source_b = by_id.get(inconsistency.a.source_id), by_id.get(inconsistency.b.source_id)
    if source_a is None or source_b is None or source_a.id == source_b.id:
        return "V1: unknown source or both sides on one source"
    shown = " ".join([inconsistency.topic, inconsistency.a.claim, inconsistency.b.claim])
    if _BANNED.search(normalise(shown)):
        return "a verdict word in the topic or a claim"
    side_a = _resolve(inconsistency.a, source_a, sources)
    side_b = _resolve(inconsistency.b, source_b, sources)
    if side_a is None or side_b is None:
        return "V3: a quote is too short, too long or not in its source's evidence"
    (source_a, quote_a), (source_b, quote_b) = side_a, side_b
    if not source_a.evidence_id or not source_b.evidence_id:
        return "V1: a source has no evidence to cite"
    if source_a.agent == source_b.agent and source_a.evidence_id == source_b.evidence_id:
        return "V2: both sides come from the same agent and evidence"
    topic_slug = slug(inconsistency.topic)
    if not topic_slug:
        return "the topic has no usable words"
    if _repeats_rule(inconsistency.topic, quote_a, quote_b, rules):
        return "V5: repeats a rule finding"
    return _Verified(inconsistency, source_a, source_b, quote_a, quote_b, _finding_id(topic_slug))


def _resolve(side: Side, source: Source, sources: list[Source]) -> tuple[Source, str] | None:
    """The source the side's quote really comes from and the quote as written there (V3).

    The quote must be in the source's quotable text (`sources.quotable`), so labels and an
    agent's own words never pass as evidence. A side that points at a finding is moved to that
    agent's `quote` source holding the quote, which carries the quote's own evidence id.
    """
    quote = clean_quote(side.quote)
    needle = normalise(quote)
    if len(needle) < MIN_QUOTE_CHARS or len(quote) > MAX_QUOTE_CHARS:
        return None
    candidates = (
        [s for s in sources if s.kind == "quote" and s.agent == source.agent]
        if source.kind == "finding"
        else [source]
    )
    for candidate in candidates:
        text = quotable(candidate)
        if needle in normalise(text):
            return candidate, original_span(quote, text)
    return None


def original_span(quote: str, text: str) -> str:
    """The exact characters of `text` that `quote` matches once both are normalised.

    Evidence quotes must be real (golden rule 6) and the UI may search for them verbatim, so the
    LLM's re-typed quote ("all BILLS", straight apostrophes, "£60" for "£ 60") is replaced by the
    source's own wording. Falls back to `quote` if the span cannot be located.
    """
    if quote in text:
        return quote
    chars: list[str] = []  # `text` normalised one character at a time ...
    origin: list[int] = []  # ... and where each normalised character came from
    for index, char in enumerate(text):
        for plain in char.lower().translate(_PLAIN_CHARS):
            if plain.isspace():
                if not chars or chars[-1] in (" ", "£"):
                    continue
                plain = " "
            chars.append(plain)
            origin.append(index)
    needle = normalise(quote)
    start = "".join(chars).find(needle)
    if not needle or start < 0:
        return quote
    return text[origin[start] : origin[start + len(needle) - 1] + 1]


def _repeats_rule(topic: str, quote_a: str, quote_b: str, rules: list[Finding]) -> bool:
    """V5: a rule finding already flags this topic and both sides quote one of its values."""
    normal_topic = normalise(topic)
    families = {key for key, words in _RULE_FAMILIES.items() if words.search(normal_topic)}
    for rule in rules:
        if rule.id.removeprefix(ID_PREFIX) not in families:
            continue
        values = [ref.quote for ref in rule.evidence if ref.quote and ref.quote.strip()]
        if all(any(_mentions(q, v) for v in values) for q in (quote_a, quote_b)):
            return True
    return False


def _mentions(quote: str, value: str) -> bool:
    """The quote names the value: as a whole phrase, or (for a value with digits) by every one of
    its numbers, so '£1,200.00' matches '1200'."""
    phrase = normalise(value)
    if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalise(quote)):
        return True
    numbers = _numbers(value)
    return bool(numbers) and numbers <= _numbers(quote)


def _numbers(text: str) -> frozenset[str]:
    """The numbers in `text`, without thousands commas, '.00' decimals or leading zeros."""
    found: set[str] = set()
    for token in _NUMBER.findall(text):
        plain = _TRAILING_ZERO_DECIMALS.sub("", token.replace(",", ""))
        found.add(plain.lstrip("0") or "0")
    return frozenset(found)


def _finding_id(topic_slug: str) -> str:
    """`crosscheck:<slug>`, moved off the ids of rule findings and the not-run finding."""
    finding_id = f"{ID_PREFIX}{topic_slug}"
    if finding_id in RULE_IDS or finding_id == NOT_RUN_ID:
        return finding_id + COLLISION_SUFFIX
    return finding_id


def _log_payment_check(verified: _Verified, log: logging.Logger | None) -> None:
    """V4: a payment topic filed under another check is kept as the LLM chose, but logged."""
    inconsistency = verified.inconsistency
    if (
        log
        and inconsistency.check_id != CheckId.PAYMENT_SAFETY
        and _PAYMENT_WORDS.search(normalise(inconsistency.topic))
    ):
        log.info(
            "cross-checker kept payment topic %r under %s",
            inconsistency.topic,
            inconsistency.check_id.value,
        )


def _finding(verified: _Verified, sources: list[Source]) -> Finding:
    """The consistency finding for one verified inconsistency (plan section 10)."""
    inconsistency = verified.inconsistency
    a, b = verified.source_a, verified.source_b
    who_a, who_b = friendly_name(a.agent), friendly_name(b.agent)
    topic = _capitalised(inconsistency.topic.strip())
    title = (
        f"{topic}: two parts of {who_a[:1].lower()}{who_a[1:]} disagree"
        if who_a == who_b
        else f"{topic}: {who_a} and {who_b} disagree"
    )
    why = inconsistency.why_it_matters.strip()
    if _BANNED.search(normalise(why)):
        why = ""  # shown to the student: no verdict words, even in the explanation
    detail = (
        f'{who_a} says {_claim(inconsistency.a)} ("{verified.quote_a}"). '
        f'{who_b} says {_claim(inconsistency.b)} ("{verified.quote_b}").'
        + (f" {why}" if why else "")
    )
    lines = list(dict.fromkeys([*_source_lines(a, sources), *_source_lines(b, sources)]))
    if lines:
        detail += "\n" + "\n".join(lines)
    student_side = STUDENT in (a.agent, b.agent)
    return Finding(
        id=verified.finding_id,
        agent=AGENT,
        check_id=inconsistency.check_id,
        title=title,
        detail=detail,
        category=Category.CONSISTENCY,
        severity=_SEVERITIES.get(inconsistency.severity, Severity.HIGH),
        confidence=CONF_STUDENT if student_side else CONF_VERIFIED,
        evidence=[
            EvidenceRef(evidence_id=a.evidence_id, quote=verified.quote_a),
            EvidenceRef(evidence_id=b.evidence_id, quote=verified.quote_b),
        ],
        supports="suspicious",
        hard_flag=False,
    )


def _claim(side: Side) -> str:
    """The side's claim without surrounding whitespace or a final full stop."""
    return side.claim.strip().removesuffix(".")


def _capitalised(text: str) -> str:
    """`text` with its first letter upper-cased and the rest unchanged."""
    return text[:1].upper() + text[1:]


def _source_lines(source: Source, sources: list[Source]) -> list[str]:
    """The `Source: <url>` lines behind a side: its own text's, and for a quote or fact, those of
    the agent's findings on the same evidence (where the URL is written)."""
    texts = [source.text]
    if source.kind in _DERIVED_KINDS:
        texts += [
            other.text
            for other in sources
            if other.kind == "finding"
            and other.agent == source.agent
            and other.evidence_id == source.evidence_id
        ]
    return [line.strip() for text in texts for line in _SOURCE_LINE.findall(text)]


def _topics_allowed(text: str, kept: list[Inconsistency], rule_topic_names: list[str]) -> bool:
    """Every topic family the recap mentions also appears in what was kept or in a rule topic."""
    allowed_text = normalise(
        " ".join(
            [
                *rule_topic_names,
                *(
                    part
                    for i in kept
                    for part in (i.topic, i.a.claim, i.a.quote, i.b.claim, i.b.quote)
                ),
                *(i.why_it_matters for i in kept),
            ]
        )
    )
    normal = normalise(text)
    return all(
        words.search(allowed_text) for words in _RECAP_FAMILIES.values() if words.search(normal)
    )


def _within_words(text: str, limit: int) -> str | None:
    """`text` if it has at most `limit` words, else its leading whole sentences that fit (None
    when even the first sentence is too long)."""
    if len(text.split()) <= limit:
        return text
    kept: list[str] = []
    count = 0
    for sentence in _SENTENCE_BREAK.split(text):
        count += len(sentence.split())
        if count > limit:
            break
        kept.append(sentence)
    return " ".join(kept) or None


def _join_topics(topics: list[str]) -> str:
    """'a', 'a and b', 'a, b and c', or 'a, b, c and more' past three topics."""
    if len(topics) > MAX_TEMPLATE_TOPICS:
        return ", ".join(topics[:MAX_TEMPLATE_TOPICS]) + " and more"
    if len(topics) <= 1:
        return "".join(topics)
    return ", ".join(topics[:-1]) + " and " + topics[-1]


def not_run_finding(reason: str) -> Finding:
    """The info finding that says the LLM pass failed this time (plan Appendix C)."""
    return Finding(
        id=NOT_RUN_ID,
        agent=AGENT,
        check_id=CheckId.CONTRACT_CONSISTENCY,
        title="Cross-check could not run this time",
        detail=(
            f"The comparison between agents' reports failed ({reason}). "
            "Rule-based checks still ran."
        ),
        category=Category.CONSISTENCY,
        severity=Severity.INFO,
        confidence=0.0,
        evidence=[],
        supports="suspicious",
        hard_flag=False,
    )


def is_llm_finding(finding: Finding) -> bool:
    """True for a consistency finding the LLM pass made (not a rule finding, not `not-run`)."""
    return (
        finding.id.startswith(ID_PREFIX) and finding.id not in RULE_IDS and finding.id != NOT_RUN_ID
    )

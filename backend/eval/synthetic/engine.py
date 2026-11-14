"""Render sources from shared facts, keeping ground truth outside agent inputs."""

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from string import Formatter
from typing import Any

from pydantic import TypeAdapter

from app.contracts import (
    Case,
    Check,
    CheckId,
    Evidence,
    EvidenceKind,
    Landlord,
    Listing,
    Message,
    StudentContext,
)
from eval.synthetic.models import (
    FAMILIES,
    CaseEntry,
    Comparison,
    Manifest,
    ManifestExpectation,
    Paraphrase,
    Scenario,
    SourceReference,
)

DATA_DIR = Path(__file__).parent
CREATED_AT = datetime(2026, 11, 14, 12, tzinfo=UTC)
CONTRACT = """Tenancy agreement
Property: {address}
Landlord: {owner_name}
Letting representative: {agent_name}, acting for {company_name}.
Rent: GBP {rent} per calendar month.
Tenancy deposit: GBP {deposit}.
The tenancy is periodic from {start_date}.
The tenant may end the tenancy with two months' written notice.
No administration fee is payable.
The landlord is responsible for structural and heating repairs, except tenant-caused damage.
"""


def digest(value: bytes) -> str:
    """Return a stable content fingerprint for provenance and integrity checks."""
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: Any) -> bytes:
    """Serialize without timestamps or platform-dependent newlines."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def identifier(seed: int, key: str, prefix: str = "c") -> str:
    """Use opaque IDs so filenames cannot reveal scenario labels to agents."""
    return f"{prefix}_{digest(f'{seed}:{key}'.encode())[:12]}"


def _fields(text: str) -> Counter[str]:
    return Counter(field for _, field, _, _ in Formatter().parse(text) if field is not None)


def _literals(text: str) -> Counter[str]:
    return Counter(re.findall(r"\b\d[\d,.]*\b|https?://\S+", text))


def apply_paraphrase(base: Scenario, paraphrase: Paraphrase) -> Scenario:
    """Apply reviewed wording edits; reject changed literal facts or placeholder roles."""
    changed = base.model_copy(deep=True)
    seen: set[int] = set()
    for rewrite in paraphrase.rewrites:
        index = rewrite.message_index
        if index in seen or index >= len(base.messages):
            raise ValueError(f"Invalid/duplicate message index in paraphrase of {base.key}.")
        seen.add(index)
        original = base.messages[index].text
        if _fields(original) != _fields(rewrite.text) or _literals(original) != _literals(
            rewrite.text
        ):
            raise ValueError(f"Paraphrase changes a literal fact or placeholder in {base.key}.")
        if original == rewrite.text:
            raise ValueError(f"Paraphrase must actually change wording in {base.key}.")
        changed.messages[index].text = rewrite.text
    expected_quotes = {e.quote for e in base.expectations}
    if not set(paraphrase.quote_replacements).issubset(expected_quotes):
        raise ValueError(f"Unknown expected quote in paraphrase of {base.key}.")
    for expectation in changed.expectations:
        expectation.quote = paraphrase.quote_replacements.get(expectation.quote, expectation.quote)
    changed.key = base.key + "_rewrite"
    changed.parent_key = base.key
    changed.variant = "paraphrase"
    return changed


def load_scenarios(data_dir: Path = DATA_DIR, *, paraphrases: bool = True) -> list[Scenario]:
    """Load author-reviewed catalogue data, preserving independent normative expectations."""
    adapter = TypeAdapter(list[Scenario])
    core = adapter.validate_json((data_dir / "catalogue.json").read_bytes())
    extras = adapter.validate_json((data_dir / "extras.json").read_bytes())
    if len(core) != 24 or len(extras) != 8:
        raise ValueError("Expected 24 core scenarios and 8 compound/robustness scenarios.")
    for family in FAMILIES:
        variants = [s.variant for s in core if s.family == family]
        if Counter(variants) != Counter(["concern", "genuine", "unresolved"]):
            raise ValueError(f"Missing or duplicate core variant for {family}.")
    if Counter(s.variant for s in extras) != Counter({"compound": 4, "robustness": 4}):
        raise ValueError("Expected four compound and four robustness scenarios.")
    scenarios = core + extras
    if paraphrases:
        edits = TypeAdapter(list[Paraphrase]).validate_json(
            (data_dir / "paraphrases.json").read_bytes()
        )
        if len(edits) != 8 or len({p.base_key for p in edits}) != 8:
            raise ValueError("Expected eight distinct paraphrase parents.")
        by_key = {s.key: s for s in core}
        for edit in edits:
            if edit.base_key not in by_key:
                raise ValueError(f"Paraphrase parent is absent: {edit.base_key}")
            scenarios.append(apply_paraphrase(by_key[edit.base_key], edit))
    if len({s.key for s in scenarios}) != len(scenarios):
        raise ValueError("Scenario keys must be unique.")
    return scenarios


def facts_for(seed: int, group: str) -> dict[str, str]:
    """Assign the same fictional literals to every meaningful variant in a family."""
    code = int(digest(f"{seed}:{group}".encode())[:8], 16)
    return {
        "owner_name": "Mira Vale",
        "agent_name": "Rowan Pike",
        "student_name": "Alex Reed",
        "company_name": "Northbank Example Lettings Ltd",
        "company_number": f"{code % 100_000_000:08d}",
        "address": f"Flat 2, {10 + code % 90} Example Mews, London W12 8QT",
        "rent": "600" if group == "deceptive_short_let" else "1300",
        "deposit": "690" if group == "deceptive_short_let" else "1500",
        "account_suffix": f"{code % 10000:04d}",
        "listing_url": f"https://listings.example/homes/{code % 10000}",
        "payment_url": f"https://portal.northbank.example/booking/{code % 10000}",
        "start_date": "1 December 2026",
        "viewing_date": "15 November 2026 at 16:00",
        "deadline": "16 November 2026 at 18:00",
    }


def _render(value: Any, facts: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format_map(facts)
    if isinstance(value, list):
        return [_render(item, facts) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, facts) for key, item in value.items()}
    return value


def _http_routes(records: list[dict[str, Any]], facts: dict[str, str]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for record in records:
        status = {"found": 200, "not_found": 404, "unavailable": 503}[record["outcome"]]
        routes.append(
            {
                "method": "GET",
                "url": record["url"],
                "status": status,
                "json": {"title": record["title"], "content": record["snippet"]},
            }
        )
        if (
            record.get("company_status")
            or "register" in record["key"]
            or "registry" in record["key"]
        ):
            profile = {
                "company_name": facts["company_name"],
                "company_number": facts["company_number"],
                "company_status": record.get("company_status"),
            }
            routes.append(
                {
                    "method": "GET",
                    "url": "https://api.company-information.service.gov.uk/"
                    f"company/{facts['company_number']}",
                    "status": status,
                    "json": profile if status == 200 else {"error": record["outcome"]},
                }
            )
    return routes


def render_scenario(spec: Scenario, seed: int) -> tuple[CaseEntry, dict[str, bytes]]:
    """Produce input files and evaluator-only expectations from one scenario specification."""
    facts = facts_for(seed, spec.family)
    if spec.viewing_completed:
        facts["viewing_date"] = "13 November 2026 at 16:00"
    if spec.key.startswith("fake_agency_genuine"):
        facts["deadline"] = "14 November 2026 at 18:00"
    rendered = Scenario.model_validate(_render(spec.model_dump(mode="json"), facts))
    case_id = identifier(seed, spec.key)
    chat_id, contract_id, listing_id = (f"{case_id}_e{i}" for i in range(1, 4))
    chat = (
        "\n".join(
            f"{facts['student_name'] if m.sender == 'student' else facts['agent_name']}: {m.text}"
            for m in rendered.messages
        )
        + "\n"
    )
    contract = (CONTRACT.format_map(facts) + rendered.contract_extra).rstrip() + "\n"
    listing_text = (
        f"Room to rent: {facts['address']}\nAdvert URL: {facts['listing_url']}\n"
        f"Rent: GBP {facts['rent']} per calendar month.\nTenancy deposit: GBP {facts['deposit']}.\n"
    )
    sources = {"chat.txt": chat, "contract.txt": contract, "listing.txt": listing_text}
    case = Case(
        case_id=case_id,
        created_at=CREATED_AT,
        student=StudentContext(budget_pcm=1500, move_in_date=date(2026, 12, 1)),
        listing=Listing(
            url=facts["listing_url"],
            platform="rental listing",
            address=facts["address"],
            postcode="W12 8QT",
            rent_pcm=int(facts["rent"]),
            deposit=int(facts["deposit"]),
        ),
        landlord=Landlord(
            name=facts["owner_name"],
            company_name=facts["company_name"],
            company_number=facts["company_number"] if facts["company_number"] in chat else None,
        ),
        evidence=[
            Evidence(
                id=chat_id,
                kind=EvidenceKind.CHAT_EXPORT,
                uploaded_at=CREATED_AT,
                filename="chat.txt",
                extracted_text=chat,
            ),
            Evidence(
                id=contract_id,
                kind=EvidenceKind.CONTRACT,
                uploaded_at=CREATED_AT,
                filename="contract.txt",
                extracted_text=contract,
            ),
            Evidence(
                id=listing_id,
                kind=EvidenceKind.LISTING,
                uploaded_at=CREATED_AT,
                filename="listing.txt",
                extracted_text=listing_text,
            ),
        ],
        messages=[
            Message(
                id=f"{case_id}_m{i}",
                evidence_id=chat_id,
                sender=m.sender,
                sent_at=CREATED_AT - timedelta(minutes=len(rendered.messages) - i + 1),
                channel="whatsapp",
                text=m.text,
            )
            for i, m in enumerate(rendered.messages, 1)
        ],
        checks=[Check(id=check_id) for check_id in CheckId],
    )
    external = [e.model_dump(mode="json") for e in rendered.external]
    for i, record in enumerate(external, 1):
        record["id"] = f"{case_id}_x{i}"
        if "register" in record["key"] or "registry" in record["key"]:
            record["query_alternatives"] = [[facts["company_number"]], [facts["company_name"]]]
    external_bundle = {
        "schema_version": "1.0",
        "records": external,
        "http_routes": _http_routes(external, facts),
        "unmatched_request": "error",
        "live_network_allowed": False,
    }
    expectations = []
    for exp in rendered.expectations:
        candidates = (
            {chat_id: chat}
            if exp.source == "chat"
            else {contract_id: contract}
            if exp.source == "contract"
            else {e["id"]: e["snippet"] for e in external}
        )
        refs = [
            SourceReference(source=key, quote=exp.quote)
            for key, value in candidates.items()
            if exp.quote in value
        ]
        if not refs:
            raise ValueError(
                f"Unsupported {exp.source} expectation quote in {spec.key}: {exp.quote}"
            )
        expectations.append(
            ManifestExpectation(
                check_id=exp.check_id,
                topic=exp.topic,
                stance=exp.stance,
                evidence=refs,
                explanation=exp.explanation,
            )
        )
    contents = {name: text.encode("utf-8") for name, text in sources.items()}
    contents["case.json"] = json_bytes(case.model_dump(mode="json"))
    contents["external.json"] = json_bytes(external_bundle)
    follow = rendered.follow_up
    if follow:
        contents["follow_up.txt"] = (follow.text.rstrip() + "\n").encode("utf-8")
    reviewers = {
        "Bill"
        if e.check_id in {CheckId.CONTRACT_CONSISTENCY, CheckId.DEPOSIT_PROTECTION}
        else "Georgi"
        if e.check_id
        in {
            CheckId.PAYMENT_SAFETY,
            CheckId.NO_PRESSURE,
            CheckId.FAIR_PRICE,
            CheckId.IN_PERSON_VIEWING,
        }
        else "Danny"
        for e in expectations
    }
    if any(
        e.check_id == CheckId.CONTRACT_CONSISTENCY and e.source != "contract"
        for e in rendered.expectations
    ):
        reviewers.add("Danny")
    entry = CaseEntry(
        case_id=case_id,
        group_id=identifier(seed, spec.family, "g"),
        family=spec.family,
        variant=spec.variant,
        parent_case_id=identifier(seed, spec.parent_key) if spec.parent_key else None,
        truth=spec.truth,
        files={name: f"cases/{case_id}/{name}" for name in contents},
        sha256={name: digest(value) for name, value in contents.items()},
        expectations=expectations,
        forbidden_assertions=rendered.forbidden_assertions,
        allowed_outcomes=rendered.allowed_outcomes,
        commitments=rendered.commitments,
        follow_up_trigger={"check_id": follow.check_id.value, "topic": follow.topic}
        if follow
        else None,
        follow_up_expected_change=follow.expected_change if follow else None,
        follow_up_available_at=follow.available_at if follow else None,
        reviewers=sorted(reviewers),
        wording_provenance=(
            "codex_authored_paraphrase; owner_review_pending"
            if spec.parent_key
            else "codex_authored_template"
        ),
    )
    return entry, {entry.files[name]: value for name, value in contents.items()}


def comparisons_for(entries: list[CaseEntry]) -> list[Comparison]:
    """Describe factual contrasts and wording invariance without putting labels in inputs."""
    controls = {e.family: e for e in entries if e.variant == "genuine"}
    comparisons = []
    for entry in entries:
        if entry.parent_case_id:
            comparisons.append(
                Comparison(
                    baseline_case_id=entry.parent_case_id,
                    variant_case_id=entry.case_id,
                    kind="wording_only",
                    expected_behavior="Preserve topics, uncertainty and outcomes under rewording.",
                )
            )
        elif entry.variant in {"concern", "unresolved"}:
            comparisons.append(
                Comparison(
                    baseline_case_id=controls[entry.family].case_id,
                    variant_case_id=entry.case_id,
                    kind="meaningful_change",
                    expected_behavior=(
                        "Detect specified concerns while avoiding the control's false positives."
                        if entry.variant == "concern"
                        else "Ask for missing evidence; uncertainty alone does not establish fraud."
                    ),
                )
            )
    return comparisons


def source_fingerprints() -> dict[str, str]:
    """Hash canonical source JSON so Windows line endings cannot change provenance."""
    return {
        name: digest(json_bytes(json.loads((DATA_DIR / name).read_bytes())))
        for name in ("catalogue.json", "extras.json", "paraphrases.json")
    }


def build_dataset(seed: int = 20261114, *, paraphrases: bool = True) -> dict[str, bytes]:
    """Assemble the complete reproducible dataset entirely in memory, without I/O clients."""
    specs = load_scenarios(paraphrases=paraphrases)
    artifacts: dict[str, bytes] = {}
    entries = []
    for spec in specs:
        entry, files = render_scenario(spec, seed)
        entries.append(entry)
        artifacts.update(files)
    manifest = Manifest(
        seed=seed,
        source_sha256=source_fingerprints(),
        cases=entries,
        comparisons=comparisons_for(entries),
        notes=[
            "All cases are development fixtures; no held-out accuracy claim.",
            "Truth is distinct from the conclusions justified by uploaded evidence.",
            "Pending is a runner outcome, not a CheckState or a declaration of genuineness.",
            "Agent-owner review of normative expectations remains pending.",
            "Deliver follow-up text only after a matching question; never inject outcomes.",
            "External fixture gaps must fail explicitly; never fall back to the live network.",
            "Numeric scores are not fraud probabilities and do not directly determine verdicts.",
        ],
    )
    artifacts["manifest.json"] = json_bytes(manifest.model_dump(mode="json"))
    artifacts["labels.json"] = json_bytes({e.case_id: e.truth for e in entries})
    artifacts[".gitattributes"] = b"*.json text eol=lf\n*.txt text eol=lf\n"
    return artifacts

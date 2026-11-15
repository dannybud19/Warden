"""Write and validate generated datasets without deleting unrelated files."""

import json
from collections import Counter
from pathlib import Path

from app.contracts import Case, CheckId, CheckState
from eval.synthetic.engine import build_dataset, digest, source_fingerprints
from eval.synthetic.external import validate_external_bundle
from eval.synthetic.models import FAMILIES, Manifest


def contained_path(root: Path, relative: str) -> Path:
    """Reject absolute paths, traversal and symlinks outside the dataset."""
    if Path(relative).is_absolute():
        raise ValueError("Dataset paths must be relative.")
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def validate_dataset(root: Path, *, require_current_sources: bool = True) -> Manifest:
    """Validate fresh state, source integrity and grounded expectations for every case."""
    manifest = Manifest.model_validate_json((root / "manifest.json").read_bytes())
    if require_current_sources and manifest.source_sha256 != source_fingerprints():
        raise ValueError("Source catalogue changed; regenerate the dataset before evaluation.")
    entries = {entry.case_id: entry for entry in manifest.cases}
    if len(entries) != len(manifest.cases) or len(entries) not in {32, 40}:
        raise ValueError("Expected 32 or 40 uniquely identified development cases.")
    if not set(FAMILIES).issubset({entry.family for entry in entries.values()}):
        raise ValueError("Dataset is missing a required scam family.")
    for entry in entries.values():
        required_files = {"case.json", "chat.txt", "contract.txt", "listing.txt", "external.json"}
        if entry.follow_up_trigger:
            required_files.add("follow_up.txt")
        if set(entry.files) != required_files:
            raise ValueError(f"Missing or unexpected case artifacts: {entry.case_id}")
        if set(entry.sha256) != set(entry.files):
            raise ValueError(f"Incomplete integrity manifest for {entry.case_id}.")
        content: dict[str, bytes] = {}
        for name, relative in entry.files.items():
            if relative != f"cases/{entry.case_id}/{name}" or Path(name).name != name:
                raise ValueError(f"Invalid artifact path for {entry.case_id}.")
            content[name] = contained_path(root, relative).read_bytes()
            if digest(content[name]) != entry.sha256[name]:
                raise ValueError(f"Content fingerprint mismatch: {relative}")
        raw = json.loads(content["case.json"])
        case = Case.model_validate(raw)
        if case.model_dump(mode="json") != raw:
            raise ValueError(f"Unexpected fields or noncanonical Case data: {entry.case_id}")
        if (
            case.case_id != entry.case_id
            or case.status != "open"
            or any((case.actions, case.reports, case.score_history, case.decision))
        ):
            raise ValueError(f"Case must contain fresh inputs only: {entry.case_id}")
        if Counter(check.id for check in case.checks) != Counter(CheckId):
            raise ValueError(f"Case must initialise all eight checks: {entry.case_id}")
        if any(
            c.state != CheckState.UNVERIFIED or c.clear_confidence != 0 or c.finding_ids or c.reason
            for c in case.checks
        ):
            raise ValueError(f"Case must not initialise check conclusions: {entry.case_id}")
        evidence = {e.id: e for e in case.evidence}
        if len(evidence) != len(case.evidence):
            raise ValueError(f"Duplicate evidence IDs: {entry.case_id}")
        if Counter(e.filename for e in case.evidence) != Counter(
            ["chat.txt", "contract.txt", "listing.txt"]
        ):
            raise ValueError(f"Case must include exactly the three input sources: {entry.case_id}")
        for item in case.evidence:
            if item.filename not in {"chat.txt", "contract.txt", "listing.txt"}:
                raise ValueError("Only ordinary input source names belong in Case evidence.")
            if item.extracted_text != content[item.filename].decode("utf-8"):
                raise ValueError(f"Raw source differs from Case evidence: {entry.case_id}")
        if len({m.id for m in case.messages}) != len(case.messages):
            raise ValueError(f"Duplicate message IDs: {entry.case_id}")
        for message in case.messages:
            if message.evidence_id not in evidence or message.text not in (
                evidence[message.evidence_id].extracted_text or ""
            ):
                raise ValueError(f"Message does not cite its actual source: {entry.case_id}")
            if message.sent_at and message.sent_at > case.created_at:
                raise ValueError(f"A message cannot postdate the initial snapshot: {entry.case_id}")
        external = json.loads(content["external.json"])
        validate_external_bundle(external)
        records = external["records"]
        if len({record["id"] for record in records}) != len(records):
            raise ValueError(f"Duplicate external source IDs: {entry.case_id}")
        sources = {e.id: e.extracted_text or "" for e in case.evidence}
        sources.update({record["id"]: record["snippet"] for record in records})
        for expectation in entry.expectations:
            if not expectation.evidence:
                raise ValueError("Every expectation must identify supporting text.")
            for ref in expectation.evidence:
                if not ref.quote.strip() or ref.quote not in sources.get(ref.source, ""):
                    raise ValueError(f"Unsupported expectation evidence: {entry.case_id}")
        if bool(entry.follow_up_trigger) != ("follow_up.txt" in content):
            raise ValueError(f"Follow-up input/trigger mismatch: {entry.case_id}")
        if entry.follow_up_trigger and (
            entry.follow_up_available_at is None
            or entry.follow_up_available_at <= case.created_at
            or not entry.follow_up_expected_change
        ):
            raise ValueError(f"Follow-up must describe a later evidence round: {entry.case_id}")
        if entry.parent_case_id:
            parent = entries.get(entry.parent_case_id)
            if parent is None or (entry.group_id, entry.truth, entry.commitments) != (
                parent.group_id,
                parent.truth,
                parent.commitments,
            ):
                raise ValueError(f"Paraphrase changes its scenario commitments: {entry.case_id}")
            if entry.allowed_outcomes != parent.allowed_outcomes or [
                (e.check_id, e.topic, e.stance) for e in entry.expectations
            ] != [(e.check_id, e.topic, e.stance) for e in parent.expectations]:
                raise ValueError(f"Paraphrase changes normative expectations: {entry.case_id}")
    expected_comparisons = 24 if len(entries) == 40 else 16
    pairs = set()
    for comparison in manifest.comparisons:
        baseline = entries.get(comparison.baseline_case_id)
        variant = entries.get(comparison.variant_case_id)
        pair = (comparison.baseline_case_id, comparison.variant_case_id)
        if (
            baseline is None
            or variant is None
            or baseline.group_id != variant.group_id
            or baseline.case_id == variant.case_id
            or pair in pairs
        ):
            raise ValueError("Comparisons must identify distinct related cases exactly once.")
        pairs.add(pair)
        if comparison.kind == "wording_only" and variant.parent_case_id != baseline.case_id:
            raise ValueError("A wording comparison must identify its actual parent.")
    if len(pairs) != expected_comparisons:
        raise ValueError("Dataset does not include the expected controlled comparisons.")
    labels = json.loads((root / "labels.json").read_bytes())
    if labels != {entry.case_id: entry.truth for entry in manifest.cases}:
        raise ValueError("Labels and manifest disagree.")
    return manifest


def write_dataset(root: Path, seed: int = 20261114, *, paraphrases: bool = True) -> Manifest:
    """Generate reproducibly; refuse stale mixed datasets or overwriting changed inputs."""
    artifacts = build_dataset(seed, paraphrases=paraphrases)
    if root.exists() and any(root.iterdir()):
        old = validate_dataset(root, require_current_sources=False)
        if old.seed != seed or len(old.cases) != (40 if paraphrases else 32):
            raise ValueError(
                "Use a new empty output directory for a different seed or variant set."
            )
        old_files = {path for entry in old.cases for path in entry.files.values()}
        if old_files != set(artifacts) - {"manifest.json", "labels.json", ".gitattributes"}:
            raise ValueError("Case identities changed; use a new empty output directory.")
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in artifacts.items():
        path = contained_path(root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return validate_dataset(root)

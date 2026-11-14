# Contract checker

Owner: Bill (WS G). Scope decisions: [README_BILL.md](README_BILL.md).

The standalone checker accepts **text-based PDF bytes or UTF-8 plain text**, extracts text
itself, and returns structured JSON. It reviews the contract and explicit orchestrator
context. Cross-source comparisons belong to the separate comparison agent. The shared
upload pipeline has not been changed.

## Run a review

From `backend/`, with the project's existing dependencies installed:

```bash
uv run python -X utf8 -m eval.contract_checker --output .uploads/contract_checker/review.json review ../fixtures/cases/contract_checker/deposit_excess.txt --context ../fixtures/cases/contract_checker/context.json
```

The default run is offline and labelled `offline_rules_only`. It exercises extraction and
deterministic rules, reporting incomplete LLM coverage as `partial`. For a two-pass live
review, configure the local `ANTHROPIC_API_KEY` and run:

```bash
uv run python -X utf8 -m eval.contract_checker --live --output .uploads/contract_checker/review.json review path/to/contract.pdf --context path/to/context.json
```

Global options precede `review` or `evaluate`. The example context describes a fictional
ordinary private tenancy in England; use the actual known facts for other documents.
Without a context file, jurisdiction and tenancy type remain unknown and relevant concerns
are conditional. Outputs contain user evidence: keep real-case results out of committed files.

In this Windows workspace, the installed interpreter is
`D:\Warden\.venv\Scripts\python.exe`; from `backend/`, replace `uv run python` with
`..\.venv\Scripts\python.exe` if `uv` is not on PATH. `-X utf8` also avoids the existing
repository tests' dependency on Windows' default text encoding.

## Backend API

```python
from app.agents.contract_checker.models import ReviewContext
from app.agents.contract_checker.review import review_contract

result = await review_contract(
    data=contract_bytes,
    filename="agreement.pdf",
    context=ReviewContext.model_validate(orchestrator_context),
    ctx=agent_context,
)
payload = result.model_dump(mode="json")
```

`assessment_date` is required. Optional typed context includes jurisdiction, tenancy type,
agreement/start dates, signing status, rent basis and answers. Missing facts stay unknown;
free-form reassurance does not override typed applicability or quoted obligations.

## How the review works

1. Extract text using the existing `pypdf` dependency, retaining page and observed clause
   references. Plain text gets paragraph references where clause numbers are absent.
2. Extract terms and candidate issues with the injected LLM. Validate exact quotes against
   their claimed segments and amounts against actual monetary literals.
3. Run decimal calculations and explicit-clause rules. Check tenancy and holding deposits
   separately, advance rent, fees, tenancy/notice terms, internal contradictions, missing
   schedules and supported problematic obligations.
4. Have a second LLM pass challenge findings using the whole contract and maintained rules.
   Dismissals need substantive quoted counter-evidence. Disputed arithmetic becomes
   conditional rather than disappearing on a model vote.
5. Return issues, rule-level passes, questions, validated terms/facts, warnings and coverage.

Issues include evidence, page/clause references, legal links where applicable, assumptions,
uncertainty, importance, confidence, a question and a resolution condition. Documentary
conflicts and missing attachments do not invent legal citations. Importance is a fixed
rule-priority rubric: 0 for passes, 45 for missing schedules, up to 85 for payment concerns.
It is not a fraud probability. Confidence is an uncalibrated support indicator, reduced
when applicability is unresolved.

`complete` means extraction, Python's two deposit checks and the challenge pass covered
the selected rule set. The LLM reports coverage of the seven semantic checks; Python owns
numeric deposit coverage. `partial` exposes failed or
incomplete review and rejected unsupported items. `needs_input` identifies unreadable
documents; `unsupported` identifies known out-of-scope tenancies/jurisdictions. There is
no global safety or fraud verdict. Limits are 10 MiB, 50 PDF pages and 100,000 characters.
Encrypted PDFs, blank/image-only pages and unsupported formats are reported explicitly;
content is never silently truncated. OCR is not implemented.

## Legal scope and shared-report adapter

[legal_rules.json](legal_rules.json) contains official sources, applicability dates and a
14 November 2026 verification date. Review it when law or scope changes. Deposit-protection
information checks and ordinary costly-commitment advice are excluded. Passing a deposit
amount check does not verify its protection.

The existing `ContractCheckerAgent.run(case, ctx)` adapter accepts one already-extracted
contract. It exports concerns and facts through the frozen `AgentReport` schema. Conditional
concerns have low severity and no hard flag. Richer fields are available in standalone JSON;
the shared schema cannot yet represent all of them.

Rule-level passes use `supports="cleared"` in detailed JSON. The adapter does not promote
these to whole-check clears: the current orchestrator would otherwise mark all of
`deposit_protection` cleared solely because an amount meets a cap. Agree finer clearing
semantics with the orchestrator owner before that integration.

The stub still replays `fixtures/reports/contract_checker.json`, with quotes checked against
`fake_agency.json`. Set `AGENT_MODE_CONTRACT_CHECKER=real` to use the real compatibility
adapter in the app. Multiple contract versions need explicit selection; persistent history
and revision matching remain future work. IDs/hashes are deterministic for identical input,
not a cross-version matcher.

## Paired evaluation and cost

The paired text fixtures and expected categories are in `fixtures/cases/contract_checker/`.
Reproduce them with `uv run python -m eval.build_contract_pairs`, then explicitly run:

```bash
uv run python -X utf8 -m eval.contract_checker --live --output .uploads/contract_checker/live_pairs.json evaluate
```

The evaluation-only adapter records provider token usage for every paid attempt, including
JSON retries, and computes cost from published rates. Hidden SDK retries are disabled.
The persistent ledger is `backend/.uploads/contract_checker/usage.json`; reservations survive
failures/restarts, and a lock prevents concurrent processes from sharing a budget unsafely.
After an interrupted run, verify the process has stopped before removing its one lock file.

The authorised total is **GBP 5**, with an additional conservative **USD 5 ceiling**.
Input token counts plus headroom and maximum output are reserved before paid requests.
Unknown-cost failures keep their reservations. Output distinguishes measured USD cost,
unknown-cost reservations and estimated GBP conversion. Price/FX dates and sources are
recorded; refresh them for future experiments. Only models with verified price tables are
accepted. The ledger stores no prompts, document text or keys.

Results measure missed/unexpected rule types and latency on constructed development cases.
They do not establish real-world accuracy or independently validate LLM interpretations.
See the [first-version validation results](../../../eval/CONTRACT_CHECKER_RESULTS.md) for
the completed live run, cumulative cost and offline checks.

## Offline checks

```bash
uv run python -X utf8 -m pytest app/agents/contract_checker/tests eval/tests -q
make check
```

No dependencies or shared schemas were added. Tests cover PDF extraction, money boundaries,
frequency conversion, missing/unsupported input, invented quotes, review failures, supported
counter-evidence, reassurance, stub compatibility and budget reservations. Run evaluation
tests explicitly: the current default pytest paths collect `app/` and `tests/` only.

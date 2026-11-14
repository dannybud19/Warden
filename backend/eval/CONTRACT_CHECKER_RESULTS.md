# Contract checker: first-version validation

Run date: 14 November 2026. Model: `claude-sonnet-5-5`, using the configured Anthropic
key. Live requests succeeded. This confirms API access; the API response does not identify
whether Anthropic debited purchased or promotional credit.

The implementation and commands are in the
[checker README](../app/agents/contract_checker/README.md). The agreed input formats and
feature subset are in [README_BILL.md](../app/agents/contract_checker/README_BILL.md).

## Final paired evaluation

The [manifest](../../fixtures/cases/contract_checker/pairs.json) contains 26 synthetic text
contracts in 13 controlled pairs. Changes cover deposit and holding-deposit caps, fees,
advance rent, fixed terms, notice, schedules, repair obligations, explicit waivers,
reassurance, prompt injection, equivalent rent periods and contradictory rent amounts.

| Measure | Result |
| --- | ---: |
| Complete reviews | 26 / 26 |
| Missed expected issue categories | 0 |
| Unexpected issue categories | 0 |
| Reviews with warnings | 0 |
| Median review latency | 9.605 seconds |
| Mean review latency | 10.529 seconds |
| Slowest review | 17.500 seconds |
| Paid requests for the final suite | 52 |
| Input / output tokens for the final suite | 248,624 / 35,897 |
| Usage-derived cost for the final suite | USD 0.856218 |

Issues are counted as active concerns when they are confirmed or conditional and have
positive importance. Limited rule passes are evaluated separately from concerns. A complete
review means the selected checks and second pass ran; it does not mean the contract is
authentic or free of other problems.

These are development fixtures, not a held-out benchmark. The first run exposed an incorrect
coverage requirement: Python owned the two deposit calculations, but the pipeline required
the LLM to claim those checks as well. Coverage now combines Python's two checks with the
LLM's seven semantic checks. That run also correctly found an unintended contradiction in
the fixed-term fixture. The fixture was revised to isolate the fixed-term concern while
preserving an explicit early-termination right. The table reports the subsequent full run.

After the live run, offline revalidation checked all 107 extracted money terms and all 125
supporting/counter-evidence quotations against the actual fixture documents. Final guards
also reject malformed partial money literals and contradictory rent frequencies hidden by
short quotes. These guards accepted every retained term from the live suite.

Local detailed output: `backend/.uploads/contract_checker/live_pairs_verified.json`.
The earlier diagnostic run is `live_pairs.json`, and the initial smoke review is
`live_sample.json` in the same directory. These artifacts are deliberately gitignored.

## Total API usage and budget

The persistent ledger includes the smoke review and both paired runs, not just the best run:

| Measure | All implementation evaluation runs |
| --- | ---: |
| Paid requests | 106 |
| Input / output tokens | 505,622 / 75,663 |
| Cache creation / cache read tokens | 0 / 0 |
| Usage-derived USD cost | 1.767874 |
| Estimated GBP equivalent | 1.34 |
| Unknown-cost requests remaining | 0 |
| Authorised GBP budget | 5.00 |
| Additional USD ceiling | 5.00 |

Costs use provider-reported token usage and the published model prices, rather than an
account invoice. GBP is an estimate using the recorded 13 November ECB reference rate.
The [pricing source](https://platform.claude.com/docs/en/about-claude/pricing) and
[exchange-rate source](https://www.ecb.europa.eu/stats/eurofxref/), verification dates, token
counts and reservations are recorded in `backend/.uploads/contract_checker/usage.json`.
Keep this ledger when rerunning evaluation so cumulative spending remains bounded.

## Offline quality checks

Executed from `backend/` with the installed Python 3.12 environment:

```powershell
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check .
..\.venv\Scripts\python.exe -m pyright --pythonpath D:\Warden\.venv\Scripts\python.exe
..\.venv\Scripts\lint-imports.exe --no-cache --no-logo
..\.venv\Scripts\python.exe -X utf8 -m pytest -q app tests eval/tests
```

Results: lint and formatting passed; Pyright reported no errors or warnings; all three
import contracts passed; **140 tests passed and 3 existing tests were skipped**. These run
the repository's `make check` gates directly because `make` is unavailable in this Windows
environment, and include the evaluation tests beyond the default pytest collection paths.
Automated tests use fakes and do not make paid network requests.

## Remaining limits

- Text-based PDF and UTF-8 text only. PDF extraction is tested offline with actual generated
  PDF bytes; the paid paired evaluation used text fixtures. No OCR or scanned pages.
- Ordinary private tenancies in England, with legal sources verified on 14 November 2026.
  Unknown applicability produces conditional findings. The rule collection needs maintenance.
- Synthetic category matching does not establish real-world legal or scam-detection accuracy.
  The second pass uses the same model and is not independent legal verification.
- Upload-pipeline integration and persistent history across revised contracts remain future
  work. Stable identifiers currently support identical reruns only.
- Rich JSON exposes rule-level clears. The shared-report adapter avoids promoting a limited
  deposit-amount pass into a whole `deposit_protection` clear.

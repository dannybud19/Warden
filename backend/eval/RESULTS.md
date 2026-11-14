# Evaluation fixes — 14 November 2026

**All three targeted failure categories were addressed and all 40 cases rerun with the live API.**
This is a development comparison on the same unreviewed synthetic dataset, not an accuracy benchmark.
The [original run summary](runs/2026-11-14-system/summary.json) and raw outputs remain preserved.

## What changed

- Payment rules distinguish actual demands from denials, ordinary prepaid debit cards and payments
  explicitly due after viewing. Reassurance in one clause cannot hide a separate positive demand.
- Landlord-name facts require a full name explicitly assigned the owner/landlord role in the source
  message. A managing agent's name is not substituted. Being abroad alone is not a viewing barrier;
  local or completed viewing context no longer creates that warning. Removing these warnings does
  not verify identity or authority.
- Explicit timing such as “I will not arrange a viewing until you pay” is recognised. Under Bill's
  chosen policy, **all payment hard flags require a targeted student confirmation before closure**.
  Yes confirms that quoted concern; no, unsure, skipped or ambiguous answers preserve it and prompt
  clarification. Answers are bound to the particular finding and evidence. Company and contract
  hard flags retain their immediate behavior. The existing schemas and message-checker LLM pass are
  sufficient; a confirmation reply still triggers the normal agent rerun.

## Before and after

Counts are cases, including related wording variants. Categories overlap.

| Measure | Before | After |
| --- | ---: | ---: |
| Genuine cases incorrectly labelled `likely_scam` | 2/17 | **0/17** |
| Genuine cases with an untraceable-payment finding | 2 | **0** |
| Genuine cases with a landlord-name mismatch | 2 | **0** |
| Genuine cases with an abroad/viewing warning | 3 | **0** |
| Genuine cases with any suspicious check | 8/17 | **3/17** |
| Scam cases with at least one suspicious check | 11/11 | **11/11** |

The two reported timing failures, [transfer pressure](runs/2026-11-14-fixes/cases/c_a919eb7d9823.json)
and [fake platform link](runs/2026-11-14-fixes/cases/c_8e908328824a.json), now both carry explicit
pre-viewing payment candidates and targeted confirmation questions. They stay open until confirmation,
as requested. Five cases received payment-confirmation questions overall.

Final initial-round outcomes: **2 `likely_scam`, 38 pending**. Both immediate verdicts were scam cases
with company-register hard flags. All 17 genuine and all 12 uncertain cases remain pending. The fall
from five to two immediate scam verdicts reflects the new confirmation policy; it is not a detection
recall comparison. No scripted student replies were injected in the live run.

## Remaining limits

- The three remaining genuine-case warnings belong to the unchanged emotion/pricing checker:
  the explained low-rent case and its rewrite trigger the area-price rule; one genuine platform-link
  rewrite receives an authority-pressure warning. These remain follow-up work.
- Companies House still lacks fixtures in 33 cases; one case intentionally simulates an outage.
  Message, emotion and contract reports returned `ok` for all 40. Controlled external responses,
  unreviewed labels, related cases and one sample per case limit conclusions.
- This rerun compares application findings and outcomes directly. The separate LLM grader was not
  rerun; its previously documented grounding-score limitations remain. All eight wording pairs kept
  their verdict, while one pair differed in suspicious checks.

## Validation and reproducibility

Tested agent/orchestrator revision: **`33cb579`**, based on main **`881d157`**. The dataset fingerprint
matches the original run. **616 offline tests passed; 3 MongoDB-dependent tests were skipped.** Ruff,
format checking, Pyright and all three import-linter contracts passed. The service/reply tests cover
yes/no/unsure, skipped replies, changed evidence, direct-decision attempts and unrelated hard flags.

Live rerun: **201 successful model requests, USD 2.251340**, no failed or truncated requests.
This is token-based list-price cost before promotional credits/tax. It excludes the original
USD 4.186248 evaluation. Model: Claude Sonnet 5.5. Finished at **20:55:44 UTC**.

Artifacts: [comparison](runs/2026-11-14-fixes/comparison.json),
[summary](runs/2026-11-14-fixes/summary.json), [configuration](runs/2026-11-14-fixes/metadata.json),
[usage](runs/2026-11-14-fixes/usage.jsonl) and per-case/raw outputs in that run directory.

Run a fresh comparison from `backend/` using a new output directory:

```powershell
& D:\Warden\.venv\Scripts\python.exe -X utf8 -m eval.run --live --env-file D:\Warden\.env --output eval/runs/my-fix-check --parallel 3 --no-grade
```

The fixes, original dataset and both evaluations are together on **`fix/evaluation-findings`**, in
`D:\Warden\.worktrees\evaluation-fixes`. This branch has not been pushed.

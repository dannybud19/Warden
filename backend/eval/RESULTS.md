# Current-system evaluation — 15 November 2026

**All 40 cases ran against the updated application. No model requests failed or were truncated;
estimated API cost was USD 2.908038.** This is a development comparison, not an accuracy benchmark:
the labels are unreviewed, cases are related, and only the initial analysis round was exercised.

## Three main findings

1. **The payment safeguards held.** All 11 scam-labelled cases had at least one suspicious check;
   none of the 17 genuine cases or 12 uncertain cases received a `likely_scam` verdict. Six targeted
   payment-confirmation questions appeared across five cases. The two immediate scam verdicts both
   had company-register hard flags. The other 38 cases stayed pending; pending means unresolved,
   not verified or cleared. No student replies were supplied.
2. **The live cross-checker now contributes evidence.** It returned `ok` on all 40 cases and produced
   six findings across five cases. For example, it caught a [GBP 1,300 versus GBP 1,400 rent mismatch](runs/2026-11-15-main/cases/c_d7225bb81851.json)
   and a [contract offering a tenancy while the messages say the owner is only selling](runs/2026-11-15-main/cases/c_9e84e913852a.json).
   Both add suspicious checks that were absent in the previous run. This demonstrates useful
   cross-source checking; it does not establish that every generated finding is correct.
3. **False alarms and wording sensitivity remain.** Two genuine cases still have suspicious checks,
   down from three. Both are the explained low-rent example and its rewrite; the original also gets
   an unsupported authority-pressure warning for the representative's stated role. These warnings
   come from the emotion/pricing checker. All eight wording pairs keep the same outcome, but only
   seven keep the same suspicious checks and six keep the same cleared checks. Clear-state
   consistency was eight of eight previously. A single sampled run cannot isolate the cause.

## Comparison with the previous fixes

Counts are cases unless specified. The input dataset is byte-for-byte unchanged.

| Measure | 14 November fixes | 15 November current system |
| --- | ---: | ---: |
| Genuine cases labelled `likely_scam` | 0/17 | 0/17 |
| Genuine cases with suspicious checks | 3/17 | 2/17 |
| Scam cases with suspicious checks | 11/11 | 11/11 |
| Immediate scam verdicts / pending cases | 2 / 38 | 2 / 38 |
| Cases with payment-confirmation questions | 5 | 5 |
| Wording pairs: identical suspicious / cleared checks | 7/8 / 8/8 | 7/8 / 6/8 |
| Successful model requests | 201 | 273 |
| Estimated API cost, USD | 2.251340 | 2.908038 |

## Coverage and limits

- The production service ran real message, emotion/pricing, contract and company checkers, the LLM
  cross-checker, scoring, consultant and composer. Message, emotion, contract and cross-check reports
  returned `ok` in all 40 cases. Video analysis was skipped throughout.
- Companies House returned `ok` in six cases and `error` in 34: 33 lack suitable register fixtures
  and one deliberately simulates an outage. This makes 34 runs degraded despite successful model
  requests. New postcode, rogue-register and search requests also exceed the original fixture
  coverage. Overall, 39 cases encounter at least one undeclared external request (150 requests,
  including retries); these are unavailable, never invented negative results or live fallbacks.
- Inputs already contain extracted text. Upload/OCR, later replies, voice, persistence, contract
  replacement/history and browser behaviour are outside this 40-case evaluation. The separate
  semantic LLM grader was not run, matching the previous comparison. These results cannot establish
  end-to-end completion or real-world detection accuracy.

## Implementation and validation

The evaluator now inherits the production **4,096-token** cap, accurately records the current
pipeline, shuts down the service after each case, and accepts newly added optional schema defaults
without rewriting old fixtures. Validation still rejects unknown fields and prior conversation
state. A Windows-compatible five-second watchdog replaces the Unix-only test alarm, with approval.

The accompanying UI change preserves the layout and shows the exact backend **Risk score**.
The shared status controls the gauge and headline: neutral when unverified, amber for concerns or
payment confirmation, red only for `likely_scam`, and green only when all eight checks are cleared.
Neutral action answers say “Answered”; the score explanation states that unverified checks keep it
high and that it is not a probability of a scam.

Validation: **1,382 backend tests passed, four skipped; 15 frontend regression tests passed.**
Ruff, formatting, Pyright, all three import contracts, frontend type checking and production build
passed. Frontend lint has no errors and one existing unused-disable warning in the generated
contracts file. Visual browser verification could not finish: computer use stopped because it
could not reliably identify Chrome's current URL on Windows. Temporary QA services were stopped.

## Reproduce and inspect

Backend revision **`d91f7fe`**, based on main **`47a492f`**. Model: **Claude Sonnet 5.5**.
Dataset SHA-256: `9b1df8e02cc05591e192711bbb922cef84a00a0b8ea84adceb72849d1fa7ff80`.
Finished **07:27:50 UTC, 15 November 2026**. Cost uses provider token usage and recorded list prices,
before promotional credits/tax; it excludes prior evaluations. The three-case pilot was resumed,
so it is included once in the totals.

Artifacts: [comparison](runs/2026-11-15-main/comparison.json),
[summary](runs/2026-11-15-main/summary.json), [configuration](runs/2026-11-15-main/metadata.json),
[usage](runs/2026-11-15-main/usage.jsonl), plus complete case and raw outputs in the same directory.
The [previous comparison](runs/2026-11-14-fixes/comparison.json) preserves the earlier fixes' results.

From `backend/`, choose a fresh output directory:

```powershell
& D:\Warden\.venv\Scripts\python.exe -X utf8 -m eval.run --live --env-file D:\Warden\.env --output eval/runs/my-current-check --parallel 3 --no-grade
```

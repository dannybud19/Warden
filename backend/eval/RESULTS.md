# First live system evaluation — 14 November 2026

**All 40 cases ran through the real agents and orchestrator using Claude Sonnet 5.5.**
The run found concrete false alarms and missed checks. It is a preliminary development evaluation:
the synthetic labels are unreviewed, and external register/search responses are controlled fixtures.

## Results after the first round

| Scenario label | Cases | `likely_scam` | Still asking questions | At least one suspicious check |
| --- | ---: | ---: | ---: | ---: |
| Scam | 11 | 5 | 6 | 11 |
| Genuine | 17 | 2 | 15 | 8 |
| Unknown | 12 | 1 | 11 | 5 |

`pending` means open questions, not a benign verdict or automatically a missed scam. No follow-up
answers were supplied. The two genuine false verdicts are one prepaid-card control and its paraphrase;
there are nine distinct genuine scenarios plus eight wording variants.

The separate LLM grader marked **87 of 110 expectations met, 9 missed, 13 violated and 1 indeterminate**.
These are provisional judgements, not real-world accuracy. All eight paraphrase pairs retained their
outcome; two changed their suspicious checks. Wording effects and model variability are not separated.

## Most useful findings

| Finding | Evidence from this run | Suggested owner |
| --- | --- | --- |
| **Negation is missed in payment rules.** A legitimate budgeting card and an explicit refusal to request gift cards still trigger the hard flag for untraceable payment. | [Genuine control](runs/2026-11-14-system/cases/c_d9080a53cc62.json), its paraphrase, and the unresolved prepaid-card case all became `likely_scam`. | Georgi |
| **Owner and agent roles get confused.** The message checker exports the managing agent's name as the landlord; the deterministic cross-check then flags an identity mismatch. | [Explained low-rent control](runs/2026-11-14-system/cases/c_14c60e282afe.json): owner Mira Vale versus agent Rowan Pike, despite explicit roles. | Georgi + Danny |
| **An owner abroad is treated as unavailable for a viewing.** Local-agent and completed-viewing context does not consistently suppress that rule. | [Legitimate paused advert](runs/2026-11-14-system/cases/c_2500da052da6.json) and the genuine compound case receive a viewing warning. | Georgi |
| **Some explicit payment-before-viewing demands remain open.** They produce concerns without the expected hard-stop behavior. | [Transfer-pressure case](runs/2026-11-14-system/cases/c_a919eb7d9823.json) remains `pending`; inspect the rule/LLM distinction before changing the decision policy. | Georgi + Danny |
| **The rent conflict is noticed but does not become a contract-consistency finding.** | [GBP 1,400 chat versus GBP 1,300 draft](runs/2026-11-14-system/cases/c_d7225bb81851.json): a clarification question is present; `contract_consistency` remains unverified. | Danny |

Positive examples: the [contract injection case](runs/2026-11-14-system/cases/c_71314e72c2ae.json)
still reports the GBP 300 fee conditionally and ignores the instruction to clear everything. Missing
attachments prompt requests. Reassuring language does not hide the payment-before-viewing demand in
[the reassurance case](runs/2026-11-14-system/cases/c_5eca4753b387.json).

## Limits that matter

- Message, emotion and contract checkers returned `ok` for **40/40** cases. Companies House returned
  `ok` for **6/40**: **33** lacked the required register fixtures and **1** deliberately modelled an
  unavailable register. Missing fixtures returned explicit unavailability, never a fabricated negative
  match. Auxiliary fixture gaps also remain. This is a test-coverage limitation, not 34 API failures.
- The LLM cross-checker has not landed in the tested main snapshot; this run uses the existing
  deterministic cross-check. Video is skipped because these cases contain no video.
- The grader raised citation/grounding objections in every case, partly around the hand-built area-rent
  table and formatted structured figures. Consequently its strict overall pass flag is **0/40** and is
  not a reliable accuracy measure. The verdict counts above come directly from the application; the
  example defects were also checked against saved outputs. Raw grading concerns remain available.
- No production rules, prompts, scoring weights or scenario labels were tuned during this evaluation.
  Fix the specific semantic errors and expand external fixtures before interpreting a later run as a
  broader system benchmark.

## Cost and reproducibility

**USD 4.19 total:** approximately USD 2.15 for agents/consultant and USD 2.04 for grading.
All **242 model requests succeeded**, with no truncated responses or unknown-billing calls.
Cost uses returned token usage and
[Anthropic's published prices](https://platform.claude.com/docs/en/about-claude/pricing), verified on
the run date, before promotional credits or taxes. The configured API key worked.

Agent code: main `ebe56a8`, tested checkout `7f7e865`. The pilot was reused. Four invalid grading answers
were retried using saved outputs; agents were not rerun. Original failures are retained. The API run
finished at 20:16:37 UTC. Settings and full token/cost records are linked below.

Artifacts: [summary](runs/2026-11-14-system/summary.json),
[configuration and dataset fingerprint](runs/2026-11-14-system/metadata.json),
[usage journal](runs/2026-11-14-system/usage.jsonl), and per-case JSON under
`runs/2026-11-14-system/cases/`. Offline validation: **566 passed, 3 MongoDB-dependent tests skipped**;
Ruff, Pyright and all three import-linter contracts passed. See [README.md](README.md) for commands.

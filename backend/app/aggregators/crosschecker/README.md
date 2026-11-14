# Cross-checker (WS J)

Reads every agent's report side by side, flags where they disagree, and writes a short recap that
the orchestrator relays to the student. Its report is stored as `case.reports["crosscheck"]`.

## The stub (now)

`review(case, rule_findings, ctx)` returns an `AgentReport` (`agent="crosscheck"`, status `ok`,
empty `input_hash`) whose findings are the orchestrator's rule findings
(`orchestrator/crosscheck.py`), passed through unchanged, and whose `summary` is a template recap.
The orchestrator passes the findings in because aggregators may not import the orchestrator.

The recap (`recap(findings)`) counts only `supports="suspicious"` findings; a cleared finding is not
a disagreement. Each finding's topic is its title minus " differs between sources", lower-cased
(the whole title if the suffix is missing), unique, in order:

| Topics | Recap |
| --- | --- |
| 0 | `None` |
| 1 | "Two sources disagree on the rent." |
| 2 or more | "Sources disagree on: rent, address." (at most 6 named, then "and N more") |

" Check these before you pay." is appended when any counted finding has `hard_flag` or severity
`critical` or `high`.

## Later

The LLM version reads all reports, adds its own findings and writes the recap, keeping the
`review(case, rule_findings, ctx)` signature.

## Tests

```bash
cd backend && uv run pytest -q app/aggregators/crosschecker
```

# Cross-checker (WS J)

Reads every agent's report side by side, flags where they disagree, and writes a short recap that
the orchestrator relays to the student. This is the **stub**: `review()` passes the orchestrator's
rule findings (`orchestrator/crosscheck.py`) through unchanged and writes a template recap in
`AgentReport.summary` (`None` when nothing disagrees). The LLM version is planned and keeps the
`review(case, rule_findings, ctx)` signature. Its report is stored as `case.reports["crosscheck"]`.

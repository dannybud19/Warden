# System design (summary)

The full, live version with both diagrams is the team doc "Rental Scam Shield: System Design & MVP Plan":
https://claude.ai/artifact/LFXC5kUzYWCg6JTtRp1LLH

For code, the repo is the source of truth (`backend/app/contracts/`), with `docs/architecture.md` describing how it fits together.

## The flow in one paragraph

A student who has picked a property uploads communication with the agent as it happens. The case opens at
maximum suspicion (score 100, 8 checks unverified). The orchestrator runs only the checker agents whose
input changed, in parallel. Each agent flags every suspicious signal (and anything that clears a check)
with quoted evidence. The orchestrator cross-checks facts between uploads, updates the checks and
recomputes the score. The consultant proposes 1 to 3 questions or actions, and the orchestrator asks the
student in the chat. Answers and new uploads loop back. When nothing useful is left to ask, or a hard red
flag is confirmed, the orchestrator gives the final verdict.

## Who talks to whom

| From | To | How |
| --- | --- | --- |
| Student | Orchestrator | API uploads and chat replies |
| Orchestrator | Student | Chat messages and action cards over the WebSocket |
| Orchestrator | Checker agents | `agent.run(case, ctx)`: a read-only snapshot of the Case |
| Checker agents | Orchestrator | `AgentReport` (findings, facts, open questions) |
| Orchestrator | Scoring, Consultant | Plain function calls |
| Agent | Agent | Never directly: only through cross-checked facts, shared checks and reruns from changed state |

## Components

| Component | Owner |
| --- | --- |
| Evidence intake, orchestrator, check tracker, crosscheck, conversation, final decision, API, storage | Danny |
| Companies House agent | Danny |
| Message checker, Emotional influence classifier, Consultant | Georgi |
| Contract checker, Scoring, Evaluation, Video analysis (later) | Bill |
| Web app, design.md, Figma, branding | Audrey |

## Checks and weights

| Check | Weight |
| --- | --- |
| landlord_identity | 0.20 |
| payment_safety | 0.20 |
| right_to_let | 0.15 |
| in_person_viewing | 0.10 |
| contract_consistency | 0.10 |
| deposit_protection | 0.10 |
| no_pressure | 0.10 |
| fair_price | 0.05 |

Score = 100 × Σ(w × s) / Σw, where s = 1 if unverified or suspicious, and 1 minus the clearing confidence if cleared.

## Verdicts

| Verdict | When |
| --- | --- |
| Likely scam | Any hard flag, or 2+ of identity, payment and right to let suspicious |
| Not verified | Closed with core checks not cleared, no hard flag |
| Proceed with care | Core checks cleared, minor checks open or suspicious |
| No red flags remaining | Every check cleared (never "safe") |

# Warden (working name: Rental Scam Shield)

A multi-agent assistant that protects London students from rental scams. The student uploads what the
property agent sent them (chats, emails, calls, videos, documents, the contract). The case starts at
maximum suspicion, checker agents flag every red flag with evidence, and one orchestrator asks focused
questions and suggests actions until nothing useful is left to check. Then it gives a verdict. It never
calls a place "safe".

Built at the Imperial AI Hackathon (Autonomous Agents track), 14 to 15 Nov 2026.
Team: Danny (backend and agents), Georgi (AI), Bill (AI), Audrey (design).

## Run it

```bash
cp .env.example .env          # add keys only for agents you switch to real
make install
make dev                      # API on http://localhost:8000 (all agents are stubs by default)
make web                      # web app on http://localhost:3000
make check                    # lint, types, import rules, tests
```

`DEFAULT_AGENT_MODE=real make dev` runs every agent's real code, which is how you see the question loop
before the agents are finished.

## Where things are

| Read | For |
| --- | --- |
| `AGENTS.md` | Rules for every person and coding agent: ownership, golden rules, commands, style |
| `CLAUDE.md` | Full system overview and docs map. Read before every session |
| `docs/architecture.md` | Architecture, orchestrator algorithm, scoring, API, quality gates |
| `docs/workstreams.md` | Who builds what, timeline, and the brief for each workstream |
| `docs/decisions.md` | Every decision so far, on one page |
| `docs/system-design.md` | Short architecture overview |
| `docs/hackathon-brief.md` | Deadlines, submission rules, prize strategy |
| `docs/design.md` | Look, brand and the frontend plan (coming, from Audrey) |

## How it works (short)

- One shared case record. Agents read it and return reports; they never talk to each other or to the
  student.
- The orchestrator runs the agents, compares their facts, updates 8 weighted checks, scores the case
  (100 means nothing is verified yet), asks the student the next 1 to 3 questions, and decides at the end.
- Verdicts: likely scam, not verified, proceed with care, no red flags remaining.

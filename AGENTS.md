# AGENTS.md

Rules for every coding agent (Claude Code, Codex, Cursor) and every person working in this repo.
Read this and `CLAUDE.md` (full system overview and docs map) first. Your task brief is in
`docs/workstreams.md`, the architecture in `docs/architecture.md`, UI and brand in `docs/design.md` (Audrey).

## What this project is

A multi-agent system that protects London students from rental scams. A student uploads their
communication with a property agent (chat screenshots, WhatsApp/email text, call recordings, videos,
documents, contract). The case starts at maximum suspicion (score 100). Independent checker agents flag
every suspicious signal, an orchestrator asks the student clarifying questions and actions, answers
adjust the score, and a final decision is made when nothing useful is left to check.

Hackathon: Imperial AI Hackathon, Autonomous Agents track. Submit on Devpost by Sun 15 Nov 11:45
(hard close 12:00).

Status: Phase 0 (foundation) is done. Everyone now works in their own workstream (`docs/workstreams.md`).

## Repo map

| Path | What lives there | Owner |
| --- | --- | --- |
| `docs/` | Team docs: architecture, workstreams, decisions, system design, hackathon brief, design | Danny (`design.md`: Audrey) |
| `plan/` | Danny's private planning files. Gitignored; do not depend on it | Danny |
| `backend/app/contracts/` | Shared Pydantic schemas. FROZEN (see "Changing contracts") | Danny |
| `backend/app/core/` | BaseAgent, AgentContext, LLM and search clients, settings | Danny |
| `backend/app/agents/companies_house/` | Companies House checker | Danny |
| `backend/app/agents/message_checker/` | Chat and email red flags | Georgi |
| `backend/app/agents/emotion_classifier/` | Facts vs feelings, pricing | Georgi |
| `backend/app/agents/contract_checker/` | Contract red flags | Bill |
| `backend/app/agents/video_analysis/` | Stub only (later) | Bill |
| `backend/app/aggregators/scoring/` | Score formula, weights | Bill |
| `backend/app/aggregators/consultant/` | Next questions and actions | Georgi |
| `backend/app/orchestrator/` | Runner, checks, crosscheck, conversation, decision | Danny |
| `backend/app/intake/` | Uploads to text and messages | Danny |
| `backend/app/storage/`, `backend/app/api/` | Repos, FastAPI, WebSocket | Danny |
| `backend/scripts/`, `Makefile`, `pyproject.toml` | Shared tooling. Ask Danny before changing | Danny |
| `backend/eval/` | Synthetic cases and evaluation | Bill |
| `web/` | Next.js app (web shell first, then Audrey's design). `web/AGENTS.md` is Next.js's own rules: read it before writing web code | Audrey |
| `fixtures/cases/`, `fixtures/reports/` | Synthetic data and stub reports | Everyone |
| `fixtures/private/` | Real data. Gitignored. Never commit | Danny |

## Golden rules

1. **Stay in your owned paths.** If your task needs a change elsewhere, stop and say so. Do not
   "quickly fix" another workstream's folder.
2. **Agents never import each other.** An agent imports only `app.contracts`, `app.core` and its own
   package. `make imports` enforces this; never weaken the import-linter config.
3. **Never change `app/contracts/` inside a feature branch.** See "Changing contracts".
4. **Every agent must keep working as a stub.** Do not delete or break `stub.py` or its fixture report.
5. **No network in tests.** Use `FakeLLM`, `FakeSearch` and `httpx.MockTransport`.
6. **Evidence or it did not happen.** Every `Finding` cites at least one `EvidenceRef` with a real quote.
   Drop LLM findings whose quote is not found in the source text. Web findings cite the URL.
7. **Flag and clear.** Emit `supports="cleared"` findings when evidence shows a check is fine. The score
   only goes down through clears.
8. **Secrets stay in `.env`.** Never commit keys, real names, phone numbers or bank details. Mask bank
   accounts to the last 4 digits in facts and logs.
9. **Never call a place "safe".** The best verdict is "no red flags remaining".

## Setup (once per clone or worktree)

```bash
git pull
git worktree add ../rss-<ws> -b feat/<ws>-<short>      # e.g. feat/d-message-checker
cd ../rss-<ws> && cp ../Warden/.env .env 2>/dev/null; make install
pre-commit install
claude   # first prompt: "Read AGENTS.md, then do workstream <letter> in docs/workstreams.md"
```

## Commands

```bash
make install        # uv sync + pnpm install
make dev            # API on :8000 (agents default to stubs)
make web            # Next.js on :3000
make check          # ruff, format check, pyright, import-linter, pytest: must be green before pushing
make fmt            # auto-format and fix lint
make schema         # regenerate web/src/types/contracts.ts after a contracts change
cd backend && uv run python -m scripts.run_agent message_checker ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent message_checker <case.json> --live   # real LLM/web
```

Agent modes:

- Default: every agent is a stub. The stub reports contain hard flags, so the first WhatsApp upload
  closes the case as `likely_scam` straight away. That is expected.
- `DEFAULT_AGENT_MODE=real make dev`: every agent runs its real code. Use this to see the question and
  reply loop (agents that are not built yet return empty reports, so nothing gets flagged).
- One agent only: `AGENT_MODE_MESSAGE_CHECKER=real` in your local `.env` (`.env` values are read).

## How to build a checker agent

1. Subclass `BaseAgent` in `agents/<name>/agent.py`. Set `name` (equal to the folder name), `version`
   and `requires` (a set of `Need`s).
2. Implement `async def run(self, case, ctx) -> AgentReport` and build the result with `self.report(...)`.
3. Reliable rules go in `rules.py` (pure functions). LLM prompts go in `prompts/*.md`, and the LLM's
   structured output models in `models.py`. Convert everything to `Finding` and `Fact` before returning.
4. Finding ids are `f"{self.name}:{slug}"`. Map each finding to exactly one `CheckId`.
5. Use only `ctx.llm`, `ctx.search` and `ctx.http` for I/O. Never construct clients yourself.
6. Tests in `agents/<name>/tests/`: rules unit tests, one full run on a fixture case with fakes, one stub test.
7. Do not register the agent yourself; it is already in `orchestrator/registry.py`.
8. Parse money yourself: the shared normaliser keeps digits only, so `£850.00` would not match `850`.

## Code style

- Python 3.12, full type hints, Pydantic v2 models, `async` for all I/O.
- Small pure functions; no module-level mutable state; no `print` (use `ctx.log`).
- Line length 100; ruff decides formatting.
- Names: `snake_case` modules and functions, `PascalCase` classes, constants in `UPPER_SNAKE`.
- Docstrings on public functions: one line on what, plus why if it is not obvious.
- No new dependencies without telling Danny (they change `pyproject.toml`, a shared file).
- Frontend: TypeScript strict. Contract types come only from `src/types/contracts.ts` (generated, never
  hand-edited) through `src/lib/types.ts`. Read optional fields with a fallback (`c.checks ?? []`).
  Skipped agents send no stream event: read `case.reports` for their status.

## Changing contracts

1. Prefer additive changes (new optional field, new enum value).
2. Make a separate branch `contracts/<short>` that touches only `backend/app/contracts/`, `fixtures/`
   and the regenerated `web/src/types/contracts.ts` (`make schema`). The exporter
   (`backend/scripts/export_schema.py`) and the `schema` Makefile target may change in the same branch.
3. Tell the team, merge, and everyone rebases.

## Git

- Branches: `feat/<ws>-<short>`, `fix/<short>`, `contracts/<short>`. Never commit straight to `main`
  (Phase 0 was the only exception).
- Commit messages: `<area>: <what>`, e.g. `contract_checker: flag deposits above 5 weeks' rent`.
- One git worktree per workstream (see Setup), so parallel agents never share a working tree.
- Before a PR: rebase on `main`, `make check` green.

## Definition of done (any task)

- [ ] Only owned paths changed (plus fixtures you added)
- [ ] Tests cover the new behaviour and run offline
- [ ] `make check` is green
- [ ] The agent still works as a stub and as real
- [ ] README in the agent folder updated (what it flags, how to run it alone)

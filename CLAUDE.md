@AGENTS.md

# CLAUDE.md: read this before every session

This file gives you (Claude Code, or a teammate) the whole system in one read: what we are building, how
the code is organised, how data moves, and where every other doc is. `AGENTS.md` (imported above) holds
the rules. Read both before touching code.

## Latest changes (read first, newest on top)

Whoever merges a change that affects other people adds a line here (see "Definition of done" in AGENTS.md).
Keep the last 8; delete older lines.

| When | Change | What it means for you |
| --- | --- | --- |
| Sat evening | **Evaluation fixes and payment confirmation** (Bill, team-delegated) | Message checks distinguish payment demands from denials and post-viewing terms; owner names must have an explicit role; being abroad alone is not a viewing barrier. Local agent/friend viewing offers suppress the abroad warning in both rule and LLM findings. The orchestrator asks for an exact yes/no/unsure confirmation before a payment hard flag closes a case, within the shared limit of three open actions. No/unsure keeps it open without clearing payment safety. Company/contract hard flags remain immediate. See the message-checker README and `docs/architecture.md` |
| Sat 20:10 | **Companies House wired into the live app; analysis runs in the background** (Danny) | `open_case` with a landlord company name or number starts the agency check at once; `add_evidence` and `reply` save and return the Case immediately and analyse in a background task (one analysis per case, short state lock, so nothing is blocked or overwritten). Agent progress and results arrive **only over the stream** after the HTTP call returns; a client that connects late is sent `agent_started` for agents still running. A failed analysis becomes an `orchestrator_message`. Tests: use `wait_idle()` / the `settled` helpers in `backend/tests/conftest.py`. Web: Add home has optional Company number and Agent's name (and sends `listing.postcode` when the address has one); findings that cite web pages show a clickable "Source" link (`sourceUrls` in `selectors.ts`). To run it live: `AGENT_MODE_COMPANIES_HOUSE=real` in `.env` (stubs hard-flag every home that has an agency) |
| Sat 19:01 | **Standalone contract checker ready** (WS G, Bill) | Accepts text-based PDF/text plus explicit context and returns quoted issues, legal links and targeted questions. The existing `AgentReport` adapter exports concerns and contract facts; rule-level passes do not clear whole shared checks. Upload integration and revision history remain follow-ups. See [WS G](docs/workstreams.md#ws-g-contract-checker-bill) and the [checker README](backend/app/agents/contract_checker/README.md) |
| Sat 18:30 | **New agent: Cross-checker** (WS J, Danny), in `backend/app/aggregators/crosschecker/` (being built) | A generalist agent that reads every agent's report side by side, flags where they disagree (contract says £60/month utilities, messages say bills included) and writes a recap. The orchestrator relays the recap to the student. Its report replaces `case.reports["crosscheck"]`. Your agent changes nothing: just keep findings and facts accurate and quoted |
| Sat 18:30 | **Companies House is now a background check** (WS B, Danny) | Register, reputation (scam reports, negative reviews, redress, London Rogue Landlord Checker), contact details, postcode. Hard flags only from the register: a company number that doesn't exist, or a dissolved or liquidated company. A name with no match is suspicious, not a hard flag. Facts: `company_number` (zero-padded) and `email_domain` only, never `address` or `landlord_name` |
| Planned | **`AgentReport.summary: str \| None`** (contracts change, Danny) | Optional, defaults to `None`, used for the Cross-checker recap. When it lands: rebase, and the TS types gain one field |
| Sat 18:00 | **Consultant role clarified** | The consultant only picks the next 1 to 3 questions or actions. The orchestrator is the only thing that talks to the student |
| Sat 16:00 | **Replies target one action** | `POST /cases/{id}/messages` takes `action_id` and `status` (`done`, `skipped`, `impossible`). Unknown or closed `action_id` gives 422 |

## 1. The product in 30 seconds

Warden (working name Rental Scam Shield) protects London students from rental scams. The student has
already found a property and uploads everything the property agent sends them: chat screenshots,
WhatsApp/email text, call recordings, videos, documents, the contract.

- The case starts at **maximum suspicion**: score 100, all 8 checks "unverified".
- Independent **checker agents** read the case and flag red flags (or clear checks), always quoting evidence.
- A generalist **Cross-checker** reads all their reports together, flags where they disagree, and writes a
  recap.
- One **orchestrator** is the only thing that talks to the student. It relays the recap and asks the next
  1 to 3 questions or actions that the **consultant** picked (for example "ask for the company number",
  "book an in-person viewing").
- The student always makes the final call on the property. We advise; we never decide for them.
- Answers and new evidence move the score. The score only goes down when something is verified.
- When nothing useful is left to check, or a hard red flag is confirmed, it gives a **verdict**:
  `likely_scam`, `not_verified`, `proceed_with_care` or `no_red_flags_remaining`. Never "safe".

Hackathon: Imperial AI Hackathon, Autonomous Agents track. Sponsors we target: Linkup (live web search with
cited URLs), MongoDB (case storage), and the Best-Designed AI Product prize (Figma). Submit on Devpost by
Sun 15 Nov 11:45 (hard close 12:00).

## 2. Docs map (what to read, when)

| File | What it covers | Read it when |
| --- | --- | --- |
| `AGENTS.md` | Ownership, golden rules, setup, commands, how to build an agent, style, git, definition of done | Always (imported above) |
| `README.md` | What the project is and how to run it | First time |
| `docs/architecture.md` | Principles, tech stack, full repo layout, orchestrator algorithm, scoring formula and weights, verdict rules, API, quality gates, contract change process | Before changing any backend code |
| `docs/workstreams.md` | Who owns what (A to I), timeline, out of scope, and the **brief for each workstream** | Before starting your workstream: do the brief for your letter |
| `docs/decisions.md` | Every product and process decision so far, on one page | When you wonder "why is it like this?" |
| `docs/system-design.md` | Short architecture summary and agent list | Quick context |
| `docs/hackathon-brief.md` | Deadlines, submission requirements, prize strategy, original brief | Planning, demo, write-up |
| `handoffs` branch (`git show origin/handoffs:README.md`) | Notes between teammates' coding agents | Start of every session |
| `docs/design.md` | Look, brand, tokens and Audrey's frontend plan (being written) | Any work in `web/` |
| `web/AGENTS.md` | Next.js 16's own rules: read its bundled docs before writing web code | Any work in `web/` |
| `backend/app/agents/*/README.md`, `backend/app/aggregators/*/README.md` | What each agent flags and how to run it alone | Working on that agent |

`plan/` is Danny's private planning folder and is gitignored. Do not look for it or depend on it.
Everything a teammate needs is in the files above.

## 3. How the system works

```text
student ──upload / reply──▶ API (FastAPI) ──▶ CaseService (orchestrator)
                                               │
                    intake: file/text → Evidence + Messages
                                               │
               runner: pick agents whose inputs exist and changed, run in parallel (timeouts)
                 ├─ companies_house   ├─ message_checker   ├─ contract_checker
                 ├─ emotion_classifier └─ video_analysis (stub)
                                               │  each returns an AgentReport (facts + findings)
                    crosscheck rules: compare facts (address, landlord name, rent, deposit)
                    Cross-checker: reads every report, flags disagreements, writes a recap
                                   (recap → orchestrator_message to the student)
                    checks: findings + answers → 8 check states
                    scoring: weighted formula → score
                    hard flag? → decide.   else consultant → next actions (or decide if none left)
                                               │
               StreamEvents over WebSocket ──▶ web app (agent progress, score, actions, decision)
```

Key ideas:

- **Blackboard pattern.** There is one shared `Case` record (evidence, messages, checks, actions, reports,
  score history, decision). Agents only read it. Only the orchestrator writes it and talks to the student.
  Agents never call or import each other; the Cross-checker compares their reports.
- **Deterministic core, LLMs at the edges.** Which agents run, check states, the score and the verdict are
  plain code. LLMs are used inside agents, the Cross-checker, the consultant and the chat layer only.
- **Reruns are automatic.** Each report stores an `input_hash` of the slice of the case the agent needs.
  New evidence reruns only the agents whose inputs changed.
- **Stubs everywhere.** Every agent has a `stub.py` that replays `fixtures/reports/<agent>.json`, so the
  whole app runs before any real logic exists.

### The 8 checks and weights

| Check | Weight | Check | Weight |
| --- | --- | --- | --- |
| `landlord_identity` | 0.20 | `contract_consistency` | 0.10 |
| `payment_safety` | 0.20 | `deposit_protection` | 0.10 |
| `right_to_let` | 0.15 | `no_pressure` | 0.10 |
| `in_person_viewing` | 0.10 | `fair_price` | 0.05 |

Score = `100 * Σ(w·s) / Σw`, where s = 1 if a check is unverified or suspicious, and `1 - clear_confidence`
if cleared. Hard flags close the case early: payment before viewing or to a pre-paid card, a company
number that doesn't exist on Companies House or a dissolved or liquidated company, or a contract address
that doesn't match the listing.
Full rules: `docs/architecture.md` section 7.

### Main data types (`backend/app/contracts/`, frozen)

| Type | What it is |
| --- | --- |
| `Case` | The shared record: student, listing, landlord, evidence, messages, checks, actions, reports, score_history, decision |
| `Evidence`, `Message` | An upload and the messages parsed out of it |
| `Fact` | A typed value an agent extracted (bank account, company number, address, rent, deposit) |
| `Finding` | A flag or clear: check id, severity, confidence, `supports` (suspicious/cleared), `hard_flag`, evidence quotes |
| `Check`, `Action` | One of the 8 checks with its state; a question or action for the student, with status and outcome |
| `AgentReport` | What one agent returns: status, input_hash, facts, findings (planned: optional `summary`, used for the Cross-checker recap) |
| `ScoreResult`, `Decision` | Score with per-check contributions; final verdict with summary and reasons |
| `StreamEvent` | `agent_started`, `agent_finished`, `score_updated`, `actions_proposed`, `orchestrator_message`, `decision_made` |

### API

| Method | Path | Does |
| --- | --- | --- |
| POST | `/cases` | Open a case |
| POST | `/cases/{id}/evidence` | Upload a file or pasted text (`kind`, `note`) |
| POST | `/cases/{id}/messages` | Student reply (`text`, optional `action_id` + `status`) |
| GET | `/cases/{id}` and `/cases/{id}/decision` | Read state |
| WS | `/cases/{id}/stream` | Live StreamEvents |

## 4. Where code lives

| Folder | Contents | Owner |
| --- | --- | --- |
| `backend/app/contracts/` | Pydantic schemas (frozen) | Danny |
| `backend/app/core/` | `BaseAgent`, `AgentContext` (llm, search, http, log), settings, `FakeLLM`, `FakeSearch`, stub base | Danny |
| `backend/app/agents/<name>/` | `agent.py`, `stub.py`, `rules.py`, `models.py`, `prompts/`, `tests/`, `README.md` | per agent |
| `backend/app/aggregators/scoring/` | Score formula and `weights.yaml` | Bill |
| `backend/app/aggregators/consultant/` | Picks the next actions (the orchestrator asks them) | Georgi |
| `backend/app/aggregators/crosschecker/` | Cross-checker: consistency findings across all reports + recap (being built, WS J) | Danny |
| `backend/app/orchestrator/` | `registry`, `runner`, `crosscheck`, `checks`, `conversation`, `decision`, `service`, `events` | Danny |
| `backend/app/intake/` | WhatsApp parser, PDF text; OCR and audio are stubs | Danny |
| `backend/app/storage/`, `backend/app/api/` | In-memory and Mongo repos; FastAPI app and routes | Danny |
| `backend/scripts/` | `run_agent.py` (run one agent on a case), `export_schema.py` | Danny |
| `backend/eval/` | Synthetic cases and evaluation | Bill |
| `fixtures/cases/` | `fake_agency.json`, `overseas_landlord.json`, `genuine_flat.json` | everyone |
| `fixtures/reports/` | Stub reports per agent and `full_case.json` for UI mocks | everyone |
| `web/` | Next.js 16 app; `src/types/contracts.ts` is generated, `src/lib/` is the data layer | Audrey |

## 5. Current state and gotchas

Phase 0 (the foundation) is done: everything runs end to end on stubs and `make check` is green. Real agent
logic is the work of the workstreams. Things that surprise people:

- **Default stubs end the case on the first upload.** The stub reports contain hard flags, so uploading the
  sample WhatsApp chat decides `likely_scam` straight away (or, if the home was added with an agency
  name or number, as soon as it is added). To see the question and reply loop, run
  `DEFAULT_AGENT_MODE=real make dev` (agents not built yet return empty reports).
- **Agent modes:** `AGENT_MODE_<NAME>=real` in `.env` switches one agent; `.env` values are read.
- **Crosscheck findings** are stored as a pseudo report under `case.reports["crosscheck"]`. Once WS J
  lands, the Cross-checker writes that same key (rule findings plus its own), so the UI needs no change.
- **Facts feed the cross-check.** Any `address`, `landlord_name`, `company_number`, `rent_pcm` or `deposit`
  fact you emit is compared with the listing, the landlord and other agents. Only emit a fact that means
  the same thing as theirs (e.g. Companies House emits no registered-office `address`).
- **Address hard flag** fires only when the contract and the listing disagree.
- **Skipped agents** (missing inputs) emit no stream event; read `case.reports[name].status`.
- **Money parsing:** the shared normaliser keeps digits only (`£850.00` becomes `85000`). Parse rent and
  deposits properly in your own agent.
- **Generated TS types:** strict (every field required, no extra keys). The single evidence item is
  named `Evidence1`. Regenerate with `make schema` after any contracts change.
- **Check question wording** in the consultant is placeholder until WS F.
- **Real personal data** (Danny's own case, the demo hook) lives only in `fixtures/private/`, which is
  gitignored. Synthetic cases are for building and tuning.

## 6. How to start a session

1. `git pull`, check the handoff notes ("Handoffs between agents" in `AGENTS.md`), then make your worktree (Setup in `AGENTS.md`).
2. Read this file, then your brief in `docs/workstreams.md` section 4, then `docs/architecture.md`.
3. Read the code you depend on: `backend/app/contracts/`, `backend/app/core/agent.py`, your agent folder
   and its stub fixture.
4. Plan in small steps, write tests first, stay inside your owned paths, use only `ctx.llm`, `ctx.search`
   and `ctx.http` for I/O.
5. `make check` green, update your agent's README, then open a PR from `feat/<ws>-<short>`.
6. If the docs and the code disagree, trust the code and tell Danny. If you need a change outside your
   paths (especially `contracts/`), stop and ask.

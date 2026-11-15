# Architecture

How the system fits together. The code is the source of truth: `backend/app/contracts/` for every
shared schema, `backend/app/core/` for the agent base class and clients. Read `CLAUDE.md` first for the
short version.

---

## 1. What we are building (one paragraph)

A student who has already picked a property uploads every piece of communication with the property agent
as it happens (chat screenshots, WhatsApp/email text, call recordings, videos, documents, the contract).
The case starts at maximum suspicion (score 100, every check unverified). Independent checker agents flag
every suspicious signal. An orchestrator tracks 8 checks, asks the student clarifying questions or suggests
actions, and adjusts the score from their answers. When nothing useful is left to ask, or a hard red flag
is confirmed, it gives a final decision with the full evidence trail.

---

## 2. Architecture principles (non-negotiable)

1. **Contracts are the only shared code.** Every agent reads a `Case` and returns an `AgentReport`.
   All schemas live in `backend/app/contracts/`. They are frozen after Phase 0 and changed only by the
   process in section 9 below.
2. **Agents never import each other.** An agent may import only `app.contracts` and `app.core`.
   This is enforced by `import-linter` (section 8 below), not by good intentions.
3. **Dependencies are injected.** Agents get LLM, web search and HTTP clients through `AgentContext`,
   so every agent runs and tests offline with fakes.
4. **Every agent has a stub.** A stub returns a fixed report. The orchestrator and UI work end to end
   before any real agent logic exists, and any agent can be switched back to its stub by env var.
5. **Storage behind an interface.** `CaseRepository` has an in-memory implementation (default for dev and
   tests) and a MongoDB Atlas implementation. Nobody waits on database setup.
6. **The orchestrator core is deterministic.** It decides which agents run, tracks checks, computes the
   score and decides when to close. LLMs are used inside agents, the Cross-checker, the consultant and the
   chat layer only.
7. **Frontend builds against mocks.** The web app can run fully on `fixtures/reports/*.json` with
   `NEXT_PUBLIC_USE_MOCK=1`, using TypeScript types generated from the Python contracts.

---

## 3. Tech stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, asyncio, managed with `uv` |
| Quality | ruff (lint + format), pyright (basic), pytest + pytest-asyncio, import-linter, pre-commit |
| LLM | One `LLMClient` protocol in `app/core/llm.py`. `LLM_PROVIDER=anthropic` (default) or `openai_compatible` (Gemini, Groq and others, for free-tier development; see `.env.example`). `FakeLLM` for tests |
| Live web | Linkup via `WebSearchClient` protocol in `app/core/search.py`; `FakeSearch` for tests |
| Registers | Companies House public API (key in `.env`) |
| Storage | `CaseRepository` protocol: `InMemoryCaseRepo` (default), `MongoCaseRepo` (MongoDB Atlas, motor) |
| Frontend | Next.js (App Router) + TypeScript, pnpm. Types generated from contracts' JSON Schema |
| Streaming | WebSocket `/cases/{id}/stream` for agent status and orchestrator messages |

---

## 4. Repository layout

```text
Warden/
  AGENTS.md                      rules for every coding agent and person
  CLAUDE.md                      Claude Code entry point (imports AGENTS.md)
  README.md                      what it is, how to run it, where the docs are
  docs/                          team docs (architecture, workstreams, decisions, design, brief)
  plan/                          Danny's private planning files. GITIGNORED
  .env.example
  .pre-commit-config.yaml
  Makefile                       dev, test, lint, types, check
  backend/
    pyproject.toml               deps, ruff, pyright, pytest, import-linter config
    app/
      contracts/                 FROZEN after Phase 0 (section 9 below)
        __init__.py              re-exports everything below
        evidence.py              Evidence, EvidenceKind, Message
        case.py                  Case, StudentContext, Listing, Landlord, CaseStatus
        findings.py              Fact, FactKey, Finding, Severity, Category
        checks.py                CheckId, Check, CheckState, Action, ActionKind, ActionStatus
        reports.py               AgentReport, AgentStatus, ScoreResult, Decision, Verdict
        events.py                StreamEvent (WebSocket payloads)
      core/                      shared infrastructure, no business logic
        agent.py                 BaseAgent, AgentContext, Need, has_need, slice_for, hash_slice
        stub.py                  FixtureStub base class used by every agent's stub.py
        ids.py                   new_id(prefix) helper
        llm.py                   LLMClient protocol, AnthropicLLM, FakeLLM
        search.py                WebSearchClient protocol, LinkupSearch, FakeSearch
        settings.py              pydantic-settings, reads .env
        logging.py
      agents/                    one folder per checker agent, owned by one person
        companies_house/         agent.py, stub.py, prompts/, tests/, README.md
        message_checker/
        contract_checker/
        emotion_classifier/
        video_analysis/          stub only until later
      aggregators/
        scoring/                 scoring.py, weights.yaml, tests/
        consultant/              consultant.py, action_library.yaml, prompts/, tests/
        crosschecker/            crosschecker.py, stub.py, prompts/, tests/ (WS J, being built)
      orchestrator/
        registry.py              the ONE list of agents; stub/real switch per agent
        events.py                in-process EventBus (per-case pub/sub for the WebSocket)
        runner.py                select, run in parallel, timeouts, input hashing
        crosscheck.py            fact comparison rules
        checks.py                check tracker: findings and answers to check states
        conversation.py          chat with the student, answer parsing
        decision.py              final decision rules
        service.py               CaseService: the use cases the API calls
      intake/
        service.py               upload to Evidence + extracted text
        whatsapp.py              WhatsApp .txt export parser
        ocr.py                   screenshot to text (vision model)
        pdf.py                   PDF to text
        docx.py                  Word (.docx) to text, standard library only
        audio.py                 call recording to transcript (later)
      storage/
        repository.py            CaseRepository protocol
        memory.py                InMemoryCaseRepo
        mongo.py                 MongoCaseRepo
      api/
        main.py                  FastAPI app factory
        routes_cases.py
        routes_stream.py
    tests/                       cross-cutting tests (orchestrator, api, import rules)
    scripts/
      export_schema.py           contracts to JSON Schema for the frontend
      run_agent.py               python -m scripts.run_agent <agent> <case.json>
  fixtures/
    cases/                       synthetic Case JSON, committed
    reports/                     AgentReports + full case report for UI mocks, committed
    private/                     REAL data incl. Danny's case. GITIGNORED, never committed
  web/                           Next.js app (Audrey)
    src/types/contracts.ts       GENERATED, do not edit
    src/mocks/                   loads fixtures/reports
```

---

## 7. Orchestrator behaviour

`CaseService` methods, each persists the Case and emits `StreamEvent`s:

1. `open_case(student, listing, landlord) -> Case`: all 8 checks UNVERIFIED, first ScoreResult = 100.
   If the landlord has a company name or number, the agency check starts at once in the background.
2. `add_evidence(case_id, upload) -> Case`: intake extracts text and messages and saves them, returns the
   Case, then analyses in the background.

   **Analysis runs in the background.** `open_case`, `add_evidence` and `reply` return before any agent
   finishes; progress and results arrive as `StreamEvent`s (a client that connects late is sent
   `agent_started` for the agents still running). One analysis runs per case at a time (analysis lock);
   its results are applied to the latest stored case under a short state lock, so uploads and replies are
   never blocked or overwritten, and a request that arrives while one is queued shares it. A failed
   analysis becomes an `orchestrator_message`. `analyse(case_id)` is the awaited form, used by tests.
3. `analyse(case_id)`:
   1. For each agent in the registry: skip if a `Need` is missing (`SKIPPED` report). Skip if
      `input_hash` equals the last report's (no rerun). Otherwise schedule.
   2. Run scheduled agents with `asyncio.gather`, each under `asyncio.wait_for(timeout_s)`.
      Exceptions and timeouts become `ERROR` reports; the run continues.
   3. `crosscheck.compare(facts)` adds CONSISTENCY findings (rule-based). Then the Cross-checker
      (`aggregators/crosschecker`, WS J) reads every OK report together, adds LLM consistency findings that
      quote both sides and name both agents, and writes a recap. Its report is stored as
      `case.reports["crosscheck"]`; a changed recap is emitted as an `orchestrator_message` before the
      consultant's actions. It never sets `hard_flag` itself.
   4. `checks.update(case)`: a check becomes SUSPICIOUS if it has any `supports="suspicious"` finding with
      severity >= MEDIUM and confidence >= 0.6; CLEARED if it has `supports="cleared"` evidence or
      answers and no open suspicious finding; otherwise UNVERIFIED. Suspicious always wins over cleared.
   5. `scoring.score()` appends a ScoreResult.
   6. Payment hard flags first require a targeted confirmation of their quoted evidence. Yes confirms
      that concern; no/unsure/skip (or a longer answer) keeps the concern on record without clearing
      the payment check, and is not asked again for the same evidence: the round carries on with the
      consultant's next steps. Other hard flags still decide immediately. Confirmations are bound to a finding
      and its evidence, so changing the quoted demand requires a new answer.
   7. Else `consultant.propose_actions()`. If it returns `[]` and no actions are open: `decide()`.
      Else store and emit any new actions, then one **round message** (`orchestrator/composer.py`): what
      changed (score delta, checks that moved, checks that did not run, notes about the reply), then the
      steps by count. An LLM writes it (max 60 words); a validator (no "safe"/"scam"/"genuine", no
      number that is not in its input, no 6+ digit run, no JSON) falls back to a fixed template.
   Steps 3 to 7 apply their results in short locked steps; the Cross-checker, the consultant and the
   composer run between them, so no LLM call ever holds the state lock. Every orchestrator message is
   also stored in `case.chat`.
4. `reply(case_id, text, evidence_ids, action_id?, status?)`: `conversation.parse()` maps the reply
   onto open actions on a snapshot (LLM, no lock held), then `apply()` writes it to the latest stored
   actions. With `action_id` only that action can change; `skipped` / `impossible` never call the LLM;
   free text may answer several actions, but only a reply on a step's own card can close it as
   `neutral` (a hedge like "I'll ask them" leaves it open). Every update must quote the reply or it is
   dropped. When the
   LLM fails (error, timeout, bad JSON, unknown ids) a keyword fallback runs, but only when exactly one
   action could be meant; otherwise nothing changes and the round message says it could not match the
   reply. The reply is stored in `case.chat`. Answers can clear or flag checks via `checks.update`; a
   flagged answer about payment asks the student to upload that message. The same LLM call also reads
   case fields the student states (company number, landlord name, rent, deposit, move-in date): each is
   validated, fills an empty field or overwrites only on an explicit correction, and is named in the
   round message (a company number never with its digits). A changed landlord reruns Companies House
   through its input hash. A question from the student is answered in the round message from the
   case's own findings and checks only, or the message says it cannot tell yet. Then the background
   analysis.
5. `decide(case_id)` (also `POST /cases/{id}/decide`, the student's final say): waits for a running
   analysis, then `decision.decide(case)` applies the verdict rules from the team doc and writes the summary.

Scoring formula (team doc): `score = 100 * sum(w_i * s_i) / sum(w_i)`, with s = 1 for UNVERIFIED or
SUSPICIOUS and s = 1 - clear_confidence for CLEARED. Weights in `aggregators/scoring/weights.yaml`:

```yaml
landlord_identity: 0.20
payment_safety: 0.20
right_to_let: 0.15
in_person_viewing: 0.10
contract_consistency: 0.10
deposit_protection: 0.10
no_pressure: 0.10
fair_price: 0.05
```

Verdict rules (`decision.py`):

| Verdict | Rule |
| --- | --- |
| likely_scam | Any hard flag, or 2+ of {landlord_identity, payment_safety, right_to_let} SUSPICIOUS |
| not_verified | Otherwise, if any of those three is not CLEARED |
| proceed_with_care | Those three CLEARED, some other check not CLEARED |
| no_red_flags_remaining | Every check CLEARED. Never call it "safe" |

Hard flags (a finding with `hard_flag=true` can close the case as `likely_scam`): payment before a viewing
or to a pre-paid card, a company **number** that does not exist on Companies House, a dissolved or
liquidated company, and a contract address that does not match the listing. Only the register can hard-flag
the agency: a company **name** with no match is suspicious (high severity, asks for the number), never a
hard flag.

Payment hard flags require an explicit student yes to their targeted confirmation question before
closure. The orchestrator prioritises these questions even for SUSPICIOUS payment checks; this is an
exception to the consultant's usual UNVERIFIED-only selection. Free chat targets an open payment
confirmation first when the reply is a bare answer (3 words or fewer); a longer reply is read
against every open action, the confirmation included. These questions parse only an exact yes
(optional terminal punctuation) as confirmation; no, unsure, skip or longer answers remain neutral,
keep the concern pending (it cannot close the case) and are not asked again for the same evidence.
Payment confirmations count towards the same maximum of three open actions as consultant questions.
If all three slots are occupied, the case stays open and a confirmation is offered when a slot opens.
Identity/contract hard flags still close immediately, including when a payment question is pending.

API (`api/`):

| Method | Path | Body / returns |
| --- | --- | --- |
| POST | /cases | `{student, listing?, landlord?}` -> Case |
| POST | /cases/{id}/evidence | multipart file + kind + note -> Case |
| POST | /cases/{id}/messages | `{text, evidence_ids?, action_id?, status?}` -> Case (`status` without `action_id`: 422) |
| POST | /cases/{id}/decide | Case: decide now on what is verified so far (waits for a running analysis; 409 once decided) |
| GET | /cases/{id} | Case |
| GET | /cases/{id}/decision | Decision or 404 |
| WS | /cases/{id}/stream | StreamEvent JSON |

### API details

- `api/main.py`: `create_app() -> FastAPI` builds Settings, repo (memory or mongo), EventBus, agents,
  context and `CaseService`, stores them on `app.state`, adds CORS from settings, and includes both routers.
  Module-level `app = create_app()`.
- Request models live in `api/` (not in contracts): `OpenCaseRequest(student, listing, landlord)`,
  `ReplyRequest(text, evidence_ids=[], action_id: str | None = None,
  status: Literal["done", "skipped", "impossible"] | None = None)`. The web app's action cards send
  `action_id` and `status`, while free chat sends only `text`. `CaseService.reply` passes both through
  to `conversation.parse`.
- `POST /cases/{id}/evidence`: multipart fields `file` (optional), `text` (optional, for pasted
  email), `kind`, `note`, `student_name`. Exactly one of `file` and `text` is required (422 otherwise).
- `WS /cases/{id}/stream`: on connect, send a `score_updated` with the latest score, then forward bus
  events as `event.model_dump_json()` until disconnect, then unsubscribe.
- Errors: unknown case gives 404, decided case gives 409, validation gives 422.

---

## 8. Quality gates

- `make check` = ruff check, ruff format --check, pyright, import-linter, pytest. Must pass before any push to `main`.
- import-linter contracts in `backend/pyproject.toml`:
  - **independence**: `app.agents.companies_house`, `app.agents.message_checker`,
    `app.agents.contract_checker`, `app.agents.emotion_classifier`, `app.agents.video_analysis`.
  - **forbidden**: `app.agents` and `app.aggregators` must not import `app.orchestrator`, `app.api`,
    `app.storage`, `app.intake`.
  - **layers**: `app.api` > `app.orchestrator` > (`app.aggregators`, `app.agents`, `app.intake`, `app.storage`) > `app.core` > `app.contracts`.
- Every agent folder has at least: one test that runs the real agent on a fixture case with `FakeLLM`
  and `FakeSearch`, and one test that its stub returns a valid `AgentReport`.
- No network in tests. Live calls only via `scripts/run_agent.py --live`.
- pre-commit runs ruff on staged files.

---

## 9. Contract change process

Contracts are frozen when Phase 0 merges. To change one:
1. Additive only (new optional field, new enum member) unless the whole team agrees.
2. One PR touching only `app/contracts/`, `fixtures/`, regenerated `web/src/types/contracts.ts`.
3. Post in the team chat, merge, everyone rebases. Never change contracts inside a feature branch.

# Workstreams

Who builds what after Phase 0, the timeline, and the brief to hand each coding agent.
Architecture: `docs/architecture.md`. Rules: `AGENTS.md`. Codebase overview: `CLAUDE.md`.

---

## 1. Parallel workstreams

Each workstream runs in its own git worktree and branch, with its own coding agent if wanted:

```bash
git pull
git worktree add ../rss-<ws> -b feat/<ws>-<short>
cd ../rss-<ws> && cp ../Warden/.env .env 2>/dev/null; make install && claude
# first prompt: "Read AGENTS.md, then do workstream <letter> in docs/workstreams.md"
```

| Person | Branches |
| --- | --- |
| Danny | `feat/a-orchestrator`, `feat/b-companies-house`, `feat/c-intake`, `feat/j-crosschecker`, `contracts/report-summary` |
| Georgi | `feat/d-message-checker`, `feat/e-emotion`, `feat/f-consultant` |
| Bill | `feat/g-contract-checker`, `feat/h-scoring-eval` |
| Audrey | `feat/i-web` (after the web shell merges and `docs/design.md` exists) |

Flip an agent to real locally with `AGENT_MODE_<NAME>=real` in `.env`. To see the question loop without
any real agents, run `DEFAULT_AGENT_MODE=real make dev`.

A workstream may edit ONLY its owned paths. Anything else is a contract change (see "Changing contracts" in AGENTS.md) or a message to the owner.

| WS | Owner | Owned paths | Deliverable | Done when |
| --- | --- | --- | --- | --- |
| A Orchestrator + API | Danny | `orchestrator/`, `api/`, `storage/mongo.py` | Real conversation parsing (LLM maps reply to actions), MongoDB wired, rerun-on-change verified | Full loop on a fixture with real agents flipped on |
| B Companies House | Danny | `agents/companies_house/` | Background check: register (number, status, age, officers), reputation (scam reports, negative reviews, redress, London Rogue Landlord Checker), contact details, postcode; Linkup with cited URLs | Hard-flags a dissolved match in `fake_agency.json`; a name with no match is high, not hard; clears an established agency |
| C Intake | Danny | `intake/` | Screenshot OCR via `LLMClient.describe_image`, then message extraction; audio later | A WhatsApp screenshot becomes `Message`s with sender and text |
| D Message checker | Georgi | `agents/message_checker/` | Rules (links, sort codes, payment words) + one LLM pass; facts: bank_account, email_domain, address, rent, deposit | Catches payment-before-viewing, pre-paid card, off-platform, overseas landlord in fixtures |
| E Emotion classifier | Georgi | `agents/emotion_classifier/` | Facts vs feelings for both sides; pricing fact vs area rent table | Splits pressure language from facts on fixtures |
| F Consultant | Georgi | `aggregators/consultant/` | `action_library.yaml` (candidate actions per check) + LLM ranking by score impact; returns [] when nothing useful remains | Picks sensible top 3 on each fixture; returns [] when all checks settled |
| G Contract checker | Bill | `agents/contract_checker/`; contract-specific evaluation in `backend/eval/` | Standalone PDF/text extraction, contract-local checks and a second LLM review; quoted JSON findings, questions and a shared-report adapter | Offline checks pass; paired synthetic evaluation records missed/unexpected issues, latency and API cost |
| H Scoring + evaluation | Bill | `aggregators/scoring/`, `backend/eval/` | Tune weights; synthetic case generator; eval script reporting catches and false positives. Danny's real case stays in `fixtures/private/` as the held-out test | Eval prints a table over all synthetic cases |
| J Cross-checker | Danny | `aggregators/crosschecker/`, orchestrator wiring | Generalist agent: reads all reports, flags disagreements quoting both agents, writes a recap the orchestrator relays | The utilities example (contract £60/month vs messages "bills included") gives one finding citing both agents and a recap message |
| I Web app | Audrey | `web/` | Starting from the web shell, keeping `src/lib/`, per `docs/design.md`: open case, upload, live agent progress, score + checks, chat with orchestrator, final decision | Works on mocks, then on the live API |

Agents that are not ready keep running as stubs, so the integrated app always works.

---

## 2. Timeline (Sat 14 to Sun 15 Nov)

| Time | Danny | Georgi | Bill | Audrey |
| --- | --- | --- | --- | --- |
| 15:15 to 16:15 | Phase 0 (done 15:15), review, push, web shell session, contracts/ts-types | Red flag lists + prompts for messages and emotion (no code needed) | Contract checklist + 6 synthetic cases | design.md, frontend plan, Figma |
| 16:15 to 18:00 | WS B (background check), report summary field | WS D, E | WS G | WS I from the web shell |
| 18:00 to 20:30 | WS J Cross-checker, WS C OCR, WS A; then flip real agents on, integrate | WS F | WS H | WS I on live API |
| 20:30 | **Gate: full live run on Danny's case** | | | |
| Overnight (optional) | Fixes | Prompt tuning | Eval numbers | Polish |
| Sun 10:00 to 11:00 | Feature freeze. Record 2-min video, write-up, README | | | Video edit |
| 11:00 to 11:45 | Buffer. **Submit to Devpost by 11:45** (hard close 12:00) | | | |

---

## 3. Out of scope for the MVP

Landlord side, property video analysis (stub only), call audio transcription (stub until WS C is done),
Synthesia avatar, user accounts, deployment beyond what the demo needs.

---

## 4. Workstream briefs (hand one to each coding agent)

Rules for every brief:

- Start with: read `CLAUDE.md`, `AGENTS.md`, this brief and `docs/architecture.md`, then the code in `backend/app/contracts/` and `backend/app/core/`. Do not edit outside the owned paths.
- LLM prompts live as Markdown files in the agent's `prompts/` folder and are loaded with
  `Path(__file__).parent / "prompts" / "<name>.md"`. Never inline long prompts in Python.
- Structured LLM output uses a Pydantic model defined inside the agent package (e.g. `agents/message_checker/models.py`),
  never a new type in `app/contracts`. Convert it to `Finding`/`Fact` before returning.
- Rules first, LLM second: anything a regex or lookup can catch reliably must not depend on the LLM.
- Every Finding needs at least one `EvidenceRef` with a short quote (under 200 characters). Web results
  must put the URL in the quote or the detail.
- Finding ids are stable: `f"{self.name}:{slug}"`, so reruns replace rather than duplicate.
- Use `supports="cleared"` when the evidence shows the check is fine (e.g. company active, 10+ years old,
  officers match). Clearing is as important as flagging: the score only drops through clears.
- Tests run offline with `FakeLLM`/`FakeSearch` and canned HTTP (`httpx.MockTransport`).
- Flip your agent to real with `AGENT_MODE_<NAME>=real` in your local `.env` once its tests pass.
- Finish with `make check` green, then a PR.

### WS A: Orchestrator conversation + MongoDB (Danny)

Owned: `app/orchestrator/`, `app/api/`, `app/storage/mongo.py`.
1. Replace `conversation.parse` with an LLM version. Input: open actions (id, check, text) and the
   student's message. Output model: `list[{action_id, status: done|skipped|impossible, answer, outcome}]`.
   Prompt rules: only mark an action done if the message answers it; "the agent refused" means `flags`;
   unclear means `neutral`. Keep the keyword version as a fallback when the LLM call fails, used only
   when the reply targets an action or exactly one action is open (built Sat 21:00: see
   `docs/architecture.md` section 7).
2. Have `parse` also return structured updates when the student gives them (company number, landlord
   name, rent, deposit, viewing date) and apply them to `case.landlord`, `case.listing` and `case.student`.
3. Add an `orchestrator_message` composer: one short, plain message per round that tells the student
   what changed and what to do next (LLM, max 60 words, from score delta + new actions).
4. `MongoCaseRepo`: one collection `cases`, `_id = case_id`, store `case.model_dump(mode="json")`,
   upsert on save. Same test suite as the memory repo, skipped when `MONGODB_URI` is empty.
5. Tests: parse fallback, structured updates, mongo repo (skippable), e2e loop with real conversation on FakeLLM.

### WS B: Companies House agent (Danny)

Updated Sat 18:30: this is now a background check (register, reputation, contact, property) in one agent.
The changes from the original brief below:
- Hard flags only from the register: a given company number that returns 404, or status dissolved or in
  liquidation. A company NAME with no match is suspicious (high) and asks for the number.
- Officer mismatch: medium, confidence 0.5 (shown, does not flip the check). `registered-active` clears
  with confidence 0.6 only.
- Facts: `company_number` (zero-padded to 8) and `email_domain` only. No `address` and no `landlord_name`:
  the cross-check compares those with the listing and the agent's name and would flag genuine cases.
- Evidence: `evidence_id` is `"companies_house"`, `"web"` or `"london_rogue_checker"`, with the URL in a
  `Source:` line in `detail`.
- Linkup only, at most 8 queries (deep for scam reports and reviews); one batched LLM call labels snippets.
  Only negative reviews and scam reports count; absence from a search gives no finding.
- Errors never count as "not found"; web failures give an info "could not run" finding; `timeout_s = 120`.

Original brief (superseded where it conflicts with the list above):
1. Client in `client.py`: `GET https://api.company-information.service.gov.uk/search/companies?q=<name>`,
   `/company/{number}` and `/company/{number}/officers`, with HTTP basic auth (API key as username, empty password).
2. Resolve the company: use `landlord.company_number` if given, else search by `company_name` and take
   the best match (normalised names equal, else the top result with a lower confidence).
3. Findings (check `landlord_identity`):
   - not found: critical, hard_flag only if the landlord presented as a company or agency
   - status not "active": critical, hard_flag
   - incorporated in the last 12 months: medium
   - no officer name matches `landlord.name` (when it is a person's name): medium
   - registered office is a known virtual-office address (small list in `virtual_offices.yaml`): low
   - active, older than 3 years, SIC code starting 68 (real estate): `supports="cleared"`, confidence 0.8
4. Redress scheme check via `ctx.search`: query `"<company_name>" property redress scheme OR "property ombudsman"`.
   No credible result: medium finding. A result from tpos.co.uk or theprs.co.uk naming the company: cleared, 0.7. Cite the URL.
5. Facts: `company_number`, `landlord_name` (from officers), `address` (registered office).
6. Questions when the name is ambiguous: "Ask the agent for their Companies House number."
7. Tests with canned JSON responses for: active old agency, dissolved, not found, new company.

### WS J: Cross-checker (Danny)

Owned: `app/aggregators/crosschecker/`, plus the wiring in `app/orchestrator/service.py`.
Why: each checker sees only its own slice of the evidence, so none of them can see that the contract
charges £60 a month for utilities while the messages say bills are included.
1. `async def review(case, rule_findings, ctx) -> AgentReport` with `agent="crosscheck"`: the rule-based
   findings from `orchestrator/crosscheck.py` (passed in, since aggregators may not import the
   orchestrator) plus LLM consistency findings, and a recap of at most 80 words in `summary` (after the
   `contracts/report-summary` change).
2. LLM input: each OK report's findings and facts (agent, title, detail, quotes) and short evidence
   excerpts. Output model per inconsistency: topic, agent_a, claim_a, quote_a, agent_b, claim_b, quote_b,
   check_id, severity.
3. Every inconsistency quotes both sides; drop any whose quotes are not in the source text. Category
   `consistency`, `supports="suspicious"`, check usually `contract_consistency` (payment topics:
   `payment_safety`). Never sets `hard_flag`; the rule-based address mismatch keeps its hard flag.
4. Stable ids `crosscheck:<topic-slug>`. Only call the LLM when 2+ reports are OK and their combined hash
   changed. Stub (`AGENT_MODE_CROSSCHECK=stub`, default) replays `fixtures/reports/crosscheck.json`.
5. Orchestrator: after the checker agents and `crosscheck.compare`, call `review`, store it as
   `case.reports["crosscheck"]`, emit the recap as an `orchestrator_message` when it changed, then
   `checks.update`, scoring and decision as before.
6. Tests: the utilities example gives one finding citing both agents; a made-up quote is dropped; rule
   findings pass through (the address hard flag still closes the case); no LLM call with fewer than 2 OK
   reports; stub works; the orchestrator emits the recap.

### WS C: Intake OCR (Danny)

Owned: `app/intake/`.
1. `ocr.py`: `async def screenshot_to_messages(image: bytes, llm) -> list[ExtractedMessage]` using
   `llm.describe_image` with a prompt that returns JSON `[{side: "left"|"right", time, text}]`.
   Right-hand bubbles are the student, left-hand bubbles the agent. Validate with a local Pydantic model.
2. Keep the raw OCR text in `Evidence.extracted_text` and create `Message`s with `channel="whatsapp"`
   unless the student's note says otherwise.
3. Later, if time allows: `audio.py` with a speech-to-text provider, making each speaker turn a Message with `channel="call"`.
4. Tests: FakeLLM returns canned JSON; assert Messages and sender mapping.

### WS D: Message checker (Georgi)

Owned: `app/agents/message_checker/`.
Evaluation fixes (Bill, delegated by the team): payment rules distinguish demands from denials and
post-viewing terms; owner facts require an explicit role; an owner abroad with local viewing access is
not an access warning. All payment hard flags now require student confirmation in the orchestrator,
while unrelated hard flags remain immediate. No/unsure preserves the concern and requests clarification.

1. `rules.py`: pure functions over `case.messages`, each returning findings:
   - payment before viewing: payment words (deposit, transfer, pay, holding fee, bank details) in agent
     messages AND no evidence of a completed viewing. payment_safety, critical, hard_flag when explicit.
   - pre-paid or untraceable payment: Western Union, MoneyGram, gift card, crypto, "pre-paid", Revolut/Wise
     to a personal name. payment_safety, critical.
   - sort code + account number pattern: extract a `bank_account` fact (mask all but the last 4 digits).
   - links: extract URLs; flag domains that imitate known sites (airbnb, spareroom, rightmove, zoopla,
     openrent) without being them. payment_safety, high.
   - off-platform move: "WhatsApp me", "email me directly", "text me on". in_person_viewing, low.
   - abroad, overseas, "out of the country", "my agent will give you the keys": in_person_viewing, high.
   - pose as a buyer, overpayment, refund the difference: payment_safety, critical.
2. `llm.py`: one LLM pass over the agent's messages, returning extra findings that the rules missed, with
   quotes. Drop any LLM finding whose quote is not a substring of a real message.
3. Clearing: messages that confirm an in-person viewing happened, or payment through a known agency portal:
   `supports="cleared"` on in_person_viewing or payment_safety.
4. Facts: bank_account, email_domain, address, rent_pcm, deposit, landlord_name when stated.
5. Tests: one per rule on small hand-written message lists, plus the full fixture.

### WS E: Emotional influence classifier (Georgi)

Owned: `app/agents/emotion_classifier/`.
1. LLM pass over all messages and `student.notes`, returning for each relevant message: `facts: list[str]`
   and `influence: list[{kind, quote, explanation}]`, where `kind` is one of
   urgency, scarcity, flattery, guilt, authority, jargon, sunk_cost, desperation.
2. Agent-side influence (urgency, scarcity, authority, jargon) gives findings on `no_pressure`
   (medium, raised to high if 3 or more distinct kinds).
3. Student-side desperation or sunk cost does not make the place more suspicious. Emit it as an `info`
   finding (category pressure) so the UI can show "how you might be feeling vs the facts".
4. Pricing: `area_rents.yaml` with median monthly room rent for about 15 London postcode districts
   (hand-built for the demo, labelled "approximate" in the UI). Rent 25% or more below the district median:
   fair_price, medium. Within plus or minus 15%: `supports="cleared"`, 0.6.
5. Tests: FakeLLM canned output; pricing thresholds.

### WS F: Consultant (Georgi)

Owned: `app/aggregators/consultant/`.
1. `action_library.yaml`: for each of the 8 checks, 2 to 4 candidate actions with `id`, `kind`, `text`
   and `why` (one line). Examples: ask for the company number; insist on an in-person viewing or send a
   friend; ask which deposit protection scheme and look it up; reverse image search the listing photos;
   ask for the landlord's ID and match it to the Land Registry title.
2. `propose_actions`: build candidates from the library for checks that are not CLEARED and have no
   open action and no action already asked. Rank by `contribution[check]` from the ScoreResult (largest
   first), then use one LLM call to reword the top `max_actions` to fit this case (mentioning the agent's
   name or the specific claim). If the LLM fails, use library text as is.
3. Return `[]` when no candidates are left (all checks settled, or every candidate already asked,
   skipped or impossible). This is what triggers the final decision, so test it.
4. Tests: ranking order, no duplicates, the `[]` case, LLM failure fallback.

### WS G: Contract checker (Bill)

Owned: `app/agents/contract_checker/`, with contract-specific evaluation in `backend/eval/`
and synthetic fixtures in `fixtures/cases/contract_checker/`.

The standalone first version is implemented. Its agreed scope and run commands are in
[README_BILL.md](../backend/app/agents/contract_checker/README_BILL.md) and the
[checker README](../backend/app/agents/contract_checker/README.md).

1. Entry point: `review_contract(data, filename, context, ctx)` accepts text-based PDF bytes or
   UTF-8 plain text and extracts the text itself. Supply explicit `ReviewContext` facts, including
   `assessment_date`; unknown applicability stays conditional. Scope is ordinary private tenancies
   in England. Scans, OCR and Word documents are excluded.
2. Review flow: structured LLM extraction, exact quote and amount validation, Python calculations
   and explicit-clause checks, then a second LLM pass challenging proposed findings. The maintained
   legal rule collection supplies applicability dates and official sources. Checks cover tenancy
   and holding deposits, fees, advance rent, tenancy/notice clauses, internal contradictions,
   missing schedules and potentially unlawful obligations.
3. Detailed JSON contains issues, rule-level passes, validated money/facts, questions and coverage.
   Issues include observed clause/page references, legal links where applicable, assumptions,
   uncertainty, importance and resolution conditions. Failed or incomplete reviews are explicit;
   a completed review is not a safety or authenticity verdict.
4. The existing `ContractCheckerAgent.run(case, ctx)` adapter accepts one already-extracted contract
   and keeps the frozen `AgentReport` schema. It exports concerns and supported contract facts:
   property address, landlord name, move-in date, unambiguous monthly rent and tenancy deposit.
   Conditional concerns have low severity and no hard flag. The stub remains available.
5. Integration boundary: rule-level passes use `supports="cleared"` in detailed JSON, but the adapter
   does not promote them to whole-check clears. Meeting a deposit amount cap does not establish
   `deposit_protection`. Agree finer clearing semantics and transport for the richer fields with
   Danny before upload-pipeline integration. Cross-source comparisons belong to WS J; this checker
   uses only the contract and explicit caller context. Deposit-protection information checks and
   ordinary costly-commitment advice are excluded.
6. Validation: offline tests cover extraction, calculations, evidence guards, challenge behaviour,
   adapter/stub compatibility and budget accounting. The 26-contract paired live evaluation completed
   with no missed or unexpected issue categories; these are development fixtures, not real-world
   accuracy estimates. See [results and measured cost](../backend/eval/CONTRACT_CHECKER_RESULTS.md).

Remaining integration work: connect raw uploads, agree shared-report clearing/field semantics, and
add persistent issue history with revision matching. IDs and hashes currently support identical
reruns only. The broader WS H scoring and system evaluation remain a separate deliverable.

### WS H: Scoring tuning + evaluation (Bill)

Owned: `app/aggregators/scoring/`, `backend/eval/`.
1. `eval/generate.py`: create synthetic cases as Case JSON (messages + contract text + listing) for each
   SpareRoom scam type (short-term let, fake Airbnb link, no live advert, fake agency, pre-paid card,
   "for sale", overpayment, bank transfer pressure) and 6 or more genuine cases. Save to `fixtures/cases/synthetic/`
   with a label file `labels.json` ({case_id: "scam"|"genuine"}).
2. `eval/run.py`: runs `CaseService` with real agents (or stubs) over every case, auto-answering no
   questions, and prints a table: case, label, final score, checks suspicious, verdict, correct?. Summary
   line: scams caught, genuine wrongly flagged.
3. Tune `weights.yaml` and the hard-flag list only through this table. Record the final numbers in
   `eval/RESULTS.md` for the write-up.
4. Danny's real case (`fixtures/private/`) is run once at the end as the held-out test, never tuned on.

### WS I: Web app (Audrey)

Owned: `web/`. Audrey works from `docs/design.md` (her design and frontend plan), starting from the web shell
already in `web/`. Keep `src/lib/api.ts` and the generated types as the data layer; replace everything else
freely. Functional checklist the final UI should still cover:
1. Screens: open case (property link, landlord or agency name, your name), case view, final decision.
2. Case view: upload area (drag and drop, kind picker, optional note); live agent list (started, finished,
   skipped, error) from the WebSocket; score with history sparkline; the 8 checks with state and reason;
   findings grouped by check, each with its quoted evidence; chat panel with orchestrator messages and
   open actions as cards the student can answer, skip, or mark impossible.
3. Facts vs feelings view for the emotion classifier findings.
4. Data layer `src/lib/api.ts` with two implementations behind one interface: mock (reads
   `fixtures/reports/full_case.json` and replays it as events) and live (`NEXT_PUBLIC_API_URL`).
   Switch with `NEXT_PUBLIC_USE_MOCK`.
5. Only types from `src/types/contracts.ts`. Never hand-write a contract type.
6. Design in Figma for the Best-Designed AI Product prize, and link the file in the README.

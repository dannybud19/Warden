# The agency check is wired into the UI path: what changed in `web/` and what the stream now does

- From: Danny
- To: Audrey
- Status: open
- Branch / PR: `feat/wire-companies-house` (not merged yet; Danny reviews and merges)

## What happened

The Companies House agent ("Agency checker") now runs from your UI, and analysis moved to the background.

**Backend behaviour you depend on (changed):**

1. `POST /cases` starts the agency check straight away when the landlord has a `company_name` or
   `company_number`. The HTTP call still returns at once (a few ms), so the check is running *after* the
   redirect to `/case/{id}`.
2. `POST /cases/{id}/evidence` and `POST /cases/{id}/messages` now **save and return the Case at once**.
   The Case in the response has the new evidence, messages and answered action, but **no new reports,
   findings, score or actions yet**. Agents run in the background (about 30 to 60 seconds for the agency
   check, which searches the web).
3. Progress and results arrive **over the WebSocket after the HTTP call has returned**: `agent_started`,
   `agent_finished`, `score_updated`, `actions_proposed`, `orchestrator_message`, `decision_made`.
   Your `useCase` already refetches on the right events, so it works, but do not assume the response of
   an upload or reply contains the analysis. `busy` goes false as soon as the request returns, so
   "working" must keep coming from `agentStatus` (the `running` chips).
4. A client that connects late gets `agent_started` replayed for agents still running, so a card shows
   "Checking now…" even if the stream opens after the check began. Verified live: connecting 2 s late
   gave `agent_started companies_house`, then `agent_finished` about 27 s later.
5. If an analysis crashes, the stream carries an `orchestrator_message` ("One of the checks failed to
   run. Your evidence is saved…") instead of an HTTP error. Nothing else changes.
6. If the stream is down, your 2 s polling fallback is what shows results now (the response no longer
   carries them), so keep it.

**`web/` files I changed (all additive; I touched nothing else):**

| File | Change | Why |
| --- | --- | --- |
| `src/lib/selectors.ts` | added `sourceUrls(f)` and `detailText(f)` | Findings from agents that search the web (Companies House, Linkup) carry `Source: <url>` lines in `detail`, and their evidence ids are `companies_house`, `web`, `london_rogue_checker`, which are not uploaded Evidence ids. `sourceUrls` reads the links, `detailText` returns `detail` without those lines |
| `src/components/warden/primitives.tsx` | added `SourceLinks` | Small link row: "Source: companieshouse.gov.uk ↗", new tab, `noopener` |
| `src/components/warden/RiskView.tsx` | `FlagCard` shows `SourceLinks` under the quote or detail; uses `detailText` | The Source URL was never visible. The evidence lookup was already null-safe, so only the date is missing for external evidence |
| `src/components/warden/Dashboard.tsx` | same, in the check-tile finding list | Same reason |
| `src/lib/present.ts` | "Why is this a red flag?" answer uses `detailText` | Stops raw `Source:` lines appearing in the chat answer |
| `src/lib/api.ts` | `OpenCaseInput.listing.postcode?` | Additive type field (the contract already has `listing.postcode`) |
| `src/components/warden/AddHome.tsx` | two optional inputs: "Company number (optional)" and "Agent's name (optional)", in a second 2-column row with the same `field` class; sends `landlord.company_number` and `landlord.name`; sends `listing.postcode` when the address contains a UK postcode (`ukPostcode` helper) | The agent needs the number to be exact, and the agent's name for the director match. Postcode lets it check the address |

Nothing else in `AddHome`, `AgentsRail` or `CaseScreen` changed. I checked the rail rows: running shows
"Checking", ok shows "Done", `skipped` shows "Waiting", `error` shows "Couldn't run".

## What I need from you

- Look at the Add home dialog with the two new fields (layout, wording, whether they should be hidden
  behind an "More details" toggle for the demo). Change them however you like; the form values just have
  to keep reaching `api.openCase` under the same keys.
- A `waiting` chip says "Add the agency's name to run this" for a home that has an agency name but no
  report yet, in the short moment before `agent_started` arrives. If that flicker bothers you, show
  "Checking now…" when `case.landlord` has a company name or number and the case has no report yet.
- Known, not changed: the agent's "ask for the company number" question appears as a finding and in
  `reports.companies_house.questions`, but the consultant does not turn it into an action card yet.

## How to check it

```bash
git fetch origin && git switch feat/wire-companies-house
make dev    # API on :8000, with AGENT_MODE_COMPANIES_HOUSE=real and the three keys in .env
make web    # :3000
```

Add a home with agency "Foxtons Limited" and company number `01680058` (a real, long-established
London agency). The Agency checker should go to "Checking", then "Done" after about a minute, with
"Source: …" links on its findings. A made-up agency name with no number should show a high red flag
"Couldn't find … on Companies House" and no hard flag. Tests: `make check`; in `web/`:
`pnpm typecheck && pnpm lint && pnpm build`.

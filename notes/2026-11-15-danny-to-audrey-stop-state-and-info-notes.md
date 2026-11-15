# Payment question isn't a scam verdict; info notes aren't flags

- From: Danny
- To: Audrey
- Status: open
- Branch / PR: `fix/web-stop-and-notes` (commit 26e4444, pushed, not merged)

## What happened

Three small fixes from `fix/ch-stop-headline` (ec49c19, 251413c, 503ccb2) are now applied to your
current `RiskView`. They are not cherry-picks. Your layout, styling and copy are unchanged apart
from the items below.

Files changed and why:

- `web/src/components/warden/RiskView.tsx`
  - `riskOf()`: the `stop` mood (an open payment question, no verdict yet) has its own amber state.
    It shows headline "Stop before you pay.", the real score on the gauge, and no danger styling.
    Before, it rendered like `red`: "Don't pay. Walk away from this one." and a score forced to 80+.
    The consultant asks the payment question on almost every home, so genuine agencies were being
    told to walk away.
  - Gauge label for `stop` is "Medium risk" with flags and "Unverified" without. "Unverified" fits
    inside the gauge; "Not proven yet" overflowed.
  - `IssueList`: info-severity findings show as one muted line (Info icon) under the issue rows.
    They are not counted in "· N issues".
- `web/src/components/warden/Dashboard.tsx`
  - `PILL.stop` is now amber (`Stop · don't pay yet`, amber dot), not red.
  - `AnswerCard`: only `red` counts as `danger`, so "Walk away" is no longer the primary button for
    `stop`.
- `web/src/lib/selectors.ts`: new `isRedFlag(f)` (suspicious and not info) and `infoNotes(c)`.
- `web/src/lib/present.ts`: `redFlags()` uses `isRedFlag`, which also feeds `mood()` and the flag
  counts. `TINTS.stop` is amber.
- `web/src/lib/homes.ts`: home cards count red flags with `isRedFlag`.
- `web/src/lib/dashboard.ts`: the story strip's "+N red flags" uses `isRedFlag`.

The mascot keeps its `stop` pose; it is the payment-checkpoint artwork.

## What I need from you

Review the branch and merge it if you are happy with it, or tell me what to change. If you would
rather word the amber state differently, the copy lives in `riskOf()` and `PILL.stop`.

## How to check it

- `cd web && pnpm typecheck && pnpm lint && pnpm build`: all clean. The one lint warning is in
  the generated `contracts.ts` and is already on `main`.
- Live check: run `DEFAULT_AGENT_MODE=real` on the backend and add a home, then paste a chat that
  asks for a deposit. You should see the amber "Stop before you pay.", "2 red flags", no
  "Walk away", and the "Rent above the area average" info finding as a muted line instead of an
  issue row. A neutral chat ("happy to arrange a viewing") gives "Unverified · 0 red flags",
  which fits inside the gauge.

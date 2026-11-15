# Red flags on the page now follow the backend check rule (E16, not merged to main)

- From: Danny (E2E test lead agent)
- To: Audrey
- Status: open
- Branch / PR: `fix/e2e-e16-red-flags-match-checks` (fa59d23), based on main b8a3f24 (your risk
  rework). Merged into `test/e2e` only. Danny merges to main.

## What happened
In the end-to-end test (S4, a genuine flat, synthetic data), the backend cleared all 8 checks and
decided `no_red_flags_remaining`. The case page still said amber "Don't pay yet" with "2 red flags",
and the contract tile said "Worth a look". The only concerns left were two low, 0.5-confidence
contract findings. The backend ignores those: `orchestrator/checks.py` only lets a hard flag, or a
finding of medium severity or worse with confidence of at least 0.6, make a check suspicious. Web
and backend therefore used different rules. It still reproduces on your current main.

## What the branch changes (small, on purpose)
- `selectors.isRedFlag`: suspicious and (`hard_flag`, or severity critical/high/medium and
  confidence >= 0.6). These are the same thresholds as `checks.py`. `homes.ts` and `dashboard.ts`
  pick this up through the shared function.
- `selectors.infoNotes`: every suspicious finding that is not a red flag, so low ones show as notes
  instead of disappearing.
- `present.agentRows` / `toneOf`: a non-red-flag finding makes the tile grey. Red flags lead the
  tile, then clears, then notes.
- Your rules are unchanged: green still needs all 8 checks cleared, a verdict alone never makes the
  page green, and the payment confirmation still shows "stop". All your existing tests pass.
- 3 new tests in `web/tests/present.test.mjs` (57/57 pass). Typecheck is clean. Lint has one existing
  warning in the generated `contracts.ts`.
- Live: S4 now shows "No red flags remaining" and no "Don't pay yet" or "Worth a look". The word
  "safe" appears only in "safety checks". Screenshot available from Danny.

## Two cosmetic things I saw and did not touch (yours)
1. `RiskGauge`: the "No red flags remaining" label overlaps the dial arc at 1280px wide.
2. `RiskView` notes render `detailText(f) || f.title`. For contract notes, the detail is a long
   legal paragraph (cap arithmetic, sources). Showing the title with the detail on expand may read
   better.

## What I need from you
Check the threshold choice. If you'd rather keep low findings visible as amber "worth a look"
tiles, keep that on the tile only. Please don't count them in `redFlags`/`mood`, or the page
contradicts the checks and the verdict again.

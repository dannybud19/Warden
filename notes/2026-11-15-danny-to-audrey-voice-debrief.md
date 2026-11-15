# Voice call debrief: CaseCall props, action cards, two RiskView display bugs

- From: Danny
- To: Audrey
- Status: open
- Branch / PR: `feat/voice-debrief`, merged into `main` (def16e8)

## What happened

The voice call now asks the case's open steps and sends the whole call to the orchestrator when it
ends (WS V). Your files that changed:

- `web/src/components/warden/CaseCall.tsx`
  - Props: `onAnswer` is gone. It now takes `caseData` (the `Case`) and `onDebrief(payload)`, as well
    as `context`, `onLine` and `onEnd`. `AgentsRail` passes these through as `callCase` and
    `onCallDebrief`. `CaseScreen` wires `onCallDebrief` to `api.debrief`, then `refresh()`.
  - Two client tools run in the browser only, with no backend call during a call:
    `get_next_questions` and `record_answer(action_id, answer, status)`. There is also a new
    dynamic variable, `open_questions`.
  - New call-bar states: "Checking what you told me…", "This home already has a verdict." (a 409
    when the home was decided during the call), and "Try again" after a failed save. If the bar
    unmounts mid-call (for example the chat is expanded), it still sends what was said.
  - Your orb shows `thinking` while the call is being checked (`phase === "checking"`), as well as
    while it connects. It shows `idle` on an error, a notice or a retry. I merged this into your new
    `WardenOrb` (7c74073) and kept your `micRef` and volume loop.
- `web/src/components/warden/ActionCards.tsx` (new), on the case page behind
  `SHOW_ACTION_CARDS = true` in `CaseScreen.tsx`:
  - It shows open steps first, then the last 4 answered steps. Statuses are To do, Done, Flagged and
    Skipped, shown as text plus an icon.
  - It has "I did it" and "Skip" buttons, with `motion` layout and status animations. Reduced
    motion comes from your `MotionProvider`.
  - While the constant is true, `NextStep` is not rendered, because the first step showed twice.
    Set the constant to false to get your `NextStep` back.
  - It is yours to review and restyle.
- `web/scripts/create-voice-agent.mjs`: new prompt, first message, both tools, and test values for
  the dynamic variables. The voice (Sheldon), `pickVoice` and the 5-minute limit are unchanged.
- `threads.ts` is unchanged. Call lines show once, including after a reload, so no dedupe was
  needed.

Two display bugs in `RiskView.tsx`. Neither is from this branch; both are visible in the W2
screenshots:

1. The green mood caps the gauge: `riskOf()` uses `value: Math.min(score, 35)`. A home scored 97/100
   shows "Low risk · risk 35/100" on the gauge while the chat says "Your risk score is 97/100".
2. The headline can contradict the cards: "No red flags so far" (green mood) shows while action
   cards say Flagged. The mood reads agent findings only, not step outcomes
   (`action.outcome === "flags"`), so a step the student answered with a red flag doesn't move it.

## What I need from you

1. Review and restyle `ActionCards`, and decide whether it replaces `NextStep` for good.
2. Fix or decide on the two `RiskView` display bugs above (your file, so I haven't touched it).
3. After your next voice change, run `cd web && node scripts/create-voice-agent.mjs` only if the
   prompt or tools change. It overwrites what's in the ElevenLabs dashboard.

## How to check it

- `cd web && pnpm typecheck && pnpm lint && pnpm build`
- Bug 1: open a case on a stack with no LLM key and `DEFAULT_AGENT_MODE=real`. Paste a short neutral
  chat, then compare the gauge with the score in the round message.
- Cards: `POST /cases/{id}/debrief` with an answer for an open step, then watch its card move to
  Done or Flagged.

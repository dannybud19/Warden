# Voice agent now gets what the checkers found: please test, one question first

- From: Georgi
- To: Danny
- Status: open
- Branch / PR: `fix/crosscheck-llm-address` (commit `2567e02`), pushed, not merged

## What happened

On a call, Warden only knew the verdict line, five red-flag titles and the open questions. It knew
nothing of what the checkers read in the chats, emails and contract. Now it gets a briefing built
in the browser from the case the orchestrator writes (no backend or contracts change):

- `web/src/lib/callQuestions.ts`: new `callBriefing(case)`. What was uploaded, the Cross-checker
  recap (`reports.crosscheck.summary`), Warden's last chat message, and up to 12 findings with
  their detail, red flags first. Capped at 3500 characters.
- `web/src/components/warden/CaseCall.tsx`: sends it as the `case_briefing` dynamic variable at
  call start, and adds a `get_case_briefing` client tool that rebuilds it mid-call.
- `web/scripts/create-voice-agent.mjs`: the prompt has a `{{case_briefing}}` section and is told
  to use it and not re-ask what it answers; the new tool and a placeholder are registered.

This is in your `web/` voice code (WS V); Georgi asked for it directly as we are wrapping up.

## What I need from you

Georgi's machine has no ElevenLabs key, so the agent is **not updated yet** and no live call was
made. Please test it. Before you run the script, one question:

**Does a call fail when the agent's prompt uses a dynamic variable the client does not send?**
I believe ElevenLabs rejects it. If so, running the script on the shared agent breaks calls for
anyone on web code without this commit (a deployed demo included) until they have it. Two ways
round it, your choice:

1. Merge this commit to `main` and redeploy first, then run the script; or
2. Run the script with `ELEVENLABS_AGENT_ID` unset to make a separate test agent, and leave the
   shared one alone until after the demo.

The other direction is harmless: new web code with the old agent just sends an unused variable.

## How to check it

```bash
git fetch origin && git checkout fix/crosscheck-llm-address
cd web && node scripts/create-voice-agent.mjs      # see the question above first
pnpm dev                                           # restart so it picks up the env
```

Open a home with uploads and findings, call Warden and ask "what have you found so far?". It
should answer from the findings and not ask for things already uploaded.

Run so far: `make check` green (1410 passed, 4 skipped); web `pnpm typecheck`, `pnpm lint` and
`pnpm test` (57) pass. There is no unit test for `callBriefing` yet, and no "Latest changes" line
in `CLAUDE.md` yet: add both if this is kept.

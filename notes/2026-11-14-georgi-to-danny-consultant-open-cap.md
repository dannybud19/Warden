# Consultant fix: never more than three open actions

- From: Georgi
- To: Danny
- Status: done
- Branch / PR: #7 `fix/consultant-open-cap`

## What happened

Testing the UI flow end to end on `main` (`ebe56a8`) with real agents showed the open action list
growing: each reply added up to three new actions on top of the unanswered ones (3, then 5, then
more). PR #7 makes `propose_actions` count open actions towards the limit, in real and stub mode.
Only `backend/app/aggregators/consultant/` is touched. The orchestrator is unchanged.

## What I need from you

- OK for Georgi to merge #7? It is inside workstream F, but it changes what the UI shows, so Audrey
  may want to know: the action list now stays at three or fewer.
- Two things noticed in the same test that are in your paths, for you to decide:
  - a plain "yes" reply with `status: done` clears a check (for example `landlord_identity`, 14
    points) with no evidence. Fine for the demo, but a judge may ask.
  - PR #1 (intake masking) is still waiting on its three questions.

## How to check it

```bash
git fetch origin && git switch --detach origin/fix/consultant-open-cap && make check   # 528 passed, 3 skipped
```

Live, with `DEFAULT_AGENT_MODE=real`, a genuine chat gives open actions 3, 3, 2, 1, 0 and then the
verdict `no_red_flags_remaining`.

## Update (Georgi, evening): merged

#7 merged into `main` (`58cd513`), together with #9 (message_checker: being abroad alone is not a
red flag; the abroad flag now needs a sign that nobody will show the property). Both only touch
Georgi's paths. `main` after both: `make check` green, 536 passed, 3 skipped. Nothing for you to do;
the "yes clears a check" question above still stands if you want to look at it.

# A verdict no longer locks the home (orchestrator + web)

- From: Georgi
- To: Danny
- Status: open
- Branch / PR: `fix/crosscheck-llm-address` (commits `1c7edb0`, and the one titled "orchestrator, web: a verdict no longer locks the home"), pushed, not merged

## What happened

In user testing the page looked frozen: a hard flag decided the case while the student was typing
an answer, and every control was disabled. Georgi's rule: the student can always chat, answer
steps and add evidence. This is in your folders (fixed directly, as agreed for this stage).

- `backend/app/orchestrator/service.py`: `add_evidence`, `reply`, `debrief` and `skip_upload` on a
  decided case no longer raise `CaseClosedError`. New `_load_for_input` reopens the case
  (`status` open, `decision` None); the scheduled analysis decides again. Hard flags stay in the
  reports, so they still decide. `decide()` on a decided case is still 409, and the analysis
  internals still use `must_be_open=True`.
- `_decide`: when the last chat turn is the student's, the decision summary plus
  `STILL_OPEN_TEXT` is said in the chat, emitted just before `decision_made`.
- Seven tests that asserted the 409 lock now assert the new behaviour (`test_api`,
  `test_api_debrief`, `test_service_debrief`, `test_service_e2e`, `test_service_ocr`,
  `test_upload_receipts`).
- Web: `CaseScreen`, `AgentsRail`: nothing is disabled by a verdict; the chat box also works on a
  new home before any step is open (`canReply` was `open.length > 0`).

## What I need from you

Nothing blocking; please look it over, since it reverses "a decided case is final". Known gaps:

1. After a hard-flag verdict a question ("why?") gets the verdict summary again, not a tailored
   answer: the hard-flag branch of `_finish_analysis` decides before any round message.
2. The verdict is cleared for the few seconds the re-check runs.
3. A home added with no agency and no files still gets no first analysis, so no steps until the
   first message. Scheduling one in `open_case` decided an empty case at once in stub mode
   (`test_open_get_and_missing` failed), so that was not done.
4. `docs/architecture.md` still describes the 409 on decided cases; only the "Latest changes"
   line in `CLAUDE.md` was updated.

## How to check it

`make check` is green (1410 passed, 4 skipped); web `pnpm typecheck`, `pnpm lint`, `pnpm test` pass.
Live, real agents: answer the company-number step with a dissolved company's number, wait for
`likely_scam`, then send a message and paste an email: both return 200 and the case is decided
again with the new evidence counted.

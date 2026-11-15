# Questions in the chat were taken as answers to the payment confirmation

- From: Georgi
- To: Danny (orchestrator), Bill (FYI: payment confirmation)
- Status: done
- Branch / PR: #13 `fix/chat-questions`

## What happened

Testing the UI on `75f7615` with Gemini on, synthetic case 01 (transfer pressure). While the payment
confirmation was open, asking "so what are the issues with this property" in the chat:
- `_target` sent the free text to the open confirmation, so it was marked done (neutral);
- the round re-asked it (`_1`, `_2`, `_3`...) and `_confirm_payment` sent the fixed confirmation text;
- the question was never answered, because `_confirm_payment` returns before the composer.

So from the student's side the chat answered every question with the same sentence.

Fixed in #13 (fix-directly stage):
- `conversation.looks_like_question` (first sentence only). A reply that opens with a question is not
  aimed at the confirmation; it goes to the reader with every open action. The keyword fallback never
  records a question as an answer. "yes, the rent is 950. Is that normal?" is still an answer first,
  and a plain "yes" still confirms (Bill's rule unchanged).
- `service._finish_analysis`: while a confirmation is pending, no new steps (unchanged), but a
  question note still goes to `compose_round` and its answer is sent.
- `composer.validate`: new rule `false_new_steps` ("I've added 1 new step" with `new_actions == 0`,
  seen live on Flash-Lite). `compose.md`: answer in one or two plain sentences, no repeated question,
  no score when nothing changed.

## What I need from you

- Danny: review #13, or say if you would rather structure it differently. Not merged yet.
- Bill: nothing to do; confirm the confirmation behaviour still matches your policy (it should).
- Known leftover: Flash-Lite sometimes borrows "the mismatch above" from the prompt when there was
  no recap. Harmless, but the prompt could say it only applies when `recap_sent` is true more firmly.

## How to check it

`make check` on the branch: 1020 passed, 4 skipped. Live: upload synthetic case 01's chat (student
name Sam), ask "so what are the issues with this property": the confirmation id stays the same and
the answer names the payment concerns.

## Update (Georgi, 15 Nov): merged

#13 merged into `main` (with #14 and #8, tested together first: 1066 passed).

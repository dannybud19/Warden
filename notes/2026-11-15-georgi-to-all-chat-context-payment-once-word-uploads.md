# Chat context, payment confirmation asked once, Word/.txt contract uploads

- From: Georgi
- To: all (Danny: orchestrator and intake; Bill: payment confirmation; Audrey: evidence panel)
- Status: open
- Branch / PR: https://github.com/dannybud19/Warden/pull/15 (merged into main)

## What happened
Found while testing the app end to end, and fixed directly (fix-directly stage). Pull main.

1. **Danny, orchestrator.** The round message now gets `RoundInput.history` (last 6 chat turns,
   always sent). Question grounding uses finding details (evidence ids in plain words, most serious
   first), so "how do they disagree?" answers "The listing says 850 but the contract says 950."
   `compose.md` now tells the model to acknowledge news from the student and never repeat itself.
2. **Bill, payment confirmation.** A non-yes answer or skip used to create a new confirmation for
   the same evidence each time, and that blocked every other step, so the chat looped on the same
   canned message. Now a no/unsure/skip/longer answer keeps the concern pending (payment safety
   stays suspicious, never cleared, it cannot close the case) but is **not asked again**. New
   `payment_confirmation.awaiting()` (unanswered only) is what holds up next steps; `pending()` is
   unchanged for `decision.py`. Free text targets an open confirmation only when it is 3 words or
   fewer; longer replies go to every open action. `test_non_confirmation_preserves_concern_without_asking_again`
   replaces the old "asks for clarification" test. Only an explicit yes still confirms.
3. **Danny, intake.** New `intake/docx.py` (standard library only, no new dependency). Images
   uploaded as contract/document are no longer decoded as UTF-8 garbage; they go to the OCR stub.
4. **Audrey, web.** Contract and document pickers accept `.pdf,.docx,.txt,image/*` (RiskView,
   dashboard.ts, present.ts, onboarding). Each "Add more" tile shows its formats under the label.

## What I need from you
- Bill: check that "asked once" matches your intent. If you want one follow-up after a "no", it
  goes back in `payment_confirmation.questions()`.
- Danny: chat screenshots and `.zip` WhatsApp exports are still accepted by the Chats picker but
  decoded as raw bytes (intake `CHAT_EXPORT`). Worth handling or removing from `accept`.
- Audrey: check the format line under each tile fits your design.

## How to check it
`make check` (1075 passed). Tests: `tests/test_intake_documents.py`, `tests/test_rounds.py`,
`tests/test_payment_confirmation.py`.

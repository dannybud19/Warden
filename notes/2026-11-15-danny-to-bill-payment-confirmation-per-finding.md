# Payment confirmation is now one per finding (E4, merged)

- From: Danny (E2E test lead agent)
- To: Bill
- Status: open
- Branch / PR: `fix/e2e-e4-payment-confirm-once` (67a6bb0), merged into `main` in 444f377

## What happened
Found in the end-to-end test (scenario S26): a chat uploaded as several screenshots made the
`message_checker:payment_before_viewing` finding's quotes grow. `payment_confirmation.action_prefix`
hashed the finding id **and** its quotes, so every new part gave a new digest: a second confirmation
was asked, "Your messages mention a payment concern" was posted twice, the first card stayed open for
ever, and a "yes" on the older card did not confirm the current finding (the case could not decide).

The fix changes your rule in one place:
- `action_prefix` hashes the **finding id only**: one confirmation per finding for good.
- `refresh(case)` (called in `service._finish_analysis`) rewrites the still-open card's text to the
  current quotes; no second card, no second message.
- `confirmed()` and `answered()` match by finding id, so a **yes still counts after the evidence
  grows**, and a no / unsure / skip is still **not asked again**. Only an explicit "yes" confirms; a
  non-yes keeps payment safety pending and never cleared (unchanged).
- A different finding id is still asked separately (unchanged).
- `test_confirmation_is_bound_to_the_quoted_evidence` was replaced by
  `test_confirmation_carries_over_when_the_evidence_grows`.
- Confirmations stored on old cases under the old quote-based digests no longer match (no migration).

## What I need from you
Confirm that "a yes carries over to the same finding when more quotes arrive" matches your policy.
If you want new evidence after a **no** to be asked again, say so and we'll add a narrower rule
(e.g. re-ask only when a new message, not a re-read of the same one, adds a quote).

## How to check it
`git switch --detach origin/main && make check`; tests in `backend/tests/test_payment_confirmation.py`
(`test_evidence_growing_keeps_one_open_confirmation`, `test_yes_still_confirms_after_the_evidence_grows`,
`test_no_is_not_asked_again_when_the_evidence_grows`, `test_a_different_finding_is_still_asked`).

# message_checker: red-flag list (v1, Sat 14 Nov)

Owner: Georgi (WS D). This is the spec `rules.py` and `llm.py` are built from. Source: the WS D brief in
`docs/workstreams.md`, the team design doc, and how `orchestrator/checks.py` reads findings.

## How findings land in the score (from `orchestrator/checks.py`)

- A finding makes its check SUSPICIOUS only if `severity >= medium` and `confidence >= 0.6`.
  Low and info findings are shown but do not move a check.
- Suspicious always beats cleared, so one clear cannot hide a flag on the same check.
- A cleared check lowers the score by `weight * clear_confidence`, so clear confidences are kept modest.
- A payment `hard_flag` is a candidate: the orchestrator first asks the student to confirm its
  quoted evidence. An exact yes closes as `likely_scam`; no/unsure/skip preserves the concern and
  asks for clarification. Other types of hard flag retain their immediate behavior.
- This agent does NOT flag pressure or urgency. `no_pressure` belongs to `emotion_classifier`.

One finding per rule id (`message_checker:<id>`); every matching message is added as an `EvidenceRef`
with its exact quote, so reruns replace rather than duplicate.

## Rules in code (`rules.py`, agent messages only unless stated)

| Id | Fires when | Check | Category | Severity | Conf. | Hard flag |
| --- | --- | --- | --- | --- | --- | --- |
| `payment_before_viewing` | An actual payment request with no earlier completed viewing; ignore denied and explicitly post-viewing-only instructions | payment_safety | payment | critical | 0.9 explicit, 0.7 otherwise | Candidate when explicitly before viewing, viewing is conditional on payment, or money is tied to holding the place/keys or an actual refusal |
| `untraceable_payment` | A positive request for money-transfer services, gift-card codes, prepaid stored value or crypto; not a denial, mere mention or ordinary prepaid debit card | payment_safety | payment | critical | 0.95 | Candidate, subject to student confirmation |
| `personal_emoney_transfer` | Revolut, Wise or Monzo named in a payment request, and the payee is not a company (no Ltd, Limited, LLP, Lettings, Estates next to it) | payment_safety | payment | critical | 0.6 | No |
| `overseas_bank_account` (addition) | An IBAN that does not start with GB, or a SWIFT/BIC code, in a payment request | payment_safety | payment | high | 0.8 | No |
| `lookalike_link` | A URL whose host contains airbnb, spareroom, rightmove, zoopla, openrent or booking but whose registered domain is not the real one | payment_safety | payment | high | 0.85 | No |
| `overpayment_refund` | Overpaid, refund the difference, send back the balance, pay more and I will return it | payment_safety | payment | critical | 0.85 | No |
| `pose_as_buyer` | Asked to say they are a buyer, friend or relative, or to pay as "friends and family" | payment_safety | payment | critical | 0.85 | No |
| `landlord_abroad` | Away (abroad, overseas, offshore, out of the country) or keys handed over by courier or a third party, **and** nobody will show the property: a viewing refusal or a key hand-off after payment, with no offer of a viewing through someone else. Being away alone does not fire | in_person_viewing | property | high | 0.8 | No |
| `viewing_refused` (addition) | Viewings not possible, cannot show it, no viewings, video only, said by the agent after the student asked to view | in_person_viewing | property | high | 0.85 | No |
| `off_platform_move` | WhatsApp me, email me directly, text me on, contact me on Telegram | in_person_viewing | identity | low | 0.6 | No |

Payment request word list: deposit, holding fee, holding deposit, first month, rent in advance, transfer,
pay, send, bank details, sort code, account number, "once everything is paid". A message counts as a
request when a payment word appears with an instruction or condition (send, pay, transfer, to hold, to
secure, once paid), or with bank details.

Completed viewing evidence: thanks for coming, nice to meet you, good to see you (either side), or the
student saying "I saw the flat" or "I viewed it". "I saw your advert" does not count, and neither does
an offered slot. A message such as "you pay nothing until you have viewed" is not a payment request.

### Clears (`supports="cleared"`)

| Id | Fires when | Check | Conf. |
| --- | --- | --- | --- |
| `viewing_completed` | Completed viewing evidence, and neither `landlord_abroad` nor `viewing_refused` fired | in_person_viewing | 0.7 |
| `viewing_offered` | The agent offers specific slots or an office address, no completed viewing yet, no refusal | in_person_viewing | 0.4 |
| `payment_after_viewing_via_portal` | Payment asked for only after a completed viewing, through an online portal, card at the office or the listing platform, and no payment flag fired | payment_safety | 0.5 |
| `deposit_scheme_named` (addition) | The agent names TDS, DPS, mydeposits or "deposit protection scheme" | deposit_protection | 0.4 |

### Facts

| Fact | How | Notes |
| --- | --- | --- |
| `bank_account` | Sort code `\d{2}-\d{2}-\d{2}` plus an 8-digit account number, or an IBAN | Masked to the last 4 digits: `sort **-**-56, account ****1234` |
| `email_domain` | Domain of any email address in agent messages or `landlord.email` | Free webmail on its own is not a flag |
| `address` | The first UK postcode in the chat, with the address text before it | Only the first one: later postcodes are often the agency's office, and the crosscheck would report a mismatch |
| `rent_pcm` | `£` amount next to pcm, per month, a month, monthly | Own money parser: `£1,384.00` becomes `1384` |
| `deposit` | `£` amount next to deposit (not "holding deposit") | Same parser |
| `landlord_name` | LLM only, full name and affirmative owner/landlord role in the cited message | Reject invented full names and managing-agent names; omission does not verify identity |

## LLM pass (`llm.py`, one call)

The model sees the whole chat and the list of rule ids that already fired. It returns only flags from a
fixed list, each with a message id and an exact quote. Code then maps flag to check, category and
severity. The model never sets `hard_flag`, and its confidence is capped at 0.8.

| Flag | What it is | Check | Category | Severity |
| --- | --- | --- | --- | --- |
| Any rule id above | A paraphrase the word lists missed ("I'm on a rig near Stavanger until March") | as the rule | as the rule | as the rule, never hard |
| `escrow_story` | Money to be "held" by Airbnb, Booking.com, TripAdvisor or a courier until the student approves | payment_safety | payment | critical |
| `id_documents_early` | Passport, ID, bank statements or payslips wanted before any viewing | landlord_identity | identity | high |
| `identity_inconsistent` | The name, company or role changes within the chat, or differs from the case's landlord | landlord_identity | identity | medium |
| `refuses_details` | Asked for a company number, office address or proof of ownership and avoids answering | landlord_identity | identity | medium |
| `no_checks_needed` | No references, no contract or no right-to-rent check needed; sublet without the owner knowing | right_to_let | property | medium |
| `other` | Anything else that is clearly a scam signal | chosen by the model from the 7 non-pressure checks | chosen | capped at medium |

Guards in code:

- Drop any LLM finding whose quote is not an exact substring of the message it names.
- Drop an LLM finding whose id already fired from a rule.
- Reject payment-method claims contradicted by their message and abroad claims without an access
  barrier. Flags must cite an agent message, not a student's hypothetical question.
- If the LLM call fails or times out, return the rule findings alone with status `ok`.

## Expected result on the fixture cases

| Case | Should fire | Should not fire |
| --- | --- | --- |
| `fake_agency` | `payment_before_viewing` (explicit, hard), `landlord_abroad`, `viewing_refused`; fact `bank_account` ending 1234 | any clear |
| `overseas_landlord` | `untraceable_payment` (hard), `payment_before_viewing` (explicit, hard), `landlord_abroad`, `viewing_refused` | any clear |
| `genuine_flat` | `viewing_completed`, `payment_after_viewing_via_portal`, `deposit_scheme_named`; facts `deposit` 1384 | any flag |

## Open points

1. `personal_emoney_transfer` is critical as the brief says. Genuine private landlords do use these, so
   it is the first rule to revisit if the evaluation shows false positives.
2. `off_platform_move` sits on `in_person_viewing` as the brief says, though it says more about identity.
   It is low, so it never moves a check either way.
3. Three additions to the brief are marked "(addition)". Georgi confirmed keeping all three.

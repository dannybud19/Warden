# Demo cases (synthetic people, real listings)

Each case starts from a **real, live Rightmove listing** (checked Sun 15 Nov, 10:45). Paste the link and the listing reader fills the form.
Everyone in the chats, emails and contracts is invented (except the student, Audrey Leo, audrey17leo@gmail.com). Bank details are fake.
**No real agent is accused of anything:** in red, a stranger copies a real listing; in yellow, a stranger claiming to be the owner goes around the real agent; in green, the agent behaves properly.

At onboarding type **Audrey**. Upload order: link, WhatsApp .txt, email (paste), contract PDF, screenshot.

---

## 1. Red: cloned listing scam

**Link:** https://www.rightmove.co.uk/properties/89251659
Real listing: Kingston House South, Ennismore Gardens, South Kensington SW7 · 2 bed · £8,645 pcm · deposit £9,975 · Relo Redac Strattons.

**Story:** "David Harrington" copied it to Facebook Marketplace for **£950**, says he's the owner working in Dubai, can't show it, keys by DHL after payment.

**Files:** `WhatsApp Chat with David Harrington.txt`, `email_from_agent.txt`, `tenancy_agreement.pdf`, `payment_details_screenshot.png`

**Red flags:** price 89% below the real listing, different agent name (Kensington Crest Lettings Ltd, gmail, not on Companies House), no viewing, pay to a personal name, bank details changed, fake secure-payment link, passport + selfie, 24-hour deadline and guilt, contract says Flat 2 (chat says Flat 4), deposit 2 months, non-refundable clause.

**Say on the call:** "He says he's a doctor in Dubai so he can't show me. The same flat is on Rightmove for over eight thousand a month. He wants £2,850 today and now he's sent new bank details for Global Property Holdings. I haven't paid."

**Expected:** `likely_scam`, red.

---

## 2. Yellow: "owner" going around the agent

**Link:** https://www.rightmove.co.uk/properties/88750473
Real listing: Whitechapel High Street, London E1 · 1 bed · £2,800 pcm · Letly.

**Story:** "Tom Hughes" says he's the owner and offers **£2,300** direct if she skips the agent. Video tour done, in-person viewing offered on Sat 21st. Names match across chat, contract and bank account.

**Files:** `WhatsApp Chat with Tom Hughes.txt`, `email_from_landlord.txt`, `tenancy_agreement.pdf`, `holding_deposit_request_screenshot.png`

**Issues:** ownership not proven (going around the listed agent), £500 holding deposit before the in-person viewing, £150 admin fee (banned), deposit 6 weeks (£3,185, cap is 5 weeks), no protection scheme, tenant pays repairs under £200.

**Say on the call:** "I did a video tour and it matched the photos. He'll show me in person on the 21st. He says he owns it and Letly only advertise it. He wants £500 by tomorrow to hold it."

**Expected:** amber, `not_verified` or `proceed_with_care`. Advice: view first, check the owner on the Land Registry or ask Letly, no admin fee, deposit max 5 weeks and protected. (Could tip to red because of the off-agent discount: that is a defensible result too.)

---

## 3. Green: looks a bit off, actually safe

**Link:** https://www.rightmove.co.uk/properties/94073190
Real listing: Carlow Street, Camden NW1 · studio · £2,275 pcm · deposit £2,625 · Chestertons, Camden & Primrose Hill.

**Story:** "Sophie Bennett" from the branch. Landlord lives in Singapore, "two other applications", money before signing.

**Files:** `WhatsApp Chat with Sophie Bennett - Chestertons.txt`, `email_from_agent.txt`, `tenancy_agreement_draft.pdf`, `holding_deposit_form_screenshot.png`

**Safe because:** in-person viewing done, same agent as the listing (registered company), agency email domain, pay only to the agency client account, holding £525 = 1 week (legal cap), deposit £2,625 = 5 weeks and matches the listing, DPS protection, no fees, Right to Rent checked in person, everything matches across listing, chat, email and contract.

**Say on the call:** "I viewed it in person on Wednesday with Sophie from Chestertons. The landlord lives in Singapore. The holding deposit goes to the Chestertons client account and the deposit is protected with the DPS. I haven't paid yet."

**Expected:** green after answering, `no_red_flags_remaining` or `proceed_with_care`. Relies on the E6 and E8 fixes (now on main).

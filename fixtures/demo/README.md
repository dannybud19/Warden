# Demo cases (synthetic)

All people, accounts and messages here are invented for the demo. Bank details are fake.
Phone numbers are left out. Student in every chat: **Audrey Leo** (audrey17leo@gmail.com). Type "Audrey" at onboarding so the app knows which side is you).

Order to upload in each case: listing form, then WhatsApp .txt, then email (paste), then contract PDF, then screenshot.

---

## 1. Red: classic overseas-landlord scam

**Form**

| Field | Value |
| --- | --- |
| Address | Flat 4, 14 Cromwell Road, London SW7 2RL |
| Area | Kensington |
| Rent | £950 pcm |
| Deposit | £1,900 |
| Landlord | David Harrington |
| Agency | Kensington Crest Lettings Ltd (no company number given) |
| Platform | Facebook Marketplace |

**Files:** `WhatsApp Chat with David Harrington.txt`, `email_from_agent.txt`, `tenancy_agreement.pdf`, `payment_details_screenshot.png`

**Built-in red flags:** no viewing, keys by DHL after payment, rent far below area, pay to a personal name that isn't the landlord or agency, bank details changed mid-chat, fake "secure payment" link, passport + selfie request, 24-hour deadline and guilt pressure, gmail address for a "Ltd", agency not on Companies House, contract says **Flat 2** (listing says Flat 4), deposit 2 months (over the 5-week cap), non-refundable clause, landlord can change the account by message.

**Say on the call:** "He says he's a doctor in Dubai so he can't show me. I asked for a video call and he said his hospital doesn't allow it. He wants £2,850 today and now he's sent new bank details for a company called Global Property Holdings. I haven't paid yet."

**Expected:** `likely_scam`, red, Stop before you pay.

---

## 2. Yellow: real private landlord, but unsafe terms

**Form**

| Field | Value |
| --- | --- |
| Address | Flat 3, 79 Whitechapel High Street, London E1 7QX |
| Area | Whitechapel |
| Rent | £1,300 pcm |
| Deposit | £1,800 |
| Landlord | Thomas Hughes (private, no agency) |
| Platform | SpareRoom |

**Files:** `WhatsApp Chat with Tom Hughes.txt`, `email_from_landlord.txt`, `tenancy_agreement.pdf`, `holding_deposit_request_screenshot.png`

**Built-in issues (not a scam):** wants a £300 holding deposit before the in-person viewing (video tour only so far), £150 admin fee (banned by the Tenant Fees Act), deposit 6 weeks (£1,800, cap is 5 weeks = £1,500), deposit not protected in a scheme, tenant pays repairs under £200. Good signs: names match across chat, contract and account; real address given; offers in-person viewing; rent fair.

**Say on the call:** "I did a video tour and it matched the photos. He's back in London on the 21st and I can view in person then. He said he can put the deposit in a scheme if I ask. He wants the £300 by tomorrow."

**Expected:** `not_verified` or `proceed_with_care`, amber. Advice: view in person before paying anything, refuse the admin fee, deposit max £1,500 and protected, check the owner on the Land Registry.

---

## 3. Green: looks a bit suspicious, actually safe

**Form**

| Field | Value |
| --- | --- |
| Address | Flat 6, 18 Ossulston Street, London NW1 2DB |
| Area | Camden |
| Rent | £1,950 pcm |
| Deposit | £2,250 |
| Landlord | Wei Lin (overseas, managed by agent) |
| Agency | Foxtons Limited, company number 01680058 |
| Platform | Rightmove |

**Files:** `WhatsApp Chat with Sophie Bennett - Foxtons.txt`, `email_from_agent.txt`, `tenancy_agreement_draft.pdf`, `holding_deposit_form_screenshot.png`

**Looks suspicious because:** landlord lives abroad, rent below nearby flats, "two other applications, apply soon", money asked before signing, bank transfer.
**Actually safe because:** in-person viewing done with the agent, real registered agency (Companies House), email from the agency domain, pay only to the agency client account (not a person), holding deposit = 1 week (£450, legal cap), deposit = 5 weeks (£2,250) protected with the DPS, no fees, agent warns against paying anyone else, Right to Rent checked in person with a gov.uk share code, everything matches across chat, email, contract and form.

**Say on the call:** "I viewed the flat in person on Wednesday with Sophie from Foxtons. The landlord lives in Singapore, that's why it's cheaper. The holding deposit goes to the Foxtons client account and the deposit is protected with the DPS. I haven't paid yet."

**Expected:** after answering the questions, `no_red_flags_remaining` or `proceed_with_care`, green. Needs the E8 fix merged (established agency reputation), otherwise review noise can make Foxtons read as suspicious.

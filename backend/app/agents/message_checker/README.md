# message_checker

Owner: Georgi (WS D). Needs: `messages`.

## What it does

Reads the chat and email messages and reports scam signals, things that look fine, and stated facts.
The full list of flags, with check, severity and confidence for each, is in `red_flags.md`.

- **Flags:** payment before viewing, untraceable payment, transfer to a personal e-money account,
  non-UK bank account, lookalike links, overpayment and refund, asked to pose as a buyer, landlord
  abroad, viewing refused, off-platform move. The LLM pass can add: escrow story, ID documents wanted
  early, changing identity, refusing details, no checks needed.
- **Hard flags** (close the case): untraceable payment; payment before viewing when the chat also
  rules out a viewing or ties the money to holding the place or to the keys.
- **Clears:** viewing completed, viewing offered, payment after a viewing through a portal, deposit
  scheme named. A clear is dropped when a medium or higher flag sits on the same check.
- **Facts:** `bank_account` (masked to the last 4 digits), `email_domain`, `address`, `rent_pcm`,
  `deposit`, and `landlord_name` (LLM, full names only).
- Bank patterns also read the masked forms intake stores (`**-**-56`, `****1234`,
  `DE** **** **** 3000`), so masking uploads does not hide payment or overseas-account flags.
- It does not flag pressure or urgency. That is `emotion_classifier`.

## How it works

| File | Role |
| --- | --- |
| `catalog.py` | Every flag and clear: check, category, severity, confidence, wording |
| `rules.py` | Pattern rules and fact extraction. Pure functions, no I/O |
| `llm.py` | One LLM call (`prompts/extra_findings.md`) for what the rules missed |
| `models.py` | Shape of the LLM's reply |
| `agent.py` | Runs rules, then the LLM pass, merges and reconciles |

Guards: the LLM picks flag names only, so severity and check always come from `catalog.py`. It can
never set a hard flag, its confidence is capped at 0.8, and a finding whose quote is not found word
for word in a message is dropped. If the LLM call fails, the rule findings are returned on their own.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent message_checker ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent message_checker <case.json> --live   # real LLM
```

Without `--live` (or without `ANTHROPIC_API_KEY`) only the rules run. Switch it on in the full app
with `AGENT_MODE_MESSAGE_CHECKER=real` in your local `.env`. `stub.py` still replays
`fixtures/reports/message_checker.json`.

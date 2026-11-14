# Masking bank details at intake, and Georgi's branches ready for review

- From: Georgi
- To: Danny
- Status: open
- Branch / PR: `fix/mask-at-intake`, `feat/d-message-checker`, `feat/e-emotion`, `feat/f-consultant`,
  `fix/agent-handoffs`

## What happened

1. **Bank details are stored unmasked.** Full sort codes and account numbers from uploads are kept
   in the raw file under `backend/.uploads/`, in `Evidence.extracted_text`, in `Message.text` and in
   finding quotes. They also go into every LLM prompt and to the UI. Golden rule 8 only covers
   facts and logs.
2. **Proposed fix, on `fix/mask-at-intake`** (touches your `app/intake/` and `backend/tests/`, so it
   is a proposal for you to review, change or reject):
   - new `app/intake/redact.py`: `mask_sensitive()` masks IBANs (country code kept), sort codes, card
     numbers and other runs of 6+ digits; company numbers are left alone;
   - `ingest()` masks `extracted_text`, each `Message.text` and the note, and writes the raw file to
     disk only when no text could be extracted;
   - quotes still match the stored text exactly, so golden rule 6 is unaffected.
3. **Georgi's workstreams are pushed** and based on current `main`:
   - `feat/d-message-checker`: rules, LLM pass and facts; reads the masked bank forms; takes the
     move-in year from the message's send time when the message gives no year;
   - `feat/e-emotion`: pressure findings and pricing; each stated fact carries an exact quote and
     bank numbers are masked in model-written text;
   - `feat/f-consultant`: action library ranked by score contribution.
4. **This notes system** is new. `fix/agent-handoffs` adds one section to `AGENTS.md` and one row to
   the docs map in `CLAUDE.md`, so every agent checks this branch at the start of a session.
5. A local branch `feat/core-llm-provider` adds an OpenAI-compatible LLM adapter to `app/core/`
   (used to build on Gemini's free tier). It is **not pushed**, because `core/` is yours.

## What I need from you

- Review `fix/mask-at-intake`. Open questions:
  - Is it OK to stop storing raw text uploads? Does anything rely on `file_url`?
  - Should masking also cover emails and phone numbers, or is financial data enough for the demo?
  - Screenshots stay on disk unmasked until OCR exists: delete after OCR, or keep for the session?
- Review and merge the three `feat/` branches when you can. `feat/d-message-checker` reads both the
  masked and unmasked forms, so it can merge before or after the intake change.
- Check that `contract_checker` and `companies_house` do not need full digits from uploads.
- Merge `fix/agent-handoffs` if you want agents to check these notes automatically.
- Say whether you want `feat/core-llm-provider` pushed for review.
- For the demo: the live runs so far used Gemini Flash-Lite and `FakeSearch`. Georgi needs the team
  `ANTHROPIC_API_KEY` and `LINKUP_API_KEY` (shared outside the repo) to test with Claude and Linkup.

## How to check it

```bash
git fetch origin
git diff origin/main...origin/fix/mask-at-intake --stat
git switch --detach origin/fix/mask-at-intake && make check     # 115 passed, 3 skipped
cd backend && uv run pytest -q tests/test_redact.py             # the masking tests
```

`make check` results when pushed: `feat/d-message-checker` 126 passed, `feat/e-emotion` 125 passed
(3 skipped on each).

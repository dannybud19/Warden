# Upload recovery and email PDFs — 15 November 2026

Implemented on `fix/bill-upload-recovery`, based on `main` at `878bd51`.

## What was wrong, with examples

- **Silently hidden:** New case started each upload and discarded errors. If `chat.txt` succeeded
  but `contract.pdf` failed, the case opened without saying the contract was missing or offering retry.
- **Incorrectly read:** Email PDFs were decoded as UTF-8 bytes. The checker received
  `%PDF-1.7…` and PDF instructions instead of “Your viewing is confirmed for Tuesday.” HTTP 200
  only meant that the evidence record had been saved.
- **Temporarily disabled (fixed Sun 15 Nov):** while a screenshot upload waited for OCR, Add/Paste
  controls were disabled until that request finished, and a final decision disabled uploads for good.
  Now uploads are queued and never disabled, and a home never closes.

## Result

The New case wizard registers its initial files before checks start. Both new and existing cases use
a shared upload queue, showing every filename and progress on the case page. Successful uploads stay
saved when another file fails. **Retry — select file** always requires selecting the original file
again; files are never retained for an automatic retry. Browser session storage holds metadata only.

Each initial attachment stays pending until it is successfully read or the student explicitly
chooses **Continue without this file**; meanwhile the case is graded live on the files it has. Skipping never clears a check.
The backend stores this manifest beside the shared Case, without changing the frozen contracts. Mongo
preserves it across API restarts; memory storage remains temporary like its cases. The case page reloads
server progress and can recover a lost upload response without sending the file again. Older analyses
also wait for queued reruns before deciding, so the last attachment is assessed first.

Email PDFs now use selectable text and OCR for pages without a text layer, preserving page order.
If a nonblank scanned page fails, the whole file is marked unreadable rather than analysing a partial
email. Extracted/OCR text is masked before it reaches checkers. The original Case-only upload response
remains available; the UI opts into a receipt with `evidence_id` and `read_error`. Identical retries do
not duplicate evidence, and an explicitly retried failed extraction updates that evidence in place.

## Limits and setup

- Team dependency update: **PDFium (`pypdfium2`) and Pillow** were added to the backend manifest and
  lockfile. Run `uv sync` from `backend/`, then restart the API. No new API key is needed: OCR uses the
  existing vision client and incurs its normal provider charges. Text-only PDFs need no LLM call.
- Email PDFs: 10 MiB, 20 pages, at most 5 nonblank scanned pages, 200,000 text characters. Password-
  protected files need an unlocked copy. PDF parsing/rendering has a 15-second process deadline;
  OCR shares a 100-second deadline. Pages render at up to 1,800 pixels on their longest side.
- The new PDF OCR is for **Emails**. Contract/document PDF extraction and the one-readable-contract
  limitation are unchanged. Audio/video uploads say they are stored without claiming analysis.
- A retry uses the original filename and size. For a different/smaller file, **add the replacement
  first** using Add more while the case is held open, then continue without the original file.

## Verification

**1,408 backend tests passed; 4 optional Mongo integration tests skipped. 46 frontend tests passed.**
Ruff, formatting, Pyright, all three import rules, TypeScript and the production build passed.
Frontend lint has no errors and one pre-existing unused-disable warning in generated contract types.

New regressions cover text/scanned/mixed PDFs, real PDF rendering with fake vision, OCR failure and
timeout, blank pages, size/page limits, redaction, partial upload failure, mandatory reselection,
lost-response deduplication, reload recovery, explicit skip, decision holds, stale-analysis races,
and offline Mongo document persistence. The production attachment panel is rendered in a test to
check filenames, failure labels, file inputs and skip controls. No live API spend was used for these tests.

Browser automation still reports “The browser access host is unavailable”; the teammate's original
case URL is unavailable too. The native picker and complete browser wizard have **not** been exercised.
Manual check: attach a chat and PDF in New case, inspect both outcomes, interrupt one upload, reload,
then reselect it or explicitly skip it. On an existing open case, upload both selectable and scanned
email PDFs. Confirm that Add/Paste re-enables after completion and failures remain visible.

The earlier audit found the existing open-case Add/Paste controls enabled (8/8), disabled during a
request or after a final decision (8/8), and email-PDF failures on both entry points. The OpenRent photo
cache fix (`v=2`) from that audit remains unchanged.

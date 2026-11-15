# Upload verification — 15 November 2026

Checked on `fix/bill-upload-verification`, based on `main` at `935552b`.
The original screenshot's case URL was unavailable, and browser automation reported
“The browser access host is unavailable”. These results combine production-component rendering,
offline API requests and source inspection; they do not establish that the native file picker works
in the teammate's browser.

## Finding

There is no blanket failure to add files to open cases. The screenshot shows all Add/Paste buttons
disabled. `CaseScreen.tsx` passes `closed || state.busy` to `EvidencePanel`: uploads are disabled
after a final decision and while a request is running. The API independently rejects decided-case
uploads with HTTP 409. The exact screenshot could therefore be a closed case or an in-flight request;
its cause cannot be confirmed without the case state. The panel does not explain this restriction.

Rendering the actual `EvidencePanel` through React's server renderer produced:

| State | Enabled Add/Paste controls | Disabled controls |
| --- | ---: | ---: |
| New open case | 8 | 0 |
| Existing open case with evidence | 8 | 0 |
| Decided case | 0 | 8 |
| Upload in progress | 0 | 8 |

The new-case wizard uses separate labelled file inputs. It retains one file per category, creates the
case, then starts the uploads and navigates to the case screen. Its upload requests use the same API
as the existing-case panel.

## Defects that remain

1. **New-case upload errors are hidden.** `Onboarding.tsx` launches each upload without waiting and
   ends every request with `.catch(() => {})`. A failed request has no retry or visible error. This
   includes HTTP 409 if an early decision closes the case before another initial file is attached.
   The backend already tests rejection when a case closes during image extraction. Source inspection
   establishes the missing error handling; the wizard's complete browser flow was not exercised.
2. **Email PDFs are not extracted.** Both screens advertise PDF under Emails, but
   `backend/app/intake/service.py::_read_file` decodes email bytes as UTF-8. A real synthetic PDF was
   accepted with HTTP 200 and its raw `%PDF` content saved as email text on both new and existing cases.
   The same PDF uploaded as a contract or document was extracted correctly. This needs an intake fix.
3. **Disabled controls have no explanation.** The screenshot is consistent with existing case-locking
   behaviour. Showing the reason is a UI improvement; accepting new evidence after a final decision
   would require a separate product decision and backend change.

No upload behaviour or case-closing policy was changed during this verification.

## Checks performed

- **76 existing API/intake tests passed**, covering file uploads, Word, images, zip exports, failures,
  background extraction and decided-case rejection. All ran offline.
- **32 additional offline multipart requests:** 16 file/kind combinations on a fresh case and on a
  case already containing chat evidence. All 32 were stored. Of 30 text/image requests, 28 yielded the
  expected extracted text and the two email PDFs failed extraction. The two video requests stored
  bytes without analysis, as expected for the current stub. No LLM quality or video decoding was tested.
- Formats: Chats `.txt`, `.zip`, PNG; Emails `.txt`, simple `.eml`, PNG, PDF; Contract and Document
  PDF, `.docx`, `.txt`, PNG; Video synthetic MP4 bytes. Images used `FakeLLM`, search was fake, HTTP used
  `MockTransport`, storage was in memory, and raw files used a temporary directory. No real cases changed.
- **31 frontend tests, TypeScript checking and the production build passed** after the photo-cache
  fix. Lint reported no errors and one pre-existing unused-disable warning in generated contracts.

Repeat the existing backend checks from `backend/`:

```powershell
..\.venv\Scripts\python.exe -X utf8 -m pytest -q tests/test_api.py tests/test_intake_documents.py tests/test_intake_images.py tests/test_service_ocr.py tests/test_images.py tests/test_zip_export.py
```

Remaining manual check: open a new case and an existing **open** case; click each Add control, choose
a supported file, and verify it appears in the evidence list. Repeat on a decided case to confirm
the disabled state. A closed case cannot be used to diagnose a file-picker fault.

## OpenRent logo

The current local photo endpoint returned a 71,117-byte JPEG matching the property's declared photo
byte for byte. The generic OpenRent share graphic was excluded. Successful responses have a one-hour
browser cache lifetime, so an earlier logo can survive a server-side correction. This branch adds
`v=2` to the image request URL to bypass that stale entry on the next page load. The exact browser cache
was not inspectable, so caching is the likely explanation rather than a directly observed cache hit.

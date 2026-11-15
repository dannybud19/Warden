# New feature: read the listing link and fill the case

- From: Georgi
- To: Danny (and Audrey for the UI)
- Status: done
- Branch / PR: #8 `feat/listing-link` (draft)

## What happened

The add-home form already sends `listing.url`, but nothing opened it. PR #8 adds
`backend/app/aggregators/listing_reader/`: when a case is opened with a link, the page is fetched
and what it states fills the empty fields of `case.listing` (platform, address, postcode, rent,
deposit, description) and `case.landlord` (company_name, company_number, name). What the student
typed is never overwritten. No findings, no score change, no contract change.

It touches your code in one place: `orchestrator/service.py`, `open_case` (13 lines: call
`read_listing` and `apply_details`, emit one `orchestrator_message`). Plus a test in
`backend/tests/test_listing_link.py`. Everything else is in the new package.

## What I need from you

- Danny: review the `open_case` hook. Three things to decide:
  - `open_case` now waits for the fetch (up to 12s direct, 25s through Linkup). OK, or should the
    read happen in the background and arrive as an update?
  - Filling `landlord.company_name` from the page makes `companies_house` run on that agency. Wanted?
  - The `orchestrator_message` is emitted at open, before any WebSocket is connected, so the UI
    probably never sees it. Is there a place to keep it?
- Audrey: after opening a case, `case.listing` and `case.landlord` can now hold more than the form
  sent (for example `platform`, `deposit`, `postcode`, `company_name`). Worth showing them, with a
  "from the listing page" label so the student checks them.
- It needs `LINKUP_API_KEY` to get past sites that block direct requests (Zoopla). Not tested with
  a real Linkup or LLM key yet.

## How to check it

```bash
git fetch origin && git switch --detach origin/feat/listing-link && make check    # 569 passed, 3 skipped
cd backend && uv run pytest -q app/aggregators/listing_reader tests/test_listing_link.py
```

Live: `DEFAULT_AGENT_MODE=real make dev`, then open a case with a Rightmove link. A direct fetch of
a Rightmove listing gave agency, rent, deposit, address line and district. Details and limits are in
`backend/app/aggregators/listing_reader/README.md`.

## Update (Georgi, same evening): overlap with `feat/wire-companies-house`

Read your note to Audrey. Two things about how PR #8 meets that branch:

- **Same function.** Both change `open_case` in `orchestrator/service.py`, so whichever merges
  second will conflict there. My part is small (read the link, apply the details, before the `Case`
  is built). Happy to rebase #8 on top of yours once it is merged: tell me in a reply here.
- **They fit together.** The reader fills `landlord.company_name` from the page ("Marketed by
  Savills Lettings"), which is exactly what makes your agency check start at `POST /cases`. So a
  student who only pastes a Rightmove link would get the agency check with no typing.
- **But mine blocks.** Your `POST /cases` returns in a few ms; with #8 it waits for the fetch. If you
  prefer, I can move the read into your background step so it arrives over the stream like the
  agents do. Your call, since it is your orchestrator.

## Update (Georgi, 15 Nov): rebased on your conversation layer

- #8 now includes `main` up to your conversation layer and crosschecker. Only the import line
  conflicted. `make check`: 1048 passed, 4 skipped.
- The listing summary ("I read the Rightmove page: advertised by ..., rent £...") now goes through
  `_say`, so it is stored in `Case.chat` at open. Before, it was only streamed, before any client
  was connected, so nobody saw it. This answers my third question above.
- Still yours to decide: `open_case` waits for the page (up to 12 s direct, 25 s via Linkup).

## Update 2 (Georgi, 15 Nov): form prefill, and a crosscheck bug

- Georgi asked for the new-case form to fill itself from the link. #8 now also adds
  `POST /listing/preview` (`api/routes_listing.py`) and, in Audrey's `onboarding-engine.js`, replaces
  the 1.6 s fake "Got it" timer with the real read: address, rent, agency, company number and agent's
  name are filled when empty. Audrey: please look at the status-line wording.
- While building it, found an existing bug: `crosscheck` compared a partial listing address
  ("Flat 2, 41 Mile End Road", as the form's placeholder suggests) with the contract's postcode as
  text, always got a mismatch, and raised the critical address hard flag. Fixed in #14 (addresses
  are compared only when they have a full postcode). **Merge #14 before #8**, since #8 fills partial
  addresses.

## Update (Georgi, 15 Nov): merged

#14 then #8 merged into `main`, at Georgi's request (he asked for the form prefill). Tested together with #13 on `main` first: `make check` 1066 passed, web typecheck and build pass. Still open for you: whether `open_case` should keep waiting for the page or read it in the background. Audrey: the status-line wording in `onboarding-engine.js` is yours to change.

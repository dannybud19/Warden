# New feature: read the listing link and fill the case

- From: Georgi
- To: Danny (and Audrey for the UI)
- Status: open
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

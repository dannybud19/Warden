# listing_reader

Owner: Georgi. Opens the listing link a student gives and pulls out what the page states, so the
student does not have to type it and the other checks have something to work with.

It does not judge the listing. It reports no findings and never changes the score.

## What it fills

When a case is opened with `listing.url`, the orchestrator calls `read_listing` and then
`apply_details`, which fill the **empty** fields only. Anything the student typed always wins.

| Page detail | Goes to | Used by |
| --- | --- | --- |
| Site name (Rightmove, SpareRoom...) | `listing.platform` | UI |
| Address with a full postcode | `listing.address` | crosscheck (listing vs contract) |
| Postcode or district (`W12 8QT`, `E14`) | `listing.postcode` | emotion_classifier price check |
| Rent per month (weekly rents converted) | `listing.rent_pcm` | price check, crosscheck |
| Tenancy deposit (not the holding deposit) | `listing.deposit` | crosscheck |
| Page title or one-line summary | `listing.description` | UI |
| Letting agency ("Marketed by ...") | `landlord.company_name` | companies_house |
| Company number, named landlord | `landlord.company_number`, `landlord.name` | companies_house, crosscheck |

A partial address ("Elm Road, London, W12") is not put in `listing.address`: the crosscheck would
compare it with the contract's full address and raise a false hard flag. It is added to the
description, and its district goes to `listing.postcode`.

## How it reads a page

1. **Fetch.** With `LINKUP_API_KEY` set it uses Linkup's fetch API (`POST /v1/fetch`, JavaScript
   rendered). Without a key, or if Linkup fails, it fetches the page directly through `ctx.http`.
2. **Extract**, strongest source first; the first one with a value wins:
   - the site's own data in the HTML: JSON-LD, the `itemprop="streetAddress"` element, embedded JSON, `<title>`;
   - one LLM call (`prompts/extract.md`): every value needs an exact quote from the page, and money
     must show the same digits in its quote, or it is dropped;
   - patterns over the page text (`£1,250 pcm`, `£185 pw`, `Deposit: £1,442`, `Marketed by ...`).
3. Every filled field keeps the page text it came from in `ListingDetails.quotes`.

`status` says what happened: `ok`, `skipped` (stub mode), `unsafe_url`, `unreachable`, `blocked`
(the site refused or showed a bot check) or `empty`. `summary_message` turns that into one line for
the student. It never raises.

## Safety

The link comes from the student and the server opens it, so `rules.safe_url` refuses anything that
is not a plain public page: only `http`/`https` on the default ports, no credentials, no
`localhost`, internal names or private IP addresses. For a direct fetch the host must also resolve
to public addresses only, and every redirect is checked the same way. Page text is passed to the
LLM as data, never as instructions.

## Known limits

- Zoopla, and sometimes SpareRoom, block direct requests. Linkup's fetch is the way through; without
  a key the student is asked to paste the details.
- No postcode is taken from loose page text: on real pages the first one is the agent's office or
  the site's own address. The postcode comes from the address, else the district in the title.
- A link to a search page rather than one listing gives the first rent on the page.
- Without an LLM key only the structured data and patterns run, so private-landlord pages
  (OpenRent, SpareRoom) usually give rent and area but no address.

## Modes

Stub (the default): no request is made; only `listing.platform` is set, from the link itself.
Real: `AGENT_MODE_LISTING_READER=real` in `.env`, or `DEFAULT_AGENT_MODE=real make dev`.

## Run the tests

```bash
cd backend && uv run pytest -q app/aggregators/listing_reader tests/test_listing_link.py
```

All tests are offline (`httpx.MockTransport`, `FakeLLM`, a fake DNS resolver).

# companies_house

Owner: Danny (WS B). A **background check** on the company, the people and contact details, and the
property. It produces evidence for the `landlord_identity` check and never gives a verdict.

It skips itself (status `skipped`) when the landlord has neither a company name nor a company number.
Without `COMPANIES_HOUSE_API_KEY` in real mode it returns `status=error` before making any call.

## What it checks

Four internal modules, merged by `agent.py`. Finding ids are `companies_house:<slug>` and stable across
reruns. Confidences are deliberate (see `constants.CONF`): a medium-or-higher suspicious finding at
confidence 0.6 or more flips `landlord_identity`, and a clear's confidence lowers the score.

| Module | Check | Source | Severity |
| --- | --- | --- | --- |
| register | `not-found`: the company number is not on the register | Companies House API | critical, **hard flag** |
| register | `dissolved`: status dissolved, liquidation, receivership, administration, insolvency-proceedings, converted-closed, removed or closed (not voluntary-arrangement) | Companies House API | critical, **hard flag** |
| register | `name-no-match`: name search finds no close match (asks for the number) | Companies House API | high |
| register | `name-number-mismatch`: the number belongs to a differently named company | Companies House API | high |
| register | `disqualified-director`: an active officer is disqualified | Companies House API | high |
| register | `ambiguous-match`, `young-company` (< 12 months), `officer-mismatch` (confidence 0.5, never flips the check), `dormant`, `insolvency-history`, `strike-off-proposed` | Companies House API | medium |
| register | `overdue-filings`, `non-property-sic`, `virtual-office` | Companies House API | low |
| register | `registered-active`: active, 24+ months old, name matches, filings current, not dormant (cleared, confidence 0.6) | Companies House API | low |
| reputation | `scam-report-*`, `negative-review-*` (max 3 each, kept by an LLM snippet filter; confidence 0.75 for scam reports and 0.5 for negative reviews, so only a scam report can flip `landlord_identity` on its own. With the LLM down, a keyword fallback instead shows a medium `negative-review` titled "A public post mentions a problem with ..." at confidence 0.5, so it cannot flip the check alone; it needs a strong scam word (scam, fraud, conned ...) in the same sentence as the company name or number) | Linkup web search | high / medium |
| reputation | `rogue-checker` (company number match), `rogue-checker-name` (record with no number, name match 95+) | London Rogue Landlord and Agent Checker, Linkup fallback | high / medium |
| reputation | `redress-member`, `cmp-member` (cleared, confidence 0.5) | Linkup, on theprs.co.uk, tpos.co.uk, propertymark.co.uk, safeagent.co.uk, ukala.org.uk | low |
| contact | `webmail`, `lookalike-domain` (imitates Rightmove, Zoopla ...), `new-domain` (< 90 days), `phone-scam-*` | landlord email/phone, RDAP, Linkup | low / high / medium / high |
| property | `postcode-invalid`, `postcode-area-mismatch` | postcodes.io | medium / low |

Facts emitted: `company_number` (zero-padded) and `email_domain` only.

## What it never does

- **No hard flag from the web.** Only the register (number 404, or a dead company) sets `hard_flag`.
  A name with no match is suspicious, not a hard flag.
- **No `address` or `landlord_name` facts.** The registered office and registered name go in finding
  `detail`; the crosscheck would otherwise flag every genuine case.
- **No claim without a source.** Every finding quotes evidence, and every external finding ends with a
  `Source: <url>` line. Absence is never evidence: no redress page, no Rogue Checker entry or no scam
  report produces no finding.
- **No error reported as "not found" or "no results".** A failed check becomes a `not-run-<module>`
  info finding ("Could not run: ...") and the report stays `ok`. A register failure is `status=error`.
- **No verdicts, no price comparison (WS E `fair_price`), no good-review clears.** LLM output is used
  only to classify snippets, and every LLM quote is re-checked as a verbatim substring.

## Environment keys

| Key | Used for |
| --- | --- |
| `COMPANIES_HOUSE_API_KEY` | register (required in real mode) |
| `LINKUP_API_KEY` | reputation and phone checks. Without it no search is made and each web check is listed in the "could not run" note as `(Linkup: no API key)`, never as "nothing found" |
| `ANTHROPIC_API_KEY` | the snippet filter (batches of 12 snippets per call; keyword fallback if a call fails) |
| `AGENT_MODE_COMPANIES_HOUSE=real` | switch this agent from stub to real in the full app |

## Run it alone

```bash
cd backend
# Companies House calls are real when a key is set; the LLM and Linkup are faked:
uv run python -m scripts.run_agent companies_house ../fixtures/private/genuine_live.json
# Everything real (Linkup, snippet filter):
uv run python -m scripts.run_agent companies_house ../fixtures/private/genuine_live.json --live
```

`fixtures/cases/genuine_flat.json` uses an invented company, so copy it to `fixtures/private/`
(gitignored) and put a real, long-established London agency in the landlord. Copy it again with
`company_number` set to `99999999` to see the `not-found` hard flag.

## Limits and timings

- 120 s agent timeout; the web modules get a 105 s deadline, and one that overruns becomes a "could
  not run" note so the register findings survive. Per call: Companies House 10 s, postcodes.io and RDAP 8 s, Linkup 15 s
  (standard) or 35 s (deep), three attempts with 1 s, 3 s, 9 s backoff and `Retry-After` (capped at 10 s).
  The Rogue Checker page is tried once, then Linkup. If only Linkup was
  read, or the first 20 entries for a name held no match, a "could not run" note says the checker
  was not fully read.
- At most 8 Linkup queries per run; normally 2 deep and 2 standard, plus a Rogue Checker fallback and a
  phone query when needed. Roughly $0.12 per run at Linkup's published rates, plus one small LLM call.

## Known gaps

EPC register, cloned-listing detection and Google Places are out of scope. Price comparison belongs to
`fair_price` (WS E). The virtual-office list is a heuristic and the Rogue Checker is scraped HTML, so a
site change falls back to Linkup rather than failing silently.

## Tests

All offline (`httpx.MockTransport` through `testing.Router`, `FakeSearch`, `FakeLLM`, injected no-op
sleep and a fixed clock). `make check` runs them. `stub.py` still replays
`fixtures/reports/companies_house.json`.

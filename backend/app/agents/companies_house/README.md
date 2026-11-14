# companies_house

Owner: Danny (WS B).

## What it flags

Landlord/agency not on Companies House, dissolved or very new companies, officer name mismatch, virtual-office address, no redress scheme. Clears active, established property companies.

## Status

Phase 0 stub. `agent.py` returns an empty OK report; `stub.py` replays
`fixtures/reports/companies_house.json`. Keep the stub working when you implement the real agent.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent companies_house ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent companies_house <case.json> --live   # real LLM/web
```

Switch it on in the full app with `AGENT_MODE_COMPANIES_HOUSE=real` in your local `.env`.

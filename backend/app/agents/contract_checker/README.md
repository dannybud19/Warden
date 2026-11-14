# contract_checker

Owner: Bill (WS G).

## What it flags

Deposit above 5 weeks' rent, banned fees, no deposit protection clause, address or landlord mismatches, clauses that do not fit the property.

## Status

Phase 0 stub. `agent.py` returns an empty OK report; `stub.py` replays
`fixtures/reports/contract_checker.json`. Keep the stub working when you implement the real agent.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent contract_checker ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent contract_checker <case.json> --live   # real LLM/web
```

Switch it on in the full app with `AGENT_MODE_CONTRACT_CHECKER=real` in your local `.env`.

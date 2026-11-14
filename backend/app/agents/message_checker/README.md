# message_checker

Owner: Georgi (WS D).

## What it flags

Payment before viewing, untraceable payment methods, lookalike links, off-platform moves, overseas landlords, overpayment scams. Extracts bank account, email domain, address, rent and deposit facts.

## Status

Phase 0 stub. `agent.py` returns an empty OK report; `stub.py` replays
`fixtures/reports/message_checker.json`. Keep the stub working when you implement the real agent.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent message_checker ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent message_checker <case.json> --live   # real LLM/web
```

Switch it on in the full app with `AGENT_MODE_MESSAGE_CHECKER=real` in your local `.env`.

# emotion_classifier

Owner: Georgi (WS E).

## What it flags

Pressure language (urgency, scarcity, authority, jargon) separated from facts, student-side desperation as info, rent far below the area median.

## Status

Phase 0 stub. `agent.py` returns an empty OK report; `stub.py` replays
`fixtures/reports/emotion_classifier.json`. Keep the stub working when you implement the real agent.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent emotion_classifier ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent emotion_classifier <case.json> --live   # real LLM/web
```

Switch it on in the full app with `AGENT_MODE_EMOTION_CLASSIFIER=real` in your local `.env`.

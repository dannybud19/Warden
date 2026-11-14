# video_analysis

Owner: Bill (later).

## What it flags

Nothing yet: stub only. Property video analysis is out of scope for the MVP.

## Status

Phase 0 stub. `agent.py` returns an empty OK report; `stub.py` replays
`fixtures/reports/video_analysis.json`. Keep the stub working when you implement the real agent.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent video_analysis ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent video_analysis <case.json> --live   # real LLM/web
```

Switch it on in the full app with `AGENT_MODE_VIDEO_ANALYSIS=real` in your local `.env`.

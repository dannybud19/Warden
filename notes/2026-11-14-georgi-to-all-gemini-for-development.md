# Run the real agents on your own Gemini key while building

- From: Georgi
- To: all (Danny to review and merge)
- Status: open
- Branch / PR: #11 `feat/core-llm-provider` (draft)

## What happened

Without `ANTHROPIC_API_KEY`, every agent runs on `FakeLLM`, so locally we only ever see the rules.
PR #11 adds an OpenAI-compatible provider to `core/` (Danny's paths) so each of us can use a free
Gemini key, and keeps Anthropic as the default for the demo. With nothing set, nothing changes.

It also fixes the timeouts seen today: each LLM attempt gets its own `LLM_TIMEOUT_S` (default 20 s)
and a timeout is retried once, inside an agent's 45 s limit. Before, a slow call hit the shared 30 s
HTTP timeout with no retry and the agent dropped to rules only.

## What I need from you

- Danny: review and merge #11 (`core/llm.py`, `core/settings.py`, `core/factory.py`, `.env.example`,
  one test file). Default behaviour is unchanged.
- Everyone, once it is merged: put these in your own `.env` (gitignored; never commit or share a key):

```
LLM_PROVIDER=openai_compatible
LLM_API_KEY=<your own key from Google AI Studio>
LLM_MODEL=gemini-3.5-flash-lite
```

  One key each also spreads the free-tier rate limits. `gemini-3.8-flash` timed out on the free tier;
  Flash-Lite answers in about 2 s. Free tiers may use what we send: synthetic cases only.
- For the demo, switch back: `LLM_PROVIDER=anthropic` and the team `ANTHROPIC_API_KEY`.

## How to check it

`make check` on the branch: 542 passed, 3 skipped. Live with Gemini on, the overseas-landlord chat:
message_checker 0.8 s and emotion_classifier 1.7 s with their LLM passes, verdict `likely_scam`.

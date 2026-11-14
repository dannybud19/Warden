# emotion_classifier

Owner: Georgi (WS E). Needs: `messages` (and reads the listing for the pricing check).

## What it does

Separates what the messages actually state from the language that works on feelings, and compares
the rent with an approximate area figure.

- **Agent-side pressure** (check `no_pressure`): one finding per kind, each with exact quotes.
  Urgency, scarcity, guilt, authority and jargon are medium, and all become high when three or more
  different kinds appear. Flattery is low and never moves the check.
- **Student-side feelings** (desperation, sunk cost, from the student's messages and notes): shown as
  `info` so the UI can put "how you might be feeling" next to the facts. Never counts against the place.
- **Clear on `no_pressure`:** only when the agent explicitly takes pressure off ("no rush") and no
  pressure language was found.
- **Stated facts** (`stated_facts`, info): the model's neutral list of checkable claims, for the
  facts-vs-feelings view.
- **Pricing** (check `fair_price`, finding `rent_vs_area`): 25% or more below the area figure is
  medium; within 15% either way is a clear at 0.6; in between is low; above is info.

## How it works

| File | Role |
| --- | --- |
| `rules.py` | Patterns for urgency, scarcity, reassurance, desperation and sunk cost. No I/O |
| `llm.py` | One LLM call (`prompts/facts_vs_feelings.md`); drops any quote not found word for word, and any kind on the wrong side of the conversation |
| `pricing.py`, `area_rents.yaml` | Rent against the area table |
| `models.py` | Shape of the LLM's reply |
| `agent.py` | Merges rule and LLM hits into one finding per kind |

Without an API key, or if the LLM call fails, the rules and the pricing check still run.

## Known limits

- `area_rents.yaml` is hand-built and approximate (20 districts). It is not from a dataset; replace
  it before relying on it. Districts not in the table get no pricing finding.
- The rent is compared with a room figure unless the text clearly says studio, one-bed or whole flat.
  A whole flat advertised at a room's price is therefore not caught unless the text says so.
- `llm.MODEL` is `None` (team default). A faster model would suit this agent.

## Run it alone

```bash
cd backend && uv run python -m scripts.run_agent emotion_classifier ../fixtures/cases/fake_agency.json
cd backend && uv run python -m scripts.run_agent emotion_classifier <case.json> --live   # real LLM
```

Switch it on in the full app with `AGENT_MODE_EMOTION_CLASSIFIER=real` in your local `.env`.
`stub.py` still replays `fixtures/reports/emotion_classifier.json`.

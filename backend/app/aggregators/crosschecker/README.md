# crosschecker

Owner: Danny (WS J). A generalist agent that reads every checker agent's report side by side, flags
where two sources disagree, and writes a short recap that the orchestrator relays to the student.

Each checker sees only its own slice of the evidence. None of them can notice that the contract
charges **£60 a month for utilities** while the agent's WhatsApp messages say **all bills are
included**. The Cross-checker can: it returns a `crosscheck:utilities` finding that quotes both sides,
and a recap like "Your contract charges £60 a month for utilities, but the agent said all bills are
included. Ask the agent to confirm in writing which is right."

## API

```python
from app.aggregators.crosschecker import crosschecker

report = await crosschecker.review(case, rule_findings, ctx)  # -> AgentReport
```

- `rule_findings` come from the orchestrator's rule-based `orchestrator/crosscheck.py` (address,
  landlord name, company number, rent and deposit facts). They are passed in because aggregators
  may not import the orchestrator. They are returned **first and unchanged**, hard flags included.
- `NAME = "crosscheck"`, `VERSION = "1.0.0"` and `recap()` (the rule-only template recap) are
  public; the orchestrator uses them.
- The report is stored as `case.reports["crosscheck"]`. Its `summary` holds the recap.

## What it flags

Disagreements **between** sources about the same thing: amounts (utilities, deposit, fees), dates
(available 1 Sep vs tenancy starts 15 Sep), who to pay (the contract names a company, a message asks
for a personal account), who the landlord or agency is.

Every LLM finding:

- quotes **both** sides verbatim, from evidence only: an upload's text, a message, an agent's
  quote, a fact's or field's value. Labels we add (`[agent]`, `rent_pcm =`) and an agent's own
  words never count; a quote the LLM takes from a finding is moved to that finding's own quote,
  with that quote's evidence id. Matching ignores case, whitespace, curly quotes and `£ 60`
  spacing; the finding is dropped if either quote is missing or over 200 characters. The stored
  quote is the source's own wording, not the LLM's retyped copy;
- uses two different sources (not the same agent and the same evidence);
- is not a repeat of a rule finding (same topic and same values);
- has id `crosscheck:<topic-slug>`, so a rerun replaces it instead of adding a copy;
- is category `consistency`, `supports="suspicious"`, severity at most `high`, and not a hard flag,
  with one exception: a disagreement on the **property address** between the listing (what the
  student entered, or an uploaded listing) and a contract that the LLM marks `certainty="certain"`
  is a hard flag (`contract_consistency`, critical, confidence 0.9). This is the same hard flag as
  the rule crosscheck's, but the LLM judges whether the two addresses are different homes, so a
  listing with only a postcode district ("W12") or no postcode is still compared. Identical full
  postcodes on both sides overrule the LLM;
- uses no verdict or legal word in its title or claims (else it is dropped; an explanation that
  uses one is left out);
- has confidence 0.7, enough to make a check suspicious at medium severity or above. If one side is
  something the student typed (listing or landlord fields), the confidence is 0.5, because typed
  values are often approximate. A 0.5 finding is shown but does not flip the check.

At most 5 findings per run. Web-sourced findings keep their `Source: <url>` lines.

## Inputs

- Other agents' reports with status `ok` (never its own previous `crosscheck` report): their
  findings, the quotes they cite and their facts.
- Excerpts of the uploads: the first 4,000 characters of contract, document, email, chat-export and listing
  text, and the parsed messages, one source per upload (an upload whose messages were parsed is
  sent as its messages only, not twice).
- What the student entered: listing and landlord fields.

Each item becomes a numbered source (`S1`, `S2`, ...) that the LLM may quote. The total is capped at
24,000 characters: evidence and message excerpts are trimmed longest first, never below 500
characters; findings, quotes, facts and student fields are never trimmed.

## When the LLM runs

| Situation | LLM call | Findings | `summary` |
| --- | --- | --- | --- |
| Stub mode (default) | no | rule findings | template recap of the rule findings, or `None` |
| Fewer than 2 sides (OK reports, plus what the student entered about the listing or landlord, plus each uploaded listing) | no | rule + previous LLM findings | previous summary if there were any, else the template recap of the rule findings, or `None` |
| Inputs unchanged since the last run (same input hash and version) | no | rule + previous LLM findings | previous summary |
| LLM error, bad JSON or over 25 s | yes, failed | rule + previous LLM findings + `crosscheck:not-run` (info, confidence 0) | previous summary, else the template; `input_hash=""` so the next analysis retries |
| LLM finds nothing that survives validation | yes | rule findings | template recap of the rule findings, or `None` |
| LLM finds disagreements | yes | rule + LLM findings | the LLM's recap if it passes the checks below, else a fixed template |

The recap is at most 80 words in whole sentences. It is replaced by the template ("A few details
don't match between your documents: ... Before paying anything, ask the agent to confirm the correct
terms in writing.") if it is empty, still names an internal source id such as "S7's" (references
like "(S36)" are stripped first, and the same ids are stripped from finding titles and details), uses a verdict or legal word (safe, scam, fraud, legit,
guarantee, illegal, sue, lawyer, genuine, fake, and their inflections), or mentions a topic that is
neither a kept disagreement nor a rule finding. The orchestrator decides whether to send it: only
when it is non-empty and different from the previous one.

"Previous LLM findings" are those of the last run by this version: a report or LLM call that
fails for now never makes verified disagreements disappear.

The 25 s limit sits below the orchestrator's own 30 s deadline around `review()`, so this module's
fallback, with its not-run finding, applies first.

## Modes

`AGENT_MODE_CROSSCHECK=real` in your local `.env` (or `DEFAULT_AGENT_MODE=real`) turns the LLM pass
on. The default is the stub. Unlike the checker agents' stubs, the stub replays **no fixture**:
canned consistency findings would cite evidence ids that don't exist in a real case. It passes the
rule findings through with the template recap, which is what the orchestrator did before WS J.

## Wiring

Done in the orchestrator (`service.py`), not here: it computes the rule findings, calls `review()`
**outside** the state lock, stores the report as `case.reports["crosscheck"]`, and relays a changed
recap as an `orchestrator_message` before the consultant's actions.

## Files

| File | Role |
| --- | --- |
| `crosschecker.py` | `review()`: stub switch, gate, reuse, LLM pass, validation, report |
| `sources.py` | Input reports, numbered sources, budget, input hash |
| `llm_pass.py` | Renders the sources, calls `ctx.llm.complete_json`, raises `LLMPassError` on any failure |
| `prompts/review.md` | System prompt |
| `models.py` | The LLM's output (`Side`, `Inconsistency`, `ReviewOutput`) |
| `validate.py` | Quote checks, dedupe, finding construction, recap cleaning, not-run finding |
| `rule_recap.py` | Template recap from rule findings only |
| `stub.py` | Stub mode |
| `constants.py` | Agent name and reserved finding ids |

## Tests

```bash
cd backend && uv run pytest -q app/aggregators/crosschecker
```

All offline (`FakeLLM`). `tests/test_review_flow.py` runs the plan's scenarios X1 to X16 end to end
through `review()` on the fixture cases in `tests/fixtures/`.

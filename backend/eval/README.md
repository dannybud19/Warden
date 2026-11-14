# Synthetic development cases (WS H, Bill)

The generator builds **40 fictional cases** for regression testing. It uses deterministic templates
and eight optional, Codex-authored wording variants. It needs no API key, makes no network calls,
adds no dependencies, and does not change shared application schemas. All case labels still need
review by the relevant agent owners; this is a development corpus, not a measured accuracy benchmark.

## Run it

From `backend/` in an installed checkout:

```bash
uv run python -m eval.generate
uv run python -m eval.generate --validate-only
uv run python -m pytest -q eval/tests/test_synthetic_generator.py
```

In Bill's Windows workspace, the equivalent commands are:

```powershell
cd D:\Warden\.worktrees\synthetic-generator\backend
& D:\Warden\.venv\Scripts\python.exe -X utf8 -m eval.generate
& D:\Warden\.venv\Scripts\python.exe -X utf8 -m eval.generate --validate-only
& D:\Warden\.venv\Scripts\python.exe -X utf8 -m pytest -q app tests eval/tests
```

The default destination is `fixtures/cases/synthetic/` in this checkout. The default seed is
`20261114`. A matching rerun is reproducible and checks existing files before writing. If a generated
source was edited, generation refuses to overwrite it. Change the source catalogue to maintain a case,
or select a **new empty output directory** when changing the seed or removing the paraphrases:

```bash
uv run python -m eval.generate --seed 7 --output ../fixtures/cases/synthetic-seed7
uv run python -m eval.generate --without-paraphrases --output ../fixtures/cases/synthetic-templates
```

The second command builds 32 cases. Generated `.gitattributes` keeps JSON/text line endings at LF,
including on Windows, so a checkout does not break the recorded file hashes. Source catalogue hashes
use canonical JSON, independent of source-file line endings.

## What the 40 cases cover

| Group | Count | Purpose |
| --- | ---: | --- |
| Eight core families, each with a concern, genuine control and unresolved version | 24 | Compare changed facts within the same fictional setting |
| Harmless rewrites of eight genuine controls | 8 | Check that rewording does not change the conclusion |
| Compound cases | 4 | Combine several concerns or legitimate explanations |
| Robustness cases | 4 | Reassuring language, document prompt injection, missing attachments, conflicting rent |

The eight families are deceptive short lets, fake platform links, unavailable adverts, fake agencies,
prepaid payments, properties also advertised for sale, overpayment, and bank-transfer pressure.
The corpus has **11 scam, 17 genuine and 12 unknown** scenario labels. The 17 genuine cases include the
eight paraphrases, so they are not 17 independent underlying scenarios. All are development fixtures;
there is no held-out split. Keep each `group_id` together when adding one later.

The legitimate controls prioritise genuine urgency, explained low rent, an owner abroad, and different
owner/agent names. Payment timing, consent and authority determine the concern; those superficial
features alone are not evidence of fraud. The low-rent family uses GBP 600/month and a GBP 690 deposit.

Each family reuses its fictional property, names and amounts across meaningful variants. These are
related scenario contrasts, not guaranteed single-clause interventions: several relevant facts may
change. The manifest explicitly identifies 16 meaningful comparisons and eight wording comparisons.

## Artifacts and the evidence boundary

```text
fixtures/cases/synthetic/
  manifest.json                    evaluator-only expectations, comparisons and provenance
  labels.json                      evaluator-only {case_id: scam | genuine | unknown}
  .gitattributes
  cases/c_<opaque-id>/
    case.json                      fresh shared Case, ready for backend consumption
    chat.txt                       readable chat transcript
    contract.txt                   ordinary tenancy draft, plus scenario-specific terms
    listing.txt                    advertised property, rent, deposit and link
    external.json                  controlled search/register responses for injected fake clients
    follow_up.txt                  one later student reply, withheld from the initial Case
```

Only `case.json` goes into the initial agent context. Its filenames/IDs do not disclose the label.
It contains exactly three source-backed evidence items, parsed messages, and all eight checks in the
unverified state. It contains no conclusions, reports, actions, score history or decision. The existing
scoring formula therefore starts at 100. Student budget and move-in date are fictional intake context.
Company numbers appear in the structured landlord data only when present in the chat; none is invented
as extra intake evidence. Names, locations and account suffixes are fictional; accounts stay masked.

Keep the **manifest and labels out of prompts**. Do not attach the entire case folder or pass the raw
external fixture metadata to an agent. `labels.json` intentionally extends the original WS H brief with
`unknown`, following the agreed requirements; a future runner must handle it explicitly. Do not parse
every JSON file recursively as a `Case`.

Each expected issue has a check, topic, stance (`concern`, `clarify`, or `must_not_assert`) and exact
supporting quote. Source references identify an input evidence item or an external record; the latter
has the URL that a web-based finding should cite. A `must_not_assert` entry prohibits the assertion
described in its explanation; it does not mean that the entire check has been cleared.

Hidden scenario truth and justified conclusions are separate. Even a genuine rental may still need
verification. Initial genuine/unknown cases permit `pending` or `not_verified`, since some critical
checks are unresolved. `pending` means the runner observed an open question loop; it is not a new
application verdict. A scam can also remain pending while an agent gathers evidence, but its required
concerns still need to be detected. Measure issue coverage and false assertions separately from verdict
agreement; a verdict-only pass would hide missed findings. Never treat the score as a fraud probability.

## Controlled external services

`eval.synthetic.external.load_external()` returns a `FixtureSearch` and `httpx.MockTransport`:

```python
from pathlib import Path

import httpx

from eval.synthetic.external import load_external

search, transport = load_external(Path("path/to/case/external.json"))
async with httpx.AsyncClient(transport=transport) as http:
    # Supply search and http through the existing AgentContext.
    # Supply FakeLLM in tests, or a budgeted provider client for a later live-model evaluation.
    ...
```

Searches match all terms within a declared query group, ignoring case and repeated whitespace.
`query_alternatives` adds alternative complete groups; register fixtures accept either company number
or company name alone. `search.queries` records requests. HTTP routes match method and full URL, with
Companies House profile responses included where the scenario has a register result. These are
controlled fictional records, not assertions about the live register.

Three distinct behaviors matter:

- A declared `not_found` search returns `[]` (HTTP absence uses 404).
- A declared service outage raises `FixtureUnavailableError` (HTTP outage uses 503).
- An undeclared query/route raises `MissingFixtureError`; it never falls back to the internet.

A search matching an unavailable source raises explicitly, even if another source also matches. The
runner must count unavailable sources and missing fixtures separately from an agent's factual mistake.
The adapter covers the declared queries/routes, not the whole Companies House or search API. Extend
fixtures when an agent owner agrees another request is appropriate. Always inject these adapters before
evaluating fictional companies: the ordinary standalone `--live` scripts do not load them automatically.

## Scripted follow-ups

Every current case has one follow-up. The manifest records its check/topic, earliest available time and
expected direction of change. Initial snapshots are fixed at 14 November 2026, 12:00 UTC. Completed
initial viewings are dated 13 November; proposed viewings are dated 15 November. Follow-ups become
available on 16 November, after any stated new viewing.

A future conversational runner should deliver the reply only when the system asks a matching question,
advance its assessment time appropriately, and record it as new student evidence using the normal reply
path. It must never inject `follow_up_expected_change` as an action outcome or automatically clear a
check. If no matching question occurs, record the follow-up as unused. The first baseline evaluation
can simply stop at the first open question, as the original WS H brief requires.

## Maintaining and reviewing the library

Edit `synthetic/catalogue.json` for the 24 core scenarios, `synthetic/extras.json` for the eight special
cases, and `synthetic/paraphrases.json` for the optional wording edits. Placeholders are rendered from
one fact set per family. `viewing_completed` selects the appropriate initial viewing date. Generated
files should be regenerated, not hand-edited. Run `--validate-only` and the offline tests afterward.

Paraphrases are a fixed library authored by Codex subagents and checked during implementation. The
generator rejects changed numeric/URL literals and placeholder counts, copies the original scenario's
commitments, and verifies the new quotes. Those checks cannot prove semantic equivalence: negation,
certainty, speaker roles and payment/viewing order still need human review. No fresh LLM paraphrase is
generated at runtime. Additional API generation and its cost cap would be a separate extension.

All entries carry `pending_agent_owner_review` and suggested reviewers. Georgi reviews messages,
emotion/price and question expectations; Bill reviews contract expectations; Danny reviews register,
authority and cross-source expectations. Review concerns and forbidden assertions as well as truth
labels. Version the library when accepting revisions. The current strict model deliberately cannot
silently claim a case has already received human approval.

The generator and offline fixture adapters are complete independently of the orchestrator. The remaining
evaluation runner should load one case, inject the controlled clients, run real checker code through
`CaseService`, and compare observed findings/questions/verdicts with the separate manifest. It should
record agent errors, missing fixture requests, latency, token usage and actual model cost. Run stubs only
as wiring smoke tests: they replay fixed reports and cannot establish detection quality. Weight tuning,
live-model performance measurements, persistent conversations and real held-out evaluation remain
separate work. Shared scripts, schemas and other owners' code were not changed here.

## Three decisions for the hackathon presentation

1. **Judge what the evidence supports.** Separate hidden truth from justified conclusions; incomplete
   evidence should trigger a question, even when the synthetic author knows the rental is genuine.
2. **Test changes, not just examples.** Compare meaningful factual changes and harmless rewrites to
   reveal missed concerns and false alarms from superficial wording.
3. **Keep facts repeatable and language flexible.** Deterministic templates control amounts, roles and
   timelines; reviewed Codex wording variants add variation without runtime generation costs.

Runtime generation makes **zero provider API calls** and incurs **USD 0 in generation API charges**.
That figure excludes Codex authoring/subscription costs and any later model evaluation. See
[SYNTHETIC_RESULTS.md](SYNTHETIC_RESULTS.md) for the recorded validation run.

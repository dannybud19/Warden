# Synthetic generator validation

Validated on 14 November 2026 using Python 3.12, on branch `feat/h-synthetic-generator`.
This records generator and fixture validation, not agent detection accuracy.

| Item | Result |
| --- | --- |
| Default seed | `20261114` |
| Default corpus | 40 cases across all eight requested families |
| Scenario truth | 11 scam, 17 genuine, 12 unknown |
| Core / wording / compound / robustness | 24 / 8 / 4 / 4 |
| Explicit comparisons | 16 meaningful changes, 8 harmless rewrites |
| Later scripted replies | 40, each withheld from its initial Case |
| Templates-only option | 32 cases |
| Human review | Pending relevant agent-owner review for every case |
| Runtime generation API calls and cost | 0 calls, USD 0 |
| Backend tests including evaluation tests | 224 passed, 3 skipped |
| New generator tests | 19 passed |
| Ruff lint and format | Passed |
| Pyright, including `eval/` explicitly | 0 errors, 0 warnings |
| Import-linter | All 3 contracts kept |

The offline tests check reproducible generation, balanced core coverage, meaningful/wording comparison
metadata, fresh shared Case schemas with eight unverified checks, source-backed evidence and money,
later follow-up timing, exact quoted expectations, separation of hidden labels from agent inputs,
literal preservation during paraphrasing, seed-based IDs and shared family facts, changed-file and
path-traversal rejection, controlled HTTP/search responses, missing/outage/negative-result distinctions,
and invalid external-route rejection. The generated corpus also passes `--validate-only`.

Genuine controls were reviewed during implementation to remove unjustified fully cleared outcomes.
Initial completed-viewing dates were corrected to precede the snapshot. Register statuses are only
provided by register fixtures, and company numbers are not added to intake metadata without chat
support. Codex-authored paraphrases preserve the reviewed payment/viewing commitments; the numeric and
placeholder guards alone are not proof of semantic equivalence. Human label review remains necessary.

The existing backend suite still passes, including checker stub tests. No shared contracts, core code,
other owners' agent code, tooling, dependencies or scoring weights were changed. The three pre-existing
skips are the MongoDB repository variants when `MONGODB_URI` is unset; they were not changed here.

The cost figure applies to running the local generator. Codex authoring/subscription usage was not
measured. No Anthropic evaluation budget was spent. Running live checker models later needs separate
token/cost accounting and the injected external fixtures described in [README.md](README.md).

The system evaluation runner, automatic follow-up delivery, real-model accuracy/latency/cost evaluation,
weight tuning and a held-out dataset are not part of this result. Unknown cases must not be silently
treated as genuine or included in a binary fraud-accuracy denominator. Wording siblings must not be
counted as independent evidence of generalisation.

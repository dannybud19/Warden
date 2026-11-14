# Decisions so far (Sat 14 Nov, 15:15)

## What we are making

A multi-agent assistant that protects London students from rental scams. A student who has already
picked a property uploads everything the property agent sends them (chat screenshots, WhatsApp/email
text, call recordings, videos, documents, the contract). The case starts at maximum suspicion. Agents flag
every red flag with evidence, the assistant asks the student focused questions and suggests actions, and
the score drops only as things are verified. When nothing useful is left to check, it gives a final verdict.

We do not build a new platform. The agents work on top of what students already use: SpareRoom,
OpenRent, Rightmove, WhatsApp, email and Companies House.

## Decisions

| Area | Decision |
| --- | --- |
| Track | 01 Autonomous Agents |
| Prizes targeted | Linkup + MongoDB (our 2 sub-bounties), Best-Designed AI Product (Figma, cross-cutting) |
| User | Student side only for the MVP; landlord side later |
| Starting point | Score 100, all 8 checks "unverified": guilty until verified |
| Who talks to the student | Only the orchestrator, through one chat |
| How agents work together | They never talk to each other. Each reads the shared Case and returns a report; the orchestrator cross-checks facts, updates checks and reruns agents when inputs change |
| Orchestrator | Deterministic code core (reliable, explainable) + an LLM layer for chat wording and parsing replies |
| Checker agents (MVP) | Companies House, Message checker, Contract checker, Emotional influence classifier. Video analysis later |
| Aggregators | Scoring (pure formula over 8 weighted checks) and Consultant (picks the next 1 to 3 questions or actions) |
| Final verdicts | Likely scam, Not verified, Proceed with care, No red flags remaining. Never "safe" |
| Early stop | A confirmed hard red flag (payment before viewing or to a pre-paid card, agency not registered or dissolved, contract address mismatch) closes the case |
| Evidence rule | Every finding quotes its source; web findings cite the URL |
| Stack | Python/FastAPI backend, Pydantic contracts, Next.js web app, MongoDB Atlas, Linkup, Companies House API, Anthropic models |
| Data | Synthetic cases for building and tuning. Danny's real experience is the demo hook and held-out test, redacted and never committed |
| Demo | 2-minute video: Danny's case caught, then a genuine place cleared |

## How we work

| Rule | Detail |
| --- | --- |
| Phase 0 first | Danny + one Claude session (Sonnet, high effort) builds the foundation: shared contracts, stubs for every agent, orchestrator, API, and a plain web shell on localhost. Opus reviews it once |
| Then parallel | Everyone works in their own git worktree and branch, in their own folders only |
| Independence | Agents may only import the shared contracts and core; import-linter enforces it. Every agent keeps a working stub, so the app always runs |
| Contracts are frozen | Changes go through a separate small PR and the whole team rebases |
| Quality gate | `make check` green before any merge to main |

## Who owns what after Phase 0

| Person | Builds |
| --- | --- |
| Danny | Orchestrator + chat parsing, MongoDB, evidence intake (screenshots), Companies House agent |
| Georgi | Message checker, Emotional influence classifier, Consultant |
| Bill | Contract checker, scoring weights, synthetic cases + evaluation |
| Audrey | Design, branding, her own frontend plan on top of the web shell, Figma for the prize |

## Timeline

| Time | Milestone |
| --- | --- |
| 15:15 to 16:15 | Phase 0 (first commit) |
| 16:15 to 20:30 | Everyone builds their features; real agents switched on one by one |
| 20:30 | Gate: full live run on Danny's case |
| Sun 10:00 to 11:00 | Feature freeze, record video, write-up |
| Sun 11:45 | Submit on Devpost (hard close 12:00) |

## Still open

- [ ] Product name and branding (Audrey)
- [ ] Anthropic API key holder and budget (the plan assumes Anthropic models)
- [ ] Danny's account of his experience, to build the demo case
- [ ] Area rent figures for the pricing check (a small hand-built table is the plan)
- [ ] Approve the system design doc, then export it as a PDF for the team

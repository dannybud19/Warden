# Hackathon brief

Event facts and our strategy in one place. Sources: the opening ceremony slides, the event site
(imperialaihack.com) and the team's Google Doc "Hackathon discussion page".

## Key times (Imperial AI Hackathon, Huxley Building)

| When | What |
| --- | --- |
| Sat 14 Nov, 15:00 | Reply workshop (Huxley 311) |
| Sat 14 Nov, 15:30 | Linkup talk: one of us attends (sub-bounty we target) |
| Sat 14 Nov, 21:00 | Building closes |
| Sun 15 Nov, 10:00 | Doors open |
| **Sun 15 Nov, 12:00** | **Devpost submissions close.** We aim for 11:45 |
| Sun 15 Nov, 13:00 to 16:30 | Judging |
| Sun 15 Nov, 17:00 | Finals, then prizes around 17:30 |

## Submission requirements (incomplete entries are removed)

1. Write-up: what the product is, what it does, how we built it
2. GitHub link (public, so no real personal data in the repo)
3. 2-minute demo video

## Prizes we are going for

| Prize | Value | Why we fit |
| --- | --- | --- |
| Main track: 01 Autonomous Agents | £500 / £200 | Multi-agent system that finishes a real multi-step task |
| Sub-bounty: Linkup | £560 + credits | Our verification checks are live web searches that cite sources |
| Sub-bounty: MongoDB Atlas | Atlas voucher | Case store, agent reports and score history (agent memory) |
| Cross-cutting: Best-Designed AI Product (Figma) | £960 + merch | Audrey designs the product in Figma; does not use a sub-bounty slot |

Rules from the slides: 1 main track is required, up to 2 sub-bounties are optional, and cross-cutting
tracks are open to every team. Considered and skipped for now: Databricks (needs a real pipeline),
Tavily (duplicates Linkup), Synthesia (stretch only), Adaption fine-tuning (only if time allows).
The Reply Challenge criteria match our design closely, but it is a separate main track.

## Original brief (Google Doc)

- Multi-agent workflow that helps students in London who are looking for accommodation avoid scams, by
  identifying suspicious messages or activity from the property agent.
- Use cases: contract decomposer; serve students at their most desperate (the people scammers target);
  separate biases and strong emotions from what is objective.
- Features: Companies House search, message checker, contract checker, property video analysis (later),
  emotional influence classifier, consultant, overall scoring agent. Student side first, landlord side later.
- Reference: SpareRoom's list of scam types (short-term let, fake Airbnb ad, no live advert, fake
  lettings agency, pre-paid card, "for sale", overpayment, bank transfer, phishing).

## Demo and data

- The hook and the held-out test case: Danny's own experience, with names, numbers and bank details redacted.
  It is stored only in `fixtures/private/` (gitignored).
- Tuning and evaluation: synthetic cases for each scam type plus genuine listings, so we can report
  catches and false positives.

# Contract checker: Bill's scope notes

Recorded: 14 November 2026. The standalone first version is implemented; see
[README.md](README.md) for commands, limitations and evaluation. These notes preserve the
agreed feature subset and distinguish the remaining integration work.

## Confirmed input formats

**The first version supports text-based PDFs and plain text.** The contract checker owns
text extraction from the supplied contract; it must not require the orchestrator to extract
the text first. Scanned PDFs, image-only pages, OCR and Word documents are outside the first
version's scope.

The checker may also receive additional context from the orchestrator. It reviews issues
verifiable within the contract and that context. A separate comparison agent owns
inconsistencies across contracts, chats, listings and other sources.

## Confirmed first-version scope

- Ordinary private tenancies, scoped to England for the London project.
- Structured extraction with exact supporting quotations and reproducible rule checks.
- Checks for tenancy deposits, holding deposits, additional fees, advance rent,
  tenancy/notice clauses, internal contradictions, missing schedules and unusual obligations.
- Targeted clarification questions explaining what an answer would change.
- A second LLM pass that challenges proposed findings using exceptions, definitions and
  other relevant clauses.
- Clearly conditional concerns when applicability or evidence is uncertain.
- A standalone backend entry point accepting the contract file plus orchestrator context
  and returning JSON. Connect the existing upload pipeline afterward; a new user interface
  is not part of this deliverable.
- Paired synthetic contracts with controlled changes, plus cost measurement for live
  API evaluation. Use the repository's configured Anthropic model with a **GBP 5 total
  evaluation budget**. Automated tests remain offline.

Deposit-protection information checks, payment timelines, ordinary costly-commitment advice
and comparison against a single-prompt baseline are excluded. Deposit amount checks remain
in scope even though deposit-protection paperwork and scheme information are excluded.

Rejecting an unhelpful reassurance is a useful example, not a requirement to organise the
whole implementation around that demo.

## Requested finding details

Each issue should include exact quotations, clause identifiers, legal-source links,
assumptions, uncertainty, a suggested question and an importance score for the orchestrator
to decide whether to surface it. Importance and confidence have different meanings.

## Implemented approach

The checker uses a small, versioned collection of official legal rules with applicability
conditions, effective dates and source links, verified on 14 November 2026. Relevant rules
are supplied directly to the LLM. Retrieval infrastructure is outside the initial build.

It extracts text locally, uses an LLM to extract terms and candidate issues, validates
quotations, runs Python calculations and rules, and uses a second LLM pass to challenge
the findings. Uncertainty and targeted questions remain explicit in JSON.

The richer JSON model lives inside the contract checker package. An adapter supplies
supported fields to the existing AgentReport; richer fields are not yet in the shared
schema. The importance scale is 0-100 and represents attention priority. Rule-level clears
are retained in detailed JSON and do not falsely clear broader shared checks.

The working target is a first version within the stated three-hour window. No additional
feature cuts have been agreed.

## Later requirement and open integration decisions

Revision tracking is a stretch for the first version and required later: maintain issue
history across multiple rounds, including whether new evidence resolves an issue or
introduces another. Stable issue IDs and document fingerprints are proposed groundwork;
persistent history is not implemented by this note.

Still to decide or coordinate:

- Later upload-pipeline integration: current intake extracts text and the runner requires
  extracted contract text; changing that flow touches Danny's owned paths. The first
  version remains standalone.
- The evaluation runner now measures provider token usage without changing the shared LLM
  client. It includes paid retries, records uncertain-cost failures and persists a budget
  ledger. The GBP 5 authorisation has an additional USD 5 ceiling; currency estimates and
  measured USD costs are reported separately.
- How richer issue fields reach the orchestrator while respecting the shared-schema process.

Editing fixtures/reports/contract_checker.json is authorised. Keep it schema-valid and
preserve the stub; its evidence quotes must remain consistent with the referenced fixture.

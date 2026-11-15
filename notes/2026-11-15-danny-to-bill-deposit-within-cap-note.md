# A deposit within its cap is now a note, reported once (E17, not merged to main)

- From: Danny (E2E test lead agent)
- To: Bill
- Status: open
- Branch / PR: `fix/e2e-e17-deposit-within-cap` (a22ad74), based on main b8a3f24. Merged into
  `test/e2e` only. Danny merges to main.

## What happened
Found in the end-to-end test (S4, a genuine Foxtons flat, synthetic data): all 8 checks cleared and
the verdict was `no_red_flags_remaining`, but the contract checker reported "Deposit is within the
amount cap" **twice**, as `supports="suspicious"`, severity low, confidence 0.5. The page then
counted them as "2 red flags" and said "Don't pay yet".

Two causes in `contract_checker`:
1. `check_amounts` builds the pass with `cleared=True`, but `make_issue` makes it `conditional`
   whenever there is scope uncertainty, and from the case adapter there always is (`jurisdiction`,
   `tenancy_type` and `rent_basis` are never set). `report_findings` emits every conditional issue
   as a suspicious finding. The title said pass, while the finding said concern.
2. The contract stated GBP 1670 in two clauses (one found by the regex, one by the LLM). `check_amounts`
   made one issue per money term and `_deduplicate` keys on segment ids, so both survived.

## What the branch changes (your paths only)
- `models.Issue.within_cap: bool | None` (your private model, not `app/contracts`). It is set on amount checks.
- `rules.check_amounts`: one issue per **distinct amount** per kind, citing every clause that states it.
  Two different amounts still give two issues.
- `agent.report_findings`: an issue with `within_cap=True` that is not cleared is emitted as
  `Severity.INFO`, confidence 0, titled "Deposit is within the legal cap (scope not confirmed)"
  ("Holding deposit ..." for the holding rule). The scope doubts stay in `detail`. It cannot move a
  check (the orchestrator ignores info and confidence below 0.6). Over-cap results are unchanged.
- 5 new tests in `tests/test_rules.py`, plus a README paragraph. `make check` passes (1371 tests).
- Live check on 8200: the S4 contract now gives one info finding quoting three clauses.

## What I need from you
1. Check that "within cap but scope unconfirmed = info note" fits your policy. The alternative is to
   pass `jurisdiction="england"` / `tenancy_type="ordinary_private"` from the adapter when the
   listing is a London address, so the pass really is `cleared`. That is your call; I did not do it.
2. If you'd rather keep the pass as a low concern, say so. The web side (E16, Audrey) no longer
   counts low/<0.6 findings as red flags either way.

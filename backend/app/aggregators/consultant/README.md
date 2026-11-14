# consultant

Owner: Georgi (WS F). Picks the next 1 to 3 questions or actions for the student.
Returning `[]` means nothing useful is left to ask, which triggers the final decision.

## How it chooses

1. **Library.** `action_library.yaml` holds 2 to 3 candidates for each of the 8 checks.
2. **Selection.** Only checks that are still UNVERIFIED get an action. A cleared check is settled,
   and a suspicious one cannot be cleared by an answer. Anything the student has already been given
   (open, done, skipped or impossible) is never offered again, and a check with an open action gets
   nothing new until that one is answered. One action per check per round.
3. **Ranking.** By how many points the check is holding up in the score (`ScoreResult.contributions`),
   largest first; ties go in library order. Plain code, no LLM.
4. **Wording.** One LLM call (`prompts/reword.md`) may reword each action's `lead` to fit the case.
   The closing yes/no question is never reworded, and the library text is used if the call fails.

Every closing question is written so that "yes" is the reassuring answer. The orchestrator's keyword
fallback reads "yes" as clearing the check and "no" as flagging it, so keep new entries that way round.

## Modes

Like the agents, the consultant has a stub: the four fixed Phase 0 actions in `stub.py`. That is the
default, and the cross-cutting tests in `backend/tests/` rely on it. Switch the library version on
with `AGENT_MODE_CONSULTANT=real` in your local `.env` (or `DEFAULT_AGENT_MODE=real`).

## Files

| File | Role |
| --- | --- |
| `action_library.yaml` | Candidates per check: `id`, `kind`, `lead`, `ask`, `why` |
| `consultant.py` | `propose_actions`: selection, ranking, rewording |
| `models.py` | Library entry and the LLM's reply |
| `stub.py` | Phase 0 fixed actions |
| `prompts/reword.md` | Rewording prompt |

# Voice call lines reach the message checker as student messages

- From: Danny
- To: Georgi
- Status: open
- Branch / PR: `feat/voice-debrief`, merged into `main` (def16e8)

## What happened

When a voice call with Warden ends, the orchestrator saves it (`POST /cases/{id}/debrief`,
`orchestrator/debrief.py`):

- one `Evidence` of kind `call_recording`, with the transcript as `extracted_text`;
- each line the student said as a `Message` with `sender="student"` and `channel="call"`.

Those messages are new input, so the message checker and the emotion classifier rerun on them.

The lines are often reported speech about the letting agent, for example "The agent said I can't
view it until I pay the deposit". Today the message checker only raises red flags on
`sender == "agent"` messages:

- `agents/message_checker/rules.py:313`: `_agent()` filters the rule input to agent messages.
- `agents/message_checker/llm.py:188`: an LLM flag on a non-agent message is dropped.

So what the student tells Warden on a call never becomes a message-checker finding. Student lines
can still clear things, for example `viewing_done_index` at `rules.py:425`. The debrief does still
record the student's answers to open steps (the reply parser), so the student's account is not
lost; it just isn't a finding.

## What I need from you

Your call, as owner of `agents/message_checker/` (and `emotion_classifier/`, which also splits by
sender):

1. Should a `channel="call"` student message that reports what the agent said ("they said", "the
   agent wants") be read as reported agent behaviour? For example, flag it at lower confidence than
   the agent's own words, quote the student's line, and never make it a hard flag on its own (the
   payment confirmation would still ask first).
2. Or keep it as it is: findings only from the agent's own words, with the call handled through the
   steps.

If you want a different shape from the orchestrator instead (for example a different `sender` or a
marker on reported lines), tell me. `contracts/` is frozen, so it would need a contracts branch.

## How to check it

- `cd backend && uv run pytest tests/test_service_debrief.py -q` shows how call lines are stored.
- Repro (run on `main`, with no LLM key): put one message in a case JSON,
  `{"id": "msg_1", "evidence_id": "ev_call", "sender": "student", "channel": "call", "text": "The agent said I can't view it until I pay the deposit."}`,
  then run `cd backend && uv run python -m scripts.run_agent message_checker <case.json>`.
  - As a student call line: no findings.
  - The same case with `"sender": "agent"` and "You can't view it until you pay the deposit.":
    `payment_before_viewing` (hard flag) and `viewing_refused`.

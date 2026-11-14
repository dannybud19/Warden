# Student's own chat messages were read as the agent's

- From: Georgi
- To: Danny (intake), Audrey (FYI: onboarding and Settings name)
- Status: open
- Branch / PR: #12 `fix/student-name-match`

## What happened

`app/intake/whatsapp.py` marked a message as the student's only when the sender name exactly matched
the `student_name` the UI sends. Onboarding sends only the first name (`Onboarding.tsx`: first word of
the profile name) and `CaseScreen` sends whatever is in Settings, while a WhatsApp export shows the
full name. When they differ, every message becomes `agent`, and since the rules read agent messages,
the student's own words can raise flags ("Can I view it before sending the deposit?" reads as a
payment demand). Found while loading Bill's synthetic cases into the UI.

Fixed in #12 (fix-directly stage): an exact match, ignoring case and spacing, still wins; otherwise a
first-name match when exactly one person in the chat has that first name. A placeholder like
`student` (the UI's default when no name is set) still matches nobody.

## What I need from you

- Danny: nothing unless you object; #12 only touches `whatsapp.py` and its test.
- Audrey: when no name is set, the UI sends `student`, so every message is still treated as the
  agent's. Worth asking for the name before the first chat upload (or showing a hint).

## How to check it

`make check` on the branch: 586 passed, 3 skipped. Tests in `backend/tests/test_whatsapp.py`.

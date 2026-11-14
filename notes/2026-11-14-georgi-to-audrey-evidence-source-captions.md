# Evidence quotes now say where they come from

- From: Georgi
- To: Audrey
- Status: open
- Branch / PR: #10 `feat/evidence-source` (draft, your call)

## What happened

Testing the case page: a flag card showed a quote with only "From your chats · 14 Nov", so with a long
chat or several uploads the student cannot tell which message it is. PR #10 adds a caption under each
quote, for example `Chat (overseas_landlord.txt) · message 3 of 6 · David · 10 Nov, 09:41`.

- `src/lib/selectors.ts`: new `quoteSource(c, ref)`. Upload kind and filename, then (when the quote is
  in a parsed message) its position, sender (`landlord.name` or "the agent", or "you") and time.
  Non-upload evidence ids get plain names ("Companies House register", "Your notes").
- `RiskView.tsx`, `FlagCard`: shows every quote a finding cites (it showed only the first), each with
  its caption, as a `figure` / `figcaption`.
- `Dashboard.tsx`, `TileDetail`: caption under the quote; it now receives `c`.

## What I need from you

Review the wording and look of the caption (12.5px, muted, under the quote). Change anything you like,
merge it, or close it and do it your way. No backend change, so nothing else depends on it.

## How to check it

`git switch feat/evidence-source`, then in `web/`: `pnpm typecheck && pnpm lint && pnpm build` (all pass).
Live: open a case, upload a WhatsApp export, open a flag and tap "See evidence".

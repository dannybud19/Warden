This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Yet to verify

The gauge is labelled **Yet to verify** and displays the exact latest backend score as `84/100`, without
rounding it or changing it to fit a colour. It measures remaining weighted uncertainty or concerns:
unverified and suspicious checks keep their full weight; cleared checks reduce it according to their
confidence. Clearing landlord identity (weight 20%) at 80% confidence takes 100 to 84. It is neither
a scam probability nor a percentage of unfinished checks. The explanation is behind the keyboard-
accessible “About Yet to verify” information button. A red verdict always takes precedence over a low
number, and the gauge remains visible. The shared presentation in
`src/lib/present.ts` drives the headline, gauge colour and status pill: neutral for unverified checks,
amber for concerns or a targeted payment-confirmation question, red only for a `likely_scam` verdict,
and green only when all eight checks are cleared. Neutral answers are labelled "Answered", not "Done".

Run `corepack pnpm test`, `corepack pnpm typecheck`, `corepack pnpm lint` and `corepack pnpm build`
from this folder. The presentation regression tests are offline and use the existing TypeScript compiler.

## Listing photos

The featured home, home grid and case header try the supplied listing URL through
`GET /api/listing-photo?url=...`. The server reads [Open Graph](https://ogp.me/), Twitter image metadata
or JSON-LD image fields, then proxies one declared image. No API key or new dependency is needed.
The photo is presentation only: it never clears a check or establishes that the property is genuine.

Missing links, blocked sites, missing/broken images and timeouts retain the existing default picture
with a visible **Default placeholder** badge, also shown during loading. Sites requiring login,
JavaScript or an anti-bot challenge can fall back; the preview does not bypass those restrictions.
The browser caches successful previews for one hour and failures for one minute. Image requests
include a selection version (`v=2`) so the earlier cached OpenRent logo is replaced on the next page
load. Bump that version when selection changes; a server-side fix alone cannot invalidate a fresh
browser cache entry. OpenRent's generic share logo is skipped in favour of its JSON-LD property photo.

Only public HTTPS destinations are fetched. Each redirect and image host is checked; connections
are pinned to checked public IPv4 addresses with hostname TLS verification. Private/reserved IPs,
credentials, nonstandard ports, non-image responses and SVG are rejected. Requests share a ten-second
deadline, at most three redirects per resource, a 1 MiB HTML limit and a 5 MiB image limit. No incoming
cookies or authorization headers are forwarded. IPv6-only sites use the placeholder for now.

## Upload progress and recovery

Both New case and existing cases use the layout's `UploadQueue`. The case page lists each filename,
progress, and outcome; successful files are kept when a neighbour fails. **Retry — select file** always
opens a new file picker. A receipt distinguishes saved/read from saved/unreadable. Session storage keeps
progress metadata, never file bytes. The server recognises the same retry identity and bytes, so a lost
response does not duplicate evidence. Audio/video are labelled saved without claiming media analysis.

New case sends an initial attachment manifest before checks start. Any unfinished or unreadable initial
file keeps the case open until a successful retry or **Continue without this file**. The server manifest
restores progress after a reload or on another device; Mongo keeps it across server restarts. Skipping
does not clear a check. The case page polls this status to recover lost responses. Add/Paste controls
explain when an upload/reply is running or a final decision has closed the case.

Email PDFs now use text extraction and OCR for scanned pages. Install the backend's updated lockfile
(`cd backend && uv sync`) and restart the API before testing. Limits and the offline verification results
are in [UPLOAD_VERIFICATION.md](UPLOAD_VERIFICATION.md) and the [intake README](../backend/app/intake/README.md).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

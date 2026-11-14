# Warden mascot

Drop-in animated mascot. One file plus five images, with no dependencies.

## Files

- `warden-mascot.js` is the component
- `warden-default.webp`, `warden-green.webp`, `warden-amber.webp`, `warden-red.webp`, `warden-stop.webp`, `warden-stop-sign.webp`, `warden-amber-flag.webp` and `warden-red-excl.webp` are the artwork

Put all nine in one public folder, e.g. `/public/warden/`.

## Plain HTML

```html
<script src="/warden/warden-mascot.js"></script>
<warden-mascot state="default" assets="/warden/" style="width: 320px"></warden-mascot>
```

## React / Next.js

```jsx
import { useEffect } from "react";

export function Warden({ state = "default", size = 320 }) {
  useEffect(() => { import("/warden/warden-mascot.js"); }, []);
  return <warden-mascot state={state} assets="/warden/" style={{ width: size }} />;
}

// <Warden state={verdict} />
```

In Next.js, load the script with `<Script src="/warden/warden-mascot.js" />` instead of the dynamic import if you prefer.

## States

| state | when to use it |
|---|---|
| `default` | idle, waiting for a listing |
| `thinking` | agents are running |
| `green` | low risk |
| `amber` | not proven, worth checking |
| `red` | likely scam |
| `stop` | the payment checkpoint |

Change the state by updating the attribute (or `el.state = "red"`). Warden jumps between poses and turns into three dots for `thinking`. Each change fires a `wardenstatechange` event. Users can tap Warden to poke it. The animation respects reduced-motion settings.

Example mapping from the scoring agent:

```js
const state = running ? "thinking"
  : aboutToPay && score >= 40 ? "stop"
  : score >= 70 ? "red"
  : score >= 40 ? "amber"
  : "green";
```

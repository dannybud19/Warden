"use client";

import Script from "next/script";

/** States the animated mascot supports (see public/warden/README-mascot.md). */
export type WardenState = "default" | "thinking" | "green" | "amber" | "red" | "stop";

/**
 * The animated Warden mascot: a WebGL web component from /public/warden/warden-mascot.js.
 * Height follows a 1000:1100 box (room for the floor reflection). Tapping it pokes Warden.
 */
export function AnimatedWarden({
  state = "default", width, className = "",
}: { state?: WardenState; width: number; className?: string }) {
  return (
    <>
      <Script src="/warden/warden-mascot.js" strategy="afterInteractive" />
      <warden-mascot
        state={state}
        assets="/warden/"
        aria-hidden
        className={`block shrink-0 ${className}`}
        style={{ width, aspectRatio: "1000 / 1100" }}
      />
    </>
  );
}

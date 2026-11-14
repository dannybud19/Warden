"use client";

import Script from "next/script";
import { useEffect, useRef } from "react";
import { motion } from "motion/react";

/** States the animated mascot supports (see public/warden/README-mascot.md). */
export type WardenState = "default" | "wave" | "thinking" | "green" | "amber" | "red" | "stop";

type MascotEl = HTMLElement & { poke?: () => void };

/**
 * The animated Warden mascot: a WebGL web component from /public/warden/warden-mascot.js.
 * Height follows a 1000:1100 box (room for the floor reflection). Tapping it pokes Warden.
 * `lively` adds a gentle float and a little bounce every few seconds, for hero spots.
 */
export function AnimatedWarden({
  state = "default", width, className = "", lively = false,
}: { state?: WardenState; width: number; className?: string; lively?: boolean }) {
  const ref = useRef<MascotEl>(null);

  useEffect(() => {
    if (!lively || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => ref.current?.poke?.(), 4200);
    return () => window.clearInterval(id);
  }, [lively]);

  const el = (
    <warden-mascot
      ref={ref}
      state={state}
      assets="/warden/"
      aria-hidden
      className={`block shrink-0 ${lively ? "" : className}`}
      style={{ width, aspectRatio: "1000 / 1100" }}
    />
  );

  return (
    <>
      <Script src="/warden/warden-mascot.js" strategy="afterInteractive" />
      {lively ? (
        <motion.div
          className={className}
          animate={{ y: [0, -10, 0] }}
          transition={{ duration: 3.4, repeat: Infinity, ease: "easeInOut" }}
        >
          {el}
        </motion.div>
      ) : (
        el
      )}
    </>
  );
}

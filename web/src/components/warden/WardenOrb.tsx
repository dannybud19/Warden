"use client";

import Script from "next/script";
import { useEffect, useRef, type RefObject } from "react";

export type OrbMode = "idle" | "listening" | "speaking" | "thinking";

type OrbEl = HTMLElement & { level: number; mic: number };

/**
 * Warden on a voice call: the teal bubble orb from /public/warden/warden-orb.js.
 * `levelRef` / `micRef` (0..1) are read every frame so the orb bounces with Warden's voice and your mic.
 */
export function WardenOrb({
  mode, size, levelRef, micRef,
}: { mode: OrbMode; size: number; levelRef?: RefObject<number>; micRef?: RefObject<number> }) {
  const el = useRef<OrbEl>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      if (el.current) {
        el.current.level = levelRef?.current ?? 0;
        el.current.mic = micRef?.current ?? 0;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [levelRef, micRef]);

  return (
    <>
      <Script src="/warden/warden-orb.js" strategy="afterInteractive" />
      <warden-orb ref={el} mode={mode} mood="calm" aria-hidden className="block" style={{ width: size }} />
    </>
  );
}

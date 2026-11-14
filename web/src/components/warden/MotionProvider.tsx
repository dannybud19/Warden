"use client";

import { MotionConfig } from "motion/react";

/** Every animation respects the viewer's "reduce motion" setting. */
export function MotionProvider({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

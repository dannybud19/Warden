"use client";

import { motion } from "motion/react";

// Re-mounted on every navigation (unlike the layout), so each page's content eases in while the shared
// frame (nav, teal band, pixels) stays put.
export default function ProductTemplate({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

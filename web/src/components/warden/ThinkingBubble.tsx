"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

// What Warden is up to while he works on an answer; the last word keeps changing.
const WORDS = [
  "thinking", "deciphering", "analyzing", "cross-checking", "sniffing around", "connecting the dots", "reading between the lines",
];

/** "Warden is thinking…" in the chat: the verb swaps every moment with a soft blur, a teal shimmer and pulsing dots. */
export function ThinkingBubble({ roomy = false }: { roomy?: boolean }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setI((n) => (n + 1) % WORDS.length), 1700);
    return () => window.clearInterval(id);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: { duration: 0.15 } }}
      role="status"
      aria-label="Warden is thinking"
      className={`flex items-baseline self-start px-1 py-1.5 font-medium tracking-[-0.01em] ${roomy ? "text-[15px]" : "text-[13.5px]"}`}
    >
      <span className="text-ink/55">Warden is&nbsp;</span>
      <motion.span layout transition={{ type: "spring", stiffness: 380, damping: 32 }} className="relative inline-flex overflow-visible">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={WORDS[i]}
            initial={{ opacity: 0, y: 9, filter: "blur(5px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -9, filter: "blur(5px)" }}
            transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
            className="whitespace-nowrap"
          >
            <motion.span
              className="bg-[linear-gradient(90deg,#138a93_0%,#138a93_40%,#3fa9b0_50%,#138a93_60%,#138a93_100%)] bg-[length:240%_100%] bg-clip-text text-transparent"
              animate={{ backgroundPosition: ["100% 0%", "0% 0%"] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "linear" }}
            >
              {WORDS[i]}
            </motion.span>
          </motion.span>
        </AnimatePresence>
      </motion.span>
      <motion.span layout transition={{ type: "spring", stiffness: 380, damping: 32 }} aria-hidden className="ml-[1px] inline-flex text-teal">
        {[0, 1, 2].map((d) => (
          <motion.span
            key={d}
            animate={{ opacity: [0.2, 1, 0.2] }}
            transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut", delay: d * 0.2 }}
          >
            .
          </motion.span>
        ))}
      </motion.span>
    </motion.div>
  );
}

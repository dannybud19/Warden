"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Copy, Check, MessageSquareReply } from "lucide-react";
import type { Action } from "@/lib/types";
import { whyAsk } from "@/lib/present";
import { useLocalJSON } from "@/lib/localStore";
import { Dot, Mascot, PillButton, rise } from "./primitives";

// Quick answers. The wording matters: the backend reads "yes" as clearing the check and "no" as a flag.
const QUICK_ANSWERS = [
  { label: "Yes, they did", text: "Yes, they did." },
  { label: "No, they wouldn't", text: "No, they wouldn't." },
];

/**
 * "Your next step": the one thing Warden needs from the student, on its own in the main column.
 * Copy the question, send it to the letting agent, then tell Warden what they said.
 */
export function NextStep({
  action, busy, onSkip, onAnswer, onPaste,
}: { action: Action; busy: boolean; onSkip: () => void; onAnswer: (text: string) => void; onPaste: () => void }) {
  // remember "sent" per question so the card stays in its waiting state after a reload
  const [sentIds, setSentIds] = useLocalJSON<string[]>("warden.sentQuestions", []);
  const sent = sentIds.includes(action.id);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(action.text);
    } catch {
      /* clipboard blocked: they can still copy it by hand */
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
    if (!sent) setSentIds([...sentIds, action.id]);
  }

  return (
    <motion.section
      variants={rise}
      layout
      className="relative flex items-start gap-5 overflow-hidden rounded-[24px] border border-aqua bg-white px-7 py-6 shadow-card"
    >
      <Mascot width={46} height={55} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <AnimatePresence mode="wait" initial={false}>
          {sent ? (
            <motion.span
              key="w"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              className="inline-flex items-center gap-[7px] rounded-full bg-mint py-1 pl-2.5 pr-3 text-[12px] font-medium text-[#0f6d74]"
            >
              <Dot src="/warden/dot-teal.svg" pulse /> {copied ? "Copied. Send it to them" : "Waiting for their reply"}
            </motion.span>
          ) : (
            <motion.span key="n" className="inline-flex items-center gap-[7px] rounded-full bg-[#fcebe7] py-1 pl-2.5 pr-3 text-[12px] font-medium text-[#9a3a27]">
              <Dot src="/warden/dot-red.svg" pulse /> Your next step
            </motion.span>
          )}
        </AnimatePresence>
        <p className="mt-3 text-[20px] font-medium leading-[1.3] tracking-[-0.01em]">{action.text}</p>
        <p className="mt-1.5 text-[14px] leading-[1.5] text-muted">{whyAsk(action)}</p>

        <AnimatePresence mode="wait" initial={false}>
          {sent ? (
            <motion.div key="answer" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="mt-4">
              <p className="text-[13.5px] font-medium">What did they say?</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {QUICK_ANSWERS.map((q) => (
                  <PillButton key={q.label} variant="secondary" disabled={busy} onClick={() => onAnswer(q.text)}>
                    {q.label}
                  </PillButton>
                ))}
                <PillButton variant="soft" disabled={busy} onClick={onPaste}>
                  <MessageSquareReply size={15} /> Paste their reply
                </PillButton>
                <span className="ml-auto flex gap-4 text-[13px] text-ink/50">
                  <button type="button" onClick={copy} className="cursor-pointer hover:text-teal">Copy again</button>
                  <button type="button" disabled={busy} onClick={onSkip} className="cursor-pointer hover:text-ink">Skip</button>
                </span>
              </div>
            </motion.div>
          ) : (
            <motion.div key="ask" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="mt-4 flex gap-2">
              <PillButton onClick={copy}>
                {copied ? <Check size={15} /> : <Copy size={15} />} Copy question
              </PillButton>
              <PillButton variant="secondary" disabled={busy} onClick={onSkip}>Skip for now</PillButton>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.section>
  );
}

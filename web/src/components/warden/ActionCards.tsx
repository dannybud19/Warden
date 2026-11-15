"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, Circle, Flag, MinusCircle } from "lucide-react";
import type { Action, Case } from "@/lib/types";
import { CHECK_LABELS } from "@/lib/labels";
import { whyAsk } from "@/lib/present";
import { PillButton, rise } from "./primitives";

type CardStatus = "todo" | "done" | "flagged" | "skipped";

const RETIRED_ANSWER = "No longer needed: your evidence already covers this.";
const MAX_ANSWERED = 4;

const STATUS_LOOK: Record<CardStatus, { label: string; cls: string }> = {
  todo: { label: "To do", cls: "bg-white text-ink/70 border-line" },
  done: { label: "Done", cls: "bg-mint text-[#0f6d74] border-mint" },
  flagged: { label: "Flagged", cls: "bg-[#fdf0d5] text-[#8a5a00] border-[#fdf0d5]" },
  skipped: { label: "Skipped", cls: "bg-[#eeeeee] text-ink/60 border-[#eeeeee]" },
};

function cardStatus(a: Action): CardStatus {
  const s = a.status ?? "open";
  if (s === "open") return "todo";
  if (s === "skipped" || s === "impossible") return "skipped";
  return a.outcome === "flags" ? "flagged" : "done";
}

/** Open actions first, then the last few answered ones (derived from the case, so it survives a reload). */
export function cardActions(c: Case): Action[] {
  const all = c.actions ?? [];
  const open = all.filter((a) => (a.status ?? "open") === "open");
  const closed = all
    .filter((a) => (a.status ?? "open") !== "open" && a.answer !== RETIRED_ANSWER)
    .slice(-MAX_ANSWERED);
  return [...open, ...closed];
}

function StatusIcon({ status }: { status: CardStatus }) {
  if (status === "done") return <Check size={13} aria-hidden />;
  if (status === "flagged") return <Flag size={13} aria-hidden />;
  if (status === "skipped") return <MinusCircle size={13} aria-hidden />;
  return <Circle size={13} aria-hidden />;
}

function StatusBadge({ status }: { status: CardStatus }) {
  const look = STATUS_LOOK[status];
  return (
    <motion.span
      key={status}
      initial={{ scale: 0.8, opacity: 0.4 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ type: "spring", stiffness: 500, damping: 28 }}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-medium leading-none transition-colors ${look.cls}`}
    >
      <StatusIcon status={status} />
      {look.label}
    </motion.span>
  );
}

function Card({
  action, index, busy, disabled, onAnswer, onSkip,
}: {
  action: Action; index: number; busy: boolean; disabled: boolean;
  onAnswer: (id: string, text: string) => void; onSkip: (id: string) => void;
}) {
  const status = cardStatus(action);
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  const off = busy || disabled;
  const label = CHECK_LABELS[action.check_id as keyof typeof CHECK_LABELS] ?? action.check_id;

  function submit() {
    const t = text.trim();
    if (!t || off) return;
    onAnswer(action.id, t);
    setText("");
    setTyping(false);
  }

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      data-testid="action-card"
      data-status={status}
      data-action-id={action.id}
      className="flex gap-4 rounded-[20px] border border-line bg-white px-5 py-4 shadow-card"
    >
      <span
        aria-hidden
        className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-mint text-[13px] font-medium text-teal"
      >
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <p className="text-[15.5px] font-medium leading-[1.35]">{action.text}</p>
          <AnimatePresence mode="wait" initial={false}>
            <StatusBadge key={status} status={status} />
          </AnimatePresence>
        </div>
        <p className="mt-1 text-[13px] leading-[1.45] text-muted">
          <span className="font-medium text-ink/70">Why: {label}.</span> {whyAsk(action)}
        </p>
        {status !== "todo" && action.answer && (
          <p className="mt-1.5 line-clamp-1 text-[13px] text-ink/70">
            <span className="font-medium">Your answer:</span> {action.answer}
          </p>
        )}
        {status === "todo" && (
          <div className="mt-3">
            {typing ? (
              <div className="flex gap-2">
                <input
                  autoFocus
                  value={text}
                  disabled={off}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submit();
                    if (e.key === "Escape") { setTyping(false); setText(""); }
                  }}
                  aria-label={`What happened with: ${action.text}`}
                  placeholder="What happened? (Enter to send, Esc to cancel)"
                  className="min-w-0 flex-1 rounded-full border border-line bg-white px-4 py-2 text-[13.5px] outline-none focus:border-teal"
                />
                <PillButton aria-label="Send answer" disabled={off || !text.trim()} onClick={submit}>Send</PillButton>
              </div>
            ) : (
              <div className="flex gap-2">
                <PillButton aria-label={`I did it: ${action.text}`} disabled={off} onClick={() => setTyping(true)}>
                  <Check size={15} /> I did it
                </PillButton>
                <PillButton variant="secondary" aria-label={`Skip: ${action.text}`} disabled={off} onClick={() => onSkip(action.id)}>
                  Skip
                </PillButton>
              </div>
            )}
          </div>
        )}
      </div>
    </motion.li>
  );
}

/**
 * Numbered cards for what Warden is waiting on: open actions first, then the latest answered ones.
 * Motion respects reduced-motion through MotionProvider (MotionConfig reducedMotion="user").
 */
export function ActionCards({
  c, busy, disabled, onAnswer, onSkip,
}: {
  c: Case; busy: boolean; disabled: boolean;
  onAnswer: (actionId: string, text: string) => void; onSkip: (actionId: string) => void;
}) {
  const cards = cardActions(c);
  if (cards.length === 0) return null;
  return (
    <motion.section variants={rise} aria-label="Your steps" data-testid="action-cards">
      <h2 className="mb-3 text-[13px] font-medium uppercase tracking-[0.04em] text-muted">Your steps</h2>
      <ul className="flex list-none flex-col gap-3 p-0">
        <AnimatePresence initial={false}>
          {cards.map((a, i) => (
            <Card key={a.id} action={a} index={i + 1} busy={busy} disabled={disabled} onAnswer={onAnswer} onSkip={onSkip} />
          ))}
        </AnimatePresence>
      </ul>
    </motion.section>
  );
}

"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { Action, ChatEntry, EvidenceKind } from "@/lib/types";
import { CHIP, agentSummary, whyAsk, type AgentRow, type Mood, type Suggestion } from "@/lib/present";
import { AnimatedWarden } from "./AnimatedWarden";
import { Dot, Mascot, PillButton } from "./primitives";

// Right side of the one-home screen (Figma "Agents rail", 52:199): who is working on it and what they need.

const AGENT_NAME: Record<string, { name: string; icon: string; job: string }> = {
  companies_house: { name: "Agency checker", icon: "/warden/agent-agency.png", job: "Checks agency" },
  message_checker: { name: "Chat reader", icon: "/warden/agent-chat.png", job: "Reads chats" },
  emotion_classifier: { name: "Pressure spotter", icon: "/warden/agent-pressure.png", job: "Spots pressure" },
  contract_checker: { name: "Contract reader", icon: "/warden/agent-contract.png", job: "Reads contract" },
  video_analysis: { name: "Video checker", icon: "/warden/agent-video.png", job: "Checks video" },
};

/** Guess the evidence kind from a picked file. */
export function kindOf(file: File): EvidenceKind {
  const name = file.name.toLowerCase();
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "call_recording";
  if (file.type.startsWith("image/")) return "chat_screenshot";
  if (/contract|tenancy|agreement|\bast\b/.test(name)) return "contract";
  if (name.endsWith(".txt") || name.endsWith(".zip")) return "chat_export";
  if (name.endsWith(".eml")) return "email";
  return "document";
}

const STARS = [
  { src: "/warden/star-lg.svg", size: 26, left: 77, top: 95, delay: 0 },
  { src: "/warden/star-md.svg", size: 18, left: 317, top: 127, delay: 0.8 },
  { src: "/warden/star-sm.svg", size: 12, left: 91, top: 149, delay: 1.6 },
];

function NeedsYou({ action, busy, onSkip }: { action: Action; busy: boolean; onSkip: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(action.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked */
    }
  }
  return (
    <div className="rounded-[20px] border border-aqua bg-white p-[15px] drop-shadow-[0px_8px_11px_rgba(27,111,117,0.07)]">
      <span className="inline-flex items-center gap-[7px] rounded-full bg-[#fcebe7] py-[3px] pl-2 pr-[9px] text-[11px] font-medium text-[#9a3a27]">
        <Dot src="/warden/dot-red.svg" pulse /> Needs you
      </span>
      <p className="mt-2.5 text-[15.5px] font-medium leading-[1.3]">{action.text}</p>
      <p className="mt-1.5 text-[12px] leading-[1.45] text-muted [@media(max-height:760px)]:hidden">{whyAsk(action)}</p>
      <div className="mt-3 flex gap-2">
        <PillButton onClick={copy} className="py-2! text-[12.5px]!">
          <AnimatePresence mode="wait" initial={false}>
            <motion.span key={copied ? "c" : "q"} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.15 }}>
              {copied ? "Copied" : "Copy question"}
            </motion.span>
          </AnimatePresence>
        </PillButton>
        <PillButton variant="secondary" disabled={busy} onClick={onSkip} className="py-2! text-[12.5px]!">Skip</PillButton>
      </div>
    </div>
  );
}

export function AgentsRail({
  mood, action, rows, chat, busy, canReply, closed, onSkip, onAsk, onSend, onUpload,
}: {
  mood: Mood;
  action: Action | undefined;
  rows: AgentRow[];
  chat: ChatEntry[];
  busy: boolean;
  canReply: boolean;
  closed: boolean;
  onSkip: () => void;
  onAsk: (q: Suggestion) => void;
  onSend: (text: string) => void;
  onUpload: (kind: EvidenceKind, file: File) => void;
}) {
  const [text, setText] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const waiting = rows.filter((r) => r.chip === "waiting").length;
  // Once a conversation starts, give it the room: the mascot stage folds away and the team row compacts.
  const chatting = chat.length > 0;

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [chat.length]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t || !canReply) return;
    onSend(t);
    setText("");
  }

  return (
    <motion.aside
      aria-label="Agents"
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
      className="relative flex h-full flex-col overflow-hidden rounded-[28px] [&>*:not(.rail-grow)]:shrink-0 border border-white bg-[linear-gradient(to_bottom,#d6eff1,#bee4e7)] px-[15px] pb-4 shadow-card"
    >
      <p className="mt-[9px] text-center text-[10px] font-semibold tracking-[1.2px] text-teal">AGENTS</p>
      <p className="mt-1 text-center text-[14px] text-ink/70 [@media(max-height:760px)]:hidden">Warden is checking this home with you</p>

      {/* mascot peeking over the Needs-you card */}
      <motion.div
        className="shrink-0 overflow-hidden"
        initial={false}
        animate={{ height: chatting ? 0 : "auto", opacity: chatting ? 0 : 1 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
      <div className="pointer-events-none relative mx-auto h-[150px] w-full shrink-0 [@media(max-height:880px)]:h-[100px] [@media(max-height:760px)]:hidden">
        <div className="absolute left-1/2 top-[-6px] size-[200px] -translate-x-1/2">
          <Image src="/warden/rail-halo.svg" alt="" width={320} height={320} unoptimized className="absolute inset-[-30%] max-w-none" />
        </div>
        {STARS.map((s) => (
          <motion.div
            key={s.src}
            className="absolute"
            style={{ left: s.left - 15, top: s.top - 46, width: s.size, height: s.size }}
            animate={{ opacity: [0.4, 1, 0.4], scale: [0.85, 1.1, 0.85] }}
            transition={{ duration: 2.4, repeat: Infinity, delay: s.delay, ease: "easeInOut" }}
          >
            <Image src={s.src} alt="" width={s.size} height={s.size} unoptimized />
          </motion.div>
        ))}
        <div className="pointer-events-auto absolute left-1/2 top-[-10px] origin-top -translate-x-1/2 [@media(max-height:880px)]:top-[-4px] [@media(max-height:880px)]:scale-[0.64]">
          <AnimatedWarden state={mood.state} width={250} />
        </div>
      </div>

      </motion.div>
      <div className={`relative z-10 ${chatting ? "mt-3" : ""}`}>
        <AnimatePresence mode="popLayout" initial={false}>
          {action ? (
            <motion.div
              key={action.id}
              initial={{ opacity: 0, y: 16, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40 }}
              transition={{ type: "spring", stiffness: 300, damping: 28 }}
            >
              <NeedsYou action={action} busy={busy} onSkip={onSkip} />
            </motion.div>
          ) : (
            <motion.div
              key="none"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-[20px] border border-white bg-white/90 p-[15px]"
            >
              <p className="text-[15px] font-medium">Nothing needs you right now</p>
              <p className="mt-1 text-[12px] text-muted">{mood.sub}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="mt-[18px] flex items-baseline gap-3 px-2">
        <p className="text-[13px] font-medium">Your team</p>
        <p className="text-[12px] text-muted">
          {agentSummary(rows, 0).replace(/(\d+) waiting/, waiting ? "$1 waiting for evidence" : "$1 waiting")}
        </p>
      </div>
      <ul className="mt-2.5 grid grid-cols-5 gap-2">
        {rows.map((r, i) => {
          const a = AGENT_NAME[r.name];
          const chip = CHIP[r.chip];
          const waiting = r.chip === "waiting";
          return (
            <motion.li
              key={r.name}
              tabIndex={0}
              aria-label={`${a?.name ?? r.meta.title}: ${chip.label}. ${r.line}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 + i * 0.06, type: "spring", stiffness: 300, damping: 24 }}
              whileHover="hover"
              whileFocus="hover"
              className={`group relative flex cursor-default flex-col items-center rounded-[18px] px-1 outline-none transition-[padding] ${chatting ? "py-1.5" : "pb-2.5 pt-2"} focus-visible:ring-2 focus-visible:ring-teal ${waiting ? "bg-white/50" : "bg-white/85"}`}
            >
              <motion.span
                className={`relative transition-all ${chatting ? "size-8" : "size-12"}`}
                variants={{ hover: { y: -3, rotate: [0, -8, 6, 0] } }}
                animate={r.chip === "checking" ? { scale: [1, 1.08, 1] } : undefined}
                transition={r.chip === "checking" ? { duration: 1, repeat: Infinity } : { duration: 0.45 }}
              >
                <Image src={a?.icon ?? r.meta.icon} alt="" fill sizes="48px" className={`object-contain ${waiting ? "opacity-55 grayscale-[40%]" : ""}`} />
                <span className="absolute -right-0.5 -top-0.5 rounded-full bg-white p-[2px] shadow-tab">
                  <Dot src={chip.dot} size={8} pulse={r.chip === "checking"} />
                </span>
              </motion.span>
              <span className={`mt-1.5 text-center text-[11.5px] font-medium leading-[1.2] ${chatting ? "hidden" : ""} ${waiting ? "text-muted" : "text-ink/85"}`}>
                {a?.job ?? r.meta.title}
              </span>

              {/* what it found, on hover / focus */}
              <motion.span
                role="tooltip"
                className={`pointer-events-none absolute bottom-[calc(100%+8px)] z-20 w-[200px] rounded-[14px] ${i === 0 ? "left-0" : i === rows.length - 1 ? "right-0" : "left-1/2 -translate-x-1/2"} bg-ink px-3 py-2.5 text-[12px] leading-[1.4] text-white shadow-glass`}
                initial={{ opacity: 0, y: 6, scale: 0.96 }}
                variants={{ hover: { opacity: 1, y: 0, scale: 1 } }}
                transition={{ type: "spring", stiffness: 420, damping: 30 }}
              >
                <span className="flex items-center gap-1.5 font-medium">
                  <Dot src={`/warden/dot-xs-${r.tone}.svg`} size={6} /> {a?.name}
                </span>
                <span className="mt-0.5 block text-white/80">{r.line}</span>
              </motion.span>
            </motion.li>
          );
        })}
      </ul>

      <div className="mx-2 mt-3 h-px bg-white/80" />

      <div className="rail-grow flex min-h-0 flex-1 flex-col justify-end">
      {chat.length === 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-hidden px-6 text-center"
        >
          <motion.div animate={{ y: [0, -4, 0] }} transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}>
            <Mascot width={40} height={48} />
          </motion.div>
          <p className="mt-2 text-[14px] font-medium text-ink/80">Ask me anything about this home</p>
          <p className="mt-1 text-[12.5px] leading-[1.45] text-ink/55">Or forward the agent&apos;s reply and I&apos;ll check it.</p>
        </motion.div>
      )}
      <AnimatePresence initial={false}>
        {chat.length > 0 && (
          <motion.div
            ref={log}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="mt-3 flex min-h-[140px] flex-col gap-2 overflow-y-auto px-1 pt-3 [mask-image:linear-gradient(to_bottom,transparent,black_28px)]"
            aria-live="polite"
          >
            {chat.map((m, i) => (
              <motion.div
                key={`${m.at}-${i}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={
                  m.role === "student"
                    ? "max-w-[85%] self-end rounded-[16px] rounded-br-[6px] bg-teal px-3 py-2 text-[12.5px] leading-[1.45] text-white"
                    : "flex max-w-[92%] items-start gap-1.5 self-start"
                }
              >
                {m.role === "student" ? (
                  m.text
                ) : (
                  <>
                    <Mascot width={20} height={24} className="mt-1" />
                    <span className="rounded-[16px] rounded-tl-[6px] bg-white px-3 py-2 text-[12.5px] leading-[1.5]">{m.text}</span>
                  </>
                )}
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      </div>

      <div className="mt-3 flex flex-wrap gap-1.5 px-2">
        {(["Why is this a red flag?", "What should I say to them?"] as const).map((q) => (
          <motion.button
            key={q}
            type="button"
            onClick={() => onAsk(q)}
            whileHover={{ y: -1 }}
            whileTap={{ scale: 0.96 }}
            className="cursor-pointer rounded-full bg-white/80 px-2.5 py-1.5 text-[12px] leading-[normal] hover:bg-white"
          >
            {q === "What should I say to them?" ? "What do I say?" : q}
          </motion.button>
        ))}
      </div>

      <form onSubmit={submit} className="relative mt-3 h-[92px] rounded-[20px] bg-white shadow-card transition focus-within:ring-4 focus-within:ring-aqua/20">
        <label htmlFor="rail-input" className="sr-only">Message Warden</label>
        <input
          id="rail-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!canReply || busy}
          placeholder={closed ? "Warden has finished checking this home." : canReply ? "Ask Warden, or forward the agent's reply…" : "Nothing to answer right now."}
          autoComplete="off"
          className="absolute left-4 right-4 top-3.5 bg-transparent text-[13.5px] leading-[1.4] outline-none placeholder:text-hint disabled:cursor-not-allowed"
        />
        <motion.button
          type="button"
          disabled={closed || busy}
          onClick={() => file.current?.click()}
          whileTap={{ scale: 0.95 }}
          className="absolute left-4 top-[56px] cursor-pointer rounded-full border border-line bg-white py-1 pl-[9px] pr-2.5 text-[11.5px] font-medium leading-[normal] disabled:cursor-not-allowed disabled:opacity-50"
        >
          + Add evidence
        </motion.button>
        <input
          ref={file}
          type="file"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(kindOf(f), f);
            e.target.value = "";
          }}
        />
        <motion.button
          type="submit"
          aria-label="Send"
          disabled={!text.trim() || !canReply || busy}
          whileHover={{ scale: 1.06 }}
          whileTap={{ scale: 0.92 }}
          className="absolute right-4 top-[46px] flex size-[38px] cursor-pointer items-center justify-center rounded-full bg-teal disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Image src="/warden/icon-send-sm.svg" alt="" width={16} height={16} unoptimized />
        </motion.button>
      </form>
    </motion.aside>
  );
}

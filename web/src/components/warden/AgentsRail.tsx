"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { motion } from "motion/react";
import { Maximize2, Phone, X } from "lucide-react";
import type { ChatEntry, EvidenceKind } from "@/lib/types";
import { agentSummary, type AgentRow, type Mood, type Suggestion, type Tone } from "@/lib/present";
import { AnimatedWarden } from "./AnimatedWarden";
import { Mascot } from "./primitives";
import { CaseCall, type CallContext } from "./CaseCall";

// Right side of the one-home screen: who is working on it (Your team) and the chat with Warden.
// The one thing Warden needs from the student lives in the main column (NextStep.tsx).

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

type Look = { tile: string; badge: string; glyph: string; word: string };

/** Each agent's tile reads at a glance: tinted by what it found, with a status badge that isn't colour alone. */
function tileLook(r: AgentRow): Look {
  if (r.chip === "checking") return { tile: "bg-white/85 ring-1 ring-aqua", badge: "bg-teal text-white", glyph: "…", word: "Checking" };
  if (r.chip === "waiting") return { tile: "bg-white/45", badge: "bg-[#c9d6d9] text-white", glyph: "–", word: "Waiting" };
  if (r.chip === "error") return { tile: "bg-white/60", badge: "bg-[#9db0b4] text-white", glyph: "?", word: "Couldn't run" };
  const byTone: Record<Tone, Look> = {
    red: { tile: "bg-[#fdeee9] ring-1 ring-[#f1b9aa]", badge: "bg-[#e06a52] text-white", glyph: "!", word: "Red flag" },
    amber: { tile: "bg-[#fdf5e6] ring-1 ring-[#ecd29c]", badge: "bg-[#d99a2b] text-white", glyph: "!", word: "Worth a look" },
    green: { tile: "bg-[#ecf8f2] ring-1 ring-[#bfe3d2]", badge: "bg-[#2e9a7c] text-white", glyph: "✓", word: "Clear" },
    grey: { tile: "bg-white/85", badge: "bg-[#9db0b4] text-white", glyph: "✓", word: "Done" },
  };
  return byTone[r.tone];
}

function TeamTile({ r, i, count }: { r: AgentRow; i: number; count: number }) {
  const a = AGENT_NAME[r.name];
  const look = tileLook(r);
  const faded = r.chip === "waiting";
  return (
    <motion.li
      tabIndex={0}
      aria-label={`${a?.name ?? r.meta.title}: ${look.word}. ${r.line}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 + i * 0.05, type: "spring", stiffness: 300, damping: 24 }}
      whileHover="hover"
      whileFocus="hover"
      className={`group relative flex cursor-default flex-col items-center rounded-[16px] px-1 pb-2 pt-2 outline-none focus-visible:ring-2 focus-visible:ring-teal ${look.tile}`}
    >
      <motion.span
        className="relative size-10"
        variants={{ hover: { y: -3, rotate: [0, -8, 6, 0] } }}
        animate={r.chip === "checking" ? { scale: [1, 1.08, 1] } : undefined}
        transition={r.chip === "checking" ? { duration: 1, repeat: Infinity } : { duration: 0.45 }}
      >
        <Image src={a?.icon ?? r.meta.icon} alt="" fill sizes="40px" className={`object-contain ${faded ? "opacity-50 grayscale-[50%]" : ""}`} />
        <span
          aria-hidden
          className={`absolute -right-1.5 -top-1.5 flex size-[18px] items-center justify-center rounded-full text-[11px] font-bold leading-none ring-2 ring-white ${look.badge}`}
        >
          {look.glyph}
        </span>
      </motion.span>
      <span className={`mt-1 text-center text-[11px] font-medium leading-[1.2] ${faded ? "text-muted" : "text-ink/85"}`}>{a?.job ?? r.meta.title}</span>

      {/* what it found, on hover / focus */}
      <motion.span
        role="tooltip"
        className={`pointer-events-none absolute top-[calc(100%+8px)] z-30 w-[210px] rounded-[14px] ${i === 0 ? "left-0" : i === count - 1 ? "right-0" : "left-1/2 -translate-x-1/2"} bg-ink px-3 py-2.5 text-[12px] leading-[1.4] text-white shadow-glass`}
        initial={{ opacity: 0, y: -6, scale: 0.96 }}
        variants={{ hover: { opacity: 1, y: 0, scale: 1 } }}
        transition={{ type: "spring", stiffness: 420, damping: 30 }}
      >
        <span className="font-medium">{a?.name} · {look.word}</span>
        <span className="mt-0.5 block text-white/80">{r.line}</span>
      </motion.span>
    </motion.li>
  );
}

type Props = {
  mood: Mood;
  rows: AgentRow[];
  chat: ChatEntry[];
  busy: boolean;
  canReply: boolean;
  closed: boolean;
  onAsk: (q: Suggestion) => void;
  onSend: (text: string) => void;
  onUpload: (kind: EvidenceKind, file: File) => void;
  onClearChat?: () => void;
  /** Enables "Call Warden" for this home. */
  callContext?: CallContext;
  onCallLine?: (role: "student" | "orchestrator", text: string) => void;
  /** Set when there's an open question: a call can record the letting agent's answer to it. */
  onAnswer?: (text: string) => void;
};

export function AgentsRail(props: Props) {
  const { mood, rows } = props;
  const [expanded, setExpanded] = useState(false);
  const waiting = rows.filter((r) => r.chip === "waiting").length;

  return (
    <motion.aside
      aria-label="Agents"
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
      className="relative flex h-full flex-col rounded-[28px] border border-white bg-[linear-gradient(to_bottom,#d6eff1,#bee4e7)] px-[15px] pb-4 shadow-card [&>*:not(.rail-grow)]:shrink-0"
    >
      {/* compact header: Warden + what's going on */}
      <div className="flex items-center gap-2 pt-3">
        <div className="-my-3 -ml-1 shrink-0">
          <AnimatedWarden state={mood.state} width={74} />
        </div>
        <div className="min-w-0">
          <p className="text-[10px] font-semibold tracking-[1.2px] text-teal">AGENTS</p>
          <p className="text-[14px] leading-[1.3] text-ink/75">Warden is checking this home with you</p>
        </div>
      </div>

      <div className="mt-3 flex items-baseline gap-3 px-1">
        <p className="text-[13px] font-medium">Your team</p>
        <p className="truncate text-[12px] text-muted">
          {agentSummary(rows, 0).replace(/(\d+) waiting/, waiting ? "$1 waiting for evidence" : "$1 waiting")}
        </p>
      </div>
      <ul className="mt-2 grid grid-cols-5 gap-1.5">
        {rows.map((r, i) => <TeamTile key={r.name} r={r} i={i} count={rows.length} />)}
      </ul>

      <div className="mx-1 mt-3 h-px bg-white/80" />

      {expanded ? (
        <div className="rail-grow flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-center text-[13px] text-ink/60">
          Chat is open in the side panel.
          <button type="button" onClick={() => setExpanded(false)} className="cursor-pointer font-medium text-teal">Bring it back</button>
        </div>
      ) : (
        <ChatPane {...props} onExpand={() => setExpanded(true)} />
      )}

      {expanded &&
        createPortal(
          <ChatDrawer onClose={() => setExpanded(false)}>
            <ChatPane {...props} roomy />
          </ChatDrawer>,
          document.body,
        )}
    </motion.aside>
  );
}

function ChatDrawer({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <motion.div className="fixed inset-0 z-50 flex justify-end" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <div className="absolute inset-0 bg-ink/20 backdrop-blur-[3px]" onClick={onClose} aria-hidden />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="Chat with Warden"
        className="relative flex h-full w-[540px] max-w-full flex-col bg-[linear-gradient(to_bottom,#e3f4f5,#cdeaec)] px-5 pb-5 pt-4 shadow-glass"
        initial={{ x: 60, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 32 }}
      >
        <div className="flex items-center gap-3">
          <Mascot width={30} height={36} />
          <p className="flex-1 text-[16px] font-medium">Chat with Warden</p>
          <button type="button" onClick={onClose} aria-label="Close" className="flex size-9 cursor-pointer items-center justify-center rounded-full text-ink/60 hover:bg-white/70 hover:text-ink">
            <X size={18} />
          </button>
        </div>
        <div className="mt-2 flex min-h-0 flex-1 flex-col">{children}</div>
      </motion.div>
    </motion.div>
  );
}

/** The conversation: history that fills the space, suggestions, and the message box or call bar. */
function ChatPane({
  chat, busy, canReply, closed, onAsk, onSend, onUpload, onClearChat, callContext, onCallLine, onAnswer, onExpand, roomy = false,
}: Props & { onExpand?: () => void; roomy?: boolean }) {
  const [text, setText] = useState("");
  const [inCall, setInCall] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLDivElement>(null);

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

  const bubble = roomy ? "text-[14px] px-3.5 py-2.5" : "text-[12.5px] px-3 py-2";
  const inputId = roomy ? "drawer-input" : "rail-input";

  return (
    <div className="rail-grow flex min-h-0 flex-1 flex-col">
      <div className="mt-2.5 flex items-center justify-between px-1 text-[12px]">
        <span className="font-medium text-ink/70">Chat{chat.length ? ` · ${chat.length}` : ""}</span>
        <span className="flex items-center gap-3">
          {onClearChat && chat.length > 0 && (
            <button type="button" onClick={onClearChat} className="cursor-pointer text-ink/50 hover:text-ink">Clear</button>
          )}
          {onExpand && (
            <button
              type="button"
              onClick={onExpand}
              disabled={inCall}
              aria-label="Expand chat"
              title="Expand chat"
              className="flex size-7 cursor-pointer items-center justify-center rounded-full text-ink/55 hover:bg-white/70 hover:text-teal disabled:opacity-40"
            >
              <Maximize2 size={14} />
            </button>
          )}
        </span>
      </div>

      <div
        ref={log}
        className="mt-1 flex min-h-[120px] flex-1 flex-col gap-2 overflow-y-auto px-1 pt-3 [mask-image:linear-gradient(to_bottom,transparent,black_24px)]"
        aria-live="polite"
      >
        {chat.length === 0 ? (
          <div className="m-auto flex flex-col items-center px-6 text-center">
            <motion.div className="mb-2" animate={{ y: [0, -4, 0] }} transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}>
              <Mascot width={36} height={43} />
            </motion.div>
            <p className="text-[14px] font-medium text-ink/80">Ask me anything about this home</p>
            <p className="mt-1 text-[12.5px] leading-[1.45] text-ink/55">Alternatively, hop on a call!</p>
          </div>
        ) : (
          chat.map((m, i) => (
            <motion.div
              key={`${m.at}-${i}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className={m.role === "student" ? `max-w-[85%] self-end rounded-[16px] rounded-br-[6px] bg-teal leading-[1.45] text-white ${bubble}` : "flex max-w-[92%] items-start gap-1.5 self-start"}
            >
              {m.role === "student" ? (
                m.text
              ) : (
                <>
                  <Mascot width={20} height={24} className="mt-1" />
                  <span className={`rounded-[16px] rounded-tl-[6px] bg-white leading-[1.5] ${bubble}`}>{m.text}</span>
                </>
              )}
            </motion.div>
          ))
        )}
      </div>

      {inCall && callContext ? (
        <CaseCall context={callContext} onLine={(role, t) => onCallLine?.(role, t)} onAnswer={onAnswer} onEnd={() => setInCall(false)} />
      ) : (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5 px-1">
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

          <form onSubmit={submit} className="relative mt-3 h-[92px] shrink-0 rounded-[20px] bg-white shadow-card transition focus-within:ring-4 focus-within:ring-aqua/20">
            <label htmlFor={inputId} className="sr-only">Message Warden</label>
            <input
              id={inputId}
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
            {callContext && (
              <motion.button
                type="button"
                onClick={() => setInCall(true)}
                aria-label="Call Warden about this home"
                title="Call Warden"
                whileHover={{ scale: 1.06 }}
                whileTap={{ scale: 0.92 }}
                className="absolute right-[64px] top-[46px] flex size-[38px] cursor-pointer items-center justify-center rounded-full bg-mint text-teal transition hover:bg-[#d3eff1]"
              >
                <Phone size={16} />
              </motion.button>
            )}
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
        </>
      )}
    </div>
  );
}

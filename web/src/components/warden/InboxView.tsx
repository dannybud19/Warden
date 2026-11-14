"use client";

import Image from "next/image";
import Link from "next/link";
import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AGENT_PROFILE, shortWhen, useWardenData, type Activity } from "@/lib/activity";
import { useLocalJSON } from "@/lib/localStore";
import { AnimatedWarden } from "./AnimatedWarden";
import { PageShell } from "./PageShell";

interface Message {
  id: string;
  title: string;
  body: string;
  kind: "question" | "flag" | "good" | "verdict";
  item: Activity;
}

const KIND = {
  question: { label: "Needs you", cls: "bg-[#fcebe7] text-[#9a3a27]" },
  flag: { label: "Red flag", cls: "bg-[#fbf2df] text-[#7a5410]" },
  good: { label: "Looks fine", cls: "bg-[#e0f4ec] text-[#1f6e58]" },
  verdict: { label: "Verdict", cls: "bg-mint text-[#0f6d74]" },
} as const;

function toMessages(items: Activity[]): Message[] {
  const out: Message[] = [];
  for (const i of items) {
    const name = AGENT_PROFILE[i.agent]?.name ?? i.agent;
    if (i.status === "needs_you") out.push({ id: i.id, kind: "question", title: "Warden has a question for you", body: i.line, item: i });
    else if (i.status !== "done") continue;
    else if (i.agent === "warden") out.push({ id: i.id, kind: "verdict", title: "Warden made a call", body: i.line, item: i });
    else if (i.tone === "red" || i.tone === "amber") out.push({ id: i.id, kind: "flag", title: `${name} found a red flag`, body: i.line, item: i });
    else if (i.tone === "green") out.push({ id: i.id, kind: "good", title: `${name} checked something`, body: i.line, item: i });
  }
  return out.sort((a, b) => Number(b.kind === "question") - Number(a.kind === "question") || b.item.at.localeCompare(a.item.at));
}

export function InboxView() {
  const { items, loading } = useWardenData();
  const [read, setRead] = useLocalJSON<string[]>("warden.inbox.read", []);
  const [tab, setTab] = useState<"all" | "unread">("all");
  const messages = useMemo(() => toMessages(items), [items]);
  const readSet = new Set(read);
  const unread = messages.filter((m) => !readSet.has(m.id));
  const shown = tab === "all" ? messages : unread;

  const markRead = (id: string) => !readSet.has(id) && setRead([...read, id]);

  return (
    <PageShell active="Inbox">
      <main className="mx-auto mt-10 max-w-[760px]">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-[32px] font-light tracking-[-0.03em]">Inbox</h1>
            <AnimatePresence mode="wait" initial={false}>
              <motion.p key={unread.length} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} className="text-[13.5px] text-muted">
                {unread.length ? `${unread.length} unread` : "You're all caught up"}
              </motion.p>
            </AnimatePresence>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={!unread.length}
              onClick={() => setRead([...new Set([...read, ...messages.map((m) => m.id)])])}
              className="cursor-pointer text-[13px] font-medium text-teal disabled:cursor-default disabled:opacity-40"
            >
              Mark all read
            </button>
            <div role="tablist" aria-label="Filter" className="liquid-glass relative flex rounded-full p-1">
              {(["all", "unread"] as const).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  type="button"
                  onClick={() => setTab(t)}
                  className="relative cursor-pointer rounded-full px-4 py-1.5 text-[13px] font-medium"
                >
                  {tab === t && <motion.span layoutId="inbox-tab" className="absolute inset-0 rounded-full bg-teal shadow-tab" transition={{ type: "spring", stiffness: 380, damping: 32 }} />}
                  <span className={`relative ${tab === t ? "text-white" : "text-ink/70"}`}>{t === "all" ? "All" : "Unread"}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-5 overflow-hidden rounded-[24px] border border-white bg-white/85 shadow-card backdrop-blur-[15px]">
          {loading ? (
            <div className="flex flex-col gap-px">
              {[0, 1, 2, 3].map((i) => (
                <motion.div key={i} className="h-[76px] bg-field" animate={{ opacity: [0.4, 1, 0.4] }} transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.12 }} />
              ))}
            </div>
          ) : shown.length === 0 ? (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col items-center px-6 pb-10 pt-6 text-center">
              <AnimatedWarden state="green" width={170} />
              <p className="-mt-2 text-[22px] font-light tracking-[-0.03em]">Nothing new here</p>
              <p className="mt-1 text-[13.5px] text-muted">Warden will drop a note in here the moment an agent finds something.</p>
            </motion.div>
          ) : (
            <ul>
              <AnimatePresence initial={false} mode="popLayout">
                {shown.map((m, i) => {
                  const isUnread = !readSet.has(m.id);
                  const icon = AGENT_PROFILE[m.item.agent]?.icon ?? "/warden/mascot.png";
                  return (
                    <motion.li
                      key={m.id}
                      layout
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i, 10) * 0.035 } }}
                      exit={{ opacity: 0, x: -24, transition: { duration: 0.18 } }}
                      className={i ? "border-t border-line" : ""}
                    >
                      <Link
                        href={m.item.home.href}
                        onClick={() => markRead(m.id)}
                        className="group relative flex items-center gap-4 px-5 py-4 transition-colors hover:bg-field"
                      >
                        <span className="relative size-11 shrink-0 rounded-[14px] bg-mint/70">
                          <Image src={icon} alt="" fill sizes="44px" className="object-contain p-0.5 transition-transform group-hover:scale-110" />
                          <AnimatePresence>
                            {isUnread && (
                              <motion.span
                                initial={{ scale: 0 }}
                                animate={{ scale: 1 }}
                                exit={{ scale: 0 }}
                                className="absolute -right-1 -top-1 size-3 rounded-full border-2 border-white bg-teal"
                              />
                            )}
                          </AnimatePresence>
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className={`truncate text-[14.5px] ${isUnread ? "font-semibold" : "font-medium text-ink/80"}`}>{m.title}</span>
                            <span className={`shrink-0 rounded-full px-2 py-[2px] text-[11px] font-medium ${KIND[m.kind].cls}`}>{KIND[m.kind].label}</span>
                          </span>
                          <span className="mt-0.5 block truncate text-[13.5px] text-ink/70">{m.body}</span>
                          <span className="mt-1 flex items-center gap-1.5 text-[12px] text-muted">
                            <span className="relative size-4 overflow-hidden rounded-[4px]">
                              <Image src={m.item.home.photos.front} alt="" fill sizes="16px" className="object-cover" />
                            </span>
                            {m.item.home.title} · {shortWhen(m.item.at)}
                          </span>
                        </span>
                        <span className="text-[14px] text-teal opacity-0 transition-all group-hover:translate-x-1 group-hover:opacity-100">→</span>
                      </Link>
                    </motion.li>
                  );
                })}
              </AnimatePresence>
            </ul>
          )}
        </div>
      </main>
    </PageShell>
  );
}

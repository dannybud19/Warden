"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { useLocalJSON, useLocalString, writeLocal } from "@/lib/localStore";
import { AnimatedWarden } from "./AnimatedWarden";
import { Dot, PillButton, rise, stagger } from "./primitives";

const card = "rounded-[24px] border border-white bg-white/85 p-6 shadow-card backdrop-blur-[15px]";

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full p-1 transition-colors ${on ? "justify-end bg-teal" : "justify-start bg-[#d5e2e4]"}`}
    >
      <motion.span layout transition={{ type: "spring", stiffness: 600, damping: 32 }} className="size-5 rounded-full bg-white shadow-tab" />
    </button>
  );
}

function Field({ id, label, value, placeholder, onSave }: { id: string; label: string; value: string; placeholder: string; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  function save() {
    if (draft === null || draft === value) return setDraft(null);
    onSave(draft);
    setDraft(null);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }
  return (
    <label htmlFor={id} className="block">
      <span className="flex items-center justify-between text-[13px] text-muted">
        {label}
        <AnimatePresence>
          {saved && (
            <motion.span initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="text-[12px] font-medium text-teal">
              ✓ Saved
            </motion.span>
          )}
        </AnimatePresence>
      </span>
      <input
        id={id}
        value={draft ?? value}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
        className="mt-1.5 w-full rounded-[14px] border border-line bg-white px-4 py-2.5 text-[14.5px] outline-none transition placeholder:text-hint focus:border-aqua focus:ring-4 focus:ring-aqua/15"
      />
    </label>
  );
}

const ALERTS = [
  { key: "needsYou", title: "When Warden needs you", body: "A WhatsApp message the moment an agent has a question." },
  { key: "redFlags", title: "New red flags", body: "Hear about a red flag as soon as it's found." },
  { key: "weekly", title: "Weekly summary", body: "One email every Sunday with where each home stands." },
] as const;

type Alerts = Record<(typeof ALERTS)[number]["key"], boolean>;

export function SettingsView() {
  const [name, setName] = useLocalString(STUDENT_NAME_KEY);
  const [uni, setUni] = useLocalString("warden.university");
  const [alerts, setAlerts] = useLocalJSON<Alerts>("warden.alerts", { needsYou: true, redFlags: true, weekly: false });
  const [confirm, setConfirm] = useState(false);
  const [cleared, setCleared] = useState(false);

  function forget() {
    writeLocal("warden.caseIds", null);
    writeLocal("warden.inbox.read", null);
    setConfirm(false);
    setCleared(true);
    setTimeout(() => setCleared(false), 2500);
  }

  return (
    <>
      <motion.main variants={stagger} initial="hidden" animate="show" className="mx-auto mt-10 flex max-w-[760px] flex-col gap-5">
        <motion.div variants={rise} className="flex items-center gap-5">
          <AnimatedWarden state="default" width={110} />
          <div>
            <h1 className="text-[32px] font-light tracking-[-0.03em]">Settings</h1>
            <p className="text-[13.5px] text-muted">How Warden knows you, and how it gets in touch.</p>
          </div>
        </motion.div>

        <motion.section variants={rise} className={card}>
          <h2 className="text-[16px] font-medium">You</h2>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <Field id="set-name" label="First name" value={name} placeholder="So Warden can cheer you on" onSave={setName} />
            <Field id="set-uni" label="University" value={uni} placeholder="e.g. Imperial College London" onSave={setUni} />
          </div>
        </motion.section>

        <motion.section variants={rise} className={card}>
          <h2 className="text-[16px] font-medium">Alerts</h2>
          <ul className="mt-2">
            {ALERTS.map((a, i) => (
              <li key={a.key} className={`flex items-center gap-4 py-3.5 ${i ? "border-t border-line" : ""}`}>
                <div className="min-w-0 flex-1">
                  <p className="text-[14.5px]">{a.title}</p>
                  <p className="text-[12.5px] text-muted">{a.body}</p>
                </div>
                <Toggle label={a.title} on={alerts[a.key]} onChange={(v) => setAlerts({ ...alerts, [a.key]: v })} />
              </li>
            ))}
          </ul>
        </motion.section>

        <motion.section variants={rise} className={card}>
          <h2 className="text-[16px] font-medium">Connections</h2>
          <ul className="mt-2">
            <li className="flex items-center gap-4 py-3.5">
              <div className="min-w-0 flex-1">
                <p className="text-[14.5px]">WhatsApp</p>
                <p className="text-[12.5px] text-muted">Forward chats to Warden and get alerts.</p>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#e0f4ec] px-3 py-1 text-[12px] font-medium text-[#1f6e58]">
                <Dot src="/warden/dot-green.svg" pulse /> Connected
              </span>
            </li>
            <li className="flex items-center gap-4 border-t border-line py-3.5">
              <div className="min-w-0 flex-1">
                <p className="text-[14.5px]">Email</p>
                <p className="text-[12.5px] text-muted">Forward letting-agent emails straight to Warden.</p>
              </div>
              <span className="rounded-full bg-field px-3 py-1 text-[12px] text-muted">Coming soon</span>
            </li>
          </ul>
        </motion.section>

        <motion.section variants={rise} className={card}>
          <h2 className="text-[16px] font-medium">Privacy</h2>
          <div className="mt-3 flex items-center gap-4">
            <p className="min-w-0 flex-1 text-[13.5px] leading-[1.5] text-ink/75">
              Forget the homes saved on this device. Your cases stay with Warden; this only clears this browser&apos;s list.
            </p>
            <AnimatePresence mode="wait" initial={false}>
              {cleared ? (
                <motion.span key="done" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} className="text-[13px] font-medium text-teal">
                  ✓ Cleared
                </motion.span>
              ) : confirm ? (
                <motion.div key="confirm" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="flex gap-2">
                  <PillButton variant="secondary" onClick={() => setConfirm(false)}>Cancel</PillButton>
                  <PillButton onClick={forget} className="border-[#e06a52]! bg-[#e06a52]!">Forget homes</PillButton>
                </motion.div>
              ) : (
                <motion.div key="ask" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <PillButton variant="secondary" onClick={() => setConfirm(true)}>Forget homes…</PillButton>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.section>
      </motion.main>
    </>
  );
}

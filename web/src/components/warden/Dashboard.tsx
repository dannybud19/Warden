"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, useState, useSyncExternalStore } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { Case, CheckId, EvidenceKind } from "@/lib/types";
import type { Mood } from "@/lib/present";
import {
  CHECK_TILE, GO_AHEAD_NEEDS, SETTLE, firstTile, goAheadUnlocked, sourceOf, story, tiles, when,
  type StepTone, type Tile,
} from "@/lib/dashboard";
import { formatRent, shortAddress } from "@/lib/homes";
import { Mascot, PillButton, rise } from "./primitives";
import { ShareButton } from "./FeaturedHome";

const card = "rounded-[22px] border border-white bg-white/85 shadow-card backdrop-blur-[15px]";

export const PILL: Record<Mood["state"], { bg: string; fg: string; dot: string; label: string }> = {
  red: { bg: "#fcebe7", fg: "#9a3a27", dot: "/warden/dot-red.svg", label: "Likely scam · don't pay" },
  stop: { bg: "#fcebe7", fg: "#9a3a27", dot: "/warden/dot-red.svg", label: "Stop · don't pay" },
  amber: { bg: "#fbf2df", fg: "#7a5410", dot: "/warden/dot-amber.svg", label: "Don't pay yet" },
  green: { bg: "#e0f4ec", fg: "#1f6e58", dot: "/warden/dot-green.svg", label: "No red flags so far" },
  thinking: { bg: "#e3f4f5", fg: "#0f6d74", dot: "/warden/dot-teal.svg", label: "Checking" },
  default: { bg: "#e3f4f5", fg: "#0f6d74", dot: "/warden/dot-teal.svg", label: "Waiting for evidence" },
};

// ---- Breadcrumb: back to all homes ----

const MotionLink = motion.create(Link);

/** Glass pill: round back button, "All homes", then this home with its status dot. */
export function Breadcrumb({ title, mood }: { title: string; mood: Mood }) {
  const pill = PILL[mood.state];
  return (
    <motion.nav
      variants={rise}
      aria-label="Breadcrumb"
      className="liquid-glass relative inline-flex items-center gap-1 rounded-full py-1 pl-1 pr-4"
    >
      <span className="liquid-edge" aria-hidden />
      <MotionLink
        href="/"
        initial="rest"
        animate="rest"
        whileHover="hover"
        whileTap={{ scale: 0.96 }}
        className="group flex items-center gap-2 rounded-full py-1 pl-1 pr-3 transition-colors hover:bg-white/70"
      >
        <span className="flex size-8 items-center justify-center rounded-full bg-teal text-white shadow-tab">
          <motion.span variants={{ rest: { x: 0 }, hover: { x: -2 } }} transition={{ type: "spring", stiffness: 400, damping: 20 }}>
            ←
          </motion.span>
        </span>
        <span className="text-[13.5px] font-medium text-ink/80 group-hover:text-teal">All homes</span>
      </MotionLink>
      <span aria-hidden className="text-[13px] text-ink/30">/</span>
      <span className="flex items-center gap-2 pl-2" aria-current="page">
        <Image src={pill.dot} alt="" width={8} height={8} unoptimized />
        <span className="max-w-[320px] truncate text-[13.5px] text-ink/70">{title}</span>
      </span>
    </motion.nav>
  );
}

// ---- Home header (Figma 52:60) ----

export function HomeHeader({ c, photo, mood, caseId }: { c: Case; photo: string | null; mood: Mood; caseId: string }) {
  const outward = c.listing?.postcode?.split(" ")[0];
  const title = [shortAddress(c.listing?.address), outward].filter(Boolean).join(", ");
  const deposit = c.listing?.deposit != null ? `Deposit £${c.listing.deposit.toLocaleString("en-GB")}` : null;
  const meta = [formatRent(c.listing?.rent_pcm), deposit, c.landlord?.company_name ?? c.landlord?.name, c.listing?.platform]
    .filter(Boolean)
    .join(" · ");
  const pill = PILL[mood.state];
  return (
    <motion.header variants={rise} className={`${card} flex items-center gap-5 p-[15px] pr-6`}>
      <div className="relative h-20 w-32 shrink-0 overflow-hidden rounded-[14px] bg-mint">
        {photo ? (
          <Image src={photo} alt="" fill sizes="128px" className="object-cover" priority />
        ) : (
          <div className="flex size-full items-center justify-center"><Mascot width={40} height={48} /></div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[24px] font-light leading-[1.4] tracking-[-0.03em]">{title}</h1>
        <p className="truncate text-[13px] leading-[1.4] text-muted">{meta || "Details still to come"}</p>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={pill.label}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="mt-1.5 inline-flex items-center gap-[7px] rounded-full py-1 pl-2.5 pr-[11px] text-[12px] font-medium"
            style={{ background: pill.bg, color: pill.fg }}
          >
            <Image src={pill.dot} alt="" width={8} height={8} unoptimized />
            {pill.label}
          </motion.span>
        </AnimatePresence>
      </div>
      <ShareButton href={`/case/${caseId}`} label="Share recap" />
    </motion.header>
  );
}

// ---- The answer: verdict + one recommended move ----

const DECISION_KEY = (id: string) => `warden.decision.${id}`;
const listeners = new Set<() => void>();
function readDecision(id: string): string {
  try {
    return localStorage.getItem(DECISION_KEY(id)) ?? "";
  } catch {
    return "";
  }
}
export function writeDecision(id: string, v: string) {
  try {
    if (v) localStorage.setItem(DECISION_KEY(id), v);
    else localStorage.removeItem(DECISION_KEY(id));
  } catch {
    /* storage unavailable */
  }
  listeners.forEach((l) => l());
}
export function useDecision(id: string): string {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => readDecision(id),
    () => "",
  );
}

export const REPORT_URL = "https://www.actionfraud.police.uk/reporting-fraud-and-cyber-crime";

export function AnswerCard({ c, mood, caseId }: { c: Case; mood: Mood; caseId: string }) {
  const decision = useDecision(caseId);
  const unlocked = goAheadUnlocked(c);
  const danger = mood.state === "red" || mood.state === "stop";
  const advice = danger
    ? "Warden recommends walking away."
    : unlocked
      ? "The key checks are clear. Go ahead carefully."
      : "Don't pay until the open checks are cleared.";

  return (
    <motion.section variants={rise} className={`${card} relative overflow-hidden`}>
      <div className="flex items-start gap-5 px-6 pb-5 pt-5">
        <motion.div
          className="relative -ml-1 size-[84px] shrink-0"
          animate={{ y: [0, -4, 0], rotate: [0, -3, 0] }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
        >
          <Image src={danger ? "/warden/obj-magnifier.png" : "/warden/obj-shield.png"} alt="" fill sizes="84px" className="object-contain" />
        </motion.div>
        <div className="min-w-0 flex-1 pt-1">
          <p className="text-[13px] text-muted">Verdict</p>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={mood.title} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
              <h2 className="text-[26px] font-light leading-[1.25] tracking-[-0.03em]">{mood.title}</h2>
              <p className="mt-1 text-[14px] leading-[1.45] text-ink/70">{mood.sub}</p>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      <div className="border-t border-line bg-white/60 px-6 py-4">
        <AnimatePresence mode="wait" initial={false}>
          {decision ? (
            <motion.div
              key="decided"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex items-center gap-4"
            >
              <p className="flex-1 text-[14px]">
                {decision === "walked"
                  ? "You walked away from this home. Good call: Warden will stop nudging you about it."
                  : "You're going ahead. See it in person, sign before paying, and check the deposit is protected."}
              </p>
              <PillButton variant="secondary" onClick={() => writeDecision(caseId, "")}>Undo</PillButton>
            </motion.div>
          ) : (
            <motion.div
              key="choose"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex flex-wrap items-center gap-x-4 gap-y-3"
            >
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-medium">What do you want to do?</p>
                <p className="text-[13px] text-muted">{advice}</p>
              </div>
              <div className="flex items-center gap-2">
                <PillButton variant={danger ? "primary" : "secondary"} onClick={() => writeDecision(caseId, "walked")}>
                  Walk away
                </PillButton>
                <motion.a
                  href={REPORT_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  whileHover={{ y: -1 }}
                  whileTap={{ scale: 0.96 }}
                  className="rounded-full bg-[#fcebe7] px-[18px] py-[10px] text-[13px] font-medium leading-[normal] text-[#b24a35]"
                >
                  Report scam
                </motion.a>
                <span className="group relative">
                  <PillButton
                    variant={unlocked && !danger ? "primary" : "secondary"}
                    disabled={!unlocked}
                    onClick={() => writeDecision(caseId, "ahead")}
                    aria-describedby="go-ahead-why"
                  >
                    {!unlocked && <span aria-hidden>🔒</span>} Go ahead
                  </PillButton>
                  {!unlocked && (
                    <span
                      id="go-ahead-why"
                      role="tooltip"
                      className="pointer-events-none absolute bottom-full right-0 mb-2 w-[230px] rounded-[12px] bg-ink px-3 py-2 text-[12px] leading-[1.4] text-white opacity-0 shadow-glass transition-opacity group-hover:opacity-100"
                    >
                      Unlocks when {GO_AHEAD_NEEDS.map((id) => CHECK_TILE[id]).join(", ").replace(/, ([^,]*)$/, " and $1")} are verified.
                    </span>
                  )}
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.section>
  );
}

// ---- Check map: 8 tiles, one detail at a time ----

const TILE_LOOK: Record<string, { tile: string; badge: string; glyph: string; word: string }> = {
  suspicious: { tile: "bg-[#fdf1ee] border-[#f6d5cc]", badge: "bg-[#fcebe7] text-[#c4513b]", glyph: "!", word: "Red flag" },
  cleared: { tile: "bg-[#eef8f3] border-[#cfeadd]", badge: "bg-[#d6efe4] text-[#1f7a60]", glyph: "✓", word: "Verified" },
  unverified: { tile: "bg-white/60 border-dashed border-[#c9dcdf]", badge: "bg-[#eef3f4] text-muted", glyph: "?", word: "Not proven yet" },
};

export function CheckMap({
  c, disabled, onUpload,
}: { c: Case; disabled: boolean; onUpload: (kind: EvidenceKind, file: File) => void }) {
  const ts = tiles(c);
  const [picked, setPicked] = useState<CheckId | null>(null);
  const selectedId = picked ?? firstTile(ts);
  const t = ts.find((x) => x.id === selectedId) ?? ts[0];
  const counts = {
    suspicious: ts.filter((x) => x.state === "suspicious").length,
    cleared: ts.filter((x) => x.state === "cleared").length,
    unverified: ts.filter((x) => x.state === "unverified").length,
  };

  return (
    <motion.section variants={rise} className={`${card} relative overflow-hidden px-6 pb-6 pt-5`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[13px] text-muted">What&apos;s checked</p>
          <p className="mt-0.5 text-[15px]">
            <span className="text-[26px] font-light tracking-[-0.03em]">{counts.suspicious + counts.cleared} of 8</span>
            <span className="ml-2 text-muted">checked</span>
          </p>
          <p className="mt-1 flex flex-wrap gap-x-3 text-[12.5px] text-muted">
            <span><b className="font-medium text-[#c4513b]">{counts.suspicious}</b> red flag{counts.suspicious === 1 ? "" : "s"}</span>
            <span><b className="font-medium text-[#1f7a60]">{counts.cleared}</b> verified</span>
            <span><b className="font-medium text-ink/70">{counts.unverified}</b> not proven yet</span>
          </p>
        </div>
        <motion.div
          className="relative -mr-2 -mt-2 size-[76px] shrink-0"
          animate={{ y: [0, -3, 0], rotate: [0, 2, 0] }}
          transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
        >
          <Image src="/warden/obj-clipboard.png" alt="" fill sizes="76px" className="object-contain" />
        </motion.div>
      </div>

      <div role="tablist" aria-label="Checks" className="mt-4 grid grid-cols-8 gap-2">
        {ts.map((x, i) => {
          const look = TILE_LOOK[x.state];
          const on = x.id === t.id;
          return (
            <motion.button
              key={x.id}
              role="tab"
              aria-selected={on}
              aria-controls="check-detail"
              type="button"
              onClick={() => setPicked(x.id)}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 + i * 0.04 }}
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.97 }}
              className={`relative flex h-[88px] cursor-pointer flex-col justify-between rounded-[16px] border p-2.5 text-left ${look.tile}`}
            >
              <span className={`flex size-6 items-center justify-center rounded-full text-[12px] font-semibold ${look.badge}`}>{look.glyph}</span>
              <span className="text-[12px] font-medium leading-[1.25] text-ink/85">{x.label}</span>
              {on && (
                <motion.span
                  layoutId="tile-ring"
                  className="pointer-events-none absolute -inset-[3px] rounded-[18px] border-2 border-teal"
                  transition={{ type: "spring", stiffness: 420, damping: 32 }}
                />
              )}
            </motion.button>
          );
        })}
      </div>

      <div id="check-detail" role="tabpanel" className="mt-4 overflow-hidden rounded-[18px] bg-field">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22 }}
            className="p-5"
          >
            <TileDetail t={t} disabled={disabled} onUpload={onUpload} />
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.section>
  );
}

function TileDetail({ t, disabled, onUpload }: { t: Tile; disabled: boolean; onUpload: (kind: EvidenceKind, file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const look = TILE_LOOK[t.state];
  const settle = SETTLE[t.id];
  const shown = t.findings.filter((f) => (t.state === "cleared" ? f.supports === "cleared" : true)).slice(0, 2);
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className={`rounded-full px-2.5 py-[3px] text-[11.5px] font-medium ${look.badge}`}>{look.word}</span>
        <span className="text-[13px] text-muted">{t.label}</span>
      </div>

      {shown.length > 0 && (
        <ul className="mt-3 flex flex-col gap-3">
          {shown.map((f) => {
            const quote = f.evidence?.[0]?.quote;
            return (
              <li key={f.id}>
                <p className="text-[16px] font-medium leading-[1.35]">{f.title}</p>
                <p className="mt-0.5 text-[12.5px] text-muted">{sourceOf(f)}</p>
                {quote && (
                  <blockquote className="mt-2 border-l-2 border-aqua pl-3 text-[13.5px] italic leading-[1.5] text-ink/75">
                    “{quote}”
                  </blockquote>
                )}
                {!quote && f.detail && <p className="mt-1.5 text-[13.5px] leading-[1.5] text-ink/75">{f.detail}</p>}
              </li>
            );
          })}
        </ul>
      )}

      {t.state !== "cleared" && (
        <div className={`flex flex-wrap items-center gap-3 ${shown.length ? "mt-4 border-t border-line pt-4" : "mt-3"}`}>
          <p className="min-w-0 flex-1 text-[13.5px] leading-[1.5]">
            <span className="font-medium">{t.state === "suspicious" ? "What would settle it: " : "To prove it: "}</span>
            {settle.text}
          </p>
          {settle.upload && (
            <>
              <PillButton variant="secondary" disabled={disabled} onClick={() => input.current?.click()}>
                {settle.upload.label}
              </PillButton>
              <input
                ref={input}
                type="file"
                accept={settle.upload.accept}
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file && settle.upload) onUpload(settle.upload.kind, file);
                  e.target.value = "";
                }}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---- Story strip: how the verdict moved ----

const TONE: Record<StepTone, { dot: string; pill: string }> = {
  red: { dot: "bg-flag-red", pill: "bg-[#fcebe7] text-[#9a3a27]" },
  amber: { dot: "bg-flag-amber", pill: "bg-[#fbf2df] text-[#7a5410]" },
  green: { dot: "bg-flag-green", pill: "bg-[#e0f4ec] text-[#1f6e58]" },
  grey: { dot: "bg-[#b9c7ca]", pill: "bg-[#eef3f4] text-muted" },
  next: { dot: "border-2 border-dashed border-[#9db0b4] bg-white", pill: "border border-dashed border-[#c9dcdf] text-muted" },
};

export function StoryStrip({ c }: { c: Case }) {
  const steps = story(c);
  return (
    <motion.section variants={rise} className={`${card} px-6 pb-5 pt-5`}>
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-muted">How it&apos;s changed</p>
        <p className="text-[12px] text-muted">{(c.evidence ?? []).length} thing{(c.evidence ?? []).length === 1 ? "" : "s"} you sent</p>
      </div>
      <ol className="relative mt-4 grid" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((s, i) => (
          <motion.li
            key={s.key}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + i * 0.08 }}
            className="relative pr-3"
          >
            <div className="flex items-center">
              <span className={`relative z-10 size-3 shrink-0 rounded-full ${TONE[s.tone].dot}`} />
              {i < steps.length - 1 && (
                <motion.span
                  className={`ml-1 h-px flex-1 origin-left ${steps[i + 1].tone === "next" ? "border-t border-dashed border-[#b9c7ca]" : "bg-[#c9dcdf]"}`}
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ delay: 0.3 + i * 0.1, duration: 0.4 }}
                />
              )}
            </div>
            <p className="mt-2 text-[11px] text-muted">{when(s.at)}</p>
            <p className="mt-0.5 line-clamp-2 text-[13.5px] font-medium leading-[1.35]">{s.title}</p>
            <span className={`mt-1.5 inline-block rounded-full px-2.5 py-[3px] text-[11.5px] font-medium ${TONE[s.tone].pill}`}>{s.result}</span>
          </motion.li>
        ))}
      </ol>
    </motion.section>
  );
}

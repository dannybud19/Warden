"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AnimatePresence, animate, motion, useMotionValue, useTransform } from "motion/react";
import {
  Banknote, Building2, Check, ChevronLeft, ChevronRight, Copy, FileText, Globe, HelpCircle, KeyRound,
  PoundSterling, Share, Trash2, ShieldCheck, Sparkles, Timer, Upload, Video, type LucideIcon,
} from "lucide-react";
import { Cell, Pie, PieChart, PolarAngleAxis, RadialBar, RadialBarChart, Tooltip } from "recharts";
import type { Case, CheckId, EvidenceKind, Finding } from "@/lib/types";
import type { Mood } from "@/lib/present";
import { CHECK_TILE, SETTLE, sourceOf, tiles } from "@/lib/dashboard";
import { currentScore, detailText, sourceUrls } from "@/lib/selectors";
import { forgetCase, formatRent, shortAddress } from "@/lib/homes";
import { useRouter } from "next/navigation";
import { Mascot, SourceLinks, rise } from "./primitives";
import { PILL } from "./Dashboard";

const RED = "#e06a52";
const AMBER = "#d99a2b";
const GREEN = "#2e9a7c";
const TEAL = "#138a93";
const TRACK = "#e6eef0";

const card = "rounded-[24px] border border-white bg-white/90 shadow-card backdrop-blur-[15px]";

const CHECK_ICON: Record<CheckId, LucideIcon> = {
  landlord_identity: Building2,
  payment_safety: Banknote,
  right_to_let: KeyRound,
  in_person_viewing: Globe,
  contract_consistency: FileText,
  deposit_protection: ShieldCheck,
  no_pressure: Timer,
  fair_price: PoundSterling,
};

const UPLOAD_TITLE: Partial<Record<EvidenceKind, string>> = {
  video: "Viewing video",
  contract: "Tenancy agreement",
  chat_export: "Your chats",
  listing: "Listing link",
};

// ---- small client-only clock for "Updated 3 min ago" ----

function subscribeMinute(cb: () => void) {
  const id = window.setInterval(cb, 30_000);
  return () => window.clearInterval(id);
}
let minute = 0;
function nowSnapshot() {
  const m = Math.floor(Date.now() / 30_000);
  if (m !== minute) minute = m;
  return minute;
}
function ago(iso: string | undefined, tick: number | null): string | null {
  if (!iso || tick === null) return null;
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

// ---- risk level from the case ----

interface Risk {
  label: string;
  color: string;
  value: number;
  headline: string;
  sub: string;
  danger: boolean;
}

function riskOf(c: Case, mood: Mood, flags: number): Risk {
  const score = Math.round(currentScore(c));
  const plural = `${flags} red flag${flags === 1 ? "" : "s"}`;
  if (mood.state === "thinking") {
    return { label: "Checking", color: TEAL, value: score, headline: "Warden is checking…", sub: "This usually takes under a minute.", danger: false };
  }
  if (mood.state === "red" || mood.state === "stop") {
    return {
      label: "High risk", color: RED, value: Math.max(score, 80), headline: "Don't pay. Walk away from this one.",
      sub: flags > 1 ? "Any one of these flags is reason enough to stop." : "This flag alone is reason enough to stop.", danger: true,
    };
  }
  if (mood.state === "amber" || flags) {
    return { label: "Medium risk", color: AMBER, value: Math.min(Math.max(score, 45), 79), headline: "Don't pay yet.", sub: `${plural} to clear up first. Settle the open checks below.`, danger: false };
  }
  if (mood.state === "green") {
    return { label: "Low risk", color: GREEN, value: Math.min(score, 35), headline: "No red flags so far.", sub: "Still see it in person and sign before you pay anything.", danger: false };
  }
  return { label: "Not checked", color: "#9db0b4", value: score, headline: "Forward what they sent you.", sub: "Chats, emails, the listing link or the contract.", danger: false };
}

// ---- Gauge (Recharts radial bar) with an animated count-up ----

function RiskGauge({ risk, flags }: { risk: Risk; flags: number }) {
  const mv = useMotionValue(0);
  const shown = useTransform(mv, (v) => Math.round(v));
  const [n, setN] = useState(0);
  useEffect(() => shown.on("change", setN), [shown]);
  useEffect(() => {
    const ctl = animate(mv, risk.value, { duration: 1.2, ease: [0.22, 1, 0.36, 1] });
    return () => ctl.stop();
  }, [mv, risk.value]);

  return (
    <div className="relative h-[176px] w-[260px] shrink-0" role="img" aria-label={`${risk.label}: risk ${risk.value} out of 100, ${flags} red flags`}>
      <RadialBarChart
        width={260}
        height={260}
        cx={130}
        cy={140}
        innerRadius={96}
        outerRadius={118}
        startAngle={200}
        endAngle={-20}
        barSize={20}
        data={[{ value: risk.value, fill: risk.color }]}
      >
        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} axisLine={false} />
        <RadialBar dataKey="value" cornerRadius={12} background={{ fill: TRACK }} isAnimationActive animationDuration={1200} />
      </RadialBarChart>
      <div className="absolute inset-x-0 top-[84px] text-center">
        <p className="text-[28px] font-medium leading-none tracking-[-0.03em]" style={{ color: risk.color }}>{risk.label}</p>
        <p className="mt-2 text-[13px] text-muted">
          {flags} red flag{flags === 1 ? "" : "s"} · risk <span className="tabular-nums">{n}</span>/100
        </p>
      </div>
    </div>
  );
}

// ---- 1. Header ----

export function RiskHeader({ c, photo, caseId }: { c: Case; photo: string | null; caseId: string }) {
  const outward = c.listing?.postcode?.split(" ")[0];
  const title = [shortAddress(c.listing?.address), outward].filter(Boolean).join(", ");
  const deposit = c.listing?.deposit != null ? `Deposit £${c.listing.deposit.toLocaleString("en-GB")}` : null;
  const meta = [formatRent(c.listing?.rent_pcm), deposit, c.landlord?.company_name ?? c.landlord?.name, c.listing?.platform].filter(Boolean);
  const [copied, setCopied] = useState(false);

  async function share() {
    const url = new URL(`/case/${caseId}`, window.location.origin).toString();
    try {
      if (navigator.share) await navigator.share({ title: "Warden recap", url });
      else await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* dismissed */
    }
  }

  return (
    <motion.header variants={rise} className="flex items-center gap-5">
      <motion.div whileHover={{ scale: 1.04, rotate: -1 }} className="relative size-[92px] shrink-0 overflow-hidden rounded-[20px] bg-mint shadow-photo">
        {photo ? (
          <Image src={photo} alt="" fill sizes="92px" className="object-cover" priority />
        ) : (
          <span className="flex size-full items-center justify-center"><Mascot width={40} height={48} /></span>
        )}
      </motion.div>
      <div className="min-w-0 flex-1">
        <Link href="/" className="group inline-flex items-center gap-0.5 text-[13.5px] text-ink/60 transition-colors hover:text-teal">
          <ChevronLeft size={16} className="transition-transform group-hover:-translate-x-0.5" /> All homes
        </Link>
        <h1 className="truncate text-[30px] font-medium leading-[1.2] tracking-[-0.03em]">{title}</h1>
        <p className="mt-1 truncate text-[14.5px] text-ink/65">{meta.join("  ·  ") || "Details still to come"}</p>
      </div>
      <RemoveHome caseId={caseId} />
      <motion.button
        type="button"
        onClick={share}
        whileHover={{ y: -1 }}
        whileTap={{ scale: 0.96 }}
        className="flex shrink-0 cursor-pointer items-center gap-2 rounded-full border border-line bg-white px-4 py-2.5 text-[14px] font-medium shadow-tab"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span key={copied ? "c" : "s"} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="flex items-center gap-2">
            {copied ? <Check size={17} /> : <Share size={17} />} {copied ? "Link copied" : "Share recap"}
          </motion.span>
        </AnimatePresence>
      </motion.button>
    </motion.header>
  );
}

// ---- quiet "remove this home" bin, with a small confirm ----

function RemoveHome({ caseId }: { caseId: string }) {
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setConfirm((v) => !v)}
        aria-label="Remove this home"
        title="Remove this home"
        className="flex size-10 cursor-pointer items-center justify-center rounded-full text-ink/40 transition-colors hover:bg-white/80 hover:text-[#c4513b]"
      >
        <Trash2 size={18} />
      </button>
      <AnimatePresence>
        {confirm && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-12 z-30 w-[230px] rounded-[16px] border border-line bg-white p-4 shadow-glass"
          >
            <p className="text-[14px] font-medium">Remove this home?</p>
            <p className="mt-1 text-[12.5px] leading-[1.4] text-muted">It disappears from your dashboard and inbox.</p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() => {
                  forgetCase(caseId);
                  router.push("/");
                }}
                className="cursor-pointer rounded-full bg-[#e06a52] px-3.5 py-1.5 text-[13px] font-medium text-white"
              >
                Remove
              </button>
              <button type="button" onClick={() => setConfirm(false)} className="cursor-pointer rounded-full px-3 py-1.5 text-[13px] text-ink/60 hover:text-ink">
                Cancel
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---- 2. Verdict card: gauge + headline + decision ----

export function VerdictCard({ c, mood, flags }: { c: Case; mood: Mood; flags: number }) {
  const risk = riskOf(c, mood, flags);
  const pill = PILL[mood.state];
  const tick = useSyncExternalStore(subscribeMinute, nowSnapshot, () => null);
  const history = c.score_history ?? [];
  const updated = ago(history[history.length - 1]?.at ?? c.created_at, tick);

  return (
    <motion.section variants={rise} className={`${card} flex items-center gap-8 px-8 py-7`}>
      <RiskGauge risk={risk} flags={flags} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium" style={{ background: pill.bg, color: pill.fg }}>
            <span className="size-1.5 rounded-full" style={{ background: risk.color }} />
            {pill.label.split(" · ")[0]}
          </span>
          {updated && <span className="text-[13.5px] text-muted">Updated {updated}</span>}
        </div>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={risk.headline} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
            <h2 className="mt-3 text-[32px] font-semibold leading-[1.15] tracking-[-0.03em]">{risk.headline}</h2>
            <p className="mt-2.5 text-[16px] text-ink/70">{risk.sub}</p>
          </motion.div>
        </AnimatePresence>

      </div>
    </motion.section>
  );
}

// ---- 3. Why Warden thinks so: flag cards ----

function FlagCard({ f, i, c }: { f: Finding; i: number; c: Case }) {
  const [open, setOpen] = useState(false);
  const Icon = CHECK_ICON[f.check_id as CheckId] ?? HelpCircle;
  const quote = f.evidence?.[0]?.quote;
  const ev = (c.evidence ?? []).find((e) => e.id === f.evidence?.[0]?.evidence_id);
  const date = ev ? new Date(ev.uploaded_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Europe/London" }) : null;
  const tone = f.severity === "critical" || f.severity === "high" || f.hard_flag ? RED : AMBER;

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15 + i * 0.08, type: "spring", stiffness: 260, damping: 24 }}
      whileHover={{ y: -3 }}
      className={`${card} flex flex-col p-5`}
    >
      <div className="flex items-center justify-between">
        <motion.span
          className="flex size-11 items-center justify-center rounded-[13px]"
          style={{ background: `${tone}1f`, color: tone }}
          whileHover={{ rotate: [0, -10, 8, 0] }}
        >
          <Icon size={22} strokeWidth={1.8} />
        </motion.span>
        <span className="text-[13.5px] font-medium" style={{ color: tone }}>Flag {i + 1}</span>
      </div>
      <p className="mt-4 text-[17px] font-medium leading-[1.4]">{f.title}</p>
      <p className="mt-2 text-[14px] text-muted">{[sourceOf(f), date].filter(Boolean).join(" · ")}</p>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            {quote ? (
              <blockquote className="mt-4 rounded-[14px] border-l-[3px] bg-field px-4 py-3 text-[14px] italic leading-[1.5] text-ink/80" style={{ borderColor: tone }}>
                “{quote}”
              </blockquote>
            ) : (
              <p className="mt-4 rounded-[14px] bg-field px-4 py-3 text-[14px] leading-[1.5] text-ink/80">{detailText(f)}</p>
            )}
            <SourceLinks urls={sourceUrls(f)} className="mt-2" />
          </motion.div>
        )}
      </AnimatePresence>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group mt-auto inline-flex cursor-pointer items-center gap-1 self-start pt-5 text-[15px] font-medium text-[#2f6f73]"
      >
        {open ? "Hide evidence" : "See evidence"}
        <motion.span animate={{ rotate: open ? 90 : 0 }}><ChevronRight size={17} /></motion.span>
      </button>
    </motion.li>
  );
}

export function WhyFlags({ c, flags }: { c: Case; flags: Finding[] }) {
  if (!flags.length) return null;
  const top = flags.slice(0, 3);
  const rest = flags.slice(3);
  return (
    <motion.section variants={rise}>
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="text-[21px] font-semibold tracking-[-0.02em]">Why Warden thinks so</h2>
        <p className="text-[14px] text-muted">Tap a flag for the evidence</p>
      </div>
      <ul className="grid grid-cols-3 gap-4">
        {top.map((f, i) => <FlagCard key={f.id} f={f} i={i} c={c} />)}
      </ul>
      {rest.length > 0 && (
        <p className="mt-3 inline-flex max-w-full items-center gap-2 rounded-full bg-white/70 px-4 py-2 text-[13.5px] text-ink/70">
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-[#fbf2df] text-[11px] font-medium text-[#8a5f12]">+{rest.length}</span>
          <span className="truncate">Smaller worr{rest.length === 1 ? "y" : "ies"}: {rest.map((f) => f.title.toLowerCase()).join("; ")}</span>
        </p>
      )}
    </motion.section>
  );
}

// ---- 4. Settle the open checks (with a breakdown donut) ----

function ChecksDonut({ red, green, open }: { red: number; green: number; open: number }) {
  const data = [
    { name: "Red flags", value: red, fill: RED },
    { name: "Verified", value: green, fill: GREEN },
    { name: "Not proven yet", value: open, fill: TRACK },
  ].filter((d) => d.value > 0);
  return (
    <div className="relative size-[96px] shrink-0">
      <PieChart width={96} height={96}>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={32} outerRadius={46} paddingAngle={4} cornerRadius={4} stroke="none" startAngle={90} endAngle={-270} animationDuration={1000}>
          {data.map((d) => <Cell key={d.name} fill={d.fill} />)}
        </Pie>
        <Tooltip
          cursor={false}
          content={({ active, payload }) =>
            active && payload?.[0] ? (
              <div className="rounded-[10px] bg-ink px-2.5 py-1.5 text-[12px] text-white shadow-glass">
                {payload[0].name}: <b className="font-semibold">{payload[0].value}</b>
              </div>
            ) : null
          }
        />
      </PieChart>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[19px] font-semibold leading-none">{red + green}</span>
        <span className="text-[10.5px] text-muted">of 8</span>
      </div>
    </div>
  );
}

export function SettleChecks({ c, disabled, onUpload }: { c: Case; disabled: boolean; onUpload: (kind: EvidenceKind, file: File) => void }) {
  const ts = tiles(c);
  const red = ts.filter((t) => t.state === "suspicious").length;
  const green = ts.filter((t) => t.state === "cleared").length;
  const open = ts.filter((t) => t.state === "unverified");
  const uploads = open.filter((t) => SETTLE[t.id].upload);
  const input = useRef<HTMLInputElement>(null);
  const pending = useRef<EvidenceKind | null>(null);

  return (
    <motion.section variants={rise} className={`${card} p-7`}>
      <div className="flex items-start gap-5">
        <div className="min-w-0 flex-1">
          <h2 className="text-[20px] font-semibold tracking-[-0.02em]">Settle the open checks</h2>
          <p className="mt-1 text-[14.5px] text-muted">
            {red + green} of 8 checked{uploads.length ? ` · ${uploads.length} upload${uploads.length === 1 ? "" : "s"} would firm up the verdict` : ""}
          </p>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink/70">
            <li className="flex items-center gap-1.5"><span className="flex size-4 items-center justify-center rounded-full text-[10px] font-bold text-white" style={{ background: RED }}>!</span>{red} red flag{red === 1 ? "" : "s"}</li>
            <li className="flex items-center gap-1.5"><span className="flex size-4 items-center justify-center rounded-full text-white" style={{ background: GREEN }}><Check size={10} strokeWidth={3} /></span>{green} verified</li>
            <li className="flex items-center gap-1.5"><span className="flex size-4 items-center justify-center rounded-full border border-[#c9d6d9] text-[10px] font-bold text-muted">?</span>{open.length} not proven yet</li>
          </ul>
        </div>
        <ChecksDonut red={red} green={green} open={open.length} />
      </div>

      {uploads.length > 0 && (
        <ul className="mt-6 grid grid-cols-3 gap-3">
          {uploads.map((t, i) => {
            const up = SETTLE[t.id].upload!;
            const Icon = up.kind === "video" ? Video : up.kind === "contract" || up.kind === "document" ? FileText : Upload;
            const title = up.kind === "document" ? (t.id === "deposit_protection" ? "Deposit certificate" : "Proof they can let it") : UPLOAD_TITLE[up.kind] ?? up.label;
            const addButton = (
            <motion.button
              type="button"
              disabled={disabled}
              aria-label={`Add ${title.toLowerCase()}`}
              onClick={() => {
                pending.current = up.kind;
                if (input.current) {
                  input.current.accept = up.accept;
                  input.current.click();
                }
              }}
              whileHover={{ scale: 1.06 }}
              whileTap={{ scale: 0.92 }}
              className="shrink-0 cursor-pointer rounded-full border border-line bg-white px-3.5 py-1.5 text-[13.5px] font-medium disabled:opacity-50"
            >
              Add
            </motion.button>
            );
            return (
              <motion.li
                key={t.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 + i * 0.06 }}
                whileHover={{ y: -2 }}
                className="flex flex-col gap-3 rounded-[18px] bg-field p-4"
              >
                <span className="flex items-center justify-between">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-[12px] bg-white text-[#2f6f73] shadow-tab"><Icon size={19} strokeWidth={1.8} /></span>
                  {addButton}
                </span>
                <span>
                  <span className="block text-[15px] leading-[1.3]">{title}</span>
                  <span className="mt-0.5 block text-[12.5px] text-muted">Settles: {CHECK_TILE[t.id].toLowerCase()}</span>
                </span>
              </motion.li>
            );
          })}
        </ul>
      )}
      <input
        ref={input}
        type="file"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f && pending.current) onUpload(pending.current, f);
          e.target.value = "";
        }}
      />
    </motion.section>
  );
}

// ---- 5. Still keen? The step that would settle the biggest flag ----

export function StillKeen({ top }: { top: Finding | undefined }) {
  const [copied, setCopied] = useState(false);
  const text = top ? SETTLE[top.check_id as CheckId].text : "See it in person, and never pay anything before you've signed.";
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked */
    }
  }
  return (
    <motion.section variants={rise} className="flex items-center gap-5 rounded-[24px] border border-white bg-[#eaf3f3] px-6 py-5 shadow-card">
      <motion.span
        className="flex size-11 shrink-0 items-center justify-center rounded-full bg-white text-[#2f6f73] shadow-tab"
        animate={{ rotate: [0, 12, -8, 0], scale: [1, 1.08, 1] }}
        transition={{ duration: 3, repeat: Infinity, repeatDelay: 2 }}
      >
        <Sparkles size={20} />
      </motion.span>
      <div className="min-w-0 flex-1">
        <h2 className="text-[17px] font-medium tracking-[-0.02em]">Still keen?</h2>
        <p className="mt-0.5 text-[14.5px] leading-[1.5] text-ink/70">{text}</p>
      </div>
      {top && (
        <motion.button
          type="button"
          onClick={copy}
          whileHover={{ y: -2 }}
          whileTap={{ scale: 0.96 }}
          className="inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-full bg-[#2f6f73] px-5 py-2.5 text-[14.5px] font-medium text-white"
        >
          {copied ? <Check size={17} /> : <Copy size={17} />} {copied ? "Copied" : "Copy message"}
        </motion.button>
      )}
    </motion.section>
  );
}

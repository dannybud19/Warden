"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AnimatePresence, animate, motion, useMotionValue, useTransform } from "motion/react";
import {
  Banknote, Building2, Check, ChevronLeft, ChevronRight, Copy, FileText, Globe, HelpCircle, Info, KeyRound,
  Mail, MessageSquare, Mic, PoundSterling, Share, Trash2, ShieldCheck, Sparkles, Timer, Upload, Video, type LucideIcon,
} from "lucide-react";
import { Cell, Pie, PieChart, Tooltip } from "recharts";
import type { Case, CheckId, EvidenceKind, Finding } from "@/lib/types";
import { riskDisplay, type Mood } from "@/lib/present";
import { SETTLE, sourceOf, tiles } from "@/lib/dashboard";
import { detailText, infoNotes, quoteSource, sourceUrls } from "@/lib/selectors";
import { forgetCase, formatRent, shortAddress } from "@/lib/homes";
import { PAYMENT_NOTE, addedBySlot, type AddSlot } from "@/lib/evidence";
import { useRouter } from "next/navigation";
import { Mascot, SourceLinks, rise } from "./primitives";
import { PILL } from "./Dashboard";

const RED = "#e06a52";
const GREEN = "#2e9a7c";
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

// ---- Gauge: the backend score sets the arc length; the case status sets its colour. ----

const DIAL = { cx: 130, cy: 124, r: 100, width: 22, from: 210, sweep: 240, slices: 120 };
/** Point on the dial for a risk value 0..100 (0 bottom-left, 100 bottom-right). */
function dialPoint(v: number, r = DIAL.r): [number, number] {
  const a = ((DIAL.from - (DIAL.sweep * v) / 100) * Math.PI) / 180;
  return [DIAL.cx + r * Math.cos(a), DIAL.cy - r * Math.sin(a)];
}

function arcPath(v0: number, v1: number): string {
  const [x0, y0] = dialPoint(v0);
  const [x1, y1] = dialPoint(v1);
  return `M ${x0} ${y0} A ${DIAL.r} ${DIAL.r} 0 0 1 ${x1} ${y1}`;
}

// Thin slices keep the existing arc animation while using one status colour.
const SLICES = Array.from({ length: DIAL.slices }, (_, i) => {
  const v0 = (i / DIAL.slices) * 100;
  const v1 = ((i + 1) / DIAL.slices) * 100;
  return { v0, v1, d: arcPath(v0, Math.min(100, v1 + 0.3)) };
});

/** A tapered needle from the hub to just inside the arc. */
function needlePath(v: number): string {
  const [tx, ty] = dialPoint(v, DIAL.r - DIAL.width / 2 - 8);
  const [lx, ly] = dialPoint(v + 25, 5);
  const [rx, ry] = dialPoint(v - 25, 5);
  const [bx, by] = dialPoint(v + 50, 12);
  return `M ${tx} ${ty} L ${lx} ${ly} L ${bx} ${by} L ${rx} ${ry} Z`;
}

function RiskGauge({ risk }: { risk: ReturnType<typeof riskDisplay> }) {
  const mv = useMotionValue(0);
  const needle = useTransform(mv, needlePath);
  const [n, setN] = useState(0);
  useEffect(() => mv.on("change", setN), [mv]);
  useEffect(() => {
    const ctl = animate(mv, risk.value, { duration: 1.4, ease: [0.22, 1, 0.36, 1] });
    return () => ctl.stop();
  }, [mv, risk.value]);

  const [sx, sy] = dialPoint(0);
  const [ex, ey] = dialPoint(Math.max(n, 0.5));
  const [hx, hy] = dialPoint(100);
  return (
    <div className="relative h-[214px] w-[260px] shrink-0" role="img" aria-label={`Risk score: ${risk.value} out of 100. ${risk.headline}`}>
      <svg width={260} height={200} viewBox="0 0 260 200" className="overflow-visible">
        <g>
          {SLICES.map((sl) => (
            <path key={`t${sl.v0}`} d={sl.d} fill="none" stroke={TRACK} strokeWidth={DIAL.width} />
          ))}
          <circle cx={hx} cy={hy} r={DIAL.width / 2} fill={TRACK} />
        </g>
        <circle cx={sx} cy={sy} r={DIAL.width / 2} fill={risk.color} />
        {/* filled up to the score */}
        {SLICES.filter((sl) => sl.v0 < n).map((sl) => (
          <path key={sl.v0} d={sl.v1 > n ? arcPath(sl.v0, n) : sl.d} fill="none" stroke={risk.color} strokeWidth={DIAL.width} />
        ))}
        <circle cx={ex} cy={ey} r={DIAL.width / 2} fill={risk.color} />
        <circle cx={ex} cy={ey} r={5} fill="white" />
        <motion.path d={needle} fill="#17393e" style={{ filter: "drop-shadow(0 2px 3px rgba(16,40,44,.25))" }} />
        <circle cx={DIAL.cx} cy={DIAL.cy} r={9} fill="#17393e" />
        <circle cx={DIAL.cx} cy={DIAL.cy} r={3.5} fill="white" />
      </svg>
      <div className="absolute inset-x-0 top-[142px] text-center">
        <p className="text-[34px] font-semibold leading-none tracking-[-0.04em] tabular-nums" style={{ color: risk.color }}>
          {risk.value}<span className="text-[14px] font-medium text-muted">/100</span>
        </p>
        <p className="mt-1.5 text-[16px] font-medium leading-none" style={{ color: risk.color }}>Risk score</p>
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

export function VerdictCard({ c, mood }: { c: Case; mood: Mood }) {
  const risk = riskDisplay(c, mood);
  const pill = PILL[mood.state];
  const tick = useSyncExternalStore(subscribeMinute, nowSnapshot, () => null);
  const history = c.score_history ?? [];
  const updated = ago(history[history.length - 1]?.at ?? c.created_at, tick);

  return (
    <motion.section variants={rise} className={`${card} flex items-center gap-8 px-8 py-7`}>
      <RiskGauge risk={risk} />
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
        <p className="mt-4 text-[13px] leading-[1.5] text-muted">
          Unverified checks keep this score high. It is not a probability of a scam.
        </p>
      </div>
    </motion.section>
  );
}

// ---- 3. Why Warden thinks so: every issue, one row each, one open at a time ----

function severityOf(f: Finding): { label: string; color: string; bg: string } {
  if (f.supports === "cleared") return { label: "Checks out", color: "#1f7a60", bg: "#e3f4ec" };
  if (f.hard_flag || f.severity === "critical" || f.severity === "high") return { label: "High", color: "#b8432f", bg: "#fcebe7" };
  if (f.severity === "medium") return { label: "Medium", color: "#8a5f12", bg: "#fbf2df" };
  return { label: "Low", color: "#5f6f73", bg: "#eef3f4" };
}

function IssueRow({
  f, c, open, onToggle, disabled, onUpload,
}: {
  f: Finding; c: Case; open: boolean; onToggle: () => void; disabled: boolean;
  onUpload: (kind: EvidenceKind, file: File) => void;
}) {
  const Icon = CHECK_ICON[f.check_id as CheckId] ?? HelpCircle;
  const sev = severityOf(f);
  // every quote the agent cited, each with where it came from (Danny's quoteSource)
  const quotes = (f.evidence ?? []).filter((r) => r.quote);
  const ev = (c.evidence ?? []).find((e) => e.id === f.evidence?.[0]?.evidence_id);
  const date = ev ? new Date(ev.uploaded_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Europe/London" }) : null;
  const cleared = f.supports === "cleared";
  // a clear needs nothing settling
  const settle = cleared ? undefined : SETTLE[f.check_id as CheckId];
  const input = useRef<HTMLInputElement>(null);

  return (
    <li className="border-t border-line first:border-t-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-field/70"
      >
        <span className="flex size-10 shrink-0 items-center justify-center rounded-[12px]" style={{ background: sev.bg, color: sev.color }}>
          {cleared ? <Check size={20} strokeWidth={2.2} /> : <Icon size={20} strokeWidth={1.8} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[16px] font-medium leading-[1.35]">{f.title}</span>
          <span className="mt-0.5 block text-[13px] text-muted">{[sourceOf(f), date].filter(Boolean).join(" · ")}</span>
        </span>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium" style={{ background: sev.bg, color: sev.color }}>
          {cleared && <Check size={12} strokeWidth={2.6} aria-hidden />}
          {sev.label}
        </span>
        <motion.span animate={{ rotate: open ? 90 : 0 }} className="shrink-0 text-ink/40">
          <ChevronRight size={18} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="pb-5 pl-[76px] pr-6">
              {quotes.map((r, k) => (
                <figure key={k} className={k ? "mt-3" : ""}>
                  <blockquote className="rounded-[14px] border-l-[3px] bg-field px-4 py-3 text-[14px] italic leading-[1.5] text-ink/80" style={{ borderColor: sev.color }}>
                    “{r.quote}”
                  </blockquote>
                  <figcaption className="mt-1.5 pl-1 text-[12.5px] leading-[1.4] text-muted">{quoteSource(c, r)}</figcaption>
                </figure>
              ))}
              {(() => {
                // don't repeat the quote if the explanation already includes it
                let d = detailText(f);
                for (const { quote } of quotes) if (quote) d = d.replace(new RegExp(`["“”']?${quote.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["“”']?\\s*`), "").trim();
                return d ? <p className={`text-[14px] leading-[1.55] text-ink/75 ${quotes.length ? "mt-3" : ""}`}>{d}</p> : null;
              })()}
              <SourceLinks urls={sourceUrls(f)} className="mt-2" />
              {settle && (
                <div className="mt-4 flex flex-wrap items-center gap-3 rounded-[14px] bg-mint/50 px-4 py-3">
                  <p className="min-w-0 flex-1 text-[13.5px] leading-[1.5]">
                    <span className="font-medium">What would settle it: </span>
                    {settle.text}
                  </p>
                  {settle.upload && (
                    <>
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => input.current?.click()}
                        className="shrink-0 cursor-pointer rounded-full border border-line bg-white px-3.5 py-1.5 text-[13px] font-medium disabled:opacity-50"
                      >
                        {settle.upload.label}
                      </button>
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
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

export function IssueList({
  c, flags, cleared, disabled, onUpload,
}: {
  c: Case; flags: Finding[]; cleared: Finding[]; disabled: boolean;
  onUpload: (kind: EvidenceKind, file: File) => void;
}) {
  const [openId, setOpenId] = useState<string | null | undefined>(undefined);
  const notes = infoNotes(c);
  if (!flags.length && !cleared.length && !notes.length) return null;
  // the worst issue starts open; after that, one row at a time across both lists
  const current = openId === undefined ? flags[0]?.id : openId;
  const row = (f: Finding) => (
    <IssueRow
      key={f.id}
      f={f}
      c={c}
      open={current === f.id}
      onToggle={() => setOpenId(current === f.id ? null : f.id)}
      disabled={disabled}
      onUpload={onUpload}
    />
  );
  return (
    <motion.section variants={rise}>
      {flags.length > 0 && (
        <>
          <div className="mb-3 flex items-baseline justify-between px-1">
            <h2 className="text-[21px] font-medium tracking-[-0.02em]">
              Why Warden thinks so <span className="text-muted">· {flags.length} issue{flags.length === 1 ? "" : "s"}</span>
            </h2>
            <p className="text-[14px] text-muted">Tap an issue for the evidence</p>
          </div>
          <ul className={`${card} overflow-hidden`}>{flags.map(row)}</ul>
        </>
      )}
      {/* What checked out: same rows, green, so the student sees the proof and its sources too. */}
      {cleared.length > 0 && (
        <>
          <div className={`mb-3 flex items-baseline justify-between px-1 ${flags.length ? "mt-7" : ""}`}>
            <h2 className="text-[21px] font-medium tracking-[-0.02em]">
              What checks out <span className="text-muted">· {cleared.length}</span>
            </h2>
            <p className="text-[14px] text-muted">Good signs, not a guarantee</p>
          </div>
          <ul className="overflow-hidden rounded-[24px] border border-[#cfeadd] bg-[#f6fbf8]/90 shadow-card backdrop-blur-[15px]">
            {cleared.map(row)}
          </ul>
        </>
      )}
      {/* Info notes (e.g. a check that couldn't run) are not flags: one muted line each. */}
      {notes.map((f) => (
        <p key={f.id} className="mt-3 flex items-start gap-2 px-1 text-[13.5px] text-muted">
          <Info size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>{detailText(f) || f.title}</span>
        </p>
      ))}
    </motion.section>
  );
}

// ---- 4. Settle the open checks (with a breakdown donut) ----

function ChecksDonut({ red, green, open, total }: { red: number; green: number; open: number; total: number }) {
  const data = [
    { name: "Look wrong", value: red, fill: RED },
    { name: "Check out", value: green, fill: GREEN },
    { name: "Still to check", value: open, fill: TRACK },
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
        <span className="text-[10.5px] text-muted">of {total}</span>
      </div>
    </div>
  );
}

const KIND_ICON: Partial<Record<EvidenceKind, LucideIcon>> = {
  chat_export: MessageSquare, chat_screenshot: MessageSquare, email: Mail, contract: FileText,
  video: Video, document: FileText, listing: Globe, call_recording: Mic,
};
const KIND_NAME: Record<EvidenceKind, string> = {
  chat_export: "Chats", chat_screenshot: "Chat screenshot", email: "Email", contract: "Contract", video: "Viewing video",
  document: "Document", listing: "Listing", call_recording: "Call recording",
};

/** What the student can always add, whatever state the checks are in. */
const ADDABLE: {
  slot: AddSlot; kind: EvidenceKind; label: string; icon: LucideIcon; accept: string; formats: string; paste?: string; note?: string;
}[] = [
  { slot: "chats", kind: "chat_export", label: "Chats", icon: MessageSquare, accept: ".txt,.zip,image/*", formats: "WhatsApp export (.txt, .zip) or screenshot", paste: "Paste a WhatsApp chat or messages…" },
  { slot: "emails", kind: "email", label: "Emails", icon: Mail, accept: ".eml,.pdf,.txt,image/*", formats: ".eml, PDF, text or screenshot", paste: "Paste the email, including who it's from…" },
  { slot: "contract", kind: "contract", label: "Contract", icon: FileText, accept: ".pdf,.docx,.txt,image/*", formats: "PDF, Word (.docx), text or photo" },
  { slot: "video", kind: "video", label: "Viewing video", icon: Video, accept: "video/*", formats: "Any video (MP4, MOV…)" },
  { slot: "payment", kind: "document", label: "Payment details", icon: Banknote, accept: ".pdf,.docx,.txt,image/*", formats: "PDF, Word, text or photo", note: PAYMENT_NOTE },
  { slot: "other", kind: "document", label: "Other document", icon: Upload, accept: ".pdf,.docx,.txt,image/*", formats: "PDF, Word, text or photo" },
];

export function EvidencePanel({
  c, disabled, onUpload, onPaste,
}: {
  c: Case; disabled: boolean;
  onUpload: (kind: EvidenceKind, file: File, note?: string) => void;
  onPaste: (kind: EvidenceKind, text: string) => void;
}) {
  const ts = tiles(c);
  const total = ts.length;
  const added = addedBySlot(c);
  const red = ts.filter((t) => t.state === "suspicious").length;
  const green = ts.filter((t) => t.state === "cleared").length;
  const open = ts.filter((t) => t.state === "unverified").length;
  const sent = [...(c.evidence ?? [])].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  const input = useRef<HTMLInputElement>(null);
  const pending = useRef<(typeof ADDABLE)[number] | null>(null);
  const [pasting, setPasting] = useState<(typeof ADDABLE)[number] | null>(null);
  const [text, setText] = useState("");

  return (
    <motion.section variants={rise} className={`${card} p-7`}>
      <div className="flex items-start gap-5">
        <div className="min-w-0 flex-1">
          <h2 className="text-[20px] font-medium tracking-[-0.02em]">Your evidence</h2>
          <p className="mt-1 text-[14.5px] text-muted">
            {red + green} of {total} safety checks done · add anything new and the right agents run again
          </p>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink/70">
            <li className="flex items-center gap-1.5"><span className="flex size-4 items-center justify-center rounded-full text-[10px] font-bold text-white" style={{ background: RED }}>!</span>{red} look{red === 1 ? "s" : ""} wrong</li>
            <li className="flex items-center gap-1.5"><span className="flex size-4 items-center justify-center rounded-full text-white" style={{ background: GREEN }}><Check size={10} strokeWidth={3} /></span>{green} check{green === 1 ? "s" : ""} out</li>
            <li className="flex items-center gap-1.5"><span className="flex size-4 items-center justify-center rounded-full border border-[#c9d6d9] text-[10px] font-bold text-muted">?</span>{open} still to check</li>
          </ul>
        </div>
        <ChecksDonut red={red} green={green} open={open} total={total} />
      </div>

      {sent.length > 0 && (
        <ul className="mt-5 flex flex-wrap gap-2">
          {sent.map((e) => {
            const Icon = KIND_ICON[e.kind] ?? FileText;
            return (
              <li key={e.id} className="flex max-w-[260px] items-center gap-2 rounded-full bg-field py-1.5 pl-2 pr-3.5 text-[13px]">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-white text-[#2f6f73]"><Icon size={13} /></span>
                <span className="truncate">{e.filename ?? (e.note === PAYMENT_NOTE ? "Pasted payment details" : `Pasted ${KIND_NAME[e.kind].toLowerCase()}`)}</span>
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-6 text-[13px] font-medium text-ink/70">Add more</p>
      <ul className="mt-2 grid grid-cols-3 gap-3">
        {ADDABLE.map((a, i) => {
          const count = added[a.slot] ?? 0;
          return (
          <motion.li
            key={a.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.04 }}
            whileHover={{ y: -2 }}
            className={`relative flex items-center gap-3 rounded-[16px] p-3 ${count ? "bg-[#e9f6f1] ring-1 ring-[#bfe3d5]" : "bg-field"}`}
          >
            <span className="relative flex size-9 shrink-0 items-center justify-center rounded-[11px] bg-white text-[#2f6f73] shadow-tab">
              <a.icon size={17} strokeWidth={1.8} />
              {count > 0 && (
                <span className="absolute -right-1.5 -top-1.5 flex size-[18px] items-center justify-center rounded-full text-white ring-2 ring-[#e9f6f1]" style={{ background: GREEN }}>
                  <Check size={11} strokeWidth={3} />
                </span>
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14px]">{a.label}</span>
              {count > 0 ? (
                <span className="block truncate text-[11.5px] font-medium text-[#1f7a60]">{count} added</span>
              ) : (
                <span className="block truncate text-[11.5px] text-muted" title={a.formats}>{a.formats}</span>
              )}
            </span>
            {a.paste && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => { setPasting(a); setText(""); }}
                className="shrink-0 cursor-pointer rounded-full px-2 py-1 text-[12px] font-medium text-teal hover:bg-white disabled:opacity-50"
              >
                Paste
              </button>
            )}
            <button
              type="button"
              disabled={disabled}
              aria-label={`${count ? "Add more" : "Upload"} ${a.label.toLowerCase()}`}
              onClick={() => {
                pending.current = a;
                if (input.current) {
                  input.current.accept = a.accept;
                  input.current.click();
                }
              }}
              className="shrink-0 cursor-pointer rounded-full border border-line bg-white px-3 py-1 text-[12.5px] font-medium disabled:opacity-50"
            >
              {count ? "Add more" : "Add"}
            </button>
          </motion.li>
          );
        })}
      </ul>

      <AnimatePresence>
        {pasting && (
          <motion.form
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
            onSubmit={(e) => {
              e.preventDefault();
              if (!text.trim()) return;
              onPaste(pasting.kind, text.trim());
              setPasting(null);
              setText("");
            }}
          >
            <label className="mt-4 block text-[13px] font-medium text-ink/70" htmlFor="paste-evidence">Paste {pasting.label.toLowerCase()}</label>
            <textarea
              id="paste-evidence"
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={pasting.paste}
              rows={5}
              className="mt-2 w-full resize-y rounded-[16px] border border-line bg-white px-4 py-3 text-[14px] outline-none focus:border-aqua focus:ring-4 focus:ring-aqua/15"
            />
            <div className="mt-2 flex gap-2">
              <button type="submit" disabled={!text.trim() || disabled} className="cursor-pointer rounded-full bg-teal px-4 py-2 text-[13.5px] font-medium text-white disabled:opacity-50">
                Send to Warden
              </button>
              <button type="button" onClick={() => setPasting(null)} className="cursor-pointer rounded-full px-3 py-2 text-[13.5px] text-ink/60 hover:text-ink">
                Cancel
              </button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>

      <input
        ref={input}
        type="file"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f && pending.current) onUpload(pending.current.kind, f, pending.current.note);
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

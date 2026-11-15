import type { Case, CheckId, EvidenceKind, Finding, AgentUiStatus, Action } from "./types";
import { CHECK_LABELS, CHECK_ORDER } from "./labels";
import { SEVERITY_ORDER, allFindings, currentScore, detailText, isRedFlag, openActions } from "./selectors";

// Plain-language presentation of a case for the hi-fi screens. Pure functions over `Case`.

export interface AgentMeta {
  title: string;
  icon: string;
  /** Shown when the agent has nothing to read yet. */
  missing: string;
  /** Evidence that would let it run, if the student can upload it directly. */
  upload?: { kind: EvidenceKind; label: string; accept: string };
}

export const AGENT_META: Record<string, AgentMeta> = {
  companies_house: {
    title: "Checking the agency is real", icon: "/warden/icon-agency.svg",
    missing: "Add the agency's name to run this",
  },
  message_checker: {
    title: "Reading your chats", icon: "/warden/icon-chat.svg",
    missing: "Forward your chats to run this",
    upload: { kind: "chat_export", label: "Add chats", accept: ".txt,.zip,image/*" },
  },
  emotion_classifier: {
    title: "Spotting pressure", icon: "/warden/icon-shield.svg",
    missing: "Forward your chats to run this",
    upload: { kind: "chat_export", label: "Add chats", accept: ".txt,.zip,image/*" },
  },
  contract_checker: {
    title: "Reading the contract", icon: "/warden/icon-contract.svg",
    missing: "Upload the contract to run this",
    upload: { kind: "contract", label: "Upload contract", accept: ".pdf,.docx,.txt,image/*" },
  },
  video_analysis: {
    title: "Checking the viewing video", icon: "/warden/icon-video.svg",
    missing: "Upload a viewing video to run this",
    upload: { kind: "video", label: "Upload video", accept: "video/*" },
  },
};

export type Tone = "red" | "amber" | "green" | "grey";

export const DOT_7: Record<Tone, string> = {
  red: "/warden/dot-sm-red.svg",
  amber: "/warden/dot-sm-amber.svg",
  green: "/warden/dot-sm-green.svg",
  grey: "/warden/dot-sm-grey.svg",
};

export type ChipKind = "done" | "waiting" | "checking" | "error";

export const CHIP: Record<ChipKind, { label: string; dot: string }> = {
  done: { label: "Done", dot: "/warden/dot-green.svg" },
  waiting: { label: "Waiting", dot: "/warden/dot-grey.svg" },
  checking: { label: "Checking", dot: "/warden/dot-teal.svg" },
  error: { label: "Couldn't run", dot: "/warden/dot-red.svg" },
};

/** Display order on the case screen (the design lists pressure before the contract). */
export const AGENT_DISPLAY_ORDER = [
  "companies_house", "message_checker", "emotion_classifier", "contract_checker", "video_analysis",
] as const;

export interface AgentRow {
  name: string;
  meta: AgentMeta;
  chip: ChipKind;
  line: string;
  tone: Tone;
  muted: boolean;
  showUpload: boolean;
}

function severityRank(f: Finding): number {
  return (f.hard_flag ? -10 : 0) + SEVERITY_ORDER.indexOf(f.severity as (typeof SEVERITY_ORDER)[number]);
}

function toneOf(f: Finding): Tone {
  if (f.supports === "cleared") return "green";
  if (!isRedFlag(f)) return "grey";
  return f.severity === "critical" || f.severity === "high" ? "red" : "amber";
}

export function agentRows(c: Case, live: Record<string, AgentUiStatus>): AgentRow[] {
  return AGENT_DISPLAY_ORDER.map((name) => {
    const meta = AGENT_META[name];
    const report = c.reports?.[name];
    const status: AgentUiStatus = live[name] === "running" ? "running" : (report?.status ?? "idle");
    // Red flags lead, then what checks out; notes that cannot move a check come last.
    const rank = (f: Finding) => (isRedFlag(f) ? 0 : f.supports === "cleared" ? 1 : 2);
    const findings = [...(report?.findings ?? [])].sort((a, b) => {
      return rank(a) - rank(b) || severityRank(a) - severityRank(b);
    });
    const top = findings[0];

    if (status === "running") {
      return { name, meta, chip: "checking", line: "Checking now…", tone: "grey", muted: true, showUpload: false };
    }
    if (status === "ok") {
      return top
        ? { name, meta, chip: "done", line: top.title, tone: toneOf(top), muted: false, showUpload: false }
        : { name, meta, chip: "done", line: "Nothing to flag here", tone: "green", muted: false, showUpload: false };
    }
    if (status === "error") {
      return { name, meta, chip: "error", line: "Couldn't run this time", tone: "grey", muted: true, showUpload: false };
    }
    // The case has what this agent needs but no report yet: it is about to start, not waiting on the student.
    if (!report && hasInputs(c, name)) {
      return { name, meta, chip: "checking", line: "Starting the check…", tone: "grey", muted: true, showUpload: false };
    }
    return { name, meta, chip: "waiting", line: meta.missing, tone: "grey", muted: true, showUpload: !!meta.upload };
  });
}

function hasInputs(c: Case, name: string): boolean {
  if (name === "companies_house") return !!(c.landlord?.company_name || c.landlord?.company_number);
  return false;
}

/** "4 done · 1 waiting · 1 needs you" */
export function agentSummary(rows: AgentRow[], needsYou: number): string {
  const count = (k: ChipKind) => rows.filter((r) => r.chip === k).length;
  return [
    count("done") && `${count("done")} done`,
    count("checking") && `${count("checking")} checking`,
    count("waiting") && `${count("waiting")} waiting`,
    needsYou && `${needsYou} needs you`,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function redFlags(c: Case): Finding[] {
  return allFindings(c)
    .filter(isRedFlag)
    .sort((a, b) => severityRank(a) - severityRank(b));
}

export function progress(c: Case): { checked: number; total: number } {
  const checks = c.checks ?? [];
  return { checked: checks.filter((k) => k.state !== "unverified").length, total: checks.length || 8 };
}

/** Why answering this action helps, in one plain sentence. */
const WHY: Record<CheckId, string> = {
  landlord_identity: "A real letting agency will share it straight away. This would settle the biggest red flag.",
  payment_safety: "Genuine agents never need money before you've seen the place.",
  right_to_let: "Only the owner, or an agent they've authorised, can let the place to you.",
  in_person_viewing: "Seeing it in person is the surest way to know the place and the landlord are real.",
  contract_consistency: "The contract should name the same address, rent and people as the listing.",
  deposit_protection: "Your deposit must go into a government-approved scheme within 30 days.",
  no_pressure: "A fair landlord gives you time to check things. Pressure is a warning sign.",
  fair_price: "A price far below similar places nearby is a common hook.",
};

export function whyAsk(a: Action): string {
  return WHY[a.check_id as CheckId] ?? `This helps verify ${CHECK_LABELS[a.check_id as CheckId] ?? "the home"}.`;
}

// ---- Suggested questions, answered locally from the case (the API has no free Q&A endpoint) ----

export const SUGGESTIONS = ["Why is this a red flag?", "What should I say to them?", "Is my deposit at risk?"] as const;
export type Suggestion = (typeof SUGGESTIONS)[number];

export function answerSuggestion(c: Case, q: Suggestion): string {
  if (q === "Why is this a red flag?") {
    const f = redFlags(c)[0];
    if (!f) return "Nothing is flagged yet. I'll tell you as soon as one of the agents spots something.";
    const quote = f.evidence?.[0]?.quote;
    return `${f.title}. ${detailText(f)}${quote ? ` They wrote: “${quote}”` : ""}`.trim();
  }
  if (q === "What should I say to them?") {
    const a = openActions(c)[0];
    return a
      ? `Try this: “${a.text.replace(/\?$/, "")}?” ${whyAsk(a)}`
      : "There's nothing I need you to ask right now. Don't pay anything until you've seen the place in person.";
  }
  const check = (c.checks ?? []).find((k) => k.id === "deposit_protection");
  if (check?.state === "cleared") return "Your deposit looks protected: Warden found it in a government-approved scheme.";
  if (check?.state === "suspicious") {
    return `Yes, it may be. ${check.reason ?? "Something about the deposit doesn't add up."} Don't pay it until this is cleared.`;
  }
  return "I can't tell yet. Ask which government-approved scheme the deposit goes into (DPS, mydeposits or TDS), and don't pay it before you've seen the place.";
}

// ---- Mood: the mascot state + headline for the case screen ----

export type MoodState = "default" | "thinking" | "green" | "amber" | "red" | "stop";

export interface Mood {
  state: MoodState;
  title: string;
  sub: string;
  /** Hero card gradient (top, bottom) and accent for the progress bar. */
  tint: [string, string];
  accent: string;
}

const TINTS: Record<MoodState, { tint: [string, string]; accent: string }> = {
  red: { tint: ["#fdf1ee", "#f8ddd6"], accent: "#e06a52" },
  stop: { tint: ["#fdf7ea", "#f6e8c9"], accent: "#d99a2b" },
  amber: { tint: ["#fdf7ea", "#f6e8c9"], accent: "#d99a2b" },
  green: { tint: ["#eef8f3", "#d6efe4"], accent: "#2e9a7c" },
  thinking: { tint: ["#eef8f9", "#d7eef0"], accent: "#138a93" },
  default: { tint: ["#eef8f9", "#d7eef0"], accent: "#138a93" },
};

/** Verdict and evidence set the colour; the numeric score never establishes a scam. */
export function mood(c: Case, working: boolean): Mood {
  const pick = (state: MoodState, title: string, sub: string): Mood => ({ state, title, sub, ...TINTS[state] });
  if (c.decision?.verdict === "likely_scam") {
    return pick("red", "This looks like a scam", "Don't pay anything. Warden found evidence of a likely scam.");
  }

  // Only the orchestrator's targeted confirmation is a payment warning, not every payment question.
  if (openActions(c).some((a) => a.check_id === "payment_safety" && a.id.startsWith("act_confirm_payment_"))) {
    return pick("stop", "Don’t pay yet—confirm the payment request", "Check the quoted request and tell Warden what happened. This concern is not yet confirmed.");
  }
  const checks = c.checks ?? [];
  const flaggedAnswer = (c.actions ?? []).some((a) => a.status === "done" && a.outcome === "flags");
  if (checks.some((k) => k.state === "suspicious") || redFlags(c).length || flaggedAnswer) {
    return pick("amber", "Don't pay yet", "There are concerns to clear up. Check the evidence and answer the open questions.");
  }
  if (c.decision?.verdict === "proceed_with_care") {
    return pick("amber", "Proceed with care", "Some checks remain unresolved. Review the remaining steps before paying.");
  }
  if (working) return pick("thinking", "Warden's agents are checking…", "This usually takes under a minute.");

  const allCleared = checks.length === CHECK_ORDER.length &&
    CHECK_ORDER.every((id) => checks.some((k) => k.id === id && k.state === "cleared"));
  if (allCleared) {
    return pick("green", "No red flags remaining", "All checks are cleared on the available evidence. This is not a guarantee.");
  }
  return pick("default", "Not verified yet", "Unverified checks remain. Add evidence or complete the open steps before paying.");
}

export type RiskCategory = "unknown" | "concerns" | "high" | "no_red_flags";

export interface RiskDisplay {
  category: RiskCategory;
  label: string;
  color: string;
  /** A category's fixed place on the dial, not a numerical risk estimate. Unknown has no needle. */
  needlePosition: number | null;
  headline: string;
  sub: string;
}

const RISK_CATEGORIES: Record<RiskCategory, Pick<RiskDisplay, "label" | "color" | "needlePosition">> = {
  unknown: { label: "Unknown risk", color: "#728990", needlePosition: null },
  concerns: { label: "Concerns found", color: "#d99a2b", needlePosition: 50 },
  high: { label: "High risk", color: "#e06a52", needlePosition: 86 },
  no_red_flags: { label: "No red flags remaining", color: "#2e9a7c", needlePosition: 14 },
};

/** Evidence and verdict determine risk; the weighted verification score never moves this needle. */
export function riskDisplay(c: Case, status: Mood) {
  const evidenceState = mood(c, false).state;
  const category: RiskCategory = evidenceState === "red" ? "high"
    : evidenceState === "stop" || evidenceState === "amber" ? "concerns"
    : evidenceState === "green" ? "no_red_flags" : "unknown";
  return { category, ...RISK_CATEGORIES[category], headline: status.title, sub: status.sub } satisfies RiskDisplay;
}

/** The user's exact weighted progress formula, as a percentage, independent of a final verdict. */
export function verificationProgress(c: Case): number {
  const remaining = currentScore(c);
  if (!Number.isFinite(remaining)) return 0;
  return Math.max(0, Math.min(100, Number((100 * (1 - remaining / 100)).toFixed(2))));
}

export type CardStatus = "todo" | "done" | "answered" | "flagged" | "skipped";

/** An answered question only earns a positive badge when its outcome actually clears a check. */
export function actionCardStatus(a: Action): CardStatus {
  const status = a.status ?? "open";
  if (status === "open") return "todo";
  if (status === "skipped" || status === "impossible") return "skipped";
  if (a.outcome === "flags") return "flagged";
  return a.outcome === "clears" ? "done" : "answered";
}

/** Cleared findings (e.g. "Active on Companies House"), most confident first, for "What checks out". */
export function clears(c: Case): Finding[] {
  return allFindings(c)
    .filter((f) => f.supports === "cleared")
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
}

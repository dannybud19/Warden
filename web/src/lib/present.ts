import type { Case, CheckId, EvidenceKind, Finding, AgentUiStatus, Action } from "./types";
import { CHECK_LABELS } from "./labels";
import { SEVERITY_ORDER, allFindings, detailText, isRedFlag, openActions } from "./selectors";

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
  return f.severity === "critical" || f.severity === "high" ? "red" : "amber";
}

export function agentRows(c: Case, live: Record<string, AgentUiStatus>): AgentRow[] {
  return AGENT_DISPLAY_ORDER.map((name) => {
    const meta = AGENT_META[name];
    const report = c.reports?.[name];
    const status: AgentUiStatus = live[name] === "running" ? "running" : (report?.status ?? "idle");
    const findings = [...(report?.findings ?? [])].sort((a, b) => {
      const s = Number(a.supports === "cleared") - Number(b.supports === "cleared");
      return s || severityRank(a) - severityRank(b);
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
    return { name, meta, chip: "waiting", line: meta.missing, tone: "grey", muted: true, showUpload: !!meta.upload };
  });
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

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Mascot state from the case. Mapping:
 * agents running -> thinking; verdict likely_scam -> red, not_verified -> amber, proceed_with_care and
 * no_red_flags_remaining -> green. Before a verdict: an open step about payment -> stop (the payment
 * checkpoint), a hard red flag -> red, any red flag -> amber, cleared checks only -> green, nothing yet -> default.
 */
export function mood(c: Case, working: boolean): Mood {
  const flags = redFlags(c);
  const n = flags.length;
  const pick = (state: MoodState, title: string, sub: string): Mood => ({ state, title, sub, ...TINTS[state] });

  if (working) return pick("thinking", "Warden's agents are checking…", "This usually takes under a minute.");

  const v = c.decision?.verdict;
  if (v === "likely_scam") return pick("red", "This looks like a scam", `Don't pay anything. Warden found ${plural(n, "red flag", "red flags")}.`);
  if (v === "not_verified") return pick("amber", "Don't pay yet", n ? `Key things aren't verified, and there ${n === 1 ? "is 1 red flag" : `are ${n} red flags`}.` : "Key things aren't verified yet.");
  if (v === "proceed_with_care") return pick("green", "Proceed with care", "Nothing serious so far. Still see it in person before paying.");
  if (v === "no_red_flags_remaining") return pick("green", "No red flags remaining", "Warden checked everything it could. Still see it in person before paying.");

  if (openActions(c).some((a) => a.check_id === "payment_safety")) {
    return pick("stop", "Stop before you pay", "Don't send any money until this is cleared.");
  }
  if (flags.some((f) => f.hard_flag)) {
    return pick("red", "This could be a scam", `Don't pay anything. ${plural(n, "red flag", "red flags")} so far.`);
  }
  if (n) return pick("amber", "Some things don't add up", `${plural(n, "red flag", "red flags")} to look into before you pay.`);
  if ((c.checks ?? []).some((k) => k.state === "cleared")) {
    return pick("green", "Nothing flagged so far", "Keep going: Warden can check more if you forward it.");
  }
  return pick("default", "Forward what they sent you", "Chats, emails, the listing link or the contract.");
}

/** Cleared findings, for the "looks fine" part of the list. */
export function clears(c: Case): Finding[] {
  return allFindings(c).filter((f) => f.supports === "cleared");
}

import type { Case, CheckId, CheckState, EvidenceKind, Finding } from "./types";
import { CHECK_ORDER } from "./labels";
import { allFindings, openActions } from "./selectors";
import { SEVERITY_ORDER } from "./selectors";

// Presentation for the one-home dashboard (left side): the check map, the story strip and the decision.

/** Plain, positive names: each tile reads as the thing we want to be true. */
export const CHECK_TILE: Record<CheckId, string> = {
  landlord_identity: "Agency is real",
  payment_safety: "Payment is safe",
  right_to_let: "Allowed to let it",
  in_person_viewing: "Seen it in person",
  contract_consistency: "Contract matches",
  deposit_protection: "Deposit protected",
  no_pressure: "No pressure",
  fair_price: "Fair price",
};

/** What would settle an unproven check, and the upload that does it (if any). */
export const SETTLE: Record<CheckId, { text: string; upload?: { kind: EvidenceKind; label: string; accept: string } }> = {
  landlord_identity: { text: "Ask the agent for their company number. A real agency shares it straight away." },
  payment_safety: { text: "Ask how they want to be paid. Never by gift card, crypto or before a viewing." },
  right_to_let: {
    text: "Ask for proof they own or manage the place, like a management agreement.",
    upload: { kind: "document", label: "Add proof", accept: ".pdf,image/*" },
  },
  in_person_viewing: {
    text: "Book a viewing, or upload a video of you walking round it.",
    upload: { kind: "video", label: "Add video", accept: "video/*" },
  },
  contract_consistency: {
    text: "Upload the tenancy agreement so Warden can compare it with the listing.",
    upload: { kind: "contract", label: "Add contract", accept: ".pdf,image/*" },
  },
  deposit_protection: {
    text: "Upload the deposit protection certificate (DPS, mydeposits or TDS).",
    upload: { kind: "document", label: "Add certificate", accept: ".pdf,image/*" },
  },
  no_pressure: {
    text: "Forward your chats so Warden can spot pressure tactics.",
    upload: { kind: "chat_export", label: "Add chats", accept: ".txt,.zip,image/*" },
  },
  fair_price: {
    text: "Share the listing link so Warden can compare the rent with similar places.",
    upload: { kind: "listing", label: "Add listing", accept: ".pdf,image/*,.txt" },
  },
};

const SOURCE: Record<string, string> = {
  message_checker: "From your chats",
  emotion_classifier: "From the tone of your chats",
  companies_house: "Checked on Companies House",
  contract_checker: "From the contract",
  video_analysis: "From the viewing video",
  crosscheck: "Compared across what you sent",
};

export function sourceOf(f: Finding): string {
  return SOURCE[f.agent] ?? "From what you sent";
}

export interface Tile {
  id: CheckId;
  label: string;
  state: CheckState;
  findings: Finding[];
  reason: string | null;
}

function rank(f: Finding): number {
  return (f.hard_flag ? -10 : 0) + SEVERITY_ORDER.indexOf(f.severity as (typeof SEVERITY_ORDER)[number]);
}

export function tiles(c: Case): Tile[] {
  const byCheck = new Map<string, Finding[]>();
  for (const f of allFindings(c)) byCheck.set(f.check_id, [...(byCheck.get(f.check_id) ?? []), f]);
  return CHECK_ORDER.map((id) => {
    const check = (c.checks ?? []).find((k) => k.id === id);
    const findings = (byCheck.get(id) ?? []).sort((a, b) => {
      const s = Number(a.supports === "cleared") - Number(b.supports === "cleared");
      return s || rank(a) - rank(b);
    });
    return { id, label: CHECK_TILE[id], state: (check?.state ?? "unverified") as CheckState, findings, reason: check?.reason ?? null };
  });
}

/** The tile to open first: the worst red flag, else the first unproven check. */
export function firstTile(ts: Tile[]): CheckId {
  const flagged = ts
    .filter((t) => t.state === "suspicious")
    .sort((a, b) => rank(a.findings[0] ?? ({ severity: "info" } as Finding)) - rank(b.findings[0] ?? ({ severity: "info" } as Finding)));
  return (flagged[0] ?? ts.find((t) => t.state === "unverified") ?? ts[0]).id;
}

// ---- Story strip: what each upload changed ----

export const AGENTS_FOR: Partial<Record<EvidenceKind, string[]>> = {
  chat_export: ["message_checker", "emotion_classifier"],
  chat_screenshot: ["message_checker", "emotion_classifier"],
  email: ["message_checker", "emotion_classifier"],
  call_recording: ["message_checker", "emotion_classifier"],
  contract: ["contract_checker"],
  video: ["video_analysis"],
  listing: ["companies_house"],
};

const KIND_TITLE: Record<EvidenceKind, string> = {
  chat_screenshot: "Chat screenshot added",
  chat_export: "Chats added",
  email: "Email added",
  call_recording: "Call recording added",
  video: "Viewing video added",
  document: "Document added",
  contract: "Contract added",
  listing: "Listing added",
};

export type StepTone = "red" | "amber" | "green" | "grey" | "next";

export interface Step {
  key: string;
  at: string | null;
  title: string;
  result: string;
  tone: StepTone;
}

function effect(c: Case, agents: string[]): { result: string; tone: StepTone } {
  const fs = agents.flatMap((a) => c.reports?.[a]?.findings ?? []);
  const flags = fs.filter((f) => f.supports === "suspicious");
  const cleared = fs.filter((f) => f.supports === "cleared").length;
  if (flags.length) {
    const hard = flags.some((f) => f.hard_flag || f.severity === "critical" || f.severity === "high");
    return { result: `+${flags.length} red flag${flags.length === 1 ? "" : "s"}`, tone: hard ? "red" : "amber" };
  }
  if (cleared) return { result: `${cleared} cleared`, tone: "green" };
  return { result: "Nothing new", tone: "grey" };
}

export function story(c: Case): Step[] {
  // A listing shared when the case was opened is the same moment as "added this home": fold it in.
  const created = Date.parse(c.created_at);
  const atStart = (iso: string) => Math.abs(Date.parse(iso) - created) < 5 * 60_000;
  const sharedListing = (c.evidence ?? []).some((e) => e.kind === "listing" && atStart(e.uploaded_at));
  const steps: Step[] = [
    {
      key: "start", at: c.created_at, title: sharedListing ? "You shared the listing" : "You added this home",
      ...effect(c, ["companies_house"]),
    },
  ];
  const seen = new Set<string>(["companies_house"]);
  const evidence = [...(c.evidence ?? [])]
    .filter((e) => !(e.kind === "listing" && atStart(e.uploaded_at)))
    .sort((a, b) => a.uploaded_at.localeCompare(b.uploaded_at));
  for (const e of evidence) {
    const agents = (AGENTS_FOR[e.kind] ?? []).filter((a) => !seen.has(a));
    agents.forEach((a) => seen.add(a));
    steps.push({ key: e.id, at: e.uploaded_at, title: KIND_TITLE[e.kind] ?? "Evidence added", ...effect(c, agents) });
  }
  const next = openActions(c)[0];
  if (next && c.status === "open") {
    steps.push({ key: "next", at: null, title: next.text.replace(/\?$/, ""), result: "Could change it", tone: "next" });
  }
  return steps;
}

export function when(iso: string | null): string {
  if (!iso) return "Next";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// ---- The decision ----

/** Checks that must be cleared before Warden unlocks "Go ahead". */
export const GO_AHEAD_NEEDS: CheckId[] = ["landlord_identity", "payment_safety", "right_to_let"];

export function goAheadUnlocked(c: Case): boolean {
  return GO_AHEAD_NEEDS.every((id) => (c.checks ?? []).find((k) => k.id === id)?.state === "cleared");
}

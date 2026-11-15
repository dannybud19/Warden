import type { Case, Finding, Action, CheckId } from "./types";

export const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;

export function currentScore(c: Case): number {
  const history = c.score_history ?? [];
  return history.length ? history[history.length - 1].score : 100;
}

export function contributions(c: Case): Record<string, number> {
  const history = c.score_history ?? [];
  return history.length ? (history[history.length - 1].contributions as Record<string, number>) : {};
}

/** Every finding from every report (incl. reports["crosscheck"]), de-duplicated by id. */
export function allFindings(c: Case): Finding[] {
  const seen = new Map<string, Finding>();
  for (const report of Object.values(c.reports ?? {})) {
    for (const f of report.findings ?? []) seen.set(f.id, f);
  }
  return [...seen.values()].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity as never) - SEVERITY_ORDER.indexOf(b.severity as never),
  );
}

/** A finding that counts against the home: suspicious, and more than an info note. */
export function isRedFlag(f: Finding): boolean {
  return f.supports === "suspicious" && f.severity !== "info";
}

/** Info notes such as "Some background checks could not run": shown to the student, never a red flag. */
export function infoNotes(c: Case): Finding[] {
  return allFindings(c).filter((f) => f.supports === "suspicious" && f.severity === "info");
}

export function findingsByCheck(c: Case): Record<CheckId, Finding[]> {
  const out = {} as Record<CheckId, Finding[]>;
  for (const f of allFindings(c)) {
    const key = f.check_id as CheckId;
    (out[key] ??= []).push(f);
  }
  return out;
}

export function openActions(c: Case): Action[] {
  return (c.actions ?? []).filter((a) => (a.status ?? "open") === "open");
}

export function closedActions(c: Case): Action[] {
  return (c.actions ?? []).filter((a) => (a.status ?? "open") !== "open");
}

export function isDecided(c: Case): boolean {
  return c.status === "decided";
}

const SOURCE_LINE = /^\s*Source:\s*(https?:\/\/\S+)\s*$/i;

/** Web pages a finding cites, read from "Source: <url>" lines in its detail (Companies House, Linkup). */
export function sourceUrls(f: Finding): string[] {
  const urls = (f.detail ?? "").split("\n").flatMap((line) => SOURCE_LINE.exec(line)?.[1] ?? []);
  return [...new Set(urls)];
}

/** The finding's detail without its "Source:" lines (those are shown as links instead). */
export function detailText(f: Finding): string {
  return (f.detail ?? "").split("\n").filter((line) => !SOURCE_LINE.test(line)).join("\n").trim();
}

type Ref = { evidence_id: string; quote?: string | null };

const KIND_LABEL: Record<string, string> = {
  chat_export: "Chat",
  chat_screenshot: "Chat screenshot",
  email: "Email",
  call_recording: "Call recording",
  video: "Video",
  document: "Document",
  contract: "Contract",
  listing: "Listing",
};

// Evidence ids that are not uploads: agents use them for what the student typed or for web checks.
const NOT_AN_UPLOAD: Record<string, string> = {
  listing: "The listing details you gave",
  landlord: "The agent details you gave",
  student_notes: "Your notes",
  companies_house: "Companies House register",
  web: "Web search",
  london_rogue_checker: "London rogue landlord checker",
  postcodes_io: "Postcode lookup",
  rdap: "Domain registration record",
};

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  });

/**
 * Where one quote comes from, for long chats and emails: the upload, and when the quote is in a
 * parsed message, its position, who sent it and when.
 * E.g. "Chat (whatsapp.txt) · message 7 of 8 · the agent · 12 Nov, 18:14".
 */
export function quoteSource(c: Case, ref: Ref): string {
  const fixed = NOT_AN_UPLOAD[ref.evidence_id];
  if (fixed) return fixed;
  const ev = (c.evidence ?? []).find((e) => e.id === ref.evidence_id);
  if (!ev) return "From what you sent";

  const kind = KIND_LABEL[ev.kind] ?? "Upload";
  const parts = [ev.filename ? `${kind} (${ev.filename})` : kind];
  const thread = (c.messages ?? []).filter((m) => m.evidence_id === ev.id);
  const quote = (ref.quote ?? "").trim();
  const at = quote ? thread.findIndex((m) => m.text.includes(quote)) : -1;
  if (at >= 0) {
    const m = thread[at];
    if (thread.length > 1) parts.push(`message ${at + 1} of ${thread.length}`);
    const agent = c.landlord?.name?.trim() || "the agent";
    parts.push(m.sender === "student" ? "you" : m.sender === "agent" ? agent : "unknown sender");
    if (m.sent_at) parts.push(when(String(m.sent_at)));
  } else {
    parts.push(`sent ${when(ev.uploaded_at)}`);
  }
  return parts.join(" · ");
}

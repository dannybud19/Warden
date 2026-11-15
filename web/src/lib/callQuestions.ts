// Questions for the voice call, built in the browser from the case the page already holds.
// The ElevenLabs client tools (get_next_questions, record_answer) use these: no backend call
// and no LLM during the call.
import { AGENT_LABELS, CHECK_LABELS, EVIDENCE_KIND_LABELS } from "./labels";
import { allFindings, detailText, isRedFlag, openActions } from "./selectors";
import type { Case, CheckId, EvidenceKind, Finding } from "./types";

/** One question Warden may ask on the call. `id` is the open action's id (pass it to
 * record_answer), or null for an agent's question that is not an action yet. */
export interface CallQuestion {
  id: string | null;
  text: string;
  why: string;
}

export const NO_QUESTIONS_TEXT =
  "No open questions. Ask if anything else happened, like money requested, a viewing refused, or pressure to decide.";

/** Id prefix of the orchestrator's payment confirmation (backend `payment_confirmation.PREFIX`). */
const PAYMENT_CONFIRMATION_PREFIX = "act_confirm_payment_";

function normalize(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();
}

/** Open actions first (a payment confirmation first of all), then agents' questions not
 * already covered by an action, at most `max`. */
export function openQuestions(c: Case, max = 3): CallQuestion[] {
  const open = openActions(c);
  // Array.prototype.sort is stable: the rest keep the case's own order.
  const ordered = [
    ...open.filter((a) => a.id.startsWith(PAYMENT_CONFIRMATION_PREFIX)),
    ...open.filter((a) => !a.id.startsWith(PAYMENT_CONFIRMATION_PREFIX)),
  ];
  const out: CallQuestion[] = [];
  // Agent questions are compared with every action, closed ones too: an answered step is not re-asked.
  const seen = new Set((c.actions ?? []).map((a) => normalize(a.text)));
  for (const a of ordered) {
    out.push({ id: a.id, text: a.text, why: CHECK_LABELS[a.check_id as CheckId] ?? "This home" });
  }
  for (const [name, report] of Object.entries(c.reports ?? {})) {
    for (const q of report.questions ?? []) {
      const key = normalize(q);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push({ id: null, text: q, why: AGENT_LABELS[report.agent ?? name] ?? AGENT_LABELS[name] ?? name });
    }
  }
  return out.slice(0, Math.max(0, max));
}

/** The tool's text: one line per question, `<action_id>: <question> (why: <check label>)`;
 * NO_QUESTIONS_TEXT when the list is empty. */
export function formatQuestions(list: CallQuestion[]): string {
  if (!list.length) return NO_QUESTIONS_TEXT;
  return list
    .map((q, i) => {
      const text = q.text.replace(/\s+/g, " ").trim();
      return q.id
        ? `${i + 1}. ${q.id}: ${text} (why: ${q.why})`
        : `${i + 1}. (no id, just ask) ${text} (why: ${q.why})`;
    })
    .join("\n");
}

/** True when `id` is an open action of this case (record_answer validates with it). */
export function isOpenAction(c: Case, id: string): boolean {
  return openActions(c).some((a) => a.id === id);
}

export const NO_BRIEFING_TEXT = "Nothing has been read yet: no chats, emails or documents are uploaded.";

const BRIEFING_MAX_FINDINGS = 12;
const BRIEFING_MAX_CHARS = 3500;

function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

/** What the checker agents found in the chats, emails and documents, as the orchestrator holds it
 * on the case: what was uploaded, the Cross-checker's recap, Warden's last chat message and each
 * agent's findings (red flags first). Passed to the voice agent at call start (`case_briefing`). */
export function callBriefing(c: Case): string {
  const parts: string[] = [];

  const kinds = new Map<string, number>();
  for (const e of c.evidence ?? []) {
    const label = EVIDENCE_KIND_LABELS[e.kind as EvidenceKind] ?? String(e.kind);
    kinds.set(label, (kinds.get(label) ?? 0) + 1);
  }
  if (kinds.size) {
    parts.push(`Uploaded so far: ${[...kinds].map(([k, n]) => `${n} x ${k.toLowerCase()}`).join(", ")}.`);
  }

  const recap = c.reports?.crosscheck?.summary;
  if (recap) parts.push(`Recap of all checks: ${clip(recap, 700)}`);

  const lastSaid = [...(c.chat ?? [])].reverse().find((t) => t.role === "orchestrator");
  if (lastSaid?.text) parts.push(`Warden's last chat message to the student: ${clip(lastSaid.text, 500)}`);

  // allFindings is already most serious first; red flags lead, then what checks out, then notes.
  const rank = (f: Finding) => (isRedFlag(f) ? 0 : f.supports === "cleared" ? 1 : 2);
  const findings = allFindings(c)
    .map((f, i) => ({ f, i }))
    .sort((a, b) => rank(a.f) - rank(b.f) || a.i - b.i)
    .slice(0, BRIEFING_MAX_FINDINGS)
    .map(({ f }) => {
      const kind = isRedFlag(f) ? "RED FLAG" : f.supports === "cleared" ? "Checks out" : "Note";
      const who = AGENT_LABELS[f.agent] ?? f.agent;
      const detail = clip(detailText(f), 220);
      return `- ${kind} (${who}): ${clip(f.title, 120)}${detail ? `. ${detail}` : ""}`;
    });
  if (findings.length) parts.push(`Findings:\n${findings.join("\n")}`);

  if (!parts.length) return NO_BRIEFING_TEXT;
  const text = parts.join("\n");
  return text.length > BRIEFING_MAX_CHARS ? `${text.slice(0, BRIEFING_MAX_CHARS - 1)}…` : text;
}

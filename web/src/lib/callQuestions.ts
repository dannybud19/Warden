// Questions for the voice call, built in the browser from the case the page already holds.
// The ElevenLabs client tools (get_next_questions, record_answer) use these: no backend call
// and no LLM during the call.
import { AGENT_LABELS, CHECK_LABELS } from "./labels";
import { openActions } from "./selectors";
import type { Case, CheckId } from "./types";

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

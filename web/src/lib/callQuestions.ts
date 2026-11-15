// Questions for the voice call, built in the browser from the case the page already holds.
// The ElevenLabs client tools (get_next_questions, record_answer) use these: no backend call
// and no LLM during the call.
import type { Case } from "./types";

/** One question Warden may ask on the call. `id` is the open action's id (pass it to
 * record_answer), or null for an agent's question that is not an action yet. */
export interface CallQuestion {
  id: string | null;
  text: string;
  why: string;
}

export const NO_QUESTIONS_TEXT =
  "No open questions. Ask if anything else happened, like money requested, a viewing refused, or pressure to decide.";

/** Open actions first (a payment confirmation first of all), then agents' questions not
 * already covered by an action, at most `max`. */
export function openQuestions(c: Case, max = 3): CallQuestion[] {
  void c;
  void max;
  throw new Error("not implemented");
}

/** The tool's text: one line per question, `<action_id>: <question> (why: <check label>)`;
 * NO_QUESTIONS_TEXT when the list is empty. */
export function formatQuestions(list: CallQuestion[]): string {
  void list;
  throw new Error("not implemented");
}

/** True when `id` is an open action of this case (record_answer validates with it). */
export function isOpenAction(c: Case, id: string): boolean {
  void c;
  void id;
  throw new Error("not implemented");
}

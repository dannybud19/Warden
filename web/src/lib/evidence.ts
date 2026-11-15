import type { Case, Evidence } from "./types";

/** Note sent with an upload from the "Payment details" spot, so it can be told apart from other documents. */
export const PAYMENT_NOTE = "Payment details";

export type AddSlot = "chats" | "emails" | "contract" | "video" | "payment" | "other";

/** Which "Add more" spot an upload belongs to. */
export function slotOf(e: Evidence): AddSlot | null {
  switch (e.kind) {
    case "chat_export":
    case "chat_screenshot":
      return "chats";
    case "email":
      return "emails";
    case "contract":
      return "contract";
    case "video":
      return "video";
    case "document":
      return e.note === PAYMENT_NOTE ? "payment" : "other";
    default:
      return null;
  }
}

/** How many uploads the student has already sent for each spot. */
export function addedBySlot(c: Case): Partial<Record<AddSlot, number>> {
  const out: Partial<Record<AddSlot, number>> = {};
  for (const e of c.evidence ?? []) {
    const s = slotOf(e);
    if (s) out[s] = (out[s] ?? 0) + 1;
  }
  return out;
}

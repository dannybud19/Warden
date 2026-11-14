import fixture from "@/mocks/full_case.json";
import type { Case } from "./types";

// Read-only mock: every call returns the decided fixture case. Good for viewing, not for flows.
export function getCase(): Case {
  return fixture as unknown as Case;
}

export function openCase(): Case {
  return getCase();
}

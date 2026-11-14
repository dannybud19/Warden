// Stable aliases over generated contract types. If a name differs in contracts.ts, fix it HERE only.
export type {
  Case,
  Evidence1 as Evidence,
  Message,
  Finding,
  Fact,
  Check,
  Action,
  AgentReport,
  ScoreResult,
  Decision,
} from "@/types/contracts";

import type {
  AgentReport,
  ScoreResult,
  Action,
  Decision,
} from "@/types/contracts";

// Enum-like string unions (copied from contracts.ts, which exports them only as loose aliases).
export type EvidenceKind =
  | "chat_screenshot" | "chat_export" | "email" | "call_recording"
  | "video" | "document" | "contract" | "listing";
export type CheckId =
  | "landlord_identity" | "payment_safety" | "right_to_let" | "in_person_viewing"
  | "contract_consistency" | "deposit_protection" | "no_pressure" | "fair_price";
export type CheckState = "unverified" | "suspicious" | "cleared";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Verdict = "likely_scam" | "not_verified" | "proceed_with_care" | "no_red_flags_remaining";
export type AgentStatus = "ok" | "skipped" | "needs_input" | "error";
export type ActionStatusInput = "done" | "skipped" | "impossible";

// Stream events (plan.md section 5). Defined by hand here because generators often flatten unions.
export type StreamEvent =
  | { type: "agent_started"; agent: string }
  | { type: "agent_finished"; report: AgentReport }
  | { type: "score_updated"; score: ScoreResult }
  | { type: "actions_proposed"; actions: Action[] }
  | { type: "orchestrator_message"; text: string }
  | { type: "decision_made"; decision: Decision };

export type AgentUiStatus = "idle" | "running" | AgentStatus;
export type ConnectionState = "mock" | "connecting" | "live" | "polling";

export interface ChatEntry {
  role: "orchestrator" | "student";
  text: string;
  at: string; // ISO time
}

// Stable aliases over generated contract types. If a name differs in contracts.ts, fix it HERE only.
// Generated fields are now all required, but nullable ones (filename, answer, error, ...) are `| null`:
// read those with `?? fallback`, never with a default parameter or `=== undefined`.
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
  EvidenceKind,
  CheckId,
  CheckState,
  Severity,
  Verdict,
  AgentStatus,
  ActionStatus,
  Event as StreamEvent,
} from "@/types/contracts";

import type { AgentStatus, ActionStatus } from "@/types/contracts";

// What the student can send when answering an action (not generated: an API-only request field).
export type ActionStatusInput = Exclude<ActionStatus, "open">;

export type AgentUiStatus = "idle" | "running" | AgentStatus;
export type ConnectionState = "mock" | "connecting" | "live" | "polling";

export interface ChatEntry {
  role: "orchestrator" | "student";
  text: string;
  at: string; // ISO time
}

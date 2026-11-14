import type { CheckId, CheckState, EvidenceKind, Severity, Verdict, AgentUiStatus } from "./types";

export const AGENT_ORDER = [
  "companies_house", "message_checker", "contract_checker", "emotion_classifier", "video_analysis",
] as const;

export const AGENT_LABELS: Record<string, string> = {
  companies_house: "Companies House",
  message_checker: "Message checker",
  contract_checker: "Contract checker",
  emotion_classifier: "Facts vs feelings",
  video_analysis: "Video analysis",
  crosscheck: "Cross-check",
};

export const AGENT_STATUS_LABELS: Record<AgentUiStatus, string> = {
  idle: "Waiting", running: "Checking…", ok: "Done", skipped: "Needs evidence",
  needs_input: "Needs input", error: "Couldn't run",
};

export const CHECK_ORDER: CheckId[] = [
  "landlord_identity", "payment_safety", "right_to_let", "in_person_viewing",
  "contract_consistency", "deposit_protection", "no_pressure", "fair_price",
];

export const CHECK_LABELS: Record<CheckId, string> = {
  landlord_identity: "Landlord identity",
  payment_safety: "Payment safety",
  right_to_let: "Right to let",
  in_person_viewing: "In-person viewing",
  contract_consistency: "Contract matches",
  deposit_protection: "Deposit protection",
  no_pressure: "No pressure tactics",
  fair_price: "Fair price",
};

export const CHECK_STATE_LABELS: Record<CheckState, string> = {
  unverified: "Not verified yet", suspicious: "Red flag", cleared: "Verified",
};

export const SEVERITY_LABELS: Record<Severity, string> = {
  critical: "Critical", high: "High", medium: "Medium", low: "Low", info: "Note",
};

export const VERDICT_LABELS: Record<Verdict, string> = {
  likely_scam: "Likely scam: do not pay",
  not_verified: "Not verified: don't pay yet",
  proceed_with_care: "Proceed with care",
  no_red_flags_remaining: "No red flags remaining",
};

export const EVIDENCE_KIND_LABELS: Record<EvidenceKind, string> = {
  chat_screenshot: "Chat screenshot",
  chat_export: "WhatsApp export / pasted chat",
  email: "Email (paste text)",
  call_recording: "Call recording",
  video: "Viewing video",
  document: "Document",
  contract: "Contract (PDF)",
  listing: "Listing",
};

export function scoreBand(score: number): string {
  if (score >= 75) return "Mostly unverified";
  if (score >= 40) return "Partly verified";
  return "Largely verified";
}

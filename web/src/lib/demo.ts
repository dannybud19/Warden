import type { Case, Finding, AgentReport, Check, Action, CheckId, EvidenceKind } from "./types";
import type { ReplyInput } from "./api";
import { CHECK_ORDER } from "./labels";

// A local, open case that mirrors the hi-fi design ("Flat 2, 41 Mile End Road"). It lets the product
// screens run with no backend at /case/demo. Replies and uploads change this in-memory copy only.
export const DEMO_CASE_ID = "demo";

const AT = "2026-11-14T14:06:30Z";
const CREATED = "2026-11-13T18:20:00Z";

function finding(
  id: string, agent: string, check_id: CheckId, title: string, detail: string,
  severity: Finding["severity"], supports: Finding["supports"], hard_flag = false,
  quote?: { from: string; text: string },
): Finding {
  return {
    id, agent, check_id, title, detail, severity, supports, hard_flag,
    category: check_id === "payment_safety" ? "payment" : check_id === "no_pressure" ? "pressure" : "identity",
    confidence: 0.9,
    evidence: quote ? [{ evidence_id: quote.from, quote: quote.text }] : [],
  } as Finding;
}

function report(agent: string, status: AgentReport["status"], findings: Finding[]): AgentReport {
  return {
    agent, version: "demo", status, input_hash: "demo", findings, facts: [], questions: [],
    error: null, duration_ms: 0,
  } as AgentReport;
}

const F = {
  money: finding(
    "f_money", "message_checker", "payment_safety",
    "They asked for money before you've seen the place",
    "The agent asked for a £500 holding deposit by bank transfer before any viewing was booked. " +
      "Genuine agents let you see a place before taking money.",
    "critical", "suspicious", true,
    { from: "ev_chats", text: "Send the £500 holding deposit today and I'll send you the keys after." },
  ),
  register: finding(
    "f_register", "companies_house", "landlord_identity",
    "The agency isn't on the official company register",
    "No company called Quickkeys Lettings is on Companies House. A real letting agency is a registered company.",
    "critical", "suspicious", true,
  ),
  abroad: finding(
    "f_abroad", "message_checker", "in_person_viewing",
    "The landlord says they're abroad and can't show you round",
    "\"I'm working in Dubai until January so I can't do viewings.\" A landlord who can't meet you is a common scam pattern.",
    "high", "suspicious", false,
    { from: "ev_chats", text: "I'm working in Dubai until January so I can't do viewings." },
  ),
  pressure: finding(
    "f_pressure", "emotion_classifier", "no_pressure",
    "2 pushy phrases, like “need it tonight”",
    "\"I need it tonight or it goes to the next student.\" Pressure to decide fast stops you from checking.",
    "medium", "suspicious", false,
    { from: "ev_chats", text: "I need it tonight or it goes to the next student." },
  ),
  contract: finding(
    "f_contract", "contract_checker", "contract_consistency",
    "Address and rent match the listing",
    "The contract names Flat 2, 41 Mile End Road at £1,150 pcm, the same as the SpareRoom listing.",
    "info", "cleared",
  ),
};

const STATES: Partial<Record<CheckId, Check["state"]>> = {
  landlord_identity: "suspicious",
  payment_safety: "suspicious",
  in_person_viewing: "suspicious",
  no_pressure: "suspicious",
  contract_consistency: "cleared",
};

const REASONS: Partial<Record<CheckId, string>> = {
  deposit_protection: "Not checked yet: we don't know which scheme your deposit would go into.",
};

const INITIAL: Case = {
  case_id: DEMO_CASE_ID,
  created_at: CREATED,
  status: "open",
  student: { budget_pcm: 1200, move_in_date: null, university: "Queen Mary University of London", notes: null },
  listing: {
    url: null, platform: "SpareRoom", address: "Flat 2, 41 Mile End Road, London E1 4TT", postcode: "E1 4TT",
    rent_pcm: 1150, deposit: 1327, description: null,
  },
  landlord: {
    name: "Daniel Price", company_name: "Quickkeys Lettings", company_number: null, email: null, phone: null,
  },
  evidence: [
    { id: "ev_listing", kind: "listing", uploaded_at: CREATED, filename: "SpareRoom listing", file_url: null, extracted_text: null, note: null },
    { id: "ev_chats", kind: "chat_export", uploaded_at: "2026-11-14T14:05:00Z", filename: "WhatsApp chat (14 messages)", file_url: null, extracted_text: null, note: null },
    { id: "ev_contract", kind: "contract", uploaded_at: "2026-11-14T14:06:00Z", filename: "Tenancy agreement (9 pages)", file_url: null, extracted_text: null, note: null },
  ] as Case["evidence"],
  messages: [],
  checks: CHECK_ORDER.map((id) => ({
    id, state: STATES[id] ?? "unverified", clear_confidence: STATES[id] === "cleared" ? 0.8 : 0,
    finding_ids: [], reason: REASONS[id] ?? null,
  })) as Check[],
  actions: [
    {
      id: "act_company_number", check_id: "landlord_identity", kind: "question",
      text: "Ask the agent for their company number?", status: "open", answer: null,
      answer_evidence_ids: [], outcome: null, asked_at: AT,
    },
  ] as Action[],
  // Insertion order matters: it breaks severity ties in the red flag list.
  reports: {
    message_checker: report("message_checker", "ok", [F.money, F.abroad]),
    companies_house: report("companies_house", "ok", [F.register]),
    emotion_classifier: report("emotion_classifier", "ok", [F.pressure]),
    contract_checker: report("contract_checker", "ok", [F.contract]),
    video_analysis: report("video_analysis", "skipped", []),
  },
  score_history: [
    { at: CREATED, score: 100, contributions: {} },
    { at: "2026-11-14T14:05:00Z", score: 88, contributions: {} },
    { at: AT, score: 81, contributions: {} },
  ],
  decision: null,
} as Case;

let current: Case = INITIAL;

export function getCase(): Case {
  return current;
}

export function reply(input: ReplyInput): Case {
  const open = (current.actions ?? []).filter((a) => a.status === "open");
  const target = input.actionId ? open.find((a) => a.id === input.actionId) : open[0];
  if (!target) return current;
  current = {
    ...current,
    actions: current.actions.map((a) =>
      a.id === target.id ? { ...a, status: input.status ?? "done", answer: input.text || null } : a,
    ),
  };
  return current;
}

export function upload(kind: EvidenceKind, filename: string | null): Case {
  current = {
    ...current,
    evidence: [
      ...current.evidence,
      {
        id: `ev_${current.evidence.length + 1}`, kind, uploaded_at: new Date().toISOString(), filename,
        file_url: null, extracted_text: null, note: null,
      } as Case["evidence"][number],
    ],
  };
  return current;
}

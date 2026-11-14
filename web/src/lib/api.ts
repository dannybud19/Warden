import { API_URL, USE_MOCK } from "./config";
import * as mock from "./mock";
import type {
  Case, Decision, EvidenceKind, StreamEvent, ConnectionState, ActionStatusInput,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export interface OpenCaseInput {
  student: { university?: string; notes?: string; budget_pcm?: number };
  listing?: { url?: string; platform?: string; address?: string; rent_pcm?: number; deposit?: number };
  landlord?: { name?: string; company_name?: string; company_number?: string };
}

export interface UploadInput {
  kind: EvidenceKind;
  file?: File | null;
  text?: string;
  note?: string;
  studentName: string;
}

export interface ReplyInput {
  text: string;
  evidenceIds?: string[];
  actionId?: string;
  status?: ActionStatusInput;
}

export async function openCase(input: OpenCaseInput): Promise<Case> {
  if (USE_MOCK) return mock.openCase();
  return request<Case>("/cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function getCase(caseId: string): Promise<Case> {
  if (USE_MOCK) return mock.getCase();
  return request<Case>(`/cases/${caseId}`);
}

export async function getDecision(caseId: string): Promise<Decision | null> {
  if (USE_MOCK) return mock.getCase().decision ?? null;
  try {
    return await request<Decision>(`/cases/${caseId}/decision`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export async function uploadEvidence(caseId: string, input: UploadInput): Promise<Case> {
  if (USE_MOCK) return mock.getCase();
  const form = new FormData();
  form.append("kind", input.kind);
  form.append("student_name", input.studentName);
  if (input.file) form.append("file", input.file);
  if (input.text) form.append("text", input.text);
  if (input.note) form.append("note", input.note);
  return request<Case>(`/cases/${caseId}/evidence`, { method: "POST", body: form });
}

export async function reply(caseId: string, input: ReplyInput): Promise<Case> {
  if (USE_MOCK) return mock.getCase();
  // NOTE: action cards send action_id + status together; free chat sends neither (backend then
  // answers the oldest open action). An unknown or already-closed action_id returns 422.
  return request<Case>(`/cases/${caseId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: input.text,
      evidence_ids: input.evidenceIds ?? [],
      action_id: input.actionId ?? null,
      status: input.status ?? null,
    }),
  });
}

/** Opens the event stream. Calls onState("polling") if the socket fails, so the hook can poll. */
export function subscribe(
  caseId: string,
  onEvent: (e: StreamEvent) => void,
  onState: (s: ConnectionState) => void,
): () => void {
  if (USE_MOCK) {
    onState("mock");
    return () => {};
  }
  let stopped = false;
  let ws: WebSocket | null = null;
  onState("connecting");
  try {
    ws = new WebSocket(`${API_URL.replace(/^http/, "ws")}/cases/${caseId}/stream`);
  } catch {
    onState("polling");
    return () => {};
  }
  ws.onopen = () => onState("live");
  ws.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data as string) as StreamEvent);
    } catch {
      /* ignore malformed event */
    }
  };
  ws.onerror = () => ws?.close();
  ws.onclose = () => {
    if (!stopped) onState("polling");
  };
  return () => {
    stopped = true;
    ws?.close();
  };
}

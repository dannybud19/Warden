import type { UploadInput } from "./api";
import type { Case } from "./types";

export interface UploadReceipt {
  case: Case;
  evidence_id: string;
  read_error: string | null;
}

export interface InitialUploadRequest {
  request_id: string;
  filename: string;
  kind: UploadInput["kind"];
  size: number;
  note?: string | null;
}

export interface InitialUpload extends InitialUploadRequest {
  state: "pending" | "accepted" | "skipped";
  evidence_id: string | null;
  read_error: string | null;
}

/** Allocate identities before opening the case, so checks cannot overtake its first files. */
export function prepareInitialUploads(inputs: UploadInput[], newId = () => crypto.randomUUID()): {
  inputs: UploadInput[]; manifest: InitialUploadRequest[];
} {
  const prepared = inputs.filter((input) => input.file).map((input) => ({ ...input, requestId: newId() }));
  return { inputs: prepared, manifest: prepared.map((input) => ({
    request_id: input.requestId, filename: input.file!.name, size: input.file!.size,
    kind: input.kind, note: input.note,
  })) };
}

export type UploadState = "queued" | "uploading" | "saved" | "unreadable" | "failed" | "interrupted" | "skipping" | "skipped";

export interface UploadRow {
  id: string;
  caseId: string;
  name: string;
  size: number;
  kind: UploadInput["kind"];
  note?: string;
  state: UploadState;
  message: string | null;
  evidenceId?: string;
  hasFile: boolean;
  initial: boolean;
  pending: boolean;
}

type StoredRows = Pick<Storage, "getItem" | "setItem">;
type Sender = (caseId: string, input: UploadInput) => Promise<UploadReceipt>;
type Skipper = (caseId: string, requestId: string) => Promise<InitialUpload[]>;
const STORAGE_KEY = "warden.uploads.v1";

/** Owns attachment progress across client-side navigation; file bytes stay in memory only. */
export class UploadQueue {
  private rows: UploadRow[] = [];
  private inputs = new Map<string, UploadInput>();
  private listeners = new Set<() => void>();
  private storage?: StoredRows;

  constructor(private send: Sender, private newId: () => string = () => crypto.randomUUID(), private skip?: Skipper) {}

  getSnapshot = (): UploadRow[] => this.rows;
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  /** Restore labels and outcomes, never files; interrupted requests must be checked before retry. */
  restore(storage: StoredRows): void {
    this.storage = storage;
    if (this.rows.length) return;
    try {
      const saved: unknown = JSON.parse(storage.getItem(STORAGE_KEY) ?? "[]");
      if (!Array.isArray(saved)) return;
      this.rows = saved.filter((r): r is UploadRow => r && typeof r.id === "string" &&
        typeof r.caseId === "string" && typeof r.name === "string" && typeof r.kind === "string" &&
        typeof r.size === "number" && ["queued", "uploading", "saved", "unreadable", "failed", "interrupted", "skipping", "skipped"].includes(r.state))
        .map((r) => ({ ...r, hasFile: false, initial: r.initial === true, pending: r.pending === true,
          note: typeof r.note === "string" ? r.note : undefined,
          evidenceId: typeof r.evidenceId === "string" ? r.evidenceId : undefined,
          state: ["queued", "uploading", "skipping"].includes(r.state) ? "interrupted" : r.state,
          message: ["queued", "uploading", "skipping"].includes(r.state)
            ? "Request interrupted. Checking the saved status; select the file again if it still needs retrying."
            : typeof r.message === "string" ? r.message : null,
        }));
      this.publish();
    } catch { /* Browser storage may be unavailable; the in-memory queue still works. */ }
  }

  private publish(): void {
    try { this.storage?.setItem(STORAGE_KEY, JSON.stringify(this.rows.map((r) => ({ ...r, hasFile: false })))); }
    catch { /* Never turn a storage quota error into an upload failure. */ }
    this.listeners.forEach((listener) => listener());
  }

  private update(id: string, change: Partial<UploadRow>): void {
    this.rows = this.rows.map((r) => r.id === id ? { ...r, ...change } : r);
    this.publish();
  }

  /** Register every filename before sending, so even immediate failures remain visible. */
  add(caseId: string, inputs: UploadInput[], initial = false): void {
    const pending = inputs.flatMap((input) => {
      if (!input.file) return [];
      const id = input.requestId ?? this.newId();
      this.inputs.set(id, { ...input, requestId: id });
      return [{ id, caseId, name: input.file.name, size: input.file.size, kind: input.kind,
        note: input.note, state: "queued" as const, message: null, hasFile: true, initial, pending: initial }];
    });
    this.rows = [...this.rows, ...pending];
    this.publish();
    for (const row of pending) void this.attempt(row.id);
  }

  /** Reconcile with the server after reload, a lost response, or a skip on another device. */
  syncInitial(caseId: string, items: InitialUpload[]): void {
    for (const item of items) {
      const current = this.rows.find((r) => r.caseId === caseId && r.id === item.request_id);
      // An older GET must not undo an upload or skip that just completed locally.
      if (item.state === "pending" && current && ["queued", "uploading", "saved", "skipping", "skipped"].includes(current.state)) continue;
      const state = item.state === "accepted" ? "saved" : item.state === "skipped" ? "skipped"
        : item.read_error ? "unreadable" : current?.state ?? "interrupted";
      const storedOnly = item.kind === "video" || item.kind === "call_recording";
      const row: UploadRow = {
        id: item.request_id, caseId, name: item.filename, size: item.size, kind: item.kind,
        note: item.note ?? undefined, initial: true, pending: item.state === "pending", state,
        evidenceId: item.evidence_id ?? undefined, hasFile: false,
        message: item.state === "accepted" ? (storedOnly ? "File saved; automatic analysis of this media is not available yet." : "File added and text read.")
          : item.state === "skipped" ? "Continuing without this file. It has not cleared any checks."
          : item.read_error ?? current?.message ?? "Select this file to retry, or continue without it. The case remains open.",
      };
      this.rows = current ? this.rows.map((r) => r === current ? row : r) : [...this.rows, row];
    }
    this.publish();
  }

  /** The student's explicit choice releases one initial-file hold; a network error does not. */
  async continueWithout(id: string): Promise<void> {
    const row = this.rows.find((r) => r.id === id);
    if (!row?.pending || !this.skip || ["queued", "uploading", "skipping"].includes(row.state)) return;
    this.update(id, { state: "skipping", message: "Saving your choice…" });
    try {
      this.syncInitial(row.caseId, await this.skip(row.caseId, id));
    } catch {
      this.update(id, { state: row.state, message: "Could not confirm your choice. The case stays open; try Continue without this file again." });
    }
  }

  /** Retry one attachment without resending successful neighbours. */
  async retry(id: string, file?: File, studentName = "student"): Promise<void> {
    const row = this.rows.find((r) => r.id === id);
    if (!row || ["saved", "uploading", "queued", "skipping", "skipped"].includes(row.state)) return;
    this.inputs.delete(id); // Every retry requires the student's fresh file selection.
    if (file) {
      if (file.name !== row.name || file.size !== row.size) {
        this.update(id, { message: "Select the original file to retry. For a replacement, use Add more below first, then continue without the original file." });
        return;
      }
      this.inputs.set(id, { kind: row.kind, note: row.note, file, studentName, requestId: id, retryRead: true });
    }
    if (!this.inputs.get(id)?.file) {
      this.update(id, { hasFile: false, message: "Select the same file again to retry this upload." });
      return;
    }
    await this.attempt(id);
  }

  private async attempt(id: string): Promise<void> {
    const row = this.rows.find((r) => r.id === id);
    const input = this.inputs.get(id);
    if (!row || !input) return;
    this.update(id, { state: "uploading", message: null, hasFile: true });
    try {
      const receipt = await this.send(row.caseId, input);
      const storedOnly = input.kind === "video" || input.kind === "call_recording";
      this.update(id, { state: receipt.read_error ? "unreadable" : "saved", evidenceId: receipt.evidence_id,
        message: receipt.read_error ?? (storedOnly ? "File saved; automatic analysis of this media is not available yet." : "File added and text read."),
        hasFile: false, pending: row.initial && !!receipt.read_error });
      this.inputs.delete(id);
    } catch (error) {
      const status = error && typeof error === "object" && "status" in error ? error.status : undefined;
      const message = status === 409
        ? error instanceof Error && !/decided/i.test(error.message) ? error.message
          : "This case has a final decision, so this file could not be added. Your other uploads are kept."
        : status === 413 ? "This file is too large. Add a smaller file instead. Your other uploads are kept."
        : status === 415 || status === 422 ? "This file could not be accepted. Check its format and add a supported file. Your other uploads are kept."
        : status === 404 ? "This case could not be found. Return to Cases and open it again before retrying."
        : "This upload could not be confirmed. Your other uploads are kept. Retry this file when the connection is available.";
      this.inputs.delete(id);
      this.update(id, { state: "failed", message, hasFile: false });
    }
  }
}

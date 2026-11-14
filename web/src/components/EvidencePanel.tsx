"use client";

import { useState } from "react";
import type { Case, EvidenceKind } from "@/lib/types";
import type { UploadInput } from "@/lib/api";
import { EVIDENCE_KIND_LABELS } from "@/lib/labels";
import { STUDENT_NAME_KEY } from "@/lib/config";

interface Props {
  caseData: Case;
  disabled: boolean;
  onUpload: (input: UploadInput) => Promise<unknown> | void;
}

export function EvidencePanel({ caseData, disabled, onUpload }: Props) {
  const [kind, setKind] = useState<EvidenceKind>("chat_export");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file && !text.trim()) {
      setMessage("Add a file or paste some text first.");
      return;
    }
    setMessage(null);
    let studentName = "student";
    try {
      studentName = localStorage.getItem(STUDENT_NAME_KEY) || "student";
    } catch {
      // localStorage unavailable: keep the fallback
    }
    setUploading(true);
    try {
      await onUpload({ kind, file, text: text.trim() || undefined, note: note.trim() || undefined, studentName });
      // NOTE: the hook swallows errors into the error banner, so this clears even after a failed upload.
      setFile(null);
      setFileKey((k) => k + 1);
      setText("");
      setNote("");
    } finally {
      setUploading(false);
    }
  }

  const evidence = [...(caseData.evidence ?? [])].reverse(); // NOTE: assumes stored order is oldest first
  const off = disabled || uploading;

  return (
    <section>
      <h2>Evidence</h2>
      <form onSubmit={submit}>
        <label htmlFor="ev-kind">Kind</label>
        <select id="ev-kind" value={kind} disabled={off} onChange={(e) => setKind(e.target.value as EvidenceKind)}>
          {(Object.keys(EVIDENCE_KIND_LABELS) as EvidenceKind[]).map((k) => (
            <option key={k} value={k}>{EVIDENCE_KIND_LABELS[k]}</option>
          ))}
        </select>
        <label htmlFor="ev-file">File</label>
        <input
          id="ev-file"
          key={fileKey}
          type="file"
          disabled={off}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <label htmlFor="ev-text">Or paste text</label>
        <textarea id="ev-text" value={text} disabled={off} onChange={(e) => setText(e.target.value)} />
        <label htmlFor="ev-note">Note</label>
        <input id="ev-note" value={note} disabled={off} onChange={(e) => setNote(e.target.value)} />
        {message && <p className="error" role="alert">{message}</p>}
        <button type="submit" disabled={off}>{uploading ? "Uploading…" : "Upload"}</button>
      </form>
      <h3>Uploaded</h3>
      {evidence.length === 0 && <p className="muted">Nothing uploaded yet.</p>}
      {evidence.map((ev) => {
        const extracted = ev.extracted_text ? String(ev.extracted_text).slice(0, 120) : "(no text extracted yet)";
        return (
          <div className="card" key={ev.id} style={{ marginBottom: 8 }}>
            <span className="tag">{EVIDENCE_KIND_LABELS[ev.kind as EvidenceKind] ?? ev.kind}</span>
            <strong>{ev.filename || "(pasted)"}</strong>
            <div className="muted">{ev.uploaded_at ? new Date(String(ev.uploaded_at)).toLocaleString() : ""}</div>
            <div>{extracted}</div>
          </div>
        );
      })}
    </section>
  );
}

"use client";

import type { UploadRow } from "@/lib/uploadQueue";
import { Collapsible } from "./primitives";

const LABELS = {
  queued: "Waiting to upload", uploading: "Uploading and reading…", saved: "Added",
  unreadable: "Saved, but could not read", failed: "Upload not confirmed", interrupted: "Upload interrupted",
  skipping: "Saving your choice…", skipped: "Skipped by you",
};

/** A persistent, filename-specific result instead of a failure lost during navigation. */
export function UploadStatus({ rows, onRetry, onSkip, defaultOpen = false }: {
  rows: UploadRow[]; onRetry: (id: string, file: File) => void; onSkip: (id: string) => void;
  /** Collapsed by default: only the header, a file count and a chevron show. */
  defaultOpen?: boolean;
}) {
  if (!rows.length) return null;
  const failures = rows.some((r) => ["failed", "interrupted", "unreadable"].includes(r.state));
  const attention = rows.filter((r) => ["failed", "interrupted", "unreadable"].includes(r.state)).length;
  const count = `${rows.length} file${rows.length === 1 ? "" : "s"}${attention ? ` · ${attention} need${attention === 1 ? "s" : ""} attention` : ""}`;
  return (
    <section aria-label="Attachment uploads" className="rounded-[20px] border border-line bg-white/90 p-5">
      <Collapsible
        as="h2"
        defaultOpen={defaultOpen}
        count={count}
        title="Your attachments"
        titleClassName="text-[17px] font-medium"
        description={failures ? "Some files need attention. Your successful uploads are kept." : "Each file is listed here as it is added."}
      >
      {rows.some((r) => r.pending) && <p className="mt-3 text-[13px] text-ink/80">
        Retry each file that needs attention, or continue without it. Your other files are already being checked.
        {failures && " For a different file, add the replacement using Add more below first, then continue without the original."}
      </p>}
      <ul className="mt-3 space-y-3" aria-live="polite" aria-relevant="additions text">
        {rows.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center gap-3 rounded-xl bg-field px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13.5px] font-medium" title={row.name}>{row.name}</p>
              <p className={`text-[12.5px] ${row.state === "saved" ? "text-[#1f7a60]" : "text-ink/75"}`}>{LABELS[row.state]}</p>
              {row.message && <p className="mt-1 text-[12.5px] text-muted">{row.message}</p>}
            </div>
            {["failed", "interrupted", "unreadable"].includes(row.state) && <>
              <label className="cursor-pointer rounded-full border border-line bg-white px-4 py-2 text-[13px] font-medium text-teal focus-within:ring-2 focus-within:ring-teal">
                Retry — select file
                <input type="file" className="sr-only" aria-label={`Select ${row.name} to retry`}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    if (file) onRetry(row.id, file);
                    event.currentTarget.value = ""; // the same file can be picked again
                  }} />
              </label>
              {row.pending && <button type="button" onClick={() => onSkip(row.id)}
                aria-label={`Continue without ${row.name}`}
                className="cursor-pointer rounded-full border border-line bg-white px-4 py-2 text-[13px] text-ink/75">
                Continue without this file
              </button>}
            </>}
          </li>
        ))}
      </ul>
      </Collapsible>
    </section>
  );
}

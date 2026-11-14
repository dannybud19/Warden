"use client";

import type { Case, StreamEvent } from "@/lib/types";

export function DebugPanel({ caseData, events }: { caseData: Case; events: StreamEvent[] }) {
  return (
    <details>
      <summary>Debug</summary>
      <h3>Last events (newest first)</h3>
      <pre>{JSON.stringify(events, null, 2)}</pre>
      <h3>Case</h3>
      <pre>{JSON.stringify(caseData, null, 2)}</pre>
    </details>
  );
}

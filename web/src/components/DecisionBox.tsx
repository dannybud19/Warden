"use client";

import { VERDICT_LABELS } from "@/lib/labels";
import type { Decision, Verdict } from "@/lib/types";

export function DecisionBox({ decision }: { decision: Decision }) {
  const reasons = decision.reasons ?? [];
  const verdict = decision.verdict as Verdict;
  const decidedAt = decision.decided_at ? new Date(decision.decided_at).toLocaleString() : "";
  return (
    <section className={`card verdict-${verdict}`}>
      <h2>{VERDICT_LABELS[verdict] ?? String(verdict)}</h2>
      <p>{decision.summary ?? ""}</p>
      {reasons.length > 0 && (
        <ul>
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {decidedAt && <p className="muted">Live assessment, updated {decidedAt}</p>}
    </section>
  );
}

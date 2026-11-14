"use client";

import type { Case, CheckId, Severity } from "@/lib/types";
import { AGENT_LABELS, CHECK_LABELS, CHECK_ORDER, SEVERITY_LABELS } from "@/lib/labels";
import { findingsByCheck } from "@/lib/selectors";

export function FindingsList({ caseData }: { caseData: Case }) {
  const byCheck = findingsByCheck(caseData);
  const groups = CHECK_ORDER.filter((id: CheckId) => (byCheck[id] ?? []).length > 0);

  return (
    <section>
      <h2>Findings</h2>
      {groups.length === 0 && <p className="muted">No findings yet. Upload something the agent sent you.</p>}
      {groups.map((id) => (
        <div key={id}>
          <h3 id={`findings-${id}`}>{CHECK_LABELS[id]}</h3>
          {byCheck[id].map((f) => (
            <div className="card" key={f.id} style={{ marginBottom: 8 }}>
              <span className={`sev-${f.severity}`}>{SEVERITY_LABELS[f.severity as Severity] ?? f.severity}</span>{" "}
              <strong>{f.title}</strong>
              <div>
                <span className="tag">{AGENT_LABELS[f.agent] ?? f.agent}</span>
                <span className="tag">
                  {(f.supports ?? "suspicious") === "cleared" ? "supports: verified" : "supports: red flag"}
                </span>
                {(f.hard_flag ?? false) && <span className="tag state-suspicious">HARD FLAG</span>}
                <span className="tag">{Math.round((f.confidence ?? 0) * 100)}%</span>
              </div>
              <p>{f.detail}</p>
              {(f.evidence ?? []).map((ref, i) => (
                <blockquote key={i}>
                  {ref.quote ? String(ref.quote) : "(no quote)"}
                  <div className="muted">evidence: {ref.evidence_id}</div>
                </blockquote>
              ))}
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

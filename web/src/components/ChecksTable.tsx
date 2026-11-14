"use client";

import type { Case, CheckState } from "@/lib/types";
import { CHECK_LABELS, CHECK_ORDER, CHECK_STATE_LABELS } from "@/lib/labels";
import { contributions } from "@/lib/selectors";

export function ChecksTable({ caseData }: { caseData: Case }) {
  const checks = caseData.checks ?? [];
  const points = contributions(caseData);

  function scrollTo(checkId: string) {
    document.getElementById(`findings-${checkId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <section>
      <h2>Checks</h2>
      <table>
        <thead>
          <tr><th>Check</th><th>State</th><th>Reason</th><th>Points</th></tr>
        </thead>
        <tbody>
          {CHECK_ORDER.map((id) => {
            const check = checks.find((c) => c.id === id);
            const state = (check?.state ?? "unverified") as CheckState;
            return (
              <tr key={id} className={`state-${state}`} style={{ cursor: "pointer" }} onClick={() => scrollTo(id)}>
                <td>{CHECK_LABELS[id]}</td>
                <td>{CHECK_STATE_LABELS[state]}</td>
                <td>{check?.reason ? String(check.reason) : ""}</td>
                <td>{(points[id] ?? 0).toFixed(1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

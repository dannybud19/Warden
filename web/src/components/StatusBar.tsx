"use client";

import type { AgentUiStatus, Case, ConnectionState } from "@/lib/types";
import { AGENT_LABELS, AGENT_ORDER, AGENT_STATUS_LABELS, scoreBand } from "@/lib/labels";
import { allFindings, currentScore } from "@/lib/selectors";

interface Props {
  caseData: Case;
  agentStatus: Record<string, AgentUiStatus>;
  connection: ConnectionState;
  onRefresh: () => void;
}

export function StatusBar({ caseData, agentStatus, connection, onRefresh }: Props) {
  const score = currentScore(caseData);
  const redFlags = allFindings(caseData).filter(
    (f) =>
      (f.supports ?? "suspicious") === "suspicious" &&
      ["critical", "high", "medium"].includes(f.severity),
  ).length;

  return (
    <section>
      <div className="score">{Math.round(score)}</div>
      <p>
        <strong>{scoreBand(score)}</strong>
        <span className="muted"> · case {caseData.status ?? "open"} · </span>
        <span>{redFlags} red flag{redFlags === 1 ? "" : "s"}</span>
        <span className="muted"> · connection: {connection}</span>
        <button type="button" className="secondary" onClick={onRefresh}>Refresh</button>
      </p>
      <table>
        <tbody>
          {AGENT_ORDER.map((name) => {
            const status = agentStatus[name] ?? "idle";
            const err = caseData.reports?.[name]?.error;
            return (
              <tr key={name}>
                <td>{AGENT_LABELS[name] ?? name}</td>
                <td title={err ? String(err) : undefined}>{AGENT_STATUS_LABELS[status]}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

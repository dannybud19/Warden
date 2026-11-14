import type { Case, Finding, Action, CheckId } from "./types";

export const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;

export function currentScore(c: Case): number {
  const history = c.score_history ?? [];
  return history.length ? history[history.length - 1].score : 100;
}

export function contributions(c: Case): Record<string, number> {
  const history = c.score_history ?? [];
  return history.length ? (history[history.length - 1].contributions as Record<string, number>) : {};
}

/** Every finding from every report (incl. reports["crosscheck"]), de-duplicated by id. */
export function allFindings(c: Case): Finding[] {
  const seen = new Map<string, Finding>();
  for (const report of Object.values(c.reports ?? {})) {
    for (const f of report.findings ?? []) seen.set(f.id, f);
  }
  return [...seen.values()].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity as never) - SEVERITY_ORDER.indexOf(b.severity as never),
  );
}

export function findingsByCheck(c: Case): Record<CheckId, Finding[]> {
  const out = {} as Record<CheckId, Finding[]>;
  for (const f of allFindings(c)) {
    const key = f.check_id as CheckId;
    (out[key] ??= []).push(f);
  }
  return out;
}

export function openActions(c: Case): Action[] {
  return (c.actions ?? []).filter((a) => (a.status ?? "open") === "open");
}

export function closedActions(c: Case): Action[] {
  return (c.actions ?? []).filter((a) => (a.status ?? "open") !== "open");
}

export function isDecided(c: Case): boolean {
  return c.status === "decided";
}

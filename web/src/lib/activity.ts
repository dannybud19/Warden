import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "./api";
import * as demo from "./demo";
import type { Action, Case } from "./types";
import { agentRows, whyAsk, type Tone } from "./present";
import { openActions } from "./selectors";
import { AGENTS_FOR } from "./dashboard";
import { VERDICT_LABELS } from "./labels";
import {
  SAMPLE_HOMES, caseToHome, parseIds, sortByNeed, useRememberedCaseIdsRaw, type Home,
} from "./homes";

// Agent activity across every home: powers the Inbox.

export const AGENT_PROFILE: Record<string, { name: string; icon: string; role: string }> = {
  warden: { name: "Warden", icon: "/warden/mascot.png", role: "Your lead agent" },
  companies_house: { name: "Agency checker", icon: "/warden/agent-agency.png", role: "Companies House" },
  message_checker: { name: "Chat reader", icon: "/warden/agent-chat.png", role: "Reads your chats" },
  emotion_classifier: { name: "Pressure spotter", icon: "/warden/agent-pressure.png", role: "Tone of your chats" },
  contract_checker: { name: "Contract reader", icon: "/warden/agent-contract.png", role: "Reads the contract" },
  video_analysis: { name: "Video checker", icon: "/warden/agent-video.png", role: "Viewing videos" },
};

export type ActivityStatus = "needs_you" | "done" | "waiting" | "checking" | "error";

export interface Activity {
  id: string;
  caseId: string;
  agent: string;
  status: ActivityStatus;
  line: string;
  tone: Tone;
  at: string;
  home: Home;
  action?: Action;
  why?: string;
}

const CHIP_TO_STATUS = { done: "done", waiting: "waiting", checking: "checking", error: "error" } as const;

/** Everything one case's agents have done, newest information first. */
export function activityFromCase(c: Case, home: Home): Activity[] {
  const evidence = [...(c.evidence ?? [])].sort((a, b) => a.uploaded_at.localeCompare(b.uploaded_at));
  const firstFeed = (agent: string) => evidence.find((e) => AGENTS_FOR[e.kind]?.includes(agent))?.uploaded_at;
  const out: Activity[] = agentRows(c, {}).map((r) => ({
    id: `${c.case_id}:${r.name}`,
    caseId: c.case_id,
    agent: r.name,
    status: CHIP_TO_STATUS[r.chip],
    line: r.line,
    tone: r.tone,
    at: (r.chip === "done" && firstFeed(r.name)) || c.created_at,
    home,
  }));
  for (const a of openActions(c)) {
    out.push({
      id: `${c.case_id}:action:${a.id}`, caseId: c.case_id, agent: "warden", status: "needs_you",
      line: a.text, tone: "red", at: a.asked_at ?? c.created_at, home, action: a, why: whyAsk(a),
    });
  }
  if (c.decision) {
    out.push({
      id: `${c.case_id}:decision`, caseId: c.case_id, agent: "warden", status: "done",
      line: VERDICT_LABELS[c.decision.verdict], tone: c.decision.verdict === "likely_scam" ? "red" : c.decision.verdict === "not_verified" ? "amber" : "green",
      at: c.decision.decided_at ?? c.created_at, home,
    });
  }
  return out;
}

// ---- Sample activity for the design's sample homes (shown until the student opens a case) ----

type Seed = [agent: string, status: ActivityStatus, line: string, tone: Tone, at: string];

const SAMPLE_SEEDS: Record<string, Seed[]> = {
  "sample-canal-wharf": [
    ["warden", "needs_you", "Ask who owns the flat and how Bowline Homes is connected?", "red", "2026-11-14T12:40:00Z"],
    ["companies_house", "done", "Bowline Homes is registered and 4 years old", "green", "2026-11-14T11:02:00Z"],
    ["message_checker", "done", "Agent won't say who the landlord is", "amber", "2026-11-14T12:31:00Z"],
    ["emotion_classifier", "done", "Nothing pushy in the chats", "green", "2026-11-14T12:31:00Z"],
    ["contract_checker", "waiting", "Upload the contract to run this", "grey", "2026-11-14T11:00:00Z"],
  ],
  "sample-albion-square": [
    ["companies_house", "done", "Hartwell & Rowe has been active since 2009", "green", "2026-11-13T16:20:00Z"],
    ["contract_checker", "done", "Deposit goes into the DPS scheme", "green", "2026-11-13T17:05:00Z"],
    ["emotion_classifier", "done", "No pressure tactics found", "green", "2026-11-13T17:01:00Z"],
    ["message_checker", "done", "Viewing booked in person for Saturday", "green", "2026-11-13T17:01:00Z"],
  ],
  "sample-rye-lane": [
    ["message_checker", "done", "They asked for the deposit in cash", "amber", "2026-11-13T19:45:00Z"],
    ["companies_house", "done", "Rye Rooms Co is registered", "green", "2026-11-13T19:10:00Z"],
    ["video_analysis", "waiting", "Upload a viewing video to run this", "grey", "2026-11-13T19:10:00Z"],
  ],
  "sample-holloway-road": [
    ["companies_house", "checking", "Checking now…", "grey", "2026-11-14T13:58:00Z"],
    ["message_checker", "checking", "Checking now…", "grey", "2026-11-14T13:58:00Z"],
  ],
};

function sampleActivity(): Activity[] {
  const out: Activity[] = activityFromCase(demo.getCase(), SAMPLE_HOMES[0]);
  for (const home of SAMPLE_HOMES.slice(1)) {
    for (const [agent, status, line, tone, at] of SAMPLE_SEEDS[home.id] ?? []) {
      out.push({ id: `${home.id}:${agent}:${status}`, caseId: home.id, agent, status, line, tone, at, home });
    }
  }
  return out;
}

// ---- Hook: every home this browser knows about, and their agents' activity ----

export function useWardenData() {
  const key = parseIds(useRememberedCaseIdsRaw()).join(",");
  const [load, setLoad] = useState<{ key: string; tick: number; cases: Case[] } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    Promise.allSettled(key.split(",").map((id) => api.getCase(id))).then((results) => {
      if (cancelled) return;
      setLoad({ key, tick, cases: results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : [])) });
    });
    return () => {
      cancelled = true;
    };
  }, [key, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  return useMemo(() => {
    const samples = { homes: SAMPLE_HOMES, items: sampleActivity(), loading: false, sample: true, refresh };
    if (!key) return samples;
    if (!load || load.key !== key) return { homes: [] as Home[], items: [] as Activity[], loading: true, sample: false, refresh };
    if (!load.cases.length) return samples;
    const homes = load.cases.map(caseToHome);
    const items = load.cases.flatMap((c, i) => activityFromCase(c, homes[i]));
    return { homes: sortByNeed(homes), items, loading: false, sample: false, refresh };
    // `tick` re-reads the in-memory demo case after a skip
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, load, refresh, tick]);
}

export function shortWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London",
  });
}

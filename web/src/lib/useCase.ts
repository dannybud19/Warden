"use client";

import { useCallback, useEffect, useReducer } from "react";
import * as api from "./api";
import type {
  Case, StreamEvent, ConnectionState, AgentUiStatus, ChatEntry,
} from "./types";
import { AGENT_ORDER } from "./labels";

interface State {
  caseData: Case | null;
  agentStatus: Record<string, AgentUiStatus>;
  chat: ChatEntry[];
  events: StreamEvent[];          // last 20, newest first, for the debug panel
  connection: ConnectionState;
  error: string | null;
  busy: boolean;
}

type Act =
  | { t: "loaded"; caseData: Case }
  | { t: "event"; e: StreamEvent }
  | { t: "chat"; entry: ChatEntry }
  | { t: "connection"; s: ConnectionState }
  | { t: "error"; msg: string | null }
  | { t: "busy"; v: boolean };

const initial: State = {
  caseData: null, agentStatus: {}, chat: [], events: [],
  connection: "connecting", error: null, busy: false,
};

function statusFromCase(c: Case): Record<string, AgentUiStatus> {
  const out: Record<string, AgentUiStatus> = {};
  for (const name of AGENT_ORDER) out[name] = "idle";
  for (const [name, report] of Object.entries(c.reports ?? {})) {
    out[name] = report.status as AgentUiStatus;
  }
  return out;
}

function reducer(state: State, a: Act): State {
  switch (a.t) {
    case "loaded":
      return {
        ...state,
        caseData: a.caseData,
        // keep "running" chips that the server has not finished yet
        agentStatus: Object.fromEntries(
          Object.entries(statusFromCase(a.caseData)).map(([k, v]) => [
            k, state.agentStatus[k] === "running" && v === "idle" ? "running" : v,
          ]),
        ),
      };
    case "event": {
      const events = [a.e, ...state.events].slice(0, 20);
      if (a.e.type === "agent_started") {
        return { ...state, events, agentStatus: { ...state.agentStatus, [a.e.agent]: "running" } };
      }
      if (a.e.type === "agent_finished") {
        return {
          ...state, events,
          agentStatus: { ...state.agentStatus, [a.e.report.agent]: a.e.report.status as AgentUiStatus },
        };
      }
      if (a.e.type === "orchestrator_message") {
        return { ...state, events, chat: [...state.chat, { role: "orchestrator", text: a.e.text, at: new Date().toISOString() }] };
      }
      return { ...state, events };
    }
    case "chat":
      return { ...state, chat: [...state.chat, a.entry] };
    case "connection":
      return { ...state, connection: a.s };
    case "error":
      return { ...state, error: a.msg };
    case "busy":
      return { ...state, busy: a.v };
  }
}

const REFETCH_ON = new Set<StreamEvent["type"]>([
  "agent_finished", "score_updated", "actions_proposed", "decision_made",
]);

export function useCase(caseId: string) {
  const [state, dispatch] = useReducer(reducer, initial);

  const refresh = useCallback(async () => {
    try {
      dispatch({ t: "loaded", caseData: await api.getCase(caseId) });
      // NOTE: clear a stale "Failed to fetch" banner once a refetch (e.g. polling) succeeds again.
      dispatch({ t: "error", msg: null });
    } catch (e) {
      dispatch({ t: "error", msg: e instanceof Error ? e.message : String(e) });
    }
  }, [caseId]);

  // initial load + subscription
  useEffect(() => {
    void refresh();
    const unsubscribe = api.subscribe(
      caseId,
      (e) => {
        dispatch({ t: "event", e });
        if (REFETCH_ON.has(e.type)) void refresh();
      },
      (s) => dispatch({ t: "connection", s }),
    );
    return unsubscribe;
  }, [caseId, refresh]);

  // polling fallback
  useEffect(() => {
    if (state.connection !== "polling") return;
    const id = setInterval(() => void refresh(), 2000);
    return () => clearInterval(id);
  }, [state.connection, refresh]);

  const run = useCallback(async (fn: () => Promise<Case>) => {
    dispatch({ t: "busy", v: true });
    dispatch({ t: "error", msg: null });
    try {
      dispatch({ t: "loaded", caseData: await fn() });
    } catch (e) {
      dispatch({ t: "error", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      dispatch({ t: "busy", v: false });
    }
  }, []);

  const upload = useCallback(
    (input: api.UploadInput) => run(() => api.uploadEvidence(caseId, input)),
    [caseId, run],
  );

  const sendReply = useCallback(
    (input: api.ReplyInput) => {
      if (input.text) {
        dispatch({ t: "chat", entry: { role: "student", text: input.text, at: new Date().toISOString() } });
      }
      return run(() => api.reply(caseId, input));
    },
    [caseId, run],
  );

  return { state, refresh, upload, sendReply };
}

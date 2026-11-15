import { useCallback, useMemo } from "react";
import type { ChatEntry } from "./types";
import { useLocalJSON } from "./localStore";

// Separate conversations with Warden inside one home. Saved in this browser, per case.

export type Thread = {
  id: string;
  /** "Call · 14:05" for calls; otherwise derived from the first thing the student asked. */
  kind: "chat" | "call";
  startedAt: string;
  messages: ChatEntry[];
};

type Store = { activeId: string | null; threads: Thread[] };

const EMPTY: Store = { activeId: null, threads: [] };

function newId(): string {
  return `t_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

export function threadTitle(t: Thread): string {
  const time = new Date(t.startedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (t.kind === "call") return `Call · ${time}`;
  const first = t.messages.find((m) => m.role === "student")?.text.trim();
  if (!first) return t.messages.length ? `Chat · ${time}` : "New chat";
  return first.length > 38 ? `${first.slice(0, 36).trimEnd()}…` : first;
}

export function threadWhen(t: Thread): string {
  const last = t.messages[t.messages.length - 1]?.at ?? t.startedAt;
  const d = new Date(last);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** All of a home's conversations, the active one, and ways to add to them. */
export function useThreads(caseId: string) {
  const [store, setStore] = useLocalJSON<Store>(`warden.threads.${caseId}`, EMPTY);
  // the single chat from before conversations existed becomes the first one
  const [legacy, setLegacy] = useLocalJSON<ChatEntry[]>(`warden.chat.${caseId}`, []);

  const threads = useMemo(() => {
    if (store.threads.length || !legacy.length) return store.threads;
    return [{ id: "t_legacy", kind: "chat" as const, startedAt: legacy[0].at, messages: legacy }];
  }, [store.threads, legacy]);

  const active = threads.find((t) => t.id === store.activeId) ?? threads[threads.length - 1] ?? null;

  const save = useCallback(
    (next: Store) => {
      setStore(next);
      if (legacy.length) setLegacy([]);
    },
    [setStore, legacy.length, setLegacy],
  );

  /** Adds messages to the active conversation (starting one if there is none). */
  const append = useCallback(
    (entries: ChatEntry[]) => {
      if (!entries.length) return;
      if (!active) {
        const t: Thread = { id: newId(), kind: "chat", startedAt: entries[0].at, messages: entries };
        save({ activeId: t.id, threads: [...threads, t] });
        return;
      }
      save({
        activeId: active.id,
        threads: threads.map((t) => (t.id === active.id ? { ...t, messages: [...t.messages, ...entries].slice(-200) } : t)),
      });
    },
    [active, threads, save],
  );

  /** Starts a fresh conversation, reusing the current one if it's still empty. */
  const start = useCallback(
    (kind: Thread["kind"] = "chat") => {
      if (active && active.messages.length === 0) {
        save({ activeId: active.id, threads: threads.map((t) => (t.id === active.id ? { ...t, kind, startedAt: new Date().toISOString() } : t)) });
        return;
      }
      const t: Thread = { id: newId(), kind, startedAt: new Date().toISOString(), messages: [] };
      save({ activeId: t.id, threads: [...threads, t] });
    },
    [active, threads, save],
  );

  const open = useCallback((id: string) => save({ activeId: id, threads }), [threads, save]);

  const remove = useCallback(
    (id: string) => {
      const rest = threads.filter((t) => t.id !== id);
      save({ activeId: store.activeId === id ? rest[rest.length - 1]?.id ?? null : store.activeId, threads: rest });
    },
    [threads, store.activeId, save],
  );

  // newest first, for lists
  const list = useMemo(
    () => [...threads].sort((a, b) => (b.messages.at(-1)?.at ?? b.startedAt).localeCompare(a.messages.at(-1)?.at ?? a.startedAt)),
    [threads],
  );

  return { threads: list, active, append, start, open, remove };
}

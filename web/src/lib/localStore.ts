import { useCallback, useSyncExternalStore } from "react";

// Tiny localStorage-backed state shared across components (and tabs). Per-browser conveniences only.

const listeners = new Set<() => void>();

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

export function writeLocal(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep going without persistence */
  }
  listeners.forEach((l) => l());
  // other listeners (e.g. the nav's name hook) listen for "storage"
  window.dispatchEvent(new StorageEvent("storage", { key }));
}

/** JSON value in localStorage. Returns `fallback` on the server, when missing, or when unreadable. */
export function useLocalJSON<T>(key: string, fallback: T): [T, (next: T) => void] {
  const raw = useSyncExternalStore(subscribe, () => read(key), () => null);
  let value = fallback;
  if (raw) {
    try {
      value = JSON.parse(raw) as T;
    } catch {
      value = fallback;
    }
  }
  const set = useCallback((next: T) => writeLocal(key, JSON.stringify(next)), [key]);
  return [value, set];
}

/** Plain string value in localStorage. */
export function useLocalString(key: string): [string, (next: string) => void] {
  const raw = useSyncExternalStore(subscribe, () => read(key), () => null);
  const set = useCallback((next: string) => writeLocal(key, next.trim() ? next.trim() : null), [key]);
  return [raw ?? "", set];
}

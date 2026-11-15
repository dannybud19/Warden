"use client";

import { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { skipInitialUpload, uploadEvidenceReceipt } from "@/lib/api";
import { UploadQueue, type UploadRow } from "@/lib/uploadQueue";

const Context = createContext<UploadQueue | null>(null);
const EMPTY: UploadRow[] = [];

/** Stays mounted across navigation from New case to the case page. */
export function UploadProvider({ children }: { children: React.ReactNode }) {
  const [queue] = useState(() => new UploadQueue(uploadEvidenceReceipt, undefined, skipInitialUpload));
  useEffect(() => {
    try { queue.restore(sessionStorage); } catch { /* File uploads still work without storage. */ }
  }, [queue]);
  return <Context.Provider value={queue}>{children}</Context.Provider>;
}

export function useUploadQueue(): UploadQueue {
  const queue = useContext(Context);
  if (!queue) throw new Error("UploadProvider is missing");
  return queue;
}

export function useUploads(): { queue: UploadQueue; rows: UploadRow[] } {
  const queue = useUploadQueue();
  const rows = useSyncExternalStore(queue.subscribe, queue.getSnapshot, () => EMPTY);
  return { queue, rows };
}

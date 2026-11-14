import { useSyncExternalStore } from "react";
import type { Case } from "./types";
import { allFindings, openActions } from "./selectors";
import { DEMO_CASE_ID } from "./demo";

/** How a home reads at a glance. Verdicts map 1:1; "checking" means no verdict yet. */
export type HomeStatus = "likely_scam" | "not_verified" | "proceed_with_care" | "no_red_flags_remaining" | "checking";

export interface HomeStatusMeta {
  label: string;
  /** Hero summary chip, e.g. "2 don't pay yet". */
  countLabel: (n: number) => string;
  /** 8px dot asset from the design. */
  dot: string;
  /** Filled progress segment colour. */
  bar: string;
  /** Folder background gradient (top, bottom). */
  folder: [string, string];
  /** Lower ranks need the student first. */
  rank: number;
}

export const HOME_STATUS: Record<HomeStatus, HomeStatusMeta> = {
  likely_scam: {
    label: "Likely scam", countLabel: (n) => `${n} likely scam`, dot: "/warden/dot-red.svg",
    bar: "#e06a52", folder: ["#fbe6e1", "#f5d3ca"], rank: 0,
  },
  not_verified: {
    label: "Don't pay yet", countLabel: (n) => `${n} don't pay yet`, dot: "/warden/dot-amber.svg",
    bar: "#d99a2b", folder: ["#fbf2df", "#f3e3c2"], rank: 1,
  },
  proceed_with_care: {
    label: "Proceed with care", countLabel: (n) => `${n} proceed with care`, dot: "/warden/dot-green.svg",
    bar: "#2e9a7c", folder: ["#e0f4ec", "#c9eadd"], rank: 3,
  },
  no_red_flags_remaining: {
    label: "No red flags remaining", countLabel: (n) => `${n} no red flags remaining`, dot: "/warden/dot-green.svg",
    bar: "#2e9a7c", folder: ["#e0f4ec", "#c9eadd"], rank: 4,
  },
  checking: {
    label: "Checking", countLabel: (n) => `${n} checking`, dot: "/warden/dot-teal.svg",
    bar: "#138a93", folder: ["#ddf1f3", "#c4e6e9"], rank: 2,
  },
};

/** Display order of the hero summary chips. */
export const STATUS_ORDER: HomeStatus[] = [
  "likely_scam", "not_verified", "proceed_with_care", "no_red_flags_remaining", "checking",
];

export interface Home {
  id: string;
  /** Where "Open" goes. */
  href: string;
  title: string;
  /** e.g. "E1 · £1,150 pcm · Quickkeys Lettings" */
  meta: string;
  platform: string | null;
  status: HomeStatus;
  needsYou: boolean;
  checked: number;
  total: number;
  redFlags: string[];
  /** What the mascot says about this home on the dashboard. */
  nudge: string | null;
  photos: { front: string; back: string };
}

const PHOTO_SETS: Home["photos"][] = [
  { front: "/warden/photo-mile-end-front.png", back: "/warden/photo-mile-end-back.png" },
  { front: "/warden/photo-canal-front.png", back: "/warden/photo-interior-a.png" },
  { front: "/warden/photo-albion-front.png", back: "/warden/photo-interior-b.png" },
  { front: "/warden/photo-interior-b.png", back: "/warden/photo-interior-a.png" },
  { front: "/warden/photo-interior-a.png", back: "/warden/photo-interior-b.png" },
];

/** Sample homes from the hi-fi design, shown until the student has opened a case of their own. */
export const SAMPLE_HOMES: Home[] = [
  {
    id: DEMO_CASE_ID, href: `/case/${DEMO_CASE_ID}`, title: "Flat 2, 41 Mile End Road",
    meta: "E1 · £1,150 pcm · Quickkeys Lettings", platform: "SpareRoom", status: "likely_scam",
    needsYou: true, checked: 5, total: 8,
    redFlags: [
      "They asked for money before a viewing",
      "The agency isn't on the official register",
      "The landlord says they're abroad",
    ],
    nudge: "They asked for money before you've seen it. I'd hold off.",
    photos: PHOTO_SETS[0],
  },
  {
    id: "sample-canal-wharf", href: `/case/${DEMO_CASE_ID}`, title: "Apt 14, Canal Wharf",
    meta: "E3 · £1,395 pcm · Bowline Homes", platform: null, status: "not_verified",
    needsYou: true, checked: 4, total: 8, redFlags: [], nudge: null, photos: PHOTO_SETS[1],
  },
  {
    id: "sample-albion-square", href: `/case/${DEMO_CASE_ID}`, title: "28 Albion Square",
    meta: "N1 · £1,250 pcm · Hartwell & Rowe", platform: null, status: "proceed_with_care",
    needsYou: false, checked: 7, total: 8, redFlags: [], nudge: null, photos: PHOTO_SETS[2],
  },
  {
    id: "sample-rye-lane", href: `/case/${DEMO_CASE_ID}`, title: "Room 3, 9 Rye Lane",
    meta: "SE15 · £780 pcm · Rye Rooms Co", platform: null, status: "not_verified",
    needsYou: false, checked: 5, total: 8, redFlags: [], nudge: null,
    photos: { front: "/warden/photo-interior-b.png", back: "/warden/photo-interior-a.png" },
  },
  {
    id: "sample-holloway-road", href: `/case/${DEMO_CASE_ID}`, title: "Studio, 63 Holloway Road",
    meta: "N7 · £1,020 pcm · Checking now", platform: null, status: "checking",
    needsYou: false, checked: 2, total: 8, redFlags: [], nudge: null,
    photos: { front: "/warden/photo-interior-a.png", back: "/warden/photo-interior-b.png" },
  },
];

/** "Flat 3, 12 Elm Road, London W12 8QT" -> "Flat 3, 12 Elm Road" */
export function shortAddress(address: string | null | undefined): string {
  if (!address) return "Untitled home";
  return address.split(/,\s*London\b/i)[0].trim() || address;
}

export function formatRent(rent: number | null | undefined): string | null {
  return rent == null ? null : `£${rent.toLocaleString("en-GB")} pcm`;
}

export function caseToHome(c: Case, index: number): Home {
  const status: HomeStatus = c.decision?.verdict ?? "checking";
  const checks = c.checks ?? [];
  const outward = c.listing?.postcode?.split(" ")[0] ?? null;
  const who = c.landlord?.company_name ?? c.landlord?.name ?? null;
  const open = openActions(c);
  const flags = allFindings(c).filter((f) => f.supports === "suspicious");
  const title = shortAddress(c.listing?.address);
  return {
    id: c.case_id,
    href: `/case/${c.case_id}`,
    title,
    meta: [outward, formatRent(c.listing?.rent_pcm), who ?? (status === "checking" ? "Checking now" : null)]
      .filter(Boolean)
      .join(" · "),
    platform: c.listing?.platform ?? null,
    status,
    needsYou: open.length > 0,
    checked: checks.filter((k) => k.state !== "unverified").length,
    total: checks.length || 8,
    redFlags: flags.slice(0, 3).map((f) => f.title),
    nudge: open[0]?.text ?? (flags[0] ? `${title}: ${flags[0].title.toLowerCase()}. I'd hold off.` : null),
    photos: PHOTO_SETS[index % PHOTO_SETS.length],
  };
}

export function sortByNeed(homes: Home[]): Home[] {
  return [...homes].sort(
    (a, b) => Number(b.needsYou) - Number(a.needsYou) || HOME_STATUS[a.status].rank - HOME_STATUS[b.status].rank,
  );
}

// ---- Cases this browser has opened (there is no "list cases" endpoint) ----

const KEY = "warden.caseIds";
const listeners = new Set<() => void>();

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? "[]";
  } catch {
    return "[]";
  }
}

export function rememberCase(caseId: string): void {
  try {
    const ids = JSON.parse(read()) as string[];
    if (!ids.includes(caseId)) localStorage.setItem(KEY, JSON.stringify([caseId, ...ids]));
  } catch {
    /* storage unavailable: the home list falls back to samples */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

/** Raw JSON string so the snapshot is referentially stable; parse it with `parseIds`. */
export function useRememberedCaseIdsRaw(): string {
  return useSyncExternalStore(subscribe, read, () => "[]");
}

export function parseIds(raw: string): string[] {
  try {
    const v = JSON.parse(raw) as unknown;
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

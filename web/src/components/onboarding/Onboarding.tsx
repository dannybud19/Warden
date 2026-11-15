"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import * as api from "@/lib/api";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { rememberCase } from "@/lib/homes";
import { writeLocal } from "@/lib/localStore";
import type { EvidenceKind } from "@/lib/types";
import {
  startWardenOnboarding, type CaseAnswers, type OnboardingFiles, type ProfileAnswers, type UploadKey,
} from "./onboarding-engine";
import "./onboarding.css";

const ICON_NAMES = ["warden", "alert", "checklist", "notes", "shield", "chat", "gauge", "doc", "camera", "search"];
const ICONS = Object.fromEntries(ICON_NAMES.map((n) => [n, `/warden/icons/${n}.webp`]));

/** Loads the <warden-mascot> web component once. */
function loadMascot(): Promise<void> {
  if (typeof window === "undefined" || customElements.get("warden-mascot")) return Promise.resolve();
  const existing = document.querySelector<HTMLScriptElement>('script[src="/warden/warden-mascot.js"]');
  if (existing) return customElements.whenDefined("warden-mascot").then(() => undefined);
  return new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = "/warden/warden-mascot.js";
    s.onload = () => res();
    s.onerror = rej;
    document.head.appendChild(s);
  });
}

function readName(): string {
  try {
    return localStorage.getItem(STUDENT_NAME_KEY) ?? "";
  } catch {
    return "";
  }
}

const FILE_KIND: Record<UploadKey, (f: File) => EvidenceKind> = {
  messages: (f) => (f.type.startsWith("image/") ? "chat_screenshot" : "chat_export"),
  contract: () => "contract",
  video: () => "video",
  emails: () => "email",
  payment: () => "document",
};

const PROFILE_KEY = "warden.profile";
export const ONBOARDED_KEY = "warden.onboarded";

function readProfile(): Partial<ProfileAnswers> {
  try {
    return JSON.parse(localStorage.getItem(PROFILE_KEY) ?? "{}") as Partial<ProfileAnswers>;
  } catch {
    return {};
  }
}

/** What the student told Warden, kept on the case so the agents and the team can read it. */
function notesFrom(p: Partial<ProfileAnswers>, a: CaseAnswers): string {
  return [
    p.area && `Moving to: ${p.area}.`,
    p.moveIn && `Move-in date: ${p.moveIn}.`,
    p.firstTimeInUK !== undefined && `First time renting in the UK: ${p.firstTimeInUK ? "yes" : "no"}.`,
    a.seenInPerson && `Seen in person: ${a.seenInPerson.toLowerCase()}.`,
    a.askedToPay && `Asked to pay: ${a.askedToPay.toLowerCase()}.`,
    `Paid anything yet: ${a.paidAlready ? "yes" : "no"}.`,
  ]
    .filter(Boolean)
    .join(" ");
}

/** A full UK postcode found in free text (e.g. "… London E1 4AA"), formatted "E1 4AA", else undefined. */
function ukPostcode(text: string | undefined): string | undefined {
  const m = /\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b/i.exec(text ?? "");
  return m ? `${m[1]} ${m[2]}`.toUpperCase() : undefined;
}

function rentNumber(v: string): number | undefined {
  const n = Number(v.replace(/[£,\s]/g, "").replace(/pcm|pm|\/month/gi, ""));
  return v.trim() && Number.isFinite(n) && n > 0 ? n : undefined;
}

/** "onboarding": get to know the student, then show the empty dashboard. "newcase": check one place. */
export default function Onboarding({ mode = "onboarding" }: { mode?: "onboarding" | "newcase" }) {
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement>(null);
  // The panel glides to its new height between steps instead of jumping.
  const innerRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");
  useEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setHeight(Math.ceil(e.borderBoxSize?.[0]?.blockSize ?? el.offsetHeight)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let stop: (() => void) | undefined;
    let cancelled = false;

    async function finishOnboarding(p: ProfileAnswers) {
      if (p.name) writeLocal(STUDENT_NAME_KEY, p.name.split(/\s+/)[0]);
      writeLocal(PROFILE_KEY, JSON.stringify(p));
      writeLocal(ONBOARDED_KEY, "1");
      router.push("/");
    }

    async function finishCase(a: CaseAnswers, files: OnboardingFiles) {
      const profile = readProfile();
      const c = await api.openCase({
        student: { notes: notesFrom(profile, a) },
        listing: {
          url: a.listingUrl || undefined,
          platform: a.listingSite || undefined,
          address: a.address || undefined,
          postcode: ukPostcode(a.address),
          rent_pcm: rentNumber(a.rent),
        },
        // a company name or number starts the agency check as soon as the case opens
        landlord:
          a.agency || a.companyNumber || a.agentName
            ? { company_name: a.agency || undefined, company_number: a.companyNumber || undefined, name: a.agentName || undefined }
            : undefined,
      });
      if (!c.case_id) throw new Error("no case id");
      rememberCase(c.case_id);
      // Uploads run on after we navigate: the case page shows each agent's check land live.
      const studentName = (profile.name ?? readName()).split(/\s+/)[0] || "student";
      for (const [k, f] of Object.entries(files) as [UploadKey, File][]) {
        void api.uploadEvidence(c.case_id, { kind: FILE_KIND[k](f), file: f, studentName }).catch(() => {});
      }
      router.push(`/case/${c.case_id}`);
    }

    loadMascot().then(() => {
      if (cancelled || !rootRef.current) return;
      stop = startWardenOnboarding(rootRef.current, {
        mode,
        icons: ICONS,
        initialName: readName(),
        profile: readProfile(),
        onFinish: (answers, files) =>
          mode === "onboarding" ? finishOnboarding(answers as ProfileAnswers) : finishCase(answers as CaseAnswers, files),
        onCancel: mode === "newcase" ? () => router.push("/") : undefined,
        previewListing: mode === "newcase" ? api.previewListing : undefined,
      });
    });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [router, mode]);

  return (
    <div className="wd-onb" data-mood="calm" ref={rootRef}>
      <div className="stage">
        <div className="halo" />
        <warden-mascot id="w" state={mode === "onboarding" ? "wave" : "default"} assets="/warden/" />
        <div className="tag" id="tag" />
      </div>
      <div className="panel">
        <motion.div
          className="panel-size"
          initial={false}
          animate={{ height }}
          transition={{ type: "spring", stiffness: 260, damping: 32, mass: 0.8 }}
        >
          <div ref={innerRef}>
        <div className="progress" id="rail">
          <span className="dashes" id="dashes" />
          <span className="lbl" id="railLbl" />
        </div>
        <section className="talk" id="bubble" aria-live="polite">
          <h1 className="line" id="line" />
          <p className="sub" id="sub" />
        </section>
        <div className="form" id="form" />
          </div>
        </motion.div>
      </div>
    </div>
  );
}

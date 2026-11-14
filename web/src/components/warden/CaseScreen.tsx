"use client";

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { useCase } from "@/lib/useCase";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { isDecided, openActions } from "@/lib/selectors";
import { rememberCase } from "@/lib/homes";
import { DEMO_CASE_ID } from "@/lib/demo";
import { agentRows, answerSuggestion, mood, type Suggestion } from "@/lib/present";
import type { ChatEntry, EvidenceKind } from "@/lib/types";
import { Mascot, stagger } from "./primitives";
import { SiteNav } from "./SiteNav";
import { PixelField, type QuietZone } from "./PixelField";
import { AnswerCard, CheckMap, HomeHeader, StoryStrip } from "./Dashboard";
import { AgentsRail } from "./AgentsRail";

function studentName(): string {
  try {
    return localStorage.getItem(STUDENT_NAME_KEY) || "student";
  } catch {
    return "student";
  }
}

/** Keep the pixels light behind the dashboard, strong in the band above it and on the edges. */
const CONTENT_ZONE: QuietZone = (w) => {
  const half = Math.min(w, 1312) / 2;
  return [w / 2 - half, 110, w / 2 + half, 400];
};

function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-[240px] bg-[linear-gradient(to_bottom,#8fd3d8,#c6ebed_60%,#f5f8f9)]">
        <PixelField className="absolute inset-0 size-full" maxAlpha={0.38} quiet={CONTENT_ZONE} />
      </div>
      <div className="relative mx-auto h-full max-w-[1440px]">
        <div className="absolute left-[-170px] top-[510px] size-[640px]">
          <Image src="/warden/glow-bottom-left.svg" alt="" width={640} height={640} unoptimized className="block size-full" />
        </div>
      </div>
    </div>
  );
}

/** Figma "V4 · One home": left is the dashboard (facts + your decision), right is the agents. */
export function CaseScreen({ caseId }: { caseId: string }) {
  const { state, upload, sendReply } = useCase(caseId);
  const [local, setLocal] = useState<ChatEntry[]>([]);
  const c = state.caseData;

  useEffect(() => {
    if (c && caseId !== DEMO_CASE_ID) rememberCase(caseId);
  }, [c, caseId]);

  const onUpload = useCallback(
    (kind: EvidenceKind, file: File) => void upload({ kind, file, studentName: studentName() }),
    [upload],
  );

  const view = useMemo(() => {
    if (!c) return null;
    const rows = agentRows(c, state.agentStatus);
    const working = rows.some((r) => r.chip === "checking") || state.busy;
    return { rows, open: openActions(c), mood: mood(c, working) };
  }, [c, state.agentStatus, state.busy]);

  const chat = useMemo(
    () => [...state.chat, ...local].sort((a, b) => a.at.localeCompare(b.at)),
    [state.chat, local],
  );

  if (!c || !view) {
    return (
      <div className="relative min-h-dvh">
        <Backdrop />
        <div className="relative mx-auto max-w-[1440px] px-16 pt-4">
          <SiteNav />
          <div className="flex flex-col items-center pt-32 text-center">
            <Mascot width={110} height={132} float />
            <p className="mt-6 text-[22px] font-light tracking-[-0.44px]">
              {state.error ? "Warden couldn't open this home" : "Opening this home…"}
            </p>
            {state.error && (
              <>
                <p className="mt-2 max-w-[420px] text-[13px] text-muted">{state.error}</p>
                <Link href="/" className="mt-5 text-[13px] font-medium text-teal">←&nbsp;&nbsp;All homes</Link>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  const closed = isDecided(c);
  const action = view.open[0];

  function ask(q: Suggestion) {
    if (!c) return;
    const at = new Date().toISOString();
    setLocal((l) => [
      ...l,
      { role: "student", text: q, at },
      { role: "orchestrator", text: answerSuggestion(c, q), at: new Date(Date.parse(at) + 1).toISOString() },
    ]);
  }

  return (
    <div className="relative min-h-dvh overflow-hidden">
      <Backdrop />
      <div className="relative mx-auto max-w-[1440px] px-16 pb-10 pt-4">
        <SiteNav />

        <div className="mt-4 grid grid-cols-[minmax(0,888fr)_minmax(0,408fr)] items-start gap-4">
          <motion.main variants={stagger} initial="hidden" animate="show" className="flex min-w-0 flex-col gap-4">
            <div className="flex items-center gap-8 pt-7">
              <Link href="/" className="group inline-flex text-[13px] text-ink/60 hover:text-teal">
                <span className="inline-block transition-transform group-hover:-translate-x-1">←</span>&nbsp;&nbsp;All homes
              </Link>
              <span className="text-[10.5px] font-semibold tracking-[1.2px] text-teal">DASHBOARD</span>
            </div>
            {state.error && (
              <p role="alert" className="rounded-[16px] bg-[#fbe6e1] px-4 py-3 text-[13px] text-[#a8402b]">{state.error}</p>
            )}
            <HomeHeader c={c} mood={view.mood} caseId={caseId} photo={caseId === DEMO_CASE_ID ? "/warden/photo-mile-end-front.png" : null} />
            <AnswerCard c={c} mood={view.mood} caseId={caseId} />
            <CheckMap c={c} disabled={closed || state.busy} onUpload={onUpload} />
            <StoryStrip c={c} />
          </motion.main>

          <div className="sticky top-4">
            <AgentsRail
              mood={view.mood}
              action={action}
              rows={view.rows}
              chat={chat}
              busy={state.busy}
              canReply={!closed && view.open.length > 0}
              closed={closed}
              onSkip={() => action && void sendReply({ text: "Skip for now", actionId: action.id, status: "skipped" })}
              onAsk={ask}
              onSend={(text) => void sendReply({ text })}
              onUpload={onUpload}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

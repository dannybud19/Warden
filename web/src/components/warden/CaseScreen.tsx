"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { useCase } from "@/lib/useCase";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { isDecided, openActions } from "@/lib/selectors";
import { rememberCase, shortAddress } from "@/lib/homes";
import { useLocalJSON } from "@/lib/localStore";
import { DEMO_CASE_ID } from "@/lib/demo";
import { agentRows, answerSuggestion, mood, redFlags, type Suggestion } from "@/lib/present";
import type { ChatEntry, EvidenceKind } from "@/lib/types";
import { Mascot, stagger } from "./primitives";
import { RiskHeader, SettleChecks, StillKeen, VerdictCard, WhyFlags } from "./RiskView";
import { AgentsRail } from "./AgentsRail";
import type { CallContext } from "./CaseCall";

function studentName(): string {
  try {
    return localStorage.getItem(STUDENT_NAME_KEY) || "student";
  } catch {
    return "student";
  }
}


/** Figma "V4 · One home": left is the dashboard (facts + your decision), right is the agents. */
export function CaseScreen({ caseId }: { caseId: string }) {
  const { state, upload, sendReply } = useCase(caseId);
  const [local, setLocal] = useState<ChatEntry[]>([]);
  // messages from before the last Clear stay hidden even though the live stream still holds them
  const [cleared, setCleared] = useState(0);
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
    return { rows, open: openActions(c), mood: mood(c, working), flags: redFlags(c) };
  }, [c, state.agentStatus, state.busy]);

  // The conversation is saved per home in this browser, so history survives a reload.
  const [saved, setSaved] = useLocalJSON<ChatEntry[]>(`warden.chat.${caseId}`, []);
  const chat = useMemo(() => {
    const seen = new Set<string>();
    return [...saved, ...state.chat, ...local]
      .filter((m) => Date.parse(m.at) > cleared)
      .filter((m) => {
        const k = `${m.role}|${m.at}|${m.text}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .sort((a, b) => a.at.localeCompare(b.at));
  }, [saved, state.chat, local, cleared]);
  useEffect(() => {
    if (chat.length > saved.length) setSaved(chat.slice(-60));
  }, [chat, saved.length, setSaved]);

  if (!c || !view) {
    return (
      <div>
        <div>
          <div className="flex flex-col items-center pt-32 text-center">
            <Mascot width={110} height={132} float />
            <p className="mt-6 text-[22px] font-light tracking-[-0.03em]">
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

  const firstName = (() => {
    try {
      return (localStorage.getItem(STUDENT_NAME_KEY) ?? "").split(/\s+/)[0];
    } catch {
      return "";
    }
  })();
  const callContext: CallContext = {
    student_name: firstName || "there",
    home: shortAddress(c.listing?.address) === "Untitled home" ? "this home" : shortAddress(c.listing?.address),
    verdict: `${view.mood.title}. ${view.mood.sub}`,
    red_flags: view.flags.length ? view.flags.slice(0, 5).map((f) => f.title).join("; ") : "none found so far",
    checks: `${(c.checks ?? []).filter((k) => k.state !== "unverified").length} of 8 checks done`,
    open_question: action?.text ?? "none right now",
  };

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
    <div>
      <div>

        <div className="mt-6 grid grid-cols-[minmax(0,888fr)_minmax(0,408fr)] items-start gap-5">
          <motion.main variants={stagger} initial="hidden" animate="show" className="flex min-w-0 flex-col gap-6">
            <RiskHeader c={c} caseId={caseId} photo={caseId === DEMO_CASE_ID ? "/warden/photo-mile-end-front.png" : null} />
            {state.error && (
              <p role="alert" className="rounded-[16px] bg-[#fbe6e1] px-4 py-3 text-[13px] text-[#a8402b]">{state.error}</p>
            )}
            <VerdictCard c={c} mood={view.mood} flags={view.flags.length} />
            <WhyFlags c={c} flags={view.flags} />
            <StillKeen top={view.flags[0]} />
            <SettleChecks c={c} disabled={closed || state.busy} onUpload={onUpload} />
          </motion.main>

          <div className="sticky top-[96px] h-[calc(100dvh-112px)] max-h-[900px]">
            <AgentsRail
              mood={view.mood}
              action={action}
              rows={view.rows}
              chat={chat}
              busy={state.busy}
              canReply={!closed && view.open.length > 0}
              closed={closed}
              onSkip={() => action && void sendReply({ text: "Skip for now", actionId: action.id, status: "skipped" })}
              onAnswer={(text) => action && void sendReply({ text, actionId: action.id, status: "done" })}
              onAsk={ask}
              onSend={(text) => void sendReply({ text })}
              onUpload={onUpload}
              callContext={callContext}
              onCallLine={(role, text) => setLocal((l) => [...l, { role, text, at: new Date().toISOString() }])}
              onClearChat={() => {
                setLocal([]);
                setSaved([]);
                setCleared(Date.now());
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

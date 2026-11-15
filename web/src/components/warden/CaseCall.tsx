"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { Mic, MicOff, PhoneOff, X } from "lucide-react";
import { WardenOrb, type OrbMood } from "../onboarding/WardenOrb";
import { ApiError, type DebriefAnswer, type DebriefInput, type DebriefLine } from "@/lib/api";
import { formatQuestions, isOpenAction, openQuestions } from "@/lib/callQuestions";
import type { Case } from "@/lib/types";

/** What Warden knows about this home when the call starts (ElevenLabs dynamic variables). */
export type CallContext = {
  student_name: string;
  home: string;
  verdict: string;
  red_flags: string;
  checks: string;
  open_question: string;
};

type Props = {
  /** The case as the page holds it now; the call's client tools read it (no backend call). */
  caseData: Case;
  context: CallContext;
  /** Each spoken line, so it lands in this home's chat history. */
  onLine: (role: "student" | "orchestrator", text: string) => void;
  /** Sends the finished call to the orchestrator once, after hang-up. Rejects with ApiError
   * (409 when the home was decided during the call). */
  onDebrief: (payload: DebriefInput) => Promise<void>;
  onEnd: () => void;
};

/** A voice call with Warden about one home. Sits in the agents rail in place of the message box. */
export function CaseCall(props: Props) {
  return (
    <ConversationProvider>
      <Call {...props} />
    </ConversationProvider>
  );
}

type Phase = "call" | "checking" | "notice";

function Call({ caseData, context, onLine, onDebrief, onEnd }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [phase, setPhase] = useState<Phase>("call");
  const [notice, setNotice] = useState<string | null>(null);
  const levelRef = useRef(0);
  const started = useRef(false);

  // The latest case and callbacks, so the client tools and onDisconnect never read stale props.
  const caseRef = useRef(caseData);
  const propsRef = useRef({ onDebrief, onEnd });
  useEffect(() => {
    caseRef.current = caseData;
    propsRef.current = { onDebrief, onEnd };
  });

  // Everything collected during the call; nothing is sent until it ends.
  const linesRef = useRef<DebriefLine[]>([]);
  const answersRef = useRef<Map<string, DebriefAnswer>>(new Map());
  const startedAtRef = useRef<string>(new Date().toISOString());
  const debriefed = useRef(false);

  /** Ends the call once: debriefs the orchestrator when the student spoke, then closes the bar. */
  const finish = useCallback(async () => {
    if (debriefed.current) return;
    debriefed.current = true;
    const { onDebrief: send, onEnd: close } = propsRef.current;
    const lines = [...linesRef.current];
    if (!lines.some((l) => l.role === "student")) {
      close();
      return;
    }
    setPhase("checking");
    try {
      await send({
        source: "call",
        started_at: startedAtRef.current,
        lines,
        answers: [...answersRef.current.values()],
      });
      propsRef.current.onEnd();
    } catch (e) {
      setNotice(
        e instanceof ApiError && e.status === 409
          ? "This home already has a verdict."
          : "I couldn't save the call. Your lines are still in the chat.",
      );
      setPhase("notice");
    }
  }, []);

  const convo = useConversation({
    clientTools: {
      get_next_questions: () => {
        const done = new Set(answersRef.current.keys());
        const next = openQuestions(caseRef.current, 50)
          .filter((q) => q.id === null || !done.has(q.id))
          .slice(0, 3);
        return formatQuestions(next);
      },
      record_answer: (params: Record<string, unknown>) => {
        const actionId = typeof params.action_id === "string" ? params.action_id.trim() : "";
        const answer = typeof params.answer === "string" ? params.answer.trim() : "";
        if (!actionId || !answer || !isOpenAction(caseRef.current, actionId)) {
          return "I couldn't find that question; I'll pick it up after the call.";
        }
        const status = params.status === "skipped" ? "skipped" : "done";
        answersRef.current.set(actionId, { action_id: actionId, answer, status });
        return "Noted. I'll check it after the call.";
      },
    },
    onConnect: () => {
      startedAtRef.current = new Date().toISOString();
    },
    onMessage: (m) => {
      const text = (m.message ?? "").replace(/\[[a-z\s-]+\]\s*/gi, "").trim();
      if (!text || /^\.{2,}$/.test(text)) return;
      const role = m.role === "agent" ? "orchestrator" : "student";
      linesRef.current.push({ role, text, at: new Date().toISOString() });
      onLine(role, text);
    },
    onError: (msg) => setError(typeof msg === "string" ? msg : "The call dropped."),
    onDisconnect: () => {
      void finish();
    },
  });
  const { status, isSpeaking, isMuted, setMuted, endSession, startSession, getOutputVolume, getInputVolume } = convo;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const res = await fetch("/api/voice/session", { method: "POST" });
        const body = (await res.json()) as { token?: string; error?: string };
        if (!res.ok || !body.token) throw new Error(body.error ?? "Couldn't start the call.");
        if (cancelled) return;
        started.current = true;
        startedAtRef.current = new Date().toISOString();
        startSession({
          conversationToken: body.token,
          connectionType: "webrtc",
          dynamicVariables: { ...context, open_questions: formatQuestions(openQuestions(caseRef.current, 5)) },
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(/denied|NotAllowed|Permission/i.test(msg) ? "Allow your microphone to call Warden." : msg);
      }
    })();
    return () => {
      cancelled = true;
    };
    // start once per call
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (status !== "connected") return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    let raf = 0;
    const loop = () => {
      levelRef.current = Math.min(1, (isSpeaking ? getOutputVolume() : getInputVolume()) * 2.4);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      clearInterval(id);
      cancelAnimationFrame(raf);
    };
  }, [status, isSpeaking, getOutputVolume, getInputVolume]);

  const busy = phase === "checking";
  const mood: OrbMood = error || phase !== "call" ? "idle" : status !== "connected" ? "connecting" : isSpeaking ? "speaking" : "listening";
  const label =
    phase === "checking"
      ? "Checking what you told me…"
      : phase === "notice"
        ? (notice ?? "")
        : (error ?? (status === "connected" ? (isSpeaking ? "Warden is talking" : "Listening…") : "Calling Warden…"));
  const mmss = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  const sub = phase !== "call" ? "" : status === "connected" ? mmss : error ? "" : "Connecting";

  return (
    <div className="relative mt-3 flex items-center gap-3 rounded-[20px] bg-white p-3 pr-4 shadow-card">
      <div className="-my-4 -ml-3 shrink-0">
        <WardenOrb size={104} mood={mood} levelRef={levelRef} />
      </div>
      <div className="min-w-0 flex-1" role="status" aria-live="polite">
        <p className={`text-[13.5px] font-medium leading-[1.3] ${error || phase === "notice" ? "text-[#a8402b]" : ""}`}>{label}</p>
        <p className="text-[12px] tabular-nums text-muted">{sub}</p>
      </div>
      {!error && phase === "call" && (
        <button
          type="button"
          onClick={() => setMuted(!isMuted)}
          disabled={status !== "connected"}
          aria-label={isMuted ? "Unmute" : "Mute"}
          aria-pressed={isMuted}
          className="flex size-10 cursor-pointer items-center justify-center rounded-full border border-line bg-white text-ink transition hover:bg-field disabled:opacity-40"
        >
          {isMuted ? <MicOff size={17} /> : <Mic size={17} />}
        </button>
      )}
      {phase === "notice" ? (
        <button
          type="button"
          onClick={onEnd}
          aria-label="Close"
          className="flex size-10 cursor-pointer items-center justify-center rounded-full border border-line bg-white text-ink transition hover:bg-field"
        >
          <X size={17} />
        </button>
      ) : (
        !busy && (
          <button
            type="button"
            onClick={() => {
              // Connected: hang up and let onDisconnect debrief. Otherwise there is no session to wait for.
              if (status === "connected") endSession();
              else void finish();
            }}
            aria-label="End call"
            className="flex size-10 cursor-pointer items-center justify-center rounded-full bg-[#e06a52] text-white transition hover:brightness-95"
          >
            <PhoneOff size={17} />
          </button>
        )
      )}
    </div>
  );
}

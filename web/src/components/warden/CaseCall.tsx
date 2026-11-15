"use client";

import { useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { Mic, MicOff, PhoneOff } from "lucide-react";
import { WardenOrb, type OrbMode } from "./WardenOrb";

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
  context: CallContext;
  /** Each spoken line, so it lands in this home's chat history. */
  onLine: (role: "student" | "orchestrator", text: string) => void;
  /** The student told Warden how the letting agent answered the open question. */
  onAnswer?: (answer: string) => void;
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

function Call({ context, onLine, onAnswer, onEnd }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const levelRef = useRef(0);
  const micRef = useRef(0);
  const started = useRef(false);

  const convo = useConversation({
    clientTools: {
      record_answer: (params: Record<string, unknown>) => {
        const answer = String(params.answer ?? "").trim();
        if (!answer || !onAnswer) return "There's no open question to answer right now.";
        onAnswer(answer);
        return "Recorded. Tell them you've passed it to your team and they'll see the check update shortly.";
      },
    },
    onMessage: (m) => {
      const text = (m.message ?? "").replace(/\[[a-z\s-]+\]\s*/gi, "").trim();
      if (!text || /^\.{2,}$/.test(text)) return;
      onLine(m.role === "agent" ? "orchestrator" : "student", text);
    },
    onError: (msg) => setError(typeof msg === "string" ? msg : "The call dropped."),
    onDisconnect: () => {
      if (started.current) onEnd();
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
        startSession({ conversationToken: body.token, connectionType: "webrtc", dynamicVariables: context });
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
      levelRef.current = Math.min(1, getOutputVolume() * 2.4);
      micRef.current = Math.min(1, getInputVolume() * 2.4);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      clearInterval(id);
      cancelAnimationFrame(raf);
    };
  }, [status, isSpeaking, getOutputVolume, getInputVolume]);

  const mode: OrbMode = error ? "idle" : status !== "connected" ? "thinking" : isSpeaking ? "speaking" : "listening";
  const label = error ?? (status === "connected" ? (isSpeaking ? "Warden is talking" : "Listening…") : "Calling Warden…");
  const mmss = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div className="relative mt-3 flex items-center gap-3 rounded-[20px] bg-white p-3 pr-4 shadow-card">
      <div className="-my-4 -ml-3 shrink-0">
        <WardenOrb size={104} mode={mode} levelRef={levelRef} micRef={micRef} />
      </div>
      <div className="min-w-0 flex-1">
        <p className={`text-[13.5px] font-medium leading-[1.3] ${error ? "text-[#a8402b]" : ""}`}>{label}</p>
        <p className="text-[12px] tabular-nums text-muted">{status === "connected" ? mmss : error ? "" : "Connecting"}</p>
      </div>
      {!error && (
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
      <button
        type="button"
        onClick={() => {
          if (status === "connected") endSession();
          else onEnd();
        }}
        aria-label="End call"
        className="flex size-10 cursor-pointer items-center justify-center rounded-full bg-[#e06a52] text-white transition hover:brightness-95"
      >
        <PhoneOff size={17} />
      </button>
    </div>
  );
}

"use client";

import { useState } from "react";
import { CHECK_LABELS } from "@/lib/labels";
import type { Action, ActionStatusInput, CheckId } from "@/lib/types";
import type { ReplyInput } from "@/lib/api";

interface Props {
  action: Action;
  disabled: boolean;
  onReply: (input: ReplyInput) => Promise<unknown> | void;
}

export function ActionItem({ action, disabled, onReply }: Props) {
  const [text, setText] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const isQuestion = action.kind === "question";
  const inputId = `answer-${action.id}`;

  async function send(status: ActionStatusInput, fallback: string) {
    const trimmed = text.trim();
    if (status === "done" && isQuestion && !trimmed) {
      setMessage("Please type an answer first.");
      return;
    }
    setMessage(null);
    // NOTE: clear the textarea right after sending, even if the request later fails.
    setText("");
    await onReply({ text: trimmed || fallback, actionId: action.id, status });
  }

  return (
    <div className="card">
      <div>
        <span className="tag">{isQuestion ? "Question" : "Action"}</span>
        <span className="tag">{CHECK_LABELS[action.check_id as CheckId] ?? String(action.check_id)}</span>
      </div>
      <p>{action.text}</p>
      <label htmlFor={inputId}>Your answer</label>
      <textarea
        id={inputId}
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
      />
      {message && <div className="muted" role="alert">{message}</div>}
      <button
        type="button"
        disabled={disabled || (isQuestion && !text.trim())}
        onClick={() => send("done", "(done)")}
      >
        Done
      </button>
      <button type="button" className="secondary" disabled={disabled} onClick={() => send("skipped", "(skipped)")}>
        Skip
      </button>
      <button
        type="button"
        className="secondary"
        disabled={disabled}
        onClick={() => send("impossible", "(can't do)")}
      >
        Can&apos;t do
      </button>
    </div>
  );
}

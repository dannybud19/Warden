"use client";

import { useState, type FormEvent } from "react";
import { closedActions, openActions } from "@/lib/selectors";
import { CHECK_LABELS } from "@/lib/labels";
import type { Case, CheckId, ChatEntry } from "@/lib/types";
import type { ReplyInput } from "@/lib/api";
import { ActionItem } from "./ActionItem";

interface Props {
  caseData: Case;
  chat: ChatEntry[];
  disabled: boolean;
  onReply: (input: ReplyInput) => Promise<unknown> | void;
}

export function ChatPanel({ caseData, chat, disabled, onReply }: Props) {
  const [text, setText] = useState("");
  const open = openActions(caseData);
  const closed = closedActions(caseData);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    setText("");
    await onReply({ text: trimmed });
  }

  return (
    <div className="col">
      <section>
        <h2>Assistant</h2>
        {chat.length === 0 ? (
          <p className="muted">No messages yet.</p>
        ) : (
          <div className="chat-log">
            {chat.map((m, i) => (
              <div key={`${m.at}-${i}`} className={`bubble ${m.role}`}>
                {m.text}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2>Open actions</h2>
        {open.length === 0 ? (
          <p className="muted">Nothing to do right now.</p>
        ) : (
          open.map((a) => <ActionItem key={a.id} action={a} disabled={disabled} onReply={onReply} />)
        )}
      </section>

      {closed.length > 0 && (
        <section>
          <h2>Answered</h2>
          {closed.map((a) => (
            <div key={a.id} className="card">
              <span className="tag">{CHECK_LABELS[a.check_id as CheckId] ?? String(a.check_id)}</span>
              <span className="tag">{a.status ?? "open"}</span>
              <p>{a.text}</p>
              {(a.answer ?? "") && <p>Answer: {a.answer}</p>}
              {(a.outcome ?? "") && <p className="muted">Outcome: {a.outcome}</p>}
            </div>
          ))}
        </section>
      )}

      <section>
        <form onSubmit={submit}>
          <label htmlFor="chat-reply">Message the assistant</label>
          <textarea
            id="chat-reply"
            value={text}
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
          />
          <button type="submit" disabled={disabled || !text.trim()}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}

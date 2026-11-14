"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { useCase } from "@/lib/useCase";
import { isDecided } from "@/lib/selectors";
import { StatusBar } from "@/components/StatusBar";
import { EvidencePanel } from "@/components/EvidencePanel";
import { ChecksTable } from "@/components/ChecksTable";
import { FindingsList } from "@/components/FindingsList";
import { ChatPanel } from "@/components/ChatPanel";
import { DecisionBox } from "@/components/DecisionBox";
import { DebugPanel } from "@/components/DebugPanel";
import { ErrorBanner } from "@/components/ErrorBanner";

function CaseView() {
  const { id } = useParams<{ id: string }>();
  const { state, refresh, upload, sendReply } = useCase(id);
  const c = state.caseData;
  if (!c) return <main className="page"><p>Loading case…</p><ErrorBanner message={state.error} /></main>;
  const disabled = isDecided(c) || state.busy;

  return (
    <main className="page">
      <ErrorBanner message={state.error} />
      <StatusBar caseData={c} agentStatus={state.agentStatus} connection={state.connection} onRefresh={refresh} />
      {c.decision && <DecisionBox decision={c.decision} />}
      <div className="grid">
        <EvidencePanel caseData={c} disabled={disabled} onUpload={upload} />
        <div className="col">
          <ChecksTable caseData={c} />
          <FindingsList caseData={c} />
        </div>
        <ChatPanel caseData={c} chat={state.chat} disabled={disabled} onReply={sendReply} />
      </div>
      <DebugPanel caseData={c} events={state.events} />
    </main>
  );
}

// NOTE: Next.js 16 (Cache Components) requires useParams() to be under <Suspense>, so the page wraps CaseView.
export default function CasePage() {
  return (
    <Suspense fallback={<main className="page"><p>Loading case…</p></main>}>
      <CaseView />
    </Suspense>
  );
}

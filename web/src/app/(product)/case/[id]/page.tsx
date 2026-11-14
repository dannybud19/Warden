"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { CaseScreen } from "@/components/warden/CaseScreen";

function CaseRoute() {
  const { id } = useParams<{ id: string }>();
  return <CaseScreen key={id} caseId={id} />;
}

// NOTE: Next.js 16 (Cache Components) requires useParams() to be under <Suspense>.
export default function CasePage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-canvas" />}>
      <CaseRoute />
    </Suspense>
  );
}

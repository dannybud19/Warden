import { Suspense } from "react";
import { HomesView } from "@/components/warden/HomesView";

// NOTE: HomesView reads ?homes= (useSearchParams), which Cache Components requires under <Suspense>.
export default function HomesPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-canvas" />}>
      <HomesView />
    </Suspense>
  );
}

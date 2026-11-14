"use client";

import Image from "next/image";
import { PixelField, type QuietZone } from "./PixelField";
import { SiteNav } from "./SiteNav";

/** Pixels stay strong in the band above the content and at the edges, calm behind the content. */
const CONTENT_ZONE: QuietZone = (w) => {
  const half = Math.min(w, 1312) / 2;
  return [w / 2 - half, 96, w / 2 + half, 400];
};

type Tab = "Cases" | "Inbox" | "Settings";

/** Teal pixel header, page glows and the glass nav, around any product page. */
export function PageShell({ active, children }: { active: Tab; children: React.ReactNode }) {
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-[260px] bg-[linear-gradient(to_bottom,#8fd3d8,#c6ebed_60%,#f5f8f9)]">
          <PixelField className="absolute inset-0 size-full" maxAlpha={0.4} quiet={CONTENT_ZONE} />
        </div>
        <div className="relative mx-auto h-full max-w-[1440px]">
          <div className="absolute left-[-170px] top-[510px] size-[640px]">
            <Image src="/warden/glow-bottom-left.svg" alt="" width={640} height={640} unoptimized className="block size-full" />
          </div>
          <div className="absolute left-[1010px] top-[550px] size-[600px]">
            <Image src="/warden/glow-bottom-right.svg" alt="" width={600} height={600} unoptimized className="block size-full" />
          </div>
        </div>
      </div>
      <div className="relative mx-auto max-w-[1440px] px-16 pb-10 pt-4">
        <SiteNav active={active} />
        {children}
      </div>
    </div>
  );
}

"use client";

import Image from "next/image";
import { Suspense } from "react";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { PixelField, type QuietZone } from "./PixelField";
import { SiteNav } from "./SiteNav";

// The frame every product page shares: teal pixel band, soft glows and the glass nav. It lives in the
// layout, so it stays mounted while you move between Cases, a home, Inbox and Settings. Only the band's
// height and its calm zone change per page (smoothly); the page content animates in via template.tsx.

type Route = "home" | "case" | "page" | "onboarding";

// onboarding: the pixels fill the screen (taller than any viewport; the frame clips it)
const BAND: Record<Route, number> = { home: 430, case: 240, page: 260, onboarding: 1100 };

const ZONES: Record<Route, QuietZone> = {
  // calm right behind Warden on the homes page
  home: (w) => [w / 2 - 190, 90, w / 2 + 190, 400],
  // calm behind the content on every other page, strong above it and at the edges
  case: (w) => [w / 2 - Math.min(w, 1312) / 2, 110, w / 2 + Math.min(w, 1312) / 2, 400],
  page: (w) => [w / 2 - Math.min(w, 1312) / 2, 96, w / 2 + Math.min(w, 1312) / 2, 400],
  // calm behind Warden and the question card, lively around the edges
  onboarding: (w) => [w / 2 - 470, 120, w / 2 + 520, 760],
};

function routeOf(path: string): Route {
  if (path === "/") return "home";
  if (path.startsWith("/onboarding") || path === "/new") return "onboarding";
  if (path.startsWith("/case/")) return "case";
  return "page";
}

function tabOf(path: string): "Cases" | "Inbox" | "Settings" {
  if (path.startsWith("/inbox")) return "Inbox";
  if (path.startsWith("/settings")) return "Settings";
  return "Cases";
}

// Onboarding background: a few very soft teal glows drifting slowly on white.
const GLOWS = [
  { color: "rgba(92,198,201,0.28)", size: 720, x: "8%", y: "6%", dx: 60, dy: 40, d: 22 },
  { color: "rgba(19,138,147,0.16)", size: 640, x: "62%", y: "52%", dx: -70, dy: -50, d: 26 },
  { color: "rgba(143,211,216,0.32)", size: 560, x: "70%", y: "-4%", dx: -40, dy: 60, d: 19 },
  { color: "rgba(46,154,124,0.10)", size: 600, x: "14%", y: "60%", dx: 50, dy: -30, d: 24 },
];

function SoftGradients() {
  return (
    <motion.div className="absolute inset-0 overflow-hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.8 }}>
      {GLOWS.map((g, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full will-change-transform"
          style={{ left: g.x, top: g.y, width: g.size * 1.4, height: g.size * 1.4, background: `radial-gradient(circle, ${g.color}, transparent 62%)` }}
          animate={{ x: [0, g.dx, 0], y: [0, g.dy, 0], scale: [1, 1.08, 1] }}
          transition={{ duration: g.d, repeat: Infinity, ease: "easeInOut" }}
        />
      ))}
    </motion.div>
  );
}

/** The teal pixel band. Its height eases between pages instead of re-mounting. */
function Band({ route }: { route: Route }) {
  return (
    <motion.div
      className="absolute inset-x-0 top-0 bg-[linear-gradient(to_bottom,#8fd3d8,#c6ebed_58%,#f5f8f9)]"
      initial={false}
      animate={{ height: BAND[route] }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
    >
      {/* onboarding: plain white under the moving teal pixels */}
      <motion.div
        className="absolute inset-0 bg-white"
        initial={false}
        animate={{ opacity: route === "onboarding" ? 1 : 0 }}
        transition={{ duration: 0.6 }}
      />
      <motion.div className="absolute inset-0" initial={false} animate={{ opacity: route === "onboarding" ? 0 : 1 }} transition={{ duration: 0.6 }}>
        <PixelField className="absolute inset-0 size-full" maxAlpha={0.42} quiet={ZONES[route]} />
      </motion.div>
      <AnimatePresence>{route === "onboarding" && <SoftGradients key="soft" />}</AnimatePresence>
    </motion.div>
  );
}

// Only these two read the URL, so only they sit behind Suspense; page content never waits on them.
function RouteBand() {
  return <Band route={routeOf(usePathname() ?? "/")} />;
}

function RouteNav() {
  const path = usePathname() ?? "/";
  // onboarding is the welcome: no nav until the student has a home. It slides in as they finish.
  return (
    <AnimatePresence initial={false}>
      {!path.startsWith("/onboarding") && (
        <motion.div
          key="nav"
          className="sticky top-4 z-30"
          initial={{ opacity: 0, y: -16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <SiteNav active={tabOf(path)} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function ProductChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <Suspense fallback={<Band route="page" />}>
          <RouteBand />
        </Suspense>
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
        <Suspense fallback={<div className="sticky top-4 z-30"><SiteNav active="Cases" /></div>}>
          <RouteNav />
        </Suspense>
        {children}
      </div>
    </div>
  );
}

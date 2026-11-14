"use client";

import Image from "next/image";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import * as api from "@/lib/api";
import {
  HOME_STATUS, SAMPLE_HOMES, STATUS_ORDER, caseToHome, parseIds, sortByNeed, useRememberedCaseIdsRaw,
  type Home,
} from "@/lib/homes";
import { Chip, rise, stagger } from "./primitives";
import { SiteNav, useStudentName } from "./SiteNav";
import { HomeFolder } from "./HomeFolder";
import { AddHomeCard } from "./AddHome";
import { FeaturedHome, HowWardenChecks } from "./FeaturedHome";
import { PixelField, type QuietZone } from "./PixelField";
import { AnimatedWarden, type WardenState } from "./AnimatedWarden";

// ---- which homes to show ----

type Load = { key: string; homes: Home[] | null; failed: boolean };

function useHomes(): { homes: Home[]; loading: boolean; failed: boolean } {
  const params = useSearchParams();
  const view = params.get("homes"); // "one" or "samples" force the design's sample data
  const ids = parseIds(useRememberedCaseIdsRaw());
  const key = ids.join(",");
  const [load, setLoad] = useState<Load>({ key: "", homes: null, failed: false });

  useEffect(() => {
    if (!key || view) return;
    let cancelled = false;
    Promise.allSettled(key.split(",").map((id) => api.getCase(id))).then((results) => {
      if (cancelled) return;
      const cases = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
      setLoad({ key, homes: sortByNeed(cases.map(caseToHome)), failed: cases.length === 0 });
    });
    return () => {
      cancelled = true;
    };
  }, [key, view]);

  if (view === "one") return { homes: SAMPLE_HOMES.slice(0, 1), loading: false, failed: false };
  if (view === "samples" || !key) return { homes: SAMPLE_HOMES, loading: false, failed: false };
  if (load.key !== key) return { homes: [], loading: true, failed: false };
  if (load.failed || !load.homes?.length) return { homes: SAMPLE_HOMES, loading: false, failed: true };
  return { homes: load.homes, loading: false, failed: false };
}

// ---- page ----

const MASCOT_FOR: Record<Home["status"], WardenState> = {
  likely_scam: "red",
  not_verified: "amber",
  proceed_with_care: "green",
  no_red_flags_remaining: "green",
  checking: "thinking",
};

/** Keep the pixels calm right behind Warden so he stands out. */
const GREETING_ZONE: QuietZone = (w) => [w / 2 - 190, 90, w / 2 + 190, 400];


function HeroBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[430px] overflow-hidden bg-[linear-gradient(to_bottom,#8fd3d8,#c6ebed_55%,#f5f8f9)]">
      <PixelField className="absolute inset-0 size-full" quiet={GREETING_ZONE} />
    </div>
  );
}

export function PageGlows() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="relative mx-auto h-full max-w-[1440px]">
        <div className="absolute left-[-170px] top-[510px] size-[640px]">
          <Image src="/warden/glow-bottom-left.svg" alt="" width={640} height={640} unoptimized className="block size-full" />
        </div>
        <div className="absolute left-[1010px] top-[550px] size-[600px]">
          <Image src="/warden/glow-bottom-right.svg" alt="" width={600} height={600} unoptimized className="block size-full" />
        </div>
      </div>
    </div>
  );
}

function partOfDay(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good Morning" : h < 18 ? "Good Afternoon" : "Good Evening";
}

/** "Good Morning" / "Good Afternoon" / "Good Evening", re-checked every minute. Null on the server. */
function useGreeting(): string | null {
  return useSyncExternalStore(
    (cb) => {
      const id = window.setInterval(cb, 60_000);
      return () => window.clearInterval(id);
    },
    partOfDay,
    () => null,
  );
}

/** Warden's one-line read on all the homes together. The chips underneath carry the counts. */
function cheer(homes: Home[]): string {
  const fishy = homes.filter((h) => h.status === "likely_scam" || h.status === "not_verified").length;
  const good = homes.filter((h) => h.status === "proceed_with_care" || h.status === "no_red_flags_remaining").length;
  const n = homes.length;
  if (!n) return "Add a home and Warden will start checking.";
  if (fishy === n) return "Something's very fishy here…";
  if (fishy > 1) return "Warden senses something fishy…";
  if (fishy === 1) return "Just one thing smells fishy…";
  if (good === n) return "Everything is looking good so far.";
  return "Warden is sniffing around…";
}



export function HomesView() {
  const { homes, loading, failed } = useHomes();
  const single = homes.length === 1;
  const needYou = homes.filter((h) => h.needsYou).length;

  const counts = useMemo(
    () => STATUS_ORDER.map((s) => ({ s, n: homes.filter((h) => h.status === s).length })).filter((c) => c.n > 0),
    [homes],
  );
  const name = useStudentName().trim().split(/\s+/)[0] ?? "";
  const mood = cheer(homes);
  const greeting = useGreeting();
  // The mascot mirrors the home that needs the student most.
  // Warden's pose follows the riskiest home, not the one that needs the student first.
  const riskiest = [...homes].sort((a, b) => HOME_STATUS[a.status].rank - HOME_STATUS[b.status].rank)[0];
  const heroState: WardenState = loading ? "thinking" : riskiest ? MASCOT_FOR[riskiest.status] : "default";

  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <PageGlows />
      <HeroBackdrop />

      <div className="relative mx-auto max-w-[1440px] px-4 pb-14 pt-4 sm:px-8 xl:px-16">
        <SiteNav />

        <header className="relative flex flex-col items-center pb-10">
          <h1 className="sr-only">
            {loading
              ? "Gathering your homes"
              : `Warden is watching ${homes.length} ${single ? "home" : "homes"}. ${needYou ? `${needYou} need${needYou === 1 ? "s" : ""} you today.` : "Nothing needs you today."}`}
          </h1>

          <div className="relative h-[284px] w-full">
            {/* soft glow Warden stands in */}
            <motion.div
              aria-hidden
              className="absolute left-1/2 top-[10px] size-[300px] -translate-x-1/2"
              animate={{ scale: [1, 1.06, 1], opacity: [0.85, 1, 0.85] }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            >
              <Image src="/warden/rail-halo.svg" alt="" width={320} height={320} unoptimized className="absolute inset-[-30%] max-w-none" />
            </motion.div>
            <motion.div
              className="absolute left-1/2 top-0 -translate-x-1/2"
              initial={{ opacity: 0, y: 24, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ type: "spring", stiffness: 180, damping: 16, delay: 0.15 }}
            >
              <AnimatedWarden state={heroState} width={262} lively />
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", stiffness: 220, damping: 20, delay: 0.45 }}
            className="text-center"
          >
            <p className="text-[40px] font-medium leading-[1.05] tracking-[-0.031em]">
              {greeting ? `${greeting}${name ? `, ${name}` : ""}` : "\u00a0"}
            </p>
            {!loading && (
              <AnimatePresence mode="wait" initial={false}>
                <motion.p
                  key={mood}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  className="mt-2.5 text-[18px] leading-[1.4] text-ink/60"
                >
                  {mood}
                </motion.p>
              </AnimatePresence>
            )}
          </motion.div>

          <motion.div variants={stagger} initial="hidden" animate="show" className="mt-5 flex flex-wrap justify-center gap-2">
            {counts.map(({ s, n }) => (
              <motion.span key={s} variants={rise}>
                <Chip dot={HOME_STATUS[s].dot} label={HOME_STATUS[s].countLabel(n)} size="lg" tone="solid" />
              </motion.span>
            ))}
          </motion.div>
        </header>

        {failed && (
          <p className="mb-3 text-[13px] text-muted">
            Couldn&apos;t reach Warden&apos;s server, so these are sample homes.
          </p>
        )}

        {single ? (
          <div className="grid grid-cols-1 gap-4 lg:mt-[28px] lg:grid-cols-[868fr_428fr]">
            <motion.div variants={rise} initial="hidden" animate="show">
              <FeaturedHome home={homes[0]} />
            </motion.div>
            <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col gap-4">
              <motion.div variants={rise}>
                <AddHomeCard size="md" title="Add another home" />
              </motion.div>
              <motion.div variants={rise}>
                <HowWardenChecks />
              </motion.div>
            </motion.div>
          </div>
        ) : (
          <section aria-labelledby="your-homes" className="lg:mt-[14px]">
            <h2 id="your-homes" className="sr-only">Your homes</h2>
            <motion.ul
              variants={stagger}
              initial="hidden"
              animate="show"
              className="mt-2 grid grid-cols-1 gap-x-[17px] gap-y-4 md:grid-cols-2 xl:grid-cols-3"
            >
              {loading
                ? Array.from({ length: 3 }, (_, i) => (
                    <motion.li
                      key={i}
                      className="h-[258px] rounded-[22px] bg-white/60"
                      animate={{ opacity: [0.5, 1, 0.5] }}
                      transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.15 }}
                    />
                  ))
                : homes.map((h, i) => (
                    <motion.li key={h.id} variants={rise} layout>
                      <HomeFolder home={h} priority={i < 3} />
                    </motion.li>
                  ))}
              <motion.li variants={rise}>
                <AddHomeCard />
              </motion.li>
            </motion.ul>
          </section>
        )}
      </div>
    </div>
  );
}

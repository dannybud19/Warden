"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "motion/react";
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

// ---- greeting ("Saturday 14 November" / "Good morning") computed once on the client ----

let today: { date: string; part: string } | null = null;
function readToday() {
  if (!today) {
    const now = new Date();
    const h = now.getHours();
    today = {
      date: now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }),
      part: h < 12 ? "morning" : h < 18 ? "afternoon" : "evening",
    };
  }
  return today;
}
const noop = () => () => {};

function useToday() {
  return useSyncExternalStore(noop, readToday, () => null);
}

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

/** Keep the pixels light behind the greeting (left, below the nav) so it stays readable. */
const GREETING_ZONE: QuietZone = (w) => {
  const left = Math.max(0, (w - 1440) / 2);
  return [left, 88, left + Math.min(w, 760), 270];
};


function HeroBackdrop() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[312px] overflow-hidden bg-[linear-gradient(to_bottom,#8fd3d8,#c6ebed_55%,#f5f8f9)]">
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

/** "Flat 2, 41 Mile End Road" -> "Mile End Road" */
function streetName(title: string): string {
  return (title.split(", ").pop() ?? title).replace(/^\d+\w?\s+/, "");
}

/** Urgency look for the bubble, keyed by the home it's about. */
const BUBBLE_TONE: Partial<Record<Home["status"], { bg: string; edge: string; dot: string; label: string }>> = {
  likely_scam: { bg: "rgba(253,241,238,0.88)", edge: "#e06a52", dot: "/warden/dot-red.svg", label: "Likely scam" },
  not_verified: { bg: "rgba(253,247,234,0.88)", edge: "#d99a2b", dot: "/warden/dot-amber.svg", label: "Don't pay yet" },
};

/** Warden's speech bubble. With a `home`, it becomes an urgent alert about that home. */
function MascotBubble({ text, home }: { text: string; home?: Home }) {
  const tone = home ? BUBBLE_TONE[home.status] : undefined;
  const bg = tone?.bg ?? "rgba(255,255,255,0.6)";
  return (
    <motion.div
      role={tone ? "alert" : undefined}
      initial={{ opacity: 0, scale: 0.85, x: 12 }}
      animate={tone ? { opacity: 1, scale: 1, x: [12, 0, -4, 4, -2, 0] } : { opacity: 1, scale: 1, x: 0 }}
      transition={
        tone
          ? { delay: 0.5, opacity: { duration: 0.25, delay: 0.5 }, scale: { type: "spring", stiffness: 260, damping: 20, delay: 0.5 }, x: { duration: 0.7, delay: 0.7 } }
          : { type: "spring", stiffness: 260, damping: 20, delay: 0.5 }
      }
      style={{ transformOrigin: "right center", background: bg, borderColor: tone ? `${tone.edge}55` : undefined }}
      className="relative mt-3 w-[300px] rounded-[22px] border border-white px-4 pb-4 pt-[14px] shadow-glass backdrop-blur-[15px]"
    >
      {/* tail pointing at Warden */}
      <span
        aria-hidden
        className="absolute -right-[9px] top-[30px] h-[18px] w-[10px] backdrop-blur-[15px]"
        style={{ background: bg, clipPath: "polygon(0 0, 100% 50%, 0 100%)" }}
      />
      {tone && home && (
        <div className="mb-2 flex items-center gap-2">
          <motion.span
            className="relative flex size-2"
            animate={{ scale: [1, 1.25, 1] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          >
            <motion.span
              className="absolute inset-0 rounded-full"
              style={{ background: tone.edge }}
              animate={{ scale: [1, 2.4], opacity: [0.5, 0] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }}
            />
            <Image src={tone.dot} alt="" width={8} height={8} unoptimized className="relative block" />
          </motion.span>
          <span className="text-[11.5px] font-semibold uppercase tracking-[0.08em]" style={{ color: tone.edge }}>
            Needs you · {tone.label}
          </span>
        </div>
      )}
      <p className="text-[14px] leading-[1.4]">{text}</p>
      {home && (
        <Link
          href={home.href}
          className="group mt-3 inline-flex items-center gap-1.5 rounded-full bg-teal px-3.5 py-[7px] text-[12.5px] font-medium leading-[normal] text-white transition-transform hover:-translate-y-px active:scale-95"
        >
          Open {streetName(home.title)}
          <span className="inline-block transition-transform group-hover:translate-x-0.5">→</span>
        </Link>
      )}
    </motion.div>
  );
}

export function HomesView() {
  const { homes, loading, failed } = useHomes();
  const name = useStudentName().trim();
  const day = useToday();
  const single = homes.length === 1;
  const needYou = homes.filter((h) => h.needsYou).length;

  const counts = useMemo(
    () => STATUS_ORDER.map((s) => ({ s, n: homes.filter((h) => h.status === s).length })).filter((c) => c.n > 0),
    [homes],
  );
  const urgent = homes.find((h) => h.needsYou && h.nudge);
  // The mascot mirrors the home that needs the student most.
  const heroState: WardenState = loading ? "thinking" : homes[0] ? MASCOT_FOR[homes[0].status] : "default";

  return (
    <div className="relative min-h-dvh overflow-hidden">
      <PageGlows />
      <HeroBackdrop />

      <div className="relative mx-auto max-w-[1440px] px-4 pb-14 pt-4 sm:px-8 xl:px-16">
        <SiteNav />

        <header className="relative pb-6 pt-[26px] lg:min-h-[240px] lg:pb-0">
          <motion.div variants={stagger} initial="hidden" animate="show">
            <motion.p variants={rise} className="h-[18px] text-[13px] font-medium leading-[1.4] text-ink/55">
              {day?.date}
            </motion.p>
            <motion.h1 variants={rise} className="mt-[2px] text-[36px] font-light leading-[1.1] tracking-[-1.44px] sm:text-[48px]">
              Good {day?.part ?? "morning"}
              {name && `, ${name}`}
            </motion.h1>
            <motion.p variants={rise} className="mt-[5px] text-[17px] leading-[1.4] tracking-[-0.2px] sm:text-[20px]">
              {loading ? (
                "Warden is gathering your homes…"
              ) : (
                <>
                  Warden is watching {homes.length} {single ? "home." : "homes"}
                  <span className="font-medium text-teal">
                    {single
                      ? needYou ? " It needs you today." : " Nothing needs you today."
                      : needYou ? `. ${needYou} need${needYou === 1 ? "s" : ""} you today.` : ". Nothing needs you today."}
                  </span>
                </>
              )}
            </motion.p>
            <motion.div variants={rise} className="mt-[18px] flex flex-wrap gap-2">
              {counts.map(({ s, n }) => (
                <Chip key={s} dot={HOME_STATUS[s].dot} label={HOME_STATUS[s].countLabel(n)} size="lg" tone="solid" />
              ))}
            </motion.div>
          </motion.div>

          <div className="absolute right-0 top-[24px] hidden items-start gap-4 lg:flex">
            {single ? (
              <MascotBubble text="Checking another place too? Add it and I'll watch both." />
            ) : urgent ? (
              <MascotBubble text={urgent.nudge!} home={urgent} />
            ) : null}
            <div className="-mt-3">
              <AnimatedWarden state={heroState} width={170} />
            </div>
          </div>
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
            <div className="flex items-baseline gap-3">
              <h2 id="your-homes" className="text-[15px] font-medium leading-[1.4]">Your homes</h2>
              <span className="text-[13px] leading-[1.4] text-muted">Sorted by what needs you first</span>
            </div>
            <motion.ul
              variants={stagger}
              initial="hidden"
              animate="show"
              className="mt-[7px] grid grid-cols-1 gap-x-[17px] gap-y-4 md:grid-cols-2 xl:grid-cols-3"
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

"use client";

import Image from "next/image";
import Link from "next/link";
import { motion } from "motion/react";
import { HOME_STATUS, type Home } from "@/lib/homes";
import { Chip, Segments } from "./primitives";

const MotionLink = motion.create(Link);
const spring = { type: "spring", stiffness: 260, damping: 24 } as const;

/** One home in the "Your homes" grid: a full-bleed photo with a liquid-glass rim, text in one glass panel. */
export function HomeFolder({ home, priority = false }: { home: Home; priority?: boolean }) {
  const meta = HOME_STATUS[home.status];
  return (
    <MotionLink
      href={home.href}
      aria-label={`${home.title}: ${meta.label}, ${home.checked} of ${home.total} checked`}
      initial="rest"
      animate="rest"
      whileHover="hover"
      whileTap={{ scale: 0.985 }}
      variants={{ rest: { y: 0 }, hover: { y: -4 } }}
      transition={spring}
      className="relative block h-[258px] overflow-hidden rounded-[24px] shadow-card hover:shadow-glass"
    >
      <motion.div className="absolute inset-0" variants={{ rest: { scale: 1 }, hover: { scale: 1.05 } }} transition={spring}>
        <Image src={home.photos.front} alt="" fill sizes="(min-width: 1280px) 430px, 50vw" priority={priority} className="object-cover" />
      </motion.div>
      {/* soften the bottom so the glass panel always has something calm behind it */}
      <div aria-hidden className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-ink/25 to-transparent" />

      {home.needsYou && (
        <Chip dot="/warden/dot-red.svg" label="Needs you" tone="glass" className="absolute right-3 top-3 text-[11.5px]! shadow-card" />
      )}

      <motion.div
        className="liquid-glass absolute inset-x-3 bottom-3 rounded-[18px] px-4 pb-3 pt-3"
        variants={{ rest: { y: 0 }, hover: { y: -2 } }}
        transition={spring}
      >
        <span className="liquid-edge" aria-hidden />
        <p className="truncate text-[20px] font-light leading-[1.2] tracking-[-0.03em]">{home.title}</p>
        <p className="mt-1 truncate text-[12px] leading-[1.4] text-ink/60">{home.meta}</p>
        <div className="mt-2.5 flex items-center justify-between gap-3">
          <Chip dot={meta.dot} label={meta.label} size="sm" className="border-white/80 bg-white/80" />
          <div className="flex flex-col items-end gap-1">
            <span className="text-[11px] leading-none text-ink/55">
              {home.checked} of {home.total} checked
            </span>
            <Segments filled={home.checked} total={home.total} color={meta.bar} track="rgba(15,42,46,0.1)" width={12} height={4} gap={3} delay={0.3} />
          </div>
        </div>
      </motion.div>

      <span className="liquid-edge" aria-hidden />
    </MotionLink>
  );
}

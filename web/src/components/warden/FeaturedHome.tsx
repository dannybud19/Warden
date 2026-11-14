"use client";

import Image from "next/image";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { HOME_STATUS, type Home } from "@/lib/homes";
import { Chip, Dot, PillButton, PillLink, Segments, stagger, rise } from "./primitives";

/** Copies a link to the page so the student can send it to their parents. */
export function ShareButton({ href, small = false, label = "Share with parents" }: { href: string; small?: boolean; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = new URL(href, window.location.origin).toString();
    try {
      if (navigator.share) await navigator.share({ title: "Warden check", url });
      else await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* user dismissed the share sheet */
    }
  }
  return (
    <PillButton variant="secondary" small={small} onClick={share} className={small ? "text-[12px]!" : ""}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={copied ? "y" : "n"}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.15 }}
        >
          {copied ? "Link copied" : label}
        </motion.span>
      </AnimatePresence>
    </PillButton>
  );
}

const spring = { type: "spring", stiffness: 240, damping: 24 } as const;

/** The one-home layout's big card: a full-bleed photo with a liquid-glass rim, all text in one glass panel. */
export function FeaturedHome({ home }: { home: Home }) {
  const meta = HOME_STATUS[home.status];
  const flags = home.redFlags;
  return (
    <motion.article
      initial="rest"
      animate="rest"
      whileHover="hover"
      className="relative h-[532px] overflow-hidden rounded-[28px] shadow-card"
    >
      <motion.div className="absolute inset-0" variants={{ rest: { scale: 1 }, hover: { scale: 1.04 } }} transition={spring}>
        <Image src={home.photos.front} alt="" fill sizes="(min-width: 1024px) 870px, 100vw" priority className="object-cover" />
      </motion.div>
      <div aria-hidden className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-ink/30 to-transparent" />

      {home.needsYou && (
        <Chip dot="/warden/dot-red.svg" label="Needs you" tone="glass" className="absolute right-5 top-5 text-[12.5px]! shadow-card" />
      )}

      <motion.div
        className="liquid-glass absolute inset-x-4 bottom-4 rounded-[22px] px-7 pb-6 pt-5"
        variants={stagger}
        initial="hidden"
        animate="show"
      >
        <span className="liquid-edge" aria-hidden />
        <motion.h2 variants={rise} className="truncate text-[30px] font-light leading-[1.15] tracking-[-0.6px]">
          {home.title}
        </motion.h2>
        <motion.p variants={rise} className="mt-1.5 truncate text-[13.5px] leading-[1.4] text-ink/60">
          {[home.meta, home.platform].filter(Boolean).join(" · ")}
        </motion.p>

        <div className="mt-4 flex items-end justify-between gap-8">
          <div className="min-w-0">
            <motion.p variants={rise} className="text-[15px] font-medium leading-[1.4]">
              {flags.length
                ? `Verification agent is sensing doubt. ${flags.length > 1 ? "Several red flags include:" : "One red flag so far:"}`
                : "No red flags so far. Warden is still checking."}
            </motion.p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {flags.map((f) => (
                <motion.li key={f} variants={rise} className="flex items-center gap-[10px] pl-0.5 text-[14px] leading-[1.4] text-ink/85">
                  <Dot src="/warden/dot-red-flag.svg" />
                  {f}
                </motion.li>
              ))}
            </ul>
          </div>
          <motion.div variants={rise} className="flex shrink-0 flex-col items-end">
            <span className="text-[12.5px] leading-[1.4] text-ink/60">
              {home.checked} of {home.total} checked
            </span>
            <div className="mt-1.5">
              <Segments filled={home.checked} total={home.total} color={meta.bar} track="rgba(15,42,46,0.1)" width={26} height={6} gap={4} delay={0.4} />
            </div>
            <div className="mt-5 flex gap-2">
              <PillLink href={home.href}>Open this home&nbsp;&nbsp;→</PillLink>
              <ShareButton href={home.href} />
            </div>
          </motion.div>
        </div>
      </motion.div>
      <span className="liquid-edge" aria-hidden />
    </motion.article>
  );
}

const STEPS = [
  { title: "Forward what they sent you", body: "Chats, emails, the listing link or the contract." },
  { title: "Warden's agents check it", body: "Each one looks for a different kind of red flag." },
  { title: "You get one clear next step", body: "Like a question to ask before you pay anything." },
];

/** Figma "How Warden checks" card (428 × 264). */
export function HowWardenChecks() {
  return (
    <motion.section
      variants={stagger}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      className="relative min-h-[264px] rounded-[24px] border border-white bg-white/70 px-[23px] pb-6 pt-[21px] shadow-glass backdrop-blur-[15px]"
    >
      <motion.h2 variants={rise} className="text-[15px] font-medium leading-[1.4]">How Warden checks a home</motion.h2>
      <ol className="mt-[19px] flex flex-col gap-[26px]">
        {STEPS.map((s, i) => (
          <motion.li key={s.title} variants={rise} className="flex gap-[14px]">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-2xl bg-mint text-[13px] font-semibold text-teal">
              {i + 1}
            </span>
            <span className="-mt-px">
              <span className="block text-[14px] font-medium leading-[1.4]">{s.title}</span>
              <span className="block text-[12.5px] leading-[1.4] text-muted">{s.body}</span>
            </span>
          </motion.li>
        ))}
      </ol>
    </motion.section>
  );
}

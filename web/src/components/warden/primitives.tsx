"use client";

import Image from "next/image";
import Link from "next/link";
import { motion, type HTMLMotionProps } from "motion/react";

/** The Warden mascot render (Figma component "Warden mascot", 21:17). */
export function Mascot({
  width, height, float = false, className = "", priority = false,
}: { width: number; height: number; float?: boolean; className?: string; priority?: boolean }) {
  const img = (
    <Image
      src="/warden/mascot.png" alt="" width={216} height={258} priority={priority}
      className="pointer-events-none size-full object-contain"
    />
  );
  return float ? (
    <motion.div
      aria-hidden
      className={`relative shrink-0 ${className}`}
      style={{ width, height }}
      animate={{ y: [0, -8, 0], rotate: [0, -1.5, 0] }}
      transition={{ duration: 4.2, repeat: Infinity, ease: "easeInOut" }}
    >
      {img}
    </motion.div>
  ) : (
    <div aria-hidden className={`relative shrink-0 ${className}`} style={{ width, height }}>
      {img}
    </div>
  );
}

/** A small coloured dot (design SVG asset). */
export function Dot({ src, size = 8, pulse = false }: { src: string; size?: number; pulse?: boolean }) {
  const img = <Image src={src} alt="" width={size} height={size} unoptimized className="block" />;
  if (!pulse) return <span className="relative block shrink-0" style={{ width: size, height: size }}>{img}</span>;
  return (
    <motion.span
      className="relative block shrink-0"
      style={{ width: size, height: size }}
      animate={{ scale: [1, 1.35, 1], opacity: [1, 0.6, 1] }}
      transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
    >
      {img}
    </motion.span>
  );
}

/** Rounded pill with a dot and a label: status chips everywhere in the design. */
export function Chip({
  dot, label, size = "md", tone = "white", pulse = false, className = "",
}: {
  dot?: string; label: string; size?: "sm" | "md" | "lg"; tone?: "white" | "glass" | "solid"; pulse?: boolean;
  className?: string;
}) {
  const pad = { sm: "py-[5px] pl-[10px] pr-[11px] text-[11.5px]", md: "py-[6px] pl-[11px] pr-[12px] text-[12px]", lg: "py-[8px] pl-[14px] pr-[15px] text-[13px]" }[size];
  const bg = {
    white: "bg-white border-line",
    glass: "bg-white/95 border-white",
    solid: "bg-white/60 border-white backdrop-blur-[10px]",
  }[tone];
  return (
    <span className={`inline-flex shrink-0 items-center gap-[7px] whitespace-nowrap rounded-full border font-medium leading-none text-ink ${pad} ${bg} ${className}`}>
      {dot && <Dot src={dot} pulse={pulse} />}
      <span className="leading-[normal]">{label}</span>
    </span>
  );
}

/** "5 of 8 checked" segmented progress. Segments fill one after another. */
export function Segments({
  filled, total = 8, color, track = "rgba(255,255,255,0.9)", width = 14, height = 5, gap = 3, delay = 0,
}: {
  filled: number; total?: number; color: string; track?: string; width?: number; height?: number; gap?: number;
  delay?: number;
}) {
  return (
    <div className="flex" style={{ gap }} role="img" aria-label={`${filled} of ${total} checked`}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className="relative overflow-hidden rounded-[3px]"
          style={{ width, height, background: track }}
        >
          <motion.span
            className="absolute inset-0 origin-left rounded-[3px]"
            style={{ background: color }}
            initial={{ scaleX: 0 }}
            animate={{ scaleX: i < filled ? 1 : 0 }}
            transition={{ delay: delay + i * 0.06, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          />
        </span>
      ))}
    </div>
  );
}

type ButtonProps = HTMLMotionProps<"button"> & { variant?: "primary" | "secondary" | "soft"; small?: boolean };

/** Pill buttons from the design: teal primary, white secondary, mint soft. */
export function PillButton({ variant = "primary", small = false, className = "", children, ...rest }: ButtonProps) {
  const look = {
    primary: "bg-teal text-white border-teal",
    secondary: "bg-white/90 text-ink border-line",
    soft: "bg-mint text-teal border-mint",
  }[variant];
  const pad = small ? "py-[5px] pl-[10px] pr-[11px] text-[11.5px]" : "px-[18px] py-[10px] text-[13px]";
  return (
    <motion.button
      type="button"
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.96 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      className={`inline-flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-full border font-medium leading-[normal] disabled:cursor-not-allowed disabled:opacity-50 ${look} ${pad} ${className}`}
      {...rest}
    >
      {children}
    </motion.button>
  );
}

const MotionLink = motion.create(Link);

/** A link that looks like the primary pill button. */
export function PillLink({ href, children, className = "" }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <MotionLink
      href={href}
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.96 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-teal bg-teal px-[18px] py-[10px] text-[13px] font-medium leading-[normal] text-white ${className}`}
    >
      {children}
    </MotionLink>
  );
}

/** Stagger container + item for page entrances. */
export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.05 } },
};

export const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const } },
};

/** "Source" links for a finding that cites web pages (e.g. Companies House). Renders nothing without URLs. */
export function SourceLinks({ urls, className = "" }: { urls: string[]; className?: string }) {
  if (!urls.length) return null;
  const host = (u: string) => {
    try {
      return new URL(u).hostname.replace(/^www\./, "");
    } catch {
      return u;
    }
  };
  return (
    <p className={`flex flex-wrap gap-x-3 gap-y-1 text-[12.5px] ${className}`}>
      {urls.map((u) => (
        <a key={u} href={u} target="_blank" rel="noopener noreferrer" className="font-medium text-teal underline underline-offset-2">
          Source: {host(u)} ↗
        </a>
      ))}
    </p>
  );
}

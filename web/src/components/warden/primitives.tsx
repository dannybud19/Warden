"use client";

import Image from "next/image";
import Link from "next/link";
import { useId, useState } from "react";
import { AnimatePresence, motion, type HTMLMotionProps } from "motion/react";
import { ChevronDown } from "lucide-react";

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

/** A long list behind its header: a real button (aria-expanded, aria-controls) inside an optional
 *  heading, with a count and a chevron; the list opens with a short height animation (reduced
 *  motion is respected app-wide). Title and description must be inline content. */
export function Collapsible({
  title, description, count, as: Heading = "div", titleClassName = "", defaultOpen = false, className = "", children,
}: {
  title: React.ReactNode;
  /** A muted line under the title, still part of the header. */
  description?: React.ReactNode;
  /** Shown as a small pill before the chevron, e.g. "3 files". */
  count?: React.ReactNode;
  /** Wrap the button in a heading so the section keeps its place in the outline. */
  as?: "div" | "h2" | "h3";
  titleClassName?: string;
  defaultOpen?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const panel = useId();
  return (
    <div className={className}>
      <Heading className="m-0">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full cursor-pointer items-center gap-3 rounded-[12px] text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal"
        >
          <span className="min-w-0 flex-1">
            <span className={`block ${titleClassName}`}>{title}</span>
            {description && <span className="mt-1 block text-[13px] font-normal text-muted">{description}</span>}
          </span>
          {count !== undefined && (
            <span className="shrink-0 rounded-full bg-field px-2.5 py-0.5 text-[12.5px] font-medium tabular-nums text-ink/70">{count}</span>
          )}
          <motion.span aria-hidden animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }} className="shrink-0 text-muted">
            <ChevronDown size={18} />
          </motion.span>
        </button>
      </Heading>
      <div id={panel}>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              key="panel"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              {children}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

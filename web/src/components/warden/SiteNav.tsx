"use client";

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { motion } from "motion/react";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { Dot, Mascot } from "./primitives";

const ITEMS = [
  { label: "Cases", href: "/" },
  { label: "Inbox", href: "/inbox" },
  { label: "Settings", href: "/settings" },
] as const;

function readName(): string {
  try {
    return localStorage.getItem(STUDENT_NAME_KEY) ?? "";
  } catch {
    return "";
  }
}

/** The student's name, saved when they open a case. Empty on the server. */
export function useStudentName(): string {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener("storage", cb);
      return () => window.removeEventListener("storage", cb);
    },
    readName,
    () => "",
  );
}

/** Glass pill navigation (Figma "Nav · glass pill"). */
export function SiteNav({ active = "Cases" }: { active?: (typeof ITEMS)[number]["label"] }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const name = useStudentName();
  const pill = hovered ?? active;

  return (
    <motion.nav
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className="relative flex h-14 items-center justify-between rounded-full border border-white/95 py-2 pl-[10px] pr-2 shadow-nav"
    >
      <div aria-hidden className="pointer-events-none absolute inset-0 rounded-full bg-white/[0.42] backdrop-blur-[14px]" />
      <div aria-hidden className="pointer-events-none absolute inset-0 rounded-full shadow-[inset_0px_1px_0px_0px_rgba(255,255,255,0.9)]" />

      <Link href="/" className="relative flex items-center gap-2 pl-1.5" aria-label="Warden home">
        <Mascot width={26} height={31} />
        <span className="text-[17px] font-semibold tracking-[0.68px] text-teal">WARDEN</span>
      </Link>

      <ul className="relative hidden items-center gap-1 md:flex" onMouseLeave={() => setHovered(null)}>
        {ITEMS.map((item) => {
          const isActive = item.label === active;
          const inner = (
            <>
              {pill === item.label && (
                <motion.span
                  layoutId="nav-pill"
                  className={`absolute inset-0 rounded-full ${isActive || !hovered ? "bg-white/85 shadow-tab" : "bg-white/55"}`}
                  transition={{ type: "spring", stiffness: 420, damping: 34 }}
                />
              )}
              <span className={`relative text-[13.5px] ${isActive ? "font-medium text-teal" : "text-ink/75"}`}>
                {item.label}
              </span>
            </>
          );
          const cls = "relative block rounded-full px-4 py-2 leading-[normal]";
          return (
            <li key={item.label} onMouseEnter={() => setHovered(item.label)}>
              <Link href={item.href} className={cls} aria-current={isActive ? "page" : undefined}>
                {inner}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="relative flex items-center gap-2">
        <span className="hidden items-center gap-1.5 rounded-full bg-white/60 px-3 py-[7px] text-[12px] font-medium leading-[normal] sm:inline-flex">
          <Dot src="/warden/dot-whatsapp.svg" size={7} />
          WhatsApp connected
        </span>
        <span className="flex size-[38px] items-center justify-center rounded-full bg-teal text-[14px] font-medium text-white">
          {(name.trim()[0] ?? "W").toUpperCase()}
        </span>
      </div>
    </motion.nav>
  );
}

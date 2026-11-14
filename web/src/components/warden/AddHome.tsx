"use client";

import Image from "next/image";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import * as api from "@/lib/api";
import { STUDENT_NAME_KEY } from "@/lib/config";
import { rememberCase } from "@/lib/homes";
import { Mascot, PillButton } from "./primitives";
import { useStudentName } from "./SiteNav";

const SIZES = {
  lg: {
    card: "h-[258px] rounded-[22px]", halo: 88, haloTop: 57, button: 64, buttonSvg: 100, buttonTop: 69,
    buttonInset: { top: -10, left: -18 }, plus: 24, plusSrc: "/warden/icon-plus-lg.svg",
    haloSrc: "/warden/add-halo-lg.svg", buttonSrc: "/warden/add-button-lg.svg", titleTop: 155,
  },
  md: {
    card: "h-[252px] rounded-[24px]", halo: 80, haloTop: 39, button: 58, buttonSvg: 94, buttonTop: 50,
    buttonInset: { top: -10, left: -18 }, plus: 22, plusSrc: "/warden/icon-plus-md.svg",
    haloSrc: "/warden/add-halo-md.svg", buttonSrc: "/warden/add-button-md.svg", titleTop: 131,
  },
} as const;

/** Dashed "Add a home" folder (Figma "Folder · Add a home"). Opens the add-home dialog. */
export function AddHomeCard({ size = "lg", title = "Add a home" }: { size?: keyof typeof SIZES; title?: string }) {
  const [open, setOpen] = useState(false);
  const s = SIZES[size];
  return (
    <>
      <motion.button
        type="button"
        onClick={() => setOpen(true)}
        initial="rest"
        animate="rest"
        whileHover="hover"
        whileTap={{ scale: 0.985 }}
        className={`relative block w-full cursor-pointer overflow-hidden border border-dashed border-aqua bg-white/50 text-center ${s.card}`}
      >
        <div className="absolute inset-x-0 flex justify-center" style={{ top: s.haloTop }}>
          <motion.div
            variants={{ rest: { scale: 1 }, hover: { scale: 1.18 } }}
            transition={{ type: "spring", stiffness: 260, damping: 18 }}
          >
            <motion.div
              animate={{ scale: [1, 1.08, 1], opacity: [1, 0.75, 1] }}
              transition={{ duration: 2.8, repeat: Infinity, ease: "easeInOut" }}
            >
              <Image src={s.haloSrc} alt="" width={s.halo} height={s.halo} unoptimized className="block" />
            </motion.div>
          </motion.div>
        </div>
        <div className="absolute inset-x-0 flex justify-center" style={{ top: s.buttonTop }}>
          <motion.div
            className="relative"
            style={{ width: s.button, height: s.button }}
            variants={{ rest: { scale: 1 }, hover: { scale: 1.07 } }}
            transition={{ type: "spring", stiffness: 400, damping: 20 }}
          >
            <Image
              src={s.buttonSrc} alt="" width={s.buttonSvg} height={s.buttonSvg} unoptimized
              className="absolute block max-w-none"
              style={{ top: s.buttonInset.top, left: s.buttonInset.left }}
            />
            <motion.div
              className="absolute inset-0 flex items-center justify-center"
              variants={{ rest: { rotate: 0 }, hover: { rotate: 90 } }}
              transition={{ type: "spring", stiffness: 300, damping: 18 }}
            >
              <Image src={s.plusSrc} alt="" width={s.plus} height={s.plus} unoptimized className="block" />
            </motion.div>
          </motion.div>
        </div>
        <span className="absolute inset-x-0 block text-[22px] font-light leading-[1.4] tracking-[-0.03em]" style={{ top: s.titleTop }}>
          {title}
        </span>
        <span className="absolute inset-x-0 block text-[12.5px] leading-[1.4] text-muted" style={{ top: s.titleTop + 32 }}>
          Forward a listing link, a chat or a contract.
        </span>
      </motion.button>
      <AddHomeDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function num(v: string): number | undefined {
  const n = Number(v.replace(/[£,\s]/g, ""));
  return v.trim() && Number.isFinite(n) ? n : undefined;
}

/** A full UK postcode found in free text (e.g. "… London E1 4AA"), formatted "E1 4AA", else undefined. */
function ukPostcode(text: string | undefined): string | undefined {
  const m = /\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b/i.exec(text ?? "");
  return m ? `${m[1]} ${m[2]}`.toUpperCase() : undefined;
}

const field =
  "w-full rounded-[14px] border border-line bg-white px-4 py-3 text-[14px] text-ink outline-none transition placeholder:text-hint focus:border-aqua focus:ring-4 focus:ring-aqua/15";

export function AddHomeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const storedName = useStudentName();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const t = setTimeout(() => first.current?.focus(), 60);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [open, onClose]);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim() || undefined;
    setBusy(true);
    setError(null);
    const name = get("name");
    if (name) {
      try {
        localStorage.setItem(STUDENT_NAME_KEY, name);
      } catch {
        /* storage unavailable */
      }
    }
    try {
      const agency = get("agency");
      const companyNumber = get("company_number")?.toUpperCase();
      const agentName = get("agent_name");
      const address = get("address");
      const c = await api.openCase({
        student: {},
        listing: { url: get("url"), address, postcode: ukPostcode(address), rent_pcm: num(String(f.get("rent") ?? "")) },
        landlord: agency || companyNumber || agentName
          ? { company_name: agency, company_number: companyNumber, name: agentName }
          : undefined,
      });
      if (!c.case_id) throw new Error("The server did not return a case id.");
      rememberCase(c.case_id);
      router.push(`/case/${c.case_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-ink/25 backdrop-blur-[6px]" onClick={onClose} aria-hidden />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-home-title"
            className="relative w-full max-w-[480px] overflow-hidden rounded-[28px] border border-white bg-white/90 p-7 shadow-glass backdrop-blur-[15px]"
            initial={{ y: 40, scale: 0.96, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={{ y: 24, scale: 0.97, opacity: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 30 }}
          >
            <div className="flex items-center gap-3">
              <Mascot width={40} height={48} float />
              <div>
                <h2 id="add-home-title" className="text-[22px] font-light tracking-[-0.03em]">Add a home</h2>
                <p className="text-[13px] text-muted">Tell Warden what you know. You can forward chats next.</p>
              </div>
            </div>
            <form className="mt-6 flex flex-col gap-3" onSubmit={onSubmit}>
              <input ref={first} name="url" type="url" placeholder="Listing link (SpareRoom, Rightmove…)" className={field} />
              <input name="address" placeholder="Address, e.g. Flat 2, 41 Mile End Road, London E1" className={field} />
              <div className="grid grid-cols-2 gap-3">
                <input name="rent" inputMode="decimal" placeholder="Rent £ pcm" className={field} />
                <input name="agency" placeholder="Agency or landlord" className={field} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <input name="company_number" placeholder="Company number (optional)" className={field} />
                <input name="agent_name" placeholder="Agent's name (optional)" className={field} />
              </div>
              {!storedName && <input name="name" placeholder="Your first name" autoComplete="given-name" className={field} />}
              <AnimatePresence>
                {error && (
                  <motion.p
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="rounded-[14px] bg-[#fbe6e1] px-4 py-3 text-[13px] text-[#a8402b]"
                  >
                    Couldn&apos;t add this home: {error}
                  </motion.p>
                )}
              </AnimatePresence>
              <div className="mt-2 flex justify-end gap-2">
                <PillButton variant="secondary" onClick={onClose}>Cancel</PillButton>
                <PillButton type="submit" disabled={busy}>{busy ? "Adding…" : "Start checking  →"}</PillButton>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

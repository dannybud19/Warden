"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";

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
export function AddHomeCard({ size = "lg", title = "New case" }: { size?: keyof typeof SIZES; title?: string }) {
  const router = useRouter();
  const s = SIZES[size];
  return (
    <>
      <motion.button
        type="button"
        onClick={() => router.push("/new")}
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
          Found a place? Warden’s agents will check it.
        </span>
      </motion.button>
    </>
  );
}

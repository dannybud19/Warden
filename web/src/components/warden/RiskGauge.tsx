"use client";

import { useEffect } from "react";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import type { RiskCategory, RiskDisplay } from "@/lib/present";

const DIAL = { cx: 130, cy: 124, r: 100, width: 22, from: 210, sweep: 240 };
const TRACK = "#e6eef0";
const ZONES: { category: RiskCategory; from: number; to: number; color: string }[] = [
  { category: "no_red_flags", from: 0, to: 28, color: "#2e9a7c" },
  { category: "concerns", from: 36, to: 64, color: "#d99a2b" },
  { category: "high", from: 72, to: 100, color: "#e06a52" },
];

function dialPoint(position: number, radius = DIAL.r): [number, number] {
  const angle = ((DIAL.from - DIAL.sweep * position / 100) * Math.PI) / 180;
  return [DIAL.cx + radius * Math.cos(angle), DIAL.cy - radius * Math.sin(angle)];
}

function arcPath(from: number, to: number): string {
  const [x0, y0] = dialPoint(from);
  const [x1, y1] = dialPoint(to);
  return `M ${x0} ${y0} A ${DIAL.r} ${DIAL.r} 0 0 1 ${x1} ${y1}`;
}

function needlePath(position: number): string {
  const [tx, ty] = dialPoint(position, DIAL.r - DIAL.width / 2 - 8);
  const [lx, ly] = dialPoint(position + 25, 5);
  const [rx, ry] = dialPoint(position - 25, 5);
  const [bx, by] = dialPoint(position + 50, 12);
  return `M ${tx} ${ty} L ${lx} ${ly} L ${bx} ${by} L ${rx} ${ry} Z`;
}

/** Risk categories on the dial; weighted verification progress has its own bar beneath it. */
export function RiskGauge({ risk, progress }: { risk: RiskDisplay; progress: number }) {
  const position = useMotionValue(risk.needlePosition ?? 50);
  const needle = useTransform(position, needlePath);
  const reduceMotion = useReducedMotion();
  useEffect(() => {
    if (risk.needlePosition === null) return;
    const animation = animate(position, risk.needlePosition, {
      duration: reduceMotion ? 0 : 0.8, ease: [0.22, 1, 0.36, 1],
    });
    return () => animation.stop();
  }, [position, risk.needlePosition, reduceMotion]);

  return (
    <div className="w-[260px] max-w-full shrink-0">
      <div className="relative h-[232px]" role="img" aria-label={`Risk level: ${risk.label}. ${risk.headline}`}>
        <svg width={260} height={200} viewBox="0 0 260 200" className="max-w-full overflow-visible" aria-hidden="true">
          {ZONES.map((zone) => (
            <path key={zone.category} d={arcPath(zone.from, zone.to)} fill="none"
              stroke={risk.category === "unknown" ? TRACK : zone.color}
              strokeOpacity={risk.category === "unknown" || risk.category === zone.category ? 1 : 0.22}
              strokeWidth={DIAL.width} strokeLinecap="round" />
          ))}
          {risk.needlePosition !== null && <>
            <motion.path d={needle} fill="#17393e" style={{ filter: "drop-shadow(0 2px 3px rgba(16,40,44,.25))" }} />
            <circle cx={DIAL.cx} cy={DIAL.cy} r={9} fill="#17393e" />
            <circle cx={DIAL.cx} cy={DIAL.cy} r={3.5} fill="white" />
          </>}
          {risk.needlePosition === null && <text x={DIAL.cx} y={DIAL.cy + 2} textAnchor="middle" fill={risk.color} fontSize={30} fontWeight={500}>?</text>}
        </svg>
        <div className="absolute inset-x-2 top-[147px] text-center">
          <p className="text-[24px] font-semibold leading-[1.15] tracking-[-0.03em]" style={{ color: risk.color }}>{risk.label}</p>
          <p className="mt-1.5 text-[13px] text-muted">Risk level</p>
        </div>
      </div>
      <div className="px-1">
        <div className="mb-2 flex items-center justify-between gap-2 text-[12.5px]">
          <span className="font-medium text-ink/80">Verification progress</span>
          <span className="tabular-nums text-muted">{progress}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-line/70" role="progressbar"
          aria-label="Verification progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}
          aria-valuetext={`${progress}% weighted verification progress`}>
          <motion.div className="h-full rounded-full bg-teal" initial={false} animate={{ width: `${progress}%` }}
            transition={{ duration: reduceMotion ? 0 : 0.5 }} />
        </div>
      </div>
    </div>
  );
}

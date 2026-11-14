"use client";

import { useEffect, useRef } from "react";

// Animated halftone "pixel" background for the teal hero. A grid of square dots whose size follows a few
// slowly drifting soft blobs, quantised with a 4x4 Bayer dither so it reads as pixels. Pure canvas, no
// dependencies, no interaction. Pauses off-screen and when the tab is hidden; draws a single still frame
// when the viewer prefers reduced motion.

type RGB = readonly [number, number, number];

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);
const LEVELS = 4;

interface Blob {
  x: number; y: number; ax: number; ay: number; sx: number; sy: number; p: number; r: number; a: number;
}

// Positions: x as a fraction of width, y of height. Radius in units of the band's height.
const BLOBS: Blob[] = [
  { x: 0.16, y: 0.4, ax: 0.1, ay: 0.25, sx: 0.11, sy: 0.17, p: 0.0, r: 0.55, a: 0.85 },
  { x: 0.52, y: 0.25, ax: 0.14, ay: 0.2, sx: 0.08, sy: 0.13, p: 1.7, r: 0.6, a: 0.7 },
  { x: 0.82, y: 0.45, ax: 0.09, ay: 0.3, sx: 0.12, sy: 0.09, p: 3.1, r: 0.65, a: 0.9 },
  { x: 0.34, y: 0.7, ax: 0.16, ay: 0.15, sx: 0.07, sy: 0.15, p: 4.4, r: 0.45, a: 0.55 },
];

const TEAL: RGB = [19, 138, 147]; // --color-teal

/** Returns [x0, y0, x1, y1] in CSS px: an area (e.g. behind text) where the pixels thin right out. */
export type QuietZone = (width: number, height: number) => readonly [number, number, number, number];

const smoothstep = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

export function PixelField({
  className = "",
  cell = 8,
  color = TEAL,
  maxAlpha = 0.46,
  quiet,
}: {
  className?: string;
  cell?: number;
  color?: RGB;
  maxAlpha?: number;
  quiet?: QuietZone;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0;
    let h = 0;
    let raf = 0;
    let visible = true;
    const start = performance.now();
    const style = `rgb(${color[0]},${color[1]},${color[2]})`;

    // One batch of rects per dot size, so each frame is only LEVELS fills.
    const fills = Array.from({ length: LEVELS }, (_, l) => ({
      alpha: maxAlpha * (0.5 + (0.5 * (l + 1)) / LEVELS),
      rects: [] as number[],
    }));

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas!.clientWidth;
      h = canvas!.clientHeight;
      canvas!.width = Math.round(w * dpr);
      canvas!.height = Math.round(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw(now: number) {
      const t = (now - start) / 1000;
      const cols = Math.ceil(w / cell);
      const rows = Math.ceil(h / cell);
      const blobs = BLOBS.map((b) => ({
        x: (b.x + Math.sin(t * b.sx + b.p) * b.ax) * w,
        y: (b.y + Math.cos(t * b.sy + b.p * 1.3) * b.ay) * h,
        r2: (b.r * h) ** 2,
        a: b.a * (0.8 + 0.2 * Math.sin(t * 0.4 + b.p)),
      }));
      for (const f of fills) f.rects.length = 0;
      const q = quiet?.(w, h);
      const soft = 48;

      for (let j = 0; j < rows; j++) {
        const cy = j * cell + cell / 2;
        // fade out towards the bottom so the band melts into the page
        const vfade = Math.min(1, Math.max(0, (1 - cy / h) / 0.8)) ** 1.2;
        for (let i = 0; i < cols; i++) {
          const cx = i * cell + cell / 2;
          const nx = cx / w;
          let v = 0;
          for (const b of blobs) {
            const dx = cx - b.x;
            const dy = cy - b.y;
            v += b.a * Math.exp(-(dx * dx + dy * dy) / b.r2);
          }
          const hfade = Math.min(1, nx * 8, (1 - nx) * 8);
          v *= 1.45 * vfade * (0.35 + 0.65 * hfade);
          if (q) {
            const inside = smoothstep(q[0] - soft, q[0] + soft, cx) * smoothstep(q[2] + soft, q[2] - soft, cx)
              * smoothstep(q[1] - soft, q[1] + soft, cy) * smoothstep(q[3] + soft, q[3] - soft, cy);
            v *= 1 - 0.85 * inside;
          }
          const level = Math.min(LEVELS, Math.floor(v * LEVELS + BAYER[(i & 3) + (j & 3) * 4]));
          if (level <= 0) continue;
          const size = Math.max(1, Math.round((level / LEVELS) * (cell - 2)));
          const off = (cell - size) / 2;
          fills[level - 1].rects.push(Math.round(i * cell + off), Math.round(j * cell + off), size);
        }
      }

      ctx!.clearRect(0, 0, w, h);
      ctx!.fillStyle = style;
      for (const f of fills) {
        if (!f.rects.length) continue;
        ctx!.globalAlpha = Math.min(1, f.alpha);
        ctx!.beginPath();
        for (let k = 0; k < f.rects.length; k += 3) ctx!.rect(f.rects[k], f.rects[k + 1], f.rects[k + 2], f.rects[k + 2]);
        ctx!.fill();
      }
      ctx!.globalAlpha = 1;
    }

    function loop(now: number) {
      draw(now);
      raf = visible && !document.hidden ? requestAnimationFrame(loop) : 0;
    }
    function wake() {
      if (!reduce && !raf && visible && !document.hidden) raf = requestAnimationFrame(loop);
    }

    resize();
    const ro = new ResizeObserver(() => {
      resize();
      if (reduce) draw(start);
    });
    ro.observe(canvas);
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      wake();
    });
    io.observe(canvas);
    document.addEventListener("visibilitychange", wake);

    if (reduce) draw(start);
    else raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", wake);
    };
  }, [cell, color, maxAlpha, quiet]);

  return <canvas ref={ref} aria-hidden className={`pointer-events-none block ${className}`} />;
}

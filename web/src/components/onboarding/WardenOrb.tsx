"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { motion } from "motion/react";

// Warden as a living voice orb: a glass ball of flowing teal light with Warden's eyes.
// Drawn with a small WebGL shader; the ribbons speed up and brighten with `levelRef` (0..1).
// Falls back to a CSS gradient ball if WebGL isn't available.

export type OrbMood = "connecting" | "listening" | "speaking" | "idle";

const VERT = `attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }`;

const FRAG = `
precision highp float;
uniform vec2 uSize;
uniform float uTime;
uniform float uLevel;
uniform float uSpeak;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) { float v = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; } return v; }
vec2 rot(vec2 p, float a) { float c = cos(a), s = sin(a); return vec2(c * p.x - s * p.y, s * p.x + c * p.y); }

// A folded membrane inside the orb: x = crease light (thin bright line + glow), y = which side of the fold.
vec2 fold(vec2 p, float ang, float off, float amp, float freq, float ph, float t) {
  vec2 q = rot(p, ang);
  // long, gentle arcs like a folded silk sheet
  float y = off + amp * sin(q.x * freq + ph + t) + 0.03 * sin(q.x * freq * 1.7 - t * 0.9 + ph);
  float d = q.y - y;
  float crease = 0.85 * exp(-d * d / 0.0016) + 0.45 * exp(-d * d / 0.022);
  // the lifted sheet: lightest right by the crease, fading away from it
  float sheet = smoothstep(0.0, 0.06, d) * exp(-max(d, 0.0) * 2.2);
  return vec2(crease, sheet);
}

void main() {
  vec2 uv = (gl_FragCoord.xy * 2.0 - uSize) / min(uSize.x, uSize.y);
  float t = uTime * (0.35 + 0.55 * uSpeak + 0.6 * uLevel);
  float ang = atan(uv.y, uv.x);
  float r = length(uv);

  // the outline breathes and wobbles, more when there's voice
  float wob = 0.045 * (noise(vec2(ang * 1.4 + uTime * 0.5, uTime * 0.25)) - 0.5) + uLevel * 0.035 * sin(ang * 3.0 + uTime * 2.2);
  float R = 0.64 * (1.0 + wob);
  vec2 p = uv / R;
  float pd = length(p);

  vec3 core  = vec3(0.22, 0.94, 0.80);  // vivid tosca
  vec3 deep  = vec3(0.04, 0.70, 0.72);  // deeper teal
  vec3 cool  = vec3(0.22, 0.56, 1.00);  // blue on the folds
  vec3 mint  = vec3(0.55, 1.00, 0.82);
  vec3 white = vec3(1.0);

  // luminous body: bright core falling to deeper teal at the edge, slowly swirling
  vec3 col = mix(core, deep, smoothstep(0.15, 1.0, pd));
  col = mix(col, mint, 0.28 * (1.0 - smoothstep(0.0, 0.55, pd)));
  float sw = fbm(p * 1.3 + vec2(t * 0.15, -t * 0.1));
  col = mix(col, core * 1.06, 0.22 * sw);

  // three folded sheets drifting around
  vec2 f1 = fold(p, t * 0.19, -0.40, 0.30 + 0.12 * uLevel, 1.2, 0.0, t * 0.9);
  vec2 f2 = fold(p, -t * 0.15 + 2.3, 0.42, 0.26 + 0.12 * uLevel, 1.0, 1.7, t * 0.75);
  // folded sheets: lighter where lifted, cooler blue toward the rim
  col = mix(col, vec3(0.62, 1.0, 0.92), 0.38 * (f1.y + f2.y));
  col = mix(col, cool, 0.32 * smoothstep(0.55, 1.0, pd) * (0.4 + 0.6 * sin(ang + t * 0.4) * 0.5 + 0.3));
  float creases = (f1.x + 0.85 * f2.x) * (0.35 + 0.65 * smoothstep(0.15, 0.95, pd));
  col += white * creases * (0.75 + 0.5 * uLevel);

  // light catching part of the rim, and a soft colour fringe
  float rim = smoothstep(0.7, 1.0, pd) * (0.5 + 0.5 * sin(ang * 2.0 + t * 0.8));
  col = mix(col, white, rim * 0.5);
  col += vec3(-0.06, 0.0, 0.14) * smoothstep(0.82, 1.0, pd) * (0.5 + 0.5 * sin(ang - t * 0.5));

  // soft, blurred edge (no outline) and a wide glow that dies out before the canvas edge
  float body = 1.0 - smoothstep(0.88, 1.04, pd);
  float halo = exp(-max(r - R, 0.0) * 5.5) * (0.4 + 0.7 * uLevel) * (1.0 - smoothstep(0.78, 0.99, r));
  vec3 hcol = mix(vec3(0.78, 1.0, 0.97), core, 0.55);
  vec3 outc = clamp(col, 0.0, 1.0) * body + hcol * halo * (1.0 - body);
  float a = clamp(body + halo * (1.0 - body) * 0.85, 0.0, 1.0);
  gl_FragColor = vec4(outc, a);
}
`;

function useOrbCanvas(canvasRef: RefObject<HTMLCanvasElement | null>, levelRef: RefObject<number>, speaking: boolean) {
  const [ok, setOk] = useState(true);
  const speakRef = useRef(0);
  const speakingRef = useRef(speaking);
  useEffect(() => {
    speakingRef.current = speaking;
  }, [speaking]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas?.getContext("webgl", { alpha: true, premultipliedAlpha: true, antialias: true });
    if (!canvas || !gl) {
      setOk(false);
      return;
    }
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
    };
    const vs = sh(gl.VERTEX_SHADER, VERT), fs = sh(gl.FRAGMENT_SHADER, FRAG);
    const prog = gl.createProgram();
    if (!vs || !fs || !prog) return setOk(false);
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return setOk(false);
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    const uSize = gl.getUniformLocation(prog, "uSize"), uTime = gl.getUniformLocation(prog, "uTime");
    const uLevel = gl.getUniformLocation(prog, "uLevel"), uSpeak = gl.getUniformLocation(prog, "uSpeak");

    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0, level = 0;
    const start = performance.now();
    const draw = (now: number) => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      level += ((levelRef.current ?? 0) - level) * 0.18;
      speakRef.current += ((speakingRef.current ? 1 : 0) - speakRef.current) * 0.06;
      gl.uniform2f(uSize, w, h);
      gl.uniform1f(uTime, reduce ? 0 : (now - start) / 1000);
      gl.uniform1f(uLevel, reduce ? 0 : Math.min(1, level));
      gl.uniform1f(uSpeak, speakRef.current);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [canvasRef, levelRef]);
  return ok;
}

/** Warden's eyes on the orb: blink every few seconds, look around while connecting, perk up when you talk. */
function Eyes({ mood, size }: { mood: OrbMood; size: number }) {
  const [blink, setBlink] = useState(false);
  const [wander, setWander] = useState({ x: 0, y: 0 });
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    const loop = () => {
      setBlink(true);
      setTimeout(() => setBlink(false), 140);
      t = setTimeout(loop, 2600 + Math.random() * 2600);
    };
    t = setTimeout(loop, 1400);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    if (mood !== "connecting") return;
    const id = setInterval(() => setWander({ x: (Math.random() - 0.5) * 0.12, y: (Math.random() - 0.5) * 0.05 }), 900);
    return () => clearInterval(id);
  }, [mood]);
  // look around while connecting, glance up while listening, straight ahead otherwise
  const look = mood === "connecting" ? wander : { x: 0, y: mood === "listening" ? -0.03 : 0 };

  const w = size * 0.075, h = size * 0.165;
  return (
    <motion.div
      className="pointer-events-none absolute left-1/2 top-[44%] flex -translate-x-1/2 -translate-y-1/2"
      style={{ gap: size * 0.11 }}
      animate={{
        x: look.x * size,
        y: look.y * size + (mood === "speaking" ? -size * 0.012 : 0),
      }}
      transition={{ type: "spring", stiffness: 140, damping: 16 }}
    >
      {[0, 1].map((i) => (
        <motion.span
          key={i}
          className="block rounded-full"
          style={{
            width: w,
            height: h,
            background: "linear-gradient(180deg, #145158, #0a2c30)",
            boxShadow: "inset 0 2px 3px rgba(255,255,255,0.18), 0 1px 6px rgba(6,40,44,0.25)",
          }}
          animate={{ scaleY: blink ? 0.1 : mood === "speaking" ? [1, 0.9, 1] : 1 }}
          transition={blink ? { duration: 0.07 } : { duration: 0.6, repeat: mood === "speaking" ? Infinity : 0 }}
        />
      ))}
    </motion.div>
  );
}

export function WardenOrb({ size, mood, levelRef }: { size: number; mood: OrbMood; levelRef: RefObject<number> }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const webgl = useOrbCanvas(canvasRef, levelRef, mood === "speaking");
  return (
    <div className="relative" style={{ width: size, height: size }} role="img" aria-label={`Warden is ${mood}`}>
      {webgl ? (
        <canvas ref={canvasRef} className="absolute inset-0 size-full" />
      ) : (
        <div
          className="absolute inset-[11%] rounded-full"
          style={{
            background:
              "radial-gradient(circle at 34% 28%, rgba(255,255,255,0.5), transparent 40%), linear-gradient(180deg, #5ee6d8, #0e9aa1)",
            boxShadow: "0 0 60px rgba(34,211,238,0.45)",
          }}
        />
      )}
      <Eyes mood={mood} size={size} />
    </div>
  );
}

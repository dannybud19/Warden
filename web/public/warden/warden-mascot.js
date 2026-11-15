/*
  <warden-mascot> — the Warden mascot as a drop-in web component.

  Usage
    <script type="module" src="/warden/warden-mascot.js"></script>
    <warden-mascot state="default" assets="/warden/"></warden-mascot>

  States: default | thinking | green | amber | red | stop
  Change state by setting the attribute or the property:
    el.setAttribute('state', 'red')      el.state = 'red'

  Assets: warden-default.webp, warden-green.webp, warden-amber.webp,
  warden-red.webp, warden-stop.webp, served from the `assets` folder
  (default "./"). Or set window.WARDEN_ASSETS = { default: url, ... } first.

  Fires a "wardenstatechange" event when the visible state changes.
  Size it with CSS width; height follows a 1000:1100 box (room for the floor reflection).
*/
(() => {
  if (customElements.get('warden-mascot')) return;

  const W = 1000, H = 920, VH = 1100, TS = 1024, STEP = 8;
  const STATES = ['default', 'wave', 'green', 'amber', 'red', 'stop'];
  const TEXOF = { wave: 'default' };
  const TEXTURES = ['default', 'green', 'amber', 'red', 'stop', 'stop-sign', 'amber-flag', 'red-excl'];

  // ---- rig data, in each source image's own pixel coordinates ----
  const RIGS = {
    default: { fx: 445, fy: 886, s: 1,
      eyes: [[397, 522], [500, 522]], eyeR: [30, 50], eyeOn: [1, 1],
      cap: [272, 630, 452] },
    wave: { fx: 445, fy: 886, s: 1,
      eyes: [[397, 522], [500, 522]], eyeR: [30, 50], eyeOn: [1, 1],
      cap: [272, 630, 452],
      armB: { S: [650, 588], H: [692, 735], rects: [[645, 556, 735, 770]], full: 0 } },
    green: { fx: 445, fy: 886, s: 1,
      cap: [272, 630, 452],
      armA: { S: [258, 600], E: [210, 573], H: [175, 535], rects: [[60, 300, 250, 700]] },
      cloth: { P0: [178, 560], U: [0.322, -0.946], N: [-0.946, -0.322], s: [80, 100], d: 95, rect: [60, 300, 250, 700] } },
    amber: { fx: 432, fy: 884, s: 1,
      eyes: [[390, 528], [0, 0]], eyeR: [28, 45], eyeOn: [1, 0],
      cap: [250, 565, 447],
      layers: [{ tex: 'amber-flag', motion: 'tilt', pivot: [420, 712], back: [390, 672, 450, 745],
        cloth: { P0: [395, 770], U: [0.471, -0.881], N: [0.881, 0.471], s: [175, 205], d: 150, rect: [440, 520, 640, 700] } }] },
    red: { fx: 445, fy: 880, s: 1.171, sy: 1.036,
      eyes: [[407, 530], [490, 530]], eyeR: [26, 44], eyeOn: [1, 1],
      cap: [318, 578, 455],
      armA: { S: [305, 585], E: [255, 515], H: [215, 455], rects: [[150, 140, 302, 625], [290, 140, 495, 322]] },
      cloth: { P0: [212, 462], U: [0.383, -0.924], N: [0.924, 0.383], s: [205, 235], d: 190, rect: [290, 140, 495, 322] },
      layers: [{ tex: 'red-excl', motion: 'pop', pivot: [660, 300] }] },
    stop: { fx: 360, fy: 952, s: 0.935,
      eyes: [[318, 563], [432, 563]], eyeR: [28, 48], eyeOn: [1, 1],
      cap: [203, 470, 458],
      layers: [{ tex: 'stop-sign', motion: 'sign', pivot: [612, 935] }] }
  };

  // convert a rig to canvas coordinates
  function toCanvas(r) {
    const sx = r.s, sy = r.sy || r.s, sm = (sx + sy) / 2;
    const P = ([x, y]) => [520 + (x - r.fx) * sx, 900 - (r.fy - y) * sy];
    const nrm = ([x, y]) => { const l = Math.hypot(x, y); return [x / l, y / l]; };
    const R = ([x0, y0, x1, y1]) => [...P([x0, y0]), ...P([x1, y1])];
    const out = { eyes: [[0, 0], [0, 0]], eyeR: [1, 1], eyeOn: [0, 0] };
    if (r.eyes) { out.eyes = r.eyes.map(P); out.eyeR = [r.eyeR[0] * sx, r.eyeR[1] * sy]; out.eyeOn = r.eyeOn; }
    const [cx0, cy] = P([r.cap[0], r.cap[2]]), [cx1] = P([r.cap[1], r.cap[2]]);
    out.cap = [cx0, cx1, cy];
    if (r.armA) out.armA = { S: P(r.armA.S), E: P(r.armA.E), H: P(r.armA.H), rects: r.armA.rects.map(R) };
    if (r.cloth) out.cloth = { P0: P(r.cloth.P0), U: nrm([r.cloth.U[0] * sx, r.cloth.U[1] * sy]), N: nrm([r.cloth.N[0] / sx, r.cloth.N[1] / sy]), s: r.cloth.s.map(v => v * sm), d: r.cloth.d * sm, rect: R(r.cloth.rect) };
    if (r.armB) out.armB = { S: P(r.armB.S), H: P(r.armB.H), rects: r.armB.rects.map(R), full: r.armB.full };
    if (r.pop) out.pop = { C: P(r.pop.C), rect: R(r.pop.rect) };
    const cl = c => ({ P0: P(c.P0), U: nrm([c.U[0] * sx, c.U[1] * sy]), N: nrm([c.N[0] / sx, c.N[1] / sy]), s: c.s.map(v => v * sm), d: c.d * sm, rect: R(c.rect) });
    out.layers = (r.layers || []).map(L => ({ tex: L.tex, motion: L.motion, pivot: P(L.pivot),
      back: L.back ? R(L.back) : null, cloth: L.cloth ? cl(L.cloth) : null }));
    return out;
  }

  const VS = `
  precision highp float;
  attribute vec2 aPos;
  uniform vec2 uRes; uniform float uView;
  uniform vec2 uBodyS; uniform float uBodyR, uBodyH, uMirror;
  uniform float uAOn; uniform vec2 uAS, uAE, uAH; uniform float uA1, uA2; uniform vec4 uAR1, uAR2;
  uniform float uCOn; uniform vec2 uCP0, uCU, uCN, uCS; uniform float uCD; uniform vec4 uCR;
  uniform float uClothT, uClothAmp, uClothDrag;
  uniform float uBOn, uBFull; uniform vec2 uBS, uBH; uniform float uB; uniform vec4 uBR1, uBR2;
  uniform float uPOn; uniform vec2 uPC; uniform vec4 uPR; uniform float uPScale, uPRot;
  uniform vec2 uE1, uE2, uER, uEOn; uniform float uBlink; uniform vec2 uLook;
  uniform vec3 uCapR; uniform vec2 uCap;
  uniform float uJelly;
  uniform float uRigOn, uRigA, uRigS; uniform vec2 uRigT, uRigP;
  uniform float uMOn; uniform vec4 uMR; uniform vec2 uMT;
  varying vec2 vUV; varying float vShade; varying vec2 vRest; varying float vFade;

  float rw(vec4 r, vec2 p) {
    float f = 6.0;
    return smoothstep(r.x - f, r.x + f, p.x) * smoothstep(r.z + f, r.z - f, p.x)
         * smoothstep(r.y - f, r.y + f, p.y) * smoothstep(r.w + f, r.w - f, p.y);
  }
  vec2 rot(vec2 p, vec2 o, float a) {
    float c = cos(a), s = sin(a); vec2 d = p - o;
    return o + vec2(c * d.x - s * d.y, s * d.x + c * d.y);
  }
  float eyeW(vec2 p, vec2 c) { return 1.0 - smoothstep(0.55, 1.0, length((p - c) / uER)); }

  void main() {
    vec2 a = aPos, p = aPos;
    vUV = aPos / vec2(1024.0); vShade = 0.0; vRest = aPos;

    if (uEOn.x > 0.5) { float w = eyeW(a, uE1); p.y = uE1.y + (p.y - uE1.y) * (1.0 - 0.92 * uBlink * w); p += uLook * w; }
    if (uEOn.y > 0.5) { float w = eyeW(a, uE2); p.y = uE2.y + (p.y - uE2.y) * (1.0 - 0.92 * uBlink * w); p += uLook * w; }

    float regA = uAOn * max(rw(uAR1, a), rw(uAR2, a));
    float regB = uBOn * max(rw(uBR1, a), rw(uBR2, a));
    float regP = uPOn * rw(uPR, a);

    if (uCOn > 0.5) {
      vec2 q = a - uCP0;
      float d = dot(q, uCN), s = dot(q, uCU);
      float cw = smoothstep(4.0, uCD, d) * smoothstep(uCS.x, uCS.y, s) * rw(uCR, a);
      float ph = uClothT - d * 0.055;
      p += uCU * (uClothAmp * cw * sin(ph));
      p += uCN * (-uClothAmp * 0.9 * cw * (0.5 + 0.5 * cos(ph * 0.9 + 0.6)));
      p = mix(p, rot(p, uCP0 + uCU * uCS.x, uClothDrag), cw);
      vShade = cw * cos(ph) * 0.10;
    }

    if (uAOn > 0.5) {
      vec2 ax = uAH - uAS;
      float t = dot(a - uAS, ax) / dot(ax, ax);
      p = rot(p, uAE, uA2 * regA * smoothstep(0.45, 0.95, t));
      p = rot(p, uAS, uA1 * regA * smoothstep(0.02, 0.5, t));
    }
    if (uBOn > 0.5) {
      float w = regB;
      if (uBFull < 0.5) { vec2 bx = uBH - uBS; float t = dot(a - uBS, bx) / dot(bx, bx); w *= smoothstep(0.02, 0.55, t); }
      p = rot(p, uBS, uB * w);
    }
    if (uPOn > 0.5) {
      vec2 pp = uPC + (rot(p, uPC, uPRot) - uPC) * uPScale;
      p = mix(p, pp, regP);
    }

    float wc = smoothstep(uCapR.z, uCapR.z - 55.0, a.y) * smoothstep(uCapR.x - 10.0, uCapR.x + 15.0, a.x) * smoothstep(uCapR.y + 10.0, uCapR.y - 15.0, a.x);
    wc *= (1.0 - regA) * (1.0 - regB) * (1.0 - regP);
    p += uCap * wc;

    float wj = smoothstep(900.0, 180.0, a.y);
    p.x += uJelly * wj * wj;
    if (uMOn > 0.5) {
      float f = 14.0;
      float wm = smoothstep(uMR.x - f, uMR.x + f, a.x) * smoothstep(uMR.z + 4.0, uMR.z - 4.0, a.x)
               * smoothstep(uMR.y - 6.0, uMR.y + 6.0, a.y) * smoothstep(uMR.w + 6.0, uMR.w - 6.0, a.y);
      p += uMT * wm;
    }
    if (uRigOn > 0.5) p = uRigP + (rot(p, uRigP, uRigA) - uRigP) * uRigS + uRigT;

    vec2 o = vec2(520.0, 900.0);
    vec2 q = (p - o) * uBodyS;
    float cr = cos(uBodyR), sr = sin(uBodyR);
    p = o + vec2(cr * q.x - sr * q.y, sr * q.x + cr * q.y) - vec2(0.0, uBodyH);
    vFade = 1.0;
    if (uMirror > 0.5) { p.y = 1800.0 - p.y; vFade = clamp(1.0 - (p.y - 900.0) / 190.0, 0.0, 1.0); vFade *= vFade; }
    vec2 clip = p / vec2(uRes.x, uView) * 2.0 - 1.0;
    gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  }`;

  const FS = `
  precision mediump float;
  uniform sampler2D uTex; uniform float uAlpha; uniform vec4 uClipR; uniform float uClipMode; uniform float uBias, uMul;
  varying vec2 vUV; varying float vShade; varying vec2 vRest; varying float vFade;
  void main() {
    bool inside = vRest.x >= uClipR.x && vRest.x <= uClipR.z && vRest.y >= uClipR.y && vRest.y <= uClipR.w;
    if ((uClipMode > 0.5 && uClipMode < 1.5 && !inside) || (uClipMode > 1.5 && inside)) discard;
    vec4 c = texture2D(uTex, vUV, uBias); c.rgb *= 1.0 + vShade; gl_FragColor = c * uAlpha * uMul * vFade;
  }`;

  const CSS = `
  :host { display: block; position: relative; width: 360px; -webkit-tap-highlight-color: transparent; }
  .stage { position: relative; width: 100%; aspect-ratio: ${W} / ${VH}; cursor: pointer; user-select: none; }
  .rig { position: absolute; inset: 0; }
  canvas { width: 100%; height: 100%; display: block; }
  .shadow { position: absolute; left: 52%; top: 81.8%; width: 34%; height: 5%; transform: translate(-50%, -50%);
    background: radial-gradient(closest-side, rgba(47,127,134,.22), rgba(47,127,134,0)); pointer-events: none; }
  .fx { position: absolute; inset: 0; pointer-events: none; overflow: visible; }
  .p { position: absolute; border-radius: 50%; }
  .dots { position: absolute; left: 52%; top: 60.2%; transform: translate(-50%, -50%); display: flex; gap: 4.5%; width: 46%; justify-content: center; pointer-events: none; }
  .dot { width: 26%; aspect-ratio: 1; border-radius: 50%;
    background: linear-gradient(170deg, rgba(214,250,236,.92) 0%, rgba(150,234,205,.9) 45%, rgba(92,211,178,.88) 100%);
    box-shadow: 0 0 26px rgba(120,220,195,.28), inset 0 0 10px rgba(255,255,255,.45), inset 0 -4px 12px rgba(70,190,160,.18);
    filter: blur(.5px) saturate(.95);
    transform: scale(0); will-change: transform; }`;

  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const ring = (ms, freq = 3, decay = 120) => ms < 0 ? 0 : Math.exp(-ms / decay) * Math.cos(ms / 1000 * Math.PI * 2 * freq);

  class WardenMascot extends HTMLElement {
    static get observedAttributes() { return ['state']; }

    constructor() {
      super();
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML = `<style>${CSS}</style>
        <div class="stage" part="stage">
          <div class="shadow"></div>
          <div class="rig"><canvas class="gl"></canvas></div>
          <div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
          <div class="fx"></div>
        </div>`;
      const $ = s => root.querySelector(s);
      this.$ = { stage: $('.stage'), rig: $('.rig'), shadow: $('.shadow'), fx: $('.fx'),
        canvas: $('.gl'), dots: [...root.querySelectorAll('.dot')] };
      this.reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.shown = 'default';
      this.queued = null;
      this.sim = { h: 0, vh: 0, air: false, S: 0, vS: 0, R: 0, vR: 0, capY: 0, capV: 0, jx: 0, jv: 0,
        prevTopV: 0, prevSideV: 0, crouch: null, pending: null, tilt: 0, big: false,
        P: 1, vP: 0, pTarget: 1, dotsOn: 0, dotsT0: 0, melting: false };
      this.tex = {}; this.prevTex = null; this.mix = 1;
      this.kick = { t0: -1e9, amp: 0 }; this.bKick = { t0: -1e9, amp: 0 }; this.popKick = { t0: -1e9, amp: 0 };
      this.stateT0 = performance.now(); this.nextHop = 0; this.nextShake = 0;
      this.blinkAt = 1200; this.blinkDouble = false;
      this.prevA1 = 0; this.clothPhase = 0; this.clothAmp = 3;
      this.$.stage.addEventListener('click', () => this.poke());
    }

    get look() { return this._look || 0; }
    set look(v) { this._look = Math.max(-1, Math.min(1, +v || 0)); }
    get lookY() { return this._lookY || 0; }
    set lookY(v) { this._lookY = Math.max(-1, Math.min(1, +v || 0)); }
    react(kind) {
      if (this.busy() || this.sim.dotsOn) return;
      const s = this.sim, now = performance.now();
      if (kind === 'nod') { s.vS -= .55; }
      else if (kind === 'hop' || kind === 'happy') {
        s.crouch = { until: now + 90, v0: Math.sqrt(2 * 2700 * (kind === 'happy' ? 26 : 14)), depth: -.07 };
        s.big = false; s.tilt = 0;
        if (kind === 'happy') setTimeout(() => this.burst('#5fd6b5', .52, 7, .7), 420);
      }
      else if (kind === 'wiggle') { s.vR += 90; setTimeout(() => { this.sim.vR -= 150; }, 140); }
    }
    get state() { return this.getAttribute('state') || 'default'; }
    set state(v) { this.setAttribute('state', v); }

    attributeChangedCallback(name, oldV, newV) { if (name === 'state' && this._ready) this.go(newV || 'default'); }

    connectedCallback() {
      if (this._started) return;
      this._started = true;
      this.initGL();
      this._ready = true;
      const first = this.state;
      if (first !== 'default' && !(this.quiet && first === 'thinking')) { this.shown = first === 'thinking' ? 'default' : first; if (first === 'thinking') this.go('thinking'); }
      this.last = performance.now(); this.acc = 0;
      const loop = now => { if (!this.isConnected) { this._started = false; return; } this.frame(now); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }

    // ---------- WebGL ----------
    initGL() {
      const gl = this.gl = this.$.canvas.getContext('webgl', { premultipliedAlpha: true, antialias: true });
      if (!gl) { this.$.stage.insertAdjacentHTML('beforeend', '<div style="position:absolute;bottom:0;font:12px sans-serif;color:#a33">WebGL unavailable</div>'); return; }
      const sh = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s);
        if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
      const prog = gl.createProgram();
      gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
      gl.linkProgram(prog); gl.useProgram(prog);
      this.U = new Proxy({}, { get: (c, n) => c[n] || (c[n] = gl.getUniformLocation(prog, n)) });

      const cols = Math.ceil(W / STEP) + 1, rows = Math.ceil(H / STEP) + 1;
      const v = new Float32Array(cols * rows * 2);
      for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) { const i = (y * cols + x) * 2; v[i] = Math.min(x * STEP, W); v[i + 1] = Math.min(y * STEP, H); }
      const idx = new Uint16Array((cols - 1) * (rows - 1) * 6); let k = 0;
      for (let y = 0; y < rows - 1; y++) for (let x = 0; x < cols - 1; x++) {
        const a = y * cols + x, b = a + 1, c = a + cols, d = c + 1;
        idx[k++] = a; idx[k++] = b; idx[k++] = c; idx[k++] = b; idx[k++] = d; idx[k++] = c;
      }
      this.nIdx = idx.length;
      gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, v, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, 'aPos'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      gl.uniform2f(this.U.uRes, W, H); gl.uniform1f(this.U.uView, VH);
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

      this.rigs = {}; for (const s of STATES) this.rigs[s] = toCanvas(RIGS[s]);
      const map = window.WARDEN_ASSETS || {};
      const base = this.getAttribute('assets') || './';
      for (const s of TEXTURES) {
        const img = new Image();
        img.onload = () => {
          const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
          gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
          const pad = document.createElement('canvas'); pad.width = TS; pad.height = TS;
          pad.getContext('2d').drawImage(img, 0, 0);
          gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, pad);
          gl.generateMipmap(gl.TEXTURE_2D);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
          gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
          this.tex[s] = t;
        };
        img.src = map[s] || `${base.replace(/\/?$/, '/')}warden-${s}.webp`;
      }
    }

    resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = this.$.stage.getBoundingClientRect();
      const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
      const c = this.$.canvas;
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      if (this.gl) this.gl.viewport(0, 0, w, h);
    }

    // ---------- state changes ----------
    busy() { const s = this.sim; return s.air || s.crouch || s.melting || (s.pTarget === 1 && s.P < .9); }

    // quiet: no melting, hops or stomps; mood changes crossfade in place
    get quiet() { return this.hasAttribute('quiet'); }

    go(target) {
      if (!['thinking', ...STATES].includes(target)) target = 'default';
      if (this.quiet) { if (target !== 'thinking' && target !== this.shown) this.swapTo(target); return; }
      if (this.busy()) { this.queued = target; return; }
      const cur = this.sim.dotsOn ? 'thinking' : this.shown;
      if (target === cur) { this.poke(); return; }
      const s = this.sim;
      if (target === 'thinking') {             // melt down into three dots
        s.melting = true; s.crouch = null; s.pTarget = 0; s.vS -= .8;
        return;
      }
      if (cur === 'thinking') {                // dots pop away, Warden pops back in
        s.dotsOn = 0; s.dotsT0 = performance.now();
        this.swapTo(target, true);
        setTimeout(() => { s.pTarget = 1; s.vP += 6; s.vS += 1.6; }, 220);
        return;
      }
      if ((TEXOF[cur] || cur) === (TEXOF[target] || target)) { this.swapTo(target, true); return; }
      s.crouch = { until: performance.now() + 150, v0: Math.sqrt(2 * 2700 * 82), depth: -.15 };
      s.pending = target; s.big = true; s.tilt = ['green', 'red'].includes(target) ? -5 : 5;
    }

    swapTo(target, silent) {
      if (this.shown !== target) { this.prevTex = this.shown; this.mix = silent ? 1 : 0; }
      this.shown = target; this.stateT0 = performance.now();
      const now = performance.now();
      if (target === 'green') this.kick = { t0: now, amp: -.5 };
      if (target === 'red') { this.popKick = { t0: now + 120, amp: .3 }; }
      this.stomp = target === 'stop' && !this.quiet ? { t0: now + 430, hit: false } : null;
      this.nextHmm = now + 1600;
      this.nextHop = now + 1800; this.nextShake = now + (target === 'stop' ? 3400 : 1500);
      this.dispatchEvent(new CustomEvent('wardenstatechange', { detail: { state: target }, bubbles: true, composed: true }));
    }

    poke() {
      if (this.busy() || this.sim.dotsOn) return;
      this.sim.vS -= 1.7; this.sim.vR += (Math.random() < .5 ? -1 : 1) * 70;
      const now = performance.now();
      if (this.shown === 'green') this.kick = { t0: now, amp: .35 };
      if (this.shown === 'stop' && (!this.stomp || now - this.stomp.t0 > 900)) this.stomp = { t0: now, hit: false };
      if (this.shown === 'amber') this.bKick = { t0: now, amp: .07 };
      if (this.shown === 'red') this.popKick = { t0: now, amp: .2 };
    }

    burst(color, fx = .52, n = 9, spread = 1) {
      if (this.reduce) return;
      const r = this.$.stage.getBoundingClientRect(), ox = r.width * fx, oy = r.height * .815;
      for (let i = 0; i < n; i++) {
        const d = document.createElement('div'); d.className = 'p';
        const s = 6 + Math.random() * 9;
        Object.assign(d.style, { width: s + 'px', height: s + 'px', left: (ox - s / 2) + 'px', top: (oy - s / 2) + 'px',
          background: `radial-gradient(circle at 35% 35%, #fff, ${color} 60%)`, boxShadow: `0 0 12px ${color}` });
        this.$.fx.appendChild(d);
        const side = i % 2 ? 1 : -1, ang = -Math.PI / 2 + side * (.5 + Math.random()), dist = (70 + Math.random() * 80) * spread;
        const dx = Math.cos(ang) * dist, dy = Math.sin(ang) * dist * .8;
        d.animate([{ transform: 'translate(0,0) scale(.3)', opacity: 0 },
          { transform: `translate(${dx * .55}px,${dy * .7}px) scale(1.1)`, opacity: 1, offset: .35 },
          { transform: `translate(${dx}px,${dy * .6 + 20}px) scale(.4)`, opacity: 0 }],
          { duration: 650 + Math.random() * 300, easing: 'cubic-bezier(.2,.7,.3,1)' }).onfinish = () => d.remove();
      }
    }

    // ---------- physics, fixed 240 Hz ----------
    step(dt, now, cssToTex) {
      const s = this.sim, st = this.shown, G = 2700, vmax = Math.sqrt(2 * G * 82);
      let sT = 0;
      if (s.crouch) {
        sT = s.crouch.depth;
        if (now >= s.crouch.until) { s.air = true; s.vh = s.crouch.v0; s.crouch = null; }
      }
      if (s.air) {
        const pv = s.vh; s.vh -= G * dt; s.h += s.vh * dt;
        sT = .13 * Math.abs(s.vh) / vmax;
        if (s.pending && pv > 0 && s.vh <= 0) { this.swapTo(s.pending); s.pending = null; s.vS += .5; }
        if (s.h <= 0) {
          const imp = Math.abs(s.vh) / vmax;
          s.h = 0; s.vh = 0; s.air = false;
          s.vS -= imp * (this.shown === 'stop' && s.big ? 3.6 : 2.7);
          if (s.big) {
            if (st === 'green') this.burst('#5fd6b5');
            if (st === 'red') this.burst('#ef6b62');
            if (st === 'amber') this.burst('#f2b84b');
          }
          s.big = false;
        }
      }

      // presence (melting into dots and back)
      s.vP += (300 * (s.pTarget - s.P) - (s.pTarget === 0 ? 34 : 18) * s.vP) * dt;
      s.P += s.vP * dt;
      if (s.melting && s.P < .04) { s.melting = false; s.P = 0; s.vP = 0; s.dotsOn = 1; s.dotsT0 = now; }

      s.vS += (400 * (sT - s.S) - 12.5 * s.vS) * dt; s.S += s.vS * dt;

      const sec = now / 1000, red = st === 'red';
      let rT = 0;
      if (!this.reduce) {
        if (st === 'green') rT = 1.6 * Math.sin(sec * Math.PI * 2 / 1.7);
        else if (st === 'amber') rT = 3.2 * Math.sin(sec * Math.PI * 2 / 3.6);
        else if (red) rT = 1.1 * Math.sin(sec * Math.PI * 2 / 2.2);
        else if (st === 'stop') rT = .5 * Math.sin(sec * Math.PI * 2 / 4);
        else rT = .7 * Math.sin(sec * Math.PI * 2 / 4.6);
      }
      rT += (this._lookS || 0) * 2.2;
      if (s.air && s.big) rT += s.tilt;
      s.vR += (260 * (rT - s.R) - 13 * s.vR) * dt; s.R += s.vR * dt;

      const topV = s.vh * cssToTex + s.vS * 600;
      s.capV += (topV - s.prevTopV) * .09; s.prevTopV = topV;
      s.capV += (-420 * s.capY - 17 * s.capV) * dt; s.capY += s.capV * dt;

      const sideV = s.vR * Math.PI / 180 * 600;
      s.jv -= (sideV - s.prevSideV) * .12; s.prevSideV = sideV;
      s.jv += (-200 * s.jx - 8 * s.jv) * dt; s.jx += s.jv * dt;

      const q = this.quiet;
      if (!q && !this.busy() && !this.reduce && !s.dotsOn && now > this.nextHop && st === 'green') {
        s.crouch = { until: now + (red ? 70 : 95), v0: Math.sqrt(2 * G * (red ? 12 : 15)), depth: red ? -.05 : -.06 };
        s.big = false; s.tilt = 0;
        this.nextHop = now + (red ? 1500 + Math.random() * 900 : 2300 + Math.random() * 1700);
        if (red) this.popKick = { t0: now + 250, amp: .16 };
      }
      if (!q && !this.busy() && !this.reduce && st === 'stop' && now > this.nextShake && (!this.stomp || now - this.stomp.t0 > 1200)) {
        this.stomp = { t0: now, hit: false }; this.nextShake = now + 3000 + Math.random() * 1600;
      }
      if (st === 'stop' && this.stomp && !this.stomp.hit && now - this.stomp.t0 >= 360) {
        this.stomp.hit = true; s.vS -= 1.25; s.vR += 25;
        if (this.rigs) { const b = this.rigs.stop.layers[0].pivot; this.burst('rgba(150,160,170,.55)', b[0] / W, 7, .45); }
      }
      if (st === 'stop' && this.stomp && now - this.stomp.t0 < 280 && now - this.stomp.t0 > 0) s.vR += -9 * dt * 60 * .02;
      if (!q && !this.busy() && !this.reduce && st === 'amber' && now > (this.nextHmm || 0)) {
        s.vS -= .55; s.vR += (Math.random() < .5 ? -1 : 1) * 45; this.bKick = { t0: now, amp: .07 };
        this.hmm2 = now + 170; this.nextHmm = now + 3000 + Math.random() * 1500;
      }
      if (this.hmm2 && now > this.hmm2) { this.hmm2 = 0; if (st === 'amber') s.vS -= .45; }

      if (!this.busy() && this.queued) { const q = this.queued; this.queued = null; this.go(q); }
    }

    // pose of the rigged parts for the current state
    pose(now) {
      const st = this.shown, t = (now - this.stateT0) / 1000, R = this.reduce;
      const o = { a1: 0, a2: 0, b: 0, amp: 3, speed: 7.5, pScale: 1, pRot: 0 };
      if (st === 'green' && !R) {
        const tt = Math.max(0, t - .3), ct = tt % 3.4;
        const env = smooth(0, .3, ct) * (1 - smooth(1.7, 2.1, ct));
        const ph = tt * Math.PI * 2 / .82, rest = .05 * Math.sin(tt * Math.PI * 2 / 2.6);
        o.a1 = env * .2 * (Math.sin(ph) + .22 * Math.sin(2 * ph + .4)) + rest - .04;
        o.a2 = env * .24 * Math.sin(ph - 1) + rest * .6;
      }
      if (st === 'red' && !R) {
        o.a1 = 0; o.a2 = 0; o.b = 0;
        o.pScale = 1 + .045 * Math.sin(t * Math.PI * 2 / .7);
        o.pRot = .035 * Math.sin(t * Math.PI * 2 / 1.1);
        o.amp = 4.5; o.speed = 9;
      }
      if (st === 'wave' && !R) {
        const ct = t % 3.2, env = smooth(0, .35, ct) * (1 - smooth(1.9, 2.4, ct));
        o.b = -env * (.42 + .2 * Math.sin(t * Math.PI * 2 / .52));
      }
      if (st === 'amber' && !R) { o.amp = 3; o.speed = 6; o.b = .03 * Math.sin(t * Math.PI * 2 / 1.9); }
      o.signT = 0; o.signA = 0;
      if (st === 'stop' && this.stomp && !R) {
        const k = now - this.stomp.t0;
        if (k >= 0 && k < 280) { const e = 1 - Math.pow(1 - k / 280, 3); o.signT = -34 * e; o.signA = -.02 * e; }
        else if (k >= 280 && k < 360) { const u = (k - 280) / 80; o.signT = -34 * (1 - u * u); o.signA = -.02 * (1 - u); }
        else if (k >= 360 && k < 1400) { o.signT = 6 * ring(k - 360, 6, 70); o.signA = .03 * ring(k - 360, 4.5, 130); }
      }
      const k = now - this.kick.t0;
      if (k < 1400) { o.a1 += this.kick.amp * ring(k, 2.2, 200); o.a2 += this.kick.amp * .8 * ring(k - 70, 2.2, 200); }
      const kb = now - this.bKick.t0;
      if (kb < 1400) o.b += this.bKick.amp * ring(kb, 2.4, 200);
      const kp = now - this.popKick.t0;
      if (kp > 0 && kp < 900) { o.pScale += this.popKick.amp * ring(kp, 2.8, 150); o.pRot += this.popKick.amp * .3 * ring(kp - 40, 2.8, 150); }
      return o;
    }

    frame(now) {
      const el = Math.min(.05, (now - this.last) / 1000); this.last = now;
      this.resize();
      const cssToTex = W / Math.max(1, this.$.stage.clientWidth);
      this.acc += el;
      while (this.acc >= 1 / 240) { this.step(1 / 240, now - this.acc * 1000, cssToTex); this.acc -= 1 / 240; }

      const s = this.sim, sec = now / 1000;
      const b = this.reduce ? 0 : Math.sin(sec * Math.PI * 2 / 3.2);
      const P = clamp(s.P, 0, 1.2);
      const S = s.S + .017 * b;
      const sy = (1 + S) * Math.max(0, s.P), sx = (1 - S * .72) * (1 + (1 - P) * .35);
      const vis = smooth(0, .12, s.P);
      const $ = this.$;
      this.body = { sx, sy, r: s.R * Math.PI / 180, h: s.h * cssToTex, vis };
      const shs = clamp(1 - s.h / 110, .35, 1) * (.35 + .65 * P);
      $.shadow.style.transform = `translate(-50%, -50%) scale(${shs * sx}, ${shs})`;
      $.shadow.style.opacity = shs.toFixed(3);

      // thinking dots
      const dt0 = now - s.dotsT0;
      $.dots.forEach((d, i) => {
        let sc, y = 0;
        if (s.dotsOn) {
          const tt = dt0 - i * 90;
          sc = tt < 0 ? 0 : clamp(1 - Math.exp(-tt / 90) * Math.cos(tt / 1000 * Math.PI * 2 * 2.6), 0, 1.3);
          const ph = (dt0 / 1000) * Math.PI * 2 / .95 - i * .7;
          const bounce = Math.max(0, Math.sin(ph));
          y = -bounce * 34 * smooth(0, 300, dt0);
          const squash = 1 + .12 * Math.cos(ph * 2) * smooth(0, 300, dt0);
          d.style.transform = `translateY(${y}px) scale(${sc / Math.sqrt(squash)}, ${sc * Math.sqrt(squash)})`;
        } else {
          const tt = dt0 - (2 - i) * 50;
          sc = tt < 0 ? 1 : clamp(1 - smooth(0, 160, tt) * 1.0, 0, 1) * (s.dotsT0 ? 1 : 0);
          d.style.transform = `scale(${sc})`;
        }
      });

      // blink
      let blink = 0;
      if (!this.reduce && now > this.blinkAt) {
        const bt = now - this.blinkAt;
        blink = bt < 70 ? smooth(0, 70, bt) : bt < 160 ? 1 - smooth(70, 160, bt) : 0;
        if (bt > 160) {
          if (!this.blinkDouble && Math.random() < .25) { this.blinkDouble = true; this.blinkAt = now + 90; }
          else { this.blinkDouble = false; this.blinkAt = now + 2400 + Math.random() * 3200; }
        }
      }

      const o = this.pose(now);
      const armV = (o.a1 - this.prevA1) / Math.max(el, 1e-3); this.prevA1 = o.a1;
      const tA = o.amp + Math.min(6, Math.abs(armV) * 2.2);
      this.clothAmp += (tA - this.clothAmp) * Math.min(1, el * 5);
      this.clothPhase += el * (o.speed + Math.min(8, Math.abs(armV) * 6));
      const drag = clamp(-armV * .09, -.22, .22);
      this.mix = Math.min(1, this.mix + el * (this.quiet ? 5 : 22));

      const gl = this.gl;
      if (!gl) return;
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
      const U = this.U;
      gl.uniform2f(U.uCap, 0, clamp(s.capY, -12, 12));
      gl.uniform1f(U.uJelly, clamp(s.jx, -10, 10));
      this._lookS = (this._lookS || 0) + ((this._look || 0) - (this._lookS || 0)) * Math.min(1, el * 6);
      gl.uniform1f(U.uBlink, blink);
      this._lookYS = (this._lookYS || 0) + ((this._lookY || 0) - (this._lookYS || 0)) * Math.min(1, el * 6);
      gl.uniform2f(U.uLook, this._lookS * 9, this._lookYS * 6);
      gl.uniform1f(U.uClothT, this.clothPhase);
      gl.uniform1f(U.uClothAmp, this.reduce ? 0 : this.clothAmp);
      gl.uniform1f(U.uClothDrag, this.reduce ? 0 : drag);

      const draw = (name, alpha, live) => {
        const tex = this.tex[TEXOF[name] || name]; if (!tex || alpha <= .001) return;
        const r = this.rigs[name], z = live ? o : { a1: 0, a2: 0, b: 0, pScale: 1, pRot: 0 };
        gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.uniform1f(U.uAlpha, alpha);
        gl.uniform1f(U.uRigOn, 0); gl.uniform1f(U.uClipMode, 0);
        gl.uniform1f(U.uMOn, 0);
        gl.uniform2f(U.uE1, ...r.eyes[0]); gl.uniform2f(U.uE2, ...r.eyes[1]); gl.uniform2f(U.uER, ...r.eyeR); gl.uniform2f(U.uEOn, ...r.eyeOn);
        gl.uniform3f(U.uCapR, ...r.cap);
        const A = r.armA;
        gl.uniform1f(U.uAOn, A ? 1 : 0);
        if (A) { gl.uniform2f(U.uAS, ...A.S); gl.uniform2f(U.uAE, ...A.E); gl.uniform2f(U.uAH, ...A.H);
          gl.uniform4f(U.uAR1, ...A.rects[0]); gl.uniform4f(U.uAR2, ...(A.rects[1] || [0, 0, 0, 0]));
          gl.uniform1f(U.uA1, z.a1); gl.uniform1f(U.uA2, z.a2); }
        const C = r.cloth;
        gl.uniform1f(U.uCOn, C ? 1 : 0);
        if (C) { gl.uniform2f(U.uCP0, ...C.P0); gl.uniform2f(U.uCU, ...C.U); gl.uniform2f(U.uCN, ...C.N); gl.uniform2f(U.uCS, ...C.s);
          gl.uniform1f(U.uCD, C.d); gl.uniform4f(U.uCR, ...C.rect); }
        const B = r.armB;
        gl.uniform1f(U.uBOn, B ? 1 : 0);
        if (B) { gl.uniform2f(U.uBS, ...B.S); gl.uniform2f(U.uBH, ...B.H); gl.uniform1f(U.uBFull, B.full);
          gl.uniform4f(U.uBR1, ...B.rects[0]); gl.uniform4f(U.uBR2, ...(B.rects[1] || [0, 0, 0, 0])); gl.uniform1f(U.uB, z.b); }
        const Pp = r.pop;
        gl.uniform1f(U.uPOn, Pp ? 1 : 0);
        if (Pp) { gl.uniform2f(U.uPC, ...Pp.C); gl.uniform4f(U.uPR, ...Pp.rect); gl.uniform1f(U.uPScale, z.pScale); gl.uniform1f(U.uPRot, z.pRot); }
        gl.drawElements(gl.TRIANGLES, this.nIdx, gl.UNSIGNED_SHORT, 0);
      };
      const drawLayer = (name, L, alpha, live, pass) => {
        if (!this.tex[L.tex] || alpha <= .001) return;
        if (pass === 'back' && !L.back) return;
        gl.bindTexture(gl.TEXTURE_2D, this.tex[L.tex]);
        gl.uniform1f(U.uAlpha, alpha);
        for (const n of ['uAOn', 'uBOn', 'uPOn', 'uMOn']) gl.uniform1f(U[n], 0);
        gl.uniform2f(U.uEOn, 0, 0); gl.uniform3f(U.uCapR, 0, 0, -1e4);
        gl.uniform1f(U.uJelly, 0);
        const C = L.cloth;
        gl.uniform1f(U.uCOn, C ? 1 : 0);
        if (C) { gl.uniform2f(U.uCP0, ...C.P0); gl.uniform2f(U.uCU, ...C.U); gl.uniform2f(U.uCN, ...C.N); gl.uniform2f(U.uCS, ...C.s);
          gl.uniform1f(U.uCD, C.d); gl.uniform4f(U.uCR, ...C.rect); }
        let ang = 0, ty = 0, sc = 1;
        if (live) {
          if (L.motion === 'sign') { ang = o.signA; ty = o.signT; }
          else if (L.motion === 'tilt') ang = o.b;
          else if (L.motion === 'pop') { ang = o.pRot; sc = o.pScale; }
        }
        gl.uniform1f(U.uRigOn, 1); gl.uniform2f(U.uRigP, ...L.pivot);
        gl.uniform1f(U.uRigA, ang); gl.uniform1f(U.uRigS, sc); gl.uniform2f(U.uRigT, 0, ty);
        if (!L.back) gl.uniform1f(U.uClipMode, 0);
        else { gl.uniform4f(U.uClipR, ...L.back); gl.uniform1f(U.uClipMode, pass === 'back' ? 1 : 2); }
        gl.drawElements(gl.TRIANGLES, this.nIdx, gl.UNSIGNED_SHORT, 0);
        gl.uniform1f(U.uJelly, clamp(s.jx, -10, 10));
      };
      const layer = (name, alpha, live) => { const Ls = this.rigs[name].layers; Ls.forEach(L => drawLayer(name, L, alpha, live, 'back')); draw(name, alpha, live); Ls.forEach(L => drawLayer(name, L, alpha, live, 'front')); };
      const bd = this.body;
      gl.uniform2f(U.uBodyS, bd.sx, bd.sy); gl.uniform1f(U.uBodyR, bd.r); gl.uniform1f(U.uBodyH, bd.h);
      const pass = (mirror) => {
        gl.uniform1f(U.uMirror, mirror ? 1 : 0);
        gl.uniform1f(U.uBias, mirror ? 3.0 : 0.0);
        gl.uniform1f(U.uMul, bd.vis * (mirror ? .2 * clamp(1 - bd.h / 200, 0, 1) : 1));
        if (this.prevTex && this.mix < 1) layer(this.prevTex, 1 - this.mix, false);
        layer(this.shown, this.mix, true);
      };
      pass(true); pass(false);
    }
  }

  customElements.define('warden-mascot', WardenMascot);
})();

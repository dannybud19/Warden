/*
  <warden-orb> — Warden's voice-call orb. Iridescent teal bubble with soft, blurred edges and Warden's eyes.
  Edges follow the reference bubble: a sharp inner rim, a thick blurred outer rim and a soft ghost
  of the rim trailing behind as it drifts.

  <script src="/warden/warden-orb.js"></script>
  <warden-orb mode="idle" mood="calm" style="width: 280px"></warden-orb>

  mode:  idle | listening | speaking | thinking
  mood:  calm | amber | stop
  orb.level = 0..1   // Warden's voice volume while speaking (e.g. ElevenLabs output volume)
  orb.mic   = 0..1   // your mic volume while listening (e.g. ElevenLabs input volume)
  orb.look(x, y)     // -1..1, where the eyes look
*/
(() => {
  if (customElements.get('warden-orb')) return;

  const CSS = `
  :host { display: block; position: relative; width: 280px; aspect-ratio: 1; --s: 1; --tilt: 0deg; --u: 1;
    --c1: #34BFA4; --c2: #6EDCC6; --c3: #1F9C9E; --c4: #7FD3E8; --c5: #A9E6F2; --rim1: #3FB9AC; --rim2: #6FB6E6; --glow: rgba(52,191,164,.38); --eye: #1D6C70; }
  :host([mood="amber"]) { --eye: #7A4A1C; --c1: #F4B860; --c2: #FFD9A0; --c3: #E79A55; --c4: #FFC8A8; --c5: #F2A6B8; --rim1: #EFA75A; --rim2: #F6C27A; --glow: rgba(244,184,96,.35); }
  :host([mood="stop"])  { --eye: #7A2E2A; --c1: #F08C82; --c2: #FFC1B8; --c3: #E06A64; --c4: #FFB3A6; --c5: #F2A6C8; --rim1: #E8786E; --rim2: #F4A79C; --glow: rgba(240,140,130,.35); }
  * { box-sizing: border-box; }
  .wrap { position: absolute; inset: 0; transform: scale(var(--s)) rotate(var(--tilt)); transition: transform .08s linear; }
  .halo { position: absolute; inset: 4%; border-radius: 50%; background: radial-gradient(closest-side, var(--glow), transparent 75%);
    filter: blur(calc(var(--u) * 22px)); transform: scale(1.14); transition: background 1s; }
  .ball { position: absolute; inset: 10%; border-radius: 50%; overflow: hidden;
    -webkit-mask: radial-gradient(closest-side, #000 50%, rgba(0,0,0,.5) 78%, transparent 100%);
            mask: radial-gradient(closest-side, #000 50%, rgba(0,0,0,.5) 78%, transparent 100%);
    background: radial-gradient(circle at 40% 36%, rgba(255,255,255,1) 0%, rgba(240,252,250,.92) 34%, rgba(214,244,238,.7) 66%, rgba(190,234,228,.4) 100%); }
  .sw { position: absolute; inset: -20%; border-radius: 50%; filter: blur(26px); mix-blend-mode: multiply; opacity: .85; transition: opacity 1s; }
  .sw.a { inset: -10% -25% -25% -10%; background: conic-gradient(from 90deg at 60% 62%, transparent 0 8%, var(--c1) 20%, var(--c2) 30%, transparent 44% 58%, var(--c4) 70%, transparent 84%); animation: spin 10s linear infinite; }
  .sw.b { background: conic-gradient(from 120deg, transparent 0 20%, var(--c2) 33%, transparent 46% 60%, var(--c5) 72%, transparent 86%); animation: spin 13s linear infinite reverse; opacity: .65; }
  .sw.c { inset: 10%; background: radial-gradient(circle at 60% 70%, var(--c3), transparent 60%); animation: drift 7s ease-in-out infinite; opacity: .55; }
  .sheen { position: absolute; inset: 0; border-radius: 50%; background: radial-gradient(circle at 32% 30%, rgba(255,255,255,.95), rgba(255,255,255,0) 46%); filter: blur(10px); }
  .crescent { position: absolute; left: 22%; right: 22%; bottom: 10%; height: 16%; border-radius: 50%;
    background: linear-gradient(90deg, transparent, var(--c5), var(--c1), transparent); filter: blur(7px); opacity: .55; animation: sway 6s ease-in-out infinite; }
  /* the outer box blurs, the inner <i> draws the ring: a mask on the same box would clip the blur away */
  .rim, .ghost { position: absolute; border-radius: 50%; }
  .rim > i, .ghost > i { position: absolute; inset: 0; border-radius: 50%; padding: var(--pad); background: var(--ring);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite: xor;
            mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0); }
  .rim { inset: 10%; --pad: calc(var(--u) * 6px); filter: blur(calc(var(--u) * 3.5px));
    --ring: conic-gradient(from 0deg, var(--rim1), rgba(255,255,255,.2), var(--rim2), rgba(255,255,255,.1), var(--rim1));
    animation: spin 11s linear infinite; opacity: .7; }
  .rim.two { inset: 8% 13% 11% 5%; --pad: calc(var(--u) * 8px); filter: blur(calc(var(--u) * 6px)); opacity: .85; animation: wob 5.5s ease-in-out infinite, spin 17s linear infinite reverse; }
  .rim.three { inset: 4%; --pad: calc(var(--u) * 14px); filter: blur(calc(var(--u) * 14px)); opacity: .6; animation: spin 21s linear infinite; }
  .rim.inner { inset: 11.5%; --pad: calc(var(--u) * 2px); filter: blur(calc(var(--u) * .8px)); opacity: .5; animation: spin 9s linear infinite reverse; }
  .ghost { inset: 8% 18% 12% -2%; --pad: calc(var(--u) * 12px); filter: blur(calc(var(--u) * 11px)); opacity: .55;
    --ring: conic-gradient(from 200deg, var(--rim1), var(--rim2) 30%, transparent 55%, var(--rim1) 85%);
    animation: trail 7s ease-in-out infinite; }
  @keyframes trail { 0%,100% { transform: translate(-3%, 1%) rotate(0deg); } 50% { transform: translate(2%, -3%) rotate(40deg); } }
  .eyes { position: absolute; left: 50%; top: 44%; width: 25%; height: 16%; transform: translate(calc(-50% + var(--ex, 0px)), calc(-50% + var(--ey, 0px)));
    display: flex; justify-content: space-between; transition: transform .25s cubic-bezier(.3,1.4,.5,1); }
  .eye { width: 27%; height: 100%; border-radius: 999px; background: var(--eye, #1D6C70); opacity: .92; box-shadow: 0 0 6px rgba(29,108,112,.25); transform-origin: 50% 55%; transition: transform .12s ease; }
  .eyes.blink .eye { transform: scaleY(.12); }
  .eyes.happy .eye { height: 46%; background: none; border: 4px solid var(--eye, #1D6C70); border-bottom: 0; border-radius: 999px 999px 0 0; transform: translateY(30%); }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes drift { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(-8%, -10%) scale(1.15); } }
  @keyframes sway { 0%,100% { transform: translateX(-6%) rotate(-4deg); } 50% { transform: translateX(6%) rotate(4deg); } }
  @keyframes wob { 0%,100% { transform: translate(0,0); } 33% { transform: translate(3%, -2%); } 66% { transform: translate(-2%, 3%); } }
  :host([mode="thinking"]) .sw.a { animation-duration: 3s; } :host([mode="thinking"]) .sw.b { animation-duration: 4.5s; }
  :host([mode="thinking"]) .rim { animation-duration: 4s; }
  @media (prefers-reduced-motion: reduce) { .sw, .rim, .crescent, .ghost { animation: none !important; } }
  `;

  class WardenOrb extends HTMLElement {
    static get observedAttributes() { return ['mode', 'mood']; }
    constructor() {
      super();
      const r = this.attachShadow({ mode: 'open' });
      r.innerHTML = `<style>${CSS}</style><div class="wrap">
        <div class="halo"></div>
        <div class="ghost"><i></i></div>
        <div class="rim three"><i></i></div>
        <div class="ball"><div class="sw a"></div><div class="sw b"></div><div class="sw c"></div><div class="crescent"></div><div class="sheen"></div></div>
        <div class="rim"><i></i></div><div class="rim two"><i></i></div><div class="rim inner"><i></i></div>
        <div class="eyes"><div class="eye"></div><div class="eye"></div></div></div>`;
      this.$eyes = r.querySelector('.eyes');
      this.level = 0; this.mic = 0;
      this._s = 1; this._v = 0; this._lx = 0; this._ly = 0; this._tx = 0; this._ty = 0;
      this._blinkAt = performance.now() + 1500;
    }
    connectedCallback() {
      if (!this.hasAttribute('mode')) this.setAttribute('mode', 'idle');
      const tick = now => { if (!this.isConnected) return; this._frame(now); requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    }
    attributeChangedCallback(n, o, v) {
      if (n === 'mode') this.$eyes && this.$eyes.classList.toggle('happy', false);
    }
    look(x = 0, y = 0) { this._tx = Math.max(-1, Math.min(1, x)); this._ty = Math.max(-1, Math.min(1, y)); }
    happy(ms = 1200) { this.$eyes.classList.add('happy'); clearTimeout(this._h); this._h = setTimeout(() => this.$eyes.classList.remove('happy'), ms); }
    _frame(now) {
      const mode = this.getAttribute('mode');
      const t = now / 1000;
      const breathe = 1 + .018 * Math.sin(t * 2 * Math.PI / 3.6);
      let target = breathe;
      if (mode === 'speaking') target += .1 * this.level;
      if (mode === 'listening') target += .045 * this.mic;
      if (mode === 'thinking') target += .02 * Math.sin(t * 9);
      // springy scale so voice pulses feel jelly-like
      this._v += (target - this._s) * .28; this._v *= .62; this._s += this._v;
      this.style.setProperty('--s', this._s.toFixed(4));
      this.style.setProperty('--tilt', (mode === 'listening' ? 3 * Math.sin(t * 1.3) : 1.2 * Math.sin(t * .8)).toFixed(2) + 'deg');
      // eyes: look where asked, glance up while thinking, a little bounce when speaking
      let tx = this._tx, ty = this._ty;
      if (mode === 'thinking') { tx = .35 * Math.sin(t * 1.6); ty = -.7; }
      if (mode === 'listening') ty = Math.max(ty, .15);
      this._lx += (tx - this._lx) * .12; this._ly += (ty - this._ly) * .12;
      const w = this.clientWidth || 280;
      this.style.setProperty('--u', (w / 280).toFixed(3));
      this.style.setProperty('--ex', (this._lx * w * .06).toFixed(1) + 'px');
      this.style.setProperty('--ey', (this._ly * w * .04 - (mode === 'speaking' ? this.level * w * .012 : 0)).toFixed(1) + 'px');
      if (now > this._blinkAt && mode !== 'thinking') {
        this.$eyes.classList.add('blink'); setTimeout(() => this.$eyes.classList.remove('blink'), 130);
        this._blinkAt = now + 2400 + Math.random() * 3000;
      }
    }
  }
  customElements.define('warden-orb', WardenOrb);
})();

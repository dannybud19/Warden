/* Warden conversational flows (adapted from the warden-onboarding prototype).

   startWardenOnboarding(root, { mode, icons, initialName, profile, onFinish, onCancel })
     mode "onboarding": intro, name and email, where you're moving, then "Welcome, <name>!".
                        onFinish(answers) saves the profile and opens the (empty) dashboard.
     mode "newcase":    the listing, how it's going, chats/contract/video, then four optional extra
                        documents, then onFinish(answers, files) creates the case and opens it.
   Returns a cleanup function. Calm text: words fade up; no blur, spin or jelly. */
function startWardenOnboarding(root, opts) {
  const ICONS = opts.icons;
  const MODE = opts.mode || 'onboarding';
  const profile = opts.profile || {};
  const ac = new AbortController(), signal = ac.signal;
  const $ = (id) => root.querySelector('#' + id);
  const w = $('w'), lineEl = $('line'), subEl = $('sub'), formEl = $('form'), tagEl = $('tag'), railEl = $('rail');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const data = {
    name: opts.initialName || '', email: '', area: '', date: '', first: null,
    url: '', host: '', address: '', rent: '', agency: '', companyNumber: '', agentName: '', viewed: null, asked: null, paid: null, files: {},
  };
  const fileObjs = {};
  let step = 0, sayToken = 0, readTimer = null;
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const first = () => esc(data.name.trim().split(/\s+/)[0] || '');
  const risky = () => data.viewed && data.viewed !== 'Yes' && data.asked && data.asked !== 'No';
  const mood = (m) => (root.dataset.mood = m);
  function setState(s) {
    w.state = s;
    mood({ stop: 'stop', red: 'stop', amber: 'amber', green: 'green', thinking: 'think' }[s] || 'calm');
  }

  // ---------- eyes follow the pointer ----------
  let attentionUntil = 0;
  window.addEventListener('pointermove', (e) => {
    if (performance.now() < attentionUntil) return;
    const r = w.getBoundingClientRect(), cx = r.left + r.width * 0.52, cy = r.top + r.height * 0.45;
    w.look = (e.clientX - cx) / (innerWidth * 0.45);
    w.lookY = (e.clientY - cy) / (innerHeight * 0.5);
  }, { signal });
  function attention() { attentionUntil = performance.now() + 1800; w.look = 1; w.lookY = 0.25; }

  // ---------- progress (onboarding: steps 1-2; new case: steps 0-3 shown as 1-4) ----------
  const STEPS_N = MODE === 'onboarding' ? 2 : 5;
  const OFFSET = MODE === 'onboarding' ? 0 : 1;
  function drawRail() {
    const n = step + OFFSET;
    const on = n > 0 && n <= STEPS_N;
    railEl.classList.toggle('on', on);
    $('railLbl').textContent = on ? `Step ${n} of ${STEPS_N}` : '';
    $('dashes').innerHTML = Array.from({ length: STEPS_N }, (_, i) => `<i class="${i + 1 < n ? 'done' : i + 1 === n ? 'now' : ''}"></i>`).join('');
  }

  // ---------- speaking: gentle word fade-up ----------
  function nudge() {
    if (reduce) return;
    $('bubble').animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-4px)' }, { transform: 'translateX(3px)' }, { transform: 'translateX(0)' }], { duration: 320, easing: 'ease-out' });
  }
  async function say(html, sub = '') {
    const token = ++sayToken;
    formEl.classList.remove('in');
    if (lineEl.childNodes.length && !reduce) {
      subEl.classList.remove('in');
      await lineEl.animate([{ opacity: 1 }, { opacity: 0, transform: 'translateY(-4px)' }], { duration: 180, easing: 'ease-in', fill: 'forwards' }).finished.catch(() => {});
      if (token !== sayToken) return;
    }
    lineEl.getAnimations().forEach((a) => a.cancel());
    const tmp = document.createElement('div');
    tmp.innerHTML = html.replace(/<br>\s+/g, '<br>');
    lineEl.innerHTML = '';
    const words = [];
    tmp.childNodes.forEach((node) => {
      if (node.nodeName === 'BR') { lineEl.appendChild(document.createElement('br')); return; }
      const parent = node.nodeName === 'B' ? lineEl.appendChild(document.createElement('b')) : lineEl;
      node.textContent.split(/(\s+)/).forEach((part) => {
        if (!part) return;
        if (!part.trim()) { parent.appendChild(document.createTextNode(' ')); return; }
        const span = document.createElement('span');
        span.className = 'w';
        span.textContent = part;
        parent.appendChild(span);
        words.push(span);
      });
    });
    subEl.textContent = sub;
    subEl.classList.remove('in');
    if (reduce) { words.forEach((u) => (u.style.opacity = 1)); subEl.classList.add('in'); return; }
    words.forEach((u, i) => {
      u.animate([{ opacity: 0, transform: 'translateY(0.35em)' }, { opacity: 1, transform: 'none' }],
        { duration: 460, delay: 40 + Math.min(i, 12) * 45, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'forwards' });
    });
    const total = 40 + Math.min(words.length, 12) * 45 + 260;
    return new Promise((res) => setTimeout(() => {
      if (token !== sayToken) return;
      subEl.classList.add('in');
      res();
    }, total));
  }

  // ---------- forms ----------
  function showForm(html, bind, bare = false) {
    formEl.classList.toggle('bare', bare);
    formEl.innerHTML = html;
    if (bind) bind();
    formEl.querySelectorAll('.chips').forEach((g) => g.addEventListener('click', (e) => {
      const b = e.target.closest('.chip');
      if (!b) return;
      data[g.dataset.key] = b.textContent;
      g.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', c === b));
      if (!reduce) b.animate([{ transform: 'scale(.94)' }, { transform: 'scale(1)' }], { duration: 260, easing: 'cubic-bezier(.3,1.4,.5,1)' });
      w.react('hop');
      attention();
      g.dispatchEvent(new CustomEvent('picked'));
      check();
    }));
    requestAnimationFrame(() => formEl.classList.add('in'));
    const f = formEl.querySelector('input:not([type=file])');
    if (f && matchMedia('(pointer:fine)').matches) setTimeout(() => f.focus({ preventScroll: true }), 400);
    check();
  }
  const chips = (key, options) => `<div class="chips" data-key="${key}">${options.map((o) => `<button type="button" class="chip" aria-pressed="${data[key] === o}">${o}</button>`).join('')}</div>`;
  const input = (id, label, type, ph = '') => `<div class="field"><label for="${id}">${label}</label><input id="${id}" type="${type}" placeholder="${ph}" value="${esc(data[id])}"></div>`;
  const nextRow = (label = 'Continue', back = 'Back') => `<div class="row"><button class="btn" id="next">${label}</button>${back ? `<button class="link" id="back">${back}</button>` : ''}</div>`;
  // `onBack` overrides what the secondary link does (e.g. "Skip" moves forward)
  function wire(fields, onBack) {
    fields.forEach((id) => { const el = $(id); if (el) el.addEventListener('input', (e) => { data[id] = e.target.value; check(); }); });
    $('next')?.addEventListener('click', () => { if (!$('next').disabled) go(step + 1); });
    $('back')?.addEventListener('click', () => {
      if (onBack) onBack();
      else if (step === 0 && opts.onCancel) opts.onCancel();
      else go(step - 1);
    });
  }
  function check() { const b = $('next'); if (b) b.disabled = !SCENES[step].ok(); }
  let lastNod = 0;
  formEl.addEventListener('input', () => { attention(); const n = performance.now(); if (n - lastNod > 260) { lastNod = n; w.react('nod'); } }, { signal });
  formEl.addEventListener('focusin', attention, { signal });

  function nameTag(text) {
    if (!text) { tagEl.classList.remove('on'); return; }
    tagEl.textContent = text;
    tagEl.classList.add('on');
  }

  // a little card flies from the input into Warden's arms
  function flyCard(fromEl, label, icon) {
    if (reduce) return Promise.resolve();
    const a = fromEl.getBoundingClientRect(), b = w.getBoundingClientRect();
    const card = document.createElement('div');
    card.className = 'fly';
    card.innerHTML = `<img src="${ICONS[icon]}" alt="">${esc(label)}`;
    root.appendChild(card);
    card.style.left = a.left + 'px';
    card.style.top = a.top + 'px';
    const dx = b.left + b.width * 0.45 - a.left, dy = b.top + b.height * 0.5 - a.top;
    return card.animate([
      { transform: 'translate(0,0) scale(1)', opacity: 1 },
      { transform: `translate(${dx * 0.5}px, ${dy * 0.5 - 60}px) scale(.8)`, opacity: 1, offset: 0.5 },
      { transform: `translate(${dx}px, ${dy}px) scale(.2)`, opacity: 0 },
    ], { duration: 700, easing: 'cubic-bezier(.45,0,.4,1)' }).finished.then(() => card.remove());
  }

  // upload tiles: [key, icon, label, accept]
  function tiles(list, cls = '') {
    const tile = ([k, ic, l, accept]) => `<label class="tile ${data.files[k] ? 'has' : ''}" data-k="${k}" data-ic="${ic}"><img src="${ICONS[ic]}" alt=""><span>${data.files[k] ? '✓ ' + esc(data.files[k]) : l}</span><input type="file" accept="${accept}" aria-label="${l}"></label>`;
    return `<div class="tiles ${cls}">${list.map(tile).join('')}</div>`;
  }
  function wireTiles(onFirst) {
    formEl.querySelectorAll('.tile input').forEach((i) => i.addEventListener('change', async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      const t = e.target.closest('.tile');
      const was = [...formEl.querySelectorAll('.tile')].some((x) => data.files[x.dataset.k]);
      fileObjs[t.dataset.k] = f;
      data.files[t.dataset.k] = f.name.length > 16 ? f.name.slice(0, 14) + '…' : f.name;
      await flyCard(t, data.files[t.dataset.k], t.dataset.ic);
      if (!was && onFirst) onFirst();
      else { w.react('happy'); t.classList.add('has'); t.querySelector('span').textContent = '✓ ' + data.files[t.dataset.k]; }
      check();
    }));
  }

  function profileAnswers() {
    return { name: data.name.trim(), email: data.email.trim(), area: data.area.trim(), moveIn: data.date || null, firstTimeInUK: data.first === 'Yes' };
  }
  function caseAnswers() {
    return {
      listingUrl: data.url.trim(), listingSite: data.host, address: data.address.trim(), rent: data.rent.trim(),
      agency: data.agency.trim(), companyNumber: data.companyNumber.trim().toUpperCase(), agentName: data.agentName.trim(),
      seenInPerson: data.viewed, askedToPay: data.asked, paidAlready: data.paid === 'Yes',
      files: Object.keys(data.files), risky: !!risky(),
    };
  }

  // ======================= onboarding: get to know the student =======================
  const ONBOARDING = [
    { ok: () => true, run: async () => {
        setState('wave'); nameTag('');
        await say(`Hi, I'm <b>Warden.</b>`, "I lead a team of autonomous agents that check every rental for scams, so you know it's real before you pay.");
        showForm(`<div class="row"><button class="btn" id="next">Get started</button></div>`, () => wire([]), true);
    } },
    { ok: () => data.name.trim() && /.+@.+\..+/.test(data.email), run: async () => {
        setState('default');
        await say(`First, who am I looking out for?`, 'Your name, and an email so I can tell you when a check lands.');
        showForm(input('name', 'First name', 'text', 'e.g. Sam') + input('email', 'Email', 'email', 'you@example.com') + nextRow(), () => {
          wire(['name', 'email']);
          $('name').addEventListener('input', () => nameTag(first() ? `Hi, ${first()}!` : ''));
          if (first()) nameTag(`Hi, ${first()}!`);
        });
    } },
    { ok: () => data.area.trim() && data.first, run: async () => {
        setState('default'); nameTag(''); setTimeout(() => w.react('happy'), 250);
        await say(`Nice to meet you, <b>${first()}.</b><br>Where's the move?`, "Every area has a going rate. I'll know if a price is too good to be true.");
        showForm(input('area', 'Area', 'text', 'e.g. Camden or Mile End') + input('date', 'Move-in date', 'date') +
          `<div class="q">First time renting in the UK?</div>${chips('first', ['Yes', 'No'])}` + nextRow(), () => wire(['area', 'date']));
    } },
    { ok: () => true, run: async () => {
        setState('green');
        setTimeout(() => w.react('happy'), 300);
        await say(`Welcome, <b>${first() || 'friend'}!</b>`, 'Your dashboard is ready. When you find a place, tap New case and my agents get to work.');
        showForm(`<div class="row opening"><span class="spin"><i></i><i></i><i></i></span><span id="openMsg">Opening your dashboard</span></div>`, null, true);
        try {
          await new Promise((r) => setTimeout(r, 1500));
          await opts.onFinish(profileAnswers(), {});
        } catch {
          const m = $('openMsg');
          if (m) m.textContent = "Couldn't open your dashboard. Try again in a moment.";
        }
    } },
  ];

  // ======================= new case: check one place =======================
  const NEWCASE = [
    { ok: () => (!!data.host || !!data.address.trim()) && !readTimer, run: async () => {
        setState('default');
        await say(`Found a place${first() ? `, <b>${first()}?</b>` : '?'}`, profile.firstTimeInUK
          ? "Paste the listing or the address. New to UK renting? I'll flag anything that isn't normal here."
          : "Paste the listing or the address. I'll find out who's really behind it.");
        showForm(input('url', 'Listing link', 'url', 'https://') + `<div class="status" id="status"></div>` +
          `<div class="pair">${input('address', 'Address', 'text', 'e.g. Flat 2, 41 Mile End Road')}${input('rent', 'Rent per month', 'text', '£')}</div>` +
          nextRow('Continue', opts.onCancel ? 'Cancel' : ''), () => {
          wire(['address', 'rent']);
          $('url').addEventListener('input', (e) => { data.url = e.target.value; readListing(); });
          if (data.host) $('status').innerHTML = `<span class="ok">✓ Got it, it's on ${esc(data.host)}.</span>`;
        });
    } },
    { ok: () => true, run: async () => {
        setState('default');
        await say(`Who's letting it?`, 'The agency or landlord. With a company number my agency checker can start straight away.');
        showForm(input('agency', 'Agency or landlord', 'text', 'e.g. Quickkeys Lettings') +
          `<div class="pair">${input('companyNumber', 'Company number (optional)', 'text', 'e.g. 01234567')}${input('agentName', "Agent's name (optional)", 'text', 'e.g. Daniel')}</div>` +
          nextRow(), () => wire(['agency', 'companyNumber', 'agentName']));
    } },
    { ok: () => data.viewed && data.asked && data.paid, run: async () => {
        setState(risky() ? 'stop' : 'default');
        await say(`Be honest with me. How's it going?`, 'Scams follow a script. Your answers tell me how far along it is.');
        showForm(`<div class="q">Seen it in person?</div>${chips('viewed', ['Yes', 'No', 'Video call only'])}
          <div class="q">Asked to pay anything?</div>${chips('asked', ['No', 'Holding deposit', 'Deposit or rent upfront'])}
          <div class="q">Paid anything yet?</div>${chips('paid', ['No', 'Yes'])}
          <div id="warn"></div>` + nextRow(), () => {
          wire([]);
          let wasRisky = risky();
          const react = () => {
            const warnEl = $('warn');
            if (risky()) {
              if (!wasRisky) { setState('stop'); say(`Stop right there. <b>Don't pay yet.</b>`, 'Money before a viewing is page one of the scam playbook.').then(() => { formEl.classList.add('in'); nudge(); }); }
              warnEl.innerHTML = '';
            } else if (data.asked && data.asked !== 'No') {
              if (w.state !== 'amber') setState('amber');
              warnEl.innerHTML = `<div class="note">Hold any payment until I've checked who you'd be paying.</div>`;
            } else {
              if (w.state !== 'default') setState('default');
              warnEl.innerHTML = '';
            }
            wasRisky = risky();
          };
          formEl.querySelectorAll('.chips').forEach((g) => g.addEventListener('picked', react));
          react();
        });
    } },
    { ok: () => true, run: async () => {
        const has = ['messages', 'contract', 'video'].some((k) => data.files[k]);
        setState(has ? 'green' : risky() ? 'amber' : 'default');
        await say(has ? `Good clues. Keep them coming.` : `Got any receipts?`, has ? "Add anything else here, or let's keep going." : 'Chats, the contract, a viewing video. Every message is a clue. All optional.');
        showForm(tiles([['messages', 'chat', 'Messages', 'image/*,.txt,.zip'], ['contract', 'doc', 'Contract', '.pdf,image/*'], ['video', 'camera', 'Viewing video', 'video/*']]) +
          nextRow(has ? 'Continue' : 'Skip for now'), () => { wire([]); wireTiles(() => SCENES[step].run()); });
    } },
    { ok: () => true, run: async () => {
        setState('default');
        await say(`Anything else that could help?`, 'Emails, their ID, payment details or screenshots. Every document gives my agents more to go on.');
        showForm(tiles([
          ['emails', 'notes', 'Emails', '.eml,.pdf,.txt,image/*'],
          ['ownership', 'shield', 'Landlord ID or proof of ownership', '.pdf,image/*'],
          ['payment', 'checklist', 'Payment or deposit details', '.pdf,image/*'],
          ['screens', 'search', 'Listing screenshots', 'image/*,.pdf'],
        ], 'grid2') + nextRow('Done', 'Skip'), () => { wire([], () => go(step + 1)); wireTiles(null); });
    } },
    { ok: () => true, run: async () => {
        setState('thinking');
        const place = data.address.trim() ? esc(data.address.trim().split(',')[0]) : data.host ? `your ${esc(data.host)} listing` : 'this place';
        await say(`Leave it with me${first() ? `, <b>${first()}.</b>` : '.'}`, `My agents are on ${place} now: the agency, the chats, the contract. Watch each check land as it finishes.${risky() ? ' Keep your money until then.' : ''}`);
        showForm(`<div class="row opening"><span class="spin"><i></i><i></i><i></i></span><span id="openMsg">Opening your case</span></div>`, null, true);
        try {
          await new Promise((r) => setTimeout(r, 1200));
          await opts.onFinish(caseAnswers(), { ...fileObjs });
        } catch {
          const m = $('openMsg');
          if (m) m.textContent = "Couldn't open the case. Is Warden's server running? Try again in a moment.";
          setState('default');
        }
    } },
  ];

  const SCENES = MODE === 'onboarding' ? ONBOARDING : NEWCASE;

  function readListing() {
    clearTimeout(readTimer); readTimer = null; data.host = '';
    const st = $('status');
    let host = '';
    try { const u = new URL(data.url.trim()); if (/^https?:$/.test(u.protocol) && u.hostname.includes('.')) host = u.hostname.replace(/^www\./, ''); } catch { /* not a URL yet */ }
    if (!host) { st.textContent = data.url.trim() ? "That doesn't look like a link yet." : ''; if (w.state === 'thinking') setState('default'); check(); return; }
    st.textContent = '';
    flyCard($('url'), host, 'search').then(() => {
      if (data.url.trim() && !data.host) { setState('thinking'); st.innerHTML = 'Reading the listing…'; }
    });
    readTimer = setTimeout(() => {
      readTimer = null; data.host = host;
      setState('default');
      st.innerHTML = `<span class="ok">✓ Got it, it's on ${esc(host)}.</span>`;
      setTimeout(() => w.react('happy'), 700);
      check();
    }, 1600);
    check();
  }

  function go(i) {
    if (i < 0 || i >= SCENES.length) return;
    const before = w.state;
    step = i; drawRail();
    SCENES[step].run();
    if (w.state === before) setTimeout(() => w.react(i > 0 ? 'hop' : 'wiggle'), 60);
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.type !== 'file') {
      e.preventDefault();
      const b = $('next');
      if (b && !b.disabled) b.click();
    }
  }, { signal });
  go(0);
  return () => { ac.abort(); clearTimeout(readTimer); sayToken++; };
}

export { startWardenOnboarding };

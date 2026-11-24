/* Australian Telco Compare: page logic for home internet (inputs, ranking, charts). */
(function () {
  "use strict";
  const D = window.TELCO_DATA, E = window.TelcoEngine;
  const $ = (s, el = document) => el.querySelector(s);
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(k));
    return el;
  };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = x => (x < 0 ? "−$" : "$") + Math.round(Math.abs(x)).toLocaleString("en-AU");
  const price = x => "$" + (Math.abs(x % 1) > 0.004 ? x.toFixed(2) : String(Math.round(x)));
  const fmtNum = (x, d = 0) => Number(x).toLocaleString("en-AU", { maximumFractionDigits: d, minimumFractionDigits: d });
  const fmtDate = iso => new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
  const shortDate = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short" });

  /* ------------------------------------------------------------------ reference data */
  // Fixed colour per kind of service (colour follows the entity, never its rank).
  const KINDS = {
    nbn: { label: "NBN", color: "var(--s1)" },
    "5g": { label: "5G home internet", color: "var(--s2)" },
    fixed_wireless: { label: "NBN fixed wireless", color: "var(--s3)" },
    starlink: { label: "Starlink", color: "var(--s4)" },
    satellite: { label: "NBN satellite", color: "var(--s5)" },
    private: { label: "Private network", color: "var(--s6)" },
  };
  const TECHS = [
    ["unknown", "Not sure"], ["fttp", "FTTP: fibre to the premises"], ["hfc", "HFC: cable"],
    ["fttc", "FTTC: fibre to the curb"], ["fttn", "FTTN: fibre to the node"], ["fttb", "FTTB: fibre to the building"],
    ["fw", "Fixed wireless"], ["sat", "Satellite (Sky Muster)"],
  ];
  const TECH_SHORT = { unknown: "Not sure", fttp: "FTTP", hfc: "HFC", fttc: "FTTC", fttn: "FTTN", fttb: "FTTB", fw: "Fixed wireless", sat: "Satellite" };
  const NETS = [["telstra", "Telstra"], ["optus", "Optus"], ["vodafone", "Vodafone"]];
  const netName = n => (NETS.find(x => x[0] === n) || [n, n])[1];
  const NBN_CHECK = "https://www.nbnco.com.au/connect-home-or-business/check-your-address";
  const ENERGY_SITE = "https://plasky.github.io/melbourne-energy-compare/";
  const TIER_PICKS = [25, 50, 100, 250, 500, 1000, 2000];
  function tierOptions(tech) {
    if (["fttn", "fttb", "fttc"].includes(tech)) return [25, 50, 100];
    if (tech === "fw") return [25, 50, 100, 250];
    if (tech === "sat") return [25];
    return [25, 50, 100, 500, 1000, 2000];
  }
  const provName = id => (D.providers[id] || {}).name || id;

  /* ------------------------------------------------------------------ state */
  const DEFAULTS = {
    conn: { tech: "unknown", fiveG: true, nets: ["telstra", "optus", "vodafone"], starlink: false, privateNet: false },
    use: { people: 4, uhd: 1, hd: 2, calls: 1, gamers: 1, uploadGB: 0, uploadHours: 6 },
    speed: { pick: 0 },     // 0 = from usage; otherwise the NBN tier picked
    cost: { months: 12, reswitch: false, needModem: false, modemPrice: 150, credits: false, bundles: false, unverified: true },
    current: { price: 0 },
    ui: { sel: null, bestPer: true, sort: "cost", shown: 25 },
  };
  const KEY = "atc-state-v1", KEY_AT = "atc-saved-at", FILE_APP = "au-telco-compare";
  const clone = o => JSON.parse(JSON.stringify(o));
  function merge(base, over) {
    if (!over || typeof over !== "object" || Array.isArray(base)) return over === undefined ? base : over;
    const out = { ...base };
    for (const k of Object.keys(base)) if (k in over) out[k] = merge(base[k], over[k]);
    return out;
  }
  function fromSaved(saved) {
    const st = merge(clone(DEFAULTS), saved || {});
    if (!TECHS.some(t => t[0] === st.conn.tech)) st.conn.tech = "unknown";
    st.conn.nets = Array.isArray(st.conn.nets) ? st.conn.nets.filter(n => NETS.some(x => x[0] === n)) : clone(DEFAULTS.conn.nets);
    if (![12, 24, 36].includes(st.cost.months)) st.cost.months = 12;
    if (st.speed.pick && !TIER_PICKS.includes(st.speed.pick)) st.speed.pick = 0;
    st.ui.shown = 25;
    return st;
  }
  let S = clone(DEFAULTS), savedAt = null, storageOk = true;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) S = fromSaved(JSON.parse(raw));
    const t = localStorage.getItem(KEY_AT);
    if (t) savedAt = new Date(t);
  } catch (e) { storageOk = false; }
  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(S));
      savedAt = new Date(); localStorage.setItem(KEY_AT, savedAt.toISOString());
      storageOk = true;
    } catch (e) { storageOk = false; }
  }
  const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
  function setPath(o, p, v) { const ks = p.split("."); let t = o; for (let i = 0; i < ks.length - 1; i++) t = t[ks[i]]; t[ks[ks.length - 1]] = v; }

  /* ------------------------------------------------------------------ model helpers */
  const need = () => {
    const n = E.neededSpeed(S.use);
    return S.speed.pick ? Object.assign({}, n, { minTier: S.speed.pick }) : n;
  };
  const avail = () => ({ fiveG: S.conn.fiveG ? S.conn.nets : false, starlink: S.conn.starlink, privateNet: S.conn.privateNet });
  const costOpts = () => ({
    months: S.cost.months, modemPrice: S.cost.needModem ? S.cost.modemPrice : 0, credits: S.cost.credits,
    bundled: S.cost.bundles, tech: S.conn.tech, avail: avail(),
  });
  function kindLine(p) {
    if (p.kind === "nbn") return `NBN ${p.tier}`;
    if (p.kind === "5g") return p.network ? `5G home internet on ${netName(p.network)}` : "5G home internet";
    return KINDS[p.kind] ? KINDS[p.kind].label : p.kind;
  }
  const speedText = p => p.down != null ? `${fmtNum(p.down)}${p.up != null ? " / " + fmtNum(p.up) : ""} Mbps` : "Not published";
  const speedOf = p => p.down != null ? p.down : (p.tier || 0);

  /* ------------------------------------------------------------------ inputs */
  const fields = [];
  function sliderPct(inp) { inp.style.setProperty("--p", ((inp.value - inp.min) / (inp.max - inp.min) * 100) + "%"); }
  function slider(path, label, min, max, step, fmt, hint) {
    const out = h("output");
    const inp = h("input", { type: "range", min, max, step, "aria-label": label });
    inp.addEventListener("input", () => { setPath(S, path, Number(inp.value)); out.textContent = fmt(Number(inp.value)); sliderPct(inp); changed(); });
    const el = h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, label), out), inp, hint ? h("div", { class: "hint" }, hint) : null);
    fields.push({ update() { inp.value = getPath(S, path); out.textContent = fmt(Number(inp.value)); inp.setAttribute("aria-valuetext", out.textContent); sliderPct(inp); } });
    return el;
  }
  function seg(path, label, options, full = true, visibleFn = null) {
    const g = h("div", { class: "seg" + (full ? " full" : ""), role: "group", "aria-label": label });
    const btns = options.map(([v, t]) => {
      const b = h("button", { type: "button", onclick: () => { setPath(S, path, v); upd(); changed(); } }, t);
      b._v = v; g.append(b); return b;
    });
    function upd() {
      const cur = getPath(S, path);
      for (const b of btns) { b.setAttribute("aria-pressed", String(b._v === cur)); if (visibleFn) b.hidden = !visibleFn(b._v); }
    }
    fields.push({ update: upd });
    return h("div", { class: "field" }, label ? h("div", { class: "lab" }, h("span", {}, label)) : null, g);
  }
  function select(path, label, options, hint) {
    const sel = h("select", { "aria-label": label }, options.map(([v, t]) => h("option", { value: v }, t)));
    sel.addEventListener("change", () => { setPath(S, path, sel.value); changed(); });
    fields.push({ update() { sel.value = getPath(S, path); } });
    return h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, label)), sel, hint || null);
  }
  function toggle(path, label, hint) {
    const inp = h("input", { type: "checkbox" });
    inp.addEventListener("change", () => { setPath(S, path, inp.checked); changed(); });
    fields.push({ update() { inp.checked = !!getPath(S, path); } });
    return h("div", { class: "field" },
      h("label", { class: "toggle" }, inp, h("span", { class: "knob" }), h("span", {}, label)),
      hint ? h("div", { class: "hint" }, hint) : null);
  }
  function netChecks() {
    const box = h("div", { class: "checks cols3" });
    for (const [id, name] of NETS) {
      const inp = h("input", { type: "checkbox" });
      inp.addEventListener("change", () => {
        const set = new Set(S.conn.nets);
        inp.checked ? set.add(id) : set.delete(id);
        S.conn.nets = NETS.map(n => n[0]).filter(n => set.has(n)); changed();
      });
      fields.push({ update() { inp.checked = S.conn.nets.includes(id); } });
      box.append(h("label", { class: "check" }, inp, name));
    }
    return h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, "Networks with 5G coverage at your address")), box,
      h("div", { class: "hint" }, "Coverage is address by address. Each provider's sign-up page checks your address before you commit."));
  }
  function showIf(el, fn) { fields.push({ update() { el.hidden = !fn(); } }); return el; }
  function group(title, ...kids) { return h("div", { class: "sub-group" }, title ? h("h3", {}, title) : null, ...kids); }
  function note(fn) { const el = h("div", { class: "hint" }); fields.push({ update() { el.textContent = fn(); } }); return el; }

  function needNote() {
    const n = E.neededSpeed(S.use);
    if (!n.parts.length) return "Add at least one person.";
    const bits = n.parts.map(p => `${p.label.toLowerCase()} ${fmtNum(p.down, p.down % 1 ? 1 : 0)}${p.up ? "/" + fmtNum(p.up, p.up % 1 ? 1 : 0) : ""}`);
    return `Adds up to ${fmtNum(n.parts.reduce((a, p) => a + p.down, 0))}/${fmtNum(n.parts.reduce((a, p) => a + p.up, 0), 1)} Mbps (${bits.join(", ")}), plus ${Math.round((n.headroom - 1) * 100)}% headroom because shared connections never run flat out.`;
  }

  const SECTIONS = [
    { id: "conn", title: "Your connection", open: true,
      sum: () => TECH_SHORT[S.conn.tech] + (S.conn.fiveG && S.conn.nets.length ? " · 5G" : "") + (S.conn.starlink ? " · Starlink" : ""),
      body: () => [
        select("conn.tech", "NBN connection type at your address", TECHS,
          h("div", { class: "hint" }, "Not sure? ", h("a", { href: NBN_CHECK, target: "_blank", rel: "noopener" }, "Check your address on NBN Co's site"),
            ". Speeds of 250 Mbps and above need FTTP or HFC.")),
        group("Other ways to connect",
          toggle("conn.fiveG", "Include 5G home internet"),
          showIf(netChecks(), () => S.conn.fiveG),
          toggle("conn.starlink", "Include Starlink", "Satellite internet that works almost anywhere. Mostly worth it where NBN is slow or unavailable."),
          toggle("conn.privateNet", "My building or estate has its own network", "Shows providers that sell only on their own fibre or wireless networks. Check that one serves your address.")),
      ] },
    { id: "use", title: "What you use it for", open: true,
      sum: () => { const n = need(); return n.minTier ? `NBN ${n.minTier}+` : `${n.down}/${n.up} Mbps`; },
      body: () => [
        slider("use.people", "People at home", 1, 10, 1, v => String(v)),
        slider("use.uhd", "4K streams at the same time", 0, 6, 1, v => String(v)),
        slider("use.hd", "HD streams at the same time", 0, 8, 1, v => String(v)),
        slider("use.calls", "Video calls at the same time", 0, 6, 1, v => String(v)),
        slider("use.gamers", "Online gamers", 0, 6, 1, v => String(v), "Gaming needs a steady, low-lag line more than a fast one."),
        slider("use.uploadGB", "Big uploads (backups, video, work files)", 0, 200, 5, v => v ? `${v} GB a day` : "None"),
        showIf(slider("use.uploadHours", "…finished within", 1, 12, 1, v => `${v} hour${v > 1 ? "s" : ""}`), () => S.use.uploadGB > 0),
        note(needNote),
        group("Speed",
          seg("speed.pick", "Minimum speed", [[0, "From my usage"], ...TIER_PICKS.map(t => [t, String(t)])], false,
            v => v === 0 || tierOptions(S.conn.tech).includes(v)),
          note(() => S.speed.pick ? `Showing NBN ${S.speed.pick} plans and faster, and other services with evening speeds of at least ${fmtNum(0.8 * S.speed.pick)} Mbps.`
            : "Picks plans whose typical evening speed covers what your household needs. Choose a tier to set it yourself.")),
      ] },
    { id: "cost", title: "Costs to count", open: false,
      sum: () => `${S.cost.months} months${S.cost.reswitch ? " · re-switch" : ""}${S.cost.needModem ? " · modem" : ""}`,
      body: () => [
        seg("cost.months", "Compare the cost over", [[12, "12 months"], [24, "24 months"], [36, "36 months"]]),
        toggle("cost.reswitch", "I'll switch again each time an intro offer ends",
          "Assumes you move to the cheapest new-customer offer of the same speed or faster, never back to a provider you've used."),
        toggle("cost.needModem", "I need a modem", "Plans that include one cost nothing extra. 5G and Starlink hardware always counts."),
        showIf(slider("cost.modemPrice", "A modem of your own would cost", 50, 400, 10, v => "$" + v,
          "Used for plans that don't include or sell one."), () => S.cost.needModem),
        toggle("cost.credits", "Count sign-up credits"),
        toggle("cost.bundles", "Count bundle discounts", "Discounts for also taking the provider's mobile or energy. Mobile plans are costed separately (coming soon)."),
        toggle("cost.unverified", "Include plans not yet checked with the provider",
          "These come from Bill Hero's open data and sometimes show an intro price as the ongoing price."),
      ] },
    { id: "current", title: "What you pay now", open: false,
      sum: () => S.current.price ? price(S.current.price) + "/month" : "Not set",
      body: () => [
        slider("current.price", "Your internet bill each month", 0, 250, 1, v => v ? "$" + v : "Not set", "Shows how much switching would save."),
      ] },
    { id: "save", title: "Save & restore", open: false, sum: () => (storageOk ? "Saved in this browser" : "Not saving"), body: () => saveSection() },
  ];

  /* ---- save & restore */
  function fmtWhen(d) {
    const now = new Date(), t = d.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }).replace(/\s/g, "").toLowerCase();
    return d.toDateString() === now.toDateString() ? `today at ${t}` : `${d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" })} at ${t}`;
  }
  function saveStatus() {
    if (!storageOk) return "This browser isn't letting the page save (a private window, or site data blocked). Use Save to file before you close it.";
    return `Every change saves automatically in this browser${savedAt ? `, last ${fmtWhen(savedAt)}` : ""}. Come back to this page in the same browser and you'll carry on where you left off.`;
  }
  function saveSection() {
    const msg = h("div", { class: "hint", role: "status" });
    const say = t => { msg.textContent = t; };
    const fileIn = h("input", { type: "file", accept: ".json,application/json", hidden: true });
    fileIn.addEventListener("change", async () => {
      const f = fileIn.files[0]; fileIn.value = "";
      if (!f) return;
      try {
        const d = JSON.parse(await f.text());
        if (!d || d.app !== FILE_APP || !d.settings || typeof d.settings !== "object") throw new Error("not a settings file");
        applySettings(fromSaved(d.settings));
        say(`Loaded ${f.name}${d.saved ? ` (saved ${fmtWhen(new Date(d.saved))})` : ""}.`);
      } catch (e) { say("That file isn't a settings file from this page, so nothing was changed."); }
    });
    let armed = 0;
    const resetBtn = h("button", { type: "button", class: "btn" }, "Reset to defaults");
    resetBtn.addEventListener("click", () => {
      if (!armed) { resetBtn.textContent = "Click again to reset"; armed = setTimeout(() => { armed = 0; resetBtn.textContent = "Reset to defaults"; }, 4000); return; }
      clearTimeout(armed); armed = 0; resetBtn.textContent = "Reset to defaults";
      applySettings(clone(DEFAULTS)); say("Reset to the defaults.");
    });
    return [
      note(saveStatus),
      h("div", { class: "btn-row" },
        h("button", { type: "button", class: "btn", onclick: () => { exportSettings(); say("Settings file downloaded."); } }, "Save to file"),
        h("button", { type: "button", class: "btn", onclick: () => fileIn.click() }, "Load from file"),
        resetBtn),
      fileIn, msg,
      h("div", { class: "hint" }, "A settings file moves your setup to another browser or computer, or keeps a backup."),
    ];
  }
  function exportSettings() {
    const now = new Date();
    const data = { app: FILE_APP, version: 1, saved: now.toISOString(), settings: S };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = h("a", { href: url, download: `telco-compare-settings-${now.toISOString().slice(0, 10)}.json` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function applySettings(st) { S = st; save(); updateInputs(); recompute(); }

  const sumEls = {};
  function buildInputs() {
    const root = $("#inputs");
    for (const sec of SECTIONS) {
      const sum = h("span", { class: "sum" });
      sumEls[sec.id] = { el: sum, fn: sec.sum };
      root.append(h("details", { class: "sec", "data-sec": sec.id, ...(sec.open ? { open: true } : {}) },
        h("summary", {}, h("span", {}, sec.title), sum),
        h("div", { class: "sec-body" }, sec.body())));
    }
  }
  function updateInputs() {
    if (S.speed.pick && !tierOptions(S.conn.tech).includes(S.speed.pick)) S.speed.pick = 0;
    for (const f of fields) f.update();
    for (const k in sumEls) sumEls[k].el.textContent = sumEls[k].fn();
  }

  /* ------------------------------------------------------------------ model */
  let M = null, timer = 0;
  function changed() { save(); updateInputs(); if (!timer) timer = setTimeout(() => { timer = 0; recompute(); }, 16); }

  function buildModel() {
    const N = need(), A = avail(), tech = S.conn.tech, o = costOpts();
    const pool = D.internet.filter(p => S.cost.unverified || p.verified);
    const rows = pool.map(p => ({ p, t: E.techOk(p, tech, A), m: E.meets(p, N, tech, A) }));
    const shown = rows.filter(r => r.t.ok);
    const fits = shown.filter(r => r.m.ok);
    const fitPlans = fits.map(r => r.p);
    for (const r of shown) {
      r.stay = E.internetCost(r.p, o);
      r.chase = r.m.ok && r.p.promo ? E.reswitchCost(r.p, fitPlans, N, o) : null;
      r.c = S.cost.reswitch && r.chase ? r.chase : r.stay;
      r.speed = speedOf(r.p);
    }
    const byCost = fits.slice().sort((a, b) => a.c.total - b.c.total || b.speed - a.speed);
    const front = E.frontier(shown.map(r => ({ r, cost: r.c.perMonth, speed: r.speed })));
    const frontIds = new Set(front.map(x => x.r.p.id));
    const excluded = { slow: rows.filter(r => r.t.ok && !r.m.ok).length, tech: rows.filter(r => !r.t.ok).length };
    return { N, A, rows, shown, fits, byCost, front, frontIds, excluded, byId: new Map(shown.map(r => [r.p.id, r])) };
  }

  function recompute() {
    M = buildModel();
    let sel = M.byId.get(S.ui.sel);
    if (!sel) { sel = M.byCost[0] || null; S.ui.sel = sel ? sel.p.id : null; }
    M.sel = sel;
    renderReadout(); renderTiles(); renderPlanCard(); renderScatter(); renderRank(); renderMbar();
  }

  /* ------------------------------------------------------------------ readout + tiles */
  function renderReadout() {
    const n = M.N;
    const speedBit = n.minTier
      ? `<b>NBN ${n.minTier}</b> or faster`
      : `about <b>${fmtNum(n.down)} Mbps</b> down and <b>${fmtNum(n.up)} Mbps</b> up`;
    $("#readout").innerHTML = `<div>Your household needs ${speedBit} in the evening (7–11pm), when networks are busiest.</div>
      <div class="bench">${M.fits.length} of ${M.rows.length} plans fit · connection: ${esc(TECH_SHORT[S.conn.tech])}</div>`;
  }

  function tile(label, value, what, delta, r) {
    const b = h("button", { class: "tile" + (r && M.sel && r.p.id === M.sel.p.id ? " selected" : ""), type: "button",
      onclick: () => { if (r) select_(r.p.id, true); } },
      h("div", { class: "label" }, label),
      h("div", { class: "value", html: value }),
      h("div", { class: "what" }, what),
      delta ? h("div", { class: "delta", html: delta }) : null);
    return b;
  }
  const horizon = () => `${S.cost.months} months`;
  function renderTiles() {
    const el = $("#tiles"); el.innerHTML = "";
    const best = M.byCost[0];
    if (!best) {
      el.append(tile("Cheapest that does the job", "–", "No plan fits these settings", "Try a lower speed or another connection type."));
      return;
    }
    const nm = r => `${provName(r.p.provider)} · ${r.p.name}`;
    const after = r => r.p.promo && r.p.promo.months < S.cost.months ? `, then ${price(r.p.price)}/month` : "";
    el.append(tile("Cheapest that does the job", `${money(best.c.total)} <small>over ${horizon()}</small>`, nm(best),
      `${money(best.c.perMonth)}/month on average${after(best)}${best.p.verified ? "" : ' · <span class="warn-t">price not yet checked</span>'}${best.m.flags.length ? ` · <span class="warn-t">${esc(best.m.flags[0][0].toLowerCase() + best.m.flags[0].slice(1))}</span>` : ""}`, best));
    const faster = M.byCost.find(r => r.speed >= 1.8 * best.speed);
    if (faster) {
      const extra = faster.c.perMonth - best.c.perMonth;
      el.append(tile("Next speed up", `+${money(Math.max(0, extra))} <small>a month</small>`, nm(faster),
        `${fmtNum(faster.speed)} Mbps in the evening vs ${fmtNum(best.speed)}`, faster));
    } else {
      el.append(tile("Next speed up", "–", "Nothing much faster fits", "Pick another connection type for faster plans."));
    }
    if (S.current.price > 0) {
      const now = S.current.price * S.cost.months, save = now - best.c.total;
      el.append(tile("Versus what you pay now", save > 0 ? `<b class="good">${money(save)}</b> <small>saved over ${horizon()}</small>` : `${money(-save)} <small>more</small>`,
        nm(best), `You pay ${money(now)} over ${horizon()} at ${price(S.current.price)}/month`, best));
    } else {
      const checked = M.byCost.find(r => r.p.verified);
      const steady = M.byCost.find(r => !r.p.promo);
      const chase = M.fits.filter(r => r.chase && r.chase.steps.length > 1).sort((a, b) => a.chase.total - b.chase.total)[0];
      if (!best.p.verified && checked) {
        el.append(tile("Cheapest checked with the provider", `${money(checked.c.total)} <small>over ${horizon()}</small>`, nm(checked),
          `${money(checked.c.perMonth)}/month on average${after(checked)}`, checked));
      } else if (steady && steady !== best) {
        el.append(tile("Cheapest with no price jump", `${money(steady.c.total)} <small>over ${horizon()}</small>`, nm(steady),
          `${price(steady.p.price)}/month from day one, no intro offer to run out`, steady));
      } else if (chase && !S.cost.reswitch && chase.chase.total < best.c.total) {
        el.append(tile("If you switch when offers end", `${money(chase.chase.total)} <small>over ${horizon()}</small>`, nm(chase),
          `Starting here, then moving to the next new-customer offer: ${money(best.c.total - chase.chase.total)} less than staying put on the cheapest`, chase));
      }
    }
  }
  function renderMbar() {
    const el = $("#mbar"), best = M.byCost[0];
    if (!best) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `<span>Cheapest that fits: <b>${money(best.c.perMonth)}/month</b></span><span>${esc(provName(best.p.provider))} · ${esc(best.p.name)}</span>`;
  }

  /* ------------------------------------------------------------------ plan card */
  function badgesFor(p, r) {
    const b = [];
    if (p.promo) b.push([`${price(p.promo.price)}/month for ${p.promo.months} month${p.promo.months > 1 ? "s" : ""}${p.promo.requires ? ` with ${provName(p.provider)} ${p.promo.requires}` : ""}${p.promo.until ? `, sign up by ${shortDate(p.promo.until)}` : ""}`, p.promo.requires && !S.cost.bundles ? "" : "free"]);
    b.push([p.contract ? `${p.contract}-month contract` : "No lock-in contract", ""]);
    const m = p.modem || {};
    if (m.offer === "included") b.push(["Modem included", ""]);
    else if (m.offer === "included_contract") b.push([m.fee ? `Modem included (${price(m.fee)} if you leave within ${m.months || "?"} months)` : "Modem included (pay it out if you leave early)", ""]);
    else if (m.offer === "purchase") b.push([m.cost != null ? `Modem ${price(m.cost)}` : "Modem sold separately", ""]);
    else if (m.offer === "rental") b.push([`Modem rental ${price(m.monthly)}/month`, ""]);
    else if (m.offer === "byo") b.push(["Bring your own modem", ""]);
    if (p.setup) b.push([`Setup ${price(p.setup)}`, ""]);
    if (p.data_gb) b.push([`${fmtNum(p.data_gb)} GB a month`, "warn"]);
    for (const x of p.bundle || []) b.push([`${price(x.off)}/month off with ${x.with}`, ""]);
    if (p.credit) b.push([`${price(p.credit)} sign-up credit`, ""]);
    for (const f of (r && r.m.flags) || []) b.push([f, "warn"]);
    if (!p.verified) b.push(["Price not yet checked with the provider", "warn"]);
    return b;
  }
  const badgeHtml = (p, r) => badgesFor(p, r).map(([t, c]) => `<span class="badge ${c}">${esc(t)}</span>`).join("");

  function breakdownRows(r) {
    const p = r.p, o = costOpts(), rows = [];
    if (S.cost.reswitch && r.chase && r.chase.steps.length > 1) {
      let m0 = 1;
      for (const st of r.chase.steps) {
        const q = M.byId.get(st.id), pp = q ? q.p : p;
        const span = st.months > 1 ? `Months ${m0}–${m0 + st.months - 1}` : `Month ${m0}`;
        const what = st.promo ? `${provName(pp.provider)} intro offer, ${price(pp.promo.price)}/month` : `${provName(pp.provider)} ongoing price, ${price(pp.price)}/month`;
        rows.push([`${span}: ${what}${st.promo && pp.setup && m0 > 1 ? ` + ${price(pp.setup)} setup` : ""}`, st.cost]);
        m0 += st.months;
      }
      return rows;
    }
    const c = r.stay.parts, ap = E.activePromo(p, o), pm = ap ? Math.min(ap.months, o.months) : 0;
    if (pm) rows.push([`${pm} month${pm > 1 ? "s" : ""} at the intro price of ${price(p.promo.price)}`, c.promo]);
    if (o.months - pm > 0) rows.push([`${o.months - pm} month${o.months - pm > 1 ? "s" : ""} at ${price(p.price)}`, c.ongoing + (pm ? 0 : 0)]);
    if (c.bundleSave) rows.push([`Bundle discount (already taken off above)`, -c.bundleSave, true]);
    if (c.rental) rows.push([`Modem rental, ${o.months} months at ${price(p.modem.monthly)}`, c.rental]);
    if (c.setup) rows.push(["Setup fee", c.setup]);
    if (c.modem) rows.push([p.kind === "5g" || p.kind === "starlink" ? "Hardware" : "Modem", c.modem]);
    if (c.credit) rows.push(["Sign-up credit", -c.credit]);
    return rows;
  }

  function renderPlanCard() {
    const card = $("#plan-card"), r = M.sel;
    if (!r) { card.innerHTML = `<p class="empty">No plan fits these settings. Try a lower speed, another connection type, or include 5G home internet.</p>`; return; }
    const p = r.p, o = costOpts();
    const kv = breakdownRows(r).map(([t, v, info]) => `<tr${info ? ' class="info"' : ""}><td>${esc(t)}</td><td class="${v < 0 ? "neg" : ""}">${info ? "(" + money(-v) + ")" : money(v)}</td></tr>`).join("");
    const links = [p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">Plan page ↗</a>` : "",
      p.cis_url ? `<a href="${esc(p.cis_url)}" target="_blank" rel="noopener">Critical Information Summary ↗</a>` : ""].filter(Boolean).join("");
    const warn = !r.m.ok ? `<div class="warnlist"><b>Doesn't fit your settings:</b> ${r.m.reasons.map(esc).join("; ")}.</div>` : "";
    const src = (D.meta.sources.find(s => s.id === p.source) || {}).name || p.source;
    card.innerHTML = `
      <div class="plan-top">
        <div><div class="plan-name">${esc(p.name)}</div>
          <div class="plan-retailer">${esc(provName(p.provider))} · ${esc(kindLine(p))} · evening speed ${esc(speedText(p))}</div></div>
        <div class="plan-cost"><div class="big">${money(r.c.total)}</div>
          <div class="per">over ${horizon()} · ${money(r.c.perMonth)}/month on average${S.cost.reswitch && r.chase ? " · re-switching" : ""}</div></div>
      </div>
      <div class="badges">${badgeHtml(p, r)}</div>${warn}
      <div class="plan-grid">
        <div>
          <table class="kv">${kv}<tr class="total"><td>Total over ${horizon()}</td><td>${money(r.c.total)}</td></tr></table>
          <div class="links">${links}</div>
          ${p.notes ? `<p class="small">${esc(p.notes)}</p>` : ""}
          <p class="small">${!p.verified ? "From Bill Hero's open data, not yet checked with the provider" : p.source === "billhero" || p.source === "override" ? "Checked by hand against the provider's own site" : `From the provider's own published plan data (${esc(src)})`}. Check the provider's Critical Information Summary before you sign up.</p>
        </div>
        <div>
          <h3>Month by month</h3>
          <div id="month-chart" class="chart"></div>
          <div id="month-legend" class="legend"></div>
          <details class="table-view"><summary>Show as table</summary><div id="month-table"></div></details>
        </div>
      </div>`;
    renderMonth(r);
  }

  /* ------------------------------------------------------------------ charts: shared */
  const SVGNS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}) => { const el = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); return el; };
  function niceMax(v) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p; return 10 * p; }
  function niceStep(range, n) { const raw = range / n, p = Math.pow(10, Math.floor(Math.log10(raw))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p; return 10 * p; }
  const tip = $("#tip");
  function showTip(ev, html) {
    tip.innerHTML = html; tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  /* ---- month by month (step lines; month 1 includes one-off costs) */
  function renderMonth(r) {
    const box = $("#month-chart"); if (!box) return;
    const n = S.cost.months, series = [];
    series.push({ name: "Staying on this plan", color: "var(--s1)", v: r.stay.monthly });
    if (r.chase && r.chase.steps.length > 1) series.push({ name: "Switching when each offer ends", color: "var(--s2)", v: r.chase.monthly });
    if (S.current.price > 0) series.push({ name: "What you pay now", color: "var(--muted)", v: Array(n).fill(S.current.price), dash: true });
    const W = Math.max(260, box.clientWidth || 360), H = 190, ml = 40, mr = 8, mt = 8, mb = 22;
    const max = niceMax(Math.max(...series.flatMap(s => s.v)) * 1.05);
    const x = i => ml + (i / n) * (W - ml - mr), y = v => mt + (1 - v / max) * (H - mt - mb);
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Monthly cost over the comparison period" });
    const step = niceStep(max, 4);
    for (let v = 0; v <= max + 1e-9; v += step) {
      svg.append(sv("line", { x1: ml, x2: W - mr, y1: y(v), y2: y(v), class: v === 0 ? "baseline" : "gridline" }));
      const t = sv("text", { x: ml - 6, y: y(v) + 3.5, "text-anchor": "end" }); t.textContent = "$" + fmtNum(v); svg.append(t);
    }
    const every = n <= 12 ? 3 : 6;
    for (let i = 0; i < n; i += every) { const t = sv("text", { x: x(i + 0.5), y: H - 6, "text-anchor": "middle" }); t.textContent = "M" + (i + 1); svg.append(t); }
    for (const s of series) {
      let d = "";
      s.v.forEach((v, i) => { d += (i ? `H${x(i)}V${y(v)}` : `M${x(0)},${y(v)}`) + `H${x(i + 1)}`; });
      svg.append(sv("path", { d, class: "step", stroke: s.color, ...(s.dash ? { "stroke-dasharray": "5 4" } : {}) }));
    }
    const xh = sv("line", { class: "xhair", y1: mt, y2: H - mb, x1: 0, x2: 0, visibility: "hidden" }); svg.append(xh);
    for (let i = 0; i < n; i++) {
      const hit = sv("rect", { x: x(i), y: mt, width: x(i + 1) - x(i), height: H - mt - mb, class: "hit" });
      hit.addEventListener("mousemove", ev => {
        xh.setAttribute("x1", x(i + 0.5)); xh.setAttribute("x2", x(i + 0.5)); xh.setAttribute("visibility", "visible");
        const extra = i === 0 && (r.stay.parts.setup || r.stay.parts.modem) ? `<div class="small">Month 1 includes setup and hardware.</div>` : "";
        showTip(ev, `<div class="t-h">Month ${i + 1}</div>` + series.map(s => `<div class="t-r"><span><i style="background:${s.color}"></i>${esc(s.name)}</span><span>${price(s.v[i])}</span></div>`).join("") + extra);
      });
      hit.addEventListener("mouseleave", () => { hideTip(); xh.setAttribute("visibility", "hidden"); });
      svg.append(hit);
    }
    box.innerHTML = ""; box.append(svg);
    $("#month-legend").innerHTML = series.length > 1
      ? series.map(s => `<span><i class="line" style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")
      : `<span class="small">Month 1 includes any setup fee and hardware.</span>`;
    $("#month-table").innerHTML = `<div class="tv-scroll"><table><tr><th>Month</th>${series.map(s => `<th>${esc(s.name)}</th>`).join("")}</tr>` +
      Array.from({ length: n }, (_, i) => `<tr><td>${i + 1}</td>${series.map(s => `<td>${price(s.v[i])}</td>`).join("")}</tr>`).join("") +
      `<tr><td><b>Total</b></td>${series.map(s => `<td><b>${money(s.v.reduce((a, b) => a + b, 0))}</b></td>`).join("")}</tr></table></div>`;
  }

  /* ---- price vs evening speed scatter */
  function renderScatter() {
    const box = $("#scatter"), pts = M.shown.filter(r => r.speed > 0);
    $("#scatter-sub").textContent = pts.length
      ? `Every plan that works on your connection: average cost per month over ${horizon()} against typical evening download speed. Faded plans are too slow for your settings. The line joins the best-value plans: nothing else is both cheaper and faster.`
      : "No plans to show.";
    box.innerHTML = ""; $("#scatter-legend").innerHTML = ""; $("#scatter-table").innerHTML = "";
    if (!pts.length) return;
    const W = Math.max(300, box.clientWidth || 600), H = Math.round(Math.min(380, Math.max(260, W * 0.5)));
    const ml = 46, mr = 14, mt = 12, mb = 34;
    const sMin = Math.min(...pts.map(r => r.speed)), sMax = Math.max(...pts.map(r => r.speed));
    const lx0 = Math.log10(Math.max(5, sMin / 1.25)), lx1 = Math.log10(sMax * 1.2);
    const costs = pts.map(r => r.c.perMonth).sort((a, b) => a - b);
    const cap = costs[Math.floor(costs.length * 0.98)] || costs[costs.length - 1];
    const yMax = niceMax(Math.max(cap, M.sel ? M.sel.c.perMonth : 0) * 1.04);
    const yMin = Math.max(0, Math.floor((costs[0] * 0.9) / 10) * 10);
    const x = s => ml + (Math.log10(s) - lx0) / (lx1 - lx0) * (W - ml - mr);
    const y = v => mt + (1 - (Math.min(v, yMax) - yMin) / (yMax - yMin)) * (H - mt - mb);
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Plans by monthly cost and evening speed" });
    const step = niceStep(yMax - yMin, 5);
    for (let v = Math.ceil(yMin / step) * step; v <= yMax + 1e-9; v += step) {
      svg.append(sv("line", { x1: ml, x2: W - mr, y1: y(v), y2: y(v), class: "gridline" }));
      const t = sv("text", { x: ml - 6, y: y(v) + 3.5, "text-anchor": "end" }); t.textContent = "$" + fmtNum(v); svg.append(t);
    }
    svg.append(sv("line", { x1: ml, x2: W - mr, y1: H - mb, y2: H - mb, class: "baseline" }));
    for (const s of [12, 25, 50, 100, 250, 500, 1000, 2000]) {
      if (Math.log10(s) < lx0 || Math.log10(s) > lx1) continue;
      svg.append(sv("line", { x1: x(s), x2: x(s), y1: H - mb, y2: H - mb + 4, class: "baseline" }));
      const t = sv("text", { x: x(s), y: H - mb + 15, "text-anchor": "middle" }); t.textContent = fmtNum(s); svg.append(t);
    }
    const xl = sv("text", { x: W - mr, y: H - 3, "text-anchor": "end" }); xl.textContent = "Typical evening download, Mbps (log scale) →"; svg.append(xl);
    const yl = sv("text", { x: ml, y: mt - 2, "text-anchor": "start", class: "ink" });
    // need line
    const needAt = M.N.minTier ? 0.8 * M.N.minTier : M.N.down;
    if (needAt > 0 && Math.log10(needAt) > lx0 && Math.log10(needAt) < lx1) {
      svg.append(sv("line", { x1: x(needAt), x2: x(needAt), y1: mt, y2: H - mb, class: "need" }));
      const t = sv("text", { x: x(needAt) + 4, y: mt + 10, class: "lbl" }); t.textContent = M.N.minTier ? `NBN ${M.N.minTier}+` : `You need ${fmtNum(needAt)}`; svg.append(t);
    }
    yl.textContent = ""; svg.append(yl);
    // frontier
    const fr = M.front.filter(f => f.speed > 0);
    if (fr.length > 1) svg.append(sv("path", { class: "frontier", d: fr.map((f, i) => `${i ? "L" : "M"}${x(f.speed)},${y(f.cost)}`).join("") }));
    // points: faded first, then fitting, then frontier, then selected
    const order = pts.slice().sort((a, b) => (a.m.ok - b.m.ok) || (M.frontIds.has(a.p.id) - M.frontIds.has(b.p.id)));
    const placed = [];
    for (const r of order) {
      const cx = x(r.speed), cy = y(r.c.perMonth), col = (KINDS[r.p.kind] || KINDS.nbn).color;
      const attrs = r.p.verified
        ? { fill: col, stroke: "var(--surface)", "stroke-width": 1 }
        : { fill: "var(--surface)", stroke: col, "stroke-width": 1.75 };
      const c = sv("circle", { cx, cy, r: 4.5, ...attrs, class: "pt" + (r.m.ok ? "" : " faded") });
      svg.append(c);
      placed.push({ r, cx, cy });
    }
    // direct labels on fitting frontier plans (skip any that would collide)
    const boxes = [];
    for (const f of fr) {
      if (!f.r.m.ok) continue;
      const cx = x(f.speed), cy = y(f.cost), txt = provName(f.r.p.provider);
      const w = txt.length * 6.2, bx = cx + 8 + w > W - mr ? cx - 8 - w : cx + 8, by = cy - 6;
      if (boxes.some(b => bx < b.x + b.w && bx + w > b.x && by - 9 < b.y && by + 3 > b.y - 12)) continue;
      boxes.push({ x: bx, y: by, w });
      const t = sv("text", { x: bx, y: by, class: "lbl" }); t.textContent = txt; svg.append(t);
    }
    if (M.sel && M.sel.speed > 0) svg.append(sv("circle", { cx: x(M.sel.speed), cy: y(M.sel.c.perMonth), r: 8, class: "sel-ring" }));
    const hov = sv("circle", { r: 7.5, class: "hov-ring", cx: 0, cy: 0, visibility: "hidden" }); svg.append(hov);
    const overlay = sv("rect", { x: ml, y: mt, width: W - ml - mr, height: H - mt - mb, fill: "transparent" });
    const nearest = ev => {
      const rect = svg.getBoundingClientRect(), k = W / rect.width;
      const mx = (ev.clientX - rect.left) * k, my = (ev.clientY - rect.top) * k;
      let best = null, bd = 16 * k;
      for (const q of placed) { const d = Math.hypot(q.cx - mx, q.cy - my); if (d < bd) { bd = d; best = q; } }
      return best;
    };
    overlay.addEventListener("mousemove", ev => {
      const q = nearest(ev);
      if (!q) { hideTip(); hov.setAttribute("visibility", "hidden"); overlay.style.cursor = "default"; return; }
      overlay.style.cursor = "pointer";
      hov.setAttribute("cx", q.cx); hov.setAttribute("cy", q.cy); hov.setAttribute("visibility", "visible");
      const p = q.r.p;
      showTip(ev, `<div class="t-h">${esc(provName(p.provider))} · ${esc(p.name)}</div>
        <div class="t-r"><span>${esc(kindLine(p))}</span><span>${esc(speedText(p))}</span></div>
        <div class="t-r"><span>Average over ${horizon()}</span><span>${money(q.r.c.perMonth)}/month</span></div>
        ${p.promo ? `<div class="t-r"><span>Intro offer${p.promo.requires ? ` (with ${esc(p.promo.requires)})` : ""}</span><span>${price(p.promo.price)} × ${p.promo.months}, then ${price(p.price)}</span></div>` : `<div class="t-r"><span>Price</span><span>${price(p.price)}/month</span></div>`}
        ${q.r.m.ok ? "" : `<div class="small">${esc(q.r.m.reasons[0])}</div>`}
        ${p.verified ? "" : `<div class="small">Price not yet checked with the provider</div>`}`);
    });
    overlay.addEventListener("mouseleave", () => { hideTip(); hov.setAttribute("visibility", "hidden"); });
    overlay.addEventListener("click", ev => { const q = nearest(ev); if (q) select_(q.r.p.id, true); });
    svg.append(overlay);
    box.append(svg);
    const kinds = [...new Set(pts.map(r => r.p.kind))];
    $("#scatter-legend").innerHTML = (kinds.length > 1 ? kinds.map(k => `<span><i class="dot" style="background:${KINDS[k].color}"></i>${esc(KINDS[k].label)}</span>`).join("") : "")
      + `<span><i class="dot hollow"></i>Hollow: price not yet checked with the provider</span><span><i class="line" style="background:var(--ink-2)"></i>Best value</span>`;
    $("#scatter-table").innerHTML = `<div class="tv-scroll"><table><tr><th>Plan</th><th>Evening speed</th><th>Average per month</th><th>Fits</th></tr>` +
      fr.map(f => `<tr><td>${esc(provName(f.r.p.provider))} · ${esc(f.r.p.name)}</td><td>${esc(speedText(f.r.p))}</td><td>${money(f.cost)}</td><td>${f.r.m.ok ? "Yes" : "No"}</td></tr>`).join("") + `</table></div>`;
  }

  /* ------------------------------------------------------------------ ranked table */
  function rankList() {
    let list = M.fits.slice();
    if (S.ui.sort === "speed") list.sort((a, b) => b.speed - a.speed || a.c.total - b.c.total);
    else list.sort((a, b) => a.c.total - b.c.total || b.speed - a.speed);
    if (S.ui.bestPer) { const seen = new Set(); list = list.filter(r => !seen.has(r.p.provider) && seen.add(r.p.provider)); }
    return list;
  }
  function renderRank() {
    const list = rankList(), shown = list.slice(0, S.ui.shown), tbl = $("#rank");
    const ex = [];
    if (M.excluded.slow) ex.push(`${M.excluded.slow} too slow for your settings`);
    if (M.excluded.tech) ex.push(`${M.excluded.tech} not available on your connection or switched off`);
    $("#rank-sub").textContent = `${list.length} ${S.ui.bestPer ? "providers" : "plans"} fit. Total cost over ${horizon()}${S.cost.reswitch ? ", switching again each time an intro offer ends" : ", staying put after any intro offer"}.` + (ex.length ? ` Not shown: ${ex.join(", ")}.` : "");
    const maxT = Math.max(...shown.map(r => r.c.total), 1);
    tbl.innerHTML = `<thead><tr><th class="rk">#</th><th>Plan</th><th class="r">Evening speed</th><th class="r">Intro offer</th><th class="r">Then</th><th class="r">Upfront</th><th class="r">Total</th><th class="bar-cell"></th></tr></thead><tbody></tbody>`;
    const tb = tbl.tBodies[0];
    shown.forEach((r, i) => {
      const p = r.p, up = r.stay.parts.setup + r.stay.parts.modem;
      const tr = h("tr", { class: M.sel && p.id === M.sel.p.id ? "sel" : "", tabindex: 0, html: `
        <td class="rk">${i + 1}</td>
        <td><div class="pn">${esc(p.name)}</div><div class="pr">${esc(provName(p.provider))} · ${esc(kindLine(p))}${p.verified ? "" : ' · <span class="warn-t">not yet checked</span>'}</div></td>
        <td class="r">${p.down != null ? fmtNum(p.down) : "–"}<span class="pr">${p.up != null ? " / " + fmtNum(p.up) : ""}</span></td>
        <td class="r">${p.promo ? `${price(p.promo.price)} <span class="pr">× ${p.promo.months}${p.promo.requires ? ` with ${esc(p.promo.requires)}` : ""}</span>` : '<span class="pr">–</span>'}</td>
        <td class="r">${price(p.price)}</td>
        <td class="r">${up ? money(up) : '<span class="pr">$0</span>'}</td>
        <td class="r"><b>${money(r.c.total)}</b></td>
        <td class="bar-cell"><div class="bar" style="width:${(r.c.total / maxT * 100).toFixed(1)}%"></div></td>` });
      const go = () => select_(p.id, true);
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
      tb.append(tr);
    });
    const more = $("#rank-more");
    more.hidden = list.length <= S.ui.shown;
    more.textContent = `Show more (${list.length - S.ui.shown} left)`;
  }

  function select_(id, scroll) {
    S.ui.sel = id; save();
    M.sel = M.byId.get(id) || M.sel;
    renderTiles(); renderPlanCard(); renderScatter(); renderRank();
    if (scroll) {
      const c = $("#plan-card"), r = c.getBoundingClientRect();
      if (r.top < 0 || r.top > innerHeight * 0.6) c.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  /* ------------------------------------------------------------------ notes, footer */
  function renderNotes() {
    const m = D.meta;
    const src = m.sources.map(s => `<tr><td>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}</td>
      <td>${s.status === "ok" ? "Up to date" : "Using the last good copy"}</td><td class="r">${s.records.internet}</td><td>${s.fetched ? fmtDate(s.fetched) : "–"}</td></tr>`).join("");
    $("#notes").innerHTML = `
      <p>Each plan is costed over the period you pick: intro-offer months at the intro price, the rest at the ongoing price, plus any setup fee and the modem or hardware you'd need. "Average per month" is that total divided by the number of months.</p>
      <h3>Speeds</h3>
      <p>Speeds are each provider's <b>typical evening speed</b> (7–11pm), the figure Australian providers publish for the busiest time of day. Your household's need adds up the streams, calls and games likely to run at once, with ${Math.round((E.HEADROOM - 1) * 100)}% headroom. NBN plans of 250 Mbps and above work only on FTTP and HFC connections; if you're not sure of yours, those plans are flagged rather than hidden.</p>
      <h3>Switching again</h3>
      <p>Most intro offers are for new customers and last 6 months. With "switch again" on, the cost assumes that when each offer ends you move to the cheapest new-customer offer of the same speed or faster from a provider you haven't used. It's a real saving, but it means changing provider a couple of times a year.</p>
      <h3>5G home internet and Starlink</h3>
      <p>5G home internet runs over a mobile network, so whether you can get it, and how fast it is, depends on your address. Starlink works almost anywhere but costs more and needs its own dish. Both need the provider's hardware, which is always counted.</p>
      <h3>Where the data comes from</h3>
      <div class="table-wrap"><table class="src"><tr><th>Source</th><th>Status</th><th class="r">Plans</th><th>Fetched</th></tr>${src}</table></div>
      <p>${m.verified.internet} of ${m.counts.internet} plans come straight from the provider's own published plan data; the rest come from Bill Hero's open data and are marked "not yet checked". Prices refresh every night. Always check the provider's Critical Information Summary before you sign up: offers change often and some have conditions.</p>
      <p>${esc([...new Set(m.sources.map(s => s.attribution).filter(Boolean))].join(" · "))}</p>
      <p>Comparing electricity and gas too? <a href="${ENERGY_SITE}">Melbourne Energy Compare</a> does the same for Victorian energy plans.</p>`;
    $("#data-date").innerHTML = `Prices checked <b>${esc(fmtDate(m.built_date_aest || m.built))}</b>`;
    $("#foot").innerHTML = `${esc([...new Set(m.sources.map(s => s.attribution).filter(Boolean))].join(" · "))} · Prices checked ${esc(fmtDate(m.built_date_aest || m.built))} · Not financial advice: check the plan's details with the provider before you switch. · <a href="${ENERGY_SITE}">Melbourne Energy Compare</a>`;
  }

  /* ------------------------------------------------------------------ boot */
  function boot() {
    buildInputs();
    const sortBox = $("#rank-sort");
    for (const [v, t] of [["cost", "Cheapest"], ["speed", "Fastest"]]) {
      const b = h("button", { type: "button", onclick: () => { S.ui.sort = v; S.ui.shown = 25; save(); upd(); renderRank(); } }, t);
      b._v = v; sortBox.append(b);
    }
    const upd = () => { for (const b of sortBox.children) b.setAttribute("aria-pressed", String(b._v === S.ui.sort)); };
    upd();
    const bp = $("#best-per-provider");
    bp.checked = S.ui.bestPer;
    bp.addEventListener("change", () => { S.ui.bestPer = bp.checked; S.ui.shown = 25; save(); renderRank(); });
    $("#rank-more").addEventListener("click", () => { S.ui.shown += 25; renderRank(); });
    renderNotes();
    updateInputs();
    recompute();
    window.addEventListener("scroll", hideTip, { passive: true });
    let rz = 0, lastW = innerWidth;
    window.addEventListener("resize", () => {
      if (innerWidth === lastW) return; lastW = innerWidth;
      clearTimeout(rz); rz = setTimeout(() => { if (M) { renderScatter(); if (M.sel) renderMonth(M.sel); } }, 150);
    });
  }
  boot();
})();

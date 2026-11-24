/* Australian Telco Compare: page logic (inputs, three result tabs: home internet, mobile lines,
 * and the whole household with bundles). */
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
  const MAX_LINES = 8;
  const DATA_STEPS = [1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200, 300];
  const LINE_STYLES = [["any", "Any"], ["short", "No long expiry"], ["postpaid", "Monthly bill"]];
  const COUNTRIES = [["BD", "Bangladesh"], ["CA", "Canada"], ["CN", "China"], ["FJ", "Fiji"], ["FR", "France"], ["DE", "Germany"],
    ["GR", "Greece"], ["HK", "Hong Kong"], ["IN", "India"], ["ID", "Indonesia"], ["IE", "Ireland"], ["IT", "Italy"], ["JP", "Japan"],
    ["LB", "Lebanon"], ["MY", "Malaysia"], ["NP", "Nepal"], ["NL", "Netherlands"], ["NZ", "New Zealand"], ["PK", "Pakistan"],
    ["PH", "Philippines"], ["SG", "Singapore"], ["ZA", "South Africa"], ["KR", "South Korea"], ["ES", "Spain"], ["LK", "Sri Lanka"],
    ["TW", "Taiwan"], ["TH", "Thailand"], ["GB", "United Kingdom"], ["US", "United States"], ["VN", "Vietnam"]];
  const countryName = c => (COUNTRIES.find(x => x[0] === c) || [c, c])[1];
  const TABS = ["internet", "mobile", "household"];
  function newLine(gb) { return { name: "", dataGB: gb || 10, nets: [], intl: [], style: "any", phone: newPhone() }; }
  function newPhone() { return { want: false, handset: "", storage: 0, term: 24, tradeIn: false }; }
  const CAT = E.handsetCatalogue(D.phones || []);
  const storageText = g => g >= 1024 ? `${g / 1024} TB` : `${g} GB`;

  /* Energy retailer: read from Melbourne Energy Compare's saved settings when both sites share a
   * browser origin (plasky.github.io). Its plan ids start with the retailer's CDR brand code. */
  const ENERGY_OPTIONS = [["auto", "From Melbourne Energy Compare"], ["none", "Another retailer, or not sure"],
    ["agl", "AGL"], ["origin-broadband", "Origin"], ["dodo", "Dodo"]];
  const ENERGY_DETECTED = (function () {
    try {
      const st = JSON.parse(localStorage.getItem("mec-state-v1") || "null");
      const ids = st && st.ui ? [st.ui.selE, st.ui.selG].filter(Boolean) : [];
      for (const id of ids) {
        if (/^AG/.test(id)) return { found: true, provider: "agl" };
        if (/^OR/.test(id)) return { found: true, provider: "origin-broadband" };
        if (/^DOD/.test(id)) return { found: true, provider: "dodo" };
      }
      return { found: ids.length > 0, provider: null };
    } catch (e) { return { found: false, provider: null }; }
  })();

  /* ------------------------------------------------------------------ state */
  const DEFAULTS = {
    conn: { tech: "unknown", fiveG: true, nets: ["telstra", "optus", "vodafone"], starlink: false, privateNet: false },
    use: { people: 4, uhd: 1, hd: 2, calls: 1, gamers: 1, uploadGB: 0, uploadHours: 6 },
    speed: { pick: 0 },     // 0 = from usage; otherwise the NBN tier picked
    cost: { months: 12, reswitch: false, needModem: false, modemPrice: 150, credits: false, bundles: false, unverified: true },
    current: { price: 0, mobile: 0 },
    mobile: { count: 4, lines: [newLine(30), newLine(20), newLine(10), newLine(5), newLine(10), newLine(10), newLine(10), newLine(10)] },
    energy: { retailer: "auto" },
    ui: { tab: "internet", sel: null, bestPer: true, sort: "cost", shown: 25, line: 0, mBestPer: true, mShown: 15, pShown: 15 },
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
    const savedLines = saved && saved.mobile && Array.isArray(saved.mobile.lines) ? saved.mobile.lines : [];
    st.mobile.lines = DEFAULTS.mobile.lines.map((d, i) => {
      const L = merge(clone(d), savedLines[i] || {});
      L.nets = Array.isArray(L.nets) ? L.nets.filter(n => NETS.some(x => x[0] === n)) : [];
      L.intl = Array.isArray(L.intl) ? L.intl.filter(c => typeof c === "string" && /^[A-Z]{2}$/.test(c)) : [];
      if (!LINE_STYLES.some(x => x[0] === L.style)) L.style = "any";
      if (!(L.dataGB > 0)) L.dataGB = 10;
      L.phone = merge(newPhone(), L.phone || {});
      if (![12, 24, 36].includes(L.phone.term)) L.phone.term = 24;
      const c = CAT.find(x => x.handset === L.phone.handset);
      if (!c) { L.phone.handset = ""; L.phone.want = false; }
      else if (!c.storages.includes(L.phone.storage)) L.phone.storage = c.storages[0];
      return L;
    });
    st.mobile.count = Number.isInteger(st.mobile.count) ? Math.max(0, Math.min(MAX_LINES, st.mobile.count)) : DEFAULTS.mobile.count;
    if (!ENERGY_OPTIONS.some(x => x[0] === st.energy.retailer)) st.energy.retailer = "auto";
    if (!TABS.includes(st.ui.tab)) st.ui.tab = "internet";
    st.ui.shown = 25; st.ui.mShown = 15; st.ui.pShown = 15;
    st.ui.line = Math.max(0, Math.min(st.mobile.count - 1, st.ui.line | 0));
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
  const energyProvider = () => S.energy.retailer === "auto" ? ENERGY_DETECTED.provider
    : S.energy.retailer === "none" ? null : S.energy.retailer;
  const costOpts = () => ({
    months: S.cost.months, modemPrice: S.cost.needModem ? S.cost.modemPrice : 0, credits: S.cost.credits,
    bundled: S.cost.bundles, tech: S.conn.tech, avail: avail(),
  });
  // Per plan: "count bundle discounts" assumes every bundle; otherwise only the energy bundle of
  // the retailer you're actually with.
  const optsFor = (p, o) => Object.assign({}, o, { bundled: S.cost.bundles ? true : (energyProvider() && p.provider === energyProvider() ? ["energy"] : []) });
  const lineLabel = i => (S.mobile.lines[i].name || "").trim() || `Line ${i + 1}`;
  const activeLines = () => S.mobile.lines.slice(0, S.mobile.count);
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

  function lineName(i) {
    const inp = h("input", { class: "txt", type: "text", maxlength: 24, placeholder: `Line ${i + 1}`, "aria-label": `Name for line ${i + 1}` });
    inp.addEventListener("input", () => { S.mobile.lines[i].name = inp.value; changed(); });
    fields.push({ update() { if (document.activeElement !== inp) inp.value = S.mobile.lines[i].name || ""; } });
    return inp;
  }
  function dataSlider(i) {
    const out = h("output");
    const inp = h("input", { type: "range", min: 0, max: DATA_STEPS.length - 1, step: 1, "aria-label": `Data a month for line ${i + 1}` });
    inp.addEventListener("input", () => { S.mobile.lines[i].dataGB = DATA_STEPS[+inp.value]; upd(); changed(); });
    function upd() {
      const v = S.mobile.lines[i].dataGB;
      let k = DATA_STEPS.findIndex(x => x >= v); if (k < 0) k = DATA_STEPS.length - 1;
      inp.value = k; out.textContent = `${v} GB a month`; inp.setAttribute("aria-valuetext", out.textContent); sliderPct(inp);
    }
    fields.push({ update: upd });
    return h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, "Data"), out), inp);
  }
  function lineNets(i) {
    const box = h("div", { class: "checks cols3" });
    for (const [id, name] of NETS) {
      const inp = h("input", { type: "checkbox" });
      inp.addEventListener("change", () => {
        const L = S.mobile.lines[i], set = new Set(L.nets);
        inp.checked ? set.add(id) : set.delete(id);
        L.nets = NETS.map(n => n[0]).filter(n => set.has(n)); changed();
      });
      fields.push({ update() { inp.checked = S.mobile.lines[i].nets.includes(id); } });
      box.append(h("label", { class: "check" }, inp, name));
    }
    return h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, "Networks with good coverage for you")), box,
      note(() => S.mobile.lines[i].nets.length ? "" : "None ticked: any network."));
  }
  function countryPicker(i) {
    const chips = h("div", { class: "chips" });
    const sel = h("select", { "aria-label": `Add a country line ${i + 1} calls` },
      h("option", { value: "" }, "Add a country…"), COUNTRIES.map(([c, n]) => h("option", { value: c }, n)));
    sel.addEventListener("change", () => {
      const L = S.mobile.lines[i];
      if (sel.value && !L.intl.includes(sel.value)) L.intl = [...L.intl, sel.value];
      sel.value = ""; changed();
    });
    fields.push({ update() {
      const L = S.mobile.lines[i];
      chips.innerHTML = "";
      for (const c of L.intl) chips.append(h("span", { class: "chip" }, countryName(c),
        h("button", { type: "button", class: "x", "aria-label": `Remove ${countryName(c)}`, onclick: () => { L.intl = L.intl.filter(x => x !== c); changed(); } }, "×")));
    } });
    return h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, "Included international calls to")), chips, sel);
  }
  function phoneSection(i) {
    const ph = () => S.mobile.lines[i].phone;
    if (!CAT.length) return h("div", { class: "hint" }, "Phone prices aren't in the data yet.");
    const want = h("input", { type: "checkbox" });
    want.addEventListener("change", () => {
      const p = ph(); p.want = want.checked;
      if (p.want && !p.handset) { p.handset = CAT[0].handset; p.storage = CAT[0].storages[0]; }
      changed();
    });
    fields.push({ update() { want.checked = !!ph().want; } });
    const hs = h("select", { "aria-label": `Phone for line ${i + 1}` });
    const brands = [...new Set(CAT.map(c => c.brand))];
    for (const b of brands) hs.append(h("optgroup", { label: b }, CAT.filter(c => c.brand === b).map(c => h("option", { value: c.handset }, c.model))));
    hs.addEventListener("change", () => {
      const p = ph(), c = CAT.find(x => x.handset === hs.value);
      p.handset = hs.value; p.storage = c ? c.storages[0] : 0; changed();
    });
    const st = h("select", { "aria-label": `Storage for line ${i + 1}` });
    st.addEventListener("change", () => { ph().storage = +st.value; changed(); });
    fields.push({ update() {
      const p = ph(), c = CAT.find(x => x.handset === p.handset);
      if (p.handset) hs.value = p.handset;
      const key = c ? c.storages.join(",") : "";
      if (st.dataset.k !== key) {
        st.innerHTML = "";
        for (const g of c ? c.storages : []) st.append(h("option", { value: g }, storageText(g)));
        st.dataset.k = key;
      }
      st.value = String(p.storage);
    } });
    return h("div", { class: "sub-group" },
      h("div", { class: "field" }, h("label", { class: "toggle" }, want, h("span", { class: "knob" }), h("span", {}, "New phone with this line"))),
      showIf(h("div", { class: "sub-group-body" },
        h("div", { class: "row2" },
          h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, "Phone")), hs),
          h("div", { class: "field" }, h("div", { class: "lab" }, h("span", {}, "Storage")), st)),
        seg(`mobile.lines.${i}.phone.term`, "Pay it off over", [[12, "12 months"], [24, "24 months"], [36, "36 months"]]),
        toggle(`mobile.lines.${i}.phone.tradeIn`, "I have a phone to trade in", "Counts carrier trade-in bonuses. Your old phone's own trade-in value comes on top of any option.")),
        () => ph().want));
  }

  function lineRow(i) {
    const remove = h("button", { type: "button", class: "btn sm", "aria-label": `Remove line ${i + 1}`, onclick: () => {
      S.mobile.lines.splice(i, 1); S.mobile.lines.push(newLine(10));
      S.mobile.count = Math.max(0, S.mobile.count - 1);
      S.ui.line = Math.max(0, Math.min(S.ui.line, S.mobile.count - 1)); changed();
    } }, "Remove");
    return showIf(h("div", { class: "list-row" },
      h("div", { class: "row-head" }, lineName(i), remove),
      dataSlider(i), lineNets(i),
      seg(`mobile.lines.${i}.style`, "Plan type", LINE_STYLES),
      countryPicker(i), phoneSection(i)), () => i < S.mobile.count);
  }
  function addLineButton() {
    const b = h("button", { type: "button", class: "btn add", onclick: () => { S.mobile.lines[S.mobile.count] = newLine(10); S.mobile.count++; changed(); } });
    fields.push({ update() { b.textContent = S.mobile.count ? "+ Add another line" : "+ Add a mobile line"; b.hidden = S.mobile.count >= MAX_LINES; } });
    return b;
  }
  function energyNote() {
    if (S.energy.retailer !== "auto") return "Unlocks energy + internet bundles such as AGL's $15 a month off.";
    if (!ENERGY_DETECTED.found) return "No Melbourne Energy Compare settings in this browser. Pick your retailer if it's listed.";
    return ENERGY_DETECTED.provider ? `Your saved energy plan is with ${provName(ENERGY_DETECTED.provider)}.`
      : "Your saved energy plan's retailer doesn't offer internet bundles.";
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
    { id: "lines", title: "Mobile lines", open: false,
      sum: () => S.mobile.count ? `${S.mobile.count} line${S.mobile.count > 1 ? "s" : ""} · ${activeLines().reduce((a, L) => a + L.dataGB, 0)} GB` : "None",
      body: () => [
        h("div", { class: "hint" }, "One per phone or tablet SIM. Check each one's monthly data use in its app or on the bill, then add a bit."),
        ...Array.from({ length: MAX_LINES }, (_, i) => lineRow(i)),
        addLineButton(),
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
        toggle("cost.bundles", "On the Home internet tab, assume every bundle", "Counts discounts for also taking the provider's mobile or energy. The Household tab works bundles out for real."),
        select("energy.retailer", "Your electricity or gas retailer", ENERGY_OPTIONS, note(energyNote)),
        toggle("cost.unverified", "Include plans not yet checked with the provider",
          "These come from Bill Hero's open data and sometimes show an intro price as the ongoing price."),
      ] },
    { id: "current", title: "What you pay now", open: false,
      sum: () => (S.current.price || S.current.mobile) ? price(S.current.price + S.current.mobile) + "/month" : "Not set",
      body: () => [
        slider("current.price", "Your internet bill each month", 0, 250, 1, v => v ? "$" + v : "Not set", "Shows how much switching would save."),
        slider("current.mobile", "Your mobile bills each month, all lines", 0, 500, 5, v => v ? "$" + v : "Not set"),
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
      const op = optsFor(r.p, o);
      r.stay = E.internetCost(r.p, op);
      r.chase = r.m.ok && r.p.promo ? E.reswitchCost(r.p, fitPlans, N, op) : null;
      r.c = S.cost.reswitch && r.chase ? r.chase : r.stay;
      r.speed = speedOf(r.p);
    }
    const byCost = fits.slice().sort((a, b) => a.c.total - b.c.total || b.speed - a.speed);
    const front = E.frontier(shown.map(r => ({ r, cost: r.c.perMonth, speed: r.speed })));
    const frontIds = new Set(front.map(x => x.r.p.id));
    const excluded = { slow: rows.filter(r => r.t.ok && !r.m.ok).length, tech: rows.filter(r => !r.t.ok).length };
    return { N, A, rows, shown, fits, byCost, front, frontIds, excluded, byId: new Map(shown.map(r => [r.p.id, r])) };
  }

  function buildMobile() {
    const months = S.cost.months, pool = D.mobile.filter(p => S.cost.unverified || p.verified);
    const lines = activeLines().map(L => ({ dataGB: L.dataGB, networks: L.nets, intl: L.intl, style: L.style }));
    const energy = energyProvider(), rules = D.bundles || {};
    const internetOpts = { modemPrice: S.cost.needModem ? S.cost.modemPrice : 0, credits: S.cost.credits };
    const hh = E.household({ internet: M.fits.map(r => r.p), lines, mobile: pool, rules, energy, months, internetOpts });
    const mo = E.household({ internet: [], lines, mobile: pool, rules, energy, months });
    return { lines, pool, hh, mo, energy };
  }

  function recompute() {
    M = buildModel();
    let sel = M.byId.get(S.ui.sel);
    if (!sel) { sel = M.byCost[0] || null; S.ui.sel = sel ? sel.p.id : null; }
    M.sel = sel;
    M.mob = buildMobile();
    renderReadout(); renderTiles(); renderMbar();
    renderPlanCard(); renderScatter(); renderRank();
    renderLines(); renderPhones(); renderMRank();
    renderSetup(); renderStack(); renderProviders();
  }

  function setTab(t, fromHash) {
    if (!TABS.includes(t)) t = "internet";
    S.ui.tab = t; save();
    for (const x of TABS) $("#tab-" + x).hidden = x !== t;
    for (const a of document.querySelectorAll("#tabs a")) a.setAttribute("aria-current", a.dataset.tab === t ? "page" : "false");
    if (t !== "internet") { const d = $('#inputs details[data-sec="lines"]'); if (d && !d.open && S.mobile.count) d.open = true; }
    if (!fromHash && location.hash !== "#" + t) history.replaceState(null, "", "#" + t);
    if (M) { renderTiles(); renderMbar(); if (t === "household") renderStack(); }
  }

  /* ------------------------------------------------------------------ readout + tiles */
  function renderReadout() {
    const n = M.N;
    const speedBit = n.minTier
      ? `<b>NBN ${n.minTier}</b> or faster`
      : `about <b>${fmtNum(n.down)} Mbps</b> down and <b>${fmtNum(n.up)} Mbps</b> up`;
    const L = activeLines();
    const mob = L.length ? `${L.length} mobile line${L.length > 1 ? "s" : ""}: ${L.map(x => x.dataGB + " GB").join(", ")} a month` : "No mobile lines";
    $("#readout").innerHTML = `<div>Your household needs ${speedBit} in the evening (7–11pm), when networks are busiest.</div>
      <div class="bench">${M.fits.length} of ${M.rows.length} internet plans fit · connection: ${esc(TECH_SHORT[S.conn.tech])}</div>
      <div class="bench mob">${esc(mob)}${M.mob && M.mob.energy ? ` · energy with ${esc(provName(M.mob.energy))}` : ""}</div>`;
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
    if (S.ui.tab === "mobile") return renderMobileTiles();
    if (S.ui.tab === "household") return renderHouseholdTiles();
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
    const el = $("#mbar");
    if (S.ui.tab !== "internet") {
      const sol = S.ui.tab === "mobile" ? M.mob.mo.independent : M.mob.hh.best;
      if (!sol || !isFinite(sol.total)) { el.hidden = true; return; }
      el.hidden = false;
      el.innerHTML = `<span>${S.ui.tab === "mobile" ? "All lines" : "Everything"}: <b>${money(sol.total / S.cost.months)}/month</b></span><span>over ${S.cost.months} months</span>`;
      return;
    }
    const best = M.byCost[0];
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

  /* ------------------------------------------------------------------ mobile tab */
  const periodText = p => p.period_days === 30 || p.period_days === 31 ? "month" : `${p.period_days} days`;
  const dataText = p => p.data_gb === -1 ? "Unlimited" : p.data_gb == null ? "Not published" : `${fmtNum(p.data_gb, p.data_gb % 1 ? 1 : 0)} GB`;
  function planLine(p) {
    const bits = [provName(p.provider)];
    if (p.network) bits.push(netName(p.network) + " network");
    bits.push(p.type === "prepaid" ? "prepaid" : "monthly bill");
    return bits.join(" · ");
  }
  function lineNeed(i) {
    const L = S.mobile.lines[i], bits = [`${L.dataGB} GB`];
    bits.push(L.nets.length ? L.nets.map(netName).join(" or ") : "any network");
    if (L.style !== "any") bits.push(L.style === "short" ? "no long expiry" : "monthly bill");
    if (L.intl.length) bits.push("calls to " + L.intl.map(countryName).join(", "));
    return bits.join(" · ");
  }
  function sumLines(sol) { return sol.lines.reduce((a, x) => a + (x ? x.c.total : Infinity), 0); }

  function renderMobileTiles() {
    const el = $("#tiles"); el.innerHTML = "";
    const mo = M.mob.mo, n = M.mob.lines.length, H = horizon();
    if (!n) { el.append(tile("Mobile", "–", "No mobile lines yet", "Add your lines in Mobile lines on the left.")); return; }
    const ind = mo.independent;
    if (!isFinite(ind.total)) {
      const bad = mo.lines.map((o, i) => o.length ? null : lineLabel(i)).filter(Boolean);
      el.append(tile("Cheapest for every line", "–", `No plan fits ${bad.join(", ")}`, "Try less data, another network or fewer countries."));
      return;
    }
    const provs = [...new Set(ind.lines.map(x => provName(x.p.provider)))];
    el.append(tile(`Cheapest for your ${n} line${n > 1 ? "s" : ""}`, `${money(ind.total)} <small>over ${H}</small>`,
      provs.length === 1 ? provs[0] : `${provs.length} providers: ${provs.join(", ")}`, `${money(ind.total / S.cost.months)}/month for all lines`, null));
    const one = mo.singles[0];
    if (one && n > 1) {
      el.append(tile("Everyone with one provider", `${money(one.total)} <small>over ${H}</small>`, provName(one.provider),
        one.total - ind.total > 0.5 ? `+${money((one.total - ind.total) / S.cost.months)}/month for one bill${one.discount.total ? `, after ${money(one.discount.total)} of multi-line discounts` : ""}` : "Same as mixing providers", null));
    } else if (n === 1) {
      const alt = mo.lines[0].find(x => x.p.provider !== ind.lines[0].p.provider);
      if (alt) el.append(tile("Runner-up", `${money(alt.c.total)} <small>over ${H}</small>`, `${provName(alt.p.provider)} · ${alt.p.name}`, planLine(alt.p), null));
    }
    if (S.current.mobile > 0) {
      const now = S.current.mobile * S.cost.months, save = now - ind.total;
      el.append(tile("Versus what you pay now", save > 0 ? `<b class="good">${money(save)}</b> <small>saved over ${H}</small>` : `${money(-save)} <small>more</small>`,
        "Cheapest plan for each line", `You pay ${money(now)} over ${H} at ${price(S.current.mobile)}/month`, null));
    } else {
      const tel = mo.lines.map(o => o.find(x => x.p.network === "telstra") || null);
      if (tel.every(Boolean)) {
        const t = tel.reduce((a, x) => a + x.c.total, 0);
        el.append(tile("Everyone on the Telstra network", `${money(t)} <small>over ${H}</small>`,
          [...new Set(tel.map(x => provName(x.p.provider)))].join(", "), `+${money(Math.max(0, t - ind.total) / S.cost.months)}/month for the widest coverage`, null));
      }
    }
  }

  function renderLines() {
    const card = $("#lines-card"), mo = M.mob.mo, n = M.mob.lines.length;
    if (!n) { card.innerHTML = `<h2>Your lines</h2><p class="empty">No mobile lines yet. Add them under Mobile lines on the left.</p>`; return; }
    if (S.ui.line >= n) S.ui.line = 0;
    const rows = mo.lines.map((o, i) => {
      const b = o[0];
      return `<tr data-i="${i}" class="${i === S.ui.line ? "sel" : ""}" tabindex="0">
        <td><div class="pn">${esc(lineLabel(i))}</div><div class="pr">${esc(lineNeed(i))}</div></td>
        ${b ? `<td><div class="pn">${esc(b.p.name)}</div><div class="pr">${esc(planLine(b.p))}${b.p.verified ? "" : ' · <span class="warn-t">not yet checked</span>'}</div></td>
        <td class="r">${esc(dataText(b.p))}<span class="pr"> / ${esc(periodText(b.p))}</span></td>
        <td class="r">${price(b.p.price)}<span class="pr"> / ${esc(periodText(b.p))}</span></td>
        <td class="r"><b>${money(b.c.total)}</b><div class="pr">${money(b.c.perMonth)}/month</div></td>`
        : `<td colspan="4" class="warn-t">No plan fits this line</td>`}</tr>`;
    }).join("");
    card.innerHTML = `<h2>Cheapest plan for each line</h2>
      <p class="card-sub">Each line costed over ${horizon()}, including intro offers. 28-day plans count 13 recharges a year. Click a line to see every plan that fits it.</p>
      <div class="table-wrap"><table class="rank lines"><thead><tr><th>Line</th><th>Cheapest plan</th><th class="r">Data</th><th class="r">Price</th><th class="r">Total</th></tr></thead><tbody>${rows}</tbody>
      <tfoot><tr><td colspan="4"><b>All lines</b></td><td class="r"><b>${isFinite(mo.independent.total) ? money(mo.independent.total) : "–"}</b></td></tr></tfoot></table></div>`;
    for (const tr of card.querySelectorAll("tbody tr")) {
      const go = () => { S.ui.line = +tr.dataset.i; S.ui.mShown = 15; save(); renderLines(); renderMRank(); };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
    }
  }

  function renderMRank() {
    const n = M.mob.lines.length, tbl = $("#mrank");
    if (!n) { $("#mrank-title").textContent = "Plans for this line"; $("#mrank-sub").textContent = ""; tbl.innerHTML = ""; $("#mrank-more").hidden = true; return; }
    const i = Math.min(S.ui.line, n - 1);
    let list = M.mob.mo.lines[i].slice();
    if (S.ui.mBestPer) { const seen = new Set(); list = list.filter(x => !seen.has(x.p.provider) && seen.add(x.p.provider)); }
    const shown = list.slice(0, S.ui.mShown);
    $("#mrank-title").textContent = `Plans for ${lineLabel(i)}`;
    const total = M.mob.pool.filter(p => !p.data_only).length;
    $("#mrank-sub").textContent = `${M.mob.mo.lines[i].length} of ${total} phone plans fit ${lineNeed(i)}. Total cost over ${horizon()}, cheapest first.`;
    const maxT = Math.max(...shown.map(x => x.c.total), 1);
    tbl.innerHTML = `<thead><tr><th class="rk">#</th><th>Plan</th><th class="r">Data</th><th class="r">Price</th><th class="r">Intro offer</th><th class="r">Total</th><th class="bar-cell"></th></tr></thead><tbody>` +
      shown.map((x, k) => { const p = x.p; return `<tr>
        <td class="rk">${k + 1}</td>
        <td><div class="pn">${esc(p.name)}</div><div class="pr">${esc(planLine(p))}${p.rollover ? " · data rollover" : ""}${p.verified ? "" : ' · <span class="warn-t">not yet checked</span>'}</div>${p.notes ? `<div class="pr">${esc(p.notes.length > 140 ? p.notes.slice(0, 137) + "…" : p.notes)}</div>` : ""}</td>
        <td class="r">${esc(dataText(p))}</td>
        <td class="r">${price(p.price)}<span class="pr"> / ${esc(periodText(p))}</span></td>
        <td class="r">${p.promo ? `${price(p.promo.price)} <span class="pr">× ${p.promo.periods}</span>` : '<span class="pr">–</span>'}</td>
        <td class="r"><b>${money(x.c.total)}</b><div class="pr">${money(x.c.perMonth)}/month</div></td>
        <td class="bar-cell"><div class="bar" style="width:${(x.c.total / maxT * 100).toFixed(1)}%"></div></td></tr>`; }).join("") + "</tbody>";
    for (const [k, tr] of [...tbl.tBodies[0].rows].entries()) {
      const p = shown[k].p;
      if (p.url) { tr.title = "Open the plan page"; tr.addEventListener("click", () => window.open(p.url, "_blank", "noopener")); }
    }
    const more = $("#mrank-more");
    more.hidden = list.length <= S.ui.mShown;
    more.textContent = `Show more (${list.length - S.ui.mShown} left)`;
  }

  /* ---- new phones */
  function phoneOptionLabel(x) {
    const L = x.listing;
    if (x.kind === "outright") return `Buy outright${L ? ` from ${esc(provName(L.provider))}` : ""} + ${esc(provName(x.plan.p.provider))} SIM-only`;
    return `${esc(provName(x.provider))} repayments, ${L.term} months at ${price(L.monthly)}`;
  }
  function renderPhones() {
    const card = $("#phones-card");
    if (!card) return;
    if (!CAT.length) { card.innerHTML = `<h2>New phones</h2><p class="empty">Phone prices aren't in the data yet.</p>`; return; }
    const want = activeLines().map((L, i) => ({ L, i })).filter(x => x.L.phone && x.L.phone.want && x.L.phone.handset);
    if (!want.length) {
      card.innerHTML = `<h2>New phones</h2><p class="card-sub">Getting a new phone? Switch on "New phone with this line" under Mobile lines to compare buying it outright plus a SIM-only plan with each carrier's repayment deal. ${CAT.length} phones from ${new Set((D.phones || []).map(x => x.provider)).size} sellers.</p>`;
      return;
    }
    let out = `<h2>New phones</h2><p class="card-sub">Each option counts the phone and a plan for that line over the repayment term, so outright and repayments compare like for like. Carrier deals use that carrier's cheapest plan that fits the line, after discounts and bill credits.</p>`;
    for (const { L, i } of want) {
      const c = CAT.find(x => x.handset === L.phone.handset);
      const line = { dataGB: L.dataGB, networks: L.nets, intl: L.intl, style: L.style };
      const opts = E.phoneOptions({ handset: L.phone.handset, storage: L.phone.storage, term: L.phone.term, line, phones: D.phones || [], mobile: M.mob.pool, tradeIn: L.phone.tradeIn });
      out += `<h3 class="ph-h">${esc(lineLabel(i))}: ${esc(c ? `${c.brand} ${c.model}` : L.phone.handset)} ${esc(storageText(L.phone.storage))}, over ${L.phone.term} months</h3>`;
      if (!opts.length) {
        out += `<p class="empty">No seller lists this phone in this size${c && c.terms.length && !c.terms.includes(L.phone.term) ? ` on ${L.phone.term}-month repayments (try ${c.terms.join(" or ")} months)` : ""}, or no plan fits the line.</p>`;
        continue;
      }
      const best = opts[0].total;
      out += `<div class="table-wrap"><table class="rank phones"><thead><tr><th>Option</th><th>Plan</th><th class="r">Phone</th><th class="r">Plan cost</th><th class="r">Total</th></tr></thead><tbody>` +
        opts.map((x, k) => {
          const L2 = x.listing, rw = x.rewards.map(r => `${esc(r.text)} −${money(r.amount)}`).join("; ");
          return `<tr class="${k === 0 ? "sel" : ""}"><td><div class="pn">${phoneOptionLabel(x)}</div>
              <div class="pr">${x.flags.map(esc).join(" · ")}${L2 && !L2.verified ? ' · <span class="warn-t">not yet checked</span>' : ""}${L2 && L2.url ? ` · <a href="${esc(L2.url)}" target="_blank" rel="noopener">details ↗</a>` : ""}</div>
              ${rw ? `<div class="pr">${rw}</div>` : ""}</td>
            <td><div>${esc(x.plan.p.name)}</div><div class="pr">${esc(planLine(x.plan.p))} · ${esc(dataText(x.plan.p))}</div></td>
            <td class="r">${money(x.device)}${x.device !== x.deviceGross ? `<div class="pr">of ${money(x.deviceGross)}</div>` : ""}</td>
            <td class="r">${money(x.plan.c.total)}</td>
            <td class="r"><b>${money(x.total)}</b><div class="pr">${money(x.perMonth)}/month${k ? ` · +${money(x.total - best)}` : " · cheapest"}</div></td></tr>`;
        }).join("") + `</tbody></table></div>`;
    }
    card.innerHTML = out;
  }

  /* ------------------------------------------------------------------ household tab */
  function solSummary(sol) {
    const bits = [];
    if (sol.internet) bits.push(`Internet: ${provName(sol.internet.p.provider)}`);
    const mp = [...new Set(sol.lines.filter(Boolean).map(x => provName(x.p.provider)))];
    if (mp.length) bits.push(`Mobile: ${mp.join(", ")}`);
    return bits.join(" · ");
  }
  function renderHouseholdTiles() {
    const el = $("#tiles"); el.innerHTML = "";
    const hh = M.mob.hh, H = horizon(), best = hh.best;
    if (!best || !isFinite(best.total)) {
      el.append(tile("Cheapest overall", "–", "Something doesn't fit", "Check the Home internet and Mobile tabs for what's missing."));
      return;
    }
    el.append(tile("Cheapest overall", `${money(best.total)} <small>over ${H}</small>`, solSummary(best),
      `${money(best.total / S.cost.months)}/month for everything`, null));
    const one = hh.singles[0];
    if (one) el.append(tile("Everything with one provider", `${money(one.total)} <small>over ${H}</small>`, provName(one.provider),
      one.total - best.total > 0.5 ? `+${money((one.total - best.total) / S.cost.months)}/month for one bill` : "Also the cheapest overall", null));
    else el.append(tile("Everything with one provider", "–", "No provider covers it all", "No single provider has a plan for every line plus your internet.", null));
    const now = (S.current.price + S.current.mobile) * S.cost.months;
    if (now > 0) {
      const save = now - best.total;
      el.append(tile("Versus what you pay now", save > 0 ? `<b class="good">${money(save)}</b> <small>saved over ${H}</small>` : `${money(-save)} <small>more</small>`,
        "Cheapest overall", `You pay ${money(now)} over ${H}`, null));
    } else {
      const gain = hh.independent.total - best.total;
      el.append(tile("What bundling is worth", gain > 0.5 ? `<b class="good">${money(gain)}</b> <small>over ${H}</small>` : "$0",
        gain > 0.5 ? `Taking more with ${provName(best.provider)}` : "Mixing providers is cheapest",
        gain > 0.5 ? "Versus the cheapest plans bought separately" : "No bundle beats the cheapest plans bought separately", null));
    }
  }

  function solRows(sol) {
    const rows = [];
    const lineSave = x => x.c.bundleSave || 0;
    if (sol.internet) {
      const p = sol.internet.p, bs = sol.internet.c.parts.bundleSave || 0;
      rows.push([`<b>Internet</b><small>${esc(provName(p.provider))} · ${esc(p.name)} · ${esc(kindLine(p))}${bs ? ` · includes ${money(bs)} bundle discount` : ""}${p.verified ? "" : ' · <span class="warn-t">price not yet checked</span>'}</small>`, sol.internet.c.total]);
    }
    sol.lines.forEach((x, i) => {
      if (!x) return;
      const s = lineSave(x);
      rows.push([`<b>${esc(lineLabel(i))}</b><small>${esc(provName(x.p.provider))} · ${esc(x.p.name)} · ${esc(dataText(x.p))} / ${esc(periodText(x.p))}${s ? ` · includes ${money(s)} bundle discount` : ""}${x.p.verified ? "" : ' · <span class="warn-t">price not yet checked</span>'}</small>`, x.c.total]);
    });
    for (const d of (sol.discount && sol.discount.items) || []) rows.push([`${esc(d.text)}`, -d.amount]);
    return rows;
  }
  function renderSetup() {
    const card = $("#setup-card"), hh = M.mob.hh, best = hh.best;
    if (!best || !isFinite(best.total)) {
      card.innerHTML = `<h2>Your cheapest setup</h2><p class="empty">No complete setup fits yet: check that every mobile line has a plan (Mobile tab) and that an internet plan fits (Home internet tab).</p>`;
      return;
    }
    const kv = solRows(best).map(([t, v]) => `<tr><td>${t}</td><td class="${v < 0 ? "neg" : ""}">${money(v)}</td></tr>`).join("");
    const one = hh.singles[0];
    const alt = one && one !== best ? `<p class="alt">Everything with <b>${esc(provName(one.provider))}</b> instead: ${money(one.total)} (${money((one.total - best.total) / S.cost.months)}/month more).</p>` : "";
    const why = best.provider
      ? `Taking ${best.internetWithP ? "your internet and " : ""}${best.lines.filter(x => x && x.onP).length} line${best.lines.filter(x => x && x.onP).length === 1 ? "" : "s"} with ${esc(provName(best.provider))} unlocks bundle discounts worth more than shopping around.`
      : "The cheapest plans bought separately beat every bundle on offer.";
    const phones = activeLines().some(L => L.phone && L.phone.want) ? " New phones aren't included here: see New phones on the Mobile tab." : "";
    card.innerHTML = `<h2>Your cheapest setup</h2>
      <p class="card-sub">${why} Total over ${horizon()}, staying on each plan after its intro offer.${phones}${M.mob.energy ? ` Your energy retailer (${esc(provName(M.mob.energy))}) is counted for energy bundles.` : ""}</p>
      <div class="setup"><table class="kv">${kv}<tr class="total"><td>Total over ${horizon()}</td><td>${money(best.total)}</td></tr>
      <tr><td>Per month on average</td><td>${money(best.total / S.cost.months)}</td></tr></table>${alt}</div>`;
  }

  function splitSol(sol) {
    let internet = sol.internet ? sol.internet.c.total : 0, mobile = sol.lines.reduce((a, x) => a + (x ? x.c.total : 0), 0);
    for (const d of (sol.discount && sol.discount.items) || []) { if (d.applies_to === "internet") internet -= d.amount; else mobile -= d.amount; }
    return { internet, mobile };
  }
  function renderStack() {
    const box = $("#stack"), hh = M.mob.hh;
    const rows = [];
    if (hh.best && isFinite(hh.best.total)) rows.push({ label: "Cheapest setup", ...splitSol(hh.best) });
    if (hh.singles[0] && hh.singles[0] !== hh.best) rows.push({ label: `All with ${provName(hh.singles[0].provider)}`, ...splitSol(hh.singles[0]) });
    if (S.current.price || S.current.mobile) rows.push({ label: "What you pay now", internet: S.current.price * S.cost.months, mobile: S.current.mobile * S.cost.months });
    $("#stack-sub").textContent = rows.length ? `Total over ${horizon()}, split into home internet and mobile.` : "";
    box.innerHTML = ""; $("#stack-legend").innerHTML = ""; $("#stack-table").innerHTML = "";
    if (!rows.length || $("#tab-household").hidden) return;
    const W = Math.max(300, box.clientWidth || 600), lw = Math.min(170, W * 0.32), barH = 20, gap = 16, mt = 4;
    const H = mt + rows.length * (barH + gap) + 16;
    const max = niceMax(Math.max(...rows.map(r => r.internet + r.mobile)) * 1.08);
    const x = v => lw + v / max * (W - lw - 60);
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Cost by service" });
    const cols = { internet: "var(--s1)", mobile: "var(--s2)" }, names = { internet: "Home internet", mobile: "Mobile" };
    rows.forEach((r, k) => {
      const y = mt + k * (barH + gap);
      const t = sv("text", { x: 0, y: y + barH / 2 + 4, class: "ink" }); t.textContent = r.label; svg.append(t);
      let x0 = lw;
      const segs = ["internet", "mobile"].filter(s => r[s] > 0.5);
      segs.forEach((s, j) => {
        const w = Math.max(1, x(x0 - lw + r[s]) - x0 - (j < segs.length - 1 ? 2 : 0));
        const last = j === segs.length - 1;
        const el = last ? sv("path", { d: roundedRight(x0, y, w, barH, 4), fill: cols[s], class: "seg-rect" })
          : sv("rect", { x: x0, y, width: w, height: barH, fill: cols[s], class: "seg-rect" });
        el.addEventListener("mousemove", ev => showTip(ev, `<div class="t-h">${esc(r.label)}</div><div class="t-r"><span><i style="background:${cols[s]}"></i>${names[s]}</span><span>${money(r[s])}</span></div><div class="t-r"><span>Total</span><span>${money(r.internet + r.mobile)}</span></div>`));
        el.addEventListener("mouseleave", hideTip);
        svg.append(el);
        x0 += w + (last ? 0 : 2);
      });
      const tl = sv("text", { x: x0 + 6, y: y + barH / 2 + 4, class: "ink" }); tl.textContent = money(r.internet + r.mobile); svg.append(tl);
    });
    box.append(svg);
    $("#stack-legend").innerHTML = ["internet", "mobile"].map(s => `<span><i style="background:${cols[s]}"></i>${names[s]}</span>`).join("");
    $("#stack-table").innerHTML = `<div class="tv-scroll"><table><tr><th></th><th>Home internet</th><th>Mobile</th><th>Total</th></tr>` +
      rows.map(r => `<tr><td>${esc(r.label)}</td><td>${money(r.internet)}</td><td>${money(r.mobile)}</td><td>${money(r.internet + r.mobile)}</td></tr>`).join("") + `</table></div>`;
  }
  function roundedRight(x, y, w, hgt, r) {
    r = Math.min(r, w / 2, hgt / 2);
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt - r}Q${x + w},${y + hgt} ${x + w - r},${y + hgt}H${x}Z`;
  }

  function renderProviders() {
    const hh = M.mob.hh, list = hh.byProvider, tbl = $("#prov");
    const bestT = hh.best && isFinite(hh.best.total) ? hh.best.total : null;
    $("#prov-sub").textContent = list.length
      ? `For each provider, the cheapest way to use it: its internet, some or all of your lines, or both, with everything else bought wherever it's cheapest. Total over ${horizon()}.`
      : "No provider deals to compare yet.";
    const shown = list.slice(0, S.ui.pShown);
    tbl.innerHTML = `<thead><tr><th class="rk">#</th><th>Provider</th><th>What you'd take with them</th><th class="r">Total</th><th class="r">vs cheapest</th></tr></thead><tbody>` +
      shown.map((sol, k) => {
        const onP = sol.lines.filter(x => x && x.onP).length;
        const what = [sol.internetWithP ? "Internet" : null, onP ? `${onP} of ${sol.lines.length} line${sol.lines.length > 1 ? "s" : ""}` : null].filter(Boolean).join(" + ");
        const disc = sol.discount.total + (sol.internetWithP && sol.internet ? sol.internet.c.parts.bundleSave || 0 : 0) + sol.lines.reduce((a, x) => a + (x && x.onP ? x.c.bundleSave || 0 : 0), 0);
        return `<tr><td class="rk">${k + 1}</td><td><div class="pn">${esc(provName(sol.provider))}</div>${sol.single ? '<div class="pr">Everything with them</div>' : ""}</td>
          <td>${esc(what)}${disc > 0.5 ? `<div class="pr">${money(disc)} in bundle discounts</div>` : ""}</td>
          <td class="r"><b>${money(sol.total)}</b></td><td class="r">${bestT != null ? (sol.total - bestT < 0.5 ? "Cheapest" : "+" + money(sol.total - bestT)) : "–"}</td></tr>`;
      }).join("") + "</tbody>";
    const more = $("#prov-more");
    more.hidden = list.length <= S.ui.pShown;
    more.textContent = `Show more (${list.length - S.ui.pShown} left)`;
  }

  /* ------------------------------------------------------------------ notes, footer */
  function renderNotes() {
    const m = D.meta;
    const src = m.sources.map(s => `<tr><td>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}</td>
      <td>${s.status === "ok" ? "Up to date" : "Using the last good copy"}</td><td class="r">${s.records.internet}</td><td class="r">${s.records.mobile}</td><td>${s.fetched ? fmtDate(s.fetched) : "–"}</td></tr>`).join("");
    $("#notes").innerHTML = `
      <p>Each plan is costed over the period you pick: intro-offer months at the intro price, the rest at the ongoing price, plus any setup fee and the modem or hardware you'd need. "Average per month" is that total divided by the number of months.</p>
      <h3>Speeds</h3>
      <p>Speeds are each provider's <b>typical evening speed</b> (7–11pm), the figure Australian providers publish for the busiest time of day. Your household's need adds up the streams, calls and games likely to run at once, with ${Math.round((E.HEADROOM - 1) * 100)}% headroom. NBN plans of 250 Mbps and above work only on FTTP and HFC connections; if you're not sure of yours, those plans are flagged rather than hidden.</p>
      <h3>Switching again</h3>
      <p>Most intro offers are for new customers and last 6 months. With "switch again" on, the cost assumes that when each offer ends you move to the cheapest new-customer offer of the same speed or faster from a provider you haven't used. It's a real saving, but it means changing provider a couple of times a year.</p>
      <h3>5G home internet and Starlink</h3>
      <p>5G home internet runs over a mobile network, so whether you can get it, and how fast it is, depends on your address. Starlink works almost anywhere but costs more and needs its own dish. Both need the provider's hardware, which is always counted.</p>
      <h3>Mobile</h3>
      <p>Each line is matched to plans with enough data each month, on a network you've ticked (any if none), with included calls to the countries you add. Recharges are counted as they fall: a 28-day plan is 13 recharges a year, a 365-day plan is one. Intro offers count for the recharges they cover.</p>
      <h3>New phones</h3>
      <p>For a line getting a new phone, each option counts the phone and a plan over the repayment term: buying outright (the lowest listed price) plus the cheapest SIM-only plan that fits, or a carrier's repayments plus its cheapest eligible plan that fits, minus the discounts and bill credits that apply. Leaving a repayment deal early means paying out the rest of the phone, so only take one if you'll stay. Trade-in bonuses count only if you say you have a phone to trade.</p>
      <h3>Household and bundles</h3>
      <p>The Household tab tries every way of splitting your lines between each provider and the cheapest plans elsewhere, with that provider's internet or the cheapest other internet. It counts bundle discounts only when their conditions are met: a mobile line with the same provider, its internet, or your energy retailer. Bundles assume you stay put, so promo-chasing is left out here.</p>
      <h3>Where the data comes from</h3>
      <div class="table-wrap"><table class="src"><tr><th>Source</th><th>Status</th><th class="r">Internet</th><th class="r">Mobile</th><th>Fetched</th></tr>${src}</table></div>
      <p>${m.verified.internet} of ${m.counts.internet} internet plans and ${m.verified.mobile} of ${m.counts.mobile} mobile plans come straight from the provider's own published plan data or were checked by hand; the rest come from Bill Hero's open data and are marked "not yet checked". Prices refresh every night. Always check the provider's Critical Information Summary before you sign up: offers change often and some have conditions.</p>
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
    const mb = $("#m-best-per");
    mb.checked = S.ui.mBestPer;
    mb.addEventListener("change", () => { S.ui.mBestPer = mb.checked; S.ui.mShown = 15; save(); renderMRank(); });
    $("#mrank-more").addEventListener("click", () => { S.ui.mShown += 15; renderMRank(); });
    $("#prov-more").addEventListener("click", () => { S.ui.pShown += 15; renderProviders(); });
    for (const a of document.querySelectorAll("#tabs a")) a.addEventListener("click", ev => { ev.preventDefault(); setTab(a.dataset.tab); });
    window.addEventListener("hashchange", () => setTab(location.hash.slice(1), true));
    const fromHash = location.hash.slice(1);
    setTab(TABS.includes(fromHash) ? fromHash : S.ui.tab, true);
    renderNotes();
    updateInputs();
    recompute();
    window.addEventListener("scroll", hideTip, { passive: true });
    let rz = 0, lastW = innerWidth;
    window.addEventListener("resize", () => {
      if (innerWidth === lastW) return; lastW = innerWidth;
      clearTimeout(rz); rz = setTimeout(() => { if (M) { renderScatter(); if (M.sel) renderMonth(M.sel); renderStack(); } }, 150);
    });
  }
  boot();
})();

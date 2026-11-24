/* Australian Telco Compare: cost engine (works in the browser and in Node for tests).
 *
 * Phase 1 covers home internet and SIM-only mobile:
 *   neededSpeed(h)                       household activities -> evening download/upload needed
 *   techOk(plan, tech)                   can this plan be used on the home's connection type?
 *   meets(plan, need, tech, avail)       speed + technology/availability check, with reasons
 *   hardwareCost(plan, modemPrice)       up-front modem / 5G / Starlink hardware
 *   internetCost(plan, opts)             cost over a horizon: promo months, setup, modem, bundle
 *   reswitchCost(plan, pool, need, opts) the same, re-switching to the best promo each time one ends
 *   frontier(items)                      plans no other plan beats on both price and speed
 *   mobileCost(plan, line, opts)         per-line cost over a horizon, or why the plan doesn't fit
 * Prices in the data already include GST. Months are averaged (365.25 / 12 days).
 */
(function (root) {
  "use strict";

  const DAYS_PER_MONTH = 365.25 / 12;
  const NBN_TIERS = [12, 25, 50, 100, 250, 500, 750, 1000, 2000];
  const FIXED_LINE = ["fttp", "hfc", "fttc", "fttn", "fttb"];

  /* Bandwidth per concurrent activity, Mbps [down, up]. Typical streaming-service and video-call
   * recommendations, rounded up a little. */
  const RATES = {
    person: [3, 0.5],      // browsing, music, social, background updates (per person at home)
    uhd: [25, 0],          // one 4K stream
    hd: [8, 0],            // one HD stream
    call: [4, 3],          // one HD video call
    gamer: [5, 1],         // online gaming (needs low latency more than speed)
  };
  const HEADROOM = 1.3;    // shared connections never hit their nominal rate, so keep a margin

  function neededSpeed(h) {
    const parts = [];
    const add = (label, n, rate) => { if (n > 0) parts.push({ label, n, down: n * rate[0], up: n * rate[1] }); };
    add("People online", h.people || 0, RATES.person);
    add("4K streams at once", h.uhd || 0, RATES.uhd);
    add("HD streams at once", h.hd || 0, RATES.hd);
    add("Video calls at once", h.calls || 0, RATES.call);
    add("Online gamers", h.gamers || 0, RATES.gamer);
    if (h.uploadGB > 0 && h.uploadHours > 0) {
      // e.g. a 20 GB nightly backup that should finish within 4 hours
      parts.push({ label: "Big uploads", n: 1, down: 0, up: h.uploadGB * 8000 / (h.uploadHours * 3600) });
    }
    const sum = k => parts.reduce((a, p) => a + p[k], 0);
    return { down: Math.ceil(sum("down") * HEADROOM), up: Math.ceil(sum("up") * HEADROOM), parts, headroom: HEADROOM };
  }

  /* tech: fttp | hfc | fttc | fttn | fttb | fw | sat | unknown. "unknown" accepts any fixed-line
   * plan but flags the ones that need FTTP or HFC.
   * avail (optional): { fiveG: [networks with 5G home coverage at the address] | false,
   *                    starlink: bool, privateNet: bool }. Without it, 5G and Starlink pass. */
  function techOk(plan, tech, avail) {
    const t = plan.techs || [];
    if (plan.kind === "5g") {
      if (!avail) return { ok: true };
      const nets = avail.fiveG || [];
      if (!nets.length) return { ok: false, why: "5G home internet is switched off in your settings" };
      if (plan.network && !nets.includes(plan.network)) return { ok: false, why: `Needs ${plan.network[0].toUpperCase() + plan.network.slice(1)} 5G coverage` };
      return { ok: true, flag: "Check 5G coverage at your address" };
    }
    if (plan.kind === "starlink") {
      if (avail && !avail.starlink) return { ok: false, why: "Starlink is switched off in your settings" };
      return { ok: true };
    }
    if (plan.kind === "private") {
      if (avail && avail.privateNet) return { ok: true, flag: "Only where the provider's own network reaches" };
      return { ok: false, why: "Only in areas served by the provider's own network" };
    }
    if (tech === "unknown" || !tech) {
      if (t.some(x => FIXED_LINE.includes(x))) {
        return t.includes("fttc") ? { ok: true } : { ok: true, flag: "Needs an FTTP or HFC connection" };
      }
      return { ok: false, why: plan.kind === "fixed_wireless" ? "Fixed wireless only" : "Satellite only" };
    }
    return t.includes(tech) ? { ok: true } : { ok: false, why: `Not available on ${tech.toUpperCase()}` };
  }

  /* need: { down, up } in Mbps (typical evening), optionally minTier: an NBN tier the user picked
   * instead. With minTier, NBN plans need that tier or faster and other plans need an evening
   * download of at least 80% of it (typical evening speeds sit a little under the tier). */
  function meets(plan, need, tech, avail) {
    const reasons = [], flags = [];
    const tk = techOk(plan, tech, avail);
    if (!tk.ok) reasons.push(tk.why);
    if (tk.flag) flags.push(tk.flag);
    if (need) {
      // No published evening speed: judge an NBN plan by its tier, anything else as unknown.
      const down = plan.down != null ? plan.down : (plan.kind === "nbn" ? plan.tier : null);
      if (down == null) reasons.push("No evening speed published");
      if (need.minTier) {
        if (plan.kind === "nbn" && plan.tier) {
          if (plan.tier < need.minTier) reasons.push(`NBN ${plan.tier} is slower than the NBN ${need.minTier} you picked`);
        } else if (down != null && down < 0.8 * need.minTier) {
          reasons.push(`Evening download ${down} Mbps is well below NBN ${need.minTier}`);
        }
      } else if (down != null && down < need.down) {
        reasons.push(`Evening download ${down} Mbps is below the ${need.down} Mbps needed`);
      }
      if (plan.up != null && need.up && plan.up < need.up) reasons.push(`Upload ${plan.up} Mbps is below the ${need.up} Mbps needed`);
    }
    return { ok: reasons.length === 0, reasons, flags };
  }

  /* What the hardware costs you up front.
   * NBN: nothing if the plan includes a modem or you already have one (modemPrice 0); otherwise
   * the provider's price if it sells one, else modemPrice (what you'd pay for your own).
   * 5G and Starlink need the provider's own hardware, so its price always counts. */
  const ownHardware = plan => plan.kind === "5g" || plan.kind === "starlink";
  function hardwareCost(plan, modemPrice) {
    const m = plan.modem || {};
    if (m.offer === "included" || m.offer === "included_contract") return 0;
    if (ownHardware(plan)) return m.cost || 0;
    if (!modemPrice) return 0;
    return (m.offer === "purchase" || m.offer === "rental") && m.cost != null ? m.cost : modemPrice;
  }
  /* Monthly hardware rental (e.g. a rented 5G modem), on top of the plan price. */
  function hardwareMonthly(plan, modemPrice) {
    const m = plan.modem || {};
    if (m.offer !== "rental" || !m.monthly) return 0;
    return ownHardware(plan) || modemPrice ? m.monthly : 0;
  }

  /* Cost of staying on one internet plan for `months`.
   * opts: months (12), bundled (true if the plan's bundle condition is met), modemPrice (what a
   * modem costs you if the plan doesn't include one; 0 if you already own one), credits (count
   * sign-up credits), bundleDuringPromo (apply bundle discounts during promo months too). */
  /* An intro offer that needs a bundle (promo.requires = "energy" | "mobile") only counts when
   * bundle discounts are being counted. */
  const activePromo = (plan, o) => (plan.promo && (!plan.promo.requires || (o && o.bundled)) ? plan.promo : null);
  function internetCost(plan, opts) {
    const o = Object.assign({ months: 12, bundled: false, modemPrice: 0, credits: false, bundleDuringPromo: false }, opts);
    const promo = activePromo(plan, o), pm = promo ? Math.min(promo.months, o.months) : 0;
    // Bundle discounts apply after any intro offer, unless the provider says they stack with it.
    const bundles = o.bundled ? (plan.bundle || []) : [];
    const offAfter = bundles.reduce((a, b) => a + (b.off || 0), 0);
    const offDuring = bundles.reduce((a, b) => a + (b.during_promo || o.bundleDuringPromo ? (b.off || 0) : 0), 0);
    const rent = hardwareMonthly(plan, o.modemPrice);
    const monthly = [];
    let promoCost = 0, ongoingCost = 0, bundleSave = 0;
    for (let m = 0; m < o.months; m++) {
      const inPromo = m < pm;
      let c = inPromo ? promo.price : plan.price;
      const off = Math.min(inPromo ? offDuring : offAfter, c);
      c -= off; bundleSave += off;
      if (inPromo) promoCost += c; else ongoingCost += c;
      monthly.push(c + rent);
    }
    const modem = hardwareCost(plan, o.modemPrice);
    const setup = plan.setup || 0;
    const credit = o.credits ? (plan.credit || 0) : 0;
    monthly[0] += setup + modem - credit;
    const rental = rent * o.months;
    const total = promoCost + ongoingCost + rental + setup + modem - credit;
    return { total, perMonth: total / o.months, monthly,
      parts: { promo: promoCost, ongoing: ongoingCost, rental, setup, modem, credit, bundleSave } };
  }

  /* Promo-chasing: take `plan` for its promo period, then each time a promo ends switch to the
   * plan in `pool` with the cheapest promo window (setup fee spread over the window). Candidates
   * must meet the need, be the same kind of service and be at least as fast as `plan`. Intro
   * offers are for new customers, so a provider already used isn't eligible again. With nothing
   * to switch to you stay put on the ongoing price. Without a promo this equals internetCost. */
  function atLeastAsFast(p, ref) {
    if (p.kind === "nbn" && ref.kind === "nbn" && p.tier && ref.tier) return p.tier >= ref.tier;
    return (p.down || 0) >= 0.9 * (ref.down || 0);
  }
  function reswitchCost(plan, pool, need, opts) {
    const o = Object.assign({ months: 12, tech: "unknown", modemPrice: 0, avail: undefined }, opts);
    if (!activePromo(plan, o)) {
      const c = internetCost(plan, o);
      return Object.assign(c, { path: [plan.id], steps: [{ id: plan.id, months: o.months, cost: c.total, promo: false }] });
    }
    const prov = p => p.provider || p.id;
    const cands = pool.filter(p => activePromo(p, o) && p.kind === plan.kind && atLeastAsFast(p, plan) && meets(p, need, o.tech, o.avail).ok);
    const used = new Set();
    let left = o.months, cur = plan, first = true;
    const monthly = [], path = [], steps = [];
    while (left > 0) {
      const cp = activePromo(cur, o);
      const span = Math.min(cp ? cp.months : left, left);
      const c = internetCost(cur, Object.assign({}, o, { months: span, modemPrice: first ? o.modemPrice : 0 }));
      monthly.push(...c.monthly);
      path.push(cur.id);
      steps.push({ id: cur.id, months: span, cost: c.total, promo: !!cp });
      used.add(prov(cur));
      left -= span; first = false;
      if (left <= 0) break;
      let best = null, bestRate = Infinity;
      for (const p of cands) {
        if (used.has(prov(p))) continue;
        const w = Math.min(p.promo.months, left);
        const rate = (p.promo.price * w + (p.setup || 0)) / w;
        if (rate < bestRate) { bestRate = rate; best = p; }
      }
      if (!best) { cur = Object.assign({}, cur, { promo: null, setup: 0 }); continue; }   // stay put
      cur = best;
    }
    const total = monthly.reduce((a, x) => a + x, 0);
    return { total, perMonth: total / o.months, monthly, path, steps };
  }

  /* Best-value frontier: the plans no other plan beats on both price and speed.
   * items: [{ cost, speed, ... }]. Returns them sorted by speed, ascending. */
  function frontier(items) {
    const xs = items.filter(x => x.speed > 0).slice().sort((a, b) => b.speed - a.speed || a.cost - b.cost);
    const out = [];
    let best = Infinity;
    for (const x of xs) if (x.cost < best - 1e-9) { out.push(x); best = x.cost; }
    return out.reverse();
  }

  /* Monthly-equivalent data allowance (GB); Infinity for unlimited, null for unknown. */
  function monthlyData(plan) {
    if (plan.data_gb === -1) return Infinity;
    if (plan.data_gb == null) return null;
    return plan.data_gb * DAYS_PER_MONTH / plan.period_days;
  }

  /* line: { dataGB (per month), dataOnly (false), networks (allowed host networks or null),
   *         intl (ISO codes that need included calls), allowUnknownData (false) }
   * opts: { months (12) } */
  function mobileCost(plan, line, opts) {
    const o = Object.assign({ months: 12 }, opts);
    const L = Object.assign({ dataGB: 0, dataOnly: false, networks: null, intl: [], allowUnknownData: false }, line);
    const why = [];
    if (!!plan.data_only !== !!L.dataOnly) why.push(plan.data_only ? "Data-only plan (no calls)" : "Includes calls (looking for data-only)");
    if (L.networks && L.networks.length && !L.networks.includes(plan.network)) why.push(`On the ${plan.network || "unknown"} network`);
    const md = monthlyData(plan);
    if (md == null && !L.allowUnknownData) why.push("Data allowance not published");
    else if (md != null && md < L.dataGB) why.push(`${Math.round(md)} GB a month is less than the ${L.dataGB} GB needed`);
    const missing = (L.intl || []).filter(c => !(plan.intl || []).includes(c));
    if (missing.length) why.push(`No included calls to ${missing.join(", ")}`);
    const recharges = o.months * DAYS_PER_MONTH / plan.period_days;     // continuous, e.g. 13.04 a year on 28 days
    const promoN = plan.promo ? Math.min(plan.promo.periods, recharges) : 0;
    const total = promoN * (plan.promo ? plan.promo.price : 0) + (recharges - promoN) * plan.price;
    return { ok: why.length === 0, why, total, perMonth: total / o.months, recharges, monthlyGB: md };
  }

  const api = { neededSpeed, techOk, meets, activePromo, hardwareCost, hardwareMonthly, internetCost, reswitchCost, atLeastAsFast, frontier, mobileCost, monthlyData,
    RATES, HEADROOM, NBN_TIERS, FIXED_LINE, DAYS_PER_MONTH };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TelcoEngine = api;
})(typeof window !== "undefined" ? window : globalThis);

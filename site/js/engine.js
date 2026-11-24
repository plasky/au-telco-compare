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
 *   accountDiscount(rules, ctx)          multi-line and bundle rules for one provider's account
 *   household(input)                     cheapest mix of internet + mobile lines, best per provider
 *   handsetCatalogue(phones)             models with their storage sizes and repayment terms
 *   phoneOptions(input)                  outright + SIM-only vs each carrier's repayments + plan
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
  // opts.bundled: true = assume every bundle condition is met; or a list such as ["mobile", "energy"]
  const hasBundle = (o, kind) => !!o && (o.bundled === true || (Array.isArray(o.bundled) && o.bundled.includes(kind)));
  const activePromo = (plan, o) => (plan.promo && (!plan.promo.requires || hasBundle(o, plan.promo.requires)) ? plan.promo : null);
  function internetCost(plan, opts) {
    const o = Object.assign({ months: 12, bundled: false, modemPrice: 0, credits: false, bundleDuringPromo: false }, opts);
    const promo = activePromo(plan, o), pm = promo ? Math.min(promo.months, o.months) : 0;
    // Bundle discounts apply after any intro offer, unless the provider says they stack with it.
    const bundles = (plan.bundle || []).filter(b => hasBundle(o, b.with));
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
   *         intl (ISO codes that need included calls), style ("any" | "short": 31 days or less |
   *         "postpaid"), allowUnknownData (false) }
   * opts: { months (12), with: services also taken from this provider, e.g. ["internet"] } */
  function mobileCost(plan, line, opts) {
    const o = Object.assign({ months: 12, with: [] }, opts);
    const L = Object.assign({ dataGB: 0, dataOnly: false, networks: null, intl: [], style: "any", allowUnknownData: false }, line);
    const why = [];
    if (!!plan.data_only !== !!L.dataOnly) why.push(plan.data_only ? "Data-only plan (no calls)" : "Includes calls (looking for data-only)");
    if (L.networks && L.networks.length && !L.networks.includes(plan.network)) why.push(`On the ${plan.network || "unknown"} network`);
    if (plan.requires && !o.with.includes(plan.requires)) why.push(`Only sold with the provider's ${plan.requires}`);
    if (L.style === "short" && plan.period_days > 31) why.push(`${plan.period_days}-day recharge (you asked for monthly)`);
    if (L.style === "postpaid" && plan.type !== "postpaid") why.push("Prepaid (you asked for a monthly bill)");
    const md = monthlyData(plan);
    if (md == null && !L.allowUnknownData) why.push("Data allowance not published");
    else if (md != null && md < L.dataGB) why.push(`${Math.round(md)} GB a month is less than the ${L.dataGB} GB needed`);
    const missing = (L.intl || []).filter(c => !(plan.intl || []).includes(c));
    if (missing.length) why.push(`No included calls to ${missing.join(", ")}`);
    const recharges = o.months * DAYS_PER_MONTH / plan.period_days;     // continuous, e.g. 13.04 a year on 28 days
    const promo = plan.promo && (!plan.promo.requires || o.with.includes(plan.promo.requires)) ? plan.promo : null;
    const promoN = promo ? Math.min(promo.periods, recharges) : 0;
    const offs = (plan.bundle || []).filter(b => o.with.includes(b.with));
    const offAfter = offs.reduce((a, b) => a + (b.off || 0), 0);
    const offDuring = offs.reduce((a, b) => a + (b.during_promo ? (b.off || 0) : 0), 0);
    const promoEach = promo ? promo.price - Math.min(offDuring, promo.price) : 0;
    const ongoingEach = plan.price - Math.min(offAfter, plan.price);
    const total = promoN * promoEach + (recharges - promoN) * ongoingEach;
    const save = promoN * (promo ? promo.price : 0) + (recharges - promoN) * plan.price - total;
    return { ok: why.length === 0, why, total, perMonth: total / o.months, recharges, monthlyGB: md, bundleSave: save };
  }

  /* Account-level discounts for the lines (and internet) taken with one provider, from
   * overrides/bundles.toml rules. lineTotals: costs over the horizon of the provider's lines.
   * Rule fields: applies_to ("mobile" | "internet"), with ("mobile": other lines on the account,
   * "internet", "energy"), then one of pct (% off each qualifying line or the internet bill),
   * off ($ a month per qualifying line, or per account for internet) or tiers ($ a month off the
   * internet by number of mobile services: [1 service, 2 services, ...]); extra_only: only lines
   * after the first (the dearest line pays full price). Returns { total, items: [{text, amount}] }. */
  function accountDiscount(rules, ctx) {
    const { lineTotals, internetTotal, hasInternet, hasEnergy, months } = ctx;
    const items = [];
    const sorted = lineTotals.slice().sort((a, b) => b - a);
    for (const r of rules || []) {
      let amt = 0;
      if (r.applies_to === "mobile") {
        if ((r.with === "internet" && !hasInternet) || (r.with === "energy" && !hasEnergy)) continue;
        const lines = (r.with === "mobile" || r.extra_only) ? sorted.slice(1) : sorted;
        if (r.with === "mobile" && sorted.length < (r.min_lines || 2)) continue;
        for (const t of lines) amt += r.pct ? t * r.pct / 100 : Math.min((r.off || 0) * months, t);
      } else if (r.applies_to === "internet" && hasInternet) {
        if (r.with === "energy" && !hasEnergy) continue;
        if (r.with === "mobile") {
          const n = sorted.length;
          if (!n) continue;
          const perMonth = r.tiers ? r.tiers[Math.min(n, r.tiers.length) - 1] : r.pct ? 0 : (r.off || 0);
          amt = r.pct ? internetTotal * r.pct / 100 : perMonth * months;
        } else {
          amt = r.pct ? internetTotal * r.pct / 100 : (r.off || 0) * months;
        }
        amt = Math.min(amt, internetTotal);
      }
      if (amt > 0) items.push({ text: r.text || "Bundle discount", amount: amt, applies_to: r.applies_to });
    }
    return { total: items.reduce((a, x) => a + x.amount, 0), items };
  }

  /* The cheapest way to buy internet plus every mobile line, and the best deal with each
   * provider.
   * input: { internet: fitting internet plans (or [] to leave internet out), lines: [line],
   *          mobile: mobile plans, rules: { provider: [rule] }, energy: provider id of your
   *          energy retailer or null, months, internetOpts: extra internetCost options (modem,
   *          credits) }
   * For each provider P, every split of the lines between P and the cheapest plan elsewhere is
   * tried (2^lines, at most 256), with P's or the cheapest other internet, counting P's
   * per-plan bundle discounts and account rules. "single" means internet and every line with P.
   * Returns { lines (per-line options, cheapest first), independent, best, byProvider, singles }. */
  function household(input) {
    const H = Object.assign({ internet: [], lines: [], mobile: [], rules: {}, energy: null, months: 12, internetOpts: {} }, input);
    const months = H.months, prov = p => p.provider;
    const iCost = (p, withMobile) => {
      const bundled = [];
      if (withMobile) bundled.push("mobile");
      if (H.energy && p.provider === H.energy) bundled.push("energy");
      return internetCost(p, Object.assign({}, H.internetOpts, { months, bundled }));
    };
    // per-line options: lineAll includes plans only sold with another service (costed with it);
    // lineOpts, used when buying the line on its own, leaves them out
    const lineAll = H.lines.map(L => H.mobile.map(p => ({ p, c: mobileCost(p, L, { months, with: p.requires ? [p.requires] : [] }) }))
      .filter(x => x.c.ok));
    const lineOpts = lineAll.map(o => o.filter(x => !x.p.requires).sort((a, b) => a.c.total - b.c.total));
    // cheapest per provider per line, plain and with that provider's internet
    const providers = [...new Set([...H.internet.map(prov), ...H.mobile.map(prov)])];
    const bestBy = H.lines.map((L, i) => {
      const m = {};
      for (const x of lineOpts[i]) {
        const k = prov(x.p);
        if (!m[k] || x.c.total < m[k].c.total) m[k] = x;
      }
      return m;
    });
    const bestWith = (i, P, withInternet) => {
      let best = null;
      for (const x of lineAll[i]) {
        if (prov(x.p) !== P) continue;
        if (x.p.requires === "internet" && !withInternet) continue;
        if (x.p.requires === "energy" && H.energy !== P) continue;
        const wi = [];
        if (withInternet) wi.push("internet");
        if (H.energy === P) wi.push("energy");
        const c = wi.length ? mobileCost(x.p, H.lines[i], { months, with: wi }) : x.c;
        if (!best || c.total < best.c.total) best = { p: x.p, c };
      }
      return best;
    };
    const cheapestExcept = (i, P) => {
      for (const x of lineOpts[i]) if (prov(x.p) !== P) return x;
      return null;
    };
    const iPlain = H.internet.map(p => ({ p, c: iCost(p, false) })).sort((a, b) => a.c.total - b.c.total);
    const iBestBy = (P, withMobile) => {
      let best = null;
      for (const p of H.internet) if (prov(p) === P) { const c = iCost(p, withMobile); if (!best || c.total < best.c.total) best = { p, c }; }
      return best;
    };
    const iCheapestExcept = P => iPlain.find(x => prov(x.p) !== P) || null;
    const wantInternet = H.internet.length > 0;

    // Independent: cheapest of everything, no cross-service bundles.
    const indLines = lineOpts.map(o => o[0] || null);
    const independent = {
      internet: wantInternet ? iPlain[0] || null : null, lines: indLines, discount: { total: 0, items: [] },
      total: (wantInternet && iPlain[0] ? iPlain[0].c.total : 0) + indLines.reduce((a, x) => a + (x ? x.c.total : Infinity), 0),
    };

    const byProvider = [], singles = [];
    const n = H.lines.length;
    for (const P of providers) {
      const rules = H.rules[P] || [];
      let best = null, bestSingle = null;
      const pInt = { plain: iBestBy(P, false), withMob: iBestBy(P, true) };
      const extInt = iCheapestExcept(P);
      // P's best plan for each line (with and without P's internet) and the cheapest elsewhere
      const onPlain = H.lines.map((L, i) => bestWith(i, P, false));
      const onWithInt = H.lines.map((L, i) => bestWith(i, P, true));
      const ext = H.lines.map((L, i) => cheapestExcept(i, P));
      if (!onPlain.some(Boolean) && !pInt.plain) continue;
      for (let mask = 0; mask < (1 << n); mask++) {
        for (const useP of wantInternet ? [true, false] : [false]) {
          if (useP && !pInt.plain) continue;
          const onP = [];
          for (let i = 0; i < n; i++) if (mask & (1 << i)) onP.push(i);
          const lines = [];
          let ok = true, total = 0;
          for (let i = 0; i < n; i++) {
            const x = (mask & (1 << i)) ? (useP ? onWithInt[i] : onPlain[i]) : ext[i];
            if (!x) { ok = false; break; }
            lines.push(Object.assign({ onP: !!(mask & (1 << i)) }, x));
            total += x.c.total;
          }
          if (!ok) continue;
          let internet = null;
          if (wantInternet) {
            internet = useP ? (onP.length ? pInt.withMob : pInt.plain) : extInt;
            if (!internet) continue;
            total += internet.c.total;
          }
          if (!useP && !onP.length) continue;       // nothing with P: that's the independent case
          const disc = accountDiscount(rules, { lineTotals: onP.map(i => lines[i].c.total), internetTotal: useP ? internet.c.total : 0,
            hasInternet: useP, hasEnergy: H.energy === P, months });
          total -= disc.total;
          const sol = { provider: P, internet, internetWithP: useP, lines, discount: disc, total, single: (!wantInternet || useP) && onP.length === n };
          if (!best || total < best.total - 1e-9) best = sol;
          if (sol.single && (!bestSingle || total < bestSingle.total - 1e-9)) bestSingle = sol;
        }
      }
      if (best) byProvider.push(best);
      if (bestSingle) singles.push(bestSingle);
    }
    byProvider.sort((a, b) => a.total - b.total);
    singles.sort((a, b) => a.total - b.total);
    const bestSol = byProvider.length && byProvider[0].total < independent.total - 1e-9 ? byProvider[0] : independent;
    return { lines: lineOpts, independent, best: bestSol, byProvider, singles };
  }

  /* Phones. The catalogue: one entry per handset with its storage sizes and repayment terms. */
  function handsetCatalogue(phones) {
    const m = new Map();
    for (const x of phones || []) {
      let h = m.get(x.handset);
      if (!h) { h = { handset: x.handset, brand: x.brand, model: x.model, storages: new Set(), terms: new Set(), sellers: new Set() }; m.set(x.handset, h); }
      h.storages.add(x.storage_gb); if (x.term) h.terms.add(x.term); h.sellers.add(x.provider);
    }
    return [...m.values()].map(h => ({ handset: h.handset, brand: h.brand, model: h.model,
      storages: [...h.storages].sort((a, b) => a - b), terms: [...h.terms].sort((a, b) => a - b), sellers: [...h.sellers] }))
      .sort((a, b) => a.brand.localeCompare(b.brand) || a.model.localeCompare(b.model, "en", { numeric: true }));
  }

  /* Ways to get one phone with a plan for a line, costed over `term` months:
   *   outright: the cheapest outright price (any seller) + the cheapest SIM-only plan that fits;
   *   repay:    each seller's repayment offer for that term + its cheapest eligible plan that fits
   *             (offer.plans, else any of its postpaid phone plans), minus the discounts and bill
   *             credits that apply to that plan (trade-in ones only if tradeIn).
   * With no outright listing, the outright price is taken as the lowest full repayment total.
   * input: { handset, storage, term, line, phones, mobile, tradeIn }
   * Returns options cheapest first: { kind, provider, listing, plan: {p, c}, deviceGross, device,
   *   rewards: [{text, amount}], total, perMonth, flags }. */
  function phoneOptions(input) {
    const o = Object.assign({ term: 24, tradeIn: false, phones: [], mobile: [], line: {} }, input);
    const months = o.term;
    const listings = o.phones.filter(x => x.handset === o.handset && x.storage_gb === o.storage);
    const sims = o.mobile.filter(p => !p.requires).map(p => ({ p, c: mobileCost(p, o.line, { months }) }))
      .filter(x => x.c.ok).sort((a, b) => a.c.total - b.c.total);
    const out = [];
    const outs = listings.filter(x => x.outright != null).sort((a, b) => a.outright - b.outright);
    const repays = listings.filter(x => x.term === months && x.monthly);
    if (sims.length) {
      if (outs.length) {
        const b = outs[0];
        out.push({ kind: "outright", provider: b.provider, listing: b, plan: sims[0], deviceGross: b.outright, device: b.outright,
          rewards: [], total: b.outright + sims[0].c.total, flags: [], sellers: outs });
      } else {
        const all = listings.filter(x => x.term && x.monthly).map(x => ({ x, t: x.monthly * x.term })).sort((a, b) => a.t - b.t);
        if (all.length) out.push({ kind: "outright", provider: all[0].x.provider, listing: all[0].x, plan: sims[0], deviceGross: all[0].t,
          device: all[0].t, rewards: [], total: all[0].t + sims[0].c.total, flags: ["Outright price taken from the full repayment total"], sellers: [] });
      }
    }
    for (const L of repays) {
      const eligible = o.mobile.filter(p => p.provider === L.provider && !p.data_only && !p.requires &&
        (L.plans ? L.plans.includes(p.id) : p.type === "postpaid"));
      let best = null;
      for (const p of eligible) {
        const c = mobileCost(p, o.line, { months });
        if (!c.ok) continue;
        const applies = r => (!r.plans || r.plans.includes(p.id)) && (!r.requires_trade_in || o.tradeIn);
        const rewards = [];
        let credited = false;
        for (const d of L.discounts || []) if (applies(d)) rewards.push({ text: d.text || "Discount", amount: d.off });
        for (const cr of L.credits || []) if (applies(cr)) { rewards.push({ text: cr.text || "Bill credit", amount: cr.per_month * Math.min(cr.months, months) }); credited = true; }
        const gross = L.monthly * L.term, reward = rewards.reduce((a, x) => a + x.amount, 0);
        const total = c.total + gross - reward;
        if (!best || total < best.total - 1e-9) {
          best = { kind: "repay", provider: L.provider, listing: L, plan: { p, c }, deviceGross: gross, device: gross - reward, rewards, total,
            flags: [`Leave before ${L.term} months and you pay out the rest of the phone${credited ? " and lose the remaining credits" : ""}`] };
        }
      }
      if (best) out.push(best);
    }
    for (const x of out) x.perMonth = x.total / months;
    return out.sort((a, b) => a.total - b.total);
  }

  const api = { neededSpeed, techOk, meets, activePromo, hardwareCost, hardwareMonthly, internetCost, reswitchCost, atLeastAsFast, frontier, mobileCost, accountDiscount, household, handsetCatalogue, phoneOptions, monthlyData,
    RATES, HEADROOM, NBN_TIERS, FIXED_LINE, DAYS_PER_MONTH };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TelcoEngine = api;
})(typeof window !== "undefined" ? window : globalThis);

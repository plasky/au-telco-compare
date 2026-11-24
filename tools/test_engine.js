// Engine and data checks: node tools/test_engine.js
// 1. Cost model on hand-worked synthetic plans (independent of the nightly data).
// 2. Sanity checks on the built site data (schema-level facts the UI relies on).
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const E = require(path.join(__dirname, "..", "site", "js", "engine.js"));

let fails = 0;
const ok = (cond, msg) => { console.log((cond ? "PASS " : "FAIL ") + msg); if (!cond) fails++; };
const near = (a, b, tol = 0.01) => Math.abs(a - b) <= tol;

// --- 1. Internet cost -------------------------------------------------------------------
const nbn100 = { id: "a-100", kind: "nbn", tier: 100, techs: E.FIXED_LINE, down: 100, up: 18, price: 90,
  promo: { price: 30, months: 6 }, setup: 0, modem: { offer: "byo" }, bundle: [{ with: "mobile", off: 10 }] };
let c = E.internetCost(nbn100, { months: 12 });
ok(near(c.total, 6 * 30 + 6 * 90), `promo 6 x $30 then 6 x $90 = $720 (got ${c.total})`);
c = E.internetCost(nbn100, { months: 12, bundled: true });
ok(near(c.total, 6 * 30 + 6 * 80) && near(c.parts.bundleSave, 60), `bundle $10 off after the promo = $660 (got ${c.total})`);
c = E.internetCost({ ...nbn100, bundle: [{ with: "mobile", off: 10, during_promo: true }] }, { months: 12, bundled: true });
ok(near(c.total, 6 * 20 + 6 * 80), `bundle that stacks with the intro offer = $600 (got ${c.total})`);
const agl = { ...nbn100, price: 85, promo: { price: 35, months: 3, requires: "energy" }, bundle: [{ with: "energy", off: 15 }] };
ok(near(E.internetCost(agl, { months: 12 }).total, 12 * 85) && near(E.internetCost(agl, { months: 12, bundled: true }).total, 3 * 35 + 9 * 70),
  "an intro offer that needs the energy bundle only counts with the bundle ($1020 vs $735)");
c = E.internetCost(nbn100, { months: 24, modemPrice: 150 });
ok(near(c.total, 6 * 30 + 18 * 90 + 150), `24 months + $150 modem on a BYO plan = $1950 (got ${c.total})`);
const withModem = { ...nbn100, promo: null, setup: 99, modem: { offer: "included_contract" } };
c = E.internetCost(withModem, { months: 12, modemPrice: 150 });
ok(near(c.total, 12 * 90 + 99) && c.parts.modem === 0, `included modem costs nothing, $99 setup counted = $1179 (got ${c.total})`);
c = E.internetCost(nbn100, { months: 3 });
ok(near(c.total, 90), `horizon shorter than the promo: 3 x $30 = $90 (got ${c.total})`);

// Promo chasing: after 6 months at $30, switch to the cheapest promo window (B: $40 x 6, setup $0
// beats C: $35 x 6 + $60 setup = $45/month effective).
const B = { id: "b", kind: "nbn", tier: 100, techs: E.FIXED_LINE, down: 100, up: 20, price: 95, promo: { price: 40, months: 6 }, setup: 0, modem: { offer: "byo" } };
const C = { id: "c", kind: "nbn", tier: 100, techs: E.FIXED_LINE, down: 100, up: 20, price: 99, promo: { price: 35, months: 6 }, setup: 60, modem: { offer: "byo" } };
const need = { down: 80, up: 15 };
c = E.reswitchCost(nbn100, [nbn100, B, C], need, { months: 12 });
ok(near(c.total, 6 * 30 + 6 * 40) && c.path.join(",") === "a-100,b", `re-switch: 6 x $30 then 6 x $40 on plan b = $420 (got ${c.total}, ${c.path})`);
c = E.reswitchCost({ ...nbn100, setup: 50 }, [{ ...nbn100, setup: 50 }], need, { months: 12 });
ok(near(c.total, 50 + 6 * 30 + 6 * 90), `nothing else to switch to: stay on the ongoing price, setup charged once (got ${c.total})`);
c = E.reswitchCost({ ...nbn100, promo: null }, [B, C], need, { months: 12 });
ok(near(c.total, 12 * 90), "no promo to chase: same as staying put");

// --- Needs and technology ---------------------------------------------------------------
const n = E.neededSpeed({ people: 4, uhd: 2, hd: 1, calls: 2, gamers: 1 });
// down = (4x3 + 2x25 + 8 + 2x4 + 5) x 1.3 = 83 x 1.3 = 107.9 -> 108; up = (4x0.5 + 2x3 + 1) x 1.3 = 11.7 -> 12
ok(n.down === 108 && n.up === 12, `needed speed for a busy family of 4: ${n.down}/${n.up} Mbps (expect 108/12)`);
const up = E.neededSpeed({ people: 1, uploadGB: 20, uploadHours: 4 });
ok(near(up.up, Math.ceil((0.5 + 20 * 8000 / (4 * 3600)) * 1.3), 0), `20 GB backup in 4 h needs ${up.up} Mbps up`);
const p500 = { kind: "nbn", tier: 500, techs: ["fttp", "hfc"], down: 500, up: 50 };
ok(!E.techOk(p500, "fttn").ok && E.techOk(p500, "hfc").ok, "NBN 500 works on HFC but not FTTN");
ok(E.techOk(p500, "unknown").ok && E.techOk(p500, "unknown").flag, "unknown connection: NBN 500 allowed but flagged");
ok(!E.techOk({ kind: "private", techs: [] }, "fttp").ok, "private-network plans are excluded");
ok(!E.meets({ ...nbn100, tier: 25, down: null }, need, "fttn").ok, "no published speed: an NBN 25 plan is judged by its tier");
ok(E.meets(nbn100, need, "fttn").ok && !E.meets(nbn100, { down: 150, up: 10 }, "fttn").ok, "speed check against the need");

// --- Availability, hardware, tiers, frontier ------------------------------------------------
const g5 = { id: "g5", provider: "x", kind: "5g", network: "optus", techs: [], down: 200, up: 20, price: 79, setup: 0, modem: { offer: "purchase", cost: 240 } };
ok(E.techOk(g5, "fttn", { fiveG: ["optus"] }).ok && E.techOk(g5, "fttn", { fiveG: ["optus"] }).flag, "5G plan allowed (and flagged) where its network has coverage");
ok(!E.techOk(g5, "fttn", { fiveG: ["telstra"] }).ok && !E.techOk(g5, "fttn", { fiveG: false }).ok, "5G plan excluded without its network's coverage");
ok(!E.techOk({ kind: "starlink", techs: [] }, "fttp", { starlink: false }).ok, "Starlink excluded when switched off");
ok(E.techOk({ kind: "private", techs: [] }, "fttp", { privateNet: true }).ok, "private networks allowed when the user opts in");
c = E.internetCost(g5, { months: 12, modemPrice: 0 });
ok(near(c.total, 12 * 79 + 240), `5G hardware counts even if you own an NBN modem = $1188 (got ${c.total})`);
ok(E.hardwareCost({ kind: "nbn", modem: { offer: "purchase", cost: 99 } }, 150) === 99 && E.hardwareCost({ kind: "nbn", modem: { offer: "purchase", cost: 99 } }, 0) === 0,
  "NBN modem: the provider's price if you need one, nothing if you have one");
ok(E.meets({ ...nbn100, down: 92 }, { minTier: 100, up: 10 }, "fttn").ok && !E.meets({ ...nbn100, tier: 50, down: 50 }, { minTier: 100 }, "fttn").ok, "picked tier: NBN 100 passes, NBN 50 doesn't");
ok(E.meets(g5, { minTier: 250 }, "fttp", { fiveG: ["optus"] }).ok && !E.meets(g5, { minTier: 500 }, "fttp", { fiveG: ["optus"] }).ok, "picked tier for 5G: compares the evening speed with 80% of the tier");
const rent5g = { ...g5, modem: { offer: "rental", cost: 25, monthly: 10 } };
c = E.internetCost(rent5g, { months: 12 });
ok(near(c.total, 12 * 79 + 25 + 12 * 10) && near(c.parts.rental, 120), `rented 5G modem: $10/month + $25 postage counted = $1093 (got ${c.total})`);
const fr = E.frontier([{ id: 1, cost: 60, speed: 50 }, { id: 2, cost: 70, speed: 45 }, { id: 3, cost: 80, speed: 100 }, { id: 4, cost: 75, speed: 100 }, { id: 5, cost: 120, speed: 900 }]);
ok(fr.map(x => x.id).join(",") === "1,4,5", `frontier keeps plans nobody beats on price and speed (got ${fr.map(x => x.id)})`);
// re-switching stays on the same kind and speed class
const slow = { id: "s", provider: "s", kind: "nbn", tier: 50, techs: E.FIXED_LINE, down: 50, up: 17, price: 60, promo: { price: 20, months: 6 }, setup: 0, modem: { offer: "byo" } };
c = E.reswitchCost(nbn100, [nbn100, slow, B], { down: 40, up: 10 }, { months: 12 });
ok(c.path.join(",") === "a-100,b", `re-switch never drops to a slower tier (path ${c.path})`);

// --- Household: bundles and the optimiser --------------------------------------------------
const R = 365.25 / 12 * 12 / 30;   // monthly recharges in a year = 12.175
const mA = { id: "mA", provider: "A", network: "optus", type: "postpaid", period_days: 30, price: 30, data_gb: 50, data_only: false, intl: [] };
ok(near(E.mobileCost({ ...mA, bundle: [{ with: "internet", off: 5 }] }, { dataGB: 10 }, { with: ["internet"] }).total, 25 * R)
  && near(E.mobileCost({ ...mA, bundle: [{ with: "internet", off: 5 }] }, { dataGB: 10 }).total, 30 * R), "SIM bundle discount only with the provider's internet");
ok(!E.mobileCost({ ...mA, period_days: 365, price: 300 }, { dataGB: 10, style: "short" }).ok && !E.mobileCost({ ...mA, type: "prepaid" }, { dataGB: 10, style: "postpaid" }).ok,
  "plan style: long expiry and prepaid can be excluded");
let ad = E.accountDiscount([{ applies_to: "mobile", with: "mobile", pct: 10 }], { lineTotals: [300, 200], internetTotal: 0, hasInternet: false, months: 12 });
ok(near(ad.total, 20), `10% off additional lines: $20 on a $200 second line (got ${ad.total})`);
ad = E.accountDiscount([{ applies_to: "internet", with: "mobile", tiers: [5, 7.5, 15] }], { lineTotals: [300, 200], internetTotal: 900, hasInternet: true, months: 12 });
ok(near(ad.total, 90), `tiered internet discount for 2 services: $7.50 x 12 = $90 (got ${ad.total})`);
ok(E.accountDiscount([{ applies_to: "internet", with: "mobile", off: 10 }], { lineTotals: [], internetTotal: 900, hasInternet: true, months: 12 }).total === 0,
  "internet-with-mobile discount needs at least one line");

const iA = { id: "iA", provider: "A", kind: "nbn", tier: 100, techs: E.FIXED_LINE, down: 100, up: 20, price: 80, setup: 0, modem: { offer: "byo" }, bundle: [{ with: "mobile", off: 10 }] };
const iB = { id: "iB", provider: "B", kind: "nbn", tier: 100, techs: E.FIXED_LINE, down: 100, up: 20, price: 75, setup: 0, modem: { offer: "byo" } };
const mB = { ...mA, id: "mB", provider: "B", price: 25 }, mC = { ...mA, id: "mC", provider: "C", price: 20, data_gb: 40 };
const hhLines = [{ dataGB: 30 }, { dataGB: 45 }];
let hh = E.household({ internet: [iA, iB], lines: hhLines, mobile: [mA, mB, mC], months: 12 });
ok(near(hh.independent.total, 900 + 20 * R + 25 * R), `independent: cheapest internet + cheapest plan per line = $${hh.independent.total.toFixed(2)}`);
ok(hh.best === hh.independent, "A's $10 internet bundle isn't worth moving a line to A's dearer SIM");
hh = E.household({ internet: [iA, iB], lines: hhLines, mobile: [mA, mB, mC], months: 12, rules: { A: [{ applies_to: "mobile", with: "internet", pct: 10 }] } });
ok(hh.best.provider === "A" && near(hh.best.total, 840 + 20 * R + 0.9 * 30 * R) && hh.best.lines.map(l => l.p.id).join(",") === "mC,mA",
  `with 10% off A's SIM too: A internet + line 2 on A = $${hh.best.total.toFixed(2)} (${hh.best.lines.map(l => l.p.id)})`);
const singleA = hh.singles.find(x => x.provider === "A");
ok(singleA && near(singleA.total, 840 + 2 * 0.9 * 30 * R), `everything with A: $${singleA && singleA.total.toFixed(2)}`);
const mBonly = { ...mA, id: "mBonly", provider: "B", price: 10, requires: "internet" };
ok(!E.mobileCost(mBonly, { dataGB: 10 }).ok && E.mobileCost(mBonly, { dataGB: 10 }, { with: ["internet"] }).ok, "a plan only sold with internet needs that internet");
hh = E.household({ internet: [iA, iB], lines: hhLines, mobile: [mA, mB, mC, mBonly], months: 12 });
ok(hh.best.provider === "B" && hh.best.internetWithP && hh.best.lines.every(l => l.p.id === "mBonly"),
  `B's internet-only SIM ($10) wins only together with B's internet (${hh.best.provider}: ${hh.best.lines.map(l => l.p.id)})`);
ok(hh.lines[0].every(x => !x.p.requires), "bundle-only plans aren't offered for a line on its own");
hh = E.household({ internet: [{ ...iB, bundle: [{ with: "energy", off: 15 }] }], lines: [], mobile: [], months: 12, energy: "B" });
ok(near(hh.independent.total, 60 * 12), "energy bundle applies when your energy retailer is the internet provider");

// --- Phones ---------------------------------------------------------------------------------
const PH = [
  { id: "apple-x-128-outright", provider: "apple", handset: "brand-x", brand: "Brand", model: "X", storage_gb: 128, outright: 1200 },
  { id: "tel-x-128-24m", provider: "tel", handset: "brand-x", brand: "Brand", model: "X", storage_gb: 128, term: 24, monthly: 50, plans: ["tel-ess"],
    discounts: [{ off: 240, text: "$240 off on Essential", plans: ["tel-ess"] }], credits: [{ per_month: 10, months: 12, text: "Trade-in credit", requires_trade_in: true }] },
  { id: "tel-x-256-24m", provider: "tel", handset: "brand-x", brand: "Brand", model: "X", storage_gb: 256, term: 24, monthly: 60 },
];
const TELESS = { id: "tel-ess", provider: "tel", network: "telstra", type: "postpaid", period_days: 30, price: 84, data_gb: 180, data_only: false };
const SIMC = { id: "c-sim", provider: "c", network: "optus", type: "prepaid", period_days: 30, price: 20, data_gb: 50, data_only: false };
const R24 = 24 * 365.25 / 12 / 30;
let po = E.phoneOptions({ handset: "brand-x", storage: 128, term: 24, line: { dataGB: 30 }, phones: PH, mobile: [TELESS, SIMC] });
ok(po[0].kind === "outright" && near(po[0].total, 1200 + 20 * R24), `outright $1200 + cheapest SIM over 24 months = $${po[0].total.toFixed(2)}`);
const rp = po.find(x => x.kind === "repay");
ok(rp && near(rp.total, 84 * R24 + 1200 - 240), `carrier: Essential plan + $50 x 24 - $240 = $${rp && rp.total.toFixed(2)}`);
po = E.phoneOptions({ handset: "brand-x", storage: 128, term: 24, line: { dataGB: 30 }, phones: PH, mobile: [TELESS, SIMC], tradeIn: true });
ok(near(po.find(x => x.kind === "repay").total, 84 * R24 + 1200 - 240 - 120), "trade-in credit counts only with a trade-in");
po = E.phoneOptions({ handset: "brand-x", storage: 256, term: 24, line: { dataGB: 30 }, phones: PH, mobile: [TELESS, SIMC] });
ok(po[0].kind === "outright" && near(po[0].deviceGross, 1440) && po[0].flags.length, "no outright listing: outright price from the full repayment total");
ok(E.phoneOptions({ handset: "brand-x", storage: 128, term: 36, line: { dataGB: 30 }, phones: PH, mobile: [TELESS, SIMC] }).every(x => x.kind === "outright"),
  "repayment offers only for the chosen term");
const cat = E.handsetCatalogue(PH);
ok(cat.length === 1 && cat[0].storages.join(",") === "128,256" && cat[0].terms.join(",") === "24", "catalogue groups storage sizes and terms per handset");

// --- Mobile -----------------------------------------------------------------------------
const p28 = { id: "m28", network: "optus", type: "prepaid", period_days: 28, price: 35, data_gb: 42, data_only: false, intl: ["NZ", "GB"] };
let mc = E.mobileCost(p28, { dataGB: 30 }, { months: 12 });
ok(near(mc.total, 35 * 365.25 / 28) && mc.ok, `28-day $35 plan over 12 months = 13.04 recharges = $${mc.total.toFixed(2)}`);
ok(near(mc.monthlyGB, 42 * 365.25 / 12 / 28), "28-day allowance converted to a monthly equivalent");
mc = E.mobileCost(p28, { dataGB: 50 });
ok(!mc.ok && /less than/.test(mc.why[0]), "too little data is rejected");
ok(!E.mobileCost(p28, { dataGB: 10, networks: ["telstra"] }).ok, "network preference is enforced");
ok(!E.mobileCost(p28, { dataGB: 10, intl: ["IN"] }).ok && E.mobileCost(p28, { dataGB: 10, intl: ["NZ"] }).ok, "international call countries are checked");
const p365 = { id: "y", network: "telstra", type: "prepaid", period_days: 365, price: 289, data_gb: 300, data_only: false };
ok(near(E.mobileCost(p365, { dataGB: 20 }, { months: 12 }).total, 289 * 365.25 / 365), "365-day plan over 12 months is one recharge");
ok(near(E.mobileCost(p365, { dataGB: 20 }, { months: 24 }).total, 2 * 289 * 365.25 / 365), "and two over 24 months");
const promoPlan = { ...p28, promo: { price: 10, periods: 3 } };
ok(near(E.mobileCost(promoPlan, { dataGB: 10 }).total, 3 * 10 + (365.25 / 28 - 3) * 35), "first 3 recharges at the promo price");
ok(!E.mobileCost({ ...p28, data_only: true }, { dataGB: 1 }).ok, "data-only plans don't suit a phone line");
ok(E.mobileCost({ ...p28, data_gb: -1 }, { dataGB: 500 }).ok, "unlimited data satisfies any need");

// --- 2. Built data ----------------------------------------------------------------------
const dataFile = path.join(__dirname, "..", "site", "data", "plans.js");
if (fs.existsSync(dataFile)) {
  const ctx = { window: {} }; vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(dataFile, "utf8"), ctx);
  const D = ctx.window.TELCO_DATA;
  ok(D.internet.length > 100 && D.mobile.length > 100, `built data has ${D.internet.length} internet and ${D.mobile.length} mobile plans`);
  ok(D.internet.every(p => D.providers[p.provider]) && D.mobile.every(p => D.providers[p.provider]), "every plan's provider is named");
  ok(D.internet.filter(p => p.kind === "nbn").every(p => E.NBN_TIERS.includes(p.tier)), "every NBN plan has a known tier");
  ok(D.internet.every(p => !p.promo || p.promo.price < p.price), "promo prices are below ongoing prices");
  ok(D.meta.sources.some(s => s.attribution), "source attribution is carried through to the site");
  const tiers = new Set(D.internet.filter(p => p.kind === "nbn").map(p => p.tier));
  ok([25, 50, 100, 500, 1000].every(t => tiers.has(t)), "main NBN tiers are all present");
  const nets = new Set(D.mobile.map(p => p.network));
  ok(["telstra", "optus", "vodafone"].every(x => nets.has(x)), "plans on all three mobile networks");
  const costs = D.internet.filter(p => p.kind === "nbn" && p.tier === 100).map(p => E.internetCost(p, { months: 12 }).total);
  ok(costs.every(x => x > 120 && x < 3000), `NBN 100 first-year costs within sane bounds ($${Math.min(...costs).toFixed(0)}-$${Math.max(...costs).toFixed(0)})`);
} else {
  console.log("SKIP built-data checks (run tools/build_data.py first)");
}

console.log(fails ? `\n${fails} FAILED` : "\nall passed");
process.exit(fails ? 1 : 0);

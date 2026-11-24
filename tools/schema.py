"""Normalised record schema for the site's plan data, with per-record validation.

Internet plan (one per plan per provider):
  id            str    unique, "<provider>-<slug>"
  provider      str    provider id (providers.toml)
  name          str    plan name as published
  kind          str    nbn | fixed_wireless | satellite | 5g | starlink | private
  tier          int?   nominal NBN tier (12 ... 2000); None for non-NBN kinds where unknown
  techs         [str]  connection types it works on (fttp, hfc, fttc, fttn, fttb, fw, sat)
  down, up      float? published download/upload speed in Mbps (typical evening where given)
  price         float  ongoing monthly price incl. GST
  promo         {price, months, until, text, requires?}?  intro price for the first `months`
                months; `until` = last sign-up date (ISO date) when known; requires = "energy" |
                "mobile" when the offer is only for customers who also take that service
  setup         float  one-off setup/connection fee (adapters may emit None when it isn't
                published; the build fills it from Bill Hero or 0 before validating)
  contract      int    minimum term in months (0 = no lock-in)
  modem         {offer, cost, fee?, months?, monthly?}  offer: byo | included | included_contract |
                purchase | rental | unknown; cost = one-off price (to buy it, or postage for a
                rental); monthly = rental per month; for included_contract, fee = what you pay if
                you leave (or don't return it) within `months`
  data_gb       float? monthly allowance; None = unlimited
  network       str?   host mobile network for kind 5g (telstra | optus | vodafone)
  credit        float? one-off sign-up bill credit (counted only if the user opts in)
  bundle        [{with, off, text, during_promo?}]  monthly discount when bundled with "mobile" or
                "energy"; it applies after any intro offer unless during_promo is true
  url, cis_url  str?
  source        str    adapter that produced it (billhero, amaysim, override, ...)
  captured      str    ISO time the source data was captured
  verified      bool   True when it comes from the provider itself or a checked override
  notes         str?   conditions worth showing (coupon needed, new customers only, ...)

Mobile plan:
  id, provider, name, source, captured, verified, url   as above
  network       str?   telstra | optus | vodafone (host network)
  type          str    postpaid | prepaid
  period_days   int    recharge/billing period: 30 (monthly), 28, 7, 30-365 for long expiry
  price         float  price per period incl. GST
  data_gb       float? data per period; None = unknown; -1 = unlimited
  data_only     bool   tablet/hotspot data plan with no voice
  calls         str    unlimited | limited | none | unknown
  five_g        bool?
  intl          [str]? ISO country codes with included international calls
  promo         {price, periods, until, text, requires?}?  intro price for the first `periods`
                recharges; requires = "internet" | "energy" when only bundled customers get it
  contract      int    months
  rollover      bool?  unused data carries over (or banks) to later periods
  bundle        [{with, off, text, during_promo?}]  $ per period off this SIM when you also take
                the provider's "internet" or "energy"
  credit        float? one-off sign-up credit
  cis_url       str?
  requires      str?   "internet" | "energy" when the plan is only sold with that service
Account-level discounts (extra lines, family plans) live in overrides/bundles.toml, not here.
"""

KINDS = {"nbn", "fixed_wireless", "satellite", "5g", "starlink", "private"}
TECHS = {"fttp", "hfc", "fttc", "fttn", "fttb", "fw", "sat"}
MODEM = {"byo", "included", "included_contract", "purchase", "rental", "unknown"}
NETWORKS = {"telstra", "optus", "vodafone", None}
CALLS = {"unlimited", "limited", "none", "unknown"}

BOUNDS = {"internet_price": (10, 500), "mobile_month": (1, 250)}


def _num(v, nullable=False):
    return (v is None and nullable) or (isinstance(v, (int, float)) and not isinstance(v, bool))


def _common(r, errs):
    for k in ("id", "provider", "name", "source", "captured"):
        if not isinstance(r.get(k), str) or not r.get(k):
            errs.append(f"missing {k}")
    if not isinstance(r.get("verified"), bool):
        errs.append("verified must be bool")
    if not _num(r.get("price")):
        errs.append("price must be a number")
    if not isinstance(r.get("contract"), int):
        errs.append("contract must be int months")


def check_internet(r):
    errs = []
    _common(r, errs)
    if r.get("kind") not in KINDS:
        errs.append(f"bad kind {r.get('kind')}")
    if not set(r.get("techs") or []) <= TECHS:
        errs.append(f"bad techs {r.get('techs')}")
    for k in ("down", "up", "tier"):
        if not _num(r.get(k), nullable=True) or (r.get(k) is not None and r[k] <= 0):
            errs.append(f"bad {k} {r.get(k)}")
    if r.get("kind") == "nbn" and not r.get("tier"):
        errs.append("nbn plan without tier")
    lo, hi = BOUNDS["internet_price"]
    if _num(r.get("price")) and not lo <= r["price"] <= hi:
        errs.append(f"price {r['price']} outside {lo}-{hi}")
    p = r.get("promo")
    if p is not None:
        if not (_num(p.get("price")) and isinstance(p.get("months"), int) and 1 <= p["months"] <= 24):
            errs.append(f"bad promo {p}")
        elif _num(r.get("price")) and p["price"] >= r["price"]:
            errs.append(f"promo price {p['price']} not below ongoing {r['price']}")
    if not _num(r.get("setup")) or r["setup"] < 0:
        errs.append("bad setup")
    m = r.get("modem") or {}
    if m.get("offer") not in MODEM or not _num(m.get("cost"), nullable=True):
        errs.append(f"bad modem {m}")
    elif m.get("offer") == "rental" and not (_num(m.get("monthly")) and m["monthly"] > 0):
        errs.append(f"rental modem without a monthly price {m}")
    if not _num(r.get("data_gb"), nullable=True):
        errs.append("bad data_gb")
    if r.get("network") not in NETWORKS:
        errs.append(f"bad network {r.get('network')}")
    if not _num(r.get("credit"), nullable=True) or (r.get("credit") or 0) < 0:
        errs.append(f"bad credit {r.get('credit')}")
    for b in r.get("bundle") or []:
        if b.get("with") not in ("mobile", "energy") or not _num(b.get("off")):
            errs.append(f"bad bundle {b}")
    return errs


def check_mobile(r):
    errs = []
    _common(r, errs)
    if r.get("network") not in NETWORKS:
        errs.append(f"bad network {r.get('network')}")
    if r.get("type") not in ("postpaid", "prepaid"):
        errs.append(f"bad type {r.get('type')}")
    pd = r.get("period_days")
    if not isinstance(pd, int) or not 1 <= pd <= 366:
        errs.append(f"bad period_days {pd}")
    elif _num(r.get("price")):
        month = r["price"] * 30.4375 / pd
        lo, hi = BOUNDS["mobile_month"]
        if not lo <= month <= hi:
            errs.append(f"monthly-equivalent price {month:.2f} outside {lo}-{hi}")
    d = r.get("data_gb")
    if not (d is None or d == -1 or (_num(d) and d >= 0)):
        errs.append(f"bad data_gb {d}")
    if r.get("calls") not in CALLS:
        errs.append(f"bad calls {r.get('calls')}")
    if not isinstance(r.get("data_only"), bool):
        errs.append("data_only must be bool")
    if r.get("requires") not in (None, "internet", "energy"):
        errs.append(f"bad requires {r.get('requires')}")
    if r.get("rollover") not in (None, True, False):
        errs.append(f"bad rollover {r.get('rollover')}")
    if not _num(r.get("credit"), nullable=True) or (r.get("credit") or 0) < 0:
        errs.append(f"bad credit {r.get('credit')}")
    for b in r.get("bundle") or []:
        if b.get("with") not in ("internet", "energy") or not _num(b.get("off")):
            errs.append(f"bad bundle {b}")
    intl = r.get("intl")
    if intl is not None and not (isinstance(intl, list) and all(isinstance(c, str) and len(c) == 2 and c.isupper() for c in intl)):
        errs.append(f"intl must be a list of ISO 3166 alpha-2 codes, got {intl}")
    p = r.get("promo")
    if p is not None:
        if not (_num(p.get("price")) and isinstance(p.get("periods"), int) and p["periods"] >= 1):
            errs.append(f"bad promo {p}")
        elif _num(r.get("price")) and p["price"] >= r["price"]:
            errs.append(f"promo price {p['price']} not below ongoing {r['price']}")
    return errs

"""Optus: phones on interest-free OptusPay device payments (12, 24 or 36 months) and outright prices.

Sources (robots.txt allows both; it disallows only /checkout/, */promotions, */mobile/Landing-Pages
and a few legacy paths):
  https://www.optus.com.au/mobile/phones
      The phone listing. Its device-listing component has a JSON `datamodel` attribute with one
      card per phone: brand, deviceName, masterProductId, detailLink, price ("Device payments
      from", after device credits, on the default 36 months), productBadge ("Save $500"),
      internalMemory and applicableCl. It doesn't carry per-storage or per-term prices.
  https://www.optus.com.au/mobile/phones/<brand>/<model>   (one per phone)
      The phone page's product component `datamodel` carries, per variant (mecId) and payment
      option (36, 24, 12, outright), oldDeviceMonthly (repayment before credits), deviceMonthly,
      deviceDiscount (device credit a month) and totalCost (outright). The capacity and colour
      swatches map mecIds to storage. discountOfferLabelBelowPrice holds the offer wording
      ("Save ... off RRP .... Ends 6/12/26." or "Available until withdrawn."). The plan carousel on
      the page lists the plans the phone can be bought with (Promo Plan, Small/Medium/Large Choice
      Plus).
  The page's own JavaScript calls a keyed catalogue API (gateway.optus.com.au); it isn't used.

Request budget: the listing plus at most MAX_PAGES phone pages a run (10 requests). The catalogue
has about 25 phones, so each run refreshes the phones that need it most and carries the rest over
from the previous output (data-raw/normalised/optus_phones.json, else the published
site/data/plans.json), keeping each record's own `captured` time. Priority: phones with no data
yet; phones whose listing card changed (from-price or storage sizes); phones with an offer past its
end date; then the oldest. Carried-over records older than MAX_AGE_DAYS are dropped.

Notes on the content:
  - Optus device discounts are monthly device credits for the whole term ("If you cancel, any
    device credits will not apply to any remaining amount outstanding"), so they go in `credits`,
    and `monthly` is the repayment before credits. The page's minimum cost confirms this: the
    full device price less one month's credit.
  - Optus outright prices are the RRP spread exactly over 36 months (e.g. $1,998.72).
  - The page also carries many hidden terms blocks from expired campaigns, so offers are read only
    from the product component, never from page-wide text.
  - Plan-fee offers on the phone page (e.g. "$39/month for a year on Small") are the SIM-only
    plans' own promos, already in optus_mobile; they aren't repeated here.
"""
import html
import json
import re
import sys
import pathlib
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import NORM, RAW, SITE_DATA, fetch, now_iso, slug, write_norm  # noqa: E402
from schema import check_phone  # noqa: E402

PID = "optus"
STEM = "optus_phones"
BASE = "https://www.optus.com.au"
LIST_URL = BASE + "/mobile/phones"
MAX_PAGES = 9                    # phone pages per run (plus the listing = 10 requests)
MAX_AGE_DAYS = 7                 # drop carried-over records older than this
AEST = timezone(timedelta(hours=10))
# robots.txt (User-agent: *): prefixes, and "*/..." patterns that match anywhere in the path.
DISALLOWED = ("/checkout/", "/notices/superreview", "/notices/former-7employee_9verifica_tion1/",
              "/portal/site/shop/template.PAGE/onepageshoppingcart",
              "/portal/site/shop/template.PAGE/onepagepordercapture", "/opfiles/OnePortal/", "/vgn-ext-templating/")
DISALLOWED_ANYWHERE = ("/Promotions", "/promotions", "/mobile/Landing-Pages")
# Voice plans (ids from optus_mobile), used if a phone page's plan carousel can't be read.
PLANS = ["optus-mobile-promo-plan", "optus-mobile-small-choice-plus-plan",
         "optus-mobile-medium-choice-plus-plan", "optus-mobile-large-choice-plus-plan"]

# Handset keys the site compares (shared with the other phone adapters).
CATALOGUE = [
    "apple-iphone-18-pro", "apple-iphone-18-pro-max", "apple-iphone-duo", "apple-iphone-air",
    "apple-iphone-17", "apple-iphone-17e", "apple-iphone-17-pro", "apple-iphone-17-pro-max",
    "samsung-galaxy-s26", "samsung-galaxy-s26-plus", "samsung-galaxy-s26-ultra", "samsung-galaxy-s26-fe",
    "samsung-galaxy-z-fold8", "samsung-galaxy-z-flip8", "samsung-galaxy-z-fold8-ultra",
    "samsung-galaxy-a17", "samsung-galaxy-a37", "samsung-galaxy-a57",
    "google-pixel-11", "google-pixel-11-pro", "google-pixel-11-pro-xl", "google-pixel-11-pro-fold",
    "google-pixel-10a",
    "motorola-moto-g57",             # budget model Optus features
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a page that moves is reported, not followed (it might lead into a
    robots-disallowed path such as a */promotions page)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"redirect to {newurl} refused", headers, fp)


urllib.request.install_opener(urllib.request.build_opener(NoRedirect))


def allowed(url):
    path = re.sub(r"^https?://[^/]+", "", url)
    return (url.startswith(BASE + "/") and not any(path.startswith(d) for d in DISALLOWED)
            and not any(d in path for d in DISALLOWED_ANYWHERE))


def text(s):
    if s is None:
        return ""
    s = html.unescape(html.unescape(s if isinstance(s, str) else json.dumps(s)))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s).replace("​", "")).strip()


def display_model(name):
    """Model name for display: as marketed, without a network suffix ("Galaxy A37 5G" -> "Galaxy A37")."""
    return re.sub(r"\s+5G$", "", re.sub(r"\s+", " ", name).strip(), flags=re.I)


def handset_key(brand, model):
    """Shared model key: slug of "<brand> <model>", '+' spelled 'plus', no 5G suffix."""
    return slug(f"{brand} {display_model(model).replace('+', ' Plus')}")


def storage_gb(s):
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|TB)\s*", s or "", re.I)
    if not m:
        return None
    return int(round(float(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)))


def num(v):
    try:
        return float(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def fmt(v):
    return f"${v:,.2f}".replace(".00", "")


def end_date(t, today):
    """'Ends 6/12/26', 'Offer ends 06/12/2026' or 'Ends 6/12.' (no year: the next such date)."""
    m = re.search(r"(?i)ends? (\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t or "")
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    if m.group(3):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
    else:
        y = today.year if (mo, d) >= (today.month, today.day) else today.year + 1
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def datamodels(page):
    for raw in re.findall(r'\sdatamodel="(\{.*?\})"', page, re.S):
        try:
            d = json.loads(html.unescape(raw))
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def parse_listing(page):
    """Listing cards (postpaid phones) in page order."""
    for d in datamodels(page):
        if isinstance(d.get("cards"), list) and "sfccApiUrl" in d:
            return [c for c in d["cards"] if isinstance(c, dict) and c.get("deviceName") and c.get("brand")
                    and not c.get("prepaid")], str(d.get("defaultContractLength") or "36")
    return [], "36"


def card_changed(card, recs, term):
    """True when the listing card's from-price (after credits, default term) no longer matches
    what earlier records for this phone imply. Storage lists aren't compared: the listing can
    name sizes the phone page doesn't sell (e.g. iPhone Air 256GB)."""
    shown = num(card.get("price"))
    lows = [r["monthly"] - sum(c["per_month"] for c in r.get("credits") or [])
            for r in recs if r.get("term") == term and r.get("monthly") is not None]
    return shown is not None and bool(lows) and abs(shown - round(min(lows), 2)) > 0.011


def parse_phone(page, card, key, url, captured, today, warnings):
    """Records for one phone page (every storage x payment option)."""
    prod = next((d for d in datamodels(page) if "ProductPrice" in d and "ProductVariant" in d), None)
    if not prod:
        warnings.append(f"{key}: no product component on {url}")
        return []
    pv, pp = prod.get("ProductVariant") or {}, prod.get("ProductPrice") or {}
    cap = {b.get("btn_id"): b.get("value") for b in ((pv.get("capacitySwatch") or {}).get("radio_btns") or [])}
    if not cap and len(card.get("internalMemory") or []) == 1:
        only = card["internalMemory"][0]
        cap = {p.get("mecId"): only for c in pp.get("pricePerContract") or [] for p in c.get("productPriceModels") or []}
    label = text(pp.get("discountOfferLabelBelowPrice")) or text(pp.get("discountOfferLabelAbovePrice"))
    until = None if re.search(r"(?i)until withdrawn", label) else end_date(label, today)
    stock = " or while stock lasts" if re.search(r"(?i)while stock lasts", label) else ""
    plans = []
    for d in datamodels(page):
        if "planId" in d and "nonDiscountedPlanPrice" in d and not d.get("isPrepaid"):
            pid = f"{PID}-mobile-{slug(text(d.get('title')))}"
            if pid not in plans:
                plans.append(pid)
    if not plans:
        warnings.append(f"{key}: no plan carousel on the page; used the standard plan list")
        plans = list(PLANS)

    price = defaultdict(list)        # (storage label, contract) -> price models across colours
    for c in pp.get("pricePerContract") or []:
        cl = str(c.get("contractLength") or "").lower()
        for p in c.get("productPriceModels") or []:
            st = cap.get(p.get("mecId"))
            if st and storage_gb(st):
                price[(st, cl)].append(p)
            if p.get("planDiscount") not in (None, 0, 0.0, "", {}):
                warnings.append(f"{key}: plan discount on the phone page not parsed: {p.get('planDiscount')}")

    def agree(vals, what):
        c = Counter(v for v in vals if v is not None)
        if not c:
            return None
        if len(c) > 1:
            warnings.append(f"{key} {what}: colours disagree {dict(c)}; used the most common")
        return c.most_common(1)[0][0]

    base = ["Interest-free OptusPay device payments with an eligible Optus postpaid plan.",
            "If you cancel or move to an ineligible plan during the term, device credits stop and the "
            "remaining device balance is payable without them."]
    out = []
    for st in sorted({s for s, _ in price}, key=storage_gb):
        gb = storage_gb(st)
        outright = agree([num(p.get("totalCost")) or num(p.get("price")) for p in price.get((st, "outright"), [])],
                         f"{st} outright")
        terms = sorted(int(cl) for s, cl in price if s == st and cl.isdigit())
        for term in terms:
            ps = price[(st, str(term))]
            credit = agree([num(p.get("deviceDiscount")) or 0.0 for p in ps], f"{st} {term}m credit") or 0.0
            monthly = agree([num(p.get("oldDeviceMonthly")) or
                             ((num(p.get("deviceMonthly")) or 0) + (num(p.get("deviceDiscount")) or 0)) for p in ps],
                            f"{st} {term}m")
            if not monthly:
                continue
            credits = []
            if credit > 0.004:
                total = round(credit * term, 2)
                was = agree([num(p.get("oldTotalRepaymentCharges")) for p in ps], f"{st} {term}m RRP") or round(monthly * term, 2)
                credits.append({
                    "per_month": round(credit, 2), "months": term, "plans": None, "requires_trade_in": False,
                    "until": until,
                    "text": f"Save {fmt(total)} off RRP {fmt(was)}: {fmt(credit)}/mth device credit for {term} months"
                            + (f"; ends {until}{stock}" if until else "; until withdrawn" if "withdrawn" in label.lower() else stock)
                            + ".",
                })
            out.append({
                "id": f"{PID}-{key}-{slug(st)}-{term}m", "provider": PID, "handset": key,
                "brand": card["brand"], "model": display_model(card["deviceName"]), "storage_gb": gb,
                "outright": outright, "term": term, "monthly": round(monthly, 2),
                "discounts": [], "credits": credits, "plans": list(plans),
                "url": url, "source": STEM, "captured": captured, "verified": True, "notes": " ".join(base),
            })
        if not terms and outright:
            out.append({
                "id": f"{PID}-{key}-{slug(st)}-outright", "provider": PID, "handset": key,
                "brand": card["brand"], "model": display_model(card["deviceName"]), "storage_gb": gb,
                "outright": outright, "term": None, "monthly": None, "discounts": [], "credits": [],
                "plans": None, "url": url, "source": STEM, "captured": captured, "verified": True,
                "notes": "Outright only.",
            })
    return out


def previous_records():
    """Last run's output, else the published data: handset -> records from this adapter."""
    for path, pick in ((NORM / f"{STEM}.json", lambda d: d.get("phones") or []),
                       (SITE_DATA / "plans.json", lambda d: [r for r in d.get("phones") or [] if r.get("source") == STEM])):
        try:
            recs = pick(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
        if recs:
            out = defaultdict(list)
            for r in recs:
                out[r["handset"]].append(r)
            return out, path.name
    return {}, None


def main():
    raw = RAW / STEM
    captured = now_iso()
    now = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    today = now.astimezone(AEST).date()
    page = fetch(LIST_URL, raw / "phones.html", min_interval=2.0, retries=2).decode("utf-8", "replace")
    cards, default_cl = parse_listing(page)
    if not cards:
        raise RuntimeError("Optus phone listing parsed to zero cards; page layout may have changed")

    wanted, warnings = {}, []
    for c in cards:
        key = handset_key(c["brand"], c["deviceName"])
        if key in CATALOGUE and key not in wanted and (c.get("detailLink") or "").startswith("/mobile/phones/"):
            wanted[key] = c
    missing = [k for k in CATALOGUE if k not in wanted]
    unlisted = [handset_key(c["brand"], c["deviceName"]) for c in cards[:20]
                if handset_key(c["brand"], c["deviceName"]) not in CATALOGUE]   # first 20 cards are the newest/featured

    prev, prev_from = previous_records()
    term0 = int(default_cl) if default_cl.isdigit() else 36

    def priority(key):
        recs = prev.get(key) or []
        if not recs:
            return (0, "")
        oldest = min(r["captured"] for r in recs)
        if card_changed(wanted[key], recs, term0):
            return (1, oldest)
        ends = [x.get("until") for r in recs for x in (r.get("credits") or []) + (r.get("discounts") or [])]
        if any(u and u < today.isoformat() for u in ends):
            return (2, oldest)
        return (3, oldest)

    rank = {k: i for i, k in enumerate(wanted)}          # listing order: Optus features its popular phones first
    order = sorted(wanted, key=lambda k: (priority(k), rank[k]))
    to_fetch = order[:MAX_PAGES]
    phones, refreshed, carried, failed = [], [], {}, []
    for key in to_fetch:
        c = wanted[key]
        url = BASE + c["detailLink"]
        if not allowed(url):
            warnings.append(f"{key}: {url} is disallowed by robots.txt; not fetched")
            failed.append(key)
            continue
        try:
            body = fetch(url, raw / f"{key}.html", min_interval=2.0, retries=2).decode("utf-8", "replace")
            recs = parse_phone(body, c, key, url, captured, today, warnings)
        except Exception as e:
            warnings.append(f"{key}: {url}: {e}")
            recs = []
        if recs:
            phones += recs
            refreshed.append(key)
        else:
            failed.append(key)
    if to_fetch and not refreshed:
        raise RuntimeError(f"optus_phones: none of the {len(to_fetch)} phone pages parsed; page layout may have changed")

    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).isoformat().replace("+00:00", "Z")
    for key in wanted:
        if key in refreshed:
            continue
        recs = [r for r in prev.get(key) or [] if r["captured"] >= cutoff]
        if recs:
            phones += recs
            carried[key] = min(r["captured"] for r in recs)
        elif prev.get(key):
            warnings.append(f"{key}: previous records older than {MAX_AGE_DAYS} days dropped")
    pending = [k for k in wanted if k not in refreshed and k not in carried]

    rejected = []                    # e.g. 2TB models on 12 months: over the schema's sanity bounds
    for r in list(phones):
        errs = check_phone(r)
        if errs:
            rejected.append(f"{r['id']}: {'; '.join(errs)}")
            phones.remove(r)
    if not phones:
        raise RuntimeError("optus_phones: no handset variants parsed")
    ids = [r["id"] for r in phones]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"optus_phones: duplicate ids {[i for i, n in Counter(ids).items() if n > 1]}")
    phones.sort(key=lambda r: (CATALOGUE.index(r["handset"]), r["storage_gb"], r["term"] or 0))
    for w in warnings + [f"left out (fails schema check): {x}" for x in rejected]:
        print(f"optus_phones: warning: {w}", file=sys.stderr)
    meta = {"name": "Optus phones on device payments (listing + phone pages)", "url": LIST_URL,
            "urls": [LIST_URL] + [BASE + wanted[k]["detailLink"] for k in to_fetch], "fetched": captured,
            "refreshed": refreshed, "carried_over": carried, "carried_from": prev_from if carried else None,
            "pending": pending, "failed": failed, "catalogue_missing": missing, "featured_not_in_catalogue": unlisted,
            "warnings": warnings, "rejected": rejected}
    write_norm(STEM, {"internet": [], "mobile": [], "phones": phones}, meta)
    print(f"optus_phones: {len(phones)} listings; refreshed {len(refreshed)} phones, carried over {len(carried)}"
          + (f", still to fetch {len(pending)}" if pending else "")
          + (f"; not sold by Optus: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()

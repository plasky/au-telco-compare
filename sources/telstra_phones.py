"""Telstra: phones on interest-free device repayments (12, 24 or 36 months) and their outright prices.

Sources (robots.txt allows all of them for all user agents; it disallows /mobile-phones/product-
catalogue/, /products/, /mobile/mobiles/ and /search, none of which are used):
  https://www.telstra.com.au/mobile-phones/mobiles-on-a-plan
      The phone grid. Each server-rendered card is <li class="tcom-device-grid__product-card"
      id="MHDWHST-..." data-mobile-device-brand=... data-mobile-device-name=...> with a link to the
      phone's page. The cards are the phones on sale now; they give the brand and page URL.
  https://www.telstra.com.au/content/experience-fragments/explore/servlet/grid.devices.mobiles.hardware.handset.json
      The grid's data feed, named by the section's data-device-grid-json-path attribute. One row
      per id x colour x storage x payment option: numberOfRepayments ("12" | "24" | "36" |
      "Outright"), recurringCharge (repayment a month), oneOffCharge (outright price), and for
      discounted rows discountText ("Black Friday Deal", "Clearance"),
      recurringChargeBeforePromo / oneOffChargeBeforePromo. hasTargetedBTLPromo marks a phone with
      a targeted offer shown only to some customers (not public, so not counted).
  One phone page per discount campaign (at most MAX_PAGES), for the campaign's end date: the page
      carries <div data-promo-name="Black Friday Deal" data-promo-productCode="MHDWHST-..."
      data-promo-end-date-time="2026-11-30T23:59:00+1100" data-promo-totalSavings=...>.

Notes on the content:
  - Telstra's device discounts lower the repayments for the whole term (totalSavings = monthly
    saving x term), and "device discounts still apply to cancelled orders bought on repayment",
    so they are one-off discounts (`discounts`), not bill credits. `monthly` is the repayment
    before the discount.
  - A discount can also lower the outright price; `outright` is the price to buy it outright now.
  - Repayments need a voice Upfront Mobile plan (Basic, Essential or Premium); the Upfront data
    plans are for tablets and modems. Leaving or moving to an ineligible plan during the term
    makes the remaining device balance payable in full.
  - Gift-type extras on phone pages (subscription trials) are not money off and are left out.
  - The handset list is CATALOGUE below (the site's ~25 popular models). Phones Telstra sells
    that aren't in it are listed in meta.unlisted_new so new launches can be added.
"""
import html
import json
import re
import sys
import pathlib
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402
from schema import check_phone  # noqa: E402

PID = "telstra"
STEM = "telstra_phones"
BASE = "https://www.telstra.com.au"
LIST_URL = BASE + "/mobile-phones/mobiles-on-a-plan"
FEED_URL = BASE + "/content/experience-fragments/explore/servlet/grid.devices.mobiles.hardware.handset.json"
MAX_PAGES = 4                        # phone pages fetched per run for campaign end dates
# robots.txt (User-agent: *) disallows these; nothing under them is requested, and redirects are
# refused (see NoRedirect) so a moved page can't lead into them.
DISALLOWED = ("/forms", "/mobile/mobiles/", "/uberprod", "/idc", "/misc/mobile-site/", "/styleguide",
              "/mobile-phones/product-catalogue/", "/small-business/product-catalogue/", "/products/",
              "/search", "/content/tcom/tplus/", "/tplus", "/aboutus/media/jump-page")
AEST = timezone(timedelta(hours=10))
# Voice Upfront Mobile plans (ids from telstra_mobile); a phone on repayments needs one of these.
PLANS = ["telstra-mobile-basic", "telstra-mobile-essential", "telstra-mobile-premium"]

# Handset keys the site compares (shared with the other phone adapters).
CATALOGUE = [
    "apple-iphone-18-pro", "apple-iphone-18-pro-max", "apple-iphone-duo", "apple-iphone-air",
    "apple-iphone-17", "apple-iphone-17e", "apple-iphone-17-pro", "apple-iphone-17-pro-max",
    "samsung-galaxy-s26", "samsung-galaxy-s26-plus", "samsung-galaxy-s26-ultra", "samsung-galaxy-s26-fe",
    "samsung-galaxy-z-fold8", "samsung-galaxy-z-flip8", "samsung-galaxy-z-fold8-ultra",
    "samsung-galaxy-a17", "samsung-galaxy-a37", "samsung-galaxy-a57",
    "google-pixel-11", "google-pixel-11-pro", "google-pixel-11-pro-xl", "google-pixel-11-pro-fold",
    "google-pixel-10a",
    "motorola-moto-g67",             # budget model Telstra features
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a page that moves is reported, not followed (it might lead into a
    robots-disallowed path such as /mobile-phones/product-catalogue/)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"redirect to {newurl} refused", headers, fp)


urllib.request.install_opener(urllib.request.build_opener(NoRedirect))


def allowed(url):
    path = re.sub(r"^https?://[^/]+", "", url)
    return url.startswith(BASE + "/") and not any(path.startswith(d) for d in DISALLOWED) and "bvstate" not in path


def display_model(name):
    """Model name for display: as marketed, without a network suffix ("Galaxy A17 5G" -> "Galaxy A17")."""
    return re.sub(r"\s+5G$", "", re.sub(r"\s+", " ", name).strip(), flags=re.I)


def handset_key(brand, model):
    """Shared model key: slug of "<brand> <model>", '+' spelled 'plus', no 5G suffix."""
    m = display_model(model).replace("+", " Plus")
    return slug(f"{brand} {m}")


def storage_gb(s):
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|TB)\s*", s or "", re.I)
    if not m:
        return None                  # e.g. "128MB" feature phones
    v = float(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)
    return int(round(v))


def money(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def local_date(ts):
    """'2026-11-30T23:59:00+1100' -> '2026-11-30' (the Australian date it ends on)."""
    if not ts:
        return None
    ts = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts.strip())
    try:
        return datetime.fromisoformat(ts).astimezone(AEST).date().isoformat()
    except ValueError:
        return None


def fmt(v):
    return f"${v:,.2f}".replace(".00", "")


def parse_listing(page):
    """Device id -> {brand, name, url} for the phones shown on the grid, in grid order."""
    out = {}
    for m in re.finditer(r'<li class="tcom-device-grid__product-card[^"]*"[^>]*>', page):
        tag = m.group(0)
        a = {k.lower(): html.unescape(v).strip() for k, v in re.findall(r'\b(id|data-[\w-]+)="([^"]*)"', tag)}
        did = a.get("id")
        brand, name = a.get("data-mobile-device-brand"), a.get("data-mobile-device-name")
        if not did or not brand or not name:
            continue
        href = re.search(r'<a href="(/mobile-phones/[^"]+)"', page[m.end():m.end() + 6000])
        out.setdefault(did, {"brand": brand, "name": name,
                             "url": BASE + html.unescape(href.group(1)) if href else LIST_URL})
    return out


def campaign_ends(page, device_id):
    """Promo name -> end date for this device's device promos on its phone page."""
    out = {}
    for tag in re.findall(r"<[a-z]+[^>]*\bdata-promo-id=[^>]*>", page):
        a = {k.lower(): html.unescape(v).strip() for k, v in re.findall(r'\b(data-promo-[\w-]+)="([^"]*)"', tag)}
        if a.get("data-promo-productcode") != device_id:
            continue
        d = local_date(a.get("data-promo-end-date-time"))
        name = a.get("data-promo-name")
        if name and d:
            out[name] = max(out.get(name, d), d)
    return out


def pick(values, warnings, what):
    """Most common value across colours (they normally agree); warn when they don't."""
    c = Counter(values)
    if len(c) > 1:
        warnings.append(f"{what}: colours disagree {dict(c)}; used the most common")
    return c.most_common(1)[0][0]


def main():
    raw = RAW / STEM
    page = fetch(LIST_URL, raw / "mobiles-on-a-plan.html", min_interval=2.0).decode("utf-8", "replace")
    m = re.search(r'data-device-grid-json-path="([^"]+)"', page)
    feed_url = BASE + html.unescape(m.group(1)) if m and m.group(1).startswith("/") else FEED_URL
    if not allowed(feed_url):
        raise RuntimeError(f"grid feed path {feed_url} is disallowed by robots.txt; not fetched")
    feed = json.loads(fetch(feed_url, raw / "grid-devices.json", min_interval=2.0).decode("utf-8"))
    captured = now_iso()
    listing = parse_listing(page)
    if not listing:
        raise RuntimeError("Telstra phone grid parsed to zero cards; page layout may have changed")

    rows = defaultdict(list)          # device id -> feed rows
    for r in feed.get("devices") or []:
        if r.get("id") in listing:
            rows[r["id"]].append(r)

    wanted, unlisted, warnings = {}, [], []
    for did, card in listing.items():
        key = handset_key(card["brand"], card["name"])
        if key in CATALOGUE:
            if key in wanted:
                warnings.append(f"{key}: two grid cards ({wanted[key]} and {did}); kept the first")
                continue
            wanted[key] = did
        else:
            launch = max((r.get("marketLaunchDate") or "" for r in rows.get(did, [])), default="")
            if launch >= (datetime.now(AEST) - timedelta(days=200)).date().isoformat():
                unlisted.append(f"{key} (launched {launch[:10]})")
    missing = [k for k in CATALOGUE if k not in wanted]

    # Campaign end dates: one phone page per discount name, taken from the first phone that has it.
    campaigns = {}
    for key, did in wanted.items():
        for r in rows.get(did, []):
            name = (r.get("discountText") or "").strip()
            if name and name not in campaigns and r.get("discountApplied"):
                campaigns[name] = did
    ends, pages = {}, []
    for name, did in list(campaigns.items())[:MAX_PAGES]:
        url = listing[did]["url"]
        if not allowed(url):
            warnings.append(f"{url} is disallowed by robots.txt; no end date for '{name}'")
            continue
        try:
            body = fetch(url, raw / f"{slug(listing[did]['name'])}.html", min_interval=2.0).decode("utf-8", "replace")
        except Exception as e:  # an end date is a nicety; carry on without it
            warnings.append(f"could not fetch {url} for the '{name}' end date: {e}")
            continue
        pages.append(url)
        got = campaign_ends(body, did)
        if name in got:
            ends[name] = got[name]
        else:
            warnings.append(f"no end date for '{name}' on {url}")
    if len(campaigns) > MAX_PAGES:
        warnings.append(f"more discount names than MAX_PAGES: {list(campaigns)}")

    phones = []
    for key, did in wanted.items():
        card = listing[did]
        model = display_model(card["name"])
        by = defaultdict(list)        # (storage label, term label) -> rows across colours
        for r in rows.get(did, []):
            by[(r.get("storage"), str(r.get("numberOfRepayments")))].append(r)
        btl = any(r.get("hasTargetedBTLPromo") for r in rows.get(did, []))
        storages = sorted({s for s, _ in by if storage_gb(s)}, key=storage_gb)
        if not storages:
            warnings.append(f"{key}: no priced storage options in the feed")
        for st in storages:
            gb = storage_gb(st)
            out_rows = by.get((st, "Outright"), [])
            outright = pick([money(r.get("oneOffCharge")) for r in out_rows], warnings, f"{key} {st} outright") if out_rows else None
            outright_was = None
            if out_rows:
                ow = pick([money(r.get("oneOffChargeBeforePromo")) for r in out_rows], warnings, f"{key} {st} outright before promo")
                outright_was = ow if ow and outright and ow > outright else None
            terms = sorted(int(t) for s, t in by if s == st and t.isdigit())
            base_notes = ["Interest-free repayments with a Telstra Upfront Mobile plan (Basic, Essential or Premium).",
                          "If you cancel the plan or move to an ineligible plan during the term, the remaining "
                          "device balance is payable in full (device discounts already given are kept)."]
            if btl:
                base_notes.append("Telstra shows a targeted 'Special deal' on this phone to some customers; "
                                  "it isn't public, so it isn't counted here.")
            for term in terms:
                rs = by[(st, str(term))]
                now_m = pick([money(r.get("recurringCharge")) for r in rs], warnings, f"{key} {st} {term}m")
                was_m = pick([money(r.get("recurringChargeBeforePromo")) or money(r.get("recurringCharge")) for r in rs],
                             warnings, f"{key} {st} {term}m before promo")
                if not now_m or not was_m:
                    continue
                discounts, notes = [], list(base_notes)
                names = {(r.get("discountText") or "").strip() for r in rs if r.get("discountApplied")} - {""}
                if was_m > now_m + 0.004:
                    name = sorted(names)[0] if names else "Device discount"
                    off = round((was_m - now_m) * term, 2)
                    until = ends.get(name)
                    discounts.append({
                        "off": off, "plans": None, "requires_trade_in": False, "until": until,
                        "text": f"{name}: {fmt(off)} off over {term} months (repayments {fmt(now_m)}/mth instead of "
                                f"{fmt(was_m)})" + (f"; ends {until}" if until else "") + ".",
                    })
                if outright_was:
                    notes.append(f"Outright price includes a discount (normally {fmt(outright_was)}).")
                phones.append({
                    "id": f"{PID}-{key}-{slug(st)}-{term}m", "provider": PID, "handset": key,
                    "brand": card["brand"], "model": model, "storage_gb": gb,
                    "outright": outright, "term": term, "monthly": was_m,
                    "discounts": discounts, "credits": [], "plans": list(PLANS),
                    "url": card["url"], "source": STEM, "captured": captured, "verified": True,
                    "notes": " ".join(notes),
                })
            if not terms and outright:
                phones.append({
                    "id": f"{PID}-{key}-{slug(st)}-outright", "provider": PID, "handset": key,
                    "brand": card["brand"], "model": model, "storage_gb": gb,
                    "outright": outright, "term": None, "monthly": None, "discounts": [], "credits": [],
                    "plans": None, "url": card["url"], "source": STEM, "captured": captured, "verified": True,
                    "notes": "Outright only." + (f" Price includes a discount (normally {fmt(outright_was)})." if outright_was else ""),
                })

    rejected = []                    # e.g. 2TB models on 12 months: over the schema's sanity bounds
    for r in list(phones):
        errs = check_phone(r)
        if errs:
            rejected.append(f"{r['id']}: {'; '.join(errs)}")
            phones.remove(r)
    if not phones:
        raise RuntimeError("Telstra phones: no handset variants parsed; feed or grid layout may have changed")
    phones.sort(key=lambda r: (CATALOGUE.index(r["handset"]), r["storage_gb"], r["term"] or 0))
    ids = [r["id"] for r in phones]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"Telstra phone ids not unique: {[i for i, n in Counter(ids).items() if n > 1]}")
    if missing:
        print(f"telstra_phones: warning: catalogue handsets not on Telstra's grid: {missing}", file=sys.stderr)
    for w in warnings + [f"left out (fails schema check): {x}" for x in rejected]:
        print(f"telstra_phones: warning: {w}", file=sys.stderr)
    meta = {"name": "Telstra phones on repayments (device grid feed)", "url": LIST_URL,
            "urls": [LIST_URL, feed_url] + pages, "fetched": captured, "feed_timestamp": feed.get("timestamp"),
            "campaign_ends": ends, "catalogue_missing": missing, "unlisted_new": unlisted, "warnings": warnings,
            "rejected": rejected}
    write_norm(STEM, {"internet": [], "mobile": [], "phones": phones}, meta)
    print(f"telstra_phones: {len(phones)} listings for {len(wanted)} handsets"
          + (f"; not sold by Telstra: {', '.join(missing)}" if missing else ""))


if __name__ == "__main__":
    main()

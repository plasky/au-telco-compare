"""Apple Australia: outright RRP for every iPhone model and storage size on apple.com/au.

https://www.apple.com/au/shop/buy-iphone links one buy page per model family
(/au/shop/buy-iphone/<slug>; "iphone-18-pro" covers both 18 Pro and 18 Pro Max). Each buy page
is server-rendered and embeds a metrics JSON block (<script type="application/json" id="metrics">)
whose data.products lists every part number with its name ("iPhone 18 Pro Max 256GB Deep Blue")
and price.fullPrice. The page's schema.org Product blocks give the low/high price per model, used
as a sanity check. robots.txt allows /au/shop/buy-iphone/*; it disallows only the shop overlay
paths (/*shop/browse/overlay/*, /*shop/iphone/payments/overlay/*), which are never fetched.

Requests per run: the listing plus one page per model (6 today; capped at MAX_MODELS).

Notes on the content:
  - fullPrice is Apple's own price, the RRP. Trade-in and Afterpay figures are ignored.
  - Prices are the same for every colour; if they ever differ the lowest is used and noted.
  - Apple's promos are gift cards rather than price cuts and are only described in marketing
    copy, so the known ones are listed in PROMOS with their dates and drop out once they end.
    The listing page's promo ribbon is saved in meta so new promos can be spotted.
"""
import html
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402
from schema import check_phone  # noqa: E402

PID = "apple"
STEM = "apple_phones"
BRAND = "Apple"
BASE = "https://www.apple.com"
LIST_URL = BASE + "/au/shop/buy-iphone"
MAX_MODELS = 7                  # listing + 7 model pages = 8 requests at most
AEST = timezone(timedelta(hours=10))

# Known Apple promos (gift cards, not price cuts). Each applies to the listed models from
# `shown_from` until `until` (inclusive, Australian date).
PROMOS = [
    {"models": {"iPhone 16", "iPhone 17", "iPhone 17e", "iPhone Air"},
     "shown_from": "2026-11-20", "until": "2026-11-30",
     "text": "Apple Black Friday event 27-30 Nov 2026: Apple Gift Card up to A$140 (or that much off) "
             "when you buy this iPhone from Apple"},
]


def clean(s):
    s = html.unescape(s or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def display_model(name):
    return re.sub(r"\s+5G$", "", clean(name), flags=re.I)


def handset_key(model):
    return slug(f"{BRAND} {display_model(model).replace('+', ' Plus')}")


def storage_gb(n, unit):
    return int(round(float(n) * (1024 if unit.upper() == "TB" else 1)))


def model_pages(page):
    """Model slugs linked from the buy-iphone listing, in page order."""
    out = []
    for s in re.findall(r'href="(?:https://www\.apple\.com)?/au/shop/buy-iphone/([a-z0-9-]+)"', page):
        if s not in out:
            out.append(s)
    return out


def ld_ranges(page):
    """Model name -> (lowPrice, highPrice) from the page's schema.org Product blocks."""
    out = {}
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("@type") != "Product":
            continue
        for o in d.get("offers") or []:
            if o.get("lowPrice") is not None:
                out[clean(d.get("name"))] = (float(o["lowPrice"]), float(o.get("highPrice") or o["lowPrice"]))
    return out


def variants(page):
    """(model, storage_gb) -> set of prices, from the metrics JSON block."""
    m = re.search(r'<script type="application/json" id="metrics">(.*?)</script>', page, re.S)
    if not m:
        return {}
    data = json.loads(m.group(1)).get("data") or {}
    out = {}
    for p in data.get("products") or []:
        name = clean(p.get("name"))
        price = (p.get("price") or {}).get("fullPrice")
        nm = re.match(r"^(iPhone.*?)\s+(\d+(?:\.\d+)?)\s*(GB|TB)\b", name)
        if not nm or not isinstance(price, (int, float)):
            continue
        out.setdefault((display_model(nm.group(1)), storage_gb(nm.group(2), nm.group(3))), set()).add(float(price))
    return out


def promo_ribbon(page):
    m = re.search(r"promoRibbonContent\s*=\s*", page)
    if not m:
        return []
    try:
        d, _ = json.JSONDecoder().raw_decode(page[m.end():])
    except ValueError:
        return []
    return [clean(v) for v in d.values() if isinstance(v, str)]


def active_promos(model, today):
    return [p["text"] for p in PROMOS if model in p["models"] and p["shown_from"] <= today <= p["until"]]


def main():
    raw = RAW / STEM
    listing = fetch(LIST_URL, raw / "buy-iphone.html").decode("utf-8")
    captured = now_iso()
    today = datetime.now(AEST).date().isoformat()
    slugs = model_pages(listing)
    if not slugs:
        raise RuntimeError("apple_phones: no model pages linked from the buy-iphone listing")
    skipped = slugs[MAX_MODELS:]
    phones, problems = [], []
    for s in slugs[:MAX_MODELS]:
        url = f"{LIST_URL}/{s}"
        page = fetch(url, raw / f"{s}.html").decode("utf-8")
        ranges = ld_ranges(page)
        found = variants(page)
        if not found:
            problems.append(f"{s}: no priced variants")
        for (model, gb), prices in sorted(found.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            price = min(prices)
            lo, hi = ranges.get(model, (None, None))
            if lo is not None and not lo <= price <= hi:
                problems.append(f"{model} {gb}GB: A${price:.0f} outside the page's A${lo:.0f}-{hi:.0f} range; skipped")
                continue
            key = handset_key(model)
            store = f"{gb // 1024}tb" if gb >= 1024 and gb % 1024 == 0 else f"{gb}gb"
            notes = active_promos(model, today)
            if len(prices) > 1:
                notes.append(f"Price varies by colour (A${min(prices):,.0f}-{max(prices):,.0f}); lowest shown.")
            rec = {
                "id": f"{PID}-{key}-{store}-outright", "provider": PID, "handset": key, "brand": BRAND,
                "model": model, "storage_gb": gb, "outright": price, "term": None, "monthly": None,
                "discounts": [], "credits": [], "plans": None, "url": url, "source": STEM,
                "captured": captured, "verified": True, "notes": " ".join(notes) or None,
            }
            errs = check_phone(rec)
            if errs:
                problems.append(f"{rec['id']}: {'; '.join(errs)}")
                continue
            phones.append(rec)
    if not phones:
        raise RuntimeError("apple_phones: parsed no phones; page layout may have changed. " + " | ".join(problems))
    for p in problems:
        print("warning: " + p, file=sys.stderr)
    meta = {"name": "Apple Store Australia (buy iPhone)", "url": LIST_URL, "fetched": captured,
            "models": slugs[:MAX_MODELS], "skipped_models": skipped, "promo_ribbon": promo_ribbon(listing),
            "problems": problems}
    write_norm(STEM, {"internet": [], "mobile": [], "phones": phones}, meta)
    print(f"apple_phones: {len(phones)} phone listings from {len(slugs[:MAX_MODELS])} model pages"
          + (f"; skipped {', '.join(skipped)} (page cap)" if skipped else ""))


if __name__ == "__main__":
    main()

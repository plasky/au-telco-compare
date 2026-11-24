"""ALDI Mobile (provider id "aldi-mobile"): SIM plans from its Shopify storefront's product feed.

https://www.aldimobile.com.au/products.json?limit=250 is Shopify's standard public product
listing (robots.txt: "Allow: /"; only cart, checkout, account, admin and a few AJAX paths are
disallowed). One request returns every plan, so a run needs just that one fetch. Each product has:
  - product_type: "Mobile Plan", "Data Plan", "Family Plan" or "Pay As You Go";
  - variants[0].price: the recharge price (incl. GST); variants[0].available is false for plans
    closed to new customers (also tagged "availability:not_available");
  - body_html: the plan bullets, e.g. "Unlimited standard calls & SMS to Australian numbers and
    20 selected destinations / 45GB data with unlimited data rollover / Bonus 45GB on your first
    6 eligible recharges / 5G enabled, speed caps apply / 30 day expiry".

Notes on the content:
  - The plan facts (data, expiry, calls, 5G, rollover) come from the bullet text; a plan whose
    data or expiry can't be read is skipped with a warning, and the run fails if none parse.
  - "Bonus xGB on your first 6 eligible recharges" is extra data, not a price offer, so it goes
    in notes and data_gb stays the base allowance.
  - The "20 selected destinations" for included international calls are listed only in a modal
    on the product pages, which this adapter doesn't fetch, so intl is None (see notes).
  - Family plans (one price for 2, 4 or 6 services sharing a data pool) are not per-line plans
    and are skipped here; the household optimiser needs a shared-plan model for them.
  - In-store-only "Special Buys" and PAYG starter kits are skipped.
  - The site answered a product HTML page with 429 "local_rate_limited" during development, so
    the adapter makes a single request and doesn't retry.
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, write_norm  # noqa: E402

BASE = "https://www.aldimobile.com.au"
URL = BASE + "/products.json?limit=250"
PID = "aldi-mobile"
STEM = pathlib.Path(__file__).stem
PLAN_TYPES = {"Mobile Plan", "Data Plan"}


def text_of(body_html):
    t = re.sub(r"\[/?modal[^\]]*\]", "", body_html or "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def gb(num, unit):
    v = float(num)
    return v * 1000 if unit.upper() == "TB" else v


def main():
    feed = json.loads(fetch(URL, RAW / STEM / "products.json", min_interval=2.0, retries=1))
    captured = now_iso()
    mobile, skipped = [], []
    for p in feed.get("products", []):
        if p.get("product_type") not in PLAN_TYPES:
            continue
        tags = set(p.get("tags") or [])
        variants = p.get("variants") or []
        if not variants or not any(v.get("available") for v in variants) or "availability:not_available" in tags:
            continue
        t = text_of(p.get("body_html"))
        low = t.lower()
        if "not available online" in low or "not available for new customers" in low:
            continue
        price = float(variants[0]["price"])
        dm = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s+(?:of\s+)?(?:5G\s+)?data\b", t, re.I)
        em = re.search(r"(\d+)\s*days?\s+expiry", t, re.I)
        if not dm or not em:
            skipped.append(f"{p.get('title')}: data or expiry not found")
            continue
        data_only = p["product_type"] == "Data Plan" or "data only" in low
        if data_only:
            calls = "none"
        elif re.search(r"unlimited[^.]*?calls", low):
            calls = "unlimited"
        elif "calls" in low:
            calls = "limited"
        else:
            calls = "unknown"
        notes = []
        bm = re.search(r"Bonus \d+(?:\.\d+)?\s*(?:GB|TB)[^.]*?recharges", t, re.I)
        if bm:
            notes.append(bm.group(0).replace("your ", "") + " (extra data, not included in data_gb).")
        if "speed cap" in low:
            notes.append("Speed caps apply.")
        im = re.search(r"(\d+)\s+selected (?:destinations|countries)|(\d+)\s+destinations", t, re.I)
        if im and not data_only:
            n = im.group(1) or im.group(2)
            notes.append(f"Includes standard calls to {n} selected international destinations (list on the plan page).")
        mobile.append({
            "id": f"{PID}-{p['handle']}", "provider": PID, "name": p["title"], "network": "telstra",
            "type": "prepaid", "period_days": int(em.group(1)), "price": price,
            "data_gb": gb(dm.group(1), dm.group(2)), "data_only": data_only, "calls": calls,
            "five_g": "5g enabled" in low, "intl": None, "promo": None, "contract": 0,
            "rollover": "rollover" in low, "credit": None,
            "url": f"{BASE}/products/{p['handle']}", "cis_url": None, "source": STEM,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })
    for s in skipped:
        print(f"{STEM}: skipped {s}", file=sys.stderr)
    if not mobile:
        raise RuntimeError("ALDI Mobile product feed parsed to zero plans; feed or wording may have changed")
    meta = {"name": "ALDI Mobile product feed (Shopify products.json)", "url": URL, "fetched": captured,
            "skipped": skipped}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"{STEM}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

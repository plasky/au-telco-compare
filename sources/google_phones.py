"""Google Store Australia: outright RRP for the Pixel phones on store.google.com/au.

https://store.google.com/au/category/phones?hl=en-GB links one product page per phone
(/product/pixel_<n>...). Each phone's configurator page, /au/config/<slug>?hl=en-GB, is
server-rendered and embeds its data in AF_initDataCallback({... data: [...]}) blocks. Every
variant appears there as ["_pixel_11_pro_obsidian_256gb_unlocked", "<name>", [images],
[status, null, 1, 2, [current price, list price, null, [sale start], [sale end], [saving], ...],
1, "<status text>", ...], [[[k, v], "Capacity", "256 GB"], [[k, v], "Style", "Pixel 11 Pro"], ...]]
with prices as ["AUD", amount]; status 1 = in stock, 2 = out of stock. robots.txt allows
/product, /category and /config; it disallows /prices, /addtocart and similar endpoints, which
are never fetched.

Requests per run: the category page plus one configurator page per phone (7 today; capped).

Notes on the content:
  - outright is today's price: the sale price while a sale runs (refreshed nightly, so it
    reverts to the list price when the sale ends), else the list price (RRP). The list price and
    sale end (AEST) go in notes.
  - Variants out of stock in every colour are skipped and listed in meta (several Pixel 10
    models are "Out of stock - get notified" today).
  - The model name comes from the variant's "Style" attribute, else from its product slug
    ("pixel_10_pro_fold" -> "Pixel 10 Pro Fold"). Variants of other phones are ignored.
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402
from schema import check_phone  # noqa: E402

PID = "google"
STEM = "google_phones"
BRAND = "Google"
BASE = "https://store.google.com"
CATEGORY_URL = BASE + "/au/category/phones?hl=en-GB"
CONFIG_URL = BASE + "/au/config/{}?hl=en-GB"
MAX_PHONES = 7                  # category + 7 configurator pages = 8 requests at most
AEST = timezone(timedelta(hours=10))


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def display_model(name):
    return re.sub(r"\s+5G$", "", clean(name), flags=re.I)


def handset_key(model):
    return slug(f"{BRAND} {display_model(model).replace('+', ' Plus')}")


def model_from_slug(s):
    words = {"pixel": "Pixel", "pro": "Pro", "xl": "XL", "fold": "Fold"}
    return " ".join(words.get(w, w) for w in s.split("_"))


def storage_gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", clean(s), re.I)
    if not m:
        return None
    return int(round(float(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)))


def store_label(gb):
    return f"{gb // 1024}tb" if gb >= 1024 and gb % 1024 == 0 else f"{gb}gb"


def phone_slugs(page):
    """Pixel phone slugs linked from the category page, newest generation first."""
    out = []
    for s in re.findall(r'"/product/(pixel_\d+[a-z]?(?:_(?:pro|xl|fold))*)"', page):
        if s not in out:
            out.append(s)
    return sorted(out, key=lambda s: -int(re.match(r"pixel_(\d+)", s).group(1)))


def af_blobs(page):
    for m in re.finditer(r"AF_initDataCallback\(\{key: *'[^']+', hash: *'\d+', data:", page):
        try:
            yield json.JSONDecoder().raw_decode(page[m.end():])[0]
        except ValueError:
            continue


def sku_entries(page):
    found = {}

    def walk(o):
        if isinstance(o, list):
            if len(o) >= 5 and isinstance(o[0], str) and re.fullmatch(r"_pixel_\w+_unlocked", o[0]) and isinstance(o[1], str):
                found.setdefault(o[0], o)
                return
            for v in o:
                walk(v)

    for b in af_blobs(page):
        walk(b)
    return found


def is_price(x):
    return isinstance(x, list) and len(x) >= 2 and x[0] == "AUD" and isinstance(x[1], (int, float))


def epoch(x):
    return datetime.fromtimestamp(x[0], timezone.utc) if isinstance(x, list) and x and isinstance(x[0], (int, float)) else None


def parse_variant(o):
    blk = next((x for x in o[2:] if isinstance(x, list) and len(x) > 6 and isinstance(x[4], list)
                and x[4] and is_price(x[4][0])), None)
    attrs = next((x for x in o[2:] if isinstance(x, list) and x and all(
        isinstance(a, list) and len(a) == 3 and isinstance(a[1], str) and isinstance(a[2], str) for a in x)), [])
    if not blk:
        return None
    a = {k: v for _, k, v in attrs}
    p = blk[4]
    current = float(p[0][1])
    listed = float(p[1][1]) if len(p) > 1 and is_price(p[1]) else current
    family = blk[11] if len(blk) > 11 and isinstance(blk[11], str) else None
    return {"family": family, "style": a.get("Style"), "capacity": a.get("Capacity"), "current": current, "list": listed,
            "start": epoch(p[3]) if len(p) > 3 else None, "end": epoch(p[4]) if len(p) > 4 else None,
            "in_stock": blk[0] == 1, "status": clean(blk[6]) if isinstance(blk[6], str) else ""}


def main():
    raw = RAW / STEM
    category = fetch(CATEGORY_URL, raw / "category-phones.html").decode("utf-8")
    captured = now_iso()
    now = datetime.now(timezone.utc)
    slugs = phone_slugs(category)
    if not slugs:
        raise RuntimeError("google_phones: no Pixel phone links on the category page")
    skipped_pages = slugs[MAX_PHONES:]
    groups, problems = {}, []
    for s in slugs[:MAX_PHONES]:
        url = CONFIG_URL.format(s)
        page = fetch(url, raw / f"config_{s}.html").decode("utf-8")
        entries = sku_entries(page)
        n = 0
        for sku, o in entries.items():
            v = parse_variant(o)
            if not v or (v["family"] and v["family"] != s):
                continue                    # not a variant of this page's phone
            model = display_model(v["style"] or model_from_slug(v["family"] or s))
            gb = storage_gb(v["capacity"]) or storage_gb(re.sub(r"_", " ", sku).replace("gb", " GB").replace("tb", " TB"))
            if not gb:
                problems.append(f"{sku}: no storage size")
                continue
            g = groups.setdefault((model, gb), {"url": url, "list": set(), "sale": [], "in_stock": False, "status": set()})
            g["list"].add(v["list"])
            if v["in_stock"]:
                g["in_stock"] = True
            elif v["status"]:
                g["status"].add(v["status"])
            if v["current"] < v["list"] and (v["start"] is None or v["start"] <= now) and (v["end"] is None or now <= v["end"]):
                g["sale"].append((v["current"], v["end"]))
            n += 1
        if not n:
            problems.append(f"{s}: no priced variants")
    phones, skipped = [], []
    for (model, gb), g in sorted(groups.items()):
        if not g["in_stock"]:
            skipped.append(f"{model} {gb}GB: {' / '.join(sorted(g['status'])) or 'out of stock'} in every colour")
            continue
        rrp = min(g["list"])
        price_now = rrp
        notes = []
        if len(g["list"]) > 1:
            notes.append(f"List price varies by colour (A${min(g['list']):,.0f}-{max(g['list']):,.0f}); lowest shown.")
        if g["sale"]:
            sale, end = min(g["sale"], key=lambda x: x[0])
            until = end.astimezone(AEST) if end else None
            notes.append(f"Google Store sale price (list price A${rrp:,.0f}, save A${rrp - sale:,.0f})"
                         + (f" until {until.day} {until.strftime('%b %Y')}." if until else "."))
            price_now = sale
        key = handset_key(model)
        rec = {
            "id": f"{PID}-{key}-{store_label(gb)}-outright", "provider": PID, "handset": key, "brand": BRAND,
            "model": model, "storage_gb": gb, "outright": price_now, "term": None, "monthly": None,
            "discounts": [], "credits": [], "plans": None, "url": g["url"], "source": STEM,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        }
        errs = check_phone(rec)
        if errs:
            problems.append(f"{rec['id']}: {'; '.join(errs)}")
            continue
        phones.append(rec)
    if not phones:
        raise RuntimeError("google_phones: parsed no phones; page layout may have changed. " + " | ".join(problems))
    for p in problems:
        print("warning: " + p, file=sys.stderr)
    meta = {"name": "Google Store Australia", "url": CATEGORY_URL, "fetched": captured,
            "pages": slugs[:MAX_PHONES], "skipped_pages": skipped_pages, "skipped": skipped, "problems": problems}
    write_norm(STEM, {"internet": [], "mobile": [], "phones": phones}, meta)
    print(f"google_phones: {len(phones)} phone listings from {len(slugs[:MAX_PHONES])} configurator pages"
          + (f"; skipped {len(skipped)} out-of-stock variants" if skipped else ""))


if __name__ == "__main__":
    main()

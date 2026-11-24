"""Samsung Australia: outright RRP for the current Galaxy S, Z Fold, Z Flip and Galaxy A phones.

https://www.samsung.com/au/smartphones/all-smartphones/ carries a schema.org ItemList (one entry
per featured SKU: name, price, product URL). The S and Z series link to "buy" configurator pages
(/au/smartphones/<model>/buy/), which are server-rendered and embed `var BC_GROUP = {...}`: every
model code with its options (device, storage, colour), `price` (RRP), `promotionPrice` (sale
price, when on sale) and stock status. The Galaxy A phones link to product pages whose other
storage sizes are priced by script only, so they come from the ItemList entry (one storage size).
robots.txt allows these pages for all user agents (it disallows search, /c/p/, multistore and
similar paths, none of which are used).

Requests per run: the listing plus one buy page per current S/Z model (5 today; capped).

Notes on the content:
  - Only the newest generation of each family (S, Z Fold, Z Flip) is kept, so previous models
    still on sale (e.g. Galaxy S25 Ultra) are left out.
  - outright is today's price: the Samsung.com sale price while a sale runs (refreshed nightly, so
    it reverts to the RRP when the sale ends), else the RRP. The RRP and sale end go in notes, from
    the page's "Save $X ... Offer ends <date>" banner.
  - Variants with no price on the page (e.g. Galaxy S26+ today) or out of stock in every colour
    are skipped and listed in meta.
"""
import html
import json
import pathlib
import re
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402
from schema import check_phone  # noqa: E402

PID = "samsung"
STEM = "samsung_phones"
BRAND = "Samsung"
BASE = "https://www.samsung.com"
LIST_URL = BASE + "/au/smartphones/all-smartphones/"
MAX_BUY_PAGES = 7               # listing + 7 buy pages = 8 requests at most
IN_STOCK = {"inStock", "lowStock"}
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def clean(s):
    s = html.unescape(html.unescape(s or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def display_model(name):
    name = re.sub(r"\s*\(Samsung\.com only\)", "", clean(name), flags=re.I)
    return re.sub(r"\s+5G$", "", name, flags=re.I).strip()


def handset_key(model):
    return slug(f"{BRAND} {display_model(model).replace('+', ' Plus')}")


def storage_gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", s or "", re.I)
    if not m:
        return None
    return int(round(float(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)))


def nice_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %Y')}"


def store_label(gb):
    return f"{gb // 1024}tb" if gb >= 1024 and gb % 1024 == 0 else f"{gb}gb"


def money(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def parse_date(s):
    """'02 December 2026', '2 Dec 2026', '02 Dec 26' -> ISO date."""
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{2,4})", s or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    y = int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return datetime(y, MONTHS[m.group(2).lower()], int(m.group(1))).date().isoformat()
    except ValueError:
        return None


def item_list(page):
    """The listing's schema.org ItemList entries: (name, price, url)."""
    for blob in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "ItemList":
            out = []
            for e in d.get("itemListElement") or []:
                it = e.get("item") or {}
                out.append((clean(it.get("name")), money((it.get("offers") or {}).get("price")), it.get("url") or ""))
            return out
    return []


def buy_pages(items):
    """Newest-generation S / Z Fold / Z Flip buy pages linked from the listing, in listing order."""
    found = []
    for _, _, url in items:
        m = re.search(r"/au/smartphones/(galaxy-(s|z-fold|z-flip)(\d+)[a-z0-9-]*)/buy/", url)
        if m and m.group(1) not in [f[0] for f in found]:
            found.append((m.group(1), m.group(2), int(m.group(3))))
    newest = {}
    for _, fam, gen in found:
        newest[fam] = max(newest.get(fam, 0), gen)
    return [f"{BASE}/au/smartphones/{p}/buy/" for p, fam, gen in found if gen == newest[fam]]


def bc_group(page):
    m = re.search(r"var BC_GROUP\s*=\s*", page)
    if not m:
        return None
    return json.JSONDecoder().raw_decode(page[m.end():])[0]


def sale_banners(page):
    """[(banner text, end date)] for the page's "Save $X ... Offer ends <date>" banners."""
    out = []
    for m in re.finditer(r'data-fold-title="([^"]*)"[^>]*>(.*?)Offer ends\s+([0-9]{1,2}\s+[A-Za-z]+\.?\s+\d{2,4})', page, re.S):
        title, body = clean(m.group(1)), clean(m.group(2))
        if re.search(r"\bSave\b", title) and len(body) < 600:
            out.append((clean(f"{body}"), parse_date(m.group(3))))
    return out


def page_variants(page):
    """(model, storage_gb) -> {rrp, sale, in_stock} from a buy page's BC_GROUP."""
    g = bc_group(page)
    if not g:
        return {}, None
    opts = {}
    for bo in g.get("buyingOptions") or []:
        opts[bo.get("typeCode")] = {it.get("itemId"): clean(it.get("displayName")) for it in bo.get("optionItems") or []}
    out = {}
    for p in (g.get("products") or {}).values():
        sel = {om.get("typeCode"): om.get("itemId") for om in p.get("optionMappings") or []}
        model = display_model(opts.get("OPT-015", {}).get(sel.get("OPT-015")) or g.get("displayModelName") or g.get("groupName"))
        gb = storage_gb(opts.get("OPT-007", {}).get(sel.get("OPT-007")))
        if not model or not gb:
            continue
        v = out.setdefault((model, gb), {"rrp": set(), "sale": set(), "in_stock": False, "priced": False})
        rrp, sale = money(p.get("price")), money(p.get("promotionPrice"))
        if rrp:
            v["priced"] = True
            v["rrp"].add(rrp)
            if sale and sale < rrp:
                v["sale"].add(sale)
            if p.get("stockLevelStatus") in IN_STOCK:
                v["in_stock"] = True
    return out, g.get("groupName")


def record(model, gb, rrp, url, captured, notes):
    key = handset_key(model)
    return {
        "id": f"{PID}-{key}-{store_label(gb)}-outright", "provider": PID, "handset": key, "brand": BRAND,
        "model": display_model(model), "storage_gb": gb, "outright": rrp, "term": None, "monthly": None,
        "discounts": [], "credits": [], "plans": None, "url": url, "source": STEM, "captured": captured,
        "verified": True, "notes": " ".join(notes) or None,
    }


def main():
    raw = RAW / STEM
    listing = fetch(LIST_URL, raw / "all-smartphones.html").decode("utf-8")
    captured = now_iso()
    items = item_list(listing)
    if not items:
        raise RuntimeError("samsung_phones: no ItemList on the all-smartphones page")
    pages = buy_pages(items)
    skipped_pages = pages[MAX_BUY_PAGES:]
    phones, skipped, problems = [], [], []
    for url in pages[:MAX_BUY_PAGES]:
        name = url.rstrip("/").split("/")[-2]
        page = fetch(url, raw / f"{name}.html").decode("utf-8")
        found, group = page_variants(page)
        if not found:
            problems.append(f"{name}: no BC_GROUP variants")
            continue
        banners = sale_banners(page)
        for (model, gb), v in sorted(found.items()):
            if not v["priced"]:
                skipped.append(f"{model} {gb}GB: no price on the page")
                continue
            if not v["in_stock"]:
                skipped.append(f"{model} {gb}GB: out of stock in every colour")
                continue
            rrp = min(v["rrp"])
            price_now = rrp
            notes = []
            if len(v["rrp"]) > 1:
                notes.append(f"RRP varies by colour (${min(v['rrp']):,.0f}-${max(v['rrp']):,.0f}); lowest shown.")
            if v["sale"]:
                sale = min(v["sale"])
                until = next((d for t, d in banners if model.lower() in t.lower()), None) \
                    or next((d for _, d in banners), None)
                notes.append(f"Samsung.com sale price (RRP ${rrp:,.0f}, save ${rrp - sale:,.0f})"
                             + (f" until {nice_date(until)}." if until else "."))
                price_now = sale
            phones.append(record(model, gb, price_now, url, captured, notes))
    covered = {r["handset"] for r in phones}
    # Galaxy A (and anything else with only a product page): one storage size from the ItemList.
    for name, price, url in items:
        model = display_model(name)
        if "/buy/" in url or not re.match(r"Galaxy (A|S|Z)\d", model) or handset_key(model) in covered:
            continue
        gb = storage_gb(re.search(r"-(\d+(?:gb|tb))-sm-", url).group(1) if re.search(r"-(\d+(?:gb|tb))-sm-", url) else name)
        if not gb or not price:
            skipped.append(f"{name}: no storage or price in the listing")
            continue
        rec = record(model, gb, price, url.split("?")[0], captured,
                     ["Samsung.com price for this storage size; other sizes are not listed."])
        if rec["id"] not in {r["id"] for r in phones}:
            phones.append(rec)
    good = []
    for r in phones:
        errs = check_phone(r)
        if errs:
            problems.append(f"{r['id']}: {'; '.join(errs)}")
        else:
            good.append(r)
    if not good:
        raise RuntimeError("samsung_phones: parsed no phones; page layout may have changed. " + " | ".join(problems))
    for p in problems:
        print("warning: " + p, file=sys.stderr)
    meta = {"name": "Samsung Australia online store", "url": LIST_URL, "fetched": captured,
            "buy_pages": pages[:MAX_BUY_PAGES], "skipped_pages": skipped_pages, "skipped": skipped,
            "problems": problems}
    write_norm(STEM, {"internet": [], "mobile": [], "phones": good}, meta)
    print(f"samsung_phones: {len(good)} phone listings from {len(pages[:MAX_BUY_PAGES])} buy pages + listing"
          + (f"; skipped {len(skipped)} variants" if skipped else ""))


if __name__ == "__main__":
    main()

"""Mate (letsbemates.com.au): SIM-only mobile plans (Telstra Wholesale network) from its own
server-rendered mobile page (WordPress). One request per run.

https://www.letsbemates.com.au/mobile/ (robots.txt allows it; it blocks only wp-admin, feeds,
some tracking query strings, video folders and /mate/wp-content/uploads/).

Sources on that page:
  1. JSON-LD Product "MATE Mobile": one Offer per plan with name, monthly price and the ongoing
     allowance ("45GB of data per month"). Primary source for name, price and data.
  2. The plan slides, one `<div class="number-slide-item ..." data-connection="5g">` per plan:
     h3 name, data pill (a struck-through base allowance next to the bonus one while Double Data
     runs: "<span class=...line-through>45GB</span> 90GB Data*"), the speed cap, the inclusions
     (data banking, "Unlimited International calls & SMS to 15 selected countries"), the price
     and the CIS link. Used for those extras, and as the fallback for name/price/data.
  3. Page text: the network ("MATE uses the Telstra Wholesale Mobile Network") and the FAQ list
     of the 15 countries with unlimited international calls ("1 – Canada 2 – China ...").

Bundle: Mate's $10/month bundle saving comes off the internet plan ("Get a further $10 per month
off our internet plans when you bundle your MATE mobile plan"), so SIM records carry no bundle;
the nbn adapter carries it on the internet side. Double Data is a data bonus, not a price
promo, so it goes in notes.
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

PID = "mate"
URL = "https://www.letsbemates.com.au/mobile/"
SRC = pathlib.Path(__file__).stem
COUNTRIES = {
    "bangladesh": "BD", "canada": "CA", "china": "CN", "germany": "DE", "greece": "GR", "hong kong": "HK",
    "india": "IN", "ireland": "IE", "japan": "JP", "malaysia": "MY", "new zealand": "NZ", "singapore": "SG",
    "south korea": "KR", "korea": "KR", "thailand": "TH", "united kingdom": "GB", "uk": "GB", "usa": "US",
    "united states": "US", "vietnam": "VN", "viet nam": "VN", "france": "FR", "italy": "IT",
    "indonesia": "ID", "philippines": "PH", "pakistan": "PK", "sri lanka": "LK", "taiwan": "TW",
}


def text(s):
    s = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", s or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", s or "", re.I)
    return float(m.group(1)) * (1000 if m.group(2).upper() == "TB" else 1) if m else None


def ld_offers(page):
    out = {}
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for g in d.get("@graph", [d]) if isinstance(d, dict) else d:
            if not isinstance(g, dict) or g.get("@type") != "Product":
                continue
            for o in g.get("offers") or []:
                ps = o.get("priceSpecification") or {}
                price = ps.get("price", o.get("price"))
                if o.get("name") and price is not None:
                    out[o["name"].strip().lower()] = {"name": o["name"].strip(), "price": float(price),
                                                      "data": gb(ps.get("description")),
                                                      "monthly": (ps.get("billingIncrement") or "").lower() == "monthly"}
    return out


def slides(page):
    parts = re.split(r'<div\s+class="number-slide-item\b', page)
    for b in parts[1:]:
        end = b.find('class="number-slide-item')
        b = b if end < 0 else b[:end]
        name = text((re.search(r"<h3[^>]*>(.*?)</h3>", b, re.S) or [None, ""])[1])
        pill = re.search(r'<span class="fs-5[^"]*rounded-pill[^"]*"[^>]*>(.*?)</span>\s*</div>', b, re.S)
        pill_html = pill.group(1) if pill else ""
        struck = re.search(r'line-through[^"]*">([^<]*)</span>', pill_html)
        price = re.search(r'font-size: ?28px;?">\s*\$(\d+(?:\.\d+)?)', b)
        cis = re.search(r'<a href="([^"]+)"[^>]*>\s*Critical Information Summary', b)
        yield {
            "name": name, "connection": (re.search(r'data-connection="([^"]*)"', b) or [None, ""])[1].lower(),
            "pill": text(pill_html), "base": gb(struck.group(1)) if struck else None,
            "price": float(price.group(1)) if price else None, "cis": html.unescape(cis.group(1)) if cis else None,
            "text": text(b),
        }


def main():
    page = fetch(URL, RAW / SRC / "mobile.html", min_interval=2.0).decode("utf-8")
    captured = now_iso()
    body = text(page[page.find("<body"):])
    offers = ld_offers(page)
    network = "telstra" if "uses the Telstra Wholesale Mobile Network" in body else None
    if network is None:
        print("warning: host network statement not found", file=sys.stderr)

    intl = None
    fm = re.search(r"Unlimited calls and SMS to the following (\d+) countries.{0,80}?:\s*(.*?)\s*Any calls made", body)
    if fm:
        names = [n.strip().lower() for n in re.split(r"\s*\d+\s*[–-]\s*", fm.group(2)) if n.strip()]
        codes = [COUNTRIES.get(n) for n in names]
        if None in codes or len(codes) != int(fm.group(1)):
            print(f"warning: country list not fully mapped: {names}", file=sys.stderr)
        else:
            intl = sorted(set(codes))
    else:
        print("warning: international country list not found", file=sys.stderr)

    mobile, ids = [], set()
    for s in slides(page):
        o = offers.get(s["name"].lower(), {})
        name = o.get("name") or s["name"]
        price = o.get("price", s["price"])
        data = o.get("data") or s["base"] or gb(s["pill"])
        if not name or price is None or data is None:
            print(f"warning: skipped unparsable slide {s['name']!r}", file=sys.stderr)
            continue
        if s["price"] is not None and o and abs(s["price"] - o["price"]) > 0.005:
            print(f"warning: {name}: slide price {s['price']} != JSON-LD {o['price']}; using JSON-LD", file=sys.stderr)
        t = s["text"]
        notes = []
        cap = re.search(r"capped at (\d+) ?Mbps", t)
        if cap:
            notes.append(f"Download speeds capped at {cap.group(1)} Mbps.")
        shown = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*GB", s["pill"])]
        if s["base"] and len(shown) > 1 and shown[-1] > s["base"]:
            dd = re.search(r"Sign up and activate .{0,80}?between (\d{1,2} \w+ \d{4}) and (\d{1,2} \w+ \d{4})", t)
            notes.append(f"Double Data offer: {shown[-1]:g}GB per month for the first 6 months"
                         + (f" for sign-ups by {dd.group(2)}" if dd else "") + ".")
        bank = re.search(r"Data banking (\d+) ?GB of banked data", t)
        if bank:
            notes.append(f"Unused data banks (up to {bank.group(1)}GB).")
        mi = re.search(r"Unlimited International calls & SMS to (\d+) selected countries", t)
        plan_intl = intl if mi and intl and len(intl) == int(mi.group(1)) else None
        if mi and plan_intl is None:
            notes.append(f"Unlimited international calls to {mi.group(1)} countries (list not parsed).")
        rid = f"{PID}-mobile-{slug(name)}"
        if rid in ids:
            continue
        ids.add(rid)
        mobile.append({
            "id": rid, "provider": PID, "name": name, "network": network, "type": "postpaid",
            "period_days": 30, "price": price, "data_gb": data, "data_only": False,
            "calls": "unlimited" if "Unlimited talk and text" in t else "unknown",
            "five_g": s["connection"] == "5g" or "5g" in name.lower(), "intl": plan_intl, "promo": None,
            "contract": 0, "rollover": True if bank else None, "bundle": [], "credit": None, "url": URL,
            "cis_url": s["cis"], "source": SRC, "captured": captured, "verified": True,
            "notes": " ".join(notes) or None,
        })
    if not mobile:
        raise RuntimeError("mate mobile: no plan slides parsed; page layout may have changed")
    missing = set(offers) - {r["name"].lower() for r in mobile}
    if missing:
        print(f"warning: JSON-LD offers without a slide: {sorted(missing)}", file=sys.stderr)
    meta = {"name": "MATE SIM-only mobile plans page", "url": URL, "fetched": captured}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

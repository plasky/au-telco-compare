"""Exetel: its 5G prepaid eSIM plan ("Plus One", Telstra Wholesale network) from its mobile page.

https://www.exetel.com.au/mobilephone (robots.txt: "Allow: /"). One request per run.

Sources on that page (TanStack Start + headless CMS, server-rendered):
  1. JSON-LD Product(s) (script#structured-data): plan name, price per recharge (offers.price),
     the offer name ("Double Data for the first 6 recharges"), size (the allowance shown, which
     includes the bonus while Double Data runs) and a description with the speed cap and the
     15 countries with unlimited international calls and SMS. Required; fails without it.
  2. Page text: the base allowance ("Get 260GB for the price of 130GB for the first 6
     recharges", "a massive 130GB every 30 days"), the network ("The mobile product of Exetel
     uses the Telstra Wholesale Mobile Network", from the FAQ content in the page's dehydrated
     state), the 30-day prepaid cycle, the 1000GB Data Bank and the CIS link.

Exetel publishes no mobile + internet bundle discount and no multi-line discount.
Double Data is a data bonus, not a price promo, so it goes in notes.
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

URL = "https://www.exetel.com.au/mobilephone"
PID = "exetel"
SRC = pathlib.Path(__file__).stem
COUNTRIES = {
    "bangladesh": "BD", "canada": "CA", "china": "CN", "germany": "DE", "greece": "GR", "hong kong": "HK",
    "india": "IN", "ireland": "IE", "japan": "JP", "malaysia": "MY", "new zealand": "NZ", "singapore": "SG",
    "south korea": "KR", "korea": "KR", "thailand": "TH", "uk": "GB", "united kingdom": "GB", "usa": "US",
    "us": "US", "united states": "US", "vietnam": "VN", "philippines": "PH", "indonesia": "ID",
    "pakistan": "PK", "sri lanka": "LK", "taiwan": "TW", "italy": "IT", "france": "FR",
}


def products(node):
    if isinstance(node, list):
        for n in node:
            yield from products(n)
    elif isinstance(node, dict):
        if node.get("@type") == "Product":
            yield node
        for k in ("@graph", "itemListElement", "hasVariant"):
            if k in node:
                yield from products(node[k])


def text(s):
    s = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", s or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", s or "", re.I)
    return float(m.group(1)) * (1000 if m.group(2).upper() == "TB" else 1) if m else None


def main():
    page = fetch(URL, RAW / SRC / "mobilephone.html", min_interval=2.0).decode("utf-8")
    captured = now_iso()
    found = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            found += list(products(json.loads(m.group(1))))
        except ValueError:
            continue
    found = [p for p in found if re.search(r"\b(e?sim|mobile)\b", f"{p.get('name')} {p.get('description')}", re.I)]
    if not found:
        raise RuntimeError("exetel mobile: no SIM Product in the page's JSON-LD")

    body = text(page[page.find("<body"):])
    raw = page.replace("\\x3C", "<")  # CMS content in the dehydrated state is JS-escaped HTML
    network = "telstra" if re.search(r"uses the Telstra Wholesale Mobile Network", raw) else \
        "optus" if re.search(r"uses the Optus", raw) else None
    if network is None:
        print("warning: host network statement not found", file=sys.stderr)
    cis = next((html.unescape(u) for u in re.findall(r'href="([^"]+)"', page)
                if re.search(r"cis", u.rsplit("/", 1)[-1], re.I) and u.lower().endswith(".pdf")), None)
    bank = re.search(r"roll over up to (?:a massive )?(\d+)\s*GB", body) or re.search(r"data bank of (\d+)\s*GB", body, re.I)

    mobile = []
    for p in found:
        offer = p.get("offers") or {}
        offer = offer[0] if isinstance(offer, list) else offer
        if offer.get("price") is None:
            continue
        price = float(offer["price"])
        desc = p.get("description") or ""
        shown = gb(p.get("size")) or gb(desc)
        dd = re.search(r"Get (\d+)\s*GB for the price of (\d+)\s*GB for the first (\d+) recharges", body)
        cyc = re.search(r"massive (\d+)\s*GB every (\d+) days", body)
        base = float(dd.group(2)) if dd else float(cyc.group(1)) if cyc else shown
        period = int(cyc.group(2)) if cyc else 30
        if base is None:
            print(f"warning: no allowance for {p.get('name')}", file=sys.stderr)
            continue
        notes = []
        if dd:
            notes.append(f"Double Data offer: {dd.group(1)}GB per recharge for the first {dd.group(3)} recharges.")
        cap = re.search(r"capped at (\d+) ?Mbps", desc)
        if cap:
            notes.append(f"Download speeds capped at {cap.group(1)} Mbps.")
        if bank:
            notes.append(f"Unused data rolls into a Data Bank (up to {bank.group(1)}GB).")
        if re.search(r"eSIM[- ]only", body, re.I):
            notes.append("eSIM only.")
        intl = None
        im = re.search(r"to (\d+) other countries\s*\(([^)]+)\)", desc)
        if im:
            names = [n.strip().lower() for n in im.group(2).split(",") if n.strip()]
            codes = [COUNTRIES.get(n) for n in names]
            if None in codes or len(codes) != int(im.group(1)):
                print(f"warning: country list not fully mapped: {names}", file=sys.stderr)
            else:
                intl = sorted(set(codes))
        name = re.sub(r"^Exetel\s+", "", p.get("name") or "Mobile plan").strip()
        prepaid = re.search(r"pre-?paid", desc + body, re.I) is not None
        mobile.append({
            "id": f"{PID}-mobile-{slug(name)}", "provider": PID, "name": name, "network": network,
            "type": "prepaid" if prepaid else "postpaid", "period_days": period, "price": price,
            "data_gb": base, "data_only": False,
            "calls": "unlimited" if re.search(r"unlimited (standard )?calls", desc + body, re.I) else "unknown",
            "five_g": "5g" in name.lower() or "5G" in desc, "intl": intl, "promo": None, "contract": 0,
            "rollover": True if bank else None, "bundle": [], "credit": None,
            "url": offer.get("url") or URL, "cis_url": cis, "source": SRC, "captured": captured, "verified": True,
            "notes": " ".join(notes) or None,
        })
    if not mobile:
        raise RuntimeError("exetel mobile: JSON-LD parsed to zero plans")
    meta = {"name": "Exetel eSIM plan page", "url": URL, "fetched": captured}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

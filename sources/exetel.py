"""Exetel: its nbn plan page (Exetel sells a single nbn plan, "The One Plan").

https://www.exetel.com.au/broadband/nbn (robots.txt: "Allow: /").

The page carries a JSON-LD Product (script#structured-data) with the price (offers.price,
monthly), "Plan speed" and "Typical evening speed" properties and the contract term. Any
Product in the page's JSON-LD in the "nbn broadband" category is read, so a second plan would
be picked up too. The adapter fails if none is found.
Other facts from the same page: the CIS link, FTTP/HFC only (FTTN/FTTC/FTTB/FW addresses are
referred to Superloop; FTTN/FTTC may get a free fibre upgrade), modem optional
("add a pre-configured high-speed modem to your Exetel order or Bring Your Own").
Exetel is Superloop-owned but its site is a separate platform (TanStack Start + headless CMS),
so it has its own adapter. No setup fee is published here (left for the build to fill).
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

URL = "https://www.exetel.com.au/broadband/nbn"
PID = "exetel"
SRC = pathlib.Path(__file__).stem


def speeds(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", s or "")
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


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


def main():
    page = fetch(URL, RAW / SRC / "nbn.html").decode("utf-8")
    captured = now_iso()
    found = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            found += list(products(json.loads(m.group(1))))
        except ValueError:
            continue
    found = [p for p in found if "nbn" in (p.get("category", "") + " " + p.get("name", "")).lower()]
    if not found:
        raise RuntimeError("exetel: no nbn Product in the page's JSON-LD")

    cis = next((html.unescape(u) for u in re.findall(r'href="([^"]+)"', page)
                if re.search(r"cis", u.rsplit("/", 1)[-1], re.I) and u.lower().endswith(".pdf")), None)
    modem_buy = re.search(r"add a pre-configured[^.]*modem to your Exetel order", page, re.I)
    byo = re.search(r"Bring Your Own", page, re.I)
    modem = {"offer": "purchase" if modem_buy else "byo" if byo else "unknown", "cost": None}

    internet = []
    for p in found:
        props = {a.get("name", "").lower(): a.get("value") for a in p.get("additionalProperty") or []}
        nom_down, nom_up = speeds(props.get("plan speed") or p.get("name"))
        down, up = speeds(props.get("typical evening speed"))
        offer = p.get("offers") or {}
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        spec = offer.get("priceSpecification") or {}
        if spec.get("unitCode") not in (None, "MON"):
            continue
        price = float(offer.get("price") or spec.get("price"))
        contract_txt = str(props.get("contract", "")).lower()
        cm = re.search(r"(\d+)\s*month", contract_txt)
        contract = 0 if ("no lock-in" in contract_txt or "month-to-month" in contract_txt or not cm) else int(cm.group(1))
        name = re.split(r"\s+[–-]\s+", p.get("name", ""))[0].replace("Exetel ", "").strip()
        size = f"{int(nom_down)}/{int(nom_up)}" if nom_down and nom_up else None
        tier = tier_from(f"nbn {size}" if size else name, down)
        notes = None
        if tier and tier >= 250:
            notes = "FTTP and HFC only; eligible FTTN/FTTC premises can get a free fibre upgrade."
        internet.append({
            "id": f"{PID}-{slug(name)}" + (f"-{size.replace('/', '-')}" if size else ""), "provider": PID,
            "name": f"{name} {size}" if size else name, "kind": "nbn", "tier": tier, "techs": techs_for("nbn", tier),
            "down": down or nom_down, "up": up or nom_up, "price": price, "promo": None, "setup": None,
            "contract": contract, "modem": dict(modem), "data_gb": None, "network": None, "credit": None,
            "bundle": [], "url": offer.get("url") or p.get("url") or URL, "cis_url": cis, "source": SRC,
            "captured": captured, "verified": True, "notes": notes,
        })
    if not internet:
        raise RuntimeError("exetel: JSON-LD products parsed to zero plans")
    meta = {"name": "Exetel nbn plan page", "url": URL, "fetched": captured}
    write_norm(SRC, {"internet": internet, "mobile": []}, meta)
    print(f"{SRC}: {len(internet)} internet")


if __name__ == "__main__":
    main()

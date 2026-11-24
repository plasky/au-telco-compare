"""Spintel: residential nbn and 5G home internet plans from its own plan pages.

https://www.spintel.net.au/home-internet/nbn and /home-internet/wireless-internet
(robots.txt disallows only /static, /filemanager and /api/v1/tracker/; neither page is there.
The CIS PDFs under /static are linked to, never fetched.)

Both pages are Inertia.js apps: the <div id="app" data-page="..."> attribute holds the page
props as JSON, including the plan blocks that render the plan cards:
  - nbn block (service_type "fibre"): `plans` (priceEach, speed_id, contract_id, show_when =
    connection types it is shown for, promo_credit / promo_credit_months / promo_credit_type,
    cis_pdf_url), `speeds` (price = the speed add-on, downMbps/upMbps, typicalDownMbps /
    typicalUpMbps, type fibre|wireless, is_coat_upgrade) and `contracts` (length, setup_fee).
    The card price is priceEach + speed price ($64.95 + $5 = $69.95 on 25/10); the intro price
    is that minus promo_credit for promo_credit_months ("$25.95/MONTH OFF FOR 6 MONTHS").
  - hardware block: modems sold outright (price + postage_fee); BYO also allowed (FAQ).
  - 5G block (package_type "5G Wireless Broadband"): plan price, speeds in the description,
    and rental-only modems (rental_price per month) linked by assigned_plan_ids.
Skipped: fixed wireless speeds (fixed-line nbn only), the "free fibre upgrade" duplicates
(is_coat_upgrade, same price, shown to FTTN/FTTC/HFC), and the 4G home plan (no 4G kind).
The nbn page is required; the 5G page is optional (a warning if it fails).
"""
import html
import json
import re
import sys
import pathlib
from urllib.parse import urljoin

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, techs_for, tier_from, write_norm  # noqa: E402

BASE = "https://www.spintel.net.au"
NBN_URL = BASE + "/home-internet/nbn"
WIRELESS_URL = BASE + "/home-internet/wireless-internet"
PID = "spintel"
SRC = pathlib.Path(__file__).stem


def page_props(page):
    m = re.search(r'data-page="([^"]*)"', page)
    if not m:
        raise RuntimeError("spintel: no Inertia data-page attribute")
    return json.loads(html.unescape(m.group(1)))["props"]


def blocks(props, btype):
    return [b.get("data") or {} for b in props.get("initialBlocks") or [] if b.get("type") == btype]


def num(v):
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(v)) if v is not None else None
    return float(m.group(1)) if m else None


def strip_tags(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def faq_text(props):
    out = []
    for btype in ("predefined_faq", "faq"):
        for b in blocks(props, btype):
            for f in b.get("faqs") or []:
                out.append(strip_tags(f"{f.get('question') or f.get('title') or ''} {f.get('answer') or f.get('content') or ''}"))
    return " ".join(out)


def promo_of(p, price):
    """(promo, ongoing adjustment) from a plan's promo_credit fields."""
    credit = num(p.get("promo_credit"))
    if not (p.get("promo_valid") and credit and credit > 0):
        return None, 0.0
    kind, months = p.get("promo_credit_type"), int(num(p.get("promo_credit_months")) or 0)
    if kind == "recurring_months" and months > 0:
        return {"price": round(price - credit, 2), "months": months, "until": None,
                "text": p.get("promo_message") or f"${credit:g}/month off for {months} months"}, 0.0
    if kind == "recurring_indefinite":
        return None, credit
    return None, 0.0


def nbn_records(props, captured):
    faq = faq_text(props)
    hw = [h for b in blocks(props, "hardwares") for h in b.get("hardwares") or []
          if h.get("is_active") and str(h.get("is_rental")) in ("0", "-1") and num(h.get("price"))]
    modem = {"offer": "purchase", "cost": round(min(num(h["price"]) + (num(h.get("postage_fee")) or 0) for h in hw), 2)} \
        if hw else {"offer": "byo" if re.search(r"own compatible modem", faq, re.I) else "unknown", "cost": None}
    out, ids = [], set()
    for b in blocks(props, "plans"):
        if b.get("service_type") != "fibre":
            continue
        speeds = {s.get("id"): s for s in b.get("speeds") or []}
        contracts = {c.get("id"): c for c in b.get("contracts") or []}
        coat_sizes = {(s.get("downMbps"), s.get("upMbps")) for s in speeds.values() if str(s.get("is_coat_upgrade")) == "1"}
        for p in b.get("plans") or []:
            s = speeds.get(p.get("speed_id"))
            if not s or s.get("type") != "fibre" or str(s.get("is_coat_upgrade")) == "1":
                continue
            nom_down, nom_up = num(s.get("downMbps")), num(s.get("upMbps"))
            if not nom_down or not nom_up or num(p.get("priceEach")) is None:
                continue
            size = f"{int(nom_down)}/{int(nom_up)}"
            price = round(num(p["priceEach"]) + (num(s.get("price")) or 0), 2)
            promo, permanent_off = promo_of(p, price)
            price = round(price - permanent_off, 2)
            down, up = num(s.get("typicalDownMbps")), num(s.get("typicalUpMbps"))
            tier = tier_from(f"nbn {size}", down)
            shown = {t for t in p.get("show_when") or [] if t in ("fttp", "hfc", "fttc", "fttn", "fttb")}
            if "fttn" in shown:
                shown.add("fttb")
            techs = [t for t in techs_for("nbn", tier) if t in shown] or techs_for("nbn", tier)
            c = contracts.get(p.get("contract_id")) or {}
            setup = num(c.get("setup_fee"))
            if setup is None and re.search(r"\$0 standard setup", faq, re.I):
                setup = 0.0
            notes = []
            if promo:
                notes.append("Intro discount for new customers.")
            if permanent_off:
                notes.append(f"Includes a ${permanent_off:g}/month ongoing discount.")
            if (s.get("downMbps"), s.get("upMbps")) in coat_sizes:
                notes.append("Also offered with a free fibre upgrade to eligible FTTN/FTTC premises.")
            pid = f"{PID}-nbn-{size.replace('/', '-')}"
            while pid in ids:
                pid += "-2"
            ids.add(pid)
            out.append({
                "id": pid, "provider": PID, "name": f"{p.get('name') or p.get('title') or 'nbn'} {size}".replace("  ", " "),
                "kind": "nbn", "tier": tier, "techs": techs, "down": down, "up": up, "price": price, "promo": promo,
                "setup": setup, "contract": int(num(c.get("length")) or 0), "modem": dict(modem), "data_gb": None,
                "network": None, "credit": None, "bundle": [], "url": NBN_URL,
                "cis_url": urljoin(BASE, p["cis_pdf_url"]) if p.get("cis_pdf_url") else None,
                "source": SRC, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
            })
    return out


def fiveg_records(props, page, captured):
    text = strip_tags(page)
    nm = re.search(r"(Optus|Telstra|Vodafone) mobile network", text)
    network = nm.group(1).lower() if nm else None
    hw = [h for b in blocks(props, "hardwares") for h in b.get("hardwares") or [] if h.get("is_active")]
    out = []
    for b in blocks(props, "plans"):
        if "5g" not in str(b.get("package_type", "")).lower():
            continue
        contracts = {c.get("id"): c for c in b.get("contracts") or []}
        for p in b.get("plans") or []:
            if not p.get("is_5g") or num(p.get("priceEach")) is None:
                continue
            desc = strip_tags(p.get("description"))
            tm = re.search(r"Typical busy period speeds?:?\s*(\d+(?:\.\d+)?) ?Mbps download\s*/\s*(\d+(?:\.\d+)?) ?Mbps upload", desc, re.I)
            dm = re.search(r"Download (\d+(?:\.\d+)?) ?Mbps Upload (\d+(?:\.\d+)?) ?Mbps", desc, re.I)
            down, up = (float(tm.group(1)), float(tm.group(2))) if tm else \
                (float(dm.group(1)), float(dm.group(2))) if dm else (None, None)
            price = num(p["priceEach"])
            promo, permanent_off = promo_of(p, price)
            price = round(price - permanent_off, 2)
            kit = [h for h in hw if str(p.get("planId")) in [str(i) for i in h.get("assigned_plan_ids") or []]]
            notes, modem = [], {"offer": "unknown", "cost": None}
            rental = [h for h in kit if str(h.get("is_rental")) == "1" and num(h.get("rental_price"))]
            if rental:
                h = min(rental, key=lambda h: num(h["rental_price"]))
                modem = {"offer": "rental", "cost": num(h.get("postage_fee")) or 0.0, "monthly": num(h["rental_price"])}
                notes.append(f"Needs Spintel's rental 5G modem ({strip_tags(h.get('title'))}): "
                             f"${num(h['rental_price']):g}/month plus ${num(h.get('postage_fee')) or 0:g} postage, "
                             "on top of the plan price (counted in the costs here).")
            elif kit:
                h = min(kit, key=lambda h: num(h.get("price")) or 1e9)
                modem = {"offer": "purchase", "cost": round((num(h.get("price")) or 0) + (num(h.get("postage_fee")) or 0), 2)}
            if not tm:
                notes.append("Speeds as published on the plan card (Spintel describes them as typical busy-period speeds).")
            c = contracts.get(p.get("contract_id")) or {}
            out.append({
                "id": f"{PID}-5g-{int(down) if down else 'home'}", "provider": PID,
                "name": strip_tags(p.get("title") or p.get("name")), "kind": "5g", "tier": None, "techs": [],
                "down": down, "up": up, "price": price, "promo": promo, "setup": num(c.get("setup_fee")),
                "contract": int(num(c.get("length")) or 0), "modem": modem, "data_gb": None, "network": network,
                "credit": None, "bundle": [], "url": WIRELESS_URL,
                "cis_url": urljoin(BASE, p["cis_pdf_url"]) if p.get("cis_pdf_url") else None,
                "source": SRC, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
            })
    return out


def main():
    page = fetch(NBN_URL, RAW / SRC / "nbn.html").decode("utf-8")
    captured = now_iso()
    internet = nbn_records(page_props(page), captured)
    if not internet:
        raise RuntimeError("spintel: nbn page parsed to zero fixed-line plans")
    n5g = 0
    try:
        wpage = fetch(WIRELESS_URL, RAW / SRC / "wireless.html").decode("utf-8")
        recs = fiveg_records(page_props(wpage), wpage, captured)
        internet += recs
        n5g = len(recs)
    except Exception as e:  # noqa: BLE001
        print(f"warning: 5G page failed: {e}", file=sys.stderr)
    meta = {"name": "Spintel home internet pages", "url": NBN_URL, "urls": [NBN_URL, WIRELESS_URL], "fetched": captured}
    write_norm(SRC, {"internet": internet, "mobile": []}, meta)
    print(f"{SRC}: {len(internet)} internet ({len(internet) - n5g} nbn, {n5g} 5g)")


if __name__ == "__main__":
    main()

"""Superloop: residential nbn plans from its own plans page.

https://www.superloop.com/internet/nbn/ (robots.txt: "Allow: /").

Sources on that page:
  1. The Livewire snapshot of the "plan-selector.broadband-offers" component
     (wire:snapshot="..." attribute, JSON). It carries Superloop's own API objects
     (App\\Data\\SuperloopApi\\BroadbandOfferData): title, speeds, typicalEveningSpeed,
     contractMonths, price {amount, discount {amount, repeats, commenceAfter}}, specialOffer,
     priceNotes, planFeatures and the CIS link. This is what the plan cards render and is the
     primary source; the adapter fails if it is missing or empty.
     Before an address check the component shows the FTTP line-up only.
  2. JSON-LD ProductGroup "nbn plans": adds the plans that only appear for other connection
     types (Family 100/20 and Power Home 100/40 on FTTN/FTTC, Hyperspeed 2000/100 on HFC),
     with ongoing price (StrikethroughPrice), intro price (offers.price), typical evening speed
     and eligible connection types (material). The JSON-LD lags the live offers on some plans
     (e.g. Megaspeed and Lightspeed prices), so it is used only for plans missing from (1),
     and for connection types.

Livewire dehydrates arrays as [value, {"s": "arr"}] pairs; unwrap() strips that metadata.
Free modem ("Free modem option*") means a modem with no upfront cost if you stay connected for
24 months (payout fee otherwise): modem offer "included_contract". contractMonths is 0.
Bundle & Save: $5/mth off the internet bill with a Superloop mobile (or home phone) service.
"""
import html
import json
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

URL = "https://www.superloop.com/internet/nbn/"
PID = "superloop"
SRC = pathlib.Path(__file__).stem
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "twelve": 12}


def unwrap(x):
    if isinstance(x, list) and len(x) == 2 and isinstance(x[1], dict) and "s" in x[1]:
        return unwrap(x[0])
    if isinstance(x, list):
        return [unwrap(i) for i in x]
    if isinstance(x, dict):
        return {k: unwrap(v) for k, v in x.items()}
    return x


def as_list(x):
    return x if isinstance(x, list) else [x] if x else []


def strip_tags(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def speeds(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", s or "")
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def techs(tier, material):
    """techs_for(tier), narrowed to the published connection types (FTTB counted with FTTN)."""
    base = techs_for("nbn", tier)
    pub = {t.lower() for t in ([material] if isinstance(material, str) else material or [])}
    if not pub:
        return base
    if "fttn" in pub:
        pub.add("fttb")
    return [t for t in base if t in pub] or base


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    page = fetch(URL, RAW / SRC / "nbn.html").decode("utf-8")
    captured = now_iso()
    text = strip_tags(page[page.find("<body"):] if "<body" in page else page)

    offers = []
    for m in re.finditer(r'wire:snapshot="([^"]*)"', page):
        try:
            snap = json.loads(html.unescape(m.group(1)))
        except ValueError:
            continue
        if (snap.get("memo") or {}).get("name") == "plan-selector.broadband-offers":
            offers += as_list(unwrap(snap.get("data", {})).get("broadbandOffers"))
    offers = [o for o in offers if isinstance(o, dict) and str(o.get("product", "")).upper() == "RESIDENTIAL"]
    if not offers:
        raise RuntimeError("superloop: no broadband-offers Livewire snapshot (or no residential offers) on the page")

    ld = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "ProductGroup":
            ld += d.get("hasVariant") or []
    material = {v.get("size"): v.get("material") for v in ld if v.get("size")}

    sm = re.search(r"Sale ends (\d{1,2}) (\w+) (\d{4})", text) or re.search(r"Ends (\d{1,2}) (\w+) (\d{4})", text)
    sale_end = None
    if sm and sm.group(2).lower() in MONTHS:
        sale_end = date(int(sm.group(3)), MONTHS[sm.group(2).lower()], int(sm.group(1))).isoformat()
    bm = re.search(r"Add mobile, save \$(\d+(?:\.\d+)?)/mth on home internet", text) \
        or re.search(r"extra \$(\d+(?:\.\d+)?)/mth off your monthly internet bill", text)
    bundle = [{"with": "mobile", "off": float(bm.group(1)),
               "text": f"Bundle & Save: ${bm.group(1)}/mth off internet with a Superloop mobile plan"}] if bm else []

    internet, seen = [], set()
    for o in offers:
        down_nom, up_nom = num(o.get("downloadSpeed")), num(o.get("uploadSpeed"))
        if not down_nom or not up_nom:
            continue
        size = f"{int(down_nom)}/{int(up_nom)}"
        tes_down, tes_up = speeds(o.get("typicalEveningSpeed"))
        prices = [p for p in as_list(o.get("price")) if str(p.get("frequency", "MONTH")).upper() == "MONTH"]
        if not prices:
            continue
        p = prices[0]
        price = num(p.get("amount"))
        promo, notes = None, []
        for dsc in as_list(p.get("discount")):
            off, months = num(dsc.get("amount")), int(dsc.get("repeats") or 0)
            if off and months and not dsc.get("commenceAfter") and str(dsc.get("frequency", "MONTH")).upper() == "MONTH":
                promo = {"price": round(price - off, 2), "months": months,
                         "until": sale_end if o.get("specialOffer") else None,
                         "text": f"${off:g}/mth off for the first {months} months"
                                 + (f" ({o['specialOffer']})" if o.get("specialOffer") else "")}
                break
        if promo:
            notes.append("Intro discount for new customers only.")
        price_notes = [strip_tags(n) for n in as_list(o.get("priceNotes")) if isinstance(n, str) and n.strip()]
        notes += price_notes
        if o.get("specialOffer") and not promo and not price_notes:
            notes.append(strip_tags(o["specialOffer"]) + (f" (sale ends {sale_end})" if sale_end else ""))
        feats = " ".join(strip_tags(f.get("name")) for f in as_list(o.get("planFeatures")) if isinstance(f, dict))
        free_modem = re.search(r"(?<!No )Free modem option", feats, re.I) is not None
        if free_modem:
            notes.append("Free modem if you stay connected for 24 months (payout fee if you leave earlier).")
        tier = tier_from(f"nbn {size}", tes_down)
        internet.append({
            "id": f"{PID}-{slug(o.get('title', ''))}-{size.replace('/', '-')}", "provider": PID,
            "name": f"{o.get('title')} {size}", "kind": "nbn", "tier": tier, "techs": techs(tier, material.get(size)),
            "down": tes_down, "up": tes_up, "price": price, "promo": promo, "setup": None,
            "contract": int(o.get("contractMonths") or 0),
            "modem": {"offer": "included_contract" if free_modem else "purchase", "cost": None},
            "data_gb": None, "network": None, "credit": None, "bundle": [dict(b) for b in bundle], "url": URL,
            "cis_url": o.get("criticalInformationSummary"), "source": SRC, "captured": captured, "verified": True,
            "notes": " ".join(notes) or None,
        })
        seen.add(size)

    # Plans only offered on other connection types: from the JSON-LD.
    default_cis = next((r["cis_url"] for r in internet if r["cis_url"]), None)
    for v in ld:
        size = v.get("size")
        if not size or size in seen or not re.fullmatch(r"\d+/\d+", size):
            continue
        props = {p.get("name", "").lower(): p.get("value") for p in (v.get("offers") or {}).get("additionalProperty", [])}
        tes_down, tes_up = speeds(props.get("typical evening speed (7pm to 11pm)")
                                  or (re.search(r"Typical evening speed is ([\d./ ]+)", v.get("description", "")) or [None, ""])[1])
        off = v.get("offers") or {}
        strike = (off.get("priceSpecification") or {}).get("price")
        intro, ongoing = num(off.get("price")), num(strike) if strike is not None else num(off.get("price"))
        if ongoing is None:
            continue
        promo = None
        mm = re.search(r"(?:first|over) (\d+|one|two|three|four|six|twelve) months", v.get("description", ""), re.I)
        months = (int(mm.group(1)) if mm.group(1).isdigit() else WORDS[mm.group(1).lower()]) if mm else None
        if intro is not None and intro < ongoing and months:
            promo = {"price": intro, "months": months,
                     "until": sale_end if off.get("priceValidUntil") == sale_end else None,
                     "text": f"${ongoing - intro:g}/mth off for the first {months} months"}
        name = v.get("name", "").split(" - ")[0].strip()
        free_modem = "free router" in str(props.get("free router option") or props.get("free modem option") or "").lower()
        tier = tier_from(f"nbn {size}", tes_down)
        notes = ["Shown for FTTN/FTTC or HFC addresses; taken from the page's structured data."]
        if promo:
            notes.append("Intro discount for new customers only.")
        if free_modem:
            notes.append("Free modem if you stay connected for 24 months (payout fee if you leave earlier).")
        internet.append({
            "id": f"{PID}-{slug(name)}-{size.replace('/', '-')}", "provider": PID, "name": f"{name} {size}",
            "kind": "nbn", "tier": tier, "techs": techs(tier, v.get("material")), "down": tes_down, "up": tes_up,
            "price": ongoing, "promo": promo, "setup": None, "contract": 0,
            "modem": {"offer": "included_contract" if free_modem else "purchase", "cost": None},
            "data_gb": None, "network": None, "credit": None, "bundle": [dict(b) for b in bundle], "url": URL,
            "cis_url": default_cis, "source": SRC, "captured": captured, "verified": True, "notes": " ".join(notes),
        })
        seen.add(size)

    if not internet:
        raise RuntimeError("superloop: offers parsed to zero plans")
    meta = {"name": "Superloop nbn plans page", "url": URL, "fetched": captured, "sale_end": sale_end,
            "from_snapshot": len(offers), "from_jsonld": sum(1 for r in internet if "structured data" in (r["notes"] or ""))}
    write_norm(SRC, {"internet": internet, "mobile": []}, meta)
    print(f"{SRC}: {len(internet)} internet ({meta['from_jsonld']} from JSON-LD only)")


if __name__ == "__main__":
    main()

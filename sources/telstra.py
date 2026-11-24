"""Telstra: home internet plan cards on https://www.telstra.com.au/internet/plans.

The page is server-rendered (Adobe AEM) and loads with a plain GET. robots.txt allows
/internet/ for all user agents (our client name is not in its blocked AI-crawler list).

Each plan card is a <div class="tcom-fixed-plan-card-container ..." data-fixed-plan-card> and
carries its facts in data-* attributes, so parsing doesn't depend on the visible layout:
  data-tcom-fixed-plan-card-header-label          plan name ("Premium nbn®")
  data-tcom-fixed-plan-card-recurring-charge      ongoing monthly price
  data-tcom-fixed-plan-card-promo-recurring-charge / -promo-duration   intro price and months
  data-tcom-fixed-plancard-dsq-evening-download / -upload   typical busy-period (7-11pm) speeds
  data-plan-id                                    SKU (on the order buttons)
  data-fixed-plan-card-container-force-5g="true"  5G Home Internet cards
The same page has a schema.org ProductGroup (JSON-LD) per SKU with `material` (the nbn
technologies a SKU is sold on) and `priceValidUntil` (last day of the current offer); both are
used when present.

Notes on the content:
  - Two families: "Internet with modem and phone line" (SKU FSUBBDL-*, Smart Modem included for
    use, $200 non-return fee if you leave within 24 months) and "Internet Only" (FSUBDAT-*-V01,
    BYO or buy the Smart Modem outright; its price comes from data-fixed-modem-details-price).
  - Premium nbn® is sold as nbn 100 on FTTN/FTTB/FTTC and as nbn 500 on FTTP/HFC at the same
    price; both are kept, with techs narrowed to the SKU's `material`.
  - nbn Fixed Wireless cards (key-facts link to ...nbn-services-fw.pdf, or "fw" in the card id
    or SKU) become kind "fixed_wireless". Basic on Fixed Wireless shows a speed range ("2 - 23");
    the card's "50% of customers achieve ... greater than N Mbps (7pm-11pm)" figure is used.
  - 5G Home Internet: 1000 GB a month (then 1.5 Mbps), modem included for use, no install fee.
"""
import html
import json
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

URL = "https://www.telstra.com.au/internet/plans"
PID = "telstra"
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}
MATERIAL = {"FTTN": "fttn", "FTTB": "fttb", "FTTC": "fttc", "FTTP": "fttp", "UNITI_FTTP": "fttp",
            "HFC": "hfc", "FW": "fw"}


def attr(block, name):
    m = re.search(rf'\b{name}="([^"]*)"', block)
    return html.unescape(m.group(1)).strip() if m else None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def jsonld_products(page):
    """SKU -> schema.org Product from the page's ProductGroup blocks."""
    out = {}
    for blob in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob, strict=False)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "ProductGroup":
            for v in d.get("hasVariant") or []:
                if v.get("sku"):
                    out[v["sku"]] = v
    return out


def ends_date(s, today):
    """'Ends 30 November' -> ISO date, in the current year unless that date has already passed."""
    m = re.search(r"\bends?\s+(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?", s or "", re.I)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    y = int(m.group(3)) if m.group(3) else today.year
    d = date(y, MONTHS[m.group(2).lower()], int(m.group(1)))
    if not m.group(3) and d < today:
        d = date(y + 1, d.month, d.day)
    return d.isoformat()


def evening_down(card):
    v = attr(card, "data-tcom-fixed-plancard-dsq-evening-download")
    if num(v):
        return num(v)
    # A range such as "2 - 23" (Basic on Fixed Wireless): use the busy-hour median the card states.
    m = re.search(r"50% of customers achieve download speeds greater than (\d+(?:\.\d+)?)\s*Mbps", card)
    if m:
        return float(m.group(1))
    r = re.findall(r"\d+(?:\.\d+)?", v or "")
    return float(r[-1]) if r else None


def main():
    page = fetch(URL, RAW / "telstra" / "internet-plans.html").decode("utf-8")
    captured = now_iso()
    today = date.fromisoformat(captured[:10])
    products = jsonld_products(page)
    modem_price = num(attr(page, "data-fixed-modem-details-price"))
    starts = [m.start() for m in re.finditer(r'<div class="tcom-fixed-plan-card-container[^"]*"[^>]*\bdata-fixed-plan-card\b', page)]
    # A card runs to the next card; the last one is capped at 1.5x the longest card so the
    # modem section and FAQ that follow the cards don't leak into it.
    longest = max((b - a for a, b in zip(starts, starts[1:])), default=60000)
    ends = starts[1:] + [min(len(page), starts[-1] + int(1.5 * longest))] if starts else []
    internet, seen = [], set()
    for st, en in zip(starts, ends):
        card = page[st:en]
        head = re.match(r"<div[^>]*>", card).group(0)
        name = attr(card, "data-tcom-fixed-plan-card-header-label")
        price = num(attr(card, "data-tcom-fixed-plan-card-recurring-charge"))
        skus = sorted(set(re.findall(r'data-plan-id="([^"]+)"', card)))
        if not name or not price or len(skus) != 1:
            continue
        sku = skus[0]
        prod = products.get(sku, {})
        offers = prod.get("offers") or {}
        if "Discontinued" in (offers.get("availability") or ""):
            continue
        card_id = (attr(head, "id") or "").lower()
        links = [html.unescape(u) for u in re.findall(r'href="([^"]+)"', card)]
        cis = next((u for u in links if "critical-information-summaries" in u), None)
        five_g = attr(head, "data-fixed-plan-card-container-force-5g") == "true" or sku.endswith("-5G")
        fw = not five_g and ("fw" in card_id.split("-") or "-FW" in sku
                             or any("nbn-services-fw" in u for u in links))
        internet_only = sku.startswith("FSUBDAT") and not five_g
        tier_label = re.search(r'<div class="tcom-able__text-label-c">\s*([^<]*?)\s*</div>', card)
        tier_label = html.unescape(tier_label.group(1)) if tier_label else ""
        down = evening_down(card)
        up = num(attr(card, "data-tcom-fixed-plancard-dsq-evening-upload"))
        if five_g:
            kind, tier, techs = "5g", None, []
        elif fw:
            kind, tier, techs = "fixed_wireless", None, ["fw"]
        else:
            kind = "nbn"
            tier = tier_from(tier_label, None) or tier_from(name, down)
            techs = techs_for("nbn", tier)
            mat = {MATERIAL[t.strip()] for t in (prod.get("material") or "").split(",") if t.strip() in MATERIAL}
            if mat & set(techs):
                techs = [t for t in techs if t in mat]
        if kind == "nbn" and not tier:
            continue

        promo = None
        sec = re.search(r"<[^>]*data-tcom-fixed-plan-card-promo-duration=[^>]*>(.*?)</div>", card, re.S)
        sec_tag = sec.group(0) if sec else ""
        pprice = num(attr(sec_tag, "data-tcom-fixed-plan-card-promo-recurring-charge"))
        pmonths = num(attr(sec_tag, "data-tcom-fixed-plan-card-promo-duration"))
        if pprice and pmonths and pprice < price:
            badge = re.search(r'<span class="sr-only">([^<]*\boff\b[^<]*)</span>', card)
            ptext = "; ".join(x for x in [html.unescape(badge.group(1)).strip() if badge else None,
                                          text(sec.group(1))] if x)
            promo = {"price": pprice, "months": int(pmonths),
                     "until": offers.get("priceValidUntil") or ends_date(ptext, today), "text": ptext}

        if five_g:
            modem = {"offer": "included_contract", "cost": None, "fee": 200.0, "months": 24}
        elif internet_only:
            modem = {"offer": "purchase", "cost": modem_price}
        else:
            modem = {"offer": "included_contract", "cost": None, "fee": 200.0, "months": 24}
        notes = []
        if promo:
            notes.append("Intro price for new services only; the discount may end early if you change plans.")
        if modem["offer"] == "included_contract":
            notes.append("Modem included for use; return it or pay a $200 non-return fee if you leave within 24 months.")
        elif internet_only:
            notes.append("Internet only (no phone line); bring your own modem or buy Telstra's.")
        if kind == "nbn" and set(techs) != set(techs_for("nbn", tier)):
            notes.append(f"Sold on {', '.join(t.upper() for t in techs)} only.")
        if five_g:
            notes.append("1000 GB a month, then slowed to 1.5 Mbps. Limited services per postcode.")
        data_val = next((p.get("value", "") for p in prod.get("additionalProperty") or []
                         if p.get("name") == "data"), "")
        if not data_val:
            dm = re.search(r'tcom-fixed-plan-card-dsq__plan-size[^>]*>\s*(?:<a[^>]*>)?\s*([^<]+)', card)
            data_val = dm.group(1) if dm else ""
        dm = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", data_val, re.I)
        data_gb = None if "unlimited" in data_val.lower() or not dm else \
            float(dm.group(1)) * (1000 if dm.group(2).upper() == "TB" else 1)

        rid = f"{PID}-{slug(name)}" + (f"-{tier}" if kind == "nbn" else "-fixed-wireless" if fw else "")
        if rid in seen:
            continue
        seen.add(rid)
        internet.append({
            "id": rid, "provider": PID, "name": name, "kind": kind, "tier": tier, "techs": techs,
            "down": down, "up": up, "price": price, "promo": promo,
            "setup": 0.0 if five_g else None, "contract": 0, "modem": modem, "data_gb": data_gb,
            "network": "telstra" if five_g else None, "credit": None, "bundle": [],
            "url": URL, "cis_url": cis, "source": PID, "captured": captured, "verified": True,
            "notes": " ".join(notes) or None,
        })
    if not internet:
        raise RuntimeError("Telstra internet plans page parsed to zero plans; page layout may have changed")
    kinds = {k: sum(r["kind"] == k for r in internet) for k in ("nbn", "fixed_wireless", "5g")}
    if not kinds["nbn"]:
        raise RuntimeError("Telstra internet plans page parsed to no nbn plans; page layout may have changed")
    meta = {"name": "Telstra home internet plans", "url": URL, "fetched": captured,
            "modem_outright": modem_price}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"telstra: {len(internet)} internet ({', '.join(f'{v} {k}' for k, v in kinds.items())})")


if __name__ == "__main__":
    main()

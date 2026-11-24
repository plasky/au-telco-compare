"""Optus: nbn and 5G Home Internet plans from the plan-card data embedded in Optus's own pages.

https://www.optus.com.au/internet/nbn and https://www.optus.com.au/internet/5g-home-internet are
Adobe AEM pages whose plan cards are server-rendered with a JSON `datamodel` attribute. Each card
carries planPrice (the intro price), nonDiscountedPlanPrice (the ongoing price), typical busy-period
speeds, the technologies the offer is sold on, and the modem repayment terms. robots.txt allows both
pages (it disallows only /checkout/, */promotions and a few legacy paths).

Notes on the content:
  - The JSON-LD on the page lists only the intro price, so it is not used for prices.
  - Each plan has a card with the Optus modem and a BYO card at the same price; only the modem
    card is kept, with the BYO option mentioned in the notes.
  - "Fast" is one product sold as nbn 500 on FTTP/HFC and nbn 100 on FTTN/FTTC/FTTB, so it gives
    two records; techs are the provider's stated technologies within common.techs_for.
  - The intro offer length and end date come from the card's offer text ("Offer ends 6/12/26.
    Plan is $63/month for 12 months, then $83/month ...").
  - Setup = the card's "Minimum cost $X with modem" minus the first month and the modem cost
    (works out at $0 on every current plan); None if that text is missing.
"""
import html
import json
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "optus"
PAGES = {
    "nbn": "https://www.optus.com.au/internet/nbn",
    "5g": "https://www.optus.com.au/internet/5g-home-internet",
}
TECH = {"NBN FTTP": "fttp", "NBN Cable (HFC)": "hfc", "NBN HFC": "hfc", "NBN FTTC": "fttc",
        "NBN FTTN": "fttn", "NBN FTTB": "fttb"}


def text(s):
    s = html.unescape(html.unescape(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).replace(" Terms", "").strip()


def mbps(s):
    m = re.search(r"(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else None


def cards(page):
    """Plan-card datamodels: JSON objects in datamodel="..." attributes that carry plan prices."""
    for raw in re.findall(r'datamodel="(\{.*?\})"', page, re.S):
        try:
            d = json.loads(html.unescape(raw))
        except ValueError:
            continue
        if isinstance(d, dict) and "nonDiscountedPlanPrice" in d and "planId" in d:
            yield d


def offer_text(card):
    for b in card.get("promoBlock") or []:
        t = text(b.get("description"))
        if re.search(r"(?i)offer ends|for \d+ months", t) and "$" in t:
            return t
    return ""


def parse_date(t):
    m = re.search(r"(?i)(?:offer )?ends (\d{1,2})/(\d{1,2})/(\d{2,4})", t)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    return date(y + 2000 if y < 100 else y, mo, d).isoformat()


def record(card, kind, url, captured):
    title = re.sub(r"(?i)\s*plan$", "", card.get("title") or "").strip()
    tip = (card.get("speedDetailsBlock") or {}).get("tooltipDetails") or {}
    down, up = mbps(tip.get("downloadSpeed")), mbps(tip.get("uploadSpeed"))
    price = float(card["nonDiscountedPlanPrice"])
    intro = float(card["planPrice"]) if card.get("planPrice") is not None else price
    offer = offer_text(card)
    promo = None
    if intro < price:
        m = re.search(r"(?i)for (\d+) months", offer) or re.search(r"(?i)for (\d+) months", text(card.get("newDurationCopy")))
        if m:
            promo = {"price": intro, "months": int(m.group(1)), "until": parse_date(offer), "text": offer or None}

    related = [t.strip() for p in card.get("productOfferRelatedTechnologies") or []
               for t in (p.get("relatedTechnologies") or "").split(",")]
    stated = {TECH[t] for t in related if t in TECH}
    if kind == "nbn":
        tier = tier_from(f"{title} nbn", down)
        techs = [t for t in techs_for("nbn", tier) if not stated or t in stated]
        dual = stated and not stated & {"fttp", "hfc"}
        name = f"{title} nbn" + (" (FTTN/FTTB/FTTC)" if dual else "")
    else:
        tier, techs, name = None, [], f"{title} 5G"

    pp = ((card.get("phonePrice") or [{}])[0])
    model = (pp.get("productPriceModels") or [{}])[0]
    modem_cost = model.get("oldTotalRepaymentCharges")
    modem_months = pp.get("deviceContractLength")
    modem = {"offer": "included_contract", "cost": float(modem_cost)} if modem_cost else {"offer": "unknown", "cost": None}

    setup = None
    mc = re.search(r"(?i)minimum\s+cost\s*\$(\d+(?:\.\d+)?)", text(card.get("newDurationCopy")))
    if mc and modem_cost:
        s = round(float(mc.group(1)) - intro - float(modem_cost), 2)
        setup = s if s >= 0 else None

    notes = []
    if promo:
        notes.append("Intro price for new services; forfeited if you change or cancel the plan.")
    if modem_cost and modem_months:
        notes.append(f"Optus modem $0 if you stay {modem_months} months, else pay out the rest of ${modem_cost:g}"
                     + ("; BYO modem at the same price." if kind == "nbn" else "."))
    if re.search(r"(?i)netflix", json.dumps(card.get("promoBlock") or [])):
        notes.append("Includes a Netflix subscription.")

    return {
        "id": f"{PID}-{'5g-' if kind == '5g' else ''}{slug(title)}{'-' + str(tier) if kind == 'nbn' else ''}",
        "provider": PID, "name": name, "kind": kind, "tier": tier, "techs": techs,
        "down": down, "up": up, "price": price, "promo": promo, "setup": setup,
        "contract": 0 if (card.get("contractLength") or 1) <= 1 else int(card["contractLength"]),
        "modem": modem, "data_gb": None, "network": "optus" if kind == "5g" else None,
        "credit": None, "bundle": [], "url": url, "cis_url": None, "source": PID,
        "captured": captured, "verified": True, "notes": " ".join(notes) or None,
    }


def main():
    internet, captured = [], now_iso()
    for kind, url in PAGES.items():
        page = fetch(url, RAW / PID / f"{kind}.html").decode("utf-8", "replace")
        seen = {}
        for c in cards(page):
            pid = c["planId"]
            if pid not in seen or (seen[pid].get("byodPlan") and not c.get("byodPlan")):
                seen[pid] = c
        recs = [record(c, kind, url, captured) for c in seen.values()]
        recs = [r for r in recs if r["down"] and r["price"]]
        if not recs:
            raise RuntimeError(f"optus {kind}: no plan cards parsed from {url}; page layout may have changed")
        internet += recs
    ids = [r["id"] for r in internet]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"optus: duplicate record ids {ids}")
    meta = {"name": "Optus nbn and 5G Home Internet pages", "url": PAGES["nbn"], "fetched": captured}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"optus: {sum(r['kind'] == 'nbn' for r in internet)} nbn, {sum(r['kind'] == '5g' for r in internet)} 5g")


if __name__ == "__main__":
    main()

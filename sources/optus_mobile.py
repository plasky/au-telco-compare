"""Optus: SIM-only mobile plans (postpaid, data-only and prepaid) from the plan-card data on Optus's pages.

The pages are Adobe AEM pages like the internet ones: each plan card is server-rendered with a JSON
`datamodel` attribute carrying planId, title, planPrice (the price shown now), nonDiscountedPlanPrice
(the ongoing price), the data allowance, the period copy ("for 28 days") and the card's feature and
offer lines (promoBlock[*].promoBlockBody[*]). robots.txt allows all three pages (it disallows only
/checkout/, */promotions, */mobile/Landing-Pages and a few legacy paths).

  https://www.optus.com.au/mobile/plans/shop   postpaid SIM-only (Choice Plus, Plus Promo)
  https://www.optus.com.au/mobile/data-plans   postpaid data-only SIMs (Choice Plus Data)
  https://www.optus.com.au/prepaid/sim-plans   prepaid Flex Plus starter kits (7, 28, 186, 365 days)

Notes on the content:
  - The pages also carry many hidden terms blocks from expired campaigns, so offers are read only
    from each card's own lines, never from page-wide text.
  - Postpaid intro offers are applied in the cart, so planPrice can equal the ongoing price; the
    intro price then comes from the card copy ("Pay $39/month for a year, then $60/month").
  - Prepaid sale prices apply to the first (activation) recharge only, so promo periods = 1.
  - Prepaid cards are titled by the data on activation and the next two recharges ("110GB Prepaid
    SIM"); data_gb is the ongoing allowance ("then 35GB ongoing") and the bonus goes in the notes.
    AutoRecharge bonus data ("5GB bonus data every recharge") is also left to the notes.
  - Included international calls: postpaid Medium/Large/Promo include unlimited calls to the
    destinations listed on the page; prepaid recharges include minutes to the page's Zone 1 list
    (and Zone 2, not listed here). Destination names are mapped to ISO codes below.
  - Postpaid plans have no excess data charges: speed drops to 1.5Mbps after the allowance.
  - CIS links are built by the page's JavaScript from an API path, so cis_url is left empty.
"""
import html
import json
import re
import sys
import pathlib
from datetime import date, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

PID = "optus"
STEM = "optus_mobile"
PAGES = {
    "postpaid": "https://www.optus.com.au/mobile/plans/shop",
    "data": "https://www.optus.com.au/mobile/data-plans",
    "prepaid": "https://www.optus.com.au/prepaid/sim-plans",
}
ISO = {
    "argentina": "AR", "bahrain": "BH", "bangladesh": "BD", "belgium": "BE", "brazil": "BR",
    "brunei": "BN", "cambodia": "KH", "canada": "CA", "china": "CN", "mainland china": "CN",
    "colombia": "CO", "columbia": "CO", "denmark": "DK", "france": "FR", "germany": "DE",
    "greece": "GR", "hong kong": "HK", "hungary": "HU", "india": "IN", "indonesia": "ID",
    "ireland": "IE", "israel": "IL", "italy": "IT", "japan": "JP", "laos": "LA", "lebanon": "LB",
    "malaysia": "MY", "malta": "MT", "mexico": "MX", "netherlands": "NL", "new zealand": "NZ",
    "norway": "NO", "philippines": "PH", "poland": "PL", "portugal": "PT", "romania": "RO",
    "singapore": "SG", "south korea": "KR", "korea": "KR", "spain": "ES", "sri lanka": "LK",
    "sweden": "SE", "switzerland": "CH", "taiwan": "TW", "thailand": "TH", "turkey": "TR",
    "uk": "GB", "united kingdom": "GB", "usa": "US", "united states": "US", "vietnam": "VN",
}


def text(s):
    s = html.unescape(html.unescape(s or ""))
    s = re.sub(r"<[^>]+>", " ", s).replace("​", "")
    return re.sub(r"\s+", " ", s.replace("\\n", " ")).strip()


def page_text(page):
    return text(page)


def cards(page):
    for raw in re.findall(r'datamodel="(\{.*?\})"', page, re.S):
        try:
            d = json.loads(html.unescape(raw))
        except ValueError:
            continue
        if isinstance(d, dict) and "nonDiscountedPlanPrice" in d and "planId" in d:
            yield d


def lines(card):
    out = []
    for b in card.get("promoBlock") or []:
        for body in b.get("promoBlockBody") or []:
            for k in ("bodyTitle", "bodyDescription"):
                t = text(body.get(k))
                t = re.sub(r"\s*All for use within Australia.*$|\s*Terms$", "", t)
                if t:
                    out.append(t)
    return out


def gb(s):
    if re.search(r"(?i)unlimited", s or ""):
        return -1
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", s or "", re.I)
    return float(m.group(1)) if m else None


def end_date(t, today):
    """'Ends 6/12/26', 'Offer ends 06/12/2026' or 'Ends 6/12.' (no year: the next such date)."""
    m = re.search(r"(?i)ends (\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    if m.group(3):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
    else:
        y = today.year if (mo, d) >= (today.month, today.day) else today.year + 1
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def destinations(s):
    names = re.split(r",\s*|\s+and\s+", s.strip().rstrip("."))
    codes = [ISO.get(n.strip().lower()) for n in names if n.strip()]
    return None if not codes or None in codes else sorted(set(codes), key=codes.index)


def intl_lists(pt):
    """Destination lists from the page text: postpaid 'To selected destinations: ...' and prepaid Zone 1."""
    post = re.search(r"(?:To selected destinations|can be used to the following selected destinations):\s*(.*?)\.\s*Destinations are subject to change", pt)
    zone1 = re.search(r"Zone 1\s*:\s*(.*?)\.\s", pt)
    return (destinations(post.group(1)) if post else None), (destinations(zone1.group(1)) if zone1 else None)


def postpaid(card, kind, url, pt, intl_post, captured, today):
    name = text(card.get("title"))
    price = float(card["nonDiscountedPlanPrice"])
    ls = lines(card)
    copy = text(card.get("newDurationCopy"))
    data_only = kind == "data"
    data = gb(" ".join(d.get("data", "") for d in card.get("dataBlock") or []))
    alltext = " ".join([copy] + ls)

    intro, periods = None, None
    if card.get("planPrice") is not None and float(card["planPrice"]) < price:
        intro = float(card["planPrice"])
    m = re.search(r"\$(\d+(?:\.\d+)?)/month for (?:the )?(?:first )?(\d+) months", alltext) \
        or re.search(r"\$(\d+(?:\.\d+)?)/month for a year", alltext)
    if m:
        intro = min(intro or price, float(m.group(1)))
        periods = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 12
    if intro is not None and not periods:
        mm = re.search(r"(?i)for (\d+) months", alltext)
        periods = int(mm.group(1)) if mm else (12 if re.search(r"(?i)for a year", alltext) else None)
    promo = None
    if intro is not None and intro < price and periods:
        offer = [l for l in ls if re.search(r"(?i)\bdeal\b|\boffer|\bends\b|withdrawn|for a year|for \d+ months|then \$", l)
                 and not re.search(r"(?i)roaming|credit to spend|unlimited data day", l)]
        until = None if re.search(r"(?i)until withdrawn", alltext) else end_date(alltext, today)
        promo = {"price": intro, "periods": periods, "until": until, "text": " ".join(offer) or copy}

    has_intl = any(re.search(r"(?i)international talk & text to \d+ destinations", l) for l in ls)
    intl = intl_post if has_intl else None
    notes = []
    if has_intl and not intl:
        notes.append("Includes calls to selected international destinations (list not parsed).")
    bonus = [l for l in ls if re.search(r"(?i)GB/month for a year", l)] or [l for l in ls if re.search(r"(?i)extra \d+GB", l)]
    if bonus:
        notes.append("Bonus data: " + re.sub(r"\s*Offer applied in cart\..*", "", bonus[0]).rstrip(".") + ".")
    for l in ls:
        if re.search(r"(?i)credit to spend on subscriptions", l):
            notes.append(f"SubHub: {l[0].lower() + l[1:]}.")
    if promo:
        notes.append("Intro offer for new services; reverts to the standard price after the offer.")
    if re.search(r"(?i)no excess data charges", alltext) and re.search(r"1\.5\s*Mbps", pt):
        notes.append("No excess data charges: speed slowed to 1.5Mbps after the allowance.")
    return {
        "id": f"{PID}-mobile-{slug(name)}", "provider": PID, "name": name, "network": "optus",
        "type": "prepaid" if card.get("isPrepaid") else "postpaid", "period_days": 30, "price": price,
        "data_gb": data, "data_only": data_only,
        "calls": "none" if data_only else "unlimited" if re.search(r"(?i)unlimited standard national talk", alltext) else "unknown",
        "five_g": bool(re.search(r"5G", alltext) or re.search(r"5G Network Access", pt)),
        "intl": intl, "promo": promo, "contract": 0 if (card.get("contractLength") or 1) <= 1 else int(card["contractLength"]),
        "rollover": None, "bundle": [], "credit": None, "url": url, "cis_url": None, "source": STEM,
        "captured": captured, "verified": True, "notes": " ".join(notes) or None,
    }


def prepaid(card, url, zone1, captured, today):
    price = float(card["nonDiscountedPlanPrice"])
    ls = lines(card)
    copy = text(card.get("newDurationCopy"))
    m = re.search(r"(\d+)\s*days", copy)
    if not m:
        return None
    days = int(m.group(1))
    alltext = " ".join([copy] + ls)
    title = text(card.get("title"))

    data = gb(" ".join(d.get("data", "") for d in card.get("dataBlock") or []))
    notes = []
    m = re.search(r"(\d+)GB on activation and next two recharges, then (\d+)GB ongoing", alltext)
    if m:
        data = float(m.group(2))
        notes.append(f"{m.group(1)}GB on activation and the next two recharges, then {m.group(2)}GB.")
    m = re.search(r"(\d+)GB bonus data every recharge", alltext)
    if m:
        notes.append(f"+{m.group(1)}GB bonus data every recharge with AutoRecharge on.")
    if re.search(r"(?i)AutoRecharge only", alltext):
        notes.append("AutoRecharge only.")
    m = re.search(r"(?i)\$(\d+) eGift Card on first three eligible AutoRecharges, then \$(\d+) ongoing", alltext)
    if m:
        notes.append(f"${m.group(1)} eGift card on the first three AutoRecharges, then ${m.group(2)}.")
    if re.search(r"(?i)unlimited data weekends", alltext):
        notes.append("Unlimited data on weekends.")

    promo = None
    if card.get("planPrice") is not None and float(card["planPrice"]) < price:
        sale = next((l for l in ls if re.search(r"(?i)\bsale\b|\bends\b", l)), "")
        promo = {"price": float(card["planPrice"]), "periods": 1, "until": end_date(sale, today),
                 "text": f"${float(card['planPrice']):g} for the first {days} days, then ${price:g}. {sale}".strip()}
        notes.append("Sale price on the activation recharge only" + (", online only." if re.search(r"(?i)online only", sale) else "."))

    has_intl = any(re.search(r"(?i)international call minutes", l) for l in ls)
    if has_intl:
        notes.append("Includes international call minutes to Zone 1 (listed) and Zone 2 destinations; allowance varies by recharge.")
    return {
        "id": f"{PID}-mobile-flex-plus-{price:g}".replace(".", "-"), "provider": PID,
        "name": f"Flex Plus ${price:g} prepaid", "network": "optus", "type": "prepaid",
        "period_days": days, "price": price, "data_gb": data, "data_only": False,
        "calls": "unlimited" if re.search(r"(?i)unlimited aus standard talk", alltext) else "unknown",
        "five_g": bool(re.search(r"5G", alltext)), "intl": zone1 if has_intl else None, "promo": promo,
        "contract": 0, "rollover": bool(re.search(r"(?i)data rollover", alltext)), "bundle": [], "credit": None,
        "url": url, "cis_url": None, "source": STEM, "captured": captured, "verified": True,
        "notes": (f"Sold as the '{title}' starter kit. " + " ".join(notes)).strip(),
    }


def main():
    mobile, captured = [], now_iso()
    today = datetime.fromisoformat(captured.replace("Z", "+00:00")).date()
    for kind, url in PAGES.items():
        page = fetch(url, RAW / STEM / f"{kind}.html", min_interval=2.0, retries=2).decode("utf-8", "replace")
        pt = page_text(page)
        intl_post, zone1 = intl_lists(pt)
        seen = {}
        for c in cards(page):
            seen.setdefault(c["planId"], c)
        if kind == "prepaid":
            recs = [prepaid(c, url, zone1, captured, today) for c in seen.values() if c.get("isPrepaid")]
        else:
            recs = [postpaid(c, kind, url, pt, intl_post, captured, today) for c in seen.values() if not c.get("isPrepaid")]
        recs = [r for r in recs if r and r["price"] and r["data_gb"] is not None]
        if not recs:
            raise RuntimeError(f"optus_mobile {kind}: no plan cards parsed from {url}; page layout may have changed")
        mobile += recs
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"optus_mobile: duplicate record ids {sorted(ids)}")
    mobile.sort(key=lambda r: (r["type"], r["data_only"], r["period_days"], r["price"]))
    meta = {"name": "Optus SIM-only, data-only and prepaid plan cards", "url": PAGES["postpaid"], "fetched": captured}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"optus_mobile: {sum(r['type'] == 'postpaid' for r in mobile)} postpaid, "
          f"{sum(r['type'] == 'prepaid' for r in mobile)} prepaid")


if __name__ == "__main__":
    main()

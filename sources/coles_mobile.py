"""Coles Mobile (provider id "coles-mobile"): prepaid SIM plans from the catalogue JSON its own
site loads (Broadleaf Commerce back end behind an Angular front end, Optus network).

Three requests per run (robots.txt disallows only /pages/*, the logged-in dashboard):
  https://www.colesmobile.com.au/api/v1/ui/catalog/product      required
      every plan for sale: name, validity (days), retailPrice (ongoing), price (price now),
      allowanceMb (data per recharge), allowanceMin (-1 = unlimited calls), networkBand,
      planType (PREPAID = 28/365-day recharge, PREPAID_MONTHLY = auto-renewing monthly),
      planTemplateId, and activeDiscount: the current new-service offer (AMOUNT_OFF price
      discount and/or EXTRA_ALLOWANCE bonus data, validTo, numberOfRecharges, and texts such
      as "Ongoing is $35 for 45GB/month. Price offer ends 22/12/26 ..." and
      priceRechargeText "First month" / "First year").
  https://www.colesmobile.com.au/api/v1/ui/widget/plan-template  optional
      the plan-card templates keyed by planTemplateId, whose text says "Unlimited standard
      international calls ... to 15 selected destinations", "5G & 4G compatible (100 Mbps max
      speed)" or "4G compatible (4G uncapped)". Used for the number of international
      destinations, 5G and speed caps; the run carries on without it.
  https://www.colesmobile.com.au/api/v1/ui/page/terms            optional
      the terms page (colesmobile.com.au/terms) as CMS JSON; its "gjs-html" has one sentence
      per plan group: "International destinations include Bangladesh, Canada, mainland China,
      ... and Vietnam." The lists are matched to plans by their length (a plan's template says
      "to 22 selected destinations"), so a list is only used when the counts agree.
The site's plan pages are drawn by JavaScript from these same feeds.

Notes on the content:
  - intl is [] when the plan's template has no international calls, and None (with the count in
    notes) when the terms page can't be read, a country name isn't in COUNTRY, or no list has
    the template's count.
  - A HYBRID discount is a price cut for the first recharge (or first year) plus bonus data for
    more recharges; the price cut becomes promo, the bonus data goes in notes and data_gb stays
    the ongoing allowance. Offers are for new services only.
  - Unused data rolls over (up to 500GB on 28/365-day plans, 1000GB on monthly plans).
  - promo.until is the UTC date of the discount's validTo, which matches the "offer ends"
    date in the offer text.
"""
import gzip
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

BASE = "https://www.colesmobile.com.au"
URL = BASE + "/api/v1/ui/catalog/product"
TEMPLATES = BASE + "/api/v1/ui/widget/plan-template"
TERMS = BASE + "/api/v1/ui/page/terms"
CIS = BASE + "/home/page/critical-information"
COUNTRY = {   # names as written on the Coles terms page (and a few likely additions)
    "argentina": "AR", "austria": "AT", "bangladesh": "BD", "belgium": "BE", "brazil": "BR",
    "cambodia": "KH", "canada": "CA", "chile": "CL", "china": "CN", "mainland china": "CN",
    "colombia": "CO", "croatia": "HR", "cyprus": "CY", "czech republic": "CZ", "denmark": "DK",
    "fiji": "FJ", "finland": "FI", "france": "FR", "germany": "DE", "greece": "GR",
    "hong kong": "HK", "hungary": "HU", "iceland": "IS", "india": "IN", "indonesia": "ID",
    "ireland": "IE", "israel": "IL", "italy": "IT", "japan": "JP", "lebanon": "LB",
    "luxembourg": "LU", "macau": "MO", "malaysia": "MY", "malta": "MT", "mexico": "MX",
    "nepal": "NP", "netherlands": "NL", "new zealand": "NZ", "norway": "NO", "pakistan": "PK",
    "peru": "PE", "philippines": "PH", "poland": "PL", "portugal": "PT", "romania": "RO",
    "singapore": "SG", "south africa": "ZA", "south korea": "KR", "spain": "ES",
    "sri lanka": "LK", "sweden": "SE", "switzerland": "CH", "taiwan": "TW", "thailand": "TH",
    "turkey": "TR", "united kingdom": "GB", "uk": "GB", "united states": "US", "usa": "US",
    "vietnam": "VN",
}
PID = "coles-mobile"
STEM = pathlib.Path(__file__).stem


def get_json(url, name):
    body = fetch(url, RAW / STEM / name, min_interval=3.0)
    if body[:2] == b"\x1f\x8b":          # the server sometimes gzips without being asked
        body = gzip.decompress(body)
    return json.loads(body)


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def template_texts():
    try:
        items = get_json(TEMPLATES, "plan-template.json")
    except Exception as e:  # optional source
        print(f"{STEM}: plan templates not read ({e})", file=sys.stderr)
        return {}
    out = {}
    for t in items if isinstance(items, list) else []:
        props = t.get("props")
        try:
            props = json.loads(props) if isinstance(props, str) else (props or {})
        except ValueError:
            props = {}
        out[str(t.get("id"))] = clean(" ".join(str(v) for k, v in props.items() if "content-1" in k))
    return out


def intl_lists():
    """{count: [ISO codes]} from the terms page's "International destinations include ..." lists."""
    try:
        page = get_json(TERMS, "terms.json")
    except Exception as e:  # optional source
        print(f"{STEM}: terms page not read ({e})", file=sys.stderr)
        return {}
    text = clean(page.get("gjs-html") if isinstance(page, dict) else "")
    out = {}
    for m in re.finditer(r"International destinations include ([^.]+)\.", text):
        names = [n.strip().lower() for n in re.split(r",\s*|\s+and\s+", m.group(1)) if n.strip()]
        codes = [COUNTRY.get(n) for n in names]
        if names and all(codes):
            out.setdefault(len(codes), list(dict.fromkeys(codes)))
        else:
            print(f"{STEM}: unknown destination names {[n for n, c in zip(names, codes) if not c]}", file=sys.stderr)
    return out


def periods_from(text, default):
    t = (text or "").lower()
    m = re.search(r"first (\d+)", t)
    if m:
        return int(m.group(1))
    if re.search(r"first (month|year|recharge)\b", t):
        return 1
    return default or 1


def main():
    products = get_json(URL, "catalog-product.json")
    templates = template_texts()
    lists = intl_lists()
    captured = now_iso()
    mobile, skipped = [], []
    for p in products if isinstance(products, list) else []:
        if not p.get("active") or p.get("archived") == "Y" or p.get("affiliateProduct"):
            continue
        name = (p.get("name") or "").strip()
        try:
            ongoing = float(p["retailPrice"])
            period = int(p["validity"])
            data_gb = round(float(p["allowanceMb"]) / 1024, 2)
        except (KeyError, TypeError, ValueError):
            skipped.append(f"{name or p.get('id')}: no price, validity or allowance")
            continue
        tmpl = templates.get(str(p.get("planTemplateId")), "")
        low = f"{name} {tmpl}".lower()
        mins = p.get("allowanceMin")
        data_only = mins == 0 and "data" in name.lower()
        notes = []
        if p.get("planType") == "PREPAID_MONTHLY":
            notes.append("Prepaid monthly plan that renews automatically each calendar month.")
        promo = None
        d = p.get("activeDiscount") or {}
        meta = d.get("metaData") or {}
        until = (d.get("validTo") or "")[:10] or None
        if d.get("discountValueType") == "AMOUNT_OFF" and d.get("discountValue"):
            pp = round(ongoing - float(d["discountValue"]), 2)
            if 0 < pp < ongoing:
                promo = {"price": pp, "periods": periods_from(meta.get("priceRechargeText"), d.get("numberOfRecharges")),
                         "until": until, "text": meta.get("promoPriceDescription") or d.get("displayName")}
        if d.get("additionalAllowance"):
            bonus = round(float(d["additionalAllowance"]) / 1024, 2)
            when = (meta.get("dataRechargeText") or f"first {d.get('numberOfRecharges') or 1} recharges").lower()
            text = f"{meta.get('promoPriceDescription') or ''} {clean(d.get('termsAndConditions'))}"
            ends = re.search(r"bonus data offer ends (\d{1,2}/\d{1,2}/\d{2,4})", text, re.I) \
                or (None if promo else re.search(r"\bends (\d{1,2}/\d{1,2}/\d{2,4})", text, re.I))
            by = re.search(r"activate by (\d{1,2}/\d{1,2}/\d{2,4})", text, re.I)
            notes.append(f"Bonus {bonus:g}GB for the {when} on new services"
                         + (f" (sign up by {ends.group(1)}" if ends else "")
                         + (f", activate by {by.group(1)})" if by and ends else f" (activate by {by.group(1)})" if by else ")" if ends else "")
                         + ".")
        if promo or d:
            notes.append("Offers are for new services only.")
        im = re.search(r"international calls[^.]*?to (\d+) selected destinations", tmpl, re.I)
        if im:
            intl = lists.get(int(im.group(1)))
            if intl is None:
                notes.append(f"Unlimited standard calls to {im.group(1)} selected countries (list at colesmobile.com.au/terms).")
        elif tmpl:
            intl = []
        else:
            intl = None
        cap = re.search(r"\((\d+)\s*mbps max", low)
        if cap:
            notes.append(f"Speed capped at {cap.group(1)} Mbps.")
        net = "optus" if ("optus" in (p.get("url") or "").lower() or "optus" in clean(p.get("defaultSku", {}).get("longDescription")).lower()) else None
        mobile.append({
            "id": f"{PID}-{slug(re.sub(r'\(.*?\)|coles mobile', '', name, flags=re.I))}-{period}d", "provider": PID, "name": name,
            "network": net, "type": "prepaid", "period_days": period, "price": ongoing, "data_gb": data_gb,
            "data_only": data_only,
            "calls": "none" if data_only else "unlimited" if mins == -1 else "limited" if mins else "unknown",
            "five_g": p.get("networkBand") == "5G" or "5g" in low, "intl": intl, "promo": promo,
            "contract": 0, "rollover": "rollover" in clean(p.get("defaultSku", {}).get("longDescription")).lower()
            or "rollover" in tmpl.lower() or None,
            "credit": None, "url": BASE + (p.get("url") or "/plans"), "cis_url": CIS, "source": STEM,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })
    for s in skipped:
        print(f"{STEM}: skipped {s}", file=sys.stderr)
    if not mobile:
        raise RuntimeError("Coles Mobile catalogue parsed to zero plans; feed may have moved or changed")
    meta = {"name": "Coles Mobile plan catalogue (site JSON)", "url": URL, "templates": TEMPLATES, "terms": TERMS,
            "fetched": captured, "skipped": skipped}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"{STEM}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

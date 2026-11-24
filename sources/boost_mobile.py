"""Boost Mobile: prepaid SIM+ recharges (7 day, 28 day and 6/12-month long expiry).

https://boost.com.au/prepaid-plans is server-rendered (Telstra's Adobe AEM stack) and loads with a
plain GET; robots.txt allows everything except /search. One request per run.

Each plan is an <article data-boost-product-card data-boost-product-card-attributes="{json}">
whose JSON carries basePrice, discount, productTotal (the SIM-pack price incl. first recharge),
sku, id, productSubType, totalDataAllowance and dataAllowanceDetails ("30GB + 50GB Bonus
data"). The page also has a schema.org Product per SKU with offers.priceValidUntil (last day of
the current SIM deal). The first cards are a featured carousel that repeats later cards, so
cards are de-duplicated by product id. Expiry comes from the card text ("28 day expiry",
"12 MONTH EXPIRY"). The "Unlimited Int'l Calls to 20 destinations" country list comes from the
page's "$39 - $74 Recharge/SIM pack includes ..." dialogs (one per price band).

Notes on the content:
  - data_gb is the ongoing allowance (the first figure in dataAllowanceDetails); activation
    bonus data is kept in notes.
  - SIM deals ("Price: $12 Was $39 ... Ongoing recharges full price. Online only.") cover the
    first recharge only, so the promo is one period.
  - The CIS (MOSC2135, 5 May 2026) says data rollover is not included on $14, $180, $300 and
    $365; the cards agree (no "Data Rollover" feature on those).
  - 6-month expiry is counted as 183 days, 12 months as 365.
"""
import html
import json
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, write_norm  # noqa: E402

PID = "boost-mobile"
STEM = "boost_mobile"
BASE = "https://boost.com.au"
URL = BASE + "/prepaid-plans"
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                      "sep", "oct", "nov", "dec"], 1)}
COUNTRIES = {
    "argentina": "AR", "austria": "AT", "bangladesh": "BD", "brazil": "BR", "cambodia": "KH",
    "canada": "CA", "chile": "CL", "china": "CN", "colombia": "CO", "denmark": "DK",
    "finland": "FI", "france": "FR", "germany": "DE", "greece": "GR", "hong kong": "HK",
    "india": "IN", "indonesia": "ID", "iran": "IR", "iraq": "IQ", "ireland": "IE", "israel": "IL",
    "italy": "IT", "japan": "JP", "kuwait": "KW", "malaysia": "MY", "mexico": "MX", "nepal": "NP",
    "netherlands": "NL", "new zealand": "NZ", "norway": "NO", "pakistan": "PK", "peru": "PE",
    "philippines": "PH", "poland": "PL", "qatar": "QA", "romania": "RO", "saudi arabia": "SA",
    "serbia": "RS", "singapore": "SG", "south africa": "ZA", "south korea": "KR", "spain": "ES",
    "sri lanka": "LK", "sweden": "SE", "taiwan": "TW", "thailand": "TH", "uae": "AE",
    "united arab emirates": "AE", "uk": "GB", "united kingdom": "GB", "usa": "US",
    "united states": "US", "vietnam": "VN",
}


def text(fragment):
    fragment = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragment or "", flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("​", "")
    return re.sub(r"\s+", " ", t).strip()


def gb(v):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)", v or "", re.I)
    if not m:
        return None
    return float(m.group(1)) * {"gb": 1, "tb": 1000, "mb": 0.001}[m.group(2).lower()]


def jsonld_offers(page):
    """SKU -> schema.org Offer from the page's Product blocks."""
    out = {}
    for blob in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(blob, strict=False)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product" and d.get("sku"):
            out.setdefault(d["sku"], d.get("offers") or {})
    return out


def intl_bands(page):
    """[(lo, hi, [ISO codes with unlimited calls], extra-minutes text)] from the dialogs."""
    bands, unknown = [], []
    for m in re.finditer(r"\$(\d+)\s*-\s*\$(\d+) Recharge/SIM pack includes the following international inclusions", page):
        body = page[m.end():m.end() + 6000]
        um = re.search(r"Unlimited international standard calls to the following \d+ destinations:\s*</p>\s*<ul>(.*?)</ul>", body, re.S)
        if not um:
            continue
        codes = []
        for name in re.findall(r"<li>(.*?)</li>", um.group(1), re.S):
            name = text(name)
            code = COUNTRIES.get(name.lower())
            if code and code not in codes:
                codes.append(code)
            elif not code:
                unknown.append(name)
        pm = re.search(r"Plus (\d+) mins of standard calls to the following (\d+) destinations", body)
        tm = re.search(r"Plus (\d+) standard texts to international destinations", body)
        extra = "; ".join(x for x in [f"plus {pm.group(1)} min to {pm.group(2)} other countries" if pm else None,
                                      f"{tm.group(1)} international texts" if tm else None] if x)
        if not any(b[0] == int(m.group(1)) for b in bands):
            bands.append((int(m.group(1)), int(m.group(2)), codes, extra))
    return bands, sorted(set(unknown))


def sale_end(s, today):
    """'Sale ends 30 Nov' -> ISO date, this year unless that date has already passed."""
    m = re.search(r"Sale ends (\d{1,2}) ([A-Za-z]{3})[a-z]*(?: (\d{4}))?", s or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    y = int(m.group(3)) if m.group(3) else today.year
    d = date(y, MONTHS[m.group(2).lower()], int(m.group(1)))
    if not m.group(3) and d < today:
        d = date(y + 1, d.month, d.day)
    return d.isoformat()


def main():
    page = fetch(URL, RAW / STEM / "prepaid-plans.html", min_interval=2.0).decode("utf-8")
    captured = now_iso()
    today = date.fromisoformat(captured[:10])
    offers = jsonld_offers(page)
    bands, unknown = intl_bands(page)
    starts = [m.start() for m in re.finditer(r"<article[^>]*\bdata-boost-product-card\b", page)]
    ends = starts[1:] + [len(page)]
    mobile, seen = [], set()
    for a_, b_ in zip(starts, ends):
        card = page[a_:min(b_, a_ + 20000)]
        tag = re.match(r"<article[^>]*>", card).group(0)
        am = re.search(r'data-boost-product-card-attributes="([^"]*)"', tag)
        if not am:
            continue
        try:
            a = json.loads(html.unescape(am.group(1)))
        except ValueError:
            continue
        pid, sku = a.get("id"), a.get("sku")
        if not pid or pid in seen or a.get("productSubType") not in ("Core", "Casual") \
                or a.get("productType") != "SIMKits":
            continue
        body = text(card)
        em = re.search(r"\b(\d+)\s*(day|month)\s+expiry", body, re.I)
        price = a.get("basePrice")
        if not em or not isinstance(price, (int, float)) or price <= 0:
            continue
        seen.add(pid)
        price = float(price)
        n, unit = int(em.group(1)), em.group(2).lower()
        period = n if unit == "day" else 365 if n == 12 else round(n * 30.4375)
        details = a.get("dataAllowanceDetails") or ""
        data_gb = gb(details.split("+")[0]) if details else gb(a.get("totalDataAllowance"))
        intl, intl_note = None, None
        if re.search(r"Unlimited Int'l Calls to \d+ destinations", body):
            band = next((b for b in bands if b[0] <= price <= b[1]), None)
            if band:
                intl = list(band[2])
                intl_note = band[3]
        notes = []
        bm = re.search(r"(\d+GB on first (?:\d+ recharges|recharge) for new activations[^.]*\.)"
                       r"(?: (\d+GB from [^.]+\.))?(?: (Activate by [^.]+\.))?", body)
        if bm and "bonus" in details.lower():
            notes.append("Activation bonus: " + " ".join(x for x in bm.groups() if x))
        if intl:
            notes.append(f"Unlimited standard calls to {len(intl)} countries" + (f"; {intl_note}." if intl_note else "."))
        sm = re.search(r"5G with (\d+)\s*Mbps download speed\s*cap", body)
        if sm:
            notes.append(f"Download speed capped at {sm.group(1)} Mbps.")
        elif "uncapped download speed" in body.lower():
            notes.append("Uncapped download speed.")
        if a.get("offerType") == "digitalESIM":
            notes.append("SIM pack sold as an eSIM only.")
        if "SIM purchase online only" in body:
            notes.append("SIM purchase online only.")
        promo = None
        total, disc = a.get("productTotal"), a.get("discount") or 0
        if isinstance(total, (int, float)) and disc < 0 and 0 < total < price:
            off = offers.get(sku) or {}
            dm = re.search(r"(Sale ends [^.]+\.(?: [^.]*full price\.)?(?: Online only\.)?)", body)
            promo = {"price": float(total), "periods": 1,
                     "until": off.get("priceValidUntil") or sale_end(body, today),
                     "text": f"SIM deal: ${total:g} (was ${price:g}) for the first recharge"
                             + (f". {dm.group(1)}" if dm else "")}
        links = [u for u in re.findall(r'href="([^"#][^"]*)"', card)]
        page_url = next((u for u in links if "/shop/" in u or "/prepaid-plans/" in u), None)
        cis = next((u for u in links if u.lower().endswith(".pdf")), None)
        name = re.sub(r"PREPAID", "Prepaid", a.get("productName") or f"${price:g} Prepaid SIM+")
        mobile.append({
            "id": f"{PID}-prepaid-{price:g}-{n}-{unit}", "provider": PID,
            "name": f"{name} ({n} {unit}{'s' if n > 1 else ''})", "network": "telstra",
            "type": "prepaid", "period_days": period, "price": price, "data_gb": data_gb,
            "data_only": False,
            "calls": "unlimited" if re.search(r"Unlimited stnd calls", body, re.I) else "limited",
            "five_g": True if "5G" in body else None, "intl": intl, "promo": promo, "contract": 0,
            "rollover": "Data Rollover" in body, "bundle": [], "credit": None,
            "url": BASE + page_url if page_url and page_url.startswith("/") else page_url or URL,
            "cis_url": BASE + cis if cis and cis.startswith("/") else cis,
            "source": STEM, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })
    if not mobile:
        raise RuntimeError("Boost prepaid plans page parsed to zero plans; page layout may have changed")
    if unknown:
        print(f"boost_mobile: warning: unmapped countries {unknown}", file=sys.stderr)
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"Boost mobile ids not unique: {ids}")
    meta = {"name": "Boost Mobile prepaid plans", "url": URL, "fetched": captured,
            "unmapped_countries": unknown}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"boost_mobile: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

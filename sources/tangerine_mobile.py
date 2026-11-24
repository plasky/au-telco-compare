"""Tangerine: 5G SIM-only plans and 5G mobile broadband (data-only) SIMs, Telstra Wholesale
network, from its own server-rendered pages.

https://www.tangerine.com.au/mobile/sim-only-mobile-plans   voice SIM plans (required)
https://www.tangerine.com.au/internet/mobile-broadband      data-only SIM plans (optional)
robots.txt disallows only /admin.

Each plan is a card `<div id="<product guid>" class="... product-sims ...">` with:
  - an offer badge ("Summer Sale: 50% Off") whose tooltip has the terms ("Sign up to a new 5G
    mobile plan between 12/11/26 and 28/2/27 and get 50% off the RRP for 3 months ...");
  - a "5G" ribbon, `<h4>` allowance ("100GB*"), and while Double Data runs an `<h2>`
    "50GB + 50GB for 6mths" and "*Double Data Offer: 100GB for 6mths, then 50GB/mth";
  - the price shown (`<span class="heading">$17<span>.50/MTH`), which is the intro price while
    a promo runs, and "For 3 months, then $35 ongoing~";
  - add-to-cart buttons with data-product-name / data-product-price (the shown price).
CIS links: /simonlycis and /mobilebroadbandcis. The 15 included countries are listed in the
page footnote ("Top 15 countries includes: Bangladesh, Canada, ... UK & USA").

Bundle: 10% off the RRP of mobile and mobile broadband plans while the account has an active
Tangerine nbn service (Bundle & Save T&Cs, linked from the page; other discounts apply first,
then the 10% on the remainder). It is a percentage, so it is not encoded in `bundle`; it belongs
in the account-level rules. The Double Data bonus is a data offer and goes in notes.
"""
import html
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

PID = "tangerine"
SRC = pathlib.Path(__file__).stem
SIM_URL = "https://www.tangerine.com.au/mobile/sim-only-mobile-plans"
MBB_URL = "https://www.tangerine.com.au/internet/mobile-broadband"
COUNTRIES = {
    "bangladesh": "BD", "canada": "CA", "china": "CN", "germany": "DE", "greece": "GR", "hong kong": "HK",
    "india": "IN", "ireland": "IE", "japan": "JP", "malaysia": "MY", "new zealand": "NZ", "singapore": "SG",
    "south korea": "KR", "korea": "KR", "thailand": "TH", "uk": "GB", "united kingdom": "GB", "usa": "US",
    "us": "US", "united states": "US", "vietnam": "VN", "philippines": "PH", "indonesia": "ID",
    "pakistan": "PK", "sri lanka": "LK", "taiwan": "TW", "italy": "IT", "france": "FR",
}


def text(s):
    s = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", s or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s):
    m = re.search(r"\$\s*(\d+)\s*(?:\.\s*(\d+))?", s or "")
    return float(f"{m.group(1)}.{m.group(2) or 0}") if m else None


def gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", s or "", re.I)
    return float(m.group(1)) * (1000 if m.group(2).upper() == "TB" else 1) if m else None


def dmy(s):
    """'28/2/27' or '28/02/2027' -> ISO date."""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", s or "")
    if not m:
        return None
    y = int(m.group(3))
    return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1))).isoformat()


def countries(page_text):
    m = re.search(r"Top (\d+) countries includes?:\s*([^.]+)\.", page_text)
    if not m:
        return None, None
    names = [n.strip().lower() for n in re.split(r",\s*|\s*&\s*|\s+and\s+", m.group(2)) if n.strip()]
    codes = [COUNTRIES.get(n) for n in names]
    if None in codes or len(codes) != int(m.group(1)):
        print(f"warning: country list not fully mapped: {names}", file=sys.stderr)
        return int(m.group(1)), None
    return int(m.group(1)), sorted(set(codes))


def cards(page):
    parts = re.split(r'(<div id="[0-9a-f-]{36}" class="[^"]*\bproduct-sims\b[^"]*")', page)
    for i in range(1, len(parts) - 1, 2):
        b = parts[i] + parts[i + 1]
        guid = re.search(r'id="([0-9a-f-]{36})"', parts[i]).group(1)
        badge = re.search(r'class="popular-plan[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>', b, re.S)
        tips = [html.unescape(t) for t in re.findall(r'\btitle="([^"]{20,})"', b)]
        btn = re.search(r'data-product-name="([^"]*)"[^>]*data-product-price="([^"]*)"', b)
        yield {
            "guid": guid,
            "badge": text(badge.group(1)) if badge else "",
            "tips": tips,
            "ribbon": text((re.search(r'class="sim_ribbon[^"]*"[^>]*>(.*?)</div>', b, re.S) or [None, ""])[1]),
            "h4": text((re.search(r"<h4 class=\"mb1 text-black[^\"]*\"[^>]*>(.*?)</h4>", b, re.S) or [None, ""])[1]),
            "h2": text((re.search(r'<h2 class="[^"]*orignal_title_text[^"]*"[^>]*>(.*?)</h2>', b, re.S) or [None, ""])[1]),
            "shown": money(text((re.search(r'<span class="heading\s*"\s*>(.*?/MTH)', b, re.S | re.I) or [None, ""])[1])),
            "footer": text((re.search(r'class="[^"]*plan_footer[^"]*"[^>]*>(.*?)</p>', b, re.S) or [None, ""])[1]),
            "btn_name": html.unescape(btn.group(1)) if btn else "",
            "btn_price": float(btn.group(2)) if btn else None,
            "text": text(b),
        }


def records(page, url, data_only, captured):
    page_text = text(page[page.find("<body"):])
    n_countries, intl = countries(page_text)
    cis = (re.search(r'href="(https://www\.tangerine\.com\.au/[a-z]*cis)"', page) or [None, None])[1]
    network = "telstra" if "Telstra Wholesale Mobile Network" in page_text or \
        "Telstra wholesale mobile network" in page_text else None
    out = []
    for c in cards(page):
        shown = c["shown"] if c["shown"] is not None else c["btn_price"]
        fm = re.search(r"For (\d+) months?, then \$(\d+(?:\.\d+)?) ongoing", c["footer"], re.I)
        price = float(fm.group(2)) if fm else shown
        dd = re.search(r"Double Data Offer: (\d+)GB for (\d+) ?mths, then (\d+)\s*GB/mth\.?(?: Ends (\d{1,2}/\d{1,2}/\d{2,4}))?",
                       c["text"].replace("7 5G B", "75GB"))
        base = float(dd.group(3)) if dd else gb(c["h2"]) if "+" in c["h2"] else gb(c["h4"])
        if price is None or base is None:
            print(f"warning: skipped unparsable card {c['guid']}", file=sys.stderr)
            continue
        notes, promo = [], None
        if fm and shown is not None and shown < price:
            terms = next((t for t in c["tips"] if re.search(r"off the RRP", t, re.I)), "")
            tm = re.search(r"between (\d{1,2}/\d{1,2}/\d{2,4}) and (\d{1,2}/\d{1,2}/\d{2,4})", terms)
            promo = {"price": shown, "periods": int(fm.group(1)), "until": dmy(tm.group(2)) if tm else None,
                     "text": f"{c['badge'] or 'Intro offer'}: ${format(shown, '.2f').removesuffix('.00')}/month "
                             f"for {fm.group(1)} months"}
            notes.append("Promo for new services; activate within 14 days of purchase."
                         if "14 days" in terms else "Promo for new services.")
        if dd:
            notes.append(f"Double Data offer: {dd.group(1)}GB per month for the first {dd.group(2)} months"
                         + (f" for sign-ups by {dd.group(4)}" if dd.group(4) else "") + ".")
        bank = re.search(r"(\d+)\s*GB DATABANK", c["text"], re.I)
        if bank:
            notes.append(f"Unused data banks (up to {bank.group(1)}GB).")
        caps = {int(g): int(s) for s, g in re.findall(r"capped at (\d+) ?Mbps on the ?(\d+)GB plan\b", page_text)}
        for s, plist in re.findall(r"capped at (\d+) ?Mbps on the ?((?:\d+GB,? (?:and )?)+)plans", page_text):
            for g in re.findall(r"(\d+)GB", plist):
                caps.setdefault(int(g), int(s))
        own_cap = re.search(r"CAPPED AT (\d+) MBPS", c["text"], re.I)
        speed = int(own_cap.group(1)) if own_cap else caps.get(int(base))
        if speed:
            notes.append(f"Download speeds capped at {speed} Mbps.")
        if "pause your service" in page_text and data_only:
            notes.append("Data pauses at the allowance until the next bill period.")
        top = re.search(r"CALLS TO TOP (\d+) COUNTRIES", c["text"], re.I)
        plan_intl = intl if top and intl and int(top.group(1)) == n_countries else None
        if top and plan_intl is None:
            notes.append(f"Unlimited calls to the top {top.group(1)} countries (list not parsed).")
        gbs = f"{base:g}GB"
        name = f"5G {gbs}" + (" Mobile Broadband" if data_only else "") if c["ribbon"].upper() == "5G" or \
            data_only else gbs
        out.append({
            "id": f"{PID}-mobile-{slug(name)}", "provider": PID, "name": name,
            "network": network, "type": "postpaid", "period_days": 30, "price": price, "data_gb": base,
            "data_only": data_only,
            "calls": "none" if data_only else "unlimited" if "UNLIMITED STANDARD CALLS" in c["text"].upper() else "unknown",
            "five_g": c["ribbon"].upper() == "5G" or "5G" in c["text"][:200], "intl": None if data_only else plan_intl,
            "promo": promo, "contract": 0, "rollover": True if bank else None, "bundle": [], "credit": None,
            "url": url, "cis_url": cis, "source": SRC, "captured": captured, "verified": True,
            "notes": " ".join(notes) or None,
        })
    return out


def main():
    captured = now_iso()
    page = fetch(SIM_URL, RAW / SRC / "sim-only-mobile-plans.html", min_interval=2.0).decode("utf-8")
    mobile = records(page, SIM_URL, False, captured)
    if not mobile:
        raise RuntimeError("tangerine mobile: no SIM plan cards parsed; page layout may have changed")
    try:
        mpage = fetch(MBB_URL, RAW / SRC / "mobile-broadband.html", min_interval=2.0).decode("utf-8")
        mobile += records(mpage, MBB_URL, True, captured)
    except Exception as e:  # noqa: BLE001
        print(f"warning: mobile broadband page skipped: {e}", file=sys.stderr)
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"tangerine mobile: duplicate ids {ids}")
    meta = {"name": "Tangerine SIM-only and mobile broadband pages", "url": SIM_URL, "urls": [SIM_URL, MBB_URL],
            "fetched": captured}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile ({sum(1 for r in mobile if r['promo'])} with promo)")


if __name__ == "__main__":
    main()

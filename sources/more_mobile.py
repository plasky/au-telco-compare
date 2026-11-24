"""More (more.com.au, provider id "more-telecom"): 5G SIM-only plans and 5G mobile broadband
(data-only) SIMs, Telstra Wholesale network, from its own server-rendered pages.

https://www.more.com.au/personal/mobile-plans        voice SIM plans (required)
https://www.more.com.au/personal/mobile-broadband    data-only SIM plans (optional)
robots.txt allows everything.

The site shares its back end with Tangerine (same product GUIDs and cart code) but not its page
template or prices, so it has its own adapter (as for nbn). Each plan is a card
`<div class="px-2 h-100" id="<product guid>">` with:
  - an optional offer banner ("Double Data Deal*") and badge ("50GB SIM Plan");
  - the allowance shown (`<p class="fs-4 fw-semibold">100<span class='gb'>GB</span>*</p>`) and,
    while Double Data runs, "For 6 months, then 50GB/mth. Sign up by 3/2/27.";
  - the monthly price split across spans ("$" "40" ".00" "/mth");
  - "5G NETWORK ACCESS", the speed cap, the feature list (1000GB databank, Calls to Top 15
    Countries), an add-to-cart button (data-product-type="sim", data-product-name) and the CIS.
The page footnote lists the 15 countries ("Top 15 countries includes: Bangladesh, ... UK & USA").

No mobile + internet bundle discount is published. The only discount offer is CommBank-only
($10/month off for 3 years, then $4/month off, via ConnectID and a CommBank card), kept in notes
as in the nbn adapter. Double Data is a data bonus and goes in notes.
"""
import html
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

PID = "more-telecom"
SRC = pathlib.Path(__file__).stem
SIM_URL = "https://www.more.com.au/personal/mobile-plans"
MBB_URL = "https://www.more.com.au/personal/mobile-broadband"
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


def gb(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB)", s or "", re.I)
    return float(m.group(1)) * (1000 if m.group(2).upper() == "TB" else 1) if m else None


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
    parts = re.split(r'(<div class="px-2 h-100" id="[0-9a-f-]{36}">)', page)
    for i in range(1, len(parts) - 1, 2):
        b = parts[i] + parts[i + 1]
        if 'data-product-type="sim"' not in b:
            continue
        price = re.search(r'<span class="fs-60[^"]*">(\d+)</span>\s*<span class="fs-3[^"]*">\.(\d+)</span>', b)
        yield {
            "guid": re.search(r'id="([0-9a-f-]{36})"', parts[i]).group(1),
            "banner": text((re.search(r'offer-title">(.*?)</div>', b, re.S) or [None, ""])[1]),
            "badge": text((re.search(r'<span\s+class="badge [^"]*">(.*?)</span>', b, re.S) or [None, ""])[1]),
            "shown": text((re.search(r'<p class="fs-4 fw-semibold[^"]*">(.*?)</p>', b, re.S) or [None, ""])[1]),
            "promo_text": text((re.search(r'<div class="promo-text[^"]*">(.*?)</div>', b, re.S) or [None, ""])[1]),
            "price": float(f"{price.group(1)}.{price.group(2)}") if price else None,
            "btn_name": html.unescape((re.search(r'data-product-name="([^"]*)" data-type="increase"', b) or [None, ""])[1]),
            "cis": html.unescape((re.search(r'<a href="([^"]+)"[^>]*>\s*Critical Information Summary', b) or [None, ""])[1]) or None,
            "text": text(b),
        }


def records(page, url, data_only, captured):
    page_text = text(page[page.find("<body"):])
    n_countries, intl = countries(page_text)
    network = "telstra" if "Telstra Wholesale Mobile Network" in page_text else None
    cb = re.search(r"\$(\d+)/mth off (?:a )?(?:new )?mobile (?:broadband )?plans? for (\d+) years,? [Tt]hen "
                   r"\$(\d+)/(?:mth|month) off ongoing",
                   page_text)
    out = []
    for c in cards(page):
        dd = re.search(r"For (\d+) months, then (\d+(?:\.\d+)?)\s*GB/mth\s*\.?\s*(?:Sign up by (\d{1,2}/\d{1,2}/\d{2,4}))?",
                       c["promo_text"])
        base = float(dd.group(2)) if dd else gb(c["badge"]) or gb(c["btn_name"]) or gb(c["shown"])
        if base is None or c["price"] is None:
            print(f"warning: skipped unparsable card {c['guid']}", file=sys.stderr)
            continue
        t = c["text"]
        notes = []
        if dd:
            notes.append(f"Double Data offer: {gb(c['shown']):g}GB per month for the first {dd.group(1)} months"
                         + (f" for sign-ups by {dd.group(3)}" if dd.group(3) else "") + ".")
        bank = re.search(r"(\d+)\s*GB databank", t, re.I)
        if bank:
            notes.append(f"Unused data banks (up to {bank.group(1)}GB).")
        cap = re.search(r"capped at (\d+) ?Mbps", t)
        if cap:
            notes.append(f"Download speeds capped at {cap.group(1)} Mbps.")
        if cb:
            notes.append(f"CommBank customers (ConnectID sign-up) get ${cb.group(1)}/month off for {cb.group(2)} years, "
                         f"then ${cb.group(3)}/month off.")
        top = re.search(r"Calls to Top (\d+) Countries", t, re.I)
        plan_intl = intl if top and intl and int(top.group(1)) == n_countries else None
        if top and plan_intl is None:
            notes.append(f"Unlimited calls to the top {top.group(1)} countries (list not parsed).")
        five_g = "5G NETWORK ACCESS" in t.upper()
        name = f"{base:g}GB " + ("Mobile Broadband" if data_only else "SIM Plan")
        if five_g:
            name = "5G " + name
        out.append({
            "id": f"{PID}-mobile-{slug(name)}", "provider": PID, "name": name, "network": network,
            "type": "postpaid", "period_days": 30, "price": c["price"], "data_gb": base, "data_only": data_only,
            "calls": "none" if data_only else "unlimited", "five_g": five_g, "intl": None if data_only else plan_intl,
            "promo": None, "contract": 0, "rollover": True if bank else None, "bundle": [], "credit": None,
            "url": url, "cis_url": c["cis"], "source": SRC, "captured": captured, "verified": True,
            "notes": " ".join(notes) or None,
        })
    if network is None and out:
        print(f"warning: {url}: host network statement not found", file=sys.stderr)
    if not data_only and out and "unlimited standard calls" not in page_text.lower():
        print("warning: 'unlimited standard calls' statement not found; calls assumed unlimited", file=sys.stderr)
    return out


def main():
    captured = now_iso()
    page = fetch(SIM_URL, RAW / SRC / "mobile-plans.html", min_interval=2.0).decode("utf-8")
    mobile = records(page, SIM_URL, False, captured)
    if not mobile:
        raise RuntimeError("more mobile: no SIM plan cards parsed; page layout may have changed")
    try:
        mpage = fetch(MBB_URL, RAW / SRC / "mobile-broadband.html", min_interval=2.0).decode("utf-8")
        mobile += records(mpage, MBB_URL, True, captured)
    except Exception as e:  # noqa: BLE001
        print(f"warning: mobile broadband page skipped: {e}", file=sys.stderr)
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"more mobile: duplicate ids {ids}")
    meta = {"name": "More mobile plans and mobile broadband pages", "url": SIM_URL, "urls": [SIM_URL, MBB_URL],
            "fetched": captured}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

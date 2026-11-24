"""Superloop: 5G prepaid SIM-only plans (Telstra Wholesale network) from its own mobile page.

https://www.superloop.com/mobile/ (robots.txt: "Allow: /"). One request per run.

Sources on that page:
  1. The server-rendered plan cards of the "plan-selector-mobile" Livewire component, one block
     per offer (wire:key="mobile-offer-<id>") with data-sync-row="label|head|price" rows, the
     buy button's data-plan-name / data-price attributes, a data-plan-special-offer badge
     ("50% off 3 recharges*") and the inclusions list. Required; the adapter fails without it.
     (The component's wire:snapshot carries only the heading, so the cards are the source.)
  2. Page text: the promo footnote ("* For existing Superloop broadband customers, or new
     customers signing up for a mobile and broadband service. 50% off monthly fee for three
     recharges after internet activation. First activation must occur before 31 Dec 2026 ..."),
     the network ("Superloop uses the Telstra Wholesale Mobile Network"), the list of 15
     countries with unlimited international calls, and the CIS link.
  3. JSON-LD ProductGroup "Superloop SIM Only Plans": fallback for the country list only. Its
     sizes and offer names lag the cards (bonus data counted in, a stale "Double data" offer).

Double data: the cards show "45GB + 45GB" while a bonus-data offer runs (new services, first
6 recharges). data_gb is the base allowance; the bonus goes in notes.
The 50%-off promo needs a Superloop broadband service, so it carries requires="internet".
Bundle & Save is a tiered discount on the broadband bill (+1 service $5/mth ... +5 services
$15/mth, https://www.superloop.com/internet/bundle-and-save/), not on the SIM, so SIM records
carry no bundle; it belongs in the account-level rules.
"""
import html
import json
import re
import sys
import pathlib
from datetime import date, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

URL = "https://www.superloop.com/mobile/"
PID = "superloop"
SRC = pathlib.Path(__file__).stem
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                      "sep", "oct", "nov", "dec"], 1)}
COUNTRIES = {
    "bangladesh": "BD", "canada": "CA", "china": "CN", "greece": "GR", "hong kong": "HK", "india": "IN",
    "ireland": "IE", "japan": "JP", "malaysia": "MY", "new zealand": "NZ", "singapore": "SG",
    "south korea": "KR", "korea": "KR", "thailand": "TH", "uk": "GB", "united kingdom": "GB",
    "usa": "US", "united states": "US", "us": "US", "germany": "DE", "vietnam": "VN", "france": "FR",
    "italy": "IT", "indonesia": "ID", "philippines": "PH", "pakistan": "PK", "sri lanka": "LK",
    "nepal": "NP", "taiwan": "TW", "israel": "IL", "spain": "ES", "brazil": "BR", "mexico": "MX",
}


def text_of(s):
    s = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", s or "", flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def between(s, a, b):
    """Markup after the tag holding marker `a` and before the tag holding marker `b`."""
    i = s.find(a)
    if i < 0:
        return ""
    start = s.find(">", i) + 1 if "=" in a else i + len(a)
    j = s.find(b, start) if b else -1
    end = (s.rfind("<", start, j) if "=" in b else j) if j > 0 else len(s)
    return s[start:end if end >= start else j]


def gb(s):
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(GB|TB)", s or "", re.I)
    if not m:
        return None
    return float(m.group(1)) * (1000 if m.group(2).upper() == "TB" else 1)


def country_codes(names_text):
    names = [n.strip(" .").lower() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+", names_text) if n.strip(" .")]
    codes = [COUNTRIES.get(n) for n in names]
    if not names or None in codes:
        unknown = [n for n, c in zip(names, codes) if c is None]
        print(f"warning: unmapped country names {unknown}; intl left empty", file=sys.stderr)
        return None
    return sorted(set(codes))


def parse_date(d, m, y):
    mo = MONTHS.get(m[:3].lower())
    return date(int(y), mo, int(d)) if mo else None


def cards(page):
    blocks = re.split(r'wire:key="mobile-offer-(\d+)"', page)
    for i in range(1, len(blocks) - 1, 2):
        oid, b = blocks[i], blocks[i + 1]
        btn = re.search(r'data-plan-name="([^"]*)"[^>]*data-price="([^"]*)"', b)
        offer = re.search(r"data-plan-special-offer[^>]*>(.*?)</div>\s*</div>", b, re.S)
        yield {
            "offer_id": oid,
            "label": text_of(between(b, 'data-sync-row="label"', 'data-sync-row="head"')),
            "head": text_of(between(b, 'data-sync-row="head"', 'data-sync-row="price"')),
            "price_row": text_of(between(b, 'data-sync-row="price"', "Buy now")),
            "btn_name": html.unescape(btn.group(1)) if btn else None,
            "btn_price": html.unescape(btn.group(2)) if btn else None,
            "special": text_of(offer.group(1)) if offer else "",
            "inclusions": text_of(between(b, "Featured inclusions", 'wire:key="')),
        }


def main():
    page = fetch(URL, RAW / SRC / "mobile.html", min_interval=2.0).decode("utf-8")
    captured = now_iso()
    text = text_of(page[page.find("<body"):])

    # Promo footnote and network.
    fm = re.search(r"\* For existing Superloop broadband customers.{0,400}?T&Cs apply", text)
    footnote = fm.group(0) if fm else ""
    am = re.search(r"First activation must occur (before|by|on or before) (\d{1,2}) (\w+) (\d{4})", footnote)
    until = None
    if am:
        d = parse_date(am.group(2), am.group(3), am.group(4))
        if d:
            until = (d - timedelta(days=1) if am.group(1) == "before" else d).isoformat()
    network = "telstra" if re.search(r"uses the Telstra Wholesale Mobile Network", text) else \
        "optus" if re.search(r"uses the Optus", text) else None
    if network is None:
        print("warning: host network statement not found on the page", file=sys.stderr)

    # Included international calls: page text first, JSON-LD descriptions as fallback.
    intl, n_countries = None, None
    im = re.search(r"unlimited international calls and standard SMS to fixed and mobile numbers in (\d+) "
                   r"countries\. These countries include: ([^.]+)\.", text)
    if not im:
        for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
            im = re.search(r"to (\d+) countries \(([^)]+)\)", m.group(1))
            if im:
                break
    if im:
        n_countries, intl = int(im.group(1)), country_codes(im.group(2))
        if intl and len(intl) != n_countries:
            print(f"warning: {n_countries} countries stated but {len(intl)} parsed", file=sys.stderr)

    cis = next((html.unescape(u) for u, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
                if text_of(label).lower() == "critical information summary"), None)

    mobile, seen = [], set()
    for c in cards(page):
        name = c["label"]
        pm = re.search(r"\$(\d+(?:\.\d+)?)", c["btn_price"] or c["price_row"])
        heading = c["btn_name"] or c["head"]
        data = gb(heading)
        if not name or not pm or data is None:
            print(f"warning: skipped unparsable card {c['offer_id']}: {c}", file=sys.stderr)
            continue
        price = float(pm.group(1))
        bonus = re.match(r"\s*\d+(?:\.\d+)?\s*GB\s*\+\s*(\d+(?:\.\d+)?)\s*GB", heading, re.I)
        inc = c["inclusions"].lower()
        notes = []
        cap = re.search(r"capped at (\d+) ?Mbps", c["price_row"], re.I)
        if cap:
            notes.append(f"Download speeds capped at {cap.group(1)} Mbps.")
        if bonus:
            dm = re.search(r"double data[^^]*?until (\d{1,2} \w+ \d{4})", c["inclusions"], re.I)
            notes.append(f"Bonus +{bonus.group(1)}GB per recharge for the first 6 recharges on new services"
                         + (f" (offer until {dm.group(1)})" if dm else "") + ".")
        rollover = True if "rollover" in inc or "data bank" in inc else None
        if rollover:
            bank = re.search(r"max (\d+) ?GB", c["inclusions"], re.I)
            notes.append(f"Unused data rolls into a Data Bank (max {bank.group(1) if bank else '?'}GB).")
        mi = re.search(r"international calls & SMS to (\d+) countries", c["inclusions"], re.I)
        plan_intl = intl if mi and intl and (n_countries is None or int(mi.group(1)) == n_countries) else None
        if mi and plan_intl is None:
            notes.append(f"Unlimited international calls to {mi.group(1)} countries (list not parsed).")
        period = int((re.search(r"(\d+) day cycle", c["inclusions"], re.I) or [None, 30])[1])
        prepaid = "prepaid" in inc or "recharge" in inc

        promo = None
        sm = re.search(r"(\d+)% off (\d+) recharges", c["special"], re.I)
        if sm:
            pct, n = float(sm.group(1)), int(sm.group(2))
            promo = {"price": round(price * (100 - pct) / 100, 2), "periods": n, "until": until,
                     "text": f"{sm.group(1)}% off the first {n} recharges with a Superloop broadband service",
                     "requires": "internet"}
            notes.append("Promo for existing Superloop broadband customers, or new customers taking mobile and "
                         "broadband together; the discounted recharges start after internet activation.")
        elif c["special"]:
            notes.append(f"Current offer: {c['special']}")

        rid = f"{PID}-mobile-{slug(name)}"
        if rid in seen:
            rid = f"{rid}-{c['offer_id']}"
        seen.add(rid)
        mobile.append({
            "id": rid, "provider": PID, "name": name, "network": network,
            "type": "prepaid" if prepaid else "postpaid", "period_days": period, "price": price,
            "data_gb": data, "data_only": False,
            "calls": "unlimited" if "unlimited national calls" in inc else "unknown",
            "five_g": "5g" in name.lower(), "intl": plan_intl, "promo": promo, "contract": 0,
            "rollover": rollover, "bundle": [], "credit": None, "url": URL, "cis_url": cis,
            "source": SRC, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })
    if not mobile:
        raise RuntimeError("superloop mobile: no plan cards parsed; page layout may have changed")
    meta = {"name": "Superloop SIM-only plans page", "url": URL, "fetched": captured, "promo_until": until,
            "promo_terms": footnote or None}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile ({sum(1 for r in mobile if r['promo'])} with promo)")


if __name__ == "__main__":
    main()

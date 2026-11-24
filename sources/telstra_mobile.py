"""Telstra: SIM-only mobile plans (postpaid Upfront plans, Upfront data plans, Pre-Paid recharges).

Three server-rendered pages (Adobe AEM), each a plain GET; robots.txt allows all of them for
all user agents (our client name is not in its blocked AI-crawler list):
  https://www.telstra.com.au/mobile-phones/sim-only-plans   Upfront Basic / Essential / Premium
  https://www.telstra.com.au/internet/data-plans            Upfront Small / Medium data plans
  https://www.telstra.com.au/prepaid/mobile-plans           Pre-Paid recharges (7 day ... 12 month)

Upfront (postpaid) cards: each card is <li class="plan-card ..." data-plan-card-id="SKU">, and
its order button carries data-plan-id, data-plan-name, data-plan-value (data), data-plan-cost
("$74 Monthly"), data-plan-subtype (VoiceData | Data), data-plan-size and data-included-calls.
Current discounts are page-level <div data-promo-productCode="SKU" data-promo-adjustmentValue=
"-37.00" data-promo-effectiveUntil="Purchase Date + 4 Month" data-promo-end-date-time=...>.
Cards with data-plan-size="CP" are Telstra's "Bundle Plans" (Mobile Bundle Plan, Data Bundle
Plan): extra services that need an Upfront Essential or Premium plan on the same account. They
are account-level discounts (overrides/bundles.toml), so they are not emitted here.

Pre-Paid cards: <div data-tcom-plan-card-name="sku" data-prepaid-plan-card-header> followed by
data-tcom-prepaid-plan-card-header-label, data-tcom-prepaid-plan-price (+ -promo-price and
-promo-end-date for a first-recharge deal on a new SIM) and an order button with data-plan-id,
data-plan-data (base allowance) and data-plan-subtype (Core | Casual). The first cards are a
featured carousel that repeats later cards, so cards are de-duplicated by SKU. Expiry comes from
the card's "28 Day Plan" / "6 Month Plan" label. Included international minutes come from the
page's zone table (minutes per recharge amount) and Zone 1 country list.

Notes on the content:
  - Upfront plans: data is "no excess data charges", slowed to 1.5 Mbps after the allowance;
    30 minutes a month of calls to any standard international number plus unlimited
    international SMS/MMS. That isn't a country list, so intl is None with a note.
  - Pre-Paid activation bonus data ("65GB on first three recharges by 15 April, then 20GB") is
    kept in notes; data_gb is the ongoing base allowance.
  - Pre-Paid cards all list "Continuous data rollover", but the Pre-Paid Critical Information
    Summary (offers from 5 May 2026) says rollover is "Not included" on the $200 6-month and
    $395 12-month recharges. The CIS is followed: rollover is False for long-expiry recharges.
  - 6-month expiry is counted as 183 days, 12 months as 365.
"""
import html
import re
import sys
import pathlib
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

PID = "telstra"
STEM = "telstra_mobile"
SIM_URL = "https://www.telstra.com.au/mobile-phones/sim-only-plans"
DATA_URL = "https://www.telstra.com.au/internet/data-plans"
PREPAID_URL = "https://www.telstra.com.au/prepaid/mobile-plans"
AEST = timezone(timedelta(hours=10))
LONG_EXPIRY_DAYS = 180   # per the Pre-Paid CIS, continuous rollover isn't included at or above this
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}
COUNTRIES = {
    "argentina": "AR", "austria": "AT", "bangladesh": "BD", "belgium": "BE", "brazil": "BR",
    "canada": "CA", "chile": "CL", "china": "CN", "colombia": "CO", "cyprus": "CY",
    "czech republic": "CZ", "denmark": "DK", "fiji": "FJ", "finland": "FI", "france": "FR",
    "germany": "DE", "greece": "GR", "guam": "GU", "hong kong": "HK", "hungary": "HU",
    "india": "IN", "indonesia": "ID", "ireland": "IE", "israel": "IL", "italy": "IT",
    "japan": "JP", "macau": "MO", "malaysia": "MY", "malta": "MT", "mexico": "MX",
    "netherlands": "NL", "new zealand": "NZ", "norway": "NO", "pakistan": "PK", "peru": "PE",
    "philippines": "PH", "poland": "PL", "portugal": "PT", "puerto rico": "PR", "romania": "RO",
    "singapore": "SG", "south africa": "ZA", "south korea": "KR", "korea": "KR", "spain": "ES",
    "sri lanka": "LK", "sweden": "SE", "switzerland": "CH", "taiwan": "TW", "thailand": "TH",
    "turkey": "TR", "uk": "GB", "united kingdom": "GB", "usa": "US", "united states": "US",
    "us virgin islands": "VI", "vietnam": "VN",
}


def attrs(tag):
    """data-* attributes of one start tag, lower-cased names, HTML-unescaped values."""
    return {k.lower(): html.unescape(v).strip()
            for k, v in re.findall(r'\b(data-[\w-]+)="([^"]*)"', tag)}


def text(fragment):
    fragment = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragment or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def gb(v):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)", v or "", re.I)
    if not m:
        return None
    return float(m.group(1)) * {"gb": 1, "tb": 1000, "mb": 0.001}[m.group(2).lower()]


def segments(page, start_re, cap):
    starts = [m.start() for m in re.finditer(start_re, page)]
    ends = starts[1:] + [len(page)]
    return [page[a:min(b, a + cap)] for a, b in zip(starts, ends)]


def local_date(ts):
    """'2026-11-30T23:59:00+1100' -> '2026-11-30' (the Australian date it ends on)."""
    try:
        return datetime.fromisoformat(ts).astimezone(AEST).date().isoformat() if ts else None
    except ValueError:
        return None


def long_date(s):
    """'30 November 2026' -> '2026-11-30'."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s or "")
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()


def upfront_promos(page):
    """SKU -> current recurring discount (page-level data-promo-* blocks)."""
    out = {}
    for tag in re.findall(r"<div[^>]*\bdata-promo-id=[^>]*>", page):
        a = attrs(tag)
        sku, adj = a.get("data-promo-productcode"), num(a.get("data-promo-adjustmentvalue"))
        if not sku or not adj or adj >= 0 or a.get("data-promo-visibility", "Public") != "Public":
            continue
        if (a.get("data-promo-recurringfrequency") or "Monthly").lower() != "monthly":
            continue
        m = re.search(r"\+\s*(\d+)\s*Month", a.get("data-promo-effectiveuntil", ""), re.I) \
            or re.search(r"for (\d+) months?", a.get("data-promo-name", ""), re.I)
        if not m:
            continue
        out[sku] = {"off": -adj, "periods": int(m.group(1)), "name": a.get("data-promo-name", ""),
                    "until": local_date(a.get("data-promo-end-date-time"))}
    return out


def parse_upfront(page, url, captured):
    promos = upfront_promos(page)
    out, skipped = [], []
    for card in segments(page, r'<li class="plan-card plan-card--subscription[^"]*"[^>]*data-plan-card-id=', 60000):
        btn = re.search(r"<button[^>]*\bdata-plan-id=[^>]*>", card)
        if not btn:
            continue
        a = attrs(btn.group(0))
        sku, name = a.get("data-plan-id"), a.get("data-plan-name")
        cost = a.get("data-plan-cost", "")
        pm = re.search(r"\$(\d+(?:\.\d+)?)\s*Monthly", cost, re.I)
        if not sku or not name or not pm or a.get("data-plan-visibility", "Public") != "Public":
            continue
        if a.get("data-plan-size") == "CP" or "bundle" in name.lower():
            skipped.append(f"{name} ({cost}, {a.get('data-plan-value')}): needs an Essential or Premium plan on the account")
            continue
        price = float(pm.group(1))
        data_only = a.get("data-plan-subtype", "").lower() == "data"
        calls_txt = a.get("data-included-calls", "")
        calls = "none" if data_only else "unlimited" if "unlimited calls" in calls_txt.lower() else "limited"
        body = text(card)
        cis = next((html.unescape(u) for u in re.findall(r'href="([^"]+)"', card)
                    if "critical-information-summaries" in u), None)
        promo = None
        p = promos.get(sku)
        if p and p["off"] < price:
            promo = {"price": round(price - p["off"], 2), "periods": p["periods"], "until": p["until"],
                     "text": f"{p['name']} (${p['off']:g}/mth off); new services only"}
        notes = ["No excess data charges: slowed to 1.5 Mbps after the monthly allowance."]
        if not data_only:
            notes.append("Includes 30 minutes a month of calls to any standard international number "
                         "and unlimited international SMS/MMS.")
        if "International Roaming Day Passes included" in body and "Premium" in name:
            notes.append("Includes 5 International Roaming Day Passes a month.")
        if promo:
            notes.append("Discount ends if you change plans or cancel.")
        label = f"{name} Data Plan" if data_only and "data" not in name.lower() else name
        out.append({
            "id": f"{PID}-mobile-{'data-' if data_only else ''}{slug(name)}", "provider": PID,
            "name": f"Upfront {label}",
            "network": "telstra", "type": "postpaid", "period_days": 30, "price": price,
            "data_gb": gb(a.get("data-plan-value")), "data_only": data_only, "calls": calls,
            "five_g": True if "5G" in body else None, "intl": None, "promo": promo, "contract": 0,
            "rollover": None, "bundle": [], "credit": None,
            "url": url, "cis_url": cis, "source": STEM, "captured": captured, "verified": True,
            "notes": " ".join(notes),
        })
    return out, skipped


def intl_tables(page):
    """Recharge amount -> (zone1, zone2, zone3) minutes, and the Zone 1 ISO codes."""
    minutes = {}
    for th, cells in re.findall(r"<tr>\s*<th[^>]*>\s*\$(\d+)\s*</th>((?:\s*<td[^>]*>.*?</td>){4})", page, re.S):
        vals = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", cells, re.S)]
        if len(vals) == 4 and "text" in vals[3].lower():
            minutes[float(th)] = tuple(int(re.sub(r"\D", "", v) or 0) if "minute" in v.lower() else 0 for v in vals[:3])
    zone1, unknown = [], []
    m = re.search(r'id="Zone-1-content"(.*?)id="Zone-2-content"', page, re.S)
    for name in re.findall(r"<li>([^<]+)</li>", m.group(1) if m else ""):
        code = COUNTRIES.get(html.unescape(name).strip().lower())
        if code and code not in zone1:
            zone1.append(code)
        elif not code:
            unknown.append(name.strip())
    return minutes, zone1, unknown


def parse_prepaid(page, url, captured):
    minutes, zone1, unknown = intl_tables(page)
    out, seen = [], set()
    for card in segments(page, r"<div[^>]*\bdata-tcom-plan-card-name=", 20000):
        btn = re.search(r"<button[^>]*\bdata-prepaid-plancard-main-button[^>]*>", card)
        price_tag = re.search(r"<div[^>]*\bdata-tcom-prepaid-plan-price=[^>]*>", card)
        if not btn or not price_tag:
            continue
        a, pa = attrs(btn.group(0)), attrs(price_tag.group(0))
        sku = a.get("data-plan-id")
        if not sku or sku in seen:
            continue
        seen.add(sku)
        name = a.get("data-plan-name") or a.get("data-plan-market-name")
        price = num(pa.get("data-tcom-prepaid-plan-price")) or num(a.get("data-plan-recurringcharge"))
        body = text(card)
        pm = re.search(r"\b(\d+)\s+(Day|Month)\s+Plan\b", body)
        if not name or not price or not pm:
            continue
        n, unit = int(pm.group(1)), pm.group(2).lower()
        period = n if unit == "day" else 365 if n == 12 else round(n * 30.4375)
        expiry = f"{n} {unit}" + ("s" if n > 1 else "")
        casual = a.get("data-plan-subtype", "").lower() == "casual"
        calls = "unlimited" if "Unlimited calls and texts" in body else "limited"
        rollover = "Continuous data rollover" in body and period < LONG_EXPIRY_DAYS
        z = minutes.get(price) if not casual else None
        intl = list(zone1) if z and z[0] > 0 and "International call minutes" in body else None
        notes = []
        bm = re.search(r"(\d+GB) \+ (\d+GB) Activation Bonus\s+\d+GB (.*?)\. (Activate by [^.]+)\.", body)
        if bm:
            notes.append(f"Activation bonus: +{bm.group(2)} data, {bm.group(3)} ({bm.group(4)}).")
        am = re.search(r"Keep the (\d+GB) bonus data rolling with auto recharge, for up to (\d+) recharges\. ([^.]+)\. ([^.]+)\.", body)
        if am:
            notes.append(f"Black Friday deal: keep the {am.group(1)} bonus with auto recharge for up to "
                         f"{am.group(2)} recharges ({am.group(3)}; {am.group(4)}).")
        if intl:
            notes.append(f"Included international calls are capped: {z[0]} min to Zone 1 (listed countries), "
                         f"{z[1]} min to Zone 2, {z[2]} min to Zone 3 per recharge; 100 international texts.")
        elif "International texts" in body:
            notes.append("International texts only (no international call minutes).")
        if casual:
            notes.append("Casual plan: limited calls and texts (allowances in the CIS).")
        if rollover:
            notes.append("Recharge before expiry to roll over up to 200GB of unused data.")
        if "Uncapped download speeds" in body:
            notes.append("Uncapped download speeds.")
        elif "Capped download speeds" in body:
            notes.append("Download speeds capped (150 or 250 Mbps; see the CIS).")
        if "eSIM price only" in body:
            notes.append("eSIM only at this price.")
        if "Physical SIM only" in body:
            notes.append("Physical SIM only.")
        promo = None
        pp = num(pa.get("data-tcom-prepaid-plan-promo-price"))
        if pp and pp < price:
            dm = re.search(r"(Now \$\d+(?:\.\d+)? Ends [^.]+\.(?: [^.]*only\.)?(?: New activations only, future recharges will be full price\.)?)", body)
            promo = {"price": pp, "periods": 1, "until": long_date(pa.get("data-tcom-prepaid-plan-promo-end-date")),
                     "text": "First recharge with a new SIM: " + (dm.group(1) if dm else f"${pp:g}")}
        out.append({
            "id": f"{PID}-mobile-prepaid-{'casual-' if casual else ''}{price:g}-{n}-{unit}",
            "provider": PID, "name": f"{name} ({expiry})", "network": "telstra", "type": "prepaid",
            "period_days": period, "price": price, "data_gb": gb(a.get("data-plan-data")),
            "data_only": False, "calls": calls, "five_g": True, "intl": intl, "promo": promo,
            "contract": 0, "rollover": rollover, "bundle": [], "credit": None,
            "url": url, "cis_url": next((html.unescape(u) for u in re.findall(r'href="([^"]+)"', card)
                                         if "critical-information-summaries" in u), None),
            "source": STEM, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })
    return out, unknown


def main():
    raw = RAW / STEM
    sim = fetch(SIM_URL, raw / "sim-only-plans.html", min_interval=2.0).decode("utf-8")
    data = fetch(DATA_URL, raw / "data-plans.html", min_interval=2.0).decode("utf-8")
    pre = fetch(PREPAID_URL, raw / "prepaid-mobile-plans.html", min_interval=2.0).decode("utf-8")
    captured = now_iso()
    voice, skipped = parse_upfront(sim, SIM_URL, captured)
    dplans, skipped2 = parse_upfront(data, DATA_URL, captured)
    prepaid, unknown = parse_prepaid(pre, PREPAID_URL, captured)
    if not voice:
        raise RuntimeError("Telstra SIM-only page parsed to zero plans; page layout may have changed")
    if not prepaid:
        raise RuntimeError("Telstra Pre-Paid page parsed to zero plans; page layout may have changed")
    if not dplans:
        print("telstra_mobile: warning: data plans page parsed to zero plans", file=sys.stderr)
    if unknown:
        print(f"telstra_mobile: warning: unmapped Zone 1 countries {unknown}", file=sys.stderr)
    mobile = voice + dplans + prepaid
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"Telstra mobile ids not unique: {ids}")
    meta = {"name": "Telstra SIM-only, data and Pre-Paid plans", "url": SIM_URL,
            "urls": [SIM_URL, DATA_URL, PREPAID_URL], "fetched": captured,
            "skipped_bundle_plans": skipped + skipped2, "unmapped_countries": unknown}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"telstra_mobile: {len(voice)} postpaid, {len(dplans)} data, {len(prepaid)} prepaid")


if __name__ == "__main__":
    main()

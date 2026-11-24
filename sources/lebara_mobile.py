"""Lebara (provider id "lebara"): prepaid SIM and data-only plans from its server-rendered plan
pages (WordPress/WooCommerce, Vodafone network).

Three pages, one request each (robots.txt disallows only wp-admin, WooCommerce internals and
?add-to-cart= links):
  https://www.lebara.com.au/prepaid-plans/28-day/          28-day SIM plans
  https://www.lebara.com.au/prepaid-plans/365-day/         365-day SIM plans
  https://www.lebara.com.au/prepaid-plans/data-only-plans/ data-only plans
Each plan is a `<div class="product-card ..." data-target="#<slug>">` card (repeated once for the
mobile layout; the first copy is used) with:
  - product-card__data "110<span>GB" and, below it, "(55GB + 55GB bonus for first 3 recharges)"
    or, on 365-day plans, "(15GB per 30/35 days)";
  - product-card__price (the price charged now) and, during a sale, "was $<del>35</del>";
  - product-card__expiry "28 day expiry", product-card__title "$35 SIM Plan";
  - the offer terms ("^Get the $50 SIM Plan for $19 for the first 28 days ... Offer ends
    03/12/26") and the bonus-data terms;
  - the CIS link (product-card__link to a PDF).
Each SIM plan also has a `<section id="<slug>" class="plan-sidebar">` listing the countries with
unlimited standard international calls as flag-icon-<iso2> elements.

Notes on the content:
  - Headline data on the cards includes first-recharge bonus data (double data on the $30-$50
    plans, +33% on data-only plans). data_gb is the ongoing allowance, the bonus goes in notes.
  - The sale ("was $35, now $10") is for new customers' first recharge only, so it is a promo
    of one period; the ongoing price is the "was" price. The $35 card's offer text names the
    $25 plan (a typo on the site), so the promo price comes from the card price, not the text.
  - 365-day plans split data and international minutes into eleven 30-day blocks and one 35-day
    block; data_gb is the 365-day total (see notes).
  - Auto Recharge takes 10% off 28-day plans of $25 and above; it is in notes, not the price.
  - Unused data can be banked (up to 500GB) on all these plans, so rollover is true.
  - Lebara's store also lists a "Medium 90 Day" plan in a long-expiry category that its menus
    don't link to; it is not included. Add-ons and roaming packs are skipped.
"""
import html
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, write_norm  # noqa: E402

BASE = "https://www.lebara.com.au"
PAGES = {"28-day": BASE + "/prepaid-plans/28-day/",
         "365-day": BASE + "/prepaid-plans/365-day/",
         "data-only-plans": BASE + "/prepaid-plans/data-only-plans/"}
PID = "lebara"
STEM = pathlib.Path(__file__).stem
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"], 1)}


def clean(s):
    s = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def cards(page):
    """Yield (slug, html) for the first copy of each plan card."""
    starts = [m for m in re.finditer(r'<div class="product-card [^"]*"\s*data-target="#([\w-]+)"', page)]
    seen = set()
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(page)
        sec = page.find("<section id=", m.end())
        if 0 <= sec < end:
            end = sec
        slug = m.group(1)
        if slug not in seen:
            seen.add(slug)
            yield slug, page[m.start():end]


def sidebar(page, slug):
    """{panel title: [(ISO code, country name), ...]} from the plan's side panel."""
    m = re.search(r'<section id="%s"[^>]*class="plan-sidebar">(.*?)</section>' % re.escape(slug), page, re.S)
    out = {}
    for blk in re.split(r'data-title="', m.group(1) if m else "")[1:]:
        title = blk.split('"', 1)[0]
        pairs = re.findall(r'flag-icon-([a-z]{2})\b.*?product-card__country-name">\s*([^<]+?)\s*<', blk, re.S)
        if pairs:
            out[title.lower()] = [(c.upper(), n) for c, n in pairs]
    return out


def offer_end(text, today):
    dates = re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if dates:
        d, m, y = (int(x) for x in dates[-1])
        return date(y + 2000 if y < 100 else y, m, d).isoformat()
    m = re.search(r"Ends (\d{1,2}) (%s)" % "|".join(MONTHS), text, re.I)
    if m:
        mon = MONTHS[m.group(2).lower()]
        y = today.year + (1 if mon < today.month else 0)
        return date(y, mon, int(m.group(1))).isoformat()
    return None


def num(s):
    return float(s.replace(",", ""))


def parse_card(slug, card, page, cat, captured, today):
    t = clean(card)
    title = re.search(r'product-card__title[^"]*">\s*([^<]+?)\s*<', card)
    data = re.search(r'product-card__data">\s*([\d.,]+)\s*<span>\s*(GB|TB)', card)
    price = re.search(r'product-card__price">\s*\$([\d.,]+)', card)
    expiry = re.search(r"(\d+)\s*day expiry", t)
    if not (title and data and price and expiry):
        return None, f"{slug}: title, data, price or expiry not found"
    total = num(data.group(1)) * (1000 if data.group(2) == "TB" else 1)
    was = re.search(r"was \$\s*<del>\s*([\d.,]+)", card)
    now_price = num(price.group(1))
    ongoing = num(was.group(1)) if was else now_price
    period = int(expiry.group(1))
    data_only = cat == "data-only-plans"
    notes = []
    split = re.search(r"\(\s*([\d.]+)\s*GB\s*\+\s*([\d.]+)\s*GB bonus for ([^)]*)\)", t)
    per_block = re.search(r"\(\s*([\d.]+)\s*GB per 30/35 days\s*\)", t)
    data_gb = total
    if split:
        data_gb = num(split.group(1))
        notes.append(f"Bonus {split.group(2)}GB on the {split.group(3).strip()} for new customers "
                     f"({total:g}GB in all); {data_gb:g}GB after that.")
    if per_block:
        notes.append(f"Data comes as {per_block.group(1)}GB per 30-day block (eleven 30-day blocks and one 35-day block).")
    promo = None
    if was and now_price < ongoing:
        terms = next((clean(x) for x in re.findall(r'<div class="panel-content[^"]*">(.*?)</div>', card, re.S)
                      if "^" in x), "")
        head = re.search(r'product-card__promo-title[^"]*">(.*?)</div>', card, re.S)
        text = terms.lstrip("^ ")
        named = re.search(r"\$(\d+) SIM Plan", text)
        if not text or (named and float(named.group(1)) != ongoing):   # the site's text names another plan
            text = f"${now_price:g} for the first {period} days, then ${ongoing:g} per recharge." + \
                (f" {clean(head.group(1))}" if head else "")
        promo = {"price": now_price, "periods": 1,
                 "until": offer_end(terms, today) or offer_end(clean(head.group(1)) if head else "", today),
                 "text": text}
        notes.append("Intro price is for new customers buying online.")
    cap = re.search(r"speed capped at (\d+)\s*Mbps", t)
    if cap:
        notes.append(f"Speed capped at {cap.group(1)} Mbps.")
    intl, calls = None, "none"
    if not data_only:
        calls = "unlimited" if re.search(r"unlimited standard national talk", t, re.I) else "limited"
        panels = sidebar(page, slug)
        unl = next((v for k, v in panels.items() if k.startswith("unlimited standard international")), None)
        intl = list(dict.fromkeys(c for c, _ in unl)) if unl else None
        zone = re.search(r"(\d+) minutes (?:per 30/35 days )?of Zone 1 calls", t)
        zlist = next((v for k, v in panels.items() if "zone 1" in k), None)
        if zone:
            where = ", ".join(n for _, n in zlist) if zlist else "Zone 1 destinations"
            notes.append(f"Also {zone.group(1)} minutes{' per 30-day block' if per_block else ''} of calls to {where}.")
        if intl is None and "international calls" in t.lower():
            notes.append("Includes unlimited standard calls to selected countries (list not read).")
    cis = re.search(r'class="product-card__link" href="([^"]+\.pdf)"', card)
    return {
        "id": f"{PID}-{slug}", "provider": PID, "name": title.group(1).strip(), "network": "vodafone",
        "type": "prepaid", "period_days": period, "price": ongoing, "data_gb": data_gb,
        "data_only": data_only, "calls": calls, "five_g": "5g network" in t.lower(), "intl": intl,
        "promo": promo, "contract": 0, "rollover": True, "credit": None,
        "url": f"{PAGES[cat]}{slug}/", "cis_url": BASE + cis.group(1) if cis and cis.group(1).startswith("/") else (cis.group(1) if cis else None),
        "source": STEM, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
    }, None


def main():
    captured = now_iso()
    today = date.today()
    mobile, skipped = [], []
    for cat, url in PAGES.items():
        page = fetch(url, RAW / STEM / f"{cat}.html", min_interval=3.0).decode("utf-8", "replace")
        auto = re.search(r"Save (\d+)% on 28 day \$(\d+)(?: SIM Plan)? and above Prepaid Recharges with\s*(?:<[^>]+>\s*)*Auto Recharge", page)
        for slug, card in cards(page):
            rec, err = parse_card(slug, card, page, cat, captured, today)
            if err:
                skipped.append(err)
                continue
            if auto and cat == "28-day" and rec["price"] >= float(auto.group(2)):
                rec["notes"] = ((rec["notes"] or "") + f" {auto.group(1)}% off each recharge with Auto Recharge.").strip()
            mobile.append(rec)
    for s in skipped:
        print(f"{STEM}: skipped {s}", file=sys.stderr)
    if not mobile:
        raise RuntimeError("Lebara plan pages parsed to zero plans; page layout may have changed")
    meta = {"name": "Lebara plan pages", "url": PAGES["28-day"], "pages": list(PAGES.values()),
            "fetched": captured, "skipped": skipped}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"{STEM}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

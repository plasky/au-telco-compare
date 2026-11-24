"""Flip (flipconnect.com.au): the prerendered block on each per-tier nbn page.

The site is a single-page app, but every page ships a server-side prerender in
`<div id="app-prerendered">` (markup without classes). Each tier has its own page
(https://flipconnect.com.au/nbn25, /nbn50, /nbn500, /nbn750, /nbn1000, found via the sitemap),
whose plan box reads, as text:
  "Premium SAVE $200 $48/mo For 12 months , then $65.90 ongoing* Typical Evening Speeds:
   25Mbps Download 8Mbps Upload ... No lock-in contract New Customer Discount* ..."
and the hero says "Promo valid on new customers only ... Offer ends 30th November unless
extended." The plan's CIS link sits next to the box. robots.txt allows everything.

Notes on the content:
  - Prerendered markup has no classes or data attributes, so the parse is a text pattern over
    the prerendered block only (not the app's script data).
  - Setup fee and modem price aren't on these pages (the CIS lists a $219 modem and no standard
    connection fee), so setup is None and modem "unknown" for the build to fill.
  - The CIS also lists a "Turbo Boost" 100/20 plan that has no page on the site; it isn't emitted.
  - Senior and veteran plans (separate pages) and satellite are not included. Flip has no 5G
    home internet.
"""
import html
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "flip"
BASE = "https://flipconnect.com.au"
FALLBACK_TIERS = [25, 50, 500, 750, 1000]


def prerendered_text(page):
    i = page.find('id="app-prerendered"')
    if i < 0:
        return ""
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", page[i:], flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def offer_end(s, today):
    """'Offer ends 30th November' (no year) -> the next such date from about a month ago."""
    m = re.search(r"Offer ends (\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)(?:\s+(\d{4}))?", s)
    if not m:
        return None
    years = [int(m.group(3))] if m.group(3) else [today.year, today.year + 1]
    for y in years:
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {y}", "%d %b %Y").date()
        except ValueError:
            return None
        if m.group(3) or d >= today - timedelta(days=31):
            return d.isoformat()
    return None


def tier_pages():
    try:
        sm = fetch(BASE + "/sitemap.xml", RAW / PID / "sitemap.xml").decode("utf-8")
        tiers = sorted({int(t) for t in re.findall(r"<loc>https?://(?:www\.)?flipconnect\.com\.au/nbn(\d+)</loc>", sm)})
    except Exception:
        tiers = []
    return tiers or FALLBACK_TIERS


def main():
    captured = now_iso()
    today = date.today()
    internet, skipped = [], []
    for t in tier_pages():
        url = f"{BASE}/nbn{t}"
        try:
            page = fetch(url, RAW / PID / f"nbn{t}.html").decode("utf-8")
        except Exception as e:  # one missing tier page shouldn't lose the rest
            skipped.append(f"nbn{t} ({type(e).__name__})")
            continue
        s = prerendered_text(page)
        m = re.search(
            r"(?:extended\.\s*)?(?P<name>[A-Z][\w' ]{1,30}?)\s+(?:SAVE \$[\d,.]+\s+)?\$(?P<promo>\d+(?:\.\d+)?)/mo\s+"
            r"For (?P<months>\d+) months?\s*,?\s*then \$(?P<price>\d+(?:\.\d+)?) ongoing\*?\s+"
            r"Typical Evening Speeds:\s*(?P<down>\d+(?:\.\d+)?)Mbps Download\s+(?P<up>\d+(?:\.\d+)?)Mbps Upload", s)
        if not m:
            # A plan with no intro offer: "<name> $X/mo Typical Evening Speeds: ..."
            m2 = re.search(r"(?P<name>[A-Z][\w' ]{1,30}?)\s+\$(?P<price>\d+(?:\.\d+)?)/mo\s+"
                           r"Typical Evening Speeds:\s*(?P<down>\d+(?:\.\d+)?)Mbps Download\s+(?P<up>\d+(?:\.\d+)?)Mbps Upload", s)
            if not m2:
                skipped.append(f"nbn{t} (no plan box)")
                continue
            g, promo = m2.groupdict(), None
        else:
            g = m.groupdict()
            promo = None
            if float(g["promo"]) < float(g["price"]) and 1 <= int(g["months"]) <= 24:
                promo = {"price": float(g["promo"]), "months": int(g["months"]), "until": offer_end(s, today),
                         "text": f"${g['promo']}/mo for {g['months']} months, then ${g['price']} (new customers only)"}
        name = g["name"].strip()
        down, up = float(g["down"]), float(g["up"])
        tier = tier_from(f"nbn{t}", down) if t in (12, 25, 50, 100, 250, 500, 750, 1000, 2000) else tier_from(name, down)
        if not tier:
            skipped.append(f"{name} (no tier)")
            continue
        cis = re.search(r'href="([^"]*/storage/pdf/nbn/[^"]*CIS[^"]*\.pdf)"', page)
        notes = []
        if promo:
            notes.append("Promo for new customers only (not previous Flip customers at any address).")
        internet.append({
            "id": f"{PID}-{slug(name)}-nbn{t}", "provider": PID, "name": name, "kind": "nbn", "tier": tier,
            "techs": techs_for("nbn", tier), "down": down, "up": up, "price": float(g["price"]), "promo": promo,
            "setup": None, "contract": 0 if re.search(r"No lock-in contract", s, re.I) else 1,
            "modem": {"offer": "unknown", "cost": None}, "data_gb": None, "network": None, "credit": None,
            "bundle": [], "url": url, "cis_url": cis.group(1) if cis else None, "source": PID,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })

    if not internet:
        raise RuntimeError("flip: tier pages parsed to zero plans; page layout may have changed")
    meta = {"name": "Flip per-tier nbn pages (prerendered)", "url": BASE, "fetched": captured, "skipped": skipped}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"flip: {len(internet)} internet (skipped: {', '.join(skipped) or 'none'})")


if __name__ == "__main__":
    main()

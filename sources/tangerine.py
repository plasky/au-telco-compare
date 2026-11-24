"""Tangerine: plan cards on its server-rendered nbn plans page.

https://www.tangerine.com.au/nbn/nbn-broadband lists the plans offered before an address check,
one `<div class="... product-speeds ...">` card each, with:
  - `<h3>` plan name, "860Mbps Download /85Mbps Upload Typical Evening Speed (7-11pm)";
  - the price shown (`<span class="heading">$89<span>.90/MTH`), which is the intro price while the
    new-customer discount runs, and "For 6 months, then $114.90 ongoing^";
  - the offer tooltip ("Get a $25/mth discount off RRP for 6 months ...") and feature list
    (FREE STANDARD CONNECTION, NO LOCK-IN CONTRACT, notices such as an upcoming RRP change);
  - an add-to-cart button with data-product-type="speed" and data-product-price (the shown price).
Router options are buttons with data-product-type="modem" (outright and 12-month instalment
prices). robots.txt allows the page.

Notes on the content:
  - Only the plans shown before an address check are here (currently Value, Speedy Max and
    UltraSpeedy). The copper-only plans (Value Plus, Speedy, Speedy Plus) appear only after the
    address check (a POST), so they need manual overrides from the CIS.
  - The mobile bundle is 10% off the mobile SIM plan, not an internet discount: `bundle` is empty.
  - Mobile broadband (5G data-only SIMs) is a mobile product, not 5G home internet.
"""
import html
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "tangerine"
URL = "https://www.tangerine.com.au/nbn/nbn-broadband"
CIS_URL = "https://www.tangerine.com.au/unlimitednbncis"


def text(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s):
    m = re.search(r"\$\s*(\d+)\s*(?:\.\s*(\d+))?", s or "")
    return float(f"{m.group(1)}.{m.group(2) or 0}") if m else None


def notice_date(s, today):
    """'FROM 1 DEC, ...' -> the next 1 December on or after about a month ago."""
    m = re.search(r"\bFROM (\d{1,2}) ([A-Z]{3})", s.upper())
    if not m:
        return None
    for year in (today.year, today.year + 1):
        try:
            d = datetime.strptime(f"{m.group(1)} {m.group(2).title()} {year}", "%d %b %Y").date()
        except ValueError:
            return None
        if d >= today - timedelta(days=31):
            return d
    return None


def cheapest_modem(page):
    """Cheapest router you can buy outright (each router has an outright and an instalment
    button; the outright price is the larger), or None if none is listed."""
    best = {}
    for m in re.finditer(r"<button\b[^>]*>", page):
        a = dict(re.findall(r'data-([\w-]+)="([^"]*)"', m.group(0)))
        if a.get("product-type") != "modem":
            continue
        if "byo" in a.get("product-name", "").lower() or not a.get("product-id"):
            continue
        try:
            price = float(a.get("product-price", ""))
        except ValueError:
            continue
        best[a["product-id"]] = max(best.get(a["product-id"], 0.0), price)
    return min(best.values()) if best else None


def main():
    page = fetch(URL, RAW / PID / "nbn-broadband.html").decode("utf-8")
    captured = now_iso()
    today = date.today()
    starts = [m.start() for m in re.finditer(r'<div class="wow fadeInUp product-speeds', page)]
    modem_cost = cheapest_modem(page)
    modem = {"offer": "purchase", "cost": modem_cost} if modem_cost is not None else {"offer": "unknown", "cost": None}

    internet, skipped = [], []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else len(page)
        seg = page[a:b]
        cut = seg.find("vff-plan-points")          # Velocity points block follows the price
        card = seg[:cut] if cut > 0 else seg[:20000]
        nm = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.S)
        if not nm:
            continue
        name = text(nm.group(1))
        sp = re.search(r"(\d+(?:\.\d+)?)\s*Mbps Download\s*/\s*(\d+(?:\.\d+)?)\s*Mbps Upload", text(card))
        down, up = (float(sp.group(1)), float(sp.group(2))) if sp else (None, None)
        shown = re.search(r'<span class="heading"\s*>(.*?)</span>\s*</span>', card, re.S)
        shown = money(text(shown.group(1) + "</span>")) if shown else None
        foot = re.search(r'plan_footer[^"]*"[^>]*>(.*?)</p>', card, re.S)
        foot = text(foot.group(1)) if foot else ""
        fm = re.search(r"For (\d+) months?, then \$(\d+(?:\.\d+)?) ongoing", foot, re.I)
        if fm:
            price, promo = float(fm.group(2)), {"price": shown, "months": int(fm.group(1)), "until": None, "text": foot}
        else:
            price, promo = shown, None
        if not price:
            skipped.append(f"{name} (no price)")
            continue
        if promo and (not promo["price"] or promo["price"] >= price):
            promo = None
        features = [text(li) for li in re.findall(r"<li>(.*?)</li>", card, re.S)]
        tip = re.search(r'popular-plan speed_tooltip.*?title="([^"]*)"', card, re.S)
        if promo and tip:
            tip_text = html.unescape(tip.group(1))
            promo["text"] = f"{tip_text} ({foot})"
            dm = re.search(r"between \d{1,2}/\d{1,2}/\d{2,4} and (\d{1,2})/(\d{1,2})/(\d{2,4})", tip_text)
            if dm:
                y = int(dm.group(3)) + (2000 if len(dm.group(3)) == 2 else 0)
                promo["until"] = date(y, int(dm.group(2)), int(dm.group(1))).isoformat()
        notes = []
        for f in features:
            if re.search(r"\bFROM \d{1,2} [A-Z]{3}\b", f):
                n = re.sub(r"\brrp\b", "RRP", f.capitalize())
                notes.append(re.sub(r"\b(\d{1,2}) ([a-z]{3})\b", lambda m: f"{m.group(1)} {m.group(2).title()}", n))
                d = notice_date(f, today)
                if promo and d and re.search(r"discount is ending", f, re.I):
                    promo["until"] = (d - timedelta(days=1)).isoformat()
        if promo:
            notes.append("Discount for new customers only, on one nbn plan per account.")
        tier = tier_from(name, down)
        if not tier:
            skipped.append(f"{name} (no tier)")
            continue
        setup = 0.0 if any("FREE STANDARD CONNECTION" in f.upper() for f in features) else None
        contract = 0 if any("NO LOCK-IN" in f.upper() for f in features) else 1
        internet.append({
            "id": f"{PID}-{slug(name)}", "provider": PID, "name": name, "kind": "nbn", "tier": tier,
            "techs": techs_for("nbn", tier), "down": down, "up": up, "price": price, "promo": promo,
            "setup": setup, "contract": contract, "modem": dict(modem), "data_gb": None, "network": None,
            "credit": None, "bundle": [], "url": URL, "cis_url": CIS_URL, "source": PID,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })

    if not internet:
        raise RuntimeError("tangerine: nbn page parsed to zero plans; page layout may have changed")
    meta = {"name": "Tangerine nbn plans page (plans shown before an address check)", "url": URL,
            "fetched": captured, "skipped": skipped}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"tangerine: {len(internet)} internet (skipped: {', '.join(skipped) or 'none'})")


if __name__ == "__main__":
    main()

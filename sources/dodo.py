"""Dodo: plan tiles on its server-rendered nbn plans page (Drupal).

https://www.dodo.com/nbn carries one `<div class="plan-tile" data-plan-id=... data-plan-name=...>`
per plan. Inside each tile:
  - `data-price-type="original"` holds the ongoing price when the tile shows a discount, and
    `price-amount` the price actually shown (the intro price while an offer runs);
  - the offer badge ("$30 MTH OFF FOR 6 MONTHS") gives the promo length, and the tile's
    `plan-terms` line ("Offer ends 8 Dec 2026") the last sign-up date;
  - "Typical evening speeds (7-11pm): 100 Mbps download. 20 Mbps upload.";
  - connection-type pills (FTTN/FTTC/FTTB/HFC/FTTP, or FW for fixed wireless).
Page-wide facts (no standard connection fee, modem price, new-customer condition) come from the
page text. robots.txt allows the page.

Notes on the content:
  - Fixed wireless tiles (pill "FW") are skipped: this adapter covers fixed-line nbn only.
  - Dodo sells its nbn100 plan on FTTN/FTTB/FTTC only and the 500/750/1000 plans on FTTP/HFC
    only (the CIS says the same), so techs are the published pills, limited to what
    `techs_for` allows for the tier.
  - The CIS also lists an "nbn15" tier that the plans page doesn't show; it isn't emitted.
  - Dodo has no 5G home internet. Its energy bundle page offers a $19/mth "Infinity" mobile
    plan to nbn customers (a mobile price, not an internet discount), so `bundle` stays empty.
"""
import html
import pathlib
import re
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "dodo"
BASE = "https://www.dodo.com"
URL = BASE + "/nbn"
CIS_FALLBACK = BASE + "/plan-summaries/nbn-cis"
TECH = {"FTTN": "fttn", "FTTC": "fttc", "FTTB": "fttb", "HFC": "hfc", "FTTP": "fttp"}


def text(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s):
    m = re.search(r"\$\s*(\d+(?:\s*\.\s*\d+)?)", s or "")
    return float(re.sub(r"\s", "", m.group(1))) if m else None


def nice_name(raw):
    """'FAST PLUS NBN500/50' -> 'Fast Plus NBN500/50' (speed codes stay upper case)."""
    return " ".join(w if re.search(r"\d", w) or w in ("NBN", "FW") else w.capitalize() for w in raw.split())


def offer_date(s):
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def tiles(page):
    """Yield (wrapper class, tile html). Each tile sits in a
    `<div [class="..."] data-component-id="dodo_bootstrap:plan_tile">` wrapper; fixed wireless
    wrappers carry class "fw-plan"."""
    wraps = list(re.finditer(r'<div\s+(?:class="([^"]*)"\s+)?data-component-id="dodo_bootstrap:plan_tile"', page))
    for i, m in enumerate(wraps):
        b = wraps[i + 1].start() if i + 1 < len(wraps) else min(len(page), m.start() + 30000)
        seg = page[m.start():b]
        if re.search(r'<div\s+class="plan-tile"[^>]*data-plan-id=', seg):
            yield m.group(1) or "", seg


def main():
    page = fetch(URL, RAW / PID / "nbn.html").decode("utf-8")
    captured = now_iso()
    body = text(page)

    setup = 0.0 if re.search(r"don.t charge any fees for a standard connection", body, re.I) else None
    modem = {"offer": "unknown", "cost": None}
    mm = re.search(r"modem\s+\$[\d.]+\s*/\s*mth for \d+ months or \$(\d+(?:\.\d+)?) upfront", body, re.I)
    if mm:
        modem = {"offer": "purchase", "cost": float(mm.group(1))}
    new_only = bool(re.search(r"new (?:nbn )?customers only", body, re.I))
    cis = re.search(r'href="([^"]*plan-summaries/nbn-cis[^"]*)"', page)
    cis_url = (BASE + cis.group(1) if cis.group(1).startswith("/") else cis.group(1)) if cis else CIS_FALLBACK

    internet, seen, skipped = [], set(), []
    for wrap_class, seg in tiles(page):
        raw_name = html.unescape(re.search(r'data-plan-name="([^"]*)"', seg).group(1)).strip()
        name = nice_name(raw_name)
        pills = [p.upper() for p in re.findall(r'class="pill(?:\s[\w-]+)*">\s*([A-Za-z]+)\s*</div>', seg)]
        if "FW" in pills or "fw-plan" in wrap_class.split():
            skipped.append(f"{name} (fixed wireless)")
            continue
        sp = re.search(r"Typical evening speeds?[^<]*</p>\s*<p>(.*?)</p>", seg, re.S)
        sp = text(sp.group(1)) if sp else ""
        dm = re.search(r"(\d+(?:\.\d+)?)\s*Mbps download", sp)
        um = re.search(r"(\d+(?:\.\d+)?)\s*Mbps upload", sp)
        down = float(dm.group(1)) if dm else None
        up = float(um.group(1)) if um else None

        orig = re.search(r'data-price-type="original"[^>]*>(.*?)</span>', seg, re.S)
        shown = re.search(r'class="price-amount">(.*?)</span>\s*<span class="pricing-duration', seg, re.S)
        shown = money(text(shown.group(1))) if shown else None
        ongoing = money(text(orig.group(1))) if orig else None
        price = ongoing or shown
        if not price:
            skipped.append(f"{name} (no price)")
            continue

        promo = None
        badge = re.search(r'plan_tile_offer_badge"[^>]*>(.*?)</div>', seg, re.S)
        badge = text(badge.group(1)) if badge else ""
        terms = re.search(r'class="plan-terms">(.*?)</p>', seg, re.S)
        terms = text(terms.group(1)) if terms else ""
        if ongoing and shown and shown < ongoing:
            months = re.search(r"(\d+)\s*MONTHS?", badge, re.I)
            if months:
                promo = {"price": shown, "months": int(months.group(1)), "until": offer_date(terms),
                         "text": "; ".join(x for x in (badge.capitalize(), terms) if x)}

        tier = tier_from(raw_name, down)
        if not tier:
            skipped.append(f"{name} (no tier)")
            continue
        techs = techs_for("nbn", tier)
        published = [TECH[p] for p in pills if p in TECH]
        if published:
            techs = [t for t in techs if t in published] or techs

        rid = f"{PID}-{slug(raw_name)}"
        if rid in seen:
            continue
        seen.add(rid)
        notes = ["Promo for new nbn customers only."] if promo and new_only else []
        internet.append({
            "id": rid, "provider": PID, "name": name, "kind": "nbn", "tier": tier, "techs": techs,
            "down": down, "up": up, "price": price, "promo": promo, "setup": setup,
            "contract": 0, "modem": dict(modem), "data_gb": None,
            "network": None, "credit": None, "bundle": [], "url": URL, "cis_url": cis_url,
            "source": PID, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })

    if not internet:
        raise RuntimeError("dodo: nbn page parsed to zero plans; page layout may have changed")
    meta = {"name": "Dodo nbn plans page", "url": URL, "fetched": captured, "skipped": skipped}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"dodo: {len(internet)} internet (skipped: {', '.join(skipped) or 'none'})")


if __name__ == "__main__":
    main()

"""Mate (letsbemates.com.au): plan slides on its server-rendered nbn page (WordPress).

https://www.letsbemates.com.au/nbn/ has one
`<div class="slide-item ... nbn-slide-item" data-plan-type="popular, FTTNB, FTTC, HFC, FTTP">` per
plan, with the plan name (`<h3>`) and tier (`<h4>nbn® 100/20</h4>`), typical busy-period speeds
(`<div class="mbps ...">97 Mbps</div>` for download then upload), the ongoing price struck through
next to the intro price, "*for the first 6 months, then reverts to $100/month", the promo code
and its terms ("... between 1 April 2026 and 31 December 2026 ... $25 ... for each of its first
six billing months"), the mobile bundle saving ("a further $10 per month off this plan") and the
plan's CIS link. robots.txt allows the page.

Notes on the content:
  - data-plan-type lists the connection types; "fixed-wireless" slides are skipped (fixed-line
    nbn only). FTTNB means FTTN and FTTB.
  - The page says every plan has "zero setup fees"; the modem is optional (BYO, or buy a TP-Link
    for the price shown in the modem section).
  - Mate has no 5G home internet (its "5G" pages are mobile plans).
"""
import html
import pathlib
import re
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "mate"
URL = "https://www.letsbemates.com.au/nbn/"
TECH = {"FTTNB": ["fttn", "fttb"], "FTTN": ["fttn"], "FTTB": ["fttb"], "FTTC": ["fttc"],
        "HFC": ["hfc"], "FTTP": ["fttp"]}


def text(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s):
    m = re.search(r"\$\s*(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else None


def long_date(s):
    try:
        return datetime.strptime(s, "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def main():
    page = fetch(URL, RAW / PID / "nbn.html").decode("utf-8")
    captured = now_iso()
    body = text(page)
    setup = 0.0 if re.search(r"\b(?:zero|no) setup fees?\b", body, re.I) else None
    mm = re.search(r"TP-Link [\w-]+ is our do-it-all modem/router.*?\$(\d+(?:\.\d+)?)", body)
    modem = {"offer": "purchase", "cost": float(mm.group(1))} if mm else {"offer": "unknown", "cost": None}

    slides = list(re.finditer(r'<div class="slide-item [^"]*nbn-slide-item[^"]*" data-plan-type="([^"]*)"', page))
    internet, skipped, seen = [], [], set()
    for i, m in enumerate(slides):
        seg = page[m.start():slides[i + 1].start() if i + 1 < len(slides) else m.start() + 40000]
        kinds = [k.strip() for k in m.group(1).split(",") if k.strip()]
        h3 = re.search(r"<h3[^>]*>(.*?)</h3>", seg, re.S)
        h4 = re.search(r"<h4[^>]*>(.*?)</h4>", seg, re.S)
        if not h3:
            continue
        label = f"{text(h3.group(1))} {text(h4.group(1)) if h4 else ''}".replace("®", "").strip()
        name = re.sub(r"\s+", " ", label)
        if "fixed-wireless" in kinds:
            skipped.append(f"{name} (fixed wireless)")
            continue
        speeds = [float(x) for x in re.findall(r'class="mbps[^"]*">.*?(\d+(?:\.\d+)?)\s*Mbps\s*</div>', seg, re.S)]
        down, up = (speeds + [None, None])[:2]
        strike = re.search(r'text-decoration-line-through[^>]*>(.*?)</span>', seg, re.S)
        green = re.search(r'<span class="text-green fw-bold">(.*?)</span>', seg, re.S)
        ongoing, shown = (money(text(strike.group(1))) if strike else None), (money(text(green.group(1))) if green else None)
        rev = re.search(r"for the first (\d+) months?, then reverts to \$(\d+(?:\.\d+)?)", text(seg))
        if rev:
            ongoing = float(rev.group(2))
        price = ongoing or shown
        if not price:
            skipped.append(f"{name} (no price)")
            continue
        promo, notes = None, []
        if shown and ongoing and shown < ongoing and rev:
            code = re.search(r"Use promo code (\w+)", text(seg))
            terms = re.search(r"Sign up using the promo code (\w+).*?between (\d{1,2} \w+ \d{4}) and (\d{1,2} \w+ \d{4})[^.]*", text(seg))
            desc = f"${ongoing - shown:g}/mth off for {rev.group(1)} months"
            if code:
                desc += f" with promo code {code.group(1)}"
            if terms:
                desc += f" (new nbn services activated {terms.group(2)} to {terms.group(3)})"
            promo = {"price": shown, "months": int(rev.group(1)),
                     "until": long_date(terms.group(3)) if terms else None, "text": desc}
            if code:
                notes.append(f"Promo needs code {code.group(1)}; new nbn services only.")
        bundle = []
        bm = re.search(r"further \$(\d+(?:\.\d+)?) per month off this plan when you bundle[^.]*mobile plan", text(seg))
        if bm:
            bundle = [{"with": "mobile", "off": float(bm.group(1)),
                       "text": f"${bm.group(1)}/mth off with a MATE mobile plan"}]
        tier = tier_from(name, down)
        if not tier:
            skipped.append(f"{name} (no tier)")
            continue
        published = sorted({t for k in kinds for t in TECH.get(k.upper(), [])})
        techs = techs_for("nbn", tier)
        if published:
            techs = [t for t in techs if t in published] or techs
        cis = re.search(r'href="([^"]*/cis/[^"]*\.pdf)"', seg)
        rid = f"{PID}-{slug(name)}"
        if rid in seen:
            continue
        seen.add(rid)
        internet.append({
            "id": rid, "provider": PID, "name": name, "kind": "nbn", "tier": tier, "techs": techs,
            "down": down, "up": up, "price": price, "promo": promo, "setup": setup, "contract": 0,
            "modem": dict(modem), "data_gb": None, "network": None, "credit": None, "bundle": bundle,
            "url": URL, "cis_url": cis.group(1) if cis else None, "source": PID, "captured": captured,
            "verified": True, "notes": " ".join(notes) or None,
        })

    if not internet:
        raise RuntimeError("mate: nbn page parsed to zero plans; page layout may have changed")
    meta = {"name": "MATE nbn plans page", "url": URL, "fetched": captured, "skipped": skipped}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"mate: {len(internet)} internet (skipped: {', '.join(skipped) or 'none'})")


if __name__ == "__main__":
    main()

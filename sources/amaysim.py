"""amaysim: its machine-readable catalogue page (published for AI assistants and crawlers).

https://www.amaysim.com.au/products/catalogue/plans has two tables (SIM plans, NBN plans).
Each row carries data-* attributes (price, data, duration, network, speeds, promo validity),
so parsing doesn't depend on the visible layout. robots.txt allows the page.

Notes on the content:
  - data-price-aud is the ongoing price. NBN promo terms are only in the description text
    ("$30/month for the first 6 months ... then $70/month thereafter, unless bundled at
    $60/month with an active amaysim SIM plan"). The "then $70" figure is repeated on every
    tier, so the ongoing price comes from the attribute and only the promo price/length and
    the bundle saving (70 - 60 = $10) come from the text.
  - NBN download figures are typical evening speeds (680 on the 750 plan, 820 on the 1000).
  - SIM promos need a coupon and the text gives no promo price, so they are kept as notes.
"""
import html
import re
import sys
import pathlib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, techs_for, tier_from, write_norm  # noqa: E402

URL = "https://www.amaysim.com.au/products/catalogue/plans"
PID = "amaysim"
AEST = timezone(timedelta(hours=10))


def rows(page):
    for table in re.findall(r"<table.*?</table>", page, re.S):
        for attrs, body in re.findall(r"<tr([^>]*)>(.*?)</tr>", table, re.S):
            a = {k: v.strip('"') for k, v in re.findall(r"data-([\w-]+)=(\"[^\"]*\"|[^\s>]+)", attrs)}
            if not a.get("sku"):
                continue
            cells = [html.unescape(re.sub(r"<.*?>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
            links = [html.unescape(u) for u in re.findall(r'href="([^"]+)"', body)]
            yield a, cells, links


def local_date(ts):
    """Promo end timestamps are UTC instants just before local midnight; report the AEST date."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(AEST).date().isoformat()


def clean_url(u):
    return re.sub(r"[?&]channel=agentic", "", u).rstrip("?") if u else None


def main():
    page = fetch(URL, RAW / "amaysim" / "catalogue.html").decode("utf-8")
    captured = now_iso()
    m = re.search(r"Generated[^0-9]*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", page)
    generated = m.group(1) if m else None
    internet, mobile = [], []
    for a, cells, links in rows(page):
        name = cells[0] if cells else a["sku"]
        promo_text = cells[10] if len(cells) > 10 else ""
        view = clean_url(next((u for u in links if "/cart/" not in u), None)) \
            or clean_url(next((re.sub(r"[?&](storeId|action)=[^&]*", "", u) for u in links), None))
        if a.get("plan-type") == "nbn":
            down, up = float(a["download-mbps"]), float(a["upload-mbps"])
            tier = tier_from(name, down)
            promo, bundle = None, []
            pm = re.search(r"\$(\d+(?:\.\d+)?)/month for the first (\d+) months?", promo_text)
            if a.get("promo-active") == "true" and pm:
                promo = {"price": float(pm.group(1)), "months": int(pm.group(2)),
                         "until": local_date(a.get("promo-valid-through")), "text": promo_text}
            bm = re.search(r"then \$(\d+(?:\.\d+)?)/month.*?bundled at \$(\d+(?:\.\d+)?)/month with an active amaysim SIM", promo_text)
            if bm and float(bm.group(1)) > float(bm.group(2)):
                bundle = [{"with": "mobile", "off": round(float(bm.group(1)) - float(bm.group(2)), 2),
                           "text": "Cheaper with an active amaysim SIM plan"}]
            internet.append({
                "id": f"{PID}-{a['sku']}", "provider": PID, "name": name, "kind": "nbn", "tier": tier,
                "techs": techs_for("nbn", tier), "down": down, "up": up, "price": float(a["price-aud"]),
                "promo": promo, "setup": None, "contract": 0, "modem": {"offer": "unknown", "cost": None},
                "data_gb": None, "bundle": bundle, "url": view, "cis_url": None, "source": PID,
                "captured": captured, "verified": True,
                "notes": "Promo needs a coupon; new services only." if a.get("coupon-required") == "yes" and promo else None,
            })
        else:
            talk = cells[4].lower() if len(cells) > 4 else ""
            data_only = talk in ("na", "n/a", "")
            notes = None
            if a.get("promo-active") == "true" and promo_text:
                notes = f"Current offer (coupon {'needed' if a.get('coupon-required') == 'yes' else 'not needed'}): {promo_text}"
            mobile.append({
                "id": f"{PID}-{a['sku']}", "provider": PID, "name": name,
                "network": "optus" if "optus" in a.get("network", "").lower() else None,
                "type": "prepaid" if a.get("plan-type", "prepaid") == "prepaid" else "postpaid",
                "period_days": int(a["duration-days"]), "price": float(a["price-aud"]),
                "data_gb": float(a["data-gb"]) if a.get("data-gb") else None, "data_only": data_only,
                "calls": "none" if data_only else "unlimited" if "unlimited" in talk else "limited",
                "five_g": "5g" in a.get("network", "").lower(), "intl": None, "promo": None, "contract": 0,
                "url": view, "source": PID, "captured": captured, "verified": True, "notes": notes,
            })
    if not internet and not mobile:
        raise RuntimeError("amaysim catalogue parsed to zero plans; page layout may have changed")
    meta = {"name": "amaysim plan catalogue", "url": URL, "fetched": captured, "generated": generated}
    write_norm(PID, {"internet": internet, "mobile": mobile}, meta)
    print(f"amaysim: {len(internet)} internet, {len(mobile)} mobile")


if __name__ == "__main__":
    main()

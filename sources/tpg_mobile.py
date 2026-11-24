"""TPG and iiNet (TPG Telecom, Vodafone network): SIM-only mobile plans from each brand's own SIM page.

  https://www.tpg.com.au/mobile              (TPG)
  https://www.iinet.net.au/sim-only-plans    (iiNet; /mobile redirects here)

Both brands run the same Drupal site build. The plan cards are drawn by a JavaScript product
configurator, but each page also carries, in static HTML:
  - a schema.org ProductGroup in an inline script (var mobileSchema = '{...}') with each plan's
    name, data allowance, network type, speed cap, international inclusions and offer price;
  - the offer terms ("50% off eligible ... SIM Only mobile plan standard monthly fees for your first
    6 months. Eligible plans: ... Small 30GB, Medium 50GB and Large 100GB ...") and the internet
    bundling terms ("$5/mth off Medium and Large standard monthly mobile plan fees with a linked
    ... internet from month 7").
robots.txt allows both pages. One request per brand.

Notes on the content:
  - The JSON-LD price is the intro (discounted) price. The ongoing price is not in the static HTML,
    so it is derived: offer price / (1 - percent off). Checks guard the derivation: where a page
    states a revert price ("50GB for $17.50/mth ... Reverts to $35/mth") it must match, and the
    existing-customer offer ("$20/mth off the Medium ... standard price", sold as "better than 50%
    off") must still be better than the percentage discount. On 24 Nov 2026 the derived prices
    ($30/$35/$45) matched TPG's plan brochure PDF (pricing as of 20 Sep 2026).
  - If a page advertises a % off in its title but the offer terms aren't found, the adapter stops
    rather than guess which price the JSON-LD shows.
  - The bundling saving is on the SIM (mobile fee), from month 7, and never during an intro offer.
  - Plans are paid monthly in advance and auto-renew (the brands call this prepaid); there are no
    recharges, so they are typed "postpaid" (a monthly plan) with a note.
  - Included international calls go to 31 destinations whose list is only in the brochure PDF,
    so intl is None with a note.
  - Excess data is $10 per 2GB from an optional prepaid balance; without one, data stops.
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, write_norm  # noqa: E402

STEM = "tpg_mobile"
BRANDS = {
    "tpg": {"label": "TPG", "url": "https://www.tpg.com.au/mobile", "cis": "https://www.tpg.com.au/terms_conditions/CIS"},
    "iinet": {"label": "iiNet", "url": "https://www.iinet.net.au/sim-only-plans", "cis": None},
}


def page_text(page):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s)


def schema(page, label):
    m = re.search(r"mobileSchema\s*=\s*'(\{.*?\})'\s*;", page, re.S)
    if not m:
        raise RuntimeError(f"tpg_mobile {label}: mobileSchema JSON-LD not found")
    return json.loads(m.group(1))


def prop(variant, name):
    for p in variant.get("additionalProperty") or []:
        if (p.get("name") or "").lower() == name.lower():
            return str(p.get("value") or "")
    return ""


def money(s):
    return float(s.replace(",", ""))


def record(pid, b, v, offer, extra, pt, captured):
    label = b["label"]
    size = re.sub(rf"(?i)^{label}\s+|\s+mobile plan$", "", v.get("name") or "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", prop(v, "Data Allowance"))
    if not size or not m:
        return None
    data = float(m.group(1))
    shown = float(v["offers"]["price"])

    price, promo, notes = shown, None, []
    if offer and size.lower() in offer["eligible"]:
        price = round(shown / (1 - offer["pct"] / 100), 2)
        promo = {"price": shown, "periods": offer["months"], "until": None,
                 "text": f"{offer['pct']:g}% off the standard monthly fee for the first {offer['months']} months. "
                         "New connections only; forfeited if you change or cancel the plan in that time. Available until withdrawn."}
        stated = extra["reverts"].get(data)
        if stated and (abs(stated[0] - shown) > 0.01 or abs(stated[1] - price) > 0.01):
            raise RuntimeError(f"tpg_mobile {label}: derived {size} price {price} disagrees with the page's "
                               f"'${stated[0]:g}/mth ... Reverts to ${stated[1]:g}/mth'")
        better = extra["existing"].get(size.lower())
        if better is not None:
            if better <= price * offer["pct"] / 100:
                raise RuntimeError(f"tpg_mobile {label}: existing-customer ${better:g} off is not better than "
                                   f"{offer['pct']:g}% of derived {price}; the JSON-LD may now show standard prices")
            notes.append(f"Existing {label} customers who log in get ${better:g}/mth off for the first "
                         f"{offer['months']} months instead (${price - better:g}/mth).")

    bundle = []
    bd = extra["bundle"]
    if bd and size.lower() in bd["eligible"]:
        bundle = [{"with": "internet", "off": bd["off"], "during_promo": False,
                   "text": f"${bd['off']:g}/mth off with a linked {label} internet plan from month {bd['from']} "
                           "(paused while another offer applies)"}]

    cap = re.search(rf"{re.escape(size)} Plan: (\d+)\s*Mbps on our ([45]G(?: and 5G)?) networks", pt)
    five_g = bool(cap and "5G" in cap.group(2)) or prop(v, "Network Type").upper() == "5G"
    if cap:
        notes.append(f"Speed capped at {cap.group(1)}Mbps.")
    intl_text = prop(v, "International Inclusions") or (v.get("description") or "")
    mi = re.search(r"(?i)\b(\d+|unlimited)\s+(?:standard\s+)?international minutes and SMS(?: to (\d+) destinations)?", intl_text)
    if mi:
        n = mi.group(2) or (re.search(r"to (\d+) destinations", pt) or [None, "31"])[1]
        notes.append(f"Includes {mi.group(1).lower()} international minutes and SMS a month to {n} destinations "
                     "(the destination list is not on the page).")
    notes.append("Excess data $10 per 2GB from an optional prepaid balance; without one, data stops until the next month.")
    notes.append("Paid monthly in advance and auto-renews (the provider calls it prepaid); no lock-in.")
    calls = prop(v, "National Calls and Texts") or ""
    return {
        "id": f"{pid}-mobile-{size.lower()}", "provider": pid, "name": f"{size} {data:g}GB",
        "network": "vodafone", "type": "postpaid", "period_days": 30, "price": price, "data_gb": data,
        "data_only": False,
        "calls": "unlimited" if re.search(r"(?i)unlimited", calls) or re.search(r"(?i)unlimited standard national calls", v.get("description") or "") else "unknown",
        "five_g": five_g, "intl": None, "promo": promo, "contract": 0,
        "rollover": False if re.search(r"(?i)does not roll ?over|forfeited at the end of each monthly billing period", pt) else None,
        "bundle": bundle, "credit": None, "url": b["url"], "cis_url": b["cis"], "source": STEM,
        "captured": captured, "verified": True, "notes": " ".join(notes),
    }


def terms(pt, label):
    offer = None
    m = re.search(rf"(\d+)% off eligible {label} SIM Only mobile plan standard monthly fees for your first (\d+) months", pt)
    if m:
        el = re.search(rf"Eligible plans: Available on (.*?) {label} SIM Only Mobile plans", pt)
        eligible = {w.lower() for w in re.findall(r"(Small|Medium|Large)", el.group(1))} if el else set()
        offer = {"pct": float(m.group(1)), "months": int(m.group(2)), "eligible": eligible}
    reverts = {}
    for gb, intro, ongoing in re.findall(r"(\d+)GB for \$(\d+(?:\.\d+)?)/mth\.[^$]{0,80}Reverts to \$(\d+(?:\.\d+)?)/mth", pt):
        reverts[float(gb)] = (money(intro), money(ongoing))
    existing = {}
    for off, size in re.findall(r"\$(\d+(?:\.\d+)?)/mth off the (Small|Medium|Large) mobile plan standard price", pt):
        existing.setdefault(size.lower(), money(off))
    bundle = None
    m = re.search(rf"\$(\d+(?:\.\d+)?)/mth off ((?:Small|Medium|Large)(?:,? (?:and )?(?:Small|Medium|Large))*) standard monthly "
                  rf"mobile plan fees with a linked {label} internet from month (\d+)", pt)
    if m:
        bundle = {"off": money(m.group(1)), "eligible": {w.lower() for w in re.findall(r"Small|Medium|Large", m.group(2))},
                  "from": int(m.group(3))}
    return offer, {"reverts": reverts, "existing": existing, "bundle": bundle}


def main():
    mobile, captured = [], now_iso()
    for pid, b in BRANDS.items():
        page = fetch(b["url"], RAW / STEM / f"{pid}.html", min_interval=2.0, retries=2).decode("utf-8", "replace")
        pt = page_text(page)
        title = (re.search(r"<title>(.*?)</title>", page, re.S) or [None, ""])[1]
        offer, extra = terms(pt, b["label"])
        if not offer and re.search(r"(?i)\d+% off", title):
            raise RuntimeError(f"tpg_mobile {pid}: title advertises a discount but the offer terms weren't parsed")
        if "Vodafone network" not in pt:
            raise RuntimeError(f"tpg_mobile {pid}: page no longer mentions the Vodafone network; check the host network")
        recs = [record(pid, b, v, offer, extra, pt, captured) for v in schema(page, pid).get("hasVariant") or []]
        recs = [r for r in recs if r]
        if not recs:
            raise RuntimeError(f"tpg_mobile {pid}: no plans parsed from {b['url']}")
        mobile += recs
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"tpg_mobile: duplicate record ids {sorted(ids)}")
    meta = {"name": "TPG and iiNet SIM-only pages (JSON-LD and offer terms)", "url": BRANDS["tpg"]["url"], "fetched": captured}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print("tpg_mobile: " + ", ".join(f"{sum(r['provider'] == p for r in mobile)} {p}" for p in BRANDS))


if __name__ == "__main__":
    main()

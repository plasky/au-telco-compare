"""Moose Mobile (provider id "moose-mobile"): postpaid SIM plans from the plan feed its own site
loads (WordPress + ACF REST API, Vodafone network).

https://moosemobile.com.au/wp-json/acf/v3/cpq-mobile-plan is the JSON the site's plan picker
(theme script build/index.js, "cpq-mobile-plan") fetches to draw the plan cards; the home page
itself has no plan markup. robots.txt allows everything with "Crawl-delay: 10"; the adapter
makes this one request. Each item's `acf` has:
  - name ("Mobile 250GB"), price (monthly, incl. GST), allowance (GB per month), description;
  - promotion {code, type: "price", description: "$10 Off for 6 Months", duration: "6",
    price: "40"} for the current new-service discount;
  - service_features ("Utilises the Vodafone 4G & 5G networks" / "... 4G network",
    "Unlimited standard talk and text in Aus") and service_documents.cis (the CIS PDF).

Notes on the content:
  - Plans are month-to-month postpaid (the CIS: "post-paid mobile services", minimum term one
    month, no early termination fee), so period_days is 30 and contract 0.
  - The CIS lists international calls and SMS as excluded (charged at international rates), so
    intl is [] unless a plan's features mention international calls.
  - The CIS also says excess data is charged at $9/GB (not slowed) and speeds are capped at
    150 Mbps; that is kept in notes as a fixed fact from the CIS of 1 Oct 2026.
  - The feed carries no promo end date. The offer terms PDF (Mobile Discount Offer Terms,
    19 Nov 2026) says the offer runs 25 Nov 2026 to 31 Mar 2027 for new services; promo.until
    is left None rather than copied from a PDF the adapter doesn't read.
"""
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

URL = "https://moosemobile.com.au/wp-json/acf/v3/cpq-mobile-plan"
PAGE = "https://moosemobile.com.au/"
PID = "moose-mobile"
STEM = pathlib.Path(__file__).stem
CIS_NOTES = "Excess data is charged at $9/GB; speeds capped at 150 Mbps (CIS)."


def main():
    items = json.loads(fetch(URL, RAW / STEM / "cpq-mobile-plan.json", min_interval=10.0))
    captured = now_iso()
    mobile, skipped = [], []
    for it in items if isinstance(items, list) else []:
        a = it.get("acf") or {}
        name = (a.get("name") or "").strip()
        try:
            price = float(a["price"])
            data = float(a["allowance"])
        except (KeyError, TypeError, ValueError):
            skipped.append(f"{name or it.get('id')}: no price or allowance")
            continue
        feats = " ".join(f.get("description") or "" for f in a.get("service_features") or [])
        text = f"{a.get('description') or ''} {feats}".lower()
        promo, notes = None, []
        p = a.get("promotion") or {}
        if p.get("type") == "price" and p.get("price") and p.get("duration"):
            pp, months = float(p["price"]), int(float(p["duration"]))
            if pp < price:
                promo = {"price": pp, "periods": months, "until": None,
                         "text": f"{p.get('description') or ''} (code {p.get('code')})".strip()}
                notes.append("Discount is for new services.")
        if p.get("allowance"):
            notes.append(f"Current offer: {p.get('description') or 'bonus data'} ({p['allowance']}).")
        notes.append(CIS_NOTES)
        intl = None if "international" in text else []
        mobile.append({
            "id": f"{PID}-{slug(re.sub(r'^(moose\s+)?mobile\s+', '', name, flags=re.I)) or slug(name)}", "provider": PID, "name": name, "network": "vodafone",
            "type": "postpaid", "period_days": 30, "price": price, "data_gb": data, "data_only": False,
            "calls": "unlimited" if re.search(r"unlimited standard (national )?(talk|calls)", text) else "limited",
            "five_g": "5g" in text, "intl": intl, "promo": promo, "contract": 0, "rollover": None,
            "credit": None, "url": PAGE, "cis_url": (a.get("service_documents") or {}).get("cis"),
            "source": STEM, "captured": captured, "verified": True, "notes": " ".join(notes),
        })
    for s in skipped:
        print(f"{STEM}: skipped {s}", file=sys.stderr)
    if not mobile:
        raise RuntimeError("Moose Mobile plan feed parsed to zero plans; feed may have moved or changed")
    meta = {"name": "Moose Mobile plan feed (WordPress ACF REST)", "url": URL, "fetched": captured,
            "skipped": skipped}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"{STEM}: {len(mobile)} mobile")


if __name__ == "__main__":
    main()

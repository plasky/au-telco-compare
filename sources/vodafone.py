"""Vodafone: nbn and 5G Home Internet plans from the __NEXT_DATA__ JSON on Vodafone's own pages.

https://www.vodafone.com.au/home-internet/nbn and https://www.vodafone.com.au/home-internet/4g-5g-plans
are Next.js pages; pageProps.plansResponseNbn / plansResponse5g .planListing.plans list every plan
with recurringCharge (the ongoing price), typical evening speeds, the CIS link and a promotions list
(amount off, end date, display-only flag). robots.txt allows both pages; it disallows /cis/ and
/documents/, so the CIS links are recorded but never fetched.

Notes on the content:
  - discountedRecurringCharge includes the $10/mth mobile bundle saving, so it is not used as the
    intro price. The intro price is recurringCharge minus the time-limited promotions
    ("Save $20/mth for 12 months"); the bundle saving goes in `bundle`.
  - The "$0 modem over 24/36 months" promotion is display-only and gives the modem's maximum cost.
  - Interim (pre-fibre-upgrade), trial and existing-customer plans are skipped.
  - "nbn Home Fast" (nbn 100) is sold on FTTB/N/C only, as the page's terms state; techs follow.
  - Promo end dates are UTC instants at local midnight; the AEST date is reported.
"""
import html
import json
import re
import sys
import pathlib
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "vodafone"
PAGES = {
    "nbn": ("https://www.vodafone.com.au/home-internet/nbn", "plansResponseNbn"),
    "5g": ("https://www.vodafone.com.au/home-internet/4g-5g-plans", "plansResponse5g"),
}
AEST = timezone(timedelta(hours=10))
COPPER = ["fttc", "fttn", "fttb"]


def text(s):
    s = html.unescape(html.unescape(s or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def next_data(page):
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError("vodafone: __NEXT_DATA__ not found")
    return json.loads(m.group(1))["props"]["pageProps"]


def local_date(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(AEST).date().isoformat()


def speeds(p):
    for inc in p.get("inclusions") or []:
        m = re.search(r"(\d+(?:\.\d+)?)\s*Mbps download and (\d+(?:\.\d+)?)\s*Mbps upload", text(inc.get("title")))
        if m:
            return float(m.group(1)), float(m.group(2))
    d = p.get("connectionSpeed")
    return (float(d) if d else None), None


def record(p, kind, url, tncs, captured):
    name = text(p.get("planName")).strip()
    down, up = speeds(p)
    price = float(p["recurringCharge"])
    off, months, until, ptext, bundle, modem, modem_months = 0.0, None, None, [], [], None, None
    for pr in p.get("promotions") or []:
        title, desc = text(pr.get("title")), text(pr.get("description"))
        if pr.get("isDisplayOnly"):
            m = re.search(r"(?i)max(?:imum)? (?:modem )?cost \$(\d+(?:\.\d+)?)(?: \(modem\))?", desc)
            mm = re.search(r"(?i)over (\d+) months|for (\d+) months", title + " " + desc)
            if re.search(r"(?i)modem", title) and m:
                modem = float(m.group(1))
                modem_months = int(next(g for g in mm.groups() if g)) if mm else None
            continue
        adj = pr.get("adjustmentValue")
        if not adj:
            continue
        if re.search(r"(?i)bundle|mobile plan with us", title + " " + desc):
            bundle.append({"with": "mobile", "off": float(adj), "text": title, "during_promo": True})
            continue
        m = re.search(r"(?i)for (\d+) months", title) or re.search(r"(?i)for (?:the first )?(\d+) months", desc)
        if m:
            off += float(adj)
            months = max(months or 0, int(m.group(1)))
            # endDate is only a last sign-up date when the offer has one; "until withdrawn" offers
            # carry an internal end date that isn't published.
            end = None if re.search(r"(?i)until withdrawn", desc) else local_date(pr.get("endDate"))
            until = min(filter(None, [until, end]), default=None)
            ptext.append(f"{title}. {desc}")
    promo = None
    if off and months and price - off > 0:
        promo = {"price": round(price - off, 2), "months": months, "until": until, "text": " ".join(ptext)}

    if kind == "nbn":
        tier = tier_from(name, down)
        techs = techs_for("nbn", tier)
        if re.search(re.escape(name) + r" plan is only available in nbn FTTB/N/C", tncs):
            techs = [t for t in techs if t in COPPER]
    else:
        tier, techs = None, []

    notes = []
    if promo:
        notes.append("Promo for new connections (select areas); forfeited if you cancel early.")
    if modem:
        notes.append(f"Vodafone modem $0 if you stay {modem_months} months, else the rest of ${modem:g}"
                     + ("; BYO modem allowed." if kind == "nbn" else "; modem required."))
    tenure = (p.get("planTenure") or "").lower()
    contract = 0 if "month to month" in tenure or (p.get("contractTerm") or 1) <= 1 else int(p["contractTerm"])
    return {
        "id": f"{PID}-{slug(re.sub(r'nbn®?', 'nbn', name).replace('+', ' plus'))}", "provider": PID, "name": name.replace("nbn®", "nbn"),
        "kind": kind, "tier": tier, "techs": techs, "down": down, "up": up, "price": price, "promo": promo,
        "setup": None, "contract": contract,
        "modem": {"offer": "included_contract", "cost": modem} if modem else {"offer": "unknown", "cost": None},
        "data_gb": None,   # all current plans are unlimited (planData "Unlimited")
        "network": "vodafone" if kind == "5g" else None, "credit": None, "bundle": bundle,
        "url": url, "cis_url": p.get("cisUrl") or None, "source": PID, "captured": captured,
        "verified": True, "notes": " ".join(notes) or None,
    }


def main():
    internet, captured = [], now_iso()
    for kind, (url, key) in PAGES.items():
        pp = next_data(fetch(url, RAW / PID / f"{kind}.html").decode("utf-8", "replace"))
        tncs = text(json.dumps(pp.get("pageDataNbn") or {}, ensure_ascii=False))
        plans = ((pp.get(key) or {}).get("planListing") or {}).get("plans") or []
        recs = [record(p, kind, url, tncs, captured) for p in plans
                if not (p.get("isInterimPlan") or p.get("isTrialPlan") or p.get("isExistingCustomer"))]
        recs = [r for r in recs if r["down"] and r["price"]]
        if not recs:
            raise RuntimeError(f"vodafone {kind}: no plans parsed from {url}; page layout may have changed")
        internet += recs
    ids = [r["id"] for r in internet]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"vodafone: duplicate record ids {ids}")
    internet.sort(key=lambda r: (r["kind"], r["tier"] or 0, r["price"]))
    meta = {"name": "Vodafone home internet pages (__NEXT_DATA__)", "url": PAGES["nbn"][0], "fetched": captured}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"vodafone: {sum(r['kind'] == 'nbn' for r in internet)} nbn, {sum(r['kind'] == '5g' for r in internet)} 5g")


if __name__ == "__main__":
    main()

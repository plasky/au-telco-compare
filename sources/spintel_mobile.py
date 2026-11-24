"""Spintel: SIM-only mobile plans (Optus network), its nbn-bundle SIM plans and its data-only
mobile internet SIM, from its own pages.

https://www.spintel.net.au/home-mobile/plans          voice SIM plans (required)
https://www.spintel.net.au/home-internet/nbn          nbn page; its mobile add-on block lists the
                                                      bundle-only SIM plans ($3/month off)
https://www.spintel.net.au/home-internet/mobile-internet   data-only SIM plans
robots.txt disallows only /static, /filemanager and /api/v1/tracker/. CIS PDFs under /static
are linked to, never fetched.

All three are Inertia.js pages: <div id="app" data-page="..."> holds the page props as JSON.
Plan blocks (type "plans", package_type "Mobile" or "Mobile Broadband") list each plan with
priceEach, included_data (GB), description (feature list HTML), cis_pdf_url and the promo fields
promo_valid / promo_credit / promo_credit_type (recurring_months | recurring_indefinite) /
promo_credit_months / promo_message ("$8/MONTH OFF FOR 6 MONTHS").

Bundle: the nbn page offers "Mobile 25GB Bundle" and "Mobile 50GB Bundle" (own plan ids and
CIS) with "$3/MONTH OFF" for as long as the plan is held (recurring_indefinite, code
3off_bundle). They are sold only alongside a Spintel nbn service, so they are emitted as their
own records with bundle off = $3 and a note. The schema has no record-level "needs internet"
flag, so their base price is shown as if available on its own.
Data-only: mobile broadband plans are kept only when a SIM-only option is offered for them
(the hardware block's "SIM Only" item lists their plan id); the Unlimited plan needs a rented
modem and is skipped.
International calls: plans include a dollar allowance ("$50 International calls"), not calls
to listed countries, so intl is None and the allowance goes in notes.
"""
import html
import json
import re
import sys
import pathlib
from urllib.parse import urljoin

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

BASE = "https://www.spintel.net.au"
MOBILE_URL = BASE + "/home-mobile/plans"
NBN_URL = BASE + "/home-internet/nbn"
MBB_URL = BASE + "/home-internet/mobile-internet"
PID = "spintel"
SRC = pathlib.Path(__file__).stem


def page_props(page):
    m = re.search(r'data-page="([^"]*)"', page)
    if not m:
        raise RuntimeError("spintel mobile: no Inertia data-page attribute")
    return json.loads(html.unescape(m.group(1)))["props"]


def blocks(props, btype):
    return [b.get("data") or {} for b in props.get("initialBlocks") or [] if b.get("type") == btype]


def features(desc):
    return [t.strip() for t in re.split(r"<[^>]+>", html.unescape(desc or "")) if t.strip()]


def num(v):
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(v)) if v is not None else None
    return float(m.group(1)) if m else None


def record(p, url, captured, data_only=False, bundle_only=False):
    price, data = num(p.get("priceEach")), num(p.get("included_data"))
    if price is None or not data:
        return None
    feats = features(p.get("description"))
    ftxt = " | ".join(feats).lower()
    name = (p.get("special_label") or p.get("title") or "").strip()
    if bundle_only and "bundle" not in name.lower():
        name += " Bundle"
    notes, promo, bundle = [], None, []
    if p.get("promo_valid") and num(p.get("promo_credit")):
        credit = num(p["promo_credit"])
        if p.get("promo_credit_type") == "recurring_indefinite":
            bundle = [{"with": "internet", "off": credit,
                       "text": f"{p.get('promo_message') or f'${credit:g}/month off'} with a Spintel nbn service"}]
        elif p.get("promo_credit_type") == "recurring_months" and int(p.get("promo_credit_months") or 0) > 0 \
                and credit < price:
            months = int(p["promo_credit_months"])
            promo = {"price": round(price - credit, 2), "periods": months, "until": None,
                     "text": p.get("promo_message") or f"${credit:g}/month off for {months} months"}
            notes.append("Promo for new customers.")
        else:
            notes.append(f"Current offer: {p.get('promo_message')}")
    if bundle_only:
        notes.append("Sold only with a Spintel nbn service (offered at nbn checkout).")
    im = re.search(r"\$(\d+) international calls", ftxt)
    if im:
        notes.append(f"Includes ${im.group(1)} of international calls.")
    sm = re.search(r"(\d+) sms", ftxt)
    if sm:
        notes.append(f"{sm.group(1)} SMS included.")
    cap = re.search(r"5g at max\s+(\d+) ?mbps", ftxt)
    if cap:
        notes.append(f"5G speeds capped at {cap.group(1)} Mbps.")
    if "data pauses" in ftxt:
        notes.append("Data pauses at the allowance; extra data blocks can be bought.")
    calls = "none" if data_only else "unlimited" if "unlimited calls" in ftxt else "unknown"
    cis = p.get("cis_pdf_url")
    return {
        "id": f"{PID}-mobile-{slug(name).removeprefix('mobile-')}", "provider": PID, "name": name, "network": "optus",
        "type": "postpaid", "period_days": 30, "price": price, "data_gb": data, "data_only": data_only,
        "calls": calls, "five_g": "5g" in ftxt, "intl": None, "promo": promo, "contract": 0,
        "rollover": None, "bundle": bundle, "credit": None, "url": url, "requires": "internet" if bundle_only else None,
        "cis_url": urljoin(BASE, cis) if cis else None, "source": SRC, "captured": captured,
        "verified": True, "notes": " ".join(notes) or None,
    }


def mobile_blocks(props, package):
    return [b for b in blocks(props, "plans") if (b.get("package_type") or "").lower() == package]


def main():
    captured = now_iso()
    props = page_props(fetch(MOBILE_URL, RAW / SRC / "plans.html", min_interval=2.0).decode("utf-8"))
    if not re.search(r"Optus", json.dumps(props)):
        print("warning: the mobile page no longer mentions the Optus network", file=sys.stderr)
    mobile, ids, plan_ids = [], set(), set()

    def add(r, plan_id):
        if r and r["id"] not in ids:
            ids.add(r["id"])
            plan_ids.add(plan_id)
            mobile.append(r)

    for b in mobile_blocks(props, "mobile"):
        for p in b.get("plans") or []:
            add(record(p, MOBILE_URL, captured), p.get("planId"))
    if not mobile:
        raise RuntimeError("spintel mobile: no Mobile plan block on /home-mobile/plans")

    # nbn page: bundle-only SIM plans (optional).
    try:
        nprops = page_props(fetch(NBN_URL, RAW / SRC / "nbn.html", min_interval=2.0).decode("utf-8"))
        for b in mobile_blocks(nprops, "mobile"):
            for p in b.get("plans") or []:
                if p.get("planId") in plan_ids:
                    continue
                if p.get("promo_credit_type") == "recurring_indefinite" or "bundle" in (p.get("title") or "").lower():
                    add(record(p, NBN_URL, captured, bundle_only=True), p.get("planId"))
    except Exception as e:  # noqa: BLE001
        print(f"warning: nbn page bundle SIMs skipped: {e}", file=sys.stderr)

    # Mobile internet page: data-only SIMs that can be bought SIM-only (optional).
    try:
        mprops = page_props(fetch(MBB_URL, RAW / SRC / "mobile-internet.html", min_interval=2.0).decode("utf-8"))
        sim_only = set()
        for h in blocks(mprops, "hardwares"):
            for hw in h.get("hardwares") or []:
                if re.search(r"sim only", f"{hw.get('title')} {hw.get('description')}", re.I) and not num(hw.get("price")):
                    sim_only |= {str(i) for i in hw.get("assigned_plan_ids") or []}
        for b in mobile_blocks(mprops, "mobile broadband"):
            for p in b.get("plans") or []:
                if str(p.get("planId")) not in sim_only:
                    continue
                r = record(p, MBB_URL, captured, data_only=True)
                if r:
                    r["notes"] = " ".join(x for x in [r["notes"], "4G only; extra data $10/GB."] if x)
                add(r, p.get("planId"))
    except Exception as e:  # noqa: BLE001
        print(f"warning: mobile internet page skipped: {e}", file=sys.stderr)

    meta = {"name": "Spintel mobile, nbn and mobile internet pages", "url": MOBILE_URL,
            "urls": [MOBILE_URL, NBN_URL, MBB_URL], "fetched": captured}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile ({sum(1 for r in mobile if r['promo'])} with promo, "
          f"{sum(1 for r in mobile if r['bundle'])} bundle-only)")


if __name__ == "__main__":
    main()

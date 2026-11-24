"""Felix Mobile (TPG Telecom, Vodafone network): SIM-only plans from the Contentful data in the home page.

https://felixmobile.com.au/ is a Next.js page; its __NEXT_DATA__ JSON carries the "Plan Summary
Carousel" module with one entry per plan: planName ("25GB", "Unlimited+"), planPrice (ongoing),
discountedPrice and copyUnderDiscountedPrice ("for 3 months"), the promo code, the plan page link and
the feature items (data banking, speed caps, what happens after the allowance). The module's terms
(rich text) give each offer's end date ("... Then $40/mth. Ends 30/11/26."). robots.txt allows the
page (it disallows only /icons/). One request per run. www.felixmobile.com.au redirects to the
bare domain, which is used directly.

Notes on the content:
  - Unlimited plans are unlimited at a capped speed (40 or 80Mbps), so data_gb = -1 with the cap
    in the notes. 25GB/50GB plans slow to 1.5Mbps after the allowance and any banked data.
  - The page doesn't name the host network; it comes from providers.toml (mvno_of).
  - Plans are paid monthly in advance and auto-renew; there are no recharges, so they are typed
    "postpaid" (a monthly plan), as Bill Hero does.
  - No international calls are included (they are app add-ons), so intl = [].
"""
import json
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, load_providers, now_iso, slug, write_norm  # noqa: E402

PID = "felix-mobile"
STEM = "felix_mobile"
URL = "https://felixmobile.com.au/"
CIS = "https://felixmobile.com.au/terms-policies/critical-information-summaries"


def rich(node):
    """Plain text of a Contentful rich-text document."""
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("nodeType") == "text":
                out.append(n.get("value", ""))
            for c in n.get("content") or []:
                walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)
    walk(node)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def entries(o, found):
    """(plan fields, terms text of the enclosing module) for every plan entry in the page data."""
    if isinstance(o, dict):
        f = o.get("fields") if isinstance(o.get("fields"), dict) else None
        if f and isinstance(f.get("individualPlans"), list):
            terms = rich(f.get("tsAndCs"))
            for p in f["individualPlans"]:
                pf = (p or {}).get("fields") or {}
                if pf.get("planName") and pf.get("planPrice"):
                    found.append((pf, terms))
        for v in o.values():
            entries(v, found)
    elif isinstance(o, list):
        for v in o:
            entries(v, found)
    return found


def dollars(v):
    return f"${v:.2f}".replace(".00", "")


def end_date(t):
    m = re.search(r"(?i)ends (\d{1,2})/(\d{1,2})/(\d{2,4})", t)
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    return date(y + 2000 if y < 100 else y, mo, d).isoformat()


def record(f, terms, network, captured):
    name = f["planName"].strip()
    price = float(f["planPrice"])
    feats = []
    for it in f.get("items") or []:
        g = (it or {}).get("fields") or {}
        feats.append((g.get("header") or g.get("name") or "", rich(g.get("lightboxContent"))))
    alltext = " ".join(h + " " + d for h, d in feats)
    m = re.search(r"(\d+(?:\.\d+)?)\s*GB", name)
    data = float(m.group(1)) if m else -1 if re.search(r"(?i)unlimited", name) else None

    promo, notes = None, []
    disc = f.get("discountedPrice")
    pm = re.search(r"(?i)for (\d+) months?", f.get("copyUnderDiscountedPrice") or "")
    if disc and float(disc) < price and pm:
        months, code = int(pm.group(1)), (f.get("promoCodeForThisPlan") or "").strip()
        sentences = re.split(r"(?<=\.)\s+(?=[A-Z])", terms)
        # "<plan> ...: 50% off 6 months is avail. to new + eligible customers. Then $40/mth. Ends 30/11/26."
        idx = next((i for i, s in enumerate(sentences) if f"Then ${price:g}/mth" in s), None)
        mine = sentences[max(idx - 1, 0):idx + 2] if idx is not None else []
        until = end_date(" ".join(sentences[idx:idx + 2])) if idx is not None else None
        if idx is None and re.search(rf"Offers on [^.]*\b{re.escape(name)}\b[^.]*until withdrawn", terms):
            mine = [s for s in sentences if "until withdrawn" in s and name in s]
        promo = {"price": float(disc), "periods": months, "until": until,
                 "text": f"{dollars(float(disc))}/month for {months} months, then {dollars(price)}"
                         + (f" (promo code {code})" if code else "") + ". " + " ".join(mine)}
        notes.append(f"Intro price needs promo code {code}; new and eligible customers." if code else
                     "Intro price for new and eligible customers.")

    cap = re.search(r"(?i)speeds (?:are capped at|up to) (\d+)\s*Mbps", alltext)
    if cap:
        notes.append(f"Speed capped at {cap.group(1)}Mbps.")
    if re.search(r"(?i)slow to 1\.5\s*Mbps", alltext):
        notes.append("After the allowance and any banked data, speed slows to 1.5Mbps (no excess charges).")
        if re.search(r"(?i)extra 10GB available for \$10", terms):
            notes.append("Extra 10GB for $10.")
    if re.search(r"(?i)data bank", alltext):
        notes.append("Unused data is banked with no limit.")
    notes.append("Paid monthly in advance and auto-renews; no lock-in. International calls are add-ons.")
    return {
        "id": f"{PID}-{slug(name.replace('+', ' plus'))}", "provider": PID, "name": name,
        "network": network, "type": "postpaid", "period_days": 30, "price": price, "data_gb": data,
        "data_only": False,
        "calls": "unlimited" if re.search(r"(?i)unlimited std talk", alltext) else "unknown",
        "five_g": bool(re.search(r"5G", alltext)), "intl": [], "promo": promo, "contract": 0,
        "rollover": True if re.search(r"(?i)data bank", alltext) else None, "bundle": [], "credit": None,
        "url": f.get("linkUrl") or URL, "cis_url": CIS, "source": STEM, "captured": captured,
        "verified": True, "notes": " ".join(notes),
    }


def main():
    page = fetch(URL, RAW / STEM / "home.html", min_interval=2.0, retries=2).decode("utf-8", "replace")
    captured = now_iso()
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError("felix_mobile: __NEXT_DATA__ not found")
    network = load_providers().get(PID, {}).get("mvno_of")
    seen = {}
    for f, terms in entries(json.loads(m.group(1)), []):
        seen.setdefault(f["planName"].strip(), (f, terms))
    mobile = [record(f, t, network, captured) for f, t in seen.values()]
    mobile = [r for r in mobile if r["price"] and r["data_gb"] is not None]
    if not mobile:
        raise RuntimeError("felix_mobile: no plans parsed from the home page data; layout may have changed")
    ids = [r["id"] for r in mobile]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"felix_mobile: duplicate record ids {sorted(ids)}")
    meta = {"name": "Felix Mobile home page plan carousel (__NEXT_DATA__)", "url": URL, "fetched": captured}
    write_norm(STEM, {"internet": [], "mobile": mobile}, meta)
    print(f"felix_mobile: {len(mobile)} plans")


if __name__ == "__main__":
    main()

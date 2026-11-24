"""More (more.com.au, provider id "more-telecom"): plan cards on its server-rendered nbn page.

https://www.more.com.au/personal/nbn-plans has one `<div class="p-2 h-100" id="<product guid>">`
card per plan: name (`<p class="fs-4 fw-bold">Fast Max</p>`), monthly price split across spans
("$" "105" ".00" "/mth"), "Typical Evening Speed (7-11pm)" figures ("500Mbps" Download,
"42.5Mbps" Upload), a feature list (Free Standard Connection, No Lock-in Contracts) and
"Special Offers". The card's add-to-cart button has data-product-type="speed" and
data-product-price (the same monthly price). Routers are buttons with data-product-type="modem"
(outright price; the NetComm NF71 is currently $0, was $198). robots.txt allows everything.

Notes on the content:
  - The site shares its back end with Tangerine (same product GUIDs and cart code) but not its
    page template, so it has its own adapter.
  - Current offers are CommBank-only (a $100 bill credit, or $25/mth off for 3 years plus a $0
    router via ConnectID). They are kept in notes, not as promo/credit, since most users can't
    get them.
  - Mobile broadband is a data-only SIM product (mobile phase), not 5G home internet.
"""
import html
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "more-telecom"
SRC = "more"
URL = "https://www.more.com.au/personal/nbn-plans"
CIS_FALLBACK = "https://www.more.com.au/ResidentialNBNCIS"


def text(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s):
    m = re.search(r"\$\s*(\d+)\s*(?:\.\s*(\d+))?", s or "")
    return float(f"{m.group(1)}.{m.group(2) or 0}") if m else None


def cheapest_modem(page):
    """Cheapest router you can buy outright (BYO excluded), or None."""
    best = None
    for m in re.finditer(r"<button\b[^>]*>", page):
        a = dict(re.findall(r'data-([\w-]+)="([^"]*)"', m.group(0)))
        if a.get("product-type") != "modem" or "byo" in a.get("product-name", "").lower():
            continue
        try:
            price = float(a.get("product-price", ""))
        except ValueError:
            continue
        best = price if best is None else min(best, price)
    return best


def main():
    page = fetch(URL, RAW / SRC / "nbn-plans.html").decode("utf-8")
    captured = now_iso()
    mc = cheapest_modem(page)
    modem = {"offer": "purchase", "cost": mc} if mc is not None else {"offer": "unknown", "cost": None}

    # Cards are wrapped in <div class="p-2 h-100" id="<guid>">; keep those with a speed button.
    starts = list(re.finditer(r'<div class="p-2 h-100" id="([0-9a-f-]{36})">', page))
    internet, skipped, seen = [], [], set()
    for i, m in enumerate(starts):
        seg = page[m.start():starts[i + 1].start() if i + 1 < len(starts) else m.start() + 30000]
        btn = re.search(r'<button\b[^>]*data-product-type="speed"[^>]*>', seg)
        if not btn:
            continue
        a = dict(re.findall(r'data-([\w-]+)="([^"]*)"', btn.group(0)))
        nm = re.search(r'<p class="fs-4 fw-bold">(.*?)</p>', seg, re.S)
        name = text(nm.group(1)) if nm else html.unescape(a.get("product-name", "")).replace("®", "").strip()
        price_html = re.search(r'<span class="fs-2 align-top">\$</span>(.*?)/mth', seg, re.S)
        shown = money("$" + text(price_html.group(1)).replace(" ", "")) if price_html else None
        try:
            listed = float(a.get("product-price", ""))
        except ValueError:
            listed = None
        price = shown or listed
        if not price:
            skipped.append(f"{name} (no price)")
            continue
        body = text(seg)
        dm = re.search(r"(\d+(?:\.\d+)?)\s*Mbps\s*Download", body)
        um = re.search(r"(\d+(?:\.\d+)?)\s*Mbps\s*Upload", body)
        down, up = (float(dm.group(1)) if dm else None), (float(um.group(1)) if um else None)

        promo = None
        was = re.search(r'(?:line-through|<del|<s\b)[^>]*>(.*?)</', seg, re.S)
        was = money(text(was.group(1))) if was else None
        if was and was > price:
            months = re.search(r"for (?:the first )?(\d+) months?", body, re.I)
            if months and 1 <= int(months.group(1)) <= 24:
                promo = {"price": price, "months": int(months.group(1)), "until": None,
                         "text": f"${price:g}/mth for {months.group(1)} months, then ${was:g}"}
                price = was
        notes = []
        offers = re.search(r"Special Offers\s*(.*?)(?:Check Address|Choose this plan|Critical Information Summary|$)", body)
        if offers and offers.group(1).strip():
            notes.append("Offer: " + offers.group(1).strip().rstrip(" .") + ".")
        tier = tier_from(name, down)
        if not tier:
            skipped.append(f"{name} (no tier)")
            continue
        cis = re.search(r'href="([^"]*ResidentialNBNCIS[^"]*)"', seg, re.I)
        rid = f"{PID}-{slug(name)}"
        if rid in seen:
            continue
        seen.add(rid)
        internet.append({
            "id": rid, "provider": PID, "name": name, "kind": "nbn", "tier": tier,
            "techs": techs_for("nbn", tier), "down": down, "up": up, "price": price, "promo": promo,
            "setup": 0.0 if re.search(r"Free Standard Connection", body, re.I) else None,
            "contract": 0 if re.search(r"No Lock-in Contract", body, re.I) else 1,
            "modem": dict(modem), "data_gb": None, "network": None, "credit": None, "bundle": [],
            "url": URL, "cis_url": cis.group(1) if cis else CIS_FALLBACK, "source": SRC,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })

    if not internet:
        raise RuntimeError("more: nbn page parsed to zero plans; page layout may have changed")
    meta = {"name": "More nbn plans page", "url": URL, "fetched": captured, "skipped": skipped}
    write_norm(SRC, {"internet": internet, "mobile": []}, meta)
    print(f"more: {len(internet)} internet (skipped: {', '.join(skipped) or 'none'})")


if __name__ == "__main__":
    main()

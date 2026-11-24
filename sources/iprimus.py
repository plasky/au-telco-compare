"""iPrimus: plan tiles and plan modals on its server-rendered nbn plans page (Drupal), plus the
HTML Critical Information Summary for the setup fee.

https://www.iprimus.com.au/nbn-plans has one `<div tiq-data="object:plan,variant:NAME" ...
plan_tile ...>` per plan in its carousel, each with the monthly price, a discount slot
(`plan_tile__price--discount`, hidden and "0" when there is no offer), connection-type spans
(`<span class="fttp">FTTP</span>`) and "500Mbps download & 50Mbps upload typical evening speeds".
Each plan also has a "learn more" modal and a terms modal (minimum cost, free-modem terms).
Some nbn plans (currently nbn Standard) appear only as modals; they are included from the modal.
https://www.iprimus.com.au/critical-information-summary/nbn-internet-plans-cis has the plan table
with "Set-up Fee $0". robots.txt allows both pages.

Notes on the content:
  - "Fixed Wireless ..." plans are skipped (fixed-line nbn only), as are "Fibre ..." plans, which
    run on Vocus's own (non-nbn) fibre networks in particular estates.
  - The modem is included and free if you stay 18 months ($180 paid off by a $10/mth credit;
    the balance is due if you leave earlier): modem offer "included_contract", cost 180.
  - The mobile-internet bundle offer is a discount on the mobile plan with no amount stated on
    these pages, so `bundle` stays empty. iPrimus has no 5G home internet.
  - nbn Standard's modal gives no typical speeds; its tier comes from iPrimus's plan naming.
"""
import html
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "iprimus"
BASE = "https://www.iprimus.com.au"
URL = BASE + "/nbn-plans"
CIS_URL = BASE + "/critical-information-summary/nbn-internet-plans-cis"
TECHS = {"fttp", "hfc", "fttc", "fttn", "fttb"}
# iPrimus plan names -> nbn tier, used only when a plan publishes no speed.
NAME_TIER = {"standard": 25, "standard plus": 50, "premium": 100, "premium plus": 500,
             "home superfast": 750, "home ultrafast": 1000}


def text(s):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def money(s):
    m = re.search(r"\$\s*(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else None


def base_name(name):
    return re.sub(r"^nbn®?\s*", "", name, flags=re.I).strip().lower()


def parse_tile(seg):
    name = text(re.search(r'plan_tile__heading[^>]*>(.*?)</p>', seg, re.S).group(1))
    price = re.search(r'plan_tile__price display[^>]*>(.*?)</div>', seg, re.S)
    disc = re.search(r'plan_tile__price--discount[^>]*?(style="[^"]*")?>(.*?)</div>', seg, re.S)
    techs = re.search(r'plan_tile__tech--type"?[^>]*>(.*?)</div>', seg, re.S)
    techs = [t for t in re.findall(r'<span class="(\w+)">', techs.group(1)) if t in TECHS] if techs else []
    sp = re.search(r'plan_tile__content__speed__text[^>]*>(.*?)</p>', seg, re.S)
    sp = text(sp.group(1)) if sp else ""
    dm = re.search(r"(\d+(?:\.\d+)?)\s*Mbps download", sp)
    um = re.search(r"(\d+(?:\.\d+)?)\s*Mbps upload", sp)
    pid = re.search(r"planId=(\w+)", seg)
    return {
        "name": name, "price": money(text(price.group(1))) if price else None,
        "discount": None if not disc or "hidden" in (disc.group(1) or "") else text(disc.group(2)),
        "techs": techs, "down": float(dm.group(1)) if dm else None, "up": float(um.group(1)) if um else None,
        "plan_id": pid.group(1) if pid else None,
    }


def terms_for(page, seg):
    """(title, text) items of the terms modal a tile or modal points at."""
    m = re.search(r'#(modal-terms-\d+)"', seg)
    if not m:
        return []
    a = page.find(f'id="{m.group(1)}"')
    if a < 0:
        return []
    b = page.find('<div class="modal fade"', a)
    body = page[a:b if b > 0 else len(page)]
    return [(text(k), text(v)) for k, v in re.findall(
        r'plan_modal__terms__content__title">(.*?)</div>\s*<p class="plan_modal__terms__content__desc">(.*?)</p>', body, re.S)]


def main():
    page = fetch(URL, RAW / PID / "nbn-plans.html").decode("utf-8")
    captured = now_iso()
    cis = fetch(CIS_URL, RAW / PID / "nbn-cis.html").decode("utf-8")
    cis_text = text(cis)
    sm = re.search(r"Set-up Fee\s*\$\s*(\d+(?:\.\d+)?)", cis_text)
    setup = float(sm.group(1)) if sm else None
    mm = re.search(r"total modem cost \$(\d+(?:\.\d+)?) over (\d+) months", text(page), re.I)
    modem = {"offer": "included_contract", "cost": float(mm.group(1))} if mm else {"offer": "unknown", "cost": None}
    modem_note = (f"Modem included; ${mm.group(1)} balance (less $10 per month connected) is payable "
                  f"if you cancel within {mm.group(2)} months.") if mm else None

    plans = []
    modal_starts = [m.start() for m in re.finditer(r'<div class="modal fade"', page)] + [len(page)]
    tile_starts = [m.start() for m in re.finditer(r'<div tiq-data="object:plan,variant:', page)]
    for i, a in enumerate(tile_starts):
        b = min([tile_starts[i + 1] if i + 1 < len(tile_starts) else len(page)] + [x for x in modal_starts if x > a])
        plans.append(dict(parse_tile(page[a:b]), where="tile", terms=terms_for(page, page[a:b])))
    # Plans that appear only as "learn more" modals.
    have = {base_name(p["name"]) for p in plans}
    for m in re.finditer(r'<div class="modal fade" id="modal-learn-more-(\d+)"[^>]*>', page):
        seg = page[m.start():min(x for x in modal_starts if x > m.start())]
        p = parse_tile(seg)
        if base_name(p["name"]) not in have:
            have.add(base_name(p["name"]))
            plans.append(dict(p, where="modal", terms=terms_for(page, f'#modal-terms-{m.group(1)}"')))

    internet, skipped = [], []
    for p in plans:
        name, bn = p["name"], base_name(p["name"])
        if re.match(r"(fixed wireless|fibre)\b", name, re.I) or not re.match(r"nbn", name, re.I):
            skipped.append(name)
            continue
        if not p["price"]:
            skipped.append(f"{name} (no price)")
            continue
        tier = tier_from(name, p["down"]) or NAME_TIER.get(bn)
        if not tier:
            skipped.append(f"{name} (no tier)")
            continue
        techs = techs_for("nbn", tier)
        if p["techs"]:
            techs = [t for t in techs if t in p["techs"]] or techs
        price, promo = p["price"], None
        notes = [modem_note] if modem_note else []
        was = money(p["discount"]) if p["discount"] else None
        if was and was > price:
            # A visible discount slot holds the struck-out ongoing price; the offer's length is in
            # the plan's terms modal ("... Discount Offer: $X off for N months ...").
            offer = next((v for k, v in p["terms"] if "discount" in k.lower()), "")
            months = re.search(r"for (\d+) months?", offer, re.I)
            if months:
                promo = {"price": price, "months": int(months.group(1)), "until": None, "text": offer[:300]}
            else:
                notes.append(f"Intro price ${price:g} shown; offer length not stated.")
            price = was
        if p["where"] == "modal":
            notes.append("Listed in plan details and the CIS but not in the main plan carousel.")
        internet.append({
            "id": f"{PID}-{slug(bn)}", "provider": PID, "name": name, "kind": "nbn", "tier": tier,
            "techs": techs, "down": p["down"], "up": p["up"], "price": price, "promo": promo,
            "setup": setup, "contract": 0, "modem": dict(modem), "data_gb": None, "network": None,
            "credit": None, "bundle": [], "url": URL, "cis_url": CIS_URL, "source": PID,
            "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })

    if not internet:
        raise RuntimeError("iprimus: nbn plans page parsed to zero plans; page layout may have changed")
    meta = {"name": "iPrimus nbn plans page and CIS", "url": URL, "cis": CIS_URL, "fetched": captured,
            "skipped": skipped}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    print(f"iprimus: {len(internet)} internet (skipped: {', '.join(skipped) or 'none'})")


if __name__ == "__main__":
    main()

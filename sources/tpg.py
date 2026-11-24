"""TPG: nbn, nbn Fixed Wireless, TPG Fibre (own FTTB network) and 5G Home Broadband plans.

https://www.tpg.com.au/nbn embeds TPG's whole home-internet catalogue as JSON in an AngularJS
attribute, ng-init='setVars({"plans": {"FTTN": {...}, "FTTC": ..., "Fibre": ..., "HFC": ...,
"FTTB": ..., "Wireless": ...}})'. Each plan entry has the ongoing monthly charge, a promotion
object ({"six_month_price": 49.99, ...} or {"twentyfour_month_price": ...}), and typical evening
speeds. robots.txt allows the page. One request covers every plan.

Notes on the content:
  - A plan appears under each nbn technology it is sold on (and again as a "Fibre Connect" variant
    for fibre-upgrade orders); records are grouped by speed label and price, and techs are the
    union of the plans' own `tech` fields, within common.techs_for.
  - tech "FTTBW" is TPG Fibre on TPG's own Vision Network FTTB (not nbn FTTB): kind "private".
  - tech "HomeWireless4G" (4G Home Wireless Broadband) has no kind in the schema and is skipped.
  - The 5G entries carry no network field; TPG 5G runs on TPG Telecom's own mobile network,
    which is the Vodafone network.
  - Fees, modem terms and the mobile bundle saving come from the page's footnote text.
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

PID = "tpg"
URL = "https://www.tpg.com.au/nbn"
URLS = {"nbn": URL, "fixed_wireless": URL, "5g": "https://www.tpg.com.au/5g-home-broadband",
        "private": "https://www.tpg.com.au/fttb"}
CIS = "https://www.tpg.com.au/terms_conditions/CIS"
TECH = {"FTTN": ("nbn", "fttn"), "FTTC": ("nbn", "fttc"), "FTTB": ("nbn", "fttb"),
        "Fibre": ("nbn", "fttp"), "HFC": ("nbn", "hfc"), "Wireless": ("fixed_wireless", "fw"),
        "FTTBW": ("private", None), "HomeBroadband5G": ("5g", None)}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "six": 6, "nine": 9, "twelve": 12,
           "eighteen": 18, "twentyfour": 24}


def page_text(page):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s)


def catalogue(page):
    m = re.search(r"ng-init='setVars\((\{.*?\})\)'", page, re.S)
    if not m:
        raise RuntimeError("tpg: setVars plan catalogue not found on the nbn page")
    return json.loads(html.unescape(m.group(1)))


def mbps(s):
    m = re.search(r"(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else None


def promotion(p):
    promo = p.get("promotion") or {}
    for k, v in promo.items():
        m = re.fullmatch(r"([a-z]+)_month_price", k)
        if m and isinstance(v, (int, float)) and m.group(1) in NUMBERS:
            msg = promo.get(f"{m.group(1)}_month_promo_message") or ""
            return float(v), NUMBERS[m.group(1)], msg.strip()
    return None


def fees(text):
    """Setup, modem and bundle terms from the footnotes (None where the wording isn't found)."""
    f = {}
    m = re.search(r"First month.s plan fee \+ \$(\d+(?:\.\d+)?) delivery fee", text)
    f["nbn_setup"] = float(m.group(1)) if m else None
    m = re.search(r"delivery fee on a no lock-in contract\. Modem is \$0 when you stay connected for (\d+) months\. "
                  r"If you cancel\s*early, the modem is \$(\d+)", text)
    f["nbn_modem"] = (int(m.group(1)), float(m.group(2))) if m else None
    m = re.search(r"5G Home Broadband Plan for \d+ months\.[^$]{0,60}Modem is \$0 when you stay connected for (\d+) months\. "
                  r"If you cancel\s*early, the modem is \$(\d+)", text)
    f["5g_modem"] = (int(m.group(1)), float(m.group(2))) if m else None
    f["fttb_setup"] = 0.0 if re.search(r"FTTB\d*:? Promotional .{0,200}Total min charge = First month.s plan fee\.", text) else None
    m = re.search(r"save \$(\d+(?:\.\d+)?)/mth on mobile fees from month (\d+)", text)
    f["bundle"] = [{"with": "mobile", "off": float(m.group(1)),
                    "text": f"${m.group(1)}/mth off an eligible TPG Medium or Large SIM-only mobile plan from month {m.group(2)}"}] if m else []
    return f


def main():
    page = fetch(URL, RAW / PID / "nbn.html").decode("utf-8", "replace")
    captured = now_iso()
    cat, f = catalogue(page), fees(page_text(page))

    groups = {}
    plans = {p["name"]: p for tech in cat["plans"].values() for p in tech.get("plans", [])}
    for p in plans.values():
        if p.get("tech") not in TECH:
            continue
        kind, tech = TECH[p["tech"]]
        d = p.get("display") or {}
        label = (d.get("speed_label") or "").strip()
        down, up = mbps(d.get("speed")), mbps(d.get("upload"))
        key = (kind, label, p.get("charge"), down, up, promotion(p))
        g = groups.setdefault(key, {"plan": p, "techs": set(), "names": []})
        if tech:
            g["techs"].add(tech)
        g["names"].append(p["name"])

    internet = []
    for (kind, label, charge, down, up, promo), g in groups.items():
        price = float(charge)
        name = label if kind != "fixed_wireless" else f"{label} Fixed Wireless"
        if kind == "5g" and not name.upper().startswith("5G"):
            name = f"5G {name}"
        if kind in ("nbn", "fixed_wireless"):
            tier = tier_from(label, down)
            techs = [t for t in techs_for(kind, tier) if kind != "nbn" or t in g["techs"]]
        else:
            tier, techs = None, []
        pr = None
        if promo and promo[0] < price:
            pr = {"price": promo[0], "months": promo[1], "until": None, "text": promo[2] or None}

        notes = []
        if kind in ("nbn", "fixed_wireless"):
            setup = f["nbn_setup"]
            months, cost = f["nbn_modem"] or (None, None)
            modem = {"offer": "included_contract", "cost": cost} if months else {"offer": "unknown", "cost": None}
            if pr:
                notes.append(f"Promo for new connections only; forfeited if you change or cancel in the first {pr['months']} months.")
            if months:
                notes.append(f"TPG modem $0 if you stay {months} months or return it (else ${cost:g}); "
                             f"${setup:g} modem delivery; BYO modem allowed with no delivery fee." if setup else
                             f"TPG modem $0 if you stay {months} months or return it (else ${cost:g}).")
        elif kind == "5g":
            setup = None
            months, cost = f["5g_modem"] or (None, None)
            modem = {"offer": "included_contract", "cost": cost} if months else {"offer": "unknown", "cost": None}
            notes.append("Promo for new connections only." if pr else "")
            if months:
                notes.append(f"TPG 5G modem required; $0 if you stay {months} months or return it (else ${cost:g}).")
        else:   # TPG Fibre on the Vision Network
            setup = f["fttb_setup"]
            modem = {"offer": "included", "cost": None}
            notes.append("TPG Fibre (TPG's own FTTB network): only in buildings TPG's network serves.")
            if pr:
                notes.append(f"{pr['months']}-month discount for new customers at newly connected premises only.")
            if (g["plan"].get("rule") or []) and "Gfast" in " ".join(g["plan"]["rule"]):
                notes.append("Only at G.fast-enabled buildings.")
            notes.append("$0 refurbished modem provided; return it if you cancel.")

        internet.append({
            "id": f"{PID}-{slug(name)}", "provider": PID, "name": name, "kind": kind, "tier": tier,
            "techs": techs, "down": down, "up": up, "price": price, "promo": pr, "setup": setup,
            "contract": 0, "modem": modem, "data_gb": None,
            "network": "vodafone" if kind == "5g" else None, "credit": None, "bundle": list(f["bundle"]),
            "url": URLS[kind], "cis_url": CIS, "source": PID, "captured": captured, "verified": True,
            "notes": " ".join(n for n in notes if n) or None,
        })

    internet.sort(key=lambda r: (r["kind"], r["tier"] or 0, r["price"]))
    if not any(r["kind"] == "nbn" for r in internet):
        raise RuntimeError("tpg: no nbn plans parsed from the setVars catalogue; page layout may have changed")
    ids = [r["id"] for r in internet]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"tpg: duplicate record ids {sorted(ids)}")
    meta = {"name": "TPG nbn plan catalogue (setVars JSON on the nbn page)", "url": URL, "fetched": captured}
    write_norm(PID, {"internet": internet, "mobile": []}, meta)
    counts = {}
    for r in internet:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    print("tpg: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))


if __name__ == "__main__":
    main()

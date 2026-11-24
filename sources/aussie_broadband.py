"""Aussie Broadband: residential nbn plans from its own plans page.

https://www.aussiebroadband.com.au/internet/nbn-plans/ (robots.txt allows everything except
/tools/fibre-operations/; wrapper.aussiebroadband.com.au allows everything).

Sources on that page, in order of trust:
  1. JSON-LD ProductGroup "nbn plans": one Product per plan with the ongoing price
     (offers.price), the eligible connection types (material) and the typical evening speed
     in the description ("Typical evening speed is 23/9 Mbps"). This is required; the adapter
     fails if it is missing or empty.
  2. The site's plan catalogue, a JavaScript module (/_nuxt/internet-<hash>.js, linked from the
     page) holding the same plans with their promo terms
     (promo:{discount:`$30`,discountedPrice:53,code:`BF30`,duration:6}) and the CIS links.
     The page itself only renders the "Popular" plan cards, so this is the only place the
     promos for the other plans appear. Used for promos and CIS links only, and only where
     its price agrees with the JSON-LD.
  3. The rendered "Popular" plan cards ("$53 /month first 6 months* Save $30/month with code
     BF30* $83/month after promo period."): promo fallback when the module can't be read.

Other facts from the page: promo end date from the offer disclaimer ("Ends 21/12/2026"),
no standard connection fee (FAQ), no lock-in contracts, modems sold optionally (cheapest
"Starting From (+ min. $15 shipping) $216 /upfront") or bring your own.
Fixed Wireless plans are in the same feeds but skipped here (fixed-line NBN only); ABB has no
5G home internet. The mobile bundle saving ($5/month) applies to the SIM, not the internet plan.
"""
import html
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

BASE = "https://www.aussiebroadband.com.au"
URL = BASE + "/internet/nbn-plans/"
PID = "aussie-broadband"
SRC = pathlib.Path(__file__).stem
OUT = RAW / SRC


def ld_blocks(page):
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            yield json.loads(m.group(1))
        except ValueError:
            continue


def visible_text(page):
    body = page[page.find("<body"):]
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def balanced(s, i):
    """The {...} starting at s[i] == "{", skipping backtick strings."""
    depth, j, tick = 0, i, False
    while j < len(s):
        c = s[j]
        if c == "`":
            tick = not tick
        elif not tick and c == "{":
            depth += 1
        elif not tick and c == "}":
            depth -= 1
            if depth == 0:
                return s[i:j + 1]
        j += 1
    return s[i:]


def jsnum(v):
    return float(v) if v is not None else None


def catalogue_plans(js):
    """Plan objects from the catalogue module: {id:`nbn25d10u`,mbpsDown:25,...}."""
    plans = []
    for m in re.finditer(r"\{id:`([^`]+)`,mbpsDown:", js):
        obj = balanced(js, m.start())
        pm = re.search(r"promo:\{", obj)
        promo_src = balanced(obj, pm.end() - 1) if pm else "{}"
        rest = obj.replace(promo_src, "{}", 1)
        g = lambda pat, src=rest: (re.search(pat, src) or [None, None])[1]  # noqa: E731
        plans.append({
            "id": m.group(1), "down": jsnum(g(r"mbpsDown:([\d.e]+)")), "up": jsnum(g(r"mbpsUp:([\d.e]+)")),
            "price": jsnum(g(r"[,{]price:([\d.e]+)")), "name": g(r",name:`([^`]*)`"),
            "promo": {"discount": g(r"discount:`([^`]*)`", promo_src),
                      "price": jsnum(g(r"discountedPrice:([\d.e]+)", promo_src)),
                      "months": int(g(r"duration:(\d+)", promo_src) or 0),
                      "code": g(r"code:`([^`]*)`", promo_src)},
        })
    return plans


def card_promos(text):
    """Fallback: promos on the rendered Popular cards, keyed by ("25/10", ongoing price)."""
    out = {}
    pat = (r"(\d+/\d+) \$(\d+(?:\.\d+)?) /month first (\d+) months?\*? "
           r"Save \$(\d+(?:\.\d+)?)/month with code (\w+)\*? \$(\d+(?:\.\d+)?)/month after promo period")
    for m in re.finditer(pat, text):
        out[(m.group(1), float(m.group(6)))] = {
            "price": float(m.group(2)), "months": int(m.group(3)), "discount": f"${m.group(4)}",
            "code": m.group(5)}
    return out


def main():
    page = fetch(URL, OUT / "nbn-plans.html").decode("utf-8")
    captured = now_iso()
    text = visible_text(page)

    variants, faq = [], ""
    for d in ld_blocks(page):
        if d.get("@type") == "ProductGroup" and "nbn" in (d.get("productGroupID") or d.get("name") or "").lower():
            variants += d.get("hasVariant") or []
        if d.get("@type") == "FAQPage":
            faq = json.dumps(d)
    if not variants:
        raise RuntimeError("aussie broadband: no JSON-LD nbn ProductGroup on the plans page")

    # Plan catalogue module(s), for promos and CIS links. Optional.
    catalogue, cis, chunks = [], {}, sorted(set(re.findall(r"/_nuxt/internet-[\w-]+\.js", page)))
    for path in chunks:
        try:
            js = fetch(BASE + path, OUT / pathlib.Path(path).name).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"warning: could not fetch {path}: {e}", file=sys.stderr)
            continue
        catalogue += [p for p in catalogue_plans(js) if p["id"].startswith("nbn")]
        for k, u in re.findall(r'"cis-resi-nbn-(lower|higher)":\{label:`[^`]*`,href:`([^`]+)`', js):
            cis.setdefault(k, u)
    by_key = {(p["name"].strip().lower(), p["down"], p["up"]): p for p in catalogue if p["name"]}
    cards = card_promos(text)
    if not by_key:
        print("warning: plan catalogue module not found or empty; promos from Popular cards only", file=sys.stderr)

    m = re.search(r"New customers and eligible existing upgrading customers only\..{0,200}?"
                  r"Ends (\d{1,2})/(\d{1,2})/(\d{4})", text)
    until = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None
    setup = 0.0 if re.search(r"don.t charge standard connection fees", faq + text, re.I) else None
    hw = [(float(p), float(s)) for s, p in re.findall(
        r"Starting From \(\+ min\. \$(\d+(?:\.\d+)?) shipping\) \$(\d+(?:\.\d+)?) /upfront", text)]
    modem = {"offer": "purchase", "cost": min(p + s for p, s in hw)} if hw else {"offer": "unknown", "cost": None}

    internet = []
    for v in variants:
        full = v.get("name", "")
        short = full.split(" - ")[0].strip()
        size = v.get("size") or (re.search(r"(\d+/\d+)", full) or [None, None])[1]
        material = [t.lower() for t in (v.get("material") or [])]
        if not size or material == ["fw"] or "fixed wireless" in short.lower():
            continue
        nom_down, nom_up = (float(x) for x in size.split("/"))
        sm = re.search(r"Typical evening speed is (\d+(?:\.\d+)?)/(\d+(?:\.\d+)?) ?Mbps", v.get("description", ""))
        down, up = (float(sm.group(1)), float(sm.group(2))) if sm else (None, None)
        price = float(v["offers"]["price"])
        tier = tier_from(f"nbn {size}", down)
        techs = techs_for("nbn", tier)
        if material:
            pub = set(material) | ({"fttb"} if "fttn" in material else set())
            techs = [t for t in techs if t in pub] or techs

        promo, notes = None, None
        cat = by_key.get((short.lower(), nom_down, nom_up))
        if cat and cat["price"] is not None and abs(cat["price"] - price) > 0.005:
            print(f"warning: {short} {size}: catalogue price {cat['price']} != JSON-LD {price}; promo skipped",
                  file=sys.stderr)
            cat = None
        p = cat["promo"] if cat else None
        if p is None:
            p = cards.get((size, price))
        if p and p.get("price") and p.get("months") and p["price"] < price:
            code = f" with code {p['code']}" if p.get("code") else ""
            promo = {"price": p["price"], "months": p["months"], "until": until,
                     "text": f"Save {p.get('discount') or '$' + format(price - p['price'], 'g')}/month for the "
                             f"first {p['months']} months{code}"}
            notes = (f"Promo needs code {p['code']}; " if p.get("code") else "") + \
                "new customers and eligible existing upgrading customers only."

        internet.append({
            "id": f"{PID}-{slug(short)}-{size.replace('/', '-')}", "provider": PID, "name": f"{short} {size}",
            "kind": "nbn", "tier": tier, "techs": techs, "down": down, "up": up, "price": price,
            "promo": promo, "setup": setup, "contract": 0, "modem": dict(modem), "data_gb": None,
            "network": None, "credit": None, "bundle": [], "url": (v.get("offers") or {}).get("url") or URL,
            "cis_url": cis.get("higher" if nom_down > 100 else "lower"), "source": SRC,
            "captured": captured, "verified": True, "notes": notes,
        })
    if not internet:
        raise RuntimeError("aussie broadband: JSON-LD parsed to zero fixed-line plans")
    meta = {"name": "Aussie Broadband nbn plans page", "url": URL, "fetched": captured,
            "catalogue": chunks, "promo_until": until}
    write_norm(SRC, {"internet": internet, "mobile": []}, meta)
    print(f"{SRC}: {len(internet)} internet ({sum(1 for r in internet if r['promo'])} with promo)")


if __name__ == "__main__":
    main()

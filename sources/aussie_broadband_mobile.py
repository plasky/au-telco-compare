"""Aussie Broadband: 5G SIM-only and data-only mobile plans (Optus network) from its own site.

Pages (robots.txt allows everything except /tools/fibre-operations/):
  https://www.aussiebroadband.com.au/mobile/sim-only-plans/   voice SIM plans
  https://www.aussiebroadband.com.au/mobile/data-only-sim/    data-only SIM plans

Sources, in order of trust:
  1. The site's mobile plan catalogue, a JavaScript module (/_nuxt/mobile-<hash>.js, linked from
     the SIM page) holding every plan as an object literal:
       {id:`sim5g45`,ref:`...`,data:45,price:40,popular:!0,maxSpeed:150,
        promo:{discount:`50%`,discountedPrice:20,code:`BF50`,duration:6,...},name:`Value`,...,
        features:[...,t.INTERNATIONAL_CALL(50),...]}
     Data-only plans carry dataOnly:!0. This is required; the adapter fails without it.
  2. The rendered SIM and data-only pages: CIS links (one per page), the promo end date
     ("Ends 21/12/2026 11:59PM AEDT") and the bundle saving ("you'll save $5/month per plan").

Bundle: $5/month off each mobile service (voice or data-only, up to five per account) when the
account also has an nbn or Opticomm plan. It does not stack with mobile promo codes; it starts
when the promo ends (https://www.aussiebroadband.com.au/bundles/). That matches the schema's
default (bundle applies after the intro offer), so during_promo is not set.
International calls: plans include a dollar IDD credit rather than calls to listed countries,
so intl is None and the credit goes in notes. Plans are billed monthly with no lock-in.
"""
import html
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, now_iso, slug, write_norm  # noqa: E402

BASE = "https://www.aussiebroadband.com.au"
SIM_URL = BASE + "/mobile/sim-only-plans/"
DATA_URL = BASE + "/mobile/data-only-sim/"
PID = "aussie-broadband"
SRC = pathlib.Path(__file__).stem
OUT = RAW / SRC


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


def catalogue_plans(js):
    """Plan objects from the mobile module: {id:`sim5g20`,ref:`...`,data:20,price:30,...}."""
    plans = []
    for m in re.finditer(r"\{id:`([^`]+)`,ref:`[^`]*`,data:", js):
        obj = balanced(js, m.start())
        pm = re.search(r"promo:\{", obj)
        promo_src = balanced(obj, pm.end() - 1) if pm else "{}"
        rest = obj.replace(promo_src, "{}", 1)
        g = lambda pat, src=rest: (re.search(pat, src) or [None, None])[1]  # noqa: E731
        price, data = g(r"[,{]price:([\d.]+)"), g(r"[,{]data:([\d.]+)")
        if price is None or data is None:
            continue
        plans.append({
            "id": m.group(1), "name": g(r",name:`([^`]*)`"), "data": float(data), "price": float(price),
            "data_only": bool(re.search(r"dataOnly:(!0|true)", rest)),
            "max_speed": g(r"maxSpeed:(\d+|`[^`]*`)"),
            "idd": g(r"INTERNATIONAL_CALL\((\d+)\)"),
            "promo": {"discount": g(r"discount:`([^`]*)`", promo_src),
                      "price": float(g(r"discountedPrice:([\d.]+)", promo_src) or 0) or None,
                      "periods": int(g(r"duration:(\d+)", promo_src) or 0),
                      "code": g(r"code:`([^`]*)`", promo_src)},
        })
    return plans


def cis_link(page):
    for u, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        if "critical information summary" in re.sub(r"<[^>]+>", "", label).lower() and u.startswith("http"):
            return html.unescape(u)
    return None


def promo_until(text):
    m = re.search(r"New customers and eligible existing upgrading customers only\..{0,200}?"
                  r"Ends (\d{1,2})/(\d{1,2})/(\d{4})", text)
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def main():
    sim_page = fetch(SIM_URL, OUT / "sim-only-plans.html", min_interval=2.0).decode("utf-8")
    captured = now_iso()
    sim_text = visible_text(sim_page)

    modules = sorted(set(re.findall(r"/_nuxt/mobile-[\w-]+\.js", sim_page)))
    if not modules:
        raise RuntimeError("aussie broadband mobile: no /_nuxt/mobile-*.js module linked from the SIM page")
    plans = []
    for path in modules:
        js = fetch(BASE + path, OUT / pathlib.Path(path).name, min_interval=2.0).decode("utf-8")
        plans += catalogue_plans(js)
    if not plans:
        raise RuntimeError("aussie broadband mobile: plan module parsed to zero plans; layout may have changed")

    data_page, data_text = "", ""
    if any(p["data_only"] for p in plans):
        try:
            data_page = fetch(DATA_URL, OUT / "data-only-sim.html", min_interval=2.0).decode("utf-8")
            data_text = visible_text(data_page)
        except Exception as e:  # noqa: BLE001
            print(f"warning: could not fetch {DATA_URL}: {e}", file=sys.stderr)

    until = promo_until(sim_text) or promo_until(data_text)
    bm = re.search(r"save \$(\d+(?:\.\d+)?)/month per plan", sim_text, re.I)
    bundle_off = float(bm.group(1)) if bm else None
    if bundle_off is None:
        print("warning: bundle saving text not found on the SIM page; no bundle emitted", file=sys.stderr)
    cis = {False: cis_link(sim_page), True: cis_link(data_page) if data_page else None}

    mobile, seen = [], set()
    for p in plans:
        if p["id"] in seen or not p["name"]:
            continue
        seen.add(p["id"])
        gb = int(p["data"]) if p["data"] == int(p["data"]) else p["data"]
        label = f"{p['name']} {gb}GB" + (" Data-only" if p["data_only"] else "")
        text = data_text if p["data_only"] else sim_text
        if text and f"{p['name']} {gb}gb".lower() not in text.lower():
            print(f"warning: {label} is in the plan module but not on the rendered page", file=sys.stderr)

        promo, notes = None, []
        pr = p["promo"]
        if pr["price"] and pr["periods"] and pr["price"] < p["price"]:
            code = f" with code {pr['code']}" if pr.get("code") else ""
            promo = {"price": pr["price"], "periods": pr["periods"], "until": until,
                     "text": f"Save {pr['discount'] or '$' + format(p['price'] - pr['price'], 'g')} for the "
                             f"first {pr['periods']} months{code}"}
            notes.append((f"Promo needs code {pr['code']}; " if pr.get("code") else "")
                         + "new customers and eligible existing upgrading customers only.")
        bundle = []
        if bundle_off:
            bundle = [{"with": "internet", "off": bundle_off,
                       "text": f"${bundle_off:g}/month off with an Aussie Broadband nbn or Opticomm plan "
                               "(up to 5 SIMs per account; starts after any mobile promo ends)"}]
        speed = p["max_speed"].strip("`") if p["max_speed"] else None
        if speed and speed.isdigit():
            notes.append(f"5G speeds capped at {speed} Mbps.")
        if p["idd"]:
            notes.append(f"Includes ${p['idd']} international call credit; PAYG after.")
        if not p["data_only"]:
            notes.append("Data pools across 5G services on the same account.")

        mobile.append({
            "id": f"{PID}-mobile-{'data-' if p['data_only'] else ''}{slug(p['name'])}-{gb}gb",
            "provider": PID, "name": label, "network": "optus", "type": "postpaid", "period_days": 30,
            "price": p["price"], "data_gb": p["data"], "data_only": p["data_only"],
            "calls": "none" if p["data_only"] else "unlimited", "five_g": True, "intl": None,
            "promo": promo, "contract": 0, "rollover": None, "bundle": bundle, "credit": None,
            "url": DATA_URL if p["data_only"] else SIM_URL, "cis_url": cis[p["data_only"]],
            "source": SRC, "captured": captured, "verified": True, "notes": " ".join(notes) or None,
        })
    if not mobile:
        raise RuntimeError("aussie broadband mobile: parsed to zero plans")
    meta = {"name": "Aussie Broadband mobile SIM and data-only plans", "url": SIM_URL, "fetched": captured,
            "catalogue": modules, "promo_until": until, "bundle_off": bundle_off}
    write_norm(SRC, {"internet": [], "mobile": mobile}, meta)
    print(f"{SRC}: {len(mobile)} mobile ({sum(1 for r in mobile if r['promo'])} with promo)")


if __name__ == "__main__":
    main()

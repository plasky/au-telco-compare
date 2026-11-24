"""Bill Hero open data feeds (CC-BY-4.0): the NBN and mobile backbone.

Attribution required on the site: "Data via Bill Hero (billhero.com.au)".
Known quirks handled here:
  - speed_down_mbps is usually the typical evening speed (740 on a 750 plan, 820/850 on 1000),
    so the nominal tier is inferred from the plan name or rounded up to the next tier;
  - some prices look like promo or bundle prices (e.g. amaysim at $30), so every record is
    marked verified=False and is replaced wholesale by a provider adapter when one exists;
  - mobile monthly_price_aud is normalised to a 30-day month; the real recharge price and
    period are reconstructed from the plan name where possible;
  - junk is dropped: $0 prices, missing speeds, roaming packs, duplicate rows.
"""
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, fetch, load_providers, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

BASE = "https://billhero.com.au/data/"
MODEM = {"free_with_contract": "included_contract", "free_with_contract_includes_mesh": "included_contract",
         "free_unconditional": "included", "optional_purchase": "purchase", "byo_required": "byo", None: "unknown"}


def internet_kind(pid, name, registry):
    n = name.lower()
    if "fixed wireless" in n:
        return "fixed_wireless"
    if "sky muster" in n or "satellite" in n:
        return "satellite"
    if registry.get(pid, {}).get("own_network") or (pid == "tpg" and "fttb" in n):
        return "private"   # TPG's FTTB plans run on TPG's own building fibre, not the NBN
    return "nbn"


def norm_internet(rows, registry, captured_default):
    out, dropped = [], []
    for p in rows:
        pid, name = p["carrier"], p["plan_name"].strip()
        price, down = p.get("monthly_price_aud"), p.get("speed_down_mbps")
        if not price or not down:
            dropped.append(f"{pid}: {name} (no price or speed)")
            continue
        kind = internet_kind(pid, name, registry)
        tier = tier_from(name, down) if kind == "nbn" else None
        modem_offer = MODEM.get(p.get("modem_offer"), "unknown")
        if modem_offer == "unknown" and p.get("modem_included"):
            modem_offer = "included"
        out.append({
            "id": f"{pid}-{slug(name)}", "provider": pid, "name": name, "kind": kind, "tier": tier,
            "techs": techs_for(kind, tier), "down": float(down),
            "up": float(p["speed_up_mbps"]) if p.get("speed_up_mbps") else None,
            "price": float(price), "promo": None, "setup": float(p.get("setup_fee") or 0),
            "contract": int(p.get("contract_term") or 0),
            "modem": {"offer": modem_offer, "cost": None}, "data_gb": None, "bundle": [],
            "url": None, "cis_url": p.get("cis_url"), "source": "billhero",
            "captured": p.get("source_captured_at") or captured_default, "verified": False,
        })
    return out, dropped


PERIOD_RE = [(r"(\d+)\s*-?\s*days?", lambda m: int(m.group(1))),
             (r"(\d+)\s*-?\s*months?", lambda m: {1: 30, 3: 91, 6: 183, 12: 365}.get(int(m.group(1)), int(m.group(1)) * 30)),
             (r"\b(12[- ]month|annual|yearly|1 year|first year)\b", lambda m: 365)]


def norm_mobile(rows, registry, captured_default):
    out, dropped = [], []
    for p in rows:
        pid, name = p["carrier"], p["plan_name"].strip()
        n = name.lower()
        monthly = p.get("monthly_price_aud")
        if not monthly or re.search(r"roaming|travel pack|add-?on|top-?up", n):
            dropped.append(f"{pid}: {name} (no price, or an add-on/roaming pack)")
            continue
        period = None
        for rx, f in PERIOD_RE:
            m = re.search(rx, n)
            if m:
                period = f(m)
                break
        if p.get("plan_type") == "postpaid" and period is None:
            period = 30
        if period is None:
            period = 30 if p.get("plan_type") != "prepaid" else 28 if "28" in n else 30
        # Price per period: the dollar figure in the name if it agrees with the feed's
        # 30-day-normalised price, otherwise reconstruct it from that price.
        price = round(monthly * period / 30, 2)
        if period != 30 and abs(price - round(price)) < 0.1:
            price = float(round(price))     # undo the feed's rounding (179.94 -> 180)
        m = re.search(r"\$(\d+(?:\.\d+)?)", name)
        if m and abs(float(m.group(1)) * 30 / period - monthly) / monthly < 0.03:
            price = float(m.group(1))
        data_only = p.get("plan_type") == "sim_only" or "data only" in n or "data plan" in n and "unlimited" not in n
        calls_txt = (p.get("calls_included") or "").lower()
        calls = "none" if data_only else "unlimited" if "unlimited" in calls_txt or "included" in calls_txt else "unknown"
        net = p.get("host_network")
        out.append({
            "id": f"{pid}-{slug(name)}", "provider": pid, "name": name,
            "network": net if net in ("telstra", "optus", "vodafone") else registry.get(pid, {}).get("mvno_of"),
            "type": "postpaid" if p.get("plan_type") == "postpaid" else "prepaid",
            "period_days": int(period), "price": price,
            "data_gb": float(p["data_gb"]) if p.get("data_gb") is not None else None,
            "data_only": bool(data_only), "calls": calls, "five_g": p.get("five_g"),
            "intl": p.get("intl_included_countries") or None, "promo": None,
            "contract": int(p.get("contract_term") or 0), "url": None, "source": "billhero",
            "captured": p.get("source_captured_at") or captured_default, "verified": False,
        })
    return out, dropped


def dedupe(recs):
    """Drop exact repeats (same provider, name, price, period/speed); suffix clashing ids."""
    seen, ids, out = set(), {}, []
    for r in recs:
        key = (r["provider"], r["name"], r["price"], r.get("period_days"), r.get("down"), r.get("data_gb"))
        if key in seen:
            continue
        seen.add(key)
        if r["id"] in ids:
            ids[r["id"]] += 1
            r["id"] = f"{r['id']}-{ids[r['id']]}"
        else:
            ids[r["id"]] = 1
        out.append(r)
    return out


def main():
    registry = load_providers()
    raw = {}
    for feed in ("broadband", "mobile"):
        raw[feed] = json.loads(fetch(BASE + feed, RAW / "billhero" / f"{feed}.json"))
    meta_b, meta_m = raw["broadband"]["_meta"], raw["mobile"]["_meta"]
    internet, d1 = norm_internet(raw["broadband"]["plans"], registry, meta_b.get("generated_at") or now_iso())
    mobile, d2 = norm_mobile(raw["mobile"]["plans"], registry, meta_m.get("generated_at") or now_iso())
    internet, mobile = dedupe(internet), dedupe(mobile)
    meta = {"name": "Bill Hero open data", "url": "https://billhero.com.au/data", "fetched": now_iso(),
            "generated": meta_b.get("generated_at"), "licence": meta_b.get("license"),
            "attribution": meta_b.get("attribution"), "dropped": d1 + d2,
            "raw_counts": {"internet": len(raw["broadband"]["plans"]), "mobile": len(raw["mobile"]["plans"])}}
    write_norm("billhero", {"internet": internet, "mobile": mobile}, meta)
    print(f"billhero: {len(internet)} internet, {len(mobile)} mobile ({len(d1) + len(d2)} dropped)")


if __name__ == "__main__":
    main()

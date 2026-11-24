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

Since 25 Nov 2026 Bill Hero puts a Cloudflare challenge in front of its feeds for automated
clients (GitHub's servers and our own machines alike). We don't work around that. Instead the
adapter falls back to a snapshot committed to snapshots/billhero/ when the live fetch fails, if
the snapshot is under SNAPSHOT_MAX_DAYS old; otherwise it fails and the build's fail-safe keeps
the last published records. Snapshots come from:
  --save-snapshot                 fetch the live feeds (works only where Bill Hero allows it)
  --import-snapshot FILE [FILE]   feeds a person downloaded in a browser from
                                  https://billhero.com.au/data/broadband and /data/mobile
The feeds are CC-BY-4.0, so redistributing them in the repo is allowed with attribution.

Usage: python3 -I sources/billhero.py [--save-snapshot | --import-snapshot FILE [FILE]]
"""
from datetime import datetime, timedelta, timezone
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from common import RAW, ROOT, fetch, load_providers, now_iso, slug, techs_for, tier_from, write_norm  # noqa: E402

BASE = "https://billhero.com.au/data/"
FEEDS = ("broadband", "mobile")
SNAPSHOT = ROOT / "snapshots" / "billhero"
SNAPSHOT_MAX_DAYS = 8     # long enough for a weekly manual download
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
            # Long-expiry recharges named only by price ("Prepaid Plus $180"): the feed divides
            # the price into 30-day months, so a name price ~12x, ~6x or ~3x the monthly figure
            # means a 365-, 180- or 90-day recharge. (The feed's data figure is the whole period's.)
            dm = re.search(r"\$(\d+(?:\.\d+)?)", name)
            if dm and monthly:
                ratio = float(dm.group(1)) / monthly
                for days in (365, 180, 90):
                    if abs(ratio - days / 30) / (days / 30) < 0.04:
                        period = days
                        break
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


def fetch_live():
    raw = {}
    for feed in FEEDS:
        raw[feed] = json.loads(fetch(BASE + feed, RAW / "billhero" / f"{feed}.json"))
        if not raw[feed].get("plans"):
            raise RuntimeError(f"Bill Hero {feed} feed has no plans")
    return raw


def write_snapshot(raw, fetched, how):
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    for feed in FEEDS:
        (SNAPSHOT / f"{feed}.json").write_text(json.dumps(raw[feed], ensure_ascii=False, separators=(",", ":")) + "\n")
    info = {"fetched": fetched, "how": how, "generated": raw["broadband"]["_meta"].get("generated_at"),
            "plans": {f: len(raw[f]["plans"]) for f in FEEDS},
            "attribution": raw["broadband"]["_meta"].get("attribution"), "licence": raw["broadband"]["_meta"].get("license")}
    (SNAPSHOT / "snapshot.json").write_text(json.dumps(info, indent=1) + "\n")
    print(f"billhero snapshot ({how}, {fetched}): {info['plans']['broadband']} broadband, {info['plans']['mobile']} mobile plans")


def save_snapshot():
    """Fetch the live feeds and store them in snapshots/billhero/."""
    write_snapshot(fetch_live(), now_iso(), "fetched")


def import_snapshot(paths):
    """Store feeds downloaded in a browser, after checking they are Bill Hero's feeds. Each file
    is identified by its plans' fields; its generated_at time becomes the snapshot time."""
    raw = {}
    for path in paths:
        d = json.loads(pathlib.Path(path).expanduser().read_text())
        plans, m = d.get("plans") or [], d.get("_meta") or {}
        if m.get("license") != "CC-BY-4.0" or len(plans) < 50:
            raise SystemExit(f"{path}: doesn't look like a Bill Hero feed (licence {m.get('license')}, {len(plans)} plans)")
        feed = "broadband" if "speed_down_mbps" in plans[0] else "mobile" if "data_gb" in plans[0] else None
        if not feed:
            raise SystemExit(f"{path}: can't tell whether this is the broadband or mobile feed")
        raw[feed] = d
    missing = [f for f in FEEDS if f not in raw]
    if missing:
        raise SystemExit(f"missing the {', '.join(missing)} feed")
    gen = sorted(raw[f]["_meta"].get("generated_at") or "" for f in FEEDS)[0]
    fetched = gen[:19] + "Z" if gen else now_iso()
    write_snapshot(raw, fetched, "imported")


def load_feeds():
    """Live feeds, or the committed snapshot if the live fetch fails and the snapshot is fresh.
    Returns (raw feeds, fetched time, how)."""
    try:
        return fetch_live(), now_iso(), "live"
    except Exception as e:
        info_file = SNAPSHOT / "snapshot.json"
        if not info_file.exists():
            raise RuntimeError(f"live fetch failed ({e}) and there is no snapshot") from e
        info = json.loads(info_file.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(info["fetched"].replace("Z", "+00:00"))
        if age > timedelta(days=SNAPSHOT_MAX_DAYS):
            raise RuntimeError(f"live fetch failed ({e}) and the snapshot is {age.days} days old "
                               f"(fetched {info['fetched']}); run tools/mac/billhero-snapshot.sh") from e
        print(f"billhero: live fetch failed ({type(e).__name__}); using the snapshot fetched {info['fetched']}")
        return {f: json.loads((SNAPSHOT / f"{f}.json").read_text()) for f in FEEDS}, info["fetched"], "snapshot"


def main():
    args = sys.argv[1:]
    if "--save-snapshot" in args:
        save_snapshot()
        return
    if "--import-snapshot" in args:
        import_snapshot(args[args.index("--import-snapshot") + 1:])
        return
    registry = load_providers()
    raw, fetched, how = load_feeds()
    meta_b, meta_m = raw["broadband"]["_meta"], raw["mobile"]["_meta"]
    internet, d1 = norm_internet(raw["broadband"]["plans"], registry, meta_b.get("generated_at") or now_iso())
    mobile, d2 = norm_mobile(raw["mobile"]["plans"], registry, meta_m.get("generated_at") or now_iso())
    internet, mobile = dedupe(internet), dedupe(mobile)
    meta = {"name": "Bill Hero open data", "url": "https://billhero.com.au/data", "fetched": fetched, "via": how,
            "generated": meta_b.get("generated_at"), "licence": meta_b.get("license"),
            "attribution": meta_b.get("attribution"), "dropped": d1 + d2,
            "raw_counts": {"internet": len(raw["broadband"]["plans"]), "mobile": len(raw["mobile"]["plans"])}}
    write_norm("billhero", {"internet": internet, "mobile": mobile}, meta)
    print(f"billhero: {len(internet)} internet, {len(mobile)} mobile ({len(d1) + len(d2)} dropped)")


if __name__ == "__main__":
    main()

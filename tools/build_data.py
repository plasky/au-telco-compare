#!/usr/bin/env python3
"""Merge the adapters' normalised output, apply overrides, validate, and write site data.

Inputs:  data-raw/normalised/<source>.json   (from sources/*.py)
         data-raw/refresh-status.json        (which adapters ran OK this time; optional)
         overrides/plans.toml
         site/data/plans.json                (the previously published data, for fail-safe)
Outputs: site/data/plans.json, site/data/plans.js (window.TELCO_DATA), site/data/report.json,
         data-raw/build-report.md

Rules:
  - A provider covered by its own adapter, or by full records in overrides/plans.toml, replaces all
    of that provider's Bill Hero records.
  - Missing setup fee / modem details on adapter records are filled from Bill Hero's record for
    the same provider, kind and tier, else setup defaults to 0 and modem to "unknown".
  - Fail-safe: if a source failed this run, or its record count fell by more than 40% against
    the published data, the previously published records from that source are kept.
  - Records failing the schema are dropped and listed. Promos past their sign-up date are
    removed. Price moves over 30% against the published data are listed for review.
Exit status: 0 = clean, 2 = published but needs attention (workflow opens an issue),
             1 = nothing written.
"""
import json
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import NORM, RAW, ROOT, SITE_DATA, load_providers, now_iso, provider_name  # noqa: E402
from schema import check_internet, check_mobile  # noqa: E402

BACKBONE = "billhero"
DROP_LIMIT = 0.40
MOVE_LIMIT = 0.30
STALE_DAYS = 3
KINDS = ("internet", "mobile")
CHECK = {"internet": check_internet, "mobile": check_mobile}


def today_aest():
    return datetime.now(timezone(timedelta(hours=10))).date().isoformat()


def load_json(p, default=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


def main():
    issues, notes = [], []      # issues -> exit 2 (open an issue); notes -> report only
    status = load_json(RAW / "refresh-status.json", {})
    prev = load_json(SITE_DATA / "plans.json", {}) or {}
    prev_by_source = {k: {} for k in KINDS}
    for k in KINDS:
        for r in prev.get(k, []):
            prev_by_source[k].setdefault(r["source"], []).append(r)

    # 1. Load each source, with fail-safe fallback to the published records.
    sources, meta = {}, {}
    names = sorted({p.stem for p in NORM.glob("*.json")} | set(status) | {s for k in KINDS for s in prev_by_source[k]})
    for src in names:
        if src == "override":
            continue
        d = load_json(NORM / f"{src}.json")
        st = status.get(src, {}).get("status", "ok" if d else "missing")
        recs = {k: (d or {}).get(k, []) for k in KINDS}
        m = dict((d or {}).get("meta", {}))
        fallback_reason = None
        if st != "ok" or d is None:
            fallback_reason = f"adapter {st}: {status.get(src, {}).get('error', 'no output')}"
        else:
            fetched = m.get("fetched")
            if fetched and datetime.fromisoformat(fetched.replace("Z", "+00:00")) < datetime.now(timezone.utc) - timedelta(days=STALE_DAYS):
                notes.append(f"{src}: data last fetched {fetched} (over {STALE_DAYS} days old)")
            for k in KINDS:
                old = len(prev_by_source[k].get(src, []))
                if old >= 5 and len(recs[k]) < old * (1 - DROP_LIMIT):
                    fallback_reason = f"{k} records fell from {old} to {len(recs[k])}"
        if fallback_reason:
            if any(prev_by_source[k].get(src) for k in KINDS):
                recs = {k: prev_by_source[k].get(src, []) for k in KINDS}
                m = next((s for s in prev.get("meta", {}).get("sources", []) if s["id"] == src), m)
                m = {**m, "status": "fallback"}
                issues.append(f"{src}: kept previously published data ({fallback_reason})")
            else:
                issues.append(f"{src}: no usable data ({fallback_reason})")
                continue
        else:
            m["status"] = "ok"
        sources[src], meta[src] = recs, m

    if not sources:
        print("no source data at all; nothing written", file=sys.stderr)
        return 1

    # 2. Merge: provider adapters replace the backbone's records for their provider.
    merged = {}
    for k in KINDS:
        covered = {r["provider"] for s, recs in sources.items() if s != BACKBONE for r in recs[k]}
        backbone = [r for r in sources.get(BACKBONE, {}).get(k, []) if r["provider"] not in covered]
        rows = [r for s, recs in sources.items() if s != BACKBONE for r in recs[k]] + backbone
        merged[k] = rows

    # 3. Fill gaps on adapter internet records from the backbone (same provider, kind and tier).
    bb = {(r["provider"], r["kind"], r.get("tier")): r for r in sources.get(BACKBONE, {}).get("internet", [])}
    for r in merged["internet"]:
        ref = bb.get((r["provider"], r["kind"], r.get("tier"))) if r.get("source") != BACKBONE else None
        if r.get("setup") is None:
            r["setup"] = ref["setup"] if ref else 0.0
        if (r.get("modem") or {}).get("offer") == "unknown" and ref and ref["modem"]["offer"] != "unknown":
            r["modem"] = dict(ref["modem"])

    # 4. Overrides.
    ov = tomllib.loads((ROOT / "overrides" / "plans.toml").read_text())
    today = today_aest()
    for k in KINDS:
        for e in ov.get(k, []):
            if e.get("expires", "9999") < today:
                issues.append(f"override plan {e.get('id')} expired {e['expires']}; re-check it")
                continue
            rec = {f: v for f, v in e.items() if f not in ("reason", "expires", "source_url")}
            rec["source"] = "override"
            if e.get("source_url"):
                rec.setdefault("url", e["source_url"])
            rec.setdefault("verified", True)
            rec.setdefault("captured", now_iso())
            merged[k] = [r for r in merged[k] if r["id"] != rec["id"]] + [rec]
    for k in KINDS:   # a provider entered by hand replaces its Bill Hero records, as an adapter does
        hand = {e["provider"] for e in ov.get(k, []) if e.get("expires", "9999") >= today}
        merged[k] = [r for r in merged[k] if not (r["source"] == BACKBONE and r["provider"] in hand)]
    ex = {e["id"] for e in ov.get("exclude", [])}
    for p in ov.get("patch", []):
        if p.get("expires", "9999") < today:
            issues.append(f"override patch for {p['id']} expired {p['expires']}; re-check it")
            continue
        hit = [r for k in KINDS for r in merged[k] if r["id"] == p["id"]]
        if not hit:
            notes.append(f"override patch for {p['id']} matched nothing")
        for r in hit:
            r.update(p.get("set", {}))
    for k in KINDS:
        merged[k] = [r for r in merged[k] if r["id"] not in ex]
    unmatched = ex - {r["id"] for k in KINDS for r in sources.get(BACKBONE, {}).get(k, []) + [x for s in sources.values() for x in s[k]]}
    for i in sorted(unmatched):
        notes.append(f"exclude {i} matched nothing (fixed upstream? remove the entry)")

    # 5. Expired promos, schema validation, duplicate ids.
    dropped = []
    for k in KINDS:
        keep, seen = [], set()
        for r in merged[k]:
            r.setdefault("notes", None)
            p = r.get("promo")
            if p and p.get("until") and p["until"] < today:
                notes.append(f"{r['id']}: promo ended {p['until']}, removed")
                r["promo"] = None
            errs = CHECK[k](r)
            if r["id"] in seen:
                errs.append("duplicate id")
            if errs:
                dropped.append({"id": r["id"], "kind": k, "source": r.get("source"), "errors": errs})
                continue
            seen.add(r["id"])
            keep.append(r)
        merged[k] = sorted(keep, key=lambda r: (r["provider"], r["price"]))
        total = len(keep) + sum(1 for d in dropped if d["kind"] == k)
        if total and len(keep) < total * 0.9:
            issues.append(f"{k}: {total - len(keep)} of {total} records failed validation")
    for d in dropped:
        notes.append(f"dropped {d['kind']} {d['id']} ({d['source']}): {'; '.join(d['errors'])}")

    # 6. Price moves against the published data.
    moves = []
    for k in KINDS:
        old = {r["id"]: r for r in prev.get(k, [])}
        for r in merged[k]:
            o = old.get(r["id"])
            if o and o.get("price") and abs(r["price"] - o["price"]) / o["price"] > MOVE_LIMIT:
                moves.append(f"{r['id']}: ${o['price']} -> ${r['price']}")
    if moves:
        notes.append(f"{len(moves)} price moves over {int(MOVE_LIMIT * 100)}%: " + "; ".join(moves[:20]))

    # 7. Write.
    registry, unknown = load_providers(), set()
    used = sorted({r["provider"] for k in KINDS for r in merged[k]})
    providers = {p: {"name": provider_name(p, registry, unknown)} for p in used}
    if unknown:
        notes.append("providers missing from providers.toml: " + ", ".join(sorted(unknown)))
    src_meta = []
    if any(r["source"] == "override" for k in KINDS for r in merged[k]):
        meta["override"] = {"name": "Manual entries, checked by hand", "url": None, "status": "ok", "fetched": None}
    for s, m in sorted(meta.items()):
        src_meta.append({"id": s, "name": m.get("name", s), "url": m.get("url"), "status": m.get("status"),
                         "fetched": m.get("fetched"), "generated": m.get("generated"),
                         "licence": m.get("licence"), "attribution": m.get("attribution"),
                         "records": {k: sum(1 for r in merged[k] if r["source"] == s) for k in KINDS}})
    out = {"meta": {"built": now_iso(), "built_date_aest": today, "sources": src_meta,
                    "counts": {k: len(merged[k]) for k in KINDS},
                    "verified": {k: sum(1 for r in merged[k] if r["verified"]) for k in KINDS}},
           "providers": providers, **merged}
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "plans.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    (SITE_DATA / "plans.js").write_text("window.TELCO_DATA=" + json.dumps(out, separators=(",", ":"), ensure_ascii=False) + ";\n")
    report = {"built": out["meta"]["built"], "issues": issues, "notes": notes, "counts": out["meta"]["counts"],
              "verified": out["meta"]["verified"], "sources": src_meta}
    (SITE_DATA / "report.json").write_text(json.dumps(report, indent=1))
    md = [f"# Build report {out['meta']['built']}", "",
          f"Internet plans: {out['meta']['counts']['internet']} ({out['meta']['verified']['internet']} verified)  ",
          f"Mobile plans: {out['meta']['counts']['mobile']} ({out['meta']['verified']['mobile']} verified)", "",
          "## Sources", ""] + [f"- {s['id']}: {s['status']}, {s['records']['internet']} internet / {s['records']['mobile']} mobile" for s in src_meta] \
        + ["", "## Needs attention", ""] + ([f"- {i}" for i in issues] or ["- nothing"]) \
        + ["", "## Notes", ""] + ([f"- {n}" for n in notes] or ["- nothing"])
    (RAW / "build-report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[2:4]))
    for i in issues:
        print("ATTENTION:", i)
    print(f"{len(notes)} notes in data-raw/build-report.md")
    return 2 if issues else 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared helpers for the data pipeline: paths, polite HTTP, provider registry, NBN tiers."""
import gzip
import json
import pathlib
import re
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data-raw"
NORM = RAW / "normalised"            # one JSON file per source, written by the adapters
SITE_DATA = ROOT / "site" / "data"
USER_AGENT = "au-telco-compare/0.1 (personal plan comparison site; nightly, rate-limited)"

# NBN wholesale speed tiers (download Mbps), late 2026. 500 and above need FTTP or HFC.
NBN_TIERS = [12, 25, 50, 100, 250, 500, 750, 1000, 2000]
FIXED_LINE = ["fttp", "hfc", "fttc", "fttn", "fttb"]

_last_request = {}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch(url, dest=None, min_interval=2.0, retries=3, timeout=60):
    """GET a URL with an identifiable client name, at most one request every 2 seconds per host.
    Retries network errors and server errors, but never a refusal (403, 404, 410, 429, 451).
    Saves the body to `dest` (a path) when given. Returns the body as bytes."""
    host = url.split("/")[2]
    wait = _last_request.get(host, 0) + min_interval - time.time()
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410, 429, 451) or attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
            continue
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    _last_request[host] = time.time()
    if body[:2] == b"\x1f\x8b":          # gzip sent without being asked for
        body = gzip.decompress(body)
    if dest:
        dest = pathlib.Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    return body


def load_providers():
    return tomllib.loads((ROOT / "providers.toml").read_text())["providers"]


def provider_name(pid, registry, unknown=None):
    if pid in registry:
        return registry[pid]["name"]
    if unknown is not None:
        unknown.add(pid)
    return " ".join(w.capitalize() for w in re.split(r"[-_]", pid))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def tier_from(name, speed):
    """Nominal NBN tier from the plan name ("NBN 750", "nbn100", "Home Fast") or, failing that,
    the smallest tier at or above the published speed (published speeds are typical evening
    speeds, e.g. 740 on a 750 plan, 820 or 850 on a 1000 plan)."""
    n = name.lower()
    m = re.search(r"(?:nbn|fibre|fiber|fttb|nbn®)\s*-?\s*(12|25|50|100|250|500|750|1000|2000)\b", n) \
        or re.search(r"\b(12|25|50|100|250|500|750|1000|2000)\s*/\s*\d+", n)
    if m:
        return int(m.group(1))
    words = [("hyperfast", 2000), ("hyperspeed", 2000), ("ultrafast", 1000), ("superfast", 750),
             ("home fast", 500), ("home standard", 50), ("home basic", 25)]
    for w, t in words:
        if w in n and not speed:
            return t
    if speed:
        for t in NBN_TIERS:
            if speed <= t * 1.0001:
                return t
        return 2000
    return None


def techs_for(kind, tier):
    """Connection technologies a plan can be used on."""
    if kind == "fixed_wireless":
        return ["fw"]
    if kind == "satellite":
        return ["sat"]
    if kind != "nbn":
        return []
    if tier and tier >= 250:   # 250 is the pre-2025 Superfast tier; like 500+, FTTP/HFC only
        return ["fttp", "hfc"]
    return list(FIXED_LINE)


def write_norm(source, records, meta):
    NORM.mkdir(parents=True, exist_ok=True)
    out = {"source": source, "meta": meta, **records}
    (NORM / f"{source}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out

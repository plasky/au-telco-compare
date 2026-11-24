#!/usr/bin/env python3
"""Nightly refresh: run every adapter in sources/, then build and test.

Each adapter runs in its own process, so one broken provider can't stop the others. Results go
to data-raw/refresh-status.json, which the build uses to decide when to fall back to the
previously published data.

Usage: python3 -I tools/refresh.py [--only billhero,amaysim] [--skip-fetch]
Exit status: 0 clean; 2 published but needs attention; 1 failed.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from common import RAW, now_iso  # noqa: E402


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    status = json.loads((RAW / "refresh-status.json").read_text()) if (RAW / "refresh-status.json").exists() else {}
    if "--skip-fetch" not in args:
        for script in sorted((ROOT / "sources").glob("*.py")):
            name = script.stem
            if only and name not in only:
                continue
            r = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=900)
            ok = r.returncode == 0
            status[name] = {"status": "ok" if ok else "failed", "at": now_iso(),
                            "error": None if ok else (r.stderr.strip().splitlines() or ["unknown error"])[-1][:300]}
            print(("ok     " if ok else "FAILED ") + name + ("" if ok else f": {status[name]['error']}"), flush=True)
            if r.stdout.strip():
                print("       " + r.stdout.strip().replace("\n", "\n       "), flush=True)
        RAW.mkdir(exist_ok=True)
        (RAW / "refresh-status.json").write_text(json.dumps(status, indent=1))
    build = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_data.py")])
    if build.returncode == 1:
        return 1
    test = subprocess.run(["node", str(ROOT / "tools" / "test_engine.js")])
    if test.returncode != 0:
        return 1
    failed = any(v["status"] != "ok" for v in status.values())
    return 2 if (build.returncode == 2 or failed) else 0


if __name__ == "__main__":
    sys.exit(main())

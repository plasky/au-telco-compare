#!/bin/bash
# Refresh the Bill Hero snapshot from feeds downloaded in a browser, then commit and push it.
#   1. Open https://billhero.com.au/data/broadband and https://billhero.com.au/data/mobile in a
#      browser and save each page (File > Save Page As..., or Cmd-S).
#   2. tools/import-billhero.sh ~/Downloads/broadband.json ~/Downloads/mobile.json
# The nightly refresh uses the snapshot for 8 days.
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -eq 2 ] || { echo "usage: $0 BROADBAND_FILE MOBILE_FILE" >&2; exit 1; }
git pull -q --ff-only
python3 -I sources/billhero.py --import-snapshot "$1" "$2"
git add snapshots/billhero
if git diff --cached --quiet; then echo "Snapshot unchanged; nothing to push."; exit 0; fi
git commit -q -m "Bill Hero snapshot $(python3 -c 'import json; print(json.load(open("snapshots/billhero/snapshot.json"))["fetched"][:10])')"
git push -q
echo "Pushed. The next nightly refresh (7:30am AEDT) will use it."

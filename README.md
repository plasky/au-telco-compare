# Australian Telco Compare

A static website that ranks Australian home internet (NBN, 5G home, Starlink) and mobile plans
against a household's needs at their true cost over time. Companion to Melbourne Energy
Compare. See [PLAN.md](PLAN.md) for the research, design and build phases.

**Status:** phase 2 (home internet comparison) built. Mobile, bundles and phones are phases 3–4.

## Layout

- `site/`: everything GitHub Pages serves.
  - `index.html`, `css/style.css`, `js/app.js`: the comparison page. The household settings
    autosave in the browser (`localStorage` key `atc-state-v1`) and can be saved to or loaded
    from a file. The stylesheet started as a copy of Melbourne Energy Compare's.
  - `js/engine.js`: cost engine (browser + Node). Covers needed speed, technology and
    availability checks (5G networks, Starlink, private networks), hardware cost, internet cost
    with promos/setup/modem/bundles, promo-chasing, the best-value frontier, and mobile cost per
    line.
  - `data/plans.js`: generated data (`window.TELCO_DATA`); `plans.json` is the same data for
    diffs and fallback; `report.json` is the last build report.
- `sources/`: one adapter per data source, each writing `data-raw/normalised/<source>.json`.
  Every `.py` file here is run as an adapter, so don't put helper modules in this folder.
  - `billhero.py`: Bill Hero open data feeds (backbone for NBN and mobile), falling back to
    the committed snapshot in `snapshots/billhero/` when the live fetch is refused.
  - `amaysim.py`: amaysim's machine-readable catalogue (NBN + SIM, with promos).
  - Provider plan pages (home internet only so far; each reads structured data such as
    JSON-LD, embedded JSON or data-* attributes from one or two server-rendered pages):
    `telstra.py` (NBN, 5G, fixed wireless), `optus.py` (NBN, 5G), `tpg.py` (NBN, 5G, fixed
    wireless, TPG's own FTTB network), `vodafone.py` (NBN, 5G), `aussie_broadband.py`,
    `superloop.py`, `exetel.py`, `spintel.py` (NBN, 5G), `dodo.py`, `iprimus.py`, `mate.py`,
    `more.py`, `flip.py`, `tangerine.py` (only the plans shown before an address check).
- Entered by hand in `overrides/plans.toml` (sites that need JavaScript or refuse automated
  clients): Starlink, Belong, iiNet, Internode, AGL and Tangerine's copper-only plans. Each
  entry has an expiry date; re-check those plans when the build report flags them.
- Not covered yet, so still on Bill Hero's data (marked "not yet checked" on the site): Origin
  (refuses our client), Leaptel (Cloudflare challenge), Kogan Internet (DataDome challenge),
  Launtel (prices only after an address check) and the long tail.
- `overrides/plans.toml`: manual excludes, patches and added plans, each with a reason, a
  source URL and (for patches and additions) an expiry date.
- `overrides/bundles.toml`: provider bundle discounts (phase 3). The current entries are
  candidates still to be checked.
- `providers.toml`: provider ids, display names, own-network and host-network hints.
- `tools/`
  - `refresh.py`: runs every adapter (each in its own process), then the build and tests.
  - `build_data.py`: merge, fill gaps, apply overrides, validate, write site data and
    `data-raw/build-report.md`.
  - `schema.py`: record schema (documented at the top) and per-record checks.
  - `test_engine.js`: cost-model tests on hand-worked plans, plus checks on the built data.
- `.github/workflows/`: `nightly.yml` (refresh, commit, report, deploy) and `pages.yml`
  (deploy `site/` to GitHub Pages).

## Run it locally

```bash
cd ~/Research/au-telco-compare
python3 -I tools/refresh.py                 # fetch all sources, build, test
python3 -I tools/refresh.py --skip-fetch    # rebuild from the last downloads
node tools/test_engine.js
python3 -m http.server 8772 --directory site
```

Exit codes: 0 = clean; 2 = data published but something needs a look (see
`data-raw/build-report.md`); 1 = failed, nothing published.

## How the data is merged

1. Each adapter produces normalised records (see `tools/schema.py`).
2. A provider with its own adapter, or with full plan records in `overrides/plans.toml`,
   replaces all of that provider's Bill Hero records. Adapter and hand-entered records are
   `verified: true`; Bill Hero records are `verified: false`. Bill Hero often lists an intro or
   bundle price as the ongoing price (this was true for most big brands in Nov 2026), so the
   site labels its records "not yet checked".
3. Missing setup fees and modem details on adapter records are filled from Bill Hero's record
   for the same provider, kind and tier.
4. Overrides apply: excludes, patches and added plans. Expired entries stop applying and are
   reported.
5. Validation: schema and price bounds. Promos past their sign-up date are removed. Records
   that fail are dropped and listed.
6. **Fail-safe:** if an adapter fails, or its record count falls by more than 40% against the
   published data, the previously published records for that source are kept. The build then
   exits 2, so the nightly workflow opens (or comments on) a GitHub issue.
7. Price moves over 30% against the published data are listed in the report.

## Adding a provider adapter

Write `sources/<provider>.py` that fetches the provider's own plan pages (respect robots.txt;
`common.fetch` rate-limits and sends an identifiable client name) and calls
`write_norm("<provider>", {"internet": [...], "mobile": [...]}, meta)` with schema-valid
records. Raise an exception if parsing finds nothing, so the fail-safe takes over. Don't scrape
comparison sites (WhistleOut, Finder, Canstar), and don't work around bot protection. Use a
manual override for providers that block automated access.

Things the schema can express that adapters should fill when the provider states them:
`down`/`up` as typical evening speeds; `techs` narrowed to the connection types the provider
lists (e.g. "Fast" plans sold as NBN 100 on FTTN/FTTB/FTTC and NBN 500 on FTTP/HFC become two
records); modem `rental` with a `monthly` price, or `included_contract` with the pay-out `fee`
and `months`; bundle discounts with `during_promo: true` when they stack with the intro offer;
and promos with `requires: "energy"` (or `"mobile"`) when only bundled customers get them.

Adapters that ran fine locally can still be blocked from GitHub's servers. The fail-safe keeps
the last good data and the nightly job opens an issue, so check the first few runs.

## Publishing (repo: github.com/plasky/au-telco-compare)

1. Push this folder to the repo (`data-raw/` is git-ignored).
2. Settings → Pages → Source: **GitHub Actions**.
3. Settings → Actions → General → Workflow permissions: read and write.
4. Run "Nightly data refresh" once by hand (Actions tab) to check it works.

## Data sources and licences

- Bill Hero open data (https://billhero.com.au/data), CC-BY-4.0. The site must show
  "Data via Bill Hero (billhero.com.au)". Since 25 Nov 2026 Bill Hero puts a Cloudflare
  challenge in front of the feeds for automated clients, so the nightly job uses the snapshot
  in `snapshots/billhero/` (valid for 8 days). Refresh it by downloading both feeds in a browser
  and running `tools/import-billhero.sh <broadband file> <mobile file>`. Once the snapshot is
  over 8 days old, the build keeps the last published Bill Hero records and opens an issue.
- amaysim plan catalogue (https://www.amaysim.com.au/products/catalogue/plans), published by
  amaysim for automated readers.
- NBN tiers: nbnco.com.au/residential/speed-plans. Evening speed labels: ACCC broadband speed
  guidance (busy hours 7–11pm).

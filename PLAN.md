# Australian Telco Compare: plan

A public static website, a companion to Melbourne Energy Compare. It finds the cheapest
combination of home internet, mobile plans and phones for a household. Plans are ranked
against what the household actually needs, at the true cost over time (including promos
ending, modem and setup costs, bundle discounts and phone repayments).

Status: draft, 24 Nov 2026. The first round of questions has been answered (section 4).

---

## 1. Research findings

### 1.1 There is no official plan feed for telco

- Energy has the Consumer Data Right product feed. Telco doesn't. The telco CDR designation
  (2022) exists, but implementation was **paused in 2023**. I found no sign that it has
  restarted. Plan data therefore has to come from providers and third parties.
- **Bill Hero open data feeds** (`billhero.com.au/data/broadband`, `/data/mobile`):
  - Free JSON, updated daily, CC-BY-4.0 (attribution: "Data via Bill Hero (billhero.com.au)").
    The site describes them as CORS-open.
  - About 276 NBN plans: carrier, plan name, monthly price, down/up speed, contract term,
    setup fee, modem offer, link to the Critical Information Summary (CIS).
  - About 322 mobile plans: carrier, host network, plan type (prepaid/postpaid/SIM-only),
    monthly price, data in GB, calls, 5G, international countries.
  - **Gaps:** no promo price or length, no typical evening speed, no 5G home or Starlink, no
    handsets.
  - **Quality issue:** the methodology says ongoing prices are used, but Amaysim's NBN prices
    in the feed match Amaysim's 6-month promo price ($30), not the ongoing price ($70). So it
    is a useful backbone and cross-check, not a source of truth.
- **Provider pages and CIS documents** are the authoritative source. Some providers publish
  machine-readable pages. Amaysim, for example, has a "machine-readable plan and promotion
  data" catalogue with promo amounts, length and validity dates. Many others are rendered
  with JavaScript and sit behind bot protection.
- **Comparison sites** (WhistleOut, Finder, Canstar Blue) are off-limits as sources. Their
  terms don't allow reuse.

### 1.2 Home internet market (late 2026)

- **NBN tiers:**
  - Home Basic (12, 25), Home Standard (50) and Home Fast (100) are available on all fixed-line
    technologies.
  - Since the 2025 upgrade, the top tiers on **FTTP and HFC only** are Home Fast 500,
    Superfast 750, Ultrafast 1000 and the new **Hyperfast 2000** (2000/200 on FTTP, 2000/100
    on HFC). Providers must opt in.
  - FTTN, FTTC and FTTB top out at 100.
  - Fixed wireless has its own tiers, up to about 400.
  - Exact speeds to be re-verified when the data schema is written.
- **Prices:** typical ongoing prices run from about $60–75/month for NBN 25–50, through
  about $80–100 for NBN 100–500, up to $130–170 for NBN 1000–2000. Wholesale price changes
  on 1 July each year flow through.
- **Promos:**
  - Most new-customer deals are "$X off for 6 months" (sometimes 12). Ranking on the headline
    price is misleading, and switching again when the promo ends is a real strategy.
  - Bundle discounts are common:
    - NBN with mobile: about $5–10/month or a percentage (Vodafone, TPG, iiNet, Superloop,
      Exetel, Mate, Tangerine, Amaysim).
    - Energy with NBN: AGL $15/month, Origin $10/month, Dodo $12–15/month.
- **Speed quality:** the ACCC's Measuring Broadband Australia programme **ended in June
  2026**. In its final report, NBN fixed-line services averaged about 100% of plan speed in
  busy hours. ACCC guidance asks providers to advertise each plan's **typical evening speed
  (7–11pm)**, and practically all do. Those per-plan figures become the speed measure.
- **Alternatives to NBN:**
  - 5G home internet (Telstra, Optus, TPG/Vodafone, iiNet and others, with Optus at about
    $69–99/month). It is usually cheaper than NBN 50–100 but has no top-tier equivalent, and
    availability is address-specific.
  - Starlink: monthly plans plus hardware. Prices must be read from its JavaScript site; to
    verify.
- **Connection type by address:** NBN Co's address checker has no official public API.
  Unofficial wrappers exist, but browsers would block calls from a static site. The site will
  ask the user to pick their connection type, with a link to NBN Co's checker.

### 1.3 Mobile market

- **Three networks:** Telstra, Optus and Vodafone (owned by TPG). Each budget brand (MVNO)
  uses one of them:
  - Telstra: Boost gets the full Telstra network; Aldi, Woolworths, Belong and others use
    Telstra's wholesale network, which covers slightly less.
  - Optus: Amaysim, Circles.Life and others.
  - Vodafone: Felix, Lebara, TPG, iiNet and others.
- Coverage is the main quality difference. There is no public coverage API, so the user rates
  each network at home and work, with links to the coverage maps.
- **Plan types:**
  - Postpaid monthly with no lock-in.
  - Prepaid recharges every 28 days (13.04 a year) or 30 days.
  - Long-expiry recharges (6 or 12 months, e.g. Telstra $44 per 6 months, Amaysim 240 GB per
    year).
  - Extras: data banking, international call packs, roaming, 5G, eSIM.
  - Multi-line discounts on some carriers.
- **Phones on plans:**
  - Telstra, Optus and Vodafone have dropped lock-in contracts. Handsets are paid off with
    separate interest-free repayments over 12, 24 or 36 months, and the remaining balance is
    due if you leave.
  - Deals change weekly: device discounts on some plans, bonus credits, trade-in bonuses.
  - The usual alternative is to buy outright (Apple/Samsung/Google, or retailers such as JB
    Hi-Fi) and use a cheap SIM-only plan. That is often cheaper, but not always when a carrier
    discount is running.

---

## 2. What the site does

Same approach as the energy site: describe the household and its needs once, see everything
ranked by true cost, and play with the settings.

### 2.1 Inputs ("Your household")

- **Address basics:**
  - State and postcode.
  - NBN connection type (FTTP / HFC / FTTC / FTTN / FTTB / fixed wireless / satellite / not
    sure), with a link to NBN Co's address checker.
  - Toggles for "5G home internet available here" and "Starlink OK".
- **Internet needs:**
  - Number of people.
  - Streaming: number of simultaneous 4K and HD streams.
  - Video calls while working from home.
  - Gaming.
  - Big uploads (cloud backup, photos, work data).
  - These produce a **recommended typical evening speed**, both download and upload, with the
    reasoning shown. You can override it with a speed-tier picker.
- **Mobile lines** (up to 8, add/remove like the "other appliances" list on the energy site).
  For each line:
  - Name.
  - Data per month (with a "check your usage" hint).
  - Calls: standard unlimited, or needs international calls to selected countries.
  - Days of overseas roaming a year.
  - Must-haves: 5G, eSIM, data rollover.
  - Network preference or coverage rating for Telstra, Optus and Vodafone at home and work.
  - Plan style: monthly, prepaid, or long-expiry OK.
- **Phones** (for each line):
  - "Need a new phone?" plus model and storage from a catalogue of about 25 popular handsets.
  - Repayment term, and whether a trade-in is available (value input).
  - "Keep my current phone" means SIM-only.
- **Current bills** (optional): what you pay now for internet and each line, to show the
  saving.
- **Strategy toggles:**
  - Comparison horizon: 12, 24 or 36 months.
  - "I'll switch again when the promo ends", which models chasing promos versus staying put.
  - Count sign-up credits.
  - Include business-grade providers.
- **Energy link:** "My electricity/gas retailer is…". Pre-filled from the energy site's saved
  settings when both sites share a GitHub Pages domain (same browser origin). This unlocks
  energy + NBN bundles.

### 2.2 Outputs

- **Headline tiles:**
  - Cheapest internet that meets your needs.
  - Cheapest mobile set-up for all lines.
  - Cheapest overall (best mix across providers).
  - Best single-provider bundle.
  - Saving versus your current bills.
- **Internet:**
  - A **cost vs typical evening speed scatter** of every eligible plan, with the best-value
    plans (the frontier) highlighted.
  - A ranked table with promo and ongoing prices, setup and modem costs, upload speed and
    contract.
  - A month-by-month cost line over the horizon, showing the promo cliff and the effect of
    switching again.
- **Mobile:**
  - The best plan for each line and the household total.
  - A "same network for everyone" alternative.
  - Multi-line discounts and NBN bundle discounts applied.
  - Plans with too little data are excluded, or shown with add-on costs.
- **Phones:** for each new phone, a side-by-side comparison:
  - Outright (cheapest listed price) + best SIM-only plan.
  - Each carrier's repayments + its required plan, minus discounts and bonus credits.
  - Shown as total cost over the horizon and per month, with the payout risk flagged.
- **Bundle finder:** combines internet, mobile and energy providers and picks the cheapest
  combination after bundle rules. Uses the same "best mix vs one provider" logic as the
  energy site.
- **Charts and tables:**
  - Stacked annual cost by service.
  - Tables behind every chart.
  - Dark mode, mobile layout and saved settings, all reused from the energy site.
- **Data panel:** data date, where each figure came from, provider coverage, and attribution
  (Bill Hero CC-BY).

### 2.3 Cost model (engine)

- **Internet cost over H months:**
  - Monthly price, with the promo price for the promo months.
  - Plus setup fee, plus modem (included / bought / bring your own).
  - Minus bundle discount if the conditions are met, minus sign-up credit if counted.
  - Exit fees if there is a contract.
  - Promo-chasing mode assumes a switch to the best then-available promo when each promo ends.
- **Needs check:** typical evening download ≥ needed download, and upload ≥ needed upload. The
  plan must be available on the connection type: NBN tier eligibility, 5G or Starlink flags.
- **Mobile cost per line over H months:**
  - Recharge cost × number of recharges (28-day plans give 13.04 a year), or monthly price × H.
  - Promo months included.
  - International and roaming add-ons where the plan lacks them.
  - Excluded if the data allowance (including rollover, if the plan has it) is below need.
    Optionally, data add-on packs can be costed instead.
- **Household optimisation:**
  - Per provider: best plan for each line plus multi-line and NBN bundle discounts.
  - Best mix across providers.
  - Best single provider.
  - Small search space (about 40 providers × a few plans), so exhaustive search is fine in the
    browser.
- **Phones:**
  - Repayments are device price ÷ term, minus carrier device discount, minus bonus credits
    (spread over their stated period), with the required plan.
  - Compared against outright price + best SIM-only plan, over the same horizon.
  - Trade-in value is subtracted where entered.
- **Engine module and tests:** a UMD module like `engine.js`, with Node tests against
  hand-checked cases. For example, Amaysim NBN 100 over 12 months = 6 × $30 + 6 × $70 = $600.

---

## 3. Data pipeline (nightly, GitHub Actions)

```
sources/                     one adapter per source, each returns normalised records
  billhero.py                NBN + mobile backbone (CC-BY, attribution shown on site)
  <provider>.py              provider plan pages / CIS / machine-readable catalogues
  handsets_*.py              manufacturer RRPs, carrier device pricing
overrides/*.yaml             manual fixes and promos, each with source URL and expiry date
tools/build_data.py          merge -> validate -> site/data/*.js
tools/validate.py            schema, price bounds, day-on-day change limits, staleness
tools/test_engine.js         cost-model tests
.github/workflows/nightly.yml
```

- **Merge order:** provider adapter > manual override > Bill Hero. Each record keeps its
  source and capture time, and the site shows them.
- **Validation:**
  - Schema check and sane bounds (e.g. NBN $20–$300/month).
  - Flag day-on-day price changes over 30%.
  - Drop promos past their end date.
  - If a source fails or its data looks wrong, keep yesterday's data for that source. The
    workflow then opens a GitHub issue rather than publishing bad prices.
- **Scraping etiquette:**
  - Plain identifiable client name, respect robots.txt, rate-limited, about one request per
    second per host.
  - Pages that need a browser use a headless browser (Playwright) in the workflow.
  - Sites that block automated access get a manual override entry or rely on Bill Hero.
  - No bot-detection workarounds.
- **Provider coverage, in priority order:**
  - **NBN:** Telstra, Optus, TPG/iiNet/Vodafone (TPG group), Aussie Broadband, Superloop,
    Exetel, Dodo/iPrimus, Belong, Amaysim, Tangerine, Leaptel, Launtel, Mate, Spintel, Buddy,
    Kogan, Origin, AGL, Flip, More. The long tail comes from Bill Hero.
  - **Mobile:** Telstra, Optus, Vodafone, Boost, Aldi, Belong, Woolworths, Amaysim, Felix,
    Lebara, Circles, Catch/Kogan/Moose, Lyca, TPG, iiNet, Superloop, Aussie Broadband,
    Tangerine, Mate.
  - **5G home / Starlink:** about 8 providers, partly manual (prices change rarely).
  - **Handsets:** about 25 models (iPhone 17 range, Galaxy S26 range, Pixel, plus a few budget
    models). Manufacturer RRP plus Telstra, Optus and Vodafone repayment pages.
- **Hosting:** new public GitHub repo, GitHub Pages serving `site/`. The nightly job commits
  the refreshed data, which triggers a Pages deploy. Data stays small (a few hundred KB).

---

## 4. Decisions so far (24 Nov 2026)

- **Services in v1:** NBN, mobile, 5G home / fixed wireless / Starlink, and bundle discounts,
  including energy + NBN.
- **Data upkeep:** nightly automatic refresh with GitHub Actions. Bill Hero is the backbone,
  with provider adapters on top.
- **Mobile scope:** full phone-on-plan, including handset repayments, carrier discounts, bonus
  credits and trade-ins, alongside SIM-only.
- **Hosting:** a new repository with its own GitHub Pages site, linked to and from the energy
  site. Paul will create the repo when it's ready to publish. Until then, everything is built
  and previewed locally, as the energy site was. The GitHub Actions workflow is written then
  but only runs once the repo exists. The energy-settings link needs both sites on the same
  github.io account; otherwise it falls back to a manual "my energy retailer" picker.
- **Default ranking:** total cost over the first **12 months**, assuming you **stay put**
  after the promo ends. "Re-switch when promos end" and 24/36-month horizons are toggles.
- **Default household:** postcode 3165, connection type "not sure" (so the picker sits up
  front with a link to NBN Co's address checker), **4 mobile lines** with placeholder usage to
  be replaced by real numbers.

## 5. Open questions

- The account name, and the energy site's repo/URL, when publishing.
- Real usage for the 4 lines (data per month, international calls, roaming) and current
  providers and bills. These can be entered on the site itself later.
- Site name (working title: Australian Telco Compare).

## 6. Build phases

1. **Scaffold:**
   - Repo, data schema, Bill Hero adapter, validation, nightly workflow (data-only).
   - Engine skeleton with tests.
2. **Home internet:**
   - NBN, 5G home and Starlink data.
   - Needs-to-speed calculator, cost model with promos and modems.
   - Scatter chart, ranked table, month-by-month view.
   - First public version.
3. **Mobile:**
   - Household lines, plan matching, multi-line and NBN bundle discounts.
   - Best mix vs one provider.
   - Energy-bundle link.
4. **Phones:** handset catalogue, outright vs repayment comparison, carrier offers.
5. **Hardening:**
   - More provider adapters.
   - Monitoring through GitHub issues, data panel.
   - Accessibility and mobile review, README for upkeep.

## 6a. Progress

- **Phase 1 (24 Nov 2026):** done. Data pipeline, Bill Hero and amaysim adapters, cost engine
  with tests, nightly workflow.
- **Phase 2 (24 Nov 2026):** home internet comparison page built (`site/index.html`,
  `js/app.js`), with saved settings, tiles, plan card with month-by-month cost, price vs
  evening speed chart with the best-value frontier, and a ranked table.
  - 14 provider adapters, plus hand-entered plans for Starlink, Belong, iiNet, Internode, AGL
    and Tangerine's copper plans: 160 of 328 internet plans now come from the provider.
  - Finding: Bill Hero listed intro or bundle prices as ongoing for nearly every big brand
    (Telstra, Optus, TPG, iiNet, Vodafone, Superloop, Belong, Mate, AGL). Its data is kept only
    for providers with no other source, labelled "not yet checked".
  - Engine additions: 5G network and Starlink availability, hardware cost (5G and Starlink
    always counted), modem rental, bundles that stack with intro offers, intro offers that
    need a bundle (AGL with energy), promo-chasing limited to the same kind and speed.
  - Not yet automatable: Origin, Leaptel, Kogan (bot protection), Launtel (address-only
    prices). The 4G home wireless plans some providers sell are skipped (no schema kind).
  - Repo created: github.com/plasky/au-telco-compare (not pushed yet). The energy site is at
    plasky.github.io/melbourne-energy-compare/, the same origin, so the energy-settings link
    in phase 3 can read its saved settings.

- **Phase 3 (25 Nov 2026):** mobile and household built.
  - Mobile tab: up to 8 lines (data, networks, plan type, international calls), cheapest plan
    per line and a ranked list per line. Household tab: cheapest setup, best single provider,
    cost by service, and each provider's best deal, from `household()` in the engine.
  - 16 mobile adapters plus Lycamobile by hand: 134 of 282 mobile plans now come from the
    provider. Circles.Life excluded (left Australia).
  - Bundles modelled: per-plan discounts (Vodafone $10 off nbn with mobile; TPG/iiNet $5 off
    Medium/Large SIMs with internet; Aussie Broadband $5 off each SIM; Mate $10 off nbn; amaysim
    $10 off nbn; AGL $15 off with energy), plans only sold with internet (Spintel), and account
    rules (Superloop tiers, Tangerine 10%). Energy retailer read from the energy site's saved
    plan on the same origin, or picked by hand.
  - Not modelled: Telstra Bundle Plans (extra lines that need an Essential/Premium line), ALDI
    family plans (shared data), bonus-data offers (in notes only), capped international minutes.
  - Bill Hero: behind a Cloudflare challenge since 25 Nov; the adapter uses a committed snapshot
    refreshed by hand (`tools/import-billhero.sh`). Its long-expiry mobile plans are now read as
    365/180/90-day recharges when the plan name's price gives them away.

## 7. Risks

- **Scraper breakage and bot protection.** This is the main ongoing cost. Mitigations: Bill
  Hero fallback, manual overrides with expiry dates, validation that fails safe and opens an
  issue.
- **Promo accuracy.** Promos are short-lived and conditional. Every promo needs an end date;
  stale promos are dropped automatically. The data date is shown prominently.
- **Phone deals change weekly and depend on the plan.** This is the hardest data to keep
  right, so it is phase 4. The fallback is outright RRP vs repayment at RRP, with carrier
  bonuses as manual overrides.
- **Public site, so accuracy matters.** Each figure links to its source, with clear "check
  before you switch" wording, and Bill Hero is attributed as the licence requires.
- **Coverage can't be automated.** Network quality relies on the user's own rating, with links
  to the official maps.

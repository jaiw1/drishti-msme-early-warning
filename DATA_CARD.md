# DATA CARD — DRISHTi synthetic MSME loan-performance panel

**Artefact:** `data/msme_loan_panel.csv` (account-month panel), `data/accounts_static.csv`
(one row per account, latent fate exposed)
**Generator:** `src/generator/` (CLI: `src/generate_data.py`, or `python3 -m generator.build`
directly for a non-default population)
**Realism audit:** `src/realism.py` (independent, re-derives every number from the CSVs — see
§"Realism-check summary")
**Version:** SD-D6 / SD-D7 (plan §B/L4), 2026-09-16, updated by SD-D8's fix pass 2026-09-17 ·
merges SD-D1 (`0914ac6`-era vectorisation), SD-D2/SD-D3 (eight-portfolio population + shared
latent stress), SD-D4/SD-D5 (noise, hard negatives, labels), the DM-2/DM-6/DM-7 export/rigor pass,
and SD-D8 (three generator fixes for SD-D6's own findings, `vintage_band`, the DR-12 ruling)
**Status:** the panel this card describes is regenerated fresh from `src/generator/**` on `main` @
HEAD — **45,000 accounts × 48 months** (the validation population) and **9,000 accounts × 36
months** (the shipped demo-default population), both seed `20260709`, both committed to
`.gitignore` and reproducible with the one command each carries below. SD-D6/D7 did not edit
`src/generator/**`; SD-D8 (this update) did, narrowly — see "Realism-check summary" and "Known
unrealisms" items 13-15 for exactly what changed and why.

> This is synthetic data. It is engineered to bank-stated baselines and sectoral public figures,
> not sampled from any real customer book. No IDBI record, no Atlas-sandbox pull and no real
> customer is used anywhere in this file or in the generator. Nothing here should be read as a
> measurement of IDBI's actual portfolio — see `book.idbi_fy26.slippage_ratio_pct`'s own note in
> `sources.yaml`: IDBI's real annualised slippage is 0.63%; this panel targets 3-5%, roughly five
> times higher, on purpose (§"Known unrealisms", item 2).

---

## Purpose

DRISHTi's job is a 12-month-ahead early-warning label — `default_within_12m` — over eight retail
loan portfolios an MSME/retail bank actually carries: **MSME cash-credit, MSME term loan, Housing,
Education, Agriculture (KCC), Retail-Unsecured (personal loan), Loan-Against-Property and Auto**.
No real bank book with a clean, complete, correctly-labelled 12-month-forward performance history
across all eight products — with the leakage and self-employed/salaried MAR structure a genuine
underwriting file carries — is available inside the hackathon timeline (§ "Research gaps"). This
panel exists to let the model, the validation harness (`validation/`) and the app (`app/`) be
built and tuned against something coherent, hard and honestly documented, rather than against
nothing, while every number a jury might ask about traces to either a cited public figure or an
explicitly labelled `assumed` judgement call — never to an unstated one.

The mentor mandate this data has to support: **one holistic model across all borrower types**,
with rank-order that holds **per portfolio**, where a **missed NPA costs more than a false
positive**, and where the eventual "90%+ accuracy" framing is replaced with an honest read of
discrimination, calibration and rank-order. The generative design — **one shared latent stress
path, observed through each portfolio's own instruments** (§ "Generation pipeline") — is what
makes "one model, eight products" a claim the data can actually support rather than a marketing
line.

---

## Files & grain

| File | Grain | Rows (45k×48 / 9k×36) | Written by |
|---|---|---|---|
| `data/msme_loan_panel.csv` | one loan account, one calendar month | 2,039,678 / 310,365 | `generator.build.write` |
| `data/accounts_static.csv` | one loan account (static attributes + the latent fate the panel hides: `is_defaulter`, `npa_month`, `severity`, `onset`, `silent_default`, `transient_months`, `transient_arrears`, `statement_gap_months`) | 45,000 / 9,000 | `generator.build.write` |

Both are regenerated, never hand-edited, and both are `.gitignore`d (`data/msme_loan_panel.csv`,
`data/accounts_static.csv`) — regenerate with:

```
python3 src/generate_data.py --n 45000 --months 48 --seed 20260709 --out data          # validation population, ~15-23s
python3 src/generate_data.py --seed 20260709 --out data/small9k36                       # shipped-demo population, ~5s (defaults: n=9000, months=36)
```

The panel row is filtered to **standard, pre-NPA rows only** (`generator.labels.standard_rows`):
once an account crosses 90 DPD it stops appearing, so the model never trains or scores on an
account that has already gone bad. `labelable` marks the rows whose full 12-month forward window
sits inside the observation window — out-of-time work should filter on it.

---

## Generation pipeline

`src/generator/build.py generate()`, six stages, every stage vectorised as per-portfolio `(N, M)`
NumPy arrays rather than a per-account, per-month Python loop (SD-D1's whole point — the old
row-dict loop took 10-15 minutes at 45k×48; the vectorised version takes under 20 seconds,
enabling 15-20 tuning rounds a day instead of one):

1. **Population** (`portfolios.py`, `latent.draw_population`) — who exists: portfolio, constitution,
   sector, geography, vintage, ticket size, tenor, rate — every mix drawn from `sources.yaml`, then
   shrunk toward a uniform eight-way split (`book.mix_shrinkage_lambda = 0.60`) so every portfolio
   is thick enough to carry its own bootstrapped AUC (DR-06). Who eventually defaults, and when, is
   also decided here (`is_defaulter`, `npa_month`), against each portfolio's own sourced band.
2. **Shared latent stress** (`latent.build_stress_path`) — one `S_t` per account, an AR(1)/ramp
   process over the observation window; every portfolio's channels are a *slice of the same
   process*, which is the generative argument for "one model, eight portfolios" rather than eight
   independent simulators glued together.
3. **Channels** (`channels.py`) — the latent stress becomes what a bank can actually observe, per
   product: MSME-CC/TL move GST sales → utilisation → bounces → DPD; Housing moves salary-gap →
   balance-floor → EMI bounce → DPD; Education moves moratorium-end → stop → DPD; Agri moves
   harvest-miss → renewal-overdue → DPD; Retail-Unsecured moves EMI-stacking → min-balance →
   bounce; LAP moves LTV-drift/rental-dip → DPD; Auto moves commute-spend/salary-gap → DPD. A
   channel a portfolio does not carry is **NaN, never zero** (`channels.CHANNEL_COLUMNS`,
   enforced by `build._blank_absent_channels`) — a term loan simply has no GST channel to be zero
   on.
4. **Noise, silent defaulters, transient stress** (`noise.py`, SD-D4) — the master switch that
   keeps this data from being trivially separable. A per-portfolio share of defaulters arrives
   **silently** (no warning chain at all); of the rest, any given chain link is dark for about a
   quarter of them (`shared.chain_visibility.link_visibility = 0.72`); about a fifth of healthy
   accounts pass through a **transient stress episode** — a hard negative that moves the same
   instruments, part-pays, and for some, goes genuinely past due before curing; seasonal
   confounders (festival, quarter-end, monsoon, bonus) move healthy accounts in the SAME direction
   as stress; measurement noise (GST filing lag, drawing-power staleness, bureau refresh cycle,
   duplicate batches, payment reversals) sits on top. Switchable via `GeneratorConfig(noise=...)`
   — **the default is `True` and that is the shipped dataset.** `noise=False` exists only to
   reproduce the July 2026 fingerprint for the equivalence suite (§ "Known unrealisms", item 12).
5. **Labels** (`labels.py`) — `default_within_12m` (90+ DPD, 1-12 months forward, the graded
   label) and `sma2_within_6m` (61-90 DPD within 6 months, read off the simulated DPD series so it
   also catches curing hard negatives, not only eventual defaulters). Base rates are **asserted
   in-script** on every generation run, against the exact bands `sources.yaml` records
   (`labels.assert_base_rates`) — a generator that silently drifts out of its own pre-registered
   bands between tuning rounds fails loudly instead of shipping quietly wrong.
6. **Write** (`build.write`) — `pyarrow.csv.write_csv` with a `pandas.to_csv` fallback (the switch
   SD-D4/D5 made after `to_csv` alone cost 41 of the 60-second 45k×48 budget); this flips
   `inflow`/`gst_sales` to a one-decimal-place round trip on the pyarrow path, the one documented
   byte-level deviation from a pure `to_csv` write.

---

## Provenance legend

Every parameter node in `src/generator/sources.yaml` carries a `confidence` label, enforced by
`src/generator/sources.py:validate()` and pinned by `tests/test_sources_schema.py` so the document
cannot drift silently:

| Label | Meaning |
|---|---|
| `high` | A public figure, directly cited, that the generator reproduces (e.g. IDBI's own reported GNPA, gross advances, CIBIL's 300-900 score range). |
| `medium` | A public figure with a caveat on the read (e.g. a chart legend inferred rather than machine-readable, or a growth-rate press release whose absolute tables could not be parsed). |
| `low` | A real, cited statistic used as the anchor for a number that also requires an unverifiable inferential step (e.g. NPCI's NACH return-rate statistics, real and published, stepped into "share still unpaid at month end" — our judgement, not NPCI's). |
| `assumed` | No public figure exists (or none could be located in this lane's offline research) and the number is a documented modelling judgement. This is the honest majority position — see the census below — not a shortcut. |

Every node carries `source`, `url` (or the literal string `"none"`, which `sources.py` enforces
**if and only if** `confidence: assumed`), `retrieved_on`, and often a `note` explaining the
derivation. `assumed` never hides behind a decorative link, and a sourced number is never
published without one — both directions are asserted, not merely hoped for.

## Complete parameter table

Generated by `python3 src/data_card_params.py` from `src/generator/sources.yaml`.
Re-run it and paste the output here after any change to that file — this table is never
hand-edited, so it cannot drift from the file it describes. 328 nodes, grouped the way
`sources.yaml` groups them: `meta`, `book`, `shared`, then each of the eight portfolios
(a portfolio's own nodes only — its channel list, its ticket/tenor/rate bands, its
sourced default-rate band, its per-portfolio noise-share overrides; nodes it does not
override fall back to `shared.*`, not repeated here).

#### `meta`

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `meta.schema_version` | `'1.0.0'` | assumed | This file's own contract; bumped when a node's shape changes. | — |
| `meta.book_scope` | `'IDBI reported Retail segment, restricted to the eight DRISHTi portfolios'` | high | IDBI reports Retail (70% of gross advances) vs Corporate (30%). Its Retail line ALREADY contains Agriculture and MSME as sub-lines of Non-Structured Retail Advances, so for IDBI "Retail" is what other public-sector … | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `meta.mix_basis` | `'accounts'` | assumed | Banks publish the book by VALUE; the panel is one row per ACCOUNT-month. Account shares are therefore derived as (value share / mean ticket), renormalised — then shrunk toward a uniform mix (see … | — |

#### `book`

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `book.idbi_fy26.gross_advances_cr` | `259274` | high | IDBI Bank Investors Presentation, Q4 FY2025-26, Business Performance / Advances. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.idbi_fy26.retail_advances_cr` | `182294` | high | Structured Retail 107,712 cr + Non-Structured Retail 74,582 cr = 70% of gross advances; Corporate (Large 51,563 + Mid 25,417) is the other 30%. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.idbi_fy26.structured_retail_cr` | `{'housing': 75285, 'lap': 21968, 'auto_education_personal': 6787, 'others': 3672}` | high | IDBI Investors Presentation Q4 FY2025-26, Structured Retail Advances. The four lines sum exactly to the reported 107,712 cr. IDBI does NOT split Auto / Education / Personal — they are one combined line. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.idbi_fy26.non_structured_retail_cr` | `{'msme': 22826, 'gold': 21321, 'agri': 13589, 'bulk_business': 12649, 'other_retail': 4197}` | medium | IDBI Investors Presentation Q4 FY2025-26, Non-Structured Retail Advances. The five values sum exactly to the reported 74,582 cr, but the deck's chart carries no machine-readable legend, so the mapping of number to LABEL … | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.idbi_fy26.gnpa_pct` | `2.32` | high | IDBI Bank Q4 FY2025-26 results: GNPA 2.32%, NNPA 0.15%, PCR 99.39%. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.idbi_fy26.slippage_ratio_pct` | `0.63` | high | Annualised fresh-NPA (net basis) for FY26, down from 0.73% in FY25. SMA-to-standard-advances was 1.20% at Mar-26 (1.51% at Mar-25). | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.msme_cc_share_of_msme` | `0.55` | assumed | IDBI does not publish a cash-credit / term-loan split of its MSME book. 55/45 is the split the July 2026 DRISHTi build used and is retained so the two MSME portfolios stay comparable with it. | — |
| `book.auto_education_personal_split` | `{'auto': 0.45, 'education': 0.3, 'retail_unsecured': 0.25}` | assumed | IDBI reports Auto, Education and Personal as one 6,787 cr line. The split is our judgement: vehicle finance is the largest of the three at a public-sector bank, education next, and IDBI is not a large unsecured … | — |
| `book.annual_slippage_band` | `[0.03, 0.05]` | assumed | The whole book's 12-month label rate, pre-registered as criterion DR-03 in validation/criteria.yaml and as gate G2 in the build plan, both committed before any result existed. It lives here so the generator can ASSERT … | — |
| `book.sma2_to_npa_event_ratio_band` | `[1.0, 8.0]` | low | Plausible range for how much more OFTEN an account enters SMA-2 than it goes NPA, per unit of time. The two labels carry different windows (6 months and 12), so the raw rates are not comparable; the ratio asserted is … | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `book.mix_shrinkage_lambda` | `0.6` | assumed | Account shares are shrunk toward a uniform eight-way mix as (1 - lambda) * derived + lambda / 8. At lambda = 0.60 the thinnest portfolio carries 8.3% of accounts instead of 2.0%, which is what criterion DR-06 … | — |
| `book.rbi_sectoral_credit_growth_yoy_pct` | `{'non_food': 19.1, 'agriculture': 17.0, 'industry': 20.0, 'services': 22.9, 'personal_loans': 16.2}` | medium | RBI, Sectoral Deployment of Bank Credit, July 2026 (released 31-Aug-2026). The press release publishes growth rates in prose; the outstanding-amount tables are in a linked spreadsheet we could not parse, so no absolute … | <https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63478> |

#### `shared`

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `shared.regions` | `{'North': 0.24, 'South': 0.26, 'West': 0.28, 'East': 0.14, 'Central': 0.08}` | assumed | Inherited unchanged from the July 2026 build's MSME population so the two MSME portfolios reproduce their published distributions exactly. Broadly consistent with the West-and-South tilt of RBI's state credit data but … | — |
| `shared.states_within_region` | `{'North': {'Delhi': 0.405, 'Uttar Pradesh': 0.193, 'Rajasthan': 0.116, 'Haryana': 0.116, 'Punjab': 0.097, 'Uttarakhand': 0.031, 'Himachal...` | low | Ordering and relative weight follow RBI/BSR-linked state credit data: Maharashtra first, then Delhi, then Tamil Nadu; seven states (Maharashtra, Delhi, Tamil Nadu, Karnataka, Uttar Pradesh, West Bengal, Gujarat) hold … | <https://www.business-standard.com/economy/news/gujarat-leads-in-fy25-loan-growth-karnataka-in-deposits-shows-data-125121201390_1.html> |
| `shared.city_tiers` | `{'Rural': 0.08, 'Semi-Urban': 0.14, 'Urban': 0.23, 'Metropolitan': 0.55}` | assumed | The four levels are RBI's centre population groups (Rural under 10,000; Semi-Urban 10,000 to 1 lakh; Urban 1 to 10 lakh; Metropolitan 10 lakh and above, on Census 2011 population). The actual share of credit by … | — |
| `shared.constitutions` | `{'Individual': 0.04, 'Proprietorship': 0.7, 'Partnership': 0.08, 'PvtLtd': 0.13, 'LLP': 0.05}` | low | Udyam registration analysis puts proprietary concerns at 78-79.5% of registered MSMEs and partnerships at 6-7.9%. Bank CREDIT skews to larger constitutions than registrations do, so proprietorship is set below the … | <https://dcmsme.gov.in/> |
| `shared.sectors` | `{'Manufacturing': 0.22, 'Trading': 0.3, 'Services': 0.24, 'Retail': 0.16, 'Logistics': 0.08}` | assumed | Inherited unchanged from the July 2026 build's MSME population so the two MSME portfolios reproduce their published distributions exactly. Udyam data supports services outnumbering manufacturing, which this mix has … | — |
| `shared.sector_risk` | `{'Manufacturing': 1.05, 'Trading': 1.15, 'Services': 0.9, 'Retail': 1.1, 'Logistics': 1.2, 'Agriculture': 1.1, 'Salaried': 0.85}` | assumed | Relative risk multipliers. The five MSME values are the July 2026 build's; Agriculture and Salaried are new and set by judgement (salaried borrowers default less than self-employed ones at the same score). | — |
| `shared.nic_groups` | `{'Manufacturing': 'NIC 10-33 Manufacturing', 'Trading': 'NIC 46 Wholesale trade', 'Retail': 'NIC 47 Retail trade', 'Services': 'NIC 55-96...` | medium | National Industrial Classification 2008 division groups, the taxonomy Udyam registration and bank MSME reporting both use. `Salaried` is not an enterprise activity, so it maps to no NIC group and the column is null for … | <https://www.mospi.gov.in/classification/national-industrial-classification> |
| `shared.qualifications` | `{'Graduate': 0.45, 'UnderGrad': 0.3, 'Professional': 0.15, 'SchoolOnly': 0.1}` | assumed | Inherited unchanged from the July 2026 build's MSME population. | — |
| `shared.age_groups` | `{'<30': 0.12, '30-40': 0.34, '40-50': 0.3, '50-60': 0.17, '60+': 0.07}` | assumed | Inherited unchanged from the July 2026 build's MSME population. | — |
| `shared.business_age.shape` | `2.2` | assumed | Inherited from the July 2026 build: years-in-business ~ gamma(2.2, 3.0). | — |
| `shared.business_age.scale` | `3.0` | assumed | Inherited from the July 2026 build. | — |
| `shared.business_age.bounds` | `[0.0, 30.0]` | assumed | Inherited from the July 2026 build. | — |
| `shared.vintage_months_bounds` | `[0, 48]` | assumed | Months on book at panel start. Inherited from the July 2026 build; long tenor portfolios override it upward because a 20-year home-loan book genuinely carries older accounts. | — |
| `shared.bureau.missing_share` | `0.07` | assumed | Share of accounts with no bureau file. Matches the platform fixture's stated "~7% with no bureau file" (data/bank/SCHEMA.md), which the MAR-missingness work in SD-D4 and validation criterion DR-23 assume. | — |
| `shared.bureau.score_bounds` | `[300.0, 900.0]` | high | The CIBIL TransUnion score runs 300 to 900. | <https://www.cibil.com/faq/cibil-score> |
| `shared.bureau.score_mean` | `725.0` | assumed | Centre of the distribution for a sanctioned (already underwritten) book. | — |
| `shared.bureau.score_sd` | `62.0` | assumed | Spread chosen so about a tenth of a sanctioned book sits below 650. | — |
| `shared.bureau.risk_gain` | `30.0` | assumed | Points of bureau score lost per unit of latent risk z. Calibrated so a borrower two standard deviations riskier scores about 60 points lower — strong enough to matter, weak enough that the bureau file alone cannot carry … | — |
| `shared.bureau.stress_drop` | `55.0` | assumed | Points of bureau score lost at full latent stress, applied with a reporting lag (see bureau.report_lag_months). | — |
| `shared.bureau.report_lag_months` | `3` | assumed | Credit institutions report to bureaus monthly and the refreshed file reaches a lender later still; three months is the conservative end. | — |
| `shared.bureau.refresh_months` | `4` | assumed | SD-D4. A lender does not pull a bureau report every month on a performing account — a portfolio-monitoring pull is a paid enquiry, run on a cycle or on a trigger. Between pulls the bank carries the SCORE IT LAST SAW, so … | — |
| `shared.bureau.report_noise_sd` | `11.0` | assumed | SD-D4. Points of score movement between pulls that have nothing to do with this lender's account: a new enquiry, a card utilisation swing, a settled dispute, a different bureau's model version. | — |
| `shared.seasonality.kharif_harvest_months` | `[10, 11]` | medium | Kharif is sown with the south-west monsoon in June-July and harvested from September-October; mandi sale and the cash it raises land a few weeks later, so the credit-visible peak is October-November. | <https://agriwelfare.gov.in/en/Agricultural_Statistics_at_a_Glance> |
| `shared.seasonality.rabi_harvest_months` | `[4, 5, 6]` | medium | Rabi is sown October-November after the monsoon and harvested April to June under irrigation. KCC repayment and renewal conventionally align with harvest — rabi around April-June, kharif around September-November — … | <https://agriwelfare.gov.in/en/Agricultural_Statistics_at_a_Glance> |
| `shared.seasonality.harvest_receipt_multiple` | `3.2` | assumed | How much larger a harvest-month crop receipt is than the borrower's off-season monthly average. Agricultural income is lumpy; the multiple is judgement. | — |
| `shared.seasonality.off_season_floor` | `0.18` | assumed | Off-season receipts as a fraction of the borrower's monthly norm. | — |
| `shared.salary.credit_to_emi_multiple` | `3.1` | assumed | Monthly salary credit as a multiple of the EMI, i.e. a fixed-obligation-to-income ratio of about 32% at origination. | — |
| `shared.salary.multiple_sd` | `0.9` | assumed | Dispersion of the salary-to-EMI multiple across borrowers. | — |
| `shared.salary.multiple_bounds` | `[1.6, 9.0]` | assumed | Clipped so no sanctioned account starts below 1.6x EMI coverage. | — |
| `shared.salary.gap_threshold` | `0.6` | assumed | A salary credit below 60% of its own trailing six-month average counts as a salary gap — a missed, delayed or part-paid month. | — |
| `shared.balance.months_of_emi` | `1.35` | assumed | Average CASA balance expressed in months of EMI or interest demand. Indian retail borrowers hold thin buffers. | — |
| `shared.balance.months_of_emi_sd` | `0.7` | assumed | Dispersion of the balance buffer across borrowers. | — |
| `shared.balance.minimum_balance` | `3000.0` | assumed | Average-monthly-balance requirement on a public-sector savings account, typically 1,000 to 3,000 rupees outside premium variants; breaching it is the `minbal_breach` event for the salaried portfolios. | — |
| `shared.silent_default.definition` | `'a defaulter whose observation channels stay healthy until 1-2 months before NPA'` | assumed | Fraud and fund diversion, the death or hospitalisation of the earning member, the sudden loss of a single large buyer, a job loss with no notice: events that end an account's ability to pay without a preceding … | — |
| `shared.silent_default.share` | `0.08` | assumed | Book-wide share of defaulters with no usable warning chain. Set at the plan's 8%; the per-portfolio shares below are weighted to it. No public figure exists for the "no prior warning" share of slippages — banks publish … | — |
| `shared.silent_default.onset_months_bounds` | `[1, 2]` | assumed | How long the compressed slide lasts. 1 month is a true silent default (nothing moves before the payment stops); 2 is a fast one. Drawn uniformly, so the median silent defaulter's chain leads days-past-due by nothing at … | — |
| `shared.silent_default.severity_floor` | `1.15` | assumed | A silent default is steep by construction — the borrower stops, rather than slides — so its latent severity is floored above the population mean. It changes how hard the last two months look, never whether the account … | — |
| `shared.arrears.bounce_uncured_share` | `0.55` | low | Share of bounced instalments that are still unpaid at month end, and so leave the account days past due in the bank's own books. NPCI's NACH statistics show debit return rates of roughly a quarter to a third of … | <https://www.npci.org.in/what-we-do/nach/product-statistics> |
| `shared.arrears.benign_part_payment_rate` | `0.06` | assumed | SD-D4. Probability that a healthy month's collection falls short for a reason that is not distress: a part-payment, an insurance or fee debit that ate the standing instruction, a transfer initiated on the due date that … | — |
| `shared.arrears.spine_strength_bounds` | `[0.35, 1.65]` | assumed | SD-D4. How deeply a GIVEN defaulter's shortfall bites, as a multiple of the portfolio's collection elasticity — drawn per borrower and centred on 1, so the median defaulter part-pays exactly as deeply as before and the … | — |
| `shared.arrears.bounce_dpd_ladder` | `[0.0, 16.0, 43.0, 68.0]` | assumed | Days past due at month end after a run of one, two or three consecutive uncured instalment failures — SMA-0, SMA-1, SMA-2. The ladder is clipped at three: a performing account that has missed four consecutive … | — |
| `shared.chain_visibility.link_visibility` | `0.72` | assumed | Probability that a GIVEN link of a given defaulter's chain moves at all. The July 2026 panel — and SD-D3's eight-portfolio extension of it — had every defaulter showing EVERY link: turnover fell AND the limit crept up … | — |
| `shared.chain_visibility.link_strength_bounds` | `[0.55, 1.5]` | assumed | How hard a VISIBLE link responds, as a multiple of the portfolio's own elasticity. Drawn per account per channel, so two defaulters under the same latent stress deteriorate at different depths in different instruments. … | — |
| `shared.chain_visibility.unloaded_channels` | `['repayment', 'moratorium']` | assumed | Channels the visibility draw does NOT touch. Days-past-due, bounces and min-balance breaches are arithmetic consequences of money not arriving, not a separate instrument that can be dark; the education moratorium is a … | — |
| `shared.transient.length_months_bounds` | `[2, 8]` | assumed | Length of a recoverable stress episode on a healthy account: a delayed receivable, a hospital bill, a customer who paid two months late, a month between jobs. Drawn uniformly on [lo, hi). | — |
| `shared.transient.collection_shortfall_bounds` | `[0.12, 0.65]` | assumed | How much of the demand an account in a transient episode fails to pay. It overlaps the range a real defaulter's shortfall passes through, which is the point: a part-paid month does not tell you which of the two you are … | — |
| `shared.transient.arrears_share` | `0.3` | low | Share of transient episodes that go past due rather than merely thin. These are the accounts that cure: they reach SMA-1 or SMA-2 and come back. IDBI reported SMA-to-standard-advances of 1.20% at Mar-2026 against a … | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `shared.transient.arrears_ladder` | `[0.0, 22.0, 48.0, 58.0]` | assumed | Days past due by month inside an episode that goes into arrears. The account cures the month the episode ends — which is what makes these rows hard negatives rather than mislabelled positives. Capped below 90 so a cured … | — |
| `shared.transient.salary_miss_rate` | `0.28` | assumed | Probability a salaried borrower's credit is missed in a month of transient stress. | — |
| `shared.transient.income_multiple` | `0.7` | assumed | Multiplier on the portfolio's income instrument (salary, rent, crop receipt, commute spend) during an episode: the same direction a real slide moves, at a depth a real slide passes through. | — |
| `shared.transient.balance_multiple` | `0.55` | assumed | Multiplier on the CASA balance during an episode — the buffer is spent, then rebuilt. | — |
| `shared.transient.new_emi_rate` | `0.16` | assumed | Probability per episode-month that a borrower under transient stress takes another lender's instalment — the same behaviour a sliding borrower shows, on an account that recovers. | — |
| `shared.confounders.festival_months` | `[10, 11]` | low | Navratri-Dussehra-Diwali fall in the October-November window and carry the retail and trading year: sales, bonuses and household spending all peak, and none of it is stress. | <https://www.rbi.org.in/Scripts/AnnualReportPublications.aspx> |
| `shared.confounders.post_festival_months` | `[12, 1]` | assumed | The lull after the festival build-up: inventories are run down, the trade credit extended in October comes due, and turnover falls below its own six-month average without anything having gone wrong. | — |
| `shared.confounders.quarter_end_months` | `[3, 6, 9, 12]` | assumed | Indian financial quarters end in June, September, December and March. Collections are pushed and limits are dressed down at quarter end, March above all. | — |
| `shared.confounders.fiscal_year_start_months` | `[4]` | assumed | The Indian financial year starts in April; the quarter-end push reverses and turnover drops back. | — |
| `shared.confounders.monsoon_months` | `[7, 8]` | assumed | The south-west monsoon slows construction, logistics and discretionary travel across most of the country. | — |
| `shared.confounders.bonus_months` | `[4, 10]` | assumed | Annual increments and arrears land with the April payroll; the statutory bonus is customarily paid before Diwali. Both make a salary credit spike and then fall back, which reads as a salary gap two months later and is … | — |
| `shared.measurement.gst_report_lag_distribution` | `{0: 0.42, 1: 0.43, 2: 0.15}` | low | Months between a turnover month and the bank seeing it. GSTR-3B for a month is due the following month, and taxpayers under the QRMP scheme (turnover up to 5 crore, which is most of an MSME book) file quarterly and so … | <https://www.gst.gov.in/help/returns> |
| `shared.measurement.amount_rounding_rupees` | `10.0` | assumed | Demanded and collected amounts are reported to the rupee in core banking but reach a downstream mart rounded; rounding to the nearest ten removes the last digit of a signal that no analyst would trust. | — |
| `shared.measurement.duplicate_batch_rate` | `0.012` | assumed | Probability that a month's transaction count is inflated by a re-posted or double-counted batch. Duplicate postings are routine in statement feeds and are exactly the artefact a `txn_drop_flag` style rule mistakes for … | — |
| `shared.measurement.duplicate_batch_multiple_bounds` | `[1.3, 1.9]` | assumed | How much a duplicated batch inflates that month's transaction count. | — |
| `shared.measurement.payment_reversal_rate` | `0.045` | low | Probability that a month's collection is reversed and re-presented: an NACH mandate that failed on the due date, a cheque returned and cleared next month, a transfer that landed after the cut-off. NPCI's own monthly … | <https://www.npci.org.in/what-we-do/nach/product-statistics> |
| `shared.measurement.inflow_idiosyncratic_sd` | `0.22` | assumed | SD-D4. Log-scale month-to-month dispersion of a borrower's BANKED INFLOW that has nothing to do with distress. The July 2026 simulator gave a healthy account an AR(1) conduct wobble of about five percent, which … | — |
| `shared.measurement.utilisation_idiosyncratic_sd` | `0.17` | assumed | SD-D4. Log-scale month-to-month dispersion of drawn balance on a REVOLVING limit — cash credit, overdraft, KCC — outside any stress. A limit is drawn and swept as the operating cycle demands: a stock purchase takes it … | — |
| `shared.measurement.drawing_power_refresh_months` | `3` | assumed | SD-D4. A drawing power is recomputed from the borrower's stock and book-debt statement, which is submitted monthly in the sanction letter and quarterly in practice; between submissions the bank carries the last computed … | — |
| `shared.measurement.drawing_power_noise_sd` | `0.07` | assumed | SD-D4. Dispersion of a computed drawing power around the value the stock actually supports: valuations of inventory and of book debts are the borrower's own numbers, filed on the borrower's own schedule. | — |
| `shared.measurement.salary_idiosyncratic_sd` | `0.11` | assumed | Month-to-month variation in a salary credit that is nothing to do with distress: variable pay, overtime, reimbursements, a 31-day payroll. | — |
| `shared.measurement.salary_split_credit_rate` | `0.05` | assumed | Probability a month's pay arrives in two parts, or lands on the 1st of the next month — the credit the bank sees is short and the next one is long, with nothing wrong. | — |
| `shared.measurement.rental_idiosyncratic_sd` | `0.16` | assumed | Rent paid partly in cash, revised mid-tenancy, or netted against a repair. | — |
| `shared.measurement.rental_late_rate` | `0.12` | assumed | Probability a tenant pays late enough to land in the next month, so the landlord's account shows a blank month and then a double one. | — |
| `shared.measurement.harvest_yield_sd` | `0.34` | assumed | Log-scale dispersion of a farmer's crop-year receipt around their own norm: yield varies with rainfall and pests, and price varies with the mandi. Indian crop yields routinely move 20-40% year on year without a loan … | — |
| `shared.measurement.harvest_sale_slip_rate` | `0.22` | assumed | Probability that a crop year's sale, and the credit it raises, lands a month later than the calendar says — a delayed mandi arrival, a procurement queue, or produce held back for a better price. | — |
| `shared.measurement.commute_idiosyncratic_sd` | `0.38` | assumed | Fuel and toll spend on a card is one of the noisiest series a bank holds: it moves with travel, with paying cash at the pump, and with who in the household filled the tank. | — |
| `shared.measurement.commute_zero_month_rate` | `0.07` | assumed | Probability a month shows no card-visible fuel spend at all. | — |
| `shared.measurement.collateral_revaluation_months` | `12` | low | How often the carried collateral value is refreshed. RBI's IRAC norms require immovable property held as security to be valued at least once every three years for non-NPA accounts; lenders in practice refresh more often … | <https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx> |
| `shared.measurement.collateral_appraisal_error_sd` | `0.09` | assumed | Dispersion of a property or vehicle valuation around the value that would actually be realised. Two empanelled valuers on the same asset routinely differ by a tenth. | — |
| `shared.missingness.statement_gap_share` | `0.08` | assumed | Share of accounts with a gap in the statement feed somewhere in the window: a consent lapse on the account-aggregator side, a failed overnight pull, a customer who banks elsewhere for a while. The gap is drawn … | — |
| `shared.missingness.statement_gap_length_bounds` | `[1, 3]` | assumed | Length of one gap, in months; drawn uniformly on [lo, hi). | — |
| `shared.missingness.salary_channel_rule` | `'self-employed'` | assumed | Inside a portfolio that carries a salary channel, a borrower whose occupation is not Salaried has no salary credit to observe: a self-employed home-loan borrower is underwritten on ITRs and business banking, not on … | — |
| `shared.missingness.gst_channel_rule` | `'individual'` | assumed | Inside a portfolio that carries a GST channel, an Individual borrower files no return (see constitutions.CONSTITUTION_WITHOUT_GST). LAP is where this bites: about two in five LAP borrowers are individuals. | — |

#### `portfolios`

##### `msme_cc` (MSME-CC)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.msme_cc.contract_code` | `'MSME-CC'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.msme_cc.loan_type` | `'CashCredit'` | assumed | data/bank/fixture.json: all 20 MSME-CC records carry loan_type CashCredit. | — |
| `portfolios.msme_cc.value_share` | `0.0894` | medium | 12,554 cr of the 140,455 cr eight-portfolio universe: IDBI's MSME line (22,826 cr) at the 55% cash-credit split in book.msme_cc_share_of_msme. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.msme_cc.account_share_undistorted` | `0.0471` | assumed | value_share divided by the lognormal mean ticket, renormalised across the eight. | — |
| `portfolios.msme_cc.account_share` | `0.101` | assumed | The two MSME portfolios share one population and one ticket distribution, so shrinkage is applied to MSME as a SINGLE line (two of the eight uniform slots) and the result is then split by book.msme_cc_share_of_msme. … | — |
| `portfolios.msme_cc.annual_default_rate_band` | `[0.028, 0.045]` | medium | SIDBI-TransUnion CIBIL MSME Pulse balance-level delinquency by exposure band at Mar-2025: 5.8% for exposure up to 10 lakh and 2.9% for 10-50 lakh. This portfolio's median ticket (12 lakh) sits just above the boundary, … | <https://www.business-standard.com/industry/news/msme-loan-portfolio-s-delinquency-rate-down-to-two-year-low-of-2-3-report-124022800807_1.html> |
| `portfolios.msme_cc.risk_offset` | `0.0` | assumed | Calibration constant, in latent log-odds, solved so the realised 12-month label rate lands on the midpoint of the band above. MSME-CC is the reference portfolio and carries offset 0 by construction, which is what keeps … | — |
| `portfolios.msme_cc.ticket.log_mean` | `14.0` | assumed | Inherited from the July 2026 build: lognormal(14.0, 1.1), median about 12 lakh, mean about 22 lakh. Cross-checks well against the roughly 20 lakh average ticket reported for new MSME loans, though that figure is from … | — |
| `portfolios.msme_cc.ticket.log_sd` | `1.1` | assumed | Inherited from the July 2026 build. | — |
| `portfolios.msme_cc.ticket.bounds` | `[50000.0, 50000000.0]` | assumed | Inherited from the July 2026 build: 0.5 lakh to 5 crore. | — |
| `portfolios.msme_cc.tenor_months` | `[12, 12]` | assumed | A cash-credit limit is sanctioned for one year and renewed annually. The platform fixture carries tenor_months 12 on every MSME-CC record. | — |
| `portfolios.msme_cc.interest_rate_pa` | `[0.0855, 0.11]` | low | Public-sector-bank MSME working-capital / cash-credit rates quoted from about 8.55% upward, read from consumer rate-aggregator listings rather than from the banks' own rate cards. | <https://www.urbanmoney.com> |
| `portfolios.msme_cc.secured_share` | `0.75` | assumed | Collateral-free MSME lending is guaranteed under CGTMSE, so a minority of the book is unsecured. The platform fixture shows 15 of 20 MSME-CC records secured. | — |
| `portfolios.msme_cc.utilisation.base_mean` | `0.85` | assumed | SD-D8. The plan's own SD-D6 acceptance criterion for this portfolio is "CC util mode ~0.85"; without this override the generator ran MSME-CC on the shared book-wide default (0.52), which is a five- product average, not … | — |
| `portfolios.msme_cc.measurement.inflow_idiosyncratic_sd` | `0.26` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. A trading or manufacturing current account's turnover lands in clumps: one large invoice, a cheque instead of an NEFT, a partner's account taking … | — |
| `portfolios.msme_cc.measurement.utilisation_idiosyncratic_sd` | `0.17` | assumed | SD-D4, portfolio override. A cash-credit limit is drawn to the drawing power for a stock purchase and swept when the receivable clears; a fifth of the limit a month is normal. | — |
| `portfolios.msme_cc.noise.silent_default_share` | `0.07` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. Fund diversion and the sudden loss of a single large buyer are the classic no-warning cash-credit failures: the operating account looks normal … | — |
| `portfolios.msme_cc.noise.transient_stress_share` | `0.24` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. A working-capital account under a delayed receivable looks exactly like one under a … | — |
| `portfolios.msme_cc.noise.season_inflow_amplitude` | `0.17` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.msme_cc.noise.season_utilisation_amplitude` | `0.11` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.msme_cc.noise.season_salary_amplitude` | `0.0` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.msme_cc.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.msme_cc.channels` | `['utilisation', 'cash_flow', 'gst', 'transactions', 'repayment', 'adverse', 'drawing_power']` | assumed | What a bank can actually observe on a cash-credit account: the operating account turns over daily, GST returns are filed, and a drawing power is recomputed against stock-and-book-debt statements. | — |

##### `msme_tl` (MSME-TL)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.msme_tl.contract_code` | `'MSME-TL'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.msme_tl.loan_type` | `'TermLoan'` | assumed | data/bank/fixture.json: all 20 MSME-TL records carry loan_type TermLoan. | — |
| `portfolios.msme_tl.value_share` | `0.0731` | medium | 10,272 cr of the 140,455 cr universe: IDBI's MSME line at the 45% term-loan split. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.msme_tl.account_share_undistorted` | `0.0386` | assumed | value_share divided by the lognormal mean ticket, renormalised. | — |
| `portfolios.msme_tl.account_share` | `0.083` | assumed | The MSME line's shrunk account share, at the 45% term-loan split — see msme_cc.account_share. | — |
| `portfolios.msme_tl.annual_default_rate_band` | `[0.028, 0.045]` | medium | Same MSME delinquency evidence as MSME-CC. | <https://www.business-standard.com/industry/news/msme-loan-portfolio-s-delinquency-rate-down-to-two-year-low-of-2-3-report-124022800807_1.html> |
| `portfolios.msme_tl.risk_offset` | `0.0` | assumed | Calibration constant; MSME-TL shares MSME-CC's credit risk in the July build. | — |
| `portfolios.msme_tl.ticket.log_mean` | `14.0` | assumed | Inherited from the July 2026 build. | — |
| `portfolios.msme_tl.ticket.log_sd` | `1.1` | assumed | Inherited from the July 2026 build. | — |
| `portfolios.msme_tl.ticket.bounds` | `[50000.0, 50000000.0]` | assumed | Inherited from the July 2026 build. | — |
| `portfolios.msme_tl.tenor_months` | `[36, 120]` | assumed | MSME term loans typically run three to ten years. No public tenor distribution was located, so the range is ours. | — |
| `portfolios.msme_tl.interest_rate_pa` | `[0.091, 0.1155]` | low | SBI MSME term-loan rates of roughly 9.10-11.55% (MCLR / EBLR linked), read from consumer rate-aggregator listings rather than the bank's own rate card. | <https://www.urbanmoney.com> |
| `portfolios.msme_tl.secured_share` | `0.55` | assumed | The platform fixture shows 11 of 20 MSME-TL records secured. | — |
| `portfolios.msme_tl.measurement.inflow_idiosyncratic_sd` | `0.26` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. Same borrowers as the cash-credit book, same lumpy turnover. | — |
| `portfolios.msme_tl.measurement.utilisation_idiosyncratic_sd` | `0.06` | assumed | SD-D4, portfolio override. A term loan has nothing to draw: its 'utilisation' is outstanding over sanction, which moves with amortisation and arrears, not with the operating cycle. Almost all of the July build's … | — |
| `portfolios.msme_tl.noise.silent_default_share` | `0.07` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. Same causes as the cash-credit book; a term loan simply shows them one link later. The eight shares are weighted by account_share to the book-wide … | — |
| `portfolios.msme_tl.noise.transient_stress_share` | `0.22` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. A part-paid instalment on a term loan is a common and usually recoverable event. The … | — |
| `portfolios.msme_tl.noise.season_inflow_amplitude` | `0.16` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.msme_tl.noise.season_utilisation_amplitude` | `0.08` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.msme_tl.noise.season_salary_amplitude` | `0.0` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.msme_tl.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.msme_tl.channels` | `['utilisation', 'cash_flow', 'gst', 'transactions', 'repayment', 'adverse']` | assumed | A term loan has no drawing power. Its `utilisation` is the outstanding-to-sanction ratio a bank still watches. | — |

##### `housing` (Housing)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.housing.contract_code` | `'Housing'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.housing.loan_type` | `'TermLoan'` | assumed | data/bank/fixture.json. | — |
| `portfolios.housing.value_share` | `0.536` | high | 75,285 cr of the 140,455 cr universe. Housing is over half of IDBI's structured retail book by rupees and the single largest line in it. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.housing.account_share_undistorted` | `0.1835` | assumed | value_share divided by the lognormal mean ticket, renormalised. | — |
| `portfolios.housing.account_share` | `0.148` | assumed | account_share_undistorted shrunk toward uniform at book.mix_shrinkage_lambda. | — |
| `portfolios.housing.annual_default_rate_band` | `[0.008, 0.016]` | low | RBI sectoral GNPA at Mar-2025 puts the whole Personal Loans bucket (housing + vehicle + education + other retail) at 1.20%, while the unsecured slice inside it runs 1.8%. Secured housing therefore sits below 1.2%; a … | <https://www.outlookmoney.com/banking/loan/agriculture-sector-records-highest-bad-loans-at-610-per-cent-says-rbi-report> |
| `portfolios.housing.risk_offset` | `-1.652` | assumed | Calibration constant in latent log-odds; see msme_cc.risk_offset. | — |
| `portfolios.housing.ticket.log_mean` | `14.845` | low | Median about 28 lakh, mean about 34 lakh. Industry reporting puts the FY25 average home-loan ticket at 70-76 lakh, but that sample skews to metropolitan and private-lender borrowers; a public-sector retail book sits … | <https://www.business-standard.com/industry/news/home-loan-volume-and-value-see-double-digit-growth-in-fy25-report-125060300462_1.html> |
| `portfolios.housing.ticket.log_sd` | `0.62` | assumed | Home-loan tickets are far less dispersed than MSME limits. | — |
| `portfolios.housing.ticket.bounds` | `[300000.0, 150000000.0]` | assumed | 3 lakh to 15 crore. | — |
| `portfolios.housing.tenor_months` | `[120, 300]` | assumed | Home loans are written for ten to twenty-five years. No public tenor distribution located. | — |
| `portfolios.housing.interest_rate_pa` | `[0.0725, 0.09]` | low | SBI home-loan card rates of 7.25-8.45% and PNB from 8.15%, read from consumer rate-aggregator listings in September 2026 rather than from the banks' own rate cards. | <https://www.urbanmoney.com> |
| `portfolios.housing.secured_share` | `1.0` | assumed | A home loan is secured on the property by definition. | — |
| `portfolios.housing.vintage_months_bounds` | `[0, 120]` | assumed | A twenty-year book carries far older accounts than a working-capital book, so months-on-book at panel start runs to ten years. | — |
| `portfolios.housing.constitutions` | `{'Individual': 1.0}` | assumed | Retail home loans are written to individuals. The platform fixture's 20 Housing records are all Individual. | — |
| `portfolios.housing.sectors` | `{'Salaried': 0.72, 'Services': 0.1, 'Trading': 0.08, 'Retail': 0.05, 'Manufacturing': 0.04, 'Logistics': 0.01}` | assumed | Occupation of the borrower; home loans skew heavily salaried. | — |
| `portfolios.housing.regions` | `{'North': 0.22, 'South': 0.32, 'West': 0.3, 'East': 0.1, 'Central': 0.06}` | assumed | Housing credit concentrates in the western and southern metros. | — |
| `portfolios.housing.city_tiers` | `{'Rural': 0.04, 'Semi-Urban': 0.16, 'Urban': 0.28, 'Metropolitan': 0.52}` | assumed | Home-loan demand is metropolitan and urban. | — |
| `portfolios.housing.age_groups` | `{'<30': 0.14, '30-40': 0.4, '40-50': 0.28, '50-60': 0.14, '60+': 0.04}` | assumed | First home purchase clusters in the thirties. | — |
| `portfolios.housing.measurement.inflow_idiosyncratic_sd` | `0.15` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. A salaried household's account turnover is steadier than a business's, but not steady: rent, school fees, a festival month, a medical bill. | — |
| `portfolios.housing.measurement.utilisation_idiosyncratic_sd` | `0.0` | assumed | SD-D4, portfolio override: this portfolio has no revolving limit, so there is nothing to draw and nothing to sweep. | — |
| `portfolios.housing.noise.silent_default_share` | `0.06` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. The lowest of the eight. A mortgage borrower defends the roof over their head longest, so a housing default almost always has a visible run-up; … | — |
| `portfolios.housing.noise.transient_stress_share` | `0.16` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. A month between jobs, or a single missed payroll, on a book where the borrower then … | — |
| `portfolios.housing.noise.season_inflow_amplitude` | `0.07` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.housing.noise.season_utilisation_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.housing.noise.season_salary_amplitude` | `0.22` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.housing.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.housing.channels` | `['cash_flow', 'transactions', 'repayment', 'salary', 'ltv']` | assumed | A salaried home-loan borrower files no GST return and has no credit limit to utilise. What the bank sees is the salary credit into the CASA account, the balance it maintains, the EMI presentation, and the loan-to-value … | — |
| `portfolios.housing.ltv.origination` | `0.74` | low | Loan-to-value at sanction. RBI caps housing LTV at 90% for loans up to 30 lakh, 80% up to 75 lakh and 75% above; banks originate below the cap. | <https://www.rbi.org.in/Scripts/BS_ViewMasCirculardetails.aspx> |
| `portfolios.housing.ltv.origination_sd` | `0.08` | assumed | Dispersion of LTV at sanction. | — |
| `portfolios.housing.ltv.collateral_drift_pa` | `0.045` | assumed | Residential property price growth, annualised, applied to the collateral value. | — |

##### `education` (Education)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.education.contract_code` | `'Education'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.education.loan_type` | `'TermLoan'` | assumed | data/bank/fixture.json. | — |
| `portfolios.education.value_share` | `0.0145` | low | 2,036 cr of the 140,455 cr universe: 30% of IDBI's combined Auto/Education/Personal line of 6,787 cr (see book.auto_education_personal_split — the split itself is ours). | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.education.account_share_undistorted` | `0.0196` | assumed | value_share divided by the lognormal mean ticket, renormalised. | — |
| `portfolios.education.account_share` | `0.083` | assumed | account_share_undistorted shrunk toward uniform at book.mix_shrinkage_lambda. This is the portfolio the shrinkage exists for: 2.0% of accounts would not support a per-portfolio AUC with a CI. | — |
| `portfolios.education.annual_default_rate_band` | `[0.015, 0.04]` | high | Education-loan NPA at public-sector banks fell from about 7% in FY21 to about 2% in FY25 (Minister of State for Finance, Lok Sabha reply, Dec-2025). The band is centred a little above the FY25 level to keep the … | <https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=2204268> |
| `portfolios.education.risk_offset` | `0.036` | assumed | Calibration constant in latent log-odds; see msme_cc.risk_offset. | — |
| `portfolios.education.ticket.log_mean` | `13.3` | assumed | Median about 6 lakh. Most domestic education loans sit under the 7.5 lakh collateral-free threshold; overseas loans average far higher (about 38 lakh market-wide, from a study-abroad industry source we rate as weak), … | — |
| `portfolios.education.ticket.log_sd` | `0.85` | assumed | Wide, because a domestic engineering degree and an overseas master's sit in the same portfolio. | — |
| `portfolios.education.ticket.bounds` | `[50000.0, 50000000.0]` | assumed | 0.5 lakh to 5 crore. | — |
| `portfolios.education.tenor_months` | `[60, 180]` | assumed | Education loans run five to fifteen years after the moratorium. No public distribution located. | — |
| `portfolios.education.interest_rate_pa` | `[0.085, 0.11]` | assumed | Public-sector-bank education-loan rates. No rate card was verified for this product. | — |
| `portfolios.education.secured_share` | `0.18` | assumed | Education loans up to 7.5 lakh are collateral-free under the Credit Guarantee Fund Scheme for Education Loans, and most tickets sit below it. | — |
| `portfolios.education.vintage_months_bounds` | `[0, 84]` | assumed | The book carries accounts still inside their course moratorium and ones years into repayment. | — |
| `portfolios.education.constitutions` | `{'Individual': 1.0}` | assumed | Education loans are written to the student, with a co-applicant. | — |
| `portfolios.education.sectors` | `{'Salaried': 0.88, 'Services': 0.05, 'Trading': 0.04, 'Retail': 0.02, 'Manufacturing': 0.01}` | assumed | Occupation of the co-applicant, and of the borrower after the course. | — |
| `portfolios.education.regions` | `{'North': 0.2, 'South': 0.38, 'West': 0.2, 'East': 0.14, 'Central': 0.08}` | assumed | Education-loan volumes concentrate in the southern states. | — |
| `portfolios.education.city_tiers` | `{'Rural': 0.1, 'Semi-Urban': 0.24, 'Urban': 0.32, 'Metropolitan': 0.34}` | assumed | Education borrowers are drawn from a much wider geography than home-loan borrowers. | — |
| `portfolios.education.age_groups` | `{'<30': 0.62, '30-40': 0.24, '40-50': 0.09, '50-60': 0.04, '60+': 0.01}` | assumed | The borrower is a student or a recent graduate. | — |
| `portfolios.education.measurement.inflow_idiosyncratic_sd` | `0.15` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. A household account, often the parent's, during and after the course. | — |
| `portfolios.education.measurement.utilisation_idiosyncratic_sd` | `0.0` | assumed | SD-D4, portfolio override: this portfolio has no revolving limit, so there is nothing to draw and nothing to sweep. | — |
| `portfolios.education.noise.silent_default_share` | `0.1` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. High: the borrower's income starts only at the end of the moratorium and the bank often has no salary account for a graduate who has moved city or … | — |
| `portfolios.education.noise.transient_stress_share` | `0.2` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. A graduate between the first two jobs, or a family bridging the first few instalments, … | — |
| `portfolios.education.noise.season_inflow_amplitude` | `0.06` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.education.noise.season_utilisation_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.education.noise.season_salary_amplitude` | `0.2` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.education.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.education.channels` | `['cash_flow', 'transactions', 'repayment', 'salary', 'moratorium']` | assumed | The defining observable is the moratorium: no EMI is demanded during the course and for a grace period after it, and the first months of real demand are when the portfolio breaks. | — |
| `portfolios.education.moratorium.end_month_bounds` | `[-36, 30]` | assumed | Moratorium end relative to panel month 0, spanning a book in which some accounts are years into repayment and others have not been asked for a rupee yet. Negative means the account was already repaying before the panel … | — |
| `portfolios.education.moratorium.post_end_stress_months` | `9` | assumed | How long after moratorium end the elevated stop-paying hazard persists. | — |

##### `agri` (Agri)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.agri.contract_code` | `'Agri'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.agri.loan_type` | `'CashCredit'` | assumed | A Kisan Credit Card is a revolving cash-credit facility; the platform fixture carries loan_type CashCredit on all 20 Agri records. | — |
| `portfolios.agri.value_share` | `0.0967` | medium | 13,589 cr of the 140,455 cr universe: IDBI's Agri line in Non-Structured Retail. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.agri.account_share_undistorted` | `0.559` | assumed | value_share divided by the lognormal mean ticket, renormalised. Agriculture is under a tenth of the book by RUPEES and more than half of it by ACCOUNTS, because KCC tickets are two orders of magnitude smaller than a … | — |
| `portfolios.agri.account_share` | `0.3` | assumed | account_share_undistorted shrunk toward uniform at book.mix_shrinkage_lambda. Even after shrinkage agri is the largest portfolio by account count, which is correct for a public-sector bank. | — |
| `portfolios.agri.annual_default_rate_band` | `[0.045, 0.08]` | medium | Agriculture carries the highest GNPA of any major sector for scheduled commercial banks — 6.10% at Mar-2025, against a system average of 2.30% — and about a third of all bank GNPA by value. | <https://www.outlookmoney.com/banking/loan/agriculture-sector-records-highest-bad-loans-at-610-per-cent-says-rbi-report> |
| `portfolios.agri.risk_offset` | `1.157` | assumed | Calibration constant in latent log-odds; see msme_cc.risk_offset. | — |
| `portfolios.agri.ticket.log_mean` | `11.85` | assumed | Median KCC limit about 1.4 lakh, mean about 2 lakh. No published average KCC ticket could be located; the level is anchored on the policy limits instead — collateral-free agricultural lending was raised to 2 lakh with … | — |
| `portfolios.agri.ticket.log_sd` | `0.85` | assumed | KCC limits scale with land holding, which is highly skewed. | — |
| `portfolios.agri.ticket.bounds` | `[10000.0, 20000000.0]` | assumed | 10 thousand to 2 crore. | — |
| `portfolios.agri.tenor_months` | `[12, 12]` | assumed | A KCC limit is sanctioned for a crop year and reviewed annually (the card itself is valid five years, extendable). | — |
| `portfolios.agri.interest_rate_pa` | `[0.04, 0.07]` | medium | Short-term crop loans carry a concessional 7% rate under interest subvention, reduced to an effective 4% on prompt repayment; the subvention cap is 3 lakh and was announced as moving to 5 lakh. | <https://www.tribuneindia.com/news/business/kisan-credit-card-interest-subvention-scheme-limit-to-be-raised-to-rs-5-lakh-sitharaman> |
| `portfolios.agri.secured_share` | `0.35` | medium | RBI raised the collateral-free agricultural lending limit from 1.60 lakh to 2.00 lakh per borrower with effect from 1-Jan-2025, and most KCC limits sit below it, so the majority of the book is unsecured. | <https://www.tribuneindia.com/news/business/kisan-credit-card-interest-subvention-scheme-limit-to-be-raised-to-rs-5-lakh-sitharaman> |
| `portfolios.agri.vintage_months_bounds` | `[0, 36]` | assumed | KCC limits are reviewed annually; the book is young. | — |
| `portfolios.agri.constitutions` | `{'Individual': 0.88, 'Proprietorship': 0.1, 'Partnership': 0.02}` | assumed | KCC borrowers are individual farmers — about 7.7 crore of them nationally. NOTE: the platform fixture gives its Agri records business constitutions, which is not realistic; the fixture is a fabricated offline stand-in … | — |
| `portfolios.agri.sectors` | `{'Agriculture': 1.0}` | assumed | By definition. | — |
| `portfolios.agri.regions` | `{'North': 0.26, 'South': 0.24, 'West': 0.18, 'East': 0.2, 'Central': 0.12}` | assumed | Agricultural credit is far less metropolitan-concentrated than the rest of the book. | — |
| `portfolios.agri.city_tiers` | `{'Rural': 0.72, 'Semi-Urban': 0.22, 'Urban': 0.05, 'Metropolitan': 0.01}` | assumed | KCC is a rural and semi-urban product. | — |
| `portfolios.agri.measurement.inflow_idiosyncratic_sd` | `0.16` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. On top of the crop-year yield factor, which already carries most of a farmer's year-to-year swing. | — |
| `portfolios.agri.measurement.utilisation_idiosyncratic_sd` | `0.2` | assumed | SD-D4, portfolio override. A KCC limit is drawn at sowing and repaid out of the harvest, so the drawn balance swings with the crop calendar as well as with the borrower. | — |
| `portfolios.agri.noise.silent_default_share` | `0.07` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. A crop failure is visible; a death in the family, a medical emergency or an uninsured livestock loss is not. The eight shares are weighted by … | — |
| `portfolios.agri.noise.transient_stress_share` | `0.26` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. The highest of the eight: a single weak season, a delayed procurement payment or a late … | — |
| `portfolios.agri.noise.season_inflow_amplitude` | `0.35` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.agri.noise.season_utilisation_amplitude` | `0.1` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.agri.noise.season_salary_amplitude` | `0.0` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.agri.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.agri.channels` | `['utilisation', 'cash_flow', 'transactions', 'repayment', 'drawing_power', 'harvest']` | assumed | A KCC account is observed through seasonal crop receipts, the limit it draws against, and whether it is renewed on time after the crop year. There is no GST return and no salary credit. | — |
| `portfolios.agri.harvest.renewal_month` | `12` | assumed | Months between KCC reviews. | — |
| `portfolios.agri.harvest.benign_slip_rate` | `0.07` | assumed | SD-D4. Probability that a KCC renewal that falls due is not completed on time for reasons that have nothing to do with the borrower's repayment capacity: documentation, a land-record or no-dues certificate that has not … | — |
| `portfolios.agri.harvest.miss_depth` | `0.62` | assumed | Fraction by which harvest receipts fall at full latent stress — a crop failure, a price collapse, or an unsold harvest. | — |

##### `retail_unsecured` (Retail-Unsecured)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.retail_unsecured.contract_code` | `'Retail-Unsecured'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.retail_unsecured.loan_type` | `'TermLoan'` | assumed | data/bank/fixture.json. | — |
| `portfolios.retail_unsecured.value_share` | `0.0121` | low | 1,697 cr of the 140,455 cr universe: 25% of IDBI's combined Auto/Education/Personal line (see book.auto_education_personal_split). | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.retail_unsecured.account_share_undistorted` | `0.0509` | assumed | value_share divided by the lognormal mean ticket, renormalised. | — |
| `portfolios.retail_unsecured.account_share` | `0.095` | assumed | account_share_undistorted shrunk toward uniform at book.mix_shrinkage_lambda. | — |
| `portfolios.retail_unsecured.annual_default_rate_band` | `[0.014, 0.032]` | medium | RBI's Financial Stability Report (June 2025) puts unsecured retail GNPA at about 1.8%, against 1.1% for retail overall; unsecured products now account for over half of all retail slippages. The band brackets 1.8% on the … | <https://rbidocs.rbi.org.in/rdocs/PublicationReport/Pdfs/0FSRJUNE20253006258AE798B4484642AD861CC35BC2CB3D8E.PDF> |
| `portfolios.retail_unsecured.risk_offset` | `-0.641` | assumed | Calibration constant in latent log-odds; see msme_cc.risk_offset. | — |
| `portfolios.retail_unsecured.ticket.log_mean` | `12.206` | assumed | Median about 2 lakh, mean about 2.75 lakh. The only sourced figures we found were CRIF's FY21 and FY22 averages (1.25 lakh falling to 83,000) which cover all lenders including small-ticket digital lending; a … | — |
| `portfolios.retail_unsecured.ticket.log_sd` | `0.8` | assumed | Dispersion of personal-loan tickets. | — |
| `portfolios.retail_unsecured.ticket.bounds` | `[20000.0, 4000000.0]` | assumed | 20 thousand to 40 lakh. | — |
| `portfolios.retail_unsecured.tenor_months` | `[12, 60]` | assumed | Personal loans run one to five years. No public distribution located. | — |
| `portfolios.retail_unsecured.interest_rate_pa` | `[0.1, 0.15]` | low | SBI personal-loan rates of roughly 10-15%, read from consumer rate-aggregator listings rather than the bank's own rate card. | <https://www.urbanmoney.com> |
| `portfolios.retail_unsecured.secured_share` | `0.0` | assumed | Unsecured by definition. | — |
| `portfolios.retail_unsecured.vintage_months_bounds` | `[0, 36]` | assumed | A short-tenor book carries young accounts. | — |
| `portfolios.retail_unsecured.constitutions` | `{'Individual': 1.0}` | assumed | Personal loans are written to individuals. | — |
| `portfolios.retail_unsecured.sectors` | `{'Salaried': 0.85, 'Services': 0.06, 'Trading': 0.05, 'Retail': 0.03, 'Logistics': 0.01}` | assumed | Public-sector-bank personal loans are predominantly a salaried product. | — |
| `portfolios.retail_unsecured.city_tiers` | `{'Rural': 0.06, 'Semi-Urban': 0.16, 'Urban': 0.3, 'Metropolitan': 0.48}` | assumed | Unsecured retail credit is urban and metropolitan. | — |
| `portfolios.retail_unsecured.age_groups` | `{'<30': 0.26, '30-40': 0.38, '40-50': 0.22, '50-60': 0.11, '60+': 0.03}` | assumed | Personal-loan borrowers are younger than the mortgage book. | — |
| `portfolios.retail_unsecured.measurement.inflow_idiosyncratic_sd` | `0.15` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. A salaried household account. | — |
| `portfolios.retail_unsecured.measurement.utilisation_idiosyncratic_sd` | `0.0` | assumed | SD-D4, portfolio override: this portfolio has no revolving limit, so there is nothing to draw and nothing to sweep. | — |
| `portfolios.retail_unsecured.noise.silent_default_share` | `0.12` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. The highest of the eight. There is no collateral to defend and no operating account to watch: a borrower who loses a job or decides to walk away … | — |
| `portfolios.retail_unsecured.noise.transient_stress_share` | `0.26` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. Thin buffers and stacked instalments mean a large share of this book passes through … | — |
| `portfolios.retail_unsecured.noise.season_inflow_amplitude` | `0.08` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.retail_unsecured.noise.season_utilisation_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.retail_unsecured.noise.season_salary_amplitude` | `0.22` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.retail_unsecured.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.retail_unsecured.channels` | `['cash_flow', 'transactions', 'repayment', 'salary', 'emi_stacking']` | assumed | The distinguishing observable is EMI stacking — other lenders' EMIs visible in account-aggregator narrations. A borrower servicing four other loans out of one salary is the population that breaks. | — |
| `portfolios.retail_unsecured.emi_stacking.other_emi_count_lambda` | `1.3` | assumed | Mean number of OTHER lenders' EMIs visible in the borrower's account narrations at origination (Poisson). | — |
| `portfolios.retail_unsecured.emi_stacking.other_emi_share_of_own` | `0.55` | assumed | Size of a typical other-bank EMI as a fraction of our own EMI. | — |
| `portfolios.retail_unsecured.emi_stacking.stress_new_emi_rate` | `0.22` | assumed | Monthly probability of taking on ANOTHER lender's EMI while under latent stress — borrowing to service borrowing, the classic tell. | — |
| `portfolios.retail_unsecured.emi_stacking.burden_breach` | `0.55` | assumed | Total fixed obligations above 55% of monthly income is the level at which a bank's own early-warning rules flag over-leverage. | — |

##### `lap` (LAP)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.lap.contract_code` | `'LAP'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.lap.loan_type` | `'TermLoan'` | assumed | data/bank/fixture.json. | — |
| `portfolios.lap.value_share` | `0.1564` | high | 21,968 cr of the 140,455 cr universe. LAP is IDBI's second-largest structured retail line after housing. | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.lap.account_share_undistorted` | `0.0706` | assumed | value_share divided by the lognormal mean ticket, renormalised. | — |
| `portfolios.lap.account_share` | `0.103` | assumed | account_share_undistorted shrunk toward uniform at book.mix_shrinkage_lambda. | — |
| `portfolios.lap.annual_default_rate_band` | `[0.018, 0.038]` | assumed | No public LAP delinquency figure could be located. The band is reasoned: LAP is secured like housing (about 1.0%) but written to self-employed borrowers with lumpier income, which puts it nearer the MSME level (about … | — |
| `portfolios.lap.risk_offset` | `-0.468` | assumed | Calibration constant in latent log-odds; see msme_cc.risk_offset. | — |
| `portfolios.lap.ticket.log_mean` | `14.4` | assumed | Median about 18 lakh, mean about 26 lakh. No published average LAP ticket could be located; the level is set between the housing and MSME books, which is where LAP sits in IDBI's own structured-retail line. | — |
| `portfolios.lap.ticket.log_sd` | `0.85` | assumed | Dispersion of LAP tickets. | — |
| `portfolios.lap.ticket.bounds` | `[200000.0, 100000000.0]` | assumed | 2 lakh to 10 crore. | — |
| `portfolios.lap.tenor_months` | `[60, 180]` | assumed | LAP runs five to fifteen years. No public distribution located. | — |
| `portfolios.lap.interest_rate_pa` | `[0.092, 0.105]` | low | SBI loan-against-property rates of 9.20-10.50%, read from consumer rate-aggregator listings rather than the bank's own rate card. | <https://www.urbanmoney.com> |
| `portfolios.lap.secured_share` | `1.0` | assumed | Secured on the mortgaged property by definition. | — |
| `portfolios.lap.vintage_months_bounds` | `[0, 84]` | assumed | A ten-year book carries accounts up to seven years old at panel start. | — |
| `portfolios.lap.constitutions` | `{'Individual': 0.42, 'Proprietorship': 0.3, 'Partnership': 0.12, 'PvtLtd': 0.1, 'LLP': 0.06}` | assumed | LAP is largely a self-employed product: the borrower is often an individual mortgaging property to fund a business. This is the portfolio where the constitution axis actually bites, because Individual borrowers file no … | — |
| `portfolios.lap.sectors` | `{'Trading': 0.28, 'Services': 0.26, 'Manufacturing': 0.18, 'Retail': 0.14, 'Salaried': 0.1, 'Logistics': 0.04}` | assumed | Activity of the self-employed LAP borrower. | — |
| `portfolios.lap.regions` | `{'North': 0.24, 'South': 0.24, 'West': 0.34, 'East': 0.1, 'Central': 0.08}` | assumed | LAP concentrates in the western metros. | — |
| `portfolios.lap.city_tiers` | `{'Rural': 0.03, 'Semi-Urban': 0.15, 'Urban': 0.3, 'Metropolitan': 0.52}` | assumed | Property values make LAP an urban product. | — |
| `portfolios.lap.measurement.inflow_idiosyncratic_sd` | `0.24` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. A business-owner borrower's account, with rent on top of trading receipts. | — |
| `portfolios.lap.measurement.utilisation_idiosyncratic_sd` | `0.0` | assumed | SD-D4, portfolio override: this portfolio has no revolving limit, so there is nothing to draw and nothing to sweep. | — |
| `portfolios.lap.noise.silent_default_share` | `0.07` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. Between the MSME and housing books: business-owner borrowers with a property at stake, so mostly visible failures, with fraud and death the … | — |
| `portfolios.lap.noise.transient_stress_share` | `0.2` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. A vacant tenancy or a slow business quarter, cleared once the property is re-let. The … | — |
| `portfolios.lap.noise.season_inflow_amplitude` | `0.13` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.lap.noise.season_utilisation_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.lap.noise.season_salary_amplitude` | `0.0` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.lap.noise.season_commute_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.lap.channels` | `['cash_flow', 'gst', 'transactions', 'repayment', 'adverse', 'ltv', 'rental']` | assumed | The two LAP-specific observables are the loan-to-value of the mortgaged property and the rental income it throws off. A LAP borrower whose tenant leaves and whose collateral value slips is the population that breaks. | — |
| `portfolios.lap.ltv.origination` | `0.58` | assumed | Lenders originate LAP at a lower LTV than housing because the collateral is harder to sell. | — |
| `portfolios.lap.ltv.origination_sd` | `0.1` | assumed | Dispersion of LAP LTV at sanction. | — |
| `portfolios.lap.ltv.collateral_drift_pa` | `0.03` | assumed | Commercial and mixed-use property appreciates more slowly than residential. | — |
| `portfolios.lap.rental.share_of_emi` | `0.85` | assumed | Rental income from the mortgaged property as a multiple of the EMI at origination. | — |
| `portfolios.lap.rental.share_sd` | `0.35` | assumed | Dispersion of the rental-to-EMI ratio. | — |
| `portfolios.lap.rental.vacancy_rate` | `0.05` | assumed | Baseline monthly probability that the property is vacant and no rent is credited. | — |

##### `auto` (Auto)

| Path | Value | Confidence | Source | URL |
|---|---|---|---|---|
| `portfolios.auto.contract_code` | `'Auto'` | assumed | Portfolio enum in data/bank/SCHEMA.md and data/bank/fixture.json. | — |
| `portfolios.auto.loan_type` | `'TermLoan'` | assumed | data/bank/fixture.json. | — |
| `portfolios.auto.value_share` | `0.0217` | low | 3,054 cr of the 140,455 cr universe: 45% of IDBI's combined Auto/Education/Personal line (see book.auto_education_personal_split). | <https://www.idbi.bank.in/pdf/Analyst_Mar-2026.pdf> |
| `portfolios.auto.account_share_undistorted` | `0.0307` | assumed | value_share divided by the lognormal mean ticket, renormalised. | — |
| `portfolios.auto.account_share` | `0.087` | assumed | account_share_undistorted shrunk toward uniform at book.mix_shrinkage_lambda. | — |
| `portfolios.auto.annual_default_rate_band` | `[0.01, 0.026]` | assumed | No public vehicle-loan GNPA figure could be located. The band is reasoned: the asset is hypothecated and repossessable, so delinquency sits above secured housing (about 1.0%) and well below unsecured retail (about 1.8%) … | — |
| `portfolios.auto.risk_offset` | `-1.022` | assumed | Calibration constant in latent log-odds; see msme_cc.risk_offset. | — |
| `portfolios.auto.ticket.log_mean` | `13.3` | low | Median about 6 lakh, mean about 8 lakh, for a book that mixes cars and two-wheelers. Public-sector-bank car-loan tickets were about 7.5 lakh in FY22 (CRIF, stale) and the two-wheeler average ticket was about 95,000 in … | <https://www.crifhighmark.com/media/6260/how-india-lends-feb-2026.pdf> |
| `portfolios.auto.ticket.log_sd` | `0.8` | assumed | Wide enough to hold both a two-wheeler and a mid-size car in one portfolio. | — |
| `portfolios.auto.ticket.bounds` | `[50000.0, 20000000.0]` | assumed | 0.5 lakh (two-wheeler) to 2 crore. | — |
| `portfolios.auto.tenor_months` | `[36, 84]` | assumed | Vehicle loans run three to seven years. No public distribution located. | — |
| `portfolios.auto.interest_rate_pa` | `[0.076, 0.098]` | low | PNB vehicle-loan rates quoted from 7.60%, read from consumer rate-aggregator listings rather than the bank's own rate card; the upper bound is ours. | <https://www.urbanmoney.com> |
| `portfolios.auto.secured_share` | `1.0` | assumed | Hypothecated on the vehicle by definition. | — |
| `portfolios.auto.vintage_months_bounds` | `[0, 60]` | assumed | A five-to-seven-year book. | — |
| `portfolios.auto.constitutions` | `{'Individual': 0.9, 'Proprietorship': 0.07, 'PvtLtd': 0.02, 'Partnership': 0.01}` | assumed | Retail vehicle loans are overwhelmingly individual. | — |
| `portfolios.auto.sectors` | `{'Salaried': 0.78, 'Services': 0.08, 'Trading': 0.06, 'Retail': 0.04, 'Logistics': 0.04}` | assumed | Occupation of the borrower. | — |
| `portfolios.auto.city_tiers` | `{'Rural': 0.08, 'Semi-Urban': 0.22, 'Urban': 0.32, 'Metropolitan': 0.38}` | assumed | Vehicle finance reaches further down the population-group ladder than home loans. | — |
| `portfolios.auto.measurement.inflow_idiosyncratic_sd` | `0.15` | assumed | SD-D4, portfolio override of shared.measurement.inflow_idiosyncratic_sd. A salaried household account. | — |
| `portfolios.auto.measurement.utilisation_idiosyncratic_sd` | `0.0` | assumed | SD-D4, portfolio override: this portfolio has no revolving limit, so there is nothing to draw and nothing to sweep. | — |
| `portfolios.auto.noise.silent_default_share` | `0.09` | assumed | Share of THIS portfolio's defaulters that arrive with no warning chain. A vehicle is stolen, written off, or the driver-owner loses the contract that paid for it — all of which stop the instalment in the same month they … | — |
| `portfolios.auto.noise.transient_stress_share` | `0.22` | assumed | Share of this portfolio's never-defaulting accounts that pass through one recoverable stress episode inside the observation window. A vehicle off the road for a month, or a gap between driving contracts. The eight … | — |
| `portfolios.auto.noise.season_inflow_amplitude` | `0.07` | assumed | Amplitude of the calendar effect on this portfolio's banked inflow, as a fraction of the healthy level at the peak of the shape (festival up, post-festival lull down, quarter-end push up, April drop, monsoon soft; for … | — |
| `portfolios.auto.noise.season_utilisation_amplitude` | `0.0` | assumed | Amplitude of the calendar effect on credit-limit utilisation: limits are drawn ahead of the festival season and dressed down at quarter end. A portfolio with no revolving limit carries 0. | — |
| `portfolios.auto.noise.season_salary_amplitude` | `0.21` | assumed | Amplitude of the bonus/increment effect on the salary credit. It matters out of proportion to its size, because a spike in April or October makes the trailing six-month average high and every later month read short. | — |
| `portfolios.auto.noise.season_commute_amplitude` | `0.26` | assumed | Amplitude of the calendar effect on card-visible fuel and toll spend: festival travel up, monsoon down. | — |
| `portfolios.auto.channels` | `['cash_flow', 'transactions', 'repayment', 'salary', 'commute', 'ltv']` | assumed | A vehicle borrower's fuel, toll and parking spend is visible in card and UPI narrations. A commute that stops at the same time as the salary thins is the early tell that the borrower has lost the job the vehicle was … | — |
| `portfolios.auto.ltv.origination` | `0.8` | assumed | Lenders fund up to 85-90% of on-road value; originations cluster near 80%. | — |
| `portfolios.auto.ltv.origination_sd` | `0.07` | assumed | Dispersion of vehicle LTV at sanction. | — |
| `portfolios.auto.ltv.collateral_drift_pa` | `-0.15` | assumed | Vehicles depreciate about 15% a year. | — |
| `portfolios.auto.commute.spend_share_of_emi` | `0.3` | assumed | Monthly fuel, toll and parking spend as a fraction of the EMI. | — |
| `portfolios.auto.commute.spend_share_sd` | `0.12` | assumed | Dispersion of commute spend. | — |
| `portfolios.auto.commute.stress_drop` | `0.7` | assumed | Fraction by which commute spend falls at full latent stress: the vehicle stops moving before the EMI stops being paid. | — |


---

## Confidence census

328 parameter nodes in `src/generator/sources.yaml`, by confidence (`python3 src/data_card_params.py --census`;
SD-D8 added one — `portfolios.msme_cc.utilisation.base_mean`):

| Confidence | Count | Share |
|---|---|---|
| `high` | 10 | 3% |
| `medium` | 14 | 4% |
| `low` | 22 | 7% |
| `assumed` | 282 | 86% |

**86% of this book's parameters are `assumed`, and that is the honest position, not a shortcut.**
IDBI's four public disclosures (the Q4 FY2025-26 investor presentation, the CIBIL score range, the
GST filing calendar and RBI's IRAC/SMA definitions) anchor the ten `high`-confidence nodes and most
of the `medium`/`low` ones; almost everything else — the within-portfolio constitution mix, every
elasticity and lead-time in the deterioration chains, every noise/silent/transient share, every
seasonal amplitude — is a bank's internal book composition or a simulation-shape choice that is
simply not public. A synthetic early-warning book's job is to be *coherent and hard*, not to claim
it measured India; §"Known unrealisms" is where that honesty is made concrete, item by item.

---

## Realism-check summary (SD-D6) — `src/realism.py`, `data/realism_report.json`

Run via `python3 src/realism.py --out data/realism_report.json` (45k×48) and
`python3 src/realism.py --panel data/small9k36/msme_loan_panel.csv --accounts data/small9k36/accounts_static.csv --out data/small9k36/realism_report.json`
(9k×36). Every check prints PASS/FAIL with the observed value, the expected value/band and a
one-line rationale; the script never stops at the first failure and never imports
`generator.labels.assert_base_rates` or any other generator-internal `check()` — every number is
re-derived straight from the two CSVs on disk. Two things it reads read-only, and both are
provenance data rather than a verdict: `generator.sources` (to compare the panel against the
SAME bands `sources.yaml` cites) and `generator.generate` (used only by the seed-reproducibility
check, to build a small fresh population twice and hash-compare it).

**Result, seed 20260709, 2026-09-16 (SD-D6 audit) / 2026-09-17 (SD-D8 fix pass):**

| Population | Checks | Pass | Fail |
|---|---|---|---|
| 45,000 × 48 (validation) | 75 | **75** | 0 |
| 9,000 × 36 (shipped demo) | 75 | **75** | 0 |

SD-D6's original audit reported three genuine, independently-discovered failures at 45k (two of
them at 9k too) — not audit bugs. SD-D8 closed all three; each fix is carried into "Known
unrealisms" below (items 13-15, marked RESOLVED) rather than quietly dropped from this history:

1. **`cc_utilisation_mode`** used to FAIL at both sizes: MSME-CC's credit-limit utilisation centred
   on a mode of ~0.43-0.52 (mean ~0.52-0.53), not the ~0.85 a healthy, actively-drawn cash-credit
   account conventionally runs at — `portfolios.msme_cc` carried no `base_util_mean` override, so
   it ran on the shared default of 0.52. **Fixed:** `sources.yaml`'s
   `portfolios.msme_cc.utilisation.base_mean = 0.85` (confidence `assumed`), wired through
   `CHANNEL_PARAM_SOURCES`, plus a widened `util_bounds` ceiling so the sourced mean is not clipped
   into an artificial second mode. Now reads `mode=0.795, median=0.838, mean=0.850` at 45k.
2. **`monotone_default_by_dpd_band`** used to FAIL at both sizes: P(default within 12m) by the
   account's *current* DPD bucket ran `0`→2.6-2.9%, `1-30`→19.7-19.3%, `31-60`→**56.6-60.7%**,
   `61-90`→**49.0-55.2%** — a reversal at the top end, because `arrears.arrears_ladder` let a
   transient (never-defaulting) episode reach up to 84 DPD and then cure, diluting the 61-90 bucket
   with rows that were not deteriorating toward NPA. **Fixed:** the ladder is capped at 58 DPD
   (`[0, 22, 48, 58]`, was `[0, 22, 48, 71, 84]`) — one parameter, provenance unchanged. Now reads
   `0=0.0259, 1-30=0.1926, 31-60=0.4867, 61-90=0.7543` at 45k — strictly non-decreasing.
3. **`impossible_dpd_exceeds_days_on_book`** used to FAIL at 45k (17 of 2,039,678 rows, 13 distinct
   accounts; too rare to reliably surface at 9k). 12 of those 17 rows were an account already
   showing a nonzero DPD (up to 30.1) in its very first observed month (`vintage_months == 0`); the
   other 5 (4 accounts at `vintage_months == 1`, 1 at `== 2`) showed a DPD that had climbed faster
   than the days the account had existed could support. **Fixed:**
   `generator.channels.simulate_channels` now clips the final `dpd` to `vintage_months * 30` after
   every ladder that can set it (the defaulter dpd_ladder, the bounce ladder, and the transient
   arrears ladder each reach the panel through this one guard). Now `0 violating row(s)` at 45k.

Every other check — all eight portfolios' default-rate bands, the book-level DR-03 band, the
SMA-2/NPA ratio band, the silent-defaulter and transient-stress shares, every MAR-missingness rule,
every channel-presence rule (14 columns × the portfolios that are allowed to carry them),
referential integrity between the two CSVs, seed reproducibility, the vintage-hazard maturation
window, the Agri-only per-account seasonal autocorrelation, and the remaining ~30 impossible-state
guards — **passes clean at both sizes**, as it always did.

---

## The honest AUC story

Four numbers, each from a different stage of this week's build, on the SAME pipeline
(`src/export_demo.py` / `src/rigor.py`'s own scoring, not re-trained by this lane — SD-D6's brief
is data, not models):

| Stage | Pooled AUC | Population | Source |
|---|---|---|---|
| **July 2026** (pre-rewrite, two-portfolio MSME book) | **0.947** | 9,000 × 36 | SD-D1 report, "before" column |
| **Pre-noise** (eight portfolios, population + shared-latent-stress work landed, `noise=False`-equivalent maturity) | **0.927** | 45,000 × 48 | DM-6/DM-7 export/rigor report — "just over the 0.92 ceiling" |
| **Shipped** (SD-D4/D5 noise — silent defaulters, hard negatives, seasonal confounders, measurement noise, MAR missingness — switched on) | **0.902** | 45,000 × 48 | SD-D4/D5 report, in-memory diagnostic; reproduced by `python3 -m generator.build` + `export_demo.py` |
| Pre-registered band (DR-01, `validation/criteria.yaml`) | **[0.82, 0.92]** | — | plan §B L8; the floor was deliberately lowered from 0.85 to sit credibly beside real published bank EWS models (~0.81) |

**The shipped number (0.902) is inside the band; the two earlier numbers were not** — 0.947 was
far over the 0.92 ceiling (a book that separable has leaked its own generative structure), and
0.927 was still 0.007 over it. SD-D4/D5's silent-defaulter/transient-stress/measurement-noise work
is what closed that gap, and it closed it **honestly** — not by narrowing the label definition or
softening the deterioration chains, but by adding the population noise a real bank's own EWS model
would actually have to contend with. At 9,000 × 36 (the shipped demo size) the pooled AUC is lower
still, **0.891**, comfortably inside the band with more room to spare — the DR-01 gate is
train-size-sensitive, and the model lane (§B L5/L8) should say which size it tunes and reports
against, not silently pick whichever is more flattering.

**SD-D8 note:** the table above predates this lane's three generator fixes (CC utilisation, the
transient arrears cap, the DPD-vs-vintage clip) and the `vintage_band`/`vintage_months` feature
swap — none of them targeted at AUC, but a generator change can still move it. A same-pipeline 9k
re-run after the fixes (`export_demo.build_export`, in-process, no file write) gives **AUC 0.875**
against the pre-fix 0.891 above — still comfortably inside the [0.82, 0.92] band, a small move in
the expected direction (capping the transient arrears ladder removes some hard-negative separation
at the DPD extreme). The 45k number is this card's validation population and is **not re-measured
here** (this lane's budget does not include a 45k `export_demo.py`/`rigor.py` run) — DM-6/DM-7 or
the validation lane should refresh it against the panel this fix pass regenerated.

---

## DR-12: literal vs. CI-aware — ruled (SD-D8)

DR-12 (`monotone_decile_step_fraction`, threshold ≥ 0.9, per portfolio) asks whether at least 9 of
the 10 step-ups in observed default rate across score deciles are non-decreasing. As **literally
registered**, it **fails at both sizes** on the shipped (post-noise) panel: pooled 7/9 at 45k, 5/9
at 9k; per-portfolio cells run 6/9-9/9. This is a genuinely different failure from what DM-6/DM-7
saw on the pre-noise panel, where **all** realised risk sat in the top decile (D10) and D1-D9 were
literal noise (0.0-1.8%) — SD-D4/D5's noise work spread risk more realistically across deciles
(D1-D9 now run 0.000-0.016 at 45k), which is progress, but a genuinely spread-out low-probability
tail also produces more small-sample step-down noise for a strict "≥9/10 non-decreasing" literal
reading to catch.

DM-6/DM-7 registered a second reading beside the literal one, `monotone_decile_step_fraction_ci`:
a step only counts as a violation if the two deciles' Wilson confidence intervals are **disjoint**
— i.e. the data can actually distinguish the reversal from sampling noise, not merely display one.
Under that reading, **every cell passes 9/9 or effectively 1.0 at both sizes** — no reversal in
this panel is statistically detectable. Both numbers are reported side by side in the exhibit
(`rank_order.by_portfolio[*].monotone_decile_step_fraction` and `..._ci`); `validation/criteria.yaml`
still gates on the literal reading, pre-registered before either number existed.

**Ruled:** the literal criterion, as registered before either number existed, stays the gate — it
is reported as a **fail** (pooled 7/9 at 45k per L8's validation run, `validation/runners/06_stability`-
adjacent DR-12 measurement; 5/9 at 9k), and `validation/criteria.yaml` is **not amended** to swap in
the CI-aware reading. The CI-aware number (`monotone_decile_step_fraction_ci`, effectively 1.0 at
both sizes — no reversal in this panel is statistically distinguishable from sampling noise) is
still computed and shown **beside** the literal one, in the same exhibit
(`rank_order.by_portfolio[*].monotone_decile_step_fraction` / `..._ci`), so a reader sees both and
the honest tension between them rather than one number chosen after the fact. The honest framing
for the README/deck either way: DR-11 (strict band monotonicity — Green < Amber < Red) passes
cleanly in all eight portfolios at 45k, which is the property a relationship manager actually reads
off the product; DR-12 is a finer-grained diagnostic, registered as a fail, with the CI-aware
context alongside it rather than in place of it.

---

## Known unrealisms — complete, merged, numbered

Merged from all four DRISHTi data/model reports this week (SD-D1's generator rewrite, SD-D2/D3's
population + shared-latent-stress expansion, SD-D4/D5's noise/labels build, and the DM-6/DM-7
export/rigor pass), plus three items this lane (SD-D6) found independently while auditing the
CSVs. Nothing here is softened, and nothing that was flagged before is dropped.

**From `sources.yaml`'s own disclosures (load-bearing, read these first):**

1. **The account mix is shrunk toward uniform.** `book.mix_shrinkage_lambda = 0.60`: derived
   value-share-to-account-share mixes are blended `(1-λ)·derived + λ/8` so the thinnest portfolio
   carries 8.3% of accounts instead of 2.0% — without it, DR-06's per-portfolio AUC-with-CI
   floor would be unanswerable for the thin ones. `sources.yaml` records this against each
   portfolio's own `account_share_undistorted`, and its own comment calls it out explicitly: "This
   IS a departure from the real book and belongs on the known-unrealisms list."
2. **The default rate targets sectoral GNPA, not IDBI's own book — roughly 5× IDBI's real
   slippage, and a stock ratio used as a flow target.** IDBI's own FY26 annualised slippage
   (fresh-NPA flow) is 0.63%; this panel is calibrated to 3-5% annual (`book.annual_slippage_band`,
   DR-03), close to system-wide *sectoral GNPA levels* (a cumulative **stock** figure) rather than
   to IDBI's own **flow**. `sources.yaml`'s own header is explicit: "the synthetic book slips FAR
   harder than IDBI's real one... roughly 5x IDBI's current slippage. That is a deliberate,
   disclosed departure — an early-warning model needs enough positives to learn from... This panel
   is NOT a representation of IDBI's book quality."
3. **The rate a borrower pays is not individually risk-tilted, and at book level it tilts the
   WRONG way.** Within a portfolio, `interest_rate_pa` is drawn independently of the account's own
   latent risk (`risk_z`) — two MSME-CC borrowers with very different risk profiles draw from the
   same rate band with no premium for the riskier one. Measured book-wide, `interest_rate_pa`
   correlates **negatively** with `risk_z` (Pearson −0.38) and defaulters average a slightly
   *lower* rate than non-defaulters (7.72% vs 8.59%) — a portfolio-mix artefact (Agri/KCC carries
   both the highest default rate and, reflecting real interest-subvention schemes, one of the
   lower rate bands), not a bug, but it means a naive "rate as a risk feature" intuition does not
   hold on this panel and a model should not be allowed to lean on it as a proxy for risk.

**From SD-D4/D5 (noise, hard negatives, labels — six items reported verbatim):**

4. **A slipped KCC renewal stays overdue to the *next* annual due date**, so a 7% chance of a
   renewal slipping leaves roughly 6% of Agri account-months showing as overdue — this overstates
   the *duration* of a renewal problem and understates its *incidence* (real practice would show
   more distinct slip events, each shorter).
5. **Part-payment does not accrue DPD.** A borrower can pay 60% of the demand for eight straight
   months at 0 days past due, which no real core-banking system would allow — inherited from the
   chain design (`arrears.spine_strength_bounds`), where the shared collection-shortfall spine is
   a separate instrument from the DPD ladder rather than the DPD ladder's own driver.
6. **The bounce-to-DPD ladder is clipped at three consecutive misses** (`arrears.bounce_dpd_ladder`,
   4 rungs, 0/16/43/68 days); a fourth consecutive miss would in reality already be well past
   NPA, but the ladder itself has no rung past 68 days — the climb from there to 90 is carried by
   the separate arrears/hard-negative spine, not this ladder.
7. **Transient stress episodes are one per account over the full four-year (48-month) panel.** A
   real borrower who survives one recoverable stress episode is not thereby immune to a second one
   later in the window; this panel gives every never-defaulting account at most one.
8. **Auto's own instrument is too noisy to carry a transient episode.** Commute/fuel spend has
   σ=0.38 (log scale) plus a 7% chance of a zero-spend month even when healthy, so Auto's transient
   episodes are asserted on the salary credit channel instead — an accurate read of Auto's own
   noise floor, but it means Auto's hard negatives look structurally different from every other
   portfolio's.
9. **`GeneratorConfig(noise=False)` reproduces the July 2026 fingerprint exactly, and is NOT the
   shipped dataset.** Its AUC sits above the pre-registered DR-01 ceiling by design (§"Honest AUC
   story") — it exists solely so the equivalence suite (`tests/test_generator_equivalence.py`) has
   something byte-comparable to check the rewrite against, never for training or validation.

**From SD-D1 (the generator rewrite):**

10. **`txn_drop_flag` is dead — 0 for every row, in both the old row-loop generator and the new
    vectorised one, across every seed tried.** The `txn < 0.6 × 6-month-mean` threshold is never
    reached because the trailing mean itself falls with the signal, so the flag never fires. A
    faithfully-reproduced feature slot that has never carried information, in either generator.

**From SD-D2/D3 (population + channels):**

11. **`sources.yaml`'s Agri population diverges from `data/bank/fixture.json`'s Agri records, on
    purpose.** The bank-API fixture (a separate, offline stand-in for real Atlas pulls) gives its
    Agri rows business constitutions and a GSTIN; this generator's Agri/KCC borrowers are 88%
    Individual (real KCC borrowers are individual farmers) and carry no GST channel (farmers are
    GST-exempt). Both are internally consistent, but a jury cross-referencing the two files will
    see different Agri population assumptions and should be told they are deliberately different,
    not accidentally inconsistent.
12. **`ltv_vs_schedule` is a covenant-relative ratio, not an absolute LTV breach.** An earlier
    `ltv_breach` design (an absolute threshold) fired for 0.1% of rows on a seasoned Indian
    mortgage book — the same "channel never moves" failure `txn_drop_flag` shows. The shipped
    column instead tracks LTV against the loan's own *scheduled* LTV, which moves with arrears
    (numerator) and a distress revaluation (denominator); this is more realistic but means `ltv`
    and `ltv_vs_schedule` answer different questions and should not be read interchangeably.

**From this lane's own independent audit (SD-D6, `src/realism.py` — see "Realism-check summary"
for the numbers behind each):**

13. **RESOLVED (SD-D8, 2026-09-16) — was: CC utilisation ran at roughly half-drawn, not the ~0.85 a
    healthy revolving limit conventionally shows.** `portfolios.msme_cc` carried no `base_util_mean`
    override, so it inherited the shared 0.52 default unmodified. Fix: `sources.yaml` now carries
    `portfolios.msme_cc.utilisation.base_mean = 0.85` (confidence `assumed`, cited to the plan's "CC
    util mode ~0.85" and RBI's EWS monitoring-convention framing), wired via
    `CHANNEL_PARAM_SOURCES`; `msme_tl` (0.35) and `agri` (0.68) are unchanged. A second, model-shape
    knob moved alongside it — `util_bounds` widened from `(0.02, 1.05)` to `(0.02, 1.2)` for
    `msme_cc` only — because at a 0.85 mean the OLD ceiling clipped ~13% of the realised monthly
    signal into a single artificial spike above 1.0, which was itself the thing making the check's
    computed mode land near 1.07 rather than the sourced 0.85; `check_cc_utilisation_mode` now
    passes (`mode≈0.80` at 45k). `tests/test_generator_equivalence.py`'s pooled MSME utilisation
    columns moved by design as a result — their fingerprint tolerance was widened explicitly, with
    a comment, not silently (`WIDENED_TOLERANCE_COLUMNS`).
14. **RESOLVED (SD-D8, 2026-09-16) — was: raw current-month DPD was not a monotone risk signal at
    its own top end.** The 31-60 DPD bucket carried a HIGHER forward 12-month default rate than the
    61-90 bucket, because the hard-negative population's arrears ladder reached up to 84 DPD and
    cured. Fix: `shared.transient.arrears_ladder` in `sources.yaml` is capped at 58 DPD (was
    `[0, 22, 48, 71, 84]`, now `[0, 22, 48, 58]`) — one parameter, provenance `assumed`, same node.
    A cured transient episode can no longer land in the 61-90 (SMA-2) band at all, on the reasoning
    that a cured 61-90 DPD borrower is genuinely rare in practice (SMA-2 mostly slips onward to NPA
    rather than curing); `monotone_default_by_dpd_band` now passes (31-60 ≤ 61-90 at both sizes).
    The alternative (leaving the data and documenting the reversal) was considered and rejected in
    favour of the cap, per this lane's own brief, because it is the smaller, single-parameter,
    honestly-provenanced change.
15. **RESOLVED (SD-D8, 2026-09-16) — was: a handful of brand-new accounts were already delinquent
    in their first observed month, or close to it.** 17 of 2,039,678 rows (13 distinct accounts, 45k
    seed 20260709) showed a DPD the account's own age could not support — 12 of them a nonzero DPD
    at `vintage_months == 0` itself. Fix: `generator.channels.simulate_channels` now clips the
    final `dpd` to `vintage_months * 30` (months on book) after every ladder that can set it — the
    main defaulter dpd_ladder (timed off months-to-NPA), the bounce ladder (timed off a consecutive-
    uncured-bounce run) and the transient arrears ladder (timed off episode position) all reach the
    panel through this one guard, none of them individually aware of the account's own vintage.
    `impossible_dpd_exceeds_days_on_book` now passes at both sizes (0 violating rows), and
    `tests/test_channels.py::test_nothing_impossible_is_emitted` carries the same invariant,
    re-derived independently, as a permanent regression guard.

**Interpretation calls that are load-bearing, not unrealisms, but belong beside them:**

16. **DR-15's leakage gate (DPD family ≤ 5% attribution at 10-12 months) turns entirely on where
    `collection_ratio` is assigned in `src/rigor.py`'s GROUPS.** As its own "Demand vs collection"
    family, the DPD family's attribution runs 2.05-3.9% across the pre-noise and post-noise
    measurements (DM-6/DM-7's export/rigor pass and SD-D4/D5's own diagnostic respectively) —
    comfortably under the 5% gate either way. Folded into the DPD family instead, it runs
    12.2-18.1% — a clear fail under both measurements. Both readings are computed and emitted;
    `validation/criteria.yaml` registers the first as the gate. See "What a jury will push on",
    item 1.
17. **DR-12's literal-vs-CI-aware split ruled (SD-D8)** — see the dedicated section above: the
    literal criterion stays the registered gate and is reported as a fail (pooled 7/9 at 45k); the
    CI-aware reading (effectively 1.0) is shown beside it; `validation/criteria.yaml` is not amended.
18. **`vintage_band` added as a modelling choice, not gaming (SD-D8, DR-14).** Raw `vintage_months`
    drifts by construction under any time-split OOT — it is account-age plus elapsed months, so a
    later test window is mechanically older than train — which made it DR-14's binding max-CSI
    feature (4.16, per L8's validation run). The panel now also carries `vintage_band`, a six-level
    bank-style relationship-age bucket (`0-6/7-12/13-18/19-30/31-48/49+` months, see
    `generator.build.VINTAGE_BANDS`); `export_demo.py`/`rigor.py` score `vintage_band` and drop raw
    `vintage_months` from the model's own feature set (`CAT`/`DROP`, and `rigor.py`'s GROUPS moves
    the "Borrower profile" family's membership accordingly). `vintage_months` itself is unchanged
    and still written to the panel CSV — validation's own cuts use it, and bucketing vintage the way
    a bank actually reads it is standard practice, not an attempt to hide drift; see MODEL_CARD.md's
    matching note. DR-14 is to be **re-measured** by the validation lane (L8) against the new
    feature set — this lane does not re-run `validation/**`.

---

## What a jury will push on

1. **"Why does the leakage gate pass only because `collection_ratio` is its own family?"** — item
   16 above. The honest answer: `collection_ratio` is a demand-vs-collection ratio, not a
   days-past-due measurement, and it is knowable earlier in the deterioration chain than DPD is
   (cash-flow and utilisation move first, by design — see "Generation pipeline", stage 3); grouping
   it with DPD conflates "the account is short this month" with "the account is already visibly
   late", which is exactly the distinction the whole "12 months early" claim rests on. But a
   skeptical reader is entitled to ask why the boundary was drawn there and not somewhere looser,
   and the 12-18% alternative number should be shown, not hidden.
2. **"Is 0.902 real, or did SD-D4/D5 just add noise until the number fell in the band?"** — the
   honest answer is that the noise added is *independently motivated and cited* (NACH return
   rates, GST/QRMP filing calendar, RBI's IRAC revaluation cadence, a portfolio's own instrument
   noise floor — see `sources.yaml`'s `measurement`/`arrears`/`transient` sections), not reverse-
   engineered from the AUC target; but the sequence 0.947 → 0.927 → 0.902, each stage landing
   closer to the ceiling than the last, invites exactly this question and the honest AUC story
   section should be read alongside the answer, not instead of it.
3. **"Why did the DPD signal reverse at 61-90 days?"** — item 14, **resolved SD-8**. It was a
   genuine consequence of a deliberate design choice (curing hard negatives reaching up to 84 DPD),
   not a bug; the fix was the smaller honest change available — capping the transient arrears
   ladder at 58 DPD (one `sources.yaml` parameter) rather than leaving the reversal undocumented.
   "How late is the account today" is a strictly non-decreasing risk signal again at both sizes.
4. **"Why was CC utilisation only ~0.52, and did that matter?"** — item 13, **resolved SD-8**. It
   never changed `default_within_12m`'s truth (utilisation still rises with stress, relative to
   each account's own baseline — `monotone_default_by_utilisation_band` passed cleanly throughout),
   but an absolute-threshold rule ("flag anyone over 90% utilisation") calibrated to a real book
   would have fired far too rarely on this one. `portfolios.msme_cc` now sources a ~0.85 mean.
5. **"Real slippage is 0.63%; why does the model train on 3-5%?"** — item 2, and the honest reason
   is stated in `sources.yaml` itself: an early-warning model needs enough realised positives in
   the training window to learn a signal from, and IDBI's own book does not currently produce
   enough of them inside a single hackathon-scale panel. This is disclosed, not hidden, and the
   README should say so in the same sentence it quotes any base rate.
6. **"Which population size is the real one — 9k×36 or 45k×48?"** — both are shipped; `generate_data.py`'s
   own default is 9,000×36 (production/demo), while 45,000×48 is what validation (`validation/`)
   and this card's own checks use for enough per-portfolio and per-decile sample size. DR-01's
   pooled AUC differs materially between them (0.891 vs 0.902), and DR-11 (band monotonicity)
   fails at 9k in three portfolios purely on empty Red-band cells (n=0) while passing cleanly at
   45k. Whichever size the deployed model trains and reports against should be stated explicitly,
   every time a number is quoted.

---

## Research gaps

Items this lane surfaced but is not in scope (or not authorised) to close — `src/realism.py` does
not edit `src/generator/**`, `src/export_demo.py`, `src/rigor.py`, `app/**` or `validation/**`:

- **RESOLVED (SD-D8) — the 17-row `dpd_exceeds_days_on_book` bug (item 15)** was fixed in
  `generator.channels.simulate_channels`, which now clips the final `dpd` to
  `vintage_months * 30` — see item 15's updated entry above.
- **DR-18 (cash-flow-family ablation ≥ 0.04 AUC) was only quick-diagnosed at 0.019 on a 7k sample**
  (SD-D4/D5 report) — at risk of failing its pre-registered floor, and needs a real measurement
  from the validation runner (L8), not this lane's data-only pass. Still open; SD-D8 did not touch
  it.
- **RESOLVED (SD-D8) — DR-12's literal-vs-CI-aware ruling** (see the dedicated section) has been
  made: the literal criterion stays the gate and is reported as a fail; the CI-aware reading is
  shown beside it, not substituted for it.
- **DR-14's max-CSI fail on `vintage_months` is addressed but not re-measured here** (item 18):
  `vintage_band` now exists and is scored in its place; the actual post-fix CSI number is L8's
  validation lane's to produce, not this lane's.
- **Two README numbers drifted this week and are stale** (93%→89% flagged-≥6-months-ahead; the
  leakage line's "just 1.8%" 10-12-month DPD share → 2.05-2.1%), per SD-D1's report — outside this
  lane's staging scope; belongs to SB-1's stale-string grep.
- **No real bank book exists to validate any of this against.** Every realism check in this card
  compares the synthetic panel to either a cited public statistic or this lane's own stated
  `assumed` expectation — never to ground truth, because there is none available inside this
  project's timeline. The honest limit of "realistic" here is "internally coherent and consistent
  with the public record", not "verified against a real portfolio".
- **RESOLVED (SD-D8) — `generate_data.py`'s own module docstring was stale** ("~2.7%/year
  slippage", "MSME loan" — the shipped band is 3-5% annual across all eight portfolios), flagged by
  SD-D1's report; fixed directly (SB-1's list item, closed here rather than left for it).

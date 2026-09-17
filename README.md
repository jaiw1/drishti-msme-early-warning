# DRISHTi — Early-Warning System for IDBI's Lending Book

*An entry for **IDBI Innovate 2026 · Track 4 (Default Prediction)**.*

**🟠 Interim demo (pre-sandbox):** **https://drishti-ews.vercel.app** — no login, no backend
behind this particular static build. This is a development demo, not the submission
deployment: the bank-sandbox deployment (EC2 behind nginx, a real backend, real auth — see
"Architecture") is in progress this week and is not live as of this writing (2026-09-17). Do
not read this link as "the deployment."

## What DRISHTi is

IDBI's mentors set four mandates for this track, and this card is organised around all four:
**one holistic model across every lending portfolio the bank carries** (not eight separate
scorecards bolted together); **rank-order that holds inside each portfolio**, not only pooled;
a decision rule built around the fact that **a missed NPA costs the bank far more than a false
positive**; and an honest replacement for the **"90%+ accuracy"** framing the mentors rejected
in July. A fifth, quieter instruction — drop the "complements SAJAG" framing from the pitch —
is also observed throughout this document: DRISHTi is described here as what it actually is, a
standalone early-warning cockpit, not as an add-on to IDBI's existing SAJAG EWS.

DRISHTi scores **eight lending portfolios** — MSME cash-credit, MSME term loan, Housing,
Education, Agriculture (KCC), Retail-Unsecured (personal loan), Loan-Against-Property and
Auto — with **one** LightGBM classifier, not eight. For every account it produces a RAG band
(Green/Amber/Red), plain-English reason codes, and — where projectable — a runway estimate in
months before the account would cross into Red. The officer decides; the model never touches
the account.

## The headline

> **84.5% of Red-flagged accounts went NPA within 8 months (95% CI 79.8%–88.2%, n=283)**

Taken verbatim from `app/public/demo_data.json` → `metrics.honesty.headline` (DM-8 round 2, the
model's final, frozen state — this is **not** the number an earlier report or an earlier draft
of this README quoted; always read it fresh from the file). The same block states why this,
and not raw accuracy, is the number to publish:

| | value | source |
|---|---|---|
| **Red-band precision @ 8 months (the headline)** | **84.5%** (95% CI 79.8–88.2%, n=283 Red-flagged, 239 went NPA) | `demo_data.json` → `metrics.honesty`, `metrics.red_band_precision_8m` |
| Raw accuracy @ 8 months | 98.8% (95% CI 98.6–99.0%) | `metrics.raw_accuracy_8m` |
| **Flag-nobody baseline** | **97.3%** | `metrics.raw_accuracy_8m.flag_nobody_baseline` |
| Base rate @ 8 months / 12 months | 2.72% / 3.90% | `metrics.base_rate_8m`, `metrics.base_rate_12m` |
| **Missed-NPA share** — of every account that went NPA within 8 months, the share the model had left in Green | **17.6%** (95% CI 13.9–21.9%) | `metrics.missed_npa_share` |

**Why not accuracy.** A model that flagged nothing at all would score 97.3% raw accuracy,
because only 2.7% of the book reaches NPA within 8 months — that figure tracks the base rate,
not the model. Raw accuracy (98.8%) is carried in the export *for contrast, never as the
headline*; a build-time guard (`export_demo.py::assert_honesty`) fails the export if the
discredited "90%" figure appears anywhere in the metrics block, or if the word "accuracy"
appears outside the paths that exist to disown it. `missed_npa_share` — not precision — is the
number the mentors care about most, and it is the number the operating point (see
"Thresholds") is actually chosen against: a missed NPA costs the bank far more than a false
positive, so the threshold search minimises expected rupee cost, not maximises precision.

**A second, larger-population reading exists and is reported alongside, not instead.**
`validation/report/REPORT.md` (DR-02) reports red-band precision pooled over **every** eligible
holdout row across the whole out-of-time window (not one snapshot month): **72.9%** (95% CI
72.1–73.7%, n=11,657). The 84.5% headline is the single frozen reference-month snapshot the
demo cockpit actually ships (`n_accounts_scored=12,760`, of which 283 sit in Red); the 72.9%
figure is the same metric measured over a much larger, multi-month holdout. Both are real,
both are cited, and the gap between them is exactly what "one snapshot" vs "pooled over time"
means — not a discrepancy to paper over.

## How it works

```
population (8 portfolios, sourced mix) → shared latent stress S_t (one AR(1)/ramp process)
  → portfolio-specific observation channels (GST/utilisation/bounces; salary-gap/balance;
    moratorium-end; harvest-miss; EMI-stacking; LTV/rental; commute/salary)
    → noise, silent defaulters, transient stress (keeps the panel from being trivially separable)
      → ONE LightGBM (`portfolio` scored as a feature, not a separate model per portfolio)
        → cost-minimising Amber/Red thresholds (rupee cost, not AUC or a validation band)
          → watch-list, reason codes, runway estimate, network-contagion lens
```

- **Population.** `src/generator/portfolios.py` draws who exists — constitution, sector,
  geography, vintage, ticket size, tenor, rate — from `sources.yaml`, then shrinks the mix
  toward a uniform eight-way split so every portfolio is thick enough to carry its own
  bootstrapped AUC. `DATA_CARD.md` §"Generation pipeline", step 1.
- **One shared latent stress path.** `latent.build_stress_path` draws a single `S_t` per
  account; every portfolio's channels are a *slice of the same process* — the generative
  argument for "one model, eight portfolios" rather than eight independent simulators glued
  together (`DATA_CARD.md` §"Purpose", §"Generation pipeline" step 2).
- **Portfolio-specific channels.** The same latent stress becomes what a bank can actually
  observe, differently per product: MSME-CC/TL move GST sales → utilisation → bounces → DPD;
  Housing moves salary-gap → balance-floor → EMI bounce → DPD; Education moves
  moratorium-end → stop → DPD; Agri moves harvest-miss → renewal-overdue → DPD;
  Retail-Unsecured moves EMI-stacking → min-balance → bounce; LAP moves LTV-drift/rental-dip →
  DPD; Auto moves commute-spend/salary-gap → DPD. A channel a portfolio doesn't carry is `NaN`,
  never zero. `DATA_CARD.md` §"Generation pipeline" step 3.
- **Noise, silent defaulters, transient stress.** A per-portfolio share of defaulters arrives
  with no warning chain at all (~7.8% of the book); roughly a fifth of healthy accounts pass
  through a transient stress episode that moves the same instruments and sometimes goes
  genuinely past due before curing; seasonal confounders and measurement noise sit on top. This
  is the mechanism that keeps AUC honest rather than trivially high (see "The AUC story", next).
  `DATA_CARD.md` §"Generation pipeline" step 4; `MODEL_CARD.md` §13.
- **One LightGBM.** `LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=48, ...)`,
  categorical features native, `portfolio` scored as one categorical feature among 62 — the
  mandate's "one holistic model" made literal in the training call, not just the pitch.
  `MODEL_CARD.md` §7.
- **Cost-minimising Amber/Red.** The band split is not hand-set — it minimises the bank's
  expected rupee cost, subject to the pre-registered rank-order criteria as a feasibility
  filter. See "Thresholds and cost model" below.
- **Watch-list.** The officer-facing output: RAG band, top-3 plain-English reason codes
  (SHAP-style contributions, human-templated), and where projectable a runway estimate in
  months before the account crosses into Red.

## The AUC story

Three numbers, same model family, same population, in the order they were measured
(`MODEL_CARD.md` §13):

1. **0.947 (July 2026)** — the original ungated model, before the eight-portfolio generator
   rewrite and before noise-hardening. Too high to be believable: a synthetic panel scoring
   above the pre-registered ceiling has leaked its own generative structure, not learned
   something real.
2. **0.927 (pre-noise-hardening checkpoint)** — after the eight-portfolio rewrite but before
   silent-defaulter, hard-negative and dark-link noise injection. Still 0.007 over the ceiling.
3. **0.902 (shipped)** — after noise-hardening (silent/fast defaulters ~7.8% of the book,
   transient never-defaulting episodes ~22.5%, chain-link visibility 0.72) and a final
   borrower-heterogeneity pass. **Inside the pre-registered [0.82, 0.92] band** (DR-01,
   `validation/criteria.yaml`).

Both the floor (0.82, deliberately lowered from a first-draft 0.85) and the ceiling (0.92) were
pre-registered **before any model result existed**: "a floor of 0.85 would tempt tuning toward
separability; 0.82 sits credibly beside real 0.81" (published bank early-warning models land
around there; DRISHTi's own real-data validation model scores 0.81 — see below). The ceiling
exists for the same reason in reverse: a synthetic panel that scores above it has made the
problem too easy to be believable.

The validation lane's own, independently regenerated 45,000×48 panel measures pooled AUC at
**0.8885** (95% CI 0.8814–0.8949) — a few points different from the 0.902 the main export
pipeline reports, because the two panels are generated separately from the same code, not
shared; both numbers are real and both are cited (`validation/report/REPORT.md` DR-01;
`MODEL_CARD.md` §9).

## Rank-order, per portfolio

The mandate that "one holistic model" is a real claim, not a slogan, is tested directly: does
observed 8-month NPA rate rise strictly Green → Amber → Red **inside every one of the eight
portfolios**, not just pooled?

| Portfolio | AUC (DR-06) | Bands strictly monotone? |
|---|---|---|
| Agri | 0.9069 | yes |
| Education | 0.8752 | yes |
| MSME-CC | 0.8724 | yes |
| Housing | 0.8659 | yes |
| MSME-TL | 0.8605 | yes |
| LAP | 0.8500 | yes |
| Retail-Unsecured | 0.8388 | yes |
| Auto | 0.8374 | yes |

**8 of 8 portfolios clear the AUC floor (≥0.78) and 8 of 8 hold strict Green<Amber<Red
monotonicity (DR-11 pass, pooled and every portfolio)** — `app/public/demo_data.json` →
`metrics.rank_order.by_portfolio`; `validation/report/REPORT.md` DR-06, DR-11.

A finer decile-level check (DR-12: at least 9 of 10 decile step-ups non-decreasing) **fails on
the literal pre-registered arithmetic** (0.5556 pooled) — not because the model doesn't rank
risk, but because almost all realised risk concentrates in the top decile, leaving the middle
deciles sitting at fractions of a percent where step-to-step ordering is statistical noise. A
second, reported-not-gated reading that only counts a step-down when the two deciles' 95%
Wilson intervals are actually disjoint scores **1.0000 — pooled and in every one of the eight
portfolios: no statistically detectable decile reversal anywhere.** The gate itself stays on
the literal arithmetic (see the validation table below); both numbers are published rather than
the passing one alone (`MODEL_CARD.md` §9).

## What is real, what is synthetic, what is bank-sandbox

Every value the platform export carries is tagged with exactly one of three sources
(`data/bank/SCHEMA.md`, `MODEL_CARD.md` §16):

| Tag | Meaning |
|---|---|
| `BANK_API` | Pulled live from an IDBI Atlas sandbox endpoint that actually answered. |
| `FIXTURE` | Sourced from the committed `data/bank/fixture.json` (160 accounts) when a live pull is unavailable or a family's account is outside its coverage. |
| `SIMULATED` | Produced by the synthetic generator — no Atlas API supplies this at all, or this build never substituted anything for it. |

**`BANK_API` on a row means the bank answered about *that row*, not that the endpoint
answered.** The two are easy to conflate and the conflation is the dishonest one: the
sandbox holds only a handful of sample accounts, so an endpoint can answer 200 while
nothing at all was fetched for the account being displayed. `src/bank.py` records the
identifiers the pull actually came back with and badges an account `BANK_API` only if it
is one of them; every other account degrades to `FIXTURE` or `SIMULATED` exactly as it did
before any pull existed. The sandbox's sample ids and this panel's generated ids are
disjoint, so **no account row in this build carries `BANK_API`** — the real bank data in a
`--bank` export is the run-level endpoint block, which is carried and badged separately.

**Only the `identity` family (CIF, account number, branch, RM) is ever overlaid with a
real/fixture value.** Every other family — `dpd`, `outstanding`, `bureau_score`, and every
other model input — is always `SIMULATED`, even on a `--bank` run: the model trains and scores
on the synthetic panel only, and badging a displayed value `FIXTURE` while showing the
generator's own number would be exactly the dishonest move this whole mechanism exists to
prevent. `filings` (GST turnover, adverse remarks) is *always* `SIMULATED` — no Atlas API in
the 25-endpoint catalogue supplies it at all.

**The sandbox is a small keyed store, not a static mock that ignores you.** Each Atlas endpoint
serves its own structured record — verified on 17 Sep 2026 by calling all 23 readable approved
APIs — and it really does look the key up: an id it does not hold answers a
`{"message": "Data not found", "sentKey": "acctId#<the id sent>"}` shaped error. API 433 is the
exception that misled us, returning a composite record carrying a slice for every API. What the
store holds is a **handful** of sample customers and accounts. A pull on 17 Sep 2026 walked every
documented identifier and found real records for three sandbox accounts (API 365; two of the
three also answered 441 and 391) and two sandbox customers (402, 442, 456, 394) — nine accounts
and CIFs in total, against a synthetic panel of 45,000. So a pull is
`BANK_API` **with** `sandbox_fixture: true`, every band and threshold in this build is computed
on the synthetic panel, and nothing here has ever scored, thresholded or banded a real bank
record (`MODEL_CARD.md` §15, "BR-6a").

**DRISHTi ingests 15 of the 25 requested APIs** (`data/bank/SCHEMA.md`): 391 (loan details),
402 (overdue/DPD), 404 (demanded vs collected), 441 (drawing power), 442 (CIF exposure, account
manager), 362 (liens), **433 (product-level rates, no customer id — the first live call with
zero dependency on a real customer)**, 473 (repayment schedule), 538 (payoff/penal split), 393
(statement), 365/394 (account/CIF enquiry), 456 (dedupe — the only place GSTIN appears), 408
(CIBIL, permitted for credit monitoring), and 508 (HRMS) — **which the bank rejected**, so no
RM roster or branch data reaches this build from it, and the platform's `app/atlas/policy.py`
now refuses it outright so no pull can call it by accident. The remaining
10 are SANKET's own surface (AA consent lifecycle, CRM write-back) or 415 (CKYC, subscribed but
deliberately never scored on).

**API 433's rate is what feeds the cost model.** `effective_rate_pa` (12.75%) and
`penal_rate_pa` (2.0%) in the threshold cost calculation are tagged `BANK_API` — a real captured
field from the sandbox's own contract — but every value derived from them carries
`sandbox_fixture: true`, because the sandbox's rate card describes its own sample book and not
ours: these are real *field values from the bank's own API contract*, not real *rates for our
borrowers*. `MODEL_CARD.md` §10.

**API 473 does answer, and it is an amortisation engine.** It was recorded here — and in the
platform's own adapter — as an endpoint that returns nothing. That was wrong; it is absent from
API 433's composite record, and absence from that record was mistaken for absence from the
sandbox. Given a principal, a rate and an instalment count it returns the level instalment and a
row per month. DRISHTi does not price instalments, so nothing in this build changed on the
strength of it; SANKET's `emi_source` now reads `BANK_API_473_schedule`
(`../sanket/MODEL_CARD.md` §13).

## Validation

All 26 acceptance bands are pre-registered in `validation/criteria.yaml`, which first entered
git at **2026-09-16T11:05:49+05:30** — that commit timestamp, not this README, is the evidence
that no band moved after seeing a result. **This is DM-8, round 2 of the two tuning rounds the
plan allows — the last permitted round; every number below is reported as measured, not chased
further** (`MODEL_CARD.md` §17).

**Current report** (`validation/report/REPORT.md`, generated 2026-09-17T02:36:16+05:30 from
commit `0c92bf980c39`): **16 pass · 4 fail · 0 warn · 6 reported.**

| ID | Metric | Band | Observed | Verdict |
|---|---|---|---|---|
| DR-01 | grouped AUC | ∈ [0.82, 0.92] | 0.8885 | pass |
| DR-02 | red-band precision @8m (pooled) | reported | 72.9% (n=11,657) | reported |
| DR-03 | annual slippage ratio | ∈ [0.03, 0.05] | 3.31% | pass |
| DR-04 | label base rate (annual) | reported | 3.63% | reported |
| DR-05 | OOT/holdout AUC ratio | ≥ 0.95 | 1.0009 | pass |
| DR-06 | per-portfolio AUC (×8) | ≥ 0.78 each | worst Auto 0.8374, best Agri 0.9069 | pass |
| DR-07 | AUC by cut (76 cells) | reported | — | reported |
| DR-08 | ECE overall | ≤ 0.02 | 0.0010 | pass |
| DR-09 | ECE per cut | ≤ 0.04 | all cells pass | pass |
| DR-10 | Δ Brier (calibrated − raw) | < 0.0 | −0.0001 | pass |
| DR-11 | band monotonicity | strictly increasing | pooled + 8/8 portfolios | pass |
| **DR-12** | monotone decile-step fraction | ≥ 0.9 | **0.5556** literal (1.0000 CI-aware) | **FAIL** |
| DR-13 | score PSI | ≤ 0.10 | 0.0006 | pass |
| **DR-14** | max feature CSI | ≤ 0.25 | **3.6344** (binding: `vintage_band`) | **FAIL** |
| DR-15 | DPD-family attribution @10–12m | ≤ 0.05 | 3.81% (alt. reading 20.92%) | pass |
| DR-16 | permuted-label AUC | ∈ [0.48, 0.52] | 0.5001 | pass |
| DR-17 | availability-at-time manifest | must exist | 62/62 covered | pass |
| **DR-18** | ΔAUC, cash-flow family removed | ≥ 0.04 | **0.0010** [-0.0057, 0.0066] | **FAIL** |
| **DR-19** | max ΔAUC gain from dropping any family | ≤ 0.0 | **0.0123** (Borrower profile) | **FAIL** |
| DR-20 | seeds run | ≥ 5 | 5 | pass |
| DR-21 | cross-seed AUC CI width | ≤ 0.02 | 0.0123 | pass |
| DR-22 | \|ΔAUC\| at 2× base rate | ≤ 0.03 | 0.0019 | pass |
| DR-23 | \|ΔAUC\| bureau missing | ≤ 0.02 | 0.0069 | pass |
| DR-24 | adverse-impact ratio (worst cut) | reported, ref. 0.80 | 0.72 (geography) | reported |
| DR-25 | TPR gap (worst cut) | reported, ref. 0.15 | 0.099 (geography) | reported |
| DR-26 | baseline ladder | reported | DPD-only 0.69 → logistic 0.86 → LightGBM 0.89 | reported |

Source: `validation/report/REPORT.md` + `validation/report/report.json`.

**The four honest fails, none of them tuned away:**

- **DR-12 — decile-step reversals.** Fails on the literal pre-registered arithmetic (0.5556);
  every individual reversal is a same-magnitude, low-count cell whose two Wilson confidence
  intervals overlap — a reading that only counts a reversal when it's statistically detectable
  clears **1.0000, pooled and in all 8 portfolios**. The gate stays on the literal reading by
  design; both numbers are published.
- **DR-14 — time-split drift on the vintage band.** `vintage_band` (a bank-style age bucket)
  binds at CSI 3.63, far over the 0.25 floor. This round banded a second elapsed-time feature
  (`months_since_moratorium_end`) the same way and cut its own CSI by ~65%, but the
  pre-registered out-of-time split embargoes training to months ≤12 and tests on months ≥24 — a
  structural 12-month gap that any account-age-correlated feature cannot survive at fine
  granularity, banded or not. Reported as a structural property of the embargo-gap design, not
  a defect in this round's fix.
- **DR-18 — the cash-flow family's own marginal contribution is small.** Removing the
  cash-flow/GST family alone costs only 0.001 AUC, far under the 0.04 floor the product's "we
  see cash flow before DPD" thesis needs. The signal isn't absent — it's *shared* across nine
  feature families: "Demand vs collection" (the round's largest single driver, ΔAUC 0.018) and
  "Income & balance" (ΔAUC 0.0085) carry much of the same underlying "money stopped arriving"
  event from different angles. The days-past-due family, the leading alternative explanation,
  carries only 3.8% of attention at 10–12 months' lead (DR-15) — the early-warning claim stands,
  but not through this one specific family, which is why DR-18 stays a reported fail.
- **DR-19 — the borrower-profile family, kept on purpose.** Dropping the seven static-profile
  columns (`constitution`, `state`, `city_tier`, `nic_group`, `tenor_months`,
  `interest_rate_pa`, `secured` — never `portfolio`, which is the one-model-many-portfolios
  mandate's own key) was tested this round: pooled AUC would *improve* by 0.0078 and ECE would
  improve too, which is exactly what a family that "may not be actively harmful" (DR-19's own
  wording) is supposed to look like when dropped. But Retail-Unsecured's own per-portfolio AUC
  would fall to 0.7375 — **below the 0.78 floor** — so the columns were kept and DR-19 is
  recorded as a fail rather than shipping a model that reads better in aggregate while breaking
  a portfolio's own guarantee. `MODEL_CARD.md` §17.

## Thresholds and cost model

The Amber/Red split minimises the bank's **expected rupee cost** over the frozen book — the
expected loss on NPAs a band misses, plus review and relationship-friction cost on the accounts
it flags — subject to the pre-registered rank-order criteria (DR-11: bands strictly monotone,
Red non-empty) as a feasibility filter, never as part of the objective itself
(`app/public/demo_data.json` → `thresholds`):

| | amber | red | expected cost | red-band precision | missed-NPA share |
|---|---|---|---|---|---|
| **Chosen (cost-minimising)** | 0.0747 | 0.2720 | **₹11.54 cr** | 84.5% | 17.6% |
| July 2026 hand-set pair | 0.0400 | 0.4000 | ₹11.83 cr | 90.6% | 14.4% |

The cost-minimising pair is **2.4% cheaper** than the hand-set pair the July build shipped,
while accepting a higher missed-NPA share and lower red-band precision — a deliberate trade:
the bank-wide expected cost accounts for review and friction cost on every flagged account, not
only the cost of the NPAs a band catches or misses. Cost assumptions: LGD 40% secured / 75%
unsecured, 6 months' income reversal, cure share 35% Red / 10% Amber (the single most uncertain
input), review cost ₹18,000 Red / ₹1,500 Amber, relationship friction 15%/2% of a year's
interest income. Every assumption is labelled `ASSUMPTION` with its reasoning; only
`effective_rate_pa`/`penal_rate_pa` are `BANK_API` (API 433). A ±50% sensitivity sweep on the
five most uncertain parameters is published beside the chosen pair, not hidden.

## Architecture

The product pipeline (`src/`, `app/`) lives in this repo. The real backend — auth, roles, the
audit trail, and the batch pipeline that runs this repo's own scripts as subprocesses — lives
in a **sibling repo, `rrsquad-platform`** (private during judging; flips public on submission
day), shared with DRISHTi's sister product SANKET:

- **Roles:** `admin` · `manager` · `credit_officer` · `relationship_manager`, enforced
  server-side; a credit officer is scoped to assigned portfolios.
- **Audit:** an append-only, hash-chained `audit_log` table — `UPDATE`/`DELETE` are both
  `REVOKE`d from the application's database role *and* blocked by a trigger, so tampering is
  rejected at the database, not merely discouraged.
- **Batch gate:** scoring is a batch job, never a live request. Seven stages — pull → enrich →
  generate → score → load → **verify** → publish. The verify stage runs this repo's own
  `validation/run.py` and attaches the result to the run record; a run that fails validation
  stays `candidate` and the previously-published run is left untouched — nothing this repo
  produces reaches an officer's screen without clearing the table above first.

## How to run locally

```bash
# 1) generate the panel, run the rigour pack, train + export (from this repo's root)
python3 -m generator.build --seed 20260709 --n 45000 --months 48 --out data   # validation population, ~9s
python3 src/rigor.py                        # calibration, leakage, OOT, baseline ladder
python3 src/export_demo.py                  # trains + writes app/public/demo_data.json (700-account sample)
python3 src/real_model.py                   # REAL-data validation model (needs ../msme_data/*.csv)

# 2) run the app
cd app && npm install && npm run dev

# 3) validate
make -C validation validate                 # writes validation/report/{REPORT.md,report.json,figures/}
python3 -m pytest -q                        # unit tests (repo root)
```

## What we did not build, and why

- **No retrain on real bank data.** The "Real-data model" (AUC 0.81, 95% CI 0.78–0.84, on 3,171
  real Indian MSMEs) is `src/real_model.py`'s independent, frozen July 2026 output, embedded
  verbatim — a separate proof-of-method on a different (real, annual, not monthly) data source,
  never blended into or used to fine-tune the synthetic-panel model this README describes.
- **The bank sandbox is a static mock, not a live data source.** Each Atlas endpoint returns its
  own structured mock record, and returns the same one regardless of the request (API 433 is the
  exception: a composite record with a slice for every API). Nothing here has ever scored,
  thresholded, or banded a real bank record.
- **Enumeration — finding a real account without already knowing one — is not proven live.**
  API 404's `selRangeLoanAcctId` range plus paging is the leading candidate route
  (`data/bank/SCHEMA.md`), but as of this writing it has not been exercised against a live,
  approved subscription.
- **DR-18 and DR-19 stay reported fails after both permitted tuning rounds** — the cash-flow
  family's marginal AUC contribution is small (the signal is shared, not absent) and the
  borrower-profile family is kept on purpose because dropping it breaks a portfolio floor. See
  "Validation" above; neither was chased further, per the plan's own freeze rule.
- **DR-12's literal-vs-CI-aware ruling is left open, not resolved.** The submission states both
  readings — the literal pre-registered fail and the CI-aware pass — rather than picking the one
  that clears the band.
- **The role-based frontend (`app/src/screens/*` — Login, Model & Trust, Thresholds, Admin) is
  still mid-build.** The deployed `drishti-ews.vercel.app` demo linked above runs the earlier
  four-tab static cockpit (`app/src/components/*`), not this newer, role-scoped one.

## Data and model cards

- [`MODEL_CARD.md`](MODEL_CARD.md) — features by family, splits, calibration, the full
  DM-8 round-2 record, known limits, provenance legend.
- [`DATA_CARD.md`](DATA_CARD.md) — the generator, every parameter's provenance
  (`high`/`medium`/`low`/`assumed` confidence), known unrealisms, research gaps.
- [`validation/README.md`](validation/README.md) and
  [`validation/criteria.yaml`](validation/criteria.yaml) — the pre-registration contract itself.

## Team, licence

**Team RR Squad** — Yuvraj Kundargi, Jai Wadhwa. IDBI Innovate 2026, Track 4 (Default
Prediction Model).

**All rights reserved.** No licence is granted. This repository is published so that the
evaluators of IDBI Innovate 2026 can read and assess the work; it is not offered for reuse.
Materials produced for the hackathon are subject to the non-disclosure agreement executed with
IDBI Bank on 31 August 2026, which governs ownership of the deliverables.

The raw licensed financial data used to build the real-data validation model is **not** part of
this repository — only derived aggregate metrics and anonymised examples
(`data/real_model.json`) are included. No AI-generated content is attributed anywhere in this
repository or its commit history.

---

> Hackathon prototype. The cockpit runs on a synthetic panel engineered to public sectoral
> baselines and bank-stated aggregate figures; the bank-sandbox deployment and any real
> customer data connect only after shortlisting, and — as of this writing — no live sandbox
> pull has ever populated this book.

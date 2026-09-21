# DRISHTi — Early-Warning System for IDBI's Lending Book

*An entry for **IDBI Innovate 2026 · Track 4 (Default Prediction)**.*

**🟠 Interim demo (pre-sandbox):** **https://drishti-ews.vercel.app** — no login, no backend
behind this particular static build. This is a development demo, not the submission
deployment.

**🟢 Submission deployment (live):** the bank-sandbox deployment (EC2 behind nginx, a real
backend, real auth — see "Architecture") **is live** in IDBI's AWS sandbox at the private
address **172.16.8.60**. There is no public IP by design: the host sits inside the bank's
VPC and is reached by SSM port forwarding, so a judge with sandbox access reaches it through
a session, and nobody else reaches it at all. Do not read the Vercel link above as "the
deployment."

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

**One score decides.** The export carries three numbers per account and only one of them is a
decision: `decision_score` (a four-month trailing mean of the monthly PD) is what the Amber/Red
thresholds were searched over, and therefore the only thing a band, a sort order, a timeline
band or a memo may come from. `pd` (the raw single-month probability) and `pd_smooth` are
carried for transparency and decide nothing; `pd_calibrated` is the decision score mapped
through a calibrator fitted on a fold neither the model nor the exported book has seen, and is
meant to be read as a probability rather than banded. `meta.policy_version` names the rule, so
a consumer that bands something else contradicts the file it loaded rather than diverging
silently — which is what had been happening: the platform API banded raw `pd`, putting 443 of
12,760 accounts in a different band from the book the model published.

**A band is not a classification.** Red says an account resembles the ones that went bad. SMA-1
says an account is 31–60 days overdue. Only the second is an arrears fact, it belongs to the
bank's own rules and the CBS, and no memo DRISHTi drafts instructs one: memos recommend a credit
review and report the observed CBS classification as a separate field.

## The headline

> **88.6% of Red-flagged accounts went NPA within 8 months (95% CI 84.0%–92.0%, n=245)**

Taken verbatim from `app/public/demo_data.json` → `metrics.honesty.headline` (DM-8 round 2, the
model's final, frozen state — this is **not** the number an earlier report or an earlier draft
of this README quoted; always read it fresh from the file). The same block states why this,
and not raw accuracy, is the number to publish:

| | value | source |
|---|---|---|
| **Red-band precision @ 8 months (the headline)** | **88.6%** (95% CI 84.0–92.0%, n=245 Red-flagged, 217 went NPA) | `demo_data.json` → `metrics.honesty`, `metrics.red_band_precision_8m` |
| Raw accuracy @ 8 months | 98.8% (95% CI 98.6–98.9%) | `metrics.raw_accuracy_8m` |
| **Flag-nobody baseline** | **97.3%** | `metrics.raw_accuracy_8m.flag_nobody_baseline` |
| Base rate @ 8 months / 12 months | 2.72% / 3.90% | `metrics.base_rate_8m`, `metrics.base_rate_12m` |
| **Missed-NPA share** — of every account that went NPA within 8 months, the share the model had left in Green | **16.1%** (95% CI 12.6–20.4%) | `metrics.missed_npa_share` |
| **ECE / Brier on the served decision score** | **0.0056 / 0.0195** raw; **0.0008 / 0.0186** after the policy-fold calibrator | `metrics.calibration_served` |

These are measured on a held-out book whose outcomes played no part in choosing the
thresholds — see "Thresholds and cost model". The previous build's 84.5% / n=283 figure was
measured at an operating point selected on that same book, and is superseded, not corrected.

**The rise from 84.5% to 88.6% is not the model getting better.** The two numbers sit at
different operating points: Red now starts at 0.3437 rather than 0.2720, so fewer accounts are
flagged Red (283 → 245) and the survivors are the riskiest, which lifts precision arithmetically.
Re-banding the *new* book at the *old* thresholds gives **82.3%** (237/288) — i.e. the model and
fold change on their own moved precision **down** 2.2pp, in line with AUC falling 0.902 → 0.885
(training on ~49% of accounts instead of ~70% so a policy fold could exist). The whole headline
gain is the threshold move. `MODEL_CARD.md` §8 carries the three-row decomposition.

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
holdout row across the whole out-of-time window (not one snapshot month): **88.2%** (95% CI
87.5–88.9%, n=8,176) — on the validation lane's own independently generated panel and its own
split. The 88.6% headline is the single frozen reference-month snapshot the demo cockpit
actually ships (`n_accounts_scored=12,760`, of which 245 sit in Red). The two now agree closely,
which they did not before 2026-09-21 (72.9% vs 84.5%): the pack had been banding the raw
per-month probability while the cockpit banded the smoothed decision score, so the two were
measuring different Red bands. Both are real and both are cited.

## How it works

```
population (8 portfolios, sourced mix) → shared latent stress S_t (one AR(1)/ramp process)
  → portfolio-specific observation channels (GST/utilisation/bounces; salary-gap/balance;
    moratorium-end; harvest-miss; EMI-stacking; LTV/rental; commute/salary)
    → noise, silent defaulters, transient stress (keeps the panel from being trivially separable)
      → ONE LightGBM (`portfolio` scored as a feature, not a separate model per portfolio)
        → cost-minimising Amber/Red thresholds (rupee cost, not AUC or a validation band)
          → watch-list, reason codes, runway estimate, network lens (illustrative)
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
- **The network lens is ILLUSTRATIVE, and labelled so everywhere it appears.** The
  trading-partner graph is *generated* — a few partners per account, drawn mostly from the same
  sector, with extra dependents attached to every Red account — so "accounts within one link of
  a Red" is a property of that construction, not a measurement of contagion. It is a second lens
  an officer can look through, it never alters a PD, a band or a threshold, and no number in this
  README or in the validation pack depends on it. Validating contagion detection would need a
  network defined **independently** of predicted risk (CRILC common exposures, a GST
  buyer–supplier graph) and a test of incremental predictive value on held-out outcomes; that has
  not been done, and the export says so in `ecosystem.illustrative_note`.
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
3. **0.902 (noise-hardened, whole-panel fit)** — after noise-hardening (silent/fast defaulters
   ~7.8% of the book, transient never-defaulting episodes ~22.5%, chain-link visibility 0.72)
   and a final borrower-heterogeneity pass.
4. **0.885 (shipped, 2026-09-21)** — same model, same panel, trained on less of it: a
   borrower-disjoint **policy fold** was carved out of the training side so the operating
   thresholds and the served-score calibrator are fitted somewhere the exported book never
   touches, and every fit and metric was restricted to `labelable == 1`. Training on ~49% of
   accounts instead of ~70% costs about 0.017 AUC. That is the price of an untouched
   evaluation, and it is a price worth paying. **Inside the pre-registered [0.82, 0.92] band**
   (DR-01, `validation/criteria.yaml`).

   95% CI **[0.8784, 0.8928]**, account-clustered bootstrap (`metrics.auc_ci`).

Both the floor (0.82, deliberately lowered from a first-draft 0.85) and the ceiling (0.92) were
pre-registered **before any model result existed**: "a floor of 0.85 would tempt tuning toward
separability; 0.82 sits credibly beside real 0.81" (published bank early-warning models land
around there; DRISHTi's own real-data validation model scores 0.81 — see below). The ceiling
exists for the same reason in reverse: a synthetic panel that scores above it has made the
problem too easy to be believable.

The validation lane keeps its own, independently regenerated 45,000×48 panel and its own
split, so its DR-01 figure and the exporter's are two real measurements of the same model
family on two separately generated panels, not one number reported twice. Both are cited
(`validation/report/REPORT.md` DR-01; `MODEL_CARD.md` §9).

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
the literal pre-registered arithmetic** (0.6667 worst portfolio) — not because the model doesn't rank
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

**Current report** (`validation/report/REPORT.md`, generated 2026-09-21T16:21:05+05:30 from
commit `1a4209cbf3ed`): **16 pass · 4 fail · 0 warn · 6 reported** — the same verdict on every
one of the 26 criteria as the run before the 2026-09-21 revision. Four *reported* numbers moved
because the pack now bands on the decision score rather than the raw per-month probability
(DR-02 0.729→0.8821 on a smaller Red band, DR-24 0.9195→0.9405, DR-25 0.0209→0.0240) and DR-12's
literal fraction rose 0.5556→0.6667 without clearing its floor. No criterion passed that used to
fail, and none failed that used to pass.

| ID | Metric | Band | Observed | Verdict |
|---|---|---|---|---|
| DR-01 | grouped AUC | ∈ [0.82, 0.92] | 0.8885 | pass |
| DR-02 | red-band precision @8m (pooled) | reported | 88.2% (n=8,176) | reported |
| DR-03 | annual slippage ratio | ∈ [0.03, 0.05] | 3.31% | pass |
| DR-04 | label base rate (annual) | reported | 3.63% | reported |
| DR-05 | OOT/holdout AUC ratio | ≥ 0.95 | 1.0009 | pass |
| DR-06 | per-portfolio AUC (×8) | ≥ 0.78 each | worst Auto 0.8374, best Agri 0.9069 | pass |
| DR-07 | AUC by cut (76 cells) | reported | — | reported |
| DR-08 | ECE overall | ≤ 0.02 | 0.0010 | pass |
| DR-09 | ECE per cut | ≤ 0.04 | all cells pass | pass |
| DR-10 | Δ Brier (calibrated − raw) | < 0.0 | −0.0001 | pass |
| DR-11 | band monotonicity | strictly increasing | pooled + 8/8 portfolios | pass |
| **DR-12** | monotone decile-step fraction | ≥ 0.9 | **0.6667** literal (1.0000 CI-aware) | **FAIL** |
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
| DR-24 | adverse-impact ratio (worst cut) | reported, ref. 0.80 | 0.70 (geography) | reported |
| DR-25 | TPR gap (worst cut) | reported, ref. 0.15 | 0.102 (constitution) | reported |
| DR-26 | baseline ladder | reported | DPD-only 0.69 → logistic 0.86 → LightGBM 0.89 | reported |

Source: `validation/report/REPORT.md` + `validation/report/report.json`.

**The four honest fails, none of them tuned away:**

- **DR-12 — decile-step reversals.** Fails on the literal pre-registered arithmetic (0.6667);
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

The Amber/Red split minimises the bank's **expected rupee cost** — the expected loss on NPAs a
band misses, plus review and relationship-friction cost on the accounts it flags — subject to the
pre-registered rank-order criteria (DR-11: bands strictly monotone, Red non-empty) as a
feasibility filter, never as part of the objective itself
(`app/public/demo_data.json` → `thresholds`).

**Chosen on a policy fold, then frozen, then measured.** The cost search reads future outcomes
to price a candidate pair. Until 2026-09-21 the book it read was the held-out test book — the
same book that then reported the pair's Red-band precision, missed-NPA share, workload and band
monotonicity. The thresholds are now chosen on a third, borrower-disjoint fold carved out of the
*training* side (fit ≈49% of accounts / policy ≈21% / test 30%, `export_demo.three_way_split`),
frozen, and only then applied to the untouched test book that this cockpit ships. The held-out
book is the same size and the same accounts it always was — the policy fold came out of train,
not out of test. A test asserts the property rather than the intention: rewrite every outcome in
the test fold and the fitted thresholds do not move.

Everything that fits or grades is also restricted to `labelable == 1` — rows whose full
12-month forward window exists inside the panel, the same eligibility rule `validation/
criteria.yaml` registered. Recent rows without a complete window are still **scored** (the
cockpit has to draw them); they are never **graded**.

| | amber | red | expected cost | red-band precision | missed-NPA share |
|---|---|---|---|---|---|
| **Chosen (cost-minimising)** | 0.0693 | 0.3437 | **₹6.68 cr** | 86.5% | 18.5% |
| July 2026 hand-set pair | 0.0400 | 0.4000 | ₹6.80 cr | 91.3% | 15.1% |

Both rows are priced on the **policy fold** (8,933 accounts), which is the book the search
sees; they are not comparable to the rupee totals this table carried before 2026-09-21, which
were priced on the 12,760-account test book. The precision and missed-NPA columns are likewise
the policy fold's — the numbers the *test* book then produced at the chosen pair are the
headline 88.6% and missed-NPA 16.1% above, and those are the ones to quote.

The cost-minimising pair is **1.7% cheaper** than the hand-set pair the July build shipped,
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

- **No retrain on real bank data.** The "Real-data model" (AUC 0.81, 95% CI 0.78–0.84) is
  `src/real_model.py`'s independent, frozen July 2026 output, embedded verbatim — a separate
  proof-of-method on a different data source, never blended into or used to fine-tune the
  synthetic-panel model this README describes.

  **What its numbers count, exactly.** The table is **3,171 companies** and **17,031
  company-year rows**, of which **1,284 are positive rows across 851 distinct companies**.
  Those are three different denominators and the difference matters: the target is
  "does this company default in the next two financial years", so one default event labels
  up to two preceding company-years, and 1,284 is a count of *rows*, not of companies and
  not of defaults. 851 companies defaulted. Anyone quoting "1,284 real defaults" is quoting
  the row count under the wrong noun.

  **What it is evidence of.** That a two-year, financial-statement model has real signal on
  real Indian MSMEs — **complementary evidence**, not external validation of the model this
  README describes.

  **And 0.81 is the most permissive of four designs** (experiment E3,
  `validation/report/experiments/real_data_scoping/`). The shipped figure comes from a
  company-grouped *random* split, which lets a 2019 row help predict a 2019 outcome at another
  company — something a forward-looking user cannot do. Tested forwards instead: temporal
  holdout **0.7968** [0.740, 0.838]; temporal *and* company-disjoint **0.7214** [0.657, 0.775];
  and with the outcome window pushed out a year to stand in for filing lag (the source carries
  no filing-availability date at all) **0.781** [0.750, 0.811]. The strictest design is also
  the smallest training set, so part of that drop is less data rather than a harder test — but
  the direction is consistent and 0.81 should be read as the ceiling of the range, not its
  centre. DRISHTi's shipped model is a twelve-month *behavioural* model on monthly
  account conduct; this one is an annual *balance-sheet* model on filed statements. Different
  horizon, different features, different unit of observation, different population. It does
  not transfer, and it is not offered as though it does. The company-clustered bootstrap
  behind the interval is retained precisely because rows within a company are not independent.
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
> baselines and bank-stated aggregate figures. The bank-sandbox deployment is live (private
> IP 172.16.8.60, reached by SSM port forwarding), but real customer data connects only
> after shortlisting: no live sandbox pull has ever populated this book.

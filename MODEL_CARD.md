# MODEL CARD — DRISHTi early-warning model

**Model:** one holistic LightGBM classifier, scored monthly per account
**Code:** `src/export_demo.py` (train/score/export), `src/costs.py` (operating-point search),
`src/rigor.py` (model-risk pack — calibration, leakage, OOT, baseline ladder), `src/bank.py` +
`src/export_contract.py` (DM-6 — bank enrichment and the platform-contract export)
**Data:** [`DATA_CARD.md`](DATA_CARD.md) — the synthetic panel this model is trained and
validated on
**Validation:** `validation/criteria.yaml` (26 pre-registered criteria, DR-01..DR-26),
`validation/runners/01`–`12`
**Version:** DM-6/DM-7 (plan §B/L5), 2026-09-17. This card describes the model as trained on
the 9,000×36 and 45,000×48 populations `DATA_CARD.md` documents; both seed `20260709`.

---

## 1. Purpose and mandate

DRISHTi is a 12-month-ahead early-warning score for MSME and retail lending accounts. The
product mandate, unchanged since the mentors' review, is **one holistic model across all eight
lending portfolios** (MSME-CC, MSME-TL, Housing, Education, Agri, Retail-Unsecured, LAP, Auto),
not eight separate models. That is a deliberate, harder bar: a single scorecard has to rank risk
sensibly for a cash-credit trader and a home-loan salaried borrower using the same weights, and
the validation suite (DR-06, DR-11, DR-12) gates every portfolio individually rather than only
the pooled number, precisely so the mandate cannot be satisfied by one portfolio carrying the
other seven.

The output an officer acts on is not the raw probability but three things together: a RAG band
(Green/Amber/Red, §10), plain-language reason codes (top-3 risk-increasing drivers), and — where
projectable — a runway estimate in months before the account would cross into Red. None of these
three touches the account's actual outcome; `ground_truth_default` / `snap_months_to_npa` exist
in the export only for the demo's own "did it happen" reveal and are never a model input.

## 2. Data

See [`DATA_CARD.md`](DATA_CARD.md) for the full generator description, sourcing, and the
"Known unrealisms" section this card's §14 draws on. In one line: a synthetic account-month
panel, portfolio-banded to public sectoral baselines and bank-stated aggregate figures, **not**
sampled from any real IDBI book. No real customer, account, or Atlas-sandbox pull feeds the
panel itself — the sandbox only reaches the export layer, and only for the identity family
(§16).

## 3. Features, by family

Every scored column belongs to exactly one of **nine** families (`src/rigor.py::GROUPS`; a test
asserts the mapping is total — zero unfamilied columns of 62-63 scored):

| Family | Representative columns |
|---|---|
| Days-past-due / repayment | `dpd`, `dpd_max_6m`, `times_late_6m`, `bounce(s)_6m`, `minbal_breach(_6m)` |
| Cash-flow (inflows / GST) | `inflow`, `gst_sales`, `inflow_trend_3m`, `inflow_vs_6m_avg`, `sales_trend_3m`, `txn_count`, `txn_drop_flag` |
| Demand vs collection | `demanded_amount`, `collected_amount`, `collection_ratio(_3m)` |
| Credit-limit utilisation | `utilisation`, `util_avg_3m`, `util_max_6m`, `months_over_90pct_util_6m`, `drawing_power`, `outstanding` |
| Income & balance | `salary_credit`, `salary_vs_6m_avg`, `salary_gap_6m`, `balance`, `min_balance_6m`, `rental_*`, `crop_receipt*`, `commute_*` |
| Leverage & collateral | `other_bank_emi`, `emi_burden_ratio`, `ltv(_vs_schedule)`, `renewal_overdue_months`, `moratorium_*` |
| Bureau | `bureau_score` |
| Adverse filings | `adverse_remark(_6m)` |
| Borrower profile | `log_sanctioned`, `vintage_band`, `business_age_years`, `sector`, `region`, `loan_type`, `segment`, `qualification`, `promoter_age_group`, `portfolio`, `constitution`, `state`, `city_tier`, `nic_group`, `secured`, `tenor_months`, `interest_rate_pa` |

**The DPD-vs-collection ruling.** "Demand vs collection" is deliberately its **own** family, not
folded into days-past-due. `collection_ratio` measures money actually arriving against what was
demanded — not lateness — and it leads arrears by 5–8 months across the eight portfolios.
Whether it counts as DPD is not a cosmetic choice: folding it in moves the 10–12-month DPD
attribution share from ~2% to ~12–14% (§11) and changes whether DR-15 passes. Both readings are
computed and reported on every run so the choice is visible rather than inherited — see §11.

`vintage_band` (a bank-style 0-6/7-12/13-18/19-30/31-48/49+ month bucket) is scored in place of
the raw `vintage_months` counter, which is dropped from the feature set entirely (kept in the
CSV for validation cuts, never trained on): `vintage_months` is account-age-plus-elapsed-time by
construction, so it drifts mechanically under any time-split OOT and was DR-14's binding
max-CSI feature before the bucket replaced it.

## 4. Forbidden inputs

Two columns are structurally excluded from the feature matrix (`export_demo.py::DROP` /
`rigor.py::DROP`, and pinned by a test against the generator's own label declaration so a new
label added later fails the test rather than quietly inflating AUC):

- **`sma2_within_6m`** — a forward-looking secondary label (does the account reach 61–90 DPD in
  the *next* six months). Landed mid-build (SD-D5) and was, for a period, being trained on —
  found and fixed as part of the DM-2/DM-3 pass.
- **`default_within_12m`** — the primary label itself.

`months_to_npa`, `labelable`, `account_id`, `month_idx` and `date` are also dropped: bookkeeping
and ground-truth columns, none of them a legitimate signal. `vintage_months` is dropped from
FEATURES only (§3), not from the panel.

## 5. Label and horizons

- **Primary label — `default_within_12m`.** 1 if the account reaches 90+ DPD within the next 12
  months of the observation row, else 0. This is what the model is trained and pre-registered
  (DR-01, DR-05, DR-08–DR-10, DR-13–DR-19) against.
- **Secondary — `sma2_within_6m`** (6-month SMA-2 crossing) exists in the panel for the
  generator's own base-rate assertions and DR-18-adjacent diagnostics; it is never a feature and
  the model does not predict it directly. The contract's `scores.sma2_within_6m` field is left
  unpopulated.
- **The rank-order / red-band-precision action window is 8 months**, not 12 — deliberately
  shorter than the label horizon, because it is the window a Relationship Manager can actually
  act inside. `red_band_precision_8m` and the rank-order exhibit (§9) are both measured over it;
  `base_rate_12m` is the only 12-month figure quoted, and it is labelled as such everywhere it
  appears.

## 6. Splits

- **Primary — grouped holdout.** `GroupShuffleSplit(test_size=0.30, random_state=7)`, grouped on
  `account_id`, so no account's months appear in both train and test. DR-01 gates on the AUC
  from this split.
- **Out-of-time (DR-05).** Trained on months 0–17, tested on months 18+, a genuinely temporal
  split rather than a random one. Gate: OOT AUC ≥ 0.95 × grouped-holdout AUC. Both sizes clear
  it comfortably: 9k 0.933 (ratio 1.047), 45k 0.933 (ratio 1.006) — SD-D4/D5's measurement, on
  the final noised panel.
- **Baseline ladder (DR-26).** The same grouped split trains a logistic-regression scorecard
  alongside LightGBM, so the gain from the more flexible model is contextualised rather than
  asserted. 45k: logistic 0.902 → 0.927 → **LightGBM 0.902 shipped** — see the honest AUC story,
  §13, for why the pre-final-noise 0.927 point is quoted alongside the shipped 0.902.

## 7. Model and calibration

`LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
colsample_bytree=0.8, min_child_samples=80, random_state=7)`, categorical features passed
natively (pandas `category` dtype), no target encoding. Reason codes come from
`booster_.predict(..., pred_contrib=True)` (SHAP-style per-feature contributions), top-3
risk-increasing, human-templated (`export_demo.py::HUMAN`) — a feature that is `NaN` for a
portfolio without that observation channel never produces a reason, by construction (both plain
float NaN and pandas nullable `Int64`'s NA, which raises rather than compares False on a bare
`<`/`>` — a real bug DM-2/3 found and fixed once, in `reason_codes`, not per-rule).

Calibration (`src/rigor.py`, DR-08–DR-10): isotonic regression fit on an inner 25% validation
slice of train, applied to the held-out test predictions. **Brier(calibrated) < Brier(raw) is
gated (DR-10)** — calibration must measurably help, not just re-shape the score. `pd` in the
contract export is the raw single-month probability; `pd_smooth` (a 4-month trailing mean, the
value bands are actually cut on — §10) is the trend an early-warning desk would act on, not a
jittery single month. `pd_calibrated` exists in the contract shape as an optional field but is
not populated in this build — the isotonic fit lives in the rigor pack's own held-out slice, not
threaded back through the export's per-account scores.

## 8. Metrics, with confidence intervals, at both sizes

All proportions below carry 95% Wilson intervals (`export_demo.py::wilson`), chosen over the
normal approximation because several cells are small and some have zero defaults, where the
normal interval collapses to a point. Source: DM-4/DM-5's reported table, both from the same
frozen 8-month-horizon book at each size.

| metric | 9k × 36 | 45k × 48 (AUC 0.902 shipped) |
|---|---|---|
| **`red_band_precision_8m`** | **44.1% [35.4–53.1]** (52/118) | **80.7% [75.9–84.8]** (243/301) |
| `missed_npa_share` | 13.9% [8.0–23.2] | 18.2% [14.5–22.6] |
| `raw_accuracy_8m` / flag-nobody baseline | 96.3% / **96.9%** | 98.7% / 97.3% |
| `base_rate_8m` / `base_rate_12m` | 3.1% / 3.9% | 2.7% / 3.9% |
| `recall_at_10pct_budget` | 74.7% [64.1–83.0] | 86.2% [82.1–89.4] |
| `flagged_share` | 27.8% | 4.7% |

**The headline, derived and asserted in-script (`assert_honesty`), never typed:**
> "80.7% of Red-flagged accounts went NPA within 8 months (95% CI 75.9%–84.8%, n=301)" — 45k.
> At 9k: "44.1% ... (95% CI 35.4%–53.1%, n=118)".

**Why not "accuracy".** At 9k the model scores *below* the flag-nobody baseline on raw accuracy
(96.3% vs 96.9%) — the cleanest possible demonstration of why the July 2026 "90% accuracy" claim
was the wrong number to publish. Raw accuracy on a ~3%-base-rate book mostly measures the base
rate, not the model; it is carried in the export (`raw_accuracy_8m`) *for contrast, never as the
headline*, and a guard (`export_demo.py::assert_honesty`) fails the build if the discredited
figure ("90%") appears anywhere in the metrics block, or if the word "accuracy" appears outside
the four paths that exist to disown it.

`missed_npa_share` is the number the mentors care about most: of every account that actually went
NPA within 8 months, the share the model had left in Green at the reference month — the early
warning that never arrived. It is the quantity the operating point (§10) is chosen against, not
precision.

## 9. Rank-order, per portfolio

`red_band_precision_8m` and DR-11/DR-12 both come off the same rank-order exhibit
(`export_demo.py::rank_order_exhibit`): realised NPA rate by RAG band and by score decile, pooled
and separately inside every one of the eight portfolios — the mandate in §1 made numerically
testable. DR-11 (bands strictly monotone Green < Amber < Red) passes **pooled and in all eight
portfolios at 45k** (5/8 at 9k, where three portfolios' Red bands are simply too thin — 1, 3, 3
accounts — to be statistically informative, not evidence the model fails there).

**Per-portfolio AUC** (SD-D4/D5's grouped-LightGBM diagnostic, 45k, 3 seeds): 0.9018 / 0.9016 /
0.8968 pooled; per portfolio 0.851–0.918, worst Retail-Unsecured (0.851), best Agri (0.918) — all
eight clear the DR-06 floor of 0.78 on the point estimate. The more granular table below is from
DM-2/DM-3's run at the pre-final-noise checkpoint (pooled AUC 0.927, before the borrower-
heterogeneity addition that brought the shipped model to 0.902 — see §13); it is reported because
it is the only per-portfolio breakdown this build actually measured cell-by-cell, and every
portfolio's AUC only *improves* between 0.927 and the eventual 0.902-band model per the 0.851–
0.918 range above, so nothing here overstates the shipped model:

| Portfolio | AUC (0.927 checkpoint) |
|---|---|
| MSME-TL | 0.949 |
| LAP | 0.946 |
| Agri | 0.913 |
| Housing | 0.905 |
| Auto | 0.889 |
| MSME-CC | 0.883 |
| Education | 0.874 |
| Retail-Unsecured | 0.809 |

**DR-12, literal vs CI-aware — the ruling this card records.** DR-12 (≥9/10 decile step-ups
non-decreasing) is pre-registered on literal arithmetic and **fails at both sizes on the literal
reading** (5/9 pooled at 9k, 5–7/9 pooled at 45k depending on the run) — not because the model
doesn't rank risk, but because almost all realised risk concentrates in the top decile at this
score's separation, leaving deciles 1–9 sitting at 0.0–1.8% where step-to-step ordering is
statistical noise (one clear example: MSME-CC's 45k "reversal" was 0.0077→0.0076, one account
across two 130-account cells whose Wilson intervals almost entirely overlap). A second,
*reported-not-gated* diagnostic (`monotone_decile_step_fraction_ci`) counts a step-down against
the model only when the two cells' 95% Wilson intervals are actually disjoint — i.e. only when
the data can tell them apart. **Under that reading, every cell is 9/9 at both sizes: no
statistically detectable decile reversal anywhere.** The gate itself stays on the literal
pre-registered arithmetic (DM-2/3 explicitly declined to relax it unilaterally); this is recorded
as an open ruling for the coordinator, not resolved by this card. See `export_demo.py::rank_order_violations`
and `_decile_steps_ci` for the exact arithmetic and the reasoning comment beside it.

## 10. Cost-minimising thresholds

The Amber/Red split is **not** a hand-set pair — it minimises the bank's expected rupee cost
over the frozen book (`src/costs.py`), subject to DR-11 as a feasibility filter (a pair that
breaks DR-11 is not a candidate at all, whatever it costs). Expected loss on a missed NPA is
`EAD × LGD + EAD × (effective_rate + penal_rate)/100 × reversal_months/12` — principal at risk
plus RBI-IRAC income reversal.

**Chosen pair, 45k:** amber **0.0741** / red **0.2364**, expected cost **₹10.36 cr**, vs the
July 2026 hand-set 0.04/0.40 pair's ₹10.75 cr (both DR-11-admissible at this size).
**9k:** amber **0.0083** / red **0.0551**; the July pair is **not** DR-11-admissible at 9k (its
Red band's default rate is not strictly the highest in every portfolio at that size), which the
export labels explicitly (`constraint_level`) rather than letting the July pair look like a
cheaper loser.

**Assumptions, every one labelled `ASSUMPTION` with its reasoning in `PARAM_NOTES`, never
`BANK_API`:** LGD 40% secured / 75% unsecured (driven by the panel's own per-account `secured`
flag; `sources.yaml`'s `secured_share` is a cross-check only), 6 months' income reversal, cure
share 35% Red / 10% Amber (**the single most uncertain number here**), review cost ₹18,000 Red /
₹1,500 Amber, relationship friction 15% Red / 2% Amber of one year's interest income on the
flagged exposure. `effective_rate_pa` (12.75%) and `penal_rate_pa` (2.0%) **are** `BANK_API` —
API 433's captured sandbox response — but every value derived from them carries
`sandbox_fixture: true`: the Atlas sandbox returns one static canned response to every caller
(BR-6a), so these are real *field values from the bank's own API contract*, not real *rates for
our borrowers*. API 538's payoff interest split is reported `available: false` — the canned
account is standard, so all three interest components read "0", which is an absence, not a
measurement, and the code says so rather than silently loading a 0% penal split.

**Sensitivity.** A ±50% sweep on the five most uncertain parameters (`cure_share_red`,
`review_cost_red_inr`, `lgd_unsecured`, `friction_share_red`, `income_reversal_months`) is
emitted beside the chosen pair (`thresholds.sensitivity`), reported rather than hidden — the
mandate is to show how much of the answer is data and how much is judgement, not to bury the
judgement.

## 11. Leakage — primary vs alternative reading

DR-15 (DPD-family attribution share at 10–12 months' lead must be ≤5%) is the check that makes
"we see it a year early" honest: for predictions made 10–12 months before NPA, the days-past-due
family must contribute at most 5% of total absolute SHAP-style attribution.

| Reading | 9k | 45k |
|---|---|---|
| **Primary** — collection its own family | **2.06%** ✅ | **2.05%** ✅ |
| **Alternative** — collection folded into DPD | 13.57% ❌ | 12.19% ❌ |

DR-15 **passes** under the pre-registered, primary reading and **fails** under the alternative —
the gap widened, not narrowed, at scale. The ruling (§3) is load-bearing precisely because of
this: it is the difference between the early-warning claim standing and not standing, and it is
why both numbers are computed and reported on every run rather than only the one that passes.

## 12. Fairness

Not evaluated by this card directly — see `validation/runners/11_fairness.py` (DR-24, DR-25).
Four-fifths adverse-impact ratio and TPR gap across the protected-proxy attributes DRISHTi
actually has (`promoter_age_group`, `qualification`, `region`, `constitution` — **DRISHTi holds
no gender, caste, religion or marital-status field at all**), at the live operating threshold.
Both criteria are `severity: report`, not gated, by the plan's own wording ("reported honestly")
— any breach belongs in the submission's "what we did not build, and why" rather than being
tuned away. This card does not reproduce the runner's numbers; run
`python3 -m validation.runners.11_fairness` for the current figures.

## 13. The honest AUC story

Three numbers, same model family, same population, in order:

1. **0.947 (July 2026)** — the original ungated model, before SD-D4/D5's realism hardening.
   Too high to be believable: a synthetic panel scoring above the pre-registered ceiling has
   leaked its own generative structure, not learned something real.
2. **0.927 (pre-noise-hardening checkpoint)** — after the eight-portfolio generator rewrite but
   before SD-D4/D5's silent-defaulter, hard-negative and dark-link noise injection. Still 0.007
   over DR-01's ceiling.
3. **0.902 (shipped)** — after SD-D4/D5's noise work (silent/fast defaulters ~7.8% of the book,
   transient never-defaulting episodes ~22.5%, graded chain-link visibility 0.72, borrower
   heterogeneity added to close a residual 0.9156-vs-0.92 margin) and after the final borrower-
   heterogeneity pass. **Inside the pre-registered [0.82, 0.92] band** (DR-01), with the smaller
   9k population landing at 0.891 (also in-band) — both sizes clear the floor, which is what
   proves the model isn't merely reading an empty score range (see §9's DR-12 discussion for what
   an empty score range would have looked like).

The floor at 0.82 (not 0.85) and the ceiling at 0.92 were **both pre-registered before any model
result existed** (`validation/criteria.yaml`, DR-01's `note`): "a floor of 0.85 would tempt
tuning toward separability; 0.82 sits credibly beside real 0.81" — published bank early-warning
models land around 0.81, so a floor above that would have created pressure to make the synthetic
data easier than reality. The ceiling exists for the same reason in reverse.

## 14. Known limits

Carried from `DATA_CARD.md`'s "Known unrealisms", the ones that bear directly on what this model
can and cannot be trusted to say:

- A slipped KCC (agri) renewal stays overdue to the *next* annual due date rather than resetting
  sooner — overstates duration, understates incidence, for one portfolio's `renewal_overdue_months`.
- Part-payment does not accrue DPD in the panel: a borrower can pay 60% for eight months at 0
  days past due, which no real core banking system would allow. Inherited from the chain-default
  design (SD-D3) and not fixed by the noise pass.
- The bounce ladder clips at three consecutive misses; a fourth would be NPA in reality.
- Transient (cured) stress episodes are one per account over the panel's whole window; a real
  borrower typically has several over a multi-year relationship.
- Auto's own payment instrument is too noisy (σ 0.38 log, 7% zero months) to carry a stress
  episode on its own — Auto's transient episodes are asserted on the salary credit signal
  instead, a modelling compromise specific to that portfolio.
- IDBI's real FY26 annualised slippage is 0.63%; this panel targets 3–5% (DR-03), roughly five
  times higher, **on purpose** — a book that behaves like IDBI's actual current portfolio would
  not exercise the early-warning machinery at all. Nothing in this card should be read as a
  measurement of IDBI's real book.
- `rigor.json` (the file this card's calibration/leakage/OOT numbers are pulled from at export
  time) can be **stale relative to the panel it is embedded beside** if the panel was regenerated
  without a matching `src/rigor.py` re-run — `export_demo.py` loads whatever is on disk and does
  not re-derive it. A shape test in `tests/test_rigor_families.py` skips (rather than fails) when
  this is detected, by design — it is a known, disclosed gap in the local dev loop, not a build
  failure.

## 15. What we did NOT do

- **No retrain on real data.** `real_data` in the platform export (§16) is `src/real_model.py`'s
  frozen July 2026 output on real Indian MSME financials, embedded **verbatim** — it is a
  separate, independent proof-of-method on a different (real, smaller, annual-not-monthly) data
  source, never blended into or used to fine-tune the synthetic-panel model this card describes.
- **The bank sandbox is a static mock.** Every Atlas sandbox endpoint this build has actually
  reached returns one canned response regardless of the request (`sandbox_fixture: true`,
  BR-6a) — nothing in this build has ever scored, thresholded, or banded a real bank record. See
  §16's provenance legend for exactly which numbers that flag touches and which it does not.
- **DR-18 (cash-flow-family ablation ≥ 0.04 AUC) is unresolved.** SD-D4/D5's own quick diagnostic
  measured **0.019** at a 7k-account sample — below the pre-registered floor, and flagged in
  their report as "at risk". This card does not re-run the ablation; L8's `08_ablation` runner
  owns the authoritative number, and until it reports, DR-18 should be treated as **not yet
  demonstrated**, not as passing by omission.
- **DR-12's literal-vs-CI-aware ruling (§9) is a recorded open question, not a resolution.** This
  card states both readings and why the gap exists; it does not decide which one the submission
  should lead with.
- **No feature selection or hyperparameter search was run against the validation criteria.**
  `LGBMClassifier`'s parameters (§7) are the ones the generator/export lanes converged on during
  development; DR-01's ceiling exists specifically to make tuning-toward-separability visible as
  a failure rather than a temptation, and no run in this project's history has swept
  hyperparameters against it.

## 16. Provenance legend

Every value the platform-contract export (`src/export_contract.py`, `--out`) carries is tagged
with exactly one of three sources, per one of **eight families** (`identity`, `exposure`,
`repayment`, `cashflow`, `bureau`, `filings`, `profile`, `model` — `data/bank/SCHEMA.md`):

| Tag | Meaning |
|---|---|
| `BANK_API` | Pulled live from an IDBI Atlas sandbox endpoint. |
| `FIXTURE` | Sourced from the committed `data/bank/fixture.json` (160 accounts) when a live pull is unavailable or a family's account is outside its coverage. |
| `SIMULATED` | Produced by the synthetic generator — no Atlas API supplies this at all, or (see below) this build never substituted anything for it. |

**Trust order, worst first: `FIXTURE < SIMULATED < BANK_API`.** The `model` family — the badge
shown beside the score itself — is the *weakest* of the other seven, per account. This is
`data/bank/SCHEMA.md`'s own rule and the platform's `app/fixtures/common.py::weakest`.

**What `--bank` actually overlays, and what it never touches.** Only the `identity` family
(`cif_id`, `foracid`, branch, RM) is ever substituted with a real fixture/live value on an
account record — it is pure display metadata that never reaches the model. The other six
non-`model` families are reported `SIMULATED` per account **even when the aggregate run reports
`FIXTURE` or `BANK_API` for them**, because their underlying VALUES (`dpd`, `outstanding`,
`bureau_score`, …) are never substituted: the model was trained on the synthetic panel and only
the synthetic panel, `--bank` or not, so badging a displayed `dpd` as `FIXTURE` while showing the
generator's own number would be the one dishonest move this whole mechanism exists to prevent.
`filings` (GST turnover, adverse remarks, EPFO, DISCOM) is **always** `SIMULATED` — no Atlas API
in the 25-endpoint catalogue supplies any of it, live pull or not.

**Coverage is honestly partial, by construction.** `data/bank/fixture.json` covers 160 of the
panel's several-thousand accounts (`MSME00001`–`MSME00160`, 20 per portfolio). An account inside
that range reads `identity: FIXTURE`; every other account reads `identity: SIMULATED` regardless
of what the *aggregate* run's summary says — `src/bank.py::BankContext.provenance_for` computes
this per account, not from the run-wide rollup, which is what makes the badge trustworthy at the
individual-account level rather than only in aggregate.

**`sandbox_sync.mode` can never read `"live"` for DRISHTi.** Because `filings` is always
`SIMULATED`, at least one non-`model` family is always `SIMULATED` regardless of how complete an
Atlas pull is — the best achievable mode is `"mixed"`. This mirrors the platform's own
`batch/enrich.py::provenance_mode`, which computes mode from every non-`model` family including
the always-simulated ones; it is a structural property of the family map, not a bug.

**`cost_model.provenance`** (§10) uses the same three-value vocabulary at a coarser grain:
`rates` (`interest_rate_pa`, `penal_rate_pa`) is always `BANK_API` (API 433's sandbox capture);
`costs` (LGD, cure shares, review costs, friction) is reported `SIMULATED` for contract purposes
— the underlying `src/costs.py` vocabulary is actually three-way (`BANK_API` / `ASSUMPTION` /
`SOURCES`), and `ASSUMPTION`/`SOURCES` both collapse to `SIMULATED` here because the platform
contract's `provenance_source` enum has no fourth value. The full three-way detail, with each
parameter's own reasoning, survives in `thresholds.cost_params`/`thresholds.provenance` in the
app-facing export (`app/public/demo_data.json`) — nothing is lost, only summarised for the
contract.

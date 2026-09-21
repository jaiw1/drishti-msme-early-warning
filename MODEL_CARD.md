# MODEL CARD — DRISHTi early-warning model

**Model:** one holistic LightGBM classifier, scored monthly per account
**Code:** `src/export_demo.py` (train/score/export), `src/costs.py` (operating-point search),
`src/rigor.py` (model-risk pack — calibration, leakage, OOT, baseline ladder), `src/bank.py` +
`src/export_contract.py` (DM-6 — bank enrichment and the platform-contract export)
**Data:** [`DATA_CARD.md`](DATA_CARD.md) — the synthetic panel this model is trained and
validated on
**Validation:** `validation/criteria.yaml` (26 pre-registered criteria, DR-01..DR-26),
`validation/runners/01`–`12`
**Version:** DM-8 round 2 (plan §B/L5), 2026-09-17 — **the last permitted tuning round.** The
plan allows two model-tuning rounds; this is round 2, and every number in this card from here
on is reported as measured, not chased toward a band.

**Revision 2026-09-21 — not a tuning round.** No hyperparameter, feature, label, criterion or
threshold band changed. What changed is *where* the operating point and the calibrator are
fitted, and *which rows* are eligible to be fitted or graded: thresholds and the served-score
calibrator now come from a borrower-disjoint **policy fold** carved out of the training side
(§6), and every fit and metric is restricted to `labelable == 1` (§6). The export also names
the one score every consumer must band on (`decision_score`, §7) — the platform API had been
banding the raw single-month `pd`, which at the saved thresholds put 443 of 12,760 accounts in
a different band from the book the model published. The headline moved 84.5% → **88.6%** and
AUC 0.902 → **0.885**; §8 carries both columns side by side and says which is which. §17 is round 2's own record: what changed,
what was tested and rejected, and the two DR-18/DR-12 findings that stay reported fails by
design. This card describes the model as trained on the 9,000×36 and 45,000×48 populations
`DATA_CARD.md` documents; both seed `20260709`.

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
| Leverage & collateral | `other_bank_emi`, `emi_burden_ratio`, `ltv(_vs_schedule)`, `renewal_overdue_months`, `moratorium_active` |
| Bureau | `bureau_score` |
| Adverse filings | `adverse_remark(_6m)` |
| Borrower profile | `log_sanctioned`, `vintage_band`, `months_since_moratorium_end_band`, `business_age_years`, `sector`, `region`, `loan_type`, `segment`, `qualification`, `promoter_age_group`, `portfolio`, `constitution`, `state`, `city_tier`, `nic_group`, `secured`, `tenor_months`, `interest_rate_pa` |

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

**Round 2:** the same mechanism resurfaced on `months_since_moratorium_end` (elapsed months since
an Education-portfolio account's moratorium ended — negative while still inside it), which became
DR-14's new binding feature once `vintage_band` stopped being it. `src/generator/**` is frozen
this round, so the fix is built post-hoc instead of as a generator column:
`export_demo.py::add_elapsed_time_bands` (mirrored byte-for-byte in `rigor.py`, and called from
`validation/runners/_shared.py::prepare_features` so every runner sees it) buckets the raw column
into `months_since_moratorium_end_band` (`in moratorium` / `0-6` / `7+`), and the raw column moves
to `DROP`, exactly like `vintage_months`. The 0-6 cut is not picked to chase the CSI number — it
is the same threshold `HUMAN["months_since_moratorium_end"]` already used for its reason-code text
("first demands after moratorium"). See §17 for the honest result: banding reduces the drift but
does not clear DR-14's floor, because the gap is structural, not a feature-encoding problem.

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
FEATURES only (§3), not from the panel — as of round 2, so is `months_since_moratorium_end`
(§3, §17), for the identical reason.

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
- **Policy fold (new, 2026-09-21).** The 70% training side is split again, borrower-disjoint, at
  30%: **fit** (≈49% of accounts) trains the model, **policy** (≈21%) chooses the Amber/Red
  thresholds and fits the served-score calibrator, and **test** (30%) is measured and exported.
  The test groups are the same accounts the primary split has always selected —
  `GroupShuffleSplit` shuffles the sorted unique groups, so carving the policy fold out of TRAIN
  leaves the held-out book untouched and the same size (`export_demo.three_way_split`, pinned by
  a test).

  **Why.** Until this change, `choose_operating_thresholds` was handed the held-out TEST
  snapshot, read its future `months_to_npa` outcomes to pick the cost-minimising pair, and the
  same snapshot then reported that pair's Red-band precision, missed-NPA share, workload and
  band monotonicity. That is threshold selection on the evaluation set: the classifier AUC was
  unaffected, but the operating-point figures were not an untouched reading of a frozen policy,
  and requiring per-portfolio monotonicity during the search made later monotonicity on the
  same book partly a construction result. Thresholds are now chosen on a fold no exported
  account appears in, frozen, and only then measured on the test book. `tests/test_export_demo.py`
  asserts the invariant directly: rewrite every outcome in the test fold and the fitted
  thresholds do not move (and asserts the perturbation reached the test fold, so the check
  cannot pass vacuously).
- **Eligibility (new, 2026-09-21).** Every fit and every metric is restricted to `labelable == 1`
  — the rule `validation/criteria.yaml` states and the validation runners apply. Rows whose
  12-month forward window runs off the end of the panel are **scored** (the cockpit must draw
  them) and **never graded**. The exporter previously trained and measured on the whole panel,
  which let the simulator expose outcomes a bank extract could not yet have observed.
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

**Calibration of the rigour pack's own model** (`src/rigor.py`, DR-08–DR-10): isotonic
regression fit on an inner 25% validation slice of train, applied to the held-out test
predictions. **Brier(calibrated) < Brier(raw) is gated (DR-10)** — calibration must measurably
help, not just re-shape the score. That fit is a property of *that* model and *that* score.

**Calibration of the score DRISHTi actually serves** (new, 2026-09-21). A calibration measured
on a separately fitted model, on the raw per-month probability, before smoothing, does not
transfer to the exported model's smoothed decision score merely because both are called a PD —
and until this change `pd_calibrated` was left empty while the deck implied a displayed 40%
meant 40%. The exporter now fits an isotonic map on the **policy fold** (borrower-disjoint from
both the training fold and the exported book), applies it to `decision_score`, writes the result
to `scores.pd_calibrated`, and reports Brier and equal-count ECE for both the raw and the
calibrated served score on the untouched test fold (`metrics.calibration_served`, with its
reliability table). The calibrator never saw a test row; the model never saw a policy row.

**Which score is which.**

| field | what it is | decides anything? |
|---|---|---|
| `pd` | raw single-month probability at the reference month | no — transparency only |
| `pd_smooth` | 4-month trailing mean of `pd` | no — kept under its old name for the chart |
| **`decision_score`** | **the same trailing mean, under the name the thresholds were searched over** | **yes — every band, sort order, timeline band and memo** |
| `pd_calibrated` | `decision_score` through the policy-fold isotonic map | no — read as a probability, not a band |

**Is it actually calibrated, and calibrated everywhere?** Measured, per portfolio, in
`validation/report/experiments/calibration_by_portfolio/` (experiment E1, run off the frozen
artefact; standard errors clustered on `account_id` because one borrower contributes up to 36
correlated months). Three findings, none of them flattering by default:

* The **served** score is **under-confident**: Cox calibration slope **1.206 [1.179, 1.233]**
  pooled — the interval excludes 1, so this is a real departure, not noise. It understates how
  far apart the risky and the safe actually are.
* The **policy-fold isotonic map fixes that pooled**: slope **0.992 [0.967, 1.017]**, ECE
  0.00561 → **0.00082**, Brier 0.01948 → **0.01859**. So `pd_calibrated`, not `decision_score`,
  is the field to read as a probability.
* It does **not** fix it in every portfolio. After calibration **MSME-CC 1.214 [1.121, 1.308]**
  and **LAP 1.128 [1.033, 1.223]** still exclude 1, and Agri sits just below at 0.962
  [0.925, 0.998]. One pooled calibrator is not a per-portfolio calibrator, and the deck must
  not claim "a displayed 40% means 40%" inside MSME-CC or LAP on this evidence.

**And where it cannot be answered at all.** At the reference month — the book an officer opens
— six of the eight portfolios have a Red band of 6 to 24 accounts (Auto 6, Housing 7,
Retail-Unsecured 7, Education 11, LAP 15, MSME-TL 24). Auto's Red band reads 100% [61.0–100.0]:
an interval 39 points wide that one account moves by 17. Only Agri (143) and MSME-CC (32) carry
a readable high-risk calibration point. The pooled account-MONTH view hides this completely —
Agri's Red band looks like 4,989 observations there — which is why E1 reports both shapes.

`meta.policy_version` and `meta.decision_score` state the transform in the export itself, so a
consumer cannot band a different quantity from the one the thresholds were chosen over without
contradicting the file it loaded. It could before: the platform API banded raw `pd`, which at
the saved thresholds put 443 of 12,760 accounts in a different band from the book the model
published — 283 Red became 357.

## 8. Metrics, with confidence intervals, at both sizes

All proportions below carry 95% Wilson intervals (`export_demo.py::wilson`), chosen over the
normal approximation because several cells are small and some have zero defaults, where the
normal interval collapses to a point. Source: DM-4/DM-5's reported table, both from the same
frozen 8-month-horizon book at each size.

| metric | 9k × 36 (DM-4/5, pre-round-2) | 45k × 48, thresholds picked on the TEST book (superseded 2026-09-21) | 45k × 48, thresholds picked on the POLICY fold (**shipped**) |
|---|---|---|---|
| **`red_band_precision_8m`** | **44.1% [35.4–53.1]** (52/118) | 84.5% [79.8–88.2] (239/283) | **88.6% [84.0–92.0]** (217/245) |
| `missed_npa_share` | 13.9% [8.0–23.2] | 17.6% [13.9–21.9] | 16.1% [12.6–20.4] |
| `raw_accuracy_8m` / flag-nobody baseline | 96.3% / **96.9%** | 98.8% / 97.3% | 98.8% / 97.3% |
| `base_rate_8m` / `base_rate_12m` | 3.1% / 3.9% | 2.7% / 3.9% | 2.7% / 3.9% |
| `recall_at_10pct_budget` | 74.7% [64.1–83.0] | 86.5% [82.5–89.7] | 85.9% [81.8–89.1] |
| `flagged_share` | 27.8% | 4.7% [4.3–5.0] | 5.5% [5.1–5.9] |
| band counts (Red / Amber / Green) | — | 283 / 310 / 12,167 | 245 / 458 / 12,057 |
| grouped-holdout AUC | — | 0.902 | 0.885 [0.8784–0.8928] |
| ECE / Brier on the served score | — | not measured | 0.0056 / 0.0195 raw, **0.0008 / 0.0186** calibrated |

The 9k column is DM-4/5's original run, not re-measured (nothing since has touched a code path
that changes the 9k demo book).

**The middle column is kept because it is the one a reviewer will have seen, not because it is
a second valid reading.** Its operating point was chosen by reading the future outcomes of the
very book it is measured on (§6), so its precision, missed-NPA share, workload and band
monotonicity are not an untouched evaluation of that point. The right column is the same model
and the same held-out book, with the thresholds and the calibrator fitted on a borrower-disjoint
policy fold and frozen first.

**Why Red precision rose 84.5% → 88.6%, and why that is NOT evidence the model improved.**
The two figures are measured at different operating points, so they are not comparable as they
stand. Red now starts at **0.3437** instead of **0.2720**: a higher bar flags fewer accounts
(283 → 245 Red) and the ones it still flags are the riskiest, which raises precision
arithmetically whatever the model does. Holding the thresholds fixed separates the two effects
on the shipped book:

| book | Red threshold | Red n | Red precision @8m |
|---|---|---|---|
| old model, old thresholds | 0.2720 | 283 | 84.5% [79.8–88.2] (239/283) |
| **new** model, **old** thresholds | 0.2720 | 288 | **82.3% [77.5–86.3]** (237/288) |
| new model, new thresholds (**shipped**) | 0.3437 | 245 | 88.6% [84.0–92.0] (217/245) |

So the model/fold change on its own moved precision **down** 2.2pp (84.5 → 82.3), consistent
with AUC falling 0.902 → 0.885 from training on ~49% of accounts instead of ~70% so the policy
fold could exist. The entire +4.1pp headline gain, and more, is the threshold moving up
(82.3 → 88.6). Read the headline as "this is what the frozen policy delivered", never as "the
model got better" — it did not. What did improve is that the number is now measured at an
operating point the book had no part in choosing.

Missed-NPA also fell (17.6% → 16.1%) despite Red being stricter, because Amber widened
(310 → 458) and `missed_npa_share` counts NPAs left in **Green**; total workload rose 4.7% →
5.5% of the book, which is the real price of that.

Every figure in the table above is re-derivable from `data/demo_data.json` by re-banding
`decision_score` at the two threshold pairs — nothing here is a second model run.

**The headline, derived and asserted in-script (`assert_honesty`), never typed:**
> "88.6% of Red-flagged accounts went NPA within 8 months (95% CI 84.0%–92.0%, n=245)" — 45k, shipped.
> Superseded: "84.5% ... (95% CI 79.8%–88.2%, n=283)" — 45k, thresholds picked on the test book.
> At 9k (pre-round-2): "44.1% ... (95% CI 35.4%–53.1%, n=118)".

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

**Since 2026-09-21 that pass is an out-of-sample result.** DR-11 is also a *feasibility filter*
inside the threshold search: a candidate pair that breaks per-portfolio monotonicity is not a
candidate at all. While the search ran on the held-out book, monotonicity on that book was
partly a construction — the pair had been required to produce it there. The search now runs on
the policy fold (§6, §10), so the eight portfolios' monotonicity on the exported book is
something the frozen pair *achieved*, not something it was selected to display.

**Per-portfolio AUC — round 2's official measurement** (`validation/runners/01_holdout.py`,
DR-06, 45k×48, seed 7 — the validation lane's own panel and its own split, independently
generated from the main pipeline's, hence a different pooled figure from §8's 0.885): every
portfolio clears the DR-06 floor of 0.78 on the point estimate:

| Portfolio | AUC (round 2, DR-06) |
|---|---|
| Agri | 0.9069 |
| Education | 0.8752 |
| MSME-CC | 0.8724 |
| Housing | 0.8659 |
| MSME-TL | 0.8605 |
| LAP | 0.8500 |
| Retail-Unsecured | 0.8388 |
| Auto | 0.8374 |

(SD-D4/D5's earlier 3-seed, pre-round-2 diagnostic — pooled 0.9018/0.9016/0.8968, per portfolio
0.851–0.918 — is superseded by the table above as the per-portfolio reference; it is not
reproduced here to avoid two "current" tables.)

**DR-12, literal vs CI-aware — the ruling this card records.** DR-12 (≥9/10 decile step-ups
non-decreasing) is pre-registered on literal arithmetic and **fails at both sizes on the literal
reading** (5/9 at 9k; **the 2026-09-21 45k run: 6/9 in the worst portfolio, 0.6667** — 5/9 before
the pack was switched to band the decision score) — not because the
model doesn't rank risk, but because almost all realised risk concentrates in the top decile at
this score's separation, leaving deciles 1–9 sitting at fractions of a percent where step-to-step
ordering is statistical noise (one clear example from an earlier run: MSME-CC's 45k "reversal" was
0.0077→0.0076, one account across two 130-account cells whose Wilson intervals almost entirely
overlap). A second, *reported-not-gated* diagnostic (`monotone_decile_step_fraction_ci`) counts a
step-down against the model only when the two cells' 95% Wilson intervals are actually disjoint —
i.e. only when the data can tell them apart. **Under that reading, round 2's official run is 9/9 —
literally 1.0000 — pooled AND in every one of the eight portfolios: no statistically detectable
decile reversal anywhere.** The gate itself stays on the literal pre-registered arithmetic (DM-2/3
explicitly declined to relax it unilaterally, and round 2 — the last tuning round — does not
revisit that call either); this is recorded as an open ruling for the coordinator, not resolved by
this card. See `export_demo.py::rank_order_violations` and `_decile_steps_ci` for the exact
arithmetic and the reasoning comment beside it.

## 10. Cost-minimising thresholds

The Amber/Red split is **not** a hand-set pair — it minimises the bank's expected rupee cost
over the frozen book (`src/costs.py`), subject to DR-11 as a feasibility filter (a pair that
breaks DR-11 is not a candidate at all, whatever it costs). Expected loss on a missed NPA is
`EAD × LGD + EAD × (effective_rate + penal_rate)/100 × reversal_months/12` — principal at risk
plus RBI-IRAC income reversal.

**The search runs on the POLICY fold, not on the book the export reports.** See §6. The cost,
precision and missed-NPA figures below are therefore the policy fold's (8,933 accounts) and are
not comparable to the rupee totals this card carried before 2026-09-21, which were priced on
the 12,760-account test book. What the chosen pair then delivered on the untouched test book is
§8's table.

**Chosen pair, 45k:** amber **0.069298** / red **0.343723**, expected cost **₹6.68 cr** over the
policy fold, vs the July 2026 hand-set 0.04/0.40 pair's ₹6.80 cr on the same fold — 1.7%
cheaper. Both are DR-11-admissible at this size. Cost alone, with the DR-11 constraint lifted,
would have picked 0.1515/0.1658 at ₹6.61 cr: the pre-registered constraint costs ₹0.07 cr on
this book, and that price is emitted beside the pair (`thresholds.unconstrained`) rather than
absorbed.
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
`sandbox_fixture: true`: the Atlas sandbox returns the same static mock record to every caller
whatever the request (BR-6a; a full 23-API pass on 17 Sep 2026 showed each endpoint has its own
record, and that API 433 alone returns a composite one carrying a slice for every API). So these
are real *field values from the bank's own API contract*, not real *rates for our borrowers*. API 538's payoff interest split is reported `available: false` — the canned
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

**The model cannot warn about stress that arrives faster than its own window** (experiment E5,
`validation/report/experiments/challenge_regimes/`). The shipped artefact was scored, unretuned,
on nine generator regimes it was never fitted to, with three same-parameter control seeds to
establish a noise floor. It is robust to most of what was varied — base rate, borrower noise,
three times the statement-feed gaps, staler bureau data, twice the silent-default share all
leave AUC inside or near the controls' own 0.8631–0.8709 band. Two regimes break it, and they
are the same mechanism:

| regime | AUC | missed-NPA share |
|---|---|---|
| control (development parameters, unseen seed) | 0.8657 | 19.5% |
| `abrupt_onset` — stress develops in half the time | **0.7709** | **41.4%** |
| `macro_shock` — abrupt onset + higher base rate + 3× feed gaps | **0.7548** | **35.0%** |

Missed NPAs more than double. The decision score is a four-month trailing mean of a
deterioration trajectory; a borrower who goes from healthy to NPA inside that window has no
trajectory to read, and no threshold choice repairs it. **Both of those AUCs are below the
pre-registered DR-01 floor of 0.82.** DR-01 grades the development panel and is unaffected, but
the plain statement is that this model, unretuned, would not clear its own acceptance band on a
book whose stress arrives quickly. Shortening the smoothing window would help that case and hurt
the jitter it exists to remove; that trade has not been measured and is the obvious next round.

**A cleaner book than the simulator's will show LOWER precision at these thresholds.** In E5's
`base_rate_down` regime the model has the *highest* AUC of any regime (0.8761) and the *lowest*
Red precision (74.8%): with half the defaults, a fixed threshold flags proportionally more false
positives. A bank should re-derive its own operating point rather than inherit this one — which
is why `PUT /drishti/threshold` exists and why the export ships the whole cost derivation.


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

  Its denominators, stated separately because they are three different things: **3,171
  companies**, **17,031 company-year rows**, **1,284 positive company-year rows** spread over
  **851 distinct companies**. The target is default within the next two financial years
  (`src/real_model.py::build_table`, `horizon=2`), so a single default event labels up to two
  preceding company-years — which is why the positive-row count (1,284) exceeds the count of
  companies that defaulted (851), and why neither number is a count of "real defaults". The
  bootstrap around AUC 0.81 is clustered by company for the same reason.

  It is **complementary evidence that a two-year financial-statement model has signal on real
  MSMEs** — not external validation of the twelve-month behavioural model this card describes.
  The two differ in horizon (2 years vs 12 months), in observation unit (company-year vs
  account-month), in features (filed balance-sheet ratios vs monthly account conduct) and in
  population. A number measured on one is not a number earned by the other.
- **The bank sandbox is a static mock.** Each Atlas endpoint returns its own structured mock
  record and returns the same one regardless of the request (`sandbox_fixture: true`, BR-6a;
  API 433 is the one endpoint that returns a composite record with a slice for every API) —
  nothing in this build has ever scored, thresholded, or banded a real bank record. See
  §16's provenance legend for exactly which numbers that flag touches and which it does not.
- **DR-18 (cash-flow-family ablation ≥ 0.04 AUC) is measured and FAILS, deliberately not chased.**
  Round 1's `08_ablation` measured 0.0099 [0.0043, 0.0156]; round 2's official rerun (same runner,
  a freshly regenerated 9k×36 book) measured **0.001** [-0.0057, 0.0066] — both well below the
  pre-registered 0.04 floor, confirming SD-D4/D5's own earlier quick diagnostic (~0.019, "at
  risk"). Round 2 (the last tuning round) did not touch the generator or the label to move this
  number: with nine feature families, the cash-flow signal is *shared* with "Demand vs collection"
  (round 2's largest single-family driver, ΔAUC 0.018) and "Income & balance" (ΔAUC 0.0085) — all
  three carry the same underlying "money stopped arriving" event from different angles — so
  cash-flow's own marginal contribution, holding the other eight families fixed, is small even
  though the *joint* early-warning families dominate the model's attribution (DR-15: the
  days-past-due family, the leading alternative explanation, carries only 3.8% of attention at
  10–12 months' lead this round — see §11). DR-18 stays a reported fail, honestly explained rather
  than engineered around.
- **DR-12's literal-vs-CI-aware ruling (§9) is a recorded open question, not a resolution — and
  stays a reported fail both rounds.** Round 2's official 45k run: 5/9 pooled decile steps
  non-decreasing (0.6667 worst cell), in the same 5–8/9 range every earlier run has shown; every reversal
  recorded is a same-magnitude, low-count cell whose two Wilson intervals overlap (§9's MSME-CC
  example from an earlier run: 0.0077→0.0076, one account). Under the *reported, not gated*
  CI-aware reading, round 2 clears **9/9 — literally 1.0000 — pooled and in every one of the eight
  portfolios**: the reversals are within each pair's own confidence interval, not a real ranking
  failure. The gate itself stays on the literal pre-registered arithmetic; this card states both
  readings and does not decide which one the submission should lead with.
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

**`BANK_API` on an account means the bank answered about *that account*.** A family is
`BANK_API` at **run** level once its endpoint answers; that is a statement about the call,
not about any particular row. Because the sandbox holds only a handful of sample accounts,
the two levels say different true things, and `src/bank.py` keeps them apart: it records
the identifiers the pull actually came back with and awards a row `BANK_API` only if it is
one of them. The sandbox's sample ids and this panel's generated ids are disjoint, so no
account row in this build carries `BANK_API` — the genuine bank data is the run-level
endpoint block, badged where it is.

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

## 17. DM-8 round 2 — the last permitted tuning round

The plan allows two model-tuning rounds. This is round 2. Everything below is what changed, what
was tested and rejected, and the honest state of every criterion this round leaves it in — after
this, per the plan, numbers are reported as they are, not chased further.

**What changed (code):**

1. **Elapsed-time feature banding (DR-14).** `months_since_moratorium_end` became DR-14's new
   binding feature once round 1 (SD-D8) banded `vintage_months` into `vintage_band`. The same
   fix — a bank-style bucket in place of the raw month counter, `vintage_band`'s precedent — is
   applied via `export_demo.py::add_elapsed_time_bands` (mirrored in `rigor.py`, wired into
   `validation/runners/_shared.py::prepare_features`), banding the raw column into `in
   moratorium` / `0-6` / `7+` and moving the raw column to `DROP` (kept in the CSV). The cut is
   `HUMAN`'s own existing reason-code threshold, not chosen to hit a CSI number.
2. **Static-profile-subset ablation, tested and REJECTED (DR-19).** Dropping `constitution`,
   `state`, `city_tier`, `nic_group`, `tenor_months`, `interest_rate_pa`, `secured` (`portfolio`
   was never a candidate — it is the one-model-many-portfolios mandate's key) was measured on the
   9k×36 book: pooled AUC **improved** (0.8568 → 0.8646, +0.0078) and pooled ECE improved
   (0.0116 → 0.0092), and six of seven affected portfolios' AUC rose. But Retail-Unsecured's
   per-portfolio AUC fell to **0.7375**, below the 0.78 guardrail (it was already marginal
   pre-drop, at 0.7408, at this scale) — one floor breaking is enough per the brief's own rule.
   The columns are **kept**; DR-19 is reported as a fail (§ below), unchanged in spirit from round
   1, and the "fewer protected-attribute proxies" fairness argument this test hoped for does not
   materialise this round.
3. **DR-18 / DR-12 — no code change**, honest explanations only (§15, §9, §11).
4. **Demo sample size.** `--demo-sample` default cut from 2,500 to **700** (`export_demo.py`).
   Measured: 2,500 → 12.5 MB; the first candidate, 800, still landed at 4.08 MB because
   stratified rounding samples slightly more than requested (810 accounts); 700 → 710 sampled →
   **3.59 MB**, safely inside the app's 4 MB budget, stratified by portfolio × band exactly as
   before.

**A bug found in passing, and fixed as a precondition for an honest round-2 measurement.**
`validation/runners/_shared.py::load_panel` caches its own 45k×48 panel under
`data/validation_panel_cache/seed7_n45000_m48/` and never invalidates that cache when the
generator changes underneath it. That cache was written **before** SD-D8's `vintage_band` commit
— it carries `vintage_months` but not `vintage_band` at all — meaning round 1's official DR-01,
DR-06, DR-08–DR-14 numbers (everything `01_holdout`/`06_stability` measure) were graded against a
panel that predates the vintage fix, the msme_cc utilisation recalibration, the DPD-clip fix and
the arrears-ladder cap. This explains the gap between round 1's validation-lane pooled AUC
(0.8862) and the main pipeline's shipped 0.902 — they were never the same panel to begin with.
Round 2 deletes `data/validation_panel_cache/` before running `validation.run` so every cache
regenerates from the current generator; no generator or CAT/DROP code was touched to do this.

**Round 2's honest DR-14 result.** Banding `months_since_moratorium_end` does not clear the 0.25
floor: on a 9k×48 dev check (production OOT geometry, embargo gap = 12 months), the raw column's
CSI (3.07) drops to **1.08** banded — a real ~65% reduction — but the pre-registered OOT split
embargoes training to months ≤12 and tests on months ≥24, a structural 12-month gap that any
account-age-correlated feature cannot survive at fine granularity. The same dev check found
**`vintage_band` itself — round 1's supposed fix, unexercised in round 1's own measurement because
of the stale-cache bug above — sitting at CSI ≈ 3.7,** far over the floor. Once the cache is
fixed, round 2's official `validation.run` reports **DR-14 FAIL, max CSI 3.6344, binding feature
`vintage_band`** (not `months_since_moratorium_end`, which no longer binds). This is reported
as-is: a structural property of the pre-registered embargo-gap OOT split acting on any
elapsed-time-correlated feature, not a defect in this round's fix, and not chased further.

**The 26-criterion table, round 2 (`validation/report/report.json`, 2026-09-17):**

16 pass, 6 report, **4 fail — the same four as round 1: DR-12, DR-14, DR-18, DR-19.**

| ID | Status | Metric | Value |
|---|---|---|---|
| DR-01 | pass | grouped AUC | 0.8885 |
| DR-02 | report | red-band precision @8m | 88.2% (n=8,176) — banded on the decision score since 2026-09-21; 72.9% (n=11,657) when the pack banded the raw per-month score |
| DR-03 | pass | annual slippage | 3.31% |
| DR-04 | report | label base rate (annual) | 3.63% |
| DR-05 | pass | OOT/holdout AUC ratio | 1.0009 |
| DR-06 | pass | per-portfolio AUC | worst Auto 0.8374, best Agri 0.9069 (§9) |
| DR-07 | report | AUC by cut | 0.8724 |
| DR-08 | pass | ECE | 0.0010 |
| DR-09 | pass | per-cut ECE | all cells ≤ 0.04 |
| DR-10 | pass | Δ Brier (cal − raw) | −0.000068 |
| DR-11 | pass | band monotonicity | pooled + 8/8 portfolios |
| **DR-12** | **fail** | monotone decile-step fraction | **0.6667** (literal, worst cell); 1.0000 pooled + 8/8 CI-aware |
| DR-13 | pass | score PSI | 0.0006 |
| **DR-14** | **fail** | max feature CSI | **3.6344** (binding: `vintage_band`) |
| DR-15 | pass | DPD-family attribution @10–12m | 3.81% (alt 20.92%) |
| DR-16 | pass | permuted-label AUC | 0.5001 |
| DR-17 | pass | availability-at-time manifest | complete, 62/62 |
| **DR-18** | **fail** | ΔAUC, cash-flow family dropped | **0.0010** [-0.0057, 0.0066] vs 0.04 floor |
| **DR-19** | **fail** | max ΔAUC gain from dropping any family | **0.0123** (family: Borrower profile, 18 cols) |
| DR-20 | pass | seeds run | 5/5 |
| DR-21 | pass | cross-seed AUC CI width | 0.0123 |
| DR-22 | pass | \|ΔAUC\| at 2× base rate | 0.0019 |
| DR-23 | pass | \|ΔAUC\| bureau missing | 0.0069 |
| DR-24 | report | adverse-impact ratio (worst) | geography (region) 0.7010; constitution 0.7912, qualification 0.7661, promoter_age_group 0.9405 — flagged on the DECISION score, as the officer's queue is |
| DR-25 | report | TPR gap (worst) | constitution 0.1023; geography (region) 0.0954, qualification 0.0242, promoter_age_group 0.0240 — same banding change |
| DR-26 | report | baseline ladder | DPD-only 0.6947 → scorecard 0.8569 → LightGBM 0.8885 (validation's own 45k panel); rigor.py's main-pipeline cross-check: logistic 0.873 → LightGBM 0.902 |

**Runtimes (round 2, this machine):** `generate_data.py --n 45000 --months 48`: 9.3s ·
`export_demo.py --demo-sample 700`: 10m35s (writes succeed, then exits 1 on its own DR-12
assertion — expected, documented behaviour, not retried) · `rigor.py`: 12m00s ·
`validation.run` (cache cleared first, so every panel regenerated from scratch): ~12m20s ·
`pytest tests/ -q -m "not slow"`: 392 passed, 22 deselected, 76s ·
`pytest validation/tests -q`: 65 passed, 17s.

**Not chased, by design:** DR-12, DR-14, DR-18, DR-19 all stay reported fails. Every one has a
pre-registered, honest explanation above and in §9/§11/§15 — none was moved by adjusting a
threshold, the generator, or the label. This is the freeze point the plan calls for.

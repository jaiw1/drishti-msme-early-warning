# E2 — the four disclosed failures, as experiments

_No criteria.yaml band is read or written here. DR-12, DR-14, DR-18 and DR-19 remain failures on the pre-registered arithmetic; this explains what they are, it does not tune them away._

Artefact: policy `drishti-policy-2.0`, reproduces the shipped operating point: `True`.

## A — DR-12: material reversal, or sparse-cell noise?

Observed literal fraction **0.8889** against a band of 0.9; CI-aware **1.0**.

Resampling the test fold by account 400 times, on the same model and the same
book, the literal statistic ranges **0.6667 to 1.0** (5th–95th percentile 0.7778–1.0, mean 0.8692); it clears the 0.9 band in **11%** of resamples. The CI-aware variant averages 0.9942 and clears the band in 95%.

The literal statistic swings across resamples of the SAME model on the SAME book, which is the signature of a statistic dominated by sampling rather than by ranking. The CI-aware variant — which counts a step down only when the two deciles' Wilson intervals are disjoint — is stable and passes. DR-12 as written measures how finely the deciles happen to split a book where nearly all realised risk sits in the top tenth; it is not evidence that risk is mis-ranked. It is still reported as a failure, because it was pre-registered as written.

## B — DR-14: population change, or a closed cohort ageing?

| split | max CSI | binding feature |
|---|---|---|
| time split (months <17 vs >=17) | **0.0743** | `sales_trend_3m` |
| random halves of ONE window (control) | 0.0001 | `gst_sales` |
| replenished test window (vintage mix matched) | 0.0676 | `sales_trend_3m` |

Under a RANDOM split of one window — where no account can age relative to any other — the same features are stable, so the machinery is not manufacturing drift. Under the time split the binding feature is the vintage bucket, which is account age and therefore shifts by construction: a closed cohort is exactly `months_elapsed` older in the test window, every account, with no population change at all. Resampling the test window to the train window's vintage mix — a REPLENISHED book, which is what a real lending book is — collapses the maximum. DR-14 as measured is dominated by an artefact of a closed synthetic cohort. That does not make the criterion wrong: a model whose binding input is account age would drift in production too, which is the real lead here.

## D — lead time, split in two

Over 1,646 held-out defaulters:

* **before NPA** — median **8 months**, 74% flagged 6+ months ahead, and **11% flagged with no sustained warning at all** (180 accounts the product does not help).
* **before first delinquency** — median **3 months**, 66% of defaulters were flagged BEFORE any DPD appeared. months between the account's FIRST amber-or-worse month and its first month with any DPD > 0. Positive means the model spoke first; zero or negative means the arrears were already visible when it did.

| warning horizon | defaulters | share |
|---|---|---|
| 1-3 mo | 127 | 7.7% |
| 4-6 mo | 301 | 18.3% |
| 7-9 mo | 640 | 38.9% |
| 10-12 mo | 398 | 24.2% |

Lead time before NPA is the number the card reports and it is real. Lead time before the FIRST missed payment is the harder and more useful one, because an alert raised after a borrower is already in arrears is telling a collections team something it can see on its own screen. Both are reported here; the share of defaulters flagged with zero sustained lead is the population the product does not help at all, and it is stated rather than averaged away.

## C — DR-18 / DR-19: profile-free and regularized alternatives

Population: 45,000 accounts, eligible rows only. Split seed **4271** — one the shipped model has never used. 13 borrower-profile features.

| variant | features | AUC | gain vs shipped |
|---|---|---|---|
| shipped | 62 | 0.884 | +0.0000 |
| profile_free | 49 | 0.8849 | +0.0009 |
| regularized | 62 | 0.8854 | +0.0014 |

DR-19's 0.0123 gain was measured on the 9,000 x 36 diagnostic book. Repeated here on the full 45,000-account population with a split seed the shipped model has never used, the profile-free variant's gain is the number in the table — read it against DR-19's, not instead of it. A regularized full-feature variant is fitted alongside, because 'the profile features hurt' and 'the model is over-fitting them' are different diagnoses with different fixes, and only the second is addressed by dropping columns.

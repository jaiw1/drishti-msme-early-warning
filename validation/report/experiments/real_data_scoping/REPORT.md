# E3 — what the real-data numbers count, and whether the signal survives scoping

**Question.** What exactly do the real-data numbers count, and does the signal survive a temporal holdout and a filing-availability lag?

**What this is.** Complementary evidence that a TWO-YEAR FINANCIAL-STATEMENT model has signal on real Indian MSMEs. It is not external validation of DRISHTi's twelve-month behavioural model: different horizon (2 years vs 12 months), different observation unit (company-year vs account-month), different features (filed balance-sheet ratios vs monthly account conduct), different population. A number measured on one is not a number earned by the other.

Source: `src/real_model.py (frozen July 2026 artefact; imported, not modified)`. Horizon 2 financial years; censoring cutoff 2026. 95% CI by resampling COMPANIES with replacement, 500 draws.

## 1. Four different numbers, and why they differ

| quantity | value |
|---|---|
| companies | **3,171** |
| company-years (rows) | **17,031** |
| positive rows | **1,284** |
| distinct companies with >=1 positive row | **851** |
| positive rows per positive company | 1.509 |

The target is default within the next 2 financial years, so ONE default event labels up to 2 preceding company-years. 1284 positive ROWS come from 851 distinct COMPANIES. Neither number is a count of 'real defaults': the event count is the company count, and the row count is an observation count.

## 2. Observation coverage and censoring

Median **7** company-years per company (mean 5.37). A company contributing six company-years carries six times the weight of one contributing one, in every unclustered statistic. This is why the AUC intervals here are bootstrapped over COMPANIES.

Censoring rule: a non-defaulter's row is kept only when its outcome window ends at or before 2026 (obs_year + 2 <= 2026); a defaulter's rows at or after its default year are dropped entirely, so no row is observed after the event it predicts. Observation years span 2018–2025.

| obs year | rows | positive rate |
|---|---|---|
| 2018 | 3,039 | 17.77% |
| 2019 | 2,680 | 9.51% |
| 2020 | 2,524 | 6.34% |
| 2021 | 2,410 | 5.48% |
| 2022 | 2,302 | 4.47% |
| 2023 | 2,174 | 2.99% |
| 2024 | 1,900 | 1.42% |
| 2025 | 2 | 100.00% |

## 3. Rating-event dates

15,675 'D' rating actions, 0 with a readable month.

_`real_model.yr()` keeps only the YEAR of a rating action, so a default in January and one in December are treated as the same event date. Every row is labelled against a financial YEAR, so the effective lead time varies by up to eleven months across the positive class and is not recoverable from the label. Using exact dates would let lead time be measured rather than assumed; it is not done here because the frozen artefact must stay as it shipped._

## 4. Does the signal survive a harder design?

| design | AUC | 95% CI (company-clustered) | train rows | test rows | test companies | test positive rows / companies |
|---|---|---|---|---|---|---|
| `company_grouped_random` | **0.8112** | [0.7843, 0.8348] | 11,916 | 5,115 | 952 | 395 / 261 |
| `temporal` | **0.7968** | [0.7401, 0.8384] | 12,955 | 4,076 | 2,180 | 94 / 70 |
| `temporal_and_company_disjoint` | **0.7214** | [0.6574, 0.7748] | 2,335 | 4,076 | 2,180 | 94 / 70 |
| `extra_filing_lag` | **0.781** | [0.75, 0.811] | 10,675 | 4,483 | 951 | 518 / 276 |

**Read the train-rows column beside the AUC.** `temporal_and_company_disjoint` is the
strictest design AND the smallest training set, so part of its drop is less data
rather than a harder test; the two are not separated here. What can be said is that
the shipped 0.81 is the most permissive of the four designs, and that every stricter
one lands lower.

**`company_grouped_random`** — the shipped design: 30% of COMPANIES held out at random, all years pooled.  
_Caveat: company-disjoint but not time-disjoint — a 2019 row may be used to predict a 2019 outcome at another company, which a forward-looking user cannot do._

**`temporal`** — train on obs_year <= 2022, test on obs_year > 2022 — forwards, as it would be used.  
_Caveat: companies may appear in both halves, in different years._

**`temporal_and_company_disjoint`** — train on obs_year <= 2022 AND on companies absent from the test window; test on obs_year > 2022.  
_Caveat: the strictest of the three, and the smallest training set._

**`extra_filing_lag`** — the same model with the outcome window pushed out one year (horizon 2 -> 3), standing in for statements that are not readable until a year after the financial year they describe.  
_Caveat: an approximation: the source carries no filing-availability date at all, so the true lag is unknown and this brackets it rather than measuring it._

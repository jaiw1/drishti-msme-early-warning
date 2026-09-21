# E6 — one 90-DPD rule for eight portfolios, and what it costs

**Question.** What does applying one 90-DPD rule to all eight portfolios — including Kisan Credit Card — cost, compared with RBI's crop-season rule for agricultural advances?

**The rule.** RBI Master Circular on Income Recognition, Asset Classification and Provisioning: a short-duration crop advance is NPA when principal or interest is overdue for two crop seasons; a long-duration crop advance for one crop season. Ordinary term loans use 90 days overdue; CC/OD uses 'out of order' for more than 90 days.

**Default: OFF. The shipped panel keeps 90 DPD everywhere. A label definition is not a free parameter, and the review's own instruction is to have the bank confirm its classification policy before this is represented as regulatory classification.**

Panel 9,000 accounts × 36 months, seed 20260709 — the same seed on both sides, so the only difference is the recognition rule.

## 1. How much does the label move?

| portfolio | 12m rate, 90 DPD | 12m rate, portfolio rule | change |
|---|---|---|---|
| Agri | 6.58% | 3.77% | -43% |
| Auto | 1.89% | 1.89% | +0% |
| Education | 3.36% | 3.36% | +0% |
| Housing | 1.06% | 1.06% | +0% |
| LAP | 3.09% | 3.09% | +0% |
| MSME-CC | 3.71% | 3.71% | +0% |
| MSME-TL | 4.10% | 4.10% | +0% |
| Retail-Unsecured | 2.83% | 2.83% | +0% |
| **book** | **3.87%** | **3.03%** | **-22%** |

Only agriculture changes, which is the point: every other portfolio here is an ordinary term loan or a CC/OD facility, and 90 days is the right test for both. Agri's rate falls because a crop advance that the 90-day rule calls NPA is, under the bank's actual norms, still a standard asset for roughly another year — and some of those accounts never reach the corrected recognition point inside the observation window at all.

## 2. Does the SHIPPED model still rank the re-labelled book?

The frozen artefact scoring each book with **no refit** — the day-one case if a bank corrects its label definition and keeps the model it already has.

| portfolio | frozen AUC, 90 DPD | frozen AUC, portfolio rule |
|---|---|---|
| Agri | 0.881 | 0.8685 |
| Auto | 0.786 | 0.786 |
| Education | 0.8298 | 0.8298 |
| Housing | 0.8389 | 0.8389 |
| LAP | 0.849 | 0.849 |
| MSME-CC | 0.8625 | 0.8625 |
| MSME-TL | 0.828 | 0.828 |
| Retail-Unsecured | 0.7714 | 0.7714 |
| **overall** | **0.8645** | **0.8427** |

## 3. What would retraining under the correct rule buy?

| | 90 DPD | portfolio rule |
|---|---|---|
| frozen model (no refit) | 0.8645 | 0.8427 |
| refit under that rule | 0.8545 | 0.8198 |
| Agri, frozen | 0.881 | 0.8685 |
| Agri, refit | 0.8784 | 0.8492 |

## What this does and does not settle

It settles that the single 90-DPD definition materially mis-states agriculture, and by roughly how much. It does **not** settle what IDBI's own classification policy is — short- versus long-duration crop mix, how a KCC renewal interacts with recognition, and whether the bank treats the seasons as half-years. Those are the bank's to confirm, which is why the switch ships off. Nothing in DRISHTi assigns a regulatory classification in either configuration: the memo recommends a credit review and reports the CBS classification as an observed field.

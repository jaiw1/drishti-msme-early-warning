# E1 — calibration of the served score, by portfolio

**Question.** Is the score DRISHTi actually serves calibrated, and is it calibrated inside every portfolio rather than only on average?

**Population.** the frozen artefact's own test fold, labelable rows only; 467,617 rows / 13,500 accounts  
**Operating point.** amber 0.069298 / red 0.343723  
**Artefact.** policy `drishti-policy-2.0`, panel sha256 `7e0e3ab0855a…`, reproduces the shipped operating point: `True`

Standard errors are clustered on `account_id`: the same borrower contributes up to
36 correlated months, and unclustered intervals here would be about six times too
narrow. Nothing below grades a pre-registered criterion.

## Summary

| cell | n rows | n accts | base rate | Brier (served) | ECE (served) | slope (served) | Brier (calib.) | ECE (calib.) | slope (calib.) |
|---|---|---|---|---|---|---|---|---|---|
| **POOLED** | 467,617 | 13,500 | 3.52% | 0.01948 | 0.00561 | 1.206 [1.179, 1.233] | 0.01859 | 0.00082 | 0.992 [0.967, 1.017] |
| Agri | 134,224 | 3,977 | 6.05% | 0.02764 | 0.00907 | 1.286 [1.247, 1.325] | 0.02623 | 0.00318 | 0.962 [0.925, 0.998] |
| Auto | 39,942 | 1,131 | 1.81% | 0.01440 | 0.00400 | 1.047 [0.948, 1.145] | 0.01428 | 0.00166 | 0.941 [0.840, 1.042] |
| Education | 40,860 | 1,167 | 2.71% | 0.01958 | 0.00779 | 1.175 [1.079, 1.272] | 0.01889 | 0.00410 | 1.010 [0.917, 1.103] |
| Housing | 69,229 | 1,954 | 1.29% | 0.01005 | 0.00336 | 1.175 [1.078, 1.272] | 0.00985 | 0.00282 | 1.096 [0.984, 1.208] |
| LAP | 49,511 | 1,415 | 2.52% | 0.01629 | 0.00563 | 1.266 [1.175, 1.357] | 0.01537 | 0.00363 | 1.128 [1.033, 1.223] |
| MSME-CC | 47,713 | 1,380 | 3.62% | 0.01692 | 0.00720 | 1.398 [1.300, 1.495] | 0.01530 | 0.00287 | 1.214 [1.121, 1.308] |
| MSME-TL | 39,013 | 1,127 | 3.71% | 0.02170 | 0.00649 | 1.198 [1.105, 1.290] | 0.02071 | 0.00171 | 0.993 [0.906, 1.080] |
| Retail-Unsecured | 47,125 | 1,349 | 2.49% | 0.01842 | 0.00616 | 1.054 [0.967, 1.140] | 0.01804 | 0.00232 | 0.932 [0.854, 1.011] |

A slope of 1 with an interval containing 1 is a score whose spread matches its
outcomes. Below 1 is over-confident (the score separates more than the world does);
above 1 is under-confident.

## High-risk cells — where a bank actually acts

The Red band only, in the two shapes it has. **Pooled** counts account-MONTHS over
the whole fold, which makes every cell look well populated. **Snapshot** is the book
an officer actually opens: one row per account at the reference month, 8-month
outcome window — and that is where the cells are thin. This is the table the review
asked for: a portfolio whose Red band holds a handful of accounts has no readable
calibration point there, and saying so is the finding.

| cell | Red rows (pooled) | observed | 95% CI | Red accounts (snapshot) | observed | 95% CI | readable at the snapshot? |
|---|---|---|---|---|---|---|---|
| POOLED | 8,083 | 90.2% | [89.6%, 90.9%] | 245 | 88.6% | [84.0%, 92.0%] | yes |
| Agri | 4,989 | 90.2% | [89.3%, 91.0%] | 143 | 87.4% | [81.0%, 91.9%] | yes |
| Auto | 180 | 77.8% | [71.2%, 83.2%] | 6 | 100.0% | [61.0%, 100.0%] | **NO** — n=6 accounts — the interval spans 39%; one account moves it by 17%, so this cell cannot support a calibration claim |
| Education | 346 | 80.9% | [76.5%, 84.7%] | 11 | 100.0% | [74.1%, 100.0%] | **NO** — n=11 accounts — the interval spans 26%; one account moves it by 9%, so this cell cannot support a calibration claim |
| Housing | 219 | 82.2% | [76.6%, 86.7%] | 7 | 85.7% | [48.7%, 97.4%] | **NO** — n=7 accounts — the interval spans 49%; one account moves it by 14%, so this cell cannot support a calibration claim |
| LAP | 443 | 93.9% | [91.3%, 95.8%] | 15 | 93.3% | [70.2%, 98.8%] | **NO** — n=15 accounts — the interval spans 29%; one account moves it by 7%, so this cell cannot support a calibration claim |
| MSME-CC | 911 | 98.4% | [97.3%, 99.0%] | 32 | 96.9% | [84.3%, 99.4%] | yes |
| MSME-TL | 638 | 92.3% | [90.0%, 94.1%] | 24 | 79.2% | [59.5%, 90.8%] | **NO** — n=24 accounts — the interval spans 31%; one account moves it by 4%, so this cell cannot support a calibration claim |
| Retail-Unsecured | 357 | 82.1% | [77.8%, 85.7%] | 7 | 71.4% | [35.9%, 91.8%] | **NO** — n=7 accounts — the interval spans 56%; one account moves it by 14%, so this cell cannot support a calibration claim |

## Reliability, pooled

| bin | n | predicted | observed | 95% CI |
|---|---|---|---|---|
| 1 | 46,762 | 0.0023 | 0.0035 | [0.0030, 0.0040] |
| 2 | 46,762 | 0.0040 | 0.0054 | [0.0048, 0.0061] |
| 3 | 46,761 | 0.0056 | 0.0073 | [0.0065, 0.0081] |
| 4 | 46,762 | 0.0073 | 0.0090 | [0.0081, 0.0099] |
| 5 | 46,761 | 0.0094 | 0.0114 | [0.0105, 0.0124] |
| 6 | 46,762 | 0.0119 | 0.0126 | [0.0116, 0.0136] |
| 7 | 46,762 | 0.0151 | 0.0151 | [0.0141, 0.0163] |
| 8 | 46,761 | 0.0196 | 0.0174 | [0.0163, 0.0186] |
| 9 | 46,762 | 0.0287 | 0.0260 | [0.0246, 0.0274] |
| 10 | 46,762 | 0.2015 | 0.2439 | [0.2401, 0.2479] |

Figure: `reliability_by_portfolio.png` — served score and calibrated score against
the diagonal, one panel per portfolio, bin area proportional to n.

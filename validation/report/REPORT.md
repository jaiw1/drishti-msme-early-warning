# DRISHTi — validation report

**Verdict: FAIL**  ·  16 pass · 4 fail · 0 warn · 0 pending · 0 skipped · 6 reported

## Pre-registration

These 26 acceptance bands were registered at **2026-09-16T10:47:14+05:30** by RR Squad, before any model result for DRISHTi existed.

`validation/criteria.yaml` first entered git at **2026-09-16T11:05:49+05:30** — that commit timestamp, not this file, is the evidence. This report was generated at 2026-09-17T02:36:16+05:30 from commit `0c92bf980c39`.

Clarifications issued during pre-registration (no band was loosened):
- *2026-09-16T02:00:00+05:30* — DRISHTi has EIGHT portfolios — MSME-CC, MSME-TL, Housing, Education, Agri, Retail-Unsecured, LAP, Auto. The "7 portfolios" figure in plan §B L4 SD-D2 and in the §D G2 gate was stale from plan v1 and has been patched.

No amendments. Every band below is as first registered.

## Failures

| Criterion | Metric | Band | Observed | 95% CI | n | Detail |
|---|---|---|---|---|---|---|
| **DR-12** | monotone_decile_step_fraction | ≥ 0.9 | 0.5556 | — | 46557 | literal fraction gates (per the brief); CI-aware fraction reported only (a step only counts as a reversal when the two deciles' Wilson intervals do not overlap): {'MSME-CC': 1.0, 'MSME-TL': 1.0, 'Housing': 1.0, 'Education': 1.0, 'Agri': 1.0, 'Retail-Unsecured': 1.0, 'LAP': 1.0, 'Auto': 1.0}. pooled literal=1.0000, pooled CI-aware=1.0000 (reported, not gated); operating thresholds amber=0.074653, red=0.271968 (live cost-minimising). |
| **DR-14** | max_feature_csi | ≤ 0.25 | 3.6344 | — | 500168 | max over 62 model-input features, binding feature: vintage_band |
| **DR-18** | auc_drop_when_cashflow_family_removed | ≥ 0.04 | 0.001 | [-0.0057, 0.0066] | 63226 | AUC drop when the Cash-flow (inflows / GST) family (7 columns) is removed, on the 9,000 x 36 book (seed 7), baseline AUC=0.8533, dropped AUC=0.8523. Full family table: Demand vs collection: ΔAUC=0.018 (CI (0.0104, 0.0261), n_cols=4); Income & balance: ΔAUC=0.0085 (CI (0.0016, 0.0153), n_cols=11); Bureau: ΔAUC=0.0024 (CI (-0.0058, 0.0097), n_cols=1); Days-past-due / repayment: ΔAUC=0.0011 (CI (-0.003, 0.0052), n_cols=7); Cash-flow (inflows / GST): ΔAUC=0.001 (CI (-0.0057, 0.0066), n_cols=7); Credit-limit utilisation: ΔAUC=-0.0005 (CI (-0.0072, 0.0068), n_cols=6); Adverse filings: ΔAUC=-0.005 (CI (-0.009, -0.0011), n_cols=2); Leverage & collateral: ΔAUC=-0.0058 (CI (-0.0116, 0.0007), n_cols=6); Borrower profile: ΔAUC=-0.0123 (CI (-0.023, -0.0037), n_cols=18). |
| **DR-19** | max_auc_gain_from_dropping_any_family | ≤ 0.0 | 0.0123 | [0.0037, 0.023] | 63226 | largest AUC gain from dropping any family: 0.0123 (family: Borrower profile). No noise allowance — a small positive gain inside its own CI is recorded as a failure (criteria.yaml DR-19 note). Full family table: Demand vs collection: ΔAUC=0.018 (CI (0.0104, 0.0261), n_cols=4); Income & balance: ΔAUC=0.0085 (CI (0.0016, 0.0153), n_cols=11); Bureau: ΔAUC=0.0024 (CI (-0.0058, 0.0097), n_cols=1); Days-past-due / repayment: ΔAUC=0.0011 (CI (-0.003, 0.0052), n_cols=7); Cash-flow (inflows / GST): ΔAUC=0.001 (CI (-0.0057, 0.0066), n_cols=7); Credit-limit utilisation: ΔAUC=-0.0005 (CI (-0.0072, 0.0068), n_cols=6); Adverse filings: ΔAUC=-0.005 (CI (-0.009, -0.0011), n_cols=2); Leverage & collateral: ΔAUC=-0.0058 (CI (-0.0116, 0.0007), n_cols=6); Borrower profile: ΔAUC=-0.0123 (CI (-0.023, -0.0037), n_cols=18). |

## All criteria

### 01_holdout

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-01 | grouped_auc | overall | ∈ [0.82, 0.92] | 0.8885 | [0.8814, 0.8949] | 467471 | fail | PASS |
| DR-02 | red_band_precision_at_8_months | overall | reported, no target | 0.729 | [0.7209, 0.737] | 11657 | report | reported |
| DR-03 | annual_slippage_ratio | overall | ∈ [0.03, 0.05] | 0.0331 | [0.0324, 0.0339] | 45000 | fail | PASS |
| DR-04 | label_base_rate_annual | overall | reported, no target | 0.0363 | [0.0354, 0.0371] | 1557251 | report | reported |

### 02_oot

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-05 | oot_auc_ratio_to_holdout | overall | ≥ 0.95 | 1.0009 | [0.9914, 1.0132] | 500168 | fail | PASS |

### 03_by_cut

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-06 | auc | per_portfolio | ≥ 0.78 | — | — | — | fail | PASS |
| DR-07 | auc | per_cut (all) | reported, no target | 0.8724 | [0.8538, 0.8923] | 46557 | report | reported |

<details><summary>DR-06 — per-cell breakdown (8 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| MSME-CC | 0.8724 | [0.8538, 0.8923] | 46557 | PASS |
| MSME-TL | 0.8605 | [0.8419, 0.8849] | 39920 | PASS |
| Housing | 0.8659 | [0.8406, 0.8887] | 71404 | PASS |
| Education | 0.8752 | [0.852, 0.899] | 37559 | PASS |
| Agri | 0.9069 | [0.8984, 0.9171] | 135043 | PASS |
| Retail-Unsecured | 0.8388 | [0.8097, 0.8623] | 45385 | PASS |
| LAP | 0.85 | [0.8259, 0.8744] | 48651 | PASS |
| Auto | 0.8374 | [0.7962, 0.8666] | 42952 | PASS |

</details>

<details><summary>DR-07 — per-cell breakdown (76 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| portfolio=MSME-CC | 0.8724 | [0.8538, 0.8923] | 46557 | reported |
| portfolio=MSME-TL | 0.8605 | [0.8419, 0.8849] | 39920 | reported |
| portfolio=Housing | 0.8659 | [0.8406, 0.8887] | 71404 | reported |
| portfolio=Education | 0.8752 | [0.852, 0.899] | 37559 | reported |
| portfolio=Agri | 0.9069 | [0.8984, 0.9171] | 135043 | reported |
| portfolio=Retail-Unsecured | 0.8388 | [0.8097, 0.8623] | 45385 | reported |
| portfolio=LAP | 0.85 | [0.8259, 0.8744] | 48651 | reported |
| portfolio=Auto | 0.8374 | [0.7962, 0.8666] | 42952 | reported |
| constitution=Individual | 0.8959 | [0.8894, 0.9029] | 335677 | reported |
| constitution=LLP | 0.8578 | [0.816, 0.9] | 7152 | reported |
| constitution=Partnership | 0.8813 | [0.8481, 0.9098] | 14945 | reported |
| constitution=Proprietorship | 0.8667 | [0.8504, 0.8808] | 93442 | reported |
| constitution=PvtLtd | 0.8727 | [0.8437, 0.9032] | 16255 | reported |
| segment=Medium | 0.9018 | [0.8525, 0.9318] | 5696 | reported |
| segment=Micro | 0.8918 | [0.8848, 0.899] | 288755 | reported |
| segment=Small | 0.8721 | [0.8572, 0.8848] | 173020 | reported |
| secured=0 | 0.8893 | [0.8801, 0.8973] | 190866 | reported |
| secured=1 | 0.885 | [0.876, 0.8961] | 276605 | reported |
| ticket_band=(147174.015, 361060.349] | 0.8974 | [0.8833, 0.9107] | 93492 | reported |
| ticket_band=(2289618.96, 50000000.0] | 0.8702 | [0.8529, 0.8881] | 93471 | reported |
| ticket_band=(361060.349, 916711.962] | 0.8704 | [0.8559, 0.886] | 93519 | reported |
| ticket_band=(916711.962, 2289618.96] | 0.8781 | [0.8599, 0.891] | 93483 | reported |
| ticket_band=(9999.999, 147174.015] | 0.8997 | [0.8867, 0.9106] | 93506 | reported |
| vintage_band=[0,12) | 0.8641 | [0.8367, 0.8912] | 21103 | reported |
| vintage_band=[12,18) | 0.8673 | [0.8408, 0.8946] | 24818 | reported |
| vintage_band=[18,30) | 0.8806 | [0.8654, 0.8972] | 76921 | reported |
| vintage_band=[30,48) | 0.8916 | [0.8801, 0.9006] | 150174 | reported |
| vintage_band=[48,inf) | 0.8912 | [0.8809, 0.9014] | 194455 | reported |
| sector=Agriculture | 0.9069 | [0.8984, 0.9171] | 135043 | reported |
| sector=Logistics | 0.8483 | [0.8157, 0.8764] | 11568 | reported |
| sector=Manufacturing | 0.8666 | [0.8417, 0.8917] | 30059 | reported |
| sector=Retail | 0.8506 | [0.8205, 0.8835] | 28180 | reported |
| sector=Salaried | 0.8591 | [0.8438, 0.8713] | 161247 | reported |
| sector=Services | 0.8707 | [0.8479, 0.8898] | 49981 | reported |
| sector=Trading | 0.8724 | [0.8492, 0.8927] | 51393 | reported |
| geography=Central | 0.9061 | [0.8877, 0.9221] | 41283 | reported |
| geography=East | 0.9057 | [0.8925, 0.9175] | 69421 | reported |
| geography=North | 0.8868 | [0.8723, 0.9006] | 109699 | reported |
| geography=South | 0.8887 | [0.8784, 0.9002] | 127315 | reported |
| geography=West | 0.8698 | [0.8534, 0.8847] | 119753 | reported |
| calendar_month=0 | 0.7889 | [0.76, 0.8214] | 13500 | reported |
| calendar_month=1 | 0.8283 | [0.7988, 0.8564] | 13500 | reported |
| calendar_month=2 | 0.8506 | [0.8262, 0.8745] | 13500 | reported |
| calendar_month=3 | 0.8846 | [0.8627, 0.9027] | 13500 | reported |
| calendar_month=4 | 0.8926 | [0.8702, 0.913] | 13500 | reported |
| calendar_month=5 | 0.9079 | [0.8889, 0.9228] | 13500 | reported |
| calendar_month=6 | 0.901 | [0.881, 0.9204] | 13463 | reported |
| calendar_month=7 | 0.8887 | [0.87, 0.9069] | 13429 | reported |
| calendar_month=8 | 0.8849 | [0.8653, 0.9032] | 13383 | reported |
| calendar_month=9 | 0.8797 | [0.8612, 0.8972] | 13344 | reported |
| calendar_month=10 | 0.8651 | [0.8467, 0.8868] | 13302 | reported |
| calendar_month=11 | 0.8701 | [0.8521, 0.8911] | 13269 | reported |
| calendar_month=12 | 0.8817 | [0.8618, 0.9013] | 13231 | reported |
| calendar_month=13 | 0.8806 | [0.8593, 0.8967] | 13187 | reported |
| calendar_month=14 | 0.8703 | [0.8477, 0.8898] | 13149 | reported |
| calendar_month=15 | 0.8683 | [0.8488, 0.8877] | 13112 | reported |
| calendar_month=16 | 0.8754 | [0.8522, 0.8918] | 13078 | reported |
| calendar_month=17 | 0.8855 | [0.8686, 0.9048] | 13051 | reported |
| calendar_month=18 | 0.8935 | [0.8743, 0.9102] | 13000 | reported |
| calendar_month=19 | 0.8892 | [0.8667, 0.9088] | 12952 | reported |
| calendar_month=20 | 0.8936 | [0.8762, 0.9132] | 12914 | reported |
| calendar_month=21 | 0.8884 | [0.8658, 0.9065] | 12863 | reported |
| calendar_month=22 | 0.9002 | [0.8818, 0.917] | 12810 | reported |
| calendar_month=23 | 0.8949 | [0.8761, 0.9137] | 12773 | reported |
| calendar_month=24 | 0.8953 | [0.8746, 0.9115] | 12730 | reported |
| calendar_month=25 | 0.9062 | [0.8907, 0.9224] | 12695 | reported |
| calendar_month=26 | 0.901 | [0.8839, 0.9198] | 12649 | reported |
| calendar_month=27 | 0.9041 | [0.885, 0.9194] | 12613 | reported |
| calendar_month=28 | 0.9022 | [0.8856, 0.9198] | 12573 | reported |
| calendar_month=29 | 0.903 | [0.8844, 0.9209] | 12530 | reported |
| calendar_month=30 | 0.9043 | [0.888, 0.9209] | 12499 | reported |
| calendar_month=31 | 0.9022 | [0.8863, 0.9177] | 12458 | reported |
| calendar_month=32 | 0.9044 | [0.8862, 0.9181] | 12416 | reported |
| calendar_month=33 | 0.9031 | [0.8878, 0.9217] | 12373 | reported |
| calendar_month=34 | 0.9053 | [0.8899, 0.9232] | 12334 | reported |
| calendar_month=35 | 0.9141 | [0.8971, 0.9283] | 12291 | reported |

</details>

### 04_calibration

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-08 | ece | overall | ≤ 0.02 | 0.001 | [0.0005, 0.0019] | 467471 | fail | PASS |
| DR-09 | ece | per_cut (all) | ≤ 0.04 | — | — | — | fail | PASS |
| DR-10 | brier_calibrated_minus_brier_raw | overall | < 0.0 | -0.0001 | [-0.0001, -0] | 467471 | fail | PASS |

<details><summary>DR-09 — per-cell breakdown (76 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| portfolio=MSME-CC | 0.0031 | [0.0009, 0.0059] | 46557 | PASS |
| portfolio=MSME-TL | 0.002 | [0.001, 0.0051] | 39920 | PASS |
| portfolio=Housing | 0.0022 | [0.0008, 0.0043] | 71404 | PASS |
| portfolio=Education | 0.0045 | [0.0018, 0.0091] | 37559 | PASS |
| portfolio=Agri | 0.002 | [0.001, 0.0037] | 135043 | PASS |
| portfolio=Retail-Unsecured | 0.0033 | [0.0011, 0.0066] | 45385 | PASS |
| portfolio=LAP | 0.0011 | [0.0008, 0.0041] | 48651 | PASS |
| portfolio=Auto | 0.0032 | [0.001, 0.006] | 42952 | PASS |
| constitution=Individual | 0.0011 | [0.0005, 0.0022] | 335677 | PASS |
| constitution=LLP | 0.0039 | [0.0025, 0.0127] | 7152 | PASS |
| constitution=Partnership | 0.0033 | [0.0014, 0.008] | 14945 | PASS |
| constitution=Proprietorship | 0.0013 | [0.0008, 0.0031] | 93442 | PASS |
| constitution=PvtLtd | 0.0034 | [0.0012, 0.0085] | 16255 | PASS |
| segment=Medium | 0.003 | [0.0015, 0.0099] | 5696 | PASS |
| segment=Micro | 0.0007 | [0.0005, 0.0023] | 288755 | PASS |
| segment=Small | 0.0014 | [0.0005, 0.0031] | 173020 | PASS |
| secured=0 | 0.0013 | [0.0006, 0.003] | 190866 | PASS |
| secured=1 | 0.0009 | [0.0005, 0.002] | 276605 | PASS |
| ticket_band=(147174.015, 361060.349] | 0.0016 | [0.0008, 0.0036] | 93492 | PASS |
| ticket_band=(2289618.96, 50000000.0] | 0.0016 | [0.0006, 0.0037] | 93471 | PASS |
| ticket_band=(361060.349, 916711.962] | 0.0014 | [0.0007, 0.0035] | 93519 | PASS |
| ticket_band=(916711.962, 2289618.96] | 0.0011 | [0.0006, 0.0033] | 93483 | PASS |
| ticket_band=(9999.999, 147174.015] | 0.0018 | [0.0009, 0.0044] | 93506 | PASS |
| vintage_band=[0,12) | 0.0017 | [0.0012, 0.0064] | 21103 | PASS |
| vintage_band=[12,18) | 0.0022 | [0.0014, 0.0056] | 24818 | PASS |
| vintage_band=[18,30) | 0.001 | [0.0007, 0.0035] | 76921 | PASS |
| vintage_band=[30,48) | 0.0007 | [0.0006, 0.0025] | 150174 | PASS |
| vintage_band=[48,inf) | 0.0012 | [0.0007, 0.0028] | 194455 | PASS |
| sector=Agriculture | 0.002 | [0.001, 0.0037] | 135043 | PASS |
| sector=Logistics | 0.0036 | [0.0016, 0.0107] | 11568 | PASS |
| sector=Manufacturing | 0.0041 | [0.0015, 0.0084] | 30059 | PASS |
| sector=Retail | 0.0037 | [0.0018, 0.007] | 28180 | PASS |
| sector=Salaried | 0.0017 | [0.0006, 0.0033] | 161247 | PASS |
| sector=Services | 0.0019 | [0.0008, 0.0048] | 49981 | PASS |
| sector=Trading | 0.0007 | [0.0008, 0.0035] | 51393 | PASS |
| geography=Central | 0.0023 | [0.0014, 0.0058] | 41283 | PASS |
| geography=East | 0.0024 | [0.0014, 0.0042] | 69421 | PASS |
| geography=North | 0.0015 | [0.0007, 0.0032] | 109699 | PASS |
| geography=South | 0.0026 | [0.0008, 0.0044] | 127315 | PASS |
| geography=West | 0.0009 | [0.0006, 0.0028] | 119753 | PASS |
| calendar_month=0 | 0.003 | [0.0025, 0.0054] | 13500 | PASS |
| calendar_month=1 | 0.0016 | [0.001, 0.004] | 13500 | PASS |
| calendar_month=2 | 0.0033 | [0.002, 0.0053] | 13500 | PASS |
| calendar_month=3 | 0.0018 | [0.0016, 0.0043] | 13500 | PASS |
| calendar_month=4 | 0.0033 | [0.0021, 0.0055] | 13500 | PASS |
| calendar_month=5 | 0.0026 | [0.0016, 0.0049] | 13500 | PASS |
| calendar_month=6 | 0.0032 | [0.0018, 0.0057] | 13463 | PASS |
| calendar_month=7 | 0.0023 | [0.0015, 0.005] | 13429 | PASS |
| calendar_month=8 | 0.001 | [0.0013, 0.0039] | 13383 | PASS |
| calendar_month=9 | 0.0026 | [0.0015, 0.0053] | 13344 | PASS |
| calendar_month=10 | 0.0047 | [0.0029, 0.0078] | 13302 | PASS |
| calendar_month=11 | 0.0033 | [0.0017, 0.0059] | 13269 | PASS |
| calendar_month=12 | 0.0017 | [0.0013, 0.0043] | 13231 | PASS |
| calendar_month=13 | 0.0013 | [0.0013, 0.0043] | 13187 | PASS |
| calendar_month=14 | 0.0033 | [0.0021, 0.0059] | 13149 | PASS |
| calendar_month=15 | 0.003 | [0.0018, 0.0058] | 13112 | PASS |
| calendar_month=16 | 0.0037 | [0.0023, 0.0066] | 13078 | PASS |
| calendar_month=17 | 0.0036 | [0.0023, 0.0065] | 13051 | PASS |
| calendar_month=18 | 0.0009 | [0.0013, 0.0042] | 13000 | PASS |
| calendar_month=19 | 0.0022 | [0.0016, 0.0049] | 12952 | PASS |
| calendar_month=20 | 0.0018 | [0.0014, 0.0043] | 12914 | PASS |
| calendar_month=21 | 0.0028 | [0.0016, 0.0056] | 12863 | PASS |
| calendar_month=22 | 0.0017 | [0.0014, 0.0046] | 12810 | PASS |
| calendar_month=23 | 0.0021 | [0.0017, 0.0044] | 12773 | PASS |
| calendar_month=24 | 0.0039 | [0.0022, 0.0064] | 12730 | PASS |
| calendar_month=25 | 0.0039 | [0.0022, 0.0063] | 12695 | PASS |
| calendar_month=26 | 0.002 | [0.0016, 0.0048] | 12649 | PASS |
| calendar_month=27 | 0.0019 | [0.0013, 0.005] | 12613 | PASS |
| calendar_month=28 | 0.0029 | [0.0016, 0.0053] | 12573 | PASS |
| calendar_month=29 | 0.0022 | [0.0015, 0.0048] | 12530 | PASS |
| calendar_month=30 | 0.0014 | [0.0013, 0.0044] | 12499 | PASS |
| calendar_month=31 | 0.002 | [0.0015, 0.0048] | 12458 | PASS |
| calendar_month=32 | 0.0026 | [0.0017, 0.0056] | 12416 | PASS |
| calendar_month=33 | 0.0034 | [0.0019, 0.0062] | 12373 | PASS |
| calendar_month=34 | 0.0046 | [0.0025, 0.0071] | 12334 | PASS |
| calendar_month=35 | 0.0018 | [0.0015, 0.0049] | 12291 | PASS |

</details>

### 05_rank_order

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-11 | risk_band_default_rate_monotonicity | per_portfolio | strictly increasing | — | — | — | fail | PASS |
| DR-12 | monotone_decile_step_fraction | per_portfolio | ≥ 0.9 | 0.5556 | — | 46557 | fail | **FAIL** |

<details><summary>DR-11 — per-cell breakdown (8 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| MSME-CC | [0.0037, 0.1031, 0.864] | — | 46557 | PASS |
| MSME-TL | [0.0032, 0.0976, 0.7566] | — | 39920 | PASS |
| Housing | [0.0031, 0.1788, 0.7892] | — | 71404 | PASS |
| Education | [0.004, 0.1296, 0.7447] | — | 37559 | PASS |
| Agri | [0.0031, 0.0496, 0.6987] | — | 135043 | PASS |
| Retail-Unsecured | [0.0047, 0.108, 0.684] | — | 45385 | PASS |
| LAP | [0.0031, 0.1022, 0.7765] | — | 48651 | PASS |
| Auto | [0.0032, 0.0766, 0.6634] | — | 42952 | PASS |

</details>

<details><summary>DR-12 — per-cell breakdown (8 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| MSME-CC | 0.5556 | — | 46557 | **FAIL** |
| MSME-TL | 0.5556 | — | 39920 | **FAIL** |
| Housing | 0.7778 | — | 71404 | **FAIL** |
| Education | 0.7778 | — | 37559 | **FAIL** |
| Agri | 0.7778 | — | 135043 | **FAIL** |
| Retail-Unsecured | 0.8889 | — | 45385 | **FAIL** |
| LAP | 0.6667 | — | 48651 | **FAIL** |
| Auto | 0.8889 | — | 42952 | **FAIL** |

</details>

### 06_stability

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-13 | psi_score_distribution | overall | ≤ 0.1 | 0.0006 | — | 500168 | fail | PASS |
| DR-14 | max_feature_csi | overall | ≤ 0.25 | 3.6344 | — | 500168 | fail | **FAIL** |

<details><summary>DR-14 — per-cell breakdown (62 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| sector | 0.0012 | — | 500168 | PASS |
| region | 0 | — | 500168 | PASS |
| loan_type | 0.0009 | — | 500168 | PASS |
| segment | 0.0003 | — | 500168 | PASS |
| qualification | 0 | — | 500168 | PASS |
| promoter_age_group | 0 | — | 500168 | PASS |
| log_sanctioned | 0.0004 | — | 500168 | PASS |
| business_age_years | 0 | — | 500168 | PASS |
| dpd | 0 | — | 500168 | PASS |
| utilisation | 0.0004 | — | 500168 | PASS |
| inflow | 0.0004 | — | 500168 | PASS |
| gst_sales | 0.0001 | — | 500168 | PASS |
| txn_count | 0.0001 | — | 500168 | PASS |
| bounce | 0 | — | 500168 | PASS |
| minbal_breach | 0 | — | 500168 | PASS |
| adverse_remark | 0 | — | 500168 | PASS |
| dpd_max_6m | 0 | — | 500168 | PASS |
| times_late_6m | 0 | — | 500168 | PASS |
| bounces_6m | 0.0179 | — | 500168 | PASS |
| minbal_breach_6m | 0.0125 | — | 500168 | PASS |
| util_avg_3m | 0.0004 | — | 500168 | PASS |
| util_max_6m | 0.0182 | — | 500168 | PASS |
| months_over_90pct_util_6m | 0.0259 | — | 500168 | PASS |
| inflow_trend_3m | 0.0519 | — | 500168 | PASS |
| inflow_vs_6m_avg | 0.0765 | — | 500168 | PASS |
| sales_trend_3m | 0.3114 | — | 500168 | **FAIL** |
| txn_drop_flag | 0 | — | 500168 | PASS |
| adverse_remark_6m | 0 | — | 500168 | PASS |
| portfolio | 0.0013 | — | 500168 | PASS |
| constitution | 0 | — | 500168 | PASS |
| state | 0.0001 | — | 500168 | PASS |
| city_tier | 0.0007 | — | 500168 | PASS |
| nic_group | 0.0009 | — | 500168 | PASS |
| secured | 0 | — | 500168 | PASS |
| tenor_months | 0.0008 | — | 500168 | PASS |
| interest_rate_pa | 0.0012 | — | 500168 | PASS |
| vintage_band | 3.6344 | — | 500168 | **FAIL** |
| outstanding | 0.029 | — | 500168 | PASS |
| demanded_amount | 0.0143 | — | 500168 | PASS |
| collected_amount | 0.0122 | — | 500168 | PASS |
| collection_ratio | 0.0033 | — | 500168 | PASS |
| collection_ratio_3m | 0.019 | — | 500168 | PASS |
| balance | 0.0002 | — | 500168 | PASS |
| min_balance_6m | 0.001 | — | 500168 | PASS |
| bureau_score | 0.001 | — | 500168 | PASS |
| drawing_power | 0.0004 | — | 500168 | PASS |
| salary_credit | 0.0003 | — | 500168 | PASS |
| salary_vs_6m_avg | 0.0627 | — | 500168 | PASS |
| salary_gap_6m | 0.0536 | — | 500168 | PASS |
| other_bank_emi | 0.0043 | — | 500168 | PASS |
| emi_burden_ratio | 0.0054 | — | 500168 | PASS |
| ltv | 0.3193 | — | 500168 | **FAIL** |
| ltv_vs_schedule | 0.2676 | — | 500168 | **FAIL** |
| rental_income | 0.0001 | — | 500168 | PASS |
| rental_vs_6m_avg | 0.0737 | — | 500168 | PASS |
| crop_receipt | 0.0025 | — | 500168 | PASS |
| crop_receipt_vs_norm | 0.0014 | — | 500168 | PASS |
| renewal_overdue_months | 0 | — | 500168 | PASS |
| moratorium_active | 0 | — | 500168 | PASS |
| commute_spend | 0.0002 | — | 500168 | PASS |
| commute_vs_6m_avg | 0.0774 | — | 500168 | PASS |
| months_since_moratorium_end_band | 1.0703 | — | 500168 | **FAIL** |

</details>

### 07_leakage

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-15 | dpd_family_attribution_share_at_10_12m | overall | ≤ 0.05 | 0.0381 | [0.0325, 0.0356] | 4330 | fail | PASS |
| DR-16 | permuted_label_auc | overall | ∈ [0.48, 0.52] | 0.5001 | [0.4937, 0.5102] | 63226 | fail | PASS |
| DR-17 | availability_at_time_manifest | overall | must exist | yes | — | 62 | fail | PASS |

<details><summary>DR-17 — per-cell breakdown (62 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| sector | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| region | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| loan_type | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| segment | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| qualification | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| promoter_age_group | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| log_sanctioned | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| business_age_years | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| dpd | same day (T+0) | — | — | PASS |
| utilisation | utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes | — | — | PASS |
| inflow | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| gst_sales | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| txn_count | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| bounce | same day (T+0) | — | — | PASS |
| minbal_breach | same day (T+0) | — | — | PASS |
| adverse_remark | same day to T+1 (branch/RM-filed remark) | — | — | PASS |
| dpd_max_6m | same day (T+0) | — | — | PASS |
| times_late_6m | same day (T+0) | — | — | PASS |
| bounces_6m | same day (T+0) | — | — | PASS |
| minbal_breach_6m | same day (T+0) | — | — | PASS |
| util_avg_3m | utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes | — | — | PASS |
| util_max_6m | utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes | — | — | PASS |
| months_over_90pct_util_6m | utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes | — | — | PASS |
| inflow_trend_3m | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| inflow_vs_6m_avg | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| sales_trend_3m | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| txn_drop_flag | bank inflows T+0 (CBS); GST-sourced fields lag 0-2 months (42% same month, 43% T+1, 15% T+2 — DATA_CARD.md measurement.gst_report_lag_distribution) | — | — | PASS |
| adverse_remark_6m | same day to T+1 (branch/RM-filed remark) | — | — | PASS |
| portfolio | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| constitution | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| state | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| city_tier | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| nic_group | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| secured | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| tenor_months | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| interest_rate_pa | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| vintage_band | known at origination (T+0 forever after) — static account attributes | — | — | PASS |
| outstanding | utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes | — | — | PASS |
| demanded_amount | same day (T+0) | — | — | PASS |
| collected_amount | same day (T+0) | — | — | PASS |
| collection_ratio | same day (T+0) | — | — | PASS |
| collection_ratio_3m | same day (T+0) | — | — | PASS |
| balance | same day (T+0) | — | — | PASS |
| min_balance_6m | same day (T+0) | — | — | PASS |
| bureau_score | up to 3 months stale (DATA_CARD.md bureau.report_lag_months=3 — bureaus refresh monthly and the file reaches the lender later still) | — | — | PASS |
| drawing_power | utilisation T+0 (CBS); drawing_power refreshed quarterly (DATA_CARD.md drawing_power_refresh_months=3) — stale up to 3 months between refreshes | — | — | PASS |
| salary_credit | same day (T+0) | — | — | PASS |
| salary_vs_6m_avg | same day (T+0) | — | — | PASS |
| salary_gap_6m | same day (T+0) | — | — | PASS |
| other_bank_emi | same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale | — | — | PASS |
| emi_burden_ratio | same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale | — | — | PASS |
| ltv | same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale | — | — | PASS |
| ltv_vs_schedule | same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale | — | — | PASS |
| rental_income | same day (T+0) | — | — | PASS |
| rental_vs_6m_avg | same day (T+0) | — | — | PASS |
| crop_receipt | same day (T+0) | — | — | PASS |
| crop_receipt_vs_norm | same day (T+0) | — | — | PASS |
| renewal_overdue_months | same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale | — | — | PASS |
| moratorium_active | same day for EMI-burden/moratorium flags (CBS); LTV updated only at valuation/schedule events, otherwise stale | — | — | PASS |
| commute_spend | same day (T+0) | — | — | PASS |
| commute_vs_6m_avg | same day (T+0) | — | — | PASS |
| months_since_moratorium_end_band | known at origination (T+0 forever after) — static account attributes | — | — | PASS |

</details>

### 08_ablation

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-18 | auc_drop_when_cashflow_family_removed | overall | ≥ 0.04 | 0.001 | [-0.0057, 0.0066] | 63226 | fail | **FAIL** |
| DR-19 | max_auc_gain_from_dropping_any_family | overall | ≤ 0.0 | 0.0123 | [0.0037, 0.023] | 63226 | fail | **FAIL** |

### 09_seeds

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-20 | n_seeds_run | overall | ≥ 5 | 5 | — | 5 | fail | PASS |
| DR-21 | cross_seed_auc_ci_width | overall | ≤ 0.02 | 0.0123 | [0.8475, 0.8598] | 63226 | fail | PASS |

### 10_stress

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-22 | abs_auc_delta_under_2x_base_rate | overall | ≤ 0.03 | 0.0019 | [-0.0023, 0.0061] | 63226 | fail | PASS |
| DR-23 | abs_auc_delta_under_bureau_missing | overall | ≤ 0.02 | 0.0069 | [-0.0152, 0.0031] | 63226 | fail | PASS |

### 11_fairness

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-24 | adverse_impact_ratio | per_cut (protected_proxies) | ≥ 0.8 | 0.9195 | — | 467471 | report | reported |
| DR-25 | tpr_gap | per_cut (protected_proxies) | ≤ 0.15 | 0.0209 | — | 16936 | report | reported |

<details><summary>DR-24 — per-cell breakdown (4 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| promoter_age_group | 0.9195 | — | 467471 | reported |
| qualification | 0.7772 | — | 467471 | reported |
| geography (region) | 0.7198 | — | 467471 | reported |
| constitution | 0.7752 | — | 467471 | reported |

</details>

<details><summary>DR-25 — per-cell breakdown (4 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| promoter_age_group | 0.0209 | — | 16936 | reported |
| qualification | 0.0215 | — | 16936 | reported |
| geography (region) | 0.0992 | — | 16936 | reported |
| constitution | 0.0962 | — | 16936 | reported |

</details>

### 12_baseline_ladder

| ID | Metric | Scope | Band | Observed | 95% CI | n | Severity | Status |
|---|---|---|---|---|---|---|---|---|
| DR-26 | auc_by_baseline_rung | overall | reported, no target | 0.8885 | [0.8814, 0.8949] | 467471 | report | reported |

<details><summary>DR-26 — per-cell breakdown (3 cells)</summary>

| Cell | Observed | 95% CI | n | Status |
|---|---|---|---|---|
| DPD-only rule (logistic, 7 cols) | 0.6947 | [0.688, 0.701] | 467471 | reported |
| Logistic regression (scorecard-style) | 0.8569 | [0.8501, 0.864] | 467471 | reported |
| LightGBM (ours) | 0.8885 | [0.8814, 0.8949] | 467471 | reported |

</details>

## Why each band is what it is

Registered rationale, verbatim from `criteria.yaml`. Notes record where a band's wording admitted more than one reading and which reading we took.

**DR-01 — grouped_auc** (∈ [0.82, 0.92], severity `fail`)  
Discrimination must be good enough to be useful and low enough to be believable. An upper bound is as important as a floor: a synthetic panel that scores above 0.92 has leaked its own generative structure.  
*Source:* plan §B L8 bands; §D gate G2
  
*Note:* THE FLOOR IS 0.82, LOWERED FROM 0.85, AND THIS IS DELIBERATE. The plan's rationale, transcribed: "a floor of 0.85 would tempt tuning toward separability; 0.82 sits credibly beside real 0.81." Published bank early-warning models land around 0.81, so a floor above that would have created pressure to make the synthetic data easier than reality. Registered at 0.82 before any result was produced.

**DR-02 — red_band_precision_at_8_months** (reported, no target, severity `report`)  
This is the honest replacement for the "90% accuracy" claim the mentors rejected. Precision of the Red band, measured at 8 months before NPA onset, reported with a 95% CI beside raw accuracy and the base rate.  
*Source:* plan §B L8 bands; §B L5 DM-4
  
*Note:* REPORTED, NO PRE-REGISTERED TARGET — explicitly so. Putting a target on the headline number is exactly the failure mode the mentors called out. The number goes in the deck as whatever it turns out to be.

**DR-03 — annual_slippage_ratio** (∈ [0.03, 0.05], severity `fail`)  
The synthetic book must slip into NPA at a rate a bank reviewer recognises. A book that slips at 12% a year would make any AUC meaningless.  
*Source:* plan §D gate G2 ("slippage 3–5%")
  
*Note:* INTERPRETATION. G2 states "slippage 3–5%" while §B L4 SD-D5 asserts a label base rate of 3.0 ± 0.5%/yr, which is a narrower and not identical quantity. We read them as two different measurements: slippage = fresh NPA during the year ÷ standard advances at the start of the year (the RBI-style ratio, gated here at 3–5%), and base rate = the mean of default_within_12m over eligible rows (asserted inside the generator, reported here as DR-04). Both are reported; only the G2 band gates.

**DR-04 — label_base_rate_annual** (reported, no target, severity `report`)  
Reported here so the validation report and the generator's in-script assertion can be reconciled by a reviewer without reading the generator.  
*Source:* plan §B L4 SD-D5 (asserted in-script at 3.0 ± 0.5%/yr)
  
*Note:* No gate here — the gate lives in the generator (§B L4 SD-D5) and in DR-03.

**DR-05 — oot_auc_ratio_to_holdout** (≥ 0.95, severity `fail`)  
Temporal generalisation. A model that only works on the months it was trained on is worthless to a bank that will run it next quarter.  
*Source:* plan §B L8 bands ("OOT ≥ 0.95×")
  
*Note:* Ratio form: AUC(out-of-time test) ÷ AUC(grouped holdout) ≥ 0.95. Read as a relative degradation limit of 5%, not an absolute AUC floor.

**DR-06 — auc** (≥ 0.78, severity `fail`)  
This is the mandate that ONE holistic model across all borrower types is legitimate. If the single model only works on MSME term loans, the claim collapses. Every portfolio must clear the floor on its own, with a CI.  
*Source:* plan §B L8 bands; §D gate G2 ("per-portfolio ≥ 0.78 all 7 w/ CI"), with the count corrected to 8 by the 16 Sep 2026 ~02:00 IST ruling recorded on the `portfolio` cut above.
  
*Note:* APPLIES TO ALL EIGHT PORTFOLIOS (MSME-CC, MSME-TL, Housing, Education, Agri, Retail-Unsecured, LAP, Auto) — see the ruling on the `portfolio` cut. The plan text said "all 7"; the correct count is 8 and the floor is pre-registered against every one of them. min_n is 0 deliberately: the floor applies regardless of cell size, so a thin portfolio is a generator problem to fix, not a cell to exempt. The point estimate gates; the CI is reported beside it.

**DR-07 — auc** (reported, no target, severity `report`)  
AUC with CI and n for every level of every one of the nine cuts. No band beyond the portfolio floor was pre-registered, so this is reported in full and read by a human — including the cells that look bad.  
*Source:* plan §B L8 (12 runners, cut list); owner direction 7 ("validated across every cut")
  
*Note:* min_n of 500 is carried over from the plan's only stated cell-size floor (the per-cut ECE clause, DR-10) rather than inventing a second number. Cells below 500 are listed with their n and marked skipped_low_n.

**DR-08 — ece** (≤ 0.02, severity `fail`)  
"PD = 40%" has to mean an observed 40% default frequency, or the cockpit's numbers cannot be used for provisioning conversations.  
*Source:* plan §B L8 bands ("ECE ≤ 0.02 overall")

**DR-09 — ece** (≤ 0.04, severity `fail`)  
Overall calibration can hide a portfolio the model is systematically over-confident about. The looser per-cut band acknowledges smaller cells.  
*Source:* plan §B L8 bands ("≤ 0.04 per cut (n≥500)")
  
*Note:* min_n = 500 is the plan's own number and gates this criterion.

**DR-10 — brier_calibrated_minus_brier_raw** (< 0.0, severity `fail`)  
Isotonic calibration must actually improve the score, not merely re-shape it. If it does not, the calibration step is decoration and should be cut.  
*Source:* plan §B L8 bands ("Brier(cal) < Brier(raw)")

**DR-11 — risk_band_default_rate_monotonicity** (strictly increasing, severity `fail`)  
Observed default rate must rise strictly from Green to Amber to Red inside every portfolio. A relationship manager reads the band, not the score, so this is the property the product actually rests on.  
*Source:* plan §B L8 bands ("bands strictly monotone within every portfolio"); §D gate G2
  
*Note:* Asserted on the 8-month rank-order exhibit (branch 0914ac6, §B L5 DM-3), i.e. the ordering must hold in each of the exhibit's months, not only pooled. Strict monotonicity — ties fail.

**DR-12 — monotone_decile_step_fraction** (≥ 0.9, severity `fail`)  
A finer-grained rank-order check than the three bands: at decile resolution, at least 9 of the 10 step-ups in observed default rate must be non-decreasing.  
*Source:* plan §B L8 bands ("≥9/10 decile steps")
  
*Note:* INTERPRETATION. The plan's clause reads "bands strictly monotone within every portfolio, ≥9/10 decile steps" as one sentence. We split it into two criteria because it states two different tests at two resolutions (three bands, strict; ten deciles, 9-of-10). Both are pre-registered at the plan's own numbers, and both are scoped per portfolio, which is the scope the sentence carries.

**DR-13 — psi_score_distribution** (≤ 0.1, severity `fail`)  
Population Stability Index of the score distribution between the training window and the most recent window. 0.10 is the conventional "no meaningful shift" line in bank model-risk practice.  
*Source:* plan §B L8 bands ("PSI ≤ 0.10")

**DR-14 — max_feature_csi** (≤ 0.25, severity `fail`)  
Characteristic Stability Index per input feature. Reported for every feature; the maximum across features gates.  
*Source:* plan §B L8 bands ("no CSI > 0.25")
  
*Note:* Expressed as a maximum so a single number gates, which is what "no CSI > 0.25" says. The full per-feature table goes in the report.

**DR-15 — dpd_family_attribution_share_at_10_12m** (≤ 0.05, severity `fail`)  
This is what makes the "we see it a year early" claim honest. For predictions made 10–12 months before NPA onset, the days-past-due family must contribute at most 5% of total absolute attribution — the warning has to come from cash flow and utilisation, not from an account that is already visibly late.  
*Source:* plan §B L8 bands ("DPD share ≤ 5% at 10–12 mo")
  
*Note:* Attribution = share of summed absolute SHAP-style contribution over the DPD family as listed in src/rigor.py GROUPS["Days-past-due / repayment"].

**DR-16 — permuted_label_auc** (∈ [0.48, 0.52], severity `fail`)  
Retrain the full pipeline on randomly permuted labels. Anything outside chance means the evaluation harness itself leaks — the strongest single check that the reported AUC is real.  
*Source:* plan §B L8 bands ("permutation AUC ∈ [0.48,0.52]")
  
*Note:* INTERPRETATION: the permutation is of the LABEL (the standard permutation-test form), with the split, features and hyper-parameters left untouched. Averaged over the registered seeds.

**DR-17 — availability_at_time_manifest** (must exist, severity `fail`)  
A per-feature manifest stating, for every model input, when that value would actually have been knowable in a bank's systems relative to the observation month. A feature that a bank only learns after the fact is leakage no statistical test will catch.  
*Source:* plan §B L8 bands ("availability-at-time manifest")
  
*Note:* INTERPRETATION. The plan lists this among the leakage bands without saying "reported", so we registered it as a gating artefact: the manifest must exist and cover every feature the model consumes. A feature missing from the manifest fails the criterion.

**DR-18 — auc_drop_when_cashflow_family_removed** (≥ 0.04, severity `fail`)  
The product's whole thesis is that current-account cash flow sees trouble before the loan account does. If removing the cash-flow family costs less than 0.04 AUC, the thesis is not supported by our own model.  
*Source:* plan §B L8 bands ("cash-flow family ≥ 0.04")
  
*Note:* Family as listed in src/rigor.py GROUPS["Cash-flow (inflows / GST)"].

**DR-19 — max_auc_gain_from_dropping_any_family** (≤ 0.0, severity `fail`)  
No feature family may be actively harmful. A family whose removal improves the model is either noise the model is over-fitting or a bug.  
*Source:* plan §B L8 bands ("no family raises AUC when dropped")
  
*Note:* Registered exactly as written, on the point estimate, with no noise allowance. A small positive delta inside its own CI would still be recorded as a failure and explained in the report rather than waved through — that decision is being made now, not after seeing the number.

**DR-20 — n_seeds_run** (≥ 5, severity `fail`)  
One seed is an anecdote. Five is the minimum at which the CI below means anything.  
*Source:* plan §B L8 bands ("≥5 seeds"); §D gate G7

**DR-21 — cross_seed_auc_ci_width** (≤ 0.02, severity `fail`)  
The headline AUC must be a property of the model, not of the seed. A cross-seed interval wider than 0.02 means the number we would print is within noise of a materially different number.  
*Source:* plan §B L8 bands ("CI width ≤ 0.02")

**DR-22 — abs_auc_delta_under_2x_base_rate** (≤ 0.03, severity `fail`)  
A downturn doubles slippage. The model has to keep ranking under it, or it is exactly the wrong tool at exactly the wrong time.  
*Source:* plan §B L8 bands ("2× base rate ΔAUC ≤ 0.03")
  
*Note:* Absolute delta against the base scenario; direction is reported.

**DR-23 — abs_auc_delta_under_bureau_missing** (≤ 0.02, severity `fail`)  
Bureau data is the input most likely to be unavailable, delayed or consent-blocked in production. The model must degrade gracefully without it.  
*Source:* plan §B L8 bands ("bureau-missing ≤ 0.02")
  
*Note:* INTERPRETATION: the stress is the bureau family fully masked at score time (100% missing), not the ~7% MAR missingness the generator already builds in (§B L4 SD-D4). The generator's baseline missingness is part of the base scenario, not the stress.

**DR-24 — adverse_impact_ratio** (≥ 0.8, severity `report`)  
Four-fifths rule on the flag rate: least-flagged group ÷ most-flagged group within each protected-proxy attribute, at the live operating threshold.  
*Source:* plan §B L8 bands ("fairness 80% rule ... reported honestly")
  
*Note:* REPORTED, NOT GATED — the plan says "reported honestly". The 0.80 reference line is recorded so the report can state how far each attribute sits from it, and any breach is written into the README's "what we did not build, and why" rather than being tuned away. DRISHTi holds no gender, caste, religion or marital-status field at all; the protected-proxy attributes evaluated are promoter_age_group, qualification, geography (region) and constitution.

**DR-25 — tpr_gap** (≤ 0.15, severity `report`)  
Maximum minus minimum true-positive rate across the groups of each protected-proxy attribute at the operating threshold — i.e. whether the early warning actually reaches every group equally.  
*Source:* plan §B L8 bands ("TPR gap ≤ 0.15 reported honestly")
  
*Note:* Same treatment as DR-24: 0.15 is a reference line that is reported, not a gate.

**DR-26 — auc_by_baseline_rung** (reported, no target, severity `report`)  
Contextualises the gain: DPD-only rule, logistic-regression scorecard, then the LightGBM model, each with CI. If the scorecard is within noise of the model, that is the honest finding and the deck says so.  
*Source:* plan §B L8 (runner 12); src/rigor.py baseline ladder
  
*Note:* The plan specifies runner 12 but pre-registers no band for it, so no threshold was invented. Reported with CIs; a human reads it.

## Figures

- `figures/ablation_deltas.png`
- `figures/auc_by_cut_grid.png`
- `figures/auc_by_portfolio.png`
- `figures/availability_manifest_note.png`
- `figures/baseline_ladder.png`
- `figures/csi_features.png`
- `figures/decile_steps.png`
- `figures/ece_by_cut.png`
- `figures/fairness_flag_rates.png`
- `figures/fairness_tpr_gaps.png`
- `figures/holdout_roc.png`
- `figures/lead_time_attribution.png`
- `figures/oot_auc_by_month.png`
- `figures/permutation_auc.png`
- `figures/psi_score.png`
- `figures/rank_order_small_multiples.png`
- `figures/red_band_precision.png`
- `figures/reliability_overall.png`
- `figures/seed_sweep_auc.png`
- `figures/stress_auc_deltas.png`


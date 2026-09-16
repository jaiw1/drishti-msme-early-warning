"""
01 Grouped holdout — headline discrimination, the honest Red-band number, and the book's slippage

Pre-registered criteria this runner answers: DR-01, DR-02, DR-03, DR-04

Consumes
--------
* ``data/msme_loan_panel.csv``
      - account_id, month_idx, date, portfolio, constitution, secured,
        segment, sector, region, loan_type, qualification,
        promoter_age_group, log_sanctioned, business_age_years,
        vintage_months, dpd, utilisation, inflow, gst_sales, txn_count,
        bounce, minbal_breach, adverse_remark, dpd_max_6m, times_late_6m,
        bounces_6m, minbal_breach_6m, util_avg_3m, util_max_6m,
        months_over_90pct_util_6m, inflow_trend_3m, inflow_vs_6m_avg,
        sales_trend_3m, txn_drop_flag, adverse_remark_6m,
        default_within_12m, sma2_within_6m, labelable, months_to_npa
* ``data/accounts_static.csv``
      - account_id, portfolio, constitution, secured, sector, region,
        loan_type, segment, qualification, promoter_age_group,
        sanctioned_amount, business_age_years, vintage_months_0,
        is_defaulter, npa_month, severity, onset
* ``app/public/demo_data.json``
      - accounts[].{account_id, pd, band, timeline[].{month, pd},
        reasons[]}, metrics.{auc, ks, base_rate, recall_at_budget[],
        recall_by_lead_time[]}

Produces
--------
* ``figures/holdout_roc.png``
* ``figures/red_band_precision.png``
* one Result per criterion above: value, 95% CI, n (and `breakdown`
  with one dict per cell for the per-cut / per-portfolio / per-product ones)

Method, as pre-registered
-------------------------
Fit the production pipeline on the account-grouped training split and score
the held-out accounts. Report ROC-AUC pooled over every eligible holdout row
(labelable == 1), the Red-band precision at the 8-months-before-onset
observation point with a bootstrap CI, the annual slippage ratio (fresh NPA
during the year / standard advances at the start of it) and the mean of
`default_within_12m`. Bootstrap resamples at account_id.

Status
------
STUB. Raises NotImplementedError, which the harness records as `pending` for
every criterion above — never as a pass. The interface is written down now, ahead
of the first model result, while the data lanes are still changing the shape of
these files; implementing against a shape that is mid-flight would be worse than
documenting it.
"""

from __future__ import annotations

from validation.criteria import Criterion, Result, RunnerContext

#: Files this runner will read, relative to the repository root.
INPUTS: tuple[str, ...] = (
    "data/msme_loan_panel.csv",
    "data/accounts_static.csv",
    "app/public/demo_data.json",
)


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    raise NotImplementedError(
        "runner 01 pending: needs data/msme_loan_panel.csv (default_within_12m, "
        "labelable, account_id), data/accounts_static.csv (npa_month, onset), "
        "app/public/demo_data.json (band, pd)"
    )

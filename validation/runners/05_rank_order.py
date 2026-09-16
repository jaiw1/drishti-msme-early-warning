"""
05 Rank order — bands and deciles inside every portfolio

Pre-registered criteria this runner answers: DR-11, DR-12

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
* ``app/public/demo_data.json``
      - accounts[].{account_id, pd, band, timeline[].{month, pd},
        reasons[]}, metrics.{auc, ks, base_rate, recall_at_budget[],
        recall_by_lead_time[]}

Produces
--------
* ``figures/rank_order_small_multiples.png``
* ``figures/decile_steps.png``
* one Result per criterion above: value, 95% CI, n (and `breakdown`
  with one dict per cell for the per-cut / per-portfolio / per-product ones)

Method, as pre-registered
-------------------------
Build the 8-month rank-order exhibit (plan §B L5 DM-3, branch 0914ac6):
for each portfolio and each of the 8 months, the observed default rate by
risk band and by score decile. Report strict band monotonicity per portfolio
and the fraction of the 10 decile steps that do not fall.

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
    "app/public/demo_data.json",
)


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    raise NotImplementedError(
        "runner 05 pending: needs data/msme_loan_panel.csv (default_within_12m, "
        "portfolio, month_idx), app/public/demo_data.json (accounts[].band, "
        "accounts[].pd)"
    )

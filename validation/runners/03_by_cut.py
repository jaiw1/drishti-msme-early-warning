"""
03 Per-portfolio floor and the full by-cut table

Pre-registered criteria this runner answers: DR-06, DR-07

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

Produces
--------
* ``figures/auc_by_portfolio.png``
* ``figures/auc_by_cut_grid.png``
* one Result per criterion above: value, 95% CI, n (and `breakdown`
  with one dict per cell for the per-cut / per-portfolio / per-product ones)

Method, as pre-registered
-------------------------
AUC with a bootstrap CI and an n for every level of all nine registered
cuts. The portfolio cut gates (every portfolio must clear the floor — see
the 16 Sep ruling recorded on `cuts.portfolio`); the rest are reported.
Ticket and vintage bands are built from the pre-registered binning rules in
criteria.yaml, never recomputed ad hoc.

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
)


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    raise NotImplementedError(
        "runner 03 pending: needs data/msme_loan_panel.csv (portfolio, "
        "constitution, segment, secured, sector, region, month_idx, "
        "vintage_months), data/accounts_static.csv (sanctioned_amount)"
    )

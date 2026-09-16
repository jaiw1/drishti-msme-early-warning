"""
10 Stress — a downturn, and no bureau

Pre-registered criteria this runner answers: DR-22, DR-23

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
* ``figures/stress_auc_deltas.png``
* one Result per criterion above: value, 95% CI, n (and `breakdown`
  with one dict per cell for the per-cut / per-portfolio / per-product ones)

Method, as pre-registered
-------------------------
Two pre-registered scenarios against the base run: base rate doubled, and
the bureau family fully masked at score time (not the ~7% MAR missingness
the generator already builds in). Report the absolute AUC change for each,
with direction.

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
        "runner 10 pending: needs data/msme_loan_panel.csv regenerated at 2x base "
        "rate (src/generator/), plus the bureau feature list to mask"
    )

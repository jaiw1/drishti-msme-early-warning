"""
07 Leakage — the claim that we see it a year early

Pre-registered criteria this runner answers: DR-15, DR-16, DR-17

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
* ``data/rigor.json``
      - calibration.{reliability[], brier_raw, brier_cal},
        leakage.lead_time_attribution[], oot.{auc_early, auc_late},
        baseline_ladder[]
* ``data/bank/**``
      - the --bank enrichment drop plus its provenance manifest (per-field
        {value, source, url, retrieved_on, confidence})

Produces
--------
* ``figures/lead_time_attribution.png``
* ``figures/permutation_auc.png``
* one Result per criterion above: value, 95% CI, n (and `breakdown`
  with one dict per cell for the per-cut / per-portfolio / per-product ones)

Method, as pre-registered
-------------------------
Three checks. (a) Lead-time attribution: for predictions made 10-12 months
before NPA onset, the share of total absolute SHAP contribution carried by
the DPD family (src/rigor.py GROUPS). (b) Permutation: retrain on shuffled
labels, averaged over the registered seeds. (c) Availability-at-time
manifest: one row per model input stating when a bank would actually have
known that value relative to the observation month, and which API supplies
it; a feature absent from the manifest fails the criterion.

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
    "data/rigor.json",
    "data/bank/**",
)


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    raise NotImplementedError(
        "runner 07 pending: needs data/msme_loan_panel.csv (all feature columns, "
        "months_to_npa), data/accounts_static.csv (onset, npa_month), "
        "data/rigor.json (leakage.lead_time_attribution), data/bank/** provenance "
        "manifest"
    )

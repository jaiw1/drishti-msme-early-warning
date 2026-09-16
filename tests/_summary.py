"""Distributional fingerprint of a generated panel.

Shared by :mod:`test_generator_equivalence` and by the fixture-building entry
point, so the reference (the old row-by-row simulator's CSV) and the candidate
(the vectorised package's CSV) are always summarised by exactly the same code.

Both sides are summarised *after* a CSV round trip, because the contract the
downstream pipeline depends on is the CSV, not the in-memory frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "CATEGORICAL_COLUMNS",
    "NUMERIC_COLUMNS",
    "QUANTILES",
    "channel_leads",
    "summarise",
]

#: numeric columns the equivalence test compares distribution-by-distribution
NUMERIC_COLUMNS: tuple[str, ...] = (
    "log_sanctioned", "business_age_years", "vintage_months",
    "dpd", "utilisation", "inflow", "gst_sales", "txn_count",
    "bounce", "minbal_breach", "adverse_remark",
    "dpd_max_6m", "times_late_6m", "bounces_6m", "minbal_breach_6m",
    "util_avg_3m", "util_max_6m", "months_over_90pct_util_6m",
    "inflow_trend_3m", "inflow_vs_6m_avg", "sales_trend_3m",
    "txn_drop_flag", "adverse_remark_6m",
)

#: categorical columns whose value shares are compared
CATEGORICAL_COLUMNS: tuple[str, ...] = (
    "sector", "region", "loan_type", "segment", "qualification", "promoter_age_group",
)

QUANTILES: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)

#: the deterioration is only looked for inside this many months before NPA
SLIDE_WINDOW = 18


def channel_leads(panel: pd.DataFrame) -> dict[str, float]:
    """Median months-before-NPA at which each deterioration channel fires.

    For every defaulting account, the *largest* ``months_to_npa`` in
    ``1..SLIDE_WINDOW`` at which a channel deviates from that account's own
    baseline is taken; the median across accounts is reported.  The ordered
    deterioration the dataset is built on implies

        cash-flow  >=  utilisation  >=  bounces  >=  days-past-due

    Thresholds are account-relative (cash-flow and utilisation) or noise-light
    (two bounces in six months, any DPD), so a term loan with a structurally
    lower utilisation is judged on the same footing as a cash-credit account.

    Args:
        panel: the generated account-month panel.

    Returns:
        Channel name -> median lead in months.
    """
    panel = panel.assign(account_id=panel["account_id"].astype(str))
    pre_slide = panel[panel.months_to_npa > SLIDE_WINDOW]
    early = panel[panel.month_idx < 3]
    signals = ["utilisation", "inflow"]
    base = pre_slide.groupby("account_id")[signals].median()
    fallback = early.groupby("account_id")[signals].median()
    base = base.reindex(fallback.index).fillna(fallback)

    rows = panel[(panel.months_to_npa >= 1) & (panel.months_to_npa <= SLIDE_WINDOW)]
    joined = rows.join(base, on="account_id", rsuffix="_base")
    fires = {
        "cash_flow": joined.inflow < 0.85 * joined.inflow_base,
        "utilisation": joined.utilisation > 1.25 * joined.utilisation_base,
        "bounces": joined.bounces_6m >= 2,
        "dpd": joined.dpd > 0,
    }
    leads: dict[str, float] = {}
    for name, mask in fires.items():
        lead = joined.loc[mask].groupby("account_id").months_to_npa.max()
        leads[name] = float(lead.median()) if len(lead) else 0.0
    return leads


def summarise(panel: pd.DataFrame) -> dict:
    """Summarise a panel into a comparable, JSON-serialisable fingerprint.

    Args:
        panel: an account-month panel, read back from CSV.

    Returns:
        Schema, per-column moments and quantiles, label prevalence and the
        ordered-deterioration channel leads.
    """
    numeric = {}
    for column in NUMERIC_COLUMNS:
        values = panel[column].to_numpy(dtype=np.float64)
        numeric[column] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=0)),
            "quantiles": [float(q) for q in np.quantile(values, QUANTILES)],
        }
    shares = {
        column: {
            str(k): float(v)
            for k, v in panel[column].value_counts(normalize=True).sort_index().items()
        }
        for column in CATEGORICAL_COLUMNS
    }
    return {
        "columns": list(panel.columns),
        "dtypes": {c: str(t) for c, t in panel.dtypes.items()},
        "n_rows": int(len(panel)),
        "n_accounts": int(panel.account_id.nunique()),
        "default_rate": float(panel.default_within_12m.mean()),
        "labelable_share": float(panel.labelable.mean()),
        "numeric": numeric,
        "shares": shares,
        "channel_leads": channel_leads(panel),
    }


def _main() -> None:
    """Rebuild the reference fingerprint from a panel CSV.

    Usage::

        python3 tests/_summary.py data/msme_loan_panel.csv tests/legacy_reference.json

    The committed fixture was built from the July 2026 row-by-row simulator's
    ``data/msme_loan_panel.csv`` (9,000 accounts x 36 months, seed 20260709).
    Rebuild it only when the dataset contract is deliberately changed.
    """
    import json
    import sys

    source, destination = sys.argv[1], sys.argv[2]
    fingerprint = summarise(pd.read_csv(source))
    with open(destination, "w") as handle:
        json.dump(fingerprint, handle, indent=1, sort_keys=True)
    print(f"wrote {destination} from {source}")


if __name__ == "__main__":
    _main()

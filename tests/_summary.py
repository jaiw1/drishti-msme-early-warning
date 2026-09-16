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
    "CHAINS",
    "SPINE_RULES",
    "NUMERIC_COLUMNS",
    "QUANTILES",
    "SLIDE_WINDOW",
    "baselines_by_account",
    "channel_leads",
    "signal_lead",
    "summarise",
    "first_warning_leads",
    "sustained_lead",
    "sustained_leads_by_account",
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


def baselines_by_account(panel: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Each account's own healthy level for ``columns``.

    The healthy level is the median over the months before the slide could
    have begun; accounts with no such month fall back to their first three
    observed months.  Judging a signal against the account's own baseline is
    what lets one rule work across portfolios whose levels differ by orders of
    magnitude (a KCC farmer's crop receipt and a home-loan salary credit).

    Args:
        panel: the generated account-month panel, ``account_id`` as strings.
        columns: the columns to baseline.

    Returns:
        A frame indexed by ``account_id``, one column per requested column.
    """
    pre_slide = panel[panel.months_to_npa > SLIDE_WINDOW]
    early = panel[panel.month_idx < 3]
    base = pre_slide.groupby("account_id")[columns].median()
    fallback = early.groupby("account_id")[columns].median()
    return base.reindex(fallback.index).fillna(fallback)


def signal_lead(
    panel: pd.DataFrame,
    column: str,
    rule: str,
    threshold: float,
    base: pd.DataFrame | None = None,
) -> tuple[float, float]:
    """Median months before NPA at which a signal first fires, and its reach.

    Args:
        panel: rows for one portfolio, ``account_id`` as strings.
        column: the signal.
        rule: ``"lt"``/``"gt"`` compare against ``threshold`` directly;
            ``"rel_lt"``/``"rel_gt"`` compare against ``threshold`` times the
            account's own baseline.
        threshold: the level, or the multiple of the baseline.
        base: per-account baselines, required for the relative rules.

    Returns:
        ``(median lead in months, share of defaulting accounts it fires for)``.
    """
    rows = panel[(panel.months_to_npa >= 1) & (panel.months_to_npa <= SLIDE_WINDOW)]
    if rule.startswith("rel"):
        assert base is not None, "a relative rule needs baselines"
        rows = rows.join(base[[column]], on="account_id", rsuffix="_base")
        reference = threshold * rows[f"{column}_base"]
    else:
        reference = threshold
    fired = rows[column] < reference if rule.endswith("lt") else rows[column] > reference
    hits = rows.loc[fired.fillna(False)].groupby("account_id").months_to_npa.max()
    accounts = rows.account_id.nunique()
    if not accounts:
        return 0.0, 0.0
    return (float(hits.median()) if len(hits) else 0.0), len(hits) / accounts


#: consecutive months a signal must stay fired before it counts as a warning
SUSTAIN_MONTHS = 3

#: Each portfolio's chain, as the SD-D4 panel makes it readable: the first link
#: of the chain the build plan gave that product, the rule that reads it, and
#: the level.  ``rel_*`` rules compare against the account's own healthy
#: baseline, which is how one rule can span a KCC crop receipt and a home-loan
#: salary credit without pretending they are the same size.
#:
#: These are NOT SD-D3's thresholds.  SD-D3 calibrated them against a panel
#: with no measurement noise, where "did this series ever cross its threshold"
#: was a fair question of a defaulter.  With reporting lags, crop-year yield
#: swings, late rent, festival seasons and a share of tenants paying a month
#: behind, every series crosses every threshold somewhere in eighteen months —
#: so the rule became what a bank would actually use (three consecutive months,
#: :func:`sustained_lead`) and the levels were re-picked against the noisy
#: panel with an eye on how often the same rule fires on an account that never
#: goes bad.  LAP moved from ``rental_vs_6m_avg`` to ``rental_income`` against
#: the borrower's own baseline for the same reason: a six-month-average
#: comparison is unreadable once 12% of tenants pay late.
CHAINS: dict[str, tuple[str, str, float]] = {
    # GST sales -> utilisation -> bounces -> DPD
    "msme_cc": ("gst_sales", "rel_lt", 0.85),
    # EMI coverage -> part-payment -> DPD
    "msme_tl": ("collection_ratio", "lt", 0.90),
    # salary gap -> balance-floor breach -> EMI bounce -> DPD
    "housing": ("salary_credit", "rel_lt", 0.75),
    # moratorium end -> payment stop -> DPD
    "education": ("collection_ratio", "lt", 0.90),
    # harvest miss (seasonal) -> renewal overdue -> DPD
    "agri": ("crop_receipt_vs_norm", "lt", -0.40),
    # EMI stacking -> min-balance -> bounce -> DPD
    "retail_unsecured": ("emi_burden_ratio", "rel_gt", 1.30),
    # rental dip + LTV deterioration -> DPD
    "lap": ("rental_income", "rel_lt", 0.60),
    # commute spend + salary gap -> DPD
    "auto": ("commute_spend", "rel_lt", 0.55),
}

#: what an early-warning system watches on every account, whatever the product
SPINE_RULES: list[tuple[str, str, float]] = [
    ("collection_ratio", "lt", 0.90),
    ("inflow", "rel_lt", 0.80),
]


def _fired(
    rows: pd.DataFrame, column: str, rule: str, threshold: float, base: pd.DataFrame | None
) -> pd.Series:
    """Boolean per row: is ``column`` past ``threshold`` under ``rule``?"""
    if rule.startswith("rel"):
        assert base is not None, "a relative rule needs baselines"
        rows = rows.join(base[[column]], on="account_id", rsuffix="_base")
        reference = threshold * rows[f"{column}_base"]
    else:
        reference = threshold
    fired = rows[column] < reference if rule.endswith("lt") else rows[column] > reference
    return fired.fillna(False)


def sustained_leads_by_account(
    panel: pd.DataFrame,
    column: str,
    rule: str,
    threshold: float,
    base: pd.DataFrame | None = None,
    sustain: int = SUSTAIN_MONTHS,
) -> pd.Series:
    """Per-account sustained lead, in months before NPA; 0 where it never fires.

    Args:
        panel: rows for one portfolio, ``account_id`` as strings.
        column: the signal.
        rule: ``lt``/``gt``/``rel_lt``/``rel_gt``.
        threshold: the level, or the multiple of the account's own baseline.
        base: per-account baselines, required for the relative rules.
        sustain: consecutive months the signal must stay fired.

    Returns:
        A Series indexed by ``account_id``.
    """
    rows = panel[(panel.months_to_npa >= 1) & (panel.months_to_npa <= SLIDE_WINDOW)]
    if not len(rows):
        return pd.Series(dtype=float)
    grid = (
        rows.assign(fired=_fired(rows, column, rule, threshold, base))
        .pivot_table(index="account_id", columns="months_to_npa", values="fired",
                     aggfunc="max", fill_value=False)
        .astype(bool)
    )
    offsets = np.asarray(grid.columns, dtype=np.int64)
    values = grid.to_numpy()
    held = values.copy()
    for step in range(1, sustain):
        held[:, step:] &= values[:, :-step]
    leads = np.where(
        held.any(axis=1), offsets[np.argmax(held[:, ::-1], axis=1) * -1 - 1], 0
    )
    return pd.Series(leads, index=grid.index, name=column)


def first_warning_leads(
    panel: pd.DataFrame, rules: list[tuple[str, str, float]], sustain: int = SUSTAIN_MONTHS
) -> pd.Series:
    """Earliest sustained warning across several signals, per account.

    This is what an early-warning system actually does: it watches every
    instrument it has and raises the alarm on whichever moves first.  Judging
    the panel on one column at a time understates the lead for exactly the
    borrowers SD-D4 made interesting — the ones whose own product signal is
    dark but whose collection ratio is not.

    Args:
        panel: rows for one portfolio, ``account_id`` as strings.
        rules: ``(column, rule, threshold)`` triples to watch.
        sustain: consecutive months a signal must stay fired.

    Returns:
        Per-account months before NPA of the earliest sustained warning; 0 for
        accounts nothing ever fired for.
    """
    best: pd.Series | None = None
    for column, rule, threshold in rules:
        observed = panel[panel[column].notna()]
        if not len(observed):
            continue
        base = (
            baselines_by_account(observed, [column]) if rule.startswith("rel") else None
        )
        leads = sustained_leads_by_account(observed, column, rule, threshold, base, sustain)
        best = leads if best is None else best.reindex(
            best.index.union(leads.index)
        ).fillna(0).combine(leads.reindex(best.index.union(leads.index)).fillna(0), max)
    return pd.Series(dtype=float) if best is None else best


def sustained_lead(
    panel: pd.DataFrame,
    column: str,
    rule: str,
    threshold: float,
    base: pd.DataFrame | None = None,
    sustain: int = SUSTAIN_MONTHS,
) -> tuple[float, float]:
    """Median months before NPA at which a signal fires **and stays fired**.

    :func:`signal_lead` asks whether a signal ever crossed its threshold, which
    was a fair question of the July 2026 panel and is not a fair question of
    the SD-D4 one.  With measurement noise, seasonal confounders and transient
    episodes in the data, *every* series crosses *every* threshold somewhere in
    eighteen months — so "did it ever fire" measures the noise, not the chain.

    A warning is therefore defined the way a bank would define one: the signal
    is past its threshold for ``sustain`` consecutive months.  The lead is the
    earliest month before NPA at which that is true.

    Args:
        panel: rows for one portfolio, ``account_id`` as strings.
        column: the signal.
        rule: ``"lt"``/``"gt"`` compare against ``threshold`` directly;
            ``"rel_lt"``/``"rel_gt"`` compare against ``threshold`` times the
            account's own baseline.
        threshold: the level, or the multiple of the baseline.
        base: per-account baselines, required for the relative rules.
        sustain: consecutive months required.

    Returns:
        ``(median lead in months, share of defaulting accounts it fires for)``.
    """
    accounts = panel[
        (panel.months_to_npa >= 1) & (panel.months_to_npa <= SLIDE_WINDOW)
    ].account_id.nunique()
    if not accounts:
        return 0.0, 0.0
    leads = sustained_leads_by_account(panel, column, rule, threshold, base, sustain)
    hit = leads[leads > 0]
    if not len(hit):
        return 0.0, 0.0
    return float(hit.median()), len(hit) / accounts


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

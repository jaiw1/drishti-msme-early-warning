"""
Metric arithmetic for runners 01-06, on known inputs — no model training, no
generated panel. These are the tests that would catch a transposed formula
(PSI's expected/actual swapped, ECE's bin weighting dropped, a bootstrap that
resamples rows instead of groups) even if a real LightGBM run happened to look
plausible.

Run with pytest, or standalone:

    pytest validation/tests/test_metrics.py -q
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.runners import _shared as sh  # noqa: E402

#: `01_holdout` is not a valid dotted-import identifier (leading digit), so it
#: is loaded the same way validation/run.py loads every runner module.
holdout01 = importlib.import_module("validation.runners.01_holdout")


# ---------------------------------------------------------------------------
# ECE
# ---------------------------------------------------------------------------
def test_ece_zero_when_perfectly_calibrated():
    # Every bin's mean prediction equals its observed rate exactly.
    p = np.array([0.05] * 20 + [0.95] * 20)
    y = np.array([0] * 19 + [1] + [1] * 19 + [0])  # 1/20 and 19/20 -> not exact
    # Build an exactly-calibrated set instead: predicted 0.5 for a 50/50 bin.
    p = np.array([0.5] * 10)
    y = np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
    assert sh.ece(y, p, n_bins=10) == pytest.approx(0.0, abs=1e-9)


def test_ece_matches_hand_computation_two_bins():
    # Bin A (p in [0, 0.5)): 4 rows, mean p=0.1, observed rate=0.25 -> |0.25-0.1|=0.15, weight 4/8
    # Bin B (p in [0.5, 1]): 4 rows, mean p=0.9, observed rate=0.75 -> |0.75-0.9|=0.15, weight 4/8
    p = np.array([0.1, 0.1, 0.1, 0.1, 0.9, 0.9, 0.9, 0.9])
    y = np.array([1, 0, 0, 0, 1, 1, 1, 0])
    expected = 0.5 * 0.15 + 0.5 * 0.15
    assert sh.ece(y, p, n_bins=2) == pytest.approx(expected, abs=1e-9)


def test_ece_empty_is_zero():
    assert sh.ece(np.array([]), np.array([]), n_bins=10) == 0.0


# ---------------------------------------------------------------------------
# Brier
# ---------------------------------------------------------------------------
def test_brier_matches_sklearn():
    from sklearn.metrics import brier_score_loss
    y = np.array([0, 1, 1, 0, 1])
    p = np.array([0.1, 0.8, 0.6, 0.3, 0.9])
    assert sh.brier(y, p) == pytest.approx(brier_score_loss(y, p))


# ---------------------------------------------------------------------------
# grouped_auc
# ---------------------------------------------------------------------------
def test_grouped_auc_perfect_separation_is_one():
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9])
    assert sh.grouped_auc(y, p) == pytest.approx(1.0)


def test_grouped_auc_single_class_is_none():
    y = np.array([0, 0, 0, 0])
    p = np.array([0.1, 0.2, 0.3, 0.4])
    assert sh.grouped_auc(y, p) is None


def test_grouped_auc_random_is_near_half():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, size=2000)
    p = rng.random(2000)  # independent of y
    auc = sh.grouped_auc(y, p)
    assert 0.45 < auc < 0.55


# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------
def test_psi_identical_distributions_is_near_zero():
    rng = np.random.default_rng(1)
    expected = rng.random(5000)
    actual = expected.copy()
    assert sh.psi(expected, actual, bins=10) == pytest.approx(0.0, abs=1e-9)


def test_psi_shifted_distribution_is_large():
    rng = np.random.default_rng(2)
    expected = rng.random(5000)          # uniform [0, 1)
    actual = rng.random(5000) * 0.2      # uniform [0, 0.2) -- big shift
    value = sh.psi(expected, actual, bins=10)
    # conventional bank model-risk reading: > 0.25 is "major shift"
    assert value > 0.25


def test_psi_moderate_shift_is_between_thresholds():
    rng = np.random.default_rng(3)
    expected = rng.normal(0, 1, 5000)
    actual = rng.normal(0.15, 1, 5000)   # small mean shift
    value = sh.psi(expected, actual, bins=10)
    assert 0.0 < value < 0.25


def test_psi_empty_inputs_are_zero():
    assert sh.psi(np.array([]), np.array([1.0, 2.0])) == 0.0
    assert sh.psi(np.array([1.0, 2.0]), np.array([])) == 0.0


# ---------------------------------------------------------------------------
# CSI (categorical)
# ---------------------------------------------------------------------------
def test_csi_categorical_identical_is_near_zero():
    expected = pd.Series(["A", "B", "A", "C"] * 100)
    actual = expected.copy()
    assert sh.csi_categorical(expected, actual) == pytest.approx(0.0, abs=1e-6)


def test_csi_categorical_disjoint_levels_is_large():
    expected = pd.Series(["A"] * 500)
    actual = pd.Series(["B"] * 500)
    value = sh.csi_categorical(expected, actual)
    assert value > 1.0  # both levels flip from ~all-mass to ~no-mass


# ---------------------------------------------------------------------------
# bootstrap_ci — group-level, not row-level
# ---------------------------------------------------------------------------
def test_bootstrap_ci_constant_statistic_collapses():
    df = pd.DataFrame({"account_id": [f"a{i}" for i in range(50)], "x": [1.0] * 50})
    lo, hi = sh.bootstrap_ci(df, lambda d: 3.0, n=50, seed=7)
    assert lo == pytest.approx(3.0)
    assert hi == pytest.approx(3.0)


def test_bootstrap_ci_resamples_whole_groups_not_rows():
    """A row-level bootstrap on this data would report a near-zero-width CI
    around the mean (the sign pattern averages out over ~1000 independent
    rows); a GROUP-level bootstrap, resampling whole accounts, must instead
    report a much wider interval, because each account's 20 rows share one
    sign and there are only 50 independent draws.
    """
    rows = []
    rng = np.random.default_rng(5)
    for i in range(50):
        sign = 1.0 if rng.random() < 0.5 else -1.0
        for _ in range(20):
            rows.append({"account_id": f"a{i}", "x": sign + rng.normal(0, 0.01)})
    df = pd.DataFrame(rows)

    lo, hi = sh.bootstrap_ci(df, lambda d: float(d["x"].mean()), n=300, seed=7)
    assert (hi - lo) > 0.3  # wide: the group structure is respected


def test_bootstrap_ci_empty_frame_is_zero_zero():
    assert sh.bootstrap_ci(pd.DataFrame(columns=["account_id", "x"]), lambda d: 1.0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# OOT cut month
# ---------------------------------------------------------------------------
def test_oot_cut_month_48_12():
    assert sh.oot_cut_month(48, 12) == 24


def test_oot_cut_month_36_12():
    assert sh.oot_cut_month(36, 12) == 12


def test_oot_cut_month_never_negative():
    assert sh.oot_cut_month(10, 12) == 0


# ---------------------------------------------------------------------------
# RAG bucket thresholds (export_demo.py's RED_THR=0.40, AMBER_THR=0.04)
# ---------------------------------------------------------------------------
def test_rag_bucket_thresholds():
    p = np.array([0.01, 0.04, 0.39, 0.40, 0.99])
    buckets = sh.rag_bucket(p)
    assert list(buckets) == ["green", "amber", "amber", "red", "red"]


# ---------------------------------------------------------------------------
# DR-03 slippage ratio (runner 01) — hand-computed on a tiny accounts table
# ---------------------------------------------------------------------------
def test_slippage_windows_48_months():
    windows = holdout01._slippage_windows(48, horizon=12)
    assert windows == [(0, 11), (12, 23), (24, 35), (36, 47)]


def test_slippage_ratio_hand_computed():
    # 10 accounts. Window [0,11]: all 10 standard at start (npa_month NaN or >=0).
    # 3 fresh NPAs land in [0,11] -> ratio = 3/10 = 0.30
    accounts = pd.DataFrame({
        "account_id": [f"a{i}" for i in range(10)],
        "npa_month": [2, 5, 9, -1, -1, -1, -1, -1, -1, -1],
    })
    ratio = holdout01._slippage_ratio(accounts, months=12)
    assert ratio == pytest.approx(0.30)


def test_slippage_ratio_excludes_already_npa_accounts_from_denominator():
    # 4 accounts; one is already NPA before window 2 starts (npa_month=1, so it
    # is NOT standard at the start of window [12,23]) -> excluded from BOTH
    # numerator and denominator of window 2.
    accounts = pd.DataFrame({
        "account_id": ["a0", "a1", "a2", "a3"],
        "npa_month": [1, 15, -1, -1],
    })
    windows = holdout01._slippage_windows(24, horizon=12)
    assert windows == [(0, 11), (12, 23)]
    npa = accounts["npa_month"].to_numpy(dtype=float)
    npa = np.where(npa < 0, np.nan, npa)
    s, e = windows[1]
    standard = np.isnan(npa) | (npa >= s)
    assert standard.tolist() == [False, True, True, True]  # a0 excluded (already NPA)
    fresh = (~np.isnan(npa)) & (npa >= s) & (npa <= e)
    assert fresh.tolist() == [False, True, False, False]
    # ratio for window 2 alone = 1/3
    assert fresh.sum() / standard.sum() == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# cut_series — ticket_band / vintage_band binning
# ---------------------------------------------------------------------------
def _fake_cut(id_, source_column, levels=None):
    from validation.criteria import Cut
    return Cut(id=id_, source_column=source_column, levels=levels)


def test_cut_series_vintage_band_edges():
    df = pd.DataFrame({"vintage_months": [0, 11, 12, 17, 18, 29, 30, 47, 48, 200]})
    cut = _fake_cut("vintage_band", "vintage_months")
    labels = sh.cut_series(cut, df)
    assert list(labels) == [
        "[0,12)", "[0,12)", "[12,18)", "[12,18)", "[18,30)",
        "[18,30)", "[30,48)", "[30,48)", "[48,inf)", "[48,inf)",
    ]


def test_cut_series_ticket_band_is_five_quantile_groups():
    df = pd.DataFrame({"log_sanctioned": np.log(np.linspace(1e5, 1e7, 500))})
    cut = _fake_cut("ticket_band", "sanctioned_amount")
    labels = sh.cut_series(cut, df)
    assert labels.nunique() == 5
    counts = labels.value_counts()
    assert counts.max() - counts.min() <= 1  # quintiles, near-equal cell sizes


def test_cut_series_resolves_id_before_source_column():
    # "sector" is a real column matching the cut id directly.
    df = pd.DataFrame({"sector": ["Retail", "Trading"], "region": ["North", "South"]})
    cut = _fake_cut("sector", "sector")
    assert list(sh.cut_series(cut, df)) == ["Retail", "Trading"]


def test_cut_series_falls_back_to_source_column_for_geography():
    # "geography" is not a column; the panel's is "region" (criteria.yaml's own note).
    df = pd.DataFrame({"region": ["North", "South"]})
    cut = _fake_cut("geography", "region")
    assert list(sh.cut_series(cut, df)) == ["North", "South"]

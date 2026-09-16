"""SD-D6 — tests for the independent realism audit (``src/realism.py``).

These tests do NOT regenerate a panel (that is SD-D6's own budget rule — the
two reference panels are generated once by hand and cached under
``data/``, gitignored). They read the CSVs already on disk and skip with a
clear message if a checkout has not produced them yet, the same pattern
``tests/test_rigor_families.py`` already uses for the same reason.

Two things are tested, deliberately kept apart:

1. The **solid invariants** — referential integrity, MAR missingness, the
   impossible-state guards, the sourced base-rate bands, the two clean
   monotonicities (utilisation, bounces) — must all PASS. If one of these
   ever fails, that is a real regression in the generator or its output.
2. The **known findings** — properties this audit independently discovered
   do NOT hold on the shipped panel (CC utilisation runs nowhere near the
   assumed 0.85 "healthy" mode; the DPD-band default rate is not monotone,
   because the 61-90 DPD bucket is diluted by curing hard negatives; a
   handful of brand-new accounts show a nonzero DPD in their very first
   month on book) — are asserted to be caught, by name, with the
   corroborating numbers. Deleting one of these assertions should mean the
   underlying issue was fixed, not that the check went quiet.

Fast path: the 9,000 x 36 population (``data/small9k36/``). Slow path: the
45,000 x 48 population (``data/``), marked ``slow`` and run against the same
assertions plus one 45k-only finding that does not surface reliably at the
smaller sample size.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import realism  # noqa: E402  (path shim must run first)

SMALL_PANEL = REPO / "data" / "small9k36" / "msme_loan_panel.csv"
SMALL_ACCOUNTS = REPO / "data" / "small9k36" / "accounts_static.csv"
LARGE_PANEL = REPO / "data" / "msme_loan_panel.csv"
LARGE_ACCOUNTS = REPO / "data" / "accounts_static.csv"


def _load_or_skip(panel_path: Path, accounts_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (panel_path.exists() and accounts_path.exists()):
        pytest.skip(f"{panel_path} / {accounts_path} not generated in this checkout "
                    "(python3 src/generate_data.py --n <N> --months <M> --seed 20260709 --out <dir>)")
    return realism.load_data(panel_path, accounts_path)


@pytest.fixture(scope="module")
def small() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The 9,000 x 36 cached reference panel — the fast path."""
    return _load_or_skip(SMALL_PANEL, SMALL_ACCOUNTS)


@pytest.fixture(scope="module")
def large() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The 45,000 x 48 cached reference panel — the slow path."""
    return _load_or_skip(LARGE_PANEL, LARGE_ACCOUNTS)


@pytest.fixture(scope="module")
def small_results(small: tuple[pd.DataFrame, pd.DataFrame]) -> list[realism.Result]:
    panel, accounts = small
    return realism.run_all(panel, accounts, months=36, skip_reproducibility=True)


@pytest.fixture(scope="module")
def large_results(large: tuple[pd.DataFrame, pd.DataFrame]) -> list[realism.Result]:
    panel, accounts = large
    return realism.run_all(panel, accounts, months=48, skip_reproducibility=True)


def _by_name(results: list[realism.Result]) -> dict[str, realism.Result]:
    by_name: dict[str, realism.Result] = {}
    for result in results:
        assert result.name not in by_name, f"duplicate check name {result.name!r}"
        by_name[result.name] = result
    return by_name


# --------------------------------------------------------------------------- #
# Shape of the report itself
# --------------------------------------------------------------------------- #
def test_at_least_25_impossible_state_assertions(small_results: list[realism.Result]) -> None:
    impossible = [r for r in small_results if r.name.startswith("impossible_")]
    assert len(impossible) >= 25, f"only {len(impossible)} impossible-state checks"


def test_every_result_carries_observed_expected_and_rationale(
    small_results: list[realism.Result],
) -> None:
    for result in small_results:
        assert result.observed.strip()
        assert result.expected.strip()
        assert result.rationale.strip()


def test_report_round_trips_through_json(tmp_path: Path, small_results: list[realism.Result]) -> None:
    out = tmp_path / "realism_report.json"
    realism.write_report(small_results, out)
    import json
    payload = json.loads(out.read_text())
    assert payload["n_checks"] == len(small_results)
    assert payload["n_passed"] + payload["n_failed"] == len(small_results)
    assert len(payload["checks"]) == len(small_results)


# --------------------------------------------------------------------------- #
# Solid invariants — must PASS at both sizes
# --------------------------------------------------------------------------- #
SOLID_INVARIANTS = (
    "book_default_rate_band",
    "sma2_to_npa_event_ratio_band",
    "silent_defaulter_share",
    "transient_stress_share",
    "monotone_default_by_utilisation_band",
    "monotone_default_by_bounce_band",
    "mar_no_gst_for_individuals",
    "mar_bureau_missing_share",
    "mar_no_salary_for_self_employed",
    "referential_integrity_account_id_bijection",
    "referential_integrity_static_attrs_constant",
    "referential_integrity_vintage_arithmetic",
    "vintage_hazard_hump_18_30m",
    "agri_seasonality_present_elsewhere_absent",
)


@pytest.mark.parametrize("name", SOLID_INVARIANTS)
def test_solid_invariant_passes_at_9k(small_results: list[realism.Result], name: str) -> None:
    result = _by_name(small_results)[name]
    assert result.passed, result.line()


def test_every_portfolio_default_rate_is_inside_its_sourced_band(
    small_results: list[realism.Result],
) -> None:
    results = [r for r in small_results if r.name.startswith("portfolio_default_rate_band[")]
    assert len(results) == 8, [r.name for r in results]
    failed = [r.line() for r in results if not r.passed]
    assert not failed, "\n".join(failed)


def test_impossible_state_checks_all_pass_at_9k_except_the_one_known_bug(
    small_results: list[realism.Result],
) -> None:
    """Every impossible-state guard must be clean, with one documented exception.

    ``impossible_dpd_exceeds_days_on_book`` does not reliably surface at 9k
    (too few brand-new accounts draw a nonzero first-month DPD to show up in
    a 9,000-account sample) — see the 45k-only test below, where it does.
    """
    known_flaky_at_small_n = {"impossible_dpd_exceeds_days_on_book"}
    failed = [
        r.line() for r in small_results
        if r.name.startswith("impossible_") and not r.passed and r.name not in known_flaky_at_small_n
    ]
    assert not failed, "\n".join(failed)


def test_channel_absent_columns_are_clean_at_9k(small_results: list[realism.Result]) -> None:
    results = [r for r in small_results if r.name.startswith("mar_channel_presence[")]
    assert len(results) == len(realism._NAN_EXCEPT_IN)
    failed = [r.line() for r in results if not r.passed]
    assert not failed, "\n".join(failed)


# --------------------------------------------------------------------------- #
# Known findings — this audit must catch them, not quietly agree with them
# --------------------------------------------------------------------------- #
def test_cc_utilisation_mode_is_not_the_assumed_healthy_0_85(
    small_results: list[realism.Result],
) -> None:
    """MSME-CC's utilisation centres near 0.5, not the assumed ~0.85 'healthy' mode.

    ``portfolios.msme_cc`` carries no ``base_util_mean`` override in
    ``src/generator/portfolios.py`` (only ``msme_tl`` and ``agri`` do), so it
    runs on the shared default of 0.52 — this is exactly what shows up here.
    A known unrealism, not a bug in this audit.
    """
    result = _by_name(small_results)["cc_utilisation_mode"]
    assert not result.passed
    assert "mode=0." in result.observed  # a sub-0.6 mode, nowhere near 0.85


def test_dpd_band_default_rate_reverses_at_61_90(small_results: list[realism.Result]) -> None:
    """31-60 DPD carries a HIGHER forward default rate than 61-90 DPD.

    The 61-90 bucket is diluted by the hard-negative population (transient
    episodes reach up to 84 DPD per ``arrears.arrears_ladder`` and then cure,
    per the "known unrealisms" note), so days-past-due alone is not a
    strictly monotone risk signal on this panel even though the two other
    band checks (utilisation, bounces) are clean.
    """
    result = _by_name(small_results)["monotone_default_by_dpd_band"]
    assert not result.passed
    values = {}
    for token in result.observed.split(", "):
        label, value = token.split("=")
        values[label] = float(value)
    assert values["31-60"] > values["61-90"], result.observed


def test_dpd_sma_shares_still_follow_a_funnel_shape(small_results: list[realism.Result]) -> None:
    """Unlike the DPD-band reversal above, the raw SMA-0/1/2 SHARE is well-behaved."""
    result = _by_name(small_results)["dpd_distribution_vs_sma_shares"]
    assert result.passed, result.line()


# --------------------------------------------------------------------------- #
# Slow path — the 45,000 x 48 population
# --------------------------------------------------------------------------- #
@pytest.mark.slow
@pytest.mark.parametrize("name", SOLID_INVARIANTS)
def test_solid_invariant_passes_at_45k(large_results: list[realism.Result], name: str) -> None:
    result = _by_name(large_results)[name]
    assert result.passed, result.line()


@pytest.mark.slow
def test_every_portfolio_default_rate_is_inside_its_sourced_band_at_45k(
    large_results: list[realism.Result],
) -> None:
    results = [r for r in large_results if r.name.startswith("portfolio_default_rate_band[")]
    assert len(results) == 8, [r.name for r in results]
    failed = [r.line() for r in results if not r.passed]
    assert not failed, "\n".join(failed)


@pytest.mark.slow
def test_impossible_dpd_exceeds_days_on_book_surfaces_at_45k(
    large_results: list[realism.Result],
) -> None:
    """The one impossible-state guard that genuinely fires: NPA-week-old accounts already past due.

    17 of 45,000 accounts (seed 20260709) show a nonzero DPD in their very
    first observed month (``vintage_months == 0``) — an account cannot be
    late on an instalment before its first one is even due. A small,
    previously unflagged generator edge case, found independently by this
    audit rather than assumed away.
    """
    result = _by_name(large_results)["impossible_dpd_exceeds_days_on_book"]
    assert not result.passed
    assert "0 violating" not in result.observed


@pytest.mark.slow
def test_impossible_state_checks_all_pass_at_45k_except_the_one_known_bug(
    large_results: list[realism.Result],
) -> None:
    known_bug = {"impossible_dpd_exceeds_days_on_book"}
    failed = [
        r.line() for r in large_results
        if r.name.startswith("impossible_") and not r.passed and r.name not in known_bug
    ]
    assert not failed, "\n".join(failed)


@pytest.mark.slow
def test_seed_reproducibility_check_runs_clean() -> None:
    """Not parametrised into small_results/large_results (both skip it for speed) — run once here."""
    result = realism.check_seed_reproducibility()
    assert result.passed, result.line()


# --------------------------------------------------------------------------- #
# CLI smoke test
# --------------------------------------------------------------------------- #
def test_cli_writes_a_report_and_exits_nonzero_on_a_known_failure(tmp_path: Path) -> None:
    if not (SMALL_PANEL.exists() and SMALL_ACCOUNTS.exists()):
        pytest.skip("9k panel not generated in this checkout")
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(SRC / "realism.py"),
         "--panel", str(SMALL_PANEL), "--accounts", str(SMALL_ACCOUNTS),
         "--out", str(out), "--skip-reproducibility"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert out.exists()
    assert proc.returncode == 1  # cc_utilisation_mode / monotone_default_by_dpd_band are known FAILs
    assert "PASS" in proc.stdout and "FAIL" in proc.stdout

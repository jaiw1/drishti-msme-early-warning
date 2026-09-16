"""SD-D6 — tests for the independent realism audit (``src/realism.py``).

These tests do NOT regenerate a panel (that is SD-D6's own budget rule — the
two reference panels are generated once by hand and cached under
``data/``, gitignored). They read the CSVs already on disk and skip with a
clear message if a checkout has not produced them yet, the same pattern
``tests/test_rigor_families.py`` already uses for the same reason.

The **solid invariants** — referential integrity, MAR missingness, the
impossible-state guards, the sourced base-rate bands, and (as of SD-D8) every
one of the checks this audit's own report used to catch as genuine findings —
must all PASS. If one of these ever fails, that is a real regression in the
generator or its output.

SD-D8 closed the three FAILs SD-D6's original audit reported at both sizes:
`cc_utilisation_mode` (MSME-CC's utilisation baseline now sources
~0.85 — ``portfolios.msme_cc``'s ``utilisation.base_mean``), and
`monotone_default_by_dpd_band` / `impossible_dpd_exceeds_days_on_book` (the
transient arrears ladder is capped at 58 DPD instead of 84, and the final
`dpd` is clipped to ``vintage_months * 30`` in
``generator.channels.simulate_channels``). What were dedicated "known
finding" tests below are now ordinary solid-invariant assertions — the
history is kept in ``DATA_CARD.md``'s "known unrealisms", not here.

Fast path: the 9,000 x 36 population (``data/small9k36/``). Slow path: the
45,000 x 48 population (``data/``), marked ``slow`` and run against the same
assertions.
"""

from __future__ import annotations

import json
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
    "cc_utilisation_mode",
    "monotone_default_by_dpd_band",
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


def test_impossible_state_checks_all_pass_at_9k(
    small_results: list[realism.Result],
) -> None:
    """Every impossible-state guard must be clean.

    SD-D8: ``impossible_dpd_exceeds_days_on_book`` used to be a documented
    exception here — 12 of 17 violating rows at 45k were already delinquent
    at ``vintage_months == 0``, too rare to reliably surface in a 9,000-
    account sample, but genuinely present. `generator.channels.
    simulate_channels` now clips the final ``dpd`` to
    ``vintage_months * 30`` (months on book), which makes the guard clean at
    every population size, not just less likely to trip.
    """
    failed = [r.line() for r in small_results if r.name.startswith("impossible_") and not r.passed]
    assert not failed, "\n".join(failed)


def test_channel_absent_columns_are_clean_at_9k(small_results: list[realism.Result]) -> None:
    results = [r for r in small_results if r.name.startswith("mar_channel_presence[")]
    assert len(results) == len(realism._NAN_EXCEPT_IN)
    failed = [r.line() for r in results if not r.passed]
    assert not failed, "\n".join(failed)


# --------------------------------------------------------------------------- #
# SD-D8 fixes — these used to be dedicated "known finding" tests, asserting
# NOT result.passed. Deleting that inversion (rather than deleting the test)
# is the point: a future regression on either fix must fail here again.
# --------------------------------------------------------------------------- #
def test_cc_utilisation_mode_is_now_the_assumed_healthy_0_85(
    small_results: list[realism.Result],
) -> None:
    """MSME-CC's utilisation centres near the sourced ~0.85 'healthy' mode.

    ``portfolios.msme_cc``'s ``base_util_mean`` now sources
    ``utilisation.base_mean`` (~0.85) from ``sources.yaml`` instead of
    inheriting the shared 0.52 default — see the "SD-D8" note on
    ``_SHAPE_OVERRIDES["msme_cc"]`` in ``src/generator/portfolios.py`` for
    the widened ``util_bounds`` that keeps this a real mode and not a clip
    artefact.
    """
    result = _by_name(small_results)["cc_utilisation_mode"]
    assert result.passed, result.line()


def test_dpd_band_default_rate_no_longer_reverses_at_61_90(
    small_results: list[realism.Result],
) -> None:
    """31-60 DPD no longer carries a HIGHER forward default rate than 61-90 DPD.

    ``transient.arrears_ladder`` is capped at 58 DPD (was 71/84), so a cured
    hard-negative episode no longer dilutes the 61-90 (SMA-2) bucket with
    never-defaulting rows — days-past-due is a strictly non-decreasing risk
    signal again, same as the utilisation and bounce bands.
    """
    result = _by_name(small_results)["monotone_default_by_dpd_band"]
    assert result.passed, result.line()
    values = {}
    for token in result.observed.split(", "):
        label, value = token.split("=")
        values[label] = float(value)
    assert values["31-60"] <= values["61-90"], result.observed


def test_dpd_sma_shares_still_follow_a_funnel_shape(small_results: list[realism.Result]) -> None:
    """The raw SMA-0/1/2 SHARE is well-behaved, as it always was."""
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
def test_impossible_dpd_exceeds_days_on_book_is_clean_at_45k(
    large_results: list[realism.Result],
) -> None:
    """The one impossible-state guard that used to genuinely fire, at 45k specifically.

    17 of 45,000 accounts (seed 20260709) used to show a nonzero DPD in
    their very first observed month (``vintage_months == 0``) — an account
    cannot be late on an instalment before its first one is even due. SD-D8
    clips the final ``dpd`` to ``vintage_months * 30`` in
    ``generator.channels.simulate_channels``, which is a population-wide fix
    (not size-dependent), so this must read clean at 45k too, not just less
    likely to trip.
    """
    result = _by_name(large_results)["impossible_dpd_exceeds_days_on_book"]
    assert result.passed, result.line()
    assert "0 violating" in result.observed


@pytest.mark.slow
def test_impossible_state_checks_all_pass_at_45k(
    large_results: list[realism.Result],
) -> None:
    failed = [r.line() for r in large_results if r.name.startswith("impossible_") and not r.passed]
    assert not failed, "\n".join(failed)


@pytest.mark.slow
def test_seed_reproducibility_check_runs_clean() -> None:
    """Not parametrised into small_results/large_results (both skip it for speed) — run once here."""
    result = realism.check_seed_reproducibility()
    assert result.passed, result.line()


# --------------------------------------------------------------------------- #
# CLI smoke test
# --------------------------------------------------------------------------- #
def test_cli_writes_a_report_and_exits_zero_when_everything_passes(tmp_path: Path) -> None:
    """SD-D8: the shipped 9k panel is clean end to end, so the CLI must exit 0.

    Before SD-D8 this same panel tripped ``cc_utilisation_mode`` and
    ``monotone_default_by_dpd_band`` by design, and the CLI's nonzero-exit
    contract was exercised here as a side effect. That contract is now
    tested directly (below, against a synthetic failing report) instead of
    depending on the shipped panel staying broken.
    """
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
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert "PASS" in proc.stdout and "0 failed" in proc.stdout


def test_main_exits_nonzero_when_a_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exit-code contract, tested directly against a synthetic failing report.

    Independent of whether any real panel currently fails anything: swaps in
    a fake ``run_all`` with one failing ``Result`` and asserts ``main()``
    still exits 1 and still writes the report.
    """
    fake_results = [
        realism.Result("synthetic_check", True, "ok", "ok", "always passes"),
        realism.Result("synthetic_broken_check", False, "bad", "good", "deliberately fails"),
    ]
    monkeypatch.setattr(realism, "run_all", lambda *a, **k: fake_results)
    monkeypatch.setattr(
        realism, "load_data", lambda *a, **k: (pd.DataFrame({"month_idx": [0]}), pd.DataFrame())
    )
    out = tmp_path / "report.json"
    with pytest.raises(SystemExit) as excinfo:
        realism.main(["--panel", "unused.csv", "--accounts", "unused.csv", "--out", str(out)])
    assert excinfo.value.code == 1
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["n_failed"] == 1

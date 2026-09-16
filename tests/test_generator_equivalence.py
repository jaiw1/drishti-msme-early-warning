"""The generator must still be a drop-in for the row-by-row July 2026 simulator.

``src/generator/`` replaced a per-account, per-month Python loop with
per-portfolio ``(N, M)`` numpy arrays, and SD-D2/SD-D3 then grew the book from
two MSME portfolios to eight and added the columns each new product is observed
through.  Neither change is allowed to move the MSME book, so this suite
regenerates **only** ``msme_cc`` and ``msme_tl`` and holds them against the
July fingerprint:

(a) reproducible — one seed, one CSV;
(b) schema-compatible — every July column survives, with the same name, the
    same relative order and the same dtype after a CSV round trip.  New columns
    are added, never substituted, and the labels stay last;
(c) distributionally equivalent on every key column, with the default rate
    within 0.3 pp and the median first-warning lead within 1 month;
(d) still ordered — for defaulters the cash-flow dip precedes the utilisation
    rise, which precedes the bounces, which precede days-past-due.

The reference in ``tests/legacy_reference.json`` was fingerprinted from the
old simulator's ``data/msme_loan_panel.csv`` (see ``tests/_summary.py``), so
it survives the panel being regenerated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from _summary import CATEGORICAL_COLUMNS, NUMERIC_COLUMNS, QUANTILES, summarise
from generator import GeneratorConfig, generate
from generator.build import LEGACY_PANEL_COLUMNS, PANEL_COLUMNS, write
from generator.portfolios import MSME_KEYS

#: the vectorised maths must not silently overflow or divide by zero
pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

REFERENCE_PATH = Path(__file__).with_name("legacy_reference.json")

#: a statistic matches if it is within 5% of the reference, 8% of that
#: column's spread, or 1e-4 absolute — whichever is loosest.  Calibrated
#: against the seed-to-seed spread of the new generator at 9,000 accounts,
#: where every reference statistic sits inside ~2 sigma.
REL_TOLERANCE = 0.05
SPREAD_TOLERANCE = 0.08
ABS_FLOOR = 1e-4

#: category shares are compared in percentage points
SHARE_TOLERANCE_PP = 2.0

#: the two headline contracts, pinned by the task
DEFAULT_RATE_TOLERANCE_PP = 0.3
LEAD_TOLERANCE_MONTHS = 1.0


@pytest.fixture(scope="module")
def reference() -> dict:
    """The old simulator's fingerprint."""
    with REFERENCE_PATH.open() as handle:
        return json.load(handle)


#: the July 2026 book, regenerated on its own out of the eight-portfolio registry
MSME_ONLY = GeneratorConfig(portfolio_keys=MSME_KEYS)


@pytest.fixture(scope="module")
def msme_panel(tmp_path_factory: pytest.TempPathFactory) -> pd.DataFrame:
    """The two MSME portfolios, generated alone and round-tripped through CSV."""
    frame, accounts = generate(MSME_ONLY)
    outdir = tmp_path_factory.mktemp("panel")
    write(frame, accounts, outdir)
    return pd.read_csv(outdir / "msme_loan_panel.csv")


@pytest.fixture(scope="module")
def fingerprint(msme_panel: pd.DataFrame) -> dict:
    """The MSME book's fingerprint, computed by the same code as the reference."""
    return summarise(msme_panel)


# --------------------------------------------------------------------------- #
# (a) reproducibility
# --------------------------------------------------------------------------- #
def test_same_seed_gives_identical_csv(tmp_path: Path) -> None:
    """One seed, one CSV — byte for byte."""
    config = GeneratorConfig(n_accounts=1500)
    written = []
    for run in ("first", "second"):
        outdir = tmp_path / run
        write(*generate(config), outdir)
        written.append((outdir / "msme_loan_panel.csv").read_bytes())
        assert (outdir / "accounts_static.csv").exists()
    assert written[0] == written[1]


def test_different_seed_gives_different_panel() -> None:
    """The seed is actually wired through to every stage."""
    first, _ = generate(GeneratorConfig(n_accounts=1500, seed=1))
    second, _ = generate(GeneratorConfig(n_accounts=1500, seed=2))
    assert not first.equals(second)


def test_config_is_honoured() -> None:
    """``--n`` and ``--months`` change the population, not the contract."""
    frame, accounts = generate(GeneratorConfig(n_accounts=500, months=24))
    assert len(accounts) == 500
    assert frame.month_idx.max() <= 23
    assert list(frame.columns) == list(PANEL_COLUMNS)
    # labelable requires a full 12-month forward window inside 24 months
    assert frame.loc[frame.labelable == 1, "month_idx"].max() == 11


# --------------------------------------------------------------------------- #
# (b) schema equality with the old CSV
# --------------------------------------------------------------------------- #
def test_every_old_column_survives(fingerprint: dict, reference: dict) -> None:
    """Every July column is still there, under the same name.

    Eight portfolios need more columns, not different ones: ``export_demo.py``
    and ``rigor.py`` address the panel by name, so a rename would be a silent
    break and a reorder would be a noisy one.
    """
    columns = fingerprint["columns"]
    assert set(reference["columns"]) <= set(columns)
    assert [c for c in columns if c in reference["columns"]] == reference["columns"]
    assert columns[-3:] == ["default_within_12m", "labelable", "months_to_npa"]


def test_new_columns_are_additions(fingerprint: dict, reference: dict) -> None:
    """The additions are SD-D2's population block and SD-D3's channels."""
    added = [c for c in fingerprint["columns"] if c not in reference["columns"]]
    assert added, "SD-D2/SD-D3 added no columns"
    assert set(added) <= set(PANEL_COLUMNS) - set(LEGACY_PANEL_COLUMNS)
    for expected in ("portfolio", "constitution", "secured", "collection_ratio",
                     "balance", "bureau_score"):
        assert expected in added, expected


def test_dtypes_match_the_old_csv(fingerprint: dict, reference: dict) -> None:
    """After a CSV round trip, every July column reads back as it used to."""
    for column, dtype in reference["dtypes"].items():
        assert fingerprint["dtypes"][column] == dtype, column


def test_population_shape_matches(fingerprint: dict, reference: dict) -> None:
    assert fingerprint["n_accounts"] == reference["n_accounts"]
    assert abs(fingerprint["n_rows"] - reference["n_rows"]) / reference["n_rows"] < 0.02
    assert abs(fingerprint["labelable_share"] - reference["labelable_share"]) < 0.005


# --------------------------------------------------------------------------- #
# (c) distributional equivalence
# --------------------------------------------------------------------------- #
def _tolerance(value: float, spread: float) -> float:
    return max(REL_TOLERANCE * abs(value), SPREAD_TOLERANCE * abs(spread), ABS_FLOOR)


@pytest.mark.parametrize("column", NUMERIC_COLUMNS)
def test_numeric_distribution_matches(column: str, fingerprint: dict, reference: dict) -> None:
    """Mean, standard deviation and five quantiles, column by column."""
    old, new = reference["numeric"][column], fingerprint["numeric"][column]
    spread = old["std"]
    for statistic in ("mean", "std"):
        tolerance = _tolerance(old[statistic], spread)
        assert abs(new[statistic] - old[statistic]) <= tolerance, (
            f"{column}.{statistic}: {new[statistic]:.6g} vs {old[statistic]:.6g} "
            f"(tolerance {tolerance:.6g})"
        )
    for quantile, old_q, new_q in zip(QUANTILES, old["quantiles"], new["quantiles"]):
        tolerance = _tolerance(old_q, spread)
        assert abs(new_q - old_q) <= tolerance, (
            f"{column} q{quantile}: {new_q:.6g} vs {old_q:.6g} (tolerance {tolerance:.6g})"
        )


@pytest.mark.parametrize("column", CATEGORICAL_COLUMNS)
def test_category_shares_match(column: str, fingerprint: dict, reference: dict) -> None:
    old, new = reference["shares"][column], fingerprint["shares"][column]
    assert set(new) == set(old)
    for value, share in old.items():
        delta_pp = abs(new[value] - share) * 100
        assert delta_pp <= SHARE_TOLERANCE_PP, f"{column}={value}: {delta_pp:.2f} pp"


def test_default_rate_within_third_of_a_point(fingerprint: dict, reference: dict) -> None:
    """The label prevalence is the number every downstream metric hangs off."""
    delta_pp = abs(fingerprint["default_rate"] - reference["default_rate"]) * 100
    assert delta_pp <= DEFAULT_RATE_TOLERANCE_PP, f"{delta_pp:.3f} pp"


def test_first_warning_lead_within_one_month(fingerprint: dict, reference: dict) -> None:
    """The lead time is DRISHTi's headline claim — it must not drift."""
    old = reference["channel_leads"]["cash_flow"]
    new = fingerprint["channel_leads"]["cash_flow"]
    assert abs(new - old) <= LEAD_TOLERANCE_MONTHS, f"{new} vs {old} months"


# --------------------------------------------------------------------------- #
# (d) the ordered-deterioration property
# --------------------------------------------------------------------------- #
def test_deterioration_is_ordered(fingerprint: dict) -> None:
    """Cash-flow dips first, DPD moves last — on the median defaulter.

    This is the whole early-warning thesis: if the order inverted, the model
    would be reading arrears rather than predicting them.
    """
    leads = fingerprint["channel_leads"]
    assert leads["cash_flow"] >= leads["utilisation"] > leads["bounces"] > leads["dpd"] > 0, leads


def test_no_row_is_already_npa(msme_panel: pd.DataFrame) -> None:
    """Only accounts that still look STANDARD today are scoreable."""
    assert msme_panel.dpd.max() < 90
    assert (msme_panel.loc[msme_panel.months_to_npa >= 0, "months_to_npa"] >= 1).all()


def test_label_matches_its_definition(msme_panel: pd.DataFrame) -> None:
    """``default_within_12m`` is exactly ``1 <= months_to_npa <= 12``."""
    expected = msme_panel.months_to_npa.between(1, 12).astype(int)
    assert msme_panel.default_within_12m.equals(expected)


# --------------------------------------------------------------------------- #
# the extension point SD-D2/SD-D3 will use
# --------------------------------------------------------------------------- #
def test_portfolio_shares_are_honoured(msme_panel: pd.DataFrame) -> None:
    """Restricting the registry renormalises the shares over what is left.

    The two MSME portfolios hold 10.1% and 8.3% of the eight-portfolio book;
    generated alone they must come back at 55/45, the cash-credit / term-loan
    split the July build used and ``book.msme_cc_share_of_msme`` records.
    """
    from generator.portfolios import portfolio_mix, registry as select

    portfolios, shares = portfolio_mix(select(MSME_KEYS))
    observed = msme_panel.drop_duplicates("account_id").portfolio.value_counts(
        normalize=True
    )
    for portfolio, share in zip(portfolios, shares):
        assert abs(observed[portfolio.code] - share) < 0.02, portfolio.key
    assert dict(zip(MSME_KEYS, shares)) == pytest.approx(
        {"msme_cc": 0.55, "msme_tl": 0.45}, abs=0.01
    )


def test_absent_channels_are_blanked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A portfolio can declare a channel it structurally cannot observe.

    The registry uses this for real now — a salaried borrower files no GST
    return — but the hook itself is what makes one wide panel legal across
    heterogeneous products, so it keeps its own test: register a portfolio that
    differs from an existing one *only* by dropping a channel, and prove that
    exactly its rows go NaN and nobody else's do.
    """
    from dataclasses import replace

    from generator import portfolios as registry

    donor = registry.PORTFOLIOS["msme_tl"]
    salaried = replace(
        donor,
        key="salaried",
        code="Salaried",
        label="Synthetic no-GST portfolio",
        channels=tuple(c for c in donor.channels if c != "gst"),
    )
    assert salaried.absent_channels == donor.absent_channels | {"gst"}
    monkeypatch.setitem(registry.PORTFOLIOS, "salaried", salaried)

    frame, _ = generate(GeneratorConfig(
        n_accounts=900, portfolio_keys=MSME_KEYS + ("salaried",)
    ))
    blanked = frame.portfolio == "Salaried"
    assert blanked.any()
    for column in ("gst_sales", "sales_trend_3m"):
        assert frame.loc[blanked, column].isna().all()
        assert frame.loc[~blanked, column].notna().all()

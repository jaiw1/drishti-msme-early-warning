"""Panel assembly and CLI — the entry point of the generator.

Driven through the pipeline's wrapper, which forwards every argument::

    python3 src/generate_data.py                                  # 9,000 x 36
    python3 src/generate_data.py --seed 7 --n 45000 --months 48 --out data

Pipeline
--------
1. :func:`generator.latent.draw_population` draws the whole book — each
   portfolio's static attributes from its own sourced distributions — and
   decides who defaults, when, and how steeply.
2. :func:`generator.latent.build_stress_path` expands that into the shared
   latent stress ``(N, M)``.
3. For each portfolio in the registry, the accounts belonging to it are
   simulated as their own ``(N_p, M)`` block by
   :func:`generator.channels.simulate_channels`, then scattered back into the
   full arrays by account index — so account ordering never depends on the
   registry, and adding a portfolio adds a block rather than changing one.
4. Trailing features are computed once over the full stack (the windows are
   per-account, so they are portfolio-agnostic).
5. :mod:`generator.labels` supplies the row filter and the forward label, and
   the kept cells are flattened into the long-format panel.

One wide panel, eight portfolios
--------------------------------
Every column exists for every row; a column a portfolio structurally cannot
observe is **NaN**, never zero.  A KCC farmer has no salary credit, a salaried
home-loan borrower files no GST return, a term loan has no drawing power.  That
distinction is load-bearing: LightGBM reads NaN as "not observed", the SD-D4
missingness work depends on zero meaning "observed, and it was zero", and the
bank-enrichment contract (``data/bank/SCHEMA.md``) says the same thing about
null columns in ``enriched.csv``.

Determinism
-----------
``--seed`` fully determines the output.  Each stage draws from its own
name-addressed stream (see :func:`generator.noise.stream`), so the same seed
gives byte-identical CSVs across runs, and adding a portfolio or a channel
leaves every other stream untouched.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .channels import (
    CHANNEL_COLUMNS,
    SHARED_COLUMNS,
    BlockInputs,
    Channels,
    draw_baselines,
    simulate_channels,
    trailing_features,
)
from . import sources
from .constitutions import SEGMENTS, files_gst, segment_codes
from .labels import (
    assert_base_rates,
    default_within_12m,
    labelable_rows,
    measure_base_rates,
    months_to_npa_column,
    sma2_within_6m,
    standard_rows,
)
from .latent import Population, build_stress_path, draw_population, state_levels
from .noise import statement_gaps, stream
from .portfolios import POPULATION, PORTFOLIOS, PopulationMix, Portfolio, registry

__all__ = [
    "ACCOUNT_COLUMNS",
    "LEGACY_PANEL_COLUMNS",
    "PANEL_COLUMNS",
    "GeneratorConfig",
    "generate",
    "main",
    "write",
]

#: the July 2026 build's column list, in its original order.  Every one of
#: these survives, with its name and its meaning, so the pipeline that consumes
#: the panel keeps working; the equivalence suite asserts their relative order
#: is unchanged.
LEGACY_PANEL_COLUMNS: tuple[str, ...] = (
    "account_id", "month_idx", "date",
    "sector", "region", "loan_type", "segment", "qualification", "promoter_age_group",
    "log_sanctioned", "business_age_years", "vintage_months",
    "dpd", "utilisation", "inflow", "gst_sales", "txn_count",
    "bounce", "minbal_breach", "adverse_remark",
    "dpd_max_6m", "times_late_6m", "bounces_6m", "minbal_breach_6m",
    "util_avg_3m", "util_max_6m", "months_over_90pct_util_6m",
    "inflow_trend_3m", "inflow_vs_6m_avg", "sales_trend_3m",
    "txn_drop_flag", "adverse_remark_6m",
    "default_within_12m", "labelable", "months_to_npa",
)

#: SD-D2's static borrower attributes.  ``portfolio`` carries the platform
#: contract's spelling (``MSME-CC``, not ``msme_cc``) — see
#: ``data/bank/SCHEMA.md`` and ``validation/criteria.yaml``.
POPULATION_COLUMNS: tuple[str, ...] = (
    "portfolio", "constitution", "state", "city_tier", "nic_group",
    "secured", "tenor_months", "interest_rate_pa",
)

#: SD-D3's per-portfolio channel columns, in channel declaration order
CHANNEL_PANEL_COLUMNS: tuple[str, ...] = tuple(
    column
    for channel, columns in CHANNEL_COLUMNS.items()
    for column in columns
    if column not in LEGACY_PANEL_COLUMNS
)

#: panel column order.  The legacy columns keep their relative order; the new
#: ones are inserted before the three label columns so the labels stay last.
#: ``sma2_within_6m`` (SD-D5) is inserted between the primary label and the
#: two bookkeeping columns, so the July columns keep their relative order and
#: every label still sits at the END of the panel — which is the contract
#: ``export_demo.py`` and ``rigor.py`` drop by name.
#: 🔴 BOTH OF THEM MUST ADD ``sma2_within_6m`` TO THEIR ``DROP`` LIST.  It is a
#: forward-looking label; left in, it trains the model on the answer.
_LABEL_COLUMNS: tuple[str, ...] = (
    "default_within_12m", "sma2_within_6m", "labelable", "months_to_npa",
)
#: SD-D8 — a bank-style bucketing of `vintage_months`, added as its own column
#: rather than folded into POPULATION_COLUMNS: it is DERIVED and dynamic (it
#: moves every month, like `vintage_months` itself), not a static attribute
#: drawn once at panel start. `vintage_months` drifts by construction under a
#: time-split OOT (it is account-age + elapsed months, so a later test window
#: is mechanically older than train) — this is DR-14's binding CSI feature.
#: Bucketing it the way a bank actually reads vintage — a relationship-age
#: band, not a raw month counter — is a legitimate modelling choice: see
#: DATA_CARD.md's "known unrealisms" and MODEL_CARD.md. `vintage_months`
#: itself stays in the panel (validation cuts use it); only the MODEL's own
#: feature set drops it in favour of `vintage_band` (`export_demo.py` /
#: `rigor.py` CAT/DROP).
VINTAGE_DERIVED_COLUMNS: tuple[str, ...] = ("vintage_band",)
#: bank-style relationship-age bands for `vintage_band`, in ascending order
VINTAGE_BANDS: tuple[str, ...] = ("0-6", "7-12", "13-18", "19-30", "31-48", "49+")
#: inclusive upper bound (months on book) of each band except the last
_VINTAGE_BAND_UPPER_BOUNDS: tuple[int, ...] = (6, 12, 18, 30, 48)
PANEL_COLUMNS: tuple[str, ...] = (
    tuple(c for c in LEGACY_PANEL_COLUMNS if c not in _LABEL_COLUMNS)
    + POPULATION_COLUMNS
    + VINTAGE_DERIVED_COLUMNS
    + SHARED_COLUMNS
    + CHANNEL_PANEL_COLUMNS
    + _LABEL_COLUMNS
)


def _vintage_band_codes(vintage_months: np.ndarray) -> np.ndarray:
    """Map months-on-book to indices into :data:`VINTAGE_BANDS`.

    Args:
        vintage_months: ``vintage_months_0 + month_idx``, any shape.

    Returns:
        Same-shape int codes, one per :data:`VINTAGE_BANDS` level.
    """
    codes = np.zeros(vintage_months.shape, dtype=np.int64)
    for bound in _VINTAGE_BAND_UPPER_BOUNDS:
        codes += (vintage_months > bound).astype(np.int64)
    return codes

#: accounts_static.csv column order
ACCOUNT_COLUMNS: tuple[str, ...] = (
    "account_id", "sector", "region", "loan_type", "segment", "qualification",
    "promoter_age_group", "sanctioned_amount", "business_age_years", "vintage_months_0",
    "is_defaulter", "npa_month", "severity", "onset",
    "portfolio", "constitution", "state", "city_tier", "nic_group", "secured",
    "tenor_months", "interest_rate_pa", "bureau_score_0", "risk_z",
    # SD-D4 ground truth: never features, and never in the panel.  They are
    # what the realism tests measure the generated book against.
    "silent_default", "transient_months", "transient_arrears", "statement_gap_months",
)

#: decimal places each float column is rounded to before writing.  Rounding is
#: not cosmetic here: at 45,000 x 48 it is most of the CSV's size.
#: ``inflow`` and ``gst_sales`` carry ONE decimal place rather than none, and
#: the reason is the writer, not the money.  They were float64 in the July 2026
#: build and the equivalence suite pins their round-tripped dtype; pyarrow
#: writes an integral float as ``11519`` where pandas wrote ``11519.0``, so
#: whole-rupee rounding would flip both columns to int64 on the way back in.
#: A tenth of a rupee is meaningless and costs 1% of the file; a silent dtype
#: change in two columns the pipeline reads by name is not meaningless.
_ROUNDING: dict[str, int] = {
    "dpd": 1, "utilisation": 4, "inflow": 1, "gst_sales": 1, "dpd_max_6m": 1,
    "util_avg_3m": 4, "util_max_6m": 4, "inflow_trend_3m": 4, "inflow_vs_6m_avg": 4,
    "sales_trend_3m": 4,
    "interest_rate_pa": 4,
    "outstanding": 0, "demanded_amount": 0, "collected_amount": 0,
    "collection_ratio": 4, "collection_ratio_3m": 4,
    "balance": 0, "min_balance_6m": 0, "bureau_score": 0,
    "drawing_power": 0, "salary_credit": 0, "salary_vs_6m_avg": 4, "salary_gap_6m": 0,
    "other_bank_emi": 0, "emi_burden_ratio": 4,
    "ltv": 4, "ltv_vs_schedule": 4,
    "rental_income": 0, "rental_vs_6m_avg": 4,
    "crop_receipt": 0, "crop_receipt_vs_norm": 4, "renewal_overdue_months": 0,
    "moratorium_active": 0, "months_since_moratorium_end": 0,
    "commute_spend": 0, "commute_vs_6m_avg": 4,
}

#: columns written as whole numbers: counts, flags and whole rupees.  A column
#: every portfolio observes gets ``int64``; one some portfolio cannot observe
#: gets pandas' nullable ``Int64``, so a missing cell stays empty in the CSV
#: instead of becoming a zero.  ``inflow`` and ``gst_sales`` are deliberately
#: NOT here: they were float64 in the July build and the equivalence suite
#: pins their round-tripped dtype.
_INTEGER_COLUMNS: tuple[str, ...] = (
    "txn_count", "times_late_6m", "bounces_6m", "minbal_breach_6m",
    "months_over_90pct_util_6m", "adverse_remark_6m",
    "bounce", "minbal_breach", "adverse_remark", "txn_drop_flag",
    "salary_gap_6m", "renewal_overdue_months",
    "moratorium_active", "months_since_moratorium_end",
    # whole rupees, and a bureau score is a whole number too
    "outstanding", "demanded_amount", "collected_amount", "balance",
    "min_balance_6m", "bureau_score", "drawing_power", "salary_credit",
    "other_bank_emi", "rental_income", "crop_receipt", "commute_spend",
)

#: the eight raw legacy channel stacks, and whether they are whole numbers
_RAW_STACKS: tuple[str, ...] = (
    "utilisation", "inflow", "gst_sales", "txn", "dpd",
    "bounce", "minbal_breach", "adverse_remark",
)


@dataclass(frozen=True)
class GeneratorConfig:
    """Everything that defines one generated population."""

    seed: int = 20260709
    n_accounts: int = 9000
    #: observation window per account, in months
    months: int = 36
    #: forward window for the label, in months
    horizon: int = 12
    #: days-past-due at which an account is NPA ("gone bad")
    npa_dpd: float = 90.0
    #: calendar month of ``month_idx == 0``
    start: pd.Timestamp = pd.Timestamp("2023-01-01")
    mix: PopulationMix = field(default_factory=lambda: POPULATION)
    #: registry keys to generate; ``None`` means all eight.  Restricting to
    #: ``("msme_cc", "msme_tl")`` is how the equivalence suite regenerates the
    #: July 2026 book on its own.
    portfolio_keys: tuple[str, ...] | None = None
    #: SD-D4 master switch: silent/fast defaulters, the hard-negative
    #: extensions to the transient episodes, seasonal confounders, measurement
    #: noise and MAR missingness.
    #:
    #: **The default is True and the shipped panel is the noisy one.**  Setting
    #: it False reproduces the July 2026 fingerprint exactly and is used by the
    #: equivalence suite and by nothing else — a panel generated with
    #: ``noise=False`` is not the dataset DRISHTi is trained or validated on,
    #: and its AUC is above the pre-registered ceiling by design.
    noise: bool = True


def _by_account(values: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Flatten an ``(N,)`` per-account column onto the kept panel rows."""
    return np.broadcast_to(values[:, None], keep.shape)[keep]


def _by_month(values: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Flatten an ``(M,)`` per-month column onto the kept panel rows."""
    return np.broadcast_to(values[None, :], keep.shape)[keep]


def _categorical(codes: np.ndarray, labels: tuple[str, ...]) -> pd.Categorical:
    """Wrap integer codes as a pandas categorical (cheap for 2M-row panels).

    A code of ``-1`` becomes NaN, which is how a borrower who is not an
    enterprise ends up with no NIC group.
    """
    return pd.Categorical.from_codes(codes.astype(np.int32), categories=list(labels))


def generate(config: GeneratorConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate the account-month panel and the static account table.

    Args:
        config: seed, population size, observation window, label horizon and
            the subset of portfolios to generate.

    Returns:
        ``(panel, accounts)`` — the long-format panel and one row per account.
    """
    months, mix = config.months, config.mix
    selected = registry(config.portfolio_keys)
    population, portfolios = draw_population(
        config.seed, config.n_accounts, months, mix, selected, config.noise
    )
    stress = build_stress_path(
        population.is_defaulter, population.npa_month, population.onset,
        population.severity, months, mix, population.silent,
    )

    month_index = np.arange(months)
    calendar_month = ((config.start.month - 1 + month_index) % 12 + 1).astype(np.int64)

    shape = (config.n_accounts, months)
    raw: dict[str, np.ndarray] = {name: np.full(shape, np.nan) for name in _RAW_STACKS}
    extra: dict[str, np.ndarray] = {}
    episode = np.zeros(shape, dtype=bool)
    arrears = np.zeros(config.n_accounts, dtype=bool)
    for code, portfolio in enumerate(portfolios):
        rows = np.flatnonzero(population.portfolio_code == code)
        if rows.size == 0:
            continue
        rng = stream(config.seed, f"channels:{portfolio.key}")
        block = simulate_channels(
            rng,
            stream(config.seed, f"channels_sdd3:{portfolio.key}"),
            stream(config.seed, f"noise_sdd4:{portfolio.key}"),
            portfolio,
            draw_baselines(rng, population.sanctioned[rows], portfolio.params),
            BlockInputs(
                sanctioned=population.sanctioned[rows],
                tenor_months=population.tenor_months[rows],
                rate_pa=population.interest_rate_pa[rows],
                vintage_months_0=population.vintage_months_0[rows],
                bureau_score_0=population.bureau_score_0[rows],
                calendar_month=calendar_month,
            ),
            stress.select(rows),
            mix,
            months,
            config.noise,
        )
        for name, values in raw.items():
            values[rows] = getattr(block, name)
        for name, values in block.extra.items():
            if name not in extra:
                extra[name] = np.full(shape, np.nan)
            extra[name][rows] = values
        if block.transient_episode is not None:
            episode[rows] = block.transient_episode
            arrears[rows] = block.transient_arrears

    stacked = Channels(
        utilisation=raw["utilisation"], inflow=raw["inflow"], gst_sales=raw["gst_sales"],
        txn=raw["txn"], dpd=raw["dpd"], bounce=raw["bounce"],
        minbal_breach=raw["minbal_breach"], adverse_remark=raw["adverse_remark"],
    )
    trailing = trailing_features(stacked)

    # Every dynamic column as an ``(N, M)`` array, so SD-D4's missingness can
    # be applied as a mask over cells rather than as a special case inside
    # each channel.  The truth was simulated; what follows decides what the
    # bank actually HELD that month.
    dynamic: dict[str, np.ndarray] = {
        "dpd": stacked.dpd,
        "utilisation": stacked.utilisation,
        "inflow": stacked.inflow,
        "gst_sales": stacked.gst_sales,
        "txn_count": stacked.txn,
        "bounce": stacked.bounce,
        "minbal_breach": stacked.minbal_breach,
        "adverse_remark": stacked.adverse_remark,
    }
    dynamic.update(trailing)
    dynamic.update(extra)
    gaps = np.zeros(shape, dtype=bool)
    if config.noise:
        gaps = statement_gaps(stream(config.seed, "missingness"), config.n_accounts,
                              months, mix)
        _apply_missingness(dynamic, population, portfolios, mix, gaps)

    keep = standard_rows(stress, stacked.dpd, config.npa_dpd)
    dates = np.array([
        (config.start + pd.DateOffset(months=int(t))).strftime("%Y-%m") for t in month_index
    ])
    states = state_levels(mix)
    # several portfolios share a loan_type (six of the eight are term loans),
    # so the categorical needs the deduplicated levels and a code per portfolio
    loan_type_levels: tuple[str, ...] = tuple(
        dict.fromkeys(p.loan_type for p in portfolios)
    )
    loan_type_code = np.array(
        [loan_type_levels.index(p.loan_type) for p in portfolios], dtype=np.int64
    )
    nic_levels = tuple(
        name for name in (mix.nic_groups.get(level) for level in mix.sector_levels)
        if name is not None
    )
    vintage_months_row = (
        _by_account(population.vintage_months_0, keep) + _by_month(month_index, keep)
    )

    panel: dict[str, object] = {
        "account_id": _categorical(
            _by_account(np.arange(config.n_accounts), keep), tuple(population.account_id)
        ),
        "month_idx": _by_month(month_index, keep),
        "date": _categorical(_by_month(month_index, keep), tuple(dates)),
        "sector": _categorical(_by_account(population.sector_code, keep), mix.sector_levels),
        "region": _categorical(_by_account(population.region_code, keep), mix.region_levels),
        "loan_type": _categorical(
            loan_type_code[_by_account(population.portfolio_code, keep)], loan_type_levels
        ),
        "segment": _categorical(
            _by_account(segment_codes(population.sanctioned), keep), SEGMENTS
        ),
        "qualification": _categorical(
            _by_account(population.qualification_code, keep), mix.qualification_levels
        ),
        "promoter_age_group": _categorical(
            _by_account(population.age_group_code, keep), mix.age_group_levels
        ),
        "log_sanctioned": _by_account(np.log(population.sanctioned), keep),
        "business_age_years": _by_account(population.business_age_years, keep),
        "vintage_months": vintage_months_row,
        "vintage_band": _categorical(
            _vintage_band_codes(vintage_months_row), VINTAGE_BANDS
        ),
        "portfolio": _categorical(
            _by_account(population.portfolio_code, keep), tuple(p.code for p in portfolios)
        ),
        "constitution": _categorical(
            _by_account(population.constitution_code, keep), mix.constitution_levels
        ),
        "state": _categorical(_by_account(population.state_code, keep), states),
        "city_tier": _categorical(
            _by_account(population.city_tier_code, keep), mix.city_tier_levels
        ),
        "nic_group": _categorical(_by_account(population.nic_code, keep), nic_levels),
        "secured": _by_account(population.secured, keep),
        "tenor_months": _by_account(population.tenor_months, keep),
        "interest_rate_pa": _by_account(population.interest_rate_pa, keep),
        "default_within_12m": default_within_12m(stress, config.horizon)[keep],
        "sma2_within_6m": sma2_within_6m(stacked.dpd)[keep],
        "labelable": labelable_rows(config.n_accounts, months, config.horizon)[keep],
        "months_to_npa": months_to_npa_column(stress)[keep],
    }
    panel.update({name: values[keep] for name, values in dynamic.items()})
    for name in PANEL_COLUMNS:
        panel.setdefault(name, np.full(int(keep.sum()), np.nan))

    for name, places in _ROUNDING.items():
        panel[name] = np.round(panel[name], places)

    frame = pd.DataFrame(panel)[list(PANEL_COLUMNS)]
    _blank_absent_channels(frame, population, portfolios, keep)
    _finalise_integers(frame)

    accounts = pd.DataFrame({
        "account_id": population.account_id,
        "sector": np.asarray(mix.sector_levels)[population.sector_code],
        "region": np.asarray(mix.region_levels)[population.region_code],
        "loan_type": np.asarray([p.loan_type for p in portfolios])[population.portfolio_code],
        "segment": np.asarray(SEGMENTS)[segment_codes(population.sanctioned)],
        "qualification": np.asarray(mix.qualification_levels)[population.qualification_code],
        "promoter_age_group": np.asarray(mix.age_group_levels)[population.age_group_code],
        "sanctioned_amount": population.sanctioned,
        "business_age_years": population.business_age_years,
        "vintage_months_0": population.vintage_months_0,
        "is_defaulter": population.is_defaulter.astype(np.int64),
        "npa_month": population.npa_month,
        "severity": population.severity,
        "onset": population.onset,
        "portfolio": np.asarray([p.code for p in portfolios])[population.portfolio_code],
        "constitution": np.asarray(mix.constitution_levels)[population.constitution_code],
        "state": np.asarray(states)[population.state_code],
        "city_tier": np.asarray(mix.city_tier_levels)[population.city_tier_code],
        "nic_group": np.where(
            population.nic_code >= 0,
            np.asarray(nic_levels + ("",))[population.nic_code],
            None,
        ),
        "secured": population.secured,
        "tenor_months": population.tenor_months,
        "interest_rate_pa": np.round(population.interest_rate_pa, 4),
        "bureau_score_0": np.round(population.bureau_score_0, 0),
        "risk_z": np.round(population.risk_z, 4),
        "silent_default": population.silent.astype(np.int64),
        "transient_months": episode.sum(axis=1).astype(np.int64),
        "transient_arrears": arrears.astype(np.int64),
        "statement_gap_months": gaps.sum(axis=1).astype(np.int64),
    })[list(ACCOUNT_COLUMNS)]
    return frame, accounts


def _blank_absent_channels(
    frame: pd.DataFrame,
    population: Population,
    portfolios: list[Portfolio],
    keep: np.ndarray,
) -> None:
    """NaN out the columns a portfolio structurally cannot observe.

    The per-portfolio blocks already leave those cells unwritten, so this is
    belt and braces — but it is also the single declaration of the rule, and
    the test that proves the hook works runs through it.

    Args:
        frame: the assembled panel, modified in place.
        population: supplies each row's portfolio.
        portfolios: the registry in code order.
        keep: the ``(N, M)`` row mask the panel was flattened with.
    """
    absent = [(code, p) for code, p in enumerate(portfolios) if p.absent_channels]
    if not absent:
        return
    portfolio_row = _by_account(population.portfolio_code, keep)
    for code, portfolio in absent:
        rows = portfolio_row == code
        for channel in portfolio.absent_channels:
            for column in CHANNEL_COLUMNS[channel]:
                if frame[column].dtype.kind in "iub":
                    frame[column] = frame[column].astype(np.float64)
                frame.loc[rows, column] = np.nan


#: what a missing bank statement takes with it.  These are the columns a
#: lender computes FROM the statement feed, so if the month never arrived none
#: of them exists — and writing a zero instead would tell the model the
#: borrower banked nothing, which is a different and much worse claim.
_STATEMENT_COLUMNS: tuple[str, ...] = (
    "inflow", "inflow_trend_3m", "inflow_vs_6m_avg",
    "txn_count", "txn_drop_flag", "balance", "min_balance_6m",
)


def _apply_missingness(
    dynamic: dict[str, np.ndarray],
    population: Population,
    portfolios: list[Portfolio],
    mix: PopulationMix,
    gaps: np.ndarray,
) -> None:
    """Blank the cells the bank did not actually have.  SD-D4.

    Three rules, and every one of them is **missing at random** — the
    missingness depends on things the model can SEE (the borrower's legal form,
    their occupation) or on nothing at all (a failed statement pull), never on
    the borrower's condition or on the label:

    * **No GST return for an Individual.**  A portfolio can carry a GST channel
      and still have borrowers who file nothing; LAP is where it bites, at
      roughly two in five.  Portfolio-level absence
      (:attr:`~generator.portfolios.Portfolio.absent_channels`) covers the
      products where nobody files — this is the per-borrower half.
    * **No salary credit for the self-employed.**  A self-employed home-loan
      borrower is underwritten on returns and business banking, not payroll, so
      the portfolio's own first link is dark for them and the model has to fall
      back on the shared spine.
    * **Statement gaps.**  One to three months, on a share of accounts, drawn
      from a stream that has never seen the latent stress.

    Args:
        dynamic: column name -> ``(N, M)`` array, modified in place.
        population: supplies constitution, sector and portfolio per account.
        portfolios: the registry in code order.
        mix: supplies the category universes.
        gaps: ``(N, M)`` statement-gap mask.
    """
    files = files_gst(population.constitution_code, mix.constitution_levels)
    salaried_code = (
        mix.sector_levels.index("Salaried") if "Salaried" in mix.sector_levels else -1
    )
    self_employed = population.sector_code != salaried_code

    per_column: dict[str, np.ndarray] = {}
    for code, portfolio in enumerate(portfolios):
        held = population.portfolio_code == code
        if portfolio.has("gst"):
            _add(per_column, CHANNEL_COLUMNS["gst"], held & ~files)
        if portfolio.has("salary"):
            _add(per_column, CHANNEL_COLUMNS["salary"], held & self_employed)
    for column, accounts in per_column.items():
        if column in dynamic:
            dynamic[column] = np.where(accounts[:, None], np.nan, dynamic[column])
    for column in _STATEMENT_COLUMNS:
        if column in dynamic:
            dynamic[column] = np.where(gaps, np.nan, dynamic[column])


def _add(store: dict[str, np.ndarray], columns: tuple[str, ...], mask: np.ndarray) -> None:
    """OR ``mask`` into each column's account-level blanking mask."""
    for column in columns:
        store[column] = store[column] | mask if column in store else mask.copy()


def _finalise_integers(frame: pd.DataFrame) -> None:
    """Give every whole-number column an integer dtype.

    A column every portfolio observes keeps the July 2026 build's plain
    ``int64``.  One that some portfolio cannot observe becomes pandas' nullable
    ``Int64``, which writes an empty cell rather than ``0.0`` — the distinction
    the whole panel rests on, and about 8% of the CSV's size at 45,000 x 48.

    Args:
        frame: the assembled panel, modified in place.
    """
    for column in _INTEGER_COLUMNS:
        values = frame[column]
        rounded = np.round(values.to_numpy(dtype=np.float64))
        if values.notna().all():
            frame[column] = rounded.astype(np.int64)
        else:
            frame[column] = pd.array(rounded, dtype="Int64")


def write(panel: pd.DataFrame, accounts: pd.DataFrame, outdir: Path) -> None:
    """Write both CSVs into ``outdir``.

    The panel is 2 million rows by 69 columns at the validation population, and
    **writing it was costing more than simulating it** — 41 s of a 60 s budget
    against 9 s of generation.  ``pyarrow.csv.write_csv`` does the same job in
    about 5 s, so it is used when pyarrow is installed (it is, as a pandas
    dependency) and ``DataFrame.to_csv`` remains the fallback.

    The two writers are interchangeable for this panel, and the equivalence
    suite is what proves it: every column round-trips to the same dtype and the
    same values.  The only visible difference is that pyarrow quotes strings,
    which ``read_csv`` strips.

    Args:
        panel: the account-month panel.
        accounts: one row per account.
        outdir: directory to write into; created if absent.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(panel, outdir / "msme_loan_panel.csv")
    _write_csv(accounts, outdir / "accounts_static.csv")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write one frame, preferring pyarrow's writer."""
    try:
        import pyarrow as pa
        import pyarrow.csv as pacsv
    except ImportError:                                   # pragma: no cover
        frame.to_csv(path, index=False)
        return
    pacsv.write_csv(pa.Table.from_pandas(frame, preserve_index=False), str(path))


def _default_outdir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def main(argv: list[str] | None = None) -> None:
    """CLI entry point; prints the same progress lines the July build printed."""
    parser = argparse.ArgumentParser(
        description="Generate the synthetic MSME loan-performance panel.",
    )
    defaults = GeneratorConfig()
    parser.add_argument("--seed", type=int, default=defaults.seed,
                        help="master seed; fully determines the output")
    parser.add_argument("--n", type=int, default=defaults.n_accounts,
                        help="number of accounts")
    parser.add_argument("--months", type=int, default=defaults.months,
                        help="observation window per account, in months")
    parser.add_argument("--out", type=Path, default=_default_outdir(),
                        help="output directory for the two CSVs")
    parser.add_argument("--portfolios", type=str, default=None,
                        help="comma-separated registry keys to generate (default: all)")
    parser.add_argument("--no-noise", action="store_true",
                        help="switch off SD-D4 (silent defaulters, hard negatives, "
                             "seasonal confounders, measurement noise, missingness). "
                             "Reproduces the July 2026 fingerprint; NOT the shipped "
                             "dataset, and its AUC is above the pre-registered ceiling")
    args = parser.parse_args(argv)

    keys = tuple(args.portfolios.split(",")) if args.portfolios else None
    config = GeneratorConfig(
        seed=args.seed, n_accounts=args.n, months=args.months, portfolio_keys=keys,
        noise=not args.no_noise,
    )
    print("Building accounts ...")
    panel, accounts = generate(config)
    rate = accounts.is_defaulter.mean()
    print(f"  {len(accounts):,} accounts | eventual default rate = {rate:.1%}")
    for key in (keys or tuple(PORTFOLIOS)):
        portfolio = PORTFOLIOS[key]
        held = int((accounts.portfolio == portfolio.code).sum())
        print(f"    {portfolio.label}: {held:,} ({held / len(accounts):.1%})")
    print("Simulating monthly trajectories + assembling panel ...")
    print(f"  panel rows = {len(panel):,}")
    print(f"  label prevalence (rows that will default within 12m) = "
          f"{panel.default_within_12m.mean():.2%}")
    print(f"  unique accounts appearing in panel = {panel.account_id.nunique():,}")

    # ---- SD-D5: the rates are ASSERTED, not hoped for -------------------- #
    rates = measure_base_rates(panel, accounts)
    print("Checking the pre-registered rates ...")
    print(f"  12-month default rate (labelable rows) = {rates.book:.2%} "
          f"[DR-03 band {sources.value('book.annual_slippage_band')}]")
    for portfolio in (PORTFOLIOS[key] for key in (keys or tuple(PORTFOLIOS))):
        observed = rates.by_portfolio.get(portfolio.code)
        if observed is not None:
            low, high = portfolio.default_rate_band
            print(f"    {portfolio.code:18s} {observed:.2%}  band "
                  f"[{low:.1%}, {high:.1%}]")
    print(f"  SMA-2 within 6m = {rates.sma2:.2%} "
          f"({rates.sma2_to_npa:.2f}x the 12-month NPA rate; "
          f"{rates.sma2_to_npa_events:.2f} SMA-2 entries per NPA per unit time, "
          f"band {sources.value('book.sma2_to_npa_event_ratio_band')})")
    print(f"  defaulters with no warning chain = {rates.silent_share:.1%}")
    if config.noise:
        assert_base_rates(rates, list(registry(keys).values()))
    else:
        print("  (noise off: bands NOT asserted — this is not the shipped dataset)")

    write(panel, accounts, args.out)
    print(f"Wrote {args.out}/msme_loan_panel.csv and accounts_static.csv")


if __name__ == "__main__":
    main()

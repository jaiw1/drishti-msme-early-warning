"""Panel assembly and CLI — the entry point of the generator.

Driven through the pipeline's wrapper, which forwards every argument::

    python3 src/generate_data.py                                  # 9,000 x 36
    python3 src/generate_data.py --seed 7 --n 45000 --months 48 --out data

Pipeline
--------
1. :func:`generator.latent.draw_population` draws the whole book and decides
   who defaults, when, and how steeply.
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

Determinism
-----------
``--seed`` fully determines the output.  Each stage draws from its own
name-addressed stream (see :func:`generator.noise.stream`), so the same seed
gives byte-identical CSVs across runs.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .channels import (
    CHANNEL_COLUMNS,
    Channels,
    draw_baselines,
    simulate_channels,
    trailing_features,
)
from .constitutions import SEGMENTS, segment_codes
from .labels import default_within_12m, labelable_rows, months_to_npa_column, standard_rows
from .latent import Population, build_stress_path, draw_population
from .noise import stream
from .portfolios import POPULATION, PORTFOLIOS, PopulationMix, Portfolio

__all__ = [
    "ACCOUNT_COLUMNS",
    "PANEL_COLUMNS",
    "GeneratorConfig",
    "generate",
    "main",
    "write",
]

#: panel column order — byte-compatible with the July build's CSV
PANEL_COLUMNS: tuple[str, ...] = (
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

#: accounts_static.csv column order
ACCOUNT_COLUMNS: tuple[str, ...] = (
    "account_id", "sector", "region", "loan_type", "segment", "qualification",
    "promoter_age_group", "sanctioned_amount", "business_age_years", "vintage_months_0",
    "is_defaulter", "npa_month", "severity", "onset",
)

#: decimal places each float column is rounded to before writing
_ROUNDING: dict[str, int] = {
    "dpd": 1, "utilisation": 4, "inflow": 0, "gst_sales": 0, "dpd_max_6m": 1,
    "util_avg_3m": 4, "util_max_6m": 4, "inflow_trend_3m": 4, "inflow_vs_6m_avg": 4,
    "sales_trend_3m": 4,
}

#: columns written as integers
_INTEGER_COLUMNS: frozenset[str] = frozenset({
    "txn_count", "times_late_6m", "bounces_6m", "minbal_breach_6m",
    "months_over_90pct_util_6m", "adverse_remark_6m",
})


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


def _by_account(values: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Flatten an ``(N,)`` per-account column onto the kept panel rows."""
    return np.broadcast_to(values[:, None], keep.shape)[keep]


def _by_month(values: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Flatten an ``(M,)`` per-month column onto the kept panel rows."""
    return np.broadcast_to(values[None, :], keep.shape)[keep]


def _categorical(codes: np.ndarray, labels: tuple[str, ...]) -> pd.Categorical:
    """Wrap integer codes as a pandas categorical (cheap for 2M-row panels)."""
    return pd.Categorical.from_codes(codes.astype(np.int32), categories=list(labels))


def generate(config: GeneratorConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate the account-month panel and the static account table.

    Args:
        config: seed, population size, observation window and label horizon.

    Returns:
        ``(panel, accounts)`` — the long-format panel and one row per account.
    """
    months, mix = config.months, config.mix
    population, portfolios = draw_population(
        stream(config.seed, "population"), config.n_accounts, months, mix
    )
    stress = build_stress_path(
        population.is_defaulter, population.npa_month, population.onset,
        population.severity, months, mix,
    )

    shape = (config.n_accounts, months)
    raw: dict[str, np.ndarray] = {
        "utilisation": np.empty(shape), "inflow": np.empty(shape),
        "gst_sales": np.empty(shape), "txn": np.empty(shape), "dpd": np.empty(shape),
        "bounce": np.empty(shape, np.int64), "minbal_breach": np.empty(shape, np.int64),
        "adverse_remark": np.empty(shape, np.int64),
    }
    for code, portfolio in enumerate(portfolios):
        rows = np.flatnonzero(population.portfolio_code == code)
        if rows.size == 0:
            continue
        rng = stream(config.seed, f"channels:{portfolio.key}")
        block = simulate_channels(
            rng,
            draw_baselines(rng, population.sanctioned[rows], portfolio.params),
            stress.select(rows),
            portfolio.params,
            months,
        )
        for name, values in raw.items():
            values[rows] = getattr(block, name)

    stacked = Channels(
        utilisation=raw["utilisation"], inflow=raw["inflow"], gst_sales=raw["gst_sales"],
        txn=raw["txn"], dpd=raw["dpd"], bounce=raw["bounce"],
        minbal_breach=raw["minbal_breach"], adverse_remark=raw["adverse_remark"],
    )
    trailing = trailing_features(stacked)

    keep = standard_rows(stress, stacked.dpd, config.npa_dpd)
    month_index = np.arange(months)
    dates = np.array([
        (config.start + pd.DateOffset(months=int(t))).strftime("%Y-%m") for t in month_index
    ])

    panel: dict[str, object] = {
        "account_id": _categorical(
            _by_account(np.arange(config.n_accounts), keep), tuple(population.account_id)
        ),
        "month_idx": _by_month(month_index, keep),
        "date": _categorical(_by_month(month_index, keep), tuple(dates)),
        "sector": _categorical(_by_account(population.sector_code, keep), tuple(mix.sectors)),
        "region": _categorical(_by_account(population.region_code, keep), tuple(mix.regions)),
        "loan_type": _categorical(
            _by_account(population.portfolio_code, keep),
            tuple(p.loan_type for p in portfolios),
        ),
        "segment": _categorical(
            _by_account(segment_codes(population.sanctioned), keep), SEGMENTS
        ),
        "qualification": _categorical(
            _by_account(population.qualification_code, keep), tuple(mix.qualifications)
        ),
        "promoter_age_group": _categorical(
            _by_account(population.age_group_code, keep), tuple(mix.age_groups)
        ),
        "log_sanctioned": _by_account(np.log(population.sanctioned), keep),
        "business_age_years": _by_account(population.business_age_years, keep),
        "vintage_months": (
            _by_account(population.vintage_months_0, keep) + _by_month(month_index, keep)
        ),
        "dpd": stacked.dpd[keep],
        "utilisation": stacked.utilisation[keep],
        "inflow": stacked.inflow[keep],
        "gst_sales": stacked.gst_sales[keep],
        "txn_count": stacked.txn[keep],
        "bounce": stacked.bounce[keep],
        "minbal_breach": stacked.minbal_breach[keep],
        "adverse_remark": stacked.adverse_remark[keep],
        "default_within_12m": default_within_12m(stress, config.horizon)[keep],
        "labelable": labelable_rows(config.n_accounts, months, config.horizon)[keep],
        "months_to_npa": months_to_npa_column(stress)[keep],
    }
    panel.update({name: values[keep] for name, values in trailing.items()})

    for name, places in _ROUNDING.items():
        panel[name] = np.round(panel[name], places)
    for name in _INTEGER_COLUMNS:
        panel[name] = np.round(panel[name]).astype(np.int64)

    frame = pd.DataFrame(panel)[list(PANEL_COLUMNS)]
    _blank_absent_channels(frame, population, portfolios, keep)

    accounts = pd.DataFrame({
        "account_id": population.account_id,
        "sector": np.asarray(tuple(mix.sectors))[population.sector_code],
        "region": np.asarray(tuple(mix.regions))[population.region_code],
        "loan_type": np.asarray([p.loan_type for p in portfolios])[population.portfolio_code],
        "segment": np.asarray(SEGMENTS)[segment_codes(population.sanctioned)],
        "qualification": np.asarray(tuple(mix.qualifications))[population.qualification_code],
        "promoter_age_group": np.asarray(tuple(mix.age_groups))[population.age_group_code],
        "sanctioned_amount": population.sanctioned,
        "business_age_years": population.business_age_years,
        "vintage_months_0": population.vintage_months_0,
        "is_defaulter": population.is_defaulter.astype(np.int64),
        "npa_month": population.npa_month,
        "severity": population.severity,
        "onset": population.onset,
    })[list(ACCOUNT_COLUMNS)]
    return frame, accounts


def _blank_absent_channels(
    frame: pd.DataFrame,
    population: Population,
    portfolios: list[Portfolio],
    keep: np.ndarray,
) -> None:
    """NaN out the columns a portfolio structurally cannot observe.

    No portfolio declares ``absent_channels`` today, so this is a no-op on the
    current book.  It is what lets SD-D2 put Housing or Education (no GST
    turnover, no drawing power) into the same wide panel.
    """
    absent = [(code, p) for code, p in enumerate(portfolios) if p.absent_channels]
    if not absent:
        return
    portfolio_row = _by_account(population.portfolio_code, keep)
    for code, portfolio in absent:
        rows = portfolio_row == code
        for channel in portfolio.absent_channels:
            for column in CHANNEL_COLUMNS[channel]:
                frame.loc[rows, column] = np.nan


def write(panel: pd.DataFrame, accounts: pd.DataFrame, outdir: Path) -> None:
    """Write both CSVs into ``outdir``."""
    outdir.mkdir(parents=True, exist_ok=True)
    panel.to_csv(outdir / "msme_loan_panel.csv", index=False)
    accounts.to_csv(outdir / "accounts_static.csv", index=False)


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
    args = parser.parse_args(argv)

    config = GeneratorConfig(seed=args.seed, n_accounts=args.n, months=args.months)
    print("Building accounts ...")
    panel, accounts = generate(config)
    rate = accounts.is_defaulter.mean()
    print(f"  {len(accounts):,} accounts | eventual default rate = {rate:.1%}")
    for portfolio in PORTFOLIOS.values():
        held = int((accounts.loan_type == portfolio.loan_type).sum())
        print(f"    {portfolio.label}: {held:,} ({held / len(accounts):.1%})")
    print("Simulating monthly trajectories + assembling panel ...")
    print(f"  panel rows = {len(panel):,}")
    print(f"  label prevalence (rows that will default within 12m) = "
          f"{panel.default_within_12m.mean():.2%}")
    print(f"  unique accounts appearing in panel = {panel.account_id.nunique():,}")
    write(panel, accounts, args.out)
    print(f"Wrote {args.out}/msme_loan_panel.csv and accounts_static.csv")


if __name__ == "__main__":
    main()

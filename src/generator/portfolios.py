"""Portfolio registry — the one place a new lending portfolio gets declared.

TODAY this registry holds only the two MSME portfolios the shipped panel
already contains: MSME cash-credit (revolving working capital) and MSME term
loan (EMI).  Their mix (55/45) and parameters reproduce the original
single-file simulator exactly; the only thing that differs between them today
is the baseline credit-limit utilisation (0.52 vs 0.35).

HOW TO EXTEND (SD-D2 / SD-D3 — deliberately NOT implemented here yet)
---------------------------------------------------------------------
Adding Housing / Education / Agri-KCC / Personal / LAP / Auto is purely
additive — one new ``Portfolio`` entry in :data:`PORTFOLIOS`::

    PORTFOLIOS["housing"] = Portfolio(
        key="housing",
        label="Housing loan",
        loan_type="Housing",
        share=0.12,
        channels=("utilisation", "cash_flow", "transactions",
                  "repayment", "adverse"),      # salaried borrower: no GST
        params=replace(BASE_CHANNEL_PARAMS, base_util_mean=0.0, ...),
    )

Nothing else in the package has to change, because:

* :mod:`generator.build` partitions the population by ``Portfolio.key`` and
  simulates each block as its own ``(N_p, M)`` array stack — a new portfolio
  is simply a new block, and blocks are scattered back into the full panel by
  account index, so account ordering is unaffected.
* :mod:`generator.channels` is driven entirely by the portfolio's
  :class:`ChannelParams` block; a new portfolio brings its own observation
  parameters rather than editing shared code.
* ``Portfolio.channels`` declares which observation channels the portfolio
  *has*; everything else is structurally unobservable for it
  (``Portfolio.absent_channels``).  :mod:`generator.build` blanks those
  columns to NaN after assembly, which is what makes one wide panel legal
  across heterogeneous portfolios (an individual borrower has no GST turnover,
  a term loan has no drawing power, and so on).

The population attributes (sector, geography, ticket size, vintage, promoter
profile) currently live in the shared :data:`POPULATION` block because every
portfolio in the July build drew from the same MSME population.  SD-D2 moves
them onto :class:`Portfolio` so each portfolio can carry its own ticket and
geography mix; the call sites already take the mix as an argument.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

__all__ = [
    "ALL_CHANNELS",
    "BASE_CHANNEL_PARAMS",
    "POPULATION",
    "PORTFOLIOS",
    "ChannelParams",
    "PopulationMix",
    "Portfolio",
    "portfolio_mix",
]


# --------------------------------------------------------------------------- #
# Channel parameter block (one per portfolio)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChannelParams:
    """Every numeric knob :mod:`generator.channels` reads, for one portfolio.

    Grouped by the observation channel it drives.  Defaults reproduce the
    original MSME simulator; a new portfolio overrides only what differs
    (``dataclasses.replace(BASE_CHANNEL_PARAMS, ...)``).
    """

    # ---- per-account baselines ------------------------------------------- #
    base_util_mean: float = 0.52
    base_util_sd: float = 0.15
    base_util_bounds: tuple[float, float] = (0.05, 0.9)
    #: annual inflow as a multiple of the sanctioned limit (divided by 12)
    inflow_ratio_mean: float = 0.9
    inflow_ratio_sd: float = 0.35
    inflow_ratio_bounds: tuple[float, float] = (0.2, 2.5)
    #: declared GST sales as a multiple of banked inflow
    sales_ratio_mean: float = 1.15
    sales_ratio_sd: float = 0.2
    sales_ratio_bounds: tuple[float, float] = (0.6, 2.0)
    txn_mean: float = 45.0
    txn_sd: float = 20.0
    txn_bounds: tuple[float, float] = (6.0, 200.0)
    #: amplitude of the AR(1) conduct wobble (lower -> cleaner slide)
    wobble_mean: float = 0.05
    wobble_sd: float = 0.02
    wobble_bounds: tuple[float, float] = (0.02, 0.14)

    # ---- healthy-conduct dynamics ---------------------------------------- #
    ar1_phi: float = 0.6
    inflow_wobble_gain: float = 0.7
    txn_wobble_gain: float = 0.5
    util_bounds: tuple[float, float] = (0.02, 1.05)
    inflow_floor: float = 1000.0
    txn_floor: float = 1.0
    #: baseline operational-noise rates on a perfectly healthy account
    bounce_rate: float = 0.03
    minbal_rate: float = 0.04

    # ---- transient stress on healthy accounts (hard negatives) ----------- #
    transient_share: float = 0.18
    #: episode start is uniform on ``[start_lo, months + start_hi_offset)``
    transient_start_lo: int = 3
    transient_start_hi_offset: int = -6
    transient_length_bounds: tuple[int, int] = (2, 5)
    transient_util_mult: float = 1.25
    transient_util_bounds: tuple[float, float] = (0.0, 1.05)
    transient_inflow_mult: float = 0.75
    transient_bounce_rate: float = 0.3

    # ---- ordered deterioration (defaulters) ------------------------------ #
    # The *intensity* of the slide is the shared latent stress (see
    # ``PopulationMix.decline_*`` and :func:`generator.latent.build_stress_path`);
    # what follows is how THIS portfolio's channels respond to it.
    inflow_elasticity: float = 0.55
    inflow_decay_floor: float = 0.2
    sales_elasticity: float = 0.60
    sales_decay_floor: float = 0.2
    txn_elasticity: float = 0.40
    txn_decay_floor: float = 0.3
    util_lead_months: int = 10
    util_slide_gain: float = 0.35
    util_slide_shift: float = 0.18
    util_slide_bounds: tuple[float, float] = (0.1, 1.08)
    bounce_lead_months: int = 6
    bounce_slide_base: float = 0.12
    bounce_slide_gain: float = 0.5
    minbal_lead_months: int = 6
    minbal_slide_base: float = 0.12
    minbal_slide_gain: float = 0.4
    adverse_lead_months: int = 9
    adverse_slide_base: float = 0.04
    adverse_slide_gain: float = 0.13
    #: months-to-NPA -> days-past-due, the final (lagging) channel
    dpd_ladder: tuple[tuple[int, float], ...] = ((3, 15.0), (2, 38.0), (1, 68.0))
    dpd_noise_sd: float = 6.0

    # ---- at/after NPA (never emitted, but keeps trajectories honest) ----- #
    post_npa_dpd_base: float = 90.0
    post_npa_dpd_step: float = 30.0
    post_npa_dpd_cap: float = 180.0
    post_npa_util_mean: float = 1.0
    post_npa_util_sd: float = 0.03
    post_npa_util_bounds: tuple[float, float] = (0.9, 1.1)
    post_npa_inflow_mult: float = 0.4
    post_npa_sales_mult: float = 0.4


BASE_CHANNEL_PARAMS = ChannelParams()

#: Every observation channel a portfolio can declare.
ALL_CHANNELS: tuple[str, ...] = (
    "utilisation", "cash_flow", "gst", "transactions", "repayment", "adverse",
)


# --------------------------------------------------------------------------- #
# Portfolio
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Portfolio:
    """One lending portfolio: its share of the book and how it is observed."""

    key: str
    label: str
    #: value written to the panel's ``loan_type`` column
    loan_type: str
    #: relative weight in the population (normalised across the registry)
    share: float
    #: observation channels this portfolio exposes; anything omitted is
    #: structurally unobservable and lands in the panel as NaN
    channels: tuple[str, ...] = ALL_CHANNELS
    params: ChannelParams = BASE_CHANNEL_PARAMS

    def __post_init__(self) -> None:
        unknown = set(self.channels) - set(ALL_CHANNELS)
        if unknown:
            raise ValueError(f"portfolio {self.key!r}: unknown channels {sorted(unknown)}")

    @property
    def absent_channels(self) -> frozenset[str]:
        """Channels the bank cannot observe here -> NaN columns in the panel."""
        return frozenset(ALL_CHANNELS) - set(self.channels)


PORTFOLIOS: dict[str, Portfolio] = {
    "msme_cc": Portfolio(
        key="msme_cc",
        label="MSME cash credit / overdraft",
        loan_type="CashCredit",
        share=0.55,
        params=BASE_CHANNEL_PARAMS,
    ),
    "msme_tl": Portfolio(
        key="msme_tl",
        label="MSME term loan",
        loan_type="TermLoan",
        share=0.45,
        # a term loan is drawn down once, so the "utilisation" a bank sees is
        # the outstanding-to-sanction ratio and sits structurally lower
        params=replace(BASE_CHANNEL_PARAMS, base_util_mean=0.35),
    ),
}


def portfolio_mix() -> tuple[list[Portfolio], list[float]]:
    """Registry order plus normalised population weights."""
    items = list(PORTFOLIOS.values())
    total = sum(p.share for p in items)
    return items, [p.share / total for p in items]


# --------------------------------------------------------------------------- #
# Population mix (shared by every portfolio today; per-portfolio in SD-D2)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PopulationMix:
    """Static borrower attributes and their distributions."""

    #: sector -> (population weight, base-risk multiplier)
    sectors: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "Manufacturing": (0.22, 1.05),
        "Trading":       (0.30, 1.15),
        "Services":      (0.24, 0.90),
        "Retail":        (0.16, 1.10),
        "Logistics":     (0.08, 1.20),
    })
    regions: dict[str, float] = field(default_factory=lambda: {
        "North": 0.24, "South": 0.26, "West": 0.28, "East": 0.14, "Central": 0.08,
    })
    qualifications: dict[str, float] = field(default_factory=lambda: {
        "Graduate": 0.45, "UnderGrad": 0.30, "Professional": 0.15, "SchoolOnly": 0.10,
    })
    age_groups: dict[str, float] = field(default_factory=lambda: {
        "<30": 0.12, "30-40": 0.34, "40-50": 0.30, "50-60": 0.17, "60+": 0.07,
    })
    #: micro-heavy ticket: lognormal(14.0, 1.1) clipped to ₹0.5L-₹5cr
    ticket_log_mean: float = 14.0
    ticket_log_sd: float = 1.1
    ticket_bounds: tuple[float, float] = (5e4, 5e7)
    #: years in business ~ gamma(2.2, 3.0), truncated to 0-30
    business_age_shape: float = 2.2
    business_age_scale: float = 3.0
    business_age_bounds: tuple[float, float] = (0.0, 30.0)
    #: months since origination at t=0
    vintage_bounds: tuple[int, int] = (0, 48)

    # ---- latent-risk scorecard (who eventually defaults) ----------------- #
    #: static profile only WEAKLY tilts the odds — the irreducible-randomness
    #: term dominates on purpose, so a static scorecard alone cannot predict
    #: well and the model is forced to learn the DYNAMIC deterioration.
    risk_sector_gain: float = 0.55 * 6
    risk_business_age: float = -0.030
    risk_vintage: float = -0.012
    risk_log_ticket: float = 0.18
    risk_qualification: dict[str, float] = field(default_factory=lambda: {
        "SchoolOnly": 0.5, "UnderGrad": 0.15, "Graduate": 0.0, "Professional": -0.25,
    })
    risk_age_group: dict[str, float] = field(default_factory=lambda: {
        "<30": 0.35, "30-40": 0.10, "40-50": 0.0, "50-60": -0.05, "60+": 0.15,
    })
    risk_noise_sd: float = 1.15
    risk_intercept: float = -2.35
    risk_slope: float = 0.45

    # ---- shared latent stress: timing and intensity of the slide --------- #
    npa_month_lo: int = 6
    severity_mean: float = 1.0
    severity_sd: float = 0.25
    severity_bounds: tuple[float, float] = (0.5, 1.7)
    onset_mean: float = 13.0
    onset_sd: float = 3.0
    onset_bounds: tuple[float, float] = (5.0, 18.0)
    #: stress rises from ``floor_share * severity`` at onset to
    #: ``(floor_share + ramp_share) * severity`` at NPA, capped at ``cap``
    decline_cap: float = 1.3
    decline_floor_share: float = 0.30
    decline_ramp_share: float = 0.70


POPULATION = PopulationMix()

"""Portfolio registry — the one place a lending portfolio is declared.

The registry holds the **eight** portfolios DRISHTi scores, keyed by the
snake_case codes the build plan fixed::

    msme_cc  msme_tl  housing  education  agri  retail_unsecured  lap  auto

Each one carries two very different kinds of number, and they are kept in two
different places on purpose:

*Empirical* parameters — the mix, constitutions, ticket sizes, geography,
vintage, sector, tenor, rate bands, default-rate bands — live in
``sources.yaml`` with a citation and a confidence level, and are read through
:mod:`generator.sources`.  Nothing about the Indian lending market is hard-coded
in this file.

*Model-shape* parameters — elasticities, lead months, AR(1) φ, how steeply a
channel responds to stress — live in :class:`ChannelParams` below.  No public
source could back them; they describe the simulator, and pretending they were
sourced would be worse than saying so.

Why the split matters
---------------------
``Portfolio.channels`` is a **positive** declaration of what the bank can
observe for that product.  Everything it omits is structurally unobservable and
lands in the panel as NaN (:attr:`Portfolio.absent_channels`, blanked in
:func:`generator.build._blank_absent_channels`).  A salaried home-loan borrower
files no GST return; a term loan has no drawing power; a KCC farmer has no
salary credit.  That, and not a different model per product, is why one model
across all eight portfolios is legitimate: the *latent* stress process is
shared (:mod:`generator.latent`), only the *observation* channels differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import sources
from .constitutions import constitution_levels

__all__ = [
    "ALL_CHANNELS",
    "BASE_CHANNEL_PARAMS",
    "CHANNEL_PARAM_SOURCES",
    "MSME_KEYS",
    "POPULATION",
    "PORTFOLIOS",
    "ChannelParams",
    "PopulationMix",
    "Portfolio",
    "PortfolioPopulation",
    "portfolio_mix",
    "registry",
]


# --------------------------------------------------------------------------- #
# Channel parameter block (one per portfolio) — SIMULATION SHAPE, NOT SOURCED
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChannelParams:
    """Every numeric knob :mod:`generator.channels` reads, for one portfolio.

    Grouped by the observation channel it drives.  Defaults reproduce the
    original MSME simulator; a portfolio overrides only what differs
    (``dataclasses.replace(BASE_CHANNEL_PARAMS, ...)``).

    Fields listed in :data:`CHANNEL_PARAM_SOURCES` are filled from
    ``sources.yaml`` when the registry is built — those are the empirical ones.
    Everything else is a deliberate simulation choice.
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
    #: SD-D4: a bounced instalment that is not cleared inside the month leaves
    #: the account genuinely past due.  Decoupling `bounce` from `dpd`, as the
    #: July build did, is what made "days past due > 0" a near-perfect
    #: classifier on a synthetic book and a weak one in a real bank.
    bounce_uncured_share: float = 0.55
    bounce_dpd_ladder: tuple[float, ...] = (0.0, 16.0, 43.0, 68.0)

    # ---- SD-D4: not every defaulter shows every link --------------------- #
    #: probability that a given channel's stress response is visible at all on
    #: a given defaulter.  A dark link is not a weaker signal — it is a
    #: borrower whose trouble simply did not reach that instrument.
    chain_link_visibility: float = 0.72
    chain_link_strength_bounds: tuple[float, float] = (0.55, 1.50)

    # ---- transient stress on healthy accounts (hard negatives) ----------- #
    #: share of NEVER-defaulting accounts given one recoverable episode.  It is
    #: the single most important number in the file for how hard the book is:
    #: an account that dips, part-pays, bounces once and recovers is
    #: indistinguishable from an early-stage defaulter while it is happening.
    transient_share: float = 0.22
    #: episode start is uniform on ``[start_lo, months + start_hi_offset)``
    transient_start_lo: int = 3
    transient_start_hi_offset: int = -6
    transient_length_bounds: tuple[int, int] = (2, 8)
    transient_util_mult: float = 1.25
    transient_util_bounds: tuple[float, float] = (0.0, 1.05)
    transient_inflow_mult: float = 0.75
    transient_bounce_rate: float = 0.3
    # SD-D4: the episode also moves the portfolio's OWN first link, which is
    # what makes it a hard negative rather than a wobble in a column nobody
    # reads.  A share of episodes goes genuinely past due and then cures.
    transient_collection_bounds: tuple[float, float] = (0.12, 0.65)
    transient_arrears_share: float = 0.30
    #: SD-D8: capped at 58 (was 71/84) — see sources.yaml's `transient.arrears_ladder`
    #: note. A cured episode no longer reaches the 61-90 DPD band, which is what
    #: was diluting that band's forward default rate below the 31-60 band's.
    transient_arrears_ladder: tuple[float, ...] = (0.0, 22.0, 48.0, 58.0)
    transient_salary_miss_rate: float = 0.28
    transient_income_mult: float = 0.70
    transient_balance_mult: float = 0.55
    transient_new_emi_rate: float = 0.16
    #: the pre-SD-D4 episode population.  Used ONLY when the generator is run
    #: with ``noise=False``, which exists so the equivalence suite can
    #: reproduce the July 2026 MSME fingerprint exactly.  It is not a second
    #: opinion about how many accounts wobble — the sourced numbers above are.
    quiet_transient_share: float = 0.18
    quiet_transient_length_bounds: tuple[int, int] = (2, 5)

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

    # ======================================================================= #
    # SD-D3 — the shared columns and the portfolio-specific channel chains
    # ======================================================================= #

    # ---- EMI / interest demanded vs collected (every portfolio) ---------- #
    #: an interest-only facility (cash credit, KCC) demands interest on the
    #: outstanding; an EMI facility demands the amortised instalment
    interest_only: bool = False
    #: months before NPA at which part-payment starts — the MSME-TL chain's
    #: middle link, and the shared "money stops arriving" signal
    collection_lead_months: int = 8
    #: fraction of the demand left unpaid at full latent stress
    collection_shortfall_gain: float = 0.62
    #: healthy-account collection noise (a late transfer, a part-payment)
    collection_noise_sd: float = 0.018
    collection_short_rate: float = 0.06
    #: SD-D4: per-borrower depth of the shortfall, centred on 1
    spine_strength_bounds: tuple[float, float] = (0.35, 1.65)

    # ---- balance (every portfolio) --------------------------------------- #
    balance_elasticity: float = 0.75
    balance_floor: float = 0.0

    # ---- drawing power (cash credit, KCC) -------------------------------- #
    dp_to_limit_mean: float = 0.93
    dp_to_limit_sd: float = 0.05
    dp_squeeze_gain: float = 0.30

    # ---- salary (housing, education, retail-unsecured, auto) ------------- #
    salary_multiple_mean: float = 3.1
    salary_multiple_sd: float = 0.9
    salary_multiple_bounds: tuple[float, float] = (1.6, 9.0)
    salary_gap_threshold: float = 0.60
    #: the salary channel fires from the onset of the slide, with no gate —
    #: it is the LEADING signal for every salaried portfolio
    salary_elasticity: float = 0.52
    salary_miss_base: float = 0.02
    salary_miss_gain: float = 0.34

    # ---- EMI stacking (retail-unsecured) --------------------------------- #
    other_emi_count_lambda: float = 1.3
    other_emi_share_of_own: float = 0.55
    stress_new_emi_rate: float = 0.22
    emi_burden_breach: float = 0.55

    # ---- loan-to-value (housing, LAP, auto) ------------------------------ #
    ltv_origination: float = 0.74
    ltv_origination_sd: float = 0.08
    ltv_collateral_drift_pa: float = 0.045
    ltv_collateral_noise_sd: float = 0.012
    #: distress shaves the realisable collateral value on top of drift
    ltv_stress_haircut: float = 0.16

    # ---- rental income (LAP) --------------------------------------------- #
    rental_share_of_emi: float = 0.85
    rental_share_sd: float = 0.35
    rental_vacancy_rate: float = 0.05
    rental_elasticity: float = 0.70
    rental_stress_vacancy_gain: float = 0.35

    # ---- harvest / KCC renewal (agri) ------------------------------------ #
    harvest_receipt_multiple: float = 3.2
    harvest_off_season_floor: float = 0.18
    harvest_miss_depth: float = 0.62
    renewal_cycle_months: int = 12
    #: months before NPA at which the annual KCC renewal starts slipping.  It
    #: spans the whole slide on purpose: a renewal comes round once a crop
    #: year, so a narrower gate would leave most defaulters with no renewal due
    #: inside it and the signal would be structurally dead.
    renewal_lead_months: int = 18
    renewal_slip_gain: float = 0.85
    #: SD-D4: renewals slip for reasons that are nothing to do with the crop
    renewal_benign_slip_rate: float = 0.20

    # ---- moratorium (education) ------------------------------------------ #
    moratorium_end_bounds: tuple[int, int] = (-36, 30)
    moratorium_post_end_months: int = 9
    #: extra collection shortfall in the months right after the moratorium ends
    moratorium_shock_gain: float = 0.45

    # ---- commute spend (auto) -------------------------------------------- #
    commute_share_of_emi: float = 0.30
    commute_share_sd: float = 0.12
    commute_stress_drop: float = 0.70

    # ======================================================================= #
    # SD-D4 — seasonal confounders and measurement noise
    # ======================================================================= #
    # The *shape* of each calendar effect is shared and lives in
    # :func:`generator.channels.confounder_profile`; what a portfolio brings is
    # how loudly it feels it.  Zero means the effect does not apply — a term
    # loan has no revolving limit to draw down before Diwali.
    season_inflow_amp: float = 0.12
    season_util_amp: float = 0.0
    season_salary_amp: float = 0.0
    season_commute_amp: float = 0.0

    #: months between the turnover month and the month the bank sees it
    gst_lag_distribution: dict[int, float] = field(
        default_factory=lambda: {0: 0.42, 1: 0.43, 2: 0.15})
    #: rupees the demanded/collected amounts are rounded to
    amount_rounding: float = 10.0
    duplicate_batch_rate: float = 0.012
    duplicate_batch_bounds: tuple[float, float] = (1.3, 1.9)
    payment_reversal_rate: float = 0.015
    dp_refresh_months: int = 3
    dp_report_noise_sd: float = 0.07
    inflow_idio_sd: float = 0.22
    #: revolving limits only; a term loan has nothing to draw
    utilisation_idio_sd: float = 0.17
    salary_idio_sd: float = 0.11
    salary_split_rate: float = 0.05
    rental_idio_sd: float = 0.16
    rental_late_rate: float = 0.12
    harvest_yield_sd: float = 0.34
    harvest_sale_slip_rate: float = 0.22
    commute_idio_sd: float = 0.38
    commute_zero_rate: float = 0.07
    #: a carried collateral value is refreshed this often, and each refresh
    #: carries an appraisal error.  Between refreshes the bank holds a STALE
    #: number, so an LTV computed monthly is not a monthly measurement.
    collateral_revaluation_months: int = 12
    collateral_appraisal_error_sd: float = 0.09


BASE_CHANNEL_PARAMS = ChannelParams()

#: ``ChannelParams`` field -> dotted path in ``sources.yaml``, relative to the
#: portfolio.  These are the empirical knobs; everything else is model shape.
CHANNEL_PARAM_SOURCES: dict[str, str] = {
    # SD-D8: only msme_cc's sources.yaml block declares `utilisation.base_mean`
    # (see the sources.yaml note); every other portfolio KeyErrors on this
    # lookup and falls through to its own _SHAPE_OVERRIDES entry below, or to
    # BASE_CHANNEL_PARAMS.base_util_mean if it has none.
    "base_util_mean": "utilisation.base_mean",
    "ltv_origination": "ltv.origination",
    "ltv_origination_sd": "ltv.origination_sd",
    "ltv_collateral_drift_pa": "ltv.collateral_drift_pa",
    "rental_share_of_emi": "rental.share_of_emi",
    "rental_share_sd": "rental.share_sd",
    "rental_vacancy_rate": "rental.vacancy_rate",
    "harvest_miss_depth": "harvest.miss_depth",
    "renewal_benign_slip_rate": "harvest.benign_slip_rate",
    "renewal_cycle_months": "harvest.renewal_month",
    "moratorium_end_bounds": "moratorium.end_month_bounds",
    "moratorium_post_end_months": "moratorium.post_end_stress_months",
    "other_emi_count_lambda": "emi_stacking.other_emi_count_lambda",
    "other_emi_share_of_own": "emi_stacking.other_emi_share_of_own",
    "stress_new_emi_rate": "emi_stacking.stress_new_emi_rate",
    "emi_burden_breach": "emi_stacking.burden_breach",
    "commute_share_of_emi": "commute.spend_share_of_emi",
    "commute_share_sd": "commute.spend_share_sd",
    "commute_stress_drop": "commute.stress_drop",
    "harvest_receipt_multiple": "seasonality.harvest_receipt_multiple",
    "harvest_off_season_floor": "seasonality.off_season_floor",
    "salary_multiple_mean": "salary.credit_to_emi_multiple",
    "salary_multiple_sd": "salary.multiple_sd",
    "salary_multiple_bounds": "salary.multiple_bounds",
    "salary_gap_threshold": "salary.gap_threshold",
    # ---- SD-D4 ----------------------------------------------------------- #
    "bounce_uncured_share": "arrears.bounce_uncured_share",
    "collection_short_rate": "arrears.benign_part_payment_rate",
    "spine_strength_bounds": "arrears.spine_strength_bounds",
    "bounce_dpd_ladder": "arrears.bounce_dpd_ladder",
    "chain_link_visibility": "chain_visibility.link_visibility",
    "chain_link_strength_bounds": "chain_visibility.link_strength_bounds",
    "transient_share": "noise.transient_stress_share",
    "transient_length_bounds": "transient.length_months_bounds",
    "transient_collection_bounds": "transient.collection_shortfall_bounds",
    "transient_arrears_share": "transient.arrears_share",
    "transient_arrears_ladder": "transient.arrears_ladder",
    "transient_salary_miss_rate": "transient.salary_miss_rate",
    "transient_income_mult": "transient.income_multiple",
    "transient_balance_mult": "transient.balance_multiple",
    "transient_new_emi_rate": "transient.new_emi_rate",
    "season_inflow_amp": "noise.season_inflow_amplitude",
    "season_util_amp": "noise.season_utilisation_amplitude",
    "season_salary_amp": "noise.season_salary_amplitude",
    "season_commute_amp": "noise.season_commute_amplitude",
    "gst_lag_distribution": "measurement.gst_report_lag_distribution",
    "amount_rounding": "measurement.amount_rounding_rupees",
    "duplicate_batch_rate": "measurement.duplicate_batch_rate",
    "duplicate_batch_bounds": "measurement.duplicate_batch_multiple_bounds",
    "payment_reversal_rate": "measurement.payment_reversal_rate",
    "dp_refresh_months": "measurement.drawing_power_refresh_months",
    "dp_report_noise_sd": "measurement.drawing_power_noise_sd",
    "inflow_idio_sd": "measurement.inflow_idiosyncratic_sd",
    "utilisation_idio_sd": "measurement.utilisation_idiosyncratic_sd",
    "salary_idio_sd": "measurement.salary_idiosyncratic_sd",
    "salary_split_rate": "measurement.salary_split_credit_rate",
    "rental_idio_sd": "measurement.rental_idiosyncratic_sd",
    "rental_late_rate": "measurement.rental_late_rate",
    "harvest_yield_sd": "measurement.harvest_yield_sd",
    "harvest_sale_slip_rate": "measurement.harvest_sale_slip_rate",
    "commute_idio_sd": "measurement.commute_idiosyncratic_sd",
    "commute_zero_rate": "measurement.commute_zero_month_rate",
    "collateral_revaluation_months": "measurement.collateral_revaluation_months",
    "collateral_appraisal_error_sd": "measurement.collateral_appraisal_error_sd",
}

#: Every observation channel a portfolio can declare.  The first six are the
#: July 2026 build's; the rest are SD-D3's portfolio-specific chains.
ALL_CHANNELS: tuple[str, ...] = (
    "utilisation", "cash_flow", "gst", "transactions", "repayment", "adverse",
    "drawing_power", "salary", "emi_stacking", "ltv", "rental", "harvest",
    "moratorium", "commute",
)

#: the two portfolios the July 2026 panel already contained
MSME_KEYS: tuple[str, str] = ("msme_cc", "msme_tl")


# --------------------------------------------------------------------------- #
# Population attributes — per portfolio, all of it from sources.yaml
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PortfolioPopulation:
    """Static borrower attributes for one portfolio, as sourced distributions."""

    constitutions: dict[str, float]
    sectors: dict[str, float]
    regions: dict[str, float]
    city_tiers: dict[str, float]
    qualifications: dict[str, float]
    age_groups: dict[str, float]
    ticket_log_mean: float
    ticket_log_sd: float
    ticket_bounds: tuple[float, float]
    business_age_shape: float
    business_age_scale: float
    business_age_bounds: tuple[float, float]
    vintage_bounds: tuple[int, int]
    secured_share: float
    tenor_bounds: tuple[int, int]
    rate_bounds: tuple[float, float]

    @classmethod
    def from_sources(cls, key: str) -> "PortfolioPopulation":
        """Read one portfolio's attribute distributions out of ``sources.yaml``."""
        get = lambda path: sources.portfolio_value(key, path)  # noqa: E731
        return cls(
            constitutions=dict(get("constitutions")),
            sectors=dict(get("sectors")),
            regions=dict(get("regions")),
            city_tiers=dict(get("city_tiers")),
            qualifications=dict(get("qualifications")),
            age_groups=dict(get("age_groups")),
            ticket_log_mean=float(get("ticket.log_mean")),
            ticket_log_sd=float(get("ticket.log_sd")),
            ticket_bounds=tuple(get("ticket.bounds")),
            business_age_shape=float(get("business_age.shape")),
            business_age_scale=float(get("business_age.scale")),
            business_age_bounds=tuple(get("business_age.bounds")),
            vintage_bounds=tuple(get("vintage_months_bounds")),
            secured_share=float(get("secured_share")),
            tenor_bounds=tuple(get("tenor_months")),
            rate_bounds=tuple(get("interest_rate_pa")),
        )


# --------------------------------------------------------------------------- #
# Portfolio
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Portfolio:
    """One lending portfolio: its share of the book and how it is observed."""

    key: str
    #: the spelling the platform contract requires in the panel's ``portfolio``
    #: column (``data/bank/SCHEMA.md``, ``validation/criteria.yaml``)
    code: str
    label: str
    #: value written to the panel's ``loan_type`` column
    loan_type: str
    #: relative weight in the population (normalised across the registry)
    share: float
    #: observation channels this portfolio exposes; anything omitted is
    #: structurally unobservable and lands in the panel as NaN
    channels: tuple[str, ...] = ALL_CHANNELS
    params: ChannelParams = BASE_CHANNEL_PARAMS
    population: PortfolioPopulation | None = None
    #: log-odds shift on the shared latent-risk scorecard; calibrated so the
    #: realised 12-month label rate lands inside ``default_rate_band``
    risk_offset: float = 0.0
    #: the pre-registered plausibility band for this portfolio's annual rate
    default_rate_band: tuple[float, float] = (0.0, 1.0)
    #: SD-D4: share of THIS portfolio's defaulters that arrive with no warning
    #: chain at all — fraud, death, a sudden shock.  They are the honest
    #: ceiling on how well any model can score this book.
    silent_share: float = 0.0
    #: Months of RECOGNITION LAG between the borrower falling irrecoverably
    #: behind and the advance being classified NPA, over and above the ordinary
    #: 90-day rule.  Zero for every portfolio governed by the 90-DPD test.
    #:
    #: The exception the 2026-09-21 review raised is agriculture.  RBI's IRAC
    #: norms do not apply 90 DPD to crop loans: a short-duration crop advance
    #: becomes NPA when principal or interest is overdue for **two crop
    #: seasons**, and a long-duration crop advance for **one crop season**
    #: (RBI Master Circular on IRAC & Provisioning, agricultural advances).  A
    #: crop season here is the kharif/rabi half-year the mix already models,
    #: so two seasons is roughly twelve months rather than three.
    #:
    #: **Only applied when ``GeneratorConfig.portfolio_npa_rules`` is True.**
    #: It is off by default and the shipped panel does not use it: changing a
    #: label definition changes every downstream number and several
    #: pre-registered bands, and the review's own instruction is to have the
    #: bank confirm its classification policy before representing this as
    #: regulatory classification.  The switch exists so the difference can be
    #: measured (validation/experiments/e6_portfolio_npa_rules.py) rather than
    #: argued about.
    npa_recognition_months: int = 0

    def __post_init__(self) -> None:
        unknown = set(self.channels) - set(ALL_CHANNELS)
        if unknown:
            raise ValueError(f"portfolio {self.key!r}: unknown channels {sorted(unknown)}")

    @property
    def absent_channels(self) -> frozenset[str]:
        """Channels the bank cannot observe here -> NaN columns in the panel."""
        return frozenset(ALL_CHANNELS) - set(self.channels)

    def has(self, channel: str) -> bool:
        """Whether this portfolio declares ``channel``."""
        return channel in self.channels


def _channel_params(key: str, channels: tuple[str, ...]) -> ChannelParams:
    """Build a portfolio's ``ChannelParams``, overlaying the sourced knobs.

    Args:
        key: portfolio registry key.
        channels: the channels it declares (only their knobs are read).

    Returns:
        ``BASE_CHANNEL_PARAMS`` with every sourced field the portfolio declares
        replaced by the value in ``sources.yaml``.
    """
    overrides: dict[str, object] = {}
    for field_name, path in CHANNEL_PARAM_SOURCES.items():
        try:
            raw = sources.portfolio_value(key, path)
        except KeyError:
            continue
        current = getattr(BASE_CHANNEL_PARAMS, field_name)
        overrides[field_name] = tuple(raw) if isinstance(current, tuple) else type(current)(raw)
    overrides.update(_SHAPE_OVERRIDES.get(key, {}))
    return replace(BASE_CHANNEL_PARAMS, **overrides)


#: Simulation-shape departures from the base block, per portfolio.  Sourced
#: numbers never appear here — they come from ``sources.yaml`` above.
_SHAPE_OVERRIDES: dict[str, dict[str, object]] = {
    # A term loan is drawn down once, so the "utilisation" a bank sees is the
    # outstanding-to-sanction ratio and sits structurally lower.  (July 2026.)
    "msme_tl": {"base_util_mean": 0.35},
    # A cash-credit limit is interest-serviced monthly, not amortised.
    # SD-D8: base_util_mean is now sourced (utilisation.base_mean, ~0.85 — see
    # CHANNEL_PARAM_SOURCES/sources.yaml) rather than a shape override, so it
    # is NOT repeated here. Two shape knobs move alongside it, both to keep
    # the realised monthly `utilisation` column's mode at the sourced 0.85
    # rather than at an artefact of where a clip happens to sit
    # (src/realism.py's check_cc_utilisation_mode wants a mode in [0.75, 0.90]):
    #   - base_util_sd tightened (0.15 -> 0.05): a healthy, actively-drawn CC
    #     account is conventionally read as clustering near the EWS
    #     convention, not spread across the whole 0.2-0.9 band either side of
    #     it, which is realistic on its own terms as well as tighter.
    #   - util_bounds widened (ceiling 1.05 -> 1.2, matching the
    #     impossible_utilisation_over_120pct guard's own threshold so nothing
    #     crosses it): util_bounds clips the MONTHLY signal, after wobble, the
    #     calendar and this portfolio's own utilisation_idiosyncratic_sd
    #     (0.17) have all multiplied the baseline — at a mean of 0.85 those
    #     alone push ~13% of months past the old 1.05 ceiling, which piled up
    #     as a single artificial spike bigger than any genuine bin and put the
    #     computed MODE at ~1.07, not the 0.85 the baseline was actually drawn
    #     around. Widening the ceiling lets that natural right tail spread out
    #     instead of stacking on the boundary; the true peak (~0.80) then wins
    #     the histogram honestly.
    "msme_cc": {"interest_only": True, "base_util_sd": 0.05, "util_bounds": (0.02, 1.2)},
    # Housing: the salary gap leads, the balance floor breaks, then the EMI
    # bounces.  A mortgage borrower defends the mortgage longest, so the
    # collection shortfall is shallower and later than an unsecured product's.
    "housing": {
        "ltv_stress_haircut": 0.16,
        "collection_lead_months": 7,
        "collection_shortfall_gain": 0.52,
        "bounce_slide_gain": 0.55,
        "inflow_elasticity": 0.45,
        "quiet_transient_share": 0.16,
    },
    # Education: the moratorium end is the event; the borrower simply stops.
    "education": {
        "collection_lead_months": 9,
        "collection_shortfall_gain": 0.78,
        "salary_elasticity": 0.60,
        "inflow_elasticity": 0.50,
    },
    # Agri/KCC: interest-serviced, seasonal, renewed annually.
    "agri": {
        "interest_only": True,
        "base_util_mean": 0.68,
        "base_util_sd": 0.17,
        "collection_lead_months": 10,
        "collection_shortfall_gain": 0.70,
        "inflow_elasticity": 0.60,
        "util_lead_months": 11,
        "quiet_transient_share": 0.24,
    },
    # Retail-unsecured: stacking starts early, the buffer is thin, and the
    # borrower walks away fastest of the eight.
    "retail_unsecured": {
        "collection_lead_months": 7,
        "collection_shortfall_gain": 0.80,
        "minbal_slide_gain": 0.55,
        "bounce_slide_gain": 0.60,
        "balance_elasticity": 0.95,
        "quiet_transient_share": 0.22,
    },
    # LAP: secured and slow, but the rental dip and the LTV drift lead by a
    # long way because both are re-measured, not reported by the borrower.
    "lap": {
        # a distress sale of commercial or mixed-use property clears well below
        # the valuation a lender carries it at
        "ltv_stress_haircut": 0.32,
        "collection_lead_months": 8,
        "collection_shortfall_gain": 0.58,
        "inflow_elasticity": 0.50,
    },
    # Auto: small ticket, short tenor, the vehicle stops moving first.
    "auto": {
        # a vehicle has an active resale market, so the distress discount is
        # small next to the depreciation already in ltv_collateral_drift_pa
        "ltv_stress_haircut": 0.10,
        "collection_lead_months": 6,
        "collection_shortfall_gain": 0.70,
        "balance_elasticity": 0.85,
    },
}


def _build_registry() -> dict[str, Portfolio]:
    """Assemble the registry from ``sources.yaml``.

    Returns:
        Registry key -> :class:`Portfolio`, in the order the YAML declares.
    """
    problems = sources.validate()
    if problems:
        raise ValueError("sources.yaml is malformed:\n  " + "\n  ".join(problems))

    built: dict[str, Portfolio] = {}
    for key in sources.portfolio_keys():
        channels = tuple(sources.value(f"portfolios.{key}.channels"))
        band = tuple(sources.value(f"portfolios.{key}.annual_default_rate_band"))
        built[key] = Portfolio(
            key=key,
            code=sources.value(f"portfolios.{key}.contract_code"),
            label=_LABELS[key],
            loan_type=sources.value(f"portfolios.{key}.loan_type"),
            share=float(sources.value(f"portfolios.{key}.account_share")),
            channels=channels,
            params=_channel_params(key, channels),
            population=PortfolioPopulation.from_sources(key),
            risk_offset=float(sources.value(f"portfolios.{key}.risk_offset")),
            default_rate_band=(float(band[0]), float(band[1])),
            silent_share=float(
                sources.value(f"portfolios.{key}.noise.silent_default_share")),
            npa_recognition_months=NPA_RECOGNITION_MONTHS.get(key, 0),
        )
    return built


#: Recognition lag over and above the 90-DPD test, by registry key.  Only
#: `agri` differs, and only because RBI's IRAC norms say so: a short-duration
#: crop advance is NPA when principal or interest has been overdue for TWO CROP
#: SEASONS, not ninety days.  The mix models kharif and rabi as half-years, so
#: two seasons is ~12 months.  Every other portfolio here is an ordinary term
#: loan or CC/OD and is governed by 90 DPD (CC/OD by the "out of order for more
#: than 90 days" test), so its lag is zero.
#:
#: Read only when `GeneratorConfig.portfolio_npa_rules` is True.  This is a
#: SIMULATOR setting, not a classification engine: nothing in DRISHTi assigns a
#: regulatory classification, and the bank must confirm its own policy before
#: any of this is represented as one.
NPA_RECOGNITION_MONTHS: dict[str, int] = {"agri": 12}


#: human labels for the CLI's progress lines
_LABELS: dict[str, str] = {
    "msme_cc": "MSME cash credit / overdraft",
    "msme_tl": "MSME term loan",
    "housing": "Housing loan",
    "education": "Education loan",
    "agri": "Agriculture (Kisan Credit Card)",
    "retail_unsecured": "Personal loan (unsecured)",
    "lap": "Loan against property",
    "auto": "Vehicle loan",
}


PORTFOLIOS: dict[str, Portfolio] = _build_registry()


def registry(keys: tuple[str, ...] | None = None) -> dict[str, Portfolio]:
    """The registry, optionally restricted to a subset of portfolios.

    Restriction is how the equivalence suite regenerates *only* the two MSME
    portfolios and compares them against the July 2026 reference: nothing else
    in the package needs to know that some portfolios are absent.

    Args:
        keys: registry keys to keep, in registry order.  ``None`` keeps all.

    Returns:
        A new mapping; the module-level :data:`PORTFOLIOS` is never mutated.

    Raises:
        KeyError: if a requested key is not registered.
    """
    if keys is None:
        return dict(PORTFOLIOS)
    unknown = [k for k in keys if k not in PORTFOLIOS]
    if unknown:
        raise KeyError(f"unknown portfolio keys: {unknown}")
    return {k: PORTFOLIOS[k] for k in keys}


def portfolio_mix(
    selected: dict[str, Portfolio] | None = None,
) -> tuple[list[Portfolio], list[float]]:
    """Registry order plus normalised population weights.

    Args:
        selected: the registry to use; defaults to the full one.

    Returns:
        ``(portfolios, shares)`` with ``shares`` summing to 1.
    """
    items = list((selected if selected is not None else PORTFOLIOS).values())
    total = sum(p.share for p in items)
    return items, [p.share / total for p in items]


# --------------------------------------------------------------------------- #
# Shared population block — the latent risk scorecard and the stress shape.
# Everything here is common to all eight portfolios by design: the LATENT is
# one process, and only the observation channels differ.
# --------------------------------------------------------------------------- #
def _level_order(attribute: str, portfolio_field: str) -> tuple[str, ...]:
    """Stable category order for one attribute across the whole registry.

    The shared mix's keys come first — that is what keeps the July 2026 MSME
    category codes and ``accounts_static.csv`` stable — followed by any extra
    level a portfolio introduces, in registry order.

    Args:
        attribute: dotted path of the shared mix in ``sources.yaml``.
        portfolio_field: matching field name on :class:`PortfolioPopulation`.

    Returns:
        The ordered level names.
    """
    order: list[str] = list(sources.value(f"shared.{attribute}"))
    for portfolio in PORTFOLIOS.values():
        assert portfolio.population is not None
        for level in getattr(portfolio.population, portfolio_field):
            if level not in order:
                order.append(level)
    return tuple(order)


@dataclass(frozen=True)
class PopulationMix:
    """What every portfolio shares: the risk scorecard and the stress shape."""

    # ---- category universes (order fixes the panel's categorical codes) --- #
    sector_levels: tuple[str, ...] = field(
        default_factory=lambda: _level_order("sectors", "sectors"))
    region_levels: tuple[str, ...] = field(
        default_factory=lambda: _level_order("regions", "regions"))
    qualification_levels: tuple[str, ...] = field(
        default_factory=lambda: _level_order("qualifications", "qualifications"))
    age_group_levels: tuple[str, ...] = field(
        default_factory=lambda: _level_order("age_groups", "age_groups"))
    constitution_levels: tuple[str, ...] = field(
        default_factory=constitution_levels)
    city_tier_levels: tuple[str, ...] = field(
        default_factory=lambda: _level_order("city_tiers", "city_tiers"))

    # ---- sourced lookups -------------------------------------------------- #
    sector_risk: dict[str, float] = field(
        default_factory=lambda: dict(sources.value("shared.sector_risk")))
    nic_groups: dict[str, str | None] = field(
        default_factory=lambda: dict(sources.value("shared.nic_groups")))
    states_within_region: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            region: dict(states)
            for region, states in sources.value("shared.states_within_region").items()
        })

    bureau_missing_share: float = field(
        default_factory=lambda: float(sources.value("shared.bureau.missing_share")))
    bureau_score_bounds: tuple[float, float] = field(
        default_factory=lambda: tuple(sources.value("shared.bureau.score_bounds")))
    bureau_score_mean: float = field(
        default_factory=lambda: float(sources.value("shared.bureau.score_mean")))
    bureau_score_sd: float = field(
        default_factory=lambda: float(sources.value("shared.bureau.score_sd")))
    bureau_risk_gain: float = field(
        default_factory=lambda: float(sources.value("shared.bureau.risk_gain")))
    bureau_stress_drop: float = field(
        default_factory=lambda: float(sources.value("shared.bureau.stress_drop")))
    bureau_report_lag_months: int = field(
        default_factory=lambda: int(sources.value("shared.bureau.report_lag_months")))
    #: SD-D4: a bureau pull is a paid enquiry run on a cycle, so between pulls
    #: the bank carries the score it last saw
    bureau_refresh_months: int = field(
        default_factory=lambda: int(sources.value("shared.bureau.refresh_months")))
    bureau_report_noise_sd: float = field(
        default_factory=lambda: float(sources.value("shared.bureau.report_noise_sd")))

    kharif_harvest_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(sources.value("shared.seasonality.kharif_harvest_months")))
    rabi_harvest_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(sources.value("shared.seasonality.rabi_harvest_months")))

    balance_months_of_emi: float = field(
        default_factory=lambda: float(sources.value("shared.balance.months_of_emi")))
    balance_months_of_emi_sd: float = field(
        default_factory=lambda: float(sources.value("shared.balance.months_of_emi_sd")))
    minimum_balance: float = field(
        default_factory=lambda: float(sources.value("shared.balance.minimum_balance")))

    # ---- SD-D4: the shared half of the realism block ---------------------- #
    #: a silent defaulter's whole slide is squeezed into this many months, so
    #: the chain has no room to lead the arrears
    silent_onset_bounds: tuple[int, int] = field(
        default_factory=lambda: tuple(
            sources.value("shared.silent_default.onset_months_bounds")))
    silent_severity_floor: float = field(
        default_factory=lambda: float(
            sources.value("shared.silent_default.severity_floor")))
    #: book-wide target the eight per-portfolio silent shares weight to
    silent_book_share: float = field(
        default_factory=lambda: float(sources.value("shared.silent_default.share")))

    #: statement-feed gaps: MAR by construction, drawn from their own stream
    statement_gap_share: float = field(
        default_factory=lambda: float(
            sources.value("shared.missingness.statement_gap_share")))
    statement_gap_length_bounds: tuple[int, int] = field(
        default_factory=lambda: tuple(
            sources.value("shared.missingness.statement_gap_length_bounds")))

    #: calendar months each confounder shape fires in
    festival_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(sources.value("shared.confounders.festival_months")))
    post_festival_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            sources.value("shared.confounders.post_festival_months")))
    quarter_end_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            sources.value("shared.confounders.quarter_end_months")))
    fiscal_year_start_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            sources.value("shared.confounders.fiscal_year_start_months")))
    monsoon_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(sources.value("shared.confounders.monsoon_months")))
    bonus_months: tuple[int, ...] = field(
        default_factory=lambda: tuple(sources.value("shared.confounders.bonus_months")))

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
    #: months of NPA exposure the scorecard was calibrated against (the July
    #: 2026 build's 36-month window, less the 6 months before an NPA can occur).
    #: :func:`generator.latent.draw_population` rescales the window probability
    #: to this reference so the ANNUAL default rate does not move with
    #: ``--months``.
    hazard_reference_months: int = 30
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

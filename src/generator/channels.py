"""Observation channels — how the shared latent stress becomes bank-visible.

:mod:`generator.latent` decides *that* an account is deteriorating and how
hard.  This module decides *what the bank sees*, and it is the only place the
two are connected.  Every function here takes a per-portfolio
:class:`~generator.portfolios.ChannelParams` block and the portfolio's declared
channels, so a portfolio brings its own instruments rather than editing shared
code.

The ordered-deterioration causality is the whole thesis of the dataset.  It is
preserved exactly as the original simulator encoded it for the MSME channels…

===========================  ==================================================
months before NPA            what moves
===========================  ==================================================
onset (median ~13) to NPA    cash inflow and GST sales fall, transactions thin
<= 10                        credit-limit utilisation creeps up
<= 9                         adverse filing remarks start appearing
<= 8                         the demand stops being met in full (part-payment)
<= 6                         cheque bounces and min-balance breaches
<= 3                         days-past-due finally rises (15 -> 38 -> 68)
===========================  ==================================================

…and extended to the eight portfolio-specific chains SD-D3 requires:

=================  ==========================================================
portfolio          chain
=================  ==========================================================
MSME-CC            GST sales -> utilisation -> bounces -> DPD
MSME-TL            EMI coverage -> part-payment -> DPD
Housing            salary gap -> balance-floor breach -> EMI bounce -> DPD
Education          moratorium end -> payment stop -> DPD
Agri / KCC         harvest miss (seasonal) -> renewal overdue -> DPD
Retail-Unsecured   EMI stacking -> min-balance -> bounce -> DPD
LAP                LTV breach + rental dip -> DPD
Auto               commute spend + salary gap -> DPD
=================  ==========================================================

Every chain ends at DPD and every chain *starts* somewhere the borrower cannot
hide and has not yet defaulted — which is what forces the model to learn
genuine twelve-month-ahead early warning rather than near-term arrears.

Everything is computed as ``(N, M)`` float/bool arrays for one portfolio block
at a time.  The only Python-level loops are over ``M`` (36-48 months) and over
the rolling-window offsets (at most 6), never over accounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import sources
from .latent import StressPath
from .noise import (
    TransientStress,
    ar1_noise,
    bernoulli,
    duplicate_batches,
    reported_with_lag,
    round_to,
    transient_stress,
)
from .portfolios import ChannelParams, PopulationMix, Portfolio

__all__ = [
    "CHANNEL_COLUMNS",
    "SHARED_COLUMNS",
    "Baselines",
    "BlockInputs",
    "Channels",
    "confounder_profile",
    "draw_baselines",
    "link_loadings",
    "seasonal_profile",
    "simulate_channels",
    "trailing_features",
]

#: which panel columns each declared observation channel owns.  A portfolio
#: that lists a channel in ``absent_channels`` gets these columns blanked.
CHANNEL_COLUMNS: dict[str, tuple[str, ...]] = {
    "utilisation": ("utilisation", "util_avg_3m", "util_max_6m",
                    "months_over_90pct_util_6m"),
    "cash_flow": ("inflow", "inflow_trend_3m", "inflow_vs_6m_avg"),
    "gst": ("gst_sales", "sales_trend_3m"),
    "transactions": ("txn_count", "txn_drop_flag"),
    "repayment": ("dpd", "bounce", "minbal_breach", "dpd_max_6m", "times_late_6m",
                  "bounces_6m", "minbal_breach_6m"),
    "adverse": ("adverse_remark", "adverse_remark_6m"),
    "drawing_power": ("drawing_power",),
    "salary": ("salary_credit", "salary_vs_6m_avg", "salary_gap_6m"),
    "emi_stacking": ("other_bank_emi", "emi_burden_ratio"),
    "ltv": ("ltv", "ltv_vs_schedule"),
    "rental": ("rental_income", "rental_vs_6m_avg"),
    "harvest": ("crop_receipt", "crop_receipt_vs_norm", "renewal_overdue_months"),
    "moratorium": ("moratorium_active", "months_since_moratorium_end"),
    "commute": ("commute_spend", "commute_vs_6m_avg"),
}

#: Columns every portfolio carries, whatever its channels — the common spine a
#: single model needs.  Blanking never touches these.
SHARED_COLUMNS: tuple[str, ...] = (
    "outstanding", "demanded_amount", "collected_amount", "collection_ratio",
    "collection_ratio_3m", "balance", "min_balance_6m", "bureau_score",
)


# --------------------------------------------------------------------------- #
# Rolling-window primitives over axis 1 of an (N, M) array
# --------------------------------------------------------------------------- #
def _rolling_sum(x: np.ndarray, window: int) -> np.ndarray:
    """Trailing sum over ``window`` months, inclusive of the current month."""
    n, m = x.shape
    cumulative = np.zeros((n, m + 1), dtype=np.float64)
    np.cumsum(x, axis=1, out=cumulative[:, 1:])
    lo = np.maximum(np.arange(m) - window + 1, 0)
    return cumulative[:, 1:] - cumulative[:, lo]


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    """Trailing mean, short windows averaged over the months available."""
    counts = np.minimum(np.arange(1, x.shape[1] + 1), window)
    return _rolling_sum(x, window) / counts


def _rolling_max(x: np.ndarray, window: int) -> np.ndarray:
    """Trailing maximum, inclusive of the current month."""
    out = x.copy()
    for k in range(1, window):
        np.maximum(out[:, k:], x[:, :-k], out=out[:, k:])
    return out


def _rolling_min(x: np.ndarray, window: int) -> np.ndarray:
    """Trailing minimum, inclusive of the current month."""
    out = x.copy()
    for k in range(1, window):
        np.minimum(out[:, k:], x[:, :-k], out=out[:, k:])
    return out


def _lag(x: np.ndarray, months: int) -> np.ndarray:
    """Value ``months`` months ago, holding the first observation before t=0."""
    out = np.empty_like(x)
    out[:, :months] = x[:, :1]
    out[:, months:] = x[:, :-months]
    return out


def _pct_change(now: np.ndarray, then: np.ndarray) -> np.ndarray:
    """Relative change, floored at a rupee-1 denominator like the original."""
    return (now - then) / np.maximum(then, 1.0)


def _ratio(now: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Ratio against a per-account base, floored so a zero base cannot divide."""
    return now / np.maximum(base, 1.0)


# --------------------------------------------------------------------------- #
# Per-account baselines
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Baselines:
    """Per-account healthy levels the monthly signals oscillate around."""

    util: np.ndarray        # (N,) credit-limit utilisation
    inflow: np.ndarray      # (N,) monthly banked inflow (rupees)
    sales: np.ndarray       # (N,) monthly declared GST sales (rupees)
    txn: np.ndarray         # (N,) monthly transaction count
    wobble: np.ndarray      # (N,) AR(1) noise amplitude


def draw_baselines(
    rng: np.random.Generator, sanctioned: np.ndarray, params: ChannelParams
) -> Baselines:
    """Draw each account's healthy operating level for this portfolio.

    Args:
        rng: source of randomness.
        sanctioned: ``(N,)`` sanctioned limit in rupees.
        params: the portfolio's channel parameters.

    Returns:
        The per-account baselines.
    """
    n = sanctioned.shape[0]
    util = np.clip(
        rng.normal(params.base_util_mean, params.base_util_sd, n), *params.base_util_bounds
    )
    inflow_ratio = np.clip(
        rng.normal(params.inflow_ratio_mean, params.inflow_ratio_sd, n),
        *params.inflow_ratio_bounds,
    )
    inflow = sanctioned * inflow_ratio / 12.0
    sales_ratio = np.clip(
        rng.normal(params.sales_ratio_mean, params.sales_ratio_sd, n),
        *params.sales_ratio_bounds,
    )
    # transaction counts are whole transactions, truncated like the original
    txn = np.trunc(
        np.clip(rng.normal(params.txn_mean, params.txn_sd, n), *params.txn_bounds)
    )
    wobble = np.clip(
        rng.normal(params.wobble_mean, params.wobble_sd, n), *params.wobble_bounds
    )
    return Baselines(
        util=util, inflow=inflow, sales=inflow * sales_ratio, txn=txn, wobble=wobble,
    )


# --------------------------------------------------------------------------- #
# Monthly signals
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BlockInputs:
    """Static per-account facts one portfolio block needs to observe itself."""

    sanctioned: np.ndarray        # (N,) rupees
    tenor_months: np.ndarray      # (N,)
    rate_pa: np.ndarray           # (N,) annual rate as a fraction
    vintage_months_0: np.ndarray  # (N,) months on book at panel month 0
    bureau_score_0: np.ndarray    # (N,) float, NaN where there is no file
    #: calendar month (1-12) of each panel month, shape ``(M,)``
    calendar_month: np.ndarray


@dataclass(frozen=True)
class Channels:
    """The raw monthly signals a bank observes, as ``(N, M)`` arrays."""

    utilisation: np.ndarray
    inflow: np.ndarray
    gst_sales: np.ndarray
    txn: np.ndarray
    dpd: np.ndarray
    bounce: np.ndarray            # int
    minbal_breach: np.ndarray     # int
    adverse_remark: np.ndarray    # int
    #: every SD-D3 column, keyed by panel column name.  Shared columns are
    #: always present; a channel's columns appear only if the portfolio
    #: declares that channel.
    extra: dict[str, np.ndarray] = field(default_factory=dict)
    #: SD-D4 ground truth, never a panel column: which months of which healthy
    #: accounts were inside a transient stress episode, and which of those
    #: episodes went past due before curing.  ``accounts_static.csv`` carries
    #: the per-account summary so the hard negatives can be tested for.
    transient_episode: np.ndarray | None = None
    transient_arrears: np.ndarray | None = None


def seasonal_profile(calendar_month: np.ndarray, params: ChannelParams,
                     mix: PopulationMix) -> np.ndarray:
    """Crop-receipt seasonality, normalised to an annual mean of 1.

    Kharif is harvested from September-October and sold through
    October-November; rabi is harvested April to June.  Those two windows carry
    the year's cash; the rest of the year runs on the off-season floor.

    Args:
        calendar_month: ``(M,)`` calendar month (1-12) of each panel month.
        params: supplies the harvest multiple and the off-season floor.
        mix: supplies the sourced kharif and rabi harvest months.

    Returns:
        ``(M,)`` multiplier with mean 1 over a full twelve-month cycle.
    """
    harvest = set(mix.kharif_harvest_months) | set(mix.rabi_harvest_months)
    cycle = np.array([
        params.harvest_receipt_multiple if month in harvest else params.harvest_off_season_floor
        for month in range(1, 13)
    ])
    cycle = cycle / cycle.mean()
    return cycle[calendar_month - 1]


#: days-past-due a cured (transient) episode is capped at.  It has to stay
#: strictly below the 90-day NPA threshold: a healthy account that touched 90
#: would be dropped by the still-standard row filter, which would quietly
#: delete the hardest negatives in the book instead of showing them.
TRANSIENT_DPD_CAP = 87.0

#: The SHAPE of each calendar confounder, as a weight on the portfolio's own
#: amplitude (``ChannelParams.season_*_amp``).  The windows themselves — which
#: months are festival, monsoon, quarter-end — are sourced in ``sources.yaml``;
#: the relative weights are a simulation choice and live here, next to the code
#: that reads them.
#:
#: These are CONFOUNDERS, not stress.  Every one of them makes a healthy
#: account move in the same direction a sliding one does: turnover falls in
#: December because the festival is over, a salary reads short in November
#: because October carried a bonus, a limit is drawn down in September because
#: the borrower is stocking up.  A model that has learned "inflow below its
#: six-month average means trouble" has to learn the calendar too.
CONFOUNDER_SHAPES: dict[str, dict[str, float]] = {
    "inflow": {"festival": 1.0, "post_festival": -0.55, "quarter_end": 0.35,
               "fiscal_year_start": -0.30, "monsoon": -0.20},
    # a KCC account's banked inflow follows the crop, not the shopping calendar
    "crop_inflow": {"harvest": 1.0, "monsoon": -0.35},
    "utilisation": {"pre_festival": 1.0, "quarter_end": -0.60},
    "salary": {"bonus": 1.0},
    "commute": {"festival": 1.0, "monsoon": -0.70},
}


def _confounder_windows(mix: PopulationMix) -> dict[str, tuple[int, ...]]:
    """Calendar months each confounder shape fires in, from ``sources.yaml``."""
    return {
        "festival": mix.festival_months,
        "post_festival": mix.post_festival_months,
        "quarter_end": mix.quarter_end_months,
        "fiscal_year_start": mix.fiscal_year_start_months,
        "monsoon": mix.monsoon_months,
        "bonus": mix.bonus_months,
        # stocking up happens two months before the festival sells through
        "pre_festival": tuple(((month - 3) % 12) + 1 for month in mix.festival_months),
        "harvest": tuple(
            sorted(set(mix.kharif_harvest_months) | set(mix.rabi_harvest_months))
        ),
    }


def confounder_profile(
    calendar_month: np.ndarray,
    params: ChannelParams,
    mix: PopulationMix,
    crop_calendar: bool,
) -> dict[str, np.ndarray]:
    """Per-signal calendar multipliers, each with an annual mean of exactly 1.

    Normalising to mean 1 is what makes these confounders rather than a level
    shift: over a full year the portfolio's inflow, utilisation, salary and
    commute spend are unchanged, and only their *within-year* shape moves.

    Args:
        calendar_month: ``(M,)`` calendar month (1-12) of each panel month.
        params: supplies this portfolio's four amplitudes.
        mix: supplies the sourced calendar windows.
        crop_calendar: True for a portfolio whose cash follows the harvest
            rather than the festival and quarter-end calendar.

    Returns:
        ``{"inflow", "utilisation", "salary", "commute"} -> (M,) multiplier``.
    """
    windows = _confounder_windows(mix)
    amplitudes = {
        "inflow": params.season_inflow_amp,
        "utilisation": params.season_util_amp,
        "salary": params.season_salary_amp,
        "commute": params.season_commute_amp,
    }
    out: dict[str, np.ndarray] = {}
    for signal, amplitude in amplitudes.items():
        shape_key = "crop_inflow" if (signal == "inflow" and crop_calendar) else signal
        cycle = np.ones(12)
        if amplitude:
            for window, weight in CONFOUNDER_SHAPES[shape_key].items():
                months = np.array(windows[window], dtype=np.int64) - 1
                cycle[months] += amplitude * weight
        cycle = np.maximum(cycle, 0.05)
        out[signal] = (cycle / cycle.mean())[calendar_month - 1]
    return out


def simulate_channels(
    rng: np.random.Generator,
    extra_rng: np.random.Generator,
    noise_rng: np.random.Generator,
    portfolio: Portfolio,
    baselines: Baselines,
    inputs: BlockInputs,
    stress: StressPath,
    mix: PopulationMix,
    months: int,
    noise: bool = True,
) -> Channels:
    """Turn baselines plus latent stress into observed monthly signals.

    Args:
        rng: the July 2026 channels stream — every legacy draw, in order.
        extra_rng: a separate stream for the SD-D3 channels, so adding them
            leaves the MSME channels bit-identical.
        noise_rng: a third stream, for SD-D4 only.  Every confounder, every
            instrument error and every extension to the transient episodes
            draws from here, so ``noise=False`` leaves the other two untouched.
        portfolio: the portfolio being simulated (supplies its channels).
        baselines: per-account healthy levels.
        inputs: static per-account facts (ticket, tenor, rate, vintage, bureau).
        stress: the shared latent stress path for the same accounts.
        mix: shared sourced constants (seasonality, balance floor, bureau).
        months: observation window ``M``.
        noise: SD-D4 master switch — seasonal confounders, measurement noise
            and the hard-negative extensions.  Default ON.

    Returns:
        The observed channels for this portfolio block.
    """
    params = portfolio.params
    n = baselines.util.shape[0]
    shape = (n, months)
    season = confounder_profile(
        inputs.calendar_month, params, mix, portfolio.has("harvest")
    )
    # SD-D4, drawn FIRST so it is the same for a given account whatever else
    # the noise stream is asked for later: which of this borrower's
    # instruments their trouble actually reaches, and how hard.
    loading = link_loadings(noise_rng, n, portfolio, mix) if noise else {}
    # A farmer's banked inflow IS their crop receipt.  The July panel gave the
    # crop receipt a season and the inflow a clean one, so a KCC account's
    # turnover was predictable to the rupee while its receipts swung — which
    # made `inflow` a far better instrument on this book than a bank has.  One
    # draw, used by both.
    crop_yield = (
        _crop_year_yield(noise_rng, n, inputs.calendar_month, params)
        if noise and portfolio.has("harvest")
        else None
    )

    # ---- 1. healthy conduct: AR(1) wobble around each baseline ----------- #
    wobble = ar1_noise(rng, baselines.wobble, months, params.ar1_phi)
    inflow_shock = rng.normal(0.0, baselines.wobble[:, None], shape)
    sales_shock = rng.normal(0.0, baselines.wobble[:, None], shape)

    # SD-D4: the calendar moves a healthy account in the same direction stress
    # does.  It is applied to the BASELINE, before any stress, so a seasonal
    # dip is never a stress response and a stressed month still carries its
    # season — which is exactly the identification problem a real analyst has.
    calendar_inflow = season["inflow"][None, :] if noise else 1.0
    calendar_util = season["utilisation"][None, :] if noise else 1.0
    # transactions follow turnover, but only half as hard: a quiet month still
    # carries the standing instructions, the rent and the salary
    calendar_txn = 1.0 + 0.5 * (season["inflow"][None, :] - 1.0) if noise else 1.0

    util = np.clip(
        baselines.util[:, None] * (1.0 + wobble) * calendar_util, *params.util_bounds
    )
    inflow = np.maximum(
        baselines.inflow[:, None] * (1.0 + params.inflow_wobble_gain * wobble + inflow_shock)
        * calendar_inflow,
        params.inflow_floor,
    )
    sales = np.maximum(
        baselines.sales[:, None] * (1.0 + params.inflow_wobble_gain * wobble + sales_shock)
        * calendar_inflow,
        params.inflow_floor,
    )
    txn = np.maximum(
        baselines.txn[:, None] * (1.0 + params.txn_wobble_gain * wobble) * calendar_txn,
        params.txn_floor,
    )
    if crop_yield is not None:
        inflow = np.maximum(inflow * crop_yield, params.inflow_floor)
    if noise:
        # Idiosyncratic month-to-month variation that is not stress and not the
        # calendar: receivables landing in clumps, a limit drawn for a stock
        # purchase and swept when the invoice clears.  The July build's healthy
        # accounts moved about five percent a month, which is why
        # `inflow_vs_6m_avg` and `utilisation` were near-perfect instruments.
        inflow = np.maximum(
            inflow * _lognormal_noise(noise_rng, shape, params.inflow_idio_sd),
            params.inflow_floor,
        )
        if portfolio.has("utilisation") and params.utilisation_idio_sd > 0:
            util = np.clip(
                util * _lognormal_noise(noise_rng, shape, params.utilisation_idio_sd),
                *params.util_bounds,
            )

    bounce = bernoulli(rng, shape, params.bounce_rate)
    minbal = bernoulli(rng, shape, params.minbal_rate)
    adverse = np.zeros(shape, dtype=bool)
    dpd = np.zeros(shape, dtype=np.float64)

    # ---- 2. hard negatives: transient stress on healthy accounts --------- #
    healthy = ~stress.post_npa.any(axis=1)
    episodes = transient_stress(rng, healthy, months, params, noise)
    util = np.where(
        episodes.episode,
        np.clip(util * params.transient_util_mult, *params.transient_util_bounds),
        util,
    )
    inflow = np.where(episodes.episode, inflow * params.transient_inflow_mult, inflow)
    if noise:
        # a bad quarter shows in the GST return too — the July build moved the
        # banked inflow during an episode and left declared turnover alone,
        # which made `sales_trend_3m` a signal only a defaulter could trip
        sales = np.where(
            episodes.episode, sales * params.transient_income_mult, sales
        )
    bounce |= episodes.bounce

    # ---- 3. ordered deterioration on the way to NPA ---------------------- #
    slide, decline, mtn = stress.in_slide, stress.decline, stress.months_to_npa
    felt = lambda channel: (                                          # noqa: E731
        decline * loading[channel] if channel in loading else decline
    )

    inflow = np.where(
        slide,
        inflow * np.maximum(
            params.inflow_decay_floor, 1.0 - params.inflow_elasticity * felt("cash_flow")),
        inflow,
    )
    sales = np.where(
        slide,
        sales * np.maximum(
            params.sales_decay_floor, 1.0 - params.sales_elasticity * felt("gst")),
        sales,
    )
    txn = np.where(
        slide,
        txn * np.maximum(
            params.txn_decay_floor, 1.0 - params.txn_elasticity * felt("transactions")),
        txn,
    )
    util_creep = slide & (mtn <= params.util_lead_months)
    util_felt = felt("utilisation")
    util = np.where(
        util_creep,
        np.clip(
            util * (1.0 + params.util_slide_gain * util_felt)
            + params.util_slide_shift * util_felt,
            *params.util_slide_bounds,
        ),
        util,
    )
    bounce |= (
        slide
        & (mtn <= params.bounce_lead_months)
        & (rng.random(shape) < params.bounce_slide_base + params.bounce_slide_gain * decline)
    )
    minbal |= (
        slide
        & (mtn <= params.minbal_lead_months)
        & (rng.random(shape) < params.minbal_slide_base + params.minbal_slide_gain * decline)
    )
    adverse |= (
        slide
        & (mtn <= params.adverse_lead_months)
        & (rng.random(shape)
           < params.adverse_slide_base + params.adverse_slide_gain * felt("adverse"))
    )

    # days-past-due rises last, on a fixed ladder plus noise
    ladder = np.zeros(shape, dtype=np.float64)
    for months_out, days in params.dpd_ladder:
        ladder = np.where(slide & (mtn == months_out), days, ladder)
    arrears = ladder > 0
    dpd = np.where(
        arrears,
        np.maximum(0.0, ladder + rng.normal(0.0, params.dpd_noise_sd, shape)),
        dpd,
    )

    # ---- 3b. SD-D4: a bounced instalment IS days past due ---------------- #
    # The July build let an account bounce a payment and stay at 0 DPD, which
    # made "the account is late" a near-perfect classifier.  In a real Indian
    # retail book a failed NACH mandate is routine, most of them cure, and
    # RBI's SMA-0 bucket is full of accounts that are going nowhere near NPA.
    if noise:
        uncured = bounce & (noise_rng.random(shape) < params.bounce_uncured_share)
        rungs = np.asarray(params.bounce_dpd_ladder, dtype=np.float64)
        run = np.clip(_consecutive(uncured), 0, rungs.shape[0] - 1)
        dpd = np.maximum(
            dpd,
            np.clip(
                rungs[run] + np.where(
                    run > 0, noise_rng.normal(0.0, params.dpd_noise_sd, shape), 0.0),
                0.0,
                TRANSIENT_DPD_CAP,
            ),
        )

    # ---- 3c. SD-D4: the hard negatives that actually go past due --------- #
    # A share of transient episodes reaches SMA-1 or SMA-2 and then CURES the
    # month the episode ends.  These rows carry a zero label with a 60-day
    # arrears history, which is the single most useful negative in the book:
    # without them "the account is late" separates perfectly, and a model that
    # has learned it is reading arrears rather than predicting them.
    if noise and episodes.arrears.any():
        rungs = np.asarray(params.transient_arrears_ladder, dtype=np.float64)
        position = np.clip(episodes.position, 0, rungs.shape[0] - 1)
        cured = np.where(
            episodes.arrears[:, None] & (episodes.position >= 0),
            rungs[position] + noise_rng.normal(0.0, params.dpd_noise_sd, shape),
            0.0,
        )
        dpd = np.maximum(dpd, np.clip(cured, 0.0, TRANSIENT_DPD_CAP))

    # ---- 4. at/after NPA (filtered out of the panel, kept for realism) --- #
    after = stress.post_npa
    if after.any():
        months_since = np.maximum(-stress.months_to_npa, 0)
        dpd = np.where(
            after,
            np.minimum(
                params.post_npa_dpd_cap,
                params.post_npa_dpd_base + months_since * params.post_npa_dpd_step,
            ),
            dpd,
        )
        util = np.where(
            after,
            np.clip(
                params.post_npa_util_mean
                + rng.normal(0.0, params.post_npa_util_sd, shape),
                *params.post_npa_util_bounds,
            ),
            util,
        )
        inflow = np.where(after, inflow * params.post_npa_inflow_mult, inflow)
        sales = np.where(after, sales * params.post_npa_sales_mult, sales)

    # ---- 4b. SD-D4: what the instrument reports, not what happened ------- #
    if noise:
        # A GST return is filed AFTER the month it describes, and a quarterly
        # filer surfaces two months late.  The lender's `gst_sales` for month t
        # is therefore the borrower's turnover in month t - lag — so the
        # earliest link of the MSME-CC chain reaches the bank blurred and late,
        # which is the single most optimistic thing the July panel assumed away.
        if portfolio.has("gst"):
            options = list(params.gst_lag_distribution)
            weights = np.array(
                [params.gst_lag_distribution[k] for k in options], dtype=np.float64
            )
            lag = np.asarray(options, dtype=np.int64)[
                noise_rng.choice(len(options), size=n, p=weights / weights.sum())
            ]
            sales = reported_with_lag(sales, lag)
        # a re-posted statement batch inflates one month's count and makes the
        # next one look like a collapse
        txn = txn * duplicate_batches(noise_rng, shape, params)

    # ---- 5. SD-D3: the shared spine and this portfolio's own instruments -- #
    extra = _simulate_extra(
        extra_rng, noise_rng, portfolio, baselines, inputs, stress, mix, months,
        utilisation=util, inflow=inflow, wobble=wobble, minbal=minbal,
        episodes=episodes, season=season, noise=noise, loading=loading,
        crop_yield=crop_yield,
    )
    minbal = extra.pop("_minbal")

    return Channels(
        utilisation=util,
        inflow=inflow,
        gst_sales=sales,
        txn=txn,
        dpd=dpd,
        bounce=bounce.astype(np.int64),
        minbal_breach=minbal.astype(np.int64),
        adverse_remark=adverse.astype(np.int64),
        extra=extra,
        transient_episode=episodes.episode,
        transient_arrears=episodes.arrears,
    )


def _amortising_emi(principal: np.ndarray, rate_pa: np.ndarray,
                    tenor: np.ndarray) -> np.ndarray:
    """Level instalment on a reducing-balance loan.

    Args:
        principal: ``(N,)`` sanctioned amount.
        rate_pa: ``(N,)`` annual rate as a fraction.
        tenor: ``(N,)`` tenor in months.

    Returns:
        ``(N,)`` monthly instalment.
    """
    monthly = rate_pa / 12.0
    growth = np.power(1.0 + monthly, tenor)
    return principal * monthly * growth / np.maximum(growth - 1.0, 1e-12)


def _scheduled_balance(principal: np.ndarray, rate_pa: np.ndarray, tenor: np.ndarray,
                       elapsed: np.ndarray) -> np.ndarray:
    """Outstanding principal after ``elapsed`` months of a level-EMI schedule."""
    monthly = (rate_pa / 12.0)[:, None]
    tenor_col = tenor[:, None]
    paid = np.minimum(elapsed, tenor_col)
    full = np.power(1.0 + monthly, tenor_col)
    so_far = np.power(1.0 + monthly, paid)
    return principal[:, None] * (full - so_far) / np.maximum(full - 1.0, 1e-12)


def _simulate_extra(
    rng: np.random.Generator,
    noise_rng: np.random.Generator,
    portfolio: Portfolio,
    baselines: Baselines,
    inputs: BlockInputs,
    stress: StressPath,
    mix: PopulationMix,
    months: int,
    *,
    utilisation: np.ndarray,
    inflow: np.ndarray,
    wobble: np.ndarray,
    minbal: np.ndarray,
    episodes: TransientStress,
    season: dict[str, np.ndarray],
    noise: bool,
    loading: dict[str, np.ndarray],
    crop_yield: np.ndarray | None,
) -> dict[str, np.ndarray]:
    """The shared spine plus whichever SD-D3 chains this portfolio declares.

    Args:
        rng: this portfolio's SD-D3 stream.
        noise_rng: this portfolio's SD-D4 stream — confounders, instrument
            error and the hard-negative extensions, and nothing else.
        portfolio: supplies the declared channels and the parameter block.
        baselines: per-account healthy levels (for the inflow scale).
        inputs: static per-account facts.
        stress: the shared latent stress path.
        mix: shared sourced constants.
        months: observation window ``M``.
        utilisation: the already-simulated utilisation, for interest-only demand.
        inflow: the already-simulated inflow, used as the balance's scale.
        wobble: the account's AR(1) conduct noise, reused so the new channels
            move with the same borrower rather than inventing a second person.
        minbal: the legacy min-balance mask, returned under ``_minbal`` with
            the balance-floor breaches of the salaried portfolios folded in.
        episodes: SD-D4's transient stress episodes.  Every income instrument
            here answers to them, which is what turns "a wobble in utilisation"
            into a hard negative that moves the portfolio's OWN first link.
        season: the per-signal calendar multipliers for this portfolio.
        noise: SD-D4 master switch.
        loading: per-account visibility of each channel's stress response
            (:func:`link_loadings`); an empty mapping means every link is
            fully visible, which is the ``noise=False`` behaviour.
        crop_yield: this crop year's yield-and-price multiplier, drawn once in
            :func:`simulate_channels` so the farmer's banked inflow and their
            crop receipt move together.

    Returns:
        Panel column name -> ``(N, M)`` array, plus the private ``_minbal`` key.
    """
    params = portfolio.params
    n = baselines.util.shape[0]
    shape = (n, months)
    grid = np.arange(months)[None, :]
    slide, decline, mtn = stress.in_slide, stress.decline, stress.months_to_npa
    felt = lambda channel: (                                          # noqa: E731
        decline * loading[channel] if channel in loading else decline
    )
    elapsed = inputs.vintage_months_0[:, None] + grid
    out: dict[str, np.ndarray] = {}

    # ---- demand: an instalment, or interest on what is drawn ------------- #
    emi = _amortising_emi(inputs.sanctioned, inputs.rate_pa, np.maximum(inputs.tenor_months, 1))
    if params.interest_only:
        demanded = utilisation * inputs.sanctioned[:, None] * (inputs.rate_pa / 12.0)[:, None]
        demand_scale = (
            params.base_util_mean * inputs.sanctioned * inputs.rate_pa / 12.0
        )
    else:
        demanded = np.broadcast_to(emi[:, None], shape).copy()
        demand_scale = emi

    # Education: nothing is demanded during the course moratorium, and the
    # first months of real demand are when this portfolio breaks.
    moratorium_end = np.zeros(n, dtype=np.int64)
    post_moratorium = np.zeros(shape, dtype=bool)
    if portfolio.has("moratorium"):
        lo, hi = params.moratorium_end_bounds
        moratorium_end = rng.integers(lo, hi + 1, size=n).astype(np.int64)
        active = grid < moratorium_end[:, None]
        since = grid - moratorium_end[:, None]
        post_moratorium = (since >= 0) & (since < params.moratorium_post_end_months)
        demanded = np.where(active, 0.0, demanded)
        out["moratorium_active"] = active.astype(np.int64)
        out["months_since_moratorium_end"] = np.clip(since, -48, 60).astype(np.int64)

    # ---- collection: the shared "money stopped arriving" signal ---------- #
    # SD-D4: the spine is never dark — money not arriving IS the event — but
    # how deeply a given borrower part-pays on the way down is theirs, not the
    # portfolio's.  Centred on 1, so the median defaulter is unchanged.
    spine = (
        noise_rng.uniform(*params.spine_strength_bounds, size=n)[:, None] if noise else 1.0
    )
    shortfall = np.where(
        slide & (mtn <= params.collection_lead_months),
        np.clip(params.collection_shortfall_gain * decline * spine, 0.0, 1.0),
        0.0,
    )
    if portfolio.has("moratorium"):
        shortfall = np.clip(
            shortfall + np.where(post_moratorium, params.moratorium_shock_gain * decline, 0.0),
            0.0, 1.0,
        )
    hiccup = rng.random(shape) < params.collection_short_rate
    shortfall = np.maximum(shortfall, np.where(hiccup, rng.uniform(0.05, 0.5, shape), 0.0))
    # SD-D4: an account inside a transient episode part-pays for real, at a
    # depth that overlaps a genuine slide's.  A single part-paid month does not
    # tell you which of the two you are looking at — and that is the point.
    if noise:
        shortfall = np.maximum(shortfall, episodes.shortfall)
    collected = np.maximum(
        0.0, demanded * (1.0 - shortfall) * (1.0 + rng.normal(0.0, params.collection_noise_sd, shape))
    )
    collected = np.minimum(collected, demanded)
    if noise:
        # A returned cheque, a failed mandate, a transfer that landed after the
        # cut-off: the month shows almost nothing collected and the next one
        # catches up.  Nothing was wrong with the borrower; the collection
        # ratio does not know that.
        reversal = noise_rng.random(shape) < params.payment_reversal_rate
        carried = np.zeros_like(collected)
        carried[:, 1:] = np.where(reversal[:, :-1], collected[:, :-1], 0.0)
        collected = np.where(
            reversal, collected * noise_rng.uniform(0.0, 0.12, shape), collected
        )
        collected = np.minimum(collected + carried, demanded)
        demanded = round_to(demanded, params.amount_rounding)
        collected = np.minimum(round_to(collected, params.amount_rounding), demanded)
    # nothing demanded means nothing missed: a moratorium month is not a default
    ratio = np.where(demanded > 0.0, _ratio(collected, demanded), 1.0)
    out["demanded_amount"] = demanded
    out["collected_amount"] = collected
    out["collection_ratio"] = ratio
    out["collection_ratio_3m"] = _rolling_mean(ratio, 3)

    # ---- outstanding ------------------------------------------------------ #
    if portfolio.has("utilisation"):
        # a revolving facility: what is outstanding is what has been drawn
        outstanding = utilisation * inputs.sanctioned[:, None]
    else:
        arrears = np.cumsum(demanded - collected, axis=1)
        outstanding = np.maximum(
            0.0,
            _scheduled_balance(
                inputs.sanctioned, inputs.rate_pa, np.maximum(inputs.tenor_months, 1), elapsed
            ) + arrears,
        )
    out["outstanding"] = outstanding

    # ---- salary (housing, education, retail-unsecured, auto) ------------- #
    salary = np.zeros(shape)
    if portfolio.has("salary"):
        multiple = np.clip(
            rng.normal(params.salary_multiple_mean, params.salary_multiple_sd, n),
            *params.salary_multiple_bounds,
        )
        salary = np.maximum(demand_scale * multiple, 1.0)[:, None] * (1.0 + 0.5 * wobble)
        salary = np.where(
            slide,
            salary * np.maximum(0.15, 1.0 - params.salary_elasticity * felt("salary")),
            salary,
        )
        missed = rng.random(shape) < np.where(
            slide, params.salary_miss_base + params.salary_miss_gain * felt("salary"),
            params.salary_miss_base,
        )
        if noise:
            # Variable pay, overtime, reimbursements, a bonus in October and an
            # increment in April.  The bonus matters out of proportion to its
            # size: it lifts the trailing six-month average, so every month
            # after it reads short against the borrower's own history.
            salary = salary * season["salary"][None, :] * _lognormal_noise(
                noise_rng, shape, params.salary_idio_sd
            )
            split = noise_rng.random(shape) < params.salary_split_rate
            salary = np.where(
                split, salary * noise_rng.uniform(0.35, 0.65, shape), salary
            )
            salary = np.where(
                episodes.episode, salary * params.transient_income_mult, salary
            )
            missed = missed | (
                episodes.episode
                & (noise_rng.random(shape) < params.transient_salary_miss_rate)
            )
        salary = np.where(missed, 0.0, salary)
        reference = _rolling_mean(salary, 6)
        out["salary_credit"] = salary
        out["salary_vs_6m_avg"] = _pct_change(salary, reference)
        out["salary_gap_6m"] = _rolling_sum(
            (salary < params.salary_gap_threshold * reference).astype(np.float64), 6
        )

    # ---- EMI stacking (retail-unsecured) ---------------------------------- #
    # Other lenders' instalments, read off account-aggregator narrations. The
    # burden is not just a correlate of stress: it is subtracted from the same
    # buffer the min-balance rule watches, which is what makes the chain
    # stacking -> min-balance -> bounce causal rather than merely coincident.
    burden_squeeze = np.zeros(shape)
    if portfolio.has("emi_stacking"):
        count0 = rng.poisson(params.other_emi_count_lambda, n).astype(np.float64)
        taken = slide & (
            rng.random(shape) < params.stress_new_emi_rate * felt("emi_stacking")
        )
        if noise:
            # a borrower bridging a transient squeeze borrows elsewhere too,
            # and the instalment does not go away when the squeeze does
            taken = taken | (
                episodes.episode
                & (noise_rng.random(shape) < params.transient_new_emi_rate)
            )
        count = count0[:, None] + np.cumsum(taken, axis=1)
        other = count * (params.other_emi_share_of_own * emi)[:, None]
        income = salary if portfolio.has("salary") else inflow
        burden = np.clip(
            (other + demanded) / np.maximum(income, 0.15 * demand_scale[:, None] + 1.0),
            0.0, 20.0,
        )
        out["other_bank_emi"] = other
        out["emi_burden_ratio"] = burden
        burden_squeeze = np.clip(burden - params.emi_burden_breach, 0.0, 0.9)

    # ---- balance, and the floor a salaried borrower breaches -------------- #
    buffer_months = np.maximum(
        rng.normal(mix.balance_months_of_emi, mix.balance_months_of_emi_sd, n), 0.05
    )
    balance_base = (
        demand_scale * buffer_months
        if portfolio.has("salary")
        else baselines.inflow * 0.25 * buffer_months
    )
    episode_drain = (
        np.where(episodes.episode, params.transient_balance_mult, 1.0) if noise else 1.0
    )
    balance = np.maximum(
        params.balance_floor,
        balance_base[:, None] * (1.0 + wobble)
        * np.where(slide, np.maximum(0.05, 1.0 - params.balance_elasticity * decline), 1.0)
        * (1.0 - burden_squeeze) * episode_drain,
    )
    if portfolio.has("salary"):
        # a missed salary drains the buffer the same month
        balance = np.where(salary <= 0.0, balance * 0.35, balance)
        minbal = minbal | (balance < mix.minimum_balance)
    out["balance"] = balance
    out["min_balance_6m"] = _rolling_min(balance, 6)
    out["_minbal"] = minbal

    # ---- bureau score, refreshed with a reporting lag --------------------- #
    lagged = _lag(decline, mix.bureau_report_lag_months)
    score = inputs.bureau_score_0[:, None] - mix.bureau_stress_drop * lagged
    if noise:
        # A portfolio-monitoring bureau pull costs money and is run on a cycle,
        # so the score on file is the one the LAST pull returned — stale by up
        # to a cycle, and moved between pulls by everything the borrower does
        # at other lenders.  A monthly bureau column is a step function.
        score = _held_between_refreshes(
            noise_rng, score, grid, mix.bureau_refresh_months
        ) + noise_rng.normal(0.0, mix.bureau_report_noise_sd, shape)
    out["bureau_score"] = np.clip(score, *mix.bureau_score_bounds)

    # ---- drawing power (cash credit, KCC) --------------------------------- #
    if portfolio.has("drawing_power"):
        cover = np.clip(rng.normal(params.dp_to_limit_mean, params.dp_to_limit_sd, n), 0.5, 1.0)
        power = inputs.sanctioned[:, None] * cover[:, None] * np.where(
            slide, np.maximum(0.2, 1.0 - params.dp_squeeze_gain * felt("drawing_power")), 1.0
        )
        if noise:
            # computed off a stock-and-book-debt statement the borrower files
            # on their own schedule, and held flat until the next one
            power = _held_between_refreshes(
                noise_rng, power, grid, params.dp_refresh_months
            ) * _lognormal_noise(noise_rng, shape, params.dp_report_noise_sd)
        out["drawing_power"] = np.minimum(power, inputs.sanctioned[:, None])

    # ---- loan-to-value (housing, LAP, auto) ------------------------------- #
    if portfolio.has("ltv"):
        origination = np.clip(
            rng.normal(params.ltv_origination, params.ltv_origination_sd, n), 0.25, 0.95
        )
        at_sanction = inputs.sanctioned / origination
        # the collateral drifts from the SANCTION date, which is `elapsed`
        # months before the current one — not from the panel's month 0
        drift = np.power(1.0 + params.ltv_collateral_drift_pa, elapsed / 12.0)
        planned_collateral = np.maximum(1.0, at_sanction[:, None] * drift)
        collateral = np.maximum(
            1.0,
            planned_collateral
            * (1.0 + rng.normal(0.0, params.ltv_collateral_noise_sd, shape))
            * np.where(slide, 1.0 - params.ltv_stress_haircut * felt("ltv"), 1.0),
        )
        if noise:
            # A bank does not revalue collateral every month.  It carries the
            # last appraisal — stale by up to a revaluation cycle, and wrong by
            # an appraiser's error when it was fresh.  Modelling LTV as a clean
            # monthly measurement is the single biggest way a synthetic panel
            # flatters a secured book: the true value moves smoothly, the
            # OBSERVED one is a step function with a tenth of noise on it.
            collateral = _stale_valuation(noise_rng, collateral, grid, params)
        ltv = np.clip(outstanding / collateral, 0.0, 3.0)
        # What an early-warning system actually watches is not the absolute
        # LTV — on a seasoned Indian mortgage book that is comfortably low and
        # a covenant breach is genuinely rare — but the gap between the LTV the
        # schedule implies and the one a revaluation gives you. Arrears push
        # the numerator up, a distress valuation pushes the denominator down,
        # and both show long before the account is 90 days past due.
        planned = np.maximum(
            1.0,
            _scheduled_balance(
                inputs.sanctioned, inputs.rate_pa, np.maximum(inputs.tenor_months, 1), elapsed
            ),
        )
        out["ltv"] = ltv
        out["ltv_vs_schedule"] = _pct_change(ltv, planned / planned_collateral)

    # ---- rental income (LAP) ---------------------------------------------- #
    if portfolio.has("rental"):
        share = np.maximum(
            rng.normal(params.rental_share_of_emi, params.rental_share_sd, n), 0.05
        )
        rent = (demand_scale * share)[:, None] * (1.0 + 0.4 * wobble)
        rent = np.where(
            slide,
            rent * np.maximum(0.1, 1.0 - params.rental_elasticity * felt("rental")),
            rent,
        )
        vacant = rng.random(shape) < np.where(
            slide,
            params.rental_vacancy_rate
            + params.rental_stress_vacancy_gain * felt("rental"),
            params.rental_vacancy_rate,
        )
        rent = np.where(vacant, 0.0, rent)
        if noise:
            rent = rent * _lognormal_noise(noise_rng, shape, params.rental_idio_sd)
            rent = np.where(
                episodes.episode, rent * params.transient_income_mult, rent
            )
            # a tenant who pays late leaves a blank month and a double one,
            # which reads as a vacancy that never happened
            late = noise_rng.random(shape) < params.rental_late_rate
            carried = np.zeros_like(rent)
            carried[:, 1:] = np.where(late[:, :-1], rent[:, :-1], 0.0)
            rent = np.where(late, 0.0, rent) + carried
        out["rental_income"] = rent
        out["rental_vs_6m_avg"] = _pct_change(rent, _rolling_mean(rent, 6))

    # ---- harvest receipts and the annual KCC renewal (agri) --------------- #
    if portfolio.has("harvest"):
        season = seasonal_profile(inputs.calendar_month, params, mix)[None, :]
        norm = baselines.inflow[:, None] * season
        receipt = np.maximum(
            0.0,
            norm * (1.0 + 0.6 * wobble)
            * np.where(
                slide,
                np.maximum(0.1, 1.0 - params.harvest_miss_depth * felt("harvest")),
                1.0,
            ),
        )
        if noise:
            # A farmer's receipt swings 30-40% a crop year on rainfall, pests
            # and the mandi price without a loan going anywhere near bad, and a
            # delayed arrival moves the whole sale into the next month.  The
            # NORM the bank compares against does not move — so a good farmer
            # in a bad year looks exactly like a farmer in trouble.
            receipt = receipt * crop_yield
            slipped = noise_rng.random(n) < params.harvest_sale_slip_rate
            receipt = np.where(slipped[:, None], _lag(receipt, 1), receipt)
            receipt = np.where(
                episodes.episode, receipt * params.transient_income_mult, receipt
            )
        out["crop_receipt"] = receipt
        # seasonally adjusted: a bad harvest shows even in a low month
        out["crop_receipt_vs_norm"] = _pct_change(receipt, norm)
        out["renewal_overdue_months"] = _renewal_overdue(
            rng, params, inputs, stress, months, noise
        )

    # ---- commute spend (auto) --------------------------------------------- #
    if portfolio.has("commute"):
        share = np.maximum(
            rng.normal(params.commute_share_of_emi, params.commute_share_sd, n), 0.02
        )
        spend = (demand_scale * share)[:, None] * (1.0 + 0.5 * wobble)
        spend = np.maximum(
            0.0,
            np.where(
                slide,
                spend * np.maximum(0.05, 1.0 - params.commute_stress_drop * felt("commute")),
                spend
            ),
        )
        if noise:
            # Card-visible fuel and toll spend is the noisiest series a bank
            # holds: it moves with travel, with paying cash at the pump, and
            # with who in the household filled the tank.
            spend = spend * season["commute"][None, :] * _lognormal_noise(
                noise_rng, shape, params.commute_idio_sd
            )
            spend = np.where(
                noise_rng.random(shape) < params.commute_zero_rate, 0.0, spend
            )
            spend = np.where(
                episodes.episode, spend * params.transient_income_mult, spend
            )
        out["commute_spend"] = spend
        out["commute_vs_6m_avg"] = _pct_change(spend, _rolling_mean(spend, 6))

    return out


def link_loadings(
    rng: np.random.Generator,
    n: int,
    portfolio: Portfolio,
    mix: PopulationMix,
) -> dict[str, np.ndarray]:
    """How visibly each of this portfolio's channels answers the latent stress.

    One draw per account per channel.  With probability
    ``1 - chain_link_visibility`` the channel does not respond **at all** for
    that borrower — their trouble never reached that instrument — and
    otherwise it responds at a borrower-specific depth.

    This is the graded form of the silent-defaulter bucket, and it is the
    single most important thing SD-D4 does to the defaulter side.  Before it,
    every defaulter's ten instruments moved coherently off one number, so a
    model could average them and separate the book at 0.97.  A real defaulting
    borrower shows two or three links clearly, one or two faintly, and several
    not at all — and which ones is not knowable in advance.

    The channels listed in ``shared.chain_visibility.unloaded_channels``, and
    the shared spine (collection ratio, balance, bureau score), are exempt:
    days past due is an arithmetic consequence of money not arriving rather
    than an instrument that can be dark, and the spine is what a single model
    leans on when a product's own instrument is quiet.

    Args:
        rng: the portfolio's SD-D4 stream.
        n: number of accounts in this block.
        portfolio: supplies the declared channels and the parameters.
        mix: unused today; kept so the exemption list can move to the mix.

    Returns:
        Channel name -> ``(N, 1)`` multiplier on that channel's stress response.
    """
    params = portfolio.params
    exempt = set(sources.value("shared.chain_visibility.unloaded_channels"))
    out: dict[str, np.ndarray] = {}
    for channel in portfolio.channels:
        if channel in exempt:
            continue
        visible = rng.random(n) < params.chain_link_visibility
        strength = rng.uniform(*params.chain_link_strength_bounds, size=n)
        out[channel] = np.where(visible, strength, 0.0)[:, None]
    return out


def _consecutive(mask: np.ndarray) -> np.ndarray:
    """Length of the run of True values ending at each month.

    Args:
        mask: ``(N, M)`` boolean.

    Returns:
        ``(N, M)`` int: 0 where the mask is False, else how many consecutive
        True months end here.
    """
    out = np.zeros(mask.shape, dtype=np.int64)
    out[:, 0] = mask[:, 0]
    for t in range(1, mask.shape[1]):       # M is 36-48: O(M) numpy passes
        out[:, t] = np.where(mask[:, t], out[:, t - 1] + 1, 0)
    return out


def _lognormal_noise(
    rng: np.random.Generator, shape: tuple[int, int], sd: float
) -> np.ndarray:
    """Multiplicative measurement noise with a mean of exactly 1.

    Args:
        rng: the SD-D4 stream.
        shape: ``(N, M)``.
        sd: log-scale dispersion; ``0`` returns ones.

    Returns:
        ``(N, M)`` positive multiplier, mean 1, so the channel's LEVEL is
        unchanged and only its month-to-month reading moves.
    """
    if sd <= 0:
        return np.ones(shape)
    return np.exp(rng.normal(0.0, sd, shape) - 0.5 * sd * sd)


def _stale_valuation(
    rng: np.random.Generator,
    collateral: np.ndarray,
    grid: np.ndarray,
    params: ChannelParams,
) -> np.ndarray:
    """The collateral value the bank CARRIES, not the one the market holds.

    The carried value is refreshed once a revaluation cycle, with an
    appraiser's error each time, and held flat in between.  Each account gets
    its own offset into the cycle so revaluations are not synchronised across
    the book.

    Args:
        rng: the SD-D4 stream.
        collateral: ``(N, M)`` true collateral value.
        grid: ``(1, M)`` month index.
        params: supplies the cycle length and the appraisal error.

    Returns:
        ``(N, M)`` carried value.
    """
    n, months = collateral.shape
    cycle = max(int(params.collateral_revaluation_months), 1)
    stale, which = _refresh_index(rng, n, months, grid, cycle)
    error = rng.normal(
        0.0, params.collateral_appraisal_error_sd, size=(n, months // cycle + 2)
    )
    carried = np.take_along_axis(collateral, stale, axis=1) * (
        1.0 + np.take_along_axis(error, which, axis=1)
    )
    return np.maximum(1.0, carried)


def _refresh_index(
    rng: np.random.Generator, n: int, months: int, grid: np.ndarray, cycle: int
) -> tuple[np.ndarray, np.ndarray]:
    """Which month each account's series was last refreshed, and which refresh.

    Each account gets its own offset into the cycle, so refreshes are spread
    across the book rather than synchronised.

    Args:
        rng: the SD-D4 stream.
        n: number of accounts.
        months: observation window ``M``.
        grid: ``(1, M)`` month index.
        cycle: months between refreshes.

    Returns:
        ``(last refreshed month, refresh ordinal)``, both ``(N, M)`` int.
    """
    offset = rng.integers(0, cycle, size=n)[:, None]
    elapsed = (grid + offset) % cycle
    return np.maximum(grid - elapsed, 0), (grid + offset) // cycle


def _held_between_refreshes(
    rng: np.random.Generator, series: np.ndarray, grid: np.ndarray, cycle: int
) -> np.ndarray:
    """The last refreshed value of a series, held flat until the next refresh.

    Args:
        rng: the SD-D4 stream.
        series: ``(N, M)`` true series.
        grid: ``(1, M)`` month index.
        cycle: months between refreshes.

    Returns:
        ``(N, M)`` step-function view of the series.
    """
    n, months = series.shape
    stale, _ = _refresh_index(rng, n, months, grid, max(int(cycle), 1))
    return np.take_along_axis(series, stale, axis=1)


def _crop_year_yield(
    rng: np.random.Generator,
    n: int,
    calendar_month: np.ndarray,
    params: ChannelParams,
) -> np.ndarray:
    """One yield-and-price multiplier per account per crop year, mean 1.

    The Indian crop year is reckoned July to June, so the multiplier steps at
    the monsoon onset and is then held for twelve months: a farmer's receipts
    are good or bad for a SEASON, not for a month.  Every account draws its own
    (the rainfall is regional, the pest is local, the price is the mandi's),
    which is what gives ``crop_receipt_vs_norm`` the year-to-year dispersion it
    has in a real KCC book and did not have in the July 2026 panel.

    Args:
        rng: the SD-D4 stream.
        n: number of accounts in this block.
        calendar_month: ``(M,)`` calendar month (1-12) of each panel month.
        params: supplies the log-scale dispersion.

    Returns:
        ``(N, M)`` multiplier, constant within a crop year.
    """
    if params.harvest_yield_sd <= 0:
        return np.ones((n, calendar_month.shape[0]))
    year = np.cumsum(calendar_month == 7) - (calendar_month[0] == 7)
    year = np.maximum(year, 0).astype(np.int64)
    draws = _lognormal_noise(rng, (n, int(year.max()) + 1), params.harvest_yield_sd)
    return draws[:, year]


def _renewal_overdue(
    rng: np.random.Generator,
    params: ChannelParams,
    inputs: BlockInputs,
    stress: StressPath,
    months: int,
    noise: bool = True,
) -> np.ndarray:
    """Months since a KCC renewal fell due and was not done.

    A Kisan Credit Card limit is reviewed once a crop year.  A farmer whose
    harvest failed cannot clear the limit, so the renewal slips — and a slipped
    renewal is visible to the bank long before the account is 90 days past due.

    Args:
        rng: the portfolio's SD-D3 stream.
        params: supplies the renewal cycle, how hard stress makes it slip, and
            SD-D4's benign slip rate.
        inputs: supplies months-on-book, which fixes each account's due months.
        stress: the shared latent stress path.
        months: observation window ``M``.
        noise: SD-D4 switch; when off, the July 2026 benign slip rate is used.

    Returns:
        ``(N, M)`` integer months overdue, 0 when the renewal is current.
    """
    n = inputs.vintage_months_0.shape[0]
    grid = np.arange(months)[None, :]
    due = (((inputs.vintage_months_0[:, None] + grid) % params.renewal_cycle_months) == 0) & (grid > 0)
    benign = params.renewal_benign_slip_rate if noise else 0.02
    slip_chance = np.where(
        stress.in_slide & (stress.months_to_npa <= params.renewal_lead_months),
        np.maximum(params.renewal_slip_gain * stress.decline, benign),
        benign,
    )
    slipped = due & (rng.random((n, months)) < slip_chance)

    last_due = np.maximum.accumulate(np.where(due, grid, -1), axis=1)
    slipped_at = np.take_along_axis(slipped, np.maximum(last_due, 0), axis=1)
    return np.where((last_due >= 0) & slipped_at, grid - last_due, 0).astype(np.int64)


# --------------------------------------------------------------------------- #
# Trailing / trend features (past-only, so the panel stays leakage-safe)
# --------------------------------------------------------------------------- #
def trailing_features(channels: Channels) -> dict[str, np.ndarray]:
    """Windowed views of the legacy channels, using only the account's own past.

    Every window is inclusive of the current month and truncated (not dropped)
    at the start of the observation window, so month 0 is still scoreable.  The
    SD-D3 channels compute their own trailing views inside
    :func:`_simulate_extra`, because several of them need the per-account base
    (a seasonal norm, a salary reference) that only the portfolio block knows.

    Args:
        channels: the raw monthly signals.

    Returns:
        Column name -> ``(N, M)`` array, ready to be flattened into the panel.
    """
    util, dpd, txn = channels.utilisation, channels.dpd, channels.txn
    inflow, sales = channels.inflow, channels.gst_sales
    return {
        "dpd_max_6m": _rolling_max(dpd, 6),
        "times_late_6m": _rolling_sum((dpd > 0).astype(np.float64), 6),
        "bounces_6m": _rolling_sum(channels.bounce.astype(np.float64), 6),
        "minbal_breach_6m": _rolling_sum(channels.minbal_breach.astype(np.float64), 6),
        "util_avg_3m": _rolling_mean(util, 3),
        "util_max_6m": _rolling_max(util, 6),
        "months_over_90pct_util_6m": _rolling_sum((util > 0.9).astype(np.float64), 6),
        "inflow_trend_3m": _pct_change(inflow, _lag(inflow, 3)),
        "inflow_vs_6m_avg": _pct_change(inflow, _rolling_mean(inflow, 6)),
        "sales_trend_3m": _pct_change(sales, _lag(sales, 3)),
        "txn_drop_flag": (txn < 0.6 * _rolling_mean(txn, 6)).astype(np.int64),
        "adverse_remark_6m": _rolling_sum(channels.adverse_remark.astype(np.float64), 6),
    }

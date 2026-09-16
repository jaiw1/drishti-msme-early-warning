"""Observation channels — how the shared latent stress becomes bank-visible.

:mod:`generator.latent` decides *that* an account is deteriorating and how
hard.  This module decides *what the bank sees*, and it is the only place the
two are connected.  Every function here takes a per-portfolio
:class:`~generator.portfolios.ChannelParams` block, so a new portfolio in
SD-D2/SD-D3 supplies its own elasticities instead of editing shared code.

The ordered-deterioration causality is the whole thesis of the dataset and is
preserved exactly as the original simulator encoded it:

===========================  ==================================================
months before NPA            what moves
===========================  ==================================================
onset (median ~13) to NPA    cash inflow and GST sales fall, transactions thin
<= 10                        credit-limit utilisation creeps up
<= 9                         adverse filing remarks start appearing
<= 6                         cheque bounces and min-balance breaches
<= 3                         days-past-due finally rises (15 -> 38 -> 68)
===========================  ==================================================

So the leading signal is business cash-flow, **not** the obvious "already
paying late" signal — which is what forces the model to learn genuine
12-month-ahead early warning rather than near-term arrears.

Everything is computed as ``(N, M)`` float/bool arrays for one portfolio
block at a time.  The only Python-level loops are over ``M`` (36-48 months)
and over the rolling-window offsets (at most 6), never over accounts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .latent import StressPath
from .noise import ar1_noise, bernoulli, transient_stress
from .portfolios import ChannelParams

__all__ = [
    "CHANNEL_COLUMNS",
    "Baselines",
    "Channels",
    "draw_baselines",
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
}


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


def _lag(x: np.ndarray, months: int) -> np.ndarray:
    """Value ``months`` months ago, holding the first observation before t=0."""
    out = np.empty_like(x)
    out[:, :months] = x[:, :1]
    out[:, months:] = x[:, :-months]
    return out


def _pct_change(now: np.ndarray, then: np.ndarray) -> np.ndarray:
    """Relative change, floored at a ₹1 denominator like the original."""
    return (now - then) / np.maximum(then, 1.0)


# --------------------------------------------------------------------------- #
# Per-account baselines
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Baselines:
    """Per-account healthy levels the monthly signals oscillate around."""

    util: np.ndarray        # (N,) credit-limit utilisation
    inflow: np.ndarray      # (N,) monthly banked inflow (₹)
    sales: np.ndarray       # (N,) monthly declared GST sales (₹)
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


def simulate_channels(
    rng: np.random.Generator,
    baselines: Baselines,
    stress: StressPath,
    params: ChannelParams,
    months: int,
) -> Channels:
    """Turn baselines plus latent stress into observed monthly signals.

    Args:
        rng: source of randomness for this portfolio block.
        baselines: per-account healthy levels.
        stress: the shared latent stress path for the same accounts.
        params: the portfolio's channel parameters.
        months: observation window ``M``.

    Returns:
        The observed channels for this portfolio block.
    """
    n = baselines.util.shape[0]
    shape = (n, months)

    # ---- 1. healthy conduct: AR(1) wobble around each baseline ----------- #
    wobble = ar1_noise(rng, baselines.wobble, months, params.ar1_phi)
    inflow_shock = rng.normal(0.0, baselines.wobble[:, None], shape)
    sales_shock = rng.normal(0.0, baselines.wobble[:, None], shape)

    util = np.clip(baselines.util[:, None] * (1.0 + wobble), *params.util_bounds)
    inflow = np.maximum(
        baselines.inflow[:, None] * (1.0 + params.inflow_wobble_gain * wobble + inflow_shock),
        params.inflow_floor,
    )
    sales = np.maximum(
        baselines.sales[:, None] * (1.0 + params.inflow_wobble_gain * wobble + sales_shock),
        params.inflow_floor,
    )
    txn = np.maximum(
        baselines.txn[:, None] * (1.0 + params.txn_wobble_gain * wobble), params.txn_floor
    )

    bounce = bernoulli(rng, shape, params.bounce_rate)
    minbal = bernoulli(rng, shape, params.minbal_rate)
    adverse = np.zeros(shape, dtype=bool)
    dpd = np.zeros(shape, dtype=np.float64)

    # ---- 2. hard negatives: transient stress on healthy accounts --------- #
    healthy = ~stress.post_npa.any(axis=1)
    episodes = transient_stress(rng, healthy, months, params)
    util = np.where(
        episodes.episode,
        np.clip(util * params.transient_util_mult, *params.transient_util_bounds),
        util,
    )
    inflow = np.where(episodes.episode, inflow * params.transient_inflow_mult, inflow)
    bounce |= episodes.bounce

    # ---- 3. ordered deterioration on the way to NPA ---------------------- #
    slide, decline, mtn = stress.in_slide, stress.decline, stress.months_to_npa

    inflow = np.where(
        slide,
        inflow * np.maximum(params.inflow_decay_floor, 1.0 - params.inflow_elasticity * decline),
        inflow,
    )
    sales = np.where(
        slide,
        sales * np.maximum(params.sales_decay_floor, 1.0 - params.sales_elasticity * decline),
        sales,
    )
    txn = np.where(
        slide,
        txn * np.maximum(params.txn_decay_floor, 1.0 - params.txn_elasticity * decline),
        txn,
    )
    util_creep = slide & (mtn <= params.util_lead_months)
    util = np.where(
        util_creep,
        np.clip(
            util * (1.0 + params.util_slide_gain * decline) + params.util_slide_shift * decline,
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
        & (rng.random(shape) < params.adverse_slide_base + params.adverse_slide_gain * decline)
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

    return Channels(
        utilisation=util,
        inflow=inflow,
        gst_sales=sales,
        txn=txn,
        dpd=dpd,
        bounce=bounce.astype(np.int64),
        minbal_breach=minbal.astype(np.int64),
        adverse_remark=adverse.astype(np.int64),
    )


# --------------------------------------------------------------------------- #
# Trailing / trend features (past-only, so the panel stays leakage-safe)
# --------------------------------------------------------------------------- #
def trailing_features(channels: Channels) -> dict[str, np.ndarray]:
    """Windowed views of the channels, using only the account's own past.

    Every window is inclusive of the current month and truncated (not dropped)
    at the start of the observation window, so month 0 is still scoreable.

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

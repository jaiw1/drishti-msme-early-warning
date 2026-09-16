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

from .latent import StressPath
from .noise import ar1_noise, bernoulli, transient_stress
from .portfolios import ChannelParams, PopulationMix, Portfolio

__all__ = [
    "CHANNEL_COLUMNS",
    "SHARED_COLUMNS",
    "Baselines",
    "BlockInputs",
    "Channels",
    "draw_baselines",
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


def simulate_channels(
    rng: np.random.Generator,
    extra_rng: np.random.Generator,
    portfolio: Portfolio,
    baselines: Baselines,
    inputs: BlockInputs,
    stress: StressPath,
    mix: PopulationMix,
    months: int,
) -> Channels:
    """Turn baselines plus latent stress into observed monthly signals.

    Args:
        rng: the July 2026 channels stream — every legacy draw, in order.
        extra_rng: a separate stream for the SD-D3 channels, so adding them
            leaves the MSME channels bit-identical.
        portfolio: the portfolio being simulated (supplies its channels).
        baselines: per-account healthy levels.
        inputs: static per-account facts (ticket, tenor, rate, vintage, bureau).
        stress: the shared latent stress path for the same accounts.
        mix: shared sourced constants (seasonality, balance floor, bureau).
        months: observation window ``M``.

    Returns:
        The observed channels for this portfolio block.
    """
    params = portfolio.params
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

    # ---- 5. SD-D3: the shared spine and this portfolio's own instruments -- #
    extra = _simulate_extra(
        extra_rng, portfolio, baselines, inputs, stress, mix, months,
        utilisation=util, inflow=inflow, wobble=wobble, minbal=minbal,
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
) -> dict[str, np.ndarray]:
    """The shared spine plus whichever SD-D3 chains this portfolio declares.

    Args:
        rng: this portfolio's SD-D3 stream.
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

    Returns:
        Panel column name -> ``(N, M)`` array, plus the private ``_minbal`` key.
    """
    params = portfolio.params
    n = baselines.util.shape[0]
    shape = (n, months)
    grid = np.arange(months)[None, :]
    slide, decline, mtn = stress.in_slide, stress.decline, stress.months_to_npa
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
    shortfall = np.where(
        slide & (mtn <= params.collection_lead_months),
        np.clip(params.collection_shortfall_gain * decline, 0.0, 1.0),
        0.0,
    )
    if portfolio.has("moratorium"):
        shortfall = np.clip(
            shortfall + np.where(post_moratorium, params.moratorium_shock_gain * decline, 0.0),
            0.0, 1.0,
        )
    hiccup = rng.random(shape) < params.collection_short_rate
    shortfall = np.maximum(shortfall, np.where(hiccup, rng.uniform(0.05, 0.5, shape), 0.0))
    collected = np.maximum(
        0.0, demanded * (1.0 - shortfall) * (1.0 + rng.normal(0.0, params.collection_noise_sd, shape))
    )
    collected = np.minimum(collected, demanded)
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
            slide, salary * np.maximum(0.15, 1.0 - params.salary_elasticity * decline), salary
        )
        missed = rng.random(shape) < np.where(
            slide, params.salary_miss_base + params.salary_miss_gain * decline,
            params.salary_miss_base,
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
        taken = slide & (rng.random(shape) < params.stress_new_emi_rate * decline)
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
    balance = np.maximum(
        params.balance_floor,
        balance_base[:, None] * (1.0 + wobble)
        * np.where(slide, np.maximum(0.05, 1.0 - params.balance_elasticity * decline), 1.0)
        * (1.0 - burden_squeeze),
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
    out["bureau_score"] = np.clip(
        inputs.bureau_score_0[:, None] - mix.bureau_stress_drop * lagged,
        *mix.bureau_score_bounds,
    )

    # ---- drawing power (cash credit, KCC) --------------------------------- #
    if portfolio.has("drawing_power"):
        cover = np.clip(rng.normal(params.dp_to_limit_mean, params.dp_to_limit_sd, n), 0.5, 1.0)
        out["drawing_power"] = inputs.sanctioned[:, None] * cover[:, None] * np.where(
            slide, np.maximum(0.2, 1.0 - params.dp_squeeze_gain * decline), 1.0
        )

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
            * np.where(slide, 1.0 - params.ltv_stress_haircut * decline, 1.0),
        )
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
            slide, rent * np.maximum(0.1, 1.0 - params.rental_elasticity * decline), rent
        )
        vacant = rng.random(shape) < np.where(
            slide,
            params.rental_vacancy_rate + params.rental_stress_vacancy_gain * decline,
            params.rental_vacancy_rate,
        )
        rent = np.where(vacant, 0.0, rent)
        out["rental_income"] = rent
        out["rental_vs_6m_avg"] = _pct_change(rent, _rolling_mean(rent, 6))

    # ---- harvest receipts and the annual KCC renewal (agri) --------------- #
    if portfolio.has("harvest"):
        season = seasonal_profile(inputs.calendar_month, params, mix)[None, :]
        norm = baselines.inflow[:, None] * season
        receipt = np.maximum(
            0.0,
            norm * (1.0 + 0.6 * wobble)
            * np.where(slide, np.maximum(0.1, 1.0 - params.harvest_miss_depth * decline), 1.0),
        )
        out["crop_receipt"] = receipt
        # seasonally adjusted: a bad harvest shows even in a low month
        out["crop_receipt_vs_norm"] = _pct_change(receipt, norm)
        out["renewal_overdue_months"] = _renewal_overdue(rng, params, inputs, stress, months)

    # ---- commute spend (auto) --------------------------------------------- #
    if portfolio.has("commute"):
        share = np.maximum(
            rng.normal(params.commute_share_of_emi, params.commute_share_sd, n), 0.02
        )
        spend = (demand_scale * share)[:, None] * (1.0 + 0.5 * wobble)
        spend = np.maximum(
            0.0,
            np.where(
                slide, spend * np.maximum(0.05, 1.0 - params.commute_stress_drop * decline), spend
            ),
        )
        out["commute_spend"] = spend
        out["commute_vs_6m_avg"] = _pct_change(spend, _rolling_mean(spend, 6))

    return out


def _renewal_overdue(
    rng: np.random.Generator,
    params: ChannelParams,
    inputs: BlockInputs,
    stress: StressPath,
    months: int,
) -> np.ndarray:
    """Months since a KCC renewal fell due and was not done.

    A Kisan Credit Card limit is reviewed once a crop year.  A farmer whose
    harvest failed cannot clear the limit, so the renewal slips — and a slipped
    renewal is visible to the bank long before the account is 90 days past due.

    Args:
        rng: the portfolio's SD-D3 stream.
        params: supplies the renewal cycle and how hard stress makes it slip.
        inputs: supplies months-on-book, which fixes each account's due months.
        stress: the shared latent stress path.
        months: observation window ``M``.

    Returns:
        ``(N, M)`` integer months overdue, 0 when the renewal is current.
    """
    n = inputs.vintage_months_0.shape[0]
    grid = np.arange(months)[None, :]
    due = (((inputs.vintage_months_0[:, None] + grid) % params.renewal_cycle_months) == 0) & (grid > 0)
    slip_chance = np.where(
        stress.in_slide & (stress.months_to_npa <= params.renewal_lead_months),
        params.renewal_slip_gain * stress.decline,
        0.02,
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

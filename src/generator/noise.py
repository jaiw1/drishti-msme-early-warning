"""Randomness plumbing, measurement noise, hard negatives and missingness.

Four responsibilities:

1. **Named RNG streams.**  Every draw in the package comes from
   :func:`stream`, which derives an independent generator from the master
   seed and a *stage name*.  Because streams are addressed by name rather
   than by draw order, adding a portfolio or a new channel in SD-D2/SD-D3 —
   or the whole SD-D4 realism block — does not perturb the streams that
   already exist: the same ``--seed`` keeps producing the same values for
   every stage that did not change.

2. **Measurement noise** — the AR(1) conduct wobble that every healthy
   account carries, the Bernoulli operational events (a bounce here, a
   min-balance breach there), and SD-D4's instrument errors: reporting lags,
   rounding, duplicated batches and reversed payments.  These do not change
   what happened to the borrower; they change what the bank *saw*.

3. **Hard negatives** — the transient stress episodes given to a share of
   *healthy* accounts.  These are the reason the panel is not trivially
   separable: an account that dips, part-pays, bounces, goes 60 days past due
   and then cures looks exactly like an early-stage defaulter for two to eight
   months, and is not one.

4. **Missingness** — statement-feed gaps, drawn from their own stream so they
   are missing-at-random *by construction* and a test can prove it.

The noise switch
----------------
Every SD-D4 mechanism in this module is gated on one boolean that reaches it
from :class:`~generator.build.GeneratorConfig`.  **The default is ON** — the
shipped panel is the noisy one.  ``noise=False`` exists so the equivalence
suite can regenerate the July 2026 MSME fingerprint exactly, and for no other
reason; a panel generated with it is *not* the dataset DRISHTi is trained or
validated on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from .portfolios import ChannelParams, PopulationMix

__all__ = [
    "TransientStress",
    "ar1_noise",
    "bernoulli",
    "duplicate_batches",
    "reported_with_lag",
    "round_to",
    "statement_gaps",
    "stream",
    "transient_stress",
]


def stream(seed: int, name: str) -> np.random.Generator:
    """An independent generator for one named stage of the simulation.

    Args:
        seed: the master seed (``--seed``).
        name: stage name, e.g. ``"population"`` or ``"channels:msme_cc"``.

    Returns:
        A ``numpy`` generator whose stream depends only on ``(seed, name)``.
    """
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    return np.random.default_rng([seed, int.from_bytes(digest, "big")])


def ar1_noise(
    rng: np.random.Generator,
    amplitude: np.ndarray,
    months: int,
    phi: float,
) -> np.ndarray:
    """AR(1) conduct wobble ``e[t] = phi * e[t-1] + N(0, amplitude)``.

    Args:
        rng: source of randomness.
        amplitude: per-account noise standard deviation, shape ``(N,)``.
        months: number of months ``M``.
        phi: autoregressive coefficient.

    Returns:
        ``(N, M)`` array with ``e[:, -1]`` seeded from ``e = 0``.
    """
    shocks = rng.normal(0.0, amplitude[:, None], size=(amplitude.shape[0], months))
    out = np.empty_like(shocks)
    out[:, 0] = shocks[:, 0]
    for t in range(1, months):                       # M is 36-48: O(M) numpy passes
        out[:, t] = phi * out[:, t - 1] + shocks[:, t]
    return out


def bernoulli(rng: np.random.Generator, shape: tuple[int, int], p: float) -> np.ndarray:
    """Independent Bernoulli draws, as a boolean ``(N, M)`` mask."""
    return rng.random(shape) < p


# --------------------------------------------------------------------------- #
# SD-D4: measurement noise
# --------------------------------------------------------------------------- #
def reported_with_lag(values: np.ndarray, lag: np.ndarray) -> np.ndarray:
    """What the bank sees when each account reports with its own delay.

    A GST return for a turnover month is filed the month after, and a quarterly
    filer surfaces up to two months late — so the ``gst_sales`` a lender has on
    file in month ``t`` is the borrower's turnover in month ``t - lag``.  Before
    the first reported month the earliest available figure is held, which is
    what a lender's file actually contains on a new relationship.

    Args:
        values: ``(N, M)`` true monthly series.
        lag: ``(N,)`` non-negative integer months of reporting delay.

    Returns:
        ``(N, M)`` reported series.
    """
    months = values.shape[1]
    index = np.clip(np.arange(months)[None, :] - lag[:, None], 0, months - 1)
    return np.take_along_axis(values, index, axis=1)


def round_to(values: np.ndarray, step: float) -> np.ndarray:
    """Round to the nearest ``step`` rupees, leaving NaN alone.

    Args:
        values: any float array.
        step: rounding granularity; ``<= 0`` is a no-op.

    Returns:
        The rounded array.
    """
    if step <= 0:
        return values
    return np.round(values / step) * step


def duplicate_batches(
    rng: np.random.Generator, shape: tuple[int, int], params: ChannelParams
) -> np.ndarray:
    """Multiplier for months whose transaction batch was posted twice.

    A duplicated or re-posted statement batch is the routine artefact that a
    ``txn_drop_flag``-style rule mistakes for behaviour: the month before looks
    normal, this one looks busy, and the next one looks like a collapse.

    Args:
        rng: the portfolio's SD-D4 stream.
        shape: ``(N, M)``.
        params: supplies the rate and how much a duplicate inflates the count.

    Returns:
        ``(N, M)`` multiplier, 1.0 where nothing was duplicated.
    """
    hit = rng.random(shape) < params.duplicate_batch_rate
    inflation = rng.uniform(*params.duplicate_batch_bounds, size=shape)
    return np.where(hit, inflation, 1.0)


# --------------------------------------------------------------------------- #
# SD-D4: missingness
# --------------------------------------------------------------------------- #
def statement_gaps(
    rng: np.random.Generator, n_accounts: int, months: int, mix: PopulationMix
) -> np.ndarray:
    """Months for which the bank has no statement at all.

    A consent lapse on the account-aggregator side, a failed overnight pull, a
    customer who banks elsewhere for a while.  Drawn from this stream and this
    stream only — it sees neither the latent stress nor the label, which is
    what makes the missingness **missing-at-random by construction** rather
    than by hope.  ``tests/test_noise.py`` regresses the gap flag on the label
    and asserts the coefficient is indistinguishable from zero.

    Args:
        rng: the missingness stream.
        n_accounts: number of accounts ``N``.
        months: observation window ``M``.
        mix: supplies the share of accounts affected and the gap length.

    Returns:
        ``(N, M)`` boolean mask; True where the statement is absent.
    """
    chosen = rng.random(n_accounts) < mix.statement_gap_share
    lo, hi = mix.statement_gap_length_bounds
    start = rng.integers(1, max(months - hi, 2), size=n_accounts)
    length = rng.integers(lo, max(hi, lo + 1), size=n_accounts)
    grid = np.arange(months)[None, :]
    return (
        chosen[:, None]
        & (grid >= start[:, None])
        & (grid < (start + length)[:, None])
    )


# --------------------------------------------------------------------------- #
# Hard negatives
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TransientStress:
    """A recoverable stress episode on an otherwise healthy account.

    The episode is the panel's population of **hard negatives**.  It moves the
    same instruments a real slide moves — the portfolio's own first link, the
    collection ratio, the balance — and a share of episodes goes genuinely past
    due before curing.  Nothing here is labelled: these accounts never reach
    NPA, so every row of every episode is a zero the model has to earn.
    """

    #: ``(N, M)`` — True inside an episode
    episode: np.ndarray
    #: ``(N, M)`` — True where the episode also produced a bounced payment
    bounce: np.ndarray
    #: ``(N, M)`` — months since the episode began, ``-1`` outside one
    position: np.ndarray
    #: ``(N,)`` — this account's episode goes into arrears and then cures
    arrears: np.ndarray
    #: ``(N, M)`` — fraction of the month's demand left unpaid inside an episode
    shortfall: np.ndarray


def transient_stress(
    rng: np.random.Generator,
    healthy: np.ndarray,
    months: int,
    params: ChannelParams,
    noise: bool = True,
) -> TransientStress:
    """Give a share of healthy accounts a short stress episode that recovers.

    Args:
        rng: the July 2026 channels stream (the legacy draws stay in order).
        healthy: ``(N,)`` boolean mask of accounts that never reach NPA.
        months: number of months ``M``.
        params: the portfolio's channel parameters.
        noise: when False, the pre-SD-D4 episode population is drawn and the
            hard-negative extensions are all inert, so the July 2026 MSME
            fingerprint is reproduced exactly.

    Returns:
        The episode mask, the bounces it caused, each month's position inside
        its episode, which accounts go past due, and how deep the shortfall is.
    """
    n = healthy.shape[0]
    share = params.transient_share if noise else params.quiet_transient_share
    bounds = (
        params.transient_length_bounds if noise else params.quiet_transient_length_bounds
    )
    chosen = healthy & (rng.random(n) < share)
    start = rng.integers(
        params.transient_start_lo, months + params.transient_start_hi_offset, size=n
    )
    length = rng.integers(*bounds, size=n)

    grid = np.arange(months)[None, :]
    since = grid - start[:, None]
    episode = chosen[:, None] & (since >= 0) & (since < length[:, None])
    bounce = episode & bernoulli(rng, (n, months), params.transient_bounce_rate)
    if not noise:
        return TransientStress(
            episode=episode,
            bounce=bounce,
            position=np.full((n, months), -1, dtype=np.int64),
            arrears=np.zeros(n, dtype=bool),
            shortfall=np.zeros((n, months)),
        )

    arrears = chosen & (rng.random(n) < params.transient_arrears_share)
    depth = rng.uniform(*params.transient_collection_bounds, size=n)
    return TransientStress(
        episode=episode,
        bounce=bounce,
        position=np.where(episode, since, -1).astype(np.int64),
        arrears=arrears,
        shortfall=np.where(episode, depth[:, None], 0.0),
    )

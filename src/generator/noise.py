"""Randomness plumbing, measurement noise and hard negatives.

Three responsibilities:

1. **Named RNG streams.**  Every draw in the package comes from
   :func:`stream`, which derives an independent generator from the master
   seed and a *stage name*.  Because streams are addressed by name rather
   than by draw order, adding a portfolio or a new channel in SD-D2/SD-D3
   does not perturb the streams that already exist — the same ``--seed``
   keeps producing the same values for every stage that did not change.

2. **Measurement noise** — the AR(1) conduct wobble that every healthy
   account carries, and the Bernoulli operational events (a bounce here, a
   min-balance breach there) that keep a clean account from looking clean.

3. **Hard negatives** — the transient stress episodes given to a share of
   *healthy* accounts.  These are the reason the panel is not trivially
   separable: an account that dips, bounces once and recovers looks exactly
   like an early-stage defaulter for two or three months.

SD-D4 hooks
-----------
SD-D4 adds silent/fast defaulters, seasonal confounders and MAR missingness
blocks.  They belong here, and the shapes are already right for it:
:func:`transient_stress` returns an ``(N, M)`` episode mask, so a
"silent defaulter" mask (deterioration suppressed) and a "missingness" mask
(channel blanked for a run of months) are the same kind of object and can be
composed with the channel arrays the same way.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from .portfolios import ChannelParams

__all__ = ["TransientStress", "ar1_noise", "bernoulli", "stream", "transient_stress"]


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


@dataclass(frozen=True)
class TransientStress:
    """A recoverable stress episode on an otherwise healthy account."""

    #: ``(N, M)`` — True inside an episode
    episode: np.ndarray
    #: ``(N, M)`` — True where the episode also produced a bounced payment
    bounce: np.ndarray


def transient_stress(
    rng: np.random.Generator,
    healthy: np.ndarray,
    months: int,
    params: ChannelParams,
) -> TransientStress:
    """Give a share of healthy accounts a short stress episode that recovers.

    Args:
        rng: source of randomness.
        healthy: ``(N,)`` boolean mask of accounts that never reach NPA.
        months: number of months ``M``.
        params: the portfolio's channel parameters.

    Returns:
        The episode mask and the bounces it caused.
    """
    n = healthy.shape[0]
    chosen = healthy & (rng.random(n) < params.transient_share)
    start = rng.integers(
        params.transient_start_lo, months + params.transient_start_hi_offset, size=n
    )
    length = rng.integers(*params.transient_length_bounds, size=n)

    grid = np.arange(months)[None, :]
    episode = (
        chosen[:, None]
        & (grid >= start[:, None])
        & (grid < (start + length)[:, None])
    )
    return TransientStress(
        episode=episode,
        bounce=episode & bernoulli(rng, (n, months), params.transient_bounce_rate),
    )

"""The latent stress process — who eventually goes bad, when, and how hard.

Two stages, both fully vectorised over the ``N`` accounts:

**Cross-section** (:func:`draw_population`).  Static borrower attributes plus a
weak latent-risk scorecard.  The scorecard is deliberately weak: the
irreducible-randomness term dominates, so a static scorecard alone cannot
predict well and the model is forced to learn the *dynamic* deterioration,
which is the whole early-warning thesis.  Accounts that will default also draw
their NPA month, the *onset* (how many months before NPA the slide begins) and
a *severity* (how steep it is).

**Time series** (:func:`build_stress_path`).  An ``(N, M)`` stress intensity
``decline`` — zero while the account is healthy, stepping to
``0.30 * severity`` the month the slide begins and ramping to
``1.00 * severity`` at NPA.  This is the shared latent state ``S_t``:
:mod:`generator.channels` is the only place it becomes an *observation*, and
each portfolio maps it to its own channels with its own elasticities.  That
separation is what makes one holistic model across portfolios legitimate —
the portfolios differ in what the bank can see, not in what is happening.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .portfolios import PopulationMix, Portfolio, portfolio_mix

__all__ = ["Population", "StressPath", "build_stress_path", "draw_population"]

#: months-to-NPA placeholder for accounts that never reach NPA
NEVER = np.iinfo(np.int32).max


def _weights(mix: dict[str, float | tuple[float, float]]) -> tuple[tuple[str, ...], np.ndarray]:
    """Category labels and normalised probabilities from a mix dict."""
    keys = tuple(mix)
    raw = np.array(
        [v[0] if isinstance(v, tuple) else v for v in mix.values()], dtype=np.float64
    )
    return keys, raw / raw.sum()


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass(frozen=True)
class Population:
    """One row per account: static attributes and the account's latent fate."""

    account_id: np.ndarray            # (N,) str
    portfolio_code: np.ndarray        # (N,) int  -> index into the registry order
    sector_code: np.ndarray           # (N,) int
    region_code: np.ndarray           # (N,) int
    qualification_code: np.ndarray    # (N,) int
    age_group_code: np.ndarray        # (N,) int
    sanctioned: np.ndarray            # (N,) float
    business_age_years: np.ndarray    # (N,) int
    vintage_months_0: np.ndarray      # (N,) int
    is_defaulter: np.ndarray          # (N,) bool
    npa_month: np.ndarray             # (N,) int, -1 when never
    severity: np.ndarray              # (N,) float, 0.0 when never
    onset: np.ndarray                 # (N,) int, 0 when never

    def __len__(self) -> int:
        return int(self.account_id.shape[0])


def draw_population(
    rng: np.random.Generator,
    n_accounts: int,
    months: int,
    mix: PopulationMix,
) -> tuple[Population, list[Portfolio]]:
    """Draw the static book and decide who defaults, when and how steeply.

    Args:
        rng: source of randomness (one named stream).
        n_accounts: number of accounts ``N``.
        months: observation window ``M`` (bounds the NPA month).
        mix: population distributions and the latent-risk scorecard.

    Returns:
        The population, and the portfolio registry in code order.
    """
    portfolios, shares = portfolio_mix()
    sector_keys, sector_p = _weights(mix.sectors)
    region_keys, region_p = _weights(mix.regions)
    qual_keys, qual_p = _weights(mix.qualifications)
    age_keys, age_p = _weights(mix.age_groups)

    portfolio_code = rng.choice(len(portfolios), size=n_accounts, p=np.asarray(shares))
    sector_code = rng.choice(len(sector_keys), size=n_accounts, p=sector_p)
    region_code = rng.choice(len(region_keys), size=n_accounts, p=region_p)
    qual_code = rng.choice(len(qual_keys), size=n_accounts, p=qual_p)
    age_code = rng.choice(len(age_keys), size=n_accounts, p=age_p)

    sanctioned = np.clip(
        rng.lognormal(mix.ticket_log_mean, mix.ticket_log_sd, size=n_accounts),
        *mix.ticket_bounds,
    )
    business_age = np.clip(
        rng.gamma(mix.business_age_shape, mix.business_age_scale, size=n_accounts),
        *mix.business_age_bounds,
    ).astype(np.int64)
    vintage0 = rng.integers(*mix.vintage_bounds, size=n_accounts).astype(np.int64)

    sector_risk = np.array([v[1] for v in mix.sectors.values()])[sector_code]
    qual_adj = np.array([mix.risk_qualification[k] for k in qual_keys])[qual_code]
    age_adj = np.array([mix.risk_age_group[k] for k in age_keys])[age_code]

    z = (
        mix.risk_sector_gain * (sector_risk - 1.0)
        + mix.risk_business_age * business_age
        + mix.risk_vintage * vintage0
        + mix.risk_log_ticket * (np.log(sanctioned) - mix.ticket_log_mean)
        + qual_adj
        + age_adj
        + rng.normal(0.0, mix.risk_noise_sd, size=n_accounts)
    )
    p_default = _sigmoid(mix.risk_intercept + mix.risk_slope * z)
    is_defaulter = rng.random(n_accounts) < p_default

    # draw the fate of every account, then blank it for the survivors
    npa_month = rng.integers(mix.npa_month_lo, months, size=n_accounts).astype(np.int64)
    severity = np.clip(
        rng.normal(mix.severity_mean, mix.severity_sd, size=n_accounts),
        *mix.severity_bounds,
    )
    onset = np.clip(
        rng.normal(mix.onset_mean, mix.onset_sd, size=n_accounts), *mix.onset_bounds
    ).astype(np.int64)
    npa_month = np.where(is_defaulter, npa_month, -1)
    severity = np.where(is_defaulter, severity, 0.0)
    onset = np.where(is_defaulter, onset, 0)

    account_id = np.array([f"MSME{i:05d}" for i in range(n_accounts)])
    return (
        Population(
            account_id=account_id,
            portfolio_code=portfolio_code,
            sector_code=sector_code,
            region_code=region_code,
            qualification_code=qual_code,
            age_group_code=age_code,
            sanctioned=sanctioned,
            business_age_years=business_age,
            vintage_months_0=vintage0,
            is_defaulter=is_defaulter,
            npa_month=npa_month,
            severity=severity,
            onset=onset,
        ),
        portfolios,
    )


@dataclass(frozen=True)
class StressPath:
    """The shared latent stress state, as ``(N, M)`` arrays."""

    #: months until NPA (``npa_month - t``); :data:`NEVER` for survivors
    months_to_npa: np.ndarray
    #: True where the slide has begun but NPA has not yet happened
    in_slide: np.ndarray
    #: stress intensity in ``[0, decline_cap]``; 0 outside the slide
    decline: np.ndarray
    #: True at and after the NPA month (these rows never reach the panel)
    post_npa: np.ndarray

    def select(self, rows: np.ndarray) -> "StressPath":
        """The same latent state restricted to a subset of accounts.

        This is how one shared ``S_t`` reaches several portfolios: the stress
        is built once for the whole book, then each portfolio block observes
        its own slice of it through its own channels.

        Args:
            rows: integer indices of the accounts to keep.

        Returns:
            A view of the stress path for those accounts.
        """
        return StressPath(
            months_to_npa=self.months_to_npa[rows],
            in_slide=self.in_slide[rows],
            decline=self.decline[rows],
            post_npa=self.post_npa[rows],
        )


def build_stress_path(
    is_defaulter: np.ndarray,
    npa_month: np.ndarray,
    onset: np.ndarray,
    severity: np.ndarray,
    months: int,
    mix: PopulationMix,
) -> StressPath:
    """Expand each account's fate into a month-by-month stress intensity.

    Args:
        is_defaulter: ``(N,)`` boolean.
        npa_month: ``(N,)`` month index of NPA, ``-1`` for survivors.
        onset: ``(N,)`` months before NPA at which the slide begins.
        severity: ``(N,)`` steepness multiplier.
        months: observation window ``M``.
        mix: supplies the shared ``decline_*`` shape parameters.

    Returns:
        The ``(N, M)`` latent stress state.
    """
    grid = np.arange(months)[None, :]
    defaulting = is_defaulter[:, None]

    mtn = np.where(defaulting, npa_month[:, None] - grid, NEVER)
    post_npa = defaulting & (mtn <= 0)
    onset_col = np.maximum(onset, 1)[:, None]          # survivors carry onset 0
    in_slide = defaulting & (mtn > 0) & (mtn <= onset_col)

    progress = (onset_col - mtn) / onset_col           # 0 at onset -> ~1 at NPA
    decline = np.where(
        in_slide,
        np.minimum(
            mix.decline_cap,
            severity[:, None] * (mix.decline_floor_share + mix.decline_ramp_share * progress),
        ),
        0.0,
    )
    return StressPath(months_to_npa=mtn, in_slide=in_slide, decline=decline, post_npa=post_npa)

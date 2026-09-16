"""The latent stress process — who eventually goes bad, when, and how hard.

Two stages, both fully vectorised over the ``N`` accounts:

**Cross-section** (:func:`draw_population`).  Static borrower attributes, drawn
*per portfolio* from that portfolio's own sourced distributions
(``sources.yaml``), plus one shared latent-risk scorecard.  The scorecard is
deliberately weak: the irreducible-randomness term dominates, so a static
scorecard alone cannot predict well and the model is forced to learn the
*dynamic* deterioration, which is the whole early-warning thesis.  A portfolio
shifts the scorecard by exactly one number — :attr:`Portfolio.risk_offset`, a
log-odds constant calibrated so its realised 12-month default rate lands inside
the band ``sources.yaml`` records for it.  Accounts that will default also draw
their NPA month, the *onset* (how many months before NPA the slide begins) and
a *severity* (how steep it is).

**Time series** (:func:`build_stress_path`).  An ``(N, M)`` stress intensity
``decline`` — zero while the account is healthy, stepping to
``0.30 * severity`` the month the slide begins and ramping to
``1.00 * severity`` at NPA.  This is the shared latent state ``S_t``.

Why this split is the whole argument
------------------------------------
``S_t`` is ONE process with ONE shape for all eight portfolios.
:mod:`generator.channels` is the only place it becomes an *observation*, and
each portfolio maps it to its own channels with its own elasticities.  A
housing borrower and a KCC farmer under the same stress are the same event
seen through different instruments — which is precisely why one holistic model
across all borrower types is legitimate, and why a per-portfolio model would be
fitting the instrument rather than the borrower.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .noise import stream
from .portfolios import PopulationMix, Portfolio, portfolio_mix

__all__ = [
    "Population",
    "StressPath",
    "build_stress_path",
    "draw_population",
    "state_levels",
]

#: months-to-NPA placeholder for accounts that never reach NPA
NEVER = np.iinfo(np.int32).max


def _weights(mix: dict[str, float], levels: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Global level codes and normalised probabilities for one portfolio's mix.

    Args:
        mix: level name -> relative weight, as declared in ``sources.yaml``.
        levels: the panel-wide ordered level universe.

    Returns:
        ``(codes, probabilities)`` — codes index into ``levels``.
    """
    index = {level: code for code, level in enumerate(levels)}
    codes = np.array([index[k] for k in mix], dtype=np.int64)
    raw = np.array(list(mix.values()), dtype=np.float64)
    return codes, raw / raw.sum()


def _draw(rng: np.random.Generator, mix: dict[str, float],
          levels: tuple[str, ...], size: int) -> np.ndarray:
    """Draw ``size`` global level codes from a portfolio's mix."""
    codes, probabilities = _weights(mix, levels)
    return codes[rng.choice(codes.shape[0], size=size, p=probabilities)]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def state_levels(mix: PopulationMix) -> tuple[str, ...]:
    """Every state name, in region order then within-region declaration order."""
    names: list[str] = []
    for region in mix.region_levels:
        for state in mix.states_within_region.get(region, {}):
            if state not in names:
                names.append(state)
    return tuple(names)


@dataclass(frozen=True)
class Population:
    """One row per account: static attributes and the account's latent fate."""

    account_id: np.ndarray            # (N,) str
    portfolio_code: np.ndarray        # (N,) int  -> index into the registry order
    sector_code: np.ndarray           # (N,) int
    region_code: np.ndarray           # (N,) int
    state_code: np.ndarray            # (N,) int
    city_tier_code: np.ndarray        # (N,) int
    constitution_code: np.ndarray     # (N,) int
    qualification_code: np.ndarray    # (N,) int
    age_group_code: np.ndarray        # (N,) int
    nic_code: np.ndarray              # (N,) int, -1 where the borrower is not an enterprise
    sanctioned: np.ndarray            # (N,) float
    business_age_years: np.ndarray    # (N,) int
    vintage_months_0: np.ndarray      # (N,) int
    secured: np.ndarray               # (N,) int 0/1
    tenor_months: np.ndarray          # (N,) int
    interest_rate_pa: np.ndarray      # (N,) float
    bureau_score_0: np.ndarray        # (N,) float, NaN where the bureau has no file
    risk_z: np.ndarray                # (N,) float, the latent-risk index
    is_defaulter: np.ndarray          # (N,) bool
    npa_month: np.ndarray             # (N,) int, -1 when never
    severity: np.ndarray              # (N,) float, 0.0 when never
    onset: np.ndarray                 # (N,) int, 0 when never
    silent: np.ndarray                # (N,) bool, SD-D4: defaults with no chain

    def __len__(self) -> int:
        return int(self.account_id.shape[0])


def draw_population(
    seed: int,
    n_accounts: int,
    months: int,
    mix: PopulationMix,
    selected: dict[str, Portfolio] | None = None,
    noise: bool = True,
) -> tuple[Population, list[Portfolio]]:
    """Draw the static book and decide who defaults, when and how steeply.

    Attributes are drawn per portfolio, from that portfolio's own stream, so
    adding or removing a portfolio does not perturb the others' draws.  The
    *fate* — defaulter, NPA month, onset, severity — is drawn once from the
    shared stream, because it is one latent process.

    Args:
        seed: master seed; each stage derives its own named stream from it.
        n_accounts: number of accounts ``N``.
        months: observation window ``M`` (bounds the NPA month).
        mix: shared category universes, scorecard and stress shape.
        selected: registry to draw from; ``None`` uses the full registry.
        noise: SD-D4 master switch.  When True (the default, and what the
            shipped panel uses) a per-portfolio share of the defenders of this
            book go bad *silently*: no warning chain, the whole slide squeezed
            into one or two months.  When False no account is silent and the
            July 2026 fate draw is reproduced exactly.

    Returns:
        The population, and the portfolios in code order.
    """
    portfolios, shares = portfolio_mix(selected)
    states = state_levels(mix)
    rng = stream(seed, "population")
    portfolio_code = rng.choice(len(portfolios), size=n_accounts, p=np.asarray(shares))

    empty_int = lambda: np.zeros(n_accounts, dtype=np.int64)          # noqa: E731
    empty_float = lambda: np.zeros(n_accounts, dtype=np.float64)      # noqa: E731
    sector_code, region_code, state_code = empty_int(), empty_int(), empty_int()
    city_tier_code, constitution_code = empty_int(), empty_int()
    qualification_code, age_group_code = empty_int(), empty_int()
    sanctioned, business_age = empty_float(), empty_int()
    vintage0, secured, tenor = empty_int(), empty_int(), empty_int()
    rate, ticket_centre = empty_float(), empty_float()
    risk_offset = empty_float()

    for code, portfolio in enumerate(portfolios):
        rows = np.flatnonzero(portfolio_code == code)
        if rows.size == 0:
            continue
        block = _draw_block(
            stream(seed, f"population:{portfolio.key}"), portfolio, mix, states, rows.size
        )
        for target, name in (
            (sector_code, "sector_code"), (region_code, "region_code"),
            (state_code, "state_code"), (city_tier_code, "city_tier_code"),
            (constitution_code, "constitution_code"),
            (qualification_code, "qualification_code"),
            (age_group_code, "age_group_code"), (sanctioned, "sanctioned"),
            (business_age, "business_age"), (vintage0, "vintage0"),
            (secured, "secured"), (tenor, "tenor"), (rate, "rate"),
        ):
            target[rows] = block[name]
        assert portfolio.population is not None
        ticket_centre[rows] = portfolio.population.ticket_log_mean
        risk_offset[rows] = portfolio.risk_offset

    nic_names = [mix.nic_groups.get(level) for level in mix.sector_levels]
    nic_levels = tuple(name for name in nic_names if name is not None)
    nic_index = {name: code for code, name in enumerate(nic_levels)}
    sector_to_nic = np.array(
        [nic_index[name] if name is not None else -1 for name in nic_names], dtype=np.int64
    )
    nic_code = sector_to_nic[sector_code]

    # ---- the shared latent-risk scorecard -------------------------------- #
    sector_risk = np.array(
        [mix.sector_risk[level] for level in mix.sector_levels]
    )[sector_code]
    qual_adj = np.array(
        [mix.risk_qualification.get(level, 0.0) for level in mix.qualification_levels]
    )[qualification_code]
    age_adj = np.array(
        [mix.risk_age_group.get(level, 0.0) for level in mix.age_group_levels]
    )[age_group_code]

    z = (
        mix.risk_sector_gain * (sector_risk - 1.0)
        + mix.risk_business_age * business_age
        + mix.risk_vintage * vintage0
        + mix.risk_log_ticket * (np.log(sanctioned) - ticket_centre)
        + qual_adj
        + age_adj
        + risk_offset
        + rng.normal(0.0, mix.risk_noise_sd, size=n_accounts)
    )
    p_default = _sigmoid(mix.risk_intercept + mix.risk_slope * z)
    # The scorecard gives the probability of going bad AT SOME POINT in the
    # observation window, so a longer window would otherwise thin the annual
    # rate every metric is quoted in. Re-expand it from the reference window's
    # implied monthly hazard, which makes the per-portfolio default-rate bands
    # a property of the book rather than of --months. At the reference window
    # the arithmetic is skipped entirely, so that panel is bit-identical.
    exposure = max(months - mix.npa_month_lo, 1)
    if exposure != mix.hazard_reference_months:
        p_default = 1.0 - np.power(1.0 - p_default, exposure / mix.hazard_reference_months)
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

    # ---- SD-D4: the defaulters that arrive with no warning --------------- #
    # Fraud, a death, a buyer who never paid, a job lost with no notice.  They
    # are drawn from their OWN stream, so switching them off leaves every other
    # stage bit-identical, and they change only the SHAPE of the slide — never
    # who defaults, when, or the portfolio's realised rate.  This is the honest
    # ceiling on how well any model can score this book.
    silent = np.zeros(n_accounts, dtype=bool)
    if noise:
        silent_rng = stream(seed, "silent")
        share = np.array([p.silent_share for p in portfolios])[portfolio_code]
        silent = is_defaulter & (silent_rng.random(n_accounts) < share)
        low, high = mix.silent_onset_bounds
        compressed = silent_rng.integers(low, high + 1, size=n_accounts)
        onset = np.where(silent, compressed, onset)
        severity = np.where(
            silent, np.maximum(severity, mix.silent_severity_floor), severity
        )

    # ---- bureau file (7% of borrowers have none) ------------------------- #
    bureau = stream(seed, "bureau")
    score = np.clip(
        bureau.normal(mix.bureau_score_mean, mix.bureau_score_sd, n_accounts)
        - mix.bureau_risk_gain * z,
        *mix.bureau_score_bounds,
    )
    score[bureau.random(n_accounts) < mix.bureau_missing_share] = np.nan

    account_id = np.array([f"MSME{i:05d}" for i in range(n_accounts)])
    return (
        Population(
            account_id=account_id,
            portfolio_code=portfolio_code,
            sector_code=sector_code,
            region_code=region_code,
            state_code=state_code,
            city_tier_code=city_tier_code,
            constitution_code=constitution_code,
            qualification_code=qualification_code,
            age_group_code=age_group_code,
            nic_code=nic_code,
            sanctioned=sanctioned,
            business_age_years=business_age,
            vintage_months_0=vintage0,
            secured=secured,
            tenor_months=tenor,
            interest_rate_pa=rate,
            bureau_score_0=score,
            risk_z=z,
            is_defaulter=is_defaulter,
            npa_month=npa_month,
            severity=severity,
            onset=onset,
            silent=silent,
        ),
        portfolios,
    )


def _draw_block(
    rng: np.random.Generator,
    portfolio: Portfolio,
    mix: PopulationMix,
    states: tuple[str, ...],
    size: int,
) -> dict[str, np.ndarray]:
    """Draw one portfolio's static attributes from its own sourced mixes.

    Args:
        rng: this portfolio's population stream.
        portfolio: the portfolio being drawn.
        mix: shared category universes.
        states: the panel-wide ordered state universe.
        size: number of accounts in this block.

    Returns:
        Attribute name -> ``(size,)`` array of global level codes or values.
    """
    population = portfolio.population
    assert population is not None

    region_code = _draw(rng, population.regions, mix.region_levels, size)
    # state is drawn CONDITIONAL on region, so the region cut keeps the shares
    # the July 2026 build published while the new state column stays sourced
    state_code = np.zeros(size, dtype=np.int64)
    for code, region in enumerate(mix.region_levels):
        within = mix.states_within_region.get(region)
        if not within:
            continue
        rows = np.flatnonzero(region_code == code)
        if rows.size:
            state_code[rows] = _draw(rng, within, states, rows.size)

    sanctioned = np.clip(
        rng.lognormal(population.ticket_log_mean, population.ticket_log_sd, size=size),
        *population.ticket_bounds,
    )
    business_age = np.clip(
        rng.gamma(population.business_age_shape, population.business_age_scale, size=size),
        *population.business_age_bounds,
    ).astype(np.int64)
    tenor_lo, tenor_hi = population.tenor_bounds
    tenor = (
        np.full(size, tenor_lo, dtype=np.int64)
        if tenor_hi <= tenor_lo
        else rng.integers(tenor_lo, tenor_hi + 1, size=size).astype(np.int64)
    )
    return {
        "sector_code": _draw(rng, population.sectors, mix.sector_levels, size),
        "region_code": region_code,
        "state_code": state_code,
        "city_tier_code": _draw(rng, population.city_tiers, mix.city_tier_levels, size),
        "constitution_code": _draw(
            rng, population.constitutions, mix.constitution_levels, size),
        "qualification_code": _draw(
            rng, population.qualifications, mix.qualification_levels, size),
        "age_group_code": _draw(rng, population.age_groups, mix.age_group_levels, size),
        "sanctioned": sanctioned,
        "business_age": business_age,
        "vintage0": rng.integers(*population.vintage_bounds, size=size).astype(np.int64),
        "secured": (rng.random(size) < population.secured_share).astype(np.int64),
        "tenor": tenor,
        # no risk tilt on price: a rate that encoded the borrower's latent risk
        # would smuggle the label into a static column
        "rate": rng.uniform(*population.rate_bounds, size=size),
    }


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
    silent: np.ndarray | None = None,
) -> StressPath:
    """Expand each account's fate into a month-by-month stress intensity.

    Args:
        is_defaulter: ``(N,)`` boolean.
        npa_month: ``(N,)`` month index of NPA, ``-1`` for survivors.
        onset: ``(N,)`` months before NPA at which the slide begins.
        severity: ``(N,)`` steepness multiplier.
        months: observation window ``M``.
        mix: supplies the shared ``decline_*`` shape parameters.
        silent: ``(N,)`` SD-D4 flag.  A silent defaulter does not ramp — it
            stops.  Its one or two slide months sit at full stress instead of
            at the foot of the ramp, so the account goes from clean to NPA with
            nothing in between for an early-warning model to have seen.

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
    if silent is not None and silent.any():
        progress = np.where(silent[:, None], 1.0, progress)
    decline = np.where(
        in_slide,
        np.minimum(
            mix.decline_cap,
            severity[:, None] * (mix.decline_floor_share + mix.decline_ramp_share * progress),
        ),
        0.0,
    )
    return StressPath(months_to_npa=mtn, in_slide=in_slide, decline=decline, post_npa=post_npa)

"""Forward-looking labels, the panel row filter, and the rates they must hit.

Two labels, both computed over the account's *future* and both honest about
the window they need:

``default_within_12m`` (the primary, unchanged)
    1 when the account crosses 90+ DPD (NPA) between 1 and 12 months *after*
    the observed month.  This is the definition the whole project is graded on.

``sma2_within_6m`` (SD-D5, new)
    1 when the account reaches **SMA-2 or worse within the next 6 months** —
    SMA-2 being the RBI special-mention category for 61-90 days past due
    (SMA-0 is 1-30, SMA-1 is 31-60, and 90+ is NPA).  It is read off the
    *simulated days-past-due series*, not off the NPA date, which matters:
    the transient-stress population (SD-D4) genuinely reaches 60-85 DPD and
    then **cures**, so an account can be SMA-2 positive and NPA negative.  That
    is what makes it a different label rather than a rescaled copy of the first
    one, and it is why the ratio between the two rates is worth reporting.

Two things keep both honest, and both are reproduced here:

* **Only standard rows are scored.**  A row is emitted only while the account
  still looks STANDARD today — at or after the NPA month it is dropped, and so
  is any month whose observed DPD has already reached the NPA threshold.  The
  model therefore never sees an account that has already gone bad.
* **``labelable``** marks the rows whose full 12-month forward window is
  inside the observation window.  Earlier rows carry a label that is only
  *conditionally* complete, so out-of-time work filters on this flag.

All of it is ``(N, M)`` array work — the forward window is a comparison
against ``months_to_npa`` or a handful of shifted views of the DPD series,
never a per-row scan.

The rates are asserted, not hoped for
-------------------------------------
:func:`assert_base_rates` is called by the CLI on every generated panel.  It
fails the run if the book's 12-month rate leaves the band pre-registered in
``validation/criteria.yaml`` (DR-03), if any portfolio leaves the band
``sources.yaml`` records for it, or if the SMA-2 rate is implausible next to
the NPA rate.  A generator that quietly drifts out of its own bands between
tuning rounds is worse than one that stops.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import sources
from .latent import NEVER, StressPath
from .portfolios import Portfolio

__all__ = [
    "SMA2_DPD",
    "SMA2_HORIZON",
    "BaseRates",
    "assert_base_rates",
    "default_within_12m",
    "labelable_rows",
    "measure_base_rates",
    "months_to_npa_column",
    "sma2_within_6m",
    "standard_rows",
]

#: days past due at which an account is SMA-2 (RBI: SMA-2 is 61-90 DPD)
SMA2_DPD = 61.0

#: forward window of the secondary label, in months
SMA2_HORIZON = 6


def standard_rows(stress: StressPath, dpd: np.ndarray, npa_dpd: float) -> np.ndarray:
    """Rows to emit: still pre-NPA, and still looking standard today.

    Args:
        stress: the latent stress path (supplies the NPA month).
        dpd: ``(N, M)`` observed days-past-due.
        npa_dpd: the NPA threshold in days (90).

    Returns:
        ``(N, M)`` boolean mask of panel rows.
    """
    return ~stress.post_npa & (dpd < npa_dpd)


def default_within_12m(stress: StressPath, horizon: int) -> np.ndarray:
    """Label: does NPA fall in the next ``horizon`` months?

    Args:
        stress: the latent stress path.
        horizon: forward window in months (12).

    Returns:
        ``(N, M)`` int array of 0/1.
    """
    mtn = stress.months_to_npa
    return ((mtn >= 1) & (mtn <= horizon)).astype(np.int64)


def sma2_within_6m(
    dpd: np.ndarray, horizon: int = SMA2_HORIZON, threshold: float = SMA2_DPD
) -> np.ndarray:
    """Label: does the account reach SMA-2 or worse in the next ``horizon`` months?

    Read off the DPD series rather than off the NPA date, so it catches both
    populations that matter: accounts on their way to NPA, and the transient-
    stress accounts that reach 61-90 DPD and cure.  Months past the end of the
    observation window count as "no" — the same convention ``labelable``
    exists to police for the primary label.

    Args:
        dpd: ``(N, M)`` observed days-past-due, INCLUDING the post-NPA months
            the row filter later drops (an account already at 120 DPD is
            certainly SMA-2-or-worse, and the month before it must say so).
        horizon: forward window in months.
        threshold: days past due at which SMA-2 begins.

    Returns:
        ``(N, M)`` int array of 0/1.
    """
    reached = dpd >= threshold
    months = dpd.shape[1]
    future = np.zeros_like(reached)
    for step in range(1, horizon + 1):
        if step >= months:
            break
        future[:, : months - step] |= reached[:, step:]
    return future.astype(np.int64)


def labelable_rows(n_accounts: int, months: int, horizon: int) -> np.ndarray:
    """Rows whose full forward window is observable.

    Args:
        n_accounts: number of accounts ``N``.
        months: observation window ``M``.
        horizon: forward window in months.

    Returns:
        ``(N, M)`` int array of 0/1, constant across accounts.
    """
    flag = (np.arange(months) <= months - horizon - 1).astype(np.int64)
    return np.broadcast_to(flag[None, :], (n_accounts, months))


def months_to_npa_column(stress: StressPath) -> np.ndarray:
    """Months until NPA for defaulters, ``-1`` for accounts that never go bad.

    Args:
        stress: the latent stress path.

    Returns:
        ``(N, M)`` int array.
    """
    mtn = stress.months_to_npa
    return np.where(mtn == NEVER, -1, mtn)


# --------------------------------------------------------------------------- #
# The rates, measured and asserted
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BaseRates:
    """What the generated book actually did, on the labelable rows."""

    #: mean of ``default_within_12m`` over rows with a complete forward window
    book: float
    #: portfolio contract code -> its own 12-month rate
    by_portfolio: dict[str, float]
    #: mean of ``sma2_within_6m`` over the same rows
    sma2: float
    #: ``sma2 / book`` — the two raw rates, which carry DIFFERENT windows
    sma2_to_npa: float
    #: the comparable quantity: how much more often an account enters SMA-2
    #: than it goes NPA, per unit of time
    sma2_to_npa_events: float
    #: share of defaulting accounts that arrive with no warning chain
    silent_share: float


def measure_base_rates(panel, accounts) -> BaseRates:
    """Measure the rates the generator is contractually held to.

    Args:
        panel: the assembled account-month panel.
        accounts: one row per account.

    Returns:
        The measured rates.
    """
    rows = panel[panel["labelable"] == 1]
    by_portfolio = {
        str(code): float(value)
        for code, value in rows.groupby("portfolio", observed=True)[
            "default_within_12m"
        ].mean().items()
    }
    book = float(rows["default_within_12m"].mean())
    sma2 = float(rows["sma2_within_6m"].mean())
    defaulters = accounts[accounts["is_defaulter"] == 1]
    silent = (
        float(defaulters["silent_default"].mean()) if len(defaulters) else 0.0
    )
    ratio = sma2 / book if book else 0.0
    return BaseRates(
        book=book,
        by_portfolio=by_portfolio,
        sma2=sma2,
        sma2_to_npa=ratio,
        sma2_to_npa_events=ratio * (12.0 / SMA2_HORIZON),
        silent_share=silent,
    )


def assert_base_rates(
    rates: BaseRates, portfolios: list[Portfolio], strict: bool = True
) -> list[str]:
    """Check the measured rates against their pre-registered bands.

    The book-level band is DR-03's, transcribed into ``sources.yaml``; each
    portfolio's is the one ``sources.yaml`` records with its citation.  Neither
    was chosen after seeing a result, and neither is widened here.

    Args:
        rates: the measured rates.
        portfolios: the registry that was generated, in code order.
        strict: raise on failure (the CLI's behaviour) rather than returning
            the problems (which is how a test reports all of them at once).

    Returns:
        The list of breaches; empty when the book is inside every band.

    Raises:
        AssertionError: if ``strict`` and any band is breached.
    """
    low, high = sources.value("book.annual_slippage_band")
    problems: list[str] = []
    if not low <= rates.book <= high:
        problems.append(
            f"book 12-month default rate {rates.book:.4f} outside "
            f"the pre-registered DR-03 band [{low}, {high}]"
        )
    for portfolio in portfolios:
        observed = rates.by_portfolio.get(portfolio.code)
        if observed is None:
            continue
        band_low, band_high = portfolio.default_rate_band
        if not band_low <= observed <= band_high:
            problems.append(
                f"{portfolio.code} 12-month default rate {observed:.4f} outside "
                f"its sourced band [{band_low}, {band_high}]"
            )
    ratio_low, ratio_high = sources.value("book.sma2_to_npa_event_ratio_band")
    if not ratio_low <= rates.sma2_to_npa_events <= ratio_high:
        problems.append(
            f"SMA-2 within 6m ({rates.sma2:.4f}) against a 12-month NPA rate of "
            f"{rates.book:.4f} implies {rates.sma2_to_npa_events:.2f} SMA-2 entries "
            f"per NPA per unit time; plausible range is [{ratio_low}, {ratio_high}]"
        )
    if strict and problems:
        raise AssertionError(
            "generated book left its pre-registered bands:\n  " + "\n  ".join(problems)
        )
    return problems

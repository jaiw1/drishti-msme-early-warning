"""Forward-looking labels and the panel row filter.

The label is unchanged from the original simulator and is the definition the
whole project is graded on:

    ``default_within_12m`` = 1 when the account crosses 90+ DPD (NPA) between
    1 and 12 months *after* the observed month.

Two things keep it honest, and both are reproduced here:

* **Only standard rows are scored.**  A row is emitted only while the account
  still looks STANDARD today — at or after the NPA month it is dropped, and so
  is any month whose observed DPD has already reached the NPA threshold.  The
  model therefore never sees an account that has already gone bad.
* **``labelable``** marks the rows whose full 12-month forward window is
  inside the observation window.  Earlier rows carry a label that is only
  *conditionally* complete, so out-of-time work filters on this flag.

All three are ``(N, M)`` computations — the forward window is a comparison
against ``months_to_npa``, not a per-row scan.
"""

from __future__ import annotations

import numpy as np

from .latent import NEVER, StressPath

__all__ = ["default_within_12m", "labelable_rows", "months_to_npa_column", "standard_rows"]


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

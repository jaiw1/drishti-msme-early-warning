"""Vectorised synthetic MSME loan-performance panel generator (DRISHTi).

One row of the output panel = one loan account observed in one month.  The
model's job is to predict "will this account go bad (NPA, 90+ DPD) within the
next 12 months?" while the account still looks STANDARD today — i.e. early
warning.

Design principles, unchanged from the original single-file simulator:

* **Deterioration is ORDERED** — cash inflow / GST sales dip first (~12 months
  out), then credit-limit utilisation creeps up (~10), then bounces and
  min-balance breaches (~6), and only then does days-past-due rise (~3).  The
  leading signal is business cash-flow, NOT "already paying late", which is
  what forces the model to learn genuine 12-month-ahead early warning.
* **Realistic, not trivially separable** — heavy noise, transient stress
  episodes on healthy accounts (hard negatives), variable ramp lengths.
* **Leakage-safe** — features use only the account's own past and present;
  ``labelable`` marks the rows with a fully observable forward window.
* **Calibrated to IDBI's book** — ~2.7%/year slippage, ₹3L-₹5cr tickets,
  Micro/Small/Medium segments, Indian sectors and regions.

Structure
---------
=====================  ====================================================
:mod:`.portfolios`     portfolio registry + per-portfolio parameter blocks
:mod:`.constitutions`  borrower taxonomy (today: MSMED size segment)
:mod:`.latent`         who defaults, when, and the shared latent stress S_t
:mod:`.channels`       how that stress becomes bank-observable signals
:mod:`.noise`          RNG streams, measurement noise, hard negatives
:mod:`.labels`         the forward label and the panel row filter
:mod:`.build`          assembly + CLI
=====================  ====================================================

Everything is computed as per-portfolio ``(N, M)`` numpy arrays; the only
Python-level loops are over months (36-48) and over the registry.
"""

from .build import ACCOUNT_COLUMNS, PANEL_COLUMNS, GeneratorConfig, generate, main, write
from .portfolios import PORTFOLIOS, Portfolio

__all__ = [
    "ACCOUNT_COLUMNS",
    "PANEL_COLUMNS",
    "PORTFOLIOS",
    "GeneratorConfig",
    "Portfolio",
    "generate",
    "main",
    "write",
]

"""Vectorised synthetic loan-performance panel generator (DRISHTi).

One row of the output panel = one loan account observed in one month.  The
model's job is to predict "will this account go bad (NPA, 90+ DPD) within the
next 12 months?" while the account still looks STANDARD today — i.e. early
warning.

The book is IDBI's retail book, restricted to the **eight portfolios** DRISHTi
scores: MSME cash credit, MSME term loan, housing, education, agriculture
(KCC), unsecured personal, loan against property and vehicle finance.

Design principles
-----------------
* **One latent stress, eight sets of instruments.**  A single latent process
  ``S_t`` decides who deteriorates, when and how steeply; each portfolio
  observes it through the channels a bank actually has for that product, and a
  channel a portfolio does not have is NaN, never zero.  That separation — the
  borrower's trouble is shared, the instruments are not — is the generative
  reason ONE model across all borrower types is legitimate.
* **Deterioration is ORDERED** — the cash side moves first (GST sales, salary
  credit, crop receipts, rental income, commute spend), then the money stops
  arriving in full, then bounces and min-balance breaches, and only then does
  days-past-due rise.  The leading signal is never "already paying late", which
  is what forces the model to learn genuine 12-month-ahead early warning.
* **Realistic, not trivially separable** — and this is SD-D4's whole job.  A
  per-portfolio share of defaulters arrives **silently**, with no warning chain
  at all; of the rest, any given link of the chain is dark for about a quarter
  of them.  About a fifth of healthy accounts pass through a **transient stress
  episode** that moves the same instruments, part-pays the instalment and, for
  a share of them, goes genuinely past due before curing.  **Seasonal
  confounders** — festival, quarter-end, monsoon, bonus — move healthy accounts
  in the direction stress does.  Channels arrive with **measurement noise**:
  GST returns a month or two late, collateral and bureau scores held stale
  between refreshes, duplicated batches, reversed payments.  And some of it
  simply is not there: **MAR missingness** for Individuals with no GST return,
  the self-employed with no payroll, the 7% with no bureau file, and
  statement-feed gaps.  All of it is switchable with
  ``GeneratorConfig(noise=...)``; **the default is ON and the shipped panel is
  the noisy one.**  ``noise=False`` exists so the equivalence suite can
  reproduce the July 2026 fingerprint, and a panel generated with it is not the
  dataset DRISHTi is trained or validated on.
* **Leakage-safe** — features use only the account's own past and present;
  ``labelable`` marks the rows with a fully observable forward window.
* **Sourced, and honest about what is not.**  Every empirical parameter lives
  in ``sources.yaml`` with a citation and a confidence level; ``assumed`` is a
  first-class value and means exactly what it says.

Structure
---------
=====================  ====================================================
:mod:`.sources`        the sourced-parameter store and its provenance rules
:mod:`.portfolios`     portfolio registry + per-portfolio parameter blocks
:mod:`.constitutions`  borrower taxonomy (MSMED size segment, legal form)
:mod:`.latent`         who defaults, when, and the shared latent stress S_t
:mod:`.channels`       how that stress becomes bank-observable signals
:mod:`.noise`          RNG streams, measurement noise, hard negatives, gaps
:mod:`.labels`         the two forward labels, the row filter, the rate checks
:mod:`.build`          assembly + CLI
=====================  ====================================================

Everything is computed as per-portfolio ``(N, M)`` numpy arrays; the only
Python-level loops are over months (36-48) and over the registry.
"""

from .build import (
    ACCOUNT_COLUMNS,
    LEGACY_PANEL_COLUMNS,
    PANEL_COLUMNS,
    GeneratorConfig,
    generate,
    main,
    write,
)
from .portfolios import PORTFOLIOS, Portfolio, registry

__all__ = [
    "ACCOUNT_COLUMNS",
    "LEGACY_PANEL_COLUMNS",
    "PANEL_COLUMNS",
    "PORTFOLIOS",
    "GeneratorConfig",
    "Portfolio",
    "generate",
    "main",
    "registry",
    "write",
]

"""Synthetic MSME loan-performance PANEL generator — IDBI Innovate 2026, Track 4
(MSME loan Early-Warning System)

One row = one loan account observed in one month.
Goal: let a model predict "will this account go bad (NPA, 90+ DPD) within the next
12 months?" while the account still looks STANDARD today — i.e. early warning.

The simulator itself lives in the :mod:`generator` package, where it is
vectorised as per-portfolio ``(N, M)`` numpy arrays instead of a per-account,
per-month Python loop.  This file stays as the pipeline's entry point:

    python3 src/generate_data.py                 # 9,000 x 36 into data/

For anything other than the default population, call the package CLI:

    python3 -m generator.build --seed 20260709 --n 45000 --months 48 --out data

Design principles baked in (see :mod:`generator` for the full statement):
  * Deterioration is ORDERED — cash-inflow/sales dip first (~t-12), utilisation
    creep (~t-10), bounces (~t-6), then days-past-due last (~t-3). The leading
    signal is business cash-flow, NOT "already paying late".
  * Realistic, not trivially separable — heavy noise, transient stress on
    healthy accounts (hard negatives), variable ramp lengths.
  * Leakage-safe — features use only the account's own past/present; the
    forward label is only fully observable where ``labelable`` is 1.
  * Calibrated to reality — ~2.7%/year slippage, Indian ₹ ticket sizes and sectors.

Output:
  data/msme_loan_panel.csv          full account-month panel (raw signals + trailing features + label)
  data/accounts_static.csv          one row per account (static attributes + outcome)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator.build import main  # noqa: E402  (path shim must run first)

if __name__ == "__main__":
    main()

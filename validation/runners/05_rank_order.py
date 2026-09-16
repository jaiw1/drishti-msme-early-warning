"""
05 Rank order — bands and deciles inside every portfolio

Pre-registered criteria this runner answers: DR-11, DR-12

Consumes
--------
* `validation.runners._shared.get_rank_order_exhibit` — `export_demo.
  rank_order_exhibit` (imported, not copied) called over the POOLED
  grouped-holdout test population (every eligible account-month row, not one
  frozen reference month), horizon = 8 months, giving `bands_monotone`,
  `monotone_decile_step_fraction` (literal) and
  `monotone_decile_step_fraction_ci` (CI-aware) pooled and per portfolio.

Produces
--------
* `figures/rank_order_small_multiples.png`
* `figures/decile_steps.png`
* DR-11: one breakdown cell per portfolio, `bands_monotone` (True/False, via
  `op: monotone_increasing` on the three band rates).
* DR-12: one breakdown cell per portfolio, `monotone_decile_step_fraction`
  (float, `op: ge 0.9`).

INTERPRETATION — DR-11's note ("the ordering must hold in each of the
exhibit's months, not only pooled") is genuinely ambiguous against the actual
exhibit `export_demo.py`/DM-3 built: `rank_order_exhibit` has no per-calendar-
month axis at all (its `by_decile` has 10 rows for SCORE deciles, its
`by_band` has 3 rows for Green/Amber/Red — neither is a month). Two readings
were considered:
  (a) "months" means calendar months, and the check should be repeated at
      several distinct reference months;
  (b) "months" is describing "the exhibit's constituent parts" (loosely,
      possibly a slip for "portfolios"/"cuts"), and the intended contrast is
      PER-PORTFOLIO vs POOLED-ACROSS-PORTFOLIOS — which is exactly
      `scope: per_portfolio` plus the note's own closing clause, "not only
      pooled".
We took (b): DR-11/DR-12 are graded on EVERY one of the 8 portfolio cells
(never only the pooled number), which is also the reading L5/DM-3's own report
used when it stated "DR-11 bands monotone: 8/8 + pooled". Reading (a) is not
literally supported by the artefact the note names ("the 8-month rank-order
exhibit... branch 0914ac6") — that branch's exhibit is single-snapshot by
construction. To still give (a) some weight without inventing a second,
un-pre-registered gate, this runner feeds the exhibit the FULL row-level
holdout-test population pooled across every eligible calendar month (not
export_demo.py's own single frozen `REF_MONTH`), so the pooled and
per-portfolio numbers already reflect every month's evidence, not one
arbitrary snapshot date. The pooled result is reported (`Result.detail`), not
graded — DR-11/DR-12's registered `scope` is `per_portfolio`, so only the 8
portfolio cells are in the breakdown that the harness grades.

DR-12 is expected to fail on the literal arithmetic at this score's shape (see
`Result.detail`): almost all realised risk concentrates in the top decile, so
deciles 1-9 sit at a few tenths of a percent and their ordering is dominated
by single-account noise. The CI-aware fraction (a step counts as a reversal
only when the two deciles' Wilson intervals do not overlap) is reported
alongside, per the brief's "grade the literal one because it is what was
registered" — DR-12 gates on the literal fraction, never on the CI-aware one.
"""

from __future__ import annotations

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh


def _small_multiples_figure(ctx: RunnerContext, exhibit: dict) -> str:
    import matplotlib.pyplot as plt

    cells = exhibit["by_portfolio"]
    ncols = 4
    nrows = -(-len(cells) // ncols) if cells else 1
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
    colors = {"Green": "#2ea043", "Amber": "#d29922", "Red": "#da3633"}
    for i, cell in enumerate(cells):
        ax = axes[i // ncols][i % ncols]
        bands = cell["by_band"]
        ax.bar([b["band"] for b in bands], [b["bad_rate"] for b in bands],
               color=[colors.get(b["band"], "#8b949e") for b in bands])
        ax.set_title(f"{cell['portfolio']} {'OK' if cell['bands_monotone'] else 'NOT MONOTONE'}", fontsize=8)
        ax.tick_params(labelsize=7)
    for j in range(len(cells), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle("DR-11 — band default rate by portfolio", y=1.02)
    return sh.savefig(fig, ctx, "rank_order_small_multiples.png")


def _decile_steps_figure(ctx: RunnerContext, exhibit: dict, floor: float) -> str:
    import matplotlib.pyplot as plt

    cells = exhibit["by_portfolio"]
    ncols = 4
    nrows = -(-len(cells) // ncols) if cells else 1
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows), squeeze=False)
    for i, cell in enumerate(cells):
        ax = axes[i // ncols][i % ncols]
        deciles = cell["by_decile"]
        rates = [d["bad_rate"] for d in deciles]
        frac = cell["monotone_decile_step_fraction"]
        color = "#2ea043" if frac >= floor else "#da3633"
        ax.plot(range(1, len(rates) + 1), rates, "o-", color=color)
        ax.set_title(f"{cell['portfolio']} {frac:.0%}", fontsize=8)
        ax.tick_params(labelsize=7)
    for j in range(len(cells), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle(f"DR-12 — decile default rate by portfolio (floor {floor:.0%})", y=1.02)
    return sh.savefig(fig, ctx, "decile_steps.png")


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if not ({"DR-11", "DR-12"} & set(by_id)):
        return []

    exhibit = sh.get_rank_order_exhibit(ctx)
    cells = exhibit["by_portfolio"]
    thr = exhibit.get("_thresholds", {})
    thr_note = (f"operating thresholds amber={thr.get('amber')}, red={thr.get('red')} "
                f"({'live cost-minimising' if thr.get('is_live') else 'FALLBACK legacy 0.04/0.40'})")
    results: list[Result] = []

    if "DR-11" in by_id:
        # `op: monotone_increasing` — Criterion.check() takes `list(value)` and
        # tests strict increase itself, so `value` must be the SEQUENCE (Green,
        # Amber, Red rates), not a pre-computed bool: the harness grades, the
        # runner measures. `by_band` is already in Green/Amber/Red order (the
        # `BANDS` tuple in export_demo.py), so it is passed through as-is.
        breakdown = [
            dict(level=c["portfolio"], value=[b["bad_rate"] for b in c["by_band"]], ci=None, n=c["n"])
            for c in cells
        ]
        fig = _small_multiples_figure(ctx, exhibit)
        pooled = "monotone" if exhibit["bands_monotone"] else "NOT monotone"
        results.append(Result(
            "DR-11", breakdown=breakdown, figures=[fig],
            detail=(f"pooled (reported, not gated — scope is per_portfolio): {pooled}, "
                    f"Green {exhibit['by_band'][0]['bad_rate']:.4f} -> Amber "
                    f"{exhibit['by_band'][1]['bad_rate']:.4f} -> Red {exhibit['by_band'][2]['bad_rate']:.4f}; {thr_note}"),
        ))

    if "DR-12" in by_id:
        crit = by_id["DR-12"]
        breakdown = [
            dict(level=c["portfolio"], value=c["monotone_decile_step_fraction"], ci=None, n=c["n"])
            for c in cells
        ]
        fig = _decile_steps_figure(ctx, exhibit, float(crit.threshold))
        ci_aware = {c["portfolio"]: c["monotone_decile_step_fraction_ci"] for c in cells}
        results.append(Result(
            "DR-12", breakdown=breakdown, figures=[fig],
            detail=(f"literal fraction gates (per the brief); CI-aware fraction reported only "
                    f"(a step only counts as a reversal when the two deciles' Wilson intervals do "
                    f"not overlap): {ci_aware}. pooled literal="
                    f"{exhibit['monotone_decile_step_fraction']:.4f}, pooled CI-aware="
                    f"{exhibit['monotone_decile_step_fraction_ci']:.4f} (reported, not gated); {thr_note}."),
        ))

    return results

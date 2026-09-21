"""
11 Fairness — reported honestly, never tuned

Pre-registered criteria this runner answers: DR-24, DR-25

Consumes
--------
* `validation.runners._shared.get_holdout` — the SAME grouped-holdout model
  and predictions DR-01/DR-02 report on (never a second split).
* `validation.runners._shared.get_rag_thresholds` — the LIVE cost-minimising
  operating thresholds (`data/demo_data.json`), falling back to the legacy
  0.04/0.40 pair with `is_live=False` if unavailable.

Produces
--------
* `figures/fairness_flag_rates.png`
* `figures/fairness_tpr_gaps.png`
* DR-24 (four-fifths adverse-impact ratio) and DR-25 (TPR gap), one
  breakdown cell per protected-proxy ATTRIBUTE (`scope: per_cut, cut:
  "protected_proxies"` — a pseudo-cut per `criteria.py`'s schema, not one of
  the nine registered cuts; its "levels" are the four attributes below, each
  contributing one cell — the per-GROUP numbers within an attribute are
  reported in `detail`, not as separate graded cells).

Method, as pre-registered
--------------------------
For each protected-proxy attribute — promoter_age_group, qualification,
geography (`region`), constitution (criteria.yaml DR-24's own note; DRISHTi
holds no gender, caste, religion or marital-status field at all) — a row is
"flagged" when its score is Amber or Red at the live operating threshold
(i.e. not Green: the threshold at which the cockpit would actually put an
account in front of a relationship manager). This is an INTERPRETATION:
`criteria.yaml` says "at the live operating threshold" (singular) while the
cockpit actually carries two (amber, red); Amber-or-above is the natural
single "flagged for review" line given a two-threshold banding scheme, and is
recorded here rather than silently assumed.

  DR-24 (four-fifths rule): least-flagged group's flag rate / most-flagged
  group's flag rate, within each attribute.
  DR-25 (TPR gap): max minus min true-positive rate (P(flagged | actually
  defaulted)) across the groups of each attribute.

Groups with fewer than the criterion's own `min_n` (500) rows are excluded
from the min/max so one thin group cannot dominate the ratio/gap; every
group's raw numbers (n, flag rate, TPR, Wilson CI) are still reported in
`detail` regardless of size — "reported honestly" per the plan, nothing is
dropped from the OUTPUT, only from the min/max comparison.

REPORTED, NOT GATED (severity: report) — per criteria.yaml, any breach goes
in the README's "what we did not build, and why", never tuned away.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from validation.criteria import Criterion, Result, RunnerContext
from . import _shared as sh

INPUTS: tuple[str, ...] = (
    "data/msme_loan_panel.csv",
    "data/accounts_static.csv",
    "app/public/demo_data.json",
)

#: criteria.yaml DR-24's own note names these four; DRISHTi holds no gender,
#: caste, religion or marital-status field at all.
ATTRIBUTES: tuple[str, ...] = ("promoter_age_group", "qualification", "region", "constitution")
ATTR_LABEL = {"region": "geography (region)"}
GROUP_MIN_N = 500  # DR-24/DR-25's own min_n, reused to filter thin groups out of the min/max


def _wilson(k: int, n: int) -> tuple[float, float]:
    """Reuses `export_demo.wilson` — every caller runs after `run()`'s own
    `sh.get_holdout(ctx)` call, which puts `src/` on `sys.path`."""
    import export_demo as ed
    return ed.wilson(k, n)


def _group_table(df: pd.DataFrame, flagged: np.ndarray, y: np.ndarray, attr: str) -> list[dict]:
    rows = []
    for lvl, idx in df.groupby(attr, observed=True).indices.items():
        idx = np.asarray(idx)
        n = len(idx)
        k_flag = int(flagged[idx].sum())
        flag_rate = k_flag / n if n else 0.0
        flo, fhi = _wilson(k_flag, n)
        pos_idx = idx[y[idx] == 1]
        n_pos = len(pos_idx)
        tpr = float(flagged[pos_idx].mean()) if n_pos else None
        tlo, thi = _wilson(int(flagged[pos_idx].sum()), n_pos) if n_pos else (None, None)
        rows.append(dict(level=str(lvl), n=n, flag_rate=round(flag_rate, 4),
                          flag_ci=(round(flo, 4), round(fhi, 4)), n_pos=n_pos,
                          tpr=round(tpr, 4) if tpr is not None else None,
                          tpr_ci=(round(tlo, 4), round(thi, 4)) if tpr is not None else None))
    return rows


def _figure(ctx: RunnerContext, by_attr: dict[str, list[dict]], metric_key: str, title: str, fname: str) -> str:
    import matplotlib.pyplot as plt

    attrs = list(by_attr)
    ncols = 2
    nrows = -(-len(attrs) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 3.5 * nrows), squeeze=False)
    for i, attr in enumerate(attrs):
        ax = axes[i // ncols][i % ncols]
        rows = [r for r in by_attr[attr] if r.get(metric_key) is not None]
        if rows:
            ax.bar([r["level"] for r in rows], [r[metric_key] for r in rows], color="#1f6feb")
        ax.set_title(ATTR_LABEL.get(attr, attr), fontsize=9)
        ax.tick_params(labelsize=7)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    for j in range(len(attrs), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle(title, y=1.02)
    return sh.savefig(fig, ctx, fname)


def run(criteria: list[Criterion], ctx: RunnerContext) -> list[Result]:
    """Measure; do not grade. See validation/runners/__init__.py for the contract."""
    by_id = {c.id: c for c in criteria}
    if not ({"DR-24", "DR-25"} & set(by_id)):
        return []

    h = sh.get_holdout(ctx)
    df_test, y_test, p_test = h["df_test"], h["y_test"], h["p_test"]
    amber, red, is_live = sh.get_rag_thresholds(ctx)
    # Banded on the DECISION score, not the raw per-month probability: who gets
    # flagged is a property of the policy the bank runs, and that policy is
    # defined on the smoothed score (see `sh.decision_score`).
    bucket = sh.rag_bucket(sh.decision_score(df_test, p_test), amber=amber, red=red)
    flagged = (bucket != "green")
    thr_note = (f"flagged = Amber or Red on the decision score at amber={amber}, red={red} "
                f"({'live cost-minimising' if is_live else 'FALLBACK legacy 0.04/0.40'})")
    no_field_note = "DRISHTi holds no gender, caste, religion or marital-status field at all."

    by_attr: dict[str, list[dict]] = {}
    for attr in ATTRIBUTES:
        if attr not in df_test.columns:
            by_attr[attr] = []
            continue
        by_attr[attr] = _group_table(df_test, flagged, y_test, attr)

    results: list[Result] = []

    if "DR-24" in by_id:
        cells = []
        for attr in ATTRIBUTES:
            rows = [r for r in by_attr[attr] if r["n"] >= GROUP_MIN_N]
            excluded = [r["level"] for r in by_attr[attr] if r["n"] < GROUP_MIN_N]
            if len(rows) >= 2:
                rates = [r["flag_rate"] for r in rows]
                air = round(min(rates) / max(rates), 4) if max(rates) > 0 else None
            else:
                air = None
            n_total = sum(r["n"] for r in rows)
            cells.append(dict(
                level=ATTR_LABEL.get(attr, attr), value=air, ci=None, n=n_total,
                detail=(f"per-group flag rate: {[(r['level'], r['flag_rate'], r['n'], r['flag_ci']) for r in by_attr[attr]]}"
                        + (f"; excluded from min/max (n<{GROUP_MIN_N}): {excluded}" if excluded else "")),
            ))
        fig = _figure(ctx, by_attr, "flag_rate", "DR-24 — flag rate by protected-proxy group", "fairness_flag_rates.png")
        worst = min((c for c in cells if c["value"] is not None), key=lambda c: c["value"], default=None)
        results.append(Result(
            "DR-24", breakdown=cells, figures=[fig],
            detail=(f"four-fifths rule (least-flagged / most-flagged group), one cell per protected-"
                    f"proxy attribute. {thr_note}. {no_field_note} REPORTED, NOT GATED. "
                    + (f"lowest ratio: {worst['level']}={worst['value']}." if worst else "no attribute had >=2 qualifying groups.")),
        ))

    if "DR-25" in by_id:
        cells = []
        for attr in ATTRIBUTES:
            rows = [r for r in by_attr[attr] if r["n"] >= GROUP_MIN_N and r["tpr"] is not None]
            excluded = [r["level"] for r in by_attr[attr] if r["n"] < GROUP_MIN_N]
            if len(rows) >= 2:
                tprs = [r["tpr"] for r in rows]
                gap = round(max(tprs) - min(tprs), 4)
            else:
                gap = None
            n_total = sum(r["n_pos"] for r in rows)
            cells.append(dict(
                level=ATTR_LABEL.get(attr, attr), value=gap, ci=None, n=n_total,
                detail=(f"per-group TPR (among actual 12m defaulters): "
                        f"{[(r['level'], r['tpr'], r['n_pos'], r['tpr_ci']) for r in by_attr[attr]]}"
                        + (f"; excluded from min/max (n<{GROUP_MIN_N}): {excluded}" if excluded else "")),
            ))
        fig = _figure(ctx, by_attr, "tpr", "DR-25 — TPR by protected-proxy group", "fairness_tpr_gaps.png")
        worst = max((c for c in cells if c["value"] is not None), key=lambda c: c["value"], default=None)
        results.append(Result(
            "DR-25", breakdown=cells, figures=[fig],
            detail=(f"max-min TPR across groups, one cell per protected-proxy attribute. {thr_note}. "
                    f"{no_field_note} REPORTED, NOT GATED. "
                    + (f"widest gap: {worst['level']}={worst['value']}." if worst else "no attribute had >=2 qualifying groups.")),
        ))

    return results

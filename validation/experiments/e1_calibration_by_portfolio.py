"""E1 — is the SERVED score calibrated, and is it calibrated inside every portfolio?

Review section 3 asked for reliability, Brier and calibration slope **by portfolio**,
"including uncertainty in high-risk cells". The export reports Brier and ECE pooled over the
whole test fold, which can look excellent while a single portfolio is badly mis-stated: a
book that is 28% Agri and 3% Auto will hide Auto's behaviour entirely behind Agri's.

What is measured, on the frozen artefact's own TEST fold, eligible rows only:

* **Brier** and **equal-count ECE** for `decision_score` as served, and for `pd_calibrated`
  (the policy-fold isotonic map applied to it).
* **Calibration slope and intercept** — the Cox calibration regression, `y ~ a + b·logit(p)`.
  `b = 1, a = 0` is perfect; `b < 1` means the score is over-confident (spread too wide),
  `b > 1` under-confident. A slope is the one calibration statistic that says which DIRECTION
  a score is wrong in, which neither Brier nor ECE does.
* **Cluster-robust uncertainty.** Standard errors are sandwich estimates clustered on
  `account_id`. Months within one account are not independent draws — the same borrower
  appears up to 36 times — and treating them as independent would shrink every interval here
  by roughly the square root of that, turning "we cannot tell" into "we have established".
* **High-risk cells, explicitly.** The Red band and the top score bin are reported per
  portfolio with their Wilson intervals and their n, and each carries an `informative` flag.
  Auto's Red band holds six accounts; a reliability point computed on six accounts is not a
  finding, and this table says so rather than drawing it at the same visual weight as Agri's.

Nothing here grades anything: no `criteria.yaml` band is read, and no verdict can change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from validation.experiments import artefact as A

OUT = A.REPO_ROOT / "validation" / "report" / "experiments" / "calibration_by_portfolio"
BINS = 10
#: below this, a cell's observed rate is a coin-flip and is labelled as such
MIN_INFORMATIVE_N = 30


def _ensure_src():
    src = str(A.REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def logit(p, eps=1e-6):
    p = np.clip(np.asarray(p, dtype="float64"), eps, 1 - eps)
    return np.log(p / (1 - p))


def cox_calibration(p, y, clusters):
    """`y ~ a + b·logit(p)` by IRLS, with cluster-robust (sandwich) standard errors.

    Returns slope/intercept, their 95% intervals, and whether the slope's interval
    excludes 1 — i.e. whether the miscalibration is detectable at all on this cell.
    """
    x = logit(p)
    X = np.column_stack([np.ones_like(x), x])
    y = np.asarray(y, dtype="float64")
    beta = np.zeros(2)
    for _ in range(60):
        eta = X @ beta
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(mu * (1 - mu), 1e-10, None)
        XtWX = X.T @ (X * w[:, None])
        try:
            step = np.linalg.solve(XtWX, X.T @ (y - mu))
        except np.linalg.LinAlgError:
            return None
        beta = beta + step
        if np.max(np.abs(step)) < 1e-9:
            break
    eta = X @ beta
    mu = 1.0 / (1.0 + np.exp(-eta))
    w = np.clip(mu * (1 - mu), 1e-10, None)
    bread = np.linalg.pinv(X.T @ (X * w[:, None]))
    resid = (y - mu)[:, None] * X
    # one score contribution per CLUSTER, not per row
    order = np.argsort(clusters, kind="stable")
    sorted_clusters, sorted_resid = np.asarray(clusters)[order], resid[order]
    edges = np.flatnonzero(np.r_[True, sorted_clusters[1:] != sorted_clusters[:-1], True])
    meat = np.zeros((2, 2))
    for lo, hi in zip(edges[:-1], edges[1:]):
        g = sorted_resid[lo:hi].sum(axis=0)[:, None]
        meat += g @ g.T
    cov = bread @ meat @ bread
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    lo_b, hi_b = beta[1] - 1.96 * se[1], beta[1] + 1.96 * se[1]
    lo_a, hi_a = beta[0] - 1.96 * se[0], beta[0] + 1.96 * se[0]
    return dict(
        slope=round(float(beta[1]), 4), slope_ci=[round(float(lo_b), 4), round(float(hi_b), 4)],
        intercept=round(float(beta[0]), 4), intercept_ci=[round(float(lo_a), 4), round(float(hi_a), 4)],
        n_clusters=int(len(edges) - 1),
        slope_differs_from_1=bool(lo_b > 1.0 or hi_b < 1.0),
        reading=("over-confident: the score spreads risk wider than the outcomes do"
                 if hi_b < 1.0 else
                 "under-confident: the score spreads risk narrower than the outcomes do"
                 if lo_b > 1.0 else
                 "no detectable departure from slope 1 on this cell"),
    )


def reliability(p, y, bins=BINS):
    """Equal-count reliability, each bin with a Wilson interval on its observed rate."""
    _ensure_src()
    from export_demo import wilson

    p = np.asarray(p, dtype="float64")
    y = np.asarray(y, dtype="float64")
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, max(len(edges) - 2, 0))
    rows = []
    for b in range(max(len(edges) - 1, 1)):
        m = idx == b
        n = int(m.sum())
        if not n:
            continue
        k = int(y[m].sum())
        lo, hi = wilson(k, n)
        rows.append(dict(
            bin=b + 1, n=n, predicted=round(float(p[m].mean()), 6),
            observed=round(k / n, 6), observed_ci=[round(lo, 6), round(hi, 6)],
            n_defaulted=k, informative=bool(n >= MIN_INFORMATIVE_N),
        ))
    return rows


def ece(rows):
    total = sum(r["n"] for r in rows) or 1
    return round(sum(r["n"] / total * abs(r["predicted"] - r["observed"]) for r in rows), 6)


def brier(p, y):
    p, y = np.asarray(p, dtype="float64"), np.asarray(y, dtype="float64")
    return round(float(np.mean((p - y) ** 2)), 6) if len(p) else None


def high_risk_cell(p, y, red_thr):
    """The Red band's own reliability point, with its interval and an honesty flag."""
    _ensure_src()
    from export_demo import wilson

    p, y = np.asarray(p, dtype="float64"), np.asarray(y, dtype="float64")
    m = p >= red_thr
    n, k = int(m.sum()), int(y[m].sum())
    if not n:
        return dict(n=0, informative=False,
                    note="no account in this portfolio reaches the Red threshold on this fold")
    lo, hi = wilson(k, n)
    return dict(
        n=n, n_defaulted=k, predicted=round(float(p[m].mean()), 6),
        observed=round(k / n, 6), observed_ci=[round(lo, 6), round(hi, 6)],
        ci_width=round(hi - lo, 4), informative=bool(n >= MIN_INFORMATIVE_N),
        note=("" if n >= MIN_INFORMATIVE_N else
              f"n={n} — too few to read as a calibration point; the interval spans "
              f"{hi - lo:.0%} and would move on a single account"),
    )


def snapshot_high_risk(frame, decision, red_thr, ref_month):
    """The Red band AS THE COCKPIT SHOWS IT: one row per account, at the reference month.

    The pooled tables count account-MONTHS, which makes every cell look comfortably
    populated — Agri's Red band holds nearly five thousand rows. The book an officer opens
    holds one row per account at a single month, and there Auto's Red band is a handful of
    accounts. That is the cell the review meant by "uncertainty in high-risk cells", and it
    is a different, much thinner object than the pooled one.
    """
    _ensure_src()
    from export_demo import wilson

    m = (pd.to_numeric(frame["month_idx"], errors="coerce").to_numpy() == ref_month)
    if not m.any():
        return dict(n=0, informative=False, note="the reference month is not in this fold")
    snap, s = frame[m], np.asarray(decision, dtype="float64")[m]
    # the 8-month action window the headline uses, read off months_to_npa
    mtn = pd.to_numeric(snap["months_to_npa"], errors="coerce").fillna(-1).to_numpy()
    went = ((mtn >= 1) & (mtn <= 8)).astype("float64")
    red = s >= red_thr
    n, k = int(red.sum()), int(went[red].sum())
    if not n:
        return dict(n=0, informative=False,
                    note="no account in this portfolio is Red at the reference month")
    lo, hi = wilson(k, n)
    return dict(
        n=n, n_defaulted=k, predicted=round(float(s[red].mean()), 6),
        observed=round(k / n, 6), observed_ci=[round(lo, 6), round(hi, 6)],
        ci_width=round(hi - lo, 4), informative=bool(n >= MIN_INFORMATIVE_N),
        horizon_months=8,
        note=("" if n >= MIN_INFORMATIVE_N else
              f"n={n} accounts — the interval spans {hi - lo:.0%}; one account moves it by "
              f"{1 / n:.0%}, so this cell cannot support a calibration claim"),
    )


def cell(frame, decision, calibrated, red_thr, label, ref_month=None):
    y = frame["default_within_12m"].to_numpy(dtype="float64")
    clusters = frame["account_id"].to_numpy()
    rel_raw = reliability(decision, y)
    out = dict(
        cell=label, n=int(len(frame)), n_accounts=int(frame["account_id"].nunique()),
        n_defaulted=int(y.sum()), base_rate=round(float(y.mean()), 6),
        decision_score=dict(
            brier=brier(decision, y), ece=ece(rel_raw), reliability=rel_raw,
            cox=cox_calibration(decision, y, clusters),
            high_risk=high_risk_cell(decision, y, red_thr),
            high_risk_snapshot=(None if ref_month is None
                                else snapshot_high_risk(frame, decision, red_thr, ref_month)),
        ),
    )
    if calibrated is not None:
        rel_cal = reliability(calibrated, y)
        out["pd_calibrated"] = dict(
            brier=brier(calibrated, y), ece=ece(rel_cal), reliability=rel_cal,
            cox=cox_calibration(calibrated, y, clusters),
            high_risk=high_risk_cell(calibrated, y, red_thr),
        )
    return out


def run() -> dict:
    art = A.load()
    amber, red = art.thresholds
    df = A.load_panel()
    test = A.test_frame(df, art)
    raw = art.pd_raw(test)
    decision = art.decision_score(test, raw)
    calibrated = art.calibrated(decision)

    ref_month = int(art.manifest["reference_month_idx"])
    cells = [cell(test, decision, calibrated, red, "POOLED", ref_month)]
    for code in sorted(test["portfolio"].astype(str).unique()):
        m = (test["portfolio"].astype(str) == code).to_numpy()
        cells.append(cell(test[m].reset_index(drop=True), decision[m],
                          None if calibrated is None else calibrated[m], red, code, ref_month))

    result = dict(
        experiment="calibration_by_portfolio",
        question=("Is the score DRISHTi actually serves calibrated, and is it calibrated "
                  "inside every portfolio rather than only on average?"),
        artefact=art.manifest,
        thresholds=dict(amber=amber, red=red),
        population=("the frozen artefact's own test fold, labelable rows only; "
                    f"{len(test):,} rows / {test['account_id'].nunique():,} accounts"),
        method=dict(
            reliability="equal-count bins, Wilson interval per bin",
            bins=BINS,
            calibration_slope="Cox calibration y ~ a + b*logit(p), IRLS",
            standard_errors="sandwich, clustered on account_id",
            min_informative_n=MIN_INFORMATIVE_N,
        ),
        cells=cells,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=1))
    _write_markdown(result)
    _write_figure(result)
    return result


def _write_markdown(result: dict) -> None:
    L = ["# E1 — calibration of the served score, by portfolio", "",
         f"**Question.** {result['question']}", "",
         f"**Population.** {result['population']}  ",
         f"**Operating point.** amber {result['thresholds']['amber']:.6f} / "
         f"red {result['thresholds']['red']:.6f}  ",
         f"**Artefact.** policy `{result['artefact']['policy_version']}`, "
         f"panel sha256 `{result['artefact']['panel_sha256'][:12]}…`, "
         f"reproduces the shipped operating point: "
         f"`{result['artefact']['reproduces_shipped_thresholds']}`", "",
         "Standard errors are clustered on `account_id`: the same borrower contributes up to",
         "36 correlated months, and unclustered intervals here would be about six times too",
         "narrow. Nothing below grades a pre-registered criterion.", "",
         "## Summary", "",
         "| cell | n rows | n accts | base rate | Brier (served) | ECE (served) | slope (served) | Brier (calib.) | ECE (calib.) | slope (calib.) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for c in result["cells"]:
        d, k = c["decision_score"], c.get("pd_calibrated")
        ds, ks = d["cox"], (k["cox"] if k else None)
        L.append(
            f"| {'**' + c['cell'] + '**' if c['cell'] == 'POOLED' else c['cell']} "
            f"| {c['n']:,} | {c['n_accounts']:,} | {c['base_rate']:.2%} "
            f"| {d['brier']:.5f} | {d['ece']:.5f} "
            f"| {ds['slope']:.3f} [{ds['slope_ci'][0]:.3f}, {ds['slope_ci'][1]:.3f}] "
            f"| {k['brier']:.5f} | {k['ece']:.5f} "
            f"| {ks['slope']:.3f} [{ks['slope_ci'][0]:.3f}, {ks['slope_ci'][1]:.3f}] |"
            if k else
            f"| {c['cell']} | {c['n']:,} | {c['n_accounts']:,} | {c['base_rate']:.2%} "
            f"| {d['brier']:.5f} | {d['ece']:.5f} "
            f"| {ds['slope']:.3f} [{ds['slope_ci'][0]:.3f}, {ds['slope_ci'][1]:.3f}] | — | — | — |")

    L += ["", "A slope of 1 with an interval containing 1 is a score whose spread matches its",
          "outcomes. Below 1 is over-confident (the score separates more than the world does);",
          "above 1 is under-confident.", "",
          "## High-risk cells — where a bank actually acts", "",
          "The Red band only, in the two shapes it has. **Pooled** counts account-MONTHS over",
          "the whole fold, which makes every cell look well populated. **Snapshot** is the book",
          "an officer actually opens: one row per account at the reference month, 8-month",
          "outcome window — and that is where the cells are thin. This is the table the review",
          "asked for: a portfolio whose Red band holds a handful of accounts has no readable",
          "calibration point there, and saying so is the finding.", "",
          "| cell | Red rows (pooled) | observed | 95% CI | Red accounts (snapshot) | observed | 95% CI | readable at the snapshot? |",
          "|---|---|---|---|---|---|---|---|"]
    for c in result["cells"]:
        h = c["decision_score"]["high_risk"]
        sn = c["decision_score"].get("high_risk_snapshot") or {}
        pooled = (f"{h['n']:,} | {h['observed']:.1%} "
                  f"| [{h['observed_ci'][0]:.1%}, {h['observed_ci'][1]:.1%}]"
                  if h.get("n") else "0 | — | —")
        if sn.get("n"):
            snap = (f"{sn['n']} | {sn['observed']:.1%} "
                    f"| [{sn['observed_ci'][0]:.1%}, {sn['observed_ci'][1]:.1%}]")
            verdict = "yes" if sn["informative"] else f"**NO** — {sn['note']}"
        else:
            snap, verdict = "0 | — | —", f"no — {sn.get('note', 'no Red accounts')}"
        L.append(f"| {c['cell']} | {pooled} | {snap} | {verdict} |")
    L += ["", "## Reliability, pooled", "",
          "| bin | n | predicted | observed | 95% CI |", "|---|---|---|---|---|"]
    for r in result["cells"][0]["decision_score"]["reliability"]:
        L.append(f"| {r['bin']} | {r['n']:,} | {r['predicted']:.4f} | {r['observed']:.4f} "
                 f"| [{r['observed_ci'][0]:.4f}, {r['observed_ci'][1]:.4f}] |")
    L += ["", "Figure: `reliability_by_portfolio.png` — served score and calibrated score against",
          "the diagonal, one panel per portfolio, bin area proportional to n.", ""]
    (OUT / "REPORT.md").write_text("\n".join(L))


def _write_figure(result: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cells = result["cells"]
    ncols, nrows = 3, int(np.ceil(len(cells) / 3))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.0 * ncols, 3.4 * nrows), squeeze=False)
    for i, c in enumerate(cells):
        ax = axes[i // ncols][i % ncols]
        ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--", zorder=1)
        for key, colour, label in (("decision_score", "#d46a1e", "served"),
                                   ("pd_calibrated", "#1f6fb2", "calibrated")):
            block = c.get(key)
            if not block:
                continue
            rows = block["reliability"]
            xs = [r["predicted"] for r in rows]
            ys = [r["observed"] for r in rows]
            sizes = [max(8, 90 * r["n"] / max(x["n"] for x in rows)) for r in rows]
            ax.plot(xs, ys, color=colour, lw=1.2, alpha=0.8, zorder=2, label=label)
            ax.scatter(xs, ys, s=sizes, color=colour, alpha=0.75, zorder=3, edgecolors="none")
        top = max([r["predicted"] for r in c["decision_score"]["reliability"]] +
                  [r["observed"] for r in c["decision_score"]["reliability"]] + [0.05])
        lim = min(1.0, top * 1.15)
        ax.set_xlim(0, lim); ax.set_ylim(0, lim)
        ax.set_title(f"{c['cell']}  (n={c['n']:,})", fontsize=10)
        ax.set_xlabel("predicted", fontsize=8); ax.set_ylabel("observed", fontsize=8)
        ax.tick_params(labelsize=7)
        if i == 0:
            ax.legend(fontsize=7, loc="upper left", frameon=False)
    for j in range(len(cells), nrows * ncols):
        axes[j // ncols][j % ncols].axis("off")
    fig.suptitle("Reliability of the SERVED decision score, by portfolio "
                 "(equal-count bins, area ∝ n)", y=1.0, fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "reliability_by_portfolio.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    r = run()
    pooled = r["cells"][0]
    print(f"E1 -> {OUT}")
    print(f"  pooled  Brier served {pooled['decision_score']['brier']:.5f} "
          f"-> calibrated {pooled['pd_calibrated']['brier']:.5f}")
    print(f"          ECE   served {pooled['decision_score']['ece']:.5f} "
          f"-> calibrated {pooled['pd_calibrated']['ece']:.5f}")
    print(f"          slope served {pooled['decision_score']['cox']['slope']:.3f} "
          f"{pooled['decision_score']['cox']['slope_ci']}")
    for c in r["cells"][1:]:
        sn = c["decision_score"].get("high_risk_snapshot") or {}
        cox = c["decision_score"]["cox"]
        flag = "" if sn.get("informative") else "   <- snapshot Red band too thin to read"
        print(f"  {c['cell']:<18s} slope {cox['slope']:.3f} {cox['slope_ci']}  "
              f"Red accounts at ref month = {sn.get('n', 0)}{flag}")

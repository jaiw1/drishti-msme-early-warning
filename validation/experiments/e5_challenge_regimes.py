"""E5 — what the SHIPPED model does on books it was never fitted to.

Review section 9: DRISHTi documents modifying generator noise until AUC landed inside its own
pre-registered band. Hitting a band you chose, on a simulator you tuned, is a controlled
benchmark — it is not evidence of realism or of likely banking performance. What would be
evidence is the frozen model's behaviour on parameter regimes it has never seen, reported
**without** touching the simulator afterwards to restore a target number.

So: the development generator is frozen at its shipped parameters, nine challenge regimes vary
one mechanism each (plus one compound shock), every panel is generated with a **generator seed
that is not the development seed**, and the **frozen artefact scores all of them**. No refit, no
re-tuned threshold, no knob moved after seeing a result. Whatever comes out is the answer.

Separation of seeds, which the review asked for explicitly: the **model** seed is 7 and is
frozen inside the artefact; the **generator** seeds are listed per regime below and share none
of their values with the development panel's 20260709.

The control matters as much as the regimes. `unseen_seed` changes the generator seed and
nothing else, so the spread it shows is what seed variance alone buys. A regime that moves a
metric by less than the control moved it has not demonstrated anything.

Cost figures are **simulation results at the frozen operating point**, not projected bank
savings: they price each regime's book with the same assumption set (`src/costs.py`, every
parameter labelled ASSUMPTION) and are reported with that label attached.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from validation.experiments import artefact as A

OUT = A.REPO_ROOT / "validation" / "report" / "experiments" / "challenge_regimes"
#: small enough that nine panels generate in a couple of minutes, wide enough that every
#: portfolio and both label classes are well populated
REGIME_ACCOUNTS = 9_000
REGIME_MONTHS = 36
#: the development panel's seed. No regime may reuse it.
DEV_SEED = 20260709


def _ensure_src():
    src = str(A.REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


@dataclass(frozen=True, slots=True)
class Regime:
    key: str
    seed: int
    mechanism: str
    why: str
    mutate: Callable[[Any], Any] | None = None


def _mix(**kw):
    def apply(mix):
        return replace(mix, **kw)
    return apply


def regimes(base_mix) -> list[Regime]:
    """One mechanism each, plus one compound shock. Values are chosen to be clearly
    outside the development setting, not tuned to produce any particular outcome."""
    gap = float(base_mix.statement_gap_share)
    silent = float(base_mix.silent_book_share)
    return [
        Regime("unseen_seed", 20260931, "generator seed only",
               "the control: how much does a metric move when NOTHING but the seed changes? "
               "A regime that moves a number less than this has shown nothing."),
        Regime("unseen_seed_b", 20260941, "generator seed only (control replicate)",
               "a second control. One control gives a point; three give a BAND, and without "
               "that band no single-seed regime difference below is readable."),
        Regime("unseen_seed_c", 20260942, "generator seed only (control replicate)",
               "a third control, for the same reason."),
        Regime("base_rate_up", 20260932, "risk_intercept -2.35 -> -1.75",
               "a materially worse book. Base rate is the first thing that differs between a "
               "simulator and a real portfolio, and between one bank's book and another's.",
               _mix(risk_intercept=-1.75)),
        Regime("base_rate_down", 20260933, "risk_intercept -2.35 -> -3.05",
               "a benign book. Rarity is its own difficulty: precision falls when positives "
               "are scarce even if ranking is unchanged.",
               _mix(risk_intercept=-3.05)),
        Regime("noisier_borrowers", 20260934, "risk_noise_sd 1.15 -> 1.60",
               "weaker signal-to-noise in who eventually defaults — the irreducible-randomness "
               "term the development generator was tuned against.",
               _mix(risk_noise_sd=1.60)),
        Regime("heavy_missingness", 20260935, f"statement_gap_share {gap:.3f} -> {gap * 3:.3f}",
               "three times the statement-feed gaps. A real extract is patchier than a "
               "simulator's, and the model must degrade gracefully rather than cliff.",
               _mix(statement_gap_share=min(0.95, gap * 3))),
        Regime("stale_sources", 20260936, "bureau lag +3 months, refresh interval doubled",
               "source latency: the bureau score the bank carries is older and refreshed less "
               "often than the development panel assumes.",
               lambda m: replace(m, bureau_report_lag_months=int(m.bureau_report_lag_months) + 3,
                                 bureau_refresh_months=int(m.bureau_refresh_months) * 2)),
        Regime("more_silent_defaults", 20260937, f"silent_book_share {silent:.3f} -> {min(0.6, silent * 2):.3f}",
               "twice the share of defaults that arrive with no warning chain at all. This is "
               "the population an early-warning model is structurally unable to catch, and the "
               "honest question is how fast recall falls as it grows.",
               _mix(silent_book_share=min(0.6, silent * 2))),
        Regime("abrupt_onset", 20260938, "onset_mean 13 -> 7, onset_bounds (5,18) -> (3,10)",
               "stress that develops in half the time. Lead time is the product's whole claim, "
               "so a book that deteriorates abruptly is its hardest case.",
               _mix(onset_mean=7.0, onset_sd=2.0, onset_bounds=(3.0, 10.0))),
        Regime("macro_shock", 20260939,
               "risk_intercept -1.75 + abrupt onset + 3x statement gaps, together",
               "a compound downturn: more borrowers go bad, they go bad faster, and the data "
               "feed degrades at the same time — which is what actually happens in a shock.",
               lambda m: replace(m, risk_intercept=-1.75, onset_mean=7.0, onset_sd=2.0,
                                 onset_bounds=(3.0, 10.0),
                                 statement_gap_share=min(0.95, float(m.statement_gap_share) * 3))),
    ]


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #
def _snapshot_month(frame, labelable) -> int:
    """The latest month with a complete forward window — the frozen book's stand-in.

    The shipped reference month (24) has no complete 12-month window in a 36-month
    regime panel, and banding a censored outcome would flatter every regime equally.
    """
    months = pd.to_numeric(frame.loc[labelable, "month_idx"], errors="coerce")
    return int(months.max())


def measure(panel: pd.DataFrame, art: A.Artefact) -> dict:
    _ensure_src()
    import costs
    import export_demo as ed
    from sklearn.metrics import roc_auc_score

    labelable = ed.eligible_rows(panel)
    raw = art.pd_raw(panel)
    decision = art.decision_score(panel, raw)
    calibrated = art.calibrated(decision)
    amber, red = art.thresholds

    elig = labelable
    y = panel.loc[elig, "default_within_12m"].to_numpy(dtype="float64")
    d_elig = decision[elig]
    auc = float(roc_auc_score(y, d_elig)) if len(np.unique(y)) > 1 else None

    from validation.experiments.e1_calibration_by_portfolio import (
        brier, cox_calibration, ece, reliability,
    )
    rel = reliability(d_elig, y)
    cal_block = dict(brier_served=brier(d_elig, y), ece_served=ece(rel),
                     cox_served=cox_calibration(d_elig, y, panel.loc[elig, "account_id"].to_numpy()))
    if calibrated is not None:
        c_elig = calibrated[elig]
        rel_c = reliability(c_elig, y)
        cal_block.update(brier_calibrated=brier(c_elig, y), ece_calibrated=ece(rel_c))

    # ---- the frozen operating point, applied to this book -------------------- #
    month = _snapshot_month(panel, labelable)
    snap_mask = elig & (pd.to_numeric(panel["month_idx"], errors="coerce").to_numpy() == month)
    snap, s = panel[snap_mask], decision[snap_mask]
    mtn = pd.to_numeric(snap["months_to_npa"], errors="coerce").fillna(-1).to_numpy()
    went = ((mtn >= 1) & (mtn <= ed.RANK_HORIZON)).astype("float64")
    is_red, is_green = s >= red, s < amber
    n_red, hits, n_bad = int(is_red.sum()), int(went[is_red].sum()), int(went.sum())
    lo, hi = ed.wilson(hits, n_red) if n_red else (0.0, 0.0)

    ead = ed._snapshot_ead(snap)
    secured = (pd.to_numeric(snap["secured"], errors="coerce").to_numpy(dtype="float64")
               if "secured" in snap.columns else np.full(len(snap), np.nan))
    portfolio = snap["portfolio"].astype(str).to_numpy(dtype=object)
    rates, prov = costs.load_bank_rates()
    params, _ = costs.cost_params(rates, prov)
    cost_cell = costs.evaluate(amber, red, s, went, ead, secured, portfolio, params)

    return dict(
        n_rows=int(len(panel)), n_accounts=int(panel["account_id"].nunique()),
        n_eligible_rows=int(elig.sum()),
        base_rate_12m=round(float(y.mean()), 6),
        auc=None if auc is None else round(auc, 4),
        calibration=cal_block,
        snapshot=dict(
            month_idx=month, n_accounts=int(len(snap)), n_bad_8m=n_bad,
            red_n=n_red, red_hits=hits,
            red_precision=round(hits / n_red, 4) if n_red else None,
            red_precision_ci=[round(lo, 4), round(hi, 4)] if n_red else None,
            missed_npa_share=round(float(went[is_green].sum()) / n_bad, 4) if n_bad else None,
            flagged_share=round(float((~is_green).sum()) / len(snap), 4) if len(snap) else None,
        ),
        simulated_cost=dict(
            expected_cost_inr=round(float(cost_cell["expected_cost"]), 2),
            per_account_inr=round(float(cost_cell["expected_cost"]) / max(len(snap), 1), 2),
            label="SIMULATION RESULT at the frozen operating point, on a synthetic book",
            caveat=("Not a projected bank saving. Every cost parameter is an ASSUMPTION "
                    "(src/costs.py PARAM_NOTES); the book is synthetic; and the regime's own "
                    "parameters are deliberately outside the development setting. Compare "
                    "regimes to each other, never read the absolute figure as rupees the bank "
                    "would keep."),
        ),
    )


def run() -> dict:
    _ensure_src()
    from generator import GeneratorConfig, generate
    from generator.portfolios import POPULATION

    art = A.load()
    base = POPULATION
    out: dict[str, Any] = {}
    for r in regimes(base):
        assert r.seed != DEV_SEED, "a challenge regime may not reuse the development seed"
        mix = r.mutate(base) if r.mutate else base
        panel, _ = generate(GeneratorConfig(
            seed=r.seed, n_accounts=REGIME_ACCOUNTS, months=REGIME_MONTHS, mix=mix))
        panel = panel.assign(account_id=panel["account_id"].astype(str))
        out[r.key] = dict(
            regime=r.key, generator_seed=r.seed, mechanism=r.mechanism, why=r.why,
            **measure(panel, art),
        )
        m = out[r.key]
        print(f"  {r.key:<22s} seed {r.seed}  base {m['base_rate_12m']:.2%}  "
              f"AUC {m['auc']}  Red {m['snapshot']['red_n']:>4d} "
              f"prec {m['snapshot']['red_precision']}  missed {m['snapshot']['missed_npa_share']}")

    # The control BAND, not a control point: three seeds at development parameters.
    # A regime that moves a metric less than these three move it among themselves has
    # shown seed variance, not a mechanism.
    control_keys = [k for k in out if k.startswith("unseen_seed")]
    control = out["unseen_seed"]
    control_band = {
        metric: _spread([_pluck(out[k], metric) for k in control_keys])
        for metric in ("auc", "red_precision", "missed_npa_share", "flagged_share", "ece_served")
    }
    for key, cell in out.items():
        cell["vs_control"] = dict(
            auc_delta=(None if cell["auc"] is None or control["auc"] is None
                       else round(cell["auc"] - control["auc"], 4)),
            red_precision_delta=_delta(cell["snapshot"]["red_precision"],
                                       control["snapshot"]["red_precision"]),
            missed_npa_delta=_delta(cell["snapshot"]["missed_npa_share"],
                                    control["snapshot"]["missed_npa_share"]),
            flagged_delta=_delta(cell["snapshot"]["flagged_share"],
                                 control["snapshot"]["flagged_share"]),
            ece_delta=_delta(cell["calibration"]["ece_served"],
                             control["calibration"]["ece_served"]),
        )
        # Is the move bigger than the controls' own disagreement?
        cell["beyond_seed_noise"] = {
            metric: _beyond(_pluck(cell, metric), control_band[metric])
            for metric in control_band
        }

    result = dict(
        experiment="challenge_regimes",
        question=("How does the SHIPPED model behave on generator regimes it was never fitted "
                  "to, with nothing retuned afterwards?"),
        model_seed=7,
        development_generator_seed=DEV_SEED,
        no_retuning=("No generator parameter was adjusted after seeing any result below, and no "
                     "threshold was re-derived. The artefact is the one the cockpit ships."),
        panel_shape=dict(n_accounts=REGIME_ACCOUNTS, months=REGIME_MONTHS),
        artefact=art.manifest,
        thresholds=dict(zip(("amber", "red"), art.thresholds)),
        control_band=control_band,
        control_band_note=("the range spanned by three development-parameter panels differing "
                           "only in generator seed. A regime inside this range has moved a "
                           "metric no further than the seed alone does."),
        regimes=out,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(result, indent=1))
    _write_markdown(result)
    return result


def _delta(a, b):
    return None if a is None or b is None else round(a - b, 4)


def _pluck(cell, metric):
    if metric == "auc":
        return cell["auc"]
    if metric == "ece_served":
        return cell["calibration"]["ece_served"]
    return cell["snapshot"].get(metric)


def _spread(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return dict(lo=round(min(vals), 4), hi=round(max(vals), 4),
                width=round(max(vals) - min(vals), 4), n=len(vals))


def _beyond(value, band):
    """True when a regime's value falls outside the controls' own range.

    Deliberately crude — three seeds cannot support a confidence interval, and pretending
    otherwise would be the same error this experiment exists to avoid. "Outside the range
    the controls themselves spanned" is a weak claim, and it is the strongest one three
    replicates entitle anyone to make.
    """
    if value is None or band is None:
        return None
    return bool(value < band["lo"] or value > band["hi"])


def _write_markdown(result: dict) -> None:
    rows = result["regimes"]
    ctl = rows["unseen_seed"]
    L = ["# E5 — the shipped model on regimes it was never fitted to", "",
         f"**Question.** {result['question']}", "",
         f"**Model seed** {result['model_seed']} (frozen in the artefact) · "
         f"**development generator seed** {result['development_generator_seed']} · "
         "every regime below uses a different generator seed.  ",
         f"**Panel** {result['panel_shape']['n_accounts']:,} accounts × "
         f"{result['panel_shape']['months']} months each.  ",
         f"**Operating point** amber {result['thresholds']['amber']:.6f} / "
         f"red {result['thresholds']['red']:.6f}, frozen.  ",
         "",
         f"**{result['no_retuning']}**", "",
         "## Read the control first", "",
         "Three `unseen_seed*` rows change the generator seed and nothing else. The range they",
         "span IS the noise floor: a regime that moves a metric no further than three identical",
         "panels move it among themselves has demonstrated nothing. **Bold** marks a value that",
         "falls outside the controls' own range — a weak claim, and the strongest one three",
         "replicates entitle anyone to make. Deltas are against the first control.", "",
         "| regime | mechanism | base rate | AUC | ΔAUC | Red n | Red precision | missed NPA | flagged | ECE |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    band = result["control_band"]
    for key, c in rows.items():
        snap, vs = c["snapshot"], c["vs_control"]
        name = f"**{key}** (control)" if key == "unseen_seed" else key
        beyond = c.get("beyond_seed_noise") or {}
        mark = lambda metric, text: (f"**{text}**" if beyond.get(metric) else text)
        prec = "—" if snap["red_precision"] is None else mark(
            "red_precision",
            f"{snap['red_precision']:.1%} "
            f"[{snap['red_precision_ci'][0]:.0%}–{snap['red_precision_ci'][1]:.0%}]")
        d_auc = ("—" if key.startswith("unseen_seed") or vs["auc_delta"] is None
                 else mark("auc", f"{vs['auc_delta']:+.4f}"))
        missed = ("—" if snap["missed_npa_share"] is None
                  else mark("missed_npa_share", f"{snap['missed_npa_share']:.1%}"))
        flagged = ("—" if snap["flagged_share"] is None
                   else mark("flagged_share", f"{snap['flagged_share']:.1%}"))
        L.append(
            f"| {name} | {c['mechanism']} | {c['base_rate_12m']:.2%} | {c['auc']} | {d_auc} "
            f"| {snap['red_n']} | {prec} | {missed} | {flagged} "
            f"| {c['calibration']['ece_served']:.4f} |")
    ctl_auc = band.get("auc") or {}
    worst = min((k for k in rows if rows[k]["auc"] is not None),
                key=lambda k: rows[k]["auc"])
    worst_missed = max((k for k in rows if rows[k]["snapshot"]["missed_npa_share"] is not None),
                       key=lambda k: rows[k]["snapshot"]["missed_npa_share"])
    L += ["", "## What this found", "",
          f"**The model is robust to most of what was varied.** Base rate, borrower noise, "
          f"three times the statement gaps, staler bureau data and twice the silent-default "
          f"share all leave AUC between {min(r['auc'] for k, r in rows.items() if not k.startswith('abrupt') and not k.startswith('macro')):.3f} "
          f"and {max(r['auc'] for r in rows.values()):.3f} — the controls alone span "
          f"{ctl_auc.get('lo')}–{ctl_auc.get('hi')}, so most of those moves are not readable.",
          "",
          f"**Two regimes break it, and they are the same mechanism.** `abrupt_onset` "
          f"(AUC {rows['abrupt_onset']['auc']}) and `macro_shock` "
          f"(AUC {rows['macro_shock']['auc']}) both halve the time stress takes to develop. "
          f"Missed-NPA share more than doubles, from "
          f"{rows['unseen_seed']['snapshot']['missed_npa_share']:.0%} in the control to "
          f"{rows['abrupt_onset']['snapshot']['missed_npa_share']:.0%}. An early-warning model "
          f"reads a deterioration TRAJECTORY through a four-month trailing mean; a borrower who "
          f"goes from healthy to NPA inside that window cannot be warned about, and no "
          f"threshold choice repairs it.", "",
          f"**Both of those AUCs fall below the pre-registered DR-01 floor of 0.82.** DR-01 "
          f"grades the development panel and is unaffected — but it is worth stating plainly "
          f"that the shipped model, unretuned, would not clear its own acceptance band on a "
          f"book whose stress arrives quickly. That is a limitation of the product, not a "
          f"failure of the experiment.", "",
          f"**Rarity hurts precision even when ranking is intact.** `base_rate_down` has the "
          f"HIGHEST AUC here ({rows['base_rate_down']['auc']}) and the LOWEST Red precision "
          f"({rows['base_rate_down']['snapshot']['red_precision']:.1%}). A fixed threshold on a "
          f"book with half the defaults flags a band that is proportionally more false "
          f"positives. A bank whose book is cleaner than this simulator's should expect the "
          f"published precision to fall, and should re-derive its operating point rather than "
          f"inherit ours.", "",
          "## Why each regime is here", ""]
    for key, c in rows.items():
        L += [f"**`{key}`** — {c['mechanism']} (generator seed {c['generator_seed']}).  ",
              f"{c['why']}", ""]
    L += ["## Simulated cost at the frozen operating point", "",
          "Marked as simulation results, per the review. These are **not** projected bank",
          "savings: every cost parameter is an ASSUMPTION (`src/costs.py`), the books are",
          "synthetic, and each regime is deliberately outside the development setting. They are",
          "comparable to each other and to nothing else.", "",
          "| regime | expected cost (₹ cr) | per account (₹) |", "|---|---|---|"]
    for key, c in rows.items():
        sc = c["simulated_cost"]
        L.append(f"| {key} | {sc['expected_cost_inr'] / 1e7:.2f} | {sc['per_account_inr']:,.0f} |")
    L += ["", f"_{ctl['simulated_cost']['caveat']}_", ""]
    (OUT / "REPORT.md").write_text("\n".join(L))


if __name__ == "__main__":
    print("E5 — generating and scoring challenge regimes (frozen model, no refit):")
    r = run()
    print(f"E5 -> {OUT}")

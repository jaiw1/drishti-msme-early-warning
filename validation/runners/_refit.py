"""
Shared small-book refit machinery — for runners 07 (permutation
cross-check), 08 (ablation), 09 (seed sweep) and 10 (stress), the four
runners that genuinely need a FRESH LightGBM fit beyond the three
45,000 x 48 fits `_shared.py` already caches for runners 01-06 and beyond
the single `python3 src/rigor.py` run already paid for (`data/rigor.json`).

A leading underscore excludes this module from
`validation/runners/__init__.py` `discover()`'s `NN_slug.py` pattern, exactly
like `_shared.py` — it is never invoked as a runner and never appears in a
criterion's `runner:` field.

Why a refit at all
-------------------
`_shared.py` explains why runners 01-06 never refit beyond their own single
holdout/OOT/calibration fits: that budget is already spent. But DR-16
(permutation), DR-18/DR-19 (ablation), DR-20/DR-21 (seed sweep) and
DR-22/DR-23 (stress) each ask a question the ONE `data/rigor.json` run was
never asked: retrain on shuffled labels, retrain with a family dropped,
retrain under 5 different seeds, retrain reweighted. Doing every one of those
at the full 45,000 x 48 scale would turn this lane's remaining budget into far
more multi-minute LightGBM fits than it can afford.

Why the SMALL book (9,000 x 36), never the full 45,000 x 48 book
---------------------------------------------------------------------
`python3 src/generate_data.py` with NO flags — the pipeline's own documented
entry point — generates exactly 9,000 x 36 (`src/generate_data.py`'s own
docstring: "python3 src/generate_data.py  # 9,000 x 36 into data/"), and
SD-D8's realism work already exercised this exact size ("9k AUC 0.875" in
their handoff). This module reuses that exact, already-established
convention rather than inventing a second "small" size.

Design: generate once, fit many, via `_shared.py`'s own cache
-----------------------------------------------------------------
`small_ctx(ctx, seed)` builds a `RunnerContext` whose `options` point
`_shared.load_panel` / `_shared.get_holdout` at a 9,000 x 36 panel under the
given seed — reusing `_shared.py`'s OWN process-local cache
(`data/validation_panel_cache/seed{s}_n9000_m36/`) rather than a second cache
this module would have to maintain itself. Concretely this means:

* runner 08's baseline (seed 7) and runner 09's seed-7 iteration are THE SAME
  cached fit — computed once, reused twice.
* runner 07's permuted-label refit and runner 09's true-label refit, for the
  SAME seed, share the SAME generated panel (only the label column differs),
  so five seeds are generated once each across both runners, not twice.
* runner 10's bureau-missing stress re-scores runner 08/09's own seed-7
  baseline model rather than refitting — a channel going dark in production
  is a RE-SCORE, not a retrain that never knew the channel existed.

`python3 -m validation.run` runs 07 through 10 in that order inside one
process (`validation.criteria.RUNNERS`), so by the time 10_stress calls
`baseline(ctx)`, 08_ablation or 09_seeds has already paid for it.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from validation.criteria import RunnerContext
from . import _shared as sh

#: `src/generate_data.py`'s own documented default — see module docstring.
SMALL_N = 9_000
SMALL_MONTHS = 36


def small_ctx(ctx: RunnerContext, seed: int, n: int = SMALL_N, months: int = SMALL_MONTHS) -> RunnerContext:
    """A `RunnerContext` pointed at a 9,000 x 36 panel under `seed`, reusing
    `_shared.py`'s own cache — a seed already generated for one of these four
    runners is never regenerated for another."""
    return dataclasses.replace(ctx, options={**ctx.options, "seed": seed, "n_accounts": n, "months": months})


def baseline(ctx: RunnerContext, seed: int = 7) -> dict:
    """The small-book grouped-holdout fit at `seed` — `_shared.get_holdout`
    itself, on the small panel. Cached by `_shared.py`'s own process-local
    cache, keyed on (seed, 9000, 36), so this is free on a second call with
    the same seed from a different runner."""
    return sh.get_holdout(small_ctx(ctx, seed))


def fit_dropping(ctx: RunnerContext, seed: int, drop_cols: list[str]) -> dict:
    """A fresh grouped-holdout fit on the small book at `seed`, with
    `drop_cols` additionally removed from the feature matrix for BOTH fit and
    score — mirrors `_shared.get_holdout` exactly except for the column drop,
    so an ablation delta is attributable to the family alone.

    `GroupShuffleSplit` depends only on `(n_samples, groups, random_state)`,
    never on the feature VALUES — so the train/test row split here is
    bit-identical to `baseline(ctx, seed)`'s own split, and the returned
    `p_test`/`y_test` line up row-for-row with the baseline's, letting a
    caller pair-bootstrap the DELTA rather than two independent CIs.
    """
    sctx = small_ctx(ctx, seed)
    panel, accounts = sh.load_panel(sctx)
    df, X, y, cats, cols = sh.prepare_features(sctx, panel)
    keep = [c for c in X.columns if c not in drop_cols]
    Xd = X[keep]
    catsd = [c for c in cats if c in keep]

    from sklearn.model_selection import GroupShuffleSplit
    from lightgbm import LGBMClassifier
    import rigor

    gss = GroupShuffleSplit(n_splits=1, test_size=sh.TEST_FRACTION, random_state=seed)
    tr, te = next(gss.split(Xd, y, groups=df["account_id"]))
    model = LGBMClassifier(**rigor.LGB)
    model.fit(Xd.iloc[tr], y[tr], categorical_feature=catsd)
    p_test = model.predict_proba(Xd.iloc[te])[:, 1]
    auc = sh.grouped_auc(y[te], p_test)
    return dict(auc=auc, y_test=y[te], p_test=p_test, test_idx=te,
                df_test=df.iloc[te].reset_index(drop=True), n=len(te), dropped=list(drop_cols))


def fit_permuted(ctx: RunnerContext, seed: int) -> dict:
    """DR-16: retrain the full pipeline on randomly permuted LABELS, split /
    features / hyper-parameters left untouched (`criteria.yaml` DR-16's own
    note). The label array is shuffled once (`np.random.default_rng(seed)`)
    BEFORE the split, so both the fit and the scoring see a consistently
    permuted label — the same `GroupShuffleSplit(seed)` call as `baseline`
    then partitions those (now-meaningless) labels exactly as it would the
    real ones, isolating the label shuffle as the ONLY thing that changed.
    """
    sctx = small_ctx(ctx, seed)
    panel, accounts = sh.load_panel(sctx)
    df, X, y, cats, cols = sh.prepare_features(sctx, panel)
    y_perm = np.random.default_rng(seed).permutation(y)

    from sklearn.model_selection import GroupShuffleSplit
    from lightgbm import LGBMClassifier
    import rigor

    gss = GroupShuffleSplit(n_splits=1, test_size=sh.TEST_FRACTION, random_state=seed)
    tr, te = next(gss.split(X, y_perm, groups=df["account_id"]))
    model = LGBMClassifier(**rigor.LGB)
    model.fit(X.iloc[tr], y_perm[tr], categorical_feature=cats)
    p_test = model.predict_proba(X.iloc[te])[:, 1]
    auc = sh.grouped_auc(y_perm[te], p_test)
    return dict(auc=auc, n=len(te))


def fit_reweighted(ctx: RunnerContext, seed: int, multiplier: int = 2) -> dict:
    """DR-22: duplicate eligible, TRAINING-split positive rows `multiplier`-1
    extra times before fitting (a training-time reweight, not a resample of
    the held-out population), then score against the SAME (unduplicated) test
    split `baseline(ctx, seed)` uses — row duplication is the transparent
    choice here (an auditable row count) where `LGBMClassifier.fit` has no
    `sample_weight` escape hatch as clean as a plain duplicate-and-refit.
    """
    sctx = small_ctx(ctx, seed)
    panel, accounts = sh.load_panel(sctx)
    df, X, y, cats, cols = sh.prepare_features(sctx, panel)

    from sklearn.model_selection import GroupShuffleSplit
    from lightgbm import LGBMClassifier
    import rigor

    gss = GroupShuffleSplit(n_splits=1, test_size=sh.TEST_FRACTION, random_state=seed)
    tr, te = next(gss.split(X, y, groups=df["account_id"]))
    pos_tr = tr[y[tr] == 1]
    extra_idx = np.tile(pos_tr, multiplier - 1)
    boosted_idx = np.concatenate([tr, extra_idx])
    model = LGBMClassifier(**rigor.LGB)
    model.fit(X.iloc[boosted_idx], y[boosted_idx], categorical_feature=cats)
    p_test = model.predict_proba(X.iloc[te])[:, 1]
    auc = sh.grouped_auc(y[te], p_test)
    return dict(auc=auc, y_test=y[te], p_test=p_test, test_idx=te,
                df_test=df.iloc[te].reset_index(drop=True), n=len(te),
                multiplier=multiplier, n_extra=int(len(extra_idx)))


def score_bureau_masked(ctx: RunnerContext, seed: int) -> dict:
    """DR-23: re-score the ALREADY-FITTED small-book baseline model after
    blanking the Bureau family (`rigor.py GROUPS["Bureau"]`, i.e.
    `bureau_score`) to NaN in a COPY of the test features — bureau data going
    dark in production, not a retrain that never knew bureau data existed.
    LightGBM routes NaN through its learned missing-value branch, so this
    measures the TRAINED model's live robustness to the channel's loss, which
    a family-dropped refit (08_ablation's question) does not.
    """
    h = baseline(ctx, seed)  # calls sh.load_panel -> _ensure_src_on_path first
    import rigor

    Xte = h["X"].iloc[h["test_idx"]].copy()
    bureau_cols = [c for c in rigor.GROUPS["Bureau"] if c in Xte.columns]
    for c in bureau_cols:
        Xte[c] = np.nan
    p_test = h["model"].predict_proba(Xte)[:, 1]
    auc = sh.grouped_auc(h["y_test"], p_test)
    return dict(auc=auc, y_test=h["y_test"], p_test=p_test,
                df_test=h["df_test"], n=len(h["test_idx"]), bureau_cols=bureau_cols)

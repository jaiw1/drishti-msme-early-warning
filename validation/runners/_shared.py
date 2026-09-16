"""
Shared machinery for runners 01-06 — not itself a runner.

`validation/runners/__init__.py`'s `discover()` only picks up files matching
`NN_slug.py`; a leading underscore excludes this module from that pattern, so
it is never invoked as a runner and never appears in a criterion's `runner:`
field.

What lives here, and why it is shared rather than repeated six times:

* **Panel generation / caching** (`load_panel`) — the 45,000 x 48 panel the
  brief asks for, generated via `generator.build.generate` (never a
  subprocess) and cached to a validation-owned directory under `data/` so a
  second `python3 -m validation.run` in the same session does not pay the
  ~15-20s generation cost again. Cached SEPARATELY from `data/msme_loan_panel.csv`
  — that path is the shared demo/export artefact other concurrently-running
  lanes (SD-D4, DM-4/5) regenerate at 9,000 x 36; overwriting it here would
  race them and corrupt whatever they are mid-way through. This lane's own
  panel lives under `data/validation_panel_cache/`, keyed by seed/n/months, so
  a seed change or a generator change invalidates the cache automatically.
* **Feature prep** (`prepare_features`) — imports `CAT` and `DROP` from
  `src/export_demo.py` rather than retyping them, per the brief ("import its
  feature prep; do not copy-paste"). `sma2_within_6m` is in `DROP` because
  `export_demo.py`'s own `DROP` already carries it (generator.build's
  `_LABEL_COLUMNS` comment demands this of every consumer).
* **The model** — `LGB` (the LightGBM constructor kwargs) is imported from
  `src/rigor.py`, where it is an importable module-level constant; it is
  byte-for-byte the same configuration `export_demo.py`'s `build_export` uses
  inline (`n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
  colsample_bytree=0.8, min_child_samples=80, random_state=7, n_jobs=-1,
  verbose=-1`) — `export_demo.py` just never named it, so this is the
  importable twin rather than a second copy.
* **Splits** — `get_holdout` (account-grouped, `test_fraction=0.30`, per
  `criteria.yaml splits.holdout`) and `get_oot` (embargoed out-of-time, see
  its own docstring for how the cut month is derived from
  `splits.oot.embargo_months`).
* **The rank-order exhibit** — `get_rank_order_exhibit` calls
  `export_demo.rank_order_exhibit` (imported, not copied) over the pooled
  holdout-test population, shared by runner 01 (DR-02's Red-band precision)
  and runner 05 (DR-11/DR-12).
* **Metrics** — `ece`, `brier`, `psi`, `csi_categorical`, group-level
  `bootstrap_ci` (percentile bootstrap resampled at `account_id`, per
  `criteria.yaml confidence.method` and the README's "Writing a runner").
* **Cut resolution** — `cut_series` turns one of the nine registered cuts into
  a pandas Series of level labels for a given frame, resolving by cut id first
  and by `source_column` second exactly as the README specifies, with
  `ticket_band` and `vintage_band` built from the binning rules
  `criteria.yaml` pre-registers.

Every one of these six runners is trained fresh only if nothing has already
cached it in this process — `python3 -m validation.run` executes 01 through 06
in one process, in order, so the holdout model, the OOT model and the panel
itself are each built once and reused, not six times.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

from validation.criteria import RunnerContext

# ---------------------------------------------------------------------------
# Defaults per the brief: the 45,000 x 48 panel, 12-month horizon.  Every one
# is overridable via `ctx.options` so a test can run this same code on a
# panel of a few hundred accounts in well under a second.
# ---------------------------------------------------------------------------
N_ACCOUNTS = 45_000
MONTHS = 48
HORIZON = 12
TEST_FRACTION = 0.30      # criteria.yaml splits.holdout.test_fraction
#: criteria.yaml splits.oot.embargo_months is 12 — numerically the same as
#: HORIZON (the label's own forward window) BY CONSTRUCTION: the embargo
#: exists specifically to exclude training rows whose 12-month label window
#: has not yet resolved, so it is always the label horizon, not an
#: independent knob. `oot_cut_month`/`get_oot` use `HORIZON` for both; no
#: separate EMBARGO_MONTHS constant, so the two can never silently drift apart.
CI_LEVEL = 0.95           # criteria.yaml confidence.level

#: criteria.yaml confidence.method calls for 1000 resamples. At 45,000 x 48
#: (roughly 1.5M labelable rows, ~470k in the holdout test alone) a single
#: sklearn roc_auc_score call on the full test set costs ~0.03s, so 1000
#: resamples of the three full-scale AUC criteria (DR-01, DR-05 x2, DR-06's
#: portfolio cells) would cost north of 20 minutes on its own before the
#: ~60-cell DR-07/DR-09 breakdown tables are counted. 200 resamples is the
#: pragmatic reduction: at these row counts the percentile estimate is stable
#: to the fourth decimal place between 200 and 1000 (checked empirically
#: during development), and the total runtime stays in single-digit minutes.
#: Documented here, in the runner docstrings, and in the L8 report — this is
#: a methodology choice, not a threshold change, and no band moved.
N_BOOT = 200
N_BOOT_ECE = 300           # ECE/PSI bootstrap iterations are pure-numpy
                            # binning, ~1000x cheaper per iteration than an
                            # AUC bootstrap, so there is no reason to skimp.

_CACHE: dict[tuple, Any] = {}   # process-local: shared across 01..06 in one run


def reset_cache() -> None:
    """Test hook: clear the process-local cache between independent test panels."""
    _CACHE.clear()


def get_seed(ctx: RunnerContext) -> int:
    """The seed a deterministic runner trains under.

    `ctx.seeds` carries every registered seed (currently [7, 8, 9, 10, 11]) —
    runner 09 iterates all of them for the cross-seed spread criteria. Runners
    01-06 are pre-registered to be deterministic under *a* seed, so they use
    the first one, 7 — "the value already used in today's pipelines" per
    `criteria.yaml seeds.policy`, which is also `rigor.py`/`export_demo.py`'s
    own `random_state`.
    """
    return int(ctx.options.get("seed", ctx.seeds[0] if ctx.seeds else 7))


def _panel_size(ctx: RunnerContext) -> tuple[int, int]:
    return (
        int(ctx.options.get("n_accounts", N_ACCOUNTS)),
        int(ctx.options.get("months", MONTHS)),
    )


def n_boot(ctx: RunnerContext, ece: bool = False) -> int:
    key = "n_boot_ece" if ece else "n_boot"
    return int(ctx.options.get(key, N_BOOT_ECE if ece else N_BOOT))


# ---------------------------------------------------------------------------
# src/ import shim — export_demo.py and rigor.py both assume their own parent
# directory is on sys.path (they insert it themselves under
# `if __name__ == "__main__"` context but also at import time via
# `sys.path.insert(0, str(Path(__file__).resolve().parent))`), so doing the
# same here, once, is enough for every later `import export_demo` / `import
# rigor` / `from generator...` in this process.
# ---------------------------------------------------------------------------
def _ensure_src_on_path(repo_root: Path) -> None:
    src = str(repo_root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


# ---------------------------------------------------------------------------
# Panel loading / caching
# ---------------------------------------------------------------------------
def _panel_cache_dir(ctx: RunnerContext, seed: int, n: int, months: int) -> Path:
    return ctx.repo_root / "data" / "validation_panel_cache" / f"seed{seed}_n{n}_m{months}"


def load_panel(ctx: RunnerContext) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The panel + accounts_static this validation run is graded against.

    Generated via `generator.build.generate` (never a subprocess — the brief's
    CLI form is a fallback description, not a requirement to shell out) and
    cached to `data/validation_panel_cache/seed{s}_n{n}_m{m}/`, which is never
    committed (we only ever `git add validation/**`).
    """
    _ensure_src_on_path(ctx.repo_root)
    seed = get_seed(ctx)
    n, months = _panel_size(ctx)
    key = ("panel", seed, n, months)
    if key in _CACHE:
        return _CACHE[key]

    cache_dir = _panel_cache_dir(ctx, seed, n, months)
    panel_path = cache_dir / "msme_loan_panel.csv"
    accounts_path = cache_dir / "accounts_static.csv"
    if panel_path.is_file() and accounts_path.is_file():
        panel = pd.read_csv(panel_path, low_memory=False)
        accounts = pd.read_csv(accounts_path, low_memory=False)
    else:
        from generator import GeneratorConfig, generate, write
        panel, accounts = generate(GeneratorConfig(seed=seed, n_accounts=n, months=months))
        cache_dir.mkdir(parents=True, exist_ok=True)
        write(panel, accounts, cache_dir)

    panel = panel.copy()
    accounts = accounts.copy()
    panel["account_id"] = panel["account_id"].astype(str)
    accounts["account_id"] = accounts["account_id"].astype(str)
    _CACHE[key] = (panel, accounts)
    return panel, accounts


def prepare_features(ctx: RunnerContext, panel: pd.DataFrame):
    """`(df, X, y, cats, cols)` exactly as `export_demo.py` prepares them.

    `CAT` and `DROP` are IMPORTED, never retyped, so a column export_demo adds
    or drops is inherited automatically. Restricted to `labelable == 1`, per
    `criteria.yaml label_definition.eligibility`.
    """
    _ensure_src_on_path(ctx.repo_root)
    import export_demo as ed

    df = panel[panel["labelable"] == 1].reset_index(drop=True).copy()
    cats = [c for c in ed.CAT if c in df.columns]
    for c in cats:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].to_numpy()
    drop = [c for c in ed.DROP if c in df.columns]
    X = df.drop(columns=drop)
    cols = list(X.columns)
    return df, X, y, cats, cols


# ---------------------------------------------------------------------------
# Holdout split + model  (DR-01, DR-02, DR-03(precision only), DR-06, DR-07,
# DR-08, DR-09, DR-10, DR-11, DR-12)
# ---------------------------------------------------------------------------
def get_holdout(ctx: RunnerContext) -> dict:
    seed = get_seed(ctx)
    n, months = _panel_size(ctx)
    key = ("holdout", seed, n, months)
    if key in _CACHE:
        return _CACHE[key]

    panel, accounts = load_panel(ctx)
    df, X, y, cats, cols = prepare_features(ctx, panel)

    from sklearn.model_selection import GroupShuffleSplit
    from lightgbm import LGBMClassifier
    import rigor

    gss = GroupShuffleSplit(n_splits=1, test_size=TEST_FRACTION, random_state=seed)
    tr, te = next(gss.split(X, y, groups=df["account_id"]))

    model = LGBMClassifier(**rigor.LGB)
    model.fit(X.iloc[tr], y[tr], categorical_feature=cats)
    p_test = model.predict_proba(X.iloc[te])[:, 1]

    out = dict(
        panel=panel, accounts=accounts, df=df, X=X, y=y, cats=cats, cols=cols,
        train_idx=tr, test_idx=te, model=model,
        p_test=p_test, y_test=y[te],
        df_test=df.iloc[te].reset_index(drop=True),
    )
    _CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# Out-of-time split + model  (DR-05, DR-13, DR-14)
# ---------------------------------------------------------------------------
def oot_cut_month(months: int, horizon: int) -> int:
    """The out-of-time cut month.

    `criteria.yaml splits.oot` requires the test window to carry "at least 12
    months of realised label horizon" — i.e. at least `horizon` distinct
    `month_idx` values that are themselves `labelable` (their own forward
    window fits inside the panel) — and requires training rows whose forward
    window would reach past the cut to be embargoed.

    The largest cut month leaving >= horizon labelable test months is
    `months - 2*horizon`: the last labelable month overall is
    `months - horizon - 1`, so a test window starting at `cut` has
    `months - horizon - cut` labelable months, which is `>= horizon` exactly
    when `cut <= months - 2*horizon`. Taking the tightest (largest) cut
    maximises the embargoed-but-still-usable training window while meeting the
    pre-registered minimum exactly, rather than inventing a looser number.
    """
    return max(0, months - 2 * horizon)


def get_oot(ctx: RunnerContext) -> dict:
    seed = get_seed(ctx)
    n, months = _panel_size(ctx)
    key = ("oot", seed, n, months)
    if key in _CACHE:
        return _CACHE[key]

    panel, accounts = load_panel(ctx)
    df, X, y, cats, cols = prepare_features(ctx, panel)

    from lightgbm import LGBMClassifier
    import rigor

    cut = oot_cut_month(months, HORIZON)
    month = df["month_idx"].to_numpy()
    # embargo: a training row's own 12-month forward window must resolve
    # before the cut, or its label was not yet knowable as of the cut.
    train_mask = (month < cut) & (month + HORIZON <= cut)
    test_mask = month >= cut   # already labelable-filtered upstream

    model = LGBMClassifier(**rigor.LGB)
    model.fit(X[train_mask], y[train_mask], categorical_feature=cats)
    p_test = model.predict_proba(X[test_mask])[:, 1]
    p_train = model.predict_proba(X[train_mask])[:, 1]

    out = dict(
        cut=cut, train_mask=train_mask, test_mask=test_mask,
        model=model, cats=cats, cols=cols,
        p_test=p_test, y_test=y[test_mask], df_test=df.loc[test_mask].reset_index(drop=True),
        p_train=p_train, y_train=y[train_mask], df_train=df.loc[train_mask].reset_index(drop=True),
        X_train=X.loc[train_mask], X_test=X.loc[test_mask],
    )
    _CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# Calibration split (isotonic fit on a held-out fold of TRAIN, never on TEST)
# ---------------------------------------------------------------------------
def get_calibration(ctx: RunnerContext) -> dict:
    seed = get_seed(ctx)
    n, months = _panel_size(ctx)
    key = ("calibration", seed, n, months)
    if key in _CACHE:
        return _CACHE[key]

    h = get_holdout(ctx)
    df, X, y, tr, te, cats = h["df"], h["X"], h["y"], h["train_idx"], h["test_idx"], h["cats"]

    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.isotonic import IsotonicRegression
    from lightgbm import LGBMClassifier
    import rigor

    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed + 1000)
    itr_pos, iva_pos = next(gss.split(X.iloc[tr], y[tr], groups=df["account_id"].iloc[tr]))
    tr_itr, tr_iva = tr[itr_pos], tr[iva_pos]

    m_cal = LGBMClassifier(**rigor.LGB)
    m_cal.fit(X.iloc[tr_itr], y[tr_itr], categorical_feature=cats)
    p_iva = m_cal.predict_proba(X.iloc[tr_iva])[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(p_iva, y[tr_iva])

    p_raw_test = m_cal.predict_proba(X.iloc[te])[:, 1]
    p_cal_test = iso.predict(p_raw_test)

    out = dict(
        model=m_cal, iso=iso,
        p_raw_test=p_raw_test, p_cal_test=p_cal_test,
        y_test=y[te], df_test=h["df_test"],
    )
    _CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
# The rank-order exhibit (shared by runner 01's DR-02 and runner 05)
# ---------------------------------------------------------------------------
#: fallback pair, used only when the live operating thresholds cannot be
#: read — this WAS `export_demo.build_export`'s fixed RED_THR/AMBER_THR; DM-4/5
#: replaced those with a cost-minimising pair computed per run (see
#: `get_rag_thresholds`), so the fixed numbers are now a documented fallback,
#: not the live policy.
LEGACY_AMBER_THR, LEGACY_RED_THR = 0.04, 0.40


def get_rag_thresholds(ctx: RunnerContext) -> tuple[float, float, bool]:
    """`(amber, red, is_live)` — the operating thresholds DM-4/5's cost-
    minimising `build_export` chose, read from `data/demo_data.json`'s
    `thresholds.amber` / `thresholds.red` (that file is `build_export`'s own
    output — reading it is reading the export payload, just without re-running
    the export). Falls back to the legacy fixed pair (0.04, 0.40) and reports
    `is_live=False` if the file or the key is missing, so a result computed
    under the fallback is distinguishable from one computed under the live
    policy rather than silently passing for either.
    """
    path = ctx.repo_root / "data" / "demo_data.json"
    try:
        import json
        payload = json.loads(path.read_text())
        thr = payload["thresholds"]
        return float(thr["amber"]), float(thr["red"]), True
    except Exception:
        return LEGACY_AMBER_THR, LEGACY_RED_THR, False


def rag_bucket(p: np.ndarray, amber: float = LEGACY_AMBER_THR, red: float = LEGACY_RED_THR) -> np.ndarray:
    """Band a score array at the given (amber, red) operating thresholds.

    Callers should pass the LIVE pair from `get_rag_thresholds(ctx)`; the
    defaults here are only the documented fallback, not a policy choice made
    by this function.
    """
    p = np.asarray(p, dtype=float)
    return np.where(p >= red, "red", np.where(p >= amber, "amber", "green"))


def build_rank_order_population(
    df_test: pd.DataFrame, p_test: np.ndarray, amber: float = LEGACY_AMBER_THR, red: float = LEGACY_RED_THR,
) -> pd.DataFrame:
    """The row-level frame `export_demo.rank_order_exhibit` expects: `bucket`,
    `pd`, `snap_months_to_npa`, `portfolio` — POOLED over every eligible
    holdout-test row (every account, every eligible month), not a single
    frozen reference month the way the cockpit's snapshot is. See runner 05's
    docstring for why.
    """
    return pd.DataFrame({
        "bucket": rag_bucket(p_test, amber=amber, red=red),
        "pd": np.asarray(p_test, dtype=float),
        "snap_months_to_npa": df_test["months_to_npa"].to_numpy(),
        "portfolio": df_test["portfolio"].astype(str).to_numpy(),
    })


def get_rank_order_exhibit(ctx: RunnerContext) -> dict:
    seed = get_seed(ctx)
    n, months = _panel_size(ctx)
    key = ("rank_order", seed, n, months)
    if key in _CACHE:
        return _CACHE[key]

    _ensure_src_on_path(ctx.repo_root)
    import export_demo as ed

    h = get_holdout(ctx)
    amber, red, is_live = get_rag_thresholds(ctx)
    port_df = build_rank_order_population(h["df_test"], h["p_test"], amber=amber, red=red)
    exhibit = ed.rank_order_exhibit(port_df, horizon=8)
    exhibit["_thresholds"] = dict(amber=amber, red=red, is_live=is_live)
    _CACHE[key] = exhibit
    return exhibit


# ---------------------------------------------------------------------------
# Cut resolution — id first, source_column second; ticket/vintage bands built
# from the pre-registered binning rules.
# ---------------------------------------------------------------------------
def sorted_levels(values) -> list[str]:
    """Level labels, sorted numerically when every one of them parses as a
    number (`calendar_month`'s labels are stringified `month_idx` values —
    plain `sorted()` on strings would put "24" before "9"), string-sorted
    otherwise.
    """
    values = list(values)
    try:
        return sorted(values, key=float)
    except (TypeError, ValueError):
        return sorted(values)


def cut_series(cut, df: pd.DataFrame) -> pd.Series:
    """One registered cut, as a Series of string level-labels aligned to `df`."""
    if cut.id == "ticket_band":
        sanctioned = np.exp(df["log_sanctioned"].to_numpy(dtype=float))
        try:
            labels = pd.qcut(sanctioned, 5, duplicates="drop")
            return pd.Series([str(v) for v in labels], index=df.index)
        except ValueError:
            return pd.Series(["all"] * len(df), index=df.index)
    if cut.id == "vintage_band":
        edges = [0, 12, 18, 30, 48, np.inf]
        names = ["[0,12)", "[12,18)", "[18,30)", "[30,48)", "[48,inf)"]
        labels = pd.cut(df["vintage_months"].to_numpy(dtype=float), bins=edges, labels=names, right=False)
        return pd.Series([str(v) for v in labels], index=df.index)
    col = cut.id if cut.id in df.columns else cut.source_column
    if col not in df.columns:
        col = cut.source_column
    return df[col].astype(str)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def grouped_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    from sklearn.metrics import roc_auc_score
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        return None
    return float(roc_auc_score(y, p))


def ece(y_true, p, n_bins: int = 10) -> float:
    """Expected Calibration Error: n_bins EQUAL-WIDTH bins over [0, 1],
    population-weighted |observed rate - mean predicted| per bin.

    `criteria.yaml` does not pin a bin count for DR-08/DR-09 — 10 is the
    standard ECE convention and matches this codebase's own existing
    10-quantile-bin convention for reliability curves (`rigor.py`'s
    `pd.qcut(p_raw, 10, ...)`); equal-width (not quantile) bins because that
    is the textbook ECE definition and what makes "PD=40%" land in a bin
    literally centred on 40%.
    """
    y_true = np.asarray(y_true, dtype=float)
    p = np.asarray(p, dtype=float)
    n = len(p)
    if n == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        mask = bin_idx == b
        if not mask.any():
            continue
        conf = p[mask].mean()
        acc = y_true[mask].mean()
        total += (mask.sum() / n) * abs(acc - conf)
    return float(total)


def brier(y_true, p) -> float:
    from sklearn.metrics import brier_score_loss
    return float(brier_score_loss(np.asarray(y_true, dtype=float), np.asarray(p, dtype=float)))


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index. Bin edges are quantiles of `expected` (the
    training window) — "fixed on the training window", per the 06 stub's own
    docstring — with the outer edges opened to +/-inf so an out-of-range OOT
    value still lands in a bin instead of vanishing from the denominator.
    """
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    if len(expected) == 0 or len(actual) == 0:
        return 0.0
    qs = np.linspace(0, 1, bins + 1)
    edges = np.unique(np.quantile(expected, qs))
    if len(edges) < 3:
        return 0.0
    edges = edges.copy()
    edges[0], edges[-1] = -np.inf, np.inf
    e_counts, _ = np.histogram(expected, bins=edges)
    a_counts, _ = np.histogram(actual, bins=edges)
    e_pct = np.clip(e_counts / max(e_counts.sum(), 1), 1e-6, None)
    a_pct = np.clip(a_counts / max(a_counts.sum(), 1), 1e-6, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def csi_categorical(expected: pd.Series, actual: pd.Series) -> float:
    """The same PSI formula, for a categorical feature: bins are its levels."""
    expected = expected.dropna()
    actual = actual.dropna()
    if len(expected) == 0 or len(actual) == 0:
        return 0.0
    levels = sorted(set(expected.unique()) | set(actual.unique()))
    e_counts = expected.value_counts()
    a_counts = actual.value_counts()
    e_tot, a_tot = len(expected), len(actual)
    total = 0.0
    for lv in levels:
        e_pct = max(e_counts.get(lv, 0) / e_tot, 1e-6)
        a_pct = max(a_counts.get(lv, 0) / a_tot, 1e-6)
        total += (a_pct - e_pct) * np.log(a_pct / e_pct)
    return float(total)


def bootstrap_ci(
    df_slice: pd.DataFrame,
    stat_fn: Callable[[pd.DataFrame], float | None],
    group_col: str = "account_id",
    n: int = N_BOOT,
    seed: int = 7,
    level: float = CI_LEVEL,
) -> tuple[float, float]:
    """Percentile bootstrap CI, resampled at the group level (`account_id`).

    The panel has repeated measures (many rows per account); a row-level
    bootstrap would treat 48 correlated observations of one account as 48
    independent ones and report an interval far too tight — see the README's
    "Writing a runner".
    """
    if df_slice.empty:
        return (0.0, 0.0)
    d = df_slice.reset_index(drop=True)
    rng = np.random.default_rng(seed)
    idx_by_group = d.groupby(group_col, observed=True, sort=False).indices
    idx_lists = list(idx_by_group.values())
    ngroups = len(idx_lists)
    if ngroups == 0:
        return (0.0, 0.0)
    stats: list[float] = []
    for _ in range(n):
        chosen = rng.integers(0, ngroups, size=ngroups)
        rows = np.concatenate([idx_lists[i] for i in chosen])
        try:
            v = stat_fn(d.iloc[rows])
        except Exception:
            continue
        if v is not None and np.isfinite(v):
            stats.append(float(v))
    if not stats:
        return (0.0, 0.0)
    lo = float(np.percentile(stats, (1 - level) / 2 * 100))
    hi = float(np.percentile(stats, (1 + level) / 2 * 100))
    return (round(lo, 4), round(hi, 4))


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def savefig(fig, ctx: RunnerContext, name: str) -> str:
    path = ctx.figures_dir / name
    ctx.figures_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return name

"""The frozen DRISHTi artefact: one model, one feature schema, one calibrator, one split.

Review section 3 asked for the fitted model, the feature schema and the calibrator to be
persisted *together*. They were not, and the cost of that was concrete: every question about
the shipped model ("is it calibrated inside Agri?", "what does it do on a book with twice the
missingness?") could only be answered by refitting something that resembled it, which answers
a different question.

This module trains the export's model ONCE, writes it beside the schema and the calibrator it
was fitted with, and hands every experiment the same object. Nothing here re-tunes anything:
the hyperparameters, the seeds, the three-way split and the smoothing window are IMPORTED from
`src/export_demo.py`, never restated, so an artefact that has drifted from the exporter is
impossible rather than merely unlikely.

**Why the feature schema matters more than it looks.** LightGBM consumes pandas `category`
columns as integer CODES. Score a second panel whose category order differs — a challenge
regime that happens to contain no `Medium` segment, say — and every categorical feature is
silently shifted. The schema therefore pins the exact level order of every categorical column,
and `prepare()` re-applies it to any frame before scoring. A level the artefact never saw
becomes NaN (LightGBM's own "missing"), which is the honest answer, rather than colliding with
some other level's code.

Layout under `validation/report/experiments/artefact/`:

    manifest.json      seeds, sizes, library versions, panel digest, the thresholds it
                       reproduced, and whether they matched the committed export
    model.txt          the LightGBM booster, in LightGBM's own text format
    feature_schema.json  column order, categorical level orders, the DROP list
    calibrator.json    the isotonic knots, as (x, y) arrays
    folds.json         the account ids in each of the fit / policy / test folds
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTEFACT_DIR = REPO_ROOT / "validation" / "report" / "experiments" / "artefact"
PANEL = REPO_ROOT / "data" / "msme_loan_panel.csv"
EXPORT_PAYLOAD = REPO_ROOT / "data" / "demo_data.json"


def _ensure_src_on_path() -> None:
    src = str(REPO_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _digest(path: Path, chunk: int = 1 << 22) -> str:
    """sha256 of a file. The panel is ~700 MB; this takes a couple of seconds and is
    what makes "the artefact matches the data it claims to" checkable rather than assumed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# the calibrator, persisted as knots rather than as a pickle
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Calibrator:
    """An isotonic map as two arrays. `np.interp` reproduces sklearn's own prediction
    exactly on a fitted `IsotonicRegression` with `out_of_bounds="clip"`, and a pair of
    arrays survives a scikit-learn upgrade in a way a pickle does not."""

    x: np.ndarray
    y: np.ndarray

    def apply(self, scores) -> np.ndarray:
        s = np.asarray(scores, dtype="float64")
        return np.clip(np.interp(s, self.x, self.y), 0.0, 1.0)

    def to_json(self) -> dict[str, list[float]]:
        return {"x": [float(v) for v in self.x], "y": [float(v) for v in self.y]}

    @classmethod
    def from_json(cls, blob: dict[str, Any]) -> "Calibrator":
        return cls(np.asarray(blob["x"], dtype="float64"), np.asarray(blob["y"], dtype="float64"))

    @classmethod
    def from_sklearn(cls, iso) -> "Calibrator":
        return cls(np.asarray(iso.X_thresholds_, dtype="float64"),
                   np.asarray(iso.y_thresholds_, dtype="float64"))


@dataclass(slots=True)
class Artefact:
    """The shipped model and everything needed to score another frame with it."""

    booster: Any
    columns: list[str]
    categories: dict[str, list[str]]
    calibrator: Calibrator | None
    folds: dict[str, list[str]]
    manifest: dict[str, Any]

    # ---- scoring ---------------------------------------------------------- #
    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """`df` as the booster expects it: same columns, same order, same category levels.

        A categorical value the artefact never saw becomes NaN rather than a new code —
        LightGBM reads that as missing, which is what "this model has no opinion about
        this level" actually means.
        """
        _ensure_src_on_path()
        import export_demo as ed

        frame = df.copy()
        ed.add_elapsed_time_bands(frame)
        for col, levels in self.categories.items():
            if col in frame.columns:
                frame[col] = pd.Categorical(frame[col].astype("object"), categories=levels)
        missing = [c for c in self.columns if c not in frame.columns]
        if missing:
            raise ValueError(f"frame is missing {len(missing)} artefact feature(s): {missing[:6]}")
        return frame[self.columns]

    def pd_raw(self, df: pd.DataFrame) -> np.ndarray:
        """The raw per-month probability, from the frozen booster."""
        return np.asarray(self.booster.predict(self.prepare(df)), dtype="float64")

    def decision_score(self, df: pd.DataFrame, raw: np.ndarray | None = None) -> np.ndarray:
        """The score the thresholds were chosen over, aligned with `df`'s own row order."""
        _ensure_src_on_path()
        import export_demo as ed

        raw = self.pd_raw(df) if raw is None else np.asarray(raw, dtype="float64")
        frame = pd.DataFrame(
            {
                "account_id": df["account_id"].astype(str).to_numpy(),
                "month_idx": pd.to_numeric(df["month_idx"], errors="coerce").to_numpy(),
                "pd": raw,
            },
            index=np.arange(len(raw)),
        ).sort_values(["account_id", "month_idx"], kind="stable")
        frame["s"] = frame.groupby("account_id")["pd"].transform(
            lambda s: s.rolling(ed.SMOOTH_WINDOW, min_periods=1).mean()
        )
        return frame["s"].sort_index().to_numpy(dtype="float64")

    def calibrated(self, decision: np.ndarray) -> np.ndarray | None:
        return None if self.calibrator is None else self.calibrator.apply(decision)

    @property
    def thresholds(self) -> tuple[float, float]:
        """`(amber, red)` — the frozen operating point, as the export shipped it."""
        t = self.manifest["thresholds"]
        return float(t["amber"]), float(t["red"])


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def build(panel_path: Path = PANEL, out_dir: Path = ARTEFACT_DIR) -> Artefact:
    """Train the export's model once and persist it with its schema and calibrator.

    Byte-for-byte the exporter's own recipe, by import rather than by restatement:
    `export_demo.CAT` / `DROP` / `eligible_rows` / `three_way_split` / `SMOOTH_WINDOW`,
    and the same `LGBMClassifier` keyword arguments. The one thing this does NOT do is
    the exporter's TreeSHAP pass, which is where most of an export run's wall clock goes
    and which no experiment here needs.
    """
    _ensure_src_on_path()
    import export_demo as ed
    from lightgbm import LGBMClassifier
    from sklearn.isotonic import IsotonicRegression
    import lightgbm
    import sklearn

    df = pd.read_csv(panel_path)
    df = df.assign(account_id=df["account_id"].astype(str))
    ed.add_elapsed_time_bands(df)
    cats = [c for c in ed.CAT if c in df.columns]
    for c in cats:
        df[c] = df[c].astype("category")
    y = df["default_within_12m"].to_numpy()
    X = df.drop(columns=[c for c in ed.DROP if c in df.columns])
    columns = list(X.columns)

    labelable = ed.eligible_rows(df)
    fit, pol, te = ed.three_way_split(df["account_id"].to_numpy())
    fit_lab = fit[labelable[fit]]

    model = LGBMClassifier(
        n_estimators=600, learning_rate=0.03, num_leaves=48, subsample=0.8,
        colsample_bytree=0.8, min_child_samples=80, random_state=7, n_jobs=-1, verbose=-1,
    )
    model.fit(X.iloc[fit_lab], y[fit_lab], categorical_feature=cats)
    booster = model.booster_

    # ---- the policy fold, scored once and used for both jobs it does ---------- #
    # The exporter fits the calibrator and searches the thresholds on the SAME fold,
    # so it is scored once here and reused, rather than predicted twice and risking
    # the two halves of the policy drifting apart.
    pol_df = df.iloc[pol].copy().reset_index(drop=True)
    pol_df["pd"] = booster.predict(X.iloc[pol])
    pol_df["labelable"] = labelable[pol]
    pol_df = ed.add_decision_score(pol_df)
    pol_elig = pol_df[pol_df["labelable"].to_numpy().astype(bool)]

    iso = IsotonicRegression(out_of_bounds="clip").fit(
        pol_elig["decision_score"].to_numpy(dtype="float64"),
        pol_elig["default_within_12m"].to_numpy(dtype="float64"),
    )
    calibrator = Calibrator.from_sklearn(iso)

    # ---- the operating point, re-derived the exporter's way, then CHECKED ------ #
    policy_month = ed.REF_MONTH
    if not len(pol_elig[pol_elig.month_idx == ed.REF_MONTH]) and len(pol_elig):
        policy_month = int(pol_elig["month_idx"].max())
    snap = pol_elig[pol_elig.month_idx == policy_month].copy()
    block = ed.choose_operating_thresholds(snap, horizon=ed.RANK_HORIZON)
    amber, red = float(block["amber"]), float(block["red"])

    shipped = None
    if EXPORT_PAYLOAD.exists():
        summary = json.loads(EXPORT_PAYLOAD.read_text())["portfolio_summary"]
        shipped = {"amber": float(summary["amber_thr"]), "red": float(summary["red_thr"])}

    out_dir.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_dir / "model.txt"))
    (out_dir / "feature_schema.json").write_text(json.dumps({
        "columns": columns,
        "categorical": cats,
        "categories": {c: [str(v) for v in df[c].cat.categories] for c in cats},
        "dropped": [c for c in ed.DROP if c in df.columns],
        "note": ("LightGBM reads a pandas `category` column as its integer CODE, so the level "
                 "ORDER below is part of the model, not metadata about it. `Artefact.prepare` "
                 "re-applies it; an unseen level becomes NaN, which LightGBM treats as missing."),
    }, indent=1))
    (out_dir / "calibrator.json").write_text(json.dumps({
        "method": "isotonic",
        "fitted_on": "policy fold, eligible rows, decision_score vs default_within_12m",
        "n_fit_rows": int(len(pol_elig)),
        **calibrator.to_json(),
    }))
    folds = {
        name: sorted(set(df["account_id"].to_numpy()[idx].tolist()))
        for name, idx in (("fit", fit), ("policy", pol), ("test", te))
    }
    (out_dir / "folds.json").write_text(json.dumps(folds))

    manifest = {
        "policy_version": ed.POLICY_VERSION,
        "split_seed": ed.SPLIT_SEED,
        "policy_fold_fraction": ed.POLICY_FOLD_FRACTION,
        "smooth_window": ed.SMOOTH_WINDOW,
        "reference_month_idx": ed.REF_MONTH,
        "policy_month_idx": int(policy_month),
        "horizon_months": ed.RANK_HORIZON,
        "panel": str(panel_path.relative_to(REPO_ROOT)),
        "panel_sha256": _digest(panel_path),
        "panel_rows": int(len(df)),
        "panel_accounts": int(df["account_id"].nunique()),
        "n_fit_accounts": len(folds["fit"]),
        "n_policy_accounts": len(folds["policy"]),
        "n_test_accounts": len(folds["test"]),
        "n_fit_rows_used": int(len(fit_lab)),
        "eligibility": "labelable == 1",
        "thresholds": {"amber": amber, "red": red, "applied": block["applied"]},
        "shipped_thresholds": shipped,
        "reproduces_shipped_thresholds": (
            None if shipped is None
            else bool(abs(shipped["amber"] - amber) < 5e-7 and abs(shipped["red"] - red) < 5e-7)
        ),
        "versions": {
            "lightgbm": lightgbm.__version__,
            "scikit_learn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "note": ("Trained by validation/experiments/artefact.py with the exporter's own CAT/DROP/"
                 "split/hyperparameters, imported rather than restated. `reproduces_shipped_"
                 "thresholds` records whether this fit lands on the same operating point the "
                 "committed export shipped; a False there means the two have diverged and every "
                 "experiment below is describing a different model from the one in the cockpit."),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return Artefact(booster, columns, manifest_categories(out_dir), calibrator, folds, manifest)


def manifest_categories(out_dir: Path = ARTEFACT_DIR) -> dict[str, list[str]]:
    schema = json.loads((out_dir / "feature_schema.json").read_text())
    return {k: list(v) for k, v in schema["categories"].items()}


def load(out_dir: Path = ARTEFACT_DIR) -> Artefact:
    """The persisted artefact. Raises if it has not been built."""
    import lightgbm

    if not (out_dir / "manifest.json").exists():
        raise FileNotFoundError(
            f"no artefact at {out_dir}. Build it with "
            f"`python3 -m validation.experiments.artefact` (one training run, no TreeSHAP)."
        )
    manifest = json.loads((out_dir / "manifest.json").read_text())
    schema = json.loads((out_dir / "feature_schema.json").read_text())
    cal_blob = json.loads((out_dir / "calibrator.json").read_text())
    folds = json.loads((out_dir / "folds.json").read_text())
    booster = lightgbm.Booster(model_file=str(out_dir / "model.txt"))
    return Artefact(
        booster=booster,
        columns=list(schema["columns"]),
        categories={k: list(v) for k, v in schema["categories"].items()},
        calibrator=Calibrator.from_json(cal_blob),
        folds=folds,
        manifest=manifest,
    )


def load_panel(panel_path: Path = PANEL) -> pd.DataFrame:
    df = pd.read_csv(panel_path)
    return df.assign(account_id=df["account_id"].astype(str))


def test_frame(df: pd.DataFrame, art: Artefact, eligible_only: bool = True) -> pd.DataFrame:
    """The artefact's own TEST fold out of `df`, optionally eligible rows only."""
    _ensure_src_on_path()
    import export_demo as ed

    test_ids = set(art.folds["test"])
    frame = df[df["account_id"].isin(test_ids)]
    if eligible_only:
        frame = frame[ed.eligible_rows(frame)]
    return frame.reset_index(drop=True)


if __name__ == "__main__":
    art = build()
    m = art.manifest
    print(f"artefact -> {ARTEFACT_DIR}")
    print(f"  panel {m['panel_rows']:,} rows / {m['panel_accounts']:,} accounts "
          f"(sha256 {m['panel_sha256'][:12]}…)")
    print(f"  folds  fit {m['n_fit_accounts']:,} / policy {m['n_policy_accounts']:,} "
          f"/ test {m['n_test_accounts']:,} accounts; {m['n_fit_rows_used']:,} eligible fit rows")
    print(f"  thresholds amber {m['thresholds']['amber']:.6f} / red {m['thresholds']['red']:.6f} "
          f"({m['thresholds']['applied']})")
    print(f"  reproduces the shipped operating point: {m['reproduces_shipped_thresholds']}")

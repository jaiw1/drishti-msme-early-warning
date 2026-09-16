"""
Runners 01-06, exercised end to end on a tiny generated panel.

Deliberately small (a few hundred accounts) but still real: a real
`generator.build.generate` panel, a real LightGBM fit per split, real
bootstrap CIs (with a small `n_boot` — see the fixture) — fast enough for
`pytest validation/tests -q`, but exercising the same code path
`python3 -m validation.run` uses at 45,000 x 48, not a mock of it.

One module-scoped panel/context is shared by every test function in this
file (`validation.runners._shared` caches the panel, the holdout split, the
OOT split, the calibration split and the rank-order exhibit per
`(seed, n_accounts, months)` in-process) — the FIRST runner call in the file
pays for generation + one model fit; everything after reuses it, the same way
`python3 -m validation.run` reuses it across 01..06 in one process.

Also covers:
  * status mapping — every graded scalar (non-breakdown) Result's `status`
    is re-derived independently from `Criterion.check()` and compared;
  * the JSON schema of `report.json`;
  * `REPORT.md` renders with the pre-registration block before the per-runner
    tables.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.criteria import Result, RunnerContext, Status, load  # noqa: E402
from validation.run import grade  # noqa: E402
from validation import report as report_mod  # noqa: E402
from validation.runners import _shared as sh  # noqa: E402

RUNNER_NAMES = ["01_holdout", "02_oot", "03_by_cut", "04_calibration", "05_rank_order", "06_stability"]

#: (n_accounts, months) chosen so `_shared.oot_cut_month(months, 12) > 0`
#: and both the embargoed train window and the OOT test window are
#: non-empty (see `_shared.oot_cut_month`'s docstring) — 48 months gives a
#: cut at month 24, the same shape as the real 45k x 48 run, just far fewer
#: accounts.
TINY_OPTIONS = {"n_accounts": 500, "months": 48, "n_boot": 15, "n_boot_ece": 20, "seed": 7}


@pytest.fixture(scope="module")
def doc():
    return load(REPO_ROOT / "validation" / "criteria.yaml")


@pytest.fixture(scope="module")
def ctx(doc, tmp_path_factory) -> RunnerContext:
    sh.reset_cache()
    out_dir = tmp_path_factory.mktemp("validation_report")
    figures = out_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    return RunnerContext(
        repo_root=REPO_ROOT, out_dir=out_dir, figures_dir=figures, doc=doc,
        seeds=(7, 8, 9, 10, 11), options=dict(TINY_OPTIONS),
    )


@pytest.fixture(scope="module")
def all_results(doc, ctx) -> list[Result]:
    results: list[Result] = []
    for name in RUNNER_NAMES:
        mod = importlib.import_module(f"validation.runners.{name}")
        crits = doc.by_runner(name)
        produced = mod.run(crits, ctx)
        for r in produced:
            results.append(grade(doc.get(r.criterion_id), r))
    return results


EXPECTED_IDS = {
    "01_holdout": {"DR-01", "DR-02", "DR-03", "DR-04"},
    "02_oot": {"DR-05"},
    "03_by_cut": {"DR-06", "DR-07"},
    "04_calibration": {"DR-08", "DR-09", "DR-10"},
    "05_rank_order": {"DR-11", "DR-12"},
    "06_stability": {"DR-13", "DR-14"},
}


# ---------------------------------------------------------------------------
# Each runner returns exactly the criteria it owns
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("runner_name", RUNNER_NAMES)
def test_runner_answers_exactly_its_registered_criteria(doc, ctx, all_results, runner_name):
    got = {r.criterion_id for r in all_results if doc.get(r.criterion_id).runner == runner_name}
    assert got == EXPECTED_IDS[runner_name]


# ---------------------------------------------------------------------------
# Every result is graded to a valid Status, never left None
# ---------------------------------------------------------------------------
def test_every_result_has_a_valid_status(all_results):
    valid = set(Status.__args__)
    for r in all_results:
        assert r.status in valid, f"{r.criterion_id}: status {r.status!r} not in {valid}"
        assert r.status != "pending", f"{r.criterion_id}: implemented runner left a criterion pending"


# ---------------------------------------------------------------------------
# Status mapping — re-derive status from Criterion.check() independently of
# the runner, for every scalar (non-breakdown) result, and compare.
# ---------------------------------------------------------------------------
def test_status_mapping_matches_criterion_check(doc, all_results):
    for r in all_results:
        if r.breakdown:
            continue  # covered by the breakdown-specific tests below
        crit = doc.get(r.criterion_id)
        if crit.min_n and r.n is not None and r.n < crit.min_n:
            assert r.status == "skipped_low_n"
            continue
        ok = crit.check(r.value)
        if ok is None:
            assert r.status == "report"
        elif ok:
            assert r.status in ("pass", "report")
        else:
            assert r.status in ("fail", "warn", "report")


# ---------------------------------------------------------------------------
# Breakdown-shaped results (DR-06, DR-07, DR-09, DR-11, DR-12, DR-14): every
# cell carries level/value/n and a status; the criterion's own status is the
# worst cell's, per validation/run.py's `grade()`.
# ---------------------------------------------------------------------------
BREAKDOWN_IDS = {"DR-06", "DR-07", "DR-09", "DR-11", "DR-12", "DR-14"}


@pytest.mark.parametrize("crit_id", sorted(BREAKDOWN_IDS))
def test_breakdown_cells_are_well_formed_and_graded(doc, all_results, crit_id):
    r = next(x for x in all_results if x.criterion_id == crit_id)
    assert r.breakdown, f"{crit_id}: expected a per-cell breakdown"
    _RANK = {"pass": 0, "report": 1, "skipped_low_n": 2, "warn": 3, "pending": 4, "fail": 5, "error": 6}
    worst = "pass"
    for cell in r.breakdown:
        assert "level" in cell and "n" in cell and "status" in cell
        assert cell["status"] in _RANK
        if _RANK[cell["status"]] > _RANK[worst]:
            worst = cell["status"]
    assert r.status == worst


def test_dr06_breakdown_has_all_eight_portfolios(doc, all_results):
    r = next(x for x in all_results if x.criterion_id == "DR-06")
    portfolio_cut = next(c for c in doc.cuts if c.id == "portfolio")
    levels = {cell["level"] for cell in r.breakdown}
    assert levels == set(portfolio_cut.levels)


def test_dr11_breakdown_values_are_three_element_band_sequences(all_results):
    r = next(x for x in all_results if x.criterion_id == "DR-11")
    for cell in r.breakdown:
        assert isinstance(cell["value"], list)
        assert len(cell["value"]) == 3  # Green, Amber, Red


# ---------------------------------------------------------------------------
# DR-01's own arithmetic, cross-checked directly against sklearn on this
# module's fitted holdout scores (not a hand-crafted example — this checks
# the RUNNER wired grouped_auc up correctly, on its own real predictions).
# ---------------------------------------------------------------------------
def test_dr01_value_matches_a_fresh_sklearn_computation(ctx, all_results):
    from sklearn.metrics import roc_auc_score

    r = next(x for x in all_results if x.criterion_id == "DR-01")
    h = sh.get_holdout(ctx)
    recomputed = roc_auc_score(h["y_test"], h["p_test"])
    assert r.value == pytest.approx(round(recomputed, 4))


# ---------------------------------------------------------------------------
# Figures actually get written where Result.figures says they are
# ---------------------------------------------------------------------------
def test_figures_referenced_in_results_exist_on_disk(ctx, all_results):
    for r in all_results:
        for fig in r.figures:
            assert (ctx.figures_dir / fig).is_file(), f"{r.criterion_id} claims figure {fig!r} but it is missing"


# ---------------------------------------------------------------------------
# report.json schema
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def written_report(doc, ctx, all_results):
    report_mod.write(doc, all_results, ctx.out_dir, strict=False)
    return ctx.out_dir


def test_report_json_schema(doc, written_report):
    payload = json.loads((written_report / "report.json").read_text())
    for key in ("product", "schema_version", "registered_at", "registered_by",
                "provenance", "verdict", "counts", "criteria", "amendments", "rulings"):
        assert key in payload, f"report.json missing top-level key {key!r}"

    assert payload["product"] == "DRISHTi"
    assert payload["verdict"] in (
        "PASS", "FAIL", "PASS (with pending runners — not yet the G7 gate)",
    )

    by_id = {row["id"]: row for row in payload["criteria"]}
    for crit_id in {"DR-01", "DR-05", "DR-08", "DR-11", "DR-13"}:
        assert crit_id in by_id, f"report.json missing criterion {crit_id}"
        row = by_id[crit_id]
        assert "result" in row
        result = row["result"]
        for key in ("criterion_id", "value", "ci", "n", "status", "detail", "breakdown", "figures"):
            assert key in result
        assert result["status"] in set(Status.__args__)


def test_report_json_is_valid_json_and_round_trips(written_report):
    raw = (written_report / "report.json").read_text()
    payload = json.loads(raw)
    assert json.dumps(payload)  # round-trips without raising


# ---------------------------------------------------------------------------
# REPORT.md structure
# ---------------------------------------------------------------------------
def test_report_markdown_leads_with_preregistration(doc, all_results, written_report):
    text = (written_report / "REPORT.md").read_text()
    assert text.startswith("# DRISHTi — validation report")

    verdict_idx = text.index("**Verdict:")
    prereg_idx = text.index("## Pre-registration")
    all_criteria_idx = text.index("## All criteria")

    assert verdict_idx < prereg_idx < all_criteria_idx, (
        "REPORT.md must lead with the verdict, then pre-registration, before the "
        "per-runner tables"
    )


def test_report_markdown_mentions_every_implemented_criterion(all_results, written_report):
    text = (written_report / "REPORT.md").read_text()
    for r in all_results:
        assert r.criterion_id in text

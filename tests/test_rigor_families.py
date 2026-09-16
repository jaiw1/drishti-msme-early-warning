"""DM-2 / architect ruling 3: the RIGOR pack's feature families and its JSON.

The leakage exhibit answers DR-15 — "at 10-12 months before NPA, the days-past-due
family contributes at most 5% of the model's attention".  That number is a RATIO, so it
is only honest if the denominator is the whole model: any column no family claims drops
silently out of the total and flatters the DPD share.  With the eight-portfolio panel
adding 33 columns, that is no longer a theoretical risk, so the mapping being total is
asserted rather than assumed.

The second thing pinned here is the ruling itself: "Demand vs collection" is its own
family, AND the alternative reading (folded into days-past-due) is computed and emitted
beside it, so the model card can show both instead of inheriting one silently.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import rigor  # noqa: E402  (path shim must run first)
from generator.build import PANEL_COLUMNS  # noqa: E402


def test_no_column_is_left_unfamilied():
    """The ruling's test: zero orphans, over the generator's own column list."""
    assert rigor.unfamilied_columns() == []


def test_no_column_is_left_unfamilied_against_the_written_panel():
    """And again against the CSV on disk, if the pipeline has been run."""
    panel = Path(__file__).resolve().parents[1] / "data" / "msme_loan_panel.csv"
    if not panel.exists():
        pytest.skip("panel not generated in this checkout")
    columns = pd.read_csv(panel, nrows=1).columns.tolist()
    assert rigor.unfamilied_columns(columns) == []


def test_every_familied_column_actually_exists_in_the_panel():
    """The other direction: a typo in GROUPS would quietly contribute nothing.

    DM-8 round 2: `months_since_moratorium_end_band` (and any future
    `_ELAPSED_TIME_BANDS` entry) is not a generator column — `src/generator/**`
    is frozen this round, so it is built post-hoc by
    `rigor.add_elapsed_time_bands` from a real panel column instead. Those
    derived names are the one allowed exception to "every familied column is a
    real PANEL_COLUMN"; anything else is still a typo.
    """
    familied = {f for feats in rigor.GROUPS.values() for f in feats}
    derived = {f"{col}_band" for col in rigor._ELAPSED_TIME_BANDS}
    unexplained = familied - set(PANEL_COLUMNS) - derived
    assert not unexplained, sorted(unexplained)


def test_no_column_belongs_to_two_families():
    """Double-counting inflates the denominator and deflates every share."""
    seen, duplicated = set(), set()
    for feats in rigor.GROUPS.values():
        for f in feats:
            (duplicated if f in seen else seen).add(f)
    assert not duplicated, sorted(duplicated)


def test_dropped_columns_are_never_scored():
    """`months_to_npa` and the label must not reach a family — that would be leakage."""
    familied = {f for feats in rigor.GROUPS.values() for f in feats}
    assert not familied & set(rigor.DROP)


def test_demand_vs_collection_is_its_own_family():
    """The architect's ruling, pinned so a later tidy-up cannot quietly undo it."""
    assert rigor.COLLECTION_FAMILY in rigor.GROUPS
    assert rigor.COLLECTION_FAMILY != rigor.DPD_FAMILY
    assert set(rigor.GROUPS[rigor.COLLECTION_FAMILY]) == {
        "collection_ratio", "collection_ratio_3m", "demanded_amount", "collected_amount",
    }
    assert not set(rigor.GROUPS[rigor.DPD_FAMILY]) & set(rigor.GROUPS[rigor.COLLECTION_FAMILY])


def test_the_alternative_reading_is_the_two_families_together():
    assert rigor.ALT_DPD_FAMILIES == (rigor.DPD_FAMILY, rigor.COLLECTION_FAMILY)
    assert all(f in rigor.GROUPS for f in rigor.ALT_DPD_FAMILIES)


def test_cat_carries_the_five_sd_d2_statics_and_matches_export_demo():
    """One panel, one categorical list — a divergence would train two different models."""
    import export_demo

    assert rigor.CAT == export_demo.CAT
    assert rigor.DROP == export_demo.DROP
    for column in ("portfolio", "constitution", "state", "city_tier", "nic_group"):
        assert column in rigor.CAT


def test_every_categorical_is_familied_as_borrower_profile():
    profile = set(rigor.GROUPS["Borrower profile"])
    assert set(rigor.CAT) <= profile


def test_written_rigor_json_is_strict_json_and_carries_both_readings():
    """The file is embedded whole into demo_data.json, so it must parse in a browser."""
    path = Path(__file__).resolve().parents[1] / "data" / "rigor.json"
    if not path.exists():
        pytest.skip("rigor.json not generated in this checkout")
    payload = json.loads(
        path.read_text(),
        parse_constant=lambda c: pytest.fail(f"rigor.json carried the JSON-invalid literal {c!r}"),
    )
    if "leakage_families" not in payload:
        pytest.skip("rigor.json predates the leakage_families block")
    assert payload["leakage_families"]["bucket"] == rigor.LEAKAGE_BUCKET
    assert payload["leakage_dpd_share"] == payload["leakage_families"]["primary"]["share"]
    assert payload["leakage_alt_dpd_share"] == payload["leakage_families"]["alternative"]["share"]
    # the alternative can only ever be the larger of the two: it is a superset of families
    assert payload["leakage_alt_dpd_share"] >= payload["leakage_dpd_share"]
    for bucket in payload["leakage_by_lead"]:
        assert set(bucket["shares"]) == set(rigor.GROUPS)
        assert bucket["dpd_share_alt"] >= bucket["dpd_share"]
        assert sum(bucket["shares"].values()) == pytest.approx(100.0, abs=0.5)


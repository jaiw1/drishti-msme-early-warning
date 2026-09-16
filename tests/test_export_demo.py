"""DM-2 / DM-3: the cockpit export against the eight-portfolio panel.

Two things are being defended here.

**The payload must be JSON.**  Five of the eight portfolios have no credit limit and
five file no GST return, so ``utilisation`` and ``sales_trend_3m`` are NaN for most of
the book.  ``float(nan)`` reaches ``json.dump`` as a bare ``NaN`` literal, which is not
JSON — ``JSON.parse`` in the browser rejects the whole file and the cockpit shows
nothing.  The tests below dump with ``allow_nan=False`` (the same guard the pipeline
uses) and re-read with the strict parser, so a regression fails here rather than on
stage.

**An absent channel must read as absent, not as zero.**  A housing borrower's
utilisation is not 0% — the bank simply has no such number.  Every account therefore
carries ``channels_present``, and it has to agree with what its portfolio declares in
the registry.

The end-to-end tests run the real pipeline (generator -> LightGBM -> payload) on a
deliberately small panel.  Small means the per-portfolio bands are far too thin to
rank-order, so the DR-11/DR-12 gate is exercised on hand-built exhibits instead.
"""

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import export_demo  # noqa: E402  (path shim must run first)
from generator import GeneratorConfig, generate  # noqa: E402
from generator.portfolios import ALL_CHANNELS, PORTFOLIOS  # noqa: E402

#: small enough to train in a few seconds, wide enough that every portfolio appears and
#: `month_idx == REF_MONTH` exists
EXPORT_ACCOUNTS = 1_600
EXPORT_MONTHS = 30


@pytest.fixture(scope="module")
def payload() -> dict:
    """The real export payload, built end to end on a small eight-portfolio panel."""
    panel, accounts = generate(
        GeneratorConfig(n_accounts=EXPORT_ACCOUNTS, months=EXPORT_MONTHS)
    )
    panel = panel.assign(account_id=panel.account_id.astype(str))
    static = accounts.assign(account_id=accounts.account_id.astype(str)).set_index("account_id")
    return export_demo.build_export(panel, static)


# --------------------------------------------------------------------------- #
# DM-2 — categoricals
# --------------------------------------------------------------------------- #
def test_cat_carries_the_five_sd_d2_statics():
    """Without these LightGBM raises "pandas dtypes must be int, float or bool"."""
    for column in ("portfolio", "constitution", "state", "city_tier", "nic_group"):
        assert column in export_demo.CAT


def test_cat_excludes_the_genuinely_numeric_statics():
    for column in ("secured", "tenor_months", "interest_rate_pa"):
        assert column not in export_demo.CAT


def test_cat_and_drop_do_not_overlap():
    assert not set(export_demo.CAT) & set(export_demo.DROP)


def test_every_label_the_generator_declares_is_dropped():
    """The leakage guard that survives the next label.

    ``sma2_within_6m`` arrived with SD-D5 and is forward-looking; left in the feature
    matrix it hands the model the answer.  Pinning DROP against the generator's OWN
    declaration means the next label to arrive fails here instead of quietly inflating
    the AUC.  ``_LABEL_COLUMNS`` is private, and reading it is the point: it is the
    authoritative list, and this test is what makes it a contract.
    """
    from generator.build import _LABEL_COLUMNS

    missing = set(_LABEL_COLUMNS) - set(export_demo.DROP)
    assert not missing, f"forward-looking columns still being trained on: {sorted(missing)}"


def test_the_panel_has_no_column_the_export_neither_drops_nor_scores():
    """Every panel column is either a label we drop or a feature we score."""
    from generator.build import PANEL_COLUMNS

    assert set(export_demo.DROP) <= set(PANEL_COLUMNS)


# --------------------------------------------------------------------------- #
# DM-2 — NaN safety
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), None, "x"])
def test_jnum_refuses_everything_that_is_not_a_finite_number(value):
    assert export_demo.jnum(value) is None
    assert export_demo.jint(value) is None


def test_jnum_rounds_and_keeps_real_numbers():
    assert export_demo.jnum(0.123456, 3) == 0.123
    assert export_demo.jnum(0.0, 3) == 0.0          # an observed zero survives as zero
    assert export_demo.jint(7.6) == 7


def test_payload_is_strict_json(payload):
    """The guard the pipeline itself uses: `allow_nan=False` rejects NaN and Infinity."""
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["portfolio"]


def test_payload_survives_the_strict_parser(payload, tmp_path):
    """`json.loads` with no NaN constants is the browser's JSON.parse, near enough."""
    path = tmp_path / "demo_data.json"
    path.write_text(json.dumps(payload, allow_nan=False))
    reloaded = json.loads(
        path.read_text(),
        parse_constant=lambda c: pytest.fail(f"payload carried the JSON-invalid literal {c!r}"),
    )
    assert reloaded["meta"]["n_accounts_scored"] == payload["meta"]["n_accounts_scored"]


def test_no_nan_hides_anywhere_in_the_payload(payload):
    """Belt and braces: walk the whole tree looking for a non-finite float."""
    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, float):
            assert math.isfinite(node), f"non-finite float at {path}"

    walk(payload)


def test_channel_gated_fields_are_null_not_zero(payload):
    """A portfolio with no credit limit must report `null` utilisation.

    Zero would be a lie the model and the officer both read as "fully unused limit".
    """
    without_limit = [r for r in payload["portfolio"] if "utilisation" not in r["channels_present"]]
    assert without_limit, "expected at least one portfolio with no utilisation channel"
    assert all(r["utilisation"] is None for r in without_limit)

    without_gst = [r for r in payload["portfolio"] if "gst" not in r["channels_present"]]
    assert without_gst
    assert all(r["sales_trend_3m"] is None for r in without_gst)


def test_timelines_carry_nulls_for_absent_channels(payload):
    """The chart must draw a gap, not a line along the x-axis."""
    by_id = {r["account_id"]: r for r in payload["portfolio"]}
    checked = 0
    for account_id, points in payload["timelines"].items():
        record = by_id.get(account_id)
        if record is None or "utilisation" in record["channels_present"]:
            continue
        assert all(p["utilisation"] is None for p in points)
        checked += 1
    assert checked, "expected at least one account with no utilisation channel"


# --------------------------------------------------------------------------- #
# DM-2 — channels_present
# --------------------------------------------------------------------------- #
def test_channels_map_covers_all_eight_portfolios():
    assert set(export_demo.CHANNELS_BY_PORTFOLIO) == {p.code for p in PORTFOLIOS.values()}
    assert len(export_demo.CHANNELS_BY_PORTFOLIO) == 8


def test_channels_present_matches_the_registry_for_every_account(payload):
    """The ruling's second test: every account's channel list is its portfolio's."""
    declared = {p.code: list(p.channels) for p in PORTFOLIOS.values()}
    seen = set()
    for record in payload["portfolio"]:
        assert record["portfolio"] in declared, record["portfolio"]
        assert record["channels_present"] == declared[record["portfolio"]]
        assert set(record["channels_present"]) <= set(ALL_CHANNELS)
        seen.add(record["portfolio"])
    assert seen == set(declared), f"portfolios missing from the snapshot: {set(declared) - seen}"


def test_meta_publishes_the_channel_map(payload):
    assert payload["meta"]["channels"] == list(ALL_CHANNELS)
    assert payload["meta"]["channels_by_portfolio"] == export_demo.CHANNELS_BY_PORTFOLIO


def test_channels_present_falls_back_to_everything_for_an_unknown_portfolio():
    assert export_demo.channels_present("not-a-portfolio") == list(ALL_CHANNELS)


# --------------------------------------------------------------------------- #
# DM-3 — Wilson intervals
# --------------------------------------------------------------------------- #
def test_wilson_brackets_the_point_estimate():
    lo, hi = export_demo.wilson(30, 100)
    assert lo < 0.30 < hi


def test_wilson_stays_inside_the_unit_interval_at_the_edges():
    assert export_demo.wilson(0, 40) == pytest.approx((0.0, 0.0872), abs=1e-3)
    lo, hi = export_demo.wilson(7, 7)
    assert hi == 1.0 and lo > 0.5


def test_wilson_narrows_as_n_grows():
    narrow = export_demo.wilson(300, 1000)
    wide = export_demo.wilson(3, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_wilson_is_defined_for_an_empty_cell():
    assert export_demo.wilson(0, 0) == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# DM-3 — the exhibit and its gate
# --------------------------------------------------------------------------- #
def _book(rows):
    """A tiny frozen book: (bucket, portfolio, pd, months_to_npa) tuples."""
    return pd.DataFrame(
        [dict(bucket=b, portfolio=p, pd=s, snap_months_to_npa=m) for b, p, s, m in rows]
    )


def _ranked_book(portfolio, n=200):
    """A book that ranks the way a healthy model does.

    Green 5% bad, Amber 20%, Red 90%, and the ten deciles never step down — i.e. a
    book that must pass DR-11 and DR-12.  Bads are spread evenly inside each band on
    purpose: a book where every bad sits in the top decile would pass the gate while
    telling us nothing about whether Amber ranks above Green.
    """
    rows = []
    for i in range(n):
        score = i / n
        if score >= 0.9:                       # Red: 18 of every 20
            bucket, went = "red", i % 10 != 9
        elif score >= 0.6:                     # Amber: 1 in 5
            bucket, went = "amber", i % 5 == 0
        else:                                  # Green: 1 in 20
            bucket, went = "green", i % 20 == 0
        rows.append((bucket, portfolio, score, 4 if went else -1))
    return _book(rows)


def test_exhibit_keeps_the_pooled_shape_the_cockpit_already_reads():
    exhibit = export_demo.rank_order_exhibit(_ranked_book("MSME-CC"))
    assert exhibit["horizon_months"] == export_demo.RANK_HORIZON
    assert [b["band"] for b in exhibit["by_band"]] == ["Green", "Amber", "Red"]
    assert [d["decile"] for d in exhibit["by_decile"]] == list(range(1, 11))
    for row in exhibit["by_band"] + exhibit["by_decile"]:
        assert {"n", "defaults", "bad_rate", "ci_lo", "ci_hi"} <= set(row)
        assert row["ci_lo"] <= row["bad_rate"] <= row["ci_hi"]


def test_exhibit_has_one_self_contained_cell_per_portfolio():
    """Each entry must be renderable by the SAME component as the pooled exhibit."""
    book = pd.concat([_ranked_book(p.code) for p in PORTFOLIOS.values()], ignore_index=True)
    exhibit = export_demo.rank_order_exhibit(book)
    assert [c["portfolio"] for c in exhibit["by_portfolio"]] == [p.code for p in PORTFOLIOS.values()]
    for cell in exhibit["by_portfolio"]:
        assert [b["band"] for b in cell["by_band"]] == ["Green", "Amber", "Red"]
        assert len(cell["by_decile"]) == 10
        assert cell["title"].startswith(cell["portfolio"])


def test_exhibit_carries_red_band_precision_with_a_ci_pooled_and_per_portfolio():
    """DM-4's hook — it falls out of the same table, so it is emitted from it."""
    book = pd.concat([_ranked_book(p.code) for p in PORTFOLIOS.values()], ignore_index=True)
    exhibit = export_demo.rank_order_exhibit(book)
    for cell in [exhibit] + exhibit["by_portfolio"]:
        rbp = cell["red_band_precision_8m"]
        red = next(b for b in cell["by_band"] if b["band"] == "Red")
        assert rbp == dict(n=red["n"], hits=red["defaults"], precision=red["bad_rate"],
                           ci_lo=red["ci_lo"], ci_hi=red["ci_hi"])
        assert rbp["ci_lo"] <= rbp["precision"] <= rbp["ci_hi"]


def test_horizon_is_respected():
    """An NPA 20 months out is not an NPA inside an 8-month window."""
    book = _book([("red", "Agri", 0.9, 20)] * 10 + [("green", "Agri", 0.1, -1)] * 90)
    red = next(b for b in export_demo.rank_order_exhibit(book)["by_band"] if b["band"] == "Red")
    assert red["defaults"] == 0


def test_gate_passes_a_book_that_ranks_in_every_portfolio():
    book = pd.concat([_ranked_book(p.code) for p in PORTFOLIOS.values()], ignore_index=True)
    exhibit = export_demo.rank_order_exhibit(book)
    assert export_demo.rank_order_violations(exhibit) == []
    export_demo.assert_rank_order(exhibit)          # must not raise


def test_gate_fails_loudly_when_one_portfolio_does_not_rank(capsys):
    """DR-11 is per portfolio: seven good ones must not carry an eighth bad one."""
    good = [_ranked_book(p.code) for p in list(PORTFOLIOS.values())[:-1]]
    broken_code = list(PORTFOLIOS.values())[-1].code
    # defaults land in Green, nothing in Red -> Green > Red, order inverted
    broken = _book([("green", broken_code, 0.1, 3)] * 40 + [("red", broken_code, 0.95, -1)] * 10)
    exhibit = export_demo.rank_order_exhibit(pd.concat(good + [broken], ignore_index=True))

    violations = export_demo.rank_order_violations(exhibit)
    assert any(v.startswith(f"DR-11 {broken_code}") for v in violations)
    with pytest.raises(AssertionError, match=f"DR-11 {broken_code}"):
        export_demo.assert_rank_order(exhibit)
    # the failure must arrive with the table that caused it
    assert any(broken_code in line for line in export_demo.format_rank_order(exhibit))


def test_gate_rejects_a_tie_between_bands():
    """DR-11 says STRICTLY increasing — an Amber that behaves like Green is a fail."""
    book = _book(
        [("green", "Housing", 0.01, -1)] * 99 + [("green", "Housing", 0.02, 3)]
        + [("amber", "Housing", 0.10, -1)] * 99 + [("amber", "Housing", 0.20, 3)]
        + [("red", "Housing", 0.95, 3)] * 10
    )
    cell = export_demo.rank_order_exhibit(book)["by_portfolio"][0]
    assert cell["by_band"][0]["bad_rate"] == cell["by_band"][1]["bad_rate"]
    assert not cell["bands_monotone"]


def test_decile_step_fraction_counts_non_decreasing_steps():
    book = _ranked_book("Agri")
    exhibit = export_demo.rank_order_exhibit(book)
    assert exhibit["decile_steps"] == 9
    assert exhibit["monotone_decile_steps"] == 9
    assert exhibit["monotone_decile_step_fraction"] == 1.0


def test_gate_reports_a_decile_reversal():
    """A book whose safest decile is its worst fails DR-12, not just DR-11."""
    rows = []
    for i in range(200):
        score = i / 200
        bucket = "red" if score >= 0.9 else "amber" if score >= 0.6 else "green"
        rows.append((bucket, "Auto", score, 3 if i < 20 else -1))     # NPAs in D1
    exhibit = export_demo.rank_order_exhibit(_book(rows))
    assert any(v.startswith("DR-12") for v in export_demo.rank_order_violations(exhibit))


def test_payload_records_the_gate_verdict(payload):
    """An artefact written by a failing run must say so on its face."""
    gate = payload["metrics"]["rank_order"]["gate"]
    assert gate["criteria"] == ["DR-11", "DR-12"]
    assert gate["passed"] is (gate["violations"] == [])


def test_payload_exhibit_covers_every_portfolio_in_the_book(payload):
    exhibit = payload["metrics"]["rank_order"]
    in_book = {r["portfolio"] for r in payload["portfolio"]}
    assert {c["portfolio"] for c in exhibit["by_portfolio"]} == in_book

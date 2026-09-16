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


def test_ci_aware_step_count_forgives_a_reversal_the_data_cannot_see():
    """One account's difference between two big deciles is not a reversal.

    This is the DIAGNOSTIC, not the gate: it must be at least as generous as the
    literal count, and it must forgive a drop whose Wilson intervals overlap.
    """
    overlapping = [dict(bad_rate=0.0077, ci_lo=0.001, ci_hi=0.04),
                   dict(bad_rate=0.0076, ci_lo=0.001, ci_hi=0.04)]
    assert export_demo._decile_steps(overlapping)[0] == 0
    assert export_demo._decile_steps_ci(overlapping)[0] == 1


def test_ci_aware_step_count_still_catches_a_real_reversal():
    separated = [dict(bad_rate=0.50, ci_lo=0.44, ci_hi=0.56),
                 dict(bad_rate=0.02, ci_lo=0.01, ci_hi=0.05)]
    assert export_demo._decile_steps_ci(separated)[0] == 0


def test_ci_aware_count_is_never_stricter_than_the_gated_one():
    book = pd.concat([_ranked_book(p.code) for p in PORTFOLIOS.values()], ignore_index=True)
    exhibit = export_demo.rank_order_exhibit(book)
    for cell in [exhibit] + exhibit["by_portfolio"]:
        assert cell["monotone_decile_steps_ci"] >= cell["monotone_decile_steps"]
        assert cell["monotone_decile_steps_ci"] <= cell["decile_steps"]


def test_the_gate_ignores_the_ci_aware_diagnostic():
    """A cell that fails the literal count must still fail, however forgiving the
    diagnostic is — the pre-registered arithmetic is what gates."""
    rows = []
    for i in range(200):
        score = i / 200
        bucket = "red" if score >= 0.9 else "amber" if score >= 0.6 else "green"
        rows.append((bucket, "Auto", score, 3 if i < 20 else -1))
    exhibit = export_demo.rank_order_exhibit(_book(rows))
    cell = exhibit["by_portfolio"][0]
    assert cell["monotone_decile_step_fraction"] < export_demo.DECILE_STEP_FLOOR
    assert any(v.startswith("DR-12") for v in export_demo.rank_order_violations(exhibit))


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


# --------------------------------------------------------------------------- #
# DM-4 — the honest headline
#
# The mentors rejected a flat accuracy claim. On a book where roughly three
# accounts in a hundred go bad, flagging NOBODY scores in the high nineties, so
# the figure measures the base rate rather than the model. What replaces it is
# the Red band's realised NPA rate at eight months, with its interval, its
# denominator, and the share of NPAs the same operating point still missed.
#
# The tests below check three separable things: the arithmetic, that the prose
# is DERIVED rather than typed, and that the guard refuses the discredited claim
# however it is phrased.
# --------------------------------------------------------------------------- #
def _banded_book():
    """A hand-counted book: 200 accounts, 12 NPAs inside 8 months, 15 inside 12.

    Red 10 (6 bad) · Amber 20 (4 bad) · Green 170 (2 bad inside 8 months, plus 3
    more that only turn inside 12).  Scores descend Red -> Amber -> Green and the
    four bad Ambers carry the highest Amber scores, so the 10% budget catches
    exactly the 10 Red and Amber NPAs.
    """
    rows = []
    for i in range(10):                                  # Red, highest scores
        rows.append(("red", "MSME-CC", 0.90 + i / 1000, 4 if i < 6 else -1))
    for i in range(20):                                  # Amber, bads score highest
        rows.append(("amber", "MSME-CC", 0.50 + (20 - i) / 1000, 4 if i < 4 else -1))
    for i in range(170):                                 # Green
        months = 4 if i < 2 else (10 if i < 5 else -1)
        rows.append(("green", "MSME-CC", 0.01 + i / 100_000, months))
    return _book(rows)


@pytest.fixture(scope="module")
def honest():
    return export_demo.honest_metrics(_banded_book())


def test_ci_helper_is_a_wilson_interval_around_the_point_estimate():
    cell = export_demo._ci(30, 100)
    assert cell["value"] == 0.30
    lo, hi = export_demo.wilson(30, 100)
    assert (cell["ci_lo"], cell["ci_hi"]) == (round(lo, 4), round(hi, 4))
    assert cell["ci_lo"] < cell["value"] < cell["ci_hi"]


def test_ci_helper_is_defined_on_an_empty_cell():
    assert export_demo._ci(0, 0) == dict(value=0.0, ci_lo=0.0, ci_hi=0.0)


def test_red_band_precision_is_the_hand_counted_number(honest):
    cell = honest["red_band_precision_8m"]
    assert (cell["n_red"], cell["n_defaulted"]) == (10, 6)
    assert cell["value"] == 0.6
    assert cell["n_defaulted_in_book"] == 12
    assert cell["horizon_months"] == 8
    assert cell["ci_lo"] < 0.6 < cell["ci_hi"]


def test_raw_accuracy_is_carried_for_contrast_with_its_own_baseline(honest):
    cell = honest["raw_accuracy_8m"]
    assert (cell["n"], cell["n_correct"]) == (200, 190)     # 6 true Red + 184 true non-Red
    assert cell["value"] == 0.95
    assert cell["flag_nobody_baseline"] == 0.94             # 188 of 200, flagging nothing
    assert cell["value"] - cell["flag_nobody_baseline"] < 0.02, (
        "the whole point: the model beats 'flag nobody' by almost nothing on this measure")


def test_the_two_base_rates_use_the_two_horizons(honest):
    assert honest["base_rate_8m"]["value"] == 0.06          # 12 of 200
    assert honest["base_rate_12m"]["value"] == 0.075        # 15 of 200
    assert honest["base_rate_8m"]["horizon_months"] == 8
    assert honest["base_rate_12m"]["horizon_months"] == 12


def test_recall_at_a_tenth_of_the_book_is_counted_over_defaulters(honest):
    cell = honest["recall_at_10pct_budget"]
    assert (cell["n_reviewed"], cell["n_defaulted"], cell["n_caught"]) == (20, 12, 10)
    assert cell["value"] == pytest.approx(10 / 12, abs=1e-4)
    assert cell["ci_lo"] < cell["value"] < cell["ci_hi"]


def test_missed_npa_share_counts_defaulters_left_in_green(honest):
    cell = honest["missed_npa_share"]
    assert (cell["n_defaulted"], cell["n_missed"]) == (12, 2)
    assert cell["value"] == pytest.approx(2 / 12, abs=1e-4)


def test_flagged_share_is_published_beside_the_lead_times(honest):
    """A long median lead means little if most of the book is flagged."""
    assert honest["flagged_share"]["n_flagged"] == 30
    assert honest["flagged_share"]["value"] == 0.15


def test_every_honest_metric_carries_an_interval_and_a_definition(honest):
    for key in ("red_band_precision_8m", "raw_accuracy_8m", "base_rate_8m", "base_rate_12m",
                "recall_at_10pct_budget", "missed_npa_share", "flagged_share"):
        cell = honest[key]
        assert {"value", "ci_lo", "ci_hi", "definition"} <= set(cell), key
        assert cell["ci_lo"] <= cell["value"] <= cell["ci_hi"], key


def test_red_band_precision_is_repeated_for_every_portfolio_in_the_book():
    book = pd.concat([_ranked_book(p.code) for p in PORTFOLIOS.values()], ignore_index=True)
    cell = export_demo.honest_metrics(book)["red_band_precision_8m"]
    assert [c["portfolio"] for c in cell["by_portfolio"]] == [p.code for p in PORTFOLIOS.values()]
    for entry in cell["by_portfolio"]:
        assert {"value", "ci_lo", "ci_hi", "n_red", "n_defaulted"} <= set(entry)
        assert entry["ci_lo"] <= entry["value"] <= entry["ci_hi"]


# --------------------------------------------------------------------------- #
# DM-4 — the honesty block, and the guard on it
# --------------------------------------------------------------------------- #
def test_the_headline_is_formatted_from_the_measured_number(honest):
    headline = honest["honesty"]["headline"]
    assert headline.startswith("60.0% of Red-flagged accounts went NPA within 8 months")
    assert "n=10" in headline
    assert f"{honest['red_band_precision_8m']['ci_lo']:.1%}" in headline


def test_the_why_is_formatted_from_the_measured_numbers(honest):
    why = honest["honesty"]["why"]
    assert "6.0%" in why and "94.0%" in why      # base rate, and the flag-nobody score
    assert "16.7%" in why                        # the NPAs this operating point missed


def test_the_block_names_what_it_does_not_claim(honest):
    assert honest["honesty"]["not_claimed"] == "accuracy"
    assert export_demo.honesty_violations(honest) == []
    export_demo.assert_honesty(honest)           # must not raise


def test_a_hard_coded_headline_fails_the_guard(honest):
    """A sentence whose number was typed rather than measured is a claim."""
    faked = dict(honest, honesty=dict(honest["honesty"], headline="91.2% of Red-flagged accounts"))
    problems = export_demo.honesty_violations(faked)
    assert any("not carry red_band_precision_8m" in p for p in problems)
    with pytest.raises(AssertionError, match="headline"):
        export_demo.assert_honesty(faked)


def test_the_discredited_figure_is_refused_wherever_it_hides(honest):
    buried = dict(honest, rank_order=dict(note="90% accuracy on held-out accounts"))
    problems = export_demo.honesty_violations(buried)
    assert any("90%" in p for p in problems)
    with pytest.raises(AssertionError, match="90%"):
        export_demo.assert_honesty(buried)


def test_the_word_is_refused_outside_the_paths_that_disown_it(honest):
    claimed = dict(honest, summary="the model reaches 0.95 accuracy on the held-out book")
    problems = export_demo.honesty_violations(claimed)
    assert any("$.summary" in p for p in problems)


def test_using_the_word_without_disowning_it_fails_even_where_it_is_allowed(honest):
    weakened = dict(honest, raw_accuracy_8m=dict(
        honest["raw_accuracy_8m"], definition="the accuracy of the model"))
    problems = export_demo.honesty_violations(weakened)
    assert any("without disowning it" in p for p in problems)


def test_not_claimed_may_name_the_word_and_nothing_else(honest):
    padded = dict(honest, honesty=dict(honest["honesty"],
                                       not_claimed="accuracy, which is actually quite good"))
    assert export_demo.honesty_violations(padded)


def test_a_cross_reference_must_name_a_metric_that_exists(honest):
    """`derived_from` is exempt only while it points at something real."""
    dangling = dict(honest, honesty=dict(honest["honesty"],
                                         derived_from=["accuracy_is_high_actually"]))
    assert any("cross-reference" in p for p in export_demo.honesty_violations(dangling))


def test_the_payloads_metrics_pass_the_guard(payload):
    """The real pipeline's own output, not a hand-built block."""
    export_demo.assert_honesty(payload["metrics"])
    assert payload["metrics"]["honesty"]["not_claimed"] == "accuracy"


def test_the_headline_and_the_rank_order_exhibit_cannot_disagree(payload):
    """Two code paths compute Red-band precision; they must be the same number."""
    metrics = payload["metrics"]
    assert (metrics["red_band_precision_8m"]["value"]
            == metrics["rank_order"]["red_band_precision_8m"]["precision"])
    assert (metrics["red_band_precision_8m"]["n_red"]
            == metrics["rank_order"]["red_band_precision_8m"]["n"])


# --------------------------------------------------------------------------- #
# DM-5 — the operating point, as the export applies it
# --------------------------------------------------------------------------- #
def test_the_payload_carries_the_cost_derivation(payload):
    block = payload["thresholds"]
    assert block["method"] == "cost_minimising"
    assert block["horizon_months"] == export_demo.RANK_HORIZON
    assert block["current"]["amber"] == export_demo.LEGACY_AMBER_THR
    assert block["current"]["red"] == export_demo.LEGACY_RED_THR
    assert block["cost_params"] and block["provenance"]
    assert block["provenance"]["effective_rate_pa"]["sandbox_fixture"] is True


def test_the_bands_in_the_book_are_the_thresholds_that_were_costed(payload):
    """Whatever the search picked has to be what the accounts were banded on."""
    amber, red = payload["thresholds"]["amber"], payload["thresholds"]["red"]
    assert payload["portfolio_summary"]["amber_thr"] == amber
    assert payload["portfolio_summary"]["red_thr"] == red
    for record in payload["portfolio"]:
        expected = "red" if record["pd"] >= red else "amber" if record["pd"] >= amber else "green"
        # `pd` is the banding score rounded for the wire, so only an account sitting
        # exactly on a threshold could differ; none may differ by a whole band.
        assert record["bucket"] == expected or abs(record["pd"] - amber) < 1e-4 \
            or abs(record["pd"] - red) < 1e-4


def test_the_july_thresholds_can_still_be_pinned():
    """The escape hatch: emit the cost evidence without moving the operating point."""
    panel, accounts = generate(GeneratorConfig(n_accounts=400, months=EXPORT_MONTHS))
    panel = panel.assign(account_id=panel.account_id.astype(str))
    static = accounts.assign(account_id=accounts.account_id.astype(str)).set_index("account_id")
    out = export_demo.build_export(panel, static, keep_legacy=True)
    assert out["thresholds"]["applied"] == "legacy"
    assert out["thresholds"]["amber"] == export_demo.LEGACY_AMBER_THR
    assert out["thresholds"]["red"] == export_demo.LEGACY_RED_THR
    assert out["thresholds"]["chosen"], "the cost evidence is still emitted"


def test_exposure_at_default_reaches_the_cockpit(payload):
    assert any(record["outstanding"] for record in payload["portfolio"])

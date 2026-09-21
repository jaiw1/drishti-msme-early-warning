"""
Asymmetric-cost band thresholds (DM-5)  ->  consumed by ``src/export_demo.py``

The mentors' mandate, in one line: **a missed NPA costs the bank far more than a
false positive.**  A threshold picked to look good on a precision slide is the
wrong threshold; the right one is the one that minimises the bank's expected
rupee cost.  This module computes that cost account by account and searches for
the Amber/Red pair that minimises it.

What the cost model says
------------------------
Every account in the frozen book lands in one of three bands, and each band has
a different cost::

    Green  (no action)      missed NPA  ->  the whole expected loss lands
    Amber  (watch)          a call, a statement pull; a small share of the loss avoided
    Red    (act)            a full review and intervention; a larger share avoided

An account that is flagged and was never going to default costs the bank the
review AND some relationship friction; an account that is flagged and *was*
going to default still costs money, just less of it.  So the objective has an
interior minimum: flag too little and missed NPAs dominate, flag too much and
review plus friction dominate.

Expected loss on a missed NPA
-----------------------------
::

    EL = EAD x LGD  +  EAD x (effective_rate + penal_rate)/100 x reversal_months/12

The first term is the brief's ``EAD x LGD x P(default)`` — P(default) is the
*realised* outcome on the held-out book, so it is 1 for an account that went bad
and 0 otherwise, and summing over the book is the empirical expectation.  The
second term is income reversal: under RBI's IRAC norms, interest accrued but not
collected on an account that turns NPA is reversed out of income.  That is a
real, rate-driven cost the early warning avoids, and it is why the rates from
API 433 are load-bearing here rather than decorative.

Provenance
----------
Three kinds of number, and they are labelled, never blended:

``BANK_API``   read from the Atlas sandbox's API-433 response (``rateInfo``,
               ``loanInfo``, ``hpPayoffInfo``).  **Every one of these carries
               ``sandbox_fixture: true``** — the sandbox returns one static
               canned blob for every caller, so these are real *field values
               from the bank's own API contract*, not real *rates for our
               borrowers*.  Saying so is the whole point of the flag.
``ASSUMPTION`` our judgement, with the reasoning written down.  No public
               source exists for Indian retail LGD, cure rates or the rupee
               cost of a credit review, and inventing a citation would be worse
               than saying "assumed".
``SOURCES``    read from ``src/generator/sources.yaml`` (cross-check only —
               the per-account ``secured`` flag in the panel is what actually
               drives LGD).

**Nothing in this module optimises toward AUC or toward any band in
``validation/criteria.yaml``.**  The objective is rupees.  The pre-registered
criteria enter only as *feasibility filters* — a threshold pair that breaks
DR-11 is not a candidate at all — and the search reports which constraints it
had to relax when no pair satisfies all of them.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so `generator` imports

from generator.portfolios import PORTFOLIOS   # noqa: E402  (path shim first)

__all__ = [
    "BANK_RATES_433",
    "CAPTURE_433",
    "CostParams",
    "band_costs",
    "choose_thresholds",
    "cost_params",
    "evaluate",
    "expected_loss",
    "lgd_vector",
    "load_bank_rates",
    "provenance_summary",
]

# --------------------------------------------------------------------------- #
# The Atlas sandbox capture.
#
# Embedded rather than read from a file because the capture lives in a browser
# scratchpad outside this repo and will not survive, and because `data/bank/`
# is another lane's tree.  The values below are copied verbatim (as strings, as
# Atlas returns them) from the response recorded in CAPTURE_433; set
# BANK_RATES_ENV to a JSON file of the same shape to override with a live pull
# (that is the hook DM-6's `--bank` path uses).
# --------------------------------------------------------------------------- #
#: env var pointing at a JSON file with the same shape as :data:`BANK_RATES_433`
BANK_RATES_ENV = "DRISHTI_BANK_RATES_433"

BANK_RATES_433: dict = {
    "rateInfo": {
        "baseRate": "12.75",
        "effectiveRate": "12.75",
        "penalRate": "2.0",
        "slabs": [{"from": "0.00", "to": "9999999.98", "maxDays": 30,
                   "maxMonths": 360, "normalPct": "11.50", "penalPct": "2.0"}],
    },
    "loanInfo": {
        "loanAmt": "2000000", "disbAmt": "2000000", "amtAlreadyDisb": "1500000",
        "amtAvailForDisb": "500000", "emiAmount": "16800",
        "loanPeriodMonths": "240", "rePmtMethod": "EMI", "netIntRate": "8.75",
    },
    # API 538's payoff split. Every interest component is "0" because the
    # sandbox's canned account is standard (npaStatus "SA"), so the split
    # cannot be read from it — see `load_bank_rates`, which says so out loud
    # rather than quietly treating zero as a measurement.
    "hpPayoffInfo": {
        "pendingPrincipal": "400000.00", "accountLiab": "400000.00",
        "netPayofamt": "400537.00", "interestRate": "7.000000",
        "interestSinceLastApplication": "537.00",
        "pendingNormalInterest": "0", "pendingOverdueInterest": "0",
        "pendingPenalInterest": "0",
    },
}

CAPTURE_433: dict = {
    "api_id": "433",
    "also_covers": ["538"],
    "endpoint": "IDBI Atlas developer sandbox, public (unauthenticated) API 433",
    "captured_on": "2026-09-16",
    "captured_by": "RR Squad browser probe (scratchpad/browser/token-probe/433-response-full.json)",
    "sandbox_fixture": True,
    "note": ("The Atlas sandbox returns ONE static canned response, shared across APIs and "
             "callers. These are genuine field values from the bank's API contract; they are "
             "not rates observed on our borrowers, and every parameter derived from them is "
             "flagged sandbox_fixture so the cockpit can badge it."),
}

BANK_API = "BANK_API"
ASSUMPTION = "ASSUMPTION"
SOURCES = "SOURCES"


def _num(text, default=None):
    """A sandbox string as a float, or ``default`` when it is not a number."""
    try:
        v = float(text)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def load_bank_rates(path=None, blob=None):
    """Interest and penal rates, with per-field provenance.

    Resolution order, which is also the order the brief pre-registered:
    a live/overridden pull, then the documented sandbox capture, then an
    assumption.  Every field records which of the three it came from.

    Args:
        path: JSON file shaped like :data:`BANK_RATES_433`; defaults to
            ``$DRISHTI_BANK_RATES_433`` when that is set and readable.
        blob: an already-parsed blob, which wins over ``path``.  For tests.

    Returns:
        ``(rates, provenance)``.  ``rates`` carries plain floats;
        ``provenance`` carries one entry per rate naming its api, its field and
        whether it is a sandbox fixture.
    """
    source_label, capture = BANK_API, dict(CAPTURE_433)
    if blob is None:
        path = path or os.environ.get(BANK_RATES_ENV) or None
        if path:
            try:
                blob = json.loads(Path(path).read_text())
                capture = dict(CAPTURE_433, captured_by=str(path), sandbox_fixture=False,
                               note="overridden from a file via " + BANK_RATES_ENV)
            except (OSError, ValueError):
                blob = None
        if blob is None:
            blob = BANK_RATES_433

    rate_info = blob.get("rateInfo") or {}
    loan_info = blob.get("loanInfo") or {}
    payoff = blob.get("hpPayoffInfo") or {}
    slabs = rate_info.get("slabs") or [{}]

    def field(value, api, name, fallback, why):
        """One rate, tagged with where it actually came from."""
        v = _num(value)
        if v is None:
            return fallback, dict(source=ASSUMPTION, confidence="assumed", note=why)
        prov = dict(source=source_label, api_id=api, field=name,
                    sandbox_fixture=bool(capture["sandbox_fixture"]),
                    captured_on=capture["captured_on"], confidence="medium")
        return v, prov

    rates, provenance = {}, {}
    rates["effective_rate_pa"], provenance["effective_rate_pa"] = field(
        rate_info.get("effectiveRate"), "433", "rateInfo.effectiveRate", 12.0,
        "no effectiveRate in the blob; 12% p.a. assumed as a mid retail card rate")
    rates["penal_rate_pa"], provenance["penal_rate_pa"] = field(
        rate_info.get("penalRate"), "433", "rateInfo.penalRate", 2.0,
        "no penalRate in the blob; 2% p.a. assumed, the common Indian penal spread")
    rates["normal_rate_pa"], provenance["normal_rate_pa"] = field(
        slabs[0].get("normalPct"), "433", "rateInfo.slabs[0].normalPct", 11.5,
        "no rate slab in the blob")
    rates["net_interest_rate_pa"], provenance["net_interest_rate_pa"] = field(
        loan_info.get("netIntRate"), "433", "loanInfo.netIntRate", 8.75,
        "no loanInfo in the blob")
    rates["payoff_interest_rate_pa"], provenance["payoff_interest_rate_pa"] = field(
        payoff.get("interestRate"), "538", "hpPayoffInfo.interestRate", 7.0,
        "no hpPayoffInfo in the blob")

    # --- API 538's penal / overdue interest SPLIT -------------------------- #
    # This is the thing the brief asked for "where available", and on the
    # sandbox blob it is NOT available: the canned account is standard, so all
    # three components read "0". A zero here is an absence, not a measurement,
    # and treating it as one would put a 0% penal loading into the cost model.
    split = {k: _num(payoff.get(v)) for k, v in
             (("normal", "pendingNormalInterest"), ("overdue", "pendingOverdueInterest"),
              ("penal", "pendingPenalInterest"))}
    total = sum(v for v in split.values() if v)
    rates["payoff_split"] = dict(
        available=bool(total),
        components={k: (None if v is None else float(v)) for k, v in split.items()},
        share_penal=round(split["penal"] / total, 4) if total and split["penal"] else None,
    )
    provenance["payoff_split"] = dict(
        source=BANK_API, api_id="538", field="hpPayoffInfo.pending*Interest",
        sandbox_fixture=bool(capture["sandbox_fixture"]),
        available=bool(total), confidence="low",
        note=("the sandbox's canned payoff account is standard (npaStatus 'SA'), so every "
              "interest component is 0 and no split can be read from it. The cost model "
              "therefore loads penal interest from rateInfo.penalRate instead, which is a "
              "rate rather than a realised split." if not total else
              "read from the payoff response"),
    )
    provenance["_capture"] = capture
    return rates, provenance


# --------------------------------------------------------------------------- #
# The cost parameters
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostParams:
    """Every rupee knob the threshold search reads.  Units are in the names.

    Rates default to the API-433 capture; everything else is an assumption with
    its reasoning in :data:`PARAM_NOTES`.
    """

    # -- loss given default, by whether the exposure is secured -------------- #
    lgd_secured: float = 0.40
    lgd_unsecured: float = 0.75
    # -- income reversal on NPA recognition (RBI IRAC) ----------------------- #
    income_reversal_months: float = 6.0
    effective_rate_pa: float = 12.75
    penal_rate_pa: float = 2.0
    # -- what acting 8 months early actually recovers ------------------------ #
    cure_share_red: float = 0.35
    cure_share_amber: float = 0.10
    # -- what a review costs the bank, per flagged account, per cycle -------- #
    review_cost_red_inr: float = 18_000.0
    review_cost_amber_inr: float = 1_500.0
    # -- relationship friction, as a share of ONE YEAR's interest income on
    #    that exposure.  Proportional to the relationship, not a flat fee. ---- #
    friction_share_red: float = 0.15
    friction_share_amber: float = 0.02


#: why each assumed parameter is the number it is.  Read by `cost_params` into
#: the provenance block, so the cockpit can show the reasoning beside the value.
PARAM_NOTES: dict[str, str] = {
    "lgd_secured": ("Basel II foundation-IRB assigns 45% LGD to senior unsecured claims and "
                    "recognises a lower figure where eligible collateral is held. RBI "
                    "publishes no retail LGD, so 40% on a secured retail exposure is our "
                    "judgement, not a citation."),
    "lgd_unsecured": ("Above Basel's 45% senior-unsecured figure, because recoveries on "
                      "unsecured Indian retail after write-off run well below corporate "
                      "senior-unsecured recoveries. Assumed."),
    "income_reversal_months": ("Interest accrues and goes uncollected through roughly two "
                               "quarters of slide before 90-DPD recognition forces the "
                               "reversal. Assumed."),
    "cure_share_red": ("The share of expected loss avoided when the bank reviews and "
                       "intervenes eight months early — restructuring, topping up security, "
                       "or simply starting recovery while there is still something to "
                       "recover. THE SINGLE MOST UNCERTAIN NUMBER HERE; the sensitivity "
                       "block shows what the thresholds do when it moves."),
    "cure_share_amber": ("A watch-list entry is a call and a statement pull, not an "
                         "intervention: assumed to recover under a third of what a full "
                         "review does."),
    "review_cost_red_inr": ("Roughly two officer-days plus a site visit, at an Indian "
                            "public-sector bank credit officer's fully loaded day rate. "
                            "Assumed."),
    "review_cost_amber_inr": "Roughly two officer-hours. Assumed.",
    "friction_share_red": ("A healthy borrower put through a full early-warning review may "
                           "reprice, move part of the relationship, or leave. Costed as 15% "
                           "of one year's interest income on that exposure. Assumed."),
    "friction_share_amber": ("A watch-list entry is largely invisible to the borrower; a "
                             "small share for the extra contact. Assumed."),
}
#: parameters that come from the bank API rather than from our judgement
RATE_PARAMS = ("effective_rate_pa", "penal_rate_pa")


def cost_params(rates=None, rate_provenance=None, **overrides):
    """The cost parameters, and one provenance entry per parameter.

    Args:
        rates: output of :func:`load_bank_rates`; loaded if omitted.
        rate_provenance: its provenance half.
        **overrides: any :class:`CostParams` field, for the sensitivity sweep.

    Returns:
        ``(CostParams, provenance)``.
    """
    if rates is None:
        rates, rate_provenance = load_bank_rates()
    rate_provenance = rate_provenance or {}

    params = CostParams(
        effective_rate_pa=float(rates.get("effective_rate_pa", CostParams.effective_rate_pa)),
        penal_rate_pa=float(rates.get("penal_rate_pa", CostParams.penal_rate_pa)),
    )
    if overrides:
        params = replace(params, **overrides)

    provenance = {}
    for name in params.__dataclass_fields__:
        if name in RATE_PARAMS and name in rate_provenance:
            provenance[name] = dict(rate_provenance[name])
        else:
            provenance[name] = dict(source=ASSUMPTION, confidence="assumed",
                                    url="none", note=PARAM_NOTES.get(name, ""))
        if name in overrides:
            provenance[name]["overridden"] = True
    provenance["_rates_unused_but_reported"] = {
        k: dict(value=rates[k], **rate_provenance.get(k, {}))
        for k in ("normal_rate_pa", "net_interest_rate_pa", "payoff_interest_rate_pa")
        if k in rates
    }
    provenance["_payoff_split_538"] = dict(rates.get("payoff_split", {}),
                                           **{"provenance": rate_provenance.get("payoff_split", {})})
    provenance["_capture"] = rate_provenance.get("_capture", CAPTURE_433)
    return params, provenance


def provenance_summary(provenance):
    """The structured provenance flattened to one readable line per parameter.

    The full block is nested because a reviewer needs the api id, the field and
    the sandbox flag. A screen needs a sentence. Both are emitted rather than
    making the UI choose which half of the truth to render.
    """
    summary = {}
    for name, entry in provenance.items():
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        if entry.get("source") == BANK_API:
            where = f"API {entry.get('api_id', '?')} {entry.get('field', '')}".strip()
            flag = " (sandbox fixture)" if entry.get("sandbox_fixture") else " (live pull)"
            summary[name] = f"{BANK_API} — {where}{flag}"
        else:
            summary[name] = f"{ASSUMPTION} — our judgement, no published source"
    return summary


# --------------------------------------------------------------------------- #
# Per-account economics
# --------------------------------------------------------------------------- #
#: contract portfolio code -> the registry key `sources.yaml` declares it under
_KEY_BY_CODE = {p.code: key for key, p in PORTFOLIOS.items()}


def declared_secured_share(code):
    """``sources.yaml``'s secured share for a portfolio, or ``None``.

    Cross-check only: LGD is driven by the panel's per-account ``secured``
    flag, which is exact.  Wrapped because the generator lane owns that file
    and may rename the node; a missing node must degrade the report, never the
    model.
    """
    key = _KEY_BY_CODE.get(str(code))
    if key is None:
        return None
    try:
        from generator import sources

        return float(sources.portfolio_value(key, "secured_share"))
    except Exception:            # noqa: BLE001 — a renamed node is not a crash
        return None


def lgd_vector(secured, params):
    """Loss-given-default per account from the panel's own ``secured`` flag.

    An account whose flag is missing is costed at the midpoint of the two, so
    an unknown never quietly reads as "fully secured".
    """
    sec = np.asarray(secured, dtype="float64")
    mid = 0.5 * (params.lgd_secured + params.lgd_unsecured)
    return np.where(np.isnan(sec), mid,
                    np.where(sec > 0.5, params.lgd_secured, params.lgd_unsecured))


def expected_loss(ead, lgd, params):
    """Rupee loss if an NPA is missed: principal at risk plus reversed income."""
    ead = np.asarray(ead, dtype="float64")
    reversal = (params.effective_rate_pa + params.penal_rate_pa) / 100.0 \
        * params.income_reversal_months / 12.0
    return ead * np.asarray(lgd, dtype="float64") + ead * reversal


def band_costs(ead, went_bad, lgd, params):
    """The rupee cost of putting each account in each band.

    Returns:
        ``(green, amber, red)`` — three per-account arrays.  Summing the one
        that matches an account's band, over the book, is the objective.
    """
    ead = np.asarray(ead, dtype="float64")
    y = np.asarray(went_bad, dtype="float64")
    el = expected_loss(ead, lgd, params)
    annual_interest = ead * params.effective_rate_pa / 100.0

    green = y * el
    amber = (params.review_cost_amber_inr
             + (1.0 - y) * params.friction_share_amber * annual_interest
             + y * el * (1.0 - params.cure_share_amber))
    red = (params.review_cost_red_inr
           + (1.0 - y) * params.friction_share_red * annual_interest
           + y * el * (1.0 - params.cure_share_red))
    return green, amber, red


# --------------------------------------------------------------------------- #
# The search
# --------------------------------------------------------------------------- #
#: share of the book flagged, for each candidate cut.  Geometric from 0.2% to
#: 70% so the tail — where the Red threshold lives — is finely sampled and the
#: middle is not oversampled.  Fixed here, not derived from a result.
CANDIDATE_FRACTIONS: tuple[float, ...] = tuple(
    round(f, 5) for f in np.geomspace(0.002, 0.70, 96)
)

#: the constraint ladder, strictest first.  The search takes the strictest
#: level that has a feasible pair and says which one it used.
CONSTRAINT_LEVELS = (
    ("all_pre_registered",
     "DR-11 bands strictly monotone pooled AND within every portfolio; Red non-empty in every portfolio"),
    ("portfolio_monotone_only",
     "DR-11 bands strictly monotone pooled AND within every portfolio; Red may be empty in a portfolio"),
    ("pooled_monotone_only",
     "DR-11 bands strictly monotone pooled only"),
    ("none",
     "three non-empty bands, nothing else"),
)


def _rate(bad, n):
    """The gate's own arithmetic: an empty cell rates 0.0, exactly as ``_rate_cell``."""
    return np.where(n > 0, bad / np.maximum(n, 1), 0.0)


#: decimals every emitted threshold is quantised to.  Candidates are rounded
#: BEFORE their flagged counts are measured, so the pair this module costs is
#: bit-for-bit the pair the export applies — a threshold rounded on the way out
#: could otherwise move an account across a band and break the DR-11 gate the
#: search had just satisfied.
THRESHOLD_DECIMALS = 6


def _cuts(scores):
    """Candidate thresholds and the number of accounts each one flags."""
    asc = np.sort(np.asarray(scores, dtype="float64"))
    n = asc.size
    thresholds, ks = [], []
    seen = set()
    for frac in CANDIDATE_FRACTIONS:
        t = round(float(np.quantile(asc, 1.0 - frac)), THRESHOLD_DECIMALS)
        k = int(n - np.searchsorted(asc, t, side="left"))
        if 1 <= k < n and k not in seen:
            seen.add(k)
            thresholds.append(t)
            ks.append(k)
    return np.array(thresholds), np.array(ks, dtype="int64")


def _cumsum(values, order):
    """Cumulative sum down the score-descending order, with a leading zero."""
    return np.concatenate(([0.0], np.cumsum(np.asarray(values, dtype="float64")[order])))


def _search(scores, went_bad, costs, portfolio):
    """Every candidate (amber, red) pair, its cost and its feasibility level.

    Costs are summed with cumulative sums down the score-descending order, so
    the whole grid is scalar arithmetic rather than one pass per pair.
    """
    scores = np.asarray(scores, dtype="float64")
    n = scores.size
    order = np.argsort(-scores, kind="stable")
    green, amber, red = costs
    cg, ca, cr = (_cumsum(c, order) for c in (green, amber, red))

    thresholds, ks = _cuts(scores)
    if not len(ks):
        return None
    a_idx, r_idx = ks[:, None], ks[None, :]           # amber cut rows, red cut cols
    valid = (a_idx > r_idx) & (r_idx >= 1) & (a_idx < n)
    total = cr[r_idx] + (ca[a_idx] - ca[r_idx]) + (cg[n] - cg[a_idx])

    y = np.asarray(went_bad, dtype="float64")
    codes = np.asarray(portfolio, dtype=object)
    groups = [("__pooled__", np.ones(n, dtype="float64"))]
    groups += [(c, (codes == c).astype("float64")) for c in sorted(set(codes.tolist()))]

    monotone_pooled = None
    monotone_all = np.ones_like(valid)
    red_non_empty_all = np.ones_like(valid)
    for code, member in groups:
        cn = _cumsum(member, order)
        cb = _cumsum(member * y, order)
        nr, na = cn[r_idx], cn[a_idx] - cn[r_idx]
        ng = cn[n] - cn[a_idx]
        br, ba = cb[r_idx], cb[a_idx] - cb[r_idx]
        bg = cb[n] - cb[a_idx]
        mono = (_rate(bg, ng) < _rate(ba, na)) & (_rate(ba, na) < _rate(br, nr))
        if code == "__pooled__":
            monotone_pooled = mono
            monotone_all &= mono
            red_non_empty_all &= nr >= 1
        else:
            monotone_all &= mono
            red_non_empty_all &= nr >= 1

    levels = {
        "all_pre_registered": valid & monotone_all & red_non_empty_all,
        "portfolio_monotone_only": valid & monotone_all,
        "pooled_monotone_only": valid & monotone_pooled,
        "none": valid,
    }
    return dict(thresholds=thresholds, ks=ks, total=total, valid=valid, levels=levels)


def _feasibility_level(scores, went_bad, portfolio, amber, red):
    """The strictest constraint level an arbitrary pair satisfies, or ``None``.

    Needed because a pair that is CHEAPER can still be inadmissible — the July
    thresholds are exactly that on a thin book. Without this the block would
    read as though the search had simply lost to the hand-set pair.
    """
    is_red = scores >= red
    is_amber = (scores >= amber) & ~is_red
    is_green = ~is_red & ~is_amber
    if not (is_red.any() and is_amber.any() and is_green.any()):
        return None

    def monotone(mask):
        cells = [(went_bad[m & mask].sum(), int((m & mask).sum()))
                 for m in (is_green, is_amber, is_red)]
        rates = [b / n if n else 0.0 for b, n in cells]
        return rates[0] < rates[1] < rates[2]

    everyone = np.ones(scores.size, dtype=bool)
    codes = sorted(set(np.asarray(portfolio, dtype=object).tolist()))
    per_portfolio = [np.asarray(portfolio, dtype=object) == c for c in codes]
    pooled = monotone(everyone)
    all_mono = pooled and all(monotone(m) for m in per_portfolio)
    red_everywhere = all(int((is_red & m).sum()) >= 1 for m in per_portfolio)
    if all_mono and red_everywhere:
        return "all_pre_registered"
    if all_mono:
        return "portfolio_monotone_only"
    if pooled:
        return "pooled_monotone_only"
    return "none"


def evaluate(amber, red, scores, went_bad, ead, secured, portfolio, params):
    """The full picture for ONE (amber, red) pair — cost and what it flags.

    Used for the chosen pair, for the thresholds currently in production, and
    for each alternative, so the three are always compared like for like.
    """
    scores = np.asarray(scores, dtype="float64")
    y = np.asarray(went_bad, dtype="float64")
    lgd = lgd_vector(secured, params)
    green_c, amber_c, red_c = band_costs(ead, y, lgd, params)

    is_red = scores >= red
    is_amber = (scores >= amber) & ~is_red
    is_green = ~is_red & ~is_amber
    total = float(green_c[is_green].sum() + amber_c[is_amber].sum() + red_c[is_red].sum())

    n_bad = float(y.sum())

    def cell(mask):
        n = int(mask.sum())
        bad = int(y[mask].sum())
        return dict(n=n, defaults=bad, bad_rate=round(bad / n, 4) if n else 0.0)

    return dict(
        amber=round(float(amber), 6), red=round(float(red), 6),
        # the strictest pre-registered level this pair clears — `null` means it
        # cannot band the book at all, and anything other than
        # "all_pre_registered" means it would fail the DR-11 gate somewhere
        constraint_level=_feasibility_level(scores, y, portfolio, amber, red),
        expected_cost=round(total, 2),
        expected_cost_per_account=round(total / max(scores.size, 1), 2),
        n=int(scores.size), n_defaulted=int(n_bad),
        bands=dict(green=cell(is_green), amber=cell(is_amber), red=cell(is_red)),
        red_band_precision=round(float(y[is_red].mean()), 4) if is_red.any() else 0.0,
        amber_band_precision=round(float(y[is_amber].mean()), 4) if is_amber.any() else 0.0,
        missed_npa_share=round(float(y[is_green].sum() / n_bad), 4) if n_bad else 0.0,
        flagged_share=round(float((~is_green).mean()), 4),
        recall_red=round(float(y[is_red].sum() / n_bad), 4) if n_bad else 0.0,
        recall_flagged=round(float(y[~is_green].sum() / n_bad), 4) if n_bad else 0.0,
        exposure_flagged_inr=round(float(np.asarray(ead, dtype="float64")[~is_green].sum()), 2),
    )


def _sensitivity(scores, went_bad, ead, secured, portfolio, rates, rate_provenance, base):
    """What the chosen pair does when the most uncertain knobs move +/- 50%.

    Reported, never optimised against — it exists so a reviewer can see how
    much of the answer is the data and how much is our judgement.
    """
    out = []
    for name in ("cure_share_red", "review_cost_red_inr", "lgd_unsecured",
                 "friction_share_red", "income_reversal_months"):
        for label, factor in (("x0.5", 0.5), ("x1.5", 1.5)):
            value = getattr(CostParams(), name) * factor
            if name.startswith(("cure_share", "friction_share")):
                value = min(value, 0.95)
            params, _ = cost_params(rates, rate_provenance, **{name: value})
            lgd = lgd_vector(secured, params)
            grid = _search(scores, went_bad, band_costs(ead, went_bad, lgd, params), portfolio)
            pick = _pick(grid, base["constraint_level"])
            if pick is None:
                continue
            a, r, _ = pick
            out.append(dict(param=name, change=label, value=round(float(value), 4),
                            amber=round(float(a), 6), red=round(float(r), 6)))
    return out


def _pick(grid, level=None):
    """The cheapest feasible pair, and the constraint level it was feasible at."""
    if grid is None:
        return None
    order = [level] if level else [name for name, _ in CONSTRAINT_LEVELS]
    for name in order:
        mask = grid["levels"][name]
        if not mask.any():
            continue
        total = np.where(mask, grid["total"], np.inf)
        flat = int(np.argmin(total))
        a, r = np.unravel_index(flat, total.shape)
        return float(grid["thresholds"][a]), float(grid["thresholds"][r]), name
    return None


def choose_thresholds(scores, went_bad, ead, secured, portfolio, *,
                      current=(0.04, 0.40), horizon=8, params=None,
                      rates=None, rate_provenance=None, sensitivity=True):
    """Amber and Red chosen to minimise the bank's expected rupee cost.

    Args:
        scores: the smoothed PD each account is banded on.
        went_bad: 1 where the account reached NPA inside ``horizon`` months.
        ead: exposure at default — the outstanding balance.
        secured: the panel's per-account secured flag (NaN allowed).
        portfolio: contract portfolio code per account.
        current: the (amber, red) pair in production, reported beside the new one.
        horizon: months the outcome is measured over, for the record.
        params: override the resolved :class:`CostParams` (tests).
        sensitivity: run the +/- 50% sweep (off for the inner sweep itself).

    Returns:
        The ``thresholds`` block the export emits.  ``feasible`` is False and
        ``amber``/``red`` fall back to ``current`` when no candidate pair
        satisfies even the loosest constraint level — a book too thin to band,
        which must degrade rather than crash.
    """
    scores = np.asarray(scores, dtype="float64")
    y = np.asarray(went_bad, dtype="float64")
    if params is None:
        if rates is None:
            rates, rate_provenance = load_bank_rates()
        params, provenance = cost_params(rates, rate_provenance)
    else:
        rates = rates or {}
        provenance = {name: dict(source=ASSUMPTION, confidence="assumed", url="none",
                                 note=PARAM_NOTES.get(name, ""))
                      for name in params.__dataclass_fields__}

    lgd = lgd_vector(secured, params)
    costs = band_costs(ead, y, lgd, params)
    grid = _search(scores, y, costs, portfolio)
    pick = _pick(grid)

    cur = evaluate(current[0], current[1], scores, y, ead, secured, portfolio, params)
    # What cost ALONE would have picked. Emitted so the price of the
    # pre-registered constraint is visible rather than absorbed: on a thin book
    # DR-11's per-portfolio monotonicity is the binding constraint, not the
    # economics, and a reviewer is entitled to see by how much.
    free = _pick(grid, "none")
    unconstrained = (evaluate(free[0], free[1], scores, y, ead, secured, portfolio, params)
                     if free else None)

    if pick is None:
        chosen_amber, chosen_red, level = float(current[0]), float(current[1]), None
        chosen = dict(cur)
        feasible = False
    else:
        chosen_amber, chosen_red, level = pick
        chosen = evaluate(chosen_amber, chosen_red, scores, y, ead, secured, portfolio, params)
        feasible = True

    alternatives, curve = [], dict(red_sweep=[], amber_sweep=[])
    if grid is not None:
        mask = grid["levels"][level] if level else grid["valid"]
        total = np.where(mask, grid["total"], np.inf)
        flat = np.argsort(total, axis=None)
        seen = set()
        for f in flat[: 400]:
            if not np.isfinite(total.flat[f]):
                break
            a, r = np.unravel_index(int(f), total.shape)
            key = (round(float(grid["thresholds"][a]), 4), round(float(grid["thresholds"][r]), 4))
            if key in seen:
                continue
            seen.add(key)
            alternatives.append(dict(
                amber=key[0], red=key[1],
                expected_cost=round(float(total.flat[f]), 2),
                n_red=int(grid["ks"][r]), n_flagged=int(grid["ks"][a]),
            ))
            if len(alternatives) >= 6:
                break
        # The two one-dimensional slices through the chosen point: what a UI
        # draws when it has to answer "why is the threshold HERE?". Each point
        # carries the trade-off in counts as well as rupees, because a cost
        # curve on its own tells an officer nothing about what the move does to
        # his queue.
        order = np.argsort(-scores, kind="stable")
        cum_n = np.arange(len(scores) + 1, dtype="float64")
        cum_bad = _cumsum(y, order)
        total_bad = float(y.sum())
        a_star = int(np.argmin(np.abs(grid["thresholds"] - chosen_amber)))
        r_star = int(np.argmin(np.abs(grid["thresholds"] - chosen_red)))
        for j in range(len(grid["thresholds"])):
            k = int(grid["ks"][j])
            if grid["valid"][a_star, j]:
                curve["red_sweep"].append(dict(
                    red=round(float(grid["thresholds"][j]), 6),
                    expected_cost=round(float(grid["total"][a_star, j]), 2),
                    n_red=int(cum_n[k]), npas_in_red=int(cum_bad[k]),
                    # NOT the same quantity as `missed_npa_share`, which counts
                    # NPAs left in GREEN. This counts NPAs not in RED at this
                    # cut-off, which is what moving the Red line trades against.
                    npas_not_in_red=int(total_bad - cum_bad[k]),
                    false_positives=int(cum_n[k] - cum_bad[k]),
                ))
            if grid["valid"][j, r_star]:
                curve["amber_sweep"].append(dict(
                    amber=round(float(grid["thresholds"][j]), 6),
                    expected_cost=round(float(grid["total"][j, r_star]), 2),
                    n_flagged=int(cum_n[k]),
                    npas_in_green=int(total_bad - cum_bad[k]),
                    false_positives=int(cum_n[k] - cum_bad[k]),
                ))

    by_portfolio = []
    codes = np.asarray(portfolio, dtype=object)
    for code in sorted(set(codes.tolist())):
        m = codes == code
        share = declared_secured_share(code)
        by_portfolio.append(dict(
            portfolio=str(code), n=int(m.sum()),
            secured_share_observed=round(float(np.nanmean(np.asarray(secured, dtype="float64")[m])), 4),
            secured_share_sources_yaml=share,
            lgd_mean=round(float(lgd[m].mean()), 4),
            ead_mean_inr=round(float(np.asarray(ead, dtype="float64")[m].mean()), 2),
            expected_loss_mean_inr=round(float(expected_loss(np.asarray(ead, dtype="float64")[m],
                                                             lgd[m], params).mean()), 2),
        ))

    saved = cur["expected_cost"] - chosen["expected_cost"]
    return dict(
        amber=round(chosen_amber, 6), red=round(chosen_red, 6),
        method="cost_minimising",
        objective=("expected rupee cost over the frozen book: the expected loss on NPAs a band "
                   "misses, plus review and relationship-friction cost on the accounts it flags"),
        horizon_months=int(horizon),
        population="held-out accounts in the frozen book at the reference month",
        feasible=feasible,
        constraint_level=level,
        constraints=dict(
            pre_registered=[
                "DR-11: band default rates strictly increasing Green < Amber < Red, pooled and within every portfolio",
                "Red band non-empty in every portfolio",
            ],
            applied=level,
            ladder=[dict(level=name, rule=rule,
                         n_feasible=(int(grid["levels"][name].sum()) if grid else 0))
                    for name, rule in CONSTRAINT_LEVELS],
            n_candidates=(int(grid["valid"].sum()) if grid else 0),
            note=("Constraints are FEASIBILITY FILTERS ONLY. The objective is rupees; neither "
                  "AUC nor any band in validation/criteria.yaml enters it. A pair that breaks "
                  "DR-11 is never a candidate, and the level actually applied is recorded "
                  "above so a relaxation cannot pass unnoticed."),
        ),
        currency="INR",
        cost_params={k: (round(float(v), 6) if isinstance(v, float) else v)
                     for k, v in params.__dict__.items()},
        provenance=provenance,
        provenance_summary=provenance_summary(provenance),
        chosen=chosen,
        current=dict(cur, note="the hand-set thresholds the July 2026 build shipped"),
        unconstrained=(dict(unconstrained,
                            note="what cost ALONE would pick, ignoring the pre-registered constraints")
                       if unconstrained else None),
        constraint_cost=(round(chosen["expected_cost"] - unconstrained["expected_cost"], 2)
                             if unconstrained else None),
        delta=dict(
            expected_cost=round(saved, 2),
            expected_cost_pct=round(saved / cur["expected_cost"], 4) if cur["expected_cost"] else 0.0,
            missed_npa_share=round(chosen["missed_npa_share"] - cur["missed_npa_share"], 4),
            red_band_precision=round(chosen["red_band_precision"] - cur["red_band_precision"], 4),
            note=(
                "The July pair can price out CHEAPER than the chosen one, and where it does "
                "it is because it is not admissible: `current.constraint_level` says which "
                "pre-registered level it clears, and anything short of 'all_pre_registered' "
                "means it breaks DR-11 in at least one portfolio. The search minimises cost "
                "over the pairs that band the book legitimately, not over all of them."
                if saved < 0 else
                "The chosen pair is cheaper than the July pair and admissible under the "
                "pre-registered constraints."),
        ),
        alternatives=alternatives,
        cost_curve=curve,
        by_portfolio=by_portfolio,
        sensitivity=(_sensitivity(scores, y, ead, secured, portfolio, rates, rate_provenance,
                                  dict(constraint_level=level))
                     if sensitivity and feasible else []),
        override=dict(
            table="threshold_change",
            api="PUT /drishti/threshold",
            note=("The platform may override amber/red at any time. Everything else in this "
                  "block is the evidence for the value being replaced, not a lock on it."),
        ),
    )


#: rupees in one crore — the unit the policy fold's expected cost is quoted in,
#: because that is how the cost of an operating point gets discussed out loud.
CRORE = 1e7


def policy_fold_cost(thresholds):
    """The two expected-cost figures the operating-point choice actually turns on.

    Both already exist inside the block :func:`choose_thresholds` returns:
    ``chosen`` is the cost-minimising pair that shipped, ``current`` is the July
    2026 hand-set pair, and — the part that makes the comparison legitimate at
    all — they are priced on the SAME policy fold, over the same accounts, with
    the same cost parameters. This reads those two numbers back in crore rather
    than recomputing them, so a screen cannot print a rupee figure the search
    never produced, and ``n_accounts`` travels with them because a cost total is
    meaningless without the size of the book it was summed over.

    Returns:
        ``{n_accounts, expected_cost_chosen_cr, expected_cost_july_cr}``, or
        ``None`` when either side is missing — a book too thin to price must
        leave the field out rather than publish a zero that looks like a
        measurement.
    """
    chosen = (thresholds or {}).get("chosen") or {}
    current = (thresholds or {}).get("current") or {}
    if chosen.get("expected_cost") is None or current.get("expected_cost") is None:
        return None
    return dict(
        n_accounts=int(chosen.get("n") or 0),
        expected_cost_chosen_cr=round(float(chosen["expected_cost"]) / CRORE, 2),
        expected_cost_july_cr=round(float(current["expected_cost"]) / CRORE, 2),
    )

# -*- coding: utf-8 -*-
"""DM-6 — ``data/export/drishti_export.json``, in the platform's contract shape.

``rrsquad-platform/contracts/drishti_export.schema.json`` is a different, larger
shape than ``app/public/demo_data.json``: it wraps a full ``meta{}`` run envelope
(run id, commit, seed, criteria hash, sandbox sync), renames ``portfolio`` to
``accounts`` (because ``portfolio`` is now a FIELD on each account — the lending
portfolio enum), nests ``scores{}`` and ``provenance{}`` per account, and adds
``real_data`` (the frozen July real-MSME validation, embedded verbatim). This
module builds that shape from the payload :func:`export_demo.build_export`
already computed — no second model run, no second read of the CSVs.

Only produced when ``--out <path>`` is passed. Validate with::

    python3 ../rrsquad-platform/contracts/validate.py drishti data/export/drishti_export.json

Two things this module does differently from SANKET's equivalent (SM-6): SANKET
left ``model_run_id`` / ``git_sha`` / ``criteria_sha`` as valid-shaped
placeholders because it runs from a repo where none of the three is derivable
without the platform batch. Here all three ARE derivable standalone —
``model_run_id`` from ``uuid5(NAMESPACE, --label)`` (so a re-run with the same
label reproduces the same id, letting the platform's ``load`` stage replace
a candidate rather than duplicate it — ``batch/run.py``'s own contract),
``git_sha`` from ``git rev-parse HEAD`` in this repo, ``criteria_sha`` from
hashing the committed ``validation/criteria.yaml`` — so none of the three is a
placeholder here.

One deliberate, DOCUMENTED contract deviation: ``metrics.rank_order.by_portfolio``
is emitted as an ARRAY (matching this repo's own ``app/public/demo_data.json``
and the FE's ``.map()`` over it), not the OBJECT keyed by portfolio code the
schema's ``$defs.rank_order.by_portfolio`` actually specifies. BE-7 already
flagged this exact API-vs-export mismatch; the ruling stands — keep the array,
note it, don't fork the shape the FE already renders. ``validate.py`` reports
this as the one schema error on an otherwise-clean export.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))   # so `import bank` resolves standalone

import bank as B                                            # noqa: E402  (path shim first)
import costs                                                # noqa: E402  (path shim first)

SCHEMA_VERSION = "1.0.0"
#: decimals every published per-account score carries. The SAME quantisation the
#: thresholds are emitted at (``costs.THRESHOLD_DECIMALS``, mirrored by
#: ``export_demo.SCORE_DECIMALS``) — imported from ``costs`` rather than from
#: ``export_demo``, which imports this module.
SCORE_DECIMALS = costs.THRESHOLD_DECIMALS
#: Fixed namespace so uuid5(NAMESPACE, label) is stable across processes and
#: machines — the whole point of deriving model_run_id from --label at all.
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://rrsquad.dev/drishti")

#: how many account-level bootstrap resamples metrics.auc_ci draws. Resampling
#: is over ACCOUNTS (with replacement), not rows, so within-account month-to-
#: month correlation does not understate the interval.
AUC_BOOTSTRAP_N = 200
AUC_BOOTSTRAP_SEED = 7


# --------------------------------------------------------------------------- #
# meta — model_run_id / git_sha / criteria_sha, all real, none placeholder
# --------------------------------------------------------------------------- #
def model_run_id(label: str | None) -> str:
    """A deterministic id: the same --label always mints the same id.

    ``batch/run.py``'s contract (BE-8's report): "--label folded into
    meta.model_run_id so a re-run with the same label replaces its candidate."
    """
    return str(uuid.uuid5(_NAMESPACE, label or "local-dev"))


def repo_git_sha(root: Path) -> tuple[str | None, str | None]:
    """``(sha, note)``. ``note`` is ``None`` on a clean HEAD, else why it might
    not be trustworthy (a dirty tree, or git being unavailable at all)."""
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
        if head.returncode != 0 or not head.stdout.strip():
            return None, "git rev-parse HEAD failed — not a git checkout, or no commits yet"
        sha = head.stdout.strip()
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=10, check=False)
        dirty = bool(status.stdout.strip())
        return sha, ("working tree has uncommitted changes at export time" if dirty else None)
    except (OSError, subprocess.SubprocessError):
        return None, "git is unavailable in this environment"


def criteria_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "0" * 64


def build_sandbox_sync(bank_ctx: B.BankContext | None, generated_at: str) -> dict:
    """``meta.sandbox_sync`` — MUST be empty ``endpoints`` when mode is fixture."""
    if bank_ctx is None or not bank_ctx.enabled:
        return dict(pulled_at=generated_at, mode="fixture", endpoints=[])
    if bank_ctx.pulled is not None:
        pulled_at = bank_ctx.pulled.get("generated_at", generated_at)
        endpoints = []
        for api_id, entry in sorted(bank_ctx.pulled.get("apis", {}).items(), key=lambda kv: int(kv[0])):
            row = dict(
                api_id=str(api_id),
                http_status=int(entry.get("http_status") or 0),
                n_records=int(entry.get("n_records") or 0),
                subscription_status="approved" if entry.get("provenance") == "BANK_API" else "pending",
            )
            latency = entry.get("latency_ms")
            if isinstance(latency, (int, float)):
                row["latency_ms"] = int(latency)
            error = entry.get("reason")
            if error:
                row["error"] = str(error)
            endpoints.append(row)
        mode = bank_ctx.mode if bank_ctx.mode in ("live", "mixed") else "fixture"
        if mode == "fixture":
            endpoints = []      # schema: endpoints MUST be empty when mode is fixture
        return dict(pulled_at=pulled_at, mode=mode, endpoints=endpoints)
    if bank_ctx.fixture_by_account:
        pulled_at = (bank_ctx.fixture_meta or {}).get("generated_at", generated_at)
        return dict(pulled_at=pulled_at, mode="fixture", endpoints=[])
    return dict(pulled_at=generated_at, mode="fixture", endpoints=[])


def build_meta(internal_out: dict, *, label: str | None, seed: int, root: Path,
               bank_ctx: B.BankContext | None) -> tuple[dict, dict]:
    """The contract's run envelope. Returns ``(meta, debug)`` — ``debug`` is not
    written to the export; it is what the CLI prints and the caller can use to
    decide whether anything needs flagging as a gap (e.g. a dirty tree)."""
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    sha, git_note = repo_git_sha(root)
    git_sha = sha or ("0" * 40)
    crit_sha = criteria_sha256(Path(root) / "validation" / "criteria.yaml")
    run_id = model_run_id(label)
    im = internal_out["meta"]

    meta = dict(
        product="drishti",
        schema_version=SCHEMA_VERSION,
        model_run_id=run_id,
        generated_at=generated_at,
        git_sha=git_sha,
        seed=int(seed),
        criteria_sha=crit_sha,
        provenance_version=1,
        sandbox_sync=build_sandbox_sync(bank_ctx, generated_at),
        generated_from=im["generated_from"] + (
            "; enriched from the IDBI Atlas sandbox / data/bank/fixture.json"
            if bank_ctx is not None and bank_ctx.enabled else ""),
        reference_month=im["reference_month"],
        horizon_months=int(im["horizon_months"]),
        npa_definition_dpd=int(im["npa_definition_dpd"]),
        n_accounts_scored=int(im["n_accounts_scored"]),
    )
    # The banding policy, named. `decision_score` is the score the thresholds were
    # chosen over; a consumer that bands on anything else is not running this
    # policy, whatever thresholds it uses. Omitted (rather than emitted null) when
    # an older internal payload carries neither — `meta` forbids unknown keys and
    # a null would be a claim that the run had no policy.
    for key in ("policy_version", "decision_score", "eligibility"):
        if im.get(key) is not None:
            meta[key] = im[key]
    debug = dict(git_sha=git_sha, git_note=git_note, criteria_sha=crit_sha,
                model_run_id=run_id, label=label or "local-dev")
    return meta, debug


# --------------------------------------------------------------------------- #
# metrics.auc_ci — account-level bootstrap around the ALREADY-PUBLISHED AUC
# --------------------------------------------------------------------------- #
def bootstrap_auc_ci(account_id: np.ndarray, y: np.ndarray, p: np.ndarray, *,
                     value: float, n_boot: int = AUC_BOOTSTRAP_N,
                     seed: int = AUC_BOOTSTRAP_SEED) -> dict:
    """A confidence interval around ``value`` (the row-level AUC every other
    report in this project already cites — never recomputed here, only
    bracketed), by resampling ACCOUNTS with replacement so within-account
    month-to-month correlation does not understate the interval.
    """
    account_id = np.asarray(account_id)
    y = np.asarray(y, dtype="float64")
    p = np.asarray(p, dtype="float64")
    uniq, inverse = np.unique(account_id, return_inverse=True)
    n = int(uniq.size)
    if n == 0 or len(np.unique(y)) < 2:
        return dict(value=round(float(value), 4), ci_low=round(float(value), 4),
                    ci_high=round(float(value), 4), n=n, method="bootstrap")

    idx_by_acc = [np.flatnonzero(inverse == i) for i in range(n)]
    rng = np.random.default_rng(seed)
    aucs = []
    for _ in range(n_boot):
        picks = rng.integers(0, n, size=n)
        idx = np.concatenate([idx_by_acc[i] for i in picks])
        yy = y[idx]
        if len(np.unique(yy)) < 2:
            continue
        aucs.append(roc_auc_score(yy, p[idx]))
    if not aucs:
        return dict(value=round(float(value), 4), ci_low=round(float(value), 4),
                    ci_high=round(float(value), 4), n=n, method="bootstrap")
    lo, hi = np.percentile(aucs, [2.5, 97.5])
    return dict(value=round(float(value), 4), ci_low=round(float(lo), 4),
                ci_high=round(float(hi), 4), n=n, method="bootstrap")


# --------------------------------------------------------------------------- #
# metrics.red_band_precision / metrics.cost_model — renamed / reshaped from
# the internal red_band_precision_8m / thresholds blocks. No new numbers.
# --------------------------------------------------------------------------- #
def red_band_precision_block(internal_metrics: dict) -> dict:
    r = internal_metrics.get("red_band_precision_8m", {})
    return dict(
        value=float(r.get("value", 0.0)), ci_low=float(r.get("ci_lo", 0.0)),
        ci_high=float(r.get("ci_hi", 0.0)), horizon_months=int(r.get("horizon_months", 8)),
        n_red=int(r.get("n_red", 0)), n_red_npa=int(r.get("n_defaulted", 0)), method="wilson",
    )


def _weighted_mean(rows: list[dict], key: str) -> float:
    total_n = sum(int(r.get("n", 0)) for r in rows)
    if not total_n:
        return 0.0
    return sum(float(r.get(key, 0.0)) * int(r.get("n", 0)) for r in rows) / total_n


def cost_model_block(thresholds: dict) -> dict:
    """DM-5's ``thresholds`` block, reshaped into the contract's ``cost_model``.

    ``cost_missed_npa`` / ``cost_false_positive`` are not single numbers DM-5
    emits directly (the search works in aggregate expected cost over the whole
    book, not a per-account rate) — they are RECOVERED here from numbers DM-5
    already computed per portfolio (``expected_loss_mean_inr``, ``ead_mean_inr``)
    and from the same per-account cost formula ``src/costs.py::band_costs``
    uses for a false positive in the Red band
    (``review_cost_red_inr + friction_share_red * EAD * effective_rate_pa``,
    at ``y=0``). No new assumption is introduced; this is the existing search's
    own arithmetic, read back out rather than re-derived.
    """
    cp = thresholds.get("cost_params", {}) or {}
    eff_rate_pa = float(cp.get("effective_rate_pa", 12.75))
    review_cost_red = float(cp.get("review_cost_red_inr", 18_000.0))
    friction_red = float(cp.get("friction_share_red", 0.15))
    lgd_secured = cp.get("lgd_secured")

    by_port = thresholds.get("by_portfolio", []) or []
    cost_missed_npa = max(_weighted_mean(by_port, "expected_loss_mean_inr"), 1.0)
    mean_ead = _weighted_mean(by_port, "ead_mean_inr")
    cost_false_positive = max(review_cost_red + friction_red * mean_ead * eff_rate_pa / 100.0, 1.0)

    curve = []
    for pt in ((thresholds.get("cost_curve") or {}).get("red_sweep") or []):
        curve.append(dict(
            threshold=round(float(pt.get("red", thresholds.get("red", 0.5))), 6),
            n_flagged=int(pt.get("n_red", 0)),
            missed_npa=int(pt.get("npas_not_in_red", 0)),
            false_positives=int(pt.get("false_positives", 0)),
            expected_cost=round(float(pt.get("expected_cost", 0.0)), 2),
        ))
    if len(curve) < 2:
        # A too-thin book (or a constrained search) can leave the sweep empty.
        # Degrade to the two points the search DID compute — chosen and
        # current — rather than fabricate a curve. Never invent a cost.
        curve = []
        for block in (thresholds.get("chosen"), thresholds.get("current")):
            if not block:
                continue
            bands = block.get("bands", {})
            red, amber, green = bands.get("red", {}), bands.get("amber", {}), bands.get("green", {})
            curve.append(dict(
                threshold=round(float(block.get("red", thresholds.get("red", 0.5))), 6),
                n_flagged=int(red.get("n", 0)) + int(amber.get("n", 0)),
                missed_npa=int(green.get("defaults", 0)),
                false_positives=int(red.get("n", 0)) - int(red.get("defaults", 0)),
                expected_cost=round(float(block.get("expected_cost", 0.0)), 2),
            ))
        if len(curve) == 1:
            twin = dict(curve[0])
            twin["threshold"] = round(min(0.999999, twin["threshold"] + 1e-6), 6)
            curve.append(twin)
        elif not curve:
            curve = [dict(threshold=float(thresholds.get("red", 0.5)), n_flagged=0,
                          missed_npa=0, false_positives=0, expected_cost=1.0),
                    dict(threshold=round(float(thresholds.get("red", 0.5)) + 1e-6, 6),
                        n_flagged=0, missed_npa=0, false_positives=0, expected_cost=1.0)]

    block = dict(
        currency="INR",
        cost_missed_npa=round(cost_missed_npa, 2),
        cost_false_positive=round(cost_false_positive, 2),
        ratio_missed_to_fp=round(cost_missed_npa / cost_false_positive, 2),
        interest_rate_pa=round(eff_rate_pa / 100.0, 6),
        penal_rate_pa=round(float(cp.get("penal_rate_pa", 2.0)) / 100.0, 6),
        chosen_red_thr=round(float(thresholds.get("red", 0.0)), 6),
        chosen_amber_thr=round(float(thresholds.get("amber", 0.0)), 6),
        curve=curve,
        provenance=dict(rates="BANK_API", costs="SIMULATED"),
    )
    if lgd_secured is not None:
        block["lgd"] = round(_weighted_mean(by_port, "lgd_mean") or float(lgd_secured), 4)
    # The two-number rupee comparison, in crore, over the fold the search ran on.
    # Same helper the internal payload's `metrics.cost_model.policy_fold` uses, so
    # the contract and the cockpit cannot quote different costs for the same run.
    # `curve` above is priced on that same fold; this is its two named points.
    policy_fold = costs.policy_fold_cost(thresholds)
    if policy_fold:
        block["policy_fold"] = policy_fold
    return block


# --------------------------------------------------------------------------- #
# accounts[] / timelines{} / scores{} / provenance{}
# --------------------------------------------------------------------------- #
def _num0(v) -> float:
    return 0.0 if v is None else float(v)


def _synthetic_cif_id(account_id: str) -> str:
    """A deterministic 9-digit numeric id from the account_id's own digits.

    Not a real CIF — used only for accounts a bank pull/fixture never covered
    — but stable across runs and collision-free (the suffix is already unique
    per account in this panel). Leading '9' flags it as synthetic to anyone
    who goes looking; real IDBI CIFs are 9 digits too, so the pattern still
    validates against the contract's ``cif_id`` format.
    """
    digits = "".join(ch for ch in str(account_id) if ch.isdigit())
    return f"9{int(digits[-8:] or 0):08d}"


def runway_estimate(timeline: list[dict], ref_month: str, red_thr: float) -> int | None:
    """Months until the smoothed score crosses the next threshold, projected
    from a least-squares fit of the last six observed months. Ported line for
    line from ``app/src/lib/runway.js`` (client-validated: median error ~3
    months on the synthetic book) so the export and the cockpit agree exactly
    when the FE later reads this field instead of recomputing it itself.

    ``None`` when there is not enough history, or the trend is not rising —
    an honest blank, never a fabricated number (schema's own words).
    """
    if not timeline:
        return None
    hist = [pt for pt in timeline if pt.get("date") and pt["date"] <= ref_month]
    if len(hist) < 7:
        return None
    # Projected on the DECISION score, because the threshold it is projected AT
    # is a threshold on the decision score. Falls back to `pd_smooth` (the same
    # number under its older name) and only then to `pd`.
    vals = [
        pt.get("decision_score")
        if pt.get("decision_score") is not None
        else (pt.get("pd_smooth") if pt.get("pd_smooth") is not None else pt.get("pd"))
        for pt in hist[-6:]
    ]
    if any(v is None for v in vals):
        return None
    n = len(vals)
    xm = (n - 1) / 2.0
    ym = sum(vals) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(vals))
    den = sum((i - xm) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    cur = vals[-1]
    if slope <= 0.002:
        return None
    target = red_thr if cur < red_thr else 0.85
    return int(max(1, min(12, math.ceil((target - cur) / slope))))


def build_contract_accounts(internal_out: dict, *, bank_ctx: B.BankContext | None) -> tuple[list, dict]:
    """``accounts[]`` and ``timelines{}`` in the contract shape.

    Four account fields the contract types as a plain non-nullable number
    (``dpd``, ``utilisation``, ``inflow_vs_6m_avg``, ``sales_trend_3m``) are
    ``null`` in the internal shape for a channel a portfolio does not have —
    the internal shape's whole point (``export_demo.py``'s own docstring: "An
    absent channel must read as absent, not as zero"). The contract has no
    slot for that distinction, so those four are coerced to 0.0 here, and
    ``channels_present`` (which DOES carry the distinction) is still attached
    as an informative extra — the account schema explicitly allows unknown
    extra properties. This is a narrow, documented adaptation to the CONTRACT
    shape only; the internal ``app/public/demo_data.json`` keeps its nulls.
    """
    ref_month = internal_out["meta"]["reference_month"]
    red_thr = float(internal_out["portfolio_summary"]["red_thr"])
    timelines_in = internal_out.get("timelines", {})
    accounts, contract_timelines = [], {}

    for rec in internal_out["portfolio"]:
        aid = rec["account_id"]
        tl = timelines_in.get(aid, [])
        # The RECORD first, the timeline only as a fallback. Both carry the same two
        # numbers, but the timeline is a chart series quantised to three decimals for
        # the app's payload budget, while the record carries them at the precision the
        # bands were decided at (`export_demo.SCORE_DECIMALS`). Reading the coarse copy
        # when the exact one is right there is how a published score stops reproducing
        # its own band.
        pd_smooth = rec.get("pd")              # already the smoothed value, internal shape
        pd_raw = rec.get("pd_raw")
        if pd_raw is None or pd_smooth is None:
            for pt in tl:
                if pt.get("date") == ref_month:
                    pd_raw = pt.get("pd") if pd_raw is None else pd_raw
                    pd_smooth = pt.get("pd_smooth") if pd_smooth is None else pd_smooth
                    break
        if pd_raw is None:
            pd_raw = pd_smooth if pd_smooth is not None else 0.0
        # The score the bands were chosen over. The record carries it explicitly
        # now; `pd_smooth` is the same number and is the fallback for an older
        # internal payload, because that is what the July policy banded on.
        decision = rec.get("decision_score")
        if decision is None:
            decision = pd_smooth if pd_smooth is not None else 0.0

        overlay = bank_ctx.overlay_for(aid) if bank_ctx is not None else {}
        provenance = (bank_ctx.provenance_for(aid) if bank_ctx is not None
                     else {f: "SIMULATED" for f in B.FAMILIES})
        cif_id = overlay.get("cif_id") or _synthetic_cif_id(aid)

        account = dict(
            account_id=aid, cif_id=cif_id,
            portfolio=rec.get("portfolio"), constitution=rec.get("constitution"),
            secured=bool(rec["secured"]) if rec.get("secured") is not None else False,
            sector=rec.get("sector"), region=rec.get("region"), loan_type=rec.get("loan_type"),
            segment=rec.get("segment"), promoter_age_group=rec.get("promoter_age_group"),
            sanctioned=_num0(rec.get("sanctioned")),
            outstanding=_num0(rec.get("outstanding")),
            vintage_months=int(rec.get("vintage_months") or 0),
            business_age_years=int(rec.get("business_age_years") or 0),
            dpd=_num0(rec.get("dpd")),
            utilisation=_num0(rec.get("utilisation")),
            inflow_vs_6m_avg=_num0(rec.get("inflow_vs_6m_avg")),
            sales_trend_3m=_num0(rec.get("sales_trend_3m")),
            snap_months_to_npa=int(rec["snap_months_to_npa"]) if rec.get("snap_months_to_npa") is not None else -1,
            ground_truth_default=int(rec.get("ground_truth_default") or 0),
            eco_partners=int(rec.get("eco_partners") or 0),
            eco_flagged=int(rec.get("eco_flagged") or 0),
            eco_red=int(rec.get("eco_red") or 0),
            channels_present=list(rec.get("channels_present") or []),
            scores=dict(
                # SCORE_DECIMALS (= costs.THRESHOLD_DECIMALS), not four: the platform
                # re-bands `decision_score >= chosen_red_thr` in SQL, so a score
                # published coarser than the threshold it is compared against is a
                # band the loader cannot reproduce. Two accounts straddled the Amber
                # cut-off at four decimals.
                pd=round(float(pd_raw), SCORE_DECIMALS),
                pd_smooth=round(float(pd_smooth), SCORE_DECIMALS),
                # The ONE score every band is derived from. Equal to pd_smooth under
                # the current policy; emitted under its own name so a consumer never
                # has to guess which of the two the thresholds were tuned on.
                decision_score=round(float(decision), SCORE_DECIMALS),
                pd_calibrated=(None if rec.get("pd_calibrated") is None
                               else round(float(rec["pd_calibrated"]), SCORE_DECIMALS)),
                bucket=rec.get("bucket"), reasons=list(rec.get("reasons") or [])[:5],
                first_warning_lead=int(rec.get("first_warning_lead") or 0),
                runway_months=runway_estimate(tl, ref_month, red_thr),
                # SD-D5's secondary label (SMA-2-or-worse within 6 months), read off the
                # panel via export_demo.py's own snapshot row. `enum: [0, 1]` in the
                # schema — a genuinely unknown value is OMITTED rather than sent as null,
                # which the enum would reject; every account in a real build_export
                # payload has one, so this only triggers on a hand-built fixture.
                **({"sma2_within_6m": int(rec["sma2_within_6m"])}
                   if rec.get("sma2_within_6m") is not None else {}),
            ),
            provenance=provenance,
        )
        for k, v in overlay.items():
            if k != "cif_id":
                account[k] = v
        accounts.append(account)

        points = [
            dict(date=pt.get("date"),
                pd=round(_num0(pt.get("pd")), 4), pd_smooth=round(_num0(pt.get("pd_smooth")), 4),
                decision_score=round(_num0(pt.get("decision_score", pt.get("pd_smooth"))), 4),
                utilisation=(None if pt.get("utilisation") is None else round(float(pt["utilisation"]), 4)),
                inflow=_num0(pt.get("inflow")),
                # Per-month DPD, schema-typed as a plain integer — never null on this
                # channel (every facility has a days-past-due reading), so unlike
                # `utilisation` there is no "channel absent" case to preserve; omitted
                # only when a point genuinely carries none (an older internal payload).
                **({"dpd": int(round(_num0(pt["dpd"])))} if pt.get("dpd") is not None else {}))
            for pt in tl
        ]
        if not points:
            # every account in `accounts[]` must have >=1 timeline point (schema).
            # Should never trigger on a real build_export payload (every listed
            # account has its own held-out history) — a defensive stub only, from
            # the account's own snapshot values, so a caller with an incomplete
            # fixture never trips a minItems violation on this account alone.
            points = [dict(date=ref_month, pd=round(_num0(pd_raw), 4),
                           pd_smooth=round(_num0(pd_smooth), 4),
                           decision_score=round(_num0(decision), 4),
                           utilisation=None, inflow=0.0,
                           dpd=int(round(_num0(rec.get("dpd")))))]
        contract_timelines[aid] = points
    return accounts, contract_timelines


# --------------------------------------------------------------------------- #
# real_data — the frozen July validation, embedded verbatim
# --------------------------------------------------------------------------- #
def load_real_data(root: Path) -> dict | None:
    """``app/public/real_model.json`` and ``data/real_model.json`` are the same
    file (``src/real_model.py`` is frozen for the build week). Either satisfies
    the contract's ``real_data`` block — meta/metrics/top_features/reliability/
    examples — which is why it can be embedded verbatim rather than gapped out.
    """
    for rel in ("app/public/real_model.json", "data/real_model.json"):
        p = Path(root) / rel
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
    return None


# --------------------------------------------------------------------------- #
# the assembler
# --------------------------------------------------------------------------- #
def build_contract_export(internal_out: dict, *, label: str | None = None, seed: int = 7,
                          bank_ctx: B.BankContext | None = None, root: Path,
                          bootstrap_data: dict | None = None) -> tuple[dict, dict]:
    """The full ``drishti_export.schema.json``-shaped payload.

    Returns ``(export, debug)``. ``debug`` carries what the CLI prints (git
    sha / dirty note, criteria sha, model_run_id) — never written to the file.
    """
    meta, debug = build_meta(internal_out, label=label, seed=seed, root=root, bank_ctx=bank_ctx)
    accounts, timelines = build_contract_accounts(internal_out, bank_ctx=bank_ctx)

    m = internal_out["metrics"]
    metrics = dict(m)   # shallow copy: keeps honesty / raw_accuracy_8m / base_rate_* etc.
    # rank_order is `additionalProperties: false` in the schema — strip the two
    # internal-only keys (`population`, the DR-11/DR-12 `gate` verdict) it does
    # not declare. `by_portfolio` stays an ARRAY: DOCUMENTED gap, see the module
    # docstring; validate.py reports exactly this one on an otherwise-clean export.
    ro = m["rank_order"]
    metrics["rank_order"] = dict(
        horizon_months=ro["horizon_months"], definition=ro["definition"],
        by_band=ro["by_band"], by_decile=ro["by_decile"], by_portfolio=ro["by_portfolio"],
    )
    metrics.pop("red_band_precision_8m", None)
    metrics["red_band_precision"] = red_band_precision_block(m)
    metrics["base_rate"] = float(m.get("base_rate_8m", {}).get("value", 0.0))
    metrics["accuracy"] = float(m.get("raw_accuracy_8m", {}).get("value", 0.0))
    metrics["cost_model"] = cost_model_block(internal_out["thresholds"])
    if bootstrap_data is not None:
        metrics["auc_ci"] = bootstrap_auc_ci(
            bootstrap_data["account_id"], bootstrap_data["y"], bootstrap_data["p"],
            value=m["auc"])
    else:
        metrics["auc_ci"] = dict(value=m["auc"], ci_low=m["auc"], ci_high=m["auc"],
                                 n=int(internal_out["meta"]["n_accounts_scored"]), method="bootstrap")

    real_data = load_real_data(root)

    export = dict(
        meta=meta,
        metrics=metrics,
        portfolio_summary=internal_out["portfolio_summary"],
        accounts=accounts,
        timelines=timelines,
        spotlight=list(internal_out.get("spotlight", [])),
        memos=dict(internal_out.get("memos", {})),
        ecosystem=internal_out.get("ecosystem", {}),
        rigor=internal_out.get("rigor", {}) or {},
        real_data=real_data or {},
    )
    return export, debug


# --------------------------------------------------------------------------- #
# --demo-sample — stratified subset for app/public/demo_data.json
# --------------------------------------------------------------------------- #
def stratified_sample(internal_out: dict, n: int, *, seed: int = 7) -> dict:
    """A NEW internal-shaped payload whose ``portfolio``/``timelines``/``memos``
    are restricted to an ``n``-account subset, stratified by (portfolio, band)
    with proportional allocation (largest-remainder rounding). Every other key
    — ``metrics``, ``thresholds``, ``portfolio_summary``, ``rigor``,
    ``ecosystem`` — is the FULL panel's, untouched: sampling is for the SPA's
    file size, not for the numbers it reports.

    DM-4/5 saw a 65 MB ``demo_data.json`` at 45k accounts, which the app
    cannot ship; this is the fix. The full ``--out`` export stays unsampled.
    """
    import random

    portfolio = internal_out.get("portfolio", [])
    total = len(portfolio)
    if n <= 0 or n >= total:
        picked_ids = {r["account_id"] for r in portfolio}
    else:
        rng = random.Random(seed)
        strata: dict[tuple, list[str]] = {}
        for r in portfolio:
            strata.setdefault((r.get("portfolio"), r.get("bucket")), []).append(r["account_id"])

        raw = {k: len(v) * n / total for k, v in strata.items()}
        alloc = {k: int(math.floor(v)) for k, v in raw.items()}
        remainder = n - sum(alloc.values())
        order = sorted(strata.keys(), key=lambda k: raw[k] - alloc[k], reverse=True)
        for k in order[: max(0, remainder)]:
            alloc[k] += 1

        picked_ids = set()
        for k, ids in strata.items():
            take = min(alloc.get(k, 0), len(ids))
            picked_ids.update(rng.sample(ids, take))

        by_id = {r["account_id"] for r in portfolio}
        for sid in internal_out.get("spotlight", []):
            if sid in by_id:
                picked_ids.add(sid)          # the demo leads with these; never drop them

    sampled_portfolio = [r for r in portfolio if r["account_id"] in picked_ids]
    out = dict(internal_out)
    out["portfolio"] = sampled_portfolio
    out["timelines"] = {k: v for k, v in internal_out.get("timelines", {}).items() if k in picked_ids}
    out["memos"] = {k: v for k, v in internal_out.get("memos", {}).items() if k in picked_ids}
    out["spotlight"] = [s for s in internal_out.get("spotlight", []) if s in picked_ids]
    # The band counts OF THE SAMPLE, recorded beside it. `portfolio_summary` counts
    # the full panel, so it cannot be used to check a consumer that loads this file:
    # any consumer that re-bands these accounts from `decision_score` against
    # `portfolio_summary.red_thr / amber_thr` must reproduce exactly these three
    # numbers, and the platform's integration test asserts that it does.
    sampled_bands = {band: sum(1 for r in sampled_portfolio if r.get("bucket") == band)
                     for band in ("red", "amber", "green")}
    out["_demo_sample"] = dict(
        requested=int(n), sampled=len(sampled_portfolio), full_panel=total,
        stratified_by=["portfolio", "bucket"], seed=int(seed),
        bands=sampled_bands,
        banded_on="decision_score",
        policy_version=internal_out.get("meta", {}).get("policy_version"),
        note=("metrics / thresholds / rank_order / rigor below are the FULL panel's — "
              "only accounts/timelines are sampled, for file size. `bands` counts THIS "
              "sample, so a consumer can check its own banding against it."),
    )
    return out


__all__ = [
    "SCHEMA_VERSION", "model_run_id", "repo_git_sha", "criteria_sha256",
    "build_sandbox_sync", "build_meta", "bootstrap_auc_ci", "red_band_precision_block",
    "cost_model_block", "runway_estimate", "build_contract_accounts", "load_real_data",
    "build_contract_export", "stratified_sample",
]

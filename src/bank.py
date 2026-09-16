# -*- coding: utf-8 -*-
"""DM-6 — the ``--bank`` enrichment path.

``data/bank/SCHEMA.md`` states the fallback rule this module implements exactly::

    credentials present AND endpoint approved  ->  live pull      -> BANK_API
    credentials present BUT endpoint pending   ->  fixture column -> FIXTURE
    no credentials / no endpoints at all       ->  whole fixture  -> FIXTURE
    no bank API supplies this field at all     ->  generator      -> SIMULATED
    the `model` family                         ->  the weakest of the other seven

Without ``--bank`` the pipeline is untouched: every family stays ``SIMULATED``,
exactly as it did in July 2026 (``data/bank/SCHEMA.md``: "without it the pipeline
runs purely synthetic").

With ``--bank``, this module reads two files the platform's batch writes into this
repo (``rrsquad-platform/batch/enrich.py``) and one committed offline stand-in:

* ``data/bank/pulled.json``     — what each Atlas API answered, per API (gitignored).
* ``data/bank/provenance.json`` — the platform's own family/endpoint summary
  (its ``columns`` block is this repo's to fill; nothing here reads it back —
  the family/endpoint levels ``pulled.json`` already carries are enough to
  derive the same families this module needs).
* ``data/bank/fixture.json``    — 160 committed accounts, the offline stand-in
  used whenever a live pull is unavailable or incomplete.

None of the three is required to exist. All three are gitignored except the
fixture (``data/bank/SCHEMA.md`` rule 1); this module degrades to whichever
subset is present rather than failing.

**Coverage is honestly partial, on purpose.** ``fixture.json`` covers 160 of the
panel's several thousand accounts (``account_id`` overlaps the panel's own
``MSME#####`` numbering by construction — the fixture and the generator share
the same id scheme). Per-account provenance (:meth:`BankContext.provenance_for`)
reflects that: an account outside the fixture reads ``SIMULATED`` for a family
the *aggregate* run reports as ``FIXTURE``, because nothing was actually
substituted for it.

**What actually gets overlaid.** Only the ``identity`` family's fields
(``cif_id``, ``foracid``, ``branch_code``, ``branch_name``, ``ifsc``, ``rm_ein``,
``rm_name``, ``reporting_manager_ein``, ``account_manager_ein``) are literal
pass-through display fields that never touch the model. They are the only ones
this module overlays onto an account record. The other six non-``model``
families (``exposure``, ``repayment``, ``cashflow``, ``bureau``, ``filings``,
``profile``) badge honestly against fixture/live coverage, but their VALUES stay
whatever the synthetic generator produced — the model was trained on the
synthetic panel and only the synthetic panel, ``--bank`` or not, so badging a
displayed ``dpd`` as ``FIXTURE`` while showing the generator's number would be
the dishonest move this whole module exists to avoid. See
``MODEL_CARD.md``'s provenance legend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PULLED_NAME = "pulled.json"
PROVENANCE_NAME = "provenance.json"
FIXTURE_NAME = "fixture.json"

#: The eight-family vocabulary ``data/bank/SCHEMA.md`` and the platform contract
#: (``drishti_export.schema.json``'s ``$defs.provenance``) both use.
FAMILIES: tuple[str, ...] = (
    "identity", "exposure", "repayment", "cashflow", "bureau", "filings", "profile", "model",
)

#: Families no Atlas API supplies at all (SCHEMA.md, "Fields no API supplies —
#: always SIMULATED": GST turnover/filing delay, sales trend, adverse remarks,
#: EPFO, DISCOM). Always this value, ``--bank`` or not.
ALWAYS_SIMULATED: tuple[str, ...] = ("filings",)

#: Only the fields this module actually overlays are the ones a live pull or the
#: fixture can genuinely replace without disturbing what the model scored:
#: identity is pure display metadata (SCHEMA.md's "identity" column group).
OVERLAY_FIELDS: tuple[str, ...] = (
    "cif_id", "foracid", "branch_code", "branch_name", "ifsc",
    "rm_ein", "rm_name", "reporting_manager_ein", "account_manager_ein",
)

#: SCHEMA.md's "The 25 APIs" table, collapsed to the family each API feeds.
FAMILY_APIS: dict[str, tuple[str, ...]] = {
    "identity": ("442", "456", "394", "508"),
    "exposure": ("391", "441", "362", "433", "473", "538"),
    "repayment": ("402", "404"),
    "cashflow": ("393",),
    "bureau": ("408",),
    "profile": ("456",),
}

#: Trust order, worst first — ``weakest`` walks it in this direction so ties fall
#: to the least-trusted source, matching SCHEMA.md's stated rule
#: (``BANK_API > SIMULATED > FIXTURE``).
_WORST_FIRST: tuple[str, ...] = ("FIXTURE", "SIMULATED", "BANK_API")


def weakest(sources: list[str]) -> str:
    """The ``model`` family's rule: the WEAKEST of the sources that fed it."""
    present = set(sources)
    for s in _WORST_FIRST:
        if s in present:
            return s
    return "SIMULATED"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _answered_apis(pulled: dict) -> set[str]:
    """API ids the pull actually got a ``BANK_API`` answer for.

    Matches ``rrsquad-platform/batch/enrich.py``'s ``build_pulled`` shape:
    ``pulled["apis"][api_id]["provenance"] == "BANK_API"``.
    """
    apis = pulled.get("apis", {})
    if not isinstance(apis, dict):
        return set()
    return {str(k) for k, v in apis.items() if isinstance(v, dict) and v.get("provenance") == "BANK_API"}


def _fixture_by_account(fixture: dict | None) -> dict[str, dict]:
    if not fixture:
        return {}
    rows = fixture.get("accounts", [])
    if not isinstance(rows, list):
        return {}
    return {str(r["account_id"]): r for r in rows if isinstance(r, dict) and "account_id" in r}


@dataclass(frozen=True)
class BankContext:
    enabled: bool
    mode: str  # "simulated" | "fixture" | "mixed" | "live"
    families: dict[str, str]
    fixture_by_account: dict[str, dict] = field(default_factory=dict)
    pulled: dict[str, Any] | None = None
    provenance_raw: dict[str, Any] | None = None
    fixture_meta: dict[str, Any] | None = None
    reason: str = ""

    def overlay_for(self, account_id: str) -> dict:
        """The identity-only overlay for ``account_id``, or ``{}`` if not covered.

        Only :data:`OVERLAY_FIELDS` are read out of the fixture/pulled row — see
        the module docstring for why exposure/repayment/cashflow/bureau/profile
        numbers are never substituted here.
        """
        row = self.fixture_by_account.get(str(account_id))
        if not row:
            return {}
        return {k: row[k] for k in OVERLAY_FIELDS if k in row and row[k] is not None}

    def provenance_for(self, account_id: str) -> dict[str, str]:
        """Per-account family provenance — honest about partial fixture coverage.

        The aggregate :attr:`families` says what the *run* achieved; a single
        account only actually got substituted data if it is one of the
        fixture's 160 (or, on a live pull, if the API genuinely answered for
        it). Every other account reads ``SIMULATED`` for that family
        regardless of what the run's summary says, because nothing was
        actually overlaid for it. Only ``identity`` is ever overlaid (see
        :meth:`overlay_for`); the other five non-``filings``/``model``
        families are reported ``SIMULATED`` per account even when the
        aggregate run reports ``FIXTURE`` or ``BANK_API`` for them, because
        this module never substitutes their VALUES.
        """
        if not self.enabled:
            return {f: "SIMULATED" for f in FAMILIES}
        covered = str(account_id) in self.fixture_by_account
        out: dict[str, str] = {}
        # identity is the only family this module actually overlays a value for
        agg = self.families.get("identity", "SIMULATED")
        out["identity"] = agg if (agg == "BANK_API" or covered) else "SIMULATED"
        for fam in ("exposure", "repayment", "cashflow", "bureau", "profile"):
            out[fam] = "SIMULATED"
        for fam in ALWAYS_SIMULATED:
            out[fam] = "SIMULATED"
        out["model"] = weakest([v for k, v in out.items() if k != "model"])
        return out

    def coverage(self) -> dict[str, int]:
        return dict(fixture_accounts=len(self.fixture_by_account))


def build_context(data_dir: Path | str, enabled: bool) -> BankContext:
    """The one entry point. ``enabled=False`` is the pre-DM-6 pipeline, untouched."""
    data_dir = Path(data_dir)
    bank_dir = data_dir / "bank"

    if not enabled:
        return BankContext(enabled=False, mode="simulated",
                           families={f: "SIMULATED" for f in FAMILIES},
                           reason="--bank not passed: the pipeline runs purely synthetic, "
                                  "exactly as it did in July 2026.")

    pulled = _load_json(bank_dir / PULLED_NAME)
    provenance_raw = _load_json(bank_dir / PROVENANCE_NAME)
    fixture = _load_json(bank_dir / FIXTURE_NAME)
    fixture_by_account = _fixture_by_account(fixture)

    families: dict[str, str] = {}
    if pulled is not None:
        answered = _answered_apis(pulled)
        for fam, apis in FAMILY_APIS.items():
            if any(a in answered for a in apis):
                families[fam] = "BANK_API"
            elif fixture_by_account:
                families[fam] = "FIXTURE"
            else:
                families[fam] = "SIMULATED"
        fell_back = sorted(f for f, s in families.items() if s == "FIXTURE")
        reason = (f"data/bank/pulled.json present; APIs answered: {sorted(answered) or 'none'}."
                  + (f" Families {', '.join(fell_back)} fell back to data/bank/fixture.json."
                     if fell_back else ""))
    elif fixture_by_account:
        for fam in FAMILY_APIS:
            families[fam] = "FIXTURE"
        reason = ("no data/bank/pulled.json: whole-fixture fallback from "
                  f"data/bank/fixture.json ({len(fixture_by_account)} of the panel's accounts "
                  "covered by account_id match; every other account stays SIMULATED for these "
                  "families — see BankContext.provenance_for).")
    else:
        for fam in FAMILY_APIS:
            families[fam] = "SIMULATED"
        reason = "no data/bank/pulled.json and no usable data/bank/fixture.json: fell all " \
                 "the way back to SIMULATED, same as --bank not being passed at all."

    for fam in ALWAYS_SIMULATED:
        families[fam] = "SIMULATED"
    families["model"] = weakest([v for k, v in families.items() if k != "model"])

    if pulled is not None:
        non_model = {v for k, v in families.items() if k != "model"}
        mode = "live" if non_model == {"BANK_API"} else ("mixed" if "BANK_API" in non_model else "fixture")
    else:
        mode = "fixture" if fixture_by_account else "simulated"

    return BankContext(enabled=True, mode=mode, families=families,
                       fixture_by_account=fixture_by_account, pulled=pulled,
                       provenance_raw=provenance_raw,
                       fixture_meta=(fixture or {}).get("_meta"), reason=reason)


__all__ = ["BankContext", "build_context", "weakest", "FAMILIES", "ALWAYS_SIMULATED",
           "FAMILY_APIS", "OVERLAY_FIELDS", "PULLED_NAME", "PROVENANCE_NAME", "FIXTURE_NAME"]

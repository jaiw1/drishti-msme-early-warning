"""Borrower taxonomy — the MSMED size segment and the legal constitution.

Two orthogonal ways of saying what kind of borrower this is, and the panel
carries both:

**Size segment** (Micro / Small / Medium) is derived from the sanctioned amount
exactly as the July 2026 simulator derived it, using the MSMED investment/
turnover ladder as the bank applies it to a limit.

**Constitution** is the legal form of the borrower — Individual,
Proprietorship, Partnership, PvtLtd, LLP.  It is the cut the mentors asked for
("one holistic model across all borrower types"), it is a pre-registered
validation cut (``validation/criteria.yaml``, five levels), and the platform
contract carries it on every account (``data/bank/SCHEMA.md``, API 456).
Spellings are the contract's: ``PvtLtd``, not "Pvt Ltd".

Why constitution is not just another categorical
------------------------------------------------
It decides what *exists* to be observed.  An Individual borrower files no GST
return, so a GST column for them is missing-because-impossible, not
missing-because-unavailable — the same distinction the enrichment contract
makes about nulls in ``enriched.csv``.  Portfolio-level absence
(:attr:`generator.portfolios.Portfolio.absent_channels`) handles the products
where nobody files; :func:`files_gst` is the per-borrower half, and it is the
hook SD-D4's MAR-missingness block uses inside the portfolios that do carry a
GST channel — LAP above all, where roughly two in five borrowers are
individuals.
"""

from __future__ import annotations

import numpy as np

from . import sources

__all__ = [
    "CONSTITUTION_WITHOUT_GST",
    "SEGMENTS",
    "SEGMENT_UPPER_BOUNDS",
    "constitution_levels",
    "files_gst",
    "segment_codes",
]

#: MSMED size segments, in ascending order of sanctioned amount
SEGMENTS: tuple[str, ...] = ("Micro", "Small", "Medium")

#: inclusive upper bound (rupees) of each segment except the last
SEGMENT_UPPER_BOUNDS: tuple[float, ...] = (1e6, 1e7)

#: constitutions that file no GST return, so have no GST turnover to observe
CONSTITUTION_WITHOUT_GST: frozenset[str] = frozenset({"Individual"})


def segment_codes(sanctioned: np.ndarray) -> np.ndarray:
    """Map sanctioned amounts to indices into :data:`SEGMENTS`.

    Args:
        sanctioned: ``(N,)`` sanctioned limit in rupees.

    Returns:
        ``(N,)`` int codes: 0 Micro (<= 10 lakh), 1 Small (<= 1 crore), 2 Medium.
    """
    codes = np.zeros(sanctioned.shape[0], dtype=np.int64)
    for bound in SEGMENT_UPPER_BOUNDS:
        codes += (sanctioned > bound).astype(np.int64)
    return codes


def constitution_levels() -> tuple[str, ...]:
    """The panel-wide ordered constitution universe.

    The shared mix's levels come first — which is what keeps the categorical
    codes stable when a portfolio is added — followed by any level a portfolio
    introduces on its own, in registry order.

    Returns:
        The ordered level names, e.g. ``("Individual", "Proprietorship", ...)``.
    """
    order: list[str] = list(sources.value("shared.constitutions"))
    for key in sources.portfolio_keys():
        for level in sources.portfolio_value(key, "constitutions"):
            if level not in order:
                order.append(level)
    return tuple(order)


def files_gst(constitution_code: np.ndarray, levels: tuple[str, ...]) -> np.ndarray:
    """Whether each borrower's legal form files a GST return at all.

    Args:
        constitution_code: ``(N,)`` codes into ``levels``.
        levels: the ordered constitution universe (:func:`constitution_levels`).

    Returns:
        ``(N,)`` boolean mask, ``False`` for the forms that file nothing.
    """
    filing = np.array(
        [level not in CONSTITUTION_WITHOUT_GST for level in levels], dtype=bool
    )
    return filing[constitution_code]

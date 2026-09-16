"""Borrower taxonomy — today only the MSMED size segment.

The panel's only borrower taxonomy right now is the RBI/MSMED **size
segment** (Micro / Small / Medium), derived from the sanctioned amount exactly
as the original simulator derived it.  That lives here rather than inline so
that the taxonomy has one home.

SD-D2 adds the real *constitution* axis — Proprietorship, Partnership, Private
Limited, LLP, Individual — which is the cut the mentors asked for ("one
holistic model across all borrower types").  It slots in beside the segment
logic: a ``CONSTITUTIONS`` registry mirroring
:data:`generator.portfolios.PORTFOLIOS`, a draw in
:func:`generator.latent.draw_population`, and a ``constitution`` column added
to the panel and to ``export_demo.CAT``.  Constitution also governs which
channels exist (an Individual borrower files no GST return), which is why
:class:`generator.portfolios.Portfolio` already carries ``absent_channels`` —
the two axes will intersect there.
"""

from __future__ import annotations

import numpy as np

__all__ = ["SEGMENTS", "SEGMENT_UPPER_BOUNDS", "segment_codes"]

#: MSMED size segments, in ascending order of sanctioned amount
SEGMENTS: tuple[str, ...] = ("Micro", "Small", "Medium")

#: inclusive upper bound (₹) of each segment except the last
SEGMENT_UPPER_BOUNDS: tuple[float, ...] = (1e6, 1e7)


def segment_codes(sanctioned: np.ndarray) -> np.ndarray:
    """Map sanctioned amounts to indices into :data:`SEGMENTS`.

    Args:
        sanctioned: ``(N,)`` sanctioned limit in rupees.

    Returns:
        ``(N,)`` int codes: 0 Micro (<= ₹10L), 1 Small (<= ₹1cr), 2 Medium.
    """
    codes = np.zeros(sanctioned.shape[0], dtype=np.int64)
    for bound in SEGMENT_UPPER_BOUNDS:
        codes += (sanctioned > bound).astype(np.int64)
    return codes

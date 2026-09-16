"""The generator has to be fast enough to tune against.

Tuning DRISHTi to ~15 pre-registered validation criteria across 9 cuts takes
15-20 regeneration rounds.  At the old row-by-row simulator's speed (~25 s for
today's population, and roughly 10-15 minutes at the 45,000 x 48 population
the validation work needs) a round costs hours; vectorised it costs minutes.
These budgets are what make that difference a contract rather than a hope.

Both budgets include writing the CSVs, because that is what a tuning round
actually pays for.  They are measured on the build machine (Apple M2); the
headroom is large — today's population runs in ~2 s against a 10 s budget and
the large one in ~17 s against 60 s — so they fail on a regression, not on a
slower laptop.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from generator import GeneratorConfig, generate
from generator.build import write

#: the vectorised maths must not silently overflow or divide by zero
pytestmark = pytest.mark.filterwarnings("error::RuntimeWarning")

#: seconds allowed for the current production population (9,000 x 36)
DEFAULT_BUDGET_SECONDS = 10.0

#: seconds allowed for the validation population (45,000 x 48)
LARGE_BUDGET_SECONDS = 60.0


def _time_generation(config: GeneratorConfig, outdir: Path) -> float:
    """Generate and write, returning wall-clock seconds."""
    start = time.perf_counter()
    write(*generate(config), outdir)
    return time.perf_counter() - start


def test_default_population_under_ten_seconds(tmp_path: Path) -> None:
    elapsed = _time_generation(GeneratorConfig(), tmp_path)
    assert elapsed < DEFAULT_BUDGET_SECONDS, (
        f"9,000 x 36 took {elapsed:.1f}s (budget {DEFAULT_BUDGET_SECONDS:.0f}s)"
    )


@pytest.mark.slow
def test_large_population_under_a_minute(tmp_path: Path) -> None:
    config = GeneratorConfig(n_accounts=45_000, months=48)
    elapsed = _time_generation(config, tmp_path)
    assert elapsed < LARGE_BUDGET_SECONDS, (
        f"45,000 x 48 took {elapsed:.1f}s (budget {LARGE_BUDGET_SECONDS:.0f}s)"
    )

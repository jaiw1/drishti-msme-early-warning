"""Test configuration for the synthetic-data generator.

Scoped to this directory on purpose: the repository has other lanes with their
own test trees (``validation/tests``), so nothing here is registered at the
repository root where it would change how their tests run.
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers these tests use."""
    config.addinivalue_line(
        "markers", "slow: long-running benchmark (deselect with -m 'not slow')"
    )

"""Test configuration for the synthetic-data generator.

Scoped to this directory on purpose: the repository has other lanes with their
own test trees (``validation/tests``), so nothing here is registered at the
repository root where it would change how their tests run.

The eight-portfolio panel is generated **once** per session and shared.  It is
large enough for a per-portfolio default rate to mean something (24,000
accounts over 48 months, roughly 1,700 accounts in the thinnest portfolio) and
still takes about two seconds, which is the whole point of the vectorised
generator.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

#: population used by the SD-D2 / SD-D3 suites
PANEL_ACCOUNTS = 24_000
PANEL_MONTHS = 48


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers these tests use."""
    config.addinivalue_line(
        "markers", "slow: long-running benchmark (deselect with -m 'not slow')"
    )


@pytest.fixture(scope="session")
def book() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The full eight-portfolio book: ``(panel, accounts)``.

    ``account_id`` is cast to ``str`` so the group-bys in the lead helpers
    behave the same way they do after a CSV round trip.
    """
    from generator import GeneratorConfig, generate

    panel, accounts = generate(
        GeneratorConfig(n_accounts=PANEL_ACCOUNTS, months=PANEL_MONTHS)
    )
    return panel.assign(account_id=panel.account_id.astype(str)), accounts


@pytest.fixture(scope="session")
def panel(book: tuple[pd.DataFrame, pd.DataFrame]) -> pd.DataFrame:
    """The eight-portfolio account-month panel."""
    return book[0]


@pytest.fixture(scope="session")
def accounts(book: tuple[pd.DataFrame, pd.DataFrame]) -> pd.DataFrame:
    """One row per account, with the latent fate the panel hides."""
    return book[1]

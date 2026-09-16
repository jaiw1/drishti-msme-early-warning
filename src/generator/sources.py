"""Sourced-parameter store — every population number, with its provenance.

``sources.yaml`` beside this module holds every *empirical* parameter the
generator uses: the portfolio mix, constitutions, ticket-size distributions,
geography, vintage, sector, tenor, rate bands and the per-portfolio default-rate
bands.  Each one is a **node**::

    value:        the number (or list, or mapping) the generator reads
    source:       who published it, in words a reviewer can check
    url:          where it can be read
    retrieved_on: the date we read it
    confidence:   high | medium | low | assumed

``assumed`` is a first-class, honest value: it means no public figure exists and
the number is our judgement.  :mod:`generator` never hard-codes an empirical
number — if it is about the Indian lending market, it lives in the YAML and is
read through this module.  Pure *model-shape* constants (AR(1) φ, the stress
ramp split, elasticities) stay in :mod:`generator.portfolios` because they
describe the simulation, not the market, and no source could ever back them.

Resolution order
----------------
:func:`portfolio_value` looks in ``portfolios.<key>.<path>`` first and falls
back to ``shared.<path>``, so a portfolio declares only what makes it different.
"""

from __future__ import annotations

import datetime as _dt
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import yaml

__all__ = [
    "CONFIDENCE_LEVELS",
    "NODE_KEYS",
    "NO_URL",
    "SOURCES_PATH",
    "iter_nodes",
    "load",
    "portfolio_keys",
    "portfolio_value",
    "value",
]

SOURCES_PATH = Path(__file__).with_name("sources.yaml")

#: the four provenance keys every parameter node carries beside ``value``
NODE_KEYS: frozenset[str] = frozenset({"source", "url", "retrieved_on", "confidence"})

#: the only confidence levels a node may declare
CONFIDENCE_LEVELS: frozenset[str] = frozenset({"high", "medium", "low", "assumed"})

#: the ``url`` an ``assumed`` node carries, and the only node kind that may.
#: Enforced both ways by :func:`validate`: an assumption cannot hide behind a
#: decorative link, and a sourced number cannot be published without one.
NO_URL = "none"


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """Parse ``sources.yaml`` once and cache it.

    Returns:
        The raw document.
    """
    with SOURCES_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _walk(node: Any, path: str) -> Iterator[tuple[str, dict]]:
    """Yield every ``(dotted path, node)`` pair under ``node``."""
    if isinstance(node, dict):
        if "value" in node:
            yield path, node
            return
        for key, child in node.items():
            yield from _walk(child, f"{path}.{key}" if path else str(key))


def iter_nodes() -> Iterator[tuple[str, dict]]:
    """Every parameter node in the document, with its dotted path.

    A node is any mapping carrying a ``value`` key; everything above it is a
    grouping.  Used by the generator to read parameters and by the schema test
    to prove that every leaf carries its provenance.
    """
    yield from _walk(load(), "")


def _resolve(path: str) -> dict:
    """The node at a dotted path, or raise with the path that failed."""
    node: Any = load()
    walked: list[str] = []
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"sources.yaml has no {'.'.join(walked + [part])!r}")
        walked.append(part)
        node = node[part]
    if not isinstance(node, dict) or "value" not in node:
        raise KeyError(f"sources.yaml: {path!r} is a grouping, not a parameter")
    return node


def value(path: str) -> Any:
    """The ``value`` of the parameter at a dotted path.

    Args:
        path: e.g. ``"shared.bureau.missing_share"``.

    Returns:
        Whatever the node's ``value`` holds.

    Raises:
        KeyError: if the path is missing or names a grouping.
    """
    return _resolve(path)["value"]


def portfolio_value(key: str, path: str) -> Any:
    """A portfolio's parameter, falling back to the shared default.

    Args:
        key: portfolio registry key, e.g. ``"housing"``.
        path: dotted path *relative to the portfolio*, e.g. ``"ticket.log_mean"``.

    Returns:
        ``portfolios.<key>.<path>`` if present, otherwise ``shared.<path>``.
    """
    try:
        return value(f"portfolios.{key}.{path}")
    except KeyError:
        return value(f"shared.{path}")


def portfolio_keys() -> list[str]:
    """Registry keys, in the order ``sources.yaml`` declares them."""
    return list(load()["portfolios"])


def validate() -> list[str]:
    """Structural problems with the document, as human-readable strings.

    Checked here rather than only in the test suite so a malformed edit fails
    the generator loudly instead of silently changing the population.

    Returns:
        An empty list when the document is well formed.
    """
    problems: list[str] = []
    for path, node in iter_nodes():
        missing = NODE_KEYS - set(node)
        if missing:
            problems.append(f"{path}: missing {sorted(missing)}")
        extra = set(node) - NODE_KEYS - {"value", "note"}
        if extra:
            problems.append(f"{path}: unexpected keys {sorted(extra)}")
        if node.get("confidence") not in CONFIDENCE_LEVELS:
            problems.append(f"{path}: confidence {node.get('confidence')!r} is not one of "
                            f"{sorted(CONFIDENCE_LEVELS)}")
        retrieved = node.get("retrieved_on")
        if not isinstance(retrieved, (_dt.date, str)) or not str(retrieved):
            problems.append(f"{path}: retrieved_on must be a date")
        for key in ("source", "url"):
            if not isinstance(node.get(key), str) or not node[key].strip():
                problems.append(f"{path}: {key} must be a non-empty string")
        # An assumption may not hide behind a decorative link, and a sourced
        # number may not be published without one.
        assumed = node.get("confidence") == "assumed"
        unlinked = node.get("url") == NO_URL
        if assumed != unlinked:
            problems.append(
                f"{path}: confidence={node.get('confidence')!r} with url={node.get('url')!r} — "
                f"exactly the 'assumed' nodes carry url {NO_URL!r}"
            )
    return problems

"""Session-wide pytest configuration.

Its one job is to record what pytest *actually collected*, so that
``tests/test_protocol_triad.py`` can assert the Protocol-triad rule against the
real collection rather than against files that merely exist. A conformance
suite bound to a fake by a class pytest never collects runs zero assertions —
that is precisely the failure mode a file-existence check cannot see, so the
evidence has to come from pytest itself.

``pytest_collection_modifyitems`` is the earliest hook with the complete item
list, and collection finishes before any test runs, so the record is always
whole by the time a test reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

# Options that narrow collection. If any is in play the recorded set is a
# subset of the suite, and absence of a class proves nothing.
_FILTERING_OPTIONS = ("keyword", "markexpr", "deselect", "lf", "failedfirst")


@dataclass
class _CollectionRecord:
    """What this pytest session collected, and whether that was the whole suite."""

    classes: frozenset[type] = field(default_factory=frozenset)
    unfiltered: bool = False


_RECORD = _CollectionRecord()


def _is_unfiltered(config: pytest.Config) -> bool:
    """Report whether this session collected the entire configured suite."""
    if any(config.getoption(option, default=None) for option in _FILTERING_OPTIONS):
        return False
    testpaths: Sequence[str] = config.getini("testpaths")
    wanted = [str(config.rootpath / path) for path in testpaths]
    given = [str(config.rootpath / arg) for arg in config.args]
    return given == wanted


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Record the test classes pytest collected for this session."""
    _RECORD.classes = frozenset(
        cls for item in items if (cls := getattr(item, "cls", None)) is not None
    )
    _RECORD.unfiltered = _is_unfiltered(config)


@pytest.fixture(scope="session")
def collected_test_classes() -> frozenset[type]:
    """Every test class pytest collected in this session."""
    return _RECORD.classes


@pytest.fixture(scope="session")
def collection_is_unfiltered() -> bool:
    """Whether this session collected the whole suite (no ``-k``, no path args)."""
    return _RECORD.unfiltered

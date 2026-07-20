"""Session-wide pytest configuration.

Its one job is to record which tests actually **ran and passed**, so that
``tests/core/test_protocol_triad.py`` can assert the Protocol-triad rule
against real executed assertions rather than against files that merely exist.
A conformance suite bound to a fake by a class pytest never collects runs zero
assertions; so does one whose tests are all collected and then skipped. Neither
is visible to a file-existence check, so the evidence has to come from pytest
itself.

Collection alone is not enough for the same reason, which is why the record is
built from call-phase reports and the triad check is reordered to run last --
it is the only test in the suite whose subject is the rest of the suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

# Options that narrow what is collected or run. If any is in play the record is
# a subset of the suite, and the absence of a class proves nothing. `maxfail`
# covers `-x`, which stops the run before later tests report.
_FILTERING_OPTIONS = ("keyword", "markexpr", "deselect", "lf", "failedfirst", "maxfail")

#: The check whose subject is every other test, so it has to run after them.
_TRIAD_CHECK = "tests/core/test_protocol_triad.py"


@dataclass
class _RunRecord:
    """What this pytest session actually ran, and whether that was the whole suite."""

    #: Test class -> names of the tests on it that ran and passed. The names
    #: matter as well as the class: they are what shows a conformance suite
    #: contributed assertions that really executed, rather than merely being
    #: inherited from, overridden, or skipped.
    class_tests: dict[type, set[str]] = field(default_factory=dict)
    #: Test class -> names of the tests on it that the test body itself opted
    #: out of, by calling ``pytest.skip()``. That is a contract deciding an
    #: obligation does not apply to this implementation, which is legitimate;
    #: it is tracked so the triad check can tell it apart from an obligation
    #: that simply never ran.
    opted_out_tests: dict[type, set[str]] = field(default_factory=dict)
    unfiltered: bool = False


_RECORD = _RunRecord()

#: nodeid -> (owning class, test name), so a report can be attributed without
#: the report itself carrying the class.
_OWNERS: dict[str, tuple[type, str]] = {}


def _is_unfiltered(config: pytest.Config) -> bool:
    """Report whether this session is running the entire configured suite."""
    if any(config.getoption(option, default=None) for option in _FILTERING_OPTIONS):
        return False
    testpaths: Sequence[str] = config.getini("testpaths")
    wanted = [str(config.rootpath / path) for path in testpaths]
    given = [str(config.rootpath / arg) for arg in config.args]
    return given == wanted


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Attribute each item to its class, and defer the triad check to the end."""
    _RECORD.unfiltered = _is_unfiltered(config)
    _OWNERS.clear()
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is not None:
            _OWNERS[item.nodeid] = (cls, getattr(item, "originalname", None) or item.name)

    deferred = [item for item in items if item.nodeid.startswith(_TRIAD_CHECK)]
    if deferred:
        items[:] = [item for item in items if not item.nodeid.startswith(_TRIAD_CHECK)] + deferred


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record whether each test passed its call phase, or was skipped."""
    owner = _OWNERS.get(report.nodeid)
    if owner is None:
        return
    cls, name = owner
    # `wasxfail` marks an xfail, which also reports as skipped at the call
    # phase. An expected *failure* is a contract assertion that did not hold --
    # the opposite of an obligation being honoured -- so it is recorded nowhere.
    if report.skipped and report.when == "call" and not hasattr(report, "wasxfail"):
        # The body ran and chose to bow out -- see ContextProviderContract's
        # `serves_a_fixed_instant`. A *mark* skips at setup instead, before the
        # body runs; that is imposed from outside the contract and is recorded
        # nowhere, so the triad check sees the obligation as simply not met.
        _RECORD.opted_out_tests.setdefault(cls, set()).add(name)
    elif report.when == "call" and report.passed:
        _RECORD.class_tests.setdefault(cls, set()).add(name)


@pytest.fixture(scope="session")
def passing_class_tests() -> dict[type, frozenset[str]]:
    """Every test class, mapped to the tests on it that ran and passed."""
    return {cls: frozenset(names) for cls, names in _RECORD.class_tests.items()}


@pytest.fixture(scope="session")
def opted_out_class_tests() -> dict[type, frozenset[str]]:
    """Every test class, mapped to the tests whose own body skipped them."""
    return {cls: frozenset(names) for cls, names in _RECORD.opted_out_tests.items()}


@pytest.fixture(scope="session")
def run_is_unfiltered() -> bool:
    """Whether this session runs the whole suite (no ``-k``, no ``-x``, no path args)."""
    return _RECORD.unfiltered

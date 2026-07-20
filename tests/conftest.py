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
# covers `-x`, which stops the run before later tests report; `ignore` and
# `ignore_glob` drop whole paths while leaving `config.args` looking complete.
_FILTERING_OPTIONS = (
    "keyword",
    "markexpr",
    "deselect",
    "lf",
    "failedfirst",
    "maxfail",
    "ignore",
    "ignore_glob",
)

#: The check whose subject is every other test, so it has to run after them.
_TRIAD_CHECK = "tests/core/test_protocol_triad.py"


@dataclass
class _RunRecord:
    """What this pytest session actually ran, and whether that was the whole suite."""

    #: Test class -> names of the tests on it with at least one satisfactory
    #: call-phase report.
    reported: dict[type, set[str]] = field(default_factory=dict)
    #: Test class -> names of the tests on it with at least one *un*satisfactory
    #: report. Tracked separately from `reported` because a parametrized test
    #: reports once per case under a single name: if any case failed, was
    #: xfailed, or was skipped by a mark, the obligation is not honoured however
    #: many sibling cases passed.
    unsatisfactory: dict[type, set[str]] = field(default_factory=dict)
    unfiltered: bool = False

    def honoured(self) -> dict[type, frozenset[str]]:
        """Return, per class, the tests whose every reported case was satisfactory."""
        return {
            cls: frozenset(names - self.unsatisfactory.get(cls, set()))
            for cls, names in self.reported.items()
        }


_RECORD = _RunRecord()

#: nodeid -> (owning class, test name, is-an-optional-obligation), so a report
#: can be attributed without the report itself carrying any of it.
_OWNERS: dict[str, tuple[type, str, bool]] = {}

#: Marker a conformance suite puts on a test its implementations may skip.
_OPTIONAL = "optional_obligation"


def _declares_optional(func: object) -> bool:
    """Report whether the *test function itself* is marked an optional obligation.

    Read off the function rather than through ``item.get_closest_marker``,
    which would also honour the mark applied to a subclass or a whole module.
    Only the conformance suite gets to say which of its obligations are
    optional; a binding class declaring its inherited tests optional and then
    skipping them all is precisely the bypass this guards.
    """
    return any(mark.name == _OPTIONAL for mark in getattr(func, "pytestmark", []))


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
            _OWNERS[item.nodeid] = (
                cls,
                getattr(item, "originalname", None) or item.name,
                _declares_optional(getattr(item, "function", None)),
            )

    deferred = [item for item in items if item.nodeid.startswith(_TRIAD_CHECK)]
    if deferred:
        items[:] = [item for item in items if not item.nodeid.startswith(_TRIAD_CHECK)] + deferred


def _is_satisfactory(report: pytest.TestReport, *, optional: bool) -> bool:
    """Report whether one phase report is consistent with an obligation being met.

    Only a call-phase pass is evidence that a contract's assertions ran. A skip
    counts *only* where the suite itself marked the test ``optional_obligation``
    and the test's own body then chose to bow out -- see
    ``ContextProviderContract``'s ``serves_a_fixed_instant``, an obligation that
    genuinely does not apply to a provider serving a fixed instant.

    Any other skip is an obligation that did not happen, whatever its cause: a
    ``pytest.skip("not implemented")`` in an unmarked contract test, or a mark
    imposing a skip at setup before the body ever runs.

    ``wasxfail`` is never satisfactory: an expected failure is a contract
    assertion that did not hold, kept green by the mark.
    """
    if hasattr(report, "wasxfail"):
        return False
    if report.when == "call":
        return bool(report.passed or (report.skipped and optional))
    return not (report.skipped or report.failed)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record how each reported phase of each test turned out."""
    owner = _OWNERS.get(report.nodeid)
    if owner is None:
        return
    cls, name, optional = owner
    if not _is_satisfactory(report, optional=optional):
        _RECORD.unsatisfactory.setdefault(cls, set()).add(name)
    elif report.when == "call":
        _RECORD.reported.setdefault(cls, set()).add(name)


@pytest.fixture(scope="session")
def honoured_class_tests() -> dict[type, frozenset[str]]:
    """Every test class, mapped to the tests on it whose every case was honoured."""
    return _RECORD.honoured()


@pytest.fixture(scope="session")
def run_is_unfiltered() -> bool:
    """Whether this session runs the whole suite (no ``-k``, no ``-x``, no path args)."""
    return _RECORD.unfiltered

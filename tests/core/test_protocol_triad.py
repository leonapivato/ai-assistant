"""Mechanical enforcement of the Protocol triad rule.

``CONTRIBUTING.md`` -> "Adding a Protocol: land the triad together" makes three
artifacts one unit of work for every Protocol in ``core/protocols.py``:

1. a shared ``<Protocol>Contract`` conformance suite under ``tests/``,
2. a canonical ``Fake<Protocol>`` exported from ``ai_assistant.testing``, and
3. a ``Test...Contract`` subclass binding the two, whose contract tests
   pytest **actually ran and passed** -- the abstract suite collects nothing
   on its own, so without the subclass the fake is unverified however many
   files exist.

Until now that rule was held by review alone: a Protocol could land with no
suite and no fake and pass the entire gate, which is how the original backfill
debt accumulated. This is the same class of gap ADR-0015 names -- an invariant
held by prose rather than mechanism.

Part 3 is why this lives in pytest rather than in a standalone script. "Did the
suite's assertions run against the fake?" is a question only pytest can answer;
a script would have to re-run pytest to ask it. ``tests/conftest.py`` records
the outcomes and defers this module to the end of the run so it can read them.
Living here it also inherits the gate and CI for free (``uv run pytest``
already runs in both), and fails as an ordinary test failure naming exactly
what is missing.

The predicates below are deliberately strict about *evidence*: a file, a name,
or a lexical mention is never enough, because each of those was a way past an
earlier draft of this check (see the negative tests at the bottom).

Conventions the check relies on (all eight Protocols already follow them):
suite ``<Protocol>Contract``, fake ``Fake<Protocol>``. A Protocol that wants
different names should change this check, deliberately, in the same PR.
"""

from __future__ import annotations

import ast
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType
from typing import TYPE_CHECKING, Final, is_protocol

import pytest

import ai_assistant.testing as testing_pkg
from ai_assistant.core import protocols as protocols_module
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: Test class -> the tests on it that ran and passed (see tests/conftest.py).
type CollectedTests = dict[type, frozenset[str]]

_TESTS_ROOT: Final = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Exemptions -- this list is the backlog, and it should only ever shrink.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriadExemption:
    """A Protocol allowed, for now, to ship without its full triad.

    Attributes:
        protocol: Name of the Protocol in ``core/protocols.py``.
        missing: The triad parts absent today, from ``TRIAD_PARTS``.
        issue: URL of the GitHub issue tracking the backfill.
        note: Why the gap exists, in one line.
    """

    protocol: str
    missing: tuple[str, ...]
    issue: str
    note: str


TRIAD_PARTS: Final = ("suite", "fake", "binding")

#: Debt, not configuration. Every entry is a Protocol whose triad is
#: incomplete: the check reports what is missing and where it is tracked, and
#: refuses to let an entry outlive the gap it describes (see
#: ``test_no_exemption_is_stale``). Adding an entry is how you record a
#: backfill you are not doing; it is not a way to skip the rule for new work.
EXEMPTIONS: Final = (
    TriadExemption(
        protocol="FeedbackProcessor",
        missing=("fake", "binding"),
        issue="https://github.com/leonapivato/ai-assistant/issues/46",
        note=(
            "Predates the triad rule. FeedbackProcessorContract exists and "
            "RuleBasedFeedbackProcessor runs through it, but there is no "
            "canonical FakeFeedbackProcessor in ai_assistant.testing, so "
            "consumers hand-roll a mock."
        ),
    ),
)

#: The debt that existed when this check landed, and the *only* Protocols an
#: exemption may ever name. Without this the list would be an escape hatch:
#: a new Protocol could ship with an exemption for all three parts and a green
#: gate -- exactly what this check exists to prevent. It is a closed set, so
#: the list can only shrink. Removing a name is how a backfill finishes;
#: adding one is not a normal operation and should not survive review.
_LEGACY_DEBT: Final = frozenset({"FeedbackProcessor"})

_EXEMPT_BY_PROTOCOL: Final = {exemption.protocol: exemption for exemption in EXEMPTIONS}

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _protocol_names() -> list[str]:
    """Return every Protocol declared in ``core/protocols.py``."""
    return sorted(
        name
        for name, obj in vars(protocols_module).items()
        if isinstance(obj, type)
        and is_protocol(obj)
        and obj.__module__ == protocols_module.__name__
    )


def _declared_class_names() -> set[str]:
    """Return every class name defined anywhere under ``tests/``.

    Parsed rather than imported: the conformance suites are plain modules that
    pytest puts on ``sys.path`` per directory, and importing them here purely
    to look at their names would be a needless side effect.
    """
    names: set[str] = set()
    for path in _TESTS_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names.update(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    return names


def _canonical_fake(protocol: str) -> type | None:
    """Return the canonical fake exported for ``protocol``, if there is one."""
    fake = getattr(testing_pkg, f"Fake{protocol}", None)
    if not isinstance(fake, type) or f"Fake{protocol}" not in testing_pkg.__all__:
        return None
    return fake


def _own_fixtures(cls: type) -> dict[str, Callable[..., object]]:
    """Return the fixtures ``cls`` itself defines, by name, unwrapped."""
    return {
        name: raw
        for name, value in vars(cls).items()
        if isinstance(raw := getattr(value, "__wrapped__", None), FunctionType)
        and hasattr(value, "_fixture_function_marker")
    }


def _fixtures_requested_by(suite: type, test_names: Iterable[str]) -> set[str]:
    """Return the fixture names the suite's own tests take as parameters.

    This is what makes the binding check target the *subject* fixture rather
    than any fixture on the class. A decoy -- a real implementation supplied
    through `store` plus an unused fixture that returns the fake -- does not
    put the fake in front of a single contract assertion, and must not count.
    """
    requested: set[str] = set()
    for name in test_names:
        func = getattr(suite, name, None)
        if callable(func):
            requested.update(p for p in inspect.signature(func).parameters if p != "self")
    return requested


def _fixture_yields(func: Callable[..., object], fake: type) -> bool:
    """Report whether calling ``func`` with only ``self`` produces a ``fake``.

    Evaluation, not inspection, is the whole point: only running the fixture
    shows what the conformance suite is actually handed. A lexical check --
    "the fixture body mentions the fake somewhere" -- is satisfied by a
    docstring, an unused import, or a constructor call in a branch that never
    runs, none of which put the fake in front of a single assertion.

    A subject fixture that needs other fixtures to build its subject cannot be
    evaluated here and so cannot be proven; that is a deliberate false
    negative. It surfaces as a loud, fixable gate failure rather than a silent
    hole, and no canonical fake needs one today.
    """
    if list(inspect.signature(func).parameters) != ["self"]:
        return False
    try:
        # A subject fixture builds its subject and ignores `self`; one that
        # does use it is simply unproven, per the docstring above.
        produced = func(None)
        if inspect.isgenerator(produced):
            produced = next(produced)
    except Exception:  # an unevaluable fixture is unproven here, not a failure
        return False
    return isinstance(produced, fake)


def _binds_fake(cls: type, protocol: str, subject_fixtures: set[str]) -> bool:
    """Report whether ``cls`` supplies the canonical fake to its conformance suite.

    Both conditions are object identity rather than text: the test module
    imported the canonical fake itself (not a same-named local stand-in), and
    one of the fixtures the suite's tests actually *request* evaluates to an
    instance of it. A mention of the fake in a docstring, an unused import, a
    constructor call on a dead branch, or a decoy fixture no contract test
    consumes is not a binding.
    """
    fake_name = f"Fake{protocol}"
    canonical = _canonical_fake(protocol)
    if canonical is None:
        return False
    fake: type = canonical
    module = sys.modules.get(cls.__module__)
    if getattr(module, fake_name, None) is not fake:
        return False
    supplied = {name: func for name, func in _own_fixtures(cls).items() if name in subject_fixtures}
    # `all`, not `any`: a class that hands the suite a real implementation
    # through one requested fixture and the fake through another has not put
    # the fake under test, whichever one the assertions happen to use.
    return bool(supplied) and all(_fixture_yields(func, fake) for func in supplied.values())


def _suite_of(cls: type, protocol: str) -> type | None:
    """Return the conformance suite ``cls`` inherits for ``protocol``, if any."""
    return next((base for base in cls.__mro__[1:] if base.__name__ == f"{protocol}Contract"), None)


def _suite_declared_tests(suite: type) -> set[str]:
    """Return every test the conformance suite itself declares."""
    return {
        name
        for name in dir(suite)
        if name.startswith("test_") and callable(getattr(suite, name, None))
    }


def _ran_every_obligation(
    cls: type, suite: type, passed: frozenset[str], opted_out: frozenset[str]
) -> bool:
    """Report whether ``cls`` honoured every test ``suite`` declares.

    Enumerating from the suite rather than from what got reported is what makes
    this exhaustive. A test the subclass suppressed -- overridden with a no-op,
    rebound to ``None``, hidden behind ``__test__ = False``, or skipped by a
    mark -- produces no passing report at all, so a check that only inspects
    reports cannot notice the obligation went missing.

    An obligation is honoured when it still resolves to the suite's own
    function object *and* it either passed or the suite's own body opted out
    of it.
    """
    for name in _suite_declared_tests(suite):
        if getattr(cls, name, None) is not getattr(suite, name):
            return False
        if name not in passed and name not in opted_out:
            return False
    return True


def _binding_classes(
    protocol: str, passing: CollectedTests, opted_out: CollectedTests
) -> list[type]:
    """Return the classes that really ran the canonical fake through the suite.

    Every condition closes a way of satisfying the letter of the triad while
    testing nothing:

    - the suite must declare tests at all, which an empty ``…Contract``
      does not;
    - every one of them must have been honoured (see
      ``_ran_every_obligation``), so neither overriding nor suppressing nor
      mark-skipping part of the contract counts, and one passing test cannot
      vouch for nine that never ran; and
    - the fake must arrive through *every* fixture the suite's tests request
      and the class supplies, so a real implementation cannot ride along
      beside it in a second fixture.
    """
    found = []
    for cls, passed in passing.items():
        suite = _suite_of(cls, protocol)
        if suite is None:
            continue
        obligations = _suite_declared_tests(suite)
        if not obligations:
            continue
        if not _ran_every_obligation(cls, suite, passed, opted_out.get(cls, frozenset())):
            continue
        if _binds_fake(cls, protocol, _fixtures_requested_by(suite, obligations)):
            found.append(cls)
    return found


def _missing_parts(
    protocol: str,
    declared: set[str],
    passing: CollectedTests | None,
    opted_out: CollectedTests | None = None,
) -> tuple[str, ...]:
    """Return the triad parts ``protocol`` is missing.

    ``passing`` may be ``None`` to check only the statically visible parts.
    """
    missing = []
    if f"{protocol}Contract" not in declared:
        missing.append("suite")
    if _canonical_fake(protocol) is None:
        missing.append("fake")
    if passing is not None and not _binding_classes(protocol, passing, opted_out or {}):
        missing.append("binding")
    return tuple(missing)


def _unexcused(protocol: str, missing: tuple[str, ...]) -> tuple[str, ...]:
    """Drop the gaps an exemption already accounts for."""
    exemption = _EXEMPT_BY_PROTOCOL.get(protocol)
    excused = set(exemption.missing) if exemption else set()
    return tuple(part for part in missing if part not in excused)


def _describe(protocol: str, missing: tuple[str, ...]) -> str:
    """Render one failure line, naming the artifact each missing part wants."""
    wants = {
        "suite": f"a shared `{protocol}Contract` conformance suite under tests/",
        "fake": f"a canonical `Fake{protocol}` exported from ai_assistant.testing",
        "binding": (
            f"a `Test...Contract` subclass of `{protocol}Contract` whose subject "
            f"fixture supplies `Fake{protocol}`, and whose inherited contract "
            f"tests actually ran and passed (not skipped, not overridden, and "
            f"not inherited from an empty suite)"
        ),
    }
    return f"{protocol} is missing:\n" + "\n".join(f"    - {wants[part]}" for part in missing)


_TRIAD_RULE: Final = (
    "See CONTRIBUTING.md -> 'Adding a Protocol: land the triad together'. "
    "The triad is one unit of work with the Protocol, not a follow-up. If a "
    "backfill genuinely cannot happen now, add a TriadExemption in this file "
    "with the issue tracking it."
)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def test_every_protocol_has_a_conformance_suite_and_canonical_fake() -> None:
    """Parts 1 and 2 of the triad exist for every Protocol."""
    declared = _declared_class_names()

    failures = [
        _describe(protocol, gaps)
        for protocol in _protocol_names()
        if (gaps := _unexcused(protocol, _missing_parts(protocol, declared, passing=None)))
    ]

    assert not failures, "\n".join([*failures, "", _TRIAD_RULE])


def test_every_protocols_fake_is_bound_by_a_contract_subclass_that_ran(
    passing_class_tests: CollectedTests,
    opted_out_class_tests: CollectedTests,
    run_is_unfiltered: bool,
) -> None:
    """Part 3: a subclass really ran each fake through its suite, and passed.

    This is the part a file-existence check cannot make. The abstract suite
    collects nothing, so only the binding subclass turns the contract into
    assertions -- and only executing them turns those assertions into evidence.
    """
    if not run_is_unfiltered:
        pytest.skip(
            "the run was narrowed (-k, -m, -x, or a path/nodeid argument), so an "
            "absent binding class proves nothing; the gate runs the full suite"
        )
    declared = _declared_class_names()

    failures = [
        _describe(protocol, gaps)
        for protocol in _protocol_names()
        if (
            gaps := _unexcused(
                protocol,
                _missing_parts(protocol, declared, passing_class_tests, opted_out_class_tests),
            )
        )
    ]

    assert not failures, "\n".join([*failures, "", _TRIAD_RULE])


def test_no_exemption_is_stale(
    passing_class_tests: CollectedTests,
    opted_out_class_tests: CollectedTests,
    run_is_unfiltered: bool,
) -> None:
    """An exemption dies with the gap it describes, so the backlog only shrinks."""
    if not run_is_unfiltered:
        pytest.skip("needs a full collection to tell a closed gap from a filtered one")
    declared = _declared_class_names()
    known = set(_protocol_names())

    failures = []
    for exemption in EXEMPTIONS:
        if exemption.protocol not in known:
            failures.append(
                f"{exemption.protocol} is exempted but no longer exists in "
                f"core/protocols.py -- drop the entry ({exemption.issue})"
            )
            continue
        gaps = set(
            _missing_parts(exemption.protocol, declared, passing_class_tests, opted_out_class_tests)
        )
        if closed := set(exemption.missing) - gaps:
            failures.append(
                f"{exemption.protocol} is exempted for {sorted(closed)} but that "
                f"part now exists -- remove it from the exemption and close "
                f"{exemption.issue}"
            )

    assert not failures, "\n".join(failures)


def test_no_new_protocol_can_be_exempted() -> None:
    """The exemption list is closed: it can shrink, never grow.

    An open list would be a bypass -- add a Protocol and an exemption for all
    three parts in one commit and the gate stays green, which is the failure
    this whole check exists to stop.
    """
    added = {exemption.protocol for exemption in EXEMPTIONS} - _LEGACY_DEBT

    assert not added, (
        f"{sorted(added)} cannot be exempted: EXEMPTIONS may only name the "
        f"pre-existing debt in _LEGACY_DEBT. A new or changed Protocol ships "
        f"its full triad in the same change (CONTRIBUTING.md)."
    )


def test_exemptions_are_well_formed() -> None:
    """Each entry names real triad parts and points at a tracking issue."""
    assert len(_EXEMPT_BY_PROTOCOL) == len(EXEMPTIONS), "duplicate protocol in EXEMPTIONS"
    for exemption in EXEMPTIONS:
        assert exemption.missing, f"{exemption.protocol}: an exemption must name a gap"
        assert set(exemption.missing) <= set(TRIAD_PARTS), (
            f"{exemption.protocol}: unknown triad part in {exemption.missing}"
        )
        assert exemption.issue.startswith("https://github.com/"), (
            f"{exemption.protocol}: exemptions must reference a tracking issue"
        )
        assert exemption.note.strip(), f"{exemption.protocol}: say why the gap exists"


def test_check_discovers_the_protocols_it_is_meant_to_guard() -> None:
    """Guard the discovery step itself: a check that finds nothing passes vacuously."""
    found = _protocol_names()

    assert len(found) >= 8, f"expected core/protocols.py to declare Protocols, found {found}"
    assert "MemoryStore" in found


def test_a_protocol_without_its_triad_is_reported() -> None:
    """The check fails on a Protocol with nothing behind it -- not vacuously true."""
    missing = _missing_parts("NonexistentThing", declared=set(), passing={})

    assert missing == TRIAD_PARTS
    assert "NonexistentThing" in _describe("NonexistentThing", missing)


# ---------------------------------------------------------------------------
# The check's own false-positive paths (adversarial review of this change).
# These classes are deliberately not `Test`-prefixed: pytest must not collect
# them, they exist only as input to the predicates above.
# ---------------------------------------------------------------------------


class _MentionsTheFakeWithoutBindingIt:
    """A class that names FakeMemoryStore in prose but never builds one."""

    @pytest.fixture
    def store(self) -> object:
        """Return something that is emphatically not a FakeMemoryStore."""
        return object()


class _ReallyBindsTheFake:
    @pytest.fixture
    def store(self) -> object:
        return FakeMemoryStore()


#: Always false. A literal `if False:` is dead code mypy and ruff would reject,
#: but the point of `_ConstructsTheFakeOnADeadBranch` is a constructor call the
#: fixture never reaches.
_NEVER: Final = bool(EXEMPTIONS) and not EXEMPTIONS


class _ConstructsTheFakeOnADeadBranch:
    @pytest.fixture
    def store(self) -> object:
        if _NEVER:
            return FakeMemoryStore()
        return object()


class _EmptySuite:
    """A conformance suite in name only -- it asserts nothing."""


# Renamed rather than declared as `MemoryStoreContract`, so the literal name
# does not leak into `_declared_class_names()` and satisfy the suite check.
_EmptySuite.__name__ = "MemoryStoreContract"


class _BoundToAnEmptySuite(_EmptySuite):
    @pytest.fixture
    def store(self) -> object:
        return FakeMemoryStore()

    def test_something_of_its_own(self) -> None: ...


class _DecoyFixture:
    """Supplies a non-fake through the subject fixture, the fake through a decoy."""

    @pytest.fixture
    def store(self) -> object:
        return object()

    @pytest.fixture
    def unused_probe(self) -> object:
        return FakeMemoryStore()


def test_naming_the_fake_without_constructing_it_is_not_a_binding() -> None:
    """A docstring mention, a type annotation, or a stray import proves nothing."""
    assert not _binds_fake(_MentionsTheFakeWithoutBindingIt, "MemoryStore", {"store"})


def test_constructing_the_fake_on_a_dead_branch_is_not_a_binding() -> None:
    """The fixture is evaluated, so an unreachable constructor call proves nothing."""
    assert not _binds_fake(_ConstructsTheFakeOnADeadBranch, "MemoryStore", {"store"})


def test_a_fixture_no_contract_test_requests_is_not_a_binding() -> None:
    """Only the fixture the suite's tests consume can put the fake under test."""
    assert not _binds_fake(_DecoyFixture, "MemoryStore", {"store"})


def test_a_fixture_that_returns_the_fake_is_a_binding() -> None:
    """The positive half of the same predicate, so it is not failing for free."""
    assert _binds_fake(_ReallyBindsTheFake, "MemoryStore", {"store"})


def test_an_empty_suite_does_not_count_as_a_conformance_suite() -> None:
    """A `…Contract` class contributing no tests of its own binds nothing.

    Otherwise `class WidgetContract: pass` plus one token test would satisfy
    the whole check while testing no Protocol behaviour at all.
    """
    passing: CollectedTests = {_BoundToAnEmptySuite: frozenset({"test_something_of_its_own"})}

    assert _binding_classes("MemoryStore", passing, {}) == []


def test_a_suite_whose_tests_ran_does_count() -> None:
    """The positive case: both suite tests ran on the binding class."""
    suite, bound = _suite_and_binding(overridden=())
    passing: CollectedTests = {bound: frozenset({"test_one", "test_two"})}

    assert suite.__name__ == "MemoryStoreContract"
    assert _binding_classes("MemoryStore", passing, {}) == [bound]


@pytest.mark.parametrize(
    ("overridden", "label"),
    [(("test_one", "test_two"), "every suite test"), (("test_two",), "one suite test")],
)
def test_overriding_a_suite_test_does_not_count_as_running_the_suite(
    overridden: tuple[str, ...], label: str
) -> None:
    """A no-op override runs under the suite's name but runs none of its assertions.

    Partial override matters as much as total: inheriting one test of ten and
    replacing the rest would otherwise pass while nine obligations went
    untested.
    """
    _, bound = _suite_and_binding(overridden=overridden)
    passing: CollectedTests = {bound: frozenset({"test_one", "test_two"})}

    assert _binding_classes("MemoryStore", passing, {}) == [], f"{label} was overridden"


def test_an_obligation_that_never_ran_does_not_count_as_running_the_suite() -> None:
    """One passing contract test cannot vouch for one that never reported.

    Covers the mark-skipped case and the suppressed case alike: neither
    produces a passing report, and the check enumerates from the suite, so
    both look the same and both fail.
    """
    _, bound = _suite_and_binding(overridden=())
    both: CollectedTests = {bound: frozenset({"test_one", "test_two"})}
    only_one: CollectedTests = {bound: frozenset({"test_one"})}

    assert _binding_classes("MemoryStore", both, {}) == [bound]  # control
    assert _binding_classes("MemoryStore", only_one, {}) == []


def test_a_suite_opting_itself_out_at_runtime_stays_legitimate() -> None:
    """A contract may decide an obligation does not apply to an implementation.

    ``ContextProviderContract`` does exactly this for a provider that serves a
    fixed instant. That is the suite's own call, made in its own body, and must
    not be confused with the obligation being suppressed from outside.
    """
    _, bound = _suite_and_binding(overridden=())
    passing: CollectedTests = {bound: frozenset({"test_one"})}
    opted_out: CollectedTests = {bound: frozenset({"test_two"})}

    assert _binding_classes("MemoryStore", passing, opted_out) == [bound]


def test_suppressing_a_suite_test_from_collection_does_not_count() -> None:
    """Rebinding a contract test to a non-function hides it from pytest entirely."""
    _, bound = _suite_and_binding(overridden=())
    setattr(bound, "test_two", None)  # noqa: B010 - rebinding to a non-function is the point
    passing: CollectedTests = {bound: frozenset({"test_one"})}

    assert _binding_classes("MemoryStore", passing, {}) == []


def test_a_second_requested_fixture_supplying_a_real_subject_is_not_a_binding() -> None:
    """The fake cannot ride along beside a real implementation the suite also takes."""
    suite, bound = _suite_and_binding(overridden=())
    setattr(bound, "probe", pytest.fixture(lambda self: object()))  # noqa: B010
    requested = _fixtures_requested_by(suite, _suite_declared_tests(suite)) | {"probe"}

    assert not _binds_fake(bound, "MemoryStore", requested)


def _suite_and_binding(*, overridden: tuple[str, ...]) -> tuple[type, type]:
    """Build a suite and a subclass overriding the named suite tests with no-ops."""

    class _Suite:
        def test_one(self, store: object) -> None: ...

        def test_two(self, store: object) -> None: ...

    class _Bound(_Suite):
        @pytest.fixture
        def store(self) -> object:
            return FakeMemoryStore()

    for name in overridden:
        # Same name, different function object: pytest still runs it, but the
        # suite's assertions do not.
        setattr(_Bound, name, lambda self, store: None)

    # Renamed rather than declared, so the literal name does not leak into
    # `_declared_class_names()` (see `_EmptySuite`).
    _Suite.__name__ = "MemoryStoreContract"
    return _Suite, _Bound

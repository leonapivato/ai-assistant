"""Mechanical enforcement of the Protocol triad rule.

``CONTRIBUTING.md`` -> "Adding a Protocol: land the triad together" makes three
artifacts one unit of work for every Protocol in ``core/protocols.py``:

1. a shared ``<Protocol>Contract`` conformance suite under ``tests/``,
2. a canonical ``Fake<Protocol>`` exported from ``ai_assistant.testing``, and
3. a ``Test...Contract`` subclass binding the two, **collected and run** by
   pytest -- the abstract suite collects nothing on its own, so without the
   subclass the fake is unverified however many files exist.

Until now that rule was held by review alone: a Protocol could land with no
suite and no fake and pass the entire gate, which is how the original backfill
debt accumulated. This is the same class of gap ADR-0015 names -- an invariant
held by prose rather than mechanism.

Part 3 is why this lives in pytest rather than in a standalone script. "Is the
binding subclass actually collected?" is a question only pytest can answer; a
script would have to re-run pytest to ask it. Living here it also inherits the
gate and CI for free (``uv run pytest`` already runs in both), and fails as an
ordinary test failure naming exactly what is missing.

Conventions the check relies on (all eight Protocols already follow them):
suite ``<Protocol>Contract``, fake ``Fake<Protocol>``. A Protocol that wants
different names should change this check, deliberately, in the same PR.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, is_protocol

import pytest

import ai_assistant.testing as testing_pkg
from ai_assistant.core import protocols as protocols_module

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


def _binds_fake(cls: type, protocol: str) -> bool:
    """Report whether ``cls`` binds the canonical fake for ``protocol``.

    Requires the test module to have imported the canonical fake object itself
    (not a same-named local stand-in) *and* the class body to reference it, so
    a module that binds the real implementation in one class and the fake in
    another is not miscredited.
    """
    fake_name = f"Fake{protocol}"
    canonical = _canonical_fake(protocol)
    module = sys.modules.get(cls.__module__)
    if canonical is None or module is None or getattr(module, fake_name, None) is not canonical:
        return False
    try:
        source = inspect.getsource(cls)
    except OSError:  # pragma: no cover - source is always available under pytest
        return False
    return re.search(rf"\b{re.escape(fake_name)}\b", source) is not None


def _binding_classes(protocol: str, collected: frozenset[type]) -> list[type]:
    """Return the collected classes that run the canonical fake through the suite."""
    suite_name = f"{protocol}Contract"
    return [
        cls
        for cls in collected
        if any(base.__name__ == suite_name for base in cls.__mro__[1:])
        and _binds_fake(cls, protocol)
    ]


def _missing_parts(
    protocol: str, declared: set[str], collected: frozenset[type] | None
) -> tuple[str, ...]:
    """Return the triad parts ``protocol`` is missing.

    ``collected`` may be ``None`` to check only the statically visible parts.
    """
    missing = []
    if f"{protocol}Contract" not in declared:
        missing.append("suite")
    if _canonical_fake(protocol) is None:
        missing.append("fake")
    if collected is not None and not _binding_classes(protocol, collected):
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
            f"a collected `Test...Contract` subclass of `{protocol}Contract` "
            f"whose fixture returns `Fake{protocol}`"
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
        if (gaps := _unexcused(protocol, _missing_parts(protocol, declared, collected=None)))
    ]

    assert not failures, "\n".join([*failures, "", _TRIAD_RULE])


def test_every_protocols_fake_is_bound_by_a_collected_contract_subclass(
    collected_test_classes: frozenset[type],
    collection_is_unfiltered: bool,
) -> None:
    """Part 3: pytest really collects a subclass running each fake through its suite.

    This is the part a file-existence check cannot make: the abstract suite
    collects nothing, so only the binding subclass turns the contract into
    assertions that run.
    """
    if not collection_is_unfiltered:
        pytest.skip(
            "collection was narrowed (-k, -m, or a path/nodeid argument), so an "
            "absent binding class proves nothing; the gate runs the full suite"
        )
    declared = _declared_class_names()

    failures = [
        _describe(protocol, gaps)
        for protocol in _protocol_names()
        if (
            gaps := _unexcused(protocol, _missing_parts(protocol, declared, collected_test_classes))
        )
    ]

    assert not failures, "\n".join([*failures, "", _TRIAD_RULE])


def test_no_exemption_is_stale(
    collected_test_classes: frozenset[type],
    collection_is_unfiltered: bool,
) -> None:
    """An exemption dies with the gap it describes, so the backlog only shrinks."""
    if not collection_is_unfiltered:
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
        gaps = set(_missing_parts(exemption.protocol, declared, collected_test_classes))
        if closed := set(exemption.missing) - gaps:
            failures.append(
                f"{exemption.protocol} is exempted for {sorted(closed)} but that "
                f"part now exists -- remove it from the exemption and close "
                f"{exemption.issue}"
            )

    assert not failures, "\n".join(failures)


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
    missing = _missing_parts("NonexistentThing", declared=set(), collected=frozenset())

    assert missing == TRIAD_PARTS
    assert "NonexistentThing" in _describe("NonexistentThing", missing)

"""The calendar parse path ships no compiled code (ADR-0183 §5, issue #1462).

ADR-0183 §5's memory-safety clause is normative over *the class of parser a reader
may hand hostile bytes to*: "adversary-chosen bytes may not reach a compiled parse
path in which a malformed document is an out-of-bounds access or a controlled
allocation". The section is explicit that today's containment is bought from a fact
about the libraries rather than from any rule — "both parse paths are pure Python, so
a stack overflow arrives as a ``RecursionError`` and is caught by the wrapping clause
above and reported as a source fault" — and that this "is a property of the libraries
chosen, not of any rule".

**This module is the instrument for that property, and it is deliberately not a pin.**
Issue #1462 asks whether "parses adversary-chosen bytes" is a second exact-pinning
axis beside ADR-0024 §3's reproducibility one, and names the alternative it is
answered with here: "a *test* that asserts the property ADR-0183 §5 actually needs —
that neither package ships a compiled parse path — which would fail the gate on a
lockfile refresh that changed it and would not freeze either package at a version with
a known bug". So nothing here reads a version, and nothing here constrains one. A
refresh that moves ``icalendar`` from 7.2.2 to 8.0 passes; a refresh that moves it to a
release shipping an extension module fails, which is the point — the property stops
being able to change with nobody deciding it should.

**The distribution names come from ``pyproject.toml``, not from a literal version.**
``test_both_parse_path_distributions_are_declared_runtime_dependencies`` is the second
half of that: ADR-0183 §5 records that ``dateutil`` was at the time "declared
**nowhere** in the runtime dependencies" while ``readers/_occurrences.py`` imported
``dateutil.rrule.rrulestr`` directly, so the one library expanding an adversary-chosen
``RRULE`` would have vanished the day ``icalendar`` stopped depending on it. That gap
is closed on ``main``; this pins it closed, because an undeclared parse path is a parse
path nobody is choosing.

**Why the whole requirement closure and not only the two names.** The clause is stated
over what the *bytes* can reach, and they do not stop at the two distributions the ADR
names by name: ``icalendar`` hands an ``RRULE`` to ``python-dateutil``, which uses
``six``. A compiled artifact arriving one level down is the same breach with a longer
path to it, so the closure is walked from the declared requirements and every
distribution in it is checked — the shape
``tests/tools/test_egress_seam.py::test_every_runtime_dependency_is_classified``
already uses, and for its reason: a new transitive dependency should be a decision
rather than an omission.

**Unverifiable is a breach, not a pass.** A distribution whose ``WHEEL`` or ``RECORD``
cannot be read is reported as a failure rather than skipped, because the assertion is
that the property *holds*, and an install this module cannot read metadata out of is
one where it has no grounds to say so.

**What this does not see, stated rather than implied.** Distribution metadata is a
manifest, so a compiled artifact a package downloads, builds or extracts at run time is
outside it; ``ctypes`` reaching a system library is not a file in any ``RECORD``; and
the check is at distribution granularity, so it says nothing about which module inside
a pure-Python distribution the bytes actually reach. It is the instrument ADR-0183 §5's
own reasoning asks for — the fact about the installed libraries, asserted rather than
assumed — and not a proof of memory safety.
"""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol

import pytest
from packaging.requirements import Requirement

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: The two distributions ADR-0183 §5 names as the calendar parse path: `icalendar`
#: does the format, and `python-dateutil` expands the `RRULE`. Normalised, so the
#: spelling in `pyproject.toml` and the spelling in the installed metadata compare
#: equal. Deliberately names no version — see this module's docstring.
PARSE_PATH_ROOTS = frozenset({"icalendar", "python_dateutil"})

#: Suffixes that mean *loadable compiled code*: a CPython extension module on the
#: three platforms that spell it differently, and a shared library shipped beside one.
#: Checked against the whole suffix chain, so `_speedups.cpython-314-x86_64-linux-gnu.so`
#: and `libfoo.so.1` are both caught. Static archives (`.a`) are left out: they are a
#: build input rather than something an interpreter loads, and the clause is about what
#: the bytes reach at run time.
COMPILED_SUFFIXES = frozenset({".so", ".pyd", ".dylib", ".dll"})


class _Distribution(Protocol):
    """The two pieces of installed metadata this module reads.

    Narrower than :class:`importlib.metadata.Distribution` so the mutation tests can
    supply one without constructing a real distribution.
    """

    @property
    def files(self) -> Sequence[PurePosixPath] | None:
        """The distribution's `RECORD`, or `None` when it cannot be read."""
        ...

    def read_text(self, filename: str) -> str | None:
        """The named metadata file's text, or `None` when it is absent."""
        ...


def _normalise(name: str) -> str:
    """A distribution name in the one spelling this module compares by.

    Args:
        name: A distribution name as declared or as installed.

    Returns:
        Lower case, with separators folded to underscores.
    """
    return name.lower().replace("-", "_").replace(".", "_")


def _declared_dependencies() -> dict[str, Requirement]:
    """This project's declared runtime requirements, keyed by normalised name.

    Returns:
        The `[project].dependencies` table of `pyproject.toml`, parsed.
    """
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    requirements = [Requirement(text) for text in declared]
    return {_normalise(requirement.name): requirement for requirement in requirements}


def _parse_path_closure() -> frozenset[str]:
    """Every distribution the calendar parse path pulls in, transitively.

    Seeded from the declared requirement for each of :data:`PARSE_PATH_ROOTS`, so a
    root declared with extras walks the requirements those extras turn on. A root that
    is not declared at all is still walked — the missing declaration is
    :func:`test_both_parse_path_distributions_are_declared_runtime_dependencies`'s
    failure to report, and swallowing the root here would hide the compiled-code
    question behind it.

    Returns:
        Normalised distribution names, the roots included.
    """
    declared = _declared_dependencies()
    installed = {
        _normalise(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata["Name"]
    }

    seen: set[str] = set()
    pending = [declared.get(root) or Requirement(root) for root in sorted(PARSE_PATH_ROOTS)]
    while pending:
        requirement = pending.pop()
        name = _normalise(requirement.name)
        if name in seen:
            continue
        seen.add(name)
        for text in installed[name].requires or [] if name in installed else []:
            dependency = Requirement(text)
            if dependency.marker is None or any(
                dependency.marker.evaluate({"extra": extra})
                for extra in {"", *(requirement.extras or set())}
            ):
                pending.append(dependency)
    return frozenset(seen)


def compiled_artifacts(files: Iterable[PurePosixPath]) -> list[str]:
    """The entries of a `RECORD` that are loadable compiled code.

    Args:
        files: The distribution's recorded files.

    Returns:
        Their paths, as strings, in the order given — empty when the distribution
        ships none, which is the property ADR-0183 §5 rests on.
    """
    return [str(path) for path in files if COMPILED_SUFFIXES & set(path.suffixes)]


def purelib_root(wheel_metadata: str) -> bool | None:
    """Whether a `WHEEL` file declares its root to be purelib.

    Args:
        wheel_metadata: The text of a distribution's `WHEEL` metadata file.

    Returns:
        The value of `Root-Is-Purelib`, or `None` when the field is absent — which is
        not the same answer as `False` and is not treated as one.
    """
    for line in wheel_metadata.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "root-is-purelib":
            return value.strip().lower() == "true"
    return None


def _purelib_breach(distribution: _Distribution) -> str | None:
    """Why the distribution's `WHEEL` fails to say its root is pure Python.

    Args:
        distribution: The installed distribution's metadata.

    Returns:
        A sentence naming the failure, or `None` when `WHEEL` declares purelib.
    """
    wheel = distribution.read_text("WHEEL")
    if wheel is None:
        return "no WHEEL metadata, so Root-Is-Purelib cannot be read"
    is_purelib = purelib_root(wheel)
    if is_purelib is None:
        return "WHEEL metadata declares no Root-Is-Purelib"
    if not is_purelib:
        return "WHEEL declares Root-Is-Purelib: false, so it installs platform code"
    return None


def _record_breach(distribution: _Distribution) -> str | None:
    """Why the distribution's `RECORD` fails to show a source-only install.

    Args:
        distribution: The installed distribution's metadata.

    Returns:
        A sentence naming the failure, or `None` when no recorded file is compiled.
    """
    files = distribution.files
    if files is None:
        return "no RECORD, so the installed files cannot be listed"
    compiled = compiled_artifacts(files)
    if compiled:
        return f"RECORD lists compiled artifacts: {', '.join(sorted(compiled))}"
    return None


def breach(name: str) -> str | None:
    """Why `name`'s installed metadata fails ADR-0183 §5's memory-safety clause.

    Both halves of the check are required, and either one being unreadable is itself
    the breach: the assertion is that the property holds, and metadata this cannot read
    is metadata that grounds nothing.

    Args:
        name: A normalised distribution name.

    Returns:
        A sentence naming the failure, or `None` when the distribution ships no
        compiled code and says so in its own metadata.
    """
    try:
        distribution: _Distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed, so the property cannot be read from its metadata"
    return _purelib_breach(distribution) or _record_breach(distribution)


def test_both_parse_path_distributions_are_declared_runtime_dependencies() -> None:
    """The parse path is declared, so it is chosen rather than inherited.

    ADR-0183 §5 records `dateutil` as "declared **nowhere** in the runtime
    dependencies" while `readers/_occurrences.py` imported `rrulestr` from it, which
    made the library expanding an adversary-chosen `RRULE` a transitive accident of
    `icalendar`'s own requirements. Both are declared on `main`; this is what notices
    the day one stops being.
    """
    declared = _declared_dependencies()
    missing = sorted(PARSE_PATH_ROOTS - declared.keys())
    assert not missing, (
        f"{missing} names the calendar parse path (ADR-0183 §5) but is not in "
        "[project].dependencies of pyproject.toml. A parse path over adversary-chosen "
        "bytes that arrives transitively is one nobody decided to depend on."
    )


def test_the_calendar_parse_path_ships_no_compiled_code() -> None:
    """No distribution the calendar parse path reaches ships loadable compiled code.

    This is ADR-0183 §5's memory-safety clause asserted rather than assumed: with the
    whole path pure Python, a hostile document's recursion arrives as a
    `RecursionError` that the reader's wrapping clause catches and reports as a source
    fault, instead of as an out-of-bounds access. A lockfile refresh that changes the
    property fails here; one that only changes a version does not.
    """
    closure = _parse_path_closure()
    assert closure >= PARSE_PATH_ROOTS, (
        f"the parse-path closure {sorted(closure)} does not contain "
        f"{sorted(PARSE_PATH_ROOTS)}; the walk is broken, and a check over an empty "
        "set would pass while asserting nothing"
    )

    breaches = {name: reason for name in sorted(closure) if (reason := breach(name)) is not None}
    assert not breaches, (
        "ADR-0183 §5 requires that adversary-chosen bytes reach no compiled parse "
        "path, and the reader's containment of a hostile document rests on it: "
        + "; ".join(f"{name}: {reason}" for name, reason in breaches.items())
    )


class _StubDistribution:
    """A distribution whose metadata this module's tests choose.

    Args:
        wheel: The text `read_text("WHEEL")` returns, or `None` for absent.
        files: The paths `files` returns, or `None` for an unreadable `RECORD`.
    """

    def __init__(self, *, wheel: str | None, files: Sequence[str] | None) -> None:
        self._wheel = wheel
        self._files = files

    @property
    def files(self) -> Sequence[PurePosixPath] | None:
        """The stubbed `RECORD` listing."""
        return None if self._files is None else [PurePosixPath(path) for path in self._files]

    def read_text(self, filename: str) -> str | None:
        """The stubbed `WHEEL` text, and nothing else.

        Args:
            filename: The metadata file requested.

        Returns:
            The configured `WHEEL` text for `"WHEEL"`, `None` otherwise.
        """
        return self._wheel if filename == "WHEEL" else None


_PURELIB_WHEEL = "Wheel-Version: 1.0\nGenerator: hatchling 1.31.0\nRoot-Is-Purelib: true\n"


@pytest.mark.parametrize(
    ("wheel", "files", "expected"),
    [
        pytest.param(
            _PURELIB_WHEEL,
            ["dateutil/_speedups.cpython-314-x86_64-linux-gnu.so", "dateutil/rrule.py"],
            "RECORD lists compiled artifacts",
            id="extension-module-in-record",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            ["icalendar/libparse.so.1", "icalendar/parser.py"],
            "RECORD lists compiled artifacts",
            id="shared-library-in-record",
        ),
        pytest.param(
            "Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp314-cp314-manylinux_2_28_x86_64\n",
            ["icalendar/parser.py"],
            "Root-Is-Purelib: false",
            id="platform-wheel",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            None,
            "no RECORD",
            id="unreadable-record",
        ),
        pytest.param(
            None,
            ["icalendar/parser.py"],
            "no WHEEL metadata",
            id="absent-wheel-metadata",
        ),
    ],
)
def test_the_check_reports_a_breach_it_is_shown(
    monkeypatch: pytest.MonkeyPatch,
    wheel: str | None,
    files: Sequence[str] | None,
    expected: str,
) -> None:
    """Each way the property can stop holding is a failure rather than a pass.

    Without this, a check that read the wrong metadata field — or read it out of a
    distribution whose `RECORD` it could not open — would be green for the same reason
    a correct one is, and the gate would pin nothing. Two of the cases are the
    unreadable ones, because "cannot verify" is the answer most likely to be mistaken
    for "verified".

    Args:
        monkeypatch: Redirects the metadata reader at the stub.
        wheel: The `WHEEL` text the stubbed distribution reports.
        files: The `RECORD` listing the stubbed distribution reports.
        expected: A fragment the reported breach must contain.
    """
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: _StubDistribution(wheel=wheel, files=files),
    )
    reported = breach("icalendar")
    assert reported is not None
    assert expected in reported


def test_a_pure_python_distribution_is_no_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check is not merely always failing, which the cases above cannot show.

    Args:
        monkeypatch: Redirects the metadata reader at the stub.
    """
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: _StubDistribution(
            wheel=_PURELIB_WHEEL,
            files=["icalendar/parser.py", "icalendar/tests/calendars/issue_156.ics"],
        ),
    )
    assert breach("icalendar") is None

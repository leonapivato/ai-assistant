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
:func:`test_both_parse_path_distributions_are_declared_runtime_dependencies` is the
second half of that: ADR-0183 §5 records that ``dateutil`` was at the time "declared
**nowhere** in the runtime dependencies" while ``readers/_occurrences.py`` imported
``dateutil.rrule.rrulestr`` directly, so the one library expanding an adversary-chosen
``RRULE`` would have vanished the day ``icalendar`` stopped depending on it. That gap
is closed on ``main``; this pins it closed, because an undeclared parse path is a parse
path nobody is choosing.

**Two instruments, because the installed environment is one platform and the property
is not.** Installed metadata answers for *this* interpreter on *this* operating system:
a dependency guarded by ``sys_platform == "darwin"`` is not installed here and a
distribution publishing a pure Linux wheel beside a compiled macOS one installs the
pure one here. Both would be green on the gate's Ubuntu runner while a macOS install
handed hostile bytes to compiled code. So the same property is asserted twice:

- :func:`test_the_installed_calendar_parse_path_ships_no_compiled_code` reads
  ``WHEEL``'s ``Root-Is-Purelib`` and ``RECORD`` for what is installed here. It is the
  fact ADR-0183 §5 states, checked where the ADR states it.
- :func:`test_the_locked_calendar_parse_path_publishes_only_pure_python_wheels` reads
  ``uv.lock``, whose resolution is universal — every wheel of every resolved version
  for every platform, and every dependency edge including the ones a marker excludes
  here. A compiled macOS wheel is a filename in that file, and a platform-guarded
  dependency is an entry in it. This is the platform-independent half.

Neither subsumes the other: the lock records what would be installed, and the installed
metadata records what *is*, which is what an environment assembled some other way
actually runs.

**Why the whole requirement closure and not only the two names.** The clause is stated
over what the *bytes* can reach, and they do not stop at the two distributions the ADR
names: ``icalendar`` hands an ``RRULE`` to ``python-dateutil``, which uses ``six``. A
compiled artifact arriving one level down is the same breach with a longer path to it,
so the closure is walked from the declared requirements and every distribution in it is
checked — the shape
``tests/tools/test_egress_seam.py::test_every_runtime_dependency_is_classified`` already
uses, and for its reason: a new transitive dependency should be a decision rather than
an omission. The walk tracks *activated extras per distribution* rather than visiting a
name once, because a diamond — a root wanting ``helper[native]`` and a sibling wanting
bare ``helper`` — otherwise marks the name seen without its extra and never walks the
requirements that extra turns on. :func:`test_the_closure_walks_an_extra_discovered_late`
is that case, in both orders.

**Unverifiable is a breach, not a pass.** A ``WHEEL`` or ``RECORD`` that cannot be read,
a distribution absent from the lock, and a locked distribution with no wheel at all
(so an install builds it from its sdist, which is where compilation happens) are each
reported as a failure rather than skipped. The claim is that the property *holds*, and
an install this module cannot read grounds nothing.

**What this does not see, stated rather than implied.** Distribution metadata and a
lock are both manifests, so a compiled artifact a package downloads, builds or extracts
at run time is outside both; ``ctypes`` reaching a system library is a file in no
``RECORD``; the granularity is the distribution, so neither test says which module
inside a pure-Python distribution the bytes reach; and the lock is checked as it is
written, so a resolution nobody has committed is outside it too. It is the instrument
ADR-0183 §5's own reasoning asks for — the fact about the libraries, asserted rather
than assumed — and not a proof of memory safety.
"""

from __future__ import annotations

import importlib.metadata
import re
import sys
import tomllib
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from packaging.requirements import Requirement

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

#: This module itself, so a test can redirect one of its readers. `monkeypatch` on the
#: dotted path would import a *second* copy under pytest's rootdir layout and patch
#: that one, leaving the functions under test reading the real files.
_MODULE = sys.modules[__name__]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_LOCK = _REPO_ROOT / "uv.lock"

#: The two distributions ADR-0183 §5 names as the calendar parse path: `icalendar`
#: does the format, and `python-dateutil` expands the `RRULE`. Normalised, so the
#: spelling in `pyproject.toml`, in `uv.lock` and in the installed metadata compare
#: equal. Deliberately names no version — see this module's docstring.
PARSE_PATH_ROOTS = frozenset({"icalendar", "python_dateutil"})

#: A file name that ends in *loadable compiled code*: a CPython extension module on the
#: three platforms that spell it differently, plus a Windows or ELF shared library,
#: with the version suffixes a `libfoo.so.1.2` carries. Anchored at the end and matched
#: case-insensitively, which is what separates `parser.DLL` — loadable, and missed by a
#: case-sensitive check — from `libfoo.dll.a`, a static archive that is a build input
#: rather than something an interpreter loads.
COMPILED_ARTIFACT = re.compile(r"\.(so|pyd|dylib|dll)(\.\d+)*$", re.IGNORECASE)


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
        name: A distribution name as declared, as locked, or as installed.

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


def closure(
    roots: Iterable[Requirement],
    requires: Callable[[str, frozenset[str]], Sequence[str]],
) -> frozenset[str]:
    """Every distribution reachable from `roots`, extras included.

    A name is revisited when an extra is discovered for it that an earlier edge did not
    activate, so the requirements that extra turns on are walked even though the name
    was already seen. Without that, a diamond loses them silently: the sibling edge
    wanting the bare name arrives first, marks it seen, and the edge wanting
    `name[extra]` is skipped. Termination is bought by the activated set only growing.

    Args:
        roots: The requirements to start from.
        requires: The requirements of a distribution, given its normalised name and the
            extras activated on it so far.

    Returns:
        Normalised distribution names, the roots included.
    """
    visited: set[str] = set()
    activated: dict[str, set[str]] = {}
    pending = list(roots)
    while pending:
        requirement = pending.pop()
        name = _normalise(requirement.name)
        extras = {extra.lower() for extra in requirement.extras}
        unseen = name not in visited
        new_extras = extras - activated.get(name, set())
        if not unseen and not new_extras:
            continue
        visited.add(name)
        activated.setdefault(name, set()).update(extras)
        pending.extend(Requirement(text) for text in requires(name, frozenset(activated[name])))
    return frozenset(visited)


def _installed_requires(name: str, extras: frozenset[str]) -> list[str]:
    """The installed distribution's requirements, for the extras activated on it.

    Args:
        name: A normalised distribution name.
        extras: The extras activated on it so far.

    Returns:
        Requirement strings whose environment marker holds here, under no extra or
        under one of `extras`. Empty when the distribution is not installed — the
        absence is reported by the checks, not by a walk that raises.
    """
    installed = _installed_distributions().get(name)
    if installed is None:
        return []
    return [
        text
        for text in installed.requires or []
        if (marker := Requirement(text).marker) is None
        or any(marker.evaluate({"extra": extra}) for extra in {"", *extras})
    ]


@cache
def _installed_distributions() -> dict[str, importlib.metadata.Distribution]:
    """Every distribution installed in this environment, keyed by normalised name.

    Returns:
        The environment's distributions; a nameless one is skipped.
    """
    return {
        _normalise(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
        if distribution.metadata["Name"]
    }


def _roots() -> list[Requirement]:
    """The declared requirement for each parse-path root.

    A root that is not declared at all is still walked, under its bare name: the
    missing declaration is
    :func:`test_both_parse_path_distributions_are_declared_runtime_dependencies`'s
    failure to report, and dropping the root here would hide the compiled-code question
    behind it.

    Returns:
        One requirement per name in :data:`PARSE_PATH_ROOTS`.
    """
    declared = _declared_dependencies()
    return [declared.get(root) or Requirement(root) for root in sorted(PARSE_PATH_ROOTS)]


def compiled_artifacts(files: Iterable[PurePosixPath]) -> list[str]:
    """The entries of a `RECORD` that are loadable compiled code.

    Args:
        files: The distribution's recorded files.

    Returns:
        Their paths, as strings, in the order given — empty when the distribution
        ships none, which is the property ADR-0183 §5 rests on.
    """
    return [str(path) for path in files if COMPILED_ARTIFACT.search(path.name)]


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


def installed_breach(name: str) -> str | None:
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


@cache
def _locked_packages() -> dict[str, list[dict[str, Any]]]:
    """Every `[[package]]` entry of `uv.lock`, grouped by normalised name.

    A list rather than one entry per name: a universal resolution may lock two
    versions of the same distribution under different resolution markers, and both are
    installable, so both are checked.

    Returns:
        The lock's package entries, keyed by normalised name.
    """
    packages: dict[str, list[dict[str, Any]]] = {}
    for package in tomllib.loads(_LOCK.read_text(encoding="utf-8"))["package"]:
        packages.setdefault(_normalise(package["name"]), []).append(package)
    return packages


def _locked_requires(name: str, extras: frozenset[str]) -> list[str]:
    """A locked distribution's dependency edges, markers deliberately ignored.

    Ignoring markers is the point of this walk: an edge guarded by
    `sys_platform == "darwin"` is exactly the one the installed closure cannot see, and
    including it here is the conservative direction.

    Args:
        name: A normalised distribution name.
        extras: The extras activated on it so far.

    Returns:
        Requirement strings for its `dependencies`, plus the `optional-dependencies` of
        each activated extra. Empty when the name is not in the lock — the absence is
        reported by :func:`locked_breach`.
    """
    edges: list[dict[str, Any]] = []
    for package in _locked_packages().get(name, []):
        edges.extend(package.get("dependencies", []))
        optional = package.get("optional-dependencies", {})
        for extra in extras:
            edges.extend(optional.get(extra, []))
    return [
        f"{edge['name']}[{','.join(edge['extra'])}]" if edge.get("extra") else str(edge["name"])
        for edge in edges
    ]


def wheel_is_pure(filename: str) -> bool:
    """Whether a wheel's own file name says it contains no compiled code.

    A wheel's last three tags are `{python}-{abi}-{platform}`. `none-any` is the pair
    that means "no ABI, no platform" — a pure-Python wheel installable everywhere.
    Anything else was built for a specific interpreter ABI or a specific platform,
    which is what shipping an extension module requires.

    Args:
        filename: A wheel's file name, with or without directories ahead of it.

    Returns:
        `True` for a `-none-any.whl`; `False` for a platform wheel and for a name that
        does not parse, since a name this cannot read is not one it can clear.
    """
    tags = PurePosixPath(filename).name.removesuffix(".whl").split("-")
    if len(tags) < 5:  # name, version, python, abi, platform
        return False
    _python, abi, platform = tags[-3:]
    return abi == "none" and set(platform.split(".")) == {"any"}


def locked_breach(name: str) -> str | None:
    """Why `name`'s entry in `uv.lock` fails ADR-0183 §5's memory-safety clause.

    Args:
        name: A normalised distribution name.

    Returns:
        A sentence naming the failure, or `None` when every locked version of the
        distribution publishes only pure-Python wheels.
    """
    packages = _locked_packages().get(name, [])
    if not packages:
        return "not in uv.lock, so what an install would fetch cannot be read"
    for package in packages:
        version = package.get("version", "?")
        wheels = [str(wheel["url"]) for wheel in package.get("wheels", [])]
        if not wheels:
            return f"{version} locks no wheel, so an install builds it from its sdist"
        impure = sorted(PurePosixPath(url).name for url in wheels if not wheel_is_pure(url))
        if impure:
            return f"{version} publishes non-pure wheels: {', '.join(impure)}"
    return None


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


def test_the_installed_calendar_parse_path_ships_no_compiled_code() -> None:
    """Nothing the calendar parse path reaches *here* ships loadable compiled code.

    This is ADR-0183 §5's memory-safety clause asserted rather than assumed: with the
    whole path pure Python, a hostile document's recursion arrives as a
    `RecursionError` that the reader's wrapping clause catches and reports as a source
    fault, instead of as an out-of-bounds access. A lockfile refresh that changes the
    property fails here; one that only changes a version does not. What this cannot
    see is any platform but the running one, which is the other test's half.
    """
    reached = closure(_roots(), _installed_requires)
    assert reached >= PARSE_PATH_ROOTS, (
        f"the installed parse-path closure {sorted(reached)} does not contain "
        f"{sorted(PARSE_PATH_ROOTS)}; the walk is broken, and a check over an empty "
        "set would pass while asserting nothing"
    )

    breaches = {
        name: reason for name in sorted(reached) if (reason := installed_breach(name)) is not None
    }
    assert not breaches, (
        "ADR-0183 §5 requires that adversary-chosen bytes reach no compiled parse "
        "path, and the reader's containment of a hostile document rests on it: "
        + "; ".join(f"{name}: {reason}" for name, reason in breaches.items())
    )


def test_the_locked_calendar_parse_path_publishes_only_pure_python_wheels() -> None:
    """The property holds on every platform the lock resolves for, not only this one.

    `uv.lock`'s resolution is universal, so it records every wheel of every resolved
    version and every dependency edge including the ones an environment marker excludes
    here. A distribution publishing a pure Linux wheel beside a compiled macOS one, or
    a parse-path dependency guarded by `sys_platform`, is invisible to the installed
    check on the gate's Ubuntu runner and visible in this file.
    """
    reached = closure(_roots(), _locked_requires)
    assert reached >= PARSE_PATH_ROOTS, (
        f"the locked parse-path closure {sorted(reached)} does not contain "
        f"{sorted(PARSE_PATH_ROOTS)}; the walk is broken, and a check over an empty "
        "set would pass while asserting nothing"
    )

    breaches = {
        name: reason for name in sorted(reached) if (reason := locked_breach(name)) is not None
    }
    assert not breaches, (
        "ADR-0183 §5's memory-safety clause is a property of the parse path on every "
        "platform an install can resolve, and uv.lock records one that is not: "
        + "; ".join(f"{name}: {reason}" for name, reason in breaches.items())
    )


def test_the_two_closures_agree_on_the_parse_path() -> None:
    """The lock's edges and the installed environment's tell the same story here.

    Not a property either check needs — the lock is a superset by construction, since
    it keeps the edges a marker excludes — but a disagreement means one of the two
    walks is reading something the other cannot see, and the assertions above would
    then be over different sets while appearing to be over one.
    """
    installed = closure(_roots(), _installed_requires)
    locked = closure(_roots(), _locked_requires)
    assert installed <= locked, (
        f"installed closure {sorted(installed)} is not contained in the locked closure "
        f"{sorted(locked)}, so something is installed that the lock does not record"
    )


_DIAMOND: dict[tuple[str, frozenset[str]], list[str]] = {
    ("wrapper", frozenset()): ["helper"],
    ("helper", frozenset()): [],
    ("helper", frozenset({"native"})): ["compiled_thing"],
    ("compiled_thing", frozenset()): [],
}


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(["helper[native]", "wrapper"], id="bare-edge-walked-first"),
        pytest.param(["wrapper", "helper[native]"], id="extra-edge-walked-first"),
    ],
)
def test_the_closure_walks_an_extra_discovered_late(order: list[str]) -> None:
    """A name already seen without an extra is revisited when the extra shows up.

    The diamond: the root wants `helper[native]` and `wrapper`, and `wrapper` wants
    bare `helper`. A walk that marked `helper` seen on the bare edge would never reach
    `compiled_thing`, which `native` turns on — so a compiled distribution would be
    installed and unchecked. Both orders are exercised because a stack makes the
    outcome depend on which edge is popped first — the *last* string given is walked
    first — and only `bare-edge-walked-first` fails against the name-only walk this
    replaced, which is why both are here.

    Args:
        order: The root's requirement strings, in the order they are handed over.
    """

    def requires(name: str, extras: frozenset[str]) -> list[str]:
        return _DIAMOND.get((name, extras), [])

    reached = closure([Requirement(text) for text in order], requires)
    assert reached == {"wrapper", "helper", "compiled_thing"}


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
            id="versioned-shared-library-in-record",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            ["icalendar/parser.DLL", "icalendar/parser.py"],
            "RECORD lists compiled artifacts",
            id="upper-case-windows-library",
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
        pytest.param(
            "Wheel-Version: 1.0\nGenerator: hatchling 1.31.0\n",
            ["icalendar/parser.py"],
            "declares no Root-Is-Purelib",
            id="wheel-metadata-without-the-field",
        ),
    ],
)
def test_the_installed_check_reports_a_breach_it_is_shown(
    monkeypatch: pytest.MonkeyPatch,
    wheel: str | None,
    files: Sequence[str] | None,
    expected: str,
) -> None:
    """Each way the property can stop holding is a failure rather than a pass.

    Without this, a check that read the wrong metadata field — or read it out of a
    distribution whose `RECORD` it could not open — would be green for the same reason
    a correct one is, and the gate would pin nothing. Three of the cases are the
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
    reported = installed_breach("icalendar")
    assert reported is not None
    assert expected in reported


def test_a_pure_python_install_is_no_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """The installed check is not merely always failing, which the cases above cannot show.

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
    assert installed_breach("icalendar") is None


@pytest.mark.parametrize(
    ("path", "compiled"),
    [
        pytest.param("dateutil/_speedups.cpython-314-x86_64-linux-gnu.so", True, id="ext-linux"),
        pytest.param("icalendar/_parse.cp314-win_amd64.pyd", True, id="ext-windows"),
        pytest.param("icalendar/_parse.dylib", True, id="shared-macos"),
        pytest.param("icalendar/libparse.so.1.2", True, id="versioned-so"),
        pytest.param("icalendar/parser.DLL", True, id="upper-case-dll"),
        pytest.param("icalendar/libparse.dll.a", False, id="static-archive"),
        pytest.param("icalendar/parser.py", False, id="source"),
        pytest.param("icalendar/tests/calendars/rfc_9074_alarm.ics", False, id="data"),
        pytest.param("icalendar/so", False, id="extensionless-so"),
    ],
)
def test_the_compiled_artifact_classifier_at_its_boundaries(path: str, compiled: bool) -> None:
    """What counts as loadable compiled code, at the names that decide it.

    `parser.DLL` is loadable on Windows and a case-sensitive check misses it;
    `libparse.dll.a` is a static archive, which the comment on
    :data:`COMPILED_ARTIFACT` excludes deliberately and a suffix-chain check reports
    anyway. Both were review findings against the version this replaced.

    Args:
        path: A `RECORD` entry.
        compiled: Whether it should be reported as compiled code.
    """
    assert bool(compiled_artifacts([PurePosixPath(path)])) is compiled


@pytest.mark.parametrize(
    ("filename", "pure"),
    [
        pytest.param("icalendar-7.2.2-py3-none-any.whl", True, id="pure-py3"),
        pytest.param("python_dateutil-2.9.0.post0-py2.py3-none-any.whl", True, id="pure-py2-py3"),
        pytest.param("icalendar-8.0-cp314-cp314-macosx_11_0_arm64.whl", False, id="macos-wheel"),
        pytest.param(
            "icalendar-8.0-cp314-cp314-manylinux_2_28_x86_64.whl", False, id="linux-wheel"
        ),
        pytest.param("icalendar-8.0-cp314-abi3-any.whl", False, id="abi-specific"),
        pytest.param(
            "icalendar-8.0-py3-none-any.macosx_11_0_arm64.whl", False, id="mixed-platform"
        ),
        pytest.param("icalendar-7.2.2.tar.gz", False, id="not-a-wheel"),
    ],
)
def test_the_wheel_purity_classifier_at_its_boundaries(filename: str, pure: bool) -> None:
    """A wheel's tags decide it, and an unreadable name is not cleared.

    Args:
        filename: A wheel file name as `uv.lock` records it.
        pure: Whether its tags say it contains no compiled code.
    """
    assert wheel_is_pure(filename) is pure


def test_the_lock_check_reports_a_distribution_it_cannot_read() -> None:
    """A parse-path name absent from the lock is a breach, not a silent pass."""
    reported = locked_breach("no_such_distribution_at_all")
    assert reported is not None
    assert "not in uv.lock" in reported


_PURE_WHEEL_URL = "https://files.pythonhosted.org/packages/f1/icalendar-7.2.2-py3-none-any.whl"
_PLATFORM_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/f1/icalendar-8.0-cp314-cp314-macosx_11_0_arm64.whl"
)


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        pytest.param(
            [{"version": "8.0", "wheels": [{"url": _PLATFORM_WHEEL_URL}]}],
            "publishes non-pure wheels",
            id="platform-wheel",
        ),
        pytest.param(
            [
                {
                    "version": "8.0",
                    "wheels": [{"url": _PURE_WHEEL_URL}, {"url": _PLATFORM_WHEEL_URL}],
                },
            ],
            "publishes non-pure wheels",
            id="platform-wheel-beside-a-pure-one",
        ),
        pytest.param(
            [{"version": "8.0", "sdist": {"url": "…/icalendar-8.0.tar.gz"}}],
            "locks no wheel",
            id="sdist-only",
        ),
        pytest.param(
            [
                {"version": "7.2.2", "wheels": [{"url": _PURE_WHEEL_URL}]},
                {"version": "8.0", "wheels": [{"url": _PLATFORM_WHEEL_URL}]},
            ],
            "publishes non-pure wheels",
            id="second-resolution-marker-version",
        ),
    ],
)
def test_the_lock_check_reports_a_breach_it_is_shown(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[dict[str, Any]],
    expected: str,
) -> None:
    """Every way a locked parse path can carry compiled code is a failure.

    The last case is why `uv.lock` is read as a list per name rather than one entry:
    a universal resolution can lock two versions under different resolution markers,
    and a platform wheel in either of them is installable.

    Args:
        monkeypatch: Redirects the lock reader at the crafted entries.
        entries: The `[[package]]` entries the lock is made to report.
        expected: A fragment the reported breach must contain.
    """
    monkeypatch.setattr(_MODULE, "_locked_packages", lambda: {"icalendar": entries})
    reported = locked_breach("icalendar")
    assert reported is not None
    assert expected in reported


def test_a_pure_python_lock_entry_is_no_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lock check is not merely always failing, which the cases above cannot show.

    Args:
        monkeypatch: Redirects the lock reader at the crafted entry.
    """
    monkeypatch.setattr(
        _MODULE,
        "_locked_packages",
        lambda: {"icalendar": [{"version": "7.2.2", "wheels": [{"url": _PURE_WHEEL_URL}]}]},
    )
    assert locked_breach("icalendar") is None

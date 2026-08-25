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
a dependency guarded by ``sys_platform == "darwin"`` is not installed here, and a
distribution publishing a pure Linux wheel beside a compiled macOS one installs the
pure one here. Both would be green on the gate's Ubuntu runner while a macOS install
handed hostile bytes to compiled code. So the same property is asserted twice:

- :func:`test_the_installed_calendar_parse_path_ships_no_compiled_code` reads what is
  installed here — ``WHEEL``'s ``Root-Is-Purelib``, and every file ``RECORD`` lists,
  **by its first bytes** rather than by its name. It is the fact ADR-0183 §5 states,
  checked where the ADR states it.
- :func:`test_the_locked_calendar_parse_path_publishes_only_pure_python_wheels` reads
  ``uv.lock``, whose resolution is universal — every wheel of every resolved version
  for every platform, and every dependency edge including the ones a marker excludes
  here. A compiled macOS wheel is a file name in that file, and a platform-guarded
  dependency is an entry in it. This is the platform-independent half.

Neither subsumes the other: the lock records what an install *would* fetch, and the
installed metadata records what *is*, which is what an environment assembled some other
way actually runs.

**A file's first bytes, not its extension.** ``Root-Is-Purelib: true`` does not forbid a
loadable artifact inside the tree, and a name-based check is a list of the formats
somebody remembered: a Mach-O ``parser.bundle``, an extensionless helper, or a
``.DLL`` a case-sensitive match slid past would each be compiled code the property
denies. So every recorded file is opened and its magic number read
(:data:`NATIVE_MAGIC`), and the file-name pattern (:data:`COMPILED_ARTIFACT`) stays as a
second net for entries that are absent from the tree. The name-based net is not the
proof; the bytes are.

**Why the whole requirement closure and not only the two names.** The clause is stated
over what the *bytes* can reach, and they do not stop at the two distributions the ADR
names: ``icalendar`` hands an ``RRULE`` to ``python-dateutil``, which uses ``six``. A
compiled artifact arriving one level down is the same breach with a longer path to it,
so the closure is walked from the declared requirements and every distribution in it is
checked — the shape
``tests/tools/test_egress_seam.py::test_every_runtime_dependency_is_classified`` already
uses, and for its reason: a new transitive dependency should be a decision rather than
an omission. Two properties of that walk are load-bearing and each has its own test:

- **Extras are tracked per distribution and canonicalised** (PEP 685, via
  :func:`packaging.utils.canonicalize_name`). A diamond — a root wanting
  ``helper[native]`` and a sibling wanting bare ``helper`` — otherwise marks the name
  seen without its extra and never walks what that extra turns on; and a root spelling
  it ``helper[Native_Code]`` against a lock whose key is ``native-code`` otherwise
  looks the extra up under a name nothing has.
- **A lock edge that selects a version is followed to that version.** A universal
  resolution may fork a name into two entries, and only the entry an edge from the
  parse path selects is the parse path's. Checking both would fail the gate over a
  fork some unrelated dependency reaches; checking neither would miss the fork this one
  does. An edge with no selector still puts every entry of that name in play, because
  then any of them can be the one installed.

**Unverifiable is a breach, not a pass.** A ``WHEEL`` or ``RECORD`` that cannot be read,
a recorded file that exists and will not open, a distribution absent from the lock, and
a locked distribution with no wheel at all (so an install builds it from its sdist,
which is where compilation happens) are each reported as a failure rather than skipped.
The claim is that the property *holds*, and an install this module cannot read grounds
nothing. A recorded file that is simply *absent* is the one exception, and it is not the
same case: bytes that are not on disk are bytes no parser loads.

**What this does not see, stated rather than implied.** A compiled artifact a package
downloads, builds or extracts at run time exists at neither of the moments this looks;
``ctypes`` reaching a system library is a file in no ``RECORD``; the granularity is the
distribution, so neither test says which module inside a pure-Python distribution the
bytes actually reach; a wheel's tags are a claim its author makes, so the lock half
trusts them where the installed half does not have to; and the lock is checked as
written, so a resolution nobody has committed is outside it too. It is the instrument
ADR-0183 §5's own reasoning asks for — the fact about the libraries, asserted rather
than assumed — and not a proof of memory safety.
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import sys
import tomllib
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

#: This module itself, so a test can redirect one of its readers. `monkeypatch` on the
#: dotted path would import a *second* copy under pytest's rootdir layout and patch
#: that one, leaving the functions under test reading the real files.
_MODULE = sys.modules[__name__]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_LOCK = _REPO_ROOT / "uv.lock"

#: The two distributions ADR-0183 §5 names as the calendar parse path: `icalendar`
#: does the format, and `python-dateutil` expands the `RRULE`. In PEP 503 canonical
#: form, so the spelling in `pyproject.toml`, in `uv.lock` and in the installed
#: metadata compare equal. Deliberately names no version — see this module's docstring.
PARSE_PATH_ROOTS = frozenset({"icalendar", "python-dateutil"})

#: The magic numbers of the loadable native formats, read from a file's first bytes.
#: This is the check that does not depend on anyone having remembered a file
#: extension. `\xca\xfe\xba\xbe` is a Mach-O universal binary and also a Java class
#: file — neither belongs in a pure-Python parse path, so the conflation costs nothing.
NATIVE_MAGIC: tuple[bytes, ...] = (
    b"\x7fELF",  # ELF: a Linux or BSD shared object
    b"MZ",  # PE/COFF: a Windows .pyd or .dll
    b"\xfe\xed\xfa\xce",  # Mach-O, 32-bit, big and little endian
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",  # Mach-O, 64-bit, big and little endian
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",  # Mach-O universal ("fat"), both byte orders
    b"\xbe\xba\xfe\xca",
)

#: The bytes to read per file: the longest magic number above, and no more.
_MAGIC_BYTES = max(len(magic) for magic in NATIVE_MAGIC)

#: A file name that ends in *loadable compiled code* — the second net, for entries
#: `RECORD` lists that are not on disk to be read. Anchored at the end and matched
#: case-insensitively, which is what separates `parser.DLL` — loadable, and missed by a
#: case-sensitive check — from `libparse.dll.a`, a static archive that is a build input
#: rather than something an interpreter loads.
COMPILED_ARTIFACT = re.compile(r"\.(so|pyd|dylib|dll|bundle|sl)(\.\d+)*$", re.IGNORECASE)


class _Distribution(Protocol):
    """The three pieces of installed metadata this module reads.

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

    def locate_file(self, path: Any) -> Any:
        """Where a `RECORD` entry actually lives on disk."""
        ...


def _normalise(name: str) -> str:
    """A distribution name in the one spelling this module compares by.

    Args:
        name: A distribution name as declared, as locked, or as installed.

    Returns:
        Its PEP 503 canonical form, so `python_dateutil`, `Python-DateUtil` and
        `python.dateutil` are one name.
    """
    return canonicalize_name(name)


def _canonical_extras(extras: Iterable[str]) -> frozenset[str]:
    """Extra names in the one spelling this module compares by.

    Args:
        extras: Extra names as a requirement or a lock spells them.

    Returns:
        Their PEP 685 canonical forms — the same normalisation as a distribution name,
        which is what makes `helper[Native_Code]` and a lock key of `native-code` the
        same extra.
    """
    return frozenset(canonicalize_name(extra) for extra in extras)


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
) -> dict[str, list[Requirement]]:
    """Every distribution reachable from `roots`, with the edges that reached it.

    A name is revisited when an extra is discovered for it that an earlier edge did not
    activate, so the requirements that extra turns on are walked even though the name
    was already seen. Without that, a diamond loses them silently: the sibling edge
    wanting the bare name arrives first, marks it seen, and the edge wanting
    `name[extra]` is skipped. Termination is bought by the activated set only growing.

    Args:
        roots: The requirements to start from.
        requires: The requirements of a distribution, given its normalised name and the
            canonical extras activated on it so far.

    Returns:
        Normalised distribution name to the requirements naming it, the roots included.
        The edges are kept because a version selector on one of them is what says which
        locked entry of a forked name this path actually reaches.
    """
    reached: dict[str, list[Requirement]] = {}
    activated: dict[str, set[str]] = {}
    pending = list(roots)
    while pending:
        requirement = pending.pop()
        name = _normalise(requirement.name)
        extras = _canonical_extras(requirement.extras)
        unseen = name not in reached
        new_extras = extras - activated.get(name, set())
        reached.setdefault(name, []).append(requirement)
        if not unseen and not new_extras:
            continue
        activated.setdefault(name, set()).update(extras)
        pending.extend(Requirement(text) for text in requires(name, frozenset(activated[name])))
    return reached


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


def _installed_requires(name: str, extras: frozenset[str]) -> list[str]:
    """The installed distribution's requirements, for the extras activated on it.

    Args:
        name: A normalised distribution name.
        extras: The canonical extras activated on it so far.

    Returns:
        Requirement strings whose environment marker holds here, under no extra or
        under one of `extras`. Empty when the distribution is not installed — the
        absence is reported by :func:`installed_breach`, not by a walk that raises.
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


def is_native(head: bytes) -> bool:
    """Whether a file's first bytes are one of the loadable native formats.

    Args:
        head: The file's leading bytes, at least :data:`_MAGIC_BYTES` of them.

    Returns:
        `True` for an ELF, PE/COFF or Mach-O image — the formats an operating system
        can load and execute, whatever the file happens to be called.
    """
    return head.startswith(NATIVE_MAGIC)


def compiled_artifacts(files: Iterable[PurePosixPath]) -> list[str]:
    """The entries of a `RECORD` whose *name* says they are loadable compiled code.

    The second net. :func:`is_native` is the first, and it is the one that decides for
    every file actually on disk.

    Args:
        files: The distribution's recorded files.

    Returns:
        Their paths, as strings, in the order given.
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


def _content_breach(distribution: _Distribution, files: Sequence[PurePosixPath]) -> str | None:
    """Why one of the distribution's installed files is a native image.

    Args:
        distribution: The installed distribution's metadata.
        files: Its recorded files.

    Returns:
        A sentence naming the first offending file, or `None` when every file that is
        on disk begins with something other than a native magic number.
    """
    for entry in files:
        located = Path(os.fspath(distribution.locate_file(entry)))
        try:
            head = located.read_bytes()[:_MAGIC_BYTES]
        except FileNotFoundError:
            continue  # Bytes that are not on disk are bytes no parser loads.
        except OSError as error:
            return f"{entry} is recorded but cannot be read ({type(error).__name__})"
        if is_native(head):
            return f"{entry} is a native image, whatever its extension says"
    return None


def _record_breach(distribution: _Distribution) -> str | None:
    """Why the distribution's `RECORD` fails to show a source-only install.

    Args:
        distribution: The installed distribution's metadata.

    Returns:
        A sentence naming the failure, or `None` when no recorded file is compiled —
        by its first bytes, and failing that by its name.
    """
    files = distribution.files
    if files is None:
        return "no RECORD, so the installed files cannot be listed"
    compiled = compiled_artifacts(files)
    if compiled:
        return f"RECORD lists compiled artifacts: {', '.join(sorted(compiled))}"
    return _content_breach(distribution, files)


def installed_breach(name: str) -> str | None:
    """Why `name`'s installed metadata fails ADR-0183 §5's memory-safety clause.

    Every half of the check is required, and any of them being unreadable is itself the
    breach: the assertion is that the property holds, and metadata this cannot read is
    metadata that grounds nothing.

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
    versions of the same distribution under different resolution markers, and an edge
    is what says which of them a given path reaches.

    Returns:
        The lock's package entries, keyed by normalised name.
    """
    packages: dict[str, list[dict[str, Any]]] = {}
    for package in tomllib.loads(_LOCK.read_text(encoding="utf-8"))["package"]:
        packages.setdefault(_normalise(package["name"]), []).append(package)
    return packages


def _edge_requirement(edge: Mapping[str, Any]) -> str:
    """One `uv.lock` dependency edge, rendered as a requirement string.

    Args:
        edge: A `dependencies` or `optional-dependencies` entry.

    Returns:
        `name[extra,…]==version` when the edge selects a forked version, and the bare
        name otherwise. The marker is deliberately dropped — an edge guarded by
        `sys_platform == "darwin"` is exactly the one the installed closure cannot see,
        and keeping it is the conservative direction.
    """
    name = str(edge["name"])
    extras = f"[{','.join(str(extra) for extra in edge['extra'])}]" if edge.get("extra") else ""
    version = f"=={edge['version']}" if edge.get("version") else ""
    return f"{name}{extras}{version}"


def _locked_requires(name: str, extras: frozenset[str]) -> list[str]:
    """A locked distribution's dependency edges, markers deliberately ignored.

    Args:
        name: A normalised distribution name.
        extras: The canonical extras activated on it so far.

    Returns:
        Requirement strings for the `dependencies` of every locked entry of that name,
        plus the `optional-dependencies` of each activated extra. Empty when the name
        is not in the lock — the absence is reported by :func:`locked_breach`.
    """
    edges: list[Mapping[str, Any]] = []
    for package in _locked_packages().get(name, []):
        edges.extend(package.get("dependencies", []))
        optional = {
            str(canonicalize_name(str(key))): value
            for key, value in package.get("optional-dependencies", {}).items()
        }
        for extra in extras:
            edges.extend(optional.get(extra, []))
    return [_edge_requirement(edge) for edge in edges]


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


def _selected_entries(name: str, edges: Sequence[Requirement]) -> list[dict[str, Any]]:
    """The locked entries of `name` that the parse path's own edges reach.

    An edge with no version selector puts every entry in play, because then any of them
    can be the one installed. An edge that selects a version narrows to it, so a fork
    of the same name that only an unrelated dependency reaches is not this path's to
    fail over.

    Args:
        name: A normalised distribution name.
        edges: The requirements that reached it.

    Returns:
        The `[[package]]` entries to check.
    """
    packages = _locked_packages().get(name, [])
    if any(not edge.specifier for edge in edges):
        return packages
    return [
        package
        for package in packages
        if any(
            edge.specifier.contains(str(package.get("version", "")), prereleases=True)
            for edge in edges
        )
    ]


def locked_breach(name: str, edges: Sequence[Requirement]) -> str | None:
    """Why `name`'s entry in `uv.lock` fails ADR-0183 §5's memory-safety clause.

    Args:
        name: A normalised distribution name.
        edges: The requirements that reached it, whose version selectors decide which
            locked entries are this path's.

    Returns:
        A sentence naming the failure, or `None` when every locked version this path
        reaches publishes only pure-Python wheels.
    """
    if not _locked_packages().get(name):
        return "not in uv.lock, so what an install would fetch cannot be read"
    selected = _selected_entries(name, edges)
    if not selected:
        return "no locked version satisfies the edges that reach it"
    for package in selected:
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
    assert reached.keys() >= PARSE_PATH_ROOTS, (
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
    assert reached.keys() >= PARSE_PATH_ROOTS, (
        f"the locked parse-path closure {sorted(reached)} does not contain "
        f"{sorted(PARSE_PATH_ROOTS)}; the walk is broken, and a check over an empty "
        "set would pass while asserting nothing"
    )

    breaches = {
        name: reason
        for name, edges in sorted(reached.items())
        if (reason := locked_breach(name, edges)) is not None
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
    installed = closure(_roots(), _installed_requires).keys()
    locked = closure(_roots(), _locked_requires).keys()
    assert installed <= locked, (
        f"installed closure {sorted(installed)} is not contained in the locked closure "
        f"{sorted(locked)}, so something is installed that the lock does not record"
    )


_DIAMOND: dict[tuple[str, frozenset[str]], list[str]] = {
    ("wrapper", frozenset()): ["helper"],
    ("helper", frozenset()): [],
    ("helper", frozenset({"native-code"})): ["compiled-thing"],
    ("compiled-thing", frozenset()): [],
}


def _diamond_requires(name: str, extras: frozenset[str]) -> list[str]:
    """The diamond's requirements, keyed by canonical name and canonical extras.

    Args:
        name: A normalised distribution name.
        extras: The canonical extras activated on it so far.

    Returns:
        The requirement strings for that node.
    """
    return _DIAMOND.get((name, extras), [])


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(["helper[native-code]", "wrapper"], id="bare-edge-walked-first"),
        pytest.param(["wrapper", "helper[native-code]"], id="extra-edge-walked-first"),
    ],
)
def test_the_closure_walks_an_extra_discovered_late(order: list[str]) -> None:
    """A name already seen without an extra is revisited when the extra shows up.

    The diamond: the root wants `helper[native-code]` and `wrapper`, and `wrapper`
    wants bare `helper`. A walk that marked `helper` seen on the bare edge would never
    reach `compiled-thing`, which the extra turns on — so a compiled distribution would
    be installed and unchecked. Both orders are exercised because a stack makes the
    outcome depend on which edge is popped first — the *last* string given is walked
    first — and only `bare-edge-walked-first` fails against the name-only walk this
    replaced.

    Args:
        order: The root's requirement strings, in the order they are handed over.
    """
    reached = closure([Requirement(text) for text in order], _diamond_requires)
    assert reached.keys() == {"wrapper", "helper", "compiled-thing"}


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param("native-code", id="canonical"),
        pytest.param("Native_Code", id="underscored-and-capitalised"),
        pytest.param("native.code", id="dotted"),
        pytest.param("NATIVE-CODE", id="upper-case"),
    ],
)
def test_an_extra_is_looked_up_in_its_canonical_spelling(spelling: str) -> None:
    """PEP 685: every spelling of an extra names the same extra.

    A requirement spelling it `helper[Native_Code]` against a lock whose key is
    `native-code` would otherwise activate an extra nothing has, and the compiled
    dependency that extra turns on would never be walked — while the installed check,
    on a platform where it is not installed, stayed green too.

    Args:
        spelling: How the requirement spells the extra.
    """
    reached = closure([Requirement(f"helper[{spelling}]")], _diamond_requires)
    assert "compiled-thing" in reached


def test_a_locked_extra_key_is_matched_in_its_canonical_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lock's `optional-dependencies` key is canonicalised before it is looked up.

    Args:
        monkeypatch: Redirects the lock reader at the crafted entry.
    """
    monkeypatch.setattr(
        _MODULE,
        "_locked_packages",
        lambda: {
            "helper": [
                {
                    "version": "1.0",
                    "optional-dependencies": {"Native.Code": [{"name": "compiled-thing"}]},
                }
            ]
        },
    )
    assert _locked_requires("helper", frozenset({"native-code"})) == ["compiled-thing"]


class _StubDistribution:
    """A distribution whose metadata this module's tests choose.

    Args:
        wheel: The text `read_text("WHEEL")` returns, or `None` for absent.
        root: The directory `locate_file` resolves entries against.
        entries: Recorded file name to its bytes on disk, or `None` for an unreadable
            `RECORD`. A `None` value records a file that `RECORD` lists and the tree
            does not have.
    """

    def __init__(
        self,
        *,
        wheel: str | None,
        root: Path,
        entries: Mapping[str, bytes | None] | None,
    ) -> None:
        self._wheel = wheel
        self._root = root
        self._entries = entries
        for name, content in (entries or {}).items():
            if content is not None:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

    @property
    def files(self) -> Sequence[PurePosixPath] | None:
        """The stubbed `RECORD` listing."""
        return None if self._entries is None else [PurePosixPath(name) for name in self._entries]

    def read_text(self, filename: str) -> str | None:
        """The stubbed `WHEEL` text, and nothing else.

        Args:
            filename: The metadata file requested.

        Returns:
            The configured `WHEEL` text for `"WHEEL"`, `None` otherwise.
        """
        return self._wheel if filename == "WHEEL" else None

    def locate_file(self, path: Any) -> Any:
        """Where a stubbed entry lives.

        Args:
            path: A `RECORD` entry.

        Returns:
            Its path under this stub's root.
        """
        return self._root / str(path)


_PURELIB_WHEEL = "Wheel-Version: 1.0\nGenerator: hatchling 1.31.0\nRoot-Is-Purelib: true\n"

_SOURCE = b"from __future__ import annotations\n"

_ELF = b"\x7fELF\x02\x01\x01\x00 the rest of a shared object"


@pytest.mark.parametrize(
    ("wheel", "entries", "expected"),
    [
        pytest.param(
            _PURELIB_WHEEL,
            {"dateutil/_speedups.cpython-314-x86_64-linux-gnu.so": _ELF},
            "RECORD lists compiled artifacts",
            id="extension-module-in-record",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            {"icalendar/libparse.so.1": _ELF, "icalendar/parser.py": _SOURCE},
            "RECORD lists compiled artifacts",
            id="versioned-shared-library-in-record",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            {"icalendar/parser.DLL": b"MZ\x90\x00", "icalendar/parser.py": _SOURCE},
            "RECORD lists compiled artifacts",
            id="upper-case-windows-library",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            {"icalendar/parser.bundle": b"\xcf\xfa\xed\xfe", "icalendar/parser.py": _SOURCE},
            "RECORD lists compiled artifacts",
            id="mach-o-bundle-by-name",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            {"icalendar/helper": b"\xcf\xfa\xed\xfe", "icalendar/parser.py": _SOURCE},
            "is a native image",
            id="extensionless-native-helper",
        ),
        pytest.param(
            _PURELIB_WHEEL,
            {"icalendar/parser.data": _ELF, "icalendar/parser.py": _SOURCE},
            "is a native image",
            id="native-image-under-a-data-extension",
        ),
        pytest.param(
            "Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp314-cp314-manylinux_2_28_x86_64\n",
            {"icalendar/parser.py": _SOURCE},
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
            {"icalendar/parser.py": _SOURCE},
            "no WHEEL metadata",
            id="absent-wheel-metadata",
        ),
        pytest.param(
            "Wheel-Version: 1.0\nGenerator: hatchling 1.31.0\n",
            {"icalendar/parser.py": _SOURCE},
            "declares no Root-Is-Purelib",
            id="wheel-metadata-without-the-field",
        ),
    ],
)
def test_the_installed_check_reports_a_breach_it_is_shown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    wheel: str | None,
    entries: Mapping[str, bytes | None] | None,
    expected: str,
) -> None:
    """Each way the property can stop holding is a failure rather than a pass.

    Without this, a check that read the wrong metadata field — or read it out of a
    distribution whose `RECORD` it could not open — would be green for the same reason
    a correct one is, and the gate would pin nothing. Two of the cases are artifacts
    whose *name* says nothing, which is what the magic-number pass is for, and three
    are the unreadable ones, because "cannot verify" is the answer most likely to be
    mistaken for "verified".

    Args:
        monkeypatch: Redirects the metadata reader at the stub.
        tmp_path: Where the stubbed distribution's files are written.
        wheel: The `WHEEL` text the stubbed distribution reports.
        entries: The `RECORD` listing, and each entry's bytes.
        expected: A fragment the reported breach must contain.
    """
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: _StubDistribution(wheel=wheel, root=tmp_path, entries=entries),
    )
    reported = installed_breach("icalendar")
    assert reported is not None
    assert expected in reported


def test_a_pure_python_install_is_no_breach(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The installed check is not merely always failing, which the cases above cannot show.

    The listing includes a recorded file that is not on disk, because `RECORD` outlives
    what an uninstall or a `__pycache__` sweep removes, and bytes that are not there are
    bytes no parser loads.

    Args:
        monkeypatch: Redirects the metadata reader at the stub.
        tmp_path: Where the stubbed distribution's files are written.
    """
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: _StubDistribution(
            wheel=_PURELIB_WHEEL,
            root=tmp_path,
            entries={
                "icalendar/parser.py": _SOURCE,
                "icalendar/tests/calendars/issue_156.ics": b"BEGIN:VCALENDAR\n",
                "icalendar/__pycache__/parser.cpython-314.pyc": None,
            },
        ),
    )
    assert installed_breach("icalendar") is None


@pytest.mark.parametrize(
    ("head", "native"),
    [
        pytest.param(b"\x7fELF\x02\x01", True, id="elf"),
        pytest.param(b"MZ\x90\x00", True, id="pe-coff"),
        pytest.param(b"\xcf\xfa\xed\xfe", True, id="mach-o-64"),
        pytest.param(b"\xca\xfe\xba\xbe", True, id="mach-o-universal"),
        pytest.param(b"from ", False, id="python-source"),
        pytest.param(b"BEGI", False, id="calendar-data"),
        pytest.param(b"", False, id="empty-file"),
    ],
)
def test_the_native_image_classifier_at_its_boundaries(head: bytes, native: bool) -> None:
    """A file's first bytes decide it, and nothing else does.

    Args:
        head: A file's leading bytes.
        native: Whether they are a loadable native image.
    """
    assert is_native(head) is native


@pytest.mark.parametrize(
    ("path", "compiled"),
    [
        pytest.param("dateutil/_speedups.cpython-314-x86_64-linux-gnu.so", True, id="ext-linux"),
        pytest.param("icalendar/_parse.cp314-win_amd64.pyd", True, id="ext-windows"),
        pytest.param("icalendar/_parse.dylib", True, id="shared-macos"),
        pytest.param("icalendar/_parse.bundle", True, id="mach-o-bundle"),
        pytest.param("icalendar/libparse.so.1.2", True, id="versioned-so"),
        pytest.param("icalendar/parser.DLL", True, id="upper-case-dll"),
        pytest.param("icalendar/libparse.dll.a", False, id="static-archive"),
        pytest.param("icalendar/parser.py", False, id="source"),
        pytest.param("icalendar/tests/calendars/rfc_9074_alarm.ics", False, id="data"),
        pytest.param("icalendar/so", False, id="extensionless-so"),
    ],
)
def test_the_compiled_artifact_classifier_at_its_boundaries(path: str, compiled: bool) -> None:
    """What the *name*-based second net counts as loadable compiled code.

    `parser.DLL` is loadable on Windows and a case-sensitive check misses it;
    `libparse.dll.a` is a static archive, which the comment on
    :data:`COMPILED_ARTIFACT` excludes deliberately and a suffix-chain check reports
    anyway. `icalendar/so` is why the pattern is anchored to an extension rather than
    matched anywhere in the name. What this net misses on a file that is on disk,
    :func:`is_native` catches.

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


_PURE_WHEEL_URL = "https://files.pythonhosted.org/packages/f1/icalendar-7.2.2-py3-none-any.whl"
_PLATFORM_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/f1/icalendar-8.0-cp314-cp314-macosx_11_0_arm64.whl"
)

_PURE_ENTRY = {"version": "7.2.2", "wheels": [{"url": _PURE_WHEEL_URL}]}
_PLATFORM_ENTRY = {"version": "8.0", "wheels": [{"url": _PLATFORM_WHEEL_URL}]}


@pytest.mark.parametrize(
    ("entries", "edges", "expected"),
    [
        pytest.param(
            [_PLATFORM_ENTRY],
            ["icalendar"],
            "publishes non-pure wheels",
            id="platform-wheel",
        ),
        pytest.param(
            [
                {
                    "version": "8.0",
                    "wheels": [{"url": _PURE_WHEEL_URL}, {"url": _PLATFORM_WHEEL_URL}],
                }
            ],
            ["icalendar"],
            "publishes non-pure wheels",
            id="platform-wheel-beside-a-pure-one",
        ),
        pytest.param(
            [{"version": "8.0", "sdist": {"url": "…/icalendar-8.0.tar.gz"}}],
            ["icalendar"],
            "locks no wheel",
            id="sdist-only",
        ),
        pytest.param(
            [_PURE_ENTRY, _PLATFORM_ENTRY],
            ["icalendar"],
            "publishes non-pure wheels",
            id="unselected-fork-with-an-unqualified-edge",
        ),
        pytest.param(
            [_PURE_ENTRY, _PLATFORM_ENTRY],
            ["icalendar==8.0"],
            "publishes non-pure wheels",
            id="the-parse-path-reaches-the-impure-fork",
        ),
        pytest.param(
            [_PURE_ENTRY],
            ["icalendar==8.0"],
            "no locked version satisfies",
            id="edge-selects-a-version-the-lock-does-not-have",
        ),
    ],
)
def test_the_lock_check_reports_a_breach_it_is_shown(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[dict[str, Any]],
    edges: list[str],
    expected: str,
) -> None:
    """Every way a locked parse path can carry compiled code is a failure.

    The forked cases are why `uv.lock` is read as a list per name: a universal
    resolution can lock two versions under different resolution markers, and an edge
    with no selector leaves either installable.

    Args:
        monkeypatch: Redirects the lock reader at the crafted entries.
        entries: The `[[package]]` entries the lock is made to report.
        edges: The requirements said to reach the name.
        expected: A fragment the reported breach must contain.
    """
    monkeypatch.setattr(_MODULE, "_locked_packages", lambda: {"icalendar": entries})
    reported = locked_breach("icalendar", [Requirement(text) for text in edges])
    assert reported is not None
    assert expected in reported


@pytest.mark.parametrize(
    ("entries", "edges"),
    [
        pytest.param([_PURE_ENTRY], ["icalendar"], id="one-pure-version"),
        pytest.param([_PURE_ENTRY, _PLATFORM_ENTRY], ["icalendar==7.2.2"], id="unrelated-fork"),
    ],
)
def test_a_locked_parse_path_that_reaches_no_platform_wheel_is_no_breach(
    monkeypatch: pytest.MonkeyPatch,
    entries: list[dict[str, Any]],
    edges: list[str],
) -> None:
    """The lock check is not merely always failing, and a fork it does not reach is not its own.

    `unrelated-fork` is the case that would otherwise fail the gate over a dependency
    nothing on the parse path installs: some other requirement forks `icalendar` to a
    platform-wheel 8.0 while the parse path's own edge selects 7.2.2.

    Args:
        monkeypatch: Redirects the lock reader at the crafted entries.
        entries: The `[[package]]` entries the lock is made to report.
        edges: The requirements said to reach the name.
    """
    monkeypatch.setattr(_MODULE, "_locked_packages", lambda: {"icalendar": entries})
    assert locked_breach("icalendar", [Requirement(text) for text in edges]) is None


def test_the_lock_check_reports_a_distribution_it_cannot_read() -> None:
    """A parse-path name absent from the lock is a breach, not a silent pass."""
    reported = locked_breach("no-such-distribution-at-all", [Requirement("no-such-distribution")])
    assert reported is not None
    assert "not in uv.lock" in reported

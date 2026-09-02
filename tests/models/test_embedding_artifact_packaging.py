"""Acceptance tests over real built distributions (ADR-0024 §5).

Everything else in this suite stubs the fastembed backend and never builds
anything, which is exactly the gap ADR-0024 §5 names: "a hook that verifies the
wrong bytes, requests the wrong revision, packages the wrong path, or configures
only the wheel ships green". These tests build a real wheel and a real sdist, and
then a second wheel *from that sdist*, and look inside all three.

They run the build backend **in-process** rather than shelling out to a build
frontend. Two reasons, both load-bearing: a frontend would create an isolated
environment by downloading its build requirements, which defeats the point of
proving the build is offline; and in-process the whole build runs inside
:func:`network_denied`, so "no fetch" is asserted rather than inferred from a
warm cache.

Each distribution carries the whole vendored artifact set — 263 MiB since
ADR-0200 §13 added the two speech models beside the embedding model — and
building all three costs about 45 s, the largest single setup cost in this suite
(#1752). Nothing about them depends on the run: they are a pure function of the
checkout's build inputs. So they are built **once per machine per set of those
inputs** and cached under a digest of them, and every run that digests the same
reuses the build — across xdist workers (``just test-fast`` runs a pytest session
per worker, and each would otherwise build its own — issue #1682), across a
branch's two gate anchors, and across the sibling clones a dispatched wave runs
in. A run whose inputs differ builds, and the cache keeps the few most recently
used builds rather than all of them. One exclusive lock covers reading, building
and pruning, so concurrent runs do one build between them rather than one each
(issue #1748).

The tests that build or load a distribution are skipped when the artifact is not
staged. A staged artifact is the normal state of a working tree — ``uv sync``
builds the project, which runs the hook — so on a developer machine and in CI
these run. The assertions that need no model bytes carry no such skip, so they
still run in a fresh clone, where ADR-0024 §4 leaves the artifact absent.
"""

from __future__ import annotations

import contextlib
import dataclasses
import email.parser
import errno
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import types
import warnings
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

# A build dependency, and therefore a test dependency here: these tests run the
# build backend in-process precisely so no build frontend goes out to fetch it.
from hatchling.build import build_editable, build_sdist, build_wheel
from network_guard import network_denied

from ai_assistant.models import embedding_artifact, fastembed_embedder
from ai_assistant.models.embedding_artifact import (
    ARTIFACT_MANIFEST,
    ARTIFACT_REVISION,
    AUDITED_PACKAGES,
    packaged_artifact_dir,
)
from ai_assistant.models.speech_artifact import SPEECH_ARTIFACTS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from hashlib import _Hash
    from typing import IO

#: The project root, if this is a source checkout rather than an installed copy.
_PROJECT_ROOT = Path(embedding_artifact.__file__).resolve().parents[3]

#: The artifact's path relative to the *package* root, derived from the accessor
#: the runtime uses. Asserting the built distributions carry this exact path is
#: what makes "packages the wrong path" a failure rather than dead weight.
_ARTIFACT_IN_PACKAGE = packaged_artifact_dir().relative_to(_PROJECT_ROOT / "src" / "ai_assistant")

#: The third-party notices for the redistributed model (ADR-0024, Consequences).
#: Its basename is what a consumer looks for, so the assertions below pin it.
_NOTICES = "THIRD-PARTY-NOTICES.md"

#: Nothing in this module works outside a source checkout, so that skip is
#: module-wide. Needing the *artifact staged* is a narrower condition — only a
#: test that builds or loads it does — and it is applied per test below, so that
#: an assertion needing no model bytes still runs in a clean checkout, where
#: ADR-0024 §4 guarantees the artifact is absent until something stages it.
pytestmark = pytest.mark.skipif(
    not (_PROJECT_ROOT / "pyproject.toml").is_file(), reason="not a source checkout"
)

_needs_the_staged_artifact = pytest.mark.skipif(
    bool(embedding_artifact.missing_files(packaged_artifact_dir())),
    reason="the vendored artifact is not staged (run `uv sync`)",
)


def _require_the_staged_artifact() -> None:
    """Skip from inside a fixture, which cannot carry a mark."""
    if embedding_artifact.missing_files(packaged_artifact_dir()):
        pytest.skip("the vendored artifact is not staged (run `uv sync`)")


@contextlib.contextmanager
def _built_in(directory: Path) -> Iterator[None]:
    """Run a hatchling build with ``directory`` as the project root, offline."""
    with contextlib.chdir(directory), network_denied():
        yield


#: The directory the three distributions are written into, under whichever root
#: serves this run — the per-user cache below, or this run's own temp tree.
_SHARED_BUILD = "packaging-distributions"

#: Written last, inside the directory, recording what was built and from which
#: inputs. Its presence is what tells the next reader the build *finished* rather
#: than merely started, so a build that died halfway is rebuilt rather than
#: half-read. The whole directory is renamed into place around it, so neither the
#: record nor the distributions it names can be found half-written.
_BUILT = "built.json"

#: The per-user cache tree, under ``$XDG_CACHE_HOME`` (or ``~/.cache``). Nothing
#: but this module writes there.
_CACHE_TREE = ("ai-assistant-tests", "packaging")

#: The cache-wide lock, held exclusively while a build is read, built or pruned.
#: Its name is not a digest, so :func:`_prune` never takes it for a cached build.
_CACHE_LOCK = "build.lock"

#: A cached build's directory name: the digest of the inputs it was built from.
_CACHED_BUILD = re.compile(r"[0-9a-f]{64}")

#: How many builds the cache keeps. Each is ~0.8 GiB — three distributions, each
#: carrying the whole vendored artifact set — so they cannot simply accumulate.
#: Four is one per clone for the usual shape of a dispatched wave
#: (``~/projects/ai-assistant-N``), each clone on its own branch and so on its own
#: digest, without one clone's build evicting the one another is about to reuse;
#: it bounds the cache at ~3 GiB. Least recently used goes first.
_KEPT_BUILDS = 4

#: How much of a build input to read at a time when digesting it.
_DIGEST_CHUNK = 1 << 20

#: The files outside ``src/`` that every build reads whatever it is configured to
#: do. ``pyproject.toml`` carries the wheel target, the hook declaration, the
#: version, the dependency pins and what :func:`_declared_files` reads back out of
#: it; ``hatch_build.py`` is the hook itself.
_KEYED_FILES = ("pyproject.toml", "hatch_build.py")


@dataclasses.dataclass(frozen=True)
class _Distributions:
    """The three real distributions this module looks inside."""

    digest: str
    checkout_wheel: Path
    sdist: Path
    sdist_wheel: Path


def _run_root(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The temp directory shared by every worker of *this* run, and by no other run.

    Under ``pytest-xdist`` a worker's basetemp is a ``popen-gw*`` directory inside
    the run's own basetemp, so the parent is the run root; a serial run's basetemp
    already is one. `tests/conftest.py` recognises a worker by the same attribute,
    which xdist sets on the worker's config and on nothing else.
    """
    base = tmp_path_factory.getbasetemp()
    return base.parent if hasattr(request.config, "workerinput") else base


@contextlib.contextmanager
def _exclusively(lock: Path) -> Iterator[None]:
    """Hold an exclusive ``flock`` on *lock* for the block.

    ``fcntl`` rather than ``filelock``, which this project does not declare as a
    dependency, and which `service/lock.py` did not need either. The kernel drops
    the lock when the descriptor closes, so a worker killed mid-build releases it
    without leaving the others waiting on a lock nobody holds.
    """
    with lock.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


#: Locks held open for the life of this process. A cached build must not be
#: pruned or rebuilt out from under a run still reading it, and that reading
#: happens after the cache-wide lock is released — so a run holds a *shared* lock
#: on the build it uses until it exits, and everything that would remove one takes
#: that lock exclusively first. The kernel drops these when the process goes,
#: killed or not, so a dead run never keeps a build alive.
_HELD_LOCKS: list[IO[bytes]] = []


def _hold(lock: Path, mode: int) -> IO[bytes] | None:
    """Take *mode* on *lock* without blocking and keep it, or return ``None``."""
    try:
        handle = lock.open("ab")  # deliberately outlives this call: see _HELD_LOCKS
    except OSError:
        return None
    try:
        fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    _HELD_LOCKS.append(handle)
    return handle


def _declared_files(root: Path) -> tuple[str, ...]:
    """The files ``pyproject.toml`` puts into a distribution by naming them.

    ``readme`` becomes the long description carried in wheel metadata and in
    ``PKG-INFO``, and every ``license-files`` entry — a glob pattern, by PEP 639 —
    is copied into both distributions. They are build inputs exactly as the hook
    is, and they are read back out of the build configuration rather than listed
    in this module so that declaring a fourth one cannot quietly leave it out of
    the key (adversarial review of this change, round 4, on a `README.md` that was
    listed nowhere).

    Args:
        root: The project root to read the declaration from.

    Returns:
        The declared files that exist, as paths relative to *root*, sorted.
    """
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    except OSError, ValueError, KeyError, TypeError:
        return ()
    declared = project.get("license-files")
    patterns = [name for name in declared if isinstance(name, str)] if declared else []
    readme = project.get("readme")
    if isinstance(readme, dict):
        readme = readme.get("file")
    if isinstance(readme, str):
        patterns.append(readme)
    return tuple(
        sorted(
            {
                path.relative_to(root).as_posix()
                for pattern in patterns
                if not pattern.startswith("/") and ".." not in pattern
                for path in root.glob(pattern)
                if path.is_file()
            }
        )
    )


def _is_derived(path: Path) -> bool:
    """Is *path* something the interpreter wrote rather than something we ship?"""
    return path.suffix == ".pyc" or "__pycache__" in path.parts


def _hash_file(digest: _Hash, path: Path) -> None:
    """Fold *path*'s bytes into *digest*, a chunk at a time."""
    with path.open("rb") as handle:
        while chunk := handle.read(_DIGEST_CHUNK):
            digest.update(chunk)


def _build_inputs_digest(root: Path) -> str:
    """Digest what decides the three distributions, cheaply enough to do every run.

    Everything a build reads is content-hashed: `pyproject.toml`, the build hook,
    every file that configuration declares (:func:`_declared_files` — the readme
    and the licence files), and every file under ``src/`` that a build packages —
    the 321 MiB of vendored model artifacts included. Those cost 0.37 s of the
    0.42 s this takes, against the ~45 s build it decides whether to skip, so
    nothing is keyed on a cheaper proxy for them: an earlier revision keyed them
    by size and modification time, and an equal-length rewrite that restored the
    timestamp then read a distribution built from other bytes, which is precisely
    what this module exists to catch (adversarial review of this change, round 2).

    This module's own bytes are keyed in too. The digest deliberately does not
    cover the rest of the repository, though hatchling's default sdist carries
    it: no assertion in this module reads an sdist member outside ``src/``,
    ``hatch_build.py``, the notices and ``PKG-INFO``. Keying this file is what
    keeps that true — an assertion added or changed below moves the digest, so it
    is evaluated against a freshly built distribution rather than one cached under
    the previous reading of what mattered.

    ``__pycache__`` and ``.pyc`` files are skipped: hatchling's VCS-aware file
    selection leaves them out of the distributions, and they would otherwise make
    an unchanged checkout digest differently depending on what had lately
    imported it.

    Args:
        root: The project root to digest.

    Returns:
        The digest, as 64 hexadecimal characters.
    """
    digest = hashlib.sha256()
    digest.update(b"ai-assistant packaging build inputs v1\n")
    digest.update(f"hatchling {importlib.metadata.version('hatchling')}\n".encode())
    digest.update(f"python {sys.version}\n".encode())
    _hash_file(digest, Path(__file__))
    for name in _KEYED_FILES + _declared_files(root):
        path = root / name
        if not path.is_file():
            digest.update(f"\n{name} absent\n".encode())
            continue
        digest.update(f"\n{name} {path.stat().st_size}\n".encode())
        _hash_file(digest, path)
    source = root / "src"
    for path in sorted(source.rglob("*")) if source.is_dir() else []:
        if not path.is_file() or _is_derived(path):
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(f"\n{relative} {path.stat().st_size}\n".encode())
        _hash_file(digest, path)
    return digest.hexdigest()


def _private_directory(path: Path) -> Path | None:
    """Create *path* as a directory only this user can enter, or return ``None``.

    The discipline `justfile`'s ``test-fast`` slot code uses, and for the same
    reason: one that is a symlink, is not ours, or is reachable by anyone else is
    refused rather than used. Refusing returns ``None`` instead of failing,
    because the cache is an optimisation — the caller then builds into this run's
    own temp tree, which is what this module did before the cache existed.

    ``parents=False``: only the directory named here is created, and the caller
    walks down one level at a time so that every level it makes is checked. A
    ``parents=True`` here would create the levels above at the default mode and
    leave them unchecked, and a directory nobody vouched for is exactly what an
    attacker needs to swap this one out from under a caller after it passed
    (adversarial review of this change, round 1).
    """
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            return None
        info = path.stat()
    except OSError:
        return None
    if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
        return None
    return path


def _trusted_root(path: Path) -> bool:
    """May directories this process makes below *path* be trusted once made?

    Two shapes qualify. One that this user owns and only this user may write to —
    what ``$XDG_CACHE_HOME`` and ``~/.cache`` normally are. And a world-writable
    directory with the sticky bit, which is what the system temp directory is:
    anyone may create an entry there, but only an entry's owner may rename or
    remove it, so a directory of ours below it cannot be swapped out.

    Anything else is refused — a shared directory another account can write to
    without the sticky bit, say, which `XDG_CACHE_HOME` may perfectly well name.
    A level above the cache that somebody else can write to is a level the whole
    checked tree can be renamed away from and replaced with a symlink after it
    passed its check, and nothing below it is worth checking (adversarial review
    of this change, round 2).
    """
    try:
        info = path.stat()
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        return False
    if info.st_mode & stat.S_ISVTX and info.st_mode & 0o002:
        return True
    return info.st_uid == os.getuid() and not info.st_mode & 0o022


def _cache_root(path: Path) -> Path | None:
    """*path* as a root to build the cache under, made if it is not there yet.

    A root that does not exist is the ordinary state of a fresh environment — a
    new ``$HOME`` has no ``.cache``, and ``$XDG_CACHE_HOME`` may name a directory
    nothing has made yet — and refusing one would leave the cache permanently off
    exactly where it was most wanted (adversarial review of this change, round 3).
    Making it is this process's own act, so it is made ``0700`` and checked like
    every level below it, and only below a parent that is itself a trusted root: a
    root nobody vouched for is no better than a level nobody vouched for.

    Resolved first, and it is the resolved path that is kept. ``$XDG_CACHE_HOME``
    may perfectly well name a symlink — people do move a cache onto another
    disk — and checking one tells you only about wherever it pointed at the time:
    whoever owns the link can repoint it afterwards, and every later open would
    follow it (adversarial review of this change, round 4). Resolving leaves a
    path with no link in it to repoint.
    """
    resolved = path.resolve()
    if _trusted_root(resolved):
        return resolved
    if resolved.exists() or not _trusted_root(resolved.parent):
        return None
    return _private_directory(resolved)


def _cache_directory() -> Path | None:
    """The directory cached builds live in, or ``None`` if it cannot be trusted.

    The root comes from the XDG base directory specification — ``$XDG_CACHE_HOME``,
    else ``~/.cache`` — and where there is no home directory at all, from the
    system temp directory, whose per-user level below it is then this process's to
    make and to vouch for rather than part of the root. The root is resolved by
    :func:`_cache_root` and every level below it by :func:`_private_directory`,
    each created before the next is, so no unchecked directory sits anywhere above
    the cache: to replace a level, somebody would have to write to its parent, and
    every parent is by then either a ``0700`` directory of ours or a root that
    passed.

    Nothing here raises. An unusable cache is what the fixture's fallback is for,
    so a filesystem that refuses any part of this — a name it will not resolve, a
    directory it will not make — is a ``None`` like every other refusal, and not
    an error that would fail every test needing a distribution over an
    optimisation that did not come off.

    ``os.environ`` rather than `core.config.Settings`: this is a test harness
    finding a scratch directory on the machine it runs on, not the product
    reading its configuration.
    """
    xdg = os.environ.get("XDG_CACHE_HOME", "")
    home = os.environ.get("HOME", "")
    ours: tuple[str, ...] = _CACHE_TREE
    if xdg.startswith("/"):
        path = Path(xdg)
    elif home.startswith("/"):
        path = Path(home) / ".cache"
    else:
        path = Path(tempfile.gettempdir())
        ours = (f"ai-assistant-{os.getuid()}", *_CACHE_TREE)
    try:
        root = _cache_root(path)
        if root is None:
            return None
        path = root
        for name in ours:
            checked = _private_directory(path / name)
            if checked is None:
                return None
            path = checked
    except OSError:
        return None
    return path


def _build_the_distributions(into: Path, digest: str) -> _Distributions:
    """Build the wheel, the sdist, and the wheel from that sdist, all under *into*.

    The sdist-derived wheel is the ``--no-binary`` install path: the one that
    would expose a hook configured for the wheel target only, or an sdist that
    shipped the code but not the artifact. It builds from the unpacked sdist,
    which has no git checkout to fetch from and no network to fetch over.
    """
    checkout_wheel_dir = into / "checkout-wheel"
    checkout_wheel_dir.mkdir(parents=True, exist_ok=True)
    with _built_in(_PROJECT_ROOT):
        checkout_wheel = checkout_wheel_dir / build_wheel(str(checkout_wheel_dir))

    sdist_dir = into / "sdist"
    sdist_dir.mkdir(parents=True, exist_ok=True)
    with _built_in(_PROJECT_ROOT):
        sdist = sdist_dir / build_sdist(str(sdist_dir))

    unpacked = into / "sdist-unpacked"
    shutil.rmtree(unpacked, ignore_errors=True)  # a previous attempt may have died here
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")  # built by this test
    (root,) = list(unpacked.iterdir())
    sdist_wheel_dir = into / "sdist-wheel"
    sdist_wheel_dir.mkdir(parents=True, exist_ok=True)
    with _built_in(root):
        sdist_wheel = sdist_wheel_dir / build_wheel(str(sdist_wheel_dir))
    # The unpacked sdist is a build *input* holding a fourth copy of the same
    # vendored bytes, and nothing reads it once the wheel is out of it (#1682).
    shutil.rmtree(unpacked)

    return _Distributions(
        digest=digest, checkout_wheel=checkout_wheel, sdist=sdist, sdist_wheel=sdist_wheel
    )


def _build_into_place(destination: Path, digest: str) -> None:
    """Build the three distributions and move them to *destination* in one step.

    They are built in a sibling staging directory and renamed, so *destination*
    is either absent or complete: a build killed halfway leaves the staging
    directory behind — which the next prune removes — and never a directory whose
    record names more than it holds. The record goes in last, and names the digest
    the build was keyed on, so a reader checks what is on disk against its own
    inputs rather than against the name it looked the directory up by.
    """
    staging = destination.parent / f".{destination.name}.building"
    shutil.rmtree(staging, ignore_errors=True)  # a previous attempt may have died here
    staging.mkdir(parents=True)
    distributions = _build_the_distributions(staging, digest)
    (staging / _BUILT).write_text(
        json.dumps(
            {
                "digest": digest,
                "distributions": {
                    key: {
                        "path": getattr(distributions, key).relative_to(staging).as_posix(),
                        "sha256": _file_digest(getattr(distributions, key)),
                    }
                    for key in _RECORDED
                },
            }
        )
    )
    shutil.rmtree(destination, ignore_errors=True)
    staging.replace(destination)


#: The distributions a cache record names, in the order this module reads them.
_RECORDED = ("checkout_wheel", "sdist", "sdist_wheel")


def _file_digest(path: Path) -> str:
    """The SHA-256 of *path*'s bytes, as hexadecimal."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _matches(directory: Path, recorded: object) -> bool:
    """Is one recorded distribution present, inside *directory*, and byte for byte it?

    Byte for byte rather than archive-shaped. Reading the three back costs 0.78 s
    against the ~45 s build being skipped, and every cheaper test has a gap to be
    argued about rather than closed: a sweep that truncates a ``.tar.gz`` after
    its first member leaves one that still opens and still yields a member, and an
    earlier revision of this reused it (adversarial review of this change, round
    3). What the record says is there is now exactly what is there, byte for byte,
    or the entry is rebuilt.

    The recorded name must also stay inside *directory*. It is read back from a
    file, and joining an unchecked relative path to a directory is how a record
    comes to name something else entirely.

    Every way the filesystem can refuse the answer is a "no" rather than an error.
    The sweep this exists to survive can just as well remove a distribution
    *while* it is being read as before, and an `OSError` escaping here would fail
    the packaging tests with a missing file — the very outcome checking the entry
    is for (adversarial review of this change, round 5).
    """
    if not isinstance(recorded, dict):
        return False
    name, expected = recorded.get("path"), recorded.get("sha256")
    if not isinstance(name, str) or not isinstance(expected, str):
        return False
    try:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            return False
        return _file_digest(path) == expected
    except OSError:
        return False


def _usable(directory: Path, recorded: Mapping[str, object], digest: str) -> bool:
    """Is *recorded* a complete cache entry that this checkout may read?

    Two things it is not. A record for **different inputs** — the digest it names
    is not the reader's — which is what stands between a changed input and a stale
    answer on the fallback path, whose directory name carries no digest.

    And a record whose **distributions are not what it says they are**. A cached
    build outlives the run that made it, so, unlike the run-scoped build this
    replaces, it can be found half-removed by anything that sweeps a cache
    directory: a record believed on its own would then name a file that is gone or
    cut short, and fail every run from that moment until somebody cleared the
    cache by hand (adversarial review of this change, round 1). Checked here
    instead, the entry is simply rebuilt.

    Args:
        directory: The directory the record was read from.
        recorded: The record.
        digest: The digest of the reader's own build inputs.

    Returns:
        Whether the entry may be used as it stands.
    """
    if recorded.get("digest") != digest:
        return False
    distributions = recorded.get("distributions")
    if not isinstance(distributions, dict) or set(distributions) != set(_RECORDED):
        return False
    return all(_matches(directory, distributions[key]) for key in _RECORDED)


def _distribution(directory: Path, recorded: Mapping[str, object], key: str) -> Path:
    """The file *recorded* names for *key*, under *directory*."""
    distributions = recorded["distributions"]
    assert isinstance(distributions, dict)
    return directory / str(distributions[key]["path"])


def _recorded(directory: Path, digest: str) -> _Distributions | None:
    """The distributions *directory* holds for *digest*, or ``None`` if it holds none.

    ``None`` covers every way there is nothing to read here: no record, a record
    that will not parse, one for other inputs, and one whose distributions are no
    longer what it says they are (:func:`_usable`).
    """
    built = directory / _BUILT
    recorded: dict[str, object] = {}
    if built.is_file():
        with contextlib.suppress(ValueError, OSError):
            loaded = json.loads(built.read_text())
            recorded = loaded if isinstance(loaded, dict) else {}
    if not _usable(directory, recorded, digest):
        return None
    return _Distributions(
        digest=str(recorded["digest"]),
        **{key: _distribution(directory, recorded, key) for key in _RECORDED},
    )


def _read_or_build(directory: Path, digest: str) -> _Distributions:
    """Return the distributions in *directory*, building them there if need be.

    The caller holds a lock that makes *directory* its own to replace, so no
    reader can see a record written by a build still in progress, no two runs can
    build the same directory, and no run has its distributions removed while it is
    reading them.
    """
    found = _recorded(directory, digest)
    if found is not None:
        return found
    _build_into_place(directory, digest)
    built = _recorded(directory, digest)
    assert built is not None, f"the build just made in {directory} cannot be read back"
    return built


def _cached(cache: Path, digest: str) -> _Distributions | None:
    """The cache's answer for *digest*, or ``None`` if this run must build its own.

    Called under the cache-wide lock, so nothing else is resolving a build while
    this runs, and the only thing another run can be doing is *reading* one it
    resolved earlier.

    That is what the per-build lock distinguishes. Taken **exclusively**, it says
    no other run is reading this build, and only then may it be replaced — a
    rebuild removes the directory, and doing that under a reader would fail its
    tests with a missing file (adversarial review of this change, round 2, which
    also gives the way in: a record damaged from outside while a run holds it).
    The lock is downgraded to shared as soon as the entry is good, because it is
    held for the whole session and every other run would otherwise queue behind
    this one's tests rather than behind its build.

    Where the exclusive lock cannot be had, the entry is another run's to keep:
    it is read if it is sound and, if it is not, left exactly as it is — this run
    builds for itself instead of repairing something in use.
    """
    entry = cache / digest
    lock = cache / f"{digest}.lock"
    exclusive = _hold(lock, fcntl.LOCK_EX)
    if exclusive is not None:
        distributions = _read_or_build(entry, digest)
        fcntl.flock(exclusive.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        os.utime(entry)
        return distributions
    if _hold(lock, fcntl.LOCK_SH) is None:
        return None
    found = _recorded(entry, digest)
    if found is not None:
        os.utime(entry)
    return found


def _last_used(build: Path) -> float:
    """When *build* was last read or written, or ``0.0`` if it is not there."""
    try:
        return build.stat().st_mtime
    except OSError:
        return 0.0


def _remove_build(cache: Path, name: str) -> None:
    """Remove one cached build, unless a run is still holding it.

    The shared lock a user takes is what says "still reading"; this takes the same
    file exclusively and without blocking, so a build in use is skipped rather
    than waited for. The caller holds the cache-wide lock, under which a run also
    takes its shared lock — so no run can start holding a build between this test
    and the removal that follows it.
    """
    lock = cache / f"{name}.lock"
    try:
        handle = lock.open("ab")
    except OSError:
        return
    with handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # another run is reading this build
        shutil.rmtree(cache / name, ignore_errors=True)
        lock.unlink(missing_ok=True)


def _prune(cache: Path, keep: str) -> None:
    """Leave *keep* and the ``_KEPT_BUILDS - 1`` most recently used other builds.

    Called under the cache-wide lock, before the build that will be used is read
    or made, so the space a departing build frees is available to the one arriving.
    Only names that are digests are considered, so nothing this module did not
    write is ever removed from that directory; a staging directory is removed
    outright, because no build can be in flight while its lock is held here.
    """
    builds: set[str] = set()
    for entry in sorted(cache.iterdir()):
        if entry.is_symlink():
            continue
        if entry.is_dir() and entry.name.startswith("."):
            shutil.rmtree(entry, ignore_errors=True)  # a build killed mid-flight
            continue
        name = entry.name.removesuffix(".lock")
        if name != keep and _CACHED_BUILD.fullmatch(name):
            builds.add(name)
    ordered = sorted(builds, key=lambda name: _last_used(cache / name), reverse=True)
    for name in ordered[_KEPT_BUILDS - 1 :]:
        _remove_build(cache, name)


@pytest.fixture(scope="session")
def built_distributions(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> _Distributions:
    """The three distributions, built once per machine per set of build inputs.

    They are a pure function of the checkout's build inputs, so they are cached
    under a digest of those inputs and reused by every run that digests the same:
    across xdist workers, across a branch's two gate anchors, and across the
    sibling clones a dispatched wave runs in. A run whose inputs differ builds its
    own, and the cache keeps the few most recently used rather than all of them.

    Reading, building and pruning all happen under one exclusive lock, so five
    clones gating at once do one build between them rather than five: the first to
    arrive builds, the rest block and then read what it left. The distributions
    themselves are read *after* that lock is released — nothing mutates a build
    once its record is in place — which is why each run also takes a shared lock
    on the build it is using and holds it for the session: a later run neither
    prunes nor replaces a build that lock says is in use, and builds its own
    instead.

    Where no private cache directory can be had, the build goes into this run's
    own temp tree under the same lock discipline, which is what this fixture did
    before the cache existed (#1682). The cache is an optimisation; its absence
    changes no assertion in this module.
    """
    _require_the_staged_artifact()
    digest = _build_inputs_digest(_PROJECT_ROOT)
    cache = _cache_directory()
    if cache is not None:
        with _exclusively(cache / _CACHE_LOCK):
            _prune(cache, keep=digest)
            cached = _cached(cache, digest)
        if cached is not None:
            return cached
    warnings.warn(
        "the packaging build is not being cached for this machine; building it"
        " into this run's own temp tree instead",
        stacklevel=1,
    )
    root = _run_root(request, tmp_path_factory)
    shared = root / _SHARED_BUILD
    shared.mkdir(parents=True, exist_ok=True)
    with _exclusively(root / f"{_SHARED_BUILD}.lock"):
        return _read_or_build(shared, digest)


@pytest.fixture(scope="session")
def checkout_wheel(built_distributions: _Distributions) -> Path:
    """A wheel built from this git checkout, with the network denied throughout."""
    return built_distributions.checkout_wheel


@pytest.fixture(scope="session")
def sdist(built_distributions: _Distributions) -> Path:
    """An sdist built from this git checkout, with the network denied throughout."""
    return built_distributions.sdist


@pytest.fixture(scope="session")
def sdist_wheel(built_distributions: _Distributions) -> Path:
    """A wheel built from the unpacked sdist — the ``--no-binary`` install path."""
    return built_distributions.sdist_wheel


def _wheel_members(wheel: Path) -> Mapping[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _assert_carries_the_verified_artifact(members: Mapping[str, bytes], prefix: Path) -> None:
    for name, expected in ARTIFACT_MANIFEST.items():
        entry = str(prefix / _ARTIFACT_IN_PACKAGE / name)
        assert entry in members, f"{entry} is not in the distribution"
        assert hashlib.sha256(members[entry]).hexdigest() == expected, entry


def test_the_wheel_carries_the_verified_artifact(checkout_wheel: Path) -> None:
    # Every file's SHA-256 matches the recorded manifest — the verified bytes,
    # not merely *some* valid ONNX file at roughly the right place.
    _assert_carries_the_verified_artifact(_wheel_members(checkout_wheel), Path("ai_assistant"))


def test_the_sdist_carries_the_verified_artifact(sdist: Path) -> None:
    with tarfile.open(sdist) as archive:
        root = Path(archive.getnames()[0]).parts[0]
        members = {}
        for name, expected in ARTIFACT_MANIFEST.items():
            entry = str(Path(root) / "src" / "ai_assistant" / _ARTIFACT_IN_PACKAGE / name)
            extracted = archive.extractfile(entry)
            assert extracted is not None, f"{entry} is not in the sdist"
            members[name] = hashlib.sha256(extracted.read()).hexdigest()
            assert members[name] == expected, entry


def test_the_sdist_derived_wheel_carries_the_verified_artifact(sdist_wheel: Path) -> None:
    _assert_carries_the_verified_artifact(_wheel_members(sdist_wheel), Path("ai_assistant"))


@_needs_the_staged_artifact
def test_an_editable_wheel_does_not_duplicate_the_artifact(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """`uv sync` must not copy 58 MiB into site-packages.

    An editable install resolves ``ai_assistant`` to the source tree, where the
    hook has just staged and verified the artifact, so shipping a second copy in
    the editable wheel would duplicate it in every environment. The hook still
    runs its acquire-and-verify — that is what leaves a working tree able to
    embed offline — it just does not package the result.
    """
    out = tmp_path_factory.mktemp("editable")
    with _built_in(_PROJECT_ROOT):
        name = build_editable(str(out))

    members = _wheel_members(out / name)
    assert not [entry for entry in members if "_vendor" in entry]
    assert not embedding_artifact.missing_files(packaged_artifact_dir())


def test_the_sdist_carries_the_build_hook(sdist: Path) -> None:
    # Without it the sdist cannot rebuild; with it, and no artifact, it would
    # fetch. The two files travel together or the `--no-binary` path is broken.
    with tarfile.open(sdist) as archive:
        assert any(name.endswith("/hatch_build.py") for name in archive.getnames())


def _notices_in_the_checkout() -> bytes:
    return (_PROJECT_ROOT / _NOTICES).read_bytes()


def test_the_notices_name_every_revision_that_ships() -> None:
    """The notices describe *these* bytes, not the models in general.

    A re-pin that moved an artifact without moving the notices would leave the
    file naming a commit the distribution no longer carries, which is the one way
    an accurate notice goes stale on its own. The *declared* commit is what a
    recipient reads, so this pins those rows rather than any mention of a SHA.

    Compared as a set against every artifact this distribution redistributes —
    the embedding model and, since ADR-0200, the two speech models — so that
    adding a fourth without its notice fails here rather than shipping silently.
    """
    notices = _notices_in_the_checkout().decode()
    declared = re.findall(r"^\|\s*Pinned commit\s*\|\s*`([0-9a-f]+)`\s*\|$", notices, re.MULTILINE)

    assert set(declared) == {ARTIFACT_REVISION} | {
        artifact.revision for artifact in SPEECH_ARTIFACTS
    }
    assert len(declared) == len(set(declared))


def test_the_notices_are_declared_as_a_licence_file() -> None:
    """The declaration is what puts the notices in a distribution.

    Asserted here as well as in the built wheel and sdist because this one needs
    no model bytes: in a fresh clone, where the artifact is not staged and the
    build assertions skip, this is what catches `license-files` regressing.
    """
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text())
    assert _NOTICES in pyproject["project"]["license-files"]


@pytest.mark.parametrize("wheel_fixture", ["checkout_wheel", "sdist_wheel"])
def test_the_wheel_carries_the_third_party_notices(
    wheel_fixture: str, request: pytest.FixtureRequest
) -> None:
    """ADR-0024's Consequences: redistributing the weights means shipping notices.

    PEP 639 puts declared licence files under ``.dist-info/licenses/`` and lists
    them in METADATA, so both are asserted — a wheel that carried the bytes but
    did not declare them would not be discoverable by a licence scanner. Both
    build sources are checked: the ``--no-binary`` install path ships the same
    weights from a *different* project root, so it owes the same notices.
    """
    wheel: Path = request.getfixturevalue(wheel_fixture)
    members = _wheel_members(wheel)
    (entry,) = [name for name in members if name.endswith(f"/licenses/{_NOTICES}")]
    assert members[entry] == _notices_in_the_checkout()

    (metadata_entry,) = [name for name in members if name.endswith(".dist-info/METADATA")]
    metadata = email.parser.BytesParser().parsebytes(members[metadata_entry])
    assert _NOTICES in (metadata.get_all("License-File") or [])


def test_the_sdist_carries_the_third_party_notices(sdist: Path) -> None:
    # The sdist carries the notices at its root and declares them in PKG-INFO —
    # and, being the root of the `--no-binary` build, is also what lets the
    # wheel built from it carry them (asserted above).
    with tarfile.open(sdist) as archive:
        root = Path(archive.getnames()[0]).parts[0]
        extracted = archive.extractfile(str(Path(root) / _NOTICES))
        assert extracted is not None, f"{_NOTICES} is not in the sdist"
        assert extracted.read() == _notices_in_the_checkout()

        pkg_info = archive.extractfile(str(Path(root) / "PKG-INFO"))
        assert pkg_info is not None
        metadata = email.parser.BytesParser().parsebytes(pkg_info.read())
        assert _NOTICES in (metadata.get_all("License-File") or [])


@pytest.mark.parametrize("wheel_fixture", ["checkout_wheel", "sdist_wheel"])
async def test_the_packaged_artifact_embeds_with_the_network_denied(
    wheel_fixture: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bytes each wheel ships load and embed offline, at the packaged path.

    The wheel is unpacked and the embedder pointed at *its* copy of the artifact,
    at the path derived from the runtime accessor — so this fails if the build
    packaged the artifact somewhere the embedder does not look, or packaged bytes
    ONNX Runtime cannot load. The embedder code is this checkout's, which is the
    same code the wheel contains; what the wheel uniquely contributes, and what
    is under test here, is the data.

    Only the members under that path are unpacked, at the same relative paths the
    wheel records them under: the embedder reads nothing else, and unpacking the
    whole wheel wrote a further 263 MiB of speech artifacts into the run's temp
    tree per parametrisation (#1682). A wheel that packaged the artifact anywhere
    else still fails here — there is then nothing to unpack and nothing to load —
    which is why the emptiness is asserted rather than left to the loader.
    """
    wheel: Path = request.getfixturevalue(wheel_fixture)
    prefix = f"ai_assistant/{_ARTIFACT_IN_PACKAGE.as_posix()}/"
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist() if name.startswith(prefix)]
        assert members, f"the wheel carries nothing under {prefix}"
        archive.extractall(tmp_path, members)  # noqa: S202  # built by this test
    unpacked = tmp_path / "ai_assistant" / _ARTIFACT_IN_PACKAGE
    monkeypatch.setattr(fastembed_embedder, "packaged_artifact_dir", lambda: unpacked)

    with network_denied():
        embedder = fastembed_embedder.FastEmbedEmbedder()
        vectors = await embedder.embed(["the user likes espresso"])

    assert len(vectors) == 1
    assert len(vectors[0]) == embedder.dimensions


def test_the_wheel_metadata_carries_the_exact_pins(checkout_wheel: Path) -> None:
    """All four audited packages are ``==``-pinned in what a user installs.

    Pinning them in ``pyproject.toml`` is not the claim; carrying the pins in the
    published METADATA is, because a wheel is what resolves dependencies on a
    user's machine (ADR-0024 §3).
    """
    members = _wheel_members(checkout_wheel)
    (metadata_entry,) = [name for name in members if name.endswith(".dist-info/METADATA")]
    metadata = email.parser.BytesParser().parsebytes(members[metadata_entry])
    requirements = set(metadata.get_all("Requires-Dist") or [])

    for package in AUDITED_PACKAGES:
        installed = importlib.metadata.version(package)
        assert f"{package}=={installed}" in requirements, package


def test_the_declared_pins_match_the_locked_versions() -> None:
    # The pins are only meaningful if they are the versions `uv sync` resolves;
    # a pin that drifted from the lockfile would pin a stack nobody runs.
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text())
    declared = set(pyproject["project"]["dependencies"])

    for package in AUDITED_PACKAGES:
        assert f"{package}=={importlib.metadata.version(package)}" in declared, package


def test_the_artifact_is_not_committed_to_git() -> None:
    # ADR-0024 §4: 58 MiB of incompressible binary must never enter history.
    tracked = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--", str(packaged_artifact_dir().parent)],  # noqa: S607
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode != 0:
        pytest.skip("not a git working tree")
    assert tracked.stdout.strip() == "", "the vendored artifact is tracked by git"


@_needs_the_staged_artifact
@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
async def test_the_packaged_artifact_loads_without_a_usable_temp_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel that needs nothing from the network must not need `/tmp` either.

    `fastembed` calls `define_cache_dir` — which *creates* the directory — before
    it honours `specific_model_path`, so an unset `cache_dir` makes every load
    `mkdir` under the system temp directory. In a read-only container that fails
    an installation holding every byte it will read. Found by adversarial review
    of this change; this is the regression test.
    """
    unwritable = tmp_path / "readonly"
    unwritable.mkdir()
    unwritable.chmod(0o500)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(unwritable / "denied"))

    with network_denied():
        vectors = await fastembed_embedder.FastEmbedEmbedder().embed(["the user likes espresso"])

    assert len(vectors) == 1


def test_the_distributions_were_built_from_this_checkouts_inputs(
    built_distributions: _Distributions,
) -> None:
    """A reused build is only sound if it was keyed on the inputs it is read under.

    This is the assertion the cache turns on. Whatever `built_distributions`
    handed back — a build this run made, one a previous run left behind, or one
    another clone built — the record found *on disk beside it* names the digest of
    this checkout's build inputs. A build keyed on anything else is rebuilt rather
    than returned, so reaching this assertion at all is most of what it says.
    """
    assert built_distributions.digest == _build_inputs_digest(_PROJECT_ROOT)


#: A source file of the synthetic checkout below: packaged, so content-hashed.
_SYNTHETIC_SOURCE = Path("src") / "ai_assistant" / "models" / "embedding_artifact.py"

#: A vendored artifact of the synthetic checkout below: 321 MiB of these are
#: content-hashed like everything else the build reads.
_SYNTHETIC_ARTIFACT = (
    Path("src") / "ai_assistant" / "models" / "_vendor" / "bge-small-en-v1.5" / "model.onnx"
)


#: The synthetic checkout's build configuration, declaring the same kinds of file
#: the real one does, so that `_declared_files` has something to find.
_SYNTHETIC_PYPROJECT = """[project]
name = "ai-assistant"
version = "{version}"
readme = "README.md"
license-files = ["LICENSE", "THIRD-PARTY-NOTICES.md"]
"""


def _rewritten_in_place(path: Path) -> None:
    """Replace *path*'s bytes with as many others, leaving its timestamp alone."""
    info = path.stat()
    path.write_bytes(bytes(byte ^ 0x20 for byte in path.read_bytes()))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert path.stat().st_size == info.st_size


def _synthetic_checkout(root: Path) -> Path:
    """Write the smallest tree carrying one file of every kind the digest keys.

    A real checkout would do, but it is 340 MiB and a perturbation of it would
    have to be undone; this is the same shape in five files, so each perturbation
    below gets a fresh one and nothing has to be put back.
    """
    (root / "src" / "ai_assistant" / "models" / "_vendor" / "bge-small-en-v1.5").mkdir(parents=True)
    (root / "pyproject.toml").write_text(_SYNTHETIC_PYPROJECT.format(version="0.1.0"))
    (root / "hatch_build.py").write_text("# the build hook\n")
    (root / "README.md").write_text("# ai-assistant\n")
    (root / "LICENSE").write_text("the licence\n")
    (root / _NOTICES).write_text("| Pinned commit | `0123abc` |\n")
    (root / _SYNTHETIC_SOURCE).write_text("ARTIFACT_REVISION = '0123abc'\n")
    (root / _SYNTHETIC_ARTIFACT).write_bytes(b"the weights")
    return root


def test_two_identical_checkouts_digest_the_same(tmp_path: Path) -> None:
    """What makes a cached build reusable across clones, not merely across runs.

    The digest is over relative paths and file contents, so two checkouts of the
    same tree at different paths agree — which is the whole of "built once per
    machine" when a dispatched wave runs five clones of one commit.
    """
    first = _synthetic_checkout(tmp_path / "one")
    second = tmp_path / "two"
    shutil.copytree(first, second)

    assert _build_inputs_digest(second) == _build_inputs_digest(first)


def test_a_compiled_source_file_does_not_move_the_digest(tmp_path: Path) -> None:
    """Importing the tree must not invalidate a build made from it.

    Hatchling leaves `__pycache__` out of the distributions, so a run that
    imported the checkout produces the same three distributions as one that did
    not — and a digest that said otherwise would rebuild on the strength of a file
    no build ever reads.
    """
    root = _synthetic_checkout(tmp_path)
    before = _build_inputs_digest(root)
    cache = root / _SYNTHETIC_SOURCE.parent / "__pycache__"
    cache.mkdir()
    (cache / "embedding_artifact.cpython-314.pyc").write_bytes(b"\x00compiled")

    assert _build_inputs_digest(root) == before


#: One change of each kind that must reach a rebuild. Each is applied to a fresh
#: synthetic checkout, so they neither depend on nor undo one another.
_PERTURBATIONS: Mapping[str, Callable[[Path], object]] = {
    "the project metadata": lambda root: (root / "pyproject.toml").write_text(
        _SYNTHETIC_PYPROJECT.format(version="0.2.0")
    ),
    "the build hook": lambda root: (root / "hatch_build.py").write_text("# a changed hook\n"),
    "the licence": lambda root: (root / "LICENSE").write_text("a changed licence\n"),
    "the readme": lambda root: (root / "README.md").write_text("# something else\n"),
    "the third-party notices": lambda root: (root / _NOTICES).write_text(
        "| Pinned commit | `4567def` |\n"
    ),
    "a packaged source file": lambda root: (root / _SYNTHETIC_SOURCE).write_text(
        "ARTIFACT_REVISION = '4567def'\n"
    ),
    "a packaged source file added": lambda root: (
        root / "src" / "ai_assistant" / "models" / "speech_artifact.py"
    ).write_text("SPEECH_ARTIFACTS = ()\n"),
    "a packaged source file removed": lambda root: (root / _SYNTHETIC_SOURCE).unlink(),
    "a vendored artifact's bytes": lambda root: _rewritten_in_place(root / _SYNTHETIC_ARTIFACT),
}


@pytest.mark.parametrize("change", list(_PERTURBATIONS.values()), ids=list(_PERTURBATIONS))
def test_a_changed_build_input_misses_the_cache(
    tmp_path: Path, change: Callable[[Path], object]
) -> None:
    """A changed input must not be answered by a build made before it changed.

    The cache is keyed by this digest and by nothing else, so "misses the cache"
    is exactly "digests differently" — a build lands in a directory the changed
    tree does not look in, and `_read_or_build` rejects a record whose digest is
    not the reader's even when the directory is the one it was handed.

    The last is the case that decided to content-hash the vendored artifacts
    rather than key them on their size and timestamp: as many bytes as before,
    written in place, the timestamp put back. Keyed on a stat that would digest
    the same, and a distribution built from the *old* bytes would be read for the
    new ones — leaving the assertions above to pass over an artifact this checkout
    no longer holds, which is the failure this module exists to make impossible.
    """
    root = _synthetic_checkout(tmp_path)
    before = _build_inputs_digest(root)
    change(root)

    assert _build_inputs_digest(root) != before


def _point_the_cache_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Point the cache at *root*, whichever of the three roots is being exercised."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(root))
    monkeypatch.delenv("HOME", raising=False)


def test_the_cache_directory_is_private_at_every_level_it_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not only the leaf: a directory nobody vouched for must not sit above it.

    An unchecked level is one an attacker can write to, and a level they can write
    to is one they can swap the cache out of after it passed its own check.
    """
    _point_the_cache_at(monkeypatch, tmp_path)
    cache = _cache_directory()

    assert cache == tmp_path.joinpath(*_CACHE_TREE)
    for level in (tmp_path / _CACHE_TREE[0], cache):
        assert level.stat().st_mode & 0o777 == 0o700


def test_the_cache_falls_back_where_no_home_directory_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared-temp root, where the per-user level is ours to make and to check."""
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    cache = _cache_directory()

    assert cache == tmp_path.joinpath(f"ai-assistant-{os.getuid()}", *_CACHE_TREE)
    assert cache is not None
    for level in (tmp_path / f"ai-assistant-{os.getuid()}", cache.parent, cache):
        assert level.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
@pytest.mark.parametrize("level", [0, 1], ids=["the outer level", "the cache itself"])
def test_a_cache_directory_others_can_write_to_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: int
) -> None:
    """At either level, and refused rather than repaired.

    A directory of this name that anyone else can write to was not made by a run
    of this suite, so its mode is not ours to correct — it is a reason to build
    into this run's own temp tree instead.
    """
    _point_the_cache_at(monkeypatch, tmp_path)
    planted = tmp_path.joinpath(*_CACHE_TREE[: level + 1])
    planted.mkdir(parents=True)
    planted.chmod(0o777)

    assert _cache_directory() is None


def test_a_symlinked_cache_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink at the cache's name is somebody else's idea of where it should go."""
    _point_the_cache_at(monkeypatch, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (tmp_path / _CACHE_TREE[0]).symlink_to(elsewhere)

    assert _cache_directory() is None


def _cache_entry(directory: Path, digest: str = "a" * 64) -> dict[str, object]:
    """A cache entry of the recorded shape, with archives small enough to write here.

    The sdist carries two members, so that a truncation can leave the first one
    intact — the shape a header-deep check would have accepted.
    """
    distributions: dict[str, dict[str, str]] = {}
    for key in _RECORDED:
        as_tar = key == "sdist"
        path = directory / key / ("archive.tar.gz" if as_tar else "archive.whl")
        path.parent.mkdir(parents=True, exist_ok=True)
        if as_tar:
            with tarfile.open(path, "w:gz") as tar:
                for member in ("PKG-INFO", "THIRD-PARTY-NOTICES.md"):
                    info = tarfile.TarInfo(member)
                    info.size = 1024
                    tar.addfile(info, io.BytesIO(b"." * info.size))
        else:
            with zipfile.ZipFile(path, "w") as zipped:
                zipped.writestr("ai_assistant/__init__.py", "")
        distributions[key] = {
            "path": path.relative_to(directory).as_posix(),
            "sha256": _file_digest(path),
        }
    return {"digest": digest, "distributions": distributions}


def test_an_intact_cache_entry_is_usable(tmp_path: Path) -> None:
    """The positive case the damaged ones below are read against."""
    record = _cache_entry(tmp_path)

    assert _usable(tmp_path, record, "a" * 64)


def test_a_cache_entry_for_other_inputs_is_not_usable(tmp_path: Path) -> None:
    """What stands between a changed input and a stale answer where the name cannot."""
    record = _cache_entry(tmp_path)

    assert not _usable(tmp_path, record, "b" * 64)


#: How a cache directory comes to hold a record it can no longer honour. The last
#: is the one a header-deep check misses: an archive whose first member survives.
_DAMAGE: Mapping[str, Callable[[Path], object]] = {
    "removed": lambda path: path.unlink(),
    "emptied": lambda path: path.write_bytes(b""),
    "replaced by something that is not an archive": lambda path: path.write_bytes(b"nope"),
    "truncated": lambda path: path.write_bytes(path.read_bytes()[: len(path.read_bytes()) // 2]),
}


@pytest.mark.parametrize("distribution", list(_RECORDED))
@pytest.mark.parametrize("damage", list(_DAMAGE.values()), ids=list(_DAMAGE))
def test_a_cache_entry_whose_distribution_is_gone_is_not_usable(
    tmp_path: Path, distribution: str, damage: Callable[[Path], object]
) -> None:
    """A record believed on its own would fail every run until a hand-cleared cache.

    A cached build outlives the run that made it, so anything that sweeps a cache
    directory can leave the record standing over distributions that are gone. Held
    to be unusable, the entry is rebuilt under the lock the caller already holds.
    """
    record = _cache_entry(tmp_path)
    damage(_distribution(tmp_path, record, distribution))

    assert not _usable(tmp_path, record, "a" * 64)


def test_a_cache_entry_may_not_name_a_path_outside_its_own_directory(tmp_path: Path) -> None:
    """The record is read back off disk, so joining its names unchecked is a hazard."""
    directory = tmp_path / "entry"
    directory.mkdir()
    record = _cache_entry(directory)
    outside = tmp_path / "outside"
    escaping = _distribution(outside, _cache_entry(outside), "sdist")
    _distribution_record(record, "sdist")["path"] = f"../outside/{escaping.relative_to(outside)}"
    _distribution_record(record, "sdist")["sha256"] = _file_digest(escaping)

    assert not _usable(directory, record, "a" * 64)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_cache_root_others_can_write_to_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`XDG_CACHE_HOME` may name anything, a shared directory included.

    Checking the levels below such a root buys nothing: whoever can write to it
    can rename the whole checked tree away and leave a symlink at its name, after
    every check on it has passed.
    """
    root = tmp_path / "shared"
    root.mkdir()
    root.chmod(0o777)  # after `mkdir`, whose mode the umask would trim
    monkeypatch.setenv("XDG_CACHE_HOME", str(root))
    monkeypatch.delenv("HOME", raising=False)

    assert _cache_directory() is None


def test_a_sticky_world_writable_cache_root_is_trusted(tmp_path: Path) -> None:
    """The shape the system temp directory has, and the reason `/tmp` is usable.

    Anyone may create an entry there, but the sticky bit means only its owner may
    rename or remove one — so a directory of ours below it cannot be swapped out,
    which is the only thing a root is being trusted for here.
    """
    root = tmp_path / "tmp"
    root.mkdir()
    root.chmod(0o1777)

    assert _trusted_root(root)


@pytest.fixture
def released_locks() -> Iterator[None]:
    """Drop the locks a call under test took, which a real run keeps for good."""
    kept = len(_HELD_LOCKS)
    yield
    for handle in _HELD_LOCKS[kept:]:
        handle.close()
    del _HELD_LOCKS[kept:]


def _distribution_record(record: Mapping[str, object], key: str) -> dict[str, str]:
    """The part of *record* describing one distribution, to be read or perturbed."""
    distributions = record["distributions"]
    assert isinstance(distributions, dict)
    named: dict[str, str] = distributions[key]
    return named


def _readable_entry(cache: Path, digest: str) -> Path:
    """A complete cache entry for *digest*, of the shape `_cached` reads."""
    entry = cache / digest
    (entry / _BUILT).write_text(json.dumps(_cache_entry(entry, digest)))
    return entry


@pytest.mark.usefixtures("released_locks")
def test_a_cache_entry_another_run_is_reading_is_read_rather_than_rebuilt(
    tmp_path: Path,
) -> None:
    """A sound entry is shared, which is the point of the lock being a shared one."""
    digest = "a" * 64
    entry = _readable_entry(tmp_path, digest)
    with (tmp_path / f"{digest}.lock").open("ab") as reader:
        fcntl.flock(reader.fileno(), fcntl.LOCK_SH)
        found = _cached(tmp_path, digest)

    assert found is not None
    assert found.sdist == entry / "sdist" / "archive.tar.gz"


@pytest.mark.usefixtures("released_locks")
def test_a_damaged_cache_entry_another_run_is_reading_is_left_alone(tmp_path: Path) -> None:
    """A rebuild removes the directory, and a reader's files with it.

    So an entry whose exclusive lock cannot be had is not this run's to replace,
    however unusable it looks from here: the run that holds it found it sound and
    is reading it, and this run builds for itself instead (adversarial review of
    this change, round 2).
    """
    digest = "a" * 64
    entry = _readable_entry(tmp_path, digest)
    (entry / "sdist" / "archive.tar.gz").unlink()
    with (tmp_path / f"{digest}.lock").open("ab") as reader:
        fcntl.flock(reader.fileno(), fcntl.LOCK_SH)

        assert _cached(tmp_path, digest) is None

    assert (entry / _BUILT).is_file()
    assert (entry / "checkout_wheel" / "archive.whl").is_file()


@pytest.mark.usefixtures("released_locks")
def test_the_lock_on_a_build_in_use_is_shared_not_exclusive(tmp_path: Path) -> None:
    """Held exclusively for the session, one run's tests would queue every other.

    The exclusive lock is what makes an entry safe to replace, so it is taken to
    resolve one and downgraded the moment the entry is good — leaving a lock that
    says "in use" without saying "wait for me".
    """
    digest = "a" * 64
    _readable_entry(tmp_path, digest)

    assert _cached(tmp_path, digest) is not None
    with (tmp_path / f"{digest}.lock").open("ab") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)  # another reader gets in
        with pytest.raises(BlockingIOError):  # a run that would replace it does not
            fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


# --- The sharing protocol itself (#1734) -------------------------------------
#
# Every other assertion in this module is about what a distribution *contains*,
# so a regression back to a build per worker — a wrong root, a record that stops
# being consulted, a build that runs in place instead of in staging — would leave
# the whole module green while quietly restoring the multi-gigabyte behaviour
# #1682 removed. What follows drives the protocol with the build itself mocked,
# so it costs milliseconds rather than the 45 s a real one does.

#: The build inputs these tests pretend to have digested. Any 64-hex string; it
#: is compared against the record's own field, never against a real checkout.
_INPUTS = "c" * 64

#: Written by the mocked build into whatever directory it is given, so a test can
#: tell a directory this run built from one it merely found and adopted.
_MOCK_MARK = "built-by-this-run"


def _mock_the_build(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Replace the 45 s build with a cheap one; return the directories it runs in.

    The distributions it leaves are the small archives :func:`_cache_entry`
    writes, so the record `_build_into_place` computes over them is a real one and
    a reader verifies it exactly as it verifies a real build's.

    Args:
        monkeypatch: The patcher, which undoes this at the end of the test.

    Returns:
        A list appended to once per build, holding the directory each ran in —
        which is both *how many* builds happened and *where*.
    """
    ran: list[Path] = []

    def build(into: Path, digest: str) -> _Distributions:
        ran.append(into)
        into.mkdir(parents=True, exist_ok=True)
        (into / _MOCK_MARK).write_text(digest)
        record = _cache_entry(into, digest)
        return _Distributions(
            digest=digest, **{key: _distribution(into, record, key) for key in _RECORDED}
        )

    monkeypatch.setattr(sys.modules[__name__], "_build_the_distributions", build)
    return ran


def _run_root_as(run_root: Path, worker: str | None) -> Path:
    """:func:`_run_root`'s answer for one session — a worker's, or a serial run's.

    ``pytest-xdist`` gives a worker a basetemp of ``<run root>/popen-gw<n>`` and
    sets ``workerinput`` on its config and on nothing else; a serial run's basetemp
    already is the run root. Both are stood up here rather than spawned, because
    what is under test is which of the two `_run_root` returns — and spawning a
    distributed session to find out would cost more than the build being guarded.

    Args:
        run_root: The directory standing in for the run's basetemp.
        worker: An xdist worker id, or ``None`` for a serial run.

    Returns:
        The root `_run_root` resolves for that session.
    """
    basetemp = run_root / f"popen-{worker}" if worker is not None else run_root
    basetemp.mkdir(parents=True, exist_ok=True)
    config = (
        types.SimpleNamespace(workerinput={"workerid": worker})
        if worker is not None
        else types.SimpleNamespace()
    )
    return _run_root(
        cast("pytest.FixtureRequest", types.SimpleNamespace(config=config)),
        cast("pytest.TempPathFactory", types.SimpleNamespace(getbasetemp=lambda: basetemp)),
    )


def _resolve_the_shared_build(root: Path) -> _Distributions:
    """The fallback branch of :func:`built_distributions`, verbatim.

    The lock is taken here as the fixture takes it, so a regression that moved the
    build out from under it — read first, lock second — is a regression this drives
    rather than one it reasons around.
    """
    shared = root / _SHARED_BUILD
    shared.mkdir(parents=True, exist_ok=True)
    with _exclusively(root / f"{_SHARED_BUILD}.lock"):
        return _read_or_build(shared, _INPUTS)


def test_two_workers_of_one_run_share_a_single_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the run-wide root: one build between every worker.

    ``just test-fast`` runs a pytest session per worker, and each would otherwise
    build its own set of three ~0.8 GiB distributions — the 5.0 GiB temp footprint
    #1682 measured. A regression in which root is chosen leaves every assertion in
    this module passing and restores that cost silently, which is why it is pinned
    here and not inferred from a green module.
    """
    ran = _mock_the_build(monkeypatch)
    run_root = tmp_path / "run"

    first, second = _run_root_as(run_root, "gw0"), _run_root_as(run_root, "gw1")
    resolved = [_resolve_the_shared_build(root) for root in (first, second)]

    assert first == second == run_root, "two workers of one run must resolve one root"
    assert len(ran) == 1, f"one build per run, not one per worker: built in {ran}"
    assert resolved[0] == resolved[1], "both workers must read the same distributions"
    assert resolved[0].sdist.is_relative_to(run_root / _SHARED_BUILD)


def test_a_serial_runs_basetemp_is_already_its_run_root(tmp_path: Path) -> None:
    """And no run shares with another, which taking the parent unconditionally would.

    A serial run's basetemp *is* the run root, so climbing to its parent would put
    the build in pytest's shared ``pytest-of-<user>`` directory — shared with every
    other run on the machine, under a lock discipline written for one. The cache
    (:func:`_cached`) is where cross-run sharing is decided, and it is keyed on a
    digest of the build inputs; this fallback path is not.
    """
    assert _run_root_as(tmp_path / "run", None) == tmp_path / "run"


def test_a_directory_without_a_record_is_rebuilt_rather_than_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record is written last, so its absence is what says "did not finish".

    Distributions on their own prove nothing: a build interrupted partway leaves
    some of them, and the largest is written first. Reading them because they are
    there is how a half-built set becomes a green run over the wrong bytes.
    """
    ran = _mock_the_build(monkeypatch)
    destination = tmp_path / _SHARED_BUILD
    _cache_entry(destination, _INPUTS)  # the three archives, and no `built.json`
    assert not (destination / _BUILT).exists()

    resolved = _read_or_build(destination, _INPUTS)

    assert len(ran) == 1, "an unfinished directory was read instead of rebuilt"
    assert (destination / _BUILT).is_file()
    assert resolved.digest == _INPUTS


def test_an_abandoned_staging_directory_is_discarded_rather_than_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that died mid-flight leaves staging behind; it is never a build.

    The staging directory is where the record for an unfinished build lives, and
    it can look complete: a build killed between writing `built.json` and the
    rename that publishes it leaves exactly the entry a reader would accept. It is
    accepted by nothing, because a reader only ever looks at the destination — and
    the next build clears staging rather than continuing it, so nothing the dead
    build left can reach the directory a reader ends up with.
    """
    destination = tmp_path / _SHARED_BUILD
    staging = tmp_path / f".{_SHARED_BUILD}.building"
    staging.mkdir(parents=True)
    (staging / _BUILT).write_text(json.dumps(_cache_entry(staging, _INPUTS)))
    # A file no build writes, so "restarted" and "continued" are told apart by
    # whether it survives into the directory the reader is handed.
    (staging / "left-behind-by-the-dead-build").write_text("")
    ran = _mock_the_build(monkeypatch)

    resolved = _read_or_build(destination, _INPUTS)

    assert ran == [staging], "the build must run in staging, never in the destination"
    assert (destination / _MOCK_MARK).read_text() == _INPUTS, "staging was adopted"
    assert not (destination / "left-behind-by-the-dead-build").exists(), "staging was continued"
    assert resolved.digest == _INPUTS
    assert not staging.exists(), "staging is renamed into place, not left beside it"


def test_a_cache_root_that_is_not_there_yet_is_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh `$HOME` has no `.cache`, and refusing one would be a cache off forever.

    Off for the environments the cache most helps — a new container, a new clone's
    first run — and off silently, since a fallback build passes every assertion.
    """
    absent = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(absent))
    monkeypatch.delenv("HOME", raising=False)

    assert _cache_directory() == absent.joinpath(*_CACHE_TREE)
    assert absent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_cache_root_is_not_made_under_a_parent_others_can_write_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Making the root does not make its parent trustworthy.

    A root created below a directory another account can write to can be renamed
    away and replaced the moment after it is checked, which is the whole reason
    the levels below it are checked one at a time.
    """
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o777)
    monkeypatch.setenv("XDG_CACHE_HOME", str(parent / "cache"))
    monkeypatch.delenv("HOME", raising=False)

    assert _cache_directory() is None


def test_the_digest_covers_every_file_this_projects_build_declares() -> None:
    """A roster, so that a fourth declared file is not silently left unkeyed.

    `pyproject.toml` names files that go into both distributions without any of
    them appearing under `src/`, and the one that went unnoticed — `README.md` —
    went unnoticed because nothing here enumerated them. This does, against the
    real checkout: declare another and this fails until the roster admits it.
    """
    assert _declared_files(_PROJECT_ROOT) == ("LICENSE", "README.md", _NOTICES)


def test_a_symlinked_cache_root_is_resolved_before_it_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checking a symlink says only where it pointed when it was checked.

    `$XDG_CACHE_HOME` may reasonably name one — a cache moved onto another disk —
    so it is resolved rather than refused, and the resolved path is what is kept.
    Whoever owns the link may repoint it afterwards; there is then no link left in
    the path this run opens.
    """
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    link = tmp_path / "cache"
    link.symlink_to(target)
    monkeypatch.setenv("XDG_CACHE_HOME", str(link))
    monkeypatch.delenv("HOME", raising=False)

    cache = _cache_directory()

    assert cache is not None
    assert cache == target.joinpath(*_CACHE_TREE)
    assert cache == cache.resolve()  # no link left in it for anyone to repoint


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_a_cache_entry_that_cannot_be_read_is_not_usable(tmp_path: Path) -> None:
    """Unreadable is unusable, and neither an error nor a reason to trust the record."""
    record = _cache_entry(tmp_path)
    _distribution(tmp_path, record, "sdist").chmod(0o000)

    assert not _usable(tmp_path, record, "a" * 64)


def test_a_cache_entry_removed_while_it_is_verified_is_not_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep can land between "it is there" and "these are its bytes".

    Made deterministic by removing the file inside the hashing step itself, which
    is the one window the check has. An `OSError` escaping there would fail the
    packaging tests with a missing file — the outcome that checking the entry at
    all is meant to prevent.
    """
    record = _cache_entry(tmp_path)
    real = _file_digest

    def vanishing(path: Path) -> str:
        path.unlink()
        return real(path)

    monkeypatch.setattr(sys.modules[__name__], "_file_digest", vanishing)

    assert not _usable(tmp_path, record, "a" * 64)


def test_a_cache_directory_that_cannot_be_resolved_is_no_cache_rather_than_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback is what an unusable cache means, at every step of finding one.

    Most of the steps refuse by returning `None` already. This pins the property
    for the whole of it: whatever the filesystem declines to do, the answer is
    that there is no cache, never an error that would fail every test needing a
    distribution over an optimisation that did not come off.
    """

    def refuses(self: Path, strict: bool = False) -> Path:
        raise OSError(errno.ELOOP, "too many levels of symbolic links")

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.setattr(Path, "resolve", refuses)

    assert _cache_directory() is None

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
ADR-0200 §13 added the two speech models beside the embedding model — so the
builds are done **once per run** and shared, rather than once per pytest session.
A session fixture is not enough on its own: ``just test-fast`` runs a session per
xdist worker, so every worker that happened to draw one of these tests built its
own wheel, sdist and sdist-derived wheel. The build now happens under a lock in
the run-wide temp root, the directory above the per-worker ones, which is the
pattern pytest-xdist documents for exactly this; a serial run has that root to
itself and simply builds (issue #1682).

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
import fcntl
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

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
    from collections.abc import Iterator, Mapping

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


#: The subdirectory of the run-wide temp root that the shared build writes into.
_SHARED_BUILD = "packaging-distributions"

#: Written last, inside the lock, recording what was built. Its presence is what
#: tells the next worker the build *finished* rather than merely started, so a
#: build that died halfway is rebuilt rather than half-read.
_BUILT = "built.json"


@dataclasses.dataclass(frozen=True)
class _Distributions:
    """The three real distributions this module looks inside."""

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


def _build_the_distributions(into: Path) -> _Distributions:
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

    return _Distributions(checkout_wheel=checkout_wheel, sdist=sdist, sdist_wheel=sdist_wheel)


@pytest.fixture(scope="session")
def built_distributions(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> _Distributions:
    """The three distributions, built once per run and shared across xdist workers.

    The first worker to arrive builds them; the rest block on the lock and then
    read what it left. Nothing mutates the built files afterwards, so reading them
    outside the lock is safe — and the recorded names are read *inside* it, so a
    reader cannot see a half-written record.
    """
    _require_the_staged_artifact()
    root = _run_root(request, tmp_path_factory)
    shared = root / _SHARED_BUILD
    shared.mkdir(parents=True, exist_ok=True)
    built = shared / _BUILT
    with _exclusively(root / f"{_SHARED_BUILD}.lock"):
        if not built.is_file():
            distributions = _build_the_distributions(shared)
            built.write_text(
                json.dumps(
                    {
                        "checkout_wheel": distributions.checkout_wheel.relative_to(
                            shared
                        ).as_posix(),
                        "sdist": distributions.sdist.relative_to(shared).as_posix(),
                        "sdist_wheel": distributions.sdist_wheel.relative_to(shared).as_posix(),
                    }
                )
            )
        recorded: dict[str, str] = json.loads(built.read_text())
    return _Distributions(
        checkout_wheel=shared / recorded["checkout_wheel"],
        sdist=shared / recorded["sdist"],
        sdist_wheel=shared / recorded["sdist_wheel"],
    )


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

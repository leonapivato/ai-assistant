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

They are skipped when the artifact is not staged. A staged artifact is the normal
state of a working tree — ``uv sync`` builds the project, which runs the hook —
so on a developer machine and in CI these run.
"""

from __future__ import annotations

import contextlib
import email.parser
import hashlib
import importlib.metadata
import os
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
    AUDITED_PACKAGES,
    packaged_artifact_dir,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

#: The project root, if this is a source checkout rather than an installed copy.
_PROJECT_ROOT = Path(embedding_artifact.__file__).resolve().parents[3]

#: The artifact's path relative to the *package* root, derived from the accessor
#: the runtime uses. Asserting the built distributions carry this exact path is
#: what makes "packages the wrong path" a failure rather than dead weight.
_ARTIFACT_IN_PACKAGE = packaged_artifact_dir().relative_to(_PROJECT_ROOT / "src" / "ai_assistant")

_REASONS = []
if not (_PROJECT_ROOT / "pyproject.toml").is_file():
    _REASONS.append("not a source checkout")
if embedding_artifact.missing_files(packaged_artifact_dir()):
    _REASONS.append("the vendored artifact is not staged (run `uv sync`)")

pytestmark = pytest.mark.skipif(bool(_REASONS), reason="; ".join(_REASONS) or "buildable")


@contextlib.contextmanager
def _built_in(directory: Path) -> Iterator[None]:
    """Run a hatchling build with ``directory`` as the project root, offline."""
    with contextlib.chdir(directory), network_denied():
        yield


@pytest.fixture(scope="session")
def checkout_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A wheel built from this git checkout, with the network denied throughout."""
    out = tmp_path_factory.mktemp("checkout-wheel")
    with _built_in(_PROJECT_ROOT):
        name = build_wheel(str(out))
    return out / name


@pytest.fixture(scope="session")
def sdist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An sdist built from this git checkout, with the network denied throughout."""
    out = tmp_path_factory.mktemp("sdist")
    with _built_in(_PROJECT_ROOT):
        name = build_sdist(str(out))
    return out / name


@pytest.fixture(scope="session")
def sdist_wheel(sdist: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A wheel built from the unpacked sdist — the ``--no-binary`` install path.

    The one that would expose a hook configured for the wheel target only, or an
    sdist that shipped the code but not the artifact: this build has no git
    checkout to fetch from and no network to fetch over.
    """
    unpacked = tmp_path_factory.mktemp("sdist-unpacked")
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")  # built by this test
    (root,) = list(unpacked.iterdir())
    out = tmp_path_factory.mktemp("sdist-wheel")
    with _built_in(root):
        name = build_wheel(str(out))
    return out / name


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
    """
    wheel: Path = request.getfixturevalue(wheel_fixture)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(tmp_path)  # noqa: S202  # built by this test
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

"""Tests for the pins, the identity, and the acquisition seam (ADR-0024 §§2-5).

The build hook is a thin adapter over this module, so this is where "requests the
recorded commit", "a digest mismatch leaves nothing staged" and "presence is not
trust" are pinned. The packaging tests next door then prove the adapter wires it
to both build targets.

Every acquisition test substitutes the download seam. The *bytes* they serve are
the real vendored ones, copied from the staged artifact — a fake payload would
make "the recorded commit was requested" unfalsifiable, since any revision would
then hash to whatever the fake produced.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from network_guard import network_denied

from ai_assistant.models import embedding_artifact
from ai_assistant.models.embedding_artifact import (
    ARTIFACT_MANIFEST,
    ARTIFACT_REPO_ID,
    ARTIFACT_REVISION,
    AUDITED_PACKAGES,
    VENDORED_MODEL_NAME,
    ArtifactError,
    embedding_space_id,
    ensure_artifact,
    installed_audited_versions,
    manifest_digest,
    packaged_artifact_dir,
    sha256_of,
    verify_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

#: The smallest manifest file, used wherever a test needs to corrupt one.
_SMALL_FILE = "config.json"

_ARTIFACT_ABSENT = pytest.mark.skipif(
    bool(embedding_artifact.missing_files(embedding_artifact.packaged_artifact_dir())),
    reason=(
        "the vendored embedding artifact is not staged; run `uv sync` (which builds the "
        "project and therefore runs the build hook) before running this test offline"
    ),
)


def _real_bytes(name: str) -> bytes:
    return (packaged_artifact_dir() / name).read_bytes()


class _Downloader:
    """A stand-in for the acquisition seam that records what the build asked for.

    Serves the genuine vendored bytes **only** for the pinned revision. Any other
    revision — a branch name, a moved ``main`` — gets different bytes, so a build
    that stopped requesting the recorded commit fails the digest check instead of
    quietly producing a different product.
    """

    def __init__(self, *, corrupt: str | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._corrupt = corrupt

    def __call__(self, *, repo_id: str, filename: str, revision: str, destination: Path) -> None:
        self.calls.append((repo_id, filename, revision))
        if revision != ARTIFACT_REVISION or filename == self._corrupt:
            destination.write_bytes(b"a different revision of " + filename.encode())
            return
        destination.write_bytes(_real_bytes(filename))

    @property
    def revisions(self) -> set[str]:
        return {revision for _, _, revision in self.calls}

    @property
    def filenames(self) -> set[str]:
        return {filename for _, filename, _ in self.calls}


# --------------------------------------------------------------------------- #
# The pins themselves
# --------------------------------------------------------------------------- #


def test_the_revision_is_an_immutable_commit() -> None:
    # A branch or tag would let the artifact change under an unchanged pin, which
    # is the whole failure ADR-0024 §2 closes.
    assert len(ARTIFACT_REVISION) == 40
    assert set(ARTIFACT_REVISION) <= set("0123456789abcdef")


def test_every_manifest_entry_is_a_sha256() -> None:
    assert ARTIFACT_MANIFEST
    for name, digest in ARTIFACT_MANIFEST.items():
        assert len(digest) == 64, name
        assert set(digest) <= set("0123456789abcdef"), name


@_ARTIFACT_ABSENT
def test_the_staged_artifact_matches_the_recorded_manifest() -> None:
    # The artifact this working tree would package really is the pinned one.
    verify_artifact(packaged_artifact_dir())


# --------------------------------------------------------------------------- #
# §5 — the acquisition seam
# --------------------------------------------------------------------------- #


@_ARTIFACT_ABSENT
def test_the_build_requests_the_recorded_commit(tmp_path: Path) -> None:
    downloader = _Downloader()

    with network_denied():
        ensure_artifact(tmp_path, download=downloader)

    assert downloader.revisions == {ARTIFACT_REVISION}
    assert downloader.filenames == set(ARTIFACT_MANIFEST)
    assert {repo for repo, _, _ in downloader.calls} == {ARTIFACT_REPO_ID}
    verify_artifact(tmp_path)


@_ARTIFACT_ABSENT
def test_a_moved_default_branch_does_not_change_the_build(tmp_path: Path) -> None:
    """The pin, not the branch, decides what ships.

    The downloader serves the real bytes only at the recorded commit. So this
    passes if and only if the build asked for that commit — an implementation
    that requested ``main`` (which is what fastembed's own download path does)
    fails here on the digest, not on a name.
    """
    with network_denied():
        ensure_artifact(tmp_path, download=_Downloader())

    for name, expected in ARTIFACT_MANIFEST.items():
        assert sha256_of(tmp_path / name) == expected


@_ARTIFACT_ABSENT
def test_a_digest_mismatch_fails_the_build_leaving_nothing_staged(tmp_path: Path) -> None:
    destination = tmp_path / "vendor"
    downloader = _Downloader(corrupt=_SMALL_FILE)

    with network_denied(), pytest.raises(ArtifactError, match="does not match its recorded digest"):
        ensure_artifact(destination, download=downloader)

    # Nothing half-written: a failed acquisition must not leave a partially
    # verified directory that a later build would find "already present".
    assert not destination.exists() or list(destination.iterdir()) == []


@_ARTIFACT_ABSENT
def test_an_already_present_corrupted_file_fails_the_build(tmp_path: Path) -> None:
    """Presence is not trust — this is the sdist case as much as the staging one.

    A file unpacked from an sdist, or left over from an interrupted build, is
    never re-downloaded (it is not missing), so the only thing standing between
    it and the wheel is that every file is re-hashed before it is packaged.
    """
    for name in ARTIFACT_MANIFEST:
        shutil.copyfile(packaged_artifact_dir() / name, tmp_path / name)
    (tmp_path / _SMALL_FILE).write_bytes(_real_bytes(_SMALL_FILE) + b"\n")

    def must_not_download(**_kwargs: object) -> None:
        raise AssertionError("a present-but-corrupt file must fail, not be re-fetched")

    with pytest.raises(ArtifactError, match=f"{_SMALL_FILE!r} does not match its recorded digest"):
        ensure_artifact(tmp_path, download=must_not_download)


@_ARTIFACT_ABSENT
def test_only_the_missing_files_are_fetched(tmp_path: Path) -> None:
    # The sdist path in miniature: what is already present and correct is kept,
    # so a `--no-binary` build downloads nothing at all.
    for name in ARTIFACT_MANIFEST:
        if name != _SMALL_FILE:
            shutil.copyfile(packaged_artifact_dir() / name, tmp_path / name)
    downloader = _Downloader()

    with network_denied():
        ensure_artifact(tmp_path, download=downloader)

    assert downloader.filenames == {_SMALL_FILE}


@_ARTIFACT_ABSENT
def test_a_complete_directory_is_verified_without_any_download(tmp_path: Path) -> None:
    for name in ARTIFACT_MANIFEST:
        shutil.copyfile(packaged_artifact_dir() / name, tmp_path / name)

    def must_not_download(**_kwargs: object) -> None:
        raise AssertionError("nothing was missing; nothing should have been fetched")

    with network_denied():
        ensure_artifact(tmp_path, download=must_not_download)


def test_a_missing_file_is_reported_by_name(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="is missing from"):
        verify_artifact(tmp_path)


def test_a_seam_that_produces_nothing_fails(tmp_path: Path) -> None:
    def produce_nothing(**_kwargs: object) -> None:
        return

    with pytest.raises(ArtifactError, match="did not produce"):
        ensure_artifact(tmp_path, download=produce_nothing)


# --------------------------------------------------------------------------- #
# §2 — the identity
# --------------------------------------------------------------------------- #


def test_the_identity_is_not_the_bare_model_name() -> None:
    # On `main` it was, and a re-pin of the weights left it identical — the
    # silent same-id/different-vectors corruption ADR-0024 §2 closes.
    identity = embedding_space_id()

    assert identity != VENDORED_MODEL_NAME
    assert identity.startswith(f"{VENDORED_MODEL_NAME}@")


def test_the_identity_is_stable_for_an_unchanged_pin_and_stack() -> None:
    versions = installed_audited_versions()

    assert embedding_space_id(versions) == embedding_space_id(versions)


@pytest.mark.parametrize("package", AUDITED_PACKAGES)
def test_bumping_any_audited_version_moves_the_identity(package: str) -> None:
    # ADR-0024 §3 makes the audited stack release-bound, so a store surviving an
    # upgrade under unchanged weights would otherwise keep its id while its
    # space moved. Each package must move it *on its own*.
    baseline = installed_audited_versions()
    bumped = {**baseline, package: baseline[package] + ".post1"}

    assert embedding_space_id(bumped) != embedding_space_id(baseline)


def test_every_audited_version_moves_the_identity_differently() -> None:
    # Not just "something changed": bumping numpy must not produce the same id
    # as bumping onnxruntime, or the identity would be collapsing inputs.
    baseline = installed_audited_versions()
    identities = {
        package: embedding_space_id({**baseline, package: baseline[package] + ".post1"})
        for package in AUDITED_PACKAGES
    }

    assert len(set(identities.values())) == len(AUDITED_PACKAGES)


def test_changing_a_manifest_digest_moves_the_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # The identity is over the *bytes shipped*, not the revision — a re-pin that
    # changes the digests has to move it even if nothing else does.
    versions = installed_audited_versions()
    baseline = embedding_space_id(versions)
    repinned = dict(ARTIFACT_MANIFEST)
    repinned[_SMALL_FILE] = "0" * 64
    monkeypatch.setattr(embedding_artifact, "ARTIFACT_MANIFEST", repinned)

    assert embedding_space_id(versions) != baseline


def test_the_identity_does_not_depend_on_the_revision_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-0024 §2 is explicit that the revision is a *separate* constant that can
    # drift from the digests, so it is not what identity is derived from.
    versions = installed_audited_versions()
    baseline = embedding_space_id(versions)
    monkeypatch.setattr(embedding_artifact, "ARTIFACT_REVISION", "f" * 40)

    assert embedding_space_id(versions) == baseline


def test_the_manifest_digest_ignores_the_order_of_the_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Canonicalised, so a reordering of the constant is not a re-embed.
    baseline = manifest_digest()
    monkeypatch.setattr(
        embedding_artifact, "ARTIFACT_MANIFEST", dict(reversed(list(ARTIFACT_MANIFEST.items())))
    )

    assert manifest_digest() == baseline


def test_a_missing_audited_version_is_refused() -> None:
    versions = installed_audited_versions()
    del versions[AUDITED_PACKAGES[0]]

    with pytest.raises(ArtifactError, match="no version recorded"):
        embedding_space_id(versions)


def test_every_audited_package_is_installed() -> None:
    # The audit is only as good as its names: a typo would silently drop a
    # package from the identity. This fails on one.
    assert set(installed_audited_versions()) == set(AUDITED_PACKAGES)

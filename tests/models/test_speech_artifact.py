"""The vendored speech models: their pins, their digests, and how a build gets them.

Everything a build relies on, asserted rather than assumed: the recorded manifest
is well-formed, the packaged bytes match it, an acquisition asks for the *pinned
commit*, a mismatch stages nothing, and no runtime path opens a socket.

The download seam is substituted throughout, so nothing here fetches anything —
which is also how "the build requested the recorded commit" becomes an assertion
instead of a hope.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from network_guard import network_denied

from ai_assistant.models.speech_artifact import (
    MOONSHINE_TINY_EN_INT8,
    SPEECH_ARTIFACTS,
    SUPERTONIC_3_INT8,
    SpeechArtifact,
    SpeechArtifactError,
    artifact_id,
    ensure_artifact,
    manifest_digest,
    missing_files,
    packaged_artifact_dir,
    verify_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

_HEX = set("0123456789abcdef")


class _RecordingDownload:
    """A download seam that records its requests and writes recorded bytes."""

    def __init__(self, contents: dict[str, bytes]) -> None:
        self.contents = contents
        self.requests: list[tuple[str, str, str]] = []

    def __call__(self, *, repo_id: str, filename: str, revision: str, destination: Path) -> None:
        self.requests.append((repo_id, filename, revision))
        destination.write_bytes(self.contents[filename])


def _artifact(tmp_path: Path, contents: dict[str, bytes]) -> tuple[SpeechArtifact, Path]:
    """A one-off artifact whose manifest is the digests of ``contents``.

    Built rather than taken from the shipped pair, so the staging cases can drive
    a mismatch without a 119 MiB download or a mutated packaged tree.
    """
    directory = tmp_path / "artifact"
    artifact = SpeechArtifact(
        directory_name="test-artifact",
        repo_id="example/repo",
        revision="0" * 40,
        manifest={name: hashlib.sha256(body).hexdigest() for name, body in contents.items()},
    )
    return artifact, directory


# --- the recorded pins -------------------------------------------------------


@pytest.mark.parametrize("artifact", SPEECH_ARTIFACTS, ids=lambda a: a.directory_name)
def test_every_manifest_is_a_non_empty_map_of_digests(artifact: SpeechArtifact) -> None:
    assert artifact.manifest
    for name, digest in artifact.manifest.items():
        assert name
        assert not name.startswith("/")
        assert len(digest) == 64
        assert _HEX.issuperset(digest), f"{name} carries a non-lowercase-hex digest"


@pytest.mark.parametrize("artifact", SPEECH_ARTIFACTS, ids=lambda a: a.directory_name)
def test_every_revision_is_a_full_commit(artifact: SpeechArtifact) -> None:
    # A branch name or a short sha would let a moved default branch change what a
    # build produces, which is the whole point of pinning.
    assert len(artifact.revision) == 40
    assert _HEX.issuperset(artifact.revision)


def test_the_two_artifacts_are_distinct_and_both_are_listed() -> None:
    assert SPEECH_ARTIFACTS == (MOONSHINE_TINY_EN_INT8, SUPERTONIC_3_INT8)
    assert len({a.directory_name for a in SPEECH_ARTIFACTS}) == 2


@pytest.mark.parametrize("artifact", SPEECH_ARTIFACTS, ids=lambda a: a.directory_name)
def test_the_packaged_directory_is_inside_this_package(artifact: SpeechArtifact) -> None:
    directory = packaged_artifact_dir(artifact)

    assert directory.parent.name == "_vendor"
    assert directory.name == artifact.directory_name


def test_an_identity_moves_with_the_bytes_and_not_with_the_revision() -> None:
    # `artifact_id` is over the manifest, not the commit: a re-pin that changed
    # the commit but not the bytes is the same model, and the reverse is not.
    same_bytes = SpeechArtifact(
        directory_name=MOONSHINE_TINY_EN_INT8.directory_name,
        repo_id="somewhere/else",
        revision="f" * 40,
        manifest=MOONSHINE_TINY_EN_INT8.manifest,
    )

    assert artifact_id(same_bytes) == artifact_id(MOONSHINE_TINY_EN_INT8)
    assert artifact_id(MOONSHINE_TINY_EN_INT8) != artifact_id(SUPERTONIC_3_INT8)
    assert artifact_id(MOONSHINE_TINY_EN_INT8).endswith(
        manifest_digest(MOONSHINE_TINY_EN_INT8)[:16]
    )


# --- the packaged bytes ------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("artifact", SPEECH_ARTIFACTS, ids=lambda a: a.directory_name)
def test_the_packaged_artifact_matches_its_manifest(artifact: SpeechArtifact) -> None:
    # ADR-0024 §5's "presence is not trust", applied to what this working tree
    # actually holds: every file re-hashed, with no network available to repair it.
    with network_denied():
        verify_artifact(artifact, packaged_artifact_dir(artifact))


@pytest.mark.integration
@pytest.mark.parametrize("artifact", SPEECH_ARTIFACTS, ids=lambda a: a.directory_name)
def test_nothing_is_missing_from_the_packaged_artifact(artifact: SpeechArtifact) -> None:
    assert missing_files(artifact, packaged_artifact_dir(artifact)) == []


# --- acquisition -------------------------------------------------------------


def test_only_absent_files_are_fetched_and_at_the_pinned_commit(tmp_path: Path) -> None:
    contents = {"model.onnx": b"weights", "tokens.txt": b"tokens"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "tokens.txt").write_bytes(contents["tokens.txt"])
    download = _RecordingDownload(contents)

    ensure_artifact(artifact, directory, download=download)

    assert download.requests == [(artifact.repo_id, "model.onnx", artifact.revision)]


def test_a_digest_mismatch_stages_nothing(tmp_path: Path) -> None:
    # The staging directory is moved into place only once *every* file matches, so
    # a corrupted download leaves the destination as it found it rather than half
    # written.
    contents = {"model.onnx": b"weights", "tokens.txt": b"tokens"}
    artifact, directory = _artifact(tmp_path, contents)
    download = _RecordingDownload({**contents, "model.onnx": b"corrupted"})

    with pytest.raises(SpeechArtifactError, match="does not match its recorded digest"):
        ensure_artifact(artifact, directory, download=download)

    assert not (directory / "model.onnx").exists()
    assert not (directory / "tokens.txt").exists()


def test_a_present_but_corrupted_file_fails_rather_than_shipping(tmp_path: Path) -> None:
    # The case a download can never repair: an sdist or a stale staging directory
    # carrying a file that is *present*, so nothing re-fetches it, and wrong.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "model.onnx").write_bytes(b"tampered")
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="does not match its recorded digest"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == []


def test_a_nested_path_is_staged_into_its_own_directory(tmp_path: Path) -> None:
    # The voice's pronunciation data is several hundred files under nested
    # directories, so staging has to create them; without this the whole artifact
    # would fail to acquire.
    contents = {"espeak-ng-data/lang/gmw/en": b"english", "tokens.txt": b"tokens"}
    artifact, directory = _artifact(tmp_path, contents)
    download = _RecordingDownload(contents)

    ensure_artifact(artifact, directory, download=download)

    assert (directory / "espeak-ng-data" / "lang" / "gmw" / "en").read_bytes() == b"english"


def test_a_seam_that_produces_nothing_is_reported(tmp_path: Path) -> None:
    class _SilentDownload:
        def __call__(
            self, *, repo_id: str, filename: str, revision: str, destination: Path
        ) -> None:
            return

    artifact, directory = _artifact(tmp_path, {"model.onnx": b"weights"})

    with pytest.raises(SpeechArtifactError, match="did not produce"):
        ensure_artifact(artifact, directory, download=_SilentDownload())


def test_verification_names_a_missing_file(tmp_path: Path) -> None:
    artifact, directory = _artifact(tmp_path, {"model.onnx": b"weights"})
    directory.mkdir(parents=True)

    with pytest.raises(SpeechArtifactError, match="incomplete"):
        verify_artifact(artifact, directory)


def test_acquisition_opens_no_socket_when_nothing_is_absent(tmp_path: Path) -> None:
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "model.onnx").write_bytes(contents["model.onnx"])

    with network_denied():
        ensure_artifact(artifact, directory, download=_RecordingDownload(contents))

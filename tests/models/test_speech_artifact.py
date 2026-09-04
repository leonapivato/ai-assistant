"""The vendored speech models: their pins, their digests, and how a build gets them.

Everything a build relies on, asserted rather than assumed: the recorded manifest
is well-formed, the packaged bytes match it, an acquisition asks for the *pinned
commit*, a mismatch stages nothing, and no runtime path opens a socket.

The download seam is substituted throughout, so nothing here fetches anything —
which is also how "the build requested the recorded commit" becomes an assertion
instead of a hope.
"""

from __future__ import annotations

import errno
import hashlib
import shutil
from pathlib import Path

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
    unexpected_files,
    verify_artifact,
)

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


@pytest.mark.integration
@pytest.mark.parametrize("artifact", SPEECH_ARTIFACTS, ids=lambda a: a.directory_name)
def test_nothing_unmanifested_is_staged_for_packaging(artifact: SpeechArtifact) -> None:
    # What this working tree would actually ship, checked against what it says it
    # ships. The two are the same list or the build packages an unrecorded file.
    assert unexpected_files(artifact, packaged_artifact_dir(artifact)) == []


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


def test_a_failed_verification_removes_what_this_build_staged(tmp_path: Path) -> None:
    """One file present-but-corrupt, one missing — issue #2081's reproduction.

    The corrupt file is never re-fetched (it is not missing), so the build only
    learns about it in the closing re-hash, after the missing one has been staged.
    Everything before this fix left that staged file in the destination.
    """
    contents = {"model.onnx": b"weights", "tokens.txt": b"tokens"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "tokens.txt").write_bytes(b"tampered")
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="does not match its recorded digest"):
        ensure_artifact(artifact, directory, download=download)

    assert [name for _, name, _ in download.requests] == ["model.onnx"]
    assert not (directory / "model.onnx").exists(), "the staged file was not left behind"
    # What was already there is untouched: it is the evidence the refusal is about.
    assert (directory / "tokens.txt").read_bytes() == b"tampered"


def test_a_rolled_back_acquisition_leaves_no_directory_it_created(tmp_path: Path) -> None:
    # The voice's files nest, so staging creates directories as well as writing
    # files; rolling back has to take those with it or the destination is not as
    # the build found it.
    contents = {"espeak-ng-data/lang/gmw/en": b"english"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "left-behind.onnx").write_bytes(b"from an earlier pin")

    with pytest.raises(SpeechArtifactError, match="does not name"):
        ensure_artifact(artifact, directory, download=_RecordingDownload(contents))

    assert not (directory / "espeak-ng-data").exists()
    assert sorted(path.name for path in directory.iterdir()) == ["left-behind.onnx"]


def test_a_rollback_keeps_a_directory_that_was_already_there(tmp_path: Path) -> None:
    # Rolling back what staging created must not become rolling back what it
    # merely *used*: an empty directory that was in the destination before the
    # build is not the build's to remove, even once the file it staged into it is
    # gone again.
    contents = {"espeak-ng-data/en": b"english"}
    artifact, directory = _artifact(tmp_path, contents)
    (directory / "espeak-ng-data").mkdir(parents=True)
    (directory / "left-behind.onnx").write_bytes(b"from an earlier pin")

    with pytest.raises(SpeechArtifactError, match="does not name"):
        ensure_artifact(artifact, directory, download=_RecordingDownload(contents))

    assert (directory / "espeak-ng-data").is_dir(), "a pre-existing directory was removed"
    assert not (directory / "espeak-ng-data" / "en").exists(), "and the staged file survived"


def test_a_manifest_entry_blocked_by_a_directory_is_refused(tmp_path: Path) -> None:
    """A directory where a manifest entry belongs is named, not staged around.

    ``missing_files`` asks whether each entry *is a file*, so this reads as
    "absent" and is fetched — and ``shutil.move`` onto an existing directory puts
    the file *inside* it, which verification then reports as the entry still
    missing while the downloaded bytes sit one level down.
    """
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    (directory / "model.onnx").mkdir(parents=True)
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="is not a regular file"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == [], "the refusal comes before the download"
    assert list((directory / "model.onnx").iterdir()) == [], "and nothing was moved inside it"


def test_a_symlinked_parent_cannot_carry_the_artifact_out_of_its_directory(
    tmp_path: Path,
) -> None:
    """Staging through a symlink writes outside the directory, unseen by both checks.

    `verify_artifact` follows the same link and passes; `unexpected_files` does
    not follow it, so it reports nothing either — the acquisition succeeded and
    put a manifest file somewhere else entirely. The parent is checked at every
    level between the destination directory and the entry, not just the innermost,
    because a link higher up leads out just as well.
    """
    contents = {"espeak-ng-data/lang/en": b"english"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "lang").mkdir(parents=True)
    (directory / "espeak-ng-data").symlink_to(elsewhere, target_is_directory=True)
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="it is a symlink"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == [], "the refusal comes before the download"
    assert not (elsewhere / "lang" / "en").exists(), "nothing was written outside"


def test_a_nested_parent_blocked_by_a_file_is_refused_before_the_download(
    tmp_path: Path,
) -> None:
    # The leaf reads as absent (a path through a regular file does not exist), so
    # only walking the parents catches this — and walking them in the preflight is
    # what keeps it from costing a download first.
    contents = {"espeak-ng-data/en": b"english"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "espeak-ng-data").write_bytes(b"a regular file where a directory belongs")
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="is not a directory"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == []


def test_a_rollback_that_cannot_remove_a_file_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A rollback that silently did not happen is worse than one that did not
    # start: the next build finds the file "already present" with nothing
    # anywhere saying why. The acquisition failure still propagates unchanged.
    contents = {"model.onnx": b"weights", "tokens.txt": b"tokens"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "tokens.txt").write_bytes(b"tampered")

    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(SpeechArtifactError, match="does not match its recorded digest") as caught:
        ensure_artifact(artifact, directory, download=_RecordingDownload(contents))

    assert any("could not remove" in note for note in caught.value.__notes__)
    assert any("model.onnx" in note for note in caught.value.__notes__)


@pytest.mark.parametrize(
    "name", ["/nonexistent-directory/escaped.bin", "../escaped.bin", "sub/../../escaped.bin"]
)
def test_a_manifest_name_that_is_not_a_confined_relative_path_is_refused(
    tmp_path: Path, name: str
) -> None:
    # `directory / name` silently discards `directory` for an absolute name and
    # walks out of it for a `..`, so an entry of either shape would be staged
    # outside the artifact directory. The names are repository constants, so this
    # is a guard against a careless re-pin rather than against a live attacker —
    # and the verification half of it is #2093.
    contents = {name: b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="not a confined relative path"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == [], "the refusal comes before the download"


def test_a_move_that_fails_after_creating_its_destination_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Across filesystems `shutil.move` copies and then unlinks the source, so a
    # failure after the copy leaves a destination this call made. The journal
    # records the destination before the move for exactly that reason.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)

    def half_move(source: str, destination: str) -> None:
        Path(destination).write_bytes(Path(source).read_bytes())
        raise OSError(errno.EXDEV, "the source could not be removed")

    monkeypatch.setattr(shutil, "move", half_move)

    with pytest.raises(OSError, match="could not be removed"):
        ensure_artifact(artifact, directory, download=_RecordingDownload(contents))

    assert not (directory / "model.onnx").exists(), "the half-moved file was left behind"


def test_a_symlinked_artifact_directory_is_refused(tmp_path: Path) -> None:
    # The one place `_refuse_a_blocked_entry`'s walk stops, and so the one that
    # has to be judged on its own: a link here moves the whole artifact out of
    # the tree the build packages, and every check downstream follows it.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # Complete and correct behind the link, which is the case that used to pass:
    # nothing is absent, so staging never ran and only verification looked — and
    # it follows the link like everything else.
    (elsewhere / "model.onnx").write_bytes(contents["model.onnx"])
    directory.symlink_to(elsewhere, target_is_directory=True)
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="is a symlink"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == []


def test_an_artifact_directory_that_is_a_file_is_refused(tmp_path: Path) -> None:
    # Without this the refusal is a raw `FileExistsError` out of `mkdir`, outside
    # the module's own failure contract.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.write_bytes(b"a file where the artifact directory belongs")

    with pytest.raises(SpeechArtifactError, match="is not a directory"):
        ensure_artifact(artifact, directory, download=_RecordingDownload(contents))


def test_a_manifest_naming_both_a_file_and_a_directory_of_it_is_refused(
    tmp_path: Path,
) -> None:
    # `a` and `a/b` ask for one path to be a file and a directory at once. Sorted
    # order stages `a` first, so `a/b` meets it as a raw `FileExistsError` out of
    # `mkdir` — outside this module's failure contract, and a manifest shape
    # nested-path support has to reject rather than half-perform.
    contents = {"tokens.txt": b"tokens", "tokens.txt/nested": b"nested"}
    artifact, directory = _artifact(tmp_path, contents)
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="file and a directory at once"):
        ensure_artifact(artifact, directory, download=download)

    assert download.requests == [], "the refusal comes before the download"


def test_a_seam_that_produces_nothing_is_reported(tmp_path: Path) -> None:
    class _SilentDownload:
        def __call__(
            self, *, repo_id: str, filename: str, revision: str, destination: Path
        ) -> None:
            return

    artifact, directory = _artifact(tmp_path, {"model.onnx": b"weights"})

    with pytest.raises(SpeechArtifactError, match="did not produce"):
        ensure_artifact(artifact, directory, download=_SilentDownload())


def test_a_file_the_manifest_does_not_name_is_refused(tmp_path: Path) -> None:
    # The build force-includes the whole vendored directory, so anything sitting
    # in it ships — a file left behind by an earlier pin, or one dropped there by
    # anyone with write access to the tree. Verifying only the *named* files would
    # let such a file be redistributed under this project's name with no digest and
    # no notice, which is what "the SHA-256 of every file as shipped" forecloses.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "model.onnx").write_bytes(contents["model.onnx"])
    (directory / "left-behind.onnx").write_bytes(b"from an earlier pin")

    with pytest.raises(SpeechArtifactError, match="does not name"):
        verify_artifact(artifact, directory)


def test_an_unexpected_file_is_found_in_a_nested_directory(tmp_path: Path) -> None:
    # The voice's files sit flat today, but a re-pin could nest them, and a check
    # that only listed the top level would stop seeing anything below it.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    (directory / "extra").mkdir(parents=True)
    (directory / "model.onnx").write_bytes(contents["model.onnx"])
    (directory / "extra" / "stowaway.bin").write_bytes(b"nested")

    assert unexpected_files(artifact, directory) == ["extra/stowaway.bin"]


def test_acquisition_refuses_a_directory_carrying_an_extra_file(tmp_path: Path) -> None:
    # `ensure_artifact` is what the build calls, so the refusal has to bite there
    # and not only in the helper beneath it.
    contents = {"model.onnx": b"weights"}
    artifact, directory = _artifact(tmp_path, contents)
    directory.mkdir(parents=True)
    (directory / "left-behind.onnx").write_bytes(b"from an earlier pin")
    download = _RecordingDownload(contents)

    with pytest.raises(SpeechArtifactError, match="does not name"):
        ensure_artifact(artifact, directory, download=download)

    # The manifest was fetched before the extra file was noticed, and none of it
    # is left behind: the refusal is what this build leaves, not a half-populated
    # directory a later one would find "already present" (#2081).
    assert [name for _, name, _ in download.requests] == ["model.onnx"]
    assert sorted(path.name for path in directory.iterdir()) == ["left-behind.onnx"]


def test_an_exactly_matching_directory_has_nothing_unexpected(tmp_path: Path) -> None:
    contents = {"model.onnx": b"weights", "tokens.txt": b"tokens"}
    artifact, directory = _artifact(tmp_path, contents)

    ensure_artifact(artifact, directory, download=_RecordingDownload(contents))

    assert unexpected_files(artifact, directory) == []


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

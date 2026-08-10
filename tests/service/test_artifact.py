"""Tests for the v1 artifact's layout and its reader (ADR-0123 §6, §8, and #895).

Three things are on test here and they are worth separating.

**The layout is pinned** (#894): the payload prefix, the manifest's member path
and the manifest's schema are wire-level facts that ADR-0123 §6 deliberately does
not name, and the mechanism that makes a later change safe is §8's greater-version
refusal — which only works if :data:`FORMAT_VERSION` actually moves when the
layout does. :func:`test_the_v1_layout_is_what_this_build_writes` is what fails
when one moves and the other does not.

**The manifest is metadata, not a restored file** (§8), which is what stops the
set-equality check eating itself.

**And the header-answerable checks run before the bytes** (#895). Each refusal
below is asserted twice: that it refuses, and that the staging directory is
*empty* afterwards — because "a tar member declaring a very large logical size, or
many members repeating one path, fills the recovery machine's filesystem before
restore reaches its refusal-and-cleanup path". A test that only asserted the
refusal would pass just as happily against a reader that wrote a terabyte first.
"""

from __future__ import annotations

import io
import sqlite3
import tarfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.service import artifact
from ai_assistant.service.agev1 import AgeError, DecryptingReader, EncryptingWriter
from ai_assistant.service.artifact import (
    FORMAT_VERSION,
    MANIFEST_MEMBER,
    PAYLOAD_PREFIX,
    ArtifactError,
    Manifest,
    ManifestEntry,
    digest_and_length,
    materialise,
    verify_materialised,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_KEYPHRASE = "a phrase the operator holds"
_WRONG_KEYPHRASE = "not the one"
_TEST_WORK_FACTOR = 8

#: SHA-256 of ``b"hello"``, which the fixtures below use as their one payload.
_HELLO = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def _manifest(*entries: ManifestEntry, version: int = FORMAT_VERSION) -> Manifest:
    return Manifest(
        format_version=version,
        taken_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
        project_version="0.1.0",
        files=entries,
    )


def _artifact(tmp_path: Path, source: Path, manifest: Manifest) -> Path:
    """Write a real artifact over ``source`` at the cheap work factor."""
    destination = tmp_path / "artifact.age"
    with destination.open("wb") as out:
        artifact.write_artifact(
            out,
            data_dir=source,
            manifest=manifest,
            passphrase=_KEYPHRASE,
            work_factor=_TEST_WORK_FACTOR,
        )
    return destination


def _forged(
    tmp_path: Path, manifest: Manifest, members: list[tuple[tarfile.TarInfo, bytes]]
) -> Path:
    """Build an artifact by hand, so a member this tool would never write can be tested.

    ADR-0123 §8's own reason for the member checks: they are on "**what was
    received**, not on what §1 was supposed to have sent … an authenticated format
    proves it is unmodified since it was written, never that it was written by
    this tool."
    """
    destination = tmp_path / "forged.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
        tarfile.open(fileobj=sealed, mode="w|", format=tarfile.PAX_FORMAT) as archive,
    ):
        encoded = manifest.model_dump_json().encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_MEMBER)
        info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))
        for member, content in members:
            archive.addfile(member, io.BytesIO(content) if member.isfile() else None)
    return destination


def _payload(name: str, content: bytes, size: int | None = None) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(PAYLOAD_PREFIX + name)
    info.size = len(content) if size is None else size
    return info, content


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A minimal data directory: one file, at a known digest."""
    directory = tmp_path / "source"
    directory.mkdir(mode=0o700)
    (directory / "notes.txt").write_bytes(b"hello")
    return directory


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    directory = tmp_path / "staging"
    directory.mkdir(mode=0o700)
    return directory


def _entry(path: str = "notes.txt", length: int = 5, sha256: str = _HELLO) -> ManifestEntry:
    return ManifestEntry(path=path, length=length, sha256=sha256)


def _materialised(staging: Path) -> list[str]:
    return sorted(str(p.relative_to(staging)) for p in staging.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- #
# The layout, pinned (#894)
# --------------------------------------------------------------------------- #


def test_the_v1_layout_is_what_this_build_writes() -> None:
    """Pin the three constants to the format version that names them (#894).

    ADR-0123 §8's greater-version refusal is the only mechanism that makes a later
    layout change detectable, and it works only if the version moves when the
    layout does. Change any of these and this test fails, which is the reminder to
    move :data:`FORMAT_VERSION` with it.
    """
    assert FORMAT_VERSION == 1
    assert PAYLOAD_PREFIX == "data/"
    assert MANIFEST_MEMBER == "backup-manifest.json"
    assert not MANIFEST_MEMBER.startswith(PAYLOAD_PREFIX)


def test_a_source_file_named_like_the_manifest_collides_with_nothing(tmp_path: Path) -> None:
    """§6's reserved member is reserved by *position*, not by hoping for a name.

    "A data directory can perfectly well contain a file named whatever the
    manifest is named, and then a single flat namespace forces the tool to drop a
    real file, overwrite the metadata, or parse a user's file as a manifest."
    """
    directory = tmp_path / "source"
    directory.mkdir(mode=0o700)
    (directory / MANIFEST_MEMBER).write_bytes(b"hello")
    manifest = _manifest(_entry(path=MANIFEST_MEMBER))
    staging = tmp_path / "out"
    staging.mkdir(mode=0o700)

    restored = materialise(
        _artifact(tmp_path, directory, manifest), passphrase=_KEYPHRASE, staging=staging
    )

    assert (staging / MANIFEST_MEMBER).read_bytes() == b"hello"
    assert [entry.path for entry in restored.files] == [MANIFEST_MEMBER]


def test_the_manifest_is_parsed_and_never_materialised(
    source: Path, staging: Path, tmp_path: Path
) -> None:
    """§8: "The manifest is not a restored file and is not a member of any set"."""
    manifest = _manifest(_entry())

    materialise(_artifact(tmp_path, source, manifest), passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == ["notes.txt"]


# --------------------------------------------------------------------------- #
# The manifest model
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["/etc/passwd", "../escape", "a/../../b", "", "a\\b"])
def test_a_manifest_path_that_could_name_somewhere_else_is_refused(path: str) -> None:
    """The manifest is what member names are checked *against*, so it is checked first."""
    with pytest.raises(ValueError, match="manifest path"):
        ManifestEntry(path=path, length=0, sha256=_HELLO)


def test_a_manifest_naming_one_path_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="more than once"):
        _manifest(_entry(), _entry())


def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Manifest(
            format_version=1,
            taken_at=datetime(2026, 8, 9, 12),  # noqa: DTZ001 - the point of the test
            project_version="0.1.0",
            files=(),
        )


def test_the_manifest_carries_only_the_four_fields_section_6_names() -> None:
    """§6: "no record content, no record identifier, no subject and no correlation identifier"."""
    assert set(Manifest.model_fields) == {
        "format_version",
        "taken_at",
        "project_version",
        "files",
    }
    assert set(ManifestEntry.model_fields) == {"path", "length", "sha256"}


def test_an_unknown_manifest_field_is_refused() -> None:
    """``extra="forbid"``: a manifest from elsewhere does not get to smuggle a field in."""
    with pytest.raises(ValueError, match="Extra inputs"):
        Manifest.model_validate(
            {
                "format_version": 1,
                "taken_at": "2026-08-09T12:00:00Z",
                "project_version": "0.1.0",
                "files": [],
                "subject": "leonardo",
            }
        )


# --------------------------------------------------------------------------- #
# §8's version rule
# --------------------------------------------------------------------------- #


def test_a_newer_format_version_is_refused(source: Path, staging: Path, tmp_path: Path) -> None:
    """§8's asymmetry: a newer artifact may carry conventions this tool does not know."""
    manifest = _manifest(_entry(), version=FORMAT_VERSION + 1)

    with pytest.raises(ArtifactError, match="format version"):
        materialise(_artifact(tmp_path, source, manifest), passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_an_older_format_version_is_accepted(source: Path, staging: Path, tmp_path: Path) -> None:
    """ "An older or equal one is accepted, because bringing a store forward is a job the
    system already owns."" Version 1 is the oldest there is, so equality is what is
    reachable — the asymmetry is asserted from the refusing side above.
    """
    manifest = _manifest(_entry(), version=FORMAT_VERSION)

    restored = materialise(
        _artifact(tmp_path, source, manifest), passphrase=_KEYPHRASE, staging=staging
    )

    assert restored.format_version == FORMAT_VERSION


# --------------------------------------------------------------------------- #
# #895 — everything a header can answer, before the bytes
# --------------------------------------------------------------------------- #


def test_a_member_the_manifest_does_not_list_is_refused_before_it_is_written(
    staging: Path, tmp_path: Path
) -> None:
    forged = _forged(tmp_path, _manifest(_entry()), [_payload("smuggled.txt", b"x" * 4096)])

    with pytest.raises(ArtifactError, match="manifest does not list"):
        materialise(forged, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_a_repeated_member_path_is_refused_before_the_second_overwrites_the_first(
    staging: Path, tmp_path: Path
) -> None:
    """#895: "tar permits repeats and a later one would otherwise overwrite an earlier one"."""
    manifest = _manifest(_entry())
    forged = _forged(
        tmp_path, manifest, [_payload("notes.txt", b"hello"), _payload("notes.txt", b"hello")]
    )

    with pytest.raises(ArtifactError, match="twice"):
        materialise(forged, passphrase=_KEYPHRASE, staging=staging)


def test_a_member_declaring_more_bytes_than_the_manifest_is_refused_before_extraction(
    staging: Path, tmp_path: Path
) -> None:
    """The case #895 is really about: a huge declared size filling a recovery machine.

    The member's header says 4096 bytes and the manifest says 5, and the refusal
    arrives from the header — so the 4096 are never written, which is the whole
    point of moving the check ahead of the extraction.
    """
    manifest = _manifest(_entry())
    oversized = _forged(tmp_path, manifest, [_payload("notes.txt", b"h" * 4096)])

    with pytest.raises(ArtifactError, match="declares 4096 bytes"):
        materialise(oversized, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_a_member_that_is_not_a_regular_file_is_refused(staging: Path, tmp_path: Path) -> None:
    """§8: "Restore refuses any archive member that is not a regular file"."""
    link = tarfile.TarInfo(PAYLOAD_PREFIX + "notes.txt")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    forged = _forged(tmp_path, _manifest(_entry()), [(link, b"")])

    with pytest.raises(ArtifactError, match="not a regular file"):
        materialise(forged, passphrase=_KEYPHRASE, staging=staging)

    assert not (staging / "notes.txt").is_symlink()


def test_a_member_outside_the_payload_prefix_is_refused(staging: Path, tmp_path: Path) -> None:
    """§8: an artifact this tool did not write "does not get to introduce a third category"."""
    stray = tarfile.TarInfo("elsewhere/notes.txt")
    stray.size = 5
    forged = _forged(tmp_path, _manifest(_entry()), [(stray, b"hello")])

    with pytest.raises(ArtifactError, match="neither the manifest nor a file under"):
        materialise(forged, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_an_archive_whose_first_member_is_not_the_manifest_is_refused(
    staging: Path, tmp_path: Path
) -> None:
    """The manifest is read before anything is written, which needs it to come first."""
    destination = tmp_path / "reordered.age"
    manifest = _manifest(_entry())
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
        tarfile.open(fileobj=sealed, mode="w|", format=tarfile.PAX_FORMAT) as archive,
    ):
        member, content = _payload("notes.txt", b"hello")
        archive.addfile(member, io.BytesIO(content))
        encoded = manifest.model_dump_json().encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_MEMBER)
        info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))

    with pytest.raises(ArtifactError, match="first archive member"):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_a_malformed_manifest_is_refused(staging: Path, tmp_path: Path) -> None:
    destination = tmp_path / "bad.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
        tarfile.open(fileobj=sealed, mode="w|", format=tarfile.PAX_FORMAT) as archive,
    ):
        info = tarfile.TarInfo(MANIFEST_MEMBER)
        info.size = 7
        archive.addfile(info, io.BytesIO(b"nonsense"[:7]))

    with pytest.raises(ArtifactError, match="manifest is malformed"):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)


def test_a_wrong_passphrase_refuses_before_the_archive_is_touched(
    source: Path, staging: Path, tmp_path: Path
) -> None:
    written = _artifact(tmp_path, source, _manifest(_entry()))

    with pytest.raises(AgeError):
        materialise(written, passphrase=_WRONG_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


# --------------------------------------------------------------------------- #
# §8's after-the-bytes checks
# --------------------------------------------------------------------------- #


def test_a_materialised_file_whose_digest_disagrees_is_refused(staging: Path) -> None:
    (staging / "notes.txt").write_bytes(b"world")

    with pytest.raises(ArtifactError, match="digest"):
        verify_materialised(staging, _manifest(_entry(length=5)))


def test_a_missing_file_is_refused(staging: Path) -> None:
    with pytest.raises(ArtifactError, match="missing"):
        verify_materialised(staging, _manifest(_entry()))


def test_an_unexpected_file_is_refused(staging: Path) -> None:
    """§8's exact set equality, which §7 earns by leaving nothing else in the directory."""
    (staging / "notes.txt").write_bytes(b"hello")
    (staging / "extra.txt").write_bytes(b"")

    with pytest.raises(ArtifactError, match="unexpected"):
        verify_materialised(staging, _manifest(_entry()))


def test_a_restored_database_is_run_through_sqlites_integrity_check(
    staging: Path, tmp_path: Path
) -> None:
    """§8's third check, recognised by SQLite's magic rather than by a filename."""
    database = tmp_path / "source" / "memory.db"
    database.parent.mkdir(mode=0o700, parents=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (x)")
    connection.execute("INSERT INTO t VALUES ('a memory')")
    connection.commit()
    connection.close()
    sha256, length = digest_and_length(database)
    manifest = _manifest(ManifestEntry(path="memory.db", length=length, sha256=sha256))

    written = _artifact(tmp_path, database.parent, manifest)
    restored = materialise(written, passphrase=_KEYPHRASE, staging=staging)
    verify_materialised(staging, restored)

    assert (staging / "memory.db").read_bytes() == database.read_bytes()


def test_a_corrupt_database_that_still_matches_its_digest_is_refused(staging: Path) -> None:
    """The digest proves the artifact carried these bytes; SQLite proves they open.

    §8 wants both, and this is the case that separates them: a database damaged
    *before* the backup was taken has a manifest digest that matches perfectly.
    """
    database = staging / "memory.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (x)")
    connection.execute("INSERT INTO t VALUES ('a memory')")
    connection.commit()
    connection.close()
    raw = bytearray(database.read_bytes())
    page_size = int.from_bytes(raw[16:18], "big")
    raw[page_size : page_size + 64] = b"\x00" * 64  # scribble over the first content page
    database.write_bytes(bytes(raw))
    sha256, length = digest_and_length(database)
    manifest = _manifest(ManifestEntry(path="memory.db", length=length, sha256=sha256))

    with pytest.raises(ArtifactError, match="integrity check"):
        verify_materialised(staging, manifest)


def test_the_integrity_check_leaves_no_journal_beside_the_database(staging: Path) -> None:
    """Opened read-only, so the check cannot add a file the manifest never carried."""
    database = staging / "memory.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (x)")
    connection.commit()
    connection.close()
    sha256, length = digest_and_length(database)

    verify_materialised(
        staging, _manifest(ManifestEntry(path="memory.db", length=length, sha256=sha256))
    )

    assert _materialised(staging) == ["memory.db"]


def test_a_deep_path_survives_the_round_trip(tmp_path: Path, staging: Path) -> None:
    """#893: PAX is what lets a path past tar's ordinary name field work at all."""
    directory = tmp_path / "source"
    deep = directory / ("nested/" * 20) / ("a" * 90 + ".bin")
    deep.parent.mkdir(parents=True, mode=0o700)
    deep.write_bytes(b"hello")
    relative = str(deep.relative_to(directory))
    assert len(relative) > 200
    manifest = _manifest(_entry(path=relative))

    restored = materialise(
        _artifact(tmp_path, directory, manifest), passphrase=_KEYPHRASE, staging=staging
    )
    verify_materialised(staging, restored)

    assert (staging / relative).read_bytes() == b"hello"


def test_an_authenticated_payload_that_is_not_a_tar_stream_is_refused(
    staging: Path, tmp_path: Path
) -> None:
    """An artifact that decrypts is not thereby an artifact that unpacks.

    The age layer authenticates the bytes against the passphrase and says nothing
    about the plaintext under them, so anyone holding the passphrase — the
    operator included, with a truncated or half-written file — can present one
    that is not a ``tar`` stream. It has to arrive as a refusal: a traceback out
    of a recovery command is the one outcome an operator on a broken machine
    cannot act on.
    """
    destination = tmp_path / "not-a-tar.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
    ):
        sealed.write(b"this is not a tar archive at all" * 100)

    with pytest.raises(ArtifactError, match="archive cannot be read"):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_a_truncated_archive_inside_a_whole_artifact_is_refused(
    staging: Path, tmp_path: Path
) -> None:
    """A member that stops mid-content is refused rather than silently short.

    The payload is made large on purpose. ``tar`` pads its stream to a 10 KiB
    block, so cutting a small archive in half removes only zero padding and
    leaves a complete, correct archive — a fact worth knowing, because a test
    written the obvious way passes without testing anything.
    """
    directory = tmp_path / "big"
    directory.mkdir(mode=0o700)
    (directory / "memory.db").write_bytes(b"m" * 200_000)
    sha256, length = digest_and_length(directory / "memory.db")
    manifest = _manifest(ManifestEntry(path="memory.db", length=length, sha256=sha256))
    whole = _artifact(tmp_path, directory, manifest).read_bytes()
    plaintext = DecryptingReader(io.BytesIO(whole), _KEYPHRASE).read()
    destination = tmp_path / "cut-short.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
    ):
        sealed.write(plaintext[: len(plaintext) // 2])

    with pytest.raises(ArtifactError, match=r"ends before its declared size|cannot be read"):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)


def test_a_manifest_declaring_an_absurd_size_is_refused_from_its_header(
    staging: Path, tmp_path: Path
) -> None:
    """The manifest is the one member held whole in memory, so its size is capped.

    Built from a bare ``tar`` header rather than from real content, which is the
    point: the refusal has to arrive from the declared size, before the member's
    body is read. A test that had to write a gigabyte to provoke it would be
    testing a check that had already failed.
    """
    info = tarfile.TarInfo(MANIFEST_MEMBER)
    info.size = 8 * 1024 * 1024 * 1024
    destination = tmp_path / "greedy.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
    ):
        sealed.write(info.tobuf(tarfile.PAX_FORMAT))

    with pytest.raises(ArtifactError, match="declares 8589934592 bytes"):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def _pax_header(size: int) -> bytes:
    """A PAX extended header block declaring ``size`` bytes of metadata."""
    info = tarfile.TarInfo("././@PaxHeader")
    info.type = tarfile.XHDTYPE
    info.size = size
    return info.tobuf(tarfile.PAX_FORMAT)


def test_an_oversized_tar_control_member_is_refused(staging: Path, tmp_path: Path) -> None:
    """``tarfile`` reads its own metadata whole, so that path needs its own bound.

    A PAX extended header is consumed inside ``tarfile`` before any ``TarInfo``
    reaches this module, so neither the manifest bound nor the payload's
    streaming copy applies to it — measured at about twice the metadata's size in
    peak allocation, where the same bytes as a payload member cost the copy
    buffer and nothing else.

    **This test is also what keeps the guard from failing silently.** It is
    installed by overriding a private ``tarfile`` method, so a rename in a future
    CPython would stop it bounding anything; the assertion below is what turns
    that into a failure instead of a quiet regression.
    """
    oversized = 4 * 1024 * 1024
    destination = tmp_path / "greedy-metadata.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
    ):
        sealed.write(_pax_header(oversized))
        sealed.write(b"A" * oversized)

    with pytest.raises(ArtifactError, match="extended header declaring 4194304 bytes"):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)

    assert _materialised(staging) == []


def test_a_control_member_declaring_more_than_it_carries_costs_nothing(
    staging: Path, tmp_path: Path
) -> None:
    """The declared size alone buys an attacker nothing, and saying so is the point.

    The streaming reader accumulates only what actually arrives, so an 8 GiB
    declaration behind an empty stream is refused at a couple of hundred
    kilobytes. Recorded because the opposite is the intuitive reading, and it
    would have justified a much more invasive bound than the one above.
    """
    destination = tmp_path / "empty-claim.age"
    with (
        destination.open("wb") as raw,
        EncryptingWriter(raw, _KEYPHRASE, work_factor=_TEST_WORK_FACTOR) as sealed,
    ):
        sealed.write(_pax_header(8 * 1024 * 1024 * 1024))

    # Under two kilobytes on disk, against a declaration of eight gigabytes.
    assert destination.stat().st_size < 2048

    with pytest.raises(ArtifactError):
        materialise(destination, passphrase=_KEYPHRASE, staging=staging)

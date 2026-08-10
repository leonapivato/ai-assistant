"""The v1 backup artifact: what is inside it, and how it is read back safely.

ADR-0123 §6 fixes the artifact's shape — "every copied file under one fixed
top-level prefix", "the manifest at a fixed member path outside that prefix" —
and §8 fixes what restore checks before it will publish anything. It names
neither string and fixes no serialization, deliberately: issue #894 records that
naming wire-level constants in an append-only ADR is the expensive place to get
them wrong, and that the lane owes them pinned in one module instead. This is
that module.

**The three constants and the version move together.** :data:`FORMAT_VERSION` is
what §8's asymmetric refusal reads — "Restore refuses an artifact whose recorded
format version is greater than the version the tool implements" — so it is only a
mechanism if the version actually moves when the layout does. Changing
:data:`PAYLOAD_PREFIX`, :data:`MANIFEST_MEMBER` or the manifest's schema without
bumping :data:`FORMAT_VERSION` produces two mutually unreadable "version 1"
artifacts; ``tests/service/test_artifact.py`` fails when a constant changes and
the version does not.

**The manifest is metadata, not a restored file** (§8). It travels in the same
``tar`` stream, is parsed rather than materialised, and is excluded from every
set the checks below compare — which is what stops the equality check eating
itself, since a manifest that listed itself would need a digest over bytes that
are not final until the digest is in them.

**Reading is a streaming, header-first operation, and that is issue #895.** §8's
digest and set checks necessarily run after the bytes are on disk. Everything a
``tar`` header can answer runs *before* them: the member's type, its name's
safety, its declared size against the manifest's length, a repeated path, and the
running total against the manifest's own total. The manifest is the first member
of the archive by construction, so all of that is available before the first
payload byte is written. Without it, "a tar member declaring a very large logical
size, or many members repeating one path, fills the recovery machine's filesystem
before restore reaches its refusal-and-cleanup path — even when the manifest's own
set is tiny" (#895), which is a failure that lands during a disaster recovery on
the one machine the operator is depending on.
"""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import sqlite3
import stat
import tarfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_assistant.service.agev1 import DEFAULT_WORK_FACTOR, DecryptingReader, EncryptingWriter
from ai_assistant.service.refusal import RefusalError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import BinaryIO, Self

#: The artifact layout this build writes and the highest it reads (ADR-0123 §8).
FORMAT_VERSION: Final = 1

#: Every copied file lives under this one prefix, and nothing else does. §6's
#: "one fixed top-level prefix" is what makes the manifest's member name reserved
#: rather than merely asserted: a data directory may legitimately hold a file
#: called whatever the manifest is called, and under a single flat namespace the
#: tool would have to drop a real file, overwrite the metadata, or parse a user's
#: file as a manifest.
PAYLOAD_PREFIX: Final = "data/"

#: The manifest's member path, outside :data:`PAYLOAD_PREFIX` and therefore
#: unreachable by any source file's name.
MANIFEST_MEMBER: Final = "backup-manifest.json"

#: The archive's tar dialect, pinned rather than inherited (#893). ``PAX_FORMAT``
#: is what lets a path too long for tar's ordinary name field survive at all, via
#: an extended header ``tarfile`` consumes internally; a future change to
#: ``tarfile``'s default would otherwise silently truncate or refuse a deep path.
_TAR_FORMAT: Final = tarfile.PAX_FORMAT

#: How much is copied at a time, in and out of the archive.
_COPY_BYTES: Final = 1024 * 1024

#: Owner-only, applied to everything this module creates (ADR-0123 §7, §9): what
#: is being unpacked is the plaintext Tier 1 store.
_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

#: SQLite's file magic, which is how a restored database is recognised for §8's
#: integrity check without a list of database filenames anywhere (§1).
SQLITE_MAGIC: Final = b"SQLite format 3\x00"

#: What ``PRAGMA integrity_check`` says when it has nothing to say.
_INTEGRITY_OK: Final = "ok"

#: The most the manifest member may declare before restore will read it.
#:
#: The manifest is the one member read whole into memory rather than streamed to
#: disk, because it has to be parsed before anything else can be checked against
#: it — so its declared size is the one number an artifact can use to make a
#: recovery machine allocate. That is the same failure #895 is about, one member
#: earlier: "a tar member declaring a very large logical size … fills the recovery
#: machine's filesystem before restore reaches its refusal-and-cleanup path."
#:
#: 64 MiB is far above any real manifest and far below anything that hurts. An
#: entry is a path, a length and a 64-character digest — on the order of 150 bytes
#: — so this admits something like 400,000 files, where the hub's data directory
#: holds seven and ADR-0104 §3's retained copy makes it eight.
_MAX_MANIFEST_BYTES: Final = 64 * 1024 * 1024


class ArtifactError(RefusalError):
    """An artifact is malformed, or disagrees with its own manifest.

    Every instance of this is a refusal under ADR-0123 §7's cleanup clause: the
    staging directory is removed whole and the target path is not touched.
    """


class ManifestEntry(BaseModel):
    """One copied file, as the manifest records it (ADR-0123 §6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(description="the file's path relative to the data directory, POSIX-style")
    length: int = Field(ge=0, description="the file's byte length when it was copied")
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="a SHA-256 digest of the file's contents, lowercase"
    )

    @field_validator("path")
    @classmethod
    def _path_is_relative_and_plain(cls, value: str) -> str:
        """Refuse a path that could name somewhere other than inside the store.

        Checked on the *manifest* rather than only on the archive members,
        because the manifest is what the member checks are compared against: a
        manifest carrying ``../etc/passwd`` would otherwise turn "the member's
        path is in the manifest" from a restriction into an authorisation.
        """
        if not value or value != posixpath.normpath(value):
            msg = f"manifest path {value!r} is empty or not normalised"
            raise ValueError(msg)
        if posixpath.isabs(value) or value.startswith("../") or "\\" in value or "\x00" in value:
            msg = f"manifest path {value!r} is absolute, escapes the store, or is not portable"
            raise ValueError(msg)
        return value


class Manifest(BaseModel):
    """What the artifact says it carries (ADR-0123 §6).

    It answers completeness and provenance and deliberately does not answer
    integrity — §4's format already makes a corrupted artifact undecryptable. It
    carries "no record content, no record identifier, no subject and no
    correlation identifier", which is a property of the fields below being the
    only ones there are.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    format_version: int = Field(ge=1, description="the artifact layout this was written to")
    taken_at: datetime = Field(description="when the backup was taken, timezone-aware")
    project_version: str = Field(min_length=1, description="the build that wrote it")
    files: tuple[ManifestEntry, ...] = Field(description="every copied file, in walk order")

    @field_validator("taken_at")
    @classmethod
    def _instant_is_aware(cls, value: datetime) -> datetime:
        """Refuse a naive instant: "which backup is this" needs an offset to answer."""
        if value.tzinfo is None:
            msg = "the manifest's instant must carry a timezone"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _paths_are_unique(self) -> Self:
        """Refuse a manifest naming one path twice (#894).

        A repeated path makes the set comparison in :func:`verify_materialised`
        ambiguous and would let two archive members both claim to be expected.
        """
        seen = {entry.path for entry in self.files}
        if len(seen) != len(self.files):
            msg = "the manifest lists a path more than once"
            raise ValueError(msg)
        return self

    @property
    def total_length(self) -> int:
        """The sum of every entry's length, which bounds what a restore may write."""
        return sum(entry.length for entry in self.files)

    def by_path(self) -> dict[str, ManifestEntry]:
        """The entries keyed by path, for the member checks."""
        return {entry.path: entry for entry in self.files}


def digest_and_length(path: Path) -> tuple[str, int]:
    """Read a file once, returning its SHA-256 and its byte length.

    Args:
        path: The file to read.

    Returns:
        The lowercase hex digest and the length in bytes.
    """
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while block := handle.read(_COPY_BYTES):
            digest.update(block)
            length += len(block)
    return digest.hexdigest(), length


def write_artifact(
    out: BinaryIO,
    *,
    data_dir: Path,
    manifest: Manifest,
    passphrase: str,
    work_factor: int = DEFAULT_WORK_FACTOR,
) -> None:
    """Stream the manifest and every copied file into ``out`` as one age artifact.

    **The manifest goes first**, which is a property of this layout rather than
    of the ADR: §8 has restore parse the manifest before it materialises
    anything, and a single forward pass over a streamed archive can only do that
    if the manifest is the member it meets first (#895).

    Args:
        out: Where the ciphertext goes — the temporary file ADR-0123 §2 requires.
        data_dir: The directory the manifest's paths are relative to.
        manifest: What is being carried.
        passphrase: The artifact's key (ADR-0123 §5).
        work_factor: Passed through to the age writer; lowered only by tests.

    Raises:
        OSError: If a source file cannot be read. Left to propagate — the caller
            removes the temporary file and reports the failure.
    """
    with (
        EncryptingWriter(out, passphrase, work_factor=work_factor) as sealed,
        tarfile.open(fileobj=sealed, mode="w|", format=_TAR_FORMAT) as archive,
    ):
        encoded = manifest.model_dump_json().encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_MEMBER)
        info.size = len(encoded)
        info.mode = _FILE_MODE
        info.mtime = int(manifest.taken_at.timestamp())
        archive.addfile(info, io.BytesIO(encoded))
        for entry in manifest.files:
            source = data_dir / entry.path
            member = tarfile.TarInfo(PAYLOAD_PREFIX + entry.path)
            member.size = entry.length
            member.mode = _FILE_MODE
            with source.open("rb") as handle:
                archive.addfile(member, handle)


def materialise(artifact: Path, *, passphrase: str, staging: Path) -> Manifest:
    """Unpack an artifact into ``staging``, refusing before it writes where it can.

    This is the one reader, shared by ``ai-assistant-restore`` and by the backup
    tool's own §9 verification — which is what makes "verify by restoring" mean
    the same checks rather than a similar set of them.

    Args:
        artifact: The age v1 file to read.
        passphrase: The operator's passphrase.
        staging: An existing, empty, owner-only directory to materialise into.

    Returns:
        The manifest the artifact carried.

    Raises:
        ArtifactError: On any of §8's refusals, or any of #895's header-answerable
            ones. Nothing outside ``staging`` is touched on any of them.
        AgeError: If the artifact does not decrypt (:mod:`ai_assistant.service.agev1`).
        OSError: If ``staging`` cannot be written.
    """
    try:
        with artifact.open("rb") as raw:
            reader = DecryptingReader(raw, passphrase)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                members = iter(archive)
                manifest = _read_manifest(archive, members)
                _materialise_payload(archive, members, manifest=manifest, staging=staging)
    except tarfile.TarError as exc:
        # An artifact that decrypts is not thereby an artifact that unpacks: the
        # age layer authenticates the bytes against the passphrase, and says
        # nothing about whether the plaintext under them is a ``tar`` stream at
        # all. §8 is explicit that the checks are on "what was received, not on
        # what §1 was supposed to have sent", so this is a refusal like any other
        # — and a traceback out of a recovery command is the one outcome an
        # operator on a broken machine cannot act on.
        msg = f"the artifact decrypts but its archive cannot be read: {exc}"
        raise ArtifactError(msg) from exc
    return manifest


def _read_manifest(archive: tarfile.TarFile, members: Iterator[tarfile.TarInfo]) -> Manifest:
    """Take the archive's first member as the manifest, and refuse anything else."""
    first = next(members, None)
    if first is None:
        msg = "the artifact's archive is empty"
        raise ArtifactError(msg)
    if first.name != MANIFEST_MEMBER or not first.isfile():
        msg = (
            f"the artifact's first archive member is {first.name!r}, not the manifest at "
            f"{MANIFEST_MEMBER!r}; this tool reads the manifest before it writes anything"
        )
        raise ArtifactError(msg)
    if first.size > _MAX_MANIFEST_BYTES:
        # Refused from the header, before a byte of it is read: the manifest is
        # the one member this tool holds whole in memory, so its declared size is
        # the one number an artifact gets to spend on a recovery machine.
        msg = (
            f"the artifact's manifest declares {first.size} bytes, past the "
            f"{_MAX_MANIFEST_BYTES} this tool will read; no manifest for a real data "
            f"directory is anywhere near that large"
        )
        raise ArtifactError(msg)
    handle = archive.extractfile(first)
    if handle is None:  # pragma: no cover - `isfile()` above already excludes it
        msg = "the artifact's manifest member carries no content"
        raise ArtifactError(msg)
    try:
        manifest = Manifest.model_validate_json(handle.read())
    except ValueError as exc:
        msg = f"the artifact's manifest is malformed: {exc}"
        raise ArtifactError(msg) from exc
    if manifest.format_version > FORMAT_VERSION:
        msg = (
            f"the artifact is format version {manifest.format_version} and this tool "
            f"implements version {FORMAT_VERSION}; it may carry files and conventions this "
            f"build does not know, so it is refused rather than partly understood"
        )
        raise ArtifactError(msg)
    return manifest


def _materialise_payload(
    archive: tarfile.TarFile,
    members: Iterator[tarfile.TarInfo],
    *,
    manifest: Manifest,
    staging: Path,
) -> None:
    """Write every payload member out, checking each header before it costs a byte."""
    expected = manifest.by_path()
    budget = manifest.total_length
    written = 0
    seen: set[str] = set()
    root = staging.resolve()
    for member in members:
        relative = _checked_relative_path(member, expected=expected, seen=seen)
        seen.add(relative)
        entry = expected[relative]
        written += entry.length
        if written > budget:
            # Unreachable while every member matches a distinct manifest entry,
            # and kept anyway: it is the one bound that does not depend on the
            # per-member checks above being exhaustive (#895).
            msg = "the artifact's members declare more bytes than its manifest accounts for"
            raise ArtifactError(msg)
        _extract(archive, member, target=_safe_target(root, relative))


def _checked_relative_path(
    member: tarfile.TarInfo, *, expected: dict[str, ManifestEntry], seen: set[str]
) -> str:
    """Answer everything about a member its ``tar`` header can answer (#895).

    Args:
        member: The header just read.
        expected: The manifest's entries by relative path.
        seen: The relative paths already materialised in this run.

    Returns:
        The member's path with :data:`PAYLOAD_PREFIX` removed.

    Raises:
        ArtifactError: If the member is not a regular file, is sparse, is named
            outside the payload prefix, repeats a path, is absent from the
            manifest, or declares a size the manifest disagrees with.
    """
    name = member.name
    if not member.isfile():
        msg = (
            f"the artifact carries {name!r}, which is not a regular file; an artifact this "
            f"tool wrote carries only regular files, and materialising anything else would "
            f"be creating a link or a device on a recovery machine"
        )
        raise ArtifactError(msg)
    if member.issparse():
        # Not supported rather than not considered (#895). A sparse member's
        # declared size and its stored size differ, which is exactly the gap the
        # size check above exists to close, and no artifact this tool writes has
        # one.
        msg = f"the artifact carries {name!r} as a sparse member, which this tool does not read"
        raise ArtifactError(msg)
    if not name.startswith(PAYLOAD_PREFIX):
        msg = (
            f"the artifact carries {name!r}, which is neither the manifest nor a file under "
            f"{PAYLOAD_PREFIX!r}; this tool reads no third kind of member"
        )
        raise ArtifactError(msg)
    relative = name[len(PAYLOAD_PREFIX) :]
    if relative in seen:
        msg = (
            f"the artifact carries {name!r} twice; tar permits it and a later member would "
            f"overwrite the earlier one during extraction"
        )
        raise ArtifactError(msg)
    entry = expected.get(relative)
    if entry is None:
        msg = f"the artifact carries {name!r}, which its own manifest does not list"
        raise ArtifactError(msg)
    if member.size != entry.length:
        msg = (
            f"the artifact's member {name!r} declares {member.size} bytes and its manifest "
            f"records {entry.length}"
        )
        raise ArtifactError(msg)
    return relative


def _safe_target(root: Path, relative: str) -> Path:
    """Resolve a member's destination, refusing anything outside the staging root.

    Belt and braces over the manifest validator: that one refuses an absolute or
    escaping path when the manifest is parsed, and this one refuses a destination
    that resolves outside ``root`` for any other reason — a symlinked component
    among the directories this run created, say.

    Args:
        root: The resolved staging directory.
        relative: The member's data-directory-relative path.

    Returns:
        Where the member is to be written.

    Raises:
        ArtifactError: If the destination is not under ``root``.
    """
    target = root / relative
    if not target.resolve().is_relative_to(root):
        msg = f"the artifact's member {relative!r} resolves outside the restore directory"
        raise ArtifactError(msg)
    return target


def _extract(archive: tarfile.TarFile, member: tarfile.TarInfo, *, target: Path) -> None:
    """Write one member out, creating its parents and following no link.

    ``tarfile``'s own extraction is not used: it would apply the member's mode,
    owner and times, and it offers no way to refuse a symlinked component in the
    path it is writing through. Writing the bytes here keeps every file
    owner-only and every create exclusive.
    """
    target.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    source = archive.extractfile(member)
    if source is None:  # pragma: no cover - `isfile()` is checked before this
        msg = f"the artifact's member {member.name!r} carries no content"
        raise ArtifactError(msg)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(target, flags, _FILE_MODE), "wb") as handle:
        remaining = member.size
        while remaining > 0:
            block = source.read(min(_COPY_BYTES, remaining))
            if not block:
                msg = f"the artifact's member {member.name!r} ends before its declared size"
                raise ArtifactError(msg)
            handle.write(block)
            remaining -= len(block)


def verify_materialised(staging: Path, manifest: Manifest) -> None:
    """Run ADR-0123 §8's after-the-bytes checks over a materialised directory.

    Three of them, in the order §8 states: the set of regular files equals the
    manifest's set exactly, each file's length and digest equal the manifest's,
    and every restored SQLite database passes SQLite's own integrity check. §8
    can ask for exact set equality because §7 leaves nothing else in the staging
    directory to except — no lock file, nothing this run did not put there.

    Args:
        staging: The directory just materialised into.
        manifest: What the artifact said it carried.

    Raises:
        ArtifactError: On any mismatch, or on a database SQLite reports as
            damaged.
    """
    found = {str(path.relative_to(staging).as_posix()) for path in _regular_files(staging)}
    declared = {entry.path for entry in manifest.files}
    if found != declared:
        missing = sorted(declared - found)
        extra = sorted(found - declared)
        msg = (
            f"the restored directory does not match the manifest: {len(missing)} file(s) "
            f"missing {missing[:5]}, {len(extra)} unexpected {extra[:5]}"
        )
        raise ArtifactError(msg)
    for entry in manifest.files:
        path = staging / entry.path
        digest, length = digest_and_length(path)
        if length != entry.length or digest != entry.sha256:
            msg = (
                f"the restored {entry.path} is {length} bytes with digest {digest[:16]}…, and "
                f"the manifest records {entry.length} bytes with digest {entry.sha256[:16]}…"
            )
            raise ArtifactError(msg)
        if _is_sqlite(path):
            _check_integrity(path)


def _regular_files(root: Path) -> Iterator[Path]:
    """Every regular file under ``root``, at any depth, following no symlink."""
    for parent, _directories, names in os.walk(root, followlinks=False):
        for name in names:
            candidate = Path(parent) / name
            if stat.S_ISREG(candidate.lstat().st_mode):
                yield candidate


def _is_sqlite(path: Path) -> bool:
    """Whether a file's first bytes are SQLite's magic."""
    with path.open("rb") as handle:
        return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def _check_integrity(path: Path) -> None:
    """Run ``PRAGMA integrity_check`` over a restored database (ADR-0123 §8).

    Opened read-only through a URI so the check cannot create a journal beside
    the file it is checking, which would otherwise leave the staging directory
    holding a file the manifest never carried.

    Args:
        path: The database to check.

    Raises:
        ArtifactError: If SQLite reports anything but ``ok``, or cannot open it.
    """
    uri = f"file:{path.as_uri().removeprefix('file:')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        msg = f"the restored {path.name} cannot be opened by SQLite: {exc}"
        raise ArtifactError(msg) from exc
    try:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        msg = f"the restored {path.name} fails SQLite's integrity check: {exc}"
        raise ArtifactError(msg) from exc
    finally:
        connection.close()
    reported = [row[0] for row in rows]
    if reported != [_INTEGRITY_OK]:
        msg = f"the restored {path.name} fails SQLite's integrity check: {'; '.join(reported)}"
        raise ArtifactError(msg)


def relative_paths(entries: Sequence[ManifestEntry]) -> list[str]:
    """The manifest's paths, for a diagnostic that lists what an artifact holds."""
    return [entry.path for entry in entries]

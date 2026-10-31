"""Fresh-state memory format boundary for ADR-0275 §12.

Advanced by ADRs 0276, 0280, 0281, 0283, 0284, 0286, 0307, 0308 and 0315; since then,
each store's own label by ADRs 0328, 0332, 0338, 0345, 0349, 0350, 0352, 0351, 0353
and 0356.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Final

from ai_assistant.core.errors import IncompatibleStateError, MemoryStoreError

#: The episode-record format this build writes and the only one it serves. ADR-0275
#: §12 minted the marker at 1 for the M36 record; ADR-0276 §7 advances it to 2 for the
#: schema_version-2 record, so a store written before that tree is refused before
#: mutation exactly as a pre-M36 store is, its files neither erased nor upgraded; ADR-0280
#: §7 advances it to 3 for the schema_version-3 record, and ADR-0281 §6 to 4 for the
#: schema_version-4 record, on the same terms. ADR-0283 §12 advances it to 5 for the
#: numbered, channel-indexed memory store and ``ActivationLinks.parks``, in the memory
#: store and the conversation store alike, again with no migration or version-4 read.
#: ADR-0284 §9 advances it to 6 for the schema_version-5 record, which loses
#: ``response_kind``, ``model_eligible``, the trigger's ``conversation`` and the episode's
#: ``disposition``, and requires ``origin`` and a resume's stages — with no migration or
#: earlier read path, so the hub moves to a fresh data directory. ADR-0286 §13 advances it
#: to 7 for the schema_version-6 record, which may be open, and for the memory store's
#: indexed open column, on the same terms. ADR-0307 §10 advances the record to
#: schema_version 7 for planning's rounds and labels, which a version-6 record does not
#: validate as, so the marker advances to 8 on the same terms: the phases start on the
#: cutover's fresh data directory (ADR-0309 §6:1). ADR-0308 §7 advances the record to
#: schema_version 8 for the digests, which a version-7 record does not validate as, so
#: the marker advances to 9 on the same terms (ADR-0308 §7:3). ADR-0308 §7 advances the
#: record to schema_version 9 for recall's second run, which a version-8 record does not
#: validate as, so the marker advances to 10 on the same terms. ADR-0315 §5 advances the
#: record to schema_version 10, whose rounds lose the mark asking for another round, which
#: a version-9 record does not validate as, so the marker advances to 11 on the same terms.
#: ADR-0318 §7:1 advances the record to schema_version 11, which loses the old path's
#: links, resume trigger, compose-stage degradation and stage verdicts, and the memory
#: store loses the parks index over ``links.parks``; a version-10 record does not
#: validate as it, so the marker advances to 12, again with no migration or reader for
#: an older store (ADR-0309 §6:4).
EPISODE_RECORD_FORMAT: Final[int] = 12

#: The memory store's label for ADR-0328's memory record, written into the same
#: ``episode_record_format`` table of ``memory.db`` alone (ADR-0328 §16:8). ADR-0328
#: advances it from :data:`EPISODE_RECORD_FORMAT`, which the conversation store kept
#: until :data:`CONVERSATION_RECORD_FORMAT`, to 13: a file at 12 is **upgraded** in
#: place when the store opens, never refused (ADR-0326 §4:7), and an older build, which
#: serves exactly 12, refuses a file at 13 rather than misreading it (ADR-0326 §5:3).
MEMORIES_RECORD_FORMAT: Final[int] = 13

#: The memory store's label for ADR-0332 §7:8's record. It advances to 14 for the
#: episode record's ``joined``, its understandings' ``continues`` and the takeover's stage
#: and rule: a file at 13 is upgraded in place by the label alone, since a record
#: written at 13 validates unchanged, and an older build, which serves 12 and 13, refuses
#: a file at 14, whose records it would misread (ADR-0326 §5:3).
JOINED_RECORD_FORMAT: Final[int] = 14

#: The memory store's label for ADR-0338 §4:4's record. It advances to 15 for the pin's
#: support: ``SupportOrigin`` gains ``pinned`` and ``SupportPart`` the part ``pin``,
#: members of closed enumerations a stored memory names (ADR-0326 §2:3). A file at 14 is
#: upgraded in place by the label alone, since a record written at 14 validates
#: unchanged, and an older build, which serves 12 to 14, refuses a file at 15, whose
#: pinned supports it would not read (ADR-0326 §5:3).
PINNED_RECORD_FORMAT: Final[int] = 15

#: The memory store's label for ADR-0345 §13:3's memory record. It advances to 16:
#: every support records its holder, and a memory carries labels, marks, ``subjects``
#: and ``involved`` in place of ``about_person`` and ``topics``. A file at 15 is upgraded
#: in place (§13:1), every memory rewritten by
#: :func:`~ai_assistant.memory._placed_upgrade.placed_memory`, and an older build, which
#: serves 12 to 15, refuses a file at 16, whose memories it would not read (ADR-0326
#: §5:3).
PLACED_RECORD_FORMAT: Final[int] = 16

#: The memory store's label for ADR-0350's episode record. It advances to 17:
#: ``PlanningRound`` gains ``place`` (§12:8) and ``InputOrigin`` the member
#: ``assistant`` (§12:7), a field of a ``core`` model the store serialises in every
#: episode and a member of a closed enumeration a stored episode names (ADR-0326 §2:3). A
#: file at 16 is upgraded in place by the label alone, since a record written at 16
#: validates unchanged, and an older build, which serves 12 to 16, refuses a file at 17,
#: whose episodes it would not read (ADR-0326 §5:3, #3429).
SCHEDULED_RECORD_FORMAT: Final[int] = 17

#: The memory store's label for ADR-0349 §10:6's episode record. It advances to 18:
#: each understanding's ``continues`` becomes a sequence of the activations it continues
#: (§10:2), the shape of a value the store serialises in every episode (ADR-0326 §2:3).
#: A file at 17 is upgraded in place: each episode whose understandings record
#: ``continues`` is rewritten, one naming an activation as a one-element sequence and
#: one naming none as an empty one, and an older build, which serves 12 to 17, refuses a
#: file at 18, whose episodes it would not read (ADR-0326 §5:3).
CONTINUING_RECORD_FORMAT: Final[int] = 18

#: The memory store's label for ADR-0352 §6:5's episode record. It advances to 19:
#: ``EpisodeProcessingRecord`` gains ``taken_over_by``, a field of a ``core`` model the
#: store serialises in every episode (ADR-0326 §2:3). A file at 18 is upgraded in place
#: by the label alone, since a record written at 18 validates unchanged, and an older
#: build, which serves 12 to 18, refuses a file at 19, whose episodes it would not read
#: (ADR-0326 §5:3).
TAKEN_OVER_RECORD_FORMAT: Final[int] = 19

#: The memory store's label for ADR-0351 §9's episode record. It advances to 20:
#: ``RecordedChannelTrigger`` loses ``origin`` and gains ``parties``, and each
#: ``RecordedInputMessage`` gains ``party``, the shape of a value the store serialises
#: in every episode (ADR-0326 §2:3). A file at 19 is upgraded in
#: place: each episode with a processing record is rewritten by
#: :func:`~ai_assistant.memory._parties_upgrade.parties_episode`, its parties those its
#: kind declares, or ``None`` where the rule does not cover it (§9:2, §9:3), and an older
#: build, which serves 12 to 19, refuses a file at 20, whose episodes it would not read
#: (ADR-0326 §5:3).
PARTIES_RECORD_FORMAT: Final[int] = 20

#: The memory store's label for ADR-0353 §9's episode record. It advances to 21 (§15:3):
#: each ``ActivationUnderstanding`` loses its ground, references, relationships,
#: unresolved matters and answer pointers and gains ``unclear``,
#: ``UnderstandingReferent.kind`` gains ``running``, and ``RecallCue``
#: gains ``understood_gap``, the shape of values and members of closed enumerations
#: the store serialises in every episode (ADR-0326 §2:3). A file at 20 is upgraded in
#: place: each episode whose versions hold a retired field is rewritten by
#: :func:`~ai_assistant.memory._understanding_upgrade.understood_episode`, the
#: referents of its references and relationships carried into its
#: ``meaning_referents`` and the rest dropped by the owner's ruling (§9:6, ADR-0326
#: §4:4), and an older build, which serves 12 to 20, refuses a file at 21, whose
#: episodes it would not read (ADR-0326 §5:3).
UNDERSTOOD_RECORD_FORMAT: Final[int] = 21

#: The memory store's own label, the one this build writes. It advances to 22 for
#: ADR-0356 §13's episode record (§13:5): ``EpisodeProcessingRecord`` gains
#: ``call_records`` and its ``schema_version`` advances to 12, and ``SupportPart`` gains
#: the part ``message_call``: a field and a version of a ``core`` model the store
#: serialises in every episode, and a member of a closed enumeration a stored memory
#: names (ADR-0326 §2:3). A file at 21 is upgraded in place: each episode with a
#: processing record is rewritten by
#: :func:`~ai_assistant.memory._calls_upgrade.called_episode`, carried whole at the new
#: version with ``call_records`` empty (§13:5), and an older build, which serves 12 to
#: 21, refuses a file at 22, whose episodes it would not read (ADR-0326 §5:3).
MEMORY_RECORD_FORMAT: Final[int] = 22

#: The memory store's labels a build opens: its own, and each it upgrades from, in
#: order (ADR-0326 §4:5, §5:1).
MEMORY_RECORD_FORMATS: Final[frozenset[int]] = frozenset(
    {
        EPISODE_RECORD_FORMAT,
        MEMORIES_RECORD_FORMAT,
        JOINED_RECORD_FORMAT,
        PINNED_RECORD_FORMAT,
        PLACED_RECORD_FORMAT,
        SCHEDULED_RECORD_FORMAT,
        CONTINUING_RECORD_FORMAT,
        TAKEN_OVER_RECORD_FORMAT,
        PARTIES_RECORD_FORMAT,
        UNDERSTOOD_RECORD_FORMAT,
        MEMORY_RECORD_FORMAT,
    }
)

#: The conversation store's own label, the one this build writes, in the
#: ``episode_record_format`` table of ``conversations.db`` alone. It held
#: :data:`EPISODE_RECORD_FORMAT` until ADR-0350 §12:9 advanced it to 13 for the
#: ``effect_id`` column of its ``messages`` table, the effect record an assistant's
#: message was claimed under (ADR-0326 §2:3). A file at 12 is upgraded in place by
#: adding the column, every message it holds carried with no effect id (§4:1, §4:4), and
#: an older build, which serves 12 alone, refuses a file at 13 (ADR-0326 §5:3).
CONVERSATION_RECORD_FORMAT: Final[int] = 13

#: The conversation store's labels a build opens: its own, and the one it upgrades
#: from (ADR-0326 §4:5, §5:1).
CONVERSATION_RECORD_FORMATS: Final[frozenset[int]] = frozenset(
    {EPISODE_RECORD_FORMAT, CONVERSATION_RECORD_FORMAT}
)


def stored_format(
    conn: sqlite3.Connection,
    *,
    allow_empty: bool = False,
    accepted: frozenset[int] = frozenset({EPISODE_RECORD_FORMAT}),
) -> int | None:
    """The format marker a store holds, refusing one this build does not open.

    Args:
        conn: An open connection to the store.
        allow_empty: Whether a store holding no table at all is admitted, as a fresh
            one about to be created.
        accepted: The markers this build opens.

    Returns:
        The marker, or ``None`` for an admitted empty store.

    Raises:
        MemoryStoreError: If the marker cannot be read.
        IncompatibleStateError: If the store holds no marker, or one not accepted.
    """
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not tables and allow_empty:
            return None
        if "episode_record_format" in tables:
            rows = conn.execute("SELECT version FROM episode_record_format").fetchall()
            if len(rows) == 1 and rows[0][0] in accepted:
                return int(rows[0][0])
    except sqlite3.Error as exc:
        msg = "cannot read episode record format"
        raise MemoryStoreError(msg) from exc
    raise IncompatibleStateError(
        "memory store requires a fresh M39 data directory",
        expected=f"episode record format in {sorted(accepted)}",
        found="missing or unsupported episode record format",
        operator_action=("Stop the old hub and configure a new empty development data directory."),
    )


def check_memory_format(conn: sqlite3.Connection, *, allow_empty: bool = False) -> bool:
    """Refuse a memory store at any marker but this build's own (ADR-0328 §16:8).

    For a reader of ``memory.db`` that does not upgrade it — the re-embedding
    migration, which copies what the store holds and has no upgrade of its own. The
    store itself opens a file at any of :data:`MEMORY_RECORD_FORMATS`.

    Returns:
        Whether the current marker exists; ``False`` only for an admitted empty store.
    """
    found = stored_format(conn, allow_empty=allow_empty, accepted=frozenset({MEMORY_RECORD_FORMAT}))
    return found is not None


def inspect_existing(
    path: str, *, accepted: frozenset[int] = frozenset({EPISODE_RECORD_FORMAT})
) -> None:
    """Check existing files without allowing SQLite recovery to modify them.

    A read-only connection suffices for a clean rollback-mode database. Pending
    journals and WAL state are recovered only in an owner-only temporary copy;
    SQLite must not touch the rejected original or its shared-memory sidecar.
    The normal writable opener rechecks the marker inside its initialization
    transaction after this probe has admitted the recovered format.

    The marker is the whole test, for the conversation store as for the memory
    store: the conversation store's turn table and its column check are retired
    (ADR-0283 §6, §12), so there is no second shape to probe.

    ``accepted`` is the opener's own set of markers, so a file the opener would then
    refuse is refused here, before a writable open could recover its journal: the
    conversation store opens :data:`CONVERSATION_RECORD_FORMATS`, the memory store
    :data:`MEMORY_RECORD_FORMATS` (ADR-0328 §16:8, ADR-0350 §12:9, ADR-0326 §5).

    Args:
        path: The store's file, or ``":memory:"``.
        accepted: The markers the calling opener opens.
    """
    if path == ":memory:":
        return
    try:
        source = Path(path)
        if not source.exists():
            return
        source = source.resolve()
        sidecars = tuple(Path(f"{source}{suffix}") for suffix in ("-journal", "-wal", "-shm"))
        if _wal_header(source) or any(file.exists() or file.is_symlink() for file in sidecars):
            _inspect_copy(source, sidecars, accepted)
        else:
            with contextlib.closing(
                sqlite3.connect(
                    f"{source.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None
                )
            ) as conn:
                _inspect_connection(conn, accepted)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise MemoryStoreError("cannot inspect existing episode record format") from exc


def _wal_header(path: Path) -> bool:
    # A closed WAL database can have no sidecars. Even mode=ro may create them
    # on its next read, so route that header through the private copy as well.
    with path.open("rb") as stream:
        header = stream.read(20)
    return header.startswith(b"SQLite format 3\0") and b"\x02" in header[18:20]


def _inspect_connection(conn: sqlite3.Connection, accepted: frozenset[int]) -> None:
    # The calling opener's own markers, which it rechecks inside its initialization
    # transaction.
    stored_format(conn, allow_empty=True, accepted=accepted)


def _file_state(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _inspect_copy(source: Path, sidecars: tuple[Path, ...], accepted: frozenset[int]) -> None:
    files = (source, *sidecars)
    before = tuple(_file_state(file) for file in files)
    with tempfile.TemporaryDirectory(prefix="assistant-format-") as directory:
        copied = Path(directory) / source.name
        for file, state in zip(files, before, strict=True):
            if state is None or (file.is_symlink() and file != source):
                continue
            target = Path(directory) / file.name
            target.touch(mode=0o600, exist_ok=False)
            with file.open("rb") as reader, target.open("wb") as writer:
                shutil.copyfileobj(reader, writer)
        if before != tuple(_file_state(file) for file in files):
            raise MemoryStoreError("store changed during format inspection; retry opening it")
        journal = Path(f"{copied}-journal")
        if journal.exists():
            _refuse_super_journal(journal)
        with contextlib.closing(sqlite3.connect(copied, isolation_level=None)) as conn:
            _inspect_connection(conn, accepted)


def _refuse_super_journal(journal: Path) -> None:
    # A multi-database transaction can name a super-journal outside the copied
    # directory. Never let recovery of a probe follow and delete that original.
    # These stores do not use ATTACH; leave such external recovery to its owner.
    with journal.open("rb") as stream:
        trailer_size = 16
        if stream.seek(0, os.SEEK_END) < trailer_size:
            return
        stream.seek(-trailer_size, os.SEEK_END)
        trailer = stream.read(trailer_size)
    if trailer[-8:] == bytes.fromhex("d9d505f920a163d7") and int.from_bytes(trailer[:4], "big"):
        raise MemoryStoreError("format inspection requires recovery of a multi-database journal")

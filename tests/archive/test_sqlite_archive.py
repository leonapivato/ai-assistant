"""The durable transcript archive (ADR-0225 §10), through both suites and on disk.

One class runs ``SqliteTranscriptArchive`` through **both** conformance suites,
which is §10's "one concrete satisfies both structurally" as a test rather than an
assertion: the composition root then hands each collaborator the seam it is entitled
to, and the two `mypy`-level narrowings do the rest.

The cases below the bindings are the ones only a durable store can answer: what the
figures are measured over, what files the archive owns, and the owner-only mode it
holds them at (§6, §9).
"""

from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from transcript_archive_contracts import (
    DAY,
    NOW,
    TranscriptArchiveContract,
    TranscriptArchiveWriterContract,
    entry,
)

from ai_assistant.archive import SqliteTranscriptArchive
from ai_assistant.archive.sqlite_store import folded
from ai_assistant.core.errors import TranscriptArchiveError

if TYPE_CHECKING:
    from ai_assistant.core.protocols import TranscriptArchive, TranscriptArchiveWriter
    from ai_assistant.core.types import TranscriptEntry

pytestmark = pytest.mark.integration

#: The sidecars ADR-0225 §6 closes the file set with, and §9 protects.
SIDECARS = ("-journal", "-wal", "-shm")

#: What the symlink case plants, and expects to find untouched afterwards.
_NOT_OURS = "held by something else"

#: A span the failure cases look for in what a refusal says. Distinctive, so a
#: match anywhere is this entry's text and not an incidental word.
_PRIVATE = "PRIVATE-TRANSCRIPT-MARKER"


def _at_now(**kwargs: Any) -> SqliteTranscriptArchive:
    """An archive reading the retention predicate against the suites' fixed instant."""
    return SqliteTranscriptArchive(now=lambda: NOW, **kwargs)


def _mode_of(path: Path) -> int:
    """The permission bits of ``path``, read synchronously and in one place."""
    return stat.S_IMODE(path.stat().st_mode)


class TestSqliteTranscriptArchiveContract(
    TranscriptArchiveWriterContract, TranscriptArchiveContract
):
    """Runs the durable archive through **both** of ADR-0225 §10's suites.

    The subject is one object satisfying both Protocols, which is what the
    composition root relies on when it hands the narrow face to capture and the wide
    face to the engine. Running the two suites against it is how "one concrete
    implements both" stops being a claim.

    Every subject here is file-backed rather than ``":memory:"``, because two of the
    obligations — what ``stored_bytes`` counts, and what a reopen restricts — are
    about files and would be vacuous otherwise.
    """

    @pytest.fixture
    def writer(self, tmp_path: Path) -> TranscriptArchiveWriter:
        return _at_now(path=tmp_path / "transcripts.db")

    @pytest.fixture
    def archive(self, tmp_path: Path) -> TranscriptArchive:
        return _at_now(path=tmp_path / "transcripts.db")

    async def held(self, writer: TranscriptArchiveWriter) -> dict[str, TranscriptEntry]:
        assert isinstance(writer, SqliteTranscriptArchive)
        return {one.address: one for one in await writer.entries(limit=2**16)}

    async def store(self, archive: TranscriptArchive, *entries: TranscriptEntry) -> None:
        assert isinstance(archive, SqliteTranscriptArchive)
        for one in entries:
            await archive.append(one)

    def failing_writer(self) -> TranscriptArchiveWriter:
        return self._closed()

    def failing_archive(self) -> TranscriptArchive:
        return self._closed()

    @staticmethod
    def _closed() -> SqliteTranscriptArchive:
        """An archive whose connection is shut, which is this backend's own fault.

        The implementation's natural failure rather than an injected exception: every
        statement raises ``sqlite3.ProgrammingError``, which the transaction helper
        translates. A monkeypatched method would be evidence about the stand-in.
        """
        archive = _at_now(path=":memory:")
        archive.close()
        return archive

    def reopened(
        self, archive: TranscriptArchive, retention: timedelta | None
    ) -> TranscriptArchive:
        assert isinstance(archive, SqliteTranscriptArchive)
        return SqliteTranscriptArchive(
            path=archive._path,  # the same file, which is the point
            retention=retention,
            now=lambda: NOW,
        )


# --- what survives a restart (§3) -------------------------------------------


async def test_an_address_still_resolves_after_a_reopen(tmp_path: Path) -> None:
    """ADR-0225 §3: an address is stable, and the archive is what outlives the horizon.

    The whole reason the store is durable: a transcript that vanished on restart
    would make the archive a cache, and the decision is about a record that is still
    there in three years.
    """
    path = tmp_path / "transcripts.db"
    first = _at_now(path=path)
    try:
        await first.append(entry(asked="Ravensworth"))
    finally:
        first.close()

    second = _at_now(path=path)
    try:
        held = await second.entry("c1:1")
        assert held is not None
        assert held.asked == "Ravensworth"
    finally:
        second.close()


# --- the size report, measured against the files (§6, §13 item 17) ----------


async def test_stored_bytes_measures_the_files_and_not_the_entry_lengths(
    tmp_path: Path,
) -> None:
    """ADR-0225 §6: every byte the archive's files occupy on disk, right now.

    Asserted **against the files** rather than against a formula, which is what
    §13 item 17 asks for: an accounting that summed entry lengths, or read the main
    database file alone, fails here. The figure is compared to the sum over the
    closed set §6 fixes, so a store that grew a sixth file would fail this too.
    """
    path = tmp_path / "transcripts.db"
    archive = _at_now(path=path)
    try:
        for ordinal in range(1, 40):
            await archive.append(
                entry(f"c1:{ordinal}", ordinal=ordinal, asked="x" * 3000, replied="y" * 3000)
            )

        reported = (await archive.size()).stored_bytes
        # The blocking `stat` calls are on a synchronous helper for the reason
        # `_mode_of` is: this is a test's own filesystem read, not an I/O path the
        # loop can be starved by.
        on_disk = _bytes_on_disk(path)

        assert reported == on_disk
        assert reported > 39 * 6000, "the sum must include the pages the text is stored in"
    finally:
        archive.close()


def _bytes_on_disk(path: Path) -> int:
    """The database and every sidecar beside it, summed."""
    total = path.stat().st_size
    for suffix in SIDECARS:
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            total += sidecar.stat().st_size
    return total


async def test_an_in_memory_archive_reports_what_its_entries_occupy() -> None:
    """ADR-0225 §6: an implementation holding no files reports by the same standard.

    A ``stored_bytes`` of zero over an archive holding entries is not a conforming
    answer for *any* implementation, and an ephemeral store is the one that would
    most naturally give it.
    """
    archive = _at_now(path=":memory:")
    try:
        await archive.append(entry())

        assert (await archive.size()).stored_bytes > 0
    finally:
        archive.close()


# --- the closed file set (§6, §9, §13 item 18) ------------------------------


async def test_the_archive_owns_its_database_and_nothing_but_the_named_sidecars(
    tmp_path: Path,
) -> None:
    """ADR-0225 §6's closed set, after a sequence of every operation and a reopen.

    The assertion that pins the set: an implementation writing a separate on-disk
    index artifact, a spill file or a second database fails here. It is what makes
    §6's accounting and §9's protection range over the same files by construction —
    a byte the size report counts is a byte the ``0600`` protects, with no third
    place for either to reach past the other.
    """
    path = tmp_path / "transcripts.db"
    archive = _at_now(path=path)
    try:
        for ordinal in range(1, 30):
            await archive.append(entry(f"c1:{ordinal}", ordinal=ordinal, asked="x" * 4000))
        await archive.search("x", limit=5)
        await archive.entries(limit=5)
        await archive.conversation("c1", limit=5)
        await archive.discard("c1:1")
        await archive.discard_conversation("c1")
        await archive.size()
    finally:
        archive.close()
    reopened = _at_now(path=path)
    try:
        await reopened.append(entry())
    finally:
        reopened.close()

    permitted = {"transcripts.db", *(f"transcripts.db{suffix}" for suffix in SIDECARS)}
    assert _names_in(tmp_path) <= permitted


# --- owner-only, on every open (§9, gate 4) ---------------------------------


async def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4, which ADR-0225 §9 holds this store to unchanged."""
    path = tmp_path / "transcripts.db"
    archive = _at_now(path=path)
    try:
        assert _mode_of(path) == 0o600
    finally:
        archive.close()


def test_a_sidecar_that_was_already_there_is_restricted_on_reopen(tmp_path: Path) -> None:
    """ADR-0225 §9: asserted on **every** open rather than at creation alone.

    SQLite copies the database file's mode onto a sidecar **it creates**, which is
    what makes restricting the file before the first statement enough for those. It
    does nothing for one already on disk: a ``-wal``/``-shm`` a previous process left
    group- or world-readable keeps its own mode across a reopen and then takes Tier 1
    pages — and here those pages are the transcript itself.
    """
    path = tmp_path / "transcripts.db"
    _at_now(path=path).close()
    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    _at_now(path=path).close()

    assert [_mode_of(each) for each in sidecars] == [0o600, 0o600]


def test_a_sidecar_that_cannot_be_restricted_fails_the_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0225 §9: it is a file about to be written through, so the failure propagates.

    Not tolerated the way a *missing* sidecar is: absence is the ordinary case for a
    cleanly closed database, but a present sidecar this process cannot narrow is a
    Tier 1 file the next statement may put transcript pages into. Provoked by making
    ``chmod`` refuse for that one name, because a file the test user cannot chmod is
    not arrangeable inside a temporary directory they own.
    """
    path = tmp_path / "transcripts.db"
    _at_now(path=path).close()
    journal = Path(f"{path}-journal")
    journal.touch()
    real_chmod = Path.chmod

    def refusing(self: Path, mode: int, **kwargs: Any) -> None:
        if self.name.endswith("-journal"):
            msg = "not permitted"
            raise PermissionError(msg)
        real_chmod(self, mode, **kwargs)

    monkeypatch.setattr(Path, "chmod", refusing)

    with pytest.raises(TranscriptArchiveError):
        _at_now(path=path)


@pytest.mark.parametrize("suffix", SIDECARS)
def test_a_symlink_under_a_sidecar_name_is_never_followed(tmp_path: Path, suffix: str) -> None:
    """The restriction narrows this store's own files, and only those (#490).

    ``chmod`` follows symlinks and ``os.chmod(follow_symlinks=False)`` is unsupported
    on Linux, so a link planted under a sidecar's name would otherwise make the open
    silently set ``0600`` on a file holding none of this store's data. Both the mode
    and the contents are asserted, because "left alone" is the whole claim.
    """
    path = tmp_path / "transcripts.db"
    unrelated = tmp_path / "not-ours.txt"
    unrelated.write_text(_NOT_OURS)
    unrelated.chmod(0o644)
    Path(f"{path}{suffix}").symlink_to(unrelated)

    _at_now(path=path).close()

    assert _mode_of(unrelated) == 0o644
    assert unrelated.read_text() == _NOT_OURS


# --- the open's own failures ------------------------------------------------


def test_an_unopenable_path_fails_as_this_seams_own_error(tmp_path: Path) -> None:
    """ADR-0225 §10's single archive error class, from the constructor too.

    A backend fault leaking out as ``sqlite3.OperationalError`` would make every
    caller match on a class the seam does not document.
    """
    with pytest.raises(TranscriptArchiveError):
        SqliteTranscriptArchive(path=tmp_path / "no-such-directory" / "transcripts.db")


def test_a_second_writer_of_the_same_address_is_refused_across_connections(
    tmp_path: Path,
) -> None:
    """ADR-0225 §2's loud failure is the database's, not this process's memory.

    Written directly through a second connection so the collision cannot be answered
    from anything this object holds: the address is the primary key, so the refusal
    survives a restart and a second process.
    """
    path = tmp_path / "transcripts.db"
    archive = _at_now(path=path)
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "INSERT INTO entries(address, conversation_id, ordinal, occurred_at_us, "
                "asked, replied, asked_folded, replied_folded, disposition) "
                "VALUES ('c1:1', 'c1', 1, 0, NULL, NULL, NULL, NULL, 'no_action_needed')"
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(TranscriptArchiveError):
            _run(archive.append(entry()))
    finally:
        archive.close()


def _run(coro: Any) -> Any:
    """Drive one coroutine to completion from a synchronous case."""
    import asyncio  # noqa: PLC0415 — one synchronous case needs a loop of its own

    return asyncio.run(coro)


# --- the retention predicate, over a store that has not been touched --------


async def test_a_hidden_entry_is_hidden_with_no_write_and_no_sweep(tmp_path: Path) -> None:
    """ADR-0225 §6, asserted over the durable store's own file (§13 item 8).

    The suite asserts this over both implementations; this case is the durable one's
    strongest form — the file is closed and reopened under a shorter horizon, and
    nothing has written to it or swept it in between, so an implementation that hid
    entries only when something ran cannot pass.
    """
    path = tmp_path / "transcripts.db"
    first = _at_now(path=path)
    try:
        await first.append(entry(at=NOW - 30 * DAY))
    finally:
        first.close()

    aged = SqliteTranscriptArchive(path=path, retention=DAY, now=lambda: NOW)
    try:
        assert await aged.entries() == []
        assert (await aged.size()).entries == 0
        assert (await aged.size()).stored_bytes > 0
        assert await aged.discard("c1:1") is True, "the destroys reach what the reads hide"
    finally:
        aged.close()


def _names_in(directory: Path) -> set[str]:
    """Every name in ``directory``, read synchronously and in one place.

    A sync helper because the case above is ``async def`` and ruff's ASYNC240
    (rightly) objects to a blocking ``pathlib`` call on an async path. The blocking
    read is real; keeping it here makes that visible, which is the shape
    ``tests/memory/test_sqlite_conversation_store.py`` established.
    """
    return {each.name for each in directory.iterdir()}


# --- this implementation's own choices, where ADR-0225 leaves one ----------


async def test_the_users_half_is_this_stores_choice_on_a_two_sided_match(
    tmp_path: Path,
) -> None:
    """ADR-0225 §7 leaves the window to the lane; this records what this lane picked.

    Deliberately **not** in the shared suite: §7 says "which window of the entry the
    excerpt is taken from is the implementing lane's", and where both halves match
    either is matching text — so a shared assertion would narrow the seam past what
    the ADR ratified, which takes an ADR rather than a test. The suite asserts what
    §7 does fix (one half, bounded, never both run together); this asserts what this
    store does with the freedom left over.

    ``asked`` wins, so a two-sided hit reads as what the *user* said.
    """
    archive = _at_now(path=tmp_path / "transcripts.db")
    try:
        await archive.append(entry(asked="Ravensworth asked", replied="Ravensworth said"))

        hit = (await archive.search("Ravensworth"))[0]

        assert hit.excerpt == "Ravensworth asked"
    finally:
        archive.close()


# --- the horizon is total over every clock this seam admits (§6) -----------


@pytest.mark.parametrize(
    "retention", [timedelta(days=4), timedelta.max], ids=["past-the-calendar", "unrepresentable"]
)
async def test_a_horizon_before_the_calendar_answers_rather_than_raising(
    tmp_path: Path, retention: timedelta
) -> None:
    """A reading near ``datetime.min`` must not take all four reads down with it.

    ``checked_clock`` refuses a *naive* or *indeterminate* reading, not an early one,
    so ``datetime.min + 1 day`` reaches this store — and subtracting a retention from
    it raises ``OverflowError`` out of ``datetime`` rather than anything this seam
    documents. ``timedelta.max`` is the other end of the same edge: it puts the floor
    below the signed 64-bit range a SQLite bind takes, whatever the reading.

    Both answer the same way, and it is the right answer: a horizon no stored instant
    can precede hides nothing.
    """
    early = datetime.min.replace(tzinfo=UTC) + timedelta(days=1)
    archive = SqliteTranscriptArchive(
        path=tmp_path / "transcripts.db", retention=retention, now=lambda: early
    )
    try:
        await archive.append(entry(at=early, asked="Ravensworth"))

        assert [one.address for one in await archive.entries()] == ["c1:1"]
        assert [one.address for one in await archive.conversation("c1")] == ["c1:1"]
        assert await archive.entry("c1:1") is not None
        assert [hit.address for hit in await archive.search("Ravensworth")] == ["c1:1"]
        assert (await archive.size()).entries == 1
    finally:
        archive.close()


@pytest.mark.parametrize(
    "retention",
    [timedelta(0), timedelta(days=-1), "P30D", 30, True],
    ids=["zero", "negative", "a-string", "an-int", "a-flag"],
)
def test_a_retention_that_is_not_a_positive_duration_is_refused(
    tmp_path: Path, retention: object
) -> None:
    """The constructor's own guard, on ADR-0225 §6's shape (``timedelta | None``).

    ``core.config.Settings`` refuses these at load with ``gt=timedelta(0)``, and this
    is the same refusal one layer down — for the reason ``SqliteConversationStore``
    states for its own: the class is public, anyone may construct one directly, and a
    guard that only fires when a caller remembered to ask is not a guard.

    **Zero and negative are not the same fault and both matter.** A zero horizon
    hides every entry the instant it is written; a negative one puts the floor
    *after* the reading and hides entries that are plainly live. Neither is a value
    §6 admits, and both would look like a working archive that had quietly stopped
    answering. ``True`` is here because ``bool`` is an ``int`` subclass and the
    non-duration arm is what catches it.
    """
    with pytest.raises(ValueError, match="retention"):
        SqliteTranscriptArchive(path=tmp_path / "transcripts.db", retention=retention)  # type: ignore[arg-type]


def test_keeping_forever_is_admitted(tmp_path: Path) -> None:
    """``None`` is §6's default and its whole spelling for "keep forever"."""
    SqliteTranscriptArchive(path=tmp_path / "transcripts.db", retention=None).close()


# --- a row this store did not write (§10) -----------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    # `2**63` is deliberately absent: a SQLite INTEGER tops out one below it, so an
    # ordinal past `TranscriptEntry`'s ceiling cannot reach a row at all — the driver
    # refuses the bind. The ceiling is asserted where it *is* reachable, on the model
    # itself (`tests/core/test_transcript_types.py`).
    [("disposition", "not-a-member"), ("ordinal", 0), ("occurred_at_us", -(2**62))],
    ids=["a-foreign-disposition", "an-ordinal-below-the-floor", "an-instant-off-the-calendar"],
)
async def test_a_row_this_store_cannot_rebuild_raises_this_seams_own_error(
    tmp_path: Path, column: str, value: object
) -> None:
    """ADR-0225 §10's single archive error class, over the one thing SQL cannot catch.

    A read reaches the model conversion only after the SQL succeeded, so a row some
    other writer put in the reserved namespace — or a damaged one — escapes the
    transaction's own translation. A raw ``ValidationError`` or ``OverflowError`` out
    of a read would leave every caller matching on a class the contract does not
    document.

    **Raised over rather than skipped**, on ADR-0119 §3's ground for a trace row that
    cannot be hydrated: dropping it silently would hide from the user a transcript
    that is on their disk.
    """
    path = tmp_path / "transcripts.db"
    archive = _at_now(path=path)
    try:
        await archive.append(entry(asked=_PRIVATE, replied=_PRIVATE))
        _damage(path, column, value)

        for read in (archive.entry("c1:1"), archive.conversation("c1"), archive.entries()):
            with pytest.raises(TranscriptArchiveError) as refused:
                await read
            assert "c1:1" in str(refused.value), "the address is what a failure names"
            assert _PRIVATE not in str(refused.value), "and never the entry's text"
            assert _PRIVATE not in repr(refused.value.__cause__), "nor anything chained to it"
    finally:
        archive.close()


async def test_a_row_whose_text_the_hit_model_refuses_raises_the_same_way(
    tmp_path: Path,
) -> None:
    """The search's own conversion, held to §10 exactly as the three whole reads are.

    A hit is built from the matching half, so a row carrying text no ``EncodableText``
    admits refuses there rather than at ``TranscriptEntry`` — a different construction
    on a different path, and one an implementation could plausibly guard in only one
    of the two places.
    """
    path = tmp_path / "transcripts.db"
    archive = _at_now(path=path)
    try:
        await archive.append(entry(asked=_PRIVATE, replied=None))
        # Written through a second connection so the value bypasses this store's own
        # `append`, which is the only way an unencodable half reaches a row at all.
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA encoding")
            conn.execute(
                "UPDATE entries SET asked = CAST(? AS TEXT), asked_folded = ?",
                (b"\xed\xa0\x80", folded(_PRIVATE)),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(TranscriptArchiveError) as refused:
            await archive.search(_PRIVATE)

        assert _PRIVATE not in str(refused.value)
    finally:
        archive.close()


def _damage(path: Path, column: str, value: object) -> None:
    """Write ``value`` into ``column`` for every row, through a second connection.

    Through raw SQL because that is the only way to arrange the case: this store's
    own ``append`` validates, so a row it wrote can never be one it cannot read back.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"UPDATE entries SET {column} = ?", (value,))  # noqa: S608 — a fixed set
        conn.commit()
    finally:
        conn.close()

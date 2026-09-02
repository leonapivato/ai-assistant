"""Canonical fakes for ADR-0225's two transcript-archive seams.

Two fakes rather than one, because ADR-0225 §10 splits the contract by **which
object performs which act**: :class:`FakeTranscriptArchiveWriter` is what capture
is handed — it can append and it cannot read — and :class:`FakeTranscriptArchive`
is what ``AssistantEngine`` is handed, which can read and cannot append. A test
holding the writer therefore cannot reach a read *through the fake either*, which
is the arrangement §4's turn-path fence exists to make true in production.

**Neither fake reaches** ``ai_assistant.archive``, which ``lint-imports`` enforces:
they stand in *for* the durable store and must not import it (the rule the trace
and secret-store fakes already live under).

**Every predicate here is the durable store's, spelled again rather than shared.**
``ai_assistant.testing`` may not import a subsystem (golden rule 1) and ADR-0225
adds no helper to ``core``, so the folding, the excerpt bound, the ordering, the
retention floor and the paging refusals are duplicated — and the shared conformance
suite is what keeps the two spellings answering the same way, over the cases §7 and
§13 name as the ones that separate implementations.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import TranscriptArchiveError
from ai_assistant.core.types import (
    TRANSCRIPT_EXCERPT_BYTES,
    TranscriptArchiveSize,
    TranscriptEntry,
    TranscriptHit,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.clock import Clock

#: One past the largest value a paging argument may take (ADR-0073 §2's range),
#: refused here so the fake and the durable store agree at the edge as well as in
#: the middle.
_PAGE_BOUND = 2**63


def _utcnow() -> datetime:
    return datetime.now(UTC)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: One past the largest microsecond key a horizon may be clamped to, mirroring the
#: durable store's bind range so the two agree at the edge as well as in the middle.
_MICROS_BOUND = 2**63


def _to_micros(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch, by integer arithmetic."""
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _span_micros(span: timedelta) -> int:
    """Return ``span`` as whole microseconds."""
    return (span.days * 86_400 + span.seconds) * 1_000_000 + span.microseconds


def _folded(text: str) -> str:
    """ADR-0225 §7's predicate form: NFC, then **full** Unicode case folding."""
    return unicodedata.normalize("NFC", text).casefold()


def _excerpt_of(text: str) -> tuple[str, bool]:
    """A window of at most :data:`TRANSCRIPT_EXCERPT_BYTES` bytes, cut on a codepoint."""
    encoded = text.encode("utf-8")
    if len(encoded) <= TRANSCRIPT_EXCERPT_BYTES:
        return text, False
    return encoded[:TRANSCRIPT_EXCERPT_BYTES].decode("utf-8", errors="ignore"), True


def _check_page(limit: int, offset: int) -> None:
    """Refuse a ``limit`` at or below zero, and a negative ``offset`` (ADR-0225 §10).

    Raises:
        ValueError: If ``limit`` is outside ``[1, 2**63)`` or ``offset`` outside
            ``[0, 2**63)``.
    """
    if not 1 <= limit < _PAGE_BOUND:
        msg = f"limit must be in [1, 2**63), got {limit}"
        raise ValueError(msg)
    if not 0 <= offset < _PAGE_BOUND:
        msg = f"offset must be in [0, 2**63), got {offset}"
        raise ValueError(msg)


def _check_named(value: str, *, name: str) -> str:
    """Refuse a blank scope or query, returning it **unstripped** (ADR-0225 §10).

    Raises:
        ValueError: If it is blank or whitespace-only.
    """
    if not value.strip():
        msg = f"{name} must not be blank"
        raise ValueError(msg)
    return value


class _Entries:
    """The rows both fakes hold, so two seams can share one archive.

    Insertion-ordered, keyed by address, and the value is a *revalidated* copy —
    the detached snapshot the durable store gets for free by storing JSON, which a
    dict of the caller's own objects would not.
    """

    def __init__(self, entries: Iterable[TranscriptEntry] = ()) -> None:
        self._rows: dict[str, TranscriptEntry] = {}
        for entry in entries:
            self.put(entry)

    def put(self, entry: TranscriptEntry) -> None:
        """Store a detached copy of ``entry``, replacing any at its address."""
        self._rows[entry.address] = TranscriptEntry.model_validate(entry.model_dump())

    def held(self) -> dict[str, TranscriptEntry]:
        """Every entry held, keyed by address — a snapshot the caller may keep."""
        return dict(self._rows)

    def contains(self, address: str) -> bool:
        return address in self._rows

    def drop(self, address: str) -> bool:
        return self._rows.pop(address, None) is not None

    def drop_conversation(self, conversation_id: str) -> int:
        doomed = [key for key, row in self._rows.items() if row.conversation_id == conversation_id]
        for key in doomed:
            del self._rows[key]
        return len(doomed)

    def stored_bytes(self) -> int:
        """What the entries occupy in what holds them (ADR-0225 §6).

        Not zero over a populated archive — which §6 rules is not a conforming
        answer for any implementation, "and a fake that gave one would make the
        conformance case vacuous". The retention predicate is deliberately **not**
        applied: ``stored_bytes`` measures what is held, hidden entries included.
        """
        return sum(len(row.model_dump_json().encode("utf-8")) for row in self._rows.values())


class FakeTranscriptArchiveWriter:
    """A canonical :class:`~ai_assistant.core.protocols.TranscriptArchiveWriter`.

    What capture is handed (ADR-0225 §10): it can append and destroy, and it cannot
    read back through the Protocol. :attr:`recorded` is the *test's* window on what
    was appended, not a seam the code under test could reach.
    """

    def __init__(self, entries: Iterable[TranscriptEntry] = ()) -> None:
        """Create a writer over ``entries``, with no scripted failure.

        Args:
            entries: The history to start from.
        """
        self._entries = _Entries(entries)
        self._failure: Exception | None = None

    @property
    def recorded(self) -> dict[str, TranscriptEntry]:
        """Every entry this writer holds, keyed by address."""
        return self._entries.held()

    def fail(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later call (ADR-0225 §10).

        Args:
            error: The underlying fault, preserved as ``__cause__``. ``None``
                scripts a generic one.
        """
        self._failure = error if error is not None else RuntimeError("the archive is unavailable")

    def _refuse(self, what: str) -> None:
        if self._failure is not None:
            msg = f"failed to {what}"
            raise TranscriptArchiveError(msg) from self._failure

    async def append(self, entry: TranscriptEntry) -> None:
        """Write ``entry`` at its own address (ADR-0225 §1, §2, §3).

        Args:
            entry: The turn to record, whole.

        Raises:
            TranscriptArchiveError: If a fault is scripted, or an entry already
                stands at ``entry.address`` — the fault §2 fails loudly rather than
                resolving by overwriting, merging or retrying.
        """
        self._refuse("append a transcript entry")
        if self._entries.contains(entry.address):
            msg = f"a transcript entry already stands at address {entry.address!r}"
            raise TranscriptArchiveError(msg)
        self._entries.put(entry)

    async def discard(self, address: str) -> bool:
        """Destroy the entry at ``address``; report whether one was there (§5).

        Args:
            address: The entry's address, taken as opaque.

        Returns:
            Whether an entry was destroyed.

        Raises:
            ValueError: If ``address`` is blank or whitespace-only.
            TranscriptArchiveError: If a fault is scripted.
        """
        named = _check_named(address, name="address")
        self._refuse("discard a transcript entry")
        return self._entries.drop(named)

    async def discard_conversation(self, conversation_id: str) -> int:
        """Destroy every entry grouped under ``conversation_id`` (§5).

        Args:
            conversation_id: The conversation whose entries are destroyed.

        Returns:
            How many entries were destroyed; zero is the conforming answer for a
            conversation with none.

        Raises:
            ValueError: If ``conversation_id`` is blank or whitespace-only.
            TranscriptArchiveError: If a fault is scripted.
        """
        named = _check_named(conversation_id, name="conversation_id")
        self._refuse("discard a conversation's transcript")
        return self._entries.drop_conversation(named)


class FakeTranscriptArchive:
    """A canonical :class:`~ai_assistant.core.protocols.TranscriptArchive`.

    What ``AssistantEngine`` is handed (ADR-0225 §10): the four reads, the two
    destroys and the size report — and **no append**, because §1 reserves writing to
    capture and a wide face that could write would defeat the split. :meth:`hold` is
    the test's way to arrange a history, since nothing on this seam can create one.
    """

    def __init__(
        self,
        entries: Iterable[TranscriptEntry] = (),
        *,
        retention: timedelta | None = None,
        now: Clock = _utcnow,
    ) -> None:
        """Create an archive holding ``entries``.

        Args:
            entries: The history to start from.
            retention: How long an entry stays readable, or ``None`` for "keep
                forever" (ADR-0225 §6's default). Enforced at the read.
            now: Clock the retention predicate is evaluated against.
        """
        self._entries = _Entries(entries)
        self._retention = retention
        self._clock = checked_clock(now, owner="FakeTranscriptArchive")
        self._failure: Exception | None = None

    @property
    def recorded(self) -> dict[str, TranscriptEntry]:
        """Every entry this archive holds, keyed by address, retention ignored."""
        return self._entries.held()

    def hold(self, *entries: TranscriptEntry) -> None:
        """Arrange a history directly, bypassing the seam that has no append.

        Args:
            *entries: What to hold, in the order given.
        """
        for entry in entries:
            self._entries.put(entry)

    def reopened(self, retention: timedelta | None) -> FakeTranscriptArchive:
        """A second archive over **the same entries**, with a different retention.

        The fake's counterpart to reopening the durable store over the same file,
        and what lets the shared suite assert ADR-0225 §6's read-time enforcement:
        nothing is written, nothing is swept, the retention changes, and the reads
        answer differently on the very next call.

        Args:
            retention: The horizon the new archive reads against.

        Returns:
            The second archive.
        """
        twin = FakeTranscriptArchive(retention=retention, now=self._clock)
        twin._entries = self._entries  # one storage, two views, by design
        twin._failure = self._failure  # the scripted fault travels with it
        return twin

    def writer(self) -> FakeTranscriptArchiveWriter:
        """The **narrow** view of this archive's own entries (ADR-0225 §10).

        One archive, two seams — which is the arrangement the composition root
        performs in production, where one concrete satisfies both Protocols and each
        collaborator is handed the face it is entitled to. A test that wired two
        unrelated fakes would be testing a composition nothing builds: capture would
        write into one store and ``forget`` would destroy from another, and every
        cascade case would pass vacuously.

        The scripted fault does **not** travel: a case arming one seam is usually
        asking what the *other* still does, and sharing it would make that
        unaskable. Each view has its own :meth:`fail`.

        Returns:
            A writer over the same entries.
        """
        narrow = FakeTranscriptArchiveWriter()
        narrow._entries = self._entries  # one storage, two views, by design
        return narrow

    def fail(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later call.

        Args:
            error: The underlying fault, preserved as ``__cause__``. ``None``
                scripts a generic one.
        """
        self._failure = error if error is not None else RuntimeError("the archive is unavailable")

    def _refuse(self, what: str) -> None:
        if self._failure is not None:
            msg = f"failed to {what}"
            raise TranscriptArchiveError(msg) from self._failure

    def _live(self) -> list[TranscriptEntry]:
        """Every entry a read may return, retention applied (ADR-0225 §6).

        The predicate binds **before** the ordering and before any page is cut, so a
        hidden entry consumes no slot in a ``limit`` and shifts no ``offset``.

        Raises:
            TranscriptArchiveError: If the clock reading is non-conforming.
        """
        rows = list(self._entries.held().values())
        if self._retention is None:
            return rows
        try:
            reading = self._clock()
        except ClockReadingError as exc:
            raise TranscriptArchiveError(str(exc)) from exc
        # In microseconds rather than as `reading - self._retention`, for the durable
        # store's reason and to the same edge: `datetime` subtraction raises
        # `OverflowError` for a reading close enough to `datetime.min`, and
        # `checked_clock` admits such a reading — it refuses a naive or indeterminate
        # one, not an early one. A fake that crashed where the store answered would
        # be the divergence the shared suite exists to prevent, arriving through the
        # one path the suite's own fixed clock cannot reach.
        floor = max(_to_micros(reading) - _span_micros(self._retention), -_MICROS_BOUND)
        return [row for row in rows if _to_micros(row.occurred_at) >= floor]

    @staticmethod
    def _newest_first(rows: list[TranscriptEntry]) -> list[TranscriptEntry]:
        """ADR-0225 §7's total order: ``occurred_at`` descending, ``address`` ascending.

        Two stable passes rather than one key with a negated instant: ``timestamp()``
        is an IEEE-754 double whose mantissa cannot resolve microseconds at the far
        end of the datetime range, so two entries a microsecond apart could compare
        equal there and the order would stop being total — the precision argument the
        durable store's integer microsecond key rests on, applied to the fake.
        """
        by_address = sorted(rows, key=lambda row: row.address)
        return sorted(by_address, key=lambda row: row.occurred_at, reverse=True)

    async def discard(self, address: str) -> bool:
        """Destroy the entry at ``address``; report whether one was there (§5).

        No retention floor is applied: the destroys reach what the reads hide.

        Args:
            address: The entry's address, taken as opaque.

        Returns:
            Whether an entry was destroyed.

        Raises:
            ValueError: If ``address`` is blank or whitespace-only.
            TranscriptArchiveError: If a fault is scripted.
        """
        named = _check_named(address, name="address")
        self._refuse("discard a transcript entry")
        return self._entries.drop(named)

    async def discard_conversation(self, conversation_id: str) -> int:
        """Destroy every entry grouped under ``conversation_id`` (§5).

        Args:
            conversation_id: The conversation whose entries are destroyed.

        Returns:
            How many entries were destroyed.

        Raises:
            ValueError: If ``conversation_id`` is blank or whitespace-only.
            TranscriptArchiveError: If a fault is scripted.
        """
        named = _check_named(conversation_id, name="conversation_id")
        self._refuse("discard a conversation's transcript")
        return self._entries.drop_conversation(named)

    async def search(self, query: str, *, limit: int = 20, offset: int = 0) -> list[TranscriptHit]:
        """Find entries whose text contains ``query``, newest first (§7).

        Args:
            query: What to look for, byte for byte as the user typed it — never
                trimmed, collapsed or otherwise normalised beyond §7's fold.
            limit: Maximum hits to return.
            offset: How many hits to skip.

        Returns:
            Up to ``limit`` hits, in the total order §7 fixes.

        Raises:
            ValueError: If ``query`` is blank, ``limit`` is zero or below, or
                ``offset`` is negative.
            TranscriptArchiveError: If a fault is scripted.
        """
        needle = _folded(_check_named(query, name="query"))
        _check_page(limit, offset)
        self._refuse("search the transcript archive")
        live = self._live()
        halves = {
            row.address: half
            for row in live
            if (half := self._matching_half(row, needle)) is not None
        }
        ordered = self._newest_first([row for row in live if row.address in halves])
        return [self._hit(row, halves[row.address]) for row in ordered[offset : offset + limit]]

    @staticmethod
    def _matching_half(entry: TranscriptEntry, needle: str) -> str | None:
        """The half of ``entry`` the needle occurs in, ``asked`` first, or ``None``.

        Evaluated **separately** over the two halves and never across them, so a
        query spanning the boundary between what was asked and what was replied
        matches nothing.
        """
        for half in (entry.asked, entry.replied):
            if half is not None and needle in _folded(half):
                return half
        return None

    @staticmethod
    def _hit(entry: TranscriptEntry, half: str) -> TranscriptHit:
        text, elided = _excerpt_of(half)
        return TranscriptHit(
            address=entry.address,
            conversation_id=entry.conversation_id,
            occurred_at=entry.occurred_at,
            excerpt=text,
            elided=elided,
        )

    async def conversation(
        self, conversation_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[TranscriptEntry]:
        """One conversation's entries, in ordinal order (§7).

        Args:
            conversation_id: The conversation to read.
            limit: Maximum entries to return.
            offset: How many entries to skip.

        Returns:
            Up to ``limit`` entries, whole, oldest first.

        Raises:
            ValueError: If ``conversation_id`` is blank, ``limit`` is zero or below,
                or ``offset`` is negative.
            TranscriptArchiveError: If a fault is scripted.
        """
        named = _check_named(conversation_id, name="conversation_id")
        _check_page(limit, offset)
        self._refuse("read a conversation's transcript")
        rows = sorted(
            (row for row in self._live() if row.conversation_id == named),
            key=lambda row: row.ordinal,
        )
        return rows[offset : offset + limit]

    async def entry(self, address: str) -> TranscriptEntry | None:
        """The entry at ``address``, whole, or ``None`` (§7).

        Args:
            address: The entry's address, taken as opaque.

        Returns:
            The entry, or ``None`` where nothing live stands there.

        Raises:
            ValueError: If ``address`` is blank or whitespace-only.
            TranscriptArchiveError: If a fault is scripted.
        """
        named = _check_named(address, name="address")
        self._refuse("read a transcript entry")
        return next((row for row in self._live() if row.address == named), None)

    async def entries(self, *, limit: int = 50, offset: int = 0) -> list[TranscriptEntry]:
        """Every entry the archive holds, newest first — the archive's export (§7).

        Args:
            limit: Maximum entries to return.
            offset: How many entries to skip.

        Returns:
            Up to ``limit`` entries, whole, in the total order §7 fixes.

        Raises:
            ValueError: If ``limit`` is zero or below, or ``offset`` is negative.
            TranscriptArchiveError: If a fault is scripted.
        """
        _check_page(limit, offset)
        self._refuse("export the transcript archive")
        return self._newest_first(self._live())[offset : offset + limit]

    async def size(self) -> TranscriptArchiveSize:
        """What the reads would return, and what the entries occupy (§6).

        Returns:
            The count after the retention predicate, and the bytes held before it —
            the two figures §6 allows to disagree.

        Raises:
            TranscriptArchiveError: If a fault is scripted.
        """
        self._refuse("measure the transcript archive")
        return TranscriptArchiveSize(
            entries=len(self._live()), stored_bytes=self._entries.stored_bytes()
        )


__all__ = ["FakeTranscriptArchive", "FakeTranscriptArchiveWriter"]

"""What every transcript-archive implementation owes (ADR-0225).

Two suites, because ADR-0225 §10 splits the contract by **which object performs
which act**: every ``TranscriptArchiveWriter`` must pass
:class:`TranscriptArchiveWriterContract` and every ``TranscriptArchive``
:class:`TranscriptArchiveContract`. One concrete satisfies both structurally, so
the durable store runs through both and the two canonical fakes run through one
each — which is §10's "one concrete implements both, and the composition root hands
each collaborator exactly the seam it is entitled to" as a test rather than an
assertion.

**The cases here are the ones two implementations diverge on**, which is why §7
names the predicate rather than leaving it to the backend: ``Straße`` and a query of
``STRASSE`` match under full case folding and do not under a tokenizer that
lower-cases ASCII only; a composed ``é`` and a decomposed one differ byte for byte
and are one string under NFC. Both divergences are invisible in a suite written
against one implementation and immediately visible to a user who switches backends.

**The retention cases are read-time cases and are written so that a sweep cannot
pass them.** ADR-0225 §6 enforces the horizon at the read, so :meth:`reopened` hands
the suite a second view of the *same* storage under a different retention: nothing
is written, nothing is swept, and the reads answer differently on the very next
call. A sweep-backed implementation fails those cases, which is the whole point of
asserting them that way.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import TranscriptArchiveError
from ai_assistant.core.types import (
    TRANSCRIPT_EXCERPT_BYTES,
    ExchangeDisposition,
    TranscriptEntry,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import TranscriptArchive, TranscriptArchiveWriter

#: The instant every binding's archive reads the retention predicate against. A
#: fixed reading rather than the wall clock, so a horizon is a property of the
#: entries rather than of how long the suite took to run: every binding constructs
#: its subject with a clock frozen here, and the entries below are placed relative
#: to it.
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)

DAY = timedelta(days=1)


def entry(  # noqa: PLR0913 — one keyword per field of the model this builds, so a case varies exactly the one it is about
    address: str = "c1:1",
    *,
    conversation: str = "c1",
    ordinal: int = 1,
    at: datetime | None = None,
    asked: str | None = "where did I say that",
    replied: str | None = "you said it on Tuesday",
    disposition: ExchangeDisposition = ExchangeDisposition.NO_ACTION_NEEDED,
) -> TranscriptEntry:
    """One entry, with every field defaulted to something a case can vary from."""
    return TranscriptEntry(
        address=address,
        conversation_id=conversation,
        ordinal=ordinal,
        occurred_at=NOW if at is None else at,
        asked=asked,
        replied=replied,
        disposition=disposition,
    )


class TranscriptArchiveWriterContract:
    """What every ``TranscriptArchiveWriter`` owes (ADR-0225 §1, §2, §5, §10).

    The narrow seam capture holds. Its obligations are the ones capture's own
    correctness rests on and cannot check for itself: the append lands at the
    address it was given, an address already taken fails loudly rather than
    overwriting, both destroys are idempotent and resolve inside the archive, and a
    backend fault raises rather than being swallowed — because ADR-0225 §2 decides
    that capture *degrades* at the caller, not that the store lies to it.
    """

    @pytest.fixture
    def writer(self) -> TranscriptArchiveWriter:
        """The subject: an empty writer."""
        raise NotImplementedError

    async def held(self, writer: TranscriptArchiveWriter) -> dict[str, TranscriptEntry]:
        """Every entry ``writer`` holds, keyed by address.

        The suite's window on the writer, not a seam the code under test could
        reach: ``TranscriptArchiveWriter`` carries no read at all, which is the
        whole of ADR-0225 §4's turn-path fence, so a conformance suite for it has to
        be given a way to look.

        Args:
            writer: The subject.

        Returns:
            What it holds.
        """
        raise NotImplementedError

    def failing_writer(self) -> TranscriptArchiveWriter:
        """A writer whose backing store fails every call.

        The implementation's own natural fault — a closed connection, a scripted
        one — rather than an injected exception, so the case is evidence about what
        really happens rather than about a stand-in.

        Returns:
            The writer.
        """
        raise NotImplementedError

    async def test_an_appended_entry_is_held_at_its_address(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """The base case, so nothing below passes vacuously."""
        await writer.append(entry())

        assert set(await self.held(writer)) == {"c1:1"}

    async def test_append_returns_nothing(self, writer: TranscriptArchiveWriter) -> None:
        """``append`` answers no question.

        Pinned because the temptation is to return the address or a bool, and either
        would invite capture to branch on what the archive did — which ADR-0225 §2
        settles at the caller instead, on the report it already builds.
        """
        assert await writer.append(entry()) is None  # type: ignore[func-returns-value]

    async def test_every_field_survives_the_round_trip(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """What was handed in is what is held: no field is derived or dropped."""
        written = entry(at=NOW - DAY, ordinal=7, disposition=ExchangeDisposition.STEP_EXECUTED)

        await writer.append(written)

        assert (await self.held(writer))["c1:1"] == written

    async def test_an_absent_half_survives_as_absent(self, writer: TranscriptArchiveWriter) -> None:
        """``None`` is a fact about the pass, not a value to normalise to ``""``.

        ADR-0225 §1 makes ``asked`` absent where the pass received no user words and
        ``replied`` absent where it produced no reply, and a store that folded either
        into an empty string would make "the user said nothing" indistinguishable
        from "the user said the empty string" — which is not a distinction a
        transcript may lose.
        """
        await writer.append(entry(asked=None, replied=None))

        held = (await self.held(writer))["c1:1"]
        assert held.asked is None
        assert held.replied is None

    async def test_an_address_already_taken_is_refused_loudly(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """ADR-0225 §2: a fault of ADR-0074 §3's class, failed rather than resolved.

        An address is derived from a unique conversation and a store-proved ordinal,
        so a collision means a broken ordinal invariant or a foreign producer in the
        reserved namespace. Neither is a race and a retry answers neither, so the
        first entry stands and the second is refused.
        """
        await writer.append(entry(asked="the first"))

        with pytest.raises(TranscriptArchiveError):
            await writer.append(entry(asked="the second"))

        assert (await self.held(writer))["c1:1"].asked == "the first"

    async def test_the_held_entry_is_detached_from_the_callers_object(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """``frozen=True`` refuses ``x.asked = …`` and not ``x.__dict__["asked"] = …``.

        A store that kept the caller's object would let a later write past the frozen
        model rewrite the record of an exchange that already happened.
        """
        written = entry()
        await writer.append(written)

        written.__dict__["asked"] = "rewritten"

        assert (await self.held(writer))["c1:1"].asked == "where did I say that"

    async def test_discard_destroys_the_entry_and_says_so(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """The address-scoped destroy, and its answer."""
        await writer.append(entry())

        assert await writer.discard("c1:1") is True
        assert await self.held(writer) == {}

    async def test_discard_is_idempotent_and_an_absent_address_is_a_no_op(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """ADR-0225 §5: it destroys what it matches or nothing."""
        await writer.append(entry())
        assert await writer.discard("c1:1") is True

        assert await writer.discard("c1:1") is False
        assert await writer.discard("never written") is False

    async def test_discard_reaches_only_the_address_it_names(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """One address, one entry — never the conversation it belongs to."""
        await writer.append(entry("c1:1", ordinal=1))
        await writer.append(entry("c1:2", ordinal=2))

        assert await writer.discard("c1:1") is True

        assert set(await self.held(writer)) == {"c1:2"}

    async def test_discard_conversation_destroys_that_conversation_and_counts(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """The conversation-scoped destroy, resolved inside the archive (§5)."""
        await writer.append(entry("c1:1", conversation="c1", ordinal=1))
        await writer.append(entry("c1:2", conversation="c1", ordinal=2))
        await writer.append(entry("c2:1", conversation="c2", ordinal=1))

        assert await writer.discard_conversation("c1") == 2

        assert set(await self.held(writer)) == {"c2:1"}

    async def test_discard_conversation_with_no_entries_is_a_no_op_returning_zero(
        self, writer: TranscriptArchiveWriter
    ) -> None:
        """ADR-0225 §5, and it is what makes ADR-0074 §8's re-run work.

        The sweep that follows a failed ``MemoryStore.delete`` finds the archive
        already empty and must carry the remaining episode deletions through to the
        drop rather than treating the zero as an error, so zero has to be the
        conforming answer rather than a fault.
        """
        assert await writer.discard_conversation("never written") == 0

        await writer.append(entry())
        assert await writer.discard_conversation("c1") == 1
        assert await writer.discard_conversation("c1") == 0

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    async def test_a_blank_scope_is_refused_and_destroys_nothing(
        self, writer: TranscriptArchiveWriter, blank: str
    ) -> None:
        """ADR-0101 §1's rule for a blank label, inherited by ADR-0225 §10.

        Never read as "everything": a destructive operation whose absent scope
        widened what it destroys is exactly ADR-0101 §9's refusal.
        """
        await writer.append(entry())

        with pytest.raises(ValueError, match="blank"):
            await writer.discard(blank)
        with pytest.raises(ValueError, match="blank"):
            await writer.discard_conversation(blank)

        assert set(await self.held(writer)) == {"c1:1"}

    async def test_a_backend_fault_raises_from_every_operation(self) -> None:
        """ADR-0225 §10: ``append`` raises on a store failure and never swallows one.

        The asymmetry with ``TraceSink.emit`` is deliberate and is the reason this
        case exists: an unrecorded trace is a lost measurement, an unrecorded
        transcript is the exchange itself, and ADR-0225 §2 decides what to do about
        it at the caller — which it can only do if it is told.
        """
        failing = self.failing_writer()

        with pytest.raises(TranscriptArchiveError):
            await failing.append(entry())
        with pytest.raises(TranscriptArchiveError):
            await failing.discard("c1:1")
        with pytest.raises(TranscriptArchiveError):
            await failing.discard_conversation("c1")


class TranscriptArchiveContract:
    """What every ``TranscriptArchive`` owes (ADR-0225 §5, §6, §7, §10).

    The wide seam the engine holds: four reads, two destroys and a size report, and
    no ``append`` — which is the capability rather than an omission (§1 reserves
    writing to capture).

    **Every read is asserted through the predicate, the order and the bound**, not
    through whichever of the three an implementation finds easiest. §7 names all
    three because "bounded" alone would admit an implementation returning an entry's
    whole text minus one byte, and an unnamed order would leave a scan-backed
    implementation and an index-backed one with no shared assertion to conform to.
    """

    @pytest.fixture
    def archive(self) -> TranscriptArchive:
        """The subject: an empty archive, reading against :data:`NOW`, keeping forever."""
        raise NotImplementedError

    async def store(self, archive: TranscriptArchive, *entries: TranscriptEntry) -> None:
        """Put ``entries`` into ``archive``, bypassing the seam that has no append.

        The suite's way to arrange a history: this face carries no ``append`` at all,
        which is ADR-0225 §10's whole arrangement, so a conformance suite for it has
        to be given a way to write.

        Args:
            archive: The subject.
            *entries: What to hold.
        """
        raise NotImplementedError

    def failing_archive(self) -> TranscriptArchive:
        """An archive whose backing store fails every call.

        Returns:
            The archive.
        """
        raise NotImplementedError

    def reopened(
        self, archive: TranscriptArchive, retention: timedelta | None
    ) -> TranscriptArchive:
        """A second view of ``archive``'s **own** storage, under ``retention``.

        The hook the retention cases turn on, and what makes them read-time cases
        rather than sweep cases (ADR-0225 §6). Nothing is written and nothing is
        swept between the two views: the horizon changes and the reads answer
        differently on the very next call, which a sweep-only implementation cannot
        do. It reads against :data:`NOW`, as the subject does.

        Args:
            archive: The subject whose storage the second view shares.
            retention: The horizon the second view reads against, or ``None``.

        Returns:
            The second view.
        """
        raise NotImplementedError

    # --- the addressed read (§7) --------------------------------------------

    async def test_an_entry_is_returned_whole_at_its_address(
        self, archive: TranscriptArchive
    ) -> None:
        """The base case, and "whole" is the substance: nothing is elided here."""
        written = entry(at=NOW - DAY, ordinal=4)
        await self.store(archive, written)

        assert await archive.entry("c1:1") == written

    async def test_an_unknown_address_reads_as_nothing(self, archive: TranscriptArchive) -> None:
        """``None`` and never an error: an address that names nothing is ordinary."""
        assert await archive.entry("never written") is None

    async def test_the_addressed_read_takes_no_page(self, archive: TranscriptArchive) -> None:
        """ADR-0225 §7: it names one entry and is bounded by that.

        Asserted as the *absence* of the parameters, because a ``limit`` here would
        be a bound on a result that is already at most one — and one nobody could
        refuse, since §7 gives this read no limit to refuse.
        """
        with pytest.raises(TypeError):
            await archive.entry("c1:1", limit=1)  # type: ignore[call-arg]

    # --- the unfiltered enumeration, which is the export (§7) ---------------

    async def test_entries_returns_everything_newest_first(
        self, archive: TranscriptArchive
    ) -> None:
        """§7's total order over the read that is ADR-0004 §6's export."""
        await self.store(
            archive,
            entry("c1:1", at=NOW - 2 * DAY, ordinal=1),
            entry("c1:2", at=NOW - DAY, ordinal=2),
            entry("c2:1", conversation="c2", at=NOW, ordinal=1),
        )

        assert [one.address for one in await archive.entries()] == ["c2:1", "c1:2", "c1:1"]

    async def test_two_entries_sharing_an_instant_are_ordered_by_address(
        self, archive: TranscriptArchive
    ) -> None:
        """The tie-break is what makes the order **total** rather than merely defined.

        Without it two entries a page apart could swap between two reads, so a paged
        export would repeat one and lose the other — which for the read that *is* the
        export is a silently incomplete artifact.
        """
        await self.store(
            archive,
            entry("c1:2", at=NOW, ordinal=2),
            entry("c1:1", at=NOW, ordinal=1),
        )

        assert [one.address for one in await archive.entries()] == ["c1:1", "c1:2"]

    async def test_entries_pages_through_the_order(self, archive: TranscriptArchive) -> None:
        """A page is cut out of the total order, so the pages compose into it."""
        await self.store(
            archive,
            entry("c1:1", at=NOW - 2 * DAY, ordinal=1),
            entry("c1:2", at=NOW - DAY, ordinal=2),
            entry("c1:3", at=NOW, ordinal=3),
        )

        first = await archive.entries(limit=2)
        second = await archive.entries(limit=2, offset=2)

        assert [one.address for one in [*first, *second]] == ["c1:3", "c1:2", "c1:1"]

    # --- one conversation's own read (§7) -----------------------------------

    async def test_a_conversation_reads_in_ordinal_order(self, archive: TranscriptArchive) -> None:
        """ADR-0225 §7: a transcript's order is the order it was said in.

        The one read whose order is **not** the newest-first total order, and the
        instants below are deliberately out of step with the ordinals so an
        implementation that sorted by instant here fails rather than coincidentally
        passing.
        """
        await self.store(
            archive,
            entry("c1:2", at=NOW, ordinal=2),
            entry("c1:1", at=NOW - DAY, ordinal=1),
            entry("c1:3", at=NOW - 2 * DAY, ordinal=3),
        )

        read = await archive.conversation("c1")

        assert [one.ordinal for one in read] == [1, 2, 3]

    async def test_a_conversation_reads_only_its_own_entries(
        self, archive: TranscriptArchive
    ) -> None:
        """The grouping is a filter over one key and never a second scheme (§3)."""
        await self.store(
            archive,
            entry("c1:1", conversation="c1", ordinal=1),
            entry("c2:1", conversation="c2", ordinal=1),
        )

        assert [one.address for one in await archive.conversation("c2")] == ["c2:1"]

    async def test_an_unknown_conversation_reads_as_empty(self, archive: TranscriptArchive) -> None:
        """Empty and never an error: the archive needs no index to answer this."""
        assert await archive.conversation("never used") == []

    # --- the search predicate (§7, §13 item 13) -----------------------------

    async def test_the_search_matches_a_substring_of_what_was_asked(
        self, archive: TranscriptArchive
    ) -> None:
        """The base case: a contiguous run, not a token."""
        await self.store(archive, entry(asked="the lender was Ravensworth", replied="noted"))

        assert [hit.address for hit in await archive.search("ender was Rav")] == ["c1:1"]

    async def test_the_search_matches_a_substring_of_what_was_replied(
        self, archive: TranscriptArchive
    ) -> None:
        """Both halves are searched, separately."""
        await self.store(archive, entry(asked="which one", replied="the lender was Ravensworth"))

        assert [hit.address for hit in await archive.search("Ravensworth")] == ["c1:1"]

    async def test_the_excerpt_is_the_half_the_query_was_found_in(
        self, archive: TranscriptArchive
    ) -> None:
        """ADR-0225 §7: "a bounded excerpt of **the matching text**".

        The case that separates "which half is present" from "which half matched" —
        and the one an implementation gets wrong by excerpting whichever half is
        non-``None``. A hit that does not contain what was searched for reads to a
        user as a *wrong* result rather than as a bounded one, and it makes the
        address the only usable part of the answer.

        Asserted in both directions, because a rule tested only where it fires is
        half a rule: a store that always excerpted ``replied`` would pass the first
        assertion below and fail the second.
        """
        await self.store(
            archive,
            entry("c1:1", asked="hello", replied="the lender was Ravensworth"),
            entry(
                "c2:1",
                conversation="c2",
                asked="was it Ravensworth",
                replied="that is right",
            ),
        )

        replied_side = await archive.search("Ravensworth", limit=1, offset=0)
        found = {hit.address: hit.excerpt for hit in await archive.search("Ravensworth")}

        assert replied_side, "the fixture must actually match"
        assert found["c1:1"] == "the lender was Ravensworth"
        assert found["c2:1"] == "was it Ravensworth"

    async def test_the_users_half_wins_where_both_halves_match(
        self, archive: TranscriptArchive
    ) -> None:
        """The tie, decided the same way by every conforming implementation.

        §7 leaves *which window* of the matching text an excerpt is taken from to the
        lane; it does not leave two implementations free to answer a two-sided match
        with different halves, which would be the divergence §7 names the predicate to
        prevent, one level up.
        """
        await self.store(archive, entry(asked="Ravensworth asked", replied="Ravensworth said"))

        hit = (await archive.search("Ravensworth"))[0]

        assert hit.excerpt == "Ravensworth asked"

    async def test_a_query_spanning_the_two_halves_matches_nothing(
        self, archive: TranscriptArchive
    ) -> None:
        """ADR-0225 §7: evaluated over each half, **never across the two**.

        An implementation that concatenated the halves before matching would invent
        a sentence neither party said and report it as something the user typed.
        """
        await self.store(archive, entry(asked="who was it", replied="Ravensworth"))

        assert await archive.search("who was itRavensworth") == []
        assert await archive.search("it Ravens") == []

    async def test_full_case_folding_matches_where_simple_folding_would_not(
        self, archive: TranscriptArchive
    ) -> None:
        """``ß`` folds to ``ss`` under ``str.casefold`` and not under lower-casing.

        The first of §7's two named divergences: invisible in a suite written against
        one implementation, immediately visible to a user who switches backends.
        """
        await self.store(archive, entry(asked="wo ist die Straße", replied="dort"))

        assert [hit.address for hit in await archive.search("STRASSE")] == ["c1:1"]

    async def test_a_decomposed_query_matches_composed_text_and_the_reverse(
        self, archive: TranscriptArchive
    ) -> None:
        """§7's second divergence: NFC first, so two spellings are one string."""
        composed = unicodedata.normalize("NFC", "café")
        decomposed = unicodedata.normalize("NFD", "café")
        assert composed != decomposed, "the fixture must actually differ byte for byte"

        await self.store(archive, entry("c1:1", asked=composed, replied=None))
        await self.store(archive, entry("c2:1", conversation="c2", asked=decomposed, replied=None))

        assert {hit.address for hit in await archive.search(decomposed)} == {"c1:1", "c2:1"}
        assert {hit.address for hit in await archive.search(composed)} == {"c1:1", "c2:1"}

    async def test_case_is_ignored_in_both_directions(self, archive: TranscriptArchive) -> None:
        """An all-caps query against lower-case text, and the reverse."""
        await self.store(archive, entry("c1:1", asked="ravensworth", replied=None))
        await self.store(
            archive, entry("c2:1", conversation="c2", asked="RAVENSWORTH", replied=None)
        )

        assert {hit.address for hit in await archive.search("RAVENSWORTH")} == {"c1:1", "c2:1"}
        assert {hit.address for hit in await archive.search("ravensworth")} == {"c1:1", "c2:1"}

    async def test_a_one_character_query_is_admitted(self, archive: TranscriptArchive) -> None:
        """ADR-0225 §7: no minimum query length, and no stop-word removal."""
        await self.store(archive, entry(asked="a", replied=None))

        assert [hit.address for hit in await archive.search("a")] == ["c1:1"]

    async def test_a_querys_own_whitespace_is_significant(self, archive: TranscriptArchive) -> None:
        """§10: the query is never trimmed, which is why it is not an ``Identifier``.

        ``Identifier`` *strips* the value it accepts, which would rewrite the user's
        search text before the predicate saw it and make ``" hello"`` and ``"hello"``
        one query.
        """
        await self.store(archive, entry("c1:1", asked="say hello there", replied=None))
        await self.store(
            archive, entry("c2:1", conversation="c2", asked="sayhello there", replied=None)
        )

        assert [hit.address for hit in await archive.search(" hello")] == ["c1:1"]

    async def test_search_results_are_newest_first_and_total(
        self, archive: TranscriptArchive
    ) -> None:
        """The same total order the enumerating reads use, with no ranking on top."""
        await self.store(
            archive,
            entry("c1:1", at=NOW - DAY, ordinal=1, asked="Ravensworth twice Ravensworth"),
            entry("c1:2", at=NOW, ordinal=2, asked="Ravensworth once"),
        )

        assert [hit.address for hit in await archive.search("Ravensworth")] == ["c1:2", "c1:1"]

    async def test_a_hit_names_where_the_match_is(self, archive: TranscriptArchive) -> None:
        """A hit is an address to read by, not the entry: §7 splits the two acts."""
        await self.store(archive, entry(at=NOW - DAY, asked="Ravensworth"))

        hit = (await archive.search("Ravensworth"))[0]

        assert hit.address == "c1:1"
        assert hit.conversation_id == "c1"
        assert hit.occurred_at == NOW - DAY

    async def test_search_pages_through_its_order(self, archive: TranscriptArchive) -> None:
        """The page is cut out of the order, as it is for the other two reads."""
        await self.store(
            archive,
            entry("c1:1", at=NOW - 2 * DAY, ordinal=1, asked="Ravensworth"),
            entry("c1:2", at=NOW - DAY, ordinal=2, asked="Ravensworth"),
            entry("c1:3", at=NOW, ordinal=3, asked="Ravensworth"),
        )

        first = await archive.search("Ravensworth", limit=2)
        second = await archive.search("Ravensworth", limit=2, offset=2)

        assert [hit.address for hit in [*first, *second]] == ["c1:3", "c1:2", "c1:1"]

    # --- the excerpt bound (§7, §13 item 10) --------------------------------

    async def test_a_long_entry_is_excerpted_to_the_bound(self, archive: TranscriptArchive) -> None:
        """ADR-0225 §7: at most 512 bytes of UTF-8, and it says it was cut."""
        await self.store(archive, entry(asked="Ravensworth " + "x" * 4000, replied=None))

        hit = (await archive.search("Ravensworth"))[0]

        assert len(hit.excerpt.encode("utf-8")) <= TRANSCRIPT_EXCERPT_BYTES
        assert hit.elided is True

    async def test_a_short_entry_is_its_own_excerpt(self, archive: TranscriptArchive) -> None:
        """Where the whole of it fits, the excerpt is it — which is what a bound means."""
        await self.store(archive, entry(asked="a", replied=None))

        hit = (await archive.search("a"))[0]

        assert hit.excerpt == "a"
        assert hit.elided is False

    async def test_a_codepoint_straddling_the_bound_is_dropped_not_split(
        self, archive: TranscriptArchive
    ) -> None:
        """A byte bound applied to UTF-8 without this clause produces invalid text.

        The text below is built so that a three-byte codepoint straddles byte 512
        exactly: a naive slice would end mid-sequence, and the result would not be a
        ``str`` at all — or, worse, would decode with a replacement character the
        user would read as something they had said.
        """
        # 510 ASCII bytes, then three-byte codepoints: the first of them starts at
        # byte 510 and ends at 513, so the bound falls inside it.
        text = "Ravensworth" + "x" * 499 + "€€€"
        assert len(("Ravensworth" + "x" * 499).encode("utf-8")) == TRANSCRIPT_EXCERPT_BYTES - 2
        await self.store(archive, entry(asked=text, replied=None))

        hit = (await archive.search("Ravensworth"))[0]

        assert hit.excerpt.encode("utf-8").decode("utf-8") == hit.excerpt
        assert len(hit.excerpt.encode("utf-8")) <= TRANSCRIPT_EXCERPT_BYTES
        assert not hit.excerpt.endswith("€"), "the straddling codepoint is dropped, not split"
        assert hit.elided is True

    # --- the refusals (§7, §10) ---------------------------------------------

    @pytest.mark.parametrize("limit", [0, -1, -(2**63)])
    async def test_a_limit_at_or_below_zero_is_refused(
        self, archive: TranscriptArchive, limit: int
    ) -> None:
        """ADR-0114 §6's refusal, on each of the three reads that take one."""
        with pytest.raises(ValueError, match="limit"):
            await archive.search("x", limit=limit)
        with pytest.raises(ValueError, match="limit"):
            await archive.conversation("c1", limit=limit)
        with pytest.raises(ValueError, match="limit"):
            await archive.entries(limit=limit)

    @pytest.mark.parametrize("offset", [-1, -(2**63)])
    async def test_a_negative_offset_is_refused(
        self, archive: TranscriptArchive, offset: int
    ) -> None:
        """The same refusal, on the other paging argument."""
        with pytest.raises(ValueError, match="offset"):
            await archive.search("x", offset=offset)
        with pytest.raises(ValueError, match="offset"):
            await archive.conversation("c1", offset=offset)
        with pytest.raises(ValueError, match="offset"):
            await archive.entries(offset=offset)

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    async def test_a_blank_scope_or_query_is_refused_and_matches_nothing(
        self, archive: TranscriptArchive, blank: str
    ) -> None:
        """ADR-0101 §1's rule for a blank label, over every operation that takes one."""
        await self.store(archive, entry())

        with pytest.raises(ValueError, match="blank"):
            await archive.search(blank)
        with pytest.raises(ValueError, match="blank"):
            await archive.conversation(blank)
        with pytest.raises(ValueError, match="blank"):
            await archive.entry(blank)
        with pytest.raises(ValueError, match="blank"):
            await archive.discard(blank)
        with pytest.raises(ValueError, match="blank"):
            await archive.discard_conversation(blank)

        assert len(await archive.entries()) == 1

    async def test_a_backend_fault_raises_from_every_operation(self) -> None:
        """ADR-0225 §10's single archive error class, over the whole seam."""
        failing = self.failing_archive()

        with pytest.raises(TranscriptArchiveError):
            await failing.search("x")
        with pytest.raises(TranscriptArchiveError):
            await failing.conversation("c1")
        with pytest.raises(TranscriptArchiveError):
            await failing.entry("c1:1")
        with pytest.raises(TranscriptArchiveError):
            await failing.entries()
        with pytest.raises(TranscriptArchiveError):
            await failing.size()
        with pytest.raises(TranscriptArchiveError):
            await failing.discard("c1:1")
        with pytest.raises(TranscriptArchiveError):
            await failing.discard_conversation("c1")

    # --- the destroys, on this seam too (§5) --------------------------------

    async def test_both_destroys_are_reachable_from_this_seam(
        self, archive: TranscriptArchive
    ) -> None:
        """§10: the two faces overlap in exactly the acts both holders perform.

        The engine reaches these from ``forget`` and from the user's own destroy;
        capture reaches its own from the compensation and from ADR-0074 §8's step 2.
        Strike either from either seam and a named act has no way to run.
        """
        await self.store(
            archive,
            entry("c1:1", conversation="c1", ordinal=1),
            entry("c1:2", conversation="c1", ordinal=2),
            entry("c2:1", conversation="c2", ordinal=1),
        )

        assert await archive.discard("c1:1") is True
        assert await archive.discard_conversation("c1") == 1

        assert [one.address for one in await archive.entries()] == ["c2:1"]

    # --- retention, enforced at the read (§6, §13 item 8) -------------------

    async def test_an_unset_retention_keeps_everything_forever(
        self, archive: TranscriptArchive
    ) -> None:
        """§6's shipped default, and the base case the horizon cases contrast with."""
        await self.store(archive, entry(at=NOW - 3650 * DAY))

        assert len(await archive.entries()) == 1
        assert (await archive.size()).entries == 1

    async def test_an_aged_entry_is_hidden_from_all_four_reads_with_no_write_or_sweep(
        self, archive: TranscriptArchive
    ) -> None:
        """§6's whole point: the horizon is a **read-time** predicate.

        The second view shares this archive's storage and has neither written to it
        nor swept it, so an implementation that hid entries only when something ran
        fails here — which is the case a sweep-only store passes on and a read-time
        one does not.
        """
        await self.store(archive, entry(at=NOW - 10 * DAY, asked="Ravensworth"))

        aged = self.reopened(archive, 3 * DAY)

        assert await aged.entry("c1:1") is None
        assert await aged.entries() == []
        assert await aged.conversation("c1") == []
        assert await aged.search("Ravensworth") == []

    async def test_an_entry_at_the_horizon_is_kept_and_one_past_it_is_not(
        self, archive: TranscriptArchive
    ) -> None:
        """§6: *strictly* older than the read minus the retention is evicted.

        The boundary is asserted on both sides because a store that used ``>``
        instead of ``>=`` would evict an entry exactly at the horizon, which is a
        day of transcript nobody asked to lose.
        """
        await self.store(
            archive,
            entry("c1:1", at=NOW - 3 * DAY, ordinal=1),
            entry("c1:2", at=NOW - 3 * DAY - timedelta(microseconds=1), ordinal=2),
        )

        aged = self.reopened(archive, 3 * DAY)

        assert [one.address for one in await aged.entries()] == ["c1:1"]

    async def test_shortening_the_retention_hides_more_on_the_very_next_read(
        self, archive: TranscriptArchive
    ) -> None:
        """§6: the predicate is evaluated against the setting in force at the read."""
        await self.store(
            archive,
            entry("c1:1", at=NOW - DAY, ordinal=1),
            entry("c1:2", at=NOW - 5 * DAY, ordinal=2),
        )

        assert len(await self.reopened(archive, 10 * DAY).entries()) == 2
        assert [one.address for one in await self.reopened(archive, 2 * DAY).entries()] == ["c1:1"]

    async def test_a_hidden_entry_still_yields_to_both_destroys(
        self, archive: TranscriptArchive
    ) -> None:
        """§6: the destroys reach what the reads hide.

        A destruction is never refused on the ground that a read would not have shown
        it, which is what keeps ADR-0004 §6's right from being conditional on a
        horizon.
        """
        await self.store(
            archive,
            entry("c1:1", conversation="c1", at=NOW - 10 * DAY, ordinal=1),
            entry("c2:1", conversation="c2", at=NOW - 10 * DAY, ordinal=1),
        )
        aged = self.reopened(archive, DAY)

        assert await aged.discard("c1:1") is True
        assert await aged.discard_conversation("c2") == 1

        assert await self.reopened(archive, None).entries() == []

    async def test_a_hidden_entry_consumes_no_page_slot(self, archive: TranscriptArchive) -> None:
        """§6: the predicate binds **before** the ordering and before the page.

        A hidden entry consumes no slot in any ``limit`` and shifts no ``offset``,
        because eviction that reached further than the entry it evicted would make a
        *live* entry unreachable through the ordinary read.

        **The arrangement is what gives the case teeth.** ADR-0225 §13 item 8 states
        it as "an expired entry newer than a live one"; under an age predicate the
        hidden entry is necessarily the *older* one, so on the two newest-first reads
        the shape that separates the implementations is a hidden entry in the
        **middle** of the order — paging first takes the newest two, drops one, and
        answers a short page where the contract owes two. A conversation's own read
        is ordered by *ordinal*, which age does not determine, so §13's literal shape
        is reachable there and the case below asserts it.
        """
        await self.store(
            archive,
            # Ordinal 1, oldest, live: the entry a page-then-filter never reaches.
            entry("c1:1", at=NOW - 5 * DAY, ordinal=1, asked="Ravensworth"),
            # Ordinal 2, in the middle by instant, hidden by the horizon below.
            entry("c1:2", at=NOW - 20 * DAY, ordinal=2, asked="Ravensworth"),
            # Ordinal 3, newest, live.
            entry("c1:3", at=NOW - DAY, ordinal=3, asked="Ravensworth"),
        )
        aged = self.reopened(archive, 10 * DAY)

        assert [one.address for one in await aged.entries(limit=2)] == ["c1:3", "c1:1"]
        assert [hit.address for hit in await aged.search("Ravensworth", limit=2)] == [
            "c1:3",
            "c1:1",
        ]
        assert [one.ordinal for one in await aged.conversation("c1", limit=2)] == [1, 3]

    async def test_a_hidden_entry_does_not_empty_a_conversations_first_page(
        self, archive: TranscriptArchive
    ) -> None:
        """§13 item 8's literal shape, on the read where it is reachable.

        A conversation's read is ordered by ordinal, which the horizon does not
        determine, so a hidden entry really can sort *ahead* of a live one — and an
        implementation that paged before it filtered answers ``limit=1`` with an
        empty first page, leaving the live entry unreachable through the ordinary
        read.
        """
        await self.store(
            archive,
            entry("c1:1", at=NOW - 20 * DAY, ordinal=1),
            entry("c1:2", at=NOW - DAY, ordinal=2),
        )
        aged = self.reopened(archive, 10 * DAY)

        assert [one.ordinal for one in await aged.conversation("c1", limit=1)] == [2]

    # --- the size report (§6, §13 item 17) ----------------------------------

    async def test_an_empty_archive_reports_no_entries(self, archive: TranscriptArchive) -> None:
        """The base case, so the counting cases below cannot pass vacuously."""
        assert (await archive.size()).entries == 0

    async def test_the_count_tracks_what_is_stored_and_both_destroys(
        self, archive: TranscriptArchive
    ) -> None:
        """§6: ``entries`` is what the reads would return."""
        await self.store(
            archive,
            entry("c1:1", conversation="c1", ordinal=1),
            entry("c1:2", conversation="c1", ordinal=2),
            entry("c2:1", conversation="c2", ordinal=1),
        )
        assert (await archive.size()).entries == 3

        await archive.discard("c1:1")
        assert (await archive.size()).entries == 2

        await archive.discard_conversation("c1")
        assert (await archive.size()).entries == 1

    async def test_a_populated_archive_never_reports_no_bytes(
        self, archive: TranscriptArchive
    ) -> None:
        """§6: zero over an archive holding entries is not a conforming answer.

        Stated over *every* implementation and not only the durable one — "a fake
        that gave one would make the conformance case vacuous" — because the figure
        exists to fire a deferred cap, and a trigger with no instrument never fires.
        """
        await self.store(archive, entry())

        assert (await archive.size()).stored_bytes > 0

    async def test_the_stored_bytes_rise_with_what_is_stored(
        self, archive: TranscriptArchive
    ) -> None:
        """It measures the storage, which is the figure the deferred cap turns on."""
        await self.store(archive, entry("c1:1", ordinal=1))
        before = (await archive.size()).stored_bytes

        await self.store(
            archive,
            *(
                entry(f"c1:{n}", ordinal=n, asked="x" * 2000, replied="y" * 2000)
                for n in range(2, 60)
            ),
        )

        assert (await archive.size()).stored_bytes > before

    async def test_the_two_figures_part_company_over_a_hidden_entry(
        self, archive: TranscriptArchive
    ) -> None:
        """§6: they answer different questions and are allowed to disagree.

        The hidden entry leaves ``entries`` and its bytes stay in ``stored_bytes``
        until something physically reclaims them. A report that netted the two would
        hide exactly the growth the cap exists to catch.
        """
        await self.store(archive, entry(at=NOW - 10 * DAY))
        aged = self.reopened(archive, DAY)

        size = await aged.size()

        assert size.entries == 0
        assert size.stored_bytes > 0

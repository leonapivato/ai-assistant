"""Shared conformance suite for the Fetcher Protocol (ADR-0230 §4, §13).

Every ``Fetcher`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`FetcherContract`, supplies
the two subject fixtures — one whose root holds something, one whose root holds
nothing — and overrides :meth:`FetcherContract.clocked` and
:meth:`FetcherContract.gated`.

**Here rather than under ``tests/readers/``**, beside the Protocol it encodes and
beside ``reader_contract.py``, which made the same choice for the same reason: the
canonical fake lives in ``ai_assistant.testing`` and the concrete implementation
lives in a package no subsystem may import, so a suite in either place would sit
beside one of its two subjects and across a directory from the other.

**What is in here, and what deliberately is not.** ADR-0230 §13 fixes the division
exactly, and this file states it so that a reader does not mistake an absence from
the suite for an absence from the contract. The suite holds the clauses expressible
**without a source** — decidable from ``name`` and two return values — and above all
the **handle clauses**, which "are suite clauses and not the concrete fetcher's,
because they are decidable from ``name`` and two return values and they are the
clauses on which §2's containment rests for **every** ``Fetcher`` this system ever
wires".

Four rulings are deliberately **not** suite clauses:

* **That the root bound is un-widenable.** The Protocol takes no argument that could
  widen it — ``listing`` takes none at all — so a generic suite has nothing to
  over-supply. It is a concrete fetcher's test and a ``Settings`` test.
* **That a *real* source failure produces each refusal class.** A suite cannot make
  an arbitrary fetcher's source fail, so it pins that a refusal is *returned* rather
  than raised, and not that each class is reached from a real deletion, a real
  directory, a real permission denial, a real growth or a real extraction failure.
  Those are the concrete fetcher's, "and it owes one per ``FetchRefusal`` member".
* **That a path escaping the root is refused, and that §4's race transitions are
  refused.** A generic suite cannot replace an arbitrary fetcher's root, so ``..``, a
  separator in a name, a symbolic link out of the root, a replacement between
  validation and acquisition, a replacement by a named pipe with no writer, a growth
  past the bound, and a replacement of the root's own pathname are the concrete
  fetcher's arms.
* **That the listing is ordered most-recently-modified-first and capped.** A suite
  holding one listing cannot decide the order a root's own modification times imply.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import Fetcher
from ai_assistant.core.types import (
    BeliefBand,
    FetchRefusal,
    MemoryKind,
    MemorySource,
    SourceListing,
    SourceListingEntry,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import FetchOutcome
    from ai_assistant.testing.cancellation import SuspendedCall

#: What a failure of the cancellation case means, in one place (ADR-0230 §4). It is
#: the one place a conforming-looking fetcher satisfies every other clause in this
#: file and still absorbs a cancellation, converting a shutdown that was working
#: correctly into an empty listing or a refusal.
_ABSORBED = (
    "a cancelled listing() or fetch() must deliver the cancellation onward unchanged "
    "and must convert it into neither an empty listing nor a refusal (ADR-0230 §4). "
    "Got: {outcome!r}"
)

#: A handle and a listing authority no fetcher minted. Any value does, since the
#: property under test is that verification is over a signature and not over a shape.
_INVENTED_HANDLE = "0." + "0" * 64
_INVENTED_AUTHORITY = "deadbeef.1.1." + "0" * 64


class Dial:
    """A clock a suite turns by hand.

    ADR-0230 §4 binds **two** deadlines into a listing's token and refuses once
    *either* has passed, and three of the expiry arms below turn exactly one of the
    two: a wall clock stepped backwards must not extend a listing, and a frozen
    monotonic source must not either. Neither is reachable without a lever on each
    clock separately, which is why a subject supplies two of these rather than one
    "advance time" callable.
    """

    def __init__(self, value: float) -> None:
        """Start the dial at ``value`` — an epoch second, or a monotonic nanosecond."""
        self._value = value

    def read(self) -> float:
        """The current reading."""
        return self._value

    def set(self, value: float) -> None:
        """Move the dial to ``value``, forwards or backwards."""
        self._value = value

    def advance(self, by: float) -> None:
        """Move the dial forwards by ``by``."""
        self._value += by


def wall_of(dial: Dial) -> datetime:
    """The wall clock a :class:`Dial` stands for, as an aware UTC instant."""
    return datetime.fromtimestamp(dial.read(), tz=UTC)


@dataclass(frozen=True)
class ClockedFetcher:
    """A subject whose two clocks the suite drives, plus its TTL.

    Attributes:
        fetcher: The subject, wired to read ``wall`` and ``monotonic``.
        ttl: The ``fetch_listing_ttl`` it was built with, so the suite can step past
            it without knowing the implementation's default.
        wall: Its wall clock, in epoch seconds.
        monotonic: Its monotonic source, in nanoseconds.
    """

    fetcher: Fetcher
    ttl: timedelta
    wall: Dial
    monotonic: Dial


@dataclass(frozen=True)
class GatedFetch:
    """One subject that can be held inside either call, plus a lever for each.

    What ADR-0060's case needs from an implementation, and no more. The property has
    no positive signal through the two members alone: a suite has to hold a call open
    at a point it has demonstrably reached, cancel it *there*, and see what comes
    back — and only the implementation knows where its suspension is.

    A call cancelled *before* it suspends exercises none of the code an
    implementation would use to catch a ``CancelledError`` during source I/O and
    convert it, so a suite without this lever reports the property as held while
    testing nothing.

    **Two levers rather than one**, because the fetch case needs an authentic listing
    first and a lever armed at construction would be spent producing it — which would
    hold the *listing* and cancel nothing the fetch does.

    Attributes:
        fetcher: The subject, ready to be called.
        arm_listing: Arms the **next** ``listing()`` to suspend inside the root, and
            returns the handle the suite waits on and releases.
        arm_fetch: The same for the next ``fetch()``.
    """

    fetcher: Fetcher
    arm_listing: Callable[[], SuspendedCall]
    arm_fetch: Callable[[], SuspendedCall]


def assert_conforms(listing: SourceListing, name: str) -> None:
    """Assert every clause that holds of any listing, whatever it carries.

    The suite's own cases each assert one clause against one subject, which is what
    makes a failure name the obligation it broke. This is the same set as one call,
    for the cases that must hold it over a *second* subject — an **empty** listing
    above all, on which every clause below still binds (ADR-0230 §6).
    """
    assert listing.source == name
    assert listing.read_at.tzinfo is not None
    assert listing.read_at.utcoffset() is not None
    assert listing.token
    for entry in listing.entries:
        assert entry.name.strip()
        assert entry.size_bytes >= 0
        assert entry.modified_at.tzinfo is not None
        assert entry.modified_at.utcoffset() is not None
        assert entry.handle


def assert_minted(outcome: FetchOutcome, name: str) -> None:
    """Assert what ADR-0230 §5 requires of the record a successful fetch mints."""
    record = outcome.record
    assert record is not None, "a successful fetch mints exactly one record (ADR-0230 §5)"
    assert outcome.refusal is None
    assert record.kind == MemoryKind.SEMANTIC.value
    assert record.provenance.source is MemorySource.EXTERNAL
    assert band_of(record.provenance.source) is BeliefBand.ATTESTED
    attestation = record.provenance.attestation
    assert attestation is not None, "an EXTERNAL record carries an attestation (ADR-0092 §1)"
    assert attestation.reported_by == name
    assert record.provenance.evidence == ()


class FetcherContract:
    """Behaviour every ``Fetcher`` implementation must exhibit (ADR-0230 §4)."""

    @pytest.fixture
    def fetcher(self) -> Fetcher:
        """Override in a subclass with a subject whose root holds **something**.

        Several clauses below quantify over ``entries``, and a fetcher whose root is
        empty would pass them having exercised nothing. The empty root is a separate
        subject with its own cases.
        """
        raise NotImplementedError

    @pytest.fixture
    def empty_fetcher(self) -> Fetcher:
        """Override with a subject whose root holds nothing.

        Not a failure and not a degradation: ADR-0230 §6 rules an empty ``entries``
        tuple a **successful** listing, and makes a root that cannot be read produce
        one too, with no consumer distinguishing them.
        """
        raise NotImplementedError

    def clocked(self) -> ClockedFetcher:
        """Override with a subject whose two clocks the suite may drive.

        Called once per case that needs it, so each gets fresh dials and a fresh
        subject. See :class:`ClockedFetcher`.
        """
        raise NotImplementedError

    def gated(self) -> GatedFetch:
        """Override with a subject that can be held at its suspension point.

        Called once per case that needs it. See :class:`GatedFetch`.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, fetcher: Fetcher) -> None:
        assert isinstance(fetcher, Fetcher)

    # --- identity (ADR-0230 §4, ADR-0189, ADR-0190) -------------------------

    def test_the_declared_identity_is_non_empty(self, fetcher: Fetcher) -> None:
        """A fetcher that cannot say what it is forces every caller to carry a name.

        Non-empty rather than merely present: the identity lands on every listing's
        ``source``, on ``reported_by`` of every record a fetch mints, and in every log
        line, and a blank one names nothing in all three places.
        """
        assert fetcher.name.strip()

    async def test_the_declared_identity_is_stable_across_calls(self, fetcher: Fetcher) -> None:
        """Assigned, not computed: listing the root must not rename the fetcher.

        A fetcher whose identity moved under a listing would scatter one source's
        records across two ``reported_by`` values that no later fold could bring back
        together (ADR-0230 §4, ADR-0189 §6).
        """
        before = fetcher.name

        await fetcher.listing()
        listing = await fetcher.listing()
        await fetcher.fetch(listing, listing.entries[0])

        assert fetcher.name == before

    # --- the listing (ADR-0230 §4, §6) --------------------------------------

    async def test_a_listing_declares_the_fetcher_that_produced_it(self, fetcher: Fetcher) -> None:
        """``source`` equals ``name``, so a listing says whose address space it is."""
        assert_conforms(await fetcher.listing(), fetcher.name)

    async def test_an_empty_listing_is_a_success_and_every_clause_holds_on_it(
        self, empty_fetcher: Fetcher
    ) -> None:
        """ADR-0230 §6: a root that is empty and one that cannot be read both list nothing.

        Asserted through the same helper the populated case uses, which is the whole
        point of the clause: an empty listing is not a lesser value with clauses
        waived, it is a listing that happens to carry no entries.
        """
        listing = await empty_fetcher.listing()

        assert listing.entries == ()
        assert_conforms(listing, empty_fetcher.name)

    async def test_listing_takes_no_argument_a_caller_could_widen_it_with(
        self, fetcher: Fetcher
    ) -> None:
        """ADR-0093 §10's rule one contract over, asserted on the signature.

        The root, the ordering, the entry cap and the type allow-list are the
        fetcher's own configuration, and "a caller able to widen the listing is a
        caller able to defeat every bound behind it". The suite cannot over-supply an
        argument that does not exist, so what it asserts is that none does.
        """
        import inspect  # noqa: PLC0415 — asserted about, not used by, this module

        parameters = inspect.signature(type(fetcher).listing).parameters
        assert [name for name in parameters if name != "self"] == []

    # --- what a fetch mints (ADR-0230 §5) -----------------------------------

    async def test_a_fetched_record_is_attested_to_this_fetcher(self, fetcher: Fetcher) -> None:
        """§5's shape, arm for arm: ``SEMANTIC``, ``EXTERNAL``, attested, no evidence.

        ``evidence`` is empty because a fetched record is not worked out from
        anything: it is a document's text, and a citation would name a belief this
        record does not rest on.
        """
        listing = await fetcher.listing()

        assert_minted(await fetcher.fetch(listing, listing.entries[0]), fetcher.name)

    async def test_an_outcome_carries_a_record_or_a_refusal_and_never_both(
        self, fetcher: Fetcher
    ) -> None:
        """ADR-0230 §4's exactly-one rule, over both of the outcomes a suite can reach."""
        listing = await fetcher.listing()

        fetched = await fetcher.fetch(listing, listing.entries[0])
        refused = await fetcher.fetch(listing, _assembled(listing.entries[0]))

        assert (fetched.record is None) != (fetched.refusal is None)
        assert (refused.record is None) != (refused.refusal is None)

    # --- membership is a minted capability (ADR-0230 §4) --------------------

    async def test_an_entry_the_caller_assembled_is_refused(self, fetcher: Fetcher) -> None:
        """The clause the whole seam exists for: a caller may not name its own file.

        An earlier draft of ADR-0230 §4 required ``fetch`` to refuse "anything the
        fetcher did not itself list" and gave the fetcher no way to tell — a
        ``SourceListingEntry`` is a public frozen model carrying display metadata, so
        a caller could assemble one for any direct child of the root, "including one
        the listing's cap left out, which is precisely the file a planner was **not**
        shown". A minted, verified capability is what makes the containment structural.
        """
        listing = await fetcher.listing()

        outcome = await fetcher.fetch(listing, _assembled(listing.entries[0]))

        assert outcome.refusal is FetchRefusal.NOT_FOUND

    async def test_a_listed_entrys_display_fields_on_an_invented_handle_are_refused(
        self, fetcher: Fetcher
    ) -> None:
        """Copying a *real* entry's name, size and instant onto a handle of one's own.

        The arm that fails an implementation deciding membership by re-reading its
        caller's ``name``: every display field here is authentic, and the one field
        that is authority is not.
        """
        listing = await fetcher.listing()
        original = listing.entries[0]

        outcome = await fetcher.fetch(
            listing, original.model_copy(update={"handle": _INVENTED_HANDLE})
        )

        assert outcome.refusal is FetchRefusal.NOT_FOUND

    async def test_a_listing_the_caller_assembled_is_refused(self, fetcher: Fetcher) -> None:
        """A real entry inside a listing carrying a token this fetcher never minted."""
        listing = await fetcher.listing()

        assembled = SourceListing(
            source=listing.source,
            read_at=listing.read_at,
            entries=listing.entries,
            token=_INVENTED_AUTHORITY,
        )

        assert (await fetcher.fetch(assembled, listing.entries[0])).refusal is (
            FetchRefusal.NOT_FOUND
        )

    async def test_an_entry_of_one_listing_carried_on_anothers_token_is_refused(
        self, fetcher: Fetcher
    ) -> None:
        """A handle is bound to the listing that minted it (ADR-0230 §4).

        Both values are authentic and both were minted by this fetcher; what they are
        not is *each other's*. An implementation whose handle is signed over the name
        alone passes every other clause here and fails this one.
        """
        first = await fetcher.listing()
        second = await fetcher.listing()

        carried = second.model_copy(update={"entries": first.entries})

        assert (await fetcher.fetch(carried, first.entries[0])).refusal is FetchRefusal.NOT_FOUND

    @pytest.mark.parametrize("alteration", ["emptied", "shortened", "reordered", "renamed"])
    async def test_an_authentic_token_over_an_altered_listing_is_refused(
        self, fetcher: Fetcher, alteration: str
    ) -> None:
        """The arm that fails any token not committing to the ordered names (§4).

        "Without it, a caller keeping a real ``token`` and replacing ``entries`` with
        ``()``, with a shorter tuple, or with the same entries reordered would present
        a value whose token and handle both verify while the entry it names is not in
        the listing it is presented in — and would satisfy every other clause of this
        section."

        Every arm keeps the listing's own authentic token and its own authentic
        entries; only the sequence changes, which is exactly what the commitment is
        over.
        """
        listing = await _listing_of_at_least(fetcher, 2)
        entry = listing.entries[0]
        altered = {
            "emptied": (),
            "shortened": listing.entries[:1],
            "reordered": tuple(reversed(listing.entries)),
            "renamed": (
                entry.model_copy(update={"name": f"{entry.name}.other"}),
                *listing.entries[1:],
            ),
        }[alteration]

        outcome = await fetcher.fetch(listing.model_copy(update={"entries": altered}), entry)

        assert outcome.refusal is FetchRefusal.NOT_FOUND

    async def test_a_faithful_copy_of_an_authentic_listing_and_entry_is_fetched(
        self, fetcher: Fetcher
    ) -> None:
        """The clause in the other direction, and it is not a concession (§4).

        §4 forbids the fetcher retaining anything, "so a byte-identical copy of a
        ``SourceListing`` and one of its entries is indistinguishable from what was
        minted and no conforming implementation attempts to distinguish them — one
        that did would be deciding from retained object identity, which is the
        counting mechanism this section already rejected".

        The copy is taken through validation from a dump rather than by
        ``model_copy``, so no object here is the one the fetcher returned.
        """
        listing = await fetcher.listing()
        copy = SourceListing.model_validate(listing.model_dump())

        assert_minted(await fetcher.fetch(copy, copy.entries[0]), fetcher.name)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("size_bytes", 999_999), ("modified_at", datetime(2000, 1, 1, tzinfo=UTC))],
    )
    async def test_an_altered_display_field_widens_nothing_and_is_ignored(
        self, fetcher: Fetcher, field: str, value: object
    ) -> None:
        """§4: "the commitment covers the addresses and not the display".

        The arm that fails an implementation deciding from display fields. Neither
        value is consulted by any fetch decision — the file is named by ``name``, and
        the size is decided against the object ``fetch`` opens — so altering one edits
        a rendering that has already happened.
        """
        listing = await fetcher.listing()

        outcome = await fetcher.fetch(listing, listing.entries[0].model_copy(update={field: value}))

        assert_minted(outcome, fetcher.name)

    # --- the two deadlines (ADR-0230 §4) ------------------------------------

    async def test_a_listing_inside_both_deadlines_is_fetched(self) -> None:
        """The positive arm, so the three refusals below are not vacuous."""
        subject = self.clocked()
        listing = await subject.fetcher.listing()
        subject.monotonic.advance(subject.ttl.total_seconds() * 1e9 / 2)
        subject.wall.advance(subject.ttl.total_seconds() / 2)

        assert_minted(
            await subject.fetcher.fetch(listing, listing.entries[0]), subject.fetcher.name
        )

    async def test_a_listing_past_both_deadlines_is_refused(self) -> None:
        """Expiry is ``NOT_FOUND``, the same class an absent file yields (§4)."""
        subject = self.clocked()
        listing = await subject.fetcher.listing()
        subject.monotonic.advance(subject.ttl.total_seconds() * 1e9 + 1)
        subject.wall.advance(subject.ttl.total_seconds() + 1)

        outcome = await subject.fetcher.fetch(listing, listing.entries[0])

        assert outcome.refusal is FetchRefusal.NOT_FOUND

    async def test_a_backward_wall_clock_does_not_extend_a_listing(self) -> None:
        """The arm that fails any implementation deciding expiry from ``read_at`` (§4).

        "A wall clock stepped backwards leaves a listing minted at 12:00 inside a
        five-minute window an hour of real time later, and the signed token stops a
        caller extending the value but nothing stops the producer's own clock
        regressing under it." The monotonic deadline is what closes it.
        """
        subject = self.clocked()
        listing = await subject.fetcher.listing()
        subject.wall.advance(-3600)
        subject.monotonic.advance(subject.ttl.total_seconds() * 1e9 + 1)

        outcome = await subject.fetcher.fetch(listing, listing.entries[0])

        assert outcome.refusal is FetchRefusal.NOT_FOUND

    async def test_a_frozen_monotonic_source_does_not_extend_a_listing(self) -> None:
        """The arm that fails any implementation deciding from a monotonic source alone.

        "The ordinary ``CLOCK_MONOTONIC``-style source does **not** advance while the
        host is suspended, so a host suspended for an hour resumes with a five-minute
        window still open." The wall deadline is what closes it, which is why §4 binds
        both rather than choosing one.
        """
        subject = self.clocked()
        listing = await subject.fetcher.listing()
        subject.wall.advance(subject.ttl.total_seconds() + 1)

        outcome = await subject.fetcher.fetch(listing, listing.entries[0])

        assert outcome.refusal is FetchRefusal.NOT_FOUND

    async def test_producing_further_listings_invalidates_none_of_them(
        self, fetcher: Fetcher
    ) -> None:
        """§4: "No listing is invalidated by the production of another."

        An earlier draft bounded the authority by a window of eight listings, and both
        review lenses found it wrong from opposite sides on the same round: nine turns
        whose listings interleave with their planner calls would evict the first turn's
        listing before its own plan came back. Nine here for that figure's sake.
        """
        listings = [await fetcher.listing() for _ in range(9)]

        for listing in listings:
            assert_minted(await fetcher.fetch(listing, listing.entries[0]), fetcher.name)

    # --- failure posture (ADR-0230 §4) --------------------------------------

    async def test_neither_member_raises_for_a_source_reason(
        self, empty_fetcher: Fetcher, fetcher: Fetcher
    ) -> None:
        """ADR-0230 adds **no** error class, so a refusal is a return value (§4).

        The half a generic suite can decide: a root with nothing in it lists rather
        than raises, and an entry no listing showed refuses rather than raises. That a
        *real* deletion, permission denial, growth or extraction failure reaches each
        class is the concrete fetcher's test (§13).
        """
        assert (await empty_fetcher.listing()).entries == ()

        listing = await fetcher.listing()
        outcome = await fetcher.fetch(listing, _assembled(listing.entries[0]))

        assert outcome.refusal is not None

    async def test_a_cancelled_listing_is_delivered_onward_unchanged(self) -> None:
        """ADR-0060 through this seam: a cancellation is never absorbed (§4).

        Held at the subject's own suspension point and cancelled *there*, because a
        call cancelled before it suspends exercises none of the code that would
        convert one.
        """
        subject = self.gated()
        gate = subject.arm_listing()
        call = asyncio.ensure_future(subject.fetcher.listing())
        await gate.reached()

        call.cancel()
        gate.release()

        with pytest.raises(asyncio.CancelledError):
            await call

    async def test_a_cancelled_fetch_is_delivered_onward_unchanged(self, fetcher: Fetcher) -> None:
        """The same clause on the other member, over an authentic listing.

        The listing is taken from the *gated* subject before the gate is armed, so the
        call under test is the fetch and not the listing that produced its authority.
        """
        subject = self.gated()
        listing = await subject.fetcher.listing()
        gate = subject.arm_fetch()
        call = asyncio.ensure_future(subject.fetcher.fetch(listing, listing.entries[0]))
        await gate.reached()

        call.cancel()
        gate.release()

        with pytest.raises(asyncio.CancelledError):
            await call


async def _listing_of_at_least(fetcher: Fetcher, count: int) -> SourceListing:
    """A listing with at least ``count`` entries, or skip the case that needs one."""
    listing = await fetcher.listing()
    if len(listing.entries) < count:
        pytest.skip(f"this subject's root holds fewer than {count} listable files")
    return listing


def _assembled(model: SourceListingEntry) -> SourceListingEntry:
    """An entry the *test* built, for a file that is plausibly under the root.

    Every field is a value a caller could compose from what it was shown, and the
    handle is one no fetcher minted — which is the whole of what makes it assembled.
    """
    return SourceListingEntry(
        name=f"assembled-{model.name}",
        size_bytes=1,
        modified_at=model.modified_at,
        handle=_INVENTED_HANDLE,
    )

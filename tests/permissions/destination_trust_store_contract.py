"""Shared conformance suite for the DestinationTrustStore Protocol (ADR-0238 §1, §15).

Every ``DestinationTrustStore`` implementation must pass this suite (CONTRIBUTING,
"Adding a Protocol"). A concrete test subclasses
:class:`DestinationTrustStoreContract` and supplies the ``store`` fixture.

**Here rather than under ``tests/core/``**, beside ``recipient_grant_contract.py``:
ADR-0238 §1 builds this store to that one's shape and states its atomicity obligation
by explicit reference to it, and this package is where the durable implementation
sits.

**What ADR-0238 §15's Arm 9 asks for, and it is what this file is.** ``trust_of``
answers ``USER_CHOSEN`` only where every member of the sequence is in one live
record's set; ``UNCHOSEN`` for an empty sequence, a partial match, a match spanning
two records, a revoked record, and where the two sides differ in any field of a
``CanonicalDestination`` or across protocols; ``record`` refuses a duplicate id, an
empty set, a duplicate live set and an ``UNCHOSEN`` record; a record is refused **at
construction** for an empty, repeated-member or non-canonically-ordered destination
tuple; **two concurrent ``record`` calls over equal destination sets admit exactly
one**; ``revoke`` is prospective and idempotent and rewrites no recorded decision; and
``export`` answers revoked records that ``live`` omits.

**Arm 8's half a suite can decide is here too.** "No path from any model output
writes, raises or is consulted about a destination's trust" is a fact about a
*composition* and about a review of the tree, not about a return value — but the half
that is decidable from the seam is that this Protocol's recording member is reached
through a contract holding no model, no supply and no content, and
:meth:`DestinationTrustStoreContract.test_the_recording_member_is_reached_with_a_record_alone`
pins exactly that.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from recipient_builders import ALICE, BOB, account_member, member

from ai_assistant.core.errors import InvalidDestinationTrustError
from ai_assistant.core.protocols import DestinationTrustStore
from ai_assistant.core.types import (
    BoundAccount,
    CanonicalDestination,
    DestinationProtocol,
    DestinationTrust,
    DestinationTrustRecord,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The instant every record here is established at. Fixed, because nothing in this
#: contract reads a clock: ``established_at`` and ``revoked_at`` are the caller's, so
#: a suite that varied them would be testing its own arithmetic.
AT: Final = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

#: A later instant, for the revocations.
LATER: Final = AT + timedelta(hours=1)

#: A third address, so the partial-match and spanning cases have somewhere to differ.
CAROL: Final = "carol@example.com"


def canonical(*addresses: str) -> tuple[CanonicalDestination, ...]:
    """``addresses`` as a destination tuple in the one canonical order.

    Sorted here rather than written out in order at each call, because the *ordering*
    rule is what one case below is about and every other case would be asserting it by
    accident — a fixture that happened to be out of order would fail cases that have
    nothing to say about order.
    """
    return tuple(sorted((member(address) for address in addresses), key=_key))


def _key(destination: CanonicalDestination) -> tuple[int, str, str]:
    """``EgressBinding.canonical_destination_set``'s order, over selected recipients."""
    if destination.account is not None:
        return (0, destination.account.reference, destination.account.identity)
    protocol = destination.protocol.value if destination.protocol is not None else ""
    return (1, protocol, destination.canonical or "")


def trust_record(
    *addresses: str,
    record_id: str = "t-1",
    established_at: datetime = AT,
    destinations: Sequence[CanonicalDestination] | None = None,
) -> DestinationTrustRecord:
    """A granting record over ``addresses``, or over ``destinations`` if given."""
    return DestinationTrustRecord(
        id=record_id,
        destinations=tuple(destinations) if destinations is not None else canonical(*addresses),
        trust=DestinationTrust.USER_CHOSEN,
        established_at=established_at,
    )


async def _refuses(store: DestinationTrustStore, record: DestinationTrustRecord) -> None:
    """Assert ``store`` refuses ``record``, and that the refusal appended nothing.

    Both halves, because a store that refused *and* appended would pass an assertion
    over the exception alone — and what §1's refusals are for is precisely the row that
    should not be there. Counted rather than checked by id, because the duplicate-id
    case is refusing a record whose id the store legitimately already holds.
    """
    before = len(await store.export())

    with pytest.raises(InvalidDestinationTrustError):
        await store.record(record)

    assert len(await store.export()) == before


class DestinationTrustStoreContract:
    """Behaviour every ``DestinationTrustStore`` must exhibit (ADR-0238 §1)."""

    @pytest.fixture
    def store(self) -> DestinationTrustStore:
        """Override in a subclass with a **fresh, empty** conforming subject."""
        raise NotImplementedError

    def reopened(self, store: DestinationTrustStore) -> DestinationTrustStore:
        """Override to return **this store's history** through a second handle.

        What a deployment gets after a restart, and what a fake gets from a second
        object over one shared log. It is a hook rather than a constructor call
        because "the same history" means a file for a durable store and a shared list
        for a fake, and the clause it serves — that what was recorded is *durable*
        rather than merely remembered — is unreachable without it.
        """
        raise NotImplementedError

    def concurrently_openable(self) -> bool:
        """Whether this implementation can be opened twice over one history.

        Override with ``False`` where it cannot; the cross-handle case then skips, as
        the ledger contracts already do for the same reason.
        """
        return True

    def test_conforms_to_the_protocol(self, store: DestinationTrustStore) -> None:
        assert isinstance(store, DestinationTrustStore)

    # --- §1: absence, and what it reads as ---------------------------------

    async def test_an_empty_store_reads_unchosen(self, store: DestinationTrustStore) -> None:
        """The fail-closed direction, and the state in which the rule would be false.

        ADR-0238 §1 states it as ADR-0146 §2 states its own — "a span for which no
        origin was recorded is **system-selected**" — for the same reason: the
        permissive default is what makes an unimplemented path work, so a store that
        answered ``USER_CHOSEN`` for a destination nobody chose would be wrong exactly
        where nobody would notice.
        """
        assert await store.trust_of([member(ALICE)]) is DestinationTrust.UNCHOSEN
        assert await store.live() == []
        assert await store.export() == []

    async def test_an_empty_sequence_reads_unchosen(self, store: DestinationTrustStore) -> None:
        """§1 names the empty sequence explicitly, and a vacuous ``all`` would not.

        "``USER_CHOSEN`` only where **every** member of the sequence it was given is a
        member of some one live record's ``destinations``" is vacuously true of no
        members at all, so an implementation writing the rule the obvious way answers
        ``USER_CHOSEN`` for a request naming nobody. §1 rules it ``UNCHOSEN``, and this
        is the case that separates the two readings.
        """
        await store.record(trust_record(ALICE))

        assert await store.trust_of([]) is DestinationTrust.UNCHOSEN

    # --- §1: what coverage is, and what it is not --------------------------

    async def test_a_live_record_covers_every_member_it_names(
        self, store: DestinationTrustStore
    ) -> None:
        """Coverage is membership, and the query's order is immaterial (§1).

        ``trust_of``'s rule is membership rather than order — "no clause here
        re-canonicalises a caller's query sequence" — so the reversed sequence must
        answer as the canonical one does.
        """
        await store.record(trust_record(ALICE, BOB))

        assert await store.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN
        assert await store.trust_of([member(ALICE), member(BOB)]) is DestinationTrust.USER_CHOSEN
        assert await store.trust_of([member(BOB), member(ALICE)]) is DestinationTrust.USER_CHOSEN

    async def test_a_partial_match_reads_unchosen(self, store: DestinationTrustStore) -> None:
        """Every member, or nothing: a set half-covered is not a set the user chose."""
        await store.record(trust_record(ALICE, BOB))

        assert await store.trust_of([member(ALICE), member(CAROL)]) is DestinationTrust.UNCHOSEN

    async def test_a_match_spanning_two_records_reads_unchosen(
        self, store: DestinationTrustStore
    ) -> None:
        """ "**some one** live record's ``destinations``", and the word is load-bearing.

        Two records the user made about two parties are not one record about both.
        An implementation folding the live sets into a union passes every other case
        here and fails this one, which is why §15's Arm 9 names it.
        """
        await store.record(trust_record(ALICE, record_id="t-1"))
        await store.record(trust_record(BOB, record_id="t-2"))

        assert await store.trust_of([member(ALICE), member(BOB)]) is DestinationTrust.UNCHOSEN
        assert await store.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN

    async def test_a_member_differing_in_any_field_is_not_covered(
        self, store: DestinationTrustStore
    ) -> None:
        """ "every field, never across protocols" — §1's no-inference clause (ADR-0193 §3).

        The three ways an implementation reaches for a looser comparison, each pinned:
        a different address, the same address under a different protocol, and a
        case-folded spelling. **Coverage is a comparison of recorded values and is
        never an inference**: no implementation folds case, matches a domain, or
        relates the two sets by anything but membership.
        """
        await store.record(trust_record(ALICE))

        assert await store.trust_of([member(CAROL)]) is DestinationTrust.UNCHOSEN
        assert (
            await store.trust_of(
                [CanonicalDestination(protocol=DestinationProtocol.HTTPS, canonical=ALICE)]
            )
            is DestinationTrust.UNCHOSEN
        )
        assert await store.trust_of([member(ALICE.upper())]) is DestinationTrust.UNCHOSEN

    async def test_an_account_member_does_not_cover_a_recipient_member(
        self, store: DestinationTrustStore
    ) -> None:
        """§1: no implementation "treats an account member as covering a recipient member
        or the reverse".

        The two member shapes of a canonical destination set are different values, and
        a store relating them would authorise a payload for a party the user never
        named on the strength of the account it would go through.
        """
        account = BoundAccount(identity=ALICE, reference="conn-0001")
        await store.record(trust_record(destinations=(account_member(account),)))

        assert await store.trust_of([account_member(account)]) is DestinationTrust.USER_CHOSEN
        assert await store.trust_of([member(ALICE)]) is DestinationTrust.UNCHOSEN

    # --- §1: what `record` refuses -----------------------------------------

    async def test_a_recorded_act_comes_back_under_its_own_id(
        self, store: DestinationTrustStore
    ) -> None:
        """The id is the **caller's**, minted before the call (ADR-0193 §1's shape).

        That is what makes the store's duplicate refusal "a comparison rather than an
        allocation" (§1): the record is a complete value before it arrives.
        """
        assert await store.record(trust_record(ALICE, record_id="t-9")) == "t-9"
        assert [held.id for held in await store.live()] == ["t-9"]

    async def test_recording_a_known_id_is_refused_rather_than_upserted(
        self, store: DestinationTrustStore
    ) -> None:
        """A store that upserts is one where a user's decision can be rewritten."""
        await store.record(trust_record(ALICE, record_id="t-1"))

        await _refuses(store, trust_record(CAROL, record_id="t-1"))

        held = await store.live()
        assert [record.destinations for record in held] == [canonical(ALICE)]

    async def test_a_record_duplicating_a_live_destination_set_is_refused(
        self, store: DestinationTrustStore
    ) -> None:
        """§1's own reason: "revoking one would leave the other standing".

        The user's revocation of the record they were shown would leave the twin
        standing with the destination still reading ``USER_CHOSEN`` — which would make
        §1's revocation clause false of the *store* rather than of any one record.
        """
        await store.record(trust_record(ALICE, BOB, record_id="t-1"))

        await _refuses(store, trust_record(ALICE, BOB, record_id="t-2"))

    async def test_a_record_over_a_different_destination_set_is_admitted(
        self, store: DestinationTrustStore
    ) -> None:
        """Overlapping sets are two things a user may reasonably have said.

        What is refused is a second record that **is** the first, not one that shares a
        member with it — so a store refusing on overlap would refuse an act the user is
        entitled to make.
        """
        await store.record(trust_record(ALICE, record_id="t-1"))

        await store.record(trust_record(ALICE, BOB, record_id="t-2"))

        assert {held.id for held in await store.live()} == {"t-1", "t-2"}

    async def test_a_reordered_twin_cannot_defeat_the_duplicate_refusal(
        self, store: DestinationTrustStore
    ) -> None:
        """§15's Arm 9: ``(Bob, Alice)`` where ``(Alice, Bob)`` is the canonical spelling.

        Refused **at construction** rather than by the store, which is the point:
        pinning one spelling on the record is what lets the store's duplicate rule be
        written as tuple equality and still mean set equality. Without it the two
        would be unequal tuples over one logical set, both admitted as live, and
        revoking one would leave the other standing.
        """
        await store.record(trust_record(ALICE, BOB, record_id="t-1"))
        reordered = tuple(reversed(canonical(ALICE, BOB)))

        with pytest.raises(ValueError, match="canonical order"):
            trust_record(record_id="t-2", destinations=reordered)

    async def test_an_empty_or_repeating_destination_set_is_refused_at_construction(
        self,
    ) -> None:
        """The other two halves of §15's Arm 9's construction clause.

        Both refused on the record rather than in the store, so no producer, decode,
        test double or later lane can build one — the discipline
        :class:`~ai_assistant.core.types.Placement` and ``QueryOutcome`` already carry.
        """
        with pytest.raises(ValueError, match="at least one canonical destination"):
            trust_record(destinations=())
        with pytest.raises(ValueError, match="once"):
            trust_record(destinations=(member(ALICE), member(ALICE)))

    async def test_an_unchosen_record_is_refused_at_construction(self) -> None:
        """``UNCHOSEN`` is what absence means, so a record asserting it is nothing twice.

        Two spellings of one state is the shape ADR-0217 §1's refusal table exists to
        prevent, and refusing it on the type is what keeps this store from ever having
        to decide which of the two an absent-and-present destination is.
        """
        with pytest.raises(ValueError, match="UNCHOSEN"):
            DestinationTrustRecord(
                id="t-1",
                destinations=canonical(ALICE),
                trust=DestinationTrust.UNCHOSEN,
                established_at=AT,
            )

    async def test_two_records_over_equal_sets_recorded_at_once_leave_exactly_one(
        self, store: DestinationTrustStore
    ) -> None:
        """The check and the append are **one operation** (§1).

        A sequential case cannot reach it.

        ADR-0021 §4's atomicity argument: "the system composes on one event loop" is
        precisely the setting in which an ``await`` between a check and a write is an
        interleaving point. An implementation that reads, compares and writes as three
        awaits admits both here — and §1 says what that costs, which is that the user's
        revocation of the record they were shown revokes nothing.
        """
        outcomes = await asyncio.gather(
            store.record(trust_record(ALICE, record_id="t-1")),
            store.record(trust_record(ALICE, record_id="t-2")),
            return_exceptions=True,
        )

        assert sum(1 for outcome in outcomes if isinstance(outcome, str)) == 1
        assert len(await store.live()) == 1

    # --- §1: revocation ----------------------------------------------------

    async def test_a_revoked_record_reads_unchosen_and_leaves_live(
        self, store: DestinationTrustStore
    ) -> None:
        """ "a destination whose record is revoked reads ``UNCHOSEN`` from that moment"."""
        await store.record(trust_record(ALICE, record_id="t-1"))

        await store.revoke("t-1", LATER)

        assert await store.trust_of([member(ALICE)]) is DestinationTrust.UNCHOSEN
        assert await store.live() == []

    async def test_a_revocation_rewrites_no_recorded_decision(
        self, store: DestinationTrustStore
    ) -> None:
        """§1: prospective, and the record is otherwise untouched.

        Every field but ``revoked_at`` comes back as it was recorded — which is what
        makes the export a record of *what the user did* rather than of what the store
        currently thinks.
        """
        recorded = trust_record(ALICE, BOB, record_id="t-1")
        await store.record(recorded)

        await store.revoke("t-1", LATER)

        (kept,) = await store.export()
        assert kept == recorded.model_copy(update={"revoked_at": LATER})

    async def test_revoking_twice_is_a_no_op_that_keeps_the_first_instant(
        self, store: DestinationTrustStore
    ) -> None:
        """Idempotent (§1), and idempotent **without restamping**.

        A second call that moved the instant would rewrite a recorded decision, which
        is the one thing §1 says a revocation never does — and would make a repeated
        sweep change the user's history.
        """
        await store.record(trust_record(ALICE, record_id="t-1"))
        await store.revoke("t-1", LATER)

        await store.revoke("t-1", LATER + timedelta(days=7))

        (kept,) = await store.export()
        assert kept.revoked_at == LATER

    async def test_revoking_an_unknown_id_is_refused(self, store: DestinationTrustStore) -> None:
        """§1: "refusing an unknown id by the same error".

        Refused rather than ignored, because a revocation that silently did nothing
        would report success to a user who believed they had withdrawn something.
        """
        with pytest.raises(InvalidDestinationTrustError):
            await store.revoke("t-nope", LATER)

    async def test_a_set_may_be_recorded_again_once_the_first_is_revoked(
        self, store: DestinationTrustStore
    ) -> None:
        """The other side of the duplicate rule: re-choosing is revoke-then-record.

        The refusal is over the **live** set, so a revoked record blocks nothing — and
        both are kept, because the export is the user's history rather than their
        current state.
        """
        await store.record(trust_record(ALICE, record_id="t-1"))
        await store.revoke("t-1", LATER)

        await store.record(trust_record(ALICE, record_id="t-2"))

        assert [held.id for held in await store.live()] == ["t-2"]
        assert {held.id for held in await store.export()} == {"t-1", "t-2"}

    # --- §1: the two reads, and why neither stands in for the other --------

    async def test_export_answers_revoked_records_that_live_omits(
        self, store: DestinationTrustStore
    ) -> None:
        """§1: "``export`` exists because the data right does" (ADR-0004 §6).

        A revoked record is the evidence that the user once permitted a destination
        and then withdrew it, which is exactly what an audit of one's own decisions is
        for. An implementation delegating ``export`` to ``live`` passes every other
        case in this file and silently drops that evidence.
        """
        await store.record(trust_record(ALICE, record_id="t-1"))
        await store.record(trust_record(BOB, record_id="t-2"))
        await store.revoke("t-1", LATER)

        assert [held.id for held in await store.live()] == ["t-2"]
        assert {held.id for held in await store.export()} == {"t-1", "t-2"}

    async def test_both_reads_are_ordered_newest_act_first_with_an_id_tie_break(
        self, store: DestinationTrustStore
    ) -> None:
        """§1's order, and the tie-break is what makes it total.

        "Newest first" is ambiguous between insertion order and act time, which
        disagree whenever records are appended out of order — so the older act is
        recorded *first* here, and an implementation ordering by insertion fails.
        """
        await store.record(trust_record(CAROL, record_id="t-old", established_at=AT))
        await store.record(trust_record(ALICE, record_id="t-b", established_at=LATER))
        await store.record(trust_record(BOB, record_id="t-a", established_at=LATER))

        assert [held.id for held in await store.live()] == ["t-a", "t-b", "t-old"]
        assert [held.id for held in await store.export()] == ["t-a", "t-b", "t-old"]

    async def test_a_read_hands_back_nothing_the_store_keeps(
        self, store: DestinationTrustStore
    ) -> None:
        """Detachment, asserted where it is reachable: two reads share no object.

        A store handing back its own record would let a caller rewrite an
        authorisation through ``__dict__`` — which ``frozen=True`` does not stop and
        which §1's "detached, validated snapshot" is stated against.
        """
        await store.record(trust_record(ALICE, record_id="t-1"))

        (first,) = await store.live()
        (second,) = await store.live()

        assert first == second
        assert first is not second
        assert first.destinations[0] is not second.destinations[0]

    # --- §1: durability, and the model's distance from the fact ------------

    @pytest.mark.optional_obligation
    async def test_a_second_handle_over_one_history_reads_what_was_recorded(
        self, store: DestinationTrustStore
    ) -> None:
        """§1: the store is **durable**, so a record outlives the handle that wrote it.

        The clause is what makes a user's act mean anything at all — a store that
        forgot on restart would leave every destination reading ``UNCHOSEN`` after the
        next start, which fails safe but delivers nothing.
        """
        if not self.concurrently_openable():
            pytest.skip("this implementation cannot be opened twice over one history")
        await store.record(trust_record(ALICE, record_id="t-1"))

        second = self.reopened(store)

        assert [held.id for held in await second.live()] == ["t-1"]
        assert await second.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN

    def test_the_recording_member_is_reached_with_a_record_alone(
        self, store: DestinationTrustStore
    ) -> None:
        """ADR-0238 §15's Arm 8, in the half a conformance suite can decide.

        "No path from any model output writes, raises or is consulted about a
        destination's trust" is a claim about a composition and a review of the tree.
        What a suite *can* pin is that this seam offers no route for one: ``record``
        takes a ``DestinationTrustRecord`` and nothing else — no model, no supply, no
        completion, no content and no judgement — so a component holding a
        ``ModelProvider`` has nothing it could hand this store that a model produced.
        The whole of what a record carries is a destination set, a trust, and two
        instants, and its ``trust`` admits exactly one value.
        """
        import inspect  # noqa: PLC0415 — asserted about, not used by the module

        parameters = [
            parameter
            for name, parameter in inspect.signature(type(store).record).parameters.items()
            if name != "self"
        ]

        assert len(parameters) == 1
        assert set(DestinationTrustRecord.model_fields) == {
            "id",
            "destinations",
            "trust",
            "established_at",
            "revoked_at",
        }

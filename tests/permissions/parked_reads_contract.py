"""Shared conformance suite for the ``ParkedReads`` Protocol (ADR-0244 §3, §18, §19).

Every ``ParkedReads`` implementation must pass this suite (``CONTRIBUTING.md`` →
"Adding a Protocol"). A concrete test subclasses :class:`ParkedReadsContract` and
supplies the ``store`` fixture.

**Here rather than under ``tests/core/``**, beside ``destination_trust_store_contract.py``
and ``recipient_grant_contract.py``: ADR-0244 §3 puts the durable implementation in
``permissions/`` — "for the reason ``SqliteSourceReadTrail`` is already there", since a
park is the unanswered half of a recorded permission question — and this package is
where that implementation sits.

**What ADR-0244 §18 asks this file to state, clause by clause.** §3's atomicity; its
one-open-park-per-conversation rule; its one-park-per-decision rule and
``park_of_decision``'s answer **across every disposition**; its settle-once answer; its
content-clearing settlement; §2's open-and-terminal shapes; and
``drop_for_conversation``'s semantics. §19's **Arm 9** is the same list read as a test
plan — "two concurrent ``park`` calls for one conversation yield exactly one park; two
concurrent ``settle`` calls for one park yield exactly one ``True``; a ``settle`` clears
the three content fields in the same step that moves the disposition; and
``drop_for_conversation`` removes open and terminal rows alike and answers ``0`` the
second time" — and that arm is one of the three ADR-0244 §19 names as the ones "this
decision would be worthless without".

**What is deliberately not here, and ADR-0244 §18 says so in terms.** Four of this
decision's rulings "are deliberately not suite clauses, and putting them there would be
the error": that no model call precedes a dispatch, that the value sent is the park's
own ``parameters``, that no adapter reads a store, and that the composition root wires
one instance. "A generic conformance suite cannot see a wiring or the absence of a
call"; each is a property of a call site and is asserted by a representative test where
that site is.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from ai_assistant.core.protocols import ParkedReads
from ai_assistant.core.types import (
    ActionPlan,
    FrozenJsonMapping,
    Goal,
    MemorySource,
    ParkedRead,
    ParkedReadDisposition,
    Provenance,
)

#: The instant every park here is written at. Fixed, because nothing in this contract
#: reads a clock: ``parked_at``, ``expires_at`` and ``settle``'s ``at`` are all the
#: caller's, so a suite that varied them would be testing its own arithmetic.
AT: Final = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

#: A later instant, for the settlements.
LATER: Final = AT + timedelta(hours=1)

#: ADR-0244 §3's deadline, as these cases carry it. The store takes no view of it —
#: settling an expired park is the engine's (§5) — so this is a value the rows carry
#: rather than a behaviour the suite drives.
EXPIRES_AT: Final = AT + timedelta(hours=24)

#: The three fields ADR-0244 §3's settlement clears. Named once, so the clause and the
#: assertion about it cannot come apart.
CONTENT: Final = ("parameters", "goal", "plan")

#: The four terminal members, so the settle cases range over every one of them rather
#: than over the author's favourite.
TERMINAL: Final = (
    ParkedReadDisposition.APPROVED,
    ParkedReadDisposition.DENIED,
    ParkedReadDisposition.CANCELLED,
    ParkedReadDisposition.EXPIRED,
)


def goal(statement: str = "what is that bell tower in Porto") -> Goal:
    """The objective a parked turn was planned against (ADR-0244 §2)."""
    return Goal(
        id="goal-1",
        statement=statement,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )


def plan() -> ActionPlan:
    """The plan the planner returned on the parked turn (ADR-0244 §2)."""
    return ActionPlan(
        id="plan-1",
        goal_id="goal-1",
        steps=(),
        created_at=AT,
        rationale="answer from what is already here, and look the tower up",
    )


def park(  # noqa: PLR0913 — one keyword per field a case varies, and each varies for a different clause; a builder bundling them would hide which clause a case is about
    *,
    park_id: str = "park-1",
    conversation_id: str = "conv-1",
    decision_id: str = "decision-1",
    parameters: FrozenJsonMapping | None = None,
    parked_at: datetime = AT,
    expires_at: datetime = EXPIRES_AT,
) -> ParkedRead:
    """An ``OPEN`` park, with the three content fields present (ADR-0244 §2)."""
    return ParkedRead(
        id=park_id,
        conversation_id=conversation_id,
        decision_id=decision_id,
        parameters=(
            {"origin": "search.example", "query": "bell tower porto"}
            if parameters is None
            else parameters
        ),
        goal=goal(),
        plan=plan(),
        parked_at=parked_at,
        expires_at=expires_at,
        disposition=ParkedReadDisposition.OPEN,
    )


class ParkedReadsContract:
    """Behaviour every ``ParkedReads`` implementation must exhibit (ADR-0244 §3)."""

    @pytest.fixture
    def store(self) -> ParkedReads:
        """Override in a subclass with a **fresh, empty** conforming subject."""
        raise NotImplementedError

    def test_conforms_to_the_protocol(self, store: ParkedReads) -> None:
        assert isinstance(store, ParkedReads)

    # --- §2: the two shapes a record may have ------------------------------

    def test_an_open_park_missing_its_content_is_refused_at_construction(self) -> None:
        """ADR-0244 §2's validator, in the direction a lane would reach by omission.

        The type is what expresses the two shapes rather than a rule to remember, and a
        park with nothing to dispatch is not one a user can answer.
        """
        for field in CONTENT:
            with pytest.raises(ValueError, match="open park carries its question"):
                park().model_copy(update={field: None}).model_validate(
                    {**park().model_dump(), field: None}
                )

    @pytest.mark.parametrize("disposition", TERMINAL)
    def test_a_terminal_park_carrying_content_is_refused_at_construction(
        self, disposition: ParkedReadDisposition
    ) -> None:
        """ADR-0244 §2's validator, in the other direction, over every terminal member.

        "A terminal park read back with its query intact would breach the retention rule
        in the one place a reader would not look."
        """
        record = park().model_dump()
        record["disposition"] = disposition

        with pytest.raises(ValueError, match="content cleared"):
            ParkedRead.model_validate(record)

    # --- §3: park, and the two rules it enforces ---------------------------

    async def test_a_written_park_is_read_back_by_id(self, store: ParkedReads) -> None:
        """The ordinary case, and the one every other case rests on."""
        assert await store.park(park()) is True

        held = await store.get("park-1")

        assert held is not None
        assert held.decision_id == "decision-1"
        assert held.disposition is ParkedReadDisposition.OPEN
        assert held.goal is not None
        assert held.plan is not None
        assert held.parameters == {"origin": "search.example", "query": "bell tower porto"}

    async def test_an_unknown_id_reads_none(self, store: ParkedReads) -> None:
        """``get`` answers ``None`` rather than raising for an id nothing holds."""
        assert await store.get("park-nobody-wrote") is None

    async def test_a_second_open_park_for_one_conversation_is_refused(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §3: **a conversation holds at most one ``OPEN`` park.**

        The enforcement is the **store's** rather than a caller's, for ``admit_search``'s
        own reason (ADR-0238 §8): two turns of one conversation, two servicings of one
        turn, and two engines over one data directory can none of them be admitted
        against the same conversation's park.

        **Refused by an answer and not by a raise**, because ADR-0244 §1's third clause
        is written over that answer: a servicing whose ``park`` answered ``False`` has
        written no park, and the turn is told what it is told today.
        """
        assert await store.park(park()) is True

        second = await store.park(park(park_id="park-2", decision_id="decision-2"))

        assert second is False
        assert await store.get("park-2") is None
        assert await store.open_park("conv-1") is not None

    async def test_another_conversation_may_hold_its_own_open_park(
        self, store: ParkedReads
    ) -> None:
        """The rule is per **conversation**, and a store that made it global would strand
        every other conversation's next search behind one unanswered question."""
        assert await store.park(park()) is True

        assert (
            await store.park(
                park(park_id="park-2", conversation_id="conv-2", decision_id="decision-2")
            )
            is True
        )

        assert (await store.open_park("conv-1")).id == "park-1"  # type: ignore[union-attr]
        assert (await store.open_park("conv-2")).id == "park-2"  # type: ignore[union-attr]

    async def test_a_settled_park_frees_the_conversations_one_slot(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §11: "a cancelled park frees the conversation's one open-park slot".

        Stated over a settlement rather than over a cancellation, because the clause is
        the store's and every terminal member reaches it.
        """
        await store.park(park())
        await store.settle("park-1", disposition=ParkedReadDisposition.CANCELLED, at=LATER)

        assert await store.park(park(park_id="park-2", decision_id="decision-2")) is True
        assert await store.open_park("conv-1") is not None

    async def test_a_second_park_naming_one_decision_is_refused(self, store: ParkedReads) -> None:
        """ADR-0244 §3: **one park names one decision.**

        What makes :meth:`ParkedReads.park_of_decision` a single answer rather than a
        listing. Driven from a *second conversation*, so the one-open-park rule cannot
        be what refuses it — which is the arm that separates the two clauses.
        """
        assert await store.park(park()) is True

        second = await store.park(park(park_id="park-2", conversation_id="conv-2"))

        assert second is False
        assert await store.get("park-2") is None

    async def test_two_parks_for_one_conversation_written_at_once_leave_exactly_one(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §19's Arm 9, first clause: **the read and the write are one step.**

        A sequential case cannot reach it. ADR-0021 §4's atomicity argument: "the system
        composes on one event loop" is precisely the setting in which an ``await``
        between a check and a write is an interleaving point. An implementation that
        reads, compares and writes as three awaits admits both — and what that costs is
        a user holding two questions where the store promised one.
        """
        outcomes = await asyncio.gather(
            store.park(park(park_id="park-1", decision_id="decision-1")),
            store.park(park(park_id="park-2", decision_id="decision-2")),
        )

        assert sum(1 for outcome in outcomes if outcome) == 1
        held = [row for row in (await store.get("park-1"), await store.get("park-2")) if row]
        assert len(held) == 1

    async def test_an_open_park_is_read_back_by_conversation(self, store: ParkedReads) -> None:
        """``open_park`` answers this conversation's open park, and ``None`` otherwise."""
        assert await store.open_park("conv-1") is None

        await store.park(park())

        assert (await store.open_park("conv-1")).id == "park-1"  # type: ignore[union-attr]
        assert await store.open_park("conv-2") is None

    async def test_a_settled_park_is_not_this_conversations_open_park(
        self, store: ParkedReads
    ) -> None:
        """``open_park`` is stated over the disposition, not over the row's existence."""
        await store.park(park())
        await store.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=LATER)

        assert await store.open_park("conv-1") is None

    # --- §3: park_of_decision, across every disposition --------------------

    @pytest.mark.parametrize("disposition", TERMINAL)
    async def test_park_of_decision_answers_whatever_its_disposition(
        self, store: ParkedReads, disposition: ParkedReadDisposition
    ) -> None:
        """ADR-0244 §3, §5: it answers the park naming that decision **whatever its
        disposition**, and §19's Arm 14 is why that matters.

        It is what §5's eighth ``grantable_decisions`` condition is decided from, and the
        condition is stated over three dispositions rather than over an open park — so a
        member answering only an open one would let the establishing act resolve a
        decision whose park had just taken the user's answer.
        """
        await store.park(park())
        await store.settle("park-1", disposition=disposition, at=LATER)

        held = await store.park_of_decision("decision-1")

        assert held is not None
        assert held.id == "park-1"
        assert held.disposition is disposition

    async def test_park_of_decision_answers_none_where_no_park_names_it(
        self, store: ParkedReads
    ) -> None:
        """The other half, and the state every unparked ``CONFIRM`` is in."""
        await store.park(park())

        assert await store.park_of_decision("decision-nobody-parked") is None

    # --- §3: outstanding ---------------------------------------------------

    async def test_outstanding_lists_every_open_park_in_parked_at_order(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §3: "every ``OPEN`` park, in ``parked_at`` order", for §5's enumeration."""
        await store.park(
            park(
                park_id="park-2",
                conversation_id="conv-2",
                decision_id="decision-2",
                parked_at=AT + timedelta(minutes=5),
            )
        )
        await store.park(park())

        assert [held.id for held in await store.outstanding()] == ["park-1", "park-2"]

    async def test_outstanding_omits_a_settled_park(self, store: ParkedReads) -> None:
        """Settled is not outstanding, whichever terminal member it reached."""
        await store.park(park())
        await store.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)

        assert await store.outstanding() == ()

    async def test_outstanding_lists_an_expired_park_because_the_store_reads_no_clock(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §5 puts the expiry settlement **at the read**, in the engine.

        A store that took a view of the clock would be deciding a lifetime it does not
        own — and the enumeration that settles an expired park rather than offering it
        is the engine's, so this member reports what is ``OPEN`` and nothing more.
        """
        await store.park(park(expires_at=AT - timedelta(seconds=1)))

        assert [held.id for held in await store.outstanding()] == ["park-1"]

    # --- §3: settle, the resolve-once gate ---------------------------------

    @pytest.mark.parametrize("disposition", TERMINAL)
    async def test_settle_moves_an_open_park_and_clears_its_content(
        self, store: ParkedReads, disposition: ParkedReadDisposition
    ) -> None:
        """ADR-0244 §19's Arm 9, third clause: **cleared in the same step that moves it.**

        And §3's terminal facts survive: ``id``, ``conversation_id``, ``decision_id``,
        ``parked_at``, ``expires_at`` and ``disposition``. "The content lives exactly as
        long as the question does", which is the whole of the retention rule this
        decision states.
        """
        original = park()
        await store.park(original)

        assert await store.settle("park-1", disposition=disposition, at=LATER) is True

        held = await store.get("park-1")
        assert held is not None
        assert held.disposition is disposition
        assert all(getattr(held, field) is None for field in CONTENT)
        assert held.id == original.id
        assert held.conversation_id == original.conversation_id
        assert held.decision_id == original.decision_id
        assert held.parked_at == original.parked_at
        assert held.expires_at == original.expires_at

    async def test_settle_on_an_already_terminal_park_answers_false_and_changes_nothing(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §3: "``settle`` on an already-terminal park answers ``False`` and
        changes nothing", and **no transition leaves a terminal member** (§2)."""
        await store.park(park())
        await store.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=LATER)

        assert (
            await store.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)
            is False
        )

        held = await store.get("park-1")
        assert held is not None
        assert held.disposition is ParkedReadDisposition.DENIED

    async def test_settle_on_an_unknown_id_answers_false(self, store: ParkedReads) -> None:
        """An answer rather than a raise, on the member every caller gates its act behind."""
        assert (
            await store.settle(
                "park-nobody-wrote", disposition=ParkedReadDisposition.APPROVED, at=LATER
            )
            is False
        )

    async def test_settle_refuses_to_move_a_park_back_to_open(self, store: ParkedReads) -> None:
        """``OPEN`` is not a settlement, and ADR-0244 §2 admits no transition out of a
        terminal member — so there is no spelling for re-opening a spent question."""
        await store.park(park())

        with pytest.raises(ValueError, match="terminal"):
            await store.settle("park-1", disposition=ParkedReadDisposition.OPEN, at=LATER)

    async def test_two_settlements_of_one_park_at_once_yield_exactly_one_true(
        self, store: ParkedReads
    ) -> None:
        """ADR-0244 §19's Arm 9, second clause — and one of the three arms §19 names as
        the ones "this decision would be worthless without".

        **The gate.** "A caller answered ``False`` has not taken the park's one answer:
        it rules nothing, records nothing, sends nothing." That is what makes "one
        answer, at most one dispatch" a property of one atomic write rather than of an
        agreement between several readers — and a sequential case cannot reach it.
        """
        await store.park(park())

        outcomes = await asyncio.gather(
            store.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER),
            store.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=LATER),
        )

        assert sum(1 for outcome in outcomes if outcome) == 1
        held = await store.get("park-1")
        assert held is not None
        assert held.disposition in {
            ParkedReadDisposition.APPROVED,
            ParkedReadDisposition.DENIED,
        }
        assert all(getattr(held, field) is None for field in CONTENT)

    # --- §3: drop_for_conversation -----------------------------------------

    async def test_drop_removes_open_and_terminal_rows_alike(self, store: ParkedReads) -> None:
        """ADR-0244 §19's Arm 9, fourth clause, and §3's one destructive member.

        The conversation deletion sequence's route, which removes "**every** park of that
        conversation, open or terminal, content and terminal facts alike".
        """
        await store.park(park())
        await store.settle("park-1", disposition=ParkedReadDisposition.EXPIRED, at=LATER)
        await store.park(park(park_id="park-2", decision_id="decision-2"))
        await store.park(park(park_id="park-3", conversation_id="conv-2", decision_id="decision-3"))

        assert await store.drop_for_conversation("conv-1") == 2

        assert await store.get("park-1") is None
        assert await store.get("park-2") is None
        assert await store.park_of_decision("decision-1") is None
        assert (await store.get("park-3")) is not None, "another conversation is untouched"

    async def test_drop_is_idempotent(self, store: ParkedReads) -> None:
        """ADR-0244 §3: "a second call answers ``0``"."""
        await store.park(park())

        assert await store.drop_for_conversation("conv-1") == 1
        assert await store.drop_for_conversation("conv-1") == 0

    async def test_drop_for_an_unknown_conversation_answers_zero(self, store: ParkedReads) -> None:
        """The deletion sequence runs for every conversation, most of which parked nothing."""
        assert await store.drop_for_conversation("conv-nobody-used") == 0

    # --- detachment --------------------------------------------------------

    async def test_what_is_handed_back_is_not_what_is_held(self, store: ParkedReads) -> None:
        """A caller that mutated a returned record has changed nothing about the store.

        The detachment obligation every store on this surface holds, and the one that
        bites hardest here: a park's ``goal`` and ``plan`` are models whose own members a
        caller could otherwise reach.
        """
        await store.park(park())

        first = await store.get("park-1")
        second = await store.get("park-1")

        assert first == second
        assert first is not second
        assert first is not None
        assert second is not None
        assert first.goal is not second.goal
        assert first.plan is not second.plan

"""The canonical ``ParkedReads`` fake, through the shared suite (ADR-0244 §3, §18).

The triad's binding: without a ``Test…Contract`` subclass the abstract suite collects
nothing and the fake is unverified however many files exist (``CONTRIBUTING.md`` →
"Adding a Protocol"). Plus the arms that are about *this* subject rather than about the
contract — the scripted faults, and the seeded history.

**Why the fake is held to the same clauses the durable store will be.** ADR-0026 §7: a
fake looser than the contract certifies consumers the real implementation rejects. The
one that bites hardest here is the settlement's content-clearing, because a fake that
kept the query would let a consumer read a spent park's question back — the one thing
ADR-0244 §3's retention rule exists to make unreachable.
"""

from __future__ import annotations

import pytest
from parked_reads_contract import AT, LATER, ParkedReadsContract, park

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import ParkedReadDisposition
from ai_assistant.testing import FakeParkedReads


class TestFakeParkedReadsContract(ParkedReadsContract):
    """The canonical fake against every clause of ADR-0244 §3."""

    @pytest.fixture
    def store(self) -> FakeParkedReads:
        return FakeParkedReads()


async def test_a_seeded_history_is_applied_under_the_write_invariants() -> None:
    """A history a conforming store could not hold is refused at construction.

    Refused *here* rather than at the first read, because a fake quietly holding two
    open parks for one conversation would certify a consumer against the very state
    ADR-0244 §3's one-open-park rule exists to make unreachable.
    """
    seeded = FakeParkedReads([park()])

    assert await seeded.get("park-1") is not None
    assert await seeded.get("park-2") is None, "the second write was refused, not raised"

    duplicated = FakeParkedReads([park(), park(park_id="park-2", decision_id="decision-2")])
    assert await duplicated.get("park-2") is None


async def test_a_seeded_terminal_park_is_admitted() -> None:
    """ADR-0244 §19's Arm 14 needs one, and no settlement can be replayed into a fixture.

    A conforming store reaches a terminal park by settling an open one; a *fixture* has
    no settlement to replay, so the seeded history admits one directly — which is the
    state that arm drives ``park_of_decision`` and ``grantable_decisions`` over.
    """
    settled = park().model_copy(
        update={
            "disposition": ParkedReadDisposition.DENIED,
            "parameters": None,
            "goal": None,
            "plan": None,
        }
    )

    store = FakeParkedReads([settled])

    held = await store.park_of_decision("decision-1")
    assert held is not None
    assert held.disposition is ParkedReadDisposition.DENIED


async def test_a_seeded_duplicate_id_is_refused() -> None:
    """The id is write-once for every store on this surface."""
    with pytest.raises(AssistantError, match="already recorded"):
        FakeParkedReads([park(), park(conversation_id="conv-2", decision_id="decision-2")])


async def test_a_scripted_read_fault_raises_rather_than_answering() -> None:
    """ADR-0244 mints no error class, so a store fault is the contract's ``AssistantError``.

    **A fault is not a refusal.** ``park`` answering ``False`` is a refusal the servicing
    site reads as "no park exists"; a store that cannot be read at all is a different
    fact, and a fake that answered ``None`` for it would certify a consumer that treats
    an unreadable store as an empty one.
    """
    store = FakeParkedReads([park()])
    store.fail_reads()

    with pytest.raises(AssistantError, match="could not be read"):
        await store.get("park-1")
    with pytest.raises(AssistantError, match="could not be read"):
        await store.outstanding()
    with pytest.raises(AssistantError, match="could not be read"):
        await store.park_of_decision("decision-1")
    with pytest.raises(AssistantError, match="could not be read"):
        await store.open_park("conv-1")


async def test_a_scripted_write_fault_raises_from_every_writing_member() -> None:
    """The other half, and what ADR-0244 §1's third clause is written over.

    "Where ``ParkedReads`` refused **or raised**, no park exists" — so the servicing site
    has to meet both, and a fake that could only be made to refuse would leave the raise
    arm of that clause undriven.
    """
    store = FakeParkedReads()
    store.fail_writes()

    with pytest.raises(AssistantError, match="could not be written"):
        await store.park(park())
    with pytest.raises(AssistantError, match="could not be written"):
        await store.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=LATER)
    with pytest.raises(AssistantError, match="could not be written"):
        await store.drop_for_conversation("conv-1")


async def test_a_terminal_record_cannot_be_written_through_park() -> None:
    """``park`` writes an ``OPEN`` park and nothing else (ADR-0244 §3).

    A terminal park is reached by settlement; admitting one through the write member
    would give an implementation a route to a spent question nobody answered.
    """
    store = FakeParkedReads()
    settled = park().model_copy(
        update={
            "disposition": ParkedReadDisposition.CANCELLED,
            "parameters": None,
            "goal": None,
            "plan": None,
        }
    )

    with pytest.raises(AssistantError, match="written OPEN"):
        await store.park(settled)


async def test_the_settlement_instant_is_the_callers_and_lands_in_no_field() -> None:
    """ADR-0244 §3's terminal facts do not include a settled-at member.

    What the contract obliges is that the **caller** supplies the instant rather than the
    store reading a clock — the rule every store on this surface holds — and this fake
    has nowhere to put it, which is the honest shape rather than an invented field.
    """
    store = FakeParkedReads([park()])

    assert await store.settle("park-1", disposition=ParkedReadDisposition.EXPIRED, at=AT)

    held = await store.get("park-1")
    assert held is not None
    assert held.parked_at == AT, "the parked-at instant is untouched by the settlement"

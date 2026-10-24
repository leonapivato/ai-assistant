"""The observer's writes: each framed memory placed and proposed, and the outcome.

Driven over the canonical fakes (ADR-0346 §6, ADR-0345 §4-§5). Every write is a placed
proposal through the write stage: retrieval, one placement call where anything is
retrieved, and an ingest carrying the placement at the revisions read. A stale placement
is placed again up to a count (§6:7); the floor's ruling is final, an ask raising nothing
(§6:8); every ``unclear`` is kept on the outcome (§6:5); and the outcome lists the
operations each memory's log gained, never one the store did not make.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, NoReturn

import pytest
from observer_support import AT, Harness, Minter, address, episode

from ai_assistant.core.errors import MemoryStoreStaleError, UnresolvedEvidenceError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryDecisionKind,
    MemoryOperationKind,
    MemoryPlacement,
    MemoryStatus,
    MemoryWrite,
    MemoryWriteMode,
    MemoryWriterName,
    PlacedPair,
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProposedNarrowing,
    SupportHolder,
)
from ai_assistant.orchestration.observer.framing import Framed, Framing
from ai_assistant.orchestration.observer.writing import FindingWriter, WriteLimits
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import ObservationWrite
    from ai_assistant.orchestration.observer.placement import PlacementView

_SEAT = "The user prefers window seats."


def _writer(harness: Harness, *, stale_retries: int = 2) -> FindingWriter:
    return FindingWriter(
        writes=harness.writes,
        memory=harness.memory,
        plans=harness.plans,
        now=harness.clock,
        limits=WriteLimits(threshold=0.8, bound=5, recent=3, stale_retries=stale_retries),
    )


def _framing(*contents: str, mint: Minter | None = None) -> Framing:
    minter = mint or Minter()
    framed = []
    for content in contents:
        support = said_support(address("one"), added_at=AT).model_copy(
            update={"added_by": MemoryWriterName.OBSERVER}
        )
        built = memory(f"observed:{minter()}", content, support, subjects=())
        framed.append(
            Framed(memory=built, texts={InputPart(episode=address("one")): "Window seats, please."})
        )
    return Framing(memories=tuple(framed))


async def _held_seat(harness: Harness, *, content: str = _SEAT) -> Memory:
    support = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        Memory.model_validate(
            memory("m-seat", content, support, subjects=(OWNER_PERSON_ID,)).model_dump()
        ),
    )
    stored = await harness.memory.get("m-seat")
    assert isinstance(stored, Memory)
    return stored


def _placing(
    relation: PlacedRelation, note: str = "How the two relate."
) -> Callable[[PlacementView], object]:
    async def place(view: PlacementView) -> MemoryPlacement:
        return MemoryPlacement(
            pairs=tuple(
                PlacedPair(
                    memory=one.memory.id,
                    revision=one.memory.revision,
                    relation=relation,
                    note=note,
                )
                for one in view.retrieved
            )
        )

    return place


async def _never(_view: PlacementView) -> NoReturn:
    msg = "nothing was retrieved, so nothing is placed"
    raise AssertionError(msg)


async def test_a_memory_like_nothing_stored_is_installed_with_no_placement_call() -> None:
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))

    written = await _writer(harness).write(
        _framing(_SEAT), supply=Placement(), narrowing=None, place=_never
    )

    (write,) = written.outcome.writes
    assert write.operations == (MemoryOperationKind.CREATE,)
    assert written.outcome.ruling is MemoryDecisionKind.ACCEPT
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == _SEAT
    (placed,) = written.placed
    assert placed.kept == (write.memory,)


async def test_a_restatement_folds_into_the_stored_memory() -> None:
    """ADR-0345 §5:2-§5:3: the operations the stored memory's log gained, listed."""
    harness = Harness()
    await _held_seat(harness)

    written = await _writer(harness).write(
        _framing(_SEAT),
        supply=Placement(),
        narrowing=None,
        place=_placing(PlacedRelation.RESTATES),  # type: ignore[arg-type]  # an async callable
    )

    assert [(one.memory, one.operations) for one in written.outcome.writes] == [
        ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    ]
    (placed,) = written.placed
    assert placed.kept == ("m-seat",)


async def test_a_holders_own_no_longer_true_retires_the_stored_memory() -> None:
    """ADR-0345 §3:3-§3:4, §5:4: installed, and the owner's own memory ended."""
    harness = Harness()
    await _held_seat(harness, content="The user prefers aisle seats.")

    written = await _writer(harness).write(
        _framing(_SEAT),
        supply=Placement(),
        narrowing=None,
        place=_placing(PlacedRelation.NO_LONGER_TRUE, "The user now prefers the window."),  # type: ignore[arg-type]  # an async callable
    )

    operations = {one.memory: one.operations for one in written.outcome.writes}
    assert MemoryOperationKind.END in operations["m-seat"]
    (created,) = [
        one for one, kinds in operations.items() if kinds == (MemoryOperationKind.CREATE,)
    ]
    ended = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert ended.status is MemoryStatus.ENDED
    assert created != "m-seat"


async def test_every_unclear_is_kept_on_the_outcome() -> None:
    """ADR-0346 §6:5: with its note and the memory it named, beside what was written."""
    harness = Harness()
    await _held_seat(harness)

    written = await _writer(harness).write(
        _framing(_SEAT),
        supply=Placement(),
        narrowing=None,
        place=_placing(PlacedRelation.UNCLEAR, "Whether it is the same trip is not shown."),  # type: ignore[arg-type]  # an async callable
    )

    (unclear,) = written.outcome.unclear
    assert (unclear.memory, unclear.wording) == ("m-seat", _SEAT)
    assert unclear.note == "Whether it is the same trip is not shown."
    assert written.outcome.writes, "an unclear installs the memory beside (ADR-0345 §5)"


async def test_a_stale_placement_is_placed_again_within_the_attempt() -> None:
    """ADR-0346 §6:7: the writer refuses it whole, and code retrieves and places again."""
    harness = Harness()
    held = await _held_seat(harness)
    calls = 0

    async def place(view: PlacementView) -> MemoryPlacement:
        nonlocal calls
        calls += 1
        if calls == 1:
            # Another write lands between this retrieval and the proposal.
            await harness.memory.write_atomic(
                [
                    MemoryWrite(
                        record=held,
                        mode=MemoryWriteMode.IF_UNCHANGED,
                        expected_revision=held.revision,
                    )
                ]
            )
        return await _placing(PlacedRelation.RESTATES)(view)  # type: ignore[misc,no-any-return]  # an async callable

    written = await _writer(harness).write(
        _framing(_SEAT), supply=Placement(), narrowing=None, place=place
    )

    assert calls == 2
    assert [one.memory for one in written.outcome.writes] == ["m-seat"]


async def test_a_placement_stale_past_its_count_fails_the_attempt() -> None:
    harness = Harness()
    held = await _held_seat(harness)

    async def place(view: PlacementView) -> MemoryPlacement:
        current = await harness.memory.get("m-seat")
        assert isinstance(current, Memory)
        await harness.memory.write_atomic(
            [
                MemoryWrite(
                    record=held,
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=current.revision,
                )
            ]
        )
        return await _placing(PlacedRelation.RESTATES)(view)  # type: ignore[misc,no-any-return]  # an async callable

    with pytest.raises(MemoryStoreStaleError):
        await _writer(harness, stale_retries=1).write(
            _framing(_SEAT), supply=Placement(), narrowing=None, place=place
        )


async def test_an_ask_from_the_floor_raises_nothing_and_is_asked() -> None:
    """ADR-0346 §6:8, ADR-0336 §7:4."""
    harness = Harness(ruling=MemoryDecisionKind.ASK_USER)
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))

    written = await _writer(harness).write(
        _framing(_SEAT), supply=Placement(), narrowing=None, place=_never
    )

    outcome = written.outcome
    assert (outcome.unwritten, outcome.ruling) == (
        FindingUnwritten.ASKED,
        MemoryDecisionKind.ASK_USER,
    )
    assert outcome.asked == (_SEAT,)
    assert [one for one in await harness.memory.export() if isinstance(one, Memory)] == []


async def test_a_rejection_writes_nothing_and_is_refused() -> None:
    harness = Harness(ruling=MemoryDecisionKind.REJECT)
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))

    written = await _writer(harness).write(
        _framing(_SEAT), supply=Placement(), narrowing=None, place=_never
    )

    assert (written.outcome.unwritten, written.outcome.ruling) == (
        FindingUnwritten.REFUSED,
        MemoryDecisionKind.REJECT,
    )


async def test_a_support_on_an_episode_no_longer_held_fails_the_check() -> None:
    """ADR-0329 §9:5: the writer refuses a part no stored episode holds."""
    harness = Harness()

    async def unresolved(_proposal: object) -> NoReturn:
        msg = "no such episode"
        raise UnresolvedEvidenceError(msg)

    harness.writes.write = unresolved  # type: ignore[method-assign,assignment]  # the writer refuses
    written = await _writer(harness).write(
        _framing(_SEAT), supply=Placement(), narrowing=None, place=_never
    )

    assert written.outcome.unwritten is FindingUnwritten.CHECK_FAILED


async def test_a_narrowing_is_proposed_only_where_nothing_narrowed_the_supply() -> None:
    """ADR-0346 §5:7, ADR-0217 §4: ``proposed`` over anyone, the supply's meet otherwise."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    narrowing = ProposedNarrowing(reach=PlacementReach.OWNER, note="Between us.")
    derived = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    mint = Minter()

    proposed = await _writer(harness).write(
        _framing(_SEAT, mint=mint), supply=Placement(), narrowing=narrowing, place=_never
    )
    supplied = await _writer(harness).write(
        _framing("The user flies often.", mint=mint),
        supply=derived,
        narrowing=narrowing,
        place=_never,
    )

    first = await harness.memory.get(proposed.outcome.writes[0].memory)
    second = await harness.memory.get(supplied.outcome.writes[0].memory)
    assert isinstance(first, Memory)
    assert isinstance(second, Memory)
    assert (first.placement.reach, first.placement.set_by) == (
        PlacementReach.OWNER,
        PlacementSetter.PROPOSED,
    )
    assert second.placement.set_by is PlacementSetter.DERIVED


async def test_what_lands_is_handed_over_as_it_lands() -> None:
    """ADR-0329 §16:1: before anything more is read."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    handed: list[tuple[ObservationWrite, ...]] = []

    async def landed(writes: tuple[ObservationWrite, ...]) -> None:
        handed.append(writes)

    await _writer(harness).write(
        _framing(_SEAT, "The user flies often."),
        supply=Placement(),
        narrowing=None,
        place=_never,
        landed=landed,
    )

    assert [len(one) for one in handed] == [1, 1, 2, 2]

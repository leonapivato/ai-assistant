"""The observer's writes: each framed memory placed and proposed, and the outcome.

Driven over the canonical fakes (ADR-0346 §6, ADR-0345 §4-§5). Every write is a placed
proposal through the write stage: retrieval, one placement call where anything is
retrieved, and an ingest carrying the placement at the revisions read. A memory reaching
more people than the finding may is never placed against (ADR-0217 §3); a stale placement
is placed again up to a count (§6:7); the floor's ruling is final, an ask raising nothing
(§6:8); every ``unclear`` is kept from the moment its call returns (§6:5); every step is
put on the record as it is taken, so an attempt resumes where the last stopped; and the
outcome lists the operations each memory's log gained, never one the store did not make.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, NoReturn

import pytest
from observer_support import AT, Harness, Minter, address, episode

from ai_assistant.core.errors import (
    MemoryStoreError,
    MemoryStoreStaleError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    FindingUnwritten,
    FramedMemory,
    FramedState,
    InputPart,
    Memory,
    MemoryChange,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryPlacement,
    MemoryStatus,
    MemorySupport,
    MemoryWrite,
    MemoryWriteMode,
    MemoryWriterName,
    NamedRevision,
    ObservationWrite,
    PinPart,
    PlacedPair,
    PlacedRelation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProposedNarrowing,
    ReadingCertainty,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
)
from ai_assistant.orchestration.observer.writing import FindingWriter, WriteLimits, outcome_of
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ai_assistant.core.types import SupportPart
    from ai_assistant.orchestration.observer.placement import PlacementView
    from ai_assistant.orchestration.observer.writing import Written

_SEAT = "The user prefers window seats."
_TEXTS: dict[SupportPart, str] = {InputPart(episode=address("one")): "Window seats, please."}
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
_RELATE = "How the two relate."


def _writer(harness: Harness, *, stale_retries: int = 2) -> FindingWriter:
    return FindingWriter(
        writes=harness.writes,
        memory=harness.memory,
        plans=harness.plans,
        now=harness.clock,
        limits=WriteLimits(threshold=0.8, bound=5, recent=3, stale_retries=stale_retries),
    )


def _framed(*contents: str, mint: Minter | None = None) -> tuple[FramedMemory, ...]:
    minter = mint or Minter()
    support = said_support(address("one"), added_at=AT).model_copy(
        update={"added_by": MemoryWriterName.OBSERVER}
    )
    return tuple(
        FramedMemory(memory=memory(f"observed:{minter()}", content, support, subjects=()))
        for content in contents
    )


class _Record:
    """What the writer put on the record, every time it put something there."""

    def __init__(self) -> None:
        self.steps: list[tuple[tuple[FramedMemory, ...], tuple[ObservationWrite, ...]]] = []

    async def __call__(
        self, framed: tuple[FramedMemory, ...], writes: tuple[ObservationWrite, ...]
    ) -> None:
        self.steps.append((framed, writes))


async def _write(  # noqa: PLR0913 — the writer's seams, each a case's to set
    harness: Harness,
    framed: tuple[FramedMemory, ...],
    *,
    place: Callable[[PlacementView], Awaitable[MemoryPlacement]] | None = None,
    supply: Placement | None = None,
    narrowing: ProposedNarrowing | None = None,
    record: _Record | None = None,
    stale_retries: int = 2,
) -> Written:
    return await _writer(harness, stale_retries=stale_retries).write(
        framed,
        texts=_TEXTS,
        supply=supply or Placement(),
        narrowing=narrowing,
        place=place or _never,
        progress=record or _Record(),
    )


async def _held_seat(
    harness: Harness, *, content: str = _SEAT, placement: Placement | None = None
) -> Memory:
    support = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    held = memory("m-seat", content, support, subjects=(OWNER_PERSON_ID,))
    if placement is not None:
        held = held.model_copy(update={"placement": placement})
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        Memory.model_validate(held.model_dump()),
    )
    stored = await harness.memory.get("m-seat")
    assert isinstance(stored, Memory)
    return stored


def _placing(
    relation: PlacedRelation, note: str = _RELATE
) -> Callable[[PlacementView], Awaitable[MemoryPlacement]]:
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


def _placing_each(
    relations: Mapping[str, tuple[PlacedRelation, str]],
) -> Callable[[PlacementView], Awaitable[MemoryPlacement]]:
    """Each retrieved memory placed as ``relations`` names it, and independent otherwise."""

    async def place(view: PlacementView) -> MemoryPlacement:
        pairs: list[PlacedPair] = []
        for one in view.retrieved:
            relation, note = relations.get(one.memory.id, (PlacedRelation.INDEPENDENT, ""))
            pairs.append(
                PlacedPair(
                    memory=one.memory.id,
                    revision=one.memory.revision,
                    relation=relation,
                    note=note,
                )
            )
        return MemoryPlacement(pairs=tuple(pairs))

    return place


def _losing(harness: Harness) -> Callable[[], None]:
    """Make the writer's reply lost after its write lands; returns what restores it."""
    ingest = harness.writer.ingest

    async def lost_after(proposal: Any) -> Any:
        await ingest(proposal)
        msg = "the store failed after the write landed"
        raise MemoryStoreError(msg)

    harness.writer.ingest = lost_after  # type: ignore[method-assign]  # lost reply

    def restore() -> None:
        harness.writer.ingest = ingest  # type: ignore[method-assign]  # the store is back

    return restore


async def _never(_view: PlacementView) -> NoReturn:
    msg = "nothing was retrieved, so nothing is placed"
    raise AssertionError(msg)


def _outcome(written: Written) -> Any:
    return outcome_of(written.framed, written.writes, at=AT)


async def test_a_memory_like_nothing_stored_is_installed_with_no_placement_call() -> None:
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))

    written = await _write(harness, _framed(_SEAT))

    (write,) = written.writes
    assert write.operations == (MemoryOperationKind.CREATE,)
    outcome = _outcome(written)
    assert outcome.ruling is MemoryDecisionKind.ACCEPT
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == _SEAT
    (done,) = written.framed
    assert (done.state, done.kept) == (FramedState.DONE, (write.memory,))


async def test_a_restatement_folds_into_the_stored_memory() -> None:
    """ADR-0345 §5:2-§5:3: the operations the stored memory's log gained, listed."""
    harness = Harness()
    await _held_seat(harness)

    written = await _write(harness, _framed(_SEAT), place=_placing(PlacedRelation.RESTATES))

    assert [(one.memory, one.operations) for one in written.writes] == [
        ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    ]
    (done,) = written.framed
    assert done.kept == ("m-seat",)


async def test_a_holders_own_no_longer_true_retires_the_stored_memory() -> None:
    """ADR-0345 §3:3-§3:4, §5:4: installed, and the owner's own memory ended."""
    harness = Harness()
    await _held_seat(harness, content="The user prefers aisle seats.")
    await harness.hold()

    written = await _write(
        harness,
        _framed("The user prefers window seats."),
        place=_placing(PlacedRelation.NO_LONGER_TRUE, "The user now prefers the window."),
    )

    operations = {one.memory: one.operations for one in written.writes}
    assert MemoryOperationKind.END in operations["m-seat"]
    (created,) = [one for one in operations if one != "m-seat"]
    assert operations[created][0] is MemoryOperationKind.CREATE
    ended = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert ended.status is MemoryStatus.ENDED


async def test_the_installed_memorys_whole_log_is_listed() -> None:
    """ADR-0329 §16:1: a dispute added to the new memory in the same write is listed too.

    Another holder's memory a retiring relation leaves current has its backing added to
    the installed memory as ``against`` (ADR-0345 §3:5), an operation on it beside its
    create.
    """
    harness = Harness()
    support = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": SupportHolder.person("person:sam")}
    )
    held = memory("m-seat", "The user prefers aisle seats.", support)
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Aisle seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        Memory.model_validate(held.model_dump()),
    )

    written = await _write(
        harness, _framed(_SEAT), place=_placing(PlacedRelation.NO_LONGER_TRUE, "Changed.")
    )

    (created,) = [one for one in written.writes if one.memory != "m-seat"]
    assert created.operations[0] is MemoryOperationKind.CREATE
    stored = await harness.memory.get(created.memory)
    assert isinstance(stored, Memory)
    assert list(created.operations) == [one.kind for one in stored.operations]
    assert len(created.operations) > 1, "the dispute is an operation beside the create"


async def test_every_unclear_is_kept_as_soon_as_its_call_returns() -> None:
    """ADR-0346 §6:5: on the record before the proposal is sent, and on the outcome."""
    harness = Harness()
    await _held_seat(harness)
    record = _Record()

    written = await _write(
        harness,
        _framed(_SEAT),
        place=_placing(PlacedRelation.UNCLEAR, "Whether it is the same trip is not shown."),
        record=record,
    )

    proposing = record.steps[0][0][0]
    assert proposing.state is FramedState.PROPOSING
    (unclear,) = proposing.unclear
    assert (unclear.memory, unclear.wording) == ("m-seat", _SEAT)
    assert unclear.note == "Whether it is the same trip is not shown."
    assert _outcome(written).unclear == (unclear,)
    assert written.writes, "an unclear installs the memory beside (ADR-0345 §5)"


async def test_an_unclear_survives_a_proposal_the_writer_refuses() -> None:
    """ADR-0346 §6:5: kept on the outcome however the write ends."""
    harness = Harness()
    await _held_seat(harness)

    async def unresolved(_proposal: object) -> NoReturn:
        msg = "no such episode"
        raise UnresolvedEvidenceError(msg)

    harness.writes.write = unresolved  # type: ignore[method-assign,assignment]  # refused
    written = await _write(
        harness, _framed(_SEAT), place=_placing(PlacedRelation.UNCLEAR, "Not shown.")
    )

    outcome = _outcome(written)
    assert outcome.unwritten is FindingUnwritten.CHECK_FAILED
    (unclear,) = outcome.unclear
    assert unclear.note == "Not shown."


async def test_a_memory_wider_than_the_finding_may_reach_is_not_placed_against() -> None:
    """ADR-0217 §3, ADR-0329 §12:6: what a relation writes onto it is never narrowed."""
    harness = Harness()
    await _held_seat(harness)

    written = await _write(harness, _framed(_SEAT), supply=_OWNER_ONLY)

    (write,) = written.writes
    assert write.memory != "m-seat"
    assert write.operations == (MemoryOperationKind.CREATE,)
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    assert len(seat.supports) == 1, "the wider memory gains nothing"


async def test_a_memory_whose_shown_supports_are_private_is_not_placed_against() -> None:
    """ADR-0329 §12:6, ADR-0217 §3: a recheck could carry the private text onto it.

    The stored memory reaches anyone, but a support it is shown with was read from an
    owner-only episode, so the meet over what the placement would be supplied is the
    owner's: the memory would be narrowed, and is left out, the new one beside it.
    """
    harness = Harness()
    support = said_support(address("past"), added_at=AT - timedelta(days=1))
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats.").model_copy(
            update={"placement": _OWNER_ONLY}
        ),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        Memory.model_validate(memory("m-seat", _SEAT, support).model_dump()),
    )

    written = await _write(harness, _framed(_SEAT), place=_never)

    (write,) = written.writes
    assert write.memory != "m-seat"
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    assert (seat.open_questions, len(seat.supports)) == ((), 1)


async def test_a_narrower_memory_placed_against_narrows_the_new_one() -> None:
    """ADR-0329 §12:6: the stored memory, and the episodes its supports were read from."""
    harness = Harness()
    support = said_support(address("past"), added_at=AT - timedelta(days=1))
    held = memory("m-seat", _SEAT, support).model_copy(update={"placement": _OWNER_ONLY})
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats.").model_copy(
            update={"placement": _OWNER_ONLY}
        ),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        Memory.model_validate(held.model_dump()),
    )

    written = await _write(harness, _framed(_SEAT), place=_placing(PlacedRelation.UNCLEAR, "?"))

    (created,) = [one for one in written.writes if one.memory != "m-seat"]
    stored = await harness.memory.get(created.memory)
    assert isinstance(stored, Memory)
    assert stored.placement.reach is PlacementReach.OWNER


async def test_another_findings_write_between_attempts_is_not_taken_for_this_ones() -> None:
    """ADR-0329 §16:1, §16:4: only operations citing the memory's own parts are its own."""
    harness = Harness()
    await _held_seat(harness)
    (framed,) = _framed(_SEAT)
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    named = NamedRevision(
        memory="m-seat",
        relation=PlacedRelation.RESTATES,
        operations=len(seat.operations),
        note=_RELATE,
    )
    proposing = framed.model_copy(update={"state": FramedState.PROPOSING, "named": (named,)})
    # Another episode adds its own support to the same memory meanwhile.
    other = said_support(address("other"), added_at=AT).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    await harness.hold(episode("other", at=AT - timedelta(minutes=1), text="Window, yes."))
    await harness.writer.apply(
        MemoryChange(
            memory=seat,
            operation=MemoryOperation(
                kind=MemoryOperationKind.ADD_SUPPORT,
                cites=other.points_at,
                at=AT,
                by=MemoryWriterName.OBSERVER,
            ),
            support=other,
        )
    )

    written = await _write(harness, (proposing,), place=_placing(PlacedRelation.RESTATES))

    (write,) = written.writes
    assert (write.memory, write.operations) == ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    after = await harness.memory.get("m-seat")
    assert isinstance(after, Memory)
    assert after.support_at(framed.memory.supports[0].points_at) is not None, (
        "this finding's support was added, not taken as added"
    )


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
        return await _placing(PlacedRelation.RESTATES)(view)

    written = await _write(harness, _framed(_SEAT), place=place)

    assert calls == 2
    assert [one.memory for one in written.writes] == ["m-seat"]


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
        return await _placing(PlacedRelation.RESTATES)(view)

    with pytest.raises(MemoryStoreStaleError):
        await _write(harness, _framed(_SEAT), place=place, stale_retries=1)


async def test_an_ask_from_the_floor_raises_nothing_and_is_asked() -> None:
    """ADR-0346 §6:8, ADR-0336 §7:4."""
    harness = Harness(ruling=MemoryDecisionKind.ASK_USER)
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))

    written = await _write(harness, _framed(_SEAT))

    outcome = _outcome(written)
    assert (outcome.unwritten, outcome.ruling) == (
        FindingUnwritten.ASKED,
        MemoryDecisionKind.ASK_USER,
    )
    assert outcome.asked == (_SEAT,)
    assert [one for one in await harness.memory.export() if isinstance(one, Memory)] == []


async def test_a_rejection_writes_nothing_and_is_refused() -> None:
    harness = Harness(ruling=MemoryDecisionKind.REJECT)
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))

    outcome = _outcome(await _write(harness, _framed(_SEAT)))

    assert (outcome.unwritten, outcome.ruling) == (
        FindingUnwritten.REFUSED,
        MemoryDecisionKind.REJECT,
    )


async def test_a_narrowing_is_proposed_only_where_nothing_narrowed_the_supply() -> None:
    """ADR-0346 §5:7, ADR-0217 §4: ``proposed`` over anyone, the supply's meet otherwise."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    narrowing = ProposedNarrowing(reach=PlacementReach.OWNER, note="Between us.")
    mint = Minter()

    proposed = await _write(harness, _framed(_SEAT, mint=mint), narrowing=narrowing)
    supplied = await _write(
        harness,
        _framed("The user flies often.", mint=mint),
        narrowing=narrowing,
        supply=_OWNER_ONLY,
    )

    first = await harness.memory.get(proposed.writes[0].memory)
    second = await harness.memory.get(supplied.writes[0].memory)
    assert isinstance(first, Memory)
    assert isinstance(second, Memory)
    assert (first.placement.reach, first.placement.set_by) == (
        PlacementReach.OWNER,
        PlacementSetter.PROPOSED,
    )
    assert second.placement.set_by is PlacementSetter.DERIVED


async def test_each_step_reaches_the_record_as_it_is_taken() -> None:
    """ADR-0329 §16:1: proposing, then done with what it wrote, memory by memory."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    record = _Record()

    await _write(harness, _framed(_SEAT, "The user flies often."), record=record)

    states = [[one.state for one in framed] for framed, _ in record.steps]
    assert states == [
        [FramedState.PROPOSING, FramedState.FRAMED],
        [FramedState.DONE, FramedState.FRAMED],
        [FramedState.DONE, FramedState.PROPOSING],
        [FramedState.DONE, FramedState.DONE],
    ]
    assert [len(writes) for _, writes in record.steps] == [0, 1, 1, 2]


async def test_a_memory_done_is_not_proposed_again() -> None:
    """ADR-0329 §16:4: a retry resumes after the memories already done."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    first, second = _framed(_SEAT, "The user flies often.")
    done = first.model_copy(update={"state": FramedState.DONE, "kept": ("observed:9",)})

    written = await _write(harness, (done, second))

    (write,) = written.writes
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == "The user flies often."


async def test_a_proposal_that_landed_before_the_attempt_stopped_is_read_off_the_store() -> None:
    """ADR-0329 §16:1: installed or folded, its operations are recovered, never guessed."""
    harness = Harness()
    await _held_seat(harness, content="The user prefers aisle seats.")
    ingest = harness.writer.ingest
    landed = False

    async def lost_after(proposal: Any) -> Any:
        nonlocal landed
        await ingest(proposal)
        landed = True
        msg = "the store failed after the write landed"
        raise MemoryStoreError(msg)

    harness.writer.ingest = lost_after  # type: ignore[method-assign]  # lost reply
    record = _Record()
    place = _placing(PlacedRelation.NO_LONGER_TRUE, "Changed.")
    with pytest.raises(MemoryStoreError):
        await _write(harness, _framed(_SEAT), place=place, record=record)
    assert landed
    (proposing,), _ = record.steps[-1]
    assert proposing.state is FramedState.PROPOSING

    harness.writer.ingest = ingest  # type: ignore[method-assign]  # the store is back
    written = await _write(harness, (proposing,), place=_never)

    operations = {one.memory: one.operations for one in written.writes}
    assert MemoryOperationKind.END in operations["m-seat"]
    assert operations[proposing.memory.id][0] is MemoryOperationKind.CREATE
    (done,) = written.framed
    assert (done.state, done.kept) == (FramedState.DONE, (proposing.memory.id,))


async def test_a_proposal_that_did_not_land_is_placed_again() -> None:
    """ADR-0329 §16:4: nothing in the store shows it, so it is proposed again."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    (framed,) = _framed(_SEAT)
    proposing = framed.model_copy(update={"state": FramedState.PROPOSING})

    written = await _write(harness, (proposing,))

    (write,) = written.writes
    assert (write.memory, write.operations) == (framed.memory.id, (MemoryOperationKind.CREATE,))


async def _proposing_on(harness: Harness, framed: FramedMemory) -> FramedMemory:
    """``framed``, its proposal recorded as sent against the stored seat as it stands."""
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    named = NamedRevision(
        memory="m-seat",
        relation=PlacedRelation.RESTATES,
        operations=len(seat.operations),
        note=_RELATE,
    )
    return framed.model_copy(update={"state": FramedState.PROPOSING, "named": (named,)})


async def test_a_fold_sharing_a_part_with_another_is_not_taken_for_this_ones() -> None:
    """ADR-0329 §16:4: another finding folding in a part both rest on landed nothing of this.

    This memory rests on an earlier part another finding shares and a part of its own;
    the other finding's fold adds the shared part, and this one's own part is still to
    be added, so it is placed again rather than done.
    """
    harness = Harness()
    await _held_seat(harness)
    await harness.hold(episode("shared", at=AT - timedelta(hours=1), text="Window, always."))
    shared = said_support(address("shared"), added_at=AT).model_copy(
        update={"added_by": MemoryWriterName.OBSERVER}
    )
    (framed,) = _framed(_SEAT)
    framed = framed.model_copy(
        update={
            "memory": framed.memory.model_copy(
                update={"supports": (*framed.memory.supports, shared)}
            )
        }
    )
    proposing = await _proposing_on(harness, framed)
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    await harness.writer.apply(
        MemoryChange(
            memory=seat,
            operation=MemoryOperation(
                kind=MemoryOperationKind.ADD_SUPPORT,
                cites=shared.points_at,
                at=AT + timedelta(minutes=5),
                by=MemoryWriterName.OBSERVER,
            ),
            support=shared.model_copy(update={"holder": SupportHolder.person(OWNER_PERSON_ID)}),
        )
    )

    written = await _write(harness, (proposing,), place=_placing(PlacedRelation.RESTATES))

    after = await harness.memory.get("m-seat")
    assert isinstance(after, Memory)
    assert after.support_at(framed.memory.supports[0].points_at) is not None
    (write,) = written.writes
    assert write.operations == (MemoryOperationKind.ADD_SUPPORT,)


async def test_a_recovered_install_lists_its_own_operations_and_no_later_one() -> None:
    """ADR-0329 §16:1: a later write on the installed memory is never taken for this one's."""
    harness = Harness()
    await harness.hold(episode("one", at=AT - timedelta(minutes=3)))
    (framed,) = _framed(_SEAT)
    first = await _write(harness, (framed,))
    installed = first.writes[0].memory
    stored = await harness.memory.get(installed)
    assert isinstance(stored, Memory)
    await harness.hold(episode("later", at=AT - timedelta(minutes=1), text="Window again."))
    later = said_support(address("later"), added_at=AT).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    harness.clock.advance(timedelta(minutes=5))
    await harness.writer.apply(
        MemoryChange(
            memory=stored,
            operation=MemoryOperation(
                kind=MemoryOperationKind.ADD_SUPPORT,
                cites=later.points_at,
                at=harness.clock(),
                by=MemoryWriterName.OBSERVER,
            ),
            support=later,
        )
    )
    proposing = framed.model_copy(update={"state": FramedState.PROPOSING})

    written = await _write(harness, (proposing,))

    assert [(one.memory, one.operations) for one in written.writes] == [
        (installed, (MemoryOperationKind.CREATE,))
    ]


async def test_a_recovered_install_keeps_the_recheck_it_raised() -> None:
    """ADR-0329 §16:1, ADR-0345 §5:9: a question resting on the stored memory's own supports."""
    harness = Harness()
    await _held_seat(harness)
    ingest = harness.writer.ingest

    async def lost_after(proposal: Any) -> Any:
        await ingest(proposal)
        msg = "the store failed after the write landed"
        raise MemoryStoreError(msg)

    harness.writer.ingest = lost_after  # type: ignore[method-assign]  # lost reply
    record = _Record()
    with pytest.raises(MemoryStoreError):
        await _write(
            harness,
            _framed(_SEAT),
            place=_placing(PlacedRelation.RECHECK, "Still the window?"),
            record=record,
        )
    (proposing,), _ = record.steps[-1]
    harness.writer.ingest = ingest  # type: ignore[method-assign]  # the store is back

    written = await _write(harness, (proposing,), place=_never)

    operations = {one.memory: one.operations for one in written.writes}
    assert operations["m-seat"] == (MemoryOperationKind.RAISE_QUESTION,)
    assert operations[proposing.memory.id] == (MemoryOperationKind.CREATE,)


@pytest.mark.parametrize(
    "note",
    ["Is it the window now?", "Still the window?", "The same claim."],
    ids=["its-own-note", "this-ones-recheck-note", "this-ones-restates-note"],
)
async def test_another_findings_recheck_is_not_taken_for_this_ones_fold(note: str) -> None:
    """ADR-0329 §16:1, §16:4: what the write must have left is checked, not only its notes.

    This memory restates one stored memory, which already carries its support, and asks
    for another to be rechecked; its proposal did not land. Another finding then raises
    a recheck on the first, citing a support the first carries, in its own words or in
    words this placement also used. Nothing of this one's write is held, so it is placed
    again and its own question written, and the other's question is never listed as its
    own.
    """
    harness = Harness()
    (framed,) = _framed(_SEAT)
    owner = SupportHolder.person(OWNER_PERSON_ID)
    past = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": owner}
    )
    own = framed.memory.supports[0].model_copy(update={"holder": owner})
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        memory("m-seat", _SEAT, past, own, subjects=(OWNER_PERSON_ID,)),
        memory("m-window", _SEAT, past, subjects=(OWNER_PERSON_ID,)),
    )
    held = await harness.memory.get_history(["m-seat", "m-window"])
    proposing = framed.model_copy(
        update={
            "state": FramedState.PROPOSING,
            "named": (
                NamedRevision(
                    memory="m-seat",
                    relation=PlacedRelation.RESTATES,
                    operations=len(held["m-seat"].operations),
                    note="The same claim.",
                ),
                NamedRevision(
                    memory="m-window",
                    relation=PlacedRelation.RECHECK,
                    operations=len(held["m-window"].operations),
                    note="Still the window?",
                ),
            ),
        }
    )
    mint = Minter()
    mint.minted = 50
    await _write(
        harness,
        _framed(_SEAT, mint=mint),
        place=_placing_each({"m-seat": (PlacedRelation.RECHECK, note)}),
    )
    asked = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert asked.operations[-1].kind is MemoryOperationKind.RAISE_QUESTION

    written = await _write(
        harness,
        (proposing,),
        place=_placing_each(
            {
                "m-seat": (PlacedRelation.RESTATES, "The same claim."),
                "m-window": (PlacedRelation.RECHECK, "Still the window?"),
            }
        ),
    )

    operations = {one.memory: one.operations for one in written.writes}
    assert "m-seat" not in operations, "the other finding's question is not this one's"
    assert operations["m-window"] == (MemoryOperationKind.RAISE_QUESTION,)
    window = (await harness.memory.get_history(["m-window"]))["m-window"]
    assert [one.asks for one in window.open_questions] == ["Still the window?"]
    (done,) = written.framed
    assert (done.state, done.kept) == (FramedState.DONE, ("m-seat",))


async def test_a_recovered_install_keeps_its_own_dispute_where_no_target_changed() -> None:
    """ADR-0329 §16:1, ADR-0345 §3:5: the installed memory's operations are told by its notes.

    The stored memory already carries this memory's part, so the retiring relation adds
    nothing to it, and another holder's backing keeps it current: the write's one
    operation beside the create is the dispute added to the installed memory.
    """
    harness = Harness()
    (framed,) = _framed(_SEAT)
    sams = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": SupportHolder.person("person:sam")}
    )
    own = framed.memory.supports[0].model_copy(
        update={
            "holder": SupportHolder.person(OWNER_PERSON_ID),
            "direction": SupportDirection.AGAINST,
            "backs_as_worded": False,
        }
    )
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Aisle seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        memory("m-seat", "The user prefers aisle seats.", sams, own),
    )
    before = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    restore = _losing(harness)
    record = _Record()
    with pytest.raises(MemoryStoreError):
        await _write(
            harness,
            (framed,),
            place=_placing(PlacedRelation.NO_LONGER_TRUE, "Changed."),
            record=record,
        )
    (proposing,), _ = record.steps[-1]
    restore()
    after = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert after.operations == before.operations, "the target gained nothing"

    written = await _write(harness, (proposing,), place=_never)

    assert [(one.memory, one.operations) for one in written.writes] == [
        (framed.memory.id, (MemoryOperationKind.CREATE, MemoryOperationKind.ADD_SUPPORT))
    ]


def _pinned_seat() -> Memory:
    """The stored seat, its first backing support a pin's, so a recheck cites the pin."""
    pin = MemorySupport(
        points_at=PinPart(pin="pin-1"),
        origin=SupportOrigin.PINNED,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=AT - timedelta(days=2),
        added_at=AT - timedelta(days=2),
        added_by=MemoryWriterName.OBSERVER,
    )
    past = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    return memory("m-seat", _SEAT, pin, past, subjects=(OWNER_PERSON_ID,))


@pytest.mark.parametrize("lost", [False, True], ids=["read-back", "recovered"])
async def test_a_recheck_citing_a_pin_is_the_writes_own(*, lost: bool) -> None:
    """ADR-0345 §5:9, ADR-0329 §16:1: only the pin pass's own support is not the write's."""
    harness = Harness()
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        _pinned_seat(),
    )
    place = _placing(PlacedRelation.RECHECK, "Still the window?")
    framed = _framed(_SEAT)
    if lost:
        restore = _losing(harness)
        record = _Record()
        with pytest.raises(MemoryStoreError):
            await _write(harness, framed, place=place, record=record)
        framed, _ = record.steps[-1]
        restore()
        place = _never

    written = await _write(harness, framed, place=place)

    seat = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert seat.operations[-1].cites == PinPart(pin="pin-1")
    operations = {one.memory: one.operations for one in written.writes}
    assert operations["m-seat"] == (MemoryOperationKind.RAISE_QUESTION,)


async def test_another_findings_fold_in_the_same_words_is_not_taken_for_this_ones() -> None:
    """ADR-0329 §16:1, §16:4: a fold landed only where the memory carries this one's parts.

    This memory and another finding's restate the same stored memory, each from its own
    part and in the same words; this one's proposal did not land, and the other's did.
    The stored memory does not carry this one's part, so it is placed again and its part
    added, and the other's support is never listed as its own.
    """
    harness = Harness()
    await _held_seat(harness)
    await harness.hold(episode("other", at=AT - timedelta(minutes=2), text="Window, yes."))
    (framed,) = _framed(_SEAT)
    proposing = await _proposing_on(harness, framed)
    theirs = said_support(address("other"), added_at=AT).model_copy(
        update={"added_by": MemoryWriterName.OBSERVER}
    )
    other = FramedMemory(memory=memory("observed:51", _SEAT, theirs, subjects=()))
    await _write(harness, (other,), place=_placing(PlacedRelation.RESTATES))
    seat = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert seat.support_at(theirs.points_at) is not None
    assert seat.operations[-1].note == _RELATE

    written = await _write(harness, (proposing,), place=_placing(PlacedRelation.RESTATES))

    after = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    assert after.support_at(framed.memory.supports[0].points_at) is not None
    ((memory_id, operations),) = [(one.memory, one.operations) for one in written.writes]
    assert (memory_id, operations) == ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    assert after.operations[-1].cites == framed.memory.supports[0].points_at


def _pin_only(record_id: str) -> Memory:
    """A stored memory backed by a pin alone, which no holder's word stops counting."""
    pin = _pinned_seat().supports[0]
    return memory(record_id, _SEAT, pin)


@pytest.mark.parametrize("lost", [False, True], ids=["read-back", "recovered"])
async def test_a_dispute_copying_a_pin_onto_the_fold_is_the_writes_own(*, lost: bool) -> None:
    """ADR-0345 §3:5, §3:8, ADR-0329 §16:1: only the pin pass's own support is not counted.

    This memory folds into one stored memory and retires another, which its pin keeps
    current, so the pin's support is copied onto the memory folded into as ``against``.
    """
    harness = Harness()
    await _held_seat(harness)
    await harness.hold(_pin_only("m-pinned"))
    place = _placing_each(
        {
            "m-seat": (PlacedRelation.RESTATES, "The same claim."),
            "m-pinned": (PlacedRelation.NO_LONGER_TRUE, "Changed."),
        }
    )
    framed = _framed(_SEAT)
    if lost:
        restore = _losing(harness)
        record = _Record()
        with pytest.raises(MemoryStoreError):
            await _write(harness, framed, place=place, record=record)
        framed, _ = record.steps[-1]
        restore()
        place = _never

    written = await _write(harness, framed, place=place)

    seat = (await harness.memory.get_history(["m-seat"]))["m-seat"]
    disputed = seat.support_at(PinPart(pin="pin-1"))
    assert disputed is not None
    assert disputed.direction is SupportDirection.AGAINST
    operations = {one.memory: one.operations for one in written.writes}
    assert operations["m-seat"] == (
        MemoryOperationKind.ADD_SUPPORT,
        MemoryOperationKind.ADD_SUPPORT,
    )
    (done,) = written.framed
    assert (done.state, done.kept) == (FramedState.DONE, ("m-seat",))


async def _owner_only_seat(harness: Harness) -> None:
    support = said_support(address("past"), added_at=AT - timedelta(days=1))
    held = memory("m-seat", _SEAT, support).model_copy(update={"placement": _OWNER_ONLY})
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats.").model_copy(
            update={"placement": _OWNER_ONLY}
        ),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        Memory.model_validate(held.model_dump()),
    )


async def test_a_stale_retry_keeps_what_the_earlier_placement_was_shown() -> None:
    """ADR-0329 §12:6, ADR-0346 §6:7: a retry never places it for more than an earlier one.

    The first placement call is shown an owner-only memory, which is gone before the
    proposal reaches the writer; the retry retrieves nothing, and the memory it installs
    is still placed for the owner alone.
    """
    harness = Harness()
    await _owner_only_seat(harness)
    calls = 0

    async def place(view: PlacementView) -> MemoryPlacement:
        nonlocal calls
        calls += 1
        await harness.memory.delete("m-seat")
        return await _placing(PlacedRelation.UNCLEAR, "?")(view)

    written = await _write(harness, _framed(_SEAT), place=place)

    assert calls == 1, "the retry retrieved nothing, so it made no placement call"
    (created,) = written.writes
    stored = await harness.memory.get(created.memory)
    assert isinstance(stored, Memory)
    assert stored.placement.reach is PlacementReach.OWNER


async def test_a_resumed_attempt_keeps_what_the_earlier_placement_was_shown() -> None:
    """ADR-0329 §12:6, §16:4: where an attempt placed the memory for is on its record."""
    harness = Harness()
    await _owner_only_seat(harness)
    ingest = harness.writer.ingest

    async def failing(proposal: Any) -> Any:
        msg = "the store failed before the write"
        raise MemoryStoreError(msg)

    harness.writer.ingest = failing  # type: ignore[method-assign]  # the store is down
    record = _Record()
    with pytest.raises(MemoryStoreError):
        await _write(
            harness, _framed(_SEAT), place=_placing(PlacedRelation.UNCLEAR, "?"), record=record
        )
    (proposing,), _ = record.steps[-1]
    harness.writer.ingest = ingest  # type: ignore[method-assign]  # the store is back
    await harness.memory.delete("m-seat")

    written = await _write(harness, (proposing,), place=_never)

    (created,) = written.writes
    stored = await harness.memory.get(created.memory)
    assert isinstance(stored, Memory)
    assert stored.placement.reach is PlacementReach.OWNER


async def test_a_restatement_left_unwritten_is_not_taken_as_landed() -> None:
    """ADR-0345 §5:1-§5:3, ADR-0329 §16:4: every memory it restates must carry its parts.

    This memory restates two stored memories, the first already carrying its part and
    the second not; its proposal did not land. Another finding then raises a recheck on
    the first in this placement's words. The second does not carry this one's part, so
    it is placed again, and the other's question is never listed as its own.
    """
    harness = Harness()
    (framed,) = _framed(_SEAT)
    owner = SupportHolder.person(OWNER_PERSON_ID)
    past = said_support(address("past"), added_at=AT - timedelta(days=1)).model_copy(
        update={"holder": owner}
    )
    own = framed.memory.supports[0].model_copy(update={"holder": owner})
    await harness.hold(
        episode("past", at=AT - timedelta(days=1), text="Window seats."),
        episode("one", at=AT - timedelta(minutes=3), text="Window seats, please."),
        memory("m-seat", _SEAT, past, own, subjects=(OWNER_PERSON_ID,)),
        memory("m-window", _SEAT, past, subjects=(OWNER_PERSON_ID,)),
    )
    held = await harness.memory.get_history(["m-seat", "m-window"])
    same = "The same claim."
    proposing = framed.model_copy(
        update={
            "state": FramedState.PROPOSING,
            "named": tuple(
                NamedRevision(
                    memory=key,
                    relation=PlacedRelation.RESTATES,
                    operations=len(held[key].operations),
                    note=same,
                )
                for key in ("m-seat", "m-window")
            ),
        }
    )
    mint = Minter()
    mint.minted = 50
    await _write(
        harness,
        _framed(_SEAT, mint=mint),
        place=_placing_each({"m-seat": (PlacedRelation.RECHECK, same)}),
    )

    written = await _write(
        harness,
        (proposing,),
        place=_placing_each(
            {"m-seat": (PlacedRelation.RESTATES, same), "m-window": (PlacedRelation.RESTATES, same)}
        ),
    )

    operations = {one.memory: one.operations for one in written.writes}
    assert "m-seat" not in operations, "the other finding's question is not this one's"
    assert operations["m-window"] == (MemoryOperationKind.ADD_SUPPORT,)
    window = (await harness.memory.get_history(["m-window"]))["m-window"]
    assert window.support_at(framed.memory.supports[0].points_at) is not None

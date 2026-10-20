"""The observer's writes, through the write stage, and each one's outcome (§12-§14, §16:1).

Driven over the canonical writer and store: a new memory through ``ingest`` under each
ruling, supports and questions through ``apply``, an entry through ``record_use``, and
the outcome naming what was written, by memory and operation, or why nothing was.
"""

from __future__ import annotations

from datetime import timedelta
from typing import NoReturn

import pytest
from observer_support import AT, Harness, address, episode

from ai_assistant.core.errors import MemoryStoreError, MemoryStoreStaleError
from ai_assistant.core.types import (
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryChange,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRetirement,
    MemoryStatus,
    MemorySupport,
    MemoryUpdateProposal,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    Placement,
    PlacementReach,
    PlacementSetter,
    ReadingCertainty,
    SupportDirection,
    SupportOrigin,
    TrackRecordEntry,
)
from ai_assistant.orchestration.observer.commit import (
    AddSupports,
    Checked,
    Create,
    RaiseQuestion,
    RecordUse,
    Resolve,
    Unwritten,
)
from ai_assistant.orchestration.observer.writing import FindingWriter, WriteBlocked
from ai_assistant.testing.memories import memory, said_support, sourced_support

_NOW = AT + timedelta(hours=1)
_CLAIM = "The user prefers window seats."


def _writer(harness: Harness) -> FindingWriter:
    return FindingWriter(
        writes=harness.writes, memory=harness.memory, now=harness.clock, mint=harness.mint
    )


def _said(
    episode_id: str = "leaving", *, direction: SupportDirection = SupportDirection.FOR
) -> MemorySupport:
    return MemorySupport(
        points_at=InputPart(episode=address(episode_id)),
        origin=SupportOrigin.USER_MESSAGE,
        direction=direction,
        backs_as_worded=direction is SupportDirection.FOR,
        how_sure=ReadingCertainty.SURE,
        when=AT,
        added_at=_NOW,
        added_by=MemoryWriterName.OBSERVER,
    )


def _new(content: str = _CLAIM, *supports: MemorySupport) -> Memory:
    held = supports or (_said(),)
    return Memory(
        id="observed:new",
        content=content,
        supports=held,
        operations=(
            MemoryOperation(
                kind=MemoryOperationKind.CREATE,
                cites=held[0].points_at,
                at=_NOW,
                by=MemoryWriterName.OBSERVER,
            ),
        ),
    )


async def _harness(ruling: MemoryDecisionKind = MemoryDecisionKind.ACCEPT) -> Harness:
    harness = Harness(ruling=ruling)
    harness.clock.at = _NOW
    await harness.hold(episode("leaving"), episode("past", at=AT - timedelta(days=1)))
    return harness


async def _stored(harness: Harness, record: Memory) -> Memory:
    await harness.hold(record)
    held = await harness.memory.get(record.id)
    assert isinstance(held, Memory)
    return held


async def test_an_accepted_memory_is_installed_and_named() -> None:
    """§12:2: through ``ingest``; the outcome names the memory and its create."""
    harness = await _harness()

    outcome = await _writer(harness).write(Checked(primary=Create(memory=_new())))

    assert outcome.ruling is MemoryDecisionKind.ACCEPT
    (write,) = outcome.writes
    assert (write.memory, write.operations) == ("observed:new", (MemoryOperationKind.CREATE,))
    assert isinstance(await harness.memory.get("observed:new"), Memory)


async def test_a_ruling_that_writes_nothing_is_refused() -> None:
    """§12:4, §16:1: a reject writes nothing, and the outcome carries the ruling."""
    harness = await _harness(MemoryDecisionKind.REJECT)

    outcome = await _writer(harness).write(Checked(primary=Create(memory=_new())))

    assert (outcome.ruling, outcome.unwritten) == (
        MemoryDecisionKind.REJECT,
        FindingUnwritten.REFUSED,
    )
    assert await harness.memory.get("observed:new") is None


async def test_an_ask_naming_no_memory_is_asked_and_raises_nothing() -> None:
    """§13:3: the finding's outcome records the ask; the candidate waits."""
    harness = await _harness(MemoryDecisionKind.ASK_USER)

    outcome = await _writer(harness).write(
        Checked(primary=Create(memory=_new(), asked_on=_said(direction=SupportDirection.AGAINST)))
    )

    assert (outcome.ruling, outcome.unwritten) == (
        MemoryDecisionKind.ASK_USER,
        FindingUnwritten.ASKED,
    )


async def test_an_ask_raises_a_policy_ask_on_each_memory_it_names() -> None:
    """§13:1: ``policy_ask`` on each stored memory the ruling names, never dropped."""
    harness = await _harness(MemoryDecisionKind.ASK_USER)
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))
    against = _said(direction=SupportDirection.AGAINST)

    outcome = await _writer(harness).write(Checked(primary=Create(memory=_new(), asked_on=against)))

    (write,) = outcome.writes
    assert (write.memory, write.operations) == (held.id, (MemoryOperationKind.RAISE_QUESTION,))
    asked = await harness.memory.get(held.id)
    assert isinstance(asked, Memory)
    (question,) = asked.open_questions
    assert question.kind is OpenQuestionKind.POLICY_ASK
    assert question.rests_on == (against.points_at,)
    assert question.raised_by is MemoryWriterName.OBSERVER


async def test_a_reinforced_memory_gains_the_supports() -> None:
    """§12:3: a create the policy rules ``REINFORCE`` adds its supports to the target."""
    harness = await _harness(MemoryDecisionKind.REINFORCE)
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))

    outcome = await _writer(harness).write(Checked(primary=Create(memory=_new())))

    (write,) = outcome.writes
    assert (write.memory, write.operations) == (held.id, (MemoryOperationKind.ADD_SUPPORT,))
    reinforced = await harness.memory.get(held.id)
    assert isinstance(reinforced, Memory)
    assert reinforced.support_at(InputPart(episode=address("leaving"))) is not None


async def test_a_retiring_proposal_installs_the_new_memory_and_retires_the_old() -> None:
    """§12:4: on an ``ACCEPT``, one atomic write, each naming the other."""
    harness = await _harness()
    held = await _stored(
        harness,
        memory("m-aisle", "The user likes aisle seats.", sourced_support(episode=address("past"))),
    )
    new = _new()
    retiring = MemoryRetirement(
        memory=held, kind=MemoryOperationKind.END, cites=new.supports[0].points_at
    )

    outcome = await _writer(harness).write(Checked(primary=Create(memory=new, retiring=retiring)))

    assert [(one.memory, one.operations) for one in outcome.writes] == [
        ("observed:new", (MemoryOperationKind.CREATE,)),
        ("m-aisle", (MemoryOperationKind.END,)),
    ]
    (ended,) = [one for one in await harness.memory.export() if one.id == "m-aisle"]
    assert isinstance(ended, Memory)
    assert ended.status is MemoryStatus.ENDED


async def test_supports_are_added_one_operation_each() -> None:
    """§12:3: one add support each, through ``apply``."""
    harness = await _harness()
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))

    outcome = await _writer(harness).write(
        Checked(primary=AddSupports(target=held, supports=(_said(),)))
    )

    (write,) = outcome.writes
    assert write.operations == (MemoryOperationKind.ADD_SUPPORT,)
    added = await harness.memory.get(held.id)
    assert isinstance(added, Memory)
    assert added.operations[-1].by is MemoryWriterName.OBSERVER


async def test_a_question_is_raised_and_another_resolved() -> None:
    """§13:1, §13:5: raise and resolve, each an operation through ``apply``."""
    harness = await _harness()
    raised = OpenQuestion(
        id="question:old",
        kind=OpenQuestionKind.RECHECK,
        asks="Still aisle?",
        rests_on=(InputPart(episode=address("past")),),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    record = memory("m-aisle", "The user likes aisle seats.", said_support(address("past")))
    record = record.model_copy(
        update={
            "open_questions": (raised,),
            "operations": (
                *record.operations,
                MemoryOperation(
                    kind=MemoryOperationKind.RAISE_QUESTION,
                    cites=InputPart(episode=address("past")),
                    at=AT,
                    by=MemoryWriterName.OBSERVER,
                    question="question:old",
                ),
            ),
        }
    )
    held = await _stored(harness, Memory.model_validate(record.model_dump()))
    against = _said(direction=SupportDirection.AGAINST)

    outcome = await _writer(harness).write(
        Checked(
            primary=RaiseQuestion(
                target=held, kind=OpenQuestionKind.RECHECK, asks="Check the seat.", support=against
            ),
            resolve=Resolve(
                target=held, question="question:old", support=against, note="window now"
            ),
        )
    )

    (write,) = outcome.writes
    assert write.operations == (
        MemoryOperationKind.RAISE_QUESTION,
        MemoryOperationKind.RESOLVE_QUESTION,
    )
    after = await harness.memory.get(held.id)
    assert isinstance(after, Memory)
    old, new = after.open_questions
    assert old.resolved
    assert old.resolution == "window now"
    assert not new.resolved
    assert new.asks == "Check the seat."


async def test_a_track_record_entry_is_recorded_through_record_use() -> None:
    """§14:4: an entry, conditionally on the revision read."""
    harness = await _harness()
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))
    entry = TrackRecordEntry(
        episode=address("leaving"),
        relied_at=AT,
        held_up=True,
        note="booked it",
        recorded_at=_NOW,
        recorded_by=MemoryWriterName.OBSERVER,
    )

    outcome = await _writer(harness).write(Checked(primary=RecordUse(memory=held, entry=entry)))

    (write,) = outcome.writes
    assert (write.memory, write.operations, write.track_record) == (held.id, (), True)
    after = await harness.memory.get(held.id)
    assert isinstance(after, Memory)
    assert after.track_record == (entry,)


async def test_a_support_on_an_episode_no_longer_held_fails_the_check() -> None:
    """§9:5, ADR-0328 §4:7: the writer refuses it, and the outcome says so."""
    harness = await _harness()

    outcome = await _writer(harness).write(
        Checked(primary=Create(memory=_new(_CLAIM, _said("gone"))))
    )

    assert outcome.unwritten is FindingUnwritten.CHECK_FAILED


async def test_a_memory_gone_before_its_write_fails_the_check() -> None:
    harness = await _harness()
    gone = memory("m-gone", _CLAIM, said_support(address("past"))).model_copy(
        update={"revision": 3}
    )

    outcome = await _writer(harness).write(
        Checked(primary=AddSupports(target=gone, supports=(_said(),)))
    )

    assert outcome.unwritten is FindingUnwritten.CHECK_FAILED


async def test_a_reason_alone_is_the_outcome() -> None:
    harness = await _harness()

    outcome = await _writer(harness).write(Checked(primary=Unwritten(FindingUnwritten.BELOW_FLOOR)))

    assert (outcome.writes, outcome.unwritten, outcome.at) == (
        (),
        FindingUnwritten.BELOW_FLOOR,
        _NOW,
    )


async def test_what_one_finding_wrote_before_a_later_write_failed_is_recorded() -> None:
    """§16:1: the first support stays written, and the outcome says so."""
    harness = await _harness()
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))

    outcome = await _writer(harness).write(
        Checked(primary=AddSupports(target=held, supports=(_said(), _said("gone"))))
    )

    (write,) = outcome.writes
    assert write.operations == (MemoryOperationKind.ADD_SUPPORT,)
    assert outcome.unwritten is None


async def test_an_entry_already_held_for_the_episode_is_recorded_as_held() -> None:
    """ADR-0328 §8:3: recording again changes nothing, and the outcome says what is held."""
    harness = await _harness()
    first = TrackRecordEntry(
        episode=address("leaving"),
        relied_at=AT,
        held_up=True,
        recorded_at=_NOW,
        recorded_by=MemoryWriterName.OBSERVER,
    )
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))
    await harness.writes.record_use(held, first)
    again = await harness.memory.get(held.id)
    assert isinstance(again, Memory)

    outcome = await _writer(harness).write(
        Checked(primary=RecordUse(memory=again, entry=first.model_copy(update={"held_up": False})))
    )

    (write,) = outcome.writes
    assert write.track_record is True
    after = await harness.memory.get(held.id)
    assert isinstance(after, Memory)
    assert after.track_record == (first,)
    assert after.revision == again.revision


async def test_a_memory_moved_since_the_decision_fails_the_attempt_as_stale() -> None:
    """ADR-0219 §2-§3: the decision is made again rather than applied to another state."""
    harness = await _harness()
    seen = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))
    await harness.writes.record_use(
        seen,
        TrackRecordEntry(
            episode=address("past"),
            relied_at=AT,
            held_up=True,
            recorded_at=_NOW,
            recorded_by=MemoryWriterName.OBSERVER,
        ),
    )

    with pytest.raises(MemoryStoreStaleError):
        await _writer(harness).write(Checked(primary=AddSupports(target=seen, supports=(_said(),))))


async def test_a_failing_store_fails_the_attempt_rather_than_refusing_the_finding() -> None:
    """§16:4: only a retry tells an outage from a refusal."""
    harness = await _harness()

    async def down(_proposal: MemoryUpdateProposal) -> NoReturn:
        msg = "database temporarily unavailable"
        raise MemoryStoreError(msg)

    harness.writer.ingest = down  # type: ignore[method-assign,assignment]  # an outage no fake arms

    with pytest.raises(MemoryStoreError):
        await _writer(harness).write(Checked(primary=Create(memory=_new())))


async def test_an_ask_on_a_memory_wider_than_the_supply_is_blocked_not_dropped() -> None:
    """§12:6, §13:6: no question carries the owner-only supply onto an ``anyone`` memory,
    and the ask is retried rather than recorded as asked.
    """
    harness = await _harness(MemoryDecisionKind.ASK_USER)
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))
    narrow = _new().model_copy(
        update={"placement": Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)}
    )

    with pytest.raises(WriteBlocked):
        await _writer(harness).write(
            Checked(
                primary=Create(memory=narrow, asked_on=_said(direction=SupportDirection.AGAINST))
            )
        )

    after = await harness.memory.get(held.id)
    assert isinstance(after, Memory)
    assert after.open_questions == ()


async def test_another_writer_between_two_own_writes_fails_the_attempt_as_stale() -> None:
    """ADR-0219 §2-§3: a revision is adopted only where this finding's own write made it."""
    harness = await _harness()
    held = await _stored(harness, memory("m-seat", _CLAIM, said_support(address("past"))))
    apply = harness.writes.apply

    async def interleaved(change: MemoryChange) -> None:
        await apply(change)
        moved = await harness.memory.get(held.id)
        assert isinstance(moved, Memory)
        await harness.writer.record_use(
            moved,
            TrackRecordEntry(
                episode=address("past"),
                relied_at=AT,
                held_up=True,
                recorded_at=_NOW,
                recorded_by=MemoryWriterName.OBSERVER,
            ),
        )

    harness.writes.apply = interleaved  # type: ignore[method-assign]  # another writer, between

    with pytest.raises(MemoryStoreStaleError):
        await _writer(harness).write(
            Checked(primary=AddSupports(target=held, supports=(_said(), _said("past"))))
        )


async def test_another_writer_between_a_fold_and_a_resolution_fails_the_attempt() -> None:
    """ADR-0219 §2-§3: a fold's result is adopted only as the fold makes it."""
    harness = await _harness(MemoryDecisionKind.REINFORCE)
    raised = OpenQuestion(
        id="question:old",
        kind=OpenQuestionKind.RECHECK,
        asks="Still?",
        rests_on=(InputPart(episode=address("past")),),
        raised_at=AT,
        raised_by=MemoryWriterName.OBSERVER,
    )
    base = memory("m-seat", _CLAIM, said_support(address("past")))
    record = Memory.model_validate(
        {
            **base.model_dump(),
            "open_questions": (raised,),
            "operations": (
                *base.operations,
                MemoryOperation(
                    kind=MemoryOperationKind.RAISE_QUESTION,
                    cites=InputPart(episode=address("past")),
                    at=AT,
                    by=MemoryWriterName.OBSERVER,
                    question="question:old",
                ),
            ),
        }
    )
    held = await _stored(harness, record)
    write = harness.writes.write

    async def interleaved(proposal: MemoryUpdateProposal) -> object:
        done = await write(proposal)
        moved = await harness.memory.get(held.id)
        assert isinstance(moved, Memory)
        await harness.writer.record_use(
            moved,
            TrackRecordEntry(
                episode=address("past"),
                relied_at=AT,
                held_up=True,
                recorded_at=_NOW,
                recorded_by=MemoryWriterName.OBSERVER,
            ),
        )
        return done

    harness.writes.write = interleaved  # type: ignore[method-assign,assignment]  # another writer
    against = _said(direction=SupportDirection.AGAINST)

    with pytest.raises(MemoryStoreStaleError):
        await _writer(harness).write(
            Checked(
                primary=Create(memory=_new()),
                resolve=Resolve(target=held, question="question:old", support=against, note="n"),
            ),
            shown=[held],
        )

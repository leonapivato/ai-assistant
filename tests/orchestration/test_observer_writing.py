"""The observer's writes, through the write stage, and each one's outcome (§12-§14, §16:1).

Driven over the canonical writer and store: a new memory through ``ingest`` under each
ruling, supports and questions through ``apply``, an entry through ``record_use``, and
the outcome naming what was written, by memory and operation, or why nothing was.
"""

from __future__ import annotations

from datetime import timedelta

from observer_support import AT, Harness, address, episode

from ai_assistant.core.types import (
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRetirement,
    MemoryStatus,
    MemorySupport,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
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
from ai_assistant.orchestration.observer.writing import FindingWriter
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

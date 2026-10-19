"""One operation applied to one memory: the record it yields and the writes refused.

ADR-0328 §5, §4:8, §5:3, §5:10-§5:11, §6:5 and §9:2, run over **both** writers'
transitions — ``MemoryIngestor``'s (``ai_assistant.memory._operations``) and the canonical
fake's own (``ai_assistant.testing._operations``) — so the two cannot drift apart. The
transition is the writer's (§11:3), not ``core``'s (ADR-0016 §2, ADR-0014); the shared
writer contract suite pins the same rules through ``MemoryWriter.apply`` and ``ingest``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

import pytest

from ai_assistant.core.types import (
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStanding,
    MemoryStatus,
    MemorySupport,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    Validity,
)
from ai_assistant.memory import _operations as production
from ai_assistant.testing import _operations as canonical_fake
from ai_assistant.testing.memories import AT, memory, remembered_support, said_support

_LATER = AT + timedelta(days=1)


class _Apply(Protocol):
    def __call__(
        self,
        memory: Memory,
        operation: MemoryOperation,
        *,
        support: MemorySupport | None = None,
        question: OpenQuestion | None = None,
    ) -> Memory: ...


@pytest.fixture(
    params=[production.applied_operation, canonical_fake.applied_operation],
    ids=["memory-ingestor", "canonical-fake"],
)
def apply(request: pytest.FixtureRequest) -> _Apply:
    """Each writer's transition in turn."""
    function: _Apply = request.param
    return function


def _operation(
    kind: MemoryOperationKind,
    cites: MemorySupport,
    *,
    at: datetime = _LATER,
    **fields: object,
) -> MemoryOperation:
    return MemoryOperation.model_validate(
        {"kind": kind, "cites": cites.points_at, "at": at, "by": MemoryWriterName.REMEMBER} | fields
    )


def test_add_support_adds_once_and_an_add_of_a_carried_part_changes_nothing(apply: _Apply) -> None:
    """§4:8, §5:3."""
    held = memory("m", "c", remembered_support())
    added = said_support("activation:x")
    grown = apply(held, _operation(MemoryOperationKind.ADD_SUPPORT, added), support=added)
    assert grown.supports == (*held.supports, added)
    assert grown.standing is MemoryStanding.SAID
    assert apply(grown, _operation(MemoryOperationKind.ADD_SUPPORT, added), support=added) is grown


def test_an_operations_support_must_be_the_one_it_cites(apply: _Apply) -> None:
    held = memory("m", "c")
    with pytest.raises(ValueError, match="the one it cites"):
        apply(
            held,
            _operation(MemoryOperationKind.ADD_SUPPORT, said_support("activation:x")),
            support=said_support("activation:y"),
        )


def test_a_create_is_never_applied(apply: _Apply) -> None:
    held = memory("m", "c")
    with pytest.raises(ValueError, match="create"):
        apply(held, held.operations[0])


def test_an_end_closes_the_window_at_its_about_when_and_ends_the_memory(apply: _Apply) -> None:
    """§5:10, §5:7."""
    held = memory("m", "c", remembered_support())
    ending = MemorySupport.model_validate(
        said_support("activation:end").model_dump() | {"about_when": AT + timedelta(hours=1)}
    )
    ended = apply(held, _operation(MemoryOperationKind.END, ending), support=ending)
    assert ended.status is MemoryStatus.ENDED
    assert ended.validity.valid_until == AT + timedelta(hours=1)
    # Nothing is removed (§5:5).
    assert set(held.supports) <= set(ended.supports)
    assert ended.operations[: len(held.operations)] == held.operations


def test_an_end_whose_about_when_is_after_its_instant_is_refused(apply: _Apply) -> None:
    held = memory("m", "c", remembered_support())
    later = MemorySupport.model_validate(
        said_support("activation:end").model_dump() | {"about_when": _LATER + timedelta(days=1)}
    )
    with pytest.raises(ValueError, match="about-when"):
        apply(held, _operation(MemoryOperationKind.END, later), support=later)


def test_a_close_clamps_and_never_extends_the_window(apply: _Apply) -> None:
    """ADR-0080 §1 kept by §5:11."""
    held = memory("m", "c", remembered_support(), validity=Validity(valid_until=AT))
    ended = apply(
        held,
        _operation(MemoryOperationKind.MARK_WRONG, said_support("activation:no")),
        support=said_support("activation:no"),
    )
    assert ended.validity.valid_until == AT
    assert ended.status is MemoryStatus.WRONG


def test_a_replace_names_its_successor_and_ends_the_memory(apply: _Apply) -> None:
    held = memory("m", "c", remembered_support())
    narrower = said_support("activation:narrower")
    replaced = apply(
        held,
        _operation(MemoryOperationKind.REPLACE, narrower, successor="m-2"),
        support=narrower,
    )
    assert replaced.status is MemoryStatus.ENDED
    assert replaced.operations[-1].successor == "m-2"


def test_a_lower_standing_never_retires_a_higher_one(apply: _Apply) -> None:
    """§6:5: the open question it needs is raised instead."""
    held = memory("m", "c", said_support())
    inferred = remembered_support("activation:guess")
    with pytest.raises(ValueError, match="ranks below"):
        apply(held, _operation(MemoryOperationKind.END, inferred), support=inferred)


def test_a_lower_standing_never_stops_a_higher_support(apply: _Apply) -> None:
    said = said_support()
    inferred = remembered_support("activation:guess")
    held = memory("m", "c", said, inferred)
    with pytest.raises(ValueError, match="ranks below"):
        apply(
            held,
            _operation(MemoryOperationKind.STOP_COUNTING, inferred, stops=said.points_at),
        )


def test_a_question_is_raised_and_resolved_by_operations(apply: _Apply) -> None:
    """§9:2."""
    held = memory("m", "c", remembered_support())
    cites = held.supports[0]
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="is this still so?",
        rests_on=(cites.points_at,),
        raised_at=_LATER,
        raised_by=MemoryWriterName.REMEMBER,
    )
    raised = apply(
        held,
        _operation(MemoryOperationKind.RAISE_QUESTION, cites, question="q-1"),
        question=question,
    )
    assert raised.open_questions == (question,)
    answer = said_support("activation:answer")
    resolved = apply(
        raised,
        _operation(
            MemoryOperationKind.RESOLVE_QUESTION,
            answer,
            question="q-1",
            note="the user said so",
        ),
        support=answer,
    )
    (closed,) = resolved.open_questions
    assert closed.resolved
    assert closed.resolved_by == answer.points_at
    with pytest.raises(ValueError, match="carries open"):
        apply(
            resolved,
            _operation(MemoryOperationKind.RESOLVE_QUESTION, answer, question="q-1", note="x"),
        )


def test_a_raise_question_cites_a_support_the_question_rests_on(apply: _Apply) -> None:
    """§5's table: a raise question cites a support the question rests on."""
    first = remembered_support("activation:first")
    second = remembered_support("activation:second")
    held = memory("m", "c", first, second)
    question = OpenQuestion(
        id="q-1",
        kind=OpenQuestionKind.RECHECK,
        asks="is this still so?",
        rests_on=(second.points_at,),
        raised_at=_LATER,
        raised_by=MemoryWriterName.REMEMBER,
    )
    with pytest.raises(ValueError, match="rests on"):
        apply(
            held,
            _operation(MemoryOperationKind.RAISE_QUESTION, first, question="q-1"),
            question=question,
        )

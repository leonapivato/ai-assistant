"""#1189: the answering block is the one the product's answering prompt would show.

``render_context`` used to dump every retrieved record's ``model_dump_json`` — id,
provenance with its whole evidence list, validity window, scores — on the stated ground
that the model should see what the store holds. The product does not show a model that.
``planning.planner._render_request`` renders one bullet per memory, ``[kind/source]``
and the content, under a heading, and a harness whose answering prompt is four times
the size and full of UUIDs is measuring a system nobody ships.

The equivalence is asserted **against the planner's own renderer**, not against a
string this file also spells: the harness copies a heading and a bullet format out of
two private functions, and a copy checked against a copy would go stale in step. So the
same records go through both, and the harness's whole block has to appear verbatim in
the prompt the product would build.

Three further properties are pinned because each is a way the mirror could be right in
form and wrong in effect: the record machinery is gone, an episode's ``occurred_at``
and ``outcome`` are gone *because the product drops them too*, and the block is the
retrieved group's rather than the conversation tail's.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from benchmarks.memory.answer import EMPTY_CONTEXT, RETRIEVED_HEADING, render_context

from ai_assistant.core.types import (
    CurrentContext,
    EpisodicMemory,
    Goal,
    GoalStatus,
    MemorySource,
    Provenance,
    SemanticMemory,
    TimeOfDay,
)
from ai_assistant.planning import planner

NOW = datetime(2023, 5, 8, 13, 56, tzinfo=UTC)

#: An id in the shape capture mints (``conv:<conversation>:<ordinal>``), long enough
#: that its absence from the rendered block is not an accident of a short string.
EPISODE_ID = "conv:6f1c2d3e-4b5a-4c7d-8e9f-0a1b2c3d4e5f:12"

BELIEF = SemanticMemory(
    id="9d2f7a10-8c44-4f2b-9a1e-1c0b5d6e7f80",
    content="Ada adopted a dog called Juno.",
    fact="Ada adopted a dog called Juno.",
    provenance=Provenance(
        source=MemorySource.INFERRED,
        confidence=0.72,
        last_updated=NOW,
        evidence=(EPISODE_ID, "conv:6f1c2d3e-4b5a-4c7d-8e9f-0a1b2c3d4e5f:13"),
    ),
)

EPISODE = EpisodicMemory(
    id=EPISODE_ID,
    content="Ada: I finally adopted her, she is a beagle.",
    occurred_at=NOW,
    outcome="Bo: congratulations!",
    provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=NOW),
)


def _product_prompt(*records: SemanticMemory | EpisodicMemory) -> str:
    """The user turn the product would assemble for these memories.

    Built through the planner's own private renderer rather than reconstructed, because
    the point is to catch the day the product's format moves and the harness's copy
    does not.

    Args:
        records: The memories, in the order retrieval handed them over.

    Returns:
        The rendered request.
    """
    goal = Goal(
        id="0f8f8f2c-1111-4222-8333-444455556666",
        statement="Answer the user's question.",
        status=GoalStatus.ACTIVE,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=NOW),
        created_at=NOW,
    )
    context = CurrentContext(
        now=NOW, time_of_day=TimeOfDay.AFTERNOON, is_weekend=False, within_working_hours=True
    )
    return planner._render_request(goal, context, list(records))


def test_the_block_is_the_one_the_product_would_render() -> None:
    """The whole of #1189, as an equivalence over behaviour rather than over a literal.

    A substring assertion rather than equality, because the product's prompt also
    carries the goal and the situational context — neither of which a benchmark
    question has. What has to match is the memory block, whole and unaltered: the
    heading, the bullets, the order, the spacing.
    """
    block = render_context([BELIEF, EPISODE])

    assert block in _product_prompt(BELIEF, EPISODE)


def test_the_heading_is_the_retrieved_groups_and_not_the_conversation_tails() -> None:
    """The harness cannot produce a tail, so it must never render the tail's heading.

    ``answer_question`` appends the ADR-0158 supplement after the beliefs and §4's
    separator rule drops it where the belief read came back empty, so the leading
    episodic run ``planner._split_conversation_tail`` looks for is always empty here. A
    block headed "Recent conversation turns" would tell the answering model that
    relevance-retrieved episodes were just said — the fabrication §4 exists to prevent,
    reintroduced by the renderer instead of by the read.
    """
    block = render_context([BELIEF, EPISODE])
    tail, retrieved = planner._split_conversation_tail([BELIEF, EPISODE])

    assert tail == []
    assert list(retrieved) == [BELIEF, EPISODE]
    assert block.splitlines()[0] == RETRIEVED_HEADING
    assert "Recent conversation turns" not in block


@pytest.mark.parametrize(
    "absent",
    [
        BELIEF.id,
        "0.72",
        "confidence",
        "validity",
        "evidence",
        "last_updated",
        "score",
        "fact",
    ],
    ids=[
        "record id",
        "confidence value",
        "confidence key",
        "validity window",
        "evidence list",
        "update stamp",
        "ranking score",
        "kind-specific field key",
    ],
)
def test_none_of_the_records_machinery_reaches_the_prompt(absent: str) -> None:
    """The cost half of #1189, pinned per field rather than as a size.

    A belief's provenance carried one UUID per cited episode — 24 of them on one
    pilot-3 record, about 1,100 characters — and none of it is content the product
    would ever show. The last two are the serialiser's own vocabulary rather than
    anything a reader wrote: ``score`` is the retrieval rank the store attaches, and
    ``fact`` is ``SemanticMemory``'s field name, which appears in a dump and in no
    prompt the product builds.
    """
    assert absent not in render_context([BELIEF, EPISODE])


def test_an_episode_shows_neither_its_instant_nor_its_outcome() -> None:
    """Because ``planner._render_record`` shows neither, and the mirror is the point.

    This is the one omission that costs the harness something. An episode carries the
    instant it happened, and #1029's P2 is a prediction about temporal reasoning; a
    harness that rendered ``occurred_at`` back in would answer that category from a
    field the shipped prompt withholds, which measures a system that does not exist.
    ``outcome`` — the assistant half of a captured turn — is dropped by the same line
    and for the same reason, and is a limitation of the product's renderer rather than
    of this copy of it.
    """
    block = render_context([EPISODE])
    bullet = block.splitlines()[1]

    assert EPISODE.content in bullet
    assert "2023-05-08" not in block
    assert EPISODE.outcome is not None
    assert EPISODE.outcome not in block
    # The bullet and not the block: an episode arriving *alone* is a leading episodic
    # run, so the planner heads it as the conversation tail. That state is unreachable
    # from `answer_question` — §4's separator rule drops a supplement with no belief
    # before it — so what is compared here is the line, which both renderers share.
    assert bullet in _product_prompt(EPISODE)


def test_the_block_is_a_fraction_of_the_dump_it_replaced() -> None:
    """The measured claim, asserted at the scale it was measured at.

    Not a threshold anyone should tune: it is a regression guard for the one shape that
    would silently undo #1189 — a renderer that quietly starts serialising the record
    again. The pilot-3 median was ~800 characters per record against ~150 of content,
    so a factor of two is a floor this cannot reach by accident.
    """
    block = render_context([BELIEF, EPISODE])
    dumped = "\n".join(record.model_dump_json() for record in (BELIEF, EPISODE))

    assert len(block) * 2 < len(dumped)


def test_no_records_render_the_stated_absence() -> None:
    """An empty section reads as a formatting error; this outcome is real and predicted."""
    assert render_context([]) == EMPTY_CONTEXT
    assert RETRIEVED_HEADING not in EMPTY_CONTEXT

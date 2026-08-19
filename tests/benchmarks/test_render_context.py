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
and ``outcome`` are *present* because since #1194 the product shows them, and the block
is the retrieved group's rather than the conversation tail's.

**Since #1181 the harness calls the product's renderer rather than copying it**, so the
first test below is no longer catching a copy going stale — it is catching the harness
assembling the product's own bullets into a block the product would not build. The
heading, the order, the spacing and the absence of a tail heading are all still this
module's to hold, and the copy the equivalence used to guard is simply gone.
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
        "validity",
        "evidence",
        "last_updated",
        "score",
        "fact",
    ],
    ids=[
        "record id",
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

    **``confidence`` used to be on this list and is deliberately off it** (#672). It
    was here as machinery, and ADR-0072 §6 rules that it is not: a derived belief
    reaching a prompt is rendered "as a belief, carrying its band and its confidence".
    The test below asserts its presence, so the two cannot both be satisfied by an
    empty renderer.
    """
    assert absent not in render_context([BELIEF, EPISODE])


def test_a_belief_carries_the_band_and_confidence_the_product_renders() -> None:
    """ADR-0072 §6 through the mirror, and the counterweight to the test above.

    The values, not merely the words: a renderer that printed a constant band or a
    constant confidence would pass a presence check and tell the answering model
    something false about every record but one.
    """
    block = render_context([BELIEF])

    assert "derived" in block
    assert "0.72" in block
    assert BELIEF.provenance.confidence == 0.72


def test_an_episode_shows_its_instant_and_its_outcome() -> None:
    """Because since #1194 ``planner._render_record`` shows both, and the mirror is
    the point.

    This used to be the one omission that cost the harness something: #1029's P2 is a
    prediction about temporal reasoning and no instant reached the prompt at all, so
    the category was being measured against a renderer that withheld its input. Both
    fields are here now for the only admissible reason — the shipped renderer emits
    them — and the assertion runs the other way so that a regression in ``planning``
    is caught here rather than only in the score.
    """
    block = render_context([EPISODE])
    bullet, outcome_line = block.splitlines()[1:3]

    assert EPISODE.content in bullet
    assert EPISODE.occurred_at.isoformat() in bullet
    assert EPISODE.outcome is not None
    assert EPISODE.outcome in outcome_line
    assert outcome_line.startswith("    how it turned out:")
    # The lines and not the block: an episode arriving *alone* is a leading episodic
    # run, so the planner heads it as the conversation tail. That state is unreachable
    # from `answer_question` — §4's separator rule drops a supplement with no belief
    # before it — so what is compared here is the record's own rendering.
    assert f"{bullet}\n{outcome_line}" in _product_prompt(EPISODE)


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

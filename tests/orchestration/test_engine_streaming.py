"""The engine's streaming turn: the four shapes, the ceiling, and a client that goes.

ADR-0173 §14's obligations that are about the *engine* rather than the stage or the
transport. The stage's own — §5's coalescing and its own half of §3's ceiling — are
in ``test_composing.py``; §1's frame sequence and §6's "same outcome in process and
across the wire" are in ``tests/wire/test_streamed_turns.py``.

**The ceiling cases measure rather than assume.** ADR-0173 §3 says "the implementing
lane measures it rather than guessing at a fraction of the frame size", and a test
that hard-coded a byte figure would be asserting this lane's arithmetic against
itself. So each one composes the answer once at an ample limit, measures the terminal
payload the engine actually built, and then re-runs a *fresh* harness at exactly that
limit — which is the same question a deployment asks.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from test_engine import PATIENT, Harness, NoStepPlanner, confirmable, tool

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import Disposition, ReplyChunk, TurnOutcome
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter, StreamAttempt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: The deltas most cases stream. Split so that a blank delta sits between two words,
#: which is the interleaving ADR-0173 §14 makes the wire lane pin and which no
#: engine-level case should quietly lose either.
_DELTAS = ("You prefer", " ", "hiking.")
_ANSWER = "You prefer hiking."


def _streaming(*deltas: str, fails: bool = False) -> ComposingStage:
    """A composing stage whose streaming seam yields ``deltas``."""
    return ComposingStage(
        model=FakeModelProvider(),
        streaming=FakeStreamingCompleter(script=(StreamAttempt(deltas=deltas, fails=fails),)),
    )


def _harness(stage: ComposingStage | None = None, **knobs: object) -> Harness:
    """A harness whose composing stage streams :data:`_DELTAS` unless told otherwise."""
    return Harness(composing=stage if stage is not None else _streaming(*_DELTAS), **knobs)  # type: ignore[arg-type]  # heterogeneous harness knobs


async def _drain(
    stream: AsyncIterator[ReplyChunk | TurnOutcome],
) -> tuple[list[str], TurnOutcome]:
    """Read one streamed turn whole, returning its chunk texts and its outcome."""
    chunks: list[str] = []
    outcome: TurnOutcome | None = None
    async for value in stream:
        if isinstance(value, TurnOutcome):
            outcome = value
        else:
            chunks.append(value.text)
    assert outcome is not None, "ADR-0173 §4: the outcome is always the last value"
    return chunks, outcome


# --- ADR-0173 §6: four shapes, read from two values --------------------------


async def test_a_whole_answer_is_the_join_of_its_chunks_and_is_not_degraded() -> None:
    """§6's fourth state and §3's join property, on the ordinary turn.

    The blank middle delta is the case §14 names: an engine that filtered it would
    answer ``"You preferhiking."`` and this is where that shows.
    """
    harness = _harness(tools=(tool(),))

    chunks, outcome = await _drain(
        harness.engine.converse_streaming("what do you know about me?", timeout=PATIENT)
    )

    assert "".join(chunks) == _ANSWER
    assert outcome.reply == _ANSWER
    assert outcome.reply_degraded is False
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED


async def test_a_failure_before_the_first_chunk_is_the_pre_commit_degradation() -> None:
    """§6: "a composition failure **before** the first ``ReplyChunk``… changes nothing".

    It degrades exactly as ADR-0170 §8 already ruled — ``reply`` ``None``,
    ``reply_degraded`` ``True``, the turn returned rather than raised.
    """
    harness = _harness(_streaming(fails=True), tools=(tool(),))

    chunks, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert chunks == []
    assert outcome.reply is None
    assert outcome.reply_degraded is True
    assert outcome.step is not None


async def test_a_failure_after_the_first_chunk_is_the_fourth_shape() -> None:
    """§6's fourth shape, "which ADR-0170 §4 does not admit and this clause adds".

    The only way it is reachable is a failure injected after a chunk has been
    yielded, which is why §14 names that injection rather than leaving it to a
    cooperative fake.
    """
    harness = _harness(_streaming("You prefer", fails=True), tools=(tool(),))

    chunks, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert chunks == ["You prefer"]
    assert outcome.reply == "You prefer"
    assert outcome.reply_degraded is True


async def test_a_park_owes_no_answer_and_streams_no_chunk() -> None:
    """§4's zero-chunk exchange, on ADR-0170 §4's first ``None`` shape.

    What the user must answer is the confirmation, so prose beside it would compete
    with the question — and the streaming entry declines on exactly the shapes the
    whole entry declines on, or a client could tell the two apart by which passes
    fell silent.
    """
    harness = _harness(tools=(confirmable(),))

    chunks, outcome = await _drain(harness.engine.converse_streaming("send it", timeout=PATIENT))

    assert chunks == []
    assert outcome.reply is None
    assert outcome.reply_degraded is False
    assert outcome.step is not None
    assert outcome.step.confirmation is not None


async def test_the_four_shapes_are_each_distinct_from_the_two_values() -> None:
    """§14: "pins §6's four shapes explicitly… each from the two field values alone"."""
    subjects = {
        "owed, whole produced": (_harness(tools=(tool(),)), "a"),
        "owed, part produced": (
            _harness(_streaming("You prefer", fails=True), tools=(tool(),)),
            "a",
        ),
        "owed, none produced": (_harness(_streaming(fails=True), tools=(tool(),)), "a"),
        "no answer owed": (_harness(tools=(confirmable(),)), "send it"),
    }
    read: dict[str, TurnOutcome] = {}
    for name, (harness, utterance) in subjects.items():
        read[name] = (await _drain(harness.engine.converse_streaming(utterance, timeout=PATIENT)))[
            1
        ]

    states = {
        name: (outcome.reply is None, outcome.reply_degraded) for name, outcome in read.items()
    }
    assert states == {
        "owed, whole produced": (False, False),
        "owed, part produced": (False, True),
        "owed, none produced": (True, True),
        "no answer owed": (True, False),
    }


# --- ADR-0173 §3: the ceiling, at all four of its inputs ---------------------


async def _payload_bytes_of_a_whole_answer() -> int:
    """How many bytes the terminal outcome takes when the answer streams whole.

    Measured against a fresh harness at its ordinary limit, so the number is the
    engine's own rather than this module's arithmetic about it.
    """
    _, outcome = await _drain(
        _harness(planner=NoStepPlanner()).engine.converse_streaming("hello", timeout=PATIENT)
    )
    assert outcome.reply == _ANSWER
    return len(canonical_payload(outcome))


async def _payload_bytes_of_no_answer() -> int:
    """How many bytes the same outcome takes carrying **no** answer at all.

    Measured rather than derived from the figure above, because the two differ by
    more than the answer's own characters: ``"reply":null`` is four bytes where a
    quoted answer is two plus its own. This is the limit at which ADR-0173 §3's
    second case is reachable at all — the answerless outcome still fits, and no
    chunk does. A byte below it the turn is §3's *third* case instead, which raises,
    and that is the honest boundary rather than a gap.
    """
    _, outcome = await _drain(
        _harness(_streaming(fails=True), planner=NoStepPlanner()).engine.converse_streaming(
            "hello", timeout=PATIENT
        )
    )
    assert outcome.reply is None
    return len(canonical_payload(outcome))


async def test_an_answer_that_exactly_fills_the_room_terminates_whole() -> None:
    """§14: "exactly fills the room the terminal frame has terminates whole".

    A lane that reserved a byte of slack, or spent one, fails here — which is the
    point of pinning the boundary rather than a value comfortably inside it.
    """
    exact = await _payload_bytes_of_a_whole_answer()
    harness = _harness(planner=NoStepPlanner())
    harness.engine._max_payload_bytes = exact

    chunks, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert "".join(chunks) == _ANSWER
    assert outcome.reply == _ANSWER
    assert outcome.reply_degraded is False


async def test_one_byte_less_stops_before_the_chunk_that_would_breach() -> None:
    """§14's step past the boundary: it stops **before** yielding that chunk.

    And what it terminates with is §6's fourth shape, so a chunk-reading client and
    a chunk-ignoring one still hold the same answer — "no chunk was yielded whose
    text the terminal ``reply`` does not repeat".
    """
    exact = await _payload_bytes_of_a_whole_answer()
    harness = _harness(planner=NoStepPlanner())
    harness.engine._max_payload_bytes = exact - 1

    chunks, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert "".join(chunks) == "You prefer"
    assert outcome.reply == "You prefer"
    assert outcome.reply_degraded is True


async def test_room_that_cannot_hold_a_first_chunk_publishes_nothing() -> None:
    """§3's second case, and §14 pins it because the boundary test cannot reach it.

    "Having yielded none — because the room left could not hold even the first
    chunk — it terminates with §6's pre-commit shape". Nothing was published, so
    this is not a truncation, and ``reply`` is ``None`` because
    ``NonBlankEncodableText`` has no way to say "the empty answer".
    """
    harness = _harness(planner=NoStepPlanner())
    harness.engine._max_payload_bytes = await _payload_bytes_of_no_answer()

    chunks, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert chunks == []
    assert outcome.reply is None
    assert outcome.reply_degraded is True


async def test_non_reply_content_that_alone_breaches_the_ceiling_still_raises() -> None:
    """§3's third case: "``OversizedValueError`` exactly as it does on ``converse``".

    A turn whose plan and retrieved memories overflow the frame on their own was
    never about the reply, and streaming "leaves [it] precisely as it found" it. Both
    entries are asserted, because the value of the clause is that they agree.
    """
    harness = _harness(planner=NoStepPlanner())
    harness.engine._max_payload_bytes = 1

    with pytest.raises(OversizedValueError):
        await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))
    with pytest.raises(OversizedValueError):
        await harness.engine.converse("hello", timeout=PATIENT)


async def test_a_stream_that_stops_at_the_ceiling_publishes_nothing_unrepeatable() -> None:
    """The property both ceiling cases share, asserted as a property.

    §14: "Both assert that **no chunk was yielded whose text the terminal ``reply``
    does not repeat**, which is the property a chunk-reading and a chunk-ignoring
    client must agree on."
    """
    exact = await _payload_bytes_of_a_whole_answer()
    for limit in (exact, exact - 1, await _payload_bytes_of_no_answer()):
        harness = _harness(planner=NoStepPlanner())
        harness.engine._max_payload_bytes = limit
        chunks, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))
        assert "".join(chunks) == (outcome.reply or "")
        assert len(canonical_payload(outcome)) <= limit


# --- ADR-0173 §7: one model call, at the seam the pass uses -------------------


async def test_a_streamed_pass_spends_its_call_at_the_streaming_seam_alone() -> None:
    """§7: "spends it on §5's sibling seam and originates **no** ``complete()`` call".

    Both halves, because the budget is what makes the clause bite: one attempt at
    the streaming seam, and none at all at the completing one.
    """
    model = FakeModelProvider("a whole answer nobody asked for")
    seam = FakeStreamingCompleter.yielding(*_DELTAS)
    harness = _harness(ComposingStage(model=model, streaming=seam), tools=(tool(),))

    _, outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert outcome.reply == _ANSWER
    assert seam.attempt_count == 1
    assert model.calls == []


async def test_the_whole_entry_still_spends_its_call_at_the_completing_seam() -> None:
    """§7's other half, and §4's "``converse`` is unchanged".

    A caller that wants no stream observes nothing this ADR adds, which includes
    which seam its turn was composed at.
    """
    model = FakeModelProvider(_ANSWER)
    seam = FakeStreamingCompleter.yielding("never asked for")
    harness = _harness(ComposingStage(model=model, streaming=seam), tools=(tool(),))

    outcome = await harness.engine.converse("hello", timeout=PATIENT)

    assert outcome.reply == _ANSWER
    assert len(model.calls) == 1
    assert seam.attempt_count == 0


# --- ADR-0173 §9: a cut stream does not abandon the turn ---------------------


async def test_a_client_that_goes_away_leaves_the_turn_completed_and_captured() -> None:
    """§9: "the turn runs to its ordinary completion, including its capture".

    A turn may have approved a non-idempotent tool and durably committed its
    execution before a word was composed; abandoning it because a socket closed
    would leave that effect committed and the exchange uncaptured, whose natural
    retry can perform it twice. One turn's tokens is the cheaper side of that trade.

    ``aclose`` is what makes the assertion exact rather than timed: ADR-0042 §2
    obliges it to drain every tracked operation, and a turn abandoned mid-stream is
    one — which is the same guarantee, read from the other end.
    """
    harness = _harness(tools=(tool(),))

    stream = harness.engine.converse_streaming("hello", timeout=PATIENT)
    first = await anext(aiter(stream))
    assert isinstance(first, ReplyChunk)
    await stream.aclose()  # type: ignore[attr-defined]  # the contract's own clause

    await harness.engine.aclose()

    conversations = await harness.conversation_store.recent(limit=10)
    assert len(conversations) == 1
    turns = await harness.conversation_store.turns(conversations[0].id)
    assert len(turns) == 1, "§9: the turn's record survives, whoever was reading"


async def test_an_abandoned_stream_re_executes_nothing() -> None:
    """§9's other half: "nothing re-executed".

    The tool ran once, before the answer was composed at all, and walking away
    from the stream neither repeats it nor rolls it back.
    """
    harness = _harness(tools=(tool(),))

    stream = harness.engine.converse_streaming("hello", timeout=PATIENT)
    await anext(aiter(stream))
    await stream.aclose()  # type: ignore[attr-defined]  # the contract's own clause
    await harness.engine.aclose()

    assert len(harness.invoker.invocations) == 1


# --- ADR-0173 §8: conversation resume, carried by the route already there ----


async def test_a_second_streamed_turn_continues_the_conversation_the_first_began() -> None:
    """§8: the same ``conversation_id`` argument and the same existing route.

    The milestone's exit test is "a streamed answer over the wire, **resumed
    mid-conversation**", and §8 records that the resume half was already built: the
    conversation's recent turns reach the composer as part of ``TurnResult.memories``
    (ADR-0074 §5), with no history parameter and no second read added here.
    """
    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = _harness(tools=(tool(),), loop_id_factory=lambda: next(goals))

    _, first = await _drain(
        harness.engine.converse_streaming("what do you know about me?", timeout=PATIENT)
    )
    assert first.conversation_id is not None

    _, second = await _drain(
        harness.engine.converse_streaming(
            "and what else?", timeout=PATIENT, conversation_id=first.conversation_id
        )
    )

    assert second.conversation_id == first.conversation_id
    assert second.turn is not None
    assert any("what do you know about me?" in record.content for record in second.turn.memories), (
        "ADR-0074 §5: the conversation's recent turns reach the turn as memories"
    )


async def test_every_chunk_the_turn_produced_reaches_a_slow_reader() -> None:
    """The relay loses nothing to a consumer that suspends between reads (§3).

    The turn runs beside the iterator that relays it, so what the engine yields and
    what a caller reads are separated by a queue — and §3's join property is a claim
    about the *caller's* side of it: "no chunk was yielded whose text the terminal
    ``reply`` does not repeat" is only half the rule if the other half can drop one.

    **A reader that gives the loop a turn between chunks is the shape in which a
    loss would appear**, because that is the only window in which the relay's own
    bookkeeping can move underneath it. The loop is written so the answer does not
    depend on that window's outcome; this is what would notice if it did.
    """
    many = tuple(f"word{n} " for n in range(1, 40))
    harness = _harness(_streaming(*many), planner=NoStepPlanner())

    chunks: list[str] = []
    outcome: TurnOutcome | None = None
    async for value in harness.engine.converse_streaming("hello", timeout=PATIENT):
        if isinstance(value, TurnOutcome):
            outcome = value
        else:
            chunks.append(value.text)
        await asyncio.sleep(0)

    assert outcome is not None
    assert len(chunks) == len(many)
    assert "".join(chunks) == outcome.reply
    assert outcome.reply_degraded is False

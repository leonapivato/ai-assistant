"""The canonical engine fake supplies ADR-0264 §7's statement, and on which shapes (#2381).

:class:`~ai_assistant.testing.FakeAssistantEngine` is the double every consumer of
``AssistantEngine`` is certified against, and ADR-0026 §7 binds it to the contract
rather than to a convenience. §7 of ADR-0264 gives ``outbound_statement`` to every pass
that composed a reply and reserves ``None`` for the passes that "neither established a
contact nor composed a reply" — so a fake that answered ``None`` everywhere would let a
surface rendering the statement be **written, tested green against it, and never read
the field at all**. That is issue #2381, found by the adversarial lens on PR #2377 and
reproduced against the shipped fake before it was filed; it is the failure a canonical
fake exists to prevent, and it lands on the surfaces that render §7's statement — the
terminal (ADR-0264 §9) and the browser when #2237's lane runs.

**The shapes are pinned rather than the default alone**, because the whole of §7's rule
is *which* pass carries the member. Two of them are counter-intuitive in opposite
directions and each is asserted here beside the other: ADR-0198 §1's **restatement**
carries ``NOT_REACHED`` though it composes no prose of its own — §7 names it among the
three passes that do — while a **recovered park** and every non-``DISPATCHED`` read
answer carry ``None``, which is §7's reserved case and not an omission. The concrete
engine draws the line in exactly those places
(:func:`ai_assistant.orchestration.engine._reached_nothing`'s call sites), and a fake
that drew it anywhere else would certify a consumer against outcome shapes no engine
produces.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    ContinuationToken,
    MemoryKind,
    OutboundDestination,
    OutboundReach,
    OutboundStatement,
    ReadAnswerOutcome,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SpokenAudio,
    SpokenAudioFormat,
    TurnOutcome,
)
from ai_assistant.testing import FakeAssistantEngine

PATIENT: Final = timedelta(seconds=30)
_AT: Final = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

#: One recording, whose octets are never read: ``converse_spoken`` hears
#: :attr:`FakeAssistantEngine.spoken_transcript` and not this.
RECORDING: Final = SpokenAudio(
    content=b64encode(b"a recording").decode(), media_type=SpokenAudioFormat.WEBM_OPUS
)


def _belief() -> Belief:
    """One live belief, as a routed ``forget`` resolves it."""
    return Belief(
        id="b-1",
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.PREFERENCE,
        content="you drink tea",
        confidence=0.9,
        last_updated=_AT,
    )


async def _streamed(engine: FakeAssistantEngine) -> TurnOutcome:
    """The terminal outcome of one streamed turn, past its chunks."""
    last: TurnOutcome | None = None
    async for piece in engine.converse_streaming("hello", timeout=PATIENT):
        if isinstance(piece, TurnOutcome):
            last = piece
    assert last is not None
    return last


# --- §7's first half: a pass that composed a reply carries the statement ---


async def test_a_plain_turn_carries_a_statement_and_not_none() -> None:
    """The shape #2381 records, at the call that records it.

    ``converse`` composes a reply on this double, so §7 gives it the member — and
    ``NOT_REACHED`` is the honest value rather than a stand-in: a fake originates no
    model call and opens no channel, so no pass of it can have reached outside this
    system.
    """
    engine = FakeAssistantEngine()

    outcome = await engine.converse("hello", timeout=PATIENT)

    assert outcome.reply is not None
    assert outcome.outbound_statement == OutboundStatement(reach=OutboundReach.NOT_REACHED)


async def test_a_streamed_turn_carries_it_on_the_terminal_outcome() -> None:
    """The streaming twin, which a client reads the member off exactly as it reads ``reply``."""
    engine = FakeAssistantEngine()

    outcome = await _streamed(engine)

    assert outcome.reply is not None
    assert outcome.outbound_statement == OutboundStatement(reach=OutboundReach.NOT_REACHED)


async def test_a_spoken_turn_carries_it_although_no_statement_is_spoken() -> None:
    """ADR-0264 §7: the spoken surface is expressly **not** a rendering surface.

    That is a fact about the surface — ADR-0200 §4 makes ``spoken`` the rendering of
    ``reply`` and of nothing else, which §12 books as a stated cost — and not a reason
    to leave the member off the outcome. A spoken turn carries it like any other, and a
    consumer reading the outcome finds it there.
    """
    engine = FakeAssistantEngine()

    spoken = await engine.converse_spoken(
        RECORDING, plays=(SpokenAudioFormat.WEBM_OPUS,), timeout=PATIENT
    )

    assert spoken.outcome is not None
    assert spoken.outcome.reply is not None
    assert spoken.outcome.outbound_statement == OutboundStatement(reach=OutboundReach.NOT_REACHED)


async def test_a_routed_pass_that_is_not_a_park_carries_it() -> None:
    """ADR-0197 §10's routed answer, which §7 names in terms.

    "An answer is owed" on it, so there is prose and §1's condition binds on it like any
    other pass. The ``None`` §7 reserves belongs to the pass that *parked* — on which
    "the composing stage is not reached" — and this is the pass that answered it.
    """
    engine = FakeAssistantEngine()
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))

    outcome = await engine.resume(card.token, approved=True, timeout=PATIENT)

    assert outcome.routed is not None
    assert outcome.reply is not None
    assert outcome.outbound_statement == OutboundStatement(reach=OutboundReach.NOT_REACHED)


async def test_a_dispatched_read_answer_carries_it() -> None:
    """ADR-0244 §8's resumed turn: a real ``TurnResult`` and a composed reply."""
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")

    outcome = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is ReadAnswerOutcome.DISPATCHED
    assert outcome.reply is not None
    assert outcome.outbound_statement == OutboundStatement(reach=OutboundReach.NOT_REACHED)


async def test_a_restatement_carries_it_although_it_composes_no_prose() -> None:
    """ADR-0264 §7 names ADR-0198 §1's restatement among the three that carry the value.

    It "drives nothing and searches nothing", so there is nothing it could have reached
    — and §7's rendering asymmetry, under which ``NOT_REACHED`` renders only beside a
    reply, is the *surface's* rule rather than a reason to leave the member absent on the
    outcome. The concrete engine carries it here for the same reason, so a fake that did
    not would put a consumer's test on an outcome no engine produces.
    """
    engine = FakeAssistantEngine()
    parked = engine.park("h-1")
    await engine.resume(parked.token, approved=True, timeout=PATIENT)

    restated = await engine.resume(ContinuationToken(handle="h-1"), approved=True, timeout=PATIENT)

    assert restated.reply is None
    assert restated.step is not None
    assert restated.outbound_statement == OutboundStatement(reach=OutboundReach.NOT_REACHED)


# --- §7's other half: the passes it reserves `None` for ---


async def test_a_recovered_park_resume_carries_none() -> None:
    """§7's one ``None`` case, on the shape ADR-0052 §3 ratifies.

    This double parks nothing from a live turn, so its ``resume`` produces the outcome a
    **recovered** park produces after a restart: ADR-0170 §4 composes nothing for it and
    no contact was established, which is "neither established a contact nor composed a
    reply" exactly.
    """
    engine = FakeAssistantEngine()
    parked = engine.park("h-1")

    outcome = await engine.resume(parked.token, approved=True, timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.outbound_statement is None


@pytest.mark.parametrize(
    "answer",
    [ReadAnswerOutcome.UNAVAILABLE_NOW, ReadAnswerOutcome.OPERATION_CHANGED],
)
async def test_a_read_answer_that_dispatched_nothing_carries_none(
    answer: ReadAnswerOutcome,
) -> None:
    """Every read answer but ``DISPATCHED`` returns with ``turn`` and ``reply`` ``None``.

    Nothing was sent and the parked turn's own reply stands (ADR-0244 §9, §10), so the
    pass composed nothing and established nothing — and the concrete engine leaves the
    member absent on the same early return.
    """
    engine = FakeAssistantEngine()
    offered = engine.park_read("h-1", query="bell tower porto")
    engine.read_answers["h-1"] = answer

    outcome = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert outcome.read_answer is answer
    assert outcome.reply is None
    assert outcome.outbound_statement is None


# --- the lever, and the aliasing it must not reopen ---


@pytest.mark.parametrize("reach", list(OutboundReach))
async def test_every_reach_member_is_scriptable(reach: OutboundReach) -> None:
    """The lever exists because **no sequence of surface calls reaches the other two**.

    This double establishes no contact, so ``REACHED`` and ``INDETERMINATE`` — the two a
    surface rendering §7's statement most needs driving over — are otherwise
    unreachable in a consumer's test. The ``destinations`` and ``records`` a ``REACHED``
    names come with the value the test hands over, never from a reach this fake invents.
    """
    scripted = (
        OutboundStatement(
            reach=reach, destinations=(OutboundDestination.SEARCH_PROVIDER,), records=3
        )
        if reach is OutboundReach.REACHED
        else OutboundStatement(reach=reach)
    )
    engine = FakeAssistantEngine()
    engine.outbound_statement = scripted

    outcome = await engine.converse("hello", timeout=PATIENT)

    assert outcome.outbound_statement == scripted


async def test_the_lever_reaches_every_shape_that_carries_a_statement() -> None:
    """One attribute, and not one per call: a renderer is driven over each shape alike.

    The routed answer and the dispatched read are the two a consumer cannot reach by
    scripting ``turn_outcome``, which is why the lever is a member of its own.
    """
    engine = FakeAssistantEngine()
    engine.outbound_statement = OutboundStatement(reach=OutboundReach.INDETERMINATE)
    card = engine.park_routed("h-1", operation=RoutableOperation.FORGET, subject=(_belief(),))
    offered = engine.park_read("h-2", query="bell tower porto")

    routed = await engine.resume(card.token, approved=True, timeout=PATIENT)
    read = await engine.resume(offered.token, approved=True, timeout=PATIENT)

    assert routed.outbound_statement == OutboundStatement(reach=OutboundReach.INDETERMINATE)
    assert read.outbound_statement == OutboundStatement(reach=OutboundReach.INDETERMINATE)


async def test_two_outcomes_never_share_one_statement_object() -> None:
    """The aliasing bug PR #2377's round 4 found in the concrete engine, pinned here.

    ``frozen=True`` stops ``statement.reach = ...`` but **not**
    ``statement.__dict__["reach"] = ...`` (ADR-0018 §3, §4), so one instance handed out
    twice would let a consumer holding either outcome rewrite what the other says this
    system did — every later outcome included. ADR-0264 §7 makes the member "composed
    once per turn", and a value minted per outcome is what makes that true of the object
    as well as of the computation.
    """
    engine = FakeAssistantEngine()

    first = await engine.converse("hello", timeout=PATIENT)
    second = await engine.converse("hello again", timeout=PATIENT)

    assert first.outbound_statement is not None
    assert second.outbound_statement is not None
    assert first.outbound_statement is not second.outbound_statement
    first.outbound_statement.__dict__["reach"] = OutboundReach.REACHED
    assert second.outbound_statement.reach is OutboundReach.NOT_REACHED


async def test_a_scripted_statement_is_copied_rather_than_shared() -> None:
    """Scripting does not reopen the aliasing the default closes.

    A caller handing over one value gets a copy of it per outcome, so rewriting one
    outcome's statement leaves every other outcome — and the scripted value itself —
    saying what it said.
    """
    engine = FakeAssistantEngine()
    scripted = OutboundStatement(reach=OutboundReach.INDETERMINATE)
    engine.outbound_statement = scripted

    first = await engine.converse("hello", timeout=PATIENT)
    second = await engine.converse("hello again", timeout=PATIENT)

    assert first.outbound_statement is not None
    assert second.outbound_statement is not None
    assert first.outbound_statement is not scripted
    first.outbound_statement.__dict__["reach"] = OutboundReach.REACHED
    assert second.outbound_statement.reach is OutboundReach.INDETERMINATE
    assert scripted.reach is OutboundReach.INDETERMINATE


@pytest.mark.parametrize("call", ["converse", "streaming", "spoken"])
async def test_a_scripted_reply_is_given_the_member_it_did_not_carry(call: str) -> None:
    """#2381, one lever further along, on each of the three calls that take it.

    ``turn_outcome`` is what every consumer drives a surface from, so an outcome
    scripted through it reaching a renderer with prose and no statement is the same
    failure the default closed: the renderer is written, tested green, and never reads
    the field. §7 admits no such shape from an engine that established no contact, and
    ADR-0026 §7 is what makes producing one worse than useless — "a fake looser than
    the contract certifies consumers the real implementation will reject".
    """
    engine = FakeAssistantEngine()
    engine.outbound_statement = OutboundStatement(reach=OutboundReach.INDETERMINATE)
    engine.turn_outcome = TurnOutcome(
        turn=None,
        routed=RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED),
        reply="scripted whole",
    )

    if call == "converse":
        outcome = await engine.converse("hello", timeout=PATIENT)
    elif call == "streaming":
        outcome = await _streamed(engine)
    else:
        spoken = await engine.converse_spoken(
            RECORDING, plays=(SpokenAudioFormat.WEBM_OPUS,), timeout=PATIENT
        )
        assert spoken.outcome is not None
        outcome = spoken.outcome

    assert outcome.reply == "scripted whole"
    assert outcome.outbound_statement == OutboundStatement(reach=OutboundReach.INDETERMINATE)


async def test_a_statement_the_caller_scripted_onto_an_outcome_is_never_rewritten() -> None:
    """The fill-in is for an **absent** member and rewrites no value a caller stated."""
    engine = FakeAssistantEngine()
    engine.outbound_statement = OutboundStatement(reach=OutboundReach.INDETERMINATE)
    engine.turn_outcome = TurnOutcome(
        turn=None,
        routed=RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED),
        reply="scripted whole",
        outbound_statement=OutboundStatement(
            reach=OutboundReach.REACHED,
            destinations=(OutboundDestination.SEARCH_PROVIDER,),
            records=2,
        ),
    )

    outcome = await engine.converse("hello", timeout=PATIENT)

    assert outcome.outbound_statement == OutboundStatement(
        reach=OutboundReach.REACHED, destinations=(OutboundDestination.SEARCH_PROVIDER,), records=2
    )


async def test_a_scripted_outcome_that_composed_nothing_is_given_no_statement() -> None:
    """A reply-less outcome is left alone, because §7 admits both values on one shape.

    A recovered park carries ``None`` and ADR-0198 §1's restatement carries
    ``NOT_REACHED``, and nothing in an outcome's shape tells them apart — so filling one
    in here would assert what the caller did not. A caller who means one states it.
    """
    engine = FakeAssistantEngine()
    engine.outbound_statement = OutboundStatement(reach=OutboundReach.INDETERMINATE)
    engine.turn_outcome = TurnOutcome(turn=None)

    outcome = await engine.converse("hello", timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.outbound_statement is None


async def test_a_scripted_statement_whose_copy_method_lies_is_rebuilt_anyway() -> None:
    """``model_copy`` is the caller's to override, and this engine does not depend on it.

    A subject whose override returned ``self`` would hand one instance to every outcome
    and reopen the aliasing :meth:`FakeAssistantEngine._outbound` exists to close —
    silently, and only for the consumer that subclassed. The statement is rebuilt from
    its declared fields instead, so what every outcome carries is an exact
    ``OutboundStatement`` of its own.
    """

    class _Sticky(OutboundStatement):
        """An ``OutboundStatement`` that hands back itself instead of a copy."""

        def model_copy(self, **kwargs: object) -> _Sticky:
            """Return this very instance, as an unhelpful subclass might."""
            return self

    engine = FakeAssistantEngine()
    engine.outbound_statement = _Sticky(reach=OutboundReach.INDETERMINATE)

    first = await engine.converse("hello", timeout=PATIENT)
    second = await engine.converse("hello again", timeout=PATIENT)

    assert first.outbound_statement is not None
    assert second.outbound_statement is not None
    assert first.outbound_statement is not second.outbound_statement
    assert type(first.outbound_statement) is OutboundStatement
    first.outbound_statement.__dict__["reach"] = OutboundReach.REACHED
    assert second.outbound_statement.reach is OutboundReach.INDETERMINATE

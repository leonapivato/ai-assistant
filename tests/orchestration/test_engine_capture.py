"""What one captured episode records, after ADR-0221's capture flip (§12, Lane E).

Three facts move at the capture point and this module is where each is pinned.
``outcome`` stops carrying one of sixteen constant phrases and carries **the
composed reply, whole** (§1); ``disposition`` carries what became of the pass as a
member of §2's closed vocabulary; and ``capture.modality`` carries how the user
material the episode renders reached this system (§5).

ADR-0221 §11's tests 1, 2, 3, 4, 10, 11, 12, 13, 14 and 15 live here, each named in
the case that discharges it, plus issue #1873's population — a record carrying a
``disposition`` beside an ``outcome`` of ``None``, which this flip is the first
thing in the system to write.

**Two of §11's cases are about what does *not* happen**, and they are the ones worth
reading first. Test 4 asserts that a distinctive span in a captured reply reaches no
prompt the observer, the planner or the composer assembled: the reply is stored,
rendered nowhere, and available to the lane that decides to read it. §13's second
bullet defers every such reader, and each owes #672's escaping fix and newline
normalisation before it renders a reply into the observer's line-oriented batch — so
:func:`test_a_captured_replys_distinctive_span_reaches_no_prompt` is "the test a
reader lane must consciously delete". Test 14 asserts the same of the logs.
"""

from __future__ import annotations

import json
from base64 import b64encode
from typing import TYPE_CHECKING, Final, ForwardRef, TypeAliasType, get_args, get_type_hints

import structlog
from pydantic import BaseModel, SecretStr
from test_engine import (
    CAPABILITY,
    PATIENT,
    Harness,
    NoStepPlanner,
    OneStepPlanner,
    _fresh_facade,
    confirmable,
    tool,
)
from test_engine_routing import (
    _BELIEF,
    _QUERY,
    _UTTERANCE,
    _names,
    _routed_harness,
    _seed_belief,
    _token,
)

from ai_assistant.core import types as core_types
from ai_assistant.core.errors import ConversationStoreError, MemoryStoreError
from ai_assistant.core.protocols import SecretStore
from ai_assistant.core.types import (
    Capture,
    Disposition,
    EpisodicMemory,
    ExchangeDisposition,
    Modality,
    RoutableOperation,
    RouteOutcome,
    SpokenAudio,
    SpokenAudioFormat,
    TurnOutcome,
)
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.orchestration import composing
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.planning import ModelBackedPlanner
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
    StreamAttempt,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import datetime

    from ai_assistant.core.types import (
        ConversationTurn,
        MemoryRecord,
        MemoryWrite,
        ParkedBinding,
        ReplyChunk,
        SpokenDelivery,
    )

#: A reply with the two properties §1's "whole" is about: it is longer than any
#: phrase this field used to carry, and it spans several lines. A store or a capture
#: point that clipped, joined or normalised it fails on the byte comparison rather
#: than on a length.
_LONG_REPLY: Final = (
    "I would not book that flight, because the fare you quoted is a basic economy "
    "fare and your bag would cost more than the difference.\n"
    "\n"
    "Two things follow from that. The first is that the cheaper itinerary is only "
    "cheaper if you travel with a personal item alone, which you have not done on "
    "any of the last four trips.\n"
    "The second is that the return leg lands after the last train, so the saving is "
    "spent on the taxi and then some."
)

#: A span nothing else in any fixture carries, so its appearance in an assembled
#: prompt or a log payload can only have come from the stored reply. Deliberately not
#: a word of the utterance, the goal statement or any phrase in §2's table.
_SPAN: Final = "zarquon-seven-marmalade"

_SPOKEN_REPLY: Final = f"You went hiking on Tuesday, {_SPAN}."

_MP4: Final = SpokenAudioFormat.MP4
_RECORDING: Final = SpokenAudio(content=b64encode(b"an utterance").decode("ascii"), media_type=_MP4)
_ASKED: Final = "what did I do this week"


def _episodes(records: Sequence[MemoryRecord]) -> list[EpisodicMemory]:
    """Every episode among ``records``, in the order the store returned them."""
    return [record for record in records if isinstance(record, EpisodicMemory)]


async def _captured(harness: Harness) -> list[EpisodicMemory]:
    """Every episode the harness's memory store holds, in write order."""
    return _episodes(await harness.memory.export())


def _replying(reply: str) -> ComposingStage:
    """A composing stage whose whole-answer seam returns ``reply``."""
    return ComposingStage(model=FakeModelProvider(reply), streaming=FakeStreamingCompleter())


def _streaming(*deltas: str, fails: bool = False) -> ComposingStage:
    """A composing stage whose streaming seam yields ``deltas``, then maybe fails."""
    return ComposingStage(
        model=FakeModelProvider(),
        streaming=FakeStreamingCompleter(script=(StreamAttempt(deltas=deltas, fails=fails),)),
    )


async def _drain(stream: AsyncIterator[ReplyChunk | TurnOutcome]) -> TurnOutcome:
    """Read one streamed turn whole and return its terminal outcome."""
    outcome: TurnOutcome | None = None
    async for value in stream:
        if isinstance(value, TurnOutcome):
            outcome = value
    assert outcome is not None, "ADR-0173 §4: the outcome is always the last value"
    return outcome


# --- §11 test 1: the reply round-trips whole ---------------------------------


async def test_the_captured_episode_carries_the_composed_reply_whole() -> None:
    """§11 test 1: a multi-line reply of a few hundred characters, byte for byte.

    §1: capture "writes that reply into the captured episode's ``outcome``, and writes
    it **whole**. No implementation, setting or later lane stores a prefix, a summary,
    an elision or any other lossy rendering of it there." The comparison is on the
    exact string rather than on a length or a prefix, because that is the only
    assertion a summariser and a clipper both fail.

    **Read back out of the store rather than off the capture call**, so what is pinned
    is what a later reader would find. §11 test 1 asks for this through the
    ``MemoryStore`` conformance suite as well; ``outcome``'s type, nullability and
    (absent) length bound are unchanged by §8, so no *new* per-implementation
    persistence property exists, and the conformance suite already round-trips this
    field beside the two ADR-0221 added.
    """
    harness = Harness(composing=_replying(_LONG_REPLY), planner=NoStepPlanner())

    outcome = await harness.engine.converse("should I book it?", timeout=PATIENT)

    assert outcome.reply == _LONG_REPLY
    (episode,) = await _captured(harness)
    assert episode.outcome == _LONG_REPLY, "the whole reply, byte for byte (§1)"
    assert "\n" in episode.outcome, "several lines, so a joiner fails here rather than silently"
    assert episode.disposition is ExchangeDisposition.NO_ACTION_NEEDED


# --- §11 test 2: the five no-reply paths, and #1873's population --------------


async def test_a_step_parked_for_confirmation_captures_no_reply() -> None:
    """§11 test 2, path one: ``_compose`` returns nothing, so ``outcome`` is ``None``.

    ADR-0170 §4: what the user must answer is the ``Confirmation``, and a second
    model-written account of the same pending action beside it is where the two can
    disagree. The episode still records **what became of the pass**, which is the
    whole point of §2's field: a record whose ``outcome`` is ``None`` used to be
    unreadable and now states its own disposition.
    """
    harness = Harness(tools=(confirmable(),), planner=OneStepPlanner())

    parked = await harness.engine.converse("send the note", timeout=PATIENT)

    assert parked.step is not None
    assert parked.step.disposition is Disposition.AWAITING_CONFIRMATION
    assert parked.reply is None
    (episode,) = await _captured(harness)
    assert episode.outcome is None
    assert episode.disposition is ExchangeDisposition.STEP_AWAITING_CONFIRMATION


async def test_a_routed_park_captures_no_reply() -> None:
    """§11 test 2, path two: a routed park "owes no answer at all" (ADR-0197 §10).

    ``_finish_route`` is handed ``compose=None`` there, so the composing stage is not
    reached, originates no model call, and there is no reply for ``outcome`` to carry.
    """
    harness = _routed_harness()
    await _seed_belief(harness.memory)

    parked = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)

    assert parked.routed is not None
    assert parked.routed.outcome is RouteOutcome.AWAITING_CONFIRMATION
    assert parked.reply is None
    (episode,) = await _captured(harness)
    assert episode.outcome is None
    assert episode.disposition is ExchangeDisposition.ROUTED_AWAITING_CONFIRMATION


async def test_a_resume_driven_from_a_recovered_park_captures_no_reply() -> None:
    """§11 test 2, path three: no turn, so nothing to compose from (ADR-0052 §3).

    ``_compose`` declines on a pass whose ``turn`` is ``None`` because "context and
    memories were never persisted and there is nothing to compose from" — which is a
    different reason from the park's and reaches the same ``None``.
    """
    harness = Harness(tools=(confirmable(),), planner=OneStepPlanner())
    await harness.engine.converse("send the note", timeout=PATIENT)

    fresh = _fresh_facade(harness)
    pending = await fresh.pending_confirmations()
    assert len(pending) == 1
    recovered = await fresh.resume(pending[0].token, approved=True, timeout=PATIENT)

    assert recovered.turn is None, "a recovered park has no live turn (ADR-0052 §3)"
    assert recovered.reply is None
    resumption = (await _captured(harness))[-1]
    assert resumption.outcome is None
    assert resumption.disposition is ExchangeDisposition.STEP_EXECUTED


async def test_a_classified_composition_failure_captures_no_reply() -> None:
    """§11 test 2, path four: a ``ComposedReply`` whose ``text`` is ``None``.

    ADR-0170 §8's classified failure, the blank completion included. The pass reports
    it on ``reply_degraded`` and the episode records that the assistant said nothing —
    which is true, and is what distinguishes this from path five only in cause.
    """
    harness = Harness(composing=_replying(""), planner=NoStepPlanner())

    outcome = await harness.engine.converse("say something", timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.reply_degraded is True
    (episode,) = await _captured(harness)
    assert episode.outcome is None
    assert episode.disposition is ExchangeDisposition.NO_ACTION_NEEDED


async def test_a_stream_that_published_nothing_captures_no_reply() -> None:
    """§11 test 2, path five: the stream stopped before its first chunk.

    ADR-0173 §6's pre-commit degradation. Nothing was published, so this is not a
    truncation and there is no text to store — which is exactly why §1's cut-stream
    clause and this one are two clauses and not one.
    """
    harness = Harness(composing=_streaming(fails=True), planner=NoStepPlanner())

    outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert outcome.reply is None
    assert outcome.reply_degraded is True
    (episode,) = await _captured(harness)
    assert episode.outcome is None
    assert episode.disposition is ExchangeDisposition.NO_ACTION_NEEDED


async def test_a_no_reply_record_renders_its_phrase_and_nothing_else_at_all_three_sites() -> None:
    """Issue #1873: the population this flip is the first to write.

    A record carrying a ``disposition`` beside an ``outcome`` of ``None`` did not exist
    before ADR-0221 — a pre-change episode always carried a phrase and a harness row
    always carries assistant text — so no render-site case covered it. §3's rule reads
    ``disposition`` **first**, so the fallback is never consulted and the ``None`` never
    reaches a formatter.

    Driven end to end over a record the **engine captured**, because that is the half
    the three per-site cases cannot show: they build their own record, and what #1873 is
    about is that this shape now arrives from production capture. The real planner and
    the real observer stand behind recording providers for test 4's reason — a fake
    assembles no prompt, and the render sites live inside the producers.
    """
    phrase = "the selected tool ran"
    goals = iter(f"g-{n}" for n in range(1, 10))
    planning_model = FakeModelProvider(
        json.dumps(
            {
                "rationale": "one step",
                "steps": [{"intent": "send it", "capability": CAPABILITY, "parameters": {}}],
            }
        )
    )
    observing_model = FakeModelProvider(json.dumps({"beliefs": []}))
    # A blank completion, which is ADR-0170 §8's classified composition failure and one
    # of §1's five no-reply paths. It is the path that reaches all three sites: the four
    # others each end the pass at a park or a recovered resume, where the composing
    # stage is not reached at all on the *following* turn either.
    composing_model = FakeModelProvider("")
    harness = Harness(
        tools=(tool(),),
        planner=ModelBackedPlanner(planning_model),
        observer=ModelBackedObserver(observing_model),
        composing=ComposingStage(model=composing_model, streaming=FakeStreamingCompleter()),
        loop_id_factory=lambda: next(goals),
    )

    first = await harness.engine.converse("send the note", timeout=PATIENT)
    assert first.conversation_id is not None
    assert first.reply is None
    assert first.reply_degraded is True
    (episode,) = await _captured(harness)
    assert (episode.outcome, episode.disposition) == (
        None,
        ExchangeDisposition.STEP_EXECUTED,
    ), "the shape #1873 is about: a member, and no reply beside it"

    await harness.engine.converse(
        "and again", timeout=PATIENT, conversation_id=first.conversation_id
    )
    await harness.engine.observe(conversation_id=first.conversation_id)

    for name, provider in (
        ("planner", planning_model),
        ("observer", observing_model),
        ("composer", composing_model),
    ):
        rendered = _assembled(provider)
        assert phrase in rendered, f"the {name} rendered the member's phrase for this record"
        for line in rendered.splitlines():
            if phrase in line:
                assert "None" not in line, (
                    "the absent outcome is never consulted, so never rendered"
                )


# --- §11 test 3: a cut stream stores what it published -----------------------


async def test_a_stream_cut_by_a_mid_stream_failure_stores_what_it_published() -> None:
    """§11 test 3, first shape: a ``ModelError`` after at least one chunk.

    §1: "on the ceiling stop (ADR-0173 §3) and on a mid-stream ``ModelError`` alike,
    ``ComposedReply.text`` is the text the stage emitted, and no continuation of it was
    ever composed", so what is stored is the whole of what the assistant said rather
    than a prefix of something longer. Discarding it would make the episode of a cut
    turn read as an exchange in which the assistant said nothing, which is false of
    every one of them.
    """
    harness = Harness(composing=_streaming("You prefer", fails=True), planner=NoStepPlanner())

    outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert outcome.reply == "You prefer"
    assert outcome.reply_degraded is True
    (episode,) = await _captured(harness)
    assert episode.outcome == "You prefer"
    assert episode.model_fields_set >= {"outcome", "disposition"}
    assert not hasattr(episode, "reply_cut_short"), (
        "§1: no field is added recording that a stored reply was cut short — whether "
        "the pass completed is the TurnOutcome's to report, and it reports it"
    )


async def test_a_stream_stopped_at_the_ceiling_stores_what_it_published() -> None:
    """§11 test 3, second shape: ADR-0173 §3's ceiling stop.

    The limit is **measured** off a whole-answer pass rather than asserted, exactly as
    ``test_engine_streaming`` measures it, so the boundary is the engine's own figure
    and not this module's arithmetic about it.
    """
    whole = Harness(composing=_streaming("You prefer", " ", "hiking."), planner=NoStepPlanner())
    unbounded = await _drain(whole.engine.converse_streaming("hello", timeout=PATIENT))
    assert unbounded.reply == "You prefer hiking."
    exact = len(canonical_payload(unbounded))

    harness = Harness(composing=_streaming("You prefer", " ", "hiking."), planner=NoStepPlanner())
    harness.engine._max_payload_bytes = exact - 1

    outcome = await _drain(harness.engine.converse_streaming("hello", timeout=PATIENT))

    assert outcome.reply == "You prefer"
    assert outcome.reply_degraded is True
    (episode,) = await _captured(harness)
    assert episode.outcome == "You prefer", "the published text, not a prefix of a longer answer"


# --- §11 test 12: a routed pass -----------------------------------------------


async def test_a_routed_passs_episode_carries_a_routed_member_and_its_reply() -> None:
    """§11 test 12: the ``ROUTED_*`` member, the reply, and none of the account.

    ADR-0197 §10 binds unchanged after ADR-0221 and the reason is mechanical: §6 gives
    the composing stage two enum values and nothing else, so a routed reply *cannot*
    contain what §6 withholds. The episode therefore carries the composed reply and
    still no listing, no display subject, no scalar argument and no candidate.
    """
    reply = f"I have forgotten it, {_SPAN}."
    harness = _routed_harness(
        router=_names(RoutableOperation.FORGET, _QUERY), composing=_replying(reply)
    )
    await _seed_belief(harness.memory)

    parked = await harness.engine.converse(_UTTERANCE, timeout=PATIENT)
    resumed = await harness.engine.resume(_token(parked), approved=True, timeout=PATIENT)

    assert resumed.routed is not None
    assert resumed.routed.outcome is RouteOutcome.PERFORMED
    resolution = (await _captured(harness))[-1]
    assert resolution.disposition is ExchangeDisposition.ROUTED_PERFORMED
    assert resolution.outcome == reply
    for account in (_QUERY, _BELIEF, "the user likes jazz"):
        assert account not in resolution.content, "ADR-0197 §10: no part of the routed account"
        assert account not in (resolution.outcome or "")


# --- §11 tests 10 and 11: the modality ----------------------------------------


async def test_a_typed_turn_and_a_streamed_turn_each_capture_text() -> None:
    """§11 test 10's second half: ``converse`` and ``converse_streaming`` carry ``TEXT``.

    §5: ``TEXT`` "is the default and says it did not [reach this system as speech]:
    true of a typed turn". Both entries are asserted because the value of the clause is
    that they agree — a lane that threaded the modality through one composer and not
    the other would pass on one of them.
    """
    typed = Harness(composing=_replying("Noted."), planner=NoStepPlanner())
    await typed.engine.converse("I went hiking", timeout=PATIENT)

    streamed = Harness(composing=_streaming("Noted."), planner=NoStepPlanner())
    await _drain(streamed.engine.converse_streaming("I went hiking", timeout=PATIENT))

    for harness in (typed, streamed):
        (episode,) = await _captured(harness)
        assert episode.capture == Capture(modality=Modality.TEXT)


async def test_a_spoken_turns_episode_carries_speech_and_the_spoken_reply() -> None:
    """§11 test 10's first half: the pass of ``converse_spoken`` and no other.

    §5: capture writes ``SPEECH`` "exactly where ``Engine._capture`` is given a
    ``_SpokenCapture`` — the passes of ``AssistantEngine.converse_spoken`` and no
    other". What the field says is that the goal statement in ``content`` is a
    **transcript**, a lossy derivation a model produced from audio; it says nothing
    about the reply in ``outcome``, which this system composed as text on every pass.
    """
    harness = Harness(
        composing=_replying(_SPOKEN_REPLY),
        planner=NoStepPlanner(),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    (episode,) = await _captured(harness)
    assert episode.capture.modality is Modality.SPEECH
    assert episode.outcome == _SPOKEN_REPLY
    assert _ASKED in episode.content, "the transcript is what the modality is about"


async def test_a_spoken_pass_that_routed_still_carries_speech() -> None:
    """§11 test 10's middle: ``SPEECH`` "whether or not that pass routed" (§5).

    A routed pass produces no ``TurnResult``, so its episode renders the **utterance**
    threaded to the capture point (ADR-0197 §10) — which is still the material the user
    supplied, and on this operation it reached the system as speech. An implementation
    that read the modality off the turn rather than off the operation would record this
    one as typed.
    """
    harness = _routed_harness(
        router=_names(RoutableOperation.RECENT_READS),
        transcriber=FakeSpeechTranscriber(transcripts=["what have you read lately"]),
    )

    spoken = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert spoken.outcome is not None
    assert spoken.outcome.routed is not None
    (episode,) = await _captured(harness)
    assert episode.capture.modality is Modality.SPEECH
    assert episode.disposition is not None
    assert episode.disposition.value.startswith("routed_")


async def test_a_step_parks_resolution_carries_the_parked_turns_modality() -> None:
    """§11 test 11's first arm: retained, never recomputed.

    §5's second case: the resolution's episode "renders user material an earlier pass
    received … The value carried is that turn's own, retained with the parked turn and
    applied unchanged. No implementation re-evaluates, recomputes or defaults it at the
    second capture." The resuming ``resume`` call hands no ``_SpokenCapture`` at all, so
    an implementation deriving the value at the capture point from what it was handed
    would record ``TEXT`` here — and would say a transcript was typed.
    """
    harness = Harness(
        tools=(confirmable(),),
        planner=OneStepPlanner(),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )

    parked = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)
    assert parked.outcome is not None
    assert parked.outcome.step is not None
    assert parked.outcome.step.confirmation is not None
    await harness.engine.resume(
        parked.outcome.step.confirmation.token, approved=True, timeout=PATIENT
    )

    park, resolution = await _captured(harness)
    assert park.capture.modality is Modality.SPEECH
    assert resolution.capture.modality is Modality.SPEECH, "the parked turn's own value (§5)"
    assert resolution.disposition is ExchangeDisposition.STEP_EXECUTED


async def test_a_routed_parks_resolution_carries_text_even_where_the_parking_pass_spoke() -> None:
    """§11 test 11's second arm, which is the one that separates the two questions.

    §5's third case: this episode "carries neither a turn nor an utterance and renders
    the bare fact of the resumption alone", so ``TEXT`` is true of what it holds rather
    than a default it falls back on — and it holds even though the pass that *parked*
    was spoken. "The pass was spoken" and "the episode renders spoken material" are
    different claims, and this is where an implementation conflating them fails.
    """
    harness = _routed_harness(transcriber=FakeSpeechTranscriber(transcripts=[_UTTERANCE]))
    await _seed_belief(harness.memory)

    parked = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)
    assert parked.outcome is not None
    await harness.engine.resume(_token(parked.outcome), approved=True, timeout=PATIENT)

    park, resolution = await _captured(harness)
    assert park.capture.modality is Modality.SPEECH, "the parking pass rendered the utterance"
    assert resolution.capture.modality is Modality.TEXT, "and this one renders no user material"
    assert "The user asked:" not in resolution.content


async def test_a_resumption_recovered_from_durable_state_carries_text() -> None:
    """§11 test 11's third arm: no turn to retain from (§5's third case).

    A recovered park has no live turn, so its episode carries no goal statement and no
    plan rationale of any turn — the same partition, at the same site, that ADR-0204
    §2's fifth clause already draws for the withholding stamp.
    """
    harness = Harness(
        tools=(confirmable(),),
        planner=OneStepPlanner(),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )
    await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    fresh = _fresh_facade(harness)
    pending = await fresh.pending_confirmations()
    assert len(pending) == 1
    recovered = await fresh.resume(pending[0].token, approved=True, timeout=PATIENT)

    assert recovered.turn is None
    resumption = (await _captured(harness))[-1]
    assert resumption.capture.modality is Modality.TEXT
    assert "The user asked:" not in resumption.content


# --- §11 test 15: the origin mark is not stamped ------------------------------


async def test_a_captured_episodes_provenance_is_not_marked_external() -> None:
    """§11 test 15: ``derived_from_external`` is ``False``, so §6 is pinned.

    §6 declines the mark and says why: stamping it would change the composing prompt's
    origin phrase — the one thing §3's byte-identity property exists to detect — and
    would remove ADR-0181 §5's automatic ``ALLOW`` for the egress calls of every later
    turn in a conversation that has once held a stamped record. Both reach subsystems
    ADR-0221 does not touch, so the mark is owed its own decision, and this test is what
    makes a later lane change it deliberately.

    Asserted on both shapes the flip writes — a reply-bearing episode and a no-reply
    one — because the mark's absence is a property of capture rather than of the reply.
    """
    replying = Harness(composing=_replying(_LONG_REPLY), planner=NoStepPlanner())
    await replying.engine.converse("should I book it?", timeout=PATIENT)
    parking = Harness(tools=(confirmable(),), planner=OneStepPlanner())
    await parking.engine.converse("send the note", timeout=PATIENT)

    for harness in (replying, parking):
        (episode,) = await _captured(harness)
        assert episode.provenance.derived_from_external is False
        assert "derived_from_external" not in episode.provenance.model_fields_set, (
            "§6: capture writes the field exactly as it does today — it is not set, and "
            "takes its False default"
        )


# --- §11 test 13: the Tier 0 reliance, at the seam it rests on -----------------


def _annotation_types(annotation: object, seen: set[int] | None = None) -> list[object]:
    """Every type this annotation names, at any depth, with aliases followed.

    Three things make a hand-written walk necessary rather than fussy, and each of them
    is a way a shallower check would answer "no secret here" about an annotation that
    has one.

    - **A PEP 695 alias is opaque to ``get_args``.** ``SecretValue`` is
      ``type SecretValue = Annotated[SecretStr, …]``, and ``get_args`` of a
      ``TypeAliasType`` is empty — so a walk that did not resolve ``__value__`` would
      stop at the alias and never see :class:`~pydantic.SecretStr`. That is not
      hypothetical: it is how the first version of this test passed with a
      ``SecretValue`` field added to :class:`~ai_assistant.core.types.Goal`.
    - **A union, a tuple element and a mapping value are all type arguments**, so one
      recursion over ``get_args`` reaches every position a field can hold a value in.
    - **Some aliases in this module are recursive** — ``FrozenJson`` names itself — so
      the walk carries the identities it has already resolved and stops at a cycle
      rather than at a recursion limit.
    """
    seen = set() if seen is None else seen
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    if id(annotation) in seen:
        return []
    seen.add(id(annotation))
    found: list[object] = [annotation]
    for argument in get_args(annotation):
        found.extend(_annotation_types(argument, seen))
    return found


def _models_in(annotation: object) -> list[type[BaseModel]]:
    """Every pydantic model this annotation names, at any depth."""
    return [
        found
        for found in _annotation_types(annotation)
        if isinstance(found, type) and issubclass(found, BaseModel)
    ]


def _reachable_from_the_composing_stage() -> dict[str, type[BaseModel]]:
    """Every model reachable from what ``ComposingStage.compose`` is handed on a turn.

    Starts at the method's own resolved parameter annotations — so the roster is read
    off the seam rather than restated from memory — and closes over each model's fields
    transitively. ``get_type_hints`` is given both modules' namespaces because the
    signature is written under ``from __future__ import annotations`` and names types
    from each.
    """
    hints = get_type_hints(ComposingStage.compose, globalns=vars(core_types) | vars(composing))
    queue = [
        model
        for name, annotation in hints.items()
        if name != "return"
        for model in _models_in(annotation)
    ]
    reached: dict[str, type[BaseModel]] = {}
    while queue:
        model = queue.pop()
        if model.__name__ in reached:
            continue
        reached[model.__name__] = model
        for field in model.model_fields.values():
            queue.extend(_models_in(field.annotation))
    return reached


def test_the_composing_stages_supply_is_enumerated_so_a_new_field_must_be_judged() -> None:
    """§11 test 13: §7's reliance, stated rather than assumed.

    §7: capture "stores the reply without inspecting it for a Tier 0 value, and no
    implementation adds such an inspection on this path. The reliance is that the
    composing stage is supplied nothing holding a Tier 0 value, which ADR-0004 §3
    secures by residency: Tier 0 secrets live in the OS keyring, are read through
    ``SecretStore`` by ``models/`` and ``tools/`` alone, and are in no record, facet,
    plan or step account the composing stage is given."

    Residency is not a property a test can assert directly, so what is asserted is the
    **whole object graph** the stage is handed: the four arguments it takes on a turn,
    and every model reachable from them transitively. A guard over the top-level models
    alone would miss the case that matters — a secret-carrying field added to ``Goal``,
    to a facet, or to a provenance would reach the composer while a shallow roster still
    passed.

    Two assertions, and they fail for different reasons. The **roster** fails when the
    graph grows: a new model reaching the stage is a new thing to judge, and §7 makes
    that judgement the implementing lane's rather than an assumption left implicit. The
    **carrier** check fails when any field on any of them admits ``SecretStr`` — which
    is what :data:`~ai_assistant.core.types.SecretValue` is built on and what every
    Tier 0 value in this system is typed with.

    Nothing here claims the fields listed are safe on some other ground; it claims the
    set cannot grow, and no secret can enter it, without someone noticing.
    """
    reachable = _reachable_from_the_composing_stage()

    assert set(reachable) == {
        "ActionPlan",
        "Attestation",
        "CalendarFacet",
        "Capture",
        "Confirmation",
        "ConfirmationEgress",
        "ContinuationToken",
        "CurrentContext",
        "EgressDestination",
        "EgressSpan",
        "EmailFacet",
        "EpisodicMemory",
        "ExecutionState",
        "Goal",
        "Placement",
        "PlanStep",
        "PreferenceMemory",
        "ProceduralMemory",
        "Provenance",
        "ReportedExtent",
        "SemanticMemory",
        "SpokenDelivery",
        "StepExecution",
        "StepFailure",
        "StepOutcome",
        "TurnResult",
        "Validity",
    }, (
        "the whole graph the composing stage is supplied on a turn — the records, the "
        "facets, the plan and the step account, and everything they carry. A model that "
        "joined it is a model ADR-0221 §7's reliance now rests on"
    )

    for name, model in sorted(reachable.items()):
        for field_name, field in model.model_fields.items():
            resolved = _annotation_types(field.annotation)
            # An unresolved forward reference is a hole in this check rather than a
            # clean field: the walk cannot see through a `ForwardRef`, so a secret
            # behind one would pass silently. Refusing it is what keeps the assertion
            # below meaning what it says.
            assert not any(isinstance(found, ForwardRef) for found in resolved), (
                f"{name}.{field_name} carries an unresolved forward reference, so the "
                f"walk below cannot see what it admits; rebuild the model or name the "
                f"type where it is defined"
            )
            carriers = [found for found in resolved if found in {SecretStr, SecretStore}]
            assert not carriers, (
                f"{name}.{field_name} admits {carriers}; ADR-0221 §7's reliance is that "
                f"the composing stage is supplied nothing holding a Tier 0 value, and "
                f"this field would carry one straight into the composed reply"
            )


# --- §11 tests 4 and 14: the reply reaches no prompt and no log ---------------


def _assembled(*providers: FakeModelProvider) -> str:
    """Every message every one of ``providers`` was ever handed, joined."""
    return "\n".join(
        message.content
        for provider in providers
        for call in provider.calls
        for message in call.messages
    )


async def test_a_captured_replys_distinctive_span_reaches_no_prompt() -> None:
    """§11 test 4. **This is the test a reader lane must consciously delete.**

    §3: "A record carrying a ``disposition`` has its ``outcome`` rendered into no model
    prompt by any of them", and the fallback is the whole of the safety argument — a
    post-change episode renders the phrase for its disposition, which is the string a
    pre-change episode of the same shape carried, so the prompt is byte-identical and
    the reply reaches no model.

    Driven end to end rather than at the render sites, because that is what §11 test 4
    asks for: a reply is captured carrying a span nothing else in the fixture holds, a
    **further turn of the same conversation** runs so the episode enters the next
    turn's supply, and an **observation pass** runs over it. The real planner and the
    real observer stand behind recording providers, because a fake assembles no prompt
    and the render sites live inside the producers.

    §13's second bullet is what this defends: every reader of the stored reply is
    deferred, and each owes #672's escaping fix *and* newline normalisation before it
    renders a reply into the observer's line-oriented batch. A lane that wants the
    reply in a prompt deletes this case deliberately and pays those costs.
    """
    planning_model = FakeModelProvider(
        json.dumps(
            {
                "rationale": "one step",
                "steps": [{"intent": "send it", "capability": CAPABILITY, "parameters": {}}],
            }
        )
    )
    observing_model = FakeModelProvider(json.dumps({"beliefs": []}))
    composing_model = FakeModelProvider(f"You went hiking, {_SPAN}.")

    goals = iter(f"g-{n}" for n in range(1, 10))
    harness = Harness(
        tools=(tool(),),
        planner=ModelBackedPlanner(planning_model),
        observer=ModelBackedObserver(observing_model),
        composing=ComposingStage(model=composing_model, streaming=FakeStreamingCompleter()),
        # A fresh goal id per turn: the second turn of one conversation is a second
        # objective, and a store that saw one id twice with two statements refuses it.
        loop_id_factory=lambda: next(goals),
    )

    first = await harness.engine.converse("what did I do?", timeout=PATIENT)
    assert first.conversation_id is not None
    (episode,) = await _captured(harness)
    assert episode.outcome is not None
    assert _SPAN in episode.outcome, "the span is in the store, which is the precondition"
    assert episode.disposition is ExchangeDisposition.STEP_EXECUTED

    await harness.engine.converse(
        "and what else?", timeout=PATIENT, conversation_id=first.conversation_id
    )
    await harness.engine.observe(conversation_id=first.conversation_id)

    assembled = _assembled(planning_model, observing_model, composing_model)
    assert _SPAN not in assembled, (
        "ADR-0221 §3: a record carrying a disposition has its outcome rendered into no "
        "model prompt by the observer, the planner or the composer"
    )
    assert "the selected tool ran" in assembled, (
        "and what is rendered in its place is §2's phrase for the disposition, which is "
        "the string a pre-change episode of the same shape carried"
    )


async def test_no_log_on_the_capture_or_observation_path_carries_the_reply() -> None:
    """§11 test 14: ADR-0004 §5 names "message bodies" a redaction target.

    The capture path logs only where something failed, so the degraded routes are the
    ones worth driving: a refused ``append`` writes ``conversation_capture_degraded``
    before the episode exists, and a refused episode write logs the same event after
    the reply is in hand. Both are exercised beside the happy path and an observation
    pass, and none of them may carry a word of the reply.
    """

    class _RefusingStore(FakeMemoryStore):
        """A store whose episode write is refused, so capture degrades with a reply in hand."""

        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            msg = "the store is down"
            raise MemoryStoreError(msg)

    class _RefusingIndex(FakeConversationStore):
        """An index whose ``append`` is refused, which is capture's *other* logging branch.

        ``ConversationLifecycle.capture`` logs ``conversation_capture_degraded`` twice
        over, at two stages and from two except blocks, and the reply is in hand at
        both. Driving only the episode-write branch would leave a future change that
        logged the reply at the append branch undetected.
        """

        async def append(
            self,
            conversation_id: str,
            *,
            occurred_at: datetime,
            parked: ParkedBinding | None = None,
            delivery: SpokenDelivery | None = None,
        ) -> ConversationTurn:
            msg = "the index is down"
            raise ConversationStoreError(msg)

    observing_model = FakeModelProvider(json.dumps({"beliefs": []}))
    with structlog.testing.capture_logs() as captured:
        happy = Harness(
            composing=_replying(f"Certainly, {_SPAN}."),
            planner=NoStepPlanner(),
            observer=ModelBackedObserver(observing_model),
        )
        outcome = await happy.engine.converse("go on", timeout=PATIENT)
        assert outcome.conversation_id is not None
        await happy.engine.observe(conversation_id=outcome.conversation_id)

        refusing = Harness(
            composing=_replying(f"Certainly, {_SPAN}."),
            planner=NoStepPlanner(),
            memory=_RefusingStore(now=happy.clock),
        )
        degraded = await refusing.engine.converse("go on", timeout=PATIENT)
        assert degraded.capture_degraded is True
        assert degraded.reply == f"Certainly, {_SPAN}."

        unindexed = Harness(
            composing=_replying(f"Certainly, {_SPAN}."),
            planner=NoStepPlanner(),
            conversation_store=_RefusingIndex(now=happy.clock),
        )
        unappended = await unindexed.engine.converse("go on", timeout=PATIENT)
        assert unappended.capture_degraded is True
        assert unappended.reply == f"Certainly, {_SPAN}."

    stages = {
        event.get("stage")
        for event in captured
        if event["event"] == "conversation_capture_degraded"
    }
    assert stages == {"append", "episode"}, (
        "both of capture's logging branches ran, so the assertion below has both subjects"
    )
    assert not any(_SPAN in json.dumps(event, default=str) for event in captured), (
        "ADR-0221 §11 test 14: no log event on the capture or observation path carries "
        "the captured reply's text"
    )

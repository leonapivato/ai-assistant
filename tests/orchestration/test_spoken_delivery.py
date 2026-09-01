"""ADR-0205 driven through the engine: the report, the stamp, and what the stage is told.

§9's named list, each case written rather than assumed. Three groups.

**The report reaching the record** — §1's two local refusals, the stamp taken before
anything else the call does, the discard of a report naming nothing, and the case
adversarial review's round-1 ``blocker`` describes: a report that arrives *after* a
later turn has been captured stamps the turn it names and leaves the later one
``UNKNOWN``. Written as an integration case with an intervening captured turn,
because two writes in a row would pass against an implementation that resolved every
report to the tail.

**What capture writes** — §4's ``UNKNOWN`` on every turn of this operation, the park
and the degraded synthesis included, and on no turn of any other; and §1's rule for
``SpokenTurn.episode_id``, ``None`` exactly on the two shapes it names.

**What the composing stage is told** — §5's supplied fact, paired with the episode it
qualifies, off the tail ``ConversationLifecycle.history`` already read: the
round-2 ``blocker``'s case (a report about turn 1 arriving on turn 3 reaching turn 3's
composing input), the withheld record taking its delivery with it, no second store
call, and the captured episode's content byte-unchanged by any of it.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import PATIENT, Harness, NoStepPlanner

from ai_assistant.core.errors import (
    ConversationStoreError,
    OversizedValueError,
    SpeechError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    EpisodicMemory,
    MemorySource,
    Provenance,
    Role,
    SemanticMemory,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
    SpokenTurn,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import (
    FakeConversationStore,
    FakeModelProvider,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ConversationTurn, MemoryRecord, ParkedBinding

_AT: Final = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
_MP4: Final = SpokenAudioFormat.MP4
_ANSWER: Final = "You went hiking on Tuesday."
_ASKED: Final = "what is on this week"
_RECORDING: Final = SpokenAudio(content=b64encode(b"an utterance").decode("ascii"), media_type=_MP4)

_UNSTAMPED: Final = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
_INTERRUPTED: Final = SpokenDelivery(
    state=SpokenDeliveryState.INTERRUPTED,
    played=timedelta(seconds=3, milliseconds=200),
    rendered=timedelta(seconds=9, milliseconds=800),
)
_COMPLETE: Final = SpokenDelivery(
    state=SpokenDeliveryState.COMPLETE,
    played=timedelta(seconds=9, milliseconds=800),
    rendered=timedelta(seconds=9, milliseconds=800),
)


def _wired(model: FakeModelProvider | None = None, *, turns: int = 4, **knobs: object) -> Harness:
    """A harness whose composing stage runs over ``model``, with ``turns`` transcripts."""
    stage = ComposingStage(
        model=FakeModelProvider(_ANSWER) if model is None else model,
        streaming=FakeStreamingCompleter(),
    )
    knobs.setdefault("transcriber", FakeSpeechTranscriber(transcripts=[_ASKED] * turns))
    return Harness(composing=stage, **knobs)  # type: ignore[arg-type]  # heterogeneous harness knobs


async def _spoken(
    harness: Harness,
    *,
    conversation_id: str | None = None,
    delivery: SpokenDeliveryReport | None = None,
) -> SpokenTurn:
    """One spoken turn against ``harness``, with this module's fixed recording."""
    return await harness.engine.converse_spoken(
        _RECORDING,
        plays=(_MP4,),
        timeout=PATIENT,
        conversation_id=conversation_id,
        delivery=delivery,
    )


def _prompt(model: FakeModelProvider, call: int) -> str:
    """The user turn of the ``call``-th completion this provider was asked for."""
    return next(one.content for one in model.calls[call].messages if one.role is Role.USER)


async def _rows(harness: Harness, conversation_id: str) -> list[ConversationTurn]:
    """This conversation's index rows, oldest first."""
    return await harness.conversation_store.turns(conversation_id)


def _report(episode_id: str, delivery: SpokenDelivery = _INTERRUPTED) -> SpokenDeliveryReport:
    """One device's report about the turn ``episode_id`` names."""
    return SpokenDeliveryReport(episode_id=episode_id, delivery=delivery)


def _episodes(records: Sequence[MemoryRecord]) -> tuple[EpisodicMemory, ...]:
    """Every captured episode among ``records``."""
    return tuple(one for one in records if isinstance(one, EpisodicMemory))


# --- §1, §2: the two local refusals ------------------------------------------


async def test_a_report_beside_no_conversation_is_refused_before_any_seam() -> None:
    """§1: "refused **locally, before any I/O**, as a malformed argument".

    "A fresh conversation contains no turn a report could name." The transcriber is
    the first seam this call reaches, so its call count is what says the refusal came
    before any of them — a refusal raised after transcription would be a recording
    sent to a stranger for a call that could never have run.
    """
    harness = _wired()

    with pytest.raises(ValueError, match="fresh conversation"):
        await _spoken(harness, delivery=_report("conv:c-1:1"))

    assert isinstance(harness.transcriber, FakeSpeechTranscriber)
    assert harness.transcriber.call_count == 0, "refused before any I/O"


async def test_an_unknown_report_is_refused_before_any_seam() -> None:
    """§2: "A report whose ``delivery.state`` is ``UNKNOWN`` is refused locally".

    "A device that does not know reports nothing, and the absence of a report is
    spelled by omitting the argument. ``UNKNOWN`` is a value the hub writes (§4) and
    never one a caller supplies."
    """
    harness = _wired()
    first = await _spoken(harness)
    assert first.outcome is not None

    with pytest.raises(ValueError, match="reports nothing"):
        await _spoken(
            harness,
            conversation_id=first.outcome.conversation_id,
            delivery=_report(str(first.episode_id), _UNSTAMPED),
        )

    assert isinstance(harness.transcriber, FakeSpeechTranscriber)
    assert harness.transcriber.call_count == 1, "the refusal came before the second transcription"


# --- §1: the stamp, and the turn it names ------------------------------------


async def test_a_report_stamps_the_turn_it_names_and_the_call_runs() -> None:
    """§1, §3: the ordinary path, so every discard case below has a positive twin."""
    harness = _wired()
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)

    second = await _spoken(
        harness,
        conversation_id=conversation,
        delivery=_report(str(first.episode_id)),
    )

    assert second.outcome is not None
    rows = await _rows(harness, conversation)
    assert [one.delivery for one in rows] == [_INTERRUPTED, _UNSTAMPED], (
        "the turn the report named is stamped and the turn just captured is not"
    )


async def test_a_report_naming_no_turn_of_this_conversation_is_discarded() -> None:
    """§1: "the report is **discarded**: nothing is recorded, nothing is raised".

    "A benign one must not cost the owner the turn they just spoke", so the assertion
    that matters is that the turn still ran — not merely that nothing raised.
    """
    harness = _wired()
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)

    second = await _spoken(harness, conversation_id=conversation, delivery=_report("conv:nobody:1"))

    assert second.heard == _ASKED, "the turn the owner just spoke still ran"
    assert second.outcome is not None
    assert [one.delivery for one in await _rows(harness, conversation)] == [
        _UNSTAMPED,
        _UNSTAMPED,
    ], "nothing was stamped"


async def test_a_report_naming_a_turn_of_another_conversation_stamps_nothing_there() -> None:
    """§3's first condition, checked from the engine: never applied across threads."""
    harness = _wired(turns=3)
    mine = await _spoken(harness)
    theirs = await _spoken(harness)
    assert mine.outcome is not None
    assert theirs.outcome is not None
    here = str(mine.outcome.conversation_id)
    elsewhere = str(theirs.outcome.conversation_id)

    await _spoken(harness, conversation_id=here, delivery=_report(str(theirs.episode_id)))

    assert [one.delivery for one in await _rows(harness, elsewhere)] == [_UNSTAMPED], (
        "the other conversation's row is untouched"
    )


async def test_a_second_report_on_a_stamped_turn_performs_nothing() -> None:
    """§1: "a turn's delivery is stamped **once**" — and a resend is idempotent."""
    harness = _wired()
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    episode = str(first.episode_id)

    await _spoken(harness, conversation_id=conversation, delivery=_report(episode))
    await _spoken(harness, conversation_id=conversation, delivery=_report(episode, _COMPLETE))

    rows = await _rows(harness, conversation)
    assert rows[0].delivery == _INTERRUPTED, "the first stamp stands"


async def test_a_report_arriving_after_a_later_turn_stamps_the_turn_it_names() -> None:
    """§1, and adversarial review's round-1 ``blocker`` written as the ADR asks.

    "A report about turn 1 that reaches the hub after turn 2 has been captured — a
    resent request whose first response was lost, or a second page on the same
    conversation — resolves to turn 2 and records delivery of an answer that device
    never played." An **intervening captured turn** is the whole of the case: two
    writes in a row would pass against an implementation that resolved every report
    to the conversation's tail.
    """
    harness = _wired()
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)

    # Turn 2 is captured with no report at all — the response to turn 1 was lost, or
    # a second page asked something.
    await _spoken(harness, conversation_id=conversation)
    # Turn 3 carries the report about turn 1.
    await _spoken(harness, conversation_id=conversation, delivery=_report(str(first.episode_id)))

    rows = await _rows(harness, conversation)
    assert [one.ordinal for one in rows] == [1, 2, 3]
    assert rows[0].delivery == _INTERRUPTED, "the turn the report named"
    assert rows[1].delivery == _UNSTAMPED, "and the later one is left unknown"
    assert rows[2].delivery == _UNSTAMPED


async def test_the_report_is_recorded_even_where_the_recording_carried_no_words() -> None:
    """§1: "recorded **before the turn plans**, so a failure … does not lose it".

    ADR-0200 §4's no-words shape is the sharpest form of "later in the call": no turn
    runs, nothing is captured and no conversation is created — and the report is
    still about a turn that has already happened, so it lands.
    """
    harness = _wired(transcriber=FakeSpeechTranscriber(transcripts=[_ASKED, "   "]))
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)

    second = await _spoken(
        harness,
        conversation_id=conversation,
        delivery=_report(str(first.episode_id)),
    )

    assert second.outcome is None, "the recording carried no words"
    rows = await _rows(harness, conversation)
    assert [one.delivery for one in rows] == [_INTERRUPTED], "and the report still landed"


async def test_the_report_is_recorded_even_where_transcription_failed() -> None:
    """§1's clause again, on the arm that raises rather than returning."""

    class Failing(FakeSpeechTranscriber):
        async def transcribe(self, audio: SpokenAudio) -> str:
            msg = "the transcriber is down"
            raise SpeechError(msg)

    harness = _wired()
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    harness.engine._transcriber = Failing()

    with pytest.raises(Exception, match="transcribed"):
        await _spoken(
            harness, conversation_id=conversation, delivery=_report(str(first.episode_id))
        )

    rows = await _rows(harness, conversation)
    assert [one.delivery for one in rows] == [_INTERRUPTED], "the fact about turn 1 survived"


async def test_a_report_against_an_unknown_conversation_is_refused() -> None:
    """§3: ``record_delivery`` "raises ``UnknownConversationError`` where the
    conversation is absent or stamped deleted — the same two refusals ``append``
    carries". It is the refusal the turn itself would have raised a moment later, and
    it is not a fact about the report.
    """
    harness = _wired()

    with pytest.raises(UnknownConversationError):
        await _spoken(harness, conversation_id="no-such-thing", delivery=_report("conv:x:1"))


async def test_a_store_fault_on_the_report_does_not_cost_the_owner_the_turn() -> None:
    """This lane's reading of a clause ADR-0205 leaves open, recorded in the PR.

    §1 and §3 say what a *benign* miss does and what the store raises on a write
    fault; neither says what the engine does with one. Capture's own argument decides
    it: the report is a fact about a turn that has already happened, and losing it
    costs a later prompt one input where raising would throw away the turn the owner
    is speaking now.
    """

    class Faulting(FakeConversationStore):
        async def record_delivery(
            self, conversation_id: str, *, episode_id: str, delivery: SpokenDelivery
        ) -> ConversationTurn | None:
            msg = "the index is unwritable"
            raise ConversationStoreError(msg)

    harness = _wired(conversation_store=Faulting(now=lambda: _AT))
    first = await _spoken(harness)
    assert first.outcome is not None

    second = await _spoken(
        harness,
        conversation_id=first.outcome.conversation_id,
        delivery=_report(str(first.episode_id)),
    )

    assert second.heard == _ASKED, "the turn the owner just spoke still ran"
    assert second.outcome is not None


# --- §4: what capture writes, and on which operation -------------------------


async def test_every_spoken_turn_is_stamped_unknown_at_capture() -> None:
    """§4: written "**unconditionally on that operation**"."""
    harness = _wired()

    first = await _spoken(harness)

    assert first.outcome is not None
    rows = await _rows(harness, str(first.outcome.conversation_id))
    assert [one.delivery for one in rows] == [_UNSTAMPED]


async def test_a_degraded_synthesis_still_leaves_the_turn_unknown() -> None:
    """§4: "including where the answer was parked, where ``outcome.reply`` is
    ``None``, and where ``spoken_degraded`` is ``True``".

    "``UNKNOWN`` is the conservative reading" of a turn the hub knows nobody heard,
    and "what is not available is leaving it absent": absence is what a turn on
    another operation carries, so a spoken turn whose answer was never rendered would
    otherwise be indistinguishable from a text turn.
    """
    harness = _wired(synthesizer=FakeSpeechSynthesizer(formats={SpokenAudioFormat.WEBM_OPUS}))

    first = await _spoken(harness)

    assert first.spoken is None
    assert first.spoken_degraded is True
    assert first.outcome is not None
    rows = await _rows(harness, str(first.outcome.conversation_id))
    assert [one.delivery for one in rows] == [_UNSTAMPED]


async def test_a_spoken_turn_with_no_answer_at_all_is_still_stamped_unknown() -> None:
    """§4's same clause, on the arm where ``outcome.reply`` is ``None``."""
    harness = Harness(
        planner=NoStepPlanner(),
        composing=ComposingStage(model=FakeModelProvider(""), streaming=FakeStreamingCompleter()),
        transcriber=FakeSpeechTranscriber(transcripts=[_ASKED]),
    )

    first = await harness.engine.converse_spoken(_RECORDING, plays=(_MP4,), timeout=PATIENT)

    assert first.outcome is not None
    assert first.outcome.reply is None, "the composing stage produced no answer"
    rows = await _rows(harness, str(first.outcome.conversation_id))
    assert [one.delivery for one in rows] == [_UNSTAMPED]


async def test_no_other_operation_writes_a_delivery() -> None:
    """§4: "``converse``, ``converse_streaming`` and ``resume`` capture exactly as
    they do today, and their rows carry none."

    An absent value is what §3 reads as "no delivery fact was recorded for this
    turn", so an operation that wrote ``UNKNOWN`` here would make every text turn
    look like a spoken one whose device never reported.
    """
    harness = _wired()

    outcome = await harness.engine.converse("what is on this week", timeout=PATIENT)

    assert outcome.conversation_id is not None
    rows = await _rows(harness, outcome.conversation_id)
    assert [one.delivery for one in rows] == [None]


# --- §1: the episode id the caller is disclosed ------------------------------


async def test_the_disclosed_episode_id_is_the_one_record_delivery_accepts_back() -> None:
    """§1: the id "reaches the caller so that it can be handed back … and for no
    other purpose". The round trip is the whole test — an id that named the wrong row
    would satisfy any assertion about its shape.
    """
    harness = _wired()

    first = await _spoken(harness)

    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    rows = await _rows(harness, conversation)
    assert first.episode_id == rows[0].episode_id
    stamped = await harness.conversation_store.record_delivery(
        conversation,
        episode_id=str(first.episode_id),
        delivery=_COMPLETE,
    )
    assert stamped is not None
    assert stamped.delivery == _COMPLETE


async def test_the_episode_id_is_absent_exactly_where_no_turn_was_recorded() -> None:
    """§1: ``None`` "**exactly when** the call recorded no turn — a recording that
    carried no words … or a capture whose index entry did not land".
    """

    class Refusing(FakeConversationStore):
        async def append(
            self,
            conversation_id: str,
            *,
            occurred_at: datetime,
            parked: ParkedBinding | None = None,
            delivery: SpokenDelivery | None = None,
        ) -> ConversationTurn:
            msg = "the index is unwritable"
            raise ConversationStoreError(msg)

    silent = _wired(transcriber=FakeSpeechTranscriber(transcripts=["   "]))
    assert (await _spoken(silent)).episode_id is None

    unrecorded = _wired(conversation_store=Refusing(now=lambda: _AT))
    turn = await _spoken(unrecorded)
    assert turn.outcome is not None
    assert turn.episode_id is None, "no index row landed, so there is nothing to name"


# --- §5: what the composing stage is told ------------------------------------


async def test_an_unknown_turn_of_the_tail_is_told_to_the_stage_as_unknown() -> None:
    """§5: "Where a tail turn's state is ``UNKNOWN`` the stage is told that it is
    unknown, and composes accordingly; it is never told, and never defaults to,
    delivered."
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model)
    first = await _spoken(harness)
    assert first.outcome is not None

    await _spoken(harness, conversation_id=first.outcome.conversation_id)

    assert "HOW MUCH OF THIS THE USER HEARD IS UNKNOWN" in _prompt(model, 1)


async def test_a_complete_turn_is_rendered_as_nothing() -> None:
    """§5: "A ``COMPLETE`` turn may be rendered as nothing, because a device saying
    it played the answer out is exactly the state the stage would otherwise assume."
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model)
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    await _spoken(
        harness,
        conversation_id=conversation,
        delivery=_report(str(first.episode_id), _COMPLETE),
    )

    await _spoken(harness, conversation_id=conversation)

    third = _prompt(model, 2)
    assert "HOW MUCH OF THIS THE USER HEARD IS UNKNOWN" in third, "turn 2 is still unknown"
    assert third.count("HOW MUCH OF THIS THE USER HEARD IS UNKNOWN") == 1, (
        "the COMPLETE turn contributes no line of its own"
    )
    assert "THE USER DID NOT HEAR ALL OF THIS" not in third


async def test_a_report_about_turn_one_reaches_turn_threes_composing_input() -> None:
    """§5, and adversarial review's round-2 ``blocker`` in the ADR's own words.

    "Turn 1 is interrupted, turn 2 is captured before turn 1's report arrives, turn 3
    carries it. §1 stamps turn 1, correctly — and a supply that read only the previous
    row would hand turn 3 the tail with turn 1's full reply in it and turn 2's
    delivery beside it, saying nothing about the one turn in that prompt the owner did
    not hear."

    So the assertion is on turn **4**'s prompt: the fact has to be paired with turn
    1's episode, "and not merely the store" — which is why the episode's own content
    is located in the prompt and the line is required to follow it.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, turns=5)
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    await _spoken(harness, conversation_id=conversation)
    await _spoken(harness, conversation_id=conversation, delivery=_report(str(first.episode_id)))

    await _spoken(harness, conversation_id=conversation)

    prompt = _prompt(model, 3)
    assert "THE USER DID NOT HEAR ALL OF THIS" in prompt
    assert "3.2 of about 9.8 seconds" in prompt, "the two durations, to a tenth (§2)"
    # Paired with the episode it qualifies: turn 1's own bullet is the one the line
    # follows, and turn 2's — captured after it and never reported on — is not.
    rows = await _rows(harness, conversation)
    episodes = {one.episode_id: one.ordinal for one in rows}
    assert episodes[str(first.episode_id)] == 1
    bullets = [line for line in prompt.splitlines() if line.startswith("  - [episodic/")]
    assert len(bullets) >= 3, "the tail carries the three earlier turns"
    lines = prompt.splitlines()
    at = lines.index(bullets[0])
    # Three lines of window rather than two, since ADR-0222 §1: a tail record renders
    # its bullet, the `how it turned out:` line, and now the reply line, and the
    # delivery fact is written under all of them — deliberately last, so that "ALL OF
    # THIS" reads as the text on the line above it.
    assert any("THE USER DID NOT HEAR ALL OF THIS" in one for one in lines[at + 1 : at + 4]), (
        "the fact follows the first turn's bullet, which is the episode it qualifies"
    )
    assert "THE USER DID NOT HEAR ALL OF THIS" not in "\n".join(
        lines[lines.index(bullets[1]) : lines.index(bullets[1]) + 2]
    ), "and never the turn captured after it, which no device reported on"


async def test_a_withheld_turns_delivery_does_not_reach_the_stage_either() -> None:
    """§5: "A delivery fact **travels with the episode it qualifies and never without
    it**. Where a supply site withholds a record — under ADR-0199 §3, or under
    ADR-0204 §3's test … — no delivery fact for that turn reaches the composing stage
    either. A fact stating how long an answer ran, standing beside no answer, is a
    value that narrows what was withheld, and ADR-0199 §5's fourth clause forbids
    one."

    Turn 1 is a withholding turn, so ADR-0204 §3 stamps its episode and ADR-0199 §3
    withholds it from turn 2. Its delivery fact must go with it.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, turns=3)
    await harness.memory.add(
        SemanticMemory(
            id="rec-1",
            content="Alice is seeing a cardiologist on Friday",
            fact="Alice is seeing a cardiologist on Friday",
            about_person="Alice",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_AT),
        )
    )
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    stamped = await harness.conversation_store.record_delivery(
        conversation,
        episode_id=str(first.episode_id),
        delivery=_INTERRUPTED,
    )
    assert stamped is not None, "turn 1 is stamped in the index"

    second = await _spoken(harness, conversation_id=conversation)

    assert second.outcome is not None
    assert second.outcome.turn is not None
    assert not _episodes(second.outcome.turn.memories), (
        "the withholding turn's own episode is withheld from the next spoken turn"
    )
    assert "THE USER DID NOT HEAR ALL OF THIS" not in _prompt(model, 1), (
        "and its delivery fact went with it"
    )


async def test_the_supply_path_makes_no_second_store_call() -> None:
    """§5: the facts "ride the tail that stage's inputs are already assembled from".

    "``ConversationLifecycle.history`` walks ``ConversationStore.turns`` and holds
    **every** one of those rows already, so the composing supply reads them off what
    was fetched and the count of them costs nothing." Counted rather than argued: one
    ``turns`` read for the tail, and no reverse lookup at all.
    """

    class Counting(FakeConversationStore):
        def __init__(self, **knobs: object) -> None:
            super().__init__(**knobs)  # type: ignore[arg-type]  # the fake's own knobs
            self.reads: list[str] = []

        async def turns(
            self,
            conversation_id: str,
            *,
            limit: int | None = None,
            before_ordinal: int | None = None,
        ) -> list[ConversationTurn]:
            self.reads.append("turns")
            return await super().turns(conversation_id, limit=limit, before_ordinal=before_ordinal)

        async def turn_of_episode(self, episode_id: str) -> ConversationTurn | None:
            self.reads.append("turn_of_episode")
            return await super().turn_of_episode(episode_id)

    store = Counting(now=lambda: _AT)
    harness = _wired(conversation_store=store)
    first = await _spoken(harness)
    assert first.outcome is not None
    store.reads.clear()

    await _spoken(harness, conversation_id=first.outcome.conversation_id)

    assert store.reads == ["turns"], (
        "one tail read for the whole turn: the delivery facts come off those rows, "
        "and nothing looks an episode back up to find them (ADR-0205 §5)"
    )


async def test_the_captured_episode_is_byte_identical_with_and_without_a_report() -> None:
    """§5: "The fact is a **supplied input and not part of the episode's
    ``content``**. Capture's canonical rendering is byte-unchanged by this ADR."

    ADR-0197 §10's failure with a different payload: a delivery sentence in
    ``content`` "would be true of one channel and replayed on every channel, it would
    still be there three turns later when it means nothing".
    """
    plain = _wired(turns=3)
    reported = _wired(turns=3)
    first_plain = await _spoken(plain)
    first_reported = await _spoken(reported)
    assert first_plain.outcome is not None
    assert first_reported.outcome is not None

    await _spoken(plain, conversation_id=first_plain.outcome.conversation_id)
    await _spoken(
        reported,
        conversation_id=first_reported.outcome.conversation_id,
        delivery=_report(str(first_reported.episode_id)),
    )

    without = [one.content for one in _episodes(await plain.memory.export())]
    with_report = [one.content for one in _episodes(await reported.memory.export())]
    assert len(without) == 2
    assert without == with_report, (
        "no delivery sentence enters what a later turn replays (ADR-0205 §5)"
    )


async def test_an_oversized_recording_raises_before_the_report_is_recorded() -> None:
    """The hub-side fact the page's retention rule rests on (ADR-0200 §6, ADR-0205 §1).

    Adversarial review, round 6, ``major``, found the page treating
    ``assistant-declined`` as proof the turn had been stamped. It is not:
    :meth:`Engine.converse_spoken` refuses a recording over
    ``hub_max_spoken_audio_bytes`` **locally, before any I/O**, which is before
    ``_converse_spoken`` records the report — so the fault crosses to the browser with
    the report unapplied.

    Pinned here rather than left implicit in the page, because it is a property of the
    *engine's ordering*: a lane that moved the recording check after the stamp would
    make the page's rule wrong without touching the page. The turn is read back
    afterwards to show it is still eligible, which is what makes the owner's next press
    able to carry the same report and land it.
    """
    harness = _wired(max_spoken_audio_bytes=16)
    first = await _spoken(harness)
    assert first.outcome is not None
    conversation = str(first.outcome.conversation_id)
    oversized = SpokenAudio(
        content=b64encode(b"x" * 64).decode("ascii"), media_type=SpokenAudioFormat.MP4
    )

    with pytest.raises(OversizedValueError):
        await harness.engine.converse_spoken(
            oversized,
            plays=(_MP4,),
            timeout=PATIENT,
            conversation_id=conversation,
            delivery=_report(str(first.episode_id)),
        )

    rows = await _rows(harness, conversation)
    assert [one.delivery for one in rows] == [_UNSTAMPED], (
        "the report never reached the store, so the turn is still stampable"
    )

    # And the very next call, with a recording that fits, carries the same report and
    # lands it — which is the whole of what the page's retention buys.
    await _spoken(harness, conversation_id=conversation, delivery=_report(str(first.episode_id)))

    landed = await _rows(harness, conversation)
    assert landed[0].delivery == _INTERRUPTED

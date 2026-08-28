"""What a spoken call returns, and the vocabulary its one failure carries.

Three subjects, each pinned rather than asserted: :class:`SpokenTurn`'s four
members and the shapes ADR-0200 §4 admits between them; the bijection §4 states
between :class:`SpeechFailure` and the ``SpeechError`` taxonomy §1 fixes; and
:class:`TranscriptionFailedError`'s standing, default and round trip.

The signature and audience clauses of §3 are here too, because they are properties
of the *declaration* rather than of any implementation: one positional subject and
three keyword-only arguments, and nothing anywhere on this surface that expresses
an audience.
"""

from __future__ import annotations

import inspect
from base64 import b64encode
from datetime import UTC, datetime
from typing import Final, get_type_hints

import pytest
from pydantic import ValidationError

from ai_assistant.core import errors as errors_module
from ai_assistant.core import types as types_module
from ai_assistant.core.errors import (
    AssistantError,
    SpeechError,
    SpeechTimeoutError,
    TranscriptionFailedError,
)
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    Goal,
    MemorySource,
    Provenance,
    SpeechFailure,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenTurn,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
)

_AUDIO: Final = SpokenAudio(
    content=b64encode(b"not really audio").decode("ascii"),
    media_type=SpokenAudioFormat.MP4,
)

_AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _turn() -> TurnResult:
    """A turn whose plan has no step — a real ratified shape, not a stub."""
    goal = Goal(
        id="g-1",
        statement="what did I do last week",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )
    return TurnResult(
        goal=goal,
        context=CurrentContext(
            now=_AT,
            time_of_day=TimeOfDay.AFTERNOON,
            is_weekend=False,
            within_working_hours=True,
        ),
        memories=(),
        plan=ActionPlan(id="p-1", goal_id=goal.id, steps=(), created_at=_AT),
    )


def _outcome_with_a_reply() -> TurnOutcome:
    """A ``TurnOutcome`` carrying prose, which is what a rendering renders."""
    return TurnOutcome(turn=_turn(), step=None, conversation_id="c-1", reply="the answer")


def _outcome_with_no_reply() -> TurnOutcome:
    """A park's shape: an answered call that has nothing to say (ADR-0170 §4)."""
    return TurnOutcome(turn=None, step=None, conversation_id="c-1", reply=None)


# --- §4: the four members and the shapes between them ------------------------


def test_the_type_has_exactly_the_five_members_adr_0205_leaves_it_with() -> None:
    # §4 fixed the member set at four and the count is what stops a sixth arriving
    # unnoticed — a second copy of the spoken words being the one §4 removed by
    # name when `SpokenReply` was deleted. ADR-0205 §10(b) partially supersedes that
    # count in exactly one scope, "the addition being `episode_id` and nothing else",
    # so the enumeration moves by that member and by no other.
    assert set(SpokenTurn.model_fields) == {
        "heard",
        "outcome",
        "spoken",
        "spoken_degraded",
        "episode_id",
    }


def test_it_is_frozen_and_forbids_extras() -> None:
    turn = SpokenTurn()
    with pytest.raises(ValidationError):
        SpokenTurn(nonsense=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        turn.spoken_degraded = True


def test_a_recording_with_no_words_is_five_absences_and_no_error() -> None:
    # §4's first shape: "nothing was asked, so nothing was answered". It is not an
    # error and no exception is raised for it, so the type must admit it as its own
    # default rather than as a case a caller assembles. ADR-0205 §1 puts
    # `episode_id` in that shape too: it is `None` "exactly when the call recorded no
    # turn", and a recording that carried no words is the first of the two cases it
    # names.
    empty = SpokenTurn()
    assert (empty.heard, empty.outcome, empty.spoken, empty.episode_id) == (
        None,
        None,
        None,
        None,
    )
    assert empty.spoken_degraded is False


def test_an_episode_id_beside_no_outcome_is_refused() -> None:
    """ADR-0205 §1: ``episode_id`` is ``None`` **exactly when** the call recorded no
    turn — and a call with no ``outcome`` ran none.

    Raised by **both** review lenses on round 1. The id is the name a device hands
    back on the next call, so a result carrying one for a turn that never ran invites
    a report against a turn nothing can stamp; and the value crosses the wire as a
    legitimate model, so the type is where it has to be refused.

    Only this direction is enforced. The converse is false of a shape §1 admits — "a
    capture whose index entry did not land" leaves an outcome standing beside no id —
    which the second case pins so a later editor cannot 'complete' the biconditional.
    """
    with pytest.raises(ValidationError, match="episode_id"):
        SpokenTurn(episode_id="conv:c-1:1")

    unrecorded = SpokenTurn(heard="hello", outcome=TurnOutcome(turn=None))
    assert unrecorded.episode_id is None, (
        "an outcome beside no id is the capture whose index entry did not land"
    )


def test_a_transcript_with_no_turn_is_refused() -> None:
    # The "exactly when" stated in the direction that would say the engine heard
    # words and answered nothing.
    with pytest.raises(ValidationError, match="together"):
        SpokenTurn(heard="hello")


def test_a_turn_with_no_transcript_is_refused() -> None:
    # And in the direction that would say it answered a recording carrying none.
    with pytest.raises(ValidationError, match="together"):
        SpokenTurn(outcome=_outcome_with_a_reply())


def test_an_answered_turn_may_carry_its_rendering() -> None:
    turn = SpokenTurn(heard="what did I do", outcome=_outcome_with_a_reply(), spoken=_AUDIO)
    assert turn.spoken is _AUDIO
    assert turn.spoken_degraded is False


def test_an_answered_turn_may_say_that_speaking_it_did_not_complete() -> None:
    turn = SpokenTurn(heard="what did I do", outcome=_outcome_with_a_reply(), spoken_degraded=True)
    assert turn.spoken is None
    assert turn.spoken_degraded is True


def test_a_rendering_beside_a_degradation_is_refused() -> None:
    # §4: "It is never `True` beside a non-`None` `spoken`, because this call
    # streams nothing and so has no partial rendering to carry."
    with pytest.raises(ValidationError, match="streams"):
        SpokenTurn(
            heard="what did I do",
            outcome=_outcome_with_a_reply(),
            spoken=_AUDIO,
            spoken_degraded=True,
        )


def test_a_rendering_with_no_answer_to_render_is_refused() -> None:
    # §4: "`spoken` is `None` wherever `outcome.reply` is `None`" — a park, a
    # recovered resume, and a composition failure each leave nothing to say, and
    # nothing is invented to fill the silence.
    with pytest.raises(ValidationError, match="rendering of the outcome"):
        SpokenTurn(heard="what did I do", outcome=_outcome_with_no_reply(), spoken=_AUDIO)


def test_a_degradation_with_no_answer_is_refused() -> None:
    # The same shape's other half: "On those shapes `spoken_degraded` is `False`."
    with pytest.raises(ValidationError, match="no answer"):
        SpokenTurn(heard="what did I do", outcome=_outcome_with_no_reply(), spoken_degraded=True)


def test_a_blank_transcript_cannot_be_carried_as_a_transcript() -> None:
    # §4: "`heard` is typed `NonBlankEncodableText | None`, so a blank transcript
    # has nowhere else to go" — which is what makes the no-words shape the only
    # reading available rather than one of two.
    with pytest.raises(ValidationError):
        SpokenTurn(heard="   ", outcome=_outcome_with_a_reply())


def test_a_transcript_is_carried_byte_for_byte() -> None:
    # §4: "nothing on this path strips, trims, case-folds or otherwise normalises
    # it" — `NonBlankEncodableText`'s own posture, which refuses `"   "` while
    # returning `"  calendar  "` unchanged.
    turn = SpokenTurn(heard="  Calendar  ", outcome=_outcome_with_a_reply())
    assert turn.heard == "  Calendar  "


# --- §4: the failure vocabulary is a bijection -------------------------------


def _speech_taxonomy() -> set[type[SpeechError]]:
    """Every class of ADR-0200 §1's taxonomy — the base and its proper subclasses."""
    return {
        value
        for value in vars(errors_module).values()
        if isinstance(value, type) and issubclass(value, SpeechError)
    }


def test_there_is_one_failure_member_per_speech_error_class() -> None:
    # §4: "exactly one member per class of the `SpeechError` taxonomy §1 fixes".
    # Enumerating both and comparing counts is what stops a later subclass landing
    # without its member — the drift §4 forbids in terms.
    assert _speech_taxonomy() == {SpeechError, SpeechTimeoutError}
    assert len(SpeechFailure) == len(_speech_taxonomy())


def test_the_vocabulary_is_the_two_members_the_adr_names() -> None:
    assert {member.value for member in SpeechFailure} == {"unclassified", "timed_out"}


# --- §4: what crosses the promoted boundary ----------------------------------


def test_a_transcription_failure_is_an_assistant_error_and_not_a_speech_one() -> None:
    # §1's count clause: "`TranscriptionFailedError` ... is **not** in it", because
    # it carries no `retryable` and no `routable` claim — whether a second attempt
    # or a second engine would help is a property of the seam's failure, not of the
    # promoted surface's.
    assert issubclass(TranscriptionFailedError, AssistantError)
    assert not issubclass(TranscriptionFailedError, SpeechError)
    assert "TranscriptionFailedError" not in {kind.__name__ for kind in _speech_taxonomy()}
    assert not hasattr(TranscriptionFailedError, "retryable")
    assert not hasattr(TranscriptionFailedError, "routable")


def test_its_signature_is_a_message_and_one_keyword_only_classification() -> None:
    parameters = inspect.signature(TranscriptionFailedError.__init__).parameters
    assert parameters["message"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["failure"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["failure"].default is SpeechFailure.UNCLASSIFIED
    assert get_type_hints(TranscriptionFailedError.__init__)["failure"] is SpeechFailure


def test_the_default_is_the_reduced_deliverys_and_it_is_marked() -> None:
    # §4: the default exists for ADR-0085 §10a's reduction alone, and the loss is
    # legible rather than silent — `UNCLASSIFIED` beside `details_elided` `True`
    # means the classification did not survive the frame, and beside `False` means
    # the seam raised a bare `SpeechError`.
    raised = TranscriptionFailedError("could not transcribe")
    assert raised.failure is SpeechFailure.UNCLASSIFIED
    assert raised.details_elided is False


def test_a_member_arriving_as_its_own_string_value_is_coerced_back() -> None:
    # ADR-0085 §10a reconstructs "by calling the named type with ... the `details`
    # members as keyword arguments", and `wire/codec.py` renders an `Enum` by its
    # value — so the far side must hold the same *member*, not a `str` that merely
    # compares equal.
    rebuilt = TranscriptionFailedError("nope", failure="timed_out")  # type: ignore[arg-type]
    assert rebuilt.failure is SpeechFailure.TIMED_OUT


def test_a_classification_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(ValueError, match="SpeechFailure"):
        TranscriptionFailedError("nope", failure="invented")  # type: ignore[arg-type]


# --- §3: the signature, and the absence of any audience ----------------------


def test_the_member_takes_one_positional_subject_and_four_keyword_only() -> None:
    # ADR-0085 §2's convention, unchanged: "the *subject* of a call is positional,
    # and every other argument is keyword-only". A second optional positional
    # cannot be joined by another without changing every call site. ADR-0205 §1
    # supersedes ADR-0200 §3's *count* alone — "a fifth argument and no others:
    # `delivery`, keyword-only, a `SpokenDeliveryReport | None` defaulting to
    # `None`" — so this enumeration is what says the addition was that one and
    # nothing beside it.
    parameters = inspect.signature(AssistantEngine.converse_spoken).parameters
    assert [name for name in parameters if name != "self"] == [
        "utterance",
        "plays",
        "timeout",
        "conversation_id",
        "delivery",
    ]
    assert parameters["utterance"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in ("plays", "timeout", "conversation_id", "delivery"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["conversation_id"].default is None
    assert parameters["delivery"].default is None
    assert parameters["plays"].default is inspect.Parameter.empty
    assert parameters["timeout"].default is inspect.Parameter.empty


def test_the_return_and_argument_types_are_the_ones_adr_0200_fixes() -> None:
    hints = get_type_hints(AssistantEngine.converse_spoken, globalns=vars(types_module))
    assert hints["return"] is SpokenTurn
    assert hints["utterance"] is SpokenAudio
    assert hints["plays"] == tuple[SpokenAudioFormat, ...]


def test_nothing_on_this_surface_expresses_an_audience() -> None:
    # ADR-0200 §3: "There is no audience argument, no audience member on any type
    # this ADR adds, and no setting." Checked as an enumeration rather than as a
    # claim, because ADR-0199 §8's third clause forbids the shape outright and an
    # earlier draft of §3 carried exactly it — a `SpokenChannel` with an `audience`
    # the caller supplied on every call.
    #
    # Matched on the *word* deliberately. Everywhere else this suite refuses to
    # decide anything by inspecting text; here the subject being searched is this
    # project's own declared names, which is the one place a name search is a
    # complete test rather than a heuristic.
    names = set(inspect.signature(AssistantEngine.converse_spoken).parameters)
    for model in (SpokenTurn, SpokenAudio):
        names |= set(model.model_fields)
    names |= {member.name for member in SpokenAudioFormat}
    names |= {member.name for member in SpeechFailure}
    assert not [name for name in names if "audience" in name.lower()]


def test_the_settings_gained_no_audience_field() -> None:
    from ai_assistant.core.config import Settings  # noqa: PLC0415 — asserted about

    assert not [name for name in Settings.model_fields if "audience" in name.lower()]


def test_the_five_names_adr_0200_adds_to_core_types_are_all_there() -> None:
    # §12's enumeration of what this decision adds to `core/types.py`, checked so
    # that a lane cannot report the additive claim without having made it.
    for name in ("SpokenAudio", "SpokenAudioFormat", "Base64Audio", "SpokenTurn", "SpeechFailure"):
        assert hasattr(types_module, name), name

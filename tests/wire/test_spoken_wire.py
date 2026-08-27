"""What the wire does with a recording, and with the one failure the call declares.

ADR-0200 §9 is a claim about *carriage*: audio crosses as
:data:`~ai_assistant.core.types.Base64Audio`, which is text, so ADR-0087 §2c's
scalar table gains no row and ``project`` gains no branch. What §9 *does* cost
``wire/`` is a **refusal path** — "a refused recording never travels inside the
refusal" — and that is what the first half of this module pins.

The second half is ADR-0200 §4's reduced delivery: ``TranscriptionFailedError``'s
``failure`` keyword defaults so that ADR-0085 §10a's reduction reconstructs the
declared failure rather than a ``ProtocolError``, and the loss is *marked* rather
than silent.
"""

from __future__ import annotations

import json
from base64 import b64encode
from typing import Final

import pytest

from ai_assistant.core.errors import TranscriptionFailedError
from ai_assistant.core.types import SpeechFailure, SpokenAudio, SpokenAudioFormat
from ai_assistant.wire.codec import canonical_payload, project
from ai_assistant.wire.errors import (
    UndecodableFrameError,
    error_payload,
    raise_from_payload,
)
from ai_assistant.wire.server import _decode_arguments
from ai_assistant.wire.surface import audio_bearing

#: A near-valid clip: correct base64 for a recognisable payload, with one
#: character replaced. Exactly the input an unlucky browser or an attacker
#: produces, and the one a happy-path retention test never sees.
_CLIP: Final = b64encode(b"PRIVATE-CLIP-MARKER-0001").decode("ascii")
_NEAR_VALID: Final = f"{_CLIP[:-2]}!{_CLIP[-1]}"


# --- §9: a refused recording never travels inside the refusal ----------------


def test_the_surface_knows_which_arguments_can_hold_a_recording() -> None:
    """Derived from the Protocol, so a second such method needs no edit here."""
    assert audio_bearing("converse_spoken") == {"utterance"}
    assert audio_bearing("converse") == frozenset()


def test_a_malformed_recording_is_refused_without_being_echoed() -> None:
    """§9: the refusal carries "no input value and no chained cause".

    Necessary and not sufficient is the point: ``Base64Audio``'s own validator names
    the class of defect and the position rather than the value, but a pydantic
    ``ValidationError`` carries the rejected **input** whatever its message says —
    so the entry point has to refuse without quoting it.
    """
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments(
            "converse_spoken",
            {
                "utterance": {"content": _NEAR_VALID, "media_type": "audio/mp4"},
                "plays": ["audio/mp4"],
                "timeout": "PT30S",
            },
        )

    assert "PRIVATE-CLIP-MARKER" not in str(caught.value)
    assert "PRIVATE-CLIP-MARKER" not in repr(caught.value)


def test_that_refusal_chains_nothing_that_could_carry_the_clip() -> None:
    """§9 again, one step further than ``from None``.

    ``from None`` clears ``__cause__`` and suppresses the context in a rendered
    traceback; it leaves the ``ValidationError`` reachable as ``__context__``, and
    the rejected input with it. Raising with no exception in flight leaves nothing
    to attach.
    """
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments(
            "converse_spoken",
            {
                "utterance": {"content": _NEAR_VALID, "media_type": "audio/mp4"},
                "plays": ["audio/mp4"],
                "timeout": "PT30S",
            },
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_a_non_audio_argument_still_quotes_what_its_type_refused() -> None:
    """The refusal path is narrowed to recordings and takes no diagnostics elsewhere.

    ADR-0200 §9's clause is about a value that is a recording; every other
    argument's refusal is unchanged, which is what keeps this a §9 fix rather than a
    quiet narrowing of what an operator can see.
    """
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments("converse", {"utterance": 17, "timeout": "PT30S"})

    assert caught.value.__cause__ is not None


def test_a_well_formed_recording_decodes_into_the_declared_type() -> None:
    """The other side: nothing about the refusal path breaks the ordinary call."""
    decoded = _decode_arguments(
        "converse_spoken",
        {
            "utterance": {"content": _CLIP, "media_type": "audio/mp4"},
            "plays": ["audio/mp4", "audio/webm;codecs=opus"],
            "timeout": "PT30S",
        },
    )

    assert decoded["utterance"] == SpokenAudio(content=_CLIP, media_type=SpokenAudioFormat.MP4)
    assert decoded["plays"] == (SpokenAudioFormat.MP4, SpokenAudioFormat.WEBM_OPUS)


def test_a_recording_projects_as_ordinary_text() -> None:
    """§9: "no file under ``wire/`` changes to carry audio".

    The recording is two members of an ordinary model, one of them a string — so
    ``project`` renders it through the ``BaseModel`` branch it already had, and no
    ``bytes`` row is involved anywhere.
    """
    projected = project(SpokenAudio(content=_CLIP, media_type=SpokenAudioFormat.MP4))

    assert projected == {"content": _CLIP, "media_type": "audio/mp4"}


# --- §4: the reduced delivery -------------------------------------------------


def test_a_transcription_failure_round_trips_with_its_classification() -> None:
    """ADR-0085 §10a: the far side reconstructs the same class with the same member."""
    payload = json.loads(
        canonical_payload(
            error_payload(
                TranscriptionFailedError("nope", failure=SpeechFailure.TIMED_OUT),
                max_bytes=4096,
            )
        )
    )

    with pytest.raises(TranscriptionFailedError) as caught:
        raise_from_payload(payload)

    assert caught.value.failure is SpeechFailure.TIMED_OUT
    assert caught.value.details_elided is False


def test_a_reduced_delivery_raises_the_declared_failure_and_marks_the_loss() -> None:
    """§4: the default's one caller, and why it exists at all.

    §10a sets ``details`` to ``null`` when an error payload will not fit the frame,
    and ``raise_from_payload`` then calls the declared type with the message alone.
    A *required* keyword there would make that call raise ``ProtocolError`` instead
    of the declared failure — "two observable failure contracts for one call", which
    is what ADR-0084 §4-§5 promote this surface to prevent.

    And the loss is legible rather than silent: ``UNCLASSIFIED`` beside
    ``details_elided`` ``True`` means the classification did not survive the frame,
    where beside ``False`` it means the seam raised a bare ``SpeechError``.
    """
    raised = TranscriptionFailedError(
        "the recording could not be transcribed " * 40, failure=SpeechFailure.TIMED_OUT
    )
    payload = json.loads(canonical_payload(error_payload(raised, max_bytes=128)))
    assert payload["reduced"] is True
    assert payload["details"] is None

    with pytest.raises(TranscriptionFailedError) as caught:
        raise_from_payload(payload)

    assert caught.value.failure is SpeechFailure.UNCLASSIFIED
    assert caught.value.details_elided is True

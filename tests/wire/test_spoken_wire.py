"""What the wire does with a recording.

ADR-0200 §9 is a claim about *carriage*: audio crosses as
:data:`~ai_assistant.core.types.Base64Audio`, which is text, so ADR-0087 §2c's
scalar table gains no row and ``project`` gains no branch. What §9 *does* cost
``wire/`` is a **refusal path** — "a refused recording never travels inside the
refusal" — and that is what this module pins.

``converse_spoken`` retired (ADR-0313 §3:1), and with it its delivery report's
argument, its result and its one declared failure. A recording still reaches the
surface inside ``receive``'s ``input``, as a speech payload every combination
refuses (§4:1), so the refusal path is pinned there.
"""

from __future__ import annotations

from base64 import b64encode
from typing import Final

import pytest

from ai_assistant.core.types import (
    SpokenAudio,
    SpokenAudioFormat,
)
from ai_assistant.wire.codec import project
from ai_assistant.wire.errors import UndecodableFrameError
from ai_assistant.wire.server import _decode_arguments
from ai_assistant.wire.surface import audio_bearing

#: A near-valid clip: correct base64 for a recognisable payload, with one
#: character replaced. Exactly the input an unlucky browser or an attacker
#: produces, and the one a happy-path retention test never sees.
_CLIP: Final = b64encode(b"PRIVATE-CLIP-MARKER-0001").decode("ascii")
_NEAR_VALID: Final = f"{_CLIP[:-2]}!{_CLIP[-1]}"


def _spoken_input(content: str) -> dict[str, object]:
    """``receive``'s arguments for the retired spoken conversational combination."""
    return {
        "input": {
            "target": {"kind": "new_conversation"},
            "payload": {
                "modality": "speech",
                "audio": {"content": content, "media_type": "audio/mp4"},
            },
        },
        "reply": {"kind": "spoken", "plays": ["audio/mp4"]},
        "timeout": "PT30S",
    }


# --- §9: a refused recording never travels inside the refusal ----------------


def test_the_surface_knows_which_arguments_can_hold_a_recording() -> None:
    """Derived from the Protocol, so a second such method needs no edit here."""
    assert audio_bearing("receive") == {"input"}
    assert audio_bearing("stop_activation") == frozenset()


def test_a_malformed_recording_is_refused_without_being_echoed() -> None:
    """§9: the refusal carries "no input value and no chained cause".

    Necessary and not sufficient is the point: ``Base64Audio``'s own validator names
    the class of defect and the position rather than the value, but a pydantic
    ``ValidationError`` carries the rejected **input** whatever its message says —
    so the entry point has to refuse without quoting it.
    """
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments("receive", _spoken_input(_NEAR_VALID))

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
        _decode_arguments("receive", _spoken_input(_NEAR_VALID))

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_a_non_audio_argument_still_quotes_what_its_type_refused() -> None:
    """The refusal path is narrowed to recordings and takes no diagnostics elsewhere.

    ADR-0200 §9's clause is about a value that is a recording; every other
    argument's refusal is unchanged, which is what keeps this a §9 fix rather than a
    quiet narrowing of what an operator can see.
    """
    with pytest.raises(UndecodableFrameError) as caught:
        _decode_arguments("belief", {"record_id": 17})

    assert caught.value.__cause__ is not None


def test_a_well_formed_spoken_input_is_refused_as_a_combination_and_not_echoed() -> None:
    """ADR-0313 §3:2, §4:1: the recording decodes, and the combination is refused.

    Refused at the far side as an unsupported combination, before any row is read or
    the engine is called, and with no part of the recording in the refusal.
    """
    with pytest.raises(UndecodableFrameError, match="unsupported channel") as caught:
        _decode_arguments("receive", _spoken_input(_CLIP))

    assert _CLIP not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_recording_projects_as_ordinary_text() -> None:
    """§9: "no file under ``wire/`` changes to carry audio".

    The recording is two members of an ordinary model, one of them a string — so
    ``project`` renders it through the ``BaseModel`` branch it already had, and no
    ``bytes`` row is involved anywhere.
    """
    projected = project(SpokenAudio(content=_CLIP, media_type=SpokenAudioFormat.MP4))

    assert projected == {"content": _CLIP, "media_type": "audio/mp4"}

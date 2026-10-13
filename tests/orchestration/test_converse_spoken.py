"""The spoken turn, composed on the hub (ADR-0200 §§2-4, §6-§8).

Every row of ADR-0200 §13's table that falls inside this lane's fence and is about
the *engine* rather than about a type: the blank-transcript shapes, the local
refusals, the format pick, the four degradations, the total failure translation,
the budget threaded to each stage, cancellation, and retention. ADR-0199's
withholding at supply is next door in ``test_spoken_disclosure.py``, because it is
about what reaches the composing stage rather than about what the call returns.

``Harness`` wires the two canonical speech fakes by default, so a case that cares
about one seam narrows or arms that one and leaves the other alone; passing
``None`` for either is the unwired deployment.
"""

from __future__ import annotations

import ast
from base64 import b64encode
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from test_engine import Harness

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import SpokenAudio, SpokenAudioFormat
from ai_assistant.orchestration import engine as engine_module
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.speech import SPOKEN_PARK_SENTENCE
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_assistant.core.protocols import ModelProvider

    #: A builder for one of ADR-0207 §1's two park shapes, so both parametrise alike.
    type _ParkSubject = Callable[..., Awaitable[Harness]]

_WEBM: Final = SpokenAudioFormat.WEBM_OPUS
_MP4: Final = SpokenAudioFormat.MP4

#: A recognisable span, so a retention assertion looks for one thing rather than
#: for "any audio". It is what the recording decodes to, so finding it anywhere is
#: finding the recording.
_CLIP: Final = "PRIVATE-CLIP-MARKER"

_ANSWER: Final = "You went hiking on Tuesday."


def _recording(media_type: SpokenAudioFormat = _MP4, *, payload: str = _CLIP) -> SpokenAudio:
    """One recording, in ``media_type``, whose octets carry a findable marker."""
    return SpokenAudio(content=b64encode(payload.encode()).decode("ascii"), media_type=media_type)


def _wired(model: ModelProvider | None = None, /, **knobs: object) -> Harness:
    """A harness whose composing stage runs over ``model`` (or over a fixed answer)."""
    stage = ComposingStage(
        model=FakeModelProvider(_ANSWER) if model is None else model,
        streaming=FakeStreamingCompleter(),
    )
    return Harness(composing=stage, **knobs)  # type: ignore[arg-type]  # heterogeneous harness knobs


# --- ADR-0207 §2, §5: the bytes, spelled once and owned by one package -------


def test_the_sentence_is_the_bytes_adr_0207_fixes() -> None:
    """§2: "those bytes, that punctuation, that terminal full stop".

    The **one** place the literal is written down; every other case refers to the
    constant, so a wording change looks like one decision rather than a dozen. It is
    the owner's product ruling on #1699 carried into the ADR unchanged: different
    words are a product decision needing an ADR that supersedes §2, not an editorial
    pass over a test.
    """
    assert SPOKEN_PARK_SENTENCE == "I need you to confirm something on your screen."


def test_only_the_orchestration_constant_spells_the_sentence() -> None:
    """§5: ``ai_assistant.orchestration`` **owns** it, and no other package copies it.

    A constant an adapter could copy is a rule an adapter has re-decided: to render
    it, ``interfaces/`` would have to hold both the literal and §1's park test, which
    is business logic in a layer supposed to have none, and the two copies would
    drift the first time either moved. The canonical fake satisfies §5's third
    exception by **naming** this object, and that is checked here as an absence
    rather than trusted.
    """
    root = Path(engine_module.__file__).resolve().parents[1]
    spelling = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if SPOKEN_PARK_SENTENCE in path.read_text(encoding="utf-8")
    }

    assert spelling == {"orchestration/speech.py"}


# --- §2, §5: where this may and may not be wired -----------------------------


@pytest.mark.parametrize("missing", ["transcriber", "synthesizer"])
def test_half_a_speech_pipeline_is_refused_at_construction(missing: str) -> None:
    """One seam without the other can hear and never answer, which nobody chose."""
    with pytest.raises(ConfigurationError, match="both"):
        _wired(**{missing: None})


def test_the_service_package_holds_neither_speech_protocol() -> None:
    """§5: "none is wired into ``ai_assistant.service`` as a resident job".

    Read over the package's own source rather than over an import graph, because a
    module that merely *named* either Protocol would already be a step toward the
    wiring §5 forbids — so the check is the stricter of the two.
    """
    from ai_assistant import service  # noqa: PLC0415 — asserted about

    _assert_no_speech_protocol_under(Path(service.__file__).parent)


def test_no_module_under_interfaces_references_either_speech_protocol() -> None:
    """§2: "no adapter calls a ``SpeechTranscriber`` or a ``SpeechSynthesizer`` at all"."""
    from ai_assistant import interfaces  # noqa: PLC0415 — asserted about

    _assert_no_speech_protocol_under(Path(interfaces.__file__).parent)


def _assert_no_speech_protocol_under(root: Path) -> None:
    """Fail if any module under ``root`` names either speech Protocol."""
    modules = sorted(root.rglob("*.py"))
    assert modules, f"{root} holds no modules, so this check would pass vacuously"
    for module in modules:
        source = module.read_text(encoding="utf-8")
        assert "SpeechTranscriber" not in source, module
        assert "SpeechSynthesizer" not in source, module


def test_the_wire_codec_carries_no_audio_branch() -> None:
    """§9: "``wire/codec.py``'s ``project`` gains no branch".

    Audio crosses as :data:`~ai_assistant.core.types.Base64Audio`, which is text,
    so the codec needs to know nothing about it — and a lane that reached for a
    ``bytes`` row would be taking the supersession ADR-0200 §9 declined.
    """
    from ai_assistant.wire import codec  # noqa: PLC0415 — asserted about

    source = Path(codec.__file__).read_text(encoding="utf-8")
    for name in ("SpokenAudio", "Base64Audio", "SpokenAudioFormat", "b64", "base64"):
        assert name not in source, name


def test_a_frozenset_of_formats_has_no_wire_form() -> None:
    """§3: ``plays`` is a tuple because a set would fail closed at the first call.

    ``wire/codec.py``'s ``project`` dispatches ``list | tuple`` and has no branch
    for a ``set`` or a ``frozenset``, so a set-typed argument raises rather than
    guessing at an order — the same fallthrough that decides §9.
    """
    from ai_assistant.wire.codec import project  # noqa: PLC0415 — asserted about

    assert project((_MP4, _WEBM)) == [_MP4.value, _WEBM.value]
    with pytest.raises(TypeError):
        project(frozenset({_MP4}))


# --- §4: every raise on this path passes its classification -------------------


def test_every_transcription_failure_raised_in_orchestration_names_its_failure() -> None:
    """§4: "Every raise on this path passes ``failure`` explicitly".

    The default exists for ADR-0085 §10a's reduced payload and for nothing else, and
    an implementation that leaned on it would silently report every seam failure as
    ``UNCLASSIFIED`` beside ``details_elided`` ``False`` — which reads as "the seam
    raised a bare ``SpeechError``" and would be a lie on every timeout.

    Checked over the syntax rather than over a run, because a run only reaches the
    raises the cases happen to drive.
    """
    root = Path(engine_module.__file__).parent
    raises = [
        node
        for module in sorted(root.rglob("*.py"))
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TranscriptionFailedError"
    ]
    assert raises, "no TranscriptionFailedError is constructed in orchestration/"
    for call in raises:
        assert any(keyword.arg == "failure" for keyword in call.keywords), ast.dump(call)


# --- §6: the bound has to be able to bind ------------------------------------


@pytest.mark.parametrize("unusable", [float("nan"), float("inf"), 1.5, True, 0, -1])
def test_an_audio_bound_that_could_not_bind_is_refused_at_construction(
    unusable: object,
) -> None:
    """§6's ceiling is guarded where it is injected, not only where it is configured.

    ``Settings`` refuses these at load, but this is a **constructor** argument and a
    composition root is not the only caller. The failure mode is also the silent
    kind rather than the loud one: ``float("nan")`` compares ``False`` against every
    ``>``, so an engine built with one would admit a recording of any length and
    return a rendering of any length while reporting health — a bound that cannot
    bind is not a weaker bound but an absent one. ``True`` earns its place twice
    over: a one-byte audio ceiling refuses every recording a browser can produce.
    """
    with pytest.raises((TypeError, ValueError), match="max_spoken_audio_bytes"):
        _wired(max_spoken_audio_bytes=unusable)

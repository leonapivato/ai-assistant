"""Where the speech seams may be wired, and the bound on what they carry (ADR-0200 §2, §6).

The spoken turn these seams served retired with ``converse_spoken`` (ADR-0313 §3:1),
and with it the cases about the call and ADR-0207's park sentence; the seams stay for
voice's own design (§3:7), and so do these rules about their wiring.

``Harness`` wires the two canonical speech fakes by default; passing ``None`` for
either is the unwired deployment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from test_engine import Harness

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import SpokenAudioFormat

_WEBM: Final = SpokenAudioFormat.WEBM_OPUS
_MP4: Final = SpokenAudioFormat.MP4


def _wired(**knobs: object) -> Harness:
    """A harness over ``knobs``."""
    return Harness(**knobs)  # type: ignore[arg-type]  # heterogeneous harness knobs


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

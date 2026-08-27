"""What this lane's implementations are, and are not, reachable from.

ADR-0200 §5's second clause: no implementation of either speech Protocol "is
wired into ``ai_assistant.service`` as a resident job, a scheduler task or a poll
loop". That is a claim about something *not* happening, so it is checked over the
source rather than inferred from behaviour — a runtime test would only show that
the seam was not reached on the path it happened to drive.

The scan is textual on purpose. A reference is what would have to appear for a
wiring to exist, and a check that imported the package instead would pass for a
module that constructs a transcriber inside a function nobody called on import.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ai_assistant

_ROOT = Path(ai_assistant.__file__).resolve().parent

#: The names a wiring would have to mention: the contracts, the implementations,
#: their module, and the library beneath them.
_SPEECH_NAMES = (
    "SpeechTranscriber",
    "SpeechSynthesizer",
    "MoonshineTranscriber",
    "SupertonicSynthesizer",
    "moonshine_transcriber",
    "supertonic_synthesizer",
    "sherpa_onnx",
)


def _sources(package: str) -> list[Path]:
    return sorted((_ROOT / package).rglob("*.py"))


def test_the_resident_process_holds_neither_speech_seam() -> None:
    # ADR-0200 §5. The hub stays a hub: nothing here starts an engine, polls one,
    # or schedules work onto one. When ADR-0200 §3's turn arrives it reaches speech
    # through the engine, which is a different thing from the service holding one.
    offenders = {
        path.relative_to(_ROOT): name
        for path in _sources("service")
        for name in _SPEECH_NAMES
        if name in path.read_text(encoding="utf-8")
    }

    assert offenders == {}


def test_the_service_sources_were_actually_read() -> None:
    # The check above is vacuously true over an empty file list, which is exactly
    # what a moved package would produce. This is what stops it passing for the
    # wrong reason.
    assert len(_sources("service")) >= 1


@pytest.mark.parametrize("name", ["av", "sherpa_onnx"])
def test_the_speech_libraries_are_confined_to_the_models_layer(name: str) -> None:
    # Golden rule 4's mechanical half is `lint-imports`, which forbids these
    # outside `models/`. This is the complementary reading — *which* modules
    # inside `models/` may import them — so that a future re-export from the
    # package root, which would put a second inference runtime on every import
    # path, is a failing test rather than a review catch.
    importers = {
        path.relative_to(_ROOT)
        for path in _sources("models")
        if f"import {name}" in path.read_text(encoding="utf-8")
    }
    allowed = {
        Path("models/speech_container.py"): "av",
        Path("models/moonshine_transcriber.py"): "sherpa_onnx",
        Path("models/supertonic_synthesizer.py"): "sherpa_onnx",
    }

    assert importers == {path for path, library in allowed.items() if library == name}

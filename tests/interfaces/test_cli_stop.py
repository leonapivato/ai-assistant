"""``assistant stop`` on the command line (ADR-0297 §5:8, ADR-0295 §1).

The command relays ``stop_activation`` and prints the answer's meaning: one fixed
sentence per :class:`~ai_assistant.core.types.ActivationStop` member, and an exit code
that is zero only where the stop acted. The answers a running activation would give are
scripted over the canonical fake, which holds a running activation only while a channel
pass is in flight; the answer an unknown id gets is the fake's own.
"""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import ActivationStop
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.types import Identifier

#: An activation id as the current state names one (ADR-0275 §6:1's canonical UUID4).
_ACTIVATION: Final = "00000000-0000-4000-8000-000000000001"

#: What each answer exits with — a table, so a new member is a ``KeyError`` here.
_EXIT_CODES: Final[dict[ActivationStop, int]] = {
    ActivationStop.STOPPED: 0,
    ActivationStop.ALREADY_ENDED: 1,
    ActivationStop.NO_SUCH_ACTIVATION: 1,
}

#: The words each answer is said in, as the user reads them.
_SAID: Final[dict[ActivationStop, str]] = {
    ActivationStop.STOPPED: "Stopped. Nothing new starts in that work from now on",
    ActivationStop.ALREADY_ENDED: "That had already ended, so this stopped nothing",
    ActivationStop.NO_SUCH_ACTIVATION: "Nothing here says work of that id ran",
}


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _flat(rendered: str) -> str:
    """The rendered text with wrapping and continuation markers flowed back."""
    return " ".join(rendered.replace("↳", " ").split())


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the command's client at ``engine``."""

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


class _Answering(FakeAssistantEngine):
    """An engine whose stop answers as scripted, recording what it was asked."""

    def __init__(self, answer: ActivationStop) -> None:
        super().__init__()
        self.scripted = answer
        self.asked: list[str] = []

    async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
        self.asked.append(activation_id)
        return self.scripted


@pytest.mark.parametrize("member", list(ActivationStop))
def test_every_answer_is_said_and_exits_by_whether_it_acted(
    member: ActivationStop, monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5:8: one fixed sentence per member, over the vocabulary itself.

    Parametrised over :class:`ActivationStop` rather than a list of its members, so a
    member arriving without a sentence or an exit code fails here instead of inheriting
    one. Only ``STOPPED`` acted; the other two wrote nothing (§5:5, §5:6).
    """
    engine = _Answering(member)
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["stop", _ACTIVATION]).exit_code

    assert engine.asked == [_ACTIVATION]
    assert _SAID[member] in _flat(output.getvalue())
    assert code == _EXIT_CODES[member]
    assert cli._STOP_EXIT_CODES == _EXIT_CODES
    assert set(cli._STOP_PHRASES) == set(ActivationStop)


def test_a_stop_promises_no_halt_mid_step_and_no_recall(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0295 §2's guarantees, and only those: nothing new starts after the stop.

    A stage already running finishes under its own deadlines (ADR-0297 §4) and an effect
    already sent is not cut off (ADR-0295 §2:3), so the sentence says both rather than
    promising that everything halted.
    """
    _wire(monkeypatch, _Answering(ActivationStop.STOPPED))

    CliRunner().invoke(cli.app, ["stop", _ACTIVATION])

    said = _flat(output.getvalue())
    assert "What it was in the middle of finishes first" in said
    assert "not called back" in said
    assert "No goal is given up" in said


def test_an_id_nothing_says_ran_is_the_fakes_own_answer(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5:6 end to end over the canonical fake: no running activation and no episode."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    code = CliRunner().invoke(cli.app, ["stop", f"  {_ACTIVATION}  "]).exit_code

    assert code == 1
    assert ("stop_activation", {"activation_id": _ACTIVATION}) in engine.calls
    assert "Nothing here says work of that id ran" in _flat(output.getvalue())


def test_a_blank_id_is_a_usage_error_before_any_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0085 §3c: refused while Typer parses, never as an uncaught ``ValueError``."""
    engine = _Answering(ActivationStop.STOPPED)
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["stop", "   "])

    assert result.exit_code == 2
    assert engine.asked == []


def test_a_failed_stop_is_rendered_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0042 §7: the engine's refusal is rendered, not raised as a traceback."""

    class _Failing(FakeAssistantEngine):
        async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
            msg = "the episode store could not be read"
            raise MemoryStoreError(msg)

    _wire(monkeypatch, _Failing())

    result = CliRunner().invoke(cli.app, ["stop", _ACTIVATION])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Stopped." not in output.getvalue()

"""The activation carried for the diagnostic record, and the one way an entry is written.

ADR-0314 §5:4's module: what is bound, for how long, who sees it, and that an emitter
whose sink is ``None`` builds nothing (§2:1) and one whose entry cannot be built loses
only the entry, logged by activation, source and class (§2:4).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Final, NoReturn

import structlog

from ai_assistant.core.diagnostics import (
    DIAGNOSTIC_NOT_WRITTEN,
    diagnosed_activation,
    diagnosed_activation_id,
    failure_body,
    returned_written,
    write_diagnostic,
    write_failure,
)
from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.testing import FakeDiagnosticSink

_AT: Final = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
_ACTIVATION: Final = "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35"
_OTHER: Final = "9a1c7e52-6b3d-4f80-8e2a-1c5d7b9f0e46"


def _clock() -> datetime:
    return _AT


def _never() -> NoReturn:
    msg = "a body was built where no entry was due"
    raise AssertionError(msg)


async def test_an_entry_is_written_for_the_bound_activation_on_its_clock() -> None:
    sink = FakeDiagnosticSink()

    with diagnosed_activation(_ACTIVATION, clock=_clock):
        await write_diagnostic(
            sink, DiagnosticSource.RECALL, DiagnosticKind.GIVEN, lambda: {"cue": "x"}
        )

    assert sink.recorded == (
        DiagnosticEntry(
            activation_id=_ACTIVATION,
            source=DiagnosticSource.RECALL,
            kind=DiagnosticKind.GIVEN,
            recorded_at=_AT,
            body={"cue": "x"},
        ),
    )


async def test_no_sink_builds_nothing() -> None:
    """§2:1: where the record is off, no entry is built."""
    with diagnosed_activation(_ACTIVATION, clock=_clock):
        await write_diagnostic(None, DiagnosticSource.RECALL, DiagnosticKind.GIVEN, _never)


async def test_no_binding_writes_nothing() -> None:
    """§5:4: nothing is written where no activation is bound."""
    sink = FakeDiagnosticSink()

    await write_diagnostic(sink, DiagnosticSource.PLANNING, DiagnosticKind.RETURNED, _never)

    assert sink.recorded == ()
    assert diagnosed_activation_id() is None


async def test_a_body_that_cannot_be_built_costs_the_entry_and_is_logged_without_content() -> None:
    """§2:4: logged by activation, source and class; the work goes on."""
    sink = FakeDiagnosticSink()

    def unencodable() -> dict[str, object]:
        return {"text": "the user's words", "score": float("nan")}

    with (
        structlog.testing.capture_logs() as captured,
        diagnosed_activation(_ACTIVATION, clock=_clock),
    ):
        await write_diagnostic(
            sink, DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED, unencodable
        )

    assert sink.recorded == ()
    assert [one for one in captured if one["event"] == DIAGNOSTIC_NOT_WRITTEN] == [
        {
            "event": DIAGNOSTIC_NOT_WRITTEN,
            "log_level": "warning",
            "activation_id": _ACTIVATION,
            "source": "digesting",
            "error_class": "ValidationError",
        }
    ]
    assert "the user's words" not in repr(captured)


async def test_a_sink_breaking_its_contract_still_costs_only_the_entry() -> None:
    class _Raising:
        async def write(self, entry: DiagnosticEntry) -> None:
            msg = "disk full"
            raise OSError(msg)

    with diagnosed_activation(_ACTIVATION, clock=_clock):
        await write_diagnostic(_Raising(), DiagnosticSource.RECALL, DiagnosticKind.GIVEN, dict)


async def test_returned_entries_are_counted_per_source_in_the_run() -> None:
    """How planning knows whether the completer wrote its returned entry (§5:2)."""
    sink = FakeDiagnosticSink()
    assert returned_written(DiagnosticSource.PLANNING) == 0

    with diagnosed_activation(_ACTIVATION, clock=_clock):
        await write_diagnostic(sink, DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, dict)
        before = returned_written(DiagnosticSource.PLANNING)
        await write_failure(sink, DiagnosticSource.PLANNING, RuntimeError("no response"))
        after = returned_written(DiagnosticSource.PLANNING)

    assert (before, after) == (0, 1)
    assert returned_written(DiagnosticSource.PLANNING) == 0


async def test_a_binding_reaches_tasks_created_inside_it_and_no_others() -> None:
    """Per-context: two activations on one loop never see each other's binding."""
    seen: dict[str, str | None] = {}

    async def run(activation: str) -> None:
        with diagnosed_activation(activation, clock=_clock):
            await asyncio.sleep(0)
            child = asyncio.ensure_future(asyncio.sleep(0, result=diagnosed_activation_id()))
            seen[activation] = await child

    await asyncio.gather(run(_ACTIVATION), run(_OTHER))

    assert seen == {_ACTIVATION: _ACTIVATION, _OTHER: _OTHER}
    assert diagnosed_activation_id() is None


def test_a_nested_binding_restores_the_outer_one() -> None:
    with diagnosed_activation(_ACTIVATION, clock=_clock):
        with diagnosed_activation(_OTHER, clock=_clock):
            assert diagnosed_activation_id() == _OTHER
        assert diagnosed_activation_id() == _ACTIVATION


def test_a_failure_is_given_by_its_class_and_message() -> None:
    assert failure_body(ValueError("the reason")) == {
        "class": "ValueError",
        "message": "the reason",
    }


def test_a_failure_whose_text_cannot_be_read_still_has_its_class() -> None:
    class _UnprintableError(Exception):
        def __str__(self) -> str:
            raise RuntimeError

    assert failure_body(_UnprintableError()) == {"class": "_UnprintableError", "message": ""}

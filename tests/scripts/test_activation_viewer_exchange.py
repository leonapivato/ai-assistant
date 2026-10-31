"""The activation viewer over a work's exchange (ADR-0356 §5, §7, §13:6, §14:9).

Since ADR-0356 a planning request records the work's exchange as handed in: its first
round's briefing alone, each later round's the earlier responses and the system's report
on each (§13:6). A round's text is its notes, written to no one (§7:2), and what people
receive comes from its message calls (§7:3). The record holds no entry for a call (acting
writes none, ADR-0314 §4:3): what came of a round's calls is in the next round's request,
as its report's results, and the last round's are in no request at all.

The record here is written by ADR-0314's own store, its exchange built from ``core``'s
own types, so a change to the shape the viewer reads fails these cases. A round recorded
before the decision keeps its reading, held by ``test_activation_viewer_walk.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Final

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import at, step, viewer

from ai_assistant.core.types import (
    CallResult,
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    ExchangeStep,
    PlanningExchange,
    ProposedCall,
    RoundReport,
    RoundResponse,
)
from ai_assistant.evaluation.diagnostic_record import FileDiagnosticRecord

pytestmark = pytest.mark.integration

_ID: Final = "exchanged"
_NOTES_1: Final = "Searching first; the booking needs a yes."
_NOTES_2: Final = "TP 1351 fits the morning the user asked for."
_SAID_1: Final = "Looking up the Lisbon flights now."
_SAID_2: Final = "I found TP 1351 at 09:40 for 212 EUR. Shall I book it?"
_SEARCH: Final = {"query": "Lisbon flights May"}
_RESULT: Final = "TP 1351 departs 09:40, 212 EUR."
_SENT: Final = "sent"
_NEWS: Final = "nothing has changed since your last round"
#: ADR-0356 §7:4: no name is reserved since, so a capability may be called this.
_NAMED_SO: Final = {"notes": "an argument, not notes", "another_round": True}

_ROUND_1: Final = RoundResponse(
    text=_NOTES_1,
    calls=(
        ProposedCall(call_id="c1", name="web_search", arguments=_SEARCH),
        ProposedCall(call_id="c2", name="text", arguments={"words": _SAID_1}),
    ),
)
_BRIEFING: Final = PlanningExchange(instruction="planning", briefing="the briefing")
_LATER: Final = _BRIEFING.model_copy(
    update={
        "steps": (
            ExchangeStep(
                response=_ROUND_1,
                report=RoundReport(
                    results=(
                        CallResult(call_id="c1", text=_RESULT),
                        CallResult(call_id="c2", text=_SENT),
                    ),
                    news=_NEWS,
                ),
            ),
        )
    }
)


def _given(exchange: PlanningExchange) -> dict[str, Any]:
    return {"exchange": exchange.model_dump(mode="json"), "tools": []}


def _returned(text: str, *calls: tuple[str, object, str]) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"part_kind": "text", "content": text}]
    parts += [
        {"part_kind": "tool-call", "tool_name": name, "args": args, "tool_call_id": call_id}
        for name, args, call_id in calls
    ]
    return {"response": {"parts": parts, "kind": "response"}, "read_as_round": True}


_ENTRIES: Final[list[tuple[DiagnosticSource, DiagnosticKind, int, dict[str, Any]]]] = [
    (DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, 470, _given(_BRIEFING)),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        900,
        _returned(_NOTES_1, ("web_search", _SEARCH, "c1"), ("text", {"words": _SAID_1}, "c2")),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        901,
        step("planning", "first_round_due", 460, 901),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1150,
        step("acting", "round_authorized", 905, 1150),
    ),
    (DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, 1170, _given(_LATER)),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        1600,
        _returned(
            _NOTES_2,
            ("text", '{"words": "' + _SAID_2 + '"}', "c3"),
            ("planning_round", _NAMED_SO, "c4"),
        ),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1601,
        step("planning", "round_due", 1160, 1601),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1800,
        step("acting", "round_authorized", 1605, 1800),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1801,
        step("end", "nothing_due", 1801, 1801),
    ),
]


async def _write(directory: Path) -> None:
    store = FileDiagnosticRecord(directory=directory, file_bytes=8 * 1024 * 1024)
    for source, kind, ms, body in _ENTRIES:
        await store.write(
            DiagnosticEntry(
                activation_id=_ID, source=source, kind=kind, recorded_at=at(ms), body=body
            )
        )


@pytest.fixture
def lines(tmp_path: Path) -> list[Any]:
    directory = tmp_path / "data" / "diagnostics"
    directory.mkdir(parents=True)
    asyncio.run(_write(directory))
    read = viewer.Record(directory.parent).lines(_ID)
    assert read is not None
    held: list[Any] = read[0]
    return held


def _planning(walked: dict[str, Any]) -> list[dict[str, Any]]:
    return [one for one in walked["steps"] if one["phase"] == "planning"]


def test_a_rounds_text_is_its_notes_and_its_message_calls_are_its_messages(
    lines: list[Any],
) -> None:
    first, second = _planning(viewer.walk(lines))
    assert first["exchange"] is True
    assert (first["notes"], first["message"]) == (_NOTES_1, "")
    assert first["message_calls"] == [{"id": "c2", "words": _SAID_1}]
    # Arguments the response wrote as a JSON string are read as written.
    assert second["message_calls"] == [{"id": "c3", "words": _SAID_2}]
    assert second["notes"] == _NOTES_2


def test_the_round_before_is_read_from_the_exchanges_last_step(lines: list[Any]) -> None:
    first, second = _planning(viewer.walk(lines))
    assert (first["first"], first["before"]) == (True, None)
    before = second["before"]
    assert before["round"] == 1
    assert (before["text"], before["notes"], before["news"]) == (None, _NOTES_1, _NEWS)
    assert [(one["id"], one["capability"], one["message"]) for one in before["calls"]] == [
        ("c1", "web_search", None),
        ("c2", "text", _SAID_1),
    ]
    assert [one["result"] for one in before["calls"]] == [
        {"label": None, "text": _RESULT},
        {"label": None, "text": _SENT},
    ]


def test_each_call_shows_what_came_of_it_and_the_last_rounds_say_none_is_held(
    lines: list[Any],
) -> None:
    """§8:3: what came of a call as planning was shown it, from the next round's report;
    the last round's calls are in no request, and the record holds no entry for them."""
    first, second = _planning(viewer.walk(lines))
    assert first["came_of"] == {
        "c1": {"label": None, "text": _RESULT},
        "c2": {"label": None, "text": _SENT},
    }
    assert "came_of_note" not in first
    assert second["came_of"] is None
    assert second["came_of_note"] == viewer.NO_CALL_ENTRY


def test_the_timeline_marks_an_exchange_round_and_its_message_calls(lines: list[Any]) -> None:
    rounds = viewer.timeline(_ID, lines)["rounds"]
    assert [(one["exchange"], one["text"], one["messages"]) for one in rounds] == [
        (True, _NOTES_1, [_SAID_1]),
        (True, _NOTES_2, [_SAID_2]),
    ]


def test_a_call_named_as_the_retired_round_tool_is_a_call_like_any_other(
    lines: list[Any],
) -> None:
    """§7:4, §14:5: in a work's exchange no tool name is reserved, so a call named
    ``planning_round`` is shown as a call, and its arguments are never read as notes."""
    _, second = _planning(viewer.walk(lines))
    assert [one["name"] for one in second["calls"]] == ["text", "planning_round"]
    assert (second["notes"], second["asks"], second["another_round"]) == (_NOTES_2, None, False)
    timeline = viewer.timeline(_ID, lines)["rounds"][1]
    assert [one["name"] for one in timeline["calls"]] == ["text", "planning_round"]
    assert timeline["marked"] is False

    alone = _returned("", ("planning_round", _NAMED_SO, "c1"))
    proposed = viewer._proposed(alone, exchange=True)
    assert [one["name"] for one in proposed["calls"]] == ["planning_round"]
    assert (proposed["notes"], proposed["another_round"]) == (None, False)
    did = viewer._did("planning", alone, exchange=True)
    assert [(one["kind"], one["title"]) for one in did["parts"]] == [
        ("text", "Text"),
        ("call", "Call · planning_round"),
    ]
    # A round recorded before reads the reserved tool as it was written.
    assert viewer._proposed(alone)["notes"] == "an argument, not notes"

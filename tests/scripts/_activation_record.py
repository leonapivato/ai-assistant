"""The record and the server ``scripts/activation_viewer.py``'s tests share (ADR-0316).

The record is written with ADR-0314's own store, so a change to the line the viewer
reads fails the tests that read it (§7:2); the lines the store cannot write are
appended by hand, as the viewer must cope with them (§5:3).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.evaluation.diagnostic_record import MIN_FILE_BYTES, FileDiagnosticRecord

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import load

if TYPE_CHECKING:
    from collections.abc import Iterator

viewer = load("activation_viewer")

#: Raw outside text, as the record holds it: the page must show it as text.
HOSTILE = '<script>alert("x")</script><img src=x onerror="alert(1)">'

#: A string that must never reach the viewer's own output.
PRIVATE = "the-secret-the-viewer-must-never-print"

_T0 = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)


def at(ms: int) -> datetime:
    return _T0 + timedelta(milliseconds=ms)


def iso(ms: int) -> str:
    return at(ms).isoformat()


def step(stage: str, due: str, start: int, end: int, outcome: str = "done") -> dict[str, Any]:
    return {
        "stage": stage,
        "due": due,
        "started_at": iso(start),
        "ended_at": iso(end),
        "outcome": outcome,
        "step_disposition": None,
        "route_outcome": None,
    }


def _understanding_request(text: str) -> dict[str, Any]:
    payload = {"input": {"received_as": "the message the user just sent", "text": text}}
    return {
        "messages": [
            {"role": "system", "content": "instruction", "name": None},
            {"role": "user", "content": json.dumps(payload), "name": None},
        ]
    }


def _response(
    *parts: dict[str, Any], offered: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "response": {"parts": list(parts), "kind": "response"},
        "read_as_round": True,
    }
    if offered is not None:
        body["offered_tools"] = offered
    return body


def _tool(name: str, description: str) -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "object"}}


#: The reserved tool's description, as the completer offers it (#2894).
ROUND_TOOL_DESCRIPTION = "Not a capability: calling it runs nothing and goes to no one."

#: Every tool round 1's request offered, in its order, the reserved one last (#2909).
#: Round 2's returned entry is written as one from before #2909, with no such list.
OFFERED = [_tool("web_search", "Search the web."), _tool("planning_round", ROUND_TOOL_DESCRIPTION)]


def _text(content: str) -> dict[str, Any]:
    return {"part_kind": "text", "content": content}


def _call(name: str, args: object, call_id: str) -> dict[str, Any]:
    return {"part_kind": "tool-call", "tool_name": name, "args": args, "tool_call_id": call_id}


#: One activation as ADR-0314 §4's sources write it: two rounds, a call that needs the
#: user, a message allowed, outside content read, and a digest that failed.
ACTIVATION: list[tuple[DiagnosticSource, DiagnosticKind, int, dict[str, Any]]] = [
    (DiagnosticSource.UNDERSTANDING, DiagnosticKind.GIVEN, 10, _understanding_request(HOSTILE)),
    (DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED, 400, {"reply": '{"meaning": "x"}'}),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        401,
        step("understanding", "not_understood", 5, 401),
    ),
    (DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, 420, {"messages": [], "tools": []}),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        900,
        _response(
            {"part_kind": "thinking", "content": "considering"},
            _text("Looking that up. " + PRIVATE),
            _call("web_search", {"query": "q"}, "c1"),
            _call("web_search", {"query": "r"}, "c2"),
            # The round's own tool, as the completer offers it: as a JSON string, and
            # asking for another round.
            _call("planning_round", '{"notes": ["n"], "another_round": true}', "c3"),
            offered=OFFERED,
        ),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        901,
        step("planning", "first_round_due", 410, 901),
    ),
    (
        DiagnosticSource.AUTHORIZING,
        DiagnosticKind.RETURNED,
        950,
        {
            "round": "round:1",
            "calls": [
                {
                    "call_id": "c1",
                    "name": "web_search",
                    "checks": [{"check": "selection", "verdict": "passed", "reason": None}],
                    "verdict": "allowed",
                    "reason": None,
                },
                {
                    "call_id": "c2",
                    "name": "web_search",
                    "checks": [{"check": "selection", "verdict": "passed", "reason": None}],
                    "verdict": "needs_you",
                    "reason": "asks first",
                },
            ],
            "read_outside_content": True,
            "grounds": [{"ground": "fetched_outside", "record": None}],
        },
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        951,
        step("authorizing", "round_unauthorized", 905, 951),
    ),
    (
        DiagnosticSource.DIGESTING,
        DiagnosticKind.GIVEN,
        960,
        {"result": "r1", "question": "q", "part": 1, "parts": 1, "messages": []},
    ),
    (
        DiagnosticSource.DIGESTING,
        DiagnosticKind.RETURNED,
        1200,
        {
            "result": "r1",
            "question": "q",
            "part": 1,
            "parts": 1,
            "failure": {"class": "ModelError", "message": "x"},
        },
    ),
    (
        DiagnosticSource.DIGESTING,
        DiagnosticKind.RETURNED,
        1201,
        {"result": "r1", "question": "q", "digest": "failed", "reason": "raised"},
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1202,
        step("digesting", "recall_undigested", 955, 1202),
    ),
    (DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, 1220, {"messages": [], "tools": []}),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        1700,
        _response(_text("Here is the answer.")),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1701,
        step("planning", "round_due", 1210, 1701),
    ),
    (
        DiagnosticSource.AUTHORIZING,
        DiagnosticKind.RETURNED,
        1750,
        {
            "round": "round:2",
            "calls": [],
            "message": {"place": "chat", "allowed": True, "reason": None},
            "read_outside_content": True,
            "grounds": [],
        },
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1751,
        step("authorizing", "round_unauthorized", 1705, 1751),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1900,
        step("acting", "round_authorized", 1755, 1900),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1901,
        step("end", "nothing_due", 1901, 1901),
    ),
]

#: Lines the store cannot write but the viewer must cope with (ADR-0316 §5:3).
FOREIGN_LINES = [
    {
        "activation_id": "act-1",
        "source": "planning",
        "kind": "pondered",
        "recorded_at": iso(1950),
        "body": {"x": 1},
    },
    {
        "activation_id": "act-1",
        "source": "oracle",
        "kind": "given",
        "recorded_at": iso(1960),
        "body": {"y": 2},
    },
]


async def _write(
    directory: Path,
    activation_id: str,
    file_bytes: int,
    entries: list[tuple[DiagnosticSource, DiagnosticKind, int, dict[str, Any]]],
) -> None:
    store = FileDiagnosticRecord(directory=directory, file_bytes=file_bytes)
    for source, kind, ms, body in entries:
        await store.write(
            DiagnosticEntry(
                activation_id=activation_id,
                source=source,
                kind=kind,
                recorded_at=at(ms),
                body=body,
            )
        )


def write_record(tmp_path: Path) -> Path:
    """A record written by ADR-0314's store, plus the lines it cannot write."""
    directory = tmp_path / "data" / "diagnostics"
    directory.parent.mkdir()
    asyncio.run(_write(directory, "act-1", 8 * 1024 * 1024, ACTIVATION))
    with (directory / "act-1.jsonl").open("a", encoding="utf-8") as handle:
        for line in FOREIGN_LINES:
            handle.write(json.dumps(line) + "\n")
        handle.write("this is not json\n")
        handle.write(
            '{"activation_id": "act-1", "source": "planning", "kind": "given"'
        )  # no newline yet
    big = "x" * (MIN_FILE_BYTES * 2)
    truncated = [
        (
            DiagnosticSource.UNDERSTANDING,
            DiagnosticKind.GIVEN,
            100_000,
            _understanding_request("hello"),
        ),
        (DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED, 100_500, {"reply": big}),
    ]
    asyncio.run(_write(directory, "act-2", MIN_FILE_BYTES, truncated))
    return directory


@contextlib.contextmanager
def serving(record: Path) -> Iterator[Any]:
    """The viewer bound on loopback at a free port, over ``record``'s data directory."""
    reports: list[str] = []
    bound = viewer.ViewerServer(viewer.Record(record.parent), 0, report=reports.append)
    thread = threading.Thread(target=bound.serve_forever, args=(0.02,), daemon=True)
    thread.start()
    try:
        yield bound
    finally:
        bound.shutdown()
        bound.server_close()
        thread.join(timeout=5)

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


# --- an activation to walk, phase by phase ---------------------------------------------
# Shaped as the hub's sources write it today: recall's two runs, understanding's request
# holding what the first run kept under its labels and its reading in a fenced reply,
# two planning rounds each with the round before's outcome in its request, their verdicts,
# acting, a digest beside it, and the end (ADR-0309 §3's phases).

#: The walked activation's id, and what its user said.
WALKED = "walked"
WALKED_INPUT = "Book the Lisbon flight we talked about, and tell Ana. " + HOSTILE

#: What recall's first run kept, as the record names it, and their texts as understanding's
#: request shows them under its labels, in the same order.
KEPT_IDS = ("mem-lisbon", "mem-ana")
KEPT_FACTS = ("The user is flying to Lisbon in May.", "Ana is the user's sister.")

#: Understanding's reading, as its reply carries it inside a Markdown fence.
READING: dict[str, Any] = {
    "meaning": "Book the Lisbon flight and tell Ana it is booked.",
    "meaning_ground": "stated",
    "meaning_labels": ["M1"],
    "references": [{"phrase": "the Lisbon flight", "labels": ["M1"]}],
    "relationships": [
        {"statement": "Ana is the user's sister.", "labels": ["M2"], "ground": "supplied"}
    ],
    "unresolved": [{"matter": "Which date in May", "why_it_matters": "the fare depends on it"}],
    "story_labels": ["S1"],
    "answers": [],
    "continues": [],
}

#: Round 1's proposed call and its result, which round 2's request shows came back.
SEARCH_ARGUMENTS = {"query": "Lisbon flights May"}
SEARCH_RESULT = "TP 1351 departs 09:40, 212 EUR."
ROUND_NOTES = "Searching first; the booking needs a yes."
ROUND_2_MESSAGE = "I found TP 1351 at 09:40 for 212 EUR. Shall I book it?"


def _document(system: str, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": system, "name": None},
            {"role": "user", "content": json.dumps(document), "name": None},
        ],
        "prompt": {"name": system, "version": "v1", "origin": "shipped", "flags": {}},
    }


def _finds(cue: str, *found: tuple[str, float, str, bool]) -> list[dict[str, Any]]:
    return [
        {"id": one, "score": score, "band": band, "cue": cue, "admitted": admitted}
        for one, score, band, admitted in found
    ]


def _planning_request(
    rounds: list[dict[str, Any]], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    return _document(
        "planning",
        {
            "place": {"takes_message": True, "description": "a chat with the user"},
            "place_window": [{"label": "H1", "text": WALKED_INPUT, "is_the_input": True}],
            "recalled": [
                {"label": "M1", "fact": KEPT_FACTS[0]},
                {"label": "M2", "fact": KEPT_FACTS[1]},
                {"label": "M3", "fact": "The user prefers window seats."},
            ],
            "rounds": rounds,
            "evidence": evidence,
        },
    )


WALKED_ACTIVATION: list[tuple[DiagnosticSource, DiagnosticKind, int, dict[str, Any]]] = [
    (
        DiagnosticSource.RECALL,
        DiagnosticKind.GIVEN,
        10,
        {"run": "first", "cues": [{"text": WALKED_INPUT, "kinds": ["activation_input"]}]},
    ),
    (
        DiagnosticSource.RECALL,
        DiagnosticKind.RETURNED,
        60,
        {
            "finds": _finds(
                WALKED_INPUT,
                (KEPT_IDS[0], 0.91, "asserted", True),
                (KEPT_IDS[1], 0.84, "derived", True),
                ("mem-weather", 0.31, "asserted", False),
            ),
            "outcome": "found",
            "kept": [
                {"id": KEPT_IDS[0], "score": 0.91, "found_by": ["activation_input"]},
                {"id": KEPT_IDS[1], "score": 0.84, "found_by": ["activation_input"]},
            ],
        },
    ),
    (DiagnosticSource.CONTROLLER, DiagnosticKind.STEP, 61, step("recall", "not_recalled", 5, 61)),
    (
        DiagnosticSource.UNDERSTANDING,
        DiagnosticKind.GIVEN,
        70,
        _document(
            "understanding",
            {
                "input": {"received_as": "the message the user just sent", "text": WALKED_INPUT},
                "recalled": [
                    {"label": "M1", "item": "a memory the user stated", "fact": KEPT_FACTS[0]},
                    {"label": "M2", "item": "a memory derived", "fact": KEPT_FACTS[1]},
                ],
                "stories": [{"label": "S1", "summary": "Trip to Lisbon"}],
            },
        ),
    ),
    (
        DiagnosticSource.UNDERSTANDING,
        DiagnosticKind.RETURNED,
        400,
        {"reply": "```json\n" + json.dumps(READING) + "\n```"},
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        401,
        step("understanding", "not_understood", 65, 401),
    ),
    (
        DiagnosticSource.RECALL,
        DiagnosticKind.GIVEN,
        410,
        {
            "run": "second",
            "cues": [{"text": READING["meaning"], "kinds": ["understood_meaning"]}],
        },
    ),
    (
        DiagnosticSource.RECALL,
        DiagnosticKind.RETURNED,
        450,
        {
            "finds": _finds(READING["meaning"], ("mem-seat", 0.5, "attested", True)),
            "outcome": "found",
            "kept": [{"id": "mem-seat", "score": 0.5, "found_by": ["understood_meaning"]}],
        },
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        451,
        step("recall", "not_recalled", 405, 451),
    ),
    (DiagnosticSource.PLANNING, DiagnosticKind.GIVEN, 470, _planning_request([], [])),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        900,
        _response(
            _text("Looking for flights."),
            _call("web_search", SEARCH_ARGUMENTS, "c1"),
            _call("planning_round", {"notes": ROUND_NOTES, "asks": ["book_flight"]}, "c2"),
            offered=OFFERED,
        ),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        901,
        step("planning", "first_round_due", 460, 901),
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
                    "checks": [],
                    "verdict": "allowed",
                    "reason": None,
                },
            ],
            "message": {"place": "chat", "allowed": True, "reason": None},
            "read_outside_content": False,
            "grounds": [],
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
        1000,
        {"result": "r1", "question": "Which flight fits?", "part": 1, "parts": 1, "messages": []},
    ),
    (
        DiagnosticSource.DIGESTING,
        DiagnosticKind.RETURNED,
        1100,
        {
            "result": "r1",
            "question": "Which flight fits?",
            "part": 1,
            "parts": 1,
            "reply": '{"evidence": ["TP 1351 at 09:40"]}',
        },
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1101,
        step("digesting", "recall_undigested", 990, 1101),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1150,
        step("acting", "round_authorized", 955, 1150),
    ),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.GIVEN,
        1170,
        _planning_request(
            [
                {
                    "round": 1,
                    "text": "Looking for flights.",
                    "text_was": "written into the place",
                    "calls": [
                        {
                            "capability": "web_search",
                            "arguments": SEARCH_ARGUMENTS,
                            "outcome": "done",
                            "result": {"label": "R1", "value": SEARCH_RESULT},
                        }
                    ],
                    "notes": ROUND_NOTES,
                }
            ],
            [{"digest_of": "R1", "looking_for": "Which flight fits?", "digest": {"evidence": []}}],
        ),
    ),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        1600,
        _response(_text(ROUND_2_MESSAGE)),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1601,
        step("planning", "round_due", 1160, 1601),
    ),
    (
        DiagnosticSource.AUTHORIZING,
        DiagnosticKind.RETURNED,
        1650,
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
        1651,
        step("authorizing", "round_unauthorized", 1605, 1651),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1800,
        step("acting", "round_authorized", 1655, 1800),
    ),
    (
        DiagnosticSource.CONTROLLER,
        DiagnosticKind.STEP,
        1801,
        step("end", "nothing_due", 1801, 1801),
    ),
]

#: The walked activation's steps' titles, in its own order.
WALKED_TITLES = [
    "Input",
    "Recall · first run",
    "Understanding",
    "Recall · second run",
    "Planning · round 1",
    "Authorizing · round 1",
    "Acting",
    "Digesting",
    "Planning · round 2",
    "Authorizing · round 2",
    "Acting",
    "The end",
]


def write_walked(directory: Path) -> Path:
    """The walked activation, written by ADR-0314's store into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    asyncio.run(_write(directory, WALKED, 8 * 1024 * 1024, WALKED_ACTIVATION))
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

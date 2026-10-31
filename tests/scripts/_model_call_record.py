"""A record of model calls shaped like the hub's, for the viewer's readable view (ADR-0316).

Written with ADR-0314's own store, as ``_activation_record`` writes its record, so a
change to the line the viewer reads fails the tests that read it (§7:2). The bodies are
shaped as the sources write them today: understanding's and digesting's requests as a
system message and a user message holding one JSON object, their returned entries as the
reply alone; planning's request with its tools, and its returned entry with the tools
offered, the provider's whole response and its usage. Two planning rounds, so a round
can be compared with the one before it, and an activation of bodies of other shapes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Final

from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.evaluation.diagnostic_record import FileDiagnosticRecord

sys.path.insert(0, str(Path(__file__).parent))
from _activation_record import HOSTILE, at, iso, step

#: The activation of model calls, and the one of bodies of other shapes.
CALLS: Final = "calls"
ODD: Final = "odd-calls"

#: Planning's instructions: paragraphs, the first as the hub's opens.
ROLE = (
    "You are the assistant, working for the user one round at a time. Each response you "
    "give is one round."
)
LABELS = "Things are named by label: stories S1, S2 and so on. " + HOSTILE
CALLS_RULE = "Every call of a round runs at the same time."
#: The paragraph round 2's instructions add.
ADDED = "This activation cannot message the user, so a call that needs them will not run."


def _instructions(*paragraphs: str) -> str:
    return "\n\n".join(paragraphs) + "\n\n"


def _messages(system: str, document: object) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system, "name": None},
        {"role": "user", "content": json.dumps(document, ensure_ascii=True), "name": None},
    ]


def _tool(name: str, description: str, **properties: object) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties},
    }


WEB_SEARCH = _tool("web_search", "Search the web.", query={"type": "string"})
EMAIL = _tool("send_email", "Send an email for the user.", to={"type": "string"})
ROUND = _tool("planning_round", "Not a capability: calling it runs nothing and goes to no one.")

#: Understanding's instructions, with a heading of each kind the view reads.
UNDERSTANDING_TOLD = (
    "Read the user's input and say what it means.\n\n"
    "## What to return\n\n"
    "One JSON object, and nothing else.\n\n"
    "RULES:\n\n"
    "Never invent a meaning the input does not carry."
)

#: Round 1's user message: the quoted source data, one JSON object.
ROUND_1_INPUT: Final[dict[str, Any]] = {
    "understood": {"meaning": "find a flight", "input": "find me a flight to Lisbon"},
    "place": {"channel": "chat", "takes_message": True},
    "stories": [
        {"label": "S1", "summary": "Trip to Lisbon", "notes": ["N1", "N2"]},
        {"label": "S2", "summary": "Work", "notes": []},
    ],
    "rounds": [],
}

#: Round 2's: its earlier round now shown, and a key round 1 did not have.
ROUND_2_INPUT: Final[dict[str, Any]] = {
    **ROUND_1_INPUT,
    "rounds": [{"round": 1, "calls": [{"name": "web_search", "outcome": "done"}]}],
    "results": [{"label": "R1", "text": "Three flights found."}],
}

ROUND_1_USAGE: Final = {
    "input_tokens": 12_345,
    "cache_write_tokens": 0,
    "cache_read_tokens": 10_000,
    "output_tokens": 456,
    "input_audio_tokens": 0,
    "cache_audio_read_tokens": 0,
    "output_audio_tokens": 0,
    "details": {},
}


def _part(kind: str, **fields: object) -> dict[str, Any]:
    return {
        **fields,
        "id": None,
        "provider_name": None,
        "provider_details": None,
        "part_kind": kind,
    }


def _response(parts: list[dict[str, Any]], usage: dict[str, Any]) -> dict[str, Any]:
    """A provider's response as pydantic-ai serialises it into planning's returned entry."""
    return {
        "parts": parts,
        "usage": usage,
        "model_name": "claude-test",
        "timestamp": iso(0),
        "kind": "response",
        "provider_name": "anthropic",
        "finish_reason": "tool_call",
    }


def _call(name: str, args: object, call_id: str) -> dict[str, Any]:
    return _part("tool-call", tool_name=name, args=args, tool_call_id=call_id, tool_kind=None)


ROUND_1_RETURNED: Final = {
    "offered_tools": [WEB_SEARCH, EMAIL, ROUND],
    "response": _response(
        [
            _part("thinking", content="The user wants flights.", signature="sig"),
            _part("text", content="I'll look for flights to Lisbon."),
            _call("web_search", {"query": "flights to Lisbon"}, "c1"),
            _call("planning_round", '{"notes": "Looking for flights.", "asks": ["c0"]}', "c2"),
        ],
        ROUND_1_USAGE,
    ),
    "read_as_round": True,
}

ROUND_2_RETURNED: Final = {
    "offered_tools": [WEB_SEARCH, ROUND],
    "response": _response(
        [_part("text", content="I found three flights.")],
        {**ROUND_1_USAGE, "input_tokens": 13_000, "output_tokens": 90},
    ),
    "read_as_round": True,
}

DIGEST_ABOUT: Final = {
    "result": "r1",
    "question": "Which flight is cheapest?",
    "part": 1,
    "parts": 1,
}

DIGEST_GIVEN: Final = {
    **DIGEST_ABOUT,
    "messages": _messages(
        "Answer the question from the records alone.",
        {
            "question": "Which flight is cheapest?",
            "records": [{"label": "L1", "from": "result", "text": "TAP 120 EUR"}],
        },
    ),
}

DIGEST_RETURNED: Final = {
    **DIGEST_ABOUT,
    "reply": '{"evidence": [{"source": "L1", "text": "TAP at 120 EUR"}]}',
    "dropped": [{"source": "L9", "text": "an item naming no record shown"}],
}

type _Written = tuple[DiagnosticSource, DiagnosticKind, int, dict[str, Any]]

_U, _P, _D, _C, _A = (
    DiagnosticSource.UNDERSTANDING,
    DiagnosticSource.PLANNING,
    DiagnosticSource.DIGESTING,
    DiagnosticSource.CONTROLLER,
    DiagnosticSource.AUTHORIZING,
)
_GIVEN, _RETURNED, _STEP = DiagnosticKind.GIVEN, DiagnosticKind.RETURNED, DiagnosticKind.STEP

#: The activation of model calls, line by line: understanding, two rounds and a digest.
CALL_ENTRIES: Final[list[_Written]] = [
    (
        _U,
        _GIVEN,
        10,
        {"messages": _messages(UNDERSTANDING_TOLD, {"input": {"text": "find me a flight"}})},
    ),
    (_U, _RETURNED, 300, {"reply": '{"meaning": "find a flight"}'}),
    (_C, _STEP, 301, step("understanding", "not_understood", 5, 301)),
    (
        _P,
        _GIVEN,
        320,
        {
            "messages": _messages(_instructions(ROLE, LABELS, CALLS_RULE), ROUND_1_INPUT),
            "tools": [WEB_SEARCH, EMAIL],
        },
    ),
    (_P, _RETURNED, 800, ROUND_1_RETURNED),
    (_C, _STEP, 801, step("planning", "first_round_due", 310, 801)),
    (
        _A,
        _RETURNED,
        850,
        {
            "round": "round:1",
            "calls": [{"call_id": "c1", "name": "web_search", "verdict": "allowed"}],
            "read_outside_content": False,
            "grounds": [],
        },
    ),
    (_C, _STEP, 851, step("authorizing", "round_unauthorized", 805, 851)),
    (_D, _GIVEN, 860, DIGEST_GIVEN),
    (_D, _RETURNED, 1100, DIGEST_RETURNED),
    (_C, _STEP, 1101, step("digesting", "recall_undigested", 855, 1101)),
    (
        _P,
        _GIVEN,
        1120,
        {
            "messages": _messages(_instructions(ROLE, LABELS, ADDED, CALLS_RULE), ROUND_2_INPUT),
            "tools": [WEB_SEARCH],
        },
    ),
    (_P, _RETURNED, 1500, ROUND_2_RETURNED),
    (_C, _STEP, 1501, step("planning", "round_due", 1110, 1501)),
    (_C, _STEP, 1600, step("end", "nothing_due", 1600, 1600)),
]

#: The line of each entry the tests name, by its place in :data:`CALL_ENTRIES`.
UNDERSTANDING_GIVEN, UNDERSTANDING_RETURNED = 0, 1
ROUND_1_GIVEN, ROUND_1_RETURNED_LINE = 3, 4
DIGEST_GIVEN_LINE, DIGEST_RETURNED_LINE = 8, 9
ROUND_2_GIVEN, ROUND_2_RETURNED_LINE = 11, 12

#: Bodies of other shapes, each a model source's given or returned entry.
ODD_ENTRIES: Final[list[_Written]] = [
    (_P, _GIVEN, 10, {"messages": "not a list", "tools": "none"}),
    (_P, _RETURNED, 20, {"response": "not a response", "offered_tools": [7, {"name": 3}]}),
    (
        _U,
        _GIVEN,
        30,
        {"messages": [{"role": "system", "content": {"odd": 1}}, {"content": ["x"]}, 5]},
    ),
    (_U, _RETURNED, 40, {"reply": {"not": "text"}}),
    (_D, _GIVEN, 50, {"part": 1, "parts": 1, "messages": []}),
    (_P, _GIVEN, 60, {"messages": [{"role": "user", "content": "{not json"}]}),
    (_P, _RETURNED, 70, {"failure": {"class": "ModelError", "message": "boom"}}),
]

#: Raw lines the store cannot write, appended to the odd activation: an entry whose body
#: is no object, and a line that is not JSON.
ODD_RAW: Final = [
    json.dumps(
        {
            "activation_id": ODD,
            "source": "planning",
            "kind": "given",
            "recorded_at": iso(80),
            "body": "not an object",
        }
    ),
    "this is not json",
]


async def _write(directory: Path, activation_id: str, entries: list[_Written]) -> None:
    store = FileDiagnosticRecord(directory=directory, file_bytes=8 * 1024 * 1024)
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


def write_calls(directory: Path) -> Path:
    """The two activations, written into ``directory`` by ADR-0314's store.

    Args:
        directory: The record's directory; created where it is not yet.

    Returns:
        The directory.
    """
    asyncio.run(_write(directory, CALLS, CALL_ENTRIES))
    asyncio.run(_write(directory, ODD, ODD_ENTRIES))
    with (directory / f"{ODD}.jsonl").open("a", encoding="utf-8") as handle:
        for raw in ODD_RAW:
            handle.write(raw + "\n")
    return directory

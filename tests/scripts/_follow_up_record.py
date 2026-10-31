"""A record the hub's follow-up asker followed up, for the viewer's tests (ADR-0337 §8:17).

Written as the composition root wires it: every entry goes through the package's own
:class:`~ai_assistant.models.follow_up.FollowUpAsker` around ADR-0314's own store, and the
asker asks each recorded call of a fake model and writes the answer into the activation's
follow-up file itself. So a change to the line either side reads fails the viewer's tests.

Activation A holds an understanding call, a planning round and a digest part written
before ADR-0334's ``prompt`` key, so not asked; the observer's scout call is written under
A and B (ADR-0333 §2:9), asked once and followed up under each; activation F's planning
round is asked a follow-up that fails.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.evaluation.diagnostic_record import FOLLOW_UP_SUFFIX, FileDiagnosticRecord
from ai_assistant.models.follow_up import FOLLOW_UP_PROMPT, FOLLOW_UP_ROUTES, FollowUpAsker
from ai_assistant.testing import default_prompt

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.messages import ModelMessage

ACT_A: Final = "act-a"
ACT_B: Final = "act-b"
ACT_F: Final = "act-f"

#: What the fake model answers every follow-up with.
ANSWER: Final = "I had to guess which day you meant, and the rules on dates disagreed."

#: The model planning's response names, and every route's spec: a follow-up goes to it.
MODEL_NAME: Final = "claude-hub"
ROUTE: Final = "fake:" + MODEL_NAME

#: A user message marking the call whose follow-up fails.
FAILING: Final = "this follow-up fails"

T0: Final = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def at(ms: int) -> datetime:
    return T0 + timedelta(milliseconds=ms)


def _prompt(name: str) -> dict[str, Any]:
    return {"name": name, "version": "0123456789ab", "origin": "default", "flags": {}}


def _messages(system: str, user: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system, "name": None},
        {"role": "user", "content": user, "name": None},
    ]


def _round(activation_id: str, user: str, ms: int) -> list[DiagnosticEntry]:
    response = {
        "parts": [{"part_kind": "text", "content": "Looking it up."}],
        "model_name": MODEL_NAME,
        "kind": "response",
    }
    return [
        _entry(
            activation_id,
            DiagnosticSource.PLANNING,
            DiagnosticKind.GIVEN,
            ms,
            {
                # ADR-0356 §13:6: planning's given entry records the exchange, beside the
                # same request as its two messages.
                "exchange": {
                    "instruction": "Planning's instruction.",
                    "briefing": user,
                    "steps": [],
                },
                "messages": _messages("Planning's instruction.", user),
                "tools": [],
                "prompt": _prompt("planning"),
            },
        ),
        _entry(
            activation_id,
            DiagnosticSource.PLANNING,
            DiagnosticKind.RETURNED,
            ms + 10,
            {"response": response, "read_as_round": True},
        ),
    ]


def _entry(
    activation_id: str,
    source: DiagnosticSource,
    kind: DiagnosticKind,
    ms: int,
    body: dict[str, Any],
) -> DiagnosticEntry:
    return DiagnosticEntry(
        activation_id=activation_id, source=source, kind=kind, recorded_at=at(ms), body=body
    )


def _scout(activation_id: str, kind: DiagnosticKind, ms: int) -> DiagnosticEntry:
    named = {"episode": f"ep-{activation_id}", "attempt_started_at": at(0).isoformat()}
    body: dict[str, Any] = (
        {
            "stage": "scout",
            "messages": _messages("The scout's instruction.", json.dumps({"episodes": []})),
            "prompt": _prompt("observer_scout"),
        }
        if kind is DiagnosticKind.GIVEN
        else {"stage": "scout", "reply": '{"findings": []}'}
    )
    return _entry(activation_id, DiagnosticSource.OBSERVER, kind, ms, {**named, **body})


#: Every entry, in the order its emitter writes it.
ENTRIES: Final = (
    _entry(
        ACT_A,
        DiagnosticSource.UNDERSTANDING,
        DiagnosticKind.GIVEN,
        10,
        {
            "messages": _messages("Understanding's instruction.", "what is on tomorrow"),
            "prompt": _prompt("understanding"),
        },
    ),
    _entry(
        ACT_A,
        DiagnosticSource.UNDERSTANDING,
        DiagnosticKind.RETURNED,
        20,
        {"reply": '{"meaning": "what is on tomorrow"}'},
    ),
    *_round(ACT_A, "what is on tomorrow", 30),
    _entry(
        ACT_A,
        DiagnosticSource.DIGESTING,
        DiagnosticKind.GIVEN,
        50,
        {
            "result": "r1",
            "question": "what was found",
            "part": 1,
            "parts": 1,
            "messages": _messages("The digest's instruction.", "{}"),
        },
    ),
    _entry(
        ACT_A,
        DiagnosticSource.DIGESTING,
        DiagnosticKind.RETURNED,
        60,
        {"result": "r1", "question": "what was found", "part": 1, "parts": 1, "reply": "{}"},
    ),
    _scout(ACT_A, DiagnosticKind.GIVEN, 100),
    _scout(ACT_B, DiagnosticKind.GIVEN, 101),
    _scout(ACT_A, DiagnosticKind.RETURNED, 110),
    _scout(ACT_B, DiagnosticKind.RETURNED, 110),
    *_round(ACT_F, FAILING, 30),
)

#: The lines of activation A's own file, and of its observer file.
UNDERSTANDING_GIVEN, UNDERSTANDING_RETURNED, PLANNING_GIVEN, PLANNING_RETURNED = 0, 1, 2, 3
DIGEST_GIVEN, SCOUT_GIVEN = 4, 0

#: How many follow-up entries each activation's follow-up file ends with.
FOLLOWED: Final = {ACT_A: 3, ACT_B: 1, ACT_F: 1}


def _answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del info
    said = [
        part.content
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    if FAILING in said:
        raise ModelHTTPError(status_code=429, model_name=MODEL_NAME)
    return ModelResponse(parts=[TextPart(ANSWER)])


async def _write(directory: Path) -> None:
    store = FileDiagnosticRecord(directory=directory, file_bytes=8 * 1024 * 1024)
    model = FunctionModel(_answer, model_name=MODEL_NAME)
    asker = FollowUpAsker(
        store,
        prompt=default_prompt(FOLLOW_UP_PROMPT),
        routes=dict.fromkeys(FOLLOW_UP_ROUTES, ROUTE),
        daily_calls=100,
        timeout=10.0,
        now=lambda: at(5_000),
        build=lambda _spec: model,
    )
    for entry in ENTRIES:
        await asker.write(entry)
    async with asyncio.timeout(10):
        while not all(  # noqa: ASYNC110 — the asker exposes no signal, by design
            _count(directory / f"{activation_id}{FOLLOW_UP_SUFFIX}") == count
            for activation_id, count in FOLLOWED.items()
        ):
            await asyncio.sleep(0.01)
    await asker.aclose()


def _count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def write_followed(tmp_path: Path) -> Path:
    """The record's directory, under a data directory, its calls followed up.

    Returns:
        ``<tmp_path>/data/diagnostics``.
    """
    directory = tmp_path / "data" / "diagnostics"
    directory.parent.mkdir()
    asyncio.run(_write(directory))
    return directory

"""A live data directory and a fake model, for ``scripts/prompt_replay.py``'s tests (ADR-0335).

The record is written with ADR-0314's own store, as the viewer's tests write theirs, so a
change to the line the tool reads fails here. Its bodies are shaped as the sources write
them: understanding's and digesting's requests as a system message and a user message,
planning's with its tools and its returned entry with the provider's whole response, and
the observer's scout call written under two activations with the same request (ADR-0333
§2:9). One understanding entry predates ADR-0334's ``prompt`` key. Every body carries
:data:`PRIVATE`, which nothing the tool prints may hold (§5:3).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ai_assistant.core.types import DiagnosticEntry, DiagnosticKind, DiagnosticSource
from ai_assistant.evaluation.diagnostic_record import FileDiagnosticRecord

sys.path.insert(0, str(Path(__file__).parent))
from _operator_recipes import load

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

replay_tool = load("prompt_replay")

#: Text the record holds that nothing the tool prints may carry (ADR-0335 §5:3).
PRIVATE: Final = "private-words-the-tool-must-never-print"

#: The activations: one of every model call, one written before ADR-0334's key.
ACT_A: Final = "act-a"
ACT_B: Final = "act-b"

#: Each prompt's recorded instruction.
UNDERSTANDING_TOLD: Final = "Recorded understanding instruction. " + PRIVATE
PLANNING_TOLD: Final = "Recorded planning instruction. " + PRIVATE
DIGEST_TOLD: Final = "Recorded digest instruction. " + PRIVATE
SCOUT_TOLD: Final = "Recorded scout instruction. " + PRIVATE

#: The user messages each call was given.
UNDERSTANDING_INPUT: Final = json.dumps({"input": {"text": "find a flight " + PRIVATE}})
PLANNING_INPUT: Final = json.dumps({"understood": {"meaning": "find a flight " + PRIVATE}})
OLD_INPUT: Final = json.dumps({"input": {"text": "an older input " + PRIVATE}})

#: The model planning's returned entry names.
ORIGINAL_MODEL: Final = "claude-original"

#: Planning's offered tool, as its given entry records it.
WEB_SEARCH: Final = {
    "name": "web_search",
    "description": "Search the web.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
}

T0: Final = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


def at(ms: int) -> datetime:
    return T0 + timedelta(milliseconds=ms)


def _messages(system: str, user: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": system, "name": None},
        {"role": "user", "content": user, "name": None},
    ]


def _prompt(name: str, flags: dict[str, bool] | None = None) -> dict[str, Any]:
    held: dict[str, Any] = {"name": name, "version": "0123456789ab", "origin": "default"}
    if flags is not None:
        held["flags"] = flags
    return held


#: Activation A: understanding, a planning round, a digest part, in its own file.
ACT_A_ENTRIES: Final = (
    (
        DiagnosticSource.UNDERSTANDING,
        DiagnosticKind.GIVEN,
        10,
        {
            "messages": _messages(UNDERSTANDING_TOLD, UNDERSTANDING_INPUT),
            "prompt": _prompt("understanding"),
        },
    ),
    (DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED, 20, {"reply": "{} " + PRIVATE}),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.GIVEN,
        30,
        {
            "messages": _messages(PLANNING_TOLD, PLANNING_INPUT),
            "tools": [WEB_SEARCH],
            "prompt": _prompt("planning"),
        },
    ),
    (
        DiagnosticSource.PLANNING,
        DiagnosticKind.RETURNED,
        40,
        {
            "response": {
                "parts": [{"part_kind": "text", "content": "done " + PRIVATE}],
                "model_name": ORIGINAL_MODEL,
                "kind": "response",
            },
            "read_as_round": True,
        },
    ),
    (
        DiagnosticSource.DIGESTING,
        DiagnosticKind.GIVEN,
        50,
        {
            "result": "r1",
            "question": "what was found",
            "part": 1,
            "parts": 1,
            "messages": _messages(DIGEST_TOLD, json.dumps({"records": [PRIVATE]})),
        },
    ),
    (DiagnosticSource.DIGESTING, DiagnosticKind.RETURNED, 60, {"reply": "{} " + PRIVATE}),
)

#: Activation B: an understanding call written before ADR-0334's ``prompt`` key.
ACT_B_ENTRIES: Final = (
    (
        DiagnosticSource.UNDERSTANDING,
        DiagnosticKind.GIVEN,
        10,
        {"messages": _messages(UNDERSTANDING_TOLD, OLD_INPUT)},
    ),
    (DiagnosticSource.UNDERSTANDING, DiagnosticKind.RETURNED, 20, {"reply": "{} " + PRIVATE}),
)

#: The scout's request, the same under both activations it read for (ADR-0333 §2:9).
SCOUT_MESSAGES: Final = _messages(SCOUT_TOLD, json.dumps({"episodes": [PRIVATE]}))


def _scout(episode: str) -> dict[str, Any]:
    return {
        "episode": episode,
        "attempt_started_at": at(0).isoformat(),
        "stage": "scout",
        "messages": SCOUT_MESSAGES,
    }


async def _write(directory: Path, activation_id: str, entries: Any) -> None:
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


def write_live(tmp_path: Path) -> Path:
    """A live data directory: a record, two databases, an override, the lock.

    Returns:
        The data directory.
    """
    live = tmp_path / "live"
    live.mkdir()
    record = live / "diagnostics"
    asyncio.run(_write(record, ACT_A, ACT_A_ENTRIES))
    asyncio.run(_write(record, ACT_B, ACT_B_ENTRIES))
    for activation_id, episode in ((ACT_A, "ep-a"), (ACT_B, "ep-b")):
        asyncio.run(
            _write(
                record,
                activation_id,
                (
                    (DiagnosticSource.OBSERVER, DiagnosticKind.GIVEN, 100, _scout(episode)),
                    (
                        DiagnosticSource.OBSERVER,
                        DiagnosticKind.RETURNED,
                        110,
                        {"stage": "scout", "reply": PRIVATE},
                    ),
                ),
            )
        )
    database = sqlite3.connect(live / "memory.db")
    database.execute("create table memories (text)")
    database.execute("insert into memories values (?)", (PRIVATE,))
    database.commit()
    database.close()
    (live / "prompts").mkdir(mode=0o700)
    (live / "prompts" / "planning.txt").write_text("An override, no final line break")
    (live / "hub.lock").write_text("123\n")
    return live


def live_snapshot(live: Path) -> dict[str, tuple[int, int, bytes]]:
    """Every file under ``live``: its mode, its modification time and its bytes."""
    shown: dict[str, tuple[int, int, bytes]] = {}
    for path in sorted(live.rglob("*")):
        status = path.lstat()
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
        shown[str(path.relative_to(live))] = (status.st_mode, status.st_mtime_ns, data)
    return shown


def make_copy(tmp_path: Path, *, retention: timedelta = timedelta(days=30)) -> Path:
    """A copy of :func:`write_live`'s data directory, made by the tool."""
    copy = tmp_path / "copy"
    replay_tool.copy_data_dir(write_live(tmp_path), copy, retention=retention, now=_now)
    return copy


def _now() -> datetime:
    return datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


now = _now


def lines(path: Path) -> list[dict[str, Any]]:
    """A results file's lines."""
    return [json.loads(one) for one in path.read_text().splitlines()]


@dataclass
class Model:
    """A fake model: what each request's system message and messages were, and its reply."""

    reply: str = "a replayed reply " + PRIVATE
    fail: Exception | None = None
    systems: list[str] = field(default_factory=list)
    users: list[str] = field(default_factory=list)
    tools: list[list[str]] = field(default_factory=list)
    during: list[Any] = field(default_factory=list)
    requests: list[list[ModelMessage]] = field(default_factory=list)

    def answer(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for hook in self.during:
            hook()
        self.requests.append(list(messages))
        self.tools.append([one.name for one in info.function_tools])
        for message in messages:
            if isinstance(message, ModelRequest):
                for part in message.parts:
                    if isinstance(part, SystemPromptPart):
                        self.systems.append(part.content)
                    elif isinstance(part, UserPromptPart) and isinstance(part.content, str):
                        self.users.append(part.content)
        if self.fail is not None:
            raise self.fail
        return ModelResponse(parts=[TextPart(self.reply)], model_name="fake-model")

    def caller(self) -> Any:
        return replay_tool.ModelCaller(FunctionModel(self.answer), timeout=10)

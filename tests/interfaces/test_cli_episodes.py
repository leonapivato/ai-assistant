"""CLI episode inspection preserves exact records and discards incomplete reads."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import StaleEpisodeReadError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    EpisodeChunk,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    MemorySource,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    UnderstandingOmission,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine

_AT = datetime(2026, 9, 20, tzinfo=UTC)
_CHANNEL = ChannelIdentity(channel_type="informational_event", instance_id="source")
_CONTENT = ":smile: " + 'exact private material café 🍵\\" '


def _record(record_id: str, *, response: EpisodeResponseKind | None = None) -> EpisodicMemory:
    return EpisodicMemory(
        id=record_id,
        content=_CONTENT * 100,
        outcome=None if response in (None, EpisodeResponseKind.NONE) else "Recorded response",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        processing_record=(
            None
            if response is None
            else EpisodeProcessingRecord(
                activation_id="activation",
                started_at=_AT,
                ended_at=_AT,
                trigger=RecordedChannelTrigger(
                    target=_CHANNEL,
                    channel=_CHANNEL,
                    payload=RecordedTextInput(text=" exact input "),
                    context=ChannelContext(),
                    conversation=None,
                    reply=None,
                ),
                status=ProcessingStatus.COMPLETED,
                reason=ProcessingReason.RETURNED,
                response_kind=response,
                model_eligible=False,
                understanding_omitted=UnderstandingOmission.NOT_REACHED,
            )
        ),
    )


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Capture only the CLI renderer, with a narrow width to expose JSON wrapping."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=40))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: AssistantEngine) -> None:
    async def opened() -> AssistantEngine:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", opened)


def _engine(*records: EpisodicMemory) -> FakeAssistantEngine:
    engine = FakeAssistantEngine(max_payload_bytes=1024)
    engine.episode_memory = FakeMemoryStore(now=lambda: _AT)
    for record in records:
        asyncio.run(engine.episode_memory.add(record))
    return engine


@pytest.mark.parametrize("record_id", ["", " a ", "é", ":smile:"])
def test_json_detail_reassembles_exact_stored_record_without_wrapping(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, record_id: str
) -> None:
    engine = _engine(_record(record_id, response=EpisodeResponseKind.INFORMATIONAL_SUMMARY))
    _wire(monkeypatch, engine)
    result = CliRunner().invoke(cli.app, ["episode", record_id, "--json"])
    assert result.exit_code == 0, result.exception
    rendered = output.getvalue().removesuffix("\n")
    first = asyncio.run(engine.episode_memory.episode_chunk(record_id))
    assert first is not None
    assert rendered == first.text
    assert hashlib.sha256(rendered.encode()).hexdigest() == first.version
    assert json.loads(rendered)["id"] == record_id
    calls = [args for method, args in engine.calls if method == "episode_chunk"]
    assert len(calls) > 1
    assert all(args["episode_id"] == record_id for args in calls)


@pytest.mark.parametrize(
    ("response", "label"),
    [
        (None, "unavailable"),
        (EpisodeResponseKind.NONE, "no response"),
        (EpisodeResponseKind.CONVERSATION_REPLY, "conversational reply"),
        (EpisodeResponseKind.INFORMATIONAL_SUMMARY, "informational summary"),
    ],
)
def test_human_detail_names_response_role_and_limits_of_processing_status(
    monkeypatch: pytest.MonkeyPatch,
    output: StringIO,
    response: EpisodeResponseKind | None,
    label: str,
) -> None:
    _wire(monkeypatch, _engine(_record(":smile:", response=response)))
    result = CliRunner().invoke(cli.app, ["episode", ":smile:"])
    assert result.exit_code == 0, result.exception
    rendered = " ".join(output.getvalue().split())
    assert 'Episode ":smile:"' in rendered
    assert f"Response: {label}" in rendered
    assert "does not report goal achievement or audio playback" in rendered
    assert "Retention expiry" in rendered
    assert "explicit forgetting" in rendered


def test_listing_relays_filters_and_displays_exact_id_and_next_cursor(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(
        *(_record(f" row-{n}:smile: ", response=EpisodeResponseKind.NONE) for n in range(10))
    )
    _wire(monkeypatch, engine)
    result = CliRunner().invoke(
        cli.app,
        [
            "episodes",
            "--channel-type",
            "informational_event",
            "--channel-instance",
            "source",
            "--status",
            "completed",
            "--limit",
            "5",
        ],
    )
    assert result.exit_code == 0, result.exception
    assert engine.calls[-1] == (
        "episodes",
        {"channel": _CHANNEL, "status": ProcessingStatus.COMPLETED, "cursor": None, "limit": 5},
    )
    assert 'Episode " row-9:smile: "' in output.getvalue()
    assert "Next cursor:" in output.getvalue()
    assert "exact private material" not in output.getvalue()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--limit", "0"],
        ["--limit", "101"],
        ["--channel-type", "conversation"],
        ["--channel-instance", "source"],
        ["--cursor", "bad"],
        ["--status", "achieved"],
    ],
)
def test_invalid_listing_options_never_open_engine(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    opened = False

    async def forbidden() -> AssistantEngine:
        nonlocal opened
        opened = True
        return FakeAssistantEngine()

    monkeypatch.setattr(cli, "_open_engine", forbidden)
    result = CliRunner().invoke(cli.app, ["episodes", *arguments])
    assert result.exit_code == 2
    assert not opened


class _BrokenDetail(FakeAssistantEngine):
    def __init__(self, failure: str) -> None:
        super().__init__(max_payload_bytes=1024)
        self.failure = failure
        self.read_count = 0

    async def episode_chunk(
        self,
        episode_id: str,
        *,
        version: str | None = None,
        offset: int = 0,
        max_bytes: int = 65536,
    ) -> EpisodeChunk | None:
        self.read_count += 1
        if self.read_count == 2:
            if self.failure == "stale":
                raise StaleEpisodeReadError
            if self.failure == "missing":
                return None
        chunk = await super().episode_chunk(
            episode_id, version=version, offset=offset, max_bytes=max_bytes
        )
        assert chunk is not None
        if self.failure == "digest":
            return chunk.model_copy(update={"text": "x" + chunk.text[1:]})
        if self.failure == "schema":
            text = '{"id":"record","content":"exact private material"}'
            return EpisodeChunk(
                episode_id=episode_id,
                version=hashlib.sha256(text.encode()).hexdigest(),
                offset=0,
                text=text,
                next_offset=None,
                total_bytes=len(text),
            )
        return chunk


@pytest.mark.parametrize("failure", ["stale", "missing", "digest", "schema"])
@pytest.mark.parametrize("as_json", [False, True])
def test_failed_reassembly_never_prints_partial_content(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, failure: str, as_json: bool
) -> None:
    engine = _BrokenDetail(failure)
    engine.episode_memory = FakeMemoryStore(now=lambda: _AT)
    asyncio.run(engine.episode_memory.add(_record("record")))
    _wire(monkeypatch, engine)
    result = CliRunner().invoke(cli.app, ["episode", "record", *(["--json"] if as_json else [])])
    assert result.exit_code != 0
    assert "exact private material" not in output.getvalue()
    assert output.getvalue()

"""CLI episode inspection preserves exact records and discards incomplete reads."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from typing import TYPE_CHECKING, get_args

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import StaleEpisodeReadError
from ai_assistant.core.types import (
    ActivationUnderstanding,
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
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    UnderstandingReference,
    UnderstandingReferent,
    UnderstandingRelationship,
    UnresolvedMatter,
)
from ai_assistant.interfaces import cli, episode_inspection
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine

_AT = datetime(2026, 9, 20, tzinfo=UTC)
_CHANNEL = ChannelIdentity(channel_type="informational_event", instance_id="source")
_CONTENT = ":smile: " + 'exact private material café 🍵\\" '


def _record(
    record_id: str,
    *,
    response: EpisodeResponseKind | None = None,
    understanding: tuple[ActivationUnderstanding, ...] = (),
    omitted: UnderstandingOmission | None = UnderstandingOmission.NOT_REACHED,
    elided: int = 0,
) -> EpisodicMemory:
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
                understanding=understanding,
                understanding_omitted=None if understanding else omitted,
                understanding_elided=elided,
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


# --- the retained understanding (ADR-0276 §7) ---------------------------------

#: Referent fields ADR-0276 §7 leaves to ``--json``: each is distinctive, so its
#: absence from the human section is a check rather than a coincidence.
_REFERENT_ID = "referent-id-f00d"
_REFERENT_SOURCE = "referent-source-beef"
_REFERENT_EXCERPT = "referent-excerpt-cafe"


def _referent(kind: str) -> UnderstandingReferent:
    return UnderstandingReferent.model_validate(
        {
            "kind": kind,
            "id": None if kind == "input" else f"{_REFERENT_ID}-{kind}",
            "source": None if kind == "input" else f"{_REFERENT_SOURCE}-{kind}",
            "excerpt": f"{_REFERENT_EXCERPT}-{kind}",
        }
    )


def _version(
    number: int,
    *,
    meaning_ground: UnderstandingGround = UnderstandingGround.STATED,
    **fields: object,
) -> ActivationUnderstanding:
    """One recorded version; a ``supplied`` meaning names a channel item, as its type requires."""
    return ActivationUnderstanding.model_validate(
        {
            "version": number,
            "recorded_at": _AT,
            "producer": UnderstandingProducer.INTERPRETATION,
            "meaning": "compare the two quotes",
            "meaning_ground": meaning_ground,
            "meaning_referents": (
                (_referent("channel_item"),)
                if meaning_ground is UnderstandingGround.SUPPLIED
                else ()
            ),
            **fields,
        }
    )


def _understanding_section(record: EpisodicMemory) -> list[str]:
    """The human detail's understanding lines, between its fixed neighbours."""
    buffer = StringIO()
    episode_inspection.render_detail(Console(file=buffer, force_terminal=False, width=200), record)
    lines = buffer.getvalue().splitlines()
    start = lines.index("Processing status does not report goal achievement or audio playback.")
    end = next(n for n, line in enumerate(lines) if line.startswith("Retention expiry"))
    return lines[start + 1 : end]


#: Every member of each closed enum, spelled out so that a member added to the enum
#: fails the coverage tests below until its rendering is looked at (ADR-0276 §2).
_OMISSIONS = ("routed", "no_text", "no_input", "failed", "not_reached")
_GROUNDS = ("stated", "supplied", "inferred")
_REFERENT_KINDS = ("input", "channel_item", "episode")


def test_rendering_tables_cover_every_member_of_each_closed_enum() -> None:
    assert {member.value for member in UnderstandingOmission} == set(_OMISSIONS)
    assert {member.value for member in UnderstandingGround} == set(_GROUNDS)
    assert {member.value for member in UnderstandingProducer} == {"interpretation"}
    kind = UnderstandingReferent.model_fields["kind"].annotation
    assert set(get_args(kind)) == set(_REFERENT_KINDS)


def test_json_detail_carries_every_retained_version_complete(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    versions = (
        _version(
            1,
            references=(UnderstandingReference(phrase="it", referents=(_referent("episode"),)),),
            unresolved=(UnresolvedMatter(matter="which quote", why_it_matters="two exist"),),
        ),
        _version(
            4,
            meaning_ground=UnderstandingGround.SUPPLIED,
            relationships=(
                UnderstandingRelationship(
                    statement="the second supersedes the first",
                    referents=(_referent("channel_item"), _referent("input")),
                    ground=UnderstandingGround.SUPPLIED,
                ),
            ),
        ),
    )
    record = _record("record", response=EpisodeResponseKind.NONE, understanding=versions, elided=2)
    engine = _engine(record)
    _wire(monkeypatch, engine)
    result = CliRunner().invoke(cli.app, ["episode", "record", "--json"])
    assert result.exit_code == 0, result.exception
    rendered = output.getvalue().removesuffix("\n")
    first = asyncio.run(engine.episode_memory.episode_chunk("record"))
    assert first is not None
    assert rendered == first.text
    assert EpisodicMemory.model_validate_json(rendered).processing_record == (
        record.processing_record
    )
    processing = json.loads(rendered)["processing_record"]
    assert processing["understanding"] == [v.model_dump(mode="json") for v in versions]
    assert processing["understanding_elided"] == 2
    assert processing["understanding_omitted"] is None


@pytest.mark.parametrize("omission", _OMISSIONS)
def test_human_detail_names_every_omission_value(omission: str) -> None:
    record = _record(
        "record",
        response=EpisodeResponseKind.NONE,
        omitted=UnderstandingOmission(omission),
    )
    assert _understanding_section(record) == [f"Understanding: not recorded ({omission})"]


def test_human_detail_without_processing_record_labels_understanding_unavailable() -> None:
    assert _understanding_section(_record("record")) == ["Understanding: unavailable"]


@pytest.mark.parametrize("ground", _GROUNDS)
def test_human_detail_names_every_ground_of_meaning_and_relationship(ground: str) -> None:
    value = UnderstandingGround(ground)
    version = _version(
        1,
        meaning_ground=value,
        relationships=(
            UnderstandingRelationship(
                statement="follows the earlier request",
                referents=(_referent("episode"),),
                ground=value,
            ),
        ),
    )
    section = _understanding_section(
        _record("record", response=EpisodeResponseKind.NONE, understanding=(version,))
    )
    assert section == [
        "Understanding v1 (interpretation)",
        f'  Meaning ({ground}): "compare the two quotes"',
        f'  Relationship ({ground}): "follows the earlier request"',
    ]


def test_human_detail_names_the_elided_count_before_the_retained_versions() -> None:
    record = _record(
        "record",
        response=EpisodeResponseKind.NONE,
        understanding=(_version(1), _version(9, meaning="the latest reading")),
        elided=7,
    )
    assert _understanding_section(record) == [
        "Understanding versions elided: 7",
        "Understanding v1 (interpretation)",
        '  Meaning (stated): "compare the two quotes"',
        "Understanding v9 (interpretation)",
        '  Meaning (stated): "the latest reading"',
    ]


def test_human_detail_renders_every_field_of_a_full_version_and_no_referent_detail() -> None:
    version = _version(
        3,
        meaning="compare [bold]both[/bold] :smile: quotes\nUnderstanding v9 (forged)",
        meaning_ground=UnderstandingGround.INFERRED,
        references=(
            UnderstandingReference(
                phrase="those two",
                referents=tuple(_referent(kind) for kind in _REFERENT_KINDS),
            ),
            UnderstandingReference(
                phrase="the earlier one", referents=(_referent("episode"), _referent("episode"))
            ),
            UnderstandingReference(phrase="that", referents=()),
        ),
        relationships=tuple(
            UnderstandingRelationship(
                statement=f"relationship {ground}",
                referents=(_referent("channel_item"),),
                ground=UnderstandingGround(ground),
            )
            for ground in _GROUNDS
        ),
        unresolved=(
            UnresolvedMatter(matter="which currency", why_it_matters="the totals differ"),
            UnresolvedMatter(matter="café 🍵 deadline", why_it_matters="nothing says"),
        ),
    )
    section = _understanding_section(
        _record("record", response=EpisodeResponseKind.NONE, understanding=(version,))
    )
    assert section == [
        "Understanding v3 (interpretation)",
        '  Meaning (inferred): "compare [bold]both[/bold] :smile: quotes\\n'
        'Understanding v9 (forged)"',
        '  Reference "those two"; referent kinds: input, channel_item, episode',
        '  Reference "the earlier one"; referent kinds: episode, episode',
        '  Reference "that"; referent kinds: none',
        '  Relationship (stated): "relationship stated"',
        '  Relationship (supplied): "relationship supplied"',
        '  Relationship (inferred): "relationship inferred"',
        '  Unresolved: "which currency"',
        '    Why it matters: "the totals differ"',
        '  Unresolved: "café 🍵 deadline"',
        '    Why it matters: "nothing says"',
    ]
    joined = "\n".join(section)
    for withheld in (_REFERENT_ID, _REFERENT_SOURCE, _REFERENT_EXCERPT):
        assert withheld not in joined


def test_cli_human_detail_carries_the_understanding_section(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    record = _record(
        "record", response=EpisodeResponseKind.CONVERSATION_REPLY, understanding=(_version(1),)
    )
    _wire(monkeypatch, _engine(record))
    result = CliRunner().invoke(cli.app, ["episode", "record"])
    assert result.exit_code == 0, result.exception
    rendered = " ".join(output.getvalue().split())
    assert (
        "audio playback. Understanding v1 (interpretation) "
        'Meaning (stated): "compare the two quotes" Retention expiry'
    ) in rendered

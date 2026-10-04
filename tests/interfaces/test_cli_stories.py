"""The owner's story commands and the episode detail's stories line (ADR-0289 §5).

Driven through the CLI over the canonical fake engine, whose nine story methods run
the engine's own logic over a real fake story store, so what is asserted here is
what the CLI renders of answers the hub would give.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StoryActor,
    StoryChange,
    StoryLogPage,
    StoryMember,
    StoryMemberKind,
    StoryRefusal,
    StoryRefusalReason,
    StoryView,
    UnderstandingOmission,
)
from ai_assistant.interfaces import cli, episode_inspection, story_inspection
from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore
from ai_assistant.testing.activation import ended_pass
from ai_assistant.wire.errors import ProtocolError

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import Identifier

_AT = datetime(2026, 10, 4, tzinfo=UTC)
_CHANNEL = ChannelIdentity(channel_type="informational_event", instance_id="source")
_FROZEN = "11111111-1111-4111-8111-111111111111"
_OPEN = "22222222-2222-4222-8222-222222222222"


def _episode(activation_id: str, *, open_: bool = False) -> EpisodicMemory:
    """The episode at ``activation:<activation_id>``, frozen or still open (ADR-0286)."""
    trigger = RecordedChannelTrigger(
        target=_CHANNEL,
        channel=_CHANNEL,
        payload=RecordedTextInput(text="input"),
        context=ChannelContext(),
        reply=None,
        origin=InputOrigin.OUTSIDE,
    )
    if open_:
        processing = EpisodeProcessingRecord(
            activation_id=activation_id, started_at=_AT, trigger=trigger
        )
        assert processing.is_open
        return EpisodicMemory(
            id=f"activation:{activation_id}",
            content="",
            occurred_at=_AT,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
            placement=Placement(
                reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT
            ),
            processing_record=processing,
        )
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="what happened",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id=activation_id,
            started_at=_AT,
            ended_at=_AT,
            trigger=trigger,
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(_AT),
        ),
    )


def _bare_episode(record_id: str) -> EpisodicMemory:
    """An episode with no processing record, so no activation a story could hold."""
    return EpisodicMemory(
        id=record_id,
        content="captured",
        occurred_at=_AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
    )


def _engine(*records: EpisodicMemory, max_payload_bytes: int = 65536) -> FakeAssistantEngine:
    engine = FakeAssistantEngine(max_payload_bytes=max_payload_bytes)
    engine.episode_memory = FakeMemoryStore(now=lambda: _AT)
    for record in records:
        asyncio.run(engine.episode_memory.add(record))
    return engine


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Capture the CLI's console, wide enough that no line is wrapped."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: AssistantEngine) -> None:
    async def opened() -> AssistantEngine:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", opened)


def _forbid_engine(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    opened: list[bool] = []

    async def forbidden() -> AssistantEngine:
        opened.append(True)
        return FakeAssistantEngine()

    monkeypatch.setattr(cli, "_open_engine", forbidden)
    return opened


def _activation(activation_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def _story(story_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.STORY, id=story_id)


def _create(engine: FakeAssistantEngine, *members: StoryMember) -> Identifier:
    outcome = asyncio.run(engine.create_story(members))
    assert outcome.story_id is not None, outcome
    return outcome.story_id


def _invoke(*arguments: str) -> tuple[int, str]:
    result = CliRunner().invoke(cli.app, list(arguments))
    return result.exit_code, result.output


# --- the group ------------------------------------------------------------------


def test_the_group_says_it_is_for_testing_and_lists_its_seven_commands() -> None:
    """§5:1: create, link, unlink, merge, split, list and show; the help says testing."""
    group = next(group for group in cli.app.registered_groups if group.name == "story")
    assert group.typer_instance is not None
    names = {command.name for command in group.typer_instance.registered_commands}
    assert names == {"create", "link", "unlink", "merge", "split", "list", "show"}
    code, text = _invoke("story", "--help")
    assert code == 0
    assert "For testing" in " ".join(text.split())


# --- writes -----------------------------------------------------------------------


def test_create_names_each_member_with_the_kind_its_option_states(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§2: the kind is carried with the id, and the CLI never reads it off the id."""
    engine = _engine(_episode(_FROZEN))
    inner = _create(engine, _activation(_FROZEN))
    _wire(monkeypatch, engine)
    code, _ = _invoke("story", "create", "--story", inner, "-a", f" {_FROZEN} ")
    assert code == 0, output.getvalue()
    method, arguments = engine.calls[-1]
    assert method == "create_story"
    # Activations first, then stories, each in the order given; ids stripped.
    assert arguments["members"] == (_activation(_FROZEN), _story(inner))
    created = asyncio.run(engine.stories()).stories[0].story_id
    assert output.getvalue() == f'Created story "{created}"; 3 change-log lines appended.\n'


def test_a_story_id_given_as_an_activation_is_an_activation(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """A ``story:``-prefixed id named with ``--activation`` is refused as an activation."""
    engine = _engine(_episode(_FROZEN))
    story = _create(engine, _activation(_FROZEN))
    _wire(monkeypatch, engine)
    code, _ = _invoke("story", "create", "--activation", story)
    assert code == 1
    assert output.getvalue() == (
        f'Refused (unknown_activation): activation "{story}" has no episode record.\n'
    )


def test_link_unlink_split_and_merge_reach_the_engine_and_say_what_they_left(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(_episode(_FROZEN), _episode(_OPEN, open_=True))
    first = _create(engine, _activation(_FROZEN))
    second = _create(engine, _activation(_OPEN))
    _wire(monkeypatch, engine)

    assert _invoke("story", "link", first, "-a", _OPEN)[0] == 0
    assert engine.calls[-1] == (
        "link_story",
        {"story_id": first, "members": (_activation(_OPEN),)},
    )
    assert output.getvalue().endswith(f'Linked to story "{first}"; 1 change-log line appended.\n')

    assert _invoke("story", "link", first, "-a", _OPEN)[0] == 0
    assert output.getvalue().endswith(
        f'Linked to story "{first}"; 0 change-log lines appended. '
        "Nothing changed: every member named was passed over.\n"
    )

    assert _invoke("story", "unlink", first, "-a", _OPEN)[0] == 0
    assert engine.calls[-1] == (
        "unlink_story",
        {"story_id": first, "members": (_activation(_OPEN),)},
    )

    assert _invoke("story", "split", second, "-a", _OPEN)[0] == 0
    assert engine.calls[-1] == (
        "split_story",
        {"story_id": second, "members": (_activation(_OPEN),)},
    )
    split_off = asyncio.run(engine.stories()).stories[0].story_id
    assert f'new story "{split_off}"' in output.getvalue()

    assert _invoke("story", "merge", split_off, "--into", first)[0] == 0
    assert engine.calls[-1] == ("merge_stories", {"story_id": split_off, "into": first})
    assert output.getvalue().endswith(
        f'Merged into story "{first}"; 4 change-log lines appended.\n'
    )


def _refusals() -> list[tuple[StoryRefusal, str]]:
    member = _activation("a-1")
    return [
        (StoryRefusal(reason=StoryRefusalReason.NO_MEMBERS), "no member was named"),
        (
            StoryRefusal(reason=StoryRefusalReason.UNKNOWN_STORY, story_id="story:x"),
            'there is no story "story:x"',
        ),
        (
            StoryRefusal(
                reason=StoryRefusalReason.MERGED_STORY, story_id="story:x", merged_into="story:y"
            ),
            'story "story:x" was merged into story "story:y"',
        ),
        (
            StoryRefusal(reason=StoryRefusalReason.SELF_MERGE, story_id="story:x"),
            'story "story:x" cannot be merged into itself',
        ),
        (
            StoryRefusal(
                reason=StoryRefusalReason.LOOP, story_id="story:x", loop=("story:x", "story:y")
            ),
            'story "story:x" would contain itself: "story:x" contains "story:y" contains "story:x"',
        ),
        (
            StoryRefusal(reason=StoryRefusalReason.NOT_A_MEMBER, story_id="story:x", member=member),
            'activation "a-1" is not a member of story "story:x"',
        ),
        (
            StoryRefusal(reason=StoryRefusalReason.UNKNOWN_ACTIVATION, member=member),
            'activation "a-1" has no episode record',
        ),
    ]


def test_every_refusal_reason_has_a_rendering() -> None:
    """Spelled out per reason, so a reason added to the closed enumeration fails here."""
    covered = {refusal.reason for refusal, _ in _refusals()}
    assert covered == set(StoryRefusalReason)


@pytest.mark.parametrize(("refusal", "detail"), _refusals())
def test_a_refusal_names_its_reason_and_what_it_was_refused_over(
    refusal: StoryRefusal, detail: str
) -> None:
    assert story_inspection.refusal_text(refusal) == f"Refused ({refusal.reason.value}): {detail}."


def test_a_refused_write_exits_non_zero_and_names_the_story_merged_into(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(_episode(_FROZEN))
    absorbed = _create(engine, _activation(_FROZEN))
    kept = _create(engine, _story(absorbed))
    _wire(monkeypatch, engine)
    assert _invoke("story", "link", kept, "-s", kept)[0] == 1
    assert output.getvalue().startswith("Refused (loop): ")
    assert _invoke("story", "merge", absorbed, "--into", kept)[0] == 0
    code, _ = _invoke("story", "link", absorbed, "-a", _FROZEN)
    assert code == 1
    assert output.getvalue().endswith(
        f'Refused (merged_story): story "{absorbed}" was merged into story "{kept}".\n'
    )
    assert _invoke("story", "create")[0] == 1
    assert output.getvalue().endswith("Refused (no_members): no member was named.\n")


@pytest.mark.parametrize(
    "arguments",
    [
        ["create", "-a", "  "],
        ["create", "-s", ""],
        ["link", " ", "-a", _FROZEN],
        ["merge", "story:x", "--into", " "],
        ["split", "", "-s", "story:x"],
        ["show", "  "],
        ["list", "--limit", "0"],
        ["list", "--limit", str(MAX_STORY_PAGE + 1)],
        ["list", "--cursor", "-1"],
    ],
)
def test_a_malformed_argument_is_a_usage_error_before_any_engine(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    opened = _forbid_engine(monkeypatch)
    code, _ = _invoke("story", *arguments)
    assert code == 2
    assert not opened


# --- reads --------------------------------------------------------------------------


def test_show_renders_members_then_the_log_oldest_first(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """§5:2: an episode's one-line summary, in progress while open; forgotten; a story's count."""
    forgotten = "33333333-3333-4333-8333-333333333333"
    engine = _engine(_episode(_FROZEN), _episode(_OPEN, open_=True), _episode(forgotten))
    inner = _create(engine, _activation(_FROZEN), _activation(_OPEN))
    story = _create(engine, _activation(_OPEN), _story(inner), _activation(forgotten))
    assert asyncio.run(engine.episode_memory.delete(f"activation:{forgotten}"))
    _wire(monkeypatch, engine)

    code, _ = _invoke("story", "show", story)
    assert code == 0, output.getvalue()
    lines = output.getvalue().splitlines()
    log = asyncio.run(engine.story_log(story))
    assert log is not None
    assert lines == [
        f'Story "{story}"',
        f"Created: {log.story.created_at.isoformat()}",
        "Members: 3",
        f'  Episode "activation:{_OPEN}" | Occurred: {_AT.isoformat()} | Activation: {_OPEN} '
        f"| Channel: informational_event/source; modality: text "
        f"| Processing: {episode_inspection.IN_PROGRESS}",
        f'  Story "{inner}": 2 members',
        f'  Activation "{forgotten}": forgotten',
        "Change log, oldest first:",
        *(
            f"  #{line.sequence} {line.at.isoformat()} owner: created"
            if line.member is None
            else f"  #{line.sequence} {line.at.isoformat()} owner: "
            f'added {line.member.kind.value} "{line.member.id}"'
            for line in log.lines
        ),
    ]
    assert [line.change for line in log.lines] == [
        StoryChange.CREATED,
        StoryChange.ADDED,
        StoryChange.ADDED,
        StoryChange.ADDED,
    ]


def test_an_activation_line_states_what_the_episode_list_states(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """The story view's activation line and the list's row come from one source."""
    engine = _engine(_episode(_FROZEN))
    story = _create(engine, _activation(_FROZEN))
    _wire(monkeypatch, engine)
    assert _invoke("episodes")[0] == 0
    row = output.getvalue().split("\n\n")[0].splitlines()
    output.truncate(0)
    output.seek(0)
    assert _invoke("story", "show", story)[0] == 0
    member = output.getvalue().splitlines()[3]
    assert member == " | ".join(line.strip() for line in row[:5]).replace(
        'Episode "', '  Episode "', 1
    )


def test_a_merged_story_shows_only_the_story_it_went_into(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(_episode(_FROZEN))
    absorbed = _create(engine, _activation(_FROZEN))
    kept = _create(engine, _activation(_FROZEN))
    assert asyncio.run(engine.merge_stories(absorbed, kept)).refusal is None
    _wire(monkeypatch, engine)
    before = len(engine.calls)
    assert _invoke("story", "show", absorbed)[0] == 0
    assert output.getvalue() == f'Story "{absorbed}" was merged into story "{kept}".\n'
    assert [method for method, _ in engine.calls[before:]] == ["story_log"]


def test_show_of_an_unknown_story_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    _wire(monkeypatch, _engine())
    assert _invoke("story", "show", "story:absent")[0] == 1
    assert output.getvalue() == 'No story "story:absent".\n'


def test_show_reads_every_page_of_a_story_too_large_for_one(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """A page the payload limit shortens is followed to the end, members then log."""
    ids = [f"{n:08d}-0000-4000-8000-000000000000" for n in range(12)]
    engine = _engine(*(_episode(activation) for activation in ids), max_payload_bytes=2048)
    story = _create(engine, *(_activation(activation) for activation in ids))
    _wire(monkeypatch, engine)
    assert _invoke("story", "show", story)[0] == 0, output.getvalue()
    story_calls = [arguments for method, arguments in engine.calls if method == "story"]
    log_calls = [arguments for method, arguments in engine.calls if method == "story_log"]
    assert len(story_calls) > 1
    assert len(log_calls) > 1
    rendered = output.getvalue()
    assert all(f"Activation: {activation} " in rendered for activation in ids)
    assert rendered.count(" owner: added activation ") == len(ids)


class _ChangingEngine(FakeAssistantEngine):
    """Answers a continuation page of the view or the log with the story changed."""

    def __init__(self, change: str) -> None:
        super().__init__(max_payload_bytes=2048)
        self.change = change

    async def story(
        self, story_id: Identifier, *, cursor: int | None = None, limit: int = 50
    ) -> StoryView | None:
        view = await super().story(story_id, cursor=cursor, limit=limit)
        if cursor is None or view is None:
            return view
        if self.change == "count":
            return view.model_copy(update={"member_count": view.member_count + 1})
        if self.change == "header":
            merged = view.story.model_copy(update={"merged_into": "story:elsewhere"})
            return view.model_copy(update={"story": merged})
        if self.change == "stalled":
            return view.model_copy(update={"next_cursor": cursor})
        return None if self.change == "gone" else view

    async def story_log(
        self, story_id: Identifier, *, cursor: int | None = None, limit: int = 50
    ) -> StoryLogPage | None:
        page = await super().story_log(story_id, cursor=cursor, limit=limit)
        if cursor is None or page is None or not self.change.startswith("log-"):
            return page
        if self.change == "log-header":
            merged = page.story.model_copy(update={"merged_into": "story:elsewhere"})
            return page.model_copy(update={"story": merged})
        if self.change == "log-stalled":
            return page.model_copy(update={"next_cursor": cursor})
        return None


@pytest.mark.parametrize(
    "change", ["count", "header", "stalled", "gone", "log-header", "log-stalled", "log-gone"]
)
def test_a_story_that_changes_between_pages_is_discarded(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, change: str
) -> None:
    engine = _ChangingEngine(change)
    engine.episode_memory = FakeMemoryStore(now=lambda: _AT)
    ids = [f"{n:08d}-0000-4000-8000-000000000000" for n in range(12)]
    for activation in ids:
        asyncio.run(engine.episode_memory.add(_episode(activation)))
    story = _create(engine, *(_activation(activation) for activation in ids))
    with pytest.raises(ProtocolError):
        asyncio.run(story_inspection.read_story(engine, story))
    _wire(monkeypatch, engine)
    assert _invoke("story", "show", story)[0] == 1
    assert "Activation:" not in output.getvalue()


class _WritingEngine(FakeAssistantEngine):
    """Unlinks a member on the first view read, before or after reading the page."""

    def __init__(self, when: str, member: StoryMember) -> None:
        super().__init__()
        self.when = when
        self.member = member
        self.written = False

    async def _write(self, story_id: Identifier) -> None:
        if not self.written:
            self.written = True
            outcome = await self.story_store.unlink(
                story_id, (self.member,), actor=StoryActor.OWNER
            )
            assert outcome.logged == 1

    async def story(
        self, story_id: Identifier, *, cursor: int | None = None, limit: int = 50
    ) -> StoryView | None:
        if self.when == "before":
            await self._write(story_id)
        view = await super().story(story_id, cursor=cursor, limit=limit)
        if self.when == "after":
            await self._write(story_id)
        return view


@pytest.mark.parametrize("when", ["before", "after"])
def test_a_write_between_the_log_and_the_members_is_discarded(
    monkeypatch: pytest.MonkeyPatch, output: StringIO, when: str
) -> None:
    """A membership and a log from two states of the story are never rendered together.

    The log is read first and the members after it; an unlink landing on either side
    of the member read appends a line the closing log read finds, so the read is
    discarded rather than showing a member beside the log line that removed it.
    """
    engine = _WritingEngine(when, _activation(_FROZEN))
    engine.episode_memory = FakeMemoryStore(now=lambda: _AT)
    asyncio.run(engine.episode_memory.add(_episode(_FROZEN)))
    asyncio.run(engine.episode_memory.add(_episode(_OPEN, open_=True)))
    story = _create(engine, _activation(_FROZEN), _activation(_OPEN))
    _wire(monkeypatch, engine)
    code, _ = _invoke("story", "show", story)
    assert engine.written
    assert code == 1
    assert "story changed while it was read" in output.getvalue()
    assert "Activation:" not in output.getvalue()


def test_list_pages_newest_first_with_a_continuation(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(_episode(_FROZEN))
    absorbed = _create(engine, _activation(_FROZEN))
    kept = _create(engine, _activation(_FROZEN))
    assert asyncio.run(engine.merge_stories(absorbed, kept)).refusal is None
    _wire(monkeypatch, engine)
    assert _invoke("story", "list", "--limit", "1")[0] == 0
    assert engine.calls[-1] == ("stories", {"cursor": None, "limit": 1})
    first = output.getvalue().splitlines()
    assert first[0].startswith(f'Story "{kept}"  created ')
    cursor = first[1].removeprefix("Next cursor: ")
    output.truncate(0)
    output.seek(0)
    assert _invoke("story", "list", "--cursor", cursor)[0] == 0
    assert output.getvalue().startswith(f'Story "{absorbed}"  created ')
    assert output.getvalue().rstrip().endswith(f'merged into "{kept}"')
    _wire(monkeypatch, _engine())
    output.truncate(0)
    output.seek(0)
    assert _invoke("story", "list")[0] == 0
    assert output.getvalue() == "No stories.\n"


def test_every_change_has_a_rendering() -> None:
    assert set(story_inspection.CHANGE_TEXT) == set(StoryChange)


def test_an_id_cannot_forge_a_line_or_drive_the_terminal() -> None:
    hostile = 'story:a\nStory "forged"\x1b[2J\x9b\u2028end'
    rendered = story_inspection.quoted(hostile)
    assert rendered.isprintable()
    assert rendered == '"story:a\\nStory \\"forged\\"\\u001b[2J\\u009b\\u2028end"'


# --- the episode detail (§5:3) ------------------------------------------------------


def test_the_episode_detail_names_the_activations_stories(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(_episode(_FROZEN), _episode(_OPEN, open_=True))
    older = _create(engine, _activation(_FROZEN))
    newer = _create(engine, _activation(_FROZEN), _activation(_OPEN))
    _wire(monkeypatch, engine)
    assert _invoke("episode", f"activation:{_FROZEN}")[0] == 0
    assert engine.calls[-1] == ("activation_stories", {"activation_id": _FROZEN})
    headers = asyncio.run(engine.activation_stories(_FROZEN))
    expected = ", ".join(f'"{header.story_id}"' for header in headers)
    assert {header.story_id for header in headers} == {older, newer}
    assert f"\nStories: {expected}\n" in output.getvalue()


def test_the_episode_detail_says_an_activation_belongs_to_no_story(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    _wire(monkeypatch, _engine(_episode(_OPEN, open_=True)))
    assert _invoke("episode", f"activation:{_OPEN}")[0] == 0
    assert "\nResponse: none yet\nStories: none\n" in output.getvalue()


def test_an_episode_with_no_activation_asks_for_no_stories(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    engine = _engine(_bare_episode("bare"))
    _wire(monkeypatch, engine)
    assert _invoke("episode", "bare")[0] == 0
    assert "\nStories: unavailable\n" in output.getvalue()
    assert "activation_stories" not in {method for method, _ in engine.calls}


def test_the_json_detail_asks_for_no_stories(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """``--json`` prints the canonical record and nothing else."""
    engine = _engine(_episode(_FROZEN))
    _create(engine, _activation(_FROZEN))
    _wire(monkeypatch, engine)
    assert _invoke("episode", f"activation:{_FROZEN}", "--json")[0] == 0
    assert "activation_stories" not in {method for method, _ in engine.calls}
    assert "Stories:" not in output.getvalue()

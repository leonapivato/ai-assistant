"""What each done call's entry keeps of what it showed, as the phases record it.

ADR-0358 §11:2-§11:4, driven over :class:`PhaseWorking` as acting hands its calls back:
a memory search keeps the records it showed by id, record by record, and nothing of
those its digest read; one no round followed keeps the ids it listed; an episode
look-up keeps the episodes it read; a call not done keeps nothing; and what is kept is
cut to the composition root's bound, the cut carried.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_receiver_contract import event_input
from phases_support import chat_turn, phases_harness, processing
from test_phases_exchange import _AT, _call, _entries, _lookup, _planned, _working
from test_planning import _episode

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionRequest,
    Attestation,
    CallShowed,
    EpisodicMemory,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RoundResponse,
    ShownRecord,
    ShownRecordKind,
    ToolCall,
    ToolDefinition,
)
from ai_assistant.orchestration.acting import ActedCall, ActedOutcome, AuthorizedCall, ResultRoute
from ai_assistant.orchestration.authorizer import CallVerdict, RoundAuthorization, Verdict
from ai_assistant.orchestration.lookups import READ_EPISODE, SEARCH_EPISODES, SEARCH_MEMORY
from ai_assistant.orchestration.phase_path import PhasePath, PhaseWorking
from ai_assistant.orchestration.planning import CallOutcomeKind, EpisodesFound, EpisodeShown
from ai_assistant.testing import FakeToolCallingCompleter
from ai_assistant.testing.memories import memory, said_support, sourced_support

if TYPE_CHECKING:
    from collections.abc import Mapping

    from test_engine import Harness


def _allowed(tool: ToolDefinition, decision: str, **parameters: Any) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=parameters)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    return ToolCall(
        request=request,
        decision=PermissionDecision.from_request(request, ruling, id=decision, decided_at=_AT),
    )


def _acted(
    tool: ToolDefinition, *, output: object, route: ResultRoute = ResultRoute.PLANNING, **args: Any
) -> PhaseWorking:
    """A working set whose one round's one call acting handed back done."""
    working = _working()
    working.planned(_planned(_call("c1", str(tool.capability), **args)))
    working.latest.authorization = RoundAuthorization(
        activation_id="activation",
        round_id="round-1",
        verdicts=(CallVerdict("c1", Verdict.ALLOWED, decision_id="d1"),),
    )
    working.latest.acted_one(
        ActedCall(
            AuthorizedCall(_allowed(tool, "d1", **args)),
            ActedOutcome.DONE,
            output=output,  # type: ignore[arg-type]  # JSON values
            route=route,
            result_id="result:1",
        )
    )
    return working


def test_a_search_keeps_the_records_planning_was_shown_by_id() -> None:
    """§11:2-§11:3: each record shown by id, one resting on outside content left out."""
    working = _acted(SEARCH_MEMORY, output={"records": ["said", "turned"]}, query="dentist")
    said = memory("said", "dentist with Dr Rao", said_support(when=_AT, added_at=_AT))
    turned = memory(
        "turned",
        "moved",
        sourced_support(Attestation(reported_by="mail", reported_at=_AT), when=_AT, added_at=_AT),
    )
    working.searched["result:1"] = (said, turned)

    (entry,) = working.call_entries(_AT)

    assert entry.outcome is CallOutcomeKind.DONE
    assert entry.showed == CallShowed(parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),))
    assert "Dr Rao" not in entry.model_dump_json()


def test_a_search_no_round_followed_keeps_the_ids_it_listed() -> None:
    """§11:2: the records it listed for planning, by id, never fetched."""
    working = _acted(SEARCH_MEMORY, output={"records": ["said"]}, query="dentist")

    (entry,) = working.call_entries(_AT, freezing=True)

    assert entry.showed == CallShowed(parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),))


def test_a_searchs_entry_waits_for_the_fetch_that_decides_what_planning_is_shown() -> None:
    """§11:2: a record gone before the next round's fetch was never shown, so a search's
    entry is made once its records are fetched, and keeps only those that came back."""
    from ai_assistant.orchestration.acting import ActedRound  # noqa: PLC0415

    working = _acted(SEARCH_MEMORY, output={"records": ["said", "gone"]}, query="dentist")
    working.latest.acted = ActedRound(
        round_id="round-1", calls=tuple(working.latest.handed.values())
    )
    assert working.call_entries(_AT) == ()

    working.searched["result:1"] = (
        memory("said", "dentist with Dr Rao", said_support(when=_AT, added_at=_AT)),
    )
    (entry,) = working.call_entries(_AT)

    assert entry.showed == CallShowed(parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),))
    assert working.call_entries(_AT) == ()


def test_a_result_held_for_a_digest_keeps_nothing() -> None:
    """§11:3: a result held for a digest keeps nothing; its digests are on the record."""
    working = _acted(SEARCH_MEMORY, output=None, route=ResultRoute.DIGEST, query="dentist")
    working.searched["result:1"] = ()

    (entry,) = working.call_entries(_AT)

    assert entry.showed == CallShowed()
    assert entry.marked


def test_an_episode_search_keeps_each_episode_it_showed() -> None:
    """§11:2: the episodes it read, held by the glue under its result, by id."""
    working = _acted(SEARCH_EPISODES, output={"looked_up": "search_episodes"}, query="dentist")
    working.looked["result:1"] = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one")),)
    )

    (entry,) = working.call_entries(_AT)

    assert entry.showed == CallShowed(
        parts=(ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:one"),)
    )


def test_a_matter_planning_already_labelled_keeps_no_summary_version() -> None:
    """§8:1, §11:2: a matter the activation already labelled is rendered by its label
    alone, so its entry keeps no summary version, whatever version it is at now."""
    from ai_assistant.core.types import LabelKind, PlanningLabel  # noqa: PLC0415
    from ai_assistant.orchestration.planning import MatterShown  # noqa: PLC0415

    working = _acted(SEARCH_EPISODES, output={"looked_up": "search_episodes"}, query="dentist")
    working.labels.add((PlanningLabel(label="S9", kind=LabelKind.STORY, id="story:dentist"),))
    matter = MatterShown(story_id="story:dentist", summary_version=2, first_line="Version two.")
    working.looked["result:1"] = EpisodesFound(
        episodes=(EpisodeShown(record=_episode("activation:one"), matters=(matter,)),)
    )

    (entry,) = working.call_entries(_AT)

    assert entry.showed == CallShowed(
        parts=(
            ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:one"),
            ShownRecord(kind=ShownRecordKind.STORY, id="story:dentist"),
        )
    )


def test_what_an_entry_keeps_is_cut_to_the_bound_and_the_cut_carried() -> None:
    """§11:4: past the composition root's bound the rest is left out, and the entry says so."""
    working = _acted(SEARCH_MEMORY, output={"records": ["aaaa", "bbbb"]}, query="dentist")

    (entry,) = working.call_entries(_AT, freezing=True, showed=5)

    assert entry.showed == CallShowed(
        parts=(ShownRecord(kind=ShownRecordKind.MEMORY, id="aaaa"),), cut=True
    )


def test_a_call_not_done_keeps_nothing_of_what_it_showed() -> None:
    """§11:2: only a done call's entry keeps what it showed."""
    working = _working()
    working.planned(_planned(_call("c1", "search_memory", query="x"), refused=("c1",)))

    (entry,) = working.call_entries(_AT)

    assert entry.outcome is CallOutcomeKind.REFUSED
    assert entry.showed is None


def test_a_full_view_showing_a_marked_summary_is_outside_content_read() -> None:
    """§6:4, ADR-0303 §3:6: a marked summary the full view shows is counted as read."""
    from ai_assistant.core.episode_encoding import project_episode  # noqa: PLC0415
    from ai_assistant.orchestration.planning import EpisodeRead, MatterShown  # noqa: PLC0415

    working = _acted(READ_EPISODE, output={"looked_up": "read_episode"}, episode="activation:one")
    record = _episode("activation:one")
    marked = MatterShown(
        story_id="story:venue", summary_version=1, first_line="The venue wrote", outside=True
    )
    read = EpisodeRead(
        episode_id=record.id,
        record=record,
        projection=project_episode(record, excerpt_chars=50, owner_records=True, full_view=True),
        matters=(marked,),
    )
    handed = tuple(working.latest.handed.values())

    PhasePath._looked(working, handed, {"d1": read})

    assert working.read_outside_content
    assert "story:venue" in working.fetched_outside_from


def test_a_marked_summary_only_another_page_shows_is_not_read_on_this_one() -> None:
    """§6:4: what the page shows is counted, and a story only a later page names is not."""
    from test_planning_episode_lookups import _full_record, _read  # noqa: PLC0415

    from ai_assistant.orchestration.planning import MatterShown  # noqa: PLC0415

    marked = MatterShown(
        story_id="story:dentist", summary_version=1, first_line="The venue wrote", outside=True
    )
    for page, read_outside in ((1, False), (3, True)):
        working = _acted(
            READ_EPISODE, output={"looked_up": "read_episode"}, episode="activation:full"
        )
        read = _read(_full_record(), page_size=1, page=page, stories={"story:dentist": marked})
        handed = tuple(working.latest.handed.values())

        PhasePath._looked(working, handed, {"d1": read})

        assert ("story:dentist" in working.fetched_outside_from) is read_outside


# --- review round 7: a done look-up keeps what it showed where acting raised ----------

#: What a search for "dentist" over :func:`_seeded`'s store showed.
_FOUND: Final = CallShowed(
    parts=(ShownRecord(kind=ShownRecordKind.EPISODE, id="activation:dentist"),)
)


async def _seeded(harness: Harness) -> None:
    """A past episode an episode search for "dentist" finds, stored in the harness."""
    record = _episode("activation:dentist").model_copy(
        update={"content": "the dentist moved the cleaning"}
    )
    await harness.memory.add(record)


async def test_an_episode_search_beside_a_sibling_that_raised_keeps_what_it_showed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§11:2, ADR-0356 §8:6: a done episode search keeps the episodes it read, though the
    plan store failing to finish its sibling's record made acting raise."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "search_episodes", query="dentist"),
                _call("c2", "once", place="Hillside"),
            )
        )
    )
    harness = phases_harness(
        completer,
        tools=(_lookup("once"),),
        phases={"capabilities": ("once",), "look_ups": True, "episode_look_ups": True},
    )
    await _seeded(harness)
    finish = harness.plans.finish_activation_effect
    failed: list[str] = []

    async def first_unfinished(effect_id: str, *args: Any, **kwargs: Any) -> None:
        if not failed:
            failed.append(effect_id)
            msg = "the plan store is down"
            raise PlanningError(msg)
        await finish(effect_id, *args, **kwargs)

    monkeypatch.setattr(harness.plans, "finish_activation_effect", first_unfinished)

    _, episode = await chat_turn(harness, "what did the dentist say")

    assert failed, "the sibling's record was the one left unfinished"
    entries = _entries(episode)
    assert entries["c1"].outcome is CallOutcomeKind.DONE
    assert entries["c1"].showed == _FOUND
    assert entries["c2"].outcome is None
    await harness.engine.aclose()


async def test_an_episode_search_finished_before_the_round_was_cancelled_keeps_it() -> None:
    """§11:2, ADR-0356 §8:6: a done episode search keeps the episodes it read, though the
    round was cancelled before acting handed the round back."""
    entered = asyncio.Event()

    async def handler(parameters: Mapping[str, object], *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        entered.set()
        await asyncio.Event().wait()  # until the round is cancelled

    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _call("c1", "search_episodes", query="dentist"),
                _call("c2", "lookup", place="Hillside"),
            )
        )
    )
    # An event's input is outside content, so the read stays on the hub to be allowed.
    harness = phases_harness(
        completer,
        tools=(_lookup("lookup", leaves_hub=False),),
        tool_handler=handler,
        phases={"capabilities": ("lookup",), "look_ups": True, "episode_look_ups": True},
    )
    await _seeded(harness)
    task = asyncio.ensure_future(
        harness.engine.receive(event_input(), reply=None, timeout=timedelta(seconds=30))
    )
    await asyncio.wait_for(entered.wait(), 5)

    def searched() -> bool:
        # The round as the phases hold it: the search has come back to acting.
        (running,) = [one.state for one in harness.engine._running if one.state is not None]
        phases = getattr(running.working, "phases", None)
        assert isinstance(phases, PhaseWorking)
        return any(
            str(one.call.call.request.tool.capability) == "search_episodes"
            for one in phases.latest.handed.values()
        )

    for _ in range(200):
        if searched():
            break
        await asyncio.sleep(0)
    assert searched(), "the search came back to acting before the round was cancelled"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (episode,) = [
        one
        for one in await harness.memory.export()
        if isinstance(one, EpisodicMemory) and one.id != "activation:dentist"
    ]
    assert not processing(episode).is_open
    entries = _entries(episode)
    assert entries["c1"].outcome is CallOutcomeKind.DONE
    assert entries["c1"].showed == _FOUND
    assert entries["c2"].outcome is None
    await harness.engine.aclose()


# --- successor round 3: a story call keeps the stories its report shows ---------------


async def test_a_story_started_keeps_the_story_its_report_showed() -> None:
    """§11:2, ADR-0356 §5:4: a story call done shows, in the next round's report, the
    story it brought the activation into, and its entry keeps that story by reference."""
    from test_engine_phases import _conversation, _harness, _say, _settled  # noqa: PLC0415

    from ai_assistant.core.types import StoryMember, StoryMemberKind  # noqa: PLC0415
    from ai_assistant.testing import FakeStoryStore  # noqa: PLC0415

    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "start_story", notes=["A camping trip to Riverside."]),)),
        RoundResponse(text="Noted."),
    )
    stories = FakeStoryStore(now=lambda: _AT)
    harness = _harness(completer, stories=stories, story_calls=True)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "help me plan a camping trip to Riverside")
    episode = await _settled(harness, conversation)

    record = processing(episode)
    member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=record.activation_id)
    (header,) = await stories.stories_of(member)
    second = json.dumps(completer.calls[1].exchange.model_dump(mode="json"))
    assert "S1" in second, "the next round's report showed the story"
    entry = _entries(episode)["c1"]
    assert entry.outcome is CallOutcomeKind.DONE
    assert entry.showed is not None
    assert [
        one.id
        for one in entry.showed.parts
        if isinstance(one, ShownRecord) and one.kind is ShownRecordKind.STORY
    ] == [str(header.story_id)]
    await harness.engine.aclose()

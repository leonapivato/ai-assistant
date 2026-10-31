"""Planning's side of the observer end to end (ADR-0329 §§3-6).

The phases as the composition root builds them, ``remember`` recording candidates,
through the engine over fakes: a candidate recorded with nothing written and its lookup
shown in the next round, a *confirm* that needs you, reliance noted with nothing
recorded but the round, and the episode window's pending candidates read from the plan
store until the observer has processed the episode.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

from exchange_support import reported
from structured_support import structured
from test_engine import AT, Harness
from test_engine_phases import _BOOK, _DIGESTED, _PHONE, _call, _conversation, _Policy, _settled
from understanding_support import understanding_stage

from ai_assistant.core.types import (
    EpisodicMemory,
    Memory,
    ObservationRecord,
    ObservationState,
    RoundResponse,
    ToolOutcome,
    UserMessage,
)
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.chat import ChatWriter
from ai_assistant.orchestration.digesting import DIGESTING_PROMPT
from ai_assistant.orchestration.lookups import LookUps
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.phase_path import PhasePath, PhaseTools
from ai_assistant.orchestration.planning import PLANNING_PROMPT
from ai_assistant.orchestration.reliance import NOTE_RELIANCE, RELIANCE_LABEL_ARGUMENTS
from ai_assistant.orchestration.remembering import (
    CANDIDATE_LABEL_ARGUMENTS,
    REMEMBER_CANDIDATE,
    CandidateCalls,
)
from ai_assistant.testing import (
    FakeModelProvider,
    FakeStoryStore,
    FakeToolCallingCompleter,
    default_prompt,
)
from ai_assistant.testing.memories import memory as memory_record
from ai_assistant.testing.memories import said_support

if TYPE_CHECKING:
    from collections.abc import Callable


_FACT: Final = "The user prefers window seats."


def _phases(
    completer: FakeToolCallingCompleter, stories: FakeStoryStore
) -> Callable[[Harness], PhasePath]:
    """The thin path as the composition root builds it."""

    def build(harness: Harness) -> PhasePath:
        looking = LookUps(memory=harness.memory, views=None, search_limit=5)
        tools = PhaseTools(
            registry=harness.invoker,
            invoker=harness.invoker,
            own_records=(REMEMBER_CANDIDATE,),
            reliance=NOTE_RELIANCE,
        )
        return PhasePath(
            planning_prompt=default_prompt(PLANNING_PROMPT),
            digesting_prompt=default_prompt(DIGESTING_PROMPT),
            completer=completer,
            provider=structured(FakeModelProvider(reply=_DIGESTED)),
            authorizing=AuthorizingStage(
                registry=tools,
                policy=_Policy(),
                trail=harness.trail,
                stories=stories,
                memory=harness.memory,
                plans=harness.plans,
                now=lambda: AT,
            ),
            acting=ActingStage(
                plans=harness.plans,
                invoker=tools,
                own_records=OwnRecordsByCapability(
                    {"remember": CandidateCalls(similar=looking, limit=3)}
                ),
                timeout=timedelta(seconds=5),
                now=lambda: AT,
            ),
            tools=tools,
            plans=harness.plans,
            writer=ChatWriter(
                conversations=harness.conversation_store,
                max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES,
            ),
            capabilities=("remember", "note_reliance"),
            label_arguments={**CANDIDATE_LABEL_ARGUMENTS, **RELIANCE_LABEL_ARGUMENTS},
            look_ups=looking,
            round_limit=4,
            round_wait=timedelta(seconds=5),
            excerpt_chars=2000,
            part_chars=4000,
            memory=harness.memory,
            recall_cap=6,
            recall_digest_wait=timedelta(seconds=5),
            now=lambda: AT,
        )

    return build


class _Harness(Harness):
    """The engine harness, its phases built as the composition root builds them."""

    def __init__(self, completer: FakeToolCallingCompleter) -> None:
        super().__init__(
            understanding=understanding_stage(),
            tools=(_BOOK,),
            phases=_phases(completer, FakeStoryStore(now=lambda: AT)),
        )


async def _say(harness: Harness, conversation: str, text: str, message_id: str) -> None:
    message = UserMessage(device_id=_PHONE.device_id, message_id=message_id, text=text)
    await harness.engine.write_message(conversation, message=message)


def _request(completer: FakeToolCallingCompleter, index: int) -> dict[str, Any]:
    rendered: dict[str, Any] = json.loads(completer.calls[index].exchange.briefing)
    return rendered


def _candidate(call_id: str = "c1", **fields: Any) -> Any:
    return _call(call_id, "remember", fact=_FACT, why="travel", rests_on_input=True, **fields)


async def test_a_candidate_is_recorded_writes_no_memory_and_shows_its_lookup_next_round() -> None:
    """§3:3, §5:7: the effect record done and nothing written; §4:1, §6:5: the lookup."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Got it, I'll remember.", calls=(_candidate(),)),
        RoundResponse(),
    )
    harness = _Harness(completer)
    await harness.memory.add(memory_record("aisle", "prefers aisle seats", said_support()))
    conversation = await _conversation(harness)

    await _say(harness, conversation, "remember I like window seats", "m-1")
    episode = await _settled(harness, conversation)

    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    (recorded,) = [one for one in effects if one.capability == "remember"]
    assert recorded.outcome is ToolOutcome.SUCCEEDED
    held = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert [one.id for one in held] == ["aisle"]
    (call,) = reported(completer.calls[1], 0)
    assert call["outcome"] == "done"
    value = call["result"]["value"]
    assert value["candidate"].startswith("recorded as a candidate, and pending")
    assert [(one["label"], one["fact"]) for one in value["similar_memories"]] == [
        ("M1", "prefers aisle seats")
    ]


async def test_a_candidate_with_confirm_set_needs_you_and_records_nothing() -> None:
    """§5:2: needs you by rule; §5:4: unanswered, it records nothing."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_candidate(confirm=True),)),
        RoundResponse(text="Want me to remember you prefer window seats?"),
    )
    harness = _Harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "I always take the window seat", "m-1")
    episode = await _settled(harness, conversation)

    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert [one for one in effects if one.capability == "remember"] == []
    (call,) = reported(completer.calls[1], 0)
    assert call["outcome"].startswith("needs the user's yes")
    assert call["because"] == "the user is asked to confirm this wording before it is kept"


async def test_reliance_is_noted_in_the_round_and_nowhere_else() -> None:
    """§6:7: no effect, no record, done, and nothing returned; the round keeps it."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_candidate(),)),
        RoundResponse(
            text="A window seat, as you like.",
            calls=(_call("c2", "note_reliance", memories=["M1"], shaped="the seat suggested"),),
        ),
        RoundResponse(),
    )
    harness = _Harness(completer)
    await harness.memory.add(memory_record("window", "prefers window seats", said_support()))
    conversation = await _conversation(harness)

    await _say(harness, conversation, "pick me a seat, and remember I like windows", "m-1")
    episode = await _settled(harness, conversation)

    effects = await harness.plans.activation_effects([episode.id.removeprefix("activation:")])
    assert [one.capability for one in effects if one.capability is not None] == ["remember"]
    assert episode.processing_record is not None
    noted = episode.processing_record.rounds[1].calls[0]
    assert (noted.name, dict(noted.arguments)["memories"]) == ("note_reliance", ("M1",))
    reliance = reported(completer.calls[2], 1)[0]
    assert reliance["outcome"] == "done"
    assert "result" not in reliance


async def _first(harness: _Harness, conversation: str) -> EpisodicMemory:
    await _say(harness, conversation, "remember I like window seats", "m-1")
    return await _settled(harness, conversation)


def _window_candidates(completer: FakeToolCallingCompleter, index: int) -> list[Any]:
    return [one.get("candidates") for one in _request(completer, index)["episode_window"]]


async def test_an_unprocessed_episodes_candidates_reach_the_next_activations_window() -> None:
    """§6:9, §3:3: read from the round, joined to the effect record that shows it done.

    The second round's candidate names a memory by the M label its lookup showed, so the
    join maps the episode's own labels as planning's check did.
    """
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Got it.", calls=(_candidate(),)),
        RoundResponse(
            calls=(
                _call(
                    "c2",
                    "remember",
                    fact="The user prefers window seats over aisle seats.",
                    why="a correction of a held memory",
                    rests_on_input=True,
                    memory="M1",
                    note="it replaces the aisle preference",
                ),
            )
        ),
        RoundResponse(),
        RoundResponse(text="Sure."),
    )
    harness = _Harness(completer)
    await harness.memory.add(memory_record("aisle", "prefers aisle seats", said_support()))
    conversation = await _conversation(harness)
    first = await _first(harness, conversation)

    await _say(harness, conversation, "thanks", "m-2")
    await _settled(harness, conversation, seeded=frozenset({first.id}))

    assert _window_candidates(completer, 3) == [
        [
            {"fact": _FACT, "status": "pending: recorded for long-term memory, not yet kept"},
            {
                "fact": "The user prefers window seats over aisle seats.",
                "status": "pending: recorded for long-term memory, not yet kept",
            },
        ]
    ]


async def test_a_processed_episode_shows_no_candidate() -> None:
    """§6:9, §16:2: once the observer has processed it, its candidates are not pending."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Got it.", calls=(_candidate(),)),
        RoundResponse(),
        RoundResponse(text="Sure."),
    )
    harness = _Harness(completer)
    conversation = await _conversation(harness)
    first = await _first(harness, conversation)
    await harness.plans.write_observation(
        ObservationRecord(episode=first.id, state=ObservationState.PROCESSED), expected_revision=0
    )

    await _say(harness, conversation, "thanks", "m-2")
    await _settled(harness, conversation, seeded=frozenset({first.id}))

    assert _window_candidates(completer, 2) == [None]


async def test_a_waiting_episode_still_shows_its_candidates() -> None:
    """§16:1-§16:2: an attempted episode not yet processed is still pending."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(text="Got it.", calls=(_candidate(),)),
        RoundResponse(),
        RoundResponse(text="Sure."),
    )
    harness = _Harness(completer)
    conversation = await _conversation(harness)
    first = await _first(harness, conversation)
    await harness.plans.write_observation(
        ObservationRecord(episode=first.id, state=ObservationState.WAITING), expected_revision=0
    )

    await _say(harness, conversation, "thanks", "m-2")
    await _settled(harness, conversation, seeded=frozenset({first.id}))

    assert _window_candidates(completer, 2) == [
        [{"fact": _FACT, "status": "pending: recorded for long-term memory, not yet kept"}]
    ]

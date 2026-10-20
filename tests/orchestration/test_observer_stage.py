"""The observer's run: the queue, the limits and the observation record (ADR-0329 §7, §16).

Driven over the canonical fakes with scripted model routes. The reading, the two steps'
checks and the writes each have their own suite; this one holds what a run does with
them: which episodes are due and in what order, what is recorded as it goes, and what a
failure, the budget, the bound and a second run do.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NoReturn

import structlog.testing
from observer_support import AT, SINCE, Harness, address, episode, remembered, reply

from ai_assistant.core.errors import MemoryStoreError, ModelError, PlanningError
from ai_assistant.core.types import (
    ActivationUnderstanding,
    AnsweredQuestion,
    AskedCall,
    ConfirmationPart,
    EpisodicMemory,
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryChange,
    MemoryDecisionKind,
    MemoryOperationKind,
    MemorySource,
    MemoryStanding,
    ObservationAttemptEnd,
    ObservationState,
    ObserverStep,
    OpenQuestionKind,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningRound,
    Provenance,
    QuestionPart,
    ReadingCertainty,
    Role,
    SupportOrigin,
    UnderstandingGround,
    UnderstandingProducer,
)
from ai_assistant.core.types import Message as MessageType
from ai_assistant.orchestration.observer import RunOutcome
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.testing import FakeModelProvider
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.types import Message

_PREFERENCE = "I prefer window seats when I fly."


async def _three(harness: Harness, *, text: str = _PREFERENCE) -> None:
    """Three episodes, a minute apart: with a window of two, the oldest has left it."""
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3), text=text),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


def _scout(*parts: str) -> str:
    return reply(findings=[{"claim": "The user prefers window seats.", "rests_on": list(parts)}])


def _create(part: str = "P1") -> str:
    return reply(
        action="create",
        wording="The user prefers window seats.",
        supports=[{"part": part, "direction": "for", "backs_as_worded": True, "how_sure": "sure"}],
    )


async def test_an_episode_that_left_the_window_is_committed_and_recorded() -> None:
    """§7:1, §9, §12, §16:1: scout, commit, a memory written, the record processed."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    (attempt,) = record.attempts
    assert attempt.end is ObservationAttemptEnd.FINISHED
    assert [call.step for call in attempt.calls] == [ObserverStep.SCOUT, ObserverStep.COMMIT]
    (finding,) = record.findings
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    assert write.operations == (MemoryOperationKind.CREATE,)
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == "The user prefers window seats."
    (support,) = stored.supports
    assert support.origin is SupportOrigin.USER_MESSAGE
    assert support.when == AT - timedelta(minutes=3)
    assert support.added_by.value == "observer"
    assert await harness.plans.observations(["activation:two", "activation:three"]) == ()


def _failing(message: str = "the route is down") -> FakeModelProvider:
    def fail(_messages: Sequence[Message]) -> str:
        raise RuntimeError(message)

    return FakeModelProvider(reply=fail)


async def test_the_queue_is_the_episodes_out_of_the_window_since_the_instant_oldest_first() -> None:
    """§7:1, §7:5, §16:2, §16:3: in the window, before the instant, or open, none is due."""
    harness = Harness()
    await harness.hold(
        episode("before", at=SINCE - timedelta(minutes=1)),
        episode("old", at=AT - timedelta(minutes=5)),
        episode("older", at=AT - timedelta(minutes=6)),
        episode("running", at=AT - timedelta(minutes=4), open_=True),
        episode("recent", at=AT - timedelta(minutes=2)),
        episode("newest", at=AT - timedelta(minutes=1)),
    )
    observer = harness.observer()

    queue = await observer.due(await RecentEpisodes(memory=harness.memory, limit=2)(frozenset()))

    assert [episode_id for episode_id, _ in queue] == ["activation:older", "activation:old"]


async def test_a_processed_episode_is_never_queued_again() -> None:
    """§7:1: the first time an episode is due is the only time it is processed."""
    harness = Harness()
    await _three(harness)
    scout = FakeModelProvider.scripted(reply(findings=[]))
    observer = harness.observer(scout=scout)

    first = await observer.run()
    second = await observer.run()

    assert first.processed == 1
    assert second == RunOutcome()
    assert len(scout.calls) == 1


async def test_an_episode_with_nothing_to_read_is_skipped_with_no_model_call() -> None:
    """§16:7: no message, no candidate, no evidence item: skipped by rule."""
    harness = Harness()
    await _three(harness, text="")
    observer = harness.observer()

    outcome = await observer.run()

    assert outcome.skipped == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.SKIPPED
    assert record.call_count() == 0


async def test_an_episode_with_no_processing_record_is_skipped() -> None:
    """Its origin cannot be set from a record it does not carry (ADR-0328 §4:2)."""
    harness = Harness()
    bare = EpisodicMemory(
        id="harness:bare",
        content="the user said they like tea",
        occurred_at=AT - timedelta(minutes=9),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    await harness.hold(bare)
    await _three(harness)
    observer = harness.observer(scout=FakeModelProvider.scripted(reply(findings=[])))

    outcome = await observer.run()

    assert (outcome.skipped, outcome.processed) == (1, 1)
    (record,) = await harness.plans.observations(["harness:bare"])
    assert record.state is ObservationState.SKIPPED


async def test_a_failed_attempt_backs_off_doubling_then_the_episode_is_stuck() -> None:
    """§16:4, §16:5: a backoff from the base, doubling, then stuck and set aside."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(scout=_failing(), stuck_after=3)

    first = await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert first.waiting == 1
    assert record.state is ObservationState.WAITING
    assert record.next_attempt_at == AT + timedelta(minutes=1)
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED
    assert record.call_count() == 1

    assert await observer.run() == RunOutcome()  # still backing off

    harness.clock.advance(timedelta(minutes=1))
    await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.next_attempt_at == harness.clock.at + timedelta(minutes=2)

    harness.clock.advance(timedelta(minutes=2))
    third = await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert third.stuck == 1
    assert record.state is ObservationState.STUCK
    assert record.next_attempt_at is None
    assert len(record.attempts) == 3

    harness.clock.advance(timedelta(days=1))
    assert await observer.run() == RunOutcome()


async def test_a_stuck_episode_is_set_aside_and_later_episodes_proceed() -> None:
    """§16:5: the queue goes on past a stuck episode."""
    harness = Harness()
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=4)),
        episode("two", at=AT - timedelta(minutes=3)),
        episode("three", at=AT - timedelta(minutes=2)),
        episode("four", at=AT - timedelta(minutes=1)),
    )
    replies: Iterator[str | Exception] = iter([RuntimeError("down"), reply(findings=[])])

    def scripted(_messages: Sequence[Message]) -> str:
        answer = next(replies)
        if isinstance(answer, Exception):
            raise answer
        return answer

    observer = harness.observer(scout=FakeModelProvider(reply=scripted), stuck_after=1)

    outcome = await observer.run()

    assert (outcome.stuck, outcome.processed) == (1, 1)
    one, two = await harness.plans.observations(["activation:one", "activation:two"])
    assert one.state is ObservationState.STUCK
    assert two.state is ObservationState.PROCESSED


async def test_a_reply_that_does_not_parse_fails_the_attempt() -> None:
    """A reply that does not parse is no proposal, never a partial one (§16:4)."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(scout=FakeModelProvider.scripted("not json"))

    outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings == ()
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED


async def test_a_retry_commits_only_the_findings_with_no_outcome() -> None:
    """§16:4: a finding whose outcome is recorded is not committed again."""
    harness = Harness()
    await _three(harness)
    two = reply(
        findings=[
            {"claim": "The user prefers window seats.", "rests_on": ["P1"]},
            {"claim": "The user flies.", "rests_on": ["P1"]},
        ]
    )
    answers: Iterator[str | Exception] = iter(
        [_create(), RuntimeError("down"), reply(action="nothing")]
    )

    def commit(_messages: Sequence[Message]) -> str:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    scout = FakeModelProvider.scripted(two)
    observer = harness.observer(scout=scout, commit=FakeModelProvider(reply=commit))

    await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.WAITING
    assert [one.outcome is not None for one in record.findings] == [True, False]

    harness.clock.advance(timedelta(minutes=1))
    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    assert len(scout.calls) == 1
    assert record.findings[1].outcome is not None
    assert record.findings[1].outcome.unwritten is FindingUnwritten.NOT_KEPT
    assert [call.step for call in record.attempts[-1].calls] == [ObserverStep.COMMIT]


async def test_the_daily_budget_holds_the_run_and_drops_nothing() -> None:
    """§16:9: a call that would exceed the budget is not made; the episode waits."""
    harness = Harness()
    await _three(harness)
    commit = FakeModelProvider.scripted(_create())
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), commit=commit, daily_calls=1
    )

    held = await observer.run()

    assert held.held
    assert commit.calls == []
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.WAITING
    assert record.attempts[-1].end is ObservationAttemptEnd.HELD
    assert record.next_attempt_at is None
    assert len(record.findings) == 1

    harness.clock.advance(timedelta(hours=24, seconds=1))
    resumed = await observer.run()

    assert resumed.processed == 1
    assert len(commit.calls) == 1


async def test_a_run_takes_at_most_its_bound_of_episodes() -> None:
    """§16:8: what is left waits for the next run."""
    harness = Harness()
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=4), text=""),
        episode("two", at=AT - timedelta(minutes=3), text=""),
        episode("three", at=AT - timedelta(minutes=2)),
        episode("four", at=AT - timedelta(minutes=1)),
    )
    observer = harness.observer(per_run=1)

    first = await observer.run()
    second = await observer.run()

    assert (first.skipped, second.skipped) == (1, 1)
    one, two = await harness.plans.observations(["activation:one", "activation:two"])
    assert (one.state, two.state) == (ObservationState.SKIPPED, ObservationState.SKIPPED)


class _Blocking:
    """A model route that answers only once released."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        del messages, model
        self.entered.set()
        await self.release.wait()
        return MessageType(role=Role.ASSISTANT, content=reply(findings=[]))


async def test_a_run_asked_for_while_one_runs_does_not_start() -> None:
    """§16:6: at most one run at a time."""
    harness = Harness()
    await _three(harness)
    route = _Blocking()
    observer = harness.observer()
    observer._scout = route

    running = asyncio.create_task(observer.run())
    await route.entered.wait()
    busy = await observer.run()
    route.release.set()
    done = await running

    assert busy == RunOutcome(busy=True)
    assert done.processed == 1


async def test_the_run_logs_no_fact_wording_or_identifier() -> None:
    """§15:7: stage and code-owned reasons only."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
    )

    with structlog.testing.capture_logs() as logs:
        await observer.run()

    rendered = repr(logs)
    assert logs
    for private in ("window seats", "activation:one", "observed:", _PREFERENCE):
        assert private not in rendered


async def test_a_failing_route_is_logged_by_its_error_class_alone() -> None:
    """§15:7: the reason is code-owned: the error's class, never its message."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(scout=_failing("the user's sister Imogen"))

    with structlog.testing.capture_logs() as logs:
        await observer.run()

    (event,) = [one for one in logs if one["event"] == "observer_attempt"]
    assert event["reason"] == ModelError.__name__
    assert "Imogen" not in repr(logs)


def _answering(decide: Callable[[dict[str, Any]], str]) -> FakeModelProvider:
    """A commit route that answers from what it was shown."""

    def answer(messages: Sequence[Message]) -> str:
        return decide(json.loads(messages[-1].content))

    return FakeModelProvider(reply=answer)


async def _confirmed_case(harness: Harness) -> str:
    """An asked candidate and the user's yes, the yes leaving the window; the fact."""
    fact = "The user prefers window seats."
    asked = AskedCall(
        part=1,
        tool=REMEMBER_CANDIDATE,
        values={
            "fact": fact,
            "why": "travel",
            "rests_on_input": True,
            "confirm": True,
            "episode": address("asking"),
            "rests_on_outside_content": False,
        },
    )
    yes_at = AT - timedelta(minutes=3)
    understood = ActivationUnderstanding(
        version=1,
        recorded_at=yes_at,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="yes to remembering it",
        meaning_ground=UnderstandingGround.STATED,
        answers=(AnsweredQuestion(activation_id="asking", round="r-ask"),),
    )
    await harness.hold(
        episode(
            "asking",
            at=AT - timedelta(minutes=4),
            text="",
            rounds=(
                PlanningRound(
                    id="r-ask",
                    recorded_at=AT - timedelta(minutes=4),
                    text="Want me to remember you prefer window seats?",
                    asked=(asked,),
                ),
            ),
        ),
        episode("yes", at=yes_at, text="yes", understanding=(understood,)),
        episode("two", at=AT - timedelta(minutes=2), text="ok"),
        episode("three", at=AT - timedelta(minutes=1), text="ok"),
    )
    await remembered(
        harness.plans,
        "yes",
        "r-yes",
        {"fact": fact, "why": "travel", "rests_on_input": True, "confirm": True},
        part=QuestionPart(round="r-ask", part=1),
    )
    return fact


async def test_a_candidate_the_user_confirmed_is_kept_in_the_words_they_approved() -> None:
    """§5:5, §11:1: the yes's support, sure, and the fact the question showed, unreworded."""
    harness = Harness()
    fact = await _confirmed_case(harness)

    def keep(shown: dict[str, Any]) -> str:
        (part,) = shown["parts"]
        return reply(
            action="create",
            wording="User likes windows",
            supports=[
                {
                    "part": part["part"],
                    "direction": "for",
                    "backs_as_worded": True,
                    "how_sure": "likely",
                }
            ],
        )

    observer = harness.observer(
        scout=FakeModelProvider.scripted(reply(findings=[])), commit=_answering(keep)
    )

    outcome = await observer.run()

    assert (outcome.skipped, outcome.processed) == (1, 1)
    (record,) = await harness.plans.observations([address("yes")])
    (finding,) = record.findings
    assert finding.candidate == "effect-1"
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.content == fact
    assert kept.standing is MemoryStanding.CONFIRMED
    (support,) = kept.supports
    assert support.points_at == ConfirmationPart(
        episode=address("yes"),
        asking_activation="asking",
        question=QuestionPart(round="r-ask", part=1),
    )
    assert support.how_sure is ReadingCertainty.SURE


async def test_an_outage_of_the_write_path_waits_and_recovers() -> None:
    """§16:4: a store failure is retried, never recorded as a refusal."""
    harness = Harness()
    await _three(harness)
    ingest = harness.writer.ingest

    async def down(_proposal: object) -> NoReturn:
        msg = "database temporarily unavailable"
        raise MemoryStoreError(msg)

    harness.writer.ingest = down  # type: ignore[method-assign,assignment]  # an outage no fake arms
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create(), _create()),
    )

    first = await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert first.waiting == 1
    assert record.findings[0].outcome is None

    harness.writer.ingest = ingest  # type: ignore[method-assign]  # the outage passes
    harness.clock.advance(timedelta(minutes=1))
    second = await observer.run()

    assert second.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].outcome is not None
    assert record.findings[0].outcome.writes


async def test_a_retry_reads_again_what_a_finding_rests_on_after_the_window_moved() -> None:
    """§16:4, §16:9: a finding held by the budget is committed later, not lost."""
    harness = Harness()
    await _three(harness)
    later = reply(findings=[{"claim": "The user prefers window seats.", "rests_on": ["P1", "P2"]}])

    def keep(shown: dict[str, Any]) -> str:
        assert [part["text"] for part in shown["parts"]] == [_PREFERENCE, "What time is it?"]
        return _create("P1")

    observer = harness.observer(
        scout=FakeModelProvider.scripted(later),
        commit=_answering(keep),
        daily_calls=1,
        related=0,
        per_run=1,
    )
    assert (await observer.run()).held
    await harness.hold(
        episode("four", at=AT + timedelta(minutes=1), text="ok"),
        episode("five", at=AT + timedelta(minutes=2), text="ok"),
    )
    harness.clock.advance(timedelta(hours=25))

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    outcome = record.findings[0].outcome
    assert outcome is not None
    (write,) = outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.placement.reach is PlacementReach.ANYONE, "nothing in the supply narrowed it"


async def test_a_retry_takes_the_supply_its_findings_were_proposed_over() -> None:
    """§12:6: an owner-only episode the scout read narrows the memory, though it left."""
    harness = Harness()
    owner_only = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3)),
        episode("two", at=AT - timedelta(minutes=2), text="ok").model_copy(
            update={"placement": owner_only}
        ),
        episode("three", at=AT - timedelta(minutes=1), text="ok"),
    )
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
        daily_calls=1,
        related=0,
        per_run=1,
    )
    assert (await observer.run()).held
    await harness.hold(
        episode("four", at=AT + timedelta(minutes=1), text="ok"),
        episode("five", at=AT + timedelta(minutes=2), text="ok"),
    )
    harness.clock.advance(timedelta(hours=25))

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    (write,) = outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.placement.reach is PlacementReach.OWNER


async def test_after_a_restart_the_pending_findings_are_proposed_again() -> None:
    """§12:6, §16:4: a supply no process holds any more is read again by a new scout."""
    harness = Harness()
    await _three(harness)
    first = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), daily_calls=1, per_run=1
    )
    assert (await first.run()).held
    harness.clock.advance(timedelta(hours=25))
    scout = FakeModelProvider.scripted(_scout("P1"))
    restarted = harness.observer(
        scout=scout, commit=FakeModelProvider.scripted(_create()), per_run=1
    )

    await restarted.run()

    assert len(scout.calls) == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    (finding,) = record.findings
    assert finding.outcome is not None
    assert finding.outcome.writes


async def test_a_write_the_supply_keeps_off_a_wider_memory_is_retried_until_stuck() -> None:
    """§12:6, §16:5: a blocked write is never dropped: the episode is set aside."""
    harness = Harness()
    owner_only = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3)).model_copy(update={"placement": owner_only}),
        episode("two", at=AT - timedelta(minutes=2), text="ok"),
        episode("three", at=AT - timedelta(minutes=1), text="ok"),
        episode("past", at=SINCE - timedelta(days=1), text="Aisle seats."),
        Memory.model_validate(
            memory(
                "m-aisle", "The user likes aisle seats.", said_support(address("past"))
            ).model_dump()
        ),
    )

    def recheck(shown: dict[str, Any]) -> str:
        (held,) = [one for one in shown["memories"] if "aisle" in one["claim"]]
        return reply(
            action="recheck",
            memory=held["memory"],
            asks="Still aisle?",
            supports=[{"part": "P1", "direction": "against", "how_sure": "likely"}],
        )

    observer = harness.observer(
        scout=FakeModelProvider(reply=_scout("P1")), commit=_answering(recheck), stuck_after=1
    )

    outcome = await observer.run()

    assert outcome.stuck == 1
    aisle = await harness.memory.get("m-aisle")
    assert isinstance(aisle, Memory)
    assert aisle.open_questions == ()


async def test_a_cancelled_call_still_counts_against_the_budget() -> None:
    """§16:9: the call is recorded before it is made."""
    harness = Harness()
    await _three(harness)
    route = _Blocking()
    observer = harness.observer(daily_calls=1)
    observer._scout = route

    running = asyncio.create_task(observer.run())
    await route.entered.wait()
    running.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await running

    assert await harness.plans.observer_calls_since(AT - timedelta(hours=1)) == 1
    assert (await observer.run()).held


async def test_a_plan_store_read_failure_is_an_attempt_that_backs_off() -> None:
    """§16:4-§16:5: a read failing inside an attempt fails that attempt, then sticks."""
    harness = Harness()
    await _three(harness)

    async def failing(_ids: object) -> NoReturn:
        msg = "the plan store could not read"
        raise PlanningError(msg)

    harness.plans.activation_effects = failing  # type: ignore[method-assign]  # no fake arms it
    observer = harness.observer(stuck_after=2)

    first = await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert first.waiting == 1
    assert record.next_attempt_at == AT + timedelta(minutes=1)

    harness.clock.advance(timedelta(minutes=1))
    second = await observer.run()
    assert second.stuck == 1


async def test_the_backoff_doubles_to_its_cap_and_no_further() -> None:
    """§16:4: the cap bounds it however many attempts fail."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(scout=_failing(), stuck_after=100, retry_cap=timedelta(minutes=4))

    waits = []
    for _ in range(50):
        await observer.run()
        (record,) = await harness.plans.observations(["activation:one"])
        assert record.next_attempt_at is not None
        waits.append(record.next_attempt_at - harness.clock.at)
        harness.clock.at = record.next_attempt_at

    assert waits[:4] == [
        timedelta(minutes=1),
        timedelta(minutes=2),
        timedelta(minutes=4),
        timedelta(minutes=4),
    ]
    assert set(waits[3:]) == {timedelta(minutes=4)}


def _keep_confirmed(shown: dict[str, Any]) -> str:
    (part,) = shown["parts"]
    return reply(
        action="create",
        wording="anything",
        supports=[
            {"part": part["part"], "direction": "for", "backs_as_worded": True, "how_sure": "sure"}
        ],
    )


async def test_a_confirmed_candidate_the_policy_asks_about_raises_its_question() -> None:
    """§13:1-§13:2: a ``policy_ask`` on the memory named, resting on the yes's input."""
    harness = Harness(ruling=MemoryDecisionKind.ASK_USER)
    fact = await _confirmed_case(harness)
    await harness.hold(
        episode("past", at=AT - timedelta(days=2), text="I like window seats."),
        Memory.model_validate(memory("m-seat", fact, said_support(address("past"))).model_dump()),
    )
    observer = harness.observer(
        scout=FakeModelProvider(reply=reply(findings=[])), commit=_answering(_keep_confirmed)
    )

    await observer.run()

    (record,) = await harness.plans.observations([address("yes")])
    (finding,) = record.findings
    assert finding.outcome is not None
    assert finding.outcome.ruling is MemoryDecisionKind.ASK_USER
    (write,) = finding.outcome.writes
    assert (write.memory, write.operations) == ("m-seat", (MemoryOperationKind.RAISE_QUESTION,))
    asked = await harness.memory.get("m-seat")
    assert isinstance(asked, Memory)
    (question,) = asked.open_questions
    assert question.kind is OpenQuestionKind.POLICY_ASK
    assert question.rests_on == (InputPart(episode=address("yes")),)


async def test_what_a_failed_commit_wrote_is_merged_into_its_later_outcome() -> None:
    """§16:1: a support written before the attempt failed is recorded when it is decided."""
    harness = Harness()
    await _three(harness)
    await harness.hold(
        episode("past", at=SINCE - timedelta(days=1), text="Window seats."),
        Memory.model_validate(
            memory(
                "m-seat", "The user prefers window seats.", said_support(address("past"))
            ).model_dump()
        ),
    )
    apply = harness.writes.apply
    calls = 0

    async def failing_second(change: MemoryChange) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            msg = "database temporarily unavailable"
            raise MemoryStoreError(msg)
        await apply(change)

    harness.writes.apply = failing_second  # type: ignore[method-assign]  # an outage midway

    decided = 0

    def add_both_then_nothing(shown: dict[str, Any]) -> str:
        nonlocal decided
        decided += 1
        if decided > 1:
            return reply(action="nothing")
        (held,) = [one for one in shown["memories"] if one["claim"].startswith("The user")]
        return reply(
            action="add",
            memory=held["memory"],
            supports=[
                {
                    "part": one["part"],
                    "direction": "for",
                    "backs_as_worded": True,
                    "how_sure": "sure",
                }
                for one in shown["parts"]
            ],
        )

    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1", "P2")),
        commit=_answering(add_both_then_nothing),
        per_run=1,
    )
    await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].outcome is None

    harness.clock.advance(timedelta(minutes=1))
    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    ]


async def test_a_failing_read_of_the_episode_is_an_attempt_and_later_episodes_proceed() -> None:
    """§16:4-§16:5: the first read is inside the attempt."""
    harness = Harness()
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=4)),
        episode("two", at=AT - timedelta(minutes=3), text=""),
        episode("three", at=AT - timedelta(minutes=2)),
        episode("four", at=AT - timedelta(minutes=1)),
    )
    get = harness.memory.get

    async def failing(record_id: str) -> object:
        if record_id == "activation:one":
            msg = "the store could not read"
            raise MemoryStoreError(msg)
        return await get(record_id)

    harness.memory.get = failing  # type: ignore[method-assign,assignment]  # one unreadable row
    observer = harness.observer()

    outcome = await observer.run()

    assert (outcome.waiting, outcome.skipped) == (1, 1)
    one, two = await harness.plans.observations(["activation:one", "activation:two"])
    assert one.attempts[-1].end is ObservationAttemptEnd.FAILED
    assert one.next_attempt_at == AT + timedelta(minutes=1)
    assert two.state is ObservationState.SKIPPED


async def test_an_episode_with_nothing_to_read_is_skipped_after_a_failed_read() -> None:
    """§16:4, §16:7: a read outage first, then the skip rule, never a crash."""
    harness = Harness()
    bare = EpisodicMemory(
        id="harness:bare",
        content="the user said they like tea",
        occurred_at=AT - timedelta(minutes=9),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    await harness.hold(bare)
    await _three(harness, text="")
    get = harness.memory.get
    down = True

    async def flaky(record_id: str) -> object:
        if down and record_id == "harness:bare":
            msg = "the store could not read"
            raise MemoryStoreError(msg)
        return await get(record_id)

    harness.memory.get = flaky  # type: ignore[method-assign,assignment]  # one outage
    observer = harness.observer()

    first = await observer.run()
    down = False
    harness.clock.advance(timedelta(minutes=1))
    second = await observer.run()

    assert first.waiting == 1
    assert second.skipped == 1
    (record,) = await harness.plans.observations(["harness:bare"])
    assert record.state is ObservationState.SKIPPED
    assert [one.end for one in record.attempts] == [
        ObservationAttemptEnd.FAILED,
        ObservationAttemptEnd.FINISHED,
    ]

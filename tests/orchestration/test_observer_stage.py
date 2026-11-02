"""The observer's run: the queue, the limits and the observation record (ADR-0329 §7, §16).

Driven over the canonical fakes with scripted model routes. The reading, the scout's,
framing's and placement's checks and the writes each have their own suite; this one holds
what a run does with them: which episodes are due and in what order, what is recorded as
it goes, and what a failure, the budget, the bound and a second run do (ADR-0346 §2-§6).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, NoReturn

import pytest
import structlog.testing
from observer_support import (
    AT,
    SINCE,
    Harness,
    address,
    episode,
    found,
    framed,
    framing,
    placing,
    remember_call,
    remembered,
    reply,
    said,
    scouted,
)
from structured_support import structured

from ai_assistant.core.errors import (
    MemoryStoreError,
    ModelContentFilterError,
    ModelError,
    PlanningError,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    EpisodicMemory,
    FindingUnwritten,
    InputPart,
    LabelKind,
    Memory,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemorySource,
    MemoryStatus,
    MemoryWrite,
    MemoryWriteMode,
    MemoryWriterName,
    ObservationAttemptEnd,
    ObservationState,
    ObservationWrite,
    ObserverStep,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningLabel,
    Provenance,
    ReplyFailure,
    Role,
    SupportHolder,
    SupportOrigin,
    Validity,
)
from ai_assistant.core.types import Message as MessageType
from ai_assistant.orchestration.observer import RunOutcome
from ai_assistant.orchestration.observer.replies import FramingReplyShape, ScoutReplyShape
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.testing import FakeModelProvider
from ai_assistant.testing.memories import memory, said_support
from ai_assistant.testing.structured import FakeStructuredCompleter, ScriptedReply

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.types import Message

_PREFERENCE = "I prefer window seats when I fly."
_CLAIM = "The user prefers window seats."


async def _three(harness: Harness, *, text: str = _PREFERENCE) -> None:
    """Three episodes, a minute apart: with a window of two, the oldest has left it."""
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3), text=text),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


def _scout(*parts: str) -> str:
    return scouted(found(_CLAIM, *parts))


def _frame(part: str = "P1", wording: str = _CLAIM) -> str:
    return framing(framed(wording, part))


def _nothing() -> str:
    return framing(nothing="The parts do not bear it out.")


async def _held_seat(harness: Harness) -> None:
    """A stored memory stating the claim, from a past episode, held by the owner."""
    support = said_support(address("past")).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    await harness.hold(
        episode("past", at=SINCE - timedelta(days=1), text="Window seats."),
        Memory.model_validate(memory("m-seat", _CLAIM, support).model_dump()),
    )


async def test_an_episode_that_left_the_window_is_committed_and_recorded() -> None:
    """§7:1, ADR-0346 §4-§6, §16:1: scout, framing, a memory written, the record processed."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_frame()),
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    (attempt,) = record.attempts
    assert attempt.end is ObservationAttemptEnd.FINISHED
    # Nothing is stored like it, so there is nothing to place and no placement call.
    assert [call.step for call in attempt.calls] == [ObserverStep.SCOUT, ObserverStep.FRAMING]
    (finding,) = record.findings
    assert finding.annotations is not None
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    assert write.operations == (MemoryOperationKind.CREATE,)
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == _CLAIM
    (support,) = stored.supports
    assert support.origin is SupportOrigin.USER_MESSAGE
    assert support.when == AT - timedelta(minutes=3)
    assert support.added_by.value == "observer"
    assert support.holder is not None, "the writer sets the holder, never the observer"
    assert await harness.plans.observations(["activation:two", "activation:three"]) == ()


async def test_a_framed_memory_like_a_stored_one_is_placed_and_folded() -> None:
    """ADR-0346 §6:1-§6:6: retrieved, placed by one call, proposed as a placed proposal."""
    harness = Harness()
    await _three(harness)
    await _held_seat(harness)
    commit = FakeModelProvider.scripted(
        _frame(), placing(("M1", "restates", "Both say the user prefers window seats."))
    )
    observer = harness.observer(scout=FakeModelProvider.scripted(_scout("P1")), commit=commit)

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    assert [call.step for call in record.attempts[-1].calls] == [
        ObserverStep.SCOUT,
        ObserverStep.FRAMING,
        ObserverStep.PLACEMENT,
    ]
    placement = json.loads(commit.calls[1].messages[-1].content)
    (shown,) = placement["stored"]
    assert shown["wording"] == _CLAIM
    assert shown["held_by"] == ["the user"]
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    ]
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    assert len(seat.supports) == 2
    assert [one for one in await harness.memory.export() if isinstance(one, Memory)] == [seat]


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
    scout = FakeModelProvider.scripted(scouted())
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
    observer = harness.observer(scout=FakeModelProvider.scripted(scouted()))

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
    replies: Iterator[str | Exception] = iter([RuntimeError("down"), scouted()])

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


async def _candidate(harness: Harness) -> None:
    """Three episodes, the oldest recording a candidate planning noted."""
    values: dict[str, Any] = {
        "fact": "The user prefers window seats",
        "why": "travel",
        "rests_on_this_stimulus": True,
    }
    await harness.hold(
        episode(
            "one",
            at=AT - timedelta(minutes=3),
            rounds=(said("r1", "Noted.", calls=(remember_call(**values),)),),
        ),
        episode("two", at=AT - timedelta(minutes=2), text="ok"),
        episode("three", at=AT - timedelta(minutes=1), text="ok"),
    )
    await remembered(harness.plans, "one", "r1", values)


async def test_a_reply_leaving_a_candidate_unaccounted_fails_the_attempt() -> None:
    """ADR-0346 §4:6: refused as a reply that does not parse is, and nothing recorded."""
    harness = Harness()
    await _candidate(harness)
    observer = harness.observer(scout=FakeModelProvider.scripted(scouted()))

    outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings == ()
    assert record.declines == ()
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED


async def test_a_declined_candidate_is_recorded_with_its_reason() -> None:
    """ADR-0346 §4:6: the record keeps each decline and its reason."""
    harness = Harness()
    await _candidate(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(
            scouted(declines=[{"candidate": "C1", "reason": "Said in jest."}])
        )
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    (decline,) = record.declines
    assert (decline.candidate, decline.reason) == ("effect-1", "Said in jest.")


async def test_a_retry_commits_only_the_findings_with_no_outcome() -> None:
    """§16:4: a finding whose outcome is recorded is not committed again."""
    harness = Harness()
    await _three(harness)
    two = scouted(found(_CLAIM, "P1"), found("The user flies.", "P1"))
    answers: Iterator[str | Exception] = iter([_frame(), RuntimeError("down"), _nothing()])

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
    assert [call.step for call in record.attempts[-1].calls] == [ObserverStep.FRAMING]


async def test_the_daily_budget_holds_the_run_and_drops_nothing() -> None:
    """§16:9: a call that would exceed the budget is not made; the episode waits."""
    harness = Harness()
    await _three(harness)
    commit = FakeModelProvider.scripted(_frame())
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


async def test_the_daily_budget_counts_the_placement_calls() -> None:
    """ADR-0346 §10:2: the bound counts every call, a placement's included."""
    harness = Harness()
    await _three(harness)
    await _held_seat(harness)
    commit = FakeModelProvider.scripted(_frame(), placing(("M1", "restates", "The same claim.")))
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), commit=commit, daily_calls=2
    )

    held = await observer.run()

    assert held.held
    assert len(commit.calls) == 1, "the framing call, and no placement past the budget"
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].outcome is None
    assert await harness.plans.observer_calls_since(AT - timedelta(hours=1)) == 2


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
        return MessageType(role=Role.ASSISTANT, content=scouted())


async def test_a_run_asked_for_while_one_runs_does_not_start() -> None:
    """§16:6: at most one run at a time."""
    harness = Harness()
    await _three(harness)
    route = _Blocking()
    observer = harness.observer()
    observer._scout = structured(route)

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
        commit=FakeModelProvider.scripted(_frame()),
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


@pytest.mark.parametrize(
    "answer",
    [
        ScriptedReply(text='Here is what I found: {"findings": []}'),
        ScriptedReply(text=" "),
        ScriptedReply(text='{"findings": []}', failure=ReplyFailure.CUT),
    ],
    ids=["invalid", "empty", "cut"],
)
async def test_a_returned_failure_leaves_the_attempt_pending_as_an_unparsed_reply(
    answer: ScriptedReply,
) -> None:
    """ADR-0354 §9:2, §12:7, #3396: a reply the rule refuses is no proposal, and waits."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(scout=FakeStructuredCompleter.scripted(answer))

    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.WAITING
    assert record.findings == ()
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED
    assert record.next_attempt_at is not None
    (event,) = [one for one in logs if one["event"] == "observer_attempt"]
    assert (event["stage"], event["reason"]) == ("scout", "unparsed")


async def test_a_refusal_fails_the_attempt_as_a_providers_refusal_did() -> None:
    """ADR-0354 §9:2: a returned ``refused`` lands where a raised one did, a model error."""
    harness = Harness()
    await _three(harness)
    refused = ScriptedReply(text=_scout("P1"), failure=ReplyFailure.REFUSED, refusal="no")
    observer = harness.observer(scout=FakeStructuredCompleter.scripted(refused))

    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert (record.state, record.findings) == (ObservationState.WAITING, ())
    (event,) = [one for one in logs if one["event"] == "observer_attempt"]
    assert event["reason"] == ModelContentFilterError.__name__


async def test_each_call_asks_for_its_steps_shape_on_its_route() -> None:
    """ADR-0354 §9:1, §6:2: each step's own shape, on its own route, no ``model=``."""
    harness = Harness()
    await _three(harness)
    scout = FakeStructuredCompleter.scripted(_scout("P1"))
    commit = FakeStructuredCompleter.scripted(_frame())

    await harness.observer(scout=scout, commit=commit).run()

    assert [(one.shape, one.model) for one in scout.calls] == [(ScoutReplyShape, None)]
    assert [(one.shape, one.model) for one in commit.calls] == [(FramingReplyShape, None)]


def _answering(decide: Callable[[dict[str, Any]], str]) -> FakeModelProvider:
    """A route that answers from what it was shown."""

    def answer(messages: Sequence[Message]) -> str:
        return decide(json.loads(messages[-1].content))

    return FakeModelProvider(reply=answer)


async def test_an_ask_from_the_floor_raises_nothing_and_is_recorded() -> None:
    """ADR-0346 §6:8: the outcome records the ask, and no memory gains a question."""
    harness = Harness(ruling=MemoryDecisionKind.ASK_USER)
    await _three(harness)
    await _held_seat(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_frame(), placing(("M1", "restates", "Same."))),
    )

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert outcome.unwritten is FindingUnwritten.ASKED
    assert outcome.ruling is MemoryDecisionKind.ASK_USER
    assert outcome.asked == (_CLAIM,)
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    assert seat.open_questions == ()
    assert len(seat.supports) == 1


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
        commit=FakeModelProvider.scripted(_frame(), _frame()),
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


async def test_a_retry_frames_over_the_same_reading_though_the_window_moved() -> None:
    """ADR-0346 §2:4, §16:9: a finding held by the budget is committed later, not lost."""
    harness = Harness()
    await _three(harness)

    def keep(shown: dict[str, Any]) -> str:
        assert [part["text"] for part in shown["parts"]] == [_PREFERENCE]
        return _frame("P1")

    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=_answering(keep),
        daily_calls=1,
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


async def test_a_memory_takes_the_supply_its_finding_was_proposed_over() -> None:
    """§12:6: an owner-only episode the record points at narrows the memory."""
    harness = Harness()
    owner_only = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    await harness.hold(
        episode("zero", at=AT - timedelta(minutes=4), text="ok").model_copy(
            update={"placement": owner_only}
        ),
        episode(
            "one",
            at=AT - timedelta(minutes=3),
            labels=(PlanningLabel(label="E1", kind=LabelKind.EPISODE, id=address("zero")),),
        ),
        episode("two", at=AT - timedelta(minutes=2), text="ok"),
        episode("three", at=AT - timedelta(minutes=1), text="ok"),
    )
    observer = harness.observer(
        scout=FakeModelProvider.scripted(scouted()),  # the zero episode first
        commit=FakeModelProvider.scripted(_frame("P1")),
        per_run=1,
    )
    await observer.run()
    observer._scout = structured(FakeModelProvider.scripted(_scout("P1")))

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    (finding,) = record.findings
    assert finding.supply is not None
    assert finding.supply.reach is PlacementReach.OWNER
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.placement.reach is PlacementReach.OWNER


async def test_a_narrowing_the_scout_proposed_is_carried_onto_the_memory() -> None:
    """ADR-0346 §5:7: a proposal at its create, within ADR-0217 §4's bounds."""
    harness = Harness()
    await _three(harness)
    narrowed = scouted(
        found(_CLAIM, "P1", narrowing={"reach": "owner", "note": "For the assistant alone."})
    )
    observer = harness.observer(
        scout=FakeModelProvider.scripted(narrowed), commit=FakeModelProvider.scripted(_frame())
    )

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    (write,) = outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.placement.reach is PlacementReach.OWNER
    assert kept.placement.set_by is PlacementSetter.PROPOSED


async def test_after_a_restart_the_pending_findings_are_committed_over_their_supply() -> None:
    """§12:6, §16:4: the supply is on the record, so a new process re-scouts nothing."""
    harness = Harness()
    await _three(harness)
    first = harness.observer(scout=FakeModelProvider.scripted(_scout("P1")), daily_calls=1)
    assert (await first.run()).held
    (held,) = await harness.plans.observations(["activation:one"])
    (pending,) = held.findings
    assert pending.supply is not None
    harness.clock.advance(timedelta(hours=25))
    scout = FakeModelProvider(reply=scouted())
    restarted = harness.observer(scout=scout, commit=FakeModelProvider.scripted(_frame()))

    await restarted.run()

    assert scout.calls == []
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    (finding,) = record.findings
    assert finding.id == pending.id
    assert finding.outcome is not None
    assert finding.outcome.writes


async def test_after_a_restart_a_private_supply_survives_losing_its_source() -> None:
    """§12:6, §16:4: what a held finding's scout read narrows its memory after a restart.

    The leaving episode's record points at an owner-only episode, which the finding's
    supply takes in; the budget holds the finding before framing, and that episode is
    gone before a new process commits it. The memory is placed for the owner alone, and
    nothing is scouted again.
    """
    harness = Harness()
    owner_only = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)
    await harness.hold(
        episode("zero", at=AT - timedelta(minutes=4), text="ok").model_copy(
            update={"placement": owner_only}
        ),
        episode(
            "one",
            at=AT - timedelta(minutes=3),
            labels=(PlanningLabel(label="E1", kind=LabelKind.EPISODE, id=address("zero")),),
        ),
        episode("two", at=AT - timedelta(minutes=2), text="ok"),
        episode("three", at=AT - timedelta(minutes=1), text="ok"),
    )
    first = harness.observer(
        scout=FakeModelProvider.scripted(scouted(), _scout("P1")), daily_calls=2, per_run=1
    )
    await first.run()
    assert (await first.run()).held
    (held,) = await harness.plans.observations(["activation:one"])
    (pending,) = held.findings
    assert pending.supply is not None
    assert pending.supply.reach is PlacementReach.OWNER
    await harness.memory.delete(address("zero"))
    harness.clock.advance(timedelta(hours=25))
    scout = FakeModelProvider(reply=scouted())
    restarted = harness.observer(
        scout=scout, commit=FakeModelProvider.scripted(_frame("P1")), per_run=1
    )

    await restarted.run()

    assert scout.calls == []
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    outcome = record.findings[0].outcome
    assert outcome is not None
    (write,) = outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.placement.reach is PlacementReach.OWNER


async def test_a_pending_finding_whose_supply_was_not_recorded_is_proposed_again() -> None:
    """§12:6: a finding the store held before the field has no supply to start from."""
    harness = Harness()
    await _three(harness)
    first = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), daily_calls=1, per_run=1
    )
    assert (await first.run()).held
    (held,) = await harness.plans.observations(["activation:one"])
    legacy = tuple(one.model_copy(update={"supply": None}) for one in held.findings)
    await harness.plans.write_observation(
        held.model_copy(update={"findings": legacy}), expected_revision=held.revision
    )
    harness.clock.advance(timedelta(hours=25))
    scout = FakeModelProvider.scripted(_scout("P1"))
    restarted = harness.observer(
        scout=scout, commit=FakeModelProvider.scripted(_frame()), per_run=1
    )

    await restarted.run()

    assert len(scout.calls) == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    (finding,) = record.findings
    assert finding.supply is not None
    assert finding.outcome is not None
    assert finding.outcome.writes


async def test_a_cancelled_call_still_counts_against_the_budget() -> None:
    """§16:9: the call is recorded before it is made."""
    harness = Harness()
    await _three(harness)
    route = _Blocking()
    observer = harness.observer(daily_calls=1)
    observer._scout = structured(route)

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


def _two_memories() -> str:
    return framing(
        framed(_CLAIM, "P1"),
        framed("The user flies.", "P1"),
    )


async def test_what_a_failed_commit_wrote_is_merged_into_its_later_outcome() -> None:
    """§16:1: a memory written before the attempt failed is recorded when it is decided."""
    harness = Harness()
    await _three(harness)
    ingest = harness.writer.ingest
    calls = 0

    async def failing_second(proposal: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            msg = "database temporarily unavailable"
            raise MemoryStoreError(msg)
        return await ingest(proposal)

    harness.writer.ingest = failing_second  # type: ignore[method-assign]  # an outage midway
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_two_memories()),
        per_run=1,
    )
    await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].outcome is None
    (written,) = record.findings[0].written
    assert written.operations == (MemoryOperationKind.CREATE,), (
        "what landed is on the record, not only in the process"
    )

    harness.clock.advance(timedelta(minutes=1))
    framing_again = FakeModelProvider.scripted()
    restarted = harness.observer(commit=framing_again, per_run=1)
    await restarted.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        (written.memory, (MemoryOperationKind.CREATE,)),
        ("observed:2", (MemoryOperationKind.CREATE,)),
    ]
    assert framing_again.calls == [], "the retry resumes from what framing kept"
    assert record.findings[0].written == (), "the outcome clears what it merged"
    assert record.findings[0].framed == ()


async def test_a_retry_resumes_after_the_memories_already_written() -> None:
    """ADR-0329 §16:4: resumed after the memory already written, nothing framed twice."""
    harness = Harness()
    await _three(harness)
    ingest = harness.writer.ingest
    calls = 0

    async def failing_second(proposal: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            msg = "database temporarily unavailable"
            raise MemoryStoreError(msg)
        return await ingest(proposal)

    harness.writer.ingest = failing_second  # type: ignore[method-assign]  # an outage midway
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_two_memories()),
    )
    await observer.run()
    harness.clock.advance(timedelta(minutes=1))

    restarted = harness.observer(commit=FakeModelProvider.scripted())
    await restarted.run()

    stored = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert sorted(one.content for one in stored) == ["The user flies.", _CLAIM]
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED


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


async def test_an_outcome_whose_record_failed_to_be_written_is_not_committed_again() -> None:
    """§16:1, §16:4: the memory written stays the finding's outcome, never decided anew."""
    harness = Harness()
    await _three(harness)
    write_observation = harness.plans.write_observation
    refused = False

    async def failing_outcome(record: Any, *, expected_revision: int) -> Any:
        nonlocal refused
        if not refused and any(one.outcome is not None for one in record.findings):
            refused = True
            msg = "the plan store could not write"
            raise PlanningError(msg)
        return await write_observation(record, expected_revision=expected_revision)

    harness.plans.write_observation = failing_outcome  # type: ignore[method-assign]  # one outage
    commit = FakeModelProvider.scripted(_frame(), _nothing())
    observer = harness.observer(scout=FakeModelProvider.scripted(_scout("P1")), commit=commit)

    await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].outcome is None

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [one.operations for one in outcome.writes] == [(MemoryOperationKind.CREATE,)]
    assert len(commit.calls) == 1, "the finding is not committed again"
    created = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert len(created) == 1


async def test_a_landed_write_whose_record_failed_to_be_written_reaches_the_outcome() -> None:
    """§16:1: the plan store refusing the write that carries ``written`` loses nothing.

    The run ends at the failed write (§16:6's backstop), and the next attempt in this
    process starts from the finding as it was built, so a framing keeping nothing the
    second time still records the memory the first one created.
    """
    harness = Harness()
    await _three(harness)
    write_observation = harness.plans.write_observation
    refused = False

    async def failing_checkpoint(record: Any, *, expected_revision: int) -> Any:
        nonlocal refused
        if not refused and any(one.written for one in record.findings):
            refused = True
            msg = "the plan store could not write"
            raise PlanningError(msg)
        return await write_observation(record, expected_revision=expected_revision)

    harness.plans.write_observation = failing_checkpoint  # type: ignore[method-assign]  # one outage
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_frame(), _nothing()),
    )

    await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].written == ()
    assert record.findings[0].outcome is None
    created = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert len(created) == 1

    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        (created[0].id, (MemoryOperationKind.CREATE,))
    ]


async def test_a_stuck_episode_keeps_what_its_failed_commit_wrote_for_a_re_run() -> None:
    """§16:1, §16:5: set aside with its writes on the record, so a re-run records them."""
    harness = Harness()
    await _three(harness)
    ingest = harness.writer.ingest
    calls = 0

    async def failing_second(proposal: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            msg = "database temporarily unavailable"
            raise MemoryStoreError(msg)
        return await ingest(proposal)

    harness.writer.ingest = failing_second  # type: ignore[method-assign]  # an outage midway
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_two_memories()),
        per_run=1,
        stuck_after=1,
    )
    assert (await observer.run()).stuck == 1
    (record,) = await harness.plans.observations(["activation:one"])
    (written,) = record.findings[0].written
    assert written.operations == (MemoryOperationKind.CREATE,)
    # The explicit re-run §16:5 names, in a process that never held the episode.
    await harness.plans.write_observation(
        record.model_copy(update={"state": ObservationState.WAITING}),
        expected_revision=record.revision,
    )
    restarted = harness.observer(commit=FakeModelProvider.scripted(), per_run=1)

    await restarted.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        (written.memory, (MemoryOperationKind.CREATE,)),
        ("observed:2", (MemoryOperationKind.CREATE,)),
    ]


async def test_a_run_cancelled_after_a_write_landed_records_it_on_the_retry() -> None:
    """§16:1: the proposal was on the record before it was sent, so the retry reads it back."""
    harness = Harness()
    await _three(harness)
    ingest = harness.writer.ingest
    landed = False

    async def cancelled_after(proposal: Any) -> Any:
        nonlocal landed
        done = await ingest(proposal)
        if not landed:
            landed = True
            raise asyncio.CancelledError
        return done

    harness.writer.ingest = cancelled_after  # type: ignore[method-assign]  # cancelled once
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_frame()),
    )
    with contextlib.suppress(asyncio.CancelledError):
        await observer.run()
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.findings[0].outcome is None
    created = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert len(created) == 1

    harness.writer.ingest = ingest  # type: ignore[method-assign]  # nothing more to cancel

    restarted = harness.observer(commit=FakeModelProvider.scripted())
    await restarted.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        (created[0].id, (MemoryOperationKind.CREATE,))
    ]
    stored = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert stored == created, "nothing is proposed a second time"


async def test_a_placement_reply_that_does_not_parse_fails_the_attempt() -> None:
    """ADR-0346 §6:2: a placement leaving a memory unplaced is refused whole."""
    harness = Harness()
    await _three(harness)
    await _held_seat(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_frame(), reply(relations=[])),
    )

    outcome = await observer.run()

    assert outcome.waiting == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.attempts[-1].end is ObservationAttemptEnd.FAILED
    assert record.findings[0].outcome is None
    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    assert len(seat.supports) == 1, "nothing is written on a placement that did not parse"


async def test_a_retry_takes_a_source_narrowed_since_the_finding_was_proposed() -> None:
    """§12:6: every attempt's reading narrows the pending findings' supply, never widens."""
    harness = Harness()
    await _three(harness)
    first = harness.observer(scout=FakeModelProvider.scripted(_scout("P1")), daily_calls=1)
    assert (await first.run()).held
    leaving = await harness.memory.get("activation:one")
    assert isinstance(leaving, EpisodicMemory)
    owner_only = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=AT)
    await harness.memory.write_atomic(
        [
            MemoryWrite(
                record=leaving.model_copy(update={"placement": owner_only}),
                mode=MemoryWriteMode.IF_UNCHANGED,
                expected_revision=leaving.revision,
            )
        ]
    )
    harness.clock.advance(timedelta(hours=25))
    restarted = harness.observer(commit=FakeModelProvider.scripted(_frame()))

    await restarted.run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    (write,) = outcome.writes
    kept = await harness.memory.get(write.memory)
    assert isinstance(kept, Memory)
    assert kept.placement.reach is PlacementReach.OWNER


async def test_a_budget_of_one_call_a_day_still_completes_a_placed_finding() -> None:
    """§16:9: each step is kept, so every window's one call moves the finding on."""
    harness = Harness()
    await _three(harness)
    await _held_seat(harness)
    commit = FakeModelProvider.scripted(_frame(), placing(("M1", "restates", "Same.")))
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")), commit=commit, daily_calls=1
    )

    for _ in range(3):
        await observer.run()
        harness.clock.advance(timedelta(hours=24, seconds=1))
    await observer.run()

    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    assert len(commit.calls) == 2, "framing once, then the placement, each in its own day"
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [one.memory for one in outcome.writes] == ["m-seat"]


async def test_a_question_a_memory_raised_is_not_raised_again_by_a_retry() -> None:
    """§16:4: the memory whose recheck landed is done, so no second question is asked."""
    harness = Harness()
    await _three(harness)
    await _held_seat(harness)
    ingest = harness.writer.ingest
    calls = 0

    async def failing_second(proposal: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            msg = "database temporarily unavailable"
            raise MemoryStoreError(msg)
        return await ingest(proposal)

    harness.writer.ingest = failing_second  # type: ignore[method-assign]  # an outage midway
    two = framing(framed(_CLAIM, "P1"), framed("The user flies.", "P1"))
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(two, placing(("M1", "recheck", "Still the window?"))),
    )
    await observer.run()
    harness.clock.advance(timedelta(minutes=1))
    harness.writer.ingest = ingest  # type: ignore[method-assign]  # the outage passes

    await harness.observer(commit=FakeModelProvider.scripted()).run()

    seat = await harness.memory.get("m-seat")
    assert isinstance(seat, Memory)
    assert len(seat.open_questions) == 1


async def test_a_pending_findings_earlier_writes_survive_a_part_that_no_longer_resolves() -> None:
    """§16:1: a finding from before ``framed`` keeps its writes whatever this commit finds."""
    harness = Harness()
    await _three(harness)
    first = harness.observer(scout=FakeModelProvider.scripted(_scout("P1")), daily_calls=1)
    assert (await first.run()).held
    (held,) = await harness.plans.observations(["activation:one"])
    written = ObservationWrite(memory="observed:old", operations=(MemoryOperationKind.CREATE,))
    stray = InputPart(episode=address("gone"))
    pending = held.findings[0].model_copy(
        update={"written": (written,), "rests_on": (*held.findings[0].rests_on, stray)}
    )
    await harness.plans.write_observation(
        held.model_copy(update={"findings": (pending,)}), expected_revision=held.revision
    )
    harness.clock.advance(timedelta(hours=25))

    await harness.observer(commit=FakeModelProvider.scripted()).run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert outcome.writes == (written,)


async def test_a_pending_supersession_from_before_framed_records_what_it_retired() -> None:
    """§16:1: the create alone on the record, its retirement read off the store."""
    harness = Harness()
    await _three(harness)
    old = memory("m-old", "The user prefers aisle seats.", said_support(address("one")))
    replacement = memory(
        "m-new", _CLAIM, said_support(address("one"), added_at=AT + timedelta(seconds=1))
    )
    replacement = replacement.model_copy(
        update={
            "operations": (replacement.operations[0].model_copy(update={"replaces": ("m-old",)}),)
        }
    )
    ended = old.model_copy(
        update={
            "operations": (
                *old.operations,
                MemoryOperation(
                    kind=MemoryOperationKind.END,
                    cites=old.supports[0].points_at,
                    at=AT,
                    by=MemoryWriterName.OBSERVER,
                    successor="m-new",
                ),
            ),
            "status": MemoryStatus.ENDED,
            "validity": Validity(valid_until=AT),
        }
    )
    await harness.hold(
        Memory.model_validate(ended.model_dump()), Memory.model_validate(replacement.model_dump())
    )
    first = harness.observer(scout=FakeModelProvider.scripted(_scout("P1")), daily_calls=1)
    assert (await first.run()).held
    (held,) = await harness.plans.observations(["activation:one"])
    created = ObservationWrite(memory="m-new", operations=(MemoryOperationKind.CREATE,))
    pending = held.findings[0].model_copy(update={"written": (created,)})
    await harness.plans.write_observation(
        held.model_copy(update={"findings": (pending,)}), expected_revision=held.revision
    )
    harness.clock.advance(timedelta(hours=25))

    await harness.observer(commit=FakeModelProvider.scripted(_nothing())).run()

    (record,) = await harness.plans.observations(["activation:one"])
    outcome = record.findings[0].outcome
    assert outcome is not None
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        ("m-new", (MemoryOperationKind.CREATE,)),
        ("m-old", (MemoryOperationKind.END,)),
    ]

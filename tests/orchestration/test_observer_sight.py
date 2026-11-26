"""The observer reads for an ended work through that work's sight (ADR-0383 §6:7, §7:7).

For each episode a run takes, code makes the producer's sight from the facts and senders
the episode records (``Sight.of_producer``), and every read and write of the run is of a
store the holder binds to it (§7:6, §7:7); the finding of what is due reads unbound
(§7:12). Driven over the canonical fakes, built to withhold or to count (§7:10):

- **withholding**, an owner's episode is read, placed and written as today, and an
  unidentified sender's, which its sight does not see, is read as never written: no model
  call, nothing recorded, and it stays due (setting it aside is §7:13's, not built);
- **counting**, every run is as today, and each read writes its ``sight_counted`` event
  with the reader ``producer`` (§11:1), counting for an unidentified sender's episode what
  would have been withheld (§7:13's last sentence).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog.testing
from identity_support import recorded_facts
from observer_support import (
    AT,
    SINCE,
    Harness,
    address,
    episode,
    found,
    framed,
    framing,
    limits,
    placing,
    scouted,
)
from structured_support import structured

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    EpisodicMemory,
    InputSender,
    Memory,
    MemoryOperationKind,
    ObservationAttempt,
    ObservationAttemptEnd,
    ObservationRecord,
    ObservationState,
    RecordHome,
    Sight,
    SightMode,
    SightReader,
    SupportHolder,
    Sureness,
)
from ai_assistant.orchestration.observer import Observer, RunOutcome
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_FRAMING_PROMPT,
    OBSERVER_PLACEMENT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.observer.stage import Due, DueRecord
from ai_assistant.orchestration.understanding import RecentEpisodes
from ai_assistant.testing import FakeModelProvider, FakePersonModelStore, default_prompt
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

_PREFERENCE: Final = "I prefer window seats when I fly."
_CLAIM: Final = "The user prefers window seats."
_UNIDENTIFIED: Final = InputSender(person=None, level=Sureness.NONE)
_SUBJECT: Final = address("one")


def _unidentified(held: EpisodicMemory) -> EpisodicMemory:
    """``held`` as an unidentified sender's work: the chat's input from no one known.

    Its facts as admission records them for such an input (ADR-0368 §3:3): for whoever the
    connection belongs to, the owner, carrying no authority; its home the owner's (ADR-0383
    §4:4).
    """
    processing = held.processing_record
    assert processing is not None
    trigger = processing.trigger.model_copy(update={"senders": (_UNIDENTIFIED,)})
    return held.model_copy(
        update={
            "processing_record": processing.model_copy(
                update={"trigger": trigger, "facts": recorded_facts(trigger)}
            )
        }
    )


async def _seeded(harness: Harness, *, stranger: bool = False) -> None:
    """Three episodes, a minute apart, the oldest out of a window of two; and a stored
    memory of the owner's stating the claim, so the oldest's finding is placed."""
    one = episode("one", at=AT - timedelta(minutes=3), text=_PREFERENCE)
    support = said_support(address("past")).model_copy(
        update={"holder": SupportHolder.person(OWNER_PERSON_ID)}
    )
    await harness.hold(
        _unidentified(one) if stranger else one,
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
        episode("past", at=SINCE - timedelta(days=1), text="Window seats."),
        Memory.model_validate(memory("m-seat", _CLAIM, support).model_dump()),
    )


def _routes() -> tuple[FakeModelProvider, FakeModelProvider]:
    """The scout's and the commit step's routes: a finding, a framing, a placement."""
    scout = FakeModelProvider.scripted(scouted(found(_CLAIM, "P1")))
    commit = FakeModelProvider.scripted(
        framing(framed(_CLAIM, "P1")),
        placing(("M1", "restates", "Both say the user prefers window seats.")),
    )
    return scout, commit


async def _run(
    mode: SightMode, *, stranger: bool = False
) -> tuple[
    Harness, RunOutcome, FakeModelProvider, FakeModelProvider, list[MutableMapping[str, Any]]
]:
    """One run over the seeded stores built to ``mode``, its logs captured."""
    harness = Harness(sight_mode=mode)
    await _seeded(harness, stranger=stranger)
    people = FakePersonModelStore(now=harness.clock, sight_mode=mode)
    scout, commit = _routes()
    observer = harness.observer(scout=scout, commit=commit, person_model=people)
    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()
    return harness, outcome, scout, commit, logs


def _counted(logs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [one for one in logs if one["event"] == "sight_counted"]


def _shown(provider: FakeModelProvider) -> list[list[tuple[str, str]]]:
    """What each call showed the model, message by message."""
    return [[(one.role.value, one.content) for one in call.messages] for call in provider.calls]


# --- the producer's sight (§6:7) -------------------------------------------------------


def test_an_owners_episode_is_read_by_the_owners_bound_alone() -> None:
    """§6:4, §6:7: the facts' bound for whom, the identified sender's, no activation."""
    held = episode("one").processing_record
    assert held is not None
    sight = Sight.of_producer(held.facts_now, held.trigger.senders)

    assert sight.reader is SightReader.PRODUCER
    assert sight.activation is None
    assert sight.codes == ("person_owner",)
    assert sight.sees(RecordHome.owners())
    assert sight.sees(RecordHome.shared())


def test_an_unidentified_senders_episode_sees_no_home() -> None:
    """§6:4, §6:7: an anyone bound beside the owner's, so no home is seen."""
    held = _unidentified(episode("one")).processing_record
    assert held is not None
    sight = Sight.of_producer(held.facts_now, held.trigger.senders)

    assert sorted(sight.codes) == ["anyone", "person_owner"]
    assert not sight.sees(RecordHome.owners())
    assert not sight.sees(RecordHome.shared())


# --- withholding (§7:2) ----------------------------------------------------------------


async def test_withholding_an_owners_episode_is_read_placed_and_written_as_today() -> None:
    """§7:7: the reading, the person's fields, retrieval, the placement and the writes are
    each a bound store's, and for the owner's episode each answers as the counting build
    does: the same calls showing the models the same messages, the same writes."""
    count, counted, count_scout, count_commit, _ = await _run(SightMode.COUNT)
    held, outcome, scout, commit, _ = await _run(SightMode.WITHHOLD)

    assert outcome == counted
    assert outcome.processed == 1
    assert _shown(scout) == _shown(count_scout)
    assert _shown(commit) == _shown(count_commit)
    (record,) = await held.plans.observations([_SUBJECT])
    assert record.state is ObservationState.PROCESSED
    assert record.home == RecordHome.owners(), "the episode's own home (§4:2)"
    (finding,) = record.findings
    assert finding.outcome is not None
    assert [(one.memory, one.operations) for one in finding.outcome.writes] == [
        ("m-seat", (MemoryOperationKind.ADD_SUPPORT,))
    ]
    (seat,) = [one for one in await held.memory.export() if isinstance(one, Memory)]
    (counted_seat,) = [one for one in await count.memory.export() if isinstance(one, Memory)]
    assert len(seat.supports) == len(counted_seat.supports) == 2


async def test_withholding_an_unidentified_senders_episode_is_read_as_never_written() -> None:
    """§7:2, §7:13: its sight sees nothing, so its run reads nothing of it. No model is
    called, nothing is recorded, nothing is written, and it stays due: setting it aside
    is §7:13's, which this build does not make. Later episodes are not held back."""
    harness, outcome, scout, commit, logs = await _run(SightMode.WITHHOLD, stranger=True)

    assert outcome == RunOutcome()
    assert (scout.calls, commit.calls) == ([], [])
    assert await harness.plans.observations([_SUBJECT]) == ()
    (seat,) = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    assert len(seat.supports) == 1, "nothing written onto the owner's memory"
    unrecorded = [one for one in logs if one.get("result") == "unrecorded"]
    assert unrecorded == [
        {
            "event": "observer_attempt",
            "stage": "attempt",
            "result": "unrecorded",
            "reason": "unseen",
            "log_level": "info",
        }
    ]
    queue = await harness.observer().due(())
    assert Due(episode=_SUBJECT, record=None) in queue


async def test_withholding_a_record_the_sight_does_not_see_is_left_as_it_was() -> None:
    """§7:5, §7:12: the due-finding hands the run the record's state and revision alone,
    and the run reads the record through the plan store bound to the episode's sight: one
    that sight does not see is never read for it, and never written again."""
    harness = Harness(sight_mode=SightMode.WITHHOLD)
    await _seeded(harness, stranger=True)
    earlier = await harness.plans.write_observation(
        ObservationRecord(
            episode=_SUBJECT,
            home=RecordHome.owners(),
            state=ObservationState.WAITING,
            attempts=(
                ObservationAttempt(
                    started_at=AT - timedelta(hours=1), end=ObservationAttemptEnd.FAILED
                ),
            ),
        ),
        expected_revision=0,
    )
    scout, commit = _routes()
    observer = harness.observer(scout=scout, commit=commit)

    queue = await observer.due(())
    outcome = await observer.run()

    assert Due(_SUBJECT, DueRecord(ObservationState.WAITING, earlier.revision)) in queue
    assert outcome == RunOutcome()
    assert scout.calls == []
    assert await harness.plans.observations([_SUBJECT]) == (earlier,)


async def test_withholding_an_episode_that_records_no_facts_is_not_read() -> None:
    """§6:7: an episode with no processing record records no facts, so its sight is an
    anyone bound alone, which sees nothing: it is not read, so not skipped by rule as the
    counting build skips it (ADR-0329 §16:7), and it stays due (§7:13 is not built)."""
    bare = episode("bare", at=AT - timedelta(minutes=9)).model_copy(
        update={"processing_record": None}
    )
    results: dict[SightMode, RunOutcome] = {}
    for mode in SightMode:
        harness = Harness(sight_mode=mode)
        await _seeded(harness)
        await harness.hold(bare)
        observer = harness.observer(per_run=1)
        results[mode] = await observer.run()
        held = await harness.plans.observations([bare.id])
        assert [one.state for one in held] == (
            [ObservationState.SKIPPED] if mode is SightMode.COUNT else []
        )

    assert results == {
        SightMode.COUNT: RunOutcome(skipped=1),
        SightMode.WITHHOLD: RunOutcome(),
    }


# --- counting (§11:1) ------------------------------------------------------------------


@pytest.mark.parametrize("stranger", [False, True], ids=["owner", "unidentified"])
async def test_counting_every_run_is_as_today_and_each_read_is_the_producers(
    stranger: bool,
) -> None:
    """§7:13's last sentence, §11:1: in the counting build an episode is processed as
    today whatever its sight sees, and each read the run makes writes one event, reader
    ``producer``, counting what the sight would have withheld."""
    harness, outcome, scout, _, logs = await _run(SightMode.COUNT, stranger=stranger)

    assert outcome.processed == 1
    assert len(scout.calls) == 1
    (record,) = await harness.plans.observations([_SUBJECT])
    assert record.state is ObservationState.PROCESSED
    counted = _counted(logs)
    assert counted
    assert {one["reader"] for one in counted} == {"producer"}
    stores = {one["store"] for one in counted}
    # The person's fields are read for a person's episode alone (ADR-0338 §2:5).
    assert stores >= ({"memory", "plans"} if stranger else {"memory", "plans", "person_model"})
    withheld = sum(one["other_home"] + one["no_home"] + one["sees_nothing"] for one in counted)
    if stranger:
        assert {tuple(one["bounds"]) for one in counted} == {("anyone", "person_owner")}
        assert withheld > 0, "the episode itself, at least, would have been withheld"
        assert all(one["other_home"] == one["no_home"] == 0 for one in counted)
    else:
        assert {tuple(one["bounds"]) for one in counted} == {("person_owner",)}
        assert withheld == 0


async def test_the_due_finding_and_the_budget_read_unbound() -> None:
    """§7:12, §8:5: the window, the episodes paged, their records and the calls in the last
    day are read by no sight, so they write no event; the pin pass, tied to no ended
    work, reads unbound too (milestone 22's B9)."""
    harness = Harness()
    await _seeded(harness)
    observer = harness.observer(person_model=FakePersonModelStore(now=harness.clock), daily_calls=0)

    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()

    assert outcome.held
    members = [(one["store"], one["member"]) for one in _counted(logs)]
    assert ("memory", "episodes") not in members
    assert ("plans", "observer_calls_since") not in members
    assert ("person_model", "export") not in members
    assert ("plans", "observations") in members, "the run reads its record bound"


async def test_an_observer_built_with_no_holder_binds_as_the_roots_does() -> None:
    """A caller outside the composition root hands no holder: one is built over the very
    stores and writer it hands, so a withholding build reads an owner's episode as the
    root's holder does, and an unidentified sender's as never written."""
    for stranger, processed in ((False, 1), (True, 0)):
        harness = Harness(sight_mode=SightMode.WITHHOLD)
        await _seeded(harness, stranger=stranger)
        scout, commit = _routes()
        observer = Observer(
            scout=structured(scout),
            commit=structured(commit),
            memory=harness.memory,
            writes=harness.writes,
            plans=harness.plans,
            stories=harness.stories,
            episodes=RecentEpisodes(memory=harness.memory, limit=2),
            limits=limits(),
            scout_prompt=default_prompt(OBSERVER_SCOUT_PROMPT),
            framing_prompt=default_prompt(OBSERVER_FRAMING_PROMPT),
            placement_prompt=default_prompt(OBSERVER_PLACEMENT_PROMPT),
            now=harness.clock,
        )

        outcome = await observer.run()

        assert outcome.processed == processed
        assert len(commit.calls) == 2 * processed, "framing and placement, or nothing"


def test_an_observer_with_no_holder_and_no_story_store_is_refused() -> None:
    harness = Harness()
    with pytest.raises(ValueError, match="story store"):
        Observer(
            scout=structured(FakeModelProvider.scripted()),
            commit=structured(FakeModelProvider.scripted()),
            memory=harness.memory,
            writes=harness.writes,
            plans=harness.plans,
            episodes=RecentEpisodes(memory=harness.memory, limit=2),
            limits=limits(),
            scout_prompt=default_prompt(OBSERVER_SCOUT_PROMPT),
            framing_prompt=default_prompt(OBSERVER_FRAMING_PROMPT),
            placement_prompt=default_prompt(OBSERVER_PLACEMENT_PROMPT),
            now=harness.clock,
        )

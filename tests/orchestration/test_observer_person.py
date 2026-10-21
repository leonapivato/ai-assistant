"""What the observer reads and writes of the person model (ADR-0338 §9, ADR-0342 §5:6).

Driven over the canonical fakes, the person-model store's among them, with scripted
model routes: no test makes a model call or contacts a hub. Where no store is wired the
observer is as it was (§11:2); where one is, the leaving episode's person's five fields
reach both steps (§9:1), the scout's suggestions and restating findings are recorded and
kept off memory (§9:2-§9:3), the commit step's style mark and pin suggestion are
recorded (§9:4-§9:5), every run confirms the pins first (§9:6), and a retirement is ruled
against the standing its memory's pins give it (§9:9-§9:10). No test asserts a
template's wording (ADR-0334 §9:1): the flags each instruction was rendered under, and
the steps' data, are tested instead.
"""

from __future__ import annotations

import contextlib
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
from observer_support import AT, Harness, address, episode, reply, said

from ai_assistant.core.errors import (
    MemoryStoreError,
    MemoryStoreStaleError,
    PersonModelStoreError,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    BeliefBand,
    ChannelIdentity,
    FindingUnwritten,
    InputPart,
    Memory,
    MemoryChange,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRetirement,
    MemoryStanding,
    MemoryStatus,
    MemoryWriterName,
    ObservationState,
    OpenQuestionKind,
    PersonActHow,
    PersonModelAct,
    PersonModelWrite,
    PinPart,
    ProfileField,
    ReadingCertainty,
    SuggestionKind,
    SupportDirection,
    SupportOrigin,
)
from ai_assistant.orchestration.observer.commit import Checked, Create, RaiseQuestion
from ai_assistant.orchestration.observer.person import PinConfirmations
from ai_assistant.orchestration.observer.prompts import (
    OBSERVER_COMMIT_PROMPT,
    OBSERVER_SCOUT_PROMPT,
)
from ai_assistant.orchestration.observer.writing import FindingWriter
from ai_assistant.orchestration.writes import MemoryWriteStage
from ai_assistant.testing import FakeModelProvider, default_prompt
from ai_assistant.testing.memories import (
    confirmed_support,
    legacy_support,
    memory,
    said_support,
)
from ai_assistant.testing.person_model import FakePersonModelStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import Message, PersonModel

_PANEL = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
_CLAIM = "The user prefers window seats."
_DOORBELL = ChannelIdentity(channel_type="doorbell", instance_id="front")


async def _three(harness: Harness, *, channel: ChannelIdentity | None = None) -> None:
    """Three episodes, a minute apart: with a window of two, ``one`` has left it."""
    extra: dict[str, Any] = {} if channel is None else {"channel": channel}
    await harness.hold(
        episode(
            "one",
            at=AT - timedelta(minutes=3),
            text="I prefer window seats when I fly.",
            rounds=[said("r1", "Noted: window seats.", at=AT - timedelta(minutes=3))],
            **extra,
        ),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


def _store(harness: Harness) -> FakePersonModelStore:
    return FakePersonModelStore(now=harness.clock)


def _create(**extra: Any) -> str:
    return reply(
        action="create",
        wording=_CLAIM,
        supports=[{"part": "P1", "direction": "for", "backs_as_worded": True, "how_sure": "sure"}],
        **extra,
    )


def _payload(messages: Sequence[Message]) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(messages[1].content)
    return loaded


async def _model(store: FakePersonModelStore) -> PersonModel:
    model = await store.read(OWNER_PERSON_ID)
    assert model is not None
    return model


# --- inert without a store (§11:2) ----------------------------------------------------


async def test_without_a_store_each_step_is_as_it_was_and_reads_no_new_output() -> None:
    """§11:2: no person flag, no ``person`` key, and the new output is never read."""
    harness = Harness()
    await _three(harness)
    scout = FakeModelProvider.scripted(
        reply(
            findings=[
                {
                    "claim": _CLAIM,
                    "rests_on": ["P1"],
                    "restates": {"field": "name", "value": "Leo"},
                }
            ],
            suggestions=[{"field": "name", "value": "Leo", "part": "P1"}],
        )
    )
    commit = FakeModelProvider.scripted(_create(style=True, pin=True))
    observer = harness.observer(scout=scout, commit=commit)

    outcome = await observer.run()

    assert (outcome.processed, outcome.pinned) == (1, 0)
    for provider, declaration in ((scout, OBSERVER_SCOUT_PROMPT), (commit, OBSERVER_COMMIT_PROMPT)):
        (call,) = provider.calls
        unflagged = default_prompt(declaration).render(flags={"person": False})
        assert call.messages[0].content == unflagged
        assert "person" not in _payload(call.messages)
    # The restating marker was not read: the finding was committed as any other.
    (record,) = await harness.plans.observations([address("one")])
    (finding,) = record.findings
    assert finding.outcome is not None
    assert finding.outcome.writes


async def test_an_episode_that_is_no_persons_is_given_no_fields() -> None:
    """§2:5, §7:4: a doorbell's input is no person's, so its steps are as they were."""
    harness = Harness()
    store = _store(harness)
    await _three(harness, channel=_DOORBELL)
    scout = FakeModelProvider.scripted(
        reply(
            findings=[{"claim": _CLAIM, "rests_on": ["P1"]}],
            suggestions=[{"field": "name", "value": "Leo", "part": "P1"}],
        )
    )
    commit = FakeModelProvider.scripted(_create(style=True))
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    await observer.run()

    for provider, declaration in ((scout, OBSERVER_SCOUT_PROMPT), (commit, OBSERVER_COMMIT_PROMPT)):
        (call,) = provider.calls
        assert call.messages[0].content == default_prompt(declaration).render(
            flags={"person": False}
        )
        assert "person" not in _payload(call.messages)
    model = await _model(store)
    assert (model.suggestions, model.style_marks) == ((), ())


# --- the five fields reach both steps (§9:1) ------------------------------------------


async def test_both_steps_are_given_the_persons_five_fields_first() -> None:
    """§7:4, §9:1, §3:9: the fields, each set or not, under the person flag."""
    harness = Harness()
    store = _store(harness)
    await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=_PANEL)
    await _three(harness)
    scout = FakeModelProvider.scripted(reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"]}]))
    commit = FakeModelProvider.scripted(_create())
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    await observer.run()

    fields = {
        "name": "Robin Vale",
        "address": None,
        "assistant_name": None,
        "time_zone": None,
        "language": None,
    }
    for provider, declaration in ((scout, OBSERVER_SCOUT_PROMPT), (commit, OBSERVER_COMMIT_PROMPT)):
        (call,) = provider.calls
        assert call.messages[0].content == default_prompt(declaration).render(
            flags={"person": True}
        )
        payload = _payload(call.messages)
        assert next(iter(payload)) == "person", "ahead of what changes from call to call"
        assert payload["person"] == fields


async def test_a_store_that_cannot_be_read_fails_the_attempt_before_any_call() -> None:
    """§9:3: no step decides without the fields it is owed; the episode waits."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted()
    observer = harness.observer(
        scout=scout, person_model=cast("PersonModelStore", _FailingReads(store))
    )

    outcome = await observer.run()

    assert outcome.waiting == 1
    assert scout.calls == []
    (record,) = await harness.plans.observations([address("one")])
    assert record.state is ObservationState.WAITING


class _FailingReads:
    """The fake person-model store, whose ``read`` alone fails as a store fault would."""

    def __init__(self, store: FakePersonModelStore) -> None:
        self._store = store

    async def read(self, person_id: str) -> PersonModel | None:
        msg = "the person-model store cannot be read"
        raise PersonModelStoreError(msg)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


# --- field suggestions and restating findings (§9:2-§9:3) -----------------------------


async def test_the_scouts_suggestion_is_recorded_pending_on_the_part_it_rests_on() -> None:
    """§9:2, §7:9: the field, the value, the episode, the part and its origin, by code."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted(
        reply(
            findings=[],
            suggestions=[
                {"field": "time_zone", "value": "Europe/Lisbon", "part": "P1"},
                # Dropped: no such field; a later episode's part; the assistant's words;
                # no part; and an entry that is no object.
                {"field": "pronouns", "value": "they", "part": "P1"},
                {"field": "name", "value": "Robin", "part": "P3"},
                {"field": "name", "value": "Robin", "part": "P2"},
                {"field": "language", "value": "Português"},
                "Europe/Lisbon",
            ],
        )
    )
    observer = harness.observer(scout=scout, person_model=store)

    outcome = await observer.run()

    assert outcome.processed == 1
    (suggestion,) = (await _model(store)).suggestions
    proposed = suggestion.proposed
    assert (proposed.kind, proposed.field, proposed.value) == (
        SuggestionKind.FIELD,
        ProfileField.TIME_ZONE,
        "Europe/Lisbon",
    )
    assert proposed.episode_id == address("one")
    assert proposed.part == InputPart(episode=address("one"))
    assert proposed.origin is SupportOrigin.USER_MESSAGE


async def test_an_invalid_value_is_refused_by_the_store_and_the_run_goes_on() -> None:
    """§3:2: a zone ``zoneinfo`` does not resolve is no suggestion; the episode is processed."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted(
        reply(findings=[], suggestions=[{"field": "time_zone", "value": "Mars/Base", "part": "P1"}])
    )
    observer = harness.observer(scout=scout, person_model=store)

    outcome = await observer.run()

    assert outcome.processed == 1
    assert (await _model(store)).suggestions == ()


async def test_a_finding_that_only_restates_a_field_becomes_a_suggestion_not_a_memory() -> None:
    """§9:3: never committed, nothing kept, and a suggestion where the profile lacks it."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted(
        reply(
            findings=[
                {
                    "claim": "The user wants to be called Leo.",
                    "rests_on": ["P1"],
                    "restates": {"field": "address", "value": "Leo"},
                }
            ]
        )
    )
    commit = FakeModelProvider.scripted()  # never called
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    outcome = await observer.run()

    assert outcome.processed == 1
    assert commit.calls == []
    (record,) = await harness.plans.observations([address("one")])
    (finding,) = record.findings
    assert finding.outcome is not None
    assert finding.outcome.unwritten is FindingUnwritten.NOT_KEPT
    assert [one for one in await harness.memory.export() if isinstance(one, Memory)] == []
    (suggestion,) = (await _model(store)).suggestions
    assert (suggestion.proposed.field, suggestion.proposed.value) == (ProfileField.ADDRESS, "Leo")


async def test_a_restated_value_the_profile_holds_writes_nothing() -> None:
    """§9:3: where the profile holds the value, nothing is written at all."""
    harness = Harness()
    store = _store(harness)
    await store.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Leo", act=_PANEL)
    await _three(harness)
    scout = FakeModelProvider.scripted(
        reply(
            findings=[
                {
                    "claim": "The user goes by Leo.",
                    "rests_on": ["P1"],
                    "restates": {"field": "address", "value": "Leo"},
                }
            ]
        )
    )
    observer = harness.observer(scout=scout, person_model=store)

    await observer.run()

    assert (await _model(store)).suggestions == ()
    assert [one for one in await harness.memory.export() if isinstance(one, Memory)] == []


async def test_a_malformed_restating_marker_leaves_the_finding_to_be_committed() -> None:
    """Every new output is optional: one that is no field and value marks nothing."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted(
        reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"], "restates": "name"}])
    )
    commit = FakeModelProvider.scripted(_create())
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    await observer.run()

    assert len(commit.calls) == 1
    assert [one.content for one in await harness.memory.export() if isinstance(one, Memory)] == [
        _CLAIM
    ]


# --- style marks and pin suggestions (§9:4-§9:5) --------------------------------------


async def test_the_commit_steps_style_and_pin_are_recorded_on_the_memory_it_created() -> None:
    """§9:4, §9:5: a style mark and a pending pin suggestion, on the new memory alone."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted(reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"]}]))
    commit = FakeModelProvider.scripted(_create(style=True, pin=True))
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    await observer.run()

    (created,) = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    model = await _model(store)
    (mark,) = model.style_marks
    assert mark.memory_id == created.id
    (suggestion,) = model.suggestions
    assert suggestion.proposed.kind is SuggestionKind.PIN
    assert suggestion.proposed.memory_id == created.id
    assert suggestion.proposed.episode_id == address("one")


async def test_style_and_pin_left_out_or_false_record_nothing() -> None:
    """Their absence means nothing to record, and so does any value but ``true``."""
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    scout = FakeModelProvider.scripted(reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"]}]))
    commit = FakeModelProvider.scripted(_create(style="yes", pin=False))
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    await observer.run()

    model = await _model(store)
    assert (model.style_marks, model.suggestions) == ((), ())


async def test_a_mark_the_person_removed_is_not_made_again() -> None:
    """§5:3, §9:4: the store keeps a removed mark, so a later commit marks nothing."""
    harness = Harness()
    store = _store(harness)
    held = memory("m-seat", _CLAIM, said_support(address("one")))
    await harness.hold(held)
    marked = await store.add_style_mark(OWNER_PERSON_ID, "m-seat")
    assert marked.record_id is not None
    await store.remove_style_mark(OWNER_PERSON_ID, marked.record_id)
    await _three(harness)
    scout = FakeModelProvider.scripted(reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"]}]))
    commit = FakeModelProvider.scripted(
        reply(
            action="add",
            memory="M1",
            supports=[
                {"part": "P1", "direction": "for", "backs_as_worded": True, "how_sure": "sure"}
            ],
            style=True,
        )
    )
    observer = harness.observer(scout=scout, commit=commit, person_model=store)

    await observer.run()

    model = await _model(store)
    assert model.standing_marks == ()
    assert len(model.style_marks) == 1


# --- the pin pass (§9:6, §9:10) -------------------------------------------------------


async def _pinned(harness: Harness, store: FakePersonModelStore, held: Memory) -> str:
    await harness.hold(held)
    written = await store.add_pin(OWNER_PERSON_ID, held.id, act=_PANEL)
    assert written.record_id is not None
    return written.record_id


async def _held(harness: Harness, memory_id: str) -> Memory:
    found = (await harness.memory.get_history([memory_id])).get(memory_id)
    assert found is not None
    return found


async def test_a_run_confirms_each_own_pin_with_no_model_call() -> None:
    """§9:6, §4:4: a ``pinned`` support, its ``when`` the pin's, added once."""
    harness = Harness()
    store = _store(harness)
    pin = await _pinned(harness, store, memory("m-veg", "The user is vegetarian."))
    pinned_at = (await _model(store)).pins[0].pinned_at
    harness.clock.advance(timedelta(minutes=5))
    observer = harness.observer(person_model=store)  # scripted with no replies

    first = await observer.run()
    second = await observer.run()

    assert (first.pinned, second.pinned) == (1, 0)
    held = await _held(harness, "m-veg")
    support = held.support_at(PinPart(pin=pin))
    assert support is not None
    assert support.origin is SupportOrigin.PINNED
    assert support.direction is SupportDirection.FOR
    assert support.backs_as_worded
    assert support.how_sure is ReadingCertainty.SURE
    assert (support.when, support.about_when) == (pinned_at, None)
    assert support.added_by is MemoryWriterName.OBSERVER
    assert held.operations[-1].kind is MemoryOperationKind.ADD_SUPPORT
    assert held.operations[-1].cites == PinPart(pin=pin)
    assert held.standing is MemoryStanding.CONFIRMED
    assert len(held.operations) == 2, "the second run added nothing"


async def test_a_removed_pin_and_a_retired_memory_still_earn_the_support() -> None:
    """§4:5, §4:7, §9:10, ADR-0342 §5:6: read whatever its status, removed or not."""
    harness = Harness()
    store = _store(harness)
    held = memory("m-veg", "The user is vegetarian.", said_support(address("held")))
    pin = await _pinned(harness, store, held)
    await store.remove_pin(OWNER_PERSON_ID, pin)
    stored = await _held(harness, "m-veg")
    await harness.writer.apply(
        MemoryChange(
            memory=stored,
            operation=MemoryOperation(
                kind=MemoryOperationKind.END,
                cites=stored.supports[0].points_at,
                at=AT,
                by=MemoryWriterName.OBSERVER,
            ),
        )
    )
    observer = harness.observer(person_model=store)

    outcome = await observer.run()

    assert outcome.pinned == 1
    retired = await _held(harness, "m-veg")
    assert retired.status is MemoryStatus.ENDED
    assert retired.support_at(PinPart(pin=pin)) is not None


async def test_a_pin_the_owner_made_on_another_persons_behalf_earns_nothing() -> None:
    """§4:3: only a pin a person made on their own profile confirms the wording."""
    harness = Harness()
    store = _store(harness)
    await harness.hold(memory("m-veg", "The user is vegetarian."))
    other = PersonModelAct(how=PersonActHow.PANEL, by="person:someone-else")
    await store.add_pin(OWNER_PERSON_ID, "m-veg", act=other)
    observer = harness.observer(person_model=store)

    outcome = await observer.run()

    assert outcome.pinned == 0
    assert len((await _held(harness, "m-veg")).supports) == 1


async def test_a_pin_on_a_memory_the_store_does_not_hold_is_passed_over() -> None:
    """§9:6, ADR-0342 §5:4: held exactly where the history read returns it."""
    harness = Harness()
    store = _store(harness)
    await store.add_pin(OWNER_PERSON_ID, "m-forgotten", act=_PANEL)
    observer = harness.observer(person_model=store)

    outcome = await observer.run()

    assert outcome.pinned == 0


async def test_the_pass_runs_whatever_the_budget_and_before_the_episodes() -> None:
    """§9:6, ADR-0329 §16:9: it counts toward no budget, so a held run still confirms."""
    harness = Harness()
    store = _store(harness)
    pin = await _pinned(harness, store, memory("m-veg", "The user is vegetarian."))
    await _three(harness)
    scout = FakeModelProvider.scripted()
    observer = harness.observer(scout=scout, person_model=store, daily_calls=0)

    outcome = await observer.run()

    assert outcome.held
    assert outcome.pinned == 1
    assert scout.calls == []
    assert (await _held(harness, "m-veg")).support_at(PinPart(pin=pin)) is not None


async def test_a_pass_that_cannot_read_the_pins_is_tried_again_on_the_next_run() -> None:
    """§9:6: a failure leaves the pin for the next run, which confirms it."""
    harness = Harness()
    store = _store(harness)
    await _pinned(harness, store, memory("m-veg", "The user is vegetarian."))
    observer = harness.observer(person_model=store)
    store.fail_next()

    first = await observer.run()
    second = await observer.run()

    assert (first.pinned, second.pinned) == (0, 1)


# --- the retirement guard (§9:9) ------------------------------------------------------


def _writer(harness: Harness, store: FakePersonModelStore) -> FindingWriter:
    pins = PinConfirmations(
        people=store, memory=harness.memory, writes=harness.writes, now=harness.clock
    )
    return FindingWriter(
        writes=harness.writes,
        memory=harness.memory,
        now=harness.clock,
        mint=harness.mint,
        pins=pins,
    )


def _ending(target: Memory, cited_episode: str) -> Create:
    """A replacement retiring ``target``, citing the user's later message (§12:4)."""
    newer = said_support(cited_episode, when=AT)
    replacement = memory("observed:new", "The user eats fish now.", newer)
    against = said_support(cited_episode, when=AT, direction=SupportDirection.AGAINST)
    return Create(
        memory=replacement,
        retiring=MemoryRetirement(
            memory=target, kind=MemoryOperationKind.END, cites=newer.points_at
        ),
        conflict=RaiseQuestion(
            target=target,
            kind=OpenQuestionKind.CONFLICT,
            asks="Newer evidence says: The user eats fish now.",
            support=against,
        ),
    )


async def test_a_retirement_its_memorys_pins_outrank_raises_its_conflict_instead() -> None:
    """§9:9, ADR-0328 §6:5, ADR-0329 §13:1: the pin first, then a question, no retirement."""
    harness = Harness()
    store = _store(harness)
    await harness.hold(episode("later", text="I eat fish now."))
    pin = await _pinned(
        harness, store, memory("m-veg", "The user is vegetarian.", said_support(address("held")))
    )
    shown = await _held(harness, "m-veg")
    assert shown.standing is MemoryStanding.SAID

    outcome = await _writer(harness, store).write(Checked(primary=_ending(shown, address("later"))))

    after = await _held(harness, "m-veg")
    assert after.support_at(PinPart(pin=pin)) is not None
    assert after.status is MemoryStatus.CURRENT
    (question,) = after.open_questions
    assert question.kind is OpenQuestionKind.CONFLICT
    assert [(one.memory, one.operations) for one in outcome.writes] == [
        ("m-veg", (MemoryOperationKind.RAISE_QUESTION,))
    ]
    assert await harness.memory.get("observed:new") is None


async def test_a_retirement_with_no_pin_lacking_its_support_is_proposed_as_decided() -> None:
    """§9:9: with nothing to confirm, the guard changes nothing and the end is written."""
    harness = Harness()
    store = _store(harness)
    await harness.hold(
        episode("later", text="I eat fish now."),
        memory("m-veg", "The user is vegetarian.", said_support(address("held"))),
    )
    shown = await _held(harness, "m-veg")

    outcome = await _writer(harness, store).write(Checked(primary=_ending(shown, address("later"))))

    assert (await _held(harness, "m-veg")).status is MemoryStatus.ENDED
    assert {one.memory for one in outcome.writes} == {"m-veg", "observed:new"}


async def test_a_confirmation_cited_over_a_memory_its_pins_made_an_assertion_is_stale() -> None:
    """ADR-0329 §12:4: only a commit shown the memory as it now stands rules on that."""
    harness = Harness()
    store = _store(harness)
    inferred = memory(
        "m-veg",
        "The user is vegetarian.",
        legacy_support({"id": "old", "content": "Vegetarian."}),
    )
    await _pinned(harness, store, inferred)
    shown = await _held(harness, "m-veg")
    assert shown.band is not BeliefBand.ASSERTED
    yes = confirmed_support(address("later"))
    replacement = memory("observed:new", "The user eats fish now.", yes)
    create = Create(
        memory=replacement,
        retiring=MemoryRetirement(memory=shown, kind=MemoryOperationKind.END, cites=yes.points_at),
    )

    with pytest.raises(MemoryStoreStaleError):
        await _writer(harness, store).write(Checked(primary=create))

    assert (await _held(harness, "m-veg")).status is MemoryStatus.CURRENT


class _FailingPinWrites(MemoryWriteStage):
    """The write stage, whose add support citing a pin fails as a store fault would."""

    async def apply(self, change: MemoryChange) -> None:
        if isinstance(change.operation.cites, PinPart):
            msg = "the store failed the write"
            raise MemoryStoreError(msg)
        await super().apply(change)


async def test_a_pin_support_the_guard_cannot_write_fails_the_retirement() -> None:
    """§9:9: a retirement is never proposed past a pin whose support did not land."""
    harness = Harness()
    store = _store(harness)
    await harness.hold(episode("later", text="I eat fish now."))
    await _pinned(
        harness, store, memory("m-veg", "The user is vegetarian.", said_support(address("held")))
    )
    shown = await _held(harness, "m-veg")
    pins = PinConfirmations(
        people=store,
        memory=harness.memory,
        writes=_FailingPinWrites(writer=harness.writer),
        now=harness.clock,
    )
    writer = FindingWriter(
        writes=harness.writes,
        memory=harness.memory,
        now=harness.clock,
        mint=harness.mint,
        pins=pins,
    )

    with pytest.raises(MemoryStoreError):
        await writer.write(Checked(primary=_ending(shown, address("later"))))

    assert (await _held(harness, "m-veg")).status is MemoryStatus.CURRENT
    assert await harness.memory.get("observed:new") is None


async def test_a_create_the_policy_may_supersede_with_confirms_every_pin_first() -> None:
    """§9:9, ADR-0328 §11:7: a supersession is ruled against the standing the pins give."""
    harness = Harness(ruling=MemoryDecisionKind.SUPERSEDE)
    store = _store(harness)
    await harness.hold(episode("later", text="I am vegetarian, mostly."))
    pin = await _pinned(
        harness, store, memory("m-veg", "The user is vegetarian.", said_support(address("held")))
    )
    newer = memory("observed:new", "The user is vegetarian.", said_support(address("later")))

    # The writer refuses an end the pinned standing outranks (ADR-0328 §6:5).
    with contextlib.suppress(MemoryStoreError):
        await _writer(harness, store).write(Checked(primary=Create(memory=newer)))

    (call,) = harness.policy.calls
    assert [one.id for one in call.conflicts] == ["m-veg"], "a supersession was in reach"
    held = await _held(harness, "m-veg")
    assert held.support_at(PinPart(pin=pin)) is not None, "confirmed before the ingest"
    assert held.status is MemoryStatus.CURRENT


class _FailingMarksOnce:
    """The fake person-model store, whose first style mark fails as a store fault would."""

    def __init__(self, store: FakePersonModelStore) -> None:
        self._store = store
        self._failed = False

    async def add_style_mark(self, person_id: str, memory_id: str) -> PersonModelWrite:
        if not self._failed:
            self._failed = True
            msg = "the person-model store cannot be written"
            raise PersonModelStoreError(msg)
        return await self._store.add_style_mark(person_id, memory_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


async def test_a_mark_the_store_failed_is_made_when_the_retry_adds_to_the_memory() -> None:
    """§9:4-§9:5, ADR-0329 §16:4: the attempt fails, and the episode stays to be retried.

    The memory the first attempt created is found again by the retry's search, by an
    observer built afresh over the same stores, and the commit step adds to it, as its
    instruction has it for a memory that already states the claim: that memory, as the
    step judged it, is marked.
    """
    harness = Harness()
    store = _store(harness)
    await _three(harness)
    first = harness.observer(
        scout=FakeModelProvider.scripted(reply(findings=[{"claim": _CLAIM, "rests_on": ["P1"]}])),
        commit=FakeModelProvider.scripted(_create(style=True, pin=True)),
        person_model=cast("PersonModelStore", _FailingMarksOnce(store)),
    )

    failed = await first.run()

    assert (failed.processed, failed.waiting) == (0, 1)
    assert (await _model(store)).style_marks == ()
    (created,) = [one for one in await harness.memory.export() if isinstance(one, Memory)]
    harness.clock.advance(timedelta(minutes=2))  # past the first backoff
    restarted = harness.observer(
        commit=FakeModelProvider.scripted(
            reply(
                action="add",
                memory="M1",
                supports=[
                    {"part": "P1", "direction": "for", "backs_as_worded": True, "how_sure": "sure"}
                ],
                style=True,
                pin=True,
            )
        ),
        person_model=store,
    )

    retried = await restarted.run()

    assert retried.processed == 1
    model = await _model(store)
    assert [one.memory_id for one in model.style_marks] == [created.id]
    assert [one.proposed.memory_id for one in model.suggestions] == [created.id]

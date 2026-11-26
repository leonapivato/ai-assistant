"""The pin pass and the upcoming-event producer read and write by a run's sight (ADR-0388).

ADR-0388 §4: the pass ADR-0338 §9:6 makes at the start of each observer run is an ADR-0384
run, once for each person domain (the owner's), by ``Sight.of_run`` for it, through the
stores the observer's holder binds to that sight, and never for the hub's shared things;
the pass before a retiring write is part of the episode's run, by that episode's sight.

ADR-0388 §7: the upcoming-event producer reads the zone and rules into the notification
store through the stores bound to the run's sight of the domain its source's home is in,
the owner's, so the cap and the duplicate lookup (§9's tests) count every record of that
home and no other.

Driven over the canonical fakes, built to withhold or to count (ADR-0383 §7:10): in the
counting build every answer is as today and each read writes its ``sight_counted`` event,
its reader ``run`` (or ``producer`` for the episode's pass); in a withholding one nothing of
another home is read, counted or written.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog.testing
from observer_support import AT, Harness
from test_observer_sight import _routes, _seeded

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    Person,
    PersonActHow,
    PersonModelAct,
    PersonRole,
    PinPart,
    RecordHome,
    Sight,
    SightMode,
)
from ai_assistant.orchestration import NotificationWriteStage
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.upkeep import PERSON_DOMAINS
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakePersonModelStore,
)
from ai_assistant.testing.memories import memory

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import Memory

_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
_MODES: Final = pytest.mark.parametrize(
    "mode", [SightMode.COUNT, SightMode.WITHHOLD], ids=["count", "withhold"]
)
#: A person other than the owner, held only by reaching in: no member admits one yet.
_OTHER: Final = "person:other"


def _counted(logs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [one for one in logs if one["event"] == "sight_counted"]


def _run_sight_codes() -> tuple[str, ...]:
    """The codes of the run's sight of the owner's domain, the one person domain."""
    return Sight.of_run(RecordHome.owners()).codes


# --- the pin pass (§4) -----------------------------------------------------------------


async def _pinned(harness: Harness, people: FakePersonModelStore, held: Memory) -> str:
    await harness.hold(held)
    written = await people.add_pin(OWNER_PERSON_ID, held.id, act=_PANEL)
    assert written.record_id is not None
    return written.record_id


def _another_persons_pin(people: FakePersonModelStore, memory_id: str) -> None:
    """A second person, with a pin of their own on ``memory_id``: a deliberate reach-in,
    since the store admits no person but the owner (ADR-0338 §2:1)."""
    owner = people._people[OWNER_PERSON_ID]
    (pin,) = owner.pins
    other = Person(id=_OTHER, role=PersonRole.OWNER, created_at=AT)
    theirs = pin.model_copy(
        update={
            "id": "pin-other",
            "person_id": _OTHER,
            "act": PersonModelAct(how=PersonActHow.PANEL, by=_OTHER),
            "memory_id": memory_id,
        }
    )
    people._people[_OTHER] = dataclasses.replace(
        owner, person=other, changes=[], pins=[theirs], marks=[], suggestions=[]
    )


async def _pass_world(
    mode: SightMode,
) -> tuple[Harness, FakePersonModelStore, dict[str, str]]:
    """An owner's pin on an owner's memory, one on a memory of the shared things, and
    another person's pin, held in stores built to ``mode``."""
    harness = Harness(sight_mode=mode)
    people = FakePersonModelStore(now=harness.clock, sight_mode=mode)
    pins = {
        "own": await _pinned(harness, people, memory("m-veg", "The user is vegetarian.")),
    }
    _another_persons_pin(people, "m-veg")
    pins["shared"] = await _pinned(
        harness, people, memory("m-wifi", "The wifi is downstairs.", home=RecordHome.shared())
    )
    return harness, people, pins


async def _supports(harness: Harness, memory_id: str) -> list[object]:
    held = (await harness.memory.get_history([memory_id])).get(memory_id)
    assert held is not None
    return [one.points_at for one in held.supports]


@_MODES
async def test_the_pass_over_the_owners_domain_confirms_as_today(mode: SightMode) -> None:
    """§4:1: the run's pass tends the owner's domain, and the owner's own pin on an
    owner's memory earns its ``pinned`` support in either build, once."""
    harness, people, pins = await _pass_world(mode)
    observer = harness.observer(person_model=people)

    first = await observer.run()
    second = await observer.run()

    assert (first.pinned, second.pinned) == (1, 0)
    assert PinPart(pin=pins["own"]) in await _supports(harness, "m-veg")
    assert PinPart(pin="pin-other") not in await _supports(harness, "m-veg")
    assert PinPart(pin=pins["shared"]) not in await _supports(harness, "m-wifi")


async def test_withholding_the_pass_reads_no_memory_and_no_profile_of_another_home() -> None:
    """§4:1, ADR-0384 §5:2: under a withholding build the run's sight sees the owner's
    domain alone, so neither the shared things' memory nor another person's pins are
    read: the shared memory is never reached, and nothing is logged of it."""
    harness, people, _ = await _pass_world(SightMode.WITHHOLD)
    observer = harness.observer(person_model=people)
    read: list[str] = []
    # Each copy the holder binds shares the fake's state; what a bound copy's export
    # gives back is recorded by wrapping `bound`.
    bound = people.bound

    def bind(sight: Sight) -> FakePersonModelStore:
        view = bound(sight)
        view_export = view.export

        async def recorded() -> Any:
            model = await view_export()
            read.extend(pin.person_id for pin in model.pins)
            return model

        view.export = recorded  # type: ignore[method-assign]
        return view

    people.bound = bind  # type: ignore[method-assign]

    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()

    assert outcome.pinned == 1
    assert read, "the pins were read through the bound store"
    assert set(read) == {OWNER_PERSON_ID}, "no other person's pin is read"
    assert not [one for one in logs if one.get("reason") == "another_home"]


async def test_counting_the_pass_writes_each_count_as_the_runs_and_passes_the_rest_over() -> None:
    """§4:1, ADR-0383 §11:1, ADR-0384 §4:2: in the counting build the pass reads what an
    unbound store gives back, writing one count event for each read, reader ``run``,
    under the owner's run's sight, and counting what it would have withheld; another
    person's pin is passed over as not of the domain tended, and the memory of the shared
    things is refused as an evidence pointer across two homes, as today."""
    harness, people, _ = await _pass_world(SightMode.COUNT)
    observer = harness.observer(person_model=people)

    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()

    assert outcome.pinned == 1
    passed = [one for one in _counted(logs) if one["reader"] == "run"]
    members = [(one["store"], one["member"]) for one in passed]
    assert ("person_model", "export") in members
    assert ("memory", "get_history") in members
    assert {tuple(one["bounds"]) for one in passed} == {_run_sight_codes()}
    withheld = sum(one["other_home"] + one["no_home"] + one["sees_nothing"] for one in passed)
    assert withheld > 0, "another person's pins and the shared memory would be withheld"
    assert [one["stage"] for one in logs if one.get("reason") == "another_home"] == ["pin"]


async def test_the_pass_is_not_run_for_the_hubs_shared_things() -> None:
    """§4:3: one run's pass for each person domain, the owner's, and none for the shared
    things: every read the pass makes is by the owner's run's sight."""
    assert (RecordHome.owners(),) == PERSON_DOMAINS
    harness, people, _ = await _pass_world(SightMode.COUNT)
    observer = harness.observer(person_model=people)

    with structlog.testing.capture_logs() as logs:
        await observer.run()

    exports = [
        one for one in _counted(logs) if (one["store"], one["member"]) == ("person_model", "export")
    ]
    assert len(exports) == 1, "one pass, for the owner's domain alone"
    assert tuple(exports[0]["bounds"]) == _run_sight_codes()


async def test_the_pass_before_a_retiring_write_reads_by_the_episodes_sight() -> None:
    """§4:4: the pass the writer runs before each retrieval is part of the episode's run:
    its reads are the producer's, by the sight made from that episode's facts."""
    harness = Harness()
    await _seeded(harness)
    people = FakePersonModelStore(now=harness.clock)
    scout, commit = _routes()
    observer = harness.observer(scout=scout, commit=commit, person_model=people)

    with structlog.testing.capture_logs() as logs:
        outcome = await observer.run()

    assert outcome.processed == 1
    exports = [
        (one["reader"], tuple(one["bounds"]))
        for one in _counted(logs)
        if (one["store"], one["member"]) == ("person_model", "export")
    ]
    assert ("run", _run_sight_codes()) in exports, "the run's own pass"
    assert ("producer", ("person_owner",)) in exports, "the guard, by the episode's sight"


# --- the upcoming-event producer (§7) --------------------------------------------------

_CLASS: Final = "upcoming_event"


def _candidate(key: str = "k-1") -> NotificationCandidate:
    return NotificationCandidate(
        candidate_key=key,
        producer="calendar-upcoming",
        notification_class=_CLASS,
        summary="something is about to start",
        noticed_at=AT,
        expires_at=AT + timedelta(hours=1),
        confidence=0.9,
        sensitivity=DataTier.PERSONAL,
    )


async def _notifications(mode: SightMode, *, cap: int = 10) -> FakeNotificationStore:
    store = FakeNotificationStore(now=lambda: AT, cap=cap, sight_mode=mode)
    await store.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )
    return store


async def _of_the_shared_things(store: FakeNotificationStore, key: str) -> None:
    """A held notification of another home than the owner's, written as a store holds one."""
    ruled = await store.admit(
        _candidate(key), home=RecordHome.shared(), policy=FakeNotificationPolicy()
    )
    assert ruled.kind is NotificationDispositionKind.INTERRUPT


def _stage(store: FakeNotificationStore, people: FakePersonModelStore) -> NotificationWriteStage:
    return NotificationWriteStage(
        stores=BoundStores(
            memory=FakeMemoryStore(now=lambda: AT), notifications=store, people=people
        ),
        policy=FakeNotificationPolicy(timezone="UTC"),
        outbox=None,
        policy_for=lambda zone: FakeNotificationPolicy(timezone=zone),
        read_zone=True,
    )


@_MODES
async def test_the_cap_counts_only_the_notifications_of_the_home_written_into(
    mode: SightMode,
) -> None:
    """§7:2, §6:1, §9: the cap is a figure of the records the bound store holds. With a
    held notification of the shared things filling a cap of one, a withholding build
    counts the owner's alone and admits the candidate; the counting build is as today."""
    store = await _notifications(mode, cap=1)
    await _of_the_shared_things(store, "shared-1")
    stage = _stage(store, FakePersonModelStore(now=lambda: AT, sight_mode=mode))

    ruling = await stage.offer(_candidate())

    if mode is SightMode.WITHHOLD:
        assert ruling.kind is NotificationDispositionKind.INTERRUPT
        assert ruling.notification_id is not None
        record = await store.get(ruling.notification_id)
        assert record is not None
        assert record.home == RecordHome.owners()
    else:
        assert ruling.reason is NotificationCondition.AT_CAP, "as today"


@_MODES
async def test_the_duplicate_lookup_counts_only_the_notifications_of_the_home_written_into(
    mode: SightMode,
) -> None:
    """§7:2, §6:1, §9: a held notification of the shared things speaking for the same key
    is no duplicate to a withholding build, which holds the owner's alone; the counting
    build is as today."""
    store = await _notifications(mode)
    await _of_the_shared_things(store, "same")
    stage = _stage(store, FakePersonModelStore(now=lambda: AT, sight_mode=mode))

    ruling = await stage.offer(_candidate("same"))

    if mode is SightMode.WITHHOLD:
        assert ruling.kind is NotificationDispositionKind.INTERRUPT
    else:
        assert ruling.kind is NotificationDispositionKind.DROP
        assert ruling.reason is NotificationCondition.DUPLICATE, "as today"


@_MODES
async def test_the_producer_writes_for_the_owner_as_today(mode: SightMode) -> None:
    """§7:1: with every record the owner's, both builds rule and write alike: one record
    of the owner's home, and a re-offer of its key a duplicate of it."""
    store = await _notifications(mode)
    stage = _stage(store, FakePersonModelStore(now=lambda: AT, sight_mode=mode))

    first = await stage.offer(_candidate("k"))
    second = await stage.offer(_candidate("k"))

    assert first.kind is NotificationDispositionKind.INTERRUPT
    assert first.notification_id is not None
    record = await store.get(first.notification_id)
    assert record is not None
    assert record.home == RecordHome.owners()
    assert second.reason is NotificationCondition.DUPLICATE


async def test_counting_the_producers_reads_are_the_runs() -> None:
    """§7:1, ADR-0383 §11:1: in the counting build the zone is read through the
    person-model store bound to the owner's run's sight, its count event's reader
    ``run``."""
    store = await _notifications(SightMode.COUNT)
    stage = _stage(store, FakePersonModelStore(now=lambda: AT))

    with structlog.testing.capture_logs() as logs:
        await stage.offer(_candidate())

    counted = _counted(logs)
    assert [(one["store"], one["member"]) for one in counted] == [("person_model", "read")]
    assert {one["reader"] for one in counted} == {"run"}
    assert {tuple(one["bounds"]) for one in counted} == {_run_sight_codes()}

"""The quiet windows are read in the zone of the person a notification is for.

ADR-0338 §3:6, as §13 reads it over ADR-0130 §6:4: quiet windows are read in the zone of
the person they are for, and in ``Settings.timezone`` where that is empty. A policy's zone
stays a construction-time property of the instance (``NotificationPolicy``), so what
varies is which instance a ruling is handed, picked by
:class:`~ai_assistant.orchestration.notifications.RulingPolicy` just before each ruling,
on both ruling paths: the write stage's live one and the engine's reconsideration.

The instant is 09:00 UTC, which is 18:00 in Tokyo and 10:00 in Lisbon, and the quiet
window is 17:00 to 19:00 local: quiet in the owner's zone, and not in the hub's.

Every collaborator is a canonical fake from ``ai_assistant.testing``, so nothing here
imports a subsystem concrete (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
from test_engine import (
    AT,
    Harness,
    _connection_operations,
    _grant_operations,
)

from ai_assistant.core.errors import ConfigurationError, PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    PersonActHow,
    PersonModelAct,
    Profile,
    ProfileField,
    QuietWindow,
)
from ai_assistant.orchestration import NotificationWriteStage
from ai_assistant.orchestration.engine import Engine
from ai_assistant.orchestration.notifications import RulingPolicy
from ai_assistant.orchestration.person_block import PersonBlocks, person_zone
from ai_assistant.testing import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)
from ai_assistant.testing.person_model import FakePersonModelStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import NotificationPolicy
    from ai_assistant.core.types import NotificationDisposition

pytestmark = pytest.mark.anyio

_CLASS = "calendar"
_PANEL = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
_TOKYO = "Asia/Tokyo"
_LISBON = "Europe/Lisbon"


class _Factory:
    """The composition root's zone-to-policy factory, recording the zones it built for."""

    def __init__(self) -> None:
        self.zones: list[str] = []

    def __call__(self, zone: ZoneInfo) -> NotificationPolicy:
        self.zones.append(zone.key)
        return FakeNotificationPolicy(timezone=zone)


def _candidate(key: str = "k1") -> NotificationCandidate:
    """A perishable candidate, so the quiet window is what decides it (ADR-0130 §5)."""
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class=_CLASS,
        summary="something the user did not ask for",
        noticed_at=AT,
        expires_at=AT + timedelta(days=1),
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


def _quiet_evening(reach: NotificationReach) -> NotificationPreferences:
    return NotificationPreferences(
        reaches=(ClassReach(notification_class=_CLASS, reach=reach),),
        quiet_windows=(QuietWindow.between(time(17, 0), time(19, 0)),),
    )


async def _people(zone: str | None) -> FakePersonModelStore:
    people = FakePersonModelStore(now=lambda: AT)
    if zone is not None:
        await people.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, zone, act=_PANEL)
    return people


async def _store(reach: NotificationReach) -> FakeNotificationStore:
    store = FakeNotificationStore(now=lambda: AT)
    await store.set_preferences(_quiet_evening(reach))
    return store


def _engine(
    harness: Harness,
    store: FakeNotificationStore,
    *,
    people: FakePersonModelStore | None,
    factory: _Factory | None,
) -> Engine:
    """``test_engine_notifications``'s façade, with the person block and the factory."""
    return Engine(
        chat_reader=False,
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        plans=harness.plans,
        trail=harness.trail,
        spend=harness.trail,
        reads=harness.reads,
        memory=harness.memory,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        notifications=store,
        notification_policy=FakeNotificationPolicy(timezone="UTC"),
        notification_policy_for=factory,
        person_blocks=(
            None if people is None else PersonBlocks(store=people, memory=harness.memory)
        ),
        now=lambda: AT,
    )


# --- the pick ------------------------------------------------------------------------


async def test_the_owners_zone_picks_a_policy_built_for_it() -> None:
    factory = _Factory()
    default = FakeNotificationPolicy(timezone="UTC")
    pick = RulingPolicy(default=default, policy_for=factory, people=await _people(_TOKYO))

    picked = await pick.pick()

    assert picked is not default
    assert factory.zones == [_TOKYO]


async def test_an_empty_zone_picks_the_hubs_policy() -> None:
    """§3:6: where the person's zone is empty, ``Settings.timezone`` governs."""
    factory = _Factory()
    default = FakeNotificationPolicy(timezone="UTC")
    pick = RulingPolicy(default=default, policy_for=factory, people=await _people(None))

    assert await pick.pick() is default
    assert factory.zones == []


@pytest.mark.parametrize("wired", ["no_store", "no_factory", "neither"])
async def test_unwired_every_ruling_is_handed_the_hubs_policy(wired: str) -> None:
    """With the person model off, every ruling is ruled exactly as before it."""
    people = await _people(_TOKYO)
    default = FakeNotificationPolicy(timezone="UTC")
    pick = RulingPolicy(
        default=default,
        policy_for=None if wired in {"no_factory", "neither"} else _Factory(),
        people=None if wired in {"no_store", "neither"} else people,
    )

    assert await pick.pick() is default


async def test_a_changed_zone_governs_the_next_pick() -> None:
    """Read just before each ruling and never cached, so no restart is needed."""
    factory = _Factory()
    people = await _people(_TOKYO)
    pick = RulingPolicy(
        default=FakeNotificationPolicy(timezone="UTC"), policy_for=factory, people=people
    )
    await pick.pick()

    await people.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, _LISBON, act=_PANEL)
    await pick.pick()

    assert factory.zones == [_TOKYO, _LISBON]


async def test_a_store_fault_picks_no_policy() -> None:
    """The fault reaches the caller, which then rules nothing."""
    factory = _Factory()
    people = await _people(_TOKYO)
    pick = RulingPolicy(
        default=FakeNotificationPolicy(timezone="UTC"), policy_for=factory, people=people
    )
    people.fail_next()

    with pytest.raises(PersonModelStoreError):
        await pick.pick()
    assert factory.zones == []


async def test_a_zone_that_does_not_resolve_picks_the_hubs_policy() -> None:
    """Lane 4's reading, shared: a store's defect is logged and the hub's zone governs."""
    people = await _people(None)
    # A deliberate reach-in: the store refuses such a zone on every write (§3:2), so a
    # held one can only be a defect, which no member can produce.
    people._people[OWNER_PERSON_ID].profile = Profile(time_zone="Mars/Olympus")
    default = FakeNotificationPolicy(timezone="UTC")
    pick = RulingPolicy(default=default, policy_for=_Factory(), people=people)

    assert await pick.pick() is default


def test_the_zone_is_read_by_the_one_reading_planning_uses() -> None:
    assert person_zone(None, stage="test") is None
    assert person_zone(Profile(), stage="test") is None
    assert person_zone(Profile(time_zone=_TOKYO), stage="test") == ZoneInfo(_TOKYO)
    assert person_zone(Profile(time_zone="Mars/Olympus"), stage="test") is None


# --- the live path: the write stage ---------------------------------------------------


async def _offered(people: FakePersonModelStore | None) -> NotificationDisposition:
    store = await _store(NotificationReach.INTERRUPT)
    stage = NotificationWriteStage(
        store=store,
        policy=FakeNotificationPolicy(timezone="UTC"),
        outbox=FakeNotificationOutbox(records=store, now=lambda: AT),
        policy_for=_Factory(),
        people=people,
    )
    return await stage.offer(_candidate())


async def test_a_fresh_candidate_is_held_in_the_owners_quiet_window() -> None:
    ruling = await _offered(await _people(_TOKYO))

    assert ruling.kind is NotificationDispositionKind.HOLD
    assert ruling.reason is NotificationCondition.QUIET_WINDOW
    # The window ends at 19:00 in Tokyo, 10:00 UTC: the due instant is the owner's too.
    assert ruling.reconsider_at == AT + timedelta(hours=1)


@pytest.mark.parametrize("zone", [None, "no_store"], ids=["empty_zone", "no_store"])
async def test_a_fresh_candidate_is_ruled_in_the_hubs_zone_otherwise(zone: str | None) -> None:
    people = None if zone == "no_store" else await _people(zone)

    ruling = await _offered(people)

    assert ruling.kind is NotificationDispositionKind.INTERRUPT


async def test_a_store_fault_on_the_live_path_rules_and_writes_nothing() -> None:
    """The safe reading: no ruling, so no zone that is not the owner's moves their night."""
    people = await _people(_TOKYO)
    store = await _store(NotificationReach.INTERRUPT)
    outbox = FakeNotificationOutbox(records=store, now=lambda: AT)
    stage = NotificationWriteStage(
        store=store,
        policy=FakeNotificationPolicy(timezone="UTC"),
        outbox=outbox,
        policy_for=_Factory(),
        people=people,
    )
    people.fail_next()

    with pytest.raises(PersonModelStoreError):
        await stage.offer(_candidate())

    assert await store.export() == []
    assert await outbox.claim() is None

    # The producer's next pass offers it again, and it is ruled in the owner's zone.
    ruling = await stage.offer(_candidate())
    assert ruling.reason is NotificationCondition.QUIET_WINDOW


# --- the reconsideration path: the engine ---------------------------------------------


async def _held(store: FakeNotificationStore) -> str:
    """A record held at reach ``hold``, then made due by raising the class (ADR-0130 §6:7)."""
    held = await store.admit(_candidate(), policy=FakeNotificationPolicy(timezone="UTC"))
    assert held.kind is NotificationDispositionKind.HOLD
    assert held.notification_id is not None
    return held.notification_id


async def _raise_the_class(engine: Engine) -> None:
    await engine.set_notification_preferences(_quiet_evening(NotificationReach.INTERRUPT))


async def test_a_reconsideration_is_ruled_in_the_owners_zone() -> None:
    store = await _store(NotificationReach.HOLD)
    record = await _held(store)
    engine = _engine(Harness(), store, people=await _people(_TOKYO), factory=_Factory())
    await _raise_the_class(engine)

    assert await engine.reconsider_notifications() == 1

    ruled = await store.get(record)
    assert ruled is not None
    assert ruled.kind is NotificationDispositionKind.HOLD
    assert ruled.reason is NotificationCondition.QUIET_WINDOW


@pytest.mark.parametrize(
    ("zone", "people", "factory"),
    [(None, True, True), (_TOKYO, False, True), (_TOKYO, True, False)],
    ids=["empty_zone", "no_store", "no_factory"],
)
async def test_a_reconsideration_is_ruled_in_the_hubs_zone_otherwise(
    zone: str | None, *, people: bool, factory: bool
) -> None:
    store = await _store(NotificationReach.HOLD)
    record = await _held(store)
    engine = _engine(
        Harness(),
        store,
        people=await _people(zone) if people else None,
        factory=_Factory() if factory else None,
    )
    await _raise_the_class(engine)

    assert await engine.reconsider_notifications() == 1

    ruled = await store.get(record)
    assert ruled is not None
    assert ruled.kind is NotificationDispositionKind.INTERRUPT


async def test_a_zone_changed_while_held_governs_the_next_reconsideration() -> None:
    """No restart: the zone set when the record falls due is the zone it is ruled in."""
    store = await _store(NotificationReach.HOLD)
    record = await _held(store)
    people = await _people(_TOKYO)
    engine = _engine(Harness(), store, people=people, factory=_Factory())
    await _raise_the_class(engine)
    await engine.reconsider_notifications()
    first = await store.get(record)
    assert first is not None
    assert first.reason is NotificationCondition.QUIET_WINDOW

    # The owner moves to Lisbon, where 09:00 UTC is 10:00 and outside the window. The
    # record is re-ruled when it next falls due: here at the stamp a quiet-window write
    # gives it (ADR-0130 §6:7), the same evening split in two, so only the zone differs.
    await people.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, _LISBON, act=_PANEL)
    await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(
                QuietWindow.between(time(17, 0), time(18, 0)),
                QuietWindow.between(time(18, 0), time(19, 0)),
            ),
        )
    )
    assert await engine.reconsider_notifications() == 1

    ruled = await store.get(record)
    assert ruled is not None
    assert ruled.kind is NotificationDispositionKind.INTERRUPT


async def test_a_store_fault_on_reconsideration_leaves_the_record_due_and_unruled() -> None:
    store = await _store(NotificationReach.HOLD)
    record = await _held(store)
    people = await _people(_TOKYO)
    engine = _engine(Harness(), store, people=people, factory=_Factory())
    await _raise_the_class(engine)
    before = await store.get(record)
    people.fail_next()

    with pytest.raises(PersonModelStoreError):
        await engine.reconsider_notifications()

    assert await store.get(record) == before, "nothing was ruled, and no unit spent"
    assert [due.id for due in await store.due()] == [record]

    # The next run reads the zone and rules it in the owner's.
    assert await engine.reconsider_notifications() == 1
    ruled = await store.get(record)
    assert ruled is not None
    assert ruled.reason is NotificationCondition.QUIET_WINDOW


def test_a_factory_with_no_policy_beside_it_is_refused() -> None:
    harness = Harness()
    with pytest.raises(ConfigurationError, match="person's zone"):
        Engine(
            chat_reader=False,
            grant_operations=_grant_operations(),
            connection_operations=_connection_operations(),
            plans=harness.plans,
            trail=harness.trail,
            spend=harness.trail,
            reads=harness.reads,
            memory=harness.memory,
            traces=harness.traces,
            trace_sink=harness.trace_sink,
            trace_retention=harness.trace_retention,
            conversations=harness.conversations,
            notification_policy_for=_Factory(),
            now=lambda: AT,
        )

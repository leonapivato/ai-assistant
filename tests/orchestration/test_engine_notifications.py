"""The engine's notification surface, and the maintenance run behind it.

ADR-0130 §9's five ``AssistantEngine`` methods are held to their *contract* by
``tests/core/notification_contract.py`` through the store they delegate to. What
is only true of the **façade** is asserted here: that an unwired deployment
refuses legibly rather than answering "none"; that reconsideration is on the
concrete class and drains the whole due set; and that the retention sweep counts
this store alongside the other three.

The engine is built from the same canonical fakes ``test_engine.py``'s harness
uses, through that module's :class:`Harness`, so nothing here imports a
subsystem (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from test_engine import AT, Harness, _grant_operations

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import (
    ClassReach,
    DataTier,
    NotificationCandidate,
    NotificationCondition,
    NotificationDisposition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    QuietWindow,
)
from ai_assistant.orchestration.engine import Engine
from ai_assistant.testing import FakeNotificationPolicy, FakeNotificationStore

_CLASS = "calendar"


def _wired(
    harness: Harness,
    store: FakeNotificationStore | None = None,
    policy: FakeNotificationPolicy | None = None,
) -> Engine:
    """A façade over ``harness``'s durable state, holding a notification store.

    Built the way ``test_engine._fresh_facade`` builds one — the same stage
    objects and the same fakes — with the two collaborators ADR-0130 §9 adds.
    """
    return Engine(
        grant_operations=_grant_operations(),
        loop=harness.engine._loop,
        runner=harness.engine._runner,
        plans=harness.plans,
        trail=harness.trail,
        memory=harness.memory,
        deferrals=harness.deferrals,
        traces=harness.traces,
        trace_sink=harness.trace_sink,
        trace_retention=harness.trace_retention,
        conversations=harness.conversations,
        observation=harness.observation,
        questions=harness.questions,
        notifications=store,
        notification_policy=policy,
        now=lambda: AT,
    )


def _candidate(key: str, *, expires: datetime | None = None) -> NotificationCandidate:
    """One candidate a producer would have offered."""
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class=_CLASS,
        summary="something the user did not ask for",
        noticed_at=AT,
        expires_at=expires,
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


# --- an unwired deployment refuses rather than answering "none" -------------


@pytest.mark.parametrize(
    "call",
    [
        lambda engine: engine.notifications(),
        lambda engine: engine.dismiss_notification("ntf-1"),
        lambda engine: engine.forget_notification("ntf-1"),
        lambda engine: engine.notification_preferences(),
        lambda engine: engine.set_notification_preferences(NotificationPreferences()),
        lambda engine: engine.reconsider_notifications(),
    ],
    ids=["read", "dismiss", "forget", "preferences", "write", "reconsider"],
)
async def test_an_unwired_surface_refuses_legibly(call: object) -> None:
    """``ingest``'s shape, and for its reason.

    "No notification store is composed" and "nothing is held" are different
    facts, and a surface answering an empty page for the first reports the second
    — which a client renders as "you have no notifications" about a deployment
    that cannot have any.
    """
    engine = _wired(Harness())

    with pytest.raises(ConfigurationError, match="no notification store is wired"):
        await call(engine)  # type: ignore[operator]


def test_a_store_and_a_policy_are_wired_together_or_not_at_all() -> None:
    """§3 puts the ruling inside the store's critical section.

    So a store with no policy can rule nothing and a policy with no store has
    nothing to rule about; either alone is a composition-root defect, and it is
    caught where the wiring happens rather than on the first scheduler tick.
    """
    harness = Harness()

    with pytest.raises(ConfigurationError, match="wired together"):
        _wired(harness, FakeNotificationStore(now=lambda: AT), None)
    with pytest.raises(ConfigurationError, match="wired together"):
        _wired(harness, None, FakeNotificationPolicy())


# --- the read and write surface ---------------------------------------------


async def test_the_surface_reads_and_tunes_what_the_store_holds() -> None:
    """The five methods relay, and the write comes back as the store holds it."""
    store = FakeNotificationStore(now=lambda: AT)
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    ruling = await store.admit(_candidate("k1"), policy=policy)
    assert ruling.notification_id is not None

    assert [record.id for record in await engine.notifications()] == [ruling.notification_id]
    assert (await engine.notification_preferences()).reach_for(_CLASS) is NotificationReach.HOLD

    written = await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.OFF),)
        )
    )

    assert written.reach_for(_CLASS) is NotificationReach.OFF
    assert await engine.dismiss_notification(ruling.notification_id) is True
    assert len(await engine.notifications()) == 1, "a dismissal is not a deletion"
    assert await engine.forget_notification(ruling.notification_id) is True
    assert await engine.notifications() == ()


# --- reconsideration is the concrete class's, and it drains ------------------


def test_reconsideration_is_not_on_the_promoted_protocol() -> None:
    """§5: not an ``AssistantEngine`` member, and no adapter may drive it.

    Asserted rather than assumed, because the method is public on the concrete
    class and the only thing keeping it off the wire is its absence from the
    Protocol — ``wire/surface.METHODS`` is derived from that Protocol, so a
    method that slipped onto it would become addressable from a spoke.
    """
    from ai_assistant.core.protocols import AssistantEngine  # noqa: PLC0415 — asserted about
    from ai_assistant.wire.surface import METHODS  # noqa: PLC0415 — asserted about

    assert not hasattr(AssistantEngine, "reconsider_notifications")
    assert "reconsider_notifications" not in METHODS


async def test_one_run_drains_every_due_record_not_one_page() -> None:
    """§5 defines the operation over **every** record whose instant has arrived.

    A run bounded at a page would leave the fifty-first record held past the
    moment the user's own act made it due, and the user has no way to ask for the
    rest — the operation is a scheduler's, and the next tick is five minutes off.
    """
    store = FakeNotificationStore(now=lambda: AT, cap=200)
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    for index in range(120):
        await store.admit(_candidate(f"k{index}"), policy=policy)
    assert len(await store.export()) == 120

    # Raising the class reaches every actionable held record of it (§6).
    assert await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )

    ruled = await engine.reconsider_notifications(page=50)

    assert ruled == 120
    assert await store.due() == []


@pytest.mark.parametrize(
    ("page", "refusal"),
    [(0, ValueError), (-1, ValueError), (2**63, ValueError), (1.5, TypeError), (True, TypeError)],
    ids=["zero", "negative", "wide", "float", "bool"],
)
async def test_a_read_size_that_reads_nothing_is_refused(
    page: object, refusal: type[Exception]
) -> None:
    """A page of zero is a silent no-op, not a smaller sweep.

    The loop takes a page and stops when a page rules nothing, so ``page=0`` would
    return ``0`` having left every due record due — a run that reports success and
    does nothing, which is worse than one that fails. Stricter than this class's
    read methods for that reason, exactly as ``recent_grants`` is stricter for its
    own (ADR-0102 §10). A non-integer is a ``TypeError`` and a bad integer a
    ``ValueError``, which is ``positive_page_argument``'s own split inherited
    rather than restated.
    """
    store = FakeNotificationStore(now=lambda: AT)
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    await store.admit(_candidate("k1"), policy=policy)
    await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )

    with pytest.raises(refusal, match="page"):
        await engine.reconsider_notifications(page=page)  # type: ignore[arg-type]

    assert len(await store.due()) == 1, "the refusal left the work undone rather than lost"


async def test_a_drained_run_leaves_each_record_ruled_afresh() -> None:
    """The drain re-rules; it does not merely clear the due flag.

    A record held only because its class sat at ``hold`` has no expiry, so raising
    the class re-holds it for perishability rather than interrupting — which is
    the ordinary outcome and the one a loop that "handled" records without ruling
    them would fake.
    """
    store = FakeNotificationStore(now=lambda: AT)
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    keeps = await store.admit(_candidate("k1"), policy=policy)
    perishes = await store.admit(_candidate("k2", expires=AT + timedelta(days=1)), policy=policy)
    assert keeps.notification_id is not None
    assert perishes.notification_id is not None
    await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),)
        )
    )

    assert await engine.reconsider_notifications() == 2

    still_held = await store.get(keeps.notification_id)
    assert still_held is not None
    assert still_held.kind is NotificationDispositionKind.HOLD
    assert still_held.reason is NotificationCondition.PERISHABLE
    reached = await store.get(perishes.notification_id)
    assert reached is not None
    assert reached.kind is NotificationDispositionKind.INTERRUPT


async def test_a_policy_that_never_advances_cannot_hang_the_drain() -> None:
    """The scheduler thread does not take the policy's word for progress.

    The drain's termination argument rests on a re-ruling writing an instant
    strictly later than the one it ruled at — a property of an *implementation*
    of the policy contract, not of this loop. A policy handing back an instant
    already past would spin the hub's scheduler forever, which is a whole
    assistant hung by a clause nothing enforces, so the run also stops once a
    page brings back only records it has already ruled.
    """

    class _Stuck:
        """Rules HOLD with a due instant in the past, every time."""

        async def rule(
            self, candidate: NotificationCandidate, *, notification_id: str, **_facts: object
        ) -> NotificationDisposition:
            return NotificationDisposition(
                kind=NotificationDispositionKind.HOLD,
                notification_id=notification_id,
                notification_class=candidate.notification_class,
                ruled_at=AT,
                reason=NotificationCondition.QUIET_WINDOW,
                failed=(NotificationCondition.QUIET_WINDOW,),
                reconsider_at=AT - timedelta(days=1),
            )

    store = FakeNotificationStore(now=lambda: AT)
    policy = _Stuck()
    engine = _wired(Harness(), store, policy)  # type: ignore[arg-type]
    await store.admit(_candidate("k1", expires=AT + timedelta(days=1)), policy=policy)

    ruled = await engine.reconsider_notifications(page=10)

    assert ruled == 1, "each record is ruled once, and the run then ends"
    assert len(await store.due()) == 1, "the record is still due, which is the policy's fault"


async def test_a_run_with_nothing_due_rules_nothing_and_terminates() -> None:
    """The empty case, which is what every tick sees on a deployment with no producers.

    It is also the loop's own termination guard under test: a page that re-rules
    nothing ends the drain, so a store returning records another writer had
    already resolved cannot spin.
    """
    store = FakeNotificationStore(now=lambda: AT)
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    await store.set_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class=_CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(0, 0), time(23, 59)),),
        )
    )
    await store.admit(_candidate("k1", expires=AT + timedelta(days=1)), policy=policy)

    assert await engine.reconsider_notifications() == 0


# --- the retention sweep counts this store too ------------------------------


async def test_the_sweep_reports_the_notifications_it_reclaimed() -> None:
    """ADR-0130 §7: the purge job ADR-0083 §7 already runs calls this store's purge.

    A fourth call behind the one operation ADR-0083 §11 permits, rather than a
    second sweeping mechanism — the instruction ADR-0078 §10 item 8 gave for the
    deferral queue and ADR-0119 §10 repeated for the trace store.
    """
    now = AT
    store = FakeNotificationStore(now=lambda: now, retention=timedelta(seconds=1))
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    ruling = await store.admit(_candidate("k1"), policy=policy)
    assert ruling.notification_id is not None
    await store.dismiss(ruling.notification_id)
    now = AT + timedelta(hours=1)

    report = await engine.purge_expired()

    assert report.notifications == 1
    assert await store.held() == []


async def test_an_unwired_sweep_reports_none_rather_than_zero() -> None:
    """ "Not wired" and "found nothing" are different facts about a run.

    The same reason ADR-0083 §7 spells a disabled job's interval ``None`` and
    never ``0``, and the reason :attr:`PurgeReport.traces` already does it: a
    value that conflates them is the one an operator cannot recover afterwards.
    """
    report = await _wired(Harness()).purge_expired()

    assert report.notifications is None


async def test_the_sweep_never_purges_an_actionable_record() -> None:
    """§7: a record's key suppresses duplicates for the whole time §8 says it does."""
    store = FakeNotificationStore(now=lambda: AT, retention=timedelta(seconds=1))
    policy = FakeNotificationPolicy()
    engine = _wired(Harness(), store, policy)
    await store.admit(_candidate("k1"), policy=policy)

    report = await engine.purge_expired()

    assert report.notifications == 0
    assert len(await store.held()) == 1

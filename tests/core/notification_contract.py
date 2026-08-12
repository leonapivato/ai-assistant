"""Shared conformance suites for the three notification Protocols (ADR-0130 §9).

Every implementation of :class:`~ai_assistant.core.protocols.NotificationPolicy`,
:class:`~ai_assistant.core.protocols.NotificationWriter` and
:class:`~ai_assistant.core.protocols.NotificationStore` must pass its suite here
(``CONTRIBUTING.md`` -> "Protocol conformance suites"). A concrete test
subclasses the suite and supplies its fixtures.

**§9 enumerates what these must assert, and the list is normative there.** Every
clause of it is a way two implementations could answer the same call differently
while both looking correct, and several are guarantees some other section states
*unconditionally* — the cap refusing at its boundary, a key suppressing
duplicates for the whole time §8 says it does, a unit of budget being spent once.
None of those is expressible as a type, so this is where they live.

**They sit under ``tests/core/`` because these Protocols have no owning subsystem
package**, exactly as ``reader_contract.py`` and ``secret_contract.py`` do
(ADR-0093 §2, ADR-0125 §8). ``tests/conftest.py`` pins this directory onto
``sys.path`` so a narrowed run imports the same suite the gate does.

**Two things are deliberately *not* asserted here.** Cancellation (ADR-0060) and
input observation (ADR-0065) bind these seams through ``core/protocols.py``'s
module-wide clauses as they bind every other; §9's enumeration does not reach
them and the scaffolding they need
(:mod:`ai_assistant.testing.cancellation`) is a second subject the triad check
would have to be taught about. Issue filed rather than smuggled in.

Named ``*_contract`` (not ``test_*``) so pytest collects these only via a
``Test``-prefixed subclass, never the abstract bases directly.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest

from ai_assistant.core.types import (
    DROP_CONDITIONS,
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

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import (
        NotificationPolicy,
        NotificationStore,
        NotificationWriter,
    )

#: The instant every case below is anchored on. Midday UTC, so a quiet window
#: placed on either side of it does not accidentally wrap a day boundary.
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

#: The class every candidate declares unless a case is about two of them.
CLASS = "calendar"

#: A second class, for the cases that must show a setting reaching one and not
#: the other.
OTHER_CLASS = "mail"


def candidate(  # noqa: PLR0913 — one keyword per field a case may vary, each defaulted
    *,
    key: str = "k1",
    notification_class: str = CLASS,
    expires_at: datetime | None = None,
    noticed_at: datetime = NOW,
    confidence: float = 0.5,
    sensitivity: DataTier = DataTier.PERSONAL,
) -> NotificationCandidate:
    """One candidate, with everything a case is not about held constant.

    Args:
        key: The ``candidate_key`` §8 deduplicates on.
        notification_class: The class §6 tunes.
        expires_at: When the opportunity perishes, or ``None``.
        noticed_at: When the producer noticed it.
        confidence: How strongly the producer proposes it.
        sensitivity: The producer's chosen tier.

    Returns:
        The candidate.
    """
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class=notification_class,
        summary="something the user did not ask for",
        noticed_at=noticed_at,
        expires_at=expires_at,
        confidence=confidence,
        sensitivity=sensitivity,
    )


def reaching(notification_class: str, reach: NotificationReach) -> NotificationPreferences:
    """Preferences that set one class's reach and default everything else.

    Args:
        notification_class: Whose reach to set.
        reach: The level to set it to.

    Returns:
        The preferences.
    """
    return NotificationPreferences(
        reaches=(ClassReach(notification_class=notification_class, reach=reach),)
    )


class MutableClock:
    """A clock a case moves, so a deadline can be crossed without waiting.

    A class rather than a closure because a suite has to *advance* it after
    handing it to a store, and a store reads its clock per operation.
    """

    def __init__(self, at: datetime = NOW) -> None:
        """Start the clock.

        Args:
            at: The first reading.
        """
        self.at = at

    def __call__(self) -> datetime:
        """Read the clock.

        Returns:
            The current reading, aware and UTC.
        """
        return self.at

    def advance(self, by: timedelta) -> datetime:
        """Move the clock forward.

        Args:
            by: How far.

        Returns:
            The new reading.
        """
        self.at += by
        return self.at


class StoreFactory(Protocol):
    """Builds a subject over the seams a case needs to control."""

    def __call__(
        self,
        *,
        now: Callable[[], datetime],
        retention: timedelta | None = ...,
        cap: int = ...,
    ) -> NotificationStore:
        """Build one store.

        Args:
            now: The clock it reads.
            retention: What it stamps onto each record at admission.
            cap: The most actionable records it holds.

        Returns:
            The store.
        """
        ...


# ---------------------------------------------------------------------------
# NotificationPolicy
# ---------------------------------------------------------------------------


async def _rule(  # noqa: PLR0913 — one parameter per input §5 weighs; a bundle would hide which case varies
    policy: NotificationPolicy,
    subject: NotificationCandidate,
    *,
    preferences: NotificationPreferences | None = None,
    now: datetime = NOW,
    duplicate: bool = False,
    at_cap: bool = False,
    budget_spent: int = 0,
    budget_frees_at: datetime | None = None,
) -> NotificationDisposition:
    """Ask a policy to rule, with everything a case is not about defaulted.

    Args:
        policy: The subject.
        subject: The candidate to rule on.
        preferences: The standing settings; the shipped defaults where absent.
        now: The ruling instant.
        duplicate: Whether an actionable record carries the key.
        at_cap: Whether the store is at its cap.
        budget_spent: Units spent inside the window.
        budget_frees_at: When the window next frees one.

    Returns:
        The disposition.
    """
    return await policy.rule(
        subject,
        notification_id="ntf-1",
        preferences=preferences or NotificationPreferences(),
        now=now,
        duplicate=duplicate,
        at_cap=at_cap,
        budget_spent=budget_spent,
        budget_frees_at=budget_frees_at,
    )


class NotificationPolicyContract(ABC):
    """What every ``NotificationPolicy`` implementation must do (ADR-0130 §4, §5)."""

    @pytest.fixture
    @abstractmethod
    def policy(self) -> NotificationPolicy:
        """The subject, reading quiet windows in UTC."""

    @pytest.fixture
    @abstractmethod
    def policy_in(self) -> Callable[[str], NotificationPolicy]:
        """Build the same implementation over a named IANA zone.

        A separate seam rather than an argument, because §6 makes the zone a
        property of the *deployment* — a caller free to vary it per call could
        move the user's night.
        """

    async def test_identical_inputs_yield_an_identical_disposition(
        self, policy: NotificationPolicy
    ) -> None:
        """§4's determinism, which is an obligation of the contract.

        The clause a signature cannot express: nothing outside the arguments and
        the implementation's own construction may reach the ruling, so asking
        twice must answer twice the same. An implementation reading its own clock
        for ``now``, or consulting a provider, fails here.
        """
        subject = candidate(expires_at=NOW + timedelta(hours=2))

        first = await _rule(policy, subject, preferences=reaching(CLASS, NotificationReach.HOLD))
        second = await _rule(policy, subject, preferences=reaching(CLASS, NotificationReach.HOLD))

        assert first == second

    @pytest.mark.parametrize(
        ("expired", "off", "duplicate", "at_cap", "expected"),
        [
            (True, True, True, True, NotificationCondition.EXPIRED),
            (False, True, True, True, NotificationCondition.REACH_OFF),
            (False, False, True, True, NotificationCondition.DUPLICATE),
            (False, False, False, True, NotificationCondition.AT_CAP),
        ],
        ids=["expired-wins", "off-wins", "duplicate-wins", "cap-alone"],
    )
    async def test_the_drop_ordering_selects_the_reason_it_names(  # noqa: PLR0913 — one parameter per condition the case makes true
        self,
        policy: NotificationPolicy,
        expired: bool,
        off: bool,
        duplicate: bool,
        at_cap: bool,
        expected: NotificationCondition,
    ) -> None:
        """§5's four conditions are evaluated **in the order it states**.

        Every case makes several of them true at once, which is the only way the
        order is observable: an implementation that checked the cap first would
        pass a suite that only ever made one condition true and would tell the
        user "you have too many notifications" about a candidate that had already
        perished.
        """
        subject = candidate(
            expires_at=NOW - timedelta(minutes=1) if expired else NOW + timedelta(hours=2),
            noticed_at=NOW - timedelta(hours=1),
        )
        reach = NotificationReach.OFF if off else NotificationReach.INTERRUPT

        ruling = await _rule(
            policy,
            subject,
            preferences=reaching(CLASS, reach),
            duplicate=duplicate,
            at_cap=at_cap,
        )

        assert ruling.kind is NotificationDispositionKind.DROP
        assert ruling.reason is expected
        assert expected in DROP_CONDITIONS

    async def test_a_candidate_satisfying_every_condition_interrupts(
        self, policy: NotificationPolicy
    ) -> None:
        """The conjunctive clause of §5, with all four conditions held.

        Perishable, a class at ``interrupt``, no quiet window, and budget to
        spend. This is the only path to an ``INTERRUPT``, and its rarity is the
        decision rather than a side effect.
        """
        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(hours=2)),
            preferences=reaching(CLASS, NotificationReach.INTERRUPT),
        )

        assert ruling.kind is NotificationDispositionKind.INTERRUPT
        assert ruling.failed == ()
        assert ruling.reconsider_at is None

    async def test_a_hold_names_the_first_failure_and_carries_the_whole_set(
        self, policy: NotificationPolicy
    ) -> None:
        """§5's whole-set clause, which §6's correctness rests on.

        A record whose *second* failure is the one a setting change removes is
        invisible to a rule that read the reason alone, and it is that record —
        held behind two things, freed by one act — that §6 argues at length.
        """
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(11, 0), time(13, 0)),),
            interruption_budget=1,
        )

        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(hours=8)),
            preferences=preferences,
            budget_spent=1,
            budget_frees_at=NOW + timedelta(hours=4),
        )

        assert ruling.kind is NotificationDispositionKind.HOLD
        assert ruling.failed == (
            NotificationCondition.QUIET_WINDOW,
            NotificationCondition.BUDGET,
        )
        assert ruling.reason is NotificationCondition.QUIET_WINDOW

    async def test_a_candidate_with_no_expiry_is_held_for_the_expiry_condition(
        self, policy: NotificationPolicy
    ) -> None:
        """§5 names the expiry condition for a candidate declaring none.

        **Perishability is the whole of the escalation test.** Something that
        keeps is not an interruption, it is a message — so a producer that will
        not commit to an expiry is held however sure it is, and however high its
        class's reach.
        """
        ruling = await _rule(
            policy,
            candidate(expires_at=None),
            preferences=reaching(CLASS, NotificationReach.INTERRUPT),
        )

        assert ruling.kind is NotificationDispositionKind.HOLD
        assert ruling.reason is NotificationCondition.PERISHABLE
        assert ruling.reconsider_at is None

    async def test_a_hold_behind_the_reach_alone_carries_no_due_instant(
        self, policy: NotificationPolicy
    ) -> None:
        """Reach is not a condition time resolves (§5).

        Which is exactly why §6 has a setting write stamp a due instant onto such
        a record: it would otherwise sit until it expired, and the user who
        raised the class would never be interrupted about the thing they raised
        it for.
        """
        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(hours=2)),
            preferences=reaching(CLASS, NotificationReach.HOLD),
        )

        assert ruling.failed == (NotificationCondition.REACH_INTERRUPT,)
        assert ruling.reconsider_at is None

    async def test_the_due_instant_is_the_latest_of_what_it_waits_on(
        self, policy: NotificationPolicy
    ) -> None:
        """§5: the earliest instant at which **every** failing condition could hold.

        The maximum, not the minimum: a record waiting on both a window and a
        budget is not free when the first of them clears, and a store that woke
        it then would re-hold it and burn a run.
        """
        frees_at = NOW + timedelta(hours=4)
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(11, 0), time(13, 0)),),
            interruption_budget=1,
        )

        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(hours=8)),
            preferences=preferences,
            budget_spent=1,
            budget_frees_at=frees_at,
        )

        assert ruling.reconsider_at == frees_at

    async def test_a_budget_that_time_will_not_free_yields_no_due_instant(
        self, policy: NotificationPolicy
    ) -> None:
        """A budget of zero is exhausted forever, and §5 spells that as ``None``.

        A due instant nothing can reach is worse than none: it schedules a run
        that must re-hold, on every tick, for as long as the record lives.
        """
        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(hours=2)),
            preferences=NotificationPreferences(
                reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
                interruption_budget=0,
            ),
            budget_spent=0,
            budget_frees_at=None,
        )

        assert ruling.reason is NotificationCondition.BUDGET
        assert ruling.reconsider_at is None

    async def test_a_quiet_window_is_read_in_the_deployments_timezone(
        self, policy_in: Callable[[str], NotificationPolicy]
    ) -> None:
        """§6: quiet windows are read in ``Settings.timezone``, and no other.

        Midday UTC is 21:00 in Tokyo, so a window running 20:00 to 23:00 covers
        the one and not the other. The same instant and the same window ruling
        differently in two zones is the whole point of the clause, and an
        implementation comparing the window against a UTC wall clock passes
        every other case here.
        """
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(20, 0), time(23, 0)),),
        )
        subject = candidate(expires_at=NOW + timedelta(hours=8))

        in_utc = await _rule(policy_in("UTC"), subject, preferences=preferences)
        in_tokyo = await _rule(policy_in("Asia/Tokyo"), subject, preferences=preferences)

        assert in_utc.kind is NotificationDispositionKind.INTERRUPT
        assert in_tokyo.kind is NotificationDispositionKind.HOLD
        assert in_tokyo.reason is NotificationCondition.QUIET_WINDOW

    async def test_a_window_ending_inside_a_dst_gap_wakes_late_and_never_early(
        self, policy_in: Callable[[str], NotificationPolicy]
    ) -> None:
        """The spring-forward case: the window ends when the clock passes it.

        In ``America/New_York`` on 2026-03-08 the clock jumps 02:00 to 03:00, so a
        window ending at 02:30 names a local time that never occurs. §5 asks for
        "the earliest instant at which every condition that failed could next
        hold", and that is the transition itself — 07:00Z. Naive construction
        gives 07:30Z instead, which is half an hour of quiet the user did not ask
        for, and §5's tolerance of a late *run* does not licence a late
        *computation*: a tick that slips is the scheduler's, a due instant that is
        wrong is the policy's.

        The exact instant is asserted rather than a tolerance, because a tolerance
        is what let the naive answer look acceptable. It is also the one instant
        that makes progress: 06:30Z, the other ``fold`` reading, is 01:30 local
        and still inside the window, so a record woken there would re-hold to the
        same instant forever.

        ADR-0093 §7b's ``fold=0`` rule covers the *ambiguous* instant the autumn
        transition leaves, which is the hazard that ADR names; this is the gap the
        same transition leaves in spring.
        """
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(22, 0), time(2, 30)),),
        )
        inside = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # 00:00 local, inside the window
        leaves_the_window = datetime(2026, 3, 8, 7, 0, tzinfo=UTC)  # 03:00 local, the transition

        ruling = await _rule(
            policy_in("America/New_York"),
            candidate(noticed_at=inside, expires_at=inside + timedelta(days=1)),
            preferences=preferences,
            now=inside,
        )

        assert ruling.reason is NotificationCondition.QUIET_WINDOW
        assert ruling.reconsider_at == leaves_the_window

    async def test_a_repeated_local_hour_yields_an_instant_still_ahead(
        self, policy_in: Callable[[str], NotificationPolicy]
    ) -> None:
        """The autumn fall-back, where the earlier reading of the endpoint is spent.

        In ``America/New_York`` on 2026-11-01 the clock falls back 02:00 to 01:00,
        so 01:35 happens twice. Ruling during the **second** one, the ``fold=0``
        reading of a window ending at 01:45 is 05:45Z — fifty minutes in the past.
        A due instant behind the ruling instant makes the record immediately due
        again, so a reconsideration re-rules it, recomputes the same past instant,
        and the maintenance drain runs forever: a whole assistant hung by a quiet
        window.

        The answer is 06:45Z, the second 01:45, which is what the clock will
        actually read next. Coverage stays a wall-clock question and is
        deliberately not fold-aware: a user who says "quiet from 01:30 to 01:45"
        is speaking about what their clock reads, and that night it reads it
        twice.
        """
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(1, 30), time(1, 45)),),
        )
        second_pass = datetime(2026, 11, 1, 6, 35, tzinfo=UTC)  # the second 01:35 local

        ruling = await _rule(
            policy_in("America/New_York"),
            candidate(noticed_at=second_pass, expires_at=second_pass + timedelta(days=1)),
            preferences=preferences,
            now=second_pass,
        )

        assert ruling.reason is NotificationCondition.QUIET_WINDOW
        assert ruling.reconsider_at == datetime(2026, 11, 1, 6, 45, tzinfo=UTC)
        assert ruling.reconsider_at > second_pass

    async def test_every_endpoint_in_a_dst_gap_resolves_to_the_transition_exactly(
        self, policy_in: Callable[[str], NotificationPolicy]
    ) -> None:
        """The gap case at every endpoint, not the one an example picks.

        The two cases above assert a single endpoint each, and a single endpoint
        is where this clause was needed: 02:30 is the *coincidence*, because a
        one-hour bracket's first midpoint is the transition, so an implementation
        bisecting only to the second exits exact there and stops short everywhere
        else. The canonical fake did exactly that and passed the suite for a whole
        release, answering ``07:00:00.234375Z`` for a window ending at 02:01 and
        landing late at 56 of these 60 endpoints (#955).

        **Lateness here is not rounding.** §5 makes ``reconsider_at`` a floor —
        the instant *before* which a record may not be reconsidered, checked with
        ``reconsider_at <= moment`` — so a due instant a fraction of a second past
        the transition means a drain ticking exactly at the transition finds the
        record not due and leaves it a whole reconsideration interval. That is the
        ordinary path of a held record reaching the user, wrong for a reason no
        reading of the ADR would reveal.

        So the assertion is exact equality, swept over the whole gap: 02:00
        through 02:59 all name a local time 2026-03-08 never has in
        ``America/New_York``, and every one of them must answer 07:00:00Z, the
        transition itself. Sixty rulings, because the property is what holds two
        implementations of §5 to one boundary, and an example is what let them
        diverge.
        """
        inside = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # 00:00 local, inside every window below
        transition = datetime(2026, 3, 8, 7, 0, tzinfo=UTC)  # 03:00 local, the clock's first pass
        policy = policy_in("America/New_York")

        for minute in range(2 * 60, 3 * 60):  # 02:00 .. 02:59, none of which occurs
            ends_at = time(minute // 60, minute % 60)
            ruling = await _rule(
                policy,
                candidate(noticed_at=inside, expires_at=inside + timedelta(days=1)),
                preferences=NotificationPreferences(
                    reaches=(
                        ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),
                    ),
                    quiet_windows=(QuietWindow.between(time(22, 0), ends_at),),
                ),
                now=inside,
            )

            assert ruling.reason is NotificationCondition.QUIET_WINDOW
            assert ruling.reconsider_at == transition, (
                f"a window ending at {ends_at} resolved to {ruling.reconsider_at}, "
                f"not the transition {transition}"
            )

    async def test_every_endpoint_in_a_repeated_hour_resolves_to_the_second_pass(
        self, policy_in: Callable[[str], NotificationPolicy]
    ) -> None:
        """The fall-back case at every endpoint the second pass has still to reach.

        The companion to the sweep above, and the other half of the same boundary:
        where spring deletes a local time, autumn serves it twice, and §5's "the
        earliest instant at which every condition that failed could next hold"
        has to pick between two real readings rather than construct a missing one.

        Ruling during the **second** 01:35 on 2026-11-01 in ``America/New_York``,
        every endpoint from 01:36 to 01:59 is still ahead exactly once — its
        ``fold=0`` reading is already spent — so each must answer that second
        reading, on the minute. An implementation that reached for a transition
        here, or that let a bisection's imprecision leak into a case that needs
        none, would answer near it rather than at it; exact equality is what
        separates the two.
        """
        second_pass = datetime(2026, 11, 1, 6, 35, tzinfo=UTC)  # the second 01:35 local, EST
        policy = policy_in("America/New_York")

        for minute in range(1 * 60 + 36, 2 * 60):  # 01:36 .. 01:59, each still ahead
            ends_at = time(minute // 60, minute % 60)
            ruling = await _rule(
                policy,
                candidate(noticed_at=second_pass, expires_at=second_pass + timedelta(days=1)),
                preferences=NotificationPreferences(
                    reaches=(
                        ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),
                    ),
                    quiet_windows=(QuietWindow.between(time(1, 30), ends_at),),
                ),
                now=second_pass,
            )
            expected = datetime(2026, 11, 1, 5, 0, tzinfo=UTC) + timedelta(minutes=minute)

            assert ruling.reason is NotificationCondition.QUIET_WINDOW
            assert ruling.reconsider_at == expected, (
                f"a window ending at {ends_at} resolved to {ruling.reconsider_at}, "
                f"not the second pass {expected}"
            )

    async def test_no_due_instant_is_ever_at_or_before_the_ruling(
        self, policy_in: Callable[[str], NotificationPolicy]
    ) -> None:
        """The property behind the case above, over every minute of both transitions.

        A due instant at or before the ruling instant is not merely wrong: it
        makes the record immediately due, so the maintenance drain re-rules it,
        gets the same answer, and never finishes. Swept over the spring gap and
        the autumn repeat rather than asserted at one instant, because both
        transitions have edges an example picks by luck.
        """
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(
                QuietWindow.between(time(1, 30), time(1, 45)),
                QuietWindow.between(time(22, 0), time(2, 30)),
            ),
        )
        policy = policy_in("America/New_York")

        for transition in (datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)):
            for minutes in range(0, 12 * 60, 5):
                moment = transition + timedelta(minutes=minutes)
                ruling = await _rule(
                    policy,
                    candidate(noticed_at=moment, expires_at=moment + timedelta(days=7)),
                    preferences=preferences,
                    now=moment,
                )
                assert ruling.reconsider_at is None or ruling.reconsider_at > moment, (
                    f"a due instant at or before {moment} never drains"
                )

    async def test_quiet_covering_every_minute_yields_no_due_instant(
        self, policy: NotificationPolicy
    ) -> None:
        """§5: no instant is offered where time cannot lift the condition.

        Two windows meeting at noon and at midnight cover the whole day, which is
        a setting a user is entitled to hold — "do not interrupt me" is what the
        quiet windows are *for*, and §6 gives no separate spelling for it. Quiet
        then never ends, so there is no earliest instant at which the condition
        could next hold and the ``HOLD`` carries none.

        **A bounded future instant would be the wrong answer, not a conservative
        one.** It promises a re-ruling that can only re-hold, so the maintenance
        job spends a run on that record on every tick for as long as it lives.
        """
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(
                QuietWindow.between(time(0, 0), time(12, 0)),
                QuietWindow.between(time(12, 0), time(0, 0)),
            ),
        )

        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(days=1)),
            preferences=preferences,
        )

        assert ruling.reason is NotificationCondition.QUIET_WINDOW
        assert ruling.reconsider_at is None

    async def test_a_long_chain_of_adjacent_windows_reads_as_one_stretch(
        self, policy: NotificationPolicy
    ) -> None:
        """A candidate is not released at a seam, however many seams there are.

        Sixty adjacent ten-minute windows are one ten-hour quiet stretch, and an
        implementation that followed the chain only so far would wake a record
        inside it — early, on a tick that can only re-hold. The count is past any
        plausible fixed bound on purpose: this is a property of the *day*, which
        has a finite number of minutes, not of a budget someone chose.
        """
        windows = tuple(
            QuietWindow(start=start, end=start + 10) for start in range(11 * 60, 17 * 60, 10)
        )
        preferences = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=windows,
        )

        ruling = await _rule(
            policy,
            candidate(expires_at=NOW + timedelta(days=1)),
            preferences=preferences,
        )

        assert len(windows) == 36
        assert ruling.reason is NotificationCondition.QUIET_WINDOW
        assert ruling.reconsider_at == datetime(2026, 8, 11, 17, 0, tzinfo=UTC)

    async def test_a_producers_confidence_settles_nothing(self, policy: NotificationPolicy) -> None:
        """§4: the confidence is **evidence on the proposal**, not authority.

        No clause of §5 is satisfied by a producer asserting that it should be,
        and §11 forbids a numeric score substituting for the conditions. Two
        candidates differing only in confidence therefore rule identically.
        """
        preferences = reaching(CLASS, NotificationReach.INTERRUPT)

        unsure = await _rule(policy, candidate(confidence=0.01), preferences=preferences)
        certain = await _rule(policy, candidate(confidence=1.0), preferences=preferences)

        assert unsure == certain


# ---------------------------------------------------------------------------
# NotificationStore
# ---------------------------------------------------------------------------


class NotificationStoreContract(ABC):
    """What every ``NotificationStore`` implementation must do (ADR-0130 §3, §5 to §9)."""

    @pytest.fixture
    @abstractmethod
    def store(self) -> NotificationStore:
        """The subject at its ordinary tuning, on a clock nothing moves."""

    @pytest.fixture
    @abstractmethod
    def factory(self) -> StoreFactory:
        """Build subjects over an injected clock, retention and cap.

        A function rather than the class itself, deliberately: the class object
        *structurally satisfies* the Protocol, so handing it over would look to
        the Protocol-triad check like a second subject standing beside the fake.
        """

    @pytest.fixture
    @abstractmethod
    def policy(self) -> NotificationPolicy:
        """The ruling every case below asks the store to apply.

        Supplied by the binding rather than built here, because §3 puts the
        ruling *inside* the store's critical section: a suite that ruled for
        itself and handed the answer in would be testing a store the contract
        does not describe.
        """

    # --- §6: an empty store is a working policy ---------------------------

    async def test_an_empty_store_rules_every_class_at_the_default_reach(
        self, store: NotificationStore
    ) -> None:
        """§6: every standing setting has a shipped default.

        **This is what makes the tuning surface reachable on the first day**,
        from an empty store, with no history — which the ruling on #879 makes a
        precondition rather than a nicety, the experiential half of this leg's
        exit test being deferred until daily use resumes.
        """
        preferences = await store.preferences()

        assert preferences.reach_for("a-class-nobody-has-named") is NotificationReach.HOLD
        assert preferences.quiet_windows == ()
        assert preferences.interruption_budget == 3
        assert preferences.budget_window == timedelta(hours=24)

    async def test_the_cap_is_published_and_strictly_positive(
        self, store: NotificationStore
    ) -> None:
        """§7 fixes the cap as an integer in ``0 < value < 2**63``.

        Published because a conformance suite cannot test a boundary nobody
        stated, and because a cap of ``0`` is at capacity before its first
        admission — the class of value ADR-0022 §4a refuses at construction.
        """
        assert isinstance(store.cap, int)
        assert 0 < store.cap < 2**63

    # --- §8: what writes a record, and what does not ----------------------

    async def test_a_hold_writes_a_record_and_names_it(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§8: ``HOLD`` and ``INTERRUPT`` write durable records."""
        ruling = await store.admit(candidate(), policy=policy)

        assert ruling.kind is NotificationDispositionKind.HOLD
        assert ruling.notification_id is not None
        assert await store.get(ruling.notification_id) is not None

    async def test_a_duplicate_is_dropped_and_writes_no_record(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§8's whole purpose: re-noticing is expected, and must be safe.

        A scheduler-driven producer over a receding window proposes the same
        thing every tick — ADR-0093 §5 guarantees it and ADR-0111 §11 rules out a
        cursor as the remedy — so idempotence lives here rather than upstream.
        The ``DROP`` writing **no** record is half of it: a store that wrote one
        and marked it a duplicate would fill its own cap with the repetition it
        exists to absorb.
        """
        first = await store.admit(candidate(key="k1"), policy=policy)

        second = await store.admit(candidate(key="k1"), policy=policy)

        assert second.kind is NotificationDispositionKind.DROP
        assert second.reason is NotificationCondition.DUPLICATE
        assert second.notification_id is None
        assert [record.id for record in await store.held()] == [first.notification_id]

    async def test_a_key_re_offered_after_a_dismissal_is_not_a_duplicate(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§7: the duplicate rule reads the **actionable** population.

        The user disposed of the old notification, so the fact recurring is news
        again. A store deduplicating against every retained record would silence
        a producer for the whole retention horizon after one dismissal.
        """
        first = await store.admit(candidate(key="k1"), policy=policy)
        assert first.notification_id is not None
        await store.dismiss(first.notification_id)

        second = await store.admit(candidate(key="k1"), policy=policy)

        assert second.kind is not NotificationDispositionKind.DROP
        assert second.notification_id != first.notification_id

    async def test_a_key_re_offered_after_its_record_expired_is_not_a_duplicate(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """The same rule reached by expiry rather than by a dismissal (§7).

        Expiry ends actionability without deleting anything, so the record is
        still enumerable and still exported — and its key still speaks for
        nothing.
        """
        clock = MutableClock()
        store = factory(now=clock)
        expiry = NOW + timedelta(hours=1)
        first = await store.admit(candidate(key="k1", expires_at=expiry), policy=policy)
        clock.advance(timedelta(hours=2))

        second = await store.admit(
            candidate(key="k1", expires_at=clock.at + timedelta(hours=1), noticed_at=clock.at),
            policy=policy,
        )

        assert second.kind is not NotificationDispositionKind.DROP
        assert {record.id for record in await store.held()} == {
            first.notification_id,
            second.notification_id,
        }

    # --- §7: the cap ------------------------------------------------------

    async def test_the_cap_refuses_at_its_boundary_and_displaces_nothing(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§7, §11: the cap **refuses**, and an implementing lane may not relax it.

        The producer still holds what it proposed and can propose again; an
        evicted record is gone with nobody left to notice. That asymmetry is why
        ADR-0078 §7 chose refusal for the deferral queue and why §11 makes this
        one unrelaxable.
        """
        store = factory(now=MutableClock(), cap=1)
        admitted = await store.admit(candidate(key="k1"), policy=policy)

        refused = await store.admit(candidate(key="k2"), policy=policy)

        assert refused.kind is NotificationDispositionKind.DROP
        assert refused.reason is NotificationCondition.AT_CAP
        assert [record.id for record in await store.held()] == [admitted.notification_id]

    async def test_a_dismissal_frees_capacity_under_the_cap_at_once(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§7: the cap counts actionable records, so dismissing frees a slot.

        Counting every retained record instead would make a hundred dismissed
        notifications under a retention of ``None`` close the store permanently —
        the failure the actionable-set choice exists to prevent.
        """
        store = factory(now=MutableClock(), cap=1)
        first = await store.admit(candidate(key="k1"), policy=policy)
        assert first.notification_id is not None
        assert await store.dismiss(first.notification_id) is True

        admitted = await store.admit(candidate(key="k2"), policy=policy)

        assert admitted.kind is not NotificationDispositionKind.DROP

    # --- §5: reconsideration ---------------------------------------------

    async def test_a_record_held_behind_a_quiet_window_interrupts_once_it_clears(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§5's reconsideration, end to end, on the condition time resolves.

        Held behind the window, due at its end, re-ruled afresh against the
        standing state as it then is, and **not** read as a duplicate of itself —
        which is the one way a store could get this exactly backwards and drop
        every record it woke.
        """
        clock = MutableClock()
        store = factory(now=clock)
        await store.set_preferences(
            NotificationPreferences(
                reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
                quiet_windows=(QuietWindow.between(time(11, 0), time(13, 0)),),
            )
        )
        held = await store.admit(candidate(expires_at=NOW + timedelta(days=1)), policy=policy)
        assert held.kind is NotificationDispositionKind.HOLD
        assert held.reason is NotificationCondition.QUIET_WINDOW
        assert held.notification_id is not None
        assert held.reconsider_at == datetime(2026, 8, 11, 13, 0, tzinfo=UTC)

        assert await store.due() == []
        clock.advance(timedelta(hours=1))
        assert [record.id for record in await store.due()] == [held.notification_id]
        again = await store.reconsider(held.notification_id, policy=policy)

        assert again is not None
        assert again.kind is NotificationDispositionKind.INTERRUPT
        assert again.notification_id == held.notification_id
        assert len(await store.held()) == 1

    async def test_a_record_held_behind_the_budget_interrupts_once_it_frees(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """The same path on the other condition time resolves (§5, §6).

        A unit is spent when a disposition is **recorded**, never when contact is
        attempted, so the window this waits on is computable with no channel in
        existence — which is what lets the bound hold at all today.
        """
        clock = MutableClock()
        store = factory(now=clock)
        await store.set_preferences(
            NotificationPreferences(
                reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
                interruption_budget=1,
                budget_window=timedelta(hours=2),
            )
        )
        spent = await store.admit(
            candidate(key="k1", expires_at=NOW + timedelta(days=1)), policy=policy
        )
        assert spent.kind is NotificationDispositionKind.INTERRUPT

        held = await store.admit(
            candidate(key="k2", expires_at=NOW + timedelta(days=1)), policy=policy
        )
        assert held.kind is NotificationDispositionKind.HOLD
        assert held.reason is NotificationCondition.BUDGET
        assert held.notification_id is not None
        assert held.reconsider_at == NOW + timedelta(hours=2)

        clock.advance(timedelta(hours=3))
        again = await store.reconsider(held.notification_id, policy=policy)

        assert again is not None
        assert again.kind is NotificationDispositionKind.INTERRUPT

    async def test_a_record_that_has_not_fallen_due_is_not_reconsidered(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """``reconsider_at`` is a floor: before it, nothing may re-rule.

        The ``None`` is a spelling for "there was nothing to do" rather than a
        fault, because a job driving this over a page of due records races other
        writers by construction.
        """
        clock = MutableClock()
        store = factory(now=clock)
        await store.set_preferences(
            NotificationPreferences(
                reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
                quiet_windows=(QuietWindow.between(time(11, 0), time(13, 0)),),
            )
        )
        held = await store.admit(candidate(expires_at=NOW + timedelta(days=1)), policy=policy)
        assert held.notification_id is not None

        assert await store.reconsider(held.notification_id, policy=policy) is None
        assert await store.reconsider("no-such-record", policy=policy) is None

    # --- §6: a standing-setting write re-arms what it reaches -------------

    async def test_raising_a_class_to_interrupt_makes_a_held_record_due(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§6's ordinary case, and the leg's exit test in its natural order.

        Reach is not a condition time resolves, so a record held because its
        class was at ``hold`` carries no due instant from its ruling and would
        otherwise sit there until it expired — the user raises the class, agrees
        to be interrupted, and is not.
        """
        clock = MutableClock()
        store = factory(now=clock)
        held = await store.admit(candidate(expires_at=NOW + timedelta(days=1)), policy=policy)
        assert held.reason is NotificationCondition.REACH_INTERRUPT
        assert held.reconsider_at is None
        assert held.notification_id is not None

        touched = await store.set_preferences(reaching(CLASS, NotificationReach.INTERRUPT))

        assert touched == 1
        assert [record.id for record in await store.due()] == [held.notification_id]
        again = await store.reconsider(held.notification_id, policy=policy)
        assert again is not None
        assert again.kind is NotificationDispositionKind.INTERRUPT

    async def test_raising_the_budget_moves_a_doubly_held_record_earlier(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§6's argument for reading the **whole** failed set, as its own example.

        A record held inside a quiet window closing at 14:00 whose budget is also
        spent until 17:00 is due at 17:00. Raising the budget at 12:30 must move
        it to 12:30 — a rule reading only the recorded first reason sees "quiet
        window", leaves it at 17:00, and loses the hours the user just bought. It
        then re-rules and re-holds to 14:00, which is why ``reconsider_at`` is a
        floor rather than a schedule, and why a setting write may move it earlier.
        """
        opened = NOW - timedelta(hours=1)  # 11:00, before the quiet window opens
        clock = MutableClock(opened)
        store = factory(now=clock)
        settings = NotificationPreferences(
            reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
            quiet_windows=(QuietWindow.between(time(12, 0), time(14, 0)),),
            interruption_budget=1,
            budget_window=timedelta(hours=6),
        )
        await store.set_preferences(settings)
        spent = await store.admit(
            candidate(key="k0", noticed_at=opened, expires_at=NOW + timedelta(days=1)),
            policy=policy,
        )
        assert spent.kind is NotificationDispositionKind.INTERRUPT

        clock.advance(timedelta(minutes=75))  # 12:15, inside the window
        held = await store.admit(
            candidate(key="k1", noticed_at=clock.at, expires_at=NOW + timedelta(days=1)),
            policy=policy,
        )
        assert held.failed == (
            NotificationCondition.QUIET_WINDOW,
            NotificationCondition.BUDGET,
        )
        assert held.reason is NotificationCondition.QUIET_WINDOW
        assert held.reconsider_at == opened + timedelta(hours=6)  # 17:00, the later of the two
        assert held.notification_id is not None

        clock.advance(timedelta(minutes=15))  # 12:30
        touched = await store.set_preferences(
            settings.model_copy(update={"interruption_budget": 5})
        )

        assert touched == 1
        record = await store.get(held.notification_id)
        assert record is not None
        assert record.reconsider_at == clock.at
        again = await store.reconsider(held.notification_id, policy=policy)
        assert again is not None
        assert again.kind is NotificationDispositionKind.HOLD
        assert again.reason is NotificationCondition.QUIET_WINDOW
        assert again.reconsider_at == datetime(2026, 8, 11, 14, 0, tzinfo=UTC)

    async def test_lowering_a_class_to_off_drops_every_actionable_held_record(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§6's exception, and the one direction that runs the other way.

        Every other setting change can only turn a hold into contact, so reaching
        a record it cannot help is merely wasted work. Turning a class off is a
        user asking for **less**, and a rule reading the failed set would leave a
        record held for an absent expiry actionable — suppressing duplicates
        forever — which is the one direction where under-reaching costs the user
        rather than the machine. The record below is exactly that one.
        """
        clock = MutableClock()
        store = factory(now=clock)
        no_expiry = await store.admit(candidate(key="k1"), policy=policy)
        assert no_expiry.reason is NotificationCondition.PERISHABLE
        assert no_expiry.reconsider_at is None
        assert no_expiry.notification_id is not None
        elsewhere = await store.admit(
            candidate(key="k2", notification_class=OTHER_CLASS), policy=policy
        )
        assert elsewhere.notification_id is not None

        touched = await store.set_preferences(reaching(CLASS, NotificationReach.OFF))

        assert touched == 1
        dropped = await store.reconsider(no_expiry.notification_id, policy=policy)
        assert dropped is not None
        assert dropped.kind is NotificationDispositionKind.DROP
        assert dropped.reason is NotificationCondition.REACH_OFF
        record = await store.get(no_expiry.notification_id)
        assert record is not None
        assert record.is_actionable_at(clock.at) is False
        untouched = await store.get(elsewhere.notification_id)
        assert untouched is not None
        assert untouched.reconsider_at is None

    async def test_no_setting_change_reaches_a_record_already_interrupted(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§6: reconsideration is an operation on a **held** record throughout.

        An ``INTERRUPT`` was a decision to reach the user, which by then may have
        been carried out; unmaking it is a transport question this ADR does not
        own and §10 leaves whole to the delivery seam.
        """
        clock = MutableClock()
        store = factory(now=clock)
        await store.set_preferences(reaching(CLASS, NotificationReach.INTERRUPT))
        interrupted = await store.admit(
            candidate(expires_at=NOW + timedelta(days=1)), policy=policy
        )
        assert interrupted.kind is NotificationDispositionKind.INTERRUPT
        assert interrupted.notification_id is not None

        touched = await store.set_preferences(reaching(CLASS, NotificationReach.OFF))

        assert touched == 0
        record = await store.get(interrupted.notification_id)
        assert record is not None
        assert record.kind is NotificationDispositionKind.INTERRUPT
        assert record.is_actionable_at(clock.at) is True

    # --- §3: two rulings never proceed on the same fact --------------------

    async def test_two_concurrent_offers_cannot_both_take_the_last_slot(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§3: the cap check and the write are one atomic act.

        Without it the cap is advisory, and the guarantee §7 states
        unconditionally — "at the cap a new candidate is ruled ``DROP``" —
        becomes a race the deployment loses first on the busiest day.
        """
        store = factory(now=MutableClock(), cap=1)

        rulings = await asyncio.gather(
            store.admit(candidate(key="k1"), policy=policy),
            store.admit(candidate(key="k2"), policy=policy),
        )

        kinds = [ruling.kind for ruling in rulings]
        assert kinds.count(NotificationDispositionKind.DROP) == 1
        assert len(await store.held()) == 1

    async def test_two_concurrent_offers_cannot_both_take_the_last_unit(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§3, on the budget: the read and the recording are one act.

        **The budget is what bounds a wrong producer.** A policy can be right
        about every individual candidate and still be intolerable in aggregate,
        and no per-candidate condition catches that — so a budget two racing
        rulings can both spend is no bound at all.
        """
        store = factory(now=MutableClock())
        await store.set_preferences(
            NotificationPreferences(
                reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
                interruption_budget=1,
            )
        )
        expires = NOW + timedelta(days=1)

        rulings = await asyncio.gather(
            store.admit(candidate(key="k1", expires_at=expires), policy=policy),
            store.admit(candidate(key="k2", expires_at=expires), policy=policy),
        )

        kinds = [ruling.kind for ruling in rulings]
        assert kinds.count(NotificationDispositionKind.INTERRUPT) == 1
        assert kinds.count(NotificationDispositionKind.HOLD) == 1

    async def test_two_concurrent_offers_of_one_key_cannot_both_find_it_absent(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§3, on the duplicate lookup: it and the write are one act.

        A ``HOLD`` racing another ``HOLD`` breaks duplicate suppression exactly
        as a raced ``INTERRUPT`` breaks the budget, which is why §3's clause
        covers **every** durable outcome rather than the interrupting one alone.
        """
        store = factory(now=MutableClock())

        rulings = await asyncio.gather(
            store.admit(candidate(key="k1"), policy=policy),
            store.admit(candidate(key="k1"), policy=policy),
        )

        kinds = [ruling.kind for ruling in rulings]
        assert kinds.count(NotificationDispositionKind.DROP) == 1
        assert len(await store.held()) == 1

    @pytest.mark.parametrize("destroy", ["delete", "clear", "purge"])
    async def test_destroying_an_interrupt_record_refunds_no_unit_of_budget(
        self, factory: StoreFactory, policy: NotificationPolicy, destroy: str
    ) -> None:
        """§5: "no spent unit is refunded except by an act that says so".

        A store deriving its spend count from the records it still holds refunds
        one on all three of these, and none of them says so. **The purge is the
        one that matters most**: it is a *scheduler's* act, so the bound §5 exists
        to make computable would widen on a timer wherever a deployment
        configured a retention shorter than the budget window — which is what the
        short retention below is.

        Destroying the record of an interruption does not unmake the
        interruption. What the user destroys is what the notification *said*; the
        budget is a rate limiter, and the instant it remembers carries no key, no
        summary and no class.
        """
        clock = MutableClock()
        store = factory(now=clock, retention=timedelta(minutes=1))
        await store.set_preferences(
            NotificationPreferences(
                reaches=(ClassReach(notification_class=CLASS, reach=NotificationReach.INTERRUPT),),
                interruption_budget=1,
                budget_window=timedelta(hours=6),
            )
        )
        spent = await store.admit(
            candidate(key="k1", expires_at=NOW + timedelta(days=1)), policy=policy
        )
        assert spent.kind is NotificationDispositionKind.INTERRUPT
        assert spent.notification_id is not None

        if destroy == "delete":
            assert await store.delete(spent.notification_id) is True
        elif destroy == "clear":
            assert await store.clear() == 1
        else:
            assert await store.dismiss(spent.notification_id) is True
            clock.advance(timedelta(minutes=2))  # past the record's own retention
            assert await store.purge() == 1
        assert await store.held() == []

        held = await store.admit(
            candidate(key="k2", noticed_at=clock.at, expires_at=NOW + timedelta(days=1)),
            policy=policy,
        )

        assert held.kind is NotificationDispositionKind.HOLD
        assert held.reason is NotificationCondition.BUDGET

    # --- §7: retention -----------------------------------------------------

    async def test_no_actionable_record_is_purged_however_long_it_has_run(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§7: retention yields, because §8's guarantee is unconditional.

        Measured from admission, a record whose expiry sits beyond the horizon is
        purged while still actionable — at which point its key suppresses
        nothing, a cursorless producer re-notices the same fact, and the same
        observation interrupts a second time on a schedule set by the retention
        figure.
        """
        clock = MutableClock()
        store = factory(now=clock, retention=timedelta(days=1))
        await store.admit(candidate(key="k1"), policy=policy)

        clock.advance(timedelta(days=3650))

        assert await store.purge() == 0
        assert len(await store.held()) == 1

    @pytest.mark.parametrize("cessation", ["dismissed", "expired", "dropped"])
    async def test_retention_runs_from_cessation_and_the_horizon_is_exclusive(
        self, factory: StoreFactory, policy: NotificationPolicy, cessation: str
    ) -> None:
        """§7, §9: purged neither before nor **at** the horizon, but after it.

        Measured from the instant the record ceased to be actionable, and from
        that instant however it was reached — all three ways are asserted,
        because a store anchoring on ``admitted_at`` gets two of them right by
        accident whenever admission and cessation coincide.
        """
        retention = timedelta(days=7)
        clock = MutableClock()
        store = factory(now=clock, retention=retention)
        ceased_at = await self._cease(store, policy, clock, how=cessation)

        clock.at = ceased_at + retention
        assert await store.purge() == 0, "a record is retained at its horizon, not past it"

        clock.at = ceased_at + retention + timedelta(microseconds=1)
        assert await store.purge() == 1
        assert await store.held() == []

    async def test_a_retention_of_none_is_never_purged(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§7: ``None`` is the deliberate "keep them", and it is complete.

        The duration axis is where the escape lives, the cap having no
        "unlimited" spelling — so this is the one way a user says "hold on to
        these", and a store treating it as zero would destroy exactly what they
        asked to keep.
        """
        clock = MutableClock()
        store = factory(now=clock, retention=None)
        ceased_at = await self._cease(store, policy, clock, how="dismissed")

        clock.at = ceased_at + timedelta(days=3650)

        assert await store.purge() == 0
        assert len(await store.held()) == 1

    async def test_a_retention_horizon_past_the_calendar_purges_nothing(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """§7's exclusive horizon, at the far edge of the range §7 leaves unbounded.

        §7 puts **no ceiling** on a retention — the deliberate escape is ``None``
        — so a record that ceased yesterday under a retention of some ten thousand
        years has a horizon outside the calendar entirely. Elapsed is elapsed: it
        has not arrived and will not, so this is the clause above asserted where
        the sum ``ceased + retention`` cannot be formed, rather than a new one.

        **It belongs in the shared suite rather than in either backend's**,
        because a horizon nobody can represent is exactly where two
        implementations diverge silently: one raises out of ``purge``, the other
        reads the failure as "not yet", and §7's boundary stops having one
        definition. The figure below is inside what a durable backend can stamp as
        exact microseconds in a signed 64-bit column, so no implementation may
        refuse it at admission and answer the question that way.

        The record must also **survive**: a ``purge`` that returned zero because
        it abandoned the sweep would satisfy a count-only assertion, and ADR-0083
        §7's job sweeps two other stores in the same operation.
        """
        retention = timedelta(days=4_000_000)
        clock = MutableClock()
        store = factory(now=clock, retention=retention)
        ceased_at = await self._cease(store, policy, clock, how="dismissed")
        with pytest.raises(OverflowError):
            ceased_at + retention  # the horizon itself, unrepresentable

        clock.advance(timedelta(days=3650))

        assert await store.purge() == 0
        assert len(await store.held()) == 1

    async def _cease(
        self,
        store: NotificationStore,
        policy: NotificationPolicy,
        clock: MutableClock,
        *,
        how: str,
    ) -> datetime:
        """Admit one record and end its actionability the named way.

        Args:
            store: The subject.
            policy: The ruling to apply.
            clock: The clock the subject reads, moved as the case needs.
            how: ``dismissed``, ``expired`` or ``dropped``.

        Returns:
            The instant the record ceased to be actionable.
        """
        if how == "expired":
            expiry = clock.at + timedelta(hours=1)
            await store.admit(candidate(key="k1", expires_at=expiry), policy=policy)
            clock.at = expiry
            return expiry
        if how == "dismissed":
            ruling = await store.admit(candidate(key="k1"), policy=policy)
            assert ruling.notification_id is not None
            clock.advance(timedelta(hours=1))
            assert await store.dismiss(ruling.notification_id) is True
            return clock.at
        ruling = await store.admit(candidate(key="k1"), policy=policy)
        assert ruling.notification_id is not None
        clock.advance(timedelta(hours=1))
        await store.set_preferences(reaching(CLASS, NotificationReach.OFF))
        dropped = await store.reconsider(ruling.notification_id, policy=policy)
        assert dropped is not None
        assert dropped.kind is NotificationDispositionKind.DROP
        return clock.at

    # --- §9: the four data-right shapes -----------------------------------

    async def test_a_deleted_record_is_gone_from_the_enumeration_and_the_export(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§9, ADR-0004 §6: the delete right, and what it must actually reach.

        **A dismissal is not a deletion**, so this surface is the one the delete
        right reaches and that one is not. An implementation hiding a deleted
        record from the enumeration while leaving it in the export would hand the
        user back, in a file they asked for, the thing they asked to destroy.
        """
        ruling = await store.admit(candidate(key="k1"), policy=policy)
        assert ruling.notification_id is not None

        assert await store.delete(ruling.notification_id) is True

        assert await store.held() == []
        assert await store.export() == []
        assert await store.get(ruling.notification_id) is None
        assert await store.delete(ruling.notification_id) is False

    async def test_a_dismissed_record_stays_readable_and_exported(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§9: dismissal ends actionability and leaves the record readable.

        Which is what makes the two acts different rather than two spellings of
        one, and what §7 means by "expiry deletes nothing".
        """
        ruling = await store.admit(candidate(key="k1"), policy=policy)
        assert ruling.notification_id is not None

        assert await store.dismiss(ruling.notification_id) is True

        assert [record.id for record in await store.held()] == [ruling.notification_id]
        assert [record.id for record in await store.export()] == [ruling.notification_id]
        assert await store.dismiss(ruling.notification_id) is False

    async def test_clear_destroys_every_record(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§9: the sweep half of the data right, unconditional as ``delete`` is."""
        await store.admit(candidate(key="k1"), policy=policy)
        await store.admit(candidate(key="k2"), policy=policy)

        assert await store.clear() == 2

        assert await store.export() == []

    async def test_clear_leaves_the_standing_settings_alone(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """The settings are the user's *choices*, not the user's notifications.

        A sweep that silently restored every class to ``hold`` would undo a
        "never tell me this" the user meant to keep, which is the one direction
        §6 says costs the user rather than the machine.
        """
        await store.set_preferences(reaching(CLASS, NotificationReach.OFF))
        await store.admit(candidate(key="k1"), policy=policy)

        await store.clear()

        preferences = await store.preferences()
        assert preferences.reach_for(CLASS) is NotificationReach.OFF

    async def test_the_enumeration_orders_oldest_first(
        self, factory: StoreFactory, policy: NotificationPolicy
    ) -> None:
        """ADR-0078 §7's ordering, taken for its reason (§11).

        The cap refuses rather than evicts, so the record blocking a newer one is
        the oldest actionable one and belongs on the first page. §11 declines an
        urgency-ordered or imminent-expiry view here as ADR-0078 §7 declined it
        there.
        """
        clock = MutableClock()
        store = factory(now=clock)
        first = await store.admit(candidate(key="k1"), policy=policy)
        clock.advance(timedelta(minutes=5))
        second = await store.admit(candidate(key="k2", noticed_at=clock.at), policy=policy)

        assert [record.id for record in await store.held()] == [
            first.notification_id,
            second.notification_id,
        ]
        assert [record.id for record in await store.held(limit=1)] == [first.notification_id]
        assert [record.id for record in await store.held(limit=1, offset=1)] == [
            second.notification_id
        ]

    @pytest.mark.parametrize(
        "bad", [-1, 2**63, 1.5, True], ids=["negative", "wide", "float", "bool"]
    )
    async def test_a_malformed_page_argument_is_refused(
        self, store: NotificationStore, bad: object
    ) -> None:
        """ADR-0073 §2's posture, inherited rather than restated.

        **The type is part of the range.** Two stores disagreeing about a bad
        argument — one slicing a list on ``1.5`` where the other raises out of its
        driver — is the failure that rule exists to stop.
        """
        with pytest.raises(ValueError, match="limit"):
            await store.held(limit=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="offset"):
            await store.held(offset=bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="limit"):
            await store.due(limit=bad)  # type: ignore[arg-type]

    # --- §2: Tier 0 never reaches this store ------------------------------

    async def test_a_secret_candidate_is_refused_at_validation_and_reaches_no_store(
        self, store: NotificationStore, policy: NotificationPolicy
    ) -> None:
        """§2: refused **at validation**, not gated at disposition.

        ADR-0004 §3 is unconditional that a Tier 0 value lives in the OS keyring,
        "never in the memory database, never in a committed file", and this store
        is a database holding free text a producer wrote to be shown to a person.
        Refusing at construction is what keeps that true of *every* disposition,
        including the held one — a rule that only stopped Tier 0 interrupting
        would still have written it down.
        """
        with pytest.raises(ValueError, match="SECRET"):
            candidate(sensitivity=DataTier.SECRET)

        assert await store.export() == []


# ---------------------------------------------------------------------------
# NotificationWriter
# ---------------------------------------------------------------------------


class NotificationWriterContract(ABC):
    """What every ``NotificationWriter`` implementation must do (ADR-0130 §1, §3)."""

    @pytest.fixture
    @abstractmethod
    def writer(self) -> NotificationWriter:
        """The subject, over a store and a policy of the binding's choosing."""

    @abstractmethod
    def store_of(self, writer: NotificationWriter) -> NotificationStore:
        """The store one subject writes through.

        A method rather than a fixture, so that a suite reaching for a subject's
        collaborator cannot be mistaken for a suite handed a **second** subject —
        which is what the Protocol-triad check refuses, and rightly.

        Args:
            writer: The subject.

        Returns:
            The store behind it.
        """

    async def test_the_seam_returns_the_ruling_and_records_it(
        self, writer: NotificationWriter
    ) -> None:
        """§3: one call — read, rule, record, return.

        ADR-0028 §3 ruled that one method suffices for the memory write path
        "because conflict detection is not a separate stage"; the same holds
        here, and it is what keeps a producer from ever holding the pieces.
        """
        ruling = await writer.offer(candidate(key="k1"))

        assert ruling.kind is NotificationDispositionKind.HOLD
        assert ruling.notification_id is not None
        assert ruling.notification_class == CLASS
        stored = await self.store_of(writer).get(ruling.notification_id)
        assert stored is not None
        assert stored.candidate.candidate_key == "k1"

    async def test_a_dropped_offer_writes_no_record(self, writer: NotificationWriter) -> None:
        """§8: a ``DROP`` writes nothing, so re-noticing cannot fill the store.

        The producer holds no channel and takes no action on the strength of
        having produced a candidate (§1); this ruling is the whole of what it
        gets back, and there is deliberately nothing to read behind it.
        """
        await writer.offer(candidate(key="k1"))

        second = await writer.offer(candidate(key="k1"))

        assert second.kind is NotificationDispositionKind.DROP
        assert second.reason is NotificationCondition.DUPLICATE
        assert second.notification_id is None
        assert len(await self.store_of(writer).held()) == 1

    async def test_the_seam_carries_the_class_so_a_surface_can_tune_it(
        self, writer: NotificationWriter
    ) -> None:
        """§6: every disposition names its class, including a dropped one.

        A surface rendering an interruption offers the two acts that tune it in
        one step — dismissing the notification, and lowering that class's reach —
        and it can only offer the second if the disposition says which class.
        """
        ruling = await writer.offer(candidate(key="k1", notification_class=OTHER_CLASS))

        assert ruling.notification_class == OTHER_CLASS

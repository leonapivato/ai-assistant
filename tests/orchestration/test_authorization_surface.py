"""ADR-0254 §11's read side: the projections, the listing and the revocation.

§20's arms 22, 40, 54, 61, 62 and 71, and §16's clock disciplines, taken over
`orchestration`'s own assembly rather than over a store or a surface.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    AuthorizationDisposition,
    AuthorizationSettlement,
    Goal,
    GoalInterpretation,
    Ground,
    MemorySource,
    Provenance,
)
from ai_assistant.orchestration.authorization_surface import (
    AuthorizationOperations,
    coverage_views,
    is_live,
    projection_of,
    view_of,
)
from ai_assistant.orchestration.authorizing import authorization_id_for
from ai_assistant.testing import (
    AUTHORIZATION_EXPIRES_AT,
    AUTHORIZATION_GOAL,
    AUTHORIZATION_NOW,
    AUTHORIZATION_PROPOSED_AT,
    AUTHORIZATION_TOOL,
    FakeGoalAuthorizationStore,
    FakePlanStore,
    authorization,
    authorization_basis,
    coverage_member,
    money_bound,
    opening_act,
    period_bound,
    terms_bound,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import Authorization

#: The statement the goal below renders as. ADR-0254 §11 renders a goal by its
#: **statement** and never by its id, so this is the value every listing arm reads.
STATEMENT: Final = "book the campsite"

#: A second goal, because §11's listing is per goal and "an authorization of goal A
#: covers no request of goal B, however adjacent" (§1).
OTHER_GOAL: Final = "goal-0002"

#: A second declaration, so one act can open two authorities that are not the same.
OTHER_TOOL: Final = AUTHORIZATION_TOOL.model_copy(update={"id": "rail"})


def _goal(goal_id: str = AUTHORIZATION_GOAL, *, statement: str = STATEMENT) -> Goal:
    """One durable goal, carrying the statement a listing renders it by."""
    return Goal(
        id=goal_id,
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome=statement,
                outcome_ground=Ground.USER_STATED,
                outcome_span=statement,
                recorded_at=AUTHORIZATION_PROPOSED_AT,
                raised_by="t-1",
            ),
        ),
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=1.0,
            last_updated=AUTHORIZATION_PROPOSED_AT,
        ),
        created_at=AUTHORIZATION_PROPOSED_AT,
    )


class _Clock:
    """A clock a test moves, so a listing's liveness is arithmetic a reader can check.

    **Counted**, because ADR-0254 §16 and ADR-0193 §9 both require **one** reading for
    a whole listing: a query reading an advancing clock per row could answer over a set
    true at no real instant, and counting is how that is asserted rather than assumed.
    """

    def __init__(self, at: datetime = AUTHORIZATION_NOW) -> None:
        self.at = at
        self.readings = 0

    def __call__(self) -> datetime:
        self.readings += 1
        return self.at


async def _settled(
    store: FakeGoalAuthorizationStore,
    *,
    disposition: AuthorizationDisposition = AuthorizationDisposition.ESTABLISHED,
    **overrides: object,
) -> Authorization:
    """Seed one row **through the store's own graph** and leave it at ``disposition``.

    ADR-0254 §1 admits a row into exactly two shapes at ``record`` — a path-(i) proposal
    written ``PROPOSED``, and a path-(ii)/(iii) row written ``ESTABLISHED`` carrying no
    ``confirmation`` — and every other disposition is reached through ``settle`` along
    one of its five edges. A suite that wrote a ``REVOKED`` row directly would be
    arranging a state the store refuses, so this walks the graph instead and the
    arrangement is itself an assertion that the graph admits it.
    """
    proposed = {AuthorizationDisposition.PROPOSED, AuthorizationDisposition.DECLINED}
    if disposition in proposed or disposition is AuthorizationDisposition.EXPIRED:
        row = authorization(**overrides)  # type: ignore[arg-type]
        await store.record(row)
        if disposition is not AuthorizationDisposition.PROPOSED:
            settled_at = (
                row.expires_at
                if disposition is AuthorizationDisposition.EXPIRED
                else AUTHORIZATION_NOW
            )
            await store.settle(row.id, to=disposition, settled_at=settled_at)
        return row
    row = opening_act(**overrides)  # type: ignore[arg-type]
    await store.record(row)
    if disposition is not AuthorizationDisposition.ESTABLISHED:
        await store.settle(row.id, to=disposition, settled_at=AUTHORIZATION_NOW)
    return row


async def _operations(
    *rows: Authorization,
    clock: _Clock | None = None,
    goals: tuple[Goal, ...] = (),
) -> tuple[AuthorizationOperations, FakeGoalAuthorizationStore, _Clock]:
    """The object under test, over a real canonical store seeded through ``record``."""
    store = FakeGoalAuthorizationStore()
    plans = FakePlanStore()
    for goal in goals or (_goal(),):
        await plans.save_goal(goal)
    for row in rows:
        await store.record(row)
    reading = clock if clock is not None else _Clock()
    return (
        AuthorizationOperations(authorizations=store, plans=plans, now=reading),
        store,
        reading,
    )


async def _over(
    *, clock: _Clock | None = None, goals: tuple[Goal, ...] = ()
) -> tuple[AuthorizationOperations, FakeGoalAuthorizationStore, _Clock]:
    """An empty store, its plan store seeded, and the object under test over both."""
    return await _operations(clock=clock, goals=goals)


# --- the projections, as transcriptions (ADR-0254 §11, ADR-0178 §5) ----------


def test_a_coverage_view_transcribes_the_member_and_carries_the_span_alone() -> None:
    """§11: the argument, the fixed value or the bound, and the user's own words.

    **And nothing of the basis but the span**: the act it rests on, the rule that
    resolved it, the ``now`` that was read and the record it resolved to are provenance
    for an auditor and reach one through ``export``.
    """
    row = authorization(
        coverage=(
            coverage_member(
                "amount",
                bound=money_bound("60"),
                basis=authorization_basis(span="under sixty pounds"),
            ),
            coverage_member(
                "site", fixed="A", basis=authorization_basis(span="the one by the lake")
            ),
        )
    )

    views = coverage_views(row)

    assert [one.argument for one in views] == ["amount", "site"]
    assert views[0].bound is not None
    assert views[0].bound.maximum == Decimal("60")
    assert views[0].fixed is None
    assert views[0].span == "under sixty pounds"
    assert views[1].fixed == "A"
    assert views[1].bound is None
    assert views[1].span == "the one by the lake"
    assert not any(hasattr(one, "basis") for one in views)


def test_the_projection_carries_the_rows_own_expiry_and_never_recomputes_one() -> None:
    """§11: *"the same coverage, the same bounds and the same ``expires_at`` the row
    carries"*, and §20 arm 22's *"the `CONFIRM` that would establish one names the
    instant"*.
    """
    row = authorization(expires_at=AUTHORIZATION_PROPOSED_AT + timedelta(hours=12))

    projection = projection_of(row)

    assert projection.expires_at == row.expires_at
    assert len(projection.coverage) == len(row.coverage)


def test_an_empty_coverage_projects_as_an_empty_projection() -> None:
    """§20 arm 54: the confirmation carries a **present** projection whose coverage is
    empty and whose ``expires_at`` is the row's.

    An empty projection says what is true — that answering establishes an authority over
    this goal, this declaration, this account and these destinations, fixing no argument
    because the call carries none.
    """
    row = authorization(coverage=())

    projection = projection_of(row)

    assert projection.coverage == ()
    assert projection.expires_at == row.expires_at


def test_a_view_renders_the_goal_by_statement_and_carries_the_revocation_handle() -> None:
    """§20 arm 62's rendering bar, over the carrier rather than over a surface."""
    row = authorization(disposition=AuthorizationDisposition.ESTABLISHED)

    view = view_of(row, goal_statement=STATEMENT, live=True)

    assert view.id == row.id
    assert view.goal_statement == STATEMENT
    assert view.tool == row.tool
    assert view.live is True
    assert not hasattr(view, "goal")
    assert not hasattr(view, "destinations")


# --- liveness: §1's predicate, both ends (ADR-0254 §20 arm 71) ---------------


@pytest.mark.parametrize(
    ("reading", "live"),
    [
        (AUTHORIZATION_PROPOSED_AT, True),
        (AUTHORIZATION_PROPOSED_AT + timedelta(hours=1), True),
        (AUTHORIZATION_EXPIRES_AT - timedelta(seconds=1), True),
        (AUTHORIZATION_EXPIRES_AT, False),
        (AUTHORIZATION_PROPOSED_AT - timedelta(hours=1), False),
    ],
    ids=["at-settlement", "inside", "just-before", "at-expiry", "clock-moved-back"],
)
def test_liveness_is_half_open_and_refuses_a_clock_that_moved_backwards(
    reading: datetime, live: bool
) -> None:
    """§1's predicate and §20 arm 71.

    **Equality at the lower end is live**; equality at the upper end is not. And a
    reading **before** ``settled_at`` answers *not live* rather than disagreeing with
    the trail — which refuses a backdated route-(d) ruling on the same two instants, so
    a liveness stated over the upper end alone would produce a route-(d) `ALLOW` the
    trail then refused.
    """
    row = authorization(disposition=AuthorizationDisposition.ESTABLISHED)

    assert is_live(row, reading) is live


@pytest.mark.parametrize(
    "disposition",
    [
        AuthorizationDisposition.PROPOSED,
        AuthorizationDisposition.DECLINED,
        AuthorizationDisposition.EXPIRED,
        AuthorizationDisposition.REVOKED,
        AuthorizationDisposition.SUPERSEDED,
    ],
)
def test_a_row_that_is_not_established_is_never_live(
    disposition: AuthorizationDisposition,
) -> None:
    """§1: a proposal is a question and not an authority, and a retired row is spent.

    The disposition test is first and there is no arm on which it is skipped.
    """
    row = authorization(disposition=disposition)

    assert is_live(row, AUTHORIZATION_NOW) is False


# --- the clock is guarded (ADR-0026 §2, §4) ----------------------------------


@pytest.mark.parametrize(
    "reading",
    [datetime(2026, 9, 13, 10, 0), None],  # noqa: DTZ001 — a naive reading is the subject
    ids=["naive", "not-an-instant"],
)
async def test_a_non_conforming_clock_reading_is_the_stages_own_error(reading: object) -> None:
    """ADR-0026 §2's wrapper and §4's translation, on both operations.

    ``core/errors.py`` defines no error for `orchestration`, so §4 gives the failure to
    the **stage**. Without the guard a naive reading reaches the listing as a bare
    ``TypeError`` from an aware/naive comparison and the revocation as a raw store
    validation failure — neither of which any contract here declares, and neither of
    which a caller's ``except (AssistantError, TransportError)`` boundary catches.
    Adversarial and architecture review, round 1, ``blocker``.
    """
    store = FakeGoalAuthorizationStore()
    plans = FakePlanStore()
    await plans.save_goal(_goal())
    await store.record(opening_act(id="auth-1"))
    operations = AuthorizationOperations(
        authorizations=store,
        plans=plans,
        now=lambda: reading,  # type: ignore[arg-type, return-value]
    )

    with pytest.raises(PlanningError, match="non-conforming"):
        await operations.standing_authorizations(AUTHORIZATION_GOAL)
    with pytest.raises(PlanningError, match="non-conforming"):
        await operations.revoke_authorization("auth-1")
    # And the listing reaches the guard only where there is a listing to judge, which
    # is what keeps §11's empty answer an answer.
    assert await operations.standing_authorizations("goal-nobody") == ()


async def test_a_non_conforming_clock_writes_nothing() -> None:
    """The refusal is taken **before** the store is reached, so a revocation that could
    not stamp an instant has not settled a row either.
    """
    store = FakeGoalAuthorizationStore()
    plans = FakePlanStore()
    await plans.save_goal(_goal())
    await store.record(opening_act(id="auth-1"))
    operations = AuthorizationOperations(
        authorizations=store,
        plans=plans,
        now=lambda: datetime(2026, 9, 13, 10, 0),  # noqa: DTZ001 — naive is the subject
    )

    with pytest.raises(PlanningError):
        await operations.revoke_authorization("auth-1")

    (held,) = await store.export()
    assert held.disposition is AuthorizationDisposition.ESTABLISHED


# --- the confirmation projection, read back (ADR-0254 §11; issue #2375) ------


async def test_the_projection_is_read_back_by_the_id_derived_from_its_confirmation() -> None:
    """§11's projection, through §16's keyed ``resolve`` and no second mechanism.

    Issue #2375's remedy is the derived id, so a proposal displaced past any page by
    newer rows of *other* goals is still found — at any age, with no limit and no
    ordering assumption.
    """
    row = authorization(id=authorization_id_for("confirm-77"), confirmation="confirm-77")
    operations, _, _ = await _operations(row)

    projection = await operations.projection_for("confirm-77")

    assert projection is not None
    assert projection.expires_at == row.expires_at


async def test_a_confirmation_that_proposed_no_row_projects_nothing() -> None:
    """§1: *"`Confirmation.authorization` is absent (§11), and the answer establishes
    nothing"*. Absence is the answer and is a fault on no ground.
    """
    operations, _, _ = await _operations()

    assert await operations.projection_for("confirm-none") is None


async def test_the_projection_survives_a_restart_because_it_is_read_from_the_row() -> None:
    """§20 arm 40: *"restart the process; recover the confirmation → the same coverage
    and the same `expires_at`"*.

    Modelled as a **second** operations object over the same store, which is what a
    restart is from this seam's side: nothing in-process is carried across, and the
    projection is rebuilt from the durable row alone.
    """
    row = authorization(id=authorization_id_for("confirm-88"), confirmation="confirm-88")
    store = FakeGoalAuthorizationStore()
    plans = FakePlanStore()
    await plans.save_goal(_goal())
    await store.record(row)
    before = await AuthorizationOperations(
        authorizations=store, plans=plans, now=_Clock()
    ).projection_for("confirm-88")

    after = await AuthorizationOperations(
        authorizations=store, plans=plans, now=_Clock()
    ).projection_for("confirm-88")

    assert before == after
    assert after is not None
    assert after.expires_at == row.expires_at


# --- the listing (ADR-0254 §20 arm 61) ---------------------------------------


async def test_the_listing_returns_the_established_rows_of_that_goal_live_and_lapsed() -> None:
    """§20 arm 61, and §16's *"live **and** lapsed"*.

    A lapsed row is returned because a user can then see and revoke what they once
    authorised — ADR-0193 §9's own reason one store over — and it is why the withdrawal
    path needs no history query.
    """
    operations, store, clock = await _over()
    await _settled(store, id="auth-live", expires_at=AUTHORIZATION_NOW + timedelta(hours=1))
    await _settled(
        store,
        id="auth-lapsed",
        tool=AUTHORIZATION_TOOL.model_copy(update={"id": "browser"}),
        expires_at=AUTHORIZATION_NOW - timedelta(minutes=1),
    )

    listed = await operations.standing_authorizations(AUTHORIZATION_GOAL)

    assert {one.id: one.live for one in listed} == {"auth-live": True, "auth-lapsed": False}
    assert clock.readings == 1, "ADR-0254 §16: one clock reading for the whole listing"


@pytest.mark.parametrize(
    "disposition",
    [
        AuthorizationDisposition.PROPOSED,
        AuthorizationDisposition.DECLINED,
        AuthorizationDisposition.EXPIRED,
        AuthorizationDisposition.REVOKED,
        AuthorizationDisposition.SUPERSEDED,
    ],
)
async def test_the_listing_never_renders_a_row_that_is_not_established(
    disposition: AuthorizationDisposition,
) -> None:
    """§20 arm 61: never a ``PROPOSED``, ``DECLINED``, ``EXPIRED``, ``REVOKED`` or
    ``SUPERSEDED`` one.

    **A fact about the read and not a filter a renderer applies** (§11): ``standing``
    never offers one, so a question the user has not answered can reach no listing as an
    authority they hold.
    """
    operations, store, _ = await _over()
    await _settled(store, disposition=disposition)

    assert await operations.standing_authorizations(AUTHORIZATION_GOAL) == ()


async def test_the_listing_never_renders_another_goals_row() -> None:
    """§1: *"an authorization of goal A covers no request of goal B, however adjacent"*."""
    operations, store, _ = await _over(
        goals=(_goal(), _goal(OTHER_GOAL, statement="do something else"))
    )
    await _settled(store, id="auth-mine")
    await _settled(store, id="auth-theirs", goal=OTHER_GOAL)

    listed = await operations.standing_authorizations(AUTHORIZATION_GOAL)

    assert [one.id for one in listed] == ["auth-mine"]


async def test_the_liveness_reading_is_taken_after_the_snapshot_and_never_before() -> None:
    """A reading taken first is one the snapshot can outrun (round 2, ``blocker``).

    A row settled ``ESTABLISHED`` while ``standing`` is suspended comes back carrying a
    ``settled_at`` **after** a reading taken before that call, and §1's predicate then
    reports a live row as not live — a listing true at no real instant, which is what
    ADR-0193 §9's one-reading rule exists to prevent, reached from the other side.

    Driven by settling the row **from inside the store read**, which is where a
    concurrent answer lands.
    """
    store = FakeGoalAuthorizationStore()
    plans = FakePlanStore()
    await plans.save_goal(_goal())
    row = authorization(id="auth-1", confirmation="d-1")
    await store.record(row)
    settled_at = AUTHORIZATION_NOW
    clock = _Clock(settled_at)
    standing = store.standing

    async def settling(goal: str) -> tuple[Authorization, ...]:
        """Answer the question between the caller's snapshot and its comparison."""
        await store.settle("auth-1", to=AuthorizationDisposition.ESTABLISHED, settled_at=settled_at)
        return await standing(goal)

    store.standing = settling  # type: ignore[method-assign]
    operations = AuthorizationOperations(authorizations=store, plans=plans, now=clock)

    (view,) = await operations.standing_authorizations(AUTHORIZATION_GOAL)

    assert view.live is True, "the row was established at the instant the listing reads"


async def test_an_unknown_goal_is_an_empty_answer_even_with_an_unusable_clock() -> None:
    """§11's *"empty answer rather than a raise"* survives a broken clock.

    The reading is taken after the goal lookup, so a goal this system does not hold is
    answered before the clock is reached at all — which is what keeps that clause true of
    a deployment whose clock is non-conforming (round 2, ``blocker``).
    """
    plans = FakePlanStore()
    operations = AuthorizationOperations(
        authorizations=FakeGoalAuthorizationStore(),
        plans=plans,
        now=lambda: datetime(2026, 9, 13, 10, 0),  # noqa: DTZ001 — naive is the subject
    )

    assert await operations.standing_authorizations("goal-nobody") == ()


async def test_a_goal_the_plan_store_does_not_hold_is_an_empty_answer() -> None:
    """§11: *"a goal that store does not hold is an **empty answer** rather than a
    raise"*.

    A listing that rendered the rows with no statement would render a goal by its id,
    which §11 forbids in terms.
    """
    operations, store, _ = await _over()
    await _settled(store, goal=OTHER_GOAL)

    assert await operations.standing_authorizations(OTHER_GOAL) == ()


async def test_each_coverage_view_in_the_listing_carries_the_members_span() -> None:
    """§20 arm 61's last clause, over all three bound kinds and a fixed value."""
    operations, store, _ = await _over()
    await _settled(
        store,
        coverage=(
            coverage_member(
                "amount", bound=money_bound("60"), basis=authorization_basis(span="under sixty")
            ),
            coverage_member(
                "when", bound=period_bound(), basis=authorization_basis(span="this weekend")
            ),
            coverage_member(
                "terms",
                bound=terms_bound("refundable"),
                basis=authorization_basis(span="only if I can cancel"),
            ),
            coverage_member(
                "site", fixed="A", basis=authorization_basis(span="the one by the lake")
            ),
        ),
    )

    (view,) = await operations.standing_authorizations(AUTHORIZATION_GOAL)

    assert [one.span for one in view.coverage] == [
        "under sixty",
        "this weekend",
        "only if I can cancel",
        "the one by the lake",
    ]


# --- the revocation (ADR-0254 §20 arm 61, §16) -------------------------------


@pytest.mark.parametrize(
    ("disposition", "settlement"),
    [
        (AuthorizationDisposition.ESTABLISHED, AuthorizationSettlement.SETTLED),
        (AuthorizationDisposition.PROPOSED, AuthorizationSettlement.NOT_AT_SOURCE),
        (AuthorizationDisposition.DECLINED, AuthorizationSettlement.NOT_AT_SOURCE),
        (AuthorizationDisposition.EXPIRED, AuthorizationSettlement.NOT_AT_SOURCE),
        (AuthorizationDisposition.REVOKED, AuthorizationSettlement.NOT_AT_SOURCE),
        (AuthorizationDisposition.SUPERSEDED, AuthorizationSettlement.NOT_AT_SOURCE),
    ],
)
async def test_the_revocation_answers_the_stores_own_word_for_every_disposition(
    disposition: AuthorizationDisposition, settlement: AuthorizationSettlement
) -> None:
    """§20 arm 61's revocation half, one test per disposition, and **no call raises**.

    A ``PROPOSED`` row is not revocable, and that is §1's graph rather than an omission:
    a question the user has not answered is withdrawn by declining it or by letting it
    lapse.
    """
    operations, store, _ = await _over()
    await _settled(store, id="auth-1", disposition=disposition)

    assert await operations.revoke_authorization("auth-1") == settlement


async def test_a_lapsed_established_row_is_still_revocable() -> None:
    """§20 arm 43: ``REVOKED`` succeeds on an ``ESTABLISHED`` row *"whether it is live or
    lapsed"*, and the lapsed row is reachable for it because ``standing`` returns it.
    """
    operations, store, _ = await _over()
    await _settled(store, id="auth-lapsed", expires_at=AUTHORIZATION_NOW - timedelta(minutes=1))
    (view,) = await operations.standing_authorizations(AUTHORIZATION_GOAL)
    assert view.live is False

    assert await operations.revoke_authorization("auth-lapsed") == AuthorizationSettlement.SETTLED


async def test_an_id_the_store_does_not_hold_is_a_result_and_never_a_raise() -> None:
    """``AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception``'s rule."""
    operations, _, _ = await _over()

    settlement = await operations.revoke_authorization("auth-nobody")

    assert settlement is AuthorizationSettlement.NO_SUCH_AUTHORIZATION


async def test_would_duplicate_is_unreachable_on_the_revocation() -> None:
    """§16: *"reachable only on a settlement **to `ESTABLISHED`**, and a revocation
    settles to `REVOKED`"* — excluded by the edge rather than by the vocabulary.

    §20 arm 55 asks it *"over a revocation of a row of a pair another row is established
    for"*, which is what this arranges: two rows of one goal and declaration id, one
    established and one not.
    """
    operations, store, _ = await _over()
    await _settled(store, id="auth-1")
    await store.record(authorization(id="auth-2", confirmation="confirm-2"))

    assert await operations.revoke_authorization("auth-2") is AuthorizationSettlement.NOT_AT_SOURCE
    assert await operations.revoke_authorization("auth-1") is AuthorizationSettlement.SETTLED


async def test_a_revoked_row_is_absent_from_the_next_listing() -> None:
    """§20 arm 61's last clause."""
    operations, store, _ = await _over()
    await _settled(store, id="auth-1")
    assert len(await operations.standing_authorizations(AUTHORIZATION_GOAL)) == 1

    await operations.revoke_authorization("auth-1")

    assert await operations.standing_authorizations(AUTHORIZATION_GOAL) == ()


# --- the announcement (ADR-0254 §11, §20 arm 64) -----------------------------


async def test_an_act_that_opened_two_authorities_announces_two() -> None:
    """§20 arm 64: *"two rows, two views, two different bounds"*, each naming its own
    declaration, and neither row carrying the other's member.

    **A lane that merged them fails this arm**, and so does one that announced only the
    first.
    """
    train = opening_act(
        id="auth-train",
        tool=AUTHORIZATION_TOOL.model_copy(update={"id": "rail"}),
        coverage=(coverage_member("amount", bound=money_bound("50")),),
    )
    hotel = opening_act(
        id="auth-hotel",
        tool=AUTHORIZATION_TOOL.model_copy(update={"id": "hotels"}),
        coverage=(coverage_member("amount", bound=money_bound("100")),),
    )
    operations, _, _ = await _over()

    announced = operations.announced(
        (train, hotel), goal_statement=STATEMENT, reading=AUTHORIZATION_NOW
    )

    assert [one.id for one in announced] == ["auth-train", "auth-hotel"]
    assert [one.tool.id for one in announced] == ["rail", "hotels"]
    assert [one.goal_statement for one in announced] == [STATEMENT, STATEMENT]
    bounds = [one.coverage[0].bound for one in announced]
    assert [one.maximum for one in bounds if one is not None] == [Decimal(50), Decimal(100)]


async def test_a_turn_that_opened_none_announces_nothing_and_reads_no_clock() -> None:
    """§11: *"It is **empty** on every turn that opened none"*, including a turn that
    only re-grounds an existing constraint — the case ADR-0250 §5 requires to stay
    unannounced and the reason this member exists.
    """
    operations, _, clock = await _over()

    assert operations.announced((), goal_statement=STATEMENT, reading=AUTHORIZATION_NOW) == ()
    assert clock.readings == 0


async def test_an_announcement_reports_the_rows_own_liveness_and_not_a_presumption() -> None:
    """§11: ``live`` is read from the row against this engine's own clock.

    An announcement cannot say *live* about a row the engine's clock says has lapsed,
    which is §20 arm 71's discipline reaching the second surface that renders the field.
    """
    row = opening_act(id="auth-1", expires_at=AUTHORIZATION_NOW - timedelta(minutes=1))
    operations, _, _ = await _over()

    (view,) = operations.announced((row,), goal_statement=STATEMENT, reading=AUTHORIZATION_NOW)

    assert view.live is False


def test_an_announcement_never_drops_a_row_and_reads_no_store() -> None:
    """§11's trigger is that the row was **written**, with no materiality judgement.

    An authority that came into being and was not announced is one the user holds and
    was never shown the handle to — so no row is dropped, on any ground. An earlier draft
    read the goal per row and skipped one the plan store could not return; a concurrent
    deletion would then have silenced a standing authority. Adversarial review, round 3,
    ``blocker``.

    **There is no store read left to fail**: ADR-0250 §3 gives a turn one goal and a
    path-(iii) row is opened for the request it is dispatching, so the statement the
    caller already holds is the one §11 renders every such row by.
    """
    store = FakeGoalAuthorizationStore()
    plans = FakePlanStore()
    operations = AuthorizationOperations(authorizations=store, plans=plans, now=_Clock())
    rows = (opening_act(id="auth-1"), opening_act(id="auth-2", tool=OTHER_TOOL))

    announced = operations.announced(rows, goal_statement=STATEMENT, reading=AUTHORIZATION_NOW)

    assert [one.id for one in announced] == ["auth-1", "auth-2"]
    assert [one.goal_statement for one in announced] == [STATEMENT, STATEMENT]


async def test_the_liveness_reading_is_taken_once_for_a_whole_listing() -> None:
    """ADR-0254 §16 and ADR-0193 §9: *"a query reading an advancing clock per row could
    answer over a set true at no real instant"*.

    Asserted by moving the clock **across** a row's expiry between two listings and
    checking that within one listing every row was judged at one instant.
    """
    boundary = datetime(2026, 9, 13, 15, 0, tzinfo=UTC)
    clock = _Clock(boundary - timedelta(seconds=1))
    operations, store, _ = await _over(clock=clock)
    for index in range(3):
        await _settled(
            store,
            id=f"auth-{index}",
            tool=AUTHORIZATION_TOOL.model_copy(update={"id": f"tool-{index}"}),
            expires_at=boundary,
        )

    before = await operations.standing_authorizations(AUTHORIZATION_GOAL)
    clock.at = boundary
    after = await operations.standing_authorizations(AUTHORIZATION_GOAL)

    assert all(one.live for one in before)
    assert not any(one.live for one in after)
    assert clock.readings == 2, "one reading per listing, not one per row"

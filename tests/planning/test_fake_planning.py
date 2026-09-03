"""The canonical planning fakes pass the shared conformance suites.

This is what lets other subsystems trust ``ai_assistant.testing.FakePlanStore``
and ``FakePlanner`` as stand-ins: they are held to the same contracts as the
real implementations. It matters more here than elsewhere, because
``FakePlanStore`` re-implements the ADR-0014 §4 transition graph independently
(it cannot import the subsystem it stands in for) — this suite is what stops the
two copies drifting apart.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from plan_store_contract import PlanStoreContract
from planner_contract import PlannerContract

from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    Goal,
    MemorySource,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    TimeOfDay,
)
from ai_assistant.testing import FakePlanner, FakePlanStore
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.protocols import Planner, PlanStore


def _fixed_now() -> datetime:
    return datetime(2026, 6, 1, tzinfo=UTC)


class TestFakePlanStoreContract(PlanStoreContract):
    """Runs FakePlanStore through the shared PlanStore conformance suite."""

    @pytest.fixture
    def store(self) -> PlanStore:
        return FakePlanStore(now=_fixed_now)

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[PlanStore]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        Dicts need no serialising, so without this the canonical fake could only
        opt out — and the cancellation case would run solely against the
        ``sqlite3`` store that already holds the invariant. Every write passes
        through the *one* modelled resource, so ``arm`` ignores which operation it
        is handed: the parametrised cases (#370) exercise the same ``held()`` path
        on the fake and earn their keep on the ``sqlite3`` store, where each
        operation is a separate lock site. Nothing to dispose of, hence the bare
        yield.
        """
        store = FakePlanStore(now=_fixed_now)
        yield SuspendedMidWrite(
            store=store,
            log=store.resource_log,
            arm=lambda _operation: store.suspend_next_operation(),
        )


class TestFakePlannerContract(PlannerContract):
    """Runs FakePlanner through the shared Planner conformance suite."""

    @pytest.fixture
    def planner(self) -> Planner:
        return FakePlanner(now=_fixed_now)

    @pytest.fixture
    def asking_planner(self) -> Planner | None:
        """The fake arranged to ask for a read, so ADR-0226 §4's arms bind on it.

        Both kinds at once, which is the widest emission the envelope admits — one
        ask of each, the hop at its two-label cap (ADR-0226 §§1-2, §6). The labels
        are the ones the suite's own supply would carry, though nothing here checks
        that: §3 gives resolution to the loop, and a fake that filtered its own
        emission would hide the drop §9's audit exists to count.
        """
        return FakePlanner(
            now=_fixed_now,
            read_request=ReadRequest(
                asks=(
                    ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1", "M2")),
                    ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="which lender did you recommend?"),
                )
            ),
        )


async def test_a_fresh_fake_does_not_reuse_a_prior_instances_execution_id() -> None:
    """The fake matches ``InMemoryPlanStore``'s cross-restart non-reuse (#280).

    A new instance rewinds the sequence to 0, so without the per-instance
    incarnation nonce it would re-mint a prior instance's id. The fake must keep
    this or it would certify a store that reuses ids across restarts — the exact
    hazard ADR-0044 §1 forbids. Impl-level, like the real store's twin, because
    "restart" for an in-memory double is a new instance.
    """
    from plan_store_contract import _goal, _plan  # noqa: PLC0415

    async def start(store: FakePlanStore) -> str:
        await store.save_goal(_goal())
        await store.save_plan(_plan())
        return (await store.start_execution("p1")).id

    first_id = await start(FakePlanStore(now=_fixed_now))
    second_id = await start(FakePlanStore(now=_fixed_now))
    assert first_id != second_id


async def test_fake_planner_records_what_it_was_asked() -> None:
    """Beyond the contract: the fake exists to let callers assert on the call."""
    planner = FakePlanner(now=_fixed_now)
    goal = Goal(
        id="g1",
        statement="ship it",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_fixed_now()
        ),
        created_at=_fixed_now(),
    )
    context = CurrentContext(
        now=_fixed_now(),
        time_of_day=TimeOfDay.MORNING,
        is_weekend=False,
        within_working_hours=True,
    )

    await planner.plan(goal, context=context, capabilities=("send_email",))

    assert len(planner.calls) == 1
    assert planner.calls[0][0].id == "g1"
    # ADR-0211 §9 item 3: the vocabulary is recorded as handed, so a test over the
    # loop can assert what the planner was told without standing a model up.
    assert planner.calls[0][3] == ("send_email",)


# --- ADR-0228 §3: a turn may call this fake twice ----------------------------


def _goal_for(goal_id: str = "g1") -> Goal:
    return Goal(
        id=goal_id,
        statement="relocate to Lisbon",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_fixed_now()
        ),
        created_at=_fixed_now(),
    )


def _context_for() -> CurrentContext:
    return CurrentContext(
        now=_fixed_now(), time_of_day=TimeOfDay.MORNING, is_weekend=False, within_working_hours=True
    )


async def test_a_synthesised_plan_takes_a_fresh_id_on_every_call_after_the_first() -> None:
    """ADR-0014 §2's new-id rule, which ADR-0228 §3 makes bind within one turn.

    The loop stamps a turn's second plan as superseding the first, and
    ``PlanStore.save_plan`` refuses a ``supersedes`` naming the saving plan's own id
    (ADR-0228 §5) — so a fake answering one id twice would fail its consumer for its
    own defect, at the store, where the consumer would blame the store.

    The **first** call keeps the id this fake has always minted, so nothing that named
    it moves.
    """
    planner = FakePlanner(now=_fixed_now)

    first = await planner.plan(_goal_for(), context=_context_for(), capabilities=())
    second = await planner.plan(_goal_for(), context=_context_for(), capabilities=())

    assert first.id == "g1-plan", "the id this fake has always minted"
    assert second.id != first.id


async def test_a_scripted_plan_also_takes_a_fresh_id_and_changes_in_nothing_else() -> None:
    """The scripted path conforms too, and moves exactly the field the contract moves.

    A consumer scripting a plan that carries a ``read_request`` drives a revising turn
    on a budgeted operation, so this path reaches two calls as readily as the
    synthesised one does. Returning the scripted plan unchanged would reuse its id;
    returning it with a fresh id is the fake **conforming**, because ``id`` is
    precisely the field ADR-0014 §2 requires to move and every other field is the
    consumer's own.
    """
    scripted = ActionPlan(
        id="scripted-1",
        goal_id="g1",
        steps=(),
        created_at=_fixed_now(),
        rationale="the consumer's own",
        read_request=ReadRequest(asks=(ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),)),
    )
    planner = FakePlanner(scripted, now=_fixed_now)

    first = await planner.plan(_goal_for(), context=_context_for(), capabilities=())
    second = await planner.plan(_goal_for(), context=_context_for(), capabilities=())

    assert first is scripted, "exactly as scripted on the first call"
    assert second.id != scripted.id
    for field in ActionPlan.model_fields:
        if field == "id":
            continue
        assert getattr(second, field) == getattr(scripted, field), f"{field} is unchanged"


async def test_a_scripted_revision_answers_the_call_after_the_first() -> None:
    """``revision`` is the hook for the milestone's own shape (ADR-0228 §13 item 1).

    A first plan that cannot name a value and asks for it, and a second that carries
    it — scripted, without standing a model up.
    """
    first_plan = ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_fixed_now())
    revision = ActionPlan(
        id="p2", goal_id="g1", steps=(), created_at=_fixed_now(), rationale="the revision"
    )
    planner = FakePlanner(first_plan, now=_fixed_now, revision=revision)

    first = await planner.plan(_goal_for(), context=_context_for(), capabilities=())
    second = await planner.plan(_goal_for(), context=_context_for(), capabilities=())

    assert first is first_plan
    assert second is revision


def test_a_script_whose_two_plans_share_an_id_is_refused() -> None:
    """A script no conforming planner could satisfy is refused at construction.

    A turn persists both plans and ``save_plan`` refuses a ``supersedes`` naming the
    saving plan's own id (ADR-0228 §5), so two plans sharing one is not a fake that
    behaves oddly — it is a fake that cannot be used at all. Refused here rather than
    surfacing as a store error the consumer would blame the store for.
    """
    shared = ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_fixed_now())
    with pytest.raises(ValueError, match="two records with two ids"):
        FakePlanner(shared, now=_fixed_now, revision=shared)

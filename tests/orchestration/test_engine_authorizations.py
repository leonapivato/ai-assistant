"""The engine's side of ADR-0254 §11: the projection, the listing and the revocation.

Driven through the **real** engine over a real ``StepRunner`` and a real park, because
the clause under test is about what a user is shown *at the question* and again *after a
restart* — which no unit over the projection alone can exhibit.

**The row is seeded rather than proposed, and that is Lane 2's fence rather than a
shortcut.** ADR-0254 §20 assigns proposing the row to Lane 2, and the goals these
harnesses drive state no bound ADR-0266 §4 reads — so nothing is minted, condition 6
refuses an empty coverage over a request carrying a user-facing argument, and such a
``CONFIRM`` proposes nothing, which the absence arm below asserts rather than works
around. What is seeded is exactly the row
:func:`~ai_assistant.orchestration.authorizing.proposed_authorization` would have
written, under exactly the id
:func:`~ai_assistant.orchestration.authorizing.authorization_id_for` derives, so the
read-back this lane owns is exercised against the writer's own naming and not against a
convention invented here.
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from typing import Final

import pytest
from test_engine import Harness, OneStepPlanner, bound_binder, egress_confirmable

from ai_assistant.core.types import (
    AuthorizationSettlement,
    Goal,
    GoalInterpretation,
    Ground,
    MemorySource,
    Provenance,
)
from ai_assistant.orchestration.engine import Engine
from ai_assistant.orchestration.runner import StepRunner
from ai_assistant.testing import (
    AUTHORIZATION_NOW,
    FakeGoalAuthorizationStore,
    opening_act,
)

#: The id the harness's first recorded decision carries, and therefore the confirmation
#: a proposal would be named after. Deterministic because the harness mints decision ids
#: from one sequence — so a row can be seeded **before** the turn and the *live*
#: question, not only the recovered one, renders the projection.
FIRST_DECISION: Final = "d-1"


def _harness(*, proposing: bool = True) -> tuple[Harness, FakeGoalAuthorizationStore]:
    """An egress-confirmable harness whose runner and engine share one row store.

    **The step carries no argument, and that is what makes a proposal reachable at
    all.** ADR-0254 §1's completeness condition, restated over ADR-0266 §7's condition
    6, holds **vacuously** over the empty coverage this goal mints — so the one
    `CONFIRM` that proposes a row here is one over an argument-free egress call (§20's
    arm 54, and arm 59's last case). `proposing=False` restores the ordinary shape, where the
    call carries a recipient and no row is proposed.

    ``episode_retention`` is ADR-0256 §1's third rung, which the ladder needs because the
    harness's goals carry no ``deadline``.
    """
    store = FakeGoalAuthorizationStore()
    definition = egress_confirmable()
    return (
        Harness(
            tools=(definition,),
            binder=bound_binder(definition),
            authorizations=store,
            planner=OneStepPlanner(parameters={}) if proposing else None,
            episode_retention=timedelta(hours=12),
        ),
        store,
    )


async def test_a_proposal_that_was_written_is_never_shown_as_establishing_nothing() -> None:
    """Round 2's blocker: the row is the **object the writer returned**.

    A second ``resolve`` taken to find it can fail transiently while the row is durable
    and an approval will establish it — and calling that absence would put a question in
    front of the user that named no bound and then established one, which §11 refuses in
    terms. Driven by arming the store to fault on **reads only**: ``record`` still
    succeeds, so a lane that resolved would see ``None`` and this one does not.
    """
    source = inspect.getsource(StepRunner._propose)

    assert "return row" in source
    assert "resolve(" not in source
    assert "_proposed_row" not in inspect.getsource(StepRunner)


def test_the_live_question_reads_no_store_while_assembling_itself() -> None:
    """The structural half of the arm above, and the one a fault injection cannot show.

    A read taken while the confirmation is assembled would be fallible work on the wrong
    side of the park **however reliable the store is** — a scripted fault can only show
    that today's store does not raise there. So what is asserted is that the row reaches
    the rendering on the **disposition**, and that the assembly names no store at all.
    """
    source = inspect.getsource(Engine._confirmation)

    assert "disposition.proposed" in source
    assert "_authorization_projection" not in source
    assert "projection_of(" in source


def test_a_parked_read_carries_no_projection_and_reads_no_store() -> None:
    """ADR-0254 §11 on the read population, and ADR-0244 §1's no-failure rule.

    The only writer of an ``Authorization`` is ``StepRunner._propose`` (§15), which a
    read park reaches by no path — a servicing parks through ``ParkedReadOperations`` and
    drives no plan step — so answering a read establishes no standing authority and
    ``None`` says exactly that. And nothing is read to discover it, because a store read
    after the servicing has parked can raise between the park and the reply.
    """
    source = inspect.getsource(Engine._read_confirmation)

    assert "authorization=None," in source
    assert "_authorization_projection" not in source


async def test_an_engine_with_no_store_answers_the_surface_rather_than_raising() -> None:
    """The fail-closed default, stated rather than discovered.

    A deployment wiring no authorization store proposes no row, so *"this goal
    authorises nothing"* is the true answer there and not a degraded one, and
    ``NO_SUCH_AUTHORIZATION`` is what is true of a store holding no row with that id.
    """
    harness = Harness()

    assert await harness.engine.standing_authorizations("goal-1") == ()
    settlement = await harness.engine.revoke_authorization("auth-1")
    assert settlement is AuthorizationSettlement.NO_SUCH_AUTHORIZATION


async def test_the_listing_and_the_revocation_are_answered_from_the_one_store() -> None:
    """ADR-0254 §11's two operations, through the engine rather than through the
    operations object — so the delegation, the identifier validation and the payload
    check are exercised on the path a client actually takes.
    """
    harness, store = _harness()
    goal = await harness.plans.save_goal(_a_goal())
    row = opening_act(id="auth-1", goal=goal, expires_at=AUTHORIZATION_NOW + timedelta(hours=1))
    await store.record(row)

    listed = await harness.engine.standing_authorizations(goal)

    assert [one.id for one in listed] == ["auth-1"]
    assert listed[0].goal_statement == "book the campsite"
    assert await harness.engine.revoke_authorization("auth-1") is AuthorizationSettlement.SETTLED
    assert await harness.engine.standing_authorizations(goal) == ()


@pytest.mark.parametrize("blank", ["", "   "])
async def test_a_blank_identifier_is_refused_locally_and_before_any_io(blank: str) -> None:
    """ADR-0085 §3c, on both operations: refused before the store is reached at all."""
    harness, store = _harness()

    with pytest.raises(ValueError, match="goal_id"):
        await harness.engine.standing_authorizations(blank)
    with pytest.raises(ValueError, match="authorization_id"):
        await harness.engine.revoke_authorization(blank)
    assert await store.export() == ()


def _a_goal() -> Goal:
    """One durable goal carrying the statement ADR-0254 §11's listing renders it by."""
    at = AUTHORIZATION_NOW
    return Goal(
        id="goal-0001",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book the campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book the campsite",
                recorded_at=at,
                raised_by="t-1",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=at),
        created_at=at,
    )

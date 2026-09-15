"""The engine's side of ADR-0254 §11: the projection, the listing and the revocation.

Driven through the **real** engine over a real ``StepRunner`` and a real park, because
the clause under test is about what a user is shown *at the question* and again *after a
restart* — which no unit over the projection alone can exhibit.

**The row is seeded rather than proposed, and that is Lane 2's fence rather than a
shortcut.** ADR-0254 §20 assigns proposing the row to Lane 2, and issue #2373 leaves it
unable to mint a ``CoverageMember`` for a named argument at all — so on this tree a
``CONFIRM`` over a request carrying a user-facing argument proposes nothing, which the
absence arm below asserts rather than works around. What is seeded is exactly the row
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
from test_engine import (
    PATIENT,
    Harness,
    OneStepPlanner,
    _fresh_facade,
    bound_binder,
    egress_confirmable,
)

from ai_assistant.core.types import (
    AuthorizationDisposition,
    AuthorizationSettlement,
    Disposition,
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
    all.** ADR-0254 §1's completeness condition — every user-facing argument named by a
    member — holds only **vacuously** while issue #2373 stands, so the one `CONFIRM`
    that proposes a row on this tree is one over an argument-free egress call (§20's arm
    54, and arm 59's last case). `proposing=False` restores the ordinary shape, where the
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


async def test_the_question_carries_what_answering_would_establish() -> None:
    """ADR-0254 §11: *"the projection is rendered from the proposed row and is not
    recomputed"*, and §20 arm 22's *"the `CONFIRM` that would establish one names the
    instant"*.

    The row is written ``PROPOSED`` before the question is put, so what reaches the
    user is a rendering of a durable record: the same coverage, the same bound, the same
    span and the same ``expires_at``.
    """
    harness, store = _harness()

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    confirmation = outcome.step.confirmation
    assert confirmation is not None
    projection = confirmation.authorization
    assert projection is not None
    (row,) = await store.export()
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert projection.expires_at == row.expires_at
    # §20 arm 54: an argument-free call proposes a row whose ``coverage`` is empty, and
    # the projection is **present** and transcribes it. Omitting it would say falsely
    # that answering establishes no authority.
    assert projection.coverage == ()


async def test_the_projection_names_no_identifier_at_all() -> None:
    """ADR-0254 §11: *"The confirmation's projection names no identifier"*.

    Not the goal's id, not the authorization's, not the connection reference, not a
    credential slot and not a ``Settings`` field — because a confirmation is about a row
    the user has not established, so there is nothing yet to withdraw.

    **Asserted over the serialised member**, because that is what actually reaches a
    client, and the row it was built from carries every one of those values.
    """
    harness, store = _harness()

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    (row,) = await store.export()
    assert outcome.step is not None
    assert outcome.step.confirmation is not None
    projection = outcome.step.confirmation.authorization
    assert projection is not None
    rendered = projection.model_dump_json()
    assert row.id not in rendered
    assert row.goal not in rendered
    assert row.account.reference not in rendered
    assert row.subject_digest not in rendered
    assert "supersedes" not in rendered
    assert "confirmation" not in rendered
    assert "destinations" not in rendered


async def test_a_confirmation_that_proposed_no_row_carries_no_projection() -> None:
    """ADR-0254 §1: *"`Confirmation.authorization` is absent (§11)"* — and on this tree
    that is **every** confirmation over a request carrying a user-facing argument.

    §1's completeness condition holds only vacuously while issue #2373 stands, so a row
    is proposed for no ordinary egress call and the answer establishes nothing: the
    `CONFIRM` is resolved and the one call is authorised by ADR-0148 §3's route (a).
    """
    harness, store = _harness(proposing=False)

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.confirmation is not None
    assert outcome.step.confirmation.authorization is None
    assert await store.export() == ()


async def test_a_restart_renders_the_same_projection() -> None:
    """ADR-0254 §11 and §20 arm 40: *"A restart between the question and the answer
    recovers the row and renders the same projection"*.

    Which is ADR-0052 §1's recovery reading a durable record rather than reconstructing
    a proposal nobody stored — and it is why §1 writes the row first rather than at the
    answer. Asserted by **equality** against the live member, so a field added later is
    covered without this case being edited.
    """
    harness, _ = _harness()
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    live = parked.step.confirmation
    assert live is not None
    assert live.authorization is not None

    fresh = _fresh_facade(harness)
    pending = await fresh.pending_confirmations()

    assert len(pending) == 1
    assert pending[0].authorization == live.authorization


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


async def test_a_recovered_confirmation_whose_row_cannot_be_read_is_withheld() -> None:
    """Round 2's second blocker, and ADR-0178 §4's own degradation.

    *"A surface that cannot render it may refuse that confirmation rather than every
    confirmation."* A row the store merely failed to return may be durable, so rendering
    the question with ``authorization`` ``None`` would state that answering establishes
    no standing authority — which it may well do. The park is withheld from **this**
    listing and the rest of it stands; nothing is settled, nothing is lost, and the next
    enumeration over a working store offers it again.
    """
    harness, store = _harness()
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    fresh = _fresh_facade(harness)
    assert len(await fresh.pending_confirmations()) == 1

    store.fail_reads()

    assert await fresh.pending_confirmations() == ()


async def test_a_store_that_cannot_be_read_does_not_fail_the_parking_turn() -> None:
    """ADR-0244 §1: the turn *"does not park, is not suspended and does not fail"*, and
    :meth:`Engine._confirmation`'s own contract that *"no fallible work remains between
    parking the step and offering its token"* (#287).

    The read that finds the projection is taken **before** the park is committed
    (``StepRunner._proposed_row``), so a store that cannot be read costs the disclosure
    and never the turn: the step parks, the token is offered, and the question is the one
    a deployment holding no rows would have put. Adversarial review, round 1,
    ``blocker``.
    """
    harness, store = _harness()
    store.fail_reads()

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    assert outcome.step.confirmation is not None
    assert outcome.step.confirmation.token.handle
    # **And `None` is honest here rather than a degradation**: `_propose` reads
    # `standing` before it writes, so a store that cannot be read wrote no row either
    # and answering really does establish nothing (ADR-0254 §1). The case round 2 is
    # about — a row that *was* written and could not be read back — is closed by
    # construction, because there is no second read to fail.
    assert outcome.step.confirmation.authorization is None


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

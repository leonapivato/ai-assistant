"""The path-(i) proposal and its expiry ladder (ADR-0254 §1, §12; ADR-0256).

These are the total functions ADR-0254 §1's four conditions and ADR-0256 §1's
ladder are stated as, exercised directly. What a turn then *does* with a
proposal — writing it, settling it on the answer — is
``test_runner_authorizations.py``'s.

**No row here carries a coverage member**, because no clause of the corpus says
how one is minted from a recorded act (issue #2373, ruled into ADR-0266).
ADR-0254 §1's completeness condition therefore holds only vacuously, which is
§10's own fail-closed sentence and §20 arm 59's third case; the arms that need a
non-empty ``coverage`` are named in the pull request and are not shipped here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from authorizing_builders import (
    ACCOUNT,
    AT,
    GOAL,
    RETENTION,
    a_binding,
    a_decision,
    a_goal,
    a_request,
    a_tool,
)

from ai_assistant.core.types import (
    Authorization,
    AuthorizationDisposition,
    AuthorizationOrigin,
    Goal,
    PermissionOutcome,
    PermissionRuling,
    SpanCoverage,
)
from ai_assistant.orchestration.authorizing import (
    horizon,
    proposal_of,
    proposed_authorization,
    user_facing_arguments,
)

# --- ADR-0256 §1's ladder ------------------------------------------------


def test_rung_2_takes_the_goals_own_deadline() -> None:
    """ADR-0254 §12's rung 2, transcribed unchanged."""
    deadline = AT + timedelta(hours=12)

    assert horizon(AT, goal=a_goal(deadline=deadline), retention=RETENTION) == deadline


def test_rung_2_is_not_displaced_by_a_finite_window() -> None:
    """ADR-0256 §9: rung 2 is taken though a window exists and would differ."""
    deadline = AT + timedelta(hours=12)
    assert deadline != AT + RETENTION

    assert horizon(AT, goal=a_goal(deadline=deadline), retention=RETENTION) == deadline


def test_the_ordinary_case_takes_the_retention_window() -> None:
    """ADR-0256 §9's ordinary case: no deadline, no stated instant, a finite window."""
    assert horizon(AT, goal=a_goal(deadline=None), retention=RETENTION) == AT + RETENTION


@pytest.mark.parametrize("deadline", [AT, AT - timedelta(seconds=1)], ids=["equal", "stale"])
def test_a_stale_or_equal_deadline_reaches_rung_3_not_rung_2(deadline: datetime) -> None:
    """ADR-0256 §9: rung 2 does not take it, and a row **is** written on rung 3.

    That arm exists because it is "the one an implementation keeping the old
    no-row behaviour would otherwise still pass".
    """
    assert horizon(AT, goal=a_goal(deadline=deadline), retention=RETENTION) == AT + RETENTION


def test_a_window_of_none_writes_no_row() -> None:
    """ADR-0256 §3: "keep forever" is not a horizon to invent one against."""
    assert horizon(AT, goal=a_goal(deadline=None), retention=None) is None


def test_a_stale_deadline_and_no_window_writes_no_row() -> None:
    """ADR-0254 §12's ratified rung 3, standing as the ladder's last (ADR-0256 §3)."""
    assert horizon(AT, goal=a_goal(deadline=AT), retention=None) is None


def test_a_goal_the_store_no_longer_holds_falls_to_rung_3() -> None:
    """An absent goal takes rung 2 out; it is not an error and invents nothing."""
    assert horizon(AT, goal=None, retention=RETENTION) == AT + RETENTION


def test_the_arithmetic_edge_writes_no_row() -> None:
    """ADR-0256 §2: "Nothing is clamped, rounded, saturated or defaulted."."""
    near_max = datetime.max.replace(tzinfo=UTC) - timedelta(seconds=1)

    assert horizon(near_max, goal=a_goal(deadline=None), retention=RETENTION) is None


def test_a_deadline_the_ladder_takes_is_never_clamped_by_the_window() -> None:
    """ADR-0256 §6: rung 2 takes no ceiling from this decision."""
    far = AT + timedelta(days=3650)

    assert horizon(AT, goal=a_goal(deadline=far), retention=RETENTION) == far


# --- ADR-0254 §3's user-facing arguments ---------------------------------


def test_a_declaration_classifying_nothing_has_every_argument_user_facing() -> None:
    """ADR-0254 §3: "Every key it does not name is user-facing"."""
    request = a_request(
        parameters={"to": "a@example.com", "subject": "hi"},
    )

    assert set(user_facing_arguments(request)) == {"to", "subject"}


def test_a_system_supplied_key_is_not_user_facing() -> None:
    """ADR-0254 §3: the classification narrows what is compared and nothing else."""
    request = a_request(
        tool=a_tool(system_supplied=("idempotency_key",)),
        parameters={"to": "a@example.com", "idempotency_key": "k-1"},
    )

    assert user_facing_arguments(request) == ("to",)


def test_a_request_carrying_only_system_supplied_arguments_has_none() -> None:
    """ADR-0254 §3: "A request carrying system-supplied arguments and no others"."""
    request = a_request(
        tool=a_tool(system_supplied=("idempotency_key",)),
        parameters={"idempotency_key": "k-1"},
    )

    assert user_facing_arguments(request) == ()


# --- ADR-0254 §1's four conditions (§20 arm 59) --------------------------


def _proposed(
    *,
    request_kwargs: dict[str, object] | None = None,
    goal: Goal | None = None,
    retention: timedelta | None = RETENTION,
    standing: tuple[Authorization, ...] = (),
) -> Authorization | None:
    """Run the four conditions over one varied input."""
    request = a_request(**(request_kwargs or {}))  # type: ignore[arg-type]  # heterogeneous test kwargs
    return proposed_authorization(
        request,
        a_decision(),
        goal=a_goal(deadline=AT + timedelta(hours=12)) if goal is None else goal,
        retention=retention,
        standing=standing,
        id_factory=lambda: "auth-1",
    )


def test_a_confirm_meeting_all_four_conditions_proposes_a_row() -> None:
    """ADR-0254 §1, §20 arm 59's last clause, and arm 54's proposal half.

    An argument-free egress call: the row carries ``coverage=()``, which §1
    permits and which covers exactly one request — one carrying no argument at
    all.
    """
    row = _proposed()

    assert row is not None
    assert row.id == "auth-1"
    assert row.goal == GOAL
    assert row.coverage == ()
    assert row.origin is AuthorizationOrigin.CONFIRMED
    assert row.disposition is AuthorizationDisposition.PROPOSED
    assert row.settled_at is None
    assert row.confirmation == "d-1"
    assert row.supersedes is None
    assert row.proposed_at == AT
    assert row.expires_at == AT + timedelta(hours=12)
    assert row.account == ACCOUNT
    assert row.destinations == a_binding().canonical_destination_set


def test_a_request_carrying_no_goal_proposes_nothing() -> None:
    """ADR-0254 §1: such a request "reaches route (d) in no case"."""
    assert _proposed(request_kwargs={"goal": None}) is None


def test_a_request_carrying_no_egress_binding_proposes_nothing() -> None:
    """ADR-0254 §1: "every clause of this decision is scoped to one"."""
    assert _proposed(request_kwargs={"binding": None}) is None


def test_a_request_carrying_a_user_facing_argument_proposes_nothing() -> None:
    """ADR-0254 §20 arm 59's third case, on #2373's blocked minting.

    "a `CONFIRM` on an egress request one of whose arguments no resolution minted
    a member for → **no row is written**". Every user-facing argument is such an
    argument until ADR-0266 lands.
    """
    assert _proposed(request_kwargs={"parameters": {"to": "a@example.com"}}) is None


def test_a_request_carrying_only_system_supplied_arguments_proposes_a_row() -> None:
    """ADR-0254 §3: such a request carries no user-facing argument, so §1 holds.

    The completeness condition is over **user-facing** arguments alone, so a
    declaration that classifies its whole parameter set is one whose calls this
    lane can still found an authority on.
    """
    row = _proposed(
        request_kwargs={
            "tool": a_tool(system_supplied=("idempotency_key",)),
            "parameters": {"idempotency_key": "k-1"},
        }
    )

    assert row is not None
    assert row.coverage == ()


def test_a_ladder_yielding_no_instant_proposes_nothing() -> None:
    """ADR-0254 §1's fourth condition, and §20 arm 69's no-row case."""
    assert _proposed(goal=a_goal(deadline=None), retention=None) is None


# --- the supersession a proposal names (ADR-0254 §1, §5) -----------------


def _established(tool_id: str = "smtp") -> Authorization:
    """An `ESTABLISHED` row of this goal and that declaration id."""
    return Authorization(
        id=f"auth-prior-{tool_id}",
        goal=GOAL,
        tool=a_tool(tool_id=tool_id),
        account=ACCOUNT,
        destinations=a_binding().canonical_destination_set,
        origin=AuthorizationOrigin.CONFIRMED,
        coverage=(),
        proposed_at=AT - timedelta(hours=2),
        expires_at=AT + timedelta(hours=2),
        confirmation="d-0",
        supersedes=None,
        disposition=AuthorizationDisposition.ESTABLISHED,
        settled_at=AT - timedelta(hours=2),
    )


def test_a_proposal_names_the_standing_row_of_that_pair() -> None:
    """ADR-0254 §1: a path-(i) proposal may name any `ESTABLISHED` row of the pair.

    Naming it is what keeps the uniqueness rule satisfiable: approving a second
    row of one pair would otherwise answer `WOULD_DUPLICATE` and establish
    nothing.
    """
    row = _proposed(standing=(_established(),))

    assert row is not None
    assert row.supersedes == "auth-prior-smtp"


def test_a_proposal_names_no_row_of_another_declaration() -> None:
    """The uniqueness key is the goal and the declaration **id** (ADR-0254 §1)."""
    row = _proposed(standing=(_established(tool_id="other"),))

    assert row is not None
    assert row.supersedes is None


def test_a_proposal_names_a_lapsed_row_of_that_pair() -> None:
    """ADR-0254 §1: "live or expired" — "That is what renews an authority"."""
    lapsed = _established().model_copy(update={"expires_at": AT - timedelta(minutes=1)})

    row = _proposed(standing=(lapsed,))

    assert row is not None
    assert row.supersedes == "auth-prior-smtp"


# --- finding the proposal an answer names --------------------------------


def test_the_proposal_is_found_by_the_confirmation_it_names() -> None:
    """ADR-0254 §16 carries no lookup by `confirmation`, so `recent` is read back."""
    mine = _proposed()
    assert mine is not None
    other = mine.model_copy(update={"id": "auth-2", "confirmation": "d-9"})

    assert proposal_of((other, mine), "d-1") is mine


def test_an_unfound_proposal_is_none_and_never_a_raise() -> None:
    """Not finding it settles nothing, which loses an authority and grants none."""
    assert proposal_of((), "d-1") is None


def test_the_lookup_never_answers_with_another_confirmations_row() -> None:
    """One answer settles one question."""
    mine = _proposed()
    assert mine is not None

    assert proposal_of((mine,), "d-9") is None


# --- what a proposal deliberately does not read (ADR-0254 §1) ------------


#: Every ``SpanCoverage`` an egress binding over external content can carry.
#: ``PATH_WITHOUT_MODEL`` is refused at construction by ADR-0155 §3 and ADR-0233
#: §6 — "forbidden absolutely, whatever any authorisation, policy, grant or user
#: answer says" — so there is no such binding for a proposal to read a floor off.
_CARRIED_COVERAGES = (SpanCoverage.NOT_COVERED, SpanCoverage.MODEL_ON_EVERY_PATH)


@pytest.mark.parametrize(
    "coverage", _CARRIED_COVERAGES, ids=[member.name for member in _CARRIED_COVERAGES]
)
def test_the_proposal_reads_no_floor_of_route_ds(coverage: SpanCoverage) -> None:
    """ADR-0254 §1: "The proposal reads none of §6's floors, and that is deliberate".

    Conditions 3, 4 and 5 of route (d)'s reachability are taken over a concrete
    request at **every dispatch**, so putting them at the write would refuse an
    authority on the strength of one call's taint — "a different rule from the
    one §6 states and a weaker one". §20 arm 60 is this over the coverage limb.
    """
    binding = a_binding(coverage=coverage, planned_with_external_content=True)

    assert _proposed(request_kwargs={"binding": binding}) is not None


def test_the_outcome_test_is_the_writers_and_not_this_functions() -> None:
    """The four conditions say nothing about the ruling's outcome.

    Keeping that guard at the call site is what lets this stay a total function
    of the request and the decision, and it is pinned here so a later lane does
    not come to state it twice.
    """
    row = proposed_authorization(
        a_request(),
        a_decision(
            ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed outright")
        ),
        goal=a_goal(deadline=AT + timedelta(hours=12)),
        retention=RETENTION,
        standing=(),
        id_factory=lambda: "auth-1",
    )

    assert row is not None

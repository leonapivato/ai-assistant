"""ADR-0254 §11's two operations at the browser edge, and the views they cross in.

**Driven through a real socket** for ``test_gateway.py``'s reason, on
``test_gateway_streams``' own harness rather than a fourth copy of it.

**ADR-0177 §1's closed enumeration is widened by these two routes and ADR-0254 records
nothing against that document** — the shape issue #2274 records one decision earlier, and
filed as #2394 rather than folded into this lane, because an ADR text change is outside
it. What is asserted here is that the routes exist and answer, which is what ADR-0254
§11 and §20 require of *"the interface adapters that render them"*.
"""

from __future__ import annotations

import json
from datetime import timedelta
from http import HTTPStatus
from typing import Final

import pytest
from test_gateway_streams import _harness

from ai_assistant.core.types import (
    Authorization,
    AuthorizationSettlement,
    AuthorizationView,
    CanonicalDestination,
    ToolDefinition,
)
from ai_assistant.interfaces.gateway.server import _ASSISTANT_PATHS, _authorization_view
from ai_assistant.orchestration.authorization_surface import view_of
from ai_assistant.testing import (
    AUTHORIZATION_ACCOUNT,
    AUTHORIZATION_NOW,
    AUTHORIZATION_TOOL,
    FakeAssistantEngine,
    authorization,
    authorization_basis,
    coverage_member,
    money_bound,
    opening_act,
    period_bound,
    terms_bound,
)

#: The goal every listing here is about, and the statement §11 renders it by.
GOAL: Final = "goal-0001"
STATEMENT: Final = "book the campsite"

_LISTING: Final = "/authorizations"
_REVOKE: Final = "/authorization/revoke"


def _rendered_view(row: Authorization) -> AuthorizationView:
    """The :class:`AuthorizationView` ``orchestration`` would have assembled for ``row``.

    Built through the shipping projection rather than by hand, so every case below is
    about what the **gateway** does with a view and not about a second way of making one.
    """
    return view_of(row, goal_statement=STATEMENT, live=True)


def _engine(*, lapsed: bool = False) -> FakeAssistantEngine:
    """An engine holding one standing authority of :data:`GOAL`."""
    engine = FakeAssistantEngine()
    engine.hold_authorization(
        opening_act(
            id="auth-1",
            goal=GOAL,
            coverage=(
                coverage_member(
                    "amount",
                    bound=money_bound("50"),
                    basis=authorization_basis(span="up to fifty pounds"),
                ),
            ),
            expires_at=(
                AUTHORIZATION_NOW - timedelta(minutes=1)
                if lapsed
                else AUTHORIZATION_NOW + timedelta(hours=1)
            ),
        ),
        goal_statement=STATEMENT,
    )
    return engine


# --- the two routes -----------------------------------------------------------


def test_the_surface_admits_exactly_the_two_operations_the_decision_promotes() -> None:
    """ADR-0254 §16 calls its ``AssistantEngine`` roster complete at **two** members.

    A third path here would be a cross-subsystem operation no ADR decided (golden
    rule 5), and the listing is its own path rather than an empty answer of the act
    because the door classifies *"from its method and path alone"* (ADR-0168 §6).
    """
    reached = {
        method: operation
        for (verb, method), operation in _ASSISTANT_PATHS.items()
        if "authoriz" in method
    }

    assert reached == {
        _LISTING: "standing_authorizations",
        _REVOKE: "revoke_authorization",
    }
    assert ("GET", _LISTING) not in _ASSISTANT_PATHS


async def test_the_listing_answers_with_one_view_per_standing_row() -> None:
    """§11's listing, over the wire, with every field the view carries."""
    async with _harness(_engine()) as one:
        status, body = await one.whole("POST", _LISTING, {"goal_id": GOAL})

    assert status == HTTPStatus.OK
    (view,) = body["authorizations"]
    assert set(view) == {
        "id",
        "goal_statement",
        "tool_id",
        "tool_description",
        "coverage",
        "expires_at",
        "live",
    }
    assert view["id"] == "auth-1"
    assert view["goal_statement"] == STATEMENT
    assert view["tool_id"] == AUTHORIZATION_TOOL.id
    assert view["live"] is True


async def test_a_goal_with_nothing_standing_answers_an_empty_listing() -> None:
    """§11: a goal this system holds no record of is an empty listing and never a raise."""
    async with _harness(FakeAssistantEngine()) as one:
        status, body = await one.whole("POST", _LISTING, {"goal_id": GOAL})

    assert status == HTTPStatus.OK
    assert body["authorizations"] == []


async def test_the_listing_reports_a_lapsed_row_as_lapsed_and_still_renders_it() -> None:
    """§16 returns a lapsed row deliberately, and ``live`` is the **engine's** answer:
    this gateway holds no clock (ADR-0042 §6) and recomputes nothing.
    """
    async with _harness(_engine(lapsed=True)) as one:
        _, body = await one.whole("POST", _LISTING, {"goal_id": GOAL})

    (view,) = body["authorizations"]
    assert view["live"] is False


async def test_the_revocation_crosses_the_stores_own_vocabulary_unmapped() -> None:
    """§16: the member crosses *"unmapped and unrenamed"*, as its own value.

    A second three-valued spelling for one fact is the second carrier ADR-0150 is named
    after, so this gateway translates nothing and the page renders prose from the member.
    """
    async with _harness(_engine()) as one:
        status, body = await one.whole("POST", _REVOKE, {"authorization_id": "auth-1"})
        _, after = await one.whole("POST", _LISTING, {"goal_id": GOAL})

    assert status == HTTPStatus.OK
    assert body == {"settlement": AuthorizationSettlement.SETTLED.value}
    assert after["authorizations"] == []


@pytest.mark.parametrize(
    ("row_id", "settlement"),
    [
        ("auth-nobody", AuthorizationSettlement.NO_SUCH_AUTHORIZATION),
        ("auth-open", AuthorizationSettlement.NOT_AT_SOURCE),
    ],
)
async def test_a_withdrawal_that_moves_nothing_is_a_result_and_never_a_fault(
    row_id: str, settlement: AuthorizationSettlement
) -> None:
    """An unknown id and a row not at the edge's source both answer 200 with a member.

    ``AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception``'s rule,
    reaching the surface: neither is an error status and neither is an exception.
    """
    engine = _engine()
    engine.hold_authorization(
        authorization(id="auth-open", goal=GOAL, confirmation="d-1"), goal_statement=STATEMENT
    )
    async with _harness(engine) as one:
        status, body = await one.whole("POST", _REVOKE, {"authorization_id": row_id})

    assert status == HTTPStatus.OK
    assert body == {"settlement": settlement.value}


# --- the rendering bar, over the view itself (ADR-0254 §20 arm 62) ------------


def test_the_view_carries_the_id_and_no_other_internal_value() -> None:
    """§20 arm 62, taken over a record whose destination set is **the connected
    account** — which is the case :class:`CanonicalDestination`'s account arm would have
    carried a ``BoundAccount.reference`` through, and the reason §11 renders no
    destination set at all.
    """
    row = opening_act(
        id="auth-1", goal=GOAL, destinations=(CanonicalDestination(account=AUTHORIZATION_ACCOUNT),)
    )
    assert row.destinations[0].account is not None, "the case is about the account arm"
    rendered = json.dumps(_authorization_view(_rendered_view(row)))

    assert "auth-1" in rendered
    assert row.goal not in rendered
    assert row.account.reference not in rendered
    assert row.account.identity not in rendered
    assert row.subject_digest not in rendered
    assert "supersedes" not in rendered
    assert "confirmation" not in rendered
    assert "resolution" not in rendered
    assert "destinations" not in rendered


def test_a_fixed_value_crosses_as_text_so_a_large_integer_is_not_a_double() -> None:
    """:func:`_parameter_text`'s rule, reaching a second member.

    A JSON number read by ``JSON.parse`` becomes a double, so an integer above ``2**53``
    would reach the person **changed** — and a rendering showing a value the record does
    not hold is worse than one showing none.
    """
    exact = 9007199254740993
    row = opening_act(
        id="auth-1",
        goal=GOAL,
        coverage=(
            coverage_member("count", fixed=exact, basis=authorization_basis(span="that many")),
        ),
    )

    view = _authorization_view(_rendered_view(row))

    assert view["coverage"][0]["fixed"] == str(exact)
    assert view["coverage"][0]["bound"] is None
    assert view["coverage"][0]["span"] == "that many"


def test_every_bound_kind_crosses_with_every_field_the_page_branches_on() -> None:
    """ADR-0254 §2's three kinds. The page renders a statement per kind, so every field
    those statements read has to arrive — and a bound missing one would render with
    ``undefined`` in it or, worse, as a blank limit.
    """
    row = opening_act(
        id="auth-1",
        goal=GOAL,
        coverage=(
            coverage_member("amount", bound=money_bound("60", minimum="10")),
            coverage_member("when", bound=period_bound()),
            coverage_member("terms", bound=terms_bound("refundable", "flexible")),
        ),
    )

    coverage = _authorization_view(_rendered_view(row))["coverage"]

    money, period, terms = coverage
    assert money["bound"]["kind"] == "money"
    assert money["bound"]["maximum"] == "60"
    assert money["bound"]["minimum"] == "10"
    assert money["bound"]["currency"] == "GBP"
    assert period["bound"]["kind"] == "period"
    assert period["bound"]["starts_at"].endswith("+00:00")
    assert period["bound"]["timezone"] == "Europe/London"
    assert terms["bound"]["kind"] == "terms"
    assert terms["bound"]["terms"] == ["refundable", "flexible"]


def test_the_declaration_crosses_by_its_identifier_and_its_description() -> None:
    """§11: the declaration's own ``VisibleIdentifier`` and description — which is how
    two announcements of one act are told apart.
    """
    rail = ToolDefinition.model_validate(AUTHORIZATION_TOOL.model_dump() | {"id": "rail"})
    row = opening_act(id="auth-1", goal=GOAL, tool=rail)

    view = _authorization_view(_rendered_view(row))

    assert view["tool_id"] == "rail"
    assert view["tool_description"] == rail.description

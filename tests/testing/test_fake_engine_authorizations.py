"""The canonical fake's side of ADR-0254 §11, held to the concrete engine's boundaries.

**A fake that judged over a different boundary is worse than none**, which is ADR-0026
§7's rule and ADR-0085 §3's substitutability obligation: a consumer's test would pass
here and fail against a hub. So what is pinned is the one place the two could quietly
differ — *when* the clock is read relative to the snapshot — and the vocabulary a client
meets unmapped.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import AuthorizationDisposition, AuthorizationSettlement
from ai_assistant.testing import (
    AUTHORIZATION_NOW,
    FakeAssistantEngine,
    authorization,
    opening_act,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import Authorization

GOAL: Final = "goal-0001"
STATEMENT: Final = "book the campsite"


def _engine() -> FakeAssistantEngine:
    """An engine holding one live authority of :data:`GOAL`."""
    engine = FakeAssistantEngine()
    engine.hold_authorization(
        opening_act(id="auth-1", goal=GOAL, expires_at=AUTHORIZATION_NOW + timedelta(hours=1)),
        goal_statement=STATEMENT,
    )
    return engine


async def test_the_listing_reads_its_clock_after_the_snapshot() -> None:
    """The boundary the concrete engine takes, taken here too.

    A row settled ``ESTABLISHED`` while ``standing`` is suspended comes back carrying a
    ``settled_at`` **after** a reading taken first, and ADR-0254 §1's predicate would
    then report a live row as lapsed — a listing true at no real instant. Driven by
    settling the row from inside the store read, which is where a concurrent answer
    lands. Adversarial and architecture review, round 3.
    """
    engine = FakeAssistantEngine()
    engine.goal_statements[GOAL] = STATEMENT
    row = authorization(id="auth-1", goal=GOAL, confirmation="d-1")
    await engine.goal_authorizations.record(row)
    settled_at = AUTHORIZATION_NOW
    engine.authorization_clock = lambda: settled_at
    standing = engine.goal_authorizations.standing

    async def settling(goal: str) -> tuple[Authorization, ...]:
        await engine.goal_authorizations.settle(
            "auth-1", to=AuthorizationDisposition.ESTABLISHED, settled_at=settled_at
        )
        return await standing(goal)

    engine.goal_authorizations.standing = settling  # type: ignore[method-assign]

    (view,) = await engine.standing_authorizations(GOAL)

    assert view.live is True, "the row was established at the instant the listing reads"


async def test_a_goal_this_engine_holds_no_statement_for_is_an_empty_answer() -> None:
    """ADR-0254 §11's *"empty answer rather than a raise"*, and it is answered **before**
    the clock is reached — so the clause survives a non-conforming clock, exactly as it
    does on the concrete engine.
    """
    engine = FakeAssistantEngine()
    engine.authorization_clock = lambda: datetime(2026, 9, 13, 10, 0)  # noqa: DTZ001

    assert await engine.standing_authorizations("goal-nobody") == ()


async def test_a_non_conforming_clock_is_this_engines_own_error() -> None:
    """ADR-0026 §4's translation, so a consumer's test against a bad clock meets here
    what it would meet against a hub.
    """
    engine = _engine()
    engine.authorization_clock = lambda: datetime(2026, 9, 13, 10, 0)  # noqa: DTZ001

    with pytest.raises(PlanningError, match=r"\w"):
        await engine.standing_authorizations(GOAL)
    with pytest.raises(PlanningError, match=r"\w"):
        await engine.revoke_authorization("auth-1")


@pytest.mark.parametrize(
    ("row_id", "settlement"),
    [
        ("auth-1", AuthorizationSettlement.SETTLED),
        ("auth-nobody", AuthorizationSettlement.NO_SUCH_AUTHORIZATION),
    ],
)
async def test_the_revocation_answers_the_stores_own_word_unmapped(
    row_id: str, settlement: AuthorizationSettlement
) -> None:
    """ADR-0254 §16: the member crosses unmapped, so a client tested against this fake
    meets exactly the vocabulary a hub sends. **No call raises.**
    """
    engine = _engine()

    assert await engine.revoke_authorization(row_id) is settlement


async def test_a_revoked_row_is_absent_from_the_next_listing() -> None:
    """§20 arm 61's last clause, over a real store rather than a scripted list."""
    engine = _engine()
    assert len(await engine.standing_authorizations(GOAL)) == 1

    await engine.revoke_authorization("auth-1")

    assert await engine.standing_authorizations(GOAL) == ()


async def test_a_proposed_row_reaches_no_listing_and_is_not_revocable() -> None:
    """§1's graph and §16's ``standing``, both exhibited by the fake's real store."""
    engine = FakeAssistantEngine()
    engine.hold_authorization(
        authorization(id="auth-open", goal=GOAL, confirmation="d-1"), goal_statement=STATEMENT
    )

    assert await engine.standing_authorizations(GOAL) == ()
    assert await engine.revoke_authorization("auth-open") is AuthorizationSettlement.NOT_AT_SOURCE

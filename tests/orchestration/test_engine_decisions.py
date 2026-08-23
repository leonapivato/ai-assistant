"""The engine's two audit reads over a **real** store (ADR-0186 §11).

The shared suite holds all three implementations to ADR-0186 §2's order, §3's local
refusals and §3's oversized result. What it cannot hold any of them to is the row
this milestone exists for: a decision recorded before ADR-0181 §3's
``planned_with_external_content`` existed, which decodes carrying an
:class:`~ai_assistant.core.types.OriginUnrecordedBinding`. ADR-0184 §10 says why the
case belongs here and not there — it "is a property of a store that persists a
**serialised payload** and rebuilds it, and a fake holding objects has no bytes for
a shared case to seed" (ADR-0049 §5) — and ADR-0186 §11 states the shape it must
take: **one** such row among **several** ordinary ones, because a test whose trail
holds only the legacy row does not satisfy the clause.

**The failure that shape catches is the one ADR-0184 §5 closed and nothing else
would notice.** A reader that raised on the unreadable row would take every *other*
row down with it — the all-or-nothing failure — so a trail of one legacy row
exercises the tolerance and says nothing about whether the tolerance is
all-or-nothing. Here the legacy row sits in the middle of the order, so a whole-list
assertion fails on either mistake: dropping it, or losing the rows around it.

Driven through ``Engine`` rather than through ``SqliteAuditTrail`` directly, because
what ADR-0186 promotes is the *engine operation*: the store's own read half is
already pinned in ``tests/permissions/test_audit.py``, and what is unpinned without
this module is whether the operation a user will reach relays it whole.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from test_engine import Harness, confirmable

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
)
from ai_assistant.permissions import SqliteAuditTrail

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: When the seeded rulings were made. Fixed, so the order under test is the values'
#: rather than the run's.
_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

#: The four rows, as ``(id, seconds after`` :data:`_AT` ``)``, in recording order.
#: ``d-legacy`` is ruled second-newest, so it lands **in the middle** of ADR-0186
#: §2's order rather than at either end: a reader that dropped it, or that dropped
#: what surrounds it, changes the list in a way a whole-sequence assertion sees.
_ROWS: tuple[tuple[str, int], ...] = (
    ("d-1", 3),
    ("d-legacy", 2),
    ("d-2", 1),
    ("d-3", 0),
)

#: ADR-0186 §2's order over :data:`_ROWS`, written out rather than computed.
_ORDER: tuple[str, ...] = ("d-1", "d-legacy", "d-2", "d-3")

_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT = "smtp://mail.example.com:587"


def _egress_binding() -> EgressBinding:
    """One whole binding of the shape a real ``send_email`` park has."""
    return EgressBinding(
        spans=(
            EgressSpan(
                argument="to",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len("a@example.com"),
                tier=DataTier.PERSONAL,
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="a@example.com",
                    canonical="a@example.com",
                ),
            ),
        ),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
        planned_with_external_content=False,
    )


def _decision(decision_id: str, *, at: datetime) -> PermissionDecision:
    """One recorded ``ALLOW`` on an egress call, through the sanctioned factory."""
    return PermissionDecision.from_request(
        ActionRequest(
            tool=confirmable(),
            parameters={"to": "a@example.com"},
            step_id="step-1",
            egress_binding=_egress_binding(),
        ),
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="within policy"),
        id=decision_id,
        decided_at=at,
    )


def _stored(trail: SqliteAuditTrail, decision_id: str) -> dict[str, Any]:
    """The row's ``data`` column, decoded as JSON — the bytes, not a model."""
    row = trail._conn.execute("SELECT data FROM decisions WHERE id = ?", (decision_id,)).fetchone()
    assert row is not None, f"no row for {decision_id!r}"
    decoded: dict[str, Any] = json.loads(str(row[0]))
    return decoded


def _rewrite(trail: SqliteAuditTrail, decision_id: str, payload: dict[str, Any]) -> None:
    """Put ``payload`` back into the row's ``data`` column and commit."""
    trail._conn.execute(
        "UPDATE decisions SET data = ? WHERE id = ?", (json.dumps(payload), decision_id)
    )
    trail._conn.commit()


@pytest.fixture
async def bound() -> AsyncIterator[Harness]:
    """An engine over a real ``SqliteAuditTrail`` seeded with :data:`_ROWS`.

    ``d-legacy`` is written by **recording the current shape and then removing
    exactly one key from the stored bytes**, which is ``test_audit``'s own technique
    and for its reason: a hand-built row could drift from what the trail actually
    stores and would then pin a shape no build ever produced. ADR-0184 §4 makes it
    unproducible through ``record``, so the ``data`` column is the only door.
    """
    trail = SqliteAuditTrail(path=":memory:")
    harness = Harness(trail=trail)
    try:
        for decision_id, offset in _ROWS:
            await trail.record(_decision(decision_id, at=_AT + timedelta(seconds=offset)))
        legacy = _stored(trail, "d-legacy")
        del legacy["egress_binding"]["planned_with_external_content"]
        _rewrite(trail, "d-legacy", legacy)
        yield harness
    finally:
        await harness.engine.aclose()
        trail.close()


async def test_the_listing_returns_the_legacy_row_together_with_every_other(
    bound: Harness,
) -> None:
    """ADR-0184 §5 and ADR-0186 §11, through the operation a user will reach.

    "A ``recent`` or an ``export`` over a trail holding one returns it **together
    with** every other row, which is the all-or-nothing failure that closes." The
    whole sequence is asserted rather than the legacy row's presence, because the
    failure this shape exists to catch takes the *neighbours* down, not the row.
    """
    listed = await bound.engine.recent_decisions()

    assert tuple(row.id for row in listed) == _ORDER


async def test_the_export_returns_the_legacy_row_together_with_every_other(
    bound: Harness,
) -> None:
    """The same clause on the unbounded read, which is the one ADR-0021 §4 assigns
    ADR-0004 §6's portability obligation to.

    Worth its own case rather than folded into the listing's: the two reads are two
    store methods, and an implementation could relay one whole and lose the row on
    the other with nothing else noticing.
    """
    exported = await bound.engine.export_decisions()

    assert tuple(row.id for row in exported) == _ORDER


async def test_the_legacy_row_arrives_as_its_own_state_and_not_as_a_projection(
    bound: Harness,
) -> None:
    """ADR-0184 §2's second test, read at the operation rather than at the store.

    The whole reason ``OriginUnrecordedBinding`` carries the account, the
    occurrences and the payload description instead of being a marker is that the
    row's facts are the user's to read: the user gets "the connected account, every
    occurrence …, the payload description and the transport endpoint … and exactly
    one thing more, that the origin of this call was never recorded". An engine that
    relayed the row as a *marker* — or that blanked the binding — would pass every
    ordering and membership case above.
    """
    exported = await bound.engine.export_decisions()
    legacy = next(row for row in exported if row.id == "d-legacy")

    assert isinstance(legacy.egress_binding, OriginUnrecordedBinding)
    assert legacy.egress_binding.account == _ACCOUNT
    assert legacy.egress_binding.transport_endpoint == _ENDPOINT
    assert [span.argument for span in legacy.egress_binding.spans] == ["to"]
    assert not hasattr(legacy.egress_binding, "planned_with_external_content")


async def test_the_rows_around_it_keep_their_recorded_origin(bound: Harness) -> None:
    """The baseline the case above is read against (ADR-0184 §3's first row).

    Without it, an engine that turned **every** binding into the origin-unrecorded
    sibling would satisfy every assertion in this module: the legacy row would look
    right, the order would be right, and the user would be told that nothing's
    origin was ever recorded. The tolerance ADR-0184 §1 calls "one shape wide" is
    only meaningful beside a row that is not that shape.
    """
    exported = await bound.engine.export_decisions()
    ordinary = [row for row in exported if row.id != "d-legacy"]

    assert len(ordinary) == len(_ROWS) - 1
    for row in ordinary:
        assert isinstance(row.egress_binding, EgressBinding)
        assert row.egress_binding.planned_with_external_content is False


async def test_the_listing_pages_the_legacy_row_at_its_own_position(bound: Harness) -> None:
    """ADR-0186 §2's prefix property, over the row that decides whether it holds.

    A bounded page is where a reader that special-cased the unreadable row would
    show: dropping it from the page while keeping it in the export makes
    ``recent_decisions(limit=2)`` stop being the export's first two, and no
    membership assertion would say so.
    """
    exported = await bound.engine.export_decisions()

    assert await bound.engine.recent_decisions(limit=2) == exported[:2]
    assert (await bound.engine.recent_decisions(limit=2))[1].id == "d-legacy"

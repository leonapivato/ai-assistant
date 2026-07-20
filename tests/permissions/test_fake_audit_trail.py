"""The canonical audit-trail fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeAuditTrail``
as a stand-in: it is held to the same append-only, validating, detaching
contract a durable trail is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from audit_trail_contract import AuditTrailContract
from permission_builders import decision, ruling

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidResolutionError,
)
from ai_assistant.core.types import PermissionOutcome
from ai_assistant.testing import FakeAuditTrail

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AuditTrail


class TestFakeAuditTrailContract(AuditTrailContract):
    """Runs FakeAuditTrail through the shared AuditTrail conformance suite."""

    @pytest.fixture
    def trail(self) -> AuditTrail:
        return FakeAuditTrail()


async def test_a_refused_write_leaves_the_trail_untouched() -> None:
    """A rejected append must not half-happen.

    The contract says ``record`` is atomic, which the suite exercises against a
    race; this is the same property from the other side — a refusal is not a
    partial write with an exception on top.
    """
    trail = FakeAuditTrail()
    await trail.record(decision("d-1"))

    with pytest.raises(DuplicateDecisionError):
        await trail.record(decision("d-1"))

    assert len(await trail.export()) == 1


async def test_the_refusals_share_one_catchable_base() -> None:
    """A caller that only wants "the trail would not accept this" gets one handler."""
    trail = FakeAuditTrail()
    await trail.record(decision("d-1"))

    with pytest.raises(AuditError):
        await trail.record(decision("d-1"))


async def test_a_resolving_deny_citing_an_authorisation_is_refused() -> None:
    """The half of the pointer rule that `PermissionRuling` already makes unreachable.

    ADR-0021 §4 has `record` refuse a resolving `DENY` that carries
    `authorised_by` at all. No validated construction can produce one — the
    ruling's own validator permits the field only on an `ALLOW` — so the value
    is written in afterwards, past the frozen model's guard, the way corrupted
    state or a careless `model_construct` would present it.

    Deliberately here rather than in the shared conformance suite: putting it
    there would oblige *every* implementation to defend against models built
    outside the type's contract, which is a strange demand to place on a store.
    The canonical fake carries the check anyway, because the trail should not
    rest a safety rule of its own on another type's invariant holding — and a
    defensive branch nothing exercises is one nobody knows is broken.
    """
    trail = FakeAuditTrail()
    confirmed = decision("d-confirm")
    await trail.record(confirmed)
    answer = decision("d-answer", ruled=ruling(PermissionOutcome.DENY), resolves=confirmed.id)
    object.__setattr__(answer.ruling, "authorised_by", confirmed.id)

    with pytest.raises(InvalidResolutionError):
        await trail.record(answer)

    assert await trail.get("d-answer") is None


async def test_clearing_an_empty_trail_removes_nothing() -> None:
    assert await FakeAuditTrail().clear() == 0

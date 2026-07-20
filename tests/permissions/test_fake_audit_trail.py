"""The canonical audit-trail fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeAuditTrail``
as a stand-in: it is held to the same append-only, validating, detaching
contract a durable trail is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from audit_trail_contract import AuditTrailContract
from permission_builders import decision

from ai_assistant.core.errors import AuditError, DuplicateDecisionError
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


async def test_clearing_an_empty_trail_removes_nothing() -> None:
    assert await FakeAuditTrail().clear() == 0

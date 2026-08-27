"""The canonical routing fakes pass the shared conformance suites (ADR-0197 §12).

Three bindings, not two, and the third is the one that carries an argument.
``TestFakeRoutingRecorderContract`` and ``TestFakeRoutingTrailContract`` are the
ordinary ones — each fake against its own seam's suite, which is what lets other
subsystems trust ``ai_assistant.testing``'s doubles as stand-ins.

``TestFakeRoutingTrailSatisfiesTheNarrowSeam`` runs the **trail** fake through the
``RoutingRecorder`` suite, which ADR-0197 §12 requires in as many words: "The shared
suite for ``RoutingRecorder`` binds to **both** fakes, as ADR-0185 §12's pair does, so
the narrow seam is evidenced rather than asserted." That claim is what lets a
composition root pass one object to the routing stage's ``RoutingRecorder`` parameter
and to a ``RoutingTrail`` one, and without this binding it would be a sentence in an
ADR rather than something the gate checks.

The scripted capabilities each fake carries beyond its contract — a raising ``record``,
a raising read, a suspendable resource — are tested here too. They are not contract,
but they are what makes ADR-0197 §9's refuse-to-act branch and §7's reservation-release
cases reachable from a test at all, so a capability that quietly stopped working would
take a later lane's coverage with it.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from routing_contract import RoutingRecorderContract, RoutingTrailContract

from ai_assistant.core.errors import RoutingTrailError
from ai_assistant.core.protocols import RoutingRecorder, RoutingTrail
from ai_assistant.core.types import RoutableOperation, RouteApproval
from ai_assistant.testing import (
    FakeRoutingRecorder,
    FakeRoutingTrail,
    routed_operation_record,
)
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import RoutedOperationRecord


class TestFakeRoutingRecorderContract(RoutingRecorderContract):
    """Runs FakeRoutingRecorder through the shared RoutingRecorder suite."""

    @pytest.fixture
    def recorder(self) -> RoutingRecorder:
        return FakeRoutingRecorder()

    async def written(self, recorder: RoutingRecorder) -> list[RoutedOperationRecord]:
        """Read back through the fake's own test-only lever.

        The write seam has no read member — that is the property under test — so what
        the narrow fake holds is observed through a name no production caller would
        reach for, rather than through the Protocol the code under test holds.
        """
        assert isinstance(recorder, FakeRoutingRecorder)
        return list(recorder.written)


class TestFakeRoutingTrailContract(RoutingTrailContract):
    """Runs FakeRoutingTrail through the shared RoutingTrail suite."""

    # No ``operations_without_shared_resource`` opt-out: every operation on this fake —
    # the two writes and both reads — enters the one modelled resource, so ADR-0060's
    # case runs against every lock site rather than skipping some.

    @pytest.fixture
    def trail(self) -> RoutingTrail:
        return FakeRoutingTrail()

    @contextlib.asynccontextmanager
    async def bounded(self, max_rows: int) -> AsyncIterator[RoutingTrail]:
        """A trail whose cap is ``max_rows``; nothing to dispose of."""
        yield FakeRoutingTrail(max_rows=max_rows)

    @contextlib.asynccontextmanager
    async def trail_suspended_mid_write(self) -> AsyncIterator[SuspendedMidWrite[RoutingTrail]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        A list needs no serialising, so without this the canonical fake could only opt
        out — and the cancellation case would then run against the durable store alone,
        where a regression is harder to arrange. Every method passes through the *one*
        modelled resource, so ``arm`` ignores which operation it is handed.
        """
        trail = FakeRoutingTrail()
        yield SuspendedMidWrite(
            store=trail,
            log=trail.resource_log,
            arm=lambda _operation: trail.suspend_next_operation(),
        )


class TestFakeRoutingTrailSatisfiesTheNarrowSeam(RoutingRecorderContract):
    """The trail fake, run through the *narrow* seam's suite (ADR-0197 §12).

    ADR-0197 §9's "one concrete store satisfies them" as a test rather than an
    assertion. Deliberately a separate class from :class:`TestFakeRoutingTrailContract`:
    that one binds the trail to the wider suite through the ``trail`` fixture, and this
    one binds it to the narrow suite through ``recorder`` — which is the fixture the
    *routing stage* would be handed, and therefore the one whose behaviour the gate
    actually depends on.
    """

    @pytest.fixture
    def recorder(self) -> RoutingRecorder:
        return FakeRoutingTrail()

    async def written(self, recorder: RoutingRecorder) -> list[RoutedOperationRecord]:
        """Read back through ``export``, since this subject has one."""
        assert isinstance(recorder, RoutingTrail)
        return list(await recorder.export())


# --- the scripted capabilities ADR-0197 §12 requires of the fakes ------------


async def test_the_narrow_fake_offers_no_way_to_read_the_trail() -> None:
    """The capability ADR-0197 §9 removes is absent from the object, not merely unused.

    A stage handed this cannot name ``recent``, ``export`` or ``clear`` — the last of
    which is what stops a stage erasing the record of its own decisions. ``written`` is
    the test author's lever and is deliberately spelled so no production caller would
    reach for it.
    """
    # Typed ``object`` so the check is a runtime one: mypy already knows the answer
    # (the fake is ``@final``), and an annotated subject would make the assertion
    # unreachable rather than merely redundant.
    recorder: object = FakeRoutingRecorder()

    assert not isinstance(recorder, RoutingTrail)
    for absent in ("recent", "export", "clear"):
        assert not hasattr(recorder, absent)


@pytest.mark.parametrize("fake", [FakeRoutingRecorder, FakeRoutingTrail])
async def test_both_fakes_can_be_scripted_to_raise_from_record(
    fake: type[FakeRoutingRecorder] | type[FakeRoutingTrail],
) -> None:
    """ADR-0197 §9's refuse-to-act branch is otherwise unreachable from any test."""
    subject = fake()
    cause = RuntimeError("disk on fire")
    subject.fail_record(cause)

    with pytest.raises(RoutingTrailError) as raised:
        await subject.record(routed_operation_record(record_id="r-1"))

    assert raised.value.__cause__ is cause


async def test_a_scripted_write_fault_leaves_the_narrow_fake_empty() -> None:
    """The refusal appends nothing, which is what the caller's contract rests on."""
    recorder = FakeRoutingRecorder()
    recorder.fail_record()

    with pytest.raises(RoutingTrailError):
        await recorder.record(routed_operation_record(record_id="r-1"))

    assert recorder.written == ()


async def test_the_trail_fake_can_be_scripted_to_raise_from_a_read() -> None:
    """ "The store could not be read" is a state no well-formed input can provoke."""
    trail = FakeRoutingTrail()
    trail.fail_read()

    with pytest.raises(RoutingTrailError):
        await trail.recent(limit=1)
    with pytest.raises(RoutingTrailError):
        await trail.export()
    with pytest.raises(RoutingTrailError):
        await trail.clear()


async def test_the_trail_fake_can_be_seeded_with_a_history() -> None:
    """A seeded history goes through ``record``'s own invariants."""
    rows = (
        routed_operation_record(record_id="r-1", route_id="route-1"),
        routed_operation_record(record_id="r-2", route_id="route-1", approval=RouteApproval.GIVEN),
    )

    trail = FakeRoutingTrail(rows)

    assert [row.id for row in await trail.export()] == ["r-1", "r-2"]


async def test_the_trail_fake_refuses_a_seeded_history_it_could_not_have_written() -> None:
    """A script this fake could only honour by breaking its contract fails where it is written.

    Two answers to one route is the sharpest case: seeded silently it would give a
    consumer's test a trail no conforming store could ever hold, and the consumer would
    then be verified against a state that cannot occur.
    """
    with pytest.raises(RoutingTrailError):
        FakeRoutingTrail(
            (
                routed_operation_record(record_id="r-1", route_id="route-1"),
                routed_operation_record(
                    record_id="r-2", route_id="route-1", approval=RouteApproval.GIVEN
                ),
                routed_operation_record(
                    record_id="r-3", route_id="route-1", approval=RouteApproval.REFUSED
                ),
            )
        )


@pytest.mark.parametrize("fake", [FakeRoutingRecorder, FakeRoutingTrail])
@pytest.mark.parametrize(("cap", "raises"), [(0, ValueError), (-1, ValueError), (True, TypeError)])
def test_neither_fake_admits_a_cap_with_no_meaning(
    fake: type[FakeRoutingRecorder] | type[FakeRoutingTrail],
    cap: int,
    raises: type[Exception],
) -> None:
    """The narrow fake holds the cap too, so the rule binds it as well as the trail."""
    with pytest.raises(raises):
        fake(max_rows=cap)


def test_the_helper_derives_a_first_rows_approval_from_the_operations_tag() -> None:
    """``routed_operation_record`` makes the coherent case cheap and no other case.

    A read-only row is always ``NOT_OWED`` and a confirm-owed one's *first* row is
    ``OWED``; a caller wanting an incoherent pairing builds the record directly, so the
    helper cannot be the reason a test asserts against a row no conforming store holds.
    """
    read_only = routed_operation_record(RoutableOperation.SPEND_TOTALS)
    confirm_owed = routed_operation_record(RoutableOperation.REVOKE, subject="calendar")

    assert read_only.approval is RouteApproval.NOT_OWED
    assert read_only.subject is None
    assert confirm_owed.approval is RouteApproval.OWED
    assert confirm_owed.subject == "calendar"

"""Shared conformance suite for the FeedbackProcessor Protocol.

Every ``FeedbackProcessor`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`FeedbackProcessorContract` and overrides the ``processor`` fixture; the
suite asserts only behaviour that is universal to the contract — not the rules of
any one implementation.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from ai_assistant.core.protocols import FeedbackProcessor
from ai_assistant.core.types import (
    FeedbackEvent,
    FeedbackKind,
    MemoryKind,
    MemoryUpdateProposal,
    Placement,
    PlacementReach,
    PlacementSetter,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _event(memory_kind: MemoryKind, *, guarded: bool = False) -> FeedbackEvent:
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=memory_kind,
        content="some feedback content",
        created_at=_WHEN,
        guarded=guarded,
    )


class FeedbackProcessorContract:
    """The behavioural contract every ``FeedbackProcessor`` must satisfy."""

    @pytest.fixture
    def processor(self) -> FeedbackProcessor:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, processor: FeedbackProcessor) -> None:
        assert isinstance(processor, FeedbackProcessor)

    @pytest.mark.parametrize("memory_kind", list(MemoryKind))
    async def test_process_returns_a_sequence_of_valid_proposals(
        self, processor: FeedbackProcessor, memory_kind: MemoryKind
    ) -> None:
        proposals = await processor.process(_event(memory_kind))

        assert isinstance(proposals, Sequence)  # a materialised sequence, not a generator
        assert all(isinstance(p, MemoryUpdateProposal) for p in proposals)
        for proposal in proposals:
            # Whatever a processor emits must be a usable, non-blank memory record.
            assert proposal.proposed.content.strip()
            assert proposal.rationale.strip()

    @pytest.mark.parametrize("memory_kind", list(MemoryKind))
    async def test_a_guarded_event_places_every_record_it_produces_for_the_owner(
        self, processor: FeedbackProcessor, memory_kind: MemoryKind
    ) -> None:
        """ADR-0217 §7's write-time act, at the seam every implementation shares.

        The arm is taken here rather than through any one processor because
        honouring ``guarded`` is a change to the ``FeedbackProcessor`` Protocol's
        *behavioural* contract and not to one implementation's rules: the signature
        does not move, so an implementation that built its normal proposal and
        ignored the member would be structurally conformant and would silently
        discard an explicit owner act.

        It says nothing about *which* records an implementation produces — a
        processor that defers a kind produces none, and "every record that event
        produces" is then vacuously satisfied. What it forbids is producing one and
        leaving it speakable on a channel of unbounded audience.

        The **setter** is asserted and not only the reach, because ADR-0217 §3
        makes the stamp what decides whether the owner may lift the narrowing
        again: a record placed ``OWNER`` with setter ``DERIVED`` is one no
        ``unguard`` can widen, so an implementation writing that stamp for an act
        the owner made would take away the correction while passing a reach-only
        assertion. The instant is left to the implementation — ADR-0217 §7 fixes
        the reach and the setter, and the type's own validator already refuses an
        ``OWNER_ACT`` placement carrying none.
        """
        proposals = await processor.process(_event(memory_kind, guarded=True))

        for proposal in proposals:
            placement = proposal.proposed.placement
            assert placement.reach is PlacementReach.OWNER
            assert placement.set_by is PlacementSetter.OWNER_ACT

    @pytest.mark.parametrize("memory_kind", list(MemoryKind))
    async def test_an_unguarded_event_leaves_the_default_placement(
        self, processor: FeedbackProcessor, memory_kind: MemoryKind
    ) -> None:
        """``guarded=False`` is not an act of any kind (ADR-0217 §7).

        The negative half of the arm above, and the half that keeps it from being
        satisfied by a processor that guards everything. ADR-0217 §6's default *is*
        ADR-0199 §3's placement of the record's class, so a record this branch
        produces is exactly as speakable as it was before the member existed.
        """
        proposals = await processor.process(_event(memory_kind))

        for proposal in proposals:
            assert proposal.proposed.placement == Placement()

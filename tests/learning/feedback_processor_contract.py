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

#: An utterance far enough back that no implementation's *write* could plausibly
#: land there. Only the transaction-time arm uses it, and only so that arm's
#: inequality is a statement about where the stamp came from.
_LONG_AGO = datetime(1970, 1, 1, tzinfo=UTC)


def _event(
    memory_kind: MemoryKind, *, guarded: bool = False, created_at: datetime = _WHEN
) -> FeedbackEvent:
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=memory_kind,
        content="some feedback content",
        created_at=created_at,
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
    async def test_no_record_takes_its_transaction_time_from_the_event(
        self, processor: FeedbackProcessor, memory_kind: MemoryKind
    ) -> None:
        """``last_updated`` is *our* write's instant, never the utterance's (ADR-0045 §3).

        "When we last revised the belief" is a fact about the store changing its
        mind, so a processor stamping it from ``created_at`` makes every record
        claim a revision at an instant nothing was revised at — wrongly by exactly
        the delay of a queued, retried or replayed event. That is #775, and it was
        fixed in one implementation while the canonical fake every consumer drives
        kept it (#780). Held **here** for that reason: the arm each implementation
        keeps to itself is the arm the next implementation does not inherit, and a
        consumer certified against the fake was certified against a conflation the
        production processor had already stopped producing.

        **What a shared suite can state is the source, not the value.** The instant
        a conforming implementation stamps is its own clock's, and this suite
        neither owns that clock nor knows whether the subject was handed a frozen
        one — so bracketing the call in real time would fail every implementation a
        fixture wires a fixed clock into. What is universal is the source it must
        not be.

        The event's instant is put **far from any plausible write** rather than at
        the suite's usual ``_WHEN``, so the arm is about that source and not about a
        constant two fixtures might happen to share: a processor taking transaction
        time from the event stamps a record as revised in 1970, whatever clock it
        was given. That is also what lets the arm bind a *scripted* implementation
        as the guarded arm below binds one, without the assertion becoming a demand
        that no script reuse a particular date.
        """
        event = _event(memory_kind, created_at=_LONG_AGO)

        proposals = await processor.process(event)

        for proposal in proposals:
            assert proposal.proposed.provenance.last_updated != event.created_at

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

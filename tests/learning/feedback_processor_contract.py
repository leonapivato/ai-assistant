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

#: What a subject wired for the transaction-time arm reads from its clock. Distinct
#: from :data:`_WHEN` on purpose: with the two equal, a processor that conflated
#: them would satisfy the arm.
_STAMPED_AT = datetime(2026, 5, 6, 7, 8, tzinfo=UTC)


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

    @pytest.fixture
    def stamping(self) -> FeedbackProcessor | None:
        """Override with a subject whose clock reads :data:`_STAMPED_AT`.

        A second fixture rather than a constraint on ``processor``, because the two
        arms want opposite things: every other case wants the subject a consumer
        actually constructs, and the arm below has to know what the subject's clock
        was told to say. ``None`` — the default — is "this implementation mints no
        record of its own", which is the honest answer for a double answering from
        a fixed script: it stamps nothing, so there is no source to state.
        """
        return None

    @pytest.mark.parametrize("memory_kind", list(MemoryKind))
    async def test_a_minted_record_is_stamped_from_the_processors_own_clock(
        self, stamping: FeedbackProcessor | None, memory_kind: MemoryKind
    ) -> None:
        """``last_updated`` is *our* write's instant, never the utterance's (ADR-0045 §3).

        "When we last revised the belief" is a fact about the store changing its
        mind, so a processor stamping it from ``created_at`` makes every record
        claim a revision at an instant nothing was revised at — wrongly by exactly
        the delay of a queued, retried or replayed event. That is #775, and it was
        fixed in one implementation while the canonical fake every consumer drives
        kept it (#780). Held **here** for that reason: the arm one implementation
        keeps to itself is the arm the next implementation does not inherit, and a
        consumer certified against the fake was certified against a conflation the
        production processor had already stopped producing.

        The **source** is what is asserted, and asserting it needs a clock whose
        reading the suite knows — hence the fixture. An inequality against the
        event's instant would not do it: an implementation stamping any fixed
        constant satisfies that while reading no clock at all, which is a different
        defect of the same field. Equality against :data:`_STAMPED_AT` admits only a
        subject that read what it was given.

        ``last_confirmed_at`` is asserted beside it and *is* the event's
        (ADR-0109 §4), because the two are one decision: an implementation that
        moved both onto the clock would satisfy this arm's first line while losing
        the confirming instant, and ADR-0103 §9 is explicit that two quantities a
        live path puts microseconds apart are the ones that break silently.
        """
        if stamping is None:
            pytest.skip("this implementation mints no record of its own to stamp")
        event = _event(memory_kind)

        proposals = await stamping.process(event)

        assert event.created_at != _STAMPED_AT  # or the arm below proves nothing
        for proposal in proposals:
            provenance = proposal.proposed.provenance
            assert provenance.last_updated == _STAMPED_AT
            assert provenance.last_confirmed_at == event.created_at

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

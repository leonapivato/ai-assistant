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
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _event(memory_kind: MemoryKind) -> FeedbackEvent:
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=memory_kind,
        content="some feedback content",
        created_at=_WHEN,
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

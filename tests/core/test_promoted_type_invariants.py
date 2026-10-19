"""The cross-field invariants that promote with the fields (ADR-0085 §4b).

**A field list is not the whole of a DTO's contract, and dropping an invariant
while promoting one is the quiet way to lose it.** Several of the promoted types
carry a cross-field rule — most state one in the text they carried in
`orchestration`, and ``BeliefSummary`` acquires one with its counts (§4a) — and
each becomes a model validator here, which is precisely the "what it adds is
validation" ADR-0084 §4 names as the reason for moving to pydantic at all.

Each case below asserts **both** directions where the rule has two, because an
invariant tested only in the direction that fires is half a rule: a model that
required a confirmation on a parked step but happily carried one on a denied step
would pass a one-sided test while offering a prompt for an action nobody is
waiting on.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    BeliefSummary,
    EvidenceSummary,
    SupportDirection,
    belief_summary,
)
from ai_assistant.testing.memories import memory, said_support

AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


class TestBeliefSummary:
    """The listing's shape (ADR-0085 §4a, ADR-0328 §15:1).

    ADR-0328 §15 retired the citation counts ADR-0085 §4b's invariant was over: the
    listing now carries the evidence summary §7:2 computes, so the cross-field rule
    between two stored counts has nothing left to bind (``lost_evidence`` and
    ``unsupported`` are gone; a memory none of whose counted supports backs it is
    ``unbacked``, computed in ``core``).
    """

    def test_an_evidence_count_is_never_negative(self) -> None:
        """The counts are strict non-negative integers, so no projection ships ``-1``."""
        with pytest.raises(ValidationError):
            EvidenceSummary(supporting=-1, against=0, episodes=0)

    def test_unbacked_is_computed_from_the_supports(self) -> None:
        """One definition everywhere (ADR-0328 §7:10): no counted ``for`` support backs it."""
        backed = memory("rec-1", "the office is in Boston")
        against = memory(
            "rec-2",
            "the office is in Boston",
            said_support(),
            said_support("activation:other", direction=SupportDirection.AGAINST),
        )
        assert not belief_summary(backed, now=AT, supports_gone=False).unbacked
        assert not belief_summary(against, now=AT, supports_gone=False).unbacked
        assert belief_summary(against, now=AT, supports_gone=False).evidence.against == 1

    def test_it_has_no_supports_field_at_all(self) -> None:
        """§4a's structural guarantee: the wrong behaviour is unrepresentable.

        Every alternative shape leaves a ``beliefs()`` implementation *able* to ship a
        support's content, so the ratified split survives only as a clause a conformance
        suite has to police.
        """
        assert "supports" not in BeliefSummary.model_fields
        assert "evidence" in BeliefSummary.model_fields

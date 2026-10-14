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
    BeliefBand,
    BeliefSummary,
    MemoryKind,
)

AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


class TestBeliefSummary:
    """The price of counts-as-fields (§4a, §4b)."""

    def test_more_citations_cannot_be_gone_than_were_made(self) -> None:
        """On ``Belief`` the counts cannot disagree with the evidence; here they can.

        Moving them to fields is what buys the listing its shape — no field a
        citation's content could occupy — at the cost of the one constraint the
        model must now assert for itself.
        """
        with pytest.raises(ValidationError, match="lost_evidence"):
            _summary(evidence_count=1, lost_evidence=2)

    @pytest.mark.parametrize(
        ("cited", "lost", "unsupported"),
        [(0, 0, False), (2, 0, False), (2, 1, False), (2, 2, True)],
    )
    def test_unsupported_is_derived_from_the_two_counts(
        self, cited: int, lost: int, unsupported: bool
    ) -> None:
        """One definition everywhere, and a belief citing nothing is *not* unsupported.

        An assertion is supported by the user's own word (ADR-0038 §1a). It stays a
        property rather than a field because the counts already determine it: a
        field would be a second source of truth for a value a client can compute
        exactly, so one implementation could send it and another omit it, and the
        same call would measure two different sizes against the contract limit.
        """
        assert _summary(evidence_count=cited, lost_evidence=lost).unsupported is unsupported

    def test_it_has_no_evidence_field_at_all(self) -> None:
        """§4a's structural guarantee: the wrong behaviour is unrepresentable.

        Every alternative shape leaves a ``beliefs()`` implementation *able* to ship
        citation contents, so the ratified split survives only as a clause a
        conformance suite has to police.
        """
        assert "evidence" not in BeliefSummary.model_fields


def _summary(*, evidence_count: int = 0, lost_evidence: int = 0) -> BeliefSummary:
    """One listing row with the given counts."""
    return BeliefSummary(
        id="rec-1",
        band=BeliefBand.DERIVED,
        kind=MemoryKind.SEMANTIC,
        content="the office is in Boston",
        confidence=0.5,
        last_updated=AT,
        evidence_count=evidence_count,
        lost_evidence=lost_evidence,
    )

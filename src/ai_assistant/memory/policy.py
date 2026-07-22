"""A first, deterministic :class:`~ai_assistant.core.protocols.MemoryPolicy`.

This is the "dispose" half of the propose/dispose write path: the model emits a
:class:`~ai_assistant.core.types.MemoryUpdateProposal`, and this policy rules on
it with simple, explainable rules. It holds no state and performs no I/O — the
conflicting records it reasons about are passed in, so it stays decoupled from
the store and trivially testable.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemorySource,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord, MemoryUpdateProposal

_DEFAULT_MIN_CONFIDENCE = 0.3
_DEFAULT_TEMPORARY_TTL = timedelta(days=7)

# Sources a user assertion may supersede (ADR-0038 §2). An allow-list rather
# than "not USER_ASSERTED": adding a `MemorySource` should not silently enrol it
# in a destructive rule, and `EXTERNAL` is excluded on its own grounds (§2a).
_SUPERSEDABLE = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED})


def _rule_on_assertion(conflicts: Sequence[MemoryRecord]) -> MemoryDecision:
    """Rule on a user-asserted proposal: supersede a stale inference, or accept.

    Supersession targets the best-ranked conflict whose source is in
    :data:`_SUPERSEDABLE` — an allow-list of the two *derived* sources, not
    "anything that is not an assertion". Two exclusions, for different reasons:

    - ``USER_ASSERTED``, because an assertion may displace a belief we derived
      but may never displace one we were told (ADR-0038 §3). Scanning past it
      rather than taking ``conflicts[0]`` matters because the sequence is
      ordered by retrieval score, so the top entry may itself be asserted and
      merging over it would destroy the user's own words on the strength of a
      lexical or embedding near-match.
    - ``EXTERNAL``, because supersession keeps the *target's* id, and an
      external record's id is that system's idempotency key. A correction
      merged into it would inherit that key and be silently overwritten by the
      next routine sync — the user's correction lost, not the stale value
      (ADR-0038 §2a).

    With nothing supersedable the assertion is accepted and lands beside the
    conflict, which is the pre-ADR-0038 behaviour (ADR-0038 §5).
    """
    superseded = next(
        (c for c in conflicts if c.provenance.source in _SUPERSEDABLE),
        None,
    )
    if superseded is None:
        return MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="user-asserted")
    return MemoryDecision(
        kind=MemoryDecisionKind.MERGE,
        merge_into=superseded.id,
        reason="user assertion supersedes a conflicting inference",
    )


class DefaultMemoryPolicy:
    """A conservative default policy for memory writes.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryPolicy`. The rules, in order:

    1. Secret-tier proposals always defer to the user.
    2. An inference never silently overrides a user-asserted memory — defer.
    3. A user-asserted proposal *supersedes* a conflicting inference: it merges
       over the best-ranked ``OBSERVED``/``INFERRED`` conflict rather than
       landing beside it, so a correction takes the stale belief off the read
       path (ADR-0038).
    4. A user-asserted proposal with nothing to supersede is trusted and
       accepted.
    5. A proposal that conflicts with an existing (non-asserted) record merges
       into it.
    6. Weak evidence (below ``min_confidence``) is stored temporarily, with an
       expiry, rather than committed.
    7. Otherwise the proposal is accepted.

    Rules 2 and 3 are the same asymmetry read in both directions: an assertion
    outranks an inference, and never the reverse.
    """

    def __init__(
        self,
        *,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        temporary_ttl: timedelta = _DEFAULT_TEMPORARY_TTL,
    ) -> None:
        """Initialise the policy.

        Args:
            min_confidence: Confidence below which a non-conflicting proposal is
                stored temporarily instead of committed.
            temporary_ttl: Retention window attached to temporary stores; must be
                positive, since a non-positive window would produce an
                already-expired record.

        Raises:
            ValueError: If ``temporary_ttl`` is not positive. ``MemoryDecision``
                rejects such a window anyway, so without this guard the policy
                constructs fine and then raises from ``decide`` — and only for
                low-confidence proposals, far from the mistake.
        """
        if temporary_ttl <= timedelta(0):
            msg = f"temporary_ttl must be positive, got {temporary_ttl}"
            raise ValueError(msg)
        self._min_confidence = min_confidence
        self._temporary_ttl = temporary_ttl

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Rule on a proposed memory update. See the class docstring for rules."""
        record = proposal.proposed
        source = record.provenance.source
        is_asserted = source is MemorySource.USER_ASSERTED

        if proposal.sensitivity is DataTier.SECRET:
            return MemoryDecision(
                kind=MemoryDecisionKind.ASK_USER,
                reason="secret-tier data requires explicit user confirmation",
            )

        asserted_conflict = any(
            c.provenance.source is MemorySource.USER_ASSERTED for c in conflicts
        )
        if not is_asserted and asserted_conflict:
            return MemoryDecision(
                kind=MemoryDecisionKind.ASK_USER,
                reason="conflicts with a user-asserted memory",
            )

        if is_asserted:
            return _rule_on_assertion(conflicts)

        if conflicts:
            return MemoryDecision(
                kind=MemoryDecisionKind.MERGE,
                merge_into=conflicts[0].id,
                reason="updates an existing memory",
            )

        if record.provenance.confidence < self._min_confidence:
            return MemoryDecision(
                kind=MemoryDecisionKind.STORE_TEMPORARY,
                ttl=self._temporary_ttl,
                reason="low-confidence evidence, stored tentatively",
            )

        return MemoryDecision(
            kind=MemoryDecisionKind.ACCEPT,
            reason="sufficient confidence and no conflict",
        )

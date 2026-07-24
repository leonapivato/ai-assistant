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
    """Rule on a user-asserted proposal: defer, supersede stale inferences, or accept.

    Three arms, in order:

    1. **A contradictory prior assertion → ``ASK_USER`` (ADR-0050 §2, #245).** If
       *any* conflict is itself ``USER_ASSERTED``, the user is contradicting
       something they earlier told us. Committing the new assertion — even by
       superseding an inference alongside it — would leave two live, contradictory
       profile records, the honesty gap issue #245 reports. We may not silently
       destroy either (topical similarity is not a contradiction signal, ADR-0045 §5
       / clause 1), and we may not silently keep both, so we defer to the one
       authority that can resolve it: the user. This is the "explicit user
       confirmation" gate ADR-0045 §7 named as the acceptable way to resolve
       assertion-versus-assertion, and it supersedes ADR-0038 §5's "accept beside"
       — the validity window now makes the *outcome* of that confirmation
       non-destructive (the earlier assertion is retained in ``export``), which flips
       the cost/benefit ADR-0038 §5 weighed. The check comes first because it must
       win even when an inference is also in the set: superseding the inference would
       still commit the contradicting assertion.

    2. **A supersedable inference → ``SUPERSEDE`` (ADR-0038, #244).** With no asserted
       conflict, supersession targets the best-ranked conflict whose source is in
       :data:`_SUPERSEDABLE` — an allow-list of the two *derived* sources, not
       "anything that is not an assertion". ``EXTERNAL`` is excluded because adopting
       its supersession is a separate deferred choice (ADR-0045 §5/§7); scanning past
       it (rather than taking ``conflicts[0]``) reaches the first inference instead of
       abandoning supersession. The named target is the **primary**; the applier
       retires the *full* supersedable set it leads (:func:`_retirement_set`, #244),
       so a second and third stale inference on the same topic do not survive.

    3. **Nothing supersedable → ``ACCEPT``.** With only ``EXTERNAL`` conflicts (or
       none), the assertion lands beside them (ADR-0045 §7's #254 shape).
    """
    if any(c.provenance.source is MemorySource.USER_ASSERTED for c in conflicts):
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason="contradicts a prior user assertion; defer to the user (ADR-0050)",
        )
    superseded = next(
        (c for c in conflicts if c.provenance.source in _SUPERSEDABLE),
        None,
    )
    if superseded is None:
        return MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="user-asserted")
    return MemoryDecision(
        kind=MemoryDecisionKind.SUPERSEDE,
        target_id=superseded.id,
        reason="user assertion supersedes the conflicting inferences",
    )


class DefaultMemoryPolicy:
    """A conservative default policy for memory writes.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryPolicy`. The rules, in order:

    1. Secret-tier proposals always defer to the user.
    2. An inference never silently overrides a user-asserted memory — defer.
    3. A user-asserted proposal that contradicts a *prior assertion* defers to
       the user (``ASK_USER``): two things the user said cannot both stay live,
       yet neither may be destroyed on a topical-similarity signal, so the user
       resolves it (ADR-0050 §2, #245).
    4. A user-asserted proposal *supersedes* the conflicting inferences: it rules
       ``SUPERSEDE`` naming the best-ranked ``OBSERVED``/``INFERRED`` conflict,
       and the applier retires the *whole* supersedable conflict set it leads, so
       no stale belief on the topic stays on the read path (ADR-0038, ADR-0040,
       ADR-0050 §1, #244).
    5. A user-asserted proposal with nothing to supersede is trusted and
       accepted.
    6. A proposal that conflicts with an existing (non-asserted) record rules
       ``REINFORCE`` over it, folding into it (ADR-0040 §4).
    7. Weak evidence (below ``min_confidence``) is stored temporarily, with an
       expiry, rather than committed.
    8. Otherwise the proposal is accepted.

    Rules 2 and 4 are the same asymmetry read in both directions: an assertion
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
                kind=MemoryDecisionKind.REINFORCE,
                target_id=conflicts[0].id,
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

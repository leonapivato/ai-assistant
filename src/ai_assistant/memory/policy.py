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
    BeliefBand,
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    band_of,
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


def _rule_on_admissibility(proposal: MemoryUpdateProposal) -> MemoryDecision | None:
    """The two rulings that precede any conflict reasoning, or ``None``.

    Both are properties of the proposal alone, so neither needs to look at what it
    contradicts — and neither commits anything, so ADR-0004 §3 holds whichever
    fires:

    1. **Secret-tier data defers** (ADR-0004 §3). Tier 0 belongs in the OS keyring,
       never the memory store, so it is never committed by any other rule below.
    2. **A derived belief citing no evidence is rejected** (ADR-0077 §5). It sits
       *after* the secret gate deliberately: both write nothing, and rule 1's
       ``ASK_USER`` is the more informative outcome for a Tier-0 proposal, so the
       new rule narrows the non-secret path rather than pre-empting a ratified one.
       Placed before the conflict rules because it is an *admissibility* floor: a
       belief with no warrant is not worth deferring to the user about, whatever it
       happens to contradict.
    """
    if proposal.sensitivity is DataTier.SECRET:
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason="secret-tier data requires explicit user confirmation",
        )
    if _cites_nothing_it_must_cite(proposal.proposed):
        return MemoryDecision(
            kind=MemoryDecisionKind.REJECT,
            reason="a derived belief citing no evidence has no warrant (ADR-0077 §5)",
        )
    return None


def _cites_nothing_it_must_cite(record: MemoryRecord) -> bool:
    """Whether ``record`` is a derived belief with no evidence at all (ADR-0077 §5).

    The gate's half of the evidence discipline, at the enforcement point ADR-0072 §3
    named: "the enforcement point is the ``MemoryPolicy`` gate, not the type… a
    policy can state the rule for the band it is judging without constraining
    ``EXTERNAL`` or ``USER_ASSERTED`` records that legitimately cite nothing." A
    derived belief is one the system worked out from evidence; one that cites none
    cannot answer "why do you believe that?" at all.

    Band-wide and minimal, because the gate serves every producer and cannot know
    which epistemic step a record took. The *producer's* floor — an ``INFERRED``
    belief needs two distinct episodes — is a different rule with a different owner
    and does not live here.

    **``EPISODIC`` records are exempt**, as ADR-0074 §4 binds this policy: an
    episode's warrant is that it happened, and requiring it to cite something would
    demand a regress. The exemption guards a path nothing takes today — capture does
    not reach the gate (ADR-0075 §1) and ADR-0077 §2 forbids the observer to propose
    an episode — and is written anyway, so the rule is not one refactor away from
    making its own substrate unwritable.

    Its counterpart is the *writer's* floor, resolvability (ADR-0077 §5). The two do
    not overlap: an empty tuple names no record that fails to resolve, so it passes
    the writer and is caught here; a populated tuple naming a record the store does
    not hold passes any policy and is caught there.
    """
    return (
        MemoryKind(record.kind) is not MemoryKind.EPISODIC
        and band_of(record.provenance.source) is BeliefBand.DERIVED
        and not record.provenance.evidence
    )


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
    2. A proposal in the ``DERIVED`` band citing **no** evidence is rejected: a
       belief we worked out from evidence, with no evidence, has no warrant
       (ADR-0077 §5). ``EPISODIC`` records are exempt (ADR-0074 §4), and
       ``ASSERTED``/``ATTESTED`` proposals are untouched — they legitimately cite
       nothing (:func:`_cites_nothing_it_must_cite`).
    3. An inference never silently overrides a user-asserted memory — defer.
    4. A user-asserted proposal that contradicts a *prior assertion* defers to
       the user (``ASK_USER``): two things the user said cannot both stay live,
       yet neither may be destroyed on a topical-similarity signal, so the user
       resolves it (ADR-0050 §2, #245).
    5. A user-asserted proposal *supersedes* the conflicting inferences: it rules
       ``SUPERSEDE`` naming the best-ranked ``OBSERVED``/``INFERRED`` conflict,
       and the applier retires the *whole* supersedable conflict set it leads —
       which is now the whole set retrieval surfaced, since the writer refuses
       rather than truncating above its ceiling (ADR-0079 §1) — so a second and
       third stale inference on the topic do not survive the correction (ADR-0038,
       ADR-0040, ADR-0050 §1, #244).
    6. A user-asserted proposal with nothing to supersede is trusted and
       accepted.
    7. A proposal that conflicts with an existing (non-asserted) record rules
       ``REINFORCE`` over it, folding into it (ADR-0040 §4).
    8. Weak evidence (below ``min_confidence``) is stored temporarily, with an
       expiry, rather than committed.
    9. Otherwise the proposal is accepted.

    Rules 3 and 5 are the same asymmetry read in both directions: an assertion
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

        # Rules 1 and 2: properties of the proposal alone, ruled on before any
        # conflict is read (:func:`_rule_on_admissibility`).
        inadmissible = _rule_on_admissibility(proposal)
        if inadmissible is not None:
            return inadmissible

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

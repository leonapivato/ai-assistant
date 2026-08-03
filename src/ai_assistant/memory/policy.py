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

    from ai_assistant.core.types import MemoryRecord, MemoryUpdateProposal, UserConfirmation

_DEFAULT_MIN_CONFIDENCE = 0.3
_DEFAULT_TEMPORARY_TTL = timedelta(days=7)

# The **retirement class**: sources a user assertion may retire (ADR-0038 §2,
# widened by ADR-0092 §4). An allow-list rather than "not USER_ASSERTED", and that
# property is the point ADR-0038 §2a's surviving argument makes: "a `MemorySource`
# added later is not silently enrolled in a destructive rule by omission." ADR-0092
# §4 changes one member, chosen; not the shape that makes the next member a
# decision.
#
# `EXTERNAL` joins because the owner ruled that the external calendar is an *input*
# and not the truth. ADR-0072 already granted the permission in the sentence
# defining the band — an attested belief is "neither entitled to the standing the
# supersession law protects nor re-derivable by observing harder" — and ADR-0092 §4
# completes the second clause: an attested belief is not re-derivable *by us* and is
# **re-reportable by its source**, on a schedule, which is a recovery path at least
# as reliable as re-observation. So it sits on the recoverable side of ADR-0038 §2's
# error calculus, and the case for retiring it is the case §2 already made for
# inferences.
#
# **This is not the applier's reinforce-safe class**, which stays `{OBSERVED,
# INFERRED}` (`memory/ingest.py`). ADR-0092 §5 splits the two because they answer
# different questions; the constant here only ever answered this one.
_RETIREMENT_CLASS = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED, MemorySource.EXTERNAL})


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


def _rule_on_confirmation(
    confirmation: UserConfirmation, conflicts: Sequence[MemoryRecord]
) -> MemoryDecision | None:
    """Rule on a *confirmed* proposal, or ``None`` to fall through (ADR-0078 §5a).

    The gate ADR-0045 §7 named and neither ADR-0045 nor ADR-0050 could build,
    because until ADR-0078 there was nowhere for the question to wait. It runs
    **ahead of every conflict rule and behind the admissibility floor**
    (:func:`_rule_on_admissibility`), and the two halves of that placement are each
    load-bearing:

    * **Ahead of the conflict rules**, because the assertion arms would otherwise
      re-defer the answer to the question they just asked, forever.
    * **Behind the floor**, because both of the floor's rulings are properties of
      the proposal alone and neither commits anything, so nothing a confirmation
      says can make either safe to skip. Putting the confirmed rule first let a
      ``DataTier.SECRET`` proposal carrying a confirmation reach step 2, rule
      ``SUPERSEDE``, and land secret payload in the store — ADR-0004 §3's "never in
      the memory database", defeated through the one path built to respect the
      user's word. The combination is unconstructable anyway
      (``MemoryUpdateProposal``'s own validator refuses it), so this is belt and
      braces over something already impossible, which is the right amount of care
      for a rule whose failure mode is a credential in a database.

    Three steps, in order:

    1. **An asserted conflict outside the answer's authority → ``ASK_USER``.** If
       the live conflict set holds a ``USER_ASSERTED`` record *not* named in
       ``confirmation.retires``, the user was never shown it, so committing beside
       it is the #245 gap reached by a new path and extending their answer to it
       would forge consent. The answer becomes a **re-deferral** (ADR-0078 §9), not
       a write, and a fresh question is minted over the new set — which ADR-0078
       §7's dedup does not suppress, because a different conflict set is a
       different ``question_key``. Nothing is retired on the way out: ADR-0079 §2's
       ordering is that only a ``SUPERSEDE`` retires anything, so sweeping the
       covered inferences while asking about the newly-surfaced assertion would
       commit part of a correction the user has not confirmed.
    2. **Otherwise ``SUPERSEDE`` the first *asserted* target in ``retires`` that is
       live.** The qualifier is load-bearing in two directions. The confirmation
       exists to authorise the one thing similarity may not do — retire a record
       the user gave us — so an asserted conflict is what it is *for*; and without
       it a set holding an ``EXTERNAL`` record and an assertion, both named, could
       name the ``EXTERNAL`` one as the audited primary while the assertion the
       user actually confirmed retiring rode in on the applier's widening, which
       puts the *incidental* record in the ruling's ``target_id`` and the confirmed
       one nowhere the audit trail names. Since ADR-0092 §4 that is a
       mis-attribution rather than an unratified adoption — ``EXTERNAL``
       supersession is now the shipped rule — but the qualifier stays, because the
       thing a confirmation authorises is retiring an *assertion* and that is what
       the ruling should say it did. An ``EXTERNAL`` id in ``retires`` is therefore
       still not acted on here: ``retires`` is a ceiling, not an instruction, and
       an ``EXTERNAL`` conflict needs no authority from the user to be retired
       anyway.
    3. **Otherwise fall through** (``None``) to the policy's ordinary rules,
       unchanged. Reading this as "otherwise ``ACCEPT``" quietly disables the
       ordinary supersession law for every confirmed proposal: freeze a question
       over an assertion and an inference, let the assertion be retired before the
       answer arrives, and a bare ``ACCEPT`` lands the correction *beside* the
       stale inference the user just corrected — left live by the confirmed path
       where the unconfirmed one would have retired it. The confirmed path exists
       to override the arms that would *re-defer an answered question*, not the
       arms ADR-0038 entitles an assertion to overturn without asking.

    Every confirmed *asserted* conflict is retired, not only the named one: the
    named target is the primary the ruling audits, and the rest ride the applier's
    widening under ADR-0078 §5b's narrowing of ADR-0050 §1's hold-out.

    Args:
        confirmation: The authority the user's answer carries.
        conflicts: The conflicts *this* ingest resolved — the live set.

    Returns:
        The ruling, or ``None`` to fall through to the ordinary rules.
    """
    unshown = next(
        (
            conflict
            for conflict in conflicts
            if conflict.provenance.source is MemorySource.USER_ASSERTED
            and conflict.id not in confirmation.retires
        ),
        None,
    )
    if unshown is not None:
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason=(
                "this correction now contradicts a prior user assertion you were not shown; "
                "defer to the user again (ADR-0078 §5a)"
            ),
        )
    live_asserted = {
        conflict.id
        for conflict in conflicts
        if conflict.provenance.source is MemorySource.USER_ASSERTED
    }
    target = next(
        (record_id for record_id in confirmation.retires if record_id in live_asserted), None
    )
    if target is None:
        return None
    return MemoryDecision(
        kind=MemoryDecisionKind.SUPERSEDE,
        target_id=target,
        reason="the user confirmed retiring their earlier assertion (ADR-0050 §2, ADR-0078 §5)",
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

    2. **A retirable conflict → ``SUPERSEDE`` (ADR-0038, ADR-0092 §4, #244).** With
       no asserted conflict, supersession targets the best-ranked conflict whose
       source is in :data:`_RETIREMENT_CLASS` — an allow-list of the two *derived*
       sources and ``EXTERNAL``, not "anything that is not an assertion", so a
       ``MemorySource`` added later is not enrolled by omission. The scan (rather
       than taking ``conflicts[0]``) is what reaches a retirable conflict past a
       ``USER_ASSERTED`` one instead of abandoning supersession — it no longer has
       an ``EXTERNAL`` hold-out to step over, since ADR-0092 §4 adopted that
       supersession: the user outranks the calendar, and the import is an input
       rather than the truth. The named target is the **primary**; the applier
       retires the *full* retirement set it leads (:func:`_retirement_set`, #244),
       so a second and third stale belief on the same topic do not survive.

    3. **Nothing retirable → ``ACCEPT``.** Reachable only when the conflict set is
       **empty**: with ``EXTERNAL`` in the class, every non-asserted conflict is
       now retirable, and an asserted one was already ruled on by arm 1. The
       ADR-0045 §7 shape where an assertion landed live beside a contradicting
       import is what ADR-0092 §4 exists to end.
    """
    if any(c.provenance.source is MemorySource.USER_ASSERTED for c in conflicts):
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason="contradicts a prior user assertion; defer to the user (ADR-0050)",
        )
    superseded = next(
        (c for c in conflicts if c.provenance.source in _RETIREMENT_CLASS),
        None,
    )
    if superseded is None:
        return MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="user-asserted")
    return MemoryDecision(
        kind=MemoryDecisionKind.SUPERSEDE,
        target_id=superseded.id,
        reason="user assertion supersedes the conflicting beliefs",
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
    3. A proposal carrying a :class:`~ai_assistant.core.types.UserConfirmation` —
       the user's answer to a question this policy earlier deferred — is judged by
       :func:`_rule_on_confirmation`: it re-defers when the live set holds an
       assertion the user was never shown, supersedes the confirmed assertion when
       one is live, and otherwise **falls through** to the rules below. Behind
       rules 1 and 2 and ahead of every rule after it; the placement is argued in
       that function.
    4. An inference never silently overrides a user-asserted memory — defer.
    5. A user-asserted proposal that contradicts a *prior assertion* defers to
       the user (``ASK_USER``): two things the user said cannot both stay live,
       yet neither may be destroyed on a topical-similarity signal, so the user
       resolves it (ADR-0050 §2, #245).
    6. A user-asserted proposal *supersedes* the conflicting beliefs: it rules
       ``SUPERSEDE`` naming the best-ranked ``OBSERVED``/``INFERRED``/``EXTERNAL``
       conflict, and the applier retires the *whole* retirement set it leads —
       which is now the whole set retrieval surfaced, since the writer refuses
       rather than truncating above its ceiling (ADR-0079 §1) — so a second and
       third stale belief on the topic do not survive the correction (ADR-0038,
       ADR-0040, ADR-0050 §1, ADR-0092 §4, #244). ``EXTERNAL`` is in that class
       since ADR-0092 §4: a connected source is an *input*, so the user's
       correction retires the import rather than sitting live beside it.
    7. A user-asserted proposal with nothing to supersede is trusted and
       accepted — which, since rule 6 took ``EXTERNAL``, means nothing conflicted
       with it at all.
    8. A proposal that conflicts with an existing (non-asserted) record rules
       ``REINFORCE`` over it, folding into it (ADR-0040 §4).
    9. Weak evidence (below ``min_confidence``) is stored temporarily, with an
       expiry, rather than committed.
    10. Otherwise the proposal is accepted.

    Rules 4 and 6 are the same asymmetry read in both directions: an assertion
    outranks an inference, and never the reverse. Rule 3 is the one ratified way
    through it — the user's own answer (ADR-0045 §7, ADR-0078 §5).
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
        # Rules 1 and 2: properties of the proposal alone, ruled on before any
        # conflict is read (:func:`_rule_on_admissibility`).
        inadmissible = _rule_on_admissibility(proposal)
        if inadmissible is not None:
            return inadmissible

        # Rule 3: a *confirmed* proposal, judged only after the floor above and
        # ahead of every conflict rule below (:func:`_rule_on_confirmation`,
        # ADR-0078 §5a). `None` falls through to the ordinary rules — deliberately,
        # because the confirmed path overrides the arms that would re-defer an
        # answered question and *not* the arms an assertion is entitled to override
        # without asking (ADR-0038).
        if proposal.confirmation is not None:
            confirmed = _rule_on_confirmation(proposal.confirmation, conflicts)
            if confirmed is not None:
                return confirmed

        return self._rule_on_conflicts(proposal, conflicts)

    def _rule_on_conflicts(
        self, proposal: MemoryUpdateProposal, conflicts: Sequence[MemoryRecord]
    ) -> MemoryDecision:
        """Rules 4 to 10: the ordinary conflict and confidence rules.

        The ruling a proposal gets when the admissibility floor let it through and
        no confirmation settled it — which is *every* proposal today except a
        re-submitted answer, and a confirmed one whose authority no longer names a
        live assertion (:func:`_rule_on_confirmation` step 3). A separate method so
        the confirmed path has something to fall *through to* by name rather than by
        control flow.
        """
        record = proposal.proposed
        is_asserted = record.provenance.source is MemorySource.USER_ASSERTED
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

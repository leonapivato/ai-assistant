"""A first, deterministic :class:`~ai_assistant.core.protocols.MemoryPolicy`.

This is the "dispose" half of the propose/dispose write path: a producer builds a
:class:`~ai_assistant.core.types.MemoryUpdateProposal`, and this policy rules on it
with simple, explainable rules. It holds no state and performs no I/O — the
conflicting records it reasons about are passed in, so it stays decoupled from the
store and trivially testable.

**It reads a memory through ADR-0328 §12** (§11:10, §13:4). Every rule below was
written over a ``MemorySource`` or a confidence, and keeps what it decided read on
the memory's band (§6:4): its asserted arms key on band ``ASSERTED`` (standing
confirmed or said), its derived arms on ``DERIVED`` (inference), its attested arms on
``ATTESTED`` (from a source), and its taint floor on a ``DERIVED`` proposal that
rests on outside content (§7:6) and carries no confirmation. Rule 13 retired with the
stored confidence it read (§10:3): no proposal is stored tentatively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    BeliefBand,
    ConflictRelation,
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryKind,
    part_episode,
    record_band,
)
from ai_assistant.memory._agreement import agrees

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import (
        Attestation,
        Memory,
        MemoryRecord,
        MemoryUpdateProposal,
        UserConfirmation,
    )

# The **retirement class**: bands a user assertion may retire (ADR-0038 §2, widened by
# ADR-0092 §4, read through ADR-0328 §12). An allow-list rather than "not ASSERTED",
# so a band added later is not silently enrolled in a destructive rule by omission
# (ADR-0038 §2a). ``ATTESTED`` is in it because a connected source is an *input* and
# not the truth (ADR-0092 §4). **It is not the writer's reinforce-safe class**, and the
# two answer different questions (ADR-0092 §5).
_RETIREMENT_CLASS = frozenset({BeliefBand.DERIVED, BeliefBand.ATTESTED})

# The target bands an **agreeing fold** may land on (ADR-0121 §3, ADR-0214 §2): a fold
# that only adds supports to a memory the store already holds. ``ATTESTED`` is excluded
# for ADR-0121 §3's reason, and the exclusion is not an oversight to tidy up later.
_AGREEMENT_FOLDABLE = frozenset({BeliefBand.DERIVED, BeliefBand.ASSERTED})

# The target bands ADR-0159 §4's two exceptions may name — the derived band, and only
# that one (ADR-0092 §5's reason, applied a third time). ADR-0161 §1's clause (ii) is
# held in :func:`_re_reported` rather than by widening this set (ADR-0161 §3).
_RELATION_TARGETS = frozenset({BeliefBand.DERIVED})


def _asserted(record: MemoryRecord) -> bool:
    """Whether ``record`` is in the ``ASSERTED`` band (ADR-0328 §12's first row)."""
    return record_band(record) is BeliefBand.ASSERTED


def _rule_on_admissibility(proposal: MemoryUpdateProposal) -> MemoryDecision | None:
    """The three rulings that precede any conflict reasoning, or ``None``.

    All three are properties of the proposal alone, so none needs to look at what it
    contradicts — and none commits anything, so ADR-0004 §3 holds whichever fires:

    1. **Secret-tier data defers** (ADR-0004 §3). Tier 0 belongs in the OS keyring,
       never the memory store.
    2. **A derived memory resting on no episode is rejected** (ADR-0077 §5, read
       through ADR-0328 §12: "the evidence it cites" is the episodes its supports
       point at). Behind the secret gate, so a Tier-0 proposal gets the more
       informative ``ASK_USER``.
    3. **An unconfirmed derived memory resting on outside content defers** (ADR-0106
       §6, ADR-0328 §13:4). Behind both: a secret and tainted proposal takes the
       secret path, and a tainted one resting on nothing is a ``REJECT`` rather than a
       question no answer could make admissible.
    """
    if proposal.sensitivity is DataTier.SECRET:
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason="secret-tier data requires explicit user confirmation",
        )
    if _cites_nothing_it_must_cite(proposal.proposed):
        return MemoryDecision(
            kind=MemoryDecisionKind.REJECT,
            reason="a derived memory resting on no episode has no warrant (ADR-0077 §5)",
        )
    if _rests_on_outside_content_unconfirmed(proposal):
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason=(
                "this memory rests on outside content, so it is not committed without "
                "your answer (ADR-0106 §6)"
            ),
        )
    return None


def clears_admissibility_floor(proposal: MemoryUpdateProposal) -> bool:
    """Whether :func:`_rule_on_admissibility` leaves ``proposal`` admissible.

    ADR-0159 §2's invocation condition reads the floor **through this predicate**
    rather than restating it, so a ruling later added to the floor excludes its
    population there too. It is a property of the proposal alone, so it binds
    ``MemoryIngestor`` whatever ``MemoryPolicy`` was injected.

    Args:
        proposal: The proposal about to be ingested.

    Returns:
        Whether no floor ruling fires on it.
    """
    return _rule_on_admissibility(proposal) is None


def _rests_on_outside_content_unconfirmed(proposal: MemoryUpdateProposal) -> bool:
    """Whether ADR-0106 §6's ceiling fires on ``proposal`` (ADR-0328 §13:4).

    Band-scoped: an ``ATTESTED`` memory rests on outside content by its nature and
    must still be allowed to commit — a faithful transcription at a band that already
    caps its standing is not the model-authored generalisation the rule is about
    (ADR-0098 §4). A confirmation passes it.

    Args:
        proposal: The proposal being ruled on.

    Returns:
        Whether the proposal is a derived, tainted, unconfirmed one.
    """
    memory = proposal.proposed
    return (
        memory.band is BeliefBand.DERIVED
        and memory.rests_on_outside_content
        and proposal.confirmation is None
    )


def _cites_nothing_it_must_cite(memory: Memory) -> bool:
    """Whether ``memory`` is a derived memory none of whose supports points at an episode.

    ADR-0077 §5's gate half, read through ADR-0328 §12. A memory always carries a
    support (§3:3), so the case that remains is a derived memory resting only on
    records stored before ADR-0328 — which no producer proposes, and which this rule
    keeps out if one ever does.
    """
    return memory.band is BeliefBand.DERIVED and all(
        part_episode(support.points_at) is None for support in memory.supports
    )


def _rule_on_confirmation(
    confirmation: UserConfirmation, conflicts: Sequence[MemoryRecord]
) -> MemoryDecision | None:
    """Rule on a *confirmed* proposal, or ``None`` to fall through (ADR-0078 §5a).

    Runs **ahead of every conflict rule and behind the admissibility floor**: ahead,
    because the assertion arms would otherwise re-defer the answer to the question
    they just asked; behind, because nothing a confirmation says makes a floor ruling
    safe to skip. Three steps, in order:

    1. **An asserted conflict outside the answer's authority → ``ASK_USER``.** A live
       conflict in the ``ASSERTED`` band not named in ``confirmation.retires`` was
       never shown to the user, so extending their answer to it would forge consent.
    2. **Otherwise ``SUPERSEDE`` the first asserted target in ``retires`` that is
       live.** ``retires`` is a ceiling, not an instruction.
    3. **Otherwise fall through** (``None``) to the ordinary rules.

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
            if _asserted(conflict) and conflict.id not in confirmation.retires
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
    live_asserted = {conflict.id for conflict in conflicts if _asserted(conflict)}
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


def _foldable_agreeing(memory: Memory, conflicts: Sequence[MemoryRecord]) -> MemoryRecord | None:
    """The best-ranked conflict an agreeing fold may land on, or ``None`` (ADR-0121 §2).

    A scan rather than ``conflicts[0]``: rank is the tie-break, never the ruling.
    """
    return next(
        (
            conflict
            for conflict in conflicts
            if record_band(conflict) in _AGREEMENT_FOLDABLE and agrees(conflict, memory)
        ),
        None,
    )


def _an_assertion_disagrees(memory: Memory, conflicts: Sequence[MemoryRecord]) -> bool:
    """Whether an ``ASSERTED`` member of the set does not agree with ``memory`` (ADR-0121 §2)."""
    return any(_asserted(conflict) and not agrees(conflict, memory) for conflict in conflicts)


def _rule_on_agreement(memory: Memory, conflicts: Sequence[MemoryRecord]) -> MemoryDecision | None:
    """Rule ``REINFORCE`` on an agreeing restatement, or ``None`` (ADR-0121 §2).

    The best-ranked member of the foldable agreeing set, exactly when that set is
    non-empty and every ``ASSERTED`` member of the conflict set agrees — the second
    condition keeps #245 closed. It reads no score, and it retires nothing: a
    ``REINFORCE`` only adds the proposal's supports to the target (ADR-0328 §11:6).

    Args:
        memory: The proposed memory, in the ``ASSERTED`` band.
        conflicts: The conflict set, best-ranked first.

    Returns:
        The ``REINFORCE`` ruling, or ``None``.
    """
    foldable = _foldable_agreeing(memory, conflicts)
    if foldable is None or _an_assertion_disagrees(memory, conflicts):
        return None
    return MemoryDecision(
        kind=MemoryDecisionKind.REINFORCE,
        target_id=foldable.id,
        reason="you have said this before; recorded as agreement, not a change (ADR-0121 §2)",
    )


def _rule_on_agreeing_observation(
    memory: Memory, conflicts: Sequence[MemoryRecord]
) -> MemoryDecision | None:
    """Rule ``REINFORCE`` on a derived memory agreeing with an assertion, or ``None``.

    ADR-0214 §1's arm, evaluated only for a ``DERIVED`` proposal whose conflict set
    holds an ``ASSERTED`` member, and firing exactly when every asserted member
    agrees. The fold adds the proposal's supports to the target and changes nothing
    else about it (ADR-0328 §11:6), which is why the writer admits it onto an
    assertion (ADR-0214 §3).

    Args:
        memory: The proposed memory, not in the ``ASSERTED`` band.
        conflicts: The conflict set, best-ranked first, holding an asserted member.

    Returns:
        The ``REINFORCE`` ruling, or ``None`` to fall through to the deferral.
    """
    if memory.band not in _AGREEMENT_FOLDABLE or _an_assertion_disagrees(memory, conflicts):
        return None
    foldable = _foldable_agreeing(memory, conflicts)
    if foldable is None:
        return None
    return MemoryDecision(
        kind=MemoryDecisionKind.REINFORCE,
        target_id=foldable.id,
        reason="this agrees with what you told us; recorded as corroboration (ADR-0214 §1)",
    )


def _effective_relations(
    memory: Memory,
    conflicts: Sequence[MemoryRecord],
    relations: Mapping[str, ConflictRelation] | None,
) -> dict[str, ConflictRelation]:
    """The relations ADR-0159 §4's arm rules on: the certain rung, then what it was handed.

    A pair that ``agrees`` under ADR-0121 §1 **is** ``RESTATES``, always (ADR-0159 §3),
    so the certain predicate is computed here and wins; with no reconciler this is
    ADR-0159 §6's floor. Entries keyed on a non-member are ignored structurally
    (ADR-0159 §8), since the mapping is read through ``conflicts``.

    Args:
        memory: The proposed memory.
        conflicts: The conflict set, best-ranked first.
        relations: What the caller determined, or ``None`` where nothing did.

    Returns:
        A relation per member one is held for.
    """
    supplied = relations if relations is not None else {}
    effective: dict[str, ConflictRelation] = {}
    for conflict in conflicts:
        if agrees(conflict, memory):
            effective[conflict.id] = ConflictRelation.RESTATES
            continue
        given = supplied.get(conflict.id)
        if given is not None:
            effective[conflict.id] = given
    return effective


def _reported_by(record: MemoryRecord) -> str | None:
    """The source a record's attestation names, read through ADR-0328 §12, or ``None``."""
    attestation: Attestation | None = (
        record.standing_attestation if record.kind == MemoryKind.MEMORY.value else None
    )
    return None if attestation is None else attestation.reported_by


def _re_reported(conflict: MemoryRecord, memory: Memory) -> bool:
    """Whether ``conflict`` is eligible under ADR-0161 §1's clause (ii).

    The proposed memory and the conflict are both ``ATTESTED``, their source details
    name the same reporting source, and they **agree** under ADR-0121 §1: a scheduled
    reader re-reporting an entry it already reported (read through ADR-0328 §12).

    Args:
        conflict: A member of the conflict set.
        memory: The proposed memory.

    Returns:
        Whether this member is the proposal's own prior report, unchanged.
    """
    if memory.band is not BeliefBand.ATTESTED or record_band(conflict) is not BeliefBand.ATTESTED:
        return False
    source = _reported_by(memory)
    return source is not None and _reported_by(conflict) == source and agrees(conflict, memory)


def _rule_on_relations(
    memory: Memory,
    conflicts: Sequence[MemoryRecord],
    relations: Mapping[str, ConflictRelation] | None,
) -> MemoryDecision | None:
    """ADR-0159 §4's two exceptions (as ADR-0161 §1 replaced the first), or ``None``.

    ``ACCEPT`` is the default and **each write is the exception**:

    - **(a) ``REINFORCE``** at the best-ranked eligible member: clause (ii), the
      proposal's own prior report unchanged (:func:`_re_reported`), named ahead of
      anything; or clause (i), a ``DERIVED`` member labelled ``RESTATES`` while **no**
      member is labelled ``CONTRADICTS``.
    - **(b) ``SUPERSEDE``** at the best-ranked ``DERIVED`` member labelled
      ``CONTRADICTS``, while **no** member is labelled ``RESTATES``.

    Unlabelled members block nothing, and rank only breaks a tie the clauses already
    selected.

    Args:
        memory: The proposed memory — not asserted, and its conflict set holding no
            assertion either.
        conflicts: The conflict set, best-ranked first.
        relations: What the caller determined about members of that set.

    Returns:
        The ruling, or ``None`` for ADR-0159 §4(c).
    """
    effective = _effective_relations(memory, conflicts, relations)
    restating = [c for c in conflicts if effective.get(c.id) is ConflictRelation.RESTATES]
    contradicting = [c for c in conflicts if effective.get(c.id) is ConflictRelation.CONTRADICTS]
    re_reported = next((c for c in conflicts if _re_reported(c, memory)), None)
    if re_reported is not None:
        return MemoryDecision(
            kind=MemoryDecisionKind.REINFORCE,
            target_id=re_reported.id,
            reason=(
                "the connected source reported this unchanged; folded onto the record "
                "it already reported (ADR-0161 §1)"
            ),
        )
    if restating and not contradicting:
        target = next((c for c in restating if record_band(c) in _RELATION_TARGETS), None)
        if target is not None:
            return MemoryDecision(
                kind=MemoryDecisionKind.REINFORCE,
                target_id=target.id,
                reason="this restates a memory already held; recorded as agreement (ADR-0159 §4)",
            )
    if contradicting and not restating:
        target = next((c for c in contradicting if record_band(c) in _RELATION_TARGETS), None)
        if target is not None:
            return MemoryDecision(
                kind=MemoryDecisionKind.SUPERSEDE,
                target_id=target.id,
                reason="this contradicts a memory already held, which it corrects (ADR-0159 §4)",
            )
    return None


def _contradicting(
    conflicts: Sequence[MemoryRecord], effective: Mapping[str, ConflictRelation]
) -> list[MemoryRecord]:
    """The members labelled ``CONTRADICTS``, best-ranked first (ADR-0336 §3, §4)."""
    return [c for c in conflicts if effective.get(c.id) is ConflictRelation.CONTRADICTS]


def _rule_on_a_prior_assertion(
    memory: Memory,
    conflicts: Sequence[MemoryRecord],
    relations: Mapping[str, ConflictRelation] | None,
) -> MemoryDecision:
    """Rule on a **non-asserted** proposal whose conflict set holds an assertion (ADR-0336 §4).

    An agreeing derived memory folds (ADR-0214 §1, :func:`_rule_on_agreeing_observation`),
    evaluated first and exactly as it stands. Otherwise the proposal defers exactly when
    an ``ASSERTED`` member is labelled ``CONTRADICTS`` — an inference never silently
    overrides an assertion (ADR-0038 §3) — and is installed beside the set otherwise.
    An assertion that only shares a subject with the proposal is no question, and an
    unlabelled one is never the ground of one (§6:1).

    Args:
        memory: The proposed memory, not in the ``ASSERTED`` band.
        conflicts: The conflict set, holding at least one asserted member.
        relations: What the writer determined about members of that set.

    Returns:
        The ruling.
    """
    agreeing = _rule_on_agreeing_observation(memory, conflicts)
    if agreeing is not None:
        return agreeing
    effective = _effective_relations(memory, conflicts, relations)
    if any(_asserted(c) for c in _contradicting(conflicts, effective)):
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason="contradicts a user-asserted memory; defer to the user (ADR-0336 §4)",
        )
    return MemoryDecision(
        kind=MemoryDecisionKind.ACCEPT,
        reason=("installed beside a user-asserted memory it does not contradict (ADR-0336 §4)"),
    )


def _rule_on_assertion(
    memory: Memory,
    conflicts: Sequence[MemoryRecord],
    relations: Mapping[str, ConflictRelation] | None,
) -> MemoryDecision:
    """Rule on an asserted proposal (ADR-0336 §3): agree, defer, supersede, or accept.

    0. **An agreeing restatement → ``REINFORCE``** (ADR-0121 §2), evaluated first and
       exactly as it stands. It is the only ``REINFORCE`` this arm rules (§3:3): a
       model-labelled ``RESTATES`` is installed beside, since a fold would lift the
       target to "you said it" on a model's judgement.
    1. **An ``ASSERTED`` member labelled ``CONTRADICTS`` → ``ASK_USER``** (§3(a)): two
       contradictory assertions cannot both stay live, and neither is destroyed here.
    2. **Otherwise a member labelled ``CONTRADICTS`` in the retirement class →
       ``SUPERSEDE``** at the best-ranked one (§3(b)); the writer retires it and the
       other labelled contradictions in that class, and nothing else (§5).
    3. **Otherwise ``ACCEPT``** (§3(c)), installed beside whatever the set holds, with
       a ``reason`` telling an empty set from one nothing in contradicts.

    Every arm reads relations and bands, never a score or a threshold, and rank only
    breaks a tie among members the relations already selected (§3:2).

    Args:
        memory: The proposed memory, in the ``ASSERTED`` band.
        conflicts: The conflict set, best-ranked first.
        relations: What the writer determined about members of that set.

    Returns:
        The ruling.
    """
    agreed = _rule_on_agreement(memory, conflicts)
    if agreed is not None:
        return agreed
    contradicting = _contradicting(conflicts, _effective_relations(memory, conflicts, relations))
    if any(_asserted(c) for c in contradicting):
        return MemoryDecision(
            kind=MemoryDecisionKind.ASK_USER,
            reason="contradicts a prior user assertion; defer to the user (ADR-0336 §3)",
        )
    superseded = next((c for c in contradicting if record_band(c) in _RETIREMENT_CLASS), None)
    if superseded is not None:
        return MemoryDecision(
            kind=MemoryDecisionKind.SUPERSEDE,
            target_id=superseded.id,
            reason="user assertion supersedes the memories it contradicts (ADR-0336 §3)",
        )
    if conflicts:
        return MemoryDecision(
            kind=MemoryDecisionKind.ACCEPT,
            reason=(
                "user-asserted; similar memories exist but none is contradicted, so it is "
                "installed beside them (ADR-0336 §3)"
            ),
        )
    return MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="user-asserted; no conflict")


class DefaultMemoryPolicy:
    """A conservative default policy for memory writes (ADR-0328 §13:4).

    Structurally implements :class:`~ai_assistant.core.protocols.MemoryPolicy`, its
    rules read through ADR-0328 §12. In order:

    1. Secret-tier proposals always defer to the user.
    2. A ``DERIVED`` memory resting on no episode is rejected (ADR-0077 §5).
    3. An **unconfirmed** ``DERIVED`` memory resting on outside content defers to the
       user (ADR-0106 §6).
    4. A confirmed proposal is judged by :func:`_rule_on_confirmation`: it re-defers
       where the live set holds an assertion the user was never shown, supersedes the
       confirmed assertion where one is live, and otherwise falls through.
    5. A ``DERIVED`` proposal agreeing with every assertion in its conflict set
       rules ``REINFORCE`` (ADR-0214 §1), evaluated only where the set holds an
       assertion.
    6. Otherwise a non-asserted proposal whose set holds an assertion defers exactly
       when an ``ASSERTED`` member is labelled ``CONTRADICTS``, and is accepted
       beside the set otherwise (ADR-0336 §4).
    7. An asserted proposal agreeing with what it conflicts with rules ``REINFORCE``
       (ADR-0121 §2) — the only ``REINFORCE`` an asserted proposal is ruled
       (ADR-0336 §3:3).
    8. An asserted proposal defers exactly when an ``ASSERTED`` member is labelled
       ``CONTRADICTS`` (ADR-0336 §3(a), narrowing ADR-0050 §2).
    9. Otherwise an asserted proposal supersedes the best-ranked ``DERIVED`` or
       ``ATTESTED`` member labelled ``CONTRADICTS`` (ADR-0336 §3(b), narrowing
       ADR-0038 §1 and ADR-0092 §4).
    10. Otherwise an asserted proposal is accepted, installed beside what it
        resembles, with a ``reason`` telling "no conflict" from "conflicts, none
        contradicted" (ADR-0336 §3(c)).
    11. A non-asserted proposal rules ``REINFORCE`` at an eligible member
        (ADR-0159 §4a as ADR-0161 §1 replaced it).
    12. Otherwise a member labelled ``CONTRADICTS``, and none ``RESTATES``, is
        superseded (ADR-0159 §4b).
    13. Retired: a proposal is never stored tentatively (ADR-0328 §10:3). This policy
        rules ``STORE_TEMPORARY`` on nothing.
    14. Otherwise the proposal is accepted, with a ``reason`` telling "no conflict"
        from "conflicts, none restating and none contradicting" (ADR-0159 §4).

    **A placed proposal is ruled by rules 1 to 4 alone** (ADR-0345 §4:5): past them it is
    accepted, and the writer applies its placement. Rules 5 to 12 read no placed
    proposal.

    It takes no construction-time knob: ``min_confidence`` and ``temporary_ttl``
    retired with rule 13 (ADR-0328 §10:3).
    """

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
        relations: Mapping[str, ConflictRelation] | None = None,
    ) -> MemoryDecision:
        """Rule on a proposed memory. See the class docstring for rules.

        A total function of its three arguments — no store, no clock, no model, no
        network (ADR-0159 §2). ``relations`` is read by rules 6, 8, 9, 11 and 12, and
        is never mutated. An unlabelled member supplies ground for no supersession and
        no deferral (ADR-0336 §6).
        """
        inadmissible = _rule_on_admissibility(proposal)
        if inadmissible is not None:
            return inadmissible
        if proposal.confirmation is not None:
            confirmed = _rule_on_confirmation(proposal.confirmation, conflicts)
            if confirmed is not None:
                return confirmed
        if proposal.placement is not None:
            # ADR-0345 §4:5: rules 5 to 12 read no placed proposal. Its producer has
            # said how it stands to each memory it read, and the writer applies that.
            return MemoryDecision(
                kind=MemoryDecisionKind.ACCEPT,
                reason="placed: the writer applies its placement (ADR-0345 §4:5)",
            )
        return self._rule_on_conflicts(proposal, conflicts, relations)

    @staticmethod
    def _rule_on_conflicts(
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
        relations: Mapping[str, ConflictRelation] | None,
    ) -> MemoryDecision:
        """Rules 5 to 14: the ordinary conflict rules."""
        memory = proposal.proposed
        is_asserted = memory.band is BeliefBand.ASSERTED
        if not is_asserted and any(_asserted(conflict) for conflict in conflicts):
            return _rule_on_a_prior_assertion(memory, conflicts, relations)
        if is_asserted:
            return _rule_on_assertion(memory, conflicts, relations)
        related = _rule_on_relations(memory, conflicts, relations)
        if related is not None:
            return related
        if conflicts:
            return MemoryDecision(
                kind=MemoryDecisionKind.ACCEPT,
                reason=(
                    "similar memories exist but none restates or contradicts this one (ADR-0159 §4)"
                ),
            )
        return MemoryDecision(kind=MemoryDecisionKind.ACCEPT, reason="no conflict")

"""Shared conformance suite for the MemoryPolicy Protocol.

Every ``MemoryPolicy`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryPolicyContract` and overrides the ``policy`` fixture.

The suite asserts only what is universal to the contract — that ``decide`` is
total, deterministic, returns an internally coherent decision, never commits
secret-tier data, and never commits an unconfirmed derived proposal whose warrant
rests on recorded external content. It deliberately does **not** encode *which*
ruling a given proposal earns: that is each policy's reasoning, and even the
default's changes — ADR-0038 rewrote what it returns for a user-asserted
proposal that meets a conflict, without touching a line here, which is the
separation working. ``DefaultMemoryPolicy``'s specific rules are tested in
``test_policy.py``.

Every obligation here traces to something already ratified — determinism to the
``MemoryPolicy`` docstring, the secret-tier rule to ADR-0004 §3, the taint ceiling
to ADR-0106 §6 (which ADR-0106 §10 promotes here by name, as golden rule 5
requires of any widening), the coherence of ``target_id`` to what ``decide`` says
its ``conflicts`` argument is. A
conformance suite **is** contract: an obligation the Protocol does not state
widens that contract without an ADR (golden rule 5) and would fail an
implementation that actually conforms. Two reasonable-sounding expectations were
cut for exactly that reason — that ``decide`` leaves its inputs alone, and that
``reason`` is non-blank. Both are tested per-implementation instead, and
Issue #40 tracks ratifying them properly.

It also does **not** assert *which* relation a target-carrying ruling picks —
``REINFORCE`` versus ``SUPERSEDE`` — for a given proposal (ADR-0040 §5): that is
the policy's reasoning, and pinning it here would refuse a policy that genuinely
conforms. Only the coherence common to both is asserted.

Two things are intentionally left unasserted because ``MemoryDecision``'s own
validator already makes them unrepresentable: that ``REINFORCE`` and
``SUPERSEDE`` carry a ``target_id`` and that ``STORE_TEMPORARY`` carries a
positive ``ttl``. Asserting them here would test pydantic. What the validator
*cannot* know — that ``target_id`` names one of the records actually supplied —
is asserted below.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ai_assistant.core.protocols import MemoryPolicy
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    DataTier,
    EpisodicMemory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
    UserConfirmation,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The top of the sweep for a belief in the DERIVED band, which may not claim the
#: standing only the user's own word carries (ADR-0077 §7).
_JUST_BELOW_FULL = 0.99

# Decisions that result in the proposal reaching long-term storage. ASK_USER and
# REJECT do not: one defers to a human, the other drops the proposal.
_COMMITTING = frozenset(
    {
        MemoryDecisionKind.ACCEPT,
        MemoryDecisionKind.REINFORCE,
        MemoryDecisionKind.SUPERSEDE,
        MemoryDecisionKind.STORE_TEMPORARY,
    }
)

# The rulings that name a target drawn from `conflicts`; the coherence of that
# target is asserted for either, but never which of the two a policy picks.
_TARGET_CARRYING = frozenset({MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE})


# Every concrete `MemoryRecord` variant. A policy is handed the union, so a
# suite that only ever builds one variant would certify a policy that crashes on
# the other three.
_RECORD_KINDS = ("semantic", "episodic", "preference", "procedural")

# The two halves of the band partition ADR-0106 §6's ceiling is keyed on, derived
# from `band_of` rather than spelled as source names, so a `MemorySource` added to
# either band later is covered without an edit here.
_DERIVED_SOURCES = tuple(s for s in MemorySource if band_of(s) is BeliefBand.DERIVED)
_SOURCES_OUTSIDE_DERIVED = tuple(s for s in MemorySource if band_of(s) is not BeliefBand.DERIVED)

#: What a derived proposal cites, so the taint cases below measure ADR-0106 §6's
#: ceiling rather than ADR-0077 §5's rejection of a derived belief citing nothing.
#: The two sit in the same admissibility floor with the evidence rule *ahead* of
#: the taint rule, so a tainted case citing nothing would be answered by the wrong
#: one and pass against a policy with no taint rule at all.
_EPISODE = "episode-1"


def _record(  # noqa: PLR0913 — one keyword per axis of the input space, all optional
    record_id: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    confidence: float = 0.6,
    record_kind: str = "semantic",
    derived_from_external: bool = False,
    evidence: tuple[str, ...] = (),
) -> MemoryRecord:
    # `Provenance` pins USER_ASSERTED to full confidence, and — since ADR-0077 §7
    # — forbids the DERIVED band from claiming it at all. Either way the requested
    # value is overridden rather than allowed to build a record the domain
    # forbids. This clips the confidence sweep at both ends, by design: the suite
    # exercises what a policy can actually be handed, and the top of the range for
    # a derived belief is now just below 1.0 rather than 1.0.
    if source is MemorySource.USER_ASSERTED:
        confidence = 1.0
    elif band_of(source) is BeliefBand.DERIVED and confidence == 1.0:
        confidence = _JUST_BELOW_FULL
    # And since ADR-0092 §1 the `ATTESTED` band must carry an attestation, on the
    # same principle: the suite hands a policy what a producer can actually build,
    # so the obligation is met from the band rather than by naming `EXTERNAL` — a
    # source added into that band later is covered without an edit here.
    attestation = (
        Attestation(reported_by="source-instance", reported_at=_WHEN)
        if band_of(source) is BeliefBand.ATTESTED
        else None
    )
    provenance = Provenance(
        source=source,
        confidence=confidence,
        last_updated=_WHEN,
        attestation=attestation,
        derived_from_external=derived_from_external,
        evidence=evidence,
    )
    match record_kind:
        case "episodic":
            return EpisodicMemory(
                id=record_id, content=record_id, provenance=provenance, occurred_at=_WHEN
            )
        case "preference":
            return PreferenceMemory(
                id=record_id, content=record_id, provenance=provenance, preference=record_id
            )
        case "procedural":
            return ProceduralMemory(
                id=record_id, content=record_id, provenance=provenance, situation=record_id
            )
        case _:
            return SemanticMemory(
                id=record_id, content=record_id, provenance=provenance, fact=record_id
            )


@dataclass(frozen=True)
class _Case:
    """One point in the input space ``decide`` must handle."""

    record_kind: str
    source: MemorySource
    confidence: float
    sensitivity: DataTier
    conflict_source: MemorySource | None
    """The provenance of the conflicting record, or ``None`` for no conflict."""

    def __str__(self) -> str:
        conflict = "clean" if self.conflict_source is None else f"vs-{self.conflict_source}"
        return f"{self.record_kind}-{self.source}-{self.confidence}-{self.sensitivity}-{conflict}"


# The full cross-product of everything a caller can vary. Bundled into one
# parameter rather than stacked `parametrize` decorators, which would push the
# test past the argument limit.
#
# The conflict axis carries a *source*, not just a yes/no: a policy branching on
# whether the record it would overwrite was user-asserted is not hypothetical —
# `DefaultMemoryPolicy` does exactly that — so a matrix whose conflicts are
# always OBSERVED would leave that branch uncertified.
_TOTALITY_CASES = [
    _Case(record_kind, source, confidence, sensitivity, conflict_source)
    for record_kind, source, confidence, sensitivity, conflict_source in product(
        _RECORD_KINDS,
        MemorySource,
        [0.0, 0.5, 1.0],
        DataTier,
        [None, *MemorySource],
    )
]


def _proposal(
    record: MemoryRecord | None = None,
    *,
    sensitivity: DataTier = DataTier.PERSONAL,
    conflicts: Sequence[MemoryRecord] = (),
    confirmed: bool = False,
) -> MemoryUpdateProposal:
    # `decide` documents that the proposal carries the ids of the records passed
    # alongside it. Deriving them here keeps the two arguments consistent: a
    # proposal claiming no conflicts while conflicting records are handed over is
    # input no caller would produce, and a policy that cross-checks the two would
    # be failed by the suite for being right.
    proposal = MemoryUpdateProposal(
        proposed=record if record is not None else _record("proposed"),
        rationale="because",
        sensitivity=sensitivity,
        conflicts=tuple(c.id for c in conflicts),
    )
    if not confirmed:
        return proposal
    # Built in two steps because the authority binds to the *question*, and the
    # question's identity is a property of the proposal (ADR-0078 §7). A hand-picked
    # digest would be input no coordinator produces, and a policy checking the two
    # agree — which the writer's `_confirmation_covers` does — would be failed by
    # this suite for being right.
    return MemoryUpdateProposal(
        proposed=proposal.proposed,
        rationale=proposal.rationale,
        sensitivity=proposal.sensitivity,
        conflicts=proposal.conflicts,
        confirmation=UserConfirmation(
            deferral_id="deferral-1",
            question_key=proposal.question_key,
            confirmed_at=_WHEN,
            retires=tuple(c.id for c in conflicts),
        ),
    )


def _inputs_for(case: _Case) -> tuple[MemoryUpdateProposal, list[MemoryRecord]]:
    """Build the ``(proposal, conflicts)`` pair one matrix case describes."""
    conflicts = (
        [_record("existing", source=case.conflict_source, record_kind=case.record_kind)]
        if case.conflict_source is not None
        else []
    )
    proposal = _proposal(
        _record(
            "new",
            source=case.source,
            confidence=case.confidence,
            record_kind=case.record_kind,
        ),
        sensitivity=case.sensitivity,
        conflicts=conflicts,
    )
    return proposal, conflicts


class MemoryPolicyContract:
    """The behavioural contract every ``MemoryPolicy`` must satisfy."""

    @pytest.fixture
    def policy(self) -> MemoryPolicy:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, policy: MemoryPolicy) -> None:
        assert isinstance(policy, MemoryPolicy)

    @pytest.mark.parametrize("case", _TOTALITY_CASES, ids=str)
    async def test_contract_holds_for_every_proposal(
        self, policy: MemoryPolicy, case: _Case
    ) -> None:
        """Check every universal obligation against one point of the input space.

        The obligations are asserted together, over one matrix, rather than each
        against its own small set of inputs. Splitting them is how a policy slips
        through the gaps between them: deferring a secret on the first call and
        committing it on the retry satisfies a one-call secret check *and* a
        determinism check that never uses a secret, while leaking Tier-0 data.
        """
        proposal, conflicts = _inputs_for(case)

        # Called twice: determinism is only observable across repeated calls, and
        # every other obligation below then holds for the retry as well as the
        # first attempt.
        decision = await policy.decide(proposal, conflicts=conflicts)
        again = await policy.decide(proposal, conflicts=conflicts)

        # Total: every proposal earns a ruling, so the write path can never stall
        # on an unhandled combination.
        assert isinstance(decision, MemoryDecision)
        # Deterministic (the `MemoryPolicy` docstring). The whole decision, not
        # just its kind: an alternating ttl changes when the record expires.
        assert decision == again
        # The fold target, which the model's validator cannot check.
        if decision.kind in _TARGET_CARRYING:
            assert decision.target_id in {c.id for c in conflicts}
        # ADR-0004 §3: Tier 0 data belongs in the OS keyring, never the memory
        # store — whatever the policy's other rules, however trusted the source,
        # and on the retry as much as the first call.
        if case.sensitivity is DataTier.SECRET:
            assert decision.kind not in _COMMITTING

    @pytest.mark.parametrize("record_kind", _RECORD_KINDS)
    @pytest.mark.parametrize("source", _DERIVED_SOURCES, ids=str)
    async def test_an_unconfirmed_tainted_derived_proposal_is_never_committed(
        self, policy: MemoryPolicy, source: MemorySource, record_kind: str
    ) -> None:
        """ADR-0106 §6's ceiling, at the enforcement point ADR-0098 §5 could not site.

        A belief this system worked out from recorded external material is never
        auto-accepted into durable memory — whatever the policy's other rules, and
        however trusted the producer (ADR-0098 §4's fourth clause). ``ASK_USER``
        and ``REJECT`` both conform; the suite pins neither, because a deployment
        somewhere a user cannot be asked conforms by refusing.

        Asserted on the retry as well as the first call, for the reason the
        secret-tier obligation is: a policy that defers once and commits on the
        second attempt satisfies a one-call check while committing exactly what
        the ceiling forbids.
        """
        record = _record(
            "tainted",
            source=source,
            record_kind=record_kind,
            derived_from_external=True,
            evidence=(_EPISODE,),
        )

        decision = await policy.decide(_proposal(record), conflicts=[])
        again = await policy.decide(_proposal(record), conflicts=[])

        assert decision.kind not in _COMMITTING
        assert again.kind not in _COMMITTING

    @pytest.mark.parametrize("source", _DERIVED_SOURCES, ids=str)
    async def test_the_ceiling_does_not_reach_the_confirmed_re_ingest(
        self, policy: MemoryPolicy, source: MemorySource
    ) -> None:
        """The confirmed answer is a *re-ingest*, and the ceiling stands down for it.

        ADR-0078 §5: the coordinator rebuilds the proposal with the user's
        authority and calls the writer again — marker and all. So the suite
        **covers** the confirmed case rather than asserting the ceiling over it
        (ADR-0106 §6): a policy that commits the answered proposal is conforming
        and must not be failed here, and one that fires the ceiling a second time
        would ask the user the question they just answered, which is the failure
        ADR-0078 §3 names in its own words.

        What is asserted is what is universal on any input — a total, deterministic,
        coherent ruling — over the one input the ceiling's carve-out creates. The
        deliberate silence is the point: no ``_COMMITTING`` assertion belongs here.
        """
        record = _record(
            "tainted",
            source=source,
            derived_from_external=True,
            evidence=(_EPISODE,),
        )
        conflicts = [_record("existing")]
        proposal = _proposal(record, conflicts=conflicts, confirmed=True)

        decision = await policy.decide(proposal, conflicts=conflicts)
        again = await policy.decide(proposal, conflicts=conflicts)

        assert isinstance(decision, MemoryDecision)
        assert decision == again
        if decision.kind in _TARGET_CARRYING:
            assert decision.target_id in {c.id for c in conflicts}

    @pytest.mark.parametrize("record_kind", _RECORD_KINDS)
    @pytest.mark.parametrize("source", _SOURCES_OUTSIDE_DERIVED, ids=str)
    async def test_the_marker_decides_nothing_outside_the_derived_band(
        self, policy: MemoryPolicy, source: MemorySource, record_kind: str
    ) -> None:
        """ADR-0106 §2: the field carries no meaning outside the ``DERIVED`` band.

        ADR-0106 §7 forbids a band-keyed validator on it, so
        ``Provenance(source=USER_ASSERTED, derived_from_external=True, …)`` stays
        constructible — and a policy reading the raw flag rather than the band
        would defer a user's own assertion on the strength of a boolean that means
        nothing there, which ADR-0098 §1 forbids in principle ("the user's own
        utterance is not [external], however it was composed"). The same reading
        would defer every calendar import in the ``ATTESTED`` band.

        Stated as an **invariance** rather than as "still commits", which is what
        ADR-0106 §10 names it by: the suite runs against a ``FakeMemoryPolicy``
        configured to every ``MemoryDecisionKind`` including ``REJECT``, so an
        assertion that these proposals earn a committing ruling would fail a double
        that conforms — and the suite's own rule is that it does not encode which
        ruling a proposal earns. Whether an attested proposal genuinely still
        commits is pinned per-implementation, in ``test_policy.py``.
        """
        marked = _record(
            "marked", source=source, record_kind=record_kind, derived_from_external=True
        )
        plain = _record("marked", source=source, record_kind=record_kind)

        with_marker = await policy.decide(_proposal(marked), conflicts=[])
        without_marker = await policy.decide(_proposal(plain), conflicts=[])

        assert with_marker.kind is without_marker.kind

    async def test_fold_targets_one_of_the_supplied_conflicts(self, policy: MemoryPolicy) -> None:
        # The sweep above only ever supplies one conflict. This is the case it
        # cannot cover: with several to choose from, `target_id` must still name
        # one the caller actually offered, not an id of the policy's own making.
        conflicts = [_record("first"), _record("second")]

        decision = await policy.decide(_proposal(conflicts=conflicts), conflicts=conflicts)

        if decision.kind in _TARGET_CARRYING:
            assert decision.target_id in {c.id for c in conflicts}

    async def test_does_not_fold_when_there_is_no_conflict(self, policy: MemoryPolicy) -> None:
        # The degenerate case of the rule above: with nothing to fold into,
        # neither REINFORCE nor SUPERSEDE can name a valid target.
        decision = await policy.decide(_proposal(), conflicts=[])

        assert decision.kind not in _TARGET_CARRYING

    async def test_the_proposal_decide_receives_is_immutable(self, policy: MemoryPolicy) -> None:
        # #40's input-immutability obligation, asserted in the shared suite rather
        # than stranded in each implementation's own tests (ADR-0068 §5). A
        # conforming producer hands `decide` a validly-constructed, frozen proposal
        # whose `conflicts` is a tuple (§1's depth rule), so `decide` cannot mutate
        # it — the property is pinned against the real subject.
        #
        # Deliberately asserts nothing about the caller-owned `conflicts`
        # *Sequence* argument: a callee mutating a caller's container is the
        # reverse-direction question ADR-0065 §5 leaves open and ADR-0068 keeps
        # open (Consequences), so a conformance suite must not silently ratify it.
        conflicts = [_record("existing")]
        proposal = _proposal(conflicts=conflicts)
        before = proposal.model_copy(deep=True)

        await policy.decide(proposal, conflicts=conflicts)

        # The proposal is frozen end to end, so `decide` left it untouched and
        # could not have mutated it: its own fields, its tuple `conflicts`, and its
        # nested record all reject mutation.
        assert proposal == before
        assert isinstance(proposal.conflicts, tuple)
        with pytest.raises(ValidationError):
            proposal.proposed.content = "rewritten"  # the nested record is frozen

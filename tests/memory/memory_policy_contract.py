"""Shared conformance suite for the MemoryPolicy Protocol.

Every ``MemoryPolicy`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryPolicyContract` and overrides the ``policy`` fixture.

The suite asserts only what is universal to the contract — that ``decide`` is
total, deterministic, side-effect-free on its inputs, returns an internally
coherent decision, and never commits secret-tier data. It deliberately does
**not** encode *which* ruling a given proposal earns: that is each policy's
reasoning, and even the default's is expected to change (``TODO.md`` item 2).
``DefaultMemoryPolicy``'s specific rules are tested in ``test_policy.py``.

Two things are intentionally left unasserted because ``MemoryDecision``'s own
validator already makes them unrepresentable: that ``MERGE`` carries a
``merge_into`` and that ``STORE_TEMPORARY`` carries a positive ``ttl``. Asserting
them here would test pydantic. What the validator *cannot* know — that
``merge_into`` names one of the records actually supplied — is asserted below.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import MemoryPolicy
from ai_assistant.core.types import (
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
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

# Decisions that result in the proposal reaching long-term storage. ASK_USER and
# REJECT do not: one defers to a human, the other drops the proposal.
_COMMITTING = frozenset(
    {
        MemoryDecisionKind.ACCEPT,
        MemoryDecisionKind.MERGE,
        MemoryDecisionKind.STORE_TEMPORARY,
    }
)


# Every concrete `MemoryRecord` variant. A policy is handed the union, so a
# suite that only ever builds one variant would certify a policy that crashes on
# the other three.
_RECORD_KINDS = ("semantic", "episodic", "preference", "procedural")


def _record(
    record_id: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    confidence: float = 0.6,
    record_kind: str = "semantic",
) -> MemoryRecord:
    # `Provenance` pins USER_ASSERTED to full confidence, so the requested value
    # is overridden rather than allowed to build a record the domain forbids.
    # This makes the confidence sweep a no-op for that one source, by design: the
    # suite exercises what a policy can actually be handed.
    if source is MemorySource.USER_ASSERTED:
        confidence = 1.0
    provenance = Provenance(source=source, confidence=confidence, last_updated=_WHEN)
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
    conflicts: bool

    def __str__(self) -> str:
        conflicts = "conflicts" if self.conflicts else "clean"
        return f"{self.record_kind}-{self.source}-{self.confidence}-{self.sensitivity}-{conflicts}"


# The full cross-product of everything a caller can vary. Bundled into one
# parameter rather than stacked `parametrize` decorators, which would push the
# test past the argument limit.
_TOTALITY_CASES = [
    _Case(record_kind, source, confidence, sensitivity, conflicts=conflicts)
    for record_kind, source, confidence, sensitivity, conflicts in product(
        _RECORD_KINDS, MemorySource, [0.0, 0.5, 1.0], DataTier, [False, True]
    )
]


def _proposal(
    record: MemoryRecord | None = None,
    *,
    sensitivity: DataTier = DataTier.PERSONAL,
    conflicts: Sequence[MemoryRecord] = (),
) -> MemoryUpdateProposal:
    # `decide` documents that the proposal carries the ids of the records passed
    # alongside it. Deriving them here keeps the two arguments consistent: a
    # proposal claiming no conflicts while conflicting records are handed over is
    # input no caller would produce, and a policy that cross-checks the two would
    # be failed by the suite for being right.
    return MemoryUpdateProposal(
        proposed=record if record is not None else _record("proposed"),
        rationale="because",
        sensitivity=sensitivity,
        conflicts=[c.id for c in conflicts],
    )


class MemoryPolicyContract:
    """The behavioural contract every ``MemoryPolicy`` must satisfy."""

    @pytest.fixture
    def policy(self) -> MemoryPolicy:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, policy: MemoryPolicy) -> None:
        assert isinstance(policy, MemoryPolicy)

    @pytest.mark.parametrize("case", _TOTALITY_CASES, ids=str)
    async def test_decide_rules_on_every_proposal(self, policy: MemoryPolicy, case: _Case) -> None:
        # A policy is total over well-formed input: every proposal gets a ruling,
        # so the write path can never stall on an unhandled combination. The
        # sweep spans every axis a caller can vary — record variant, source,
        # confidence, tier, and whether anything conflicts.
        conflicts = [_record("existing", record_kind=case.record_kind)] if case.conflicts else []
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

        decision = await policy.decide(proposal, conflicts=conflicts)

        assert isinstance(decision, MemoryDecision)

    @pytest.mark.parametrize("with_conflicts", [False, True])
    async def test_decision_carries_a_reason(
        self, policy: MemoryPolicy, *, with_conflicts: bool
    ) -> None:
        # Every ruling is explainable: `reason` exists for transparency, and a
        # blank one satisfies the type while defeating the purpose.
        conflicts = [_record("existing")] if with_conflicts else []

        decision = await policy.decide(_proposal(conflicts=conflicts), conflicts=conflicts)

        assert decision.reason.strip()

    async def test_merge_targets_one_of_the_supplied_conflicts(self, policy: MemoryPolicy) -> None:
        # `merge_into` is a free-form id the validator cannot check. Merging into
        # a record the caller never offered would target something the caller has
        # not resolved — or nothing at all.
        conflicts = [_record("first"), _record("second")]

        decision = await policy.decide(_proposal(conflicts=conflicts), conflicts=conflicts)

        if decision.kind is MemoryDecisionKind.MERGE:
            assert decision.merge_into in {c.id for c in conflicts}

    async def test_does_not_merge_when_there_is_no_conflict(self, policy: MemoryPolicy) -> None:
        # The degenerate case of the rule above: with nothing to merge into,
        # MERGE cannot name a valid target.
        decision = await policy.decide(_proposal(), conflicts=[])

        assert decision.kind is not MemoryDecisionKind.MERGE

    @pytest.mark.parametrize("source", list(MemorySource))
    @pytest.mark.parametrize("with_conflicts", [False, True])
    async def test_secret_tier_is_never_committed(
        self, policy: MemoryPolicy, source: MemorySource, *, with_conflicts: bool
    ) -> None:
        # ADR-0004 §3: Tier 0 data belongs in the OS keyring, never the memory
        # store. No policy may route a secret-tier proposal into storage,
        # whatever its other rules and however trusted the source — and a policy
        # that defers only when there is nothing to merge into would still leak
        # the secret down its merge path, so both cases are swept.
        conflicts = [_record("existing")] if with_conflicts else []
        proposal = _proposal(
            _record("secret", source=source), sensitivity=DataTier.SECRET, conflicts=conflicts
        )

        decision = await policy.decide(proposal, conflicts=conflicts)

        assert decision.kind not in _COMMITTING

    @pytest.mark.parametrize("record_kind", _RECORD_KINDS)
    @pytest.mark.parametrize("with_conflicts", [False, True])
    async def test_decide_is_deterministic(
        self, policy: MemoryPolicy, record_kind: str, *, with_conflicts: bool
    ) -> None:
        # The Protocol docstring makes determinism the point of the "dispose"
        # half: the same proposal must not be accepted once and deferred the
        # next time, or the write path stops being reviewable. Both branches are
        # swept: the conflict-free path is a different branch in every policy
        # written so far, and equally bound by this.
        conflicts = [_record("existing", record_kind=record_kind)] if with_conflicts else []
        proposal = _proposal(_record("new", record_kind=record_kind), conflicts=conflicts)

        first = await policy.decide(proposal, conflicts=conflicts)
        second = await policy.decide(proposal, conflicts=conflicts)

        # The whole decision, not just its kind: an alternating ttl changes when
        # the record expires while leaving the kind identical.
        assert first == second

    @pytest.mark.parametrize("record_kind", _RECORD_KINDS)
    async def test_decide_does_not_mutate_its_inputs(
        self, policy: MemoryPolicy, record_kind: str
    ) -> None:
        # A policy rules on a proposal; it does not edit it. The caller still
        # owns both arguments after the call.
        conflicts = [_record("existing", record_kind=record_kind)]
        proposal = _proposal(_record("new", record_kind=record_kind), conflicts=conflicts)
        proposal_before = proposal.model_copy(deep=True)
        conflicts_before = [c.model_copy(deep=True) for c in conflicts]

        await policy.decide(proposal, conflicts=conflicts)

        assert proposal == proposal_before
        assert conflicts == conflicts_before

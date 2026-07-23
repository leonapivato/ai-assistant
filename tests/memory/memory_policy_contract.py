"""Shared conformance suite for the MemoryPolicy Protocol.

Every ``MemoryPolicy`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryPolicyContract` and overrides the ``policy`` fixture.

The suite asserts only what is universal to the contract — that ``decide`` is
total, deterministic, returns an internally coherent decision, and never commits
secret-tier data. It deliberately does **not** encode *which*
ruling a given proposal earns: that is each policy's reasoning, and even the
default's changes — ADR-0038 rewrote what it returns for a user-asserted
proposal that meets a conflict, without touching a line here, which is the
separation working. ``DefaultMemoryPolicy``'s specific rules are tested in
``test_policy.py``.

Every obligation here traces to something already ratified — determinism to the
``MemoryPolicy`` docstring, the secret-tier rule to ADR-0004 §3, the coherence of
``target_id`` to what ``decide`` says its ``conflicts`` argument is. A
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

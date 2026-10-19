"""Shared conformance suite for the MemoryPolicy Protocol.

Every ``MemoryPolicy`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryPolicyContract` and overrides the ``policy`` fixture.

The suite asserts only what is universal to the contract — that ``decide`` is
total, deterministic, returns an internally coherent decision, never commits
secret-tier data, never stores a proposal tentatively (``STORE_TEMPORARY``, ADR-0328
§10:3), and never commits an unconfirmed memory at inference that rests on outside
content (ADR-0106 §6, read through ADR-0328 §12). It deliberately does **not** encode *which*
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
``SUPERSEDE`` carry a ``target_id``, and the shape of a ``STORE_TEMPORARY`` no policy
rules. Asserting them here would test pydantic. What the validator
*cannot* know — that ``target_id`` names one of the records actually supplied —
is asserted below.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from typing import TYPE_CHECKING, Literal

import pytest
from pydantic import ValidationError

from ai_assistant.core.protocols import MemoryPolicy
from ai_assistant.core.types import (
    DataTier,
    EpisodicMemory,
    Memory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryStanding,
    MemoryUpdateProposal,
    Provenance,
    QuestionPart,
    SupportOrigin,
    UserConfirmation,
    origin_is_outside,
    origin_standing,
)
from ai_assistant.testing.memories import memory, remembered_support, support_with_origin

if TYPE_CHECKING:
    from collections.abc import Sequence

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

# Decisions that result in the proposal reaching long-term storage. ASK_USER and
# REJECT do not: one defers to a human, the other drops the proposal.
# ``STORE_TEMPORARY`` is here because a ruling of it would ask for a write: no
# policy rules it (ADR-0328 §10:3), which the suite asserts on every case.
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

#: Every origin a memory's one support can take: the proposal axis. A policy is
#: handed whatever a writer can build, and a suite sweeping one origin would certify
#: a policy that crashes on the others.
_ORIGINS = tuple(SupportOrigin)

#: The origins ADR-0106 §6's ceiling is keyed on, read through ADR-0328 §12: a memory
#: at inference (the ``DERIVED`` band) whose support is outside content. Derived from
#: the origin table rather than spelled, so an origin added later is covered.
_TAINTED_ORIGINS = tuple(
    origin
    for origin in SupportOrigin
    if origin_standing(origin) is MemoryStanding.INFERENCE and origin_is_outside(origin)
)

#: Pairs of origins ranking at one standing above inference, one outside and one not:
#: the outside mark decides nothing there (ADR-0106 §2, ADR-0328 §7:6).
_MARKED_PAIRS = (
    (SupportOrigin.ASSISTANT_MESSAGE, SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE),
    (SupportOrigin.EVIDENCE, SupportOrigin.EVIDENCE),
    (SupportOrigin.USER_MESSAGE, SupportOrigin.USER_MESSAGE),
)


def _record(record_id: str, origin: SupportOrigin = SupportOrigin.REMEMBERED) -> Memory:
    """A memory stating ``record_id`` on one support taking ``origin``."""
    return memory(record_id, record_id, support_with_origin(origin))


def _conflict(record_id: str, origin: SupportOrigin | None) -> MemoryRecord:
    """A conflicting record: a memory resting on ``origin``, or an episode for ``None``.

    An episode is a record the store holds beside memories, so a policy handed
    conflicts must cope with one among them.
    """
    if origin is None:
        return EpisodicMemory(
            id=record_id,
            content=record_id,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_WHEN),
            occurred_at=_WHEN,
        )
    return _record(record_id, origin)


@dataclass(frozen=True)
class _Case:
    """One point in the input space ``decide`` must handle."""

    origin: SupportOrigin
    sensitivity: DataTier
    conflict: SupportOrigin | Literal[False] | None
    """The origin of the conflicting memory, ``None`` for an episode, ``False`` for none."""

    def __str__(self) -> str:
        if self.conflict is False:
            conflict = "clean"
        elif self.conflict is None:
            conflict = "vs-episode"
        else:
            conflict = f"vs-{self.conflict}"
        return f"{self.origin}-{self.sensitivity}-{conflict}"


# The full cross-product of everything a caller can vary. The conflict axis carries
# an *origin*, not just a yes/no: a policy branching on whether the record it would
# overwrite stands in the user's own band is not hypothetical — `DefaultMemoryPolicy`
# does exactly that — so a matrix whose conflicts are always inferences would leave
# that branch uncertified.
_TOTALITY_CASES = [
    _Case(origin, sensitivity, conflict)
    for origin, sensitivity, conflict in product(_ORIGINS, DataTier, [False, None, *SupportOrigin])
]


def _proposal(
    record: Memory | None = None,
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
    # agree would be failed by this suite for being right.
    return MemoryUpdateProposal(
        proposed=proposal.proposed,
        rationale=proposal.rationale,
        sensitivity=proposal.sensitivity,
        conflicts=proposal.conflicts,
        confirmation=UserConfirmation(
            question=QuestionPart(round="deferral-1", part=1),
            question_key=proposal.question_key,
            confirmed_at=_WHEN,
            retires=tuple(c.id for c in conflicts),
        ),
    )


def _inputs_for(case: _Case) -> tuple[MemoryUpdateProposal, list[MemoryRecord]]:
    """Build the ``(proposal, conflicts)`` pair one matrix case describes."""
    conflicts = [] if case.conflict is False else [_conflict("existing", case.conflict)]
    proposal = _proposal(
        _record("new", case.origin), sensitivity=case.sensitivity, conflicts=conflicts
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
        # ADR-0328 §10:3: no policy stores a proposal tentatively.
        assert decision.kind is not MemoryDecisionKind.STORE_TEMPORARY

    @pytest.mark.parametrize("origin", _TAINTED_ORIGINS, ids=str)
    async def test_an_unconfirmed_tainted_derived_proposal_is_never_committed(
        self, policy: MemoryPolicy, origin: SupportOrigin
    ) -> None:
        """ADR-0106 §6's ceiling, read through ADR-0328 §12 and §13:4.

        A memory at inference that rests on outside content is never auto-accepted
        into durable memory — whatever the policy's other rules, and however trusted
        the producer (ADR-0098 §4's fourth clause). ``ASK_USER`` and ``REJECT`` both
        conform; the suite pins neither, because a deployment somewhere a user cannot
        be asked conforms by refusing.

        Asserted on the retry as well as the first call, for the reason the
        secret-tier obligation is: a policy that defers once and commits on the
        second attempt satisfies a one-call check while committing exactly what
        the ceiling forbids.
        """
        record = _record("tainted", origin)
        assert record.rests_on_outside_content

        decision = await policy.decide(_proposal(record), conflicts=[])
        again = await policy.decide(_proposal(record), conflicts=[])

        assert decision.kind not in _COMMITTING
        assert again.kind not in _COMMITTING

    async def test_a_memory_with_one_outside_support_among_others_is_tainted(
        self, policy: MemoryPolicy
    ) -> None:
        """ADR-0328 §7:6: one outside support, counted or not, makes it rest on outside content.

        A memory at inference with a plain remember call beside one over outside
        content rests on outside content as a whole, so the ceiling holds for it too.
        """
        record = memory(
            "mixed",
            "mixed",
            remembered_support(),
            remembered_support(effect="effect-2", outside=True),
        )
        assert record.rests_on_outside_content

        decision = await policy.decide(_proposal(record), conflicts=[])

        assert decision.kind not in _COMMITTING

    @pytest.mark.parametrize("origin", _TAINTED_ORIGINS, ids=str)
    async def test_the_ceiling_does_not_reach_the_confirmed_re_ingest(
        self, policy: MemoryPolicy, origin: SupportOrigin
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
        record = _record("tainted", origin)
        conflicts: list[MemoryRecord] = [_record("existing")]
        proposal = _proposal(record, conflicts=conflicts, confirmed=True)

        decision = await policy.decide(proposal, conflicts=conflicts)
        again = await policy.decide(proposal, conflicts=conflicts)

        assert isinstance(decision, MemoryDecision)
        assert decision == again
        assert decision.kind is not MemoryDecisionKind.STORE_TEMPORARY
        if decision.kind in _TARGET_CARRYING:
            assert decision.target_id in {c.id for c in conflicts}

    @pytest.mark.parametrize(("plain", "marked"), _MARKED_PAIRS, ids=str)
    async def test_the_marker_decides_nothing_outside_the_derived_band(
        self, policy: MemoryPolicy, plain: SupportOrigin, marked: SupportOrigin
    ) -> None:
        """ADR-0106 §2, read through ADR-0328 §7:6: outside content binds only at inference.

        A memory in the ``ASSERTED`` band never rests on outside content, however
        many outside supports it carries beside the user's word; one in the
        ``ATTESTED`` band rests on it by its nature. A policy reading the raw
        outside origins rather than the band would defer a user's own assertion, or
        every source's report, on the strength of a mark that decides nothing there.

        Stated as an **invariance** rather than as "still commits": the suite runs
        against a ``FakeMemoryPolicy`` configured to every ruling, ``REJECT``
        included, so an assertion that these proposals commit would fail a double
        that conforms.
        """
        with_marker = memory(
            "marked",
            "marked",
            support_with_origin(marked),
            remembered_support(effect="effect-2", outside=True),
        )
        # The same parts and the same count, only the outside origins differ: a policy
        # may weigh corroboration, and this asks about the marker alone.
        without_marker = memory(
            "marked",
            "marked",
            support_with_origin(plain),
            remembered_support(effect="effect-2", outside=False),
        )

        ruled_with = await policy.decide(_proposal(with_marker), conflicts=[])
        ruled_without = await policy.decide(_proposal(without_marker), conflicts=[])

        assert ruled_with.kind is ruled_without.kind

    async def test_fold_targets_one_of_the_supplied_conflicts(self, policy: MemoryPolicy) -> None:
        # The sweep above only ever supplies one conflict. This is the case it
        # cannot cover: with several to choose from, `target_id` must still name
        # one the caller actually offered, not an id of the policy's own making.
        conflicts: list[MemoryRecord] = [_record("first"), _record("second")]

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
        conflicts: list[MemoryRecord] = [_record("existing")]
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

"""Tests for the default memory policy.

The universal ``MemoryPolicy`` obligations live in ``memory_policy_contract.py``
and are run against this policy by :class:`TestDefaultMemoryPolicyContract`. What
remains here is what makes *this* policy the default one: its specific rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from memory_policy_contract import MemoryPolicyContract
from pydantic import ValidationError

from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    DataTier,
    EpisodicMemory,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
    UserConfirmation,
    band_of,
)
from ai_assistant.memory import DefaultMemoryPolicy

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryPolicy

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The episode a well-formed derived proposal cites. Since ADR-0077 §5 this policy
#: rejects a ``DERIVED`` proposal citing **nothing**, so a case exercising any
#: *other* rule has to cite something — otherwise it would be measuring the new
#: rule instead. The cases that mean to measure it pass ``evidence=()``.
_EPISODE = "episode-1"

#: What an `EXTERNAL` record is obliged to carry since ADR-0092 §1 — an attestation
#: naming what reported it and when that source said so. Attached by `_semantic`
#: from the band rather than passed per case: none of the rules under test turns on
#: its *contents*, so making every `EXTERNAL` site spell it out would be noise
#: standing in front of the rule each case is actually about.
_ATTESTED_BY = Attestation(reported_by="calendar:work", reported_at=_WHEN)


def _attestation_for(source: MemorySource) -> Attestation | None:
    """The attestation ``source``'s band obliges, read from :func:`band_of`.

    Keyed on the band rather than on ``source is EXTERNAL``, so a `MemorySource`
    added into the `ATTESTED` band later needs no edit here.
    """
    return _ATTESTED_BY if band_of(source) is BeliefBand.ATTESTED else None


def _semantic(
    record_id: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    confidence: float = 0.6,
    evidence: tuple[str, ...] = (_EPISODE,),
) -> MemoryRecord:
    return SemanticMemory(
        id=record_id,
        content=record_id,
        fact=record_id,
        provenance=Provenance(
            source=source,
            confidence=confidence,
            last_updated=_WHEN,
            evidence=evidence,
            attestation=_attestation_for(source),
        ),
    )


def _episodic(record_id: str, *, evidence: tuple[str, ...] = ()) -> MemoryRecord:
    """An episode: a record that something happened, whose warrant is that it did."""
    return EpisodicMemory(
        id=record_id,
        content=record_id,
        occurred_at=_WHEN,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN, evidence=evidence
        ),
    )


def _proposal(
    record: MemoryRecord,
    *,
    sensitivity: DataTier = DataTier.PERSONAL,
) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=sensitivity)


class TestDefaultMemoryPolicyContract(MemoryPolicyContract):
    """Runs DefaultMemoryPolicy through the shared MemoryPolicy conformance suite."""

    @pytest.fixture
    def policy(self) -> MemoryPolicy:
        return DefaultMemoryPolicy()


async def test_secret_tier_defers_to_user() -> None:
    proposal = _proposal(_semantic("s"), sensitivity=DataTier.SECRET)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ASK_USER


# --- Rule 2: a derived belief must cite something (ADR-0077 §5, ADR-0072 §3) ---


@pytest.mark.parametrize("source", [MemorySource.OBSERVED, MemorySource.INFERRED], ids=str)
async def test_a_derived_proposal_citing_no_evidence_is_rejected(source: MemorySource) -> None:
    # The gate's half of the evidence discipline, at the enforcement point
    # ADR-0072 §3 named: a belief we worked out *from evidence*, carrying none,
    # cannot answer "why do you believe that?" at all. Band-wide and minimal,
    # because the gate serves every producer and cannot know which epistemic step
    # a record took. Without it, ADR-0077's "every proposal cites" would hold only
    # for the producer that happens to obey it.
    proposal = _proposal(_semantic("unsupported", source=source, confidence=0.9, evidence=()))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.REJECT
    assert decision.reason.strip()


async def test_a_derived_proposal_citing_no_evidence_is_rejected_even_with_conflicts() -> None:
    # Rule 2 precedes the conflict rules: an inadmissible proposal is not worth
    # deferring to the user about, and it must not be folded into a live record
    # either. A rule placed after rule 3 would rule ASK_USER here, and one placed
    # after rule 7 would REINFORCE an unsupported belief onto a real one.
    proposal = _proposal(_semantic("unsupported", confidence=0.9, evidence=()))
    conflicts = [
        _semantic("their-words", source=MemorySource.USER_ASSERTED, confidence=1.0),
        _semantic("our-guess", source=MemorySource.INFERRED),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.REJECT


async def test_an_episodic_record_is_not_rejected_for_citing_nothing() -> None:
    # ADR-0074 §4 binds this policy: an episode's warrant is that it happened, and
    # requiring it to cite something would demand a regress. The exemption guards a
    # path nothing takes today — capture does not reach the gate (ADR-0075 §1) and
    # ADR-0077 §2 forbids the observer to propose an episode — and is written
    # anyway, so the rule is not one refactor away from making its own substrate
    # unwritable.
    proposal = _proposal(_episodic("what-happened"))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


@pytest.mark.parametrize("source", [MemorySource.USER_ASSERTED, MemorySource.EXTERNAL], ids=str)
async def test_an_asserted_or_external_proposal_citing_nothing_is_untouched(
    source: MemorySource,
) -> None:
    # The rule is scoped to the band ADR-0072 §3 obliges to cite. The user's own
    # word is its own warrant and an integration's report is that system's, so
    # neither is constrained — which is exactly why ADR-0072 §3 put the rule at the
    # policy gate rather than on the type.
    proposal = _proposal(_semantic("stated", source=source, confidence=1.0, evidence=()))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_inference_conflicting_with_asserted_defers_to_user() -> None:
    proposal = _proposal(_semantic("new", source=MemorySource.INFERRED, confidence=0.9))
    asserted = _semantic("old", source=MemorySource.USER_ASSERTED, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[asserted])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_user_asserted_is_accepted() -> None:
    proposal = _proposal(_semantic("a", source=MemorySource.USER_ASSERTED, confidence=1.0))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_user_assertion_supersedes_a_conflicting_inference() -> None:
    # ADR-0038: the correction must displace the stale belief, not land beside
    # it. Before this rule the ACCEPT above fired first and both stayed live.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    stale = _semantic("stale", source=MemorySource.INFERRED, confidence=0.6)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[stale])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "stale"


async def test_user_assertion_contradicting_an_assertion_defers_even_with_an_inference() -> None:
    # ADR-0050 §2 (#245): when the conflict set contains a prior *assertion*, the
    # proposal is contradicting something the user themselves said. Superseding the
    # inference alongside it (the old ADR-0038 §3 behaviour) would still commit the
    # new assertion beside "their-words", leaving two live contradictory profile
    # records. The assertion-conflict check wins over the inference, so the policy
    # defers the whole thing to the user rather than half-resolving it.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    conflicts = [
        _semantic("their-words", source=MemorySource.USER_ASSERTED, confidence=1.0),
        _semantic("our-guess", source=MemorySource.OBSERVED, confidence=0.6),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_user_assertion_supersedes_an_external_record() -> None:
    # ADR-0092 §4, reversing ADR-0038 §2a's policy-side exclusion: the external
    # calendar is an *input*, not the truth, so the user's correction retires the
    # import rather than landing live beside it. §2a's mechanical reason is gone —
    # ADR-0045 §4 makes a SUPERSEDE mint a fresh id rather than inherit the
    # external one — and ADR-0038 §2's error calculus puts the band on the
    # recoverable side, since an attested belief is re-reportable by its source on
    # a schedule. What ADR-0092 §4 did *not* touch is the REINFORCE refusal, which
    # still inherits the id; the ingest-level case pins that.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    imported = _semantic("imported", source=MemorySource.EXTERNAL, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[imported])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "imported"


@pytest.mark.parametrize("source", list(MemorySource), ids=str)
async def test_an_assertion_never_lands_beside_a_conflict_any_more(
    source: MemorySource,
) -> None:
    # Arm 3's reachability, stated over the whole enum. Before ADR-0092 §4 an
    # assertion contradicting only an EXTERNAL record was ACCEPTed *beside* it and
    # both stayed live — the "stale belief stays live" shape of #38, surviving for
    # one source. With EXTERNAL in the retirement class there is no longer any
    # non-empty conflict set an assertion is merely accepted alongside: every
    # source either gets retired (the class) or gets deferred to the user
    # (USER_ASSERTED, ADR-0050 §2). Parametrised so a `MemorySource` added later
    # cannot restore the shape by being left out of the class.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    confidence = 1.0 if source is MemorySource.USER_ASSERTED else 0.6
    conflict = _semantic("prior", source=source, confidence=confidence)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[conflict])

    assert decision.kind is not MemoryDecisionKind.ACCEPT
    assert decision.kind in {MemoryDecisionKind.SUPERSEDE, MemoryDecisionKind.ASK_USER}


async def test_user_assertion_takes_the_best_ranked_retirable_conflict() -> None:
    # The scan reaches past a USER_ASSERTED conflict rather than abandoning
    # supersession — which is what it was always for; before ADR-0092 §4 it also
    # had an EXTERNAL hold-out to step over, and now it does not. An imported
    # record ranked first is simply the target.
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    conflicts = [
        _semantic("imported", source=MemorySource.EXTERNAL, confidence=1.0),
        _semantic("our-guess", source=MemorySource.INFERRED, confidence=0.6),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "imported"


async def test_external_proposal_conflicting_with_an_assertion_defers() -> None:
    # Rule 2, restated for EXTERNAL specifically: a sync is a non-asserted
    # proposal, so it may not silently overwrite what the user told us.
    proposal = _proposal(_semantic("sync", source=MemorySource.EXTERNAL, confidence=1.0))
    corrected = _semantic("corrected", source=MemorySource.USER_ASSERTED, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[corrected])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_user_assertion_contradicting_only_an_assertion_defers_to_the_user() -> None:
    # ADR-0050 §2 (#245): two things the user said, both at confidence 1.0. Nothing
    # ranks them and topical similarity is not a contradiction signal, so neither may
    # be destroyed (ADR-0045 §5 / clause 1); but leaving both live is the honesty gap
    # #245 reports. The policy defers to the user — the acceptable gate ADR-0045 §7
    # named — superseding ADR-0038 §5's "accept beside".
    proposal = _proposal(_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0))
    earlier = _semantic("earlier", source=MemorySource.USER_ASSERTED, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_secret_tier_assertion_still_defers_before_superseding() -> None:
    # Rule 1 outranks supersession: a secret-tier correction must not silently
    # overwrite a record on its way to being confirmed.
    proposal = _proposal(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
        sensitivity=DataTier.SECRET,
    )
    stale = _semantic("stale", source=MemorySource.INFERRED, confidence=0.6)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[stale])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_conflict_with_non_asserted_merges() -> None:
    proposal = _proposal(_semantic("new"))
    existing = _semantic("existing")

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[existing])

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "existing"


async def test_low_confidence_is_stored_temporarily() -> None:
    proposal = _proposal(_semantic("weak", confidence=0.1))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.STORE_TEMPORARY
    assert decision.ttl is not None


async def test_confident_and_unconflicted_is_accepted() -> None:
    proposal = _proposal(_semantic("ok", confidence=0.9))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_non_positive_temporary_ttl_is_rejected_at_construction(ttl: timedelta) -> None:
    # Without this guard the policy builds fine and raises later from `decide`,
    # and only for a low-confidence proposal — a crash far from its cause. Both
    # zero and negative are checked: a guard narrowed to `== 0` would let a
    # negative window through and restore exactly that delayed failure.
    with pytest.raises(ValueError, match="temporary_ttl must be positive"):
        DefaultMemoryPolicy(temporary_ttl=ttl)


# `test_decide_does_not_mutate_its_inputs` moved to the shared `MemoryPolicyContract`
# (ADR-0068 §5): freezing makes input-immutability an obligation every conforming
# producer satisfies, so it belongs in the suite, held against every implementation.


async def test_decision_carries_a_non_blank_reason() -> None:
    # Also not in the shared suite (TODO item 7): `reason=""` passes the model,
    # so requiring otherwise would be the suite inventing an obligation. This
    # implementation does explain itself, and that is worth pinning here.
    decision = await DefaultMemoryPolicy().decide(_proposal(_semantic("new")), conflicts=[])

    assert decision.reason.strip()


# --------------------------------------------------------------------------- #
# Rule 3: the confirmation gate (ADR-0078 §5a)                                #
# --------------------------------------------------------------------------- #


def _confirmed(
    record: MemoryRecord,
    *,
    retires: tuple[str, ...],
    frozen: tuple[str, ...] | None = None,
) -> MemoryUpdateProposal:
    """A proposal carrying the authority a claimed answer mints (ADR-0078 §5).

    Built the way the coordinator builds it: the ``conflicts`` the proposal arrives
    with are the ids the question froze, and the key is that proposal's own. The
    *policy* verifies none of that — the writer's floor does (ADR-0078 §5b) — so what
    matters here is only that a confirmation is present and what it names.
    """
    proposal = MemoryUpdateProposal(
        proposed=record,
        rationale="because",
        conflicts=retires if frozen is None else frozen,
    )
    return proposal.model_copy(
        update={
            "confirmation": UserConfirmation(
                deferral_id="q-1",
                question_key=proposal.question_key,
                confirmed_at=_WHEN,
                retires=retires,
            )
        }
    )


async def test_a_confirmed_proposal_supersedes_the_assertion_the_answer_named() -> None:
    """Step 2, and the whole point of the gate (ADR-0078 §5a).

    The rule that would otherwise re-defer the answer to the question it just asked,
    forever. It comes ahead of the conflict rules for exactly that reason, and step 1
    is what keeps that precedence from becoming a blanket override.
    """
    prior = _semantic("prior", source=MemorySource.USER_ASSERTED, confidence=1.0)
    proposal = _confirmed(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
        retires=("prior",),
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[prior])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "prior"


async def test_a_confirmed_proposal_re_defers_on_an_assertion_it_was_never_shown() -> None:
    """Step 1: an assertion outside the answer's authority blocks the apply.

    Superseding the covered assertion while committing beside the uncovered one is the
    #245 gap reached by a new path, and extending the user's answer to a record they
    did not see would forge consent. So the answer becomes a **re-deferral**, and
    nothing is retired on the way out (ADR-0079 §2: only a ``SUPERSEDE`` retires).
    """
    shown = _semantic("prior", source=MemorySource.USER_ASSERTED, confidence=1.0)
    unshown = _semantic("surprise", source=MemorySource.USER_ASSERTED, confidence=1.0)
    proposal = _confirmed(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
        retires=("prior",),
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[shown, unshown])

    assert decision.kind is MemoryDecisionKind.ASK_USER
    assert decision.target_id is None


async def test_a_confirmed_proposal_targets_the_assertion_and_not_an_external_record() -> None:
    """Step 2's qualifier, load-bearing in two directions (ADR-0078 §5a).

    Without "whose source is ``USER_ASSERTED``", a set holding an ``EXTERNAL`` record
    and an assertion — both named in ``retires``, the external one first — could name
    the external record as the audited primary while the assertion the user actually
    confirmed retiring rode in on the applier's widening: the *incidental* record in
    the ruling's ``target_id``, and the confirmed one nowhere the audit trail names.

    Since ADR-0092 §4 adopted ``EXTERNAL`` supersession that is a mis-attribution
    rather than an unratified adoption, but the qualifier stays for the reason it
    was written: a confirmation's authority is to retire an **assertion**, and the
    ruling should say that is what it did. An ``EXTERNAL`` id in ``retires`` is
    still not acted on here — ``retires`` is a ceiling, not an instruction — and it
    no longer needs to be, because the applier's widening now sweeps it anyway.
    """
    external = _semantic("ext", source=MemorySource.EXTERNAL)
    prior = _semantic("prior", source=MemorySource.USER_ASSERTED, confidence=1.0)
    proposal = _confirmed(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
        retires=("ext", "prior"),
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[external, prior])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "prior", "an EXTERNAL id in `retires` is not acted on"


async def test_a_confirmed_proposal_falls_through_and_still_retires_a_stale_inference() -> None:
    """Step 3 **falls through** rather than accepting (ADR-0078 §5a).

    The wrong reading — "otherwise ``ACCEPT``" — quietly disables the ordinary
    supersession law for every confirmed proposal: freeze a question over an assertion
    and an inference, let the assertion be retired or deleted before the answer
    arrives, and a bare ``ACCEPT`` lands the correction **beside** the stale inference
    the user just corrected. The confirmed path exists to override the arms that would
    re-defer an answered question; it has no business overriding the arms ADR-0038
    entitles an assertion to overturn without asking.
    """
    inference = _semantic("stale", source=MemorySource.INFERRED)
    proposal = _confirmed(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
        retires=("gone",),
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[inference])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "stale"


async def test_a_confirmed_proposal_with_nothing_live_to_retire_is_accepted() -> None:
    """Step 3's other fall-through arm: nothing supersedable, so the assertion lands.

    ``retires`` may legitimately be empty — every conflict the user was shown has since
    gone — and the answer then authorises a write and no retirement. That case must not
    read as "no confirmation" under a truthiness check, which would re-defer an
    answered question forever.
    """
    proposal = _confirmed(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0), retires=()
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_the_secret_gate_still_precedes_the_confirmed_rule() -> None:
    """The confirmed rule sits **behind** the admissibility floor (ADR-0078 §5a).

    Putting it first let a ``DataTier.SECRET`` proposal carrying a confirmation reach
    step 2, rule ``SUPERSEDE``, pass the writer exception, and land secret payload in
    the ``MemoryStore`` — ADR-0004 §3's "never in the memory database", defeated
    through the one path built to respect the user's word.

    The pairing is unconstructable through the model (asserted below), so this drives
    it past the validator: a floor that holds only while a coincidence holds is not a
    floor, and ADR-0078 wants the ordering stated rather than left to that argument.
    """
    prior = _semantic("prior", source=MemorySource.USER_ASSERTED, confidence=1.0)
    honest = _confirmed(
        _semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0), retires=("prior",)
    )
    bypassed = MemoryUpdateProposal.model_construct(
        proposed=honest.proposed,
        rationale=honest.rationale,
        sensitivity=DataTier.SECRET,
        conflicts=honest.conflicts,
        confirmation=honest.confirmation,
    )

    decision = await DefaultMemoryPolicy().decide(bypassed, conflicts=[prior])

    assert decision.kind is MemoryDecisionKind.ASK_USER
    assert "secret-tier" in decision.reason


async def test_a_secret_tier_proposal_cannot_carry_a_confirmation_at_all() -> None:
    """The other half of the belt and braces (ADR-0078 §1, §5a).

    §1 refuses to queue a secret-tier proposal, so no deferral exists for one, so no
    confirmation can have been issued for one. That makes the combination a
    *contradiction* rather than a case — and the model says so, which is what keeps the
    policy ordering and the writer floor as belt and braces over something already
    unconstructable.
    """
    # Constructed directly rather than through `_confirmed`, which reaches the field
    # with `model_copy(update=...)` — and that skips validators, which is exactly why
    # ADR-0078 §5b's check 0 exists at the writer boundary as well.
    with pytest.raises(ValidationError, match="cannot carry a confirmation"):
        MemoryUpdateProposal(
            proposed=_semantic("new", source=MemorySource.USER_ASSERTED, confidence=1.0),
            rationale="because",
            sensitivity=DataTier.SECRET,
            confirmation=UserConfirmation(
                deferral_id="q-1",
                question_key="0" * 64,
                confirmed_at=_WHEN,
                retires=("prior",),
            ),
        )


async def test_a_confirmed_derived_proposal_citing_nothing_is_still_rejected() -> None:
    """The floor's *other* ruling is not skippable either (ADR-0078 §5a).

    Both of the floor's rulings are properties of the proposal alone and neither
    commits anything, so nothing a confirmation says can make either safe to skip. This
    arm cannot arise on the honest path — a derived belief citing nothing is rejected at
    its first ingest, so it is never deferred and never confirmed — but the ordering is
    stated rather than left to that argument.
    """
    proposal = _confirmed(
        _semantic("new", source=MemorySource.INFERRED, evidence=()), retires=("prior",)
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.REJECT

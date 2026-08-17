"""Tests for the default memory policy.

The universal ``MemoryPolicy`` obligations live in ``memory_policy_contract.py``
and are run against this policy by :class:`TestDefaultMemoryPolicyContract`. What
remains here is what makes *this* policy the default one: its specific rules.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from memory_policy_contract import MemoryPolicyContract
from pydantic import ValidationError

from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    ConflictRelation,
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


def _semantic(  # noqa: PLR0913 — one keyword per record axis a case may vary
    record_id: str,
    *,
    content: str | None = None,
    source: MemorySource = MemorySource.OBSERVED,
    confidence: float = 0.6,
    evidence: tuple[str, ...] = (_EPISODE,),
    derived_from_external: bool = False,
) -> MemoryRecord:
    # Content defaults to the id, so a case not about ADR-0121's agreement predicate
    # gets records that cannot accidentally agree: two records agree only when their
    # `content` matches, and no two ids here do.
    content = record_id if content is None else content
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=source,
            confidence=confidence,
            last_updated=_WHEN,
            evidence=evidence,
            attestation=_attestation_for(source),
            derived_from_external=derived_from_external,
        ),
    )


def _episodic(
    record_id: str,
    *,
    content: str | None = None,
    source: MemorySource = MemorySource.OBSERVED,
    evidence: tuple[str, ...] = (),
) -> MemoryRecord:
    """An episode: a record that something happened, whose warrant is that it did."""
    return EpisodicMemory(
        id=record_id,
        content=record_id if content is None else content,
        occurred_at=_WHEN,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_WHEN,
            evidence=evidence,
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
    # either. A rule placed after rule 4 would rule ASK_USER here, and one placed
    # after rule 8 would REINFORCE an unsupported belief onto a real one.
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


# --- Rule 3: a tainted derived proposal defers (ADR-0106 §6, ADR-0098 §4) ------


@pytest.mark.parametrize("source", [MemorySource.OBSERVED, MemorySource.INFERRED], ids=str)
async def test_a_tainted_derived_proposal_defers_with_a_reason_naming_its_warrant(
    source: MemorySource,
) -> None:
    """The default takes the question, and says why it is asking (ADR-0106 §6).

    The contract ceiling admits ``ASK_USER`` or ``REJECT``; this policy picks the
    question, because a silent refusal on a scheduler's path destroys the belief,
    tells nobody, and leaves the user unable to keep a summary they would have
    wanted. #668's goal — which ADR-0106 inherits — is turning a successful
    injection into "a visible, source-attributed proposal — spam, not poison".

    The ``reason`` is asserted for content and not merely for being non-blank,
    which is the whole of ADR-0106 §6's legibility clause: a user shown an
    unexplained question about a plausible-sounding belief answers yes, and the
    gate will have converted a silent corruption into a solicited one. This
    obligation is the default's and is deliberately **not** in the shared suite —
    no test can distinguish a sentence that conveys externality from one that
    claims to, and ``MemoryPolicyContract`` records that a ``reason`` obligation
    was cut for want of a Protocol statement (#40).
    """
    proposal = _proposal(_semantic("consolidated", source=source, derived_from_external=True))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ASK_USER
    assert "external" in decision.reason.lower()


async def test_a_tainted_derived_proposal_defers_ahead_of_every_conflict_rule() -> None:
    # The rule is an *admissibility* rule — a property of the proposal alone,
    # committing nothing — so it sits in the floor rather than beside the conflict
    # reasoning. Placed after the conflict rules it would fold a tainted
    # consolidation straight onto a live belief, which is the write ADR-0098 §4
    # forbids happening without the user's answer.
    proposal = _proposal(_semantic("consolidated", derived_from_external=True))
    existing = _semantic("existing", source=MemorySource.OBSERVED)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[existing])

    assert decision.kind is MemoryDecisionKind.ASK_USER
    assert decision.target_id is None


async def test_a_secret_tainted_proposal_takes_the_secret_path() -> None:
    """Rule 1 outranks rule 3, and the two are not interchangeable.

    Both rule ``ASK_USER``, so the *kind* cannot tell them apart — which is why
    the ``reason`` is what this asserts. ADR-0078 §1 refuses to queue a secret
    proposal at all, so its question is reported and never persisted; a taint rule
    ordered first would produce a question the write stage *would* queue, putting
    Tier-0 content into a durable ``DeferralStore`` row. ADR-0004 §3's "never in
    the memory database" is defeated by the queue as surely as by the store.
    """
    proposal = _proposal(
        _semantic("consolidated", derived_from_external=True), sensitivity=DataTier.SECRET
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ASK_USER
    assert "secret" in decision.reason.lower()


async def test_a_tainted_derived_proposal_citing_nothing_is_rejected_not_queued() -> None:
    """Rule 2 outranks rule 3 (ADR-0106 §6, ADR-0078 §5a's ordering).

    A taint rule ordered first would return ``ASK_USER`` and put an unwarranted
    belief in front of the user as though answering it could make it admissible —
    ADR-0077 §5 rejects it whatever the user says. ADR-0078 §5a could observe that
    such a proposal "is rejected at its first ingest, so it is never deferred and
    never confirmed"; a consolidator's *first* ingest is exactly where a
    citation-less proposal arrives, so the case is live rather than unreachable,
    and "a floor that holds only while a coincidence holds is not a floor".
    """
    proposal = _proposal(_semantic("consolidated", evidence=(), derived_from_external=True))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.REJECT


async def test_a_confirmed_tainted_proposal_is_judged_on_the_ordinary_path() -> None:
    """The carve-out that makes the question a question (ADR-0078 §5, ADR-0106 §6).

    The confirmed answer is a *re-ingest*: the coordinator rebuilds the proposal
    with the user's authority and calls the writer again, marker and all. Without
    the carve-out this rule fires a second time and defers the answered question —
    "The user answers, and is asked again" (ADR-0078 §3) — and a tainted
    consolidation could never land at all, contradicting ADR-0106 §5 and its
    Consequences. Being reached by asking the user is not the *auto*-acceptance
    ADR-0098 §4 forbids.
    """
    proposal = _confirmed(_semantic("consolidated", derived_from_external=True), retires=())

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_an_attested_proposal_carrying_the_marker_still_commits() -> None:
    """ADR-0106 §10's first boundary, at the one place it is assertable.

    A calendar reader's proposal rests on recorded external content by definition,
    so a ceiling stated over
    ``rests_on_recorded_external_content`` would refuse every occurrence leg 6
    imports and make the reader useless (ADR-0106 §6). The marker is set here as
    well, because ADR-0106 §7 leaves the combination constructible and a rule
    reading the raw field across every band would fail on it.

    Pinned against *this* policy rather than in ``MemoryPolicyContract``: the
    shared suite runs ``FakeMemoryPolicy`` at every ``MemoryDecisionKind``,
    including ``REJECT``, so "must commit" would fail a double that conforms —
    and the suite's own rule is that it does not encode which ruling a proposal
    earns. What the suite asserts there instead is the *invariance*: the marker
    changes nothing outside the ``DERIVED`` band.
    """
    proposal = _proposal(
        _semantic(
            "import", source=MemorySource.EXTERNAL, confidence=0.9, derived_from_external=True
        )
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_a_user_assertion_carrying_a_stray_marker_is_not_deferred() -> None:
    """ADR-0106 §10's second boundary: it fails a rule that drops the band guard.

    ADR-0106 §7 forbids a band-keyed validator on the field, so this record
    constructs — and ADR-0106 §2 says the field means nothing in this band. A rule
    reading the raw flag would defer a user's own assertion on the strength of it,
    which ADR-0098 §1 forbids in principle: the user's own utterance is not
    external "however it was composed — a user who pastes an email into a turn is
    exercising judgement".
    """
    proposal = _proposal(
        _semantic(
            "their-words",
            source=MemorySource.USER_ASSERTED,
            confidence=1.0,
            derived_from_external=True,
        )
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[])

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_an_untainted_derived_proposal_is_untouched_by_the_rule() -> None:
    # The negative control: without it every case above passes a policy that
    # defers every derived proposal, which would stop the observer landing
    # anything at all.
    proposal = _proposal(_semantic("our-guess", source=MemorySource.INFERRED, confidence=0.9))

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
    # Rule 5, restated for EXTERNAL specifically: a sync is a non-asserted
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


# --- ADR-0159 §4: the non-asserted arm reads relations, never the set's size ---
#
# The rule these replace folded into ``conflicts[0]`` whenever the set was
# non-empty. The pilot (#1188, run `8a8f7a033b3c`) measured that on seven LoCoMo
# conversations: 765 proposals, 380 `ACCEPT`, **385 `REINFORCE`**, and the folds
# were routinely distinct facts sitting at cosine 0.77 to 0.80. The two contents in
# `_JON_LOST` / `_JON_TOOK` are that measurement's own pair, verbatim in substance,
# and the first test below is the shape it produces under this arm.

#: The 0.77 pair from #1188's error anatomy: two true, dated facts about one
#: person's employment, which the conflict probe surfaces together at 0.75 and which
#: the rule ADR-0159 replaced folded into one.
_JON_LOST = "Jon lost his job shortly before 21 June 2023"
_JON_TOOK = "Jon took a temporary job around mid-July 2023"


async def test_the_pilots_own_0_77_pair_lands_beside_what_it_resembles() -> None:
    """`ADDS` rules `ACCEPT` and names no target, so nothing is retired (ADR-0159 §4c).

    The case the whole ADR is about. Under the rule this replaces the proposal
    folded into `existing` at `existing`'s id and one of the two facts stopped
    existing. Under this arm a relation that is neither a restatement nor a
    contradiction authorises nothing, so the belief lands beside the one it
    resembles — and the `reason` says which of the two `ACCEPT` paths it took.
    """
    existing = _semantic("existing", content=_JON_LOST)
    proposal = _proposal(_semantic("new", content=_JON_TOOK))

    decision = await DefaultMemoryPolicy().decide(
        proposal, conflicts=[existing], relations={"existing": ConflictRelation.ADDS}
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT
    assert decision.target_id is None
    assert "none restates" in decision.reason


async def test_a_non_empty_conflict_set_alone_no_longer_folds_anything() -> None:
    """An unlabelled member authorises nothing (ADR-0159 §4).

    The inversion stated at its barest: the exact input that ruled `REINFORCE` at
    `conflicts[0]` before this ADR now rules `ACCEPT`, because nothing has said the
    two records say the same thing.
    """
    existing = _semantic("existing")

    decision = await DefaultMemoryPolicy().decide(_proposal(_semantic("new")), conflicts=[existing])

    assert decision.kind is MemoryDecisionKind.ACCEPT
    assert decision.target_id is None


async def test_the_two_accept_paths_are_legible_apart() -> None:
    """ADR-0159 §4's second clause: "no conflict" and "conflicts, none related" differ.

    Both rule `ACCEPT`, and only the `reason` records which store state produced it —
    a fact a later trace can report and the ruling alone cannot.
    """
    policy = DefaultMemoryPolicy()

    alone = await policy.decide(_proposal(_semantic("new")), conflicts=[])
    beside = await policy.decide(_proposal(_semantic("new")), conflicts=[_semantic("existing")])

    assert alone.kind is beside.kind is MemoryDecisionKind.ACCEPT
    assert alone.reason != beside.reason


async def test_a_restates_member_reinforces_and_names_it_by_relation_not_rank() -> None:
    """ADR-0159 §4a, and `conflicts[0]` is not the target (§4's third clause)."""
    first = _semantic("first")
    second = _semantic("second")
    proposal = _proposal(_semantic("new"))

    decision = await DefaultMemoryPolicy().decide(
        proposal,
        conflicts=[first, second],
        relations={"second": ConflictRelation.RESTATES, "first": ConflictRelation.ADDS},
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "second"


async def test_a_contradicts_member_supersedes_it() -> None:
    """ADR-0159 §4b: the observed path acquires a supersession for the first time."""
    existing = _semantic("existing", source=MemorySource.INFERRED)
    proposal = _proposal(_semantic("new"))

    decision = await DefaultMemoryPolicy().decide(
        proposal, conflicts=[existing], relations={"existing": ConflictRelation.CONTRADICTS}
    )

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "existing"


async def test_a_set_holding_both_a_restatement_and_a_contradiction_accepts() -> None:
    """Both purity conditions fail together, so neither exception fires (ADR-0159 §4).

    The set is one in which the *stored records disagree with each other*, and no
    ruling on this proposal resolves that: reinforcing one leaves the contradiction
    live, superseding the other leaves the reinforced record's own contradiction
    live. Deliberately not `ASK_USER` — an observation is not something the user
    should be interrogated about (#869).
    """
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new")),
        conflicts=[_semantic("agreeing"), _semantic("disagreeing")],
        relations={
            "agreeing": ConflictRelation.RESTATES,
            "disagreeing": ConflictRelation.CONTRADICTS,
        },
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


@pytest.mark.parametrize(
    ("relation", "blocked"),
    [
        (ConflictRelation.RESTATES, ConflictRelation.CONTRADICTS),
        (ConflictRelation.CONTRADICTS, ConflictRelation.RESTATES),
    ],
)
async def test_an_external_member_is_named_by_neither_arm_yet_still_blocks(
    relation: ConflictRelation, blocked: ConflictRelation
) -> None:
    """ADR-0159 §4: excluded from the target classes, and from nothing else.

    Two halves in one sweep. An `EXTERNAL` member carrying the relation an arm acts
    on is never that arm's `target_id` — a fold at an imported id is overwritten by
    the next sync, and a supersession is a claim an observation may not make against
    the system that reported the fact (ADR-0121 §3). And an `EXTERNAL` member
    carrying the *other* relation still fails the other arm's purity condition, so a
    policy that ignored `EXTERNAL` labels wholesale would reinforce here.
    """
    imported = _semantic("imported", source=MemorySource.EXTERNAL)
    other = _semantic("other")

    named = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new")), conflicts=[imported], relations={"imported": relation}
    )
    blocking = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new")),
        conflicts=[imported, other],
        relations={"imported": blocked, "other": relation},
    )

    assert named.kind is MemoryDecisionKind.ACCEPT
    assert blocking.kind is MemoryDecisionKind.ACCEPT


async def test_an_unlabelled_member_neither_authorises_nor_withdraws() -> None:
    """ADR-0159 §4: unlabelled blocks nothing, and this is the right sign.

    Letting it block would mean one reconciler failure downgrades a *certain*
    `agrees` restatement into a duplicate — a regression against ADR-0121 for no
    gain. Letting it pass means the fold happens while an unexamined member sits
    there, which is strictly better than the rule this replaces, where every member
    folded unexamined.
    """
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new")),
        conflicts=[_semantic("labelled"), _semantic("silent")],
        relations={"labelled": ConflictRelation.RESTATES},
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "labelled"


async def test_an_entry_naming_no_member_of_the_set_is_ignored() -> None:
    """ADR-0159 §8: a policy ignores a key that is not a conflict's id."""
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new")),
        conflicts=[_semantic("existing")],
        relations={"ghost": ConflictRelation.RESTATES},
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_no_relations_reproduces_adr_0121s_floor_exactly() -> None:
    """ADR-0159 §6, on the policy's own arm: `agrees` folds, everything else lands.

    The degraded case is a *decision* and not a fallback. With no reconciler the
    certain predicate is still computed here, so a verbatim restatement reinforces
    while a merely-similar record duplicates — where the rule this replaces folded
    both on similarity alone. Asserted with `relations=None`, which ADR-0159 §8 fixes
    as the value a writer holding no reconciler passes.
    """
    policy = DefaultMemoryPolicy()
    identical = _semantic("identical", content="I prefer window seats")
    similar = _semantic("similar", content="I prefer aisle seats")
    proposal = _proposal(_semantic("new", content="I  PREFER   Window Seats "))

    folded = await policy.decide(proposal, conflicts=[identical], relations=None)
    landed = await policy.decide(proposal, conflicts=[similar], relations=None)

    assert folded.kind is MemoryDecisionKind.REINFORCE
    assert folded.target_id == "identical"
    assert landed.kind is MemoryDecisionKind.ACCEPT


async def test_the_certain_rung_outranks_a_reconciler_that_disagrees_with_it() -> None:
    """ADR-0159 §3's first rung is unconditional, so a wrong label cannot overturn it.

    A reconciler "that reaches a different answer on a pair `agrees` admits is not
    conforming"; this policy recomputes the predicate rather than trusting the
    mapping, so a non-conforming label cannot turn a certain restatement into a
    retirement.
    """
    identical = _semantic("identical", content="I prefer window seats")
    proposal = _proposal(_semantic("new", content="I prefer window seats"))

    decision = await DefaultMemoryPolicy().decide(
        proposal, conflicts=[identical], relations={"identical": ConflictRelation.CONTRADICTS}
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "identical"


async def test_a_low_confidence_proposal_beside_an_unrelated_conflict_stores_temporarily() -> None:
    """ADR-0159 §4c is "the confidence arm exactly as it stands", now reachable here.

    Before this ADR a non-empty set never reached the confidence arm at all: it
    folded first. The arm is unchanged; what changed is that it is reached.
    """
    proposal = _proposal(_semantic("weak", confidence=0.1))

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[_semantic("existing")])

    assert decision.kind is MemoryDecisionKind.STORE_TEMPORARY
    assert decision.ttl is not None


async def test_an_asserted_conflict_still_defers_whatever_the_relations_say() -> None:
    """ADR-0159 §4's last clause: the `ASK_USER` arm precedes this one and is untouched."""
    asserted = _semantic("asserted", source=MemorySource.USER_ASSERTED, confidence=1.0, evidence=())

    decision = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new")),
        conflicts=[asserted],
        relations={"asserted": ConflictRelation.RESTATES},
    )

    assert decision.kind is MemoryDecisionKind.ASK_USER


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


# --- ADR-0121: an agreeing restatement is agreement, not conflict ------------
#
# The three shapes below are #862's live failure modes, pinned by the shapes the
# QA run actually observed rather than by the mechanism that produced them. Each
# ran three times out of three against a live hub, and each was structural: with
# `_rule_on_assertion`'s three arms and rule 9's reinforce sitting behind
# `not is_asserted`, `decisions_reinforce` at a direct seam was reachable at no
# input whatever (ADR-0120 §6's numerator, ADR-0121's Context).

#: The belief every case below restates. A preference the user states in so many
#: words, which is the population ADR-0121 §1's predicate is narrow enough to see.
_SEAT = "the user prefers window seats"

#: The same belief, one token different — ADR-0121 §1's own adversarial fixture.
#: Under a hashing embedder (what #862 ran) this scores at the *top* of the ranking
#: against `_SEAT`, which is why agreement may not be read off a retrieval score: a
#: threshold-keyed test folds this correction into the belief it corrects.
_AISLE = "the user prefers aisle seats"


async def test_a_verbatim_self_restatement_reinforces_rather_than_asking() -> None:
    """#862's first failure mode: the system asked whether the user contradicted itself.

    ``_rule_on_assertion`` arm 1 fires when *any* member of the conflict set is
    ``USER_ASSERTED``, and the conflict set is a topical-similarity ranking — which
    a verbatim restatement tops. So the arm fired and the user was interrogated
    about agreeing with themselves, three times out of three, which is exactly the
    interaction ADR-0038 §5 predicted when it rejected ``ASK_USER`` for this case.
    """
    proposal = _proposal(
        _semantic("again", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    earlier = _semantic(
        "said-before", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "said-before"


async def test_a_restatement_agreeing_with_an_observed_belief_reinforces_it() -> None:
    """#862's second failure mode: the confirmation retired what it confirmed.

    Above the conflict threshold arm 2 fired and ruled ``SUPERSEDE`` — closing the
    window on the very record the user had just confirmed, and counting in ADR-0120
    §5's correction rate as a belief the user overturned. An agreement inflating the
    correction rate is a measure-fidelity defect §5's own justification forbids:
    "One ruling kind means 'what was held is now wrong', and it is the one counted."
    """
    proposal = _proposal(
        _semantic("told-you", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    observed = _semantic("we-noticed", content=_SEAT, source=MemorySource.OBSERVED)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[observed])

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "we-noticed"


async def test_a_one_token_contradiction_still_defers_to_the_user() -> None:
    """The case ADR-0050 §2 was written for is untouched (ADR-0121 §9).

    §2's rule stands whole for every conflict set holding an asserted member that
    *disagrees* with the proposal — which is #245's honesty gap and is the reason
    ADR-0121 §1 refuses to read agreement off a similarity score at all: this pair
    is one token apart and would score at the top of any threshold drawn high
    enough to call a restatement an agreement.
    """
    proposal = _proposal(
        _semantic("correction", content=_AISLE, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    earlier = _semantic(
        "said-before", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_a_restatement_beside_a_disagreeing_assertion_still_defers() -> None:
    """ADR-0121 §2's second firing condition, which is what keeps #245 closed.

    The arm requires **every** ``USER_ASSERTED`` member of the conflict set to be in
    the agreeing set, not merely one. Without that, a user who said "window seats",
    then "aisle seats", then "window seats" again would reinforce the first record
    and leave the second live — two live contradictory assertions, the honesty
    defect ADR-0050 §2 exists to prevent, reached by a new path. So the ruling here
    is the deferral even though a perfectly good foldable agreeing member is present.
    """
    proposal = _proposal(
        _semantic("again", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    conflicts = [
        _semantic("agrees", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0),
        _semantic("disagrees", content=_AISLE, source=MemorySource.USER_ASSERTED, confidence=1.0),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_a_disagreeing_derived_conflict_does_not_block_the_agreement() -> None:
    """The condition is stated over the *asserted* members alone (ADR-0121 §2).

    A disagreeing ``OBSERVED`` or ``INFERRED`` member is not evidence of a
    contradiction — it is a similarity hit — so it neither blocks the arm nor is
    retired by it. ``REINFORCE`` has no retirement set (ADR-0045 §4), and retiring a
    record on the strength of a *restatement* would be retiring it on similarity
    alone, which ADR-0045 §5 refuses. It stays live, and the ruling names the
    agreeing member.
    """
    proposal = _proposal(
        _semantic("again", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    conflicts = [
        _semantic("our-guess", content=_AISLE, source=MemorySource.INFERRED),
        _semantic("we-noticed", content=_SEAT, source=MemorySource.OBSERVED),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "we-noticed"
    # A REINFORCE carries no retirement set at all, so nothing is retired here and
    # the ruling names one record rather than leading a set.
    assert decision.ttl is None


async def test_an_agreeing_external_record_is_never_named_by_the_arm() -> None:
    """ADR-0121 §3's exclusion, and the residue it states rather than hides.

    ``EXTERNAL`` is out of the foldable class for ADR-0092 §5's reason unchanged: a
    ``REINFORCE`` folds at the *target's* id, an import's id is the integrating
    system's idempotency key, and the next routine sync overwrites the fold —
    whether or not the user's words matched the import's. So the arm does not fire,
    the proposal falls through to the supersession arm, and ADR-0120 §5's correction
    rate counts a correction that did not happen. That is filed (ADR-0121 §7), and
    the store outcome is defensible: the user's own words land at a fresh id and the
    import is retired, which is what ADR-0092 §4 decided a user assertion does.
    """
    proposal = _proposal(
        _semantic("told-you", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    imported = _semantic("calendar", content=_SEAT, source=MemorySource.EXTERNAL, confidence=1.0)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[imported])

    assert decision.kind is MemoryDecisionKind.SUPERSEDE
    assert decision.target_id == "calendar"


async def test_the_arm_names_the_best_ranked_foldable_agreeing_member() -> None:
    """ADR-0121 §2 names the best-ranked member of the *foldable* agreeing set.

    Ranked first here is an agreeing ``EXTERNAL`` record, which §3 puts outside the
    foldable set — so the scan reaches past it to the agreeing ``OBSERVED`` one
    rather than abandoning the arm, exactly as the supersession arm's scan reaches
    past a member it may not name. Taking ``conflicts[0]`` would name a record the
    writer refuses to fold onto, turning an agreement into a ``MemoryStoreError``.
    """
    proposal = _proposal(
        _semantic("again", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    conflicts = [
        _semantic("calendar", content=_SEAT, source=MemorySource.EXTERNAL, confidence=1.0),
        _semantic("we-noticed", content=_SEAT, source=MemorySource.OBSERVED),
    ]

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=conflicts)

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "we-noticed"


async def test_records_of_different_kinds_never_agree() -> None:
    """ADR-0121 §1 requires ``kind`` equality, and states it rather than assuming it.

    Kind-scoped conflict detection means the ingestor never hands this policy a
    cross-kind conflict set, so the clause guards a path nothing takes today. It is
    written anyway, for the reason ADR-0074 §4's episodic exemption is: a floor that
    holds only while a coincidence holds is not a floor, and ADR-0121 §11 leaves
    #864's cross-kind reach explicitly undecided rather than foreclosed.
    """
    proposal = _proposal(
        _semantic("again", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    other_kind = _episodic("that-time", content=_SEAT, source=MemorySource.USER_ASSERTED)

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[other_kind])

    assert decision.kind is MemoryDecisionKind.ASK_USER


async def test_an_observation_agreeing_with_an_assertion_still_defers() -> None:
    """ADR-0121 §11's out-of-scope case, pinned so it is a decision and not a gap.

    An observation restating what the user told us still rules ``ASK_USER`` under
    rule 5. The arm is stated over a ``USER_ASSERTED`` *proposal* because the fold's
    ordinary arm would take the incoming record's source and **demote** the
    assertion to an observation; fixing that means extending ADR-0103 §6's
    corroboration rule again, on a path ADR-0120 §6 excludes from its measure anyway.
    Filed, not fixed here.
    """
    proposal = _proposal(_semantic("we-noticed", content=_SEAT, source=MemorySource.OBSERVED))
    theirs = _semantic(
        "their-words", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[theirs])

    assert decision.kind is MemoryDecisionKind.ASK_USER


#: ADR-0121 §1's four transformations and the ones it excludes, stated as pairs
#: against :data:`_SEAT`. The admitted ones "change no word"; each excluded one
#: decides that two *different* strings mean the same thing, which is a judgement,
#: and a judgement is what this predicate must not contain if it is to license a
#: fold onto a record the user gave us.
_AGREEMENT_FORMS = [
    (_SEAT, True, "byte-identical"),
    ("The User Prefers WINDOW Seats", True, "case-folded"),
    ("the  user   prefers window   seats", True, "collapsed-runs"),
    ("\n  the user prefers window seats \t", True, "stripped-ends"),
    # Escaped rather than written literally: a no-break space is invisible in
    # source and this case is *about* it. §1 says "Unicode whitespace", so a
    # collapse keyed on ASCII would call these two sentences different beliefs.
    ("the user prefers window\u00a0seats", True, "unicode-whitespace"),
    ("the user prefers window seats.", False, "trailing-stop"),
    ("user prefers window seats", False, "dropped-article"),
    ("the user prefers windowseats", False, "joined-tokens"),
    (_AISLE, False, "one-token-edit"),
]


@pytest.mark.parametrize(
    ("restatement", "expected_agreement"),
    [(form, agrees) for form, agrees, _ in _AGREEMENT_FORMS],
    ids=[label for _, _, label in _AGREEMENT_FORMS],
)
async def test_agreement_absorbs_exactly_the_four_transformations(
    restatement: str, expected_agreement: bool
) -> None:
    """ADR-0121 §1's predicate, exercised through the ruling it licenses.

    NFC normalisation, case folding, whitespace-run collapse and end-stripping are
    admitted; everything else is refused, including a trailing full stop, a dropped
    stop-word and a one-token substitution. Stemming, synonym expansion and every
    embedding comparison are out for the same reason, and their exclusion is the
    point rather than a simplification: the failure mode of a false *agreement* is
    folding a contradiction into the record it contradicts, at that record's id.

    Driven through ``decide`` rather than against the predicate directly, so what is
    pinned is the behaviour the ADR rules and not one implementation's helper.
    """
    proposal = _proposal(
        _semantic("again", content=restatement, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    earlier = _semantic(
        "said-before", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    expected = MemoryDecisionKind.REINFORCE if expected_agreement else MemoryDecisionKind.ASK_USER
    assert decision.kind is expected


async def test_agreement_normalises_composed_and_decomposed_forms_alike() -> None:
    """The NFC limb of ADR-0121 §1, which no ASCII case can reach.

    Two spellings of the same accented word — precomposed U+00E9 against ``e`` plus
    U+0301 — are the same text and a reader sees no difference at all. Without the
    normalisation limb the predicate would call them different beliefs and put the
    question back in front of the user, which is the harm this ADR removes.
    """
    composed = "the user prefers a window seat in the caf\u00e9 car"
    decomposed = "the user prefers a window seat in the cafe\u0301 car"
    proposal = _proposal(
        _semantic("again", content=decomposed, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    earlier = _semantic(
        "said-before", content=composed, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "said-before"


async def test_agreement_folds_case_beyond_ascii_lowering() -> None:
    """The case-*folding* limb of ADR-0121 §1, which no ASCII pair can reach.

    ``"ß".casefold()`` is ``"ss"``, while ``"Straße".lower()`` is ``"straße"`` —
    so a policy built on ``str.lower`` refuses this agreement and puts a question
    to a user who restated their own belief in another legitimate spelling. Every
    ASCII case in the table above passes under either implementation; this pair
    is the one that tells them apart, and the writer suite's twin case cannot
    stand in for it because ADR-0121 §6 makes the two recomputations independent
    obligations.
    """
    sharp = "the user prefers window seats on the Stra\u00dfe"
    folded = "the user prefers window seats on the STRASSE"
    proposal = _proposal(
        _semantic("again", content=folded, source=MemorySource.USER_ASSERTED, confidence=1.0)
    )
    earlier = _semantic(
        "said-before", content=sharp, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "said-before"


async def test_the_agreement_arm_stays_behind_the_admissibility_floor() -> None:
    """ADR-0121 §2 places the arm ahead of the *conflict* arms, not ahead of rule 1.

    A secret-tier restatement is Tier 0 whether or not it agrees with anything, and
    ADR-0004 §3 keeps it out of the memory database by every route. The floor's
    rulings are properties of the proposal alone and none commits anything, so
    nothing about the records' relation can make one safe to skip — the same
    argument that puts the *confirmed* rule behind the floor (ADR-0078 §5a).
    """
    proposal = _proposal(
        _semantic("again", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0),
        sensitivity=DataTier.SECRET,
    )
    earlier = _semantic(
        "said-before", content=_SEAT, source=MemorySource.USER_ASSERTED, confidence=1.0
    )

    decision = await DefaultMemoryPolicy().decide(proposal, conflicts=[earlier])

    assert decision.kind is MemoryDecisionKind.ASK_USER


# --- ADR-0161 §1: an attested re-read folds at an id that is ours ---
#
# ADR-0159 §4 kept `EXTERNAL` out of both target classes on ADR-0121 §3's argument,
# whose premise — an import's id is the integrating system's idempotency key — is
# false on this tree for a conforming producer: ADR-0092 §6 rules that the producer
# **mints**, opaque to the source. So the next routine sync never addresses the id
# the fold landed at, the futility never arises, and the fold ADR-0110 §4's presence
# rule depends on is available again (#1198).
#
# ADR-0161 §6 owes a `DefaultMemoryPolicy` test per branch clause (ii) opens, and
# says why they are owed *here* rather than end to end: four of them "are **not**
# reached by a repeat-read fixture, so passing the end-to-end tests above is not
# evidence that they hold". The conformance suite deliberately pins none of it
# (ADR-0040 §5, ADR-0159 §8).

#: The entry a connected calendar reports, rendered identically on every read. The
#: fold turns on `agrees`, so the *bytes* are the fixture and the ids are not.
_ENTRY = 'Calendar entry "standup", on 2026-08-03 from 09:00 to 09:15 (UTC).'

#: A second connected instance reporting the very same text. `Attestation.reported_by`
#: is "the only durable handle the record keeps on where it came from", and clause
#: (ii) requires it to match — so this is the axis that separates one integration
#: re-reporting itself from two integrations colliding (#1204).
_OTHER_SOURCE = Attestation(reported_by="calendar:personal", reported_at=_WHEN)


def _imported(
    record_id: str,
    *,
    content: str = _ENTRY,
    attestation: Attestation = _ATTESTED_BY,
) -> MemoryRecord:
    """An `EXTERNAL` belief in the shape a reader proposes and stores it.

    `EXTERNAL` is in the `ATTESTED` band, which ADR-0092 §1 requires to carry an
    attestation — so `reported_by` is always available where clause (ii) reaches,
    and the comparison it makes is total.
    """
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=1.0,
            last_updated=_WHEN,
            attestation=attestation,
        ),
    )


async def test_an_attested_re_read_folds_onto_the_record_it_already_reported() -> None:
    """ADR-0161 §1 clause (ii), and the whole reason for it (#1198).

    A scheduled read re-proposes an unchanged entry at a **freshly minted** id
    (ADR-0092 §6). Without this clause the arm finds no `OBSERVED`/`INFERRED`
    member, falls to ADR-0159 §4(c) and rules `ACCEPT`, which installs at that new
    id — so the predecessor is *absent* from a reading that in fact reported it, and
    ADR-0110 §5's coverage close retires it. Every scheduled read then retires its
    entire previous set and re-installs it at new ids.
    """
    stored = _imported("stored")

    decision = await DefaultMemoryPolicy().decide(
        _proposal(_imported("freshly-minted")), conflicts=[stored]
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "stored"


async def test_an_eligible_re_read_is_named_ahead_of_a_better_ranked_restatement() -> None:
    """ADR-0161 §1's precedence clause, which is a decision and not a tie-break.

    Without it a set holding both the proposal's own identical predecessor and a
    better-ranked `OBSERVED` member labelled `RESTATES` would fold onto the
    observation, leave the predecessor absent, and close it — #1198's failure
    reached by retrieval order instead of by source class. The observation is placed
    **first** here, so a scan that took the first eligible member by rank fails.
    """
    observed = _semantic("better-ranked", content=_ENTRY)
    stored = _imported("stored")

    decision = await DefaultMemoryPolicy().decide(
        _proposal(_imported("freshly-minted")),
        conflicts=[observed, stored],
        relations={"better-ranked": ConflictRelation.RESTATES},
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "stored"


async def test_a_contradicting_member_does_not_block_an_attested_re_read() -> None:
    """ADR-0161 §1 lifts ADR-0159 §4(a)'s purity condition from clause (ii) alone.

    Not an exemption from honesty — an application of it. Work both branches: the
    fold retires nothing (ADR-0045 §4), installs nothing new, and lands
    byte-identical content on a record that already carries it, so the contradicting
    member stays live. *Refusing* installs a third live record saying exactly what
    the target says, leaves the same member live, and — under a covered reading —
    leaves the target absent for ADR-0110 §5's close to retire. Blocking makes the
    store less honest on the same set.
    """
    stored = _imported("stored")
    disputed = _semantic("disputed", source=MemorySource.INFERRED)

    decision = await DefaultMemoryPolicy().decide(
        _proposal(_imported("freshly-minted")),
        conflicts=[stored, disputed],
        relations={"disputed": ConflictRelation.CONTRADICTS},
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "stored"


async def test_a_re_read_from_a_different_integration_does_not_fold() -> None:
    """Clause (ii)'s `reported_by` conjunct, from its failing side (ADR-0161 §1).

    Two integrations reporting an entry that renders identically land as two
    records, each present in its own reader's reading, and nothing alternates.
    Keying on `reported_by` also puts presence and absence on the same handle —
    ADR-0110 §3's condition 1 already selects absence candidates by it. Whether the
    restriction should ever be lifted is #1204's; this clause decides the case, and
    decides it the conservative way.
    """
    theirs = _imported("theirs", attestation=_OTHER_SOURCE)

    decision = await DefaultMemoryPolicy().decide(_proposal(_imported("ours")), conflicts=[theirs])

    assert decision.kind is MemoryDecisionKind.ACCEPT
    assert decision.target_id is None


async def test_a_rewritten_entry_from_the_same_integration_does_not_fold() -> None:
    """Clause (ii)'s `agrees` conjunct, from its failing side (ADR-0161 §1, §5).

    ADR-0110 §4's rewrite path, and the division ADR-0161 §5 turns on: "standup
    9am" becoming "sprint planning, Thursday, room 4" does **not** agree, so it
    installs beside its predecessor, whose window the reading closes — "the
    predecessor genuinely stopped being true and the install carries the current
    text."

    **This is the case an implementation keying clause (ii) on `reported_by` alone
    passes every other test with**, which is why ADR-0161 §6 names it and why no
    repeat-read fixture reaches it: such an implementation would fold a rewritten
    entry onto the predecessor it replaces, silently keeping the old text.
    """
    stored = _imported("stored")
    rewritten = _imported(
        "freshly-minted",
        content='Calendar entry "sprint planning", on 2026-08-06 from 14:00 to 15:00 (UTC).',
    )

    decision = await DefaultMemoryPolicy().decide(_proposal(rewritten), conflicts=[stored])

    assert decision.kind is MemoryDecisionKind.ACCEPT
    assert decision.target_id is None


async def test_the_model_rung_never_reaches_an_attested_target() -> None:
    """Clause (ii) is the certain rung and nothing above it (ADR-0161 §1).

    ADR-0121 §3's surviving half, read in the *agreement* direction: a model-judged
    statement is not a claim an observation is entitled to make against the system
    that reported the fact, and that is as true of "these say the same thing" as of
    "these cannot both be true". So a `RESTATES` label on an `EXTERNAL` member buys
    nothing — clause (i) requires the target to be `OBSERVED`/`INFERRED`, and clause
    (ii) requires the records to actually agree.
    """
    stored = _imported("stored")
    rewritten = _imported("freshly-minted", content="something the source now says instead")

    decision = await DefaultMemoryPolicy().decide(
        _proposal(rewritten),
        conflicts=[stored],
        relations={"stored": ConflictRelation.RESTATES},
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


async def test_an_external_member_is_still_no_supersession_target() -> None:
    """ADR-0161 §1: §4(b) is untouched, whatever the proposal's source.

    A supersession onto an import is what ADR-0121 §3's surviving half refuses in
    the contradiction direction, and clause (ii) reaches only the agreement one.
    """
    stored = _imported("stored")

    decision = await DefaultMemoryPolicy().decide(
        _proposal(_imported("freshly-minted", content="a different claim entirely")),
        conflicts=[stored],
        relations={"stored": ConflictRelation.CONTRADICTS},
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


# --- ADR-0161 §4: the degraded path names the same members ---
#
# §6 states no target class at all — "rules `REINFORCE` onto a member that `agrees`
# under ADR-0121 §1" — so read as its own text a deployment with no provider would
# fold where one with a provider does not. ADR-0161 §4 supplies the class and states
# it as **parity**: no ruling turns on whether a provider was reachable, because a
# presence rule that held only where one was configured would fail silently in the
# direction ADR-0117 §1 names. Every case below is run in **both** states ADR-0159
# §8 distinguishes — `None` says nothing determined relations at all, `{}` says
# something did and labelled nothing — which must rule identically.

_UNLABELLED: Final = pytest.mark.parametrize(
    "relations", [None, {}], ids=["no-reconciler", "reconciler-labelled-nothing"]
)


@_UNLABELLED
async def test_the_degraded_path_folds_an_attested_re_read(
    relations: dict[str, ConflictRelation] | None,
) -> None:
    """Clause (ii) names no label, so it reads identically with none (ADR-0161 §4)."""
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_imported("freshly-minted")),
        conflicts=[_imported("stored")],
        relations=relations,
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "stored"


@_UNLABELLED
async def test_the_degraded_path_refuses_a_cross_integration_fold(
    relations: dict[str, ConflictRelation] | None,
) -> None:
    """A ruling §6's unqualified "any agreeing member" gets wrong (ADR-0161 §8).

    This is one of the two rulings that change against §6's own text, which is why
    §6 is *partially superseded* rather than amended: an implementer building from
    it folds here, and after ADR-0161 rules `ACCEPT`.
    """
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_imported("ours")),
        conflicts=[_imported("theirs", attestation=_OTHER_SOURCE)],
        relations=relations,
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


@_UNLABELLED
@pytest.mark.parametrize(
    "source", [MemorySource.OBSERVED, MemorySource.INFERRED], ids=lambda s: str(s.value)
)
async def test_the_degraded_path_refuses_a_derived_proposal_onto_an_import(
    relations: dict[str, ConflictRelation] | None, source: MemorySource
) -> None:
    """The second ruling that changes against §6's text (ADR-0161 §8).

    Eligible under neither limb: (i) requires the **target** to be derived, and (ii)
    requires the **proposal** to be external. That outcome is ADR-0159 §4(a)'s
    exclusion holding exactly as ratified — what is new is that ADR-0161 §1 is the
    first place §6's target class is written down, so it is §1 an implementer now
    builds from.

    Confidence is above `min_confidence`, so a fall to the confidence arm is an
    `ACCEPT` and not a `STORE_TEMPORARY` — otherwise this case would be measuring
    the wrong arm.
    """
    proposal = _proposal(_semantic("derived", content=_ENTRY, source=source, confidence=0.9))

    decision = await DefaultMemoryPolicy().decide(
        proposal, conflicts=[_imported("stored")], relations=relations
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


@_UNLABELLED
async def test_the_degraded_path_refuses_a_rewritten_entry(
    relations: dict[str, ConflictRelation] | None,
) -> None:
    """Clause (ii)'s conjunction, pinned on the path that states limb (i)'s predicate.

    ADR-0161 §6 names this case in both matrices for a reason its own text gives: an
    implementation reading `reported_by` as the whole of (ii) "satisfies every other
    case in this matrix and still folds a rewritten entry, and the reconciled-path
    matrix above does not reach the degraded path at all".
    """
    rewritten = _imported("freshly-minted", content="the source now reports something else")

    decision = await DefaultMemoryPolicy().decide(
        _proposal(rewritten), conflicts=[_imported("stored")], relations=relations
    )

    assert decision.kind is MemoryDecisionKind.ACCEPT


@_UNLABELLED
async def test_the_degraded_path_still_folds_an_agreeing_derived_member(
    relations: dict[str, ConflictRelation] | None,
) -> None:
    """What ADR-0159 §6 *decided* is untouched, and ADR-0161 §8 says so.

    "An agreeing `OBSERVED` or `INFERRED` member folds in the degraded case exactly
    as it does today." Only the target set moved, and it moved by clause (ii) alone.
    """
    decision = await DefaultMemoryPolicy().decide(
        _proposal(_semantic("new", content="I prefer window seats")),
        conflicts=[_semantic("identical", content="I  PREFER   Window Seats ")],
        relations=relations,
    )

    assert decision.kind is MemoryDecisionKind.REINFORCE
    assert decision.target_id == "identical"

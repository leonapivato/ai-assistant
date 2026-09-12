"""Shared conformance suite for the GoalAssociator Protocol (ADR-0250 §4).

Every ``GoalAssociator`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`GoalAssociatorContract` and overrides
:meth:`~GoalAssociatorContract.answering`.

**Here rather than under ``tests/core/``**, beside ``query_composer_contract.py`` and
``planner_contract.py``: ADR-0250 §4 puts the production associator in
``ai_assistant.planning`` — for :class:`QueryComposer`'s own reason, that the
associator is a prompt — and this package is where the suite sits beside it.

**A fixture *and* a hook, and the split is the composer suite's.** The clauses about
the *shape* of the seam — one positional-only parameter, one member, a candidacy the
call does not modify — hold of any conforming subject, so they take the ordinary
``associator`` fixture. The clauses about the *answer* — "the verdict is dispositive in
three ways and ambiguous in one", and "an implementation that cannot parse its model's
answer returns ``UNDECIDED`` and never a guess" — cannot be reached by calling an
arbitrary associator with an arbitrary candidacy, because only the implementation's own
harness knows how to make its subject answer with a given verdict. Those take a
**prepared subject** from :meth:`~GoalAssociatorContract.answering` and assert what came
back.

**What is deliberately not in here**, because a generic suite cannot decide it:

* **That a real model's unreadable answer produces** ``UNDECIDED``. A suite cannot
  make an arbitrary associator's model return gibberish, so it pins that the decline
  is *returned* rather than raised, and not that it is reached from a malformed
  completion. That is the concrete associator's arm, in ADR-0250 §19's M2.
* **That the prompt carries no identifier.** A generic suite cannot see an arbitrary
  associator's model call, and the canonical fake makes none. The half a suite *can*
  decide is structural — that :class:`GoalCandidacy` and :class:`CandidateGoal` carry
  no field an identifier could sit in — and that is ADR-0250 §20 arm 22(a), asserted
  over the two types themselves in ``tests/core/test_planning_types.py``. Arm 22(b) is
  behavioural and belongs to the production renderer.
* **That no store seam is held.** A constructor is not reachable through the Protocol,
  and "this implementation holds a ``ModelProvider`` and nothing else that reads" is a
  fact about a composition and a review of ``planning/``, not about a return value.
* **That the caller resolves every label.** Label resolution is ``orchestration``'s by
  §4 — "the loop resolves a label by parsing *n* and indexing the very tuple it passed
  on this call" — so there is nothing on this side of the seam to assert it over.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import GoalAssociator
from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    AssociationVerdict,
    CandidateGoal,
    GoalAssociation,
    GoalCandidacy,
    GoalStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The request every case here associates over. Nothing in the contract is a function
#: of its content: what an associator makes of an utterance is a model's judgement,
#: and this suite asserts the shape of the answer rather than its correctness.
REQUEST = "make it Sunday"


def candidacy_of(
    *outcomes: str,
    elided: int = 0,
    focused: str | None = None,
) -> GoalCandidacy:
    """Build a candidacy over ``outcomes``, in the order given.

    Args:
        outcomes: One outcome statement per candidate, in ADR-0250 §1's order.
        elided: How many goals the cap dropped.
        focused: The label of the focused candidate, or ``None``.

    Returns:
        The candidacy, with every candidate ``ACTIVE`` — the status is a value the
        associator reads and this suite does not vary.
    """
    return GoalCandidacy(
        request=REQUEST,
        candidates=tuple(
            CandidateGoal(outcome=outcome, status=GoalStatus.ACTIVE) for outcome in outcomes
        ),
        elided=elided,
        focused=focused,
    )


#: Every verdict, paired with a label tuple its own validator admits — so a harness
#: asked for one can prepare a subject that returns it (ADR-0250 §4).
ADMITTED_ANSWERS: tuple[tuple[AssociationVerdict, tuple[str, ...]], ...] = (
    (AssociationVerdict.ASSOCIATES, ("G1",)),
    (AssociationVerdict.FRESH, ()),
    (AssociationVerdict.CONTINUES, ()),
    (AssociationVerdict.UNDECIDED, ()),
    (AssociationVerdict.UNDECIDED, ("G1", "G2")),
)


class GoalAssociatorContract:
    """Behaviour every ``GoalAssociator`` implementation must exhibit (ADR-0250 §4)."""

    @pytest.fixture
    def associator(self) -> GoalAssociator:
        """Override in a subclass with any conforming subject.

        What the subject answers is not this fixture's business: the cases that take it
        assert the shape of the seam rather than the verdict, and the ones that need a
        particular answer ask :meth:`answering` for a prepared subject instead.
        """
        raise NotImplementedError

    def answering(self, answer: GoalAssociation) -> GoalAssociator:
        """Override with a subject whose ``associate`` returns ``answer``.

        Called once per case that needs it, so each case gets a fresh subject.

        Args:
            answer: What the prepared subject must return.

        Returns:
            The prepared subject.
        """
        raise NotImplementedError

    def test_a_conforming_subject_satisfies_the_protocol(self, associator: GoalAssociator) -> None:
        """The subject *is* a ``GoalAssociator``, structurally.

        ``GoalAssociator`` is ``@runtime_checkable``, so this is the cheapest
        statement of the triad's first obligation: a fake that drifted from the
        Protocol's member set fails here rather than at a consumer.
        """
        assert isinstance(associator, GoalAssociator)

    def test_associate_takes_exactly_one_positional_only_parameter(
        self, associator: GoalAssociator
    ) -> None:
        """ADR-0250 §4: one positional-only parameter, no keyword, no second.

        "There is **no second member**, **no keyword parameter** and **no second
        positional**", on ADR-0238 §2's ruling that one value "names the whole of what
        a composition may draw on in a place a reviewer reads once". A subject that
        grew a keyword would let a supply site pass the right records or the wrong
        ones with no signal from the signature, which is the failure that clause
        exists to prevent — so the *subject's* signature is asserted and not only the
        Protocol's.
        """
        parameters = [
            parameter
            for name, parameter in inspect.signature(associator.associate).parameters.items()
            if name != "self"
        ]
        assert len(parameters) == 1, f"associate() takes {len(parameters)} parameters, not one"
        assert parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY

    def test_the_protocol_carries_exactly_one_member(self) -> None:
        """ADR-0250 §4: "exactly one member and no more".

        Asserted over the Protocol rather than over a subject, because a subject is
        free to carry anything else it likes — what is fixed is the surface a consumer
        may reach through the seam.
        """
        declared = sorted(
            name
            for name, member in vars(GoalAssociator).items()
            if not name.startswith("_") and inspect.isfunction(member)
        )
        assert declared == ["associate"]

    @pytest.mark.parametrize(("verdict", "labels"), ADMITTED_ANSWERS)
    async def test_every_verdict_is_returned_and_never_raised(
        self, verdict: AssociationVerdict, labels: Sequence[str]
    ) -> None:
        """Each of the four verdicts comes back as a value (ADR-0250 §4).

        **The decline is asserted rather than empty**, on ADR-0176 §1's shape: an
        implementation "that cannot parse its model's answer returns ``UNDECIDED`` and
        never a guess", and none reads an unparseable answer "as ``FRESH``, as
        ``CONTINUES``, or as an error that fails the turn". So every member — the
        decline included — is a *return*, and this is the half of that clause a
        generic suite can decide.
        """
        answer = GoalAssociation(verdict=verdict, labels=tuple(labels))
        subject = self.answering(answer)
        got = await subject.associate(candidacy_of("book a campsite", "file the tax return"))
        assert isinstance(got, GoalAssociation)
        assert got.verdict is verdict
        assert got.labels == tuple(labels)

    async def test_the_candidacy_is_not_modified(self, associator: GoalAssociator) -> None:
        """The value handed in comes back untouched (ADR-0250 §4).

        ``GoalCandidacy`` is frozen, so an implementation cannot edit the caller's
        value — and this states it as a property of the *seam* rather than of the
        type, because the containment argument §4 makes rests on the caller still
        holding the very tuple it passed: "the loop resolves a label by parsing *n*
        and indexing **the very tuple it passed on this call**".
        """
        candidacy = candidacy_of("book a campsite", "file the tax return", elided=3, focused="G1")
        before = candidacy.model_dump()

        await associator.associate(candidacy)

        assert candidacy.model_dump() == before

    async def test_a_single_candidate_is_associated_over_like_any_other(
        self, associator: GoalAssociator
    ) -> None:
        """One candidate is still a call (ADR-0250 §3).

        "It is tempting to rule that a conversation holding exactly one candidate
        associates to it without asking anything. It would be wrong" — so an
        implementation neither refuses a one-candidate candidacy nor short-circuits it
        into an ``ASSOCIATES`` nobody decided. What the suite can decide is that the
        shape is accepted and the subject's own answer comes back.
        """
        got = await associator.associate(candidacy_of("book a campsite"))

        assert isinstance(got, GoalAssociation)

    async def test_a_full_candidacy_is_associated_over(self, associator: GoalAssociator) -> None:
        """The cap is a shape an implementation must accept, not refuse (§2, §4).

        ``MAX_ASSOCIATION_CANDIDATES`` is the largest candidacy a caller can build, so
        a subject that fell over on it would make the cap unreachable — and the
        elision the cap discloses would then never be rendered to the associator at
        all, which is the one thing §2 requires of this seam.
        """
        candidacy = candidacy_of(
            *(f"objective {n}" for n in range(1, MAX_ASSOCIATION_CANDIDATES + 1)),
            elided=2,
        )

        got = await associator.associate(candidacy)

        assert isinstance(got, GoalAssociation)

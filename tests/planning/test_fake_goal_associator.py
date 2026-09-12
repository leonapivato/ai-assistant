"""The canonical ``GoalAssociator`` fake passes the shared conformance suite.

This is what lets other subsystems trust ``ai_assistant.testing.FakeGoalAssociator``
as a stand-in for an associator: it is held to the same contract the model-backed one
will be (ADR-0250 §19). Beyond the binding, what is here is the recording behaviour
the suite does not reach — the figure ADR-0250 §20's arms 1, 2 and 14 are stated over,
which is *whether this seam was reached at all*, and therefore the half that has to be
right before those arms are written.

**Here and not under ``tests/testing/``**, for the reason ``test_fake_query_composer``
is here: the suite this binds lives beside the production associator's package, and
pytest's ``prepend`` import mode puts a test module's *own* directory on ``sys.path``
and no other's. A binding one directory over would import the suite only in a
whole-suite run, and would fail to collect on its own.
"""

from __future__ import annotations

import pytest
from goal_associator_contract import GoalAssociatorContract, candidacy_of

from ai_assistant.core.types import AssociationVerdict, GoalAssociation
from ai_assistant.testing import FakeGoalAssociator


class TestFakeGoalAssociatorContract(GoalAssociatorContract):
    """Runs ``FakeGoalAssociator`` through the shared conformance suite."""

    @pytest.fixture
    def associator(self) -> FakeGoalAssociator:
        """Return an unconfigured fake, which declines (ADR-0250 §4).

        The cases taking this one assert the shape of the seam rather than the verdict,
        so what it answers does not matter — and the default is the decline, which is
        the answer §4 makes safe to give when nothing has been decided.
        """
        return FakeGoalAssociator()

    def answering(self, answer: GoalAssociation) -> FakeGoalAssociator:
        """Return a fresh associator scripted with ``answer``.

        Args:
            answer: What the subject must return.

        Returns:
            The prepared subject.
        """
        return FakeGoalAssociator(answer=answer)


async def test_the_default_answer_is_the_decline() -> None:
    """An unconfigured fake declines rather than associating (ADR-0250 §4).

    Deliberate rather than convenient: §4 makes ``UNDECIDED`` the shape an
    implementation returns when it cannot read its model's answer, and a fake that
    defaulted to ``CONTINUES`` would hand every unconfigured consumer a silent
    association to the focused goal — which is precisely the silent rewrite §3 exists
    to forbid.
    """
    associator = FakeGoalAssociator()
    answer = await associator.associate(candidacy_of("book a campsite"))
    assert answer.verdict is AssociationVerdict.UNDECIDED
    assert answer.labels == ()


async def test_it_records_every_candidacy_it_was_handed() -> None:
    """The figure ADR-0250 §20's arms 1, 2 and 14 are stated over.

    "A first turn costs nothing new", "one candidate still costs a call" and "a spoken
    turn is told nothing a stored goal holds" are each, at this seam, an assertion
    about whether ``associate`` was reached and over what — so the fake records the
    candidacies rather than only counting them.
    """
    associator = FakeGoalAssociator()
    before = associator.calls
    assert associator.call_count == 0
    assert before == ()

    first = candidacy_of("book a campsite")
    second = candidacy_of("file the tax return", "book a campsite", elided=1)
    await associator.associate(first)
    await associator.associate(second)

    recorded = associator.calls
    assert associator.call_count == 2
    assert recorded == (first, second)
    assert [one.elided for one in recorded] == [0, 1], "and each is the value that call got"


async def test_the_recorded_calls_are_a_tuple_a_caller_cannot_edit() -> None:
    """A caller that mutated the page has changed nothing about the record.

    ADR-0085 §3b's reasoning, applied to a test double's own listing: a consumer that
    could clear ``calls`` would be able to make an arm about a call that happened pass
    by deleting the evidence of it.
    """
    associator = FakeGoalAssociator()
    await associator.associate(candidacy_of("book a campsite"))
    page = associator.calls
    assert isinstance(page, tuple)
    assert associator.calls == page

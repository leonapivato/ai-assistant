"""The canonical ``CoverageAnswers`` fake, bound to the shared suite.

ADR-0270 §1 lands a triad — the Protocol, its shared conformance suite and a
canonical fake — and this is the third artifact: without a binding class the suite
collects nothing and the fake is unverified however many files exist
(``tests/core/test_protocol_triad.py`` makes that mechanical).

Beyond the suite, the two obligations that **override** the fake's configuration are
driven here. Neither is a matter of taste: a fake configurable into an answer its own
conformance suite refuses would certify a consumer that relied on it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from coverage_answers_contract import (
    BARE,
    DATED,
    GOVERNING_QUOTE,
    MONEY_COVERAGE,
    PERIOD_COVERAGE,
    PRICED,
    CoverageAnswersContract,
)

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.testing import FakeCoverageAnswers

if TYPE_CHECKING:
    from ai_assistant.core.protocols import CoverageAnswers


class TestFakeCoverageAnswersContract(CoverageAnswersContract):
    """Runs :class:`~ai_assistant.testing.FakeCoverageAnswers` through the shared suite."""

    @pytest.fixture
    def answers(self) -> CoverageAnswers:
        """A fake configured to answer met, carrying the governing quote.

        One configuration answers all three of the suite's met cases, because the
        first override drops the quote wherever the evidence route could not have
        decided one — which is the rule the suite is about.

        Returns:
            The subject.
        """
        return FakeCoverageAnswers(met=True, quote=GOVERNING_QUOTE)

    @pytest.fixture
    def unmet_answers(self) -> CoverageAnswers:
        """A fake configured to answer unmet.

        Returns:
            The subject.
        """
        return FakeCoverageAnswers(met=False)


async def test_a_quote_rides_back_only_where_a_money_member_is_in_play() -> None:
    """ADR-0270 §2's presence rule, held **over** the configuration.

    Configured with a quote, the fake still answers ``quoted`` ``None`` for a coverage
    carrying no ``MONEY`` member and for an empty one: the evidence route meets a
    member of no other kind in any case (ADR-0266 §7), so there is nothing such an
    answer could have been proved over. Without the override a consumer could seed
    *"met, over this quote"* for a ``PERIOD``-only coverage and be certified against a
    value the one implementation never produces.
    """
    seam = FakeCoverageAnswers(met=True, quote=GOVERNING_QUOTE)
    assert (await seam.coverage_met(PRICED, MONEY_COVERAGE)).quoted == GOVERNING_QUOTE
    assert (await seam.coverage_met(DATED, PERIOD_COVERAGE)).quoted is None
    assert (await seam.coverage_met(BARE, ())).quoted is None


async def test_a_met_money_coverage_is_unavailable_without_a_quote_to_prove_it() -> None:
    """ADR-0270 §2's presence rule in the **other** direction, held over the
    configuration (adversarial review, round 1, ``blocker``).

    ``quoted`` is *"set where ``met`` is true **and** ``coverage`` carries a ``MONEY``
    member"*, so a met answer over a priced coverage carrying no quote is not an
    answer the one implementation can produce — and a consumer seeded with one would
    be certified against an absent ``Authorization.quoted`` on a row the evidence
    route did decide. A fake holding no quote is the fake's own reading of §4's *"An
    implementation constructed with **no** ``GoalQuotes`` answers ``met`` false"*, so
    it answers **unmet**, which is the fail-closed direction.

    The coverage carrying no ``MONEY`` member is the control: nothing there needs a
    quote, so the default fake still answers met.
    """
    seam = FakeCoverageAnswers(met=True)
    priced = await seam.coverage_met(PRICED, MONEY_COVERAGE)
    assert (priced.met, priced.quoted) == (False, None)
    assert (await seam.coverage_met(DATED, PERIOD_COVERAGE)).met is True
    assert (await seam.coverage_met(BARE, ())).met is True


async def test_an_unmet_answer_drops_the_configured_quote_rather_than_raising() -> None:
    """The same override, in the direction :class:`CoverageAnswer`'s model refuses.

    A fake that passed a configured quote straight through beside ``met=False`` would
    raise a ``ValidationError`` out of the member — which is not an answer ADR-0254 §1
    disposes of, and would make *"configure it unmet"* fail for a reason the caller
    cannot see.
    """
    seam = FakeCoverageAnswers(met=False, quote=GOVERNING_QUOTE)
    answer = await seam.coverage_met(PRICED, MONEY_COVERAGE)
    assert answer.met is False
    assert answer.quoted is None


async def test_reconfiguring_changes_what_the_next_call_answers() -> None:
    """``answer`` is how a test drives the branch it wants, mid-case."""
    seam = FakeCoverageAnswers(met=False)
    assert (await seam.coverage_met(PRICED, MONEY_COVERAGE)).met is False
    seam.answer(met=True, quote=GOVERNING_QUOTE)
    assert (await seam.coverage_met(PRICED, MONEY_COVERAGE)).quoted == GOVERNING_QUOTE


async def test_every_call_is_recorded_detached_and_counted() -> None:
    """What a test asserts the **writer** did with the seam (ADR-0270 §3).

    The proposal path's whole obligation is that condition 6 goes through this member
    and that no conjunct is re-implemented beside it, so a consumer's test reads back
    the pair it was asked about. Recorded detached, because the caller still holds
    both.
    """
    seam = FakeCoverageAnswers(quote=GOVERNING_QUOTE)
    await seam.coverage_met(PRICED, MONEY_COVERAGE)
    await seam.coverage_met(BARE, ())
    assert seam.call_count == 2
    recorded, coverage = seam.calls[0]
    assert recorded == PRICED
    assert coverage == MONEY_COVERAGE
    assert recorded is not PRICED, "a recorded call the caller can still rewrite records nothing"
    assert seam.calls[1] == (BARE, ())


async def test_an_armed_fault_propagates_and_is_never_an_absence() -> None:
    """ADR-0270 §4: the fault *"propagates"* rather than answering met or unmet.

    A component that asked writes no row where this member faults, and the one call
    is confirmed under ADR-0148 §3's route (a) — ADR-0254 §1's own disposition for a
    failed completeness condition. A fake that converted it into an unmet answer
    would certify a writer that never learned to tell the two apart.
    """
    seam = FakeCoverageAnswers(quote=GOVERNING_QUOTE)
    seam.fail_coverage_met()
    with pytest.raises(AuthorizationError):
        await seam.coverage_met(PRICED, MONEY_COVERAGE)
    assert seam.call_count == 1, "the call it faulted on is still a call it was asked"


async def test_a_returned_quote_is_detached_from_the_one_it_holds() -> None:
    """The bypass ``GoalQuotes``' own fake closes, one seam later.

    An amount rewritten through a returned object is a ceiling proved against a
    figure no provider ever quoted — and a path-(i) writer records this value on the
    row, so it is the row that carries the rewrite.
    """
    seam = FakeCoverageAnswers(met=True, quote=GOVERNING_QUOTE)
    answer = await seam.coverage_met(PRICED, MONEY_COVERAGE)
    assert answer.quoted is not None
    answer.quoted.__dict__["amount"] = answer.quoted.amount + Decimal("1000")

    again = await seam.coverage_met(PRICED, MONEY_COVERAGE)
    assert again.quoted is not None
    assert again.quoted.amount == GOVERNING_QUOTE.amount

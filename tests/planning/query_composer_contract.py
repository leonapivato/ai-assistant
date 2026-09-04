"""Shared conformance suite for the QueryComposer Protocol (ADR-0231 §3, §17).

Every ``QueryComposer`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`QueryComposerContract`, supplies the ``composer`` fixture, and overrides
:meth:`~QueryComposerContract.composing`, :meth:`~QueryComposerContract.refusing`
and :meth:`~QueryComposerContract.gated`.

**Here rather than under ``tests/core/``**, beside ``planner_contract.py``: ADR-0231
§3 puts the production composer in ``ai_assistant.planning`` — "because the composer
is a prompt" — and this package is where the suite sits beside it, exactly as the
``Planner`` suite does. The ``Fetcher`` suite made the other choice for a reason that
does not hold here: its concrete implementation lives in ``ai_assistant.readers``,
"a package no subsystem may import".

**Three hooks and not one fixture, because the clauses are about answers a suite has
to choose.** "A composition over the bound is a refusal and never a truncation" and
"every refusal is returned and none is raised" cannot be reached by calling an
arbitrary composer with an arbitrary utterance: only the implementation's own harness
knows how to make its subject answer with a given string or refuse with a given
class. So the suite asks for a **prepared subject** — and what it asserts is what
came back.

**The bound comes from the harness, and ADR-0231 §17 says why**: "a returned query is
non-blank and within *the bound the implementation under test was configured with*,
which the harness supplies because no ``core`` value carries it". ``QueryOutcome``
carries no bound and validates identically in every deployment (§3), so there is
nothing in the value for a suite to read it off. It is a hook of its own —
:meth:`QueryComposerContract.bound` — rather than a field on a prepared subject,
because the cases that drive the boundary have to know the figure *before* they can
say what composition to prepare.

**What is deliberately not in here.** The clauses expressible without a model, and no
others (§17):

* **That a *real* model failure produces each refusal class.** A suite cannot make an
  arbitrary composer's model fail, so it pins that each class is *returned* rather
  than raised, and not that ``UNAVAILABLE`` is reached from a real transport error or
  ``MALFORMED`` from a real answer. Those are the concrete composer's arms.
* **That the prompt carries the utterance and nothing else.** A generic suite cannot
  see an arbitrary composer's model call, and the canonical fake makes none. ADR-0231
  §18's test 4 asserts it over the concrete composer's own ``ModelProvider`` fake; the
  half a suite *can* decide — that no second input exists to be passed — is
  :meth:`QueryComposerContract.test_compose_takes_exactly_one_positional_parameter`,
  and it is the whole reason §17 puts that clause here rather than there.
* **That no store seam is held.** A constructor is not reachable through the
  Protocol, and "this implementation holds no ``MemoryStore``" is a fact about a
  composition and a review of ``planning/``, not about a return value.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.protocols import QueryComposer
from ai_assistant.core.types import QueryRefusal

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.testing.cancellation import SuspendedCall

#: An utterance a suite hands a subject where the words themselves do not matter.
#: Every hook is free to ignore it and name its own.
UTTERANCE = "what is the tallest building in Porto"

#: What a failure of the truncation case means, in one place (ADR-0231 §3). It is the
#: one place a conforming-looking composer satisfies every other clause here and
#: still hands the seam a question nobody asked: "a composition over the bound is
#: refused rather than truncated", because a prefix of a query is a different
#: question and one no reader of the outcome could tell from the one that was asked.
_TRUNCATED = (
    "a composition longer than the configured bound is refused TOO_LONG and never "
    "truncated to fit (ADR-0231 §3). Got: {outcome!r}"
)


@dataclass(frozen=True)
class ScriptedComposition:
    """A subject prepared to compose one particular query, and how to reach it.

    Attributes:
        composer: The subject, ready to be called.
        utterance: The utterance that draws the prepared composition out of it.
    """

    composer: QueryComposer
    utterance: str


@dataclass(frozen=True)
class ScriptedRefusal:
    """A subject prepared to refuse with one particular class, and how to reach it.

    Attributes:
        composer: The subject, ready to be called.
        utterance: The utterance that draws the prepared refusal out of it.
    """

    composer: QueryComposer
    utterance: str


@dataclass(frozen=True)
class GatedComposition:
    """One subject that can be held inside its composition, plus the lever.

    What ADR-0060's case needs from an implementation, and no more. The property has
    no positive signal through the member alone: a suite has to hold a call open at a
    point it has demonstrably reached, cancel it *there*, and see what comes back —
    and only the implementation knows where its suspension is. A call cancelled
    *before* it suspends exercises none of the code an implementation would use to
    catch a ``CancelledError`` during a model call and convert it into a refusal, so
    a suite without this lever reports the property as held while testing nothing.

    Attributes:
        composer: The subject, ready to be called.
        utterance: The utterance to compose.
        arm: Arms the **next** ``compose`` to suspend, and returns the handle the
            suite waits on and releases.
    """

    composer: QueryComposer
    utterance: str
    arm: Callable[[], SuspendedCall]


class QueryComposerContract:
    """Behaviour every ``QueryComposer`` implementation must exhibit (ADR-0231 §3)."""

    @pytest.fixture
    def composer(self) -> QueryComposer:
        """Override in a subclass with any conforming subject."""
        raise NotImplementedError

    def bound(self) -> int:
        """Override with the ``search_query_max_chars`` every subject here carries.

        One figure for the whole harness: every subject :meth:`composing`,
        :meth:`refusing` and :meth:`gated` return must be configured with it, since
        the boundary cases below choose what to compose from it.
        """
        raise NotImplementedError

    def composing(self, query: str) -> ScriptedComposition:
        """Override with a subject whose composition for one utterance is ``query``.

        ``query`` is what the subject *composes*, before its own bound is applied —
        so a harness asked for a string longer than the bound it configured must
        prepare a subject that would have answered with it, and let the subject
        refuse. A harness that clipped ``query`` itself would be answering the
        question this suite is asking.

        Called once per case that needs it, so each gets a fresh subject.
        """
        raise NotImplementedError

    def refusing(self, refusal: QueryRefusal) -> ScriptedRefusal:
        """Override with a subject whose composition for one utterance refuses so.

        Called once per case that needs it, and once per member: every member of
        :class:`~ai_assistant.core.types.QueryRefusal` must be reachable, because
        ADR-0231 §3's posture is that *each* of them is returned rather than raised.
        """
        raise NotImplementedError

    def gated(self) -> GatedComposition:
        """Override with a subject that can be held at its suspension point.

        Called once per case that needs it. See :class:`GatedComposition`.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, composer: QueryComposer) -> None:
        assert isinstance(composer, QueryComposer)

    # --- the signature is the safety claim (ADR-0231 §3, §17) ---------------

    def test_compose_takes_exactly_one_positional_parameter(self, composer: QueryComposer) -> None:
        """The clause ADR-0231 §3's whole safety claim rests on, on the signature.

        §17 puts it in the suite rather than in the concrete composer's tests
        "because it is the clause on which §3's whole safety claim rests for **every**
        ``QueryComposer`` this system ever wires". The claim is that no store value is
        in view when the query is written, and what makes it true is that there is no
        parameter through which one could arrive — not a rule an implementation
        keeps. So the assertion is over the *runtime* signature: one positional
        parameter beside ``self``, and no keyword parameter at all.

        ``VAR_POSITIONAL`` and ``VAR_KEYWORD`` are refused for the same reason a
        second named parameter is: ``compose(self, utterance, /, *args, **kwargs)``
        is a caller able to widen the input, whatever its first parameter is called.
        """
        parameters = [
            parameter
            for name, parameter in inspect.signature(type(composer).compose).parameters.items()
            if name != "self"
        ]

        assert [parameter.kind for parameter in parameters] == [
            inspect.Parameter.POSITIONAL_ONLY
        ], (
            "QueryComposer.compose takes exactly one positional-only parameter and no "
            f"keyword parameters (ADR-0231 §3). Got: {parameters!r}"
        )

    # --- what an outcome carries (ADR-0231 §3) ------------------------------

    async def test_an_outcome_carries_a_query_or_a_refusal_and_never_both(self) -> None:
        """§3's exactly-one rule, over both of the outcomes a suite can reach.

        The condition is the model's own, so this case cannot fail on a conforming
        *value* — what it fails is a composer that never reaches one of the two
        states, which is the half a harness can get wrong.
        """
        composed = self.composing("porto tallest building")
        refused = self.refusing(QueryRefusal.DECLINED)

        first = await composed.composer.compose(composed.utterance)
        second = await refused.composer.compose(refused.utterance)

        assert (first.query is None) != (first.refusal is None)
        assert (second.query is None) != (second.refusal is None)

    async def test_a_composed_query_is_non_blank_and_within_the_configured_bound(
        self,
    ) -> None:
        """§17's clause, over a composition the harness chose and the bound it set."""
        subject = self.composing("porto tallest building")

        outcome = await subject.composer.compose(subject.utterance)

        assert outcome.query is not None
        assert outcome.query.strip()
        assert len(outcome.query) <= self.bound()

    async def test_a_composition_at_the_bound_is_returned_whole(self) -> None:
        """ADR-0231 §18's arm 13b, first half: the boundary and not only over it.

        "A query of exactly ``search_query_max_chars`` is returned and one longer is
        ``TOO_LONG``." The pair fails an implementation whose comparison is the wrong
        way round, which is the defect a test only over the bound cannot see.
        """
        at_the_bound = "q" * self.bound()
        subject = self.composing(at_the_bound)

        outcome = await subject.composer.compose(subject.utterance)

        assert outcome.query == at_the_bound

    async def test_a_composition_over_the_bound_is_refused_and_never_truncated(
        self,
    ) -> None:
        """§3's refuse-rather-than-truncate clause, and 13b's second half.

        Both halves are asserted, because they fail different implementations: the
        refusal class fails one that returned some other member, and ``query is
        None`` fails one that clipped the composition to fit and returned it — which
        would satisfy every other clause in this file.
        """
        subject = self.composing("q" * (self.bound() + 1))

        outcome = await subject.composer.compose(subject.utterance)

        assert outcome.refusal is QueryRefusal.TOO_LONG
        assert outcome.query is None, _TRUNCATED.format(outcome=outcome)

    async def test_the_bound_is_counted_in_unicode_code_points(self) -> None:
        """ADR-0231 §5: the bound is "counted in Unicode code points".

        The arm that fails an implementation counting UTF-8 bytes or UTF-16 units. An
        astral code point is four bytes and two UTF-16 units, so a query of exactly
        the bound in astral characters is four times the bound in bytes: a byte-
        counting composer refuses it, and this suite's other cases — written in ASCII,
        where every unit count coincides — cannot tell.
        """
        at_the_bound = "\U0001f600" * self.bound()
        subject = self.composing(at_the_bound)

        outcome = await subject.composer.compose(subject.utterance)

        assert outcome.query == at_the_bound

    # --- failure posture (ADR-0231 §3) --------------------------------------

    @pytest.mark.parametrize("refusal", list(QueryRefusal))
    async def test_compose_raises_for_no_composition_reason(self, refusal: QueryRefusal) -> None:
        """§3: "every one of ``QueryRefusal``'s members is returned and not raised".

        Parametrised over the whole enumeration rather than over one member, so a
        fifth added without an arm here fails: the clause is about the vocabulary and
        not about an example of it. A composer that raised would make ADR-0226 §5's
        degradation posture the servicer's problem to catch correctly at every call
        site, where a closed refusal enumeration makes the non-yield a value the audit
        can count and the turn can ignore.
        """
        subject = self.refusing(refusal)

        outcome = await subject.composer.compose(subject.utterance)

        assert outcome.refusal is refusal
        assert outcome.query is None

    async def test_a_cancelled_composition_is_delivered_onward_unchanged(self) -> None:
        """ADR-0060 through this seam: a cancellation is never absorbed (§3).

        Held at the subject's own suspension point and cancelled *there*, because a
        call cancelled before it suspends exercises none of the code that would
        convert one. This is the place a conforming-looking composer satisfies every
        other clause in this file and still gets it wrong — by catching broadly around
        its model call and returning ``UNAVAILABLE`` for a shutdown that was working.
        """
        subject = self.gated()
        gate = subject.arm()
        call = asyncio.ensure_future(subject.composer.compose(subject.utterance))
        await gate.reached()

        call.cancel()
        gate.release()

        with pytest.raises(asyncio.CancelledError):
            await call

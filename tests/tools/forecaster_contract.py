"""Shared conformance suite for the Forecaster Protocol (ADR-0260 §4, §5, §12).

Every ``Forecaster`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`ForecasterContract`, supplies
the ``forecaster`` fixture, and overrides the hooks below.

**Here rather than under ``tests/core/``**, beside ``web_searcher_contract.py``: ADR-0260
§1 puts the production forecaster in ``ai_assistant.tools``, at the seam ADR-0154 §1
designates, and this package is where the suite sits beside it.

**The hooks are ``async``**, for the ``WebSearcher`` suite's reason: preparing a subject
here means arranging a configured provider and a keyring, and a keyring is written to
through an ``async`` seam.

**Hooks and not one fixture, because the clauses are about answers a suite has to
choose.** "At most the configured day count", "every minted record declares a bounded
extent" and "each refusal is returned rather than raised" cannot be reached by handing an
arbitrary forecaster an arbitrary call: only the implementation's own harness knows how
to make its subject answer with a given number of days, refuse with a given class, or
accept a call at all — an *authorised* ``ToolCall`` is not something a suite can build for
a subject whose declaration it has never seen. So the suite asks for a **prepared subject
and the call that draws the prepared answer out of it**, and what it asserts is what came
back.

**Both bounds come from the harness, and ADR-0260 §4 says why**: ``forecast_max_days`` and
``forecast_max_day_chars`` are ``Settings`` fields the *configured* forecaster enforces,
and ``ForecastOutcome`` "carries none of them and validates identically in every
deployment". So there is nothing in the value for a suite to read either off, and each is
a hook of its own, because the cases that drive them have to know the figure *before* they
can say what answer to prepare.

**What is deliberately not in here.** ADR-0260 §13's preamble makes "the production type
or component" the subject of its own arms, and this preamble "reaches the shared
conformance suite not at all" — so the clauses a generic suite cannot make an arbitrary
subject exhibit are absent and are the concrete forecaster's arms instead:

* **That a real provider failure produces each refusal class.** A suite cannot make an
  arbitrary provider fail, so it pins that each class is *returned* rather than raised,
  and not that ``TRANSPORT_FAILED`` is reached from a refused connection or
  ``UNATTESTED`` from a response declaring no instant.
* **That §5's drop rules drop what they say.** A day whose offset is undeclared, a day
  over the content bound, a day whose transcribed span carries a line break — none is
  expressible over a subject whose documented response format this suite has never seen.
  **The duplicate rule is the exception, and it is here**: its consequence is stateable
  without seeing a response at all — a provider that names one day and only that day,
  twice, has described no day once, so §5 drops both rows and the read yields
  ``NO_RESULT``. It is here because ADR-0260 §13(b-prime) names it as the clause an
  implementation gets wrong by *ordering* (capping before it counts), and because a
  canonical fake that minted the first of the two rows is scriptable into a state no
  response can put a production forecaster in — which is a consumer's suite passing over
  an answer no deployment can produce. What each implementation still owes its own arms
  is which days survive beside a duplicate, and both encounter orders.
* **That §6's three pre-execution checks reach no credential and open no channel.**
  A generic suite holds no doubles to look at. That the checks **refuse** is asserted
  here, because §6 puts them on ``read`` itself; the *ordering* — before the credential
  read and before any channel — is each implementation's own arm.
* **That the declaration is absent from every ``ToolRegistry``.** A property of a
  *composition*, asserted in the wiring's own test where it can be broken.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError
from ai_assistant.core.protocols import Forecaster
from ai_assistant.core.types import (
    ForecastOutcome,
    ForecastRefusal,
    MemorySource,
    ToolCall,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.testing.cancellation import SuspendedCall

#: The bound every case here passes unless it is about the bound (ADR-0241 §1).
#: Generous enough that no arrangement reaches it by accident, so a case that fails is
#: failing on the clause it is about rather than on a machine's load.
A_BOUND: Final = timedelta(seconds=30)

#: The bound the deadline case sets, small enough that a real wait past it is a fraction
#: of a second. A **real** duration and not a fake clock, because what ADR-0241 asks for
#: is that the read stops waiting.
_SHORT_BOUND: Final = timedelta(milliseconds=50)

#: How long a case will wait for a subject to answer once it has been released. Failing
#: here is a hang, and a hang is what this suite exists to catch.
_WAIT_SECONDS: Final = 5.0


class _CannotDescribeItself:
    """A bound outside the domain whose ``__repr__`` raises.

    **The diagnostic must not be able to destroy the diagnosis.** The value and its
    ``__repr__`` are both the caller's, so an implementation interpolating it into the
    message that reports it raises whatever that ``__repr__`` threw — in place of the
    ``ValueError`` ADR-0241 §1 says a bound outside the domain gets. ``core`` carries
    :func:`~ai_assistant.core.types.describe_untrusted` for exactly this, and this case is
    what holds every ``Forecaster`` to using something like it.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """Raise instead of describing this value.

        Returns:
            Never.

        Raises:
            RuntimeError: Always.
        """
        msg = "a value that will not say what it is"
        raise RuntimeError(msg)


class _LyingBound(timedelta):
    """A bound of :data:`_SHORT_BOUND`'s duration whose own arithmetic cannot be trusted.

    ``isinstance`` admits a subclass, and an implementation that opened its window from
    ``timeout.total_seconds()`` would open one that never closes — the spelling for
    "unbounded" ADR-0241 §1 says the contract does not have, reached through a value that
    passes every check on its face. The three fields ``timedelta`` itself carries are
    untouched, so the duration this states is :data:`_SHORT_BOUND`'s.
    """

    __slots__ = ()

    def total_seconds(self) -> float:
        """Report a duration no deadline could fire at.

        Returns:
            Infinity, which is what an implementation reading the object rather than its
            fields would hand ``asyncio.timeout``.
        """
        return float("inf")


#: One instance, since it is immutable and every case uses it the same way.
_LYING_BOUND: Final = _LyingBound(milliseconds=50)

#: What a failure of the day-count case means, in one place (ADR-0260 §5, §11). A
#: forecaster that minted more than it was configured for is one whose contribution to
#: ADR-0226 §6's budget of ten is a figure the operator did not set, which is the reason
#: §11 makes three a ceiling the setting narrows and never widens.
_OVER_THE_COUNT = (
    "a forecast read mints at most the `forecast_max_days` it was configured with "
    "(ADR-0260 §5, §11). Configured for {bound}, got {count}"
)

#: What a failure of the duplicate case means (ADR-0260 §5, §13(b-prime)). A forecaster
#: that minted anything from a response naming one day twice has preferred one of the
#: provider's rows over another, which is the one thing §5's duplicate clause forbids in
#: terms — and the shape §13(b-prime) says an implementation reaches by capping before it
#: counts.
_KEPT_A_DUPLICATE = (
    "a day the provider names more than once is dropped in every one of its rows, so a "
    "response naming one day twice and no other yields NO_RESULT (ADR-0260 §5). Got "
    "{count} record(s)"
)

#: What a failure of the attestation case means (ADR-0260 §5, ADR-0092 §3). The record's
#: ``reported_by`` is the **source instance** and is required to equal the forecaster's
#: own ``name``; a producer that put a vendor, an origin or a place there would be
#: attributing its record to a party this system never spoke to.
_MISATTRIBUTED = (
    "every record a forecast read mints carries an Attestation whose reported_by is the "
    "forecaster's own name (ADR-0260 §5, ADR-0092 §3). Expected {name!r}, got {got!r}"
)

#: What a failure of the extent case means (ADR-0260 §5, ADR-0117 §2). It is the field
#: the whole decision is bought for: without it ADR-0252 §3 has nothing to compose a
#: ``supported`` window from, and every row would fail §6's first test exactly as a
#: ``WEB_SEARCH`` row does.
_NO_EXTENT = (
    "every record a forecast read mints declares a bounded half-open extent over the day "
    "it is about (ADR-0260 §5, ADR-0117 §2). Got {got!r}"
)


@dataclass(frozen=True)
class ScriptedRead:
    """A subject prepared to answer with a given number of days, and how to reach it.

    Attributes:
        forecaster: The subject, ready to be called.
        call: The authorised call that draws the prepared answer out of it.
        timeout: The bound to pass at that call (ADR-0241 §1). Defaults to
            :data:`A_BOUND`, which every answering arrangement fits inside.
    """

    forecaster: Forecaster
    call: ToolCall
    timeout: timedelta = field(default=A_BOUND)


@dataclass(frozen=True)
class ScriptedRefusal:
    """A subject prepared to refuse with one particular class, and how to reach it.

    Attributes:
        forecaster: The subject, ready to be called.
        call: The authorised call that draws the prepared refusal out of it.
        timeout: The bound to pass at that call. Defaults to :data:`A_BOUND`, and is a
            field rather than a constant because one member —
            :attr:`~ai_assistant.core.types.ForecastRefusal.DEADLINE_EXPIRED` — is
            reached by the bound itself expiring, so the harness that arranges a real
            cause for it is the party that knows which bound reaches it.
    """

    forecaster: Forecaster
    call: ToolCall
    timeout: timedelta = field(default=A_BOUND)


@dataclass(frozen=True)
class GatedRead:
    """One subject that can be held inside its read, plus the lever.

    What ADR-0060's case needs from an implementation, and no more. The property has no
    positive signal through the member alone: a suite has to hold a call open at a point
    it has demonstrably reached, cancel it *there*, and see what comes back — and only the
    implementation knows where its suspension is. A call cancelled *before* it suspends
    exercises none of the code an implementation would use to catch a ``CancelledError``
    during a provider call and convert it into a refusal, so a suite without this lever
    reports the property as held while testing nothing.

    Attributes:
        forecaster: The subject, ready to be called.
        call: The authorised call to make.
        arm: Arms the **next** ``read`` to suspend, and returns the handle the suite
            waits on and releases.
    """

    forecaster: Forecaster
    call: ToolCall
    arm: Callable[[], SuspendedCall]


@dataclass(frozen=True)
class ConfiguredProvider:
    """A subject with a forecast provider configured, and the facts a suite cannot read.

    Attributes:
        forecaster: The subject, ready to be called.
        origin: The one origin its request names — the harness's, because ADR-0260 §6
            makes it the configured provider's and no member of this Protocol reports
            one.
        latitude: The place its request names, likewise: ADR-0260 §3 holds it in the
            forecaster's own configuration and gives no member that reports it.
        longitude: Likewise.
        declaration: The forecaster's own declaration, which its request carries by
            value. Supplied for the same reason: a suite comparing a request's ``tool``
            against itself would assert nothing.
    """

    forecaster: Forecaster
    origin: str
    latitude: float
    longitude: float
    declaration: ToolDefinition


class ForecasterContract:
    """Behaviour every ``Forecaster`` implementation must exhibit (ADR-0260 §4)."""

    @pytest.fixture
    def forecaster(self) -> Forecaster:
        """Override in a subclass with any conforming subject."""
        raise NotImplementedError

    def days_bound(self) -> int:
        """Override with the ``forecast_max_days`` every subject here carries.

        One figure for the whole harness: every subject the hooks below return must be
        configured with it, since the count case chooses what to prepare from it.
        """
        raise NotImplementedError

    def content_bound(self) -> int:
        """Override with the ``forecast_max_day_chars`` every subject here carries.

        Counted as ADR-0230 §6 counts a fetched document — on the quoted rendering,
        ``json.dumps`` at its default ``ensure_ascii=True``, its two delimiters included
        — which is the measure ADR-0260 §5 adopts by reference.
        """
        raise NotImplementedError

    async def reading(self, days: int) -> ScriptedRead:
        """Override with a subject whose provider answers with ``days`` days.

        ``days`` is what the *provider* returned, before the subject's own bound is
        applied — so a harness asked for more than the count it configured must prepare a
        subject that was offered them, and let the subject drop the excess. A harness that
        clipped ``days`` itself would be answering the question this suite is asking.

        Called once per case that needs it, so each gets a fresh subject.
        """
        raise NotImplementedError

    async def naming_one_day_twice(self) -> ScriptedRead:
        """Override with a subject whose provider names **one** day, twice, and no other.

        Both rows are the provider's own and neither is malformed: what makes them
        droppable is only that they name one day between them. A harness that prepared
        two *different* days, or a day beside a malformed row, would be answering a
        different question — so the subject's whole response is the duplicate pair, and
        the case can then assert the refusal rather than count records.

        Called once per case that needs it, so each gets a fresh subject.
        """
        raise NotImplementedError

    async def refusing(self, refusal: ForecastRefusal) -> ScriptedRefusal:
        """Override with a subject whose read refuses with ``refusal``.

        Called once per case that needs it, and once per member: every member of
        :class:`~ai_assistant.core.types.ForecastRefusal` must be reachable, because
        ADR-0260 §4's posture is that *each* of them is returned rather than raised.
        """
        raise NotImplementedError

    async def gated(self) -> GatedRead:
        """Override with a subject that can be held at its suspension point.

        Called once per case that needs it. See :class:`GatedRead`.
        """
        raise NotImplementedError

    async def configured(self) -> ConfiguredProvider:
        """Override with a subject that has a forecast provider configured."""
        raise NotImplementedError

    async def unconfigured(self) -> Forecaster:
        """Override with a subject built where no forecast provider is configured.

        Unreached by an implementation that sets
        :attr:`constructed_only_with_a_provider`, which then leaves this alone.
        """
        raise NotImplementedError

    #: Whether this implementation's request names no place at all, so that there is
    #: nothing for a caller to name elsewhere. ADR-0260 §3 obliges the forecaster to
    #: read its own configured place and fixes no argument for it, so an implementation
    #: composing the place entirely inside its own request shape satisfies the clause by
    #: construction — which is the shape ``CONTRIBUTING.md`` gives
    #: ``optional_obligation``.
    names_no_place_in_its_request: bool = False

    async def another_declaration(self) -> ScriptedRead:
        """Override with a **fully bound, separately authorised** call carrying a valid
        but different declaration.

        Its id, its origin and its binding are the subject's own; only some field of the
        declaration the policy ruled over differs, and the decision it carries was
        recorded over that very request. Every check but the second therefore passes it.
        """
        raise NotImplementedError

    async def elsewhere(self) -> ScriptedRead:
        """Override with a **fully bound, separately authorised** wrong-place call.

        Its declaration, its origin and its binding are the subject's own; only the
        coordinate differs, and the decision it carries was recorded over that very
        request. Every check but the place's therefore passes it.

        Unreached by an implementation that sets
        :attr:`names_no_place_in_its_request`, which then leaves this alone.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, forecaster: Forecaster) -> None:
        assert isinstance(forecaster, Forecaster)

    # --- the signatures are the seam (ADR-0260 §3, §4) ----------------------

    def test_request_takes_no_parameters_at_all(self, forecaster: Forecaster) -> None:
        """§3: the ask carries nothing, and §4 gives ``request`` no argument for one.

        **This is the clause the whole kind's safety rests on**, and it is checked
        against the **runtime** signature so that an implementation which grew an input
        fails here rather than at a review. There is no parameter through which a caller
        could name a place, widen a horizon or compose a window — so ADR-0231 §1's
        failure mode, a planner-writable field carrying covered content to an egress
        seam, is unreachable rather than forbidden.
        """
        parameters = [
            parameter
            for name, parameter in inspect.signature(type(forecaster).request).parameters.items()
            if name != "self"
        ]

        assert parameters == [], (
            f"Forecaster.request takes no parameters at all (ADR-0260 §3, §4). Got: {parameters!r}"
        )

    def test_read_takes_exactly_one_positional_only_value_parameter(
        self, forecaster: Forecaster
    ) -> None:
        """§4: ``read`` takes a ``ToolCall`` positionally and a ``timeout`` keyword.

        Positional-only for :meth:`QueryComposer.compose`'s reason one seam further out:
        no keyword name of it exists for a caller to pass a second value under, so an
        implementation that wanted a supply, a record or a listing would have to acquire
        it out of band — a different defect in a different place, and one a reviewer of
        ``tools/`` is looking straight at.

        ``VAR_POSITIONAL`` and ``VAR_KEYWORD`` are refused for the same reason a second
        named parameter is: ``read(self, call, /, *args, **kwargs)`` is a caller able to
        widen the input, whatever its first parameter is called.
        """
        parameters = [
            parameter
            for name, parameter in inspect.signature(type(forecaster).read).parameters.items()
            if name != "self" and parameter.kind is not inspect.Parameter.KEYWORD_ONLY
        ]

        assert [parameter.kind for parameter in parameters] == [
            inspect.Parameter.POSITIONAL_ONLY
        ], (
            f"Forecaster.read takes exactly one positional-only value parameter "
            f"(ADR-0260 §4, ADR-0241 §1). Got: {parameters!r}"
        )

    def test_read_takes_one_keyword_only_parameter_named_timeout(
        self, forecaster: Forecaster
    ) -> None:
        """ADR-0241 §1's form exactly: one keyword-only parameter, named ``timeout``.

        Exactly one, because §1's parameter "is a duration and nothing else": a
        forecaster that added a second keyword would be widening the seam ADR-0260 §4
        closes, and one that made ``timeout`` *optional* would be reintroducing the
        spelling for "unbounded" that §1 says the contract does not have — which the
        default check below is what catches.
        """
        keywords = [
            parameter
            for parameter in inspect.signature(type(forecaster).read).parameters.values()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        ]

        assert [parameter.name for parameter in keywords] == ["timeout"], (
            f"Forecaster.read takes exactly one keyword-only parameter, named `timeout` "
            f"(ADR-0241 §1). Got: {keywords!r}"
        )
        assert keywords[0].default is inspect.Parameter.empty, (
            "`timeout` is required and has no default, so there is no spelling for an "
            f"unbounded call (ADR-0241 §1). Got: {keywords[0].default!r}"
        )

    # --- the bound the caller states (ADR-0241 §1, ADR-0260 §4) -------------

    @pytest.mark.parametrize(
        "bound",
        [
            pytest.param(30, id="not-a-timedelta"),
            pytest.param(None, id="none"),
            pytest.param("30s", id="a-string"),
            pytest.param(timedelta(0), id="zero"),
            pytest.param(timedelta(seconds=-1), id="negative"),
            pytest.param(_CannotDescribeItself(), id="a-value-whose-repr-raises"),
        ],
    )
    async def test_a_bound_outside_its_domain_is_refused(self, bound: object) -> None:
        """ADR-0260 §4: a ``timeout`` no implementation could run under.

        **A suite clause, because it is what makes "there is always a bound" true of
        every ``Forecaster`` this system ever wires.** The annotation is not the
        enforcement — the value crosses a Protocol boundary from a possibly untyped
        caller — so each implementation checks it, and each is held to the same domain
        here rather than to whatever its own constructor happened to police.

        Zero and a negative duration are refused rather than treated as instantly
        expired, for ADR-0029 §4's reason: expiry is delivered at an await point, so an
        implementation reading "expired" as "do not call" would be promising something
        the event loop does not keep.

        **What was not touched is each implementation's own arm**: §13(c) asks that
        nothing is revalidated, no credential is read and no channel is opened, and a
        generic suite holds none of those doubles to look at.
        """
        subject = await self.reading(1)

        with pytest.raises(ValueError, match=r"timeout|deadline"):
            await subject.forecaster.read(subject.call, timeout=bound)  # type: ignore[arg-type]  # the annotation is what this case ignores

    async def test_a_read_held_past_its_bound_comes_back_as_an_expiry(self) -> None:
        """ADR-0241 §1 and §4, at the one point a suite can hold a subject open.

        Driven through the same lever ADR-0060's case uses, and for the same reason: only
        the implementation knows where its suspension is, and a bound that expires before
        the subject has demonstrably reached one exercises none of the code that
        classifies an expiry.

        **The wait is real and the bound is a real duration**: a fake clock would assert
        nothing about the property ADR-0260 §13's arm (i) names, which is that a
        deliberately stalled read is *terminated*.
        """
        subject = await self.gated()
        gate = subject.arm()
        call = asyncio.ensure_future(subject.forecaster.read(subject.call, timeout=_SHORT_BOUND))
        await gate.reached()

        await asyncio.sleep(_SHORT_BOUND.total_seconds() * 3)
        gate.release()

        outcome = await asyncio.wait_for(call, _WAIT_SECONDS)
        assert outcome.refusal is ForecastRefusal.DEADLINE_EXPIRED, (
            "a read whose bound expired is `DEADLINE_EXPIRED` and never "
            f"`TRANSPORT_FAILED` (ADR-0241 §4). Got: {outcome.refusal!r}"
        )
        assert outcome.records == ()

    async def test_a_bound_whose_own_arithmetic_lies_is_still_enforced(self) -> None:
        """ADR-0241 §1: the bound is the duration the value carries, not what it reports.

        **A suite clause for the same reason the domain case above is one**: "there is
        always a bound" is a claim about every ``Forecaster`` this system wires, and the
        annotation is not the enforcement — the value crosses a Protocol boundary from a
        possibly untyped caller, and ``isinstance`` admits a subclass. An implementation
        opening its window from ``timeout.total_seconds()`` opens one that never closes,
        which is the spelling for "unbounded" §1 says the contract does not have.

        Driven through the same lever the expiry case uses, because what fails an
        implementation here is a read that is *not* terminated: the subject is held at its
        suspension well past the duration the bound carries, and an implementation that
        trusted the object would still be waiting.
        """
        subject = await self.gated()
        gate = subject.arm()
        call = asyncio.ensure_future(subject.forecaster.read(subject.call, timeout=_LYING_BOUND))
        await gate.reached()

        await asyncio.sleep(_SHORT_BOUND.total_seconds() * 3)
        gate.release()

        outcome = await asyncio.wait_for(call, _WAIT_SECONDS)
        assert outcome.refusal is ForecastRefusal.DEADLINE_EXPIRED, (
            "a bound is the duration `timedelta`'s own fields carry, so a subclass whose "
            f"`total_seconds` lies states 50ms and not forever (ADR-0241 §1). "
            f"Got: {outcome.refusal!r}"
        )

    # --- what a request proposes (ADR-0260 §4) ------------------------------

    #: Whether this implementation has no unconfigured state to exhibit, because it is
    #: constructed only where a provider is configured — which is what ADR-0260 §12
    #: requires of ``app/composition.py``'s wiring. The two clauses are both §4's and
    #: they are not in tension: a deployment that configured nothing holds **no**
    #: concrete forecaster at all, and the ``None`` arm is what a ``Forecaster`` whose
    #: provider can be absent — the canonical fake — answers with. So the obligation is
    #: real and is not every implementation's, which is exactly the shape
    #: ``CONTRIBUTING.md`` gives ``optional_obligation``.
    constructed_only_with_a_provider: bool = False

    @pytest.mark.optional_obligation
    async def test_request_answers_none_where_no_provider_is_configured(self) -> None:
        """§4: ``request`` returns ``None`` "where the deployment has configured no
        forecast provider".

        A configuration fact and never a failure, which is why it is a return value
        rather than a refusal or an exception: nothing is wrong, and there is simply no
        act to rule on. It is also what ``orchestration`` computes
        ``CarriedProvenance.forecast_reach`` from (§11).
        """
        if self.constructed_only_with_a_provider:
            pytest.skip("implementation is constructed only where a provider is configured")

        subject = await self.unconfigured()

        assert await subject.request() is None

    async def test_request_carries_the_declaration_and_exactly_the_configured_place(
        self,
    ) -> None:
        """§4's request clause, whole: the declaration by value, and its own arguments.

        The parameter assertion is over the *values* rather than the key names, which
        ADR-0260 §6 leaves to the integration: what §4 fixes is that the request carries
        this forecaster's declaration and nothing besides its own arguments — no step, no
        execution, and no binding this member has no business deriving.
        """
        subject = await self.configured()

        request = await subject.forecaster.request()

        assert request is not None
        assert request.tool == subject.declaration
        assert sorted(str(value) for value in request.parameters.values()) == sorted(
            [subject.origin, str(subject.latitude), str(subject.longitude)]
        )
        assert request.step_id is None
        assert request.execution_id is None
        assert request.egress_binding is None

    # --- the identity a record is attested to (ADR-0260 §4, §5) -------------

    def test_name_is_non_blank_and_a_value_identifier_accepts_unchanged(
        self, forecaster: Forecaster
    ) -> None:
        """§4's two clauses on ``name``, at the one place they can be read.

        ``Attestation.reported_by`` is typed ``Identifier``, which "refuses a blank value
        **and strips the one it accepts**" — so a forecaster naming itself
        ``" forecast "`` would satisfy every other clause here and yet mint a record whose
        ``reported_by`` is ``"forecast"``, which no equality §5 asserts could hold.
        """
        assert forecaster.name.strip()
        assert forecaster.name.strip() == forecaster.name

    async def test_name_is_the_same_string_before_and_after_every_read(self) -> None:
        """§4: "the same string on every access and across every call".

        Read before and after a call that **succeeds** and again around a call that
        **refuses**, which is §4's clause over the calls a suite can actually make: two
        calls on one subject would need two authorisations, so "across every call" is
        asserted across every call this harness can prepare rather than by driving one
        subject twice.

        An identity that moved under a turn would scatter one source's records across two
        ``reported_by`` values no later fold could bring back together, and a property
        asserted once per subject cannot see it.
        """
        for prepared in (
            await self.reading(1),
            await self.refusing(ForecastRefusal.NO_RESULT),
        ):
            before = prepared.forecaster.name
            await prepared.forecaster.read(prepared.call, timeout=prepared.timeout)

            assert before == prepared.forecaster.name
            assert before.strip() == before
            assert before.strip()

    # --- what an outcome carries (ADR-0260 §4, §5) --------------------------

    async def test_an_outcome_carries_records_or_a_refusal_and_never_both(self) -> None:
        """§4's exactly-one rule, over both of the outcomes a suite can reach.

        The condition is the model's own, so this case cannot fail on a conforming
        *value* — what it fails is a forecaster that never reaches one of the two states,
        which is the half a harness can get wrong.
        """
        succeeding = await self.reading(1)
        refusing = await self.refusing(ForecastRefusal.TRANSPORT_FAILED)

        first = await succeeding.forecaster.read(succeeding.call, timeout=succeeding.timeout)
        second = await refusing.forecaster.read(refusing.call, timeout=refusing.timeout)

        assert bool(first.records) != (first.refusal is not None)
        assert bool(second.records) != (second.refusal is not None)

    async def test_at_most_the_configured_day_count_is_minted(self) -> None:
        """§5: "at most ``forecast_max_days``".

        Driven over a provider answer *larger* than the bound, because a subject offered
        exactly the bound cannot distinguish a forecaster that enforces one from a
        forecaster that has none.

        **Which days those are is not asserted here, and that is deliberate.** §5 makes
        them "the *first* that many in the order the provider returned them", and a
        generic suite cannot tell a subject what order its provider returned anything in
        — so the arm that pins the cap's direction is ADR-0260 §13(b-prime)'s, over the
        production forecaster and a response whose order the case wrote. What a suite
        can hold every implementation to is that the bound binds at all.
        """
        bound = self.days_bound()
        subject = await self.reading(bound + 2)

        outcome = await subject.forecaster.read(subject.call, timeout=subject.timeout)

        assert len(outcome.records) <= bound, _OVER_THE_COUNT.format(
            bound=bound, count=len(outcome.records)
        )
        assert outcome.records

    async def test_a_day_named_twice_is_dropped_in_every_one_of_its_rows(self) -> None:
        """§5: "A day the response names more than once is dropped in **every one of its
        rows**".

        "Whether they agree or conflict: the response has not described that day once,
        and preferring one row over another would be this system deciding what the
        provider said." **That is not a deduplication** — nothing is merged and no row is
        preferred — so a provider naming one day twice and no other has described no day,
        and the read yields ``NO_RESULT`` rather than one record.

        **Asserted over the refusal and not over a record count**, which is what makes it
        stateable for every implementation: an implementation that kept the first row
        would answer with one record, and one that merged them would answer with one
        record too, so the surviving member tells both apart from the clause without this
        suite knowing what either row said.
        """
        subject = await self.naming_one_day_twice()

        outcome = await subject.forecaster.read(subject.call, timeout=subject.timeout)

        assert outcome.refusal is ForecastRefusal.NO_RESULT, _KEPT_A_DUPLICATE.format(
            count=len(outcome.records)
        )
        assert outcome.records == ()

    async def test_every_minted_record_is_an_attested_external_semantic(self) -> None:
        """§5's minting clause, every conjunct a suite can read off a record.

        The ``reported_by`` equality is the one that fails an implementation which put a
        vendor, an origin or a place where §5 puts the source instance; the empty
        ``evidence`` fails one that made a turn-scoped record look like a citation target;
        the fully open ``validity`` fails one that wrote the source's testimony into the
        operational axis, which is the authorship mixing ADR-0117 §2 refuses and which
        would hand ADR-0252 §3's prohibited fallback exactly the value it was written to
        refuse; and the bounded extent is the field the whole decision is bought for.
        """
        subject = await self.reading(self.days_bound())

        outcome = await subject.forecaster.read(subject.call, timeout=subject.timeout)

        assert outcome.records
        for record in outcome.records:
            assert record.kind == "semantic"
            assert record.provenance.source is MemorySource.EXTERNAL
            assert record.provenance.evidence == ()
            assert record.topics == ()
            assert record.about_person is None
            assert record.validity.valid_from is None
            assert record.validity.valid_until is None
            attestation = record.provenance.attestation
            assert attestation is not None
            assert attestation.reported_by == subject.forecaster.name, _MISATTRIBUTED.format(
                name=subject.forecaster.name, got=attestation.reported_by
            )
            extent = attestation.extent
            assert extent is not None, _NO_EXTENT.format(got=extent)
            assert extent.extends_from is not None, _NO_EXTENT.format(got=extent)
            assert extent.extends_until is not None, _NO_EXTENT.format(got=extent)
            assert extent.extends_until > extent.extends_from
            assert len(json.dumps(record.content)) <= self.content_bound()

    async def test_a_record_attested_to_an_undeclared_instant_is_unconstructable(
        self,
    ) -> None:
        """§4: such a ``ForecastOutcome`` is unconstructable.

        Asserted here rather than in a types test because the clause is about what *this*
        seam can emit: the records come from a real subject, and the outcome is rebuilt
        around them with a report instant the response did not declare — which is exactly
        the local substitute ADR-0092 §3 forbids. An implementation that reached for a
        clock of its own fails at the value, not at a review.
        """
        subject = await self.reading(1)
        outcome = await subject.forecaster.read(subject.call, timeout=subject.timeout)
        assert outcome.reported_at is not None

        with pytest.raises(ValidationError):
            ForecastOutcome(
                reported_at=outcome.reported_at.replace(year=outcome.reported_at.year - 1),
                records=outcome.records,
            )

    # --- failure posture (ADR-0260 §4) --------------------------------------

    @pytest.mark.parametrize("refusal", list(ForecastRefusal))
    async def test_read_raises_for_no_source_reason(self, refusal: ForecastRefusal) -> None:
        """§4: "Neither acting member raises for a source reason".

        Parametrised over the whole enumeration rather than over one member, so a seventh
        added without an arm here fails: the clause is about the vocabulary and not about
        an example of it. A forecaster that raised would make ADR-0226 §5's degradation
        posture the servicer's problem to catch correctly at every call site, where a
        closed refusal enumeration makes the non-yield a value the audit can count and the
        turn can ignore.
        """
        subject = await self.refusing(refusal)

        outcome = await subject.forecaster.read(subject.call, timeout=subject.timeout)

        assert outcome.refusal is refusal
        assert outcome.records == ()
        assert outcome.reported_at is None

    # --- the three checks before the send (ADR-0260 §6) ---------------------

    async def test_a_call_mutated_after_construction_is_refused(self) -> None:
        """§6's first check, over every implementation: revalidated and **detached**.

        "So a mutation landed after construction cannot survive into the read."
        ``frozen=True`` refuses ``call.request = …`` and does nothing about
        ``call.__dict__["request"] = …``, and that bypass is inside this repository's
        threat model rather than outside it (ADR-0018 §3). An implementation trusting
        the validator that ran at construction answers the substituted call.

        **A suite clause because §6 puts the checks on ``read``**, not on one
        implementation of it: a fake that answered a call production would refuse would
        let a consumer's test pass over an exchange no deployment can have. What each
        implementation *additionally* owes — that no credential is read and no channel
        is opened — is its own arm, since a generic suite holds no doubles to look at.
        """
        subject = await self.reading(1)
        rewritten = subject.call.request.model_copy(
            update={"parameters": {"nothing": "this schema declares"}}
        )
        subject.call.__dict__["request"] = rewritten

        with pytest.raises(ToolBindingError):
            await subject.forecaster.read(subject.call, timeout=subject.timeout)

    async def test_a_call_carrying_another_declaration_is_refused(self) -> None:
        """§6's second check: compared against the forecaster's **own** declaration.

        The authoritative original here, standing where ADR-0029 §2 puts the registry's,
        because this integration has an egress registration and no registry entry. The
        call the hook supplies is **valid and authorised** — its own decision was
        recorded over its own request, so the third check passes it — which is exactly
        what the second exists to catch: a definition the policy never ruled on,
        reaching a seam that holds a credential. ADR-0018 §4's case, where a declaration
        tampered into a still-valid state carries a ``discloses``, a ``cost`` or a
        ``risk_level`` other than the one the ruling was taken over.

        **The call comes from the harness, and round 4's lesson is why.** A suite that
        built a request for a declaration of its own would produce an *unbound* one,
        which an egress-backed forecaster refuses at ADR-0148 §8's floor before it ever
        compares a definition — so the case would stay green with this check deleted,
        which is what the wrong-place case one arm down was found doing. Only the
        implementation knows how to build a bound call for a declaration its own seam
        will bind.
        """
        subject = await self.another_declaration()

        with pytest.raises(ToolBindingError):
            await subject.forecaster.read(subject.call, timeout=subject.timeout)

    @pytest.mark.optional_obligation
    async def test_a_separately_authorised_call_naming_another_place_is_refused(self) -> None:
        """§3: "the place is the deployment's own configured place", over every
        implementation.

        **The call the hook supplies is entirely valid, and that is the whole of the
        case**: the subject's own declaration, its own origin and its own binding, with
        another coordinate, carried by its **own** recorded ``ALLOW``. So it survives
        revalidation, carries the registered declaration, and its decision authorises
        it — every one of §6's three checks passes — and only a comparison against the
        forecaster's own held configuration stands between it and a read about somewhere
        the deployment did not choose. §3 is absolute that no caller widens, narrows or
        offsets the read, on ADR-0093 §10's ground — "a caller able to widen the read is
        a caller able to defeat the bound".

        **The call comes from the harness rather than from this suite**, and round 4's
        architecture lens is why: a suite that rebuilt the proposal itself would produce
        an *unbound* request, which an egress-backed forecaster refuses at ADR-0148 §8's
        floor before it ever reaches the place — so the case would stay green with the
        place check deleted. Only the implementation knows how to build a fully bound
        call, which is this suite's standing shape for every other clause too.

        **A suite clause because the obligation is the contract's**, not one
        implementation's: a fake answering a call production refuses is one a consumer's
        test can pass against.

        **Optional, because an implementation may carry no place in its request at all**
        — §3 obliges the forecaster to read its own configured place and fixes no
        argument for it, so one that composes the place entirely inside its own request
        shape has nothing to name and satisfies the clause by construction.
        """
        if self.names_no_place_in_its_request:
            pytest.skip("this implementation's request names no place")

        subject = await self.elsewhere()

        with pytest.raises(ToolBindingError):
            await subject.forecaster.read(subject.call, timeout=subject.timeout)

    async def test_a_cancelled_read_is_delivered_onward_unchanged(self) -> None:
        """ADR-0060 through this seam: a cancellation is never absorbed (§4).

        Held at the subject's own suspension point and cancelled *there*, because a call
        cancelled before it suspends exercises none of the code that would convert one.
        This is the place a conforming-looking forecaster satisfies every other clause in
        this file and still gets it wrong — by catching broadly around its provider call
        and returning ``TRANSPORT_FAILED`` for a shutdown that was working correctly.
        """
        subject = await self.gated()
        gate = subject.arm()
        call = asyncio.ensure_future(subject.forecaster.read(subject.call, timeout=A_BOUND))
        await gate.reached()

        call.cancel()
        gate.release()

        with pytest.raises(asyncio.CancelledError):
            await call

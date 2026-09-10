"""Shared conformance suite for the WebSearcher Protocol (ADR-0231 §10, §17).

Every ``WebSearcher`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`WebSearcherContract`,
supplies the ``searcher`` fixture, and overrides the six hooks below.

**Here rather than under ``tests/core/``**, beside ``tool_invoker_contract.py`` and
``egress_binder_contract.py``: ADR-0231 §17 puts the production searcher in
``ai_assistant.tools.egress`` — the module ADR-0154 §1 designates — and this package
is where the suite sits beside it, exactly as the ``QueryComposer`` suite sits beside
the composer in ``tests/planning/``. The ``Fetcher`` suite made the other choice for
a reason that does not hold here: its implementation lives in ``ai_assistant.readers``,
"a package no subsystem may import".

**The hooks are ``async``**, unlike the ``QueryComposer`` suite's: preparing a
subject here means arranging a connected account and a keyring, and a keyring is
written to through an ``async`` seam. A sync hook would have to drive a loop of its
own inside the one the case is already running on.

**Hooks and not one fixture, because the clauses are about answers a suite has to
choose.** "At most the configured result count", "every minted record is attested to
this searcher's name" and "each refusal is returned rather than raised" cannot be
reached by handing an arbitrary searcher an arbitrary call: only the implementation's
own harness knows how to make its subject answer with a given number of results,
refuse with a given class, or accept a call at all — an *authorised* ``ToolCall`` is
not something a suite can build for a subject whose declaration it has never seen. So
the suite asks for a **prepared subject and the call that draws the prepared answer
out of it**, and what it asserts is what came back.

**Both bounds come from the harness, and ADR-0231 §17 says why**: ``search_max_results``
and ``search_max_result_chars`` are ``Settings`` fields "enforced by the searcher,
never by the model", and ``SearchOutcome`` "carries neither bound and validates
identically in every deployment". So there is nothing in the value for a suite to read
either off, and each is a hook of its own rather than a field on a prepared subject,
because the cases that drive them have to know the figure *before* they can say what
answer to prepare.

**What is deliberately not in here.** ADR-0231 §17 names four rulings that would be an
error to put in a suite, and every one of them is absent:

* **That the transport follows no redirect and reaches one origin.** "A generic suite
  cannot make an arbitrary searcher's transport redirect" — those are Lane 2's tests
  over a real exchange.
* **That the declaration is absent from every ``ToolRegistry``.** A property of a
  *composition*, asserted in the wiring's own test where it can be broken.
* **That a real provider failure produces each refusal class.** A suite cannot make an
  arbitrary provider fail, so it pins that each class is *returned* rather than raised,
  and not that ``TRANSPORT_FAILED`` is reached from a refused connection or
  ``UNATTESTED`` from a response carrying no instant. Those are the concrete
  searcher's arms.
* **That the credential is read inside the authorised call and never outside it.** A
  ``Secrets`` face is a constructor's, not a return value's, and no member of this
  Protocol carries one.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
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

from ai_assistant.core.protocols import WebSearcher
from ai_assistant.core.types import MemorySource, SearchOutcome, SearchRefusal

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import ToolCall, ToolDefinition
    from ai_assistant.testing.cancellation import SuspendedCall

#: A query a suite hands a subject where the words themselves do not matter. Every
#: hook is free to ignore it and name its own.
QUERY = "tallest building in porto"

#: The bound every case here passes unless it is about the bound (ADR-0241 §1).
#: Generous enough that no arrangement reaches it by accident, so a case that fails
#: is failing on the clause it is about rather than on a machine's load.
A_BOUND: Final = timedelta(seconds=30)

#: The bound the deadline case sets, small enough that a real wait past it is a
#: fraction of a second. A **real** duration and not a fake clock, because what
#: ADR-0241 §12's Arm 1 asks for is that the search stops waiting, and a fake clock
#: asserts nothing about that.
_SHORT_BOUND: Final = timedelta(milliseconds=50)

#: How long a case will wait for a subject to answer once it has been released.
#: Failing here is a hang, and a hang is what this suite exists to catch.
_WAIT_SECONDS: Final = 5.0

#: What a failure of the result-count case means, in one place (ADR-0231 §5, §10). A
#: searcher that minted more than it was configured for is one whose contribution to
#: ADR-0226 §6's budget of ten is a figure the operator did not set, which is the
#: reason §5 makes three a ceiling the setting narrows and never widens.
_OVER_THE_COUNT = (
    "a search mints at most the `search_max_results` it was configured with "
    "(ADR-0231 §5, §10). Configured for {bound}, got {count}"
)

#: What a failure of the attestation case means (ADR-0231 §10, ADR-0092 §3). The
#: record's ``reported_by`` is the **source instance** and is required to equal the
#: searcher's own ``name``; a producer that put a vendor, an origin or a URL there
#: would be attributing its record to a party this system never spoke to.
_MISATTRIBUTED = (
    "every record a search mints carries an Attestation whose reported_by is the "
    "searcher's own name (ADR-0231 §10, ADR-0092 §3). Expected {name!r}, got {got!r}"
)


@dataclass(frozen=True)
class ScriptedSearch:
    """A subject prepared to answer one particular search, and the call that reaches it.

    Attributes:
        searcher: The subject, ready to be called.
        call: The authorised call that draws the prepared answer out of it.
        timeout: The bound to pass at that call (ADR-0241 §1). Defaults to
            :data:`A_BOUND`, which every answering arrangement fits inside.
    """

    searcher: WebSearcher
    call: ToolCall
    timeout: timedelta = field(default=A_BOUND)


@dataclass(frozen=True)
class ScriptedRefusal:
    """A subject prepared to refuse with one particular class, and how to reach it.

    Attributes:
        searcher: The subject, ready to be called.
        call: The authorised call that draws the prepared refusal out of it.
        timeout: The bound to pass at that call. Defaults to :data:`A_BOUND`, and is
            a field rather than a constant because one member — ADR-0241 §4's
            :attr:`~ai_assistant.core.types.SearchRefusal.DEADLINE_EXPIRED` — is
            reached by the bound itself expiring, so the harness that arranges a real
            cause for it is the party that knows which bound reaches it. A harness
            scripting that member directly leaves this alone.
    """

    searcher: WebSearcher
    call: ToolCall
    timeout: timedelta = field(default=A_BOUND)


@dataclass(frozen=True)
class GatedSearch:
    """One subject that can be held inside its search, plus the lever.

    What ADR-0060's case needs from an implementation, and no more. The property has
    no positive signal through the member alone: a suite has to hold a call open at a
    point it has demonstrably reached, cancel it *there*, and see what comes back —
    and only the implementation knows where its suspension is. A call cancelled
    *before* it suspends exercises none of the code an implementation would use to
    catch a ``CancelledError`` during a provider call and convert it into a refusal,
    so a suite without this lever reports the property as held while testing nothing.

    Attributes:
        searcher: The subject, ready to be called.
        call: The authorised call to make.
        arm: Arms the **next** ``search`` to suspend, and returns the handle the
            suite waits on and releases.
    """

    searcher: WebSearcher
    call: ToolCall
    arm: Callable[[], SuspendedCall]


@dataclass(frozen=True)
class ConnectedAccount:
    """A subject with a search account connected, and the two facts about it a suite
    cannot read off a return value.

    Attributes:
        searcher: The subject, ready to be called.
        origin: The one origin its request names — the harness's, because ADR-0231 §5
            makes it "the connected account's configuration" and no member of this
            Protocol reports one.
        declaration: The searcher's own declaration, which its request carries by
            value. Supplied for the same reason: a suite comparing a request's
            ``tool`` against itself would assert nothing.
    """

    searcher: WebSearcher
    origin: str
    declaration: ToolDefinition


class WebSearcherContract:
    """Behaviour every ``WebSearcher`` implementation must exhibit (ADR-0231 §17)."""

    @pytest.fixture
    def searcher(self) -> WebSearcher:
        """Override in a subclass with any conforming subject."""
        raise NotImplementedError

    def results_bound(self) -> int:
        """Override with the ``search_max_results`` every subject here carries.

        One figure for the whole harness: every subject the hooks below return must
        be configured with it, since the count case chooses what to prepare from it.
        """
        raise NotImplementedError

    def content_bound(self) -> int:
        """Override with the ``search_max_result_chars`` every subject here carries.

        Counted as ADR-0230 §6 counts a fetched document — on the quoted rendering,
        ``json.dumps`` at its default ``ensure_ascii=True``, its two delimiters
        included — which is the measure ADR-0231 §10 adopts by reference.
        """
        raise NotImplementedError

    async def searching(self, results: int) -> ScriptedSearch:
        """Override with a subject whose provider answers with ``results`` results.

        ``results`` is what the *provider* returned, before the subject's own bound
        is applied — so a harness asked for more than the count it configured must
        prepare a subject that was offered them, and let the subject drop the excess.
        A harness that clipped ``results`` itself would be answering the question
        this suite is asking.

        Called once per case that needs it, so each gets a fresh subject.
        """
        raise NotImplementedError

    async def refusing(self, refusal: SearchRefusal) -> ScriptedRefusal:
        """Override with a subject whose search refuses with ``refusal``.

        Called once per case that needs it, and once per member: every member of
        :class:`~ai_assistant.core.types.SearchRefusal` must be reachable, because
        ADR-0231 §17's posture is that *each* of them is returned rather than raised.
        """
        raise NotImplementedError

    async def gated(self) -> GatedSearch:
        """Override with a subject that can be held at its suspension point.

        Called once per case that needs it. See :class:`GatedSearch`.
        """
        raise NotImplementedError

    async def connected(self) -> ConnectedAccount:
        """Override with a subject that has a search account connected."""
        raise NotImplementedError

    async def unconnected(self) -> WebSearcher:
        """Override with a subject built where no search account is connected.

        Unreached by an implementation that sets
        :attr:`constructed_only_with_an_account`, which then leaves this alone.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, searcher: WebSearcher) -> None:
        assert isinstance(searcher, WebSearcher)

    # --- the signatures are the seam (ADR-0231 §17) -------------------------

    @pytest.mark.parametrize("member", ["request", "search"])
    def test_each_acting_member_takes_exactly_one_positional_value_parameter(
        self, searcher: WebSearcher, member: str
    ) -> None:
        """§17: "Both value parameters are **positional-only**".

        For :meth:`~ai_assistant.core.protocols.QueryComposer.compose`'s reason, one
        seam further out: no keyword name of either exists for a caller to pass a
        second value under, so an implementation that wanted a supply, a record or a
        listing would have to acquire it out of band — a different defect in a
        different place, and one a reviewer of ``tools/`` is looking straight at.

        ``VAR_POSITIONAL`` and ``VAR_KEYWORD`` are refused for the same reason a
        second named parameter is: ``search(self, call, /, *args, **kwargs)`` is a
        caller able to widen the input, whatever its first parameter is called.

        **This half is unchanged by ADR-0241 §1** — ``call`` stays positional-only,
        and the duration it adds is keyword-only and is not a value parameter. The
        no-keyword-parameters half, which this case used to assert of *both* members,
        is now :meth:`test_request_takes_no_keyword_parameters`' alone; ``search``'s
        own shape is :meth:`test_search_takes_one_keyword_only_parameter_named_timeout`.
        """
        parameters = [
            parameter
            for name, parameter in inspect.signature(
                getattr(type(searcher), member)
            ).parameters.items()
            if name != "self" and parameter.kind is not inspect.Parameter.KEYWORD_ONLY
        ]

        assert [parameter.kind for parameter in parameters] == [
            inspect.Parameter.POSITIONAL_ONLY
        ], (
            f"WebSearcher.{member} takes exactly one positional-only value parameter "
            f"(ADR-0231 §17, ADR-0241 §1). Got: {parameters!r}"
        )

    def test_request_takes_no_keyword_parameters(self, searcher: WebSearcher) -> None:
        """§17's no-keyword clause, now over ``request`` alone (ADR-0241 §14).

        ADR-0241 §1 gives ``search`` exactly one keyword-only parameter and moves
        ADR-0231 §17's exact-signature declaration *for that member alone*;
        ``request``'s signature is untouched, and this case is what keeps that true
        rather than being relaxed alongside its sibling's.
        """
        parameters = [
            parameter
            for name, parameter in inspect.signature(type(searcher).request).parameters.items()
            if name != "self"
        ]

        assert all(
            parameter.kind is inspect.Parameter.POSITIONAL_ONLY for parameter in parameters
        ), f"WebSearcher.request takes no keyword parameters (ADR-0231 §17). Got: {parameters!r}"

    def test_search_takes_one_keyword_only_parameter_named_timeout(
        self, searcher: WebSearcher
    ) -> None:
        """ADR-0241 §12's Arm 7: exactly one keyword-only parameter, named ``timeout``.

        Checked against the **runtime** signature, so an implementation that grew a
        second input fails here rather than at a review. Exactly one, because §1's
        parameter "is a duration and nothing else": a searcher that added a second
        keyword would be widening the seam ADR-0231 §17 closes, and one that made
        ``timeout`` *optional* would be reintroducing the spelling for "unbounded"
        that §1 says the contract does not have — which the default check below is
        what catches.
        """
        keywords = [
            parameter
            for parameter in inspect.signature(type(searcher).search).parameters.values()
            if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        ]

        assert [parameter.name for parameter in keywords] == ["timeout"], (
            f"WebSearcher.search takes exactly one keyword-only parameter, named "
            f"`timeout` (ADR-0241 §1). Got: {keywords!r}"
        )
        assert keywords[0].default is inspect.Parameter.empty, (
            "`timeout` is required and has no default, so there is no spelling for "
            f"an unbounded call (ADR-0241 §1). Got: {keywords[0].default!r}"
        )

    # --- the bound the caller states (ADR-0241 §1, §12's Arms 6 and 1) ------

    @pytest.mark.parametrize(
        "bound",
        [
            pytest.param(30, id="not-a-timedelta"),
            pytest.param(None, id="none"),
            pytest.param("30s", id="a-string"),
            pytest.param(timedelta(0), id="zero"),
            pytest.param(timedelta(seconds=-1), id="negative"),
        ],
    )
    async def test_a_bound_outside_its_domain_is_refused(self, bound: object) -> None:
        """ADR-0241 §12's Arm 6: a ``timeout`` no implementation could run under.

        **A suite clause, because it is what makes "there is always a bound" true of
        every ``WebSearcher`` this system ever wires** (§12). The annotation is not
        the enforcement — the value crosses a Protocol boundary from a possibly
        untyped caller — so each implementation checks it, and each is held to the
        same domain here rather than to whatever its own constructor happened to
        police.

        Zero and a negative duration are refused rather than treated as instantly
        expired, for ADR-0029 §4's reason: expiry is delivered at an await point, so
        an implementation reading "expired" as "do not call" would be promising
        something the event loop does not keep.

        **What was *not* touched is each implementation's own arm**, not this one's:
        §12 asks that nothing is revalidated, no credential is read, no gate is
        consulted, no claim is appended and no channel is opened, and a generic suite
        holds none of those doubles to look at.
        """
        subject = await self.searching(1)

        with pytest.raises(ValueError, match=r"timeout|deadline"):
            await subject.searcher.search(subject.call, timeout=bound)  # type: ignore[arg-type]  # the annotation is what this case ignores

    async def test_a_search_held_past_its_bound_comes_back_as_an_expiry(self) -> None:
        """ADR-0241 §1 and §4, at the one point a suite can hold a subject open.

        Driven through the same lever ADR-0060's case uses, and for the same reason:
        only the implementation knows where its suspension is, and a bound that
        expires before the subject has demonstrably reached one exercises none of the
        code that classifies an expiry.

        **The wait is real and the bound is a real duration** (§12's Arm 1): a fake
        clock would assert nothing about the property the milestone's acceptance
        sentence names, which is that a deliberately stalled search is *terminated*.

        **The release is what makes the answer observable, not what produces it.**
        ``LoopSuspension`` defers a cancellation until the work it models has
        finished — ADR-0054's shape, which the fake exists to reproduce — so the
        deadline fires while the subject is held and the classification is delivered
        once the modelled work lets go. That is ADR-0241 §7's "the deadline stops the
        waiting, not the work" made observable rather than asserted.
        """
        subject = await self.gated()
        gate = subject.arm()
        call = asyncio.ensure_future(subject.searcher.search(subject.call, timeout=_SHORT_BOUND))
        await gate.reached()

        await asyncio.sleep(_SHORT_BOUND.total_seconds() * 3)
        gate.release()

        outcome = await asyncio.wait_for(call, _WAIT_SECONDS)
        assert outcome.refusal is SearchRefusal.DEADLINE_EXPIRED, (
            "a search whose bound expired is `DEADLINE_EXPIRED` and never "
            f"`TRANSPORT_FAILED` (ADR-0241 §4). Got: {outcome.refusal!r}"
        )
        assert outcome.records == ()

    # --- what a request proposes (ADR-0231 §17) -----------------------------

    #: Whether this implementation has no unconnected state to exhibit, because it
    #: is constructed only where an account is connected — which is what ADR-0231
    #: §17 requires of ``app/composition.py``'s wiring in terms ("constructs a
    #: searcher only where an account is connected"). The two clauses are both §17's
    #: and they are not in tension: a deployment that connected nothing holds **no**
    #: concrete searcher at all, and the ``None`` arm is what a ``WebSearcher`` whose
    #: account can be absent — the canonical fake, or a later one holding several —
    #: answers with. So the obligation is real and is not every implementation's,
    #: which is exactly the shape ``CONTRIBUTING.md`` gives ``optional_obligation``.
    constructed_only_with_an_account: bool = False

    @pytest.mark.optional_obligation
    async def test_request_answers_none_where_no_account_is_connected(self) -> None:
        """§17: ``request`` returns ``None`` "where the deployment has connected no
        search account".

        A configuration fact and never a failure, which is why it is a return value
        rather than a refusal or an exception: nothing is wrong, and there is simply
        no act to rule on.
        """
        if self.constructed_only_with_an_account:
            pytest.skip("implementation is constructed only where an account is connected")

        subject = await self.unconnected()

        assert await subject.request(QUERY) is None

    async def test_request_carries_the_declaration_and_exactly_the_origin_and_query(
        self,
    ) -> None:
        """§17's request clause, whole: the declaration by value, and two arguments.

        The parameter assertion is over the *values* rather than the key names, which
        ADR-0231 §5 leaves to the integration ("which parameter names … are the
        integration's own"): what §17 fixes is that the request carries "exactly the
        origin and the query it was given" and nothing besides — no step, no
        execution, and no binding this member has no business deriving (§6).
        """
        subject = await self.connected()

        request = await subject.searcher.request(QUERY)

        assert request is not None
        assert request.tool == subject.declaration
        assert sorted(str(value) for value in request.parameters.values()) == sorted(
            [subject.origin, QUERY]
        )
        assert len(request.parameters) == 2
        assert request.step_id is None
        assert request.execution_id is None
        assert request.egress_binding is None

    # --- the identity a record is attested to (ADR-0231 §10, §17) -----------

    def test_name_is_non_blank_and_a_value_identifier_accepts_unchanged(
        self, searcher: WebSearcher
    ) -> None:
        """§17's two clauses on ``name``, at the one place they can be read.

        ``Attestation.reported_by`` is typed ``Identifier``, which "refuses a blank
        value **and strips the one it accepts**" — so a searcher naming itself
        ``" search "`` would satisfy every other clause here and yet mint a record
        whose ``reported_by`` is ``"search"``, which no equality §10 asserts could
        hold.
        """
        assert searcher.name.strip()
        assert searcher.name.strip() == searcher.name

    async def test_name_is_the_same_string_before_and_after_every_search(self) -> None:
        """§17: "the same string on every access and across every call".

        Read before and after a call that **succeeds** and again around a call that
        **refuses**, which is §17's clause over the calls a suite can actually make:
        two calls on one subject would need two authorisations, since ADR-0192 §1
        spends one on the claim — so "across every call" is asserted across every call
        this harness can prepare rather than by driving one subject twice.

        An identity that moved under a turn would scatter one source's records across
        two ``reported_by`` values no later fold could bring back together, and a
        property asserted once per subject cannot see it.
        """
        for prepared in (
            await self.searching(1),
            await self.refusing(SearchRefusal.NO_RESULT),
        ):
            before = prepared.searcher.name
            await prepared.searcher.search(prepared.call, timeout=prepared.timeout)

            assert before == prepared.searcher.name
            assert before.strip() == before
            assert before.strip()

    # --- what an outcome carries (ADR-0231 §10, §17) ------------------------

    async def test_an_outcome_carries_records_or_a_refusal_and_never_both(self) -> None:
        """§17's exactly-one rule, over both of the outcomes a suite can reach.

        The condition is the model's own, so this case cannot fail on a conforming
        *value* — what it fails is a searcher that never reaches one of the two
        states, which is the half a harness can get wrong.
        """
        succeeding = await self.searching(1)
        refusing = await self.refusing(SearchRefusal.TRANSPORT_FAILED)

        first = await succeeding.searcher.search(succeeding.call, timeout=succeeding.timeout)
        second = await refusing.searcher.search(refusing.call, timeout=refusing.timeout)

        assert bool(first.records) != (first.refusal is not None)
        assert bool(second.records) != (second.refusal is not None)

    async def test_at_most_the_configured_result_count_is_minted(self) -> None:
        """§17: "at most the result count the implementation under test was configured
        with".

        Driven over a provider answer *larger* than the bound, because a subject
        offered exactly the bound cannot distinguish a searcher that enforces one
        from a searcher that has none.
        """
        bound = self.results_bound()
        subject = await self.searching(bound + 2)

        outcome = await subject.searcher.search(subject.call, timeout=subject.timeout)

        assert len(outcome.records) <= bound, _OVER_THE_COUNT.format(
            bound=bound, count=len(outcome.records)
        )
        assert outcome.records

    async def test_every_minted_record_is_an_attested_external_semantic(self) -> None:
        """§17's minting clause, every conjunct of it.

        The ``reported_by`` equality is the one that fails an implementation which put
        a vendor, an origin or a URL where §10 puts the source instance; the empty
        ``evidence`` fails one that made a turn-scoped record look like a citation
        target (§16); and the content bound fails one that let a result through the
        prompt-facing bound its operator set.
        """
        subject = await self.searching(self.results_bound())

        outcome = await subject.searcher.search(subject.call, timeout=subject.timeout)

        assert outcome.records
        for record in outcome.records:
            assert record.kind == "semantic"
            assert record.provenance.source is MemorySource.EXTERNAL
            assert record.provenance.evidence == ()
            attestation = record.provenance.attestation
            assert attestation is not None
            assert attestation.reported_by == subject.searcher.name, _MISATTRIBUTED.format(
                name=subject.searcher.name, got=attestation.reported_by
            )
            assert len(json.dumps(record.content)) <= self.content_bound()

    async def test_a_record_attested_to_an_undeclared_instant_is_unconstructable(
        self,
    ) -> None:
        """§17: such a ``SearchOutcome`` "is unconstructable".

        Asserted here rather than in a types test because the clause is about what
        *this* seam can emit: the records come from a real subject, and the outcome
        is rebuilt around them with a report instant the response did not declare —
        which is exactly the local substitute ADR-0092 §3 forbids. An implementation
        that reached for a clock of its own fails at the value, not at a review.
        """
        subject = await self.searching(1)
        outcome = await subject.searcher.search(subject.call, timeout=subject.timeout)
        assert outcome.reported_at is not None

        with pytest.raises(ValidationError):
            SearchOutcome(
                reported_at=outcome.reported_at.replace(year=outcome.reported_at.year - 1),
                records=outcome.records,
            )

    # --- failure posture (ADR-0231 §17) -------------------------------------

    @pytest.mark.parametrize("refusal", list(SearchRefusal))
    async def test_search_raises_for_no_source_reason(self, refusal: SearchRefusal) -> None:
        """§17: "``search`` raises for no source reason".

        Parametrised over the whole enumeration rather than over one member, so a
        seventh added without an arm here fails: the clause is about the vocabulary
        and not about an example of it. A searcher that raised would make ADR-0226
        §5's degradation posture the servicer's problem to catch correctly at every
        call site, where a closed refusal enumeration makes the non-yield a value the
        audit can count and the turn can ignore.
        """
        subject = await self.refusing(refusal)

        outcome = await subject.searcher.search(subject.call, timeout=subject.timeout)

        assert outcome.refusal is refusal
        assert outcome.records == ()
        assert outcome.reported_at is None

    async def test_a_cancelled_search_is_delivered_onward_unchanged(self) -> None:
        """ADR-0060 through this seam: a cancellation is never absorbed (§17).

        Held at the subject's own suspension point and cancelled *there*, because a
        call cancelled before it suspends exercises none of the code that would
        convert one. This is the place a conforming-looking searcher satisfies every
        other clause in this file and still gets it wrong — by catching broadly around
        its provider call and returning ``TRANSPORT_FAILED`` for a shutdown that was
        working correctly.
        """
        subject = await self.gated()
        gate = subject.arm()
        call = asyncio.ensure_future(subject.searcher.search(subject.call, timeout=A_BOUND))
        await gate.reached()

        call.cancel()
        gate.release()

        with pytest.raises(asyncio.CancelledError):
            await call

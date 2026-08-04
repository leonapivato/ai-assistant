"""Shared conformance suite for the AssistantEngine Protocol.

Every ``AssistantEngine`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`AssistantEngineContract` and overrides its four fixtures.

**This suite is why the Protocol is worth having.** ADR-0084 §4 promotes the
engine surface so that a client over a transport and the in-process engine are
substitutable, and it names six clauses that *no type expresses* — ADR-0085's
Consequences list them. Every one of them is a way two implementations could
answer the same call differently while both looking correct, so each is asserted
here rather than left to each implementation's own tests:

1. **The page-size default is normative** (§3a). A default in a ``Protocol``
   signature binds nobody; a client defaulting to 100 against an engine defaulting
   to 50 returns a different page for one call.
2. **Every identifier argument is validated *and normalised* before any I/O**
   (§3c). The normalisation is the load-bearing half: without it ``belief(" x ")``
   answers ``None`` in-process and finds the record over a wire client that
   deserialises through ``Identifier``.
3. **The two filters are materialised before the first ``await``** (§3d).
4. **A malformed page argument and a blank identifier are refused locally** (§9),
   so neither implementation is silently more permissive.
5. **The size limit is enforced in both directions** (§8c) — an oversized result
   coming back is refused exactly as an oversized argument going in.
6. **An error type's structured state round-trips through its own constructor**
   (§10a), with ``details_elided`` marking a reconstruction that lost it.

Two shapes the *types* enforce are asserted too, because a suite that only tested
prose would leave a reader unsure whether the guarantee exists: the listing
returns :class:`~ai_assistant.core.types.BeliefSummary` and therefore cannot ship
a citation's content (§4a), and every enumeration returns a tuple (§3b).

**The grant surface adds a second list of behavioural clauses** (ADR-0102 §12
item 2): "the ``AssistantEngine`` conformance suite gains a clause per ruling above
that a store cannot exhibit, which is the whole of §4, §5 and §10's local-refusal
clause". They live here for the same reason the six above do — each is a way two
implementations could answer one call differently while both looking correct — and
two of them are worth naming as the ones nothing else would catch. A ``source``
differing from a held reader's name only by whitespace must be **refused rather
than matched**, which the wire implementation alone could have got wrong, since it
validates each argument against the Protocol's own annotation before dispatch. And
a grant revoked by a record timestamped *earlier* than itself must read as
withdrawn, which an implementation deriving liveness from a time-ordered page gets
wrong on the one deployment where a clock moved.

**Lifecycle is deliberately not asserted.** ``start`` and ``aclose`` are not on
the Protocol (ADR-0084 §5, ADR-0083 §8) — a client that could call ``aclose()``
could shut down the hub from a spoke — so an implementation without a lifecycle
conforms, and this suite must never reach for one.

**``RuntimeError`` on a shutting-down engine is likewise not required** (ADR-0085
§1): it is a property of one object's lifecycle rather than of the contract, and a
client never observes it.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core import errors as error_module
from ai_assistant.core.errors import (
    AssistantError,
    InvalidGrantError,
    OversizedValueError,
    UngrantableSourceError,
    UnknownContinuationError,
    UnknownConversationError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    AnswerKind,
    BeliefBand,
    BeliefSummary,
    ContinuationToken,
    Disposition,
    FeedbackEvent,
    FeedbackKind,
    GrantScope,
    MemoryKind,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: A generous per-turn budget: nothing in this suite is about a deadline.
_PATIENT = timedelta(seconds=30)

#: A limit large enough that an ordinary ``learn`` call — argument *and* result —
#: fits inside it, and small enough that a handful of stored beliefs does not.
#:
#: **Both halves matter.** Too small and every call is refused on its arguments,
#: which is how a suite ends up "testing" result enforcement with a case that never
#: reaches a result: with a 64-byte limit a ``learn`` whose event carries any
#: content at all is refused before the write, so an implementation that had removed
#: its result check entirely would still pass. At 512 the argument object of every
#: setup call is comfortably inside the bound and only the *page* crosses it.
_TINY_LIMIT = 512

#: The one grantable identity every ``granting_engine`` fixture holds. A declared
#: constant, which is what a reader's ``name`` is (ADR-0093 §7) and therefore what
#: the admissible set is made of.
_SOURCE = "calendar"


def _feedback(content: str) -> FeedbackEvent:
    """One piece of feedback, as an adapter hands it over."""
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=MemoryKind.SEMANTIC,
        content=content,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


class AssistantEngineContract(ABC):
    """What every ``AssistantEngine`` implementation must do."""

    @pytest.fixture
    @abstractmethod
    def engine(self) -> AssistantEngine:
        """The subject, at its ordinary contract limit."""

    @pytest.fixture
    @abstractmethod
    def tiny_engine(self) -> AssistantEngine:
        """The same implementation, with the contract limit set to :data:`_TINY_LIMIT`.

        A separate subject rather than a knob on the first, because the limit is a
        construction-time property of an implementation — a deployment's frame size
        — and not something a caller changes mid-flight.
        """

    @pytest.fixture
    @abstractmethod
    def granting_engine(self) -> AssistantEngine:
        """A subject holding **exactly one** grantable source, named :data:`_SOURCE`.

        A separate subject rather than a step in a test, for ``parked_engine``'s
        reason: which sources exist is a property of what the composition root
        *built* (ADR-0102 §7), not something the surface can be asked to change. An
        implementation has to be handed to the suite already holding one.

        It must hold no grant on that source, so the first ``grant`` in each test
        below is the first grant. It must carry a configured location for it, so
        §6's disclosure is a value a client can render.
        """

    @pytest.fixture
    @abstractmethod
    def back_dated_engine(self) -> AssistantEngine:
        """:attr:`granting_engine`'s subject, whose clock runs **backwards**.

        Each record it mints is stamped *earlier* than the one before, so a
        ``grant`` followed by a ``revoke`` produces the pair ADR-0102 §12's
        normative clause requires: a revocation whose ``decided_at`` predates the
        grant it revokes.

        **A fixture because no sequence of surface calls can produce it.** ADR-0102
        §5 puts the clock on the implementation and keeps it away from every client,
        which is what stops a caller backdating a user act — so the only way to
        reach the state ADR-0097 §4 explicitly permits is to hand an implementation
        a clock that has been corrected backwards, which is exactly the deployment
        the clause is about.
        """

    @pytest.fixture
    @abstractmethod
    def parked_engine(self) -> AssistantEngine:
        """A subject holding **exactly one** answerable parked confirmation.

        The resume path cannot be reached by calling the surface: parking is the
        *policy's* ruling, reached inside a turn, so an implementation has to be
        handed to the suite already in that state. It is a fixture rather than a
        step in a test for that reason — and it is the shape ADR-0042 §4's whole
        park/render/relay sequence depends on, so a suite that skipped it would
        leave a client with no shared account of the one interaction a human is in
        the middle of.
        """

    # --- the shape of the surface -----------------------------------------

    def test_it_satisfies_the_protocol(self, engine: AssistantEngine) -> None:
        """Structurally, at runtime — not merely by a type checker's reading."""
        assert isinstance(engine, AssistantEngine)

    def test_lifecycle_is_not_part_of_the_contract(self, engine: AssistantEngine) -> None:
        """ADR-0083 §8: an implementation without a lifecycle conforms.

        Asserted over the **Protocol** rather than over the subject, because a
        concrete engine may legitimately keep both methods — a Protocol constrains
        what an implementation must have, not what it may not. What must stay true
        is that nothing here obliges a client to have them, since a client that
        could call ``aclose()`` could shut down the hub from a spoke.
        """
        surface = {name for name in dir(AssistantEngine) if not name.startswith("_")}
        assert "start" not in surface
        assert "aclose" not in surface

    async def test_every_enumeration_returns_a_tuple(self, engine: AssistantEngine) -> None:
        """ADR-0085 §3b: a caller that mutated a returned page changed nothing.

        ``pending_confirmations`` is the one this pins: it returned a ``list``
        before, and a surface this size with one method returning a mutable
        page is a wart a spoke author has to remember.
        """
        assert isinstance(await engine.beliefs(), tuple)
        assert isinstance(await engine.questions(), tuple)
        assert isinstance(await engine.interrupted_questions(), tuple)
        assert isinstance(await engine.recent_conversations(), tuple)
        assert isinstance(await engine.pending_confirmations(), tuple)

    # --- clause 1: the page-size default is normative (§3a) ----------------

    @pytest.mark.parametrize(
        "method",
        ["beliefs", "questions", "interrupted_questions", "recent_conversations"],
    )
    def test_the_page_size_default_is_the_declared_one(
        self, engine: AssistantEngine, method: str
    ) -> None:
        """All four paging signatures default to ``DEFAULT_PAGE_SIZE``.

        Read off the signature rather than by counting a page, because the property
        is about what "not passed" *means*: an implementation whose own default were
        100 would return a different page for the same call, which is the divergence
        the limit was moved into the contract to prevent, arriving one field over.
        """
        parameter = inspect.signature(getattr(engine, method)).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    async def test_calling_without_a_limit_behaves_as_though_the_default_was_passed(
        self, engine: AssistantEngine
    ) -> None:
        """The clause itself, not merely the signature that advertises it."""
        assert await engine.beliefs() == await engine.beliefs(limit=DEFAULT_PAGE_SIZE)
        assert await engine.questions() == await engine.questions(limit=DEFAULT_PAGE_SIZE)
        assert await engine.interrupted_questions() == await engine.interrupted_questions(
            limit=DEFAULT_PAGE_SIZE
        )
        assert await engine.recent_conversations() == await engine.recent_conversations(
            limit=DEFAULT_PAGE_SIZE
        )

    # --- clause 2 and 4: identifiers (§3c, §9) -----------------------------

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    @pytest.mark.parametrize(
        "call",
        [
            "belief",
            "forget",
            "forget_question",
            "conversation",
            "forget_conversation",
        ],
    )
    async def test_a_blank_identifier_is_refused_locally(
        self, engine: AssistantEngine, call: str, blank: str
    ) -> None:
        """A blank id satisfies "an id is present" while identifying nothing.

        ``ValueError`` and deliberately not an
        :class:`~ai_assistant.core.errors.AssistantError`: it is a caller
        programming error rather than a condition of the system. Refused *before any
        I/O*, so a wire client refuses the same values without a round trip.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(engine, call)(blank)

    async def test_a_blank_identifier_is_refused_on_the_keyword_selectors(
        self, engine: AssistantEngine
    ) -> None:
        """The two methods whose identifier is a keyword-only selector."""
        with pytest.raises(ValueError, match=r"\w"):
            await engine.converse("hello", timeout=_PATIENT, conversation_id="  ")
        with pytest.raises(ValueError, match=r"\w"):
            await engine.observe(conversation_id="  ")
        with pytest.raises(ValueError, match=r"\w"):
            await engine.answer("  ", accept=True)

    async def test_an_identifier_is_stripped_before_it_is_used(
        self, engine: AssistantEngine
    ) -> None:
        """§3c's load-bearing half: the *normalisation*, not only the refusal.

        A rule that said "reject blank" would leave stripping optional, and optional
        normalisation on an **identity** argument is worse than none: it makes the
        answer to ``belief(" rec-1 ")`` a property of which implementation you are
        holding. A wire client deserialising its arguments through ``Identifier``
        would find the record; an in-process engine handed the raw ``str`` would
        look up ``" rec-1 "`` and answer ``None``.
        """
        outcome = await engine.learn(_feedback("the office is in Boston"))
        record_id = outcome.results[0].record_id
        assert record_id is not None
        assert await engine.belief(f"  {record_id}  ") is not None

    @pytest.mark.parametrize("bad", [-1, 2**63])
    @pytest.mark.parametrize("argument", ["limit", "offset"])
    @pytest.mark.parametrize(
        "method", ["beliefs", "questions", "interrupted_questions", "recent_conversations"]
    )
    async def test_a_malformed_page_argument_is_refused_locally(
        self, engine: AssistantEngine, method: str, argument: str, bad: int
    ) -> None:
        """Refused rather than clamped (ADR-0073 §2), and before any I/O (§9)."""
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(engine, method)(**{argument: bad})

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    @pytest.mark.parametrize("argument", ["limit", "offset"])
    @pytest.mark.parametrize(
        "method", ["beliefs", "questions", "interrupted_questions", "recent_conversations"]
    )
    async def test_a_page_argument_that_is_not_an_integer_is_refused_locally(
        self, engine: AssistantEngine, method: str, argument: str, bad: object
    ) -> None:
        """The type, checked before the range and before any I/O.

        ``0 <= 1.5 < 2**63`` is *true*, so a range check alone lets a float through
        to the store, where it fails inside slice arithmetic — after I/O has begun,
        as a ``TypeError`` from somewhere the caller cannot place, and differently
        per implementation. ``True`` is worse: it is an ``int``, so it would be
        accepted and silently mean a page size of one, which is a wrong answer
        rather than a refusal.

        A wire client decoding a JSON ``1.5`` for ``limit`` meets the same value,
        which is why this is a contract clause and not one implementation's input
        hygiene.
        """
        with pytest.raises(TypeError, match=r"\w"):
            await getattr(engine, method)(**{argument: bad})

    # --- clause 3: the filters are materialised (§3d) ----------------------

    async def test_the_filters_are_materialised_before_the_first_await(
        self, engine: AssistantEngine
    ) -> None:
        """A caller that mutates the sequence mid-call cannot change its page (§3d).

        **The mutation has to land after the call has begun**, and getting that
        window right is the whole of the test. ADR-0065 is explicit that the
        boundary is "the coroutine's **first executed line**, not the call
        expression": calling an ``async def`` only builds a coroutine, so a
        mutation made between construction and the first ``await`` is captured
        whole and is *not* a tear — no invocation-time capture is claimed. So the
        call is scheduled and given a turn of the loop before the list is cleared,
        which puts the mutation squarely in the window §3d protects.

        An implementation that read ``bands`` after suspending would see the
        emptied list and return an empty page. :func:`page_after_mutating_the_filter`
        is shared with ``test_fake_engine``'s discrimination case, which runs it
        against a deliberately lazy subject and watches this assertion fail.
        """
        await engine.learn(_feedback("the office is in Boston"))
        page, control = await page_after_mutating_the_filter(engine)
        assert page == control

    async def test_an_empty_filter_selects_nothing_and_none_selects_everything(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0073 §2: ``None`` and empty are different answers, not one.

        The pair matters because a client serialising a ``None`` filter as an empty
        JSON array would turn "every band" into "no band" — a silently empty page
        for a call that asked for everything.
        """
        await engine.learn(_feedback("the office is in Boston"))
        assert await engine.beliefs(bands=[]) == ()
        assert await engine.beliefs(kinds=[]) == ()
        assert await engine.beliefs(bands=None, kinds=None) != ()

    # --- clause 5: the size limit, in both directions (§8c) ----------------

    async def test_an_oversized_argument_is_refused(self, tiny_engine: AssistantEngine) -> None:
        """The *going in* direction: refused before dispatch, with the number."""
        with pytest.raises(OversizedValueError) as caught:
            await tiny_engine.converse("x" * (_TINY_LIMIT * 4), timeout=_PATIENT)
        assert caught.value.limit == _TINY_LIMIT
        assert caught.value.size > _TINY_LIMIT
        assert caught.value.field == "utterance"

    async def test_an_oversized_result_is_refused(self, tiny_engine: AssistantEngine) -> None:
        """The *coming back* direction, which is the one ADR-0084 §4 insisted on.

        Without it a client is silently **more** capable than the engine it stands
        in for in one direction and less in the other: the in-process engine would
        hand a caller a value the wire client provably cannot deliver.

        **The argument object here is twelve bytes**, so nothing but the result can
        trip the limit: the page is built from beliefs each stored through a
        ``learn`` the bound comfortably admits, and then a listing whose whole
        request payload is ``{"offset":0}`` grows past it. An implementation that
        measured only its arguments passes every other case in this class and fails
        this one, which is the whole reason it is written this way round.

        ``field`` is ``None`` because a listing result is a bare JSON array with no
        member to name — ADR-0085 §9 says that case is reachable rather than
        defensive, and this is where it is reached.
        """
        for index in range(6):
            await tiny_engine.learn(_feedback(f"the office is in Boston, building {index}"))
        with pytest.raises(OversizedValueError) as caught:
            await tiny_engine.beliefs()
        assert caught.value.limit == _TINY_LIMIT
        assert caught.value.size > _TINY_LIMIT
        assert caught.value.field is None

    async def test_a_result_that_fits_is_returned(self, tiny_engine: AssistantEngine) -> None:
        """The discriminating half of the case above.

        One stored belief lists comfortably inside the bound, so the refusal above
        is about the page's size and not about ``beliefs()`` being refused
        unconditionally.
        """
        await tiny_engine.learn(_feedback("the office is in Boston"))
        assert len(await tiny_engine.beliefs()) == 1

    async def test_a_payload_inside_the_limit_is_admitted(
        self, tiny_engine: AssistantEngine
    ) -> None:
        """The limit refuses what it must and nothing else — the discriminating half.

        Without this, an implementation that refused *every* call would pass the two
        assertions above.
        """
        assert await tiny_engine.beliefs() == ()
        assert await tiny_engine.forget("no-such-record") is False

    async def test_the_refusal_names_the_limit_and_the_measured_size(
        self, tiny_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §9: "too large" without a number is not actionable."""
        with pytest.raises(OversizedValueError) as caught:
            await tiny_engine.belief("z" * (_TINY_LIMIT * 4))
        assert caught.value.limit == _TINY_LIMIT
        assert caught.value.size == pytest.approx(caught.value.size)
        assert caught.value.field == "record_id"

    # --- §4a: the listing cannot ship the corpus ---------------------------

    async def test_the_listing_returns_summaries_and_carries_no_citation(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0077 §6's split, made structural (§4a).

        The listing "resolves *existence* and renders the count, the lost count, and
        the adjusted confidence"; the single-belief view "renders the surviving
        citations as readable evidence". This is the shape where the wrong behaviour
        is **unrepresentable** rather than merely detectable: a
        :class:`~ai_assistant.core.types.BeliefSummary` has nowhere to put a
        citation's content, so a conforming listing cannot over-deliver.
        """
        await engine.learn(_feedback("the office is in Boston"))
        page = await engine.beliefs()
        assert page
        for summary in page:
            assert isinstance(summary, BeliefSummary)
            assert not hasattr(summary, "evidence")

    async def test_the_same_three_names_read_alike_on_both_belief_types(
        self, engine: AssistantEngine
    ) -> None:
        """§4a's table: only the *category* of two of them changes, never the answer.

        That is what keeps a renderer from needing two code paths, and it is the
        reason ``unsupported`` stays derived on both — a field there would put a
        value on the wire a client can compute exactly, so one implementation could
        send it and another omit it, and the same call would measure two sizes.
        """
        outcome = await engine.learn(_feedback("the office is in Boston"))
        record_id = outcome.results[0].record_id
        assert record_id is not None
        summary = next(one for one in await engine.beliefs() if one.id == record_id)
        detail = await engine.belief(record_id)
        assert detail is not None
        assert summary.evidence_count == detail.evidence_count
        assert summary.lost_evidence == detail.lost_evidence
        assert summary.unsupported == detail.unsupported

    # --- ADR-0074 §1: an unknown conversation is refused, never started -----

    async def test_an_unknown_conversation_is_refused_rather_than_started(
        self, engine: AssistantEngine
    ) -> None:
        """ADR-0074 §1: refused, **not silently started**.

        Silently starting one turns a typo or a stale copy-paste into "my
        conversation vanished" and lands the user's continuation somewhere they
        cannot find. It is asserted of every implementation because a stand-in that
        started one instead would let a client's tests pass over the exact path the
        engine refuses — which is the substitutability this Protocol exists for,
        failing in the direction nobody looks.
        """
        with pytest.raises(UnknownConversationError):
            await engine.converse("hello", timeout=_PATIENT, conversation_id="no-such-id")
        with pytest.raises(UnknownConversationError):
            await engine.observe(conversation_id="no-such-id")

    async def test_a_turn_with_no_conversation_named_runs_in_one_it_minted(
        self, engine: AssistantEngine
    ) -> None:
        """The other side of the same rule: passing no id starts a conversation.

        Every turn runs under one and the outcome reports which (ADR-0074 §2),
        because a stateless client cannot keep it otherwise.
        """
        outcome = await engine.converse("hello", timeout=_PATIENT)
        assert outcome.conversation_id is not None
        continued = await engine.converse(
            "and again", timeout=_PATIENT, conversation_id=outcome.conversation_id
        )
        assert continued.conversation_id == outcome.conversation_id

    # --- ADR-0078 §8: only an open question is answerable --------------------

    async def test_a_question_that_is_not_open_answers_not_open(
        self, engine: AssistantEngine
    ) -> None:
        """Rendering a non-open answer as anything else would claim a write.

        "That question is not open — absent, lapsed, already being answered, or
        already answered. Nothing was written." An id naming nothing is the case
        every implementation can be held to without seeding a queue.
        """
        outcome = await engine.answer("no-such-question", accept=True)
        assert outcome.kind is AnswerKind.NOT_OPEN
        assert outcome.record_id is None

    # --- ADR-0084 §7: an unresolvable token is its own refusal --------------

    async def test_an_unknown_continuation_is_its_own_typed_refusal(
        self, engine: AssistantEngine
    ) -> None:
        """Never a generic failure, and **never a denial** (ADR-0084 §7).

        An unresolvable token means nobody ruled on the action;
        :class:`~ai_assistant.core.errors.PermissionDeniedError` means somebody did
        and said no. Reporting one as the other tells a user their action was
        refused when it was merely forgotten — and the remedy differs: this one is
        answered by ``pending_confirmations()`` and a fresh token.
        """
        with pytest.raises(UnknownContinuationError):
            await engine.resume(
                ContinuationToken(handle="not-a-real-handle"), approved=True, timeout=_PATIENT
            )

    # --- ADR-0042 §4 and ADR-0052 §1: park, render, relay --------------------

    async def test_a_park_is_recovered_with_a_token_that_resolves(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0052 §1's enumerate-and-re-mint, held over both implementations.

        The confirmation carries what a person needs to judge the action — the
        tool, what it does, the parameters it would run with, and the policy's own
        reason for asking — because the adapter may read neither the audit trail
        nor a ``PermissionDecision`` to recover any of it (ADR-0042 §6).
        """
        pending = await parked_engine.pending_confirmations()
        assert len(pending) == 1
        assert pending[0].reason
        assert pending[0].tool_description
        resumed = await parked_engine.resume(pending[0].token, approved=True, timeout=_PATIENT)
        assert resumed.step is not None

    async def test_a_resume_always_carries_its_resolved_step(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §4: the step is what a resume is *for*, so it is never ``None``.

        ``turn`` may legitimately be absent — a park recovered from durable state
        after a restart has no live turn, and fabricating one would misrepresent
        what the turn saw (ADR-0052 §3) — which is exactly why the step cannot be.
        A client handed neither has nothing to render.

        ``step_id`` names the plan step the pass drove, which is what turns "read
        ``state`` too" from advice into an addressable operation (ADR-0084 §8).
        """
        pending = await parked_engine.pending_confirmations()
        resumed = await parked_engine.resume(pending[0].token, approved=True, timeout=_PATIENT)
        assert resumed.step is not None
        assert resumed.step.step_id
        named = [
            execution
            for execution in resumed.step.state.steps
            if execution.step_id == resumed.step.step_id
        ]
        assert len(named) == 1, "step_id must address exactly one execution record"

    async def test_a_refusal_is_a_result_and_not_an_exception(
        self, parked_engine: AssistantEngine
    ) -> None:
        """ADR-0042 §4: only ``approved=False -> DENY`` is guaranteed, and DENY is a *ruling*.

        "The adapter conveys consent; the policy rules on it; the engine records and
        executes." A denial is therefore a
        :attr:`~ai_assistant.core.types.Disposition.DENIED` disposition in the
        outcome, never a raised
        :class:`~ai_assistant.core.errors.PermissionDeniedError` — an implementation
        that raised would hand a client a failure path the in-process engine does
        not have, and the CLI renders the outcome rather than catching anything.
        """
        pending = await parked_engine.pending_confirmations()
        resumed = await parked_engine.resume(pending[0].token, approved=False, timeout=_PATIENT)
        assert resumed.step is not None
        assert resumed.step.disposition is Disposition.DENIED
        assert resumed.step.confirmation is None

    async def test_a_token_is_answered_once(self, parked_engine: AssistantEngine) -> None:
        """A resolved park is evicted, so a replay is a clean unknown token.

        A second answer would be refused by the trail's single-resolution index
        anyway; turning the replay into
        :class:`~ai_assistant.core.errors.UnknownContinuationError` is what keeps
        the table bounded and gives the client the one refusal that has a remedy.
        """
        pending = await parked_engine.pending_confirmations()
        await parked_engine.resume(pending[0].token, approved=True, timeout=_PATIENT)
        with pytest.raises(UnknownContinuationError):
            await parked_engine.resume(pending[0].token, approved=True, timeout=_PATIENT)

    # --- ADR-0074 §2: the listing is ordered by activity ---------------------

    async def test_conversations_are_listed_by_activity_and_not_by_last_turn(
        self, engine: AssistantEngine
    ) -> None:
        """Most recently active first, and the key is never "has a turn landed".

        Ordering by the latter would sink a conversation the user opened a minute
        ago below one they abandoned last week. It is held over every
        implementation because a stand-in that returned insertion order would let a
        client's ordering tests pass while production rendered stale conversations
        first — the failure is invisible until someone looks at a real listing.
        """
        first = (await engine.converse("one", timeout=_PATIENT)).conversation_id
        second = (await engine.converse("two", timeout=_PATIENT)).conversation_id
        assert first is not None
        assert second is not None
        assert [one.id for one in await engine.recent_conversations()] == [second, first]

        await engine.converse("again", timeout=_PATIENT, conversation_id=first)
        listed = await engine.recent_conversations()
        assert [one.id for one in listed] == [first, second]
        assert listed[0].last_active_at >= listed[1].last_active_at

    # --- forgetting something absent is not an error ------------------------

    async def test_forgetting_what_is_not_held_reports_false_rather_than_raising(
        self, engine: AssistantEngine
    ) -> None:
        """The user's intent — "let this not be held" — is already satisfied."""
        assert await engine.forget("no-such-record") is False
        assert await engine.forget_question("no-such-question") is False
        assert await engine.forget_conversation("no-such-conversation") is False

    async def test_reading_what_is_not_held_answers_none(self, engine: AssistantEngine) -> None:
        """An optional getter answers ``None``; it does not invent a record."""
        assert await engine.belief("no-such-record") is None
        assert await engine.conversation("no-such-conversation") is None

    # --- clause 6: an error's structured state survives (§10a) --------------

    def test_every_error_s_structured_state_round_trips_through_its_constructor(self) -> None:
        """ADR-0085 §10a, over **every** subtype rather than over a list of two.

        The wire reconstructs a declared failure "by calling the named type with the
        message positionally and the ``details`` members as keyword arguments", and
        ``details`` is "the exception's public attributes whose names match its
        constructor's keyword parameters". An attribute the constructor will not
        accept back under the same name breaks reconstruction, and nothing else
        would catch it.

        Walked rather than enumerated: ADR-0085 §4c's own lesson is that a field
        list rots and a rule survives, and a table of error types here would go
        stale the first time a structured error is added.
        """
        for name, kind in vars(error_module).items():
            if not (isinstance(kind, type) and issubclass(kind, AssistantError)):
                continue
            initialiser = kind.__init__
            if initialiser is AssistantError.__init__ or initialiser is object.__init__:
                continue  # carries a message and nothing else, so it sends no details
            parameters = [
                parameter
                for parameter in inspect.signature(initialiser).parameters.values()
                if parameter.name not in {"self", "message"}
            ]
            sample = {parameter.name: _sample_for(parameter.name) for parameter in parameters}
            original = kind("the failure", **sample)
            details = {
                attribute: getattr(original, attribute)
                for attribute in sample
                if attribute != "details_elided"
            }
            rebuilt = kind("the failure", **details)
            for attribute in details:
                assert getattr(rebuilt, attribute) == getattr(original, attribute), (
                    f"{name}.{attribute} does not survive its own constructor"
                )

    def test_details_elided_is_false_on_every_in_process_raise(self) -> None:
        """ADR-0085 §10a: nothing elides in-process, so the marker is never set.

        It exists so a client whose reconstruction lost an exception's structured
        state can say so: ``unresolved_ids`` defaults to ``()``, so a reconstructed
        :class:`~ai_assistant.core.errors.UnresolvedEvidenceError` **without** the
        flag would tell a caller that nothing was unresolved at the exact moment
        that too much was.
        """
        assert UnresolvedEvidenceError("gone", ["a", "b"]).details_elided is False
        assert OversizedValueError("too big", limit=1, size=2, field=None).details_elided is False
        elided = UnresolvedEvidenceError("gone")
        elided.details_elided = True
        assert elided.unresolved_ids == ()
        assert elided.details_elided is True

    @pytest.mark.parametrize(
        "build",
        [
            lambda: AssistantError("bad \ud800"),
            lambda: UnresolvedEvidenceError("bad \ud800"),
            lambda: UnresolvedEvidenceError("fine", ["\ud800"]),
            lambda: OversizedValueError("fine", limit=1, size=2, field="\ud800"),
        ],
    )
    def test_an_error_carrying_unencodable_text_is_refused(
        self, build: Callable[[], AssistantError]
    ) -> None:
        """ADR-0085 §9: ``core/errors.py`` is outside #566's coverage guard.

        The guard in ``tests/core/test_text_encodability_coverage.py`` is scoped to
        ``core.types`` deliberately, so nothing mechanical enforces this one — it is
        a clause this suite carries. It matters because §10a's reduction cannot
        rescue it: the reduction *measures* a payload, and measuring means encoding,
        so an unencodable message fails **before** the rule that was supposed to
        handle an oversized error, and the declared exception reaches a caller as an
        undeclared transport failure.
        """
        with pytest.raises(ValueError, match="UTF-8 encoding"):
            build()

    # --- §4: admission, and what it never applies to -----------------------

    async def test_the_enumeration_offers_the_source_with_its_location(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0097 §9: a client offers a choice among declared identities.

        And ADR-0102 §6: this response is the **only** carrier of a source's
        configured location, so a client has something to render before it grants.
        """
        offered = await granting_engine.grantable_sources()
        assert [one.source for one in offered] == [_SOURCE]
        assert offered[0].location
        assert offered[0].live is None

    async def test_a_source_no_reader_declares_is_ungrantable(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§4: any validated value that is not a held identity raises, and nothing is built.

        :class:`~ai_assistant.core.errors.UngrantableSourceError` specifically, and
        **not** ``InvalidGrantError``: ADR-0097 §10 scopes that class to "the store
        refused the record", and this refusal happens before a record exists. A
        caller given the wrong one is told to construct a different record when the
        actual remedy is to pick a different source.
        """
        with pytest.raises(UngrantableSourceError):
            await granting_engine.grant("no-such-source", scope=[GrantScope.FACET])
        assert await granting_engine.recent_grants() == ()

    async def test_a_source_differing_only_by_whitespace_is_refused_not_matched(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0097 §10, and the reason ``source`` is not :data:`Identifier` (§2).

        **This is the clause the wire implementation could have failed alone**, and
        ADR-0102 §12 item 2 says so in as many words: ``wire/surface.py`` validates
        each argument against the Protocol's own annotation before dispatch, so an
        ``Identifier`` annotation would have arrived at the operation already
        stripped and *matched* — while the in-process engine, handed the string
        unvalidated, refused the same call. Two observable contracts for one call is
        the substitutability failure ADR-0084 §4 promotes this surface to prevent.
        """
        with pytest.raises(UngrantableSourceError):
            await granting_engine.grant(f"  {_SOURCE}  ", scope=[GrantScope.FACET])
        assert await granting_engine.recent_grants() == ()

    async def test_revoking_a_source_no_reader_declares_is_not_refused_for_that(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§4: ``revoke`` applies **no** admission check.

        A grant whose reader is later unconfigured must stay revocable — otherwise a
        configuration edit makes it permanently unrevokable, which is the failure
        ADR-0097 §4 refused when it declined an ordering invariant on ``decided_at``.
        Nothing leaks through the opening: the value finds no live grant, constructs
        nothing and records nothing.
        """
        assert await granting_engine.revoke("no-such-source") is None
        assert await granting_engine.recent_grants() == ()

    # --- §5: who mints, and the store as arbiter ---------------------------

    async def test_a_second_grant_on_a_live_source_is_refused(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5: the store is the arbiter, and its refusal propagates.

        Never retried and never converted into a success. ADR-0097 §10 makes
        ``record`` atomic over the live-grant check, so a lost race is a typed
        refusal rather than a second live grant, and the client's remedy is to
        re-read ``grantable_sources``.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        with pytest.raises(InvalidGrantError):
            await granting_engine.grant(_SOURCE, scope=[GrantScope.INGEST])

    async def test_revoking_with_no_live_grant_returns_none(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5: where no member of ``GrantScope`` answers, nothing is recorded."""
        assert await granting_engine.revoke(_SOURCE) is None
        assert await granting_engine.recent_grants() == ()

    async def test_a_revocation_transcribes_the_grant_it_withdraws(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5: the revoking record carries the grant's ``source`` and ``scope`` verbatim.

        ADR-0021 §1's reason for embedding a declaration rather than a name: the
        record says what was withdrawn without a join. The store verifies the
        transcription, which is why an implementation that got it wrong would be
        refused rather than silently recording a lie.
        """
        granted = await granting_engine.grant(_SOURCE, scope=[GrantScope.INGEST])
        withdrawn = await granting_engine.revoke(_SOURCE)
        assert withdrawn is not None
        assert withdrawn.revokes == granted.id
        assert withdrawn.source == granted.source
        assert withdrawn.scope == granted.scope

    async def test_an_ingest_only_grant_is_revocable(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§5's sweep, and the wrong version passes every other test here.

        ``SourceGrants.live`` takes a ``use``, so an implementation querying only
        ``FACET`` resolves a ``FACET``-scoped grant and silently fails to find this
        one — leaving it unrevokable while ``revoke`` reports success by returning
        ``None``. Written over the enum rather than over its members, so it stays
        total as ``GrantScope`` grows.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.INGEST])
        assert await granting_engine.revoke(_SOURCE) is not None

    async def test_a_grant_reaches_the_enumeration_as_live_and_a_revocation_clears_it(
        self, granting_engine: AssistantEngine
    ) -> None:
        """The round trip, without which every refusal above proves nothing.

        A suite that only asserted refusals would pass against an implementation
        that refused everything.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        live = (await granting_engine.grantable_sources())[0].live
        assert live is not None
        assert live.scope == (GrantScope.FACET,)

        await granting_engine.revoke(_SOURCE)
        assert (await granting_engine.grantable_sources())[0].live is None
        assert len(await granting_engine.recent_grants()) == 2

    async def test_liveness_is_stated_rather_than_derived_from_the_page(
        self, back_dated_engine: AssistantEngine
    ) -> None:
        """ADR-0102 §12's normative clause, and **nothing else in this list reaches it**.

        ADR-0097 §4 derives liveness from the ``revokes`` relation alone and is
        emphatic that "a revocation is never refused for its timestamp — including
        one that predates the grant it revokes", because ``decided_at`` is
        caller-supplied and a host clock corrected backwards would otherwise make a
        grant permanently unrevokable. ``recent_grants`` is ordered newest first by
        ``decided_at``, so on such a deployment a revoking record sorts **below** the
        grant it revokes and can fall outside a page that contains it.

        An implementation computing ``live`` by walking that page would then report
        a **withdrawn grant as live** — the one answer this whole contract exists to
        get right — and would pass every other clause in this class, because every
        other clause is about admission, refusal or paging. It would also fail only
        on the deployment where a clock moved, which is the failure that never shows
        up in a test unless a test is written for it.

        So the two halves are asserted together: the source is not live, **and**
        both records are still listed. Asserting only the first would pass against
        an implementation that had dropped the revoked grant from the record, which
        ADR-0097 §6 forbids — revocation retires nothing and the history stays whole.
        """
        granted = await back_dated_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        withdrawn = await back_dated_engine.revoke(_SOURCE)
        assert withdrawn is not None
        # The premise the fixture exists to establish. Asserted rather than assumed,
        # because a fixture whose clock did *not* run backwards would leave every
        # assertion below true of an implementation this case is written to fail.
        assert withdrawn.decided_at < granted.decided_at
        # And the page really is ordered the way that misleads: the grant sorts
        # first, so an implementation reading liveness off the newest entry sees a
        # granting record and answers "live".
        page = await back_dated_engine.recent_grants()
        assert [record.id for record in page] == [granted.id, withdrawn.id]

        assert (await back_dated_engine.grantable_sources())[0].live is None

    async def test_the_record_is_ordered_newest_first_with_ids_breaking_ties(
        self, granting_engine: AssistantEngine
    ) -> None:
        """``SourceGrantStore.recent``'s order, as the surface relays it.

        Descending by ``decided_at``, ties broken by ``id`` **ascending**. The
        tie-break is what makes the order total rather than merely mostly
        determined, and it is the half a one-line ``sorted(..., reverse=True)`` over
        a compound key gets wrong: reversing the compound key reverses the tie-break
        with it, so two records at one instant come back in the opposite order the
        contract states. An implementation whose clock does not advance between two
        records — a fixed test clock, or a real one at any resolution — reaches that
        case immediately, and nothing else in this class would notice.
        """
        await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET])
        await granting_engine.revoke(_SOURCE)
        page = await granting_engine.recent_grants()
        assert len(page) == 2
        # Composed as two stable sorts rather than one reversed compound key,
        # because that compound key is precisely the wrong answer being checked
        # for: ``reverse=True`` over ``(decided_at, id)`` reverses the tie-break
        # too.
        by_id = sorted(page, key=lambda record: record.id)
        assert list(page) == sorted(by_id, key=lambda record: record.decided_at, reverse=True)

    # --- §2a and §10: the local refusals -----------------------------------

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    @pytest.mark.parametrize("call", ["grant", "revoke"])
    async def test_a_blank_source_is_refused_locally(
        self, granting_engine: AssistantEngine, call: str, blank: str
    ) -> None:
        """§2a: a caller programming error, refused before any I/O.

        ``ValueError`` and deliberately not an ``AssistantError``, exactly as a
        blank identifier is on the rest of the surface.
        """
        arguments = {"scope": [GrantScope.FACET]} if call == "grant" else {}
        with pytest.raises(ValueError, match=r"\w"):
            await getattr(granting_engine, call)(blank, **arguments)

    async def test_an_empty_or_duplicated_scope_is_refused_locally(
        self, granting_engine: AssistantEngine
    ) -> None:
        """§2a, over ADR-0097 §2 and §10's two refusals.

        A grant naming no use authorises nothing and would still *read* as a grant —
        and worse, would occupy the source's one live-grant slot. A repeated member
        is a caller that has lost track of what it is asking for.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await granting_engine.grant(_SOURCE, scope=[])
        with pytest.raises(ValueError, match=r"\w"):
            await granting_engine.grant(_SOURCE, scope=[GrantScope.FACET, GrantScope.FACET])
        assert await granting_engine.recent_grants() == ()

    @pytest.mark.parametrize("bad", [0, -1, 2**63])
    async def test_recent_grants_refuses_a_non_positive_limit_locally(
        self, granting_engine: AssistantEngine, bad: int
    ) -> None:
        """§10's local-refusal clause, and ``0`` is the case it exists for.

        ADR-0085 §9 admits a page argument in ``[0, 2**63)`` and
        ``SourceGrantStore.recent`` requires a strictly positive ``limit``, so
        ``recent_grants(limit=0)`` is well-formed under the surface rule and refused
        by the store. Refusing it locally in **both** implementations is §9's own
        clause — "neither is silently more permissive" — applied to the one argument
        where the two ranges do not coincide.
        """
        with pytest.raises(ValueError, match=r"\w"):
            await granting_engine.recent_grants(limit=bad)

    @pytest.mark.parametrize("bad", [1.5, True, "1", None])
    async def test_a_limit_that_is_not_an_integer_is_refused_locally(
        self, granting_engine: AssistantEngine, bad: object
    ) -> None:
        """The type before the range, for :meth:`beliefs`' reason.

        ``0 < 1.5 < 2**63`` is true, so a range check alone admits a float; and
        ``True`` is an ``int`` that would silently mean a page of one, which is a
        wrong answer rather than a refusal.
        """
        with pytest.raises(TypeError, match=r"\w"):
            # The wrong *type* is the point of the case, so the annotation is
            # deliberately violated here.
            await granting_engine.recent_grants(limit=bad)  # type: ignore[arg-type]

    def test_the_grant_page_size_default_is_the_declared_one(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §3a reaches ``recent_grants`` like every other paging method."""
        parameter = inspect.signature(granting_engine.recent_grants).parameters["limit"]
        assert parameter.default == DEFAULT_PAGE_SIZE

    async def test_every_grant_enumeration_returns_a_tuple(
        self, granting_engine: AssistantEngine
    ) -> None:
        """ADR-0085 §3b: a caller that mutated a returned page changed nothing."""
        assert isinstance(await granting_engine.grantable_sources(), tuple)
        assert isinstance(await granting_engine.recent_grants(), tuple)


def backwards_clock() -> Callable[[], datetime]:
    """A clock whose every reading is **earlier** than the last.

    What :attr:`AssistantEngineContract.back_dated_engine` is built on, shared so
    the three bindings cannot arrange three different premises for one clause. It
    models a host clock that has been corrected backwards — the deployment ADR-0097
    §4 refuses to make a grant unrevokable on, and therefore the only deployment on
    which a liveness derived from ``decided_at`` gives a wrong answer.

    Steps by a whole second per reading, so the two records a grant/revoke pair
    mints are unambiguously ordered rather than separated by a resolution a
    serialiser might round away.

    Returns:
        A callable returning a strictly decreasing sequence of instants.
    """
    numbers = count(1)
    origin = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    return lambda: origin - timedelta(seconds=next(numbers))


async def page_after_mutating_the_filter(
    engine: AssistantEngine,
) -> tuple[tuple[BeliefSummary, ...], tuple[BeliefSummary, ...]]:
    """Run ``beliefs`` while emptying the list it was handed, and page it again.

    Shared with the discrimination case in ``test_fake_engine``, which is what
    makes the assertion above evidence rather than a tautology: a scenario nobody
    has watched fail is a scenario that agrees with whatever it is run against.

    Returns:
        The page from the mutated call, and the page the same filter yields when
        nothing touches it.
    """
    every_band = [BeliefBand.ASSERTED, BeliefBand.DERIVED, BeliefBand.ATTESTED]
    bands = list(every_band)
    running = asyncio.ensure_future(engine.beliefs(bands=bands))
    # One turn of the loop, so the call has reached its first suspension (or run to
    # completion) before the list is emptied — the window ADR-0065 §3d is about.
    await asyncio.sleep(0)
    bands.clear()
    page = await running
    return page, await engine.beliefs(bands=every_band)


def _sample_for(parameter: str) -> object:
    """A plausible value for one structured-state parameter, by its declared shape.

    Deliberately shallow: what the round-trip test needs is *a* value the
    constructor accepts, not a realistic one. A parameter this does not know is
    given a string, which is what every operator-facing field on the hierarchy is.
    """
    if parameter in {"limit", "size"}:
        return 1
    if parameter.endswith("_ids"):
        return ("a", "b")
    return "text"

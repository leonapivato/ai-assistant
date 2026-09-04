"""Shared conformance suites for the two invocation faces (ADR-0192 §2).

Every ``InvocationCompleter`` implementation must pass
:class:`InvocationCompleterContract`, and every ``InvocationLedger`` must pass
:class:`InvocationLedgerContract` — which inherits it rather than repeating it.
That split is the Protocols' own: the wide face is the narrow one plus the claim,
so the completion obligations are stated once and the claim's are added, exactly
as ``SecretStoreContract`` adds writes to ``SecretsContract``.

**The subject is one object satisfying both faces *and* ``AuditTrail``**, because
that is what ADR-0192 §2 requires of an implementation — the composition root
injects one object over one store and hands each consumer a face. So the trail's
three new reads are exercised here too, against the writes that produce the rows
they read: a suite that could only claim would have nothing to read back, and one
that could only read would have nothing to read.

**What is deliberately *not* here.** Everything ADR-0192 §9 assigns to the seam
group (``ToolInvoker.invoke``'s claim/complete obligation, the shield, the
diagnostic matrix, the ``ToolResult`` -> ``ToolInvocation`` mapping), to the
recovery group (the scan and its ordering), and to the surface group (the engine's
two operations and their adapters). What this suite owes about those is the
**store-side fact each of them reads** — that a completion which failed leaves the
claim open, that the rows the scan will append are constructible field by field,
and that ``open_invocations`` answers the exact set the scan is written against.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest
from permission_builders import AT, action, decision, ruling, tool

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.errors import (
    AssistantError,
    AuditError,
    AuthorisationSpentError,
    InvalidCompletionError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.protocols import AuditTrail, InvocationLedger
from ai_assistant.core.types import (
    BoundAccount,
    CostBasis,
    EgressBinding,
    FrozenDict,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from pydantic import BaseModel

    from ai_assistant.core.types import RecordedInvocation
    from ai_assistant.testing.cancellation import ResourceLog, SuspendedCall


def _undeclared(value: BaseModel, state: dict[object, object]) -> None:
    """Put ``state`` into ``value``'s instance dict, whatever its keys look like.

    Written through an untyped view because that is exactly the point: a model's
    ``__dict__`` is annotated ``dict[str, Any]`` and nothing enforces it at
    runtime, so a caller's value can carry keys of any hashable type at all — and
    an implementation that ``sorted()``s them raises ``TypeError`` from inside its
    own refusal the moment two of them differ in type.
    """
    holder = cast("dict[object, object]", value.__dict__)
    holder.update(state)


class HostileKey(str):
    """A ``str`` subclass that collides with a field name and refuses to be compared.

    The construction a set difference walks into: it hashes as the field name it
    spells, so a lookup against the declared field names lands in that bucket and
    has to compare — and once :meth:`arm` is called the comparison raises. An
    implementation that classifies a non-``str`` key *without touching it* never
    provokes it; one that builds a ``set`` of the keys, or asks ``key in
    declared``, leaves as that ``RuntimeError`` instead of this layer's refusal.

    A ``str`` **subclass** rather than an unrelated object, because ``type(key) is
    str`` is the discriminator an implementation must use: an ``isinstance`` check
    admits this and then compares it.

    **Armed after insertion, and explicitly.** Putting the key into a dict that
    already holds the real one costs comparisons — how many is CPython's business,
    not the test's — so a key that counted them would fail by table layout rather
    than by anything the subject did. Disarmed it simply answers "not equal", which
    lands it beside the real key rather than over it.
    """

    _armed: bool

    def __init__(self, *_spelling: object) -> None:
        """Start disarmed; ``str`` itself is built by ``__new__``."""
        self._armed = False

    def arm(self) -> None:
        """Refuse every comparison from here on."""
        self._armed = True

    def __hash__(self) -> int:
        """Hash as the plain text it spells, so a lookup of that field must compare."""
        return hash(str(self))

    def __eq__(self, other: object) -> bool:
        """Never equal while disarmed, so it lands *beside* the real key; then refuse.

        Equal-while-disarmed would make the insertion replace the field's value
        instead of adding an undeclared key, and the case would then be about a
        decision naming something the store does not hold.
        """
        if self._armed:
            msg = "this key will not be compared"
            raise RuntimeError(msg)
        return False


class HostileMapping(Mapping[str, object]):
    """A mapping that is not a decision and refuses to be read as one.

    A value that is not a model reaches ``model_validate`` untouched, which is the
    ordering the case below is about — and validating a *mapping* walks it. This one
    raises from ``__getitem__``, so the fault leaves as itself through a check that
    was going to refuse the value anyway.
    """

    def __getitem__(self, key: str) -> object:
        """Refuse to be read."""
        msg = "this mapping refuses to be read"
        raise RuntimeError(msg)

    def __iter__(self) -> Iterator[str]:
        """Offer one key, so a validator has something to reach for."""
        return iter(("id",))

    def __len__(self) -> int:
        """Report the one key."""
        return 1


class Unhashable(str):
    """A str that refuses to be hashed, which an enum lookup has to do.

    Not a value a validator rejects: a value that stops the validator from reaching a
    verdict at all. ToolOutcome(value) looks the member up in a mapping, so the
    fault leaves as whatever __hash__ raised rather than as the refusal the
    lookup was about to make.
    """

    def __hash__(self) -> int:
        """Refuse to be hashed."""
        msg = "this value refuses to be hashed"
        raise RuntimeError(msg)


class HostileClass:
    """An object that refuses to say what it is, which ``isinstance`` has to ask.

    ``isinstance`` consults ``__class__`` when ``type()`` does not settle the
    question, so a property that raises turns the *type probe* into a way out of
    ADR-0192 §2's refusal classes — before any field has been read at all.
    """

    @property  # type: ignore[misc]  # a read-only `__class__` is the whole point
    def __class__(self) -> type:
        """Refuse to say what this is."""
        msg = "this value refuses to say what it is"
        raise RuntimeError(msg)


class UnspeakableError(ValueError):
    """A ``ValueError`` that cannot be described, which is the caller's to raise.

    A container's own ``__iter__`` runs the caller's code, and what it raises is the
    caller's value too. A refusal that interpolates the caught exception into its
    message calls this ``__str__`` from inside the ``except`` block that exists to
    report it, and leaves as whatever that threw — outside the classes ADR-0192 §2's
    order admits. ``ValueError`` specifically, because that is the class an
    implementation is most likely to let through untouched as "already the right
    kind of refusal".
    """

    def __str__(self) -> str:
        """Refuse to describe this exception."""
        msg = "this exception refuses to describe itself"
        raise RuntimeError(msg)

    def __repr__(self) -> str:
        """Refuse to describe this exception, the other way round too."""
        msg = "this exception refuses to describe itself"
        raise RuntimeError(msg)


class Unspeakably(list[object]):
    """A container whose iteration raises an exception that cannot be described."""

    def __iter__(self) -> Iterator[object]:
        """Refuse to be iterated, unspeakably."""
        raise UnspeakableError


class Undescribable:
    """A value that refuses to describe itself, and can still be a mapping key.

    The shape ``describe_untrusted`` exists for: a diagnostic that reaches for
    ``repr`` on the caller's value can be made to raise from inside the ``except``
    block that exists to report the fault, replacing this layer's refusal with
    whatever the value threw (``core/types.py``).
    """

    def __repr__(self) -> str:
        """Refuse, which is the whole of this class."""
        msg = "this value will not describe itself"
        raise RuntimeError(msg)

    def __hash__(self) -> int:
        """Hashable, so it can be an undeclared ``__dict__`` key too."""
        return 1

    def __eq__(self, other: object) -> bool:
        """Identity, since equality would have to describe the other side."""
        return self is other


class LedgerSubject(AuditTrail, InvocationLedger, Protocol):
    """One object over one store, which is what ADR-0192 §2 requires."""


#: The window every keyed case below is measured against. Ten seconds, so the
#: boundary cases read as the ADR states them (``t=0``, ``t=9``, ``t=18``).
WINDOW = timedelta(seconds=10)

#: What a completion carries when nothing measured a price — ADR-0192 §5's value
#: for "the act ran at a price the tool could not report", which an accumulator
#: fails closed on.
UNKNOWN_COST = ToolCost(basis=CostBasis.UNKNOWN)

#: A measured price, for the cases that pin a figure surviving the round trip.
PRICED = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.25"), currency="USD")


def natural() -> ToolDefinition:
    """A tool whose repetition is safe by nature, so no claim under it is spent."""
    return spendable(idempotency=Idempotency.NATURAL, idempotency_window=None)


def read_only() -> ToolDefinition:
    """A tool that changes nothing outside itself, so no claim under it is spent."""
    return spendable(side_effecting=False, idempotency=Idempotency.NONE, idempotency_window=None)


def spendable(**overrides: object) -> ToolDefinition:
    """A tool one authorisation backs exactly one act of: side-effecting, ``KEYED``.

    ``KEYED`` rather than ``NONE`` so the retry arm is reachable at all; the
    ``NONE`` case overrides it and is the one that gets exactly one claim ever.
    """
    fields: dict[str, object] = {
        "side_effecting": True,
        "idempotency": Idempotency.KEYED,
        "idempotency_window": WINDOW,
    }
    fields.update(overrides)
    return tool(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


#: The least that makes a well-formed egress binding — no described span, one
#: account, one endpoint — which keeps it constructible over ``action()``'s empty
#: parameters. ``egress_binding is None`` is the discriminator (ADR-0178 §4), and
#: ``RecordedInvocation.egress_call`` is true exactly when it is not ``None``.
_BINDING_MEMBERS: dict[str, object] = {
    "spans": (),
    "account": BoundAccount(identity="work@example.com", reference="conn-0001"),
    "transport_endpoint": "test://endpoint/one",
    "planned_with_external_content": False,
    "coverage": SpanCoverage.NOT_COVERED,
}


def allowed(
    decision_id: str = "d-1",
    *,
    definition: ToolDefinition | None = None,
    at: datetime = AT,
    egress: bool = False,
) -> PermissionDecision:
    """An ``ALLOW`` over ``definition``, which is what a claim needs to be admitted."""
    used = definition if definition is not None else spendable()
    request = (
        action(tool=used, egress_binding=EgressBinding(**_BINDING_MEMBERS))  # type: ignore[arg-type]  # heterogeneous members
        if egress
        else action(tool=used)
    )
    return decision(
        decision_id,
        request=request,
        ruled=ruling(PermissionOutcome.ALLOW),
        decided_at=at,
    )


class StepClock:
    """A clock that advances a fixed step per reading, and counts them.

    Counting is what pins "exactly one guarded reading per append" (ADR-0192 §1):
    an implementation reading twice would let a retry be admitted at ``t+9`` inside
    a ten-second window and stamped at ``t+11`` outside it, so the row would
    disagree with the rule that admitted it.
    """

    def __init__(self, *, start: datetime = AT, step: timedelta = timedelta(seconds=1)) -> None:
        """Start at ``start``, advancing ``step`` on every reading."""
        self.readings = 0
        self._start = start
        self._step = step

    def __call__(self) -> datetime:
        """Return the next reading."""
        reading = self._start + self._step * self.readings
        self.readings += 1
        return reading


class ScriptedClock:
    """A clock returning a scripted sequence, then repeating its last value."""

    def __init__(self, instants: Sequence[object]) -> None:
        """Read ``instants`` in order; the last one stands for every later read."""
        self.readings = 0
        self._instants = list(instants)

    def __call__(self) -> Any:
        """Return the next scripted value, whatever it is."""
        value = self._instants[min(self.readings, len(self._instants) - 1)]
        self.readings += 1
        if isinstance(value, BaseException):
            raise value
        return value


@dataclass
class ScriptedIdentifiers:
    """A factory returning a scripted sequence, then a fresh counter.

    ``forced`` is drawn from first, in order; ``always`` overrides it and is
    returned on every draw, which is how the exhausted-bound arm is reached.
    ``reserved`` records what the store handed back, so a case can assert the
    reservation happened at all as well as what it did.
    """

    forced: list[str] = field(default_factory=list)
    always: str | None = None
    label: str = "scripted"
    raises: BaseException | None = None
    returns: object | None = None
    reserved: list[str] = field(default_factory=list)
    _counter: itertools.count[int] = field(default_factory=itertools.count)

    def __call__(self) -> Any:
        """Return the next identifier, or whatever this factory was told to do."""
        if self.raises is not None:
            raise self.raises
        if self.returns is not None:
            return self.returns
        if self.always is not None:
            return self.always
        while self.forced:
            drawn = self.forced.pop(0)
            if drawn not in self.reserved:
                return drawn
        return f"{self.label}-{next(self._counter)}"

    def reserve(self, ids: Iterable[str]) -> None:
        """Record the reservation and honour it for the life of this factory.

        Honouring it is the obligation itself (ADR-0192 §2), not bookkeeping: a
        factory that recorded the ids and went on returning them is exactly the
        collaborator the clause exists to forbid.
        """
        self.reserved.extend(ids)


class LedgerHarness(Protocol):
    """How a binding builds subjects the cases can drive.

    ``open`` returns a subject over a **fresh** store unless ``store`` names one a
    previous ``open`` returned, which is how the restart and two-instance cases
    reach one store through two objects. ``store_of`` hands back that token.
    """

    def open(
        self,
        *,
        now: Callable[[], Any] = ...,
        identifiers: Any = None,
        store: object | None = None,
    ) -> LedgerSubject:
        """Build a subject, over ``store`` where one is named."""
        ...

    def store_of(self, subject: LedgerSubject) -> object | None:
        """The token naming ``subject``'s store, or ``None`` if it cannot be shared."""
        ...

    def arm(self, subject: LedgerSubject, operation: str) -> SuspendedCall:
        """Hold ``subject``'s next entry into ``operation`` open inside its resource."""
        ...

    def log_of(self, subject: LedgerSubject) -> ResourceLog:
        """When each armed call was inside ``subject``'s resource (ADR-0060 §3)."""
        ...

    def break_store(self, subject: LedgerSubject) -> bool:
        """Make ``subject``'s store unreadable and unwritable, or say it cannot be.

        ``False`` where the implementation's store cannot fail at all — a dict has
        no backend to lose — and the cases then skip with that reason stated.
        """
        ...


async def _claim(subject: LedgerSubject, authorisation: PermissionDecision) -> ToolInvocation:
    """Record ``authorisation`` if it is not recorded yet, then claim under it."""
    if await subject.get(authorisation.id) is None:
        await subject.record(authorisation)
    return await subject.claim_invocation(decision=authorisation)


async def _complete(
    subject: LedgerSubject,
    claim: ToolInvocation,
    outcome: ToolOutcome = ToolOutcome.FAILED,
    *,
    kind: ToolFailureKind | None = ToolFailureKind.UNAVAILABLE,
    cost: ToolCost = UNKNOWN_COST,
) -> ToolInvocation:
    """Complete ``claim``, defaulting to the retryable failure the retry arm needs."""
    return await subject.complete_invocation(
        claim_id=claim.id, outcome=outcome, incurred_cost=cost, failure_kind=kind
    )


#: What a released-early resource looks like from outside, said once.
_RELEASED_EARLY = (
    "the resource reached the next caller while the cancelled call's work was still using it"
)


async def _cancelled_inside_the_resource(
    harness: LedgerHarness,
    ledger: LedgerSubject,
    operation: str,
    first_call: Callable[[], Awaitable[object]],
    second_call: Callable[[], Awaitable[object]],
) -> None:
    """Cancel ``first_call`` inside ``operation``'s resource and watch the next caller.

    ADR-0192 §9 names two writes that "run from paths that may themselves be
    cancelled" — the claim append and the completion — and owes each "a write that
    survives that path". The surviving half is asserted by the caller, which knows
    what a coherent trail looks like for its own write; this is the half every
    resource-holding method shares, and it is ``core.protocols``' cancellation
    clause (ADR-0060 §3) on the two members ADR-0192 adds.

    **The second caller is what makes it a test of the invariant** rather than of
    propagation: a single cancelled call in isolation looks identical whether the
    resource was released early or not, which is why pre-ADR-0054 code — raising
    ``CancelledError`` correctly and dropping the connection anyway — passed the
    weaker case. Cancelled **twice**, because deferring one cancellation is not the
    contract: a second delivered while the deferred wait runs must not escape and
    unwind out of the resource either.

    Returns once the dust has settled — the first call ended cancelled, the second
    completed whole, and neither was inside the resource while the other was.
    """
    log = harness.log_of(ledger)
    # Armed *after* the caller's preconditions, so a fake arming its one resource
    # suspends the call under test rather than a setup write.
    suspended = harness.arm(ledger, operation)
    visited_before = log.visits

    first = asyncio.ensure_future(first_call())
    second: asyncio.Task[object] | None = None
    try:
        await suspended.reached()
        first.cancel()
        await settle()

        second = asyncio.ensure_future(second_call())
        await settle()
        assert not second.done(), _RELEASED_EARLY

        first.cancel()
        await settle()
        assert not second.done(), _RELEASED_EARLY
    finally:
        suspended.release()

    with pytest.raises(asyncio.CancelledError):
        await first
    assert second is not None
    await second

    # Decisive where the blocked-caller check above is not: a store whose work runs
    # on an executor can leave a second call pending for reasons that have nothing
    # to do with the resource. A delta, because a fake's preconditions pass through
    # the same logged resource.
    assert not log.overlapped, _RELEASED_EARLY
    assert log.visits - visited_before == 2, "both calls should have reached the resource by now"


async def recent_invocations(subject: LedgerSubject) -> list[RecordedInvocation]:
    """The bounded listing, called the way a surface consumer calls it."""
    return await subject.recent_invocations()


async def export_invocations(subject: LedgerSubject) -> list[RecordedInvocation]:
    """The unbounded listing."""
    return await subject.export_invocations()


#: The two joined listings, named so a parametrised case can arm the operation it
#: is about. Their names are the member names, which is what ``harness.arm`` takes.
_LISTINGS = (recent_invocations, export_invocations)


# The four distinct store paths ADR-0192 §9's translated-failure clause reaches,
# as named callables so each carries its own parameter id and the `pytest.raises`
# block stays one statement.


async def _bounded_listing(subject: LedgerSubject, claim: ToolInvocation) -> object:
    """``recent_invocations``, whose ``LIMIT`` is its own statement."""
    del claim
    return await subject.recent_invocations()


async def _whole_listing(subject: LedgerSubject, claim: ToolInvocation) -> object:
    """``export_invocations``, the unbounded read."""
    del claim
    return await subject.export_invocations()


async def _a_claim(subject: LedgerSubject, authorisation: PermissionDecision) -> object:
    """``claim_invocation``, an append inside a transaction."""
    return await subject.claim_invocation(decision=authorisation)


async def _the_open_set(subject: LedgerSubject, authorisation: PermissionDecision) -> object:
    """``open_invocations``, the read the recovery scan acts on."""
    return await subject.open_invocations(decision_id=authorisation.id)


def _over_the_same_store(
    harness: LedgerHarness, first: LedgerSubject, **built: Any
) -> LedgerSubject:
    """A second, independently constructed subject over ``first``'s store.

    ADR-0192 §9: "Where a store under test cannot be opened twice, the suite
    **skips with its reason stated** ... and never by omitting the case." A subject
    whose store is a dict cannot reach these cases at all, so the skip is stated
    once here rather than repeated in each of them.
    """
    store = harness.store_of(first)
    if store is None:
        pytest.skip("this store cannot be opened twice, so two instances are unreachable")
    return harness.open(store=store, **built)


async def _rows(subject: LedgerSubject) -> list[ToolInvocation]:
    """Every invocation row the trail holds, newest first."""
    return [held.invocation for held in await subject.export_invocations()]


class InvocationCompleterContract:
    """Behaviour every ``InvocationCompleter`` implementation must exhibit."""

    @pytest.fixture
    def harness(self) -> LedgerHarness:
        """Return the binding's way of building subjects."""
        raise NotImplementedError

    @pytest.fixture
    def ledger(self, harness: LedgerHarness) -> LedgerSubject:
        """An empty subject over a fresh store."""
        return harness.open()

    # --- the completion row -----------------------------------------------

    async def test_a_completion_points_at_its_claim_and_carries_what_it_was_given(
        self, ledger: LedgerSubject
    ) -> None:
        claim = await _claim(ledger, allowed())

        completion = await _complete(ledger, claim, ToolOutcome.SUCCEEDED, kind=None, cost=PRICED)

        assert completion.completes == claim.id
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert completion.incurred_cost == PRICED
        assert completion.failure_kind is None
        assert completion.id != claim.id

    async def test_a_completions_decision_comes_from_its_claim(self, ledger: LedgerSubject) -> None:
        """Never accepted from a caller, so the two cannot disagree (ADR-0192 §2)."""
        claim = await _claim(ledger, allowed("d-only"))

        completion = await _complete(ledger, claim)

        assert completion.decision_id == "d-only" == claim.decision_id

    @pytest.mark.parametrize(
        "outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE], ids=["failed", "indeterminate"]
    )
    async def test_a_kindless_completion_is_admitted_on_both_non_success_outcomes(
        self, ledger: LedgerSubject, outcome: ToolOutcome
    ) -> None:
        """The shape a cancellation-derived completion has (ADR-0192 §2).

        ``failure_kind`` is transcribed from a ``ToolResult`` and never
        synthesised, and a completion derived from an exception has none to
        transcribe from. ADR-0031 §3 forbids the seam inventing ``CANCELLED``, so
        the absence is the honest value and the row must be able to hold it.
        """
        claim = await _claim(ledger, allowed())

        completion = await _complete(ledger, claim, outcome, kind=None)

        assert completion.outcome is outcome
        assert completion.failure_kind is None

    @pytest.mark.parametrize(
        "outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE], ids=["failed", "indeterminate"]
    )
    async def test_a_reported_kind_is_stored_unaltered_on_both_non_success_outcomes(
        self, ledger: LedgerSubject, outcome: ToolOutcome
    ) -> None:
        """``INDETERMINATE`` carries a kind on the same terms as ``FAILED``.

        ADR-0029 §3's validator requires a ``ToolFailure`` on every result that is
        not ``SUCCEEDED``, so a keyed side-effecting call that timed out arrives
        carrying ``TIMED_OUT`` — and a row refusing to hold it would either fail
        validation and leave the claim open, or discard a kind the seam was handed.
        """
        claim = await _claim(ledger, allowed())

        completion = await _complete(ledger, claim, outcome, kind=ToolFailureKind.TIMED_OUT)

        assert completion.failure_kind is ToolFailureKind.TIMED_OUT

    async def test_the_row_a_recovery_scan_appends_is_storable_field_by_field(
        self, ledger: LedgerSubject
    ) -> None:
        """The shape ADR-0192 §3's scan writes, pinned where it is constructed.

        The scan itself is the recovery group's (§9), but its row is this store's:
        ``INDETERMINATE``, **no** ``failure_kind`` — there was no result to
        transcribe from and §2 forbids synthesising one — and an ``incurred_cost``
        whose basis is ``UNKNOWN``, never a figure and never
        ``ToolDefinition.cost``. Without this a scan may close every claim with
        ``TIMED_OUT`` and the declaration's price, pass every ordering case, and
        corrupt the spend total §5 is built on.
        """
        priced = spendable(cost=PRICED)
        claim = await _claim(ledger, allowed(definition=priced))

        completion = await _complete(ledger, claim, ToolOutcome.INDETERMINATE, kind=None)

        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.failure_kind is None
        assert completion.incurred_cost == UNKNOWN_COST
        assert completion.incurred_cost != priced.cost

    # --- the refusals, in the order ADR-0192 §2 fixes ----------------------

    async def test_completing_an_unknown_claim_is_refused(self, ledger: LedgerSubject) -> None:
        with pytest.raises(InvalidCompletionError):
            await ledger.complete_invocation(
                claim_id="no-such-claim",
                outcome=ToolOutcome.FAILED,
                incurred_cost=UNKNOWN_COST,
            )

        assert await _rows(ledger) == []

    async def test_completing_a_claim_twice_is_refused(self, ledger: LedgerSubject) -> None:
        claim = await _claim(ledger, allowed())
        await _complete(ledger, claim)

        with pytest.raises(InvalidCompletionError):
            await _complete(ledger, claim)

        assert len(await _rows(ledger)) == 2

    async def test_a_completion_naming_a_completion_is_refused(self, ledger: LedgerSubject) -> None:
        """``claim_id`` points at a claim; a completion is not one."""
        claim = await _claim(ledger, allowed())
        completion = await _complete(ledger, claim)

        with pytest.raises(InvalidCompletionError):
            await _complete(ledger, completion)

    async def test_a_kind_under_a_succeeded_outcome_is_an_argument_fault(
        self, ledger: LedgerSubject
    ) -> None:
        """The one combination the row's shape forbids, refused as an argument fault.

        Asserted with a ``claim_id`` naming nothing, so the case also pins the
        **order**: the argument fault is decided first, and an implementation
        checking the claim before its arguments raises the wrong class here.
        """
        with pytest.raises(AuditError) as raised:
            await ledger.complete_invocation(
                claim_id="no-such-claim",
                outcome=ToolOutcome.SUCCEEDED,
                incurred_cost=UNKNOWN_COST,
                failure_kind=ToolFailureKind.TIMED_OUT,
            )

        assert not isinstance(raised.value, InvalidCompletionError)
        assert await _rows(ledger) == []

    @pytest.mark.parametrize(
        "field_name", ["outcome", "failure_kind"], ids=["the-outcome", "the-failure-kind"]
    )
    async def test_an_enum_argument_that_cannot_be_looked_up_is_an_argument_fault(
        self, ledger: LedgerSubject, field_name: str
    ) -> None:
        """The case above, where the value defeats the *check* rather than failing it.

        ``ToolOutcome(value)`` looks the member up in a mapping, so it hashes what it
        was given: a ``str`` subclass whose ``__hash__`` raises leaves through a
        validator that never got as far as saying no. An implementation catching only
        what its validators mean to raise lets that out of ``complete_invocation`` as
        itself, and ADR-0192 §2's order is exhaustive over the classes a refusal
        arrives in.

        The claim is left open, because nothing was appended: this is an argument
        fault, decided before the store is touched at all.
        """
        claim = await _claim(ledger, allowed())
        arguments: dict[str, Any] = {
            "claim_id": claim.id,
            "outcome": ToolOutcome.FAILED,
            "incurred_cost": UNKNOWN_COST,
        }
        arguments[field_name] = Unhashable("SUCCEEDED" if field_name == "outcome" else "TIMED_OUT")

        with pytest.raises(AuditError) as raised:
            await ledger.complete_invocation(**arguments)

        assert not isinstance(raised.value, InvalidCompletionError)
        assert [row.id for row in await ledger.open_invocations(decision_id="d-1")] == [claim.id]

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            pytest.param("claim_id", None, id="a-claim-id-that-is-not-text"),
            pytest.param("outcome", "SUCCEEDED", id="an-outcome-that-is-not-the-enum"),
            pytest.param("incurred_cost", None, id="a-cost-that-is-not-a-cost"),
        ],
    )
    async def test_an_argument_the_signature_does_not_name_is_an_argument_fault(
        self, ledger: LedgerSubject, field_name: str, value: object
    ) -> None:
        """Every argument is *validated* before it is read, not dereferenced.

        ADR-0192 §2's two refusal orders are "exhaustive over the **classes a
        refusal arrives in**", so a value the signature does not name must arrive
        as ``AuditError`` and not as whatever a field read on it happens to raise.
        The failure this catches is an implementation that validates most of its
        arguments and reaches into one — ``incurred_cost.model_dump_json()`` on a
        ``None`` raises ``AttributeError``, which is not an ``AssistantError`` at
        all and leaves this boundary through a hole in the order.

        Static typing makes none of these reachable from a conforming caller,
        which is exactly why an implementation drifts here unnoticed: the two
        implementations diverged, one refusing a non-text ``claim_id`` and the
        other stringifying it into a lookup that then reported the *claim* as
        missing — a different class, for a fault that is not about the claim.
        """
        arguments: dict[str, Any] = {
            "claim_id": "no-such-claim",
            "outcome": ToolOutcome.FAILED,
            "incurred_cost": UNKNOWN_COST,
        }
        arguments[field_name] = value

        with pytest.raises(AuditError) as raised:
            await ledger.complete_invocation(**arguments)

        assert not isinstance(raised.value, InvalidCompletionError), (
            "an argument fault says nothing about the claim"
        )
        assert await _rows(ledger) == []

    async def test_a_cost_whose_model_dump_lies_records_its_real_field_state(
        self, ledger: LedgerSubject
    ) -> None:
        """``model_dump`` is an ordinary attribute, so it is not what may be trusted.

        A subclass overriding it — or an instance shadowing it through ``__dict__``
        — hands back a valid-but-false mapping, and an implementation that rebuilds
        from *that* records a price nobody submitted while every detachment case
        above still passes. ``orchestration/executor.py`` states the same reasoning
        for ``ToolResult``: the class serializer reads field values and consults no
        instance attribute.
        """

        class _Lying(ToolCost):
            def model_dump(self, **kwargs: object) -> dict[str, object]:
                return {"basis": CostBasis.PER_CALL, "amount": Decimal("999.00"), "currency": "USD"}

        claim = await _claim(ledger, allowed())
        lying = _Lying(basis=CostBasis.PER_CALL, amount=Decimal("1.00"), currency="USD")

        completion = await ledger.complete_invocation(
            claim_id=claim.id, outcome=ToolOutcome.FAILED, incurred_cost=lying
        )

        assert completion.incurred_cost is not None
        assert completion.incurred_cost.amount == Decimal("1.00")
        stored = [row for row in await _rows(ledger) if row.completes == claim.id]
        assert stored[0].incurred_cost == completion.incurred_cost

    @pytest.mark.parametrize(
        "tamper",
        [
            pytest.param("undescribable", id="a-field-that-cannot-be-described"),
            pytest.param("undeclared", id="undeclared-state-of-mixed-key-types"),
            pytest.param("hostile-key", id="a-key-that-refuses-to-be-compared"),
            pytest.param("cycle", id="a-container-that-contains-itself"),
            pytest.param("unspeakable", id="a-container-raising-what-cannot-be-described"),
        ],
    )
    async def test_malformed_model_state_is_still_an_argument_fault(
        self, ledger: LedgerSubject, tamper: str
    ) -> None:
        """The refusal must survive the value it is refusing (ADR-0192 §2).

        Every parameter is a way the *diagnostic* can destroy the diagnosis. A
        field whose ``__repr__`` raises turns a message that reaches for ``repr``
        into whatever it threw, from inside the ``except`` block. Undeclared
        ``__dict__`` keys of two different types turn a ``sorted`` over them into a
        ``TypeError``. A key that hashes like a field name and raises when compared
        turns the *lookup* itself into that exception, before any message is built
        — which is why an implementation must classify a non-``str`` key without
        touching it rather than ask a set. Each leaves this boundary as a class §2's
        order does not admit, and a consumer catching ``AuditError`` catches none of
        them.
        """
        claim = await _claim(ledger, allowed())
        cost = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1.00"), currency="USD")
        if tamper == "undescribable":
            cost.__dict__["amount"] = Undescribable()
        elif tamper == "hostile-key":
            hostile = HostileKey("basis")
            _undeclared(cost, {hostile: "shadow"})
            hostile.arm()
        elif tamper == "cycle":
            # A container that contains itself, in a field the model declares. An
            # implementation walking the value to check it must **terminate**: the
            # walk runs before the first ``await``, so one that re-expands the same
            # container spins on the event loop and the refusal never arrives at
            # all. It is nothing the serializer can render either — on a value like
            # this it raises ``AttributeError``, outside the classes §2's order
            # admits.
            cyclic: list[object] = []
            cyclic.append(cyclic)
            cost.__dict__["amount"] = cyclic
        elif tamper == "unspeakable":
            cost.__dict__["amount"] = Unspeakably([1])
        else:
            _undeclared(cost, {1: "one", "extra": "text"})

        with pytest.raises(AuditError):
            await ledger.complete_invocation(
                claim_id=claim.id, outcome=ToolOutcome.FAILED, incurred_cost=cost
            )

        assert [row.completes for row in await _rows(ledger)] == [None]

    async def test_a_claim_id_is_read_as_the_type_the_signature_names(
        self, ledger: LedgerSubject
    ) -> None:
        """``" x "`` and ``"x"`` name one claim, because ``Identifier`` strips.

        An implementation looking the raw text up refuses this as an unknown claim
        while the row it names is sitting open — and the two implementations must
        not disagree about which claims exist.
        """
        claim = await _claim(ledger, allowed())

        completion = await ledger.complete_invocation(
            claim_id=f"  {claim.id}  ", outcome=ToolOutcome.FAILED, incurred_cost=UNKNOWN_COST
        )

        assert completion.completes == claim.id
        assert await ledger.open_invocations(decision_id=claim.decision_id) == []

    async def test_a_completion_never_reports_an_unrecorded_authorisation(
        self, ledger: LedgerSubject
    ) -> None:
        """A completion names a claim, and the claim already names the decision."""
        with pytest.raises(AuditError) as raised:
            await ledger.complete_invocation(
                claim_id="nope", outcome=ToolOutcome.FAILED, incurred_cost=UNKNOWN_COST
            )

        assert not isinstance(raised.value, UnrecordedAuthorisationError)

    # --- detachment -------------------------------------------------------

    async def test_a_mutated_cost_does_not_reach_a_stored_row(self, ledger: LedgerSubject) -> None:
        """``frozen=True`` bounds the ordinary write path and not ``__dict__``.

        ADR-0021 §4 pins this for ``record`` rather than resting on a model's own
        immutability, and ``incurred_cost`` is the live object at the end of the
        chain that clause names — a shallow copy would share it.
        """
        claim = await _claim(ledger, allowed())
        cost = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1.00"), currency="USD")
        completion = await _complete(ledger, claim, cost=cost)

        cost.__dict__["amount"] = Decimal("999.00")

        assert completion.incurred_cost is not None
        assert completion.incurred_cost.amount == Decimal("1.00")
        stored = next(row for row in await _rows(ledger) if row.completes is not None)
        assert stored.incurred_cost is not None
        assert stored.incurred_cost.amount == Decimal("1.00")

    async def test_a_mutated_returned_row_does_not_reach_the_store(
        self, ledger: LedgerSubject
    ) -> None:
        """A returned row aliasing the stored one would rewrite history through it."""
        claim = await _claim(ledger, allowed())
        completion = await _complete(ledger, claim, cost=PRICED)

        completion.__dict__["outcome"] = ToolOutcome.SUCCEEDED
        assert completion.incurred_cost is not None
        completion.incurred_cost.__dict__["amount"] = Decimal("999.00")

        stored = next(row for row in await _rows(ledger) if row.completes is not None)
        assert stored.outcome is ToolOutcome.FAILED
        assert stored.incurred_cost == PRICED

    async def test_a_mutated_returned_claim_does_not_reach_open_invocations(
        self, ledger: LedgerSubject
    ) -> None:
        """``open_invocations``' own detachment case: a claim carries no cost.

        It cannot be covered by the completion cases above — it returns claims no
        completion names, so a completed claim has left that read entirely.
        """
        claim = await _claim(ledger, allowed("d-open"))

        claim.__dict__["decision_id"] = "d-somewhere-else"

        still_open = await ledger.open_invocations(decision_id="d-open")
        assert [row.decision_id for row in still_open] == ["d-open"]

    async def test_the_submitted_cost_is_observed_before_the_first_await(
        self, ledger: LedgerSubject, harness: LedgerHarness
    ) -> None:
        """ADR-0065: a post-call mutation test does not detect tearing.

        An implementation that validates, suspends and then re-reads the caller's
        object persists a cost nobody submitted, while passing every case above.
        """
        claim = await _claim(ledger, allowed())
        cost = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1.00"), currency="USD")
        suspension = harness.arm(ledger, "complete_invocation")
        completing = asyncio.ensure_future(_complete(ledger, claim, cost=cost))
        await suspension.reached()

        cost.__dict__["amount"] = Decimal("999.00")
        suspension.release()
        completion = await completing

        assert completion.incurred_cost is not None
        assert completion.incurred_cost.amount == Decimal("1.00")

    # --- cancelled while the write holds its resource (ADR-0192 §9) --------

    async def test_a_cancelled_completion_holds_its_resource_and_leaves_a_coherent_trail(
        self, harness: LedgerHarness
    ) -> None:
        """The completion is one of the two writes ADR-0192 §9 owes a surviving path.

        Two halves, and the second is what makes this ADR-0192's case rather than
        ADR-0060's.

        **The resource.** A cancelled completion must not hand the connection to
        the next caller while the work it started is still using it, which is
        ``core.protocols``' clause on any method that acquires one.

        **The trail.** Whatever the cancellation did, what is left must be a state
        §3's commit-state clause can name. Either the completion did not commit,
        and the claim is **left open** — "the honest state, and not a licence to
        write a wrong outcome" — or it committed before the failure, and it stands
        with the claim closed. Never a completion carrying an outcome nobody
        submitted, never two completions of one claim, and never a claim that is
        both closed and absent from the completions. The cancelled call submits
        ``SUCCEEDED`` and the surviving one ``FAILED``, so an implementation that
        wrote the wrong row's outcome is visible rather than plausible.

        Both implementations are conforming and they land differently: a store that
        shields its worker (ADR-0054) commits the cancelled completion, and one
        whose write is on the event loop never runs its body. Asserting the
        *disjunction* is the contract; asserting either branch would write one
        implementation into the suite.
        """
        ledger = harness.open()
        authorisation = allowed("d-open", definition=natural())
        first_claim = await _claim(ledger, authorisation)
        second_claim = await _claim(ledger, authorisation)

        await _cancelled_inside_the_resource(
            harness,
            ledger,
            "complete_invocation",
            lambda: ledger.complete_invocation(
                claim_id=first_claim.id, outcome=ToolOutcome.SUCCEEDED, incurred_cost=PRICED
            ),
            lambda: ledger.complete_invocation(
                claim_id=second_claim.id, outcome=ToolOutcome.FAILED, incurred_cost=UNKNOWN_COST
            ),
        )

        held = await _rows(ledger)
        assert len({row.id for row in held}) == len(held), "no id names two rows"
        completions = [row for row in held if row.completes is not None]
        surviving = [row for row in completions if row.completes == second_claim.id]
        assert len(surviving) == 1, "the second completion landed whole"
        assert surviving[0].outcome is ToolOutcome.FAILED
        assert surviving[0].incurred_cost == UNKNOWN_COST

        open_now = {row.id for row in await ledger.open_invocations(decision_id="d-open")}
        cancelled = [row for row in completions if row.completes == first_claim.id]
        if cancelled:
            assert len(cancelled) == 1, "a claim is completed once"
            assert cancelled[0].outcome is ToolOutcome.SUCCEEDED, (
                "a committed completion carries what its caller submitted, not another outcome"
            )
            assert cancelled[0].incurred_cost == PRICED
            assert first_claim.id not in open_now, "a completed claim has left the open set"
        else:
            assert first_claim.id in open_now, (
                "an uncommitted completion leaves its claim open, which is the honest state"
            )

    # --- the collaborators, split where ADR-0026 §2 splits them ------------

    async def test_a_rejected_clock_reading_surfaces_as_this_layers_error(
        self, harness: LedgerHarness
    ) -> None:
        """The guard's own rejection is translated, so no caller meets a bare ``ValueError``."""
        ledger = harness.open(now=ScriptedClock([AT, "not an instant"]))
        claim = await _claim(ledger, allowed())

        with pytest.raises(AuditError) as raised:
            await _complete(ledger, claim)

        assert isinstance(raised.value.__cause__, ClockReadingError)
        assert len(await _rows(ledger)) == 1

    async def test_an_exception_the_clock_callable_raises_is_not_relabelled(
        self, harness: LedgerHarness
    ) -> None:
        """ADR-0026 §2: the guard covers the reading, not the invocation.

        Relabelling a callable's own failure would destroy its type and its cause,
        which is the reason that section gives.
        """
        boom = RuntimeError("the clock is down")
        ledger = harness.open(now=ScriptedClock([AT, boom]))
        claim = await _claim(ledger, allowed())

        with pytest.raises(RuntimeError) as raised:
            await _complete(ledger, claim)

        assert raised.value is boom

    async def test_an_exception_the_factory_callable_raises_is_not_relabelled(
        self, harness: LedgerHarness
    ) -> None:
        """The same arm on the other collaborator, which an earlier draft left implicit."""
        claimed = ScriptedIdentifiers()
        ledger = harness.open(identifiers=claimed)
        claim = await _claim(ledger, allowed())
        claimed.raises = RuntimeError("the allocator is down")

        with pytest.raises(RuntimeError, match="allocator"):
            await _complete(ledger, claim)

        assert len(await _rows(ledger)) == 1

    async def test_a_factory_returning_an_unusable_value_is_a_guard_rejection(
        self, harness: LedgerHarness
    ) -> None:
        """A non-conforming collaborator's *output* is not an exception of its own.

        Without this an implementation may build the row before it validates the
        id, and a blank id then reaches the store as a raw model or driver failure
        that one implementation raises and another quietly accepts.
        """
        drawn = ScriptedIdentifiers()
        ledger = harness.open(identifiers=drawn)
        claim = await _claim(ledger, allowed())
        before = await _rows(ledger)
        drawn.returns = "   "

        with pytest.raises(AuditError):
            await _complete(ledger, claim)

        assert await _rows(ledger) == before

    @pytest.mark.parametrize(
        "drawn",
        [
            pytest.param(" claim-1 ", id="whitespace-around-a-held-id"),
            pytest.param("\ud800", id="text-with-no-utf-8-encoding"),
        ],
    )
    async def test_a_factory_output_is_read_as_the_type_before_it_is_used(
        self, harness: LedgerHarness, drawn: str
    ) -> None:
        """A drawn id is normalised and refused by ``DurableIdentifier``, not by a likeness.

        Both parameters are cases a hand-rolled "text, and not blank" check passes
        and the type does not, and each is a different loss.

        ``" claim-1 "`` is the sharper one. ``Identifier`` **strips**, so it and
        ``"claim-1"`` are one identifier to every model that holds one — but two to
        a check that returns its input unchanged. The collision check then clears,
        and the row is stored under the id the *model* carries, replacing the claim
        already there: an append-only store losing a row, and one durable
        identifier naming two acts, which is precisely what ADR-0192 §2's single id
        space forbids.

        A lone surrogate has no UTF-8 encoding at all (ADR-0087 §7), so no row can
        be written down under it; ``.strip()`` cannot see that.

        The assertion is on what the store *holds*, not on which of the two the
        implementation takes: refusing the draw and drawing again are both
        conforming, and neither may lose the live row.
        """
        drawing = ScriptedIdentifiers(forced=["claim-1"])
        ledger = harness.open(identifiers=drawing)
        claim = await _claim(ledger, allowed())
        assert claim.id == "claim-1"
        before = await _rows(ledger)
        drawing.forced = [drawn, "fresh-1"]

        with contextlib.suppress(AuditError):
            await _complete(ledger, claim)

        held = {row.id: row for row in await _rows(ledger)}
        assert held["claim-1"] == before[0], "the claim already there is not replaced"
        assert set(held) <= {"claim-1", "fresh-1"}, "no row is stored under an id the type refuses"

    # --- what a broken store surfaces as (ADR-0192 §9) ---------------------

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(_complete, id="the-completion-append"),
            pytest.param(_bounded_listing, id="the-bounded-listing"),
            pytest.param(_whole_listing, id="the-whole-listing"),
        ],
    )
    async def test_a_store_that_cannot_be_reached_surfaces_as_this_layers_error(
        self,
        harness: LedgerHarness,
        call: Callable[[LedgerSubject, ToolInvocation], Awaitable[object]],
    ) -> None:
        """ADR-0192 §9 pins the translated failures as **classes**.

        "A store that cannot be read and a store that cannot be written each
        surface as an ``AuditError`` carrying its cause, none escapes as a
        non-``AssistantError``, and none arrives as one of the three named
        refusals." All three limbs are asserted: an implementation letting a driver
        error out gives a consumer catching ``AuditError`` nothing to catch, one
        that swallows the cause destroys the only account of what went wrong, and
        one that reports ``InvalidCompletionError`` says the claim was bad when the
        store was.

        Each *distinct* path is driven, because they are separate call sites that
        translate separately — an append inside a transaction, a bounded read and an
        unbounded one.
        """
        ledger = harness.open()
        claim = await _claim(ledger, allowed())
        if not harness.break_store(ledger):
            pytest.skip("this store cannot fail, so an unreachable one is unreachable")

        with pytest.raises(AuditError) as raised:
            await call(ledger, claim)

        assert not isinstance(
            raised.value, InvalidCompletionError | UnrecordedAuthorisationError
        ), "a broken store says nothing about the claim or the authorisation"
        assert raised.value.__cause__ is not None, "the backend's failure is the account"
        assert not isinstance(raised.value.__cause__, AssistantError), (
            "the cause is the backend's own failure, not this layer's"
        )

    # --- the redraw, over one id space ------------------------------------

    async def test_one_collision_is_drawn_away_from_and_reaches_nobody(
        self, harness: LedgerHarness
    ) -> None:
        """A collision is not by itself evidence of a broken collaborator.

        The append proceeds under the id that cleared, the live row is untouched,
        and nothing about the collision reaches the caller, the trail or a
        diagnostic — no row was appended under a colliding id, so there is nothing
        to report.
        """
        drawn = ScriptedIdentifiers(forced=["claim-1"])
        ledger = harness.open(identifiers=drawn)
        claim = await _claim(ledger, allowed())
        assert claim.id == "claim-1"
        drawn.forced = ["claim-1"]

        completion = await _complete(ledger, claim)

        assert completion.id != "claim-1"
        still = await ledger.open_invocations(decision_id="d-1")
        assert still == []
        held = {row.id: row for row in await _rows(ledger)}
        assert held["claim-1"].completes is None
        assert held["claim-1"].decision_id == claim.decision_id
        assert held["claim-1"].recorded_at == claim.recorded_at

    async def test_an_exhausted_redraw_refuses_and_appends_nothing(
        self, harness: LedgerHarness
    ) -> None:
        """Only an exhausted bound is a refusal, and it is not one of the named three."""
        drawn = ScriptedIdentifiers(forced=["claim-1"])
        ledger = harness.open(identifiers=drawn)
        claim = await _claim(ledger, allowed())
        before = await _rows(ledger)
        drawn.always = "claim-1"

        with pytest.raises(AuditError) as raised:
            await _complete(ledger, claim)

        assert not isinstance(raised.value, InvalidCompletionError | AuthorisationSpentError), (
            "an exhausted redraw says nothing about the authorisation"
        )
        assert await _rows(ledger) == before

    async def test_the_redraw_walks_several_occupied_ids_of_both_kinds(
        self, harness: LedgerHarness
    ) -> None:
        """One id space, and it is every row the store holds (ADR-0192 §2).

        An implementation that redraws exactly once refuses here; one that checks
        invocation rows alone appends under the **decision's** id, which the joined
        read then resolves to two different rows under one identifier.
        """
        drawn = ScriptedIdentifiers(forced=["claim-1"])
        ledger = harness.open(identifiers=drawn)
        authorisation = allowed("d-seeded")
        claim = await _claim(ledger, authorisation)
        before = {row.id: row for row in await _rows(ledger)}
        drawn.forced = ["claim-1", "d-seeded", "fresh-1"]

        completion = await _complete(ledger, claim)

        assert completion.id == "fresh-1"
        after = {row.id: row for row in await _rows(ledger)}
        assert after["claim-1"] == before["claim-1"]
        stored = await ledger.get("d-seeded")
        assert stored == authorisation

    # --- erasure ----------------------------------------------------------

    async def test_clear_removes_both_kinds_and_counts_both(self, ledger: LedgerSubject) -> None:
        """Asserting emptiness alone leaves the pre-ADR-0192 count passing (§6)."""
        claim = await _claim(ledger, allowed())
        await _complete(ledger, claim)

        assert await ledger.clear() == 3

        assert await ledger.export() == []
        assert await ledger.export_invocations() == []
        assert await ledger.recent_invocations(limit=5) == []
        assert await ledger.open_invocations(decision_id="d-1") == []

    async def test_a_completion_whose_claim_was_erased_is_refused_and_nothing_returns(
        self, ledger: LedgerSubject
    ) -> None:
        """``clear()`` wins, and the store does not put back what the user destroyed.

        ADR-0192 §3's "the claim is left open" postcondition is the one thing that
        cannot follow here: the claim was erased, so **no claim remains**, and
        recreating the row is the one answer no store may give.
        """
        claim = await _claim(ledger, allowed())
        await ledger.clear()

        with pytest.raises(InvalidCompletionError):
            await _complete(ledger, claim)

        assert await _rows(ledger) == []

    async def test_a_completion_racing_clear_lands_before_it_or_is_refused_after_it(
        self, ledger: LedgerSubject, harness: LedgerHarness
    ) -> None:
        """§6's ``clear()`` wins over a write in flight as much as over one written.

        An implementation may validate the claim, let the erasure land, and then
        append into a store emptied after the check that admitted it.
        """
        claim = await _claim(ledger, allowed())
        suspension = harness.arm(ledger, "complete_invocation")
        completing = asyncio.ensure_future(_complete(ledger, claim))
        await suspension.reached()
        erasing = asyncio.ensure_future(ledger.clear())
        await asyncio.sleep(0)
        suspension.release()
        outcome = await asyncio.gather(completing, erasing, return_exceptions=True)

        assert await _rows(ledger) == [], "no row survives the erasure, and none follows it"
        failure = outcome[0]
        assert not isinstance(failure, BaseException) or isinstance(failure, InvalidCompletionError)

    async def test_two_coroutines_completing_one_claim_append_exactly_one_row(
        self, ledger: LedgerSubject
    ) -> None:
        """The completion invariant under a race, as ADR-0021 §4 exercises its own.

        An implementation that separates the "already completed?" check from the
        write passes the sequential case and appends two rows here.
        """
        claim = await _claim(ledger, allowed())

        results = await asyncio.gather(
            _complete(ledger, claim), _complete(ledger, claim), return_exceptions=True
        )

        appended = [row for row in results if not isinstance(row, BaseException)]
        refused = [row for row in results if isinstance(row, InvalidCompletionError)]
        assert len(appended) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"
        assert len([row for row in await _rows(ledger) if row.completes is not None]) == 1

    # --- the same collaborator arms, on the claim path ---------------------
    # ADR-0192 §2 writes the redraw and the factory's two failure shapes over *the
    # append*, not over one member, and a suite testing only ``complete_invocation``
    # leaves the claim's write-once guarantee unpinned. These are the twins of the
    # cases in the narrow suite above, and each is owed.

    async def test_a_claims_collision_is_drawn_away_from_and_reaches_nobody(
        self, harness: LedgerHarness
    ) -> None:
        ledger = harness.open(identifiers=ScriptedIdentifiers(forced=["claim-1"]))
        authorisation = allowed(definition=natural())
        first = await _claim(ledger, authorisation)
        assert first.id == "claim-1"

        second = await ledger.claim_invocation(decision=authorisation)

        assert second.id != "claim-1"
        held = {row.invocation.id: row.invocation for row in await ledger.export_invocations()}
        assert held["claim-1"].recorded_at == first.recorded_at
        assert held["claim-1"].completes is None

    async def test_an_exhausted_redraw_on_a_claim_refuses_and_appends_nothing(
        self, harness: LedgerHarness
    ) -> None:
        drawn = ScriptedIdentifiers(forced=["claim-1"])
        ledger = harness.open(identifiers=drawn)
        authorisation = allowed(definition=natural())
        await _claim(ledger, authorisation)
        before = await _rows(ledger)
        drawn.always = "claim-1"

        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=authorisation)

        assert not isinstance(
            raised.value, AuthorisationSpentError | UnrecordedAuthorisationError
        ), "an exhausted redraw says nothing about the authorisation"
        assert await _rows(ledger) == before

    async def test_a_claims_redraw_walks_several_occupied_ids_of_both_kinds(
        self, harness: LedgerHarness
    ) -> None:
        drawn = ScriptedIdentifiers(forced=["claim-1"])
        ledger = harness.open(identifiers=drawn)
        authorisation = allowed("d-seeded", definition=natural())
        first = await _claim(ledger, authorisation)
        drawn.forced = ["claim-1", "d-seeded", "fresh-1"]

        second = await ledger.claim_invocation(decision=authorisation)

        assert second.id == "fresh-1"
        held = {row.invocation.id: row.invocation for row in await ledger.export_invocations()}
        assert held["claim-1"] == first
        assert await ledger.get("d-seeded") == authorisation

    async def test_a_factory_raising_on_a_claim_is_not_relabelled(
        self, harness: LedgerHarness
    ) -> None:
        drawn = ScriptedIdentifiers()
        ledger = harness.open(identifiers=drawn)
        authorisation = allowed()
        await ledger.record(authorisation)
        drawn.raises = RuntimeError("the allocator is down")

        with pytest.raises(RuntimeError, match="allocator"):
            await ledger.claim_invocation(decision=authorisation)

        assert await _rows(ledger) == []

    async def test_a_factory_returning_an_unusable_value_on_a_claim_is_a_guard_rejection(
        self, harness: LedgerHarness
    ) -> None:
        drawn = ScriptedIdentifiers()
        ledger = harness.open(identifiers=drawn)
        authorisation = allowed()
        await ledger.record(authorisation)
        drawn.returns = 17

        with pytest.raises(AuditError):
            await ledger.claim_invocation(decision=authorisation)

        assert await _rows(ledger) == []

    # --- the joined listings (ADR-0192 §2) --------------------------------

    async def test_a_joined_row_carries_its_decisions_tool_and_capability(
        self, ledger: LedgerSubject
    ) -> None:
        """The tool's identity lives on the decision, which is why the store joins.

        A bare ``ToolInvocation`` cannot be rendered under ADR-0192 §4's floor at
        all, and a bounded page may hold a completion whose claim and whose
        decision are not on it.
        """
        claim = await _claim(ledger, allowed(definition=spendable(id="smtp-1")))

        rows = await ledger.export_invocations()

        assert [row.invocation.id for row in rows] == [claim.id]
        assert rows[0].tool == "smtp-1"
        assert rows[0].capability == "send_email"

    @pytest.mark.parametrize("egress", [True, False], ids=["egress", "local"])
    async def test_egress_call_is_true_exactly_when_the_decision_carries_a_binding(
        self, ledger: LedgerSubject, *, egress: bool
    ) -> None:
        """A boolean and not the binding (ADR-0192 §2).

        Who received the bytes is ``recent_decisions``' to render from the binding
        itself; a second copy here would be the "second shape that must agree"
        ADR-0184 §2 refuses, in service of a rendering another operation owes.
        """
        await _claim(ledger, allowed(egress=egress))

        rows = await ledger.export_invocations()

        assert rows[0].egress_call is egress

    async def test_a_joined_row_carries_no_second_copy_of_the_binding(
        self, ledger: LedgerSubject
    ) -> None:
        """It carries nothing else — no ruling, reason, binding, destination or digest."""
        await _claim(ledger, allowed(egress=True))

        rows = await ledger.export_invocations()

        assert set(type(rows[0]).model_fields) == {
            "invocation",
            "tool",
            "capability",
            "egress_call",
        }

    async def test_the_listings_are_newest_first_with_ties_broken_by_id(
        self, harness: LedgerHarness
    ) -> None:
        """``recent``'s total order, carried onto the second row kind.

        A frozen clock puts every row at one instant, so the tie-break is the whole
        of the order — an implementation leaving insertion order for a tie fails
        here and passes every other case.
        """
        ledger = harness.open(
            now=ScriptedClock([AT]), identifiers=ScriptedIdentifiers(forced=["b", "a", "c"])
        )
        authorisation = allowed(definition=natural())
        await _claim(ledger, authorisation)
        await ledger.claim_invocation(decision=authorisation)
        await ledger.claim_invocation(decision=authorisation)

        rows = await ledger.export_invocations()

        assert [row.invocation.id for row in rows] == ["a", "b", "c"]

    async def test_a_later_row_comes_back_first(self, harness: LedgerHarness) -> None:
        ledger = harness.open(now=StepClock())
        authorisation = allowed(definition=natural())
        first = await _claim(ledger, authorisation)
        second = await ledger.claim_invocation(decision=authorisation)

        rows = await ledger.export_invocations()

        assert [row.invocation.id for row in rows] == [second.id, first.id]

    @pytest.mark.parametrize("limit", [1, 2, 3, 9], ids=["short", "equal", "one-past", "far-past"])
    async def test_a_bounded_listing_is_a_prefix_of_the_whole_one(
        self, harness: LedgerHarness, limit: int
    ) -> None:
        """The invariant a store that ordered its two reads differently would break."""
        ledger = harness.open(now=StepClock())
        authorisation = allowed(definition=natural())
        await _claim(ledger, authorisation)
        await ledger.claim_invocation(decision=authorisation)

        whole = await ledger.export_invocations()
        bounded = await ledger.recent_invocations(limit=limit)

        assert bounded == whole[:limit]

    @pytest.mark.parametrize("limit", [0, -1], ids=["zero", "negative"])
    async def test_a_limit_that_is_not_strictly_positive_is_refused(
        self, ledger: LedgerSubject, limit: int
    ) -> None:
        """``recent``'s own refusal, for ``recent``'s own reason.

        SQLite reads ``LIMIT -1`` as *no limit at all*, so the one call offering a
        bounded read of a Tier 1 store would become the unbounded read it exists to
        avoid.
        """
        with pytest.raises(ValueError, match="strictly positive"):
            await ledger.recent_invocations(limit=limit)

    async def test_a_listing_hands_back_a_detached_snapshot(self, ledger: LedgerSubject) -> None:
        claim = await _claim(ledger, allowed())
        await _complete(ledger, claim, cost=PRICED)
        rows = await ledger.export_invocations()

        rows[0].__dict__["tool"] = "somebody-elses-tool"
        held = rows[0].invocation.incurred_cost
        if held is not None:
            held.__dict__["amount"] = Decimal("999.00")

        again = await ledger.export_invocations()
        assert again[0].tool == "smtp"
        assert again[0].invocation.incurred_cost == PRICED

    # --- the id space, from the caller's side ------------------------------

    async def test_a_record_racing_a_claim_on_one_id_leaves_one_record_under_it(
        self, harness: LedgerHarness
    ) -> None:
        """The concurrent arm of ``AuditTrailContract``'s sequential case.

        The refusal is inside ``record``'s own atomic act, so a check-then-write
        implementation passes the sequential case and loses this one — leaving two
        records under one durable identifier, which the joined read then resolves
        to two different rows. Either winner is admissible: where the decision
        lands first the ledger simply draws again.
        """
        ledger = harness.open(identifiers=ScriptedIdentifiers(forced=["contested", "spare"]))
        authorisation = allowed(definition=natural())
        await ledger.record(authorisation)

        results = await asyncio.gather(
            ledger.record(decision("contested")),
            ledger.claim_invocation(decision=authorisation),
            return_exceptions=True,
        )

        named = await ledger.get("contested")
        rows = [row.invocation.id for row in await ledger.export_invocations()]
        assert not (named is not None and "contested" in rows), (
            f"one identifier names one record, of either kind: {results}"
        )


class InvocationLedgerContract(InvocationCompleterContract):
    """Everything above, plus the claim — which is where the consume lives."""

    # --- the claim row ----------------------------------------------------

    async def test_a_first_claim_under_a_recorded_allow_is_admitted(
        self, ledger: LedgerSubject
    ) -> None:
        authorisation = allowed("d-first")
        await ledger.record(authorisation)

        claim = await ledger.claim_invocation(decision=authorisation)

        assert claim.decision_id == "d-first"
        assert claim.completes is None
        assert claim.outcome is None
        assert claim.incurred_cost is None
        assert claim.failure_kind is None

    async def test_every_row_id_comes_from_the_injected_factory(
        self, harness: LedgerHarness
    ) -> None:
        """No caller supplies one, and a claim and its own completion differ."""
        ledger = harness.open(identifiers=ScriptedIdentifiers(label="minted"))
        claim = await _claim(ledger, allowed())

        completion = await _complete(ledger, claim)

        assert claim.id.startswith("minted-")
        assert completion.id.startswith("minted-")
        assert claim.id != completion.id

    async def test_two_claims_under_one_decision_get_distinct_ids(
        self, ledger: LedgerSubject
    ) -> None:
        """A derivation from ``decision_id`` collides here, which is why there is none."""
        authorisation = allowed(definition=spendable(side_effecting=False))
        first = await _claim(ledger, authorisation)

        second = await ledger.claim_invocation(decision=authorisation)

        assert first.id != second.id

    async def test_a_cancelled_claim_holds_its_resource_and_leaves_a_coherent_trail(
        self, harness: LedgerHarness
    ) -> None:
        """The claim is the other write ADR-0192 §9 owes a surviving path.

        The resource half is :meth:`InvocationCompleterContract`'s. The trail half
        is §1's: a claim is a write-ahead record of an attempt, so what the store
        holds afterwards must be **observable** — §9 says in terms that "where the
        claim's outcome cannot be observed, the implementation does not satisfy §1
        and the conformance suite says so". Either the append landed, in which case
        the claim is a whole row and ``open_invocations`` returns it, or it did
        not, in which case nothing of it is in the store. Never a half-row, never
        an id naming two acts, and never a claim the recovery read cannot see.

        Under a non-spendable authorisation so a second claim is admissible at all
        — the consume is not what this case is about, and refusing the second would
        make the blocked-caller check untestable.
        """
        ledger = harness.open()
        authorisation = allowed("d-open", definition=natural())
        await ledger.record(authorisation)

        await _cancelled_inside_the_resource(
            harness,
            ledger,
            "claim_invocation",
            lambda: ledger.claim_invocation(decision=authorisation),
            lambda: ledger.claim_invocation(decision=authorisation),
        )

        held = await _rows(ledger)
        assert 1 <= len(held) <= 2, "the surviving claim landed, and no call appended twice"
        assert len({row.id for row in held}) == len(held), "no id names two acts"
        assert all(row.completes is None for row in held)
        assert all(row.decision_id == "d-open" for row in held)
        observable = {row.id for row in await ledger.open_invocations(decision_id="d-open")}
        assert observable == {row.id for row in held}, (
            "every claim that landed is one the recovery read can see"
        )

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(_a_claim, id="the-claim-append"),
            pytest.param(_the_open_set, id="the-recovery-read"),
        ],
    )
    async def test_a_broken_store_surfaces_as_this_layers_error_on_the_claim_paths(
        self,
        harness: LedgerHarness,
        call: Callable[[LedgerSubject, PermissionDecision], Awaitable[object]],
    ) -> None:
        """The same clause on the two members only the wide face has.

        ``open_invocations`` is the sharpest of the four: the recovery scan acts on
        its answer, and an empty list from a store that could not be read would
        report "no claim was left open" for a store that cannot say.
        """
        ledger = harness.open()
        authorisation = allowed(definition=natural())
        await ledger.record(authorisation)
        if not harness.break_store(ledger):
            pytest.skip("this store cannot fail, so an unreachable one is unreachable")

        with pytest.raises(AuditError) as raised:
            await call(ledger, authorisation)

        assert not isinstance(
            raised.value, UnrecordedAuthorisationError | AuthorisationSpentError
        ), "a broken store says nothing about the authorisation"
        assert raised.value.__cause__ is not None, "the backend's failure is the account"
        assert not isinstance(raised.value.__cause__, AssistantError), (
            "the cause is the backend's own failure, not this layer's"
        )

    # --- what the store must already hold ---------------------------------

    async def test_a_claim_under_an_unrecorded_decision_is_refused(
        self, ledger: LedgerSubject
    ) -> None:
        with pytest.raises(UnrecordedAuthorisationError):
            await ledger.claim_invocation(decision=allowed("d-nobody"))

        assert await _rows(ledger) == []

    async def test_a_decision_equal_but_for_its_value_is_refused_like_one_never_held(
        self, ledger: LedgerSubject
    ) -> None:
        """ADR-0192 §1's attack, constructed: an id lookup alone admits it.

        A caller takes the id of a recorded, harmless ``ALLOW`` and builds a second
        ``ALLOW`` carrying that id and a dangerous ``ToolDefinition``. ADR-0029
        §2's three checks inspect the decision the *call* carries and pass; a
        ledger holding only the id finds the harmless row and admits the claim; the
        dangerous callable runs and the row then reports the harmless tool. That is
        worse than an unrecorded execution — it is a **misrecorded** one.
        """
        harmless = allowed("d-1", definition=spendable(id="harmless", risk_level=RiskLevel.LOW))
        await ledger.record(harmless)
        dangerous = allowed(
            "d-1", definition=spendable(id="dangerous", risk_level=RiskLevel.CRITICAL)
        )

        with pytest.raises(UnrecordedAuthorisationError):
            await ledger.claim_invocation(decision=dangerous)

        assert await _rows(ledger) == []

    @pytest.mark.parametrize(
        "outcome", [PermissionOutcome.CONFIRM, PermissionOutcome.DENY], ids=["confirm", "deny"]
    )
    async def test_a_claim_under_a_decision_that_is_not_an_allow_is_refused(
        self, ledger: LedgerSubject, outcome: PermissionOutcome
    ) -> None:
        unauthorised = decision("d-1", request=action(tool=spendable()), ruled=ruling(outcome))
        await ledger.record(unauthorised)

        with pytest.raises(UnrecordedAuthorisationError):
            await ledger.claim_invocation(decision=unauthorised)

    @pytest.mark.parametrize(
        "given",
        [
            pytest.param(None, id="a-value-with-no-fields-at-all"),
            pytest.param(HostileMapping(), id="a-mapping-that-refuses-to-be-read"),
        ],
    )
    async def test_a_value_that_is_not_a_decision_is_an_argument_fault(
        self, ledger: LedgerSubject, given: object
    ) -> None:
        """The decision is *validated* before any field of it is read.

        ``decision.model_dump()`` is a field read, so an implementation calling it
        first lets a value that is not a decision escape as ``AttributeError`` —
        which is not an ``AssistantError``, and so is outside the classes ADR-0192
        §2's order is exhaustive over. ``FakeToolInvoker._revalidated`` states the
        same ordering for the same reason (ADR-0152 §1).

        The second case is the other half of that ordering: validating a value that
        is not a model *walks* it, so the refusal has to survive the walk as well as
        the read it replaces.
        """
        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=cast("PermissionDecision", given))

        assert not isinstance(raised.value, UnrecordedAuthorisationError | AuthorisationSpentError)
        assert await _rows(ledger) == []

    async def test_a_decision_whose_model_dump_lies_is_judged_on_its_real_field_state(
        self, ledger: LedgerSubject
    ) -> None:
        """§1's equality check is on the value, so it cannot rest on an overridable method.

        The store holds a harmless ``ALLOW``. The caller passes a decision whose
        *fields* authorise something else under that same id and whose
        ``model_dump`` returns the harmless one. An implementation rebuilding from
        the mapping compares the store's row against a decision the caller never
        held, finds them equal, and admits a claim under an authorisation for a
        different act — which is exactly the substitution §1's whole-value equality
        exists to refuse.
        """
        harmless = allowed("d-1", definition=natural())
        await ledger.record(harmless)
        dangerous = allowed("d-1", definition=spendable(tool_id="wire-transfer"))

        class _Lying(PermissionDecision):
            def model_dump(self, **kwargs: object) -> dict[str, object]:
                return harmless.model_dump()

        lying = _Lying.model_construct(**dict(dangerous))

        with pytest.raises(UnrecordedAuthorisationError):
            await ledger.claim_invocation(decision=lying)

        assert await _rows(ledger) == []

    @pytest.mark.parametrize(
        "depth", ["tool", "cost"], ids=["the-tool", "the-cost-inside-the-tool"]
    )
    async def test_a_decision_carrying_a_subclass_beneath_it_is_an_argument_fault(
        self, ledger: LedgerSubject, depth: str
    ) -> None:
        """§1 compares the decision the ledger was *passed*, and a subclass survives.

        ``PermissionDecision.tool`` is declared a ``ToolDefinition``, and pydantic's
        default ``revalidate_instances="never"`` keeps whatever instance the caller
        constructed the decision with. So this decision is **normally constructed**
        rather than tampered, and it is unequal to the recorded one by the frozen
        model's own equality — the assertion below states that premise rather than
        assuming it. An implementation that compares a snapshot serialised through
        the *declared* type drops the subclass's own field, finds the two equal, and
        admits a claim under an authorisation for a tool the store never approved:
        ADR-0192 §1's attack shape, reached without tampering with anything.

        The refusal is the argument fault, first in ADR-0192 §2's order — the value
        cannot be recorded as what it is, so no comparison that would lose it is
        reached. Both depths are pinned because the check has to *descend*: the
        ``ToolCost`` inside the definition is a level below the field the shape is
        usually stated on.
        """
        recorded = allowed("d-1")
        await ledger.record(recorded)

        if depth == "tool":

            class _ExtendedTool(ToolDefinition):
                smuggled: str = "state the store never approved"

            substituted: ToolDefinition = _ExtendedTool(**dict(recorded.tool))
        else:

            class _ExtendedCost(ToolCost):
                smuggled: str = "state the store never approved"

            substituted = recorded.tool.model_copy(
                update={"cost": _ExtendedCost(**dict(recorded.tool.cost))}
            )
        carried = PermissionDecision(**{**dict(recorded), "tool": substituted})
        assert carried != recorded

        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=carried)

        assert not isinstance(raised.value, UnrecordedAuthorisationError | AuthorisationSpentError)
        assert await _rows(ledger) == []

    @pytest.mark.parametrize(
        "shape",
        [
            pytest.param("root-subclass", id="a-subclass-that-declares-nothing-of-its-own"),
            pytest.param("list-for-tuple", id="a-list-where-the-model-declares-a-tuple"),
        ],
    )
    async def test_a_decision_the_rebuild_would_normalise_is_not_the_one_it_was_passed(
        self, ledger: LedgerSubject, shape: str
    ) -> None:
        """§1's equality is on the value passed, and a rebuild can *normalise* as well as drop.

        The companion above is about state a rebuild would **drop**. These two lose
        nothing at all: every field of the first is identical and only the runtime
        model type differs, and the second differs only in the container the values
        sit in. Both are nonetheless unequal by the frozen model's own equality —
        asserted below rather than assumed — so §1 says the trail records no decision
        equal to what was passed, and the claim is refused as an authorisation the
        store never recorded.

        An implementation that decides the admission over a snapshot alone admits
        both, because normalising is exactly what building the snapshot does. The way
        out is not to compare the caller's live object inside the atomic operation —
        ADR-0065 forbids that re-read — but to establish that the value *is* its own
        snapshot before the first suspension, and then compare snapshots.
        """
        recorded = allowed("d-1", egress=shape == "list-for-tuple")
        await ledger.record(recorded)

        if shape == "root-subclass":

            class _Restated(PermissionDecision):
                """Declares nothing of its own, so no field state can differ."""

            handed: PermissionDecision = _Restated(**dict(recorded))
        else:
            handed = recorded.model_copy(deep=True)
            assert handed.egress_binding is not None
            handed.egress_binding.__dict__["spans"] = []

        assert handed != recorded

        with pytest.raises(UnrecordedAuthorisationError):
            await ledger.claim_invocation(decision=handed)

        assert await _rows(ledger) == []
        assert await ledger.get("d-1") == recorded, "the recorded decision is untouched"

    async def test_a_decision_whose_schema_repeats_an_empty_array_is_ordinary(
        self, ledger: LedgerSubject
    ) -> None:
        """The control the cycle refusal needs, and it is not a hypothetical.

        :data:`~ai_assistant.core.types.FrozenJson` freezes a JSON array to a
        ``tuple``, and the empty tuple is interned — so a ``parameters_schema``
        carrying ``"required": []`` and ``"examples": []`` puts *one object* under two
        keys of a perfectly ordinary declaration. An implementation that refuses every
        container it reaches twice refuses this decision, which is valid, acyclic, and
        the shape any tool with two empty arrays in its schema has. Reaching a
        container twice is not a cycle; containing itself is.
        """
        schema: dict[str, object] = {
            "type": "object",
            "properties": {},
            "required": [],
            "examples": [],
        }
        authorisation = allowed("d-1", definition=spendable(parameters_schema=schema))
        await ledger.record(authorisation)

        claim = await ledger.claim_invocation(decision=authorisation)

        assert claim.decision_id == "d-1"
        assert await ledger.get("d-1") == authorisation

    @pytest.mark.parametrize(
        "tamper",
        [
            pytest.param("undescribable", id="a-field-that-cannot-be-described"),
            pytest.param("undeclared", id="undeclared-state-of-mixed-key-types"),
            pytest.param("hostile-key", id="a-key-that-refuses-to-be-compared"),
            pytest.param("cycle", id="a-container-that-contains-itself"),
            pytest.param("hidden-model", id="a-model-hidden-in-a-frozen-mapping"),
            pytest.param("unwalkable", id="a-container-that-refuses-to-be-iterated"),
            pytest.param("deep", id="a-model-under-two-thousand-containers"),
            pytest.param("unspeakable", id="a-container-raising-what-cannot-be-described"),
        ],
    )
    async def test_a_malformed_decision_is_still_an_argument_fault(
        self, ledger: LedgerSubject, tamper: str
    ) -> None:
        """:meth:`test_malformed_model_state_is_still_an_argument_fault` on the claim path.

        The decision's own ``id`` is the value the refusal names, so it is the one
        whose ``__repr__`` a message must not call — and a decision is the argument
        a caller is most likely to have built by hand.
        """
        authorisation = allowed()
        await ledger.record(authorisation)
        handed = authorisation.model_copy()
        if tamper == "undescribable":
            handed.__dict__["id"] = Undescribable()
        elif tamper == "hostile-key":
            hostile = HostileKey("id")
            _undeclared(handed, {hostile: "shadow"})
            hostile.arm()
        elif tamper == "cycle":
            # As above, one level up: a container that contains itself, in a field
            # the decision declares. An implementation walking the value must
            # **terminate** — and the walk runs before the first ``await``, so one
            # that re-expands the same container spins on the event loop and the
            # refusal never arrives at all.
            cyclic: list[object] = []
            cyclic.append(cyclic)
            handed.__dict__["step_id"] = cyclic
        elif tamper == "hidden-model":
            # A model where the field declares none, inside a `FrozenDict` — which
            # is a `Mapping` and not a `dict`, so a walk written for `dict` alone
            # goes straight past it and the stored record is not the value passed.
            hidden = tool()
            hidden.__dict__["parameters_schema"] = FrozenDict(
                {"cost": cast("Any", ToolCost(basis=CostBasis.FREE))}
            )
            handed.__dict__["tool"] = hidden
        elif tamper == "unwalkable":

            class _Unwalkable(list[object]):
                """A container whose own iteration raises, which is the caller's code."""

                def __iter__(self) -> Iterator[object]:
                    msg = "this container refuses to be read"
                    raise RuntimeError(msg)

            handed.__dict__["step_id"] = _Unwalkable([1])
        elif tamper == "deep":
            # Acyclic but deep, with a model at the bottom: the walk has to reach
            # it, so a check that gives up at a depth — or that pays for depth
            # quadratically, before the first `await` and on the shared event loop
            # — is not one this suite admits.
            deep: list[object] = []
            cursor = deep
            for _ in range(2000):
                inner: list[object] = []
                cursor.append(inner)
                cursor = inner
            cursor.append(ToolCost(basis=CostBasis.FREE))
            handed.__dict__["step_id"] = deep
        elif tamper == "unspeakable":
            handed.__dict__["step_id"] = Unspeakably([1])
        else:
            _undeclared(handed, {1: "one", "extra": "text"})

        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=handed)

        assert not isinstance(raised.value, UnrecordedAuthorisationError | AuthorisationSpentError)
        assert await _rows(ledger) == []

    @pytest.mark.parametrize(
        "hostility",
        [
            pytest.param("type-probe", id="a-value-that-refuses-to-say-what-it-is"),
            pytest.param("colliding-id", id="a-key-spelling-id-in-place-of-the-real-one"),
        ],
    )
    async def test_a_hostile_value_cannot_escape_through_the_refusal_itself(
        self, ledger: LedgerSubject, hostility: str
    ) -> None:
        """:meth:`test_a_malformed_decision_is_still_an_argument_fault`, one step earlier.

        Those cases are about reading the *fields* of a hostile value. These two are
        about the two things an implementation does around that read — asking what the
        value is, and naming it in the refusal — and either can be made to raise on
        its own.

        ``isinstance`` consults ``__class__`` when ``type()`` leaves the question
        open, so a property that raises turns the type probe into a way out of §2's
        classes before a field has been read at all. And naming the decision by
        ``__dict__["id"]`` hashes ``"id"`` and compares it against whatever collides
        with it: delete the genuine key, leave a ``str`` subclass spelling ``"id"``
        whose ``__eq__`` raises, and the *diagnostic* raises from inside the
        ``except`` block that exists to report the fault. With the genuine key still
        present the lookup may never probe past it, which is why the hostile-key case
        above does not reach this one.
        """
        authorisation = allowed()
        await ledger.record(authorisation)
        if hostility == "type-probe":
            handed = cast("PermissionDecision", HostileClass())
        else:
            handed = authorisation.model_copy()
            spelling = HostileKey("id")
            del handed.__dict__["id"]
            _undeclared(handed, {spelling: "shadow"})
            spelling.arm()

        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=handed)

        assert not isinstance(raised.value, UnrecordedAuthorisationError | AuthorisationSpentError)
        assert await _rows(ledger) == []

    async def test_an_argument_fault_is_decided_before_the_authority(
        self, ledger: LedgerSubject
    ) -> None:
        """ADR-0192 §2's order, and no other."""
        corrupt = allowed("d-never-recorded")
        corrupt.__dict__["decided_at"] = datetime(2026, 7, 20, 12, 0)  # noqa: DTZ001 — the fault

        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=corrupt)

        assert not isinstance(raised.value, UnrecordedAuthorisationError)

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            pytest.param("id", "d-elsewhere", id="the-decision-it-names"),
            pytest.param("ruling", ruling(PermissionOutcome.DENY), id="the-ruling-it-carries"),
        ],
    )
    async def test_the_submitted_decision_is_observed_before_the_first_await(
        self, harness: LedgerHarness, field_name: str, value: object
    ) -> None:
        """ADR-0065, on the other of the two values ADR-0192 §9 names.

        The cost case above pins what is *persisted*; this pins what the admission
        was *decided on*, which is the half a post-call mutation test cannot reach.
        An implementation that validates, suspends and then re-reads the caller's
        object decides the authority against whatever the object says by then — it
        would look up ``d-elsewhere``, or read a ``DENY`` — so it refuses a claim
        this ADR admits, or admits one under an authorisation the store never
        recorded. Both mutations are of a frozen model through ``__dict__``, which
        is the bypass ADR-0021 §4 pins ``record`` against for the same reason.
        """
        ledger = harness.open()
        authorisation = allowed("d-1")
        await ledger.record(authorisation)
        suspension = harness.arm(ledger, "claim_invocation")

        claiming = asyncio.ensure_future(ledger.claim_invocation(decision=authorisation))
        await suspension.reached()
        authorisation.__dict__[field_name] = value
        suspension.release()
        claim = await claiming

        assert claim.decision_id == "d-1", "the row derives from the pre-await snapshot"
        held = await ledger.open_invocations(decision_id="d-1")
        assert [row.id for row in held] == [claim.id]

    # --- the consume ------------------------------------------------------

    async def test_a_second_claim_while_one_is_open_is_refused(self, ledger: LedgerSubject) -> None:
        """The direction this rule fails in everywhere (ADR-0192 §1).

        An open claim is an act that may have run at an outcome nobody observed,
        and admitting a second act under the same authorisation is the one thing
        the consume exists to prevent. It is also why completion durability is a
        third prerequisite for ADR-0029 §5's retry.
        """
        authorisation = allowed()
        await _claim(ledger, authorisation)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

        assert len(await _rows(ledger)) == 1

    @pytest.mark.parametrize(
        "outcome", [ToolOutcome.SUCCEEDED, ToolOutcome.INDETERMINATE], ids=["succeeded", "may-have"]
    )
    async def test_a_settled_act_spends_the_authorisation(
        self, ledger: LedgerSubject, outcome: ToolOutcome
    ) -> None:
        """``INDETERMINATE`` spends it exactly as ``SUCCEEDED`` does (ADR-0192 §3).

        It is ADR-0014 §4's durable ignorance: the effect may have committed, and
        an authorisation left unspent on it would let a second act run under an
        approval that may already have sent.
        """
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, outcome, kind=None)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

    async def test_a_kindless_failure_admits_no_further_claim(self, ledger: LedgerSubject) -> None:
        """A cancelled act is not auto-retried, and it falls out of the conjunction."""
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=None)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

    async def test_an_unretryable_failure_admits_no_further_claim(
        self, ledger: LedgerSubject
    ) -> None:
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=ToolFailureKind.INVALID_REQUEST)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

    async def test_a_none_idempotency_tool_gets_exactly_one_claim_ever(
        self, ledger: LedgerSubject
    ) -> None:
        """ADR-0029 §5's own rule, made a property of the store.

        "An ``Idempotency.NONE`` side-effecting tool is therefore **never**
        auto-retried, whatever the failure kind" — so a retryable failure changes
        nothing here, which is the tool class most at risk.
        """
        authorisation = allowed(
            definition=spendable(idempotency=Idempotency.NONE, idempotency_window=None)
        )
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

    async def test_a_retryable_failure_inside_a_keyed_window_admits_a_further_claim(
        self, harness: LedgerHarness
    ) -> None:
        """The arm ADR-0029 §5's reason turns on: a transient failure still retries."""
        ledger = harness.open(now=StepClock(step=timedelta(seconds=1)))
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        retry = await ledger.claim_invocation(decision=authorisation)

        assert retry.id != claim.id
        assert retry.completes is None

    @pytest.mark.parametrize(
        ("step", "admitted"),
        [(timedelta(seconds=3), True), (timedelta(seconds=5), False)],
        ids=["inside", "at-the-boundary"],
    )
    async def test_the_window_is_strict_at_its_boundary(
        self, harness: LedgerHarness, step: timedelta, *, admitted: bool
    ) -> None:
        """Three readings in: claim at ``0``, completion at ``s``, retry at ``2s``.

        With ``s = 5`` the retry lands exactly on the ten-second window and is
        refused, because ADR-0029 §5 makes the comparison *strictly* less than.
        """
        ledger = harness.open(now=StepClock(step=step))
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        if admitted:
            assert await ledger.claim_invocation(decision=authorisation) is not None
        else:
            with pytest.raises(AuthorisationSpentError):
                await ledger.claim_invocation(decision=authorisation)

    async def test_the_window_is_measured_from_the_first_claim_and_not_the_last(
        self, harness: LedgerHarness
    ) -> None:
        """A chain of three, which the single-retry boundary cases cannot see.

        On a ten-second window: a claim at ``t=0`` completed retryable ``FAILED``,
        a second admitted at ``t=9`` and completed the same way, and a third
        attempted at ``t=18`` — refused, because eighteen seconds have elapsed from
        the **first** claim whatever the gap from the last. An implementation
        measuring from the most recent claim admits it and renews the window
        indefinitely, one retryable failure at a time.
        """
        ledger = harness.open(
            now=ScriptedClock([AT, AT, AT + timedelta(seconds=9), AT + timedelta(seconds=18)])
        )
        authorisation = allowed()
        first = await _claim(ledger, authorisation)
        await _complete(ledger, first, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)
        second = await ledger.claim_invocation(decision=authorisation)
        await _complete(ledger, second, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

    async def test_a_clock_that_steps_backwards_does_not_reorder_the_ledger(
        self, harness: LedgerHarness
    ) -> None:
        """The order is the ledger's own append order, never one over instants.

        The second claim is stamped ten seconds **before** the first. A stored
        instant is what a reader is shown; the order is what the rules are decided
        on, and an implementation sorting the open set by ``recorded_at`` returns
        them the other way round — at which point "the last claim" and "the first
        claim" in ADR-0192 §1's conjunction mean something the store never
        recorded.

        Driven on a ``NATURAL`` authorisation because it is the only kind that
        admits two open claims at all: on a spendable one the window's fail-closed
        reading refuses a claim stamped before its predecessor outright, so the
        two orderings can never be told apart there.
        """
        backwards = ScriptedClock([AT + timedelta(seconds=10), AT])
        ledger = harness.open(now=backwards)
        authorisation = allowed(definition=natural())
        first = await _claim(ledger, authorisation)
        second = await ledger.claim_invocation(decision=authorisation)

        still_open = await ledger.open_invocations(decision_id=authorisation.id)

        assert second.recorded_at < first.recorded_at
        assert [row.id for row in still_open] == [first.id, second.id]

    async def test_a_backwards_stamped_completion_still_spends_the_authorisation(
        self, harness: LedgerHarness
    ) -> None:
        """The consume reads the append order, so a wall clock cannot undo a success."""
        ledger = harness.open(now=ScriptedClock([AT + timedelta(seconds=10), AT]))
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        completion = await _complete(ledger, claim, ToolOutcome.SUCCEEDED, kind=None)

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

        assert completion.recorded_at < claim.recorded_at

    async def test_a_spent_authorisation_is_refused_as_spent_without_consulting_the_clock(
        self, harness: LedgerHarness
    ) -> None:
        """Every arm of §1's conjunction but the window is decided without an instant.

        ADR-0192 §1 says a claim refused because the authorisation is spent raises
        ``AuthorisationSpentError``, and §2 puts that class in the order. An
        implementation reading the clock in front of the conjunction lets a
        collaborator it did not have to consult stand in for a refusal the store's
        own history had already settled — and by ADR-0026 §2 an exception the clock
        *callable* raises is not even the ledger's to translate, so what the caller
        meets is not an ``AuditError`` at all.

        The clock yields one reading and then fails, so the first claim is stamped
        and the second must be refused without a second reading. The count is
        asserted as well as the class: an implementation that reads and swallows the
        failure would raise the right class for the wrong reason.
        """
        clock = ScriptedClock([AT, RuntimeError("the clock is down")])
        ledger = harness.open(now=clock)
        authorisation = allowed()
        await ledger.record(authorisation)
        await ledger.claim_invocation(decision=authorisation)
        assert clock.readings == 1

        with pytest.raises(AuthorisationSpentError):
            await ledger.claim_invocation(decision=authorisation)

        assert clock.readings == 1, "the refusal needed no instant, so none was taken"
        assert len(await _rows(ledger)) == 1

    async def test_a_rejected_reading_refuses_the_claim_and_appends_nothing(
        self, harness: LedgerHarness
    ) -> None:
        """A clock that cannot be read fails closed, which is ADR-0029 §5's own rule."""
        ledger = harness.open(now=ScriptedClock(["not an instant"]))
        authorisation = allowed()
        await ledger.record(authorisation)

        with pytest.raises(AuditError):
            await ledger.claim_invocation(decision=authorisation)

        assert await _rows(ledger) == []

    async def test_the_append_takes_exactly_one_guarded_reading(
        self, harness: LedgerHarness
    ) -> None:
        """Two readings would let a retry be admitted inside a window and stamped outside it."""
        clock = StepClock()
        ledger = harness.open(now=clock)
        authorisation = allowed()
        await ledger.record(authorisation)

        claim = await ledger.claim_invocation(decision=authorisation)
        after_claim = clock.readings
        completion = await _complete(ledger, claim)

        assert after_claim == 1
        assert clock.readings == 2
        assert claim.recorded_at == AT
        assert completion.recorded_at == AT + timedelta(seconds=1)

    async def test_the_instant_the_admission_was_decided_on_is_the_instant_stored(
        self, harness: LedgerHarness
    ) -> None:
        """Otherwise a reader auditing the window finds a claim the store cannot justify."""
        clock = StepClock(step=timedelta(seconds=4))
        ledger = harness.open(now=clock)
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        retry = await ledger.claim_invocation(decision=authorisation)

        # Admitted at t+8 against a window measured from t+0, and stamped there.
        assert retry.recorded_at == AT + timedelta(seconds=8)
        assert retry.recorded_at - claim.recorded_at < WINDOW

    # --- what is never refused on this ground -----------------------------

    @pytest.mark.parametrize(
        "definition",
        [
            read_only(),
            natural(),
        ],
        ids=["not-side-effecting", "natural"],
    )
    async def test_a_non_spendable_authorisation_backs_as_many_acts_as_are_asked_for(
        self, ledger: LedgerSubject, definition: ToolDefinition
    ) -> None:
        """A read gated by ADR-0016 §3 is invoked under one ``ALLOW`` repeatedly.

        Refusing the second would break working behaviour to protect nothing, and
        a store that consumed every ``ALLOW`` would silently become a lock on
        reads.
        """
        authorisation = allowed(definition=definition)
        first = await _claim(ledger, authorisation)

        second = await ledger.claim_invocation(decision=authorisation)

        assert {first.id, second.id} == {row.id for row in await _rows(ledger)}
        assert len(await ledger.open_invocations(decision_id=authorisation.id)) == 2

    async def test_two_open_claims_under_one_decision_come_back_in_append_order(
        self, ledger: LedgerSubject
    ) -> None:
        """The state the recovery scan completes **both** of (ADR-0192 §3).

        Reachable only on a non-spendable authorisation: on a spendable one §1
        refuses the second claim while one is open, so no case may construct two
        open claims there.
        """
        authorisation = allowed(definition=natural())
        first = await _claim(ledger, authorisation)
        second = await ledger.claim_invocation(decision=authorisation)

        still_open = await ledger.open_invocations(decision_id=authorisation.id)

        assert [row.id for row in still_open] == [first.id, second.id]

    # --- the recovery read ------------------------------------------------

    async def test_a_completed_claim_leaves_the_open_set(self, ledger: LedgerSubject) -> None:
        claim = await _claim(ledger, allowed("d-1"))
        assert [row.id for row in await ledger.open_invocations(decision_id="d-1")] == [claim.id]

        await _complete(ledger, claim)

        assert await ledger.open_invocations(decision_id="d-1") == []

    async def test_an_unknown_decision_has_no_open_claims(self, ledger: LedgerSubject) -> None:
        """Empty states that no call was in flight, which is what the scan reads."""
        assert await ledger.open_invocations(decision_id="d-nobody") == []

    async def test_the_open_set_is_scoped_to_the_decision_it_names(
        self, ledger: LedgerSubject
    ) -> None:
        mine = await _claim(ledger, allowed("d-mine"))
        await _claim(ledger, allowed("d-theirs"))

        assert [row.id for row in await ledger.open_invocations(decision_id="d-mine")] == [mine.id]

    async def test_open_invocations_reserves_the_ids_it_returns(
        self, harness: LedgerHarness
    ) -> None:
        """The reservation ADR-0192 §2 requires, asserted at the factory it is made to.

        A completion names its claim by ``id`` alone, so an id reissued after the
        row it first named was erased would let a completion held by one call land
        on a **different** call's claim.
        """
        drawn = ScriptedIdentifiers()
        ledger = harness.open(identifiers=drawn)
        claim = await _claim(ledger, allowed("d-1"))

        await ledger.open_invocations(decision_id="d-1")

        assert drawn.reserved == [claim.id]

    async def test_a_reserved_id_is_not_reissued_after_the_row_it_named_was_erased(
        self, harness: LedgerHarness
    ) -> None:
        """The restart, read, erase, re-claim sequence the reservation exists for.

        The factory is driven so that it **would** have minted the erased claim's
        id absent the reservation — a factory left to its own sequence reproduces
        the collision only by coincidence, and a test resting on one asserts
        nothing. With the row gone the ledger's redraw cannot see the reissue: the
        store holds nothing to collide with.
        """
        drawn = ScriptedIdentifiers(forced=["claim-x"])
        ledger = harness.open(identifiers=drawn)
        stale = await _claim(ledger, allowed("d-1"))
        assert stale.id == "claim-x"
        await ledger.open_invocations(decision_id="d-1")
        await ledger.clear()
        drawn.forced = ["claim-x", "claim-y"]

        fresh = await _claim(ledger, allowed("d-1"))

        assert fresh.id != "claim-x"
        with pytest.raises(InvalidCompletionError):
            await _complete(ledger, stale)

    async def test_the_reservation_is_taken_inside_the_read_that_returns_the_ids(
        self, harness: LedgerHarness
    ) -> None:
        """Raced, because the sequential case cannot see a read-then-reserve store.

        An erasure and a fresh claim land while the read is held open; an
        implementation that released the serialisation boundary and reserved
        afterwards reserves an id naming the **new** claim, which is the
        misdirection unchanged.
        """
        drawn = ScriptedIdentifiers(forced=["claim-x"])
        ledger = harness.open(identifiers=drawn)
        await _claim(ledger, allowed("d-1"))
        suspension = harness.arm(ledger, "open_invocations")
        reading = asyncio.ensure_future(ledger.open_invocations(decision_id="d-1"))
        await suspension.reached()
        erasing = asyncio.ensure_future(ledger.clear())
        await asyncio.sleep(0)
        drawn.forced = ["claim-x", "claim-y"]
        suspension.release()
        returned = await reading
        await erasing
        fresh = await _claim(ledger, allowed("d-1"))

        assert {row.id for row in returned} == {"claim-x"}
        assert fresh.id not in {row.id for row in returned}, (
            "no id the read returned may be one a claim appended after it holds"
        )

    # --- erasure erases the consume ---------------------------------------

    async def test_a_decision_re_recorded_after_an_erasure_admits_a_claim(
        self, ledger: LedgerSubject
    ) -> None:
        """§6 states this as a scope rather than leaving it to be inferred.

        The consume **is** a row, so a rule surviving the erasure of the rows it is
        made of would be a second, undeletable record of an act the user asked to
        have erased. No generation, epoch or marker is asserted, because §6 mints
        none.
        """
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.SUCCEEDED, kind=None)
        await ledger.clear()
        await ledger.record(authorisation)

        again = await ledger.claim_invocation(decision=authorisation)

        assert again.decision_id == authorisation.id

    async def test_a_claim_racing_clear_lands_before_it_or_is_refused_after_it(
        self, ledger: LedgerSubject, harness: LedgerHarness
    ) -> None:
        authorisation = allowed()
        await ledger.record(authorisation)
        suspension = harness.arm(ledger, "claim_invocation")
        claiming = asyncio.ensure_future(ledger.claim_invocation(decision=authorisation))
        await suspension.reached()
        erasing = asyncio.ensure_future(ledger.clear())
        await asyncio.sleep(0)
        suspension.release()
        results = await asyncio.gather(claiming, erasing, return_exceptions=True)

        assert await _rows(ledger) == []
        failure = results[0]
        assert not isinstance(failure, BaseException) or isinstance(
            failure, UnrecordedAuthorisationError
        )

    # --- races ------------------------------------------------------------

    async def test_two_racing_claims_on_a_spendable_authorisation_settle_it_once(
        self, ledger: LedgerSubject
    ) -> None:
        """One atomic append, as ADR-0021 §4 already answers for two resolutions.

        Anywhere else the check and the write are separated by an ``await``, and
        "the system composes on one event loop" is precisely the setting in which
        that is an interleaving point.
        """
        authorisation = allowed()
        await ledger.record(authorisation)

        results = await asyncio.gather(
            ledger.claim_invocation(decision=authorisation),
            ledger.claim_invocation(decision=authorisation),
            return_exceptions=True,
        )

        appended = [row for row in results if not isinstance(row, BaseException)]
        refused = [row for row in results if isinstance(row, AuthorisationSpentError)]
        assert len(appended) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"
        assert len(await _rows(ledger)) == 1

    @pytest.mark.parametrize(
        "definition",
        [
            read_only(),
            natural(),
        ],
        ids=["not-side-effecting", "natural"],
    )
    async def test_two_racing_claims_on_a_non_spendable_one_both_append(
        self, ledger: LedgerSubject, definition: ToolDefinition
    ) -> None:
        """The half a one-winner test cannot see, and how a store becomes a lock on reads."""
        authorisation = allowed(definition=definition)
        await ledger.record(authorisation)

        results = await asyncio.gather(
            ledger.claim_invocation(decision=authorisation),
            ledger.claim_invocation(decision=authorisation),
            return_exceptions=True,
        )

        assert all(not isinstance(row, BaseException) for row in results), results
        assert len(await _rows(ledger)) == 2

    async def test_the_retry_admission_is_settled_once_under_a_race(
        self, harness: LedgerHarness
    ) -> None:
        """A second branch rather than a repeat of the first (ADR-0192 §9).

        An implementation may well have written the *retry* admission as a check
        followed by an append even where it made the first claim atomic — and a
        store passing the first-claim race and failing this one admits the
        duplicate effect one state later.
        """
        ledger = harness.open(now=StepClock())
        authorisation = allowed()
        claim = await _claim(ledger, authorisation)
        await _complete(ledger, claim, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        results = await asyncio.gather(
            ledger.claim_invocation(decision=authorisation),
            ledger.claim_invocation(decision=authorisation),
            return_exceptions=True,
        )

        appended = [row for row in results if not isinstance(row, BaseException)]
        refused = [row for row in results if isinstance(row, AuthorisationSpentError)]
        assert len(appended) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"

    @pytest.mark.parametrize("listing", _LISTINGS, ids=lambda call: call.__name__)
    async def test_the_join_against_a_concurrent_clear_is_all_or_nothing(
        self,
        ledger: LedgerSubject,
        harness: LedgerHarness,
        listing: Callable[[LedgerSubject], Awaitable[list[RecordedInvocation]]],
    ) -> None:
        """The race the store-side join exists for (ADR-0192 §2).

        A two-read implementation — rows, then their decisions — is the natural
        one, and it passes every claim and completion race above. Only this
        distinguishes it: either answer is acceptable, and a row without its
        decision is not.

        **Both listings**, because §9 says both and because they are two entry
        points a store may serialise differently — the bounded one is the method a
        surface consumer actually calls, and a limit clause is exactly the kind of
        thing that gets its own code path.
        """
        claim = await _claim(ledger, allowed("d-1"))
        await _complete(ledger, claim)
        suspension = harness.arm(ledger, listing.__name__)
        reading = asyncio.ensure_future(listing(ledger))
        await suspension.reached()
        erasing = asyncio.ensure_future(ledger.clear())
        await asyncio.sleep(0)
        suspension.release()
        rows = await reading
        await erasing

        assert len(rows) in {0, 2}
        assert all(row.tool == "smtp" for row in rows)

    @pytest.mark.optional_obligation
    async def test_two_instances_over_one_store_admit_one_spendable_claim(
        self, harness: LedgerHarness
    ) -> None:
        """Atomicity that is a per-instance lock is no atomicity at all.

        ADR-0192 §2 makes overlapping instances reachable — nothing makes the
        ledger unreplaceable and no quiescence rule is minted — so an
        implementation whose exclusion is an ``asyncio.Lock`` on the object
        satisfies every single-object race above while two instances each observe
        no claim and each append.

        **Optional, and ADR-0192 §9 says so in terms**: "Where a store under test
        cannot be opened twice, the suite **skips with its reason stated**, as the
        conformance suites in this corpus already do, and never by omitting the
        case." A subject whose store is a dict cannot reach it at all.
        """
        first = harness.open()
        store = harness.store_of(first)
        if store is None:
            pytest.skip("this store cannot be opened twice, so two instances are unreachable")
        second = harness.open(store=store)
        authorisation = allowed()
        await first.record(authorisation)

        results = await asyncio.gather(
            first.claim_invocation(decision=authorisation),
            second.claim_invocation(decision=authorisation),
            return_exceptions=True,
        )

        appended = [row for row in results if not isinstance(row, BaseException)]
        assert len(appended) == 1, f"expected exactly one winner, got {results}"
        assert len(await _rows(first)) == 1

    @pytest.mark.optional_obligation
    async def test_two_instances_over_one_store_settle_the_retry_admission_once(
        self, harness: LedgerHarness
    ) -> None:
        """The second branch of the consume, through the door a per-instance lock leaves.

        A store may have made the *first* claim atomic and written the retry
        admission as a check followed by an append; layering the two-instance arm on
        it is what ADR-0192 §9 asks for, because an implementation excluding on an
        ``asyncio.Lock`` passes both single-object races and admits two acts here.

        One clock for both instances, because that is what the composition root
        injects: two clocks each starting at ``AT`` would put the second instance's
        reading *at* the first claim, and a zero elapsed time is a lapsed window
        (ADR-0029 §5's fail-closed rule) rather than the race under test.
        """
        clock = StepClock()
        first = harness.open(now=clock)
        second = _over_the_same_store(harness, first, now=clock)
        authorisation = allowed()
        claim = await _claim(first, authorisation)
        await _complete(first, claim, ToolOutcome.FAILED, kind=ToolFailureKind.UNAVAILABLE)

        results = await asyncio.gather(
            first.claim_invocation(decision=authorisation),
            second.claim_invocation(decision=authorisation),
            return_exceptions=True,
        )

        appended = [row for row in results if not isinstance(row, BaseException)]
        refused = [row for row in results if isinstance(row, AuthorisationSpentError)]
        assert len(appended) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"
        assert len([row for row in await _rows(first) if row.completes is None]) == 2

    @pytest.mark.optional_obligation
    async def test_two_instances_over_one_store_complete_one_claim_once(
        self, harness: LedgerHarness
    ) -> None:
        """The completion's write-once guarantee through the same door (ADR-0192 §9).

        A claim completed twice is two outcomes for one act, and the second could
        carry a different one — which is the record saying two contradictory things
        about what happened, on the row a recovery scan reads.
        """
        first = harness.open()
        second = _over_the_same_store(harness, first)
        claim = await _claim(first, allowed())

        results = await asyncio.gather(
            _complete(first, claim), _complete(second, claim), return_exceptions=True
        )

        appended = [row for row in results if not isinstance(row, BaseException)]
        refused = [row for row in results if isinstance(row, InvalidCompletionError)]
        assert len(appended) == 1, f"expected exactly one winner, got {results}"
        assert len(refused) == 1, f"the loser must be refused, got {results}"
        assert len([row for row in await _rows(first) if row.completes is not None]) == 1

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("listing", _LISTINGS, ids=lambda call: call.__name__)
    async def test_two_instances_over_one_store_join_against_a_clear_all_or_nothing(
        self,
        harness: LedgerHarness,
        listing: Callable[[LedgerSubject], Awaitable[list[RecordedInvocation]]],
    ) -> None:
        """The join race where the erasure is a *different object's* (ADR-0192 §9).

        The single-object version can be passed by a store whose read and whose
        ``clear`` merely share one ``asyncio.Lock``. Here they share nothing but the
        file, so what has to hold the answer together is the store's own
        serialisation — which is the reason §2 puts the join inside one operation
        rather than the reason the suite could have settled for.
        """
        first = harness.open()
        second = _over_the_same_store(harness, first)
        claim = await _claim(first, allowed("d-1"))
        await _complete(first, claim)
        suspension = harness.arm(first, listing.__name__)

        reading = asyncio.ensure_future(listing(first))
        await suspension.reached()
        erasing = asyncio.ensure_future(second.clear())
        await asyncio.sleep(0)
        suspension.release()
        rows = await reading
        await erasing

        assert len(rows) in {0, 2}
        assert all(row.tool == "smtp" for row in rows)

    @pytest.mark.optional_obligation
    async def test_a_replacement_factory_does_not_reissue_across_an_erasure(
        self, harness: LedgerHarness
    ) -> None:
        """The reset ADR-0192 §2 scopes to the **process** and not to the instance.

        Driven **across a ``clear()``**, and the interleaving is the point rather
        than a variation: with rows still in the store the ledger's redraw hides a
        reset allocator — the reissued id collides, the ledger draws again, and the
        two ids differ for a reason that has nothing to do with the factory. With
        nothing left to collide with, the factory is the only thing under test.

        The second subject is built **the way the composition root builds the
        first** — its own factory, default-constructed — because that is the
        replacement §2 says nothing forbids. A factory whose prefix is fixed and
        whose counter is per-instance passes every same-instance draw case and
        reissues here.

        The stale-completion consequence is asserted beside it, which is why the
        reissue matters at all: a completion held by a call that outlived the first
        instance must not land on a claim the second one appended and be recorded as
        that call's outcome.
        """
        first = harness.open()
        second = _over_the_same_store(harness, first)
        kept = await _claim(first, allowed("d-1"))
        await first.clear()

        fresh = await _claim(second, allowed("d-1"))

        assert fresh.id != kept.id, "a replacement factory is a new instance, not a new process"
        with pytest.raises(InvalidCompletionError):
            await _complete(second, kept)
        held = await _rows(second)
        assert [row.id for row in held] == [fresh.id]

    @pytest.mark.optional_obligation
    async def test_a_new_process_draws_away_from_a_claim_a_previous_one_left(
        self, harness: LedgerHarness
    ) -> None:
        """The redraw's reason for existing, and the cost of refusing instead.

        The store is opened holding an open claim under ``x`` with no live process
        that minted it — the state a recovery scan reads at startup — and the new
        factory's first draw is ``x``, which a conforming, process-scoped factory
        in a *new* process may legally return. An implementation refusing on the
        first collision fails here, and fails the same way on every subsequent
        restart.
        """
        first = harness.open(identifiers=ScriptedIdentifiers(forced=["claim-x"]))
        store = harness.store_of(first)
        if store is None:
            pytest.skip("this store does not outlive its object, so a restart is unreachable")
        authorisation = allowed(definition=natural())
        stale = await _claim(first, authorisation)
        assert stale.id == "claim-x"

        restarted = harness.open(
            store=store, identifiers=ScriptedIdentifiers(forced=["claim-x", "claim-z"])
        )
        fresh = await restarted.claim_invocation(decision=authorisation)

        assert fresh.id == "claim-z"
        still_open = await restarted.open_invocations(decision_id=authorisation.id)
        assert {row.id for row in still_open} == {"claim-x", "claim-z"}
        closed = await restarted.complete_invocation(
            claim_id="claim-x", outcome=ToolOutcome.INDETERMINATE, incurred_cost=UNKNOWN_COST
        )
        assert closed.completes == "claim-x"

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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

import pytest
from permission_builders import AT, action, decision, ruling, tool

from ai_assistant.core.clock import ClockReadingError
from ai_assistant.core.errors import (
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
    Idempotency,
    PermissionOutcome,
    RiskLevel,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

    from ai_assistant.core.types import PermissionDecision, ToolDefinition
    from ai_assistant.testing.cancellation import ResourceLog, SuspendedCall


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

    async def test_a_value_that_is_not_a_decision_is_an_argument_fault(
        self, ledger: LedgerSubject
    ) -> None:
        """The decision is *validated* before any field of it is read.

        ``decision.model_dump()`` is a field read, so an implementation calling it
        first lets a value that is not a decision escape as ``AttributeError`` —
        which is not an ``AssistantError``, and so is outside the classes ADR-0192
        §2's order is exhaustive over. ``FakeToolInvoker._revalidated`` states the
        same ordering for the same reason (ADR-0152 §1).
        """
        with pytest.raises(AuditError) as raised:
            await ledger.claim_invocation(decision=None)  # type: ignore[arg-type]  # the fault

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

    async def test_the_join_against_a_concurrent_clear_is_all_or_nothing(
        self, ledger: LedgerSubject, harness: LedgerHarness
    ) -> None:
        """The race the store-side join exists for (ADR-0192 §2).

        A two-read implementation — rows, then their decisions — is the natural
        one, and it passes every claim and completion race above. Only this
        distinguishes it: either answer is acceptable, and a row without its
        decision is not.
        """
        claim = await _claim(ledger, allowed("d-1"))
        await _complete(ledger, claim)
        suspension = harness.arm(ledger, "export_invocations")
        reading = asyncio.ensure_future(ledger.export_invocations())
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

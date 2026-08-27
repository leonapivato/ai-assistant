"""Shared conformance suite for the ToolInvoker Protocol (ADR-0029).

Every ``ToolInvoker`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ToolInvokerContract` and overrides the ``invoker`` fixture.

`InMemoryToolRegistry` and `FakeToolInvoker` implement the seam independently —
the fake cannot import the subsystem it stands in for — so this suite is what
stops the two drifting.

**Scope: what an implementation could get wrong.** ADR-0029's type-level rules —
an unauthorised ``ToolCall`` being unconstructable, ``ToolResult``'s cross-field
invariants, ``retryable``'s exhaustiveness, the key derivation itself — hold by
construction in ``core`` and are the same for every implementation, so they are
pinned in ``tests/core/test_tool_types.py`` where the types live rather than
re-asserted per subject. What lives here is everything ``invoke`` is free to get
wrong: the binding checks and their **order**, the deadline and its
classification, the provenance of a cancellation, and what reaches the callable.

The suite also requires its subject to present **both faces** of the registry,
which is how ADR-0029 §1's biconditional becomes checkable: an implementation
keeping a second table of callables fails ``test_the_invocable_set_is_exactly
_all_tools`` rather than passing review.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, NoReturn, Protocol, cast

import pytest
import structlog.testing
from pydantic import BaseModel, ConfigDict, ValidationError

from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    ClassifiedToolError,
    SpendCeilingError,
    SpendUndeterminedError,
    ToolBindingError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.protocols import ToolInvoker, ToolRegistry
from ai_assistant.core.types import (
    UNREPRESENTABLE_FAULT_CLASS,
    ActionRequest,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ReportedOutput,
    Reversibility,
    RiskLevel,
    SpendAdmissionHandle,
    SpendPeriod,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
)
from ai_assistant.testing import (
    APPEND_FAILED,
    CLAIM,
    COMPLETION,
    REPORTED_FAILURE,
    RESERVED_KIND,
    FakeAuditTrail,
)

if TYPE_CHECKING:
    from collections.abc import (
        Awaitable,
        Callable,
        Coroutine,
        Mapping,
        MutableMapping,
        Sequence,
    )
    from types import GetSetDescriptorType

    from ai_assistant.core.protocols import InvocationLedger, SpendGate
    from ai_assistant.core.types import FrozenJson, ToolInvocation, ToolResult
    from ai_assistant.testing import FakeToolImplementation

#: A fixed instant, so nothing here depends on how fast the suite runs.
AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: Long enough that a prompt tool finishes inside it on any machine the gate
#: runs on, short enough that the tests that *want* an expiry are quick.
PATIENT = timedelta(seconds=30)
BRIEF = timedelta(milliseconds=20)


class InvocableToolRegistry(ToolRegistry, ToolInvoker, Protocol):
    """Both faces, plus the one method this suite needs to arrange them.

    Requiring both is the point (ADR-0029 §1): the canonical implementation is
    one object over one mapping from id to ``(definition, callable)``, so the
    two sets this suite compares are read from the same place by construction.
    """

    def register(self, tool: ToolDefinition, implementation: FakeToolImplementation, /) -> None:
        """Bind a declaration and the callable that satisfies it."""
        ...

    @property
    def ledger(self) -> InvocationLedger:
        """The ledger this seam claims through, which the suite arranges."""
        ...


# --- builders -----------------------------------------------------------


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """Build a valid, side-effecting, non-``NATURAL`` definition.

    That base is deliberate: it is the declaration for which ADR-0029 §4's
    interrupted-call rule answers ``INDETERMINATE``, so a test wanting the
    ``FAILED`` half has to say so, rather than getting it by forgetting.
    """
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def read_only(tool_id: str = "inbox") -> ToolDefinition:
    """A tool with no side effect: ADR-0029 §4's ``FAILED`` branch."""
    return tool(
        tool_id,
        capability="read_email",
        side_effecting=False,
        reversibility=Reversibility.REVERSIBLE,
    )


def natural(tool_id: str = "upsert") -> ToolDefinition:
    """A side-effecting tool that is idempotent by nature: also ``FAILED``."""
    return tool(tool_id, idempotency=Idempotency.NATURAL)


def keyed(tool_id: str = "smtp", window: timedelta = timedelta(hours=24)) -> ToolDefinition:
    """A tool whose repeats are deduplicated by key inside ``window``."""
    return tool(tool_id, idempotency=Idempotency.KEYED, idempotency_window=window)


def gated(tool_id: str = "inbox", window: timedelta = timedelta(hours=24)) -> ToolDefinition:
    """A ``KEYED`` tool that is **not** side-effecting, so it is not spendable.

    The class the key cases below need since ADR-0192 §1 made a claim the consume:
    the key is derived from ``idempotency is KEYED`` alone
    (``ToolCall.idempotency_key``), while *spendability* is "side-effecting **and**
    not ``NATURAL``". So this tool derives a key exactly as ``keyed()`` does and
    §1 refuses no repetition under it — which is the read ADR-0016 §3 gates, and
    the only class under which "the same call twice" is still a thing ``invoke``
    will do.

    A **spendable** ``KEYED`` tool's repeat is governed by §1's conjunction
    instead, and is pinned where that conjunction is — not here.
    """
    return tool(
        tool_id,
        capability="read_email",
        side_effecting=False,
        reversibility=Reversibility.REVERSIBLE,
        idempotency=Idempotency.KEYED,
        idempotency_window=window,
    )


def call_for(
    definition: ToolDefinition,
    *,
    parameters: Mapping[str, FrozenJson] | None = None,
    step_id: str | None = "step-1",
    decision_id: str = "d-1",
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
) -> ToolCall:
    """Build an authorised call for ``definition``, through the sanctioned path.

    The decision goes through ``from_request`` rather than the constructor,
    because that is what the contract asks callers to use and it is what makes a
    call whose subject disagrees with its request unarrangeable here.
    """
    request = ActionRequest(
        tool=definition, parameters=parameters or {"to": "someone@example.com"}, step_id=step_id
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=outcome, reason=f"because it is {outcome}"),
        id=decision_id,
        decided_at=AT,
    )
    return ToolCall(request=request, decision=decision)


class Spy:
    """A tool implementation that records what it was handed.

    The recording is what makes "the tool was never reached" assertable, which
    every binding-refusal test in this suite needs: asserting only that
    ``invoke`` raised would pass against an implementation that ran the callable
    and then checked.
    """

    def __init__(self, output: FrozenJson = None) -> None:
        """Record nothing yet; return ``output`` when called."""
        self.calls: list[tuple[dict[str, FrozenJson], str | None]] = []
        self._output = output

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Record the arguments and return the configured output."""
        self.calls.append((dict(parameters), idempotency_key))
        return self._output


class Raiser:
    """A tool implementation that raises whatever it was built with."""

    def __init__(self, exc: BaseException) -> None:
        """Raise ``exc`` on every call."""
        self._exc = exc
        self.calls = 0

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Raise, without ever awaiting anything."""
        self.calls += 1
        raise self._exc


class Returner:
    """A tool implementation returning a value ``FrozenJsonValue`` refuses."""

    def __init__(self, value: object) -> None:
        """Return ``value``, whatever it is."""
        self._value = value

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Return the unserialisable value, as a broken integration would."""
        return self._value  # type: ignore[return-value]  # the point of this double


class Slow:
    """A tool that waits long past any deadline the suite gives it."""

    def __init__(self) -> None:
        """Create the event that reports the callable has been entered."""
        self.entered = asyncio.Event()

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Sleep until cancelled."""
        self.entered.set()
        await asyncio.sleep(3600)
        return None


class Stubborn:
    """A tool that suppresses its cancellation and waits on an event.

    ADR-0029 §4's stated hole, made deterministic: ``asyncio.timeout`` does not
    return until the inner frame finishes unwinding, so a ``finally`` that
    awaits keeps ``invoke`` waiting past the deadline it was given. Pinning the
    *limit* is what stops an implementation quietly acquiring a watchdog, or a
    later reader assuming the deadline is a hard bound.
    """

    def __init__(self) -> None:
        """Create the event the test releases it with."""
        self.release = asyncio.Event()
        self.entered = asyncio.Event()

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Sleep, then refuse to unwind until the test says so."""
        try:
            self.entered.set()
            await asyncio.sleep(3600)
        finally:
            await self.release.wait()
        return None


class Swallower:
    """A tool that *catches* its cancellation and returns a value anyway.

    Nothing forces a callable to let a cancellation through, and this is the
    shape that makes an implementation trusting the returned value wrong in the
    worst available direction: a cancelled turn reported ``SUCCEEDED``, or a
    side-effecting call that outran its deadline reported as though it had met
    it. ``Stubborn`` does not cover it — that one delays its unwinding and still
    re-raises.
    """

    def __init__(self) -> None:
        """Create the event that reports the callable has been entered."""
        self.entered = asyncio.Event()
        self.swallowed = False

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Absorb whatever cancellation arrives and return normally."""
        self.entered.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.swallowed = True
        return {"done": True}


class KeyedTool:
    """A ``KEYED`` tool that deduplicates a repeat inside its declared window.

    The tool-side half of ADR-0029 §5's two-sided obligation: "a ``KEYED`` tool
    receiving the same key twice within its declared window performs the effect
    once and returns the first result". It keeps its own clock reading so the
    test can move time rather than wait.
    """

    def __init__(self, window: timedelta) -> None:
        """Deduplicate for ``window`` from each key's first use."""
        self._window = window
        self._seen: dict[str, tuple[datetime, int]] = {}
        self.now = AT
        self.effects = 0

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Perform the effect once per key per window, returning the first result."""
        assert idempotency_key is not None, "a KEYED tool must be handed a key"
        first = self._seen.get(idempotency_key)
        if first is not None and self.now - first[0] < self._window:
            return first[1]
        self.effects += 1
        self._seen[idempotency_key] = (self.now, self.effects)
        return self.effects


# --- the consume: ADR-0192 §1 and §3 ------------------------------------
#
# Everything below drives `invoke` through a ledger, which is the only thing that
# can observe the claim and the completion. The ledger under it is always the
# canonical `FakeAuditTrail` — the store side is the paired lane's suite, not this
# one — wrapped where a test needs an append held, failed, or failed *after* it
# committed.


class MovingClock:
    """A clock the test advances, for the window ADR-0192 §1 measures.

    The ledger stamps ``recorded_at`` from this and decides its admission rules on
    the same reading, so moving it is how a test reaches the far side of an
    ``idempotency_window`` without racing one.
    """

    def __init__(self, at: datetime = AT) -> None:
        """Read ``at`` until moved."""
        self.now = at

    def __call__(self) -> datetime:
        """Return the current reading."""
        return self.now


class Append:
    """How one ledger member behaves on the next call (a test's own arrangement)."""

    def __init__(self) -> None:
        """Behave exactly like the ledger under it, until arranged otherwise."""
        #: Set the moment the append is entered.
        self.entered = asyncio.Event()
        #: Awaited before the append proceeds, where a test holds one.
        self.hold: asyncio.Event | None = None
        #: Raised instead of, or after, the real append.
        self.error: BaseException | None = None
        #: Whether the real append runs before ``error`` is raised. ``True`` is
        #: ADR-0192 §1's and §3's commit-state case: the row stands and the append
        #: raised, and no caller may tell that apart from a write that never landed.
        self.commits = False
        #: How many times this member has been entered.
        self.calls = 0


class DrivenLedger:
    """An ``InvocationLedger`` a test can hold, fail, or fail after it committed.

    **A wrapper rather than a second store.** Every rule about *what a ledger
    does* is the paired lane's, pinned in its own conformance suite; what this
    suite needs is a ledger whose **timing** and **failure** the test owns, so the
    seam's own clauses — the shield, the absorption, the commit-state split, the
    diagnostic — become observable.

    ADR-0192 §3 decides absorption "by class, not by origin", so raising the
    exception from here is a faithful driver for a ledger that raised it, whatever
    produced it — a refusal, a guard's rejection, a store that would not write, or
    an exception an injected clock callable raised and the ledger propagated
    unwrapped (ADR-0026 §2).
    """

    def __init__(self, inner: FakeAuditTrail) -> None:
        """Delegate to ``inner``, under the two arrangements below."""
        self.inner = inner
        self.claim = Append()
        self.completion = Append()

    async def _through(
        self, append: Append, real: Callable[[], Awaitable[ToolInvocation]]
    ) -> ToolInvocation:
        """Run ``real`` under ``append``'s arrangement."""
        append.calls += 1
        append.entered.set()
        if append.hold is not None:
            await append.hold.wait()
        if append.error is not None and not append.commits:
            raise append.error
        row = await real()
        if append.error is not None:
            raise append.error
        return row

    async def claim_invocation(self, *, decision: PermissionDecision) -> ToolInvocation:
        """Append a claim under ``decision``, or behave as arranged."""
        return await self._through(
            self.claim, lambda: self.inner.claim_invocation(decision=decision)
        )

    async def complete_invocation(
        self,
        *,
        claim_id: str,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Append the completion of ``claim_id``, or behave as arranged."""
        return await self._through(
            self.completion,
            lambda: self.inner.complete_invocation(
                claim_id=claim_id,
                outcome=outcome,
                incurred_cost=incurred_cost,
                failure_kind=failure_kind,
            ),
        )


async def rows(trail: FakeAuditTrail) -> list[ToolInvocation]:
    """Every invocation row the trail holds, in the order the read returns them.

    That order is ``recent``'s and not the ledger's append order (ADR-0192 §2), so
    nothing below reads a row *by position*: the two kinds are told apart by
    :attr:`ToolInvocation.completes`, which is what the shape's own discriminator
    is for.
    """
    return [each.invocation for each in await trail.export_invocations()]


async def claims(trail: FakeAuditTrail) -> list[ToolInvocation]:
    """Every claim row the trail holds, completed or not."""
    return [each for each in await rows(trail) if each.completes is None]


async def completions(trail: FakeAuditTrail) -> list[ToolInvocation]:
    """Every completion row the trail holds."""
    return [each for each in await rows(trail) if each.completes is not None]


def appended(captured: Sequence[Mapping[str, Any]]) -> list[dict[str, object]]:
    """The append-failure diagnostics among ``captured``, fields and all.

    ``capture_logs`` adds its own ``event`` and ``log_level`` keys; both are
    dropped so a test can assert the ADR-0192 §3 matrix **field by field**,
    including that an absent field is absent rather than merely unchecked.
    """
    return [
        {key: value for key, value in each.items() if key not in {"event", "log_level"}}
        for each in captured
        if each.get("event") == APPEND_FAILED
    ]


#: ``BaseException``'s own ``__cause__`` descriptor — the slot the seam writes
#: through, and the one these tests read and arrange, so that neither half of a
#: check is answered by a ``__cause__`` the subclass under test declares.
CAUSE_SLOT: GetSetDescriptorType = BaseException.__dict__["__cause__"]


def cause_of(exception: BaseException) -> BaseException | None:
    """Read ``exception``'s cause out of the slot, past any ``__cause__`` it declares.

    The seam attaches the cause through ``BaseException``'s own descriptor
    precisely so that a subclass cannot intercept the write. Reading it back with
    plain attribute access would hand the question to the very ``__cause__``
    property the write went around, so the check reads the same slot the write
    landed in.
    """
    return cast("BaseException | None", CAUSE_SLOT.__get__(exception))


class NameRaises(type):
    """A metaclass that refuses to be named, raising an ``Exception`` when asked.

    ``fault_class_of`` guards the ``__name__`` read precisely because "total" has
    to mean it: a metaclass may override the access and raise, and either would
    otherwise take down the diagnostic together with the fault it was recording.
    """

    def __getattribute__(cls, name: str) -> object:
        """Raise on ``__name__`` and behave normally on everything else."""
        if name == "__name__":
            msg = "the metaclass refuses to be named"
            raise RuntimeError(msg)
        return super().__getattribute__(name)


async def _settled(cycles: int = 4) -> None:
    """Let the loop deliver whatever is pending, without sleeping on a clock.

    A cancellation is delivered at the invoking task's next suspension point, so
    a test that asserts "still waiting" has to give the loop a turn first —
    deterministically, and never by racing a duration.
    """
    for _ in range(cycles):
        await asyncio.sleep(0)


async def invoked(
    invoker: InvocableToolRegistry,
    trail: FakeAuditTrail,
    call: ToolCall,
    *,
    timeout: timedelta = PATIENT,  # noqa: ASYNC109 — relayed to the seam, which owns it
) -> ToolResult:
    """Record ``call``'s authorisation if the trail has not got it, then invoke.

    What ``StepRunner`` does in front of every execution, and what ADR-0192 §1 now
    makes a precondition of reaching the callable at all: the ledger requires the
    decision it is passed to equal the one the store holds under that id, so an
    unrecorded authorisation is refused before the tool. The cases *about* that
    refusal call ``invoke`` directly; every case about something else goes through
    here.

    **Recorded once per decision, not once per call.** A trail refuses a second
    ``record`` under one id, and a decision legitimately backs more than one act
    where ADR-0192 §1 admits one — so this mirrors the runner, which records the
    ruling once and may then execute under it again.
    """
    if await trail.get(call.decision.id) is None:
        await trail.record(call.decision)
    return await invoker.invoke(call, timeout=timeout)


class SynchronousFactory:
    """A registration that is **not** a native ``async def``.

    Nothing makes one: the callable shape is satisfied by any object returning an
    awaitable, so a plain function's body runs at the **call**, before the
    coroutine it hands back is ever awaited. That is what makes ADR-0192 §1's "the
    claim is appended immediately before the callable is entered" a statement about
    *calling* and not only about awaiting — an implementation that obtains the
    coroutine in order to hold it across the claim has already run this body.
    """

    def __init__(self) -> None:
        """Record nothing yet."""
        self.entered = 0

    def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> Coroutine[Any, Any, FrozenJson]:
        """Run the synchronous half **now**, and return the awaitable half."""
        self.entered += 1
        recorded = dict(parameters)

        async def _acting() -> FrozenJson:
            return recorded.get("to")

        return _acting()


#: Sentinel argument values, appearing nowhere else in this module, so that a
#: refusal's user-facing channels can be checked for them (ADR-0194 §11).
SENTINEL_RECIPIENT = "zzq-recipient-sentinel@example.invalid"
SENTINEL_SUBJECT = "zzq-subject-sentinel"

#: The two refusals ADR-0194 §4 gives ``admit_invocation``, driven as one
#: parameterisation everywhere the clause binds both.
REFUSALS = [
    SpendCeilingError("the projected total 101 crosses the CALENDAR_DAY ceiling of 100"),
    SpendUndeterminedError("the CALENDAR_DAY period could not be measured"),
]


def user_facing_channels(exception: BaseException) -> list[str]:
    """Render every channel ADR-0029 §3's message rule encloses, as text.

    ``str()``, ``repr()``, ``args``, ``__notes__``, ``__cause__``,
    ``__context__``, and any field the class itself declares. Stated as a
    **closed** set because a check for "no attribute anywhere" would be
    unsatisfiable: ``__traceback__`` is the interpreter's, and a propagating
    exception necessarily carries frames whose locals include the ``ToolCall``.
    """
    declared = [
        f"{name}={value!r}" for name, value in vars(exception).items() if not name.startswith("__")
    ]
    return [
        str(exception),
        repr(exception),
        repr(exception.args),
        repr(getattr(exception, "__notes__", ())),
        repr(exception.__cause__),
        repr(exception.__context__),
        *declared,
    ]


def trail_of(invoker: InvocableToolRegistry) -> FakeAuditTrail:
    """Read back the trail an ``admitting``-built subject claims through."""
    ledger = invoker.ledger
    assert isinstance(ledger, FakeAuditTrail), (
        "this suite arranges authorisations through the trail the subject holds"
    )
    return ledger


# --- ADR-0194 §3: the gate doubles this suite admits through -----------------

#: What a gate fake returns where the suite does not care which value it is.
_HANDLE = "spend-handle"


class RecordingGate:
    """A ``SpendGate`` that records what it was asked and what was released.

    ADR-0194 §11 requires the invoker suite to drive over a gate fake that
    **records its arguments**: without it, an invoker passing ``FREE`` for a
    registered ``PER_CALL`` cost of 20 lets the callable begin at an accounted
    total of 90 against a ceiling of 100 and still passes every refusal, release
    and no-row clause beside it, because none of those looks at what was handed
    over.

    It also tracks which handles are still outstanding, so a test can assert the
    projection a *later* admission would see rather than only that a release was
    called — the assertion ADR-0194 §3's cancellation and blocked-gate clauses
    are actually about.
    """

    def __init__(self, *, refusal: BaseException | None = None) -> None:
        """Admit everything, or refuse every call with ``refusal``."""
        self.estimates: list[ToolCost] = []
        self.released: list[SpendAdmissionHandle] = []
        self.outstanding: list[SpendAdmissionHandle] = []
        self._refusal = refusal
        self._minted = 0

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Record ``estimate``, then admit or refuse."""
        self.estimates.append(estimate)
        if self._refusal is not None:
            raise self._refusal
        self._minted += 1
        handle = SpendAdmissionHandle(handle=f"{_HANDLE}-{self._minted}")
        self.outstanding.append(handle)
        return handle

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Retire ``handle``, tolerating one that names no live reservation."""
        self.released.append(handle)
        if handle in self.outstanding:
            self.outstanding.remove(handle)


class BlockingGate:
    """A gate whose admission never answers, and which cooperates with cancellation.

    Cancellation-cooperative **by construction**, which is what makes the
    deadline assertion one about the seam rather than about ADR-0029 §4's
    excluded case (ADR-0194 §3): a fake built on a thread or a shielded wait
    would make the clause untestable rather than failing it.
    """

    def __init__(self) -> None:
        """Answer nothing; record whether the admission was entered and cancelled."""
        self.entered = 0
        self.cancelled = 0
        self.outstanding: list[SpendAdmissionHandle] = []
        self.released: list[SpendAdmissionHandle] = []

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Wait forever, and leave no reservation behind when cancelled."""
        del estimate
        self.entered += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # ADR-0194 §3: a reservation whose handle will never be delivered is
            # removed before the exception leaves the member. This fake records
            # none in the first place, and asserting on `outstanding` is what
            # makes the invoker's side of that checkable.
            self.cancelled += 1
            raise
        raise AssertionError  # pragma: no cover — the wait never returns

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Retire ``handle``; nothing here ever delivered one."""
        self.released.append(handle)


class SlowGate:
    """A gate that consumes a fixed slice of the caller's deadline and then admits."""

    def __init__(self, spends: float) -> None:
        """Take ``spends`` seconds over the admission."""
        self._spends = spends
        self.released: list[SpendAdmissionHandle] = []

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Sleep, then admit."""
        del estimate
        await asyncio.sleep(self._spends)
        return SpendAdmissionHandle(handle=_HANDLE)

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Retire ``handle``."""
        self.released.append(handle)


class Sleeper:
    """A tool implementation that sleeps for a fixed duration and then succeeds."""

    def __init__(self, seconds: float) -> None:
        """Sleep ``seconds`` on every call."""
        self._seconds = seconds
        self.calls = 0

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Sleep, then return nothing."""
        del parameters, idempotency_key
        self.calls += 1
        await asyncio.sleep(self._seconds)
        return None


# --- ADR-0195: what a tool reports its own call cost ------------------------
#
# The channel's producer is deliberately **test-only**. ADR-0195 §7 requires it:
# no integration in the tree reports a figure, `send_email` reports none because
# SMTP carries no price, and teaching a production integration to report a number
# nobody measured — in order to make an end-to-end case pass — is the fiction
# ADR-0016 §4 refused on the declaration side, reached from the other end.

#: The figure a test-only priced integration reports.
REPORTED = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.03"), currency="USD")

#: What an interceptor returns to mean "hand back the real value".
PASS: Final = object()


class Priced:
    """A test-only priced integration: it returns its output **and** its price."""

    def __init__(self, output: FrozenJson = None, cost: ToolCost = REPORTED) -> None:
        """Return ``output`` at ``cost`` on every call."""
        self.calls = 0
        self._output = output
        self._cost = cost

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> ReportedOutput:
        """Report what this call cost, on the exit a successful call composes."""
        self.calls += 1
        return ReportedOutput(output=self._output, incurred_cost=self._cost)


class Envelope:
    """A tool that hands back one **prepared** envelope, whatever is in it.

    Separate from :class:`Priced` because half of ADR-0195's cases are about a
    hostile or unvalidated envelope the case itself built — a subclass counting
    its reads, or a ``model_construct``-built one carrying an output the
    annotation refuses.
    """

    def __init__(self, envelope: ReportedOutput) -> None:
        """Return ``envelope`` on every call."""
        self.calls = 0
        self._envelope = envelope

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> ReportedOutput:
        """Hand back the prepared envelope."""
        self.calls += 1
        return self._envelope


def unvalidated(output: object, cost: ToolCost = REPORTED) -> ReportedOutput:
    """An envelope pydantic never validated, so ``output`` reaches the seam.

    Constructed normally the refused value would raise in the tool's own frame
    (which is the other half of ADR-0195 §2's clause, pinned on the model in
    ``tests/core``). ``model_construct`` is what lets the same value reach the
    seam's *own* construction of the ``ToolResult`` — the arm §11 names.
    """
    return ReportedOutput.model_construct(output=output, incurred_cost=cost)


class SwallowingPriced:
    """A priced tool that **absorbs** its cancellation and returns an envelope anyway.

    The shape that makes ADR-0195 §4's first interruption check assertable: a
    seam that checked only after reading would build a result carrying a figure
    obtained after it had stopped waiting, and one that checked only before would
    still have entered the accessors. Neither field is read here, and the
    envelope reports that.
    """

    def __init__(self, envelope: ReportedOutput) -> None:
        """Return ``envelope`` after absorbing whatever cancellation arrives."""
        self.entered = asyncio.Event()
        self._envelope = envelope

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> ReportedOutput:
        """Absorb the cancellation and return the envelope regardless."""
        self.entered.set()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)
        return self._envelope


class Accesses:
    """How many times each of a watched envelope's two fields was read."""

    def __init__(self) -> None:
        """Nothing read yet."""
        self.counts: dict[str, int] = {"output": 0, "incurred_cost": 0}


def watched(
    *,
    output: FrozenJson = None,
    cost: ToolCost = REPORTED,
    intercept: Callable[[str, int], object] | None = None,
) -> tuple[ReportedOutput, Accesses]:
    """A ``ReportedOutput`` **subclass** that counts, and can sabotage, its reads.

    ``isinstance`` admits a subclass, so both of the envelope's fields are
    tool-authored reads (ADR-0195 §2) and a seam that read either one twice would
    be reading a value it had not judged. ``intercept`` is called with the field's
    name and its 1-based access count *before* the real value is handed back; it
    may raise, cancel the invoking task, or return a substitute, and returning
    :data:`PASS` means "the real value".

    The counter is armed only after construction, so pydantic's own reads while
    building the model are not what a case measures.
    """
    seen = Accesses()
    armed = False

    class Watched(ReportedOutput):
        def __getattribute__(self, name: str) -> object:
            if armed and name in seen.counts:
                seen.counts[name] += 1
                if intercept is not None:
                    substitute = intercept(name, seen.counts[name])
                    if substitute is not PASS:
                        return substitute
            return super().__getattribute__(name)

    built = Watched(output=output, incurred_cost=cost)
    armed = True
    return built, seen


def hostile_after_the_first(name: str, count: int) -> object:
    """Answer the first read truthfully; raise on the second, differ on the third.

    ADR-0195 §11's own shape, and the reason it is not a matrix of hostile
    *first* accesses: that matrix is satisfiable by an implementation which reads
    ``output`` a second time when it builds the ``ToolResult``, which is exactly
    the path §2's single-read clause exists to close.
    """
    if count == 1:
        return PASS
    if count == 2:
        msg = f"{name} may be read only once"
        raise RuntimeError(msg)
    return "a different answer entirely"


def dumping(behaviour: Callable[[], Mapping[str, object] | None]) -> ToolCost:
    """A ``ToolCost`` whose ``model_dump`` runs ``behaviour`` before answering.

    Overriding it is **legitimate** — ADR-0032 §6 rules that "the round-trip's
    result is what crosses" — which is precisely why the seam runs it under a
    guard rather than trusting it. ``behaviour`` returning ``None`` means "answer
    normally".
    """

    class Dumping(ToolCost):
        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            substitute = behaviour()
            if substitute is not None:
                return dict(substitute)
            return super().model_dump(*args, **kwargs)

    return Dumping(basis=CostBasis.PER_CALL, amount=Decimal("0.03"), currency="USD")


def cancel_this_task() -> None:
    """Cancel whichever task is invoking, from inside tool-authored code."""
    task = asyncio.current_task()
    assert task is not None, "these cases drive `invoke` inside a task"
    task.cancel()


# --- ADR-0032: a failure the tool classified itself -------------------------
#
# The producer here is test-only for ADR-0195 §7's reason one type over: no
# integration in the tree classifies its own failure yet, ADR-0017 §3's egress
# conditions are undischarged, and the first real one arrives with its own ADR.

#: The message a classified failure carries, so a case can assert it **verbatim**
#: — ADR-0032 §5's by-value rule is that the seam never edits, wraps, prefixes,
#: truncates or re-authors a tool's text.
REPORTED_MESSAGE = "the upstream returned 429 and asked us to back off"

#: What a classified failure reports about a call that was nonetheless billed.
CLASSIFIED_COST = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.07"), currency="USD")

#: ADR-0029 §3's six **integration-facing** kinds — the ones that had no carrier
#: at all, which is what #192 asked for and what ADR-0032 gives them. ``INTERNAL``
#: is accepted as raised too but is the seam's own synthesis elsewhere, and
#: ``TIMED_OUT`` is reserved (§3); both are covered by the exhaustive case.
INTEGRATION_KINDS: Final = (
    ToolFailureKind.INVALID_REQUEST,
    ToolFailureKind.NOT_AUTHORISED,
    ToolFailureKind.UNAVAILABLE,
    ToolFailureKind.RATE_LIMITED,
    ToolFailureKind.REFUSED,
    ToolFailureKind.CANCELLED,
)

#: Means "delete this attribute" rather than "assign this value" — ADR-0032 §6
#: names deletion specifically, because ``del exc.failure`` is as reachable as
#: assigning ``None`` to it and an implementation reading the attribute directly
#: raises a raw ``AttributeError`` where the rule requires a result.
DELETED: Final = object()


def carrier(
    kind: ToolFailureKind = ToolFailureKind.RATE_LIMITED,
    message: str = REPORTED_MESSAGE,
    *,
    committed: bool = False,
    cost: ToolCost | None = None,
) -> ClassifiedToolError:
    """A carrier built the way an integration author writes one."""
    return ClassifiedToolError(
        ToolFailure(kind=kind, message=message),
        effect_may_have_committed=committed,
        incurred_cost=cost,
    )


def tampered(
    *, committed: bool | object = False, cost: ToolCost | None = None, **attributes: object
) -> ClassifiedToolError:
    """A validly-constructed carrier, then written to **past** its constructor.

    ADR-0032 §6's subject: an exception's attributes are ordinary attributes, an
    integration is not required to have been type-checked, and ``isinstance`` is
    not evidence that a pydantic model was validated. Every arrangement here is
    reachable in ordinary Python on an object the seam did not write.
    """
    built = carrier(cost=cost)
    if committed is not False:
        attributes = {"effect_may_have_committed": committed, **attributes}
    for name, value in attributes.items():
        if value is DELETED:
            delattr(built, name)
        else:
            setattr(built, name, value)
    return built


def unreadable(
    name: str, *, committed: bool = False, cost: ToolCost | None = None
) -> ClassifiedToolError:
    """A carrier whose access to ``name`` **raises**, as a tool's property would.

    ``isinstance`` admits a subclass, so every attribute of a carrier is a
    tool-authored read — and an exception raised inside an ``except`` body is not
    caught by the sibling ``except`` clauses of the same ``try``, so an unguarded
    read leaves ``invoke`` uncaught exactly where the rule requires a result.
    """

    class UnreadableError(ClassifiedToolError):
        def __getattribute__(self, attribute: str) -> object:
            if attribute == name:
                msg = f"{attribute} is not available"
                raise RuntimeError(msg)
            return super().__getattribute__(attribute)

    return UnreadableError(
        ToolFailure(kind=ToolFailureKind.RATE_LIMITED, message=REPORTED_MESSAGE),
        effect_may_have_committed=committed,
        incurred_cost=cost,
    )


def dumped(behaviour: Callable[[], Mapping[str, object] | None]) -> ToolFailure:
    """A ``ToolFailure`` whose ``model_dump`` runs ``behaviour`` before answering.

    Overriding it is **legitimate** — ADR-0032 §6 declines to arbitrate between
    two accounts a tool gives of its own failure, and rules that "the round-trip's
    result is what crosses" — which is precisely why the seam runs it under a
    guard rather than trusting it. ``behaviour`` returning ``None`` means "answer
    normally".
    """

    class Dumped(ToolFailure):
        def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            substitute = behaviour()
            if substitute is not None:
                return dict(substitute)
            return super().model_dump(*args, **kwargs)

    return Dumped(kind=ToolFailureKind.RATE_LIMITED, message=REPORTED_MESSAGE)


class Impostor(BaseModel):
    """A ``ToolFailure``-shaped value of another class entirely (ADR-0032 §6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ToolFailureKind
    message: str


class Reads:
    """How many times each of a watched carrier's three attributes was read."""

    def __init__(self) -> None:
        """Nothing read yet."""
        self.counts: dict[str, int] = {
            "failure": 0,
            "effect_may_have_committed": 0,
            "incurred_cost": 0,
        }


def watched_carrier(
    *,
    committed: bool = False,
    cost: ToolCost | None = None,
    intercept: Callable[[str, int], object] | None = None,
) -> tuple[ClassifiedToolError, Reads]:
    """A carrier **subclass** that counts, and can sabotage, its three reads.

    ``isinstance`` admits a subclass, so every attribute of a carrier is a
    tool-authored read (ADR-0032 §6). ``intercept`` is called with the attribute's
    name and its 1-based access count *before* the real value is handed back; it
    may raise, cancel the invoking task, or return a substitute, and returning
    :data:`PASS` means "the real value".

    The counter is armed only after construction, so the constructor's own writes
    are not what a case measures.
    """
    seen = Reads()
    armed = False

    class WatchedError(ClassifiedToolError):
        def __getattribute__(self, name: str) -> object:
            if armed and name in seen.counts:
                seen.counts[name] += 1
                if intercept is not None:
                    substitute = intercept(name, seen.counts[name])
                    if substitute is not PASS:
                        return substitute
            return super().__getattribute__(name)

    built = WatchedError(
        ToolFailure(kind=ToolFailureKind.RATE_LIMITED, message=REPORTED_MESSAGE),
        effect_may_have_committed=committed,
        incurred_cost=cost,
    )
    armed = True
    return built, seen


def refuses_to_dump() -> Mapping[str, object] | None:
    """A ``model_dump`` that raises — legitimate to override, so guarded not trusted."""
    msg = "this value refuses to be dumped"
    raise RuntimeError(msg)


class BlankMessage:
    """A tool whose classified raise never gets built (ADR-0032 §1).

    ``ToolFailure._message_is_present`` fires in the **tool's own frame**, at the
    raise site where the author can see it, so the carrier never exists and what
    escapes is an ordinary ``ValidationError``. That is the ordinary path and not
    a guarantee, which is why the suite pins the ``model_construct`` route beside
    it.
    """

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Try to classify a failure with a message that renders as nothing."""
        raise ClassifiedToolError(
            ToolFailure(kind=ToolFailureKind.RATE_LIMITED, message="   "),
            effect_may_have_committed=False,
        )


class SwallowingClassifier:
    """A tool that **absorbs** its cancellation and raises a carrier anyway.

    The shape that makes ADR-0032 §4's ranks 1 and 2 assertable against rank 3: a
    seam checking the carrier first would answer with the tool's own kind for a
    call it had already stopped waiting for, and one checking only after reading
    would still have entered the carrier's accessors.
    """

    def __init__(self, raising: ClassifiedToolError) -> None:
        """Raise ``raising`` after absorbing whatever cancellation arrives."""
        self.entered = asyncio.Event()
        self._raising = raising

    async def __call__(
        self, parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
    ) -> FrozenJson:
        """Absorb the cancellation and raise the carrier regardless."""
        self.entered.set()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)
        raise self._raising


class ToolInvokerContract:
    """Behaviour every ``ToolInvoker`` implementation must exhibit."""

    @pytest.fixture
    def consuming(self) -> Callable[[InvocationLedger], InvocableToolRegistry]:
        """Return a factory building an empty invoker over ``ledger``.

        A factory rather than a built subject, because half the consume cases need
        the ledger *wrapped* — held on a barrier, made to fail, made to fail after
        it committed — and an invoker is handed its ledger at construction.
        """
        raise NotImplementedError

    @pytest.fixture
    def invoker(self) -> InvocableToolRegistry:
        """The subject, and it is **ledger-bearing** like every other invoker.

        Since ADR-0192 §1 made the consume unconditional there is no ledger-free
        ``ToolInvoker`` to be had, so this suite has one subject rather than an
        ordinary one beside a consuming one — a second, non-conforming fixture
        would leave the ordinary subject unbound by the new obligations while they
        were pinned on a different object.

        Overridden by each binding subclass and **taking no other fixture**, which
        is what lets ``tests/core/test_protocol_triad.py`` evaluate it and see the
        canonical fake come out (CONTRIBUTING, "Adding a Protocol"). The trail is
        read back off the subject rather than injected beside it, for the same
        reason the composition root wires one object: two would leave the seam
        claiming against a store the test never recorded into.
        """
        raise NotImplementedError

    @pytest.fixture
    def trail(self, invoker: InvocableToolRegistry) -> FakeAuditTrail:
        """The trail the subject claims through, read back off the subject."""
        ledger = invoker.ledger
        assert isinstance(ledger, FakeAuditTrail), (
            "this suite arranges authorisations through the trail the subject holds"
        )
        return ledger

    # --- §1: one registry, two faces ------------------------------------

    async def test_the_invocable_set_is_exactly_all_tools(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The biconditional, asserted as set equality rather than exhorted.

        An implementation keeping a second table of callables — two mappings
        that could be rebound independently — fails here rather than at review.
        """
        invoker.register(tool("alpha"), Spy())
        invoker.register(tool("zulu"), Spy())

        declared = {each.id for each in await invoker.all_tools()}
        invocable = set()
        for each in await invoker.all_tools():
            # A decision id apiece: two tools authorised under one id is not a
            # trail this store could hold, and since ADR-0192 §1 the seam reads it.
            result = await invoked(
                invoker, trail, call_for(each, decision_id=f"d-{each.id}"), timeout=PATIENT
            )
            assert result.outcome is ToolOutcome.SUCCEEDED
            invocable.add(each.id)

        assert invocable == declared == {"alpha", "zulu"}

        unregistered = tool("never-registered")
        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call_for(unregistered), timeout=PATIENT)

    async def test_an_unbound_id_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Nothing is bound, so there is nothing to invoke."""
        with pytest.raises(ToolBindingError, match="smtp"):
            await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

    async def test_a_tampered_but_still_valid_definition_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0018 §4's named gap, closing here.

        ``risk_level`` moved from ``CRITICAL`` to ``LOW`` rebuilds successfully,
        so no amount of re-validation catches it. The registry is the only holder
        of an untampered original, and this seam is the only place all three
        declarations meet.
        """
        spy = Spy()
        invoker.register(tool(risk_level=RiskLevel.CRITICAL), spy)

        # A wholly valid call — about a *different* declaration under the same id.
        downgraded = call_for(tool(risk_level=RiskLevel.LOW))

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, downgraded, timeout=PATIENT)
        assert spy.calls == [], "the callable must not be reached"

    # --- §2: refused again at the seam ----------------------------------

    async def test_parameters_swapped_after_construction_are_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """``frozen=True`` does not survive a ``__dict__`` write.

        Construct a call approving one recipient, replace ``parameters`` with a
        valid frozen mapping naming another, and a seam checking only the
        definition would execute the second under the first's approval.
        """
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool(), parameters={"to": "approved@example.com"})

        swapped = ActionRequest(
            tool=tool(),
            parameters={"to": "elsewhere@example.com"},
            step_id=call.request.step_id,
        )
        call.__dict__["request"] = swapped

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_replaced_decision_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A decision about a different payload cannot authorise this one."""
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool(), parameters={"to": "approved@example.com"})
        other = call_for(tool(), parameters={"to": "elsewhere@example.com"}, decision_id="d-2")
        call.__dict__["decision"] = other.decision

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_substituted_definition_is_refused(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The declaration on the call is rewritten after it was authorised."""
        spy = Spy()
        invoker.register(tool(risk_level=RiskLevel.CRITICAL), spy)
        call = call_for(tool(risk_level=RiskLevel.CRITICAL))

        object.__setattr__(call.request.tool, "risk_level", RiskLevel.LOW)

        with pytest.raises(ToolBindingError):
            await invoked(invoker, trail, call, timeout=PATIENT)
        assert spy.calls == []

    async def test_a_malformed_parameter_mutation_is_a_binding_error_from_revalidation(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The **order** of the checks, which only a malformed mutation distinguishes.

        ``authorises`` compares ``parameters_digest``, which canonicalises the
        mapping to JSON. Run before revalidation, a payload ``FrozenJson`` would
        never have accepted raises a raw serialisation error out of a method
        whose contract is that it answers a question — after the executor has
        already committed its ``→ RUNNING`` claim, leaving the step durably
        ``RUNNING`` until recovery. Revalidating first turns it into a rejection,
        and the ``ValidationError`` cause is the evidence of which ran.

        A suite mutating only into *valid* states passes under either order.
        """
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())

        malformed = ActionRequest.model_construct(
            tool=call.request.tool,
            parameters={"to": {"a", "set", "has", "no", "json"}},
            step_id=call.request.step_id,
        )
        call.__dict__["request"] = malformed

        with pytest.raises(ToolBindingError) as caught:
            await invoked(invoker, trail, call, timeout=PATIENT)

        assert isinstance(caught.value.__cause__, ValidationError), (
            "a malformed mutation must be rejected by revalidation, not by the digest"
        )
        assert spy.calls == []

    # --- §4: the deadline -----------------------------------------------

    async def test_a_side_effecting_non_natural_tool_that_times_out_is_indeterminate(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0014 §4's case, reached through a deadline rather than a crash."""
        invoker.register(tool(), Slow())

        result = await invoked(invoker, trail, call_for(tool()), timeout=BRIEF)

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert result.output is None

    @pytest.mark.parametrize("definition", [read_only(), natural()], ids=["read-only", "natural"])
    async def test_a_read_only_or_natural_tool_that_times_out_is_failed(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, definition: ToolDefinition
    ) -> None:
        """A read changed nothing; a ``NATURAL`` repeat does the same thing again."""
        invoker.register(definition, Slow())

        result = await invoked(invoker, trail, call_for(definition), timeout=BRIEF)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    @pytest.mark.parametrize(
        "bad",
        [timedelta(0), timedelta(seconds=-1), 5, None, "30s"],
        ids=["zero", "negative", "int", "none", "str"],
    )
    async def test_a_timeout_that_is_not_a_positive_timedelta_raises(
        self, invoker: InvocableToolRegistry, bad: object
    ) -> None:
        """Refused before the tool's coroutine is created.

        Not "expired means do not call": expiry is delivered at an await point,
        so a callable performing a synchronous side effect before its first
        ``await`` would already have acted. Refusing the value never creates the
        coroutine, which is the only placement that holds for every tool.
        """
        spy = Spy()
        invoker.register(tool(), spy)

        with pytest.raises(ValueError, match="timeout"):
            await invoker.invoke(call_for(tool()), timeout=bad)  # type: ignore[arg-type]  # the guard is the subject  # type: ignore[arg-type]
        assert spy.calls == []

    @pytest.mark.parametrize(
        "duration",
        ["raises", float("inf"), "not a number"],
        ids=["read-raises", "infinite", "non-numeric"],
    )
    async def test_a_timedelta_subclasss_overrides_never_decide_the_deadline(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], duration: object
    ) -> None:
        """``isinstance`` admits a subclass, and the deadline is opened after the claim.

        A guard that validates the caller's object and hands the same object on
        accepts anything ``isinstance`` calls a ``timedelta``, and the seam then
        reads the duration *later* — opening ``asyncio.timeout`` after the claim
        has landed. A ``total_seconds`` that raises there escapes with a claim
        open, no completion written and no ``ToolResult`` at all, which is exactly
        the exit ADR-0192 §3 makes total over; one returning ``inf`` disables the
        deadline ADR-0029 §4 says there always is, in the one method whose
        contract is that there is one.

        So the duration is taken **before** the claim and from the base class's
        own fields, which a subclass cannot shadow. The three arms are three ways
        an override could decide something, and the assertion is the same in each:
        it decided nothing. The call runs normally, under its true 30 seconds,
        with the claim appended once and completed — no refusal invented, and no
        open row left behind.

        Refusing the value would also be a defensible design, and is a worse one:
        a plain ``timedelta`` is a valid deadline whatever a subclass says about
        it, and rejecting the whole subclass would make ``invoke`` refuse durations
        it can enforce exactly.
        """

        class Hostile(timedelta):
            """A real 30 seconds by every field, and a liar about all of them."""

            def total_seconds(self) -> float:
                if duration == "raises":
                    msg = "the duration refuses to be read"
                    raise RuntimeError(msg)
                return duration  # type: ignore[return-value]  # the guard is the subject

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 2}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=Hostile(seconds=30))

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == {"unread": 2}
        assert ledger.claim.calls == 1
        assert ledger.completion.calls == 1
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the deadline is the base class's, so nothing raises after the claim"
        )

    async def test_a_timedelta_subclass_that_is_not_positive_is_still_refused(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """And the positivity check reads the snapshot, not the subclass.

        The companion to the case above: taking the duration from the base fields
        must not become a way *past* the guard. A subclass reporting itself
        positive through an overridden comparison is still zero, and is refused
        before the claim exactly as a plain ``timedelta(0)`` is.
        """

        class Optimistic(timedelta):
            """Claims to be longer than anything it is compared with."""

            def __le__(self, other: timedelta) -> bool:
                return False

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(read_only("inbox"), spy)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with pytest.raises(ValueError, match="timeout"):
            await invoker.invoke(call, timeout=Optimistic(0))

        assert spy.calls == [], "the callable is never entered"
        assert ledger.claim.calls == 0, "a refused deadline leaves no open invocation"

    async def test_a_tool_that_suppresses_its_cancellation_outlives_its_deadline(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The cooperative limit, deterministically (ADR-0029 §4).

        "Timeout" here means the seam stops waiting, not that the tool stops
        working — and no seam can make it stronger, because ``asyncio.timeout``
        does not return until the inner frame finishes unwinding. Pinning the
        limit is what stops an implementation quietly acquiring a watchdog.
        """
        stubborn = Stubborn()
        invoker.register(tool(), stubborn)

        running = asyncio.ensure_future(invoked(invoker, trail, call_for(tool()), timeout=BRIEF))
        await stubborn.entered.wait()
        await asyncio.sleep(BRIEF.total_seconds() * 5)

        assert not running.done(), "the deadline is not a hard bound, and must not look like one"

        stubborn.release.set()
        result = await running
        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    # --- §3: an exception escaping the tool ------------------------------

    async def test_a_raising_tool_becomes_an_internal_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Integration authors raise; a seam that let that propagate would leave
        the step durably ``RUNNING`` with nothing recording why.
        """
        invoker.register(tool(), Raiser(RuntimeError("upstream said no")))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.kind.retryable is False

    @pytest.mark.parametrize(
        "hostile",
        ["raises", "cancels", "str-subclass", "unrepresentable"],
    )
    async def test_a_tool_whose_exception_class_is_hostile_is_still_an_internal_result(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], hostile: str
    ) -> None:
        """ADR-0029 §3's rule has to survive the class the *tool* chose.

        A broken tool becomes a ``ToolResult``, not an exception — and the seam
        builds that result by naming the exception's class. Everything about that
        name comes from an object the tool controls, and this runs **after** the
        claim, so each way it can misbehave has the same two consequences:
        ``invoke`` leaves without a ``ToolResult``, and ADR-0192 §3 gets no
        completion for a claim it already appended — a known-failed act
        permanently spending its authorisation with its failure lost as data.

        The four arms are the four ways it misbehaves.

        - ``raises`` — the ``__name__`` access raises an ``Exception``.
        - ``cancels`` — it raises a ``CancelledError`` instead. Nothing was
          cancelled: this branch has already established that (ADR-0029 §4), and
          the read is synchronous, so delivering it would report a cancellation
          nobody asked for **and** leave the claim open. ADR-0031 §2 calls an
          invented one exactly that, and §4 makes it ``INTERNAL``.
        - ``str-subclass`` — the access returns a ``str`` subclass whose
          ``__format__`` raises, so the *message* build is where the frame is
          lost rather than the read.
        - ``unrepresentable`` — the name is a valid string carrying content. It
          reaches a ``ToolFailure.message`` and a log, and ADR-0004 §5 rules a log
          Tier 2 only, so a class named after a recipient is a disclosure on the
          failure path of every tool nobody thought about.

        In all four the answer is the same, and it is ``core``'s own reserved
        literal rather than one invented at this seam.
        """
        sentinel = "recipient@example.com"

        class Formatting(str):
            """A name that passes every check and then runs its own code."""

            def __format__(self, spec: str) -> str:
                msg = "the name refuses to be rendered"
                raise RuntimeError(msg)

        class Named(type):
            """A metaclass that misbehaves on the ``__name__`` access."""

            def __getattribute__(cls, name: str) -> object:
                if name == "__name__":
                    if hostile == "raises":
                        msg = "the metaclass refuses to be named"
                        raise RuntimeError(msg)
                    if hostile == "cancels":
                        raise asyncio.CancelledError
                    if hostile == "str-subclass":
                        return Formatting("RuntimeError")
                    return sentinel
                return super().__getattribute__(name)

        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(read_only("inbox"), Raiser(Named("H", (RuntimeError,), {})("upstream")))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.message == (
            f"{UNREPRESENTABLE_FAULT_CLASS} escaped tool {read_only('inbox').id!r}"
        )
        assert sentinel not in repr(captured), "a class name is as attacker-controlled as a message"
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the completion is written, so the claim does not stay open"
        )

    async def test_the_exceptions_own_text_never_reaches_the_failure_message(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The message-leak rule (§3), which nothing downstream would catch.

        ``core/logging.py`` redacts by *key* and names ``error=str(exc)`` as the
        Tier 1 leak it cannot see. ``message`` lands under precisely such a key,
        in a log and in ``StepExecution.error``, so the rule has to hold at the
        producer: a message the seam generates carries no content it did not
        author.
        """
        invoker.register(tool(), Raiser(RuntimeError("recipient alice@example.com rejected")))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert "alice@example.com" not in result.failure.message
        assert "rejected" not in result.failure.message
        assert "RuntimeError" in result.failure.message

    @pytest.mark.parametrize("value", [{"a", "set"}, float("nan")], ids=["set", "nan"])
    async def test_a_return_value_frozen_json_refuses_becomes_internal(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, value: object
    ) -> None:
        """A tool whose return value will not validate is broken, and saying so
        is more useful than storing something unserialisable — or than letting a
        ``ValidationError`` escape a method that returns classified data.
        """
        invoker.register(tool(), Returner(value))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL

    async def test_a_tools_own_timeout_error_inside_the_deadline_is_internal(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """``TIMED_OUT`` means *this* deadline expired, established not inferred.

        An upstream SDK raises Python's ``TimeoutError`` for its own reasons —
        a connect timeout, a read timeout it configures itself — often long
        inside our budget. Classifying by catching the type would label it
        ``TIMED_OUT`` and, for this side-effecting tool, escalate it to
        ``INDETERMINATE``: a call that failed fast and provably did nothing,
        recorded as one whose effect is unknown and therefore excluded from
        retry.
        """
        invoker.register(tool(), Raiser(TimeoutError("the upstream's own deadline")))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.outcome is ToolOutcome.FAILED

    async def test_a_base_exception_propagates_rather_than_becoming_a_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A guard whose own failure modes bypass its failure path enforces nothing."""
        invoker.register(tool(), Raiser(KeyboardInterrupt()))

        with pytest.raises(KeyboardInterrupt):
            await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

    # --- §4: cancellation, classified by provenance ----------------------

    async def test_a_cancelled_error_the_tool_invents_is_an_internal_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Nothing about the exception's type says where it came from.

        A tool raising one before it issues its request would otherwise read as
        an external teardown: the executor would record ``INDETERMINATE`` for a
        call that did nothing, and re-raise — cancelling a request nobody
        cancelled, on a tool's say-so. Paired with the next test, this is what
        pins the classification to provenance rather than to the type.
        """
        invoker.register(tool(), Raiser(asyncio.CancelledError()))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        task = asyncio.current_task()
        assert task is not None
        assert task.cancelling() == 0, "nothing was cancelled, so nothing may be left cancelling"

    @pytest.mark.parametrize(
        "definition", [tool(), read_only()], ids=["side-effecting", "read-only"]
    )
    async def test_an_external_cancellation_propagates_on_both_branches(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, definition: ToolDefinition
    ) -> None:
        """The seam does not convert a real cancellation into a result.

        Swallowing it would break structured concurrency and shutdown, and there
        is no return path from a task being torn down. Committing the step by
        ADR-0029 §4's rule and then re-raising is the *executor's* obligation
        (§8), which is why what is pinned here is that the exception arrives
        rather than that a status was written.
        """
        slow = Slow()
        invoker.register(definition, slow)

        running = asyncio.ensure_future(
            invoked(invoker, trail, call_for(definition), timeout=PATIENT)
        )
        await slow.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running

    async def test_a_tool_that_absorbs_its_deadline_is_not_reported_successful(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The deadline is read from the timeout, not inferred from an exception.

        A callable that catches the cancellation ``asyncio.timeout`` injects and
        returns a value leaves nothing to catch — so an implementation
        classifying only on what was raised hands back ``SUCCEEDED`` for a
        side-effecting call that ran past its deadline, which is the one
        direction ADR-0014 §4 refuses to guess in.
        """
        swallower = Swallower()
        invoker.register(tool(), swallower)

        result = await invoked(invoker, trail, call_for(tool()), timeout=BRIEF)

        assert swallower.swallowed, "the fixture must actually absorb the cancellation"
        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT

    async def test_a_tool_that_absorbs_an_external_cancellation_still_cancels_the_call(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A cancelled task must not be answered with a result.

        The cancellation was requested of the *invoking task*, and a callable
        catching it does not withdraw the request. Returning normally here would
        report a cancelled turn as ``SUCCEEDED`` and leave the executor with no
        cancellation to commit against or re-raise (ADR-0029 §4).
        """
        swallower = Swallower()
        invoker.register(tool(), swallower)

        running = asyncio.ensure_future(invoked(invoker, trail, call_for(tool()), timeout=PATIENT))
        await swallower.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await running
        assert swallower.swallowed

    @pytest.mark.parametrize(
        ("implementation", "expected"),
        [
            (Spy(), ToolOutcome.SUCCEEDED),
            (Raiser(asyncio.CancelledError()), ToolOutcome.FAILED),
        ],
        ids=["succeeds", "invents-a-cancellation"],
    )
    async def test_a_caller_that_absorbed_an_earlier_cancellation_is_not_treated_as_cancelled(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        implementation: FakeToolImplementation,
        expected: ToolOutcome,
    ) -> None:
        """Provenance is a delta, not a count.

        ``Task.cancelling()`` is a lifetime total that only ``uncancel()``
        lowers, so a caller that caught an earlier cancellation to finish some
        work still carries a positive count with nothing about *this* call
        cancelled. An implementation reading it as a boolean fails every
        subsequent invocation on that task, and turns a tool's invented
        ``CancelledError`` — which §4 requires to be ``INTERNAL`` — into a
        cancellation on the strength of something that predates the seam.
        """
        invoker.register(tool(), implementation)
        reached_the_sleep = asyncio.Event()

        async def caller() -> ToolOutcome:
            try:
                reached_the_sleep.set()
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass  # absorbed, and deliberately not `uncancel()`-ed
            result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)
            return result.outcome

        running = asyncio.ensure_future(caller())
        await reached_the_sleep.wait()
        running.cancel()

        assert await running is expected

    # --- §5: the key is the authorisation --------------------------------

    async def test_a_keyed_tool_receives_the_decision_id_as_its_key(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Derived, not minted: there is no caller field to fill in wrongly."""
        spy = Spy()
        invoker.register(keyed(), spy)

        await invoked(invoker, trail, call_for(keyed(), decision_id="d-42"), timeout=PATIENT)

        assert [key for _, key in spy.calls] == ["d-42"]

    @pytest.mark.parametrize(
        "definition", [tool(), natural()], ids=["idempotency-none", "idempotency-natural"]
    )
    async def test_a_tool_that_is_not_keyed_receives_no_key(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, definition: ToolDefinition
    ) -> None:
        """A key is meaningless to a tool that made no guarantee about one."""
        spy = Spy()
        invoker.register(definition, spy)

        await invoked(invoker, trail, call_for(definition), timeout=PATIENT)

        assert [key for _, key in spy.calls] == [None]

    async def test_the_key_is_identical_across_retries_of_one_call(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """There is deliberately no attempt counter: a key that varied per
        attempt would defeat the guarantee at exactly the moment it is needed.
        """
        spy = Spy()
        # Not spendable, so ADR-0192 §1 refuses no repetition and the *key* is
        # what this case is left testing — which is what it was always about.
        invoker.register(gated(), spy)
        call = call_for(gated(), decision_id="d-7")

        await invoked(invoker, trail, call, timeout=PATIENT)
        await invoked(invoker, trail, call, timeout=PATIENT)

        assert [key for _, key in spy.calls] == ["d-7", "d-7"]

    async def test_two_decisions_about_identical_parameters_derive_different_keys(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """A fresh authorisation is a fresh action, not a duplicate of the old one."""
        spy = Spy()
        invoker.register(keyed(), spy)
        payload = {"to": "someone@example.com"}

        await invoked(
            invoker,
            trail,
            call_for(keyed(), parameters=payload, decision_id="d-1"),
            timeout=PATIENT,
        )
        await invoked(
            invoker,
            trail,
            call_for(keyed(), parameters=payload, decision_id="d-2"),
            timeout=PATIENT,
        )

        assert [key for _, key in spy.calls] == ["d-1", "d-2"]

    async def test_the_key_is_reproducible_from_the_decision_alone_after_a_restart(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The property that makes the key worth anything.

        A restarted executor reads ``StepExecution.approval_ref``, loads *that*
        decision from the durable trail, rebuilds the request, and derives the
        identical key. A key held only in memory would be lost by precisely the
        crash it exists to survive — so this reloads the decision through a JSON
        round-trip rather than reusing the object.
        """
        spy = Spy()
        invoker.register(gated(), spy)
        before = call_for(gated(), decision_id="d-99")
        await invoked(invoker, trail, before, timeout=PATIENT)

        reloaded = PermissionDecision.model_validate(before.decision.model_dump(mode="json"))
        after = ToolCall(request=before.request, decision=reloaded)
        await invoked(invoker, trail, after, timeout=PATIENT)

        assert after.idempotency_key == before.idempotency_key
        assert [key for _, key in spy.calls] == ["d-99", "d-99"]

    async def test_a_keyed_tool_deduplicates_inside_its_window_and_acts_again_outside_it(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The tool's half of ADR-0029 §5's two-sided obligation.

        The executor's half — stopping once the window has elapsed, and treating
        any reading that is not a positive elapsed duration as *lapsed* — is an
        obligation on `orchestration`'s executor and is not observable here.
        """
        window = timedelta(hours=1)
        deduplicating = KeyedTool(window)
        # The non-spendable ``KEYED`` class: a repeat under one decision is what
        # this case is about, and ADR-0192 §1 admits one only here.
        invoker.register(gated(window=window), deduplicating)
        call = call_for(gated(window=window), decision_id="d-5")

        first = await invoked(invoker, trail, call, timeout=PATIENT)
        inside = await invoked(invoker, trail, call, timeout=PATIENT)
        deduplicating.now = AT + window + timedelta(seconds=1)
        outside = await invoked(invoker, trail, call, timeout=PATIENT)

        assert first.output == inside.output == 1
        assert outside.output == 2
        assert deduplicating.effects == 2

    # --- success ---------------------------------------------------------

    async def test_a_successful_call_returns_its_output_and_the_tools_arguments(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The happy path, and that the callable receives what was authorised."""
        spy = Spy(output={"message_id": "m-1"})
        invoker.register(tool(), spy)

        result = await invoked(
            invoker,
            trail,
            call_for(tool(), parameters={"to": "someone@example.com"}),
            timeout=PATIENT,
        )

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.failure is None
        assert result.output == {"message_id": "m-1"}
        assert spy.calls == [({"to": "someone@example.com"}, None)]

    # --- ADR-0192 §1: the claim, and where it sits ------------------------

    async def test_a_call_claims_before_the_callable_and_completes_after(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The order ADR-0192 §1 places and §3 closes, asserted as a sequence.

        Held on a barrier the test owns, so "before" is observed rather than
        inferred from two rows that happen to be in that order: while the claim
        append is in flight the callable has **not** been entered and ``invoke``
        has not returned, and the completion exists only once the call has run.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await ledger.claim.entered.wait()

        assert spy.calls == [], "the claim is appended before the callable is entered"
        assert not task.done()
        assert await rows(trail) == []

        ledger.claim.hold.set()
        result = await task

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert spy.calls == [({"to": "someone@example.com"}, None)]
        (claim,) = await claims(trail)
        (completion,) = await completions(trail)
        assert claim.decision_id == call.decision.id
        assert completion.completes == claim.id
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    @pytest.mark.parametrize("refusal", ["unrecorded", "spent"])
    async def test_a_refused_claim_never_calls_the_registration(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], refusal: str
    ) -> None:
        """ "Before the callable is entered" is about **calling**, not only awaiting.

        A registration is not required to be a native ``async def``, so obtaining
        its coroutine in order to hold one across the claim already runs whatever
        it does synchronously. An implementation that does so passes every case
        driven by an ``async def`` double and then performs a side effect under an
        authorisation the ledger went on to refuse — as spent, or as one the trail
        never recorded — which is the single thing ADR-0192 §1 exists to prevent.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        factory = SynchronousFactory()
        invoker.register(tool(), factory)
        call = call_for(tool())

        if refusal == "spent":
            await trail.record(call.decision)
            await invoker.invoke(call, timeout=PATIENT)
            assert factory.entered == 1, "the first act reaches the registration"

        expected = AuthorisationSpentError if refusal == "spent" else UnrecordedAuthorisationError
        with pytest.raises(expected):
            await invoker.invoke(call, timeout=PATIENT)

        assert factory.entered == (1 if refusal == "spent" else 0), (
            "a refused claim calls the registration no further"
        )

    @pytest.mark.parametrize(
        "wiring",
        ["unbound-id", "substituted-definition", "unauthorised", "malformed-parameters"],
    )
    async def test_a_refused_check_appends_no_invocation_row(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], wiring: str
    ) -> None:
        """Every check that raises a seam fault sits **above** the claim (ADR-0192 §1).

        Parameterised rather than written for one check, because a suite
        inspecting only the exception and the untouched callable certifies an
        implementation that claims first and then refuses — which enters no
        callable, raises the expected class, and has nonetheless spent the
        authorisation and left an open claim for a call that was never made.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(tool(), spy)

        call = call_for(tool("never-registered") if wiring == "unbound-id" else tool())
        await trail.record(call.decision)
        if wiring == "substituted-definition":
            object.__setattr__(call.request.tool, "risk_level", RiskLevel.LOW)
        elif wiring == "unauthorised":
            call.__dict__["request"] = ActionRequest(
                tool=tool(), parameters={"to": "elsewhere@example.com"}, step_id="step-1"
            )
        elif wiring == "malformed-parameters":
            call.__dict__["request"] = ActionRequest.model_construct(
                tool=call.request.tool,
                parameters={"to": {"a", "set", "has", "no", "json"}},
                step_id="step-1",
            )

        with pytest.raises(ToolBindingError):
            await invoker.invoke(call, timeout=PATIENT)

        assert spy.calls == [], "the callable was never reached"
        assert await rows(trail) == [], "a seam fault appends no invocation row"

    async def test_an_unrecorded_authorisation_is_refused_before_the_callable(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The claim is the consume, and a claim the ledger refuses never reaches the tool.

        The refusal reaches the caller **as its own class**, unwrapped: ADR-0192
        §2's exhaustive refusal orders would mean nothing if a caller could not
        catch the class they name (§1).
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(tool(), spy)

        with pytest.raises(UnrecordedAuthorisationError):
            await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert spy.calls == []
        assert await rows(trail) == []

    async def test_a_second_act_under_a_spendable_authorisation_is_refused_at_the_seam(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """One authorisation, one act — and the refusal is what leaves ``invoke``.

        Asserted at the seam rather than on a ledger method driven directly: the
        refusal is ADR-0192 §1's and is decided inside the append, so a
        ledger-only test would pin the store's rule while leaving the seam free to
        swallow it.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        first = await invoker.invoke(call, timeout=PATIENT)
        with pytest.raises(AuthorisationSpentError):
            await invoker.invoke(call, timeout=PATIENT)

        assert first.outcome is ToolOutcome.SUCCEEDED
        assert len(spy.calls) == 1, "the second act never reached the callable"
        assert len(await rows(trail)) == 2, "one claim and one completion, and no more"

    @pytest.mark.parametrize("definition", [read_only("inbox"), natural("upsert")])
    async def test_a_second_act_under_a_non_spendable_authorisation_is_admitted(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        definition: ToolDefinition,
    ) -> None:
        """A read gated by ADR-0016 §3 is invoked under one ``ALLOW`` as often as needed.

        The half a one-winner test cannot see: an implementation consuming every
        ``ALLOW`` would refuse the second gated read and the second ``NATURAL``
        invocation, which ADR-0192 §1 says are never refused on this ground.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        spy = Spy()
        invoker.register(definition, spy)
        call = call_for(definition)
        await trail.record(call.decision)

        await invoker.invoke(call, timeout=PATIENT)
        await invoker.invoke(call, timeout=PATIENT)

        assert len(spy.calls) == 2
        assert len(await completions(trail)) == 2
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_completion_that_did_not_commit_leaves_the_claim_open_and_spends_it(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """Completion durability is a third prerequisite for a further act (ADR-0192 §1).

        The composition a suite holding the two halves separately cannot see: the
        completion append fails before committing, ``invoke`` returns the call's
        own result unchanged, and the next act under that authorisation is refused
        **twice over** — a claim is open, and the last claim in the append order is
        that same open one and so is not completed ``FAILED`` at all.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = RuntimeError("the store would not write")
        invoker = consuming(ledger)
        spy = Spy(output={"message_id": "m-1"})
        invoker.register(keyed(), spy)
        call = call_for(keyed())
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED, "the act's own result stands"
        assert result.output == {"message_id": "m-1"}
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1
        assert await completions(trail) == []

        with pytest.raises(AuthorisationSpentError):
            await invoker.invoke(call, timeout=PATIENT)

        assert len(spy.calls) == 1, "no second callable was entered"
        assert len(await rows(trail)) == 1, "one claim, still open, and no completion"

    # --- ADR-0192 §2, §5: what the completion row carries ------------------

    async def test_a_success_completes_with_no_kind_and_a_cost_nobody_measured(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The declaration's price appears on no row, on this path or any other.

        ``ToolResult.incurred_cost`` is what the *tool* reported, and this tool
        reported nothing, so the row records an ``UNKNOWN`` basis — beside a
        declaration that carries a real ``PER_CALL`` figure, which is the whole
        point of the case. A lane filling the field from ``ToolDefinition.cost``
        would put a declaration where a measurement belongs and corrupt the spend
        total ADR-0192 §5 is built on, and ADR-0195's channel changes nothing
        about that: the figure comes from the tool or the row says ``UNKNOWN``.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        priced = tool(
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.01"), currency="USD")
        )
        invoker.register(priced, Spy())
        call = call_for(priced)
        await trail.record(call.decision)

        await invoker.invoke(call, timeout=PATIENT)

        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert completion.failure_kind is None, (
            "a SUCCEEDED result carries no failure to transcribe"
        )
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    @pytest.mark.parametrize(
        ("definition", "expected"),
        [(read_only("inbox"), ToolOutcome.FAILED), (keyed(), ToolOutcome.INDETERMINATE)],
    )
    async def test_a_deadline_transcribes_its_kind_onto_the_completion(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        definition: ToolDefinition,
        expected: ToolOutcome,
    ) -> None:
        """``TIMED_OUT`` is transcribed and never dropped, on both outcomes.

        A ``FAILED``-with-kind case is owed separately from the
        ``INDETERMINATE``-with-kind one: an implementation can preserve one and
        drop the other, and dropping either produces a valid kindless completion
        that silently refuses a legitimate retry as spent (ADR-0192 §9).
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(definition, Slow())
        call = call_for(definition)
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=BRIEF)

        assert result.outcome is expected
        (completion,) = await completions(trail)
        assert completion.outcome is expected
        assert completion.failure_kind is ToolFailureKind.TIMED_OUT
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    @pytest.mark.parametrize(
        ("definition", "expected"),
        [(read_only("inbox"), ToolOutcome.FAILED), (tool(), ToolOutcome.INDETERMINATE)],
    )
    async def test_a_cancelled_call_completes_kindless_at_an_unknown_cost(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        definition: ToolDefinition,
        expected: ToolOutcome,
    ) -> None:
        """A completion derived from no ``ToolResult`` invents neither field.

        ``failure_kind`` is transcribed and never synthesised — ADR-0031 §3 rules
        that the seam never synthesises ``CANCELLED`` — and the cost is the
        ``UNKNOWN`` basis, never the declaration's figure. Without this a spend
        accumulator counts an invented measurement.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        slow = Slow()
        invoker.register(definition, slow)
        call = call_for(definition)
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await slow.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        (completion,) = await completions(trail)
        assert completion.outcome is expected
        assert completion.failure_kind is None
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    # --- ADR-0192 §3: a failed append changes nothing about the act --------

    async def test_a_completion_that_fails_does_not_change_what_the_call_returned(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A ``SUCCEEDED`` side effect is not reported as failed because a disk was full.

        The failure is not swallowed either: it reaches the operator as a Tier 2
        diagnostic carrying the operation, the fault class and the outcome that
        was being written — and **nothing else**, the instance, the message and
        every member of the cause chain included (ADR-0192 §3, ADR-0004 §5).
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = RuntimeError("recipient@example.com")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 3}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == {"unread": 3}
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": "RuntimeError",
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_the_diagnostics_four_shapes_carry_exactly_their_own_fields(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """ADR-0192 §3's matrix, shape by shape, with absent fields asserted absent.

        A shape-by-shape test is owed because every drift this rule has had was a
        clause restating the field list for one case and disagreeing with another.
        The claim shapes carry **no** outcome — a claim carries no ``ToolOutcome``
        at all, so nothing stands in for it and no literal is minted for the
        position — and the ``BaseException`` shapes carry **no class**, which is
        ``fault_class_of``'s own rule read forward rather than worked around.
        """
        shapes: list[tuple[str, BaseException, dict[str, object]]] = [
            ("claim", RuntimeError("boom"), {"operation": CLAIM, "fault_class": "RuntimeError"}),
            ("claim", KeyboardInterrupt(), {"operation": CLAIM}),
            (
                "completion",
                RuntimeError("boom"),
                {
                    "operation": COMPLETION,
                    "fault_class": "RuntimeError",
                    "outcome": ToolOutcome.SUCCEEDED,
                },
            ),
            (
                "completion",
                KeyboardInterrupt(),
                {"operation": COMPLETION, "outcome": ToolOutcome.SUCCEEDED},
            ),
        ]
        for member, error, expected in shapes:
            trail = FakeAuditTrail()
            ledger = DrivenLedger(trail)
            getattr(ledger, member).error = error
            invoker = consuming(ledger)
            invoker.register(read_only("inbox"), Spy())
            call = call_for(read_only("inbox"))
            await trail.record(call.decision)

            # The exit itself is the other cases' subject; this one is about the
            # fields the diagnostic carries on the way out.
            with structlog.testing.capture_logs() as captured, contextlib.suppress(BaseException):
                await invoker.invoke(call, timeout=PATIENT)

            assert appended(captured) == [expected], f"{member} raising {type(error).__name__}"

    async def test_no_tier_one_content_reaches_the_diagnostic_by_any_route(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The sentinel in four hostile positions (ADR-0192 §9, ADR-0004 §5).

        A message, a member of the cause chain, an identifier, and the **class
        name** of a dynamically built exception. On the first three the assertion
        is that no such name reaches the log at all; on the fourth it is
        ``fault_class_of``'s own boundary and nothing wider — a name outside that
        function's identifier pattern becomes the reserved literal, and the
        residue for a *pattern-valid* hostile name is ADR-0119's, filed as #1569.
        """
        sentinel = "recipient@example.com"
        hostile = type(sentinel, (RuntimeError,), {})
        error = hostile("the message names " + sentinel)
        error.__cause__ = ValueError("the cause names " + sentinel)

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = error
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy())
        call = call_for(read_only("inbox"), decision_id=sentinel)
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            await invoker.invoke(call, timeout=PATIENT)

        (diagnostic,) = appended(captured)
        assert diagnostic == {
            "operation": COMPLETION,
            "fault_class": UNREPRESENTABLE_FAULT_CLASS,
            "outcome": ToolOutcome.SUCCEEDED,
        }
        assert sentinel not in repr(captured), "no route carries a Tier 1 name into the log"

    async def test_a_class_name_that_cannot_be_read_becomes_the_reserved_literal(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """``fault_class_of``'s totality is what ADR-0192 §3 relies on, so it is pinned.

        The suite already covers a name outside the identifier pattern; this is
        the other arm — an exception whose ``__name__`` **access** raises an
        ``Exception``. It yields the same reserved literal, and it neither takes
        the diagnostic down nor changes what ``invoke`` returns. An implementation
        that validated ordinary names but let that access failure escape would
        replace a successful call's result with a bookkeeping failure, which is
        the one outcome §3 calls worse than an incomplete record.

        **No case asserts a literal where the ``__name__`` read raises a
        ``BaseException`` that is not an ``Exception``**, and none may:
        ``fault_class_of`` lets that one propagate by design, so a test demanding
        the literal would demand the widening ADR-0119 refuses (ADR-0192 §9).
        """
        unnameable = NameRaises("Unnameable", (RuntimeError,), {})
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = unnameable("the store would not write")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 7}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.output == {"unread": 7}, "the diagnostic never changes what invoke returns"
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": UNREPRESENTABLE_FAULT_CLASS,
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]

    async def test_a_collaborators_cancellation_on_the_completion_path_is_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A cancellation with nothing cancelled is not a cancellation of this call.

        Propagating it would discard a ``ToolResult`` the tool had already
        produced and hand the executor a ``CancelledError`` for a call nothing
        cancelled — a known-successful side effect recorded as interrupted, the
        one outcome ADR-0192 §3 calls worse than an incomplete record. The two
        cases are told apart by the ``Task.cancelling()`` count and by nothing
        else, so the diagnostic carries no class.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = asyncio.CancelledError("the ledger invented one")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 1}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.output == {"unread": 1}
        assert appended(captured) == [{"operation": COMPLETION, "outcome": ToolOutcome.SUCCEEDED}]
        assert ledger.completion.calls == 1, "no exit attempts a second completion for one claim"
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_a_collaborators_cancellation_on_the_claim_path_is_an_audit_error(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The mirror case at the seam, and it must **not** leave as a ``CancelledError``.

        No callable was entered and no claim was observed, so this is a
        pre-callable exit: ADR-0034 §1's second ground classifies the step
        ``FAILED`` and no retry follows. Leaving as a cancellation would have the
        executor record ``interrupted_outcome`` — ``INDETERMINATE`` for a
        side-effecting tool — for a call that provably did not run.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        invented = asyncio.CancelledError("the ledger invented one")
        ledger.claim.error = invented
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(AuditError) as caught:
            await invoker.invoke(call, timeout=PATIENT)

        assert not isinstance(caught.value, asyncio.CancelledError)
        assert caught.value.__cause__ is invented
        assert spy.calls == []
        assert await rows(trail) == []

    async def test_a_collaborators_cancellation_on_the_claim_path_propagates_when_one_is_pending(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The other side of the discriminator, on the path the mirror case owns.

        Told apart by the ``Task.cancelling()`` **count** and by nothing else —
        never by the exception's class, never by its identity, and never by where
        in the body it surfaced (ADR-0192 §1, §3). With the count **increased** a
        cancellation request really did reach this task, so the ``CancelledError``
        is what leaves and ADR-0029 §4's classification of a genuinely cancelled
        call is untouched. An implementation that always translated a claim-side
        collaborator cancellation to ``AuditError`` would pass the unmoved-count
        case beside this one and lose a real concurrent shutdown.

        The executor's half of this pair — that it commits ``interrupted_outcome``
        here and ``FAILED`` on the unmoved-count case — is `orchestration`'s and
        is owed by the group that owns the executor (ADR-0192 §9).
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invented = asyncio.CancelledError("the ledger invented one")
        ledger.claim.error = invented
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.claim.entered.wait()
            task.cancel()
            await _settled()
            ledger.claim.hold.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task

        assert not isinstance(caught.value, AuditError)
        assert caught.value.__cause__ is invented
        assert task.cancelled()
        assert spy.calls == [], "the callable is never entered"
        assert ledger.completion.calls == 0
        assert appended(captured) == [{"operation": CLAIM}], "a cancellation is not a fault class"

    @pytest.mark.parametrize("member", ["claim", "completion"])
    async def test_a_class_name_read_that_raises_a_base_exception_is_not_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], member: str
    ) -> None:
        """``fault_class_of``'s guard stops at ``Exception``, and §3 does not widen it.

        A metaclass whose ``__name__`` access raises a ``BaseException`` that is not
        an ``Exception`` leaves the classifier by design, and ADR-0192 §3 gives it
        no exemption: it "is governed by this section's own clauses on a
        ``BaseException`` raised there … everything else propagating unchanged with
        **no diagnostic standing in for it**". So it is **not** swallowed behind the
        append's own failure — the call does not return a ``ToolResult``, and the
        claim path does not answer with the ``AuditError`` it would give an
        ordinary ``Exception``.

        **And no diagnostic is written at all.** §3 says of that exception that "it
        leaves the emitting frame", which is false of an implementation that
        catches it inside the emitter, omits the class field and writes the record
        anyway — and that record is exactly the one standing in for the exception
        §3 forbids. An earlier draft of this suite asserted the omitted-field
        shape here; it was asserting the construct the clause rules out. The
        omitted-field shape is still right where the *append's own* failure is a
        ``BaseException`` no class can be read from — that case is next — and the
        two are told apart by which exception the classifier was asked about.

        The class that leaves is not asserted: on the completion path this runs
        inside a retained append, which is the one thing §3 declines to state.
        """

        # A single instance, so the case can assert **identity** rather than class:
        # ADR-0192 §3 requires this exception to propagate *unchanged*, and an
        # implementation that annotates it on the way — attaching the append's
        # failure as its context, say — hands the caller whatever a hostile
        # ``__setattr__`` raises instead of the exception itself.
        interrupt = KeyboardInterrupt("the metaclass refuses to be named")

        class Unnameable(type):
            """Refuses to be named, with a ``BaseException`` the guard lets pass."""

            def __getattribute__(cls, name: str) -> object:
                if name == "__name__":
                    raise interrupt
                return super().__getattribute__(name)

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        getattr(ledger, member).error = Unnameable("Hostile", (RuntimeError,), {})("boom")
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 1}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        returned: ToolResult | None = None
        raised: BaseException | None = None
        with structlog.testing.capture_logs() as captured:
            try:
                returned = await invoker.invoke(call, timeout=PATIENT)
            except BaseException as exc:
                raised = exc

        assert raised is interrupt, (
            "the classifier's own failure propagates unchanged — neither absorbed, "
            "nor translated, nor replaced by the failure of annotating it"
        )
        assert returned is None
        assert appended(captured) == [], (
            "the exception leaves the emitting frame, so no diagnostic stands in for it"
        )

    @pytest.mark.parametrize("thrown", ["exception", "cancellation"])
    async def test_a_raising_log_processor_costs_the_diagnostic_and_nothing_else(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], thrown: str
    ) -> None:
        """A broken *emitter* is not the classifier ADR-0192 §3 governs.

        §3's subject throughout is what may be **read off an exception and
        rendered** — the fault class, the field omitted where none can be read,
        the ``BaseException`` the name read raises and the clauses that dispose of
        it. It says nothing at all about the pipeline the rendered fields are then
        handed to, and ADR-0004 §5 and ADR-0119 likewise govern what a diagnostic
        may *carry* rather than what happens when the sink behind it is
        misconfigured. So the guard this case requires around the **emission** is
        not the guard §3 puts on the **classify**; the two are separable because
        they are about different things.

        **What an unguarded emitter costs.** Since the classifier's own failure is
        routed to the append path for disposition (§3), an exception the *emitter*
        raises would be routed there too — and would then stand in for the append
        failure it was being emitted about. On the claim path the caller is told
        the claim failed because a log sink did: an ``AuditError`` whose cause is
        the sink's exception, with the ledger's own failure nowhere in the chain.
        On the completion path it is absorbed in that failure's place, so a
        propagating cancellation carries the sink's exception as its cause instead
        of the append's. Neither is a fault of the *call*, and reporting a
        completed act as failed because a disk was full is precisely what §3 calls
        worse than an incomplete record — the fail-open ADR-0034 §1 exists to
        prevent.

        So an ``Exception`` from the pipeline costs the **diagnostic** and nothing
        else: the append's own failure stays intact for the path to dispose of by
        its own rules, and a successful ``ToolResult`` still reaches the caller.
        A ``CancelledError`` from it is the same, and the second arm drives that:
        every emission here happens after the ``Task.cancelling()`` count has been
        read, and none of them awaits, so one a processor raises is invented with
        nothing cancelled — ADR-0031 §2's case, which ADR-0029 §4 makes a fault.
        Delivering it would answer a completed act with a cancellation nobody
        requested.

        The processor is configured rather than the module logger patched, because
        a shared suite has two subjects in two modules and only the pipeline is
        common to both. ``capture_logs`` cannot serve here at all — it *replaces*
        the chain, which is the thing under test.
        """

        class BrokenSinkError(Exception):
            """What a misconfigured processor raises on the way to its sink."""

        def refuse(_logger: object, _name: str, _event: MutableMapping[str, Any]) -> NoReturn:
            if thrown == "cancellation":
                # Invented, with nothing cancelled: both seams read the
                # `Task.cancelling()` count before emitting and the emission is
                # synchronous, so ADR-0031 §2 governs and ADR-0029 §4 makes it a
                # fault rather than a cancellation of this call.
                raise asyncio.CancelledError
            msg = "the log pipeline is broken"
            raise BrokenSinkError(msg)

        async def under_a_broken_sink(
            member: str, error: Exception
        ) -> tuple[FakeAuditTrail, ToolResult | None, BaseException | None]:
            trail = FakeAuditTrail()
            ledger = DrivenLedger(trail)
            getattr(ledger, member).error = error
            invoker = consuming(ledger)
            invoker.register(read_only("inbox"), Spy(output={"unread": 3}))
            call = call_for(read_only("inbox"))
            await trail.record(call.decision)

            configured = structlog.get_config()
            structlog.configure(processors=[refuse])
            try:
                return trail, await invoker.invoke(call, timeout=PATIENT), None
            except BaseException as exc:  # the case below decides what it means
                return trail, None, exc
            finally:
                structlog.configure(**configured)

        # The claim path reports a fault, and the fault it reports is the ledger's.
        refused = RuntimeError("the store would not write the claim")
        _, returned, raised = await under_a_broken_sink("claim", refused)
        assert returned is None
        assert isinstance(raised, AuditError)
        assert raised.__cause__ is refused, (
            "the diagnostic's own failure never stands in for the append failure "
            "the operator is being told about"
        )

        # The completion path returns the result the tool already produced.
        trail, returned, raised = await under_a_broken_sink(
            "completion", RuntimeError("the store would not write the completion")
        )
        assert raised is None
        assert returned is not None
        assert returned.outcome is ToolOutcome.SUCCEEDED
        assert returned.output == {"unread": 3}, "a broken log sink does not fail a completed act"
        open_after = await trail.open_invocations(
            decision_id=call_for(read_only("inbox")).decision.id
        )
        assert len(open_after) == 1, "the completion was refused, so the claim is left open"

        # And the same holds of the *tool-failure* diagnostic, which runs after
        # the claim: a broken sink there would leave this frame in place of the
        # `ToolResult`, so §3 would get no completion for a claim already
        # appended — a known-failed act permanently spending its authorisation,
        # with the tool's failure lost as data (ADR-0029 §3).
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(read_only("inbox"), Raiser(RuntimeError("upstream said no")))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        configured = structlog.get_config()
        structlog.configure(processors=[refuse])
        try:
            failed = await invoker.invoke(call, timeout=PATIENT)
        finally:
            structlog.configure(**configured)

        assert failed.outcome is ToolOutcome.FAILED
        assert failed.failure is not None
        assert failed.failure.kind is ToolFailureKind.INTERNAL
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the completion is written, so the claim does not stay open"
        )

    @pytest.mark.parametrize("refusal", ["setattr-raises", "setattr-drops", "own-cause-descriptor"])
    async def test_a_cancellation_that_will_not_hold_the_cause_still_carries_it(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], refusal: str
    ) -> None:
        """Attaching the cause must not enter the collaborator's code.

        When the completion append fails while a cancellation is propagating,
        ADR-0192 §3 has **that** cancellation leave carrying the failure as its
        cause, and ``ToolInvoker.invoke``'s contract has this method "re-raise
        what it was already raising". So the exception the tool raised is what
        the caller receives — same object, same type, same arguments — with the
        append's failure attached to it.

        Attaching it is where the difficulty is, because the object need not be a
        built-in ``CancelledError`` at all: an externally cancelled tool may catch
        the injected cancellation and raise its own subclass, and then
        ``cancellation.__cause__ = failure`` runs *that tool's* code. Three
        refusals are driven, and the quiet ones are the dangerous ones:

        * a ``__setattr__`` that **raises** — an assignment would leave this frame
          with neither the cancellation ADR-0060 §1 requires nor the failure §3
          requires it to carry;
        * a ``__setattr__`` that **accepts and stores nothing** — an assignment
          would look correct with the failure silently gone, so falling back only
          where the assignment *raises* is not enough;
        * a ``__cause__`` **descriptor of the subclass's own**, whose setter drops
          the value and whose getter answers ``None`` — which no ``__setattr__``
          fallback reaches at all.

        None of them is entered: the seam writes through ``BaseException``'s own
        ``__cause__`` descriptor, into a slot no subclass can shadow. The last arm
        is why :func:`cause_of` reads that slot rather than the attribute — a
        hostile *getter* can still misreport what the object holds, which is a
        collaborator lying about its own exception and not something this seam can
        cure. What §3 puts a rule on is that the failure is attached.
        """

        class RaisesOnSet(asyncio.CancelledError):
            """Refuses the annotation by raising."""

            def __setattr__(self, name: str, value: object) -> None:
                msg = "this exception refuses to be annotated"
                raise RuntimeError(msg)

        class DropsOnSet(asyncio.CancelledError):
            """Accepts the annotation and stores nothing."""

            def __setattr__(self, name: str, value: object) -> None:
                return

        class OwnCauseDescriptor(asyncio.CancelledError):
            """Declares ``__cause__`` itself, dropping writes and answering ``None``."""

            @property
            def __cause__(self) -> BaseException | None:
                return None

            @__cause__.setter
            def __cause__(self, value: BaseException | None) -> None:
                return

        rejecting: type[asyncio.CancelledError] = {
            "setattr-raises": RaisesOnSet,
            "setattr-drops": DropsOnSet,
            "own-cause-descriptor": OwnCauseDescriptor,
        }[refusal]

        class Substituting:
            """Catches the injected cancellation and raises its own instead."""

            def __init__(self) -> None:
                self.entered = asyncio.Event()
                self.raised: asyncio.CancelledError | None = None

            async def __call__(
                self,
                parameters: Mapping[str, FrozenJson],
                *,
                idempotency_key: str | None,
            ) -> FrozenJson:
                self.entered.set()
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    self.raised = rejecting()
                    raise self.raised from None
                return None

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        refused = RuntimeError("the store would not write the completion")
        ledger.completion.error = refused
        invoker = consuming(ledger)
        tool_under_test = Substituting()
        invoker.register(read_only("inbox"), tool_under_test)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        running = asyncio.ensure_future(invoker.invoke(call, timeout=PATIENT))
        await tool_under_test.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await running

        assert tool_under_test.raised is not None
        assert caught.value is tool_under_test.raised, (
            "the cancellation the tool raised is what leaves — a completion that "
            "failed does not cost the caller its type, its arguments or its identity"
        )
        assert cause_of(caught.value) is refused, (
            "the append's own failure travels with the cancellation, and no "
            "refusal to be annotated keeps it off"
        )

    async def test_a_cause_whose_finaliser_would_reclaim_the_slot_never_runs(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
    ) -> None:
        """The write enters no collaborator code, and it releases none either.

        Writing through ``BaseException``'s descriptor runs nothing the object
        declares. It can still *free* something: the slot holds a reference, and
        ``PyException_SetCause`` stores the new value before dropping the old one,
        so a cause the tool put there first — whose last reference the slot was —
        would be finalised **after** the seam's value had landed. A ``__del__``
        writing that slot again from there would leave the caller holding the
        tool's value where the ledger's failure belongs, silently, because the
        write did exactly what it was asked.

        Substituting a cancellation the seam owns is not open to it: ADR-0192 §3
        has ``invoke`` re-raise the exception it was already raising *exactly as it
        would have*. So the trigger is removed instead of the damage repaired — the
        frame that raises retains the displaced cause, which the traceback then
        keeps alive for as long as the caller holds the exception, and the
        finaliser does not run at all.

        That last fact is what this case asserts directly: a seam that dropped the
        reference would leave ``fired`` non-empty here, and would hand back a
        cancellation carrying ``replacement``.
        """
        fired: list[object] = []
        replacement = RuntimeError("the value the finaliser would put back")

        class ReclaimingCauseError(Exception):
            """A cause whose finaliser writes the slot it was displaced from."""

            def __init__(self, target: BaseException) -> None:
                super().__init__("the cause the tool put there first")
                self.target = target

            def __del__(self) -> None:
                fired.append(self)
                CAUSE_SLOT.__set__(self.target, replacement)

        class Reclaiming:
            """Raises a cancellation whose existing cause would take its slot back."""

            def __init__(self) -> None:
                self.entered = asyncio.Event()
                self.raised: asyncio.CancelledError | None = None

            async def __call__(
                self,
                parameters: Mapping[str, FrozenJson],
                *,
                idempotency_key: str | None,
            ) -> FrozenJson:
                self.entered.set()
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    self.raised = asyncio.CancelledError("raised by the tool")
                    # The slot is the only reference it has, so displacing it is
                    # what would finalise it — the whole of the hazard.
                    CAUSE_SLOT.__set__(self.raised, ReclaimingCauseError(self.raised))
                    # Not `from None`: that writes the slot again and finalises
                    # the cause this case exists to displace.
                    raise self.raised  # noqa: B904
                return None

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        refused = RuntimeError("the store would not write the completion")
        ledger.completion.error = refused
        invoker = consuming(ledger)
        tool_under_test = Reclaiming()
        invoker.register(read_only("inbox"), tool_under_test)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        running = asyncio.ensure_future(invoker.invoke(call, timeout=PATIENT))
        await tool_under_test.entered.wait()
        running.cancel()

        with pytest.raises(asyncio.CancelledError) as caught:
            await running

        assert fired == [], (
            "the seam's write displaced the cause but did not release it, so the "
            "collaborator's finaliser never ran"
        )
        assert caught.value is tool_under_test.raised, (
            "the cancellation the tool raised is what leaves, exactly as it would "
            "have without a completion failure"
        )
        assert cause_of(caught.value) is refused, (
            "and it carries the append's own failure, not the value the finaliser "
            "was waiting to put back"
        )
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1, (
            "the completion was refused, so the claim is left open as on every "
            "other completion failure"
        )

    async def test_a_log_processor_that_cancels_this_task_is_not_answered_with_a_result(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The count is sampled around the append; the emission sits after that sample.

        A diagnostic's processor is arbitrary code, and it can cancel the invoking
        task and then raise. Swallowing the raise is right — an emitter's failure
        stands in for nothing — but the *request* it left behind is real: the
        loop will deliver it, and ADR-0192 §1's branch turns on the
        ``Task.cancelling()`` count whoever moved it. A seam still holding the
        sample it took before the emission answers a cancelled call with an
        ordinary ``AuditError`` and leaves a request nobody honoured, which is the
        swallowing ADR-0060 §1 says a method never does.

        So the count is re-read after the emission, and the call leaves as a
        cancellation carrying the append's own failure as its cause.
        """

        def cancel_then_raise(
            _logger: object, _name: str, _event: MutableMapping[str, Any]
        ) -> NoReturn:
            running = asyncio.current_task()
            assert running is not None
            running.cancel()
            raise asyncio.CancelledError

        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        refused = RuntimeError("the store would not write the claim")
        ledger.claim.error = refused
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy())
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        configured = structlog.get_config()
        structlog.configure(processors=[cancel_then_raise])
        try:
            with pytest.raises(asyncio.CancelledError) as caught:
                await invoker.invoke(call, timeout=PATIENT)
        finally:
            structlog.configure(**configured)
            asyncio.current_task().uncancel()  # type: ignore[union-attr]  # inside a running task

        assert caught.value.__cause__ is refused, (
            "the cancellation carries the append's own failure, not the emitter's"
        )

    @pytest.mark.parametrize("member", ["claim", "completion"])
    async def test_a_ledger_that_raises_before_returning_a_coroutine_is_disposed_of_normally(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], member: str
    ) -> None:
        """Nothing makes a conforming ledger method a native ``async def``.

        ``InvocationLedger`` declares ``async def``, but a plain function
        returning a coroutine satisfies the Protocol structurally — and such a
        function can raise **before** it returns anything to await. A seam that
        calls it in its own frame and only then hands the coroutine to the
        shielded task misses that raise entirely: it never becomes the captured
        value the disposition rules read, so on the claim path it reaches the
        caller untranslated instead of as the ``AuditError`` ADR-0192 §1 requires,
        and on the completion path it replaces a ``ToolResult`` the tool had
        already produced and leaves the claim open, which §3 calls worse than an
        incomplete record.

        The failure is identical in kind to one the coroutine raises, so the two
        must be answered identically — and this case is the one that says so.
        """

        class Eager:
            """A structurally conforming ledger that fails before it is awaited."""

            def __init__(self, inner: FakeAuditTrail) -> None:
                self.inner = inner

            def claim_invocation(self, *, decision: PermissionDecision) -> Any:
                if member == "claim":
                    msg = "the ledger failed before it returned a coroutine"
                    raise RuntimeError(msg)
                return self.inner.claim_invocation(decision=decision)

            def complete_invocation(self, **kwargs: Any) -> Any:
                if member == "completion":
                    msg = "the ledger failed before it returned a coroutine"
                    raise RuntimeError(msg)
                return self.inner.complete_invocation(**kwargs)

        trail = FakeAuditTrail()
        invoker = consuming(Eager(trail))
        invoker.register(read_only("inbox"), Spy(output={"unread": 5}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        if member == "claim":
            with pytest.raises(AuditError) as caught:
                await invoker.invoke(call, timeout=PATIENT)
            assert isinstance(caught.value.__cause__, RuntimeError)
        else:
            result = await invoker.invoke(call, timeout=PATIENT)
            assert result.output == {"unread": 5}, "a completion failure never changes the result"

    @pytest.mark.parametrize("member", ["claim", "completion"])
    async def test_a_non_assistant_error_reaches_the_caller_as_an_audit_error_or_is_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry], member: str
    ) -> None:
        """The two boundaries answer differently, and an earlier draft ran them together.

        On the **claim** path an exception that is not an ``AssistantError`` is
        translated to an ``AuditError`` carrying it as the cause, its type intact
        — parameterised over three classes, so an implementation that catches one
        name rather than the class boundary fails. On the **completion** path none
        leaves at all, because it is absorbed (ADR-0192 §1, §3).
        """

        class BespokeError(Exception):
            """An exception class this test defines, so no name is being caught."""

        for raised in (RuntimeError("a"), ValueError("b"), BespokeError("c")):
            trail = FakeAuditTrail()
            ledger = DrivenLedger(trail)
            getattr(ledger, member).error = raised
            invoker = consuming(ledger)
            invoker.register(read_only("inbox"), Spy())
            call = call_for(read_only("inbox"))
            await trail.record(call.decision)

            if member == "claim":
                with pytest.raises(AuditError) as caught:
                    await invoker.invoke(call, timeout=PATIENT)
                assert caught.value.__cause__ is raised
            else:
                result = await invoker.invoke(call, timeout=PATIENT)
                assert result.outcome is ToolOutcome.SUCCEEDED

    async def test_a_base_exception_on_the_completion_path_is_not_absorbed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A process being torn down is not a refusal (ADR-0192 §3).

        No ``ToolResult`` reaches the caller, no completion is written, the claim
        is left open and the diagnostic carries **no class**. The test asserts
        those and stops there, asserting **nothing** about the class ``invoke``
        raises outward: that clock runs inside a retained append, and ADR-0192 §3
        leaves exactly that one thing uncontracted, so a case asserting it would
        pin behaviour the ADR declines to state.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = KeyboardInterrupt()
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 1}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        returned: ToolResult | None = None
        raised: BaseException | None = None
        with structlog.testing.capture_logs() as captured:
            try:
                returned = await invoker.invoke(call, timeout=PATIENT)
            except BaseException as exc:
                # Captured rather than named: ADR-0192 §3 leaves the outward class
                # of a `BaseException` raised inside a retained append
                # uncontracted, so nothing here asserts one. That it *left* is a
                # different claim and is asserted — absorbing a `KeyboardInterrupt`
                # into a returned `None` would pass a suppression alone.
                raised = exc

        assert raised is not None, "a torn-down process is not absorbed"
        assert returned is None, "no result is manufactured for one"
        assert appended(captured) == [{"operation": COMPLETION, "outcome": ToolOutcome.SUCCEEDED}]
        assert await completions(trail) == []
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_a_base_exception_from_the_callable_propagates_unchanged(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The path that **is** contracted, and it answers differently (ADR-0192 §3).

        The callable is awaited **directly** and is not isolated in a task, so its
        own ``KeyboardInterrupt`` propagates unchanged, asserted by class. A suite
        omitting this would admit an implementation that had isolated the callable
        too — the shape ADR-0031 §4 refused outright.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(tool(), Raiser(KeyboardInterrupt()))
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(KeyboardInterrupt):
            await invoker.invoke(call, timeout=PATIENT)

        assert await completions(trail) == [], "no outcome is invented for one"
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    # --- ADR-0192 §1, §3: what the store already committed, stands ---------

    async def test_a_claim_that_committed_and_then_raised_leaves_its_row_standing(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """No rollback is on offer, and none is faked (ADR-0192 §1, §6).

        The row is durable before the failure reaches the frame. ``invoke``
        observed no claim, so it enters no callable and attempts no completion —
        and the committed row **stands**: nothing deleted, no compensating append,
        no marker. Without this case a suite certifies an implementation that
        cleans up after itself.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.error = RuntimeError("the connection dropped after the commit")
        ledger.claim.commits = True
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(AuditError):
            await invoker.invoke(call, timeout=PATIENT)

        assert spy.calls == [], "the callable is never entered"
        assert ledger.completion.calls == 0, "no completion is attempted for a claim never observed"
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_a_completion_that_committed_and_then_raised_leaves_the_claim_closed(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The other side of the commit-state split, on the same clause.

        A suite carrying only the failed-before-commit timing certifies an
        implementation that tries to repair this one. What ``invoke`` returns is
        decided independently of which side of the commit the failure landed on,
        and the test asserts that too.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = RuntimeError("the connection dropped after the commit")
        ledger.completion.commits = True
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 2}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        result = await invoker.invoke(call, timeout=PATIENT)

        assert result.output == {"unread": 2}, "the outward answer is decided independently"
        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.SUCCEEDED
        assert await trail.open_invocations(decision_id=call.decision.id) == []
        assert ledger.completion.calls == 1, "no compensating append and no second completion"

    @pytest.mark.parametrize("timing", ["before-the-commit", "after-the-commit"])
    @pytest.mark.parametrize(
        "branch",
        [
            "absorbed-exception",
            "invented-cancellation",
            "torn-down",
            "external-cancellation",
            "external-cancellation-meeting-an-invented-one",
        ],
    )
    async def test_the_commit_state_split_holds_on_every_completion_failure_branch(
        self,
        consuming: Callable[[InvocationLedger], InvocableToolRegistry],
        branch: str,
        timing: str,
    ) -> None:
        """What the store already committed, stands — on **every** failure branch.

        An implementation may honour the commit-state rule on one path and repair
        the others, so each branch is driven with the append failing **before** it
        commits, where the claim is left open, and again with the row durable
        before the failure reaches the frame, where the completion stands and the
        claim it names is closed. Nothing is deleted, rewritten or compensated to
        make the two look alike: ADR-0192 §6 offers no selective delete, and
        ADR-0060 §1 already rules that an abandoned append may have committed.

        **What ``invoke`` returns or raises is decided independently of which side
        of the commit the failure landed on**, and the test asserts that too —
        which is exactly what a repairing implementation gets wrong.
        """
        errors: dict[str, BaseException] = {
            "absorbed-exception": RuntimeError("the store would not write"),
            "invented-cancellation": asyncio.CancelledError("the ledger invented one"),
            "torn-down": KeyboardInterrupt(),
            "external-cancellation": RuntimeError("the store would not write"),
            # The discriminator's other side: a collaborator's `CancelledError`
            # while an external one **is** propagating is not absorbed. An
            # implementation that always absorbs a completion-path cancellation
            # would lose a real concurrent shutdown (ADR-0192 §3, ADR-0060 §1).
            "external-cancellation-meeting-an-invented-one": asyncio.CancelledError(
                "the ledger invented one"
            ),
        }
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.error = errors[branch]
        ledger.completion.commits = timing == "after-the-commit"
        invoker = consuming(ledger)
        cancelled = branch.startswith("external-cancellation")
        implementation = Slow() if cancelled else Spy(output={"unread": 1})
        invoker.register(read_only("inbox"), implementation)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        returned: ToolResult | None = None
        raised: BaseException | None = None
        try:
            if cancelled:
                # A task only where one is needed: a `BaseException` propagating
                # out of a task is re-raised into the event loop (ADR-0031 §4), so
                # the torn-down branch is awaited in this frame instead.
                task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
                await implementation.entered.wait()  # type: ignore[union-attr]  # `Slow` here
                task.cancel()
                returned = await task
            else:
                returned = await invoker.invoke(call, timeout=PATIENT)
        except BaseException as exc:
            # Every class: which one leaves is the branch's own subject, asserted
            # below rather than narrowed by the `raises` that catches it.
            raised = exc

        if branch in {"absorbed-exception", "invented-cancellation"}:
            assert returned is not None
            assert returned.output == {"unread": 1}, "the act's own result stands"
        elif branch == "torn-down":
            assert returned is None, "no result is manufactured for a torn-down process"
        else:
            assert isinstance(raised, asyncio.CancelledError)
            assert raised.__cause__ is errors[branch]

        assert ledger.completion.calls == 1, "no second completion is attempted for one claim"
        if timing == "after-the-commit":
            assert len(await completions(trail)) == 1, "the committed row stands"
            assert await trail.open_invocations(decision_id=call.decision.id) == []
        else:
            assert await completions(trail) == []
            assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    async def test_an_erasure_between_the_claim_and_its_completion_leaves_no_claim(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """``clear()`` wins over a write in flight (ADR-0192 §3, §6).

        The call's own result stands, the refusal reaches the operator as a
        diagnostic, and **nothing is recreated**: the "claim left open"
        postcondition is not an obligation to put back a row the user destroyed on
        purpose, which §6 names as the one answer no store may give.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.hold = asyncio.Event()
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy(output={"unread": 4}))
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.completion.entered.wait()
            await trail.clear()
            ledger.completion.hold.set()
            result = await task

        assert result.output == {"unread": 4}
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": "InvalidCompletionError",
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]
        assert await rows(trail) == [], "nothing is recreated over an erased claim"

    # --- ADR-0192 §1, §3: neither append is bounded, and both are shielded --

    async def test_neither_append_is_bounded_by_the_seams_deadline(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """A lane that "helpfully" wraps either in a deadline breaks a clause here.

        ``invoke`` is given a ``timeout`` far shorter than each barrier is held
        for, and the **negative** is what is asserted while the barrier is held:
        no return, no ``AuditError``, no diagnostic, no ``ToolResult``. Nothing
        advances the ledger's clock, because that clock supplies instants and
        nothing here is decided on a duration at all — the determinism comes from
        the ordering the barrier fixes.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(read_only("inbox"), spy)
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        held = asyncio.create_task(invoker.invoke(call, timeout=BRIEF))
        await ledger.claim.entered.wait()
        await _settled()

        assert not held.done(), "the claim append outlasts the call's deadline"
        assert spy.calls == []

        ledger.claim.hold.set()
        ledger.completion.hold = asyncio.Event()
        await ledger.completion.entered.wait()
        await _settled()

        assert not held.done(), "the completion append outlasts it too"
        assert len(spy.calls) == 1, "the callable has run and its result is computed"

        ledger.completion.hold.set()
        result = await held

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert len(await completions(trail)) == 1

    async def test_two_cancellations_during_the_claim_append_do_not_lose_the_claim(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The shield, and ADR-0192 §1's clause on a cancellation before the callable.

        One cancellation is passed by an implementation that shields the first
        await and then awaits the retained task bare, so two are delivered and the
        test asserts ``invoke`` was still waiting after the second. Four things
        follow once the append lands: the callable is **never entered**; the
        completion carrying what ADR-0029 §4 computes for that cancellation is
        **durably appended**; **no claim is left open**; and the
        ``CancelledError`` still reaches the caller, with the task ending
        cancelled (ADR-0060 §1).
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await ledger.claim.entered.wait()
        for _ in range(2):
            task.cancel()
            await _settled()
            assert not task.done(), "absorbing exactly one cancellation is a failure"

        ledger.claim.hold.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()
        assert spy.calls == [], "the callable is never entered"
        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.failure_kind is None
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_cancellation_during_a_failing_claim_carries_its_failure_out(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The **append-fails** twin of the append-lands case, and the exits differ.

        There the append succeeded, so a completion is owed and its absence is the
        defect. Here ``invoke`` observed **no** claim, so it enters no callable and
        completes nothing — and the cancellation is delivered onward **whatever
        the append did** (ADR-0060 §1): the append's failure does not stand in its
        place, it is attached as the cause and reaches the operator through the
        diagnostic. An implementation can pass either case and fail the other.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        failure = RuntimeError("the store would not write")
        ledger.claim.error = failure
        invoker = consuming(ledger)
        spy = Spy()
        invoker.register(tool(), spy)
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.claim.entered.wait()
            task.cancel()
            await _settled()
            ledger.claim.hold.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task

        assert caught.value.__cause__ is failure, "the append failure never stands in its place"
        assert task.cancelled()
        assert spy.calls == [], "the callable is never entered"
        assert ledger.completion.calls == 0, "no completion is attempted for a claim never observed"
        assert appended(captured) == [{"operation": CLAIM, "fault_class": "RuntimeError"}]

    async def test_two_cancellations_during_a_failing_completion_carry_its_failure_out(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The shield on the *second* append, which §3 puts on each and not the first.

        An implementation can shield the claim robustly and then await the
        retained completion task bare, losing the append's real failure to the
        cancellation ADR-0054 permits the store to re-raise in its place — and
        reporting neither the fault nor the open claim. Here the cancellation is
        what leaves, carrying the append's failure as its ``__cause__``, the
        diagnostic is emitted, and the claim is left open.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.completion.hold = asyncio.Event()
        failure = RuntimeError("the worker failed")
        ledger.completion.error = failure
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy())
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
            await ledger.completion.entered.wait()
            for _ in range(2):
                task.cancel()
                await _settled()
                assert not task.done(), "absorbing exactly one cancellation is a failure"

            ledger.completion.hold.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task

        assert caught.value.__cause__ is failure
        assert task.cancelled()
        assert appended(captured) == [
            {
                "operation": COMPLETION,
                "fault_class": "RuntimeError",
                "outcome": ToolOutcome.SUCCEEDED,
            }
        ]
        assert len(await trail.open_invocations(decision_id=call.decision.id)) == 1

    # --- ADR-0194 §3, §11: the spend admission at this seam ---------------

    @pytest.fixture
    def admitting(self) -> Callable[[SpendGate], InvocableToolRegistry]:
        """Return a factory building an empty invoker over ``gate``.

        A factory rather than a built subject for ``consuming``'s reason: every
        case here needs the *gate* arranged — refusing, blocked, slow, recording —
        and an invoker is handed its gate at construction. The ledger it claims
        through is a fresh ``FakeAuditTrail``, read back off the subject, so a case
        can assert that a refused call left no claim and no completion.
        """
        raise NotImplementedError

    @pytest.fixture(params=REFUSALS, ids=["ceiling", "undetermined"])
    def refusal(self, request: pytest.FixtureRequest) -> BaseException:
        """Each of ADR-0194 §4's two refusal classes, driven wherever both bind.

        A fresh instance per case: the identity assertion below is what proves the
        invoker propagated the gate's own object rather than an equivalent, so a
        shared one reused across cases would let a stale ``__notes__`` from an
        earlier test answer a later one.
        """
        return cast("BaseException", type(request.param)(*request.param.args))

    async def test_a_refused_admission_reaches_no_callable_and_writes_no_row(
        self,
        admitting: Callable[[SpendGate], InvocableToolRegistry],
        refusal: BaseException,
    ) -> None:
        """ADR-0194 §3: refused before the claim, so there is nothing to complete.

        The two halves are separable and both are asserted. An implementation
        consulting the gate *after* the claim leaves a row for an act that never
        happened; one consulting it after the callable has already reached the
        world.
        """
        gate = RecordingGate(refusal=refusal)
        invoker = admitting(gate)
        spy = Spy()
        invoker.register(tool(), spy)
        trail = trail_of(invoker)
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(type(refusal)):
            await invoker.invoke(call, timeout=PATIENT)

        assert spy.calls == []
        assert await trail.open_invocations(decision_id=call.decision.id) == []
        assert await trail.export_invocations() == []

    async def test_the_refusal_the_caller_catches_is_the_gate_s_own_instance(
        self,
        admitting: Callable[[SpendGate], InvocableToolRegistry],
        refusal: BaseException,
    ) -> None:
        """ADR-0194 §4's payload-free rule, driven at the seam that can undo it.

        §4 makes both messages payload-free where they are **raised**; the seam
        between the gate and the caller is the only place that could put the
        recipient back. An invoker catching the refusal and re-raising the same
        class with the call appended passes every other clause here — they assert
        the class, the untouched callable, the unwritten rows and the released
        handle, and none of them reads the message.

        The six channels are the closed set ADR-0029 §3's message rule uses.
        ``__traceback__`` is deliberately absent: a propagating exception
        necessarily carries frames whose locals include the ``ToolCall``, so
        requiring the sentinel's absence from them would forbid the propagation
        this same test requires.
        """
        gate = RecordingGate(refusal=refusal)
        invoker = admitting(gate)
        invoker.register(tool(), Spy())
        trail = trail_of(invoker)
        call = call_for(tool(), parameters={"to": SENTINEL_RECIPIENT, "subject": SENTINEL_SUBJECT})
        await trail.record(call.decision)

        with pytest.raises(type(refusal)) as caught:
            await invoker.invoke(call, timeout=PATIENT)

        assert caught.value is refusal
        for channel in user_facing_channels(caught.value):
            assert SENTINEL_RECIPIENT not in channel, channel
            assert SENTINEL_SUBJECT not in channel, channel

    @pytest.mark.parametrize(
        "cost",
        [
            ToolCost(basis=CostBasis.FREE),
            ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("20"), currency="USD"),
            ToolCost(basis=CostBasis.UNKNOWN),
        ],
        ids=["free", "per-call", "unknown"],
    )
    async def test_the_pinned_definitions_own_cost_is_what_reaches_the_gate(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry], cost: ToolCost
    ) -> None:
        """ADR-0194 §3, §11: the estimate is the pinned declaration, unchanged.

        Without this an invoker passing ``FREE`` for a registered ``PER_CALL`` cost
        of 20 lets the callable begin at an accounted total of 90 against a ceiling
        of 100 and passes every refusal and release clause beside it.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        definition = tool(cost=cost)
        invoker.register(definition, Spy())
        trail = trail_of(invoker)

        result = await invoked(invoker, trail, call_for(definition), timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert gate.estimates == [cost]

    async def test_the_estimate_is_not_read_from_the_callers_argument(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """A call mutated after construction fails ADR-0029's way, and never reaches the gate.

        ADR-0194 §3 marks the order fail-closed in one direction: a ``__dict__``
        write could carry an ``UNKNOWN`` cost the user never authorised, and an
        invoker reaching the gate first would refuse it as a *spend* fault when it
        is a binding failure — sending the operator to a budget setting to repair
        a tampered call.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        registered = tool(cost=ToolCost(basis=CostBasis.FREE))
        spy = Spy()
        invoker.register(registered, spy)
        trail = trail_of(invoker)
        call = call_for(registered)
        await trail.record(call.decision)
        object.__setattr__(call.request.tool, "cost", ToolCost(basis=CostBasis.UNKNOWN))

        with pytest.raises(ToolBindingError):
            await invoker.invoke(call, timeout=PATIENT)

        assert gate.estimates == []
        assert spy.calls == []

    async def test_the_handle_is_released_after_the_completion_on_the_admitted_path(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """ADR-0194 §3: released in a ``finally``, once, and not before the row lands.

        Releasing *before* the completion would close ADR-0194 §3's stated
        double-count window in the wrong direction — the mechanism is required to
        over-count for one operation rather than under-count for one.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        invoker.register(tool(), Spy())
        trail = trail_of(invoker)
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert len(gate.released) == 1
        assert gate.outstanding == []
        # The claim and its completion, so the release did not run ahead of the row.
        assert len(await trail.export_invocations()) == 2
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_the_handle_is_released_when_the_tool_raises(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """The raising path, which the succeeding one does not reach."""
        gate = RecordingGate()
        invoker = admitting(gate)
        invoker.register(tool(), Raiser(RuntimeError("boom")))
        trail = trail_of(invoker)

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        # An exception escaping the tool is data, not a raise (ADR-0029 §3), so the
        # `finally` unwinds through a *returned* failure rather than a propagating
        # one — which is the path a release placed after the return would miss.
        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert len(gate.released) == 1
        assert gate.outstanding == []

    async def test_the_handle_is_released_under_a_cancellation_inside_the_callable(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """ADR-0194 §5's synchronous release doing the work it exists for.

        The ``finally`` runs while the task is being torn down. A release carrying
        a suspension point could be cancelled there and leave the reservation
        standing; this one cannot, because there is no ``await`` in it.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        entered = asyncio.Event()

        async def waits(
            parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
        ) -> FrozenJson:
            del parameters, idempotency_key
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError  # pragma: no cover — the wait never returns

        invoker.register(tool(), waits)
        trail = trail_of(invoker)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(gate.released) == 1
        assert gate.outstanding == []

    async def test_the_invoker_releases_one_admission_exactly_once(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """The gate must tolerate a second release; the invoker must not make one.

        A double release is a no-op against a conforming gate, so an invoker making
        one passes every other clause here — and against a *hostile* reading of
        ADR-0194 §3's lifetime rule it is exactly the shape that drops a live
        reservation.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        invoker.register(tool(), Spy())
        trail = trail_of(invoker)

        await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert len(gate.released) == 1

    @pytest.mark.parametrize(
        ("definition", "expected"),
        [
            (tool(), ToolOutcome.INDETERMINATE),
            (read_only(), ToolOutcome.FAILED),
            (tool(idempotency=Idempotency.NATURAL), ToolOutcome.FAILED),
        ],
        ids=["side-effecting", "read-only", "natural"],
    )
    async def test_a_gate_that_never_answers_expires_at_the_callers_deadline(
        self,
        admitting: Callable[[SpendGate], InvocableToolRegistry],
        definition: ToolDefinition,
        expected: ToolOutcome,
    ) -> None:
        """ADR-0194 §3: the admission runs **inside** the deadline ``invoke`` enforces.

        A suite whose gate fake always answers leaves the one window where a new
        await sits outside the deadline untested — and an implementation admitting
        outside it has moved the one await ADR-0029 §4 exists for out of that
        section's reach, in the window before the callable is even created.

        The classification is ADR-0029 §4's existing rule, unchanged and
        unnarrowed: this is ``invoke`` suspended in its own pre-call work, and
        nothing states which await the expiry landed in (ADR-0034 §1).
        """
        gate = BlockingGate()
        invoker = admitting(gate)
        spy = Spy()
        invoker.register(definition, spy)
        trail = trail_of(invoker)
        call = call_for(definition)

        result = await invoked(invoker, trail, call, timeout=BRIEF)

        assert result.outcome is expected
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert spy.calls == [], "the callable was never created"
        assert gate.entered == 1
        assert gate.cancelled == 1
        assert gate.outstanding == [], "no reservation nobody holds a handle for"
        assert await trail.export_invocations() == []

    async def test_the_admission_and_the_callable_share_one_deadline(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """ADR-0194 §3, §11: one window, not one each.

        The gate takes more than half the budget and the callable then does the
        same — each inside the deadline on its own, together past it. An
        implementation giving the admission a fresh window and the callable another
        passes the never-answering-gate case above (that gate expires inside the
        first window) and then returns this call **successfully** at nearly twice
        the deadline the caller set.
        """
        budget = 0.3
        gate = SlowGate(budget * 0.6)
        invoker = admitting(gate)
        sleeper = Sleeper(budget * 0.6)
        invoker.register(tool(), sleeper)
        trail = trail_of(invoker)
        call = call_for(tool())

        started = asyncio.get_running_loop().time()
        result = await invoked(invoker, trail, call, timeout=timedelta(seconds=budget))
        elapsed = asyncio.get_running_loop().time() - started

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert elapsed < budget * 1.8, (
            f"expired at {elapsed:.3f}s, which is a second window rather than the caller's one"
        )
        assert sleeper.calls == 1, "the callable was entered; it simply did not finish"
        assert len(gate.released) == 1

    async def test_the_claim_append_does_not_consume_the_callables_window(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """ADR-0192 §7's exclusion, pinned so that ADR-0194 §3 cannot be read past it.

        §3 puts the **admission** inside the window ``invoke`` already enforces, and
        §11 drives that as one window shared with the callable. It says nothing about
        ADR-0192's appends, and ADR-0192 §7 is explicit in the other direction:
        "``timeout`` is the deadline for the *call*, and it is not a budget for this
        method's whole frame … **Neither ledger append is bounded by it**: each is
        awaited to its outcome, so a store that has stopped answering blocks the call
        before the callable."

        So a slow claim does not shorten the callable's window, and a conforming
        ``invoke`` measures the remainder it hands the callable **before** the claim
        rather than after it. An implementation recomputing the remainder afterwards
        would let an append bound the call — the exact narrowing §7 refuses — and
        would classify a call as timed out on the strength of a store's latency.

        This is stated as a fixture rather than left to be inferred because the
        opposite reading is available and plausible: a reviewer reading §3's "single
        original deadline" alone, without §7 beside it, concludes that the claim
        must eat the budget too.
        """
        trail = FakeAuditTrail()
        ledger = DrivenLedger(trail)
        ledger.claim.hold = asyncio.Event()
        invoker = consuming(ledger)
        invoker.register(read_only("inbox"), Spy())
        call = call_for(read_only("inbox"))
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=BRIEF))
        await ledger.claim.entered.wait()
        # Well past the caller's deadline, with the claim still in flight.
        await asyncio.sleep(BRIEF.total_seconds() * 4)
        assert not task.done(), "the claim is awaited to its outcome, not to the deadline"

        ledger.claim.hold.set()
        result = await asyncio.wait_for(task, 5.0)

        assert result.outcome is ToolOutcome.SUCCEEDED, (
            "the callable kept its own window: the append that delayed it is not "
            "bounded by the deadline and does not shorten what the call is given"
        )

    async def test_a_granted_admission_is_released_when_an_unrecorded_claim_is_refused(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """ADR-0194 §3: released "after the failure that prevented" the completion.

        The gate **granted**, so a reservation is standing; ADR-0192 §1's claim then
        refuses, so no callable runs and no completion is owed. An invoker that
        released only after a returned result or a cancelled callable passes every
        other release clause here and strands the reservation — after which the
        projected total of every later admission counts a call that never happened,
        and the ceiling refuses work the user authorised.

        The condition is the real one rather than a scripted knob: the decision is
        simply never recorded, which is what ADR-0192 §1 refuses a claim on.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        spy = Spy()
        invoker.register(tool(), spy)

        with pytest.raises(UnrecordedAuthorisationError):
            await invoker.invoke(call_for(tool()), timeout=PATIENT)

        assert gate.estimates == [tool().cost], "the gate was consulted before the claim"
        assert len(gate.released) == 1, "the reservation the grant took was retired"
        assert gate.outstanding == [], "no reservation nobody holds a handle for"
        assert spy.calls == [], "the callable was never reached"

    async def test_a_granted_admission_is_released_when_a_spent_claim_is_refused(
        self, admitting: Callable[[SpendGate], InvocableToolRegistry]
    ) -> None:
        """The other of ADR-0192 §1's two refusals, which arrives by a different route.

        There the trail held no matching decision; here it holds one that has already
        been spent. An implementation catching a single class would pass the case
        above and strand the reservation on this one — so both are driven, and the
        assertion is over the **delta** across the second call rather than over the
        totals, since the first one legitimately took and released a reservation of
        its own.
        """
        gate = RecordingGate()
        invoker = admitting(gate)
        spy = Spy()
        invoker.register(tool(), spy)
        trail = trail_of(invoker)
        call = call_for(tool())

        first = await invoked(invoker, trail, call, timeout=PATIENT)
        assert first.outcome is ToolOutcome.SUCCEEDED
        already = len(gate.released)

        with pytest.raises(AuthorisationSpentError):
            await invoker.invoke(call, timeout=PATIENT)

        assert len(gate.released) == already + 1, "the second grant's reservation was retired too"
        assert gate.outstanding == []
        assert len(spy.calls) == 1, "the refused call reached no callable"

    # --- ADR-0195: the cost a successful call reports ----------------------

    @pytest.fixture
    def accounting(self) -> Callable[[FakeAuditTrail], InvocableToolRegistry]:
        """Return a factory building an invoker whose ledger **and** gate are ``trail``.

        The two other factories give the subject a fresh counterpart for whichever
        seam they are not arranging, which is right for every case that reads one
        of them. ADR-0195's end-to-end case reads **both at once** — a figure
        written to a completion row by the ledger has to be the figure the gate
        then totals — and two objects would leave the gate measuring a history the
        ledger never wrote. One trail is also what the composition root wires.
        """
        raise NotImplementedError

    async def test_a_reported_figure_reaches_the_completion_row_unaltered(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §2 and §6: the seam unwraps, and ADR-0192 §5's mapping carries it.

        The envelope itself reaches nothing: what the result holds is the output
        and the figure, separately, and no ``ReportedOutput`` is on the row.
        """
        priced = Priced(output={"sent": True})
        invoker.register(tool(), priced)
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == {"sent": True}
        assert result.incurred_cost == REPORTED
        (completion,) = await completions(trail)
        assert completion.incurred_cost == REPORTED
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_bare_return_beside_it_still_records_an_unknown_cost(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The control the reporting case is only meaningful against.

        A widening obliges nobody: the tool that says nothing is the tool every
        registration in this tree is today, and its row records ``UNKNOWN``
        exactly as it did before the channel existed.
        """
        invoker.register(tool("reports"), Priced(output=1))
        invoker.register(tool("silent"), Spy(output=1))

        priced = await invoked(invoker, trail, call_for(tool("reports"), decision_id="d-priced"))
        silent = await invoked(invoker, trail, call_for(tool("silent"), decision_id="d-silent"))

        assert priced.output == silent.output == 1
        assert priced.incurred_cost == REPORTED
        assert silent.incurred_cost is None
        recorded = {each.decision_id: each.incurred_cost for each in await completions(trail)}
        assert recorded == {"d-priced": REPORTED, "d-silent": ToolCost(basis=CostBasis.UNKNOWN)}

    async def test_an_unknown_basis_in_an_envelope_lands_as_a_bare_return_does(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §5, asserted as identity rather than as two similar rows.

        The clause is that no implementation treats the two differently — at the
        seam, on the row, or in the total — so that no reader can build a
        distinction on the difference between saying ``UNKNOWN`` and saying
        nothing.
        """
        unknown = ToolCost(basis=CostBasis.UNKNOWN)
        invoker.register(tool("reports"), Priced(output="x", cost=unknown))
        invoker.register(tool("silent"), Spy(output="x"))

        reported = await invoked(invoker, trail, call_for(tool("reports"), decision_id="d-priced"))
        bare = await invoked(invoker, trail, call_for(tool("silent"), decision_id="d-silent"))

        assert reported.outcome is bare.outcome is ToolOutcome.SUCCEEDED
        assert reported.output == bare.output == "x"
        recorded = {each.decision_id: each.incurred_cost for each in await completions(trail)}
        assert recorded == {"d-priced": unknown, "d-silent": unknown}

    async def test_a_cost_that_fails_revalidation_is_discarded_alone(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §4, in ADR-0032 §6's own idiom and for its own reason.

        ``model_construct`` bypasses every validator while satisfying
        ``isinstance``, so a ``PER_CALL`` basis with no amount would otherwise
        reach a row and, through it, ADR-0194's arithmetic. What is discarded is
        the **cost and nothing else**: discarding a real success — an act that
        already happened, possibly irreversibly — over an accounting field would
        destroy the record ADR-0192 exists to write, to reach a fail-closed state
        the ``UNKNOWN`` row already reaches.

        The envelope is ``model_construct``-built too, and it has to be: pydantic
        revalidates a nested model, so a normally-constructed ``ReportedOutput``
        refuses this cost in the **tool's** frame. That is where the case would
        stop without the seam's own round-trip — and it is also why the seam
        cannot simply hand the figure to ``ToolResult`` and let *that* refuse it:
        the refusal would arrive as an ``INTERNAL`` result, destroying a real
        success over an accounting field.
        """
        bad = ToolCost.model_construct(basis=CostBasis.PER_CALL)
        invoker.register(tool(), Envelope(unvalidated({"sent": True}, cost=bad)))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED, "the act happened and the record says so"
        assert result.output == {"sent": True}
        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_dumped_cost_that_differs_crosses_as_the_round_trips_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §6's rule inherited rather than a new one being minted here.

        A ``ToolCost`` subclass may legitimately override ``model_dump``, and what
        crosses is what the round-trip produced — not what the attribute appeared
        to hold.
        """
        substitute = {"basis": CostBasis.PER_CALL, "amount": Decimal("9.99"), "currency": "EUR"}
        invoker.register(tool(), Priced(cost=dumping(lambda: substitute)))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.incurred_cost == ToolCost(
            basis=CostBasis.PER_CALL, amount=Decimal("9.99"), currency="EUR"
        )
        (completion,) = await completions(trail)
        assert completion.incurred_cost == result.incurred_cost

    async def test_an_output_an_envelope_carries_but_the_annotation_refuses_is_internal(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Exactly where the same value lands when it is returned bare (ADR-0029 §3).

        The envelope adds **no** route by which content reaches a result that a
        bare return does not already reach, so both tools produce the same
        classification — and the reported figure goes with the discarded result,
        because the two came off one object.
        """
        invoker.register(tool("enveloped"), Envelope(unvalidated({1, 2})))
        invoker.register(tool("bare"), Returner({1, 2}))

        enveloped = await invoked(invoker, trail, call_for(tool("enveloped"), decision_id="d-env"))
        bare = await invoked(invoker, trail, call_for(tool("bare"), decision_id="d-bare"))

        assert enveloped.outcome is bare.outcome is ToolOutcome.FAILED
        assert enveloped.failure is not None
        assert bare.failure is not None
        assert enveloped.failure.kind is bare.failure.kind is ToolFailureKind.INTERNAL
        recorded = {each.decision_id: each.incurred_cost for each in await completions(trail)}
        unknown = ToolCost(basis=CostBasis.UNKNOWN)
        assert recorded == {"d-env": unknown, "d-bare": unknown}

    async def test_a_returned_mapping_carrying_an_incurred_cost_key_is_output(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """``isinstance`` and no other test (ADR-0195 §2).

        An implementation sniffing for a ``dict`` with an ``incurred_cost`` key
        would read a tool's *output* as a report, and every JSON API that happens
        to use that word would start filling a spend ledger.
        """
        payload = {"incurred_cost": {"basis": "per_call", "amount": "5.00", "currency": "USD"}}
        invoker.register(tool(), Spy(output=payload))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.output == payload, "JSON that mentions a cost is still JSON"
        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    async def test_this_seams_deadline_discards_the_figure_it_pre_empts(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §4: one carrier has one fate, and neither accessor is entered.

        The callable absorbed its cancellation and returned an envelope anyway. A
        row citing its figure would attribute to the tool a statement about a call
        the seam has just said it did not get to finish — and the first
        interruption check is what stops the accessors being entered at all.
        """
        envelope, seen = watched(output={"sent": True})
        swallowing = SwallowingPriced(envelope)
        invoker.register(tool(), swallowing)
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=BRIEF)

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert result.incurred_cost is None
        assert seen.counts == {"output": 0, "incurred_cost": 0}, "no field of it was read"
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    async def test_a_delivered_cancellation_discards_the_figure_it_pre_empts(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The deadline's twin, on the route ADR-0029 §4 keeps on the executor.

        A separate case because an implementation can hold one and drop the other:
        the deadline is the seam's own state, while this one is read off the task.
        """
        envelope, seen = watched(output={"sent": True})
        swallowing = SwallowingPriced(envelope)
        invoker.register(tool(), swallowing)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await swallowing.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert seen.counts == {"output": 0, "incurred_cost": 0}, "no field of it was read"
        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_each_of_the_envelopes_fields_is_read_exactly_once(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §2's single-read clause, asserted on the access **count**.

        A matrix of hostile *first* accesses alone is satisfiable by an
        implementation that reads ``output`` a second time when it builds the
        ``ToolResult`` — so this envelope answers its first read truthfully,
        raises on the second and would answer differently on the third, and the
        count is what the case is about.
        """
        envelope, seen = watched(output={"sent": True}, intercept=hostile_after_the_first)
        invoker.register(tool(), Envelope(envelope))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert seen.counts == {"output": 1, "incurred_cost": 1}
        assert result.output == {"sent": True}, "the completion carries the first captured value"
        assert result.incurred_cost == REPORTED

    async def test_an_output_accessor_that_raises_is_internal_and_discards_the_figure(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §2: the two reads' defects resolve on their **subject**.

        An unreadable ``output`` leaves the seam with nothing to record as the
        call's result, so it takes the ``INTERNAL`` path an unrepresentable output
        already takes — and the figure is discarded with it, unread, because a
        seam keeping half of a misbehaving carrier would be arbitrating between
        two accounts a tool gave of its own call.
        """

        def raise_on_output(name: str, count: int) -> object:
            if name == "output":
                msg = "this accessor is broken"
                raise RuntimeError(msg)
            return PASS

        envelope, seen = watched(output={"sent": True}, intercept=raise_on_output)
        invoker.register(tool(), Envelope(envelope))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert seen.counts["incurred_cost"] == 0, "the figure went with the result, unread"
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_cost_accessor_that_raises_yields_unknown_and_nothing_else(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The other subject: a malformed cost costs the **cost** and no more.

        The read runs under its own ``Exception`` guard because it happens after
        ADR-0192 §1's claim has been appended, so an exception escaping it would
        leave a claim with no completion — over an accounting field, on a call
        that already ran.
        """

        def raise_on_cost(name: str, count: int) -> object:
            if name == "incurred_cost":
                msg = "this accessor is broken"
                raise RuntimeError(msg)
            return PASS

        envelope, _ = watched(output={"sent": True}, intercept=raise_on_cost)
        invoker.register(tool(), Envelope(envelope))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == {"sent": True}
        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_model_dump_that_raises_yields_unknown_and_nothing_else(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The same guard, one step further in: the dump is tool-authored too.

        ADR-0032 §6 rules that overriding ``model_dump`` is legitimate, so the
        seam runs the attribute access, the dump **and** the validation under one
        guard rather than trusting any of the three.
        """

        def explode() -> Mapping[str, object] | None:
            msg = "this dump is broken"
            raise RuntimeError(msg)

        invoker.register(tool(), Priced(output="ok", cost=dumping(explode)))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.SUCCEEDED
        assert result.output == "ok"
        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    @pytest.mark.parametrize("field", ["output", "incurred_cost"])
    async def test_an_accessor_that_cancels_the_invoking_task_discards_the_figure(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, field: str
    ) -> None:
        """ADR-0195 §4's **second** interruption check, which is what sees this.

        Reading a tool-authored value can itself deliver a cancellation, so a
        check made only before the reads would build a result carrying a figure
        obtained after the seam had stopped waiting. The cancellation propagates
        unchanged — it is not an accounting fact — and the row records ``UNKNOWN``.
        """

        def cancel_on(name: str, count: int) -> object:
            if name == field:
                cancel_this_task()
            return PASS

        envelope, _ = watched(output={"sent": True}, intercept=cancel_on)
        invoker.register(tool(), Envelope(envelope))
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        with pytest.raises(asyncio.CancelledError):
            await task

        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_model_dump_that_cancels_the_invoking_task_discards_the_figure(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """And it returns a **valid** value, so only the re-read can catch it.

        An implementation that took the round-trip's result because the round-trip
        succeeded would record a figure obtained after the seam had stopped
        waiting.
        """

        def cancel_and_answer() -> Mapping[str, object] | None:
            cancel_this_task()
            return None

        invoker.register(tool(), Priced(output="ok", cost=dumping(cancel_and_answer)))
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        with pytest.raises(asyncio.CancelledError):
            await task

        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_reported_figure_reaches_the_total_and_a_ceiling_refuses_the_next_call(
        self, accounting: Callable[[FakeAuditTrail], InvocableToolRegistry]
    ) -> None:
        """The end-to-end case ADR-0192 §9 deferred to whichever ADR minted the channel.

        A **test-only** priced integration reports a ``PER_CALL`` figure, through
        ``invoke``, onto a completion row, into ADR-0194 §2's accounted total, and
        the ceiling then refuses a later call — with **no allowance configured**,
        which is the whole point: until this channel existed every row read
        ``UNKNOWN``, so the period was indeterminate unless the user had stated a
        per-call worst case of their own. The declaration is ``FREE`` throughout,
        so nothing the ceiling bites on came from ``ToolDefinition.cost``.
        """
        trail = FakeAuditTrail(currency="USD", day_ceiling=Decimal("1.00"))
        invoker = accounting(trail)
        priced = tool(cost=ToolCost(basis=CostBasis.FREE))
        invoker.register(
            priced,
            Priced(cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.60"), currency="USD")),
        )

        for attempt in ("first", "second"):
            result = await invoked(
                invoker, trail, call_for(priced, decision_id=f"d-{attempt}"), timeout=PATIENT
            )
            assert result.outcome is ToolOutcome.SUCCEEDED

        stated = {each.period: each for each in await trail.spend_totals()}
        assert stated[SpendPeriod.CALENDAR_DAY].accounted == Decimal("1.20"), (
            "the total is made of measured figures, not of an allowance"
        )

        with pytest.raises(SpendCeilingError):
            await invoked(invoker, trail, call_for(priced, decision_id="d-third"), timeout=PATIENT)

    # --- ADR-0032: the failure a tool classified itself ---------------------

    @pytest.mark.parametrize("kind", INTEGRATION_KINDS, ids=lambda each: each.value)
    async def test_each_integration_facing_kind_crosses_with_its_message_verbatim(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, kind: ToolFailureKind
    ) -> None:
        """ADR-0032 §9's first obligation, and #192's whole point.

        Six of ADR-0029 §3's eight kinds had no carrier at all, so an integration
        could not report any of them and every real failure arrived as
        ``INTERNAL``. Each of them now crosses as the tool raised it: the kind
        unchanged, and the message **verbatim** — the seam never edits, wraps,
        prefixes, truncates or re-authors a tool's text (§5).
        """
        invoker.register(tool(), Raiser(carrier(kind)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is kind
        assert result.failure.message == REPORTED_MESSAGE
        assert result.output is None

    @pytest.mark.parametrize(
        ("definition", "committed", "expected"),
        [
            (tool("smtp"), True, ToolOutcome.INDETERMINATE),
            (read_only("inbox"), True, ToolOutcome.FAILED),
            (natural("upsert"), True, ToolOutcome.FAILED),
            (tool("smtp"), False, ToolOutcome.FAILED),
            (read_only("inbox"), False, ToolOutcome.FAILED),
            (natural("upsert"), False, ToolOutcome.FAILED),
        ],
        ids=[
            "side-effecting-may-have-committed",
            "read-only-may-have-committed",
            "natural-may-have-committed",
            "side-effecting-did-not",
            "read-only-did-not",
            "natural-did-not",
        ],
    )
    async def test_the_outcome_is_the_fact_conjoined_with_the_declaration(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        definition: ToolDefinition,
        committed: bool,
        expected: ToolOutcome,
    ) -> None:
        """ADR-0032 §2's table over **both** inputs, asserted rather than sampled.

        Kind is what the tool knows; outcome is what the seam rules. The two
        middle rows are the ones that pin the conjunction — an implementation
        reading the fact alone passes the other four. A read-only tool reporting a
        possible commit is contradicting the declaration the policy approved, and
        the declaration is the trusted value; a ``NATURAL`` tool is idempotent by
        nature, so ignorance costs nothing.

        The conjunction is read off ``definition.interrupted_outcome`` rather than
        recomputed here, which is ADR-0031 §1's single copy acquiring its third
        reader instead of a fourth spelling of the same comparison.
        """
        invoker.register(definition, Raiser(carrier(committed=committed)))

        result = await invoked(invoker, trail, call_for(definition), timeout=PATIENT)

        assert result.outcome is expected
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.RATE_LIMITED, (
            "the kind is the tool's either way"
        )

    async def test_no_report_makes_a_raise_succeed(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """§2's monotonicity, stated as the property rather than as a row.

        There is no value of the fact that produces ``SUCCEEDED`` — a raise is
        never a success — so the worst a lying or careless integration achieves is
        ``INDETERMINATE`` for a call that definitely failed: pessimistic, not
        auto-retried, resolved explicitly.
        """
        outcomes = set()
        for index, committed in enumerate((True, False)):
            invoker.register(tool(f"t-{index}"), Raiser(carrier(committed=committed)))
            result = await invoked(
                invoker, trail, call_for(tool(f"t-{index}"), decision_id=f"d-{index}")
            )
            outcomes.add(result.outcome)

        assert ToolOutcome.SUCCEEDED not in outcomes
        assert outcomes == {ToolOutcome.INDETERMINATE, ToolOutcome.FAILED}

    @pytest.mark.parametrize("kind", list(ToolFailureKind), ids=lambda each: each.value)
    async def test_every_kind_a_tool_may_raise_is_accepted_or_refused_exhaustively(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail, kind: ToolFailureKind
    ) -> None:
        """ADR-0032 §3, in the shape ADR-0029 §10 already requires of ``retryable``.

        Asserted over the **whole enum** rather than sampled, so a member added
        later cannot become silently reachable. ``TIMED_OUT`` is the only reserved
        member — stated as an enumeration of one rather than as a category
        ("seam-owned kinds"), because a category drifts as members are added — and
        ``CANCELLED`` is accepted, which ADR-0031 §3 requires: refusing it would
        leave that member with no producer at all.
        """
        reserved = kind is ToolFailureKind.TIMED_OUT
        invoker.register(tool(), Raiser(carrier(kind)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is (ToolFailureKind.INTERNAL if reserved else kind)
        assert (result.failure.message == REPORTED_MESSAGE) is not reserved

    async def test_a_reserved_timed_out_is_refused_and_its_message_never_crosses(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §3: the seam's deadline is the seam's alone.

        ``TIMED_OUT`` means **this** deadline expired, which ADR-0029 §4 requires
        the seam to *establish* rather than infer — so a tool naming it is the
        misclassification that rule refuses, arriving by the front door. The
        tool-authored ``ToolFailure`` is discarded **whole**: refused rather than
        remapped to ``UNAVAILABLE``, because choosing a neighbouring kind on the
        tool's behalf is the seam interpreting a broken integration's meaning, one
        step from interpolating its text. It fails safe — ``INTERNAL`` is not
        retryable — and the message the tool wrote reaches neither the result nor
        anything the seam logs.
        """
        invoker.register(tool(), Raiser(carrier(ToolFailureKind.TIMED_OUT)))
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert not result.failure.kind.retryable, "nothing is retried on a claim the seam rejected"
        assert REPORTED_MESSAGE not in result.failure.message
        assert "smtp" in result.failure.message
        assert ToolFailureKind.TIMED_OUT.value in result.failure.message
        assert REPORTED_MESSAGE not in repr(captured)
        [line] = [each for each in captured if each["event"] == RESERVED_KIND]
        assert line["tool_id"] == "smtp"
        assert line["kind"] is ToolFailureKind.TIMED_OUT

    async def test_the_fact_survives_a_refused_reserved_kind(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """§3's last clause, which nothing else pins and which reads as tidy-up.

        A tool that got the *kind* wrong may still be telling the truth about its
        side effect, and discarding that with the payload would record a possible
        commit as certainly-nothing-happened. Structurally: the seam throws away
        the whole ``ToolFailure`` and keeps the fact, because they are separable
        values — which is why the fact is a field on the exception rather than on
        ``ToolFailure``.
        """
        invoker.register(tool(), Raiser(carrier(ToolFailureKind.TIMED_OUT, committed=True)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL

    async def test_a_raised_cancelled_is_accepted_as_the_tool_reported_it(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The mirror of the reserved case, and together they pin one member.

        ADR-0031 §3 re-scoped ``CANCELLED`` to "what an integration reports when
        its own upstream cancelled or aborted the operation" and stated that the
        seam never synthesises it. Refusing a raised one here would leave the
        member with no producer at all. Stating the reservation as an enumeration
        of one rather than as a category is what makes this pair meaningful.
        """
        invoker.register(tool(), Raiser(carrier(ToolFailureKind.CANCELLED, committed=True)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.INDETERMINATE, "ADR-0031 §3's own rule, computed"
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.CANCELLED
        assert result.failure.message == REPORTED_MESSAGE

    async def test_a_retryable_classified_failure_admits_a_keyed_retry_and_refuses_an_unkeyed_one(
        self, consuming: Callable[[InvocationLedger], InvocableToolRegistry]
    ) -> None:
        """The retry algebra's first non-``INTERNAL`` exercise (ADR-0032 §9, #1583).

        ADR-0029 §5's conjunction was inert for every real failure: the only kind a
        spendable authorisation could reach was ``INTERNAL``, which is not
        retryable, or the ``INDETERMINATE`` an expiry gives such a tool — so "a
        retryable ``FAILED`` on a spendable ``KEYED`` authorisation" had no
        producer through ``invoke`` at all, which is what #1583 records. A raised
        ``RATE_LIMITED`` is that producer.

        **Both conjuncts, because asserting only the first would certify an
        implementation that reads ``retryable`` as permission** — which is the
        misreading ADR-0029 §3 says the clause exists to prevent. The ``KEYED``
        tool satisfies both and its further claim is admitted; the
        ``Idempotency.NONE`` tool satisfies conjunct 1, fails conjunct 2, and is
        refused at the seam.
        """
        trail = FakeAuditTrail()
        invoker = consuming(trail)
        invoker.register(keyed("keyed"), Raiser(carrier()))
        invoker.register(tool("unkeyed"), Raiser(carrier()))
        keyed_call = call_for(keyed("keyed"), decision_id="d-keyed")
        unkeyed_call = call_for(tool("unkeyed"), decision_id="d-unkeyed")
        await trail.record(keyed_call.decision)
        await trail.record(unkeyed_call.decision)

        first = await invoker.invoke(keyed_call, timeout=PATIENT)
        assert first.outcome is ToolOutcome.FAILED
        assert first.failure is not None
        assert first.failure.kind.retryable, "conjunct 1, answering something other than False"
        (completion,) = await completions(trail)
        assert completion.failure_kind is ToolFailureKind.RATE_LIMITED, "the kind is not dropped"

        await invoker.invoke(keyed_call, timeout=PATIENT)
        assert len(await claims(trail)) == 2, "conjunct 2 holds, so the retry's claim is admitted"

        await invoker.invoke(unkeyed_call, timeout=PATIENT)
        with pytest.raises(AuthorisationSpentError):
            await invoker.invoke(unkeyed_call, timeout=PATIENT)

    async def test_this_seams_expired_deadline_outranks_the_tools_classification(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §4's rank 2 over rank 3, with the carrier never read.

        A tool that maps its aborted request to ``UNAVAILABLE`` while the seam's
        deadline actually fired would, on a side-effecting non-``NATURAL`` tool,
        produce ``FAILED`` — certainly-nothing-happened for a call that outran its
        budget, where ADR-0029 §4 requires ``INDETERMINATE``. The seam knows and
        the tool does not, so the seam's knowledge wins and the carrier is
        discarded fact and all. Discarding the fact loses nothing: on this path
        the outcome is ``interrupted_outcome`` alone.
        """
        raising, seen = watched_carrier(committed=False, cost=CLASSIFIED_COST)
        invoker.register(tool(), SwallowingClassifier(raising))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=BRIEF)

        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.TIMED_OUT
        assert result.incurred_cost is None, "one carrier has one fate (ADR-0195 §4)"
        assert seen.counts == {
            "failure": 0,
            "effect_may_have_committed": 0,
            "incurred_cost": 0,
        }, "no attribute of the carrier was read"
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    async def test_a_pending_cancellation_outranks_the_tools_classification(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §4's rank 1: no result is constructed at all.

        The classified raise may itself be a consequence of the cancellation — an
        SDK mapping its aborted request to ``UNAVAILABLE`` on the way out — and
        answering a cancellation with a value is what ADR-0029 §4 forbids
        everywhere. A separate case from the deadline because an implementation
        can hold one and drop the other: the deadline is the seam's own state,
        while this is read off the task.
        """
        raising, seen = watched_carrier(committed=True, cost=CLASSIFIED_COST)
        swallowing = SwallowingClassifier(raising)
        invoker.register(tool(), swallowing)
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        await swallowing.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert seen.counts["failure"] == 0, "no attribute of the carrier was read"
        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_the_causes_text_reaches_neither_the_message_nor_a_log(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §5's enumeration, and the cause chain is the new hazard.

        ``raise ClassifiedToolError(...) from upstream_exc`` is good practice and
        should stay possible — the chain is exactly what a developer wants in a
        traceback. It is also where the upstream's error body lives, quoting a
        recipient or a subject line. So nothing derived from the exception object
        enters a message or a log: not ``str``, ``repr``, ``args``, ``__cause__``,
        ``__context__`` or ``__notes__``.
        """
        upstream = RuntimeError("recipient alice@example.com rejected")
        raising = carrier()
        raising.__cause__ = upstream
        raising.add_note("subject: quarterly numbers")
        invoker.register(tool(), Raiser(raising))
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            result = await invoker.invoke(call, timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.message == REPORTED_MESSAGE
        for leaked in ("alice@example.com", "rejected", "quarterly numbers"):
            assert leaked not in result.failure.message
            assert leaked not in repr(captured)

    async def test_the_log_line_carries_the_kind_and_never_the_tools_message(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §5 and §9, asserted **positively and negatively**.

        Only the negative half is a rule an implementation can violate silently —
        the natural log line includes the message, because it is the useful part —
        so a suite asserting only that the *cause* text is absent passes it. What
        the seam may log about a translated failure is the tool's id and
        ``failure.kind``: an identifier and a member of a closed enum.

        Declining to log the message is not a mitigation and §5 says so: it lands
        in ``ToolResult.failure.message``, and its onward destinations are the
        executor's — a log and a durable ``StepFailure`` when the outcome is
        ``FAILED``.
        """
        invoker.register(tool(), Raiser(carrier(ToolFailureKind.UNAVAILABLE)))
        call = call_for(tool())
        await trail.record(call.decision)

        with structlog.testing.capture_logs() as captured:
            await invoker.invoke(call, timeout=PATIENT)

        [line] = [each for each in captured if each["event"] == REPORTED_FAILURE]
        assert line["tool_id"] == "smtp"
        assert line["kind"] is ToolFailureKind.UNAVAILABLE
        assert REPORTED_MESSAGE not in repr(line)

    @pytest.mark.parametrize(
        "build",
        [
            BlankMessage,
            lambda: Raiser(
                tampered(failure=ToolFailure.model_construct(kind="rate_limited", message=" "))
            ),
        ],
        ids=["validated-at-the-raise-site", "model-construct-evading-the-validator"],
    )
    async def test_a_blank_message_never_reaches_a_result_by_either_route(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        build: Callable[[], FakeToolImplementation],
    ) -> None:
        """ADR-0032 §9, and the second arm is what makes the first worth writing.

        A tool raising with a message that renders as nothing fails
        ``ToolFailure``'s own validator in its **own frame** and comes back
        ``INTERNAL``; one evading that validator with ``model_construct`` comes
        back ``INTERNAL`` too, from §6's revalidation. Only the second fails
        against an implementation that trusts the raise site because
        ``isinstance`` passed.
        """
        invoker.register(tool(), build())

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.message.strip() != ""

    async def test_the_round_trip_repairs_what_pydantic_can_repair(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §6, pinned so a later lane cannot tighten it into a refusal.

        The line between repair and refusal is pydantic's own. ``"rate_limited"``
        names a member, so validation coerces it and the ``AttributeError`` a
        downstream ``failure.kind.retryable`` would otherwise raise is gone —
        which is the outcome to want. Surrounding whitespace is stripped, the same
        normalisation ``ToolFailure(...)`` performs at the raise site, which is
        why §5's pass-through is a pass-through for every normally-constructed
        failure. Requiring an exact runtime type instead would refuse a value
        pydantic can make correct, for no gain.
        """
        evaded = ToolFailure.model_construct(kind="rate_limited", message=f"  {REPORTED_MESSAGE}  ")
        invoker.register(tool(), Raiser(tampered(failure=evaded)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.RATE_LIMITED
        assert result.failure.kind.retryable is True, "a member, not the string it arrived as"
        assert result.failure.message == REPORTED_MESSAGE

    async def test_a_dumped_failure_that_differs_crosses_as_the_round_trips_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §6's stated limit, pinned as a limit.

        A subclass may override ``model_dump()`` to return something other than
        its own fields, and the value that crosses is the dumped one. Not a hole:
        the tool authored both accounts and could have raised the dumped failure
        directly, and a seam arbitrating between two stories a tool tells about
        its own failure would be settling a dispute neither side has an interest
        in — closing it would mean refusing subclasses, which buys nothing and
        forbids a legitimate integration-side base class.
        """
        substitute = {"kind": ToolFailureKind.REFUSED, "message": "the upstream declined it"}
        invoker.register(tool(), Raiser(tampered(failure=dumped(lambda: substitute))))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure == ToolFailure(
            kind=ToolFailureKind.REFUSED, message="the upstream declined it"
        )

    @pytest.mark.parametrize(
        "build",
        [
            lambda: tampered(failure=None),
            lambda: tampered(failure="rate_limited"),
            lambda: tampered(failure=Impostor(kind=ToolFailureKind.RATE_LIMITED, message="x")),
            lambda: tampered(failure=DELETED),
            lambda: tampered(failure=ToolFailure.model_construct(kind="no such kind", message="x")),
            lambda: tampered(failure=ToolFailure.model_construct(kind=ToolFailureKind.REFUSED)),
            lambda: unreadable("failure"),
        ],
        ids=[
            "none",
            "a-string",
            "another-class",
            "deleted",
            "a-kind-naming-no-member",
            "a-missing-field",
            "an-accessor-that-raises",
        ],
    )
    async def test_a_malformed_payload_is_refused_for_the_seams_own_internal(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        build: Callable[[], ClassifiedToolError],
    ) -> None:
        """ADR-0032 §6, across every shape the attribute can take.

        ``isinstance`` is not evidence that a pydantic model was validated, and
        neither is an annotation: an exception's attributes are ordinary
        attributes. Each of these comes back ``INTERNAL``, and specifically **not**
        as an ``AttributeError`` or a ``ValidationError`` escaping ``invoke``. The
        deletion case is the one a natural implementation fails — reading
        ``exc.failure`` directly raises where the rule requires a result — and a
        suite testing only ``None`` certifies it. The accessor that raises is the
        one that fails against a guard placed only around the round-trip.
        """
        invoker.register(tool(), Raiser(build()))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert await trail.open_invocations(decision_id=call.decision.id) == [], (
            "the completion is written, so nothing escaped in place of the result"
        )

    @pytest.mark.parametrize(
        "build",
        [
            lambda committed: tampered(failure=None, committed=committed),
            lambda committed: tampered(failure=DELETED, committed=committed),
            lambda committed: tampered(
                failure=ToolFailure.model_construct(kind="no such kind", message="x"),
                committed=committed,
            ),
            lambda committed: unreadable("failure", committed=committed),
        ],
        ids=["none", "deleted", "a-kind-naming-no-member", "an-accessor-that-raises"],
    )
    @pytest.mark.parametrize(
        ("committed", "expected"),
        [(True, ToolOutcome.INDETERMINATE), (False, ToolOutcome.FAILED)],
        ids=["may-have-committed", "did-not"],
    )
    async def test_the_fact_outlives_a_refused_payload(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        build: Callable[[bool], ClassifiedToolError],
        committed: bool,
        expected: ToolOutcome,
    ) -> None:
        """ADR-0032 §6, for §3's reason applied twice — and it is the whole point
        of reading the two attributes independently.

        A tool that built its ``ToolFailure`` with ``model_construct`` may still
        have had its request land upstream. Dropping the fact would make §6 the
        one path in the ADR that resolves an ambiguity in the direction ADR-0014
        §4 refuses to guess in, and would do so on the malformed input most likely
        to come from a *careless* integration rather than an adversarial one. So a
        side-effecting non-``NATURAL`` tool raising a garbage payload with the
        fact ``True`` gets ``INDETERMINATE`` with an ``INTERNAL`` kind: the seam
        says "this tool is broken **and** we do not know whether it acted", which
        is both of the true things.

        The accessor arm is the one that pins the independence itself — an
        implementation refusing the whole carrier on any defect passes every other
        case in this list.
        """
        invoker.register(tool(), Raiser(build(committed)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is expected
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL

    @pytest.mark.parametrize(
        "build",
        [
            lambda: tampered(effect_may_have_committed="yes"),
            lambda: tampered(effect_may_have_committed=1),
            lambda: tampered(effect_may_have_committed=DELETED),
            lambda: unreadable("effect_may_have_committed"),
        ],
        ids=["a-string", "an-int", "deleted", "an-accessor-that-raises"],
    )
    async def test_a_malformed_fact_refuses_the_whole_carrier(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        build: Callable[[], ClassifiedToolError],
    ) -> None:
        """§6's converse, and the asymmetry is the rule rather than a lapse in it.

        A bad payload costs the *kind*; a bad fact costs the *carrier*. Losing the
        fact would be unsafe, because the lost value might be ``True`` and the
        loss records a possible commit as certainly-nothing-happened — so it is
        never inferred. Losing the kind is safe, because what a refused kind costs
        is a ``retryable=True`` the seam has no reason to trust: a carrier missing
        a *required, keyword-only* argument never went through ``__init__``, so
        nothing about it was checked, and reporting a confident ``RATE_LIMITED``
        off it would be the seam authorising a retry on the strength of an object
        assembled around its own constructor.

        The subject is a side-effecting non-``NATURAL`` tool, whose
        ``interrupted_outcome`` is ``INDETERMINATE`` — so ``FAILED`` here is the
        rule being applied and not the declaration answering for it.
        """
        invoker.register(tool(), Raiser(build()))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED, "whatever the payload said"
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.failure.message != REPORTED_MESSAGE

    async def test_a_carrier_whose_payload_dump_raises_is_internal(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §6's guard, which every other malformed case passes without.

        ``isinstance`` admits a subclass, so ``model_dump()`` is a dispatch to a
        method a tool may have overridden — and it runs from inside an ``except``
        body, where no sibling clause catches what it raises. The durable form of
        the rule: **the seam's total failure path may not itself contain an
        unguarded call into tool-supplied code.**
        """

        def explode() -> Mapping[str, object] | None:
            msg = "the failure refuses to be dumped"
            raise RuntimeError(msg)

        invoker.register(tool(), Raiser(tampered(failure=dumped(explode))))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_base_exception_from_the_payloads_dump_propagates(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """Paired with the case above, so the guard is not a bare ``except
        BaseException``.

        ADR-0029 §3 requires a ``BaseException`` to propagate unchanged
        everywhere else, and §6 takes that exemption identically: a process being
        torn down is not a tool failure.
        """

        def interrupt() -> Mapping[str, object] | None:
            raise KeyboardInterrupt

        invoker.register(tool(), Raiser(tampered(failure=dumped(interrupt))))
        call = call_for(tool())
        await trail.record(call.decision)

        with pytest.raises(KeyboardInterrupt):
            await invoker.invoke(call, timeout=PATIENT)

    async def test_each_of_the_carriers_attributes_is_read_exactly_once(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """One read per attribute, captured into a local before it is judged.

        The caller must not find two instructions to choose between: a carrier
        whose first access succeeds and whose second raises or answers differently
        would otherwise put a different value on the ``ToolResult`` than the one
        the seam judged. The counts are the assertion — a matrix of hostile
        *first* accesses alone is satisfiable by an implementation that reads
        ``exc.failure`` a second time when it builds the result.
        """
        raising, seen = watched_carrier(
            committed=True, cost=CLASSIFIED_COST, intercept=hostile_after_the_first
        )
        invoker.register(tool(), Raiser(raising))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert seen.counts == {"failure": 1, "effect_may_have_committed": 1, "incurred_cost": 1}
        assert result.outcome is ToolOutcome.INDETERMINATE
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.RATE_LIMITED
        assert result.incurred_cost == CLASSIFIED_COST

    async def test_a_payload_dump_that_cancels_the_invoking_task_is_not_answered_with_a_result(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §4's re-read, and nothing else pins it.

        Every other carrier case leaves the delta alone, so an implementation
        checking interruption once on entry to the handler passes all of them.
        This ``model_dump()`` cancels the invoking task and then returns **valid**
        data, so only a check made *after* the read can see it — otherwise a
        ``FAILED`` result leaves a task carrying a pending cancellation, which is
        rank 1 violated by the mechanism §6 introduced.
        """

        def cancel_and_answer() -> Mapping[str, object] | None:
            cancel_this_task()
            return None

        invoker.register(tool(), Raiser(tampered(failure=dumped(cancel_and_answer))))
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        with pytest.raises(asyncio.CancelledError):
            await task

        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_payload_dump_that_cancels_and_then_raises_is_not_answered_either(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The same carrier on the guard's **fallback** path (§4, §9).

        The ``INTERNAL`` §6 synthesises is itself a result the re-read must
        precede. An implementation re-reading only after a *successful*
        translation passes the case above and still returns a result from a
        cancelled task — which is the whole failure "before **any** result" exists
        to name.
        """

        def cancel_and_explode() -> Mapping[str, object] | None:
            cancel_this_task()
            msg = "the failure refuses to be dumped"
            raise RuntimeError(msg)

        invoker.register(tool(), Raiser(tampered(failure=dumped(cancel_and_explode))))
        call = call_for(tool())
        await trail.record(call.decision)

        task = asyncio.create_task(invoker.invoke(call, timeout=PATIENT))
        with pytest.raises(asyncio.CancelledError):
            await task

        (completion,) = await completions(trail)
        assert completion.outcome is ToolOutcome.INDETERMINATE
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    # --- ADR-0195 §3, §4: what a classified failure reports it cost ---------

    async def test_a_classified_failure_lands_its_figure_with_the_kind_unchanged(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0195 §11's first owed case, and the clause it exists for.

        A failed call may genuinely have cost money — an upstream that billed a
        request it then rejected, a message accepted and not delivered — and
        ADR-0194 §2 requires such a row to be counted, "including one whose
        outcome is ``INDETERMINATE``". Without this field a priced integration
        would poison its own period on every failure, so this is what stops the
        channel working only while nothing goes wrong.
        """
        invoker.register(tool(), Raiser(carrier(committed=True, cost=CLASSIFIED_COST)))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.outcome is ToolOutcome.INDETERMINATE, "the figure changes no ruling"
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.RATE_LIMITED
        assert result.incurred_cost == CLASSIFIED_COST
        (completion,) = await completions(trail)
        assert completion.incurred_cost == CLASSIFIED_COST

    async def test_a_classified_failure_reporting_nothing_records_an_unknown_cost(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The control the case above is only meaningful against (ADR-0195 §3).

        ``incurred_cost`` is **defaulted** where ``effect_may_have_committed``
        deliberately is not: silence about a price already means "no figure" and
        is the fail-closed direction under ADR-0194 §2, while silence about a side
        effect would assert one.
        """
        invoker.register(tool(), Raiser(carrier()))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

    @pytest.mark.parametrize(
        "build",
        [
            lambda: tampered(cost=ToolCost.model_construct(basis=CostBasis.PER_CALL)),
            lambda: unreadable("incurred_cost"),
            lambda: tampered(cost=dumping(refuses_to_dump)),
        ],
        ids=["fails-revalidation", "an-accessor-that-raises", "a-dump-that-raises"],
    )
    async def test_a_classified_cost_that_does_not_survive_is_discarded_alone(
        self,
        invoker: InvocableToolRegistry,
        trail: FakeAuditTrail,
        build: Callable[[], ClassifiedToolError],
    ) -> None:
        """ADR-0195 §11's second owed case: a malformed cost costs the **cost**.

        The failure and ``effect_may_have_committed`` stand and the row records
        ``UNKNOWN``, which is that field's own pessimistic direction — ADR-0194 §2
        already refuses to read ``UNKNOWN`` as zero. Every step of the read is
        tool-authored code, so all three defects resolve identically.
        """
        invoker.register(tool(), Raiser(build()))
        call = call_for(tool())

        result = await invoked(invoker, trail, call, timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.RATE_LIMITED, "the classification stands"
        assert result.failure.message == REPORTED_MESSAGE
        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)
        assert await trail.open_invocations(decision_id=call.decision.id) == []

    async def test_a_refused_payload_keeps_a_reported_cost_that_is_sound(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """ADR-0032 §6's independence, extended to the third attribute.

        The carrier itself went through ``__init__``, so the figure is an ordinary
        attribute revalidated on its own: a malformed payload costs the *kind*, a
        malformed cost costs the *cost*, and neither costs the other. An
        implementation refusing everything on any defect passes the plain case and
        fails this one.
        """
        invoker.register(tool(), Raiser(tampered(failure=None, cost=CLASSIFIED_COST)))

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.incurred_cost == CLASSIFIED_COST
        (completion,) = await completions(trail)
        assert completion.incurred_cost == CLASSIFIED_COST

    async def test_a_refused_carrier_discards_its_reported_cost_with_it(
        self, invoker: InvocableToolRegistry, trail: FakeAuditTrail
    ) -> None:
        """The converse, and it turns on **which** defect was found (ADR-0195 §4).

        ADR-0032 §6 refuses "the *whole* carrier" where the fact does not
        validate, on the ground that such an object never went through
        ``__init__`` and so nothing about it was checked. A price read off that
        same unchecked object is a figure stated by the very object whose kind is
        being refused for that reason, so it goes with it and the row records
        ``UNKNOWN`` — that field's own pessimistic direction. ADR-0195 §4 states
        the three costs in the same breath: a malformed payload costs the kind, a
        malformed fact costs the carrier, a malformed cost costs the cost.
        """
        invoker.register(
            tool(), Raiser(tampered(effect_may_have_committed="yes", cost=CLASSIFIED_COST))
        )

        result = await invoked(invoker, trail, call_for(tool()), timeout=PATIENT)

        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INTERNAL
        assert result.incurred_cost is None
        (completion,) = await completions(trail)
        assert completion.incurred_cost == ToolCost(basis=CostBasis.UNKNOWN)

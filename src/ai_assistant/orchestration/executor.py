"""The executor half of the tool-invocation contract (ADR-0029 §8).

:class:`StepExecutor` is the pipeline's ``execute`` stage: it claims a plan step,
runs one authorised :class:`~ai_assistant.core.types.ToolCall` through an
injected :class:`~ai_assistant.core.protocols.ToolInvoker`, and commits what came
back. Everything it knows about tools it learns through two Protocols —
``ToolRegistry`` and ``ToolInvoker`` — so nothing here imports `tools/`
(CLAUDE.md golden rule 1), and the interrupted-call rule it needs is
:attr:`~ai_assistant.core.types.ToolDefinition.interrupted_outcome`, in ``core``,
rather than a second copy of a safety-critical classification (ADR-0031 §1).

Three rules shape the whole module and are worth stating before the code:

- **The claim precedes the call** (ADR-0014 §4). The ``→ RUNNING`` transition is
  committed before ``invoke`` is reached, so the compare-and-swap in ADR-0014 §5
  is what stops two workers acting. Everything that can go wrong afterwards
  therefore goes wrong against a step that is already durably ``RUNNING``, which
  is why every exit path here commits something.
- **Retry is scheduled only from a ``ToolResult``, never from an exception**
  (ADR-0029 §8). The three exception paths write ``StepFailure(kind=None)``, so a
  ``FAILED`` step whose ``failure.kind`` is ``None`` provably had no
  ``ToolResult`` to read a retry decision from (ADR-0039 §3) — the rule is
  readable off the record now, not only inferable from this loop's shape.
  "Never retried" is still a property of that shape and not enforced by the
  transition graph; what changed is that the record shows it.
- **Classification reads the registry's declaration, captured before the call**
  (ADR-0029 §4). Never ``call.request.tool``, which a ``__dict__`` write could
  flip to read-only mid-flight and turn a possible side effect into
  certainly-nothing-happened.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, assert_never

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    AssistantError,
    PlanningError,
    RetriesExhaustedError,
    SpendError,
    ToolBindingError,
)
from ai_assistant.core.types import (
    Disposition,
    EffectClaim,
    Idempotency,
    StepFailure,
    StepStatus,
    StepTransition,
    ToolCall,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.effects import (
    condition_elements,
    conditions_hold,
    verification_holds,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import PlanStore, ToolInvoker, ToolRegistry
    from ai_assistant.core.types import (
        EffectKey,
        EffectOutcome,
        ExecutionState,
        FrozenJsonValue,
        StepExecution,
        ToolDefinition,
    )

_log = structlog.get_logger(__name__)

#: Total over :class:`ToolOutcome`, so the result mapping needs no default
#: branch and a member added later raises rather than acquiring a status nobody
#: chose — the shape ``ToolFailureKind.retryable`` uses for the same reason.
_STATUS_BY_OUTCOME: Mapping[ToolOutcome, StepStatus] = {
    ToolOutcome.SUCCEEDED: StepStatus.SUCCEEDED,
    ToolOutcome.FAILED: StepStatus.FAILED,
    ToolOutcome.INDETERMINATE: StepStatus.INDETERMINATE,
}

#: What a seam rejection records. Authored here rather than taken from the
#: exception: ``StepFailure.message`` is Tier 2 operator text bound for a log,
#: and a ``ToolBindingError``'s own message interpolates identifiers off an
#: untrusted call (ADR-0029 §3, ADR-0004 §5). No tool classified this, so the
#: paired ``kind`` is ``None`` (ADR-0039 §3).
_REFUSED = (
    "the invoker refused the call before the tool ran: it is not the call that was authorised"
)

#: What the seam's own claim-path exit records (ADR-0192 §1, ADR-0034 §1). Every
#: ``AssistantError`` that leaves ``invoke`` is a **claim-path** one: the claim is
#: appended before the callable is entered, and every completion-path failure is
#: absorbed at the seam, which returns the call's own result rather than raising
#: (ADR-0192 §3). So the callable was never reached, ``FAILED`` is the honest
#: record on ADR-0034 §1's second ground, and ``INDETERMINATE`` would report a
#: call that provably never started as one that may have acted. Authored here for
#: :data:`_REFUSED`'s reason: an ``AuthorisationSpentError``'s own message names
#: the decision, and ``StepFailure.message`` is Tier 2 operator text (ADR-0004 §5,
#: ADR-0031 §5). ``kind`` is ``None`` — no tool classified it — so ADR-0029 §5
#: never retries it either.
_UNCLAIMED = (
    "the invoker could not record the call against its authorisation, so the tool was not reached"
)

#: What a spend refusal records when its own account cannot be read.
#: :func:`_spend_refusal` records the error's own message, so this stands in for
#: the two ways a raiser can leave nothing recordable — a ``__str__`` that raises,
#: and text ``StepFailure`` rejects — neither of which may strand the step durably
#: ``RUNNING``. It keeps the *ground*, which is the whole point of separating this
#: path: a budget stop must not read as an internal fault (ADR-0194 §4).
_UNSTATED = (
    "the invocation was refused on spend grounds before the tool was reached, and the "
    "refusal's own account could not be read"
)

#: What a cancelled call records, on both the ``FAILED`` and the
#: ``INDETERMINATE`` branch. ``StepFailure`` is now accepted on both (ADR-0039
#: §2), so the ``INDETERMINATE`` branch records this text rather than discarding
#: it — the change that closes #208. ``kind`` is ``None``: no tool classified it.
_CANCELLED = "the invocation was cancelled before it completed"

#: What a claim closed before the tool could be reached records. ``FAILED``
#: rather than ``INDETERMINATE`` for ADR-0029 §8's reason: nothing happened, and
#: ``INDETERMINATE`` is the state whose whole meaning is ignorance.
_UNSTARTED = "the attempt ended after the claim and before the tool was reached, so nothing ran"

#: Stands in when a non-``SUCCEEDED`` result somehow carries no failure.
#: ``ToolResult``'s own validator makes that unconstructable; this exists so the
#: mapping stays total against a value tampered past ``frozen=True``.
_UNEXPLAINED = "the tool reported a failure with nothing in it"

#: What a returned result that does not survive revalidation records. The seam
#: is contracted to return a valid ``ToolResult`` (ADR-0029 §3) and the executor
#: records it verbatim (ADR-0039 §6), but ``frozen=True`` refuses
#: ``result.outcome = ...`` and does nothing about
#: ``result.__dict__["outcome"] = ...`` — the same ``__dict__``-bypass ADR-0018
#: §3 puts inside the threat model for the inbound call. Recording such a value
#: verbatim would raise past the claim (:func:`_detached_result`), so the step is
#: closed ``INDETERMINATE`` with this instead (ADR-0051, :meth:`_discard_unusable`).
#: ``kind`` is ``None``: no tool classified it (§3).
_UNUSABLE = "the invoker returned a result that did not survive revalidation, so it is unusable"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _detached(call: ToolCall) -> ToolCall:
    """Revalidate and detach the call before any durable record names it.

    **The executor is handed a caller's object and holds it across two awaits**
    — the registry lookup and the claim's own commit — before the seam ever sees
    it. ``frozen=True`` refuses ``call.request = ...`` and does nothing about
    ``call.__dict__["request"] = ...``, and ADR-0018 §3, ADR-0018 §4 and
    ADR-0029 §2 all put that bypass inside this repository's threat model rather
    than outside it. So a call substituted while the claim is in flight would be
    claimed as one authorised call and executed as another: ``invoke`` would
    revalidate at *its* moment and run the second, ADR-0029 §8's "``bound_tool``
    must equal ``call.request.tool.id``" would name the first, and the
    interrupted-call classification would read the first tool's declaration
    about the second tool's possible side effect.

    Taking the snapshot **before** the claim closes that: the registry lookup,
    the claim, the invocation and the retry classification all read one value
    nothing else holds a reference to. This does not replace the seam's own
    revalidation (ADR-0029 §2's first check) and is not meant to — the seam
    cannot trust its caller either, and each guard is total over what it is
    handed.

    Raises:
        ToolBindingError: If the call does not survive revalidation. Raised
            before the claim, so an unusable call touches no durable state at
            all — the same placement, and the same reason, as
            :func:`_checked_timeout`.
    """
    try:
        return ToolCall.model_validate(call.model_dump())
    except ValidationError as exc:
        msg = "the call did not survive revalidation, so it is not the call that was authorised"
        raise ToolBindingError(msg) from exc


def _detached_result(result: ToolResult) -> ToolResult | None:
    """Revalidate and detach the result the seam returned, or reject it.

    The mirror of :func:`_detached` for the seam's *output*. ADR-0029 §3 makes
    :meth:`~ai_assistant.core.protocols.ToolInvoker.invoke` return a valid
    ``ToolResult`` and ADR-0039 §6 has the executor record it verbatim — but
    ``frozen=True`` refuses ``result.outcome = ...`` and does nothing about
    ``result.__dict__["outcome"] = ...``, the same ``__dict__``-bypass ADR-0018
    §3 already puts inside this repository's threat model for the inbound
    ``ToolCall``. A result tampered that way — ``outcome`` a non-member,
    ``failure`` an object without ``kind``/``message`` — would raise a
    ``KeyError`` out of :data:`_STATUS_BY_OUTCOME` or an ``AttributeError`` out
    of :func:`_failure_of`, and both raise **after** the claim, stranding the
    step durably ``RUNNING`` for recovery to read as ``INDETERMINATE`` about a
    call that did in fact finish.

    Unlike :func:`_detached`, this returns ``None`` rather than raising, because
    of where it sits: the claim precedes it, so an unusable result must become a
    committed close (:meth:`StepExecutor._discard_unusable`) rather than an
    escaping exception — the same reason :meth:`StepExecutor._refuse` commits the
    seam's own rejection instead of propagating it. Detaching also means the
    value that reaches the commit is one nothing else holds a reference to, so it
    cannot be edited between revalidation and the write.

    **Only an exact ``ToolResult`` is trusted, and it is serialized through the
    *class*, never the instance.** Two ``__dict__`` bypasses have to be closed,
    not one. A *subclass* could override ``model_dump``/validators to forge or to
    raise, so the type is checked before anything else — ``type(result) is
    ToolResult``, not ``isinstance`` — and a subclass, a ``None`` or any other
    object a non-conforming seam returned fails it. But an *exact* ``ToolResult``
    can still shadow the method per-instance: ``result.__dict__["model_dump"]`` is
    an ordinary attribute, and a plain method loses to the instance dict, so
    ``result.model_dump(...)`` would call an injected callable returning a
    valid-but-false ``{"outcome": "succeeded", ...}`` for a genuinely
    ``INDETERMINATE`` result — a forged commit past the type gate. So the
    serialization goes through ``ToolResult.__pydantic_serializer__`` — the class
    serializer, resolved on the class and reading ``result``'s *field values*
    directly — which consults no instance attribute and is inert to a shadowed
    ``model_dump`` or ``__pydantic_serializer__``. ADR-0029 §3 has the seam return
    a ``ToolResult``; the executor records the contract type, serialized by the
    contract's own code.

    **The round-trip is then total over a genuine instance tampered past
    ``frozen=True``.** The class serializer reads the actual field values, so a
    ``__dict__``-injected ``outcome`` or ``failure`` is what ``model_validate``
    sees and rejects; a field holding an object whose own serialization raises is
    caught. Every ordinary exception from the round-trip is reported as "unusable"
    rather than allowed to strand the claim.

    **``asyncio.CancelledError`` is caught too, and only because this body is
    synchronous.** The event loop delivers a genuine task cancellation at an
    ``await``, and there is none here — the serialize-then-validate is synchronous.
    A ``CancelledError`` surfacing from it can therefore only have been raised by
    the untrusted value's own code, i.e. forged, and letting it propagate would
    strand the claimed step by masquerading as a teardown that is not happening. A
    *real* cancellation of the executing task is unaffected: it is delivered at the
    next ``await`` — the commit — where :meth:`_commit_shielded` still lands the
    write and re-raises. ``KeyboardInterrupt`` and ``SystemExit`` are deliberately
    *not* named, so a real process signal still propagates. This does not replace
    the seam's contract to return a valid result and is not meant to.

    Returns:
        A revalidated, detached copy, or ``None`` if the returned value is not
        exactly a ``ToolResult`` or does not survive revalidation.
    """
    if type(result) is not ToolResult:
        # A subclass's `model_dump`/validators are not the contract's, and could
        # forge or raise; a non-`ToolResult` is not a result at all. Rejected
        # before any overridable method is called.
        return None
    try:
        # Serialize via the *class* serializer, never `result.model_dump`: a plain
        # method loses to `result.__dict__["model_dump"]`, so an exact ToolResult
        # could shadow it to forge a valid dict past the type gate. The class
        # serializer reads the field values and consults no instance attribute.
        # `warnings=False`: a `__dict__`-tampered enum serializes with a
        # `PydanticSerializationUnexpectedValue` warning that is noise here — the
        # `model_validate` is what rejects it, by return.
        dumped = ToolResult.__pydantic_serializer__.to_python(result, warnings=False)
        return ToolResult.model_validate(dumped)
    except Exception, asyncio.CancelledError:
        # Total over a genuine instance tampered past `frozen=True` (see
        # docstring). CancelledError is named because this body is synchronous:
        # one surfacing here is forged by an injected field, not a real teardown,
        # and must become "unusable" rather than strand the claim.
        return None


@dataclass(slots=True)
class CallableReach:
    """Whether this drive got as far as the tool's own callable (ADR-0264 §2, §3).

    **The executor's own pre-callable fact, written through rather than returned**, on
    the shape ``_SearchCounts`` already has in
    :mod:`ai_assistant.orchestration.reads` and for the same reason: the three exits
    ADR-0192 §1 places *before* the callable are caught inside :meth:`StepExecutor._run_once`
    and never leave it, so a caller that wanted the fact back would have to read it off
    the ``ExecutionState`` those exits committed — and ADR-0192 §4 rules that no such
    value carries it.

    **It is not** ``Disposition.EXECUTED`` **and no lane reads it as one** (ADR-0264
    §2, §3). ``StepRunner`` returns ``EXECUTED`` for those three windows as well as for
    a call that reached the callable, which is exactly why §2 states the contribution
    over this fact instead: an implementation gating on the disposition would report a
    refused spend as a send that may have left.

    **It establishes no contact** (§3). What a ``True`` here buys is
    :attr:`~ai_assistant.core.types.OutboundReach.INDETERMINATE` — this system cannot
    say the turn reached nothing — and never
    :attr:`~ai_assistant.core.types.OutboundReach.REACHED`, because
    ``ToolImplementation`` returns ``FrozenJson`` with no channel for a transmission
    fact and ADR-0192 §4 says so in terms.

    Attributes:
        reached: Whether the seam was entered at all — set once
            :meth:`~ai_assistant.core.protocols.ToolInvoker.invoke` has returned or
            raised from inside the callable, and **sticky**. Stickiness is the whole of
            the retry story: ADR-0029 §5 re-claims only after a *result* came back, so a
            second attempt that is refused before the callable must not unmake what the
            first attempt reached. ``False`` where every attempt exited in one of
            ADR-0192 §1's three windows, which is the executor establishing that the
            call provably never reached the callable.
    """

    reached: bool = False


@dataclass(frozen=True, slots=True)
class Dispatch:
    """What one :meth:`StepExecutor.execute` did with the step (ADR-0259 §2).

    **A value rather than a bare ``ExecutionState``, because §2 gives the executor two
    outcomes that commit nothing** — the step keeps the status it was entered at, and
    the state alone cannot say whether that is a refusal or a step nobody claimed. It
    is an `orchestration`-local frozen dataclass on :class:`StepDisposition`'s own
    terms: a stage type no Protocol returns, so ADR-0085 §5's promoted-surface walk
    never reaches it. ``StepExecutor.execute`` gains **no argument** for any of this
    (§2); what widened is what it hands back.

    Attributes:
        state: Durable execution state after the last transition this drive
            committed — the caller's own ``state`` unchanged on the two that commit
            none.
        refused: :attr:`~ai_assistant.core.types.Disposition.EFFECT_ALREADY_CLAIMED`
            where the goal had already claimed this act,
            :attr:`~ai_assistant.core.types.Disposition.EFFECT_UNSCOPED` where a
            side-effecting step named no intended action, and ``None`` where the drive
            was not refused on either ground. **No other member ever rides here**: it
            carries the two §2 mints and nothing about what the seam did, which is
            ``state``'s to say.
        satisfied: Whether this step was **satisfied from an earlier holder** (§2)
            rather than dispatched — committed ``→ SUCCEEDED`` from the status it was
            entered at, with the store copying the holder's own ``output``. Nothing was
            invoked, no authorisation was spent and ``attempts`` did not move, so the
            two facts a caller needs of such a step — that it is the turn's
            ``satisfied_from_earlier`` entry, and that it recorded no fresh output for
            ADR-0267 §4 to read a price from — both hang here.
    """

    state: ExecutionState
    refused: Disposition | None = None
    satisfied: bool = False


def _checked_timeout(timeout: object) -> timedelta:
    """Refuse a deadline *before* the claim is committed (ADR-0029 §4, §8).

    Not a second copy of the seam's guard, and the difference between them is
    what each is protecting. ``invoke`` checks the value to protect the
    **callable** — the annotation is not the enforcement, and
    ``asyncio.timeout(None)`` is no deadline at all in the one method whose
    contract is that there is always one. This checks it to protect the
    **claim**.

    The claim precedes the call, so a ``ValueError`` raised inside ``invoke``
    would arrive *after* the step is durably ``RUNNING``, and stranding it there
    has recovery record ``INDETERMINATE`` — "we cannot tell whether it acted" —
    about a call whose coroutine that same guard guarantees was never created.
    That is the stranding §8 spells out for ``ToolBindingError``, reached through
    the other exception ``invoke`` is contracted to raise before the tool is
    touched. Refusing here means no durable state is touched at all, which is
    better than committing an honest ``FAILED`` after the fact.

    Raises:
        ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
    """
    if not isinstance(timeout, timedelta):
        msg = f"timeout must be a timedelta, got {type(timeout).__name__}"
        raise ValueError(msg)
    if timeout <= timedelta(0):
        msg = f"timeout must be strictly positive, got {timeout}"
        raise ValueError(msg)
    return timeout


class StepExecutor:
    """Runs one claimed plan step through the invocation seam (ADR-0029 §8).

    Args:
        plans: Durable planning state. Every transition this executor makes goes
            through :meth:`~ai_assistant.core.protocols.PlanStore.commit_transition`,
            which is the only write path and the compare-and-swap the claim
            depends on.
        registry: Where the *trusted* declaration comes from. Read once, before
            the call, because the seam's binding checks all run before the
            callable starts and nothing re-examines a declaration afterwards.
        invoker: The seam. **The composition root must inject one object as both
            ``registry`` and ``invoker``** (ADR-0029 §8): no Protocol can enforce
            it, and two genuinely different bindings under one id is the wiring
            ADR-0016 §7 calls unrecoverable.
        now: Clock used to measure the idempotency window; injectable so retry
            tests are deterministic. Guarded by
            :func:`~ai_assistant.core.clock.checked_clock`. A *reading* that is
            not a positive elapsed duration lapses the window
            (:meth:`_window_is_open`); a clock that *raises* is a wiring bug and
            is translated at this boundary (:meth:`_reading`, ADR-0034 §2).
    """

    def __init__(
        self,
        *,
        plans: PlanStore,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        now: Clock = _utcnow,
    ) -> None:
        """Wire the executor from injected contracts."""
        self._plans = plans
        self._registry = registry
        self._invoker = invoker
        self._clock = checked_clock(now, owner="StepExecutor")

    async def execute(  # noqa: PLR0913 — the execution, the step, the authorised call, the attempt the claim is made under and the budget, plus ADR-0264 §2's observer; each is a distinct fact about the act
        self,
        state: ExecutionState,
        *,
        step_id: str,
        call: ToolCall,
        attempt_id: str,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
        reach: CallableReach | None = None,
    ) -> Dispatch:
        """Claim ``step_id``, run ``call``, and commit the outcome.

        Retries while ADR-0029 §5 permits one — the failure kind is retryable
        **and** repeating is safe — re-claiming the step each time, which is what
        spends an attempt against the tracker's ceiling.

        Args:
            state: The execution as currently stored. Its ``version`` is what the
                first claim is computed against.
            step_id: Which step to run. It must be the step ``call`` is
                authorised for: ADR-0021 §1 binds an approval to the step, and
                accepting the id twice without comparing them would let one
                step's approval claim another's.
            call: The authorised call. It is revalidated and **detached** first
                (:func:`_detached`), and every later step reads that snapshot —
                the caller's object stays mutable across the awaits in between.
                Its ``request.tool.id`` becomes ``bound_tool`` and its
                ``decision.id`` becomes ``approval_ref``, so the durable record
                describes the call that actually ran (ADR-0029 §8).
            attempt_id: The :class:`~ai_assistant.core.types.GoalAttempt` every claim
                this executor makes is made under (ADR-0255 §3) — including each
                **re-claim** a retry spends, since each is its own ``→ RUNNING``
                transition. It is passed to the ``StepTransition`` and read for
                nothing else: it selects no tool, fills no argument and reaches no
                gate, so **no collaborator is added** and this executor gains no
                ``PlanStore`` read it did not already have (ADR-0058, ADR-0254 §13).
            timeout: How long the seam may wait, per attempt. The caller's
                budget, not the tool's property (ADR-0029 §4).
            reach: ADR-0264 §2's pre-callable observer, written through as the drive
                runs (:class:`CallableReach`). ``None``, the default, observes nothing
                and changes no behaviour — it is what every caller that does not carry
                an outbound statement passes, and what keeps this signature honest about
                the fact being an observation rather than an input.

        Returns:
            A :class:`Dispatch`: the execution state after the last transition this
            executor committed, together with ADR-0259 §2's two refusals and whether
            the step was satisfied from an effect the goal had already completed.

        Raises:
            CancelledError: If the executing task is cancelled from outside. The
                step is committed first and the cancellation then propagates,
                because swallowing it would break structured concurrency and
                shutdown. What is committed depends on where the cancellation
                landed: during the invocation, the interrupted-call
                classification (:meth:`_commit_through_cancellation`); during a
                terminal write, the outcome already established, since by then
                the answer is known and discarding it would have recovery report
                ignorance over it (:meth:`_finish`).
            PlanningError: If a transition is rejected, the store is stale, or
                the injected clock's reading is not a conforming one — a wiring
                bug rather than a pessimistic measurement (:meth:`_reading`).
            ToolBindingError: If the call does not survive revalidation
                (:func:`_detached`), is authorised for a different plan step than
                ``step_id``, or is authorised for a different execution than
                ``state`` (ADR-0044 §1). All are raised before the claim, so they
                leave no durable state — unlike the seam's own refusal, which
                arrives after it and is committed ``FAILED``.
            ValueError: If ``timeout`` is not a strictly positive ``timedelta``.
                Checked **before** the claim, so a deadline the seam would
                refuse never leaves a step durably ``RUNNING``
                (:func:`_checked_timeout`).

        **Nothing that fails between the claim and the callable leaves a step
        durably ``RUNNING``** (ADR-0034 §1). A cancelled claim, a raising clock, a
        ``ToolBindingError`` and every other ``AssistantError`` the seam's own
        claim raises all close it ``FAILED``: nothing ran, and recovery would
        otherwise record
        ``INDETERMINATE`` about a call that provably never started.
        """
        _checked_timeout(timeout)
        # One snapshot, taken before anything durable names the call, and used
        # for the lookup, the claim, the invocation and the classification. See
        # `_detached`: the caller's object is mutable across every await here.
        authorised = _detached(call)
        if authorised.request.step_id != step_id:
            # ADR-0021 §1 binds an approval to the tool, the parameters **and**
            # the step, and `authorises` compares all three — but it compares
            # them against the call's own `step_id`, not against the step this
            # executor was asked to run. Taking the id twice is what reopens
            # that: the claim would record a decision that authorised a
            # different step, and ADR-0014 §4's "every executed step must name
            # the decision that authorised it" would be satisfied by a pointer
            # to somewhere else. Refused before the claim, so nothing durable
            # names it (`_detached`).
            msg = (
                "the call is authorised for a different plan step, so claiming this one "
                "would name a decision that approved something else"
            )
            raise ToolBindingError(msg)
        if authorised.request.execution_id != state.id:
            # ADR-0044 §1's third seam. `authorises` binds the decision to the
            # *request*, and a `ToolCall` whose request and decision both name
            # execution A is internally consistent — but nothing there stops that
            # call being handed to `execute(state=B, …)`. The executor already
            # checks `step_id` against the step it was asked to run; this checks
            # `execution_id` against the *execution* it was asked to claim, so a
            # call bound to A cannot claim B's identically-shaped step (two
            # executions of one plan parked on the same step, #253). Refused
            # before the claim, so nothing durable names it (`_detached`), exactly
            # like the `step_id` mismatch above.
            msg = (
                "the call is authorised for a different execution, so claiming this step "
                "would run it under an approval made for another execution of the plan"
            )
            raise ToolBindingError(msg)
        trusted = await self._registry.get(authorised.request.tool.id)
        # **ADR-0259 §2's claim, between the read-back and the `→ RUNNING` commit**,
        # and taken **once** rather than at each re-claim: §2 places it immediately
        # before the `PENDING → RUNNING` or `AWAITING_APPROVAL → RUNNING` commit, and a
        # retry's commit is `FAILED → RUNNING`, which is neither. The `FAILED` row of
        # §2's table exists so that a *later plan's* step cannot take the key while
        # this loop's own retry is still coming, not so that the retry re-claims it.
        settled = await self._effect(state, step_id, authorised)
        if settled is not None:
            return settled

        state = await self._claim(state, step_id, authorised, attempt_id)
        # Read *after* the claim, because ADR-0029 §5 measures from "the first
        # attempt of this call" — a slow `commit_transition` is not part of the
        # window, and counting it could consume one before the tool was reached.
        #
        # Anything that goes wrong here is between the claim and the callable, so
        # the step is closed before it leaves: ADR-0034 §1's rule, and the same
        # one §8 states for a `ToolBindingError`. Nothing ran, and leaving a
        # durable `RUNNING` would have recovery record `INDETERMINATE` about it.
        try:
            started = self._reading()
        except BaseException as cause:
            cancelling = isinstance(cause, asyncio.CancelledError)
            if await self._resolve_unstarted(state, step_id, cancelling=cancelling):
                # Absorbed while closing, so it outranks the reason for closing:
                # the caller's teardown must still be observable (ADR-0034 §1).
                msg = f"step {step_id!r} was closed unstarted; its task was cancelled"
                raise asyncio.CancelledError(msg) from None
            raise
        # One observer for the whole drive, so a retry cannot unmake what an earlier
        # attempt reached (:class:`CallableReach`).
        observed = reach if reach is not None else CallableReach()
        while True:
            state, result = await self._run_once(
                state, step_id, authorised, trusted, timeout, observed
            )
            # A `None` result is a terminal close — a seam rejection, a
            # cancellation's classification, or a returned value too tampered to
            # read (`_run_once`) — none of which ADR-0029 §5 retries. A recorded
            # result is retried only while §5 permits: retryable *and* safe.
            if result is None or not self._may_retry(result, trusted, started):
                return Dispatch(state)
            try:
                state = await self._claim(state, step_id, authorised, attempt_id)
            except RetriesExhaustedError:
                # The ceiling is the tracker's (ADR-0014 §4), and hitting it is
                # an ordinary end to this loop rather than a fault: the step is
                # already durably FAILED with the reason the tool gave.
                _log.info("step_retries_exhausted", step_id=step_id)
                return Dispatch(state)

    # --- the effect claim (ADR-0259 §2) ---------------------------------

    async def _effect(self, state: ExecutionState, step_id: str, call: ToolCall) -> Dispatch | None:
        """Take ADR-0259 §2's claim, or say why nothing is dispatched.

        **The claim is one indivisible store write** and this method neither reads
        before it nor decides anything the store could have decided: the row's scope —
        the goal and the intended action — is resolved by the store from the execution's
        own plan, so no argument carries either and none is computed here. What is
        decided here is what §11's L2 gives the stage: which of the five
        :class:`~ai_assistant.core.types.EffectClaim` members was answered, and, on
        ``COMPLETED``, whether the two reuse conditions the *step* carries hold.

        **The unscoped test reads the decision and never the request** (§1). ADR-0266's
        lane sets ``ActionRequest.intended_action`` from the plan step the request
        serves, ``PermissionDecision`` carries the trail's own copy, and ``authorises``
        compares the two as its sixth conjunct — which ``ToolCall``'s validator and
        :func:`_detached`'s revalidation each enforce. So the decision's copy *is* the
        step's, and it is the copy a ``__dict__`` write on ``call.request`` cannot
        move, which is the discipline §1 states for every value of the key itself.
        **Both ways the two could still disagree fail closed**: a decision naming none
        over a stored step that names one returns ``EFFECT_UNSCOPED`` and dispatches
        nothing, and a decision naming one over a stored step that names none meets the
        store's own refusal — §2 closes that window *"at the store as well as at the
        stage"* — which raises and writes nothing.

        Returns:
            ``None`` where the drive goes on to claim the step and call the tool — a
            call that is not side-effecting, and a ``CLAIMED`` answer — and a
            :class:`Dispatch` on every other route, which is terminal for this drive.

        Raises:
            PlanningError: If the store refuses the claim, or refuses the satisfaction
                (:meth:`_satisfy`). Both leave the step at its entry status.
        """
        key = call.effect_key
        if key is None:
            # §1: a call of a tool that is not `side_effecting` has no key, reaches
            # `claim_effect` never, writes no row and is held to nothing here.
            return None
        if call.decision.intended_action is None:
            # §2, answering the question ADR-0265 §4 left open: dispatching here would
            # perform an effect **no row could ever recognise**, so every later plan of
            # the goal would answer `CLAIMED` and repeat it. `claim_effect` is not
            # called at all.
            return Dispatch(state, refused=Disposition.EFFECT_UNSCOPED)
        outcome = await self._plans.claim_effect(
            execution_id=state.id, step_id=step_id, effect_key=key
        )
        match outcome.claim:
            case EffectClaim.CLAIMED:
                return None
            case EffectClaim.COMPLETED:
                satisfied = await self._satisfy(state, step_id, key, outcome)
                if satisfied is None:
                    # §2: "Where any fails, nothing is written" — the step keeps its
                    # entry status and the walk stops, exactly as for the three below.
                    return Dispatch(state, refused=Disposition.EFFECT_ALREADY_CLAIMED)
                return Dispatch(satisfied, satisfied=True)
            case EffectClaim.COMPLETED_OTHERWISE | EffectClaim.UNCERTAIN | EffectClaim.HELD:
                # §2: each dispatches nothing, commits no transition and stops the
                # walk, and **which member produced it is not carried** on the
                # disposition — what the turn tells the user is the reply surface's.
                return Dispatch(state, refused=Disposition.EFFECT_ALREADY_CLAIMED)
            case _:  # pragma: no cover - exhaustive
                assert_never(outcome.claim)

    async def _satisfy(
        self, state: ExecutionState, step_id: str, key: EffectKey, outcome: EffectOutcome
    ) -> ExecutionState | None:
        """Satisfy the step from the holder, where §2's remaining conditions hold.

        ``claim_effect`` has already established the first of the three — *"the
        intended action is the same and the keys are equal, which ``claim_effect``
        establishes together"* — by answering ``COMPLETED`` at all. The other two are
        properties of the **claiming step** and are checked here: every member of its
        ``when`` is satisfied for the goal **at this instant** (ADR-0252 §6), and its
        ``verifies`` holds over the **borrowed** output (ADR-0253 §4).

        **The stage makes no call and writes no output.** It commits ``→ SUCCEEDED``
        from the status the step was entered at, carrying the satisfaction trio and
        nothing else; §9 has the store copy ``output`` from the holder row it has just
        verified and stamp ``finished_at`` from its own clock, and
        ``StepTransition``'s own validator refuses a transition that carried either.
        ``attempts`` is not incremented and no authorisation is spent.

        **The holder is read for one reason only** — the ``verifies`` predicate needs
        the output it is stated over. What is *written* is never taken from that read:
        the store re-verifies the holder against the goal's own row inside the same
        indivisible step as the write (§9's five-limbed claim condition), so a holder
        that moved between the read and the commit is refused rather than copied.

        Returns:
            The committed state, or ``None`` where a condition failed — where nothing
            is written and the caller answers ``EFFECT_ALREADY_CLAIMED``.

        Raises:
            CancelledError: If the executing task was cancelled while the satisfaction
                was in flight. Raised **after** it has landed: the step is then durably
                ``SUCCEEDED`` naming the act it borrowed, which is the record ADR-0034
                §1 wants, and there is nothing left to close.
            PlanningError: If the store refused the satisfaction — a holder that is not
                this goal's, a key the row no longer carries, a source status that is
                not one of §2's two entry statuses. It is the non-stale class, so no
                caller re-reads and retries it.
        """
        borrowed = await self._borrowed(outcome)
        plan = await self._plans.get_plan(state.plan_id)
        step = (
            None if plan is None else next((one for one in plan.steps if one.id == step_id), None)
        )
        if borrowed is None or plan is None or step is None:
            return None
        if step.when:
            goal = await self._plans.get_goal(plan.goal_id)
            if goal is None:
                return None
            history = await self._plans.evidence_of(plan.goal_id)
            if not conditions_hold(
                step,
                elements=condition_elements(goal, revision=plan.targets_revision),
                rows=history.rows,
                at=self._reading(),
            ):
                return None
        if not verification_holds(step.verifies, borrowed.output):
            return None
        committed, cancelled = await self._commit_shielded(
            StepTransition(
                execution_id=state.id,
                step_id=step_id,
                to_status=StepStatus.SUCCEEDED,
                expected_version=state.version,
                satisfied_by_execution=outcome.execution_id,
                satisfied_by_step=outcome.step_id,
                satisfied_by_key=key,
            )
        )
        if cancelled:
            msg = f"step {step_id!r} was satisfied from an earlier effect; its task was cancelled"
            raise asyncio.CancelledError(msg)
        return committed

    async def _borrowed(self, outcome: EffectOutcome) -> StepExecution | None:
        """The holder's own record, or ``None`` where it cannot be resolved.

        ``EffectOutcome``'s validator makes both ids non-``None`` on ``COMPLETED`` and
        refuses either elsewhere, so the two guards below are the type narrowing that
        fact does not itself perform. A holder the store cannot return is not an error
        here: §2 has every failed condition write nothing and stop the walk, and a row
        naming an execution that has since gone is that case rather than a fault of
        this drive.
        """
        if outcome.execution_id is None or outcome.step_id is None:
            return None
        holder = await self._plans.get_execution(outcome.execution_id)
        return None if holder is None else holder.step(outcome.step_id)

    async def _run_once(  # noqa: PLR0913 — the five values one attempt is assembled from, plus ADR-0264 §2's observer; each is a distinct fact about the attempt
        self,
        state: ExecutionState,
        step_id: str,
        authorised: ToolCall,
        trusted: ToolDefinition | None,
        timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
        reach: CallableReach,
    ) -> tuple[ExecutionState, ToolResult | None]:
        """Invoke the seam once and commit what it says, revalidating the result.

        Returns the state after the commit, and the *revalidated* result the
        retry decision reads — or ``None`` where nothing retryable was produced:

        - a ``ToolBindingError`` is the seam's own rejection, committed ``FAILED``
          and never retried (:meth:`_refuse`, ADR-0029 §5 reads a result's kind);
        - a ``SpendError`` is a spend ceiling refusing the call before the
          callable, which is the same window and the same ``FAILED``, but not the
          same news: it is committed with the refusal's **own** account so a
          budget stop does not read as an internal fault
          (:meth:`_close_refused_by_spend`, ADR-0194 §4);
        - any **other** ``AssistantError`` is an exit from the seam's own claim
          on the authorisation, which ADR-0192 §1 places before the callable
          **as a clause of the contract**, and is committed ``FAILED`` for the
          same reason one step earlier: nothing ran (:meth:`_close_unclaimed`);
        - a ``CancelledError`` commits the interrupted-call classification and
          propagates, because swallowing it would break shutdown;
        - a result that does not survive revalidation is tampered past
          ``frozen=True`` (ADR-0018 §3) and is closed ``INDETERMINATE`` here
          (ADR-0051) rather than read verbatim into a
          ``KeyError``/``AttributeError`` past the claim
          (:func:`_detached_result`, :meth:`_discard_unusable`).

        Only the last case is the executor's own invention; the first three are
        the seam's contracted exits (ADR-0029 §8, ADR-0192 §9). Detaching the
        result before either the record or the retry decision reads it is what
        makes both total over what the seam returned, the mirror of
        :func:`_detached` for the inbound call.
        """
        # ADR-0264 §2, and the three `except` clauses below are the whole of what
        # establishes the negative: each is one of ADR-0192 §1's pre-callable windows,
        # committed `FAILED` "for the stated reason that recording `INDETERMINATE` would
        # be about a call that provably never reached the callable". Every other exit
        # from `invoke` — a return, a fault the callable itself raised, a cancellation
        # that landed inside it — leaves the observer set, because none of them
        # establishes that nothing left the machine.
        try:
            returned = await self._invoker.invoke(authorised, timeout=timeout)
        except ToolBindingError:
            return await self._refuse(state, step_id), None
        except SpendError as refusal:
            return await self._close_refused_by_spend(state, step_id, refusal), None
        except AssistantError:
            return await self._close_unclaimed(state, step_id), None
        except asyncio.CancelledError:
            reach.reached = True
            await self._commit_through_cancellation(state, step_id, _interrupted(trusted))
            raise
        reach.reached = True
        result = _detached_result(returned)
        if result is None:
            return await self._discard_unusable(state, step_id), None
        return await self._record(state, step_id, result), result

    # --- the transitions ------------------------------------------------

    async def _claim(
        self, state: ExecutionState, step_id: str, call: ToolCall, attempt_id: str
    ) -> ExecutionState:
        """Commit the ``→ RUNNING`` claim that must precede the call.

        ``bound_tool`` and ``approval_ref`` are pinned to the call being made,
        which is what makes the durable record a description of what ran rather
        than of what was planned (ADR-0029 §8). **``attempt_id`` names the attempt
        the claim is made under** (ADR-0255 §3), which the store checks against that
        row's own ``execution_ids`` and state in the same indivisible step as the
        write — so a caller naming the wrong attempt is refused rather than obeyed,
        and nothing is invoked.

        **A claim that lands into a cancellation is closed, not left standing.**
        The claim is a write like any other, so a cancellation can arrive while
        it is in flight — and this one lands *before* the tool is reachable. A
        durable ``RUNNING`` there is the worst available record: recovery reads
        it as ``INDETERMINATE``, "we cannot tell whether it acted", about a call
        that provably never started. So the write goes through the same shield
        idiom, and a claim known to have landed is resolved ``FAILED`` — nothing
        happened, which is what §8 says of the other pre-invocation exit — before
        the cancellation is allowed to leave.

        Args:
            state: The execution as stored, whose ``version`` the claim is computed
                against.
            step_id: The step being claimed.
            call: The authorised call, already detached and revalidated.
            attempt_id: The attempt the claim is made under (ADR-0255 §3).

        Raises:
            CancelledError: If the executing task was cancelled while the claim
                was in flight. Raised after the step has been closed.
            PlanningError: If the store rejected the claim — including where
                ADR-0255 §3's conjuncts refuse it, which leaves the step at its entry
                status with nothing invoked.
        """
        claimed, cancelled = await self._commit_shielded(
            StepTransition(
                execution_id=state.id,
                step_id=step_id,
                to_status=StepStatus.RUNNING,
                expected_version=state.version,
                bound_tool=call.request.tool.id,
                approval_ref=call.decision.id,
                attempt_id=attempt_id,
            )
        )
        if not cancelled:
            return claimed

        # The reason for closing is itself a cancellation, so it wins whatever
        # the close does: a store fault must not hide a teardown in progress.
        await self._resolve_unstarted(claimed, step_id, cancelling=True)
        msg = f"step {step_id!r} was claimed and closed unstarted; its task was cancelled"
        raise asyncio.CancelledError(msg)

    async def _resolve_unstarted(
        self, state: ExecutionState, step_id: str, *, cancelling: bool
    ) -> bool:
        """Close the claimed step, applying ADR-0034 §1's precedence to the close.

        One place, because all three pre-invocation exits reach it and the
        ordering is the part that is easy to get subtly different at each site.

        Args:
            state: The claimed execution.
            step_id: The step to close.
            cancelling: Whether the reason for closing is *itself* a
                cancellation. If it is, §1's first rule already governs — the
                teardown is what the caller must see — so a rejected close is
                logged rather than raised over it. If it is not, the rejected
                close is the more urgent fact and propagates.

        Returns:
            Whether a cancellation was absorbed by the close, which the caller
            owes a re-raise for. Always ``False`` when ``cancelling``, since the
            caller is already raising one.
        """
        if not cancelling:
            return await self._close_unstarted(state, step_id)
        try:
            await self._close_unstarted(state, step_id)
        except PlanningError:
            _log.warning("executor_unstarted_close_failed", step_id=step_id, exc_info=True)
        return False

    async def _close_unstarted(self, state: ExecutionState, step_id: str) -> bool:
        """Close a claimed step the callable was never reached from (ADR-0034 §1).

        ``FAILED`` rather than ``INDETERMINATE``, on ADR-0029 §8's own reasoning
        for the other pre-invocation exit: nothing happened, and
        ``INDETERMINATE`` is "the state whose whole meaning is ignorance". It is
        not retried, for §8's reason too — retry is scheduled only from a
        ``ToolResult``, and no exit through here produces one.

        **Two precedence rules, because this runs while another exception is
        already on its way out** (ADR-0034 §1). An **absorbed cancellation wins
        over everything**: absorbing one is a promise to re-raise it, and a
        teardown the caller cannot observe is worse than a diagnosis it loses. A
        **rejected close beats the reason for closing**, chained to it, because
        the step is now durably wrong in the exact way this rule exists to
        prevent — a `RUNNING` a recovery scan will read as `INDETERMINATE` — and
        that is the more urgent of the two facts. The one exception is where the
        reason for closing is *itself* a cancellation, in which case the first
        rule already applies and the caller logs instead.

        Returns:
            Whether a cancellation was absorbed while the close was in flight,
            which the caller owes a re-raise for.

        Raises:
            PlanningError: If the store rejected the close, so the step is left
                ``RUNNING`` and somebody has to be told.
            CancelledError: If a cancellation was absorbed and the close then
                failed — :meth:`_commit_shielded`'s own precedence.
        """
        _, cancelled = await self._commit_shielded(
            self._closing(
                state,
                step_id,
                StepStatus.FAILED,
                failure=StepFailure(kind=None, message=_UNSTARTED),
            )
        )
        return cancelled

    async def _refuse(self, state: ExecutionState, step_id: str) -> ExecutionState:
        """Commit ``RUNNING → FAILED`` for a seam rejection, and schedule nothing.

        The claim precedes the call, so a ``ToolBindingError`` arrives after the
        step is durably ``RUNNING``. Letting it propagate uncommitted would
        strand the step until recovery, which would record ``INDETERMINATE`` —
        "we cannot tell whether it acted" — about a call that provably never
        reached the callable, and that is the one thing ``INDETERMINATE`` must
        not be used for.

        Returning from here rather than falling into the retry decision is the
        whole mechanism for "never retried": ADR-0029 §5's conjuncts read
        ``result.failure.kind``, and an exception produces no result to read.
        """
        return await self._finish(
            state, step_id, StepStatus.FAILED, failure=StepFailure(kind=None, message=_REFUSED)
        )

    async def _close_unclaimed(self, state: ExecutionState, step_id: str) -> ExecutionState:
        """Commit ``RUNNING → FAILED`` for a seam exit before the callable (ADR-0192 §1).

        The executor's ``→ RUNNING`` claim precedes ``invoke``, and ``invoke``'s
        own claim on the authorisation precedes the callable, so an
        ``AssistantError`` from that append arrives after the step is durably
        ``RUNNING`` and before anything could have acted. Letting it propagate
        uncommitted would strand the step until recovery, which would record
        ``INDETERMINATE`` — "we cannot tell whether it acted" — about a call that
        provably never reached the callable.

        **Caught at the ``AssistantError`` boundary and never on a list of
        causes**, which is ADR-0192 §1's own instruction: "the executor commits
        ``RUNNING → FAILED`` and never retries, **on the window and not on a list
        of causes**". The named refusals and the ``AuditError`` the ledger
        translated a non-``AssistantError`` into are the common cases, but they are
        not all of them — ADR-0026 §2 has the ledger propagate a **clock
        callable's** own exception unwrapped, and §1 translates only what is *not*
        an ``AssistantError``, so a wired-wrong clock raising a ``PlanningError``
        reaches here as itself. A handler naming ``AuditError`` alone would leave
        exactly that exit durably ``RUNNING``.

        A ``SpendError`` is taken one branch earlier
        (:meth:`_close_refused_by_spend`) and reaches the same ``FAILED``: the
        clause governs the outcome, which no branch here varies, and that branch
        varies only which sentence the record carries — the ledger seam's, which
        is false of a budget stop, or the refusal's own (ADR-0194 §4).

        A *completion*-path failure never arrives here at all, because the seam
        absorbs it and returns the call's own ``ToolResult`` (ADR-0192 §3); and a
        ``BaseException`` is not reached either — §1 states no outcome for one and
        asks the executor to derive nothing from it.

        **It does not repair the trail.** Where the seam's claim append committed
        and then failed, that row stands and its claim is left open under a step
        this commit takes out of ``RUNNING`` — ADR-0192 §3's not-``RUNNING`` clause,
        which that ADR states rather than repairs, and which no recovery scan
        returns for. Nothing here deletes, rewrites or compensates for it.

        Retried never, by the same mechanism as :meth:`_refuse`: ADR-0029 §5's
        conjuncts read ``result.failure.kind`` and an exception produces no result
        to read.
        """
        return await self._finish(
            state, step_id, StepStatus.FAILED, failure=StepFailure(kind=None, message=_UNCLAIMED)
        )

    async def _close_refused_by_spend(
        self, state: ExecutionState, step_id: str, refusal: SpendError
    ) -> ExecutionState:
        """Commit ``RUNNING → FAILED`` for a spend refusal, in its own words (ADR-0194 §4).

        A ``SpendError`` sits in the same window as :meth:`_close_unclaimed` and
        gets the same outcome for the same reason — the gate refuses **before**
        the callable, so nothing ran, ``FAILED`` is honest and no result exists
        for ADR-0029 §5 to read a retry from. What differs is the *record*.

        **The generic wording would be false here.** ``_UNCLAIMED`` says the
        invoker "could not record the call against its authorisation", and that is
        not what happened: the authorisation is intact and recorded ``ALLOW``, and
        what refused is arithmetic over a calendar period. ADR-0194 §4 keeps
        :class:`~ai_assistant.core.errors.SpendError` out of
        :class:`~ai_assistant.core.errors.PermissionDeniedError` precisely so a
        trace can separate "you declined" from "you are out of budget"; collapsing
        it into the ledger seam's sentence one hop later loses the separation the
        type system was shaped to keep, and hides the remedy §4 names — the user
        raises the ceiling, in configuration, as a deliberate act.

        **So the error's own message is recorded, and none is composed here.**
        ADR-0194 §4 authors that text: which ceiling was crossed, its period, its
        currency, the accounted and projected totals — or, for
        :class:`~ai_assistant.core.errors.SpendUndeterminedError`, which of the six
        grounds fired and deliberately **no** amount. §3 has both ceilings bind
        independently and one error name both when both are crossed, in
        ``SpendPeriod``'s fixed order; a second sentence composed here could only
        contradict it or duplicate it. :func:`_spend_refusal` is where the reading
        happens, and why reading it is safe.

        **Naming a class here does not reopen "on the window and not on a list of
        causes"** (ADR-0192 §1). That clause governs the *outcome*, and the outcome
        is unchanged for every class: everything leaving ``invoke`` as an
        ``AssistantError`` still commits ``FAILED`` and is still never retried.
        This branch selects which authored sentence describes it — the same thing
        the ``ToolBindingError`` branch beside it has always done.
        """
        return await self._finish(
            state, step_id, StepStatus.FAILED, failure=_spend_refusal(refusal)
        )

    async def _discard_unusable(self, state: ExecutionState, step_id: str) -> ExecutionState:
        """Close a claimed step whose returned result cannot be read (ADR-0051).

        The claim precedes the call, so a result tampered past ``frozen=True``
        (ADR-0018 §3, :func:`_detached_result`) is discovered **after**
        ``invoke`` has returned. Recording it verbatim would raise a
        ``KeyError``/``AttributeError`` out of :meth:`_record` and strand the step
        durably ``RUNNING``, so it is closed here instead.

        **The close is ``INDETERMINATE``, not ``FAILED``, and unconditionally
        so.** Every other executor-authored ``FAILED`` here rests on "nothing
        ran" being a *known* fact — the pre-invocation exits (:meth:`_refuse`,
        :meth:`_close_unstarted`) all sit before the callable is reached. This one
        does not: the tool was invoked and may have acted, and the result whose
        ``outcome`` is now unreadable was the only evidence of whether it did.
        ``FAILED`` would record a possible irreversible effect as
        certainly-nothing-happened, the one use ADR-0014 §4 and ADR-0034 §1
        refuse — so this records ADR-0014 §4's durable ignorance instead, the
        same widened live-executor use as a deadline expiry (ADR-0029 §8, #208).

        Not the interrupted-call classification (:func:`_interrupted`): that rule
        maps a ``NATURAL`` side-effecting tool to ``FAILED`` *because a repeat
        does the same thing* — a premise that holds only when a retry follows.
        An unusable return is terminal (below), so the premise is absent and the
        honest answer is ignorance for every tool kind. Recording it needs no
        ``trusted`` declaration, which matters because the same corruption that
        produced this return may be why one is unavailable (ADR-0051 §2).

        Schedules nothing: the failure takes ``kind=None`` — no tool classified
        it — and ADR-0029 §5's conjuncts read ``result.failure.kind``, so a
        ``None`` kind is never retried (ADR-0039 §3). ``INDETERMINATE`` is outside
        automatic retry regardless (ADR-0014 §4), which is a second lock on the
        same door.
        """
        return await self._finish(
            state,
            step_id,
            StepStatus.INDETERMINATE,
            failure=StepFailure(kind=None, message=_UNUSABLE),
        )

    async def _record(
        self, state: ExecutionState, step_id: str, result: ToolResult
    ) -> ExecutionState:
        """Commit what the seam returned — a total mapping over ``ToolOutcome``.

        ``SUCCEEDED`` carries the output; ``FAILED`` and ``INDETERMINATE`` carry
        the tool's failure by value — kind and message unedited (ADR-0032 §5,
        ADR-0039 §6). ADR-0014 §4's ``INDETERMINATE`` transition, once reserved
        for a crash found at recovery, now records a diagnostic from a live
        deadline expiry too, where it used to drop it (#208); ADR-0029 §3
        requires ``failure`` present on a non-``SUCCEEDED`` result, so nothing is
        fabricated.

        ``result`` here is the revalidated, detached copy
        (:func:`_detached_result`), never the raw value the seam handed back: the
        ``outcome`` lookup and the ``failure`` dereference below are total only
        because a value tampered past ``frozen=True`` was already turned into a
        close before this runs (:meth:`_discard_unusable`).
        """
        status = _STATUS_BY_OUTCOME[result.outcome]
        if status is StepStatus.SUCCEEDED:
            return await self._finish(state, step_id, status, output=result.output)
        return await self._finish(state, step_id, status, failure=_failure_of(result))

    async def _finish(
        self,
        state: ExecutionState,
        step_id: str,
        status: StepStatus,
        *,
        output: FrozenJsonValue = None,
        failure: StepFailure | None = None,
    ) -> ExecutionState:
        """Commit a terminal transition for the claimed step, through the shield.

        Through the same idiom the cancellation path uses, and for the same
        reason rather than for symmetry. The claim precedes the call, so by the
        time this runs the tool has been reached and its outcome is *known*. A
        cancellation landing on this ``await`` would abandon the write and leave
        the step ``RUNNING``, and recovery would then record ``INDETERMINATE`` —
        "we cannot tell whether it acted" — over an answer the executor was
        holding, discarding a ``SUCCEEDED`` result's output with it. The whole
        write path is therefore cancellation-aware, not just the handler's.

        Raises:
            CancelledError: If the executing task was cancelled while this write
                was in flight. Raised **after** the write has landed, so the
                cancellation still propagates and shutdown still works, which is
                the same order ADR-0029 §4 requires of the handler's commit.
            PlanningError: If the store rejected the transition.
        """
        committed, cancelled = await self._commit_shielded(
            self._closing(state, step_id, status, output=output, failure=failure)
        )
        if cancelled:
            msg = f"step {step_id!r} was committed {status}; its executing task was cancelled"
            raise asyncio.CancelledError(msg)
        return committed

    def _closing(
        self,
        state: ExecutionState,
        step_id: str,
        status: StepStatus,
        *,
        output: FrozenJsonValue = None,
        failure: StepFailure | None = None,
    ) -> StepTransition:
        """Build the terminal transition without committing it."""
        return StepTransition(
            execution_id=state.id,
            step_id=step_id,
            to_status=status,
            expected_version=state.version,
            output=output,
            failure=failure,
        )

    # --- cancellation ---------------------------------------------------

    async def _commit_shielded(self, transition: StepTransition) -> tuple[ExecutionState, bool]:
        """Land ``transition`` even through a cancellation (ADR-0029 §4).

        **Shielding alone is not enough, and this is the part that looks done and
        is not.** ``asyncio.shield`` protects the inner task, not the ``await`` of
        it: a ``cancel()`` — a shutdown that has stopped waiting politely — raises
        here immediately while the commit is still in flight, and a caller that
        re-raised there would re-raise *before* the write landed, leaving the step
        ``RUNNING`` with no record of the outcome just established. So the rule is
        the whole idiom: keep the commit as a task, wait on it through the shield,
        **absorb any further cancellations while it is still running**, and let
        the caller re-raise only once it has completed.

        Even that is not a guarantee — the process can still be killed between the
        outcome and the write, and there ADR-0014 §4's answer is unchanged:
        recovery finds a durable ``RUNNING`` and records ``INDETERMINATE``.

        **An absorbed cancellation outranks the write's own failure.** Absorbing
        one is a promise to re-raise it, and letting a ``PlanningError`` out
        instead would break that promise at the one moment it matters: the
        caller's ``except PlanningError`` would handle a store fault while the
        task it belongs to quietly kept running, having had its teardown
        swallowed. The store fault is logged and the cancellation is what leaves.

        Returns:
            The committed state, and whether any cancellation was absorbed —
            which the caller owes a re-raise for.

        Raises:
            CancelledError: If a cancellation was absorbed and the commit then
                failed, so there is no state to return and a promise to keep.
            PlanningError: If the commit failed with nothing absorbed.
        """
        commit = asyncio.ensure_future(self._plans.commit_transition(transition))
        cancelled = False
        while True:
            try:
                return await asyncio.shield(commit), cancelled
            except asyncio.CancelledError:
                if not commit.done():
                    # Absorbed deliberately. The caller re-raises once the write
                    # has landed, so the cancellation still propagates.
                    cancelled = True
                    _log.debug("executor_absorbed_cancellation_mid_commit")
                    continue
                if commit.cancelled() or commit.exception() is not None:
                    # Nothing landed, so there is nothing to hand back and
                    # nothing to close. The teardown is all that is left.
                    raise
                # **The write landed and the cancellation arrived on the way
                # back.** `shield` protects the inner task, not the `await` of
                # it, so a `cancel()` between the commit completing and this
                # frame resuming raises here with a result already in hand.
                # Re-raising would throw that result away, and the caller would
                # be unable to close a claim it did in fact write — leaving the
                # step durably `RUNNING` for recovery to read as
                # `INDETERMINATE`, which is the outcome ADR-0034 §1 exists to
                # prevent. So it is reported as absorbed, like any other.
                _log.debug("executor_absorbed_cancellation_after_commit")
                return commit.result(), True
            except PlanningError:
                if not cancelled:
                    raise
                _log.warning("executor_commit_failed_after_absorbing", exc_info=True)
                msg = "the commit failed; the cancellation of the executing task still stands"
                raise asyncio.CancelledError(msg) from None

    async def _commit_through_cancellation(
        self, state: ExecutionState, step_id: str, outcome: ToolOutcome
    ) -> None:
        """Land the interrupted-call classification, for a cancelled invocation.

        A failure of the commit itself is logged rather than raised, because the
        cancellation is what the caller must see: replacing it with a
        ``PlanningError`` would strand a shutdown mid-teardown. The absorbed-flag
        is ignored for the same reason — the caller re-raises unconditionally.

        Both branches record now (ADR-0039 §2): ``outcome`` is ``FAILED`` or
        ``INDETERMINATE`` — never ``SUCCEEDED`` — and both require a failure, so
        the ``INDETERMINATE`` branch keeps its text instead of discarding it
        (#208). ``kind`` is ``None``: no tool classified this cancellation (§3).
        """
        status = _STATUS_BY_OUTCOME[outcome]
        failure = StepFailure(kind=None, message=_CANCELLED)
        try:
            await self._commit_shielded(self._closing(state, step_id, status, failure=failure))
        except PlanningError:
            _log.warning("executor_cancellation_commit_failed", step_id=step_id, exc_info=True)

    # --- the retry decision (ADR-0029 §5) -------------------------------

    def _may_retry(
        self, result: ToolResult, trusted: ToolDefinition | None, started: datetime
    ) -> bool:
        """Whether ADR-0029 §5's two conjuncts both hold.

        Both, never either: ``retryable`` says a repeat could plausibly succeed,
        and it says nothing about whether repeating is *safe*. An executor
        reading it alone would double a charge on the first ``TIMED_OUT`` send it
        saw.
        """
        if result.outcome is not ToolOutcome.FAILED:
            # An INDETERMINATE outcome is outside automatic retry by ADR-0014 §4,
            # and this does not relax it.
            return False
        failure = result.failure
        if failure is None or not failure.kind.retryable:
            return False
        return self._repeat_is_safe(trusted, started)

    def _repeat_is_safe(self, trusted: ToolDefinition | None, started: datetime) -> bool:
        """Whether repeating this call cannot act twice (ADR-0029 §5).

        Read from the registry's declaration for the same reason the interrupted
        rule is. A tool the registry does not know is refused a retry outright:
        with no trusted declaration there is nothing to establish safety from,
        and the fail-closed direction is a retry not taken.
        """
        if trusted is None:
            return False
        if not trusted.side_effecting or trusted.idempotency is Idempotency.NATURAL:
            return True
        if trusted.idempotency is not Idempotency.KEYED:
            # An `Idempotency.NONE` side-effecting tool is never auto-retried,
            # whatever the failure kind.
            return False
        window = trusted.idempotency_window
        return window is not None and self._window_is_open(started, window)

    def _window_is_open(self, started: datetime, window: timedelta) -> bool:
        """Whether the idempotency window has not yet elapsed — fail-closed.

        Past the window "the tool is free to act again" (ADR-0016 §4) and the
        retry stops being a retry, so the executor stops retrying.

        **Measuring an elapsed duration needs a clock the system does not have.**
        ADR-0026 §7 is explicit that ``Clock`` produces wall-clock instants and
        that measuring across a DST transition or an NTP step is a different
        contract it should not be stretched to. So the rule is made fail-closed
        instead: any reading that is **not a positive elapsed duration** — a step
        backwards, a jump past the window — is treated as *the window has
        lapsed*. Declining to retry costs a recoverable error surfaced to the
        user; retrying outside a lapsed window costs a duplicated side effect. A
        monotonic clock seam is the proper fix and is #171, deferred by ADR-0029
        §5 itself.

        This is scoped to a **reading**, and deliberately: a clock that raises
        produced none, and is a wiring bug rather than a pessimistic measurement
        (:meth:`_reading`, ADR-0034 §2).
        """
        elapsed = self._reading() - started
        if elapsed <= timedelta(0):
            return False
        return elapsed < window

    def _reading(self) -> datetime:
        """The clock's reading, as `orchestration`'s own error (ADR-0026 §4).

        **A reading and an invocation are different failures, and only one of
        them is ADR-0029 §5's** (ADR-0034 §2). §5's fail-closed rule is scoped to
        a *reading*: "any **reading** that is not a positive elapsed duration — a
        step backwards, a jump past the window — is treated as the window has
        lapsed". A clock that *raises* produced no reading to be pessimistic
        about, and ADR-0026 §2 is explicit that this is a different thing: "The
        guard covers the reading, not the invocation. An exception raised by the
        clock callable itself propagates unwrapped."

        So a raising clock is a **wiring bug**, and ADR-0026 §4 requires the
        owning subsystem to translate it at its own boundary. That is what this
        does for the guard's own rejection, exactly as ``LearningLoop`` and
        ``PlanExecution`` do; anything the callable raises on its own account
        propagates untouched, carrying its type and cause.

        Swallowing it instead would let a broken clock become a log line and a
        retry quietly not taken — the silent degradation ADR-0026 §4 rejected
        when it chose to convert a fabrication into a loud failure. It costs the
        execution: the caller sees a ``PlanningError`` where a lapsed window
        would have let the turn finish. That is the trade ADR-0034 §2 takes,
        because a clock this broken makes *every* window measurement wrong and
        the next one is a duplicated side effect rather than an aborted turn.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc


def _failure_of(result: ToolResult) -> StepFailure:
    """The ``StepFailure`` a non-``SUCCEEDED`` result records, by value (ADR-0039 §6).

    Kind and message cross **unedited** — ADR-0032 §5 governs the message up to
    the seam, and the executor adds no rule of its own past that point: it does
    not prefix, wrap or annotate. ``_UNEXPLAINED`` stands in only for the
    result-with-no-failure that :class:`~ai_assistant.core.types.ToolResult`'s
    own validator makes unconstructable, keeping the mapping total against a
    value tampered past ``frozen=True``; it takes ``kind=None`` because — like an
    executor-authored failure — no tool classified it (§3).
    """
    failure = result.failure
    if failure is None:
        return StepFailure(kind=None, message=_UNEXPLAINED)
    return StepFailure(kind=failure.kind, message=failure.message)


def _spend_refusal(refusal: SpendError) -> StepFailure:
    """The ``StepFailure`` a spend refusal records: the error's own account.

    **Carried rather than authored, which is the opposite of the ledger seam's
    treatment, and the difference is contractual.** The executor authors
    :data:`_REFUSED` and :data:`_UNCLAIMED` because those errors' own messages are
    not log-safe — a ``ToolBindingError`` interpolates identifiers off an
    untrusted call, and an ``AuthorisationSpentError`` names a decision id, which
    ADR-0031 §5 records is not contractually log-safe. ADR-0194 §4 states the
    reverse of a ``SpendError``: its message is **payload-free** — "no argument
    value, no recipient, no account, no tool output and no digest of any of them"
    — and is authored to be read. It clears ADR-0004 §5 as Tier 2 text on the
    contract's own word, so it crosses unedited, exactly as a tool's own failure
    message does in :func:`_failure_of`.

    **Two ways a raiser can still leave nothing recordable, and neither may
    strand the step.** This runs inside an exception handler on an already
    durably-``RUNNING`` step: an exception escaping it abandons the close, and
    recovery would read that ``RUNNING`` as ``INDETERMINATE`` — "we cannot tell
    whether it acted" — about a call the gate provably stopped. So a ``__str__``
    that raises is caught (the hazard ``permissions/audit.py`` names when it
    refuses to interpolate a collaborator's exception), and text
    :class:`~ai_assistant.core.types.StepFailure` rejects — blank, or with no
    UTF-8 encoding — is caught as well. Both fall back to :data:`_UNSTATED`, which
    still says the refusal was a spend one: the ground survives even when the
    account does not.
    """
    try:
        stated = str(refusal)
    except Exception:
        return StepFailure(kind=None, message=_UNSTATED)
    try:
        return StepFailure(kind=None, message=stated)
    except ValidationError:
        return StepFailure(kind=None, message=_UNSTATED)


def _interrupted(trusted: ToolDefinition | None) -> ToolOutcome:
    """What an interrupted call of ``trusted`` means (ADR-0029 §4).

    Delegates wholly to
    :attr:`~ai_assistant.core.types.ToolDefinition.interrupted_outcome`, the one
    copy of the rule (ADR-0031 §1). An unknown declaration is ``INDETERMINATE``:
    with nothing trusted to classify from, the honest answer is the ignorant one,
    and ``FAILED`` would record a possible side effect as
    certainly-nothing-happened.
    """
    return ToolOutcome.INDETERMINATE if trusted is None else trusted.interrupted_outcome


__all__ = ["StepExecutor"]

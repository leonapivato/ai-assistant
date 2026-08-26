"""Running one bound callable under a deadline, and classifying what came back.

The half of ADR-0029 §3 and §4 that is about *execution* rather than about binding.
:mod:`ai_assistant.tools.registry` owns the binding and the three checks that
precede a call; everything here starts once a trusted ``(definition, callable)``
pair is in hand.

The callable's own signature is deliberately **not** a ``core`` contract.
ADR-0029 §1 leaves "how the callable is reached" internal to `tools/`, on
ADR-0008's precedent — a ``ContextProvider`` crosses the boundary while the
``ContextSource`` seam that populates it stays inside `context/`. Registration
is this subsystem's ``ContextSource``.

**There are two callable shapes, not one**, and the second is what that licence
was being kept for. :class:`ToolImplementation` takes the call's arguments;
:class:`EgressToolImplementation` takes them and the
:class:`~ai_assistant.core.types.EgressBinding` the authorising decision carries,
because a transport may re-derive none of what the ruling fixed (ADR-0148 §4).
:func:`_awaited` is where a registration's two halves are checked against each
other, and it refuses both mismatches before the deadline opens.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog
from pydantic import ValidationError

from ai_assistant.core.errors import ToolBindingError, ToolRegistrationError
from ai_assistant.core.types import (
    UNREPRESENTABLE_FAULT_CLASS,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping
    from datetime import timedelta

    from ai_assistant.core.types import EgressBinding, FrozenJson, ToolCall, ToolDefinition

    #: What enters the bound callable once the claim has landed: a zero-argument
    #: callable returning the coroutine to await. :func:`checked_pairing` builds
    #: one, having decided the shape — so nothing about the callable is read again
    #: after the claim, and nothing is *called* before it (ADR-0192 §1).
    #:
    #: Declared here rather than at module scope because it is a name for a
    #: signature and never a value: every use is an annotation, which
    #: ``from __future__ import annotations`` leaves unevaluated, so binding it at
    #: runtime would buy three imports nothing else in this module needs.
    EntersCallable = Callable[[], Coroutine[Any, Any, FrozenJson]]

    #: What a registration will enter, read off the object **once at
    #: registration** (:func:`resolved_implementation`). Spelled with an ellipsis
    #: because it is called only through ``functools.partial`` below, which
    #: supplies whichever keywords the resolved shape declares.
    EnteredCallable = Callable[..., Coroutine[Any, Any, FrozenJson]]

_log = structlog.get_logger(__name__)


class ToolImplementation(Protocol):
    """The callable an integration binds to a declaration at registration.

    Receives the call's arguments and, for a ``KEYED`` tool, the derived
    idempotency key as an **opaque string** (ADR-0029 §5). A tool whose upstream
    constrains the key's format maps it inside the integration, and that mapping
    must be deterministic: one that is not a function of the key reintroduces
    the variance the derivation removed.

    It receives no credential, and returns none. A tool that needs one obtains
    it itself; nothing about a secret crosses the invocation seam in either
    direction (ADR-0029 §6).

    An implementation **raises** to report a failure it cannot classify; the
    seam turns that into an ``INTERNAL`` result. One that can classify its own
    failure returns nothing useful by raising — it should be given the vocabulary
    of :class:`~ai_assistant.core.types.ToolFailureKind` by a future integration
    ADR, which this one does not decide.
    """

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> FrozenJson:
        """Perform the call and return its JSON-shaped output."""
        ...


@runtime_checkable
class EgressToolImplementation(Protocol):
    """The callable an **egress** integration binds to a declaration (ADR-0029 §1).

    :class:`ToolImplementation` with one addition it cannot do without: the
    :class:`~ai_assistant.core.types.EgressBinding` the authorising decision
    carries. A transport needs the account, the pinned endpoint and the canonical
    destination set the ruling fixed; it may re-derive none of them (ADR-0148 §4's
    third clause, which says a later lane "cannot satisfy it by re-deriving the set
    at the seam"); and the only holder of them at execution time is the request the
    executor read back out of the trail (ADR-0037 §3).

    **A second shape rather than a wider first one, for the reason ADR-0029 §1
    gives for splitting ``ToolInvoker`` off ``ToolRegistry``**: "the surface should
    not widen to cover a concern its consumers do not have." ``current_time`` and
    ``recall_memory`` have no business being handed a
    :class:`~ai_assistant.core.types.BoundAccount` carrying an account identity —
    Tier 1 personal data (ADR-0149 §3) — merely to satisfy a signature. Widening
    the one shape would hand every tool in the system that value forever, which is
    the direction ADR-0017 §8 wants to move away from and which ADR-0152 §10
    refuses one boundary out.

    **The method is named rather than being a second ``__call__``**, because
    ``runtime_checkable`` against a ``__call__``-only Protocol matches every
    callable in the language and so could not tell the two shapes apart at all. A
    distinct name makes the discrimination structural and total.

    Nothing else moves. ADR-0029 §6 still holds — no credential crosses this seam
    in either direction, and a binding carries none (ADR-0148 §6's exclusion
    clause). And choosing this shape is ADR-0029 §1's to give away: "How the
    callable is reached is `tools/`-internal, and this ADR does not contract it …
    What signature an integration author writes … is decided by the implementation
    PR — where it will have implementation contact — not blessed here."
    """

    async def invoke_bound(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
        egress_binding: EgressBinding,
    ) -> FrozenJson:
        """Perform the bound egress call and return its JSON-shaped output."""
        ...


#: Either callable shape a registration may bind. A union rather than a common
#: base class, because both are structural Protocols: an integration author
#: satisfies one by writing a method, never by inheriting anything.
BoundImplementation = ToolImplementation | EgressToolImplementation


@dataclass(frozen=True, slots=True)
class ResolvedImplementation:
    """A registration's callable shape, decided once and held by the registry.

    **Nothing the implementation controls is read per call.** Deciding the shape
    means asking the object two questions — is it an
    :class:`EgressToolImplementation`, and what is its ``invoke_bound`` — and both
    are attribute accesses on an object this seam did not write, so both run
    whatever that object's ``__getattribute__`` does. Asked at invocation time
    they would run it *before* the claim, so a call the ledger then refused
    ``UnrecordedAuthorisationError`` would already have reached
    implementation-controlled code. Asked at **registration** they run once, at
    composition time, under no authorisation at all — an object being registered
    is trusted by definition, and there is no decision for it to run ahead of.

    That also makes ADR-0192 §1's property hold by construction rather than by
    care: an implementation that acquires or sheds ``invoke_bound`` after
    registration changes nothing the seam reads, so no re-read can raise a
    ``ToolBindingError`` after the claim. ADR-0016 §5 already binds an id to *the*
    callable for the life of the process and refuses a different one under a used
    id; this holds the shape of that callable to the same standard.

    **One callable and a flag, rather than one field per shape.** A record with a
    field for each admits a state with neither set — which is exactly what an
    object carrying a non-callable ``invoke_bound`` would produce, and it would
    only be discovered at the point of entry, after the claim. There is no such
    state here: the pairing check below is a two-way branch on the registry's own
    record, and both branches have something to enter.
    """

    #: What will be entered: the bound egress method, or the registration itself.
    enter: EnteredCallable
    #: Whether :attr:`enter` takes the authorised ``EgressBinding`` (ADR-0148 §4).
    egress: bool


def resolved_implementation(implementation: BoundImplementation) -> ResolvedImplementation:
    """Decide ``implementation``'s shape, at registration and not at invocation.

    Args:
        implementation: The callable being registered.

    Returns:
        The callable to enter and whether it takes the authorised binding.

    Raises:
        ToolRegistrationError: If the object satisfies neither shape — it is not
            callable and carries no callable ``invoke_bound``. Refused here rather
            than at the point of entry, because there it would be a fault raised
            after the claim (ADR-0192 §1).
    """
    if isinstance(implementation, EgressToolImplementation):
        bound = implementation.invoke_bound
        # `runtime_checkable` tests for the attribute's **presence** and nothing
        # else, so an ordinary callable carrying an `invoke_bound` that is not a
        # method — a property returning `None`, a data attribute — reports as
        # egress. Taking that on trust would store a shape with no callable in it
        # and fail at the point of entry, after the claim. It is not an egress
        # binding, so it is not treated as one.
        if callable(bound):
            return ResolvedImplementation(enter=bound, egress=True)
    # Typed as `object` so the check is over the *value*: the annotation is not
    # the enforcement, and this argument reaches here from a composition root the
    # type checker may never have seen (ADR-0026 §2's rule for a clock reading).
    ordinary: object = implementation
    if not callable(ordinary):
        msg = (
            "the object registered satisfies neither tool shape: it is not callable "
            "and carries no callable 'invoke_bound', so there would be nothing to invoke"
        )
        raise ToolRegistrationError(msg)
    return ResolvedImplementation(enter=ordinary, egress=False)


def checked_pairing(resolved: ResolvedImplementation, call: ToolCall) -> EntersCallable:
    """Check the pairing and return what will enter the callable — **without entering it**.

    Two things have to be true at once since ADR-0192 §1, and an implementation
    that does either without the other is wrong in a way no ordinary test sees.

    **The shape is resolved exactly once, and not here.**
    :class:`ResolvedImplementation` is read off the object at *registration*, so
    this check asks the registry's own record and never the implementation.
    Reading the shape again per call would let an object that acquired or shed
    ``invoke_bound`` while the claim append was in flight raise a
    ``ToolBindingError`` *after* the claim, and §3 would owe a completion carrying
    an outcome ADR-0029 computes for no such error. §1 states that as a
    **property, not a list**: after the claim, ``invoke`` performs no check that
    can raise a seam fault. Resolving at registration also keeps a *refused* claim
    from reaching implementation-controlled code at all — an attribute access is
    that object's own ``__getattribute__``, and asking for it per call would run
    it before the ledger had accepted anything.

    **And nothing is called here.** An earlier version returned the *coroutine*,
    which meant invoking the registered callable to obtain one. Nothing makes a
    registration a native ``async def`` — a plain function returning a coroutine
    satisfies the shape — so its body would have run before the claim, and a claim
    then refused as spent or unrecorded would have left a side effect performed
    under an authorisation the ledger declined. So this returns a **factory**: the
    branch is decided here, and entering the callable is the first thing that
    happens after the claim lands, inside the deadline.

    **The check, separated from creating the coroutine, because ADR-0192 §1 puts
    the ledger claim between them.** "After ADR-0029 §2's three checks" is that
    section's floor and not the whole ordering: the claim is appended after
    *every* check that can raise a seam fault, and this pairing check is one of
    them — it reads the registry's callable and not the call alone, so those three
    do not subsume it. Claiming first would owe ADR-0192 §3 a completion carrying
    an outcome ADR-0029 computes for no ``ToolBindingError``: that error is given
    no ``ToolResult`` at all, only the executor's ``FAILED`` step. Performing the
    check without creating the coroutine is what lets the claim sit between the
    two without a never-awaited coroutine left behind on a refused claim.

    The cost is nothing — this enters no callable, performs no I/O and opens no
    deadline — and the gain is that a ``ToolBindingError`` stays exactly where
    ADR-0029 and ADR-0034 §1 already put it: a pre-callable exit with no claim
    appended and no row written.

    **Both mismatches are seam faults and both fail closed**, which is why they are
    checked here rather than left to whichever side would notice first:

    - an **egress** callable reached with no binding would be a tool that transmits
      being handed no account, no pinned endpoint and no authorised destination
      set. That is the state a binding seam answering "not an egress call" for a
      tool whose callable can only make one would produce — the mis-registration
      ADR-0152 §8 refuses, arriving one stage later.
    - an **ordinary** callable reached *with* a binding is the mirror image. A
      ruling was taken over a canonical destination set and a payload description,
      and the thing about to run can honour neither; ADR-0148 §4's third clause is
      that what is transmitted is bound to what was authorised, and a callable that
      never sees the binding is not held to it by anything.

    Neither is reachable through a correctly wired registry, and that is the
    argument *for* the check rather than against it: which callable a declaration
    binds is `tools/`-internal and contracted nowhere (ADR-0152 §10), so nothing
    else in the system would notice a root that paired them wrongly.

    Args:
        resolved: The shape the registry decided when this callable was
            registered (:func:`resolved_implementation`).
        call: The revalidated, detached call.

    Returns:
        A zero-argument callable that enters the bound callable and returns its
        coroutine. It performs no check of its own.

    Raises:
        ToolBindingError: If the callable's shape and the call's binding disagree.
    """
    authorised = call.request.egress_binding
    if resolved.egress:
        if authorised is None:
            msg = (
                f"tool {call.request.tool.id!r} is bound to an egress callable and this call "
                f"carries no egress binding, so there is no authorised account, endpoint or "
                f"destination set for it to transmit under (ADR-0148 §4, ADR-0152 §8)"
            )
            raise ToolBindingError(msg)
        return partial(
            resolved.enter,
            call.request.parameters,
            idempotency_key=call.idempotency_key,
            egress_binding=authorised,
        )
    if authorised is not None:
        msg = (
            f"tool {call.request.tool.id!r} was authorised as an egress call and is bound to a "
            f"callable that takes no egress binding, so what would run cannot be held to what "
            f"was authorised (ADR-0148 §4)"
        )
        raise ToolBindingError(msg)
    return partial(resolved.enter, call.request.parameters, idempotency_key=call.idempotency_key)


#: What names an invented cancellation, as a **literal** rather than a read. A
#: ``CancelledError`` reaches :func:`internal_failure` only from the branch that
#: has already established none was requested (ADR-0029 §4, ADR-0031 §2), so what
#: happened is fully described without asking a tool-controlled class for its
#: name — and asking would put an attacker-controlled string in a message for no
#: gain over this one.
_INVENTED_CANCELLATION = "CancelledError"


def _fault_class(exc: BaseException) -> str:
    """Name the exception's class, totally, and with nothing the tool controls.

    **Read once, and total, because this runs after the claim.** Both the
    diagnostic and the failure message below need the class, and an unguarded
    read would leave this frame in place of the ``ToolResult`` — so ADR-0192 §3
    would get no completion for a claim it had already appended, a known-failed
    act permanently spending its authorisation, and ADR-0029 §3's rule that a
    broken tool becomes a *result* rather than an exception would not hold for the
    one class of tool most likely to break it.

    **The classifier is ``core``'s**, not a second one written here:
    :func:`~ai_assistant.core.types.fault_class_of` guards the ``__name__`` access,
    rejects a name that is not a plain identifier, and answers with
    :data:`~ai_assistant.core.types.UNREPRESENTABLE_FAULT_CLASS` for both. That
    matters twice over — an unguarded access takes the result down, and a name is
    as attacker-controlled as a message, so a class called
    ``recipient@example.com`` would otherwise be copied verbatim into
    ``ToolFailure.message`` and into a log ADR-0004 §5 rules Tier 2 only.

    Two things it cannot do from inside ``core`` are done here.

    **A ``CancelledError`` from the name read is swallowed, not delivered.**
    ``fault_class_of`` deliberately lets one out, because at *its* callers the
    ``Task.cancelling()`` count is read afterwards and decides. Here it is already
    decided: every branch reaching :func:`internal_failure` has established that
    no cancellation was requested, and the read is synchronous, so none can be
    delivered between the two. One raised by a hostile metaclass is therefore
    invented with nothing cancelled — ADR-0031 §2's case, which ADR-0029 §4 makes
    ``INTERNAL`` rather than a cancellation. Letting it out would report a
    cancellation nobody asked for *and* leave the claim open. Every other
    ``BaseException`` still propagates: a process being torn down is not a
    refusal, and the open claim is the honest state for it (ADR-0192 §3).

    **The result is required to be an exact ``str``.** ``fault_class_of`` hands
    back the name it validated, and a metaclass may return a ``str`` *subclass*
    that passes both the type check and the pattern and then runs its own
    ``__format__`` when the message is built — after the claim, with the same
    consequence as the raising read. An exact built-in string cannot.
    """
    try:
        fault = fault_class_of(exc) if isinstance(exc, Exception) else _INVENTED_CANCELLATION
    except asyncio.CancelledError:
        return UNREPRESENTABLE_FAULT_CLASS
    # `type(...) is str` and not `isinstance`: the subclass is the thing refused.
    return fault if type(fault) is str else UNREPRESENTABLE_FAULT_CLASS


def internal_failure(definition: ToolDefinition, exc: BaseException) -> ToolResult:
    """Describe a broken tool without quoting it (ADR-0029 §3).

    **The message names the exception's type and the tool's id, and nothing
    else.** It does not interpolate ``str(exc)``, which is where a
    ``RuntimeError`` quoting a recipient would arrive — and ``core/logging.py``
    names that exact shape, ``error=str(exc)``, as the Tier 1 leak its key-based
    redactor cannot see. The cost is a thinner diagnostic for a broken
    integration, accepted because the alternative is a disclosure on the failure
    path of every tool nobody thought about.
    """
    fault = _fault_class(exc)
    with contextlib.suppress(Exception, asyncio.CancelledError):
        # Guarded because this runs **after** the claim: a configured processor
        # that raises would otherwise leave this frame in place of the
        # ``ToolResult``, and ADR-0192 §3 would get no completion for a claim it
        # had already appended — a known-failed act permanently spending its
        # authorisation, with the tool's failure lost as data. ADR-0029 §3 makes
        # a broken tool a result rather than an exception, and a broken log sink
        # does not undo that.
        #
        # The ``CancelledError`` is named for the same reason `_fault_class`
        # names it: this branch has already established that none was requested,
        # and the emission is synchronous, so one raised by a processor is
        # invented with nothing cancelled (ADR-0031 §2) and ADR-0029 §4 makes
        # that ``INTERNAL`` rather than a cancellation. Every other
        # ``BaseException`` still propagates.
        _log.warning(
            "tool_implementation_raised",
            tool_id=definition.id,
            # The type, never the instance: rendering the exception is the leak.
            error_type=fault,
        )
    return ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(
            kind=ToolFailureKind.INTERNAL,
            message=f"{fault} escaped tool {definition.id!r}",
        ),
    )


def expiry_failure(definition: ToolDefinition, timeout: timedelta) -> ToolResult:
    """Describe this seam's own deadline expiring.

    Public because the deadline is no longer opened in one place: ADR-0194 §3 puts
    the spend admission inside the same window, so an expiry can land before the
    callable is ever created and the frame that observes it there needs the same
    classification this one gives. ``timeout`` is the figure the **caller** stated
    rather than whatever remained of it, so the message names the budget the caller
    set (ADR-0029 §4).
    """
    return ToolResult(
        outcome=definition.interrupted_outcome,
        failure=ToolFailure(
            kind=ToolFailureKind.TIMED_OUT,
            message=f"tool {definition.id!r} did not finish within {timeout}",
        ),
    )


def _pending_cancellations() -> int:
    """How many cancellation requests the invoking task is currently carrying.

    Read as a **baseline and a delta**, never as a boolean. ``Task.cancelling()``
    is a lifetime count that only ``uncancel()`` lowers, so a caller that
    absorbed an earlier cancellation to finish some work and then invoked a tool
    still reports a positive count with nothing about *this* call cancelled.
    Treating that as provenance would fail every subsequent invocation on that
    task as cancelled — and would convert a tool's invented ``CancelledError``,
    which ADR-0029 §4 requires to be ``INTERNAL``, into a cancellation on the
    strength of something that happened before the seam was entered.
    """
    task = asyncio.current_task()
    return 0 if task is None else task.cancelling()


def _interruption(
    definition: ToolDefinition,
    timeout: timedelta,
    deadline: asyncio.Timeout,
    cancellations_on_entry: int,
) -> ToolResult | None:
    """Answer what an interruption the tool *absorbed* means, if there was one.

    Nothing forces a callable to let a cancellation through: one that catches
    ``CancelledError`` and returns a value leaves the seam holding an output and
    no exception. Trusting that return would be the seam's worst available bug —
    a cancelled turn reported as ``SUCCEEDED``, or a call that outran the
    deadline reported as though it had met it. So the state is read from the
    task and the timeout rather than inferred from what came back.

    A pending external cancellation is re-raised rather than reported, because
    ADR-0029 §4 keeps that on the executor: swallowing it would break structured
    concurrency and shutdown. An expired deadline is reported, because that is
    the seam's own knowledge and the only form in which ``INDETERMINATE`` can be
    delivered at all.

    **What this does not close, stated rather than papered over.** The deadline
    half is tool-proof — ``Timeout.expired()`` is the seam's own state and no
    callable can reset it. The cancellation half is not: a callable that catches
    an *external* cancellation and then calls ``uncancel()`` on the invoking task
    restores the count to its baseline, and the call comes back as an ordinary
    result. That is the same family ADR-0029 §4 already calls unclosable from
    this side — "a tool that suppresses its own cancellation can outlive its
    deadline, and no seam can prevent that" — and the mitigation it names, one
    stalled turn on a loop that keeps running, applies unchanged. Closing it
    would mean running the callable in a child task, which is the shape §10
    warns against ("an implementation quietly acquiring a watchdog") and would
    make ``invoke``'s cooperative limit a different, weaker thing. Tracked as an
    issue rather than fixed here, because the fix is a contract question.

    Returns:
        The expiry result if this deadline expired, or ``None`` if the call was
        not interrupted.

    Raises:
        CancelledError: If a cancellation of the invoking task is still pending.
    """
    if _pending_cancellations() > cancellations_on_entry:
        # Freshly raised rather than re-raised: the original was consumed inside
        # the callable. What matters is that the cancellation reaches the
        # executor rather than being answered with a result.
        msg = f"tool {definition.id!r} absorbed the cancellation of its invoking task"
        raise asyncio.CancelledError(msg)
    if deadline.expired():
        return expiry_failure(definition, timeout)
    return None


async def run_bound_call(
    implementation: BoundImplementation,
    *,
    definition: ToolDefinition,
    call: ToolCall,
    timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
) -> ToolResult:
    """Pair ``call`` with ``implementation`` and run it, in one step.

    The convenience composition of :func:`checked_pairing` and
    :func:`run_prepared_call`, for a caller with no ledger claim to place between
    them. A caller that has one **must** use the two halves: resolving the shape
    twice would put a check that can raise a seam fault *after* the claim, which
    ADR-0192 §1 forbids as a property rather than as a list of inputs.

    Raises:
        ToolBindingError: If the callable's shape and the call's egress binding
            disagree (:func:`checked_pairing`). Raised **before** the deadline
            opens, so it is a seam fault like the three ``invoke`` performs and
            never a classified tool failure.
        CancelledError: If the invoking task was cancelled from outside.
    """
    return await run_prepared_call(
        checked_pairing(resolved_implementation(implementation), call),
        definition=definition,
        timeout=timeout,
    )


async def run_prepared_call(
    entering: EntersCallable,
    *,
    definition: ToolDefinition,
    timeout: timedelta,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0029 §4)
    stated: timedelta | None = None,
) -> ToolResult:
    """Await ``running`` under this seam's deadline and classify the result.

    Every classification here keys on something the seam itself established,
    never on an exception's type alone:

    - ``TIMED_OUT`` requires **this** deadline to have expired. An upstream SDK
      raising Python's ``TimeoutError`` for its own reasons, well inside our
      budget, is an exception like any other and becomes ``INTERNAL`` — because
      labelling it ``TIMED_OUT`` would, for a side-effecting tool, escalate a
      call that failed fast and provably did nothing into one whose effect is
      unknown, and therefore out of retry.
    - A ``CancelledError`` is a cancellation only if one was actually
      **requested** — of this deadline, or of the invoking task. If none was,
      the tool invented it, and a tool that raised is ``INTERNAL``. Otherwise it
      propagates: swallowing it would break structured concurrency and shutdown,
      and there is no return path from a task being torn down.
    - **Neither of those is inferred from what the callable did**, because a
      callable that catches a cancellation and returns a value leaves the seam
      holding an output and no exception at all. So the deadline and the task
      are read directly, on the normal-return path as well as the raising one —
      see :func:`_interruption`. Without that, a cancelled turn comes back
      ``SUCCEEDED``, and a side-effecting call that outran its deadline comes
      back as though it had met it.

    ``BaseException`` otherwise propagates unchanged, which is the boundary
    ADR-0026 §2 drew for ``checked_clock``: a guard whose own failure modes
    bypass the failure path it specifies is enforcing nothing.

    Args:
        entering: What :func:`checked_pairing` built, having resolved the
            callable's shape **once** and before any claim, and having called
            nothing.
        definition: The registry's own declaration, used for classification.
        timeout: How long to wait; already checked by the caller. Since ADR-0194
            §3 this may be **what is left** of the caller's budget after the spend
            admission consumed part of it, rather than the whole of it.
        stated: The figure an expiry message names, defaulting to ``timeout``.
            Passed where the two differ, so a user reads the deadline they set
            rather than the remainder the callable happened to be handed — the
            classification is unaffected either way, because what makes an expiry
            an expiry is this deadline having fired.

    Returns:
        The classified outcome.

    Raises:
        CancelledError: If the invoking task was cancelled from outside.
    """
    entered_with = _pending_cancellations()
    named = timeout if stated is None else stated
    deadline = asyncio.timeout(timeout.total_seconds())
    try:
        async with deadline:
            # Entered here, inside the deadline, and not a moment earlier: this is
            # the first thing that happens after the claim landed (ADR-0192 §1).
            output = await entering()
    except asyncio.CancelledError as exc:
        if _pending_cancellations() > entered_with:
            raise
        return internal_failure(definition, exc)
    except Exception as exc:
        # Python's own `TimeoutError` arrives here too, and is *not* special:
        # what makes an expiry an expiry is this deadline having fired, which
        # only `_interruption` can say.
        return _interruption(definition, named, deadline, entered_with) or internal_failure(
            definition, exc
        )

    interrupted = _interruption(definition, named, deadline, entered_with)
    if interrupted is not None:
        return interrupted

    try:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=output)
    except ValidationError as exc:
        # The tool returned something `FrozenJsonValue` refuses — a set, a NaN.
        # The tool is broken, and saying so is more useful than storing
        # something unserialisable (ADR-0029 §3).
        return internal_failure(definition, exc)


__all__ = [
    "BoundImplementation",
    "EgressToolImplementation",
    "ResolvedImplementation",
    "ToolImplementation",
    "checked_pairing",
    "expiry_failure",
    "internal_failure",
    "resolved_implementation",
    "run_bound_call",
    "run_prepared_call",
]

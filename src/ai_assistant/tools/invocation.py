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

from ai_assistant.core.errors import (
    ClassifiedToolError,
    ToolBindingError,
    ToolRegistrationError,
)
from ai_assistant.core.types import (
    UNREPRESENTABLE_FAULT_CLASS,
    ReportedOutput,
    ToolCost,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    fault_class_of,
)
from ai_assistant.tools.egress import IndeterminateTransmissionError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping
    from datetime import timedelta

    from ai_assistant.core.types import EgressBinding, FrozenJson, ToolCall, ToolDefinition

    #: What either callable shape may hand back: the output bare, or the output
    #: with what the call cost, in the envelope ADR-0195 §2 mints. A **widening**
    #: rather than a replacement, so every registered tool in the tree keeps
    #: type-checking untouched — a return type is covariant, and a callable
    #: returning ``FrozenJson`` satisfies this union already.
    ReportedReturn = FrozenJson | ReportedOutput

    #: What enters the bound callable once the claim has landed: a zero-argument
    #: callable returning the coroutine to await. :func:`checked_pairing` builds
    #: one, having decided the shape — so nothing about the callable is read again
    #: after the claim, and nothing is *called* before it (ADR-0192 §1).
    #:
    #: Declared here rather than at module scope because it is a name for a
    #: signature and never a value: every use is an annotation, which
    #: ``from __future__ import annotations`` leaves unevaluated, so binding it at
    #: runtime would buy three imports nothing else in this module needs.
    EntersCallable = Callable[[], Coroutine[Any, Any, ReportedReturn]]

    #: What a registration will enter, read off the object **once at
    #: registration** (:func:`resolved_implementation`). Spelled with an ellipsis
    #: because it is called only through ``functools.partial`` below, which
    #: supplies whichever keywords the resolved shape declares.
    EnteredCallable = Callable[..., Coroutine[Any, Any, ReportedReturn]]

_log = structlog.get_logger(__name__)

#: The event key a failure the tool classified is logged under. What it carries
#: is the tool's id and ``failure.kind`` — an identifier and a member of a closed
#: enum — and never the tool's message (ADR-0032 §5).
REPORTED_FAILURE = "tool_reported_failure"

#: The event key a refused ``TIMED_OUT`` is logged under: the kind is reserved to
#: the seam's own deadline, and a tool naming it is broken (ADR-0032 §3).
RESERVED_KIND = "tool_reported_reserved_kind"


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
    seam turns that into an ``INTERNAL`` result. One that **can** classify its own
    failure raises
    :class:`~ai_assistant.core.errors.ClassifiedToolError` instead, carrying a
    constructed :class:`~ai_assistant.core.types.ToolFailure` and the keyword-only
    ``effect_may_have_committed`` — whether this call's effect may already have
    landed upstream, which only the integration can know (ADR-0032 §1, §2). The
    seam translates that into a ``ToolResult``: the kind and the message cross by
    value, and the *outcome* stays the seam's ruling, conjoining the reported fact
    with the registry's own declaration. ``TIMED_OUT`` is the one member reserved
    to the seam's own deadline and is refused; an upstream that did not answer is
    ``UNAVAILABLE``, which carries the same ``retryable``.

    **A classified failure may also report what the call cost**, through that
    carrier's keyword-only ``incurred_cost`` (ADR-0195 §3) — defaulted, where
    ``effect_may_have_committed`` deliberately is not, because silence about a
    price already means "no figure".

    **It may also report what the call cost**, by returning its output inside a
    :class:`~ai_assistant.core.types.ReportedOutput` rather than bare (ADR-0195
    §2). The union is a widening and obliges nobody: returning ``FrozenJson`` is
    what every registered tool in this tree does and keeps doing. A tool that
    cannot price its own call returns bare, and the row records ``UNKNOWN``.
    """

    async def __call__(
        self,
        parameters: Mapping[str, FrozenJson],
        *,
        idempotency_key: str | None,
    ) -> ReportedReturn:
        """Perform the call and return its JSON-shaped output, priced or bare."""
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
    not widen to cover a concern its consumers do not have." ``current_time`` has no
    business being handed a
    :class:`~ai_assistant.core.types.BoundAccount` carrying an account identity —
    Tier 1 personal data (ADR-0149 §3) — merely to satisfy a signature. Widening
    the one shape would hand every tool in the system that value forever, which is
    the direction ADR-0017 §8 wants to move away from and which ADR-0152 §10
    refuses one boundary out.

    **The method is named rather than being a second ``__call__``**, because
    ``runtime_checkable`` against a ``__call__``-only Protocol matches every
    callable in the language and so could not tell the two shapes apart at all. A
    distinct name makes the discrimination structural and total.

    **The cost channel is orthogonal to this split and no third shape is minted
    for it** (ADR-0195 §2): both shapes widen in the *return* position, which they
    already share, so the registry's resolution stays a two-way branch instead of
    becoming a two-by-two matrix.

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
    ) -> ReportedReturn:
        """Perform the bound egress call and return its output, priced or bare."""
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

    The outcome is ``FAILED`` because every caller here is an exception that
    escaped: a raise is never a success and none of these paths reads a fact that
    could make it more ignorant. The classified path splits the two — it needs
    this same failure *value* under an outcome ADR-0032 §2 rules from the tool's
    own report — so the value is :func:`_internal_failure_value` and this is the
    result built from it.
    """
    return ToolResult(outcome=ToolOutcome.FAILED, failure=_internal_failure_value(definition, exc))


def _internal_failure_value(definition: ToolDefinition, exc: BaseException) -> ToolFailure:
    """The seam's own ``INTERNAL`` failure, and the one log line that goes with it."""
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
    return ToolFailure(
        kind=ToolFailureKind.INTERNAL,
        message=f"{fault} escaped tool {definition.id!r}",
    )


def indeterminate_failure(definition: ToolDefinition, exc: BaseException) -> ToolResult:
    """Report a tool that says its effect may have committed, as unknown (ADR-0148 §9).

    :class:`~ai_assistant.tools.egress.IndeterminateTransmissionError` marks one
    window and only one: the payload and its terminator are on the wire and the
    reply that would say whether the far end accepted them could not be read. It
    is deliberately not an ``EgressTransportError``, because every member of that
    hierarchy is a refusal that transmitted nothing — and until this branch existed
    the split died here, where :func:`internal_failure` flattened it into
    ``FAILED``/``INTERNAL``: an unknown disclosure recorded as one that certainly
    did not happen, which ADR-0191 §4's last clause forbids in as many words and
    ADR-0017 §3 names as the whole reason for wanting an explicit outcome
    ("otherwise a timeout is indistinguishable from a successful disclosure").
    Issue #1602, found by driving a recorder that drops the socket after ``DATA``.

    **This is the one classification here that keys on the exception's type**, and
    the exemption is narrow enough to state. The seam refuses to take a tool's word
    for ``TIMED_OUT`` or ``CANCELLED`` because both are the *seam's own* state and
    a tool claiming either would say "this did not happen" about something that
    may well have. This claim runs the other way: only the party that wrote the
    octets can know it wrote them, the seam can observe nothing about the far end,
    and a tool that raises this type — sincerely, mistakenly, or by subclassing it
    to be believed — moves the record from ``FAILED`` to ``INDETERMINATE`` and no
    further. That is the direction ADR-0014 §4 already refuses to guess in, and the
    direction with a reconciliation path.

    **The outcome is ``definition.interrupted_outcome``, not a literal
    ``INDETERMINATE``**, so the branch is correct for every declaration rather than
    for ``send_email``'s. That property is ``core``'s single answer to "a call of
    this tool, cut short, means what?" — ``FAILED`` where the tool is not
    side-effecting or its idempotency is ``NATURAL``, because neither a read nor a
    naturally idempotent act leaves an unknown behind, and ``INDETERMINATE``
    otherwise (ADR-0029 §4). It names three readers, and this is the one that had
    no implementation: "the seam again when a tool reports its effect may have
    committed". Read from the registry's committed declaration, which is what this
    seam is handed.

    **``UNAVAILABLE`` rather than ``INTERNAL``**, on both halves of the word. The
    tool is not broken — it did exactly what ADR-0191 §4 requires of it — and the
    upstream demonstrably either stopped answering or answered a refusal after the
    fact, which is what that kind names. Its ``retryable`` is ``True``, and that is
    safe here rather than in spite of the outcome: the executor's retry gate reads
    a kind only on a ``FAILED`` result (ADR-0029 §5), so it is consulted exactly
    where ``interrupted_outcome`` already established that a repeat leaves nothing
    unknown, and never on the ``INDETERMINATE`` a side-effecting tool produces.

    **The message names the state and never the wire.** It does not interpolate
    ``str(exc)`` — the seam's own text names an endpoint and a tool id, and
    ``internal_failure`` documents why a message from below is not copied outward —
    and it says neither that the call was sent nor that nothing went out, because
    the entire content of this result is that the seam cannot say which.
    """
    fault = _fault_class(exc)
    with contextlib.suppress(Exception, asyncio.CancelledError):
        # Guarded exactly as `internal_failure`'s emission is, for its reason: this
        # runs after the claim, and a processor that raised would leave this frame
        # in place of the `ToolResult` — losing the one outcome ADR-0192 §3 most
        # needs recorded.
        _log.warning(
            "tool_transmission_indeterminate",
            tool_id=definition.id,
            # The type, never the instance: rendering the exception is the leak.
            error_type=fault,
        )
    return ToolResult(
        outcome=definition.interrupted_outcome,
        failure=ToolFailure(
            kind=ToolFailureKind.UNAVAILABLE,
            message=(
                f"tool {definition.id!r} reported that it may have transmitted and could "
                f"not read the outcome, so whether the call took effect is unknown"
            ),
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


@dataclass(frozen=True, slots=True)
class _ReportedRead:
    """What one pass over a returned envelope's two fields captured (ADR-0195 §2).

    A record rather than a tuple because the ``output`` a defect leaves behind is
    not an output: the two states are "both fields read" and "the output read
    raised", and a caller that had to tell them apart by a sentinel would have to
    pick one out of ``FrozenJson``, which has none to spare — ``None`` is a
    perfectly ordinary tool output.
    """

    #: The local the single guarded read of ``output`` captured. Meaningful only
    #: where :attr:`defect` is ``None``.
    output: FrozenJson = None
    #: The validated, detached figure, or ``None`` where the tool reported none,
    #: where the round-trip refused it, or where reading it raised (ADR-0195 §4).
    cost: ToolCost | None = None
    #: What the read of ``output`` raised, where it did. The seam has nothing to
    #: record as the call's result, so this takes the ``INTERNAL`` path.
    defect: Exception | None = None


def _revalidated_cost(envelope: ReportedOutput) -> ToolCost | None:
    """Round-trip the reported figure, or answer ``None`` (ADR-0195 §4).

    **Revalidated rather than read**, in ADR-0032 §6's own idiom and for its own
    reason: ``ToolCost.model_construct`` bypasses every validator while satisfying
    ``isinstance``, so a ``PER_CALL`` basis with no amount, a ``NaN``, a negative
    amount or a ``str`` where a ``CostBasis`` belongs would otherwise reach a
    completion row and, through it, ADR-0194's arithmetic. What crosses is
    ``ToolCost.model_validate(cost.model_dump())`` — a validated, detached value.

    **The whole read runs under one ``Exception`` guard**, and that is the half
    that makes the round-trip safe rather than a refinement of it. Every step
    executes tool-authored code: the attribute access can be a property, and
    ``model_dump`` can be overridden by a ``ToolCost`` subclass — which ADR-0032
    §6 rules legitimate, "the round-trip's result is what crosses". So a raise
    from the access, the dump or the validation is caught *here* and yields the
    same ``None`` a value failing validation yields.

    That guard is load-bearing because of **where** this sits: after ADR-0192
    §1's claim has been appended. An exception escaping it would leave a claim
    with no completion — the state ADR-0192 §3 requires a completion attempt on
    every exit to prevent — over an accounting field, on a call that already ran.

    A ``BaseException`` that is not an ``Exception`` — a ``CancelledError``
    delivered from outside above all — is **propagated unchanged**, exactly as
    ADR-0029 §3, ADR-0032 §4 and ADR-0194 §4 each propagate it: a cancellation is
    not an accounting fact.

    Nothing derived from the ``ValidationError`` a refusal produces reaches a
    message or a log (ADR-0032 §5, ADR-0195 §4): it is raised *about* the reported
    value and would render it.

    Returns:
        The validated figure, or ``None`` — which the row records as an
        ``UNKNOWN`` basis, the pessimistic direction ADR-0194 §2 already fixes.
    """
    try:
        return ToolCost.model_validate(envelope.incurred_cost.model_dump())
    except Exception:
        return None


def _reported_read(envelope: ReportedOutput) -> _ReportedRead:
    """Read the envelope's two fields **once each**, under their guards (ADR-0195 §2).

    ``isinstance`` admits a **subclass**, so both fields are tool-authored reads
    and neither is read bare: a subclass overriding ``__getattribute__``, or a
    field shadowed by a property, is a defect this frame absorbs rather than an
    exception escaping after the claim has been appended.

    **One read per field, captured into locals**, because the caller must not
    find two instructions to choose between: a subclass whose first access
    succeeds and whose second raises or answers differently would otherwise put a
    different value on the ``ToolResult`` than the one this frame judged.

    **The two defects resolve differently, on their subject rather than on their
    severity.** A cost that cannot be read or does not survive the round-trip is
    discarded **alone** — the outcome, the output and the row all stand, and the
    row records ``UNKNOWN``. An ``output`` that cannot be read leaves the seam
    with nothing to record as the call's result, so it takes the ``INTERNAL``
    path an unrepresentable output already takes (ADR-0029 §3) — and the reported
    cost goes with it, unread, because the two came off one object and keeping
    half of a misbehaving carrier would be arbitrating between two accounts a
    tool gave of its own call, which ADR-0032 §6 declines to do.
    """
    try:
        output = envelope.output
    except Exception as exc:
        return _ReportedRead(defect=exc)
    return _ReportedRead(output=output, cost=_revalidated_cost(envelope))


def _succeeded(
    returned: ReportedReturn,
    *,
    definition: ToolDefinition,
    timeout: timedelta,
    deadline: asyncio.Timeout,
    entered_with: int,
) -> ToolResult:
    """Classify a normal return, unwrapping a reported cost if one came with it.

    **The order is fixed, and it is two interruption checks rather than one
    moved** (ADR-0195 §4). The caller's check keeps its place *before any
    tool-authored value is read* — that is what stops a callable which swallowed
    its own cancellation from having its accessors entered at all, the property
    ``invoke`` has today. The check here is the second one, and it exists because
    reading a tool-authored value can itself deliver a cancellation or let the
    deadline expire: a seam that checked only beforehand would build a result
    carrying a figure obtained after it had stopped waiting.

    Where that second check answers, the values read are discarded together with
    the classification they accompanied — the figure with the outcome, because
    one carrier has one fate and a row citing a report the seam ruled
    inadmissible would attribute to the tool a statement about a call the seam
    has just said it did not get to finish.

    **A malformed cost does not turn a successful call into ``INTERNAL``**, and
    the difference from the output case is the subject rather than the severity:
    discarding a real success — an act that already happened, possibly
    irreversibly — over an accounting field would destroy the record ADR-0192
    exists to write, to reach a fail-closed state the row already reaches.

    Args:
        returned: What the callable handed back — bare, or in ADR-0195 §2's
            envelope. Discriminated by ``isinstance`` and by no other test: a
            tool returning JSON that happens to carry an ``incurred_cost`` key
            returns JSON.
        definition: The registry's own declaration, used for classification.
        timeout: The figure an expiry message names.
        deadline: This seam's deadline, whose expiry only it can report.
        entered_with: The cancellation count this invocation was entered with.

    Returns:
        The classified outcome, carrying the reported figure where one survived.

    Raises:
        CancelledError: If a cancellation of the invoking task is pending — a
            read of a tool-authored value delivering one included.
    """
    cost: ToolCost | None = None
    if isinstance(returned, ReportedOutput):
        read = _reported_read(returned)
        interrupted = _interruption(definition, timeout, deadline, entered_with)
        if interrupted is not None:
            return interrupted
        if read.defect is not None:
            return internal_failure(definition, read.defect)
        returned, cost = read.output, read.cost

    try:
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=returned, incurred_cost=cost)
    except ValidationError as exc:
        # The tool returned something `FrozenJsonValue` refuses — a set, a NaN.
        # The tool is broken, and saying so is more useful than storing
        # something unserialisable (ADR-0029 §3).
        return internal_failure(definition, exc)


@dataclass(frozen=True, slots=True)
class _ClassifiedRead:
    """What one pass over a raised carrier's three attributes captured (ADR-0032 §6).

    **Every field here is the result of a guarded, independent read**, because an
    exception's attributes are ordinary attributes: ``isinstance`` is not evidence
    a pydantic model was validated, ``del exc.failure`` is as reachable as
    assigning ``None`` to it, and either access may be a property a tool wrote.
    The reads are by sentinel — ``None`` for each — so the total path is total,
    and a defect in one does not take the others down with it: "a ``failure``
    property that explodes must not take the ``bool`` down with it".

    Judging them is :func:`_classified_result`'s, deliberately, so that nothing
    between the two reads and the ``ToolResult`` runs tool-supplied code: the
    caller re-reads the interruption state in that gap (ADR-0032 §4).
    """

    #: The revalidated, detached failure, or ``None`` where the payload did not
    #: survive — absent, not a ``ToolFailure``, refused by the round-trip, or a
    #: read that raised. A refused payload costs the *kind* and nothing else.
    failure: ToolFailure | None = None
    #: The validated fact, or ``None`` where it was absent, was not a ``bool``, or
    #: the read raised — which refuses the **whole** carrier (§6).
    committed: bool | None = None
    #: The validated, detached figure, or ``None`` where the tool reported none,
    #: where the round-trip refused it, or where reading it raised (ADR-0195 §4).
    cost: ToolCost | None = None


def _revalidated_failure(exc: ClassifiedToolError) -> ToolFailure | None:
    """Round-trip the raised payload, or answer ``None`` (ADR-0032 §6).

    **Revalidated rather than read**, because ``isinstance`` is not evidence that
    a pydantic model was validated: ``ToolFailure.model_construct(kind=
    "rate_limited", message=" ")`` bypasses every validator, satisfies
    ``isinstance``, and carries a ``str`` where a ``ToolFailureKind`` belongs — so
    a downstream ``result.failure.kind.retryable`` would be an ``AttributeError``
    rather than a retry decision. ``model_validate`` on the instance does not
    help: pydantic's default ``revalidate_instances="never"`` returns it
    unchanged.

    **The round-trip repairs what it can and refuses what it cannot, and the line
    between them is pydantic's own.** ``"rate_limited"`` names a member, so
    validation coerces it and the result is a correct ``ToolFailure``; a string
    naming no member, a missing field, or a message that renders as nothing does
    not survive. Requiring an exact runtime type instead would refuse a value
    pydantic can make correct, for no gain — the obligation is that what reaches a
    ``ToolResult`` is valid, not that the tool built it in the approved way.

    **What crosses is the round-trip's result**, so a subclass overriding
    ``model_dump()`` to return a different valid failure yields that one. Not a
    hole: the tool authored both accounts and could have raised the dumped one,
    and a seam arbitrating between two stories a tool tells about its own failure
    would be settling a dispute neither side has an interest in. For any failure
    built through ``ToolFailure(...)`` the round-trip is a pass-through.

    **The whole read runs under one ``Exception`` guard**, and that is what makes
    it safe rather than a refinement of it. ``isinstance`` admits a subclass, so
    ``exc.failure`` is an access a tool may have made a property and
    ``model_dump()`` is a dispatch to a method a tool may have overridden — and an
    exception raised inside an ``except`` body is **not** caught by the sibling
    ``except`` clauses of the same ``try``, so an unguarded read would leave
    ``invoke`` uncaught where the rule requires a result. ``BaseException``
    propagates unchanged, as ADR-0029 §3 requires everywhere else.

    Nothing derived from the ``ValidationError`` a refusal produces enters a
    message or a log (§5): it is raised *about* the payload and would render it.
    """
    try:
        # Typed as `object` so every check below is over the **value**. The
        # annotation is not the enforcement anywhere in this seam (ADR-0029 §4),
        # and least of all here: an exception's attributes are ordinary
        # attributes, an integration is not required to have been type-checked,
        # and `del exc.failure` is as reachable as assigning `None` to it.
        failure: object = exc.failure
        if not isinstance(failure, ToolFailure):
            return None
        return ToolFailure.model_validate(failure.model_dump())
    except Exception:
        return None


def _validated_fact(exc: ClassifiedToolError) -> bool | None:
    """Read ``effect_may_have_committed``, or answer ``None`` (ADR-0032 §6).

    ``None`` means the carrier is refused whole, not that the fact was ``False``:
    a carrier missing a *required, keyword-only* argument never went through
    ``__init__``, so nothing about it was checked, and reporting a confident
    ``RATE_LIMITED`` off it would be the seam authorising a retry on the strength
    of an object assembled around its own constructor.

    Read under its own guard and judged on its own, so that a payload which
    explodes cannot take it down — which is what lets a garbage payload raised
    with a sound ``True`` still reach ``INDETERMINATE``.
    """
    try:
        # `object` for `_revalidated_failure`'s reason: the check is over the
        # value, not over what the annotation promises about it.
        committed: object = exc.effect_may_have_committed
    except Exception:
        return None
    return committed if isinstance(committed, bool) else None


def _revalidated_incurred_cost(exc: ClassifiedToolError) -> ToolCost | None:
    """Round-trip the reported figure, or answer ``None`` (ADR-0195 §3, §4).

    The classified-failure exit's half of the rule :func:`_revalidated_cost`
    applies at the success exit, in ADR-0032 §6's own idiom and under the same
    single ``Exception`` guard, for the same reason: every step of it —
    the attribute access, ``model_dump()``, the validation — is tool-authored
    code, and this runs after ADR-0192 §1's claim has been appended.

    A cost that does not survive is discarded **alone**: the outcome, the failure
    and ``effect_may_have_committed`` all stand and the row records an ``UNKNOWN``
    basis, which is §6's "each defect resolves in its own pessimistic direction"
    applied to a field whose pessimistic direction ADR-0194 §2 already fixes.

    The field is **defaulted** where the fact is not, so ``None`` is the ordinary
    answer rather than a defect: silence about a price already means "no figure",
    while silence about a side effect would assert one.
    """
    try:
        # No type test, exactly as the success exit's `_revalidated_cost` makes
        # none: what crosses is the round-trip's result (ADR-0032 §6), and an
        # object whose `model_dump()` yields a valid figure reports a figure the
        # tool could have reported directly. `None` is the field's own default
        # and the ordinary answer, so it is answered before the dump rather than
        # through the `AttributeError` one would raise.
        cost = exc.incurred_cost
        if cost is None:
            return None
        return ToolCost.model_validate(cost.model_dump())
    except Exception:
        return None


def _classified_read(exc: ClassifiedToolError) -> _ClassifiedRead:
    """Read the carrier's three attributes, each under its own guard (ADR-0032 §6).

    Every tool-authored read this exit performs happens here and nowhere else, so
    the caller can put ADR-0032 §4's re-read of the interruption state between
    this and the result: reading the carrier is what opens the window — a
    ``model_dump()`` that calls ``cancel()`` on the invoking task and then returns
    valid data raises the delta *between* the handler's first check and the result
    — so the re-read closes it where it is opened.
    """
    return _ClassifiedRead(
        failure=_revalidated_failure(exc),
        committed=_validated_fact(exc),
        cost=_revalidated_incurred_cost(exc),
    )


def _reserved_kind_failure(definition: ToolDefinition) -> ToolFailure:
    """The seam's own ``INTERNAL`` for a tool naming the reserved kind (ADR-0032 §3).

    ``TIMED_OUT`` means **this** seam's deadline expired, which the seam must
    establish rather than infer, so a raised failure naming it is refused: the
    tool-authored ``ToolFailure`` is discarded whole and this is synthesised in its
    place, naming the reserved kind and the tool's id and nothing else.

    **Refused rather than remapped to a neighbour.** ``UNAVAILABLE`` is what the
    tool should have raised and the seam must not choose it on the tool's behalf —
    that is the seam interpreting a broken integration's meaning, one step from
    interpolating its text. ``INTERNAL`` is what the vocabulary already means by
    "the tool implementation is broken", and a tool naming a kind the contract
    reserves *is* broken. It fails safe: ``INTERNAL`` is not retryable, so nothing
    is retried on the strength of a claim the seam rejected. The cost is nil — an
    honest ``UNAVAILABLE`` carries the same ``retryable=True``.

    ``effect_may_have_committed`` is **not** discarded with the payload: a tool
    that got the kind wrong may still be telling the truth about its side effect,
    and dropping that would record a possible commit as certainly-nothing-happened.
    """
    with contextlib.suppress(Exception, asyncio.CancelledError):
        # Guarded for `internal_failure`'s reason: this runs after the claim, and
        # a processor that raised would leave this frame in place of the result.
        # What is logged is the tool's id and a member of a closed enum — §5's
        # whole permitted vocabulary for a log line about a translated failure.
        _log.warning(
            RESERVED_KIND,
            tool_id=definition.id,
            kind=ToolFailureKind.TIMED_OUT,
        )
    return ToolFailure(
        kind=ToolFailureKind.INTERNAL,
        message=(
            f"tool {definition.id!r} reported {ToolFailureKind.TIMED_OUT.value!r}, "
            f"a kind reserved to this seam's own deadline"
        ),
    )


def _translated_failure(definition: ToolDefinition, failure: ToolFailure) -> ToolFailure:
    """Pass the tool's own failure through by value, logging neither half of it (§5).

    **The seam either passes the raised ``ToolFailure`` through by value or
    discards it whole**, and there is no third behaviour: it never edits, wraps,
    prefixes, truncates or re-authors a tool's message. "By value" is through §6's
    revalidation, which applies ``ToolFailure``'s **own** validators and nothing
    else, so a message is stripped exactly as ``ToolFailure(...)`` would have
    stripped it at the raise site and is otherwise untouched.

    **The log line carries the tool's id and the kind, and never the message** —
    even though that message is Tier 2 and the tool's own. The natural log line
    includes it, because it is the useful part, and that is precisely why the rule
    is stated rather than assumed: the message lands in ``ToolResult.failure.
    message`` and nowhere else *by the seam's hand*. Its onward destinations are
    the executor's, and the seam declining to log it does not stop it being logged
    one frame away — which is why ADR-0029 §3's Tier 2 obligation on the producer
    is the only real defence.

    And nothing derived from the exception object goes anywhere: not ``str(exc)``,
    ``repr(exc)``, ``exc.args``, ``exc.__cause__``, ``exc.__context__`` or
    ``exc.__notes__``. The cause chain is the specific hazard — ``raise
    ClassifiedToolError(...) from upstream_exc`` is good practice and is exactly
    where an upstream's error body lives — so keeping it out of everything the
    seam renders is what makes ``from`` safe to write.
    """
    with contextlib.suppress(Exception, asyncio.CancelledError):
        _log.warning(REPORTED_FAILURE, tool_id=definition.id, kind=failure.kind)
    return failure


def _classified(
    exc: ClassifiedToolError,
    *,
    definition: ToolDefinition,
    timeout: timedelta,
    deadline: asyncio.Timeout,
    entered_with: int,
) -> ToolResult:
    """Translate a raised carrier, bracketed by ADR-0032 §4's two checks.

    **The senior signals are read first, and where either answers the carrier is
    discarded whole — fact, figure and all — with no attribute of it touched.** A
    cancellation of the invoking task is rank 1: the classified raise may itself
    be a consequence of it, an SDK mapping its aborted request to ``UNAVAILABLE``
    on the way out, and answering a cancellation with a value is what ADR-0029 §4
    forbids everywhere. This seam's expired deadline is rank 2, and it is the same
    "establish, don't infer" rule applied to a claim instead of to an exception
    type: a tool that maps its aborted request to ``UNAVAILABLE`` while the
    deadline actually fired would, on a side-effecting non-``NATURAL`` tool,
    produce ``FAILED`` — certainly-nothing-happened for a call that outran its
    budget. Discarding the fact there loses nothing: on that path the outcome is
    ``interrupted_outcome`` alone, which is ``INDETERMINATE`` in every case where
    the fact could have mattered.

    **The second check is not the first one moved.** ADR-0031 §2(b)'s
    postcondition names ``SUCCEEDED`` because a normal return was once the only
    path that built a result from something the callable produced; ADR-0032 §4
    states it for *any* result, because §6's revalidation is itself tool-supplied
    code that runs between the two. A ``ToolFailure`` subclass whose
    ``model_dump()`` calls ``cancel()`` on the invoking task and then answers
    normally raises the delta in exactly that gap, and a seam checking only on
    entry would return a ``FAILED`` result from a task carrying a pending
    cancellation — rank 1 violated by the mechanism §6 introduced. It precedes the
    refusal path too: a ``model_dump()`` that cancels and *then* raises leaves the
    same delta, so an implementation re-reading only after a successful
    translation still returns a result from a cancelled task.

    Raises:
        CancelledError: If a cancellation of the invoking task is pending — one
            delivered by a read of the carrier included.
    """
    interrupted = _interruption(definition, timeout, deadline, entered_with)
    if interrupted is not None:
        return interrupted
    read = _classified_read(exc)
    interrupted = _interruption(definition, timeout, deadline, entered_with)
    if interrupted is not None:
        return interrupted
    return _classified_result(definition, exc, read)


def _classified_result(
    definition: ToolDefinition, exc: ClassifiedToolError, read: _ClassifiedRead
) -> ToolResult:
    """Rule the outcome and choose the failure, over values already read (ADR-0032 §2).

    **Kind is what the tool knows; outcome is what the seam rules.** The rule is
    one line — ``INDETERMINATE`` when the tool reports its effect may have
    committed **and** the registry's ``definition.interrupted_outcome`` is
    ``INDETERMINATE``, ``FAILED`` otherwise — and ``definition`` is the registry's
    own declaration, never ``call.request.tool``.

    **The conjunction rather than the fact alone**, case by case: a *read-only*
    tool reporting a possible commit is contradicting the declaration the policy
    approved, so the fact is ignored and the outcome is ``FAILED``; a ``NATURAL``
    tool is idempotent by nature, so ignorance costs nothing and ``FAILED`` is
    correct; a ``NONE`` or ``KEYED`` side-effecting tool is ADR-0014 §4's case
    exactly, reached through a transport failure rather than a crash, so
    ``INDETERMINATE``. Conjoining rather than restating is deliberate: writing
    ``not side_effecting or idempotency is NATURAL`` here would be the fourth copy
    of a safety-critical ordering ADR-0031 §1 moved into ``core`` to have one of.

    **The report is monotone.** No value of the fact produces ``SUCCEEDED`` — a
    raise is never a success — and none overrides the seam's own expiry or
    cancellation, which outrank it entirely (§4). The worst a lying or careless
    integration achieves is ``INDETERMINATE`` for a call that definitely failed:
    pessimistic, not auto-retried, resolved explicitly.

    **The asymmetry between the two defects is the rule rather than an
    inconsistency in it.** A bad payload costs the *kind*, because what a refused
    kind costs is a ``retryable=True`` the seam has no reason to trust and
    ``INTERNAL`` is the fail-closed answer. A bad fact costs the *carrier*,
    because the lost value might be ``True`` and losing it would record a possible
    commit as certainly-nothing-happened — ADR-0014 §4's forbidden guess. Both
    point the same way, toward the outcome that retries less and knows less.

    **A refused carrier takes its reported figure with it, and a refused payload
    does not** (ADR-0195 §4). §6 refuses "the *whole* carrier" when the fact does
    not validate, and a figure read off an object that never went through its own
    constructor is a price stated by the same unchecked object whose kind is being
    refused for that reason — so the row records ``UNKNOWN``, which is that
    field's own pessimistic direction. Where only the payload is refused the
    carrier itself went through ``__init__``, the figure is an ordinary attribute
    revalidated on its own, and §6's independence rule keeps it: a malformed
    payload costs the kind, a malformed cost costs the cost.
    """
    if read.committed is None:
        return ToolResult(
            outcome=ToolOutcome.FAILED, failure=_internal_failure_value(definition, exc)
        )
    if read.failure is None:
        failure = _internal_failure_value(definition, exc)
    elif read.failure.kind is ToolFailureKind.TIMED_OUT:
        failure = _reserved_kind_failure(definition)
    else:
        failure = _translated_failure(definition, read.failure)
    indeterminate = read.committed and definition.interrupted_outcome is ToolOutcome.INDETERMINATE
    return ToolResult(
        outcome=ToolOutcome.INDETERMINATE if indeterminate else ToolOutcome.FAILED,
        failure=failure,
        incurred_cost=read.cost,
    )


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
    - ``INDETERMINATE`` is the one that *does* read a type, and reads it in the
      only direction a tool may be believed in: an
      :class:`~ai_assistant.tools.egress.IndeterminateTransmissionError` says the
      effect may already have committed, which nothing out here can observe and
      which moves the record away from "certainly did not happen" rather than
      towards it (:func:`indeterminate_failure`, ADR-0148 §9, ADR-0191 §4).
    - **Neither of the first two is inferred from what the callable did**, because a
      callable that catches a cancellation and returns a value leaves the seam
      holding an output and no exception at all. So the deadline and the task
      are read directly, on the normal-return path as well as the raising one —
      see :func:`_interruption`. Without that, a cancelled turn comes back
      ``SUCCEEDED``, and a side-effecting call that outran its deadline comes
      back as though it had met it.
    - **A normal return may be an envelope**, and :func:`_succeeded` owns what
      happens then: ADR-0195 §2's ``ReportedOutput`` is unwrapped here and
      travels no further, its figure revalidated onto
      ``ToolResult.incurred_cost``. The interruption check stays *before* any
      field of it is read, and a second one follows the reads (§4).
    - **A raise may be a classified failure**, and it is the only branch that
      takes the tool's own account of *why* — :class:`~ai_assistant.core.errors.
      ClassifiedToolError` is caught here, revalidated (:func:`_classified_read`)
      and ruled (:func:`_classified_result`). It is ranked **below** both senior
      signals, so a cancellation or this seam's expired deadline discards it whole
      before an attribute of it is touched, and the same two interruption checks
      bracket the reads. The carrier never escapes ``invoke``.

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
    except IndeterminateTransmissionError as exc:
        # Ahead of the generic branch, and **behind** `_interruption`, which is not
        # an ordering to tidy: `_interruption` re-raises a pending external
        # cancellation, and swallowing one to answer with a result would break
        # structured concurrency (ADR-0029 §4). Where it answers instead, its
        # answer carries the same `interrupted_outcome` this branch would, so the
        # record does not turn on which of the two spoke.
        return _interruption(definition, named, deadline, entered_with) or indeterminate_failure(
            definition, exc
        )
    except ClassifiedToolError as exc:
        # ADR-0032 §4's third rank, and it sits exactly where the `except
        # Exception` clause below sits — after the interruption check, never
        # before it. `IndeterminateTransmissionError` above is a `ToolError` and
        # this is deliberately not one (§1), so the two hierarchies are disjoint
        # and the order between them decides nothing reachable.
        #
        # `_classified` owns the rest, including the two interruption checks that
        # bracket every tool-authored read of the carrier (§4, ADR-0195 §4).
        return _classified(
            exc,
            definition=definition,
            timeout=named,
            deadline=deadline,
            entered_with=entered_with,
        )
    except Exception as exc:
        # Python's own `TimeoutError` arrives here too, and is *not* special:
        # what makes an expiry an expiry is this deadline having fired, which
        # only `_interruption` can say.
        return _interruption(definition, named, deadline, entered_with) or internal_failure(
            definition, exc
        )

    # ADR-0195 §4's **first** interruption check, keeping the place it already
    # had: a call this seam has ruled interrupted has nothing read off what it
    # returned, so a hostile accessor on the envelope is never entered at all.
    interrupted = _interruption(definition, named, deadline, entered_with)
    if interrupted is not None:
        return interrupted

    return _succeeded(
        output,
        definition=definition,
        timeout=named,
        deadline=deadline,
        entered_with=entered_with,
    )


__all__ = [
    "REPORTED_FAILURE",
    "RESERVED_KIND",
    "BoundImplementation",
    "EgressToolImplementation",
    "ResolvedImplementation",
    "ToolImplementation",
    "checked_pairing",
    "expiry_failure",
    "indeterminate_failure",
    "internal_failure",
    "resolved_implementation",
    "run_bound_call",
    "run_prepared_call",
]

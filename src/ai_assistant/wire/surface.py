"""The promoted surface, read off the Protocol rather than transcribed.

ADR-0085 §10 assigns the per-method wire mapping, and says it "follows
mechanically from §3's own rules once the signatures are fixed, so it is stated
compactly rather than method by method". This module is that mechanical step,
taken mechanically: the argument names, their types and each method's return type
are read from :class:`~ai_assistant.core.protocols.AssistantEngine` itself.

**A transcribed table would be a second vocabulary to keep in step with the
first**, which is the objection ADR-0085 §4 raises to mapping ``Disposition`` to a
bare string and §10a raises to a hand-kept error registry. It applies with more
force here: the Protocol carries dozens of methods and more parameters again, a
Protocol change costs an ADR and would arrive with no mechanical signal that the
wire had been left behind, and the divergence would surface as one implementation
quietly ignoring an argument the other honours. Reading the annotations makes the
mapping *total by construction* — a method the Protocol grows is a method this
module already knows about, and one whose type the wire cannot carry fails loudly
at import rather than silently at the first call.

**The figures are named by their owner rather than written down** (#1125,
`CONTRIBUTING.md` -> "No state claims in living documents"). This paragraph read
"nineteen methods and twenty-nine parameters" against a Protocol that had grown
past both, which is precisely the failure the module argues against, one level up:
a transcribed number is a second vocabulary too. ``tests/core/
test_engine_surface_closure.py`` is what pins the method count, and ``METHODS``
below is what makes the parameter count unnecessary to state at all.

**ADR-0102 and ADR-0151 are the evidence this was right.** ADR-0102 put four
methods and one error class on the surface, and §12 item 5 records the
consequence: nothing in this module changed, and nothing in ``wire/errors.py``
either. ADR-0151 put **five** methods and seven error classes on it and §11 says
the same before the fact — "Nothing in ``wire/`` changes but the client's five
methods" — which held: ``METHODS``, the argument and result adapters and the error
code are all derived from the contract, so a credential-carrying argument reached
the wire correctly because its annotation said what it was.

**ADR-0173 §4 adds a rule here rather than an exception**, and the shape is the
same one: "a method whose return annotation is an async iterator is adapted by one
adapter per member of the yielded union, selected by the frame kind being decoded,
where a non-streaming method keeps its single result adapter built from its return
annotation. No method is adapted by both rules." Which methods those are is read
off the Protocol (:data:`STREAMING_METHODS`) exactly as everything else here is, so
a second streaming method is a method this module already knows about.

**The annotations are resolved against ``core.types``' namespace** because
``core/protocols.py`` imports its types under ``if TYPE_CHECKING``. That is a fact
about how the contract module is written, not a coupling this module chooses.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from functools import cache
from typing import Any, Final, get_args, get_origin

from pydantic import TypeAdapter

from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import AssistantEngine

#: The names ``core/protocols.py`` leaves unresolved at runtime, plus the three
#: standard-library names its signatures use.
_NAMESPACE: Final[dict[str, Any]] = {
    **vars(core_types),
    "timedelta": timedelta,
    "Sequence": Sequence,
    "AsyncIterator": AsyncIterator,
}

#: The method name the envelope's ``method`` member carries (ADR-0085 §8a) — the
#: ``AssistantEngine`` method name, unmodified. Frozen so a caller cannot widen it,
#: and derived so it cannot fall behind the Protocol.
METHODS: Final[frozenset[str]] = frozenset(
    name
    for name, member in vars(AssistantEngine).items()
    if not name.startswith("_") and inspect.isfunction(member)
)


@cache
def _hints(method: str) -> dict[str, Any]:
    """The resolved annotations of one Protocol method.

    Args:
        method: The method's name.

    Returns:
        Its parameter and return annotations.

    Raises:
        KeyError: If the Protocol declares no such method.
    """
    if method not in METHODS:
        raise KeyError(method)
    return typing.get_type_hints(getattr(AssistantEngine, method), localns=_NAMESPACE)


@cache
def parameters(method: str) -> tuple[str, ...]:
    """The names of one method's arguments, in declaration order.

    Args:
        method: The method's name.

    Returns:
        The parameter names, ``self`` excluded.

    Raises:
        KeyError: If the Protocol declares no such method.
    """
    if method not in METHODS:
        raise KeyError(method)
    signature = inspect.signature(getattr(AssistantEngine, method))
    return tuple(name for name in signature.parameters if name != "self")


@cache
def argument_adapter(method: str, parameter: str) -> TypeAdapter[Any]:
    """A validator for one argument, from the Protocol's own annotation.

    This is where ADR-0087 §7's ordering is honoured on the receiving side:
    "**the order is decode, then validate, then measure**, and it is fixed rather
    than left to an implementation. A value with no canonical form must not reach
    the measurement step." Measuring first is not merely fussy but unsatisfiable —
    ``1e999`` is well-formed JSON that decodes to ``float("inf")``, which ADR-0087
    §2c gives no encoding at all.

    Args:
        method: The method's name.
        parameter: The argument's name.

    Returns:
        A :class:`~pydantic.TypeAdapter` over the declared annotation.

    Raises:
        KeyError: If the Protocol declares no such method or argument.
    """
    return TypeAdapter[Any](_hints(method)[parameter])


def _yielded(method: str) -> tuple[Any, ...] | None:
    """The union a streaming method yields, chunk first, or ``None`` if it is not one.

    **Read off the annotation rather than listed**, exactly as everything else in
    this module is: a method is streaming when its declared return is an async
    iterator, which is a fact about the Protocol and not a name a table here would
    have to be kept in step with.

    **The order is the convention, and it is deliberately the annotation's own.**
    ADR-0173 §4 fixes the union as ``ReplyChunk | TurnOutcome`` and gives it a
    one-to-one map onto the frames — a chunk frame carries the first member, the
    terminal result frame the last — so writing the yielded union chunk-first,
    terminal-last is what a streaming method on this surface declares.
    ``tests/core/test_engine_surface_closure.py`` pins it, so a second streaming
    method written the other way round fails there rather than at a client.
    """
    annotation = _hints(method)["return"]
    if get_origin(annotation) is not AsyncIterator:
        return None
    members = get_args(get_args(annotation)[0])
    if len(members) < 2:  # noqa: PLR2004 — a union of one is not a union
        msg = f"{method}() streams a single type; ADR-0173 §4's union has two members"
        raise TypeError(msg)
    return members


#: The methods a transport adapts with ADR-0173 §4's second rule — "a method whose
#: return annotation is an async iterator is adapted by **one adapter per member of
#: the yielded union**, selected by the frame kind being decoded, where a
#: non-streaming method keeps its single result adapter built from its return
#: annotation. No method is adapted by both rules."
STREAMING_METHODS: Final[frozenset[str]] = frozenset(
    name for name in METHODS if _yielded(name) is not None
)


@cache
def return_adapter(method: str) -> TypeAdapter[Any]:
    """A validator for one method's result, from its declared return annotation.

    ADR-0085 §10: "A **result** payload takes the shape of the method's own
    declared return annotation, so it follows the signature rather than a second
    declaration."

    Args:
        method: The method's name.

    Returns:
        A :class:`~pydantic.TypeAdapter` over the declared return type.

    Raises:
        KeyError: If the Protocol declares no such method, or if it is a streaming
            one — whose answer is many frames rather than a result, and which
            ADR-0173 §4 adapts by :func:`chunk_adapter` and :func:`terminal_adapter`
            instead. "No method is adapted by both rules", so this refuses rather
            than returning an adapter over an iterator type nothing can validate.
    """
    if method in STREAMING_METHODS:
        raise KeyError(method)
    return TypeAdapter[Any](_hints(method)["return"])


@cache
def chunk_type(method: str) -> Any:
    """The type one streaming method's chunk frames carry (ADR-0173 §4).

    What a *writer* needs where :func:`chunk_adapter` is what a reader needs: the
    server holds already-built values and has to say which frame kind each one is,
    and ADR-0173 §4 makes that the Protocol's answer rather than a name transcribed
    into the transport.

    Args:
        method: The method's name.

    Returns:
        The first member of the yielded union.

    Raises:
        KeyError: If the Protocol declares no such method, or it does not stream.
    """
    members = _yielded(method)
    if members is None:
        raise KeyError(method)
    return members[0]


@cache
def chunk_adapter(method: str) -> TypeAdapter[Any]:
    """A validator for one streaming method's chunk-frame payload (ADR-0173 §4).

    Args:
        method: The method's name.

    Returns:
        A :class:`~pydantic.TypeAdapter` over the first member of the yielded union.

    Raises:
        KeyError: If the Protocol declares no such method, or it does not stream.
    """
    members = _yielded(method)
    if members is None:
        raise KeyError(method)
    return TypeAdapter[Any](members[0])


@cache
def terminal_adapter(method: str) -> TypeAdapter[Any]:
    """A validator for one streaming method's terminal result payload (ADR-0173 §4).

    Args:
        method: The method's name.

    Returns:
        A :class:`~pydantic.TypeAdapter` over the last member of the yielded union.

    Raises:
        KeyError: If the Protocol declares no such method, or it does not stream.
    """
    members = _yielded(method)
    if members is None:
        raise KeyError(method)
    return TypeAdapter[Any](members[-1])

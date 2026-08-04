"""The promoted surface, read off the Protocol rather than transcribed.

ADR-0085 §10 assigns the per-method wire mapping, and says it "follows
mechanically from §3's own rules once the signatures are fixed, so it is stated
compactly rather than method by method". This module is that mechanical step,
taken mechanically: the argument names, their types and each method's return type
are read from :class:`~ai_assistant.core.protocols.AssistantEngine` itself.

**A transcribed table would be a second vocabulary to keep in step with the
first**, which is the objection ADR-0085 §4 raises to mapping ``Disposition`` to a
bare string and §10a raises to a hand-kept error registry. It applies with more
force here: the Protocol carries nineteen methods and twenty-nine parameters, a
Protocol change costs an ADR and would arrive with no mechanical signal that the
wire had been left behind, and the divergence would surface as one implementation
quietly ignoring an argument the other honours. Reading the annotations makes the
mapping *total by construction* — a method the Protocol grows is a method this
module already knows about, and one whose type the wire cannot carry fails loudly
at import rather than silently at the first call.

**ADR-0102 is the evidence that was right.** It put four methods and one error
class on the surface, and §12 item 5 records the consequence: nothing in this
module changed, and nothing in ``wire/errors.py`` either, because ``METHODS``, the
argument and result adapters and the error code are all derived from the contract.
Only the figures in the paragraph above moved, and only because they are prose.

**The annotations are resolved against ``core.types``' namespace** because
``core/protocols.py`` imports its types under ``if TYPE_CHECKING``. That is a fact
about how the contract module is written, not a coupling this module chooses.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Sequence
from datetime import timedelta
from functools import cache
from typing import Any, Final

from pydantic import TypeAdapter

from ai_assistant.core import types as core_types
from ai_assistant.core.protocols import AssistantEngine

#: The names ``core/protocols.py`` leaves unresolved at runtime, plus the two
#: standard-library names its signatures use.
_NAMESPACE: Final[dict[str, Any]] = {
    **vars(core_types),
    "timedelta": timedelta,
    "Sequence": Sequence,
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
        KeyError: If the Protocol declares no such method.
    """
    return TypeAdapter[Any](_hints(method)["return"])

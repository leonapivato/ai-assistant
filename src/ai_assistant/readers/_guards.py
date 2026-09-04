"""The one read a constructor guard makes of the value it is about to refuse.

Every reader in this package refuses a configured value it was handed by a direct
caller, and every such refusal names the value's **type** rather than the value:
the refused object is of arbitrary type, so its own ``__repr__`` would run inside
the message that refuses it and a hostile one raises straight past the guard
(#1978). Reaching for the type name is then the same problem one level in, which
is what :func:`type_name_of` closes.

**A shared home in this package, decided rather than accreted** (#2110). This
module is the first in ``readers/`` that exists for a *cross-reader* helper rather
than for a bounded capability, and that is the shape #2110 chose over three copies
maintained in step: the guard is one rule with one statement of it, and the next
reader that refuses a value of arbitrary type imports it here instead of writing a
fourth. What belongs here is that narrow thing — a helper every reader's *guards*
need — and not reader logic, which stays in the reader or in the module of the
capability it belongs to.

**:func:`~ai_assistant.core.types.fault_class_of` cannot serve and is not
duplicated by this.** It is the canonical statement of the same guarded read and
this mirrors its shape, but it takes an ``Exception`` because it classifies a
fault, where a configuration guard refuses a value of arbitrary type. Widening its
parameter to ``object`` would put a trace-formatting function on a configuration
path and make a ``core/types.py`` change out of a readability preference (golden
rule 5), which is why the shared home is here and the shared *rule* is cited
rather than imported across the boundary.
"""

from __future__ import annotations

from typing import Final

#: What a type refusal names when the type will not say what it is called.
UNNAMEABLE_TYPE: Final = "an unnameable type"


def type_name_of(value: object) -> str:
    """``type(value).__name__``, or a fixed literal where reading it will not answer.

    **The name read is itself a call into the refused object's class**, which is
    the half of #1978 that survived substituting ``repr``: a metaclass may
    override ``__getattribute__`` for ``"__name__"`` and raise, or answer with
    something that is not a built-in ``str`` whose own rendering then raises.
    Either takes the refusal down with the value it was refusing — the same
    wrong-exception-class escape one level in, so a guard that reaches for a type
    name owes this read the same distrust it gives the value.

    :func:`~ai_assistant.core.types.fault_class_of` guards the same read for the
    same reason and this mirrors its shape rather than inventing a second one:
    ``Exception`` is caught and ``BaseException`` is **not**, so a
    ``CancelledError`` raised by the name read is delivered onward (ADR-0060 §1).
    ``type(name) is str`` rather than ``isinstance``, because a ``str`` subclass is
    a second object with a second chance to raise and this one is asked to render
    itself into the message.

    Args:
        value: The refused object, asked only what its type is called.

    Returns:
        The type's name, or :data:`UNNAMEABLE_TYPE` where it could not be read.
    """
    try:
        name = type(value).__name__
        nameable = type(name) is str and bool(name)
    # A blind `except Exception` on purpose — see the docstring; `BaseException`
    # is deliberately not caught. `BLE` is not enabled in this tree and `RUF100`
    # fails the gate on an unused directive, so the reason stays a comment.
    except Exception:
        return UNNAMEABLE_TYPE
    return name if nameable else UNNAMEABLE_TYPE

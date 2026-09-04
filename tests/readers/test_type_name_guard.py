"""The readers' one guarded type-name read, proved where it is now written.

``readers/calendar.py``, ``readers/email.py`` and ``readers/files.py`` each held
their own copy of this function, and each was proved only *through* its own
guards — so its branches were asserted many times over at the seams and never
once against the function. #2110 collapsed the three into
``readers/_guards.py``; this is that module's own suite, and the seam arms in the
three reader suites stay exactly where they are, because what they prove is that
each reader still routes its refusals through this read.

**Two branches reach no seam at all**, which is what a shared home buys: a
``__name__`` that answers with an *empty* ``str``, and one that answers with a
``str`` **subclass**. Neither is reachable through a reader's constructor without
a probe built for it, and the second is the whole reason the read tests
``type(name) is str`` rather than ``isinstance`` — a subclass is a second object
with a second chance to raise, and it is asked to render itself into the message.

**The ``BaseException`` half of ADR-0060 §1 is asserted here too.** Every copy's
docstring claimed a ``CancelledError`` raised by the name read is delivered
onward rather than swallowed into the literal, and no arm anywhere asked. A blind
``except Exception`` that grew a ``BaseException`` would pass every seam arm in
the tree.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from hostile_values import UNNAMEABLE_KINDS, ClassRaises, Hostile, impostor_of, unnameable

from ai_assistant.readers._guards import UNNAMEABLE_TYPE, type_name_of


class _EmptyName(type):
    """A metaclass answering ``__name__`` with the empty ``str``.

    A name that reads without raising and is a built-in ``str`` still says nothing:
    ``got `` is a refusal that names no type. The ``bool(name)`` half of the read
    is the only thing standing between that message and a caller, and no reader's
    constructor can be handed a class built this way without a probe for it.
    """

    @property
    def __name__(cls) -> Any:  # type: ignore[override]  # the hostile case, on purpose
        return ""


class _SubclassName(str):
    """A ``str`` subclass that raises when the message asks it to render."""

    def __str__(self) -> str:
        raise RuntimeError("a hostile __name__ subclass must not raise past a guard")

    def __repr__(self) -> str:
        raise RuntimeError("a hostile __name__ subclass must not raise past a guard")


class _SubclassedName(type):
    """A metaclass whose ``__name__`` is a ``str`` subclass rather than a ``str``.

    ``isinstance(name, str)`` admits this and the read would then hand the message
    a second object with a second chance to raise — which :class:`_SubclassName`
    takes. ``type(name) is str`` is what refuses it.
    """

    @property
    def __name__(cls) -> Any:  # type: ignore[override]  # the hostile case, on purpose
        return _SubclassName("Evil")


class _CancelledName(type):
    """A metaclass whose ``__name__`` raises a ``BaseException``.

    ADR-0060 §1's line, at this read: a cancellation is not a fault to classify
    and must reach the caller rather than being absorbed into a refusal message.
    """

    def __getattribute__(cls, name: str) -> object:
        if name == "__name__":
            raise asyncio.CancelledError
        return super().__getattribute__(name)


def test_an_ordinary_value_is_named_by_its_type() -> None:
    """The answer in the case every refusal is built for."""
    assert type_name_of(3) == "int"
    assert type_name_of("configured") == "str"


def test_an_object_that_will_not_render_is_still_named() -> None:
    """The point of naming the type rather than the value (#1978).

    :class:`Hostile` raises from ``__repr__``, which is what a refusal built with
    ``repr`` would have called — and this read never asks the value anything.
    """
    assert type_name_of(Hostile()) == "Hostile"


@pytest.mark.parametrize("kind", UNNAMEABLE_KINDS)
def test_a_type_that_will_not_name_itself_answers_the_fixed_literal(kind: str) -> None:
    """Both shapes the reader suites exercise at their seams, asserted here once.

    The probe is built inside the arm rather than passed to it, for
    :func:`~hostile_values.unnameable`'s reason.
    """
    assert type_name_of(unnameable(kind)) == UNNAMEABLE_TYPE


def test_an_empty_name_is_refused_rather_than_rendered() -> None:
    """``bool(name)``'s branch, which no seam arm reaches.

    A ``__name__`` of ``""`` reads without raising and is a built-in ``str``, so
    only the emptiness test stops ``got `` reaching a caller as the whole of a
    refusal.
    """
    assert type_name_of(_EmptyName("Evil", (), {})()) == UNNAMEABLE_TYPE


def test_a_name_that_is_a_str_subclass_is_refused_rather_than_rendered() -> None:
    """``type(name) is str``'s branch, which no seam arm reaches either.

    ``isinstance`` would admit the subclass, and the message would then ask it to
    render itself — which is a second object with a second chance to raise, and
    this one takes it.
    """
    assert type_name_of(_SubclassedName("Evil", (), {})()) == UNNAMEABLE_TYPE


def test_a_base_exception_from_the_name_read_is_delivered_onward() -> None:
    """ADR-0060 §1: ``Exception`` is caught and ``BaseException`` is not.

    A cancellation raised by the name read belongs to the caller. Swallowing it
    into the fixed literal would make the refusal look ordinary and lose the
    cancellation, and no arm at any seam would notice.
    """
    with pytest.raises(asyncio.CancelledError):
        type_name_of(_CancelledName("Evil", (), {})())


def test_the_real_class_is_named_however_the_object_answers_class() -> None:
    """``type()`` reads ``Py_TYPE``, which no override reaches.

    :func:`~hostile_values.impostor_of` answers ``__class__`` with whatever it was
    given, so a read routed through that attribute would report the claim rather
    than the fact — and :class:`~hostile_values.ClassRaises` would take the read
    down before any refusal was built.
    """
    assert type_name_of(impostor_of(Path)) == "Impostor"
    assert type_name_of(ClassRaises()) == "ClassRaises"


def test_the_literal_is_the_phrase_the_readers_refusals_carry() -> None:
    """What the seam arms match on, stated once where the read lives.

    Every reader suite asserts a message ending ``got an unnameable type``; this
    is the constant those assertions are about, so a change to it fails here as
    well as at every seam rather than only there.
    """
    assert UNNAMEABLE_TYPE == "an unnameable type"

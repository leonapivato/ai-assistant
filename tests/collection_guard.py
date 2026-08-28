"""Refuse a test class that carries obligations pytest will not run and not mention.

A conformance suite is an ``ABC`` whose fixtures are ``@abstractmethod``, and a
binding is a ``Test…`` subclass that implements them. Add an abstract fixture to
the suite, implement it in two of three bindings, and the third stays abstract —
at which point ``_pytest.python.PyCollector.istestclass`` answers ``False`` for
it::

    def istestclass(self, obj: object, name: str) -> bool:
        if not (self.classnamefilter(name) or self.isnosetest(obj)):
            return False
        if inspect.isabstract(obj):
            return False
        return True

The class is then not a test class at all: no item is made from it, nothing is
reported about it, and the run stays green having silently stopped asserting
everything it held. Observed on PR #1751 (issue #1757): three new abstract
fixtures, two bindings updated, and ``--collect-only`` went from 24,408 to
24,165 — the wire client's whole 243-test binding gone, with a passing run. It
was caught only by comparing the total against the previous run, which nothing
in the gate does.

That is the worst available failure mode. ``AssistantEngineContract`` is the
mechanism ADR-0084 §4's substitutability clause rests on, and the coverage
disappears exactly when someone is extending the contract — the moment it is most
needed. Nor does ``tests/core/test_protocol_triad.py`` catch it: ADR-0179's check
requires *a* binding per Protocol, not every one, so the surviving bindings keep
the run green. ADR-0015 names an invariant held by prose rather than by mechanism
as the thing to close, so this closes it.

**One question, and the loss is the whole of it:** does this class carry test
functions that pytest will now not run? Both halves are asked as pytest itself
answers them.

- *Will pytest collect nothing from it?* Two ways, differing only in which line
  of ``_pytest/python.py`` drops the class. ``inspect.isabstract`` is answered in
  ``istestclass``, before any item is made; ``__test__ = False`` is answered one
  step later, in ``Class.collect``, which returns no items. Either way the class
  contributes nothing and says nothing.
- *Was anything lost by that?* The test functions the class carries, read off its
  MRO the way ``PyCollector.collect`` reads them — first definition wins, and
  ``istestfunction`` decides, so a ``classmethod`` counts and a name shadowed by
  a non-callable does not.

An abstract helper carrying no test loses nothing and is left alone, whatever it
is called. A class carrying a suite's obligations is refused whichever of the two
mechanisms would drop it — ``__test__ = False`` included, which cannot be an
opt-out here: it removes exactly the tests an unimplemented fixture removes, and
the author of a genuine base has the class's *name* to say it with instead.

**Refused at collection rather than at run time**, because that is where the loss
happens. A guard that ran as a test would have to reconstruct which classes
*should* have been collected from something other than the collection — and any
such reconstruction is a second description of the suite that can itself go
stale. Here there is nothing to reconstruct: the object pytest is about to drop
is in hand, with ``__abstractmethods__`` on it saying exactly what is missing.

Registered by ``tests/conftest.py`` importing the hook. It lives in its own module
rather than in that conftest so the end-to-end check can hand it to a nested
pytest run with ``-p collection_guard``; a conftest cannot be loaded twice under
one module name.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.python import PyCollector

#: How many of the lost tests the refusal names. The count is what says how much
#: is at stake; a few names say which suite it is. All of them -- 161 for the
#: binding issue #1757 was found on -- would bury both under a wall of text.
_NAMED = 3


def _is_test_class(collector: PyCollector, name: str, obj: type) -> bool:
    """Report whether pytest would treat ``obj`` as a test class but for the drop.

    ``istestclass`` cannot be asked directly: its whole answer here is ``False``,
    for the abstractness this guard exists to catch. So its first half is asked
    separately, through pytest's own predicates rather than through a second
    reading of ``python_classes`` — which would drift from the ini option the
    moment a project set it.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the class is bound to there.
        obj: The class itself.

    Returns:
        Whether the name, or an explicit ``__test__ = True``, marks it as a test
        class.
    """
    return bool(collector.classnamefilter(name)) or collector.isnosetest(obj)


def _opts_out(obj: type) -> bool:
    """Report whether the class carries pytest's ``__test__ = False``.

    Read defensively, as pytest reads it: a class whose metaclass defines
    ``__getattr__`` can raise here, and a collection that died reading an
    attribute would be a worse failure than the one being prevented. Unreadable
    reads as "not opted out", which keeps the guard's subject rather than
    widening it.

    Args:
        obj: The class pytest is deciding about.

    Returns:
        Whether the class carries a falsy ``__test__``.
    """
    try:
        return not getattr(obj, "__test__", True)
    except Exception:  # any attribute error means "cannot tell"; see above
        return False


def _why_nothing_is_collected(obj: type) -> str | None:
    """Say why pytest will make no test item from this class, or ``None``.

    The two mechanisms are stated separately because the fix differs: one is a
    fixture to implement, the other a line to delete.

    Args:
        obj: The class pytest is deciding about.

    Returns:
        The reason, or ``None`` when pytest will collect from it normally.
    """
    if inspect.isabstract(obj):
        abstract: frozenset[str] = getattr(obj, "__abstractmethods__", frozenset())
        return f"it is still abstract -- never implemented: {', '.join(sorted(abstract))}"
    if _opts_out(obj):
        return "it sets `__test__ = False`"
    return None


def _carried_test_names(collector: PyCollector, obj: type) -> frozenset[str]:
    """The test functions this class carries, and would therefore stop contributing.

    Read off the whole MRO, because that is where a binding's obligations come
    from: a conformance suite's tests are inherited, never written on the binding.

    Read the way ``PyCollector.collect`` reads them, rather than by a prefix and a
    ``callable``. **First definition wins** — a name the class shadows is decided
    on the class's own value, so overriding an inherited test with ``None`` really
    does mean pytest collects nothing under that name. And ``istestfunction``
    decides, so ``python_functions`` is honoured, a ``staticmethod`` or
    ``classmethod`` is unwrapped and counted, and a fixture that happens to match
    the prefix is not.

    Args:
        collector: The module or class pytest is collecting from.
        obj: The class pytest is deciding about.

    Returns:
        The names, empty when the class would take nothing down with it.
    """
    seen: set[str] = set()
    carried: set[str] = set()
    for base in inspect.getmro(obj):
        for name, value in vars(base).items():
            if name in seen:
                continue
            seen.add(name)
            if collector.istestfunction(value, name) and getattr(value, "__test__", True):
                carried.add(name)
    return frozenset(carried)


def silently_dropped_refusal(collector: PyCollector, name: str, obj: object) -> str | None:
    """Say why ``obj`` may not be dropped in silence, or ``None`` if it may be collected.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the object is bound to there.
        obj: The object pytest is deciding about.

    Returns:
        The refusal to fail collection with, or ``None`` when there is nothing
        wrong — which is every object that is not a test class about to take
        tests down with it.
    """
    if not inspect.isclass(obj) or not _is_test_class(collector, name, obj):
        return None
    reason = _why_nothing_is_collected(obj)
    if reason is None:
        return None
    lost = _carried_test_names(collector, obj)
    if not lost:
        return None
    named = sorted(lost)[:_NAMED]
    rest = len(lost) - len(named)
    sample = ", ".join(named) + (f", and {rest} more" if rest else "")
    return (
        f"{name} carries {len(lost)} test(s) that pytest will not run and will "
        f"report nothing about, because {reason}. The suite would stay green "
        f"having stopped asserting every one of them (issue #1757).\n"
        f"  defined in: {getattr(obj, '__module__', '<unknown>')}\n"
        f"  would stop running: {sample}\n"
        f"Fix the reason above -- on a binding, that means implementing the "
        f"conformance suite's abstract fixtures. If the class is deliberately a "
        f"base rather than a binding, give it a name pytest does not collect: the "
        f"suites themselves are named `...Contract`, not `Test...`. "
        f"`__test__ = False` is not that: on a class carrying obligations it "
        f"removes them exactly as an unimplemented fixture does, one step on."
    )


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector: PyCollector, name: str, obj: object) -> None:
    """Fail collection on a test class pytest would quietly collect nothing from.

    It returns nothing in every case it does not refuse, which is how a
    ``firstresult`` hook declines: pytest's own implementation then decides, and
    this guard changes what is collected only by refusing.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the object is bound to there.
        obj: The object pytest is deciding about.
    """
    refusal = silently_dropped_refusal(collector, name, obj)
    if refusal is not None:
        pytest.fail(refusal, pytrace=False)

"""Refuse the one test class pytest drops from collection without a word.

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
disappears exactly when someone is extending the contract — the moment it is
most needed. ADR-0015 names an invariant held by prose rather than by mechanism
as the thing to close, so this closes it: the same condition pytest answers
``False`` to is answered here first, as a collection error naming the class and
the fixtures it never implemented.

**Refused at collection rather than at run time**, because that is where the
loss happens. A guard that ran as a test would have to reconstruct which classes
*should* have been collected from something other than the collection — and any
such reconstruction is a second description of the suite that can itself go
stale. Here there is nothing to reconstruct: the object pytest is about to drop
is in hand, with ``__abstractmethods__`` on it saying exactly what is missing.

**One question, and the loss is the whole of it:** would this abstract class have
contributed tests that will now not run? An abstract helper under a collected
name that inherits no test function loses nothing, and is left alone — including
one that has said ``__test__ = False``, pytest's explicit opt-out. But a class
that inherits a conformance suite's obligations loses them all whether or not it
carries that flag, since `__test__` is read a step later, in ``Class.collect``,
and removes the very items this is about. So the flag is not asked about at all:
it cannot change the answer where there is something to lose, and where there is
not, there was nothing to refuse either way.

(That leaves ``__test__ = False`` on a *concrete* binding losing exactly as much,
in silence, and this guard does not see it — its subject is abstractness. Filed
as issue #1774 rather than folded in here.)

Registered by ``tests/conftest.py`` importing the hook. It lives in its own
module rather than in that conftest so the end-to-end check can hand it to a
nested pytest run with ``-p collection_guard``; a conftest cannot be loaded
twice under one module name.
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


def _inherited_test_names(collector: PyCollector, obj: type) -> frozenset[str]:
    """The test functions this class carries, and would stop contributing.

    Read off the whole MRO, because that is where a binding's obligations come
    from: a conformance suite's tests are inherited, never written on the binding.
    Selected by pytest's own ``funcnamefilter`` rather than by a literal ``test``
    prefix, so the ``python_functions`` ini option decides here too.

    Args:
        collector: The module or class pytest is collecting from.
        obj: The class pytest is deciding about.

    Returns:
        The names, empty when the class would take nothing down with it.
    """
    return frozenset(
        name
        for base in inspect.getmro(obj)
        for name, value in vars(base).items()
        if collector.funcnamefilter(name) and callable(value)
    )


def _is_test_class(collector: PyCollector, name: str, obj: type) -> bool:
    """Report whether pytest would treat ``obj`` as a test class but for its abstractness.

    ``istestclass`` cannot be asked directly: its whole answer here is ``False``,
    for the abstractness this guard exists to catch. So the other two halves of
    it are asked separately, through pytest's own predicates rather than through
    a second reading of ``python_classes`` — which would drift from the ini
    option the moment a project set it.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the class is bound to there.
        obj: The class itself.

    Returns:
        Whether the name or the ``__test__`` attribute marks it as a test class.
    """
    return bool(collector.classnamefilter(name)) or collector.isnosetest(obj)


def abstract_test_class_refusal(collector: PyCollector, name: str, obj: object) -> str | None:
    """Say why ``obj`` may not be silently dropped, or ``None`` if it may be collected.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the object is bound to there.
        obj: The object pytest is deciding about.

    Returns:
        The refusal to fail collection with, or ``None`` when there is nothing
        wrong — which is every object that is not an abstract test class.
    """
    if not inspect.isclass(obj) or not inspect.isabstract(obj):
        return None
    if not _is_test_class(collector, name, obj):
        return None
    lost = _inherited_test_names(collector, obj)
    if not lost:
        return None
    abstract: frozenset[str] = getattr(obj, "__abstractmethods__", frozenset())
    missing = ", ".join(sorted(abstract))
    named = sorted(lost)[:_NAMED]
    rest = len(lost) - len(named)
    sample = ", ".join(named) + (f", and {rest} more" if rest else "")
    return (
        f"{name} is a test class that is still abstract, so pytest would drop it "
        f"from collection and report nothing: the {len(lost)} test(s) it carries "
        f"would stop running with the suite green (issue #1757).\n"
        f"  defined in: {getattr(obj, '__module__', '<unknown>')}\n"
        f"  never implemented: {missing}\n"
        f"  would stop running: {sample}\n"
        f"Implement the names above on this binding -- they are the conformance "
        f"suite's abstract fixtures -- or, if the class is deliberately a base "
        f"rather than a binding, give it a name pytest does not collect: the "
        f"suites themselves are named `...Contract`, not `Test...`. "
        f"`__test__ = False` does not answer this -- it removes the same tests, "
        f"one step further on."
    )


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector: PyCollector, name: str, obj: object) -> None:
    """Fail collection on an abstract test class, before pytest quietly skips it.

    It returns nothing in every case it does not refuse, which is how a
    ``firstresult`` hook declines: pytest's own implementation then decides, and
    this guard changes what is collected only by refusing.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the object is bound to there.
        obj: The object pytest is deciding about.
    """
    refusal = abstract_test_class_refusal(collector, name, obj)
    if refusal is not None:
        pytest.fail(refusal, pytrace=False)

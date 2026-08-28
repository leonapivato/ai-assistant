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


def _opts_out(obj: type) -> bool:
    """Report whether the class says, in pytest's own terms, that it is not a test class.

    ``__test__ = False`` is the explicit opt-out, and pytest honours it a step
    later than ``istestclass`` -- in ``Class.collect``, which returns no items for
    it. A class carrying it therefore contributes nothing whether it is abstract
    or not, so there is nothing for this guard to be about: no test is lost, and
    the loss is the whole subject. Refusing it anyway would break the one
    supported way to write an abstract helper named ``Test…``.

    Read defensively, exactly as pytest reads it: a class whose metaclass defines
    ``__getattr__`` can raise here, and a collection that died reading an
    attribute would be a worse failure than the one being prevented.

    Args:
        obj: The class pytest is deciding about.

    Returns:
        Whether the class carries a falsy ``__test__``.
    """
    try:
        return not getattr(obj, "__test__", True)
    except Exception:  # any attribute error means "cannot tell"; see above
        return False


def _is_test_class(collector: PyCollector, name: str, obj: type) -> bool:
    """Report whether pytest would treat ``obj`` as a test class but for its abstractness.

    ``istestclass`` cannot be asked directly: its whole answer here is ``False``,
    for the abstractness this guard exists to catch. So the other two halves of
    it are asked separately, through pytest's own predicates rather than through
    a second reading of ``python_classes`` — which would drift from the ini
    option the moment a project set it. The third condition, ``__test__``, is one
    ``istestclass`` does not ask at all; see :func:`_opts_out`.

    Args:
        collector: The module or class pytest is collecting from.
        name: The name the class is bound to there.
        obj: The class itself.

    Returns:
        Whether the name or the ``__test__`` attribute marks it as a test class,
        and it has not opted out.
    """
    if _opts_out(obj):
        return False
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
    abstract: frozenset[str] = getattr(obj, "__abstractmethods__", frozenset())
    missing = ", ".join(sorted(abstract))
    return (
        f"{name} is a test class that is still abstract, so pytest would drop it "
        f"from collection and report nothing: every test it inherits would stop "
        f"running with the suite green (issue #1757).\n"
        f"  defined in: {getattr(obj, '__module__', '<unknown>')}\n"
        f"  never implemented: {missing}\n"
        f"Implement the names above on this binding -- they are the conformance "
        f"suite's abstract fixtures -- or, if the class is deliberately a base "
        f"rather than a binding, say so: give it a name pytest does not collect "
        f"(the suites themselves are named `...Contract`, not `Test...`), or set "
        f"`__test__ = False` on it."
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

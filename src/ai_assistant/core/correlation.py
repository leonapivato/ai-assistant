"""The ambient correlation identifier ADR-0119 §4 requires and refuses to put in a signature.

§4 makes joinability the requirement and leaves the carrier to the implementing
lane, with one prohibition and one expectation. The prohibition: the identifier
"is **not** added to ``MemoryStore``, ``MemoryWriter`` or any other existing
Protocol's signature", because "a correlation id is not an input to a relevance
read" — threading one through would put an observability concern into a contract
every implementation and every fake must carry, break golden rule 5's seal for a
reason that has nothing to do with what the Protocol does, "and still not reach
the write path or the reader path without doing it again". The expectation:
``contextvars``, because "``core/logging.py`` already configures
``structlog.contextvars.merge_contextvars``, so the pattern is in the tree", and
because "asyncio propagates a context into tasks created inside it, which is what
``Engine._tracked``'s shielded task is".

**It lives in `core` because every subsystem must be able to read it.** §8 has
four seams emit, in three different packages, and golden rules 1 and 2 leave
exactly one place all three can import from. Nothing here is a Protocol and
nothing crosses a subsystem boundary as data, so this is a module beside
:mod:`ai_assistant.core.logging` rather than an addition to
:mod:`ai_assistant.core.protocols` or :mod:`ai_assistant.core.types`.

**The identifier is minted here and cannot be supplied**, which is §2's
containment rule made structural rather than promised. §2 admits an identifier
into a trace only for "its origin, never its current resolvability" — "an opaque
value **minted by this system**" — and the one way to be sure of that is to give
no caller a way to pass one in. :func:`correlated_operation` mints, binds and
unbinds; :func:`current_correlation` reads. There is no setter.

**Reading is the only capability an emitter needs, and it is the only one it
gets.** A memory emitter under §8 asks "what operation am I serving?" and writes
the answer under :data:`~ai_assistant.core.types.TraceRef.CORRELATION`. It never
opens a scope: an operation is an ``AssistantEngine`` call (§3's reading of
ADR-0083 §8, where "every scheduler job is a public ``Engine`` call"), so the one
place a scope legitimately opens is that boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Final
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The carrier itself. ``default=None`` rather than an empty string, because
#: "no operation is in scope" and "an operation whose id is blank" are different
#: facts and only the first is real — a blank string would additionally fail
#: :data:`~ai_assistant.core.types.Identifier` at the trace that tried to carry
#: it, turning an honest absence into a dropped record under §5.
_CORRELATION: Final[ContextVar[str | None]] = ContextVar("ai_assistant_correlation", default=None)


def current_correlation() -> str | None:
    """The identifier of the operation being served here, or ``None``.

    ``None`` is the honest answer outside an operation — a hub startup, a test
    calling a subsystem directly — and an emitter records the absence by omitting
    :data:`~ai_assistant.core.types.TraceRef.CORRELATION` rather than by
    inventing a value. ADR-0119 §3's observation rule says the same of a metric
    key: an absent key means *not observed*, never a stand-in.

    Returns:
        The ambient correlation identifier, or ``None`` if no operation is in
        scope.
    """
    return _CORRELATION.get()


@contextmanager
def correlated_operation() -> Iterator[str]:
    """Mint an identifier, bind it for the duration of the block, and yield it.

    **The binding is per-context, which is what makes it safe on one event
    loop.** A ``ContextVar`` set inside a task mutates that task's own copy of
    the context, so two concurrent operations — two turns, a turn and a scheduled
    job — never see each other's identifier, and a child task created inside
    either inherits the right one. That is the property §4 is buying, and it is
    the reason the shape is a context variable rather than an attribute on the
    engine.

    **The reset is in a ``finally`` and uses the token**, not a re-set to
    ``None``: restoring the previous value is what makes a nested scope leave the
    outer one intact, and a re-set would silently erase an enclosing operation's
    identifier on the way out of an inner one.

    Yields:
        The minted identifier — the 32-character hex of a random UUID, so it is
        opaque, minted by this system, and carries nothing derived from data
        (ADR-0119 §2).
    """
    correlation = uuid4().hex
    token = _CORRELATION.set(correlation)
    try:
        yield correlation
    finally:
        _CORRELATION.reset(token)


__all__ = ["correlated_operation", "current_correlation"]

"""The activation a diagnostic entry is written for, carried outside every signature.

ADR-0314 §5:4 puts this here: "``core`` gains a module carrying the activation an entry
is written for, outside every signature, as ``core/correlation.py`` carries ADR-0119
§4's identifier. ``orchestration`` binds it for the whole of an activation's run, and
only there; the completer reads it, and writes nothing where none is bound."

**Why ambient, and why here.** ADR-0314 rejects passing the activation into
``ToolCallingCompleter.respond``: it "would put a diagnostic concern into a contract
every implementation and fake carries", which is ADR-0119 §4's ground for a context
variable. The completer is in ``models/`` and the phases in ``orchestration``, and
golden rules 1 and 2 leave ``core`` as the one place both can import from. Nothing here
is a Protocol or crosses a boundary as data, so it is a module beside
:mod:`ai_assistant.core.correlation`.

**What the binding carries.** The activation's id, which names its file (§6:1); the
clock the activation's entries are stamped from, so every source of one activation
writes on one clock; and how many returned entries each source has handed its sink,
which is how planning's module knows whether the completer already wrote planning's
returned entry before it writes one with the failure (§5:2). None of it is an entry,
and nothing here reads the record (§3:1).

**Writing.** :func:`write_diagnostic` is the one way an emitter writes: it builds
nothing where the emitter holds no sink — ``Settings.diagnostic_record`` is false — or
no activation is bound, so "where it is false, no entry is built" (§2:1) holds at every
call site by construction; and an entry that cannot be built is logged naming the
activation, the source and the failure's class, never its content, and the work goes on
(§2:4).
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.types import (
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    fault_class_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from datetime import datetime

    from ai_assistant.core.protocols import DiagnosticSink

_log = structlog.get_logger(__name__)

#: The event an entry that could not be built or handed on is logged under (§2:4).
DIAGNOSTIC_NOT_WRITTEN: Final = "diagnostic_entry_not_written"


@dataclass(slots=True)
class _Run:
    """One activation's binding: its id, its clock, and what each source has returned."""

    activation_id: str
    clock: Callable[[], datetime]
    returned: Counter[DiagnosticSource] = field(default_factory=Counter)


#: The carrier. ``None`` outside an activation's run, where nothing is written.
_RUN: Final[ContextVar[_Run | None]] = ContextVar("ai_assistant_diagnostic_run", default=None)


@contextmanager
def diagnosed_activation(activation_id: str, *, clock: Callable[[], datetime]) -> Iterator[None]:
    """Bind ``activation_id`` and its clock for the block (§5:4).

    Per-context, as :func:`~ai_assistant.core.correlation.correlated_operation` is: two
    concurrent activations never see each other's binding, and a task created inside
    one inherits it. The reset uses the token, so a nested binding leaves the outer
    one intact.

    Args:
        activation_id: The activation whose run this is.
        clock: The clock its entries are stamped from.

    Yields:
        Nothing; the binding is read through :func:`diagnosed_activation_id`.
    """
    token = _RUN.set(_Run(activation_id=activation_id, clock=clock))
    try:
        yield
    finally:
        _RUN.reset(token)


def diagnosed_activation_id() -> str | None:
    """The activation bound here, or ``None`` outside an activation's run."""
    run = _RUN.get()
    return None if run is None else run.activation_id


def returned_written(source: DiagnosticSource) -> int:
    """How many returned entries ``source`` has handed its sink in the bound run.

    Planning's module reads it before and after a round's request: where it did not
    move, the completer wrote no returned entry, because no response came back, and
    the module writes it with the failure (§5:2). ``0`` outside a run.

    Args:
        source: The source asked about.

    Returns:
        The count, which only grows during a run.
    """
    run = _RUN.get()
    return 0 if run is None else run.returned[source]


def failure_body(error: BaseException) -> dict[str, object]:
    """A failure as an entry's body gives it: its class and its message.

    The record is Tier 1 and holds what the work held (§2:3), so the message is kept;
    reading it is guarded, since an exception's ``__str__`` is arbitrary code.

    Args:
        error: The failure.

    Returns:
        ``{"class": ..., "message": ...}``.
    """
    try:
        message = str(error)
    except Exception:  # an exception whose text cannot be read still has a class
        message = ""
    named = fault_class_of(error) if isinstance(error, Exception) else type(error).__name__
    return {"class": named, "message": message}


async def write_diagnostic(
    sink: DiagnosticSink | None,
    source: DiagnosticSource,
    kind: DiagnosticKind,
    body: Callable[[], Mapping[str, object]],
) -> None:
    """Write one entry for the bound activation, where there is a sink and a binding.

    ``body`` is called only where an entry will be built, so a source whose sink is
    ``None`` builds nothing (§2:1). Nothing here raises but a cancellation: an entry
    that cannot be built, or that the sink raises on against its contract, is logged
    naming the activation, the source and the failure's class (§2:4).

    Args:
        sink: The emitter's sink, or ``None`` where the record is off.
        source: Which source writes.
        kind: Given, returned or step.
        body: Builds the entry's body.

    Raises:
        CancelledError: Re-raised wherever it reaches (§2:5).
    """
    run = _RUN.get()
    if sink is None or run is None:
        return
    try:
        # Validated from a plain mapping: a body is built from whatever the source
        # holds, and the type's own validation is what makes it a frozen JSON object.
        entry = DiagnosticEntry.model_validate(
            {
                "activation_id": run.activation_id,
                "source": source,
                "kind": kind,
                "recorded_at": run.clock(),
                "body": body(),
            }
        )
    except Exception as exc:  # the instrument is subordinate to the work (§2:4)
        _dropped(run.activation_id, source, exc)
        return
    if kind is DiagnosticKind.RETURNED:
        run.returned[source] += 1
    try:
        await sink.write(entry)
    except Exception as exc:  # a sink breaking its contract still costs only the entry
        _dropped(run.activation_id, source, exc)


def _dropped(activation_id: str, source: DiagnosticSource, error: Exception) -> None:
    """Log an entry that was not written, by activation, source and class alone (§2:4)."""
    _log.warning(
        DIAGNOSTIC_NOT_WRITTEN,
        activation_id=activation_id,
        source=source.value,
        error_class=fault_class_of(error),
    )


__all__ = [
    "DIAGNOSTIC_NOT_WRITTEN",
    "diagnosed_activation",
    "diagnosed_activation_id",
    "failure_body",
    "returned_written",
    "write_diagnostic",
]

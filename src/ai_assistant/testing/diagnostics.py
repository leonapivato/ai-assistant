"""Canonical in-memory fakes for ADR-0314's two diagnostic-record Protocols.

One fake per Protocol, as the trace fakes are one per seam: an emitter's test holds a
:class:`~ai_assistant.core.protocols.DiagnosticSink` and can only write, and the
sweep's test holds a :class:`~ai_assistant.core.protocols.DiagnosticRetention` and can
only delete. Each fake's ``recorded`` or ``remaining`` property is the *test's* window
on what happened, and no seam the code under test can reach: the record has no read
(ADR-0314 §3).

**They keep serialised entries, not objects**, so what a test reads back is a detached
snapshot, as a line in a file is.

**A failure to write is logged rather than raised**, with the event name and the three
keys the durable store logs (§2:4), so the shared suite can assert "never silent and
never content" against either.

**They model the resource they do not own** (ADR-0060 §3) through
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so the cancellation
case runs against a canonical fake and not only against the file store.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN
from ai_assistant.core.errors import DiagnosticRecordError
from ai_assistant.core.types import (
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    fault_class_of,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import UtcInstant

_log = structlog.get_logger(__name__)

#: What a refused id or an entry that could not be revalidated is logged as.
UNREADABLE_DIAGNOSTIC_FIELD: Final = "unreadable"

#: The instant :func:`diagnostic_entry` stamps unless a case says otherwise.
DEFAULT_RECORDED_AT: Final = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

#: The longest name a file system takes for one entry, as the durable store bounds it.
_NAME_BYTES: Final = 255

#: Each activation's own file's suffix, as the durable store names it (§6:1).
_SUFFIX: Final = ".jsonl"

#: Each source writing to a file of its own beside the activation's, by that file's
#: suffix: the observer's (ADR-0333 §3:1) and the follow-up asker's (ADR-0337 §8:12).
_SECOND_FILES: Final = {
    DiagnosticSource.OBSERVER: ".observer" + _SUFFIX,
    DiagnosticSource.FOLLOW_UP: ".followup" + _SUFFIX,
}

#: The activation :func:`diagnostic_entry` writes for unless a case says otherwise.
DEFAULT_DIAGNOSED_ACTIVATION: Final = "3f2b8c4e-1d5a-4e7b-9c0d-2a6f8e1b7c35"


def diagnostic_entry(
    activation_id: str = DEFAULT_DIAGNOSED_ACTIVATION,
    *,
    source: DiagnosticSource = DiagnosticSource.PLANNING,
    kind: DiagnosticKind = DiagnosticKind.GIVEN,
    recorded_at: datetime = DEFAULT_RECORDED_AT,
    body: Mapping[str, object] | None = None,
) -> DiagnosticEntry:
    """Build a valid :class:`~ai_assistant.core.types.DiagnosticEntry` for a case.

    Args:
        activation_id: Whose file it goes in.
        source: Which source writes it.
        kind: Given, returned or step.
        recorded_at: When it was written.
        body: Its body, defaulting to a small one.

    Returns:
        The entry.
    """
    return DiagnosticEntry.model_validate(
        {
            "activation_id": activation_id,
            "source": source,
            "kind": kind,
            "recorded_at": recorded_at,
            "body": {"note": "a case's entry"} if body is None else body,
        }
    )


def plain_file_name(activation_id: str, source: DiagnosticSource | None = None) -> bool:
    """Whether ``activation_id`` names a plain file, as the durable store decides it (§6:1).

    An observer entry's file is a second one beside the activation's,
    ``<id>.observer.jsonl`` (ADR-0333 §3:1), and a follow-up entry's a third,
    ``<id>.followup.jsonl`` (ADR-0337 §8:12). An id ending ``.observer`` or ``.followup``
    names no file, so an activation's own name never meets another's second one, and an
    entry's name is bounded with the suffix of the file it goes to. Duplicated from the
    store, because ``ai_assistant.testing`` may not import ``evaluation``; the shared
    suite holds the two to one answer.

    Args:
        activation_id: The id.
        source: The source writing, where it decides the file; ``None`` asks about the
            activation's own file.
    """
    separators = {os.sep, "\0"} | ({os.altsep} if os.altsep else set())
    suffix = _SUFFIX if source is None else _SECOND_FILES.get(source, _SUFFIX)
    return (
        activation_id not in {"", ".", ".."}
        and not any(one in activation_id for one in separators)
        and not any(
            activation_id.endswith(second.removesuffix(_SUFFIX))
            for second in _SECOND_FILES.values()
        )
        and len(f"{activation_id}{suffix}".encode("utf-8", errors="replace")) <= _NAME_BYTES
    )


def _dropped(activation_id: str | None, source: str | None, error: Exception) -> None:
    _log.warning(
        DIAGNOSTIC_NOT_WRITTEN,
        activation_id=UNREADABLE_DIAGNOSTIC_FIELD if activation_id is None else activation_id,
        source=UNREADABLE_DIAGNOSTIC_FIELD if source is None else source,
        error_class=fault_class_of(error),
    )


class FakeDiagnosticSink:
    """A canonical :class:`~ai_assistant.core.protocols.DiagnosticSink`.

    What an emitter's test is handed. :attr:`recorded` is the test's window on what
    was written, in order; nothing the code under test holds can read it.
    """

    def __init__(self) -> None:
        """Create an empty sink with no scripted failure."""
        self._rows: list[str] = []
        self._resource = SuspendableResource()
        self._failure: Exception | None = None

    @property
    def resource(self) -> SuspendableResource:
        """The modelled resource ADR-0060's cancellation case suspends."""
        return self._resource

    @property
    def recorded(self) -> tuple[DiagnosticEntry, ...]:
        """Every entry written, hydrated, in the order written."""
        return tuple(DiagnosticEntry.model_validate_json(row) for row in self._rows)

    def of(
        self, source: DiagnosticSource, kind: DiagnosticKind | None = None
    ) -> tuple[DiagnosticEntry, ...]:
        """The entries ``source`` wrote, of ``kind`` where one is named, in order."""
        return tuple(
            one
            for one in self.recorded
            if one.source is source and (kind is None or one.kind is kind)
        )

    def fail_write(self, error: Exception | None = None) -> None:
        """Script a backing-store fault on every later write.

        A store fault, not a refusal: :meth:`write` swallows and logs it (§2:4).

        Args:
            error: The fault to model. ``None`` scripts a generic one.
        """
        self._failure = (
            error if error is not None else DiagnosticRecordError("the record is unavailable")
        )

    async def write(self, entry: DiagnosticEntry) -> None:
        """Append ``entry``; never let a fault escape (§2:4).

        Args:
            entry: The entry to keep.
        """
        try:
            snapshot = DiagnosticEntry.model_validate(entry.model_dump())
        except ValidationError as exc:
            _dropped(None, None, exc)
            return
        if not plain_file_name(snapshot.activation_id, snapshot.source):
            _dropped(None, snapshot.source.value, DiagnosticRecordError("not a plain name"))
            return
        async with self._resource.held():
            if self._failure is not None:
                _dropped(snapshot.activation_id, snapshot.source.value, self._failure)
                return
            self._rows.append(snapshot.model_dump_json())


class FakeDiagnosticRetention:
    """A canonical :class:`~ai_assistant.core.protocols.DiagnosticRetention`.

    What the ``Engine``'s sweep is handed: it can delete and nothing else.
    :meth:`hold` arranges the files a case starts from, by activation and last write,
    since nothing on this seam can create one.
    """

    def __init__(self) -> None:
        """Create a record holding no file."""
        self._files: dict[str, datetime] = {}
        self._resource = SuspendableResource()
        self._failure: Exception | None = None
        self._calls: list[datetime] = []

    @property
    def resource(self) -> SuspendableResource:
        """The modelled resource ADR-0060's cancellation case suspends."""
        return self._resource

    @property
    def remaining(self) -> frozenset[str]:
        """The activations whose files the record still holds."""
        return frozenset(self._files)

    @property
    def purged_at(self) -> tuple[datetime, ...]:
        """Each instant a sweep was asked to delete below, in order."""
        return tuple(self._calls)

    def hold(self, activation_id: str, last_write: datetime) -> None:
        """Arrange a file for ``activation_id``, last written at ``last_write``."""
        self._files[activation_id] = last_write

    def fail_purge(self, error: Exception | None = None) -> None:
        """Script a fault on every later purge, preserved as ``__cause__``."""
        self._failure = error if error is not None else OSError("the directory is unavailable")

    async def purge_before(self, instant: UtcInstant) -> int:
        """Delete every file last written before ``instant``; return how many.

        Args:
            instant: The window's edge; a file written at it is kept.

        Returns:
            How many files were deleted.

        Raises:
            DiagnosticRecordError: If a fault is scripted (:meth:`fail_purge`).
        """
        async with self._resource.held():
            self._calls.append(instant)
            if self._failure is not None:
                msg = "the diagnostic record could not be swept"
                raise DiagnosticRecordError(msg) from self._failure
            expired = [name for name, written in self._files.items() if written < instant]
            for name in expired:
                del self._files[name]
            return len(expired)


__all__ = [
    "DEFAULT_DIAGNOSED_ACTIVATION",
    "DEFAULT_RECORDED_AT",
    "UNREADABLE_DIAGNOSTIC_FIELD",
    "FakeDiagnosticRetention",
    "FakeDiagnosticSink",
    "diagnostic_entry",
    "plain_file_name",
]

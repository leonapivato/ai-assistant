"""The observation record's rules, stated once for every store in this package.

ADR-0329 §16:9 gives :class:`~ai_assistant.core.protocols.PlanStore` three members over
the observer's records: a write conditional on the revision the writer read, a read by
episode id, and a count of the model calls they hold since an instant. What a store
checks of its arguments, and what it decides from the record it holds, is written here
rather than in each store, for the reason :mod:`ai_assistant.planning.stops` gives: two
statements of one rule are two places for it to drift, and a store's own job is the
indivisible step the rule runs inside.

The canonical fake in :mod:`ai_assistant.testing` re-implements these rather than
importing them, as it does the stop record's and the effect record's; the conformance
suite is what keeps the copies agreeing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import ObservationRecord, UtcInstant

if TYPE_CHECKING:
    from datetime import datetime

_INSTANT: Final[TypeAdapter[datetime]] = TypeAdapter(UtcInstant)

#: The bound :attr:`~ai_assistant.core.types.ObservationRecord.revision` carries, which
#: an issuer reaching it could not stamp.
_REVISION_BOUND: Final = 2**63


def checked_observation(record: object) -> ObservationRecord:
    """Return the store's own copy of a record about to be written, or refuse it.

    Rebuilt from its dump, so a caller holding the record cannot change what is written
    while the write waits (ADR-0018 §3), and a record built with ``model_construct`` or
    edited through ``__dict__`` is validated rather than trusted.

    Args:
        record: What the caller passed.

    Returns:
        The validated copy, its revision as submitted (the store discards it).

    Raises:
        PlanningError: If the value is not a valid ``ObservationRecord``.
    """
    if not isinstance(record, ObservationRecord):
        msg = (
            f"write_observation writes an ObservationRecord, and {type(record).__name__} is not one"
        )
        raise PlanningError(msg)
    try:
        return ObservationRecord.model_validate(record.model_dump())
    except ValidationError as exc:
        msg = f"the observation record to write does not validate: {exc}"
        raise PlanningError(msg) from exc


def checked_expected_revision(expected: object) -> int:
    """Return ``expected`` as a revision a write may be conditional on, or refuse it.

    Raises:
        PlanningError: If it is not a non-negative integer (a ``bool`` included,
            which is an ``int`` in Python and no revision).
    """
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        msg = f"expected_revision is 0 or a revision the store issued, not {expected!r}"
        raise PlanningError(msg)
    return expected


def decide_observation_write(episode: str, *, held: int | None, expected: int) -> None:
    """Refuse a write whose expectation the held record does not meet (ADR-0329 §16:9).

    Args:
        episode: The record's episode, for the message.
        held: The revision of the record the store holds, or ``None`` where it holds
            none.
        expected: The revision the writer read, or ``0`` where it read none.

    Raises:
        PlanningError: If a record is held where none was expected, none is held where
            one was, or one is held at another revision.
    """
    if held == expected or (held is None and expected == 0):
        return
    found = "no record" if held is None else f"a record at revision {held}"
    wanted = "no record" if expected == 0 else f"revision {expected}"
    msg = (
        f"the plan store holds {found} for episode {episode!r}, and the write expected "
        f"{wanted}; nothing is written"
    )
    raise PlanningError(msg)


def stamped(record: ObservationRecord, revision: int) -> ObservationRecord:
    """Return ``record`` carrying the revision the store issued for this write.

    Raises:
        PlanningError: If the issuer has run past the bound a revision carries.
    """
    if revision >= _REVISION_BOUND:
        msg = "the plan store has issued every observation revision it can"
        raise PlanningError(msg)
    return record.model_copy(update={"revision": revision})


def requested_episodes(episode_ids: object) -> tuple[str, ...]:
    """Return the episodes a read names, each once in the order named, or refuse them.

    Raises:
        PlanningError: If ``episode_ids`` is a bare string, or not a sequence of
            strings.
    """
    if (
        not isinstance(episode_ids, Sequence)
        or isinstance(episode_ids, (str, bytes))
        or not all(isinstance(one, str) for one in episode_ids)
    ):
        msg = "observations reads a sequence of episode ids, not one string or anything else"
        raise PlanningError(msg)
    return tuple(dict.fromkeys(episode_ids))


def checked_since(since: object) -> datetime:
    """Return ``since`` as the instant a count runs from, or refuse it.

    Raises:
        PlanningError: If it is not a timezone-aware instant.
    """
    try:
        return _INSTANT.validate_python(since, strict=True)
    except ValidationError as exc:
        msg = f"observer_calls_since counts from a timezone-aware instant, not {since!r}"
        raise PlanningError(msg) from exc


__all__ = [
    "checked_expected_revision",
    "checked_observation",
    "checked_since",
    "decide_observation_write",
    "requested_episodes",
    "stamped",
]

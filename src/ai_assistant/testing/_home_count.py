"""The count event a canonical fake bound in the counting mode writes (ADR-0383 §11).

For the story, notification, conversation and person-model fakes, whose records are seen
by their home alone, as ``ai_assistant.memory._home_columns`` has it for the durable
stores (:func:`count_homes`); and for the plan fake, some of whose records are its sight's
activation's own (ADR-0383 §7:4), as ``ai_assistant.planning._home_columns`` has it
(:func:`count_given`). Duplicated rather
than shared for the reason every shared piece of a fake is: ``ai_assistant.testing`` may
not import a subsystem (golden rule 1). Each Protocol's conformance suite runs the same
count cases against the fake and the durable store, so the copies cannot drift unseen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import RecordHome, Sight

_log = structlog.get_logger(__name__)

#: The event a read through a store bound in the counting mode writes (§11:1).
SIGHT_COUNTED: Final = "sight_counted"


def count_homes(
    sight: Sight, *, store: str, member: str, homes: Iterable[RecordHome | None]
) -> None:
    """Write §11:1's event for one read that gave back records of ``homes``.

    In numbers and codes alone (§11:3); no record here is made by an activation.

    Args:
        sight: The sight the fake is bound to.
        store: The store's code, as the durable store writes it.
        member: The read member's name.
        homes: The home of each record the read gave back, ``None`` for one with no home
            a bound store reads (a device row, ADR-0383 §3:3).
    """
    count = sight.count(store=store, member=member, given=((home, None) for home in homes))
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))


def count_given(
    sight: Sight,
    *,
    store: str,
    member: str,
    given: Iterable[tuple[RecordHome | None, str | None]],
) -> None:
    """Write §11:1's event for one read, each record given with the activation that made it.

    In numbers and codes alone (§11:3). For a store that records some records as made by
    an activation (ADR-0383 §7:4), which its sight's own activation sees whatever their
    home.

    Args:
        sight: The sight the fake is bound to.
        store: The store's code, as the durable store writes it.
        member: The read member's name.
        given: Each record the read gave back, as its home (``None`` for one with no home
            a bound store reads, a stop record's among them, §3:3) and the activation the
            store records as having made it, or ``None``.
    """
    count = sight.count(store=store, member=member, given=given)
    _log.info(SIGHT_COUNTED, **count.model_dump(mode="json"))

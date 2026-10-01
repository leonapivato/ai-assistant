"""What the memory stores' channel reads share (ADR-0283 §1, §3).

The argument bounds of ``channel_episodes`` and ``channel_episode_ids``, and the two
facts those reads and ``episode_parking`` take off a record: which channel it is on
and which binding its own step parked. Both stores in this package import them, so
the two cannot disagree about either; the canonical fake in ``ai_assistant.testing``
repeats them, since it may not import a subsystem (golden rule 1), and the shared
conformance suite runs the same cases against all three.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import EpisodicMemory

if TYPE_CHECKING:
    from ai_assistant.core.types import ChannelIdentity, MemoryRecord, ParkedBinding

#: The largest page either channel read serves (ADR-0283 §3:2).
MAX_CHANNEL_PAGE: Final = 1000

#: The largest number a store can have issued: SQLite's ``rowid`` ceiling. An
#: ``after`` above it is a valid argument that no number exceeds, so a store binding
#: it clamps it here rather than overflowing the bind.
MAX_EPISODE_NUMBER: Final = 2**63 - 1


def check_channel_page(after: object, limit: object) -> None:
    """Refuse a channel read's ``after`` or ``limit`` before any I/O (ADR-0283 §3:2).

    Strict: ``bool`` is an ``int`` subclass and is refused, as are floats and
    numeric strings.

    Raises:
        ValueError: ``limit`` is not a strict integer in ``[1, 1000]``, or ``after``
            is neither ``None`` nor a strict positive integer.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_CHANNEL_PAGE:
        msg = f"a channel read's limit must be a strict integer in [1, {MAX_CHANNEL_PAGE}]"
        raise ValueError(msg)
    if after is not None and (type(after) is not int or after < 1):
        msg = "a channel read's after must be None or a strict positive integer"
        raise ValueError(msg)


def channel_of(record: MemoryRecord) -> ChannelIdentity | None:
    """The channel ``record`` is on: its processing record's ``trigger.channel``.

    ``None`` for a record that is not an episode, an episode with no processing
    record, and one whose trigger names no channel — each is on no channel.
    """
    if not isinstance(record, EpisodicMemory) or record.processing_record is None:
        return None
    return record.processing_record.trigger.channel


def parks_of(record: MemoryRecord) -> ParkedBinding | None:
    """The binding ``record``'s own step parked (``links.parks``), or ``None``."""
    if not isinstance(record, EpisodicMemory) or record.processing_record is None:
        return None
    return record.processing_record.links.parks

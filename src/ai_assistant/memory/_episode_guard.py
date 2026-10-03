"""What the memory stores share about an open episode (ADR-0286 §1, §12).

Whether a record is an open episode, and the write guard that admits a replacement
of a stored episode. Both stores in this package import them, so the two cannot
disagree about either; the canonical fake in ``ai_assistant.testing`` repeats them,
since it may not import a subsystem (golden rule 1), and the shared conformance suite
runs the same cases against all three.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.episode_encoding import episode_extends
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import EpisodicMemory
from ai_assistant.memory._channel_reads import channel_of

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryRecord


def is_open(record: MemoryRecord) -> bool:
    """Whether ``record`` is an open episode: its processing record is open (§1).

    ``False`` for a record that is not an episode and for an episode with no
    processing record, neither of which is ever open.
    """
    return (
        isinstance(record, EpisodicMemory)
        and record.processing_record is not None
        and record.processing_record.is_open
    )


def refuse_episode_change(stored: MemoryRecord, record: MemoryRecord) -> None:
    """Refuse a write of ``record`` over ``stored`` that §12 forbids, before anything is written.

    Two refusals, judged on the record already stored at the id:

    - **The processing record and the response** (§12:2-§12:3). Where ``stored`` is
      an episode carrying a processing record and ``record`` differs from it in its
      processing record or ``outcome``, the write is refused unless ``stored`` is
      open and :func:`~ai_assistant.core.episode_encoding.episode_extends` holds of
      the two. No other field is judged, so a placement act or a re-derived
      ``content`` on a frozen episode, which leaves both as stored, is admitted.
    - **The channel** (§12:4, ADR-0283 §1:3 as superseded). A channel already
      written never changes and is never dropped; an episode stored on no channel
      may gain one.

    The cross-kind refusal (ADR-0108 §4) is the caller's, beside this one.

    Raises:
        MemoryStoreError: The write changes a stored episode's processing record or
            response other than by extending an open one, or changes or drops the
            channel the stored episode is on.
    """
    if (
        isinstance(stored, EpisodicMemory)
        and stored.processing_record is not None
        and (
            not isinstance(record, EpisodicMemory)
            or record.processing_record != stored.processing_record
            or record.outcome != stored.outcome
        )
        and not (isinstance(record, EpisodicMemory) and episode_extends(stored, record))
    ):
        msg = "recorded processing and response are immutable unless extending an open episode"
        raise MemoryStoreError(msg)
    if channel_of(stored) not in (None, channel_of(record)):
        msg = "an episode's channel is immutable: once written, it never changes"
        raise MemoryStoreError(msg)

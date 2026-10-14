"""Whether an episode the phases show planning rests on outside content (ADR-0303 §3:2).

ADR-0306 §4:5 says an activation has read outside content when its record says so: an
outside trigger, digested evidence, or a marked summary or note. Planning is shown other
episodes, by the episode window, by recall and in the story views, and three places
count what it was shown: planning, marking its round's notes (ADR-0307 §4:3); the
phases' glue, carrying what was read into the first ruling (ADR-0181 §4); and
authorizing, reading the activation's record by its labels (ADR-0306 §4:5-§4:6). They
must agree, so the glue and authorizing ask their question of one rule, here, in a
module the phase modules may import without breaking their independence (ADR-0309
§2:3). Planning counts what it renders, by the same facts, as it renders them.

**An outside episode** (ADR-0303 §3:2) is one whose trigger's ``origin`` is
``outside``, or whose activation's record of what it read shows outside content: its
provenance rests on recorded external content (ADR-0106 §1), it records a digest that
answered with evidence (ADR-0308 §5:4-§5:5), or one of its rounds carries a marked note
(ADR-0307 §4:3).

This is the built lineage rule, read over its own inputs; it is not the authority
design's value tracing.
"""

from __future__ import annotations

from ai_assistant.core.types import (
    DigestOutcome,
    EpisodicMemory,
    InputOrigin,
    MemoryRecord,
    rests_on_recorded_external_content,
)

__all__ = ["carries_evidence", "from_outside", "is_outside_episode", "rests_on_outside_content"]


def from_outside(record: EpisodicMemory) -> bool:
    """Whether an episode's input came from outside (ADR-0284 §2:1, ADR-0303 §3:2).

    Args:
        record: The episode.

    Returns:
        Whether its trigger is a channel trigger whose ``origin`` is ``outside``.
    """
    processing = record.processing_record
    trigger = None if processing is None else processing.trigger
    return trigger is not None and trigger.origin is InputOrigin.OUTSIDE


def carries_evidence(record: MemoryRecord) -> bool:
    """Whether an episode records a digest that answered with evidence (ADR-0308 §5:5).

    Counted whatever the reader's audience, the conservative direction: where the
    evidence is withheld it was not read, and counting it only marks more.

    Args:
        record: The record; only an episode carries digests.

    Returns:
        Whether it is an episode one of whose digests answered with an item.
    """
    processing = record.processing_record if isinstance(record, EpisodicMemory) else None
    return processing is not None and any(
        one.outcome is DigestOutcome.ANSWERED and one.evidence for one in processing.digests
    )


def rests_on_outside_content(record: EpisodicMemory) -> bool:
    """Whether an episode rests on outside content by its own record, its notes apart.

    Its provenance rests on recorded external content, its input came from outside,
    whose understood meaning planning is still shown, or it carries digested evidence.
    This is what the phases' glue counts of a record it fetched before planning: a
    marked note of the episode's rounds is counted where planning is shown it, and by
    authorizing from the episode's label.

    Args:
        record: The episode, as it was read.

    Returns:
        Whether it rests on outside content.
    """
    return (
        rests_on_recorded_external_content(record.provenance)
        or from_outside(record)
        or carries_evidence(record)
    )


def is_outside_episode(record: EpisodicMemory) -> bool:
    """Whether an episode shown to planning is an outside episode (ADR-0303 §3:2).

    What authorizing counts of an episode planning was shown under a label: everything
    :func:`rests_on_outside_content` counts, and a marked note of its rounds, whatever
    the reader's audience may be shown of it, since authorizing does not know it.

    Args:
        record: The episode, as it was read.

    Returns:
        Whether it is an outside episode.
    """
    processing = record.processing_record
    return rests_on_outside_content(record) or (
        processing is not None and any(one.notes_marked for one in processing.rounds)
    )

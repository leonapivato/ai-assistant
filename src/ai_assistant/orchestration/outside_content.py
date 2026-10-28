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

**An outside episode** (ADR-0303 §3:2) is one one of whose inputs is outside (ADR-0351
§5:1, §8:3), or whose activation's record of what it read shows outside content: its
provenance rests on recorded external content (ADR-0106 §1), it records a digest that
answered with evidence (ADR-0308 §5:4-§5:5), or one of its rounds carries a marked note
(ADR-0307 §4:3).

**Whose words an input carries** (ADR-0351 §5, §8:2). An input is outside where its
parties are, read with its relay mark: the trigger's by the latest understanding version
its activation records (§5:11), a joined input's by its own record (§5:14). An
activation holding more than one input is read over all of them, so it holds outside
input where any of them is outside (§8:5, §5:13). :func:`relayed_by`,
:func:`joined_parties` and :func:`holds_outside` are that reading, which the readers
of a stored episode and of a running activation share.

This is the built lineage rule, read over its own inputs; it is not the authority
design's value tracing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    DigestOutcome,
    EpisodicMemory,
    MemoryRecord,
    canonical_parties,
    parties_are_assistants,
    parties_are_outside,
    parties_are_persons_own,
    rests_on_recorded_external_content,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        ActivationUnderstanding,
        EpisodeProjection,
        JoinedInput,
        RecordedChannelTrigger,
        SupportHolder,
    )

__all__ = [
    "carries_evidence",
    "from_outside",
    "holds_outside",
    "is_outside_episode",
    "joined_parties",
    "projected_assistants",
    "projected_outside",
    "projected_own",
    "relayed_by",
    "rests_on_outside_content",
]


def relayed_by(understanding: Sequence[ActivationUnderstanding]) -> bool:
    """Whether the trigger's input is relayed, by the latest version recorded (§5:11).

    Before any version exists, and where understanding was omitted, there is no relay
    mark, and the input is read by its parties alone.

    Args:
        understanding: The activation's understanding versions, in order.

    Returns:
        Whether the latest version marks the trigger's input relayed.
    """
    return bool(understanding) and understanding[-1].relayed


def joined_parties(joined: JoinedInput) -> tuple[SupportHolder, ...] | None:
    """Whose words a joined input carries: its messages' distinct parties (ADR-0351 §2:6).

    ``None`` where one of its messages has unknown parties, which only the episode store's
    upgrade records (§9:3).

    Args:
        joined: The joined input.

    Returns:
        Its parties, or ``None`` where they are unknown.
    """
    if any(message.party is None for message in joined.messages):
        return None
    return canonical_parties(
        message.party for message in joined.messages if message.party is not None
    )


def holds_outside(
    trigger: RecordedChannelTrigger,
    understanding: Sequence[ActivationUnderstanding],
    joined: Sequence[JoinedInput],
) -> bool:
    """Whether an activation holds outside input: any of its inputs is (ADR-0351 §8:5).

    Its trigger's input, by its parties and the latest version's relay mark, and each
    joined input, by its parties and its own relay mark (§5:7, §5:13, §5:14).

    Args:
        trigger: The activation's trigger.
        understanding: Its understanding versions, in order.
        joined: The inputs it took in beside its trigger's.

    Returns:
        Whether any input it holds is outside.
    """
    return parties_are_outside(trigger.parties, relayed=relayed_by(understanding)) or any(
        parties_are_outside(joined_parties(one), relayed=one.relayed) for one in joined
    )


def projected_outside(projection: EpisodeProjection) -> bool:
    """Whether a projected episode's input is outside, read with its relay mark (§5:1).

    An episode with no processing record has no parties, and is none of the three.
    """
    return projection.has_processing_record and parties_are_outside(
        projection.parties, relayed=projection.relayed
    )


def projected_own(projection: EpisodeProjection) -> bool:
    """Whether a projected episode's input is the person's own, read with its relay mark."""
    return projection.has_processing_record and parties_are_persons_own(
        projection.parties, relayed=projection.relayed
    )


def projected_assistants(projection: EpisodeProjection) -> bool:
    """Whether a projected episode's input is the assistant's, read with its relay mark."""
    return projection.has_processing_record and parties_are_assistants(
        projection.parties, relayed=projection.relayed
    )


def from_outside(record: EpisodicMemory) -> bool:
    """Whether an episode's input came from outside (ADR-0351 §5:1, §8:3, ADR-0303 §3:2).

    Args:
        record: The episode.

    Returns:
        Whether it has a processing record one of whose inputs is outside, read with
        its relay mark (:func:`holds_outside`).
    """
    processing = record.processing_record
    return processing is not None and holds_outside(
        processing.trigger, processing.understanding, processing.joined
    )


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

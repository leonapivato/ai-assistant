"""Builders for the memory record, for tests and fixtures (ADR-0328 §3-§5).

A memory is a statement resting on supports, and every change to it an operation citing
one (ADR-0328 §3, §5). Building one by hand means a support whose origin fits its part
(§4's tables), and a create citing it; these builders do that once, so a test states
only what it is about. Nothing here is a fake: each returns a real
:class:`~ai_assistant.core.types.Memory` that ``core``'s validators accept.

Every support is ``for`` and backs its memory as worded unless a builder says
otherwise, dated :data:`AT`, and added by ``remember``; a memory's create cites its
first support, at that support's ``added_at``, by its writer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    ConfirmationPart,
    EvidenceItemPart,
    InputPart,
    LegacyPart,
    Memory,
    MemoryOperation,
    MemoryOperationKind,
    MemorySupport,
    MemoryWriterName,
    ObserverInferencePart,
    PinPart,
    QuestionPart,
    ReadingCertainty,
    RememberCallPart,
    RoundMessagePart,
    SupportDirection,
    SupportOrigin,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson

__all__ = [
    "AT",
    "HELD_EPISODE",
    "confirmed_support",
    "derived_from",
    "derived_support",
    "inference_support",
    "legacy_support",
    "memory",
    "memory_in_band",
    "message_support",
    "pinned_support",
    "remembered_support",
    "said_support",
    "sourced_support",
    "support_with_origin",
]

#: The instant a builder dates a support at, unless told otherwise.
AT: Final = datetime(2026, 1, 1, 12, tzinfo=UTC)

#: The episode a builder's support points into, unless told otherwise.
HELD_EPISODE: Final = "activation:held"


def said_support(
    episode: str = HELD_EPISODE,
    *,
    when: datetime | None = AT,
    added_at: datetime = AT,
    direction: SupportDirection = SupportDirection.FOR,
    note: str = "",
) -> MemorySupport:
    """A support pointing at an episode's input, which the user wrote: "you said it".

    Args:
        episode: The episode whose input it points at.
        when: When the input was given.
        added_at: When the support was added.
        direction: ``for`` or ``against``; an ``against`` one never backs as worded.
        note: How the part relates to the claim.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=InputPart(episode=episode),
        origin=SupportOrigin.USER_MESSAGE,
        direction=direction,
        note=note,
        backs_as_worded=direction is SupportDirection.FOR,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.REMEMBER,
    )


def confirmed_support(
    episode: str = HELD_EPISODE,
    *,
    asking_activation: str = "act-asking",
    question: QuestionPart | None = None,
    when: datetime | None = AT,
    added_at: datetime = AT,
) -> MemorySupport:
    """A support pointing at a yes and the part it approved: "you confirmed this wording".

    Args:
        episode: The yes's episode.
        asking_activation: The activation that asked.
        question: The approved part; round ``round-1``, part 1 where ``None``.
        when: When the yes was given.
        added_at: When the support was added.

    Returns:
        The support, ``sure`` as every confirmation is (ADR-0328 §4:11).
    """
    return MemorySupport(
        points_at=ConfirmationPart(
            episode=episode,
            asking_activation=asking_activation,
            question=QuestionPart(round="round-1", part=1) if question is None else question,
        ),
        origin=SupportOrigin.CONFIRMATION,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.REMEMBER,
    )


def sourced_support(  # noqa: PLR0913 — a part's three positions and the support's own facts, each a test's to set
    attestation: Attestation | None = None,
    *,
    episode: str = HELD_EPISODE,
    digest: int = 0,
    item: int = 0,
    when: datetime | None = AT,
    added_at: datetime = AT,
    how_sure: ReadingCertainty | None = ReadingCertainty.SURE,
) -> MemorySupport:
    """A support pointing at a digest's evidence item: "from a source", and outside.

    Args:
        attestation: Which source said so, and when.
        episode: The episode whose digest holds the item.
        digest: The digest's position.
        item: The item's position in it.
        when: When the item was read.
        added_at: When the support was added.
        how_sure: How sure the reading was.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=EvidenceItemPart(episode=episode, digest=digest, item=item),
        origin=SupportOrigin.EVIDENCE,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=how_sure,
        when=when,
        source_details=attestation,
        added_at=added_at,
        added_by=MemoryWriterName.REMEMBER,
    )


def message_support(  # noqa: PLR0913 — a part's address and the support's own facts, each a test's to set
    episode: str = HELD_EPISODE,
    *,
    round_id: str = "round-1",
    outside: bool = False,
    when: datetime | None = AT,
    added_at: datetime = AT,
    how_sure: ReadingCertainty | None = ReadingCertainty.SURE,
) -> MemorySupport:
    """A support pointing at a round's message: "from a source", outside where ``outside``.

    Args:
        episode: The episode the round belongs to.
        round_id: The round that wrote the message.
        outside: Whether the activation had read outside content.
        when: When the message was written.
        added_at: When the support was added.
        how_sure: How sure the reading was.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=RoundMessagePart(episode=episode, round=round_id),
        origin=(
            SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE
            if outside
            else SupportOrigin.ASSISTANT_MESSAGE
        ),
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=how_sure,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.REMEMBER,
    )


def remembered_support(
    episode: str = HELD_EPISODE,
    *,
    effect: str = "effect-1",
    outside: bool = False,
    when: datetime | None = AT,
    added_at: datetime = AT,
) -> MemorySupport:
    """A support pointing at a remember call: "inference", outside where ``outside``.

    Args:
        episode: The episode the call ran in.
        effect: The id of the effect record the call is claimed under.
        outside: Whether the activation had read outside content.
        when: The episode's ``occurred_at``.
        added_at: When the support was added.

    Returns:
        The support, not judged, as ADR-0328 §13:2 writes it.
    """
    return MemorySupport(
        points_at=RememberCallPart(episode=episode, effect=effect),
        origin=SupportOrigin.REMEMBERED_OVER_OUTSIDE if outside else SupportOrigin.REMEMBERED,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.REMEMBER,
    )


def legacy_support(
    record: dict[str, FrozenJson],
    *,
    outside: bool = False,
    when: datetime | None = None,
    added_at: datetime = AT,
) -> MemorySupport:
    """A legacy support carrying ``record`` whole, added by ``migration`` (ADR-0328 §16:4).

    Args:
        record: The record as it was stored; it must carry an ``id``.
        outside: Whether it rested on recorded external content.
        when: The support's ``when`` (§16:5).
        added_at: The upgrade's instant.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=LegacyPart(record=str(record["id"])),
        origin=SupportOrigin.LEGACY_OUTSIDE if outside else SupportOrigin.LEGACY,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.MIGRATION,
        carries=record,
    )


def derived_support(
    record: str = "legacy-1",
    *,
    outside: bool = False,
    when: datetime | None = AT,
    added_at: datetime = AT,
) -> MemorySupport:
    """The tests' derived stand-in: a legacy record, "inference", outside where ``outside``.

    A memory standing at inference that a writer creates or folds into. A legacy
    record's holder is unknown, so ADR-0345 §2:4's limit on what the assistant's
    statement backs does not bind it, where a remember call's or an observer's
    inference would make a memory the writer refuses unless it is a record of the
    saying (§8:3). It points into no episode, so no episode need be held for it.

    Args:
        record: The id of the legacy record it carries; distinct ids are distinct parts.
        outside: Whether it rested on recorded external content.
        when: The support's ``when``.
        added_at: When it was added.

    Returns:
        The support, a :func:`legacy_support` carrying a record of that id alone.
    """
    return legacy_support({"id": record}, outside=outside, when=when, added_at=added_at)


def derived_from(
    episode: str = HELD_EPISODE,
    *,
    key: str = "1",
    outside: bool = False,
    when: datetime | None = AT,
    added_at: datetime = AT,
) -> tuple[MemorySupport, MemorySupport]:
    """The derived stand-in's supports where an episode must warrant the memory.

    A :func:`derived_support` backing it, first, so its create cites that; and the
    episode's round message, ``for`` and backing nothing, as ADR-0345 §2:4 lets any
    memory cite what the assistant said. The memory stands at inference, cites
    ``episode`` (ADR-0077 §5, read through ADR-0328 §12, so ``DefaultMemoryPolicy``
    does not reject it for want of a warrant), and is refused by no writer.

    Args:
        episode: The episode the round message is in.
        key: What tells two memories' parts apart: the legacy record is
            ``legacy-{key}`` and the round ``round-{key}``.
        outside: Whether the legacy record rested on recorded external content.
        when: Both supports' ``when``.
        added_at: When both were added.

    Returns:
        The two supports, the backing one first.
    """
    cited = message_support(
        episode, round_id=f"round-{key}", when=when, added_at=added_at
    ).model_copy(update={"backs_as_worded": False})
    return (
        derived_support(f"legacy-{key}", outside=outside, when=when, added_at=added_at),
        cited,
    )


def inference_support(
    episode: str = HELD_EPISODE,
    *,
    when: datetime | None = AT,
    added_at: datetime = AT,
    direction: SupportDirection = SupportDirection.FOR,
    how_sure: ReadingCertainty | None = ReadingCertainty.LIKELY,
) -> MemorySupport:
    """A support that is an observer's inference: "inference", not outside (ADR-0329 §9:7).

    Added by the observer, carrying no source details. ``when`` stands for the
    ``occurred_at`` of the episode whose processing drew it, which the writer checks
    against the stored episode.

    Args:
        episode: The episode whose processing drew it.
        when: That episode's ``occurred_at``.
        added_at: When the support was added.
        direction: ``for``, backing the claim as worded, or ``against``.
        how_sure: How sure the commit step's reading was.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=ObserverInferencePart(episode=episode),
        origin=SupportOrigin.OBSERVER_INFERENCE,
        direction=direction,
        backs_as_worded=direction is SupportDirection.FOR,
        how_sure=how_sure,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.OBSERVER,
    )


def pinned_support(
    pin: str = "pin-1",
    *,
    when: datetime = AT,
    added_at: datetime = AT,
) -> MemorySupport:
    """A support a pin earns: "you confirmed this wording", not outside (ADR-0338 §4:4).

    ``for``, backing the memory as worded and ``sure``, added by the observer (§4:6),
    with no about-when and no source details. ``when`` stands for the instant the pin
    was made.

    Args:
        pin: The pin's id.
        when: The instant the pin was made.
        added_at: When the support was added.

    Returns:
        The support.
    """
    return MemorySupport(
        points_at=PinPart(pin=pin),
        origin=SupportOrigin.PINNED,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=when,
        added_at=added_at,
        added_by=MemoryWriterName.OBSERVER,
    )


def support_with_origin(  # noqa: PLR0911 — one arm per part §4's origin table names
    origin: SupportOrigin,
    *,
    episode: str = HELD_EPISODE,
    when: datetime | None = AT,
    added_at: datetime = AT,
) -> MemorySupport:
    """A ``for`` support taking ``origin``, on the part §4's origin table gives it.

    For a case swept over every origin: each builder above, chosen by the origin. An
    ``outside_input`` support points at the episode's input and carries source details,
    as an outside report does; a legacy one carries a record whose id is ``episode``.

    Args:
        origin: The origin the support takes.
        episode: The episode its part points into.
        when: Its ``when``.
        added_at: When it was added.

    Returns:
        The support.
    """
    match origin:
        case SupportOrigin.USER_MESSAGE:
            return said_support(episode, when=when, added_at=added_at)
        case SupportOrigin.OUTSIDE_INPUT:
            return MemorySupport(
                points_at=InputPart(episode=episode),
                origin=origin,
                direction=SupportDirection.FOR,
                backs_as_worded=True,
                how_sure=ReadingCertainty.SURE,
                when=when,
                source_details=Attestation(reported_by="outside-source", reported_at=AT),
                added_at=added_at,
                added_by=MemoryWriterName.REMEMBER,
            )
        case SupportOrigin.CONFIRMATION:
            return confirmed_support(episode, when=when, added_at=added_at)
        case SupportOrigin.EVIDENCE:
            return sourced_support(
                Attestation(reported_by="source-instance", reported_at=AT),
                episode=episode,
                when=when,
                added_at=added_at,
            )
        case SupportOrigin.ASSISTANT_MESSAGE | SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE:
            return message_support(
                episode,
                outside=origin is SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE,
                when=when,
                added_at=added_at,
            )
        case SupportOrigin.REMEMBERED | SupportOrigin.REMEMBERED_OVER_OUTSIDE:
            return remembered_support(
                episode,
                outside=origin is SupportOrigin.REMEMBERED_OVER_OUTSIDE,
                when=when,
                added_at=added_at,
            )
        case SupportOrigin.LEGACY | SupportOrigin.LEGACY_OUTSIDE:
            return legacy_support(
                {"id": episode},
                outside=origin is SupportOrigin.LEGACY_OUTSIDE,
                when=when,
                added_at=added_at,
            )
        case SupportOrigin.OBSERVER_INFERENCE:
            return inference_support(episode, when=when, added_at=added_at)
        case SupportOrigin.PINNED:
            return pinned_support(f"pin-{episode}", when=when or AT, added_at=added_at)
        case _:  # pragma: no cover - exhaustive
            assert_never(origin)


def memory(
    record_id: str,
    content: str,
    *supports: MemorySupport,
    **envelope: object,
) -> Memory:
    """A memory stating ``content`` on ``supports``, created citing the first of them.

    Args:
        record_id: The memory's id.
        content: Its wording.
        *supports: What it rests on; one :func:`said_support` where none is given.
        **envelope: Any other field of the memory (``validity``, ``placement``,
            ``topics``, ``about_person``, ``expires_at``, ``operations``...). An
            ``operations`` given here replaces the single create.

    Returns:
        The memory.
    """
    held = supports or (said_support(),)
    first = held[0]
    create = MemoryOperation(
        kind=MemoryOperationKind.CREATE,
        cites=first.points_at,
        at=first.added_at,
        by=first.added_by,
    )
    fields: dict[str, object] = {
        "id": record_id,
        "content": content,
        "supports": held,
        "operations": (create,),
    }
    fields.update(envelope)
    return Memory.model_validate(fields)


def memory_in_band(  # noqa: PLR0913 — a band and what each band's support takes, each a test's to set
    record_id: str,
    content: str,
    band: BeliefBand = BeliefBand.ASSERTED,
    *,
    outside: bool = False,
    attestation: Attestation | None = None,
    episode: str = HELD_EPISODE,
    when: datetime | None = AT,
    **envelope: object,
) -> Memory:
    """A memory standing in ``band``: said, sourced, or inferred (ADR-0328 §6:4).

    ``ASSERTED`` rests on a :func:`said_support`; ``ATTESTED`` on a
    :func:`sourced_support` carrying ``attestation``; ``DERIVED`` on a
    :func:`derived_support`, outside where ``outside`` says so: a legacy record, the
    one support standing at inference that no assistant's statement holds, so a writer
    creates such a memory (ADR-0345 §2:4, §8:3).

    Args:
        record_id: The memory's id.
        content: Its wording.
        band: The band its one support's origin ranks it in.
        outside: Whether a ``DERIVED`` memory's support is outside content.
        attestation: The source details of an ``ATTESTED`` memory's support.
        episode: The episode its support points into, or, for ``DERIVED``, the id of
            the legacy record it carries.
        when: Its support's ``when``.
        **envelope: Any other field of the memory, as :func:`memory` takes them.

    Returns:
        The memory.
    """
    match band:
        case BeliefBand.ASSERTED:
            support = said_support(episode, when=when)
        case BeliefBand.ATTESTED:
            support = sourced_support(attestation, episode=episode, when=when)
        case BeliefBand.DERIVED:
            support = derived_support(episode, outside=outside, when=when)
        case _:  # pragma: no cover - exhaustive
            assert_never(band)
    return memory(record_id, content, support, **envelope)

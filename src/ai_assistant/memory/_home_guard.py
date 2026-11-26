"""What the memory stores and the memory writer share about a record's home (ADR-0383 §4).

A write never changes a stored record's home (§4:6), and no record the memory store
holds names a record of another home it also holds, as a lineage or an evidence
pointer (§4:7, third item). Both are judged where both homes are at hand: the store
for every write it makes, and the writer for what it decides before it writes. Both
stores in this package and the ingestor import these, so they cannot disagree; the
canonical fakes in ``ai_assistant.testing`` repeat them, since that package may not
import a subsystem (golden rule 1), and the shared conformance suites run the same
cases against every implementation.

A store bound to a sight in the withholding mode also refuses a write adding a name
that resolves to no record it holds (ADR-0388 §2), :func:`refuse_unresolved_names`.

Every refusal here is :class:`~ai_assistant.core.errors.CrossHomeWriteError`, save that
one, :class:`~ai_assistant.core.errors.UnresolvedEvidenceError`; each with nothing
written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.errors import CrossHomeWriteError, UnresolvedEvidenceError
from ai_assistant.core.types import ConfirmationPart, EpisodicMemory, Memory, part_episode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from collections.abc import Set as AbstractSet

    from ai_assistant.core.types import MemoryRecord, RecordHome, SupportPart


def episode_address(activation_id: str) -> str:
    """The id of an activation's episode, ``activation:<activation_id>`` (ADR-0283 §2)."""
    return f"activation:{activation_id}"


def _memory_names(memory: Memory) -> set[str]:
    """The records a memory names: the episodes its evidence points at, and its lineage.

    The evidence pointers (ADR-0328 §4, §8, §9; ADR-0345 §7) are the episode of every
    part it carries, on a support, an operation, or an open question, of every
    track-record entry, and of every situation label that names one. A legacy part and a
    pin point into no episode (:func:`~ai_assistant.core.types.part_episode`); a
    confirmation points into two more, by activation: the asking activation's, whose
    round holds the question part the yes approved, and, on the request form, the one
    that ran the ticket (ADR-0328 §4:5, ADR-0361 §5:10). The lineage (§5:6) is every
    memory a create replaces and every memory an operation names as its successor.
    """
    parts: list[SupportPart] = [support.points_at for support in memory.supports]
    for operation in memory.operations:
        parts.append(operation.cites)
        if operation.stops is not None:
            parts.append(operation.stops)
    for question in memory.open_questions:
        parts.extend(question.rests_on)
        if question.resolved_by is not None:
            parts.append(question.resolved_by)
    names = {episode for episode in map(part_episode, parts) if episode is not None}
    for part in parts:
        if isinstance(part, ConfirmationPart):
            names.add(episode_address(part.asking_activation))
            if part.ran_in is not None:
                names.add(episode_address(part.ran_in))
    names.update(entry.episode for entry in memory.track_record)
    names.update(label.episode for label in memory.labels if label.episode is not None)
    for operation in memory.operations:
        names.update(operation.replaces)
        if operation.successor is not None:
            names.add(operation.successor)
    return names


def _episode_names(episode: EpisodicMemory) -> set[str]:
    """The episodes an episode names as its lineage (ADR-0349 §7:7, §7:21; ADR-0352 §5:2).

    The activation that took it over, and each activation a joined input was taken over
    from, each by its episode's id.
    """
    processing = episode.processing_record
    if processing is None:
        return set()
    activations = {one.taken_over_from for one in processing.joined}
    activations.add(processing.taken_over_by)
    return {episode_address(one) for one in activations if one is not None}


def named_records(record: MemoryRecord) -> frozenset[str]:
    """The ids of the records ``record`` names, as a lineage or an evidence pointer.

    ADR-0383 §4:7's third item, as far as it reaches this store's file: a member, a
    link, a pin, a mark and a reply name records another store holds. Its own id is
    left out.

    Args:
        record: An episode or a memory.

    Returns:
        The named ids.
    """
    names = _memory_names(record) if isinstance(record, Memory) else _episode_names(record)
    names.discard(record.id)
    return frozenset(names)


def refuse_home_change(stored: MemoryRecord, record: MemoryRecord) -> None:
    """Refuse a write of ``record`` over ``stored`` that changes its home (ADR-0383 §4:6).

    Raises:
        CrossHomeWriteError: The two homes differ.
    """
    if stored.home != record.home:
        msg = (
            f"cannot write {record.id!r} with a {record.home.kind} home: the record stored "
            f"under that id is of another home, and no write changes a record's home "
            f"(ADR-0383 §4:6)"
        )
        raise CrossHomeWriteError(msg)


def refuse_crossing_names(
    records: Iterable[MemoryRecord], home_of: Callable[[str], RecordHome | None]
) -> None:
    """Refuse records that name a record of another home this store holds (ADR-0383 §4:7).

    Judged over the state the write would leave: ``home_of`` answers the home a named id
    holds once the write is made, from the write itself where it writes that id, and
    otherwise from the store, or ``None`` where the store holds no record under it. A
    name of a record the store does not hold is not judged here: whether a support's
    episode is held is the writer's check (ADR-0328 §4:7).

    Args:
        records: The records the write would leave stored.
        home_of: The home each named id would hold, or ``None``.

    Raises:
        CrossHomeWriteError: A record names a record of another home.
    """
    for record in records:
        for name in sorted(named_records(record)):
            home = home_of(name)
            if home is not None and home != record.home:
                msg = (
                    f"cannot write {record.id!r}: it names {name!r}, a record of another "
                    f"home, as a lineage or an evidence pointer (ADR-0383 §4:7)"
                )
                raise CrossHomeWriteError(msg)


def refuse_other_home_evidence(memory: Memory, named: Mapping[str, MemoryRecord]) -> None:
    """Refuse a memory naming a record of another home it would write (ADR-0383 §4:7).

    The writer's check, before it seeks any ruling, on the records it read for what the
    memory names (:func:`named_records`): the episodes its supports point at, a
    confirmation's asking activation's, and every other name it carries. A fold writes
    the supports onto a stored memory and never the proposal's own record, so the store
    would not see the proposal's own names.

    Args:
        memory: The proposal's memory.
        named: The records it names that the store holds, by id.

    Raises:
        CrossHomeWriteError: One of them is of another home.
    """
    for name, found in named.items():
        if found.home != memory.home:
            msg = (
                f"refusing to write {memory.id!r}: it names {name!r}, a record of another "
                f"home (ADR-0383 §4:7)"
            )
            raise CrossHomeWriteError(msg)


def refuse_other_home_targets(
    memory: Memory, targets: Iterable[MemoryRecord], *, what: str
) -> None:
    """Refuse a write for ``memory`` that changes or places against a record of another home.

    ADR-0383 §4:7's first and second items, where the writer holds both homes in one
    write: a fold, a retirement or a placement the proposal's memory makes onto a stored
    memory changes that memory or names it, and the proposal's home is the write's
    (ADR-0369 §2:6, §2:7).

    Args:
        memory: The proposal's memory.
        targets: The stored memories the write would change or place against.
        what: What the write does to them, for the message.

    Raises:
        CrossHomeWriteError: A target is of another home than ``memory``.
    """
    for target in targets:
        if target.home != memory.home:
            msg = (
                f"refusing to write {memory.id!r}: it would {what} {target.id!r}, a memory "
                f"of another home (ADR-0383 §4:7)"
            )
            raise CrossHomeWriteError(msg)


def judged_names(record: MemoryRecord, *, own_episode: str | None) -> frozenset[str]:
    """The names of ``record`` ADR-0388 §2:1 judges: :func:`named_records`, save one lineage.

    The takeover lineage a work's capture writes on its own episode is not judged
    (§2:5): where ``record`` is the episode ``own_episode`` names, the episode of the
    activation of the sight the store is bound to, the activation that took it over
    and each activation a joined input was taken from are left out. Nothing else is.

    Args:
        record: An episode or a memory a write would leave stored.
        own_episode: The id of the bound sight's activation's episode, or ``None``
            where the sight carries no activation.

    Returns:
        The names judged.
    """
    names = named_records(record)
    if own_episode is not None and record.id == own_episode and isinstance(record, EpisodicMemory):
        return names - _episode_names(record)
    return names


def refuse_unresolved_names(
    records: Iterable[MemoryRecord],
    *,
    resolves: Callable[[str], bool],
    carried: Callable[[frozenset[str]], AbstractSet[str]],
    own_episode: str | None,
) -> None:
    """Refuse a write adding a name that resolves to no record the store holds (ADR-0388 §2).

    A withholding bound store's judgement, over the records it holds alone (§2:3,
    ADR-0383 §7:2): ``resolves`` answers whether a name resolves once the write is
    made, to a record of the same write or one the bound store holds, and ``carried``
    which of the names given a record the bound store holds already carried before
    the write, the record stored under the written id or any other (§2:2). It is asked
    only of names that do not resolve, so no index of names is needed (§9). A name
    withheld from the sight and one never written are refused alike, by the ids alone.

    Args:
        records: The records the write would leave stored, in the write's order.
        resolves: Whether a name resolves once the write is made.
        carried: Of the names given, those a held record already carried.
        own_episode: The id of the bound sight's activation's episode, whose takeover
            lineage is not judged (§2:5), or ``None``.

    Raises:
        UnresolvedEvidenceError: A record adds a name that does not resolve, naming
            each such name. Nothing is written.
    """
    unresolved: dict[str, list[str]] = {}
    for record in records:
        names = sorted(
            name for name in judged_names(record, own_episode=own_episode) if not resolves(name)
        )
        if names:
            unresolved[record.id] = names
    if not unresolved:
        return
    already = carried(frozenset(name for names in unresolved.values() for name in names))
    for record_id, names in unresolved.items():
        added = [name for name in names if name not in already]
        if added:
            msg = (
                f"cannot write {record_id!r}: it names "
                f"{', '.join(repr(name) for name in added)}, which resolves to no record "
                f"this store holds (ADR-0388 §2:1)"
            )
            raise UnresolvedEvidenceError(msg, added)

"""The episode window's pending candidates (ADR-0329 §3:3, §6:9).

A candidate is a ``remember`` call as its round records it, read with the episode's
labels and joined to its effect record (§3:3): no episode field, record or store holds
one. So the candidates an episode's own rounds recorded are read here from the episode
and the plan store, and an episode's are **pending** while the observer has not
processed it: where the plan store holds no observation record for it, or one not
marked processed, skipped or stuck (§16:1-§16:2, ``SETTLED_OBSERVATION_STATES``).

**The join** (§3:3). A round records the call as planning proposed it, its things named
by label; the effect record acting claimed it under names its round, its capability and
the digest of the values authorizing ruled on, those labels mapped to ids
(:func:`~ai_assistant.orchestration.authorizer.values_digest`). A recorded call is a
candidate of its episode exactly where an effect record of that episode's activation,
for that round, of ``remember``, with that digest and spending no question part, shows
it done. A call refused, not done, still needing the user, or naming a label the episode
does not record is no candidate. A candidate recorded under an approval is proposed by
its approved-action label, so no ``remember`` call is recorded for it in the yes's
rounds: it is shown in the question that asked it, whose exact line carries its fact
(§6:9), and not here.

**The panel's read** (§18:1-§18:2). :func:`held_candidates` is the same reading over
every episode, newest first, which the engine and the canonical fake engine both answer
``AssistantEngine.pending_candidates`` with. The panel shows the pending candidates
whole, so the walk has no horizon; what keeps it cheap is that each page of the episode
listing is narrowed by two batched reads of the plan store before any record is read in
full — an episode the observer has settled is passed over, and so is one whose
activation has no ``remember`` effect record done — so only an unsettled episode with a
done ``remember`` is fetched. And the panel, unlike the window, has no question to show
an approved candidate in, so this read adds **the candidates recorded under an
approval** (§3:3): a done ``remember`` effect record spending a question part names the
asking round and the part, the yes's understanding names the asking activation, and the
asked call the asking round recorded there carries the fact, its digest checked against
the effect record's.

**The observer reads the same join** (ADR-0329 §9:1): :func:`done_candidates` gives
one episode's candidates its own rounds recorded, each with its values and the id of the
effect record that shows it done, which is how a finding names the candidate it came
from (``ObservationFinding.candidate``).

A glue module of the phases, outside their ``independence`` contract: it reads
authorizing's digest and planning's mark, and no phase module imports it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from pydantic import ValidationError

from ai_assistant.core.types import (
    SETTLED_OBSERVATION_STATES,
    ActionRequest,
    EpisodicMemory,
    PendingCandidate,
    ToolOutcome,
)
from ai_assistant.orchestration.authorizer import values_digest
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.planning import DELIBERATE_REPEAT, LOOKING_FOR
from ai_assistant.orchestration.remembering import (
    CANDIDATE_LABEL_ARGUMENTS,
    EPISODE_ARGUMENT,
    FACT_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER_CANDIDATE,
    REMEMBER_CAPABILITY,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import MemoryStore, PlanStore
    from ai_assistant.core.types import (
        ActivationEffect,
        AskedCall,
        EpisodeProcessingRecord,
        EpisodeSummary,
        FrozenJson,
        PlanningLabel,
        PlanningRound,
        ProposedCall,
    )

__all__ = ["DoneCandidate", "done_candidates", "held_candidates", "pending_candidates"]

#: How many episodes one page of the panel's walk lists: the episode listing's most.
_EPISODE_PAGE: Final = 100

#: A round, an activation and a values digest: the key a done candidate's record joins on.
type _Done = frozenset[tuple[str, str, str]]


async def pending_candidates(
    plans: PlanStore, episodes: Sequence[EpisodicMemory], /
) -> dict[str, tuple[str, ...]]:
    """Each unprocessed episode's pending candidates, by its id (ADR-0329 §6:9).

    Args:
        plans: The plan store the observation records and effect records are read from.
        episodes: The episodes the window shows. An open one, or one with no processing
            record, records no round and has none.

    Returns:
        For each episode the observer has not processed whose rounds recorded a
        candidate, the candidates' facts in the order recorded; an episode with none is
        left out.

    Raises:
        PlanningError: If the plan store cannot be read.
    """
    recorded = [
        (record.id, processing)
        for record in episodes
        if (processing := record.processing_record) is not None
        and not processing.is_open
        and any(call.name == REMEMBER_CAPABILITY for one in processing.rounds for call in one.calls)
    ]
    if not recorded:
        return {}
    held = {one.episode: one for one in await plans.observations([one for one, _ in recorded])}
    unprocessed = [
        (episode, processing)
        for episode, processing in recorded
        if (observed := held.get(episode)) is None
        or observed.state not in SETTLED_OBSERVATION_STATES
    ]
    if not unprocessed:
        return {}
    effects = await plans.activation_effects([one.activation_id for _, one in unprocessed])
    # An effect spending a question part is the approved call's, whatever a call of
    # the same round with the same values says: it shows no recorded call done (§3:3).
    done: _Done = frozenset(
        (effect.activation_id, effect.round, effect.values_digest)
        for effect in effects
        if effect.capability == REMEMBER_CAPABILITY
        and effect.outcome is ToolOutcome.SUCCEEDED
        and effect.round is not None
        and effect.values_digest is not None
        and effect.part is None
    )
    pending: dict[str, tuple[str, ...]] = {}
    for episode, processing in unprocessed:
        facts = _facts(episode, processing, done)
        if facts:
            pending[episode] = facts
    return pending


@dataclass(frozen=True, slots=True)
class DoneCandidate:
    """One candidate an episode's own rounds recorded, joined to its effect record (§3:3).

    Attributes:
        effect: The id of the effect record that shows the ``remember`` call done.
        round: The id of the round that recorded the call.
        fact: The candidate's fact.
        values: The call's values as authorizing ruled on them, its labels mapped to
            the ids the episode recorded, which
            :func:`~ai_assistant.orchestration.remembering.candidate_of` reads.
    """

    effect: str
    round: str
    fact: str
    values: Mapping[str, FrozenJson]


def done_candidates(
    episode: str, processing: EpisodeProcessingRecord, effects: Sequence[ActivationEffect], /
) -> tuple[DoneCandidate, ...]:
    """The candidates one episode's own rounds recorded that its effect records show done.

    The join :func:`pending_candidates` makes, keeping each candidate's effect record:
    an effect record of the episode's activation, for the call's round, of ``remember``,
    with the call's digest and spending no question part, shows it done.

    Args:
        episode: The episode's id, exactly as held.
        processing: Its processing record.
        effects: Effect records read for its activation; others are passed over.

    Returns:
        Its candidates in the order its rounds recorded them.
    """
    done = {
        (effect.activation_id, effect.round, effect.values_digest): effect.id
        for effect in effects
        if _done_remember(effect) and effect.part is None
    }
    labels = {one.label: one for one in processing.labels}
    joined: list[DoneCandidate] = []
    for one in processing.rounds:
        for call in one.calls:
            if call.name != REMEMBER_CAPABILITY:
                continue
            values = _ruled_values(call, labels)
            digest = None if values is None else _digest(episode, values)
            if digest is None or values is None:
                continue
            effect = done.get((processing.activation_id, one.id, digest))
            fact = values.get(FACT_ARGUMENT)
            if effect is not None and isinstance(fact, str):
                joined.append(DoneCandidate(effect=effect, round=one.id, fact=fact, values=values))
    return tuple(joined)


async def held_candidates(memory: MemoryStore, plans: PlanStore, /) -> tuple[PendingCandidate, ...]:
    """Every pending candidate, as the panel shows them (ADR-0329 §18:1).

    Args:
        memory: The store the episodes are read from.
        plans: The plan store the observation records and effect records are read from.

    Returns:
        Each pending candidate by its episode and its fact, the most recent episode's
        first; within an episode, those its own rounds recorded in the order recorded,
        then those recorded under an approval in the order they ran.

    Raises:
        MemoryStoreError: If the episodes cannot be read.
        PlanningError: If the plan store cannot be read.
    """
    held: list[PendingCandidate] = []
    cursor: str | None = None
    while True:
        page = await memory.episodes(cursor=cursor, limit=_EPISODE_PAGE)
        held.extend(await _page_candidates(memory, plans, page.items))
        # Progress is the cursor's: a store handing back the cursor it was given would
        # otherwise be walked forever.
        if page.next_cursor is None or page.next_cursor == cursor:
            return tuple(held)
        cursor = page.next_cursor


async def _page_candidates(
    memory: MemoryStore, plans: PlanStore, rows: Sequence[EpisodeSummary]
) -> list[PendingCandidate]:
    """The pending candidates of one page of the episode listing, in its order."""
    named = {
        row.position.episode_id: row.activation_id
        for row in rows
        if row.has_processing_record and row.activation_id is not None
    }
    if not named:
        return []
    settled = {
        one.episode
        for one in await plans.observations(list(named))
        if one.state in SETTLED_OBSERVATION_STATES
    }
    unsettled = {
        episode: activation for episode, activation in named.items() if episode not in settled
    }
    if not unsettled:
        return []
    done: dict[str, list[ActivationEffect]] = {}
    for effect in await plans.activation_effects(list(unsettled.values())):
        if _done_remember(effect):
            done.setdefault(effect.activation_id, []).append(effect)
    wanted = [episode for episode, activation in unsettled.items() if activation in done]
    if not wanted:
        return []
    found = without_open_episodes(await memory.get_many(wanted))
    episodes = [record for one in wanted if isinstance(record := found.get(one), EpisodicMemory)]
    own = await pending_candidates(plans, episodes)
    approved = await _approved_candidates(memory, episodes, done)
    return [
        PendingCandidate(episode_id=episode.id, fact=fact)
        for episode in episodes
        for fact in (*own.get(episode.id, ()), *approved.get(episode.id, ()))
    ]


def _done_remember(effect: ActivationEffect) -> bool:
    """Whether an effect record shows a ``remember`` call done, as a candidate's must."""
    return (
        effect.capability == REMEMBER_CAPABILITY
        and effect.outcome is ToolOutcome.SUCCEEDED
        and effect.round is not None
        and effect.values_digest is not None
    )


async def _approved_candidates(
    memory: MemoryStore,
    episodes: Sequence[EpisodicMemory],
    done: Mapping[str, Sequence[ActivationEffect]],
) -> dict[str, tuple[str, ...]]:
    """Each episode's candidates recorded under an approval, by its id (ADR-0329 §3:3).

    A ``remember`` run on a yes is proposed by its approved-action label, so the yes's
    rounds record no ``remember`` call for it; its effect record spends the question
    part the asking round showed it under (ADR-0321 §4:9). The candidate is that asked
    call as the asking round recorded it (§2:8), and its values already name things by
    id. The asking activation is one the yes's understanding answers (§3:1).
    """
    spent = {
        episode.id: [effect for effect in done.get(activation, ()) if effect.part is not None]
        for episode in episodes
        if (processing := episode.processing_record) is not None
        and (activation := processing.activation_id)
    }
    asking_of = {episode.id: _asking(episode) for episode in episodes if spent.get(episode.id)}
    addresses = sorted({address for named in asking_of.values() for address in named})
    if not addresses:
        return {}
    asking = without_open_episodes(await memory.get_many(addresses))
    facts: dict[str, tuple[str, ...]] = {}
    for episode, named in asking_of.items():
        rounds = {
            one.id: one
            for address in named
            if isinstance(record := asking.get(address), EpisodicMemory)
            and record.processing_record is not None
            for one in record.processing_record.rounds
        }
        found = [
            fact
            for effect in spent[episode]
            if (fact := _approved_fact(effect, rounds)) is not None
        ]
        if found:
            facts[episode] = tuple(found)
    return facts


def _asking(episode: EpisodicMemory) -> tuple[str, ...]:
    """The addresses of the episodes whose questions an episode's understanding answers.

    None: since ADR-0353 §11:2 no understanding version records an answer pointer, and
    the upgrade dropped every one stored before (§9:6).
    """
    del episode
    return ()


def _approved_fact(effect: ActivationEffect, rounds: Mapping[str, PlanningRound]) -> str | None:
    """The fact of the asked call an approved effect record spent, or ``None``.

    ``None`` where the asking round is not among those read, it asked no such part, the
    part is no candidate, or its digest is not the one the effect record claimed.
    """
    part = effect.part
    if part is None or (asking := rounds.get(part.round)) is None:
        return None
    asked: AskedCall | None = next((one for one in asking.asked if one.part == part.part), None)
    if asked is None or asked.tool.capability != REMEMBER_CAPABILITY:
        return None
    try:
        digest = values_digest(asked.request)
    except ValueError:
        return None
    fact = asked.values.get(FACT_ARGUMENT)
    if digest != effect.values_digest or not isinstance(fact, str):
        return None
    return fact


def _facts(episode: str, processing: EpisodeProcessingRecord, done: _Done) -> tuple[str, ...]:
    """The facts of the candidates one episode's rounds recorded that its records show done."""
    labels = {one.label: one for one in processing.labels}
    facts: list[str] = []
    for one in processing.rounds:
        for call in one.calls:
            if call.name != REMEMBER_CAPABILITY:
                continue
            values = _ruled_values(call, labels)
            digest = None if values is None else _digest(episode, values)
            if digest is None or values is None:
                continue
            fact = values.get(FACT_ARGUMENT)
            if (processing.activation_id, one.id, digest) in done and isinstance(fact, str):
                facts.append(fact)
    return tuple(facts)


def _digest(episode: str, values: dict[str, FrozenJson]) -> str | None:
    """The digest of ``values`` authorizing's request carried, or ``None``.

    The request carries the two arguments the hub fills (ADR-0329 §3:4), which the
    digest leaves out (ADR-0306 §2:10), so any value of theirs gives the same digest.
    ``None`` where the values do not satisfy the declaration's schema: such a call was
    not done, so it is no candidate.
    """
    filled: dict[str, FrozenJson] = {
        **values,
        EPISODE_ARGUMENT: episode,
        OUTSIDE_CONTENT_ARGUMENT: False,
    }
    try:
        request = ActionRequest(tool=REMEMBER_CANDIDATE, parameters=filled)
    except ValidationError, ValueError:
        return None
    return values_digest(request)


def _ruled_values(
    call: ProposedCall, labels: Mapping[str, PlanningLabel]
) -> dict[str, FrozenJson] | None:
    """A recorded call's values as authorizing ruled on them, or ``None``.

    Planning's check takes out the *looking for* and the *deliberate repeat* mark and
    maps each label argument to the ids its labels name (ADR-0307 §5:3, ADR-0306
    §2:10); this does the same with the episode's recorded labels. ``None`` where a
    label names nothing the episode records, or a thing of another kind: such a call
    was refused before it ran.
    """
    values: dict[str, FrozenJson] = dict(call.model_dump()["arguments"])
    values.pop(DELIBERATE_REPEAT, None)
    values.pop(LOOKING_FOR, None)
    for argument, kind in CANDIDATE_LABEL_ARGUMENTS[REMEMBER_CAPABILITY].items():
        if argument not in values:
            continue
        given = values[argument]
        named = [given] if isinstance(given, str) else given
        if not isinstance(named, list):
            return None
        ids: list[str] = []
        for label in named:
            known = labels.get(label) if isinstance(label, str) else None
            if known is None or known.kind is not kind:
                return None
            ids.append(known.id)
        values[argument] = ids[0] if isinstance(given, str) else cast("FrozenJson", ids)
    return values

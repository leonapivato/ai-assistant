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
for that round, of ``remember``, with that digest, shows it done. A call refused, not
done, still needing the user, or naming a label the episode does not record is no
candidate. A candidate recorded under an approval is proposed by its approved-action
label, so no ``remember`` call is recorded for it in the yes's rounds: it is shown in the
question that asked it, whose exact line carries its fact (§6:9), and not here.

A glue module of the phases, outside their ``independence`` contract: it reads
authorizing's digest and planning's mark, and no phase module imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from ai_assistant.core.types import (
    SETTLED_OBSERVATION_STATES,
    ActionRequest,
    ToolOutcome,
)
from ai_assistant.orchestration.authorizer import values_digest
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

    from ai_assistant.core.protocols import PlanStore
    from ai_assistant.core.types import (
        EpisodeProcessingRecord,
        EpisodicMemory,
        FrozenJson,
        PlanningLabel,
        ProposedCall,
    )

__all__ = ["pending_candidates"]

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
    done: _Done = frozenset(
        (effect.activation_id, effect.round, effect.values_digest)
        for effect in effects
        if effect.capability == REMEMBER_CAPABILITY
        and effect.outcome is ToolOutcome.SUCCEEDED
        and effect.round is not None
        and effect.values_digest is not None
    )
    pending: dict[str, tuple[str, ...]] = {}
    for episode, processing in unprocessed:
        facts = _facts(episode, processing, done)
        if facts:
            pending[episode] = facts
    return pending


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

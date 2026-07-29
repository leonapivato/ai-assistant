r"""The model-backed observer (ADR-0077).

The production :class:`~ai_assistant.core.protocols.Observer`: it reads a bounded
batch of :class:`~ai_assistant.core.types.EpisodicMemory` records — what actually
happened — and proposes what the system should believe about the user as a
result, by prompting an injected
:class:`~ai_assistant.core.protocols.ModelProvider` for a JSON envelope and
distilling that text into :class:`~ai_assistant.core.types.MemoryUpdateProposal`\ s.

It lives in `learning` because that is the subsystem ADR-0005 §3 gives the
observations-to-proposals job, and it is the placement ADR-0077 §9.5 names. Four
boundaries shape the module:

- **It holds no store and no writer.** Episodes in, proposals out; the scope of
  observation is a property of the seam rather than of this code (ADR-0077 §1),
  and the ingesting stage — never this class — puts each proposal through the
  ratified ``MemoryPolicy`` gate. ADR-0075 §2 names this producer as the paradigm
  case the gate exists for, and it is not exempt from it.
- **The citations are ours, never the model's.** The prompt labels each episode
  and the model cites labels; this module maps every label back to the id of the
  episode it actually read (ADR-0047 §2's rule applied to evidence). A model that
  can write an id can write one for an episode it never saw.
- **The confidence is ours, never the model's.** :func:`_confidence` is a pure
  function of the epistemic step and the number of distinct supporting episodes —
  no clock, no randomness, nothing from the response — so re-observing the same
  episodes cannot inflate a belief through a ``REINFORCE`` that takes the maximum
  (ADR-0077 §5, §8).
- **A malformed response degrades; a model failure propagates.** Entries that
  cannot be used are discarded and *counted* rather than repaired, invented, or
  re-prompted for: an observation has nothing waiting on it, so the cheap remedy
  is a later run rather than a second call inside this one (ADR-0077 §4).

The envelope schema below is this implementation's, not the ``Observer`` seam's.
ADR-0077 §9.5 deliberately declines to ratify one — a second observer would
legitimately prompt differently, as a second ``Planner`` would — so it is fixed
here, in the lane that runs it against a real model, exactly as ADR-0047 §4 fixed
the planner's.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.types import (
    MemorySource,
    MemoryUpdateProposal,
    Message,
    ObservationOutcome,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    Role,
    SemanticMemory,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import EpisodicMemory, MemoryRecord

#: The batch bound ADR-0077 §1 names and the proposal bound §2 names, as
#: defaults. Both are *also* ``Settings`` fields, so the composition root passes
#: the operator's values; these are what the class does when nobody says.
DEFAULT_OBSERVATION_BATCH_SIZE: Final = 20
DEFAULT_OBSERVATION_MAX_PROPOSALS: Final = 5

#: The most decode **misses** :func:`_extract_object` tolerates in one reply
#: before giving up, for the reason ``planning.planner`` records: a failed
#: ``raw_decode`` costs work proportional to how far into the reply it reached, so
#: attempting it at every brace of a brace-dense reply is quadratic and blocks the
#: event loop. Bounding the misses keeps the scan linear.
_MAX_EXTRACTION_MISSES: Final = 256

#: This producer's confidence ladder: ``(base, ceiling)`` per epistemic step, plus
#: what one further distinct supporting episode adds. The *values* are this
#: implementation's — ADR-0077 §5 ratifies the properties and leaves the constants
#: to the lane, as ADR-0074 §4 did for capture — but the shape is contract:
#: strictly below 1.0 always, ``OBSERVED`` above ``INFERRED`` on equal support
#: (the latter took a step the evidence does not entail), non-decreasing in
#: support, under a ceiling, and a pure function of those two inputs alone.
#:
#: The ceilings are what keep the ladder honest at the top: an observation is
#: never as good as being told, however many times it recurs, and without a
#: ceiling a long enough batch would walk a derived belief up to the standing only
#: the user's own word carries.
_LADDER: Final[dict[MemorySource, tuple[float, float]]] = {
    MemorySource.OBSERVED: (0.55, 0.85),
    MemorySource.INFERRED: (0.35, 0.70),
}
_SUPPORT_INCREMENT: Final = 0.05

#: How many *distinct* supporting episodes each step needs before a belief may be
#: proposed at all (ADR-0077 §5). An ``OBSERVED`` belief restates what its
#: evidence directly shows, so one episode entails it; an ``INFERRED`` belief
#: generalises beyond the evidence, and a generalisation from a single instance is
#: the exact shape of "a single unusual interaction hardens into a permanent,
#: wrong preference" (ADR-0005 §Context).
_EVIDENCE_FLOOR: Final[dict[MemorySource, int]] = {
    MemorySource.OBSERVED: 1,
    MemorySource.INFERRED: 2,
}

#: The record kinds an observer may propose. ``EPISODIC`` is absent by decision,
#: not by omission: an episode is a record that something happened, and the only
#: thing entitled to write one is the deterministic capture path that was present
#: when it happened (ADR-0077 §2).
_PROPOSABLE_KINDS: Final = frozenset({"semantic", "preference", "procedural"})

_SYSTEM_PROMPT = """\
You are the observation stage of an AI assistant. You are shown a batch of \
recorded episodes — things that happened — and you propose what the assistant \
should durably believe about the user as a result.

Propose a belief only when it is ABOUT THE USER and would change a later answer: \
a preference, a durable fact about them or their world, a workflow they follow. \
Do not summarise the exchange. Do not propose what merely happened; that is \
already recorded. Proposing nothing is a perfectly good answer.

Each belief takes one of two epistemic steps:
- "observed" — the cited episodes directly show it. One episode may be enough.
- "inferred" — you generalised beyond what the episodes show. Cite at least TWO \
different episodes; a generalisation from a single episode will be discarded.

Cite episodes by the labels in brackets, exactly as they appear. Never invent a \
label, and never cite one that is not in the batch.

Reply with a single JSON object and nothing else — no prose, no code fence:

{"beliefs": [
   {"kind": "semantic" | "preference" | "procedural",
    "step": "observed" | "inferred",
    "content": "<the belief, in one sentence>",
    "evidence": ["<label>", ...],
    "rationale": "<why the cited episodes justify it>",
    "steps": ["<ordered step>", ...]}
 ]}

`beliefs` must be a list, and may be empty. `steps` applies to a "procedural" \
belief only and is otherwise ignored. Do not include ids, confidence values, or \
timestamps; those are assigned downstream."""


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _confidence(step: MemorySource, supports: int) -> float:
    """This producer's confidence for ``supports`` distinct episodes taken by ``step``.

    Pure in exactly the two inputs ADR-0077 §5 allows, so the same evidence yields
    the same number however many times it is derived. That is what closes the
    repetition route to inflation: a second pass over one batch re-proposes the
    belief, the gate folds it as a ``REINFORCE``, and the fold's maximum finds
    nothing higher.
    """
    base, ceiling = _LADDER[step]
    return min(base + _SUPPORT_INCREMENT * (supports - 1), ceiling)


class ModelBackedObserver:
    """An ``Observer`` that distils beliefs out of episodes with an LLM.

    Structurally implements :class:`~ai_assistant.core.protocols.Observer`. The
    model proposes each belief's kind, epistemic step, content and citations; this
    class mints the ids, maps the citations back onto the episodes it actually
    read, computes the confidence, stamps the timestamp, applies its own bound,
    and counts everything it threw away (ADR-0077).
    """

    def __init__(
        self,
        model: ModelProvider,
        *,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        max_batch_size: int = DEFAULT_OBSERVATION_BATCH_SIZE,
        max_proposals: int = DEFAULT_OBSERVATION_MAX_PROPOSALS,
    ) -> None:
        """Create an observer over an injected model, clock and id factory.

        Args:
            model: The model seam that reads the episodes. The only dependency on
                the LLM; no provider SDK is imported (golden rule 4). **It must
                not fall back** — ADR-0077 §3 rules that an observation's failure
                is never re-sent to a second provider, because fallback buys
                reliability by widening the set of providers that see a prompt and
                an observation is deferrable, so the reliability is worth nothing
                and the widening is the one cost that matters. That is a property
                of the provider the composition root builds and hands in; this
                class cannot enforce it and does not pretend to.
            now: Clock for each proposal's ``provenance.last_updated``; injectable
                for deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7).
            id_factory: Mints the id of every proposed record; injectable so tests
                assert exact ids (ADR-0047 §2). Defaults to random UUIDs.
            max_batch_size: The largest batch this observer accepts. A longer one
                is refused, never truncated (ADR-0077 §1).
            max_proposals: The most proposals one call may return. Usable beliefs
                beyond it are discarded and counted, never queued (ADR-0077 §2).

        Raises:
            TypeError: If either bound is not an ``int`` (``bool`` included).
            ValueError: If either bound is below 1. A zero batch bound observes
                nothing while reporting health; a zero proposal bound could never
                propose anything.
        """
        _check_bound("max_batch_size", max_batch_size)
        _check_bound("max_proposals", max_proposals)
        self._model = model
        self._clock = checked_clock(now, owner="ModelBackedObserver")
        self._id_factory = id_factory
        self._max_batch_size = max_batch_size
        self._max_proposals = max_proposals

    @property
    def max_batch_size(self) -> int:
        """The largest batch this observer accepts."""
        return self._max_batch_size

    @property
    def max_proposals(self) -> int:
        """The most proposals one ``observe`` call may return."""
        return self._max_proposals

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose what ``episodes`` justifies believing about the user.

        The batch is observed **once**, on this coroutine's first executed line
        and before the first ``await`` (ADR-0065). A shallow tuple is a complete
        snapshot: the container is the caller's and mutable, while every
        :class:`~ai_assistant.core.types.EpisodicMemory` in it is frozen
        (ADR-0068). Without it, a caller mutating its own list across the model
        round trip — the widest suspension window in the system — would get
        beliefs whose citations name episodes the model was never shown.

        An **empty batch reaches no model**: there is nothing to observe, and
        sending an empty prompt would spend an egress of the most sensitive data
        the system holds to be told nothing.

        Args:
            episodes: The batch to observe, as a set of at most
                :attr:`max_batch_size` records.

        Returns:
            The proposals distilled from the batch, and the two counts of what was
            thrown away getting there.

        Raises:
            ValueError: If ``episodes`` exceeds :attr:`max_batch_size` or repeats
                an episode id — refused rather than truncated or de-duplicated
                (ADR-0077 §1) — or if the injected clock's reading does not
                conform (a :class:`~ai_assistant.core.clock.ClockReadingError`,
                which is a ``ValueError`` and is left unwrapped: `learning` has no
                error class of its own to translate it into, and the distinct
                subclass keeps it separable from a malformed batch).
            ModelError: Propagated unwrapped from the provider, its classification
                intact (ADR-0013 §5). The caller asked for observation and it did
                not happen; returning "no beliefs" would be indistinguishable from
                "nothing to learn" (ADR-0022 §3).
        """
        batch = tuple(episodes)
        _check_batch(batch, self._max_batch_size)
        if not batch:
            return ObservationOutcome()

        # Read **once**, and before the model call: once, so every proposal in one
        # outcome carries the same transaction time rather than a spread of them
        # from a clock that moved while the loop ran; and before, so a
        # misconfigured clock costs no egress of the batch to find out.
        now = self._clock()
        labels = {f"E{index + 1}": record.id for index, record in enumerate(batch)}
        conversation = [
            Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
            Message(role=Role.USER, content=_render_batch(batch)),
        ]
        reply = await self._model.complete(conversation)
        return self._distil(reply.content, labels, now)

    def _distil(self, content: str, labels: dict[str, str], now: datetime) -> ObservationOutcome:
        """Turn one model reply into proposals and the two discard counts.

        **Validate every entry first, then apply the bound to the survivors**, in
        that order, because both halves of it are observable and ADR-0077 §4
        ratifies it rather than leaving it to be discovered. Capping first would
        put an unusable entry into ``discarded_over_limit`` when it happened to
        sit past the cut and into ``discarded_unusable`` when it did not — two
        conforming producers reporting different outcomes for one response — and,
        worse, would let a malformed entry occupy a slot a good one could have
        filled, so six entries of which one was junk would yield four proposals
        instead of five.
        """
        entries = _entries(content)
        if entries is None:
            # An envelope that does not decode, or that carries no `beliefs` list,
            # counts as exactly one entry and that entry is unusable (ADR-0077
            # §4). Without the synthetic unit, "I cannot help" yields zero
            # proposals and zero discards, which is indistinguishable from a model
            # that read the batch and honestly proposed nothing — the one
            # confusion this counting exists to remove.
            return ObservationOutcome(discarded_unusable=1)

        usable: list[MemoryUpdateProposal] = []
        unusable = 0
        for entry in entries:
            proposal = self._to_proposal(entry, labels, now)
            if proposal is None:
                unusable += 1
            else:
                usable.append(proposal)
        return ObservationOutcome(
            proposals=tuple(usable[: self._max_proposals]),
            discarded_unusable=unusable,
            discarded_over_limit=max(len(usable) - self._max_proposals, 0),
        )

    def _to_proposal(
        self, entry: object, labels: dict[str, str], now: datetime
    ) -> MemoryUpdateProposal | None:
        """Build one proposal, or ``None`` where the entry cannot be used.

        Every refusal here is counted as ``discarded_unusable`` by the caller and
        none is repaired: an unmappable citation is dropped rather than replaced,
        and a belief left citing nothing is discarded rather than propped up with
        the batch wholesale. Evidence attached to satisfy a rule is not evidence,
        and it would make the "why do you believe that?" answer a list of
        everything the observer happened to be reading (ADR-0077 §5).
        """
        if not isinstance(entry, dict):
            return None
        kind = entry.get("kind")
        step = _step_of(entry.get("step"))
        text = entry.get("content")
        if kind not in _PROPOSABLE_KINDS or step is None:
            return None
        if not isinstance(text, str) or not text.strip():
            return None

        cited = _resolve(entry.get("evidence"), labels)
        if len(cited) < _EVIDENCE_FLOOR[step]:
            return None

        rationale = entry.get("rationale")
        provenance = Provenance(
            source=step,
            confidence=_confidence(step, len(cited)),
            evidence=cited,
            last_updated=now,
        )
        try:
            record = _record(
                str(kind), text.strip(), entry.get("steps"), provenance, self._id_factory()
            )
        except ValidationError:
            # A `core` invariant the entry's own text broke. Counted like any
            # other refusal rather than raised: one bad belief in a batch is a
            # degradation, not a failed observation (ADR-0077 §4).
            return None
        return MemoryUpdateProposal(
            proposed=record,
            rationale=rationale.strip()
            if isinstance(rationale, str) and rationale.strip()
            else f"observed across {len(cited)} episode(s)",
        )


def _check_bound(name: str, value: int) -> None:
    """Refuse a non-positive or non-integral bound at construction.

    Validated here rather than at first use, for ADR-0022 §4a's reason: a bound
    the caller got wrong should fail where it was set, not on the first
    observation that silently does half the work.

    Raises:
        TypeError: If ``value`` is not an ``int`` (``bool`` included).
        ValueError: If ``value`` is below 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{name} must be an integer, got {value!r}"
        raise TypeError(msg)
    if value < 1:
        msg = f"{name} must be at least 1, got {value}"
        raise ValueError(msg)


def _check_batch(batch: Sequence[EpisodicMemory], maximum: int) -> None:
    """Refuse an oversized or repeating batch (ADR-0077 §1).

    Raises:
        ValueError: If ``batch`` is longer than ``maximum``, or names one episode
            twice. Neither is repaired: a silent truncation disables half the work
            while the caller keeps reporting health, and a silent de-duplication
            hides a selection bug — the route by which one episode becomes the two
            distinct supports an ``INFERRED`` belief owes.
    """
    if len(batch) > maximum:
        msg = (
            f"batch of {len(batch)} episodes exceeds the configured maximum of "
            f"{maximum}; it is refused, never truncated"
        )
        raise ValueError(msg)
    ids = [record.id for record in batch]
    if len(set(ids)) != len(ids):
        msg = (
            "a batch is a set: an episode appears in it at most once, and a repeat "
            "would let one observation supply two distinct supports"
        )
        raise ValueError(msg)


def _render_batch(batch: Sequence[EpisodicMemory]) -> str:
    """Render the batch as the labelled user turn.

    **The payload is the batch and nothing else** (ADR-0077 §3): each episode's
    canonical ``content`` (ADR-0005 §1) and the label the model cites it by. Not
    the user's existing beliefs, not the profile, not a context facet, not a plan
    — de-duplication is the gate's job, deterministically and locally, and paying
    for it with a second class of Tier 1 data in the prompt would trade ADR-0004
    §7's minimisation for something already solved.

    Not the store ids either, and that is the same rule from the other side: the
    model has no use for an id it is not allowed to cite, and an id in the prompt
    is an id a model can echo back.
    """
    lines = ["Episodes:"]
    lines += [f"  [E{index + 1}] {record.content}" for index, record in enumerate(batch)]
    return "\n".join(lines)


def _step_of(raw: object) -> MemorySource | None:
    """Map the envelope's ``step`` onto an epistemic step, or ``None``."""
    match raw:
        case "observed":
            return MemorySource.OBSERVED
        case "inferred":
            return MemorySource.INFERRED
        case _:
            return None


def _resolve(raw: object, labels: dict[str, str]) -> tuple[str, ...]:
    """Map cited labels back onto the ids of the episodes actually read.

    A label that does not map is **dropped**, never repaired (ADR-0077 §5), and
    the result is de-duplicated in citation order: two labels resolving to one
    episode are one support, which is the same rule the duplicate-batch refusal
    enforces from the input side.
    """
    if not isinstance(raw, list):
        return ()
    resolved = [labels[label] for label in raw if isinstance(label, str) and label in labels]
    return tuple(dict.fromkeys(resolved))


def _record(
    kind: str,
    content: str,
    raw_steps: object,
    provenance: Provenance,
    record_id: str,
) -> MemoryRecord:
    """Build the typed record the entry names.

    ``episodic`` is unreachable: :data:`_PROPOSABLE_KINDS` refuses it before this
    is called, which is why there are three arms and no fourth.
    """
    match kind:
        case "preference":
            return PreferenceMemory(
                id=record_id, content=content, provenance=provenance, preference=content
            )
        case "procedural":
            steps = (
                tuple(step.strip() for step in raw_steps if isinstance(step, str) and step.strip())
                if isinstance(raw_steps, list)
                else ()
            )
            return ProceduralMemory(
                id=record_id,
                content=content,
                provenance=provenance,
                situation=content,
                steps=steps,
            )
        case _:
            return SemanticMemory(
                id=record_id, content=content, provenance=provenance, fact=content
            )


def _entries(content: str) -> list[object] | None:
    """The envelope's ``beliefs`` list, or ``None`` where there is no usable one.

    ``None`` is the synthetic single unusable entry of ADR-0077 §4 — a reply that
    decodes to no object at all, or to one carrying no ``beliefs`` list. An
    envelope whose ``beliefs`` is present and *empty* is not that case: it is a
    model that read the batch and honestly proposed nothing, which is a normal
    outcome and must not be reported as a discard.
    """
    envelope = _extract_object(content)
    if envelope is None:
        return None
    beliefs = envelope.get("beliefs")
    return beliefs if isinstance(beliefs, list) else None


def _extract_object(content: str) -> dict[str, object] | None:
    """Decode the JSON envelope embedded in ``content``, or ``None``.

    ADR-0071's scan, duplicated from ``planning.planner`` rather than promoted:
    ADR-0077 §9.5 rules that the extraction helper stays in the producing
    subsystem, because two implementations of one scan is cheaper than promoting a
    non-contract helper into `core` on speculation — and the *third* model-backed
    producer is the trigger to promote it, the discipline ADR-0028 §7 and ADR-0045
    §1 each applied. What must not happen is a producer re-deriving ADR-0047 §4
    step 1's superseded first-``{``-to-last-``}`` slice, which spans a prose brace
    and the envelope's closer at once (#293).

    Each ``{`` is tried left to right with :meth:`json.JSONDecoder.raw_decode`,
    which stops at the end of the object and ignores trailing text, so a model
    that wraps the object in prose or a code fence is tolerated. The **envelope**
    is preferred over the leftmost object: the first candidate carrying a
    ``beliefs`` list wins, so a decoy object in the prose ahead of it is stepped
    over rather than distilled from. Where none is well-formed the first decoded
    object stands in, so a single malformed envelope reaches the caller's precise
    verdict rather than a generic miss. A decoded object is advanced *past*, never
    re-entered, so a nested object is part of its parent rather than a separate
    candidate.

    At most :data:`_MAX_EXTRACTION_MISSES` decode **misses** are tolerated, which
    keeps the scan linear; a decoded object never counts as a miss, so any number
    of valid JSON fragments may precede the envelope. A candidate raising for a
    bounded reason that is not a syntax miss — CPython's digit-limit
    ``ValueError``, a ``RecursionError`` on a pathologically nested payload — is a
    miss like any other, so nothing escapes this scan.
    """
    decoder = json.JSONDecoder()
    first: dict[str, object] | None = None
    misses = 0
    index = 0
    length = len(content)
    while index < length:
        if content[index] != "{":
            index += 1
            continue
        try:
            candidate, end = decoder.raw_decode(content, index)
        except ValueError, RecursionError:
            misses += 1
            if misses > _MAX_EXTRACTION_MISSES:
                break
            index += 1
            continue
        if isinstance(candidate, dict):
            if isinstance(candidate.get("beliefs"), list):
                return candidate
            if first is None:
                first = candidate
        index = end
    return first


__all__ = [
    "DEFAULT_OBSERVATION_BATCH_SIZE",
    "DEFAULT_OBSERVATION_MAX_PROPOSALS",
    "ModelBackedObserver",
]

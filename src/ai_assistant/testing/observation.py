"""A canonical :class:`~ai_assistant.core.protocols.Observer` fake (ADR-0077).

The shared test double for the ``Observer`` contract, so a subsystem that drives
observation — `orchestration`, above all — can exercise every branch of its own
pipeline *without importing the learning subsystem's internals* (CLAUDE.md golden
rule 1) and without reaching a model provider.

It is deliberately not scriptable at the level of a finished
:class:`~ai_assistant.core.types.MemoryUpdateProposal`. A consumer scripts
:class:`ObservedBelief` *templates* — what to believe, by which epistemic step,
on how much support — and the fake supplies the evidence from the batch it is
actually handed, mints the id, and computes the confidence. That is what keeps
the canonical fake from being configurable into breaking its own contract
(``FakeFeedbackProcessor`` makes the same trade for a different reason): a
scripted proposal would carry citations chosen before the batch existed, so the
first consumer to script one would get a fake that violates the one clause the
``Observer`` suite cares most about — every cited id is drawn from the batch.

Beyond the contract it records every batch it was given to :attr:`batches`, so a
test can assert what its subject selected. Only the behaviour pinned by the
shared ``Observer`` conformance suite is part of the contract; the scripting,
the recording and :class:`ObservationGate` are conveniences on top.

**Not a fault injector.** Everything here conforms. A consumer that needs an
observer which *breaks* the contract on purpose — one citing an id it was never
handed, to drive the write path's unresolved-evidence refusal (ADR-0077 §5) — is
testing a reaction to a non-conforming producer and supplies its own stub for it;
this fake must stay the thing a conforming implementation is compared against.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Final, final

from ai_assistant.core.types import (
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    ObservationOutcome,
    PreferenceMemory,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import EpisodicMemory, MemoryRecord

#: The batch bound ADR-0077 §1 names, and the proposal bound §2 names. Repeated
#: here rather than imported from `learning`: a fake must not reach into a
#: subsystem (golden rule 1), and a consumer building the fake beside a real
#: observer wants the same numbers without either depending on the other.
DEFAULT_MAX_BATCH_SIZE: Final = 20
DEFAULT_MAX_PROPOSALS: Final = 5

#: This fake's confidence ladder. Its *values* are nothing the contract pins —
#: ADR-0077 §5 leaves them to each implementation — but its *shape* is: strictly
#: below 1.0, ``OBSERVED`` above ``INFERRED`` on equal support, non-decreasing in
#: support, under a ceiling, and a pure function of those two inputs alone.
_LADDER: Final[dict[MemorySource, tuple[float, float]]] = {
    MemorySource.OBSERVED: (0.5, 0.9),
    MemorySource.INFERRED: (0.3, 0.7),
}
_SUPPORT_INCREMENT: Final = 0.05

#: The epistemic steps an observer may take (ADR-0077 §2). ``USER_ASSERTED`` and
#: ``EXTERNAL`` are not steps this producer can take: it is neither the user nor
#: a connected source.
_STEPS: Final = frozenset({MemorySource.OBSERVED, MemorySource.INFERRED})

#: How many distinct supporting episodes each step needs before a belief may be
#: proposed at all (ADR-0077 §5). An ``INFERRED`` belief generalises beyond its
#: evidence, and a generalisation from one instance is the failure the floor
#: exists for.
_EVIDENCE_FLOOR: Final[dict[MemorySource, int]] = {
    MemorySource.OBSERVED: 1,
    MemorySource.INFERRED: 2,
}

_DEFAULT_INSTANT: Final = datetime(2026, 1, 1, tzinfo=UTC)


def _confidence(step: MemorySource, supports: int) -> float:
    """This fake's confidence for ``supports`` distinct episodes taken by ``step``.

    A pure function of exactly the two inputs ADR-0077 §5 allows — no clock, no
    randomness, nothing from a model — so re-observing the same episodes cannot
    inflate a belief through a ``REINFORCE`` that takes the maximum.
    """
    base, ceiling = _LADDER[step]
    return min(base + _SUPPORT_INCREMENT * (supports - 1), ceiling)


@final
@dataclass(frozen=True)
class ObservedBelief:
    """A belief for :class:`FakeObserver` to propose, minus its evidence.

    The evidence, the id and the confidence are the *producer's* to supply
    (ADR-0077 §5), so a consumer scripts everything else and the fake fills those
    three in from the batch it is handed. A template asking for more support than
    the batch can give is **discarded and counted**, exactly as a real producer
    discards an entry below its evidence floor — which is what lets a consumer
    drive a non-zero ``discarded_unusable`` without the fake ever emitting a
    proposal that breaks the contract.

    Attributes:
        content: The belief's canonical text rendering (ADR-0005 §1). Also the
            kind-specific field's value, so one string is all a consumer needs.
        kind: Which typed record to propose. ``EPISODIC`` is refused at
            construction — an observer distils evidence, it does not manufacture
            it (ADR-0077 §2).
        step: ``OBSERVED`` or ``INFERRED``; anything else is refused at
            construction.
        supports: How many **distinct** episodes from the batch to cite. Must be
            at least the step's floor (1 for ``OBSERVED``, 2 for ``INFERRED``).
        start: Which position in the batch the cited window begins at, so two
            templates can cite different episodes rather than all crowding onto
            the front of the batch. A window running off the end cites what is
            there, and falls below its floor — and is discarded — if that is not
            enough.
        record_id: A stable id for the proposed record, for a consumer asserting
            exactly what landed — or re-observing the same batch and expecting a
            ``REINFORCE`` at the same id. ``None`` derives one from the belief and
            the episodes it ends up citing.
        rationale: Why this belief is being proposed. Non-blank.
        steps: A ``PROCEDURAL`` record's steps; ignored for the other kinds.
    """

    content: str
    kind: MemoryKind = MemoryKind.SEMANTIC
    step: MemorySource = MemorySource.OBSERVED
    supports: int = 1
    start: int = 0
    record_id: str | None = None
    rationale: str = "fake observer: the batch supports this"
    steps: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        """Refuse a template the fake could only honour by breaking its contract.

        Raises:
            ValueError: If ``content`` or ``rationale`` is blank, ``kind`` is
                ``EPISODIC``, ``step`` is not an epistemic step an observer may
                take, ``supports`` is below the step's evidence floor, or
                ``start`` is negative. Each is a clause of the ``Observer``
                contract (or, for ``start``, a window that would silently cite the
                tail of the batch), so allowing it would only move the failure to
                ``observe`` time, far from the mistake.
        """
        if not self.content.strip():
            msg = "content must not be blank"
            raise ValueError(msg)
        if not self.rationale.strip():
            msg = "rationale must not be blank"
            raise ValueError(msg)
        if self.kind is MemoryKind.EPISODIC:
            msg = "an observer never proposes an EPISODIC record (ADR-0077 §2)"
            raise ValueError(msg)
        if self.step not in _STEPS:
            msg = f"step must be OBSERVED or INFERRED, got {self.step.name}"
            raise ValueError(msg)
        floor = _EVIDENCE_FLOOR[self.step]
        if self.supports < floor:
            msg = f"a {self.step.name} belief needs at least {floor} distinct supports"
            raise ValueError(msg)
        if self.start < 0:
            msg = f"start must not be negative, got {self.start}"
            raise ValueError(msg)


@final
class ObservationGate:
    """Holds one ``observe`` call at its first ``await``, and lets it go again.

    The two-lever shape ``ai_assistant.testing.cancellation.SuspendedCall``
    documents, in the position ADR-0065 §3 needs it: a conformance suite has to
    hold a call open *after* it has taken its one observation of the caller's
    batch, mutate that batch, and then release — a hook at method entry would let
    the mutation land before the observation, so a torn implementation would see
    one coherent mutated version and pass.

    Deliberately **not** ``LoopSuspension``'s run-to-completion shape: a
    cancellation delivered here escapes immediately, because ``observe`` acquires
    no resource that a cancellation could orphan, and a gate that deferred would
    model a stronger seam than the one it stands in for.
    """

    def __init__(self) -> None:
        """Create an unreached, unreleased gate."""
        self._reached = asyncio.Event()
        self._released = asyncio.Event()

    async def hold(self) -> None:
        """Announce arrival and suspend until released (or cancelled)."""
        self._reached.set()
        await self._released.wait()

    async def reached(self) -> None:
        """Wait until the held call has arrived at the gate.

        Raises:
            TimeoutError: If it never arrives, so a hung scenario fails here
                rather than somewhere upstream.
        """
        async with asyncio.timeout(5.0):
            await self._reached.wait()

    def release(self) -> None:
        """Let the held call finish; idempotent."""
        self._released.set()


class FakeObserver:
    """An ``Observer`` test double that distils scripted beliefs from real batches.

    Structurally implements :class:`~ai_assistant.core.protocols.Observer`. Every
    call is appended to :attr:`batches` and answered with the scripted beliefs —
    or, by default, with beliefs synthesised from the batch itself.

    The default script is chosen so that a suite running this fake exercises every
    clause rather than passing several of them vacuously: one ``OBSERVED`` belief
    per episode, plus — for a batch of two or more — one ``INFERRED`` belief over
    the first two. A batch of *n* therefore asks for more proposals than *n*,
    which is what makes the configured maximum bite.
    """

    def __init__(  # noqa: PLR0913 — two bounds, a script, a discard count, a gate and a clock; each is one knob a consumer sets on its own
        self,
        beliefs: Sequence[ObservedBelief] | None = None,
        *,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        max_proposals: int = DEFAULT_MAX_PROPOSALS,
        discarded_unusable: int = 0,
        gate: ObservationGate | None = None,
        now: datetime = _DEFAULT_INSTANT,
    ) -> None:
        """Create the fake observer.

        Args:
            beliefs: Proposed — after the evidence, id and confidence are filled
                in from the batch — for every call. ``None`` (the default)
                synthesises them from the batch instead; an *empty* sequence is
                the distinct, explicit "this observer proposes nothing", which a
                consumer needs for its no-op path.
            max_batch_size: The largest batch this observer accepts. A longer one
                is refused with ``ValueError``, never truncated (ADR-0077 §1).
            max_proposals: The most proposals one call may return. Usable beliefs
                beyond it are dropped and counted in ``discarded_over_limit``
                (ADR-0077 §2).
            discarded_unusable: Added to the count of beliefs this fake itself
                could not support, so a consumer can drive a non-zero degradation
                report without a model (the gap ADR-0022 §Consequences filed
                against ``FakeMemoryStore``). Ignored for an empty batch, which
                always yields the zero outcome.
            gate: Held at ``observe``'s first ``await``, after the batch has been
                observed once. ``None`` means ``observe`` never suspends.
            now: Stamped on every proposal's ``provenance.last_updated``. A plain
                instant rather than a ``Clock``: this fake computes nothing from
                the passage of time, and a callable would invite a test to make it
                do so.

        Raises:
            TypeError: If ``max_batch_size`` or ``max_proposals`` is not an
                ``int`` (``bool`` included).
            ValueError: If either bound is below 1, or ``discarded_unusable`` is
                negative. A zero batch bound observes nothing while reporting
                health; a zero proposal bound can never propose anything.
        """
        _check_bound("max_batch_size", max_batch_size)
        _check_bound("max_proposals", max_proposals)
        if discarded_unusable < 0:
            msg = f"discarded_unusable must not be negative, got {discarded_unusable}"
            raise ValueError(msg)
        self._beliefs = None if beliefs is None else tuple(beliefs)
        self._max_batch_size = max_batch_size
        self._max_proposals = max_proposals
        self._extra_unusable = discarded_unusable
        self._gate = gate
        self._now = now
        self.batches: list[tuple[EpisodicMemory, ...]] = []

    @property
    def max_batch_size(self) -> int:
        """The largest batch this observer accepts."""
        return self._max_batch_size

    @property
    def max_proposals(self) -> int:
        """The most proposals one ``observe`` call may return."""
        return self._max_proposals

    @property
    def call_count(self) -> int:
        """How many times ``observe`` has been called."""
        return len(self.batches)

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose the scripted or synthesised beliefs the batch can support.

        The batch is snapshotted on this coroutine's first executed line, before
        any ``await`` (ADR-0065). A shallow tuple is a *complete* snapshot here:
        the container is the caller's and mutable, while every
        :class:`~ai_assistant.core.types.EpisodicMemory` in it is frozen
        (ADR-0068), so nothing reachable through it can change underneath.

        Args:
            episodes: The batch to observe.

        Returns:
            The proposals, and what was thrown away getting there.

        Raises:
            ValueError: If ``episodes`` exceeds :attr:`max_batch_size` or repeats
                an episode id (ADR-0077 §1).
        """
        batch = tuple(episodes)
        if len(batch) > self._max_batch_size:
            msg = (
                f"batch of {len(batch)} episodes exceeds the configured maximum "
                f"of {self._max_batch_size}; it is refused, never truncated"
            )
            raise ValueError(msg)
        ids = [episode.id for episode in batch]
        if len(set(ids)) != len(ids):
            msg = (
                "a batch is a set: an episode appears in it at most once, and a "
                "repeat would let one observation supply two distinct supports"
            )
            raise ValueError(msg)
        self.batches.append(batch)

        if self._gate is not None:
            await self._gate.hold()

        if not batch:
            # An empty batch yields no proposals and no discards, whatever this
            # instance was scripted with: there is nothing to have thrown away.
            return ObservationOutcome()

        templates = self._beliefs if self._beliefs is not None else _synthesise(batch)
        usable: list[MemoryUpdateProposal] = []
        unusable = self._extra_unusable
        for template in templates:
            proposal = self._to_proposal(template, batch)
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
        self, template: ObservedBelief, batch: Sequence[EpisodicMemory]
    ) -> MemoryUpdateProposal | None:
        """Build one proposal, or ``None`` where the batch cannot support it.

        The citations are drawn from the batch in order — the producer's ids,
        never a model's (ADR-0077 §5) — and a template wanting more support than
        the batch holds falls below its step's evidence floor and is discarded
        rather than repaired by attaching what is there.
        """
        window = batch[template.start : template.start + template.supports]
        cited = tuple(episode.id for episode in window)
        if len(cited) < _EVIDENCE_FLOOR[template.step]:
            return None
        provenance = Provenance(
            source=template.step,
            confidence=_confidence(template.step, len(cited)),
            evidence=cited,
            last_updated=self._now,
        )
        return MemoryUpdateProposal(
            proposed=_record(template, provenance, _identify(template, cited)),
            rationale=template.rationale,
        )


def _check_bound(name: str, value: int) -> None:
    """Refuse a non-positive or non-integral bound at construction.

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


def _synthesise(batch: Sequence[EpisodicMemory]) -> tuple[ObservedBelief, ...]:
    """The default script: one ``OBSERVED`` belief per episode, plus one ``INFERRED``.

    Both steps appear whenever the batch can support them, so a suite running this
    fake exercises the ``INFERRED``-needs-two clause rather than passing it
    vacuously — and asks for ``len(batch) + 1`` proposals, so a configured maximum
    at or below the batch size actually bites.
    """
    beliefs = [
        ObservedBelief(content=f"fake observation of {episode.id}", start=index)
        for index, episode in enumerate(batch)
    ]
    if len(batch) >= _EVIDENCE_FLOOR[MemorySource.INFERRED]:
        beliefs.append(
            ObservedBelief(
                content="fake inference across the batch",
                step=MemorySource.INFERRED,
                supports=2,
            )
        )
    return tuple(beliefs)


def _identify(template: ObservedBelief, cited: Sequence[str]) -> str:
    """A stable id for the record ``template`` proposes over ``cited``.

    Derived from what is being believed and what supports it rather than from a
    counter, so it is deterministic without depending on execution order and
    identical across instances — two fakes writing into one store cannot silently
    overwrite each other, and re-observing one batch proposes the *same* record id
    twice, which is what a consumer testing a ``REINFORCE`` fold needs.
    """
    if template.record_id is not None:
        return template.record_id
    material = "\x00".join([template.content, template.kind.value, template.step.value, *cited])
    return f"fake-observed-{sha256(material.encode()).hexdigest()[:16]}"


def _record(template: ObservedBelief, provenance: Provenance, record_id: str) -> MemoryRecord:
    """Build the typed record ``template`` names.

    ``EPISODIC`` is unreachable: :class:`ObservedBelief` refuses it at
    construction, which is why this match has three arms and no fourth.
    """
    match template.kind:
        case MemoryKind.PREFERENCE:
            return PreferenceMemory(
                id=record_id,
                content=template.content,
                provenance=provenance,
                preference=template.content,
            )
        case MemoryKind.PROCEDURAL:
            return ProceduralMemory(
                id=record_id,
                content=template.content,
                provenance=provenance,
                situation=template.content,
                steps=template.steps,
            )
        case _:
            return SemanticMemory(
                id=record_id,
                content=template.content,
                provenance=provenance,
                fact=template.content,
            )


__all__ = [
    "DEFAULT_MAX_BATCH_SIZE",
    "DEFAULT_MAX_PROPOSALS",
    "FakeObserver",
    "ObservationGate",
    "ObservedBelief",
]

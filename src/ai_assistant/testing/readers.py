"""A canonical :class:`~ai_assistant.core.protocols.Reader` fake (ADR-0093 §10).

The shared test double for the ``Reader`` contract, so a subsystem that drives a
read — `orchestration`'s ingestion stage, and later `context`'s facet adapter —
can exercise every branch of its own pipeline without a source on disk and
without importing a concrete reader (``CLAUDE.md`` golden rule 1; ADR-0093 §2
forbids importing ``ai_assistant.readers`` from a subsystem outright).

It is scriptable to the **three states ADR-0093 §8 distinguishes**, which is what
a consumer needs to test its own degradation path:

* a reading **with proposals** — the source had something to say;
* an **empty** reading — a success, and emphatically not a failure signal;
* a read that **raises** :class:`~ai_assistant.core.errors.ReaderError` — the
  source could not be read at all.

That third capability is the gap ADR-0022 §Consequences filed against
``FakeMemoryStore`` as #105, not repeated here.

**And a fourth, which is what makes the cancellation clause testable at all.**
The fake wraps its read in :class:`~ai_assistant.testing.cancellation.\
SuspendableResource`, so a suite can arm :meth:`FakeReader.suspend_next` and
cancel a ``read()`` that has *demonstrably* arrived at an await. Without it the
clause passes vacuously: a fake that completes immediately can only be cancelled
before it starts, which exercises none of the code an implementation would use to
catch a ``CancelledError`` during source I/O and convert it — and that conversion
is the exact failure the clause exists to forbid, so a test that cannot reach it
is worse than no test, because it reports the property as held (ADR-0093 §10).

**Not a fault injector.** Everything here conforms. A consumer that needs a
reader which *breaks* the contract on purpose — one proposing an episode, or a
belief outside the ``ATTESTED`` band, to drive some caller's refusal — is testing
a reaction to a non-conforming producer and supplies its own stub for it. This
fake must stay the thing a conforming implementation is compared against, so a
script it could only honour by violating its own contract is refused at
construction (``FakeObserver`` and ``FakeFeedbackProcessor`` make the same trade).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, final

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    DataTier,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
    SourceReading,
    band_of,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: The identity this fake declares unless a test names another. Tier 2 and says
#: what the producer *is*, never what its source holds (ADR-0093 §7).
DEFAULT_READER_NAME: Final = "fake-source"

#: When this fake pretends it read — **our** clock (ADR-0093 §10).
_DEFAULT_READ_AT: Final = datetime(2026, 1, 2, tzinfo=UTC)

#: When the scripted source pretends it spoke — **its** clock, and deliberately
#: earlier than the read: "Monday's report, revised into the store on Tuesday" is
#: the normal case rather than an anomaly (ADR-0092 §3).
_DEFAULT_REPORTED_AT: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: What a connected source's report is worth. Below 1.0 — nothing forces that in
#: the ``ATTESTED`` band, since a source may legitimately report a fact it is
#: certain of (ADR-0038 §2a), but a third party's claim about the user is not the
#: user's own word, and 0.9 is what the corpus's other attested fixtures use.
_ATTESTED_CONFIDENCE: Final = 0.9


def attested_proposal(
    content: str,
    *,
    reported_by: str,
    record_id: str | None = None,
    reported_at: datetime = _DEFAULT_REPORTED_AT,
    last_updated: datetime = _DEFAULT_READ_AT,
) -> MemoryUpdateProposal:
    """One well-formed proposal of the shape a ``Reader`` may emit.

    Exported rather than private, for :func:`~ai_assistant.testing.\
    observation.episode`'s reason: a consumer scripting :class:`FakeReader`, and a
    concrete reader's own tests, must not have to re-derive what an attested
    proposal looks like — four decisions have to line up at once, and since
    ADR-0092 §1 three of them are *unconstructable* if they do not.

    ``EXTERNAL`` provenance is the ``ATTESTED`` band (ADR-0072 §2), and since
    ADR-0092 §1 an ``EXTERNAL`` :class:`~ai_assistant.core.types.Provenance`
    without an :class:`~ai_assistant.core.types.Attestation` cannot be constructed
    at all — so every fixture a ``Reader`` suite builds carries one. The record is
    a :class:`~ai_assistant.core.types.SemanticMemory`: a reader reports what a
    source says, and an ``EpisodicMemory`` is the one kind it may never propose
    (ADR-0093 §4).

    Args:
        content: The belief's canonical text rendering, and the fact itself.
        reported_by: The source instance that reported it — the producing reader's
            declared identity (ADR-0093 §7). Tier 2, and never a path.
        record_id: A stable id for the record. ``None`` derives one from
            ``reported_by`` and ``content``, so two calls with the same belief mint
            the same id and a consumer can test a fold. **Minted by us and never
            the source's own key**, whether directly or namespaced (ADR-0092 §6).
        reported_at: When the source asserts the fact was current, on **its** clock.
        last_updated: When *we* last revised the belief — transaction time, our
            clock (ADR-0045 §3).

    The ``rationale`` and the ``sensitivity`` are set rather than parameterised,
    because ADR-0093 §4 obliges a reader to make both a choice: the rationale
    **names the source**, and the tier is stated explicitly —
    ``MemoryUpdateProposal.sensitivity`` defaults to ``PERSONAL``, which is right
    for a calendar and must not be *assumed* right for the next source. A caller
    that needs different values for either builds the proposal itself; the point
    of this helper is the four decisions that must line up, not a knob for each
    field.

    Returns:
        The proposal, ready to script or to assert against.

    Raises:
        ValueError: If ``content`` or ``reported_by`` is blank. Neither is
            rejected where it lands — ``reported_by`` is an
            :data:`~ai_assistant.core.types.Identifier` and would be, but blank
            ``content`` would sail through — and both would surface far from the
            mistake.
    """
    if not content.strip():
        msg = "content must not be blank"
        raise ValueError(msg)
    if not reported_by.strip():
        msg = "reported_by must not be blank"
        raise ValueError(msg)
    return MemoryUpdateProposal(
        proposed=SemanticMemory(
            id=record_id if record_id is not None else f"{reported_by}:{content}",
            content=content,
            fact=content,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                last_updated=last_updated,
                attestation=Attestation(reported_by=reported_by, reported_at=reported_at),
            ),
        ),
        rationale=f"{reported_by} reported it",
        # Stated, never defaulted: a producer that defaults its way past this
        # classification is the failure ADR-0004 §1's tiering exists to prevent.
        sensitivity=DataTier.PERSONAL,
    )


@final
class FakeReader:
    """A ``Reader`` test double returning a scripted reading, or raising.

    Structurally implements :class:`~ai_assistant.core.protocols.Reader`. The
    reading is built **at construction**, so a script this fake could only honour
    by breaking its own contract fails where it was written rather than at
    ``read()`` time — and so does a naive instant, which
    :data:`~ai_assistant.core.types.UtcInstant` refuses.

    Beyond the contract it counts its calls and exposes its suspension gate;
    neither is contract. Only the behaviour pinned by the shared ``Reader``
    conformance suite is.
    """

    def __init__(
        self,
        proposals: Sequence[MemoryUpdateProposal] | None = None,
        *,
        name: str = DEFAULT_READER_NAME,
        read_at: datetime = _DEFAULT_READ_AT,
        as_of: datetime | None = None,
        failure: Exception | None = None,
    ) -> None:
        """Create the fake reader.

        Args:
            proposals: Returned verbatim by every read. ``None`` (the default)
                synthesises one proposal instead; an *empty* sequence is the
                distinct, explicit "this source had nothing to propose", which is a
                **successful** reading a consumer needs to exercise (ADR-0093 §8).
            name: The identity this reader declares, and therefore the reading's
                ``source``.
            read_at: The instant this fake pretends it acquired the source's bytes
                — our clock, always present because it is always knowable.
            as_of: A reading-wide instant the *source* declares, or ``None`` where
                it declares none. ``None`` is the first real source's case and is a
                ruling rather than laxity: it may never be filled from the
                filesystem, from the clock, or from one entry's stamp applied to
                the rest (ADR-0093 §10).
            failure: The **source-level** failure to model. When given, every read
                raises :class:`~ai_assistant.core.errors.ReaderError` from it —
                with a payload-free message carrying only this reader's identity
                and the cause's class, which is the whole of what ADR-0093 §8
                permits a message to say.

        Raises:
            ValueError: If ``name`` is blank, or any scripted proposal is outside
                the ``ATTESTED`` band or is an ``EpisodicMemory``. Each is a clause
                of the ``Reader`` contract, so allowing it would only move the
                failure to ``read()`` time, far from the mistake — and the
                canonical fake must not be configurable into breaking its own
                contract.
        """
        if not name.strip():
            msg = "a reader's declared identity must not be blank (ADR-0093 §7)"
            raise ValueError(msg)
        scripted = _synthesise(name, read_at) if proposals is None else tuple(proposals)
        for index, proposal in enumerate(scripted):
            _refuse_unconformable(index, proposal)
        self._name = name
        self._failure = failure
        self._resource = SuspendableResource()
        self._calls = 0
        # Built eagerly, and returned as-is by every read: `SourceReading` is
        # frozen and so is everything reachable through it (ADR-0068), so there is
        # nothing a caller could mutate and no copy worth paying for.
        self._reading = SourceReading(
            source=name,
            read_at=read_at,
            as_of=as_of,
            proposals=scripted,
        )

    @property
    def name(self) -> str:
        """This reader's declared identity — stable, and the reading's ``source``."""
        return self._name

    @property
    def call_count(self) -> int:
        """How many times :meth:`read` has been called."""
        return self._calls

    @property
    def log(self) -> ResourceLog:
        """When each read was inside the modelled source (ADR-0060's case reads it)."""
        return self._resource.log

    def suspend_next(self) -> LoopSuspension:
        """Arm the next :meth:`read` to suspend inside the source it is reading.

        The fourth capability ADR-0093 §10 requires of this fake, and the reason
        the cancellation clause is not vacuous: the handle's ``reached`` and
        ``release`` are :mod:`ai_assistant.testing.cancellation`'s, so a suite can
        wait until a read has demonstrably arrived at an await, cancel it *there*,
        and see what comes back.

        Returns:
            The handle the suite waits on and releases.

        Raises:
            RuntimeError: If a suspension is already armed (see
                :meth:`~ai_assistant.testing.cancellation.SuspendableResource.suspend_next`).
        """
        return self._resource.suspend_next()

    async def read(self) -> SourceReading:
        """Return the scripted reading, or raise the scripted failure.

        Takes no arguments, as the contract does: a caller able to widen the read
        is a caller able to defeat the bound (ADR-0093 §10).

        Returns:
            The reading fixed at construction. Frozen all the way down, so two
            callers share it safely.

        Raises:
            ReaderError: If this fake was constructed with a ``failure``, wrapping
                it as ``__cause__`` under a payload-free message.
            CancelledError: Re-raised unchanged if the call is cancelled while
                suspended on an armed gate — **never** converted into a
                ``ReaderError``, which is the clause the gate exists to test
                (ADR-0093 §8).
        """
        self._calls += 1
        async with self._resource.held():
            if self._failure is not None:
                # Identity and the cause's class, and nothing else: the path, the
                # file's contents and the cause's own message are all payload
                # ADR-0004 §5 forbids in a log (ADR-0093 §8).
                msg = f"{self._name}: {type(self._failure).__name__}"
                raise ReaderError(msg) from self._failure
            return self._reading


def _synthesise(name: str, read_at: datetime) -> tuple[MemoryUpdateProposal, ...]:
    """The default script: one attested belief, so no clause passes vacuously.

    A suite running this fake asserts over ``reading.proposals``, and every one of
    those clauses — not ``EPISODIC``, in the ``ATTESTED`` band — is empty on an
    empty tuple. The default therefore proposes something, and the *empty* reading
    is the state a consumer asks for explicitly.
    """
    return (
        attested_proposal(
            f"{name} reported one thing",
            reported_by=name,
            last_updated=read_at,
        ),
    )


def _refuse_unconformable(index: int, proposal: MemoryUpdateProposal) -> None:
    """Refuse a scripted proposal no conforming reader could have emitted.

    Raises:
        ValueError: If the proposal is an ``EpisodicMemory`` (ADR-0093 §4) or its
            provenance is outside the ``ATTESTED`` band (ADR-0093 §4, ADR-0072 §2).
    """
    if proposal.proposed.kind == MemoryKind.EPISODIC.value:
        msg = (
            f"proposals[{index}]: a reader never proposes an EpisodicMemory — it has "
            f"neither a gate it can survive nor an exemption it can claim (ADR-0093 §4)"
        )
        raise ValueError(msg)
    band = band_of(proposal.proposed.provenance.source)
    if band is not BeliefBand.ATTESTED:
        msg = (
            f"proposals[{index}]: a reader proposes in the ATTESTED band, not "
            f"{band.name} — what it reports is a third party's claim (ADR-0093 §4)"
        )
        raise ValueError(msg)


__all__ = [
    "DEFAULT_READER_NAME",
    "FakeReader",
    "attested_proposal",
]

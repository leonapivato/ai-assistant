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
from uuid import uuid4

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    CalendarFacet,
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
    from collections.abc import Callable, Sequence

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


def _mint(factory: Callable[[], str] | None = None) -> str:
    """Mint one opaque record id, guarded at its output (ADR-0092 §6, ADR-0045 §4).

    **Opaque, and re-minted per proposal rather than derived.** ADR-0092 §6 rules
    that an ``EXTERNAL`` producer "proposes each record at an id it mints, opaque to
    the source", and ADR-0081 §8 — which §6 quotes to say it is declining to pull
    that trigger — names the alternative it forbids: "a producer that *derives* a
    record id from content rather than minting one — **a content hash**, or an
    external system's key adopted as the id". A derived id is an *address*, aimed
    at the same record on every re-read, deterministically; "minting removes the
    aim", and with it the ADR-0038 §2a resurrection where a re-sync recomputes a
    retired record's id and overwrites its closed validity window through
    ``ACCEPT``'s blind upsert.

    That is why this fake breaks with ``FakeObserver``'s and
    ``FakeFeedbackProcessor``'s deterministic content-derived ids rather than
    copying them. Those producers are inside the class ADR-0081 §8's deferral
    assumes safe; the first ``EXTERNAL`` producer is exactly the one §6 rules on. A
    test that needs a stable id supplies one — a caller *choosing* an id is not a
    producer *deriving* one.

    **Idempotency does not vanish; it moves** (ADR-0092 §6). An unchanged re-read
    proposes the same content, ``_detect_conflicts`` ranks the identical live
    record top, and ``DefaultMemoryPolicy`` rules ``REINFORCE``, which folds at the
    **target's** id. One record, updated in place, reached through the ordinary
    write path rather than through a key the producer asserts.

    Args:
        factory: Supplies the id, for a test that wants to name them. ``None``
            mints a ``uuid4``.

    Returns:
        The minted id.

    Raises:
        ValueError: If the factory returns anything that is not a non-blank
            built-in ``str``. ADR-0092 §6 owes exactly this — "the producer's id
            factory is **guarded at its output**" — so a malformed mint fails
            loudly instead of becoming a key.
    """
    minted = factory() if factory is not None else f"reader-{uuid4().hex}"
    # The guard ``FakeMemoryWriter._checked_id`` uses, for its reasons. An
    # **exact** ``str`` is required rather than an ``isinstance`` one: a hostile
    # subclass — one whose ``strip`` or ``__hash__`` raises — passes ``isinstance``
    # and then leaks an arbitrary exception across the seam as a store key. And
    # nothing about the returned object is introspected in the message (not
    # ``repr``, not ``type(...).__name__``), because a hostile ``__repr__`` could
    # raise past the guard; ``type(minted) is not str`` invokes no user code.
    if type(minted) is not str or not minted.strip():
        msg = (
            "the id factory did not return a non-blank built-in str; "
            "a malformed mint must not become a key (ADR-0092 §6)"
        )
        raise ValueError(msg)
    return minted


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
            declared identity (ADR-0093 §7). Tier 2, and never a path. It **must
            equal the ``name`` of the** :class:`FakeReader` **this is scripted
            into**, which that constructor refuses otherwise: the identity reaching
            :attr:`~ai_assistant.core.types.Attestation.reported_by` is the
            producer's own (ADR-0093 §10), and ADR-0092 §6 mints our own ids, so it
            is the only durable handle the stored record keeps on where it came
            from. The two are one value until ADR-0093 §11's registry deferral
            fires and ``reported_by`` becomes instance-distinguishing.
        record_id: A stable id, for a test that wants to name the record it is
            asserting on. ``None`` **mints an opaque one** (see :func:`_mint`):
            never the source's own key, and never derived from the content either,
            so two calls with the same belief do not aim at one address. A caller
            *choosing* an id here is not a producer *deriving* one, which is what
            ADR-0092 §6 rules on.
        reported_at: When the source asserts the fact was current, on **its**
            clock. It lands in ``last_confirmed_at`` as well as in the
            ``Attestation``, because the ``ATTESTED`` band's confirming event *is*
            the source's report and never our ingestion of it (ADR-0103 §9,
            ADR-0109 §4). Written as it stands — a value in our future is stored
            unchanged (ADR-0092 §3) — which is what makes this fake follow the
            concrete calendar reader rather than diverge from it.
        last_updated: When *we* last revised the belief — transaction time, our
            clock (ADR-0045 §3). Deliberately **not** the confirming instant: a
            months-old report imported this morning is not a fresh belief.

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
            id=record_id if record_id is not None else _mint(),
            content=content,
            fact=content,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=_ATTESTED_CONFIDENCE,
                last_updated=last_updated,
                attestation=Attestation(reported_by=reported_by, reported_at=reported_at),
                last_confirmed_at=reported_at,
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

    Structurally implements :class:`~ai_assistant.core.protocols.Reader`. A
    *scripted* reading is validated and built **at construction**, so a script this
    fake could only honour by breaking its own contract fails where it was written
    rather than at ``read()`` time — and so does a naive instant, which
    :data:`~ai_assistant.core.types.UtcInstant` refuses.

    **The default script is re-synthesised on every read, and that is ADR-0092 §6
    rather than an implementation detail.** A real reader re-reads its source and
    **mints a fresh id for every record it proposes**; a fake that handed back one
    fixed reading would model a producer whose re-read aims at the ids it proposed
    last time, which is the address §6 exists to remove (see :func:`_mint`). A
    consumer testing "the second read duplicated rather than folded" needs the
    conformant behaviour, not a convenient one. A *scripted* reading is returned
    verbatim, ids included: those ids are the test author's choice, not a
    derivation this fake performed.

    Beyond the contract it counts its calls and exposes its suspension gate;
    neither is contract. Only the behaviour pinned by the shared ``Reader``
    conformance suite is.
    """

    def __init__(  # noqa: PLR0913 — a script, an identity, two instants, a facet, a failure and an id factory; each is one knob a consumer sets on its own
        self,
        proposals: Sequence[MemoryUpdateProposal] | None = None,
        *,
        name: str = DEFAULT_READER_NAME,
        read_at: datetime = _DEFAULT_READ_AT,
        as_of: datetime | None = None,
        facet: CalendarFacet | None = None,
        failure: Exception | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create the fake reader.

        Args:
            proposals: Returned verbatim by every read, ids included. ``None`` (the
                default) synthesises one proposal **per read** instead; an *empty*
                sequence is the distinct, explicit "this source had nothing to
                propose", which is a **successful** reading a consumer needs to
                exercise (ADR-0093 §8).
            name: The identity this reader declares, and therefore the reading's
                ``source`` and every proposal's ``reported_by``. A parameter here
                and a **declared constant** on a real reader (ADR-0093 §7) — a fake
                whose identity were hard-coded could not stand in for two readers
                at once, which is what a consumer testing "the right identity
                reached the right belief" needs it for. That it is Tier 2 stays a
                *test author's* obligation, and deliberately not a validator: §7
                rules that "no validator can tell a chosen label from a personal
                one", which is why it makes a real reader's identity declared
                rather than configured instead of trying to check it. So name the
                producer (``"calendar"``), never its source's location or the data
                it holds (``"alice@example.com calendar"``). Nothing production
                reads it — ``lint-imports`` keeps ``ai_assistant.testing`` out of
                every shipping package — so the blast radius is one test's output.
            read_at: The instant this fake pretends it acquired the source's bytes
                — our clock, always present because it is always knowable.
            as_of: A reading-wide instant the *source* declares, or ``None`` where
                it declares none. ``None`` is the first real source's case and is a
                ruling rather than laxity: it may never be filled from the
                filesystem, from the clock, or from one entry's stamp applied to
                the rest (ADR-0093 §10).
            facet: The situational half of every reading this fake returns, or
                ``None`` — the default, and the state a consumer of a reader whose
                source has no situational reading sees (ADR-0096 §5). Its stamp
                must be this fake's own: :class:`SourceReading`'s validator refuses
                a facet naming a different source or carrying different instants,
                which is what makes a mis-stamped script fail *here* rather than at
                the consumer that lifted it into ``CurrentContext``.
            failure: The **source-level** failure to model. When given, every read
                raises :class:`~ai_assistant.core.errors.ReaderError` from it —
                with a payload-free message carrying only this reader's identity
                and the cause's class, which is the whole of what ADR-0093 §8
                permits a message to say.
            id_factory: Supplies the ids of *synthesised* proposals, for a test
                that wants to name them. ``None`` mints a ``uuid4`` each time. It
                is guarded at its output, which is the discipline ADR-0092 §6 owes
                a minted id: a blank mint fails rather than becoming a key.

        Raises:
            ValueError: If ``name`` is blank, if ``facet``'s stamp is not the one
                this fake's readings carry (a ``ValidationError``, which is a
                ``ValueError``), or if any scripted proposal is an
                ``EpisodicMemory``, is outside the ``ATTESTED`` band, is attested
                to a source other than ``name``, or carries no rationale. Each is a
                clause of the ``Reader`` contract, so allowing it would only move
                the failure to ``read()`` time — or, for the attribution, to a
                stored belief attributed to a reader that never reported it — far
                from the mistake. The canonical fake must not be configurable into
                failing its own conformance suite.
        """
        if not name.strip():
            msg = "a reader's declared identity must not be blank (ADR-0093 §7)"
            raise ValueError(msg)
        # Canonicalised the way `Identifier` canonicalises `Attestation.
        # reported_by`, so `SourceReading.source` and every proposal's reporter
        # cannot disagree by a space. `source` is `EncodableText`, which does not
        # strip, and `reported_by` is `Identifier`, which does — so `" calendar "`
        # would otherwise produce a reading attributed to `"calendar"` by a
        # producer calling itself `" calendar "`, failing the suite's attribution
        # clause on a difference no author would see.
        self._name = name.strip()
        self._read_at = read_at
        self._as_of = as_of
        self._facet = facet
        self._failure = failure
        self._id_factory = id_factory
        self._resource = SuspendableResource()
        self._calls = 0
        self._scripted = None if proposals is None else tuple(proposals)
        # Built eagerly whether or not it is the one `read` returns: constructing
        # it is what refuses a naive instant, and validates a script, *here* rather
        # than at read time. For a scripted reading it *is* what `read` returns —
        # `SourceReading` is frozen and so is everything reachable through it
        # (ADR-0068), so there is nothing a caller could mutate and no copy worth
        # paying for.
        self._scripted_reading = self._build(self._scripted or ())

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

    def _build(self, proposals: tuple[MemoryUpdateProposal, ...]) -> SourceReading:
        """One validated reading over ``proposals``, with this reader's identity.

        Every reading goes through here — scripted at construction, synthesised per
        read — so the refusals below cannot be true of one path and not the other.
        Validating only the constructor's argument is how a synthesised proposal
        drifted out from under them once already.

        Raises:
            ValueError: If any proposal is one no conforming reader could have
                emitted (see :func:`_refuse_unconformable`).
        """
        for index, proposal in enumerate(proposals):
            _refuse_unconformable(index, self._name, proposal)
        return SourceReading(
            source=self._name,
            read_at=self._read_at,
            as_of=self._as_of,
            proposals=proposals,
            # Carried on every reading this fake builds, scripted or synthesised,
            # so the two paths cannot disagree about the field a consumer reads.
            # A facet whose stamp is not this reading's is refused here, at
            # construction, by `SourceReading`'s own validator (ADR-0096 §5).
            facet=self._facet,
        )

    async def read(self) -> SourceReading:
        """Return a reading, or raise the scripted failure.

        Takes no arguments, as the contract does: a caller able to widen the read
        is a caller able to defeat the bound (ADR-0093 §10).

        Returns:
            The scripted reading, fixed at construction; or, on the default script,
            a fresh reading whose proposal carries a **newly minted id** — the
            behaviour ADR-0092 §6 requires of a re-read. Frozen all the way down
            either way, so two callers share one safely.

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
            if self._scripted is not None:
                return self._scripted_reading
            return self._build(_synthesise(self._name, self._read_at, self._id_factory))


def _synthesise(
    name: str, read_at: datetime, id_factory: Callable[[], str] | None = None
) -> tuple[MemoryUpdateProposal, ...]:
    """The default script: one attested belief, so no clause passes vacuously.

    A suite running this fake asserts over ``reading.proposals``, and every one of
    those clauses — not ``EPISODIC``, in the ``ATTESTED`` band, attributed to the
    producer, carrying a rationale — is empty on an empty tuple. The default
    therefore proposes something, and the *empty* reading is the state a consumer
    asks for explicitly.

    Called **per read**, so each pass mints its own id (:func:`_mint`).
    """
    return (
        attested_proposal(
            f"{name} reported one thing",
            reported_by=name,
            record_id=_mint(id_factory),
            last_updated=read_at,
        ),
    )


def _refuse_unconformable(index: int, name: str, proposal: MemoryUpdateProposal) -> None:
    """Refuse a scripted proposal no conforming reader could have emitted.

    **What is checked, and the one half of ADR-0093 §4 that is not.** §4 obliges a
    reader's proposals to "carry a ``rationale`` naming the source, and a
    ``sensitivity`` chosen for what the source holds rather than defaulted". The
    *carrying* is checked below, as ``FeedbackProcessorContract`` checks it for the
    sibling producer. **Naming** is not, and neither is *chosen*: a substring test
    for the identity would both over- and under-fire — ``"your work calendar said
    so"`` names the source without containing ``calendar:work``, while
    ``"scheduled calendar import"`` contains it and names a mechanism — and no
    check can distinguish a deliberate ``PERSONAL`` from a defaulted one at all.
    Both stay producer obligations stated in ``Reader.read``'s contract, on the
    reasoning ADR-0093 §7 uses for the identity itself: a proxy that reports the
    property as held is worse than none, because it is believed.

    Raises:
        ValueError: If the proposal is an ``EpisodicMemory`` (ADR-0093 §4), its
            provenance is outside the ``ATTESTED`` band (ADR-0093 §4, ADR-0072 §2),
            its attestation names a source other than ``name`` (ADR-0093 §10), or
            it carries no rationale at all (ADR-0093 §4).
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
    if not proposal.rationale.strip():
        msg = (
            f"proposals[{index}]: a reader's proposal carries a rationale naming the "
            f"source (ADR-0093 §4); a blank one is what the user is shown when they "
            f"ask why a belief is held"
        )
        raise ValueError(msg)
    attestation = proposal.proposed.provenance.attestation
    # Unreachable while the band above holds: ADR-0092 §1's iff makes an ATTESTED
    # provenance without an attestation unconstructable. Read rather than asserted
    # so this stays a check and not a narrowing `assert` the gate would strip.
    if attestation is not None and attestation.reported_by != name:
        msg = (
            f"proposals[{index}]: attested to {attestation.reported_by!r} but produced by "
            f"{name!r} — the identity that reaches Attestation.reported_by is the "
            f"producer's own (ADR-0093 §10), and ADR-0092 §6 leaves it the only durable "
            f"handle the stored record keeps on where it came from"
        )
        raise ValueError(msg)


__all__ = [
    "DEFAULT_READER_NAME",
    "FakeReader",
    "attested_proposal",
]

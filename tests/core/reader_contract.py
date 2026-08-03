"""Shared conformance suite for the Reader Protocol (ADR-0093 §10, ADR-0095).

Every ``Reader`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`ReaderContract`, supplies
the three subject fixtures — a reader with something to report, one with nothing,
and one whose source cannot be read — and overrides
:meth:`ReaderContract.gated_read`.

**Here rather than under ``tests/readers/``.** The corpus puts a suite beside the
subsystem that implements it, and ``ai_assistant/readers/`` does not exist yet:
ADR-0093 §10's closing paragraph puts the concrete ``.ics`` reader in a later lane
and ADR-0093 §2's ``lint-imports`` contract with it. Everything this lane ships
lives in ``core`` and in ``ai_assistant.testing``, which is also where ADR-0095 §3
insists the seam's weight stays, so the suite lives beside the Protocol it
encodes. A later reader's tests import it across directories exactly as
``tests/wire/test_client_contract.py`` imports ``assistant_engine_contract``
today.

**What is in here, and what deliberately is not.** The suite encodes the clauses
that bind *every* reader — the ones expressible without a source, i.e. decidable
from ``name`` and one ``read()`` return value, which is the whole of what a
conforming ``Reader`` is. ADR-0093 §10 names four rulings that are **not** suite
clauses, and it names them there so a reader of this file does not mistake their
absence from the suite for absence from the contract:

* **§5's bound, refused at construction.** ``Reader`` specifies no constructor and
  no configuration surface — ``read()`` takes no arguments precisely so a caller
  cannot widen the bound — so a generic suite has nothing to over-supply. This is
  where the shape differs from ``ObserverContract``, whose equivalent clause is
  testable only because ``observe`` *takes* the batch whose size the bound
  governs. It is a concrete reader's test and a ``Settings`` test.
* **That a *real* source failure is what raises.** A suite cannot make an
  arbitrary implementation's source fail, so it pins the *type* (below) but not
  that the type is reached from a missing, unreadable or malformed source. Those
  three cases are the concrete reader's, and ADR-0093 §10 names all three so its
  lane writes each rather than the one easiest to provoke. §8's two neighbouring
  obligations on that raise — that ``__cause__`` survives, and that the message is
  payload-free — are unreachable generically for their own reasons and are the
  same lane's; :meth:`ReaderContract.failing_reader` states both, and **#648**
  tracks all three so a docstring is not the only thing holding them.
* **§4's "never proposes an absence."** A statement about what a producer declines
  to emit; nothing in a return value exhibits it.
* **§3's "neither consumer derives its answer from the other's reading."** A
  statement about how a *caller* wires two paths.

One further omission is this lane's judgement rather than ADR-0093 §10's ruling,
and is recorded so it reads as a decision. ADR-0060's **resource** clause — a
second caller must not reach the resource while a cancelled first call's work is
still using it — is not asserted generically here. ADR-0093 §10 enumerates the
cancellation obligation this seam owes and lists only the propagation half, and a
generic suite has no handle on an arbitrary reader's file descriptor; asserting it
would mean obliging every concrete reader to expose a ``SuspendedMidWrite``-style
hook that no ratified clause asks for. The canonical fake models the resource
anyway, and ``tests/core/test_fake_reader.py`` asserts non-overlap on it.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.protocols import Reader
from ai_assistant.core.types import BeliefBand, MemoryKind, band_of

if TYPE_CHECKING:
    from ai_assistant.core.types import SourceReading
    from ai_assistant.testing.cancellation import SuspendedCall

#: What a failure of the cancellation case means, in one place (ADR-0093 §8). It
#: is the one place a conforming-looking reader satisfies every other clause in
#: this file and still absorbs a cancellation: the facet would degrade and the
#: scheduler would log a source fault and re-arm, on a shutdown that was working
#: correctly.
_ABSORBED = (
    "read() must deliver a cancellation from outside onward unchanged and must "
    "never convert it into a ReaderError — a cancelled read has, in plain "
    "English, 'not completed', and a reader wrapping everything it catches "
    "converts it (ADR-0093 §8). Got: {outcome!r}"
)


@dataclass(frozen=True)
class GatedRead:
    """One ``read`` call an implementation can be held inside, plus its lever.

    What ADR-0060's case needs from an implementation, and no more. The property
    has no positive signal through ``read`` alone: a suite has to hold the call
    open at a point it has demonstrably reached, cancel it *there*, and see what
    comes back — and only the implementation knows where its suspension is, inside
    a file read for a concrete reader, on a modelled resource for the fake.

    A call cancelled *before* it suspends exercises none of the code an
    implementation would use to catch a ``CancelledError`` during source I/O and
    convert it, so a suite without this lever reports the property as held while
    testing nothing (ADR-0093 §10).

    Attributes:
        reader: The subject, ready to be called.
        gate: Waits until the read is suspended, and lets it go again.
    """

    reader: Reader
    gate: SuspendedCall


def assert_conforms(reading: SourceReading, name: str) -> None:
    """Assert every clause that holds of any reading, whatever it carries.

    The suite's own cases each assert one clause against one subject, which is
    what makes a failure name the obligation it broke. This is the same set as one
    call, for the cases that must hold it over a *second* subject — an empty
    reading, above all, on which every clause below still binds (ADR-0093 §8) —
    and for an implementation's own tests over a reading it provoked itself.
    """
    assert reading.source == name
    assert reading.read_at.tzinfo is not None
    assert reading.read_at.utcoffset() is not None
    if reading.as_of is not None:
        assert reading.as_of.tzinfo is not None
        assert reading.as_of.utcoffset() is not None
    for proposal in reading.proposals:
        assert proposal.proposed.kind != MemoryKind.EPISODIC.value
        assert band_of(proposal.proposed.provenance.source) is BeliefBand.ATTESTED
        attestation = proposal.proposed.provenance.attestation
        assert attestation is not None
        assert attestation.reported_by == name


class ReaderContract:
    """Behaviour every ``Reader`` implementation must exhibit (ADR-0093, ADR-0095)."""

    @pytest.fixture
    def reader(self) -> Reader:
        """Override in a subclass to supply the implementation under test.

        The subject must be one whose read reports **something**: several clauses
        below quantify over ``proposals``, and a reader configured to report
        nothing would pass them having exercised nothing. The reader that reports
        nothing is a separate subject, and has its own case.
        """
        raise NotImplementedError

    @pytest.fixture
    def empty_reader(self) -> Reader:
        """Override with a subject whose source has nothing to propose.

        Not a failure and not a degradation: ADR-0093 §8 rules an empty
        ``proposals`` tuple a **successful** reading, so this is a state a
        conforming implementation must be able to be in.
        """
        raise NotImplementedError

    @pytest.fixture
    def failing_reader(self) -> Reader:
        """Override with a subject whose source cannot be read at all.

        The suite pins the *type* that escapes. Three further obligations §8 puts
        on that raise are the **concrete reader's tests** and are named here so its
        lane writes them (ADR-0093 §10 names the first; #648 tracks all three):
        that a real missing, unreadable or malformed source is what reaches it;
        that the underlying failure survives as ``__cause__``; and that the message
        is payload-free — identity and the cause's class, never the source's
        location or contents.

        Neither of the last two is a clause a generic suite can reach. A reader
        that detects a malformed document by its own validation has no underlying
        exception to preserve, so ``__cause__ is not None`` would fail a conforming
        implementation; and payload-freeness cannot be decided without knowing what
        the payload *would* have been, which is the source's secret and not
        something ``name`` and one call disclose.
        """
        raise NotImplementedError

    def gated_read(self) -> GatedRead:
        """Override with a subject that can be held at its suspension point.

        Called once per case that needs it, so each gets a fresh gate and a fresh
        subject. See :class:`GatedRead`.
        """
        raise NotImplementedError

    def test_conforms_to_protocol(self, reader: Reader) -> None:
        assert isinstance(reader, Reader)

    # --- identity (ADR-0093 §7) ---------------------------------------------

    def test_the_declared_identity_is_non_empty(self, reader: Reader) -> None:
        """A reader that cannot say what it is forces every caller to carry a name.

        Non-empty rather than merely present: the identity lands on the reading,
        on every belief the gate then stores, in every export and in every log
        line, and a blank one names nothing in all four places.
        """
        assert reader.name.strip()

    async def test_the_declared_identity_is_stable_across_calls(self, reader: Reader) -> None:
        """Declared, not computed: reading the source must not rename the reader.

        ``name`` is a **declared constant** rather than a configurable value
        (ADR-0093 §7), so it cannot depend on what a read found — and a reader
        whose identity moved would scatter one source's beliefs across two
        ``reported_by`` values that no later fold could bring back together.
        """
        before = reader.name

        await reader.read()

        assert reader.name == before

    # --- the reading (ADR-0093 §10) -----------------------------------------

    async def test_the_reading_names_the_reader_that_produced_it(self, reader: Reader) -> None:
        """``source`` is carried on the reading rather than left to the caller.

        So the value that reaches ``Attestation.reported_by`` is the producer's
        own, and not whatever the ingesting stage happened to have beside it.
        """
        reading = await reader.read()

        assert reading.source == reader.name

    async def test_both_instants_are_timezone_aware(self, reader: Reader) -> None:
        """Neither instant is ever naive (ADR-0026 §1).

        :data:`~ai_assistant.core.types.UtcInstant` already refuses a naive value,
        so this pins the *contract* rather than standing as its only defence — the
        clause is in ADR-0093 §10's list, and a suite that asserted only what no
        type enforced would leave the seam's obligation legible nowhere.
        """
        reading = await reader.read()

        assert reading.read_at.tzinfo is not None
        assert reading.read_at.utcoffset() is not None
        if reading.as_of is not None:
            assert reading.as_of.tzinfo is not None
            assert reading.as_of.utcoffset() is not None

    # --- what may be proposed (ADR-0093 §4) ---------------------------------

    async def test_no_proposal_is_an_episodic_record(self, reader: Reader) -> None:
        """An ingested episode has no gate it survives and no exemption it claims.

        ADR-0075 §2 declines the capture exemption to this producer and ADR-0075
        §4 shows the gate is destructive to an episode, so §4's refusal is a
        property of the seam rather than of one implementation — which is why it
        is asserted here and not in a concrete reader's tests.
        """
        reading = await reader.read()

        assert reading.proposals, "the subject proposed nothing, so this clause is vacuous"
        assert all(
            proposal.proposed.kind != MemoryKind.EPISODIC.value for proposal in reading.proposals
        )

    async def test_every_proposal_is_in_the_attested_band(self, reader: Reader) -> None:
        """What a source reported is a third party's claim, and nothing more.

        A band whose whole standing is that someone else said it is the last band
        that should reach the store unmediated (ADR-0093 §1) — and since ADR-0092
        §1 the band brings an obligation with it: an ``ATTESTED``
        :class:`~ai_assistant.core.types.Provenance` carries an
        :class:`~ai_assistant.core.types.Attestation` naming what reported the
        belief and when that source said so, or it does not construct at all.
        """
        reading = await reader.read()

        assert reading.proposals, "the subject proposed nothing, so this clause is vacuous"
        for proposal in reading.proposals:
            source = proposal.proposed.provenance.source
            assert band_of(source) is BeliefBand.ATTESTED, source

    async def test_every_proposal_is_attributed_to_the_reader_that_produced_it(
        self, reader: Reader
    ) -> None:
        """The identity that reaches the stored belief is the producer's own.

        ADR-0093 §10 carries ``source`` on the reading "so the value that reaches
        ADR-0092's vehicle is the producer's own" — and that vehicle is
        :attr:`~ai_assistant.core.types.Attestation.reported_by`. A reading whose
        ``source`` says ``calendar`` while its proposals are attested to something
        else stores beliefs attributed to a reader that never reported them, which
        no later fold can bring back together: ADR-0092 §6 mints our own ids, so
        ``reported_by`` is "the only durable handle the record keeps on where it
        came from".

        **It is a suite clause on ADR-0093 §10's own test** — decidable from
        ``name`` and one ``read()`` return value, which is the whole of what a
        conforming ``Reader`` is — rather than because §10's list enumerates it;
        the list predates the field being real, and §10 names its four *exclusions*
        precisely so an unlisted, decidable clause is read as an omission and not a
        licence.

        **Revisit when ADR-0093 §11's registry deferral fires.** It defers "a
        source registry, and with it a configurable display label and an
        instance-distinguishing ``reported_by``", firing at the second instance of
        one source type — at which point a reader's identity and the *instance* it
        reports for may legitimately differ, and this equality is the assertion
        that lane amends. Until then a reader reads one source (§1), so the two are
        one value, and ADR-0093 §7 states the equality for the first reader in as
        many words.
        """
        reading = await reader.read()

        assert reading.proposals, "the subject proposed nothing, so this clause is vacuous"
        for proposal in reading.proposals:
            attestation = proposal.proposed.provenance.attestation
            assert attestation is not None, "an ATTESTED belief carries one (ADR-0092 §1)"
            assert attestation.reported_by == reader.name

    # --- the empty reading is a success (ADR-0093 §8) ------------------------

    async def test_an_empty_reading_is_a_success_on_which_every_clause_holds(
        self, empty_reader: Reader
    ) -> None:
        """Nothing to report is an answer, and must not read as a failure.

        No caller may treat it as one: a scheduled job that read an empty tuple as
        a fault would re-arm forever on a source that is simply quiet, and a facet
        that read it as one would degrade rather than say "your calendar is
        clear". The clauses above are asserted again here because an empty reading
        is where an implementation is most likely to stop bothering — a blank
        ``source`` or a naive ``read_at`` on the nothing-to-say path is exactly
        the shape that survives review.
        """
        reading = await empty_reader.read()

        assert reading.proposals == ()
        assert_conforms(reading, empty_reader.name)

    # --- failure is a raise, never a smaller reading (ADR-0093 §8) ----------

    async def test_a_read_that_cannot_complete_raises_rather_than_returning(
        self, failing_reader: Reader
    ) -> None:
        """A half-parsed calendar is not a smaller calendar.

        If a failed read returned an empty reading the two states would be
        indistinguishable at the seam, and both consumers need to tell them apart
        in opposite directions: the scheduled job would report success on every
        failure — a reader whose file was unreadable for a week would look healthy
        for a week — and the facet would present "your calendar is clear" when the
        truth is "we could not read your calendar", which is the same class of
        falsehood §4's absence rule forbids arriving through the other consumer.

        This pins the type, which is what a generic suite can reach. That a real
        source failure is what gets here is the concrete reader's test.
        """
        with pytest.raises(ReaderError):
            await failing_reader.read()

    # --- input observation (ADR-0065) ---------------------------------------

    def test_read_takes_no_arguments(self, reader: Reader) -> None:
        """The seam has no caller-owned input, and that is what discharges ADR-0065.

        ADR-0065's clause is about an argument the caller may still be holding and
        mutate mid-flight; ``read()`` has none, so the clause is **vacuous here and
        must stay that way** — which is a property of the signature and is
        therefore assertable. It is the same fact ADR-0093 §10 argues from the
        other side: a caller able to widen the read is a caller able to defeat the
        bound §5 puts on the producer, which is the property ADR-0077 §1 bought by
        putting the maximum on the producer rather than on the call.
        """
        assert not inspect.signature(reader.read).parameters

    # --- cancellation (ADR-0060, ADR-0093 §8) -------------------------------

    async def test_a_cancellation_is_delivered_onward_and_never_becomes_a_reader_error(
        self,
    ) -> None:
        """A cancellation from outside is re-raised, never wrapped and never absorbed.

        The clause ADR-0093 §8 carves out of its own wrapping rule, and the one
        clause beyond the standard pair that §10 spells out. It is driven through
        :meth:`gated_read` rather than by cancelling a fresh task, because a call
        cancelled before it suspends never reaches the ``except`` an
        implementation wraps its source I/O in — and that ``except`` is the whole
        of what this case is about.
        """
        gated = self.gated_read()

        call = asyncio.ensure_future(gated.reader.read())
        try:
            await gated.gate.reached()
            call.cancel()
        finally:
            gated.gate.release()

        outcome: object
        try:
            outcome = await call
        except asyncio.CancelledError as exc:
            outcome = exc
        except ReaderError as exc:
            outcome = exc

        assert isinstance(outcome, asyncio.CancelledError), _ABSORBED.format(outcome=outcome)

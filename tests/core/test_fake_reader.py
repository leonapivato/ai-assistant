"""The canonical FakeReader passes the shared Reader suite (ADR-0093, ADR-0095).

This is what lets other subsystems trust ``ai_assistant.testing.FakeReader`` as a
stand-in for a real producer: it is held to the same contract the concrete ``.ics``
reader will be, in the lane ADR-0093 §10 defers it to.

Below the binding are the behaviours specific to the fake — its scripting, its
refusals at construction, and the resource it models so the suite's cancellation
case is not vacuous — none of which are contract.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from reader_contract import GatedRead, ReaderContract, assert_conforms, declared_name_of

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import (
    Attestation,
    EpisodicMemory,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    ReadCoverage,
    ReportedExtent,
    SemanticMemory,
)
from ai_assistant.testing import DEFAULT_READER_NAME, FakeReader, attested_proposal

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Reader

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = datetime(2026, 3, 1, tzinfo=UTC)

#: One minted discriminator, written out rather than generated: a case that drew
#: its own would pass on a value no reader of the test can check against §4's
#: alphabet and width (ADR-0190 §4).
_DISCRIMINATOR = "0f3c9d1a7b45e28c6d90fa3b17e4c852"

#: What a deployment's *second* configured source of the fake's type declares.
_DISCRIMINATED = f"{DEFAULT_READER_NAME}:{_DISCRIMINATOR}"


class TestFakeReaderContract(ReaderContract):
    """Runs FakeReader through the shared Reader conformance suite."""

    @pytest.fixture
    def reader(self) -> Reader:
        return FakeReader()

    @pytest.fixture
    def empty_reader(self) -> Reader:
        return FakeReader([], name="quiet-source")

    @pytest.fixture
    def failing_reader(self) -> Reader:
        return FakeReader(name="broken-source", failure=FileNotFoundError())

    def gated_read(self) -> GatedRead:
        subject = FakeReader()
        return GatedRead(reader=subject, gate=subject.suspend_next())


class TestFakeReaderContractDiscriminated(ReaderContract):
    """The same fake through the same suite, declaring a **discriminated** identity.

    ADR-0190 §4's second form, exercised rather than asserted about. A second
    configured source of one reader type declares its type's name, one colon and a
    32-character minted discriminator, and every clause of the suite has to hold
    of that exactly as it holds of a bare name — the reading naming its producer,
    each proposal's ``Attestation.reported_by`` matching it, the identity's own
    form. Binding the suite twice is what shows the form is admitted *everywhere*
    the identity travels rather than only where a case happened to look.
    """

    @pytest.fixture
    def reader(self) -> Reader:
        return FakeReader(discriminator=_DISCRIMINATOR)

    @pytest.fixture
    def empty_reader(self) -> Reader:
        return FakeReader([], name="quiet-source", discriminator=_DISCRIMINATOR)

    @pytest.fixture
    def failing_reader(self) -> Reader:
        return FakeReader(
            name="broken-source", discriminator=_DISCRIMINATOR, failure=FileNotFoundError()
        )

    def gated_read(self) -> GatedRead:
        subject = FakeReader(discriminator=_DISCRIMINATOR)
        return GatedRead(reader=subject, gate=subject.suspend_next())


# --- behaviour specific to FakeReader, beyond the shared contract -----------


async def test_the_default_script_reports_something() -> None:
    """A suite run against this fake must not pass its band clause vacuously."""
    reading = await FakeReader().read()

    assert reading.proposals
    assert_conforms(reading, DEFAULT_READER_NAME)


async def test_an_empty_script_is_the_explicit_nothing_to_report_state() -> None:
    """Distinct from the default, and distinct from a failure (ADR-0093 §8)."""
    reading = await FakeReader([]).read()

    assert reading.proposals == ()
    assert reading.source == DEFAULT_READER_NAME


async def test_a_declared_as_of_is_carried_and_defaults_to_absent() -> None:
    """``None`` is the first real source's case, and a ruling (ADR-0093 §10)."""
    assert (await FakeReader().read()).as_of is None
    assert (await FakeReader(as_of=_WHEN).read()).as_of == _WHEN


async def test_a_declared_coverage_is_carried_and_defaults_to_absent() -> None:
    """#804's knob, and the ``None`` is the state of every reader that has not opted in.

    ADR-0110 §2 makes a coverage optional and its absence load-bearing: a reading
    that declares none warrants no absence at all, which is where every consumer
    that does not care about ADR-0110 §3 stays without having to ask.
    """
    coverage = ReadCoverage(covers_from=_WHEN, covers_until=_LATER)

    assert (await FakeReader().read()).coverage is None
    assert (await FakeReader(coverage=coverage).read()).coverage == coverage


async def test_the_coverage_is_the_test_authors_and_is_never_synthesised() -> None:
    """ADR-0117 §9's Reader-suite clause, where this fake can be held to it.

    A coverage states what a read **exhausted** and "may not be widened to what the
    reader was configured to cover" (ADR-0110 §2), so a fake that computed one from
    its own configuration — from ``read_at`` and a notional window, or from the
    span of the proposals it holds — would model exactly what the clause forbids,
    and every consumer driven by it would be testing against a producer no
    conforming reader may be.

    Three levers move underneath a fixed ``coverage`` here and none of them reaches
    it: the identity, the read instant, and the proposals — whose extent lies
    **outside** the declared coverage, which is a state a real reader reaches
    whenever an entry straddles its window edge (ADR-0117 §6) and which a fake
    deriving a coverage from its script could not produce.
    """
    declared = ReadCoverage(covers_from=_WHEN, covers_until=_LATER)
    outside = ReportedExtent(extends_from=_LATER, extends_until=_LATER + timedelta(days=400))
    subject = FakeReader(
        [attested_proposal("a standup", reported_by="calendar", extent=outside)],
        name="calendar",
        read_at=_LATER + timedelta(days=900),
        coverage=declared,
    )

    reading = await subject.read()

    assert reading.coverage == declared
    attestation = reading.proposals[0].proposed.provenance.attestation
    assert attestation is not None
    assert attestation.extent == outside


async def test_the_synthesised_reading_carries_the_declared_coverage_too() -> None:
    """Both build paths, so the two cannot disagree about the field a consumer reads.

    The default script re-synthesises its proposal per read (ADR-0092 §6) and a
    coverage is no part of that synthesis: it is the author's value, carried onto
    whatever the fake happens to be returning.
    """
    coverage = ReadCoverage(covers_until=_LATER)
    subject = FakeReader(coverage=coverage)

    first, second = await subject.read(), await subject.read()

    assert first.coverage == coverage == second.coverage
    assert first.proposals[0].proposed.id != second.proposals[0].proposed.id


def test_a_proposal_states_no_extent_unless_the_author_gives_it_one() -> None:
    """ADR-0117 §2's third clause, at the helper every ``Reader`` suite builds with.

    Declaring none is always available and always safe, so it is the default: a
    helper that handed every proposal an extent would make ADR-0110 §3's close fire
    in suites that never asked for it, and would make the no-extent case — which
    ADR-0117 §9 obliges each writer's tests to cover — the awkward one to write.
    """
    stated = ReportedExtent(extends_from=_WHEN, extends_until=_LATER)
    plain = attested_proposal("a standup", reported_by="calendar")
    positioned = attested_proposal("a standup", reported_by="calendar", extent=stated)

    assert plain.proposed.provenance.attestation is not None
    assert plain.proposed.provenance.attestation.extent is None
    assert positioned.proposed.provenance.attestation is not None
    assert positioned.proposed.provenance.attestation.extent == stated


def test_the_extent_is_a_different_fact_from_the_report_time() -> None:
    """ADR-0117 §6's last paragraph, pinned where both values are set together.

    "An entry reported on Monday about a meeting on Thursday has both, and they
    disagree by design." Neither is derived from the other, and a helper filling one
    from the other would make every fixture in the corpus agree about a pair that
    has to be free to differ.
    """
    proposal = attested_proposal(
        "a standup",
        reported_by="calendar",
        reported_at=_WHEN,
        extent=ReportedExtent(extends_from=_LATER, extends_until=_LATER + timedelta(hours=1)),
    )

    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None
    assert attestation.reported_at == _WHEN
    assert attestation.extent is not None
    assert attestation.extent.extends_from == _LATER, "the entry lies well after the report"


async def test_a_scripted_failure_is_wrapped_with_its_cause_and_a_payload_free_message() -> None:
    """Both halves of §8: the cause survives, and the message says nothing.

    Preserving the cause and logging it are different acts, and the obvious
    wrapper conflates them: ``raise ReaderError(str(exc)) from exc`` would put the
    source's path into a message the scheduler writes to a log (ADR-0004 §5).
    """
    cause = PermissionError("/home/alice/Private/therapy.ics")
    subject = FakeReader(name="calendar", failure=cause)

    with pytest.raises(ReaderError) as caught:
        await subject.read()

    assert caught.value.__cause__ is cause
    assert str(caught.value) == "calendar: PermissionError"
    assert "therapy" not in str(caught.value)


async def test_a_scripted_proposal_is_returned_verbatim() -> None:
    """The consumer scripts the belief; there is no batch for the fake to fill in."""
    proposal = attested_proposal("the user has a 10:00 standup", reported_by="calendar")

    reading = await FakeReader([proposal], name="calendar").read()

    assert reading.proposals == (proposal,)


async def test_a_re_read_mints_a_new_id_rather_than_aiming_at_the_last_one() -> None:
    """ADR-0092 §6: minting removes the aim, and a fake must not restore it.

    The id is an *address*. A producer whose re-read recomputes the id it proposed
    last time can land on a record the user has since retired and overwrite its
    closed validity window through ``ACCEPT``'s blind upsert — the ADR-0038 §2a
    resurrection. The content is unchanged across the two reads, which is exactly
    the case a derived id would collapse.

    The factory is injected rather than left to ``uuid4`` (CONTRIBUTING →
    "Determinism"): what is under test is that a *second* mint happens at all, and
    ambient randomness would assert it through a probability rather than through
    the behaviour. That the default mint is opaque is its own case below.
    """
    minted = iter(["r-1", "r-2"])
    subject = FakeReader(id_factory=lambda: next(minted))

    first = await subject.read()
    second = await subject.read()

    assert first.proposals[0].proposed.content == second.proposals[0].proposed.content
    assert first.proposals[0].proposed.id == "r-1"
    assert second.proposals[0].proposed.id == "r-2"
    assert subject.call_count == 2


async def test_the_default_mint_is_opaque_to_the_source() -> None:
    """Not the source's key, and not a hash of what it said (ADR-0092 §6).

    The one case that exercises the un-injected ``uuid4`` path, and it asserts
    nothing probabilistic: a hex digest can contain neither the content (it has
    spaces) nor a name with a non-hex letter in it.
    """
    reading = await FakeReader(name="calendar").read()
    record = reading.proposals[0].proposed

    assert record.content not in record.id
    assert "calendar" not in record.id


async def test_a_blank_mint_fails_rather_than_becoming_a_key() -> None:
    """The guard ADR-0092 §6 owes a minted id, at the factory's output."""
    subject = FakeReader(id_factory=lambda: "   ")

    with pytest.raises(ValueError, match=r"(?i)non-blank|key"):
        await subject.read()


async def test_a_non_string_mint_is_refused_rather_than_reaching_a_string_method() -> None:
    """A malformed mint is a deliberate refusal, not an ``AttributeError``.

    ``mypy`` already forbids the annotation, so this is the guard for a factory
    that defeats it — which is the case a *guarded output* is for.
    """
    subject = FakeReader(id_factory=lambda: 1)  # type: ignore[arg-type,return-value]

    with pytest.raises(ValueError, match=r"(?i)built-in str"):
        await subject.read()


async def test_a_hostile_string_subclass_is_refused_before_it_is_touched() -> None:
    """``type(minted) is not str`` invokes no user code (``FakeMemoryWriter``'s reason).

    An ``isinstance`` check would admit this and then leak the subclass's own
    exception across the seam as a store key.
    """

    class Hostile(str):
        __slots__ = ()

        def strip(self, chars: str | None = None, /) -> str:
            raise AssertionError

    subject = FakeReader(id_factory=lambda: Hostile("r-1"))

    with pytest.raises(ValueError, match=r"(?i)built-in str"):
        await subject.read()


async def test_a_scripted_reading_is_stable_across_reads() -> None:
    """Those ids are the test author's, so re-minting them would defeat the script."""
    proposal = attested_proposal("a standup", reported_by="calendar", record_id="r-9")
    subject = FakeReader([proposal], name="calendar")

    assert await subject.read() == await subject.read()


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("   ", id="blank"),
        pytest.param("", id="empty"),
        pytest.param(" calendar ", id="padded"),
        pytest.param("calendar ", id="trailing space"),
        pytest.param("calendar:0f3c9d1a7b45e28c6d90fa3b17e4c852", id="a whole identity"),
        pytest.param("calendar:work", id="any colon at all"),
        pytest.param("calendar\ud800", id="lone surrogate"),
    ],
)
def test_a_value_that_is_not_a_declared_name_is_refused_at_construction(name: str) -> None:
    """``name`` is the **declared name** half, and this seam refuses rather than repairs.

    ADR-0190 §4: non-empty, UTF-8-encodable, equal to its own ``str.strip()``, and
    colon-free. A whole discriminated identity is refused here too, and that is the
    point of the split — the discriminator arrives through its own parameter, so
    there is exactly one way to spell each half and no way for the two to disagree.

    The padded cases are the ones that used to be *repaired*. The fake stripped, on
    the sound ground that ``Attestation.reported_by`` strips and
    ``SourceReading.source`` does not; §4 closes that at the declaring end instead,
    and a fake that canonicalised silently would hide the offending value from the
    author who wrote it.
    """
    with pytest.raises(ValueError, match=r"(?i)ADR-0190"):
        FakeReader(name=name)


@pytest.mark.parametrize(
    "discriminator",
    [
        pytest.param("0F3C9D1A7B45E28C6D90FA3B17E4C852", id="uppercase"),
        pytest.param("0f3c9d1a7b45e28c6d90fa3b17e4c85", id="31 characters"),
        pytest.param("0f3c9d1a7b45e28c6d90fa3b17e4c8523", id="33 characters"),
        pytest.param("0f3c9d1a7b45e28c6d90fa3b17e4c85g", id="outside the alphabet"),
        pytest.param("0f3c9d1a-7b45-e28c-6d90-fa3b17e4c852", id="separators"),
        pytest.param("", id="empty"),
    ],
)
def test_a_value_that_is_not_a_discriminator_is_refused_at_construction(
    discriminator: str,
) -> None:
    """ADR-0190 §4's *first* admitting clause, which is not the identity clause.

    §4 binds "a seam that takes a discriminator on its own — a configuration field,
    a mint's output — whether or not a whole identity passes through it", and gives
    the reason: §1 rules that what a deployment supplies is the discriminator
    alone, so "a registry field taking ``ABC…`` uppercase breaches no clause and
    composes ``calendar:ABC…`` afterwards" if only the identity clause guards it.
    This parameter is that seam, and it is guarded before anything composes.
    """
    with pytest.raises(ValueError, match=r"(?i)ADR-0190"):
        FakeReader(discriminator=discriminator)


def test_a_hex_shaped_declared_name_is_admitted_because_a_declared_name_is_not_a_spelling() -> None:
    """A discriminator is defined by its role, not by looking like one (ADR-0190 §1).

    §4 constrains a declared name to be non-empty, UTF-8-encodable, canonical and
    colon-free, and constrains its spelling no further — so a reader type declaring
    32 hexadecimal characters is conforming, and the canonical fake has to be able
    to stand in for it. §3's "never a discriminator on its own" is not reachable by
    inspecting one string: nothing decidable tells this value from a discriminator
    handed over without its prefix.

    The split is what makes both true at once. A discriminator can only arrive as
    ``discriminator=``, so it can never *become* the whole identity however it is
    spelled; and a declared name is whatever the reader type says it is. Pinned
    because the shape heuristic that would refuse this was tried and was wrong.
    """
    subject = FakeReader(name=_DISCRIMINATOR)

    assert subject.name == _DISCRIMINATOR


def test_a_discriminator_never_becomes_the_whole_identity() -> None:
    """§3's "never a discriminator on its own", held structurally rather than checked.

    There is no argument to this constructor that yields an identity with no
    declared half: ``name`` refuses a colon and defaults to a real declared name,
    and ``discriminator`` is only ever composed onto it. So the property is a fact
    about the constructor's shape rather than a validator that could be argued
    with — which is the same move ADR-0092 §2 makes when it prefers a value object
    over two nullable fields to make a half-state unconstructable.
    """
    assert FakeReader(discriminator=_DISCRIMINATOR).name == _DISCRIMINATED
    assert declared_name_of(FakeReader(discriminator=_DISCRIMINATOR).name) == DEFAULT_READER_NAME


async def test_a_discriminated_identity_reaches_the_reading_and_its_attestation() -> None:
    """A second configured source's identity travels the whole seam unaltered.

    Both halves matter and neither is canonicalised on the way: ``source`` carries
    the value verbatim and ``reported_by`` — an ``Identifier``, which strips — has
    nothing to strip, which is exactly what §4's canonicality rule buys.
    """
    subject = FakeReader(discriminator=_DISCRIMINATOR)

    reading = await subject.read()

    assert subject.name == _DISCRIMINATED
    assert reading.source == _DISCRIMINATED
    (proposal,) = reading.proposals
    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None
    assert attestation.reported_by == _DISCRIMINATED
    assert_conforms(reading, subject.name)


def test_the_declared_half_of_the_fakes_own_identity_is_its_own_declared_name() -> None:
    """The half ``ReaderContract`` cannot reach, for this subject (ADR-0190 §3).

    The suite holds a ``Reader`` and nothing to compare a prefix against. For the
    fake the declared name is ``name``'s own value, so the check is that composing
    a discriminator onto it leaves that half exactly as the caller gave it.
    """
    assert declared_name_of(FakeReader().name) == DEFAULT_READER_NAME
    assert declared_name_of(FakeReader(discriminator=_DISCRIMINATOR).name) == DEFAULT_READER_NAME


def test_an_episodic_proposal_is_refused_at_construction() -> None:
    """ADR-0093 §4's refusal, caught where the script was written."""
    episode = MemoryUpdateProposal(
        proposed=EpisodicMemory(
            id="e-1",
            content="the standup happened",
            occurred_at=_WHEN,
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=0.9,
                last_updated=_LATER,
                attestation=Attestation(reported_by="calendar", reported_at=_WHEN),
            ),
        ),
        rationale="calendar reported it",
    )

    with pytest.raises(ValueError, match=r"(?i)episodic"):
        FakeReader([episode], name="calendar")


def test_a_proposal_outside_the_attested_band_is_refused_at_construction() -> None:
    """What a reader reports is a third party's claim, never our own inference."""
    inferred = MemoryUpdateProposal(
        proposed=SemanticMemory(
            id="s-1",
            content="the user prefers mornings",
            fact="the user prefers mornings",
            provenance=Provenance(
                source=MemorySource.INFERRED,
                confidence=0.4,
                last_updated=_LATER,
            ),
        ),
        rationale="worked out from the calendar",
    )

    with pytest.raises(ValueError, match=r"(?i)attested"):
        FakeReader([inferred], name="calendar")


def test_a_proposal_attested_to_another_source_is_refused_at_construction() -> None:
    """A belief may not be stored under a reader that never reported it.

    The one refusal whose absence would not fail ``read()`` but would fail the
    shared suite — and, in production, would put a stored belief under a
    ``reported_by`` no later fold could bring back together (ADR-0092 §6).
    """
    with pytest.raises(ValueError, match=r"(?i)attested to|producer"):
        FakeReader([attested_proposal("a standup", reported_by="other")], name="calendar")


def test_a_proposal_with_no_rationale_is_refused_at_construction() -> None:
    """The decidable half of ADR-0093 §4; *naming* the source stays the producer's."""
    silent = MemoryUpdateProposal(
        proposed=SemanticMemory(
            id="s-2",
            content="a standup at 10:00",
            fact="a standup at 10:00",
            provenance=Provenance(
                source=MemorySource.EXTERNAL,
                confidence=0.9,
                last_updated=_LATER,
                attestation=Attestation(reported_by="calendar", reported_at=_WHEN),
            ),
        ),
        rationale="   ",
    )

    with pytest.raises(ValueError, match=r"(?i)rationale"):
        FakeReader([silent], name="calendar")


def test_a_naive_instant_is_refused_where_it_was_written() -> None:
    """Built eagerly, so ``UtcInstant``'s refusal lands at construction, not at read."""
    with pytest.raises(ValueError, match=r"(?i)aware|naive|timezone|utc"):
        FakeReader(read_at=datetime(2026, 1, 1))  # noqa: DTZ001 — the point is the naivety


def test_a_blank_proposal_content_is_refused_by_the_helper() -> None:
    """``attested_proposal`` refuses what nothing downstream would (see its docstring)."""
    with pytest.raises(ValueError, match=r"(?i)content"):
        attested_proposal("  ", reported_by="calendar")


def test_the_helper_reports_the_source_clock_and_ours_separately() -> None:
    """Monday's report, revised into the store on Tuesday (ADR-0092 §3)."""
    proposal = attested_proposal(
        "the user has a 10:00 standup",
        reported_by="calendar",
        reported_at=_WHEN,
        last_updated=_LATER,
    )

    attestation = proposal.proposed.provenance.attestation
    assert attestation is not None
    assert attestation.reported_by == "calendar"
    assert attestation.reported_at == _WHEN
    assert proposal.proposed.provenance.last_updated == _LATER
    # And the *confirming* instant is the source's too, never ours (ADR-0109 §4):
    # the `ATTESTED` band is confirmed by the report and not by our ingestion of
    # it. Pinned on the canonical helper because a fake that quietly wrote `None`
    # here, or `last_updated`, would let every suite built on it certify a reader
    # the concrete `CalendarReader` does not resemble (ADR-0026 §7).
    assert proposal.proposed.provenance.last_confirmed_at == _WHEN
    assert proposal.proposed.provenance.last_confirmed_at != _LATER


async def test_a_second_read_does_not_reach_the_source_a_cancelled_one_still_holds() -> None:
    """ADR-0060's resource half, on the one subject that can exhibit it.

    Not a suite clause — a generic suite has no handle on an arbitrary reader's
    file descriptor (see ``reader_contract``'s module docstring) — but the fake
    models the resource, so the property the module clause is *about* is asserted
    somewhere rather than nowhere: cancelling the first caller must not let the
    second in while the first's work is still notionally using the source.
    """
    subject = FakeReader()
    gate = subject.suspend_next()

    first = asyncio.ensure_future(subject.read())
    await gate.reached()
    second = asyncio.ensure_future(subject.read())
    first.cancel()
    gate.release()

    with pytest.raises(asyncio.CancelledError):
        await first
    await second

    assert not subject.log.overlapped
    assert subject.log.visits == 2

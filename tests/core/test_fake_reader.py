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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from reader_contract import GatedRead, ReaderContract, assert_conforms

from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import (
    Attestation,
    EpisodicMemory,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
)
from ai_assistant.testing import DEFAULT_READER_NAME, FakeReader, attested_proposal

if TYPE_CHECKING:
    from ai_assistant.core.protocols import Reader

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = datetime(2026, 3, 1, tzinfo=UTC)


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
    """
    subject = FakeReader()

    first = await subject.read()
    second = await subject.read()

    assert first.proposals[0].proposed.content == second.proposals[0].proposed.content
    assert first.proposals[0].proposed.id != second.proposals[0].proposed.id
    assert subject.call_count == 2


async def test_a_minted_id_is_opaque_to_the_source() -> None:
    """Not the source's key, and not a hash of what it said (ADR-0092 §6)."""
    reading = await FakeReader(name="calendar").read()
    record = reading.proposals[0].proposed

    assert record.content not in record.id
    assert "calendar" not in record.id


async def test_an_id_factory_names_the_records_for_a_test_that_needs_to() -> None:
    """A caller *choosing* an id is not a producer *deriving* one."""
    ids = iter(["r-1", "r-2"])
    subject = FakeReader(id_factory=lambda: next(ids))

    assert (await subject.read()).proposals[0].proposed.id == "r-1"
    assert (await subject.read()).proposals[0].proposed.id == "r-2"


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


def test_a_blank_identity_is_refused_at_construction() -> None:
    """The canonical fake must not be configurable into breaking its own contract."""
    with pytest.raises(ValueError, match=r"(?i)identity|blank"):
        FakeReader(name="   ")


async def test_a_padded_identity_cannot_split_the_reading_from_its_attestation() -> None:
    """``source`` does not strip and ``reported_by`` does, so the fake canonicalises.

    Otherwise ``" calendar "`` produces a reading attributed to ``"calendar"`` by a
    producer calling itself ``" calendar "`` — a failure of the suite's attribution
    clause on a difference no author would see in the source.
    """
    subject = FakeReader(name=" calendar ")

    reading = await subject.read()

    assert subject.name == "calendar"
    assert reading.source == "calendar"
    assert_conforms(reading, subject.name)


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

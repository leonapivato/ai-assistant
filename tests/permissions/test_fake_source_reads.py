"""The canonical read-trail fakes pass the shared conformance suites (ADR-0185 §12).

Three bindings, not two, and the third is the one that carries an argument.
``TestFakeSourceReadRecorderContract`` and ``TestFakeSourceReadTrailContract`` are
the ordinary ones — each fake against its own seam's suite, which is what lets
other subsystems trust ``ai_assistant.testing``'s doubles as stand-ins.

``TestFakeSourceReadTrailSatisfiesTheNarrowSeam`` runs the **trail** fake through
the ``SourceReadRecorder`` suite, which ADR-0185 §12 requires in as many words:
"The lane's conformance suite binds the ``SourceReadRecorder`` contract to **both**
fakes and to the concrete store, so the store's satisfaction of the narrow seam is
evidence rather than assertion." That claim is what lets a composition root pass
one object to every driver's ``SourceReadRecorder`` parameter and to the hub's
``SourceReadTrail`` one, and without this binding it would be a sentence in an ADR
rather than something the gate checks.

The scripted capabilities each fake carries beyond its contract — a raising
``record``, a raising read, a suspendable resource — are tested here too. They are
not contract, but they are what makes a *driver's* ADR-0185 §5 fail-closed branch
and §11 arm (e)'s three attempts reachable from a test at all, so a capability that
quietly stopped working would take a later lane's coverage with it.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest
from source_read_contract import SourceReadRecorderContract, SourceReadTrailContract

from ai_assistant.core.errors import ReadTrailError
from ai_assistant.core.protocols import SourceReadRecorder, SourceReadTrail
from ai_assistant.core.types import ReadOutcome
from ai_assistant.testing import (
    DEFAULT_READ_SOURCE,
    FakeReader,
    FakeSourceReadRecorder,
    FakeSourceReadTrail,
    source_read_record,
)
from ai_assistant.testing.cancellation import SuspendedMidWrite

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.types import SourceReadRecord


class TestFakeSourceReadRecorderContract(SourceReadRecorderContract):
    """Runs FakeSourceReadRecorder through the shared SourceReadRecorder suite."""

    @pytest.fixture
    def recorder(self) -> SourceReadRecorder:
        return FakeSourceReadRecorder()

    async def written(self, recorder: SourceReadRecorder) -> list[SourceReadRecord]:
        """Read back through the fake's own test-only lever.

        The write seam has no read member — that is the property under test — so
        what the narrow fake holds is observed through a name no production caller
        would reach for, rather than through the Protocol the code under test holds.
        """
        assert isinstance(recorder, FakeSourceReadRecorder)
        return list(recorder.written)


class TestFakeSourceReadTrailContract(SourceReadTrailContract):
    """Runs FakeSourceReadTrail through the shared SourceReadTrail suite."""

    # No ``operations_without_shared_resource`` opt-out: every operation on this
    # fake — the two writes and both reads — enters the one modelled resource, so
    # ADR-0060's case runs against every lock site rather than skipping some.

    @pytest.fixture
    def trail(self) -> SourceReadTrail:
        return FakeSourceReadTrail()

    @contextlib.asynccontextmanager
    async def bounded(self, max_rows: int) -> AsyncIterator[SourceReadTrail]:
        """A trail whose cap is ``max_rows``; nothing to dispose of."""
        yield FakeSourceReadTrail(max_rows=max_rows)

    @contextlib.asynccontextmanager
    async def trail_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[SourceReadTrail]]:
        """The fake models the resource it does not really own (ADR-0060 §3).

        A list needs no serialising, so without this the canonical fake could only
        opt out — and the cancellation case would then run against the durable store
        alone, where a regression is harder to arrange. Every method passes through
        the *one* modelled resource, so ``arm`` ignores which operation it is
        handed: the parametrised cases exercise the same ``held()`` path here and
        earn their keep on the durable store, where each operation is a separate
        lock site.
        """
        trail = FakeSourceReadTrail()
        yield SuspendedMidWrite(
            store=trail,
            log=trail.resource_log,
            arm=lambda _operation: trail.suspend_next_operation(),
        )


class TestFakeSourceReadTrailSatisfiesTheNarrowSeam(SourceReadRecorderContract):
    """The trail fake, run through the *narrow* seam's suite (ADR-0185 §12).

    ADR-0185 §4's "one implementation satisfies both" as a test rather than an
    assertion. Deliberately a separate class from
    :class:`TestFakeSourceReadTrailContract`: that one binds the trail to the wider
    suite through the ``trail`` fixture, and this one binds it to the narrow suite
    through ``recorder`` — which is the fixture a *driver* would be handed, and
    therefore the one whose behaviour the gate actually depends on.
    """

    @pytest.fixture
    def recorder(self) -> SourceReadRecorder:
        return FakeSourceReadTrail()

    async def written(self, recorder: SourceReadRecorder) -> list[SourceReadRecord]:
        """Read back through ``export``, since this subject has one."""
        assert isinstance(recorder, SourceReadTrail)
        return await recorder.export()


# --- the scripted capabilities ADR-0185 §11 requires of the fakes ------------


async def test_the_narrow_fake_offers_no_way_to_read_the_trail() -> None:
    """The capability split modelled in the fake, not only in the annotation.

    ADR-0185 §4's guarantee is static — a driver cannot *name* ``recent`` on a
    ``SourceReadRecorder`` parameter — and a canonical fake that carried the members
    anyway would let a driver's own test reach them through a concrete annotation,
    which is the one place the type stops arguing. What that forecloses is the
    cursor ADR-0093 §5 forbids by name: a driver able to ask "when did I last read
    this, and what did it produce" is a driver able to skip, back off or resume.
    """
    # Typed `object` so the check is a runtime one: mypy already knows the answer
    # (the fake is `@final`), and an annotated subject would make the assertion
    # unreachable rather than merely redundant.
    recorder: object = FakeSourceReadRecorder()

    assert not isinstance(recorder, SourceReadTrail)
    for member in ("recent", "export", "clear"):
        assert not hasattr(recorder, member), member


@pytest.mark.parametrize(
    "make",
    [FakeSourceReadRecorder, FakeSourceReadTrail],
    ids=["the narrow fake", "the trail fake"],
)
async def test_both_fakes_can_be_scripted_to_raise_from_record(
    make: type[FakeSourceReadRecorder] | type[FakeSourceReadTrail],
) -> None:
    """ADR-0185 §5's fail-closed clause is otherwise unreachable from any test.

    "Where the recorder raises, the driver discards the reading: nothing is
    proposed, no facet is contributed, no candidate is concluded." Required of
    **both** fakes because a driver may be handed either — the composition root is
    free to pass the concrete trail to a ``SourceReadRecorder`` parameter — and a
    capability present on only one would leave that wiring's branch untested. The
    cause survives, so a driver's own test can assert what it wrapped.
    """
    subject = make()
    cause = OSError("disk gone")
    subject.fail_record(cause)

    with pytest.raises(ReadTrailError) as raised:
        await subject.record(source_read_record())

    assert raised.value.__cause__ is cause


async def test_a_scripted_write_fault_leaves_the_narrow_fake_empty() -> None:
    """A refusal must not half-write, which is what makes arm (e) measurable.

    §11's leaked-product figure counts what reached a consumer from an *unrecorded*
    attempt, so a fake that appended and then raised would make the attempt
    recorded and the figure vacuous.
    """
    recorder = FakeSourceReadRecorder()
    recorder.fail_record()

    with pytest.raises(ReadTrailError):
        await recorder.record(source_read_record())

    assert recorder.written == ()


async def test_the_trail_fake_can_be_scripted_to_raise_from_a_read() -> None:
    """ "The trail could not be read" is a state no well-formed input can provoke.

    A consumer's own ``ReadTrailError`` branch on the read path is unreachable
    without a lever for it, and the surface ADR-0186 decides will have one.
    """
    trail = FakeSourceReadTrail([source_read_record(record_id="r-1")])
    trail.fail_read()

    for call in (trail.recent(), trail.export(), trail.clear()):
        with pytest.raises(ReadTrailError):
            await call


async def test_the_trail_fake_can_be_seeded_with_a_history() -> None:
    """Seeded in the order given, through the same invariants ``record`` applies."""
    trail = FakeSourceReadTrail(
        [
            source_read_record(record_id="r-1", outcome=ReadOutcome.REFUSED),
            source_read_record(record_id="r-2"),
        ]
    )

    assert [row.id for row in await trail.export()] == ["r-1", "r-2"]


# --- the scripts a conforming fake must refuse -------------------------------


@pytest.mark.parametrize(
    "make",
    [FakeSourceReadRecorder, FakeSourceReadTrail],
    ids=["the narrow fake", "the trail fake"],
)
@pytest.mark.parametrize("cap", [0, -1])
def test_neither_fake_admits_a_cap_with_no_meaning(
    make: type[FakeSourceReadRecorder] | type[FakeSourceReadTrail], cap: int
) -> None:
    """ADR-0185 §6's refusal, at construction rather than at the first prune.

    ADR-0077 §1's rule as ADR-0093 §5 quotes it — "A setting the store read would
    refuse must fail at load, not at the first observation" — applied to a fake that
    reads no setting at all: a test that could build a trail with a cap of zero
    could assert against a store no conforming deployment can produce.
    """
    with pytest.raises(ValueError, match="strictly positive"):
        make(max_rows=cap)


def test_the_trail_fake_refuses_a_seeded_history_it_could_not_have_written() -> None:
    """A duplicate id in the seed fails where it was written, not at query time.

    ``FakeReader``'s trade, for its reason: a fake that could be put into a state
    its own contract forbids would let a consumer's test assert against answers no
    real store could give.
    """
    with pytest.raises(ReadTrailError):
        FakeSourceReadTrail(
            [source_read_record(record_id="r-1"), source_read_record(record_id="r-1")]
        )


# --- the default that makes the natural wiring work --------------------------


def test_the_default_source_is_the_default_fake_readers_identity() -> None:
    """The two defaults line up, and that is worth pinning rather than hoping.

    ADR-0185 §2 keys a record on the reader's **declared identity**, so a driver's
    test that wires a :class:`~ai_assistant.testing.FakeReader` beside a recorder
    gets rows naming the reader that produced them only if the two default names
    are the same value. Two defaults that drifted apart would make every such
    assertion read as a mis-recorded source, and the failure would look like a bug
    in the driver rather than in a fixture.
    """
    assert FakeReader().name == DEFAULT_READ_SOURCE
    assert source_read_record().source == DEFAULT_READ_SOURCE

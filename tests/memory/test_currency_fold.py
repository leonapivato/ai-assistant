"""ADR-0109 §5 and §6 under ADR-0328 §7:3: a fold keeps every confirming instant, in both writers.

Every case here runs against **both** ``MemoryIngestor`` and the canonical
``FakeMemoryWriter``, over the same store and the same policy, so the only thing
that varies is the fold. ADR-0109 §9 declines to promote its §5 and §6 to the
``MemoryWriter`` conformance suite while requiring *this* fake to implement them
identically to the ingestor; parameterising one table over the two is how that
obligation is discharged without asserting it of every implementation.

Since ADR-0328 a memory stores no confirming instant: its *as of* is computed on
read, the latest usable confirming instant among its counted ``for`` supports
(§7:3), and a reinforcement only adds the proposal's supports to the target
(§11:6). So ADR-0109 §5's selection is no longer made at the fold but by every
reader, against the reader's own clock — and what this file guards is that neither
writer drops or re-dates a side's support on the way, which is how a fold would
still make a survivor's currency older or invent one.

**Every instant below is distinct, and that is load-bearing** (ADR-0109 §10). A
case whose expected value coincided with the writer's clock or with either side's
``added_at`` would pass against a writer that stamped the wrong one.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    BeliefBand,
    EpisodicMemory,
    Memory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryWriter, FakeTraceSink
from ai_assistant.testing.memories import memory, message_support, remembered_support, said_support

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import MemorySupport

#: The writers' injected clock. Every fold below is decided against *this*, never
#: against a wall clock.
_CLOCK: Final = datetime(2026, 6, 1, tzinfo=UTC)

#: The two ordinary confirming instants, both in the clock's past and distinct
#: from each other, so "the later one" and "the target's" are different answers.
_JANUARY: Final = datetime(2026, 1, 15, tzinfo=UTC)
_MARCH: Final = datetime(2026, 3, 20, tzinfo=UTC)

#: An instant in the writer's future — #741's future-dated ``reported_at``, which
#: ADR-0092 §3 stores unchanged and ADR-0109 §5 refuses to *select*.
_FUTURE: Final = datetime(2027, 2, 11, tzinfo=UTC)

#: When each side's support was added, distinct from every confirming instant and
#: from the clock: ADR-0109 §10's third clause wants a case where a survivor taking
#: transaction time for its currency would be visible.
_TARGET_ADDED: Final = datetime(2026, 2, 2, tzinfo=UTC)
_INCOMING_ADDED: Final = datetime(2026, 4, 4, tzinfo=UTC)

#: The content both memories carry, so retrieval detects the conflict and the fold
#: onto an asserted target is the agreeing one clause 1 admits (ADR-0121 §5).
_CONTENT: Final = "prefers concise emails"

#: The episode every support points into, which the store must hold (ADR-0328 §4:7).
_EPISODE: Final = "episode-1"

#: The band each arm's target stands in. Since ADR-0328 there is one fold, so the
#: arms are kept for ADR-0109 §6's reading of ADR-0103 §9's fourth clause: currency
#: is refreshed "whatever band that record came from".
_ARMS: Final = pytest.mark.parametrize(
    "band",
    [BeliefBand.DERIVED, BeliefBand.ATTESTED, BeliefBand.ASSERTED],
    ids=["derived-target", "attested-target", "asserted-target"],
)

WriterFactory = Callable[["MemoryStore", "MemoryPolicy", "Clock"], "MemoryWriter"]


def _fixed_now() -> datetime:
    return _CLOCK


def _build_ingestor(store: MemoryStore, policy: MemoryPolicy, now: Clock) -> MemoryWriter:
    return MemoryIngestor(traces_sink=FakeTraceSink(), store=store, policy=policy, now=now)


def _build_fake(store: MemoryStore, policy: MemoryPolicy, now: Clock) -> MemoryWriter:
    return FakeMemoryWriter(store=store, policy=policy, now=now)


@pytest.fixture(params=[_build_ingestor, _build_fake], ids=["ingestor", "canonical-fake"])
def make_writer(request: pytest.FixtureRequest) -> WriterFactory:
    """The two fold implementations ADR-0109 §9 requires to agree."""
    factory: WriterFactory = request.param
    return factory


async def _seeded(*memories: Memory, now: Clock = _fixed_now) -> InMemoryMemoryStore:
    """A store holding the episode every support points into, and ``memories``."""
    store = InMemoryMemoryStore(now=now)
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="the exchange the memories rest on",
            occurred_at=_JANUARY,
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, last_updated=_TARGET_ADDED
            ),
        )
    )
    for one in memories:
        await store.add(one)
    return store


def _target(*, confirmed: datetime | None, band: BeliefBand) -> Memory:
    """The stored memory the ruling folds into, its one support confirmed at ``confirmed``.

    Each support takes its confirming instant from its ``when`` (§7:3): a said one,
    a round's message (``ATTESTED``, carrying no source details), or a remember call.
    """
    support: MemorySupport
    match band:
        case BeliefBand.ASSERTED:
            support = said_support(_EPISODE, when=confirmed, added_at=_TARGET_ADDED)
        case BeliefBand.ATTESTED:
            support = message_support(_EPISODE, when=confirmed, added_at=_TARGET_ADDED)
        case BeliefBand.DERIVED:
            support = remembered_support(
                _EPISODE, effect="effect-target", when=confirmed, added_at=_TARGET_ADDED
            )
    return memory("target", _CONTENT, support)


def _incoming(*, confirmed: datetime | None, record_id: str = "incoming") -> Memory:
    """The proposed memory: always ``DERIVED``, on its own remember call."""
    return memory(
        record_id,
        _CONTENT,
        remembered_support(
            _EPISODE, effect=f"effect-{record_id}", when=confirmed, added_at=_INCOMING_ADDED
        ),
    )


def _proposal(record: Memory) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because")


async def _fold(
    make_writer: WriterFactory,
    *,
    target_at: datetime | None,
    incoming_at: datetime | None,
    band: BeliefBand,
    now: Clock = _fixed_now,
) -> Memory:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    The ruling is injected (ADR-0040 §3): these cases are about the applier's fold,
    not about which ruling ``DefaultMemoryPolicy`` would reach (ADR-0159 §12).
    """
    store = await _seeded(_target(confirmed=target_at, band=band), now=now)
    writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), now)

    result = await writer.ingest(_proposal(_incoming(confirmed=incoming_at)))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert isinstance(survivor, Memory)
    assert survivor.band is band
    return survivor


@_ARMS
@pytest.mark.parametrize(
    ("target_at", "incoming_at", "expected"),
    [
        (_JANUARY, _MARCH, _MARCH),
        (_MARCH, _JANUARY, _MARCH),
        (_JANUARY, None, _JANUARY),
        (None, _MARCH, _MARCH),
        (_FUTURE, _JANUARY, _JANUARY),
        (_JANUARY, _FUTURE, _JANUARY),
    ],
    ids=[
        "later-incoming-wins",
        "later-target-wins",
        "target-only-usable",
        "incoming-only-usable",
        "future-target-is-not-usable",
        "future-incoming-is-not-usable",
    ],
)
async def test_the_survivor_is_as_of_the_later_usable_confirming_instant(
    make_writer: WriterFactory,
    *,
    band: BeliefBand,
    target_at: datetime | None,
    incoming_at: datetime | None,
    expected: datetime,
) -> None:
    """ADR-0103 §6's composition, read off the survivor's supports (ADR-0328 §7:3).

    ``later-target-wins`` is the backwards-move guard ADR-0109 §5 names: a proposal
    citing a December episode reinforcing a belief confirmed in January must not make
    the survivor's currency *older*. A writer that replaced the target's supports
    with the incoming one's would fail exactly there.

    The two future-dated cases are #741's example: a future instant is stored
    unchanged (ADR-0092 §3) and is not *usable*, so the January confirmation on the
    other side wins rather than the survivor reading as unknown.
    """
    survivor = await _fold(make_writer, target_at=target_at, incoming_at=incoming_at, band=band)

    assert survivor.as_of(_CLOCK) == expected
    # Not the clock, and not either side's transaction time: a writer stamping the
    # moment of the fold onto the added support's `when` is a reachable mistake.
    assert survivor.as_of(_CLOCK) not in {_CLOCK, _TARGET_ADDED, _INCOMING_ADDED}


@_ARMS
@pytest.mark.parametrize(
    ("target_at", "incoming_at"),
    [(None, None), (_FUTURE, None), (None, _FUTURE), (_FUTURE, _FUTURE)],
    ids=["neither-known", "future-target-only", "future-incoming-only", "both-future"],
)
async def test_the_survivor_is_as_of_unknown_where_neither_instant_is_usable(
    make_writer: WriterFactory,
    *,
    band: BeliefBand,
    target_at: datetime | None,
    incoming_at: datetime | None,
) -> None:
    """ADR-0103 §6's "unknown only where neither is usable".

    ``is None`` exactly: ``None`` is ADR-0103 §9's *unknown*, a distinct state rather
    than a small number. The sibling above is what keeps this from being vacuous.
    """
    survivor = await _fold(make_writer, target_at=target_at, incoming_at=incoming_at, band=band)

    assert survivor.as_of(_CLOCK) is None


@_ARMS
async def test_a_future_instant_is_selected_once_the_readers_clock_passes_it(
    make_writer: WriterFactory, *, band: BeliefBand
) -> None:
    """The selection is the reader's, against the reader's clock (ADR-0328 §7:3).

    Before ADR-0328 the fold selected once and stored the result; now nothing is
    stored, so the same survivor reads as of January today and as of the "future"
    instant once a reader's clock is past it. Both readings, off one stored record,
    prove the fold kept the future-dated support rather than dropping it.
    """
    survivor = await _fold(make_writer, target_at=_FUTURE, incoming_at=_JANUARY, band=band)
    later = _FUTURE.replace(year=_FUTURE.year + 1)

    assert survivor.as_of(_CLOCK) == _JANUARY
    assert survivor.as_of(later) == _FUTURE


async def test_an_accept_installs_the_proposals_own_instant(make_writer: WriterFactory) -> None:
    """Only a ``REINFORCE`` combines supports; an ``ACCEPT`` installs what was proposed.

    ``STORE_TEMPORARY``, the other non-folding install this case once ran, is
    refused since ADR-0328 (§11:7), so the write path has one such install left.
    """
    store = await _seeded()
    writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT), _fixed_now)

    result = await writer.ingest(_proposal(_incoming(confirmed=_MARCH)))

    assert result.decision.kind is MemoryDecisionKind.ACCEPT
    stored = await store.get("incoming")
    assert isinstance(stored, Memory)
    assert stored.as_of(_CLOCK) == _MARCH


async def test_a_supersede_carries_the_correction_and_inherits_nothing(
    make_writer: WriterFactory,
) -> None:
    """A ``SUPERSEDE`` takes the proposal's instant and none of the target's.

    ADR-0040 §5a's "carries nothing of the target onto the surviving record",
    applied to currency (ADR-0109 §6): a superseding proposal states a **different
    belief**, so the retired memory's confirmation is not evidence about it.

    The retirement half is the other clause: the end adds the correction's support
    to the retired memory as an ``against`` one (ADR-0328 §5:4), which no ``as of``
    counts, so the retired memory still reads as of the instant it was confirmed. It
    is read back through ``export``, which returns retired memories (ADR-0045 §6).
    """
    stale = memory(
        "stale",
        "user prefers morning meetings",
        remembered_support(_EPISODE, effect="effect-stale", when=_JANUARY),
    )
    store = await _seeded(stale)
    # A user assertion contradicting a derived belief is what `DefaultMemoryPolicy`
    # rules `SUPERSEDE` on (ADR-0038 §1), so the ruling is the policy's rather than a
    # fake's.
    correction = memory(
        "correction", "user prefers afternoon meetings", said_support(_EPISODE, when=_MARCH)
    )
    writer = make_writer(store, DefaultMemoryPolicy(), _fixed_now)

    result = await writer.ingest(_proposal(correction))

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    new_id = result.record_id
    assert new_id is not None
    exported = {record.id: record for record in await store.export()}
    replacement, retired = exported[new_id], exported["stale"]
    assert isinstance(replacement, Memory)
    assert isinstance(retired, Memory)
    assert replacement.as_of(_CLOCK) == _MARCH
    assert retired.as_of(_CLOCK) == _JANUARY

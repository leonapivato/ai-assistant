"""ADR-0109 §5 and §6: the fold selects the confirming instant, in both writers.

Every case here runs against **both** ``MemoryIngestor`` and the canonical
``FakeMemoryWriter``, over the same store and the same policy, so the only thing
that varies is the fold. ADR-0109 §9 declines to promote its §5 and §6 to the
``MemoryWriter`` conformance suite — ADR-0040 §5a's "a writer that combines
confidence differently conforms, and must" would become false, and ADR-0028 §8's
exclusion would be void — while requiring *this* fake to implement them
identically to the ingestor. Parameterising one table over the two is how that
obligation is discharged without asserting it of every implementation: a third
writer is free to compose currency differently and is not run here.

**Every instant below is distinct, and that is load-bearing** (ADR-0109 §10). A
case whose expected value coincided with the injected clock's reading, with the
other record's value, or with either ``last_updated`` would pass against a fold
that read the wrong one. :data:`_REPORTED_AT` is distinct for the same reason on
the corroboration arm: the target's attestation is an instant the fold could have
reached for instead of ``last_confirmed_at``, and a fixture that made the two
equal would not notice.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    MAX_EVIDENCE_CITATIONS,
    Attestation,
    EpisodicMemory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryWriter, FakeTraceSink

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import MemoryRecord

#: The writers' injected clock. Every fold below is decided against *this*, never
#: against a wall clock — which is what makes the future-dated cases deterministic
#: instead of a date the suite outlives (ADR-0109 §5's last clause).
_CLOCK: Final = datetime(2026, 6, 1, tzinfo=UTC)

#: The two ordinary confirming instants, both in the clock's past and distinct
#: from each other, so "the later one" and "the target's" are different answers.
_JANUARY: Final = datetime(2026, 1, 15, tzinfo=UTC)
_MARCH: Final = datetime(2026, 3, 20, tzinfo=UTC)

#: An instant in the writer's future — #741's future-dated ``reported_at``, which
#: ADR-0092 §3 stores unchanged and ADR-0109 §5 refuses to *select*.
_FUTURE: Final = datetime(2027, 2, 11, tzinfo=UTC)

#: Transaction time on each side (ADR-0045 §3), distinct from every confirming
#: instant and from the clock: ADR-0109 §10's third clause wants at least one fold
#: case where a survivor taking `last_updated` for its currency would be visible.
_TARGET_UPDATED: Final = datetime(2026, 2, 2, tzinfo=UTC)
_INCOMING_UPDATED: Final = datetime(2026, 4, 4, tzinfo=UTC)

#: The attested target's ``Attestation.reported_at``. Deliberately *not* its
#: ``last_confirmed_at``: a corroborated survivor keeps the target's attestation
#: while its instant may be the incoming derived record's (ADR-0103 §6), so the
#: two fields legitimately disagree and the fold must read the right one
#: (ADR-0109 §8, §11).
_REPORTED_AT: Final = datetime(2025, 11, 9, tzinfo=UTC)

#: The content both records carry, so retrieval detects the conflict.
_CONTENT: Final = "prefers concise emails"

#: The episode a well-formed `DERIVED` proposal must cite, and which the store
#: must be holding for the ingestor to accept it (ADR-0077 §5).
_EPISODE: Final = "episode-1"

#: Builds a writer over a store, a policy and a clock. The clock is a parameter
#: rather than a constant because ADR-0109 §5's usability test *is* a clock read:
#: the case that moves it is what proves the earlier cases turned on it.
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


async def _plant_episodes(store: MemoryStore, *episodes: EpisodicMemory) -> None:
    for record in episodes:
        await store.add(record)


def _episode(episode_id: str, occurred_at: datetime) -> EpisodicMemory:
    return EpisodicMemory(
        id=episode_id,
        content=f"the exchange {episode_id} records",
        occurred_at=occurred_at,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.6, last_updated=_TARGET_UPDATED
        ),
    )


def _target(
    *,
    last_confirmed_at: datetime | None,
    corroborating: bool,
    record_id: str = "target",
) -> MemoryRecord:
    """The stored record the ruling folds into, on whichever arm the case wants.

    ``corroborating`` selects ADR-0103 §6's pairing — an ``ATTESTED`` target under
    a ``DERIVED`` proposal — where the survivor is the *target* wearing a new
    provenance. Anything else is the ordinary arm, where the survivor is the
    incoming record wearing the target's id. ADR-0109 §6 rules the instant
    identically on both, which is what running every case over the pair checks.
    """
    source = MemorySource.EXTERNAL if corroborating else MemorySource.OBSERVED
    return PreferenceMemory(
        id=record_id,
        content=_CONTENT,
        preference=_CONTENT,
        provenance=Provenance(
            source=source,
            confidence=0.6,
            last_updated=_TARGET_UPDATED,
            attestation=(
                Attestation(reported_by="calendar:work", reported_at=_REPORTED_AT)
                if corroborating
                else None
            ),
            last_confirmed_at=last_confirmed_at,
        ),
    )


def _incoming(
    *,
    last_confirmed_at: datetime | None,
    evidence: tuple[str, ...] = (_EPISODE,),
    record_id: str = "incoming",
) -> MemoryRecord:
    """The proposed record. Always ``DERIVED``, so either arm is reachable."""
    return PreferenceMemory(
        id=record_id,
        content=_CONTENT,
        preference=_CONTENT,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            evidence=evidence,
            last_updated=_INCOMING_UPDATED,
            last_confirmed_at=last_confirmed_at,
        ),
    )


def _believed(
    record_id: str,
    content: str,
    *,
    source: MemorySource,
    confidence: float,
    last_confirmed_at: datetime | None,
) -> MemoryRecord:
    """A preference at arbitrary content, for the cases that are not folds."""
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=Provenance(
            source=source,
            confidence=confidence,
            last_updated=_INCOMING_UPDATED,
            last_confirmed_at=last_confirmed_at,
        ),
    )


def _proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because")


async def _fold(
    make_writer: WriterFactory,
    *,
    target_at: datetime | None,
    incoming_at: datetime | None,
    corroborating: bool,
) -> MemoryRecord:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    End to end rather than through ``_merge``: the rule ADR-0109 §5 states is
    about what is *stored*, and both writers reach their fold through a policy
    ruling and an install. A unit call on either private function would also have
    to be written twice, which is the drift this file exists to catch.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await _plant_episodes(store, _episode(_EPISODE, _JANUARY))
    await store.add(_target(last_confirmed_at=target_at, corroborating=corroborating))

    writer = make_writer(store, DefaultMemoryPolicy(), _fixed_now)
    result = await writer.ingest(_proposal(_incoming(last_confirmed_at=incoming_at)))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert survivor is not None
    # The arm actually taken, asserted rather than assumed: both arms leave a
    # record at the target's id, so a `corroboration-arm` case that silently ran
    # the ordinary one would pass every currency assertion below while checking
    # half of what ADR-0109 §6 rules. `source` is the discriminator, because the
    # corroboration arm keeps the target's and the ordinary arm takes the
    # incoming record's (ADR-0103 §6).
    expected_source = MemorySource.EXTERNAL if corroborating else MemorySource.OBSERVED
    assert survivor.provenance.source is expected_source
    return survivor


_ARMS: Final = pytest.mark.parametrize(
    "corroborating", [False, True], ids=["ordinary-arm", "corroboration-arm"]
)


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
async def test_the_fold_takes_the_later_usable_confirming_instant(
    make_writer: WriterFactory,
    *,
    corroborating: bool,
    target_at: datetime | None,
    incoming_at: datetime | None,
    expected: datetime,
) -> None:
    """ADR-0103 §6's composition, over the stored field (ADR-0109 §5).

    The later of the two records' **usable** instants, and the usable one where
    only one is usable. Four of the six cases would pass under a fold that simply
    took the incoming record's value; ``later-target-wins`` is the one that would
    not, and it is the backwards-move guard ADR-0109 §5 names — a proposal citing a
    December episode reinforcing a belief confirmed in January must not make the
    survivor's currency *older*. "A confirmation we do hold is not unmade" is
    ADR-0103 §6's own sentence, and it reads identically about the merely-older
    case as about the unknown one.

    The two future-dated cases are #741's example with teeth. A future instant is
    stored unchanged by its producer (ADR-0092 §3) and is not *usable*, so the
    January confirmation on the other side wins. A fold selecting "the later
    present value" takes the future one and makes the survivor unknown with a
    perfectly good confirmation in hand — the manufactured staleness ADR-0103 §6
    and ADR-0103 §9 both refuse, which is the whole reason this fold takes a clock.

    Run on both arms because ADR-0109 §6 reads ADR-0103 §9's fourth clause
    generally: "whatever band that record came from" is vacuous under ADR-0103 §6's
    pairing alone, and a same-band rule that withheld currency would age a belief
    re-observed every week exactly as fast as one nobody has seen since.
    """
    survivor = await _fold(
        make_writer,
        target_at=target_at,
        incoming_at=incoming_at,
        corroborating=corroborating,
    )

    assert survivor.provenance.last_confirmed_at == expected
    # Not the clock, and not either side's transaction time. ADR-0109 §5's second
    # clause forbids writing the moment of the fold, and ADR-0103 §9 forbids
    # reading currency off transaction time at all; both are reachable mistakes
    # that every case above would otherwise pass through.
    assert survivor.provenance.last_confirmed_at not in {
        _CLOCK,
        _TARGET_UPDATED,
        _INCOMING_UPDATED,
    }


@_ARMS
@pytest.mark.parametrize(
    ("target_at", "incoming_at"),
    [(None, None), (_FUTURE, None), (None, _FUTURE), (_FUTURE, _FUTURE)],
    ids=["neither-known", "future-target-only", "future-incoming-only", "both-future"],
)
async def test_the_fold_yields_unknown_where_neither_instant_is_usable(
    make_writer: WriterFactory,
    *,
    corroborating: bool,
    target_at: datetime | None,
    incoming_at: datetime | None,
) -> None:
    """ADR-0103 §6's "unknown only where neither is usable" (ADR-0109 §5).

    ``is None`` exactly, never merely falsy: ``None`` is ADR-0103 §9's *unknown*,
    which is a distinct state rather than a small number, and a surface that read
    it as either fresh or stale would be making a claim nobody measured.

    The sibling the test above provides is what keeps this from being vacuous
    (ADR-0109 §10): ``is None`` alone passes against a fold that never writes the
    field at all, and the concrete cases run the same path and would fail there.

    A *future* instant reaching unknown is the deliberate half. The value is not
    rewritten and not refused — the producer stored what the source said
    (ADR-0092 §3) — it is simply not selectable, so with nothing usable opposite it
    the survivor honestly says the store does not know.
    """
    survivor = await _fold(
        make_writer,
        target_at=target_at,
        incoming_at=incoming_at,
        corroborating=corroborating,
    )

    assert survivor.provenance.last_confirmed_at is None


@_ARMS
async def test_a_future_instant_is_not_promoted_when_the_clock_passes_it(
    make_writer: WriterFactory, *, corroborating: bool
) -> None:
    """The selection is made once, at the fold (ADR-0109 §5).

    The same pair of records, folded by a writer whose clock is *past* the
    "future" instant, selects it — which is what proves the previous cases turned
    on the injected clock rather than on the value being unusual. Nothing else in
    the fixture moved, so a fold reading a module-level wall clock, or no clock at
    all, cannot produce both outcomes.
    """
    later = _FUTURE.replace(year=_FUTURE.year + 1)
    store = InMemoryMemoryStore(now=lambda: later)
    await _plant_episodes(store, _episode(_EPISODE, _JANUARY))
    await store.add(_target(last_confirmed_at=_FUTURE, corroborating=corroborating))

    writer = make_writer(store, DefaultMemoryPolicy(), lambda: later)
    result = await writer.ingest(_proposal(_incoming(last_confirmed_at=_JANUARY)))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert survivor is not None
    assert survivor.provenance.last_confirmed_at == _FUTURE


async def test_the_citation_bound_displaces_citations_and_not_the_instant(
    make_writer: WriterFactory,
) -> None:
    """The case ADR-0109 exists to decide (#744, PR #742's finding 2).

    The incoming record carries one citation more than
    :data:`MAX_EVIDENCE_CITATIONS`, in an accumulation order that is **not**
    ``occurred_at`` order: its oldest-accumulated citation is the episode holding
    the *latest* instant, so ADR-0086 §3's bound displaces exactly that one. A
    resolver — "the latest ``occurred_at`` among the citations the record still
    carries" — would answer with a strictly earlier instant, and could never
    recover the displaced one, because ``evidence_elided`` retains a count and
    never an id (ADR-0086 §4).

    The stored field answers ``_MARCH``, because it was computed by the producer
    while the confirming event was in hand — *before* the bound could apply. The
    two assertions together are what make the point: the instant survived **and**
    the displacement really happened. Either alone is satisfiable by a fixture
    where the bound never bit.

    ADR-0086 §3 is untouched by this: the bound displaces exactly what it always
    displaced, and ADR-0103 §1's promise not to disturb it holds. What changed is
    what *depends* on the retained tuple, which is now nothing.
    """
    overflow = MAX_EVIDENCE_CITATIONS + 1
    # `ep-00` is accumulated first and so is displaced first, and it is the one
    # carrying `_MARCH`. Every other episode is older, so the retained tuple's
    # latest instant is strictly earlier than the answer.
    episodes = [
        _episode(f"ep-{index:02d}", _MARCH if index == 0 else _JANUARY) for index in range(overflow)
    ]
    store = InMemoryMemoryStore(now=_fixed_now)
    await _plant_episodes(store, *episodes)
    await store.add(_target(last_confirmed_at=None, corroborating=False))

    writer = make_writer(store, DefaultMemoryPolicy(), _fixed_now)
    result = await writer.ingest(
        _proposal(
            _incoming(
                last_confirmed_at=_MARCH,
                evidence=tuple(record.id for record in episodes),
            )
        )
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert survivor is not None
    # The instant the producer measured, intact.
    assert survivor.provenance.last_confirmed_at == _MARCH
    # ...and the displacement that would have destroyed it under a resolver.
    assert len(survivor.provenance.evidence) == MAX_EVIDENCE_CITATIONS
    assert "ep-00" not in survivor.provenance.evidence
    assert survivor.provenance.evidence_elided == 1
    retained = {record.id: record.occurred_at for record in episodes}
    assert max(retained[cited] for cited in survivor.provenance.evidence) == _JANUARY


@pytest.mark.parametrize(
    "kind",
    [MemoryDecisionKind.ACCEPT, MemoryDecisionKind.STORE_TEMPORARY],
    ids=["accept", "store-temporary"],
)
async def test_a_non_folding_install_carries_the_proposals_own_instant(
    make_writer: WriterFactory, kind: MemoryDecisionKind
) -> None:
    """Only a ``REINFORCE`` composes; these install what was proposed (ADR-0109 §6).

    Enumerated rather than left to the reader, in the shape ADR-0086 §4 used for
    ``evidence_elided``'s recurrence and for its reason: stating the rule over
    every install is what stops a non-fold case quietly inventing or dropping a
    value. ``STORE_TEMPORARY`` rewrites ``expires_at`` on its way through, so it is
    the install most able to lose a field it does not name.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await _plant_episodes(store, _episode(_EPISODE, _JANUARY))

    writer = make_writer(store, FakeMemoryPolicy(kind), _fixed_now)
    result = await writer.ingest(_proposal(_incoming(last_confirmed_at=_MARCH)))

    assert result.decision.kind is kind
    stored = await store.get("incoming")
    assert stored is not None
    assert stored.provenance.last_confirmed_at == _MARCH


async def test_a_supersede_carries_the_correction_and_inherits_nothing(
    make_writer: WriterFactory,
) -> None:
    """A ``SUPERSEDE`` takes the proposal's instant and none of the target's.

    ADR-0040 §5a's "carries nothing of the target onto the surviving record",
    applied to this field (ADR-0109 §6). The asymmetry with ``evidence_elided`` is
    real and follows from what each field is: an elision count is a fact about a
    record's *history*, so it sums over an install's sources; a confirming instant
    is a fact about the *world*, so it is selected rather than accumulated, and a
    superseding proposal states a **different belief** — the retired record's
    confirmation is not evidence about it.

    The retirement half is the other clause: closing a window asserts nothing new
    about the warrant, so the retired record keeps the instant it was stored with
    (ADR-0080 §1). It is read back through ``export``, which returns records whose
    window is closed (ADR-0045 §6) — ``get`` will not, because the record is off
    the read path, which is the point of the retirement.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(
        _believed(
            "stale",
            "user prefers morning meetings",
            source=MemorySource.OBSERVED,
            confidence=0.6,
            last_confirmed_at=_JANUARY,
        )
    )

    # A user assertion contradicting a derived belief is what `DefaultMemoryPolicy`
    # rules `SUPERSEDE` on (ADR-0038 §1), so the ruling is the policy's rather than
    # a fake's: the two records have to be near enough for retrieval to surface the
    # conflict and different enough to be a contradiction.
    correction = _believed(
        "correction",
        "user prefers afternoon meetings",
        source=MemorySource.USER_ASSERTED,
        confidence=1.0,
        last_confirmed_at=_MARCH,
    )
    writer = make_writer(store, DefaultMemoryPolicy(), _fixed_now)
    result = await writer.ingest(_proposal(correction))

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    new_id = result.record_id
    assert new_id is not None
    exported = {record.id: record for record in await store.export()}
    # The correction, at its fresh id, states its own confirming instant.
    assert exported[new_id].provenance.last_confirmed_at == _MARCH
    # The retired record is unedited — a retirement is not an install.
    assert exported["stale"].provenance.last_confirmed_at == _JANUARY

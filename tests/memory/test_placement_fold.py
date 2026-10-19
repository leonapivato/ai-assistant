"""ADR-0217 §3: the fold's meet, its eligibility, and the instant it carries.

ADR-0204 §5's ratchet — "the stamp never clears, and a supersession carries neither
way" — restated over the field ADR-0217 §1 moved it to and generalised from a
disjunction to a **meet**. The shape ``test_taint_fold.py`` established for ADR-0106
§4 and ``test_currency_fold.py`` for ADR-0109 §5: every case runs against **both**
``MemoryIngestor`` and the canonical ``FakeMemoryWriter``, over the same store and
the same policy, so the only thing that varies is the writer's own composition of the
survivor.

**Not promoted to the ``MemoryWriter`` conformance suite**, for the reason ADR-0106
§10 gives about its own field: ADR-0028 §8 and ADR-0040 §5a keep the fold's
composition rules off that contract, so a third writer stays free to compose
differently and is not run here. What the *canonical fake* owes is not to launder —
a fold that kept one side's placement would quietly discard the other's, widening a
narrowed target on the first unnarrowed reinforcement. That is production's
laundering path performed by the object a consumer reaches for instead of
`memory`'s internals.

**Both positions and every arm** (:data:`_ARM_TARGET`), for ADR-0106 §10's reason
transferred whole: a case in either position alone passes an implementation that
simply copies that side.

**What is *not* here is the half §11 orders later.** ADR-0217 §10 pins several of
these arms beside "a later ``unguard`` on the survivor succeeds" / "writes nothing",
because the setter is only observable to the owner through what they may then do.
``guard`` and ``unguard`` are §7's two acts, which §11 places after #248's
conditional write and after this change; the arms below pin the recorded setter
itself, and the acts lane pins what the owner may then do with it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    EpisodicMemory,
    Memory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
)
from ai_assistant.memory import InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryWriter, FakeTraceSink
from ai_assistant.testing.memories import memory, memory_in_band, remembered_support

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter

_CLOCK: Final = datetime(2026, 6, 1, tzinfo=UTC)
_WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: Two distinct narrowing instants, both well before ``_CLOCK`` — so an
#: implementation that stamped *the fold's own* instant is caught by the value and
#: not merely by the ordering (ADR-0217 §3).
_EARLY: Final = datetime(2026, 2, 1, tzinfo=UTC)
_LATE: Final = datetime(2026, 3, 1, tzinfo=UTC)

#: The content both records carry, so retrieval detects the conflict.
_CONTENT: Final = "prefers concise emails"

#: The episode the proposal cites, which the store must hold for the ingestor to
#: accept it at all (ADR-0077 §5).
_EPISODE: Final = "episode-1"

#: The id a supersession's correction is minted at, scripted so the case can name
#: both records rather than discovering one (ADR-0045 §4's "freshly-minted id").
_CORRECTION: Final = "corrected"

#: The four placements every case below is built out of, one per row of ADR-0217
#: §1's table that a *stored* record can carry.
_DEFAULT: Final = Placement()
_DERIVED: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_EARLY
)
_PROPOSED: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_LATE
)
_GUARDED: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_LATE
)
_UNGUARDED: Final = Placement(
    reach=PlacementReach.ANYONE, set_by=PlacementSetter.OWNER_ACT, set_at=_LATE
)
#: What ADR-0217 §9's decode produces for a record written under ADR-0204: narrowed,
#: by the derivation, at an instant nobody recorded.
_LEGACY: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED)

#: The band each arm's target stands in, and therefore the discriminator that says
#: which arm a case actually took. Since ADR-0328 there is one fold — the proposal's
#: supports added to the target (§11:6), with placement's ratchet applied as on any
#: fold (§11:9) — so the arms are kept for what ADR-0217 §3 says over every fold:
#: whatever the target's band, the meet holds.
#:
#: **The asserted arm is reached through clause 1's agreeing-fold exception**
#: (ADR-0121 §5 as widened by ADR-0214 §3), which is why every case below folds
#: content the target already carries.
_ORDINARY: Final = "ordinary"
_ATTESTED: Final = "attested"
_ASSERTED: Final = "asserted"

_ARM_TARGET: Final = {
    _ORDINARY: BeliefBand.DERIVED,
    _ATTESTED: BeliefBand.ATTESTED,
    _ASSERTED: BeliefBand.ASSERTED,
}

WriterFactory = Callable[
    ["MemoryStore", "MemoryPolicy", "Clock", Callable[[], str]], "MemoryWriter"
]


def _fixed_now() -> datetime:
    return _CLOCK


def _build_ingestor(
    store: MemoryStore, policy: MemoryPolicy, now: Clock, id_factory: Callable[[], str]
) -> MemoryWriter:
    return MemoryIngestor(
        traces_sink=FakeTraceSink(), store=store, policy=policy, now=now, id_factory=id_factory
    )


def _build_fake(
    store: MemoryStore, policy: MemoryPolicy, now: Clock, id_factory: Callable[[], str]
) -> MemoryWriter:
    return FakeMemoryWriter(store=store, policy=policy, now=now, id_factory=id_factory)


@pytest.fixture(params=[_build_ingestor, _build_fake], ids=["ingestor", "canonical-fake"])
def make_writer(request: pytest.FixtureRequest) -> WriterFactory:
    """The two folds a consumer may be looking at, held to the same rule."""
    factory: WriterFactory = request.param
    return factory


def _target(*, placement: Placement, arm: str, content: str = _CONTENT) -> Memory:
    """The stored memory the ruling folds into, in the band the case's arm names."""
    return memory_in_band(
        "target",
        content,
        _ARM_TARGET[arm],
        attestation=Attestation(reported_by="calendar:work", reported_at=_WHEN),
        episode=_EPISODE,
        placement=placement,
    )


def _incoming(*, placement: Placement, record_id: str = "incoming") -> Memory:
    """The proposed memory: always ``DERIVED``, on its own remember call.

    Its wording is always :data:`_CONTENT`; what the supersession case varies is the
    **target's** wording, because a proposal that agrees with its target *restates*
    it under ADR-0121 §1 and ADR-0159 §5 refuses to retire a conflict so related.
    """
    return memory(
        record_id,
        _CONTENT,
        remembered_support(_EPISODE, effect=f"effect-{record_id}"),
        placement=placement,
    )


async def _seeded(target: Memory) -> InMemoryMemoryStore:
    """A store holding the cited episode and ``target``."""
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="the exchange the proposal stands on",
            occurred_at=_WHEN,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
        )
    )
    await store.add(target)
    return store


async def _fold(
    make_writer: WriterFactory,
    *,
    target: Placement,
    incoming: Placement,
    arm: str = _ORDINARY,
) -> Memory:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    End to end rather than through the fold's helper: §5's clause is about what is
    *stored*, and a unit call on either private function would have to be written
    twice — which is the drift running both writers exists to catch.
    """
    store = await _seeded(_target(placement=target, arm=arm))
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(proposed=_incoming(placement=incoming), rationale="because")
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert isinstance(survivor, Memory)
    # The arm actually taken, asserted rather than assumed: the band is computed from
    # the supports, and a reinforcement only adds (ADR-0328 §6:3, §11:6).
    assert survivor.band is _ARM_TARGET[arm]
    return survivor


_ARMS: Final = pytest.mark.parametrize(
    "arm",
    [_ORDINARY, _ATTESTED, _ASSERTED],
    ids=["ordinary-arm", "attested-corroboration-arm", "asserted-corroboration-arm"],
)


# --- ADR-0204 §8's arms, restated over reach OWNER (ADR-0217 §10) ------------


@_ARMS
@pytest.mark.parametrize(
    ("target", "incoming"),
    [(_DERIVED, _DEFAULT), (_DEFAULT, _DERIVED), (_DERIVED, _DERIVED)],
    ids=["narrowed-target", "narrowed-incoming", "both-narrowed"],
)
async def test_a_fold_combining_a_narrowed_side_is_narrowed(
    make_writer: WriterFactory,
    *,
    target: Placement,
    incoming: Placement,
    arm: str,
) -> None:
    """ADR-0204 §8 case 7, over the meet: the survivor is narrowed, in both orders.

    ADR-0106 §4's ratchet argument, which ADR-0204 §5 takes by citation: "a tainted
    belief reinforced by a clean observation stays tainted. Without that, the
    laundering the marker exists to stop simply moves one step along." Here the step
    along is a narrowed episode reinforced once by an unnarrowed proposal, after
    which a channel of unbounded audience is handed the record ADR-0217 §2 withholds.
    """
    survivor = await _fold(make_writer, target=target, incoming=incoming, arm=arm)

    assert survivor.placement.reach is PlacementReach.OWNER
    assert survivor.placement.set_by is PlacementSetter.DERIVED


@_ARMS
async def test_a_fold_of_two_unnarrowed_records_stays_unnarrowed(
    make_writer: WriterFactory, *, arm: str
) -> None:
    """The negative control, without which the cases above pass a hardcoded ``OWNER``.

    It is also the claim ADR-0217 §1 makes about an absent setter on a post-field
    record: a measurement rather than a ratchet that starts on. A fold that narrowed
    records neither of which was narrowed would withhold every reinforced belief from
    the spoken channel, which is milestone 19's exit test failing by a second route
    (ADR-0217 §6).
    """
    survivor = await _fold(make_writer, target=_DEFAULT, incoming=_DEFAULT, arm=arm)

    assert survivor.placement == _DEFAULT


@pytest.mark.parametrize(
    ("target", "incoming"),
    [(_DERIVED, _DEFAULT), (_DEFAULT, _DERIVED)],
    ids=["narrowed-target", "narrowed-proposal"],
)
async def test_a_supersession_writes_the_proposals_placement_beside_a_retained_target(
    make_writer: WriterFactory, *, target: Placement, incoming: Placement
) -> None:
    """ADR-0204 §8 case 15, over the placement: two records, two ids, both directions.

    ADR-0040 §5a's differential and ADR-0045 §4's retention, pinned together with §5's
    third and fourth clauses so neither can be implemented at the other's expense. A
    ``SUPERSEDE`` is not an operation on the narrowed record's placement at all: the
    correction carries what its **own** producer was supplied and nothing of the
    target's, and the target is not written to — it is retained with a closed validity
    window, still carrying its own placement, and stays withheld from a channel of
    unbounded audience for as long as it is in the store.

    A ratchet that made the correction inherit its target's placement would contradict
    the differential; one that widened the target's would contradict the retention.
    Both directions are asserted, so neither is satisfiable by the other's rule.
    """
    store = await _seeded(
        _target(
            placement=target,
            arm=_ORDINARY,
            content="prefers concise emails, an older note",
        )
    )
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(
            proposed=_incoming(placement=incoming, record_id="new"),
            rationale="because",
        )
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert result.record_id == _CORRECTION
    stored = {record.id: record for record in await store.export()}
    assert {"target", _CORRECTION} <= set(stored), "two records, at distinct ids"
    retained = stored["target"]
    assert retained.validity.valid_until is not None, "the target is retained, not edited"
    assert retained.placement == target
    correction = stored[_CORRECTION]
    assert correction.validity.valid_until is None, "the correction is live"
    assert correction.placement == incoming


# --- ADR-0217 §3: the setter propagates, and it is not the fold's -----------


@pytest.mark.parametrize(
    ("target", "incoming", "expected"),
    [
        pytest.param(_DEFAULT, _PROPOSED, _PROPOSED, id="a proposal narrows an unnarrowed record"),
        pytest.param(_DEFAULT, _DERIVED, _DERIVED, id="a derivation narrows it as DERIVED"),
        pytest.param(
            _GUARDED,
            _PROPOSED,
            _GUARDED,
            id="an act outranks a proposal at the same reach",
        ),
        pytest.param(
            _DERIVED,
            _GUARDED.model_copy(update={"set_at": _EARLY}),
            _DERIVED,
            id="a derivation outranks an act at the same reach",
        ),
        pytest.param(
            _UNGUARDED,
            _PROPOSED,
            _UNGUARDED,
            id="an unguarded record is not re-narrowed by a proposal",
        ),
        pytest.param(
            _UNGUARDED,
            _DERIVED,
            _DERIVED,
            id="a derivation is eligible against an act, and an act does not lift one",
        ),
        pytest.param(
            _GUARDED,
            _DEFAULT,
            _GUARDED,
            id="a duplicate does not dilute a guard",
        ),
        pytest.param(
            _LEGACY,
            _DEFAULT,
            _LEGACY,
            id="a decoded legacy narrowing keeps its unknown instant",
        ),
    ],
)
async def test_the_fold_records_the_surviving_setter_and_its_own_instant(
    make_writer: WriterFactory, *, target: Placement, incoming: Placement, expected: Placement
) -> None:
    """ADR-0217 §3's propagation over the fold, arm by arm, on the ingestion path.

    The reach alone is not the claim: an implementation that returned the right reach
    with the wrong setter would pass every ADR-0204 arm above while leaving the owner
    unable to lift what a model proposed, or able to lift what a derivation wrote.
    Three arms take **differing reaches**, which the same-reach arms cannot reach and
    which §3's eligibility clause exists for — a record the owner has *unguarded*
    folded with a fresh proposal survives unguarded, so a model cannot undo an act by
    duplication, while the same stored side folded with a derivation survives narrowed
    because an act does not lift one.

    The survivor's ``set_at`` is the **winning side's** and never ``_CLOCK``, the
    instant of the fold: the stamp names when the placement was set, not when a
    duplicate was merged. The legacy arm is why that matters most — without it an
    implementation could satisfy every other arm by stamping the fold's own instant,
    which would assert a time for a narrowing nobody timed and turn §1's *unknown*
    into a false measurement.
    """
    survivor = await _fold(make_writer, target=target, incoming=incoming)

    assert survivor.placement == expected
    assert survivor.placement.set_at != _CLOCK, "the fold mints no instant of its own"

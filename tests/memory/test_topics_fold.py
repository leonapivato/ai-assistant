"""ADR-0213 §8: the fold unions, the bound retains, and a supersession carries nothing.

``test_withheld_fold.py``'s shape, applied to the field ADR-0213 §1 adds to the
envelope rather than to the warrant: every case runs against **both**
``MemoryIngestor`` and the canonical ``FakeMemoryWriter``, over the same store and
the same policy, so the only thing that varies is the writer's own composition of
the survivor.

**Both positions and every arm**, for ADR-0106 §10's reason transferred whole:
``_merge`` reads most of the survivor from one side, so a case in either position
alone passes an implementation that simply copies that side. §12.15 names the
direction that has to be exercised — a **labelled target reinforced by an
unlabelled incoming** — because the majority style, ``incoming.…``, drops the
target's labels there and passes the opposite direction with full marks.

**Not promoted to the ``MemoryWriter`` conformance suite**, for the reason its
sibling gives: ADR-0028 §8 and ADR-0040 §5a keep the fold's composition rules off
that contract. What the canonical fake owes is not to launder — §8's guarantee is
that no fold drops a label the target carried, and a double that took the incoming
tuple would make a health-scoped act stop reaching a record on its first
reinforcement, with nothing about the survivor looking wrong afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    MAX_TOPICS_PER_RECORD,
    Attestation,
    EpisodicMemory,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
)
from ai_assistant.memory import InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryWriter, FakeTraceSink

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import MemoryRecord

_CLOCK: Final = datetime(2026, 6, 1, tzinfo=UTC)
_WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)
_CONTENT: Final = "prefers concise emails"
_EPISODE: Final = "episode-1"
_CORRECTION: Final = "corrected"

_ORDINARY: Final = "ordinary"
_ATTESTED: Final = "attested"
_ASSERTED: Final = "asserted"

#: The source each arm's target carries, and therefore the discriminator that says
#: which arm a case actually took: every arm leaves a record at the target's id, so
#: a corroboration case that silently ran the ordinary one would check half of §8.
_ARM_TARGET: Final = {
    _ORDINARY: MemorySource.OBSERVED,
    _ATTESTED: MemorySource.EXTERNAL,
    _ASSERTED: MemorySource.USER_ASSERTED,
}

#: A full set of labels at the bound, for the overflow cases. Zero-padded so code
#: point order and numeric order agree, which is what lets a case name the label it
#: expects to be admitted rather than computing one.
_AT_BOUND: Final = tuple(f"topic {index:02d}" for index in range(MAX_TOPICS_PER_RECORD))

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


def _target(*, topics: tuple[str, ...], arm: str, content: str = _CONTENT) -> MemoryRecord:
    """The stored record the ruling folds into, on whichever arm the case wants."""
    source = _ARM_TARGET[arm]
    return PreferenceMemory(
        id="target",
        content=content,
        preference=content,
        topics=topics,
        provenance=Provenance(
            source=source,
            confidence=1.0 if arm == _ASSERTED else 0.6,
            last_updated=_WHEN,
            attestation=(
                Attestation(reported_by="calendar:work", reported_at=_WHEN)
                if arm == _ATTESTED
                else None
            ),
        ),
    )


def _incoming(
    *, topics: tuple[str, ...], record_id: str = "incoming", preference: str = _CONTENT
) -> MemoryRecord:
    """The proposed record. Always ``DERIVED``, so either arm is reachable."""
    return PreferenceMemory(
        id=record_id,
        content=_CONTENT,
        preference=preference,
        topics=topics,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            evidence=(_EPISODE,),
            last_updated=_WHEN,
        ),
    )


async def _seeded(target: MemoryRecord) -> InMemoryMemoryStore:
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
    target_topics: tuple[str, ...],
    incoming_topics: tuple[str, ...],
    arm: str,
) -> MemoryRecord:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    End to end rather than through ``_merge``: §8's clause is about what is
    *installed*, and the bound of §1 is applied at the seam after the fold — so a
    unit call on either private function would measure half the rule, twice.
    """
    store = await _seeded(_target(topics=target_topics, arm=arm))
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(proposed=_incoming(topics=incoming_topics), rationale="because")
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert survivor is not None
    assert survivor.provenance.source is _ARM_TARGET[arm]
    return survivor


_ARMS: Final = pytest.mark.parametrize(
    "arm",
    [_ORDINARY, _ATTESTED, _ASSERTED],
    ids=["ordinary-arm", "attested-corroboration-arm", "asserted-corroboration-arm"],
)


# --- §12.15: the union, on both arms and in both positions ------------------


@_ARMS
async def test_a_fold_takes_the_union_of_both_sides(
    make_writer: WriterFactory, *, arm: str
) -> None:
    """§8's first clause: the survivor's topics are the union, in §1's order."""
    survivor = await _fold(
        make_writer, target_topics=("health",), incoming_topics=("sleep",), arm=arm
    )

    assert survivor.topics == ("health", "sleep")


@_ARMS
async def test_a_labelled_target_reinforced_by_an_unlabelled_incoming_keeps_its_labels(
    make_writer: WriterFactory, *, arm: str
) -> None:
    """§12.15's named direction — the one a copy of the incoming tuple would fail.

    ADR-0106 §4's ratchet in this currency: a record the owner filed under
    ``"health"`` must not quietly stop being reachable by a health-scoped act the
    first time an unlabelled proposal reinforces it. Nothing about the survivor
    looks wrong afterwards, which is exactly why the rule is asserted here rather
    than trusted to a reviewer.
    """
    survivor = await _fold(make_writer, target_topics=("health",), incoming_topics=(), arm=arm)

    assert survivor.topics == ("health",)


@_ARMS
async def test_an_unlabelled_target_reinforced_by_a_labelled_incoming_takes_them(
    make_writer: WriterFactory, *, arm: str
) -> None:
    """The other position, without which the case above passes a rule that ignores incoming."""
    survivor = await _fold(make_writer, target_topics=(), incoming_topics=("sleep",), arm=arm)

    assert survivor.topics == ("sleep",)


@_ARMS
async def test_a_fold_of_two_unlabelled_records_stays_unlabelled(
    make_writer: WriterFactory, *, arm: str
) -> None:
    """The negative control: §7's empty tuple is not invented by a fold."""
    survivor = await _fold(make_writer, target_topics=(), incoming_topics=(), arm=arm)

    assert survivor.topics == ()


@_ARMS
async def test_the_union_is_stored_in_canonical_order_however_it_was_admitted(
    make_writer: WriterFactory, *, arm: str
) -> None:
    """§8's last sentence: admission order decides *which*, §1's order decides how stored."""
    survivor = await _fold(
        make_writer, target_topics=("sleep",), incoming_topics=("health",), arm=arm
    )

    assert survivor.topics == ("health", "sleep")


# --- §12.26 and §12.27: the bound retains, and counts nothing ---------------


async def test_a_target_at_the_bound_loses_nothing_to_an_incoming_label(
    make_writer: WriterFactory,
) -> None:
    """§12.26's first half: a conforming target's labels all fit ahead of any incoming one."""
    survivor = await _fold(
        make_writer, target_topics=_AT_BOUND, incoming_topics=("zebra",), arm=_ORDINARY
    )

    assert survivor.topics == _AT_BOUND


async def test_a_target_one_short_of_the_bound_admits_the_lesser_of_two(
    make_writer: WriterFactory,
) -> None:
    """§12.26's second half: code point order is the only order available among the incoming."""
    survivor = await _fold(
        make_writer,
        target_topics=_AT_BOUND[:-1],
        incoming_topics=("aardvark", "zebra"),
        arm=_ORDINARY,
    )

    assert survivor.topics == tuple(sorted((*_AT_BOUND[:-1], "aardvark")))
    assert "zebra" not in survivor.topics
    assert len(survivor.topics) == MAX_TOPICS_PER_RECORD


async def test_an_overflow_moves_no_other_field_and_is_counted_nowhere(
    make_writer: WriterFactory,
) -> None:
    """§12.27: no field records what an overflow did not admit, here or on ``core``.

    ADR-0086 §4's ``evidence_elided`` is deliberately not copied (§1): ``evidence``
    claims a warrant whose size ADR-0073 §4 obliges a surface to convey, while §7
    rules that a topic set is never a claim to completeness. So the assertion is
    that the survivor is otherwise **identical** to the one the same fold produces
    under a bound it does not reach — which is what a new counter would break.
    """
    overflowed = await _fold(
        make_writer, target_topics=_AT_BOUND, incoming_topics=("zebra",), arm=_ORDINARY
    )
    within = await _fold(make_writer, target_topics=_AT_BOUND, incoming_topics=(), arm=_ORDINARY)

    assert overflowed.provenance.evidence_elided == 0
    assert overflowed.model_dump() == within.model_dump()


# --- §12.29: a target already over the bound converges downward -------------


@pytest.mark.parametrize(
    "incoming_topics",
    [pytest.param((), id="unlabelled-incoming"), pytest.param(("zebra",), id="labelled-incoming")],
)
async def test_a_target_over_the_bound_converges_downward_rather_than_raising(
    make_writer: WriterFactory, incoming_topics: tuple[str, ...]
) -> None:
    """§12.29, both cases: the record this deployment cannot have written, installed.

    Reachable only by import or under a constant a later ADR raised. Neither case
    raises, and the incoming label is admitted nowhere: the target's own labels come
    first in the admission order, and there are already more of them than the bound.
    """
    over_bound = (*_AT_BOUND, "zzz beyond the bound")
    survivor = await _fold(
        make_writer, target_topics=over_bound, incoming_topics=incoming_topics, arm=_ORDINARY
    )

    assert survivor.topics == _AT_BOUND
    assert "zebra" not in survivor.topics


async def test_a_retire_carries_an_over_bound_targets_labels_whole(
    make_writer: WriterFactory,
) -> None:
    """§1's retire exemption and §12.29's last sentence, on the one write that is not an install.

    A write that merely narrows a record's validity window asserts nothing new about
    what the record is about, so it carries the tuple as it stands — truncating a
    record on its way *off* the read path would be the eager rewrite ADR-0077 §6
    refused, and would make the history ``export`` keeps disagree with what was
    stored.
    """
    over_bound = (*_AT_BOUND, "zzz beyond the bound")
    store = await _seeded(
        _target(topics=over_bound, arm=_ORDINARY, content="prefers concise emails, an older note")
    )
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), _fixed_now, lambda: _CORRECTION
    )

    await writer.ingest(
        MemoryUpdateProposal(
            proposed=_incoming(
                topics=("sleep",), record_id="new", preference="prefers detailed emails"
            ),
            rationale="because",
        )
    )

    retained = {record.id: record for record in await store.export()}["target"]
    assert retained.validity.valid_until is not None, "the target is retained, not edited"
    assert retained.topics == over_bound


# --- §12.25's install half: a non-fold install is bounded too ---------------


async def test_a_direct_install_over_the_bound_stores_the_bounded_subset(
    make_writer: WriterFactory,
) -> None:
    """§8's second admission arm, at the same seam and in the same sense as ADR-0086 §2.

    The record's own labels in canonical order, cut to the bound. It is the arm a
    fold-only implementation misses entirely, and the one an ``ACCEPT`` takes.
    """
    over_bound = (*_AT_BOUND, "zzz beyond the bound")
    # Seeded with the cited episode alone: the proposal's own evidence has to
    # resolve (ADR-0077 §5), and there is no target because an `ACCEPT` has none.
    store = await _seeded(_target(topics=(), arm=_ORDINARY, content="an unrelated older note"))
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(
            proposed=_incoming(topics=over_bound, record_id="fresh"), rationale="because"
        )
    )

    assert result.record_id is not None
    stored = await store.get(result.record_id)
    assert stored is not None
    assert stored.topics == _AT_BOUND


# --- §12.16: a supersession carries nothing across --------------------------


async def test_a_supersession_writes_its_own_topics_beside_a_retained_target(
    make_writer: WriterFactory,
) -> None:
    """§8's ``SUPERSEDE`` clause: ADR-0040 §5a's differential, unchanged.

    Two records at two ids, and both directions pinned so neither is satisfiable by
    the other's rule: a correction that inherited its target's labels would
    contradict the differential, and a target that lost its own would contradict
    ADR-0045 §4's retention — and would make a topic-scoped act's account of
    history wrong as well.
    """
    store = await _seeded(
        _target(topics=("health",), arm=_ORDINARY, content="prefers concise emails, an older note")
    )
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(
            proposed=_incoming(
                topics=("sleep",), record_id="new", preference="prefers detailed emails"
            ),
            rationale="because",
        )
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    stored = {record.id: record for record in await store.export()}
    assert {"target", _CORRECTION} <= set(stored), "two records, at distinct ids"
    assert stored["target"].topics == ("health",)
    assert stored[_CORRECTION].topics == ("sleep",)

"""ADR-0106 §4 under ADR-0328 §7:6: a fold rests on outside content if either side did.

Every case here runs against **both** ``MemoryIngestor`` and the canonical
``FakeMemoryWriter``, over the same store and the same policy, so the only thing
that varies is the fold. The obligation is not promoted to the ``MemoryWriter``
conformance suite: ADR-0106 §10 assigns the test to "the lane changing `memory`'s
fold", so a third writer stays free to compose differently and is not run here.

Since ADR-0328 the marker is no longer a field the fold builds: whether a memory
rests on outside content is computed from its supports (§7:6), and a reinforcement
only adds the proposal's supports to the target (§11:6). So the survivor carries
both sides' supports, and the disjunction falls out of reading them — what this
file guards is that neither writer *drops* a side's support on the way, which is
the laundering ADR-0106 §4 exists to stop.

**Both positions of the outside side are exercised**, because a writer that kept
only one side's supports passes a case in that position with full marks (ADR-0106
§10). **And every band of target**, because §7:6 reads the band: an ``ASSERTED``
memory never reports resting on outside content, however many outside supports it
carries, so on that arm the case reads the supports themselves.
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
    QuestionPart,
    UserConfirmation,
)
from ai_assistant.memory import InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryWriter, FakeTraceSink
from ai_assistant.testing.memories import memory, message_support, remembered_support, said_support

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import MemorySupport

_CLOCK: Final = datetime(2026, 6, 1, tzinfo=UTC)
_WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: The content both memories carry, so retrieval detects the conflict and the fold
#: onto an asserted target is the agreeing one clause 1 admits (ADR-0121 §5).
_CONTENT: Final = "prefers concise emails"

#: The episode every support points into, which the store must hold (ADR-0328 §4:7).
_EPISODE: Final = "episode-1"

WriterFactory = Callable[["MemoryStore", "MemoryPolicy", "Clock"], "MemoryWriter"]


def _fixed_now() -> datetime:
    return _CLOCK


def _build_ingestor(store: MemoryStore, policy: MemoryPolicy, now: Clock) -> MemoryWriter:
    return MemoryIngestor(traces_sink=FakeTraceSink(), store=store, policy=policy, now=now)


def _build_fake(store: MemoryStore, policy: MemoryPolicy, now: Clock) -> MemoryWriter:
    return FakeMemoryWriter(store=store, policy=policy, now=now)


@pytest.fixture(params=[_build_ingestor, _build_fake], ids=["ingestor", "canonical-fake"])
def make_writer(request: pytest.FixtureRequest) -> WriterFactory:
    """The two folds a consumer may be looking at, held to the same rule."""
    factory: WriterFactory = request.param
    return factory


def _target(*, outside: bool, band: BeliefBand) -> Memory:
    """The stored memory the ruling folds into, in ``band``.

    A ``DERIVED`` target rests on a remember call and an ``ATTESTED`` one on a
    round's message, each outside where ``outside`` says. A said support is never
    outside, so an ``ASSERTED`` target that is carries a second, outside support.
    """
    supports: tuple[MemorySupport, ...]
    match band:
        case BeliefBand.DERIVED:
            supports = (remembered_support(_EPISODE, effect="effect-target", outside=outside),)
        case BeliefBand.ATTESTED:
            supports = (message_support(_EPISODE, round_id="round-target", outside=outside),)
        case BeliefBand.ASSERTED:
            said = said_support(_EPISODE)
            supports = (
                (said, remembered_support(_EPISODE, effect="effect-target", outside=True))
                if outside
                else (said,)
            )
    return memory("target", _CONTENT, *supports)


def _incoming(*, outside: bool) -> Memory:
    """The proposed memory: always ``DERIVED``, resting on its own remember call."""
    return memory(
        "incoming",
        _CONTENT,
        remembered_support(_EPISODE, effect="effect-incoming", outside=outside),
    )


def _confirmed_proposal(record: Memory) -> MemoryUpdateProposal:
    """``record`` proposed under a user's answer to the question it would raise.

    **Every case carries one**, and it is what makes the two positions one code
    path: both policies defer an unconfirmed derived proposal resting on outside
    content (ADR-0106 §6), so the outside-incoming cases would never reach a fold.
    Confirming every case is ADR-0078 §5's re-ingest, the one route such a proposal
    has to landing, and it keeps the outside support the only thing that varies.
    Built in two steps because the authority binds to the question (ADR-0078 §7).
    """
    unconfirmed = MemoryUpdateProposal(proposed=record, rationale="because")
    return MemoryUpdateProposal(
        proposed=record,
        rationale="because",
        confirmation=UserConfirmation(
            question=QuestionPart(round="deferral-1", part=1),
            question_key=unconfirmed.question_key,
            confirmed_at=_WHEN,
        ),
    )


async def _fold(
    make_writer: WriterFactory, *, outside_target: bool, outside_incoming: bool, band: BeliefBand
) -> Memory:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    The ruling is injected (ADR-0040 §3): these cases are about the applier's fold,
    not about which ruling ``DefaultMemoryPolicy`` would reach (ADR-0159 §12).
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="the exchange the memories rest on",
            occurred_at=_WHEN,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
        )
    )
    target = _target(outside=outside_target, band=band)
    await store.add(target)
    incoming = _incoming(outside=outside_incoming)

    writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), _fixed_now)
    result = await writer.ingest(_confirmed_proposal(incoming))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert isinstance(survivor, Memory)
    # Every support of both sides, kept: the reinforcement only adds (§11:6).
    assert set(survivor.supports) >= set(target.supports)
    assert survivor.support_at(incoming.supports[0].points_at) is not None
    assert survivor.band is band
    return survivor


_BANDS: Final = pytest.mark.parametrize(
    "band",
    [BeliefBand.DERIVED, BeliefBand.ATTESTED, BeliefBand.ASSERTED],
    ids=["derived-target", "attested-target", "asserted-target"],
)


@_BANDS
@pytest.mark.parametrize(
    ("outside_target", "outside_incoming"),
    [(True, False), (False, True), (True, True)],
    ids=["outside-target", "outside-incoming", "both-outside"],
)
async def test_a_fold_combining_an_outside_side_rests_on_outside_content(
    make_writer: WriterFactory, *, outside_target: bool, outside_incoming: bool, band: BeliefBand
) -> None:
    """ADR-0106 §4, in both positions and on every band of target.

    The position that has to be exercised is the **outside target reinforced by a
    plain incoming**: a writer that rebuilt the survivor from the incoming side alone
    passes the other position and proves nothing.
    """
    survivor = await _fold(
        make_writer, outside_target=outside_target, outside_incoming=outside_incoming, band=band
    )

    assert any(support.outside for support in survivor.supports)
    # §7:6 reads the band: an asserted memory never reports it.
    assert survivor.rests_on_outside_content is (band is not BeliefBand.ASSERTED)


@_BANDS
async def test_a_fold_of_two_plain_memories_does_not(
    make_writer: WriterFactory, *, band: BeliefBand
) -> None:
    """The negative control, without which the cases above pass a hardcoded ``True``.

    It is also ADR-0106 §2's claim: the marker is a disjunction, not a ratchet that
    starts on.
    """
    survivor = await _fold(make_writer, outside_target=False, outside_incoming=False, band=band)

    assert not any(support.outside for support in survivor.supports)
    assert survivor.rests_on_outside_content is False

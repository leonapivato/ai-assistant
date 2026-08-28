"""ADR-0204 §5: the stamp never clears, and a supersession carries neither way.

The shape ``test_taint_fold.py`` established for ADR-0106 §4 and
``test_currency_fold.py`` for ADR-0109 §5, applied to the sibling field ADR-0204
§1 adds: every case runs against **both** ``MemoryIngestor`` and the canonical
``FakeMemoryWriter``, over the same store and the same policy, so the only thing
that varies is the writer's own composition of the survivor's ``Provenance``.

**Not promoted to the ``MemoryWriter`` conformance suite**, for the reason
ADR-0106 §10 gives about its own field: ADR-0028 §8 and ADR-0040 §5a keep the
fold's composition rules off that contract, so a third writer stays free to
compose differently and is not run here. What the *canonical fake* owes is not to
launder — it builds its survivor's ``Provenance`` field by field, exactly as
`memory`'s applier does, so a double that omitted the field would default it to
``False`` and clear a stamped target on the first unstamped reinforcement. That
is production's laundering path performed by the object a consumer reaches for
instead of `memory`'s internals.

**Both positions and both arms**, for ADR-0106 §10's reason transferred whole:
``_merge`` reads most of its provenance from one side, so a case in either
position alone passes an implementation that simply copies that side. The
direction that has to be exercised is a **stamped target reinforced by an
unstamped incoming** — the majority style, ``incoming.provenance.…``, clears the
stamp there and passes the opposite direction with full marks.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
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

#: The content both records carry, so retrieval detects the conflict.
_CONTENT: Final = "prefers concise emails"

#: The episode the proposal cites, which the store must hold for the ingestor to
#: accept it at all (ADR-0077 §5).
_EPISODE: Final = "episode-1"

#: The id a supersession's correction is minted at, scripted so the case can name
#: both records rather than discovering one (ADR-0045 §4's "freshly-minted id").
_CORRECTION: Final = "corrected"

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


def _target(*, stamped: bool, corroborating: bool, content: str = _CONTENT) -> MemoryRecord:
    """The stored record the ruling folds into, on whichever arm the case wants.

    ``corroborating`` selects ADR-0103 §6's pairing — an ``ATTESTED`` target under
    a ``DERIVED`` proposal — where the survivor is the *target* wearing a new
    provenance. Anything else is the ordinary arm, where the survivor is the
    incoming record wearing the target's id.
    """
    source = MemorySource.EXTERNAL if corroborating else MemorySource.OBSERVED
    return PreferenceMemory(
        id="target",
        content=content,
        preference=content,
        provenance=Provenance(
            source=source,
            confidence=0.6,
            last_updated=_WHEN,
            attestation=(
                Attestation(reported_by="calendar:work", reported_at=_WHEN)
                if corroborating
                else None
            ),
            supplied_withheld_content=stamped,
        ),
    )


def _incoming(
    *, stamped: bool, record_id: str = "incoming", preference: str = _CONTENT
) -> MemoryRecord:
    """The proposed record. Always ``DERIVED``, so either arm is reachable.

    ``preference`` is carried for readability; what the supersession case actually
    varies is the **target's** ``content``, because a proposal whose content agrees
    with its target *restates* it under ADR-0121 §1 and ADR-0159 §5 refuses to
    retire a conflict so related — by any ruling, this fake policy's included.
    """
    return PreferenceMemory(
        id=record_id,
        content=_CONTENT,
        preference=preference,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            evidence=(_EPISODE,),
            last_updated=_WHEN,
            supplied_withheld_content=stamped,
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
    stamped_target: bool,
    stamped_incoming: bool,
    corroborating: bool,
) -> MemoryRecord:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    End to end rather than through ``_merge``: §5's clause is about what is
    *stored*, and a unit call on either private function would have to be written
    twice — which is the drift running both writers exists to catch.
    """
    store = await _seeded(_target(stamped=stamped_target, corroborating=corroborating))
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(proposed=_incoming(stamped=stamped_incoming), rationale="because")
    )

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert survivor is not None
    # The arm actually taken, asserted rather than assumed: both arms leave a record
    # at the target's id, so a `corroboration-arm` case that silently ran the
    # ordinary one would check half of what §5's first clause rules. `source` is the
    # discriminator (ADR-0103 §6).
    expected = MemorySource.EXTERNAL if corroborating else MemorySource.OBSERVED
    assert survivor.provenance.source is expected
    return survivor


_ARMS: Final = pytest.mark.parametrize(
    "corroborating", [False, True], ids=["ordinary-arm", "corroboration-arm"]
)


@_ARMS
@pytest.mark.parametrize(
    ("stamped_target", "stamped_incoming"),
    [(True, False), (False, True), (True, True)],
    ids=["stamped-target", "stamped-incoming", "both-stamped"],
)
async def test_a_fold_combining_a_stamped_side_is_stamped(
    make_writer: WriterFactory,
    *,
    stamped_target: bool,
    stamped_incoming: bool,
    corroborating: bool,
) -> None:
    """§8 case 7: the survivor's value is the disjunction, in both argument orders.

    ADR-0106 §4's ratchet argument, which ADR-0204 §5 takes by citation: "a tainted
    belief reinforced by a clean observation stays tainted. Without that, the
    laundering the marker exists to stop simply moves one step along." Here the step
    along is a stamped episode reinforced once by an unstamped proposal, after which
    a channel of unbounded audience is handed the record ADR-0204 §3 withholds.
    """
    survivor = await _fold(
        make_writer,
        stamped_target=stamped_target,
        stamped_incoming=stamped_incoming,
        corroborating=corroborating,
    )

    assert survivor.provenance.supplied_withheld_content is True


@_ARMS
async def test_a_fold_of_two_unstamped_records_stays_unstamped(
    make_writer: WriterFactory, *, corroborating: bool
) -> None:
    """The negative control, without which the cases above pass a hardcoded ``True``.

    It is also the claim ADR-0204 §1 makes about ``False`` on a post-field record:
    a measurement rather than a ratchet that starts on. A fold that raised the stamp
    on records neither of which carried it would withhold every reinforced belief
    from the spoken channel, which is milestone 19's exit test failing by a second
    route (§1's third clause).
    """
    survivor = await _fold(
        make_writer, stamped_target=False, stamped_incoming=False, corroborating=corroborating
    )

    assert survivor.provenance.supplied_withheld_content is False


@pytest.mark.parametrize(
    ("stamped_target", "stamped_incoming"),
    [(True, False), (False, True)],
    ids=["stamped-target", "stamped-proposal"],
)
async def test_a_supersession_writes_the_proposals_value_beside_a_retained_target(
    make_writer: WriterFactory, *, stamped_target: bool, stamped_incoming: bool
) -> None:
    """§8 case 15: two records, two ids, in both directions.

    ADR-0040 §5a's differential and ADR-0045 §4's retention, pinned together with
    §5's third and fourth clauses so neither can be implemented at the other's
    expense. A ``SUPERSEDE`` is not an operation on the stamped record's value at
    all: the correction carries what its **own** producer was supplied and nothing
    of the target's, and the target is not written to — it is retained with a closed
    validity window, still carrying its own value, and stays withheld from a channel
    of unbounded audience for as long as it is in the store.

    A ratchet that made the correction inherit its target's stamp would contradict
    the differential; one that cleared the target's would contradict the retention.
    Both directions are asserted, so neither is satisfiable by the other's rule.
    """
    store = await _seeded(
        _target(
            stamped=stamped_target,
            corroborating=False,
            content="prefers concise emails, an older note",
        )
    )
    writer = make_writer(
        store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), _fixed_now, lambda: _CORRECTION
    )

    result = await writer.ingest(
        MemoryUpdateProposal(
            proposed=_incoming(
                stamped=stamped_incoming, record_id="new", preference="prefers detailed emails"
            ),
            rationale="because",
        )
    )

    assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
    assert result.record_id == _CORRECTION
    stored = {record.id: record for record in await store.export()}
    assert {"target", _CORRECTION} <= set(stored), "two records, at distinct ids"
    retained = stored["target"]
    assert retained.validity.valid_until is not None, "the target is retained, not edited"
    assert retained.provenance.supplied_withheld_content is stamped_target
    correction = stored[_CORRECTION]
    assert correction.validity.valid_until is None, "the correction is live"
    assert correction.provenance.supplied_withheld_content is stamped_incoming

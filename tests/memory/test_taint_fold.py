"""ADR-0106 §4: the fold's taint marker is the disjunction of both sides.

Every case here runs against **both** ``MemoryIngestor`` and the canonical
``FakeMemoryWriter``, over the same store and the same policy, so the only thing
that varies is the fold — the shape ``test_currency_fold.py`` established for
ADR-0109 §5. The obligation is not promoted to the ``MemoryWriter`` conformance
suite: ADR-0106 §10 assigns the test to "the lane changing `memory`'s fold", and
ADR-0028 §8 and ADR-0040 §5a keep the fold's own composition rules off that
contract, so a third writer stays free to compose differently and is not run
here. What the fake owes is not to *launder*: it builds its survivor's
``Provenance`` field by field, so a fake that omitted the field would default it
to ``False`` and clear a tainted target — production's laundering path, performed
by the double a consumer reaches for instead of `memory`'s internals.

**Both positions of the tainted side are exercised, and that is the point of the
parametrisation rather than thoroughness** (ADR-0106 §10). ``_merge`` reads most
of its ``Provenance`` from one side, so a test in either position alone passes an
implementation that simply copies that side: a fold written in the majority style
— ``incoming.provenance.derived_from_external`` — clears a tainted target on the
first clean reinforcement, which is exactly the laundering ADR-0106 §4 exists to
stop, and it passes a tainted-incoming case with full marks.

**Both fold arms too**, because ADR-0103 §6's corroboration arm builds its
survivor from the *target's* provenance and is therefore the arm where a
copy-one-side implementation looks right for the other reason. ADR-0106 §4 states
its clause over the fold rather than over either record, so both arms owe the
disjunction.

**Every case carries a ``UserConfirmation``**, and it is what makes the two
positions one code path rather than two. Since ADR-0106 §6 ``DefaultMemoryPolicy``
defers an unconfirmed tainted derived proposal, so the tainted-incoming cases
would never reach a fold at all — while the tainted-*target* cases would, since
the ceiling is a property of the proposal and says nothing about what it folds
onto. Confirming both is ADR-0078 §5's re-ingest, which is the one route a tainted
proposal has to landing, and it keeps the marker as the only thing that varies.
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
    UserConfirmation,
)
from ai_assistant.memory import DefaultMemoryPolicy, InMemoryMemoryStore, MemoryIngestor
from ai_assistant.testing import FakeMemoryWriter

if TYPE_CHECKING:
    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore, MemoryWriter
    from ai_assistant.core.types import MemoryRecord

_CLOCK: Final = datetime(2026, 6, 1, tzinfo=UTC)
_WHEN: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: The content both records carry, so retrieval detects the conflict.
_CONTENT: Final = "prefers concise emails"

#: The episode the `DERIVED` proposal cites, and which the store must hold for the
#: ingestor to accept it at all (ADR-0077 §5).
_EPISODE: Final = "episode-1"

WriterFactory = Callable[["MemoryStore", "MemoryPolicy", "Clock"], "MemoryWriter"]


def _fixed_now() -> datetime:
    return _CLOCK


def _build_ingestor(store: MemoryStore, policy: MemoryPolicy, now: Clock) -> MemoryWriter:
    return MemoryIngestor(store=store, policy=policy, now=now)


def _build_fake(store: MemoryStore, policy: MemoryPolicy, now: Clock) -> MemoryWriter:
    return FakeMemoryWriter(store=store, policy=policy, now=now)


@pytest.fixture(params=[_build_ingestor, _build_fake], ids=["ingestor", "canonical-fake"])
def make_writer(request: pytest.FixtureRequest) -> WriterFactory:
    """The two folds a consumer may be looking at, held to the same rule."""
    factory: WriterFactory = request.param
    return factory


def _target(*, tainted: bool, corroborating: bool) -> MemoryRecord:
    """The stored record the ruling folds into, on whichever arm the case wants.

    ``corroborating`` selects ADR-0103 §6's pairing — an ``ATTESTED`` target under
    a ``DERIVED`` proposal — where the survivor is the *target* wearing a new
    provenance. Anything else is the ordinary arm, where the survivor is the
    incoming record wearing the target's id.
    """
    source = MemorySource.EXTERNAL if corroborating else MemorySource.OBSERVED
    return PreferenceMemory(
        id="target",
        content=_CONTENT,
        preference=_CONTENT,
        provenance=Provenance(
            source=source,
            confidence=0.6,
            last_updated=_WHEN,
            attestation=(
                Attestation(reported_by="calendar:work", reported_at=_WHEN)
                if corroborating
                else None
            ),
            derived_from_external=tainted,
        ),
    )


def _incoming(*, tainted: bool) -> MemoryRecord:
    """The proposed record. Always ``DERIVED``, so either arm is reachable."""
    return PreferenceMemory(
        id="incoming",
        content=_CONTENT,
        preference=_CONTENT,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.6,
            evidence=(_EPISODE,),
            last_updated=_WHEN,
            derived_from_external=tainted,
        ),
    )


def _confirmed_proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    """``record`` proposed under a user's answer to the question it would raise.

    Built in two steps because the authority binds to the *question*, whose
    identity is a property of the proposal (ADR-0078 §7): a hand-picked digest
    would be input no coordinator produces. ``retires`` stays empty — this
    confirmation authorises nothing to be retired, and the fold it unblocks is a
    ``REINFORCE``, which retires nothing.
    """
    unconfirmed = MemoryUpdateProposal(proposed=record, rationale="because")
    return MemoryUpdateProposal(
        proposed=record,
        rationale="because",
        confirmation=UserConfirmation(
            deferral_id="deferral-1",
            question_key=unconfirmed.question_key,
            confirmed_at=_WHEN,
        ),
    )


async def _fold(
    make_writer: WriterFactory,
    *,
    tainted_target: bool,
    tainted_incoming: bool,
    corroborating: bool,
) -> MemoryRecord:
    """Drive one ``REINFORCE`` end to end and return the survivor.

    End to end rather than through ``_merge``: ADR-0106 §4's clause is about what
    is *stored*, and a unit call on either private function would have to be
    written twice — which is the drift running both writers exists to catch.
    """
    store = InMemoryMemoryStore(now=_fixed_now)
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="the exchange the proposal stands on",
            occurred_at=_WHEN,
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
        )
    )
    await store.add(_target(tainted=tainted_target, corroborating=corroborating))

    writer = make_writer(store, DefaultMemoryPolicy(), _fixed_now)
    result = await writer.ingest(_confirmed_proposal(_incoming(tainted=tainted_incoming)))

    assert result.decision.kind is MemoryDecisionKind.REINFORCE
    survivor = await store.get("target")
    assert survivor is not None
    # The arm actually taken, asserted rather than assumed: both arms leave a
    # record at the target's id, so a `corroboration-arm` case that silently ran
    # the ordinary one would pass every assertion below while checking half of
    # what ADR-0106 §4 rules. `source` is the discriminator (ADR-0103 §6).
    expected_source = MemorySource.EXTERNAL if corroborating else MemorySource.OBSERVED
    assert survivor.provenance.source is expected_source
    return survivor


_ARMS: Final = pytest.mark.parametrize(
    "corroborating", [False, True], ids=["ordinary-arm", "corroboration-arm"]
)


@_ARMS
@pytest.mark.parametrize(
    ("tainted_target", "tainted_incoming"),
    [(True, False), (False, True), (True, True)],
    ids=["tainted-target", "tainted-incoming", "both-tainted"],
)
async def test_a_fold_combining_a_tainted_side_is_tainted(
    make_writer: WriterFactory,
    *,
    tainted_target: bool,
    tainted_incoming: bool,
    corroborating: bool,
) -> None:
    """ADR-0106 §4, in both positions and on both arms.

    The direction that has to be exercised is the **tainted target reinforced by
    an untainted incoming**: the opposite direction passes an implementation that
    merely copies the incoming field and proves nothing, and the majority of
    ``_merge``'s fields *are* copied from the incoming record. One parametrised
    test over the two positions satisfies the clause; either position alone does
    not.
    """
    survivor = await _fold(
        make_writer,
        tainted_target=tainted_target,
        tainted_incoming=tainted_incoming,
        corroborating=corroborating,
    )

    assert survivor.provenance.derived_from_external is True


@_ARMS
async def test_a_fold_of_two_untainted_records_stays_untainted(
    make_writer: WriterFactory, *, corroborating: bool
) -> None:
    """The negative control, without which the cases above pass a hardcoded ``True``.

    It is also the claim ADR-0106 §2 makes about the default: the field is a
    disjunction and not a ratchet that starts on. A fold that raised the marker
    on records neither of which carried it would put every reinforced belief
    behind a user question, which is the backfill ADR-0106 §2 refuses.
    """
    survivor = await _fold(
        make_writer,
        tainted_target=False,
        tainted_incoming=False,
        corroborating=corroborating,
    )

    assert survivor.provenance.derived_from_external is False

"""Shared conformance suite for the MemoryWriter Protocol (ADR-0028 §8).

Every ``MemoryWriter`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`MemoryWriterContract` and overrides two fixtures:

* ``make_writer`` — a factory building the writer under test over a *given*
  store and policy. It has to be a factory rather than a ready-made writer: a
  writer holds its own policy and exposes neither it nor its store, so a suite
  handed only a writer could neither drive a particular ruling nor see what was
  persisted. Supplying both collaborators is what makes the obligations below
  observable at all.
* ``writer`` — one ready-made writer, for the structural check (and the
  evidence the triad check reads).

The obligations are the ones ADR-0028 §8 lists (as amended by ADR-0040 §5a and §5b),
and no more: conflicts are resolved *before* the policy is asked and their ids
are carried on the proposal it sees; ``ACCEPT`` stores the record and returns its
id; ``STORE_TEMPORARY`` stores it with an expiry; ``REJECT`` and ``ASK_USER``
write nothing and return a ``None`` record id; a ``REINFORCE`` or ``SUPERSEDE``
naming a target absent from the conflicts raises ``MemoryStoreError`` rather than
storing the proposal as new.

``REINFORCE`` and ``SUPERSEDE`` both land on the target's id and return it — the
one mechanism clause here, marked as what issue #112 rewrites — and are pinned
*differentially* (ADR-0040 §5a): ``REINFORCE`` retains **both** records'
``evidence``, and ``SUPERSEDE`` carries **nothing** of the target across, so the
live record equals the proposed record but for its id. Both must also refuse the
two unsafe folds (§5b): any fold onto a ``USER_ASSERTED`` target, and a
``USER_ASSERTED`` proposal onto an ``EXTERNAL`` one, each raising
``MemoryStoreError`` and writing nothing. Every other pairing is permitted, which
the suite exercises as well as the two it refuses.

It deliberately does **not** pin the conflict threshold, the conflict limit, the
constructor's tuning check, or — for ``REINFORCE`` — which content wins and how
confidence combines: those are one implementation's tuning and `memory`'s
semantics, and a suite that pinned them would stop being a contract. Nor does it
pin clock handling: a writer with no clock at all conforms, so
``MemoryIngestor``'s naive-clock guard is asserted in ``test_ingest.py`` where it
belongs (ADR-0028 §4b).

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.protocols import MemoryWriter
from ai_assistant.core.types import (
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore

#: Builds the writer under test over the store and policy the suite supplies.
type WriterFactory = Callable[[MemoryStore, MemoryPolicy], MemoryWriter]

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The store's clock, fixed far enough back that any expiry a writer stamps from
#: any clock is still in the future. The contract fixes no writer clock, so a
#: store reading "now" as the present could hide a just-stored temporary record
#: behind ADR-0007's read-time retention and fail a conforming writer.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)

_CONTENT = "prefers concise emails"


def _long_ago() -> datetime:
    return _LONG_AGO


def _preference(
    record_id: str,
    content: str = _CONTENT,
    *,
    confidence: float = 0.6,
    source: MemorySource = MemorySource.OBSERVED,
    evidence: tuple[str, ...] = (),
) -> MemoryRecord:
    # USER_ASSERTED is pinned to full confidence by `Provenance`, so honour that
    # here rather than build a record the domain forbids.
    if source is MemorySource.USER_ASSERTED:
        confidence = 1.0
    return PreferenceMemory(
        id=record_id,
        content=content,
        preference=content,
        provenance=Provenance(
            source=source,
            confidence=confidence,
            last_updated=_WHEN,
            evidence=list(evidence),
        ),
    )


def _proposal(record: MemoryRecord) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=DataTier.PERSONAL)


#: The two rulings that name a target record and fold the proposal against it.
_FOLD_KINDS = [MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE]


def _fold_is_refused(incoming: MemorySource, target: MemorySource) -> bool:
    """Exactly ADR-0040 §5b's two prohibited predicates — every other pairing is
    permitted: a fold onto a ``USER_ASSERTED`` target, or a ``USER_ASSERTED``
    proposal onto an ``EXTERNAL`` one."""
    return target is MemorySource.USER_ASSERTED or (
        incoming is MemorySource.USER_ASSERTED and target is MemorySource.EXTERNAL
    )


#: The complete ``ruling`` by ``incoming source`` by ``target source`` space, so the suite
#: samples nothing: every pairing is either refused (write nothing) or applied
#: (the fold reaches the store), per :func:`_fold_is_refused`.
_FOLD_MATRIX = [
    (kind, incoming, target)
    for kind in _FOLD_KINDS
    for incoming in MemorySource
    for target in MemorySource
]


class _FoldToAbsentTargetPolicy:
    """Always asks to fold into a record that is not among the conflicts."""

    def __init__(self, kind: MemoryDecisionKind) -> None:
        self._kind = kind

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Name a target the writer was never offered."""
        return MemoryDecision(kind=self._kind, target_id="ghost", reason="contract: misdirection")


class MemoryWriterContract:
    """The behavioural contract every ``MemoryWriter`` must satisfy."""

    @pytest.fixture
    def make_writer(self) -> WriterFactory:
        """Override in a subclass: build the writer under test over these two."""
        raise NotImplementedError

    @pytest.fixture
    def writer(self) -> MemoryWriter:
        """Override in a subclass: one writer, however it likes to be built."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, writer: MemoryWriter) -> None:
        assert isinstance(writer, MemoryWriter)

    async def test_conflicts_are_resolved_before_the_policy_is_asked(
        self, make_writer: WriterFactory
    ) -> None:
        """The caller supplies no conflicts, so the writer must find them itself.

        And the proposal the policy sees must name them, so a decision is
        auditable against what it was ruled on.
        """
        store = FakeMemoryStore(now=_long_ago)
        await store.add(_preference("existing"))
        policy = FakeMemoryPolicy(MemoryDecisionKind.REJECT)

        await make_writer(store, policy).ingest(_proposal(_preference("new")))

        assert [record.id for record in policy.calls[0].conflicts] == ["existing"]
        assert policy.last_proposal.conflicts == ["existing"]

    async def test_accept_stores_the_record_and_returns_its_id(
        self, make_writer: WriterFactory
    ) -> None:
        store = FakeMemoryStore(now=_long_ago)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_proposal(_preference("new")))

        assert result.decision.kind is MemoryDecisionKind.ACCEPT
        assert result.record_id == "new"
        # Stored by the time `ingest` returned: the result reports an id written,
        # so a writer that queued the proposal for later would be claiming
        # something this result type cannot say (ADR-0028 §Consequences).
        assert await store.get("new") is not None

    async def test_store_temporary_stores_the_record_with_an_expiry(
        self, make_writer: WriterFactory
    ) -> None:
        """The expiry is stamped from the writer's own clock, whatever that is.

        Its *value* is not pinned — the contract fixes no clock — but it must be
        set, and aware, since a naive deadline raises ``TypeError`` at the first
        comparison inside a store.
        """
        store = FakeMemoryStore(now=_long_ago)
        policy = FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=timedelta(days=1))

        result = await make_writer(store, policy).ingest(_proposal(_preference("new")))

        assert result.decision.kind is MemoryDecisionKind.STORE_TEMPORARY
        assert result.record_id == "new"
        stored = await store.get("new")
        assert stored is not None
        assert stored.expires_at is not None
        assert stored.expires_at.tzinfo is not None

    @pytest.mark.parametrize(
        "kind", [MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER], ids=str
    )
    async def test_a_declined_ruling_writes_nothing(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        store = FakeMemoryStore(now=_long_ago)

        result = await make_writer(store, FakeMemoryPolicy(kind)).ingest(
            _proposal(_preference("new"))
        )

        assert result.decision.kind is kind
        assert result.record_id is None
        assert await store.export() == []

    async def test_reinforce_folds_into_the_target_and_keeps_both_evidences(
        self, make_writer: WriterFactory
    ) -> None:
        """``REINFORCE`` lands on the target's id and retains both evidences.

        Which content wins and how confidence combines is `memory`'s own rule
        and is not pinned here. That it lands on the target's id, mints no second
        record, and keeps **both** records' ``evidence`` is the contract
        (ADR-0040 §5a).
        """
        store = FakeMemoryStore(now=_long_ago)
        await store.add(_preference("existing", evidence=("t-ev",)))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        result = await writer.ingest(
            _proposal(_preference("new", confidence=0.9, evidence=("p-ev",)))
        )

        assert result.decision.kind is MemoryDecisionKind.REINFORCE
        assert result.record_id == "existing"
        assert [record.id for record in await store.export()] == ["existing"]
        stored = await store.get("existing")
        assert stored is not None
        assert set(stored.provenance.evidence) == {"t-ev", "p-ev"}

    async def test_supersede_overwrites_the_target_keeping_only_its_id(
        self, make_writer: WriterFactory
    ) -> None:
        """``SUPERSEDE`` carries nothing of the target across (ADR-0040 §5a).

        The live record is the proposed record — content, provenance, evidence,
        confidence, and every other field — borrowing from the target only the id
        it is written at. A *complete* specification, unlike ``REINFORCE``'s fold:
        "take nothing across" leaves nothing open, so the stored record must equal
        the proposed record with only its id replaced. Target and proposal differ
        in every settable field, so a writer that kept any one of the target's —
        not merely its evidence — is caught.
        """
        store = FakeMemoryStore(now=_long_ago)
        # Target INFERRED (supersedable, so neither §5b refusal fires); its
        # content is a superset of the proposal's terms, so the conflict is found.
        target = PreferenceMemory(
            id="existing",
            content="prefers concise emails, an older note",
            preference="older preference",
            context="stale-context",
            strength=0.1,
            expires_at=datetime(2029, 1, 1, tzinfo=UTC),
            provenance=Provenance(
                source=MemorySource.INFERRED,
                confidence=0.9,
                evidence=["t-ev"],
                last_updated=_WHEN,
            ),
        )
        await store.add(target)
        proposed = PreferenceMemory(
            id="new",
            content=_CONTENT,
            preference="fresh preference",
            context="fresh-context",
            strength=0.9,
            expires_at=datetime(2030, 6, 1, tzinfo=UTC),
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.6,
                evidence=["p-ev"],
                last_updated=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE))

        result = await writer.ingest(_proposal(proposed))

        assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
        assert result.record_id == "existing"
        assert [record.id for record in await store.export()] == ["existing"]
        stored = await store.get("existing")
        # Complete: the live record is the proposed record, only its id changed.
        assert stored == proposed.model_copy(update={"id": "existing"})

    @pytest.mark.parametrize("kind", _FOLD_KINDS, ids=str)
    async def test_a_fold_naming_an_absent_target_is_refused(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """Storing the proposal as new would create the duplicate the fold
        existed to prevent, while reporting success."""
        store = FakeMemoryStore(now=_long_ago)
        writer = make_writer(store, _FoldToAbsentTargetPolicy(kind))

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new")))

        # Nothing written: the store is exactly as empty as it began.
        assert await store.export() == []

    @pytest.mark.parametrize(
        ("kind", "incoming", "target"),
        _FOLD_MATRIX,
        ids=[f"{k}-{i}-onto-{t}" for k, i, t in _FOLD_MATRIX],
    )
    async def test_every_fold_pairing_is_refused_or_applied_per_5b(
        self,
        make_writer: WriterFactory,
        kind: MemoryDecisionKind,
        incoming: MemorySource,
        target: MemorySource,
    ) -> None:
        """The whole ADR-0040 §5b predicate, over the complete source matrix.

        For *every* ``(ruling, incoming source, target source)`` triple: a fold
        onto a ``USER_ASSERTED`` target and a ``USER_ASSERTED`` proposal onto an
        ``EXTERNAL`` one raise and leave the store byte-for-byte unchanged; every
        other pairing is *applied* — and applied means it reached the store, so a
        writer that returned the target's id without writing (leaving the stale
        record live) is caught. The proposal carries evidence the target lacks,
        so the stored record's evidence proves the fold actually ran.
        """
        store = FakeMemoryStore(now=_long_ago)
        await store.add(_preference("existing", source=target))
        writer = make_writer(store, FakeMemoryPolicy(kind))
        before = await store.export()
        proposal = _proposal(_preference("new", source=incoming, evidence=("p-ev",)))

        if _fold_is_refused(incoming, target):
            with pytest.raises(MemoryStoreError):
                await writer.ingest(proposal)
            # Write nothing: the whole store is unchanged, so a writer that
            # mutated the target and *then* raised is caught, not only one that
            # stored the proposal as new.
            assert await store.export() == before
            return

        result = await writer.ingest(proposal)

        assert result.decision.kind is kind
        assert result.record_id == "existing"
        assert await store.get("new") is None  # folded in place, no duplicate
        stored = await store.get("existing")
        assert stored is not None
        # The fold reached the store: both REINFORCE (union) and SUPERSEDE (the
        # proposed record) leave the proposal's evidence on the live record, which
        # the pre-fold target did not carry.
        assert "p-ev" in stored.provenance.evidence

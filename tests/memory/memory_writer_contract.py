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

The obligations are the ones ADR-0028 §8 lists (as amended by ADR-0040 §5a/§5b and
ADR-0045 §5), and no more: conflicts are resolved *before* the policy is asked and
their ids are carried on the proposal it sees; ``ACCEPT`` stores the record and
returns its id; ``STORE_TEMPORARY`` stores it with an expiry; ``REJECT`` and
``ASK_USER`` write nothing and return a ``None`` record id; a ``REINFORCE`` or
``SUPERSEDE`` naming a target absent from the conflicts raises ``MemoryStoreError``
rather than storing the proposal as new.

``REINFORCE`` and ``SUPERSEDE`` are pinned *differentially* (ADR-0040 §5a, as the
mechanism half is rewritten by ADR-0045 §5):

* ``REINFORCE`` folds at the target's id, mints no second record, and retains
  **both** records' ``evidence``, returning the target's id.
* ``SUPERSEDE`` (ADR-0045 §4/§5a) leaves the target **retained with a closed
  validity window** and writes the proposed record — carrying nothing of the
  target, with a **fresh open window** so the correction is live — at an id
  **absent from the store**, so it overwrites no existing record.
  ``record_id`` is the **live record's** id, neither the target's nor any
  collided-with record's. The id is minted by an **injected id factory** and written
  insert-if-absent: a collision is re-minted (bounded), an always-colliding factory
  raises ``MemoryStoreError`` with the target left live, and a raising or
  non-``str``/empty factory raises ``MemoryStoreError`` before any write — the four
  id cases below. The retained target's closed window hides it from ``get``/``search``
  **read-time-relatively**, not absolutely: ``valid_until`` is the *writer's* close
  instant, and ``get``/``search`` hide it once the *store's* read clock is at or
  after it — the same read-time filter ``expires_at`` uses (ADR-0007, ADR-0045 §6).
  The suite therefore reads from a store clock at or after the close (``_after_close``,
  the coherent case production's forward-advancing wall clock gives); the
  read-time-relative behaviour itself, including that a store clock *behind* the
  close transiently still returns the target, is pinned per-writer (``test_ingest.py``
  and ``test_fake_writer.py``). ``export`` keeps the
  target unconditionally. An absolute, clock-coherence-independent guarantee is
  deferred to issue #306.

Both must also refuse the unsafe folds (§5b as narrowed by ADR-0045 §5): **clause
1** — any fold onto a ``USER_ASSERTED`` target — stays record-keyed for **both**
rulings; the **``EXTERNAL``** clause is **narrowed to ``REINFORCE``** — a
``USER_ASSERTED`` proposal *reinforcing* an ``EXTERNAL`` target still raises, while
the same *supersession* is now permitted and writes a new-id correction. Every
other pairing is permitted, which the suite exercises as well as those it refuses.

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
from typing import TYPE_CHECKING, Protocol

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.protocols import MemoryWriter
from ai_assistant.core.types import (
    DataTier,
    EpisodicMemory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryRecord,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    Validity,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore

    #: Mints the id a ``SUPERSEDE`` writes its correction at (ADR-0045 §4).
    type IdFactory = Callable[[], str]


class WriterFactory(Protocol):
    """Builds the writer under test over the store, policy, and (optional) id factory.

    A callable rather than a ready-made writer because a writer hides its own
    store and policy (see the class docstring). The ``id_factory`` is keyword-only
    and optional: most obligations do not care which id a ``SUPERSEDE`` mints, but
    the four id-factory cases (ADR-0045 §5) drive it deterministically, so the
    factory must reach the writer's constructor. ``None`` leaves the writer's own
    default (random UUIDs). No clock seam is exposed — the suite deliberately does
    not pin clock handling (a writer with no clock at all conforms), so the
    bounded-window close tests live with each concrete writer, not here.
    """

    def __call__(
        self,
        store: MemoryStore,
        policy: MemoryPolicy,
        *,
        id_factory: IdFactory | None = None,
    ) -> MemoryWriter: ...


_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The store's clock, fixed far enough back that any expiry a writer stamps from
#: any clock is still in the future. The contract fixes no writer clock, so a
#: store reading "now" as the present could hide a just-stored temporary record
#: behind ADR-0007's read-time retention and fail a conforming writer.
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)

#: A store read clock fixed far enough *forward* that any window a writer closes
#: from any clock is already closed by the time the store reads — i.e. the store
#: reads **at or after the close instant**, the coherent case production gives when
#: the store and ingestor each independently sample a forward-advancing wall clock
#: (a ``get`` after ``ingest`` reads at/after the write). The mirror of
#: ``_LONG_AGO``: supersession stamps ``valid_until = writer_now`` on
#: the retired target, and ``get``/``search`` hide it *read-time-relatively*, only
#: when read at or after that instant. This is deliberately the coherent direction —
#: it does not "mask" the skew, it fixes the reader at/after the close so the
#: read-time-relative hide is observable; the *behind*-the-close direction (target
#: transiently still returned) is pinned per-writer in ``test_ingest.py`` and
#: ``test_fake_writer.py``. The
#: contract fixes no writer clock, so the window tests read from a store whose "now"
#: is after every plausible writer now, and pin their records' ``expires_at`` to
#: ``None`` or beyond it so retention does not confound the window assertion.
_AFTER_CLOSE = datetime(2100, 1, 1, tzinfo=UTC)

_CONTENT = "prefers concise emails"


def _long_ago() -> datetime:
    return _LONG_AGO


def _after_close() -> datetime:
    return _AFTER_CLOSE


def _episodic(record_id: str, content: str) -> MemoryRecord:
    """A live record of a *different kind* from the preference under test.

    Used as the innocent bystander in the id cases: because conflict detection is
    kind-scoped, an episodic record never enters the preference proposal's
    conflicts, so it can occupy an id (the proposal's own, or one the factory
    mints) purely to prove a ``SUPERSEDE`` does not clobber it.
    """
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=_WHEN,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_WHEN),
    )


def _scripted(*ids: str) -> Callable[[], str]:
    """An id factory that yields ``ids`` in order — deterministic minting."""
    minted = iter(ids)

    def _next() -> str:
        return next(minted)

    return _next


def _always(record_id: str) -> Callable[[], str]:
    """An id factory that always mints the same (colliding) id."""
    return lambda: record_id


def _raises_id() -> str:
    """An id factory that raises rather than returning an id."""
    msg = "id factory is broken"
    raise RuntimeError(msg)


def _empty_id() -> str:
    """An id factory that returns an empty id."""
    return ""


def _non_str_id() -> str:
    """An id factory that returns a non-``str`` id (a wiring bug the guard catches)."""
    return 123  # type: ignore[return-value]  # deliberately wrong, to drive the output guard


class _HostileId(str):
    """A ``str`` *subclass* whose ``__hash__`` raises when used as a store key.

    It passes a naive ``isinstance(x, str)`` check, so an output guard that only
    tests ``isinstance`` would install it and let the store hash it — leaking a raw
    ``RuntimeError`` across the writer seam. The guard must reject a non-exact
    ``str`` (``type(x) is str``) to catch it before any write.
    """

    __slots__ = ()

    def __hash__(self) -> int:
        msg = "hostile id refuses to be hashed"
        raise RuntimeError(msg)


def _hostile_subclass_id() -> str:
    """An id factory returning a hostile ``str`` subclass (ADR-0045 §4's output guard)."""
    return _HostileId("looks-like-a-str")


class _HostileMeta(type):
    """A metaclass whose ``__name__`` access raises.

    A guard that tried to name the offending type in its error message —
    ``type(minted).__name__`` — would trip this and leak a raw exception instead of
    ``MemoryStoreError``. The guard must introspect *nothing* about the returned
    object on the error path.
    """

    @property
    def __name__(cls) -> str:  # type: ignore[override]
        msg = "hostile type refuses to be named"
        raise RuntimeError(msg)


class _HostileTyped(metaclass=_HostileMeta):
    """Not a ``str`` at all, and whose type resists being introspected."""


def _hostile_typed_id() -> str:
    """An id factory returning a non-str whose *type* raises when named."""
    return _HostileTyped()  # type: ignore[return-value]  # deliberately not a str


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


def _fold_is_refused(
    kind: MemoryDecisionKind, incoming: MemorySource, target: MemorySource
) -> bool:
    """ADR-0040 §5b's predicate as narrowed by ADR-0045 §5 — now ruling-aware.

    Clause 1 (any fold onto a ``USER_ASSERTED`` target) refuses under **both**
    rulings. The ``EXTERNAL`` clause (a ``USER_ASSERTED`` proposal onto an
    ``EXTERNAL`` target) is refused only for ``REINFORCE``: the same ``SUPERSEDE``
    is now permitted, because it mints a fresh id rather than inheriting the
    external one (ADR-0045 §4). Every other pairing is permitted.
    """
    if target is MemorySource.USER_ASSERTED:
        return True
    return (
        kind is MemoryDecisionKind.REINFORCE
        and incoming is MemorySource.USER_ASSERTED
        and target is MemorySource.EXTERNAL
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

    async def test_supersede_retires_the_target_and_writes_a_new_id_correction(
        self, make_writer: WriterFactory
    ) -> None:
        """``SUPERSEDE`` retires the target and writes the proposal at a fresh id.

        ADR-0045 §5a's rewrite: the target is **retained with a closed window**
        (hidden from ``get``, kept in ``export``) and the live record is the
        proposed record — carrying nothing of the target — written at an id
        **absent from the store**, returned as ``record_id`` (neither the target's
        nor the proposal's own). Target and proposal differ in every settable
        field, and "take nothing across" is complete, so the stored correction must
        equal the proposed record with only its id replaced.
        """
        store = FakeMemoryStore(now=_after_close)
        # Target INFERRED (supersedable, so neither refusal fires); content a
        # superset of the proposal's terms, so the conflict is found; no expiry, so
        # the far-forward store clock does not retire it before the window does.
        target = PreferenceMemory(
            id="existing",
            content="prefers concise emails, an older note",
            preference="older preference",
            context="stale-context",
            strength=0.1,
            expires_at=None,
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
            expires_at=datetime(2200, 6, 1, tzinfo=UTC),
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.6,
                evidence=["p-ev"],
                last_updated=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        )
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(proposed))

        assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
        # The live record's id is the minted one — not the target's, not "new".
        assert result.record_id == "corrected"
        # Target retained with a closed window: hidden from get, present in export.
        assert await store.get("existing") is None
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", "corrected"}
        assert retained["existing"].validity.valid_until is not None
        assert retained["existing"].validity.live_at(_AFTER_CLOSE) is False
        # The rest of the target is otherwise untouched (only its window moved).
        assert retained["existing"].content == target.content
        assert set(retained["existing"].provenance.evidence) == {"t-ev"}
        # The correction is the proposed record, only its id changed (and its window
        # reset to open, which the proposal already had), at an id that named no
        # record before — so it overwrote nothing.
        stored = await store.get("corrected")
        assert stored == proposed.model_copy(update={"id": "corrected"})
        # The proposal's own id is discarded, never written at.
        assert await store.get("new") is None

    @pytest.mark.parametrize(
        "proposal_window",
        [
            Validity(valid_until=datetime(2000, 1, 1, tzinfo=UTC)),  # producer-set, already closed
            Validity(valid_from=datetime(2200, 1, 1, tzinfo=UTC)),  # producer-set, not yet open
        ],
        ids=["proposal-already-closed", "proposal-not-yet-open"],
    )
    async def test_supersede_gives_the_correction_a_fresh_open_window(
        self, make_writer: WriterFactory, proposal_window: Validity
    ) -> None:
        """The correction is written with a fresh open window (ADR-0045 §4).

        The whole point of a supersession is to install a *live* belief. A proposal
        may carry a producer-set ``validity`` (the public type permits a closed or
        future-dated window); if that survived onto the correction, the target would
        be retired and the correction already hidden or not yet live — no live belief
        at all. The applier overrides it with an open window, so the correction is
        live at the store's read clock regardless of what the proposal supplied.
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        proposed = _preference("new", evidence=("p-ev",)).model_copy(
            update={"validity": proposal_window}
        )
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(proposed))

        assert result.record_id == "corrected"
        live = await store.get("corrected")
        # Live at the store's read clock: would be None if the proposal's closed or
        # future window had survived onto the correction.
        assert live is not None
        assert live.validity.valid_from is None
        assert live.validity.valid_until is None
        assert "p-ev" in live.provenance.evidence

    async def test_supersede_discards_the_proposal_id_and_clobbers_no_record_there(
        self, make_writer: WriterFactory
    ) -> None:
        """Case (a): the proposal's own id already names a live, non-target record.

        The applier mints its own id and discards ``proposed.id``, so the unrelated
        record living at that id is left intact — writing at ``proposed.id`` would
        silently clobber it (ADR-0045 §4).
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED, evidence=("t-ev",)))
        occupant = _episodic("new", "an unrelated memory that happens to share the id")
        await store.add(occupant)
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=("p-ev",))))

        assert result.record_id == "corrected"
        # The record at the proposal's id is untouched — not clobbered.
        assert await store.get("new") == occupant
        # Target retired, correction live at the minted id.
        assert await store.get("existing") is None
        live = await store.get("corrected")
        assert live is not None
        assert "p-ev" in live.provenance.evidence

    async def test_supersede_re_mints_a_colliding_id_then_succeeds(
        self, make_writer: WriterFactory
    ) -> None:
        """Case (b): the first minted id collides; the applier mints again.

        Insert-if-absent, not a blind upsert (ADR-0045 §4): the colliding record is
        rejected — never overwritten — and the correction lands at the next free id.
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        await store.add(_episodic("taken", "occupies the id the factory mints first"))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted("taken", "free"),
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=("p-ev",))))

        assert result.record_id == "free"  # the first mint collided, re-minted
        collided = await store.get("taken")
        assert collided is not None
        assert collided.content == "occupies the id the factory mints first"  # not clobbered
        assert await store.get("existing") is None  # target retired
        live = await store.get("free")
        assert live is not None
        assert "p-ev" in live.provenance.evidence

    async def test_supersede_re_mints_when_the_minted_id_is_the_target_itself(
        self, make_writer: WriterFactory
    ) -> None:
        """Case (b-bis): the minted id equals the retained target's own id.

        The target is a *stored* record, so its id is one the correction must not be
        written at (ADR-0045 §4, "the retained target T included"). This is the one
        collision a naive applier misses: the two-element batch would name the
        target's id twice, which ``write_atomic`` rejects as a hard
        ``MemoryStoreError`` (a repeated id, ADR-0046 §3), not the retryable conflict
        it is — so the applier detects it up front and re-mints instead of aborting.
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted("existing", "corrected"),
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=("p-ev",))))

        assert result.record_id == "corrected"  # re-minted past the target's own id
        assert await store.get("existing") is None  # target retired, not clobbered
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", "corrected"}
        live = await store.get("corrected")
        assert live is not None
        assert "p-ev" in live.provenance.evidence

    async def test_supersede_may_mint_the_proposal_id_when_it_is_absent(
        self, make_writer: WriterFactory
    ) -> None:
        """A minted id equal to the *unstored* proposal id is permitted (ADR-0045 §4).

        The obligation is "absent from the store," not "differs from the proposal's
        id." When the proposal's own id names no stored record, nothing lives there
        to clobber, so a factory that mints exactly it succeeds — the id is
        immaterial as long as it is absent. The counterpart is
        ``test_supersede_discards_the_proposal_id_and_clobbers_no_record_there``,
        where the proposal id *does* name a live record and so must be avoided.
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        # "new" (the proposal's id) names no stored record; the factory mints it.
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("new")
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=("p-ev",))))

        assert result.record_id == "new"  # permitted: nothing was stored at "new"
        assert await store.get("existing") is None  # target retired
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", "new"}
        live = await store.get("new")
        assert live is not None
        assert "p-ev" in live.provenance.evidence

    async def test_supersede_with_an_always_colliding_factory_leaves_the_target_live(
        self, make_writer: WriterFactory
    ) -> None:
        """Case (c): the factory always collides; the applier gives up, target live.

        After a bounded number of re-mints the applier raises ``MemoryStoreError``,
        and — because the whole ``SUPERSEDE`` is one atomic batch — the window-close
        rolls back with it, so the target is left **live and unchanged** (ADR-0045
        §4/§8).
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED, evidence=("t-ev",)))
        await store.add(_episodic("wall", "always in the way"))
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_always("wall")
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new")))

        target = await store.get("existing")
        assert target is not None  # still live: window never closed
        assert target.validity.valid_until is None
        assert set(target.provenance.evidence) == {"t-ev"}
        collided = await store.get("wall")
        assert collided is not None  # the collided record is intact

    @pytest.mark.parametrize(
        "factory",
        [_raises_id, _empty_id, _non_str_id, _hostile_subclass_id, _hostile_typed_id],
        ids=["raises", "empty", "non-str", "hostile-str-subclass", "hostile-metaclass"],
    )
    async def test_supersede_with_a_malformed_id_factory_writes_nothing(
        self, make_writer: WriterFactory, factory: Callable[[], str]
    ) -> None:
        """Case (d): a raising or non-``str``/empty factory raises before any write.

        The output guard turns the factory's own failure into ``MemoryStoreError``
        *before* the atomic write, so the two writers cannot diverge on a malformed
        factory and the store is left byte-for-byte unchanged, the target live
        (ADR-0045 §4).
        """
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=MemorySource.INFERRED, evidence=("t-ev",)))
        before = await store.export()
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=factory
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new")))

        assert await store.export() == before  # nothing written
        target = await store.get("existing")
        assert target is not None
        assert target.validity.valid_until is None  # target left live

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
        """The whole §5b predicate as narrowed by ADR-0045 §5, over the source matrix.

        For *every* ``(ruling, incoming source, target source)`` triple: clause 1
        (a fold onto a ``USER_ASSERTED`` target) and a ``USER_ASSERTED``
        *reinforcement* of an ``EXTERNAL`` target raise and leave the store
        byte-for-byte unchanged; every other pairing — the same *supersession* of an
        ``EXTERNAL`` target now included — is *applied*. "Applied" means it reached
        the store, so a writer that returned an id without writing is caught; the
        proposal carries evidence the target lacks, which the stored record proves.
        The two rulings apply *differently* (ADR-0045 §4): ``REINFORCE`` folds at the
        target's id; ``SUPERSEDE`` retires the target and writes a new-id correction.
        """
        # A far-forward store clock so a SUPERSEDE's window-close is observable
        # through get (the target's records carry no expiry to confound it).
        store = FakeMemoryStore(now=_after_close)
        await store.add(_preference("existing", source=target))
        writer = make_writer(store, FakeMemoryPolicy(kind))
        before = await store.export()
        proposal = _proposal(_preference("new", source=incoming, evidence=("p-ev",)))

        if _fold_is_refused(kind, incoming, target):
            with pytest.raises(MemoryStoreError):
                await writer.ingest(proposal)
            # Write nothing: the whole store is unchanged, so a writer that
            # mutated the target and *then* raised is caught, not only one that
            # stored the proposal as new.
            assert await store.export() == before
            return

        result = await writer.ingest(proposal)

        assert result.decision.kind is kind

        if kind is MemoryDecisionKind.REINFORCE:
            # Folded in place at the target's id, which is returned; no second record
            # at the proposal's id.
            assert result.record_id == "existing"
            assert await store.get("new") is None
            stored = await store.get("existing")
            assert stored is not None
            assert "p-ev" in stored.provenance.evidence
            return

        # SUPERSEDE: the target is retired (window closed, hidden from get, kept in
        # export) and the correction lands at a fresh id, returned as record_id. The
        # id differs from the target's (the retained target is a separate record),
        # but the ADR pins only "absent from the store"; whether it happens to equal
        # the *unstored* proposal id "new" is immaterial (ADR-0045 §4), so the suite
        # asserts the store's *shape* — exactly {target, correction} — not that the
        # id avoids "new". The default uuid factory makes it a fresh id here anyway.
        assert result.record_id is not None
        assert result.record_id != "existing"
        assert await store.get("existing") is None
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", result.record_id}
        assert retained["existing"].validity.valid_until is not None  # window closed
        live = await store.get(result.record_id)
        assert live is not None
        assert "p-ev" in live.provenance.evidence

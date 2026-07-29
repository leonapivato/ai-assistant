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

Three refusals are pinned besides, each stated on what a writer can observe:

* **Evidence must resolve** (ADR-0077 §5). A ``DERIVED`` proposal citing a record
  the store does not hold raises ``UnresolvedEvidenceError`` naming the id, with
  nothing written and no ruling sought. It is deliberately **not** a floor on
  citing *nothing* — that rule is the ``MemoryPolicy``'s (ADR-0072 §3), so an
  ``ASSERTED`` or ``EXTERNAL`` proposal citing nothing passes here untouched.
  Because it *is* a floor on citing something absent, every derived proposal below
  cites :data:`_CITED`, which :func:`_cite` plants.
* **Resolve or refuse** (ADR-0079 §1). A writer's conflict limit is a ceiling, not
  a truncation budget: above it ``ingest`` raises ``MemoryStoreError`` with nothing
  written, no window closed, and the policy not asked. Stated relative to *the
  writer's own* limit, which is why :class:`WriterFactory` carries the seam — the
  suite sets one to make the boundary observable and asserts nothing about what
  the value should be.
* **An unrepresentable close refuses** (ADR-0080 §3), whole, leaving every record
  in the retirement set byte-identical.

``REINFORCE`` and ``SUPERSEDE`` are pinned *differentially* (ADR-0040 §5a, as the
mechanism half is rewritten by ADR-0045 §5):

* ``REINFORCE`` folds at the target's id, mints no second record, and retains
  **both** records' ``evidence``, returning the target's id.
* ``SUPERSEDE`` (ADR-0045 §4/§5a) leaves the target **retained with a closed
  validity window** and writes the proposed record — carrying nothing of the
  target, with a **fresh open window** so the correction is live — at an id
  **absent from the store**, so it overwrites no existing record. Since ADR-0079
  §3 it retires **the whole ruled-on set**, not the named target alone: that
  target — ``EXTERNAL`` included, where a policy names one explicitly — plus every
  other conflict whose source is supersedable, with ``USER_ASSERTED`` and
  ``EXTERNAL`` *siblings* left live. Each retirement **clamps** rather than
  extends: the window closes at the earlier of the writer's close instant and the
  record's own ``valid_until``, ``valid_from`` untouched (ADR-0080 §1).
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
  and ``test_fake_writer.py``). ``export`` keeps the target **regardless of its
  validity window**, but still only while non-expired (a record past ``expires_at``
  is excluded there too, ADR-0007 §3/ADR-0045 §6). An absolute,
  clock-coherence-independent hide guarantee is deferred to issue #460 (split out
  of #306 by ADR-0080 §9, which leaves this semantics exactly as ADR-0045 §6 has
  it).

Both must also refuse the unsafe folds (§5b as narrowed by ADR-0045 §5): **clause
1** — any fold onto a ``USER_ASSERTED`` target — stays record-keyed for **both**
rulings; the **``EXTERNAL``** clause is **narrowed to ``REINFORCE``** — a
``USER_ASSERTED`` proposal *reinforcing* an ``EXTERNAL`` target still raises, while
the same *supersession* is now permitted and writes a new-id correction. Every
other pairing is permitted, which the suite exercises as well as those it refuses.

It deliberately does **not** pin the conflict threshold, the *value* of the
conflict limit, the constructor's tuning check, or — for ``REINFORCE`` — which
content wins and how confidence combines: those are one implementation's tuning
and `memory`'s semantics, and a suite that pinned them would stop being a
contract. Only the behaviour *at* the ceiling is contract, which is why the seam
sets a limit and asserts nothing about it (ADR-0079 §3/§4).

Nor does it pin clock handling: a writer with no clock at all conforms, so
``MemoryIngestor``'s naive-clock guard is asserted in ``test_ingest.py`` where it
belongs (ADR-0028 §4b). That constraint is what shapes the two ADR-0080
obligations below — "never extend" is stated as an **inequality** against the
planted end, which every conforming writer satisfies whatever its clock reads, and
the unrepresentable close is stated as an observable **disjunction** rather than as
a required raise (ADR-0080 §7). Two things follow and both are accepted: the suite
cannot force the refusal branch, and it cannot see whether a stamped close instant
*is* a writer's own reading of one. Driving the exact clamp and the exact refusal
against an **injected** clock — the advancing-clock and tie regressions — is
therefore each writer's own job, in ``test_ingest.py`` and ``test_fake_writer.py``.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import MemoryStoreError, UnresolvedEvidenceError
from ai_assistant.core.protocols import MemoryWriter
from ai_assistant.core.types import (
    DataTier,
    EpisodicMemory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
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
    """Builds the writer under test over the store, policy, and two optional knobs.

    A callable rather than a ready-made writer because a writer hides its own
    store and policy (see the class docstring). Both knobs are keyword-only and
    optional, and ``None`` leaves the writer's own default in each case:

    * ``id_factory`` — most obligations do not care which id a ``SUPERSEDE``
      mints, but the id-factory cases (ADR-0045 §5) drive it deterministically, so
      the factory must reach the writer's constructor.
    * ``conflict_limit`` — the same argument, for the same reason (ADR-0079 §4):
      the resolve-or-refuse obligation is not observable without it, and the
      multi-conflict obligations need a ceiling above the set they plant. The
      suite sets a limit to make a boundary observable; it asserts **nothing**
      about what the value should be, so the limit stays tuning.

    No clock seam is exposed — the suite deliberately does not pin clock handling
    (a writer with no clock at all conforms). The obligations below are stated so
    they need none: an inequality for the clamp, an observable disjunction for the
    refusal (ADR-0080 §7). Driving the exact clamp and the exact refusal against an
    **injected** clock is each concrete writer's own regression, not this suite's.
    """

    def __call__(
        self,
        store: MemoryStore,
        policy: MemoryPolicy,
        *,
        id_factory: IdFactory | None = None,
        conflict_limit: int | None = None,
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

#: A producer-set end far past any plausible writer clock, so a target planted with
#: it is a live conflict at ``_WHEN`` and its retirement can only clamp *downwards*
#: (ADR-0080 §1). Read at exactly this instant the retired record is gone: the
#: window is half-open, so ``valid_until`` itself is exclusive.
_SELF_CLOSE = datetime(2050, 1, 1, tzinfo=UTC)

#: A producer-set *start* after ``_fixed_now``-shaped writer clocks, so closing at
#: the writer's instant would form the empty-or-inverted window ADR-0080 §3 refuses.
_NOT_YET_OPEN = datetime(2026, 9, 1, tzinfo=UTC)

#: A store read clock at or after :data:`_NOT_YET_OPEN`, so a record planted with
#: that start is *live* and therefore surfaces as a conflict at all.
_AT_OR_AFTER_F = datetime(2026, 10, 1, tzinfo=UTC)

#: The record every ``DERIVED`` proposal below cites, planted by :func:`_cite`.
#: ADR-0077 §5 refuses a derived proposal whose ``evidence`` names a record the
#: store does not hold, so a suite driving derived proposals has to plant what they
#: cite — otherwise it would be exercising the refusal rather than the obligation
#: under test. It is ``EPISODIC``, so kind-scoped conflict detection never returns
#: it as a conflict for the preference proposals below.
_CITED = "cited-episode"

#: How high the ceiling is set for the multi-conflict obligations: above the sets
#: they plant, so the boundary those cases exercise is the *retirement* rule and
#: not ADR-0079 §1's refusal. Nothing is asserted about the value (ADR-0079 §4).
_ROOMY_CEILING = 10


async def _cite(store: MemoryStore) -> str:
    """Plant the episode a ``DERIVED`` proposal's ``evidence`` names, returning its id."""
    await store.add(_episodic(_CITED, "the exchange a derived proposal rests on"))
    return _CITED


def _long_ago() -> datetime:
    return _LONG_AGO


def _after_close() -> datetime:
    return _AFTER_CLOSE


def _at_or_after_f() -> datetime:
    return _AT_OR_AFTER_F


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
            evidence=evidence,
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


class _SupersedeNamingPolicy:
    """Rules ``SUPERSEDE`` naming a chosen conflict, whatever retrieval ranked first.

    ``FakeMemoryPolicy`` always names ``conflicts[0]``, which cannot express
    ADR-0079 §4's obligation 1a — a ruling whose named target is the ``EXTERNAL``
    record rather than the best-ranked one — nor pin which member of a retirement
    set is the *named* target and which are swept in behind it.
    """

    def __init__(self, target_id: str) -> None:
        self._target_id = target_id
        self.calls = 0

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Supersede, naming the conflict this policy was built to name."""
        self.calls += 1
        return MemoryDecision(
            kind=MemoryDecisionKind.SUPERSEDE,
            target_id=self._target_id,
            reason="contract: a named target",
        )


#: The ids :func:`_plant_conflict_set` gives the two supersedable siblings — the
#: ones ADR-0050 §1's widening sweeps in behind whatever target a ruling names.
_SWEPT_IN = ("sib-observed", "sib-inferred")

#: And the two it holds out of the widening under every ruling (ADR-0050 §1): a
#: record the user gave us, and one an integration reported.
_HELD_OUT = ("sib-asserted", "sib-external")


async def _plant_conflict_set(store: MemoryStore, *, target_source: MemorySource) -> None:
    """Plant a five-record conflict set: a named ``target`` and one sibling per source.

    Every record carries :data:`_CONTENT`, so all five are conflicts of the
    proposals below and the ruling's reach — rather than retrieval's — is what the
    obligations observe. ``target_source`` varies so the same shape drives both the
    ordinary supersession and ADR-0079 §4's obligation 1a, where the *named* target
    is ``EXTERNAL`` and its sibling must still be spared.
    """
    await store.add(_preference("target", source=target_source, evidence=("t-ev",)))
    await store.add(_preference("sib-observed", source=MemorySource.OBSERVED))
    await store.add(_preference("sib-inferred", source=MemorySource.INFERRED))
    await store.add(_preference("sib-asserted", source=MemorySource.USER_ASSERTED))
    await store.add(_preference("sib-external", source=MemorySource.EXTERNAL))


#: How long :class:`_SuspendingPolicy` waits for ``decide`` to be reached before
#: declaring the scenario broken. Generous — only hit when a case has already hung.
_GATE_SECONDS = 5.0

#: Content sharing no term with ``_CONTENT``, so a proposal mutated to it is
#: unmistakably a *different* belief from the one conflicts were detected for.
_UNRELATED = "keeps a canoe in the garage"

#: What a failure of the input-observation case below means, in one place
#: (ADR-0065): the writer read the caller's proposal more than once and the reads
#: disagreed, so what it retired and what it stored describe two different beliefs.
_TORN_PROPOSAL = (
    "ingest derived its outcome from more than one observation of the proposal: the "
    "conflicts it resolved and the ruling it applied describe one version, and the "
    "record it wrote describes another — beliefs retired over a statement that was "
    "never stored"
)


class _SuspendingPolicy:
    """Rules on the proposal, then suspends *inside* ``decide`` until released.

    ADR-0065 §3's lever for ``MemoryWriter``, and it needs no new hook: a writer
    hides its store and its policy, so the suite already has to hand it both
    (ADR-0028 §4), and a policy that suspends is therefore a window **every**
    conforming writer must reach. Its position needs no clause either — ``ingest``
    resolves conflicts before it asks and writes after, so a suspension inside
    ``decide`` necessarily falls between the two reads the clause is about. That
    ordering is not an assumption about any one writer; it is what
    ``test_conflicts_are_resolved_before_the_policy_is_asked`` already enforces.

    The proposal and the conflicts are copied *before* the suspension, so
    :attr:`ruled_on` is the version the ruling was actually derived from —
    whatever the caller does to its own object next.
    """

    def __init__(self, kind: MemoryDecisionKind) -> None:
        """Rule with ``kind`` (through :class:`FakeMemoryPolicy`), then suspend."""
        self._delegate = FakeMemoryPolicy(kind)
        self.ruled_on: MemoryUpdateProposal | None = None
        self.conflicts: tuple[MemoryRecord, ...] = ()
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Capture what is being ruled on, rule, then hold the writer here."""
        self.ruled_on = proposal.model_copy(deep=True)
        self.conflicts = tuple(record.model_copy(deep=True) for record in conflicts)
        decision = await self._delegate.decide(proposal, conflicts=conflicts)
        self._entered.set()
        await self._released.wait()
        return decision

    async def reached(self) -> None:
        """Wait until the writer is suspended inside ``decide``."""
        async with asyncio.timeout(_GATE_SECONDS):
            await self._entered.wait()

    def release(self) -> None:
        """Let the writer finish; idempotent."""
        self._released.set()


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
        # ADR-0068 §1: `conflicts` is populated on the real ingest path via
        # `model_copy(update=...)`, which skips validation — so the ingestor must
        # pre-build a tuple, or a mutable list would be installed past the frozen
        # proposal. A `list` here would fail the equality (`["existing"] !=
        # ("existing",)`); the `isinstance` pins it unambiguously.
        assert policy.last_proposal.conflicts == ("existing",)
        assert isinstance(policy.last_proposal.conflicts, tuple)

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
        await _cite(store)
        await store.add(_preference("existing", evidence=("t-ev",)))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        result = await writer.ingest(
            _proposal(_preference("new", confidence=0.9, evidence=(_CITED,)))
        )

        assert result.decision.kind is MemoryDecisionKind.REINFORCE
        assert result.record_id == "existing"
        assert {record.id for record in await store.export()} == {"existing", _CITED}
        stored = await store.get("existing")
        assert stored is not None
        assert set(stored.provenance.evidence) == {"t-ev", _CITED}

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
        await _cite(store)
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
                evidence=("t-ev",),
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
                evidence=(_CITED,),
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
        assert set(retained) == {"existing", "corrected", _CITED}
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
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        proposed = _preference("new", evidence=(_CITED,)).model_copy(
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
        assert _CITED in live.provenance.evidence

    async def test_supersede_discards_the_proposal_id_and_clobbers_no_record_there(
        self, make_writer: WriterFactory
    ) -> None:
        """Case (a): the proposal's own id already names a live, non-target record.

        The applier mints its own id and discards ``proposed.id``, so the unrelated
        record living at that id is left intact — writing at ``proposed.id`` would
        silently clobber it (ADR-0045 §4).
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED, evidence=("t-ev",)))
        occupant = _episodic("new", "an unrelated memory that happens to share the id")
        await store.add(occupant)
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        # The record at the proposal's id is untouched — not clobbered.
        assert await store.get("new") == occupant
        # Target retired, correction live at the minted id.
        assert await store.get("existing") is None
        live = await store.get("corrected")
        assert live is not None
        assert _CITED in live.provenance.evidence

    async def test_supersede_re_mints_a_colliding_id_then_succeeds(
        self, make_writer: WriterFactory
    ) -> None:
        """Case (b): the first minted id collides; the applier mints again.

        Insert-if-absent, not a blind upsert (ADR-0045 §4): the colliding record is
        rejected — never overwritten — and the correction lands at the next free id.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        await store.add(_episodic("taken", "occupies the id the factory mints first"))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted("taken", "free"),
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "free"  # the first mint collided, re-minted
        collided = await store.get("taken")
        assert collided is not None
        assert collided.content == "occupies the id the factory mints first"  # not clobbered
        assert await store.get("existing") is None  # target retired
        live = await store.get("free")
        assert live is not None
        assert _CITED in live.provenance.evidence

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
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted("existing", "corrected"),
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"  # re-minted past the target's own id
        assert await store.get("existing") is None  # target retired, not clobbered
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", "corrected", _CITED}
        live = await store.get("corrected")
        assert live is not None
        assert _CITED in live.provenance.evidence

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
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        # "new" (the proposal's id) names no stored record; the factory mints it.
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("new")
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "new"  # permitted: nothing was stored at "new"
        assert await store.get("existing") is None  # target retired
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", "new", _CITED}
        live = await store.get("new")
        assert live is not None
        assert _CITED in live.provenance.evidence

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
        # Planted whatever the incoming source, so the setup is one shape: a
        # derived proposal's citation must resolve (ADR-0077 §5), and an asserted
        # or external one is unaffected by carrying a citation that does.
        await _cite(store)
        await store.add(_preference("existing", source=target))
        writer = make_writer(store, FakeMemoryPolicy(kind))
        before = await store.export()
        proposal = _proposal(_preference("new", source=incoming, evidence=(_CITED,)))

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
            assert _CITED in stored.provenance.evidence
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
        assert set(retained) == {"existing", result.record_id, _CITED}
        assert retained["existing"].validity.valid_until is not None  # window closed
        live = await store.get(result.record_id)
        assert live is not None
        assert _CITED in live.provenance.evidence

    # --- the full-conflict ruling and its ceiling (ADR-0079 §4) -------------

    @pytest.mark.parametrize(
        "target_source",
        [MemorySource.INFERRED, MemorySource.EXTERNAL],
        ids=["named-target-derived", "named-target-external"],
    )
    async def test_supersede_retires_the_whole_ruled_on_supersedable_set(
        self, make_writer: WriterFactory, target_source: MemorySource
    ) -> None:
        """Obligations 1 and 1a: the named target *and* every supersedable sibling.

        ADR-0079 §3 promotes ADR-0050 §1's retirement set into the contract, and
        both halves of its phrasing are load-bearing. **The named target is
        retired whatever its source** — ADR-0045 §5b permits a ``SUPERSEDE`` onto
        an ``EXTERNAL`` record and ADR-0050 §1 rules that one a policy names
        explicitly *is* retired — which the ``named-target-external`` case is here
        to pin, because a promotion phrased as "every supersedable conflict" alone
        would silently release a conforming writer from it. **The supersedable
        siblings are retired too**, which is the widening itself: retiring only the
        policy's best-ranked target leaves a second and third stale belief live on
        the topic.

        And the two held-out sources stay live under either ruling: topical
        similarity may not retire a record the user gave us (ADR-0045 §5), and
        adopting ``EXTERNAL`` supersession is a separate deferred policy choice —
        so an ``EXTERNAL`` *sibling* survives even in the case where an
        ``EXTERNAL`` *target* does not.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await _plant_conflict_set(store, target_source=target_source)
        policy = _SupersedeNamingPolicy("target")
        writer = make_writer(
            store,
            policy,
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await store.export()}
        for retired_id in ("target", *_SWEPT_IN):
            # Window closed: off the read path at a clock at or after the close,
            # and still present in `export` (ADR-0045 §6).
            assert await store.get(retired_id) is None
            assert retained[retired_id].validity.valid_until is not None
            assert retained[retired_id].validity.live_at(_AFTER_CLOSE) is False
        for spared_id in _HELD_OUT:
            spared = await store.get(spared_id)
            assert spared is not None
            assert spared.validity.valid_until is None
        # The correction is a fresh record naming none of the retired ones.
        assert result.record_id not in {"target", *_SWEPT_IN}
        correction = await store.get("corrected")
        assert correction is not None
        assert _CITED in correction.provenance.evidence

    async def test_an_unmintable_multi_target_supersede_leaves_every_target_live(
        self, make_writer: WriterFactory
    ) -> None:
        """Obligation 2: all-or-nothing across the whole set, not just the target.

        ADR-0045 §8's floor generalised to N. With an always-colliding id factory
        the applier gives up after its bounded re-mints, and because the N window
        closes and the correction's insert are **one** atomic batch, every record
        in the set is left byte-identical — not some retired with no replacement.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await _plant_conflict_set(store, target_source=MemorySource.INFERRED)
        await store.add(_episodic("wall", "always in the way"))
        before = await store.export()
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_always("wall"),
            conflict_limit=_ROOMY_CEILING,
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert await store.export() == before
        for record_id in ("target", *_SWEPT_IN):
            live = await store.get(record_id)
            assert live is not None
            assert live.validity.valid_until is None

    async def test_supersede_re_mints_when_the_minted_id_names_a_swept_in_conflict(
        self, make_writer: WriterFactory
    ) -> None:
        """Obligation 3: the minted id may name **no** retired record, not just the target.

        The existing "re-mints when the minted id is the target itself" case,
        generalised to the widened set. Every retired record is *stored*, so the
        correction written beside them may name none of them: a repeated id in the
        batch is ``write_atomic``'s hard error (ADR-0046 §3), not the retryable
        conflict a re-mint handles, so an applier that only checked the named
        target would abort a supersession the ADR requires it to retry.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await _plant_conflict_set(store, target_source=MemorySource.INFERRED)
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_scripted("sib-inferred", "corrected"),
            conflict_limit=_ROOMY_CEILING,
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"  # re-minted past a swept-in conflict
        retained = {record.id: record for record in await store.export()}
        # The record whose id was minted is retired, not clobbered by the correction.
        assert retained["sib-inferred"].validity.valid_until is not None
        assert retained["sib-inferred"].content == _CONTENT
        assert await store.get("sib-inferred") is None
        assert await store.get("corrected") is not None

    async def test_a_conflict_set_above_the_writers_ceiling_refuses_before_any_ruling(
        self, make_writer: WriterFactory
    ) -> None:
        """Obligation 4: resolve or refuse — a correction resolves every conflict it is shown.

        Stated relative to *the writer's own* limit, so no value is pinned: the
        seam drives one low and plants more conflicts than that. The refusal fires
        in conflict resolution, before any ruling is sought, so the policy is not
        asked at all — which is what makes it a statement about the ingest's
        *inputs* rather than an outcome a policy weighed.

        And it is stated on the conflicts the writer's own retrieval **surfaced**,
        which is all a suite running over ``FakeMemoryStore`` can observe; whether
        a durable store's retrieval is itself threshold-complete is a different
        obligation with a different owner (issue #457).
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        for index in range(3):
            await store.add(_preference(f"existing-{index}", source=MemorySource.INFERRED))
        before = await store.export()
        policy = FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE)
        writer = make_writer(store, policy, conflict_limit=2)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert policy.call_count == 0  # no ruling was sought
        assert await store.export() == before  # nothing written, no window closed
        for index in range(3):
            live = await store.get(f"existing-{index}")
            assert live is not None
            assert live.validity.valid_until is None

    # --- the retirement clamp (ADR-0080 §7) ---------------------------------

    async def test_a_retirement_never_extends_the_targets_own_window(
        self, make_writer: WriterFactory
    ) -> None:
        """Obligation 1: the close is never *later* than the record's own end.

        ADR-0080 §1's clamp, stated as an **inequality** against the planted end
        rather than as an equality against a close instant — which is what lets it
        hold for every conforming writer whatever its clock reads, in a suite that
        deliberately pins no writer clock. Writing ``now`` over an earlier
        producer-set end would push a self-closed belief back onto the read path
        for ``[valid_until, now)``: retirement takes a belief off the read path and
        never puts one back.

        ``valid_from`` is asserted too, because §1 preserves *every* other field: a
        retirement narrows one end of the envelope and moves nothing else.
        """
        read_at = [_WHEN]  # store read clock, mutable; starts before the planted end
        store = FakeMemoryStore(now=lambda: read_at[0])
        await _cite(store)
        await store.add(
            PreferenceMemory(
                id="existing",
                content=_CONTENT,
                preference=_CONTENT,
                validity=Validity(valid_until=_SELF_CLOSE),
                provenance=Provenance(
                    source=MemorySource.INFERRED, confidence=0.6, last_updated=_WHEN
                ),
            )
        )
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await store.export()}
        end = retained["existing"].validity.valid_until
        assert end is not None
        assert end <= _SELF_CLOSE  # never extended past the producer's own end
        assert retained["existing"].validity.valid_from is None  # the start did not move
        # Read at the planted end: off the read path, still in `export`.
        read_at[0] = _SELF_CLOSE
        assert await store.get("existing") is None
        assert all(record.id != "existing" for record in await store.search(_CONTENT))
        live = await store.get("corrected")
        assert live is not None
        assert live.validity.valid_from is None
        assert live.validity.valid_until is None

    async def test_an_unrepresentable_close_refuses_whole_or_closes_lawfully(
        self, make_writer: WriterFactory
    ) -> None:
        """Obligations 2 and 3: the exhaustive disjunction, with no third outcome.

        A retirement set holding a target planted with ``valid_from = F`` **and**
        an ordinary open-window sibling, read from a store clock at or after ``F``
        so both are live conflicts. ADR-0080 §7 states this as a disjunction rather
        than as a required raise, because the suite fixes no writer clock and a
        writer whose close instant falls after ``F`` lawfully succeeds:

        - **either** ``ingest`` raised and **every** record in the set is
          byte-identical to what was planted — no window closed, no correction
          written, no id minted (§3, §6);
        - **or** it succeeded, and both planted records — neither of which carries
          a ``valid_until`` of its own, so §1's clamp leaves both at the writer's
          own end — were retired with the **same** ``valid_until``, and that
          instant is strictly after ``F``, which is exactly the case where the
          window was representable.

        Both conjuncts on the success branch are load-bearing. Requiring one shared
        end rules out per-target clock sampling — a writer that closed the
        future-dated target before ``F`` (persisting the inverted window ``[F,
        earlier)``, which ``model_copy(update=...)`` constructs without re-running
        ``Validity``'s validator) and then sampled again past ``F`` for the sibling
        would satisfy a weaker assertion about the sibling alone. Requiring each
        retired window to be well-formed rules that persisted inversion out
        directly rather than by inference, which the suite must do itself: it runs
        over ``FakeMemoryStore``, so ``SqliteMemoryStore``'s decode re-validation is
        not there to catch it.

        What this cannot reach is stated rather than implied: it cannot force the
        refusal branch, and it cannot see that a stamped instant is a writer's own
        reading of a clock. The clock-injected clamp, refusal and tie regressions
        are each writer's own (§7).
        """
        store = FakeMemoryStore(now=_at_or_after_f)
        await _cite(store)
        await store.add(
            PreferenceMemory(
                id="future",
                content=_CONTENT,
                preference=_CONTENT,
                validity=Validity(valid_from=_NOT_YET_OPEN),
                provenance=Provenance(
                    source=MemorySource.INFERRED, confidence=0.6, last_updated=_WHEN
                ),
            )
        )
        await store.add(_preference("sibling", source=MemorySource.INFERRED))
        before = await store.export()
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("sibling"),
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
        )
        proposal = _proposal(_preference("new", evidence=(_CITED,)))

        # Captured rather than asserted in the handler, so which branch the writer
        # took is decided once, below, where both branches read side by side.
        outcome: MemoryIngestResult | None = None
        refusal: MemoryStoreError | None = None
        try:
            outcome = await writer.ingest(proposal)
        except MemoryStoreError as raised:
            refusal = raised

        if refusal is not None:
            # ADR-0080 §7: this refusal is about a *target's window*, never an
            # evidence failure, so it must not arrive as the subclass ADR-0077 §5
            # took for that other question.
            assert not isinstance(refusal, UnresolvedEvidenceError)
            assert await store.export() == before
            assert await store.get("corrected") is None
            return

        assert outcome is not None
        retained = {record.id: record for record in await store.export()}
        assert outcome.record_id == "corrected"
        ends = {retained[record_id].validity.valid_until for record_id in ("future", "sibling")}
        assert len(ends) == 1  # one close instant recorded across the whole set
        (shared_end,) = ends
        assert shared_end is not None
        assert shared_end > _NOT_YET_OPEN  # the window was representable after all
        for record_id in ("future", "sibling"):
            window = retained[record_id].validity
            assert window.valid_until is not None
            if window.valid_from is not None:
                assert window.valid_until > window.valid_from  # well-formed, never inverted

    # --- evidence must resolve (ADR-0077 §5) --------------------------------

    async def test_a_derived_proposal_citing_a_record_the_store_lacks_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """The writer's floor: a citation that does not resolve refuses the ingest.

        A raise rather than a fabricated ``REJECT``, because a ruling is the
        policy's to make (ADR-0005 §3) — which is why the policy must not have been
        asked. The named subclass carries the unresolved ids, so a stage can
        compare them against the batch it selected and tell an evidence record that
        went away under it from a producer citing something it was never handed.
        """
        store = FakeMemoryStore(now=_long_ago)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        before = await store.export()
        policy = FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
        writer = make_writer(store, policy)

        with pytest.raises(UnresolvedEvidenceError) as caught:
            await writer.ingest(_proposal(_preference("new", evidence=("gone",))))

        assert "gone" in caught.value.unresolved_ids
        assert policy.call_count == 0  # refused before any ruling was sought
        assert await store.export() == before
        assert await store.get("new") is None

    async def test_a_derived_proposal_whose_citations_resolve_is_unaffected(
        self, make_writer: WriterFactory
    ) -> None:
        """The other side of the floor: a citation the store holds passes untouched."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert result.record_id == "new"
        assert await store.get("new") is not None

    @pytest.mark.parametrize("source", [MemorySource.USER_ASSERTED, MemorySource.EXTERNAL], ids=str)
    async def test_an_asserted_or_external_proposal_citing_nothing_is_unaffected(
        self, make_writer: WriterFactory, source: MemorySource
    ) -> None:
        """The floor is scoped to the ``DERIVED`` band, and to citing *absently*.

        ADR-0072 §3 put the emptiness rule at the ``MemoryPolicy`` gate precisely
        so the writer would not constrain records that legitimately cite nothing:
        the user's own word is its own warrant, and an integration's report is
        that system's. An empty tuple also names no record that fails to resolve,
        so it has nothing for this check to refuse.
        """
        store = FakeMemoryStore(now=_long_ago)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_proposal(_preference("new", source=source)))

        assert result.record_id == "new"
        assert await store.get("new") is not None

    # --- input observation (ADR-0065) ---------------------------------------

    async def test_ingest_cannot_tear_on_a_mid_flight_mutation_of_its_proposal(
        self, make_writer: WriterFactory
    ) -> None:
        """The single-proposal ``ingest`` tear is unrepresentable under ADR-0068.

        ``ingest`` reads the caller's proposal to find conflicts, hands it to the
        policy to rule on, and reads it a third time to decide what to write.
        ADR-0065's input clause guarded the window between the first read and the
        last against a caller mutating the record it still holds — a ``SUPERSEDE``
        desync being the sharpest form, where beliefs contradicting the *searched*
        content are retired while a correction is built from the content read
        *last*. Freezing ``MemoryUpdateProposal`` and ``MemoryRecord`` makes that
        stimulus unrepresentable (ADR-0068 §4): the mid-flight mutation raises
        rather than tearing, so the three reads necessarily see one belief. The
        clause survives only for the ``Sequence`` arguments (``decide``'s
        ``conflicts``), not for this single-value one.
        """
        store = FakeMemoryStore(now=_after_close)
        # INFERRED so neither fold refusal fires; content a superset of the
        # proposal's terms so the conflict is found; no expiry so the far-forward
        # store clock does not retire it before the window does.
        target = _preference(
            "existing", "prefers concise emails, an older note", source=MemorySource.INFERRED
        )
        await store.add(target)
        policy = _SuspendingPolicy(MemoryDecisionKind.SUPERSEDE)
        writer = make_writer(store, policy, id_factory=_scripted("corrected"))
        proposal = _proposal(_preference("new"))

        call = asyncio.ensure_future(writer.ingest(proposal))
        try:
            await policy.reached()
            with pytest.raises(ValidationError):
                proposal.proposed.content = _UNRELATED  # frozen: the caller cannot rewrite it
        finally:
            policy.release()
        result = await call

        ruled_on = policy.ruled_on
        assert ruled_on is not None
        # The conflicts the ruling was made on are the ones the writer found for
        # the version it ruled on, and they are named on that proposal (ADR-0028).
        assert [record.id for record in policy.conflicts] == ["existing"]
        assert list(ruled_on.conflicts) == ["existing"]
        # And the record installed is that same version — every field of it, not
        # just the content, at the minted id with the fresh open window a
        # supersession always gives (ADR-0045 §4).
        assert result.record_id == "corrected"
        written = await store.get("corrected")
        assert written is not None
        assert written == ruled_on.proposed.model_copy(
            update={"id": "corrected", "validity": Validity()}
        ), _TORN_PROPOSAL
        # The belief retired is the one that contradicted what was actually stored.
        retained = {record.id: record for record in await store.export()}
        assert set(retained) == {"existing", "corrected"}
        assert retained["existing"].validity.live_at(_AFTER_CLOSE) is False

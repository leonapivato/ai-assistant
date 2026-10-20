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

Four refusals are pinned besides, each stated on what a writer can observe:

* **Evidence must resolve** (ADR-0077 §5). A ``DERIVED`` proposal citing a record
  the store does not hold raises ``UnresolvedEvidenceError`` naming the id, with
  nothing written and no ruling sought. It is deliberately **not** a floor on
  citing *nothing* — that rule is the ``MemoryPolicy``'s (ADR-0072 §3), so an
  ``ASSERTED`` or ``EXTERNAL`` proposal citing nothing passes here untouched.
  Because it *is* a floor on citing something absent, every derived proposal below
  cites :data:`_CITED`, which :func:`_cite` plants.
* **No write consumes the evidence its own proposal cites** (ADR-0081 §1), in
  three limbs. A ruling that **installs** the proposal at an id the proposal cites
  raises ``MemoryStoreError`` — nothing written, no window closed, no decision
  returned — whether or not a record stands at that id and for **every** band. A
  ``SUPERSEDE``, whose destination is *minted*, re-mints past a cited candidate
  instead, and raises only when its own bound is exhausted, leaving every target
  live. And a ``SUPERSEDE`` whose **retirement set** holds a cited record still
  retires it and still lands, *where the ruling is otherwise admissible*: this rule
  adds no refusal to ``SUPERSEDE`` and removes none, so a cited ``USER_ASSERTED``
  target is still refused by ADR-0045 §5 clause 1.
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
  other conflict whose source is in the retirement class, which since ADR-0092 §4
  is ``{OBSERVED, INFERRED, EXTERNAL}``, with ``USER_ASSERTED`` *siblings* left live
  save by ADR-0078 §5b's confirmed batch. **Two relation-side narrowings cut that
  set down**, and neither touches the class: a member the writer holds ``RESTATES``
  or ``ADDS`` for is never in it (ADR-0159 §5), and — where the crossing produced a
  labelled contradiction at all — a member the writer holds **no** relation for is
  left live too (ADR-0171 §2). Where the crossing produced none, which is every
  ingest ADR-0159 §2 excludes from reconciliation, the obligation binds exactly as
  ADR-0079 §3 states it. Each retirement **clamps** rather than
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

Both must also refuse the unsafe folds (§5b as narrowed by ADR-0045 §5, ADR-0121 §5
and ADR-0214 §3): **clause 1** — any fold onto a ``USER_ASSERTED`` target — stays
record-keyed
for **both** rulings; the **``EXTERNAL``** clause is **narrowed to ``REINFORCE``** —
a ``USER_ASSERTED`` proposal *reinforcing* an ``EXTERNAL`` target still raises, while
the same *supersession* is now permitted and writes a new-id correction. Every
other pairing is permitted, which the suite exercises as well as those it refuses.

**Clause 1 has a second exception since ADR-0121 §5**, and it is the only fold onto
an assertion that needs no confirmation: a ``REINFORCE`` which **agrees** with the
target — equal ``kind``, and equal ``content`` after NFC, case folding, whitespace
collapse and stripping (ADR-0121 §1) — and whose incoming record is ``USER_ASSERTED``,
``OBSERVED`` or ``INFERRED``. The last two are ADR-0214 §3's widening of that one
condition, and it changes no other: the ruling is still ``REINFORCE``, the records
must still agree, and an ``EXTERNAL`` proposal is still refused. The predicate is
**verified at the writer, never trusted from the ruling**, so a disagreeing
``REINFORCE`` is refused whatever a policy claims. The permitted fold's *survivor*
is contract here too — the stored target with its ``content``, ``source``,
confidence, attestation, window and expiry unchanged, taking the incoming record's
evidence and confirming instant (ADR-0214 §4, subsuming ADR-0121 §4's second clause)
— which is the one place this suite pins what a ``REINFORCE`` writes, because it is
the exception's own safety argument rather than tuning. Since ADR-0214 §3 it is also
what stops the widened fold *demoting* the assertion: the survivor keeps the
target's ``source``, so a fold from an observation leaves the record in the
``ASSERTED`` band (ADR-0038 §2a).

**That reinforce refusal is the one ADR-0092 §5 exists to protect.** §4 put
``EXTERNAL`` in the retirement class the widening above uses, and a writer that
performed the widening by widening *one* shared constant would silently stop
refusing this fold — reopening the ADR-0038 §2a data loss as a one-line change
that passes every other case here. The two sets answer different questions
(what a correction may retire; what an assertion may fold onto at the target's
own id), so the suite states both and
:meth:`~MemoryWriterContract.test_an_assertion_still_may_not_reinforce_an_external_record`
pins the second on its own, where a merged constant fails visibly.

It deliberately does **not** pin the conflict threshold, the *value* of the
conflict limit, the constructor's tuning check, or — for ``REINFORCE`` — which
content wins and how confidence combines: those are one implementation's tuning
and `memory`'s semantics, and a suite that pinned them would stop being a
contract. The single exception is the fold clause 1 permits onto an assertion,
whose survivor ADR-0121 §5's third clause states in terms; everywhere else the fold's
composition stays `memory`'s. Only the behaviour *at* the ceiling is contract,
which is why the seam sets a limit and asserts nothing about it (ADR-0079 §3/§4).

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

**ADR-0329's additions are pinned as stated, on the record each write leaves.**
``record_use`` adds one track-record entry conditionally on the revision read and
changes nothing for an episode already recorded (§14:4). A proposal carrying a retiring
operation is ruled on over every conflict but the memory it retires; an ``ACCEPT``
installs and retires in one write, each naming the other, a ``REINFORCE`` of an end or
a mark wrong adds the supports and retires naming no successor, and every other ruling
writes nothing (§12:4); the refusals of §12:5, ADR-0328 §4:6 and §6:5 leave the store
as it was. An observer's inference is admitted only in §9:7's two shapes.

This module is intentionally not named ``test_*`` so pytest does not collect the
abstract base directly; it is collected via a ``Test``-prefixed subclass.
"""

from __future__ import annotations

import asyncio
import zlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import (
    MemoryStoreConflictError,
    MemoryStoreError,
    MemoryStoreStaleError,
    SelfConsumingWriteError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.protocols import MemoryWriter
from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    ConflictRelation,
    DataTier,
    EpisodicMemory,
    InputPart,
    Memory,
    MemoryChange,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryOperation,
    MemoryOperationKind,
    MemoryRecord,
    MemoryRetirement,
    MemorySource,
    MemoryStanding,
    MemoryStatus,
    MemorySupport,
    MemoryUpdateProposal,
    MemoryWriterName,
    OpenQuestion,
    OpenQuestionKind,
    Provenance,
    QuestionPart,
    SupportDirection,
    SupportOrigin,
    SupportPart,
    TrackRecordEntry,
    UserConfirmation,
    Validity,
    band_of,
)
from ai_assistant.memory._reconciler import ReconcilerOutcome
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore
from ai_assistant.testing.memories import (
    confirmed_support,
    inference_support,
    legacy_support,
    memory,
    remembered_support,
    said_support,
    sourced_support,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.protocols import MemoryPolicy, MemoryStore

    #: Mints the id a ``SUPERSEDE`` writes its correction at (ADR-0045 §4).
    type IdFactory = Callable[[], str]


class StubReconciler(Protocol):
    """The reconciler seam ADR-0159 §5's ``ADDS`` half is driven through.

    Stated here rather than imported from either writer, for the reason ADR-0159 §2
    gives for keeping it out of ``core/protocols.py`` at all: it is a
    ``memory``-internal seam, and the canonical fake carries its own copy (golden
    rule 1). A shared suite needs a shape both writers accept, and this is it.

    The suite never asserts what a reconciler answers — that is ADR-0159 §3's
    contract and is pinned per implementation. What it asserts is what a *writer*
    does with the relations it ends up holding.

    **The two writers read a determination differently, and the shape here is the
    one both accept.** Since ADR-0164 §3 ``MemoryIngestor`` reads an outcome report
    beside the relations; the canonical fake predates it and reads a bare mapping,
    and ADR-0164 §7 rules that neither the fake nor this suite is reached by that
    ADR — the fake emits no trace and this suite asserts none. So the answer is
    :class:`_Determination`, which *is* the mapping and *carries* the report, and
    the divergence stays where it belongs: in what each writer chooses to read.
    """

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> _Determination:
        """Label what can be labelled, keyed by ``MemoryRecord.id``."""
        ...


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

    * ``reconciler`` — ADR-0159 §5's ``ADDS`` half is not observable without one:
      that relation is a *model's* determination, and a writer computes only the
      ``agrees`` half for itself. The suite injects a stub rather than a model, so
      no obligation here turns on a provider being reachable, and it asserts
      nothing about what a reconciler should answer — only what a writer does with
      what it holds. ``None`` leaves the writer with the certain rung alone, which
      is the state every ``agrees``-half case below runs in.

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
        reconciler: StubReconciler | None = None,
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

#: What the ``ATTESTED`` band must carry since ADR-0092 §1. The suite pins nothing
#: about its *contents* — the obligations here are about what a ruling reaches, not
#: about what a source said — so one value serves every ``EXTERNAL`` record and
#: :func:`_preference` attaches it from the band.
_ATTESTED_BY = Attestation(reported_by="source-instance", reported_at=_WHEN)

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

#: A second episode a case plants where a target and a proposal must rest on
#: different parts (ADR-0328 §4:8).
_OTHER_CITED = "other-cited-episode"

#: How high the ceiling is set for the multi-conflict obligations: above the sets
#: they plant, so the boundary those cases exercise is the *retirement* rule and
#: not ADR-0079 §1's refusal. Nothing is asserted about the value (ADR-0079 §4).
_ROOMY_CEILING = 10

#: The ceiling the #1302 conv-50 case needs: above the **thirteen** members that
#: crossing offered, so what it exercises is ADR-0171 §2's narrowing and not
#: ADR-0079 §1's refusal. Held apart from :data:`_ROOMY_CEILING` rather than raising
#: it, so every other multi-conflict case keeps the set size it was written for.
_AUDIT_CEILING = 20


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


def _unstamped(record: MemoryRecord) -> MemoryRecord:
    """``record`` with its store-authored ``revision`` back at the default.

    A record a store returned never equals the record a case constructed, because
    ADR-0219 §1 makes ``revision`` store-authored: the store issues one for the write
    that stored the row and discards whatever the submitted record carried. The cases
    below compare *whole* records deliberately — an id-only check would pass a write
    that committed the wrong row — so the one store-authored field is stripped rather
    than the comparison weakened. What the writer does with the stamp is ADR-0219 §5's
    second change and is asserted there, not here.
    """
    return record.model_copy(update={"revision": 0})


def _unstamped_or_none(record: MemoryRecord | None) -> MemoryRecord | None:
    """:func:`_unstamped`, for a read whose answer may legitimately be ``None``."""
    return None if record is None else _unstamped(record)


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


def _support(  # noqa: PLR0913 — the band, the episode, and the part's and dates' axes
    source: MemorySource,
    episode: str,
    *,
    owner: str,
    index: int,
    when: datetime | None,
    added_at: datetime,
) -> MemorySupport:
    """One support pointing into ``episode``, in the band ``source`` names (ADR-0328 §12).

    ``USER_ASSERTED`` is the user's message, ``EXTERNAL`` a source's evidence item
    carrying :data:`_ATTESTED_BY`, and ``OBSERVED`` or ``INFERRED`` a remember call.
    The part is keyed on ``owner`` (the memory's id) and ``index``, so two memories
    in one case rest on different parts of the same episode — a supersession ends its
    target with the correction's first support, which the target must not carry
    already (ADR-0328 §11:7).
    """
    position = zlib.crc32(owner.encode()) % 100_000 + index * 100_000
    match band_of(source):
        case BeliefBand.ASSERTED:
            return said_support(episode, when=when, added_at=added_at).model_copy(
                update={"points_at": InputPart(episode=episode, message=position)}
            )
        case BeliefBand.ATTESTED:
            return sourced_support(
                _ATTESTED_BY, episode=episode, item=position, when=when, added_at=added_at
            )
        case BeliefBand.DERIVED:
            return remembered_support(
                episode, effect=f"effect-{owner}-{index}", when=when, added_at=added_at
            )
        case _:  # pragma: no cover - exhaustive
            raise AssertionError(source)


def _preference(  # noqa: PLR0913 — one keyword per record axis a case may vary
    record_id: str,
    content: str = _CONTENT,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    evidence: tuple[str, ...] = (),
    last_updated: datetime = _WHEN,
    last_confirmed_at: datetime | None = None,
) -> Memory:
    """A memory stating ``content``, resting on one support per episode it rests on.

    The supports point at ``evidence``'s episodes, or at :data:`_CITED` where it names
    none — ADR-0328 §4:7 refuses a support pointing at an episode the store does not
    hold, whatever the band, so every case plants :data:`_CITED` (:func:`_cite`).
    ``last_updated`` dates each support's addition and the create, so it is the
    memory's transaction time (§7:8); ``last_confirmed_at`` is the supports' ``when``.
    """
    supports = tuple(
        _support(
            source,
            episode,
            owner=record_id,
            index=index,
            when=last_confirmed_at if last_confirmed_at is not None else last_updated,
            added_at=last_updated,
        )
        for index, episode in enumerate(evidence or (_CITED,))
    )
    return memory(record_id, content, *supports)


async def _memories(store: MemoryStore) -> list[MemoryRecord]:
    """What ``store`` exports, less its episodes: the memories a writer wrote."""
    return [record for record in await store.export() if isinstance(record, Memory)]


async def _snapshot(store: MemoryStore) -> list[MemoryRecord]:
    """Everything ``store`` exports, episodes included: what a refused write leaves alone.

    A no-write assertion compares this whole, because the episodes a proposal's supports
    point at are state a writer could damage on a refused path as much as any memory
    (ADR-0328 §5:11, §11:8).
    """
    return list(await store.export())


def _proposal(record: Memory) -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=record, rationale="because", sensitivity=DataTier.PERSONAL)


#: The two rulings that name a target record and fold the proposal against it.
_FOLD_KINDS = [MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE]

#: The incoming sources clause 1's agreeing-fold exception admits (ADR-0121 §5 as
#: widened by ADR-0214 §3). Written out here rather than imported from either writer:
#: a suite reading the implementation's own constant would pass any widening of it,
#: and this set **is** what §5b obliges both writers to agree on.
_AGREEING_FOLD_INCOMING = frozenset(
    {MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED}
)


#: The order of the standings each band's one support ranks at here (ADR-0328 §6:1): a
#: said memory above a sourced one above an inference.
_BAND_RANK = {BeliefBand.DERIVED: 0, BeliefBand.ATTESTED: 1, BeliefBand.ASSERTED: 2}


def _fold_is_refused(
    kind: MemoryDecisionKind, incoming: MemorySource, target: MemorySource, *, agrees: bool
) -> bool:
    """§5b's predicate as narrowed by ADR-0045 §5, ADR-0121 §5 and ADR-0214 §3.

    Ruling-aware since ADR-0045 §5, and **agreement-aware** since ADR-0121 §5.

    Clause 1 (any fold onto a ``USER_ASSERTED`` target) refuses under both rulings,
    with one exception and one only: a ``REINFORCE`` which **agrees** with the target
    under ADR-0121 §1 and whose incoming record is ``USER_ASSERTED``, ``OBSERVED`` or
    ``INFERRED`` — the last two admitted by ADR-0214 §3, which widens ADR-0121 §5's
    single ``USER_ASSERTED`` condition and changes no other. ``EXTERNAL`` is not
    among them: an agreeing import folded onto an assertion is refused exactly as it
    was, because the reason ADR-0121 §3 keeps ``EXTERNAL`` out is about what a write
    at a foreign idempotency key does and identity of content does nothing to it. The
    ``EXTERNAL`` clause (a ``USER_ASSERTED`` proposal onto an ``EXTERNAL`` target)
    is refused only for ``REINFORCE``, because a ``SUPERSEDE`` mints a fresh id
    rather than inheriting the external one (ADR-0045 §4) — and **agreement does
    nothing to it**, for ADR-0092 §5's reason: the next routine sync overwrites the
    fold whether or not the user's words matched the import's. Every other pairing
    is permitted, on either agreement axis.

    **ADR-0159 §5 adds one refusal, and it is a ``SUPERSEDE``'s** — a conflict the
    writer holds a ``RESTATES`` or ``ADDS`` relation for "is **never retired**, by
    any ruling, at any writer… and a writer that would retire it refuses the write
    instead". A writer determines ADR-0121 §1's agreement for itself with no model
    (§5's ``agrees`` half), on the ingests ADR-0159 §2 admits — a non-asserted
    proposal, no asserted member, and the admissibility floor clear. So an
    *agreeing* supersession from a non-asserted proposal is refused, whatever the
    target's source: superseding a record that says the same thing retires a live
    belief on the strength of a restatement, which is what §5 exists to stop.

    **ADR-0328 §6:5 adds one more, also a ``SUPERSEDE``'s**: the end it writes on the
    target cites the correction's first support, so a correction whose standing ranks
    below the target's — an inference correcting a source's report — is refused, and
    the open question it needs is the observer's to raise.

    **The asserted rows are untouched**, and that is ADR-0159 §2's invocation
    condition rather than a carve-out here: a ``USER_ASSERTED`` proposal determines
    no relations at all, so the writer holds none and ADR-0079 §3 binds it exactly
    as it always did. A ``USER_ASSERTED`` *target* is likewise outside the
    condition, and clause 1 already refuses every fold onto one.
    """
    if target is MemorySource.USER_ASSERTED:
        return not (
            agrees and kind is MemoryDecisionKind.REINFORCE and incoming in _AGREEING_FOLD_INCOMING
        )
    if (
        kind is MemoryDecisionKind.SUPERSEDE
        and agrees
        and incoming is not MemorySource.USER_ASSERTED
    ):
        return True  # ADR-0159 §5
    if (
        kind is MemoryDecisionKind.SUPERSEDE
        and _BAND_RANK[band_of(incoming)] < _BAND_RANK[band_of(target)]
    ):
        return True  # ADR-0328 §6:5: the end cites a support ranking below the target
    return (
        kind is MemoryDecisionKind.REINFORCE
        and incoming is MemorySource.USER_ASSERTED
        and target is MemorySource.EXTERNAL
    )


#: A content one token away from :data:`_CONTENT` — enough to be a *different*
#: belief under ADR-0121 §1, and close enough that :class:`FakeMemoryStore` still
#: ranks the target as a conflict: three of these four query terms appear in
#: ``_CONTENT``, which is exactly :data:`_DEFAULT_CONFLICT_THRESHOLD`. That
#: arithmetic is the point of the constant rather than an accident of it — the
#: adversarial case ADR-0121 §1 argues from is a one-token edit scoring at the *top*
#: of the ranking, and a refusal case that fell below the threshold would exercise
#: an empty conflict set instead of the predicate.
_DISAGREEING = "prefers concise formal emails"


def _correcting(
    record_id: str,
    *,
    source: MemorySource = MemorySource.OBSERVED,
    evidence: tuple[str, ...] = (),
) -> Memory:
    """A proposal carrying :data:`_DISAGREEING` — a *correction*, not a restatement.

    **Why the supersession cases below need it, since ADR-0159 §5.** A conflict a
    writer holds a ``RESTATES`` relation for is never retired, by any ruling, and a
    writer determines ADR-0121 §1's agreement for itself with no model. So a
    ``SUPERSEDE`` whose proposal carries :data:`_CONTENT` — the target's own content
    — is now *refused*, and the cases that only ever needed a conflict to exist
    would have been measuring that refusal instead of the mechanic each is about
    (the minted id, the fresh window, the clamp, the re-mint loop).

    Those cases always meant a correction; the agreeing content was how they got a
    conflict detected, and ``_DISAGREEING`` gets one just as well while saying what
    the fixture means. The refusal itself is pinned where it belongs — in
    :func:`_fold_is_refused`'s matrix and in the two ADR-0159 §5 cases of their own.
    """
    return _preference(
        record_id,
        _DISAGREEING,
        source=source,
        evidence=evidence,
    )


#: The same belief as :data:`_CONTENT`, differing only in the case and whitespace
#: ADR-0121 §1's four transformations are chosen to absorb. Used where a case must
#: show that the *target's own bytes* survive the permitted fold — against a proposal
#: equal to the target byte for byte, "the target's content survived" and "the
#: incoming content was written" are the same observation and the case pins nothing.
_RESTATED = "  Prefers   CONCISE\temails "

#: When the restatement was made and last confirmed: strictly later than
#: :data:`_WHEN` and still in the past of every plausible writer clock. The gap is
#: what makes §4's *positive* half observable — a writer that kept all the target's
#: fields would be indistinguishable from a conforming one if both records carried
#: the same instants (ADR-0109 §5's usability test is satisfied by both).
_RESTATED_AT = datetime(2026, 2, 1, tzinfo=UTC)

#: Restatements a writer implementing ADR-0121 §1 with ASCII ``str.lower`` and
#: ASCII whitespace handling would wrongly refuse. Each shares five of its six terms
#: with its target, so :class:`FakeMemoryStore` still ranks the target as a conflict
#: and the case exercises the *predicate* rather than conflict detection. The
#: `.lower()` writer is not a straw man: it is the obvious implementation, it passes
#: every other case in this suite, and ADR-0121 §6 makes the writer's recomputation
#: an *independent* obligation — a policy-side Unicode test cannot discharge it.
_UNICODE_RESTATEMENTS = [
    # NFC: precomposed U+00E9 against `e` + U+0301. The same text; a reader sees no
    # difference at all, and no case or whitespace rule reaches it.
    (
        "prefers concise emails from the caf\u00e9",
        "prefers concise emails from the cafe\u0301",
        "nfc",
    ),
    # Case *folding*, not lowering: "ß".casefold() is "ss", so these agree — while
    # "Straße".lower() is "straße" and never equals "strasse".
    (
        "prefers concise emails on the Stra\u00dfe",
        "prefers concise emails on the STRASSE",
        "case-fold",
    ),
    # Unicode whitespace: a no-break space is whitespace, and `str.split()` collapses
    # it. A run keyed on " " or on `str.strip()`'s ASCII default does not.
    ("prefers concise emails at the office", "prefers concise emails at\u00a0the office", "nbsp"),
]

#: The complete ``ruling`` by ``incoming source`` by ``target source`` by
#: ``agreement`` space, so the suite samples nothing: every combination is either
#: refused (write nothing) or applied (the fold reaches the store), per
#: :func:`_fold_is_refused`. The fourth axis is ADR-0121 §5's, and it is a full axis
#: rather than one extra case because the clause it pins is a *narrowing*: the
#: pairings agreement does **not** free — every ``SUPERSEDE`` onto an assertion, the
#: ``EXTERNAL`` reinforce refusal, every agreeing fold from an ``EXTERNAL`` proposal
#: — are what a later tidy-up would take with it. ADR-0214 §3 moves exactly two
#: cells of this space, from refused to applied, and the axis is what makes that
#: visible as two cells rather than as a rewritten predicate.
_FOLD_MATRIX = [
    (kind, incoming, target, agrees)
    for kind in _FOLD_KINDS
    for incoming in MemorySource
    for target in MemorySource
    for agrees in (True, False)
]


class _Determination(dict[str, ConflictRelation]):
    """A determination in the one shape both writers under test can read.

    It **is** the mapping, so the canonical fake reads it exactly as it read a
    ``dict`` before ADR-0164; and it carries ``relations`` and ``outcomes``, so
    ``MemoryIngestor`` reads it as the report ADR-0164 §3 requires. Reporting
    ``ANSWERED`` is what makes the labels installable at that writer: §3 discards a
    mapping whose report claims less than the labels beside it.

    A double rather than a change to the canonical fake, because ADR-0164 §7 rules
    that fake out of the lane in terms and its author does not hold that ground.
    Nothing about it is asserted here; it exists so that one stub can drive two
    writers whose seams have diverged, and the moment the fake grows a report of its
    own this class collapses back into a plain mapping.
    """

    @property
    def relations(self) -> Mapping[str, ConflictRelation]:
        """The labels, which are this object (ADR-0164 §3)."""
        return self

    @property
    def outcomes(self) -> frozenset[ReconcilerOutcome]:
        """The one outcome a conforming reconciler reports beside labels."""
        return frozenset({ReconcilerOutcome.ANSWERED})


class _LabellingReconciler:
    """A stub answering with fixed ADR-0159 §1 relations, keyed by record id.

    The suite asserts nothing about what a reconciler *should* answer — that is
    ADR-0159 §3's contract, pinned per implementation — so the stub is deliberately
    inert: no model, no rungs, no economics. What it makes observable is the half of
    §5's exclusion a writer cannot compute for itself.
    """

    def __init__(self, labels: Mapping[str, ConflictRelation]) -> None:
        self._labels = dict(labels)

    async def reconcile(
        self,
        proposal: MemoryUpdateProposal,
        conflicts: Sequence[MemoryRecord],
    ) -> _Determination:
        """Answer with this stub's fixed labels."""
        return _Determination(self._labels)


class _FoldToAbsentTargetPolicy:
    """Always asks to fold into a record that is not among the conflicts."""

    def __init__(self, kind: MemoryDecisionKind) -> None:
        self._kind = kind

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
        relations: Mapping[str, ConflictRelation] | None = None,
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
        relations: Mapping[str, ConflictRelation] | None = None,
    ) -> MemoryDecision:
        """Supersede, naming the conflict this policy was built to name."""
        self.calls += 1
        return MemoryDecision(
            kind=MemoryDecisionKind.SUPERSEDE,
            target_id=self._target_id,
            reason="contract: a named target",
        )


#: The ids :func:`_plant_conflict_set` gives the siblings in the **retirement
#: class** — the ones ADR-0050 §1's widening sweeps in behind whatever target a
#: ruling names. ``sib-external`` joined them in ADR-0092 §4, which partially
#: supersedes ADR-0050 §1's ``EXTERNAL`` hold-out: the widening's set is the
#: policy's retirement class, and ADR-0079 §3 states the obligation *intensionally*
#: — "every other conflict … **whose source is supersedable**" — so widening the
#: class widens the contract without ADR-0079 needing an edit.
_SWEPT_IN = ("sib-observed", "sib-inferred", "sib-external")

#: And the one it holds out of the widening under every ruling: a record the user
#: gave us. Topical similarity may not retire an assertion (ADR-0045 §5 clause 1),
#: and ADR-0038 §3's one-way asymmetry is untouched by ADR-0092 §4 — that ADR
#: widens what an *assertion* may retire and says nothing about who may retire an
#: assertion. The user's own answer is still the only exception (ADR-0078 §5b).
_HELD_OUT = ("sib-asserted",)


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
        relations: Mapping[str, ConflictRelation] | None = None,
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


# --- ADR-0078 §5's confirmation gate: the six inputs it must tell apart ------

#: The frozen conflict set a question is asked about in these cases. Held as data
#: rather than inlined because check 4 recomputes the ``question_key`` from *exactly*
#: this, so every honest confirmation below has to be issued against the same set the
#: proposal carries — which is what makes the two mismatch shapes expressible.
_FROZEN = ("asserted", "external")


def _confirmed(
    record: Memory, *, retires: tuple[str, ...], frozen: tuple[str, ...] = ("asserted",)
) -> MemoryUpdateProposal:
    """A proposal carrying an **honest** confirmation for its own question.

    Honest means the whole binding holds by construction, exactly as the coordinator
    builds it (ADR-0078 §5): the ``conflicts`` the proposal arrives with are the ids
    the question froze, and the ``question_key`` is recomputed from that very
    proposal, so checks 4 and 5 pass and only the check under test can fail.

    ``frozen`` is the set the question was asked about, and it is a parameter rather
    than a constant because check 5 bounds the authority by it: a case naming two
    assertions in ``retires`` has to have shown the user both, or it is testing
    check 5 by accident instead of the clause it means to.
    """
    proposal = MemoryUpdateProposal(
        proposed=record,
        rationale="because",
        sensitivity=DataTier.PERSONAL,
        conflicts=frozen,
    )
    return proposal.model_copy(update={"confirmation": _authority(proposal, retires)})


def _confirmed_memory(record_id: str, content: str = _CONTENT) -> Memory:
    """A memory resting on the user's yes to its wording (ADR-0328 §13:3).

    What a confirmed proposal carries: one ``confirmation`` support, so it stands at
    "you confirmed this wording" — above every memory it may end (§6:5).
    """
    return memory(record_id, content, confirmed_support(_CITED, when=_WHEN, added_at=_WHEN))


def _authority(proposal: MemoryUpdateProposal, retires: tuple[str, ...]) -> UserConfirmation:
    """The authority a claim would mint for ``proposal``'s own question."""
    return UserConfirmation(
        question=QuestionPart(round="q-1", part=1),
        question_key=proposal.question_key,
        confirmed_at=_WHEN,
        retires=retires,
    )


#: How one case mangles the honest proposal, so the six inputs read as a table
#: rather than as six near-identical bodies.
type _Mangle = Callable[[Memory], MemoryUpdateProposal]


def _no_confirmation(record: Memory) -> MemoryUpdateProposal:
    """No confirmation at all: clause 1 stands verbatim."""
    return _proposal(record)


def _retires_elsewhere(record: Memory) -> MemoryUpdateProposal:
    """Check 2: a confirmation whose ``retires`` does not name the target."""
    return _confirmed(record, retires=("external",), frozen=_FROZEN)


def _target_outside_the_live_set(record: Memory) -> MemoryUpdateProposal:
    """Check 3: the named target is not among the conflicts *this ingest* resolved.

    Driven by naming a record the store does not hold: it is in ``retires`` and in the
    frozen set, so only the live-set check can refuse it. A confirmation cannot
    authorise retiring a record the current ruling was not even made against.
    """
    proposal = MemoryUpdateProposal(
        proposed=record, rationale="because", conflicts=("asserted", "gone")
    )
    return proposal.model_copy(update={"confirmation": _authority(proposal, ("gone",))})


def _target_outside_the_frozen_set(record: Memory) -> MemoryUpdateProposal:
    """Check 5: every id in ``retires`` must have been among the conflicts *shown*.

    Check 3 requires a target to be in the live set; this requires it to have been in
    the set the user saw. Both, because the two can differ in either direction and the
    authority is bounded by the smaller one.
    """
    proposal = MemoryUpdateProposal(proposed=record, rationale="because", conflicts=())
    return proposal.model_copy(update={"confirmation": _authority(proposal, ("asserted",))})


def _a_different_question_same_id(record: Memory) -> MemoryUpdateProposal:
    """Check 4, shape one: **same proposed record id, different content**.

    The input an *id*-based binding waves through. A suite that varied the id instead
    would pass against exactly the weaker binding ADR-0078 rejected, because a
    proposal's record id is caller-minted and unique only once stored.
    """
    elsewhere = MemoryUpdateProposal(
        proposed=_preference(record.id, _UNRELATED), rationale="because", conflicts=_FROZEN[:1]
    )
    honest = MemoryUpdateProposal(proposed=record, rationale="because", conflicts=_FROZEN[:1])
    return honest.model_copy(update={"confirmation": _authority(elsewhere, ("asserted",))})


def _a_different_question_same_proposal(record: Memory) -> MemoryUpdateProposal:
    """Check 4, shape two: **identical proposal, different frozen conflict set**.

    Two questions with the same fingerprint, shown different conflicts, one's
    confirmation presented against the other's apply. The input a *fingerprint*
    binding waves through — and invisible to a suite that varies content, which is
    every natural way to write the case above.
    """
    broader = MemoryUpdateProposal(proposed=record, rationale="because", conflicts=_FROZEN)
    honest = MemoryUpdateProposal(proposed=record, rationale="because", conflicts=_FROZEN[:1])
    assert broader.proposal_fingerprint == honest.proposal_fingerprint
    assert broader.question_key != honest.question_key
    return honest.model_copy(update={"confirmation": _authority(broader, ("asserted",))})


class _RulesExactly:
    """A policy that rules exactly what it was told to, secret-tier included.

    ``FakeMemoryPolicy`` deliberately overrides a secret-tier proposal to ``ASK_USER``
    "because a fake that could be configured into violating its own conformance suite
    would be a trap" — which is right, and which makes it unable to express the input
    check 0 exists for. A ``MemoryPolicy`` reaches the writer through an injected seam
    and any conforming implementation may rule differently, so the boundary has to
    hold against one that does (ADR-0078 §5b).
    """

    def __init__(self, kind: MemoryDecisionKind) -> None:
        self._kind = kind

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
        relations: Mapping[str, ConflictRelation] | None = None,
    ) -> MemoryDecision:
        """Rule the configured kind, naming a target where the kind requires one."""
        if self._kind in {MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE}:
            return MemoryDecision(
                kind=self._kind, target_id=conflicts[0].id, reason="contract: an injected ruling"
            )
        if self._kind is MemoryDecisionKind.STORE_TEMPORARY:
            return MemoryDecision(
                kind=self._kind, ttl=timedelta(days=1), reason="contract: an injected ruling"
            )
        return MemoryDecision(kind=self._kind, reason="contract: an injected ruling")


def _bypassed_secret(record: Memory) -> MemoryUpdateProposal:
    """A ``DataTier.SECRET`` proposal built **past** its own validator.

    ``model_construct`` skips validation, which is the whole point of check 0: a
    validator is not a boundary, and the refusal that survives a bypass is the one at
    the seam that performs the write (ADR-0078 §5b).
    """
    return MemoryUpdateProposal.model_construct(
        proposed=record,
        rationale="because",
        sensitivity=DataTier.SECRET,
        conflicts=(),
        confirmation=None,
    )


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
        await _cite(store)
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

    @pytest.mark.parametrize(
        "kind",
        [kind for kind in MemoryDecisionKind if kind is not MemoryDecisionKind.STORE_TEMPORARY],
    )
    async def test_ingest_returns_the_conflict_ids_it_resolved_on_every_ruling(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """The result carries what the ruling was ruled *against* (ADR-0078 §4).

        The clause ADR-0078 §4 adds to ADR-0028 §8's list, and the reason it is a
        conformance obligation rather than an implementation detail: the writer
        resolves conflicts onto its **own** copy of the proposal, so the caller's
        proposal still carries an empty ``conflicts`` when ``ingest`` returns. A
        coordinator that enqueued the untouched original would satisfy every other
        clause in this suite and produce a question showing the user no conflicting
        assertion, an answer whose authority is empty, and a re-ingest that meets
        that assertion outside the authority and defers again — the user answers,
        and is asked the same thing.

        Parametrised over **every** ruling rather than a representative one, because
        "on every ruling" is the whole clause: the set is resolved before the policy
        is asked, so an implementation that attached it only where something was
        written would pass a sampled test and drop it on exactly the ``ASK_USER``
        this exists for. It is not a claim about *which* records conflict — that
        stays the implementation's tuning and is still excluded (ADR-0028 §8).
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("existing"))
        policy = FakeMemoryPolicy(kind)

        result = await make_writer(store, policy).ingest(_proposal(_correcting("new")))

        assert result.decision.kind is kind
        assert result.conflicts == ("existing",)
        # A tuple, not a list: the field is frozen on a frozen model, and a
        # mutable sequence installed past it would let a caller rewrite what a
        # question was asked about after the question was asked.
        assert isinstance(result.conflicts, tuple)

    async def test_accept_stores_the_record_and_returns_its_id(
        self, make_writer: WriterFactory
    ) -> None:
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_proposal(_preference("new")))

        assert result.decision.kind is MemoryDecisionKind.ACCEPT
        assert result.record_id == "new"
        # Stored by the time `ingest` returned: the result reports an id written,
        # so a writer that queued the proposal for later would be claiming
        # something this result type cannot say (ADR-0028 §Consequences).
        assert await store.get("new") is not None

    async def test_accept_installs_the_memory_as_its_producer_built_it(
        self, make_writer: WriterFactory
    ) -> None:
        """``ACCEPT`` installs the proposed memory, supports and create (ADR-0328 §11:5).

        The producer built the memory; the writer adds nothing to it and takes nothing
        from it, so what is stored is the proposal's memory with its store-authored
        revision.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        proposed = _preference("new", source=MemorySource.USER_ASSERTED)

        await make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)).ingest(
            _proposal(proposed)
        )

        assert _unstamped_or_none(await store.get("new")) == proposed

    async def test_a_store_temporary_ruling_is_refused_and_writes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0328 §10:3: no proposal is stored tentatively, from any policy.

        ``FakeMemoryPolicy`` answers a configured ``STORE_TEMPORARY`` with ``ACCEPT``,
        so the ruling is driven through :class:`_RulesExactly`, which rules exactly
        what it is told — the input a writer taking rulings from any injected policy
        must refuse.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, _RulesExactly(MemoryDecisionKind.STORE_TEMPORARY))

        with pytest.raises(MemoryStoreError, match="STORE_TEMPORARY"):
            await writer.ingest(_proposal(_preference("new")))

        assert await _memories(store) == []

    @pytest.mark.parametrize("kind", [MemoryDecisionKind.ACCEPT], ids=str)
    async def test_an_installing_ruling_at_an_already_stored_id_is_refused(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """The defect #630 filed, pinned as a refusal (ADR-0108 §1, §2, §3).

        An installing ruling says the proposal contradicts nothing retrieval
        surfaced, so an id that already names a stored record is an accident in
        every case — a minting producer whose factory collided. The standing record
        is **not** among the conflicts and never could be: conflict detection
        filters the proposal's own id (#110), so no ruling was ever made about the
        record a bare upsert would have destroyed.

        ``MemoryStoreConflictError`` specifically, and the assertion is explicit
        because the subclass **is** a ``MemoryStoreError``: the producer's remedy is
        the documented one — re-mint and re-propose — and a writer that raised the
        base class would tell it nothing it could act on.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        standing = _preference("collide", "the user drinks coffee")
        await store.add(standing)
        writer = make_writer(store, FakeMemoryPolicy(kind))

        with pytest.raises(MemoryStoreConflictError):
            await writer.ingest(_proposal(_preference("collide", "the user drinks tea")))

        # Nothing written, and nothing re-minted around the collision: the id is the
        # producer's, so a writer that minted another would edit a record the
        # producer made and report an id nobody proposed (ADR-0081 §9).
        assert [_unstamped(r) for r in await _memories(store)] == [standing]

    @pytest.mark.parametrize(
        "kind", [MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER], ids=str
    )
    async def test_a_declined_ruling_writes_nothing(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        before = await _snapshot(store)

        result = await make_writer(store, FakeMemoryPolicy(kind)).ingest(
            _proposal(_preference("new"))
        )

        assert result.decision.kind is kind
        assert result.record_id is None
        assert await _snapshot(store) == before

    async def test_reinforce_adds_the_proposals_supports_to_the_target(
        self, make_writer: WriterFactory
    ) -> None:
        """``REINFORCE`` adds each support to the target, one add support each (§11:6).

        It lands on the target's id, mints no second memory, leaves the target's
        wording and its own supports as they were, and records one ``add_support``
        operation per support it adds, citing that support.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        target = _preference("existing", evidence=(_OTHER_CITED,))
        await store.add(target)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))
        incoming = _preference("new")

        result = await writer.ingest(_proposal(incoming))

        assert result.decision.kind is MemoryDecisionKind.REINFORCE
        assert result.record_id == "existing"
        assert {record.id for record in await _memories(store)} == {"existing"}
        stored = await store.get("existing")
        assert isinstance(stored, Memory)
        assert stored.content == target.content
        assert [one.points_at for one in stored.supports] == [
            target.supports[0].points_at,
            incoming.supports[0].points_at,
        ]
        added = stored.operations[len(target.operations) :]
        assert [(one.kind, one.cites) for one in added] == [
            (MemoryOperationKind.ADD_SUPPORT, incoming.supports[0].points_at)
        ]

    async def test_reinforce_with_a_support_the_target_carries_changes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """§4:8: a support whose part the target already carries is not added again."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        target = _preference("existing")
        await store.add(target)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        await writer.ingest(
            _proposal(memory("new", "prefers concise emails again", target.supports[0]))
        )

        stored = await store.get("existing")
        assert isinstance(stored, Memory)
        assert stored.supports == target.supports
        assert stored.operations == target.operations

    async def test_reinforce_adds_every_new_support_past_one_the_target_carries(
        self, make_writer: WriterFactory
    ) -> None:
        """§11:6, §4:8: each support added, one add support each, a carried one skipped.

        The proposal's first support is one the target already carries and its next two
        are new: the carried one changes nothing, and both new ones land, in order, each
        with its own ``add_support`` citing it. A writer stopping at the first support,
        or at the first already-carried one, fails here.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        await store.add(_episodic("third-episode", "a third exchange"))
        target = _preference("existing")
        await store.add(target)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))
        fresh = _preference("new", evidence=(_OTHER_CITED, "third-episode")).supports
        incoming = memory("new", _CONTENT, target.supports[0], *fresh)

        result = await writer.ingest(_proposal(incoming))

        assert result.record_id == "existing"
        stored = await store.get("existing")
        assert isinstance(stored, Memory)
        assert [one.points_at for one in stored.supports] == [
            target.supports[0].points_at,
            *(one.points_at for one in fresh),
        ]
        added = stored.operations[len(target.operations) :]
        assert [(one.kind, one.cites) for one in added] == [
            (MemoryOperationKind.ADD_SUPPORT, one.points_at) for one in fresh
        ]

    async def test_supersede_ends_the_target_and_installs_the_correction_at_a_new_id(
        self, make_writer: WriterFactory
    ) -> None:
        """``SUPERSEDE`` (§11:7): the target ended, the correction installed fresh.

        The target is **ended** — an ``end`` citing the correction's first support,
        added to it as an ``against`` support that does not back it as worded, naming
        the correction as its successor — and retained with a closed window (hidden
        from ``get``, kept in ``export``). The correction is the proposed memory at an
        id absent from the store (neither the target's nor the proposal's own), with a
        fresh open window, its create naming the target among those it replaces.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        target = _preference(
            "existing", "prefers concise emails, an older note", evidence=(_OTHER_CITED,)
        )
        await store.add(target)
        proposed = _preference(
            "new",
            source=MemorySource.OBSERVED,
            last_updated=datetime(2026, 2, 1, tzinfo=UTC),
        ).model_copy(update={"expires_at": datetime(2200, 6, 1, tzinfo=UTC)})
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(proposed))

        assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
        assert result.record_id == "corrected"
        assert await store.get("existing") is None
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"existing", "corrected"}
        ended = retained["existing"]
        assert isinstance(ended, Memory)
        assert ended.status is MemoryStatus.ENDED
        assert ended.validity.live_at(_AFTER_CLOSE) is False
        assert ended.content == target.content
        end = ended.operations[-1]
        assert end.kind is MemoryOperationKind.END
        assert end.cites == proposed.supports[0].points_at
        assert end.successor == "corrected"
        against = ended.support_at(proposed.supports[0].points_at)
        assert against is not None
        assert against.direction is SupportDirection.AGAINST
        assert not against.backs_as_worded
        corrected = await store.get("corrected")
        assert isinstance(corrected, Memory)
        assert corrected.content == proposed.content
        assert corrected.supports == proposed.supports
        assert corrected.operations[0].replaces == ("existing",)
        assert corrected.expires_at == proposed.expires_at
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
        proposed = _correcting("new", evidence=(_CITED,)).model_copy(
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

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        # The record at the proposal's id is untouched — not clobbered.
        assert _unstamped_or_none(await store.get("new")) == occupant
        # Target retired, correction live at the minted id.
        assert await store.get("existing") is None
        live = await store.get("corrected")
        assert isinstance(live, Memory)
        assert live.content == _DISAGREEING

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

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "free"  # the first mint collided, re-minted
        collided = await store.get("taken")
        assert collided is not None
        assert collided.content == "occupies the id the factory mints first"  # not clobbered
        assert await store.get("existing") is None  # target retired
        live = await store.get("free")
        assert isinstance(live, Memory)
        assert live.content == _DISAGREEING

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

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"  # re-minted past the target's own id
        assert await store.get("existing") is None  # target retired, not clobbered
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"existing", "corrected"}
        live = await store.get("corrected")
        assert isinstance(live, Memory)
        assert live.content == _DISAGREEING

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

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "new"  # permitted: nothing was stored at "new"
        assert await store.get("existing") is None  # target retired
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"existing", "new"}
        live = await store.get("new")
        assert isinstance(live, Memory)
        assert live.content == _DISAGREEING

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
        await _cite(store)
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
        assert isinstance(target, Memory)
        assert target.status is MemoryStatus.CURRENT
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
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED, evidence=("t-ev",)))
        before = await _snapshot(store)
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=factory
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new")))

        assert await _snapshot(store) == before  # nothing written
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
        await _cite(store)
        writer = make_writer(store, _FoldToAbsentTargetPolicy(kind))

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new")))

        # Nothing written: the store is exactly as empty as it began.
        assert await _memories(store) == []

    @pytest.mark.parametrize(
        ("kind", "incoming", "target", "agrees"),
        _FOLD_MATRIX,
        ids=[
            f"{k}-{i}-onto-{t}-{'agreeing' if a else 'disagreeing'}" for k, i, t, a in _FOLD_MATRIX
        ],
    )
    async def test_every_fold_pairing_is_refused_or_applied_per_5b(
        self,
        make_writer: WriterFactory,
        kind: MemoryDecisionKind,
        incoming: MemorySource,
        target: MemorySource,
        agrees: bool,
    ) -> None:
        """The whole §5b predicate, as narrowed by ADR-0045 §5, ADR-0121 §5, ADR-0214 §3.

        For *every* ``(ruling, incoming source, target source, agreement)``
        combination: clause 1 (a fold onto a ``USER_ASSERTED`` target) and a
        ``USER_ASSERTED`` *reinforcement* of an ``EXTERNAL`` target raise and leave
        the store byte-for-byte unchanged; every other combination — the same
        *supersession* of an ``EXTERNAL`` target, and an **agreeing** ``REINFORCE``
        onto a ``USER_ASSERTED`` target from a ``USER_ASSERTED`` proposal (ADR-0121
        §5) or an ``OBSERVED`` or ``INFERRED`` one (ADR-0214 §3) — is *applied*.
        "Applied" means it reached the store, so a writer that returned an id
        without writing is caught; the proposal carries evidence the target lacks,
        which the stored record proves. The two rulings apply *differently*
        (ADR-0045 §4): ``REINFORCE`` folds at the target's id; ``SUPERSEDE`` retires
        the target and writes a new-id correction.

        **The agreement axis runs over every combination, not only the ones it
        frees.** Clause 1 is narrowed by exactly three cells of this space, and what
        a later tidy-up would take with it is everything the narrowing does *not*
        reach: a ``SUPERSEDE`` onto an assertion however verbatim the restatement,
        an ``EXTERNAL`` proposal agreeing with an assertion, the ``EXTERNAL``
        reinforce refusal under either content. Stating the axis over the whole
        matrix is what makes each of those a failing case rather than an absence.
        """
        # A far-forward store clock so a SUPERSEDE's window-close is observable
        # through get (the target's records carry no expiry to confound it).
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=target))
        writer = make_writer(store, FakeMemoryPolicy(kind))
        before = await _snapshot(store)
        # `_DISAGREEING` still ranks the target as a conflict (see the constant), so
        # the disagreeing half exercises the predicate rather than an empty set.
        proposal = _proposal(
            _preference(
                "new",
                _CONTENT if agrees else _DISAGREEING,
                source=incoming,
                evidence=(_CITED,),
            )
        )

        if _fold_is_refused(kind, incoming, target, agrees=agrees):
            with pytest.raises(MemoryStoreError):
                await writer.ingest(proposal)
            # Write nothing: the whole store is unchanged, so a writer that
            # mutated the target and *then* raised is caught, not only one that
            # stored the proposal as new.
            assert await _snapshot(store) == before
            return

        result = await writer.ingest(proposal)

        assert result.decision.kind is kind

        if kind is MemoryDecisionKind.REINFORCE:
            # Folded in place at the target's id, which is returned; no second record
            # at the proposal's id.
            assert result.record_id == "existing"
            assert await store.get("new") is None
            stored = await store.get("existing")
            assert isinstance(stored, Memory)
            # The target's wording stands; the proposal's support was added to it.
            assert stored.content == _CONTENT
            assert stored.support_at(proposal.proposed.supports[0].points_at) is not None
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
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"existing", result.record_id}
        assert retained["existing"].validity.valid_until is not None  # window closed
        live = await store.get(result.record_id)
        assert isinstance(live, Memory)
        assert live.content == proposal.proposed.content

    # --- clause 1's agreeing-fold exception, on its own ----------------------

    @pytest.mark.parametrize(
        "incoming",
        [MemorySource.USER_ASSERTED, MemorySource.OBSERVED, MemorySource.INFERRED],
        ids=["user_asserted", "observed", "inferred"],
    )
    async def test_an_agreeing_fold_writes_the_assertions_own_record_back(
        self, make_writer: WriterFactory, incoming: MemorySource
    ) -> None:
        """Clause 1's exception, and the fold rule that makes it safe.

        The matrix above pins that the fold is *permitted*. This pins **what it
        writes**, which is the whole of the exception's argument: ADR-0045 §5 clause
        1's two justifications are both about a fold that replaces or retires what
        the user told us, and the exception carves out exactly the case in which
        neither reaches, because the write puts the target's own bytes back at the
        target's own id — "not similar bytes, not normalised bytes: the same ones".

        So the suite states it, in spite of its own refusal to pin which content
        wins for a ``REINFORCE`` (ADR-0040 §5a leaves that unasserted). ADR-0121 §5's
        third normative clause is what changes: "A conforming writer performing the
        permitted fold writes it as §4's second clause specifies. A writer that would
        fold otherwise refuses instead." A suite that admitted the fold without
        pinning the survivor would certify a writer that overwrote an assertion
        through the one gate opened on the promise that it does not.

        **Run over all three admitted incoming sources** (ADR-0214 §3). The two
        ADR-0214 adds are the ones that carry a second obligation the assertion case
        cannot show: on the ordinary fold arm the survivor takes the *incoming*
        record's ``source``, so a writer that folded an ``OBSERVED`` proposal onto an
        assertion by that arm would leave the belief in the ``DERIVED`` band —
        ADR-0038 §2a's "from a non-asserted proposal it also downgrades the record's
        provenance out of the profile", performed through the one gate opened on the
        promise that it does not. With a ``USER_ASSERTED`` proposal both arms write
        the same ``source`` and the assertion below proves nothing about which ran.

        **The proposal differs from the target in case and whitespace**, which
        ADR-0121 §1's four transformations absorb. Against a byte-identical proposal
        "the target's content survived" and "the incoming content was written" are
        the same observation, and the case would pin nothing.

        **Both halves of §4's second clause are stated, and the timestamps are made
        distinguishable so the positive half can be seen at all.** The clause is a
        pair — what the incoming record does *not* contribute (content, source,
        confidence, attestation, window, expiry) and what it *does* (evidence,
        ``last_updated``, the confirming instant). A fixture giving both records the
        same instants tests only the first half, and a writer that special-cased the
        new arm by keeping *all* the target's fields would pass while storing stale
        currency — the very outcome ADR-0121's Consequences ("a restatement now
        refreshes currency") says this arm exists to produce, and which ADR-0214
        extends to a belief the user is merely watched still living out.

        **The confirming instant is asserted as a contribution, not as a composition
        rule.** ADR-0109 §9 declines to promote its currency composition to this
        suite — a writer composing differently still conforms — so the case plants
        the incoming instant strictly *later* than the target's and both in the past,
        where every admissible rule agrees on the answer. What fails is only a writer
        that discards the contribution, which is what §4 forbids.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(
            _preference(
                "theirs",
                source=MemorySource.USER_ASSERTED,
                evidence=("earlier-episode",),
                last_updated=_WHEN,
                last_confirmed_at=_WHEN,
            )
        )
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        incoming_memory = _preference(
            "new",
            _RESTATED,
            source=incoming,
            evidence=(_CITED,),
            last_updated=_RESTATED_AT,
            last_confirmed_at=_RESTATED_AT,
        )
        result = await writer.ingest(_proposal(incoming_memory))

        assert result.decision.kind is MemoryDecisionKind.REINFORCE
        # Folded at the target's id; no second record minted for the proposal.
        assert result.record_id == "theirs"
        assert await store.get("new") is None
        survivor = await store.get("theirs")
        assert isinstance(survivor, Memory)
        # The user's own words, byte for byte — not the proposal's spelling (§3:2).
        assert survivor.content == _CONTENT
        # The standing the user's word gives it, kept whatever the proposal's band:
        # the fold only adds a support, so it can never demote (ADR-0038 §2a).
        assert survivor.band is BeliefBand.ASSERTED
        assert survivor.status is MemoryStatus.CURRENT
        # Nothing retired: a REINFORCE closes no window (ADR-0045 §4).
        assert survivor.validity.valid_until is None
        assert survivor.expires_at is None
        # What the restatement contributes: its support, and with it the confirming
        # instant a belief the user repeats ages from (ADR-0121 §4, ADR-0328 §7:3).
        assert survivor.support_at(incoming_memory.supports[0].points_at) is not None
        assert survivor.as_of(_AFTER_CLOSE) == _RESTATED_AT

    @pytest.mark.parametrize(
        ("target_content", "restatement"),
        [(target, restatement) for target, restatement, _ in _UNICODE_RESTATEMENTS],
        ids=[label for _, _, label in _UNICODE_RESTATEMENTS],
    )
    async def test_the_writer_recomputes_the_predicate_over_unicode(
        self, make_writer: WriterFactory, target_content: str, restatement: str
    ) -> None:
        """ADR-0121 §1's Unicode limbs, at the boundary obliged to recompute them.

        §1 fixes four transformations and **three of them are Unicode operations**:
        NFC normalisation, Unicode *case folding* (not lowering), and collapse of
        Unicode whitespace runs. §6 has the writer compute the predicate
        independently of the policy and §5 has it verify rather than trust the
        ruling, so the obligation is the writer's own and no policy-side test can
        discharge it, however thorough.

        Each case is one an ASCII implementation gets wrong **in the refusing
        direction**: a writer using ``str.lower`` and ASCII whitespace passes every
        other case in this suite and then refuses a fold ADR-0121 §5 requires,
        leaving the user interrogated about agreeing with themselves — the exact harm
        the ADR exists to remove, reintroduced underneath a green suite.

        That direction is also why these belong here and not only in the matrix: the
        matrix's ``disagreeing`` axis catches a predicate that is too **wide**, and
        nothing else in this suite catches one that is too **narrow**.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("theirs", target_content, source=MemorySource.USER_ASSERTED))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        result = await writer.ingest(
            _proposal(
                _preference(
                    "new", restatement, source=MemorySource.USER_ASSERTED, evidence=(_CITED,)
                )
            )
        )

        # Admitted by the writer's own recomputation, and folded at the target's id.
        assert result.decision.kind is MemoryDecisionKind.REINFORCE
        assert result.record_id == "theirs"
        assert await store.get("new") is None
        survivor = await store.get("theirs")
        assert isinstance(survivor, Memory)
        # Still the user's own spelling, which is what makes the fold permissible.
        assert survivor.content == target_content
        assert len(survivor.supports) == 2

    @pytest.mark.parametrize(
        ("target_content", "restatement"),
        [
            # One token *inserted*: the adversarial case ADR-0121 §1 argues from,
            # scoring 3 of 4 query terms — exactly the conflict threshold.
            (_CONTENT, _DISAGREEING),
            # Terminal punctuation only. "daily." is not a substring of the
            # unpunctuated target, so the case still scores 3 of 4 — at the
            # threshold, exercising the predicate and not an empty conflict set.
            # A writer predicate that strips trailing stops accepts this fold and
            # refreshes an assertion's evidence and currency from a sentence the
            # user never quite said.
            ("prefers concise emails daily", "prefers concise emails daily."),
            # A dropped leading article. Every remaining term is a substring of
            # the target (score 1.0), so the target *tops* the ranking while the
            # texts remain different beliefs under §1 — the widening a
            # stop-word-stripping predicate admits.
            ("the user prefers concise emails", "user prefers concise emails"),
        ],
        ids=["one-token-insertion", "trailing-stop", "dropped-article"],
    )
    async def test_a_disagreeing_restatement_may_not_fold_onto_an_assertion(
        self, make_writer: WriterFactory, target_content: str, restatement: str
    ) -> None:
        """ADR-0121 §5's exception is **verified at the writer, never trusted**.

        Pinned on its own as well as in the matrix, for the reason
        :meth:`test_an_assertion_still_may_not_reinforce_an_external_record` is: this
        is the case a later simplification breaks. A writer that admitted the fold
        on the ruling's word — the policy said ``REINFORCE``, so the records must
        agree — passes every other case here and folds a *correction* into the belief
        it corrects, at that belief's id, which ADR-0121 §1 names as strictly worse
        than either failure mode the ADR set out to fix.

        The two contents are one token apart and the target still ranks as a
        conflict (:data:`_DISAGREEING`), so this exercises the predicate rather than
        an empty conflict set — which is the shape of the hazard: the strings
        scoring *highest* against a belief include the one that contradicts it.

        The punctuation and dropped-article cases pin the predicate from the other
        side: §1 admits exactly four transformations, and a writer that "helpfully"
        strips a terminal stop or a stop-word widens agreement past what was
        ratified — accepting a forced fold this suite otherwise never shows it.
        Each case's arithmetic keeps the target at or above the conflict
        threshold, so all three refusals are decided by the predicate alone.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("theirs", target_content, source=MemorySource.USER_ASSERTED))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(
                _proposal(
                    _preference(
                        "new",
                        restatement,
                        source=MemorySource.USER_ASSERTED,
                        evidence=(_CITED,),
                    )
                )
            )

        assert await _snapshot(store) == before

    @pytest.mark.parametrize(
        ("kind", "incoming", "content"),
        [
            # A non-asserted proposal that does not agree.
            (MemoryDecisionKind.REINFORCE, MemorySource.OBSERVED, _DISAGREEING),
            # An agreeing import.
            (MemoryDecisionKind.REINFORCE, MemorySource.EXTERNAL, _CONTENT),
            # A supersession with no covering confirmation.
            (MemoryDecisionKind.SUPERSEDE, MemorySource.USER_ASSERTED, _DISAGREEING),
        ],
        ids=["disagreeing-observation", "agreeing-external", "supersede-without-confirmation"],
    )
    async def test_the_refusals_the_widened_exception_leaves_standing(
        self,
        make_writer: WriterFactory,
        kind: MemoryDecisionKind,
        incoming: MemorySource,
        content: str,
    ) -> None:
        """Clause 1 still refuses everything ADR-0214 §3 does not name.

        §3 widens ADR-0121 §5's exception in **exactly one condition** — the incoming
        record's source, from ``USER_ASSERTED`` to ``USER_ASSERTED``/``OBSERVED``/
        ``INFERRED`` — and leaves its other two alone: the ruling must be
        ``REINFORCE``, and the two records must **agree** under ADR-0121 §1. So
        clause 1 carries two exceptions after ADR-0214 and not three, and these are
        the three shapes a widening one condition too far would take:

        * a non-asserted proposal that does **not** agree — the fold that folds a
          correction into the belief it corrects, at that belief's id;
        * an agreeing ``EXTERNAL`` proposal — refused for ADR-0121 §3's reason, which
          identity of content does not weaken: an imported record's id is the
          integrating system's idempotency key, and the next routine sync overwrites
          the fold (ADR-0214 §2);
        * a ``SUPERSEDE`` onto an assertion with no covering confirmation — which
          retires what the user told us, and only their own answer authorises that
          (ADR-0078 §5b).

        The matrix decides all three from :func:`_fold_is_refused`; they are pinned
        again here, from literal expectations, because that is the function a
        widening edits. A tidy-up that stated the exception over "any agreeing
        ``REINFORCE``" or over "any non-``EXTERNAL`` incoming source" moves the
        predicate and the matrix together and leaves nothing failing. The fourth
        refusal ADR-0214 leaves standing has its own case already —
        :meth:`test_an_assertion_still_may_not_reinforce_an_external_record`, which
        is clause 2 rather than clause 1.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("theirs", source=MemorySource.USER_ASSERTED))
        writer = make_writer(store, FakeMemoryPolicy(kind))
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(
                _proposal(_preference("new", content, source=incoming, evidence=(_CITED,)))
            )

        # Write nothing: a writer that mutated the target and then raised is caught
        # as well as one that stored the proposal as new.
        assert await _snapshot(store) == before

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

        **``EXTERNAL`` siblings are swept in too, since ADR-0092 §4** — which
        adopts ``EXTERNAL`` supersession and partially supersedes ADR-0050 §1's
        hold-out. So the ``named-target-external`` case now pins something narrower
        than it used to: not that an ``EXTERNAL`` sibling survives, but that naming
        an ``EXTERNAL`` record as the *primary* is still honoured and still audited
        as the target.

        The one held-out source stays live under either ruling: topical similarity
        may not retire a record the user gave us (ADR-0045 §5), and ADR-0038 §3's
        one-way asymmetry is untouched — ADR-0092 §4 widens what an *assertion* may
        retire and nothing about who may retire an assertion.
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

        # A user's correction, so its standing ranks at or above every member it ends
        # (ADR-0328 §6:5) and no relation is determined (ADR-0159 §2).
        result = await writer.ingest(
            _proposal(_preference("new", source=MemorySource.USER_ASSERTED))
        )

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
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
        assert isinstance(correction, Memory)
        assert set(correction.operations[0].replaces) == {"target", *_SWEPT_IN}

    async def test_a_correction_retires_an_attested_sibling(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0092 §4's adoption, as a ``MemoryWriter`` obligation (ADR-0079 §3).

        The case named in ADR-0092 §9: a user's correction supersedes a stale
        inference and the *attested* record beside it is swept in with it, rather
        than surviving as a second live belief on the same topic. Stated on its own
        as well as inside the matrix above, because it is the behavioural half of
        the adoption and the widening case would still pass if a writer swept in
        one arbitrary extra record.

        The class widened, not the shape: this is why ADR-0079 §3 owes no amendment
        (ADR-0092 §8). §3 states the obligation *intensionally* — "every other
        conflict … **whose source is supersedable**" — so widening what is
        supersedable leaves that sentence true verbatim and leaves no reader acting
        differently.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("stale", source=MemorySource.INFERRED))
        await store.add(_preference("imported", source=MemorySource.EXTERNAL))
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("stale"),
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
        )

        result = await writer.ingest(
            _proposal(_preference("new", source=MemorySource.USER_ASSERTED))
        )

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        for retired_id in ("stale", "imported"):
            assert await store.get(retired_id) is None, f"{retired_id} was not retired"
            assert retained[retired_id].validity.valid_until is not None
        # Retired, not destroyed: the import is retained in `export` with its source
        # details intact, so "your calendar reported this, and we retired it" is still
        # answerable (ADR-0045 §6, ADR-0073 §4).
        imported = retained["imported"]
        assert isinstance(imported, Memory)
        assert imported.supports[0].source_details == _ATTESTED_BY
        assert await store.get("corrected") is not None

    async def test_an_assertion_still_may_not_reinforce_an_external_record(
        self, make_writer: WriterFactory
    ) -> None:
        """The refusal ADR-0092 §5 exists to keep, stated where a merge would break it.

        This is the regression a one-line performance of ADR-0092 §4 ships. The
        widening above and this refusal read what *was* one ``_SUPERSEDABLE``
        constant serving two unrelated questions:

        1. which sibling conflicts a ``SUPERSEDE`` closes (the widening); and
        2. which targets a ``USER_ASSERTED`` proposal may ``REINFORCE`` onto.

        They were the same set only by coincidence. Adding ``EXTERNAL`` for (1)
        makes (2)'s condition ``source not in <set>`` **false** for an ``EXTERNAL``
        target, so the refusal stops firing and a correction folds at the external
        id again — precisely the loss ADR-0038 §2a reproduced and ADR-0045 §5 kept
        refused by name while lifting its ``SUPERSEDE`` sibling.

        The suite states both, so a writer that merges the constants back together
        fails **here** rather than passing everything and losing a user's correction
        at the next sync. ADR-0092's Consequences names that merge as the kind of
        thing a later reader tidies; this case is what stops the tidy-up.

        **ADR-0121 §5 widened the other set**, so the two now differ in *both*
        directions — ``EXTERNAL`` is retirable and not foldable-onto,
        ``USER_ASSERTED`` is foldable-onto (by an agreeing restatement) and not
        retirable — and a merge is no longer even coincidentally harmless in one
        direction. This case keeps its job unchanged: identity of content does
        nothing to ADR-0092 §5's argument, because the next routine sync overwrites
        the fold whether or not the user's words matched the import's.

        A ``SUPERSEDE`` of the same target is *permitted* — it mints a fresh id
        (ADR-0045 §4) — and the matrix case above covers it, which is what makes the
        distinction here about the **ruling** and not about the source pair.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("imported", source=MemorySource.EXTERNAL))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new", source=MemorySource.USER_ASSERTED)))

        # Fail-closed and whole: the import is byte-identical and nothing landed,
        # so a writer that folded and *then* raised is caught too.
        assert await _snapshot(store) == before
        assert await store.get("new") is None

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
        before = await _snapshot(store)
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_always("wall"),
            conflict_limit=_ROOMY_CEILING,
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new", source=MemorySource.USER_ASSERTED)))

        assert await _snapshot(store) == before
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

        result = await writer.ingest(
            _proposal(_preference("new", source=MemorySource.USER_ASSERTED))
        )

        assert result.record_id == "corrected"  # re-minted past a swept-in conflict
        retained = {record.id: record for record in await _memories(store)}
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
        before = await _snapshot(store)
        policy = FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE)
        writer = make_writer(store, policy, conflict_limit=2)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        assert policy.call_count == 0  # no ruling was sought
        assert await _snapshot(store) == before  # nothing written, no window closed
        for index in range(3):
            live = await store.get(f"existing-{index}")
            assert live is not None
            assert live.validity.valid_until is None

    # --- ADR-0159 §5: what a supersession may not retire ---------------------

    async def test_an_agreeing_conflict_is_never_retired_and_needs_no_model(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0159 §5's ``agrees`` half — the one every writer computes with no model.

        A conflict a writer holds a ``RESTATES`` relation for "is **never retired**,
        by any ruling, at any writer… and a writer that would retire it refuses the
        write instead". ADR-0121 §1's predicate is syntactic and certain, so a
        writer determines this half for itself on the ingests ADR-0159 §2 admits —
        no reconciler is injected here, and none is needed.

        Superseding a record that says the same thing retires a live belief on the
        strength of a *restatement*, which is what §5 exists to stop. Refused rather
        than silently narrowed, because retiring the named target is what the ruling
        means: there is nothing to leave out of the set.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE))
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_preference("new", evidence=(_CITED,))))

        # Nothing written and nothing retired: a writer that closed the window and
        # *then* raised is caught, not only one that stored the correction.
        assert await _snapshot(store) == before

    async def test_a_supersede_leaves_an_adds_sibling_live(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0159 §5's ``ADDS`` half, driven by an injected stub reconciler.

        The clause on which ADR-0159 §4(b) may exist at all. ADR-0050 §1 defines the
        retirement set on the premise that "every entry in the conflict set the
        detector surfaced is a same-kind, at-or-above-threshold contradiction of the
        proposal", which #1188 measured false: at the ratified threshold the set is
        routinely a mixture of restatements, additions and contradictions. Left
        standing, a supersession arm on the observed path would turn one lost fact
        per fold into up to ``conflict_limit`` lost facts per correction.

        So the widening skips a member the writer holds an ``ADDS`` relation for —
        it is not the belief being corrected, it is a distinct fact similarity
        surfaced beside it — while the ordinary supersedable sibling is still swept
        in, which is what keeps ADR-0079 §3 otherwise unchanged.

        **From the writer's own relations, never trusted from the ruling** (ADR-0038
        §2a, ADR-0159 §8): the ruling below names one member and says nothing about
        the other two.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("target", source=MemorySource.INFERRED))
        await store.add(_preference("distinct", source=MemorySource.INFERRED))
        await store.add(_preference("swept", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
            reconciler=_LabellingReconciler({"distinct": ConflictRelation.ADDS}),
        )

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.decision.kind is MemoryDecisionKind.SUPERSEDE
        retained = {record.id: record for record in await _memories(store)}
        assert retained["target"].validity.valid_until is not None, "the named target is retired"
        assert retained["swept"].validity.valid_until is not None, "an ordinary sibling still is"
        assert retained["distinct"].validity.valid_until is None, "an ADDS sibling is not"

    async def test_a_supersede_naming_an_adds_conflict_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """The other limb: the exclusion cannot be an omission when *this* is the target.

        A ``SUPERSEDE`` naming another member simply leaves such a conflict out of
        the set; one naming this member has nowhere to leave it, so ADR-0159 §5
        refuses the write. Nothing is retired on the way out.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            reconciler=_LabellingReconciler({"existing": ConflictRelation.ADDS}),
        )
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert await _snapshot(store) == before

    async def test_a_contradicting_conflict_is_retired_exactly_as_before(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0159 §5 narrows and does not invert: a labelled contradiction is retired.

        ``CONTRADICTS`` is deliberately outside the exclusion — a labelled
        contradiction is precisely what a correction is warranted to retire, and the
        retirement class still decides whether it may be. Without this case the
        exclusion could be implemented as "any relation blocks", which would make
        ADR-0159 §4(b)'s supersession arm unreachable at the writer.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted("corrected"),
            reconciler=_LabellingReconciler({"existing": ConflictRelation.CONTRADICTS}),
        )

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        assert retained["existing"].validity.valid_until is not None

    # --- ADR-0171 §2: a supersession sweeps in only a labelled contradiction --
    #
    # Three arms reach the widening, they behave differently, and each of these
    # cases fails on a writer that implements only the others. The discriminator is
    # the **crossing** — did this ingest produce a labelled contradiction at all —
    # and not the member, because a writer cannot tell a member left unlabelled
    # beyond ADR-0159 §3's bound from one no reconciler ever judged (ADR-0164 §6 and
    # §9 decline the consulted set that would; #1225 records it).

    async def test_a_labelled_contradiction_leaves_an_unlabelled_sibling_live(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0171 §2, first clause — the reconciled arm, and where the narrowing bites.

        Where the writer holds ``CONTRADICTS`` for at least one member of the ruled-on
        set, the supersession retires the named target and, beyond it, **only** the
        other members it holds that relation for. A member it holds *no* relation for
        is left live, whatever its source.

        This is the record #1302's audit says is being destroyed. The unlabelled
        member is not spared because anything judged it harmless — it is spared
        because nothing judged it at all, and ADR-0050 §1's premise that every member
        of a similarity-surfaced set "is a same-kind, at-or-above-threshold
        contradiction of the proposal" is what #1188 and #1302 between them measured
        false. Before this clause the lookup returned nothing, nothing was not in the
        unretirable set, and the member was swept in on that double negative.

        The sibling's source is in the retirement class, so a writer that narrowed on
        the *source* rather than on the relation passes nothing here.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("target", source=MemorySource.INFERRED))
        await store.add(_preference("unjudged", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
            reconciler=_LabellingReconciler({"target": ConflictRelation.CONTRADICTS}),
        )

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        assert retained["target"].validity.valid_until is not None, "the named target is retired"
        assert retained["unjudged"].validity.valid_until is None, (
            "a member the writer holds no relation for was swept into the retirement "
            "set of a crossing that produced a labelled contradiction (ADR-0171 §2)"
        )
        assert await store.get("unjudged") is not None

    async def test_a_crossing_with_no_relations_still_retires_the_whole_set(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0171 §2, third clause — the asserted arm, unchanged and #313/#314's.

        **This is the case a narrowing phrased as "retire only labelled
        contradictions" would have destroyed**, which is why §2 is stated over the
        crossing. A ``USER_ASSERTED`` proposal never reaches a reconciler — ADR-0159
        §2's invocation condition excludes it, and excludes any crossing holding an
        asserted member — so the writer holds no relations, no member is labelled
        ``CONTRADICTS``, and ADR-0079 §3's obligation binds exactly as it stands. A
        user correcting a belief still retires every stale sibling it is shown
        (ADR-0079 §1), across all three sources of the retirement class.

        A reconciler that *would* have labelled one member and narrowed the set to
        two is injected anyway, so the case pins that the exclusion is the invocation
        condition's and not an accident of nothing being injected. A writer that
        consulted it here would retire two records instead of four.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("target", source=MemorySource.OBSERVED))
        await store.add(_preference("stale-observed", source=MemorySource.OBSERVED))
        await store.add(_preference("stale-inferred", source=MemorySource.INFERRED))
        await store.add(_preference("stale-external", source=MemorySource.EXTERNAL))
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
            reconciler=_LabellingReconciler({"target": ConflictRelation.CONTRADICTS}),
        )

        result = await writer.ingest(
            _proposal(_preference("new", source=MemorySource.USER_ASSERTED))
        )

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        for retired_id in ("target", "stale-observed", "stale-inferred", "stale-external"):
            assert retained[retired_id].validity.valid_until is not None, (
                f"{retired_id} survived a user's own correction: ADR-0171 §2's third "
                "clause hands an unreconciled crossing to ADR-0079 §3 unchanged"
            )

    async def test_a_crossing_holding_only_restates_labels_retires_the_unlabelled(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0171 §2, third clause — the degraded arm, and ADR-0159 §6's floor unmoved.

        With no reconciler injected the writer holds at most the certain rung's
        ``RESTATES`` labels, computed with no model from ADR-0121 §1's predicate. That
        rung can **never** produce ``CONTRADICTS``, so the third clause governs and an
        unlabelled supersedable sibling is retired exactly as it is today.

        Sparing on the strength of a test that was never run would be the wrong
        direction — it would leave a stale belief live beside its correction because
        no provider was configured — and ADR-0171 §2 does not. The ``RESTATES``
        member is still spared, by ADR-0159 §5 and not by anything here, which is what
        keeps the two narrowings distinguishable in this case rather than collapsed.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("target", source=MemorySource.INFERRED))
        await store.add(_preference("restated", _DISAGREEING, source=MemorySource.INFERRED))
        await store.add(_preference("unjudged", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_scripted("corrected"),
            conflict_limit=_ROOMY_CEILING,
        )

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        assert retained["target"].validity.valid_until is not None
        assert retained["unjudged"].validity.valid_until is not None, (
            "the degraded arm holds no CONTRADICTS, so ADR-0079 §3 binds unchanged"
        )
        assert retained["restated"].validity.valid_until is None, "ADR-0159 §5 still spares it"

    async def test_the_audits_worst_crossing_retires_two_and_leaves_eleven_live(
        self, make_writer: WriterFactory
    ) -> None:
        """#1302's conv-50 shape, by its measured values (ADR-0171 §5).

        The verified worst case of #1294's supersede audit: a crossing offering **13**
        members, of which the model was asked about three and labelled one ``ADDS``
        and two ``CONTRADICTS``. Today twelve records are retired and ten of them were
        never labelled at all — among them 'performed on stage 2 Aug' and 'met artists
        in Boston 3 Oct', which no reading calls contradicted.

        Under ADR-0171 §2 the ruling names one of the two contradictions, the
        retirement set adds the other, ADR-0159 §5 spares the ``ADDS`` member as it
        already does, and the ten unlabelled members are left live: **two retired
        instead of twelve.**

        The shape is pinned rather than the anatomy — the numbers here are the audit's
        own, and the case is what stops a later reader restoring the widening on the
        argument that a similarity-surfaced set is all one belief.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("target", source=MemorySource.INFERRED))
        await store.add(_preference("other-contradiction", source=MemorySource.INFERRED))
        await store.add(_preference("distinct", source=MemorySource.INFERRED))
        unjudged = tuple(f"unjudged-{index}" for index in range(10))
        for record_id in unjudged:
            await store.add(_preference(record_id, source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            _SupersedeNamingPolicy("target"),
            id_factory=_scripted("corrected"),
            conflict_limit=_AUDIT_CEILING,
            reconciler=_LabellingReconciler(
                {
                    "target": ConflictRelation.CONTRADICTS,
                    "other-contradiction": ConflictRelation.CONTRADICTS,
                    "distinct": ConflictRelation.ADDS,
                }
            ),
        )

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        retired = {
            record_id
            for record_id, record in retained.items()
            if record_id != _CITED and record.validity.valid_until is not None
        }
        assert retired == {"target", "other-contradiction"}
        for spared_id in ("distinct", *unjudged):
            assert await store.get(spared_id) is not None

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
            _preference("existing", source=MemorySource.INFERRED).model_copy(
                update={"validity": Validity(valid_until=_SELF_CLOSE)}
            )
        )
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_proposal(_correcting("new", evidence=(_CITED,))))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        end = retained["existing"].validity.valid_until
        assert end is not None
        assert end <= _SELF_CLOSE  # never extended past the producer's own end
        assert retained["existing"].validity.valid_from is None  # the start did not move
        # Read at the planted end: off the read path, still in `export`.
        read_at[0] = _SELF_CLOSE
        assert await store.get("existing") is None
        assert all(record.id != "existing" for record in (await store.search(_CONTENT)).records)
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
            _preference("future", source=MemorySource.INFERRED).model_copy(
                update={"validity": Validity(valid_from=_NOT_YET_OPEN)}
            )
        )
        await store.add(_preference("sibling", source=MemorySource.INFERRED))
        before = await _snapshot(store)
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
            assert await _snapshot(store) == before
            assert await store.get("corrected") is None
            return

        assert outcome is not None
        retained = {record.id: record for record in await _memories(store)}
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

    # --- every support must resolve (ADR-0328 §4:7, widening ADR-0077 §5) -----

    @pytest.mark.parametrize("source", list(MemorySource), ids=str)
    async def test_a_support_pointing_at_an_episode_the_store_lacks_is_refused(
        self, make_writer: WriterFactory, source: MemorySource
    ) -> None:
        """The writer's floor, in every band: a support's episode must resolve.

        ADR-0328 §4:7 widens ADR-0077 §5 from a derived record's citations to every
        support of every memory, so the case runs over every band. A raise rather
        than a fabricated ``REJECT``, because a ruling is the policy's to make — which
        is why the policy must not have been asked.

        **Every** unresolved episode is named, **in support order**: a missing one, a
        resolvable one between them, and a second missing one, in an order no sort
        reproduces. The consumer reads the ids to tell an expired episode from a
        producer fault, so a writer reporting only the first would bury one under the
        other.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        before = await _snapshot(store)
        policy = FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
        writer = make_writer(store, policy)

        with pytest.raises(UnresolvedEvidenceError) as caught:
            await writer.ingest(
                _proposal(
                    _preference("new", source=source, evidence=("gone-later", _CITED, "gone-early"))
                )
            )

        assert tuple(caught.value.unresolved_ids) == ("gone-later", "gone-early")
        assert policy.call_count == 0  # refused before any ruling was sought
        assert await _snapshot(store) == before

    async def test_a_support_pointing_at_a_memory_rather_than_an_episode_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """A support points at a part of an *episode* (ADR-0328 §4's part table).

        An id naming a stored memory resolves to a record, but not to an episode, so a
        support pointing into it rests on nothing a support may rest on.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        with pytest.raises(UnresolvedEvidenceError) as caught:
            await writer.ingest(_proposal(_preference("new", evidence=("existing",))))

        assert tuple(caught.value.unresolved_ids) == ("existing",)

    @pytest.mark.parametrize("source", list(MemorySource), ids=str)
    async def test_supports_whose_episodes_resolve_are_unaffected(
        self, make_writer: WriterFactory, source: MemorySource
    ) -> None:
        """The other side of the floor: a support whose episode is held passes untouched."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_proposal(_preference("new", source=source)))

        assert result.record_id == "new"
        assert await store.get("new") is not None

    async def test_a_legacy_support_is_not_resolved_against_episodes(
        self, make_writer: WriterFactory
    ) -> None:
        """A legacy support points at a record stored before ADR-0328, not an episode.

        It carries that record whole (§16:4), so there is nothing to resolve, and the
        floor does not read it.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(
            _proposal(memory("new", _CONTENT, legacy_support({"id": "unstored-legacy"})))
        )

        assert result.record_id == "new"

    # --- no write consumes its own warrant (ADR-0081 §1, read through §12) ----
    # What a memory cites is the episodes its supports point at (ADR-0328 §12). So a
    # proposal installed at an id one of its supports points into would stand as its
    # own warrant. A legacy support is no citation: it carries the record it points at
    # whole (§16:4), so an install at that record's id consumes nothing.

    @pytest.mark.parametrize("source", list(MemorySource), ids=str)
    async def test_an_accept_at_an_id_its_supports_point_at_is_refused(
        self, make_writer: WriterFactory, source: MemorySource
    ) -> None:
        """Limb 1, ``ACCEPT``: the producer chose the destination, and it is cited.

        The proposal's id is the episode its own support points at. The refusal is
        ``SelfConsumingWriteError`` by exact type, never ``UnresolvedEvidenceError``
        (the episode resolves perfectly well), and nothing is written.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        before = await _snapshot(store)
        writer = make_writer(store, _RulesExactly(MemoryDecisionKind.ACCEPT))

        with pytest.raises(MemoryStoreError) as caught:
            await writer.ingest(_proposal(_preference(_CITED, source=source)))

        assert type(caught.value) is SelfConsumingWriteError
        assert await _snapshot(store) == before

    async def test_an_accept_at_its_own_legacy_records_id_installs(
        self, make_writer: WriterFactory
    ) -> None:
        """A legacy support at the proposal's own id is no citation (§12, §16:4).

        The legacy support carries its record whole, so installing at that id leaves
        nothing the memory rests on unreadable: §16:4's upgraded memory is exactly this
        shape, and no refusal ADR-0081 makes reaches it.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, _RulesExactly(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(
            _proposal(memory("new", _CONTENT, legacy_support({"id": "new"})))
        )

        assert result.record_id == "new"
        assert await store.get("new") is not None

    async def test_a_reinforce_onto_a_target_a_legacy_support_names_lands(
        self, make_writer: WriterFactory
    ) -> None:
        """A legacy support naming the target is no citation, so the fold lands (§12).

        ``FoldOntoCitedRecordError`` keys on the episodes a proposal's supports point
        into, and a target memory is never one.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(store, _RulesExactly(MemoryDecisionKind.REINFORCE))
        proposed = memory(
            "new",
            _CONTENT,
            _preference("new").supports[0],
            legacy_support({"id": "existing"}),
        )

        result = await writer.ingest(_proposal(proposed))

        assert result.record_id == "existing"
        assert {record.id for record in await _memories(store)} == {"existing"}

    @pytest.mark.parametrize(
        "kind", [MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER], ids=str
    )
    async def test_a_ruling_that_writes_nothing_on_a_self_citing_proposal_is_unaffected(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """The negative arm: ``REJECT`` and ``ASK_USER`` neither raise nor write.

        The rule gates the write, after the ruling, so a self-citing proposal the
        policy declines is reported as the decision the policy made (ADR-0081 §1/§2).
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, _RulesExactly(kind))

        result = await writer.ingest(_proposal(_preference(_CITED)))

        assert result.decision.kind is kind
        assert result.record_id is None
        assert await _memories(store) == []

    async def test_an_unresolvable_second_support_still_refuses_with_the_evidence_error(
        self, make_writer: WriterFactory
    ) -> None:
        """Precedence (ADR-0081 §6): the pre-policy floor fires first, with its own class.

        A self-citing proposal that also carries an unresolvable support is refused by
        ADR-0328 §4:7's floor before the policy is asked, naming only the episode that
        does not resolve.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        policy = FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
        writer = make_writer(store, policy)

        with pytest.raises(UnresolvedEvidenceError) as caught:
            await writer.ingest(_proposal(_preference(_CITED, evidence=(_CITED, "gone"))))

        assert tuple(caught.value.unresolved_ids) == ("gone",)
        assert policy.call_count == 0

    @pytest.mark.parametrize("kind", _FOLD_KINDS, ids=str)
    async def test_a_fold_naming_an_absent_target_the_proposal_cites_keeps_that_error(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """The standing refusal keeps precedence: an absent target is no destination.

        The ruling names ``"ghost"`` and a legacy support points at ``"ghost"``. A
        ``REINFORCE``'s destination is drawn from the conflicts, so a target outside
        them installs nothing and the not-among-the-conflicts refusal is the one that
        fires (ADR-0081 §6).
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, _FoldToAbsentTargetPolicy(kind))
        proposed = memory(
            "new", _CONTENT, _preference("new").supports[0], legacy_support({"id": "ghost"})
        )

        with pytest.raises(MemoryStoreError, match="not among the conflicts"):
            await writer.ingest(_proposal(proposed))

        assert await _memories(store) == []

    async def test_supersede_re_mints_past_a_cited_id_and_lands(
        self, make_writer: WriterFactory
    ) -> None:
        """Limb 2: a minted id the proposal cites is re-minted, not refused (ADR-0081 §4).

        The minted id is the episode the correction's own support points into; the
        writer mints again rather than installing the correction over its warrant.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted(_CITED, "corrected"),
        )

        result = await writer.ingest(_proposal(_correcting("new")))

        assert result.record_id == "corrected"
        assert isinstance(await store.get(_CITED), EpisodicMemory)
        retained = {record.id for record in await _memories(store)}
        assert retained == {"existing", "corrected"}

    async def test_supersede_with_an_always_cited_factory_leaves_every_target_live(
        self, make_writer: WriterFactory
    ) -> None:
        """Limb 2's bound: exhausted re-mints raise, every target live and unchanged."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        before = await _snapshot(store)
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_always(_CITED),
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_correcting("new")))

        assert await _snapshot(store) == before

    async def test_a_supersede_still_retires_a_cited_record_and_lands(
        self, make_writer: WriterFactory
    ) -> None:
        """Limb 3: a cited memory in the retirement set is still retired, and the write lands.

        ADR-0081 adds no refusal to ``SUPERSEDE`` and removes none: retiring a memory
        the correction cites consumes nothing, since the retired memory is kept.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        writer = make_writer(
            store,
            FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE),
            id_factory=_scripted("corrected"),
        )
        correction = _correcting("new")
        proposed = memory(
            "new", _DISAGREEING, correction.supports[0], legacy_support({"id": "existing"})
        )

        result = await writer.ingest(_proposal(proposed))

        assert result.record_id == "corrected"
        assert await store.get("existing") is None
        assert {record.id for record in await _memories(store)} == {"existing", "corrected"}

    async def test_a_supersede_onto_a_cited_assertion_is_still_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """Limb 3's negative: being cited buys no exception to clause 1 (ADR-0045 §5)."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.USER_ASSERTED))
        before = await _snapshot(store)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE))
        correction = _correcting("new")
        proposed = memory(
            "new", _DISAGREEING, correction.supports[0], legacy_support({"id": "existing"})
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(proposed))

        assert await _snapshot(store) == before

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
        await _cite(store)
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
        # Every field of the version ruled on, at the minted id with the fresh open
        # window a supersession always gives (ADR-0045 §4), its create naming the
        # memory it replaces (ADR-0328 §11:7).
        proposed = ruled_on.proposed
        create = proposed.operations[0].model_copy(update={"replaces": ("existing",)})
        assert _unstamped(written) == proposed.model_copy(
            update={"id": "corrected", "validity": Validity(), "operations": (create,)}
        ), _TORN_PROPOSAL
        # The belief retired is the one that contradicted what was actually stored.
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"existing", "corrected"}
        assert retained["existing"].validity.live_at(_AFTER_CLOSE) is False

    # --- ADR-0028 §8's second clause: the confirmation gate (ADR-0078 §5) ----

    @pytest.mark.parametrize(
        ("mangle", "label"),
        [
            (_no_confirmation, "no confirmation at all"),
            (_retires_elsewhere, "a confirmation that does not name the target"),
            (
                _target_outside_the_live_set,
                "a target absent from the conflicts this ingest resolved",
            ),
            (
                _target_outside_the_frozen_set,
                "a target absent from the conflicts the user was shown",
            ),
            (
                _a_different_question_same_id,
                "a confirmation for a different question, same record id",
            ),
            (
                _a_different_question_same_proposal,
                "a confirmation for a question shown other conflicts",
            ),
        ],
        ids=[
            "uncovered",
            "retires-elsewhere",
            "outside-the-live-set",
            "outside-the-frozen-set",
            "another-question-same-id",
            "another-question-same-conflicts",
        ],
    )
    @pytest.mark.parametrize(
        "proposed",
        [_preference, _confirmed_memory],
        ids=["inference", "confirmed-wording"],
    )
    async def test_a_supersede_onto_an_assertion_raises_unless_a_confirmation_covers_it(
        self,
        make_writer: WriterFactory,
        mangle: _Mangle,
        label: str,
        proposed: Callable[[str], Memory],
    ) -> None:
        """ADR-0028 §8's second clause, in six parts (ADR-0078 §5b).

        Clause 1 refuses any fold onto a ``USER_ASSERTED`` target because "the
        conflict signal is topical similarity, not contradiction… and is too weak to
        retire a record the user gave us" — a justification about the *signal*. The
        exception is narrow and **verified rather than trusted**, because the floor
        exists precisely so that it does not depend on anyone's good behaviour: a
        policy reaches the writer through an injected seam and any conforming
        implementation may rule differently.

        Two of these are the shapes that would otherwise go untested, and each
        defeats a weaker binding ADR-0078 rejected:

        * **same proposed record id, different content** — the input an *id*-based
          binding waves through, and a suite that varied the id instead would pass
          against exactly that weaker binding;
        * **identical proposal, different frozen conflict set** — the input a
          *fingerprint* binding waves through, and invisible to a suite that varies
          content, which is every natural way to write the case above.

        A suite asserting only the refusal certifies the gate as shut; one omitting
        either mismatch shape certifies a bearer token rather than a bound authority.

        **Run on a proposal standing at "you confirmed this wording" too** (ADR-0328
        §13:3), the shape a confirmed remember proposes: a confirmation *support* is no
        authority to retire anything, so only the authority conditions above decide,
        and a writer treating the confirmed standing itself as authorisation fails here.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("asserted", source=MemorySource.USER_ASSERTED))
        writer = make_writer(store, _SupersedeNamingPolicy("asserted"))

        with pytest.raises(MemoryStoreError, match="refusing to fold onto"):
            await writer.ingest(mangle(proposed("new")))

        assert label
        retained = await _memories(store)
        assert [record.id for record in retained] == ["asserted"], "nothing was written"
        assert retained[0].validity.live_at(_LONG_AGO), "and the assertion is still live"

    async def test_a_covered_confirmation_supersedes_the_assertion_it_names(
        self, make_writer: WriterFactory
    ) -> None:
        """It **applies** only when every check holds — the other half of the gate.

        A suite asserting only the refusals certifies nothing about the pass, and the
        pass is the whole point: this is the confirmation gate ADR-0045 §7 named, and
        two ADRs deferred assertion-versus-assertion resolution to it.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("asserted", source=MemorySource.USER_ASSERTED))
        writer = make_writer(
            store, _SupersedeNamingPolicy("asserted"), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(_confirmed(_confirmed_memory("new"), retires=("asserted",)))

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"asserted", "corrected"}
        assert not retained["asserted"].validity.live_at(_AFTER_CLOSE), "retired, not destroyed"
        assert retained["corrected"].validity.live_at(_AFTER_CLOSE)

    async def test_a_confirmed_reinforce_onto_an_assertion_stays_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """Check 1: the ruling must be ``SUPERSEDE`` (ADR-0078 §5b).

        A ``REINFORCE`` folds at the *target's* id, so it would rewrite the user's own
        words — which no answer authorises, whatever the confirmation says.

        **The proposal has to disagree with the target for this to be check 1's
        case**, since ADR-0214 §3. Clause 1 carries a second exception, and an
        agreeing ``OBSERVED`` ``REINFORCE`` onto an assertion is now admitted *by
        that one* — needing no confirmation at all. A case whose proposal restated
        the target would therefore measure the agreeing-fold exception rather than
        this gate, and would go on passing if check 1 were deleted. ``_correcting``
        is a correction, which no exception reaches.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("asserted", source=MemorySource.USER_ASSERTED))
        policy = FakeMemoryPolicy(MemoryDecisionKind.REINFORCE)
        writer = make_writer(store, policy)

        with pytest.raises(MemoryStoreError, match="refusing to fold onto"):
            await writer.ingest(_confirmed(_correcting("new"), retires=("asserted",)))

        assert [record.id for record in await _memories(store)] == ["asserted"]

    async def test_a_confirmed_supersede_retires_the_named_assertion_and_the_import(
        self, make_writer: WriterFactory
    ) -> None:
        """The ordering case, on the tree ADR-0092 §4 leaves behind.

        Both records are named in ``retires``, the assertion is the **named
        target**, and both end up retired — but by two different routes, which is
        the whole content of the case:

        * the **assertion** is retired because the user's answer authorises it, and
          only because of that: it is verified through the five checks of ADR-0078
          §5b, and topical similarity could never have reached it (ADR-0045 §5);
        * the **import** is retired by the ordinary widening, since ADR-0092 §4 put
          ``EXTERNAL`` in the retirement class. It needs no authority from the
          confirmation — which is exactly why ``retires`` naming it changes nothing.

        Before ADR-0092 §4 this case pinned the import staying *live*, on the
        ground that retiring it would adopt a deferred policy choice by accident.
        The choice is now made, so what is left to protect is the **attribution**:
        the ruling's audited target must still be the assertion the confirmation was
        given for, not the incidental record beside it.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("asserted", source=MemorySource.USER_ASSERTED))
        await store.add(_preference("external", source=MemorySource.EXTERNAL))
        writer = make_writer(
            store, _SupersedeNamingPolicy("asserted"), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(
            _confirmed(_confirmed_memory("new"), retires=("asserted", "external"), frozen=_FROZEN)
        )

        assert result.decision.target_id == "asserted", "the confirmation's own target is audited"
        retained = {record.id: record for record in await _memories(store)}
        assert not retained["asserted"].validity.live_at(_AFTER_CLOSE), "the assertion is retired"
        assert not retained["external"].validity.live_at(_AFTER_CLOSE), (
            "and so is the import, by the widening rather than by the confirmation"
        )

    async def test_a_confirmation_naming_two_assertions_retires_both_in_one_batch(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0078 §5b's narrowing of ADR-0050 §1's hold-out, at width.

        Every confirmed *asserted* conflict is retired, not only the named one: the
        named target is the primary the ruling audits, and the rest ride the same
        widening the derived siblings already do — in the one atomic batch.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("asserted-a", source=MemorySource.USER_ASSERTED))
        await store.add(_preference("asserted-b", source=MemorySource.USER_ASSERTED))
        writer = make_writer(
            store, _SupersedeNamingPolicy("asserted-a"), id_factory=_scripted("corrected")
        )

        await writer.ingest(
            _confirmed(
                _confirmed_memory("new"),
                retires=("asserted-a", "asserted-b"),
                frozen=("asserted-a", "asserted-b"),
            )
        )

        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"asserted-a", "asserted-b", "corrected"}
        assert not retained["asserted-a"].validity.live_at(_AFTER_CLOSE)
        assert not retained["asserted-b"].validity.live_at(_AFTER_CLOSE), (
            "both, not only the named one"
        )

    async def test_a_confirmed_supersede_still_retires_a_live_inference(
        self, make_writer: WriterFactory
    ) -> None:
        """§5a step 3's fall-through, seen from the applier (ADR-0078 §5).

        The shown assertion has been retired before the answer arrives, leaving a live
        derived conflict. The correction still supersedes that inference rather than
        landing beside it: the confirmed path exists to override the arms that would
        *re-defer an answered question*, not the arms ADR-0038 entitles an assertion to
        overturn without asking.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("inferred", source=MemorySource.INFERRED))
        writer = make_writer(
            store, _SupersedeNamingPolicy("inferred"), id_factory=_scripted("corrected")
        )

        result = await writer.ingest(
            _confirmed(_confirmed_memory("new"), retires=("asserted-gone",))
        )

        assert result.record_id == "corrected"
        retained = {record.id: record for record in await _memories(store)}
        assert not retained["inferred"].validity.live_at(_AFTER_CLOSE)

    # --- check 0: no write of secret-tier data, however the ruling arrives ---

    @pytest.mark.parametrize(
        "kind",
        [
            MemoryDecisionKind.ACCEPT,
            MemoryDecisionKind.STORE_TEMPORARY,
            MemoryDecisionKind.REINFORCE,
            MemoryDecisionKind.SUPERSEDE,
        ],
        ids=["accept", "store-temporary", "reinforce", "supersede"],
    )
    async def test_no_write_producing_ruling_persists_secret_tier_data(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """Check 0 (ADR-0078 §5b), parametrised over the set rather than sampled from it.

        Each omission is a live hole. ``ACCEPT`` and ``STORE_TEMPORARY`` never reach
        the fold helper, so a check placed there passes ``SUPERSEDE`` and writes the
        secret on them; ``REINFORCE`` reaches the merge-and-add path against a
        non-asserted target, so a gate written for the three that came up in discussion
        persists the secret through the fourth.

        The proposal is built past its own validator with ``model_construct``, which is
        the point: a validator is **not a boundary**. ``model_construct`` and
        ``model_copy(update=...)`` both skip validation, and this repository already
        treats a model tampered past ``frozen=True`` as inside its threat model
        (ADR-0018 §3, ADR-0021 §4). This is the half of the belt and braces that
        survives a bypass, and the failure it guards is a credential in the memory
        database.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("inferred", source=MemorySource.INFERRED))
        writer = make_writer(store, _RulesExactly(kind), id_factory=_scripted("corrected"))

        with pytest.raises(MemoryStoreError, match="secret-tier"):
            await writer.ingest(_bypassed_secret(_preference("new")))

        assert [record.id for record in await _memories(store)] == ["inferred"]

    @pytest.mark.parametrize(
        "kind",
        [MemoryDecisionKind.ASK_USER, MemoryDecisionKind.REJECT],
        ids=["ask-user", "reject"],
    )
    async def test_a_ruling_that_writes_nothing_on_secret_tier_data_raises_nothing(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """The negative half of check 0, and the other way to implement it wrongly.

        ADR-0004 §3 forbids a secret **in the database**, not a secret being *judged*.
        An unconditional refusal before the policy runs would turn the ordinary
        secret-tier path into an error: today a secret ``learn`` reaches the policy, is
        ruled ``ASK_USER``, writes nothing and raises nothing (ADR-0078 §1), and that
        behaviour is what ADR-0078 preserves. Refusing here would break the one path it
        promised not to touch.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        writer = make_writer(store, _RulesExactly(kind))

        result = await writer.ingest(_bypassed_secret(_preference("new")))

        assert result.decision.kind is kind
        assert result.record_id is None
        assert await _memories(store) == []

    # --- the operation member: apply (ADR-0328 §11:3, §5) --------------------
    # Every case reads the memory back from the store first: a change is applied to
    # the memory the caller read, revision and all (§5:4). Each writer computes the
    # record with its own transition (§11:3); these cases state that record and every
    # refusal outright, so the two writers are held to one answer here, not to a
    # function either shares.

    async def _stored(self, store: MemoryStore, record: Memory) -> Memory:
        """Store ``record`` and return it as the store hands it back, revision and all."""
        await store.add(record)
        read = await store.get(record.id)
        assert isinstance(read, Memory)
        return read

    async def test_apply_of_an_add_support_writes_exactly_that_support_and_its_operation(
        self, make_writer: WriterFactory
    ) -> None:
        """An add support adds its support and its operation, and nothing else (§5:3)."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        read = await self._stored(store, _preference("existing"))
        support = _preference("other", evidence=(_OTHER_CITED,)).supports[0]
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=support.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        writer = make_writer(store, FakeMemoryPolicy())

        await writer.apply(MemoryChange(memory=read, operation=operation, support=support))

        written = await store.get("existing")
        assert isinstance(written, Memory)
        expected = Memory.model_validate(
            read.model_dump()
            | {"supports": (*read.supports, support), "operations": (*read.operations, operation)}
        )
        assert _unstamped(written) == _unstamped(expected)
        assert written.content == read.content  # no write changes the wording (§3:2)
        assert written.revision > read.revision

    async def test_apply_of_a_support_the_memory_carries_writes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """§4:8: an add support whose part the memory carries changes nothing, no error."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation, support=read.supports[0])
        )

        assert await store.get("existing") == read

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (MemoryOperationKind.END, MemoryStatus.ENDED),
            (MemoryOperationKind.MARK_WRONG, MemoryStatus.WRONG),
        ],
        ids=["end", "mark-wrong"],
    )
    async def test_apply_of_a_retiring_operation_closes_the_window_and_sets_the_status(
        self, make_writer: WriterFactory, kind: MemoryOperationKind, status: MemoryStatus
    ) -> None:
        """§5:7, §5:10: a retiring operation closes the window and sets the status.

        The memory is kept — off the read path, still in ``export`` (§5:5).
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        operation = MemoryOperation(
            kind=kind, cites=read.supports[0].points_at, at=_WHEN, by=MemoryWriterName.REMEMBER
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation)
        )

        assert await store.get("existing") is None
        (kept,) = await _memories(store)
        assert isinstance(kept, Memory)
        assert kept.status is status
        assert kept.validity.valid_until == _WHEN
        assert kept.operations[-1] == operation

    async def test_apply_writes_a_named_successor_in_the_same_write(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:6: an end naming a successor writes it with the end, atomically."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        successor_base = _preference("successor", _DISAGREEING)
        create = successor_base.operations[0].model_copy(update={"replaces": ("existing",)})
        successor = successor_base.model_copy(update={"operations": (create,)})
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
            successor="successor",
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation, successor=successor)
        )

        assert _unstamped_or_none(await store.get("successor")) == successor
        retained = {record.id: record for record in await _memories(store)}
        assert set(retained) == {"existing", "successor"}

    async def test_apply_of_a_successor_at_a_stored_id_is_refused_whole(
        self, make_writer: WriterFactory
    ) -> None:
        """A successor's id naming a stored record is refused, and the end with it."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        await store.add(_episodic("successor", "already stands here"))
        successor_base = _preference("successor", _DISAGREEING)
        create = successor_base.operations[0].model_copy(update={"replaces": ("existing",)})
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
            successor="successor",
        )

        with pytest.raises(MemoryStoreConflictError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(
                    memory=read,
                    operation=operation,
                    successor=successor_base.model_copy(update={"operations": (create,)}),
                )
            )

        assert await store.get("existing") == read

    async def test_apply_of_a_stop_counting_stops_the_support_it_names(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:8: a stop counting stops the support it names, citing another."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        read = await self._stored(store, _preference("existing", evidence=(_CITED, _OTHER_CITED)))
        stopped, explaining = read.supports
        operation = MemoryOperation(
            kind=MemoryOperationKind.STOP_COUNTING,
            cites=explaining.points_at,
            stops=stopped.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation)
        )

        written = await store.get("existing")
        assert isinstance(written, Memory)
        assert stopped.points_at in written.stopped
        assert written.supports == read.supports  # nothing is removed (§5:5)

    async def test_apply_raises_and_resolves_an_open_question(
        self, make_writer: WriterFactory
    ) -> None:
        """§9:2: a raise question records the question; a resolve question its answer."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        part = read.supports[0].points_at
        question = OpenQuestion(
            id="q-1",
            kind=OpenQuestionKind.RECHECK,
            asks="does this still hold?",
            rests_on=(part,),
            raised_at=_WHEN,
            raised_by=MemoryWriterName.REMEMBER,
        )
        writer = make_writer(store, FakeMemoryPolicy())
        raise_it = MemoryOperation(
            kind=MemoryOperationKind.RAISE_QUESTION,
            cites=part,
            question="q-1",
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        await writer.apply(MemoryChange(memory=read, operation=raise_it, question=question))

        raised = await store.get("existing")
        assert isinstance(raised, Memory)
        assert [one.id for one in raised.open_questions] == ["q-1"]
        resolve_it = raise_it.model_copy(
            update={"kind": MemoryOperationKind.RESOLVE_QUESTION, "note": "it does"}
        )
        await writer.apply(MemoryChange(memory=raised, operation=resolve_it))
        resolved = await store.get("existing")
        assert isinstance(resolved, Memory)
        assert resolved.open_questions[0].resolved_at == _WHEN
        assert resolved.open_questions[0].resolution == "it does"

    async def test_apply_refuses_a_create(self, make_writer: WriterFactory) -> None:
        """A create starts a memory and is ``ingest``'s, never applied (§11:4)."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=read.operations[0])
            )

        assert await store.get("existing") == read

    async def test_apply_refuses_an_operation_citing_a_support_the_memory_lacks(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:3: an operation cites a support the memory carries once it is applied."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=_preference("elsewhere").supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation)
            )

        assert await store.get("existing") == read

    async def test_apply_refuses_a_support_that_is_not_the_one_its_operation_cites(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:3: the support an operation adds is the one it cites; another is refused."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        read = await self._stored(store, _preference("existing"))
        cited, other = _preference("other", evidence=(_OTHER_CITED, _CITED)).supports
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=cited.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation, support=other)
            )

        assert await _snapshot(store) == before

    async def test_apply_of_an_end_closes_at_its_supports_about_when(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:10: an end closes validity at the about-when of the support it cites."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        read = await self._stored(store, _preference("existing"))
        ending = (
            _preference("other", evidence=(_OTHER_CITED,))
            .supports[0]
            .model_copy(
                update={
                    "direction": SupportDirection.AGAINST,
                    "backs_as_worded": False,
                    "about_when": _WHEN - timedelta(days=3),
                }
            )
        )
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=ending.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation, support=ending)
        )

        (kept,) = await _memories(store)
        assert isinstance(kept, Memory)
        assert kept.status is MemoryStatus.ENDED
        assert kept.validity.valid_until == _WHEN - timedelta(days=3)

    async def test_apply_refuses_an_end_whose_about_when_lies_after_its_instant(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:10: a claim holding until a later time is worded so, never ended early."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        read = await self._stored(store, _preference("existing"))
        ending = (
            _preference("other", evidence=(_OTHER_CITED,))
            .supports[0]
            .model_copy(
                update={
                    "direction": SupportDirection.AGAINST,
                    "backs_as_worded": False,
                    "about_when": _WHEN + timedelta(days=3),
                }
            )
        )
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=ending.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation, support=ending)
            )

        assert await _snapshot(store) == before

    async def test_apply_of_a_close_clamps_and_never_extends_the_window(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:11, ADR-0080 §1: a window already ending earlier keeps its earlier end."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        bounded = _preference("existing").model_copy(
            update={"validity": Validity(valid_until=_WHEN)}
        )
        read = await self._stored(store, bounded)
        operation = MemoryOperation(
            kind=MemoryOperationKind.MARK_WRONG,
            cites=read.supports[0].points_at,
            at=_WHEN + timedelta(days=30),
            by=MemoryWriterName.REMEMBER,
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation)
        )

        (kept,) = await _memories(store)
        assert isinstance(kept, Memory)
        assert kept.status is MemoryStatus.WRONG
        assert kept.validity.valid_until == _WHEN

    async def test_apply_refuses_a_close_with_no_representable_end(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:11, ADR-0080 §3: a close at or before the window's start is refused whole."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        later = _preference("existing").model_copy(
            update={"validity": Validity(valid_from=_WHEN + timedelta(days=1))}
        )
        read = await self._stored(store, later)
        operation = MemoryOperation(
            kind=MemoryOperationKind.MARK_WRONG,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation)
            )

        assert await _snapshot(store) == before

    async def test_apply_refuses_a_lower_standing_stopping_a_higher_support(
        self, make_writer: WriterFactory
    ) -> None:
        """§6:5: a stop counting citing a support ranking below the one it stops."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        said = _preference("s", source=MemorySource.USER_ASSERTED).supports[0]
        inferred = _preference("i", evidence=(_OTHER_CITED,)).supports[0]
        read = await self._stored(store, memory("existing", _CONTENT, said, inferred))
        operation = MemoryOperation(
            kind=MemoryOperationKind.STOP_COUNTING,
            cites=inferred.points_at,
            stops=said.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation)
            )

        assert await _snapshot(store) == before

    async def test_apply_refuses_a_lower_standing_overriding_a_higher_one(
        self, make_writer: WriterFactory
    ) -> None:
        """§6:5: an end citing a support ranking below the memory's standing is refused.

        The user said it; an inference cannot end it. The open question it needs is
        raised instead — never a silent override.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("theirs", source=MemorySource.USER_ASSERTED))
        inference = _preference("ours").supports[0]
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=inference.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(
                    memory=read,
                    operation=operation,
                    support=inference.model_copy(
                        update={"direction": SupportDirection.AGAINST, "backs_as_worded": False}
                    ),
                )
            )

        assert await store.get("theirs") == read

    async def test_apply_refuses_a_support_whose_episode_the_store_lacks(
        self, make_writer: WriterFactory
    ) -> None:
        """§4:7 on the operation member: the support an operation adds must resolve."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        support = _preference("other", evidence=("gone",)).supports[0]
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=support.points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        with pytest.raises(UnresolvedEvidenceError) as caught:
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation, support=support)
            )

        assert tuple(caught.value.unresolved_ids) == ("gone",)
        assert await store.get("existing") == read

    async def test_apply_refuses_a_memory_another_writer_moved(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:4: written only where the stored revision is the one read.

        A memory moved between the caller's read and the write is refused as stale,
        rather than overwritten with a record computed over the version it replaced.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        await store.add(read)  # another writer moves it on
        moved = await store.get("existing")
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )

        with pytest.raises(MemoryStoreStaleError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation)
            )

        assert await store.get("existing") == moved

    async def test_apply_refuses_a_raise_question_citing_a_support_it_does_not_rest_on(
        self, make_writer: WriterFactory
    ) -> None:
        """§5's table: a raise question cites a support the question rests on."""
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        read = await self._stored(store, _preference("existing", evidence=(_CITED, _OTHER_CITED)))
        first, second = read.supports
        question = OpenQuestion(
            id="q-1",
            kind=OpenQuestionKind.RECHECK,
            asks="does this still hold?",
            rests_on=(second.points_at,),
            raised_at=_WHEN,
            raised_by=MemoryWriterName.REMEMBER,
        )
        operation = MemoryOperation(
            kind=MemoryOperationKind.RAISE_QUESTION,
            cites=first.points_at,
            question="q-1",
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation, question=question)
            )

        assert await _snapshot(store) == before

    async def test_apply_of_a_carried_support_whose_episode_went_writes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """§4:8 before §4:7: a duplicate addition changes nothing, its episode gone or not.

        §4:7's episode check binds a support actually added; one whose part the memory
        already carries is no addition, so it raises nothing and writes nothing.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        assert await store.delete(_CITED)  # forgotten, as an expiry would leave it
        operation = MemoryOperation(
            kind=MemoryOperationKind.ADD_SUPPORT,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        before = await _snapshot(store)

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation, support=read.supports[0])
        )

        assert await _snapshot(store) == before

    async def test_apply_with_a_successor_retires_the_predecessor_and_links_both(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:6, §5:7: the predecessor is ended, its window closed, and each names the other."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        successor_base = _preference("successor", _DISAGREEING)
        create = successor_base.operations[0].model_copy(update={"replaces": ("existing",)})
        successor = successor_base.model_copy(update={"operations": (create,)})
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
            successor="successor",
        )

        await make_writer(store, FakeMemoryPolicy()).apply(
            MemoryChange(memory=read, operation=operation, successor=successor)
        )

        kept = {record.id: record for record in await _memories(store)}
        predecessor = kept["existing"]
        assert isinstance(predecessor, Memory)
        assert predecessor.status is MemoryStatus.ENDED
        assert predecessor.validity.valid_until == _WHEN
        assert predecessor.operations[-1].successor == "successor"
        written = kept["successor"]
        assert isinstance(written, Memory)
        assert written.status is MemoryStatus.CURRENT
        assert "existing" in written.operations[0].replaces

    async def test_apply_with_a_successor_resting_on_a_missing_episode_writes_neither(
        self, make_writer: WriterFactory
    ) -> None:
        """§4:7 on the successor: its supports must resolve, or nothing is written (§5:6).

        The predecessor is valid and the end alone would land; the successor's support
        points at an episode the store does not hold, so the whole write is refused,
        naming that episode, and the predecessor stays live.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        before = await _snapshot(store)
        successor_base = _preference("successor", _DISAGREEING, evidence=("missing-episode",))
        create = successor_base.operations[0].model_copy(update={"replaces": ("existing",)})
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
            successor="successor",
        )

        with pytest.raises(UnresolvedEvidenceError) as caught:
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(
                    memory=read,
                    operation=operation,
                    successor=successor_base.model_copy(update={"operations": (create,)}),
                )
            )

        assert tuple(caught.value.unresolved_ids) == ("missing-episode",)
        assert await _snapshot(store) == before

    async def test_apply_with_a_successor_over_a_moved_predecessor_writes_neither(
        self, make_writer: WriterFactory
    ) -> None:
        """§5:4 with §5:6: a stale predecessor refuses the whole write, successor included."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        read = await self._stored(store, _preference("existing"))
        await store.add(read)  # another writer moves it on
        before = await _snapshot(store)
        successor_base = _preference("successor", _DISAGREEING)
        create = successor_base.operations[0].model_copy(update={"replaces": ("existing",)})
        operation = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=read.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
            successor="successor",
        )

        with pytest.raises(MemoryStoreStaleError):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(
                    memory=read,
                    operation=operation,
                    successor=successor_base.model_copy(update={"operations": (create,)}),
                )
            )

        assert await _snapshot(store) == before

    async def test_a_reinforce_never_carries_a_confirmation_onto_other_wording(
        self, make_writer: WriterFactory
    ) -> None:
        """§4:6: a confirmation backs only a wording agreeing with what the user approved.

        A policy ruling ``REINFORCE`` onto a differently worded inference would
        otherwise lift that wording to "you confirmed this wording". Refused, with
        nothing written.
        """
        store = FakeMemoryStore(now=_long_ago)
        await _cite(store)
        await store.add(_preference("existing", _DISAGREEING, source=MemorySource.INFERRED))
        before = await _snapshot(store)
        writer = make_writer(store, _RulesExactly(MemoryDecisionKind.REINFORCE))

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(_confirmed_memory("new")))

        assert await _snapshot(store) == before

    async def test_a_supersede_with_a_proposal_that_cannot_stand_live_is_a_store_error(
        self, make_writer: WriterFactory
    ) -> None:
        """A proposal already ended cannot take a fresh open window: refused, not raw.

        The refusal is a ``MemoryStoreError`` — what every caller of ``ingest`` handles
        — never a bare validation failure, and nothing is written.
        """
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_preference("existing", source=MemorySource.INFERRED))
        before = await _snapshot(store)
        correction = _correcting("new")
        end = MemoryOperation(
            kind=MemoryOperationKind.END,
            cites=correction.supports[0].points_at,
            at=_WHEN,
            by=MemoryWriterName.REMEMBER,
        )
        ended = Memory.model_validate(
            correction.model_dump()
            | {
                "operations": (*correction.operations, end),
                "status": MemoryStatus.ENDED,
                "validity": Validity(valid_until=_WHEN),
            }
        )
        writer = make_writer(
            store, FakeMemoryPolicy(MemoryDecisionKind.SUPERSEDE), id_factory=_scripted("c")
        )

        with pytest.raises(MemoryStoreError):
            await writer.ingest(_proposal(ended))

        assert await _snapshot(store) == before

    # --- the observer's additions (ADR-0329 §9:7, §12:4, §12:5, §14:4) --------------
    # The track-record member, the proposal that may retire, and the observer's
    # inference. Each case states the record a write leaves, or that a refused write
    # leaves the store exactly as it was.

    async def _observer_store(self) -> FakeMemoryStore:
        """A store holding the three episodes these cases' supports point into."""
        store = FakeMemoryStore(now=_after_close)
        await _cite(store)
        await store.add(_episodic(_OTHER_CITED, "a second exchange"))
        await store.add(_episodic(_THIRD_CITED, "a third exchange"))
        return store

    # · the track record (§14:4, ADR-0328 §8)

    async def test_record_use_adds_one_entry_and_nothing_else(
        self, make_writer: WriterFactory
    ) -> None:
        """§14:4: the entry is added; it is no support and no operation (ADR-0328 §8:4)."""
        store = await self._observer_store()
        read = await self._stored(store, _preference("existing"))
        entry = _entry(_OTHER_CITED)

        await make_writer(store, FakeMemoryPolicy()).record_use(read, entry)

        written = await store.get("existing")
        assert isinstance(written, Memory)
        assert written.track_record == (entry,)
        assert _unstamped(written.model_copy(update={"track_record": ()})) == _unstamped(read)
        assert written.standing is read.standing
        assert written.revision > read.revision

    async def test_record_use_for_an_episode_already_recorded_writes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0328 §8:3: one entry per episode; recording it again changes nothing."""
        store = await self._observer_store()
        await store.add(_preference("existing").model_copy(update={"track_record": (_entry(),)}))
        read = await store.get("existing")
        assert isinstance(read, Memory)

        await make_writer(store, FakeMemoryPolicy()).record_use(
            read, _entry(held_up=False, note="a second reading of the same use")
        )

        assert await store.get("existing") == read

    async def test_record_use_on_a_memory_another_writer_moved_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """§14:4: written conditionally on the revision read (ADR-0219 §2)."""
        store = await self._observer_store()
        read = await self._stored(store, _preference("existing"))
        await store.add(read.model_copy(update={"topics": ("moved",)}))
        moved = await store.get("existing")

        with pytest.raises(MemoryStoreStaleError):
            await make_writer(store, FakeMemoryPolicy()).record_use(read, _entry())

        assert await store.get("existing") == moved

    async def test_record_use_on_a_memory_no_store_returned_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """An entry is recorded on a memory as read, revision and all."""
        store = await self._observer_store()
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError, match="revision"):
            await make_writer(store, FakeMemoryPolicy()).record_use(
                _preference("never-stored"), _entry()
            )

        assert await _snapshot(store) == before

    # · the proposal that may retire (§12:4, §12:5)

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (MemoryOperationKind.END, MemoryStatus.ENDED),
            (MemoryOperationKind.MARK_WRONG, MemoryStatus.WRONG),
            (MemoryOperationKind.REPLACE, MemoryStatus.ENDED),
        ],
        ids=["end", "mark-wrong", "replace"],
    )
    async def test_an_accepted_retiring_proposal_installs_and_retires_in_one_write(
        self, make_writer: WriterFactory, kind: MemoryOperationKind, status: MemoryStatus
    ) -> None:
        """§12:4: on an ``ACCEPT`` both memories are written, each naming the other.

        The retired memory carries the cited support as ``against``, not backing it as
        worded, and its operation cites that part and names the new memory as its
        successor; the new memory's create names the retired one among those it
        replaces (ADR-0328 §5:6).
        """
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))
        cited = new.supports[0]
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

        result = await writer.ingest(_retiring(new, old, kind))

        assert result.decision.kind is MemoryDecisionKind.ACCEPT
        assert result.record_id == "new"
        installed = await store.get("new")
        assert isinstance(installed, Memory)
        assert installed.operations[0].replaces == ("old",)
        assert installed.supports == new.supports
        retired = {record.id: record for record in await _memories(store)}["old"]
        assert isinstance(retired, Memory)
        assert retired.status is status
        operation = retired.operations[-1]
        assert (operation.kind, operation.cites, operation.successor) == (
            kind,
            cited.points_at,
            "new",
        )
        against = retired.support_at(cited.points_at)
        assert against is not None
        assert (against.direction, against.backs_as_worded, against.origin) == (
            SupportDirection.AGAINST,
            False,
            cited.origin,
        )
        assert retired.supports[: len(old.supports)] == old.supports  # nothing removed

    async def test_the_policy_rules_over_every_conflict_but_the_memory_retired(
        self, make_writer: WriterFactory
    ) -> None:
        """§12:4: the retired memory is withheld from the conflicts and from their ids."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        await store.add(_preference("sibling", evidence=(_THIRD_CITED,)))
        policy = FakeMemoryPolicy(MemoryDecisionKind.ACCEPT)
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))

        result = await make_writer(store, policy).ingest(
            _retiring(new, old, MemoryOperationKind.END)
        )

        (call,) = policy.calls
        assert [conflict.id for conflict in call.conflicts] == ["sibling"]
        assert call.proposal.conflicts == ("sibling",)
        assert result.conflicts == ("sibling",)

    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (MemoryOperationKind.END, MemoryStatus.ENDED),
            (MemoryOperationKind.MARK_WRONG, MemoryStatus.WRONG),
        ],
        ids=["end", "mark-wrong"],
    )
    async def test_a_reinforce_of_an_end_or_a_mark_wrong_retires_naming_no_successor(
        self, make_writer: WriterFactory, kind: MemoryOperationKind, status: MemoryStatus
    ) -> None:
        """§12:4: the supports go to the target, and the operation names no successor."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        await store.add(_preference("target", _DISAGREEING, evidence=(_THIRD_CITED,)))
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))
        cited = new.supports[0]
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        result = await writer.ingest(_retiring(new, old, kind))

        assert (result.decision.kind, result.record_id) == (MemoryDecisionKind.REINFORCE, "target")
        assert await store.get("new") is None
        target = await store.get("target")
        assert isinstance(target, Memory)
        assert target.support_at(cited.points_at) is not None
        retired = {record.id: record for record in await _memories(store)}["old"]
        assert isinstance(retired, Memory)
        assert retired.status is status
        assert retired.operations[-1].kind is kind
        assert retired.operations[-1].successor is None

    async def test_a_reinforce_of_a_replace_writes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """§12:4: a replace must name its replacement, which a reinforce installs not."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        await store.add(_preference("target", _DISAGREEING, evidence=(_THIRD_CITED,)))
        before = await _snapshot(store)
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        result = await writer.ingest(_retiring(new, old, MemoryOperationKind.REPLACE))

        assert (result.decision.kind, result.record_id) == (MemoryDecisionKind.REINFORCE, None)
        assert await _snapshot(store) == before

    @pytest.mark.parametrize(
        "kind",
        [MemoryDecisionKind.SUPERSEDE, MemoryDecisionKind.REJECT, MemoryDecisionKind.ASK_USER],
        ids=str,
    )
    async def test_any_other_ruling_on_a_retiring_proposal_writes_nothing(
        self, make_writer: WriterFactory, kind: MemoryDecisionKind
    ) -> None:
        """§12:4: "on any other ruling, it writes nothing"."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        await store.add(_preference("target", _CONTENT, evidence=(_THIRD_CITED,)))
        before = await _snapshot(store)
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))
        writer = make_writer(store, FakeMemoryPolicy(kind), id_factory=_scripted("minted"))

        result = await writer.ingest(_retiring(new, old, MemoryOperationKind.END))

        assert (result.decision.kind, result.record_id) == (kind, None)
        assert await _snapshot(store) == before

    @pytest.mark.parametrize(
        "cites",
        ["absent", "not-backing", "against"],
    )
    async def test_a_retirement_citing_no_backing_support_of_the_new_memory_is_refused(
        self, make_writer: WriterFactory, cites: str
    ) -> None:
        """§12:5: the cited support is a counted ``for`` support backing the new memory."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        before = await _snapshot(store)
        backing = remembered_support(_OTHER_CITED, effect="effect-new", when=_WHEN, added_at=_WHEN)
        aside = said_support(_THIRD_CITED, when=_WHEN, added_at=_WHEN)
        if cites == "not-backing":
            aside = aside.model_copy(update={"backs_as_worded": False})
        if cites == "against":
            aside = said_support(
                _THIRD_CITED, when=_WHEN, added_at=_WHEN, direction=SupportDirection.AGAINST
            )
        new = memory("new", _DISAGREEING, backing, *(() if cites == "absent" else (aside,)))
        proposal = _retiring(new, old, MemoryOperationKind.END, cites=aside.points_at)

        with pytest.raises(MemoryStoreError, match="§12:5"):
            await make_writer(store, FakeMemoryPolicy()).ingest(proposal)

        assert await _snapshot(store) == before

    async def test_a_retirement_citing_a_support_below_the_retired_standing_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0328 §6:5 refuses the operation, and the whole proposal with it (§12:5)."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old", source=MemorySource.USER_ASSERTED))
        before = await _snapshot(store)
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))

        with pytest.raises(MemoryStoreError, match="§6:5"):
            await make_writer(store, FakeMemoryPolicy()).ingest(
                _retiring(new, old, MemoryOperationKind.END)
            )

        assert await _snapshot(store) == before

    async def test_what_the_user_said_retires_what_they_said_before(
        self, make_writer: WriterFactory
    ) -> None:
        """§20: assertion against assertion is no longer deferred here, §6:5 guarding it.

        The new memory's said support ranks with the old memory's standing, so the
        retirement stands; the policy never sees the old assertion as a conflict.
        """
        store = await self._observer_store()
        old = await self._stored(store, _preference("old", source=MemorySource.USER_ASSERTED))
        new = _preference(
            "new", _DISAGREEING, source=MemorySource.USER_ASSERTED, evidence=(_OTHER_CITED,)
        )

        result = await make_writer(store, FakeMemoryPolicy()).ingest(
            _retiring(new, old, MemoryOperationKind.END)
        )

        assert result.record_id == "new"
        retired = {record.id: record for record in await _memories(store)}["old"]
        assert isinstance(retired, Memory)
        assert retired.status is MemoryStatus.ENDED

    async def test_a_confirmation_retires_an_assertion_only_where_the_question_showed_it(
        self, make_writer: WriterFactory
    ) -> None:
        """§12:4, ADR-0328 §4:6: a confirmation retires an assertion the question showed.

        Without the answer's authority over the old assertion the retirement is refused;
        with a confirmation covering it (ADR-0078 §5b) it stands.
        """
        store = await self._observer_store()
        old = await self._stored(store, _preference("old", source=MemorySource.USER_ASSERTED))
        before = await _snapshot(store)
        confirmed = confirmed_support(_OTHER_CITED, when=_WHEN, added_at=_WHEN)
        new = memory("new", _DISAGREEING, confirmed)
        bare = _retiring(new, old, MemoryOperationKind.END)

        with pytest.raises(MemoryStoreError, match="§4:6"):
            await make_writer(store, FakeMemoryPolicy()).ingest(bare)
        assert await _snapshot(store) == before

        asked = bare.model_copy(update={"conflicts": ("old",)})
        covered = asked.model_copy(
            update={
                "confirmation": UserConfirmation(
                    question=QuestionPart(round="round-1", part=1),
                    question_key=asked.question_key,
                    confirmed_at=_WHEN,
                    retires=("old",),
                )
            }
        )
        result = await make_writer(store, FakeMemoryPolicy()).ingest(covered)

        assert result.record_id == "new"

    async def test_a_confirmation_retires_an_inference_without_covering_it(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0328 §4:6: the retirement class needs no answer's authority (ADR-0079 §3)."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        new = memory("new", _DISAGREEING, confirmed_support(_OTHER_CITED, when=_WHEN))

        result = await make_writer(store, FakeMemoryPolicy()).ingest(
            _retiring(new, old, MemoryOperationKind.END)
        )

        assert result.record_id == "new"

    async def test_a_retirement_of_a_memory_another_writer_moved_writes_nothing(
        self, make_writer: WriterFactory
    ) -> None:
        """§12:4: the retired memory's write is conditional on its revision as read."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        await store.add(old.model_copy(update={"topics": ("moved",)}))
        before = await _snapshot(store)
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))

        with pytest.raises(MemoryStoreStaleError):
            await make_writer(store, FakeMemoryPolicy()).ingest(
                _retiring(new, old, MemoryOperationKind.END)
            )

        assert await _snapshot(store) == before

    async def test_a_retirement_of_a_memory_carrying_the_cited_part_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """§12:4: the cited support is added to the retired memory, which lacks it."""
        store = await self._observer_store()
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))
        old = await self._stored(store, memory("old", _CONTENT, *_preference("o").supports))
        carrying = Memory.model_validate(
            old.model_dump()
            | {
                "supports": (
                    *old.supports,
                    new.supports[0].model_copy(update={"backs_as_worded": False}),
                )
            }
        )
        await store.add(carrying)
        read = await store.get("old")
        assert isinstance(read, Memory)
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError, match="carries that part already"):
            await make_writer(store, FakeMemoryPolicy()).ingest(
                _retiring(new, read, MemoryOperationKind.END)
            )

        assert await _snapshot(store) == before

    async def test_a_retirement_the_retired_memory_cannot_take_is_refused(
        self, make_writer: WriterFactory
    ) -> None:
        """ADR-0328 §5:7: an ended memory is not ended again, so nothing is written."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        writer = make_writer(store, FakeMemoryPolicy())
        await writer.apply(
            MemoryChange(
                memory=old,
                operation=MemoryOperation(
                    kind=MemoryOperationKind.END,
                    cites=old.supports[0].points_at,
                    at=_WHEN,
                    by=MemoryWriterName.OBSERVER,
                ),
            )
        )
        (ended,) = [record for record in await _memories(store) if record.id == "old"]
        assert isinstance(ended, Memory)
        before = await _snapshot(store)
        new = _preference("new", _DISAGREEING, evidence=(_OTHER_CITED,))

        with pytest.raises(MemoryStoreError, match="§5:7"):
            await writer.ingest(_retiring(new, ended, MemoryOperationKind.END))

        assert await _snapshot(store) == before

    # · the observer's inference (§9:7)

    async def test_an_inference_reading_its_companions_is_kept(
        self, make_writer: WriterFactory
    ) -> None:
        """§9:7: ``for`` and backing, beside ``for`` supports that do not back as worded."""
        store = await self._observer_store()
        new = _inferred("new")

        result = await make_writer(store, FakeMemoryPolicy()).ingest(_proposal(new))

        assert result.record_id == "new"
        written = await store.get("new")
        assert isinstance(written, Memory)
        assert _unstamped(written) == new
        assert written.standing is MemoryStanding.INFERENCE
        assert not written.rests_on_outside_content

    @pytest.mark.parametrize(
        "shape",
        [
            "alone",
            "companion-backs",
            "companion-against",
            "inference-not-backing",
            "inference-against",
            "two-inferences",
            "misdated",
        ],
    )
    async def test_an_inference_the_clause_does_not_admit_is_refused(
        self, make_writer: WriterFactory, shape: str
    ) -> None:
        """§9:7: every other shape of an inference on a proposal, with nothing written."""
        store = await self._observer_store()
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError, match="§9:7"):
            await make_writer(store, FakeMemoryPolicy()).ingest(
                _proposal(_inadmissible_inference(shape))
            )

        assert await _snapshot(store) == before

    @pytest.mark.parametrize("carried", ["every-companion", "no-companion"])
    async def test_a_reinforce_admits_an_inference_among_the_supports_it_adds(
        self, make_writer: WriterFactory, carried: str
    ) -> None:
        """§9:7 holds over what a fold actually adds, after ADR-0328 §4:8's deduplication.

        Where the target already carries every companion, the fold would add the
        inference alone, and the whole write is refused; where it carries none of them,
        the inference arrives with the supports it reads and is added with them.
        """
        store = await self._observer_store()
        new = _inferred("new")
        companions = new.supports[1:]
        base = remembered_support(_THIRD_CITED, effect="effect-target", when=_WHEN, added_at=_WHEN)
        held = (*companions,) if carried == "every-companion" else ()
        target = memory("target", _DISAGREEING, base, *held)
        await store.add(target)
        before = await _snapshot(store)
        writer = make_writer(store, FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

        if carried == "every-companion":
            with pytest.raises(MemoryStoreError, match="§9:7"):
                await writer.ingest(_proposal(new))
            assert await _snapshot(store) == before
            return
        result = await writer.ingest(_proposal(new))
        assert result.record_id == "target"
        written = await store.get("target")
        assert isinstance(written, Memory)
        assert {one.points_at for one in new.supports} <= {
            one.points_at for one in written.supports
        }

    @pytest.mark.parametrize("direction", list(SupportDirection), ids=str)
    async def test_apply_never_adds_an_inference(
        self, make_writer: WriterFactory, direction: SupportDirection
    ) -> None:
        """§9:7: an operation adds one support alone, never an inference."""
        store = await self._observer_store()
        read = await self._stored(store, _preference("existing"))
        support = inference_support(_OTHER_CITED, when=_WHEN, direction=direction)
        kind = (
            MemoryOperationKind.ADD_SUPPORT
            if direction is SupportDirection.FOR
            else MemoryOperationKind.END
        )
        operation = MemoryOperation(
            kind=kind, cites=support.points_at, at=_WHEN, by=MemoryWriterName.OBSERVER
        )

        with pytest.raises(MemoryStoreError, match="§9:7"):
            await make_writer(store, FakeMemoryPolicy()).apply(
                MemoryChange(memory=read, operation=operation, support=support)
            )

        assert await store.get("existing") == read

    async def test_an_inference_retires_a_memory_at_inference_and_only_there(
        self, make_writer: WriterFactory
    ) -> None:
        """§9:7, §12:4: ``against`` on the memory its ingest retires; §6:5 bounds it."""
        store = await self._observer_store()
        old = await self._stored(store, _preference("old"))
        said = await self._stored(
            store,
            _preference("said", "prefers long letters", source=MemorySource.USER_ASSERTED),
        )
        new = _inferred("new")
        inference = new.supports[0]
        before = await _snapshot(store)

        with pytest.raises(MemoryStoreError, match="§6:5"):
            await make_writer(store, FakeMemoryPolicy()).ingest(
                _retiring(new, said, MemoryOperationKind.END)
            )
        assert await _snapshot(store) == before

        result = await make_writer(store, FakeMemoryPolicy()).ingest(
            _retiring(new, old, MemoryOperationKind.END)
        )

        assert result.record_id == "new"
        retired = {record.id: record for record in await _memories(store)}["old"]
        assert isinstance(retired, Memory)
        against = retired.support_at(inference.points_at)
        assert against is not None
        assert (against.origin, against.direction) == (
            SupportOrigin.OBSERVER_INFERENCE,
            SupportDirection.AGAINST,
        )


#: A third episode, for a case whose memories rest on three different parts.
_THIRD_CITED = "third-cited-episode"


def _entry(
    episode: str = _CITED, *, held_up: bool = True, note: str = "the suggestion was taken"
) -> TrackRecordEntry:
    """One track-record entry naming ``episode``, recorded by the observer."""
    return TrackRecordEntry(
        episode=episode,
        relied_at=_WHEN,
        held_up=held_up,
        note=note,
        recorded_at=_WHEN,
        recorded_by=MemoryWriterName.OBSERVER,
    )


def _retiring(
    new: Memory,
    retired: Memory,
    kind: MemoryOperationKind,
    *,
    cites: SupportPart | None = None,
) -> MemoryUpdateProposal:
    """``new`` proposed with one retiring operation on ``retired``, citing its first support."""
    return _proposal(new).model_copy(
        update={
            "retiring": MemoryRetirement(
                memory=retired,
                kind=kind,
                cites=new.supports[0].points_at if cites is None else cites,
                note="the new memory shows the old one no longer holds",
            )
        }
    )


def _companions() -> tuple[MemorySupport, MemorySupport]:
    """Two ``for`` supports that bear on a claim without stating it as worded."""
    said = said_support(_OTHER_CITED, when=_WHEN, added_at=_WHEN)
    message = said_support(_THIRD_CITED, when=_WHEN, added_at=_WHEN)
    return (
        said.model_copy(update={"backs_as_worded": False}),
        message.model_copy(update={"backs_as_worded": False}),
    )


def _inferred(record_id: str) -> Memory:
    """A memory whose claim is an inference read from two companions (§9:7)."""
    return memory(
        record_id,
        _DISAGREEING,
        inference_support(_CITED, when=_WHEN, added_at=_WHEN),
        *_companions(),
    )


def _inadmissible_inference(shape: str) -> Memory:
    """A memory carrying an inference in a shape §9:7 does not admit."""
    inference = inference_support(_CITED, when=_WHEN, added_at=_WHEN)
    first, second = _companions()
    said = said_support(_OTHER_CITED, when=_WHEN, added_at=_WHEN)
    shapes: dict[str, tuple[MemorySupport, ...]] = {
        "alone": (inference,),
        "companion-backs": (inference, said),
        "companion-against": (
            inference,
            said_support(
                _OTHER_CITED, when=_WHEN, added_at=_WHEN, direction=SupportDirection.AGAINST
            ),
        ),
        "inference-not-backing": (
            said,
            inference.model_copy(update={"backs_as_worded": False}),
            second,
        ),
        "inference-against": (
            said,
            inference_support(
                _THIRD_CITED, when=_WHEN, added_at=_WHEN, direction=SupportDirection.AGAINST
            ),
        ),
        "two-inferences": (
            inference,
            inference_support(_THIRD_CITED, when=_WHEN, added_at=_WHEN),
            first,
        ),
        "misdated": (
            inference.model_copy(update={"when": _WHEN + timedelta(hours=1)}),
            first,
            second,
        ),
    }
    return memory("new", _DISAGREEING, *shapes[shape])

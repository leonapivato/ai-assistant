"""Shared conformance suite for the DeferralStore Protocol (ADR-0078 §2).

Every ``DeferralStore`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`DeferralStoreContract` and overrides the ``store`` and ``factory``
fixtures plus the suspension hook; the suite asserts only behaviour *universal*
to the contract.

Three subjects, deliberately.

* ``store`` is the plain one, built with the implementation's own defaults — that
  is what pins the *defaults* the contract names, and it is the fixture the
  Protocol-triad check evaluates.
* ``factory`` builds a store with a movable clock, a scripted token source and
  chosen tuning, because most of ADR-0078's obligations — the deadline boundary,
  the cap, the purge anchors, the token re-draw — are unreachable against a store
  whose clock and token source are fixed.
* ``store_suspended_mid_write`` hands back a store whose next entry into its own
  exclusion can be held open, which is the only way to drive the four
  compare-and-set clauses (§2's admission atomicity, ``claim``, the unclaimed
  rejection, and the no-resurrection product) as races rather than as sequential
  calls that would pass against a read-then-write backend.

What is **not** here, and why. Everything ADR-0078 §10 item 3 lists — the write
stage's enqueue, the answer path's ``claim``/``ingest``/``resolve`` sequence, the
re-deferral branch, cancellation of that sequence, the composition-root
obligations — is a property of the *sequence* rather than of one store, so it
belongs with the coordinator (`tests/orchestration/`). What this suite holds is
every obligation local to one store, including the store-level half of the
concurrency clauses, so that every implementation is held to them rather than only
the wiring.

The 25 clauses ADR-0078 §2 names are each carried by a test below whose docstring
says which one it is and what breaks without it.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import DeferralIdConflictError, DeferralStoreError
from ai_assistant.core.types import (
    TERMINAL_DEFERRAL_STATES,
    DataTier,
    DeferralAdmissionOutcome,
    DeferralState,
    DeferredProposal,
    MemoryDecision,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    ProceduralMemory,
    Provenance,
    SemanticMemory,
    UserConfirmation,
    Validity,
)
from ai_assistant.testing.cancellation import settle

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import DeferralStore
    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.testing.cancellation import SuspendedMidWrite

#: The instant every store fixture's clock starts at.
_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_TICK = timedelta(microseconds=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)

#: The lifetime the ``factory``-built stores use unless a case varies it: long
#: enough that nothing lapses by accident, short enough to step over.
_TTL = 7 * _DAY

#: The cap the ``factory``-built stores use unless a case varies it: roomy, so a
#: case that is not about the cap never trips it.
_LIMIT = 200

#: The ruling every question below carries. Nothing else is a question.
_ASK = MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="which of these do you hold?")


class MovableClock:
    """A clock a case can step forward, so a deadline is reachable in a test."""

    def __init__(self, start: datetime = _NOW) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self._now += delta

    def set(self, instant: datetime) -> None:
        """Move the clock to exactly ``instant`` — the boundary cases need equality."""
        self._now = instant


class ScriptedTokens:
    """A claim-token source handing out a fixed script, then distinct fallbacks.

    ADR-0078 §2's live-collision re-draw is only reachable through a source that
    repeats, and the source is injected precisely so that it can. The fallback is
    distinct per call so a case that runs past its script does not silently start
    colliding.
    """

    def __init__(self, script: Sequence[str]) -> None:
        self._script = list(script)
        self._served = 0

    def __call__(self) -> str:
        self._served += 1
        if self._script:
            return self._script.pop(0)
        return f"fallback-token-{self._served}"


class DeferralStoreFactory(Protocol):
    """Builds the subject with every injected seam the contract names."""

    def __call__(
        self,
        *,
        now: Callable[[], datetime],
        retention: timedelta | None,
        queue_limit: int,
        new_claim_id: Callable[[], str],
    ) -> DeferralStore:
        """Return a store wired to these seams."""
        ...


class DeferralStoreRebuild(Protocol):
    """Reopens an implementation's *same durable state* under different tuning.

    The seam ADR-0078 §2's stored-retention clause needs and nothing else: a
    conforming store reads its lifetime once, at construction, so "the setting has
    changed since this question was admitted" is only expressible across two
    instances over one state. An implementation that keeps no state between
    instances has no way to express it and says so (see
    :meth:`DeferralStoreContract.rebuild`).
    """

    def __call__(
        self,
        store: DeferralStore,
        *,
        now: Callable[[], datetime],
        retention: timedelta | None,
        queue_limit: int,
    ) -> DeferralStore:
        """Return a store over ``store``'s state, tuned as given."""
        ...


def _build(
    factory: DeferralStoreFactory,
    *,
    now: Callable[[], datetime] | None = None,
    retention: timedelta | None = _TTL,
    queue_limit: int = _LIMIT,
    new_claim_id: Callable[[], str] | None = None,
) -> DeferralStore:
    """Build a subject, filling in whatever the case does not care about."""
    return factory(
        now=now or MovableClock(),
        retention=retention,
        queue_limit=queue_limit,
        new_claim_id=new_claim_id or ScriptedTokens([]),
    )


def _record(  # noqa: PLR0913 — one keyword per field a fingerprint case has to vary
    fact: str = "the user prefers dark mode",
    *,
    record_id: str = "rec-1",
    source: MemorySource = MemorySource.OBSERVED,
    confidence: float = 0.6,
    evidence: tuple[str, ...] = (),
    score: float | None = None,
    last_updated: datetime = _NOW,
    validity: Validity | None = None,
) -> MemoryRecord:
    """A semantic record, with every field a fingerprint case needs to vary."""
    return SemanticMemory(
        id=record_id,
        content=fact,
        fact=fact,
        score=score,
        validity=validity if validity is not None else Validity(),
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else confidence,
            evidence=evidence,
            last_updated=last_updated,
        ),
    )


def _proposal(
    fact: str = "the user prefers dark mode",
    *,
    conflicts: tuple[str, ...] = (),
    sensitivity: DataTier = DataTier.PERSONAL,
    rationale: str = "it contradicts a prior assertion",
    record: MemoryRecord | None = None,
) -> MemoryUpdateProposal:
    """A deferrable proposal."""
    return MemoryUpdateProposal(
        proposed=record if record is not None else _record(fact),
        rationale=rationale,
        sensitivity=sensitivity,
        conflicts=conflicts,
    )


async def _admit(
    store: DeferralStore, deferral_id: str, proposal: MemoryUpdateProposal | None = None
) -> DeferredProposal:
    """Admit a question and return the record, failing loudly if it was not admitted."""
    admission = await store.defer(
        deferral_id=deferral_id,
        proposal=proposal if proposal is not None else _proposal(deferral_id),
        decision=_ASK,
    )
    assert admission.outcome is DeferralAdmissionOutcome.ADMITTED
    assert admission.deferral is not None
    return admission.deferral


async def _claim(store: DeferralStore, deferral_id: str) -> str:
    """Claim a question and return its token, failing loudly if it was not open."""
    claim = await store.claim(deferral_id)
    assert claim is not None
    return claim.claim_id


def _ids(rows: Sequence[DeferredProposal]) -> list[str]:
    return [row.id for row in rows]


async def _dumped(store: DeferralStore, deferral_id: str) -> str:
    """Every read's JSON rendering of one question, concatenated.

    What the token-secrecy clause searches: a capability that appears in *any*
    read is a capability an export leaks (ADR-0078 §2).
    """
    one = await store.get(deferral_id)
    payloads = [
        [] if one is None else [one.model_dump(mode="json")],
        [row.model_dump(mode="json") for row in await store.pending()],
        [row.model_dump(mode="json") for row in await store.interrupted()],
        [row.model_dump(mode="json") for row in await store.export()],
    ]
    return json.dumps(payloads)


# --- the no-resurrection product (clause 4) ----------------------------------
# A continuation is a write that mutates a row it has already observed; a
# destruction is `delete`, `clear` or `purge`. The rule is quantified over both
# classes, so it is driven as a product: the axes are not interchangeable, and a
# rule tested on one pair is how this clause has already drifted twice.


class _Continuation(Protocol):
    """One write that mutates a row it has already observed (ADR-0078 §2)."""

    #: The operation name the suspension hook arms — the store's own method name,
    #: which is what ties this axis to a specific lock site rather than to "some
    #: write".
    name: str

    async def prepare(self, store: DeferralStore, deferral_id: str) -> None:
        """Seed whatever the continuation needs before it can run."""
        ...

    def run(self, store: DeferralStore, deferral_id: str) -> asyncio.Future[object]:
        """Start the continuation."""
        ...


class _ClaimContinuation:
    """``claim`` on a row it read as ``PENDING``; recreates it as ``APPLYING``."""

    name = "claim"

    async def prepare(self, store: DeferralStore, deferral_id: str) -> None:
        """Nothing beyond the seeded ``PENDING`` row."""

    def run(self, store: DeferralStore, deferral_id: str) -> asyncio.Future[object]:
        return asyncio.ensure_future(store.claim(deferral_id))


class _ClaimedResolveContinuation:
    """A claimed ``resolve``; recreates the row terminal, holding a claim."""

    name = "resolve"

    def __init__(self) -> None:
        self._token = ""

    async def prepare(self, store: DeferralStore, deferral_id: str) -> None:
        """Claim the row, so the resolve has a token to present."""
        self._token = await _claim(store, deferral_id)

    def run(self, store: DeferralStore, deferral_id: str) -> asyncio.Future[object]:
        return asyncio.ensure_future(
            store.resolve(
                deferral_id,
                claim_id=self._token,
                state=DeferralState.ACCEPTED,
                record_id="written-1",
            )
        )


class _UnclaimedResolveContinuation:
    """The one unclaimed compare-and-set: ``PENDING`` → ``REJECTED``."""

    name = "resolve"

    async def prepare(self, store: DeferralStore, deferral_id: str) -> None:
        """Nothing: an unclaimed rejection takes no claim."""

    def run(self, store: DeferralStore, deferral_id: str) -> asyncio.Future[object]:
        return asyncio.ensure_future(
            store.resolve(deferral_id, claim_id=None, state=DeferralState.REJECTED)
        )


#: The three continuations, by case id. **Factories, not instances**: the claimed
#: resolve carries the token its ``prepare`` took, so a shared instance would leak
#: one case's capability into the next.
_CONTINUATIONS: dict[str, Callable[[], _Continuation]] = {
    "claim": _ClaimContinuation,
    "claimed-resolve": _ClaimedResolveContinuation,
    "unclaimed-resolve": _UnclaimedResolveContinuation,
}

#: The three destructions, which differ in scope and in who triggers them —
#: ``purge`` is the only one driven by a clock rather than a caller.
_DESTRUCTIONS = ("delete", "clear", "purge")

#: The full product, for the ordering in which the continuation commits first.
_CONTINUATION_FIRST = [
    pytest.param(destruction, kind, id=f"{kind}-then-{destruction}")
    for destruction in _DESTRUCTIONS
    for kind in _CONTINUATIONS
]

#: The same product **minus one pair**, and the exclusion is the rule rather than a
#: gap: a ``purge`` may never take an ``APPLYING`` row at any age, so there is no
#: ordering in which it destroys a claimed answer out from under its ``resolve``.
#: Excluded from the product rather than skipped inside the case, because a skipped
#: obligation is an obligation that did not happen — the other ordering asserts the
#: same rule from the inside.
_DESTRUCTION_FIRST = [
    pytest.param(destruction, kind, id=f"{destruction}-then-{kind}")
    for destruction in _DESTRUCTIONS
    for kind in _CONTINUATIONS
    if not (destruction == "purge" and kind == "claimed-resolve")
]


async def _destroy(store: DeferralStore, destruction: str) -> object:
    """Run the named destruction on ``d1``, so the product can name one axis."""
    if destruction == "delete":
        return await store.delete("d1")
    if destruction == "clear":
        return await store.clear()
    return await store.purge()


class DeferralStoreContract:
    """The behavioural contract every ``DeferralStore`` must satisfy (ADR-0078 §2)."""

    @pytest.fixture
    def store(self) -> DeferralStore:
        """Override in a subclass: the implementation on its own defaults."""
        raise NotImplementedError

    @pytest.fixture
    def factory(self) -> DeferralStoreFactory:
        """Override in a subclass: build the subject over these injected seams."""
        raise NotImplementedError

    @pytest.fixture
    def rebuild(self) -> DeferralStoreRebuild | None:
        """Override where the implementation's state outlives one instance.

        ``None`` — the default — means it does not, and the one clause that needs
        it bows out saying so.
        """
        return None

    def store_suspended_mid_write(
        self,
        *,
        now: Callable[[], datetime],
        retention: timedelta | None = _TTL,
        queue_limit: int = _LIMIT,
        new_claim_id: Callable[[], str] | None = None,
    ) -> AbstractAsyncContextManager[SuspendedMidWrite[DeferralStore]]:
        """Override in a subclass: a store whose next named write can be held open.

        The suite runs any preconditions first, then calls ``arm`` with the
        operation's name to get the lever back — *after* the preconditions, so a
        fake arming its single modelled resource suspends the operation under test
        rather than a setup write.

        Its own store on its own state, never the ``store`` fixture's: a suspended
        worker is parked for the length of the case, and sharing would make an
        unrelated failure hang instead of fail. The tuning is passed in because the
        clauses that need a race also need a movable clock, a chosen lifetime and,
        for the cap, a chosen ceiling — none of which the plain subject has.

        Returned as a context manager so the subject is disposed of the way that
        implementation needs.
        """
        raise NotImplementedError

    # --- structure and the plain defaults ------------------------------------

    def test_conforms_to_protocol(self, store: DeferralStore) -> None:
        from ai_assistant.core.protocols import DeferralStore as Contract  # noqa: PLC0415

        assert isinstance(store, Contract)

    async def test_an_empty_store_reads_empty(self, store: DeferralStore) -> None:
        assert await store.pending() == []
        assert await store.interrupted() == []
        assert await store.export() == []
        assert await store.get("nothing") is None
        assert await store.purge() == 0
        assert await store.clear() == 0
        assert await store.delete("nothing") is False

    async def test_a_question_is_admitted_and_readable(self, store: DeferralStore) -> None:
        admitted = await _admit(store, "d1")

        assert admitted.state is DeferralState.PENDING
        assert admitted.proposal.conflicts == ()
        assert await store.get("d1") == admitted
        assert _ids(await store.pending()) == ["d1"]
        assert _ids(await store.export()) == ["d1"]
        assert await store.interrupted() == []

    async def test_the_plain_store_stamps_a_finite_lifetime(self, store: DeferralStore) -> None:
        """The default is **finite**, which is the whole of ADR-0078 §6's decision.

        A never-expiring queue of machine-asked questions is the undignified pile
        §7 exists to prevent, and ``None`` is reachable only as the user's
        deliberate "ask me forever". Asserted on the *plain* subject, because a
        default nothing exercises is a default nothing holds.
        """
        admitted = await _admit(store, "d1")

        assert admitted.retention is not None
        assert admitted.retention > timedelta(0)
        assert admitted.expires_at == admitted.deferred_at + admitted.retention

    # --- clause 23: the store stamps the admission ---------------------------

    async def test_defer_stamps_the_admission_from_its_own_clock_and_lifetime(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 23 (§2). Three values the caller cannot reach.

        An assertion about the *signature* as much as the behaviour: there is no
        argument able to change ``deferred_at``, ``retention`` or ``expires_at``,
        which is what stops a question being admitted already lapsed — never
        answerable, immediately purgeable, its content dropped in silence — or
        dated far enough ahead to hold the queue and its Tier 1 content for
        decades. Neither is caught by a validator that only checks the fields
        agree with each other: 1970 and 2100 are both perfectly self-consistent.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=3 * _DAY)

        admitted = await _admit(store, "d1")

        assert admitted.deferred_at == _NOW
        assert admitted.retention == 3 * _DAY
        assert admitted.expires_at == _NOW + 3 * _DAY

    async def test_an_ask_me_forever_store_stamps_no_deadline(
        self, factory: DeferralStoreFactory
    ) -> None:
        store = _build(factory, retention=None)

        admitted = await _admit(store, "d1")

        assert admitted.retention is None
        assert admitted.expires_at is None

    async def test_a_lifetime_with_no_representable_deadline_refuses_the_admission(
        self, factory: DeferralStoreFactory
    ) -> None:
        """The overflow boundary, reported as this seam's own error.

        ``deferral_ttl`` is bounded below and not above — a lifetime is a positive
        duration, and no upper bound is meaningful in the abstract — so a
        configuration can name one whose deadline falls past the representable
        range. Whether it does depends on *when* the question is admitted, not on
        the lifetime alone, so it cannot honestly be refused at construction; it is
        refused at the admission instead, and refused as ``DeferralStoreError``
        rather than as a raw ``OverflowError`` that would escape an adapter's
        ``AssistantError`` handler as a traceback.

        Nothing is admitted, which is the half that matters: a question half-written
        under an unstampable deadline would be answerable forever and never purged.
        """
        store = _build(factory, retention=timedelta.max)

        with pytest.raises(DeferralStoreError):
            await store.defer(deferral_id="d1", proposal=_proposal(), decision=_ASK)

        assert await store.export() == []
        assert await store.get("d1") is None

    # --- clause 22: the record type refuses an inconsistent question --------

    async def test_a_secret_tier_proposal_is_refused_and_admits_nothing(
        self, store: DeferralStore
    ) -> None:
        """Clause 22, the sensitivity group (§1, §2).

        ADR-0004 §3 is unconditional — Tier 0 secrets live in the OS keyring,
        "never in the memory database, never in a committed file" — and a durable
        queue is a file. Today the secret-tier arm of the policy is precisely what
        keeps such content *out* of storage, so persisting it here would open a gap
        rather than close one. The clause that keeps that true of this store **no
        matter who calls it**.
        """
        with pytest.raises(ValueError, match="SECRET"):
            await store.defer(
                deferral_id="d1",
                proposal=_proposal(sensitivity=DataTier.SECRET),
                decision=_ASK,
            )

        assert await store.export() == []
        assert await store.get("d1") is None

    @pytest.mark.parametrize(
        "kind", [kind for kind in MemoryDecisionKind if kind is not MemoryDecisionKind.ASK_USER]
    )
    async def test_a_ruling_that_is_not_ask_user_is_refused_and_admits_nothing(
        self, store: DeferralStore, kind: MemoryDecisionKind
    ) -> None:
        """Clause 22, the ruling group (§2), parametrised over the enum.

        A record built around an ``ACCEPT`` or a ``SUPERSEDE`` is not a question at
        all — it is a durable pending entry for a proposal nobody deferred, which a
        surface would present and an answer path would re-ingest as though a user
        had been asked. Parametrised over every other member rather than sampled,
        because a rule about which member is admissible is exactly the kind a later
        member silently joins the wrong side of.
        """
        target = (
            "rec-9"
            if kind in {MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE}
            else None
        )
        ttl = _HOUR if kind is MemoryDecisionKind.STORE_TEMPORARY else None
        decision = MemoryDecision(kind=kind, reason="not a question", target_id=target, ttl=ttl)

        with pytest.raises(ValueError, match="ASK_USER"):
            await store.defer(deferral_id="d1", proposal=_proposal(), decision=decision)

        assert await store.export() == []

    @pytest.mark.parametrize(
        ("retention", "expires_at"),
        [
            pytest.param(_DAY, None, id="a-lifetime-with-no-deadline"),
            pytest.param(None, _NOW + _DAY, id="a-deadline-with-no-lifetime"),
            pytest.param(timedelta(0), _NOW, id="a-zero-lifetime"),
            pytest.param(-_DAY, _NOW - _DAY, id="a-negative-lifetime"),
            pytest.param(_DAY, _NOW + 2 * _DAY, id="a-deadline-that-is-not-the-sum"),
        ],
    )
    def test_the_record_refuses_an_inconsistent_deadline(
        self, retention: timedelta | None, expires_at: datetime | None
    ) -> None:
        """Clause 22, the deadlines group (§2).

        Without these a question is admissible with a one-day ``retention`` and no
        ``expires_at``, and a literal implementation keeps it answerable forever and
        never purges it — ADR-0078 §1's finite exposure cap defeated by a record the
        contract accepted.
        """
        with pytest.raises(ValidationError):
            DeferredProposal(
                id="d1",
                proposal=_proposal(),
                decision=_ASK,
                state=DeferralState.PENDING,
                deferred_at=_NOW,
                retention=retention,
                expires_at=expires_at,
            )

    @pytest.mark.parametrize(
        ("state", "stamps"),
        [
            pytest.param(DeferralState.PENDING, {"claimed_at": _NOW}, id="pending-claimed"),
            pytest.param(DeferralState.PENDING, {"answered_at": _NOW}, id="pending-answered"),
            pytest.param(
                DeferralState.PENDING, {"outcome_record_id": "r"}, id="pending-with-a-record"
            ),
            pytest.param(
                DeferralState.PENDING, {"successor_id": "d2"}, id="pending-with-a-successor"
            ),
            pytest.param(DeferralState.APPLYING, {}, id="applying-unclaimed"),
            pytest.param(
                DeferralState.APPLYING,
                {"claimed_at": _NOW, "answered_at": _NOW},
                id="applying-answered",
            ),
            pytest.param(
                DeferralState.APPLYING,
                {"claimed_at": _NOW, "outcome_record_id": "r"},
                id="applying-with-a-record",
            ),
            pytest.param(
                DeferralState.ACCEPTED,
                {"claimed_at": _NOW, "outcome_record_id": "r"},
                id="accepted-unanswered",
            ),
            pytest.param(
                DeferralState.ACCEPTED,
                {"answered_at": _NOW, "outcome_record_id": "r"},
                id="accepted-unclaimed",
            ),
            pytest.param(
                DeferralState.ACCEPTED,
                {"claimed_at": _NOW, "answered_at": _NOW},
                id="accepted-naming-nothing",
            ),
            pytest.param(
                DeferralState.ACCEPTED,
                {
                    "claimed_at": _NOW,
                    "answered_at": _NOW,
                    "outcome_record_id": "r",
                    "successor_id": "d2",
                },
                id="accepted-with-a-successor",
            ),
            pytest.param(DeferralState.REJECTED, {}, id="rejected-unanswered"),
            pytest.param(
                DeferralState.REJECTED,
                {"answered_at": _NOW, "outcome_record_id": "r"},
                id="rejected-with-a-record",
            ),
            pytest.param(
                DeferralState.REJECTED,
                {"answered_at": _NOW, "successor_id": "d2"},
                id="rejected-with-a-successor",
            ),
            pytest.param(DeferralState.STALE, {"answered_at": _NOW}, id="stale-unclaimed"),
            pytest.param(
                DeferralState.STALE,
                {"claimed_at": _NOW, "answered_at": _NOW, "outcome_record_id": "r"},
                id="stale-with-a-record",
            ),
            pytest.param(
                DeferralState.REDEFERRED,
                {"answered_at": _NOW, "successor_id": "d2"},
                id="redeferred-unclaimed",
            ),
            pytest.param(
                DeferralState.REDEFERRED,
                {"claimed_at": _NOW, "answered_at": _NOW},
                id="redeferred-naming-nothing",
            ),
            pytest.param(
                DeferralState.REDEFERRED,
                {
                    "claimed_at": _NOW,
                    "answered_at": _NOW,
                    "successor_id": "d2",
                    "outcome_record_id": "r",
                },
                id="redeferred-with-a-record",
            ),
        ],
    )
    def test_the_record_refuses_a_lifecycle_that_is_not_its_states(
        self, state: DeferralState, stamps: dict[str, object]
    ) -> None:
        """Clause 22, the lifecycle group (§2), parametrised over the states.

        ``ACCEPTED``, ``STALE`` and ``REDEFERRED`` each without ``claimed_at`` is
        the case a single representative misses, and a backend can otherwise
        round-trip one — recording an apply as claim-protected when no claim ever
        covered it. ``REJECTED`` is driven both ways below, since it is the one
        state legal with and without a claim.
        """
        with pytest.raises(ValidationError):
            DeferredProposal(
                id="d1",
                proposal=_proposal(),
                decision=_ASK,
                state=state,
                deferred_at=_NOW,
                retention=_DAY,
                expires_at=_NOW + _DAY,
                **stamps,  # type: ignore[arg-type]  # the case supplies exactly the fields it names
            )

    @pytest.mark.parametrize("claimed_at", [None, _NOW], ids=["unclaimed", "claimed"])
    def test_a_rejected_record_is_legal_with_and_without_a_claim(
        self, claimed_at: datetime | None
    ) -> None:
        """The other half of the lifecycle clause: ``REJECTED`` is the one exception.

        An unclaimed rejection writes nothing, so it needs no claim — and a claimed
        one is how a conforming policy's ``REJECT`` on a confirmed proposal is
        recorded (§2's total outcome mapping). Both are real, so neither may be
        refused.
        """
        record = DeferredProposal(
            id="d1",
            proposal=_proposal(),
            decision=_ASK,
            state=DeferralState.REJECTED,
            deferred_at=_NOW,
            retention=_DAY,
            expires_at=_NOW + _DAY,
            claimed_at=claimed_at,
            answered_at=_NOW,
        )

        assert record.state is DeferralState.REJECTED

    # --- clauses 24 and 25: the fingerprint and the key ---------------------

    def test_the_fingerprint_and_key_agree_across_independently_built_inputs(self) -> None:
        """Clause 24 (§7). The parity the confirmed path depends on.

        The coordinator fingerprints at admission and the writer recomputes at
        answer time. The failure this guards is not a mismatch on some input but a
        mismatch on *every* input — no asserted conflict ever confirmable — so it is
        driven through a serialised round trip rather than by hashing one in-memory
        object twice.
        """
        original = _proposal("a fact", conflicts=("c2", "c1"))
        rebuilt = MemoryUpdateProposal.model_validate_json(original.model_dump_json())

        assert rebuilt.proposal_fingerprint == original.proposal_fingerprint
        assert rebuilt.question_key == original.question_key
        confirmation = UserConfirmation(
            deferral_id="d1", question_key=original.question_key, confirmed_at=_NOW
        )
        assert confirmation.question_key == rebuilt.question_key

    @pytest.mark.parametrize(
        ("left", "right", "collide"),
        [
            pytest.param(
                _proposal(record=_record("f", record_id="a")),
                _proposal(record=_record("f", record_id="b")),
                True,
                id="id-is-excluded",
            ),
            pytest.param(
                _proposal(record=_record("f", score=None)),
                _proposal(record=_record("f", score=0.9)),
                True,
                id="score-is-excluded",
            ),
            pytest.param(
                _proposal(record=_record("f", last_updated=_NOW)),
                _proposal(record=_record("f", last_updated=_NOW + _HOUR)),
                True,
                id="transaction-time-is-excluded",
            ),
            pytest.param(
                _proposal(record=_record("f", evidence=("e1", "e2"))),
                _proposal(record=_record("f", evidence=("e2", "e1"))),
                True,
                id="evidence-order-is-normalised",
            ),
            pytest.param(
                _proposal(record=_record("f", evidence=("e1",))),
                _proposal(record=_record("f", evidence=("e1", "e1"))),
                True,
                id="evidence-repeats-are-normalised",
            ),
            pytest.param(
                _proposal("f", conflicts=("c1", "c2")),
                _proposal("f", conflicts=("c2", "c1")),
                True,
                id="conflict-order-is-normalised",
            ),
            pytest.param(
                _proposal("f", conflicts=("c1",)),
                _proposal("f", conflicts=("c1", "c1")),
                True,
                id="conflict-repeats-are-normalised",
            ),
            pytest.param(
                _proposal(record=_record("f", validity=Validity())),
                _proposal(record=_record("f", validity=Validity(valid_until=_NOW + _DAY))),
                False,
                id="the-validity-window-is-in",
            ),
            pytest.param(
                _proposal(record=_record("f", confidence=0.4)),
                _proposal(record=_record("f", confidence=0.8)),
                False,
                id="confidence-is-in",
            ),
            pytest.param(
                _proposal("f", conflicts=("c1",)),
                _proposal("f", conflicts=("c2",)),
                False,
                id="a-different-conflict-set-is-a-different-question",
            ),
        ],
    )
    def test_the_key_is_a_canonical_projection(
        self, left: MemoryUpdateProposal, right: MemoryUpdateProposal, collide: bool
    ) -> None:
        """Clause 25 (§7). A case per excluded field and a case per collection.

        The exclusions are bookkeeping *about* the record rather than the belief it
        states; the normalisations are collections that are sets in meaning, where
        membership is the content and position is an artefact of how they were
        gathered. Everything else is in: an inventory would have to be extended by
        whoever adds the next field, in a file they are not editing, so the
        criterion classifies it for them.
        """
        assert (left.question_key == right.question_key) is collide

    def test_a_procedural_proposals_step_order_is_preserved(self) -> None:
        """Clause 25's deciding pair (§7): a workflow **is** its order.

        The pair a suite written with tidy fixtures never reaches, since the
        sequences it builds happen to be in the same order every time — and the
        pair that decides whether the canonicalisation is a criterion or a blanket
        sort. A blanket sort passes every other case on the list while letting a
        pending "back up, then delete" suppress "delete, then back up".
        """
        provenance = Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW)
        forwards = ProceduralMemory(
            id="p",
            content="release",
            situation="release",
            steps=("back up", "delete"),
            provenance=provenance,
        )
        backwards = forwards.model_copy(update={"steps": ("delete", "back up")})

        assert _proposal(record=forwards).question_key != _proposal(record=backwards).question_key

    async def test_the_key_collides_on_the_key_and_only_on_the_key(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 13 (§7). Two near-misses admit; the identical repeat collides.

        A suite that varies only ``content`` certifies a weaker key than the one
        ratified: an ``OBSERVED`` proposal and a later ``USER_ASSERTED`` one with
        identical words are **not** the same question — the first asks "shall I keep
        what I worked out?", the second is the user telling us directly — and a
        ``PERSONAL`` and an ``OPERATIONAL`` proposal ask different questions even
        when the words match.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        observed = _proposal(record=_record("one fact", source=MemorySource.OBSERVED))
        asserted = _proposal(record=_record("one fact", source=MemorySource.USER_ASSERTED))
        operational = _proposal("one fact", sensitivity=DataTier.OPERATIONAL)

        await _admit(store, "d1", observed)
        await _admit(store, "d2", asserted)
        await _admit(store, "d3", operational)
        clock.advance(_DAY)
        repeat = await store.defer(deferral_id="d4", proposal=observed, decision=_ASK)

        assert repeat.outcome is DeferralAdmissionOutcome.SUPPRESSED
        assert repeat.deferral is not None
        assert repeat.deferral.id == "d1"
        # Not refreshed: refreshing would let a chatty producer keep a question
        # alive indefinitely by re-proposing, which is the opposite of a lifetime.
        assert repeat.deferral.expires_at == _NOW + _TTL
        assert await store.get("d4") is None

    # --- clause 14: which keys still speak ----------------------------------

    async def test_a_settled_or_lapsed_key_does_not_collide(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 14, the non-speaking half (§2, §7).

        A lapsed question, one that was accepted, one that went stale and one that
        was replaced by the successor it names each deserve a fresh question for a
        fresh proposal. A suite that tests only the live collision leaves all of
        them unpinned — and a lapsed row that suppressed would be a question nobody
        could answer silently swallowing the next honest proposal.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        proposals = {
            name: _proposal(name) for name in ("lapsed", "accepted", "stale", "redeferred")
        }
        for name, proposal in proposals.items():
            await _admit(store, name, proposal)
        accepted_token = await _claim(store, "accepted")
        assert await store.resolve(
            "accepted",
            claim_id=accepted_token,
            state=DeferralState.ACCEPTED,
            record_id="written-1",
        )
        stale_token = await _claim(store, "stale")
        assert await store.resolve("stale", claim_id=stale_token, state=DeferralState.STALE)
        redeferred_token = await _claim(store, "redeferred")
        successor = await store.defer(
            deferral_id="successor",
            proposal=_proposal("redeferred", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="redeferred",
            successor_to_claim=redeferred_token,
        )
        assert successor.outcome is DeferralAdmissionOutcome.ADMITTED
        assert await store.resolve(
            "redeferred",
            claim_id=redeferred_token,
            state=DeferralState.REDEFERRED,
            successor_id="successor",
        )
        clock.advance(2 * _DAY)  # past the lapsed row's deadline

        for name, proposal in proposals.items():
            admission = await store.defer(
                deferral_id=f"fresh-{name}", proposal=proposal, decision=_ASK
            )
            assert admission.outcome is DeferralAdmissionOutcome.ADMITTED, name

    async def test_a_rejected_key_within_retention_and_an_applying_one_collide(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 14, the speaking half (§2, §7).

        "We asked and you declined" and "an answer to that may be committing right
        now" are the two states a fresh arrival must not be given a new question
        for. The first is the no-nagging rule; the second is what stops a twin
        question whose later answer writes the second correction the claim exists to
        prevent.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        rejected = _proposal("declined")
        applying = _proposal("in flight")
        await _admit(store, "rejected", rejected)
        await _admit(store, "applying", applying)
        assert await store.resolve("rejected", claim_id=None, state=DeferralState.REJECTED)
        await _claim(store, "applying")

        for name, proposal in (("rejected", rejected), ("applying", applying)):
            admission = await store.defer(
                deferral_id=f"fresh-{name}", proposal=proposal, decision=_ASK
            )
            assert admission.outcome is DeferralAdmissionOutcome.SUPPRESSED, name
            assert admission.deferral is not None
            assert admission.deferral.id == name

    # --- clause 6 and 7: the physical id ------------------------------------

    @pytest.mark.parametrize(
        "settle_first", [False, True], ids=["against-pending", "against-terminal"]
    )
    async def test_a_physical_id_collision_raises_and_mutates_nothing(
        self, factory: DeferralStoreFactory, settle_first: bool
    ) -> None:
        """Clause 6, the refusal (§2).

        Without it a dict-backed store silently overwrites someone else's pending
        question while a SQL one raises, and the suite certifies two different
        contracts. "Already present" is *physical presence* in ADR-0046 §3's sense,
        which is why a terminal row blocks the id as firmly as a pending one.
        """
        store = _build(factory)
        held = await _admit(store, "d1", _proposal("the first question"))
        if settle_first:
            assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)

        with pytest.raises(DeferralIdConflictError):
            await store.defer(
                deferral_id="d1", proposal=_proposal("a different question"), decision=_ASK
            )

        stored = await store.get("d1")
        assert stored is not None
        assert stored.proposal == held.proposal
        assert _ids(await store.export()) == ["d1"]

    @pytest.mark.parametrize("state", ["pending", "rejected", "applying"])
    async def test_a_same_id_same_key_retry_is_suppressed_not_admitted(
        self, factory: DeferralStoreFactory, state: str
    ) -> None:
        """Clause 7 (§2). The case an id comparison got wrong.

        A caller retrying an uncertain admission under the same id names a question
        that is still open, so the key-idempotent path runs. Comparing the returned
        id to the one the caller minted would call every one of these an admission
        — announcing a newly parked question over a suppressed one — and a suite
        that only ever retries with a fresh id never reaches it.
        """
        store = _build(factory)
        proposal = _proposal("one question")
        await _admit(store, "d1", proposal)
        if state == "rejected":
            assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)
        elif state == "applying":
            await _claim(store, "d1")

        admission = await store.defer(deferral_id="d1", proposal=proposal, decision=_ASK)

        assert admission.outcome is DeferralAdmissionOutcome.SUPPRESSED
        assert admission.deferral is not None
        assert admission.deferral.id == "d1"
        assert admission.deferral.state is DeferralState[state.upper()]

    @pytest.mark.parametrize("finish", ["lapse", "accept"])
    async def test_a_same_id_retry_against_a_key_that_no_longer_speaks_raises(
        self, factory: DeferralStoreFactory, finish: str
    ) -> None:
        """Clause 6's third case (§2). The line the same-key exception stops at.

        Scoping the exception to a *speaking* key is what keeps the two rules from
        disagreeing on a lapsed row, which an earlier revision left open by saying
        only "the same key". That question is finished, the incoming proposal
        deserves a fresh one, and a fresh question gets a fresh id.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        proposal = _proposal("one question")
        await _admit(store, "d1", proposal)
        if finish == "lapse":
            clock.advance(2 * _DAY)
        else:
            token = await _claim(store, "d1")
            assert await store.resolve(
                "d1", claim_id=token, state=DeferralState.ACCEPTED, record_id="written-1"
            )

        with pytest.raises(DeferralIdConflictError):
            await store.defer(deferral_id="d1", proposal=proposal, decision=_ASK)

    async def test_an_id_collision_wins_over_a_key_suppression(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 6's intersection (§2). The input on which two backends diverge.

        An id that collides with one row while the key duplicates another is
        simultaneously both rules' subject. The id collision wins, because it is a
        caller-side minting fault and the suppression path would hide it — handing
        the caller back a different question, under an id it believes it just minted
        and now believes it owns. Two clauses that each pass in isolation say
        nothing about which wins when both apply.
        """
        store = _build(factory)
        first = _proposal("the first question")
        second = _proposal("the second question")
        await _admit(store, "a", first)
        await _admit(store, "b", second)

        with pytest.raises(DeferralIdConflictError):
            await store.defer(deferral_id="a", proposal=second, decision=_ASK)

        assert _ids(await store.export()) == ["a", "b"]
        held = await store.get("a")
        assert held is not None
        assert held.proposal == first

    # --- clause 1: the claim token ------------------------------------------

    async def test_two_live_claims_carry_distinct_tokens(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 1, the uniqueness half (§2), at the width the contract states.

        Distinct across claims of **different deferrals held at the same time**,
        and no more: uniqueness after a resolution or a deletion is deliberately
        not promised, because closing that would need the historical ledger
        ADR-0078 §11 declines.
        """
        store = _build(factory)
        await _admit(store, "d1")
        await _admit(store, "d2", _proposal("another question"))

        assert await _claim(store, "d1") != await _claim(store, "d2")

    async def test_no_read_republishes_a_claim_token(self, factory: DeferralStoreFactory) -> None:
        """Clause 1, the half that actually bites (§2).

        ``interrupted`` publishes every claimed question's id to any caller, so a
        token reachable from a read is a capability anyone holding an id can spend
        — resolving someone else's claim, or spending its cap exemption. It is not
        a field of the record, so ``export`` cannot leak it either: a capability is
        not the user's data.
        """
        minted = "a-very-distinctive-token"
        store = _build(factory, new_claim_id=ScriptedTokens([minted]))
        await _admit(store, "d1")

        token = await _claim(store, "d1")

        assert token == minted
        assert token not in await _dumped(store, "d1")

    async def test_a_token_a_live_claim_already_holds_is_redrawn(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 1, the live-collision path (§2).

        A duplicate is not a cosmetic clash: two live claims sharing a token lets
        either holder resolve the other's question or spend its successor
        exemption, which is the whole capability collapsing.
        """
        tokens = ScriptedTokens(["t1", "t1", "t2"])
        store = _build(factory, new_claim_id=tokens)
        await _admit(store, "d1")
        await _admit(store, "d2", _proposal("another question"))

        first = await _claim(store, "d1")
        second = await _claim(store, "d2")

        assert first == "t1"
        assert second == "t2"

    async def test_an_always_duplicating_token_source_exhausts_and_claims_nothing(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 1's bounded end (§2). "Bounded" without an exhaustion case is a
        loop nobody has counted.

        The deferral is left ``PENDING`` — still answerable, still in ``pending``,
        with no claim minted — because a claim half-taken is a question nothing can
        apply and nothing can sweep.
        """
        store = _build(factory, new_claim_id=lambda: "always-the-same")
        await _admit(store, "d1")
        await _admit(store, "d2", _proposal("another question"))
        await _claim(store, "d1")

        with pytest.raises(DeferralStoreError):
            await store.claim("d2")

        stranded = await store.get("d2")
        assert stranded is not None
        assert stranded.state is DeferralState.PENDING
        assert "d2" in _ids(await store.pending())

    async def test_claim_refuses_a_deferral_that_is_absent_lapsed_or_not_pending(
        self, factory: DeferralStoreFactory
    ) -> None:
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        await _admit(store, "claimed")
        await _admit(store, "lapsing", _proposal("another question"))
        await _claim(store, "claimed")

        assert await store.claim("nothing") is None
        assert await store.claim("claimed") is None
        clock.advance(2 * _DAY)
        assert await store.claim("lapsing") is None

    # --- clauses 9, 19, 20, 21: resolve -------------------------------------

    @pytest.mark.parametrize(
        ("state", "record_id", "successor_id"),
        [
            pytest.param(DeferralState.ACCEPTED, None, None, id="accepted-naming-nothing"),
            pytest.param(DeferralState.ACCEPTED, "r", "d2", id="accepted-with-a-successor"),
            pytest.param(DeferralState.REDEFERRED, None, None, id="redeferred-naming-nothing"),
            pytest.param(DeferralState.REDEFERRED, "r", None, id="redeferred-with-a-record"),
            pytest.param(DeferralState.REJECTED, "r", None, id="rejected-with-a-record"),
            pytest.param(DeferralState.STALE, None, "d2", id="stale-with-a-successor"),
        ],
    )
    async def test_resolve_refuses_a_malformed_terminal_payload(
        self,
        factory: DeferralStoreFactory,
        state: DeferralState,
        record_id: str | None,
        successor_id: str | None,
    ) -> None:
        """Clause 19 (§2). Six cases, and the reason the two ids are separate.

        The transition tests pass against a store that writes whatever payload it is
        handed. Without these a valid claim can resolve ``ACCEPTED`` with no record
        id at all, and the question renders as applied while naming nothing that was
        written — a terminal state that lies, reached through the one call whose
        whole job is to record what happened.
        """
        store = _build(factory)
        await _admit(store, "d1")
        token = await _claim(store, "d1")

        # The message must name the state it refused, for the reason the paging
        # clause qualifies its own: an unqualified ``pytest.raises`` would be
        # satisfied by any ValueError raised anywhere inside the call.
        with pytest.raises(ValueError, match=state.name):
            await store.resolve(
                "d1", claim_id=token, state=state, record_id=record_id, successor_id=successor_id
            )

        held = await store.get("d1")
        assert held is not None
        assert held.state is DeferralState.APPLYING

    @pytest.mark.parametrize("state", [DeferralState.PENDING, DeferralState.APPLYING])
    async def test_resolve_refuses_a_state_that_is_not_terminal(
        self, factory: DeferralStoreFactory, state: DeferralState
    ) -> None:
        store = _build(factory)
        await _admit(store, "d1")
        token = await _claim(store, "d1")

        with pytest.raises(ValueError, match="terminal"):
            await store.resolve("d1", claim_id=token, state=state)

    @pytest.mark.parametrize("terminal", sorted(TERMINAL_DEFERRAL_STATES))
    async def test_every_terminal_state_is_reachable_from_a_claim(
        self, factory: DeferralStoreFactory, terminal: DeferralState
    ) -> None:
        """The mapping from ingest outcome to terminal state is **total** (§2).

        ``REJECTED`` is the one an earlier revision omitted: a ``MemoryWriter``
        takes an injected policy, and a conforming policy that is not the default
        one may rule ``REJECT`` on a confirmed proposal — so an accept whose ingest
        returns ``REJECT`` would otherwise have no legal transition and strand
        forever.
        """
        store = _build(factory)
        await _admit(store, "d1")
        token = await _claim(store, "d1")
        successor_id: str | None = None
        if terminal is DeferralState.REDEFERRED:
            successor = await store.defer(
                deferral_id="d2",
                proposal=_proposal("the successor question", conflicts=("c-new",)),
                decision=_ASK,
                predecessor_id="d1",
                successor_to_claim=token,
            )
            assert successor.deferral is not None
            successor_id = successor.deferral.id

        assert await store.resolve(
            "d1",
            claim_id=token,
            state=terminal,
            record_id="written-1" if terminal is DeferralState.ACCEPTED else None,
            successor_id=successor_id,
        )

        held = await store.get("d1")
        assert held is not None
        assert held.state is terminal

    async def test_resolve_refuses_every_state_and_claim_but_the_ones_it_names(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 9 (§2). A second attempt, an unclaimed accept, and a stale token.

        The ``claim_id`` is what keeps the bookkeeping bound to the apply that
        actually ran: without it a caller who never applied anything could stamp a
        question ``ACCEPTED``.
        """
        store = _build(factory)
        await _admit(store, "unclaimed")
        await _admit(store, "claimed", _proposal("another question"))
        token = await _claim(store, "claimed")

        # An `ACCEPTED` from `PENDING`: an accept that skipped its claim must not
        # commit bookkeeping for an apply nothing authorised.
        assert not await store.resolve(
            "unclaimed", claim_id=None, state=DeferralState.ACCEPTED, record_id="written-1"
        )
        assert not await store.resolve(
            "claimed", claim_id="not-the-token", state=DeferralState.ACCEPTED, record_id="w"
        )
        assert not await store.resolve(
            "claimed", claim_id=None, state=DeferralState.ACCEPTED, record_id="w"
        )
        assert await store.resolve(
            "claimed", claim_id=token, state=DeferralState.ACCEPTED, record_id="written-1"
        )
        assert not await store.resolve(
            "claimed", claim_id=token, state=DeferralState.ACCEPTED, record_id="written-1"
        )
        assert not await store.resolve("nothing", claim_id=None, state=DeferralState.REJECTED)

    async def test_a_redeferred_resolution_must_name_the_successor_the_store_stamped(
        self, factory: DeferralStoreFactory
    ) -> None:
        """The transition is checked against durable state, not the caller's word (§2).

        A ``REDEFERRED`` resolution naming some *other* question is refused, so a
        parent cannot be recorded as having raised a question it never did.
        """
        store = _build(factory)
        await _admit(store, "d1")
        token = await _claim(store, "d1")
        await store.defer(
            deferral_id="d2",
            proposal=_proposal("the successor question", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="d1",
            successor_to_claim=token,
        )
        await _admit(store, "elsewhere", _proposal("an unrelated question"))

        assert not await store.resolve(
            "d1", claim_id=token, state=DeferralState.REDEFERRED, successor_id="elsewhere"
        )
        held = await store.get("d1")
        assert held is not None
        assert held.state is DeferralState.APPLYING
        assert await store.resolve(
            "d1", claim_id=token, state=DeferralState.REDEFERRED, successor_id="d2"
        )

    async def test_a_row_that_raised_a_successor_resolves_only_as_redeferred(
        self, factory: DeferralStoreFactory
    ) -> None:
        """The other half of the durable-state check (§2).

        The record type forbids a successor on every terminal state but
        ``REDEFERRED``, and the store stamps one the moment it admits a successor —
        so a claim that raised a question and then tried to record itself
        ``ACCEPTED`` would be asking the store to persist a contradiction. It is a
        compare-and-set precondition rather than a malformed payload, so it answers
        ``False`` and leaves the claim exactly where it was, still resolvable as the
        one thing it truthfully is.
        """
        store = _build(factory)
        await _admit(store, "d1")
        token = await _claim(store, "d1")
        await store.defer(
            deferral_id="d2",
            proposal=_proposal("the successor question", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="d1",
            successor_to_claim=token,
        )

        assert not await store.resolve(
            "d1", claim_id=token, state=DeferralState.ACCEPTED, record_id="written-1"
        )
        assert not await store.resolve("d1", claim_id=token, state=DeferralState.STALE)
        held = await store.get("d1")
        assert held is not None
        assert held.state is DeferralState.APPLYING
        assert await store.resolve(
            "d1", claim_id=token, state=DeferralState.REDEFERRED, successor_id="d2"
        )

    async def test_resolve_stamps_answered_at_from_the_stores_own_clock(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 20 (§2). An assertion about the signature as much as the behaviour.

        ``answered_at`` is a **retention anchor**, so a caller that supplied it would
        decide how long its own rejection suppresses the next honest proposal:
        an instant in 1970 sweeps the record at once and re-asks something just
        declined; one far in the future keeps the key suppressed long past the
        retention it was admitted under. There is no parameter to forge, which is
        the clause's whole content.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_TTL)
        await _admit(store, "d1")
        clock.advance(_HOUR)

        assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)

        held = await store.get("d1")
        assert held is not None
        assert held.answered_at == _NOW + _HOUR

    async def test_an_unclaimed_rejection_past_the_deadline_fails_and_suppresses_nothing(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 21 (§2). And the second half, which is what the refusal is *for*.

        Without the deadline a client that displayed the question a moment before it
        lapsed could reject it a moment after, and the lapsed row would become a
        retained ``REJECTED`` key that suppresses a fresh identical proposal — the
        one outcome a question nobody could answer must not have.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        proposal = _proposal("one question")
        admitted = await _admit(store, "d1", proposal)
        assert admitted.expires_at is not None
        clock.set(admitted.expires_at - _TICK)
        assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED) is True

        await _admit(store, "d2", _proposal("another question"))
        second = await store.get("d2")
        assert second is not None
        assert second.expires_at is not None
        clock.set(second.expires_at)

        assert await store.resolve("d2", claim_id=None, state=DeferralState.REJECTED) is False
        held = await store.get("d2")
        assert held is not None
        assert held.state is DeferralState.PENDING
        fresh = await store.defer(
            deferral_id="d3", proposal=_proposal("another question"), decision=_ASK
        )
        assert fresh.outcome is DeferralAdmissionOutcome.ADMITTED

    # --- clause 15: the deadline boundary, at the instant -------------------

    async def test_the_answerability_boundary_is_driven_at_the_instant_itself(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 15's four consequences (§2), at ``expires_at`` and one tick before.

        The listed clock cases elsewhere step well past the deadline and never touch
        the comparison two backends actually spell differently: unstated, one store
        writes ``expires_at <= now`` and another ``< now``, and they hide the same
        question one instant apart.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY, queue_limit=1)
        proposal = _proposal("one question")
        admitted = await _admit(store, "d1", proposal)
        assert admitted.expires_at is not None
        deadline = admitted.expires_at

        clock.set(deadline - _TICK)
        assert _ids(await store.pending()) == ["d1"]
        at_cap = await store.defer(
            deferral_id="other", proposal=_proposal("an unrelated question"), decision=_ASK
        )
        assert at_cap.outcome is DeferralAdmissionOutcome.REFUSED
        same_key = await store.defer(deferral_id="again", proposal=proposal, decision=_ASK)
        assert same_key.outcome is DeferralAdmissionOutcome.SUPPRESSED

        clock.set(deadline)
        assert await store.pending() == []
        assert await store.claim("d1") is None
        with_room = await store.defer(
            deferral_id="other", proposal=_proposal("an unrelated question"), decision=_ASK
        )
        assert with_room.outcome is DeferralAdmissionOutcome.ADMITTED
        assert await store.delete("other")
        fresh_key = await store.defer(deferral_id="again", proposal=proposal, decision=_ASK)
        assert fresh_key.outcome is DeferralAdmissionOutcome.ADMITTED

    async def test_the_claim_boundary_admits_one_tick_before_the_deadline(
        self, factory: DeferralStoreFactory
    ) -> None:
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        admitted = await _admit(store, "d1")
        assert admitted.expires_at is not None
        clock.set(admitted.expires_at - _TICK)

        assert await store.claim("d1") is not None

    async def test_purges_two_boundaries_are_driven_at_their_own_instants(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 15's second half (§2). The two anchors differ, so both are driven.

        A suite that drives one and infers the other proves nothing about the one
        carrying ADR-0078 §1's exposure cap — a *lapsed* row is swept at
        ``expires_at`` with no further grace, while a *terminal* row is retained for
        one more lifetime because the no-nagging rule reads it.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        lapsing = await _admit(store, "lapsing")
        assert lapsing.expires_at is not None
        await _admit(store, "rejected", _proposal("a declined question"))
        # Answered halfway through the lifetime, so the terminal grace ends strictly
        # after the lapse: with both anchors on one instant the case would prove
        # nothing about which rule swept which row.
        answered_at = _NOW + _DAY / 2
        clock.set(answered_at)
        assert await store.resolve("rejected", claim_id=None, state=DeferralState.REJECTED)

        clock.set(lapsing.expires_at - _TICK)
        assert await store.purge() == 0
        clock.set(lapsing.expires_at)
        assert await store.purge() == 1
        assert await store.get("lapsing") is None
        assert await store.get("rejected") is not None

        clock.set(answered_at + _DAY - _TICK)
        assert await store.purge() == 0
        assert await store.get("rejected") is not None
        clock.set(answered_at + _DAY)
        assert await store.purge() == 1
        assert await store.get("rejected") is None

    # --- clause 16: ask me forever ------------------------------------------

    async def test_ask_me_forever_never_lapses_and_is_never_purged(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 16 (§2, §6). Five assertions, because an implementation that
        coerces ``None`` to a sentinel passes the first three and fails the rest.

        ``None`` is a real value with stated behaviour, not a gap: left unstated one
        implementation stores a far-future instant and another a ``None``, and the
        two disagree about whether a question still exists.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=None)
        proposal = _proposal("one question")
        await _admit(store, "d1", proposal)
        clock.advance(1000 * _DAY)

        assert _ids(await store.pending()) == ["d1"]
        collides = await store.defer(deferral_id="d2", proposal=proposal, decision=_ASK)
        assert collides.outcome is DeferralAdmissionOutcome.SUPPRESSED
        assert await store.purge() == 0
        assert await store.claim("d1") is not None

        assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED) is False
        # It is `APPLYING` now, so reject it through its claim instead — the point
        # of the last assertion is the retention half, not the transition.
        await store.delete("d1")
        await _admit(store, "d3", proposal)
        assert await store.resolve("d3", claim_id=None, state=DeferralState.REJECTED)
        clock.advance(1000 * _DAY)
        assert await store.purge() == 0
        assert await store.get("d3") is not None

    # --- clause 10, 11, 12: purge, delete, clear ----------------------------

    async def test_purge_sweeps_a_lapsed_question_retains_a_rejected_one_and_never_an_applying_one(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 10 (§2). Four cases pulling in different directions.

        The first is ADR-0078 §1's exposure cap, the second is §7's no-nagging rule,
        the third is §9's guard on the record of an answer, and the fourth is
        ADR-0007's unconditional data right. A suite that applies one grace to every
        finished row passes the second and fails the first.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        await _admit(store, "lapsing")
        await _admit(store, "rejected", _proposal("a declined question"))
        await _admit(store, "applying", _proposal("an interrupted question"))
        # Answered *later* than the admission, so the two anchors genuinely differ:
        # with `answered_at == deferred_at` the terminal grace and the lapse fall on
        # the same instant and the case cannot tell one rule from the other.
        clock.advance(_DAY / 2)
        assert await store.resolve("rejected", claim_id=None, state=DeferralState.REJECTED)
        await _claim(store, "applying")

        # Past `lapsing`'s deadline (`_NOW + _DAY`) and strictly inside `rejected`'s
        # grace (`_NOW + 1.5 * _DAY`), so exactly one row is sweepable.
        clock.advance(_DAY / 2 + _HOUR)
        assert await store.purge() == 1
        assert await store.get("lapsing") is None
        assert await store.get("rejected") is not None

        clock.advance(1000 * _DAY)
        assert await store.purge() == 1  # the rejected row, now past its retention
        assert await store.get("applying") is not None
        assert _ids(await store.interrupted()) == ["applying"]

        assert await store.delete("applying") is True
        assert await store.get("applying") is None

    @pytest.mark.optional_obligation
    async def test_purge_reads_the_stored_retention_not_the_live_setting(
        self, factory: DeferralStoreFactory, rebuild: DeferralStoreRebuild | None
    ) -> None:
        """Clause 11 (§2). Nothing else in this suite varies configuration between
        admission and resolution, so nothing else reaches it.

        Defer under a 30-day lifetime, reject tomorrow, shorten the setting to a
        day: an implementation reading the live setting drops the rejected key 29
        days early and the user is re-asked a question they already declined — a
        retention they never chose, differing between two processes reading
        different config. An implementation that reads the setting passes every
        other purge clause.

        Only expressible across two instances over one state, because a conforming
        store reads its lifetime once at construction. An implementation whose state
        does not outlive an instance says so rather than pretending.
        """
        if rebuild is None:
            pytest.skip("this implementation keeps no state between instances")
        clock = MovableClock()
        store = _build(factory, now=clock, retention=30 * _DAY)
        await _admit(store, "d1")
        clock.advance(_DAY)
        assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)

        shortened = rebuild(store, now=clock, retention=_DAY, queue_limit=_LIMIT)
        clock.advance(2 * _DAY)  # past the *new* setting, well inside the stamped one

        assert await shortened.purge() == 0
        held = await shortened.get("d1")
        assert held is not None
        assert held.retention == 30 * _DAY

    async def test_clear_destroys_every_row_whatever_its_state(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 12 (§2, ADR-0007). "Unconditional" is a word that needs a test.

        Without it an implementation can clear the answerable queue and leave the
        rest while every other clause still passes: ``delete``'s clause drives one
        row and says nothing about the sweep.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY)
        seeded = ["pending", "lapsing", "applying", "accepted", "rejected", "stale", "redeferred"]
        for name in seeded:
            await _admit(store, name, _proposal(name))
        await _claim(store, "applying")
        accepted = await _claim(store, "accepted")
        assert await store.resolve(
            "accepted", claim_id=accepted, state=DeferralState.ACCEPTED, record_id="written-1"
        )
        assert await store.resolve("rejected", claim_id=None, state=DeferralState.REJECTED)
        stale = await _claim(store, "stale")
        assert await store.resolve("stale", claim_id=stale, state=DeferralState.STALE)
        redeferred = await _claim(store, "redeferred")
        successor = await store.defer(
            deferral_id="successor",
            proposal=_proposal("redeferred", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="redeferred",
            successor_to_claim=redeferred,
        )
        assert successor.deferral is not None
        assert await store.resolve(
            "redeferred",
            claim_id=redeferred,
            state=DeferralState.REDEFERRED,
            successor_id="successor",
        )
        clock.advance(2 * _DAY)  # so `lapsing` is lapsed rather than merely pending

        assert await store.clear() == len(seeded) + 1
        assert await store.export() == []
        assert await store.pending() == []
        assert await store.interrupted() == []
        for name in [*seeded, "successor"]:
            assert await store.get(name) is None, name

    # --- clauses 17 and 18: the two enumerations ----------------------------

    async def test_interrupted_enumerates_applying_rows_and_is_disjoint_from_pending(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 17 (§2). A store that returned an interrupted question among the
        answerable ones would offer the user a claim that cannot be taken.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        for index in range(4):
            await _admit(store, f"d{index}", _proposal(f"question {index}"))
            clock.advance(_HOUR)  # so the admission order is unambiguous
        await _claim(store, "d1")
        await _claim(store, "d3")

        assert _ids(await store.pending()) == ["d0", "d2"]
        assert _ids(await store.interrupted()) == ["d1", "d3"]

    @pytest.mark.parametrize("read", ["pending", "interrupted"])
    @pytest.mark.parametrize("argument", ["limit", "offset"])
    @pytest.mark.parametrize(
        "value",
        [-1, 2**63, 1.5, "10", True],
        ids=["negative", "past-the-64-bit-bound", "a-float", "a-string", "a-bool"],
    )
    async def test_both_reads_refuse_a_paging_argument_that_is_not_a_count(
        self, store: DeferralStore, read: str, argument: str, value: object
    ) -> None:
        """Clause 18 (§2), at both ends and on the type.

        ``limit=-1`` is SQLite's spelling for *no limit*, so an unvalidated negative
        turns the bounded read of a Tier 1 queue into an unbounded one; a value past
        the 64-bit bound surfaces a driver ``OverflowError`` instead of this
        contract's refusal; and ``1.5`` satisfies the range while a SQL driver
        refuses to bind it and an in-memory store slices happily with it. ``True`` is
        an ``int`` subclass and is refused because a ``bool`` is not a count.
        """
        # The message must name the offending parameter. That is what separates
        # "the store refused this argument" from any other ValueError raised
        # somewhere inside the read — a decode failure would otherwise satisfy an
        # unqualified ``pytest.raises`` and certify a store that never checked
        # (the qualification ``MemoryStoreContract`` already makes for its own
        # paging clause).
        with pytest.raises(ValueError, match=argument):
            await getattr(store, read)(**{argument: value})

    @pytest.mark.parametrize("read", ["pending", "interrupted"])
    async def test_both_reads_page_by_the_ids_they_return(
        self, factory: DeferralStoreFactory, read: str
    ) -> None:
        """Clause 18's offset half (§2), asserting **ids** rather than page length.

        ADR-0073 §8's own warning: an implementation ignoring ``offset`` returns a
        full ordered page every time and passes a length-only assertion for good.
        """
        clock = MovableClock()
        store = _build(factory, now=clock)
        for index in range(5):
            await _admit(store, f"d{index}", _proposal(f"question {index}"))
            clock.advance(_HOUR)
            if read == "interrupted":
                await _claim(store, f"d{index}")

        page = await getattr(store, read)(limit=2, offset=1)

        assert _ids(page) == ["d1", "d2"]
        assert _ids(await getattr(store, read)(limit=2, offset=4)) == ["d4"]
        assert await getattr(store, read)(limit=0) == []

    @pytest.mark.parametrize("read", ["pending", "interrupted"])
    async def test_both_reads_are_bounded_when_a_caller_names_no_limit(
        self, factory: DeferralStoreFactory, read: str
    ) -> None:
        """Clause 18's default half (§2), exercised past the default.

        An implementation defaulting to unbounded satisfies every explicit-limit
        case while breaking the guarantee that keeps an unbounded read of a Tier 1
        store from being what a caller gets by saying nothing.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, queue_limit=1000)
        for index in range(60):
            await _admit(store, f"d{index:03d}", _proposal(f"question {index}"))
            clock.advance(_HOUR)
            if read == "interrupted":
                await _claim(store, f"d{index:03d}")

        page = await getattr(store, read)()

        assert len(page) < 60
        assert _ids(page) == sorted(_ids(page))

    # --- clause 8: the successor exemption ----------------------------------

    async def test_a_successor_is_admitted_past_a_full_queue_and_links_its_parent(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 8, the admitting half (§2).

        Without the exemption a full queue strands a claimed answer: a re-deferral
        would have nowhere to go, and the newly-surfaced assertion would never be
        asked about — the exact drop ADR-0078 exists to end.
        """
        store = _build(factory, queue_limit=1)
        await _admit(store, "parent")
        token = await _claim(store, "parent")
        # The queue is at its cap for anything without an exemption.
        await _admit(store, "filler", _proposal("a filler question"))
        refused = await store.defer(
            deferral_id="ordinary", proposal=_proposal("an ordinary question"), decision=_ASK
        )
        assert refused.outcome is DeferralAdmissionOutcome.REFUSED
        assert refused.deferral is None

        admission = await store.defer(
            deferral_id="child",
            proposal=_proposal("parent", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="parent",
            successor_to_claim=token,
        )

        assert admission.outcome is DeferralAdmissionOutcome.ADMITTED
        assert admission.deferral is not None
        assert admission.deferral.predecessor_id == "parent"
        parent = await store.get("parent")
        assert parent is not None
        assert parent.successor_id == "child"
        assert parent.state is DeferralState.APPLYING

    async def test_a_suppressed_successor_still_links_its_parent(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 8's suppression case (§2), which a suite never reaches unless it
        seeds the collision first.

        Without the stamp the parent has no successor to name,
        ``resolve(REDEFERRED)`` has nothing to check against, and a legitimately
        claimed answer strands ``APPLYING`` forever — a duplicate question the queue
        was right to refuse, punished by stranding the answer that raised it. The
        link is **one-way** on this path: the existing question has its own origin,
        and rewriting its ``predecessor_id`` would claim the user's answer created a
        question that predates it.
        """
        store = _build(factory)
        successor_proposal = _proposal("the successor question", conflicts=("c-new",))
        already_open = await _admit(store, "already-open", successor_proposal)
        await _admit(store, "parent", _proposal("the parent question"))
        token = await _claim(store, "parent")

        admission = await store.defer(
            deferral_id="child",
            proposal=successor_proposal,
            decision=_ASK,
            predecessor_id="parent",
            successor_to_claim=token,
        )

        assert admission.outcome is DeferralAdmissionOutcome.SUPPRESSED
        assert admission.deferral is not None
        assert admission.deferral.id == "already-open"
        parent = await store.get("parent")
        assert parent is not None
        assert parent.successor_id == "already-open"
        # One-way: the pre-existing question keeps its own (absent) origin.
        assert already_open.predecessor_id is None
        standing = await store.get("already-open")
        assert standing is not None
        assert standing.predecessor_id is None
        assert await store.get("child") is None
        assert await store.resolve(
            "parent",
            claim_id=token,
            state=DeferralState.REDEFERRED,
            successor_id="already-open",
        )

    async def test_a_successor_whose_parent_is_gone_is_admitted_as_an_ordinary_question(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 8's deleted-parent case (§2), driven **together** with the next.

        The two differ only in whether the parent exists, and a suite that drives
        one and calls it "the unknown-token case" certifies the rule that strands a
        live answer. Here the parent was destroyed by the user mid-apply, so there
        is no claimed answer to strand and no bookkeeping to record: the successor is
        an ordinary question, subject to the cap, linked to nothing, and nothing
        raises.
        """
        store = _build(factory, queue_limit=1)
        await _admit(store, "parent")
        token = await _claim(store, "parent")
        assert await store.delete("parent")

        admission = await store.defer(
            deferral_id="child",
            proposal=_proposal("the successor question", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="parent",
            successor_to_claim=token,
        )

        assert admission.outcome is DeferralAdmissionOutcome.ADMITTED
        assert admission.deferral is not None
        # Subject to the cap: with the parent gone there is no exemption to spend,
        # so the next ordinary question is refused at the same ceiling.
        refused = await store.defer(
            deferral_id="another", proposal=_proposal("an unrelated question"), decision=_ASK
        )
        assert refused.outcome is DeferralAdmissionOutcome.REFUSED

    async def test_an_unmatched_token_against_a_live_parent_raises(
        self, factory: DeferralStoreFactory
    ) -> None:
        """Clause 8's live-parent refusal (§2). The case that must not be folded
        into the one above.

        The parent is alive and waiting: admitting an unlinked successor would leave
        it with no ``successor_id`` to name, and its ``resolve(REDEFERRED)`` would
        then fail forever. A live parent with a bad token is a caller fault, and a
        fault that strands a real answer is exactly the kind to surface rather than
        absorb.
        """
        store = _build(factory)
        await _admit(store, "parent")
        await _claim(store, "parent")

        with pytest.raises(DeferralStoreError):
            await store.defer(
                deferral_id="child",
                proposal=_proposal("the successor question", conflicts=("c-new",)),
                decision=_ASK,
                predecessor_id="parent",
                successor_to_claim="not-the-token",
            )

        assert await store.get("child") is None
        parent = await store.get("parent")
        assert parent is not None
        assert parent.successor_id is None

    async def test_a_resolved_parent_refuses_the_exemption(
        self, factory: DeferralStoreFactory
    ) -> None:
        store = _build(factory)
        await _admit(store, "parent")
        token = await _claim(store, "parent")
        assert await store.resolve(
            "parent", claim_id=token, state=DeferralState.ACCEPTED, record_id="written-1"
        )

        with pytest.raises(DeferralStoreError):
            await store.defer(
                deferral_id="child",
                proposal=_proposal("the successor question", conflicts=("c-new",)),
                decision=_ASK,
                predecessor_id="parent",
                successor_to_claim=token,
            )

        assert await store.get("child") is None

    async def test_a_parent_that_already_names_a_successor_refuses_a_second(
        self, factory: DeferralStoreFactory
    ) -> None:
        """One successor per claim: what bounds the exemption.

        Without it, anything holding the token could admit an unbounded number of
        questions past a full queue and overwrite the parent's link each time.
        """
        store = _build(factory)
        await _admit(store, "parent")
        token = await _claim(store, "parent")
        await store.defer(
            deferral_id="child",
            proposal=_proposal("the first successor", conflicts=("c-new",)),
            decision=_ASK,
            predecessor_id="parent",
            successor_to_claim=token,
        )

        with pytest.raises(DeferralStoreError):
            await store.defer(
                deferral_id="second-child",
                proposal=_proposal("a second successor", conflicts=("c-newer",)),
                decision=_ASK,
                predecessor_id="parent",
                successor_to_claim=token,
            )

        assert await store.get("second-child") is None
        parent = await store.get("parent")
        assert parent is not None
        assert parent.successor_id == "child"

    @pytest.mark.parametrize(
        ("predecessor_id", "token"),
        [
            pytest.param("parent", None, id="a-parent-with-no-token"),
            pytest.param(None, "a-token", id="a-token-with-no-parent"),
        ],
    )
    async def test_the_exemption_arguments_must_agree_about_being_present(
        self, factory: DeferralStoreFactory, predecessor_id: str | None, token: str | None
    ) -> None:
        """A malformed call, refused rather than half-honoured (§2)."""
        store = _build(factory)
        await _admit(store, "parent")
        await _claim(store, "parent")

        with pytest.raises(DeferralStoreError):
            await store.defer(
                deferral_id="child",
                proposal=_proposal("the successor question", conflicts=("c-new",)),
                decision=_ASK,
                predecessor_id=predecessor_id,
                successor_to_claim=token,
            )

        assert await store.get("child") is None

    # --- the cap ------------------------------------------------------------

    async def test_the_cap_refuses_the_new_question_and_keeps_the_old_ones(
        self, factory: DeferralStoreFactory
    ) -> None:
        """§7's cap. Eviction is rejected: dropping the oldest question to make room
        for a newer one is the silent vanishing this contract exists to end,
        performed by the mechanism meant to prevent it.

        Lapsed and resolved rows awaiting a sweep do not count against it, so a
        queue cannot be held shut by questions nobody can answer.
        """
        clock = MovableClock()
        store = _build(factory, now=clock, retention=_DAY, queue_limit=2)
        await _admit(store, "d1")
        clock.advance(_HOUR)
        await _admit(store, "d2", _proposal("a second question"))

        refused = await store.defer(
            deferral_id="d3", proposal=_proposal("a third question"), decision=_ASK
        )

        assert refused.outcome is DeferralAdmissionOutcome.REFUSED
        assert refused.deferral is None
        assert _ids(await store.pending()) == ["d1", "d2"]
        assert await store.get("d3") is None

        assert await store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)
        room = await store.defer(
            deferral_id="d3", proposal=_proposal("a third question"), decision=_ASK
        )
        assert room.outcome is DeferralAdmissionOutcome.ADMITTED

    # --- clauses 2, 3, 5: the compare-and-sets, as races -------------------

    async def test_two_concurrent_claims_admit_exactly_one(self) -> None:
        """Clause 2 (§2, §9). This is the whole guarantee, and asserting only that a
        single ``claim`` succeeds tests nothing about it.

        Without it two concurrent answers both read a ``PENDING`` deferral, both
        ingest, and **both write** — with only one winning the terminal
        compare-and-set while the loser's memory mutation stands. A duplicate
        correction with no crash anywhere, produced by ordinary concurrent use.
        """
        clock = MovableClock()
        async with self.store_suspended_mid_write(now=clock) as harness:
            store = harness.store
            await _admit(store, "d1")
            suspended = harness.arm("claim")
            first = asyncio.ensure_future(store.claim("d1"))
            await suspended.reached()
            second = asyncio.ensure_future(store.claim("d1"))
            await settle()
            suspended.release()
            outcomes = [await first, await second]

        assert not harness.log.overlapped
        assert sum(outcome is not None for outcome in outcomes) == 1

    async def test_two_concurrent_unclaimed_rejections_resolve_once(self) -> None:
        """Clause 3 (§2). The one compare-and-set the accept-path clauses never
        exercise, because they all go through ``claim`` first.

        A read-then-write store lets both rejections succeed and reports the question
        answered twice.
        """
        clock = MovableClock()
        async with self.store_suspended_mid_write(now=clock) as harness:
            store = harness.store
            await _admit(store, "d1")
            suspended = harness.arm("resolve")
            first = asyncio.ensure_future(
                store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)
            )
            await suspended.reached()
            second = asyncio.ensure_future(
                store.resolve("d1", claim_id=None, state=DeferralState.REJECTED)
            )
            await settle()
            suspended.release()
            outcomes = [await first, await second]
            held = await store.get("d1")

        assert not harness.log.overlapped
        assert sorted(outcomes) == [False, True]
        assert held is not None
        assert held.state is DeferralState.REJECTED

    async def test_two_concurrent_same_key_admissions_leave_one_row(self) -> None:
        """Clause 5, the key half (§2). A sequential test passes against a
        read-then-insert implementation and certifies nothing.

        A background producer is precisely a concurrent producer, so this is a live
        condition rather than a theoretical one.
        """
        clock = MovableClock()
        proposal = _proposal("one question")
        async with self.store_suspended_mid_write(now=clock) as harness:
            store = harness.store
            suspended = harness.arm("defer")
            first = asyncio.ensure_future(
                store.defer(deferral_id="a", proposal=proposal, decision=_ASK)
            )
            await suspended.reached()
            second = asyncio.ensure_future(
                store.defer(deferral_id="b", proposal=proposal, decision=_ASK)
            )
            await settle()
            suspended.release()
            outcomes = [await first, await second]
            rows = await store.export()

        assert not harness.log.overlapped
        assert sorted(admission.outcome.value for admission in outcomes) == [
            DeferralAdmissionOutcome.ADMITTED.value,
            DeferralAdmissionOutcome.SUPPRESSED.value,
        ]
        assert len(rows) == 1

    async def test_two_concurrent_admissions_at_the_cap_admit_exactly_one(self) -> None:
        """Clause 5, the cap half (§2).

        Left non-atomic, two concurrent producers each see room at
        capacity-minus-one and the cap is exceeded.
        """
        clock = MovableClock()
        async with self.store_suspended_mid_write(now=clock, queue_limit=1) as harness:
            store = harness.store
            suspended = harness.arm("defer")
            first = asyncio.ensure_future(
                store.defer(deferral_id="a", proposal=_proposal("one"), decision=_ASK)
            )
            await suspended.reached()
            second = asyncio.ensure_future(
                store.defer(deferral_id="b", proposal=_proposal("two"), decision=_ASK)
            )
            await settle()
            suspended.release()
            outcomes = [await first, await second]
            rows = await store.export()

        assert not harness.log.overlapped
        assert sorted(admission.outcome.value for admission in outcomes) == [
            DeferralAdmissionOutcome.ADMITTED.value,
            DeferralAdmissionOutcome.REFUSED.value,
        ]
        assert len(rows) == 1

    # --- clause 4: the no-resurrection product ------------------------------

    @pytest.mark.parametrize(("destruction", "kind"), _CONTINUATION_FIRST)
    async def test_a_destruction_landing_after_a_continuation_leaves_the_right_row(
        self, destruction: str, kind: str
    ) -> None:
        """Clause 4, the continuation-wins half (§2), across the full product.

        Stated as a product rather than a list because a rule quantified over two
        classes and tested on one pair is how this clause has already drifted twice.
        The axes are not interchangeable: the three destructions differ in scope and
        in who triggers them, ``claim`` recreates a row as ``APPLYING`` where
        ``resolve`` recreates it terminal, and ``purge`` is the only one driven by a
        clock rather than a caller.

        **The assertion splits by winner, and only ``purge`` needs the split.**
        ``delete`` and ``clear`` are unconditional, so the row ends absent whichever
        way the race fell. ``purge`` is conditional on state, so a uniform "absent"
        would contradict its own rule: an ``APPLYING`` row may never be removed at
        any age, and a terminal one is retained until ``answered_at + retention``.
        Asserting the conditional cases is worth as much as asserting the
        destructive ones — a purge that swept an ``APPLYING`` row would pass a
        uniformly-absent matrix and break the guard on the record of an answer.
        """
        clock = MovableClock()
        continuation = _CONTINUATIONS[kind]()
        async with self.store_suspended_mid_write(now=clock, retention=_DAY) as harness:
            store = harness.store
            admitted = await _admit(store, "d1")
            assert admitted.expires_at is not None
            # Halfway through the lifetime, so the continuation's own clock reading
            # is inside the deadline while `purge`'s is past it — and the terminal
            # row's retention still runs well beyond.
            clock.set(_NOW + _DAY / 2)
            await continuation.prepare(store, "d1")

            suspended = harness.arm(continuation.name)
            first = continuation.run(store, "d1")
            await suspended.reached()
            clock.set(admitted.expires_at + _TICK)
            second = asyncio.ensure_future(_destroy(store, destruction))
            await settle()
            suspended.release()
            await first
            await second
            survivor = await store.get("d1")
            exported = await store.export()

        assert not harness.log.overlapped
        if destruction == "purge":
            # A `claim` left it `APPLYING`, which no sweep may take at any age; a
            # `resolve` left it terminal and retained until `answered_at + retention`.
            # In both, the correct outcome is that the row survives.
            assert survivor is not None
            assert _ids(exported) == ["d1"]
        else:
            assert survivor is None
            assert exported == []

    @pytest.mark.parametrize(("destruction", "kind"), _DESTRUCTION_FIRST)
    async def test_a_continuation_landing_after_a_destruction_finds_nothing(
        self, destruction: str, kind: str
    ) -> None:
        """Clause 4, the destruction-wins half (§2). The row stays **gone**.

        "Atomic with its own read" bounds a continuation against another
        continuation and says nothing about a destruction landing between that read
        and its write, so a read-then-write backend would put its stale row back —
        **resurrecting Tier 1 content the user destroyed**, through the call whose
        only job is bookkeeping.

        ``purge`` against a claimed answer is deliberately absent from this half
        rather than overlooked: a purge may never take an ``APPLYING`` row, so there
        is no ordering in which it wins one, which is the rule the other half
        asserts from the inside.
        """
        clock = MovableClock()
        continuation = _CONTINUATIONS[kind]()
        async with self.store_suspended_mid_write(now=clock, retention=_DAY) as harness:
            store = harness.store
            admitted = await _admit(store, "d1")
            assert admitted.expires_at is not None
            await continuation.prepare(store, "d1")
            if destruction == "purge":
                clock.set(admitted.expires_at + _TICK)

            suspended = harness.arm(destruction)
            first = asyncio.ensure_future(_destroy(store, destruction))
            await suspended.reached()
            second = continuation.run(store, "d1")
            await settle()
            suspended.release()
            await first
            outcome = await second
            survivor = await store.get("d1")
            exported = await store.export()

        assert not harness.log.overlapped
        assert outcome in (None, False)
        assert survivor is None
        assert exported == []

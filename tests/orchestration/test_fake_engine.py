"""The canonical FakeAssistantEngine passes the shared AssistantEngine suite.

This is what lets a client lane trust ``ai_assistant.testing.FakeAssistantEngine``
as a stand-in for the engine: it is held to the same contract as the concrete
:class:`~ai_assistant.orchestration.engine.Engine` (``tests/orchestration/
test_engine_contract.py``).

**It is also the pair ADR-0084 §4's size clause needs.** That clause says the
limit is enforced by "*every* implementation", with the conformance suite as what
holds them to it — and until this fake exists there is only one implementation, so
the clause has nothing to bind. ADR-0087 §6 makes exactly that argument for
ratifying the canonical encoding before this change rather than with the hub.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from approvals_panel_contract import APPROVALS_AT, APPROVALS_LIMIT, ApprovalsPanelSubject
from assistant_engine_contract import (
    _BELIEF_LIMIT,
    _DECISION_LIMIT,
    _INVOCATION_LIMIT,
    _NOT_CANONICAL,
    _OVERFULL_DECISIONS,
    _OVERFULL_GRANTS,
    _OVERFULL_READS,
    _SOURCE,
    _SPEND_LIMIT,
    _TINY_LIMIT,
    _UNHELD_SOURCE,
    _UNWRITABLE_LOCATION,
    _UNWRITABLE_SOURCE,
    SPEAKABLE_NOTIFICATION,
    SPEND_ZERO_CEILING,
    UNSPEAKABLE_NOTIFICATION,
    AssistantEngineContract,
    BeliefSubject,
    ConnectionSubject,
    DecisionSubject,
    DerivedPlacementSubject,
    InvocationSubject,
    ReadSubject,
    SpendSubject,
    backwards_clock,
    fake_belief_holder,
    near_ceiling_limit,
    overfull_invocation_rows,
    page_after_mutating_the_filter,
    seeded_invocation_trail,
    seeded_read_trail,
    seeded_spend_ledger,
    seeded_trail,
)
from chat_surface_contract import (
    CHAT_LIMIT,
    CHAT_SURFACE_AT,
    ChatReaderSubject,
    ChatSurfaceSubject,
)
from episode_inspection_contract import (
    INSPECTION_AT,
    INSPECTION_LIMIT,
    EpisodeInspectionSubject,
)
from pending_candidates_contract import PENDING_AT, PENDING_LIMIT, PendingCandidatesSubject
from person_model_contract import (
    PERSON_BUDGET,
    PERSON_LIMIT,
    PersonModelSubject,
    person_model_stores,
)
from story_surface_contract import STORY_LIMIT, STORY_SURFACE_AT, StorySurfaceSubject

from ai_assistant.core.errors import (
    ConversationStoreError,
    OversizedValueError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEnding,
    Attestation,
    BeliefBand,
    BeliefSummary,
    BoundAccount,
    ChatDevice,
    Conversation,
    ConversationState,
    ConversationSummary,
    DestinationProtocol,
    DeviceAccess,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    EpisodicMemory,
    GrantScope,
    MemoryKind,
    MemoryStanding,
    MemoryWrite,
    MessageAuthor,
    MessageReceipt,
    NewMessage,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingStatus,
    SpanCoverage,
    TranscriptMessage,
    UserMessage,
)
from ai_assistant.orchestration.chat import COULDNT_FINISH
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeMemoryStore,
    FakePlanStore,
)

#: The per-turn budget the two ``converse`` entries take. A fixed figure rather than a
#: clock reading: nothing in the cases that pass it turns on the duration.
_BUDGET = timedelta(seconds=30)

#: What reported an attested proposal, on the source's own clock (ADR-0092 §3). A
#: fixed instant rather than a clock reading: nothing here turns on time.
_REPORTED = Attestation(
    reported_by="work-calendar", reported_at=datetime(2026, 3, 2, 8, 30, tzinfo=UTC)
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import Belief, Identifier


def _binding() -> EgressBinding:
    """One whole egress binding, for a park the shared suite's ADR-0178 clauses reach.

    A destination-bearing occurrence and a description-only one, so the derived
    set has a recipient member rather than falling back to the account: an
    account-only set would satisfy the correspondence clause while exercising the
    arm that is the same on both sides.
    """
    return EgressBinding(
        spans=(
            EgressSpan(
                argument="body",
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=5,
            ),
            EgressSpan(
                argument="to",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=17,
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="Alice@Example.ORG",
                    canonical="alice@example.org",
                ),
            ),
        ),
        account=BoundAccount(identity="work@example.com", reference="conn-0001"),
        transport_endpoint="test://endpoint/one",
        planned_with_external_content=False,
        coverage=SpanCoverage.NOT_COVERED,
    )


def _pending() -> PendingCandidatesSubject:
    """A fake at the pending candidates' bound, its stores injected and clocked there."""
    memory = FakeMemoryStore(now=lambda: PENDING_AT)
    plans = FakePlanStore(now=lambda: PENDING_AT)
    built = FakeAssistantEngine(max_payload_bytes=PENDING_LIMIT)
    built.episode_memory = memory
    built.plan_store = plans
    return PendingCandidatesSubject(engine=built, memory=memory, plans=plans)


def _approvals() -> ApprovalsPanelSubject:
    """A fake at the approvals panel's bound, its stores injected, clocked there."""
    built = FakeAssistantEngine(max_payload_bytes=APPROVALS_LIMIT)
    built.plan_store = FakePlanStore(now=lambda: APPROVALS_AT)
    built.episode_memory = FakeMemoryStore(now=lambda: APPROVALS_AT)
    built.approval_clock = lambda: APPROVALS_AT
    return ApprovalsPanelSubject(engine=built, plans=built.plan_store, memory=built.episode_memory)


def _person_model(*, wired: bool) -> PersonModelSubject:
    """A fake at the person model's bound, its two stores injected; wired or not."""
    people, memory = person_model_stores()
    built = FakeAssistantEngine(max_payload_bytes=PERSON_LIMIT)
    built.episode_memory = memory
    if wired:
        built.person_blocks = PersonBlocks(store=people, memory=memory, budget_chars=PERSON_BUDGET)
    return PersonModelSubject(engine=built, people=people, memory=memory)


class TestFakeAssistantEngineContract(AssistantEngineContract):
    """The canonical fake, held to the shared contract."""

    @pytest.fixture
    def chat_surface(self) -> ChatSurfaceSubject:
        """The canonical fake over an injected memory store, at the chat bound, not answering."""
        memory = FakeMemoryStore(now=lambda: CHAT_SURFACE_AT)
        built = FakeAssistantEngine(max_payload_bytes=CHAT_LIMIT, chat_reader=False)
        built.episode_memory = memory
        return ChatSurfaceSubject(engine=built, memory=memory)

    @pytest.fixture
    def chat_reader_surface(self) -> ChatReaderSubject:
        """The canonical fake answering, over an injected memory store, at the chat bound."""
        memory = FakeMemoryStore(now=lambda: CHAT_SURFACE_AT)
        built = FakeAssistantEngine(max_payload_bytes=CHAT_LIMIT)
        built.episode_memory = memory
        return ChatReaderSubject(engine=built, memory=memory, chat=built.chat)

    @pytest.fixture
    def story_surface(self) -> StorySurfaceSubject:
        """The canonical fake over the same injected memory store and bound."""
        memory = FakeMemoryStore(now=lambda: STORY_SURFACE_AT)
        built = FakeAssistantEngine(max_payload_bytes=STORY_LIMIT)
        built.episode_memory = memory
        return StorySurfaceSubject(engine=built, memory=memory, stories=built.story_store)

    @pytest.fixture
    def episode_inspection(self) -> EpisodeInspectionSubject:
        """The canonical fake with the same injected inspection store and bound."""
        memory = FakeMemoryStore(now=lambda: INSPECTION_AT)
        built = FakeAssistantEngine(max_payload_bytes=INSPECTION_LIMIT)
        built.episode_memory = memory
        return EpisodeInspectionSubject(engine=built, memory=memory)

    @pytest.fixture
    def pending_candidates_subject(self) -> PendingCandidatesSubject:
        """The canonical fake, over injected stores, at the bound."""
        return _pending()

    @pytest.fixture
    def person_model_subject(self) -> PersonModelSubject:
        """The canonical fake with a person-model store wired, over injected stores."""
        return _person_model(wired=True)

    @pytest.fixture
    def person_model_off(self) -> PersonModelSubject:
        """The same fake with no store, as a hub with the switch off."""
        return _person_model(wired=False)

    @pytest.fixture
    def approvals_subject(self) -> ApprovalsPanelSubject:
        """The canonical fake over injected stores, clocked at the panel's instant."""
        return _approvals()

    @pytest.fixture
    def engine(self) -> AssistantEngine:
        """One fake engine at the ordinary contract limit."""
        return FakeAssistantEngine()

    @pytest.fixture
    def tiny_engine(self) -> AssistantEngine:
        """The same implementation, with the limit small enough to reach."""
        return FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)

    @pytest.fixture
    def beliefs(self) -> BeliefSubject:
        """One fake engine, holding beliefs through its own ``hold``."""
        built = FakeAssistantEngine()
        return BeliefSubject(engine=built, hold=fake_belief_holder(built))

    @pytest.fixture
    def tiny_beliefs(self) -> BeliefSubject:
        """:meth:`beliefs`' subject at the limit small enough to reach."""
        built = FakeAssistantEngine(max_payload_bytes=_BELIEF_LIMIT)
        return BeliefSubject(engine=built, hold=fake_belief_holder(built))

    @pytest.fixture
    async def speaking_engine(self) -> AssistantEngine:
        """The fake holding one placed candidate, over its own outbox.

        ``spoken_formats`` defaults to every member, which is what the suite requires
        of this subject, so nothing is narrowed here.
        """
        engine = FakeAssistantEngine()
        await engine.notification_outbox.offer(SPEAKABLE_NOTIFICATION)
        return engine

    @pytest.fixture
    async def withholding_engine(self) -> AssistantEngine:
        """The fake holding one candidate ADR-0206 §3 does not place."""
        engine = FakeAssistantEngine()
        await engine.notification_outbox.offer(UNSPEAKABLE_NOTIFICATION)
        return engine

    @pytest.fixture
    async def near_ceiling_engine(self) -> AssistantEngine:
        """The fake at the limit only a rendering bursts."""
        engine = FakeAssistantEngine(max_payload_bytes=near_ceiling_limit(SPEAKABLE_NOTIFICATION))
        await engine.notification_outbox.offer(SPEAKABLE_NOTIFICATION)
        return engine

    @pytest.fixture
    def connections(self) -> ConnectionSubject:
        """The fake and the provisioner it already holds — the same object, twice.

        This binding is where the pairing is least ceremonious and most revealing:
        ``FakeAssistantEngine.connections`` **is** the canonical provisioner fake,
        so a clause below is judged against exactly the object the other two
        bindings reach through a seam and a socket.
        """
        engine = FakeAssistantEngine()
        return ConnectionSubject(engine=engine, provisioner=engine.connections)

    @pytest.fixture
    def tiny_connections(self) -> ConnectionSubject:
        """The same fake at the limit the suite can reach."""
        engine = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        return ConnectionSubject(engine=engine, provisioner=engine.connections)

    @pytest.fixture
    def granting_engine(self) -> AssistantEngine:
        """One fake engine holding a single grantable source with a location."""
        engine = FakeAssistantEngine()
        engine.hold_source(_SOURCE, location="/srv/calendar.ics")
        return engine

    @pytest.fixture
    def defective_source_engine(self) -> AssistantEngine:
        """The same fake, holding one grantable source and two that are not."""
        engine = FakeAssistantEngine()
        engine.hold_source(_SOURCE, location="/srv/calendar.ics")
        engine.hold_source(_UNWRITABLE_SOURCE, location=_UNWRITABLE_LOCATION)
        engine.hold_source(_NOT_CANONICAL, location="/srv/mail")
        return engine

    @pytest.fixture
    def back_dated_engine(self) -> AssistantEngine:
        """The same fake, with a clock that steps **backwards** on every reading."""
        engine = FakeAssistantEngine()
        engine.hold_source(_SOURCE, location="/srv/calendar.ics")
        engine.grant_clock = backwards_clock()
        return engine

    @pytest.fixture
    def disagreeing_engine(self) -> AssistantEngine:
        """One grantable-and-ungranted source, one live grant on a source not held.

        ``hold_grant`` applies no admission check, which is what makes the state
        reachable at all: nothing on the surface unholds a reader, so a grant on a
        source the hub no longer builds has to be seeded (ADR-0139 §8).
        """
        engine = FakeAssistantEngine()
        engine.hold_source(_SOURCE, location="/srv/calendar.ics")
        engine.hold_grant(_UNHELD_SOURCE, scope=(GrantScope.INGEST,))
        return engine

    @pytest.fixture
    def overfull_granting_engine(self) -> AssistantEngine:
        """A tiny-limit fake whose live set does not fit that limit."""
        engine = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        for index in range(_OVERFULL_GRANTS):
            engine.hold_grant(f"source-{index}", scope=(GrantScope.NOTIFY,))
        return engine

    @pytest.fixture
    def derived_placement(self) -> DerivedPlacementSubject:
        """One fake engine holding a belief the derivation placed (ADR-0217 §3).

        Seeded through ``hold``'s ``placement`` knob, which exists for exactly this: no
        call on the promoted surface writes a ``DERIVED`` placement, so a consumer
        testing an act against the refusal has to be able to arrange one.
        """
        engine = FakeAssistantEngine()
        held = engine.hold(
            "rec-derived",
            content="the user's consultant said the merger is off",
            placement=Placement(
                reach=PlacementReach.OWNER,
                set_by=PlacementSetter.DERIVED,
                set_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            ),
        )
        return DerivedPlacementSubject(engine=engine, record_id=held.id)

    @pytest.fixture
    async def decisions(self) -> DecisionSubject:
        """The fake over a seeded trail — the same object the suite reads as its control.

        ``trail`` is a plain attribute for the reason every other scriptable
        behaviour here is one: a test changes one thing without restating the rest,
        and the canonical fake's default remains a conforming ``FakeAuditTrail``.
        """
        trail = await seeded_trail()
        engine = FakeAssistantEngine()
        engine.trail = trail
        return DecisionSubject(engine=engine, trail=trail)

    @pytest.fixture
    async def unordered_decisions(self) -> DecisionSubject:
        """The same fake over a trail whose ``export`` exercises the contract's freedom.

        **This binding is why the fake holds an ``AuditTrail`` rather than a list of
        decisions.** A fake that kept rows in a list of its own could only ever hand
        back what its own sort produced, so the case separating an engine which
        sorts from one which relays would pass while asserting nothing.
        """
        trail = await seeded_trail(ordered_export=False)
        engine = FakeAssistantEngine()
        engine.trail = trail
        return DecisionSubject(engine=engine, trail=trail)

    @pytest.fixture
    async def overfull_decisions(self) -> AssistantEngine:
        """A fake at the decision limit whose whole trail does not fit it."""
        engine = FakeAssistantEngine(max_payload_bytes=_DECISION_LIMIT)
        engine.trail = await seeded_trail(
            rows=tuple((f"d-{index}", index) for index in range(_OVERFULL_DECISIONS))
        )
        return engine

    @pytest.fixture
    async def reads(self) -> ReadSubject:
        """The fake over a seeded read trail — the object the suite reads as its control.

        ``reads`` is a plain attribute on :attr:`decisions`' terms. **Why the fake
        holds a whole ``SourceReadTrail`` is a different argument here**, and it
        points the other way: on the audit side a bare list would have been unable
        to exercise a freedom the contract grants, while here it would fail to
        exercise an obligation the contract *states* — the store promises recording
        order, and a list could only reproduce it by accident of append order rather
        than by a contract this suite can hold the surface to.
        """
        trail = await seeded_read_trail()
        engine = FakeAssistantEngine()
        engine.reads = trail
        return ReadSubject(engine=engine, trail=trail)

    @pytest.fixture
    async def spending(self) -> SpendSubject:
        """The fake over a ledger carrying a zero ceiling on both periods.

        ``trail`` and ``spend`` are set together, as the composition root wires one
        object: a fake whose two attributes were different objects would state
        totals over rows the decision reads cannot see.
        """
        ledger = await seeded_spend_ledger(
            day_ceiling=SPEND_ZERO_CEILING, month_ceiling=SPEND_ZERO_CEILING
        )
        engine = FakeAssistantEngine()
        engine.trail = ledger
        engine.spend = ledger
        return SpendSubject(engine=engine, ledger=ledger)

    @pytest.fixture
    async def unconfigured_spending(self) -> SpendSubject:
        """The fake over a ledger with no currency configured."""
        ledger = await seeded_spend_ledger(currency=None)
        engine = FakeAssistantEngine()
        engine.trail = ledger
        engine.spend = ledger
        return SpendSubject(engine=engine, ledger=ledger)

    @pytest.fixture
    async def indeterminate_spending(self) -> SpendSubject:
        """The fake over a ledger holding an open claim, day ceiling only."""
        ledger = await seeded_spend_ledger(day_ceiling=Decimal("10"), open_claim=True)
        engine = FakeAssistantEngine()
        engine.trail = ledger
        engine.spend = ledger
        return SpendSubject(engine=engine, ledger=ledger)

    @pytest.fixture
    async def overfull_spending(self) -> AssistantEngine:
        """The fake at a limit the pair of totals cannot fit inside."""
        ledger = await seeded_spend_ledger()
        engine = FakeAssistantEngine(max_payload_bytes=_SPEND_LIMIT)
        engine.trail = ledger
        engine.spend = ledger
        return engine

    @pytest.fixture
    async def invocations(self) -> InvocationSubject:
        """The fake over a seeded invocation trail — the object the suite reads as control.

        ``trail`` is a plain attribute on :attr:`decisions`' terms, and it is the
        **same** attribute: ADR-0192 §2 puts both row kinds in one store, so a fake
        holding two would be modelling a split the contract does not have.
        """
        trail = await seeded_invocation_trail()
        engine = FakeAssistantEngine()
        engine.trail = trail
        return InvocationSubject(engine=engine, trail=trail)

    @pytest.fixture
    async def overfull_invocations(self) -> AssistantEngine:
        """A fake at the invocation limit whose whole trail does not fit it."""
        engine = FakeAssistantEngine(max_payload_bytes=_INVOCATION_LIMIT)
        engine.trail = await seeded_invocation_trail(rows=overfull_invocation_rows())
        return engine

    @pytest.fixture
    async def overfull_reads(self) -> AssistantEngine:
        """A fake at the tiny limit whose whole read trail does not fit it."""
        engine = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        engine.reads = await seeded_read_trail(
            rows=tuple((f"r-{index}", index) for index in range(_OVERFULL_READS))
        )
        return engine


# --- what the fake offers beyond the contract ------------------------------
# Its own tests, not the suite's: a canonical fake has to be *usable* as well as
# conformant, and these pin the setters a consumer's test will reach for.


async def test_a_held_belief_is_listed_and_readable() -> None:
    """``hold`` seeds the inspection surface without going through ``learn``."""
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the office is in Boston")
    page = await engine.beliefs()
    assert [summary.id for summary in page] == ["rec-1"]
    detail = await engine.belief("rec-1")
    assert detail is not None
    assert detail.content == "the office is in Boston"


async def test_the_fake_projects_what_core_s_projection_computes() -> None:
    """ADR-0328 §15:1: the fake's views are ``core``'s, so they agree with the engine's.

    A held memory rests on one support whose origin ranks at the band asked for, and
    every computed value is read off it rather than set: the standing, whether it
    rests on outside content, and the legacy mark.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-said", content="a")
    engine.hold("rec-sourced", content="b", band=BeliefBand.ATTESTED)
    engine.hold("rec-outside", content="c", band=BeliefBand.DERIVED, rests_on_outside_content=True)
    engine.hold("rec-old", content="d", legacy=True)

    listed = {summary.id: summary for summary in await engine.beliefs()}
    assert listed["rec-said"].standing is MemoryStanding.SAID
    assert listed["rec-sourced"].standing is MemoryStanding.SOURCE
    assert listed["rec-sourced"].rests_on_outside_content is True
    assert listed["rec-outside"].standing is MemoryStanding.INFERENCE
    assert listed["rec-outside"].rests_on_outside_content is True
    assert listed["rec-old"].legacy is True
    for record_id, summary in listed.items():
        detail = await engine.belief(record_id)
        assert detail is not None
        assert summary == BeliefSummary.model_validate(detail.model_dump(exclude={"supports"}))


async def test_the_band_filter_selects_by_band() -> None:
    """A memory is listed when its band is selected (ADR-0073 §2)."""
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="a", band=BeliefBand.ASSERTED)
    engine.hold("rec-2", content="b", band=BeliefBand.DERIVED)
    listed = await engine.beliefs(bands=[BeliefBand.ATTESTED])
    assert listed == ()
    listed = await engine.beliefs(bands=[BeliefBand.DERIVED])
    assert [summary.id for summary in listed] == ["rec-2"]


# --- the suite discriminates ------------------------------------------------
# Each clause below is asserted by watching a deliberately non-conforming subject
# *fail* the very scenario the contract runs. A conformance test nobody has seen
# fail is a test that agrees with whatever it was written against; these are what
# make the six clauses evidence rather than description.


class _LazyFilterEngine(FakeAssistantEngine):
    """An engine that reads its filter *after* suspending — the §3d violation."""

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """Suspend first, then read ``bands`` — so a mid-call mutation is visible."""
        await asyncio.sleep(0)
        return await super().beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


async def test_the_materialisation_clause_catches_a_lazy_filter() -> None:
    """The scenario the contract runs really does separate the two behaviours."""
    engine = _LazyFilterEngine()
    engine.hold("rec-1", content="the office is in Boston")
    page, control = await page_after_mutating_the_filter(engine)
    assert control != ()
    assert page == ()  # the emptied list was read after the suspension


class _UnlimitedEngine(FakeAssistantEngine):
    """An engine that measures its arguments and never its results — the §8c gap."""

    def _checked[T](self, result: T, method: str) -> T:
        """Skip the result check the contract requires of every implementation."""
        return result


async def test_the_size_clause_catches_an_unchecked_result() -> None:
    """An implementation that measured only its arguments would slip through §8c.

    ADR-0084 §4 insists on **both** directions precisely so a client is never
    silently less capable than the engine it stands in for; this is the half that
    would otherwise go unnoticed, because an oversized result is only visible to
    whoever tried to send it.

    **This is the scenario the suite runs**, down to the listing call whose request
    payload is twelve bytes — so what it demonstrates is that the suite's case is
    load-bearing rather than incidentally passing. An earlier draft asserted the
    same clause with an oversized *event*, which both implementations refused on
    the argument object before any result existed: an engine with no result check
    at all passed it.
    """

    async def _page(engine: FakeAssistantEngine) -> object:
        for index in range(6):
            engine.hold(f"rec-{index}", content=f"the office is in Boston, building {index}")
        return await engine.beliefs()

    with pytest.raises(OversizedValueError):
        await _page(FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT))
    assert await _page(_UnlimitedEngine(max_payload_bytes=_TINY_LIMIT))  # nothing refused it


class _PermissiveEngine(FakeAssistantEngine):
    """An engine that admits a blank identifier — the §3c/§9 violation."""

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Look the id up without validating it first."""
        return self.beliefs_held.get(record_id)


async def test_the_identifier_clause_catches_a_permissive_engine() -> None:
    """A blank id must be refused, not answered ``None``.

    The distinction is what stops "no such belief" — a true sentence about a call
    the caller never meant to make — from standing in for a refusal.
    """
    with pytest.raises(ValueError, match=r"\w"):
        await FakeAssistantEngine().belief("  ")
    assert await _PermissiveEngine().belief("  ") is None  # nothing refused it


async def test_the_identifier_clause_catches_an_engine_that_does_not_strip() -> None:
    """The normalisation half, which a "reject blank" rule alone would leave open."""
    conforming = FakeAssistantEngine()
    conforming.hold("rec-1", content="the office is in Boston")
    assert await conforming.belief("  rec-1  ") is not None

    permissive = _PermissiveEngine()
    permissive.hold("rec-1", content="the office is in Boston")
    assert await permissive.belief("  rec-1  ") is None  # the raw value was looked up


class _InsertionOrderEngine(FakeAssistantEngine):
    """An engine that lists conversations as they were created — the ADR-0074 §2 gap."""

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """Return them in insertion order, which is what a naive dict gives."""
        held = tuple(
            ConversationSummary(
                id=digest.id,
                started_at=digest.started_at,
                last_active_at=digest.started_at,
                last_turn_at=digest.last_turn_at,
            )
            for digest in self.conversations_held.values()
        )
        return held[offset : offset + limit]


async def test_the_ordering_clause_catches_insertion_order() -> None:
    """The suite's ordering case really does separate the two behaviours.

    Two conversations and no continuation is the shape where the two orders
    *disagree*: activity descending puts the newer first, insertion order puts the
    older first. Continuing the older one afterwards makes them agree again, which
    is why the suite asserts both halves — the second alone would pass against an
    engine that never ordered anything.
    """

    async def _listed(engine: FakeAssistantEngine) -> list[str]:
        await engine.start_conversation()
        await engine.start_conversation()
        return [one.id for one in await engine.recent_conversations()]

    assert await _listed(FakeAssistantEngine()) == ["c-2", "c-1"]
    assert await _listed(_InsertionOrderEngine()) == ["c-1", "c-2"]  # nothing ordered it


def test_the_payload_limit_is_guarded_exactly_as_the_concrete_engine_guards_it() -> None:
    """ADR-0085 §8c's limit, held to the same shape on the double (#1686).

    ADR-0084 §4's substitutability runs in both directions, and this is the argument
    with the widest blast radius on this surface: *every* argument check and *every* result
    check this double performs measures against this one number, so a value that
    cannot bind does not weaken the contract limit, it removes it. ``float("nan")``
    is the sharp case — it compares ``False`` against every ``>``, so nothing is ever
    over the limit and the double reports health throughout.
    """
    for wrong_type in (True, 1.5, float("nan"), float("inf"), "1"):
        with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
            FakeAssistantEngine(max_payload_bytes=wrong_type)  # type: ignore[arg-type]

    for not_positive in (0, -1):
        with pytest.raises(ValueError, match="max_payload_bytes must be positive"):
            FakeAssistantEngine(max_payload_bytes=not_positive)

    assert FakeAssistantEngine(max_payload_bytes=1) is not None


def test_an_int_subclass_that_answers_its_own_comparisons_is_refused_as_a_limit() -> None:
    """The guard is an allowlist of the exact ``int``, so a subclass cannot slip past.

    A denylist naming ``bool`` closes one case of a class. This is another, and it is
    the one that makes the limit non-binding rather than merely wrong: Python gives a
    *subclass's* reflected comparison priority, so a value overriding ``__gt__``
    answers every ``size > limit`` the double performs, and overriding ``__lt__``
    walks through the positivity check on the way in. The two together are a
    contract limit nothing is ever over, on a double whose whole job is to make a
    consumer's tests mean something.
    """

    class _NonBinding(int):
        def __lt__(self, other: object) -> bool:
            return False

        def __gt__(self, other: object) -> bool:
            return False

    with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
        FakeAssistantEngine(max_payload_bytes=_NonBinding(0))


def test_a_knob_that_cannot_describe_itself_still_gets_the_documented_refusal() -> None:
    """The diagnostic must not be able to destroy the diagnosis (#1686).

    The refusal interpolates the offending value, so a value whose ``__repr__`` raises
    would otherwise replace the documented ``TypeError`` with whatever that
    ``__repr__`` threw — from inside the ``raise`` that reports it. ``core.types``
    already owns the non-throwing renderer for exactly this, and the placeholder it
    falls back to is what the caller sees.
    """

    class _Unspeakable:
        def __repr__(self) -> str:
            msg = "this value refuses to describe itself"
            raise RuntimeError(msg)

    with pytest.raises(TypeError, match="max_payload_bytes must be an integer"):
        FakeAssistantEngine(max_payload_bytes=_Unspeakable())  # type: ignore[arg-type]


async def test_seeding_over_a_held_id_replaces_its_placement_rather_than_inheriting_one() -> None:
    """``hold``'s ``placement`` default means the default placement, not the last one.

    The table is held beside the beliefs rather than on them, so a conditional write
    into it would leak: ``hold(id, placement=DERIVED)`` followed by a plain ``hold(id)``
    would leave a **fresh** belief carrying the previous one's ``DERIVED`` narrowing, and
    ``unguard`` would then refuse an act on a record no producer had ever narrowed.

    The refusal is what makes this worth a case rather than a comment: it is silent and
    it fails *closed*, so a consumer meeting it would read a correct-looking
    "``unguard`` declined" and have no way to tell it from ADR-0217 §3's real clause.
    """
    engine = FakeAssistantEngine()
    engine.hold(
        "rec-1",
        content="the merger is off",
        placement=Placement(
            reach=PlacementReach.OWNER,
            set_by=PlacementSetter.DERIVED,
            set_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        ),
    )

    engine.hold("rec-1", content="the merger is back on")

    lifted = await engine.unguard("rec-1")

    assert lifted is not None
    assert lifted.reach is PlacementReach.ANYONE
    assert lifted.set_by is PlacementSetter.OWNER_ACT


async def test_two_first_reads_of_a_held_conversation_join_the_chat_space_once() -> None:
    """A held conversation joins the chat space once, however many first reads race."""
    engine = FakeAssistantEngine()
    engine.hold_conversation("c")

    first, second = await asyncio.gather(engine.transcript("c"), engine.transcript("c"))

    assert first is not None
    assert second is not None
    started = (await engine.chat_changes(after=0)).changes
    assert [type(one).__name__ for one in started] == ["ConversationStartedChange"]


async def test_a_composing_signal_is_recorded_as_a_call_and_nowhere_else() -> None:
    """ADR-0332 §5:8: the fake keeps the signal in ``calls`` alone, for a test to read."""
    engine = FakeAssistantEngine()
    conversation = (await engine.start_conversation()).id
    before = await engine.chat_changes(after=0)

    await engine.composing(f" {conversation} ")

    assert engine.calls[-1] == ("composing", {"conversation_id": conversation})
    assert await engine.chat_changes(after=0) == before


async def test_a_deletion_racing_a_first_read_leaves_no_chat_conversation() -> None:
    """Deleting a held conversation while a first read is joining it to the chat space.

    The deletion waits for the join and stamps what it joined, so no write is accepted
    into a conversation every other read calls deleted (#2696 round 3).
    """
    engine = FakeAssistantEngine()
    engine.hold_conversation("c")
    entered, release = asyncio.Event(), asyncio.Event()
    start = engine.chat.start

    async def slow_start() -> Conversation:
        entered.set()
        await release.wait()
        return await start()

    engine.chat.start = slow_start  # type: ignore[method-assign]
    reading = asyncio.create_task(engine.transcript("c"))
    await entered.wait()
    deleting = asyncio.create_task(engine.delete_conversation("c"))
    await asyncio.sleep(0)
    release.set()
    await reading
    assert await deleting is True

    assert await engine.conversation("c") is None
    assert await engine.transcript("c") is None
    with pytest.raises(UnknownConversationError):
        await engine.write_message(
            "c", message=UserMessage(device_id="phone", message_id="m", text="hello")
        )


async def _started(engine: FakeAssistantEngine) -> str:
    """Start a conversation on one device, so a message can be written into it."""
    await engine.set_my_devices([ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)])
    return (await engine.start_conversation()).id


async def _reading(engine: FakeAssistantEngine, conversation: str) -> asyncio.Task[None]:
    """Write one message, and return the read the fake's reader started for it.

    The read is the activation that takes the message in and captures its episode
    (ADR-0293 §6): the conversational capture left since ``converse`` retired
    (ADR-0309 §5:1).
    """
    before = set(engine._chat_reads)
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id="m-1", text="hello")
    )
    (read,) = set(engine._chat_reads) - before
    return read


async def test_a_forgotten_capture_whose_write_commits_then_cancels_leaves_no_episode() -> None:
    """ADR-0293 §2:6: a write committed and then cancelled is still cleaned up.

    The turn's capture write is held, its conversation forgotten, and the write then
    commits and propagates a cancellation — which the store's cancellation contract
    permits. The forgotten capture deletes what landed before the cancellation goes on
    (#2696 round 5).
    """
    engine = FakeAssistantEngine()
    conversation = await _started(engine)
    memory = engine.episode_memory
    entered, release = asyncio.Event(), asyncio.Event()
    original = memory.write_atomic
    landed: list[str] = []

    async def commit_then_cancel(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        entered.set()
        await release.wait()
        await original(writes)
        landed.extend(write.record.id for write in writes)
        raise asyncio.CancelledError

    memory.write_atomic = commit_then_cancel  # type: ignore[method-assign]
    turn = await _reading(engine, conversation)
    await entered.wait()
    await engine.forget_conversation(conversation)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert landed, "the write committed before it was cancelled"
    assert await memory.get(landed[0]) is None


async def test_a_cancelled_insert_never_withdraws_another_conversations_episode() -> None:
    """ADR-0293 §2:8: forgetting reaches that conversation's episodes alone.

    Conversation A holds an episode at the address B's turn reuses. B's insert is
    cancelled before it reaches the store's collision check, and B was forgotten
    meanwhile: the record at the address is A's, so nothing is deleted (#2696 r6).
    """
    engine = FakeAssistantEngine()
    engine.activation_id_factory = lambda: "00000000-0000-4000-8000-0000000000cc"
    first = await _started(engine)
    await (await _reading(engine, first))
    address = "activation:00000000-0000-4000-8000-0000000000cc"
    assert await engine.episode_memory.get(address) is not None
    second = await _started(engine)
    memory = engine.episode_memory
    entered, release = asyncio.Event(), asyncio.Event()

    async def cancelled_before_the_check(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        entered.set()
        await release.wait()
        raise asyncio.CancelledError

    memory.write_atomic = cancelled_before_the_check  # type: ignore[method-assign]
    turn = await _reading(engine, second)
    await entered.wait()
    await engine.forget_conversation(second)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert await memory.get(address) is not None, "A's episode is not B's to withdraw"


async def test_a_forgotten_captures_cleanup_outlasts_its_callers_cancellation() -> None:
    """ADR-0293 §2:6, ADR-0275 §8:11: the withdrawal runs to its end, then cancels.

    The capture's write lands after its conversation was forgotten; its withdrawal is
    held, and the turn is cancelled twice while it waits. The episode is still gone
    once the withdrawal is released, and the turn ends cancelled (#2696 r6).
    """
    engine = FakeAssistantEngine()
    conversation = await _started(engine)
    memory = engine.episode_memory
    writing, write_go = asyncio.Event(), asyncio.Event()
    deleting, delete_go = asyncio.Event(), asyncio.Event()
    write, delete = memory.write_atomic, memory.delete
    landed: list[str] = []

    async def held_write(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        writing.set()
        await write_go.wait()
        landed.extend(one.record.id for one in writes)
        return await write(writes)

    async def held_delete(record_id: str) -> bool:
        deleting.set()
        await delete_go.wait()
        return await delete(record_id)

    memory.write_atomic = held_write  # type: ignore[method-assign]
    turn = await _reading(engine, conversation)
    await writing.wait()
    await engine.forget_conversation(conversation)
    memory.delete = held_delete  # type: ignore[method-assign]
    write_go.set()
    await deleting.wait()
    turn.cancel()
    await asyncio.sleep(0)
    turn.cancel()
    await asyncio.sleep(0)
    assert not turn.done(), "the withdrawal holds the turn until it is done"
    delete_go.set()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert landed
    assert await memory.get(landed[0]) is None


async def test_a_cancellation_landing_as_the_cleanup_finishes_still_cancels_the_turn() -> None:
    """ADR-0060, ADR-0293 §2:6: a cancellation is never lost to a finished cleanup.

    The withdrawal is released and the turn cancelled with no yield between, so the
    cleanup ends before the turn handles its cancellation. The turn still ends
    cancelled, and the episode is still gone (#2696 round 7).
    """
    engine = FakeAssistantEngine()
    conversation = await _started(engine)
    memory = engine.episode_memory
    writing, write_go = asyncio.Event(), asyncio.Event()
    deleting, delete_go = asyncio.Event(), asyncio.Event()
    write, delete = memory.write_atomic, memory.delete
    landed: list[str] = []

    async def held_write(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        writing.set()
        await write_go.wait()
        landed.extend(one.record.id for one in writes)
        return await write(writes)

    async def held_delete(record_id: str) -> bool:
        deleting.set()
        await delete_go.wait()
        return await delete(record_id)

    memory.write_atomic = held_write  # type: ignore[method-assign]
    turn = await _reading(engine, conversation)
    await writing.wait()
    await engine.forget_conversation(conversation)
    memory.delete = held_delete  # type: ignore[method-assign]
    write_go.set()
    await deleting.wait()
    delete_go.set()
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn

    assert landed
    assert await memory.get(landed[0]) is None


# --- ADR-0293 §6, §10: the fake answers a written message, and can be told not to ------


async def _chat_with_one_message(engine: FakeAssistantEngine) -> str:
    """Start a conversation on one device and write ``"hello"`` into it."""
    device = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
    await engine.set_my_devices([device])
    conversation = (await engine.start_conversation()).id
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id="m-1", text="hello")
    )
    return conversation


async def _settled(engine: FakeAssistantEngine) -> None:
    """Let every read the fake's reader started run to its end."""
    async with asyncio.timeout(10):
        while engine._chat_reads:
            await asyncio.gather(*engine._chat_reads)


async def _episode(engine: FakeAssistantEngine) -> EpisodicMemory:
    """The one activation's episode the fake captured, read from its episode store."""
    (episode,) = [
        one for one in await engine.episode_memory.export() if one.id.startswith("activation:")
    ]
    assert isinstance(episode, EpisodicMemory)
    return episode


async def test_the_fake_answers_with_a_composed_reply_naming_the_input() -> None:
    """The canned reply, written once by the engine's own adapter (§10:1)."""
    engine = FakeAssistantEngine()
    conversation = await _chat_with_one_message(engine)
    await _settled(engine)
    page = await engine.transcript(conversation)
    assert page is not None
    reply = page.entries[-1]
    assert isinstance(reply, TranscriptMessage)
    assert reply.author is MessageAuthor.ASSISTANT
    assert "hello" in reply.text
    # ADR-0307 §10: the episode keeps the message it wrote as its outcome.
    assert (await _episode(engine)).outcome == reply.text


async def test_a_reply_past_the_transcripts_bound_is_cut_and_says_so() -> None:
    """§5:2, §6:16: cut to the bound and marked cut off, as the phases cut a message."""
    engine = FakeAssistantEngine()
    device = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
    await engine.set_my_devices([device])
    conversation = (await engine.start_conversation()).id
    text = "x" * TRANSCRIPT_MESSAGE_MAX_CHARS
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id="m-1", text=text)
    )
    await _settled(engine)
    page = await engine.transcript(conversation)
    assert page is not None
    reply = page.entries[-1]
    assert isinstance(reply, TranscriptMessage)
    assert reply.author is MessageAuthor.ASSISTANT
    assert len(reply.text) == TRANSCRIPT_MESSAGE_MAX_CHARS
    assert reply.cut_off
    # ADR-0307 §10: the text as the conversation holds it — the cut one, not the uncut.
    assert (await _episode(engine)).outcome == reply.text


async def test_a_pass_that_fails_writes_couldnt_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0317 §3: what was taken in is consumed, so a failed pass says it could not finish."""
    engine = FakeAssistantEngine()

    def failing(*_: object) -> NewMessage:
        msg = "the pass failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(engine, "_chat_message", failing)
    conversation = await _chat_with_one_message(engine)
    await _settled(engine)
    page = await engine.transcript(conversation)
    assert page is not None
    reply = page.entries[-1]
    assert isinstance(reply, TranscriptMessage)
    assert (reply.author, reply.text) == (MessageAuthor.ASSISTANT, COULDNT_FINISH)
    digest = await engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.COULDNT_FINISH
    assert (await _episode(engine)).outcome == COULDNT_FINISH


async def test_a_cancellation_during_the_couldnt_finish_write_still_ends_the_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0293 §8, §9:2: cancelled while writing *couldn't finish*, the pass still ends.

    Its episode is captured interrupted, it stops counting as running, and the
    cancellation goes on.
    """
    engine = FakeAssistantEngine()

    def failing(*_: object) -> NewMessage:
        msg = "the pass failed"
        raise RuntimeError(msg)

    writing = asyncio.Event()
    never = asyncio.Event()
    conversation = await _started(engine)
    append = engine.chat.append_message

    async def held(conversation_id: str, message: NewMessage) -> MessageReceipt:
        if message.author is not MessageAuthor.ASSISTANT:
            return await append(conversation_id, message)
        writing.set()
        await never.wait()
        raise AssertionError  # pragma: no cover — cancelled first

    monkeypatch.setattr(engine, "_chat_message", failing)
    monkeypatch.setattr(engine.chat, "append_message", held)
    read = await _reading(engine, conversation)
    async with asyncio.timeout(10):
        await writing.wait()
    read.cancel()
    with pytest.raises(asyncio.CancelledError):
        await read

    assert not engine._running_activations
    digest = await engine.conversation(conversation)
    assert digest is not None
    assert not digest.state.working
    assert digest.state.last_ended is ActivationEnding.INTERRUPTED
    (episode,) = [
        one for one in await engine.episode_memory.export() if one.id.startswith("activation:")
    ]
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is ProcessingStatus.INTERRUPTED


@pytest.mark.parametrize("by", ["constructor", "attribute"])
async def test_a_fake_told_not_to_answer_leaves_the_message_waiting(by: str) -> None:
    """``chat_reader=False``: the message is recorded and waits, as before the reader."""
    engine = FakeAssistantEngine(chat_reader=by != "constructor")
    if by == "attribute":
        engine.chat_reader = False
    conversation = await _chat_with_one_message(engine)
    for _ in range(10):
        await asyncio.sleep(0)
    assert not engine._chat_reads
    page = await engine.transcript(conversation)
    assert page is not None
    assert [type(one) for one in page.entries] == [TranscriptMessage]
    assert len(await engine.chat.untaken_messages(conversation)) == 1
    digest = await engine.conversation(conversation)
    assert digest is not None
    assert digest.state == ConversationState()


async def test_a_reply_the_store_refuses_does_not_strand_what_waited() -> None:
    """As the engine: a reply the store refuses is lost, and the reader goes on to what waited.

    The first activation is held at its marking while a second message is written;
    its reply's write is then refused once. The second message is still taken in and
    answered, rather than left waiting for a notice that never comes.
    """
    engine = FakeAssistantEngine()
    entered, release = asyncio.Event(), asyncio.Event()
    take_in, append = engine.chat.take_in, engine.chat.append_message

    async def held(*args: Any, **kwargs: Any) -> tuple[int, ...]:
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await take_in(*args, **kwargs)

    refused: list[NewMessage] = []

    async def refusing(conversation_id: str, message: NewMessage) -> MessageReceipt:
        if message.author is MessageAuthor.ASSISTANT and not refused:
            refused.append(message)
            msg = "the store is unavailable"
            raise ConversationStoreError(msg)
        return await append(conversation_id, message)

    engine.chat.take_in = held  # type: ignore[method-assign]
    engine.chat.append_message = refusing  # type: ignore[method-assign]
    conversation = await _chat_with_one_message(engine)
    async with asyncio.timeout(10):
        await entered.wait()
    await engine.write_message(
        conversation, message=UserMessage(device_id="phone", message_id="m-2", text="again")
    )
    release.set()
    await _settled(engine)

    assert len(refused) == 1
    page = await engine.transcript(conversation)
    assert page is not None
    authors = [one.author for one in page.entries if isinstance(one, TranscriptMessage)]
    assert authors == [MessageAuthor.USER, MessageAuthor.USER, MessageAuthor.ASSISTANT]
    assert await engine.chat.untaken_messages(conversation) == ()


async def test_a_reply_the_store_refuses_leaves_its_episode_without_an_outcome() -> None:
    """ADR-0307 §10: an activation that wrote no message keeps no outcome.

    The store refuses the reply's write, so the conversation holds no message from the
    activation, and its episode records none.
    """
    engine = FakeAssistantEngine()
    append = engine.chat.append_message
    refused: list[NewMessage] = []

    async def refusing(conversation_id: str, message: NewMessage) -> MessageReceipt:
        if message.author is MessageAuthor.ASSISTANT:
            refused.append(message)
            msg = "the store is unavailable"
            raise ConversationStoreError(msg)
        return await append(conversation_id, message)

    engine.chat.append_message = refusing  # type: ignore[method-assign]
    conversation = await _chat_with_one_message(engine)
    await _settled(engine)

    assert len(refused) == 1
    page = await engine.transcript(conversation)
    assert page is not None
    authors = [one.author for one in page.entries if isinstance(one, TranscriptMessage)]
    assert authors == [MessageAuthor.USER]
    assert (await _episode(engine)).outcome is None

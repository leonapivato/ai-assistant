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
from typing import TYPE_CHECKING

import pytest
from assistant_engine_contract import (
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
    SETTLED_SINGLE_SLOT,
    SPEAKABLE_NOTIFICATION,
    SPEND_ZERO_CEILING,
    UNSPEAKABLE_NOTIFICATION,
    AssistantEngineContract,
    ConnectionSubject,
    DecisionSubject,
    DerivedPlacementSubject,
    InvocationSubject,
    ReadSubject,
    RoutedParkSubject,
    SettledParkSubject,
    SingleSlotParkSubject,
    SpendSubject,
    TranscriptSubject,
    backwards_clock,
    near_ceiling_limit,
    overfull_invocation_rows,
    page_after_mutating_the_filter,
    seeded_invocation_trail,
    seeded_read_trail,
    seeded_spend_ledger,
    seeded_trail,
    seeded_transcript_archive,
    spoken_routed_park_outcome,
    spoken_step_park_outcome,
)

from ai_assistant.core.errors import DuplicateDecisionError, OversizedValueError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    ActionRequest,
    AnswerKind,
    Attestation,
    BeliefBand,
    BeliefSummary,
    BoundAccount,
    ContinuationToken,
    ConversationSummary,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    GrantScope,
    Idempotency,
    MemoryKind,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    QuestionState,
    RecipientGrantNotEstablished,
    Reversibility,
    RiskLevel,
    RoutableOperation,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
    UtcInstant,
)
from ai_assistant.testing import FakeAssistantEngine

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


#: The instant every recipient-grant case here is arranged at, matching the fake's
#: own default :attr:`recipient_grant_clock` so nothing has to move it.
_RECIPIENT_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _transmitting_tool() -> ToolDefinition:
    """A declaration a recorded egress ``CONFIRM`` can be about."""
    return ToolDefinition(
        id="send_email",
        capability="send_email",
        description="Send an email.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.IRREVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(DataTier.PERSONAL,),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NONE,
    )


_TRANSMITTING_TOOL = _transmitting_tool()


class TestFakeAssistantEngineContract(AssistantEngineContract):
    """The canonical fake, held to the shared contract."""

    @pytest.fixture
    def engine(self) -> AssistantEngine:
        """One fake engine at the ordinary contract limit."""
        return FakeAssistantEngine()

    @pytest.fixture
    def tiny_engine(self) -> AssistantEngine:
        """The same implementation, with the limit small enough to reach."""
        return FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)

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
            engine.hold_grant(f"source-{index}", scope=(GrantScope.FACET,))
        return engine

    @pytest.fixture
    def routed_park(self) -> RoutedParkSubject:
        """One fake engine holding a single answerable routed park, on a ``forget``.

        The card is assembled by ``park_routed`` from the operation and the belief the
        engine already holds, so what the shared suite holds this fake to is the type's
        own invariants rather than a pre-built member — ``park``'s arrangement one
        operation over.
        """
        engine = FakeAssistantEngine()
        held = engine.hold("rec-routed", content="the user likes jazz")
        engine.park_routed("routed-1", operation=RoutableOperation.FORGET, subject=(held,))
        return RoutedParkSubject(
            engine=engine, token=ContinuationToken(handle="routed-1"), belief_id=held.id
        )

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
    def parked_engine(self) -> AssistantEngine:
        """One fake engine holding a single answerable park, on an egress call.

        The binding is handed to ``park`` whole and reduced there by the rule the
        real engine uses (ADR-0178 §5), so what the suite's correspondence clause
        holds this fake to is the *reduction* rather than a pre-built member.
        """
        engine = FakeAssistantEngine()
        engine.park("h-1", egress=_binding())
        return engine

    @pytest.fixture
    def spoken_step_park(self) -> AssistantEngine:
        """One fake engine whose scripted turn is ADR-0207 §1's step park.

        ``turn_outcome`` is the double's own documented lever for "a consumer that
        wants the turn to say something else", and the outcome comes from the shared
        suite rather than being written out here — so this binding and the wire one
        script the *same* shape and the suite is holding all three implementations to
        one statement of §1.
        """
        engine = FakeAssistantEngine()
        engine.turn_outcome = spoken_step_park_outcome()
        return engine

    @pytest.fixture
    def spoken_routed_park(self) -> AssistantEngine:
        """One fake engine whose scripted turn is ADR-0207 §1's routed park."""
        engine = FakeAssistantEngine()
        engine.turn_outcome = spoken_routed_park_outcome()
        return engine

    @pytest.fixture
    async def settled_park(self) -> SettledParkSubject:
        """One fake engine that has answered its park, and the token that named it.

        Settled by calling ``resume`` rather than by seeding ``settled`` directly, so
        the record under test is the one this fake's own resolution installs — a fake
        whose lever wrote the record would pass the suite over a path no ``resume``
        takes.
        """
        engine = FakeAssistantEngine()
        engine.park("h-1", egress=_binding())
        token = ContinuationToken(handle="h-1")
        await engine.resume(token, approved=True, timeout=timedelta(seconds=30))
        return SettledParkSubject(engine=engine, token=token)

    @pytest.fixture
    async def settled_park_without_its_execution(self) -> SettledParkSubject:
        """:attr:`settled_park`'s subject whose ``executions`` have been emptied.

        ``executions`` is this fake's stand-in for the plan store a restatement
        re-reads (ADR-0198 §2), and emptying it is the fake's spelling of a store that
        has stopped holding the settled binding's execution. It is done from the test
        process because no call on the promoted surface removes one — which is the same
        reason the concrete binding reaches for the store's own data-rights operation.
        """
        engine = FakeAssistantEngine()
        engine.park("h-1", egress=_binding())
        token = ContinuationToken(handle="h-1")
        await engine.resume(token, approved=True, timeout=timedelta(seconds=30))
        engine.executions.clear()
        return SettledParkSubject(engine=engine, token=token)

    @pytest.fixture
    async def single_slot_parks(self) -> SingleSlotParkSubject:
        """A fake at a ceiling of one, holding one settled record and one live park.

        The parks are levered in and the settlement is real, which is the division
        this fake keeps everywhere: a park is reached inside a turn no fake runs, and
        what the suite is holding this one to is what ``resume`` does with them. The
        ceiling binds only the retained set here — this fake admits no turn, so the
        backpressure half has nothing to reach — and the retention is the half ADR-0198
        §4's discard is about.
        """
        engine = FakeAssistantEngine(max_outstanding_confirmations=SETTLED_SINGLE_SLOT)
        engine.park("h-1", egress=_binding())
        settled = ContinuationToken(handle="h-1")
        await engine.resume(settled, approved=True, timeout=timedelta(seconds=30))
        engine.park("h-2", egress=_binding())
        return SingleSlotParkSubject(
            engine=engine, settled=settled, parked=ContinuationToken(handle="h-2")
        )

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
    def transcripts(self) -> TranscriptSubject:
        """The fake over a seeded transcript archive — the archive it relays to.

        A plain attribute on :attr:`reads`' terms, and here the reason the fake holds
        a whole ``TranscriptArchive`` rather than a dict is the sharpest of the three:
        ADR-0225 §6 and §7 make the retention predicate, the matching predicate, the
        total order and both size figures the **archive's** guarantees, so a fake
        engine that reimplemented any of them would be a second implementation of a
        rule this suite could then only compare against itself.
        """
        archive = seeded_transcript_archive()
        engine = FakeAssistantEngine()
        engine.archive = archive
        return TranscriptSubject(engine=engine, archive=archive)

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


async def test_the_fake_s_listing_discloses_the_same_elision_as_its_detail_view() -> None:
    """ADR-0107 §8 item 5: the canonical fake and the real projection agree.

    ``_summary_of`` is the fake's counterpart to
    :func:`~ai_assistant.orchestration.engine.belief_summary_from_record`, and a fake
    that dropped the field would let a consumer's suite pass against a listing that
    discloses **less** than the detail view it was drilled into — exactly the
    inversion of ADR-0077 §6's split that ADR-0107 §3 refused when it declined to put
    the field on ``BeliefSummary`` alone.

    Asserted at a non-default value on both surfaces, per §8 item 6: at ``0`` the two
    would agree whether the field were carried or silently dropped.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the office is in Boston", evidence_elided=900)

    page = await engine.beliefs()
    assert [summary.evidence_elided for summary in page] == [900]

    detail = await engine.belief("rec-1")
    assert detail is not None
    assert detail.evidence_elided == 900
    assert page[0].evidence_elided == detail.evidence_elided


async def test_the_two_question_enumerations_stay_disjoint() -> None:
    """ADR-0078 §8: an interrupted question is a second list all the way up.

    Offering it beside the answerable ones would present a claim that cannot be
    taken — the system does not know whether the memory write landed.
    """
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="works from home", state=QuestionState.OPEN)
    engine.ask("q-2", content="prefers metric", state=QuestionState.INTERRUPTED)
    assert [q.id for q in await engine.questions()] == ["q-1"]
    assert [q.id for q in await engine.interrupted_questions()] == ["q-2"]


async def test_accepting_a_question_leaves_a_record_live() -> None:
    """An applied answer names what is now live (ADR-0078 §8)."""
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="works from home", state=QuestionState.OPEN)
    outcome = await engine.answer("q-1", accept=True)
    assert outcome.record_id is not None
    assert await engine.belief(outcome.record_id) is not None
    assert await engine.questions() == ()


async def test_declining_a_question_writes_nothing() -> None:
    """A rejection needs no claim, because it writes nothing."""
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="works from home", state=QuestionState.OPEN)
    outcome = await engine.answer("q-1", accept=False)
    assert outcome.record_id is None
    assert await engine.beliefs() == ()


async def test_a_parked_confirmation_is_recovered_and_then_resolvable() -> None:
    """ADR-0052 §1's enumerate-and-re-mint, in miniature."""
    engine = FakeAssistantEngine()
    engine.park("h-1")
    pending = await engine.pending_confirmations()
    assert len(pending) == 1
    await engine.resume(pending[0].token, approved=True, timeout=timedelta(seconds=30))
    assert await engine.pending_confirmations() == ()


async def test_the_filters_compose_by_conjunction() -> None:
    """A belief is listed when its band is selected *and* its kind is (ADR-0073 §2)."""
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="a", kind=MemoryKind.SEMANTIC, band=BeliefBand.ASSERTED)
    engine.hold("rec-2", content="b", kind=MemoryKind.PREFERENCE, band=BeliefBand.DERIVED)
    listed = await engine.beliefs(bands=[BeliefBand.ASSERTED], kinds=[MemoryKind.PREFERENCE])
    assert listed == ()
    listed = await engine.beliefs(bands=[BeliefBand.DERIVED], kinds=[MemoryKind.PREFERENCE])
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
        await engine.converse("one", timeout=timedelta(seconds=30))
        await engine.converse("two", timeout=timedelta(seconds=30))
        return [one.id for one in await engine.recent_conversations()]

    assert await _listed(FakeAssistantEngine()) == ["c-2", "c-1"]
    assert await _listed(_InsertionOrderEngine()) == ["c-1", "c-2"]  # nothing ordered it


class _SteplessEngine(FakeAssistantEngine):
    """An engine whose resume carries no resolved step — the ADR-0085 §4 gap."""

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
        remember_recipients_until: UtcInstant | None = None,
    ) -> TurnOutcome:
        """Resolve the park and hand back nothing to render."""
        await super().resume(
            token,
            approved=approved,
            timeout=timeout,
            remember_recipients_until=remember_recipients_until,
        )
        return TurnOutcome(turn=None)


def test_the_retention_ceiling_is_guarded_exactly_as_the_concrete_engine_guards_it() -> None:
    """The fake refuses every value ``Engine`` refuses, with the class ``Engine`` uses.

    ADR-0084 §4's substitutability runs in both directions. A fake admitting a
    deployment no engine admits lets a consumer's tests pass over a configuration
    production cannot be built into — and a fake refusing the same value with a
    different class makes the two disagree about what kind of failure it is, which is
    the half a positivity check on its own would leave open.

    The three shapes are the ones the concrete engine names: a ``bool``, which is an
    ``int`` subclass and would silently mean one; a ``float``, which would compare
    fine and then bound the retention at ``int``-of-itself; and a non-positive count,
    which would discard from an empty table on the first settlement.
    """
    for wrong_type in (True, 1.5, "1"):
        with pytest.raises(TypeError):
            FakeAssistantEngine(max_outstanding_confirmations=wrong_type)  # type: ignore[arg-type]

    for not_positive in (0, -1):
        with pytest.raises(ValueError, match="must be positive"):
            FakeAssistantEngine(max_outstanding_confirmations=not_positive)

    # And the smallest admitted value really is one, which is what the shared suite's
    # bound case is built at.
    assert FakeAssistantEngine(max_outstanding_confirmations=1) is not None


def test_the_payload_limit_is_guarded_exactly_as_the_concrete_engine_guards_it() -> None:
    """ADR-0085 §8c's limit, held to the same shape on the double (#1686).

    The same both-directions argument as the ceiling above, over the argument with the
    widest blast radius on this surface: *every* argument check and *every* result
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
    with pytest.raises(TypeError, match="max_outstanding_confirmations must be an integer"):
        FakeAssistantEngine(max_outstanding_confirmations=_NonBinding(0))


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


async def test_the_resume_clause_catches_an_outcome_with_no_step() -> None:
    """A resume that carries neither a turn nor a step leaves a client nothing.

    ``turn`` is legitimately ``None`` on a recovered park, which is exactly why the
    step cannot be: between them they are the whole of what a resumption produced.
    """
    conforming = FakeAssistantEngine()
    conforming.park("h-1")
    resolved = await conforming.resume(
        ContinuationToken(handle="h-1"), approved=True, timeout=timedelta(seconds=30)
    )
    assert resolved.step is not None

    stepless = _SteplessEngine()
    stepless.park("h-1")
    empty = await stepless.resume(
        ContinuationToken(handle="h-1"), approved=True, timeout=timedelta(seconds=30)
    )
    assert empty.step is None  # nothing to render, and nothing refused it


# --- ADR-0189 §2 on the far side of an answer (#1523's knobs, round-1 finding 1) ---


async def test_accepting_a_question_writes_a_belief_carrying_the_proposals_own_origin() -> None:
    """ADR-0189 §2 makes these facts about the record acceptance **writes**.

    So an ``answer`` that dropped them would leave this engine holding a belief whose
    origin differs from the question it came from — and on the attested band it would
    not merely differ, it would be unconstructable: ``Provenance`` makes an
    ``Attestation`` mandatory exactly there (ADR-0092 §1), so writing the proposal's
    band without the proposal's attestation raises rather than lying quietly.

    Unreachable until #1523's knobs landed, because :meth:`ask` fixed the band at
    ``ASSERTED`` and no question could carry an attestation at all. Making the state
    scriptable is what puts an engine on the far side of it.
    """
    engine = FakeAssistantEngine()
    engine.ask(
        "q-1",
        content="the board dine at Nopa on Thursday",
        state=QuestionState.OPEN,
        band=BeliefBand.ATTESTED,
        attestation=_REPORTED,
    )

    outcome = await engine.answer("q-1", accept=True)
    assert outcome.record_id is not None
    written = await engine.belief(outcome.record_id)

    assert outcome.kind is AnswerKind.APPLIED
    assert written is not None
    assert written.band is BeliefBand.ATTESTED
    assert written.attestation == _REPORTED
    assert written.rests_on_recorded_external_content is True


async def test_accepting_a_tainted_proposal_keeps_the_warrant_it_was_deferred_for() -> None:
    """The predicate is what #746 exists for, and it is the one an answer would drop.

    A tainted consolidation reaches the user as an ``ASK_USER`` question precisely
    because its warrant rests on recorded external content (ADR-0106 §6). A belief
    written from accepting it that reported ``False`` would have laundered the one fact
    the question was raised about — and on the ``DERIVED`` band nothing else on the
    projection supplies it.
    """
    engine = FakeAssistantEngine()
    engine.ask(
        "q-1",
        content="they consolidate travel around board weeks",
        state=QuestionState.OPEN,
        band=BeliefBand.DERIVED,
        derived_from_external=True,
    )

    outcome = await engine.answer("q-1", accept=True)
    assert outcome.record_id is not None
    written = await engine.belief(outcome.record_id)

    assert written is not None
    assert written.rests_on_recorded_external_content is True
    assert written.attestation is None, "a derived belief names no reporting source"


async def test_a_stray_externality_answer_is_discarded_by_the_band_and_not_by_this_engine() -> None:
    """ADR-0106 §2's band guard, reached through the answer rather than restated in it.

    ADR-0106 §7 forbids a band-keyed validator on ``derived_from_external``, so a
    ``USER_ASSERTED`` provenance carrying ``True`` stays constructible, and ADR-0189 §2
    adds no validator to ``Question`` either — so a proposal banded ``ASSERTED`` with
    the predicate ``True`` is model-valid and reaches this method. What answers it is
    the classifier: "the user's own utterance is not [external], however it was
    composed" (ADR-0098 §1), so the written belief reports ``False``.

    Asserted here because the alternative repair — this engine zeroing the value before
    forwarding it — would be a second spelling of a rule ADR-0072 §4 already keys on the
    source, and a second spelling is a second thing that can disagree.
    """
    engine = FakeAssistantEngine()
    engine.ask(
        "q-1",
        content="the office is in Boston",
        state=QuestionState.OPEN,
        band=BeliefBand.ASSERTED,
        derived_from_external=True,
    )

    outcome = await engine.answer("q-1", accept=True)
    assert outcome.record_id is not None
    written = await engine.belief(outcome.record_id)

    assert written is not None
    assert written.rests_on_recorded_external_content is False


async def test_accepting_an_answer_retires_exactly_what_it_said_it_would() -> None:
    """ADR-0078 §8: ``retires`` is "the exact scope the answer authorises".

    Not decoration — so an engine that applied the correction and left the conflict live
    would hold two beliefs the user was told could not both stand, and every surface
    reading it would render the retired one as current. Unreachable until #1523 made
    ``retires`` scriptable, which is why it is checked now rather than earlier.

    The tombstone arm rides along because it is the same rule rather than an exception:
    a retirement that no longer resolves names a ``record_id`` like any other, the
    record is already gone (ADR-0045 §6), and discarding by id is idempotent.

    **The live entry carries resolved content and the tombstone names a record that was
    never held**, which is what makes this a scenario a producer could actually build.
    An earlier draft tombstoned the *live* record — so the question said "no longer
    held … would not touch it" about a belief the answer then destroyed, and the
    assertion passed while describing a state no store produces. Adversarial review
    caught it on this lane's round 2.
    """
    engine = FakeAssistantEngine()
    engine.hold("live-1", content="the user works from Madrid")
    engine.hold("keep-1", content="the office is in Boston")
    engine.ask(
        "q-1",
        content="the user works from Lisbon",
        state=QuestionState.OPEN,
        retires=(
            engine.retirement("live-1", content="the user works from Madrid"),
            engine.retirement("gone-1"),
        ),
    )

    outcome = await engine.answer("q-1", accept=True)

    assert outcome.record_id is not None
    assert await engine.belief("live-1") is None, "the named conflict is gone"
    assert await engine.belief("keep-1") is not None, "and nothing else was touched"
    assert await engine.belief(outcome.record_id) is not None


async def test_declining_an_answer_retires_nothing_and_writes_nothing() -> None:
    """The scope is what **accepting** authorises, so a rejection spends none of it.

    ADR-0078 §8's four outcomes are distinct in what they leave behind, and this is the
    one that must leave everything: a rejection that retired the conflicts anyway would
    destroy records on the strength of an answer that declined to make the change.
    """
    engine = FakeAssistantEngine()
    engine.hold("live-1", content="the user works from Madrid")
    engine.ask(
        "q-1",
        content="the user works from Lisbon",
        state=QuestionState.OPEN,
        retires=(engine.retirement("live-1"),),
    )

    outcome = await engine.answer("q-1", accept=False)

    assert outcome.kind is AnswerKind.REJECTED
    assert outcome.record_id is None
    assert await engine.belief("live-1") is not None


async def test_an_answer_that_retires_never_writes_over_a_record_it_did_not_name() -> None:
    """The scope is exact in both directions, and the id is where it stopped being.

    ADR-0078 §8 makes ``retires`` "the exact scope the answer authorises", which forbids
    retiring less than it named *and* touching anything it did not. The id an accepted
    answer wrote used to be sized from the store — fine while nothing shrank it, and
    wrong the moment this method began retiring: with ``rec-1`` and ``rec-2`` held,
    retiring ``rec-1`` frees the number ``rec-2`` and the next write lands on top of the
    survivor. Two beliefs become one, silently, with no answer having named the loser.

    Adversarial review found it on this lane's round 2, on the path this lane added.
    """
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="first", state=QuestionState.OPEN)
    engine.ask("q-2", content="second", state=QuestionState.OPEN)
    first = await engine.answer("q-1", accept=True)
    second = await engine.answer("q-2", accept=True)
    assert first.record_id is not None
    assert second.record_id is not None

    engine.ask(
        "q-3",
        content="third",
        state=QuestionState.OPEN,
        retires=(engine.retirement(first.record_id, content="first"),),
    )
    third = await engine.answer("q-3", accept=True)

    assert third.record_id not in {first.record_id, second.record_id}
    survivor = await engine.belief(second.record_id)
    assert survivor is not None, "the record no answer named is still held"
    assert survivor.content == "second", "and still says what it said"
    assert await engine.belief(first.record_id) is None, "the one that was named is gone"


async def test_an_explicitly_held_id_is_never_minted_over() -> None:
    """The other direction of the same rule, where a test holds a ``rec-N`` of its own.

    :meth:`hold` takes the id its caller names, so a suite that seeded ``rec-1`` before
    answering anything would have the first accepted answer land on top of it. Skipping
    past an id already held keeps ``answer``'s write additive, which is what every
    caller of this engine assumes when it reads ``record_id`` back.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="seeded by hand")
    engine.ask("q-1", content="answered", state=QuestionState.OPEN)

    outcome = await engine.answer("q-1", accept=True)

    assert outcome.record_id != "rec-1"
    seeded = await engine.belief("rec-1")
    assert seeded is not None
    assert seeded.content == "seeded by hand"


async def test_a_correction_never_lands_on_the_id_it_just_retired() -> None:
    """ADR-0045 §4's id rule, read one implementation over.

    A supersession there writes the correction "as a *new* record, at a freshly-minted
    unique id … it no longer borrows ``T``'s id", and the requirement is that the minted
    id is absent from the store with "the retained target ``T`` included" — because §4
    step 1 keeps the target: "``T`` stays on disk with a closed window — retained, off
    the read path".

    **This engine has no windows, and that is exactly why the rule needs stating here.**
    Retiring removes the record outright, so an absence check alone is satisfied by the
    id that was just freed, and the correction lands on the identity of the belief it
    overturned. A consumer reading ``record_id`` back would then be told the new belief
    *is* the old one, which is the confusion §4's "no longer borrows" clause exists to
    prevent.
    """
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the user works from Madrid")
    engine.ask(
        "q-1",
        content="the user works from Lisbon",
        state=QuestionState.OPEN,
        retires=(engine.retirement("rec-1", content="the user works from Madrid"),),
    )

    outcome = await engine.answer("q-1", accept=True)

    assert outcome.record_id != "rec-1", "the correction is a new record, not the old id"
    assert await engine.belief("rec-1") is None
    assert outcome.record_id is not None
    written = await engine.belief(outcome.record_id)
    assert written is not None
    assert written.content == "the user works from Lisbon"


async def test_an_id_another_open_question_calls_gone_is_never_handed_to_a_new_belief() -> None:
    """The case only a record of the past catches, and the reason the reservation is one.

    A question that names an unresolved retirement has already told the user that id is
    "no longer held, so accepting would not touch it" (ADR-0045 §6, ADR-0189 §4). If a
    *different* answer then mints that id, the first question's promise is retrospectively
    false: answering it retires a belief that did not exist when it was asked, and ADR-0078
    §8's exact scope is breached by an ordering rather than by a scope.

    Nothing about the store at mint time can see this coming — the id is absent from it,
    which is exactly why the question called it gone. Adversarial review found it on this
    lane's round 4, after two narrower repairs to the present state had each left the next
    case open.
    """
    engine = FakeAssistantEngine()
    engine.ask(
        "q-gone",
        content="a question about something already retired",
        state=QuestionState.OPEN,
        retires=(engine.retirement("rec-1"),),
    )
    engine.ask("q-new", content="an unrelated correction", state=QuestionState.OPEN)

    written = await engine.answer("q-new", accept=True)
    assert written.record_id is not None
    assert written.record_id != "rec-1", "the id a live question calls gone is spoken for"

    await engine.answer("q-gone", accept=True)

    survivor = await engine.belief(written.record_id)
    assert survivor is not None, "answering the other question touched nothing of it"
    assert survivor.content == "an unrelated correction"


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


# --- ADR-0235 §2, ADR-0193 §2: the fake records before it settles ------------


async def test_a_trail_that_refuses_the_answer_leaves_the_park_answerable() -> None:
    """The order ADR-0193 §2 fixes, held on the canonical fake (ADR-0235 §2).

    The answer is recorded **before** the park is evicted, which is what the
    concrete engine does — its runner records the resolving decision inside the
    critical section that then replaces the park with its settled record. A fake
    that settled first would, on a trail refusing the write, hand back a token that
    **restates an execution** no recorded answer authorised: a state no conforming
    hub can be in, and precisely the one a consumer's own retry logic would be
    written against.

    Arranged by seeding the id the fake mints for the answer, so ``record`` refuses
    it as a duplicate — a refusal the operation cannot have caused, which is the
    shape that separates "the write failed" from "the act was refused".
    """
    engine = FakeAssistantEngine()
    binding = _binding()
    confirmed = PermissionDecision.from_request(
        ActionRequest(
            tool=_TRANSMITTING_TOOL,
            parameters={"to": "Alice@Example.ORG", "body": "hello"},
            egress_binding=binding,
        ),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it discloses off-device"),
        id="d-confirm",
        decided_at=_RECIPIENT_AT,
    )
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("park-1", confirmed)
    parked = engine.park("park-1", egress=binding)
    await engine.trail.record(
        confirmed.model_copy(
            update={
                "id": "decision-park-1-answer",
                "ruling": PermissionRuling(outcome=PermissionOutcome.DENY, reason="a squatter"),
                "decided_at": _RECIPIENT_AT,
                "expires_at": None,
            }
        )
    )

    with pytest.raises(DuplicateDecisionError):
        await engine.resume(
            parked.token,
            approved=True,
            timeout=timedelta(seconds=30),
            remember_recipients_until=_RECIPIENT_AT + timedelta(days=1),
        )

    assert [held.token.handle for held in await engine.pending_confirmations()] == ["park-1"]
    assert await engine.recipient_grants.export() == []

    resumed = await engine.resume(parked.token, approved=True, timeout=timedelta(seconds=30))

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is None


async def test_a_successful_act_leaves_a_reference_that_resolves() -> None:
    """The step names the decision that cleared it (ADR-0004 §7, ADR-0014 §4).

    Before ADR-0235 this fake's resume recorded no decision at all, so its
    ``approval_ref`` resolved to nothing on every path and could mislead nobody. Now
    that the establishing act records one, a reference naming a different id would be
    the dangling pointer ADR-0014 §4 exists to prevent — and it would be dangling in
    the *one* state a consumer's own recovery test can resolve, which is the state
    that would be believed.
    """
    engine = FakeAssistantEngine()
    binding = _binding()
    confirmed = PermissionDecision.from_request(
        ActionRequest(
            tool=_TRANSMITTING_TOOL,
            parameters={"to": "Alice@Example.ORG", "body": "hello"},
            egress_binding=binding,
        ),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it discloses off-device"),
        id="d-confirm",
        decided_at=_RECIPIENT_AT,
    )
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("park-1", confirmed)
    parked = engine.park("park-1", egress=binding)

    resumed = await engine.resume(
        parked.token,
        approved=True,
        timeout=timedelta(seconds=30),
        remember_recipients_until=_RECIPIENT_AT + timedelta(days=1),
    )

    assert resumed.step is not None
    cleared = resumed.step.state.step("step-1")
    assert cleared is not None
    assert cleared.approval_ref is not None
    answering = await engine.trail.get(cleared.approval_ref)
    assert answering is not None
    assert answering.resolves == confirmed.id
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None


async def test_a_declined_act_records_the_deny_the_carrier_claims() -> None:
    """ADR-0235 §2, §4: ``DECLINED`` asserts a recorded answer, so one is recorded.

    Supplied beside ``approved=False`` the argument "establishes nothing and changes
    nothing else: the answer is recorded as a ``DENY`` exactly as it is today" —
    ADR-0042 §4's guarantee — and the carrier's ``DECLINED`` is what says on the
    outcome that this happened. A fake carrying it over an empty trail would let a
    consumer's test pass against a state no conforming hub is ever in: production
    exposes an auditable settled decision there, and the double would not.

    The store is asserted empty beside it, because ``DECLINED`` is the one member
    that never reaches ``RecipientGrantStore.record`` at all.
    """
    engine = FakeAssistantEngine()
    binding = _binding()
    confirmed = PermissionDecision.from_request(
        ActionRequest(
            tool=_TRANSMITTING_TOOL,
            parameters={"to": "Alice@Example.ORG", "body": "hello"},
            egress_binding=binding,
        ),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="it discloses off-device"),
        id="d-confirm",
        decided_at=_RECIPIENT_AT,
    )
    await engine.trail.record(confirmed)
    engine.hold_confirmation_decision("park-1", confirmed)
    parked = engine.park("park-1", egress=binding)

    resumed = await engine.resume(
        parked.token,
        approved=False,
        timeout=timedelta(seconds=30),
        remember_recipients_until=_RECIPIENT_AT + timedelta(days=1),
    )

    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.DENIED
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.not_established is RecipientGrantNotEstablished.DECLINED
    answers = [row for row in await engine.trail.export() if row.resolves == confirmed.id]
    assert [row.ruling.outcome for row in answers] == [PermissionOutcome.DENY]
    assert await engine.recipient_grants.export() == []

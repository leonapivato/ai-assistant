"""Servicing the search a planner asked for (ADR-0231 §17's Lane 5).

ADR-0231 §18's representative-input tests that turn on **the servicer, the order, the
budget, the ruling or the audit field**, at the seam that owes them. The items this
module discharges are numbered in the case that takes each: **1**, **2**, **3**,
**4**'s servicing half, **4a**'s three arms, **6**, **7**'s two budget branches,
**9a**, and **12a**'s five stage arms, together with §11's servicing order, §11's
origin-fact computation and §13's Tier 1 rule.

Items **5**, **8**, **9**, **10**, **11**, **12**, **13**, **13a**, **13aa**, **13b**
and **14** are the contract's, the transport's, the searcher's and the planner's, and
were discharged by Lanes 1 to 4; **4**'s composer half is
``tests/planning/test_composer.py``'s, over the messages the provider actually
received.

**What this module is about is the loop's half of the mechanism**: that a
``WEB_SEARCH`` ask is composed, bound, ruled on and recorded in that order and no
other; that no channel opens without a recorded ``ALLOW``; that every other outcome
degrades the turn and names itself; that the search is serviced **second**, after the
one-record local file and ahead of the hop and the query, out of ADR-0226 §6's one
budget of ten; and that ADR-0226 §9's record gains one field which is a class and
carries no query, no origin and no result.

**One deviation from §18's letter, and it is pinned rather than glossed** (issue
#2111). Item 1 wants the search ``ALLOW``ed on ADR-0148 §3's route (b), and the
declaration both the production searcher and the canonical fake carry declares
``cost=UNKNOWN`` — which fires ``ThresholdActionPolicy``'s second floor beside the
disclosure one, so ``_only_the_disclosure_floor`` is false and a covering grant is
never consulted. No ``Settings`` field and no ``build_web_search_integration``
parameter offers the *"operator's configured per-call figure"* ADR-0231 §5 admits, so
the arm is unreachable as merged. :data:`_COSTED` is that configured deployment
modelled — a per-call figure declared where one is known, which is §5's own case and
**not** ADR-0231 §9's forbidden weakening: nothing is narrowed, restated or declared
``FREE`` where the figure is unknown. Every other arm here runs the production
``ThresholdActionPolicy`` over the fake's own declaration unchanged, and
:func:`test_a_covering_grant_reaches_an_allow_only_on_a_declared_cost` asserts both
rulings side by side so the gap is a **recorded** fact of this suite rather than
something the substitution hides.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_engine import (
    AT,
    CAPABILITY,
    EGRESS_SCHEMA,
    PATIENT,
    Harness,
    OneStepPlanner,
    bound_binder,
    tool,
)
from test_engine_capture import _captured, _replying

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    AuditError,
    ConnectionStoreError,
    MemoryStoreError,
    PermissionDeniedError,
)
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    BeliefBand,
    BoundAccount,
    CanonicalDestination,
    CarriedProvenance,
    CostBasis,
    CurrentContext,
    DestinationProtocol,
    Disposition,
    EgressBinding,
    EpisodicMemory,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    Provenance,
    QueryRefusal,
    ReadAsk,
    ReadKind,
    ReadRequest,
    Role,
    SearchRefusal,
    SemanticMemory,
    SpanCoverage,
    ToolCost,
    band_of,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration import LearningLoop, MemoryWriteStage
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.origin import SelectionOrigin
from ai_assistant.orchestration.reads import (
    QUERY_DISPOSITIONS,
    READ_AUDIT_EVENT,
    READ_BUDGET,
    SEARCH_DISPOSITIONS,
    SearchDisposition,
    SearchServicer,
    TurnReadAudit,
    _Reads,
    _serviced_search,
    _Union,
    service_read_request,
)
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.planning.composer import ModelBackedQueryComposer
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeContextProvider,
    FakeDeferralStore,
    FakeEgressBinder,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakePlanner,
    FakeQueryComposer,
    FakeRecipientGrantResolution,
    FakeRecipientGrants,
    FakeStreamingCompleter,
    FakeToolRegistry,
    FakeWebSearcher,
)
from ai_assistant.testing.queries import DEFAULT_COMPOSED_QUERY
from ai_assistant.testing.recipient_grants import recipient_grant
from ai_assistant.testing.searching import (
    DEFAULT_SEARCH_ORIGIN,
    DEFAULT_SEARCH_SOURCE_NAME,
    FAKE_WEB_SEARCH,
)
from ai_assistant.tools.web_search import WEB_SEARCH

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from ai_assistant.core.protocols import ActionPolicy, AuditTrail, WebSearcher
    from ai_assistant.core.types import (
        Goal,
        MemoryRecord,
        SearchOutcome,
        ShownFile,
        ToolCall,
    )
    from ai_assistant.orchestration.loop import RespondedTurn


_NOW: Final = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)

#: The word the exit's search clause turns on. It is in the provider's snippet and in
#: nothing the store holds, so a reply carrying it can only have come from the search.
_DISTINCTIVE: Final = "quinoa-flavoured stroopwafel"

#: One result, shaped as ADR-0231 §10 shapes a content — a title, an address and a
#: snippet, one per line — with the word in the snippet.
_RESULT: Final = (
    f"Torre dos Clérigos\nhttps://example.com/clerigos\nA tower, over a {_DISTINCTIVE}."
)

#: The utterance every case's turn runs on unless it needs another.
_ASK: Final = "what is that bell tower in Porto"

#: A span in the *supply* that must never reach the composer or the searcher —
#: ADR-0231 §18's tests 4 and 4a assert its absence at each of the two seams.
_SUPPLY_SPAN: Final = "the account number is 55-40-119"

#: The connected account the fake searcher's origin is registered against.
_ACCOUNT: Final = BoundAccount(identity="search@example.com", reference="search-account")

#: See this module's docstring and issue #2111: the declaration ADR-0231 §5 gives a
#: deployment that knows its per-call figure. Nothing else about it moves, so every
#: safety field the policy rules on is the merged one.
_COSTED: Final = FAKE_WEB_SEARCH.model_copy(
    update={"cost": ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.005"), currency="USD")}
)

#: The operation a revising case runs on. ADR-0228 §2(a) admits a second planner call
#: only where the turn's operation declares a planning budget.
_REVISING: Final = ConversationalOperation.CONVERSE


def _clock() -> datetime:
    return _NOW


# --------------------------------------------------------------------------- #
# Records and requests                                                         #
# --------------------------------------------------------------------------- #


def _belief(record_id: str, content: str) -> SemanticMemory:
    """A belief the turn's own retrieval selects."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        placement=Placement(),
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_NOW),
    )


def _stamped_episode(record_id: str = "episode-tainted") -> EpisodicMemory:
    """A captured turn ADR-0223 §1 stamped from a supply that held a search result."""
    return EpisodicMemory(
        id=record_id,
        content="we looked that up together",
        occurred_at=_NOW,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=_NOW,
            derived_from_external=True,
        ),
    )


def _search() -> ReadRequest:
    """A request asking for a search and nothing else (ADR-0231 §1)."""
    return ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH),))


def ActionPlanFor(*, read_request: ReadRequest | None = None) -> ActionPlan:  # noqa: N802 — names the value it builds
    """The revision a two-plan case scripts, over this module's one goal.

    ADR-0228 §1: a revision carries the same ``goal_id`` as the plan it replaces, and
    it is the *plan* the planner returns on its second call rather than a knob on the
    servicer.

    Args:
        read_request: What the second plan asks for, or ``None`` where it settles.

    Returns:
        The plan.
    """
    return ActionPlan(
        id="plan-2",
        goal_id="goal-1",
        steps=(),
        created_at=_NOW,
        rationale="answered over the wider supply",
        read_request=read_request,
    )


def _search_and_query(text: str) -> ReadRequest:
    """A search **and** a sighted query, with the query listed first.

    The order in ``asks`` is deliberately the reverse of the servicing order ADR-0231
    §11 fixes, so an implementation following the tuple rather than §11 fails.
    """
    return ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text),
            ReadAsk(kind=ReadKind.WEB_SEARCH),
        )
    )


# --------------------------------------------------------------------------- #
# The seam, and the loop over it                                               #
# --------------------------------------------------------------------------- #


def _grant(*, at: datetime = _NOW) -> Any:
    """A standing recipient grant covering the fake searcher's origin and account.

    ADR-0193 §3's route (b) subject: the declaration by value, the connected account by
    value, and the canonical destination set the binding derives — the HTTPS origin and
    the account the call is made to. A window around this module's clock, because
    ADR-0193 §6 refuses an `ALLOW` sourced from a grant that was not live when the
    ruling was made and the trail checks it independently of the policy.
    """
    return recipient_grant(
        CanonicalDestination(
            protocol=DestinationProtocol.HTTPS, canonical=f"{DEFAULT_SEARCH_ORIGIN}:443"
        ),
        CanonicalDestination(account=_ACCOUNT),
        grant_id="g-search",
        tool=_COSTED,
        account=_ACCOUNT,
        decided_at=at - timedelta(days=1),
        expires_at=at + timedelta(days=30),
    )


class _CostedSearcher:
    """``FakeWebSearcher`` in a deployment that declared its per-call figure.

    See this module's docstring and issue #2111. It rewrites **one field of one
    declaration** — the cost — and delegates every member otherwise, so what the
    policy rules on and what the seam is registered against are the configured
    deployment ADR-0231 §5 describes. `search` reads its script off
    ``call.request.parameters["query"]``, which this leaves untouched.
    """

    def __init__(self, inner: FakeWebSearcher) -> None:
        self.inner = inner

    @property
    def name(self) -> str:
        """The configured source this searcher serves."""
        return self.inner.name

    async def request(self, query: str, /) -> ActionRequest | None:
        """Propose the search, under the costed declaration."""
        proposed = await self.inner.request(query)
        return None if proposed is None else proposed.model_copy(update={"tool": _COSTED})

    async def search(self, call: ToolCall, /) -> SearchOutcome:
        """Perform the authorised search."""
        return await self.inner.search(call)


def _binder(*, definition: Any = _COSTED) -> FakeEgressBinder:
    """A binding seam holding the search declaration against a connected account."""
    binder = FakeEgressBinder()
    binder.register_egress(definition, reference=_ACCOUNT.reference, identity=_ACCOUNT.identity)
    return binder


def _servicer(  # noqa: PLR0913 — one knob per contract ADR-0231 §6 names; that is what this is
    *,
    composer: Any = None,
    searcher: WebSearcher | None = None,
    binder: FakeEgressBinder | None = None,
    policy: ActionPolicy | None = None,
    trail: AuditTrail | None = None,
    granted: bool = False,
    at: datetime = _NOW,
) -> SearchServicer:
    """A servicer over canonical fakes, granted or not.

    ``granted`` is the one knob that decides the ruling: with it, a standing recipient
    grant covers the origin and the production ``ThresholdActionPolicy`` reaches
    ADR-0148 §3's route (b); without it the store is empty and every ruling is the
    ``CONFIRM`` ADR-0231 §9 says every deployment reads today.
    """
    grant = _grant(at=at)
    ids = itertools.count(1)
    return SearchServicer(
        composer=FakeQueryComposer() if composer is None else composer,
        searcher=_CostedSearcher(FakeWebSearcher()) if searcher is None else searcher,
        binder=_binder() if binder is None else binder,
        policy=(
            ThresholdActionPolicy(
                grants=FakeRecipientGrants([grant] if granted else [], now=lambda: at)
            )
            if policy is None
            else policy
        ),
        trail=(
            FakeAuditTrail(recipient_grants=FakeRecipientGrantResolution([grant]))
            if trail is None
            else trail
        ),
        now=lambda: at,
        id_factory=lambda: f"d-{next(ids)}",
    )


def _loop(
    *,
    planner: Any = None,
    search: SearchServicer | None = None,
    memory: FakeMemoryStore | None = None,
) -> LearningLoop:
    """A loop over canonical fakes, with the servicer a case supplies (or none).

    The episodic supplement is **off**, for ``test_loop_fetch.py``'s reason: a case's
    supply is then exactly the beliefs it seeded, so "what the servicing added" is a
    reading rather than a subtraction.
    """
    store = memory if memory is not None else FakeMemoryStore(now=_clock)
    return LearningLoop(
        context=FakeContextProvider(),
        memory=store,
        writes=MemoryWriteStage(
            writer=FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(), now=_clock),
            deferrals=FakeDeferralStore(now=_clock),
        ),
        planner=planner if planner is not None else FakePlanner(now=_clock),
        registry=FakeToolRegistry(),
        feedback=FakeFeedbackProcessor(),
        search=search,
        retrieval_limit=30,
        episodic_limit=0,
        now=_clock,
        id_factory=lambda: "goal-1",
    )


def _bounded() -> BoundedAudienceSupply:
    """The filter ``converse`` supplies: evaluates, and subtracts nothing."""
    return BoundedAudienceSupply(speakable_attested_sources=frozenset())


def _record(captured: Sequence[MutableMapping[str, Any]]) -> Mapping[str, Any]:
    """The one audit record ADR-0226 §9 obliges this turn to have written."""
    [only] = [event for event in captured if event["event"] == READ_AUDIT_EVENT]
    return only


def _serviced(captured: Sequence[MutableMapping[str, Any]], ordinal: int = 0) -> Mapping[str, Any]:
    """One servicing's entry in this turn's record (ADR-0228 §9)."""
    return _record(captured)["servicings"][ordinal]  # type: ignore[no-any-return]


def _contents(memories: Sequence[MemoryRecord]) -> str:
    """Every record's content run together, for an "appears nowhere" assertion."""
    return "\n".join(record.content for record in memories)


async def _prompt_over(responded: RespondedTurn) -> str:
    """The user-turn prompt the **production** renderer assembles for one turn.

    ADR-0227 §7's fidelity rule forbids substituting "the renderer whose output the
    assertion is about" and permits a fake ``ModelProvider``, so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles the prompt
    and the fake merely records it.
    """
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(
        turn=responded.turn, step=None, undriven=(), hop_reached=responded.hop_reached
    )
    [call] = model.calls
    return next(one.content for one in call.messages if one.role is Role.USER)


# --------------------------------------------------------------------------- #
# §18 item 1: the exit's search clause, first half                             #
# --------------------------------------------------------------------------- #


async def test_a_turn_whose_supply_knows_nothing_answers_from_the_search() -> None:
    """§18 item 1: the reply carries the word, and it came from the provider.

    "A turn whose supply holds nothing about the subject; a connected search account
    whose origin a seeded ``RecipientGrant`` covers; a fake searcher returning one
    result whose snippet carries a distinctive word; the planner emits a
    ``WEB_SEARCH`` ask; the search is ``ALLOW``ed on route (b); one record is minted;
    and **the reply carries the word**."

    **Everything on the path is the production article but the model, the planner and
    the provider**: the real servicer, the production ``ThresholdActionPolicy`` over a
    real ``RecipientGrants`` holding one seeded grant, the production
    ``EgressBinder`` contract's canonical fake, and ``composing.py``'s own renderer.
    A ``FakeModelProvider`` reads the assembled prompt and a ``FakePlanner`` emits the
    ask, because neither a completion nor a model's choice to search is what this case
    is about.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "we talked about Porto last week"))
    planner = FakePlanner(now=_clock, read_request=_search())
    searcher = FakeWebSearcher(results=(_RESULT,))

    responded = await _loop(
        planner=planner,
        memory=memory,
        search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
    ).respond(_ASK, narrow=_bounded())

    assert _DISTINCTIVE not in _contents(planner.calls[0][2]), (
        "the supply the planner saw held nothing about the subject"
    )
    minted = [record for record in responded.turn.memories if _DISTINCTIVE in record.content]
    assert len(minted) == 1, "the search minted exactly one record (ADR-0231 §10)"
    assert _DISTINCTIVE in await _prompt_over(responded), (
        "the production renderer put the provider's own words in front of the model"
    )
    assert len(searcher.searched) == 1, "and exactly one authorised call was made"


async def test_the_record_the_search_minted_is_the_one_adr_0231_s10_describes() -> None:
    """§10's shape, over the record that reached a turn's supply through the servicer.

    The externality mark is the milestone's control rather than its cost (§10), so the
    fields it rests on are asserted where the record actually enters a supply: a
    ``SEMANTIC`` record in the ``ATTESTED`` band, ``EXTERNAL``-sourced, attested to
    the searcher's own source instance, carrying no evidence, and carrying **no**
    instant this system read — ``reported_at`` is the provider's own (ADR-0092 §3).
    """
    searcher = FakeWebSearcher(results=(_RESULT,))
    planner = FakePlanner(now=_clock, read_request=_search())

    responded = await _loop(
        planner=planner, search=_servicer(searcher=_CostedSearcher(searcher), granted=True)
    ).respond(_ASK, narrow=_bounded())

    [record] = [one for one in responded.turn.memories if _DISTINCTIVE in one.content]
    assert isinstance(record, SemanticMemory), "ADR-0231 §10: SEMANTIC records"
    assert record.provenance.source is MemorySource.EXTERNAL
    assert band_of(record.provenance.source) is BeliefBand.ATTESTED
    assert rests_on_recorded_external_content(record.provenance) is True
    assert record.provenance.evidence == ()
    attestation = record.provenance.attestation
    assert attestation is not None
    assert attestation.reported_by == DEFAULT_SEARCH_SOURCE_NAME, "the source, never a vendor"
    assert DEFAULT_SEARCH_ORIGIN not in repr(record), "no origin is on the record"


# --------------------------------------------------------------------------- #
# §18 item 2: that conversation's egress asks first thereafter                 #
# --------------------------------------------------------------------------- #


async def test_a_turn_that_searched_leaves_a_supply_that_carries_the_origin_fact() -> None:
    """§18 item 2's first link: what the minted record does to the turn's own origin.

    ADR-0223 §1 stamps the captured episode from the turn's **final** supply and
    ADR-0181 §4 computes the egress seam's fact over the same selection, so the whole
    of the mechanism §12 calls "#1908's exit sentence" rests on the minted record
    satisfying ``rests_on_recorded_external_content``. Computed here by the production
    ``SelectionOrigin.over`` over the supply a real servicing produced, rather than
    asserted of a hand-built record.
    """
    planner = FakePlanner(now=_clock, read_request=_search())

    responded = await _loop(
        planner=planner,
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
        ),
    ).respond(_ASK, narrow=_bounded())

    before = SelectionOrigin.over(planner.calls[0][2])
    after = SelectionOrigin.over(responded.turn.memories)
    assert before.planned_with_external_content is False, "nothing external before the search"
    assert after.planned_with_external_content is True, "and the minted record carries it"


async def test_the_same_grant_that_allowed_the_search_confirms_the_conversations_next_egress() -> (
    None
):
    """§18 item 2: "the assertion is that the grant did not cover it".

    "The same conversation's next turn plans a step at the egress seam; the binding
    carries ``planned_with_external_content``; the same seeded grant covers the same
    destination set; and the ruling is **``CONFIRM`` and not ``ALLOW``**, asserted
    through the production ``ThresholdActionPolicy`` with a real ``RecipientGrants``."

    **One grant, one destination set, one policy, two requests** — and the only thing
    that differs between them is the fact ADR-0223 §1's stamp carries into the second
    turn's supply. That is what makes this ADR-0193 §4 with ADR-0223 §1 behind it
    rather than a rule ADR-0231 added: the grant is live, covering and unchanged, and
    ADR-0181 §5's floor admits no ``ALLOW`` above it.

    The end-to-end half — that a *subsequent* turn's egress **step** is a confirmation
    rather than an allow — is
    ``test_engine_capture_origin.py::test_a_turn_that_searched_stamps_its_capture_and_the_next_turn_asks``,
    over the engine and the stamped episode; this is the ruling it turns on, isolated
    so the cause is visible.
    """
    grant = _grant()
    policy = ThresholdActionPolicy(grants=FakeRecipientGrants([grant], now=_clock))
    binder = _binder()
    proposed = await _CostedSearcher(FakeWebSearcher()).request("porto bell tower")
    assert proposed is not None

    async def _ruled(*, external: bool) -> PermissionRuling:
        bound = await binder.bind(
            proposed.tool,
            parameters=proposed.parameters,
            provenance=CarriedProvenance(
                spans={},
                planned_with_external_content=external,
                coverage=SpanCoverage.NOT_COVERED,
            ),
        )
        assert bound is not None
        return await policy.decide(
            ActionRequest(
                tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
            )
        )

    clean = await _ruled(external=False)
    tainted = await _ruled(external=True)

    assert clean.outcome is PermissionOutcome.ALLOW
    assert clean.authorised_by == "g-search", "the grant covered the first call"
    assert tainted.outcome is PermissionOutcome.CONFIRM, "ADR-0193 §4: and not the second"
    assert tainted.authorised_by is None, "no grant sourced it"


# --------------------------------------------------------------------------- #
# §18 item 3: a second search in the same turn is refused                      #
# --------------------------------------------------------------------------- #


async def test_a_second_search_in_the_same_turn_opens_no_channel() -> None:
    """§18 item 3, over a searcher that fails the case if ``search`` is called twice.

    "A turn whose first servicing minted a result and whose revision emits a second
    ``WEB_SEARCH`` ask: the second request's binding carries the origin fact, the
    ruling is not ``ALLOW``, the searcher's ``search`` is **never reached**, and §13's
    disposition records the ``CONFIRM``."

    Nothing ADR-0231 adds does this. §12: "once a minted record is in a turn's supply
    the binding of any later request in that turn carries
    ``planned_with_external_content``, ADR-0193 §4 admits no grant on such a request
    and ADR-0181 §5's floor admits no ``ALLOW`` but a decision of the user about that
    request". The grant is the same one that allowed the first search, live and
    covering throughout — asserted by the first servicing having yielded.
    """
    searcher = FakeWebSearcher(results=(_RESULT,))
    planner = FakePlanner(
        now=_clock,
        read_request=_search(),
        revision=ActionPlanFor(read_request=_search()),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner,
            search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
        ).respond(_ASK, narrow=_bounded(), operation=_REVISING)

    assert len(planner.calls) == 2, "the turn revised (ADR-0228 §2)"
    assert len(searcher.searched) == 1, "`search` was reached on the first servicing alone"
    assert _serviced(captured, 0)["disposition"] is None, "the first yielded"
    assert _serviced(captured, 1)["disposition"] == SearchDisposition.RULING_CONFIRM.value
    assert _serviced(captured, 1)["new"] == 0, "and the second added nothing"
    minted = [one for one in responded.turn.memories if _DISTINCTIVE in one.content]
    assert len(minted) == 1, "one record from one search"


# --------------------------------------------------------------------------- #
# §18 item 4's servicing half, and item 4a's three arms                        #
# --------------------------------------------------------------------------- #


async def test_the_composers_model_is_shown_the_utterance_and_no_supply_span() -> None:
    """§18 item 4, the servicing half — over the **concrete** composer's own provider.

    "A servicing test in which the supply holds a record with a distinctive span and
    the messages the composer's ``ModelProvider`` fake received are asserted to contain
    the utterance and **no byte of that span**, no tail, no listing and no rationale."

    The composer's own half — that the member takes one positional parameter — is the
    conformance suite's, and what it was *handed* is
    ``tests/planning/test_composer.py``'s. What is new here is the **supply site**
    §4's argument rests on: the servicer holds the records and has a composer to hand
    them to, and this is the call where it does not.
    """
    model = FakeModelProvider(json.dumps({"query": "porto bell tower"}))
    audit = TurnReadAudit()

    await service_read_request(
        FakeMemoryStore(now=_clock),
        _search(),
        supply=(_belief("belief-1", _SUPPLY_SPAN),),
        fetcher=None,
        listing=None,
        search=_servicer(composer=ModelBackedQueryComposer(model), granted=True),
        utterance=_ASK,
        audit=audit,
    )

    assert model.call_count == 1
    shown = "\n".join(one.content for one in model.last_messages)
    assert _ASK in shown, "the turn's own words reached the composing seam"
    assert _SUPPLY_SPAN not in shown, "and no byte of the supply did (ADR-0231 §4)"
    assert "belief-1" not in shown, "no identifier either"


async def test_the_searcher_receives_the_composers_output_byte_for_byte() -> None:
    """§18 arm 4a, first arm: byte-identical and not merely containing.

    "The string ``request`` receives is asserted **byte-identical** to the ``query``
    the composer returned on that turn — not merely containing it, since an
    implementation that appended a site filter or stripped punctuation would pass a
    containment assertion."

    §11's tenth clause is the one this is about: "the only value
    ``WebSearcher.request`` is ever passed is the ``query`` of a ``QueryOutcome`` the
    ``QueryComposer`` returned in that same servicing, byte for byte". The composed
    query is deliberately awkward — leading and trailing space, mixed case,
    punctuation — so an implementation that normalised anything fails.
    """
    composed = "  Torre dos Clérigos — HEIGHT? (in metres)  "
    composer = FakeQueryComposer({_ASK: composed})
    inner = FakeWebSearcher()

    await service_read_request(
        FakeMemoryStore(now=_clock),
        _search(),
        supply=(),
        fetcher=None,
        listing=None,
        search=_servicer(composer=composer, searcher=_CostedSearcher(inner), granted=True),
        utterance=_ASK,
        audit=TurnReadAudit(),
    )

    assert composer.utterances == [_ASK], "the composer saw the turn's own words"
    assert inner.requested == [composed], "and the searcher saw exactly what it wrote"


async def test_a_refused_composition_reaches_the_searcher_not_at_all() -> None:
    """§18 arm 4a, second arm: no fallback of any kind.

    "A servicing whose composition returned a ``QueryRefusal`` reaches ``request``
    **not at all**, which fails an implementation that falls back to the utterance, to
    a supply value or to a cached query when a composition refuses."

    §11: "where the composition returned a ``QueryRefusal`` there is **no request at
    all** — no ruling is sought, no channel is opened, and §13's disposition names the
    refusal".
    """
    inner = FakeWebSearcher()
    trail = FakeAuditTrail()
    audit = TurnReadAudit()

    await service_read_request(
        FakeMemoryStore(now=_clock),
        _search(),
        supply=(_belief("belief-1", _SUPPLY_SPAN),),
        fetcher=None,
        listing=None,
        search=_servicer(
            composer=FakeQueryComposer(refusals={_ASK: QueryRefusal.DECLINED}),
            searcher=_CostedSearcher(inner),
            trail=trail,
            granted=True,
        ),
        utterance=_ASK,
        audit=audit,
    )

    assert inner.requested == [], "no request was proposed"
    assert inner.searched == [], "and no channel was opened"
    assert await trail.recent() == [], "no ruling was sought, so nothing was recorded"
    assert audit.servicings[-1].disposition is SearchDisposition.COMPOSER_DECLINED


async def test_no_span_of_the_supply_reaches_any_value_the_searcher_received() -> None:
    """§18 arm 4a, third arm: the seam at which no signature can decide it.

    "A turn whose supply carries a record with a distinctive span asserts that span
    appears in **no** value ``request`` received." §11 is explicit that this seam's
    guarantee is weaker than §3's — "at ``WebSearcher.request`` the parameter **is**
    the query, so no type distinguishes text a composer produced from text a caller
    assembled" — and names this arm as one of the three things that carry it instead.
    """
    inner = FakeWebSearcher()

    await service_read_request(
        FakeMemoryStore(now=_clock),
        _search(),
        supply=(_belief("belief-1", _SUPPLY_SPAN), _belief("belief-2", "and another thing")),
        fetcher=None,
        listing=None,
        search=_servicer(searcher=_CostedSearcher(inner), granted=True),
        utterance=_ASK,
        audit=TurnReadAudit(),
    )

    assert inner.requested != [], "the searcher was reached at all"
    assert all(_SUPPLY_SPAN not in received for received in inner.requested)
    assert all("belief-1" not in received for received in inner.requested)


# --------------------------------------------------------------------------- #
# §18 item 6: a non-ALLOW degrades the turn and the prompt does not move        #
# --------------------------------------------------------------------------- #


async def test_a_refused_search_degrades_the_turn_and_moves_no_byte_of_the_prompt() -> None:
    """§18 item 6, and ADR-0226 §5's posture unchanged for this kind.

    "With no grant seeded: the turn completes, the reply is composed from the supply
    planning saw, no record enters the fourth group, the read budget is unspent, the
    assembled prompt is **byte-identical** to the same turn with no ``WEB_SEARCH``
    ask, and §13's disposition names the ``CONFIRM``."

    The byte-identity is ADR-0231 §9's third clause asserted rather than argued: "the
    composing stage is told nothing new, and the assembled prompt on a turn whose
    search was refused is byte-identical to what it would be had the planner asked for
    nothing". A turn that *told* the model its search was refused would fail here, and
    §19 defers that message by name.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "Porto has a river"))
    searcher = FakeWebSearcher(results=(_RESULT,))

    with structlog.testing.capture_logs() as captured:
        refused = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            memory=memory,
            search=_servicer(searcher=_CostedSearcher(searcher), granted=False),
        ).respond(_ASK, narrow=_bounded())

    silent = await _loop(planner=FakePlanner(now=_clock), memory=memory, search=None).respond(
        _ASK, narrow=_bounded()
    )

    entry = _serviced(captured)
    assert entry["disposition"] == SearchDisposition.RULING_CONFIRM.value
    assert entry["new"] == 0, "the budget is unspent"
    assert entry["returned"] == 0, "and nothing was returned to be discarded"
    assert entry["failed"] is False, "a decline is not a failure (ADR-0226 §5)"
    assert searcher.searched == [], "no channel was opened"
    assert _DISTINCTIVE not in _contents(refused.turn.memories), "nothing entered the supply"
    assert await _prompt_over(refused) == await _prompt_over(silent), (
        "ADR-0231 §9: byte-identical to the same turn with no ask"
    )


# --------------------------------------------------------------------------- #
# §18 item 7: the two budget branches, driven at the servicer                  #
# --------------------------------------------------------------------------- #


async def test_with_no_slot_remaining_nothing_is_composed_and_nothing_is_ruled_on() -> None:
    """§18 item 7's first branch, driven directly over the servicer.

    "With no slot remaining: no query is composed, no ruling is sought, ``search`` is
    never reached, and the disposition is ``NO_BUDGET``."

    **Not written as a production-turn scenario**, because §11's order makes the
    premise one no turn can have: the search is serviced second, only the one-record
    local file precedes it, and at least nine of ten slots therefore always remain
    against a cap of three. §18 says so in terms — "an implementation cannot be asked
    to satisfy a premise this ADR's own order forbids" — so the remaining count is
    supplied and the branch is driven where it lives.
    """
    composer = FakeQueryComposer()
    inner = FakeWebSearcher()
    trail = FakeAuditTrail()

    found = await _servicer(
        composer=composer, searcher=_CostedSearcher(inner), trail=trail, granted=True
    ).service(_ASK, remaining=0, external=False)

    assert found.disposition is SearchDisposition.NO_BUDGET
    assert found.records == ()
    assert composer.utterances == [], "no query was composed, so no model call was paid for"
    assert inner.requested == [], "no request was proposed"
    assert inner.searched == [], "and no channel was opened"
    assert await trail.recent() == [], "and no ruling was sought"


async def test_the_budget_admits_the_records_that_fit_and_no_more() -> None:
    """§18 item 7's second branch, over the union every other kind draws on.

    "With fewer slots remaining than the search returned results: exactly the slots
    that remain are admitted, in the order §10 minted them, the rest are not, and the
    fourth group is no larger than ADR-0226 §6 admits."

    Driven over :func:`~ai_assistant.orchestration.reads._serviced_search` with a
    union whose budget a case chose, for the branch above's reason and by §18's own
    instruction. It is the forward-compatibility guard §11 states in terms, and the
    lane that makes it reachable is the one that reorders the kinds or raises the
    file's cap.
    """
    results = ("first result", "second result", "third result")
    union = _Union(held=set(), budget=2)
    truncated: list[ReadKind] = []

    disposition = await _serviced_search(
        _servicer(searcher=_CostedSearcher(FakeWebSearcher(results=results)), granted=True),
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        _ASK,
        union=union,
        supply=(),
        reads=_Reads(),
        truncated=truncated,
    )

    assert disposition is None, "the search yielded, so §13's field stays empty"
    assert [record.content for record in union.admitted] == list(results[:2]), (
        "exactly the slots that remain, in the order §10 minted them"
    )
    assert union.remaining == 0
    assert truncated == [ReadKind.WEB_SEARCH], "and the audit says the budget cut it"


# --------------------------------------------------------------------------- #
# §18 item 9a: the vocabularies are complete and the mapping is total          #
# --------------------------------------------------------------------------- #


def test_the_three_vocabularies_are_closed_at_the_sizes_adr_0231_fixes() -> None:
    """§18 arm 9a's first half, asserted over the enums themselves.

    "``QueryRefusal`` holds exactly its four members, ``SearchRefusal`` exactly its
    six, and ``SearchDisposition`` exactly its fifteen." Over the enums rather than
    over a list of names, so a member added without an arm below fails here first.
    """
    assert len(QueryRefusal) == 4
    assert len(SearchRefusal) == 6
    assert len(SearchDisposition) == 15
    assert all(member.value == member.name.lower() for member in SearchDisposition), (
        "each valued by its lower-cased name, as every closed vocabulary here is"
    )


def test_every_refusal_maps_to_a_distinct_disposition_and_no_result_maps_to_none() -> None:
    """§18 arm 9a's second half: total, injective, and one deliberate absence.

    "Every ``QueryRefusal`` member and every ``SearchRefusal`` member except
    ``NO_RESULT`` maps to a distinct ``SearchDisposition`` member, and ``NO_RESULT``
    maps to none." §13's injectivity is what keeps the field useful: "an unconnected
    account is a provisioning fact, an ungranted recipient is a user act waiting to
    happen, a ``DENY`` is a policy the operator set, a spend refusal is a ceiling, a
    transport failure is an outage" — collapsing any two would make the field useless
    at exactly the moment someone reads it.
    """
    assert set(QUERY_DISPOSITIONS) == set(QueryRefusal), "total over the composing vocabulary"
    assert set(SEARCH_DISPOSITIONS) == set(SearchRefusal) - {SearchRefusal.NO_RESULT}
    assert SearchRefusal.NO_RESULT not in SEARCH_DISPOSITIONS, (
        "a completed servicing with a zero count is not a disposition (§13)"
    )
    carried = [*QUERY_DISPOSITIONS.values(), *SEARCH_DISPOSITIONS.values()]
    assert len(set(carried)) == len(carried), "injective across both vocabularies"
    assert set(SearchDisposition) - set(carried) == {
        SearchDisposition.NOT_CONFIGURED,
        SearchDisposition.NO_BUDGET,
        SearchDisposition.BINDING_FAILED,
        SearchDisposition.RULING_CONFIRM,
        SearchDisposition.RULING_DENY,
        SearchDisposition.RULING_UNAVAILABLE,
    }, "and the six members no refusal vocabulary supplies are the servicer's own stages"


# --------------------------------------------------------------------------- #
# §18 item 12a: a refusal at any stage degrades the turn and names itself      #
# --------------------------------------------------------------------------- #


class _RaisingPolicy:
    """An ``ActionPolicy`` whose ``decide`` raises, for §9's "policy that raised"."""

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        """Raise rather than rule.

        Args:
            request: The request that will not be ruled on.

        Raises:
            PermissionDeniedError: Always.
        """
        msg = f"this policy cannot rule on {request.tool.id!r}"
        raise PermissionDeniedError(msg)

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        """Unreached on this path (ADR-0231 §9: a search parks nothing).

        Args:
            confirmed: The recorded question.
            approved: The user's answer.

        Raises:
            PermissionDeniedError: Always.
        """
        msg = f"no resolution is available for {confirmed.id!r} (approved={approved})"
        raise PermissionDeniedError(msg)


class _LosingTrail:
    """A trail that accepts the append and cannot hand the record back.

    §9 declines on "an ``AuditTrail`` that could not record the decision", and a store
    that keys the row and loses it is one — the failure ``StepRunner._record``'s own
    read-back exists to catch, at a second call site. Every other member delegates, so
    what this models is one store fault rather than a different contract.
    """

    def __init__(self) -> None:
        self.inner = FakeAuditTrail()

    async def record(self, decision: PermissionDecision) -> str:
        """Accept the append and drop it.

        Args:
            decision: What was decided.

        Returns:
            The id the caller will not be able to read back.
        """
        return decision.id

    def __getattr__(self, name: str) -> Any:
        """Delegate every other member to the fake this wraps."""
        return getattr(self.inner, name)


async def _disposition_of(
    *,
    binder: FakeEgressBinder | None = None,
    policy: ActionPolicy | None = None,
    trail: AuditTrail | None = None,
    searcher: WebSearcher | None = None,
) -> Mapping[str, Any]:
    """Run one turn whose search fails at one stage, and read §9's record back.

    Returns:
        This turn's one servicing entry, as ADR-0226 §9's event carries it.
    """
    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(
                binder=binder, policy=policy, trail=trail, searcher=searcher, granted=True
            ),
        ).respond(_ASK, narrow=_bounded())
    assert responded.turn is not None, "the turn completed (ADR-0226 §5)"
    assert _DISTINCTIVE not in _contents(responded.turn.memories), "and nothing was minted"
    return _serviced(captured)


async def test_a_binder_that_refuses_names_the_binding_stage() -> None:
    """§18 arm 12a's binder arm, over ADR-0152 §1's own registry-original refusal.

    The seam holds the merged declaration and the request carries the costed one, so
    the comparison ADR-0152 §1 makes refuses the call — a **production** refusal path
    rather than a stub that raises. §13: ``BINDING_FAILED`` "carries no message, no
    exception type and no store detail".
    """
    entry = await _disposition_of(binder=_binder(definition=FAKE_WEB_SEARCH))

    assert entry["disposition"] == SearchDisposition.BINDING_FAILED.value
    assert entry["failed"] is False, "a decline is not a servicing failure"
    assert entry["new"] == 0, "and the read budget is unspent"


async def test_a_connection_record_that_cannot_be_read_names_the_binding_stage() -> None:
    """§9's third binder limb: "the connection could not be read".

    ``ConnectionStoreError`` and ``EgressBindingError`` are one disposition, which §13
    admits in terms — "two outcomes of one stage that an operator would act on
    identically may share a member" — and both are the operator's fact.
    """
    binder = _binder()
    binder.fail_next_read()

    entry = await _disposition_of(binder=binder)

    assert entry["disposition"] == SearchDisposition.BINDING_FAILED.value


async def test_a_policy_that_raises_names_the_ruling_stage() -> None:
    """§18 arm 12a's policy arm, and §13's first ``RULING_UNAVAILABLE`` limb."""
    entry = await _disposition_of(policy=_RaisingPolicy())

    assert entry["disposition"] == SearchDisposition.RULING_UNAVAILABLE.value
    assert entry["failed"] is False


async def test_a_trail_that_loses_the_decision_names_the_ruling_stage() -> None:
    """§18 arm 12a's trail arm, and §13's second ``RULING_UNAVAILABLE`` limb.

    The decision the searcher's own ``InvocationLedger`` claim would be keyed on
    (ADR-0192 §1) is not in the store, so opening a channel here would be sending under
    a decision nothing holds. §9 declines instead.
    """
    entry = await _disposition_of(trail=_LosingTrail())

    assert entry["disposition"] == SearchDisposition.RULING_UNAVAILABLE.value


@pytest.mark.parametrize(
    ("refusal", "disposition"),
    [
        (SearchRefusal.SPEND_REFUSED, SearchDisposition.SPEND_REFUSED),
        (SearchRefusal.TRANSPORT_FAILED, SearchDisposition.TRANSPORT_FAILED),
        (SearchRefusal.PROVIDER_REFUSED, SearchDisposition.PROVIDER_REFUSED),
        (SearchRefusal.RESPONSE_TOO_LARGE, SearchDisposition.RESPONSE_TOO_LARGE),
        (SearchRefusal.UNATTESTED, SearchDisposition.UNATTESTED),
    ],
    ids=["spend", "transport", "provider", "oversized", "unattested"],
)
async def test_a_refusal_past_the_ruling_names_its_own_class(
    refusal: SearchRefusal, disposition: SearchDisposition
) -> None:
    """§18 arm 12a's spend and transport arms, and §13's five carried-across members.

    The gate's and the transport's own halves — that a refused admission reads no
    credential, opens no channel and appends no claim — are the searcher's and are
    Lane 3's tests. What is asserted here is the half that is this seam's: the class
    reaches §13's field as **that stage's** member and not another, for every member
    of ``SearchRefusal`` that can reach the servicer.
    """
    entry = await _disposition_of(
        searcher=_CostedSearcher(FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: refusal}))
    )

    assert entry["disposition"] == disposition.value
    assert entry["failed"] is False, "a refusal degrades the turn and never fails it"


async def test_a_search_that_reached_the_provider_and_returned_nothing_is_no_disposition() -> None:
    """§13's one deliberate absence: ``NO_RESULT`` is not a disposition.

    "A search that reached the provider and yielded nothing is a completed servicing
    whose returned count is zero, which ADR-0226 §9 already records, and calling it a
    disposition would double-count it." So the field is empty and the counts say what
    happened — which is the same shape §9 gives a hop that resolved no live record.
    """
    entry = await _disposition_of(
        searcher=_CostedSearcher(
            FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.NO_RESULT})
        )
    )

    assert entry["disposition"] is None
    assert entry["returned"] == 0
    assert entry["new"] == 0
    assert entry["failed"] is False


@pytest.mark.parametrize(
    "searcher",
    [None, _CostedSearcher(FakeWebSearcher(origin=None))],
    ids=["no_servicer_wired", "no_account_connected"],
)
async def test_a_deployment_with_no_search_account_says_so(searcher: WebSearcher | None) -> None:
    """§13's ``NOT_CONFIGURED``, by both routes to the one provisioning fact.

    A deployment that wired no servicer at all, and one whose searcher answers ``None``
    because no account is connected, are the same fact about the same stage — §13
    admits one member for "two outcomes of one stage that an operator would act on
    identically". Neither composes a query, seeks a ruling or opens a channel, so a
    deployment that connected nothing pays nothing for a planner that asks.
    """
    with structlog.testing.capture_logs() as captured:
        await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=None if searcher is None else _servicer(searcher=searcher, granted=True),
        ).respond(_ASK, narrow=_bounded())

    assert _serviced(captured)["disposition"] == SearchDisposition.NOT_CONFIGURED.value


# --------------------------------------------------------------------------- #
# §11: the servicing order, and one budget                                     #
# --------------------------------------------------------------------------- #


async def test_the_search_is_serviced_before_the_sighted_query() -> None:
    """§11's order, over a request whose ``asks`` are in the reverse of it.

    "The servicing order is: local file, then web search, then citation hop, then
    sighted query." ADR-0226 §6's decision is applied and not moved — the capped read
    ahead of the uncapped one — so the fourth group holds the minted record **before**
    the query's, and the query is asked for exactly the slots the search left.

    The request lists the query first, so an implementation following the tuple rather
    than §11 fails; and the query matches a seeded belief, so it really does have
    something to contribute.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the bell tower is in Porto"))
    planner = FakePlanner(now=_clock, read_request=_search_and_query("bell tower Porto"))

    responded = await _loop(
        planner=planner,
        memory=memory,
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
        ),
    ).respond(_ASK, narrow=_bounded())

    fourth = [record.content for record in responded.turn.memories[len(planner.calls[0][2]) :]]
    assert fourth, "the servicing contributed something"
    assert fourth[0] == _RESULT, "the search is serviced before the sighted query (§11)"


async def test_the_search_draws_slots_of_the_one_budget_and_never_a_second() -> None:
    """§11: "one budget, and the search draws at most ``search_max_results`` slots".

    "It is not a share, not a second budget, and no lane funds it by lowering
    ``RETRIEVAL_LIMIT`` or ``EPISODIC_SUPPLEMENT_LIMIT``." Asserted where a second
    budget would show: the fourth group of a turn whose search and whose query both
    contribute is never larger than ADR-0226 §6's ten.
    """
    memory = FakeMemoryStore(now=_clock)
    for ordinal in range(12):
        await memory.add(_belief(f"belief-{ordinal}", f"bell tower note {ordinal}"))
    planner = FakePlanner(now=_clock, read_request=_search_and_query("bell tower note"))

    responded = await _loop(
        planner=planner,
        memory=memory,
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT, "second", "third"))),
            granted=True,
        ),
    ).respond(_ASK, narrow=_bounded())

    fourth = responded.turn.memories[len(planner.calls[0][2]) :]
    assert len(fourth) <= READ_BUDGET, "ADR-0226 §6's ten, shared by the whole emission"
    assert [record.content for record in fourth[:3]] == [_RESULT, "second", "third"]


# --------------------------------------------------------------------------- #
# §11: the origin fact on a search request's binding                           #
# --------------------------------------------------------------------------- #


async def test_a_supply_already_holding_an_external_record_taints_the_search_request() -> None:
    """§11's origin-fact clause, over the **pre-servicing supply**.

    "The ``planned_with_external_content`` on a search request's binding is the
    disjunction of ``rests_on_recorded_external_content`` over the turn's
    pre-servicing supply and over every record this servicing has already
    contributed." So a turn whose supply already carries a stamped episode — ADR-0223
    §1's mechanism reaching a later turn of the conversation — draws a ``CONFIRM``
    under the very grant that would otherwise have allowed it, and the searcher is
    never reached.

    This is §12's second answer to #1844 stated where it is computed: the conversation
    "un-taints as the tail moves on", and until it does every search in it asks first.
    """
    inner = FakeWebSearcher(results=(_RESULT,))

    with structlog.testing.capture_logs() as captured:
        await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(searcher=_CostedSearcher(inner), granted=True),
        ).respond(_ASK, narrow=_bounded(), history=(_stamped_episode(),))

    assert _serviced(captured)["disposition"] == SearchDisposition.RULING_CONFIRM.value
    assert inner.searched == [], "no channel opened over a tainted supply (ADR-0193 §4)"


async def test_a_clean_supply_leaves_the_grant_covering() -> None:
    """The control for the case above: a wired episode is not itself a taint.

    Without it that case would pass on an implementation that stamped every request
    whose turn carried any history at all — which would make the origin fact a
    property of the tail's existence rather than of what it rests on (ADR-0181 §2).
    """
    inner = FakeWebSearcher(results=(_RESULT,))
    clean = EpisodicMemory(
        id="episode-clean",
        content="we talked about Porto",
        occurred_at=_NOW,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_NOW),
    )

    with structlog.testing.capture_logs() as captured:
        await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(searcher=_CostedSearcher(inner), granted=True),
        ).respond(_ASK, narrow=_bounded(), history=(clean,))

    assert _serviced(captured)["disposition"] is None, "the search yielded"
    assert len(inner.searched) == 1


async def test_the_binding_a_search_is_ruled_on_is_covered_by_nothing() -> None:
    """§4 and ADR-0233 §5: the coverage fact this package computes for a search.

    ADR-0233 §5 puts ``coverage`` on "the component that composed the call's
    arguments, from the membership and path character of what it supplied to the
    operations that produced them", and what this package supplied the composer's
    model call is the turn's own utterance and nothing else. §4 states the
    consequence: "the composer's model call is supplied no covered content, and its
    output is therefore not covered content either. Neither §3's second clause … nor
    its third … has a subject" — which is ADR-0233 §4's ``NOT_COVERED``.

    A turn whose supply is full of store records is used deliberately: an
    implementation reading the coverage off the *turn's* selection, as the step path
    correctly does, would answer ``MODEL_ON_EVERY_PATH`` here and fail.
    """
    trail = FakeAuditTrail(recipient_grants=FakeRecipientGrantResolution([_grant()]))
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the bell tower is in Porto"))

    await _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        memory=memory,
        search=_servicer(trail=trail, granted=True),
    ).respond(_ASK, narrow=_bounded())

    [decision] = await trail.recent()
    binding = decision.egress_binding
    assert isinstance(binding, EgressBinding), "a search request carries a whole binding"
    assert binding.coverage is SpanCoverage.NOT_COVERED
    assert binding.planned_with_external_content is False
    assert decision.step_id is None, "§6: no plan step is synthesised"
    assert decision.execution_id is None, "and no execution"


# --------------------------------------------------------------------------- #
# §13: the audit carries a class and nothing else                              #
# --------------------------------------------------------------------------- #


async def test_the_audit_carries_no_query_no_origin_and_no_result() -> None:
    """§13's Tier 1 rule, over a turn that composed, sent and minted.

    "No query text, no fragment of one, no length of one, no origin, no host, no
    address, no title, no snippet and no provider message appears anywhere in this
    event." Every one of those values exists on this turn and is distinctive, so an
    implementation that copied any of them into the record fails — and the record is
    serialised whole rather than field by field, because §13's clause is over the
    event and not over a list of keys.

    ADR-0226 §9's own no-copy rule is what admits the one field this kind adds: a
    ``SearchDisposition`` member is a **class**, and there is nowhere in a closed
    enumeration for a query to sit.
    """
    composed = "torre dos clerigos height in metres"
    searcher = FakeWebSearcher(contents={composed: (_RESULT,)})

    with structlog.testing.capture_logs() as captured:
        await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(
                composer=FakeQueryComposer({_ASK: composed}),
                searcher=_CostedSearcher(searcher),
                granted=True,
            ),
        ).respond(_ASK, narrow=_bounded())

    written = json.dumps(_record(captured), default=str)
    assert composed not in written, "no query text"
    assert "clerigos" not in written.lower(), "no fragment of one, and no address"
    assert DEFAULT_SEARCH_ORIGIN not in written, "no origin"
    assert "search.example.com" not in written, "and no host"
    assert _DISTINCTIVE not in written, "no snippet"
    assert "Torre dos Clérigos" not in written, "no title"
    assert DEFAULT_SEARCH_SOURCE_NAME not in written, "and not the source instance either"
    assert str(len(composed)) not in json.dumps(_serviced(captured)["disposition"], default=str)


async def test_the_disposition_rides_on_a_failing_record_too() -> None:
    """§13's field survives the failure ADR-0226 §5 zeroes every count for.

    §13 enumerates the two cases in which the field is empty — where the search
    yielded records and where no ``WEB_SEARCH`` ask was made — and a search that
    declined before a later kind's read raised is neither. Dropping it would make this
    turn indistinguishable from one whose planner never asked for a search, which is
    the collapse ADR-0230 §9 refuses one field over for the unresolved-label count.

    The store raises on the sighted query, which the servicer degrades (§5); the
    search declined before it, on a stage the store has nothing to do with.
    """

    class _RaisingStore(FakeMemoryStore):
        async def search(self, *args: Any, **kwargs: Any) -> Any:
            msg = "the store is unavailable"
            raise MemoryStoreError(msg)

    audit = TurnReadAudit()

    await service_read_request(
        _RaisingStore(now=_clock),
        _search_and_query("anything at all"),
        supply=(),
        fetcher=None,
        listing=None,
        search=_servicer(granted=False),
        utterance=_ASK,
        audit=audit,
    )

    [entry] = audit.servicings
    assert entry.failed is True, "the servicing failed (ADR-0226 §5)"
    assert entry.records == (), "every count zero and the supply as planning saw it"
    assert entry.new == 0
    assert entry.disposition is SearchDisposition.RULING_CONFIRM, (
        "and the search's own disposition survives it (ADR-0231 §13)"
    )


async def test_a_turn_that_asked_for_no_search_carries_no_disposition() -> None:
    """§13's second absence, and the reason the field is nullable at all.

    "Nothing where the search yielded records or where no ``WEB_SEARCH`` ask was
    made." A turn whose planner named only a sighted query has a servicer wired and
    still reports nothing, so the field says something about the *ask* rather than
    about the deployment.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the bell tower is in Porto"))

    with structlog.testing.capture_logs() as captured:
        await _loop(
            planner=FakePlanner(
                now=_clock,
                read_request=ReadRequest(
                    asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="bell tower"),)
                ),
            ),
            memory=memory,
            search=_servicer(granted=True),
        ).respond(_ASK, narrow=_bounded())

    entry = _serviced(captured)
    assert entry["kinds"] == (ReadKind.SIGHTED_QUERY.value,)
    assert entry["disposition"] is None


# --------------------------------------------------------------------------- #
# §18 item 2, end to end: the conversation's egress asks first thereafter      #
# --------------------------------------------------------------------------- #


class _SearchingOneStepPlanner(OneStepPlanner):
    """Plans the same step every turn, and asks for a search on its **first call**.

    ``test_engine_capture_origin.py``'s ``_FetchingOneStepPlanner`` one kind over, and
    for its reason: with a planner that searched every turn, the consequence §18 item 2
    asserts would be indistinguishable from the second turn's own search.
    """

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
    ) -> ActionPlan:
        """Answer the base plan, carrying a ``WEB_SEARCH`` ask the first time only."""
        first = self._calls == 0
        plan = await super().plan(
            goal, context=context, memories=memories, capabilities=capabilities, files=files
        )
        return plan if not first else plan.model_copy(update={"read_request": _search()})


def _searching_egress_harness(*, searching: bool) -> Harness:
    """An engine whose bound tool the fake policy allows on a clean turn, plus a search.

    ``tool()`` is low-risk, reversible, free and discloses nothing, so every clause of
    :class:`~ai_assistant.testing.FakeActionPolicy` but ADR-0181 §5's is silent on it
    — which is what makes the second turn's ruling read the origin fact and nothing
    else, as ``test_engine_capture_origin.py``'s own egress harness does.

    The store is seeded with **nothing** external, so the only thing that can taint the
    first turn is the search result: ADR-0231 §10's mark doing the work ADR-0223 §6
    then acts on. The servicer runs the production ``ThresholdActionPolicy`` over a
    real grant, exactly as every other case here.

    Args:
        searching: Whether the planner asks for a search on its first call. ``False``
            is the control, and the servicer is wired either way.

    Returns:
        The harness.
    """
    definition = tool("smtp", parameters_schema=EGRESS_SCHEMA)
    return Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        planner=(_SearchingOneStepPlanner if searching else OneStepPlanner)(capability=CAPABILITY),
        composing=_replying("Sent."),
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True, at=AT
        ),
    )


async def test_a_turn_that_searched_stamps_its_capture_and_the_next_turn_asks() -> None:
    """§18 item 2, end to end and not at the predicate.

    "That conversation's egress asks first thereafter. The same conversation's
    **next** turn plans a step at the egress seam; the binding carries
    ``planned_with_external_content``; … and the ruling is ``CONFIRM`` and not
    ``ALLOW``."

    **This is the assertion standing between this rung and #1844's exfiltration
    channel**, and unlike ADR-0230's the containment is not that there is nowhere to
    steer to: §12 concedes "the address space is the world, and the loop can reach it",
    and answers with two things — no channel for the steering to travel down, and the
    policy closing even the one bit it leaves. This is the second answer observed, and
    §12 calls it "#1908's exit sentence, mechanically": "a search result is cited as a
    record, and that conversation's egress asks first thereafter — for a second search,
    for an email, for anything at the seam".

    The store holds nothing external at any point and the planner searches on the first
    turn alone, so the second turn's ruling can only be reading the first turn's own
    captured episode, which is asserted rather than assumed.
    """
    harness = _searching_egress_harness(searching=True)

    first = await harness.engine.converse(_ASK, timeout=PATIENT)

    assert first.conversation_id is not None
    assert first.turn is not None
    assert [one.id for one in first.turn.memories if _DISTINCTIVE in one.content] != [], (
        "the search really did put the provider's words in this turn's supply"
    )
    (stamped,) = await _captured(harness)
    assert stamped.provenance.derived_from_external is True, "ADR-0223 §1 over ADR-0231 §10"

    second = await harness.engine.converse(
        _ASK, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.turn is not None
    assert [
        one.id for one in second.turn.memories if rests_on_recorded_external_content(one.provenance)
    ] == [stamped.id], "the first turn's own episode is the only thing carrying the fact"
    assert _DISTINCTIVE not in _contents(second.turn.memories), (
        "and the second turn searched nothing of its own (ADR-0231 §11: turn-scoped)"
    )
    assert second.step is not None
    assert second.step.disposition is Disposition.AWAITING_CONFIRMATION, (
        "ADR-0181 §5's third clause: no ruling on this request is ALLOW"
    )
    request = harness.policy.requests[-1]
    assert request.egress_binding is not None
    assert request.egress_binding.planned_with_external_content is True


async def test_a_conversation_whose_deployment_searched_nothing_keeps_its_allow() -> None:
    """The control: a wired servicer is not itself a taint.

    Without it the case above would pass on an implementation that stamped every turn a
    searcher was wired into — which is what a mark taken from the *wiring* rather than
    from the minted record would do, and what §13 forbids by making a 0% yield "a true
    statement about that configuration rather than a reading of a trigger".
    """
    harness = _searching_egress_harness(searching=False)

    first = await harness.engine.converse(_ASK, timeout=PATIENT)
    assert first.conversation_id is not None
    (episode,) = await _captured(harness)
    assert episode.provenance.derived_from_external is False

    second = await harness.engine.converse(
        _ASK, timeout=PATIENT, conversation_id=first.conversation_id
    )

    assert second.step is not None
    assert second.step.disposition is Disposition.EXECUTED


# --------------------------------------------------------------------------- #
# ADR-0226 §5: a fault the searcher raised degrades the turn and never fails it #
# --------------------------------------------------------------------------- #


class _RaisingTrail:
    """A trail whose ``record`` or ``get`` raises the error the seam contracts.

    ``FakeAuditTrail`` has no failure knob, and §9's second decline cause is stated
    over a trail that "could not record the decision" — which a store outage at either
    await is. Every other member delegates, so what this models is one store fault
    rather than a different contract.
    """

    def __init__(self, *, at: str) -> None:
        self.inner = FakeAuditTrail()
        self._at = at

    async def record(self, decision: PermissionDecision) -> str:
        """Append, or raise where this fake was armed to.

        Args:
            decision: What was decided.

        Returns:
            The id, where the append is allowed to happen.

        Raises:
            AuditError: If this fake was armed at ``record``.
        """
        if self._at == "record":
            msg = "the trail is unavailable"
            raise AuditError(msg)
        return await self.inner.record(decision)

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Read back, or raise where this fake was armed to.

        Args:
            decision_id: What to read.

        Returns:
            The stored decision.

        Raises:
            AuditError: If this fake was armed at ``get``.
        """
        if self._at == "get":
            msg = "the trail's row could not be read"
            raise AuditError(msg)
        return await self.inner.get(decision_id)

    def __getattr__(self, name: str) -> Any:
        """Delegate every other member to the fake this wraps."""
        return getattr(self.inner, name)


@pytest.mark.parametrize("at", ["record", "get"], ids=["the append", "the read-back"])
async def test_a_trail_that_raises_at_either_await_names_the_ruling_stage(at: str) -> None:
    """§13's ``RULING_UNAVAILABLE``, over the fault a store actually has.

    ``_LosingTrail`` above models the trail that accepts and loses; this models the
    one that is simply down, at each of the two awaits ``_ruled`` makes. Both are "an
    ``AuditTrail`` that could not record the decision" (§9), both degrade the turn
    rather than failing it, and neither opens a channel — asserted over a searcher
    that would record the call if one were made.
    """
    searcher = FakeWebSearcher(results=(_RESULT,))

    entry = await _disposition_of(trail=_RaisingTrail(at=at), searcher=_CostedSearcher(searcher))

    assert entry["disposition"] == SearchDisposition.RULING_UNAVAILABLE.value
    assert entry["failed"] is False, "a decline is not a servicing failure"
    assert searcher.searched == [], "and no channel was opened on a decision nothing holds"


class _FaultingSearcher:
    """A searcher whose authorised ``search`` raises the fault its concrete kin do.

    ADR-0231 §17 gives this seam ``Fetcher``'s raise-for-no-source-reason posture, and
    the concrete searcher keeps it — but it also performs ``ToolInvoker.invoke``'s own
    machinery at §6's second route, and *that* raises: ``web_search.py``'s ``search``
    documents ``ConnectionStoreError`` for a connection record it could not read,
    ``AuditError`` for a claim append that failed, ``AuthorisationSpentError`` for a
    spent authorisation, and three more. None of them is a ``SearchRefusal`` and §13
    has no member for any of them.
    """

    def __init__(self, error: Exception) -> None:
        self.inner = _CostedSearcher(FakeWebSearcher(results=(_RESULT,)))
        self._error = error

    @property
    def name(self) -> str:
        """The configured source this searcher serves."""
        return self.inner.name

    async def request(self, query: str, /) -> ActionRequest | None:
        """Propose the search, exactly as the fake it wraps does."""
        return await self.inner.request(query)

    async def search(self, call: ToolCall, /) -> SearchOutcome:
        """Raise the fault this searcher was built with.

        Args:
            call: The authorised call, unused.

        Raises:
            Exception: Whatever this fake was built with.
        """
        raise self._error


@pytest.mark.parametrize(
    "error",
    [
        ConnectionStoreError("the connection record could not be read"),
        AuditError("the ledger refused the claim"),
    ],
    ids=["a connection store outage", "a ledger that refused the claim"],
)
async def test_a_fault_the_searcher_raised_degrades_the_servicing(error: Exception) -> None:
    """ADR-0226 §5 binds this kind entire, and the searcher's own faults reach it.

    "A mechanism whose whole purpose is a marginal improvement in reach must never be
    able to take the reply down with it." ADR-0231 §11 restates it — "a servicing
    failure degrades the turn and never fails it" — and §9's decline list covers the
    three stages *before* the send, each of which resolves to its own disposition. A
    fault the searcher raises after the ruling is none of those and has no
    ``SearchRefusal`` member either, so what it reaches is §5's **all-or-nothing**
    degradation: the supply is left as planning saw it, every count is zero, and the
    record says the servicing failed.

    The other kinds' net is deliberately unwidened by this — ADR-0230 §4's fetch seam
    raises nothing, and the hop and the query raise ``MemoryStoreError`` — so a fault
    reaches the degradation only from the kind whose seam can produce one.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "Porto has a river"))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            memory=memory,
            search=_servicer(searcher=_FaultingSearcher(error), granted=True),
        ).respond(_ASK, narrow=_bounded())

    assert responded.turn is not None, "the turn completed"
    assert responded.turn.plan is not None, "and it carries the plan it was answered from"
    assert [one.id for one in responded.turn.memories] == ["belief-1"], (
        "the supply is exactly what planning saw (ADR-0226 §5)"
    )
    assert _DISTINCTIVE not in _contents(responded.turn.memories)
    entry = _serviced(captured)
    assert entry["failed"] is True, "ADR-0226 §5: the servicing failed"
    assert entry["new"] == 0
    assert entry["returned"] == 0
    assert entry["kinds"] == (ReadKind.WEB_SEARCH.value,), "and the record says which kind"


async def test_the_degradation_line_carries_the_class_and_no_tier_1_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0004 §5, over the **rendered** output rather than the event dict.

    Round 2's architecture blocker, and it is about the *renderer*: ``core.logging``
    renders through ``structlog.dev.ConsoleRenderer``, whose default exception
    formatter is ``rich``'s with ``show_locals=True``, so an ``exc_info=True`` on the
    degradation line writes the raising frames' locals into the log — and those frames
    hold the turn's own utterance, the composed query, the request and the bound call.
    ``redact_sensitive`` cannot reach any of it: it runs **before** the renderer and
    over the event dict's keys, and a rendered traceback is neither.

    Asserted over ``capsys`` and never over ``structlog.testing.capture_logs``, for
    ``tests/permissions/test_action_policy.py``'s reason one seam over: that fixture
    replaces the processor chain, so a "does not leak" test written against it passes
    while the real emission path leaks.

    What the line keeps is what an operator acts on: that a servicing degraded, and
    the **class** that refused — both Tier 2, and enough to tell a connection outage
    from a refused ledger claim.
    """
    utterance = "where is that quinoa-flavoured stroopwafel bakery in Porto"
    composed = "porto stroopwafel bakery address"
    configure_logging(Settings())
    capsys.readouterr()

    await service_read_request(
        FakeMemoryStore(now=_clock),
        _search(),
        supply=(_belief("belief-1", _SUPPLY_SPAN),),
        fetcher=None,
        listing=None,
        search=_servicer(
            composer=FakeQueryComposer({utterance: composed}),
            searcher=_FaultingSearcher(ConnectionStoreError("conn-0001 could not be read")),
            granted=True,
        ),
        utterance=utterance,
        audit=TurnReadAudit(),
    )

    written = capsys.readouterr().out
    assert "read_request_degraded" in written, "the operator is told the servicing degraded"
    assert "ConnectionStoreError" in written, "and which class refused"
    assert utterance not in written, "no utterance"
    assert composed not in written, "no composed query"
    assert _SUPPLY_SPAN not in written, "no span of the supply"
    assert DEFAULT_SEARCH_ORIGIN not in written, "and no origin"
    assert "conn-0001" not in written, "not the connection reference the fault named either"


# --------------------------------------------------------------------------- #
# The production declaration's ruling, pinned rather than assumed (issue #2111) #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [(WEB_SEARCH, PermissionOutcome.CONFIRM), (_COSTED, PermissionOutcome.ALLOW)],
    ids=["the production declaration", "an operator's configured per-call figure"],
)
async def test_a_covering_grant_reaches_an_allow_only_on_a_declared_cost(
    declaration: Any, expected: PermissionOutcome
) -> None:
    """What a covering grant does to the **production** search declaration, today.

    Round 4's adversarial blocker, waived on this branch and filed as issue #2111,
    pinned here so it is a recorded fact rather than something ``_COSTED`` hides.
    ``ThresholdActionPolicy`` fires two floors on ``tools/web_search.py``'s
    ``WEB_SEARCH``: ADR-0021 §5's disclosure floor, which ADR-0193 §3's route (b)
    exists to discharge, **and** ADR-0016 §4's ``UNKNOWN``-cost floor, which is "not
    configurable" and which a grant "satisfies no floor stated over any fact but
    recipient authorisation". ``_only_the_disclosure_floor`` therefore never admits
    route (b) and the seam is not even consulted.

    So on ``origin/main`` a search is `CONFIRM` for **two** reasons, and ADR-0231 §9
    names one: "the disclosure floor fires and ``ActionPolicy`` returns ``CONFIRM``",
    with §19's grant surface as the firing condition. ADR-0231 §5 admits the other's
    remedy in terms — "a ``cost`` that is the operator's configured per-call figure
    where one is configured" — but adds no ``Settings`` field for one and
    ``build_web_search_integration`` takes no parameter for one, so no deployment can
    be that deployment. Closing it is a decision (a fifth ``Settings`` field ADR-0231
    §5 closes at four, or a clause ruling the search ``CONFIRM``-forever), and both
    lie outside this lane's fence.

    The second row is what the rest of this module drives, and it is the *same*
    declaration with the *same* grant and one field ADR-0231 §5 admits — which is
    what makes it a configured deployment modelled rather than ADR-0231 §9's
    forbidden weakening: nothing is narrowed, nothing is restated, and nothing is
    declared ``FREE`` where the figure is unknown.
    """
    binder = _binder(definition=declaration)
    proposed = await _CostedSearcher(FakeWebSearcher()).request("porto bell tower")
    assert proposed is not None
    bound = await binder.bind(
        declaration,
        parameters=proposed.parameters,
        provenance=CarriedProvenance(
            spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
        ),
    )
    assert bound is not None
    grant = _grant().model_copy(update={"tool": declaration})
    policy = ThresholdActionPolicy(grants=FakeRecipientGrants([grant], now=_clock))

    ruled = await policy.decide(
        ActionRequest(tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding)
    )

    assert ruled.outcome is expected
    assert (ruled.authorised_by == "g-search") is (expected is PermissionOutcome.ALLOW), (
        "route (b) names the grant where it is reached, and is not reached otherwise"
    )

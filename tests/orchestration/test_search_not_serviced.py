"""What a turn tells the user about a search it did not make (ADR-0242 §§6-9, §15).

Every arm here drives the **production** servicing path — ``service_read_request``
through ``LearningLoop``, over ``ThresholdActionPolicy`` and the real
:class:`~ai_assistant.orchestration.reads.SearchServicer` — with the canonical fakes
standing only where a *store*, a *provider* or a *model* does, which is §15's own bar.
Where an arm names a reply, the assertion runs the **real** composing renderer
(ADR-0227 §3: "the test that says so runs the real renderer") and a
``FakeModelProvider`` merely records the prompt it was handed.

**No arm asserts that a model produced particular words** (§15). What is asserted of the
reply is that the fixed fragment reached the assembled prompt, and that the prompt on a
turn carrying no member is byte-identical to today's. The eight **surface** statements
are asserted over their rendered bytes in
``tests/interfaces/test_cli_destination_trust.py``, because those are the system's own
words.

**What is deliberately not here.** ADR-0242 §10 rules that this lane "implements no
producer" for ``DEADLINE_EXPIRED`` or ``SEARCH_FAILED`` — those are ADR-0241's lane's to
emit — so the arms over those two construct the dispositions directly, which is what
that section says in terms.

**``TRUST_MISSING`` now joins them, and for a reason of its own** (ADR-0247 §1, §6,
#2252). The member and its row in ADR-0242 §8's table stay ratified and are still
asserted over ``not_serviced`` at the top of this module; what has gone is its producer,
because the servicing site no longer takes a ``trust_of`` answer to pass. So the §15
journeys that revoked trust, established it later, or told a ``TRUST_MISSING`` follow-up
from an ``UNAVAILABLE`` one are **removed rather than rewritten**: each was an arm over a
read that is not taken. ``AUTHORISATION_AWAITED`` keeps a producer — ADR-0236 §4's
unknown per-call cost — and its arms are unmoved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, final

import pytest
import structlog
from test_closed_loop import _chosen_footing, _external_belief
from test_loop_search import (
    _ASK,
    _RESULT,
    _REVISING,
    SettlesAfter,
    _belief,
    _binder,
    _bounded,
    _clock,
    _CostedSearcher,
    _footing,
    _loop,
    _search,
    _serviced,
    _servicer,
)

from ai_assistant.core.types import (
    QueryRefusal,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SearchNotServiced,
    SearchOutcome,
    SearchRefusal,
    StructuredAsk,
    TurnOutcome,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reads import SearchDisposition, earliest, not_serviced
from ai_assistant.testing import (
    DEFAULT_COMPOSED_QUERY,
    FAKE_WEB_SEARCH,
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanner,
    FakeQueryComposer,
    FakeStreamingCompleter,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ToolCall
    from ai_assistant.orchestration.loop import RespondedTurn


# --------------------------------------------------------------------------- #
# §8's table, stated once here so a lane changing the mapping changes this too  #
# --------------------------------------------------------------------------- #

#: ADR-0242 §8's mapping, transcribed from the ADR's own table. Written out rather than
#: derived, so this is a second statement of the decision the implementation can be
#: compared against rather than a restatement of the implementation.
_TABLE: Final[dict[SearchDisposition, SearchNotServiced]] = {
    SearchDisposition.SPEND_REFUSED: SearchNotServiced.SPEND_EXHAUSTED,
    SearchDisposition.RULING_DENY: SearchNotServiced.DECLINED,
    SearchDisposition.DEADLINE_EXPIRED: SearchNotServiced.INTERRUPTED,
    SearchDisposition.NOT_CONFIGURED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.NO_BUDGET: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.COMPOSER_DECLINED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.COMPOSER_UNAVAILABLE: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.COMPOSER_MALFORMED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.COMPOSER_TOO_LONG: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.BINDING_FAILED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.RULING_UNAVAILABLE: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.TRANSPORT_FAILED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.PROVIDER_REFUSED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.RESPONSE_TOO_LARGE: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.UNATTESTED: SearchNotServiced.UNAVAILABLE,
    SearchDisposition.SEARCH_FAILED: SearchNotServiced.UNAVAILABLE,
}


def test_the_mapping_is_total_over_all_seventeen_dispositions() -> None:
    """§15: "the mapping table in §8 is **total**" over the enumeration as it stands.

    Failing if a member is added without a mapping — which is what makes forgetting one a
    test failure rather than a silent ``UNAVAILABLE``. The enumeration is asserted at
    **seventeen** first, because ADR-0247 §6 removes ``NOT_ADMITTED`` "in that count
    alone" and an eighteenth is an ADR's to add: without that half, a member added with
    no entry here would be admitted by the ``case _`` default and this arm would pass.

    And the two members that row rendered — ``SEARCH_DISABLED`` and ``NOT_ADMITTED`` —
    are gone with it (ADR-0247 §6), which is why the discriminated set below is one row
    rather than two.
    """
    assert len(SearchDisposition) == 17, (
        "ADR-0231 §13's fifteen and ADR-0241's two, less ADR-0238 §11's sixteenth, "
        "which ADR-0247 §6 removes with the budget — and ADR-0242 §8 maps every one"
    )
    discriminated = {SearchDisposition.RULING_CONFIRM}

    assert set(_TABLE) | discriminated == set(SearchDisposition)
    for stage, member in _TABLE.items():
        assert not_serviced(stage) is member, stage


def test_the_removed_members_are_absent_from_both_vocabularies() -> None:
    """ADR-0247 §6, asserted by name so a reintroduction is a test failure.

    ``SearchDisposition.NOT_ADMITTED``, ``SearchNotServiced.SEARCH_DISABLED`` and
    ``SearchNotServiced.NOT_ADMITTED`` were each defined over ``admit_search``'s refusal
    and over ``Settings.search_calls_per_conversation``'s value, and neither vocabulary
    holds them once §5 removes the budget. **The two that are *not* removed are asserted
    beside them**: ``TRUST_MISSING`` and ``AUTHORISATION_AWAITED`` become unreachable on
    a configured deployment and stay, because removing them is outside the owner's own
    ruling (§6, #2252).
    """
    assert "NOT_ADMITTED" not in SearchDisposition.__members__
    assert "SEARCH_DISABLED" not in SearchNotServiced.__members__
    assert "NOT_ADMITTED" not in SearchNotServiced.__members__
    assert len(SearchNotServiced) == 7, "ADR-0247 §6 closes the vocabulary at seven"
    assert {"TRUST_MISSING", "AUTHORISATION_AWAITED"} <= set(SearchNotServiced.__members__), (
        "and the two ADR-0247 §6 names as *not* removed are still here (#2252)"
    )


def test_the_one_discriminated_row_is_the_one_the_disposition_cannot_decide() -> None:
    """§8's value-discriminated row, each way.

    ``RULING_CONFIRM`` is three members because it "is recorded both where **no grant
    covers the recipients at all** and where **a grant stands but the closed loop is not
    closed**". It is now the **only** such row: ADR-0247 §6 removes the
    configuration-discriminated one with the ``Settings`` value that discriminated it.
    """
    from ai_assistant.core.types import DestinationTrust  # noqa: PLC0415 — one arm's input

    assert (
        not_serviced(SearchDisposition.RULING_CONFIRM, planned_with_external_content=False)
        is SearchNotServiced.AUTHORISATION_AWAITED
    )
    assert (
        not_serviced(
            SearchDisposition.RULING_CONFIRM,
            planned_with_external_content=True,
            trust=DestinationTrust.UNCHOSEN,
        )
        is SearchNotServiced.TRUST_MISSING
    )
    assert (
        not_serviced(
            SearchDisposition.RULING_CONFIRM,
            planned_with_external_content=True,
            trust=DestinationTrust.USER_CHOSEN,
        )
        is SearchNotServiced.UNAVAILABLE
    ), "the destination is already chosen, so the trust act is not the answer (§8)"


def test_a_servicing_that_yielded_carries_no_member() -> None:
    """§6: "the eligibility condition is the disposition's presence and nothing else"."""
    assert not_serviced(None) is None


# --------------------------------------------------------------------------- #
# §7's precedence, over the declared order and never the encounter order        #
# --------------------------------------------------------------------------- #


def test_the_declared_order_and_not_the_encounter_order_decides() -> None:
    """§7: "**The order and not the encounter order decides it**".

    Both directions, because an implementation carrying the last one it computed and one
    assigning only while the carrier is ``None`` each pass every single-servicing arm.
    """
    first, second = SearchNotServiced.SPEND_EXHAUSTED, SearchNotServiced.UNAVAILABLE

    assert earliest(first, second) is first
    assert earliest(second, first) is first


def test_a_yielding_servicing_does_not_clear_an_earlier_members() -> None:
    """§7: "A servicing that yields records does not clear a member an earlier one
    produced."

    §6's eligibility is stated over the *presence* of a disposition, and a later success
    does not remove one.
    """
    assert earliest(SearchNotServiced.TRUST_MISSING, None) is SearchNotServiced.TRUST_MISSING
    assert earliest(None, None) is None


# --------------------------------------------------------------------------- #
# §6, §7: the fragment reaches the prompt, and only where a member is carried   #
# --------------------------------------------------------------------------- #


async def _system_prompt(
    responded: RespondedTurn, *, member: SearchNotServiced | None = None
) -> str:
    """The system prompt the **production** renderer assembles for one turn.

    ADR-0227 §7's fidelity rule forbids substituting "the renderer whose output the
    assertion is about" and permits a fake ``ModelProvider``, so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles the prompt
    and the fake merely records it.
    """
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(
        turn=responded.turn,
        step=None,
        undriven=(),
        hop_reached=responded.hop_reached,
        search_not_serviced=member if member is not None else responded.search_not_serviced,
    )
    [call] = model.calls
    from ai_assistant.core.types import Role  # noqa: PLC0415 — one helper's own lookup

    return next(one.content for one in call.messages if one.role is Role.SYSTEM)


@pytest.mark.parametrize("member", list(SearchNotServiced))
async def test_every_member_puts_a_fragment_of_its_own_into_the_prompt(
    member: SearchNotServiced,
) -> None:
    """§7, §13: **eight** fragments, one per member, written out as literals.

    Parametrised over the vocabulary itself, so a ninth member added without its fragment
    fails here rather than composing a prompt with nothing in it — which is what §13
    means by "a member added without its two texts is a member with no rendering".
    """
    responded = await _loop(planner=FakePlanner(now=_clock)).respond(_ASK, narrow=_bounded())
    bare = await _system_prompt(responded)

    carried = await _system_prompt(responded, member=member)

    assert carried != bare
    assert carried.startswith(bare), (
        "the fragment is **appended**, so a turn carrying one sees everything a turn "
        "carrying none sees (ADR-0228 §10's shape)"
    )


async def test_the_fragments_are_one_distinct_text_per_member() -> None:
    """§13: written out one per member, and never assembled from a name or a mapping.

    Two members sharing a text would be two members with one rendering, which is the
    collapse §8's split exists to prevent — a user sent to the wrong command.
    """
    responded = await _loop(planner=FakePlanner(now=_clock)).respond(_ASK, narrow=_bounded())
    bare = await _system_prompt(responded)

    fragments = {
        (await _system_prompt(responded, member=member)).removeprefix(bare)
        for member in SearchNotServiced
    }

    assert len(fragments) == len(SearchNotServiced)


@pytest.mark.parametrize("member", list(SearchNotServiced))
async def test_no_fragment_carries_a_destination_a_count_or_a_command_name(
    member: SearchNotServiced,
) -> None:
    """§7's bar, asserted over the assembled prompt and not over an intention.

    No fragment carries a destination, a host, an origin, a provider name, a connection
    reference, an account identity, a query or any fragment of one, a record, a count, a
    monetary figure, a duration, a budget, a ``Settings`` field name, a
    ``SearchDisposition`` value, a record id, a decision id, **or a command name**. A
    command name in a model-composed reply "would reach a browser and a voice channel
    where no terminal exists, and it would be a string a model may paraphrase, truncate
    or invent" (§9).
    """
    responded = await _loop(planner=FakePlanner(now=_clock)).respond(_ASK, narrow=_bounded())
    bare = await _system_prompt(responded)

    fragment = (await _system_prompt(responded, member=member)).removeprefix(bare)

    assert not any(character.isdigit() for character in fragment)
    for forbidden in ("assistant ", "http", "@", "$", "search_calls_per_conversation"):
        assert forbidden not in fragment
    for stage in SearchDisposition:
        assert stage.value not in fragment


async def test_a_turn_carrying_no_member_assembles_the_prompt_it_always_did() -> None:
    """§6: "the assembled prompt is byte-identical to what it is today".

    The clause that keeps a new prompt input from silently moving every reply the system
    composes — ADR-0227 §3's own guarantee and ADR-0228 §10's, taken here for the same
    reason. Asserted by composing **twice** over one turn, once with the parameter
    omitted entirely and once with the carrier the turn actually produced, and comparing
    the two prompts byte for byte.
    """
    responded = await _loop(planner=FakePlanner(now=_clock)).respond(_ASK, narrow=_bounded())
    assert responded.search_not_serviced is None

    without = FakeModelProvider("answer")
    await ComposingStage(model=without, streaming=FakeStreamingCompleter()).compose(
        turn=responded.turn, step=None, undriven=()
    )
    threaded = FakeModelProvider("answer")
    await ComposingStage(model=threaded, streaming=FakeStreamingCompleter()).compose(
        turn=responded.turn,
        step=None,
        undriven=(),
        search_not_serviced=responded.search_not_serviced,
    )

    assert [one.content for one in threaded.calls[0].messages] == [
        one.content for one in without.calls[0].messages
    ]


# --------------------------------------------------------------------------- #
# §15 Arm 1 — the positive path                                                 #
# --------------------------------------------------------------------------- #


async def test_a_turn_whose_search_was_serviced_carries_no_member() -> None:
    """§15 Arm 1: "``TurnOutcome.search_not_serviced`` is ``None`` on both".

    §6's byte-identity guarantee made checkable: a turn that searched and got records
    says nothing about a lookup that did not happen, because there was none.
    """
    footing = _chosen_footing()
    searcher = FakeWebSearcher(results=(_RESULT,))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
            footing=footing,
        ).respond(_ASK, narrow=_bounded())

    assert _serviced(captured)["disposition"] is None
    assert responded.search_not_serviced is None


async def test_a_search_that_found_nothing_carries_no_member() -> None:
    """§6: a search that **ran, reached the provider and found nothing** carries none.

    ``SearchRefusal.NO_RESULT`` is not a refusal and maps to no ``SearchDisposition``
    member (ADR-0231 §13), "so the assistant looked, and saying it did not would be
    false".
    """
    responded = await _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(
            searcher=_CostedSearcher(
                FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.NO_RESULT})
            ),
            granted=True,
        ),
        footing=_chosen_footing(),
    ).respond(_ASK, narrow=_bounded())

    assert responded.search_not_serviced is None


async def test_a_response_refused_after_it_arrived_carries_unavailable() -> None:
    """§6: a search "that reached the provider and whose response was then refused" does.

    It carries ``UNAVAILABLE``: records reached no supply, the user has no act, and §9
    fixes a statement for that member which says the lookup produced nothing usable and
    **does not say that no request was made**.
    """
    searcher = FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.UNATTESTED})

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
            footing=_chosen_footing(),
        ).respond(_ASK, narrow=_bounded())

    assert _serviced(captured)["disposition"] == SearchDisposition.UNATTESTED.value
    assert responded.search_not_serviced is SearchNotServiced.UNAVAILABLE
    assert len(searcher.searched) == 1, "the request was made, which is why §9 may not deny it"


# --------------------------------------------------------------------------- #
# §15 Arm 2 — missing authority, as three fixtures rather than two              #
# --------------------------------------------------------------------------- #


async def test_a_first_refused_search_carries_authorisation_awaited() -> None:
    """§15 Arm 2(a): no grant, a first search, a clean footing.

    The binding carries ``planned_with_external_content`` ``False``, the disposition is
    ``RULING_CONFIRM``, and the carried member is ``AUTHORISATION_AWAITED`` — the class
    of act being ADR-0235's, and the decision one that act **may ride** by construction.
    """
    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            search=_servicer(granted=False),
            footing=_footing(),
        ).respond(_ASK, narrow=_bounded())

    assert _serviced(captured)["disposition"] == SearchDisposition.RULING_CONFIRM.value
    assert responded.search_not_serviced is SearchNotServiced.AUTHORISATION_AWAITED


async def test_a_standing_grant_and_an_unknown_cost_still_carry_authorisation_awaited() -> None:
    """§15 Arm 2(a2): the configuration that falsifies the easier reading.

    A grant **standing**, an utterance-only search, and ``web_search_cost_per_call``
    unset — so ADR-0236 §4's unknown-cost floor produces the same ``RULING_CONFIRM``
    whatever grants exist: "the ``RecipientGrants`` seam is consulted **zero** times".
    The member is ``AUTHORISATION_AWAITED`` again, which is what pins §8's
    states-what-its-inputs-establish rule; the statement's own half — that it does not
    say no standing authorisation covers the recipients — is asserted over the rendered
    bytes in ``tests/interfaces/test_cli_destination_trust.py``.
    """
    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            # The **uncosted** deployment: `_servicer`'s default wraps the fake in
            # `_CostedSearcher`, which is the deployment that declared a figure, so the
            # bare fake is ADR-0236 §4's shipped default. The binder is registered
            # against *its* declaration, because a binding seam holding a different
            # declaration refuses the request before any ruling is sought.
            search=_servicer(
                searcher=FakeWebSearcher(), binder=_binder(definition=FAKE_WEB_SEARCH), granted=True
            ),
            footing=_footing(),
        ).respond(_ASK, narrow=_bounded())

    assert _serviced(captured)["disposition"] == SearchDisposition.RULING_CONFIRM.value
    assert responded.search_not_serviced is SearchNotServiced.AUTHORISATION_AWAITED


async def _followed_up() -> FakeMemoryStore:
    """A store whose retrieval puts one record of **another** external origin in view.

    What makes ADR-0242 §15 Arm 2's (b) and (c) *follow-up* searches is a recorded
    external span in the turn's supply, and ADR-0238 §5's condition is "blind to why a
    record is external" — so a reader's, a fetch's or an ingested message's serves as
    well as any. **It may not be a stamped episode of this conversation**: ADR-0238 §15
    Arm 1b rules that one an ``ALLOW`` and it is this milestone's exit, so a (c) built on
    one would assert the closed-loop condition refuses a request the corpus deliberately
    admits (#2205). (b) and (c) take the same store, because Arm 2 says they "differ in
    the ``trust_of`` answer alone".
    """
    store = FakeMemoryStore(now=_clock)
    await store.add(_external_belief("belief-foreign", "something a reader ingested"))
    return store


async def test_a_follow_up_at_the_configured_provider_is_serviced_and_carries_nothing() -> None:
    """What ADR-0247 §3 leaves of §15 Arm 2's (b) and (c): neither row is reachable.

    Both were rows of one ``RULING_CONFIRM`` the lineage floor drew over a follow-up
    search — a turn with a recorded external span in view — and ADR-0247 §3 retires that
    floor for a request at the configured provider. So the follow-up is **serviced**, the
    disposition is ``None`` and the turn carries no member at all: there is nothing to
    explain, because the search happened.

    **The two members are not deleted and this case is not their replacement.** ADR-0247
    §6 rules that ``TRUST_MISSING`` and ``AUTHORISATION_AWAITED`` stay and that "no lane
    removes them"; what has gone is ``TRUST_MISSING``'s producer on a configured
    deployment (#2252), while ``AUTHORISATION_AWAITED``'s survives on the unknown-cost
    floor two cases above. The mapping itself — including the ``UNCHOSEN`` row that
    yields ``TRUST_MISSING`` — is still asserted over ``not_serviced`` directly at the
    top of this module.
    """
    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=FakePlanner(now=_clock, read_request=_search()),
            memory=await _followed_up(),
            search=_servicer(granted=True),
            footing=_footing(),
        ).respond(_ASK, narrow=_bounded())

    assert _serviced(captured)["disposition"] is None, (
        "the lineage floor no longer fires at the configured provider (ADR-0247 §3), so "
        "the follow-up reached the provider"
    )
    assert responded.search_not_serviced is None


# --------------------------------------------------------------------------- #
# §15 Arm 2b — the turn-wide precedence and retention rule                      #
# --------------------------------------------------------------------------- #


@final
class _RefusingOnceThen:
    """A conforming ``WebSearcher`` whose refusal differs by call ordinal.

    A turn's two servicings compose the **same** query, so neither the canonical fake's
    scripted refusals nor its suspension can express "the first call and then the
    second" from outside a ``respond`` — which is the shape §15's Arm 2b needs. It
    delegates every other member, so what the policy rules on and what the seam is
    registered against are the deployment ADR-0231 §5 describes.
    """

    def __init__(self, inner: Any, refusals: Sequence[SearchRefusal | None]) -> None:
        self.inner = inner
        self._refusals = list(refusals)
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        """Delegate everything this class does not name."""
        return getattr(self.inner, name)

    async def search(
        self,
        call: ToolCall,
        *,
        timeout: Any = None,  # noqa: ASYNC109 — the seam's own signature (ADR-0241 §3), relayed
    ) -> SearchOutcome:
        """Answer the scripted refusal for this call's ordinal."""
        refusal = self._refusals[min(self.calls, len(self._refusals) - 1)]
        self.calls += 1
        if refusal is None:
            outcome: SearchOutcome = await self.inner.search(call, timeout=timeout)
            return outcome
        return SearchOutcome(refusal=refusal)


@final
class _DecliningOnCall:
    """A ``QueryComposer`` that declines on one call ordinal and composes on the others."""

    def __init__(self, inner: FakeQueryComposer, *, declines_on: int) -> None:
        self.inner = inner
        self._declines_on = declines_on
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        """Delegate everything this class does not name."""
        return getattr(self.inner, name)

    async def compose(self, supply: Any) -> Any:
        """Decline on the scripted ordinal, compose otherwise."""
        ordinal = self.calls
        self.calls += 1
        if ordinal == self._declines_on:
            from ai_assistant.core.types import QueryOutcome  # noqa: PLC0415 — one branch's type

            return QueryOutcome(refusal=QueryRefusal.DECLINED)
        return await self.inner.compose(supply)


def _search_beside_an_empty_structured_read() -> ReadRequest:
    """A ``WEB_SEARCH`` ask beside a ``STRUCTURED_READ`` that matches nothing.

    **This is what makes a turn with two *refused* servicings reachable at all**, and it
    is ADR-0228 §2(e) rather than a trick: a turn revises only where the servicing added
    records **or** its structured read came back empty, so a turn whose first search was
    refused and which asked for nothing else settles at once. ADR-0240 §6's second
    branch is the door, and §15's Arm 2b needs a turn that goes through it.
    """
    return ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.WEB_SEARCH),
            ReadAsk(
                kind=ReadKind.STRUCTURED_READ,
                structure=StructuredAsk(topics=("nothing-is-filed-under-this",)),
            ),
        )
    )


async def _separated() -> FakeMemoryStore:
    """A store holding one **semantic** record, so a structured read is reached at all.

    ADR-0240 §5 blocks a structured read where every record of the supply is
    ``EPISODIC`` when the read is reached — its own episodes would form the leading run
    — and records that as ``NO_SEPARATOR`` rather than as an empty read. A turn over an
    empty store hits that branch, so the revision door §2(e) opens would stay shut and
    the arm would be asserting the stop rule rather than the precedence rule.
    """
    store = FakeMemoryStore(now=_clock)
    await store.add(_belief("belief-1", "we talked about Porto last week"))
    return store


def _revising_planner() -> Any:
    """A planner that asks for a search on two rounds and then settles (ADR-0251 §4).

    Two rounds is what these cases are about, and under §4 that is the planner's own
    judgement rather than a bound: (e) is dissolved and the count is the attempt's, so
    a planner that went on asking would be called until §7's run test refused it.
    """
    return SettlesAfter(
        FakePlanner(now=_clock, read_request=_search_beside_an_empty_structured_read())
    )


@pytest.mark.parametrize("spend_first", [True, False])
async def test_the_earliest_member_in_the_declared_order_is_the_one_carried(
    spend_first: bool,
) -> None:
    """§15 Arm 2b, **both** orders, on the production servicing path.

    A turn recording ``SPEND_REFUSED`` and then ``COMPOSER_DECLINED`` carries
    ``SPEND_EXHAUSTED`` — which a last-computed-wins implementation fails — and the
    reversed order carries ``SPEND_EXHAUSTED`` too, which a first-computed-wins one
    fails. "An implementation assigning only while the carrier is ``None`` passes every
    other arm here, so without this one the precedence rule is untested in the direction
    it is most likely to be got wrong."
    """
    # The composer decides which servicing reaches the searcher at all, so the searcher
    # refuses **whichever** call it gets: on one order that is the first servicing's, on
    # the other the second's, and the encounter order below is what the arm varies.
    searcher = _RefusingOnceThen(_CostedSearcher(FakeWebSearcher()), (SearchRefusal.SPEND_REFUSED,))
    composer = _DecliningOnCall(FakeQueryComposer(), declines_on=1 if spend_first else 0)

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=_revising_planner(),
            search=_servicer(searcher=searcher, composer=composer, granted=True),
            memory=await _separated(),
            footing=_chosen_footing(),
        ).respond(_ASK, narrow=_bounded(), operation=_REVISING)

    recorded = [servicing["disposition"] for servicing in _serviced_all(captured)]
    expected = [SearchDisposition.SPEND_REFUSED.value, SearchDisposition.COMPOSER_DECLINED.value]
    assert recorded == (expected if spend_first else expected[::-1]), recorded
    assert responded.search_not_serviced is SearchNotServiced.SPEND_EXHAUSTED


def _serviced_all(captured: Sequence[Any]) -> Sequence[Any]:
    """Every servicing this turn recorded, in servicing order (ADR-0228 §9)."""
    [only] = [event for event in captured if event["event"] == "turn_read_request"]
    return only["servicings"]  # type: ignore[no-any-return]


async def test_a_second_servicing_that_succeeds_does_not_clear_the_first_members() -> None:
    """§15 Arm 2b's third shape: a refused first search and a **successful** second.

    "A turn whose first search is refused and whose second **succeeds** still carries the
    first's member", because §6's eligibility is stated over the presence of a
    disposition and a later success does not remove one.
    """
    searcher = _RefusingOnceThen(
        _CostedSearcher(FakeWebSearcher(results=(_RESULT,))), (SearchRefusal.SPEND_REFUSED, None)
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=_revising_planner(),
            search=_servicer(searcher=searcher, granted=True),
            memory=await _separated(),
            footing=_chosen_footing(),
        ).respond(_ASK, narrow=_bounded(), operation=_REVISING)

    dispositions = [servicing["disposition"] for servicing in _serviced_all(captured)]
    assert dispositions == [SearchDisposition.SPEND_REFUSED.value, None]
    assert responded.search_not_serviced is SearchNotServiced.SPEND_EXHAUSTED


# --------------------------------------------------------------------------- #
# ADR-0247 §12 Arm H — nothing bounds a conversation's search count             #
# --------------------------------------------------------------------------- #


async def test_a_conversation_searches_past_the_former_default_without_a_refusal() -> None:
    """ADR-0247 §12's **Arm H**, which replaces ADR-0238 §15's Arms 3, 6 and 6b entire.

    "A conversation makes more searches than ``search_calls_per_conversation``'s former
    default without a refusal, no disposition naming an allowance is reachable, and the
    turn-level bound still holds." The former default was **eight**, so nine turns of one
    conversation is the shape that would have been refused on the ninth — and each turn
    here declares no planning budget, so it starts one planner call and therefore one
    search (ADR-0228 §4), which is the bound §5 names as what remains.
    """
    searcher = FakeWebSearcher(results=(_RESULT,))
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
        footing=_chosen_footing(),
    )

    outcomes = [await turns.respond(_ASK, narrow=_bounded()) for _ in range(9)]

    assert len(searcher.searched) == 9, (
        "every turn of the conversation reached the provider — nothing per-conversation "
        "counted, compared or refused (ADR-0247 §5)"
    )
    assert [one.search_not_serviced for one in outcomes] == [None] * 9, (
        "and no turn carried a member at all, least of all one naming an allowance"
    )


async def test_no_member_of_either_vocabulary_names_an_allowance() -> None:
    """ADR-0247 §12 Arm H's second half, asserted over the vocabularies themselves.

    "No disposition naming an allowance is reachable" — which after §6 is true by
    construction rather than by exhaustion, because the members that named one are
    removed. Asserted by name so that a lane reintroducing either fails here as well as
    at the mapping table.
    """
    assert "NOT_ADMITTED" not in SearchDisposition.__members__
    assert not {"SEARCH_DISABLED", "NOT_ADMITTED"} & set(SearchNotServiced.__members__)


async def test_a_spend_refusal_carries_its_own_member() -> None:
    """§15 Arm 4's residue, over the members ADR-0247 §6 leaves.

    Arm 4 is **retired** by ADR-0247 §12 — the allowance it was stated over is gone —
    and what survives of it is that a monetary ceiling is not collapsed into any other
    outcome: §9 fixes a distinct statement per member, and a spend refusal has one.
    """
    responded = await _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(
            searcher=_CostedSearcher(
                FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.SPEND_REFUSED})
            ),
            granted=True,
        ),
        footing=_chosen_footing(),
    ).respond(_ASK, narrow=_bounded())

    assert responded.search_not_serviced is SearchNotServiced.SPEND_EXHAUSTED
    assert len({SearchNotServiced.SPEND_EXHAUSTED, SearchNotServiced.DECLINED}) == 2, (
        "a ceiling of money and a ruling are two facts with two different owners"
    )


# --------------------------------------------------------------------------- #
# §9: the field is `None` on a restatement, and on every unsearching turn       #
# --------------------------------------------------------------------------- #


def test_a_restatement_carries_no_member() -> None:
    """§9: ``None`` on ADR-0198 §1's **restatement**, "which drives nothing and searches
    nothing".

    That adds a value to ADR-0198 §2's enumeration without changing any value it fixes.
    """
    assert TurnOutcome(turn=None, step=None).search_not_serviced is None


def test_the_field_does_not_set_reply_degraded() -> None:
    """§6: "The fact does **not** set ``TurnOutcome.reply_degraded``."

    ADR-0170 §4 fixes the three shapes on which ``reply`` is ``None`` and the one on
    which ``reply_degraded`` is ``True``; this decision alters neither. "A turn that
    could not search still composed the reply it composed."
    """
    outcome = TurnOutcome(turn=None, step=None, search_not_serviced=SearchNotServiced.TRUST_MISSING)

    assert outcome.reply_degraded is False
    assert outcome.reply is None

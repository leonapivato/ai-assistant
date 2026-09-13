"""What a turn says it did about reaching outside this system (ADR-0264 §§1-6, §13).

Every arm here drives the **production** servicing path — ``service_read_request``
through ``LearningLoop``, over ``ThresholdActionPolicy`` and the real
:class:`~ai_assistant.orchestration.reads.SearchServicer` — with the canonical fakes
standing only where a *store*, a *provider* or a *model* does. The harness is
``test_loop_search``'s and ``test_search_not_serviced``'s, deliberately: ADR-0264 §8
rules that this decision's member and ADR-0242 §9's "ride together and neither is read
off the other", and an arm asserting that over two different harnesses would be
asserting it over two different turns.

``tests/orchestration/test_engine_outbound_statement.py`` drives the pipeline **above**
this one — the ``TurnOutcome`` the capture point builds, the routed passes, the driven
egress step and the two-valued shapes #2268 and #2365 record.

**No arm asserts that a model produced particular words.** §6's closing paragraph is
explicit that telling the model is *not* what makes this decision work: "a prompt
fragment is an instruction a model may ignore — #2268 is a model ignoring the absence of
one, #2365 a model inventing what none supplied". What is asserted of the reply is that
the fixed fragment reached the assembled prompt; the **rendered** statements are lane
2's, landed with the renderer they are about (§11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final, final

import pytest
import structlog
from test_closed_loop import _chosen_footing
from test_loop_search import (
    _ASK,
    _CONFIGURED_SEARCH,
    _NOW,
    _RESULT,
    _REVISING,
    SettlesAfter,
    _belief,
    _bounded,
    _clock,
    _CostedSearcher,
    _loop,
    _RefiningSearcher,
    _search,
    _search_and_query,
    _servicer,
)
from test_search_not_serviced import _RefusingOnceThen, _separated, _serviced_all

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    MemoryKind,
    OutboundDestination,
    OutboundReach,
    PermissionOutcome,
    ReadAsk,
    ReadKind,
    ReadRequest,
    RiskLevel,
    Role,
    SearchNotServiced,
    SearchOutcome,
    SearchRefusal,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reads import (
    SEARCH_CONTACTS,
    SearchDisposition,
    contact_of,
    folded_reach,
    outbound_statement,
)
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing import (
    DEFAULT_COMPOSED_QUERY,
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanner,
    FakeRecipientGrants,
    FakeStreamingCompleter,
    FakeWebSearcher,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import BeliefBand, MemoryRecord, MemorySearchResult, ToolCall
    from ai_assistant.orchestration.loop import RespondedTurn


# --------------------------------------------------------------------------- #
# §2's partition, transcribed from the ADR rather than read off the mapping     #
# --------------------------------------------------------------------------- #

#: ADR-0264 §2's three groups, written out from the decision's own prose so this module
#: is a second statement of it rather than a restatement of the implementation. The
#: eighteenth case — an absent disposition — is asserted separately, because it is a
#: property of :func:`contact_of` and not a row of any table.
_PARTITION: Final[dict[SearchDisposition, OutboundReach]] = {
    # "A call whose disposition is ``NOT_CONFIGURED``, ``NO_BUDGET``,
    # ``COMPOSER_DECLINED``, ``COMPOSER_UNAVAILABLE``, ``COMPOSER_MALFORMED``,
    # ``COMPOSER_TOO_LONG``, ``BINDING_FAILED``, ``RULING_CONFIRM``, ``RULING_DENY``,
    # ``RULING_UNAVAILABLE`` or ``SPEND_REFUSED`` establishes **no** contact."
    SearchDisposition.NOT_CONFIGURED: OutboundReach.NOT_REACHED,
    SearchDisposition.NO_BUDGET: OutboundReach.NOT_REACHED,
    SearchDisposition.COMPOSER_DECLINED: OutboundReach.NOT_REACHED,
    SearchDisposition.COMPOSER_UNAVAILABLE: OutboundReach.NOT_REACHED,
    SearchDisposition.COMPOSER_MALFORMED: OutboundReach.NOT_REACHED,
    SearchDisposition.COMPOSER_TOO_LONG: OutboundReach.NOT_REACHED,
    SearchDisposition.BINDING_FAILED: OutboundReach.NOT_REACHED,
    SearchDisposition.RULING_CONFIRM: OutboundReach.NOT_REACHED,
    SearchDisposition.RULING_DENY: OutboundReach.NOT_REACHED,
    SearchDisposition.RULING_UNAVAILABLE: OutboundReach.NOT_REACHED,
    SearchDisposition.SPEND_REFUSED: OutboundReach.NOT_REACHED,
    # "or where the disposition it recorded is ``RESPONSE_TOO_LARGE`` or
    # ``UNATTESTED``, each of which this system reaches only from octets the provider's
    # channel had already returned."
    SearchDisposition.RESPONSE_TOO_LARGE: OutboundReach.REACHED,
    SearchDisposition.UNATTESTED: OutboundReach.REACHED,
    # "A call whose disposition is ``TRANSPORT_FAILED``, ``DEADLINE_EXPIRED``,
    # ``SEARCH_FAILED`` or ``PROVIDER_REFUSED`` establishes **nothing either way**."
    SearchDisposition.TRANSPORT_FAILED: OutboundReach.INDETERMINATE,
    SearchDisposition.DEADLINE_EXPIRED: OutboundReach.INDETERMINATE,
    SearchDisposition.SEARCH_FAILED: OutboundReach.INDETERMINATE,
    SearchDisposition.PROVIDER_REFUSED: OutboundReach.INDETERMINATE,
}

#: A distinctive clause of each of ADR-0264 §6's three fragments, quoted so an arm
#: asserts the **fragment** reached the prompt rather than that two prompts differ —
#: which they also do for reasons ADR-0228 §10 and ADR-0242 §7 own.
_REACHED_FRAGMENT: Final = "this assistant reached outside this system, and it took in"
_NOT_REACHED_FRAGMENT: Final = "this assistant reached nothing outside this system"
_INDETERMINATE_FRAGMENT: Final = "this system cannot say whether it reached outside itself"


class _FailSearchFrom(FakeMemoryStore):
    """A store whose ``search`` fails from the ``nth`` call onward.

    ``test_loop_reads``' own double, brought here rather than imported because that
    module's copy is keyed to its clock: "the turn's own belief composition reads three
    bands before the servicer reads anything, so counting calls is how a case arms a
    failure *inside* the servicing while leaving the supply planning saw intact".
    """

    def __init__(self, *, nth: int, now: Clock = _clock) -> None:
        """Fail from the ``nth`` ``search`` call of this store's life."""
        super().__init__(now=now)
        self.calls = 0
        self._nth = nth

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
        **axes: Any,  # ADR-0237 §1's axes, relayed not observed
    ) -> MemorySearchResult:
        """Answer as the fake does until the armed call, then raise."""
        self.calls += 1
        if self.calls >= self._nth:
            msg = "fake: this band's read is unavailable"
            raise MemoryStoreError(msg)
        return await super().search(query, limit=limit, kinds=kinds, bands=bands, **axes)


@final
class _ReturningTwiceUnderOneId:
    """A searcher whose one response carries the same record twice (§13 item 1).

    §4 is explicit that this is not claimed unreachable: ``SearchOutcome`` constrains
    neither identifier uniqueness nor record count, "so an unreachability argued from
    ``tools/web_search.py`` would be about the shipped searcher and not about the seam
    every ``WebSearcher`` is wired through".
    """

    def __init__(self, records: Sequence[MemoryRecord]) -> None:
        """Hold the records every call answers with."""
        self.records = tuple(records)
        # The **costed** declaration, because this deployment declared its per-call
        # figure: a bare ``FakeWebSearcher`` proposes a tool the binder and the policy
        # are not configured for, and the servicing would resolve to ``BINDING_FAILED``
        # before reaching the answer this arm is about (#2111, ADR-0236).
        self._inner = _CostedSearcher(FakeWebSearcher())

    @property
    def name(self) -> str:
        """The configured source this searcher serves."""
        return self._inner.name

    async def request(self, query: str, /) -> Any:
        """Propose the search exactly as the searcher this wraps proposes it."""
        return await self._inner.request(query)

    async def search(self, call: ToolCall, /, *, timeout: Any = None) -> SearchOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2)
        """Answer as the fake does, with this arm's records in place of its own.

        The outcome is the inner fake's, so its report instant and every other field
        ADR-0231 §10 fixes are what they were; ``records`` is the one field replaced,
        which is ``_RefiningSearcher``'s own discipline one field over.
        """
        outcome = await self._inner.search(call, timeout=timeout)
        return outcome.model_copy(update={"records": self.records})


def _denying() -> ThresholdActionPolicy:
    """A policy that rules ``DENY`` on this deployment's own search.

    ADR-0264 §13 item 3's first side is "a search refused before the send
    (``RULING_DENY``)", and the shipped ``FAKE_WEB_SEARCH`` declares ``RiskLevel.LOW``
    — so a deny floor at ``LOW`` is the deployment's own threshold refusing it, which
    is ADR-0242 §8's own ground for ``DECLINED``: "a policy the operator set".
    """
    return ThresholdActionPolicy(deny_at_risk=RiskLevel.LOW)


async def _prompt(responded: RespondedTurn) -> str:
    """The **system** prompt the production stage assembles for this turn.

    ADR-0227 §7's fidelity rule forbids substituting the renderer whose output the
    assertion is about and permits a fake ``ModelProvider``, so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles the prompt
    and the fake merely records it. The statement is assembled through the production
    :func:`~ai_assistant.orchestration.reads.outbound_statement` for the same reason:
    what the engine gives the stage is §6's assembly and not the loop's raw carriers.
    """
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(
        turn=responded.turn,
        step=None,
        undriven=(),
        search_not_serviced=responded.search_not_serviced,
        outbound=outbound_statement(
            search=responded.outbound_reach,
            egress=None,
            records=responded.outbound_records,
            composes=True,
        ),
    )
    [call] = model.calls
    return next(one.content for one in call.messages if one.role is Role.SYSTEM)


def _assembled(responded: RespondedTurn) -> Any:
    """§6's assembly over one turn's carriers, as the engine performs it."""
    return outbound_statement(
        search=responded.outbound_reach,
        egress=None,
        records=responded.outbound_records,
        composes=True,
    )


# --------------------------------------------------------------------------- #
# §13 item 3, first half: the partition over the enumeration itself             #
# --------------------------------------------------------------------------- #


def test_the_partition_is_total_over_all_seventeen_dispositions() -> None:
    """§13 item 3: "asserted over the **enumeration itself**".

    "The arm walks **every member** of ``SearchDisposition`` and asserts the group §2
    places it in, so a member added without an arm **fails** rather than falling to a
    default — the discipline §18 item 9a of ADR-0231 already holds over
    ``SEARCH_DISPOSITIONS``."

    The enumeration is asserted at **seventeen** first: without that half, a member
    added with no entry in the mapping would be missing from both tables and this arm
    would compare two equally incomplete dictionaries and pass.
    """
    assert len(SearchDisposition) == 17, (
        "ADR-0231 §13's fifteen and ADR-0241's two, less the sixteenth ADR-0247 §6 "
        "removed with the budget — and ADR-0264 §2 places every one"
    )
    assert dict(SEARCH_CONTACTS) == _PARTITION
    assert set(SEARCH_CONTACTS) == set(SearchDisposition), "total, with no member left out"


def test_the_four_that_establish_nothing_either_way_are_named_rather_than_grouped() -> None:
    """§13 item 3: the four, asserted by name and for the reason §2 gives each.

    "It asserts that ``TRANSPORT_FAILED``, ``DEADLINE_EXPIRED``, ``SEARCH_FAILED`` and
    ``PROVIDER_REFUSED`` establish nothing either way, the last over **both** its
    causes, because an implementation reading it as a response is what this arm exists
    to catch."

    ``PROVIDER_REFUSED``'s two causes are ADR-0148 §6's: a response the provider gave
    and this system refused, and an account that changed across the credential read,
    whose limbs "discarded the credential and wrote nothing to any channel — none was
    opened". The member carries no value separating them, which is exactly why the
    honest answer is neither side rather than the more likely one.
    """
    undetermined = {
        one for one, group in SEARCH_CONTACTS.items() if group is OutboundReach.INDETERMINATE
    }

    assert undetermined == {
        SearchDisposition.TRANSPORT_FAILED,
        SearchDisposition.DEADLINE_EXPIRED,
        SearchDisposition.SEARCH_FAILED,
        SearchDisposition.PROVIDER_REFUSED,
    }
    assert SEARCH_CONTACTS[SearchDisposition.PROVIDER_REFUSED] is OutboundReach.INDETERMINATE, (
        "recorded both for a response the provider gave and for an account change that "
        "opened no channel, so neither side is established (ADR-0148 §6, ADR-0264 §2)"
    )


def test_a_response_too_large_is_a_contact_and_a_refused_connection_is_not() -> None:
    """§2: the one reading of ``_result_of``'s docstring that is kept out.

    That docstring groups ``RESPONSE_TOO_LARGE`` with ``TRANSPORT_FAILED`` and
    ``PROVIDER_REFUSED`` as "calls that did not complete as calls", "which is about the
    **invocation's** outcome and not about whether bytes crossed the wire. A response
    too large to carry arrived, because that member is reached only from a reader
    counting octets off the channel; a refused connection did not."
    """
    assert SEARCH_CONTACTS[SearchDisposition.RESPONSE_TOO_LARGE] is OutboundReach.REACHED
    assert SEARCH_CONTACTS[SearchDisposition.TRANSPORT_FAILED] is OutboundReach.INDETERMINATE


def test_an_absent_disposition_at_a_performing_site_is_the_eighteenth_case() -> None:
    """§2: "the absence of a disposition is the eighteenth case".

    "A site establishes an outbound contact where its call **completed and recorded no**
    ``SearchDisposition`` — which is a search that reached the provider and was
    answered, records or none, because ``SearchRefusal.NO_RESULT`` maps to no
    disposition (ADR-0231 §13)."

    The precondition is that a call was performed: a site that performed none
    establishes nothing either way and does not reach this function at all, which the
    servicing arms below assert over a real turn.
    """
    assert contact_of(None) is OutboundReach.REACHED


# --------------------------------------------------------------------------- #
# §2's fold, and §6's assembly                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("carried", "one", "expected"),
    [
        (None, None, None),
        (None, OutboundReach.NOT_REACHED, OutboundReach.NOT_REACHED),
        (OutboundReach.NOT_REACHED, None, OutboundReach.NOT_REACHED),
        (OutboundReach.NOT_REACHED, OutboundReach.INDETERMINATE, OutboundReach.INDETERMINATE),
        (OutboundReach.INDETERMINATE, OutboundReach.NOT_REACHED, OutboundReach.INDETERMINATE),
        (OutboundReach.INDETERMINATE, OutboundReach.REACHED, OutboundReach.REACHED),
        (OutboundReach.REACHED, OutboundReach.INDETERMINATE, OutboundReach.REACHED),
        (OutboundReach.REACHED, OutboundReach.NOT_REACHED, OutboundReach.REACHED),
    ],
)
def test_the_fold_takes_the_least_claiming_answer_available(
    carried: OutboundReach | None, one: OutboundReach | None, expected: OutboundReach | None
) -> None:
    """§2: ``REACHED`` outranks ``INDETERMINATE`` outranks ``NOT_REACHED``.

    "One call that established a contact makes the turn ``REACHED`` however many others
    did not; failing that, one call that established nothing either way makes it
    ``INDETERMINATE`` … The order is the least-claiming one available: a turn is never
    reported as having reached nothing while one of its own calls may have reached
    something."

    **Both directions of each pair are given**, because §6's "assembly accumulates and
    never replaces" is what a last-writer-wins implementation fails and encounter order
    is what it would be sensitive to.
    """
    assert folded_reach(carried, one) is expected


def test_a_turn_that_contributed_nothing_and_composed_carries_not_reached() -> None:
    """§7: the member is ``NOT_REACHED`` and not ``None`` on a turn that reached nothing.

    "It is likewise not ``None`` on an ordinary turn that reached nothing … which is the
    value #2365 needed and did not have."
    """
    statement = outbound_statement(search=None, egress=None, records=0, composes=True)

    assert statement is not None
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0


def test_a_pass_that_neither_reached_nor_composed_carries_nothing() -> None:
    """§7's one ``None`` case, asserted over the assembly.

    "``outbound_statement`` is ``None`` on exactly the passes that **neither established
    a contact nor composed a reply**."
    """
    assert outbound_statement(search=None, egress=None, records=0, composes=False) is None
    assert (
        outbound_statement(
            search=None, egress=OutboundReach.INDETERMINATE, records=0, composes=False
        )
        is None
    ), "an INDETERMINATE send established no contact, so a pass composing none carries nothing"


def test_a_pass_that_reached_carries_the_statement_though_it_composed_nothing() -> None:
    """§7: ``REACHED`` is carried on a pass that composed no reply.

    "A pass that establishes a contact carries the statement whether or not it composes"
    (§1), and §7 fixes the asymmetry's reason: ``REACHED`` reports "an **act this system
    performed**, which the user is owed whether or not prose was written".
    """
    statement = outbound_statement(
        search=OutboundReach.REACHED, egress=None, records=2, composes=False
    )

    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert statement.records == 2


def test_a_send_can_make_the_turn_indeterminate_and_can_never_name_a_class() -> None:
    """§3: the prohibition is over ``REACHED`` **and** over ``destinations``.

    "No component derives ``REACHED``, and none adds an ``OutboundDestination``, from an
    ``EgressBinding``, from ``Disposition.EXECUTED``, from ``StepStatus.SUCCEEDED`` or
    from any combination of them, so no turn is ``REACHED`` on a send's account and no
    class is named on one." What such a turn gets instead is ``INDETERMINATE`` "with
    ``destinations`` empty — the statement saying this system cannot tell".
    """
    statement = outbound_statement(
        search=None, egress=OutboundReach.INDETERMINATE, records=0, composes=True
    )

    assert statement is not None
    assert statement.reach is OutboundReach.INDETERMINATE
    assert statement.destinations == ()


def test_a_search_contact_names_its_class_even_beside_a_driven_send() -> None:
    """§4: a turn that contacted one class through several acts names it once.

    The fold takes ``REACHED`` over the send's ``INDETERMINATE`` (§2), and the class is
    derived from the **search** reach alone — which is §3 written as code rather than as
    a rule to remember.
    """
    statement = outbound_statement(
        search=OutboundReach.REACHED, egress=OutboundReach.INDETERMINATE, records=1, composes=True
    )

    assert statement is not None
    assert statement.reach is OutboundReach.REACHED
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)


# --------------------------------------------------------------------------- #
# §13 item 1: a search that brought records into a non-empty supply             #
# --------------------------------------------------------------------------- #


async def test_a_search_that_yielded_counts_what_it_brought_in_and_not_the_supply() -> None:
    """§13 item 1, and the non-empty pre-existing supply is what makes it discriminate.

    "``destinations`` is ``(SEARCH_PROVIDER,)``; ``records`` counts the records the
    search brought in and **not** the pre-existing ones; ``search_not_serviced`` is
    ``None``; the prompt carries §6's fragment and ``_PLAN_IS_ABOUT_ACTING``. The
    non-empty pre-existing supply is what makes the arm discriminate: a lane reading
    ``ServicedRead.supplied`` passes every other arm and fails this one."

    ``supplied`` is ADR-0238 §11's count of what this servicing sent **to the query
    composer** — assigned before the query is composed and before anything is sent — so
    a lane reading it would report the pre-existing beliefs here and ``0`` on a turn
    whose supply was empty. §4 refuses that population by name.
    """
    store = FakeMemoryStore(now=_clock)
    for ordinal in range(3):
        await store.add(_belief(f"belief-{ordinal}", f"a thing already known, {ordinal}"))
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
        ),
        memory=store,
    )

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == 1, "what the search brought in, not the three held"
    assert responded.search_not_serviced is None, "ADR-0242 §6's eligibility is a disposition"
    statement = _assembled(responded)
    assert statement.destinations == (OutboundDestination.SEARCH_PROVIDER,)
    assert len(responded.turn.memories) > 1, "the pre-existing supply is in front of the turn"
    prompt = await _prompt(responded)
    assert _REACHED_FRAGMENT in prompt
    assert "1 record(s)" in prompt, "§6 interpolates records and nothing else"


async def test_two_records_under_one_id_are_counted_as_the_supply_admitted_them() -> None:
    """§13 item 1's second half: the duplicate enters once and is counted once.

    "**The same search returns two records under one id**, and ``records`` is the count
    the supply admitted — the duplicate enters once (ADR-0226 §7) and is counted once —
    so a lane counting what the response carried fails the arm. No arm asserts that a
    searcher cannot return such a response (§4)."
    """
    # ``_belief``'s shape, because what this arm turns on is the **id** the union
    # deduplicates by and not the provenance: ADR-0226 §7's sameness is "what the supply
    # already holds", and a record offered twice under one id is one arrival whatever
    # minted it.
    twice = _belief("minted-1", "one result, delivered twice")
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(searcher=_ReturningTwiceUnderOneId((twice, twice)), granted=True),
    )

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == 1, "the union deduplicates, and the count is the union's"


# --------------------------------------------------------------------------- #
# §13 item 2: a search that reached the provider and returned nothing           #
# --------------------------------------------------------------------------- #


async def test_a_search_that_found_nothing_carries_a_contact_with_a_count_of_zero() -> None:
    """§13 item 2, on a turn whose pre-existing supply is **non-empty**.

    "``outbound_statement`` is set with ``records`` ``0``, ``search_not_serviced`` is
    ``None`` (ADR-0242 §6's third clause), and the rendered statement states the ``0``
    rather than eliding it." The rendered half is lane 2's; what is asserted here is the
    value it renders from and the fragment the composer is given.

    This is the case §4 says the decision most needs to state: "a turn that reached
    outside itself and brought nothing into its supply … is the one a user cannot tell
    from a turn that did not look, and telling them apart is what #2268 asks for".
    """
    store = FakeMemoryStore(now=_clock)
    await store.add(_belief("belief-0", "a thing already known"))
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(
            searcher=_CostedSearcher(
                FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.NO_RESULT})
            ),
            granted=True,
        ),
        memory=store,
    )

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == 0
    assert responded.search_not_serviced is None, "NO_RESULT maps to no disposition"
    assert "0 record(s)" in await _prompt(responded), "§6 says the zero rather than eliding it"


# --------------------------------------------------------------------------- #
# §13 item 3, second half: the three sides in a turn                            #
# --------------------------------------------------------------------------- #


async def test_a_search_refused_before_the_send_reached_nothing_and_says_which_act() -> None:
    """§13 item 3: ``RULING_DENY`` carries ``NOT_REACHED`` **and** ``DECLINED``.

    ADR-0264 §8's two conditions answering different questions, over one turn: this
    decision's is *the contact's establishment* and ADR-0242 §6's is *the disposition's
    presence*, so a turn whose every servicing refused before the send carries both —
    "``search_not_serviced`` names the act that would help, ``NOT_REACHED`` states that
    nothing left, and neither is read off the other".
    """
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(policy=_denying()),
    )

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is OutboundReach.NOT_REACHED
    assert responded.outbound_records == 0
    assert responded.search_not_serviced is SearchNotServiced.DECLINED
    prompt = await _prompt(responded)
    assert _NOT_REACHED_FRAGMENT in prompt
    assert "the rules this installation is run under declined it" in prompt, (
        "both fragments are given, neither suppressing the other (ADR-0264 §8)"
    )


async def test_a_transport_failure_says_this_system_cannot_tell() -> None:
    """§13 item 3: ``TRANSPORT_FAILED`` carries ``INDETERMINATE``.

    §2's third group reached through the production path rather than constructed: a
    refused connection "is consistent with a request that left and with one that did
    not", and §1 ranks a value that might be false below none in either direction.
    """
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(
            searcher=_CostedSearcher(
                FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.TRANSPORT_FAILED})
            ),
            granted=True,
        ),
    )

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is OutboundReach.INDETERMINATE
    assert responded.search_not_serviced is SearchNotServiced.UNAVAILABLE
    assert _INDETERMINATE_FRAGMENT in await _prompt(responded)


async def test_a_response_received_and_then_refused_carries_both_statements() -> None:
    """§13 item 3: ``UNATTESTED`` carries ``REACHED`` with ``0`` **and** ``UNAVAILABLE``.

    ADR-0264 §8: "One turn's ``UNAVAILABLE`` now rides beside a contact, and that is the
    design. Where a response arrived and was refused … ADR-0242 §8 maps it to
    ``UNAVAILABLE``, whose statement §9 fixes as saying the lookup produced nothing
    usable and expressly **not** saying that no request was made. This decision supplies
    the other half of that sentence, which §9 declined to assert because it had nothing
    establishing it. Read together they say: a request was made, and nothing usable came
    back."
    """
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search()),
        search=_servicer(
            searcher=_CostedSearcher(
                FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.UNATTESTED})
            ),
            granted=True,
        ),
    )

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == 0
    assert responded.search_not_serviced is SearchNotServiced.UNAVAILABLE
    prompt = await _prompt(responded)
    assert _REACHED_FRAGMENT in prompt
    assert "that lookup produced nothing this turn could use" in prompt


# --------------------------------------------------------------------------- #
# §13 item 5: two servicings, and a later one that clears nothing               #
# --------------------------------------------------------------------------- #


async def test_two_servicings_that_both_admit_sum_their_counts_and_name_one_class() -> None:
    """§13 item 5: ``records`` is the **sum**, and the class is carried once.

    "§4 counts one population over the turn — and ``destinations`` carries
    ``SEARCH_PROVIDER`` **once** and not twice." Two servicings is the planner's own
    judgement under ADR-0251 §4 rather than a bound, which is why the case says so with
    the planner.
    """
    turns = _loop(
        planner=SettlesAfter(FakePlanner(now=_clock, read_request=_search())),
        search=_servicer(
            # A refining provider, because ADR-0226 §7 deduplicates an identical answer
            # out: a searcher handing back the same record twice makes the second
            # servicing admit nothing, which is that section working rather than this
            # arm's subject. What the arm is about is **two servicings that both admit**.
            searcher=_RefiningSearcher(_CostedSearcher(FakeWebSearcher(results=(_RESULT,)))),
            granted=True,
        ),
        memory=await _separated(),
        footing=_chosen_footing(),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded(), operation=_REVISING)

    assert len(_serviced_all(captured)) == 2, "two servicings, which is what the arm is about"
    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == 2, "one population over the turn, not the later one's"
    assert _assembled(responded).destinations == (OutboundDestination.SEARCH_PROVIDER,), (
        "one class, carried once and not twice (ADR-0264 §4)"
    )


async def test_a_later_refusal_leaves_the_contact_and_the_count_standing() -> None:
    """§13 item 5: a later servicing refusing before the send changes neither.

    §6: "Assembly accumulates and never replaces. A servicing that establishes no
    contact clears nothing an earlier one established … A last-writer-wins assembly is
    the defect this clause names." The first servicing here reaches the provider and the
    second is refused at the send, which is the encounter order a last-writer-wins fold
    gets wrong.
    """
    turns = _loop(
        planner=SettlesAfter(FakePlanner(now=_clock, read_request=_search())),
        search=_servicer(
            searcher=_RefusingOnceThen(
                _CostedSearcher(FakeWebSearcher(results=(_RESULT,))),
                (None, SearchRefusal.SPEND_REFUSED),
            ),
            granted=True,
        ),
        memory=await _separated(),
        footing=_chosen_footing(),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded(), operation=_REVISING)

    assert [one["disposition"] for one in _serviced_all(captured)] == [
        None,
        SearchDisposition.SPEND_REFUSED.value,
    ]
    assert responded.outbound_reach is OutboundReach.REACHED, "the first call's contact stands"
    assert responded.outbound_records == 1, "and the count it admitted is not reset"
    assert responded.search_not_serviced is SearchNotServiced.SPEND_EXHAUSTED, (
        "ADR-0242 §6's member rides beside it, neither read off the other (ADR-0264 §8)"
    )


# --------------------------------------------------------------------------- #
# §13 item 7: a servicing that failed after its search was answered             #
# --------------------------------------------------------------------------- #


async def test_a_failed_servicing_keeps_the_contact_its_answered_call_established() -> None:
    """§13 item 7's first shape, and §2's invariant is what it rests on.

    "One whose search was answered and whose later ``SIGHTED_QUERY`` raises, recording
    **no disposition**: it carries a contact with ``records`` ``0`` — ADR-0226 §5
    discarded the records, and §4's ``0`` does not suppress the statement — and
    ``search_not_serviced`` ``None``."

    §2: "A contact is established the moment a response arrived, and nothing that
    happens to the enclosing servicing afterwards unmakes it … What ADR-0226 §5 discards
    is the records and not the call: a failed servicing zeroes its counts, so ``records``
    counts what entered the supply, which on that turn is none."
    """
    store = _FailSearchFrom(nth=4)
    await store.add(_belief("belief-0", "a thing already known"))
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search_and_query("bell tower Porto")),
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
        ),
        memory=store,
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded())

    [serviced] = _serviced_all(captured)
    assert serviced["failed"] is True, "the sighted query raised after the search was answered"
    assert serviced["disposition"] is None, "and no disposition was recorded"
    assert responded.outbound_reach is OutboundReach.REACHED, "the call was answered"
    assert responded.outbound_records == 0, "and §5 left the supply as planning saw it"
    assert responded.search_not_serviced is None, "ADR-0242 §6's eligibility is a disposition"


async def test_a_failed_servicing_that_performed_no_call_carries_no_contact() -> None:
    """§13 item 7's third shape, and the pair is what the carrier exists to separate.

    "And one that raised **before** its search was serviced, recording no disposition
    and performing no call: it carries **no** contact. An implementation that suppresses
    a failed servicing's contact fails the first, and one that classifies from the ended
    servicing's record rather than at the performing site cannot tell the first from the
    third (§2)."

    **The two records are identical**, which is the whole of §2's reason for computing
    the fact at the performing site: "an absent disposition on a failed servicing covers
    both a search that was answered and a servicing that raised before its search was
    serviced, and the record holds nothing that separates them — ``failed_after_read_returned``
    is stated over *reads* and not over the send". So this arm asserts the record is the
    same as the one above and the carrier is not.
    """
    store = _FailSearchFrom(nth=4)
    await store.add(_belief("belief-0", "a thing already known"))
    turns = _loop(
        planner=FakePlanner(
            now=_clock,
            read_request=ReadRequest(
                asks=(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="bell tower Porto"),)
            ),
        ),
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
        ),
        memory=store,
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded())

    [serviced] = _serviced_all(captured)
    assert serviced["failed"] is True
    assert serviced["disposition"] is None, "the same record the answered-then-failed turn wrote"
    assert responded.outbound_reach is None, "no call was performed, so nothing is established"
    assert responded.outbound_records == 0
    statement = _assembled(responded)
    assert statement.reach is OutboundReach.NOT_REACHED, "and the turn folds to reaching nothing"


# --------------------------------------------------------------------------- #
# §13 item 9: a turn that made no call at all — #2365's shape                   #
# --------------------------------------------------------------------------- #


async def test_a_turn_that_asked_for_no_search_reaches_nothing_and_says_so() -> None:
    """§13 item 9: #2365's shape, ``servicing=not_asked``.

    "The statement is carried with ``reach`` ``NOT_REACHED``, ``destinations`` **empty**
    and ``records`` ``0``; ``search_not_serviced`` is ``None``; the prompt carries the
    ``NOT_REACHED`` fragment and ``_PLAN_IS_ABOUT_ACTING`` … **An implementation that
    leaves the member ``None`` on such a turn fails this arm**, which is the whole of
    what #2365 records."

    #2365 is a turn whose trail recorded ``servicing=not_asked``, ``servicings=()`` and
    ``stop=not_iterated`` telling the user its forecast "is already in front of me from
    **this turn's searches**". The figures came from retrieved memory of earlier
    conversations — "a legitimate source, and not what the reply said it was".
    """
    turns = _loop(planner=FakePlanner(now=_clock), search=None)

    responded = await turns.respond(_ASK, narrow=_bounded())

    assert responded.outbound_reach is None, "no servicing performed a call"
    assert responded.search_not_serviced is None
    statement = _assembled(responded)
    assert statement.reach is OutboundReach.NOT_REACHED
    assert statement.destinations == ()
    assert statement.records == 0
    assert _NOT_REACHED_FRAGMENT in await _prompt(responded)


# --- §13 item 5's remaining halves: both orders, and what a later servicing leaves ---


@final
class _YieldingCounts:
    """A searcher answering with ``counts[n]`` **distinct** records on its ``n``-th call.

    §13 item 5 asks for two servicings "that both admit records, **in both encounter
    orders**", and a searcher handing back the same one twice cannot show an order at
    all: ADR-0226 §7 deduplicates the second arrival out, so both orders read ``1``
    whatever the fold does. Distinct counts per call are the smallest thing that makes
    the sum discriminate — a lane carrying the *later* servicing's figure reads ``2``
    on one order and ``1`` on the other, and a lane summing reads ``3`` on both.
    """

    def __init__(self, inner: Any, counts: Sequence[int]) -> None:
        """Answer the ``n``-th call with ``counts[n]`` records of its own."""
        self._inner = inner
        self._counts = tuple(counts)
        self.calls = 0

    @property
    def name(self) -> str:
        """The configured source this searcher serves."""
        return str(self._inner.name)

    async def request(self, query: str, /) -> Any:
        """Propose the search exactly as the searcher this wraps proposes it."""
        return await self._inner.request(query)

    async def search(self, call: ToolCall, /, *, timeout: Any = None) -> SearchOutcome:  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2)
        """Answer as the fake does, with this call's own count of distinct records."""
        outcome = await self._inner.search(call, timeout=timeout)
        wanted = self._counts[min(self.calls, len(self._counts) - 1)]
        self.calls += 1
        [template] = outcome.records[:1] or [None]
        assert template is not None, "the inner fake answered with no record to shape"
        shaped: SearchOutcome = outcome.model_copy(
            update={
                "records": tuple(
                    template.model_copy(
                        update={
                            "id": f"minted-{self.calls}-{ordinal}",
                            "content": f"{template.content} ({self.calls}.{ordinal})",
                        }
                    )
                    for ordinal in range(wanted)
                )
            }
        )
        return shaped


@final
class _DenyingFrom:
    """A policy that rules as the production one does until its ``nth`` call, then ``DENY``.

    §13 item 5's "a later servicing that refuses before the send (``RULING_DENY``)"
    needs the **second** ruling to be the refused one, which no threshold can express:
    the two requests of one turn are alike in risk, reversibility, cost and binding.
    So the ordinal is the knob, and everything else is the production policy's own
    reasoning over the deployment's own configuration.
    """

    def __init__(self, inner: ThresholdActionPolicy, *, nth: int) -> None:
        """Deny from the ``nth`` ruling of this policy's life."""
        self._inner = inner
        self._nth = nth
        self.calls = 0

    async def resolve(self, confirmed: Any, *, approved: bool) -> Any:
        """Resolve as the production policy does — no case here answers a confirmation."""
        return await self._inner.resolve(confirmed, approved=approved)

    async def decide(self, request: Any) -> Any:
        """Rule as the production policy does, or deny once the ordinal is reached."""
        from ai_assistant.core.types import PermissionRuling  # noqa: PLC0415 — the returned value

        self.calls += 1
        if self.calls >= self._nth:
            return PermissionRuling(
                outcome=PermissionOutcome.DENY, reason="the operator's own threshold refused it"
            )
        return await self._inner.decide(request)


@pytest.mark.parametrize(("counts", "expected"), [((1, 2), 3), ((2, 1), 3)])
async def test_two_servicings_sum_their_counts_in_either_encounter_order(
    counts: tuple[int, int], expected: int
) -> None:
    """§13 item 5, **both encounter orders**: ``records`` is the sum either way.

    "A turn with two search servicings that both admit records, **in both encounter
    orders**, where ``records`` is the **sum** of what the two admitted — §4 counts one
    population over the turn."

    The counts differ between the servicings precisely so the orders are
    distinguishable: a lane carrying the later servicing's figure reads ``2`` on one
    order and ``1`` on the other, and a lane carrying the earlier one reads them the
    other way round. Only a fold that accumulates reads ``3`` on both.
    """
    turns = _loop(
        planner=SettlesAfter(FakePlanner(now=_clock, read_request=_search())),
        search=_servicer(
            searcher=_YieldingCounts(_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), counts),
            granted=True,
        ),
        memory=await _separated(),
        footing=_chosen_footing(),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded(), operation=_REVISING)

    assert len(_serviced_all(captured)) == 2
    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == expected, "one population over the turn (ADR-0264 §4)"
    assert _assembled(responded).destinations == (OutboundDestination.SEARCH_PROVIDER,), (
        "the class is carried once whichever order the servicings ran in"
    )


async def test_a_later_ruling_deny_leaves_the_contact_and_the_count_standing() -> None:
    """§13 item 5: "A later servicing that refuses before the send (``RULING_DENY``) …

    … leave[s] the contact and the count standing" (§6). ``RULING_DENY`` is §2's third
    group — a stage before the send — so it contributes ``NOT_REACHED``, which the fold
    must not let outrank the first servicing's contact. A last-writer-wins assembly
    reports this turn as having reached nothing while its own first call reached the
    provider, which is the defect §6's accumulate-never-replace clause names.
    """
    policy = _DenyingFrom(
        ThresholdActionPolicy(
            grants=FakeRecipientGrants([], now=lambda: _NOW), configured_search=_CONFIGURED_SEARCH
        ),
        nth=2,
    )
    turns = _loop(
        planner=SettlesAfter(FakePlanner(now=_clock, read_request=_search())),
        search=_servicer(
            searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), policy=policy
        ),
        memory=await _separated(),
        footing=_chosen_footing(),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded(), operation=_REVISING)

    assert [one["disposition"] for one in _serviced_all(captured)] == [
        None,
        SearchDisposition.RULING_DENY.value,
    ]
    assert responded.outbound_reach is OutboundReach.REACHED, "the first call's contact stands"
    assert responded.outbound_records == 1, "and the count it admitted is not reset"
    assert responded.search_not_serviced is SearchNotServiced.DECLINED, (
        "ADR-0242 §6's member rides beside it, neither read off the other (ADR-0264 §8)"
    )


async def test_a_later_servicing_that_failed_after_a_response_leaves_them_standing() -> None:
    """§13 item 5: "and one that fails after a response, each leave the contact … standing".

    The second servicing's search is answered and its later sighted query then raises,
    so ADR-0226 §5 discards everything that servicing fetched — "a failed servicing
    zeroes its counts". What it does **not** discard is the *first* servicing's
    admission, and what it does not unmake is either call's contact: §2's "nothing that
    happens to the enclosing servicing afterwards unmakes it", accumulated by §6's fold.
    """
    store = _FailSearchFrom(nth=7)
    await store.add(_belief("belief-0", "we talked about Porto last week"))
    turns = _loop(
        planner=SettlesAfter(
            FakePlanner(now=_clock, read_request=_search_and_query("bell tower Porto"))
        ),
        search=_servicer(
            searcher=_RefiningSearcher(_CostedSearcher(FakeWebSearcher(results=(_RESULT,)))),
            granted=True,
        ),
        memory=store,
        footing=_chosen_footing(),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded(), operation=_REVISING)

    servicings = _serviced_all(captured)
    assert len(servicings) == 2
    assert servicings[0]["failed"] is False
    assert servicings[1]["failed"] is True, "the second raised after its search was answered"
    assert responded.outbound_reach is OutboundReach.REACHED
    assert responded.outbound_records == 1, (
        "the first servicing's admission stands; the failed one contributed its own zero"
    )


async def test_the_composing_stage_is_given_one_fragment_however_many_servicings_ran() -> None:
    """§13 item 5's last clause: "§6's one fragment is given once".

    §6 gives the composing stage "**one fixed fragment per** ``OutboundReach`` member",
    and the value is "assembled **once per turn**" — so a turn that serviced twice is
    told the fact once, not once per servicing. A lane appending per carrier would put
    the sentence in the prompt twice and leave a model reading two reaches.
    """
    turns = _loop(
        planner=SettlesAfter(FakePlanner(now=_clock, read_request=_search())),
        search=_servicer(
            searcher=_RefiningSearcher(_CostedSearcher(FakeWebSearcher(results=(_RESULT,)))),
            granted=True,
        ),
        memory=await _separated(),
        footing=_chosen_footing(),
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded(), operation=_REVISING)

    assert len(_serviced_all(captured)) == 2
    assert (await _prompt(responded)).count(_REACHED_FRAGMENT) == 1


# --- §13 item 7's second shape: UNATTESTED before the same later failure -------


async def test_a_servicing_recording_unattested_before_a_later_failure_carries_both() -> None:
    """§13 item 7's second shape, and it is the pair §8 says ride together.

    "One whose search recorded **``UNATTESTED``** before the same later failure: it
    carries the contact **and** ``search_not_serviced`` ``UNAVAILABLE`` (§8)."

    Both carriers ride out of the failing servicing for the same reason — §7's fold is
    performed on every path out of the body, so the disposition's member and this
    decision's contact survive the degradation together. A lane that carried one and
    dropped the other would either tell the user a lookup produced nothing usable while
    saying the turn reached nothing, or the reverse.
    """
    store = _FailSearchFrom(nth=4)
    await store.add(_belief("belief-0", "a thing already known"))
    turns = _loop(
        planner=FakePlanner(now=_clock, read_request=_search_and_query("bell tower Porto")),
        search=_servicer(
            searcher=_CostedSearcher(
                FakeWebSearcher(refusals={DEFAULT_COMPOSED_QUERY: SearchRefusal.UNATTESTED})
            ),
            granted=True,
        ),
        memory=store,
    )

    with structlog.testing.capture_logs() as captured:
        responded = await turns.respond(_ASK, narrow=_bounded())

    [serviced] = _serviced_all(captured)
    assert serviced["failed"] is True
    assert serviced["disposition"] == SearchDisposition.UNATTESTED.value
    assert responded.outbound_reach is OutboundReach.REACHED, "the response had already arrived"
    assert responded.outbound_records == 0, "and ADR-0226 §5 discarded what the servicing held"
    assert responded.search_not_serviced is SearchNotServiced.UNAVAILABLE

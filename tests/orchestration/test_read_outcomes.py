"""ADR-0251 §2 at the loop: every outcome reaches the planner, distinguished.

§16's L1 arms that are turn-shaped. Each one drives the **real orchestration path** —
the production :class:`~ai_assistant.orchestration.loop.LearningLoop` over the real
:func:`~ai_assistant.orchestration.reads.service_read_request`, with a scripted planner
and canonical fakes for the seams — and reads the carrier off the argument the planner
was actually handed. §17 is explicit that "no arm is discharged by a unit test of a
helper in isolation", so every member below is driven from a **real source vocabulary
value** rather than from a constructed ``ReadAskOutcome``.

**The companion ask is not scaffolding, it is the reason these arms are honest.** L1
changes no behaviour: ADR-0228 §3's bound is still two and §2's conditions still decide
whether a second call happens at all. A turn whose only ask was refused makes **one**
planner call, so nothing observes its carrier — which is exactly right, and which means
an arm about a refusal has to pair it with an ask that satisfies §2(e) on its own. The
pairing also buys the arm §3 asks for directly: one servicing, several asks, one entry
each, in servicing order.

The classifier's **totality** — §2's precedence over combinations of the four facts
rather than over enum membership — is asserted in the last section, over the one
function and over the one table it reads, because "every member of every vocabulary has
a class" is a statement about a table and not about a turn.
"""

from __future__ import annotations

import inspect
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
import structlog
from test_loop_search import (
    _ASK,
    _RESULT,
    ActionPlanFor,
    _belief,
    _bounded,
    _clock,
    _CostedSearcher,
    _loop,
    _record,
    _serviced,
    _servicer,
)

from ai_assistant import orchestration
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    MemorySearchResult,
    ReadAsk,
    ReadAskOutcome,
    ReadKind,
    ReadOutcomeKind,
    ReadRequest,
    SearchRefusal,
    StructuredAsk,
    TimeWindow,
)
from ai_assistant.orchestration.disclosure import UnboundedAudienceSupply
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.reads import (
    _NON_YIELD_CLASSES,
    _NON_YIELD_VOCABULARIES,
    AskFacts,
    SearchDisposition,
    ServicedRead,
    StopReason,
    StructuredOutcome,
    _NonYieldClass,
    _vocabulary_key,
    classified_reads,
    classify_read_outcome,
)
from ai_assistant.planning.planner import _render_read_outcomes
from ai_assistant.testing import FakeMemoryStore, FakePlanner, FakeWebSearcher
from ai_assistant.testing.queries import DEFAULT_COMPOSED_QUERY

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: The query the one seeded belief answers, so a sighted query really does read it.
_MATCHED: Final = "bell tower"

#: A window no record in any of these stores falls in, so a structured read over it
#: reaches the store and returns nothing — ADR-0240 §6's *empty structured read*, which
#: is the **second** branch of ADR-0228 §2(e) and the one that admits a further round
#: without any record being new.
_EMPTY_WINDOW: Final = StructuredAsk(
    window=TimeWindow(start=datetime(2001, 1, 1, tzinfo=UTC), end=datetime(2002, 1, 1, tzinfo=UTC))
)

#: The seeded belief every case starts from. The retrieval stage puts it in the supply
#: before the servicing, which is what makes a sighted query that re-reads it a
#: **duplicate** rather than a novelty.
_SEEDED: Final = (("belief-1", "the bell tower is in Porto"),)


def _query_ask(text: str = _MATCHED) -> ReadAsk:
    """A sighted query, as the planner composed it."""
    return ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=text)


def _structured_ask() -> ReadAsk:
    """A structured read over a window nothing falls in."""
    return ReadAsk(kind=ReadKind.STRUCTURED_READ, structure=_EMPTY_WINDOW)


async def _outcomes_of(
    *asks: ReadAsk,
    refusal: SearchRefusal | None = None,
    results: Sequence[str] = (_RESULT,),
    seeded: Sequence[tuple[str, str]] = _SEEDED,
) -> tuple[tuple[ReadAskOutcome, ...], FakePlanner]:
    """Run one turn asking for ``asks``, and return what its **second** call was handed.

    **The turn is a production one end to end**: the real ``LearningLoop`` over the real
    servicing site, a real ``SearchServicer`` over canonical fakes, and a planner whose
    only scripting is which request its first plan carries and that its second settles.

    Args:
        asks: What the first plan asks for, in the order it lists them — deliberately
            not ADR-0226 §6's servicing order, so an implementation following the tuple
            fails.
        refusal: What the searcher answers the composed query with, or ``None`` to let
            it answer with ``results``.
        results: What an unrefused search brings back.
        seeded: The beliefs the store holds, as ``(id, content)`` pairs.

    Returns:
        The carrier the second planner call received, and the planner.
    """
    memory = FakeMemoryStore(now=_clock)
    for record_id, content in seeded:
        await memory.add(_belief(record_id, content))
    planner = _searching_planner(*asks)
    searcher = FakeWebSearcher(
        results=tuple(results),
        refusals=None if refusal is None else {DEFAULT_COMPOSED_QUERY: refusal},
    )

    await _loop(
        planner=planner,
        memory=memory,
        search=_servicer(searcher=_CostedSearcher(searcher), granted=True),
    ).respond(_ASK, narrow=_bounded(), operation=ConversationalOperation.CONVERSE)

    assert len(planner.calls) == 2, (
        "ADR-0228 §2's conditions still decide the second call and L1 changes none of "
        "them, so every arm here pairs the ask under test with one that satisfies §2(e) "
        "on its own — a search that minted a record, or ADR-0240 §6's empty structured "
        "read. An arm whose turn made one call would observe no carrier at all."
    )
    return planner.calls[1][6], planner


def _member_for(kind: ReadKind, carried: Sequence[ReadAskOutcome]) -> ReadOutcomeKind:
    """The member one kind's ask reached, asserting it earned exactly one entry."""
    [only] = [one for one in carried if one.ask.kind is kind]
    return only.outcome


def _searching_planner(*asks: ReadAsk) -> FakePlanner:
    """A planner asking for ``asks`` on its first call and settling on its second.

    The revision carries no ``read_request``, so the turn stops at ADR-0228 §2(b) on its
    second call — which makes that call's ``read_outcomes`` the whole of what this module
    reads, and keeps every arm at the two calls L1 leaves the bound at.
    """
    return FakePlanner(now=_clock, read_request=ReadRequest(asks=asks), revision=ActionPlanFor())


# --------------------------------------------------------------------------- #
# §17 arm 2: each of the seven outcomes reaches the planner, distinguished     #
# --------------------------------------------------------------------------- #


async def test_a_read_that_admitted_a_record_reaches_the_planner_as_returned_records() -> None:
    """§2 limb 7: "added at least one record the supply did not already hold".

    Counted after ADR-0226 §7's deduplication. The search mints a record no store holds,
    so it is the one ask in this module that is productive on its own.
    """
    carried, planner = await _outcomes_of(ReadAsk(kind=ReadKind.WEB_SEARCH))

    assert planner.calls[0][6] == (), "a turn's first call is always handed ()"
    assert carried == (
        ReadAskOutcome(
            ask=ReadAsk(kind=ReadKind.WEB_SEARCH), outcome=ReadOutcomeKind.RETURNED_RECORDS
        ),
    )


async def test_a_read_the_source_matched_nothing_for_reaches_the_planner_as_empty() -> None:
    """§2 limb 5: "the source returned no record at all", before deduplication.

    ADR-0240 §6 admitted only a structured read's emptiness; §2 makes an empty read of
    **any** kind a fact about that ask, so the sighted query — the kind §6 explicitly
    withheld — reports it too, and the two are reported alike.
    """
    # No term of it appears as a substring of the one seeded belief, which is what
    # ``FakeMemoryStore.search`` scores on — so the store returns nothing at all rather
    # than returning a record the supply already held.
    unmatched = _query_ask("marmalade")

    carried, _ = await _outcomes_of(unmatched, _structured_ask(), ReadAsk(kind=ReadKind.WEB_SEARCH))

    assert _member_for(ReadKind.SIGHTED_QUERY, carried) is ReadOutcomeKind.EMPTY
    assert _member_for(ReadKind.STRUCTURED_READ, carried) is ReadOutcomeKind.EMPTY
    assert [one.ask.kind for one in carried] == [
        ReadKind.WEB_SEARCH,
        ReadKind.STRUCTURED_READ,
        ReadKind.SIGHTED_QUERY,
    ], "in ADR-0226 §6's servicing order, which is not the order the plan listed them"


async def test_a_read_whose_every_record_was_already_held_reaches_the_planner_as_duplicate() -> (
    None
):
    """§2 limb 6: "it returned records and admitted none after deduplication".

    Precisely ADR-0228 §2(e)'s "a servicing whose every record was deduplicated out", and
    ADR-0240 §6's clause binds verbatim: such a read is **not** empty, because "the store
    returned records, and a planner told otherwise would broaden away from records already
    in front of it". This is the arm a classifier reading the union's admissions rather
    than the store's own return gets wrong — it would report ``EMPTY``.
    """
    carried, planner = await _outcomes_of(_query_ask(), ReadAsk(kind=ReadKind.WEB_SEARCH))

    assert any(record.id == "belief-1" for record in planner.calls[0][3]), (
        "the belief is in the supply before the servicing, so the query's return "
        "deduplicates out rather than being absent"
    )
    assert _member_for(ReadKind.SIGHTED_QUERY, carried) is ReadOutcomeKind.DUPLICATE
    assert _member_for(ReadKind.WEB_SEARCH, carried) is ReadOutcomeKind.RETURNED_RECORDS


async def test_a_read_the_budget_cut_reaches_the_planner_as_truncated() -> None:
    """§2 limb 8: ADR-0226 §6's cut leaves completeness uncertified.

    "It says that completeness was not certified and never that more records exist." The
    search takes three of the ten slots first (ADR-0231 §11), the sighted query is asked
    for exactly the seven that remain, and it fills every one — which is the case ADR-0226
    §6 says the audit records, read here at the planning seam.

    **And limb 8 displaces limb 6 as well as limb 7.** Every record the query returned was
    already in the supply, so an implementation testing the counts before the certification
    would report ``DUPLICATE`` — true of the yield, and silent about the fact the planner
    would act on.
    """
    carried, _ = await _outcomes_of(
        _query_ask("note"),
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        results=("first result", "second result", "third result"),
        seeded=tuple((f"belief-{n}", f"a note number {n}") for n in range(12)),
    )

    assert _member_for(ReadKind.SIGHTED_QUERY, carried) is ReadOutcomeKind.TRUNCATED
    assert _member_for(ReadKind.WEB_SEARCH, carried) is ReadOutcomeKind.RETURNED_RECORDS


async def test_a_source_that_decided_not_to_answer_reaches_the_planner_as_refused() -> None:
    """§2 limb 4: "the source decided not to answer, on a ground it owns".

    ``SearchRefusal.PROVIDER_REFUSED`` is a decision member, and it is what #2169's "an
    inaccessible source produces a justified alternative or an honest stop" turns on: a
    refusal is a decision that will be taken again, so what it licenses is a **different**
    source — the planner's call and not this seam's.

    **Nothing about the ground crosses** (ADR-0242 §9's bar): the member says the source
    decided, and never why.
    """
    carried, _ = await _outcomes_of(
        _structured_ask(),
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        refusal=SearchRefusal.PROVIDER_REFUSED,
    )

    assert _member_for(ReadKind.WEB_SEARCH, carried) is ReadOutcomeKind.REFUSED
    assert _member_for(ReadKind.STRUCTURED_READ, carried) is ReadOutcomeKind.EMPTY


async def test_a_source_whose_answer_was_a_failure_reaches_the_planner_as_failed() -> None:
    """§2 limb 3, and §17 arm 5: "a source failure is not a servicing failure".

    ADR-0231 §17 rules that "every member is returned and none is raised", so a transport
    that fell over is a **completed** servicing carrying a typed non-yield — it satisfies
    ADR-0228 §2(d), reaches the planner as ``FAILED``, and is kept apart from ``REFUSED``,
    which licenses a different next move.
    """
    carried, _ = await _outcomes_of(
        _structured_ask(),
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        refusal=SearchRefusal.TRANSPORT_FAILED,
    )

    assert _member_for(ReadKind.WEB_SEARCH, carried) is ReadOutcomeKind.FAILED


async def test_a_deadline_that_passed_reaches_the_planner_as_expired_and_not_as_failed() -> None:
    """§2 limb 2: ADR-0241 §4's expiry, preserved at the seam where it can be acted on.

    "A deadline that passed says the source may well answer if asked with more room, where
    a transport that failed says nothing of the kind." Asserted against ``FAILED``
    directly, because folding the two is the one way this limb is lost.
    """
    carried, _ = await _outcomes_of(
        _structured_ask(),
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        refusal=SearchRefusal.DEADLINE_EXPIRED,
    )

    assert _member_for(ReadKind.WEB_SEARCH, carried) is ReadOutcomeKind.EXPIRED


async def test_the_rendered_block_states_each_ask_and_what_became_of_it() -> None:
    """§3, §2: the carrier reaches the **production** prompt, and carries no ground.

    ADR-0227 §7's fidelity rule: the assertion is about what the real renderer wrote, so
    the block is read off
    :func:`~ai_assistant.planning.planner._render_read_outcomes` over the very value the
    loop handed the planner. What must not be there is as fixed as what must: no provider
    name, no monetary figure, no count and no ``Settings`` field name (ADR-0242 §9's bar).
    """
    carried, _ = await _outcomes_of(
        _structured_ask(),
        ReadAsk(kind=ReadKind.WEB_SEARCH),
        refusal=SearchRefusal.PROVIDER_REFUSED,
    )

    block = "\n".join(_render_read_outcomes(carried))

    assert "what became of each" in block, "the heading names the block and instructs nothing"
    assert "the source decided not to answer" in block
    assert "nothing at all came back" in block
    for forbidden in ("provider_refused", "brave", "$", "budget", "deadline of"):
        assert forbidden not in block.lower(), f"{forbidden} is a ground, not an outcome"


async def test_a_declined_servicing_puts_no_entry_in_the_carrier() -> None:
    """§2's precedence case 1: ADR-0226 §5's channel scoping decides the whole request.

    "``Servicing`` is not one of the classifier's inputs", because it is the stage's
    disposition for the whole request rather than an answer about one ask —
    ``Servicing.DECLINED`` lands in case 1 by the servicer never being reached, and the
    turn's one planner call was handed ``()`` before anything was serviced.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the bell tower is in Porto"))
    planner = _searching_planner(_query_ask(), ReadAsk(kind=ReadKind.WEB_SEARCH))

    await _loop(planner=planner, memory=memory).respond(
        _ASK,
        narrow=UnboundedAudienceSupply(speakable_attested_sources=frozenset()),
        operation=ConversationalOperation.CONVERSE_SPOKEN,
    )

    assert len(planner.calls) == 1, "ADR-0228 §2(c) fails, so there is no second call"
    assert planner.calls[0][6] == (), "and the one call it made was handed nothing"


# --------------------------------------------------------------------------- #
# §17 arm 3: the classifier is total over the four facts, not over membership  #
# --------------------------------------------------------------------------- #


def _facts(
    *,
    reached: bool = True,
    non_yield: object = None,
    returned: int = 0,
    admitted: int = 0,
    certified: bool = True,
) -> AskFacts:
    """One ask's four facts, defaulted to a completed read that returned nothing."""
    return AskFacts(
        ask=_query_ask(),
        reached=reached,
        non_yield=non_yield,  # type: ignore[arg-type]
        returned=returned,
        admitted=admitted,
        certified=certified,
    )


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        # --- the source answered: limbs 5, 6 and 7 decide from the counts alone ---
        (_facts(returned=0, admitted=0), ReadOutcomeKind.EMPTY),
        (_facts(returned=3, admitted=0), ReadOutcomeKind.DUPLICATE),
        (_facts(returned=3, admitted=1), ReadOutcomeKind.RETURNED_RECORDS),
        (_facts(returned=3, admitted=3), ReadOutcomeKind.RETURNED_RECORDS),
        # --- limb 8 displaces 5, 6 and 7 — and only those ---
        (_facts(returned=0, admitted=0, certified=False), ReadOutcomeKind.TRUNCATED),
        (_facts(returned=3, admitted=0, certified=False), ReadOutcomeKind.TRUNCATED),
        (_facts(returned=3, admitted=3, certified=False), ReadOutcomeKind.TRUNCATED),
        # --- limbs 2, 3 and 4 beat limb 8, whatever the counts and the certification --
        (
            _facts(non_yield=SearchRefusal.DEADLINE_EXPIRED, certified=False),
            ReadOutcomeKind.EXPIRED,
        ),
        (
            _facts(non_yield=SearchRefusal.TRANSPORT_FAILED, returned=3, certified=False),
            ReadOutcomeKind.FAILED,
        ),
        (
            _facts(non_yield=SearchDisposition.RULING_DENY, admitted=2, certified=False),
            ReadOutcomeKind.REFUSED,
        ),
        # --- a source that answered with a typed non-yield still goes to the counts ---
        (
            _facts(non_yield=StructuredOutcome.RETURNED_RECORDS, returned=2, admitted=1),
            ReadOutcomeKind.RETURNED_RECORDS,
        ),
        (
            _facts(non_yield=StructuredOutcome.RETURNED_NOTHING),
            ReadOutcomeKind.EMPTY,
        ),
        (_facts(non_yield=SearchRefusal.NO_RESULT), ReadOutcomeKind.EMPTY),
        # --- limb 1: no entry at all ---
        (_facts(reached=False, returned=3, admitted=3), None),
        (_facts(non_yield=StructuredOutcome.NOT_ASKED), None),
        (_facts(non_yield=StructuredOutcome.NO_SEPARATOR), None),
        (_facts(non_yield=StructuredOutcome.NO_SLOT), None),
        (_facts(non_yield=SearchDisposition.NO_BUDGET), None),
    ],
)
def test_the_precedence_is_decided_by_the_facts_and_not_by_enum_membership(
    facts: AskFacts, expected: ReadOutcomeKind | None
) -> None:
    """§2: "one function over those four facts, evaluated in this order".

    Combinations rather than members, which is the clause this replaces: "the
    implementing lane pins the classifier by enumerating the combinations of the four
    facts … and not by enumerating enum membership". The rows that matter most are the
    ones where one enum value reaches two members — ``StructuredOutcome.RETURNED_RECORDS``
    over a read that admitted a record and one whose every record deduplicated out — and
    the ones where the certification displaces a count.
    """
    assert classify_read_outcome(facts) is expected


def test_an_ask_earning_no_entry_contributes_nothing_to_the_carrier() -> None:
    """§2: "exactly one entry per ask the servicing reached, and every ask it reached has one".

    The no-entry case is a **hole in the sequence**, not a member: the carrier the
    planner receives is shorter than the request's ask list, and nothing marks the gap.
    """
    carried = classified_reads(
        [
            _facts(returned=1, admitted=1),
            _facts(non_yield=StructuredOutcome.NO_SLOT),
            _facts(non_yield=SearchRefusal.TRANSPORT_FAILED),
        ]
    )

    assert [one.outcome for one in carried] == [
        ReadOutcomeKind.RETURNED_RECORDS,
        ReadOutcomeKind.FAILED,
    ]


def test_every_member_of_every_source_vocabulary_is_placed_by_name() -> None:
    """§2: "no default branch and no fallback member", held mechanically.

    The classifier reads exactly one table, and this asserts the table is total over the
    four vocabularies — so a member added to any of them without a class fails here (and
    at import, which is the harder failure) rather than falling through to a silent
    fifth outcome.
    """
    every = {
        _vocabulary_key(member) for vocabulary in _NON_YIELD_VOCABULARIES for member in vocabulary
    }

    assert set(_NON_YIELD_CLASSES) == every
    assert len(every) == 34, (
        "seventeen SearchDisposition, seven SearchRefusal, five FetchRefusal and five "
        "StructuredOutcome; a change to any of those four counts is a change to this table"
    )
    assert set(_NON_YIELD_CLASSES.values()) == set(_NonYieldClass), (
        "every limb is reached by some member, so none is dead"
    )


def test_the_table_is_keyed_so_two_vocabularies_sharing_a_name_are_two_rows() -> None:
    """§2's "no fallback member", held against the hazard that would hide a hole.

    All four vocabularies are ``StrEnum``s and six member names are shared between two of
    them, so a mapping keyed on the member itself hashes
    ``SearchDisposition.SPEND_REFUSED`` and ``SearchRefusal.SPEND_REFUSED`` to **one**
    key — twenty-eight rows presented as thirty-four, with the agreement between the two
    silent rather than checked, and with a member added to one vocabulary tomorrow
    inheriting a class the other decided. The key is the vocabulary's own name beside the
    member's, which is what makes the count above mean what it says.
    """
    collapsed = {member for vocabulary in _NON_YIELD_VOCABULARIES for member in vocabulary}

    assert len(collapsed) == 28, (
        "the collapse is real: this is what keying on the member alone would have given"
    )
    assert _vocabulary_key(SearchRefusal.SPEND_REFUSED) != _vocabulary_key(
        SearchDisposition.SPEND_REFUSED
    )


def test_the_two_spellings_of_one_provider_fact_reach_one_member() -> None:
    """§2: the disposition and the refusal vocabularies overlap, and must not disagree.

    ``SearchRefusal.RESPONSE_TOO_LARGE`` is named a failure by §2 and
    ``SearchDisposition.RESPONSE_TOO_LARGE`` is the same fact one layer out; the same
    holds for ``PROVIDER_REFUSED``, ``TRANSPORT_FAILED``, ``SPEND_REFUSED``,
    ``DEADLINE_EXPIRED`` and ``UNATTESTED``. A value meaning one thing under two
    spellings must not reach a planner under two members.
    """
    shared: Mapping[str, tuple[SearchRefusal, SearchDisposition]] = {
        member.name: (member, SearchDisposition[member.name])
        for member in SearchRefusal
        if member.name in SearchDisposition.__members__
    }

    assert set(shared) == {
        "SPEND_REFUSED",
        "TRANSPORT_FAILED",
        "DEADLINE_EXPIRED",
        "PROVIDER_REFUSED",
        "RESPONSE_TOO_LARGE",
        "UNATTESTED",
    }
    for name, (refusal, disposition) in shared.items():
        assert (
            _NON_YIELD_CLASSES[_vocabulary_key(refusal)]
            is _NON_YIELD_CLASSES[_vocabulary_key(disposition)]
        ), f"{name} is one fact and reaches one member"


# --------------------------------------------------------------------------- #
# §16: "No behaviour changes in L1"                                            #
# --------------------------------------------------------------------------- #


async def test_the_bound_is_still_two_over_a_turn_whose_every_round_was_productive() -> None:
    """§16: "the bound is still two", asserted where a raised one would show.

    A turn whose first servicing minted a record and whose second plan asks for another
    search satisfies every one of ADR-0228 §2's conditions on its second call as well —
    and still stops, because §3's count is unchanged until L2 moves it. What the audit
    records is ``BOUND_REACHED``, which is §3's own stopped-at-the-bound rule.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(_belief("belief-1", "the bell tower is in Porto"))
    searching = ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH),))
    planner = FakePlanner(
        now=_clock,
        read_request=searching,
        revision=ActionPlanFor(read_request=searching),
    )

    with structlog.testing.capture_logs() as captured:
        await _loop(
            planner=planner,
            memory=memory,
            search=_servicer(
                searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
            ),
        ).respond(_ASK, narrow=_bounded(), operation=ConversationalOperation.CONVERSE)

    assert len(planner.calls) == 2, "ADR-0228 §3's two, unmoved by L1"
    assert _record(captured)["stop"] == StopReason.BOUND_REACHED.value


def test_no_stop_reason_is_added_and_the_vocabulary_still_holds_five() -> None:
    """§16: "no progress test runs and no stop reason is added".

    ADR-0251 §7 mints two further members and §15 records the closure moving from five to
    seven — **in L2**. A lane that added one here would be shipping half of §7 without
    the fold that produces it, so the count is pinned as five until that lane lands.
    """
    assert [member.value for member in StopReason] == [
        "not_iterated",
        "settled",
        "bound_reached",
        "budget_reached",
        "planning_failed",
    ]


def test_no_allowance_is_declared_and_no_kind_is_stamped_by_this_lane() -> None:
    """§16: "no allowance is declared, no attempt kind is stamped".

    ADR-0251 §5 puts the declarations in one mapping keyed on ``AttemptKind`` and the
    stamp at the instant an attempt is opened — both L2's. Asserted as an **absence over
    the orchestration package**, because that is the only shape a "not yet" claim can
    take: no module under ``orchestration`` names ``AttemptKind`` at all, so nothing
    reads a figure off one and nothing writes one onto a ledger.
    """
    package = Path(orchestration.__file__).parent
    naming = sorted(
        path.name
        for path in package.rglob("*.py")
        if "AttemptKind" in path.read_text(encoding="utf-8")
    )

    assert naming == [], (
        "§5's declaration mapping and its stamping site are L2's; L1 mints the "
        f"vocabulary and reads it nowhere (found in {naming})"
    )


# --------------------------------------------------------------------------- #
# §3: the carrier mints nothing durable, and the audit is not widened          #
# --------------------------------------------------------------------------- #


def test_the_carrier_reaches_no_durable_record_and_no_store_member() -> None:
    """§3: "the carrier does not span the attempt, and it mints nothing durable".

    "No ``PlanStore`` member, no ``core`` field and no store column is added for it; it
    is an in-process argument built from the turn's own servicings and discarded with the
    turn." Asserted where a later lane would add one: ``PlanStore``'s method set is the
    four ADR-0249 §12 landed plus the plan and execution members it already had, and none
    of them names a read outcome.

    §14 defers a cross-turn carrier with what fires it, and the reason it waits is
    recorded rather than merely obeyed: a ``ReadAsk`` is recoverable from the attempt's
    persisted plans, a typed outcome is recoverable from nothing, so carrying it across
    turns means a ``PlanStore`` widening that ADR-0249 §10 has already booked for A4.
    """
    from ai_assistant.core import protocols  # noqa: PLC0415 — the Protocol is the subject

    signatures = inspect.getsource(protocols.PlanStore)

    assert "ReadAskOutcome" not in signatures
    assert "ReadOutcomeKind" not in signatures
    assert "read_outcome" not in signatures


def test_the_audit_record_gained_no_field_for_the_classifier() -> None:
    """§16: "no behaviour changes in L1", read against ADR-0226 §9's own record.

    ADR-0251 §17 arm 24 gives the audit a per-servicing ``ReadOutcomeKind`` sequence —
    **in L2**, with the attempt's kind, its consumed calls and its declared allowance
    beside it. This lane records the classifier's four facts in memory, classifies them
    at the servicing site and hands the result to the planner, and it widens the Tier 2
    event by nothing at all: a lane that added the sequence here would ship half of arm
    24 without the figures that make it readable.
    """
    assert [field.name for field in fields(ServicedRead)] == [
        "kinds",
        "records",
        "returned",
        "new",
        "deduplicated",
        "labels_unresolved",
        "refusal",
        "disposition",
        "supplied",
        "withheld",
        "supplied_narrowed",
        "structured_axes",
        "structured",
        "truncated_kinds",
        "failed",
        "failed_after_read_returned",
    ]


async def test_a_failed_servicing_carries_no_outcome_for_the_asks_it_had_already_put() -> None:
    """§17 arm 5's second half, and §2's precedence case 1 at its widest.

    "A servicing ADR-0226 §5 left partial fails (d), produces no carrier entry, and
    admits none." The search is serviced **second** and the structured read fourth, so a
    store fault raised by the structured read unwinds past a search that had already
    minted a record — and ADR-0226 §5's all-or-nothing degradation takes the carrier with
    the records, which is the fact this arm exists to pin.
    """
    memory = _FaultingSelect(now=_clock)
    await memory.add(_belief("belief-1", "the bell tower is in Porto"))
    planner = _searching_planner(_structured_ask(), ReadAsk(kind=ReadKind.WEB_SEARCH))

    with structlog.testing.capture_logs() as captured:
        responded = await _loop(
            planner=planner,
            memory=memory,
            search=_servicer(
                searcher=_CostedSearcher(FakeWebSearcher(results=(_RESULT,))), granted=True
            ),
        ).respond(_ASK, narrow=_bounded(), operation=ConversationalOperation.CONVERSE)

    assert responded.turn is not None, "the turn answered from the supply it had (§5)"
    assert _serviced(captured)["failed"] is True
    assert len(planner.calls) == 1, "ADR-0228 §2(d) fails, so no further round is admitted"
    assert planner.calls[0][6] == (), "and nothing of the search's outcome survived with it"


class _FaultingSelect(FakeMemoryStore):
    """A store whose structured read raises, after the search has already minted.

    ADR-0226 §5's fault, taken at the **fourth** kind so that the servicing is genuinely
    partial: the search ran, the union holds its record, and the degradation still leaves
    the supply as planning saw it.
    """

    async def select(self, **kwargs: object) -> MemorySearchResult:
        """Raise, as a store whose structured read is unavailable does."""
        del kwargs
        msg = "fake: the structured read is unavailable"
        raise MemoryStoreError(msg)

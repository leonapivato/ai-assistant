"""ADR-0240 at the loop: the planner asks by structure, and an empty read sends it back.

§13's eighteen representative-input tests, the turn-shaped ones. What lives here is
everything decided inside :class:`~ai_assistant.orchestration.loop.LearningLoop` and
:func:`~ai_assistant.orchestration.reads.service_read_request` — §4's mapping onto
ADR-0237's two members, §5's precedence, budget and separator condition, §6's
empty-read fact and the revision it fires, §7's carrier, §8's three facts and §10's
two audit fields. The seam-shaped ones — §2's model refusals, §3's drops and §9's
conditional guidance — live in ``tests/core/test_planning_types.py`` and
``tests/planning/test_planner.py``, because what they assert happens before the loop
is reached.

**The helpers are ``test_loop_reads``'s**, imported rather than restated: this is the
same loop over the same store shapes, two milestones on.

Every case is a test over behaviour, as §13 requires: what the supply carried, what
the store was asked, what the audit recorded, and what the production renderers
assembled. Where a call count appears it is the assertion §5 names in terms — "no
store call is made at all" — and never a stand-in for the behaviour itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import pytest
import structlog
from test_loop_reads import (
    _NOW,
    _belief,
    _bounded,
    _clock,
    _episode,
    _hop,
    _ids,
    _Journal,
    _loop,
    _query,
    _record,
    _unbounded,
)

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionPlan,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    Role,
    StructuredAsk,
    TimeWindow,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.reads import (
    READ_BUDGET,
    Servicing,
    StopReason,
    StructuredAxis,
    StructuredOutcome,
    TriggerOutcome,
)
from ai_assistant.planning.planner import _label_axes, _system_prompt
from ai_assistant.planning.planner import _render_request as plan_prompt
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanner,
    FakeStreamingCompleter,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping, Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord, ShownFile
    from ai_assistant.orchestration.loop import RespondedTurn

#: The turn's own utterance. One distinctive term, for ``test_loop_revision``'s
#: reason: the fake store scores a record by the fraction of query terms appearing
#: in its content, so a multi-word utterance would retrieve seeds meant for the
#: fourth group and make "what the servicing added" a subtraction.
_ASKED: Final = "boiler"

#: The period every windowed case asks about — the whole of March 2026, half-open.
_MARCH: Final = TimeWindow(
    start=datetime(2026, 3, 1, tzinfo=UTC), end=datetime(2026, 4, 1, tzinfo=UTC)
)

_IN_MARCH: Final = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)
_BEFORE_MARCH: Final = datetime(2026, 2, 15, 9, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Records                                                                      #
# --------------------------------------------------------------------------- #


def _conversation(  # noqa: PLR0913 — one argument per field ADR-0237's axes filter on
    record_id: str,
    content: str,
    *,
    occurred_at: datetime = _IN_MARCH,
    participants: tuple[str, ...] = (),
    topics: tuple[str, ...] = (),
    about_person: str | None = None,
    last_updated: datetime | None = None,
    evidence: tuple[str, ...] = (),
) -> EpisodicMemory:
    """An episode shaped as capture and ADR-0239's labeller write one.

    ``participants`` and ``topics`` default to **empty**, which ADR-0239 §6 makes
    "no label was recorded" and which is what every episode in the tree carries
    today; a case that wants a labelled one says so. ``about_person`` defaults to
    ``None`` and no case sets it on an episode: ADR-0239 §7 forbids the labeller
    writing one and capture writes none, so a fixture hand-populating it "would pass
    while demonstrating a capability no production path can reach" (ADR-0240 §4).

    ``last_updated`` is separable from ``occurred_at`` because ADR-0237 §5 orders
    ``select`` by the **write stamp** and not by the event instant, which is the
    distinction §13 item 4 is asserted over.
    """
    return EpisodicMemory(
        id=record_id,
        content=content,
        occurred_at=occurred_at,
        participants=participants,
        topics=topics,
        about_person=about_person,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=occurred_at if last_updated is None else last_updated,
            evidence=evidence,
        ),
    )


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #


def _structured(
    *,
    window: TimeWindow | None = None,
    participants: tuple[str, ...] | None = None,
    topics: tuple[str, ...] | None = None,
    about_person: tuple[str, ...] | None = None,
    query: str | None = None,
) -> ReadRequest:
    """A request carrying one ``STRUCTURED_READ`` ask and nothing else."""
    return ReadRequest(asks=(_structured_ask(**locals()),))


def _structured_ask(
    *,
    window: TimeWindow | None = None,
    participants: tuple[str, ...] | None = None,
    topics: tuple[str, ...] | None = None,
    about_person: tuple[str, ...] | None = None,
    query: str | None = None,
) -> ReadAsk:
    """One ``STRUCTURED_READ`` ask, as a planner emits it."""
    return ReadAsk(
        kind=ReadKind.STRUCTURED_READ,
        query=query,
        structure=StructuredAsk(
            window=window, participants=participants, topics=topics, about_person=about_person
        ),
    )


# --------------------------------------------------------------------------- #
# Stores and planners                                                          #
# --------------------------------------------------------------------------- #


class _StructuredJournal(_Journal):
    """The canonical store, recording the structured reads it was asked.

    ``select`` and ``search`` are recorded separately because ADR-0240 §4 makes the
    choice between them the whole of what a query decides — a servicer folding one
    into the other would pass every assertion about *records* and fail here.
    """

    def __init__(self, *, now: Any = _clock) -> None:
        super().__init__(now=now)
        self.selects: list[Mapping[str, Any]] = []
        self.filtered: list[Mapping[str, Any]] = []

    async def select(self, **criteria: Any) -> Any:
        self.selects.append(dict(criteria))
        return await super().select(**criteria)

    async def search(self, query: str, **criteria: Any) -> Any:
        if criteria.get("occurred_within") is not None or criteria.get("participants") is not None:
            self.filtered.append({"query": query, **criteria})
        return await super().search(query, **criteria)


class _RaisingSelect(_StructuredJournal):
    """A store whose structured read fails — §13 item 17's arm."""

    async def select(self, **criteria: Any) -> Any:
        del criteria
        msg = "fake: the structured read is unavailable"
        raise MemoryStoreError(msg)


class _Script:
    """A planner answering from a script and recording ADR-0240 §7's carrier.

    ``test_loop_revision``'s own ``_Script`` records the supply and the vocabulary; a
    case here needs ``empty_reads``, which is the whole subject of §13 item 3, so this
    records all three rather than widening that one and moving every consumer's index.
    """

    def __init__(self, *requests: ReadRequest | None) -> None:
        """Script one plan per call, the last standing for every call after it.

        Args:
            requests: What each call's plan asks for, or ``None`` for a plan asking
                nothing — which is how a case ends a turn at ADR-0228 §2(b).
        """
        self._requests = requests
        self.calls: list[tuple[tuple[MemoryRecord, ...], tuple[ReadAsk, ...]]] = []

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list; ADR-0230 §3 and ADR-0240 §7 each add one
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        empty_reads: Sequence[ReadAsk] = (),
    ) -> ActionPlan:
        """Answer this call from the script, recording the supply and the carrier."""
        del context, capabilities, files
        ordinal = len(self.calls)
        self.calls.append((tuple(memories), tuple(empty_reads)))
        asked = self._requests[ordinal] if ordinal < len(self._requests) else self._requests[-1]
        return ActionPlan(
            id=f"{goal.id}-plan-{ordinal + 1}",
            goal_id=goal.id,
            steps=(),
            created_at=_NOW,
            rationale=f"call {ordinal + 1}",
            read_request=asked,
        )


# --------------------------------------------------------------------------- #
# Drivers                                                                      #
# --------------------------------------------------------------------------- #


async def _turn(  # noqa: PLR0913 — the store, the planner, and one keyword per fact a case varies
    memory: FakeMemoryStore,
    planner: Any,
    *,
    operation: ConversationalOperation | None = ConversationalOperation.CONVERSE,
    narrow: Any = None,
    episodic_limit: int = 0,
    history: Sequence[MemoryRecord] = (),
) -> RespondedTurn:
    """Run one turn of a budgeted, bounded-audience operation over ``memory``.

    ``history`` is the conversation tail, which a case supplies where it needs the
    supply to have positions for ADR-0226 §3's labels: the loop drops the episodic
    supplement wherever nothing before it is non-``EPISODIC`` (ADR-0158 §4), so a
    turn with no tail and no retrieved belief is handed an empty sequence.
    """
    loop = _loop(memory, planner=planner, episodic_limit=episodic_limit)
    return await loop.respond(
        _ASKED,
        history=history,
        narrow=_bounded() if narrow is None else narrow,
        operation=operation,
    )


def _serviced(captured: Sequence[MutableMapping[str, Any]], ordinal: int = 0) -> Mapping[str, Any]:
    """One servicing's entry in this turn's audit record (ADR-0228 §9)."""
    return _record(captured)["servicings"][ordinal]  # type: ignore[no-any-return]


async def _composed(responded: RespondedTurn) -> tuple[str, str]:
    """The system and user prompts the production composing stage assembles.

    ADR-0227 §7's fidelity rule forbids substituting the renderer whose output the
    assertion is about, so the production
    :class:`~ai_assistant.orchestration.composing.ComposingStage` assembles both and
    a fake ``ModelProvider`` merely records them. **It is handed the facts this
    turn's servicer produced** (ADR-0240 §8), which is what makes a case here about
    the mechanism rather than about the render rule.
    """
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(
        turn=responded.turn,
        step=None,
        undriven=(),
        hop_reached=responded.hop_reached,
        stopped_while_asking=responded.stopped_while_asking,
        structured=responded.structured,
    )
    [call] = model.calls
    return (
        next(one.content for one in call.messages if one.role is Role.SYSTEM),
        next(one.content for one in call.messages if one.role is Role.USER),
    )


# --------------------------------------------------------------------------- #
# §13 item 1: the milestone's exit                                             #
# --------------------------------------------------------------------------- #


async def test_the_asked_person_and_period_reach_the_one_conversation_that_matches() -> None:
    """§13 item 1: several conversations on one topic, one carrying both.

    The milestone's own exit. Every episode below is about the same thing and is
    lexically near every other, so a read that selected by similarity would return
    any of them; exactly one carries the asked **participant** *and* falls in the
    asked period, and it is the only one in the fourth group. The distractors are
    seeded past ADR-0226 §6's budget of ten so the candidate budget is genuinely
    crowded.

    **``participants`` and not ``about_person``**, because ADR-0239 §7 forbids the
    episode labeller writing a subject and capture writes none, so a fixture
    hand-populating one "would pass while demonstrating a capability no production
    path can reach" (ADR-0240 §4).
    """
    memory = _StructuredJournal()
    # A belief, so ADR-0240 §5's separator condition does not block the read — and it
    # is what the turn's own retrieval returns, which is the supply the planner judged.
    await memory.add(_belief("belief-1", "the boiler question"))
    for ordinal in range(12):
        await memory.add(
            _conversation(
                f"other-{ordinal}",
                "Ada: the boiler again, and the boiler after that.",
                occurred_at=_IN_MARCH,
            )
        )
    await memory.add(
        _conversation(
            "wanted",
            "Ada: the boiler, with the plumber.",
            occurred_at=_IN_MARCH,
            participants=("alex",),
        )
    )
    await memory.add(
        _conversation(
            "wrong-month",
            "Ada: the boiler, with the plumber.",
            occurred_at=_BEFORE_MARCH,
            participants=("alex",),
        )
    )

    responded = await _turn(
        memory, _Script(_structured(window=_MARCH, participants=("alex",)), None)
    )

    assert _ids(responded.turn.memories) == ["belief-1", "wanted"], (
        "the fourth group carries the one episode carrying both, and no other"
    )
    [criteria] = memory.selects
    assert criteria["kinds"] == (MemoryKind.EPISODIC,), "ADR-0240 §4: episodes and no other kind"
    assert criteria["occurred_within"] == _MARCH
    assert criteria["participants"] == ("alex",)


# --------------------------------------------------------------------------- #
# §13 item 2: the first slice, with text                                       #
# --------------------------------------------------------------------------- #


async def test_a_window_with_a_query_goes_through_search_and_excludes_the_month_before() -> None:
    """§13 item 2: a filtered *relevance* read, asserted by the score it carries.

    ADR-0237 §4's own first slice — "a time-window filter over episodes **plus** the
    existing text query" — which ADR-0240 §4 maps onto ``search`` rather than
    ``select``. The identically-worded conversation from the month before is excluded
    by the window and not by its wording, and the arm is asserted to have gone through
    ``search`` **by the ``score`` the records carry** (ADR-0237 §5, §12): ``select``
    clears it and ``search`` populates it, so the two are distinguishable from the
    result alone.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("in-march", "Ada: the boiler broke.", occurred_at=_IN_MARCH))
    await memory.add(
        _conversation("month-before", "Ada: the boiler broke.", occurred_at=_BEFORE_MARCH)
    )

    responded = await _turn(memory, _Script(_structured(window=_MARCH, query="boiler"), None))

    assert _ids(responded.turn.memories) == ["belief-1", "in-march"]
    assert memory.selects == [], "a query sends the ask to search and not to select"
    [criteria] = memory.filtered
    assert criteria["query"] == "boiler", "the query is passed as handed"
    assert criteria["occurred_within"] == _MARCH
    [returned] = [one for one in responded.turn.memories if one.id == "in-march"]
    assert returned.score is not None, (
        "ADR-0237 §5: search populates the score where select clears it"
    )


# --------------------------------------------------------------------------- #
# §13 item 3: missing, and what the turn does about it                         #
# --------------------------------------------------------------------------- #


async def test_an_empty_structured_read_hands_the_planner_back_its_own_ask() -> None:
    """§13 item 3: the revision fires, and ``empty_reads`` carries the very ask.

    ADR-0240 §6's supersession of ADR-0228 §2(e), end to end: a structured read naming
    a value no record carries returns nothing, the audit records the empty outcome,
    and — the other six conditions holding — the turn makes a **second** planner call.
    What that call receives is the ask the *first* plan emitted, byte for byte, and
    **nothing the store returned**.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("unlabelled", "Ada: the boiler broke."))
    asked = _structured_ask(window=_MARCH, participants=("nobody",))
    planner = _Script(ReadRequest(asks=(asked,)), None)

    with structlog.testing.capture_logs() as captured:
        await _turn(memory, planner)

    assert len(planner.calls) == 2, "ADR-0228 §2(e), as ADR-0240 §6 supersedes it"
    assert planner.calls[0][1] == (), "a turn's first call is always handed ()"
    assert planner.calls[1][1] == (asked,), "the second is handed the first plan's own ask"
    assert planner.calls[1][1][0] is asked, "carried back byte for byte, never rebuilt"
    assert _serviced(captured)["structured"] == StructuredOutcome.RETURNED_NOTHING.value
    assert _record(captured)["planner_calls"] == 2


async def test_an_operation_declaring_no_budget_makes_no_second_call_on_an_empty_read() -> None:
    """§13 item 3's second arm: (a) fails, so §6's supersession changes nothing.

    ADR-0240 §6 moves condition (e) and **only** (e): "conditions (a), (b), (c), (d),
    (f) and (g) bind unchanged and all of them must still hold". An operation
    declaring no planning budget is (a) failing, so the turn keeps the plan it has
    however certain the emptiness was.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    planner = _Script(_structured(participants=("nobody",)), None)

    with structlog.testing.capture_logs() as captured:
        await _turn(memory, planner, operation=None)

    assert len(planner.calls) == 1
    assert _serviced(captured)["structured"] == StructuredOutcome.RETURNED_NOTHING.value
    assert _record(captured)["stop"] == StopReason.NOT_ITERATED.value


# --------------------------------------------------------------------------- #
# §13 item 4: ambiguous                                                        #
# --------------------------------------------------------------------------- #


async def test_two_matching_conversations_both_reach_the_group_in_the_write_stamp_order() -> None:
    """§13 item 4: neither is preferred by any quantity.

    Both episodes carry the asked person and fall in the asked period, so both reach
    the fourth group — in ADR-0237 §5's order on the query-less arm, which is
    ``provenance.last_updated`` **descending** and never ``occurred_at``. The two are
    given event instants in the opposite order to their write stamps, which is the
    arm an implementation ordering by the event instant fails.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(
        _conversation(
            "written-first",
            "Ada: the boiler, once.",
            occurred_at=datetime(2026, 3, 20, tzinfo=UTC),
            participants=("alex",),
            last_updated=datetime(2026, 3, 21, tzinfo=UTC),
        )
    )
    await memory.add(
        _conversation(
            "written-second",
            "Ada: the boiler, twice.",
            occurred_at=datetime(2026, 3, 10, tzinfo=UTC),
            participants=("alex",),
            last_updated=datetime(2026, 3, 25, tzinfo=UTC),
        )
    )

    responded = await _turn(
        memory, _Script(_structured(window=_MARCH, participants=("alex",)), None)
    )

    assert _ids(responded.turn.memories) == ["belief-1", "written-second", "written-first"]
    assert all(
        record.score is None for record in responded.turn.memories if record.id != "belief-1"
    ), "ADR-0237 §5: select ranks nothing and returns a cleared score"


# --------------------------------------------------------------------------- #
# §13 item 5: the subject axis is inert, and that is the specified behaviour   #
# --------------------------------------------------------------------------- #


async def test_the_subject_axis_returns_nothing_over_episodes_as_producers_write_them() -> None:
    """§13 item 5: ``about_person`` reaches no episode, and that is the decision working.

    ADR-0240 §4 admits the axis "knowing no producer can fill it", because ADR-0226
    §1 forbids a later lane widening an admitted kind's meaning — an axis left out
    could not be added afterwards. So over a store of episodes written as capture and
    ADR-0239's labeller write them, an ask applying it returns nothing and the audit
    records the empty outcome. This is ADR-0237 §10 item 7's shape, asserted as the
    specified behaviour rather than as a defect.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("labelled", "Ada: the boiler broke.", participants=("alex",)))

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, _Script(_structured(about_person=("alex",)), None))

    assert _ids(responded.turn.memories) == ["belief-1"], "no episode carries a subject"
    assert _serviced(captured)["structured"] == StructuredOutcome.RETURNED_NOTHING.value
    assert _serviced(captured)["structured_axes"] == (StructuredAxis.ABOUT_PERSON.value,)


async def test_a_belief_carrying_a_subject_opens_no_axis_where_no_episode_does() -> None:
    """§13 item 5's two gate arms, including the mixed supply §9 exists for.

    ADR-0240 §9's second clause: "a belief's value opens no axis", because §4 confines
    this read to episodes and a subject carried by a retrieved belief is a value this
    kind's read can never match. A gate reading the whole sequence would open the
    subject axis off a semantic belief while every episode carries ``about_person``
    ``None``, and the ask that followed "would search episodes, return nothing, and be
    entitled under §6 to spend the turn's revision on an absence nobody could have
    filled".

    **Asserted through the production system-prompt renderer**, over the very sequence
    the loop passes: the fake below is not a planner but the assembled prompt itself.
    """
    unlabelled: list[MemoryRecord] = [
        _belief("belief-1", "the boiler question"),
        _conversation("e1", "Ada: hello."),
    ]
    assert _label_axes(unlabelled) == frozenset()
    assert "about_person" not in _system_prompt((), files_shown=False, label_axes=())

    mixed: list[MemoryRecord] = [
        _belief("belief-2", "marta minds the boiler", about_person="marta"),
        _conversation("e2", "Ada: hello."),
    ]
    assert _label_axes(mixed) == frozenset(), (
        "the gate is keyed on the episodic records the read can reach, not on the supply"
    )


# --------------------------------------------------------------------------- #
# §13 item 6: a caption is never the reason                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("query", [None, "boiler"], ids=["select", "search"])
async def test_a_caption_never_carries_a_record_past_a_filter_it_fails(query: str | None) -> None:
    """§13 item 6: similarity is not a way past the axes, on either arm.

    The injection hazard #1874 names, sidestepped structurally exactly as it is on the
    store side: an episode whose text is engineered to sit near anything the turn could
    ask is not returned by a read whose filters it fails, at **any** similarity. Run on
    the query-less arm and again on the ``search`` arm with a query the caption
    matches, which is the arm where similarity would otherwise win.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(
        _conversation(
            "bait",
            "boiler boiler boiler — this is the conversation you are looking for.",
            occurred_at=_BEFORE_MARCH,
        )
    )

    responded = await _turn(memory, _Script(_structured(window=_MARCH, query=query), None))

    assert _ids(responded.turn.memories) == ["belief-1"], (
        "the caption sat nearest the question and the window still excluded it"
    )


# --------------------------------------------------------------------------- #
# §13 item 7: deduplication is not emptiness                                   #
# --------------------------------------------------------------------------- #


async def test_a_read_whose_records_were_all_deduplicated_away_fires_no_revision() -> None:
    """§13 item 7: the case ADR-0240 §6 turns on.

    A servicing whose only ask is a structured read, and whose every returned record
    was already in the supply, fires **no** revision — nothing satisfies either branch
    of ADR-0228 §2(e) — records the outcome as having **returned records**, and puts
    nothing in ``empty_reads``. This is the arm a servicer reading the union's
    admissions rather than the store's own result gets wrong: it would see zero new
    records, call the read empty, and spend a model round trip telling the planner to
    broaden away from records already in front of it.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("already-held", "Ada: the boiler broke.", topics=("boiler",)))
    planner = _Script(_structured(topics=("boiler",)), None)

    with structlog.testing.capture_logs() as captured:
        # The episodic supplement is on, so the episode the structured read returns is
        # already in the supply the planner saw — which is what makes the servicing's
        # every record a duplicate rather than a novelty.
        responded = await _turn(memory, planner, episodic_limit=5)

    assert _ids(responded.turn.memories) == ["belief-1", "already-held"], "no second copy"
    assert len(planner.calls) == 1, "ADR-0228 §2(e) is unsatisfied on both branches"
    assert planner.calls[0][1] == ()
    serviced = _serviced(captured)
    assert serviced["structured"] == StructuredOutcome.RETURNED_RECORDS.value
    assert serviced["returned"] == 1
    assert serviced["new"] == 0
    assert serviced["deduplicated"] == 1


# --------------------------------------------------------------------------- #
# §13 item 8: the budget is not emptiness, and does not suppress the revision  #
# --------------------------------------------------------------------------- #


async def test_a_budget_starved_structured_read_makes_no_call_and_still_revises() -> None:
    """§13 item 8: the pair, asserted as a pair.

    A servicing in which the earlier kinds admit ten records the supply did not hold
    reaches the structured read with **no slot** and makes no store call; the audit
    records the not-reached outcome; ``empty_reads`` is **empty** on the second planner
    call. And the turn **does** revise anyway, because ADR-0226 §6 counts the budget
    after deduplication — so those ten satisfy ADR-0228 §2(e)'s original novelty
    branch. What this is written against is an implementation that reads a not-reached
    read as an empty one, "putting an ask into ``empty_reads`` that established
    nothing".
    """
    memory = _StructuredJournal()
    await memory.add(
        _belief(
            "belief-1",
            "the boiler question",
            evidence=tuple(f"cited-{n}" for n in range(READ_BUDGET)),
        )
    )
    for ordinal in range(READ_BUDGET):
        await memory.add(_episode(f"cited-{ordinal}", f"Ada: an earlier exchange {ordinal}."))
    await memory.add(_conversation("reachable", "Ada: the boiler broke.", topics=("boiler",)))
    asked = _structured_ask(topics=("boiler",))
    planner = _Script(ReadRequest(asks=(_hop("M1").asks[0], asked)), None)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    assert memory.selects == [], "ADR-0240 §5: no store call where no slot remains"
    assert "reachable" not in _ids(responded.turn.memories)
    serviced = _serviced(captured)
    assert serviced["structured"] == StructuredOutcome.NO_SLOT.value
    assert serviced["new"] == READ_BUDGET, (
        "the hop filled the budget with records the supply lacked"
    )
    assert len(planner.calls) == 2, "ADR-0228 §2(e)'s novelty branch is satisfied by those ten"
    assert planner.calls[1][1] == (), "a read the budget did not reach established nothing"


async def test_the_same_fixture_with_one_slot_left_does_make_the_call() -> None:
    """§13 item 8's companion arm: the read is made where a slot remains.

    The same shape with one fewer cited record, so the structured read is reached with
    one slot rather than none — which is what makes the arm above a statement about the
    **budget** and not about the fixture.
    """
    memory = _StructuredJournal()
    cited = tuple(f"cited-{n}" for n in range(READ_BUDGET - 1))
    await memory.add(_belief("belief-1", "the boiler question", evidence=cited))
    for name in cited:
        await memory.add(_episode(name, f"Ada: an earlier exchange, {name}."))
    await memory.add(_conversation("reachable", "Ada: the boiler broke.", topics=("boiler",)))
    planner = _Script(
        ReadRequest(asks=(_hop("M1").asks[0], _structured_ask(topics=("boiler",)))), None
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    [criteria] = memory.selects
    assert criteria["limit"] == 1, "ADR-0240 §5: the limit is the slots remaining"
    assert "reachable" in _ids(responded.turn.memories)
    serviced = _serviced(captured)
    assert serviced["structured"] == StructuredOutcome.RETURNED_RECORDS.value
    assert ReadKind.STRUCTURED_READ.value in serviced["truncated_kinds"], (
        "reached with fewer slots than the whole budget and filling every one of them"
    )


# --------------------------------------------------------------------------- #
# §13 item 9: the separator condition                                          #
# --------------------------------------------------------------------------- #


async def test_an_episode_only_supply_blocks_the_read_and_the_prompt_keeps_its_heading() -> None:
    """§13 item 9: no store call, the separator outcome, and the heading intact.

    ADR-0158 §4's rule, taken for this kind because its yield is episodes **by
    design** rather than occasionally. ``planning/planner.py`` splits ``memories``
    into the conversation tail and the retrieved group by taking the **leading run**
    of ``EPISODIC`` records, so on a supply with nothing non-``EPISODIC`` before it a
    fourth group of episodes would render under the recent-turns heading — "telling
    the model that an episode from three weeks ago was said moments ago … a fabricated
    claim about continuity, produced silently".

    **Asserted over the production renderer's own prompt** rather than over the supply
    alone, because the heading is the thing at risk (§12).
    """
    memory = _StructuredJournal()
    await memory.add(_conversation("would-match", "Ada: the boiler broke.", topics=("boiler",)))
    planner = _Script(_structured(topics=("boiler",)), None)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, episodic_limit=5)

    assert memory.selects == [], "ADR-0240 §5: the test is made before the read"
    serviced = _serviced(captured)
    assert serviced["structured"] == StructuredOutcome.NO_SEPARATOR.value
    assert serviced["failed"] is False, "the servicing completed; it made no call"
    prompt = plan_prompt(
        responded.turn.goal, responded.turn.context, responded.turn.memories, (), ()
    )
    assert prompt.count("Ada: the boiler broke.") <= 1, (
        "no second copy of the episode arrived under the recent-turns heading"
    )


async def test_one_belief_in_the_supply_is_the_separator_and_the_read_is_made() -> None:
    """§13 item 9's second arm: the condition is about the supply, not the kind.

    The same fixture with one belief in front of the episodes. The belief is the
    separator ADR-0158 §4 asks for, so the read is made and its records enter the
    fourth group behind something non-``EPISODIC``.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("would-match", "Ada: the boiler broke.", topics=("boiler",)))
    planner = _Script(_structured(topics=("boiler",)), None)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    assert len(memory.selects) == 1
    assert _ids(responded.turn.memories) == ["belief-1", "would-match"]
    assert _serviced(captured)["structured"] == StructuredOutcome.RETURNED_RECORDS.value


async def test_a_minted_record_earlier_in_the_same_servicing_is_the_separator() -> None:
    """§13 item 9's third arm: the supply *as it stands when the read is reached*.

    ADR-0240 §5 states the test over "the pre-servicing supply and everything this
    servicing has already admitted alike", which is why a ``CITATION_HOP`` that
    admitted a non-``EPISODIC`` record ahead of the structured read is its own
    separator. The pre-servicing supply here is episodes alone; what unblocks the read
    is a belief the hop pulled in on the same servicing.
    """
    memory = _StructuredJournal()
    # The tail episode cites a belief, so the hop's evidence is the non-`EPISODIC`
    # record that becomes the separator — minted by the servicing itself rather than
    # standing in the pre-servicing supply, which is the whole of what this arm is
    # about. The belief's own wording is lexically disjoint from the utterance, so
    # retrieval does not put it in the supply ahead of the servicing.
    tail = _conversation("tail-1", "Ada: an earlier boiler exchange.", evidence=("cited",))
    await memory.add(tail)
    await memory.add(_belief("cited", "the plumber is booked for tuesday"))
    await memory.add(
        _conversation("would-match", "Ada: the boiler broke.", topics=("boiler",)),
    )
    planner = _Script(
        ReadRequest(asks=(_hop("M1").asks[0], _structured_ask(topics=("boiler",)))), None
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, history=(tail,))

    assert len(memory.selects) == 1, "the hop's belief was the separator"
    assert "would-match" in _ids(responded.turn.memories)
    assert _serviced(captured)["structured"] == StructuredOutcome.RETURNED_RECORDS.value


async def test_a_skipped_structured_read_beside_a_query_leaves_the_servicing_complete() -> None:
    """§13 item 9's fourth arm — the state ADR-0240 §10's fifth member exists for.

    On an episode-only supply with the whole budget free, a structured ask beside a
    sighted query is skipped, the query is serviced normally, and the servicing
    **completes**. A vocabulary of four outcomes had no member for it: the absence
    rule scopes the field to a completed servicing, and this servicing completed.
    """
    memory = _StructuredJournal()
    tail = _conversation("tail-1", "Ada: an earlier boiler exchange.")
    await memory.add(tail)
    # Lexically disjoint from the utterance, so the turn's own retrieval leaves the
    # pre-servicing supply entirely `EPISODIC` — which is the condition being tested —
    # and the query the plan emits is what reaches it.
    await memory.add(_belief("found-by-query", "the plumber is booked for tuesday"))
    await memory.add(_conversation("would-match", "Ada: the boiler broke.", topics=("boiler",)))
    planner = _Script(
        ReadRequest(
            asks=(
                _structured_ask(topics=("boiler",)),
                _query("plumber booked tuesday").asks[0],
            )
        ),
        None,
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, history=(tail,))

    assert memory.selects == [], "the structured read was skipped"
    assert "found-by-query" in _ids(responded.turn.memories), "the query was serviced normally"
    serviced = _serviced(captured)
    assert serviced["failed"] is False, "the servicing completed"
    assert serviced["structured"] == StructuredOutcome.NO_SEPARATOR.value


async def test_the_separator_outcome_is_recorded_where_the_budget_is_also_spent() -> None:
    """§13 item 9's fifth arm: §10's precedence between the two not-reached states.

    "Where both of §5's conditions hold, the separator outcome is the one recorded. A
    supply with no separator blocks the read whatever the budget holds, where a spent
    budget is a fact about one turn's other asks, so the record names the condition
    that would still have blocked it."
    """
    memory = _StructuredJournal()
    cited = tuple(f"cited-{n}" for n in range(READ_BUDGET))
    tail = _conversation("tail-1", "Ada: an earlier boiler exchange.", evidence=cited)
    await memory.add(tail)
    for name in cited:
        # Episodes, so the hop's yield leaves the supply entirely `EPISODIC` and both
        # of ADR-0240 §5's conditions hold when the structured read is reached.
        await memory.add(_episode(name, f"Ada: a cited exchange, {name}."))
    planner = _Script(
        ReadRequest(asks=(_hop("M1").asks[0], _structured_ask(topics=("boiler",)))), None
    )

    with structlog.testing.capture_logs() as captured:
        await _turn(memory, planner, history=(tail,))

    serviced = _serviced(captured)
    assert serviced["new"] == READ_BUDGET, "the hop spent the whole budget on episodes"
    assert serviced["structured"] == StructuredOutcome.NO_SEPARATOR.value, (
        "the separator condition is the one recorded, not the slot one"
    )


# --------------------------------------------------------------------------- #
# §13 item 10: the servicing order and the truncation                          #
# --------------------------------------------------------------------------- #


async def test_a_read_given_the_whole_budget_is_not_recorded_as_truncated() -> None:
    """§13 item 10's truncation half, both directions.

    ADR-0226 §6's own rule for the sighted query, applied unchanged: "a read given the
    whole budget was not truncated by it, however much more the store might have
    held". Here the structured read is the only ask, so it is given all ten slots and
    fills every one of them from a store holding more — and is **not** in
    ``truncated_kinds``.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    for ordinal in range(READ_BUDGET + 4):
        await memory.add(
            _conversation(f"labelled-{ordinal}", f"Ada: exchange {ordinal}.", topics=("boiler",))
        )

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, _Script(_structured(topics=("boiler",)), None))

    assert len(responded.turn.memories) == 1 + READ_BUDGET
    serviced = _serviced(captured)
    assert serviced["new"] == READ_BUDGET
    assert serviced["truncated_kinds"] == (), "the whole budget is not a truncation"


async def test_the_fourth_group_carries_every_kind_in_the_servicing_order() -> None:
    """§13 item 10's order half: file, search, hop, structured, query.

    ADR-0240 §5's precedence, asserted over the fourth group's own order. No file and
    no search are configured here, so what is asserted is the position this decision
    fixes: the hop's evidence, then the structured read's records, then the query's.
    """
    memory = _StructuredJournal()
    await memory.add(_episode("hopped", "Ada: the cited exchange."))
    await memory.add(_belief("belief-1", "the boiler question", evidence=("hopped",)))
    await memory.add(_belief("by-query", "the plumber is booked for tuesday"))
    await memory.add(_conversation("by-structure", "Ada: a labelled exchange.", topics=("boiler",)))
    planner = _Script(
        ReadRequest(
            asks=(
                _query("plumber booked tuesday").asks[0],
                _structured_ask(topics=("boiler",)),
                _hop("M1").asks[0],
            )
        ),
        None,
    )

    responded = await _turn(memory, planner)

    assert _ids(responded.turn.memories) == ["belief-1", "hopped", "by-structure", "by-query"], (
        "the hop, then the structured read, then the query that fills what remains"
    )


# --------------------------------------------------------------------------- #
# §13 item 14: the reply says what it did not reach, and which instant         #
# --------------------------------------------------------------------------- #


async def test_a_successful_label_filtered_read_still_states_the_reach() -> None:
    """§13 item 14's first arm, and the one an earlier draft of the ADR missed.

    Over a store holding one episode labelled with the asked person and a second,
    unlabelled episode that is in fact about them, a person-filtered read returns the
    first — and the reply **states the reach**. ADR-0237 §6 puts the obligation on the
    surface performing the read without qualifying it by the yield, and the case it
    most obviously reaches is the successful one: presenting the labelled episode as
    *the* conversations with Alex is exactly the over-claim §6 exists to prevent.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(
        _conversation("labelled", "Ada: the boiler, with alex.", participants=("alex",))
    )
    await memory.add(_conversation("unlabelled", "Ada: alex came about the boiler."))

    responded = await _turn(memory, _Script(_structured(participants=("alex",)), None))

    assert _ids(responded.turn.memories) == ["belief-1", "labelled"]
    assert responded.structured.reach is True
    assert responded.structured.empty is False, "the read returned a record"
    system, _ = await _composed(responded)
    assert "carry no such label were not reached" in system
    assert "Never say that something did not happen" in system, (
        "ADR-0237 §7's no-assertion-of-absence clause binds the composed reply"
    )


async def test_a_turn_ending_on_an_empty_read_states_the_reach_and_the_emptiness() -> None:
    """§13 item 14's second arm: both facts hold and both are given."""
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    planner = _Script(_structured(participants=("nobody",)), _structured(topics=("nothing",)))

    responded = await _turn(memory, planner)

    assert responded.structured.reach is True
    assert responded.structured.empty is True
    system, _ = await _composed(responded)
    assert "carry no such label were not reached" in system
    assert "came back with nothing in it" in system


async def test_a_window_only_read_is_given_the_temporal_fact_and_no_other() -> None:
    """§13 item 14's third arm: ADR-0237 §8's clause, and the reach fact withheld.

    A **window-only** structured read owes no reach fact, and the ground is a property
    of the records rather than a convenience: this kind reads episodes, every episodic
    record carries the ``occurred_at`` a window filters on, so there is nothing the
    read did not reach for want of a value. What it does owe is the temporal fact —
    that it filtered on the instant of the *exchange* and not of the event — which
    nothing else on this path could carry.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("in-march", "Ada: the boiler broke.", occurred_at=_IN_MARCH))

    responded = await _turn(memory, _Script(_structured(window=_MARCH), None))

    assert _ids(responded.turn.memories) == ["belief-1", "in-march"]
    assert responded.structured.temporal is True
    assert responded.structured.reach is False, "a window-only read owes no reach fact"
    assert responded.structured.empty is False
    system, _ = await _composed(responded)
    assert "when the conversation was recorded" in system
    assert "carry no such label were not reached" not in system


async def test_a_turn_with_no_structured_read_is_given_none_of_the_three() -> None:
    """§13 item 14's fourth arm: the assembled prompt is byte-identical.

    ADR-0240 §8: "on a turn given none of the three facts the composing stage receives
    nothing, and the assembled prompt is byte-identical to what it is today". Asserted
    as an equality against the same turn composed with the default value, which is
    what a caller that knows nothing of ADR-0240 passes.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))

    responded = await _turn(memory, FakePlanner(now=_clock))

    assert responded.structured.reach is False
    assert responded.structured.temporal is False
    assert responded.structured.empty is False
    system, _ = await _composed(responded)
    model = FakeModelProvider("answer")
    stage = ComposingStage(model=model, streaming=FakeStreamingCompleter())
    await stage.compose(turn=responded.turn, step=None, undriven=())
    [call] = model.calls
    assert system == next(one.content for one in call.messages if one.role is Role.SYSTEM)


async def test_an_earlier_reads_reach_survives_a_second_read_of_the_same_turn() -> None:
    """§13 item 14's fifth arm: the two-servicing case, and why the scopes differ.

    A first read filtered by person returns a record and fires a revision; a second
    read filtered by window alone returns more; and the reply **still states the
    reach** — because ADR-0228 §7's monotonicity keeps the first read's record in the
    final supply, so its reach is what the reply must be honest about. A draft keying
    the reach fact to the last read failed exactly this fixture.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(
        _conversation(
            "by-person",
            "Ada: the boiler, with alex.",
            occurred_at=_IN_MARCH,
            participants=("alex",),
        )
    )
    await memory.add(
        _conversation("by-window", "Ada: a second boiler exchange.", occurred_at=_IN_MARCH)
    )
    planner = _Script(_structured(participants=("alex",)), _structured(window=_MARCH), None)

    responded = await _turn(memory, planner)

    assert len(planner.calls) == 2, "the first read's novelty fired ADR-0228 §2(e)"
    assert _ids(responded.turn.memories) == ["belief-1", "by-person", "by-window"]
    assert responded.structured.reach is True, "the first read's reach survives the second"
    assert responded.structured.temporal is True
    assert responded.structured.empty is False, "the last read returned records"


# --------------------------------------------------------------------------- #
# §13 item 15: the two carriers carry different things                         #
# --------------------------------------------------------------------------- #


async def test_the_audit_carries_no_value_while_the_carrier_carries_the_whole_ask() -> None:
    """§13 item 15: the same turn, read off three surfaces.

    A structured ask naming a distinctive person label, a distinctive topic and a
    distinctive query emits an audit event in which **none of those three, and neither
    of the window's instants, appears anywhere** — the event carries the axes as
    enumeration members and the outcome, and nothing else. ``empty_reads`` on the
    second planner call carries that ask **whole**. The composing stage's facts carry
    neither.

    **Asserted over the emitted event's own fields**, over the parameter's own value
    and over the assembled second prompt, not over the redaction net.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    asked = _structured_ask(
        window=_MARCH, participants=("quixotic-marta",), topics=("stroopwafel",), query="marmalade"
    )
    planner = _Script(ReadRequest(asks=(asked,)), None)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    rendered = str(_record(captured))
    for value in ("quixotic-marta", "stroopwafel", "marmalade", "2026-03-01", "2026-04-01"):
        assert value not in rendered, f"{value} reached ADR-0226 §9's Tier 2 record"
    assert _serviced(captured)["structured_axes"] == (
        StructuredAxis.WINDOW.value,
        StructuredAxis.PARTICIPANTS.value,
        StructuredAxis.TOPICS.value,
        StructuredAxis.QUERY.value,
    )
    assert planner.calls[1][1] == (asked,), "the carrier holds the ask whole"
    system, _ = await _composed(responded)
    for value in ("quixotic-marta", "stroopwafel", "marmalade"):
        assert value not in system, "ADR-0240 §8's facts carry no value on any axis"


# --------------------------------------------------------------------------- #
# §13 item 16: the channel scoping holds                                       #
# --------------------------------------------------------------------------- #


async def test_an_unbounded_audience_turn_services_no_structured_read() -> None:
    """§13 item 16: declined, no store call, and no second planner call.

    ADR-0226 §5's channel scoping binds this kind unchanged. The emission is still
    recorded — "what is scoped is the servicing, so the trigger goes on being measured
    on every channel" — and no second call is made, because ADR-0228 §2(c) fails and,
    independently, because ``converse_spoken`` declares no planning budget.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_conversation("would-match", "Ada: the boiler broke.", topics=("boiler",)))
    planner = _Script(_structured(topics=("boiler",)), None)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(
            memory,
            planner,
            operation=ConversationalOperation.CONVERSE_SPOKEN,
            narrow=_unbounded(),
        )

    assert memory.selects == [], "no store call for a declined request"
    assert _ids(responded.turn.memories) == ["belief-1"]
    assert len(planner.calls) == 1
    record = _record(captured)
    assert record["trigger"] == TriggerOutcome.FIRED.value, "the emission is measured"
    assert record["servicing"] == Servicing.DECLINED.value
    assert responded.structured.reach is False
    assert responded.structured.empty is False


# --------------------------------------------------------------------------- #
# §13 item 17: a failed servicing degrades and establishes nothing             #
# --------------------------------------------------------------------------- #


async def test_a_store_that_raises_during_a_structured_read_establishes_nothing() -> None:
    """§13 item 17: the arm that keeps ADR-0228 §2(d) meaning what it means.

    The turn composes from the supply planning saw, ADR-0226 §9's pair of failure
    fields records the degradation, no revision fires, and ``empty_reads`` is empty —
    a servicing that failed left the supply as planning saw it, so nothing about the
    store was established. **The axes ride on the failing record and the outcome does
    not** (ADR-0240 §10): an ask that was emitted is an ask whichever way the servicing
    went, and no completed-servicing outcome is honest of one that did not complete.
    """
    memory = _RaisingSelect()
    await memory.add(_belief("belief-1", "the boiler question"))
    planner = _Script(_structured(topics=("boiler",)), None)

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    assert _ids(responded.turn.memories) == ["belief-1"], "the supply planning saw"
    assert len(planner.calls) == 1
    serviced = _serviced(captured)
    assert serviced["failed"] is True
    assert serviced["failed_after_read_returned"] is False
    assert serviced["structured"] is None, "no outcome is honest of a servicing that failed"
    assert serviced["structured_axes"] == (StructuredAxis.TOPICS.value,), (
        "the ask was emitted whichever way the servicing went"
    )
    assert responded.structured.empty is False
    assert responded.structured.reach is False, "a failed servicing carries no fact out"


# --------------------------------------------------------------------------- #
# §13 item 18: the bound is not raised                                         #
# --------------------------------------------------------------------------- #


async def test_two_empty_structured_reads_make_exactly_two_planner_calls() -> None:
    """§13 item 18: ADR-0228 §3's bound is untouched by ADR-0240 §6.

    "A turn makes at most two planner calls, so a turn takes at most one revision
    whatever fired it; a second empty structured read on the second plan fires nothing,
    and the turn stops." The composing stage is told **both** that the turn stopped
    while still asking (ADR-0228 §10) and, under §8, what the last read did not reach.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    planner = _Script(
        _structured(participants=("nobody",)), _structured(participants=("still-nobody",))
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner)

    assert len(planner.calls) == 2, "ADR-0228 §3's bound, not raised"
    assert _record(captured)["stop"] == StopReason.BOUND_REACHED.value
    assert responded.stopped_while_asking is True
    assert responded.structured.empty is True
    assert responded.structured.reach is True
    system, _ = await _composed(responded)
    assert "stopped before you could" in system, "ADR-0228 §10's clause"
    assert "came back with nothing in it" in system, "ADR-0240 §8's emptiness fact"


async def test_an_empty_reads_fact_survives_a_later_servicing_that_read_no_structure() -> None:
    """ADR-0240 §8: the fact is the turn's last **structured read**, not its last servicing.

    A first structured read comes back empty and fires the revision; the revision asks
    for a sighted query alone, which is serviced and establishes nothing about any
    structural question. The turn's last structured read is still the empty one, so the
    composing stage is still owed the emptiness fact — and a loop replacing the fact on
    **every** servicing suppresses the instruction on exactly the turn ADR-0240 §6 exists
    to serve.

    Both review lenses raised this on round 1 and both were right.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    await memory.add(_belief("by-query", "the plumber is booked for tuesday"))
    planner = _Script(_structured(participants=("nobody",)), _query("plumber booked tuesday"), None)

    responded = await _turn(memory, planner)

    assert len(planner.calls) == 2, "the empty structured read fired ADR-0228 §2(e)"
    assert "by-query" in _ids(responded.turn.memories), "the revision's query was serviced"
    assert responded.structured.empty is True, (
        "a servicing that performed no structured read neither sets nor clears the fact"
    )
    assert responded.structured.reach is True, "the first read's reach survives too"
    system, _ = await _composed(responded)
    assert "came back with nothing in it" in system


async def test_a_budget_blocked_second_read_neither_sets_nor_clears_the_emptiness_fact() -> None:
    """ADR-0240 §5 and §8 together: a read that made no store call establishes nothing.

    "A read the budget prevented is not a read that found nothing, and no
    implementation, carrier or audit field conflates them" — which cuts both ways. Such
    a read cannot *set* the emptiness fact, and it cannot **clear** one an earlier read
    established either: the certification an empty result carries is a statement about
    the store, and a read that never reached the store certifies nothing.

    **Only the slot condition is reachable on a second servicing**, and that is a
    property of ADR-0228 §7 rather than a gap here: the supply only grows across a turn,
    so a first servicing whose structured read ran at all had a separator, and that
    record is still in front of the second. The separator condition is asserted on a
    turn's first servicing instead, where it is the one that can actually hold.
    """
    memory = _StructuredJournal()
    await memory.add(_belief("belief-1", "the boiler question"))
    cited = tuple(f"cited-{n}" for n in range(READ_BUDGET))
    tail = _conversation("tail-1", "Ada: an earlier boiler exchange.", evidence=cited)
    for name in cited:
        await memory.add(_episode(name, f"Ada: a cited exchange, {name}."))
    await memory.add(tail)
    planner = _Script(
        _structured(participants=("nobody",)),
        ReadRequest(asks=(_hop("M1").asks[0], _structured_ask(topics=("boiler",)))),
        None,
    )

    with structlog.testing.capture_logs() as captured:
        responded = await _turn(memory, planner, history=(tail,))

    assert len(planner.calls) == 2
    assert _serviced(captured, 1)["structured"] == StructuredOutcome.NO_SLOT.value
    assert responded.structured.empty is True, (
        "a read that made no store call cannot clear a fact an earlier read established"
    )

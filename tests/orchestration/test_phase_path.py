"""The thin path's glue, apart from any engine (ADR-0309 §3, ADR-0306 §5, ADR-0308 §4:15).

The conversions between the phases' own shapes, the window planning is shown of the
chat, and the registry and invoker that put the search and remembering in front of
authorizing. The whole path runs in ``test_engine_phases.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from test_activation_state import _admitted

from ai_assistant.core.types import (
    ActivationDigest,
    DigestOutcome,
    EvidenceItem,
    ForecastOutcome,
    ForecastRefusal,
    LabelKind,
    MessageAuthor,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    SearchOutcome,
    SearchRefusal,
    ToolFailureKind,
    ToolOutcome,
    TranscriptMessage,
)
from ai_assistant.orchestration.authorizer import CallVerdict, RoundAuthorization, Verdict
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.digesting import Digested
from ai_assistant.orchestration.held_results import HeldResult
from ai_assistant.orchestration.phase_path import (
    PhaseTools,
    PhaseWorking,
    _extended,
    _forecasted,
    _searched,
    call_outcomes,
    digested_evidence,
    place_window,
)
from ai_assistant.orchestration.planning import (
    CallOutcomeKind,
    PlaceAuthor,
    PlannedCall,
    PlannedRound,
    RefusedCall,
)
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.story_calls import TIDY_STORY_CAPABILITY
from ai_assistant.orchestration.supplied_records import SuppliedRecords
from ai_assistant.orchestration.understanding import TranscriptWindow, _channel_items
from ai_assistant.testing import FakeAuditTrail, FakeForecaster, FakeToolInvoker, FakeWebSearcher
from ai_assistant.testing.forecasting import (
    DEFAULT_FORECAST_LATITUDE,
    DEFAULT_FORECAST_LONGITUDE,
    DEFAULT_FORECAST_ORIGIN,
    DEFAULT_FORECAST_REPORTED_AT,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import ToolCall

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _message(position: int, author: MessageAuthor, text: str) -> TranscriptMessage:
    user = author is MessageAuthor.USER
    return TranscriptMessage(
        conversation_id="c1",
        position=position,
        written_at=_AT,
        author=author,
        text=text,
        device_id="phone" if user else None,
        message_id=f"m-{position}" if user else None,
    )


def test_the_chat_window_is_shown_as_a_place_that_takes_a_message() -> None:
    """ADR-0307 §6:1, §5:6: authors kept, the input marked, links shown as episodes."""
    window = TranscriptWindow(
        conversation=conversation_channel("c1"),
        messages=(
            _message(1, MessageAuthor.USER, "hello"),
            _message(2, MessageAuthor.ASSISTANT, "hi"),
        ),
        input_messages=(_message(3, MessageAuthor.USER, "and now?"),),
        links={1: "act-1"},
    )
    place = place_window(window)
    assert place.takes_message
    assert place.description is not None
    assert [(one.author, one.text, one.is_input, one.episode_id) for one in place.items] == [
        (PlaceAuthor.USER, "hello", False, "activation:act-1"),
        (PlaceAuthor.ASSISTANT, "hi", False, None),
        (PlaceAuthor.USER, "and now?", True, None),
    ]


def test_each_item_carries_the_id_understandings_referent_names_it_by() -> None:
    """A reference understanding resolved to a message reaches planning as that item.

    Pinned against understanding's own referent for the same message, so the two
    spellings of a message's id cannot drift apart.
    """
    window = TranscriptWindow(
        conversation=conversation_channel("c1"),
        messages=(
            _message(4, MessageAuthor.USER, "my father called"),
            _message(5, MessageAuthor.ASSISTANT, "Noted."),
        ),
        replied_to=(_message(2, MessageAuthor.USER, "earlier"),),
        input_messages=(_message(6, MessageAuthor.USER, "call him"),),
        links={4: "act-1"},
    )
    understood = {
        item.position: item.referent.id for item in _channel_items(window) if item.position
    }
    shown = [one.referent_id for one in place_window(window).items if not one.is_input]
    assert shown == [understood[position] for position in sorted(understood)]
    assert shown == ["message:2", "message:4", "message:5"]


def _planned(*calls: ProposedCall, refused: tuple[RefusedCall, ...] = ()) -> PlannedRound:
    planning_round = PlanningRound(id="round:1", recorded_at=_AT, calls=calls)
    return PlannedRound(
        round=planning_round,
        labels=(),
        recorded=True,
        calls=tuple(PlannedCall(one) for one in calls if one not in {r.call for r in refused}),
        refused=refused,
    )


def test_each_call_reaches_planning_as_what_came_of_it() -> None:
    """Planning's check refused, authorizing's verdicts, and a call with no decision yet."""
    calls = (
        ProposedCall(call_id="a", name="x"),
        ProposedCall(call_id="b", name="y"),
        ProposedCall(call_id="c", name="z"),
        ProposedCall(call_id="d", name="w"),
    )
    planned = _planned(*calls, refused=(RefusedCall(calls[0], "named nothing shown"),))
    decided = RoundAuthorization(
        activation_id="act",
        round_id="round:1",
        verdicts=(
            CallVerdict("b", Verdict.NEEDS_YOU, reason="asks the user"),
            CallVerdict("c", Verdict.NOT_DONE, reason="denied"),
        ),
    )
    outcomes = call_outcomes(planned, decided, None)
    assert [(one.call_id, one.kind, one.reason) for one in outcomes] == [
        ("a", CallOutcomeKind.REFUSED, "named nothing shown"),
        ("b", CallOutcomeKind.NEEDS_YOU, "asks the user"),
        ("c", CallOutcomeKind.REFUSED, "denied"),
    ]


def test_a_digest_is_shown_under_the_thing_its_source_label_names() -> None:
    """ADR-0308 §4:15: an item's source label resolves to the record it names."""
    digested = Digested(
        result_id="result:1",
        digest=ActivationDigest(
            result="R1",
            question="when",
            outcome=DigestOutcome.ANSWERED,
            evidence=(EvidenceItem(text="at nine", source="R1"),),
            recorded_at=_AT,
        ),
        labels=(),
        recorded=True,
    )
    shown = digested_evidence(
        digested, (PlanningLabel(label="R1", kind=LabelKind.RESULT, id="result:1"),)
    )
    assert shown.answered
    assert [(one.text, one.source_kind, one.source_id) for one in shown.items] == [
        ("at nine", LabelKind.RESULT, "result:1")
    ]


@pytest.mark.parametrize(
    ("refusal", "outcome"),
    [
        (SearchRefusal.NO_RESULT, ToolOutcome.SUCCEEDED),
        (SearchRefusal.DEADLINE_EXPIRED, ToolOutcome.INDETERMINATE),
        (SearchRefusal.TRANSPORT_FAILED, ToolOutcome.INDETERMINATE),
        (SearchRefusal.PROVIDER_REFUSED, ToolOutcome.FAILED),
        (SearchRefusal.SPEND_REFUSED, ToolOutcome.FAILED),
    ],
)
def test_a_search_refusal_is_a_result_unknown_or_not_done(
    refusal: SearchRefusal, outcome: ToolOutcome
) -> None:
    """A search cut short may have reached the provider, so it is unknown (ADR-0312 §2)."""
    assert _searched(SearchOutcome(refusal=refusal)).outcome is outcome


async def test_the_tools_add_remembering_and_the_search_and_fill_the_searchs_origin() -> None:
    trail = FakeAuditTrail()
    registry = FakeToolInvoker([], ledger=trail, gate=trail)
    searcher = FakeWebSearcher()
    tools = PhaseTools(
        registry=registry, invoker=registry, own_records=(REMEMBER_CANDIDATE,), searcher=searcher
    )
    assert await tools.capabilities() == ("remember", "web_search")
    (offered_search,) = [
        one for one in await tools.offered(("web_search",)) if one.capability == "web_search"
    ]
    assert "origin" in offered_search.system_supplied
    (registered,) = await tools.find("web_search")
    assert registered.system_supplied == ()
    filled = await tools.filled(
        ProposedCall(call_id="c1", name="web_search", arguments={"query": "hours"})
    )
    assert filled.arguments == {"origin": "https://search.example.com", "query": "hours"}
    untouched = ProposedCall(call_id="c2", name="web_search", arguments={})
    assert await tools.filled(untouched) == untouched


async def test_a_search_call_goes_to_its_searcher_and_comes_back_as_its_records() -> None:
    trail = FakeAuditTrail()
    registry = FakeToolInvoker([], ledger=trail, gate=trail)
    searcher = FakeWebSearcher(results=("first", "second"))
    tools = PhaseTools(registry=registry, invoker=registry, searcher=searcher)
    proposal = await searcher.request("hours")
    assert proposal is not None
    call = _allowed(proposal)
    result = await tools.invoke(call, timeout=timedelta(seconds=5))
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output == ("first", "second")
    assert searcher.searched == [call]


async def test_the_tools_offer_the_weather_pull_beside_the_registry_with_no_argument() -> None:
    """ADR-0324 §5:4-§5:5, §3:1, §3:4: the forecast read is offered as the search is.

    The deployment's registry never holds it, the tools list it beside the registry's
    capabilities, planning is offered it with every argument the hub's, and the hub fills
    them all from the forecaster's own proposal, whatever planning wrote for them.
    """
    trail = FakeAuditTrail()
    registry = FakeToolInvoker([], ledger=trail, gate=trail)
    tools = PhaseTools(registry=registry, invoker=registry, forecaster=FakeForecaster())

    assert "forecast_read" not in await registry.capabilities()
    assert [str(one.id) for one in await registry.all_tools()] == []
    assert await tools.capabilities() == ("forecast_read",)
    (offered,) = await tools.offered(("forecast_read",))
    assert set(offered.system_supplied) >= {"origin", "latitude", "longitude"}
    (registered,) = await tools.find("forecast_read")
    assert registered.system_supplied == ()
    filled = await tools.filled(
        ProposedCall(call_id="c1", name="forecast_read", arguments={"latitude": 0.0})
    )
    assert filled.arguments == {
        "origin": DEFAULT_FORECAST_ORIGIN,
        "latitude": DEFAULT_FORECAST_LATITUDE,
        "longitude": DEFAULT_FORECAST_LONGITUDE,
    }


async def test_no_forecaster_or_none_configured_offers_no_weather_pull() -> None:
    """ADR-0324 §5:4: offered only where a forecaster is configured (ADR-0260 §4)."""
    trail = FakeAuditTrail()
    registry = FakeToolInvoker([], ledger=trail, gate=trail)
    unconfigured = PhaseTools(
        registry=registry, invoker=registry, forecaster=FakeForecaster(origin=None)
    )
    absent = PhaseTools(registry=registry, invoker=registry)

    assert await unconfigured.capabilities() == ()
    assert await absent.capabilities() == ()
    assert await unconfigured.forecast_declaration() is None


async def test_a_forecast_read_goes_to_its_forecaster_and_is_attributed_by_the_hub() -> None:
    """ADR-0324 §5:4, §2:4: sent to ``Forecaster.read``, its records held and attributed.

    The records are handed to the activation, and the answer's channel and author are
    noted under the call's decision from the hub's own data: the forecaster's name and
    the instant the provider declared, never the answer's text.
    """
    trail = FakeAuditTrail()
    registry = FakeToolInvoker([], ledger=trail, gate=trail)
    forecaster = FakeForecaster()
    tools = PhaseTools(registry=registry, invoker=registry, forecaster=forecaster)
    proposal = await forecaster.request()
    assert proposal is not None
    call = _allowed(proposal)
    supplied = SuppliedRecords()
    attributions: dict[str, str] = {}

    with PhaseTools.holding(supplied, attributions):
        result = await tools.invoke(call, timeout=timedelta(seconds=5))

    assert forecaster.read_calls == [call]
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert isinstance(result.output, tuple)
    assert len(result.output) == 3
    assert all(isinstance(text, str) and text.startswith("2026-09-0") for text in result.output)
    attribution = attributions[call.decision.id]
    assert '"fake forecast"' in attribution
    assert "a service, the forecast provider, claimed" in attribution
    assert DEFAULT_FORECAST_REPORTED_AT.isoformat() in attribution
    assert "Clear" not in attribution, "never from the answer's text"


@pytest.mark.parametrize(
    ("refusal", "outcome", "kind"),
    [
        (ForecastRefusal.NO_RESULT, ToolOutcome.SUCCEEDED, None),
        (ForecastRefusal.UNATTESTED, ToolOutcome.SUCCEEDED, None),
        (ForecastRefusal.DEADLINE_EXPIRED, ToolOutcome.INDETERMINATE, ToolFailureKind.TIMED_OUT),
        (ForecastRefusal.TRANSPORT_FAILED, ToolOutcome.FAILED, ToolFailureKind.UNAVAILABLE),
        (ForecastRefusal.PROVIDER_REFUSED, ToolOutcome.FAILED, ToolFailureKind.REFUSED),
        (ForecastRefusal.RESPONSE_TOO_LARGE, ToolOutcome.FAILED, ToolFailureKind.REFUSED),
    ],
)
def test_a_forecast_refusal_is_the_outcome_its_ledger_completion_records(
    refusal: ForecastRefusal, outcome: ToolOutcome, kind: ToolFailureKind | None
) -> None:
    """ADR-0306 §5:8, ADR-0321 §4:10, ADR-0324 §8:1: one outcome for both records.

    Acting writes an approved call's effect record from this result, so it is the
    outcome the forecaster's ledger completion records for the same refusal; the
    forecaster's tests pin the same table for the ledger. An answer the provider gave is
    done, a read cut short is unknown, and a call that did not complete is not done. A
    refusal brings no text back, whichever outcome it is.
    """
    result = _forecasted(ForecastOutcome(refusal=refusal))

    assert result.outcome is outcome
    assert (None if result.failure is None else result.failure.kind) is kind
    assert not result.output


async def test_a_forecast_that_described_days_is_done_with_their_texts() -> None:
    """The success arm of the same table: done, with one text per minted record."""
    forecaster = FakeForecaster()
    proposal = await forecaster.request()
    assert proposal is not None
    outcome = await forecaster.read(_allowed(proposal), timeout=timedelta(seconds=5))

    result = _forecasted(outcome)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.failure is None
    assert result.output == tuple(record.content for record in outcome.records)


def test_a_pulls_attribution_follows_its_result_when_a_follow_up_offers_it_again() -> None:
    """ADR-0324 §2:4, ADR-0308 §6:7: noted by decision, carried on by the result's id.

    A follow-up offers the held result under its own decision, so the attribution the
    tools noted under the first call's decision is taken when the result is first held.
    A result no pull brought has none.
    """
    working = PhaseWorking(
        activation_id="act",
        place=place_window(TranscriptWindow(conversation=conversation_channel("c1"), messages=())),
        conversation_id="c1",
        trigger=None,
        owner_records=True,
        round_limit=2,
    )
    working.attributions["decision:forecast"] = "outside content: the weather channel"
    pulled = HeldResult(
        result_id="result:1", round_id="r1", decision_id="decision:forecast", content=("day",)
    )
    other = HeldResult(
        result_id="result:2", round_id="r1", decision_id="decision:search", content=()
    )

    working.held.hold(pulled)
    working.held.hold(other)
    offered = working.held.offer_again("result:1", round_id="r2", decision_id="decision:again")

    assert offered is not None
    assert working.attribution(pulled) == "outside content: the weather channel"
    assert working.attribution(offered) == "outside content: the weather channel"
    assert working.attribution(other) is None


def _allowed(proposal: object) -> ToolCall:
    from ai_assistant.core.types import (  # noqa: PLC0415 — local to the one helper
        ActionRequest,
        PermissionDecision,
        PermissionOutcome,
        PermissionRuling,
        ToolCall,
    )

    assert isinstance(proposal, ActionRequest)
    decision = PermissionDecision.from_request(
        proposal,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test"),
        id="decision:1",
        decided_at=_AT,
    )
    return ToolCall(request=proposal, decision=decision)


def test_the_working_set_answers_the_rules_from_the_latest_rounds_decisions() -> None:
    working = PhaseWorking(
        activation_id="act",
        place=place_window(TranscriptWindow(conversation=conversation_channel("c1"), messages=())),
        conversation_id="c1",
        trigger=None,
        owner_records=True,
        round_limit=2,
    )
    assert (working.rounds, working.latest_round) == (0, None)
    working.planned(_planned(ProposedCall(call_id="a", name="x")))
    assert (working.latest_has_calls, working.latest_authorized) == (True, False)
    working.latest.authorization = RoundAuthorization(
        activation_id="act",
        round_id="round:1",
        verdicts=(CallVerdict("a", Verdict.NEEDS_YOU, reason="asks"),),
    )
    assert working.latest_authorized
    assert not working.latest_allows
    assert working.latest_calls_beyond_tidy_ups


@pytest.mark.parametrize(
    ("names", "beyond"),
    [
        ((), False),
        ((TIDY_STORY_CAPABILITY,), False),
        ((TIDY_STORY_CAPABILITY, TIDY_STORY_CAPABILITY), False),
        (("remember",), True),
        ((TIDY_STORY_CAPABILITY, "note_story"), True),
    ],
    ids=["no-calls", "one-tidy-up", "tidy-ups-only", "a-call", "a-call-beside-a-tidy-up"],
)
def test_only_a_call_other_than_a_tidy_up_brings_a_round(
    names: tuple[str, ...],
    beyond: bool,
) -> None:
    """ADR-0315 §2:1-§2:2: whatever the call brought back; a tidy-up never brings one."""
    working = PhaseWorking(
        activation_id="act",
        place=place_window(TranscriptWindow(conversation=conversation_channel("c1"), messages=())),
        conversation_id="c1",
        trigger=None,
        owner_records=True,
        round_limit=2,
    )
    working.planned(
        _planned(*(ProposedCall(call_id=f"c{i}", name=name) for i, name in enumerate(names)))
    )
    assert working.latest_calls_beyond_tidy_ups is beyond
    with pytest.raises(ValueError, match="at least one round"):
        PhaseWorking(
            activation_id="act",
            place=working.place,
            conversation_id=None,
            trigger=None,
            owner_records=False,
            round_limit=0,
        )


async def test_records_side_by_side_extend_the_episode_one_append_at_a_time() -> None:
    """ADR-0286 §3:4, ADR-0306 §5:17, ADR-0308 §5:2: one owner appends, and no lock.

    Recorders that find the episode being extended await the owner's next append,
    which carries both their additions, and return only once it has returned.
    """
    state = _admitted()
    gate = asyncio.Event()
    running = 0
    most = 0
    appended = 0
    returned: list[int] = []

    async def append() -> None:
        nonlocal running, most, appended
        running += 1
        most = max(most, running)
        await gate.wait()
        running -= 1
        appended += 1

    async def recorder() -> None:
        await _extended(state, append)
        returned.append(appended)

    owner = asyncio.create_task(recorder())
    await asyncio.sleep(0)
    waiting = [asyncio.create_task(recorder()) for _ in range(2)]
    await asyncio.sleep(0)
    assert not any(one.done() for one in waiting)
    gate.set()
    await asyncio.gather(owner, *waiting)

    assert (appended, most) == (2, 1)
    # Every recorder returned once the append carrying its addition had: the second.
    assert returned == [2, 2, 2]
    assert (state.extending, state.extension) == (False, None)


async def test_a_recorder_waiting_on_an_owner_that_stopped_takes_the_appends_over() -> None:
    """The owner cancelled mid-append: the waiting recorder's addition is still appended."""
    state = _admitted()
    gate = asyncio.Event()
    appended = 0

    async def append() -> None:
        nonlocal appended
        await gate.wait()
        appended += 1

    owner = asyncio.create_task(_extended(state, append))
    await asyncio.sleep(0)
    waiting = asyncio.create_task(_extended(state, append))
    await asyncio.sleep(0)
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    gate.set()
    await waiting

    assert appended == 1
    assert (state.extending, state.extension) == (False, None)


def test_a_taken_offers_messages_join_the_place_window_in_the_order_sent() -> None:
    """ADR-0349 §7:21: a renewed offer brings the absorber's own input before what it
    absorbed, and the window shows them oldest first; an absorbed input is not shown."""
    from datetime import UTC, datetime  # noqa: PLC0415 — this case's clock alone

    from ai_assistant.core.types import JoinedInput, RecordedInputMessage  # noqa: PLC0415

    at = datetime(2026, 10, 21, 9, tzinfo=UTC)
    place = conversation_channel("c1")
    working = PhaseWorking(
        activation_id="act",
        place=place_window(TranscriptWindow(conversation=place, messages=())),
        conversation_id="c1",
        trigger=None,
        owner_records=True,
        round_limit=2,
    )

    def joined(text: str, minute: int, position: int, came_from: str) -> JoinedInput:
        return JoinedInput(
            joined_at=at,
            channel=place,
            messages=(
                RecordedInputMessage(
                    text=text, sent_at=at.replace(minute=minute), position=position
                ),
            ),
            taken_over_from=came_from,
        )

    working.take_joined(
        (
            joined("actually three bedrooms", 2, 3, "offering"),
            joined("make it two bedrooms", 1, 2, "offering"),
            joined("near the park", 0, 1, "absorbed-elsewhere"),
        ),
        place,
        taken={"offering"},
    )

    assert [one.text for one in working.place.items] == [
        "make it two bedrooms",
        "actually three bedrooms",
    ]
    assert all(one.is_input for one in working.place.items)
    working.take_joined((), place, taken={"offering"})
    assert len(working.place.items) == 2, "each input is taken once"


def test_a_take_in_a_later_round_lands_among_the_messages_it_came_between() -> None:
    """ADR-0349 §7:21: the window stays in the order sent, by time and then position."""
    from datetime import UTC, datetime  # noqa: PLC0415 — this case's clock alone

    from ai_assistant.core.types import JoinedInput, RecordedInputMessage  # noqa: PLC0415

    at = datetime(2026, 10, 21, 9, tzinfo=UTC)
    place = conversation_channel("c1")
    working = PhaseWorking(
        activation_id="act",
        place=place_window(TranscriptWindow(conversation=place, messages=())),
        conversation_id="c1",
        trigger=None,
        owner_records=True,
        round_limit=2,
    )

    def joined(*messages: tuple[str, int, int]) -> JoinedInput:
        return JoinedInput(
            joined_at=at,
            channel=place,
            messages=tuple(
                RecordedInputMessage(text=text, sent_at=at.replace(minute=minute), position=n)
                for text, minute, n in messages
            ),
            taken_over_from="offering",
        )

    first = joined(("actually three bedrooms", 2, 3))
    later = joined(("make it two bedrooms", 1, 2))
    tied = joined(("and a lift", 2, 5), ("and a garden", 2, 4))
    working.take_joined((first,), place, taken={"offering"})
    working.take_joined((first, later), place, taken={"offering"})
    working.take_joined((first, later, tied), place, taken={"offering"})

    assert [one.text for one in working.place.items] == [
        "make it two bedrooms",
        "actually three bedrooms",
        "and a garden",
        "and a lift",
    ]


def test_a_take_follows_the_mediums_positions_where_the_clock_went_back() -> None:
    """ADR-0349 §7:21: positions decide, as the medium holds them, before any time."""
    from datetime import UTC, datetime  # noqa: PLC0415 — this case's clock alone

    from ai_assistant.core.types import JoinedInput, RecordedInputMessage  # noqa: PLC0415
    from ai_assistant.orchestration.planning import (  # noqa: PLC0415
        PlaceAuthor,
        PlaceItem,
        PlaceWindow,
    )

    place = conversation_channel("c1")
    original = PlaceItem(
        author=PlaceAuthor.USER,
        text="find two-bedroom flats",
        at=datetime(2026, 10, 21, 9, 2, tzinfo=UTC),
        is_input=True,
        referent_id="message:1",
    )
    working = PhaseWorking(
        activation_id="act",
        place=PlaceWindow(takes_message=True, items=(original,)),
        conversation_id="c1",
        trigger=None,
        owner_records=True,
        round_limit=2,
    )
    correction = JoinedInput(
        joined_at=datetime(2026, 10, 21, 9, 3, tzinfo=UTC),
        channel=place,
        messages=(
            RecordedInputMessage(
                text="actually three bedrooms",
                sent_at=datetime(2026, 10, 21, 9, 1, tzinfo=UTC),
                position=2,
            ),
        ),
        taken_over_from="offering",
    )

    working.take_joined((correction,), place, taken={"offering"})

    assert [one.text for one in working.place.items] == [
        "find two-bedroom flats",
        "actually three bedrooms",
    ]

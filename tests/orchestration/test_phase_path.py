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
    LabelKind,
    MessageAuthor,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    SearchOutcome,
    SearchRefusal,
    ToolOutcome,
    TranscriptMessage,
)
from ai_assistant.orchestration.authorizer import CallVerdict, RoundAuthorization, Verdict
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.digesting import Digested
from ai_assistant.orchestration.phase_path import (
    PhaseTools,
    PhaseWorking,
    _extended,
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
from ai_assistant.orchestration.remembering import REMEMBER
from ai_assistant.orchestration.story_calls import TIDY_STORY_CAPABILITY
from ai_assistant.orchestration.understanding import TranscriptWindow, _channel_items
from ai_assistant.testing import FakeAuditTrail, FakeToolInvoker, FakeWebSearcher

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
        registry=registry, invoker=registry, own_records=(REMEMBER,), searcher=searcher
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
        trigger_origin=None,
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
        trigger_origin=None,
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
            trigger_origin=None,
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

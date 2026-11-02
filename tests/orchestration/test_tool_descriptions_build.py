"""ADR-0364 §14:4's tests of lane B, at the stage and the seam each rule lives at.

The engine-level cases, a message into a connection and a task's work speaking, are in
``test_phases_tool_descriptions_build``; these drive planning, the renames' table, the
approval register, the exact parts and the connections search directly, over fakes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from exchange_support import reported, section, tags

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    MessageAuthor,
    NewMessage,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    RequestedCall,
    Reversibility,
    RiskLevel,
    RoundResponse,
    TicketState,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.approval_rules import ALWAYS_NEEDS_APPROVAL, approval_rule
from ai_assistant.orchestration.approvals import Ticket
from ai_assistant.orchestration.channel_kinds import (
    ACCOUNT_KINDS,
    CONNECTION_KINDS,
    EMAIL_ACCOUNT_KIND,
)
from ai_assistant.orchestration.lookups import SEARCH_CONNECTIONS, ConnectionSearch
from ai_assistant.orchestration.message_tools import (
    EMAIL_LABEL_ARGUMENTS,
    exact_words,
    reworded,
)
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CALLS
from ai_assistant.orchestration.phase_path import _forecast_filled, _without
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    CallOutcome,
    CallOutcomeKind,
    ConnectionShown,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
    RefusedCall,
    offered_tools,
)
from ai_assistant.orchestration.remembering import candidate_of, is_remember
from ai_assistant.orchestration.renames import Void, translated
from ai_assistant.testing import FakeConversationStore, FakeToolCallingCompleter, default_prompt
from ai_assistant.tools.forecast import FORECAST_READ
from ai_assistant.tools.send_email import EMAIL
from ai_assistant.tools.web_search import WEB_SEARCH

_AT: Final = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)

#: The origin, a conversation of the hub chat.
_ORIGIN: Final = "conversation:c-here"
#: The person's email account, as the composition root registers it.
_ACCOUNT: Final = "account:gmail-personal"


def _now() -> datetime:
    return _AT


class _Recorder:
    async def record(self, planning_round: PlanningRound, labels: Any) -> None:
        del planning_round, labels


def _stage(*responses: RoundResponse) -> tuple[PlanningStage, FakeToolCallingCompleter]:
    completer = FakeToolCallingCompleter.scripted(*responses)
    ids = iter(f"round:{n}" for n in range(100))
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
        new_id=lambda: next(ids),
    )
    return stage, completer


def _connections(*extra: ConnectionShown) -> tuple[ConnectionShown, ...]:
    conversation = CONNECTION_KINDS["conversation"]
    return (
        ConnectionShown(place=_ORIGIN, kind=conversation),
        ConnectionShown(place="conversation:c-two", kind=conversation),
        ConnectionShown(place="conversation:c-three", kind=conversation),
        ConnectionShown(place="telegram:line", kind=CONNECTION_KINDS["telegram"]),
        ConnectionShown(place="task_scheduler:schedule", kind=CONNECTION_KINDS["task_scheduler"]),
        ConnectionShown(
            place=_ACCOUNT,
            kind=ACCOUNT_KINDS[EMAIL_ACCOUNT_KIND],
            account=EMAIL_ACCOUNT_KIND,
        ),
        *extra,
    )


def _inputs(**fields: Any) -> PlanningInputs:
    values: dict[str, Any] = {
        "activation_id": "a1",
        "place": PlaceWindow(takes_message=True),
        "capabilities": (EMAIL, WEB_SEARCH),
        "connections": _connections(),
        "person_id": OWNER_PERSON_ID,
        "approvals": True,
        "label_arguments": EMAIL_LABEL_ARGUMENTS,
    }
    values.update(fields)
    return PlanningInputs(**values)


# --- Connections (§3) ----------------------------------------------------------------------


async def test_connections_show_the_origin_every_single_place_and_three_of_the_hub_chat() -> None:
    """§3:2-§3:5: each entry under its L label, the hub chat's grouped, and no address."""
    stage, completer = _stage(RoundResponse())
    await stage.plan(_inputs())

    shown = section(completer.last_call.exchange.briefing, "## Connections")
    entries = tags(shown, "connection")
    assert [one.attributes["label"] for one in entries] == ["L1", "L2", "L3", "L4", "L5", "L6"]
    assert shown.startswith("- The hub chat:")
    assert [one.text for one in entries[:3]] == ["a conversation in the hub chat"] * 3
    assert {one.attributes["reaches"] for one in entries[:4]} == {"P1"}
    assert entries[4].attributes["can"].endswith("it takes no message")
    assert entries[5].attributes["reaches"] == "the addresses a call names"
    # §3:4: no identifier, an account's own address among them.
    assert "gmail-personal" not in shown
    assert "c-here" not in shown


async def test_the_situation_names_the_time_and_the_last_stimulus_alone() -> None:
    """§2:2, §3:1: the origin is no longer the situation's."""
    stage, completer = _stage(RoundResponse())
    await stage.plan(_inputs())

    situation = section(completer.last_call.exchange.briefing, "## The situation")
    assert len(situation.split("\n")) == 2
    assert "Places a message" not in completer.last_call.exchange.briefing


async def test_p1_is_the_owner_and_always_in_mind_says_who_it_is() -> None:
    """§4:1-§4:2: the owner's label is minted first, the same in every work."""
    stage, _ = _stage(RoundResponse())
    planned = await stage.plan(_inputs())

    (person,) = [one for one in planned.labels if one.kind is LabelKind.PERSON]
    assert person == PlanningLabel(label="P1", kind=LabelKind.PERSON, id=OWNER_PERSON_ID)


# --- the offer (§9:2, ADR-0356 §4:3) --------------------------------------------------------


async def test_the_offered_tools_stay_identical_across_two_works() -> None:
    """§9:2: no connection enum, so two works with different connections are offered alike."""
    first_stage, first = _stage(RoundResponse())
    second_stage, second = _stage(RoundResponse())
    await first_stage.plan(_inputs())
    await second_stage.plan(
        _inputs(
            connections=(
                ConnectionShown(place="conversation:other", kind=CONNECTION_KINDS["conversation"]),
            )
        )
    )

    assert first.last_call.tools == second.last_call.tools


# --- the result shape (§6) -------------------------------------------------------------------


async def _second_round(outcome: CallOutcome, call: ProposedCall) -> dict[str, Any]:
    stage, completer = _stage(RoundResponse(calls=(call,)), RoundResponse())
    inputs = _inputs()
    first = await stage.plan(inputs)
    await stage.plan(
        replace(
            inputs,
            work=first.work,
            rounds=(first.round,),
            labels=(*inputs.labels, *first.labels),
            outcomes=(replace(outcome, round_id=first.round.id),),
        )
    )
    return reported(completer.calls[1], 0)[0]


async def test_a_call_needing_approval_comes_back_refused_saying_to_ask_with_request_approval() -> (
    None
):
    """§6:3: the outcome planning is shown is refused, with request_approval its why."""
    call = ProposedCall(
        call_id="c1", name="search_web", arguments={"query": "q", "looking_for": "x"}
    )
    shown = await _second_round(
        CallOutcome("r", "c1", CallOutcomeKind.NEEDS_YOU, reason="the policy asks"), call
    )
    assert shown == {
        "outcome": "refused",
        "because": "it needs approval: ask for it with request_approval",
    }


async def test_every_result_opens_with_its_outcome_and_a_not_done_says_why() -> None:
    """§6:1: the outcome first, then why, with any but done."""
    call = ProposedCall(
        call_id="c1", name="search_web", arguments={"query": "q", "looking_for": "x"}
    )
    shown = await _second_round(
        CallOutcome("r", "c1", CallOutcomeKind.NOT_DONE, reason="the search failed"), call
    )
    assert list(shown) == ["outcome", "because"]
    assert shown["outcome"] == "not done"


# --- send_email (§9:11-§9:12) ------------------------------------------------------------------


async def test_an_email_from_a_label_that_is_no_email_account_is_refused() -> None:
    """§9:11: from names an email account connection the work was shown."""
    call = ProposedCall(
        call_id="c1",
        name="send_email",
        arguments={"from": "L1", "to": "maren@example.org", "subject": "Hi", "words": "Hello."},
    )
    stage, _ = _stage(RoundResponse(calls=(call,)))
    planned = await stage.plan(_inputs())

    (refused,) = planned.refused
    assert isinstance(refused, RefusedCall)
    assert "no email account" in refused.reason


async def test_an_email_from_the_accounts_label_names_the_persons_account() -> None:
    """§9:11: the email tool reads the account the label names."""
    call = ProposedCall(
        call_id="c1",
        name="send_email",
        arguments={"from": "L6", "to": "maren@example.org", "subject": "Hi", "words": "Hello."},
    )
    stage, _ = _stage(RoundResponse(calls=(call,)))
    planned = await stage.plan(_inputs())

    (sent,) = planned.calls
    assert sent.call.arguments["from"] == "user"


def test_every_email_needs_approval_and_so_do_the_person_models_calls() -> None:
    """§7:5, §9:12, §13:1: one register, which the effects lines say."""
    assert approval_rule("send_email") is not None
    assert set(ALWAYS_NEEDS_APPROVAL) == {
        "send_email",
        *(str(one.capability) for one in PERSON_MODEL_CALLS),
    }
    for declaration in (EMAIL, *PERSON_MODEL_CALLS):
        assert "Always needs approval first" in declaration.description
    assert approval_rule("send_text") is None


# --- exact parts (§9:6-§9:9) ---------------------------------------------------------------------


def test_an_exact_part_reworded_away_sends_planning_s_words() -> None:
    """§9:7: where a marked part is not in what is to be sent, planning's words go."""
    read = exact_words("Tell her <exact>the gate code is 4471</exact> tonight.")
    assert not isinstance(read, str)
    assert reworded(read) == "Tell her the gate code is 4471 tonight."
    # A rendering that loses the marked part sends the words as planning wrote them.
    lost = replace(read, parts=("a part no wording kept",))
    assert reworded(lost) == read.text


def test_an_unclosed_tag_comes_back_not_done() -> None:
    assert isinstance(exact_words("Say <exact>this"), str)


def test_a_literal_tag_sent_escaped_arrives_as_written() -> None:
    """§9:8: a backslash before a tag sends the tag as literal text."""
    read = exact_words("Type \\<exact> and \\</exact> to mark a part.")
    assert not isinstance(read, str)
    assert reworded(read) == "Type <exact> and </exact> to mark a part."


# --- stored calls under old names (§8:5-§8:6) -------------------------------------------------


def _old_email() -> ToolDefinition:
    """``email`` as the build before ADR-0364 declared it, its `from`, `exact` and attachments."""
    recipient: dict[str, Any] = {
        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
        "x-egress-destination": "smtp",
        "x-egress-tier": "personal",
    }
    return ToolDefinition(
        id="email",
        capability="email",
        description="Send an email to the recipients.",
        risk_level=RiskLevel.HIGH,
        reversibility=Reversibility.IRREVERSIBLE,
        side_effecting=True,
        reads=(DataTier.SECRET,),
        writes=(),
        discloses=(DataTier.PERSONAL,),
        cost=ToolCost(basis=CostBasis.UNKNOWN),
        idempotency=Idempotency.NONE,
        effect=CapabilityEffect.WORLD,
        leaves_hub=True,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=True,
        safe_to_repeat=False,
        parameters_schema={
            "type": "object",
            "properties": {
                "to": recipient,
                "subject": {"type": "string"},
                "words": {"type": "string"},
                "attachments": {"type": "array", "items": {"type": "string"}},
                "from": {"type": "string", "enum": ["assistant", "user"]},
                "exact": {"type": "boolean"},
            },
            "required": ["to", "subject", "words"],
            "additionalProperties": False,
        },
    )


def _waiting(values: dict[str, Any]) -> RequestedCall:
    return RequestedCall(tool=_old_email(), values=values)


def test_a_waiting_email_request_from_before_the_build_runs_as_send_email() -> None:
    """§8:6: read with the new declaration, `from` the person's account, `exact` the words."""
    read = translated(
        _waiting(
            {
                "to": "maren@example.org",
                "subject": "Dinner",
                "words": "See you <exact> at 8.",
                "from": "user",
                "exact": True,
            }
        ),
        {"send_email": EMAIL}.get,
    )
    assert isinstance(read, RequestedCall)
    assert read.tool == EMAIL
    assert dict(read.values) == {
        "to": "maren@example.org",
        "subject": "Dinner",
        "words": "See you <exact> at 8.",
        "from": "user",
    }


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({"to": "Maren", "subject": "s", "words": "w", "from": "user"}, id="a-name"),
        pytest.param({"to": "m@x.org", "subject": "s", "words": "w"}, id="the-assistants"),
    ],
)
def test_a_waiting_email_the_translation_cannot_carry_is_void(values: dict[str, Any]) -> None:
    """§8:6: a recipient that is not an address, or no account the system holds."""
    assert isinstance(translated(_waiting(values), {"send_email": EMAIL}.get), Void)


async def test_an_approved_searchs_looking_for_survives_a_restart_and_reaches_its_digest() -> None:
    """§10:2, §10:6: kept with the request, read back from storage, and run with the ticket."""
    requested = RequestedCall(
        tool=WEB_SEARCH,
        values={"origin": "https://search.example.com", "query": "museum hours"},
        looking_for="When does it open on Sunday?",
    )
    request = ApprovalRequest(
        id="approval:1",
        person=OWNER_PERSON_ID,
        activation_id="asker",
        round="r1",
        call=requested,
        why="You asked about the museum.",
        written_at=_AT - timedelta(minutes=5),
        expires_at=_AT + timedelta(hours=1),
        state=ApprovalRequestState.APPROVED,
        answer=ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT - timedelta(minutes=1)),
        ticket=TicketState.HELD,
    )
    stored = ApprovalRequest.model_validate_json(request.model_dump_json())
    ticket = Ticket(request=stored)
    call = ProposedCall(call_id="c1", name="run_approved", arguments={"ticket": "A1"})
    stage, _ = _stage(RoundResponse(calls=(call,)))
    inputs = _inputs(
        tickets=(ticket,),
        labels=(PlanningLabel(label="A1", kind=LabelKind.APPROVED_ACTION, id="approval:1"),),
    )
    planned = await stage.plan(inputs)

    (run,) = planned.calls
    assert run.ticket == "approval:1"
    assert run.call.name == "search_web"
    assert run.looking_for == "When does it open on Sunday?"


# --- search_connections (§3:7-§3:8) -------------------------------------------------------------


async def test_search_connections_finds_an_unshown_conversation_and_labels_it() -> None:
    """§3:7-§3:8: matched against its transcript, read through the store's existing reads."""
    store = FakeConversationStore()
    plans = await store.start()
    other = await store.start()
    await store.append_message(
        plans.id, NewMessage(author=MessageAuthor.ASSISTANT, text="the trip to Porto in June")
    )
    await store.append_message(
        other.id, NewMessage(author=MessageAuthor.ASSISTANT, text="the dentist on Tuesday")
    )
    search = ConnectionSearch(conversations=store, scan=10, page_size=5)

    found = await search.search("Porto trip", 1)

    assert [one.place for one in found.connections] == [f"conversation:{plans.id}"]
    assert not found.more
    # Planning shows it as Connections shows an entry, under the next L label.
    call = ProposedCall(call_id="c1", name="search_connections", arguments={"query": "Porto"})
    shown = await _second_round(
        CallOutcome("r", "c1", CallOutcomeKind.DONE, result_id="result:1", connections=found),
        call,
    )
    (entry,) = shown["result"]["connections"]
    (tag,) = tags(entry, "connection")
    assert tag.attributes["label"] == "L7"
    assert tag.text == "a conversation in the hub chat"
    assert "Porto" not in entry


def test_search_connections_is_offered_with_a_query_and_a_page() -> None:
    (offered,) = offered_tools((SEARCH_CONNECTIONS,))
    schema = json.loads(json.dumps(offered.model_dump(mode="json")["parameters"]))
    assert set(schema["properties"]) == {"query", "page"}
    assert schema["required"] == ["query"]


# --- read_forecast (§12) -----------------------------------------------------------------------


def test_read_forecast_is_offered_its_coordinates_and_never_its_origin() -> None:
    """§12:1-§12:2: the origin is the hub's, the coordinates planning's, both optional."""
    # The hub offers it without the origin, as PhaseTools offers the search (§12:1).
    (offered,) = offered_tools((_without(FORECAST_READ, {"origin"}),))
    schema = offered.model_dump(mode="json")["parameters"]
    assert set(schema["properties"]) == {"latitude", "longitude", "looking_for"}
    assert schema["required"] == ["looking_for"]


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        pytest.param({}, {"origin": "o", "latitude": 1.0, "longitude": 2.0}, id="neither"),
        pytest.param(
            {"latitude": 42.36, "longitude": -71.06},
            {"origin": "o", "latitude": 42.36, "longitude": -71.06},
            id="both",
        ),
        pytest.param({"latitude": 42.36}, {"origin": "o", "latitude": 42.36}, id="one"),
    ],
)
def test_the_hub_fills_the_origin_and_the_configured_place_only_where_none_was_named(
    given: dict[str, Any], kept: dict[str, Any]
) -> None:
    """§12:2: planning's coordinates are what the call sends; left out, the configured."""
    call = ProposedCall(call_id="c1", name="read_forecast", arguments=given)
    filled = _forecast_filled(call, {"origin": "o", "latitude": 1.0, "longitude": 2.0})
    assert {**given, **filled} == kept


def test_a_remember_recorded_before_the_renames_still_reads_as_a_candidate() -> None:
    """ADR-0364 §8:2/§8:4: an old ``remember`` and its old argument names still read."""
    assert is_remember("remember")
    assert is_remember("remember_fact")
    assert not is_remember(None)
    assert not is_remember("search_memories")
    old = candidate_of(
        {
            "fact": "The owner likes tea.",
            "why": "A standing taste.",
            "rests_on_input": True,
            "rests_on_user_messages": ["episode:one"],
        }
    )
    assert old.rests_on_input
    assert old.user_messages == ("episode:one",)

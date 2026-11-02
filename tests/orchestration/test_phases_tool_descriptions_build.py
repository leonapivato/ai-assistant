"""ADR-0364 §14:4's engine-level tests of lane B: a message into a connection.

Driven through the phases over the fakes, as ``phases_support`` wires them: a work is
shown its connections (§3), a ``send_text`` call goes into any connection it was shown
that takes a text message (§9:3), and one into a connection that takes none, or one the
work was not shown, is refused (§9:2).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from exchange_support import reported, section, tags, text_call
from phases_support import open_conversation, phases_harness, say, settled, written

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import MessageAuthor, NewMessage, ProposedCall, RoundResponse
from ai_assistant.orchestration.approval_calls import ApprovalsSeams
from ai_assistant.orchestration.channel_kinds import EMAIL_ACCOUNT_KIND, AccountConnection
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import pytest

    from ai_assistant.core.types import OfferedTool, PlanningExchange

#: The approvals channel's knobs: a request that expires in a day, rechecked quickly.
_APPROVALS: Final = ApprovalsSeams(expiry=timedelta(days=1), recheck=timedelta(milliseconds=20))


def _label_of(briefing: str, what: str) -> str:
    """The ``L`` label of the connection whose entry says ``what``."""
    for one in tags(section(briefing, "## Connections"), "connection"):
        if what in (one.text or ""):
            return one.attributes["label"]
    msg = f"no connection shows {what!r}"
    raise AssertionError(msg)


async def _first_round_results(
    first: Callable[[PlanningExchange], RoundResponse],
) -> tuple[list[dict[str, object]], FakeToolCallingCompleter, list[str]]:
    """One work whose first round is ``first``'s, and what came of its calls."""

    def respond(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        return first(exchange) if not exchange.steps else RoundResponse()

    completer = FakeToolCallingCompleter(response=respond)
    harness = phases_harness(completer, approvals=_APPROVALS)
    conversation = await open_conversation(harness)
    await say(harness, conversation, "hello")
    await settled(harness, conversation)
    said = [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]
    return reported(completer.calls[1], 0), completer, said


async def test_a_text_into_the_origin_by_its_label_is_sent() -> None:
    """§9:1-§9:2: the stimulus's ``where`` names its origin, which takes a text."""

    def first(exchange: PlanningExchange) -> RoundResponse:
        origin = _label_of(exchange.briefing, "a conversation in the hub chat")
        return RoundResponse(calls=(text_call("Hi.", connection=origin),))

    results, _, said = await _first_round_results(first)

    assert results == [{"outcome": "done"}]
    assert said == ["Hi."]


async def test_a_text_into_a_connection_that_takes_none_is_refused() -> None:
    """§9:2: the approvals take no message, so a text naming them runs nothing."""

    def first(exchange: PlanningExchange) -> RoundResponse:
        approvals = _label_of(exchange.briefing, "the approvals")
        return RoundResponse(calls=(text_call("Hi.", connection=approvals),))

    results, _, said = await _first_round_results(first)

    (result,) = results
    assert result["outcome"] == "refused"
    assert "takes no text message" in str(result["because"])
    assert "Hi." not in said


async def test_a_text_into_a_connection_the_work_was_not_shown_is_refused() -> None:
    """§9:2: a label the work was never shown names nothing."""

    def first(exchange: PlanningExchange) -> RoundResponse:
        del exchange
        return RoundResponse(calls=(text_call("Hi.", connection="L9"),))

    results, _, said = await _first_round_results(first)

    (result,) = results
    assert result["outcome"] == "refused"
    assert "names no connection you were shown" in str(result["because"])
    assert "Hi." not in said


async def test_a_text_whose_exact_tag_is_never_closed_comes_back_not_done() -> None:
    """§9:8: the tool's own check, so not done, and nothing is written."""

    def first(exchange: PlanningExchange) -> RoundResponse:
        origin = _label_of(exchange.briefing, "a conversation in the hub chat")
        return RoundResponse(calls=(text_call("Say <exact>this", connection=origin),))

    results, _, said = await _first_round_results(first)

    (result,) = results
    assert result["outcome"] == "not done"
    assert not any("Say" in one for one in said)


async def test_a_literal_tag_sent_escaped_arrives_as_written() -> None:
    """§9:8: a backslash before a tag sends it as literal text."""

    def first(exchange: PlanningExchange) -> RoundResponse:
        origin = _label_of(exchange.briefing, "a conversation in the hub chat")
        return RoundResponse(
            calls=(text_call("Type \\<exact> to mark a part.", connection=origin),)
        )

    results, _, said = await _first_round_results(first)

    assert results == [{"outcome": "done"}]
    assert said == ["Type <exact> to mark a part."]


async def test_every_work_is_shown_its_connections_and_the_approvals_among_them() -> None:
    """§3:1-§3:2: the system's own channels are connections, so every origin is one."""
    completer = FakeToolCallingCompleter(response=lambda _exchange, _tools: RoundResponse())
    harness = phases_harness(completer, approvals=_APPROVALS)
    conversation = await open_conversation(harness)
    await say(harness, conversation, "hello")
    await settled(harness, conversation)

    shown = section(completer.calls[0].exchange.briefing, "## Connections")
    texts = [one.text or "" for one in tags(shown, "connection")]
    assert "a conversation in the hub chat" in texts
    assert any("the approvals" in one for one in texts)


async def test_a_conversation_search_connections_found_takes_a_text() -> None:
    """§3:7, §9:3: a conversation outside the recent ones the section shows, found by
    ``search_connections`` under its own ``L`` label, takes a ``send_text`` like any
    connection the work was shown."""
    found: list[str] = []
    shown_first: list[str] = []

    def respond(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
        if "tell the Porto chat" not in exchange.briefing:
            return RoundResponse()
        if not exchange.steps:
            shown_first.extend(
                str(one.get("label")) for one in tags(exchange.briefing, "connection")
            )
            search = ProposedCall(
                call_id="c1", name="search_connections", arguments={"query": "flight"}
            )
            return RoundResponse(calls=(search,))
        if len(exchange.steps) == 1:
            (result,) = [json.loads(one.text) for one in exchange.steps[-1].report.results]
            (entry,) = result["result"]["connections"]
            (shown,) = tags(entry, "connection")
            found.append(shown.attributes["label"])
            return RoundResponse(calls=(text_call("Found it.", connection=found[0]),))
        return RoundResponse()

    harness = phases_harness(FakeToolCallingCompleter(response=respond), phases={"look_ups": True})
    conversations = [await open_conversation(harness) for _ in range(5)]
    asking = await open_conversation(harness)
    # The search's target is one the section does not show: outside the store's three most
    # recent, which the origin's own conversation is among.
    recent = {one.id for one in await harness.conversation_store.recent(limit=3)}
    older = next(one for one in conversations if one not in recent)
    await harness.conversation_store.append_message(
        older, NewMessage(author=MessageAuthor.ASSISTANT, text="the flight to Porto leaves at nine")
    )
    assert older not in {one.id for one in await harness.conversation_store.recent(limit=3)}
    await say(harness, asking, "tell the Porto chat I found it")
    await settled(harness, asking)

    assert len(found) == 1
    assert found[0] not in shown_first, "the search found a conversation the work was not shown"
    assert "Found it." in [one.text for one in await written(harness, older)]


async def test_an_account_whose_state_could_not_be_read_is_not_shown_as_normal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§3:3: an entry's state shows where it is not normal, and unread is not normal."""
    harness = phases_harness(FakeToolCallingCompleter())
    engine = harness.engine
    monkeypatch.setattr(
        engine,
        "_account_connections",
        (AccountConnection(reference="conn-1", kind=EMAIL_ACCOUNT_KIND),),
    )

    async def unreadable() -> tuple[object, ...]:
        msg = "the connection log could not be read"
        raise ConnectionStoreError(msg)

    monkeypatch.setattr(engine._connections, "connected", unreadable)

    (shown,) = await engine._accounts_shown()

    assert shown.state == "its state could not be read"


async def test_connections_hold_the_three_most_recent_conversations_and_an_older_origin() -> None:
    """§3:5, §14:4: the hub chat's three most recent conversations, and the origin first
    where it is older than them; the others are left to search_connections."""
    from ai_assistant.orchestration.conversations import conversation_channel  # noqa: PLC0415

    harness = phases_harness(FakeToolCallingCompleter())
    conversations: list[str] = []
    for one in range(5):
        conversation = await open_conversation(harness)
        await harness.conversation_store.append_message(
            conversation, NewMessage(author=MessageAuthor.ASSISTANT, text=f"note {one}")
        )
        conversations.append(conversation)
    recent = [one.id for one in await harness.conversation_store.recent(limit=3)]
    origin = next(one for one in conversations if one not in recent)

    shown, targets = await harness.engine._shown_connections(conversation_channel(origin))

    hub_chat = [one.place for one in shown if one.place.startswith("conversation:")]
    assert hub_chat == [f"conversation:{one}" for one in (origin, *recent)]
    assert len(set(conversations) - {origin, *recent}) == 1, "one left to the search"
    assert set(hub_chat) <= set(targets)

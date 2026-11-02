"""ADR-0364 §14:4's engine-level tests of lane B: a message into a connection.

Driven through the phases over the fakes, as ``phases_support`` wires them: a work is
shown its connections (§3), a ``send_text`` call goes into any connection it was shown
that takes a text message (§9:3), and one into a connection that takes none, or one the
work was not shown, is refused (§9:2).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from exchange_support import reported, section, tags, text_call
from phases_support import open_conversation, phases_harness, say, settled, written

from ai_assistant.core.types import MessageAuthor, RoundResponse
from ai_assistant.orchestration.approval_calls import ApprovalsSeams
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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

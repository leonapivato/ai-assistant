"""ADR-0364 §9 through the phases: ``send_text``'s arguments, where it goes, its result.

End to end over the engine and the phases, a scripted planner and the canonical fakes:
the connection a ``send_text`` call names by its ``L`` label, what comes back sending
nothing, the words with their exact parts as the wording step renders them, and what the
next round is shown of a message call, its outcome alone (§9:5). No message asks: no
exact lines follow its words, and no round records an asked call (ADR-0361 §8:5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from exchange_support import reported
from phases_support import chat_turn, phases_harness, processing, written

from ai_assistant.core.types import (
    CallOutcomeKind,
    DeliveryStatus,
    MessageAuthor,
    ProposedCall,
    RecordedCall,
    RoundResponse,
)
from ai_assistant.orchestration.message_tools import TEXT_CAPABILITY
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from test_engine import Harness


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


def _text(call_id: str, **arguments: object) -> ProposedCall:
    """A ``send_text`` call, into ``L1``, the stimulus's origin, unless it names another."""
    return _call(call_id, TEXT_CAPABILITY, **{"connection": "L1", **arguments})


def _entries(episode: object) -> dict[str, RecordedCall]:
    return {one.call_id: one for one in processing(episode).call_records}  # type: ignore[arg-type]  # an episode


async def _said(harness: Harness, conversation: str) -> list[str]:
    return [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]


async def test_an_exact_part_is_sent_as_written_its_tags_removed_its_result_its_outcome() -> None:
    """§9:5-§9:9, §14:4: the words as written, the tags removed; the entry holds where and
    how, and the next round is shown the outcome alone."""
    words = "Tell her: <exact>“I'll be late,”</exact> word for word."
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_text("t1", words=words),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "tell her I'll be late")

    sent = "Tell her: “I'll be late,” word for word."
    assert await _said(harness, conversation) == [sent]
    entry = _entries(episode)["t1"]
    assert entry.outcome is CallOutcomeKind.DONE
    assert entry.delivered is not None
    assert entry.delivered.words == sent
    assert entry.delivered.went.instance_id == conversation
    assert entry.delivered.status is DeliveryStatus.SENT
    (shown,) = reported(completer.calls[1], 0)
    assert shown == {"outcome": "done"}
    await harness.engine.aclose()


async def test_a_literal_tag_sent_escaped_arrives_as_written() -> None:
    """§9:8, §14:4: a backslash before a tag sends the tag as literal text."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_text("t1", words=r"Type \<exact> to mark a part."),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, _ = await chat_turn(harness, "how do I mark a part?")

    assert await _said(harness, conversation) == ["Type <exact> to mark a part."]
    await harness.engine.aclose()


async def test_an_unclosed_tag_comes_back_not_done_and_sends_nothing() -> None:
    """§9:8, §14:4: the tool's own check, so not done rather than refused."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_text("t1", words="Say <exact>this"),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "say it")

    assert "Say this" not in await _said(harness, conversation)
    entry = _entries(episode)["t1"]
    assert (entry.outcome, entry.delivered) == (CallOutcomeKind.NOT_DONE, None)
    assert entry.reason is not None
    assert "never closed" in entry.reason
    (shown,) = reported(completer.calls[1], 0)
    assert shown["outcome"] == "not done"
    assert "never closed" in shown["because"]
    await harness.engine.aclose()


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        pytest.param(
            {"connection": "L4"},
            "'L4' names no connection you were shown",
            id="a-label-never-shown",
        ),
        pytest.param(
            {"connection": "the hub chat"}, "names one connection, by its L label", id="a-name"
        ),
        pytest.param({"to": "the owner"}, "nothing else", id="an-argument-it-takes-no-more"),
    ],
)
async def test_a_text_that_cannot_be_carried_out_comes_back_and_sends_nothing(
    arguments: dict[str, Any], says: str
) -> None:
    """§9:1-§9:2, §14:4: refused, nothing is written and nothing is claimed, and the
    result says why and what it may name instead."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_text("t1", words="Running late.", **arguments),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "tell her I'm late")

    # Nothing of it is written; the work's ending is said as ADR-0317 §3 says it.
    assert "Running late." not in await _said(harness, conversation)
    entry = _entries(episode)["t1"]
    assert (entry.outcome, entry.delivered) == (CallOutcomeKind.REFUSED, None)
    assert entry.reason is not None
    assert says in entry.reason
    record = processing(episode)
    effects = await harness.plans.activation_effects([record.activation_id])
    assert [one for one in effects if one.round == record.rounds[0].id] == []
    (shown,) = reported(completer.calls[1], 0)
    assert shown["outcome"] == "refused"
    assert says in shown["because"]
    await harness.engine.aclose()


async def _after_a_call_needing_a_yes(**text: object) -> tuple[Harness, str, Any]:
    """A booking that needs the user, then a round whose ``text`` speaks of it."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),)),
        RoundResponse(calls=(_text("t1", **text),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)
    conversation, episode = await chat_turn(harness, "book a table for the 12th")
    return harness, conversation, episode


async def test_a_text_about_a_call_needing_a_yes_is_its_words_alone() -> None:
    """ADR-0361 §8:5: no exact line follows the words, and no round records an asked call."""
    words = "Shall I book it for the 12th?"
    harness, conversation, episode = await _after_a_call_needing_a_yes(words=words)

    assert await _said(harness, conversation) == [words]
    entry = _entries(episode)["t1"]
    assert entry.delivered is not None
    assert entry.delivered.words == words
    assert all(one.asked == () for one in processing(episode).rounds)
    await harness.engine.aclose()


async def test_a_text_naming_calls_in_asks_runs_nothing() -> None:
    """ADR-0361 §8:5: ``asks`` is no argument of ``text``, so the call comes back."""
    harness, conversation, episode = await _after_a_call_needing_a_yes(
        words="Shall I book it?", asks=["1.1"]
    )

    assert "Shall I book it?" not in await _said(harness, conversation)
    entry = _entries(episode)["t1"]
    assert (entry.outcome, entry.delivered) == (CallOutcomeKind.REFUSED, None)
    assert entry.reason is not None
    assert "nothing else" in entry.reason
    assert all(one.asked == () for one in processing(episode).rounds)
    await harness.engine.aclose()

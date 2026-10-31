"""ADR-0357 §§2-4 and §8 through the phases: ``text``'s arguments, where it goes, its result.

End to end over the engine and the phases, a scripted planner and the canonical fakes:
who a ``text`` call is for and where it goes, what comes back sending nothing, the words
as the wording step renders them, an asking call's exact lines after them, and what the
next round is shown of every message call (§3:1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

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
from ai_assistant.orchestration import phase_path
from ai_assistant.orchestration.message_tools import NEEDS_YOUR_YES, TEXT_CAPABILITY
from ai_assistant.testing import FakeToolCallingCompleter

if TYPE_CHECKING:
    from test_engine import Harness

_BOOKING: Final = 'book — date: "2026-10-12"'


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


def _text(call_id: str, **arguments: object) -> ProposedCall:
    return _call(call_id, TEXT_CAPABILITY, **{"to": "the user", **arguments})


def _entries(episode: object) -> dict[str, RecordedCall]:
    return {one.call_id: one for one in processing(episode).call_records}  # type: ignore[arg-type]  # an episode


async def _said(harness: Harness, conversation: str) -> list[str]:
    return [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]


async def test_a_text_with_exact_delivers_its_words_unchanged_and_says_where_and_how() -> None:
    """§3:1, §4:2, §10's tests: the words as written, the place by the platform, and how."""
    words = "  Tell her: “I'll be late,” word for word.  "
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_text("t1", words=words, exact=True, via="hub_chat"),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "tell her I'll be late")

    assert await _said(harness, conversation) == [words]
    entry = _entries(episode)["t1"]
    assert entry.outcome is CallOutcomeKind.DONE
    assert entry.delivered is not None
    assert entry.delivered.words == words
    assert entry.delivered.went.instance_id == conversation
    assert entry.delivered.status is DeliveryStatus.SENT
    (shown,) = reported(completer.calls[1], 0)
    assert shown["delivered"] == {
        "words": words,
        "went": f"conversation:{conversation}",
        "by": "the hub chat",
        "how": "sent",
    }
    await harness.engine.aclose()


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        pytest.param({"to": "Anna"}, "it could be the user", id="for-no-one-it-reaches"),
        pytest.param(
            {"via": "telegram"},
            "only into the place your input came from",
            id="a-platform-off-the-input",
        ),
        pytest.param({"via": "L4"}, "'L4' names no place you were shown", id="a-label-never-shown"),
        pytest.param({"via": "whatsapp"}, "no platform", id="a-platform-not-built"),
        pytest.param({"exact": "yes"}, "'exact'", id="a-wrong-argument"),
    ],
)
async def test_a_text_that_cannot_be_carried_out_comes_back_and_sends_nothing(
    arguments: dict[str, Any], says: str
) -> None:
    """§2:3-§2:5, §6:1, §10's test: nothing is written and nothing is claimed, and the
    result says why and what it may use instead."""
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
    assert shown["outcome"].startswith("refused")
    await harness.engine.aclose()


async def test_a_text_naming_the_input_by_its_platform_goes_there() -> None:
    """§2:4: a platform names the place the input came from, where it is on it."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_text("t1", words="On it.", via="the hub chat"),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, _ = await chat_turn(harness, "do it")

    assert await _said(harness, conversation) == ["On it."]
    await harness.engine.aclose()


async def _asked_round(
    monkeypatch: pytest.MonkeyPatch | None = None, *, words: str = "Shall I book it for the 12th?"
) -> tuple[Harness, FakeToolCallingCompleter, str, Any]:
    """A booking that needs the user, then a round whose ``text`` asks about it."""
    if monkeypatch is not None:
        # A wording step that rewords everything it is handed: what it never touches
        # are the exact lines code appends after it (§4:4, §8:2).
        monkeypatch.setattr(phase_path, "reworded", lambda words, *, exact: words.upper())
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),)),
        RoundResponse(calls=(_text("t1", words=words, asks=["1.1"]),)),
        RoundResponse(),
    )
    harness = phases_harness(completer)
    conversation, episode = await chat_turn(harness, "book a table for the 12th")
    return harness, completer, conversation, episode


async def test_an_asking_texts_exact_lines_follow_its_words_and_it_is_recorded_asked() -> None:
    """§8:1-§8:4: the lines after the words, the delivered text carrying them, and the
    round recording the call it asks about."""
    harness, completer, conversation, episode = await _asked_round()

    question = f"Shall I book it for the 12th?\n\n{NEEDS_YOUR_YES}\n{_BOOKING}"
    assert await _said(harness, conversation) == [question]
    record = processing(episode)
    (asked,) = record.rounds[1].asked
    assert (asked.part, str(asked.tool.capability)) == (1, "book")
    entry = _entries(episode)["t1"]
    assert entry.delivered is not None
    assert entry.delivered.words == question
    (shown,) = reported(completer.calls[2], -1)
    assert shown["delivered"]["words"] == question
    await harness.engine.aclose()


async def test_the_exact_lines_follow_any_rewording_and_are_never_reworded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§4:4, §8:2, §10's test: code appends them after the wording step has run."""
    harness, _, conversation, _ = await _asked_round(monkeypatch, words="Shall I book it?")

    assert await _said(harness, conversation) == [
        f"SHALL I BOOK IT?\n\n{NEEDS_YOUR_YES}\n{_BOOKING}"
    ]
    await harness.engine.aclose()


async def test_a_second_asking_text_in_a_round_runs_nothing() -> None:
    """§8:3, §10's test: the first in the model's order asks; the second comes back."""
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(calls=(_call("c1", "book", date="2026-10-12"),)),
        RoundResponse(
            calls=(
                _text("t1", words="Shall I book it?", asks=["1.1"]),
                _text("t2", words="Really book it?", asks=["1.1"]),
            )
        ),
        RoundResponse(),
    )
    harness = phases_harness(completer)

    conversation, episode = await chat_turn(harness, "book a table for the 12th")

    assert await _said(harness, conversation) == [
        f"Shall I book it?\n\n{NEEDS_YOUR_YES}\n{_BOOKING}"
    ]
    second = _entries(episode)["t2"]
    assert (second.outcome, second.delivered) == (CallOutcomeKind.REFUSED, None)
    assert second.reason is not None
    assert "already asked" in second.reason
    await harness.engine.aclose()

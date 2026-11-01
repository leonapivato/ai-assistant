"""One matter, one activation, through the engine, over the phases (ADR-0349 §5-§7).

Each case drives whole passes of the hub chat's activations with the phases wired. No
place waits (§8:1): a message written on a conversation while an activation runs there
starts its own (:func:`_beside`). Understanding's model is routed: it reads each input
as meaning its own text, and names in ``continues`` every in-progress entry whose input
holds a word the input lists after ``continues:``. Planning's model is routed by that
meaning.

- The newest absorbs older work of its standing that has not acted, on any place,
  bringing every input it holds and stopping it as a stop does, with no cascade (§7:4-
  §7:8, §4:5); every activation one version names in one step, or none above
  ``held_input_limit`` (§7:6); and two newer ones naming one older one decide oldest
  first, whichever finishes its understanding first (§7:15).
- An act waits for newer input that could absorb it, so the older dispatches nothing
  once absorbed (§7:12-§7:14); and once it has acted it waits for nothing on another
  place.
- The absorber's planning is shown the findings of what it took over, read fresh from
  their own episodes (§7:10).
- Work that has acted on another place is waited on, with no offer: the waiting round
  never ends the activation, the time waited moves its deadline, and the rounds after
  it are shown the finished work (§7:17, §7:25-§7:28).
- On one place, work that has acted is offered the newer input: a take ends the
  offering activation silent and the older's reply covers both; a decline sends the
  newer to its waiting round with the reason; an older that ends unanswered has
  declined; and an offer made while the older plans holds its round back (§7:14,
  §7:17-§7:24).
- Planning's stop call stops committed work it was shown in the list pull's running
  part, and that work alone (ADR-0352 §2:1); its result shows what had finished and what
  the work set up that is still live, which the next round may name (ADR-0352 §3); a
  look-up shows what running work has found (§4:6-§4:11, §6:1-§6:6).
- A conversation never shows the ending of an activation whose matter was taken over:
  within one place it shows the taker's, and across places it keeps what it showed
  before (ADR-0352 §5).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from exchange_support import Tag, says, section, tag, tags, text_call
from phases_support import (
    SETTLE,
    Gated,
    frozen,
    open_conversation,
    phases_harness,
    processing,
    said,
    stopped,
    until,
    working,
    written,
)
from task_support import AT, seams
from understanding_support import rendered

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import (
    ActivationEnding,
    ControllerRule,
    ControllerStage,
    MessageAuthor,
    ProcessingReason,
    ProposedCall,
    RoundResponse,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.testing import FakeModelProvider, FakeToolCallingCompleter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from test_engine import Harness

    from ai_assistant.core.types import (
        ConversationState,
        EpisodeProcessingRecord,
        EpisodicMemory,
        ExchangeStep,
        Message,
        OfferedTool,
        PlanningExchange,
    )

#: What an input lists the words of the work it continues after.
_CONTINUES: Final = "continues:"
#: What an input lists the words of the work it cites, and belongs with, after.
_ABOUT: Final = "about:"


# --- the routed models ------------------------------------------------------------------


class _Understanding(FakeModelProvider):
    """Understanding's model, routed: each input means its own text, and continues work.

    It names in ``meant_for`` each in-progress entry whose input holds a word the input
    lists after :data:`_CONTINUES`, and in ``cites`` and ``belongs_to`` each whose input
    holds a word it lists after :data:`_ABOUT` (ADR-0353 §9:2). :meth:`hold` holds the
    reply to one input until released, so a case decides the order understandings are
    recorded in.
    """

    def __init__(self) -> None:
        super().__init__(reply=self._reply)
        self._gates: dict[str, tuple[asyncio.Event, asyncio.Event]] = {}
        self.shown: dict[str, list[dict[str, Any]]] = {}

    def hold(self, text: str) -> tuple[asyncio.Event, asyncio.Event]:
        """The (entered, release) pair holding the reply to the input ``text``."""
        return self._gates.setdefault(text, (asyncio.Event(), asyncio.Event()))

    def _reply(self, messages: Sequence[Message]) -> str:
        message = rendered(messages)
        text = message.stimulus
        section = message.concurrent()
        self.shown[text] = section

        def named(marker: str) -> list[str]:
            if marker not in text:
                return []
            words = [one.strip() for one in text.split(marker, 1)[1].split(",")]
            return [
                str(entry["label"])
                for entry in section
                if any(word and word in str(entry["input"]) for word in words)
            ]

        cited = named(_ABOUT)
        return json.dumps(
            {
                "understanding": text,
                "cites": cited,
                "belongs_to": cited,
                "meant_for": named(_CONTINUES),
            }
        )

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        text = rendered(messages).stimulus
        gate = self._gates.get(text)
        if gate is not None:
            gate[0].set()
            await gate[1].wait()
        return await super().complete(messages, model=model)


@dataclass(frozen=True)
class _Request:
    """One round's exchange, read as planning's model reads it: by what it was shown.

    The briefing, then each earlier round's response and report (ADR-0356 §5): a case
    reads a section by its heading, the results of a round's calls decoded, and the news.
    """

    exchange: PlanningExchange

    @property
    def briefing(self) -> str:
        return self.exchange.briefing

    @property
    def rounds(self) -> tuple[ExchangeStep, ...]:
        """The work's earlier rounds, each its response and its report."""
        return self.exchange.steps

    @property
    def text(self) -> str:
        """Everything the round was shown: the briefing, then each report in order."""
        parts = [self.briefing]
        for step in self.rounds:
            parts.extend(one.text for one in step.report.results)
            parts.append(step.report.news)
        return "\n".join(parts)

    @property
    def meaning(self) -> str:
        """What the latest understanding the round was shown says the input means."""
        found = tags(self.text, "understanding")
        return "" if not found else str(found[-1].text)

    def section(self, heading: str) -> str:
        return section(self.briefing, heading)

    def results(self, round_number: int) -> list[dict[str, Any]]:
        """What came of each call of round ``round_number``, decoded, with its call."""
        step = self.rounds[round_number - 1]
        return [
            {
                "capability": call.name,
                "arguments": call.model_dump()["arguments"],
                **json.loads(one.text),
            }
            for call, one in zip(step.response.calls, step.report.results, strict=True)
        ]

    def news(self) -> str:
        """Every report's news, in order."""
        return "\n".join(step.report.news for step in self.rounds)


type _Reply = RoundResponse | Callable[[_Request], RoundResponse]


class _Planner(FakeToolCallingCompleter):
    """Planning's model, routed by what the round's understanding says the input means.

    Each input's rounds are answered from its own script in turn, a callable answering
    from the rendered request; past its script, a work's first such round sends
    ``done: <input>`` by a ``text`` call, and each after it proposes nothing, so the work
    ends (a round's own text is its notes alone, ADR-0356 §7:3). A script whose last
    reply is a message ends with an empty round of its own. A held input's rounds wait
    for its release.
    """

    def __init__(self) -> None:
        super().__init__()
        self._scripts: dict[str, list[_Reply]] = {}
        self._gates: dict[str, tuple[asyncio.Event, asyncio.Event]] = {}
        self._from: dict[str, int] = {}
        self._within: list[str] = []
        self._pauses: dict[tuple[str, int], tuple[asyncio.Event, asyncio.Event]] = {}
        self.requests: dict[str, list[_Request]] = {}
        self.offered: dict[str, list[list[str]]] = {}

    def script(self, text: str, *replies: _Reply) -> None:
        self._scripts.setdefault(text, []).extend(replies)

    def pause(self, text: str, round_number: int) -> tuple[asyncio.Event, asyncio.Event]:
        """The (entered, release) pair holding ``text``'s round ``round_number`` alone."""
        return self._pauses.setdefault((text, round_number), (asyncio.Event(), asyncio.Event()))

    def route_within(self, fragment: str) -> None:
        """Route every input whose meaning holds ``fragment`` as ``fragment``.

        An activation the Task Scheduler started means the hub's statement of its task,
        which holds the task's instruction among the rest.
        """
        self._within.append(fragment)

    def hold(self, text: str, *, from_round: int = 1) -> tuple[asyncio.Event, asyncio.Event]:
        """The (entered, release) pair holding ``text``'s rounds from ``from_round`` on."""
        self._from.setdefault(text, from_round)
        return self._gates.setdefault(text, (asyncio.Event(), asyncio.Event()))

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        del model
        # The briefing and the reports since, read as one request (ADR-0356 §5).
        request = _Request(exchange)
        key = request.meaning
        key = next((one for one in self._within if one in key), key)
        self.requests.setdefault(key, []).append(request)
        self.offered.setdefault(key, []).append([one.name for one in tools])
        gate = self._gates.get(key)
        if gate is not None and len(self.requests[key]) >= self._from.get(key, 1):
            gate[0].set()
            await gate[1].wait()
        paused = self._pauses.get((key, len(self.requests[key])))
        if paused is not None:
            paused[0].set()
            await paused[1].wait()
        script = self._scripts.get(key) or []
        if not script:
            said = any(
                one.call_id == "done" for step in exchange.steps for one in step.response.calls
            )
            if said:
                return RoundResponse()
            return RoundResponse(calls=(text_call(f"done: {key}", call_id="done"),))
        reply = script.pop(0)
        return reply(request) if callable(reply) else reply


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


class _Counting(Gated):
    """:class:`Gated`, counting the planning calls waiting on :attr:`release`."""

    def __init__(self, *responses: RoundResponse) -> None:
        super().__init__(*responses)
        self.calls_waiting = 0

    async def respond(
        self, exchange: Any, tools: Any, *, model: str | None = None
    ) -> RoundResponse:
        self.calls_waiting += 1
        return await super().respond(exchange, tools, model=model)


def _routed() -> FakeModelProvider:
    """Understanding's model, routed as :class:`_Understanding` routes it."""
    return _Understanding()


def _harness(
    understanding: _Understanding, planner: FakeToolCallingCompleter, **knobs: Any
) -> Harness:
    from understanding_support import understanding_stage  # noqa: PLC0415 — beside the harness

    return phases_harness(planner, understanding=understanding_stage(model=understanding), **knobs)


# --- driving the places -----------------------------------------------------------------


async def _start(harness: Harness, text: str, *, message_id: str) -> tuple[str, str]:
    """A conversation of its own, and the activation its message starts."""
    conversation = (await harness.engine.start_conversation()).id
    await harness.engine.write_message(conversation, message=said(message_id, text))
    return conversation, await working(harness, conversation)


async def _beside(
    harness: Harness, conversation: str, text: str, *, message_id: str
) -> tuple[str, asyncio.Future[None]]:
    """Write a message on ``conversation`` while an activation runs there.

    The hub chat's reader starts its own activation for it (ADR-0349 §8:1). The case
    reads which by the bookkeeping, and is handed what ends once that one has frozen.
    """
    receipt = await harness.engine.write_message(conversation, message=said(message_id, text))
    position = receipt.position
    assert position is not None
    found: list[str] = []

    async def taken() -> bool:
        marked = await harness.conversation_store.taken_in(conversation, positions=[position])
        found.extend(marked.values())
        return bool(found)

    await until(taken, what="the message to start an activation of its own")
    activation_id = found[0]

    async def ended() -> None:
        async def done() -> bool:
            return any(
                processing(one).activation_id == activation_id for one in await frozen(harness)
            )

        await until(done, what="its activation to end")

    return activation_id, asyncio.ensure_future(ended())


async def _frozen(harness: Harness, count: int) -> list[EpisodicMemory]:
    async def done() -> bool:
        return len(await frozen(harness)) >= count

    await until(done, what=f"{count} frozen episode(s)")
    return await frozen(harness)


def _of(found: Sequence[EpisodicMemory], activation_id: str) -> EpisodeProcessingRecord:
    (record,) = [processing(one) for one in found if processing(one).activation_id == activation_id]
    return record


def _episode(found: Sequence[EpisodicMemory], activation_id: str) -> EpisodicMemory:
    (episode,) = [one for one in found if processing(one).activation_id == activation_id]
    return episode


def _ran(record: EpisodeProcessingRecord, stage: ControllerStage) -> list[ControllerRule]:
    return [one.due for one in record.stages if one.stage is stage]


async def _assistant(harness: Harness, conversation: str) -> list[str]:
    return [
        one.text
        for one in await written(harness, conversation)
        if one.author is MessageAuthor.ASSISTANT
    ]


async def _understood(harness: Harness, activation_id: str) -> None:
    """Wait until ``activation_id`` has recorded its first understanding version."""

    async def recorded() -> bool:
        return any(
            one.state is not None
            and one.state.activation_id == activation_id
            and bool(one.state.understanding)
            for one in harness.engine._running
        )

    await until(recorded, what="the understanding to be recorded")


def _label_of(request: _Request, key: str) -> str:
    """The ``E`` label a request shows other work under: an offer, work it waits on, or
    running work a list pull's result shows (ADR-0356 §3:2, §5:5)."""
    for one in tags(request.text, "stimulus"):
        if "yes" in (one.get("offered"), one.get("waited_on")):
            return str(one.get("label"))
    for number in range(1, len(request.rounds) + 1):
        for call in request.results(number):
            value = call.get("result", {}).get("value", {})
            for running in (value.get("running") if isinstance(value, dict) else None) or ():
                if isinstance(running, dict):
                    return str(running["episode"])
    msg = f"no running work shown for {key}: {request.text[:200]}"
    raise AssertionError(msg)


def _round_limit(harness: Harness, limit: int) -> None:
    """Bound the hub's activations at ``limit`` rounds.

    A round's message is a ``text`` call, whose round brings another (ADR-0356 §7:3,
    ADR-0315 §2:1), so a case that pulls, acts and then answers needs a fourth.
    """
    phases = harness.engine._phases
    assert phases is not None
    phases._round_limit = limit


# --- §7:4-§7:8: the newest absorbs what it continues ---------------------------------


async def test_the_newest_absorbs_older_work_that_has_not_acted_and_brings_its_input() -> None:
    """§7:4-§7:8, §4:5: the older is stopped as a stop is; its input is the newer's."""
    understanding, planner = _Understanding(), _Planner()
    planner.hold("book Riverside")
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, older = await _start(harness, "book Riverside", message_id="a-1")
    await asyncio.wait_for(planner.hold("book Riverside")[0].wait(), SETTLE)

    second, newer = await _start(harness, "for two, continues: Riverside", message_id="b-1")
    await _understood(harness, newer)
    planner.hold("book Riverside")[1].set()
    found = await _frozen(harness, 2)

    stopped(_episode(found, older))
    taker = _of(found, newer)
    (joined,) = taker.joined
    assert joined.taken_over_from == older
    assert joined.channel == conversation_channel(first)
    assert [one.text for one in joined.messages] == ["book Riverside"]
    assert [(one.version, one.continues) for one in taker.understanding] == [(1, (older,))]
    assert _ran(taker, ControllerStage.TAKEOVER) == [ControllerRule.TAKEOVER_UNDECIDED]
    assert _ran(taker, ControllerStage.UNDERSTANDING) == [ControllerRule.NOT_UNDERSTOOD], (
        "the version that named it covers what it brought (§7:9)"
    )
    held = await harness.plans.export()
    assert older in held.stopped_activations
    assert await _assistant(harness, first) == [], "the older wrote nothing"
    assert await _assistant(harness, second) == ["done: for two, continues: Riverside"]


async def test_separate_work_continues_nothing_and_each_runs_on_its_own() -> None:
    """§7:3: an input asking for separate work names nothing, and never waits."""
    understanding, planner = _Understanding(), _Planner()
    planner.hold("book Riverside")
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, older = await _start(harness, "book Riverside", message_id="a-1")
    await asyncio.wait_for(planner.hold("book Riverside")[0].wait(), SETTLE)

    second, newer = await _start(harness, "what's the weather there?", message_id="b-1")
    found_weather = await _frozen(harness, 1)
    planner.hold("book Riverside")[1].set()
    found = await _frozen(harness, 2)

    assert [processing(one).activation_id for one in found_weather] == [newer], (
        "the weather answers first"
    )
    assert _of(found, newer).joined == ()
    assert _of(found, older).joined == ()
    assert await _assistant(harness, first) == ["done: book Riverside"]
    assert await _assistant(harness, second) == ["done: what's the weather there?"]
    # The in-progress section showed the running work, newest first, exactly as §5:6 has
    # it, and planning was shown no section (§5:9).
    (entry,) = understanding.shown["what's the weather there?"]
    assert {key: entry[key] for key in ("label", "origin", "acted", "input")} == {
        "label": "R1",
        "origin": "the hub chat",
        "input": "book Riverside",
        "acted": "no",
    }
    assert entry["at"], "ADR-0353 §2:5: when its input arrived"
    # Planning is shown it as a concurrent stimulus, not acted, its input as written
    # (ADR-0356 §3:2).
    (running,) = tags(
        planner.requests["what's the weather there?"][0].section("## Concurrent stimuli"),
        "stimulus",
    )
    assert running.get("acted") == "no"
    assert [one.text for one in running.held("said")] == ["book Riverside"]


async def test_running_work_cited_and_belonged_to_alone_is_never_taken_over() -> None:
    """ADR-0353 §10:4, §16:4: an ``R`` label in ``cites`` and ``belongs_to`` records a
    ``running`` referent and an activation member, and drives no takeover: the takeover
    reads ``continues`` alone, which only ``meant_for`` fills, so each runs on its own."""
    understanding, planner = _Understanding(), _Planner()
    planner.hold("book Riverside")
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, older = await _start(harness, "book Riverside", message_id="a-1")
    await asyncio.wait_for(planner.hold("book Riverside")[0].wait(), SETTLE)

    second, newer = await _start(harness, "is it sunny, about: Riverside", message_id="b-1")
    found_weather = await _frozen(harness, 1)
    planner.hold("book Riverside")[1].set()
    found = await _frozen(harness, 2)

    assert [processing(one).activation_id for one in found_weather] == [newer]
    taker = _of(found, newer)
    (version,) = taker.understanding
    assert version.continues == ()
    assert [(one.kind, one.id) for one in version.meaning_referents] == [
        ("running", f"activation:{older}")
    ]
    assert [one.id for one in version.story_links] == [older]
    assert _ran(taker, ControllerStage.TAKEOVER) == []
    assert taker.joined == ()
    assert _of(found, older).joined == ()
    assert await _assistant(harness, first) == ["done: book Riverside"]
    assert await _assistant(harness, second) == ["done: is it sunny, about: Riverside"]


async def test_one_version_naming_two_absorbs_both_in_one_step() -> None:
    """§7:4-§7:6: every activation the version names that qualifies, in one step."""
    understanding, planner = _Understanding(), _Planner()
    for text in ("book Riverside", "a table for two"):
        planner.hold(text)
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, a = await _start(harness, "book Riverside", message_id="a-1")
    second, b = await _start(harness, "a table for two", message_id="b-1")
    for text in ("book Riverside", "a table for two"):
        await asyncio.wait_for(planner.hold(text)[0].wait(), SETTLE)

    third, c = await _start(harness, "at eight, continues: Riverside, table", message_id="c-1")
    await _understood(harness, c)
    for text in ("book Riverside", "a table for two"):
        planner.hold(text)[1].set()
    found = await _frozen(harness, 3)

    for older in (a, b):
        stopped(_episode(found, older))
    taker = _of(found, c)
    assert {(one.taken_over_from, one.channel) for one in taker.joined} == {
        (a, conversation_channel(first)),
        (b, conversation_channel(second)),
    }
    assert [len(one.continues) for one in taker.understanding] == [2]
    assert _ran(taker, ControllerStage.TAKEOVER) == [ControllerRule.TAKEOVER_UNDECIDED]
    assert await _assistant(harness, first) == []
    assert await _assistant(harness, second) == []
    assert len(await _assistant(harness, third)) == 1


@pytest.mark.parametrize("limit", [1, 2])
async def test_an_absorption_above_held_input_limit_absorbs_none(limit: int) -> None:
    """§7:6, §9:2, §1:5's case: at a limit of 1, and at one two absorptions exhaust."""
    understanding, planner = _Understanding(), _Planner()
    for text in ("book Riverside", "a table for two"):
        planner.hold(text)
    harness = _harness(understanding, planner, held_input_limit=limit)
    await open_conversation(harness)
    first, a = await _start(harness, "book Riverside", message_id="a-1")
    second, b = await _start(harness, "a table for two", message_id="b-1")
    for text in ("book Riverside", "a table for two"):
        await asyncio.wait_for(planner.hold(text)[0].wait(), SETTLE)

    _, c = await _start(harness, "at eight, continues: Riverside, table", message_id="c-1")
    await _understood(harness, c)
    for text in ("book Riverside", "a table for two"):
        planner.hold(text)[1].set()
    found = await _frozen(harness, 3)

    assert _of(found, c).joined == ()
    for older in (a, b):
        assert _of(found, older).stages[-1].due is ControllerRule.NOTHING_DUE
    assert len(await _assistant(harness, first)) == 1
    assert len(await _assistant(harness, second)) == 1
    stops = (await harness.plans.export()).stopped_activations
    assert a not in stops
    assert b not in stops


@pytest.mark.parametrize("first_understood", ["middle", "newest"])
async def test_two_newer_naming_one_older_decide_oldest_first_in_either_order(
    first_understood: str,
) -> None:
    """§7:15, §1:5's first case: the older of the two absorbs first, the newer follows."""
    understanding, planner = _Understanding(), _Planner()
    planner.hold("book Riverside")
    middle_text, newest_text = "for two, continues: Riverside", "at eight, continues: Riverside"
    for text in (middle_text, newest_text):
        understanding.hold(text)
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, older = await _start(harness, "book Riverside", message_id="a-1")
    await asyncio.wait_for(planner.hold("book Riverside")[0].wait(), SETTLE)
    _, middle = await _start(harness, middle_text, message_id="b-1")
    third, newest = await _start(harness, newest_text, message_id="c-1")
    for text in (middle_text, newest_text):
        await asyncio.wait_for(understanding.hold(text)[0].wait(), SETTLE)

    order = (
        (newest_text, middle_text)
        if first_understood == "newest"
        else (
            middle_text,
            newest_text,
        )
    )
    understanding.hold(order[0])[1].set()
    for _ in range(30):
        await asyncio.sleep(0.001)
    understanding.hold(order[1])[1].set()
    planner.hold("book Riverside")[1].set()
    found = await _frozen(harness, 3)

    stopped(_episode(found, older))
    stopped(_episode(found, middle))
    assert [one.taken_over_from for one in _of(found, middle).joined] == [older]
    taker = _of(found, newest)
    assert [one.taken_over_from for one in taker.joined] == [middle, middle], (
        "it followed forward and absorbed the absorber, with every input it held"
    )
    assert await _assistant(harness, first) == []
    assert len(await _assistant(harness, third)) == 1


# --- §7:12-§7:14: every act waits for the newest ---------------------------------------


async def test_an_older_one_reaching_its_first_act_waits_and_the_newer_absorbs_it() -> None:
    """§7:12, §1:5's case: it dispatches nothing once the newer input absorbs it."""
    understanding, planner = _Understanding(), _Planner()
    newer_text = "actually Sunday, continues: Saturday"
    understanding.hold(newer_text)
    planner.hold("book Saturday")
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, older = await _start(harness, "book Saturday", message_id="a-1")
    await asyncio.wait_for(planner.hold("book Saturday")[0].wait(), SETTLE)
    second, newer = await _start(harness, newer_text, message_id="b-1")
    await asyncio.wait_for(understanding.hold(newer_text)[0].wait(), SETTLE)

    planner.hold("book Saturday")[1].set()
    for _ in range(50):
        await asyncio.sleep(0.001)
    assert await _assistant(harness, first) == [], "its act waits for the newer understanding"
    understanding.hold(newer_text)[1].set()
    found = await _frozen(harness, 2)

    stopped(_episode(found, older))
    assert await harness.plans.activation_effects([older]) == (), "it dispatched nothing"
    assert await _assistant(harness, first) == []
    assert [one.taken_over_from for one in _of(found, newer).joined] == [older]
    assert await _assistant(harness, second) == [f"done: {newer_text}"]


async def test_an_activation_that_has_acted_waits_for_newer_input_on_another_place() -> None:
    """§7:12, ADR-0361 §7:2: after it commits, newer input on any place is waited for."""
    understanding, planner = _Understanding(), _Planner()
    planner.script(
        "book Riverside",
        RoundResponse(
            calls=(
                text_call("Looking.", call_id="m1"),
                _call(
                    "c1", "remember", fact="Likes Riverside.", why="a taste", rests_on_input=True
                ),
            ),
        ),
    )
    planner.hold("book Riverside", from_round=2)
    weather = "what's the weather there?"
    understanding.hold(weather)
    harness = _harness(understanding, planner)
    await open_conversation(harness)
    first, older = await _start(harness, "book Riverside", message_id="a-1")
    await asyncio.wait_for(planner.hold("book Riverside")[0].wait(), SETTLE)
    _, newer = await _start(harness, weather, message_id="b-1")
    await asyncio.wait_for(understanding.hold(weather)[0].wait(), SETTLE)

    # The older has acted, and its second round's act comes while the newer input
    # elsewhere is running and has not been understood: an offer could now come from it.
    planner.hold("book Riverside")[1].set()
    await asyncio.sleep(0.3)
    assert await _assistant(harness, first) == ["Looking."], (
        "its second act waits on the newer input elsewhere"
    )
    assert any(
        one.state is not None and one.state.activation_id == newer
        for one in harness.engine._running
    ), "the newer one was running, unsettled, the whole time"
    understanding.hold(weather)[1].set()
    found = await _frozen(harness, 2)
    assert {processing(one).activation_id for one in found} == {older, newer}
    assert await _assistant(harness, first) == ["Looking.", "done: book Riverside"]


async def test_the_absorbers_planning_is_shown_what_it_took_over_read_from_the_source() -> None:
    """§7:10, §1:5's case: A's findings reach C through B, read fresh from A's own episode."""
    understanding, planner = _Understanding(), _Planner()
    planner.script(
        "find a hotel",
        RoundResponse(
            calls=(_call("c1", "search_memory", query="hotels", looking_for="past stays"),),
            text="The Grand had a view last time.",
        ),
    )
    planner.hold("find a hotel", from_round=2)
    b_text, c_text = "near the station, continues: hotel", "under 200, continues: station"
    planner.hold(b_text)
    harness = _harness(understanding, planner, phases={"look_ups": True})
    await open_conversation(harness)
    _, a = await _start(harness, "find a hotel", message_id="a-1")
    await until(_has(planner, "find a hotel", 2), what="A's look-up and its second round")
    _, b = await _start(harness, b_text, message_id="b-1")
    await asyncio.wait_for(planner.hold(b_text)[0].wait(), SETTLE)
    _, c = await _start(harness, c_text, message_id="c-1")
    found_c = await _frozen(harness, 1)
    planner.hold(b_text)[1].set()
    planner.hold("find a hotel")[1].set()
    found = await _frozen(harness, 3)

    assert [processing(one).activation_id for one in found_c] == [c]
    request, _ = planner.requests[c_text]
    shown = tags(request.section("## Short-term memory"), "episode")
    assert len(shown) == 2, "A's work and B's, each from its own episode"
    notes = [note.text for one in shown for note in one.held("notes")]
    assert "The Grand had a view last time." in notes
    stopped(_episode(found, a))
    stopped(_episode(found, b))


# --- §7:17, §7:25-§7:28: work that has acted elsewhere is waited on ---------------------


async def test_input_continuing_work_that_acted_elsewhere_is_offered_and_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0361 §7:1, ADR-0349 §7:17-§7:21: an offer is made from any place, and taken."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "search apartments", "only two bedrooms, continues: apartments"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Searching.", call_id="m2"),
                _call("c1", "remember", fact="Wants a flat.", why="a plan", rests_on_input=True),
            ),
        ),
        # Planned before the offer, so held back (§7:14) and never written.
        says("Still searching.", call_id="m10"),
        lambda request: RoundResponse(
            calls=(_call("c2", "answer_offer", offer=_label_of(request, older_text), take=True),)
        ),
        says("Two-bedroom flats: three found.", call_id="m12"),
        # ADR-0361 §7:3: the taken input's place is on its list, and a message may go there.
        lambda request: RoundResponse(
            calls=(text_call("Filtered for you here.", call_id="m13", via=_taken_place(request)),)
        ),
    )
    planner.hold(older_text, from_round=2)
    # The place lists are the Task Scheduler's, which every deployment wires (ADR-0350 §5:11).
    harness = _harness(understanding, planner, task_scheduler=seams())
    first, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    second, newer = await _start(harness, newer_text, message_id="b-1")

    async def offered() -> bool:
        state = next(
            (
                one.state
                for one in harness.engine._running
                if one.state is not None and one.state.activation_id == older
            ),
            None,
        )
        return state is not None and bool(state.offers)

    await until(offered, what="the offer from another place")
    planner.hold(older_text)[1].set()
    found = await _frozen(harness, 2)

    stopped(_episode(found, newer))
    assert newer_text not in planner.requests, "while its offer was open it planned no round"
    record = _of(found, older)
    assert [one.taken_over_from for one in record.joined] == [newer]
    assert record.joined[0].channel.instance_id == second
    assert (await _assistant(harness, first))[:2] == [
        "Searching.",
        "Two-bedroom flats: three found.",
    ]
    assert await _assistant(harness, second) == ["Filtered for you here."], (
        "the offering one wrote nothing; the taker wrote into the taken input's place"
    )


def _taken_place(request: _Request) -> str:
    """The ``L`` label of a place newly on the list, an input's taken by a take (§7:3)."""
    (place,) = [
        one
        for one in tags(request.text, "place")
        if one.text == "a conversation an input this activation took came from"
    ]
    return str(place.get("label"))


async def test_input_continuing_work_it_cannot_be_offered_to_waits_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:22, §7:25-§7:28, §1:5's case: a waiting round, the moved deadline, the work.

    No offer is made to an older holding as much input as it may (§7:22), so the newer
    one, on another place, waits on it (ADR-0361 §7:1 lets an offer come from any place).
    """
    understanding, planner = _Understanding(), _Planner()
    planner.script(
        "search apartments",
        RoundResponse(
            calls=(
                text_call("Searching.", call_id="m2"),
                _call("c1", "remember", fact="Wants a flat.", why="a plan", rests_on_input=True),
            ),
        ),
    )
    planner.hold("search apartments", from_round=2)
    newer_text = "only two bedrooms, continues: apartments"
    planner.script(newer_text, says("I'll filter to two bedrooms once it ends.", call_id="m10"))
    harness = _harness(understanding, planner)
    monkeypatch.setattr(harness.engine._matters, "held_input_limit", 1)
    await open_conversation(harness)
    first, _ = await _start(harness, "search apartments", message_id="a-1")
    await until(_has(planner, "search apartments", 2), what="the older to act and plan again")
    monkeypatch.setattr(harness.engine, "_chat_turn_budget", timedelta(seconds=0.3))
    second, newer = await _start(harness, newer_text, message_id="b-1")

    async def waiting_round_written() -> bool:
        return "I'll filter to two bedrooms once it ends." in await _assistant(harness, second)

    await until(waiting_round_written, what="the waiting round's message")
    await asyncio.sleep(0.5)
    assert len(planner.requests[newer_text]) == 1, "its next round waits for the older's end"
    planner.hold("search apartments")[1].set()
    found = await _frozen(harness, 2)

    record = _of(found, newer)
    assert record.joined == ()
    assert record.status is not None
    assert record.status.value == "completed", "the wait did not count against its deadline"
    first_round, second_round, _ = planner.requests[newer_text]
    waited = tag(first_round.section("## Concurrent stimuli"), "stimulus", waited_on="yes")
    assert waited.get("acted") == "yes"
    # ADR-0356 §4:3, §4:5: the waiting round is offered every call, as every round is,
    # and a call but the stop or a message comes back refused.
    assert planner.offered[newer_text][0] == planner.offered[newer_text][1]
    assert "- Finished work newly read:" in second_round.news()
    work = tag(second_round.news(), "episode")
    assert work.get("status") == "ended"
    assert [one.text for one in work.held("said")] == ["search apartments"]
    assert [one.text for one in work.held("did")] == [
        "sent the message: Searching.",
        "the tool remember ran",
        "sent the message: done: search apartments",
    ], "its finished work, the message it wrote during the wait included"
    assert await _assistant(harness, first) == ["Searching.", "done: search apartments"]
    assert await _assistant(harness, second) == [
        "I'll filter to two bedrooms once it ends.",
        f"done: {newer_text}",
    ]


def _offers(request: _Request) -> list[Tag]:
    """The offers a request was shown open: each a stimulus tag offered to the work."""
    return tags(request.text, "stimulus", offered="yes")


def _has(planner: _Planner, text: str, count: int) -> Callable[[], Any]:
    async def check() -> bool:
        return len(planner.requests.get(text, ())) >= count

    return check


# --- §7:17-§7:24: on one place, work that has acted is offered the input -------------


async def _acted_on_one_place(
    harness: Harness, planner: _Planner, monkeypatch: pytest.MonkeyPatch, text: str
) -> tuple[str, str]:
    """An activation that has acted and is held in its second round, on a place of its own.

    Its rounds are bounded at six, so a round held back for an offer (§7:14) and the
    answer's round both fit before its reply.
    """
    phases = harness.engine._phases
    assert phases is not None
    monkeypatch.setattr(phases, "_round_limit", 6)
    await open_conversation(harness)
    conversation, older = await _start(harness, text, message_id="a-1")
    await until(_has(planner, text, 2), what="the older to act and plan again")
    return conversation, older


async def test_an_offer_taken_ends_the_offering_one_silent_and_the_reply_covers_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:17-§7:21, §1:5's case."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "search apartments", "only two bedrooms, continues: apartments"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Searching.", call_id="m3"),
                _call("c1", "remember", fact="Wants a flat.", why="a plan", rests_on_input=True),
            ),
        ),
        # Planned before the offer, so held back (§7:14) and never written.
        says("Still searching.", call_id="m11"),
        lambda request: RoundResponse(
            calls=(_call("c2", "answer_offer", offer=_label_of(request, older_text), take=True),)
        ),
        says("Two-bedroom flats: three found.", call_id="m12"),
        RoundResponse(),
    )
    planner.hold(older_text, from_round=2)
    harness = _harness(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, task = await _beside(harness, conversation, newer_text, message_id="b-1")

    async def offered() -> bool:
        state = next(
            (
                one.state
                for one in harness.engine._running
                if one.state is not None and one.state.activation_id == older
            ),
            None,
        )
        return state is not None and bool(state.offers)

    await until(offered, what="the offer to be made")
    planner.hold(older_text)[1].set()
    await task
    found = await _frozen(harness, 2)

    stopped(_episode(found, newer))
    assert newer_text not in planner.requests, "while its offer was open it planned no round"
    record = _of(found, older)
    assert [one.taken_over_from for one in record.joined] == [newer]
    assert await _assistant(harness, conversation) == [
        "Searching.",
        "Two-bedroom flats: three found.",
    ], "the offering one wrote nothing, and the older's reply covers both"
    assert not _offers(planner.requests[older_text][1]), "planned before the offer"
    (shown,) = _offers(planner.requests[older_text][2])
    assert [one.text for one in shown.held("understood")] == [newer_text]
    assert [one.text for one in shown.held("said")] == [newer_text]
    assert "answer_offer" in planner.offered[older_text][2]
    # §7:21: once taken, the input is the older's own, shown to its planning as a new
    # message of the place, once, by its writer and with when it was sent; the offer is
    # said closed (ADR-0356 §5:5).
    after = planner.requests[older_text][3]
    news = after.rounds[-1].report.news
    taken = [one for one in tags(news, "message") if one.text == newer_text]
    assert len(taken) == 1
    assert taken[0].get("from") == tag(after.briefing, "said").get("from")
    assert taken[0].get("at") is not None
    (offer,) = _offers(after)
    assert f"- The offer of {offer.get('label')} is no longer open." in news


async def test_an_offer_declined_sends_the_newer_one_to_wait_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:22-§7:27, §1:5's case: the reason, the waiting round, then the older's work."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "book Saturday", "actually Sunday, continues: Saturday"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Booking.", call_id="m4"),
                _call(
                    "c1", "remember", fact="Books Saturdays.", why="a habit", rests_on_input=True
                ),
            ),
        ),
        says("Still booking.", call_id="m13"),
        lambda request: RoundResponse(
            calls=(
                _call(
                    "c2",
                    "answer_offer",
                    offer=_label_of(request, older_text),
                    take=False,
                    reason="already booked",
                ),
            )
        ),
    )
    planner.hold(older_text, from_round=2)
    harness = _harness(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, task = await _beside(harness, conversation, newer_text, message_id="b-1")

    async def offered() -> bool:
        state = next(
            (
                one.state
                for one in harness.engine._running
                if one.state is not None and one.state.activation_id == older
            ),
            None,
        )
        return state is not None and bool(state.offers)

    await until(offered, what="the offer to be made")
    planner.hold(older_text)[1].set()
    await task
    found = await _frozen(harness, 2)

    rounds = planner.requests[newer_text]
    waited = tag(rounds[0].section("## Concurrent stimuli"), "stimulus", waited_on="yes")
    assert waited.get("declined") == "already booked"
    work = tag(rounds[-1].news(), "episode")
    assert [one.text for one in work.held("said")] == [older_text]
    did = [one.text for one in work.held("did")]
    assert "the tool remember ran" in did, "it plans from the older's finished work"
    assert "sent the message: done: book Saturday" in did
    assert _of(found, newer).joined == ()
    assert _of(found, older).joined == ()


async def test_an_older_one_ending_without_answering_has_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:24, §1:5's case: the offer is declined, and the newer plans once it has ended."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "book Saturday", "for two, continues: Saturday"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Booking.", call_id="m5"),
                _call(
                    "c1", "remember", fact="Books Saturdays.", why="a habit", rests_on_input=True
                ),
            ),
        ),
        says("Booked.", call_id="m14"),
        says("Booked.", call_id="m15"),
        RoundResponse(),
    )
    planner.hold(older_text, from_round=2)
    harness = _harness(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, task = await _beside(harness, conversation, newer_text, message_id="b-1")

    async def offered() -> bool:
        state = next(
            (
                one.state
                for one in harness.engine._running
                if one.state is not None and one.state.activation_id == older
            ),
            None,
        )
        return state is not None and bool(state.offers)

    await until(offered, what="the offer to be made")
    # The older's round was planned before the offer, so it is held back and planned
    # again, shown the offer (§7:14); its script answers nothing, so it ends unanswered.
    planner.hold(older_text)[1].set()
    await task
    found = await _frozen(harness, 2)

    assert _of(found, newer).joined == ()
    work = tag(planner.requests[newer_text][-1].text, "episode", status="ended")
    assert "sent the message: Booked." in [one.text for one in work.held("did")], (
        "it plans from the older's finished work"
    )


async def test_an_offer_made_while_the_older_plans_holds_its_round_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:14, §1:5's case: the round's acts are held back and planning runs again."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "book Saturday", "make it Sunday, continues: Saturday"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Booking.", call_id="m6"),
                _call(
                    "c1", "remember", fact="Books Saturdays.", why="a habit", rests_on_input=True
                ),
            ),
        ),
        # Planned before the offer: a write and its message, both held back (§7:14).
        RoundResponse(
            calls=(
                text_call("Booked for Saturday.", call_id="m7"),
                _call(
                    "c2",
                    "remember",
                    fact="Booked Saturday.",
                    why="the booking",
                    rests_on_input=True,
                ),
            ),
        ),
        lambda request: RoundResponse(
            calls=(_call("c3", "answer_offer", offer=_label_of(request, older_text), take=True),)
        ),
        says("Booked for Sunday instead.", call_id="m16"),
        RoundResponse(),
    )
    planner.hold(older_text, from_round=2)
    harness = _harness(understanding, planner)
    conversation, older = await _acted_on_one_place(harness, planner, monkeypatch, older_text)
    newer, task = await _beside(harness, conversation, newer_text, message_id="b-1")

    async def offered() -> bool:
        state = next(
            (
                one.state
                for one in harness.engine._running
                if one.state is not None and one.state.activation_id == older
            ),
            None,
        )
        return state is not None and bool(state.offers)

    await until(offered, what="the offer to be made")
    planner.hold(older_text)[1].set()
    await task
    found = await _frozen(harness, 2)

    assert await _assistant(harness, conversation) == ["Booking.", "Booked for Sunday instead."], (
        "the round planned before the offer was held back, its message never written"
    )
    stopped(_episode(found, newer))
    record = _of(found, older)
    assert [one.taken_over_from for one in record.joined] == [newer]
    assert not _offers(planner.requests[older_text][1])
    replanned = planner.requests[older_text][2]
    assert _offers(replanned)
    # The held-back round's message and write each come back not run (ADR-0349 §7:14).
    held_back = replanned.results(2)
    assert [one["capability"] for one in held_back] == ["text", "remember"]
    assert all(
        "offered to this work before this round acted" in one["outcome"] for one in held_back
    )
    remembered = [
        one
        for one in await harness.plans.activation_effects([older])
        if one.capability == "remember"
    ]
    assert len(remembered) == 1, "the held-back write was never claimed, by any path"


# --- §4:6-§4:11, §6:1-§6:6: the stop call and the look-up --------------------------------


def _stop_result(request: _Request, round_number: int) -> dict[str, Any]:
    """What a stop call a round made came back with, as a later round is shown it."""
    (call,) = [
        one for one in request.results(round_number) if one["capability"] == "stop_activation"
    ]
    result: dict[str, Any] = call["result"]
    return result


def _stopped_work(result: dict[str, Any]) -> Tag:
    """The work a stop call's result shows, as the ``episode`` tag its value is."""
    return tag(str(result["value"]), "episode")


async def test_the_stop_call_stops_committed_work_and_its_task_stays_and_is_listed() -> None:
    """ADR-0352 §2:1, §3:1-§3:3, §7:7, and ADR-0349 §1:5's case as ADR-0352 leaves it."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "remind me hourly to stretch", "never mind the research"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("I'll remind you.", call_id="remind"),
                _call("c1", "spawn", instruction="Remind them to stretch.", delay_minutes=60),
            ),
        ),
    )
    planner.hold(older_text, from_round=2)
    planner.script(
        newer_text,
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        lambda request: RoundResponse(
            calls=(_call("c2", "stop_activation", activation=_label_of(request, newer_text)),)
        ),
        says("Stopped; the reminder is still set.", call_id="m17"),
        RoundResponse(),
    )
    harness = _harness(understanding, planner, task_scheduler=seams())
    _round_limit(harness, 4)
    await harness.engine.start()
    await open_conversation(harness)
    _, older = await _start(harness, older_text, message_id="a-1")
    await until(_has(planner, older_text, 2), what="the spawn to run and its next round to wait")
    _, newer = await _start(harness, newer_text, message_id="b-1")
    (first,) = await _frozen(harness, 1)
    assert processing(first).activation_id == newer
    # A stop cuts off nothing in flight (ADR-0295 §2): the older's round finishes, and
    # then its pass ends on the stop, writing nothing.
    planner.hold(older_text)[1].set()
    found = await _frozen(harness, 2)
    stopped(_episode(found, older))

    held = await harness.plans.export()
    assert older in held.stopped_activations
    (task,) = await harness.plans.spawned_tasks([older])
    assert task.pending, "what the stopped work set up stays (ADR-0352 §2:4)"
    result = _stop_result(planner.requests[newer_text][2], 2)
    work = _stopped_work(result)
    assert work.get("stopped_by_this_call") == "yes"
    assert any("spawn" in str(one.text) for one in work.held("did")), (
        "its result shows what had finished"
    )
    left = result["set_up_still_live"]
    (shown,) = left["scheduled"]
    assert shown["label"].startswith("T")
    assert shown["state"] == "pending"
    assert shown["falls_due"]
    assert shown["set_by"] == "person"
    assert tag(shown["carries"], "task").text == "Remind them to stretch."
    assert left["running"] == "none"
    await harness.engine.aclose()


async def test_a_stop_call_naming_work_that_set_up_nothing_says_nothing_is_still_live() -> None:
    """ADR-0352 §3:1, §7:7: where there is none, the result says so."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "find a hotel", "never mind the hotel"
    planner.script(
        older_text,
        RoundResponse(
            calls=(_call("c1", "search_memory", query="hotels", looking_for="past stays"),)
        ),
    )
    planner.hold(older_text, from_round=2)
    planner.script(
        newer_text,
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        lambda request: RoundResponse(
            calls=(_call("c2", "stop_activation", activation=_label_of(request, newer_text)),)
        ),
        says("Stopped.", call_id="m18"),
        RoundResponse(),
    )
    harness = _harness(understanding, planner, task_scheduler=seams(), phases={"look_ups": True})
    _round_limit(harness, 4)
    await harness.engine.start()
    await open_conversation(harness)
    _, _older = await _start(harness, older_text, message_id="a-1")
    await until(_has(planner, older_text, 2), what="the look-up to run and the next round wait")
    _, _newer = await _start(harness, newer_text, message_id="b-1")
    await _frozen(harness, 1)
    planner.hold(older_text)[1].set()
    await _frozen(harness, 2)

    result = _stop_result(planner.requests[newer_text][2], 2)
    assert _stopped_work(result).get("stopped_by_this_call") == "yes"
    assert result["set_up_still_live"] == "nothing it set up is still live"
    await harness.engine.aclose()


async def test_a_stop_calls_result_lists_running_work_below_which_the_next_round_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0352 §3:4, §3:7, §7:7: a step running from a task below, shown by its label."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text, step = (
        "research blenders",
        "never mind all the blender stuff",
        "Read blender reviews.",
    )
    planner.route_within(step)
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Researching.", call_id="research"),
                _call("c1", "spawn", instruction=step, delay_minutes=5),
            ),
        ),
    )
    planner.hold(older_text, from_round=2)
    planner.hold(step)

    def stop_below(request: _Request) -> RoundResponse:
        listed = _stop_result(request, 2)["set_up_still_live"]["running"]
        return RoundResponse(
            calls=(_call("c3", "stop_activation", activation=listed[0]["episode"]),)
        )

    planner.script(
        newer_text,
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        lambda request: RoundResponse(
            calls=(_call("c2", "stop_activation", activation=_label_of(request, newer_text)),)
        ),
        stop_below,
        says("Stopped the research and its reading.", call_id="m19"),
        RoundResponse(),
    )
    planner.hold(newer_text, from_round=2)
    clock = _Clock()
    harness = _harness(understanding, planner, task_scheduler=seams(), now=clock)
    phases = harness.engine._phases
    assert phases is not None
    monkeypatch.setattr(phases, "_round_limit", 6)
    await harness.engine.start()
    await open_conversation(harness)
    _, older = await _start(harness, older_text, message_id="a-1")
    await until(_has(planner, older_text, 2), what="the spawn to run and its next round wait")
    _, _newer = await _start(harness, newer_text, message_id="b-1")
    await asyncio.wait_for(planner.hold(newer_text)[0].wait(), SETTLE)
    # Only now does the step fall due, so the list pull showed the older alone.
    clock.now += timedelta(minutes=6)
    await asyncio.wait_for(planner.hold(step)[0].wait(), SETTLE)
    (task,) = await harness.plans.spawned_tasks([older])
    (running_step,) = task.activations
    planner.hold(newer_text)[1].set()
    await _until_stopped(harness, running_step)
    planner.hold(older_text)[1].set()
    planner.hold(step)[1].set()
    found = await _frozen(harness, 3)

    listing = planner.requests[newer_text][0].rounds
    assert listing == (), "the list pull's round was planned before the step started"
    first = _stop_result(planner.requests[newer_text][2], 2)
    (listed,) = first["set_up_still_live"]["running"]
    assert listed["input"], "shown as the list pull's running part shows one"
    assert first["set_up_still_live"]["scheduled"] == "none"
    second = _stop_result(planner.requests[newer_text][3], 3)
    assert _stopped_work(second).get("stopped_by_this_call") == "yes"
    stopped(_episode(found, older))
    stopped(_episode(found, running_step))
    held = await harness.plans.export()
    assert {older, running_step} <= set(held.stopped_activations)
    await harness.engine.aclose()


class _Clock:
    """A clock a case steps forward, so a task comes due without a wait."""

    def __init__(self) -> None:
        self.now = AT

    def __call__(self) -> datetime:
        return self.now


async def _until_stopped(harness: Harness, activation_id: str) -> None:
    async def recorded() -> bool:
        return activation_id in (await harness.plans.export()).stopped_activations

    await until(recorded, what="the stop record to be written")


async def test_a_look_up_shows_what_running_work_has_found_so_far() -> None:
    """§6:1, §6:4-§6:6: by the label the list pull showed it under, a pure read."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "find a hotel", "what has the hotel search found?"
    planner.script(
        older_text,
        RoundResponse(
            calls=(_call("c1", "search_memory", query="hotels", looking_for="past stays"),),
            text="The Grand is 180 a night.",
        ),
    )
    planner.hold(older_text, from_round=2)
    planner.script(
        newer_text,
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        lambda request: RoundResponse(
            calls=(_call("c2", "look_up_activation", activation=_label_of(request, newer_text)),)
        ),
        says("The Grand, at 180.", call_id="m20"),
        RoundResponse(),
    )
    harness = _harness(understanding, planner, task_scheduler=seams(), phases={"look_ups": True})
    _round_limit(harness, 4)
    await harness.engine.start()
    await open_conversation(harness)
    _, older = await _start(harness, older_text, message_id="a-1")
    await until(_has(planner, older_text, 2), what="the look-up to run and the next round wait")
    _, newer = await _start(harness, newer_text, message_id="b-1")
    found = await _frozen(harness, 1)

    assert [processing(one).activation_id for one in found] == [newer]
    found_so_far = tag(planner.requests[newer_text][2].results(2)[0]["result"]["value"], "episode")
    assert found_so_far.get("status") == "running"
    assert [one.text for one in found_so_far.held("notes")] == ["The Grand is 180 a night."]
    assert older not in (await harness.plans.export()).stopped_activations
    planner.hold(older_text)[1].set()
    await _frozen(harness, 2)
    await harness.engine.aclose()


async def test_a_stop_call_waits_and_a_newer_input_absorbs_the_stopping_one() -> None:
    """§4:12, §7:12, §1:5's case: "never mind", then "no, keep them": nothing is stopped."""
    understanding, planner = _Understanding(), _Planner()
    older_text, stopper, keeper = (
        "remind me hourly to stretch",
        "never mind the reminders",
        "no, keep them, continues: reminders",
    )
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("I'll remind you.", call_id="remind"),
                _call("c1", "spawn", instruction="Remind them to stretch.", delay_minutes=60),
            ),
        ),
    )
    planner.hold(older_text, from_round=2)
    planner.script(
        stopper,
        RoundResponse(calls=(_call("c1", "list_tasks"),)),
        lambda request: RoundResponse(
            calls=(_call("c2", "stop_activation", activation=_label_of(request, stopper)),)
        ),
    )
    planner.hold(stopper, from_round=2)
    understanding.hold(keeper)
    harness = _harness(understanding, planner, task_scheduler=seams())
    await harness.engine.start()
    await open_conversation(harness)
    _, older = await _start(harness, older_text, message_id="a-1")
    await until(_has(planner, older_text, 2), what="the spawn to run and its next round wait")
    _, stopping = await _start(harness, stopper, message_id="b-1")
    await asyncio.wait_for(planner.hold(stopper)[0].wait(), SETTLE)
    _, keeping = await _start(harness, keeper, message_id="c-1")
    await asyncio.wait_for(understanding.hold(keeper)[0].wait(), SETTLE)

    planner.hold(stopper)[1].set()
    for _ in range(50):
        await asyncio.sleep(0.001)
    held = await harness.plans.export()
    assert older not in held.stopped_activations, "the stop call waits for the newer input"
    understanding.hold(keeper)[1].set()
    found = await _frozen(harness, 2)

    stopped(_episode(found, stopping))
    assert [one.taken_over_from for one in _of(found, keeping).joined] == [stopping]
    held = await harness.plans.export()
    assert older not in held.stopped_activations, "nothing is stopped"
    planner.hold(older_text)[1].set()
    await _frozen(harness, 3)
    await harness.engine.aclose()


async def test_a_waiting_round_is_shown_no_ticket_and_the_round_after_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§7:25-§7:26: the waiting round is offered the stop call alone, its ticket withheld.

    ADR-0361 §5:1, ADR-0356 §15: a ticket renders in the input that holds it, so the
    round after the wait is shown it as news, the briefing being rendered once.
    """
    from ai_assistant.core.types import (  # noqa: PLC0415 — one case's
        OWNER_PERSON_ID,
        ApprovalGiver,
        ApprovalRequest,
        ApprovalRequestState,
        ApprovalTap,
        RequestedCall,
        TicketState,
    )
    from ai_assistant.orchestration.approvals import Ticket  # noqa: PLC0415 — one case's
    from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE  # noqa: PLC0415

    understanding, planner = _Understanding(), _Planner()
    planner.script(
        "search apartments",
        RoundResponse(
            calls=(
                text_call("Searching.", call_id="m8"),
                _call("c1", "remember", fact="Wants a flat.", why="a plan", rests_on_input=True),
            ),
        ),
    )
    planner.hold("search apartments", from_round=2)
    newer_text = "yes, and only two bedrooms, continues: apartments"
    harness = _harness(understanding, planner)
    phases = harness.engine._phases
    assert phases is not None
    request = ApprovalRequest(
        id="approval:1",
        person=OWNER_PERSON_ID,
        activation_id="act-asking",
        round="round:asking",
        call=RequestedCall(
            tool=REMEMBER_CANDIDATE,
            values={
                "fact": "Wants two bedrooms.",
                "why": "a plan",
                "rests_on_input": True,
                "episode": "activation:act-asking",
                "rests_on_outside_content": False,
            },
        ),
        why="Leo said so.",
        written_at=AT,
        expires_at=AT + timedelta(days=1),
        state=ApprovalRequestState.APPROVED,
        answer=ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=AT),
        ticket=TicketState.HELD,
    )

    async def held(state: Any) -> tuple[Ticket, ...]:
        said = getattr(state.trigger.payload, "text", "")
        return (Ticket(request=request),) if said == newer_text else ()

    monkeypatch.setattr(phases, "_tickets", held)
    # ADR-0349 §7:22: no offer is made to an older holding as much input as it may, so
    # the newer one waits on it, wherever it runs (ADR-0361 §7:1).
    monkeypatch.setattr(harness.engine._matters, "held_input_limit", 1)
    await open_conversation(harness)
    await _start(harness, "search apartments", message_id="a-1")
    await until(_has(planner, "search apartments", 2), what="the older to act and plan again")
    await _start(harness, newer_text, message_id="b-1")
    await until(_has(planner, newer_text, 1), what="the waiting round")
    planner.hold("search apartments")[1].set()
    await _frozen(harness, 2)

    waiting_round, after = planner.requests[newer_text][:2]
    assert tags(waiting_round.section("## Concurrent stimuli"), "stimulus", waited_on="yes")
    assert tags(waiting_round.text, "ticket") == []
    # ADR-0356 §4:3, §5:2: every round of a work is offered what its first was.
    assert planner.offered[newer_text][0] == planner.offered[newer_text][1]
    assert tags(after.text, "ticket") != []
    await harness.engine.aclose()


# --- ADR-0352 §5: what a conversation shows after a hand-over ---------------------------


def _fails(_request: _Request) -> RoundResponse:
    msg = "the model is down"
    raise ModelError(msg)


async def _state(harness: Harness, conversation: str) -> ConversationState:
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    return digest.state


async def _running_only(harness: Harness, conversation: str, *running: str) -> ConversationState:
    """The state once exactly ``running`` run from ``conversation``: what ended has left."""

    async def settled() -> bool:
        return (await _state(harness, conversation)).activation_ids == running

    await until(settled, what="the ended activations to leave the conversation's state")
    return await _state(harness, conversation)


async def _failed_first(harness: Harness, planner: _Planner, conversation: str) -> None:
    """An activation on ``conversation`` that could not finish, so it has an ending to keep."""
    planner.script("tell me a joke", _fails)
    await harness.engine.write_message(conversation, message=said("z-1", "tell me a joke"))
    await _frozen(harness, 1)
    state = await _state(harness, conversation)
    assert state.last_ended is ActivationEnding.COULDNT_FINISH


async def test_a_take_within_one_conversation_never_reads_stopped_then_reads_the_takers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5:1-§5:3, §7:7: "working…" for the taker beside the ending before, then its own."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "search apartments", "only two bedrooms, continues: apartments"
    planner.script(
        older_text,
        RoundResponse(
            calls=(
                text_call("Searching.", call_id="m9"),
                _call("c1", "remember", fact="Wants a flat.", why="a plan", rests_on_input=True),
            ),
        ),
        says("Still searching.", call_id="m21"),
        lambda request: RoundResponse(
            calls=(_call("c2", "answer_offer", offer=_label_of(request, older_text), take=True),)
        ),
        says("Two-bedroom flats: three found.", call_id="m22"),
        RoundResponse(),
    )
    planner.hold(older_text, from_round=2)
    paused = planner.pause(older_text, 4)
    harness = _harness(understanding, planner)
    phases = harness.engine._phases
    assert phases is not None
    monkeypatch.setattr(phases, "_round_limit", 6)
    conversation = await open_conversation(harness)
    await _failed_first(harness, planner, conversation)
    await harness.engine.write_message(conversation, message=said("a-1", older_text))
    await until(_has(planner, older_text, 2), what="the older to act and plan again")
    older = await working(harness, conversation)
    newer, task = await _beside(harness, conversation, newer_text, message_id="b-1")

    async def offered() -> bool:
        state = harness.engine._running_state(older)
        return state is not None and bool(state.offers)

    await until(offered, what="the offer to be made")
    planner.hold(older_text)[1].set()
    await task
    await asyncio.wait_for(paused[0].wait(), SETTLE)

    found = await frozen(harness)
    handed = _of(found, newer)
    assert handed.reason is ProcessingReason.STOPPED
    assert handed.taken_over_by == older, "the freeze names the activation that took it"
    while_taker_runs = await _running_only(harness, conversation, older)
    assert while_taker_runs.working
    assert while_taker_runs.last_ended is ActivationEnding.COULDNT_FINISH, (
        "the ending it showed before, never stopped"
    )
    paused[1].set()
    found = await _frozen(harness, 3)
    assert _of(found, older).taken_over_by is None
    after = await _running_only(harness, conversation)
    assert not after.working
    assert after.last_ended is ActivationEnding.DONE, "how the taker ended"


async def test_an_absorption_across_places_keeps_the_absorbed_conversations_ending() -> None:
    """§5:2-§5:3, §7:7, the owner's "go with a": the ending stays what it was before."""
    understanding, planner = _Understanding(), _Planner()
    older_text, newer_text = "book Riverside", "for two, continues: Riverside"
    harness = _harness(understanding, planner)
    first = await open_conversation(harness)
    await _failed_first(harness, planner, first)
    planner.hold(older_text)
    await harness.engine.write_message(first, message=said("a-1", older_text))
    older = await working(harness, first)
    await asyncio.wait_for(planner.hold(older_text)[0].wait(), SETTLE)
    paused = planner.pause(newer_text, 1)
    second, newer = await _start(harness, newer_text, message_id="b-1")
    await _understood(harness, newer)
    planner.hold(older_text)[1].set()
    await asyncio.wait_for(paused[0].wait(), SETTLE)
    found = await _frozen(harness, 2)

    absorbed = _of(found, older)
    assert absorbed.reason is ProcessingReason.STOPPED
    assert absorbed.taken_over_by == newer
    while_absorber_runs = await _running_only(harness, first)
    assert not while_absorber_runs.working, "working… stops for the absorbed one"
    assert while_absorber_runs.last_ended is ActivationEnding.COULDNT_FINISH
    assert (await _state(harness, second)).activation_ids == (newer,)
    paused[1].set()
    await _frozen(harness, 3)
    await _running_only(harness, second)
    after = await _state(harness, first)
    assert not after.working
    assert after.last_ended is ActivationEnding.COULDNT_FINISH, (
        "the absorber's ending shows on its own place, not this one"
    )
    assert (await _state(harness, second)).last_ended is ActivationEnding.DONE


async def test_a_burst_absorbed_in_one_conversation_never_reads_stopped() -> None:
    """§5:1-§5:3, §7:7: each absorbed in turn, followed forward to the one that ran on."""
    understanding, planner = _Understanding(), _Planner()
    texts = ("plan a party", "for ten, continues: party", "on Saturday, continues: party")
    harness = _harness(understanding, planner)
    conversation = await open_conversation(harness)
    planner.hold(texts[0])
    planner.hold(texts[1])
    paused = planner.pause(texts[2], 1)
    await harness.engine.write_message(conversation, message=said("a-1", texts[0]))
    first = await working(harness, conversation)
    await asyncio.wait_for(planner.hold(texts[0])[0].wait(), SETTLE)
    second, _ = await _beside(harness, conversation, texts[1], message_id="a-2")
    await asyncio.wait_for(planner.hold(texts[1])[0].wait(), SETTLE)
    third, last = await _beside(harness, conversation, texts[2], message_id="a-3")
    await _understood(harness, third)
    planner.hold(texts[0])[1].set()
    planner.hold(texts[1])[1].set()
    await asyncio.wait_for(paused[0].wait(), SETTLE)
    found = await _frozen(harness, 2)

    assert _of(found, first).taken_over_by == second
    assert _of(found, second).taken_over_by == third
    during = await _running_only(harness, conversation, third)
    assert during.last_ended is None, "nothing it started has ended that is shown"
    paused[1].set()
    await last
    after = await _state(harness, conversation)
    assert after.last_ended is ActivationEnding.DONE
    assert _of(await frozen(harness), third).taken_over_by is None

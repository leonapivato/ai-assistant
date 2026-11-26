"""The switch, through the production root: every store it builds withholds (ADR-0383 §7:10).

Milestone 22's B11c. The composition root builds each of its six stores in one mode,
:data:`~ai_assistant.app.composition.SIGHT_MODE`, which this build sets to withholding,
and hands the observer the same value (§7:13). The counting build these cases compare
with is the same root with that one value set back to counting, which is what starting the
first deploy's build again amounts to.

What is shown here, each through the root as it is (the model-facing seams alone
substituted, :mod:`phases_composition_support`), and the lines of #3709 it stands for:

- every store the root builds, and the observer, is built in the one mode;
- an owner's work, at normal and lowered to weak, reads, is shown and writes exactly what
  the counting build's does: every rendered model input byte for byte, the chat, and the
  episode frozen ("Nothing changes for what the owner asks");
- a work by a link lowered to none, an unidentified sender's, reads none of the owner's
  records, its own chat's earlier messages and a memory recall would find included, and
  still begins its turn, answers and has its turn recorded (ADR-0387 §8); and every input
  it is shown is the one it is shown on a hub holding none of the owner's records, so
  nothing withheld is marked, counted or named ("An unidentified sender's work reads none
  of the owner's records", "Withheld means absent");
- a work whose facts were not recorded captures its episode, freezes it and has its turn
  recorded (ADR-0388 §5, #3763);
- the observer sets aside, as stuck and with no model call, an episode its sight does not
  see, and processes the owner's as before (§7:13; "Upkeep still works", for the observer).

**Nothing here opens a socket or contacts a hub.**
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_composition_support import (
    PHONE,
    UNDERSTANDING_INSTRUCTIONS,
    build_phased,
    structured_through,
    until,
)
from structlog.testing import capture_logs

from ai_assistant.app import build_engine, composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    Conversation,
    EpisodicMemory,
    MessageAuthor,
    ObservationState,
    ObserverStep,
    ProposedCall,
    Role,
    RoundResponse,
    SightMode,
    Sureness,
)
from ai_assistant.core.types import Message as ModelMessage
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.notification_store import SqliteNotificationStore
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.memory.story_store import SqliteStoryStore
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration import work_facts
from ai_assistant.orchestration.observer.prompts import OBSERVER_SCOUT_PROMPT
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import FakeToolCallingCompleter, default_renderings
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from phases_composition_support import Phased

    from ai_assistant.core.types import Message, OfferedTool, PlanningExchange
    from ai_assistant.orchestration.engine import Engine

pytestmark = pytest.mark.anyio

#: The six store classes the root builds, each of which binds to a sight (§7:1).
_STORES: Final = (
    SqliteMemoryStore,
    SqliteStoryStore,
    SqlitePersonModelStore,
    SqlitePlanStore,
    SqliteConversationStore,
    SqliteNotificationStore,
)

#: What the owner says first, which no work of an unidentified sender reads.
_SAID: Final = "the boat code is 7731"
#: A memory of the owner's, which recall finds for the question below.
_KEPT: Final = "The boat code is kept in the blue tin."
#: The question the second work asks.
_ASKED: Final = "what is the boat code?"
#: The account the phone's messages are read by, whose link a case lowers.
_PHONE_ACCOUNT: Final = Account(kind="conversation", identifier=PHONE.device_id)

#: A time as the briefing renders it, to the minute, and a date, long or short: two
#: builds run a minute apart render a different one, and nothing else of a time.
_TIME: Final = re.compile(r"\b\d{1,2}:\d{2} [ap]m\b")
_DATE: Final = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]* \d{1,2} "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b"
)


def _timeless(text: str) -> str:
    """``text`` with each rendered time and date named alike."""
    return _DATE.sub("<date>", _TIME.sub("<time>", text))


# --- the one mode -------------------------------------------------------------------------


def _within(held: object) -> list[object]:
    """What one object holds: a container's items, a callable's object and closure, and,
    for this package's objects, their attributes and slots."""
    if isinstance(held, dict):
        return list(held.values())
    if isinstance(held, (list, tuple, set, frozenset)):
        return list(held)
    inner = [getattr(held, name, None) for name in ("__self__", "func", "__wrapped__")]
    within = [one for one in inner if one is not None]
    for cell in getattr(held, "__closure__", None) or ():
        try:
            within.append(cell.cell_contents)
        except ValueError:  # an empty cell
            continue
    if type(held).__module__.startswith("ai_assistant"):
        within.extend(getattr(held, "__dict__", {}).values())
        slots = (name for kind in type(held).__mro__ for name in getattr(kind, "__slots__", ()))
        within.extend(getattr(held, name) for name in slots if hasattr(held, name))
    return within


def _held(root: object) -> list[object]:
    """Every object the composed engine reaches that carries a store's mode.

    Walks the object graph from ``root`` through attributes, slots, containers, bound
    methods, partials and closures, into this package's objects alone, so a store a later
    change builds is found wherever it is held, without naming where.
    """
    found: list[object] = []
    seen: set[int] = set()
    stack: list[object] = [root]
    while stack:
        held = stack.pop()
        if id(held) in seen:
            continue
        seen.add(id(held))
        if type(held).__module__.startswith("ai_assistant") and "_sight_mode" in getattr(
            held, "__dict__", {}
        ):
            found.append(held)
        stack.extend(_within(held))
    return found


def _mode_of(store: object) -> object:
    """The mode a store found by :func:`_held` was built in."""
    return vars(store)["_sight_mode"]


async def test_every_store_the_root_builds_withholds_and_the_observer_knows_it(
    tmp_path: Path,
) -> None:
    """§7:10: the six stores are built in the one mode, withholding, and nothing else
    decides it. Every object the engine reaches that carries a store's mode carries it, so
    a store built later without the argument, which counts by default, fails here."""
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True), data_dir=tmp_path
    )
    try:
        held = _held(engine)
        assert {type(one) for one in held} >= set(_STORES), "the walk reaches all six"
        assert all(_mode_of(one) is SightMode.WITHHOLD for one in held), [
            type(one).__name__ for one in held if _mode_of(one) is SightMode.COUNT
        ]
        observer = engine._observer
        assert observer is not None
        assert observer._withholds, "§7:13: the observer is handed the stores' mode"
    finally:
        await engine.aclose()
    assert composition.SIGHT_MODE is SightMode.WITHHOLD


async def test_the_counting_build_is_the_same_root_with_the_one_value_set_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The undo of the switch: with the root's one value counting, every store counts and
    the observer processes as before. The comparisons below rest on it."""
    monkeypatch.setattr(composition, "SIGHT_MODE", SightMode.COUNT)
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True), data_dir=tmp_path
    )
    try:
        held = _held(engine)
        assert {type(one) for one in held} >= set(_STORES)
        assert all(_mode_of(one) is SightMode.COUNT for one in held)
        assert engine._observer is not None
        assert not engine._observer._withholds
    finally:
        await engine.aclose()


# --- a work, through the root --------------------------------------------------------------


@dataclass
class _Run:
    """What one build left: the second work's rendered inputs, the chat and its episodes."""

    phased: Phased
    conversation: str
    inputs: list[str]
    messages: list[tuple[MessageAuthor, str]]
    episode: EpisodicMemory
    recorded: Conversation


def _rendered(phased: Phased, models: int, rounds: int) -> list[str]:
    """Every input a model was handed from the given counts on, as rendered."""
    understood = [repr(one) for one in phased.model.calls[models:]]
    planned = [one.exchange.model_dump_json() for one in phased.completer.calls[rounds:]]
    return [*understood, *planned]


async def _link(phased: Phased) -> str:
    identities = phased.engine._identities
    assert identities is not None
    link = await identities.find_link(_PHONE_ACCOUNT)
    assert link is not None
    return link.id


async def _lower(phased: Phased, level: Sureness) -> None:
    identities = phased.engine._identities
    assert identities is not None
    await identities.lower(await _link(phased), level, by=OWNER_PERSON_ID)


async def _second_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: SightMode,
    *,
    level: Sureness = Sureness.NORMAL,
    owners: bool = True,
) -> _Run:
    """The owner's first work and a kept memory, then a second work at ``level``.

    With ``owners`` false, the first work is not run and nothing is kept: the hub holds
    none of the owner's records when the second work runs.
    """
    monkeypatch.setattr(composition, "SIGHT_MODE", mode)
    phased = build_phased(tmp_path, monkeypatch)
    engine = phased.engine
    try:
        await engine.start()
        conversation = await phased.start_conversation()
        if owners:
            first = await phased.say(_SAID, conversation)
            await phased.memory.add(memory("m-kept", _KEPT, said_support(first.address)))
        if level is not Sureness.NORMAL:
            await _lower(phased, level)
        models, rounds = len(phased.model.calls), len(phased.completer.calls)
        second = await phased.say(_ASKED, conversation)
        inputs = _rendered(phased, models, rounds)
        messages = [(one.author, one.text) for one in await phased.messages(conversation)]
        episode = await phased.stored(second.address)
        recorded = await phased.conversations.get(conversation)
    finally:
        await engine.aclose()
    assert episode is not None
    assert recorded is not None
    return _Run(phased, conversation, inputs, messages, episode, recorded)


def _normalized(run: _Run) -> list[str]:
    """The run's inputs, its own ids and the rendered times named alike."""
    activation = run.episode.id.removeprefix("activation:")
    return [
        _timeless(one.replace(activation, "<work>").replace(run.conversation, "<chat>"))
        for one in run.inputs
    ]


def _frozen(run: _Run) -> dict[str, Any]:
    """The second work's frozen episode, its ids and instants left out."""
    dumped = json.loads(run.episode.model_dump_json(exclude={"id"}))
    text = json.dumps(dumped, sort_keys=True)
    text = text.replace(run.episode.id.removeprefix("activation:"), "<work>")
    text = text.replace(run.conversation, "<chat>")
    text = re.sub(r"\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?", "<at>", text)
    text = re.sub(r"\b[0-9a-f]{32}\b", "<minted>", text)
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<id>", text)
    result: dict[str, Any] = json.loads(text)
    return result


@pytest.mark.parametrize("level", [Sureness.NORMAL, Sureness.WEAK], ids=["normal", "weak"])
async def test_the_owners_work_reads_is_shown_and_writes_as_the_counting_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: Sureness
) -> None:
    """#3709's first promise: every work for the owner reads what it reads today. At
    normal and lowered to weak, the second work's every rendered model input, the chat it
    leaves and the episode it freezes are the counting build's, byte for byte."""
    withheld = await _second_work(
        tmp_path / "withhold", monkeypatch, SightMode.WITHHOLD, level=level
    )
    counted = await _second_work(tmp_path / "count", monkeypatch, SightMode.COUNT, level=level)
    record = withheld.episode.processing_record
    assert record is not None
    assert record.trigger.senders[0].level is level, "the premise: the owner at this level"
    assert record.trigger.senders[0].person == OWNER_PERSON_ID

    shown = "".join(withheld.inputs)
    assert _SAID in shown, "the owner's work is shown its chat's earlier messages"
    assert _KEPT in shown, "and recalls the owner's memory"
    assert _normalized(withheld) == _normalized(counted)
    assert withheld.messages == counted.messages
    assert _frozen(withheld) == _frozen(counted)
    assert withheld.episode.home == counted.episode.home


async def test_a_work_by_a_link_lowered_to_none_reads_none_of_the_owners_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3709, SEE-27, ADR-0387 §8: an unidentified sender's work reads nothing of the
    owner's, its chat's earlier messages and a memory recall would find included; it
    begins its turn, answers, and has its turn recorded and its episode frozen. And
    withheld means absent: each input it is shown is the one the same work is shown on a
    hub holding none of the owner's records, so nothing withheld is marked, counted or
    named."""
    withheld = await _second_work(
        tmp_path / "withhold", monkeypatch, SightMode.WITHHOLD, level=Sureness.NONE
    )
    alone = await _second_work(
        tmp_path / "alone", monkeypatch, SightMode.WITHHOLD, level=Sureness.NONE, owners=False
    )
    record = withheld.episode.processing_record
    assert record is not None
    (sender,) = record.trigger.senders
    # The premise: a link lowered to none, so the sender is not identified (ADR-0383 §6's
    # table: the work's sight has an anyone bound beside the owner's).
    assert sender.level is Sureness.NONE

    shown = "".join(withheld.inputs)
    assert withheld.inputs, "it was planned"
    assert "7731" not in shown
    assert "blue tin" not in shown
    assert _normalized(withheld) == _normalized(alone)

    begun = [one for one in record.stages if one.stage.value == "begin_conversation"]
    assert [one.outcome.value for one in begun] == ["done"]
    assert withheld.messages[-2:] == [
        (MessageAuthor.USER, _ASKED),
        (MessageAuthor.ASSISTANT, "Noted."),
    ]
    assert withheld.recorded.last_turn_at is not None, "its turn was recorded"
    processing = withheld.episode.processing_record
    assert processing is not None
    assert not processing.is_open, "its episode froze"


async def test_a_work_whose_facts_were_not_recorded_captures_and_records_its_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3763, ADR-0388 §5: a work whose facts could not be recorded has a work's sight of
    an anyone bound and its own activation, so under withholding stores it reads its own
    episode back: the capture is recorded, not degraded, the episode freezes, and the
    conversation records its turn."""

    def defect(*_args: object, **_kwargs: object) -> object:
        msg = "a defect"
        raise RuntimeError(msg)

    monkeypatch.setattr(composition, "SIGHT_MODE", SightMode.WITHHOLD)
    phased = build_phased(tmp_path, monkeypatch)
    engine = phased.engine
    try:
        await engine.start()
        conversation = await phased.start_conversation()
        monkeypatch.setattr(work_facts, "started", defect)
        with capture_logs() as logs:
            turn = await phased.say("hello there", conversation)
        episode = await phased.stored(turn.address)
        recorded = await phased.conversations.get(conversation)
        answered = await phased.answered(conversation)
    finally:
        await engine.aclose()
    events = [one["event"] for one in logs]
    assert "work_facts_unrecorded" in events, "the premise: its facts were not recorded"
    assert "activation_capture_degraded" not in events
    assert episode is not None
    record = episode.processing_record
    assert record is not None
    assert not record.is_open, "its episode froze"
    assert record.facts_now is None
    assert recorded is not None
    assert recorded.last_turn_at is not None, "its turn was recorded"
    assert answered == ["Noted."]


# --- the observer, through the root --------------------------------------------------------

#: The scout's calls, told apart by their default's renderings, not words.
_SCOUT: Final = default_renderings(OBSERVER_SCOUT_PROMPT)


class _Scouted:
    """The provider's ``complete``: understanding, and a scout that finds nothing."""

    def __init__(self) -> None:
        self.shown: list[str] = []

    def __call__(self, messages: Sequence[Message]) -> str:
        system = messages[0].content
        if system in UNDERSTANDING_INSTRUCTIONS:
            return json.dumps({"understanding": "As said."})
        if system in _SCOUT:
            self.shown.append(messages[-1].content)
            return json.dumps({"findings": [], "declines": []})
        return "Noted."


def _replying(exchange: PlanningExchange, _tools: Sequence[OfferedTool]) -> RoundResponse:
    if exchange.steps:
        return RoundResponse()
    call = ProposedCall(
        call_id="say", name="send_text", arguments={"connection": "L1", "words": "Noted."}
    )
    return RoundResponse(calls=(call,))


async def _observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: SightMode
) -> tuple[Engine, dict[str, ObservationState], _Scouted, tuple[Any, ...]]:
    """A work by a link lowered to none, then eleven of the owner's: the first two leave
    the window and the observer runs. Its records for the two, by whose, and what the scout
    was shown."""
    monkeypatch.setattr(composition, "SIGHT_MODE", mode)
    phased = build_phased(tmp_path, monkeypatch, completer=FakeToolCallingCompleter(_replying))
    scouted = _Scouted()

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> ModelMessage:
        del model
        return ModelMessage(role=Role.ASSISTANT, content=scouted(messages))

    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    monkeypatch.setattr(PydanticAIProvider, "complete_structured", structured_through(complete))
    engine = phased.engine
    plans = engine._plans
    try:
        await engine.start()
        conversation = await phased.start_conversation()
        owners = await phased.say("my locker is number 12", conversation)
        identities = engine._identities
        assert identities is not None
        link = await identities.find_link(_PHONE_ACCOUNT)
        assert link is not None
        lowered = await identities.lower(link.id, Sureness.NONE, by=OWNER_PERSON_ID)
        unseen = await phased.say("the gate code is 4410", conversation)
        assert lowered.record_id is not None
        await identities.withdraw_lowering(lowered.record_id, by=OWNER_PERSON_ID)
        for turn in range(10):
            await phased.say(f"thanks, number {turn}", conversation)

        async def settled() -> bool:
            held = await plans.observations([owners.address, unseen.address])
            return len(held) == 2 and all(one.state is not ObservationState.WAITING for one in held)

        await until(settled, what="both episodes to be settled")
        held = await plans.observations([owners.address, unseen.address])
        states = {
            ("owners" if one.episode == owners.address else "unseen"): one.state for one in held
        }
        unseen_record = next(one for one in held if one.episode == unseen.address)
    finally:
        await engine.aclose()
    return engine, states, scouted, unseen_record.attempts


async def test_the_observer_sets_aside_an_episode_its_sight_does_not_see(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:13: where the stores withhold, the finding of what is due hands no run the
    episode of a link lowered to none: it is set aside as stuck, with no attempt and no
    model call, and the scout never reads it. The owner's episode is processed as before.
    """
    with capture_logs() as logs:
        _, states, scouted, attempts = await _observed(tmp_path, monkeypatch, SightMode.WITHHOLD)
    assert states == {"owners": ObservationState.PROCESSED, "unseen": ObservationState.STUCK}
    assert attempts == ()
    assert any("my locker is number 12" in one for one in scouted.shown)
    assert not any("4410" in one for one in scouted.shown)
    set_aside = [
        one
        for one in logs
        if one["event"] == "observer_attempt" and one.get("reason") == "out_of_sight"
    ]
    assert [(one["stage"], one["result"]) for one in set_aside] == [("due", "stuck")]
    assert not [one for one in logs if one["event"] == "sight_counted"], (
        "§11:1: a withholding build writes no count event"
    )


async def test_in_the_counting_build_the_same_episode_is_processed_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:13's last sentence: where the stores count, the episode is processed as today,
    and the count event of its run's reads says what would have been withheld (§11:1)."""
    with capture_logs() as logs:
        _, states, scouted, attempts = await _observed(tmp_path, monkeypatch, SightMode.COUNT)
    assert states == {"owners": ObservationState.PROCESSED, "unseen": ObservationState.PROCESSED}
    assert len(attempts) == 1
    assert [one.step for one in attempts[0].calls] == [ObserverStep.SCOUT]
    assert any("4410" in one for one in scouted.shown)
    assert not [one for one in logs if one.get("reason") == "out_of_sight"]
    counted = [
        one for one in logs if one["event"] == "sight_counted" and one["reader"] == "producer"
    ]
    assert any(one["sees_nothing"] for one in counted), "the unseen episode's reads, counted"
    # #3709's evidence between the deploys: no read for the owner alone counts anything.
    owners = [one for one in counted if one["bounds"] == ["person_owner"]]
    assert owners
    assert not [one for one in owners if one["other_home"] or one["no_home"] or one["sees_nothing"]]

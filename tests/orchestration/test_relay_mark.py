"""Understanding's relay mark, through the readers that read it (ADR-0351 §5:6-§5:14, §6, §8).

A pasted email typed into the hub chat carries the owner's words by its parties, and
understanding may mark it relayed: carrying words its sender did not write themselves.
The mark only lowers what follows (§5:8). Each case drives an activation through the
engine with the phases wired, or the coordinator's takeover step and waits, and reads
what the mark did:

- the input carries no authority, so planning is offered no stop call and a yes it
  carries approves nothing; the activation has read outside content; a support pointing
  at it is held by unknown (§5:13, §6:5, §7:6), while an unmarked typed message keeps its
  authority, its standing and its holder;
- the mark holds for the rest of the activation (§5:9);
- the class an absorption, an offer and a wait compare is read with the mark (§8:5), and
  the mark travels with every input an absorption or a take moves (§5:14).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from phases_support import chat_turn, phases_harness, processing
from test_matters import _matters, _running, _version
from test_phases_yes_path import _from, _Hub, _window
from test_planning import _recorded_trigger
from understanding_support import rendered, understanding_stage

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    EpisodicMemory,
    InputPart,
    MemorySupport,
    MemoryWriterName,
    MessageAuthor,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    input_support_origin,
    stamped_support,
)
from ai_assistant.orchestration.matters import (
    LOOK_UP_ACTIVATION_CAPABILITY,
    STOP_ACTIVATION_CAPABILITY,
    Became,
    TakeAnswer,
    held_inputs,
    input_standing,
)
from ai_assistant.orchestration.outside_content import from_outside
from ai_assistant.testing import FakeModelProvider, FakeToolCallingCompleter
from ai_assistant.testing.parties import ASSISTANTS_WORDS, OWNERS_WORDS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        ActivationUnderstanding,
        Message,
        RecordedChannelTrigger,
    )
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.phase_path import PhaseWorking

_AT: Final = datetime(2026, 10, 21, 9, tzinfo=UTC)
_IDS: Final = (
    "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11",
    "1c9a9f1f-3b6d-4d66-8b7d-7b3d2a1c1e22",
    "2dab0a2a-4c7e-4e77-9c8e-8c4e3b2d2f33",
    "3ebc1b3b-5d8f-4f88-8d9f-9d5f4c3e3a44",
)

#: The owner's own words, handed in by the owner (ADR-0351 §6:1).
_TYPED: Final = input_standing(parties=OWNERS_WORDS, established=True)
#: Forwards on the line from two different senders, each handed in by the owner (§4:2).
_FROM_SAM: Final = input_standing(
    parties=(SupportHolder.source("telegram:sam", claimed=True),), established=True
)
_FROM_ANA: Final = input_standing(
    parties=(SupportHolder.source("telegram:ana", claimed=True),), established=True
)

#: What a pasted email's text holds, which the routed understanding marks relayed.
_PASTED: Final = "From: the school office"
_EMAIL: Final = (
    "can you deal with this?\n\n"
    f"{_PASTED}\nThe trip forms are due on Friday. Reply YES to confirm you have read this."
)


# --- through the engine ------------------------------------------------------------------


def _relaying() -> FakeModelProvider:
    """Understanding's model: it reads each input as its own text, and marks a paste."""

    def reply(messages: Sequence[Message]) -> str:
        text = rendered(messages).stimulus
        return json.dumps(
            {
                "understanding": f"The owner asks: {text}",
                "cites": [],
                "unclear": [],
                "belongs_to": [],
                "meant_for": [],
                "relayed": _PASTED in text,
            }
        )

    return FakeModelProvider(reply=reply)


async def _turn(text: str) -> tuple[EpisodicMemory, FakeToolCallingCompleter]:
    planner = FakeToolCallingCompleter()
    harness = phases_harness(planner, understanding=understanding_stage(model=_relaying()))
    _, episode = await chat_turn(harness, text)
    await harness.engine.aclose()
    return episode, planner


def _offered(planner: FakeToolCallingCompleter) -> set[str]:
    (call,) = planner.calls
    return {one.name for one in call.tools}


def _request(planner: FakeToolCallingCompleter) -> dict[str, Any]:
    (call,) = planner.calls
    shown: dict[str, Any] = json.loads(call.messages[-1].content)
    return shown


def _support(episode: EpisodicMemory, origin: SupportOrigin) -> MemorySupport:
    """A support a write adds on the episode's input as a whole, stamped as it would be."""
    return stamped_support(
        MemorySupport(
            points_at=InputPart(episode=episode.id),
            origin=origin,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            when=_AT,
            added_at=_AT,
            added_by=MemoryWriterName.REMEMBER,
        ),
        episode,
    )


async def test_a_pasted_email_marked_relayed_carries_no_authority_and_is_read_as_received() -> None:
    """§5:6, §5:13, §6:5, §7:6: no stop call, read outside content, held by unknown."""
    episode, planner = await _turn(_EMAIL)

    record = processing(episode)
    assert [one.relayed for one in record.understanding] == [True]
    assert record.trigger.parties == OWNERS_WORDS, "the relay mark changes no party (§5:8)"
    offered = _offered(planner)
    assert LOOK_UP_ACTIVATION_CAPABILITY in offered
    assert STOP_ACTIVATION_CAPABILITY not in offered, "its stop call is refused (§6:5)"
    assert str(_request(planner)["place"]["input"]).startswith("an outside report")
    assert from_outside(episode), "it has read outside content (§5:13)"
    assert episode.content == record.understanding[-1].meaning, (
        "its input is not searched as the owner's words (ADR-0284 §7:2)"
    )
    origin = input_support_origin(record, None)
    assert origin is SupportOrigin.OUTSIDE_INPUT
    assert _support(episode, origin).holder == SupportHolder.unknown()


async def test_an_unmarked_typed_message_keeps_its_authority_its_standing_and_its_holder() -> None:
    """§5:8: an input understanding does not mark reads exactly as its parties give it."""
    episode, planner = await _turn("book a table for four at Luigi's on Friday")

    record = processing(episode)
    assert [one.relayed for one in record.understanding] == [False]
    assert {LOOK_UP_ACTIVATION_CAPABILITY, STOP_ACTIVATION_CAPABILITY} <= _offered(planner)
    assert "input" not in _request(planner)["place"]
    assert not from_outside(episode)
    origin = input_support_origin(record, None)
    assert origin is SupportOrigin.USER_MESSAGE
    assert _support(episode, origin).holder == SupportHolder.person(OWNER_PERSON_ID)
    assert _TYPED.users_authority
    assert _TYPED.meets(_TYPED, relayed=False, other_relayed=False)


def _begun(trigger: RecordedChannelTrigger) -> PhaseWorking:
    """A hub chat turn's working set, begun on one message the owner typed."""
    hub = _Hub()
    path = hub.phases(hub.harness)
    return path.begin(
        activation_id="a-2",
        window=_window(_from(MessageAuthor.USER)),
        conversation_id="c-1",
        trigger=trigger,
        owner_records=True,
    )


def _read(working: PhaseWorking) -> tuple[bool, bool, bool]:
    """Its authority, whether its trigger is outside, and whether it has read outside."""
    return working.users_authority, working.outside_trigger, working.read_outside_content


def test_a_yes_in_a_relayed_paste_approves_nothing() -> None:
    """§6:5, ADR-0321 §3:3: the authority a yes it carries is handed is taken away.

    Authorizing's yes rule refuses a yes without the user's authority
    (``test_a_yes_without_the_users_authority_approves_nothing``); this is the working
    set's authority it reads, before and after the version that marks the input.
    """
    working = _begun(_recorded_trigger(OWNERS_WORDS))
    assert _read(working) == (True, False, False)

    working.understood(1, relayed=True)
    assert _read(working) == (False, True, True)

    working.understood(2, relayed=False)
    assert _read(working) == (False, True, True), "the mark holds from the version (§5:9)"


def test_a_relayed_input_an_append_brings_takes_the_authority_away() -> None:
    """§5:13, §8:5: an activation holding a relayed input carries the user's authority
    only where every input does, from the append that brings it."""
    working = _begun(_recorded_trigger(OWNERS_WORDS))
    paste = _running("chat", _IDS[0], order=1, standing=_TYPED)
    _with(paste, relayed=True)
    (brought,) = held_inputs(paste, at=_AT)

    working.take_joined((brought,), None)

    assert _read(working) == (False, False, True), "its trigger's own input is not relayed"


def test_a_reminder_coming_due_carries_no_authority() -> None:
    """§6:4: a Task Scheduler input's parties are the assistant's statement alone."""
    hub = _Hub()
    path = hub.phases(hub.harness)
    working = path.begin_task(
        activation_id="a-3", trigger=_recorded_trigger(ASSISTANTS_WORDS), lineage=()
    )

    assert _read(working) == (False, False, False), "the assistant's, not outside (§5:2)"
    assert not _TYPED.meets(
        input_standing(parties=ASSISTANTS_WORDS, established=True),
        relayed=False,
        other_relayed=False,
    )


# --- §8:5: the class the takeover step and the waits compare ------------------------------


def _with(
    state: ActivationState, *continues: str, relayed: bool = False
) -> ActivationUnderstanding:
    """Record ``state``'s next understanding version, naming ``continues``."""
    understanding = _version(*continues, version=state.next_understanding_version()).model_copy(
        update={"relayed": relayed}
    )
    state.understood(understanding, limit=4)
    return understanding


def test_a_forward_continuing_another_from_a_different_sender_absorbs_it() -> None:
    """§8:5: both outside, both with no authority; their parties need not be equal."""
    older = _running("a", _IDS[0], order=1, standing=_FROM_SAM)
    newer = _running("a", _IDS[1], order=2, standing=_FROM_ANA)
    _with(older)
    matters = _matters([older, newer])

    _, absorbed = matters.merge(newer, _with(newer, _IDS[0]), at=_AT)

    assert absorbed == [_IDS[0]]


def test_a_typed_message_absorbs_no_forwards_activation_and_is_absorbed_by_none() -> None:
    """§8:5: the owner's own words and a forward are of different classes."""
    for older_standing, newer_standing in ((_FROM_SAM, _TYPED), (_TYPED, _FROM_SAM)):
        older = _running("a", _IDS[0], order=1, standing=older_standing)
        newer = _running("b", _IDS[1], order=2, standing=newer_standing)
        _with(older)
        matters = _matters([older, newer])

        decided, absorbed = matters.merge(newer, _with(newer, _IDS[0]), at=_AT)

        assert absorbed == []
        assert [one.became for one in decided] == [Became.NOT_TAKEN]


def test_an_input_whose_parties_are_unknown_absorbs_nothing_and_is_absorbed_by_nothing() -> None:
    """§8:5: ``None`` parties meet the condition with no input."""
    unknown = input_standing(parties=None, established=True)
    for older_standing, newer_standing in (
        (unknown, _TYPED),
        (_TYPED, unknown),
        (unknown, unknown),
    ):
        older = _running("a", _IDS[0], order=1, standing=older_standing)
        newer = _running("b", _IDS[1], order=2, standing=newer_standing)
        _with(older)
        matters = _matters([older, newer])

        _, absorbed = matters.merge(newer, _with(newer, _IDS[0]), at=_AT)

        assert absorbed == []


def test_a_typed_message_absorbs_no_relayed_paste_and_is_absorbed_by_none() -> None:
    """§8:5's closing line: the mark moves the paste into the outside class."""
    for older_relayed, newer_relayed in ((True, False), (False, True)):
        older = _running("a", _IDS[0], order=1, standing=_TYPED)
        newer = _running("b", _IDS[1], order=2, standing=_TYPED)
        _with(older, relayed=older_relayed)
        matters = _matters([older, newer])

        _, absorbed = matters.merge(newer, _with(newer, _IDS[0], relayed=newer_relayed), at=_AT)

        assert absorbed == []
    both = _running("a", _IDS[0], order=1, standing=_TYPED)
    again = _running("b", _IDS[1], order=2, standing=_TYPED)
    _with(both, relayed=True)
    _, absorbed = _matters([both, again]).merge(again, _with(again, _IDS[0], relayed=True), at=_AT)
    assert absorbed == [_IDS[0]], "two relayed pastes are both outside, so they meet"


def test_a_forward_absorbing_a_relayed_paste_records_and_carries_the_relay_mark() -> None:
    """§5:14: recorded on the joined input in the step that appends it, and kept."""
    paste = _running("chat", _IDS[0], order=1, standing=_TYPED)
    forward = _running("line", _IDS[1], order=2, standing=_FROM_SAM)
    _with(paste, relayed=True)
    matters = _matters([paste, forward])

    _, absorbed = matters.merge(forward, _with(forward, _IDS[0]), at=_AT)

    assert absorbed == [_IDS[0]]
    assert [(one.taken_over_from, one.relayed) for one in forward.joined] == [(_IDS[0], True)]

    # A later version of the absorber that marks nothing leaves it relayed.
    later = _with(forward, relayed=False)
    assert not later.relayed
    assert [one.relayed for one in forward.joined] == [True]

    # The absorber's episode, frozen before any further version, keeps it.
    frozen = forward.open_processing()
    assert [one.relayed for one in frozen.joined] == [True]

    # A newer activation absorbing the absorber carries the mark again.
    newest = _running("line", _IDS[2], order=3, standing=_FROM_ANA)
    matters = _matters([paste, forward, newest])
    _, absorbed = matters.merge(newest, _with(newest, _IDS[1]), at=_AT)
    assert absorbed == [_IDS[1]]
    assert [(one.taken_over_from, one.relayed) for one in newest.joined] == [
        (_IDS[1], False),
        (_IDS[1], True),
    ]


def test_a_take_of_an_offered_relayed_input_records_the_relay_mark() -> None:
    """§5:14: the take appends the offered input with its relay mark, read as it takes."""
    older = _running("a", _IDS[0], order=1, standing=_FROM_SAM)
    older.committed = True
    _with(older)
    newer = _running("a", _IDS[1], order=2, standing=_TYPED)
    matters = _matters([older, newer])

    decided, absorbed = matters.merge(newer, _with(newer, _IDS[0], relayed=True), at=_AT)

    assert absorbed == []
    assert [one.became for one in decided] == [Became.OFFERED]
    answered = matters.answer(older, _IDS[1], take=True, reason=None)
    assert answered.came_to is TakeAnswer.TAKEN
    assert [(one.taken_over_from, one.relayed) for one in older.joined] == [(_IDS[1], True)]


async def test_an_older_forward_about_to_act_waits_for_a_newer_paste_not_yet_understood() -> None:
    """§8:5's waits: an input no version covers is read both ways, so the forward waits;
    once marked relayed, the paste absorbs it."""
    forward = _running("line", _IDS[0], order=1, standing=_FROM_SAM)
    _with(forward)
    paste = _running("chat", _IDS[1], order=2, standing=_TYPED)
    matters = _matters([forward, paste])
    loop = asyncio.get_running_loop()

    assert not await matters.before_act(forward, loop.time() + 0.05), "it waited"

    waiting = asyncio.ensure_future(matters.before_act(forward, loop.time() + 5))
    await asyncio.sleep(0.01)
    assert not waiting.done(), "it waits for the paste's understanding"
    understood = _with(paste, _IDS[0], relayed=True)
    decided, absorbed = matters.merge(paste, understood, at=_AT)
    paste.takeovers[understood.version] = decided
    matters.changed()

    assert absorbed == [_IDS[0]]
    assert await asyncio.wait_for(waiting, 1), "its decision settles the paste"
    assert forward.stopped


async def test_a_forward_about_to_act_waits_for_no_typed_message_understood_unmarked() -> None:
    """§8:5: once covered, a typed message is of the owner's own class, so nothing waits."""
    forward = _running("line", _IDS[0], order=1, standing=_FROM_SAM)
    _with(forward)
    typed = _running("chat", _IDS[1], order=2, standing=_TYPED)
    _with(typed)
    matters = _matters([forward, typed])
    loop = asyncio.get_running_loop()

    assert await matters.before_act(forward, loop.time() + 0.05)

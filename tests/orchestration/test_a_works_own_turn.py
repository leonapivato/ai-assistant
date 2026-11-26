"""A work's own turn is written into its own places outside the filter (ADR-0387).

Milestone 22's B8f. Four things go through the unbound conversation store, and nothing
else does: marking the trigger's conversation active, writing a message into one of a
work's own places, recording the turn, and answering whether one of its own places still
stands (§8). Which places are a work's own is decided by code from its inputs alone
(§2:4, ``ActivationState.own_places``); a message into any other place goes through the
store bound to the work's sight (§3:2), and so does every read of any place (§4:3, §5).

With stores built to withhold, an unidentified sender's work, whose sight sees none of
the owner's records, begins its turn, writes its answer, has its turn recorded and
verified, and still reads none of its chat's earlier messages (§8); the position its
reply was written at is kept in its effect record alone and reaches no model and no
surface (§3:4). The owner's work, at normal and lowered to weak, reads and writes as
today, which the counting build answers as.
"""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from identity_support import owners_identities
from phases_support import PHONE, chat_turn, open_conversation, phases_harness, replying
from sight_support import OWNER_WEAK, UNIDENTIFIED
from structlog.testing import capture_logs
from test_engine import AT as ENGINE_AT
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.errors import UnknownConversationError
from ai_assistant.core.types import (
    HUB_DEVICE_ID,
    OWNER_PERSON_ID,
    ChannelIdentity,
    ChannelInput,
    JoinedInput,
    MessageAuthor,
    Modality,
    NewMessage,
    RecordedInputMessage,
    RecordHome,
    SendOutcome,
    SightMode,
    Sureness,
    TextChannelPayload,
    TranscriptMessage,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    CaptureFacts,
    admit_channel,
)
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.channel_kinds import place_of
from ai_assistant.orchestration.chat import ChatWriter
from ai_assistant.orchestration.conversations import (
    ConversationLifecycle,
    conversation_channel,
    episodes_on_place,
)
from ai_assistant.orchestration.task_manager import PlaceLists
from ai_assistant.orchestration.work_facts import chat_account
from ai_assistant.testing import (
    FakeConversationStore,
    FakeIdentityStore,
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanStore,
)
from ai_assistant.testing.parties import OWNER_SENDER

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator, Sequence

    from test_engine import Harness

    from ai_assistant.core.types import (
        Conversation,
        ConversationDigest,
        EpisodeCaptureReport,
        EpisodicMemory,
        InputSender,
    )
    from ai_assistant.orchestration.activation_state import ActivationState

_AT: Final = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
_WORK: Final = "60f3c223-6a54-4b06-aab8-4fc397c3d43b"
_LIMIT: Final = 4096

#: The senders whose work reads as the owner's: ADR-0383 §6's first row, and lowered.
_OWNERS: Final = pytest.mark.parametrize(
    "sender", [OWNER_SENDER, OWNER_WEAK], ids=["normal", "weak"]
)


async def _drain(work: Awaitable[None]) -> None:
    await work


# --- the stores and the work ---------------------------------------------------------------


class _Space:
    """The owner's chat space, with three conversations of the owner's: ``here``, the one a
    work's input came through, ``there`` and ``beyond``, two others."""

    def __init__(self, mode: SightMode) -> None:
        ids = iter(("c-here", "c-there", "c-beyond"))
        self.store = FakeConversationStore(
            now=lambda: _AT, new_id=lambda: next(ids), sight_mode=mode
        )
        self.memory = FakeMemoryStore(now=lambda: _AT, sight_mode=mode)
        self.stores = BoundStores(memory=self.memory, conversations=self.store)

    async def open(self) -> tuple[str, str, str]:
        made = [(await self.store.start(home=RecordHome.owners())).id for _ in range(3)]
        here, there, beyond = made
        return here, there, beyond

    def writer(self) -> ChatWriter:
        return ChatWriter(conversations=self.store, stores=self.stores, max_payload_bytes=_LIMIT)

    async def texts(self, conversation_id: str) -> list[str]:
        page = await self.store.transcript(conversation_id, limit=50)
        assert page is not None
        return [one.text for one in page.entries if isinstance(one, TranscriptMessage)]


def _admitted(*senders: InputSender, came_through: str, text: str = "hello") -> ActivationState:
    """A hub chat message from ``senders`` in ``came_through``, admitted as the chat's
    reader admits one, so its sight is the one admission makes (ADR-0383 §6:4)."""
    return admit_channel(
        ChannelInput(
            target=conversation_channel(came_through), payload=TextChannelPayload(text=text)
        ),
        WholeTextReply(),
        clock=lambda: _AT,
        id_factory=lambda: _WORK,
        senders=senders or (OWNER_SENDER,),
    )


def _joins(state: ActivationState, came_through: str) -> None:
    """An input from ``came_through`` joins ``state``, as an absorption brings one."""
    state.take_inputs(
        [
            JoinedInput(
                joined_at=_AT,
                channel=conversation_channel(came_through),
                messages=(RecordedInputMessage(text="and this", sent_at=_AT),),
                taken_over_from="act-absorbed",
            )
        ],
        merged=["act-absorbed"],
    )


@contextlib.contextmanager
def _running(state: ActivationState) -> Iterator[ActivationState]:
    token = CURRENT_ACTIVATION.set(ActivationScope(state))
    try:
        yield state
    finally:
        CURRENT_ACTIVATION.reset(token)


def _reply(text: str = "the answer") -> NewMessage:
    return NewMessage(author=MessageAuthor.ASSISTANT, text=text, home=RecordHome.owners())


# --- which places are a work's own (§2) ----------------------------------------------------


def test_a_works_own_places_are_its_inputs_places_and_an_approvals_asked_places() -> None:
    """§2:1, §2:2, §2:4: its trigger's place and each joined input's, and an approval's
    work's asked places; never a place its input's text names (§2:3)."""
    state = _admitted(OWNER_SENDER, came_through="c-here", text="write to conversation:c-beyond")
    assert list(state.own_places) == ["conversation:c-here"]
    _joins(state, "c-there")
    assert list(state.own_places) == ["conversation:c-here", "conversation:c-there"]
    assert not state.owns("conversation:c-beyond"), "named by its text, so not its own"
    state.asked_places = ("conversation:c-beyond",)
    assert state.owns("conversation:c-beyond")


# --- writing a message (§3:1, §3:2) --------------------------------------------------------


async def test_an_unidentified_senders_message_into_its_own_place_is_written() -> None:
    """§3:1: written outside the filter, though its sight does not see the place."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    with _running(_admitted(UNIDENTIFIED, came_through=here)) as state:
        assert state.sight is not None
        assert await space.store.bound(state.sight).get(here) is None, "the premise: withheld"
        receipt = await space.writer().send(here, _reply())
    assert receipt is not None
    assert receipt.outcome is SendOutcome.RECORDED
    assert await space.texts(here) == ["the answer"]


async def test_a_message_into_a_place_not_its_own_is_refused_as_one_never_written() -> None:
    """§3:2, ADR-0383 §8:2: through its bound store, a place its sight does not see answers
    as a conversation never started does, and nothing is written there."""
    space = _Space(SightMode.WITHHOLD)
    here, there, _ = await space.open()
    writer = space.writer()
    with _running(_admitted(UNIDENTIFIED, came_through=here)):
        with capture_logs() as unseen:
            into_there = await writer.send(there, _reply())
        with capture_logs() as never:
            into_nothing = await writer.send("c-never-started", _reply())
    assert into_there is None
    assert into_nothing is None
    assert [one for one in unseen if one["event"] != "sight_counted"] == never
    assert await space.texts(there) == []


@_OWNERS
async def test_the_owners_work_writes_into_another_place_as_today(sender: InputSender) -> None:
    """§3:2: the owner's sight sees the owner's places, so its bound store writes there."""
    space = _Space(SightMode.WITHHOLD)
    here, there, _ = await space.open()
    with _running(_admitted(sender, came_through=here)):
        receipt = await space.writer().send(there, _reply())
    assert receipt is not None
    assert receipt.outcome is SendOutcome.RECORDED
    assert await space.texts(there) == ["the answer"]


async def test_in_the_counting_build_every_message_is_written_as_today() -> None:
    space = _Space(SightMode.COUNT)
    here, there, _ = await space.open()
    with _running(_admitted(UNIDENTIFIED, came_through=here)):
        own = await space.writer().send(here, _reply("mine"))
        other = await space.writer().send(there, _reply("elsewhere"))
    assert own is not None
    assert other is not None
    assert (own.outcome, other.outcome) == (SendOutcome.RECORDED, SendOutcome.RECORDED)
    assert (await space.texts(here), await space.texts(there)) == (["mine"], ["elsewhere"])


async def test_a_work_with_several_inputs_writes_into_each_of_their_places() -> None:
    """§6:3: an input joined from another place makes it one of the work's own; a place
    none of its inputs came through stays refused."""
    space = _Space(SightMode.WITHHOLD)
    here, there, beyond = await space.open()
    state = _admitted(UNIDENTIFIED, came_through=here)
    _joins(state, there)
    with _running(state):
        writer = space.writer()
        written = [await writer.send(one, _reply(one)) for one in (here, there, beyond)]
    assert [None if one is None else one.outcome for one in written] == [
        SendOutcome.RECORDED,
        SendOutcome.RECORDED,
        None,
    ]
    assert await space.texts(beyond) == []


async def test_an_approvals_work_writes_where_its_request_was_asked() -> None:
    """§2:2: the places its request was asked from are its own, as code read them."""
    space = _Space(SightMode.WITHHOLD)
    here, there, _ = await space.open()
    state = _admitted(UNIDENTIFIED, came_through=here)
    state.asked_places = (place_of(conversation_channel(there)),)
    with _running(state):
        receipt = await space.writer().send(there, _reply())
    assert receipt is not None
    assert receipt.outcome is SendOutcome.RECORDED


async def test_a_place_deleted_while_the_work_runs_takes_no_message() -> None:
    """§6:1: the store's own check refuses it, as it does today."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    with _running(_admitted(UNIDENTIFIED, came_through=here)):
        await space.store.stamp_deleted(here)
        assert await space.writer().send(here, _reply()) is None


async def test_no_message_is_written_outside_a_running_work() -> None:
    """§3: a message is a work's; outside one there is no own place and no sight."""
    space = _Space(SightMode.COUNT)
    here, _, _ = await space.open()
    with pytest.raises(RuntimeError):
        await space.writer().send(here, _reply())
    assert await space.texts(here) == []


# --- recording the turn (§3:1), and the episode it records --------------------------------


def _capture_writer(space: _Space) -> ActivationWriter:
    return ActivationWriter(
        conversations=space.store,
        stores=space.stores,
        retention=timedelta(days=30),
        now=lambda: _AT,
    )


async def _captured(writer: ActivationWriter, state: ActivationState) -> EpisodeCaptureReport:
    """The episode written at admission, one stage's append, and the freeze."""
    state.facts = CaptureFacts(
        modality=Modality.TEXT, supplied_withheld=False, derived_from_external=False
    )
    state.response = "the answer"
    await writer.admit(state, payload_limit=_LIMIT)
    await writer.append(state, payload_limit=_LIMIT, drain=_drain)
    return await writer.write(
        state,
        state.processing(_AT, None),
        payload_limit=_LIMIT,
        checked_output=lambda: state.processing(_AT, None),
        drain=_drain,
    )


async def test_an_unidentified_senders_turn_is_recorded_and_verified() -> None:
    """§3:1, ADR-0383 §7:4: its episode is read and written through the store bound to its
    sight, which holds it, and the turn is recorded outside the filter."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    state = _admitted(UNIDENTIFIED, came_through=here)

    report = await _captured(_capture_writer(space), state)

    assert report.state == "recorded"
    assert report.episode_id == state.episode_address
    conversation = await space.store.get(here)
    assert conversation is not None
    assert conversation.last_turn_at is not None
    assert await episodes_on_place(space.memory, here) == [state.episode_address]


async def test_a_place_deleted_while_the_work_runs_records_nothing_and_keeps_the_episode() -> None:
    """§6:1, ADR-0293 §2:7: recording the turn writes nothing, and the episode is kept."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    state = _admitted(UNIDENTIFIED, came_through=here)
    writer = _capture_writer(space)
    state.facts = CaptureFacts(
        modality=Modality.TEXT, supplied_withheld=False, derived_from_external=False
    )
    await writer.admit(state, payload_limit=_LIMIT)
    await space.store.stamp_deleted(here)

    report = await writer.write(
        state,
        state.processing(_AT, None),
        payload_limit=_LIMIT,
        checked_output=lambda: state.processing(_AT, None),
        drain=_drain,
    )

    assert report.state == "degraded"
    assert report.episode_id is None
    assert state.episode_address is not None
    kept = await space.memory.get(state.episode_address)
    assert kept is not None, "the episode is kept"


class _Watched(FakeConversationStore):
    """A chat space that counts every call made of it."""

    def __init__(self, **knobs: Any) -> None:
        super().__init__(**knobs)
        self.called: list[str] = []

    def __getattribute__(self, name: str) -> Any:
        found = super().__getattribute__(name)
        if not name.startswith("_") and callable(found) and name not in {"bound", "called"}:
            super().__getattribute__("called").append(name)
        return found


async def test_a_trigger_that_came_through_no_conversation_marks_and_records_nothing() -> None:
    """§6:3: an event's work records its episode and tells no conversation of it."""
    store = _Watched(now=lambda: _AT)
    memory = FakeMemoryStore(now=lambda: _AT, sight_mode=SightMode.WITHHOLD)
    writer = ActivationWriter(
        conversations=store,
        stores=BoundStores(memory=memory, conversations=store),
        retention=None,
        now=lambda: _AT,
    )
    state = admit_channel(
        ChannelInput(
            target=ChannelIdentity(channel_type="informational_event", instance_id="sensor"),
            payload=TextChannelPayload(text="the door opened"),
        ),
        None,
        clock=lambda: _AT,
        id_factory=lambda: _WORK,
    )
    assert state.conversation_id is None

    report = await _captured(writer, state)

    assert report.state == "recorded"
    assert store.called == []


# --- marking the trigger's conversation active (§3:1) --------------------------------------


async def test_marking_active_gives_back_the_conversations_id_alone() -> None:
    """§3:1, §3:4: marked outside the filter as the store marks it; nothing of the
    conversation comes back but which it is."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    later = _AT + timedelta(minutes=5)
    lifecycle = ConversationLifecycle(
        conversations=space.store, memory=space.memory, retention=None, now=lambda: later
    )
    space.store._now = lambda: later  # type: ignore[method-assign]

    begun = await lifecycle.begin(here, home=RecordHome.owners())

    assert begun == here
    marked = await space.store.get(here)
    assert marked is not None
    assert marked.last_active_at == later


async def test_a_place_deleted_before_the_turn_begins_refuses_the_turn() -> None:
    """§6:1: marking it active is refused, and so is the turn."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    await space.store.stamp_deleted(here)
    lifecycle = ConversationLifecycle(
        conversations=space.store, memory=space.memory, retention=None, now=lambda: _AT
    )
    with pytest.raises(UnknownConversationError):
        await lifecycle.begin(here, home=RecordHome.owners())


# --- whether one of its own places stands, and the lists (§4) -----------------------------


def _lists(space: _Space) -> PlaceLists:
    return PlaceLists(conversations=space.store, stores=space.stores)


async def test_a_works_own_places_stay_listed_and_any_other_is_read_by_its_sight() -> None:
    """§4:1 to §4:3: its input's place and a taken input's are named from its inputs and
    answered outside the filter; a suggested place it does not see is not listed, as a
    place gone is not."""
    space = _Space(SightMode.WITHHOLD)
    here, there, beyond = await space.open()
    state = _admitted(UNIDENTIFIED, came_through=here)
    _joins(state, there)

    own = await _lists(space).shown(
        input_place=conversation_channel(here),
        suggested=None,
        taken=[conversation_channel(there)],
        work=state,
    )
    suggested = await _lists(space).shown(
        input_place=None, suggested=[place_of(conversation_channel(beyond))], work=state
    )

    assert [one.place for one in own] == [f"conversation:{here}", f"conversation:{there}"]
    assert suggested == ()


@_OWNERS
async def test_the_owners_work_lists_its_places_as_today(sender: InputSender) -> None:
    space = _Space(SightMode.WITHHOLD)
    here, _, beyond = await space.open()
    state = _admitted(sender, came_through=here)
    counted = _Space(SightMode.COUNT)
    await counted.open()

    shown = await _lists(space).shown(
        input_place=None, suggested=[f"conversation:{beyond}"], work=state
    )
    today = await _lists(counted).shown(
        input_place=None, suggested=[f"conversation:{beyond}"], work=state
    )

    assert shown == today
    assert [one.place for one in shown] == [f"conversation:{beyond}"]


async def test_one_of_its_own_places_deleted_is_answered_gone() -> None:
    """§6:1: §4:2 answers that the place is gone."""
    space = _Space(SightMode.WITHHOLD)
    here, _, _ = await space.open()
    state = _admitted(UNIDENTIFIED, came_through=here)
    await space.store.stamp_deleted(here)

    shown = await _lists(space).shown(
        input_place=conversation_channel(here), suggested=None, work=state
    )

    assert shown == ()


async def test_the_connections_section_names_its_origin_and_reads_the_rest_by_its_sight() -> None:
    """§4:1, §4:3: the origin is named from the input; the recent conversations, the
    owner's, are read through the store bound to the work's sight."""
    harness = _engine(SightMode.WITHHOLD, identities=FakeIdentityStore())
    for _ in range(3):
        await harness.conversation_store.start(home=RecordHome.owners())
    origin = (await harness.conversation_store.start(home=RecordHome.owners())).id

    with _running(_admitted(UNIDENTIFIED, came_through=origin)):
        unseen, _ = await harness.engine._shown_connections(conversation_channel(origin))
    with _running(_admitted(OWNER_SENDER, came_through=origin)):
        seen, _ = await harness.engine._shown_connections(conversation_channel(origin))
    await harness.engine.aclose()

    def chats(shown: Sequence[Any]) -> list[str]:
        return [one.place for one in shown if one.place.startswith("conversation:")]

    assert chats(unseen) == [f"conversation:{origin}"]
    assert len(chats(seen)) > 1
    assert chats(seen)[0] == f"conversation:{origin}"


# --- through the engine: the decision's own test (§8) --------------------------------------

#: How many of the owner's messages the chat holds before the work's input, so the reply
#: lands at a position no rendering would show by chance.
_EARLIER: Final = 120
#: What the owner's earlier messages say, which no work of an unidentified sender reads.
_EARLIER_WORDS: Final = "the boat code is 7731"


def _engine(
    mode: SightMode,
    *,
    identities: FakeIdentityStore,
    model: FakeModelProvider | None = None,
    completer: Any = None,
) -> Harness:
    """An engine whose memory, chat space and plan store are built in ``mode``."""
    ids = iter(f"c-{n}" for n in range(1, 50))
    return phases_harness(
        completer or replying(),
        memory=FakeMemoryStore(now=lambda: ENGINE_AT, sight_mode=mode),
        conversation_store=FakeConversationStore(
            now=lambda: ENGINE_AT, new_id=lambda: next(ids), sight_mode=mode
        ),
        plans=FakePlanStore(now=lambda: ENGINE_AT, sight_mode=mode),
        identities=identities,
        understanding=understanding_stage(model=model or FakeModelProvider(reply=STATED_PROPOSAL)),
    )


class _Turn:
    """One turn through the engine, after the owner's earlier messages, and what it left."""

    def __init__(self, harness: Harness, model: FakeModelProvider, completer: Any) -> None:
        self.harness = harness
        self.model = model
        self.completer = completer
        self.conversation = ""
        self.episode: EpisodicMemory | None = None
        self.view: ConversationDigest | None = None

    @classmethod
    async def run(cls, mode: SightMode, identities: FakeIdentityStore) -> _Turn:
        model = FakeModelProvider(reply=STATED_PROPOSAL)
        completer = replying()
        harness = _engine(mode, identities=identities, model=model, completer=completer)
        turn = cls(harness, model, completer)
        turn.conversation = await open_conversation(harness)
        for n in range(_EARLIER):
            await harness.conversation_store.append_message(
                turn.conversation, _reply(f"note {n}: {_EARLIER_WORDS}")
            )
        try:
            _, turn.episode = await chat_turn(
                harness, "what is the code?", conversation=turn.conversation
            )
            turn.view = await harness.engine.conversation(turn.conversation)
        finally:
            await harness.engine.aclose()
        return turn

    @property
    def activation_id(self) -> str:
        assert self.episode is not None
        record = self.episode.processing_record
        assert record is not None
        return record.activation_id

    async def messages(self) -> list[tuple[int, MessageAuthor, str]]:
        page = await self.harness.conversation_store.transcript(self.conversation, limit=500)
        assert page is not None
        return [
            (one.position, one.author, one.text)
            for one in page.entries
            if isinstance(one, TranscriptMessage)
        ][_EARLIER:]

    def model_inputs(self) -> list[str]:
        """Every input a model was handed, as rendered: understanding's and each round's."""
        understood = [repr(one) for one in self.model.calls]
        planned = [one.exchange.model_dump_json() for one in self.completer.calls]
        return [*understood, *planned]

    def normalized(self) -> list[str]:
        """:meth:`model_inputs`, the activation's id and the conversation's left out."""
        return [
            one.replace(self.activation_id, "<work>").replace(self.conversation, "<chat>")
            for one in self.model_inputs()
        ]


#: An id code mints for a record of the work's, a round's or a decision's, fresh each run.
_MINTED: Final = re.compile(r"\b(round|decision|effect):[0-9a-f]{32}\b")


def _minted(text: str) -> str:
    """``text`` with each id code minted in it named by the order it first appears."""
    order: dict[str, int] = {}
    return _MINTED.sub(
        lambda one: f"{one.group(1)}:<{order.setdefault(one.group(0), len(order))}>", text
    )


async def _lowered(store: FakeIdentityStore, level: Sureness) -> FakeIdentityStore:
    """The owner's links, the phone's and the hub machine's lowered to ``level``."""
    for device in (PHONE.device_id, HUB_DEVICE_ID):
        account = chat_account(device)
        assert account is not None
        link = await store.find_link(account)
        assert link is not None
        await store.lower(link.id, level, by=OWNER_PERSON_ID)
    return store


async def test_an_unidentified_senders_work_begins_answers_and_is_recorded_reading_nothing() -> (
    None
):
    """§8: under a store that withholds, an unidentified sender's work begins its turn,
    writes its answer, has its turn recorded and verified, and still reads none of its
    chat's earlier messages."""
    turn = await _Turn.run(SightMode.WITHHOLD, FakeIdentityStore())
    assert turn.episode is not None
    record = turn.episode.processing_record
    assert record is not None
    assert record.trigger.senders[0].person is None, "the premise: an unidentified sender"

    begun = [one for one in record.stages if one.stage.value == "begin_conversation"]
    assert [one.outcome.value for one in begun] == ["done"]
    messages = await turn.messages()
    assert [(author, text) for _, author, text in messages] == [
        (MessageAuthor.USER, "what is the code?"),
        (MessageAuthor.ASSISTANT, "fake planning round"),
    ]
    conversation: Conversation | None = await turn.harness.conversation_store.get(turn.conversation)
    assert conversation is not None
    assert conversation.last_turn_at is not None, "the turn was recorded"
    assert record.trigger.channel == conversation_channel(turn.conversation)
    assert await episodes_on_place(turn.harness.memory, turn.conversation) == [turn.episode.id], (
        "and verified: the episode is on its place"
    )
    assert turn.model_inputs()
    assert not any(_EARLIER_WORDS in one or "note 0" in one for one in turn.model_inputs())


async def test_the_position_a_reply_was_written_at_reaches_no_model_and_no_surface() -> None:
    """§3:4: kept in the work's effect record alone. It reaches no model input as
    rendered, no later round's report, and not the episode a surface shows."""
    turn = await _Turn.run(SightMode.WITHHOLD, FakeIdentityStore())
    assert turn.episode is not None
    (_, (reply_at, author, _)) = await turn.messages()
    assert author is MessageAuthor.ASSISTANT
    effects = await turn.harness.plans.activation_effects([turn.activation_id])
    assert [one.position for one in effects if not one.is_call] == [reply_at]

    shown = re.compile(rf"(?<![\w.]){reply_at}(?![\w.])")
    assert len(turn.completer.calls) >= 2, "a round was planned after the reply was written"
    assert not any(shown.search(one) for one in turn.model_inputs())
    assert not shown.search(turn.episode.model_dump_json())
    assert turn.view is not None
    assert not shown.search(turn.view.model_dump_json())


@pytest.mark.parametrize("level", [Sureness.NORMAL, Sureness.WEAK], ids=["normal", "weak"])
async def test_the_owners_turn_is_as_today_byte_for_byte(level: Sureness) -> None:
    """The owner's work, at normal and lowered to weak: the same messages, the same model
    inputs and the same record under a store that withholds as under the counting build,
    which answers as the unbound store did."""

    async def identities() -> FakeIdentityStore:
        store = owners_identities()
        return store if level is Sureness.NORMAL else await _lowered(store, level)

    withheld = await _Turn.run(SightMode.WITHHOLD, await identities())
    counted = await _Turn.run(SightMode.COUNT, await identities())
    assert withheld.episode is not None
    assert counted.episode is not None
    record = withheld.episode.processing_record
    assert record is not None
    assert record.trigger.senders[0].level is level, "the premise: the owner at this level"

    assert await withheld.messages() == await counted.messages()
    assert withheld.normalized() == counted.normalized()
    assert _EARLIER_WORDS in "".join(withheld.model_inputs()), "the owner's window shows the chat"

    def kept(turn: _Turn) -> str:
        assert turn.episode is not None
        return _minted(turn.episode.model_dump_json().replace(turn.activation_id, "<work>"))

    assert kept(withheld) == kept(counted)


# --- the line (§6:2) -----------------------------------------------------------------------


async def test_on_the_line_no_conversation_is_marked_recorded_or_written() -> None:
    """§6:2: the answer leaves through the line's outbox, and no conversation record is
    marked or recorded: the hub keeps no copy of the chat."""
    from telegram_support import text  # noqa: PLC0415 — the line's own suite's helpers
    from test_phases_telegram import _harness as line_harness  # noqa: PLC0415
    from test_phases_telegram import _Line  # noqa: PLC0415
    from test_phases_telegram import _settled as line_settled  # noqa: PLC0415

    line = _Line()
    line.fake.hold(text(1, "What's on today?", message_id=40))
    store = _Watched(now=lambda: ENGINE_AT, sight_mode=SightMode.WITHHOLD)
    harness = line_harness(
        line,
        conversation_store=store,
        memory=FakeMemoryStore(now=lambda: ENGINE_AT, sight_mode=SightMode.WITHHOLD),
    )
    await harness.engine.start()
    try:
        await line_settled(harness)
    finally:
        await harness.engine.aclose()

    assert line.sent(), "the answer left through the line"
    assert "recent" in store.called, "the watch sees the chat space's reads"
    assert not {"mark_active", "record_turn", "append_message", "start"} & set(store.called)

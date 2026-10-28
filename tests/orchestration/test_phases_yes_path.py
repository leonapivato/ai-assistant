"""ADR-0321 end to end, as ADR-0353 §11 leaves it: a question asked, and a yes that runs nothing.

The phases as the composition root wires them, driven through the engine across
several activations, for #3058's scenarios. Each case scripts planning's rounds and
understanding's reading, because the model's own judgment is QA's to test live; what
these cases pin is what the code owns: how a question is asked and recorded, and who
carries the user's authority. Approvals stop until the authority run (ADR-0353 §11):
understanding is shown no question mark and records no answer pointer whatever its reply
holds, so authorizing's rules, which stand unchanged, find none, every call that needs
the user goes back to planning as needing them, and an identical call already asked is
not asked again (§11:3). The cases a yes ran a call in, ADR-0322 §5's among them, fail
again until approvals are redesigned, and are not here.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_support import chat_turn, frozen, processing, until, written
from story_support import CONVERSATION
from telegram_support import CASE_START_WAIT, CHAT, REFERENCE, YieldingTelegram, text
from test_engine import AT, Harness
from understanding_support import recall_stage

from ai_assistant.core.errors import ClassifiedToolError, OversizedValueError
from ai_assistant.core.types import (
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ApprovalGiver,
    AskedCall,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ChannelInput,
    ClaimedAuthor,
    CostBasis,
    DataTier,
    Idempotency,
    InputOrigin,
    MessageAuthor,
    NewMessage,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProposedCall,
    Reversibility,
    RiskLevel,
    RoundResponse,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    TelegramForwardKind,
    TelegramForwardOrigin,
    TelegramQuotedMessage,
    TelegramUpdate,
    TextChannelPayload,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    TranscriptMessage,
)
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.chat import ChatWriter
from ai_assistant.orchestration.digesting import DIGESTING_PROMPT
from ai_assistant.orchestration.lookups import LookUps
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.phase_path import (
    Delivery,
    Fitted,
    PhasePath,
    PhaseTools,
    PlaceTarget,
    place_window,
)
from ai_assistant.orchestration.planning import APPROVED_ACTION_TOOL, PLANNING_PROMPT, PlaceAuthor
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE, CandidateCalls
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.telegram import TelegramLineSeams, line_channel
from ai_assistant.orchestration.understanding import (
    UNDERSTANDING_PROMPT,
    LineMessage,
    RecentEpisodes,
    TranscriptWindow,
    UnderstandingStage,
    WindowsStage,
)
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanStore,
    FakeStoryStore,
    FakeTelegramBotClient,
    FakeTelegramIntakeRecord,
    FakeToolCallingCompleter,
    FakeToolImplementation,
    FakeWebSearcher,
    default_prompt,
)

#: Understanding's shipped template, as the composition root hands it the stage.
_UNDERSTANDING = default_prompt(UNDERSTANDING_PROMPT)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.types import (
        ActionRequest,
        EpisodicMemory,
        FrozenJson,
        Message,
        MessageReceipt,
        OfferedTool,
        PermissionDecision,
    )
    from ai_assistant.orchestration.person_block import PersonBlocks


def _tool(name: str, properties: Mapping[str, FrozenJson]) -> ToolDefinition:
    """A call in the world: not safe to repeat, its outcome can be unknown, high risk."""
    return ToolDefinition(
        id=name,
        capability=name,
        description=f"{name} for the user.",
        risk_level=RiskLevel.HIGH,
        reversibility=Reversibility.RECOVERABLE,
        side_effecting=True,
        reads=(DataTier.PERSONAL,),
        writes=(DataTier.PERSONAL,),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NONE,
        effect=CapabilityEffect.WORLD,
        leaves_hub=True,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=True,
        safe_to_repeat=False,
        parameters_schema={
            "type": "object",
            "properties": dict(properties),
            "required": list(properties),
            "additionalProperties": False,
        },
    )


#: A booking: the policy confirms it, so it needs the user's yes.
_BOOK: Final = _tool("book", {"date": {"type": "string"}})
#: An email: the policy confirms it, and its body must show whole (§8:9).
_EMAIL: Final = _tool("send_email", {"to": {"type": "string"}, "body": {"type": "string"}})
#: A call the user's settings do not allow: the policy denies it.
_WIPE: Final = _tool("wipe_calendar", {"month": {"type": "string"}})

_TOOLS: Final = (_BOOK, _EMAIL, _WIPE)
_CAPABILITIES: Final = ("web_search", "remember", "book", "send_email", "wipe_calendar")

#: What a digest of the search's result answers.
_DIGESTED: Final = json.dumps({"evidence": [{"text": "It opens at nine.", "source": "D1"}]})

#: The question's text, which understanding's reading finds the question by.
_ASKING: Final = "Shall I book a table for Friday?"
#: The booking's exact line, as the question shows it (§2:5).
_FRIDAY_LINE: Final = 'book — date: "Friday"'
#: The question as the user reads it: the text, then the fixed line code puts above the
#: exact line (the owner's ruling on #3094), then the line.
_QUESTION: Final = f"{_ASKING}\n\nNeeds your yes:\n{_FRIDAY_LINE}"


class _Policy:
    """The test hub's policy: a call in the world needs you, and a wipe is denied.

    It resolves the confirm a yes answers on route (a) (ADR-0321 §4:7), resting the
    allow on that confirm as the trail requires.
    """

    def __init__(self) -> None:
        self.resolved: list[PermissionDecision] = []

    async def decide(self, request: ActionRequest) -> PermissionRuling:
        capability = str(request.tool.capability)
        if capability == _WIPE.capability:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="test: not allowed")
        if request.tool.effect is CapabilityEffect.WORLD and capability != "web_search":
            return PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="test: the world")
        return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="test: allowed")

    async def resolve(self, confirmed: PermissionDecision, *, approved: bool) -> PermissionRuling:
        self.resolved.append(confirmed)
        if not approved:
            return PermissionRuling(outcome=PermissionOutcome.DENY, reason="test: declined")
        return PermissionRuling(
            outcome=PermissionOutcome.ALLOW, reason="test: your yes", authorised_by=confirmed.id
        )


# --- the scripts --------------------------------------------------------------------------

type _Respond = Callable[[Sequence[Message], Sequence[OfferedTool]], RoundResponse]


@dataclass(frozen=True)
class _Hooked:
    """A round whose response is given once ``hook`` has run, inside the activation."""

    hook: Callable[[], Awaitable[None]]
    response: RoundResponse


class _Planner(FakeToolCallingCompleter):
    """Planning's rounds, scripted in order across every activation of a case."""

    def __init__(self) -> None:
        super().__init__()
        self._steps: deque[RoundResponse | _Hooked] = deque()

    def then(self, *steps: RoundResponse | _Hooked) -> None:
        self._steps.extend(steps)

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        assert self._steps, "planning ran a round the case did not script"
        step = self._steps.popleft()
        if isinstance(step, _Hooked):
            await step.hook()
            step = step.response
        self._response = step
        return await super().respond(messages, tools, model=model)

    def shown(self, index: int) -> str:
        """What round ``index``, counted across the case, was shown."""
        return self.calls[index].messages[-1].content

    def offered(self, index: int) -> set[str]:
        """The tools round ``index`` was offered, by name."""
        return {one.name for one in self.calls[index].tools}


def _proposal(**fields: object) -> str:
    return json.dumps({"understanding": "The user answers."} | fields)


class _Reader:
    """Understanding's readings, one per activation, in order.

    A reading approves nothing, or is a yes: a reply in the shape a build before
    ADR-0353 read, whose ``answers`` points at the first question it was shown. No call
    renders a ``Q`` label any more, so the pointer names nothing the call rendered, and
    the drop removes ``answers`` before the parse whatever it holds (§9:14).
    """

    def __init__(self) -> None:
        self._readings: deque[bool] = deque()
        self.model = FakeModelProvider(reply=self._reply)

    def nothing(self) -> None:
        self._readings.append(False)

    def yes(self) -> None:
        self._readings.append(True)

    def _reply(self, messages: Sequence[Message]) -> str:
        del messages
        if self._readings and self._readings.popleft():
            return _proposal(answers=[{"question": "Q1", "parts": [1]}])
        return _proposal()


class _World:
    """What each call in the world did, by capability.

    A capability named in :attr:`unknown` fails its next call with its outcome
    unknown, once, as a call that may have committed does.
    """

    def __init__(self) -> None:
        self.ran: list[tuple[str, dict[str, FrozenJson]]] = []
        self.unknown: set[str] = set()

    def handler(self, capability: str) -> FakeToolImplementation:
        async def run(
            parameters: Mapping[str, FrozenJson], *, idempotency_key: str | None
        ) -> FrozenJson:
            del idempotency_key
            self.ran.append((capability, dict(parameters)))
            if capability in self.unknown:
                self.unknown.discard(capability)
                raise ClassifiedToolError(
                    ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="test: no answer"),
                    effect_may_have_committed=True,
                )
            return None

        return run

    def of(self, capability: str) -> list[dict[str, FrozenJson]]:
        return [values for name, values in self.ran if name == capability]


# --- the hub ------------------------------------------------------------------------------


class _Hub:
    """An engine with the phases wired as the composition root wires them, over fakes.

    The authorizer reads the yes's facts from the one plan store acting claims in, the
    built ``MemoryPolicy`` rules both at authorizing and at the write, and the remember
    runner reads the memory store for what a write-time conflict would replace.
    """

    def __init__(  # noqa: PLR0913 — one keyword per seam a case varies
        self,
        *,
        recall: bool = False,
        aged_out: bool = False,
        plans: FakePlanStore | None = None,
        stories_shown: bool = False,
        telegram: TelegramLineSeams | None = None,
        person: Callable[[FakeMemoryStore], PersonBlocks] | None = None,
    ) -> None:
        self.planner = _Planner()
        self.reader = _Reader()
        self.world = _World()
        self.policy = _Policy()
        self.searcher = FakeWebSearcher(results=("The museum opens at nine every day.",))
        self.stories = FakeStoryStore(now=lambda: AT)
        self.memory = FakeMemoryStore(now=lambda: AT)
        self.harness = Harness(
            memory=self.memory,
            plans=plans,
            understanding=UnderstandingStage(
                model=self.reader.model, excerpt_chars=2000, prompt=_UNDERSTANDING
            ),
            recall=recall_stage(self.memory) if recall else None,
            # A question asked long enough ago has left the episode window, and is
            # found through recall alone.
            windows=(
                WindowsStage(
                    episodes=RecentEpisodes(memory=FakeMemoryStore(now=lambda: AT), limit=10)
                )
                if aged_out
                else None
            ),
            phases=self.phases,
            # Understanding is shown the candidate stories' short views (ADR-0300 §6).
            story_candidates=StoryCandidates(
                stories=self.stories, memory=self.memory, limit=5, lines=3, notes=2, episodes=2
            )
            if stories_shown
            else None,
            story_links=StoryLinksStage(stories=self.stories) if stories_shown else None,
            telegram=telegram,
            # ADR-0338 §7:1, §8:4: the person block's assembly over the hub's memory
            # store, where a case wires a person-model store.
            person_blocks=None if person is None else person(self.memory),
        )
        for tool in _TOOLS:
            self.harness.invoker.register(tool, self.world.handler(str(tool.capability)))

    def phases(self, harness: Harness, *, writer: ChatWriter | None = None) -> PhasePath:
        tools = PhaseTools(
            registry=harness.invoker,
            invoker=harness.invoker,
            own_records=(REMEMBER_CANDIDATE,),
            searcher=self.searcher,
            search_query="query",
        )
        similar = LookUps(memory=harness.memory, views=None, search_limit=5)
        return PhasePath(
            planning_prompt=default_prompt(PLANNING_PROMPT),
            completer=self.planner,
            provider=FakeModelProvider(reply=_DIGESTED),
            authorizing=AuthorizingStage(
                registry=tools,
                policy=self.policy,
                trail=harness.trail,
                stories=self.stories,
                memory=harness.memory,
                plans=harness.plans,
                now=lambda: AT,
            ),
            acting=ActingStage(
                plans=harness.plans,
                invoker=tools,
                own_records=OwnRecordsByCapability(
                    {"remember": CandidateCalls(similar=similar, limit=5)}
                ),
                timeout=timedelta(seconds=5),
                now=lambda: AT,
            ),
            tools=tools,
            plans=harness.plans,
            writer=writer
            or ChatWriter(
                conversations=harness.conversation_store,
                max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES,
            ),
            capabilities=_CAPABILITIES,
            round_limit=4,
            round_wait=timedelta(seconds=5),
            excerpt_chars=2000,
            part_chars=4000,
            memory=harness.memory,
            recall_cap=6,
            recall_digest_wait=timedelta(seconds=5),
            now=lambda: AT,
            digesting_prompt=default_prompt(DIGESTING_PROMPT),
        )

    async def turn(
        self, text: str, *, conversation: str | None = None, message_id: str = "m-1"
    ) -> tuple[str, EpisodicMemory]:
        """One message from the user, and the episode its activation froze."""
        return await chat_turn(self.harness, text, conversation=conversation, message_id=message_id)

    async def line_turn(
        self, fake: FakeTelegramBotClient, update: TelegramUpdate
    ) -> EpisodicMemory:
        """One update the line takes in, and the episode its activation froze."""
        before = {one.id for one in await frozen(self.harness)}
        fake.hold(update)
        found: list[EpisodicMemory] = []

        async def done() -> bool:
            found[:] = [one for one in await frozen(self.harness) if one.id not in before]
            return bool(found) and fake.held == ()

        await until(done, what="the line's activation to settle")
        (episode,) = found
        return episode

    async def said(self, conversation: str) -> list[TranscriptMessage]:
        """The assistant's messages in ``conversation``, oldest first."""
        return [
            one
            for one in await written(self.harness, conversation)
            if one.author is MessageAuthor.ASSISTANT
        ]

    async def linked(self, *activations: str) -> None:
        """One story holding these activations and the one running now (ADR-0321 §4:11)."""
        state = active_state()
        assert state is not None
        assert state.activation_id is not None
        await self.stories.create(
            [
                StoryMember(kind=StoryMemberKind.ACTIVATION, id=one)
                for one in (*activations, state.activation_id)
            ],
            actor=StoryActor.OWNER,
        )


def _call(call_id: str, name: str, **arguments: object) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)  # type: ignore[arg-type]  # JSON values


def _book(date: str = "Friday", **marks: object) -> RoundResponse:
    """A round proposing the booking, writing nothing."""
    return RoundResponse(calls=(_call("c1", "book", date=date, **marks),))


def _ask(text: str = _ASKING, *refs: str) -> RoundResponse:
    """A round whose message asks about the calls ``refs`` name: round 1's first call."""
    return RoundResponse(text=text, asks=refs or ("1.1",))


def _run_approved(label: str = "A1") -> RoundResponse:
    """A round proposing the approved action ``label`` names, by its label alone."""
    return RoundResponse(calls=(_call("c1", APPROVED_ACTION_TOOL, action=label),))


_DONE: Final = RoundResponse(text="Done.")


async def _asked(hub: _Hub) -> tuple[str, EpisodicMemory]:
    """The booking asked about in a conversation of its own: round 1 needs you, round 2 asks."""
    hub.reader.nothing()
    hub.planner.then(_book(), _ask())
    return await hub.turn("Book a table for Friday.")


def _asked_calls(episode: EpisodicMemory) -> list[tuple[AskedCall, ...]]:
    """What each of the episode's rounds recorded its message asking about."""
    return [one.asked for one in processing(episode).rounds]


def _activation(episode: EpisodicMemory) -> str:
    return processing(episode).activation_id


# --- a booking (§8:1) ---------------------------------------------------------------------


async def test_a_booking_is_asked_with_its_exact_line_and_a_yes_runs_nothing() -> None:
    """ADR-0353 §11:1-§11:3: the question is asked and recorded as before; a yes to it
    records no pointer, so planning is shown no approved action, and the booking
    proposed again goes back as needing the user, already asked, and is not asked again."""
    hub = _Hub()
    conversation, asking = await _asked(hub)

    (question,) = await hub.said(conversation)
    assert question.text == _QUESTION
    assert not question.cut_off
    (asked,) = _asked_calls(asking)[1]
    assert (asked.part, asked.values) == (1, {"date": "Friday"})
    assert "needs the user's yes" in hub.planner.shown(1)
    assert hub.world.of("book") == []

    async def link() -> None:
        await hub.linked(_activation(asking))

    hub.reader.yes()
    hub.planner.then(
        _Hooked(link, _book()), RoundResponse(text="I'm waiting on your answer above.")
    )
    _, yes = await hub.turn("Yes please.", conversation=conversation, message_id="m-2")

    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)
    assert APPROVED_ACTION_TOOL not in hub.planner.offered(2)
    assert "already asked about" in hub.planner.shown(3)
    assert _asked_calls(yes) == [(), ()]
    assert "answers" not in processing(yes).understanding[-1].model_dump()
    # Understanding was shown the question's message, and no mark on it.
    shown = hub.reader.model.calls[-1].messages[-1].content
    assert _ASKING in shown
    assert "answer_label" not in shown
    assert not [
        one
        for one in await hub.harness.trail.recent(limit=20)
        if one.ruling.outcome is PermissionOutcome.ALLOW and one.approval is not None
    ]


async def test_a_prose_question_in_the_proposing_round_asks_nothing() -> None:
    """#3071, #3072: only a message that showed the exact line asks.

    The proposing round writes "Shall I?" and names a reference it guessed: no call has
    come back yet, so the name is dropped and nothing is recorded as asked. The next
    round is shown the call as needing a yes and not yet asked, and its question carries
    the line.
    """
    hub = _Hub()
    hub.reader.nothing()
    prose = "Friday is free. Shall I book it? Please confirm the details below."
    proposing = RoundResponse(
        text=prose, calls=(_call("c1", "book", date="Friday"),), asks=("1.1",)
    )
    hub.planner.then(proposing, _ask())
    conversation, asking = await hub.turn("Book a table for Friday.")

    assert _asked_calls(asking)[0] == ()
    shown = hub.planner.shown(1)
    assert "needs the user's yes, and is not yet asked" in shown
    assert "already asked" not in shown
    assert [one.text for one in await hub.said(conversation)] == [
        prose,
        _QUESTION,
    ]


async def test_proposing_it_again_while_it_waits_is_already_asked() -> None:
    """§4:11: a call identical to one asked in a story's episode, not yet used."""
    hub = _Hub()
    conversation, asking = await _asked(hub)

    async def link() -> None:
        await hub.linked(_activation(asking))

    hub.reader.nothing()
    hub.planner.then(_Hooked(link, _book()), _ask("Waiting on you for Friday."))
    _, again = await hub.turn(
        "And dinner on Friday, then?", conversation=conversation, message_id="m-2"
    )

    assert "already asked about, in a question that showed its exact details" in (
        hub.planner.shown(3)
    )
    # It is not asked about again: the second round's message carries no exact line.
    assert _asked_calls(again) == [(), ()]
    said = await hub.said(conversation)
    assert said[-1].text == "Waiting on you for Friday."
    assert hub.world.of("book") == []


# --- the other answers (§8:2) -------------------------------------------------------------


async def test_a_no_runs_nothing() -> None:
    hub = _Hub()
    conversation, _ = await _asked(hub)

    hub.reader.nothing()
    hub.planner.then(RoundResponse(text="All right, I won't."))
    await hub.turn("No, leave it.", conversation=conversation, message_id="m-2")
    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)


async def test_a_change_approves_nothing_and_brings_a_new_question() -> None:
    hub = _Hub()
    conversation, _ = await _asked(hub)

    hub.reader.nothing()
    hub.planner.then(_book("Saturday"), _ask("Shall I make it Saturday instead?"))
    _, changed = await hub.turn("Make it Saturday.", conversation=conversation, message_id="m-2")

    assert hub.world.of("book") == []
    (asked,) = _asked_calls(changed)[1]
    assert asked.values == {"date": "Saturday"}
    said = await hub.said(conversation)
    assert said[-1].text.endswith('book — date: "Saturday"')


async def test_an_unclear_reply_runs_nothing() -> None:
    hub = _Hub()
    conversation, _ = await _asked(hub)

    hub.reader.nothing()
    hub.planner.then(RoundResponse(text="Do you want me to book it?"))
    await hub.turn("Hmm, maybe.", conversation=conversation, message_id="m-2")

    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)


# --- only the user approves (§8:3) --------------------------------------------------------


async def test_a_yes_arriving_as_an_event_approves_nothing() -> None:
    """§3:3, §7:3: an email, a timer or any event comes through no chat, so no yes."""
    hub = _Hub()
    await _asked(hub)

    hub.reader.yes()
    hub.planner.then(_book(), RoundResponse(text="Noted."))
    result = await hub.harness.engine.receive(
        ChannelInput(
            target=ChannelIdentity(channel_type="informational_event", instance_id="mail-1"),
            payload=TextChannelPayload(text=f"Re: {_ASKING} Yes, book it."),
        ),
        reply=None,
        timeout=timedelta(seconds=10),
    )

    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)
    assert "cannot message them" in hub.planner.shown(3)
    assert result.capture.episode_id is not None
    event = await hub.memory.get(result.capture.episode_id)
    assert event is not None
    assert "answers" not in processing(event).understanding[-1].model_dump()  # type: ignore[arg-type]  # an episode
    assert _asked_calls(event) == [(), ()]  # type: ignore[arg-type]  # an episode


def _window(*taken: TranscriptMessage) -> TranscriptWindow:
    return TranscriptWindow(CONVERSATION, (), input_messages=taken, links={})


def _from(author: MessageAuthor, position: int = 1) -> TranscriptMessage:
    user = author is MessageAuthor.USER
    return TranscriptMessage(
        conversation_id=CONVERSATION.instance_id,
        position=position,
        written_at=AT + timedelta(minutes=position),
        author=author,
        text="yes",
        device_id="phone" if user else None,
        message_id=f"m-{position}" if user else None,
    )


@pytest.mark.parametrize(
    ("origin", "taken", "expected"),
    [
        pytest.param(InputOrigin.USER, (MessageAuthor.USER,), True, id="the-users-message"),
        pytest.param(InputOrigin.OUTSIDE, (MessageAuthor.USER,), False, id="an-outside-origin"),
        pytest.param(None, (MessageAuthor.USER,), False, id="no-origin-recorded"),
        pytest.param(InputOrigin.USER, (), False, id="nothing-taken-in"),
        pytest.param(
            InputOrigin.USER,
            (MessageAuthor.USER, MessageAuthor.ASSISTANT),
            False,
            id="a-message-not-the-users",
        ),
    ],
)
def test_only_the_users_own_chat_message_carries_their_authority(
    origin: InputOrigin | None, taken: tuple[MessageAuthor, ...], expected: bool
) -> None:
    """§3:3, ADR-0292 §5:5: anything that cannot be established is not the user's."""
    hub = _Hub()
    path = hub.phases(hub.harness)
    messages = tuple(_from(author, position) for position, author in enumerate(taken, 1))

    working = path.begin(
        activation_id="a-2",
        window=_window(*messages),
        conversation_id=CONVERSATION.instance_id,
        trigger_origin=origin,
        owner_records=True,
    )

    assert working.users_authority is expected
    assert working.given_at == (messages[-1].written_at if messages else None)


class _NoWrites:
    """A place writer no case here reaches: it only names the place."""

    def fitted(self, text: str) -> Fitted:
        return Fitted(text=text)

    async def deliver(self, fitted: Fitted, *, effect_id: str) -> Delivery:
        raise AssertionError


_LINE = line_channel(REFERENCE, CHAT)


def _said_on_the_line(position: int, author: MessageAuthor = MessageAuthor.USER) -> LineMessage:
    return LineMessage(
        position=position,
        written_at=AT + timedelta(minutes=position),
        author=author,
        text="yes",
    )


@pytest.mark.parametrize(
    ("origin", "forwarded", "expected"),
    [
        pytest.param(InputOrigin.USER, (), True, id="the-owners-own-messages"),
        pytest.param(InputOrigin.OUTSIDE, (2,), False, id="a-forward-among-them"),
        pytest.param(InputOrigin.USER, (2,), False, id="a-forward-whatever-the-origin"),
        pytest.param(InputOrigin.OUTSIDE, (), False, id="an-outside-origin"),
    ],
)
def test_on_the_line_only_the_owners_own_messages_none_forwarded_carry_authority(
    origin: InputOrigin, forwarded: tuple[int, ...], expected: bool
) -> None:
    """ADR-0323 §4:6: every message taken in is the user's, established, none a forward."""
    hub = _Hub()
    path = hub.phases(hub.harness)
    taken = (_said_on_the_line(1), _said_on_the_line(2))
    window = TranscriptWindow(
        _LINE,
        (),
        input_messages=taken,
        forwarded={one: ClaimedAuthor(name="Sam") for one in forwarded},
    )

    working = path.begin_line(
        activation_id="a-2",
        window=window,
        target=PlaceTarget(channel=_LINE, writer=_NoWrites()),
        description="the line",
        giver=ApprovalGiver.USER_THROUGH_TELEGRAM,
        trigger_origin=origin,
        owner_records=True,
    )

    assert working.users_authority is expected
    assert working.given_at == taken[-1].written_at
    assert working.giver is ApprovalGiver.USER_THROUGH_TELEGRAM
    assert working.conversation_id is None
    assert working.target is not None
    assert working.target.place == f"telegram:{_LINE.instance_id}"


def test_a_forward_in_the_lines_window_is_someone_elses_whose_text_planning_never_sees() -> None:
    """ADR-0323 §4:10, ADR-0307 §9:2: a forward is ``other``'s in the place window."""
    window = TranscriptWindow(
        _LINE,
        (_said_on_the_line(1, MessageAuthor.ASSISTANT),),
        input_messages=(_said_on_the_line(2), _said_on_the_line(3)),
        forwarded={2: ClaimedAuthor(name="Sam")},
    )

    place = place_window(window, description="the line")

    assert [one.author for one in place.items] == [
        PlaceAuthor.ASSISTANT,
        PlaceAuthor.OTHER,
        PlaceAuthor.USER,
    ]


def test_an_event_never_carries_the_users_authority() -> None:
    hub = _Hub()
    working = hub.phases(hub.harness).begin_event(
        activation_id="a-2", trigger_origin=InputOrigin.USER, owner_records=True
    )

    assert working.users_authority is False
    assert working.conversation_id is None


async def test_a_bare_yes_with_nothing_to_connect_it_to_records_no_pointer() -> None:
    hub = _Hub()

    hub.reader.nothing()
    hub.planner.then(RoundResponse(text="Yes to what?"))
    _, bare = await hub.turn("Yes.")

    assert "answers" not in processing(bare).understanding[-1].model_dump()
    assert "approved_actions" not in hub.planner.shown(0)
    assert hub.world.ran == []


# --- a deny (§8:7) ------------------------------------------------------------------------


async def test_a_deny_is_never_asked_about() -> None:
    hub = _Hub()
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "wipe_calendar", month="May"),)),
        _ask("Your settings do not allow that."),
    )
    conversation, denied = await hub.turn("Wipe my calendar for May.")

    assert "never ask the user about it" in hub.planner.shown(1)
    assert _asked_calls(denied) == [(), ()]
    (said,) = await hub.said(conversation)
    assert said.text == "Your settings do not allow that."
    assert hub.world.ran == []


# --- email (§8:9) -------------------------------------------------------------------------


async def test_an_emails_full_text_is_in_its_exact_line() -> None:
    hub = _Hub()
    body = "Running late.\nSee you at 7."
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "send_email", to="sam@example.com", body=body),)),
        _ask("Shall I email Sam that you are running late?"),
    )
    conversation, _ = await hub.turn("Email Sam that I'm running late.")

    (question,) = await hub.said(conversation)
    line = question.text.splitlines()[-1]
    assert json.dumps(body) in line
    assert '"sam@example.com"' in line
    assert hub.world.of("send_email") == []


# --- a question cut to fit is not shown (§4:4) --------------------------------------------


async def test_a_question_cut_to_fit_is_not_approvable_and_is_asked_again_whole() -> None:
    hub = _Hub()
    long = (
        _ASKING
        + " "
        + "It is the corner table by the window. " * (TRANSCRIPT_MESSAGE_MAX_CHARS // 30)
    )
    hub.reader.nothing()
    hub.planner.then(_book(), _ask(long))
    conversation, cut = await hub.turn("Book a table for Friday.")

    (question,) = await hub.said(conversation)
    assert question.cut_off
    assert _FRIDAY_LINE not in question.text
    assert _asked_calls(cut) == [(), ()], "a cut question records no asked call"

    # A yes approves nothing: planning is shown no approved action, and the call
    # proposed again is not held back as already asked, so it is asked again, whole.
    hub.reader.yes()
    hub.planner.then(_book(), _ask())
    _, again = await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    assert "approved_actions" not in hub.planner.shown(2)
    assert "already asked" not in hub.planner.shown(3)
    assert [len(one) for one in _asked_calls(again)] == [0, 1]
    assert (await hub.said(conversation))[-1].text == _QUESTION
    assert hub.world.ran == []


async def test_the_fixed_line_counts_toward_the_size_a_question_must_fit() -> None:
    """#3094 with §4:4: the cut rule measures the whole message, the fixed line in it.

    The text and the exact line alone come to the transcript's bound exactly, so only
    the fixed line puts the question over it: it is cut, and records no asked call.
    """
    hub = _Hub()
    long = _ASKING + "x" * (TRANSCRIPT_MESSAGE_MAX_CHARS - len(f"{_ASKING}\n\n{_FRIDAY_LINE}"))
    assert len(f"{long}\n\n{_FRIDAY_LINE}") == TRANSCRIPT_MESSAGE_MAX_CHARS
    hub.reader.nothing()
    hub.planner.then(_book(), _ask(long))
    conversation, cut = await hub.turn("Book a table for Friday.")

    (question,) = await hub.said(conversation)
    assert question.cut_off
    assert question.text.startswith(f"{long}\n\nNeeds your yes:\n")
    assert _FRIDAY_LINE not in question.text
    assert _asked_calls(cut) == [(), ()], "a cut question records no asked call"


class _Narrow(ChatWriter):
    """The chat's writer under a payload bound that cuts any message longer than 40."""

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        if len(message.text) <= 40:
            return message
        return message.model_copy(update={"text": message.text[:40], "cut_off": True})


class _Unmeasurable(ChatWriter):
    """A writer under a bound no non-blank prefix fits."""

    def fitted(self, conversation_id: str, message: NewMessage) -> NewMessage:
        msg = "too small for any message"
        raise OversizedValueError(msg, limit=1, size=len(message.text))

    async def send(self, conversation_id: str, message: NewMessage) -> MessageReceipt | None:
        raise AssertionError  # pragma: no cover - nothing is written in these cases


def _asking_round(text: str) -> PlanningRound:
    return PlanningRound(
        id="round:1",
        recorded_at=AT,
        text=text,
        asked=(AskedCall(part=1, tool=_BOOK, values={"date": "Friday"}),),
    )


@pytest.mark.parametrize(
    ("writer", "text", "whole"),
    [
        pytest.param(ChatWriter, _QUESTION, True, id="fits"),
        pytest.param(_Narrow, _QUESTION, False, id="cut-by-the-writer"),
        pytest.param(_Unmeasurable, "Shall I?", False, id="cannot-be-measured"),
    ],
)
def test_a_round_whose_message_the_writer_would_cut_asks_about_nothing(
    writer: type[ChatWriter], text: str, whole: bool
) -> None:
    hub = _Hub()
    path = hub.phases(
        hub.harness,
        writer=writer(
            conversations=hub.harness.conversation_store,
            max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES,
        ),
    )
    working = path.begin(
        activation_id="a-1",
        window=_window(),
        conversation_id=CONVERSATION.instance_id,
        trigger_origin=InputOrigin.USER,
        owner_records=True,
    )
    planned = _asking_round(text)

    shown = path.shown_whole(working, planned)

    assert (shown is planned) is whole
    assert len(shown.asked) == (1 if whole else 0)
    assert shown.text == planned.text


def test_a_round_in_a_place_that_takes_no_message_asks_about_nothing() -> None:
    hub = _Hub()
    path = hub.phases(hub.harness)
    working = path.begin_event(
        activation_id="a-1", trigger_origin=InputOrigin.OUTSIDE, owner_records=True
    )

    assert path.shown_whole(working, _asking_round("Shall I?")).asked == ()


# --- the Telegram line (ADR-0323 §4:7-§4:9, §7) ---------------------------------------------


def _line() -> tuple[FakeTelegramBotClient, TelegramLineSeams]:
    fake = FakeTelegramBotClient(chat_id=CHAT, first_message_id=300)
    return fake, TelegramLineSeams(
        client=YieldingTelegram(fake),
        intake=FakeTelegramIntakeRecord(),
        reference=REFERENCE,
        poll_wait=timedelta(seconds=1),
        poll_bound=timedelta(seconds=2),
        send_bound=timedelta(seconds=1),
        start_wait=CASE_START_WAIT,
    )


async def _asked_on_the_line() -> tuple[_Hub, FakeTelegramBotClient, int, EpisodicMemory]:
    """The booking asked about on the line: the question is the chat's first message."""
    fake, seams = _line()
    hub = _Hub(telegram=seams)
    await hub.harness.engine.start()
    hub.reader.nothing()
    hub.planner.then(_book(), _ask())
    asking = await hub.line_turn(fake, text(1, "Book a table for Friday.", message_id=10))
    ((question_id, question),) = fake.messages
    assert question == _QUESTION, "plain text with its exact lines, no buttons (§7:1)"
    return hub, fake, question_id, asking


def _reply(update_id: int, words: str, question_id: int, **marks: Any) -> TelegramUpdate:
    """The owner's reply to the question's message, which Telegram sends it with (§7:2)."""
    return text(
        update_id,
        words,
        message_id=question_id + update_id,
        reply_to=TelegramQuotedMessage(
            message_id=question_id, sender_id=1, sender_is_bot=True, text=_QUESTION
        ),
        **marks,
    )


async def test_a_typed_yes_on_the_line_approves_nothing() -> None:
    """§4:7-§4:9, §7:2, ADR-0353 §11:3: a typed reply to the question records no pointer,
    so nothing runs and planning is shown no approved action."""
    hub, fake, question_id, _ = await _asked_on_the_line()
    assert hub.world.of("book") == []

    hub.reader.yes()
    hub.planner.then(RoundResponse(text="I'm waiting on your answer above."))
    yes = await hub.line_turn(fake, _reply(2, "Yes please.", question_id))
    await hub.harness.engine.aclose()

    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)
    assert "answers" not in processing(yes).understanding[-1].model_dump()


async def test_a_forward_saying_yes_on_the_line_approves_nothing() -> None:
    """§4:6-§4:7: an input taking in a forward carries no authority, so no yes."""
    hub, fake, question_id, _ = await _asked_on_the_line()
    forward = TelegramForwardOrigin(kind=TelegramForwardKind.USER, name="Sam", account_id=5)

    hub.reader.yes()
    hub.planner.then(_run_approved(), RoundResponse(text="Noted."), _DONE)
    await hub.line_turn(fake, _reply(2, "Yes, book it.", question_id, forward=forward))
    await hub.harness.engine.aclose()

    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)

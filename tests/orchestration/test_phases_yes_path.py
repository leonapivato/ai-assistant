"""ADR-0321 end to end: a question, its answer, and the call run on a yes, over fakes.

The phases as the composition root wires them, driven through the engine across
several activations, for #3058's scenarios. Each case scripts planning's rounds and
understanding's reading, because the model's own judgment is QA's to test live; what
these cases pin is what the code owns. That is how a question is asked and recorded,
how understanding's pointer reaches authorizing and planning, how the facts are checked
against the records, how a part is spent once, and that every failure ends in another
question rather than in a call that runs.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from phases_support import chat_turn, processing, written
from story_support import CONVERSATION, episode
from test_engine import AT, Harness
from understanding_support import recall_stage

from ai_assistant.core.errors import ClassifiedToolError, OversizedValueError
from ai_assistant.core.types import (
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEffect,
    ActivationUnderstanding,
    AnsweredQuestion,
    Approval,
    AskedCall,
    CapabilityEffect,
    CapabilityResult,
    ChannelIdentity,
    ChannelInput,
    ControllerStage,
    CostBasis,
    DataTier,
    Idempotency,
    InputOrigin,
    MemorySource,
    MessageAuthor,
    NewMessage,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    PlanningRound,
    ProposedCall,
    Provenance,
    Reversibility,
    RiskLevel,
    RoundResponse,
    SemanticMemory,
    StageOutcome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    TextChannelPayload,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    TranscriptMessage,
    UnderstandingGround,
    UnderstandingProducer,
)
from ai_assistant.memory import DefaultMemoryPolicy
from ai_assistant.orchestration.acting import ActingStage, OwnRecordsByCapability
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.authorizer import AuthorizingStage
from ai_assistant.orchestration.chat import ChatWriter
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.payloads import DEFAULT_MAX_PAYLOAD_BYTES
from ai_assistant.orchestration.phase_path import PhasePath, PhaseTools, PhaseWorking
from ai_assistant.orchestration.planning import APPROVED_ACTION_TOOL
from ai_assistant.orchestration.remembering import REMEMBER, RememberCalls
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.understanding import (
    RecentEpisodes,
    TranscriptWindow,
    UnderstandingStage,
    WindowsStage,
)
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeModelProvider,
    FakePlanStore,
    FakeStoryStore,
    FakeToolCallingCompleter,
    FakeToolImplementation,
    FakeWebSearcher,
)

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
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.recall import Recalled
    from ai_assistant.orchestration.story_links import Candidates
    from ai_assistant.orchestration.understanding import Fetched, Windows


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


def _labelled(content: str, needle: str) -> list[str]:
    """Every label of an item whose rendering holds ``needle``, in the order shown."""
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            label = value.get("label")
            if isinstance(label, str) and needle in json.dumps(value, ensure_ascii=False):
                found.append(label)
            for one in value.values():
                walk(one)
        elif isinstance(value, list):
            for one in value:
                walk(one)

    walk(json.loads(content))
    return found


def _marked(content: str, needle: str) -> list[tuple[str, str]]:
    """Each question mark whose question holds ``needle``, in the order shown.

    As ``(Q label, label of the item that shows it)``: a message of the place window
    carries its mark as ``question`` (ADR-0322 §4:2), and an episode its questions as
    ``questions_asked``, each with its message; a mark gives its ``Q`` label as
    ``answer_label`` (#3081). A story's latest episodes take no label of their own, so
    the item that shows them is the story.
    """
    found: list[tuple[str, str]] = []

    def walk(value: object, holder: str) -> None:
        if isinstance(value, dict):
            label = value.get("label")
            if isinstance(label, str):
                holder = label
            mark = value.get("question")
            if isinstance(mark, dict) and needle in str(value.get("text", "")):
                found.append((str(mark["answer_label"]), holder))
            asked = value.get("answer_label")
            if isinstance(asked, str) and needle in str(value.get("message", "")):
                found.append((asked, holder))
            for one in value.values():
                walk(one, holder)
        elif isinstance(value, list):
            for one in value:
                walk(one, holder)

    walk(json.loads(content), "")
    return found


def _proposal(**fields: object) -> str:
    return json.dumps({"meaning": "The user answers.", "meaning_ground": "stated"} | fields)


@dataclass(frozen=True)
class _Yes:
    """One question a reading approves: its text, the parts, and where to find it.

    The pointer names the question's ``Q`` label, found where an item of ``prefer``'s
    kind shows it, or else wherever it is first shown; ``unmarked`` names instead the
    ``H`` label of the place-window message holding the text, as a reading that landed
    on a prose question would (ADR-0322 §4:5).
    """

    question: str = _ASKING
    parts: tuple[int, ...] = ()
    prefer: str = "H"
    unmarked: bool = False


class _Reader:
    """Understanding's readings, one per activation, in order.

    A reading is ``None`` for an input that approves nothing, or the questions the input
    says yes to, each with the parts it approves, and the words of an unresolved matter
    the reading also records, if any (#3080).
    """

    def __init__(self) -> None:
        self._readings: deque[tuple[tuple[_Yes, ...], str | None] | None] = deque()
        self.model = FakeModelProvider(reply=self._reply)
        #: The label of the item each pointer's question was found on, in order.
        self.labels: list[str] = []
        #: The label each pointer named, in order.
        self.named: list[str] = []

    def nothing(self) -> None:
        self._readings.append(None)

    def yes(
        self, question: str = _ASKING, *, parts: tuple[int, ...] = (), prefer: str = "H"
    ) -> None:
        self._readings.append(((_Yes(question, parts, prefer),), None))

    def several(self, *yeses: _Yes, unresolved: str | None = None) -> None:
        self._readings.append((yeses, unresolved))

    def _reply(self, messages: Sequence[Message]) -> str:
        reading = self._readings.popleft() if self._readings else None
        if reading is None:
            return _proposal()
        yeses, unresolved = reading
        content = messages[-1].content
        answers: list[dict[str, object]] = []
        for one in yeses:
            if one.unmarked:
                labels = [label for label in _labelled(content, one.question) if label[0] == "H"]
                assert labels, f"understanding was shown no message holding {one.question!r}"
                named, holder = labels[0], labels[0]
            else:
                marks = _marked(content, one.question)
                assert marks, f"understanding was shown no question holding {one.question!r}"
                named, holder = next(
                    (mark for mark in marks if mark[1].startswith(one.prefer)), marks[0]
                )
            self.labels.append(holder)
            self.named.append(named)
            answers.append({"question": named, "parts": list(one.parts)})
        matters = [] if unresolved is None else [{"matter": unresolved, "why_it_matters": "?"}]
        return _proposal(answers=answers, unresolved=matters)


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

    def __init__(
        self,
        *,
        recall: bool = False,
        aged_out: bool = False,
        plans: FakePlanStore | None = None,
        stories_shown: bool = False,
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
            understanding=UnderstandingStage(model=self.reader.model, excerpt_chars=2000),
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
        )
        for tool in _TOOLS:
            self.harness.invoker.register(tool, self.world.handler(str(tool.capability)))

    def phases(self, harness: Harness, *, writer: ChatWriter | None = None) -> PhasePath:
        tools = PhaseTools(
            registry=harness.invoker,
            invoker=harness.invoker,
            own_records=(REMEMBER,),
            searcher=self.searcher,
            search_query="query",
        )
        memory_writer = FakeMemoryWriter(
            store=harness.memory, policy=DefaultMemoryPolicy(), now=lambda: AT
        )
        return PhasePath(
            completer=self.planner,
            provider=FakeModelProvider(reply=_DIGESTED),
            authorizing=AuthorizingStage(
                registry=tools,
                policy=self.policy,
                memory_policy=DefaultMemoryPolicy(),
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
                    {
                        "remember": RememberCalls(
                            writer=memory_writer, memory=harness.memory, now=lambda: AT
                        )
                    }
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
        )

    async def turn(
        self, text: str, *, conversation: str | None = None, message_id: str = "m-1"
    ) -> tuple[str, EpisodicMemory]:
        """One message from the user, and the episode its activation froze."""
        return await chat_turn(self.harness, text, conversation=conversation, message_id=message_id)

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


async def test_a_booking_is_asked_with_its_exact_line_and_a_yes_runs_it_once() -> None:
    hub = _Hub()
    conversation, asking = await _asked(hub)

    (question,) = await hub.said(conversation)
    assert question.text == _QUESTION
    assert not question.cut_off
    (asked,) = _asked_calls(asking)[1]
    assert (asked.part, asked.values) == (1, {"date": "Friday"})
    assert "needs the user's yes" in hub.planner.shown(1)
    assert hub.world.of("book") == []

    hub.reader.yes()
    hub.planner.then(_run_approved(), RoundResponse(text="Booked for Friday."))
    _, yes = await hub.turn("Yes please.", conversation=conversation, message_id="m-2")

    assert hub.world.of("book") == [{"date": "Friday"}]
    assert "approved_actions" in hub.planner.shown(2)
    assert APPROVED_ACTION_TOOL in hub.planner.offered(2)
    (answers,) = processing(yes).understanding[-1].answers
    assert answers.activation_id == _activation(asking)
    assert hub.reader.named == ["Q1"]
    # The decision that ran it names the approval, given in the yes's activation.
    (ran,) = [
        one
        for one in await hub.harness.trail.recent(limit=20)
        if one.approval is not None and one.ruling.outcome is PermissionOutcome.ALLOW
    ]
    assert ran.approval is not None
    assert ran.approval.given.activation_id == _activation(yes)
    assert ran.resolves is not None, "the confirm ruled fresh is resolved on route (a)"


async def test_a_prose_question_in_the_proposing_round_asks_nothing() -> None:
    """#3071, #3072: only a message that showed the exact line asks, and only it is marked.

    The proposing round writes "Shall I?" and names a reference it guessed: no call has
    come back yet, so the name is dropped and nothing is recorded as asked. The next
    round is shown the call as needing a yes and not yet asked, and its question carries
    the line. The prose carries no mark, so a pointer naming it is not recorded and the
    understanding says so (ADR-0322 §4:5); a yes to the question runs it once.
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

    async def link() -> None:
        await hub.linked(_activation(asking))

    assert _marked(hub.reader.model.calls[-1].messages[-1].content, prose) == []
    hub.reader.several(_Yes(prose, unmarked=True))
    hub.planner.then(
        _Hooked(link, _book()), RoundResponse(text="I'm waiting on your answer above.")
    )
    _, pointed = await hub.turn("Yes.", conversation=conversation, message_id="m-2")
    understood = processing(pointed).understanding[-1]
    assert understood.answers == ()
    assert [one.matter for one in understood.unresolved][-1].endswith(
        "is not the Q label of a question the assistant asked."
    )
    assert "approved_actions" not in hub.planner.shown(2)
    assert "already asked about" in hub.planner.shown(3)
    assert hub.world.of("book") == []

    hub.reader.yes()
    hub.planner.then(_run_approved(), _DONE)
    await hub.turn("Yes, that one.", conversation=conversation, message_id="m-3")
    assert hub.world.of("book") == [{"date": "Friday"}]


async def test_a_second_yes_does_not_run_it_again() -> None:
    hub = _Hub()
    conversation, _ = await _asked(hub)
    hub.reader.yes()
    hub.planner.then(_run_approved(), _DONE)
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    # The second yes points at the same question, whose part is spent: planning is
    # shown no approved action, and the call proposed outright needs the user again.
    hub.reader.yes()
    hub.planner.then(_book(), RoundResponse(text="That is already booked."))
    await hub.turn("Yes!", conversation=conversation, message_id="m-3")

    assert hub.world.of("book") == [{"date": "Friday"}]
    assert "approved_actions" not in hub.planner.shown(4)
    assert APPROVED_ACTION_TOOL not in hub.planner.offered(4)
    assert "needs the user's yes" in hub.planner.shown(5)


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


async def test_a_no_runs_nothing_and_a_later_actually_yes_runs_it() -> None:
    hub = _Hub()
    conversation, _ = await _asked(hub)

    hub.reader.nothing()
    hub.planner.then(RoundResponse(text="All right, I won't."))
    await hub.turn("No, leave it.", conversation=conversation, message_id="m-2")
    assert hub.world.of("book") == []
    assert "approved_actions" not in hub.planner.shown(2)

    hub.reader.yes()
    hub.planner.then(_run_approved(), _DONE)
    await hub.turn("Actually, yes.", conversation=conversation, message_id="m-3")

    assert hub.world.of("book") == [{"date": "Friday"}]


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
    _, asking = await _asked(hub)

    hub.reader.yes(prefer="P")
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
    (answers,) = processing(event).understanding[-1].answers  # type: ignore[arg-type]  # an episode
    assert answers.activation_id == _activation(asking)
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


def test_an_event_never_carries_the_users_authority() -> None:
    hub = _Hub()
    working = hub.phases(hub.harness).begin_event(
        activation_id="a-2", trigger_origin=InputOrigin.USER, owner_records=True
    )

    assert working.users_authority is False
    assert working.conversation_id is None


# --- a yes from elsewhere (§8:4) ----------------------------------------------------------


async def test_a_yes_in_another_conversation_through_recall_runs_it() -> None:
    hub = _Hub(recall=True, aged_out=True)
    _, asking = await _asked(hub)

    hub.reader.yes(prefer="M")
    hub.planner.then(_run_approved(), _DONE)
    other, yes = await hub.turn("Yes, book the table for Friday.")

    assert hub.reader.labels[-1].startswith("M"), "found through recall"
    (answers,) = processing(yes).understanding[-1].answers
    assert (answers.activation_id, answers.round) == (
        _activation(asking),
        processing(asking).rounds[1].id,
    )
    assert hub.world.of("book") == [{"date": "Friday"}]
    (said,) = await hub.said(other)
    assert said.text == "Done."


async def test_a_bare_yes_with_nothing_to_connect_it_to_records_no_pointer() -> None:
    hub = _Hub()

    hub.reader.nothing()
    hub.planner.then(RoundResponse(text="Yes to what?"))
    _, bare = await hub.turn("Yes.")

    assert processing(bare).understanding[-1].answers == ()
    assert "approved_actions" not in hub.planner.shown(0)
    assert hub.world.ran == []


# --- memory (§8:5, §5:5) ------------------------------------------------------------------


async def test_after_a_search_a_remember_asks_and_a_yes_saves_it_with_its_source() -> None:
    hub = _Hub()
    statement = "The museum opens at nine."
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(
            calls=(_call("c1", "web_search", query="museum hours", looking_for="when it opens"),)
        ),
        RoundResponse(calls=(_call("c1", "remember", statement=statement),)),
        _ask("It opens at nine. Shall I remember that?", "2.1"),
    )
    conversation, asking = await hub.turn("When does the museum open? Remember it.")

    (asked,) = _asked_calls(asking)[2]
    assert str(asked.tool.capability) == "remember"
    said = await hub.said(conversation)
    assert said[-1].text.endswith(f'remember — statement: "{statement}"')
    assert await _beliefs(hub.memory, statement) == []

    hub.reader.yes("Shall I remember that?")
    hub.planner.then(_run_approved(), RoundResponse(text="Remembered."))
    await hub.turn("Yes, keep that.", conversation=conversation, message_id="m-2")

    (saved,) = await _beliefs(hub.memory, statement)
    # Its source is kept as the proposal carried it, and the decision that wrote it
    # names the approval (§5:3).
    assert saved.provenance.derived_from_external
    assert saved.provenance.source is MemorySource.INFERRED
    (decided,) = [
        one
        for one in await hub.harness.trail.recent(limit=20)
        if str(one.tool.capability) == "remember"
        and one.approval is not None
        and one.ruling.outcome is PermissionOutcome.ALLOW
    ]
    assert decided.approved_part is not None


async def _beliefs(memory: FakeMemoryStore, fact: str) -> list[SemanticMemory]:
    """The live beliefs stating ``fact``."""
    return [
        one
        for one in await memory.export()
        if isinstance(one, SemanticMemory) and one.fact == fact and one.validity.valid_until is None
    ]


async def test_a_conflict_at_write_time_asks_replacing_and_a_yes_retires_what_was_shown() -> None:
    """§5:5, #2845: the writer's ask needs you, showing the assertion it replaces."""
    hub = _Hub()
    statement = "drinks coffee every morning"
    old = f"never {statement}"
    conversation, asking = await _replacing(hub, statement, old)

    (asked,) = _asked_calls(asking)[1]
    assert asked.replaces == ("assertion:1",)
    said = await hub.said(conversation)
    assert f'replacing "{old}"' in said[-1].text.splitlines()[-1]
    assert await _beliefs(hub.memory, old)

    hub.reader.yes("Shall I replace it?")
    hub.planner.then(_run_approved(), RoundResponse(text="Updated."))
    await hub.turn("Yes, replace it.", conversation=conversation, message_id="m-2")

    assert await _beliefs(hub.memory, old) == []
    assert await _beliefs(hub.memory, statement)


async def _replacing(
    hub: _Hub, statement: str, old: str, *, placement: Placement | None = None
) -> tuple[str, EpisodicMemory]:
    """The user's earlier assertion ``old``, and a remember of ``statement`` asked about."""
    asserted = SemanticMemory(
        id="assertion:1",
        content=old,
        fact=old,
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=1.0,
            evidence=("episode:earlier",),
            last_updated=AT,
        ),
    )
    if placement is not None:
        asserted = asserted.model_copy(update={"placement": placement})
    await hub.memory.add(asserted)
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "remember", statement=statement),)),
        _ask("You told me otherwise before. Shall I replace it?"),
    )
    return await hub.turn("Remember that I drink coffee every morning.")


async def test_owner_only_records_a_question_rests_on_place_what_follows_them() -> None:
    """ADR-0309 §5:10: the assertions a question shows replaced, and the asking episode a
    yes reads, are obtained, so the episodes and the belief they lead to are placed by
    them.

    The episode window is empty, so the yes's activation obtains the asking episode
    only through the records its yes leads to.
    """
    hub = _Hub(aged_out=True)
    statement = "drinks coffee every morning"
    owner = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT)
    conversation, asking = await _replacing(hub, statement, f"never {statement}", placement=owner)

    assert asking.placement.reach is PlacementReach.OWNER

    hub.reader.yes("Shall I replace it?")
    hub.planner.then(_run_approved(), RoundResponse(text="Updated."))
    _, yes = await hub.turn("Yes, replace it.", conversation=conversation, message_id="m-2")

    assert yes.placement.reach is PlacementReach.OWNER
    (saved,) = await _beliefs(hub.memory, statement)
    assert saved.placement.reach is PlacementReach.OWNER


# --- a retry after an unknown outcome (§8:6, §6) ------------------------------------------


async def test_a_retry_after_an_unknown_outcome_runs_only_on_a_yes() -> None:
    hub = _Hub()
    conversation, _ = await _asked(hub)
    hub.world.unknown.add("book")
    retry = "I could not tell whether the booking went through. Shall I try again?"

    hub.reader.yes()
    hub.planner.then(_run_approved(), _book(deliberate_repeat=True), _ask(retry, "2.1"))
    _, unknown = await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    assert hub.world.of("book") == [{"date": "Friday"}], "the retry waits on a yes"
    (asked,) = _asked_calls(unknown)[2]
    assert asked.deliberate_repeat

    hub.reader.yes(retry)
    hub.planner.then(_run_approved(), _DONE)
    await hub.turn("Yes, try again.", conversation=conversation, message_id="m-3")

    assert hub.world.of("book") == [{"date": "Friday"}, {"date": "Friday"}]


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


async def test_an_emails_full_text_is_in_its_exact_line_and_a_yes_sends_it_once() -> None:
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

    hub.reader.yes("Shall I email Sam")
    hub.planner.then(_run_approved(), RoundResponse(text="Sent."))
    await hub.turn("Yes, send it.", conversation=conversation, message_id="m-2")

    assert hub.world.of("send_email") == [{"to": "sam@example.com", "body": body}]


# --- several questions in one reply (ADR-0322 §5) -----------------------------------------


def _run_approved_all(count: int) -> RoundResponse:
    """A round proposing approved actions ``A1`` to ``A<count>``, each by its label alone."""
    return RoundResponse(
        calls=tuple(
            _call(f"c{index}", APPROVED_ACTION_TOOL, action=f"A{index}")
            for index in range(1, count + 1)
        )
    )


async def _approvals(hub: _Hub) -> list[Approval]:
    """The approval each allowed decision ran under, in the trail's order."""
    return [
        one.approval
        for one in await hub.harness.trail.recent(limit=50)
        if one.approval is not None and one.ruling.outcome is PermissionOutcome.ALLOW
    ]


async def test_a_change_then_book_both_books_both_nights_once_each() -> None:
    """§5:1: "make it two nights" while the first night's question waits, then "book both".

    The change proposes both nights. Friday is identical to the call still waiting on
    the user, so it goes back as already asked (ADR-0321 §4:12), and the new question
    shows Saturday alone. "Yes, book both" names both questions, each under its own Q
    label, so each night runs under its own question's approval, once.
    """
    hub = _Hub()
    conversation, friday = await _asked(hub)

    async def link() -> None:
        await hub.linked(_activation(friday))

    saturday = "Shall I also book Saturday?"
    hub.reader.nothing()
    hub.planner.then(
        _Hooked(
            link,
            RoundResponse(
                calls=(_call("c1", "book", date="Friday"), _call("c2", "book", date="Saturday"))
            ),
        ),
        _ask(saturday, "1.2"),
    )
    _, changed = await hub.turn("Make it two nights.", conversation=conversation, message_id="m-2")

    assert "already asked about" in hub.planner.shown(3)
    assert [[one.values for one in asked] for asked in _asked_calls(changed)] == [
        [],
        [{"date": "Saturday"}],
    ]

    hub.reader.several(_Yes(_ASKING), _Yes(saturday))
    hub.planner.then(_run_approved_all(2), RoundResponse(text="Both nights are booked."))
    _, both = await hub.turn("Yes, book both.", conversation=conversation, message_id="m-3")

    assert sorted(str(one["date"]) for one in hub.world.of("book")) == ["Friday", "Saturday"]
    assert hub.reader.named == ["Q1", "Q2"]
    answers = processing(both).understanding[-1].answers
    assert [one.activation_id for one in answers] == [_activation(friday), _activation(changed)]
    # One approval per question, each covering its own question's part alone.
    approvals = await _approvals(hub)
    assert len(approvals) == 2
    assert {one.how.activation_id for one in approvals} == {
        _activation(friday),
        _activation(changed),
    }
    assert all(len(one.covers) == 1 for one in approvals)

    # A second "both" runs neither again: each part is spent.
    hub.reader.several(_Yes(_ASKING), _Yes(saturday))
    hub.planner.then(RoundResponse(text="Both are already booked."))
    await hub.turn("Yes, both!", conversation=conversation, message_id="m-4")
    assert "approved_actions" not in hub.planner.shown(5)
    assert len(hub.world.of("book")) == 2


async def test_both_to_two_waiting_questions_one_seen_only_through_recall_books_both() -> None:
    """§5:2: "both", given to two waiting questions, books both, once each.

    The booking was asked in one conversation and the email in another. The yes, in the
    email's conversation, sees the email's question on its message in the place window,
    and the booking's only through recall, each under its own Q label.
    """
    hub = _Hub(recall=True, aged_out=True)
    _, booking = await _asked(hub)
    body = "Running late."
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "send_email", to="sam@example.com", body=body),)),
        _ask("Shall I email Sam that you are running late?"),
    )
    conversation, email = await hub.turn("Email Sam that I'm running late.")

    hub.reader.several(_Yes(_ASKING, prefer="M"), _Yes("Shall I email Sam", prefer="H"))
    hub.planner.then(_run_approved_all(2), _DONE)
    await hub.turn(
        "Yes, book a table for Friday and the email.",
        conversation=conversation,
        message_id="m-2",
    )

    assert [label[0] for label in hub.reader.labels] == ["M", "H"]
    assert hub.world.of("book") == [{"date": "Friday"}]
    assert hub.world.of("send_email") == [{"to": "sam@example.com", "body": body}]
    assert {one.how.activation_id for one in await _approvals(hub)} == {
        _activation(booking),
        _activation(email),
    }


async def test_both_to_two_waiting_questions_one_seen_only_through_a_story_books_both() -> None:
    """§5:2, through a story: the booking's episode shows only in the story's short view.

    The story holds both activations, and the yes's place window links to the email's,
    so the story is a candidate; its latest episodes take no label, so the booking's
    question takes a Q label of its own.
    """
    hub = _Hub(aged_out=True, stories_shown=True)
    _, booking = await _asked(hub)
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "send_email", to="sam@example.com", body="Late."),)),
        _ask("Shall I email Sam that you are running late?"),
    )
    conversation, email = await hub.turn("Email Sam that I'm running late.")
    await hub.stories.create(
        [
            StoryMember(kind=StoryMemberKind.ACTIVATION, id=_activation(booking)),
            StoryMember(kind=StoryMemberKind.ACTIVATION, id=_activation(email)),
        ],
        actor=StoryActor.OWNER,
    )

    hub.reader.several(_Yes(_ASKING, prefer="S"), _Yes("Shall I email Sam", prefer="H"))
    hub.planner.then(_run_approved_all(2), _DONE)
    await hub.turn("Yes, do both.", conversation=conversation, message_id="m-2")

    assert [label[0] for label in hub.reader.labels] == ["S", "H"]
    assert hub.world.of("book") == [{"date": "Friday"}]
    assert hub.world.of("send_email") == [{"to": "sam@example.com", "body": "Late."}]


async def test_a_bare_yes_to_two_waiting_questions_runs_neither() -> None:
    """ADR-0322 §2:3, ADR-0321 §3:5: a bare yes that could fit both records none."""
    hub = _Hub()
    conversation, _ = await _asked(hub)
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "send_email", to="sam@example.com", body="Late."),)),
        _ask("Shall I email Sam that you are running late?"),
    )
    await hub.turn("And email Sam that I'm late.", conversation=conversation, message_id="m-2")

    hub.reader.nothing()
    hub.planner.then(RoundResponse(text="Yes to which: the booking, the email, or both?"))
    _, bare = await hub.turn("Yes.", conversation=conversation, message_id="m-3")

    assert processing(bare).understanding[-1].answers == ()
    assert "approved_actions" not in hub.planner.shown(4)
    assert hub.world.ran == []


async def test_a_bare_yes_read_as_fitting_two_but_pointing_runs_neither_then_both_does() -> None:
    """#3080: the reading says the bare yes fits both questions, and points at one anyway.

    Its own unresolved matter names both questions, so code records no pointer on the
    reading's own word: nothing runs, and planning is shown the matter to ask "yes to
    which?" by (ADR-0322 §2:3, ADR-0321 §3:5). "Both" then says which, and books each
    once (§2:2).
    """
    hub = _Hub()
    conversation, _ = await _asked(hub)
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "send_email", to="sam@example.com", body="Late."),)),
        _ask("Shall I email Sam that you are running late? Say the word and I'll do both."),
    )
    await hub.turn("And email Sam that I'm late.", conversation=conversation, message_id="m-2")

    hub.reader.several(
        _Yes("Shall I email Sam"), unresolved="The yes could approve Q1, Q2 or both."
    )
    hub.planner.then(RoundResponse(text="Yes to which: the booking, the email, or both?"))
    _, bare = await hub.turn("Yes, go ahead.", conversation=conversation, message_id="m-3")

    understood = processing(bare).understanding[-1]
    assert understood.answers == ()
    assert any("does not say which question" in one.matter for one in understood.unresolved)
    assert "approved_actions" not in hub.planner.shown(4)
    assert "does not say which question" in hub.planner.shown(4)
    assert hub.world.ran == []

    hub.reader.several(_Yes(_ASKING), _Yes("Shall I email Sam"))
    hub.planner.then(_run_approved_all(2), _DONE)
    await hub.turn("Both, please.", conversation=conversation, message_id="m-4")

    assert hub.world.of("book") == [{"date": "Friday"}]
    assert hub.world.of("send_email") == [{"to": "sam@example.com", "body": "Late."}]


async def test_a_bare_yes_to_the_one_waiting_question_still_runs_it() -> None:
    """ADR-0321 §3:5 binds several questions: with one shown, a bare yes approves it.

    A matter naming a ``Q`` label the call did not render counts for nothing.
    """
    hub = _Hub()
    conversation, _ = await _asked(hub)

    hub.reader.several(_Yes(_ASKING), unresolved="The yes fits Q1, unless Q2 was meant.")
    hub.planner.then(_run_approved_all(1), _DONE)
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    assert hub.world.of("book") == [{"date": "Friday"}]


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

    # It carries no mark (ADR-0322 §4:1), so a yes read as naming it approves nothing:
    # planning is shown no approved action, and the call proposed again is not held back
    # as already asked, so it is asked again, whole.
    hub.reader.several(_Yes(unmarked=True))
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


# --- the yes's records are read inside the deadline (ADR-0280 §5) -------------------------


class _Stalled(FakePlanStore):
    """A plan store whose read of an activation's effect records never returns."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.entered = asyncio.Event()

    async def activation_effects(
        self, activation_ids: Sequence[str], /
    ) -> tuple[ActivationEffect, ...]:
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError  # pragma: no cover - the wait above never returns


@dataclass(frozen=True)
class _Given:
    """A pass's working set as a phase stage reads it (``PhasePass``)."""

    deadline: float
    phases: PhaseWorking
    understanding: ActivationUnderstanding | None = None
    understanding_fetch: Fetched | None = None
    supply: TurnSupply = field(
        default_factory=lambda: BoundedAudienceSupply(speakable_attested_sources=frozenset())
    )
    windows: Windows | None = None
    recalled: Recalled | None = None
    story_candidates: Candidates | None = None


async def _asked_in(hub: _Hub, activation_id: str, round_id: str, date: str) -> None:
    """``activation_id``'s frozen episode, whose round ``round_id`` asked one booking, shown."""
    stored = episode(activation_id)
    record = stored.processing_record
    assert record is not None
    asked = AskedCall(part=1, tool=_BOOK, values={"date": date})
    planned = PlanningRound(id=round_id, recorded_at=AT, text="Shall I?", asked=(asked,))
    await hub.memory.add(
        stored.model_copy(
            update={"processing_record": record.model_copy(update={"rounds": (planned,)})}
        )
    )
    effect = ActivationEffect(
        id=f"e-{activation_id}",
        activation_id=activation_id,
        round=round_id,
        place=f"conversation:{CONVERSATION.instance_id}",
        claimed_at=AT,
    )
    await hub.harness.plans.claim_activation_effect(effect, match=None)
    await hub.harness.plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED, position=1)


@pytest.mark.parametrize(
    ("rounds", "shown"),
    [
        pytest.param(("round:a", "round:b"), ["Friday", "Saturday"], id="two-rounds"),
        pytest.param(("round:x", "round:x"), [], id="one-round-id-under-two-activations"),
    ],
)
async def test_the_approved_actions_are_gathered_from_every_pointer(
    rounds: tuple[str, str], shown: list[str]
) -> None:
    """ADR-0322 §3:4: every pointer's actions; a part two askers share is shown by neither.

    A part's label names it by its round and number alone, so a part reached from two
    asking activations could not be told apart when proposed (§3:3), and fails closed.
    """
    hub = _Hub()
    await _asked_in(hub, "a-1", rounds[0], "Friday")
    await _asked_in(hub, "a-2", rounds[1], "Saturday")
    path = hub.phases(hub.harness)
    working = path.begin(
        activation_id="a-3",
        window=_window(_from(MessageAuthor.USER)),
        conversation_id=CONVERSATION.instance_id,
        trigger_origin=InputOrigin.USER,
        owner_records=True,
    )
    understanding = ActivationUnderstanding(
        version=1,
        recorded_at=AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="yes to both",
        meaning_ground=UnderstandingGround.STATED,
        answers=(
            AnsweredQuestion(activation_id="a-1", round=rounds[0]),
            AnsweredQuestion(activation_id="a-2", round=rounds[1]),
        ),
    )
    given = _Given(
        deadline=asyncio.get_running_loop().time() + 5,
        phases=working,
        understanding=understanding,
    )

    approved = await path._approved(given, working)

    assert [one.call.values["date"] for one in approved] == shown


async def test_a_stalled_read_of_the_yes_records_times_the_round_out() -> None:
    """Planning's round ends ``timed_out`` at the deadline, never waiting on the store."""
    plans = _Stalled()
    hub = _Hub(plans=plans)
    path = hub.phases(hub.harness)
    working = path.begin(
        activation_id="a-2",
        window=_window(_from(MessageAuthor.USER)),
        conversation_id=CONVERSATION.instance_id,
        trigger_origin=InputOrigin.USER,
        owner_records=True,
    )
    understanding = ActivationUnderstanding(
        version=1,
        recorded_at=AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="the user says yes",
        meaning_ground=UnderstandingGround.STATED,
        answers=(AnsweredQuestion(activation_id="a-1", round="round:1"),),
    )
    given = _Given(
        deadline=asyncio.get_running_loop().time() + 0.2,
        phases=working,
        understanding=understanding,
    )
    (planning,) = [one for one in path.stages() if one.name is ControllerStage.PLANNING]

    result = await asyncio.wait_for(planning.run(given), timeout=5)

    assert plans.entered.is_set()
    assert result.outcome is StageOutcome.TIMED_OUT
    assert hub.planner.calls == []

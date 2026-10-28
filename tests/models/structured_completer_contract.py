"""Shared conformance suite for the StructuredCompleter Protocol (ADR-0354 §2, §5).

Every ``StructuredCompleter`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`StructuredCompleterContract`, overrides the ``completer`` fixture, and
implements :meth:`StructuredCompleterContract.world`, which stands up a subject
scripted to answer with one :class:`Answer` and reports what reached the model
underneath it. What plays the script is the implementation's business: the canonical
fake is its own script, the provider-backed implementation stands up a programmable
pydantic-ai model, the vendor stacks a canned response on a replaced transport, and a
wrapper the fake beneath it.

The suite asserts what is universal to the seam: which calls are refused before any
model is contacted, and with which disposition (§2:3); that every response that comes
back is returned, as the shape's value or as the first of §5:2's four failures that
applies, and never raised; that the reading rule is §3:4's; that one call is one
request at the model, whatever came back (§4:1); what the exchange carries (§5:3); and
the input-observation clause (§2:4, ADR-0065), enforced as ``ModelProviderContract``
enforces it (ADR-0069).

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

import pytest
from model_provider_contract import ConversationLog, FirstAwaitGate
from pydantic import BaseModel, ConfigDict, Field, Json, JsonValue

from ai_assistant.core.errors import ModelError, ModelUnavailableError
from ai_assistant.core.protocols import StructuredCompleter
from ai_assistant.core.reply_shapes import reply_shape_version
from ai_assistant.core.types import (
    Message,
    ReplyFailure,
    ReplyMode,
    ReplyUsage,
    Role,
    StructuredReply,
)
from ai_assistant.testing import FakeStructuredCompleter, ScriptedReply

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.testing.cancellation import SuspendedCall


# --- the shapes ---------------------------------------------------------------


class Verdict(BaseModel):
    """The reply the suite asks for. This docstring is text the schema never carries."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(description="What the answer is.")
    confidence: int = Field(description="How sure, from 1 to 5.", examples=[3])


#: A reply that validates as :class:`Verdict`, and the value it validates as.
VALID_REPLY = '{"answer": "yes", "confidence": 4}'
VALID_VALUE = Verdict(answer="yes", confidence=4)


class Seen(BaseModel):
    """What a suspended subject's model saw: the content of each turn, in order."""

    seen: list[str]


class _Mapping(BaseModel):
    scores: dict[str, int]


class _FurtherKeys(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, int]
    name: str


class _OpenValue(BaseModel):
    payload: JsonValue


class _AnyValue(BaseModel):
    anything: Any


class _InnerOpen(BaseModel):
    anything: Any = None


class _NestedOpenValue(BaseModel):
    inner: _InnerOpen


class _ConstrainedOpenValue(BaseModel):
    payload: Any = Field(min_length=1)


class _MappingInJson(BaseModel):
    payload: Json[dict[str, int]]


#: The shapes §2:3 refuses before any model is contacted.
UNCLOSABLE_SHAPES = [
    pytest.param(_Mapping, id="mapping"),
    pytest.param(_FurtherKeys, id="schema-for-further-keys"),
    pytest.param(_OpenValue, id="open-json-value"),
    pytest.param(_AnyValue, id="any"),
    pytest.param(_NestedOpenValue, id="nested-open-value"),
    pytest.param(_ConstrainedOpenValue, id="constrained-open-value"),
    pytest.param(_MappingInJson, id="mapping-inside-a-json-string"),
    pytest.param(dict, id="not-a-model"),
]


# --- the script ---------------------------------------------------------------


#: How a scripted response ends: normally, at its output ceiling, or refused.
type Ending = Literal["stop", "length", "refused"]

#: The usage every scripted response reports, each count distinct so a swapped field
#: shows.
SCRIPTED_USAGE = ReplyUsage(
    input_tokens=17, output_tokens=7, cache_read_tokens=5, cache_write_tokens=3
)

#: The statement and category a scripted refusal carries.
REFUSAL = "I can't help with that request."
REFUSAL_CATEGORY = "cyber"


@dataclass(frozen=True)
class Answer:
    """One scripted response, in terms every binding can script.

    Attributes:
        reply: The text the model writes.
        ending: How the response ends.
        refusal: The provider's statement, for a refused response.
        usage: The tokens the response reports.
    """

    reply: str
    ending: Ending = "stop"
    refusal: str | None = None
    usage: ReplyUsage = field(default=SCRIPTED_USAGE)


#: The finish reason each ending is recorded as, in pydantic-ai's vocabulary (§5:3).
FINISH_REASONS: dict[Ending, str] = {
    "stop": "stop",
    "length": "length",
    "refused": "content_filter",
}


class StructuredWorld(Protocol):
    """A subject scripted with one answer, and what reached the model under it."""

    @property
    def completer(self) -> StructuredCompleter:
        """The subject under test."""
        ...

    @property
    def attempts(self) -> int:
        """How many requests reached the model underneath."""
        ...

    @property
    def answered_by(self) -> str:
        """The ``"provider:model"`` the exchange should say answered."""
        ...

    @property
    def mode(self) -> ReplyMode:
        """The mode the subject sends this world's requests in."""
        ...


#: Every response kind, for the cases that must hold whatever came back.
EVERY_KIND = [
    pytest.param(Answer(VALID_REPLY), None, id="value"),
    pytest.param(Answer("", ending="refused", refusal=REFUSAL), ReplyFailure.REFUSED, id="refused"),
    pytest.param(Answer('{"answer": "ye', ending="length"), ReplyFailure.CUT, id="cut"),
    pytest.param(Answer("  \n "), ReplyFailure.EMPTY, id="empty"),
    pytest.param(Answer(f"Here it is: {VALID_REPLY}"), ReplyFailure.INVALID, id="prose"),
]

#: Responses to which more than one of §5:2's kinds applies, and the first in order.
ORDERED = [
    pytest.param(
        Answer(VALID_REPLY, ending="refused", refusal=REFUSAL),
        ReplyFailure.REFUSED,
        id="refused-over-a-valid-reply",
    ),
    pytest.param(
        Answer("", ending="refused", refusal=REFUSAL), ReplyFailure.REFUSED, id="refused-over-empty"
    ),
    pytest.param(
        Answer("I won't {", ending="refused", refusal=REFUSAL),
        ReplyFailure.REFUSED,
        id="refused-over-invalid",
    ),
    pytest.param(
        Answer(VALID_REPLY, ending="length"), ReplyFailure.CUT, id="cut-over-a-valid-reply"
    ),
    pytest.param(Answer("", ending="length"), ReplyFailure.CUT, id="cut-over-empty"),
    pytest.param(
        Answer('{"answer": "ye', ending="length"), ReplyFailure.CUT, id="cut-over-invalid"
    ),
    pytest.param(Answer("```json\n\n```"), ReplyFailure.EMPTY, id="empty-once-unfenced"),
]

#: Replies that do not validate as :class:`Verdict`.
INVALID_REPLIES = [
    pytest.param(f"Here it is: {VALID_REPLY}", id="prose-before-the-object"),
    pytest.param(f"{VALID_REPLY}\nThat's my answer.", id="prose-after-the-object"),
    pytest.param('{"answer": "yes", "confidence": 4, "why": "x"}', id="a-stray-key"),
    pytest.param('{"answer": "yes"}', id="a-missing-field"),
    pytest.param('{"answer": "yes", "confidence": "high"}', id="a-wrong-type"),
    pytest.param("[1, 2]", id="not-an-object"),
]

#: The shapes ADR-0066 §1's precondition refuses, as role sequences.
_REFUSED_HISTORIES = [
    pytest.param([], id="empty"),
    pytest.param([Role.USER, Role.ASSISTANT], id="ends-on-assistant"),
    pytest.param([Role.ASSISTANT], id="lone-assistant"),
]


def request() -> list[Message]:
    """A conversation awaiting a structured reply."""
    return [
        Message(role=Role.SYSTEM, content="Answer the question."),
        Message(role=Role.USER, content="Is the sky blue?"),
    ]


def _history(roles: Sequence[Role]) -> list[Message]:
    return [Message(role=role, content=f"{role.value} turn") for role in roles]


def seen_reply(contents: Sequence[str]) -> str:
    """The reply a suspended subject's model writes for what it saw."""
    return json.dumps({"seen": list(contents)})


def scripted_reply(answer: Answer) -> ScriptedReply:
    """``answer`` as the canonical fake scripts it, for a binding over the fake."""
    failure: Literal[ReplyFailure.REFUSED, ReplyFailure.CUT] | None
    match answer.ending:
        case "refused":
            failure = ReplyFailure.REFUSED
        case "length":
            failure = ReplyFailure.CUT
        case "stop":
            failure = None
    return ScriptedReply(
        text=answer.reply, failure=failure, refusal=answer.refusal, usage=answer.usage
    )


# --- input observation (ADR-0065, as ADR-0069 enforces it) ----------------------


#: The conversation turn identity the log records: role, content and name.
type Turn = tuple[Role, str, str | None]


def fingerprint(messages: Sequence[Message]) -> tuple[Turn, ...]:
    """The full identity of every turn in ``messages``."""
    return tuple((m.role, m.content, m.name) for m in messages)


class SuspendingStructuredRecorder:
    """A suite-owned inner a wrapper suspends inside and observes through.

    The structured sibling of ``model_provider_contract.SuspendingRecorder``: it
    records the conversation each attempt hands it, and answers with
    :func:`seen_reply` of that one observation, read as the shape. Its first call
    suspends at its own first ``await`` behind a gate, and ``fail_times`` calls fail
    first with a retryable, routable ``ModelUnavailableError``, so a retry loop takes a
    second attempt and a router falls through to its next route: the windows where a
    wrapper could re-read the caller's ``Sequence`` after a suspension.

    It implements ``ModelProvider`` too, as a wrapper's inner must.
    """

    def __init__(
        self, log: ConversationLog, *, gate: FirstAwaitGate | None = None, fail_times: int = 0
    ) -> None:
        """Record into ``log``; suspend the first call on ``gate``; fail ``fail_times``."""
        self._log = log
        self._gate = gate
        self._fail_times = fail_times
        self._calls = 0

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Not part of the case: a wrapper's structured call never reaches it."""
        raise AssertionError

    async def complete_structured[T: BaseModel](
        self, messages: Sequence[Message], shape: type[T], *, model: str | None = None
    ) -> StructuredReply[T]:
        """Record the conversation observed, then suspend, fail or answer as configured."""
        self._calls += 1
        observed = fingerprint(messages)
        self._log.record(observed)
        if self._gate is not None and self._calls == 1:
            await self._gate.hold()
        if self._calls <= self._fail_times:
            raise ModelUnavailableError("503")
        answer = seen_reply([content for _role, content, _name in observed])
        return await FakeStructuredCompleter(answer).complete_structured(messages, shape)


def _append_a_turn(conversation: list[Message]) -> None:
    conversation.append(Message(role=Role.USER, content="wait, actually"))


def _replace_the_turn(conversation: list[Message]) -> None:
    conversation[0] = Message(role=Role.SYSTEM, content="hi")


#: Both container mutations ADR-0069 §3 names.
_MUTATIONS = [
    pytest.param(_append_a_turn, id="appended-turn"),
    pytest.param(_replace_the_turn, id="replaced-turn"),
]

#: What a failure of the input-observation case means.
_TORN_INPUT = (
    "the structured call derived its outcome from more than one observation of its "
    "conversation: a caller's mid-flight mutation reached one attempt (or the value) "
    "and not another"
)


class StructuredCompleterContract:
    """Obligations every ``StructuredCompleter`` implementation must meet."""

    @pytest.fixture
    def completer(self) -> StructuredCompleter:
        """Override: the subject, unscripted."""
        raise NotImplementedError

    def world(self, answer: Answer) -> AbstractAsyncContextManager[StructuredWorld]:
        """Override: a subject scripted to answer with ``answer``, and its model."""
        raise NotImplementedError

    def reported_usage(self, usage: ReplyUsage) -> ReplyUsage:
        """The usage the exchange should carry for a response reporting ``usage``.

        Override where the provider underneath cannot state all of it: the exchange
        carries what the provider reported, and nothing it did not.
        """
        return usage

    # --- what is refused before any model is contacted (§2:3) ---------------

    async def test_satisfies_the_protocol(self, completer: StructuredCompleter) -> None:
        assert isinstance(completer, StructuredCompleter)
        async with self.world(Answer(VALID_REPLY)) as scripted:
            assert isinstance(scripted.completer, StructuredCompleter)

    @pytest.mark.parametrize("roles", _REFUSED_HISTORIES)
    async def test_a_malformed_history_is_refused_before_the_model(self, roles: list[Role]) -> None:
        async with self.world(Answer(VALID_REPLY)) as scripted:
            with pytest.raises(ModelError) as caught:
                await scripted.completer.complete_structured(_history(roles), Verdict)
            assert scripted.attempts == 0
        assert caught.value.retryable is False
        assert caught.value.routable is False

    async def test_a_tool_turn_is_refused_before_the_model(self) -> None:
        history = [*request(), Message(role=Role.TOOL, content="result", name="lookup")]
        history.append(Message(role=Role.USER, content="and?"))
        async with self.world(Answer(VALID_REPLY)) as scripted:
            with pytest.raises(ModelError) as caught:
                await scripted.completer.complete_structured(history, Verdict)
            assert scripted.attempts == 0
        assert caught.value.retryable is False
        assert caught.value.routable is False

    @pytest.mark.parametrize("shape", UNCLOSABLE_SHAPES)
    async def test_a_shape_that_cannot_be_closed_is_refused_before_the_model(
        self, shape: type[BaseModel]
    ) -> None:
        async with self.world(Answer(VALID_REPLY)) as scripted:
            with pytest.raises(ModelError) as caught:
                await scripted.completer.complete_structured(request(), shape)
            assert scripted.attempts == 0
        assert caught.value.retryable is False
        assert caught.value.routable is False

    async def test_a_history_ending_on_a_system_turn_is_answered(self) -> None:
        async with self.world(Answer(VALID_REPLY)) as scripted:
            reply = await scripted.completer.complete_structured(
                _history([Role.USER, Role.SYSTEM]), Verdict
            )
        assert reply.value == VALID_VALUE

    async def test_the_model_keyword_is_accepted(self) -> None:
        async with self.world(Answer(VALID_REPLY)) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict, model=None)
        assert reply.value == VALID_VALUE

    # --- what comes back (§5) ----------------------------------------------

    async def test_a_reply_that_validates_is_returned_as_the_value(self) -> None:
        async with self.world(Answer(VALID_REPLY)) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
        assert reply.value == VALID_VALUE
        assert isinstance(reply.value, Verdict)
        assert reply.failure is None
        assert reply.exchange.reply == VALID_REPLY

    async def test_one_fence_enclosing_the_reply_is_removed_before_it_is_read(self) -> None:
        fenced = f"```json\n{VALID_REPLY}\n```"
        async with self.world(Answer(fenced)) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
        assert reply.value == VALID_VALUE
        assert reply.exchange.reply == fenced

    @pytest.mark.parametrize("text", INVALID_REPLIES)
    async def test_a_reply_that_does_not_validate_is_returned_invalid(self, text: str) -> None:
        async with self.world(Answer(text)) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
        assert reply.failure is ReplyFailure.INVALID
        assert reply.value is None
        assert reply.exchange.reply == text

    @pytest.mark.parametrize(("answer", "failure"), EVERY_KIND)
    async def test_every_response_is_returned_and_none_is_raised(
        self, answer: Answer, failure: ReplyFailure | None
    ) -> None:
        async with self.world(answer) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
        assert reply.failure is failure
        assert (reply.value is None) is (failure is not None)
        assert reply.exchange.reply == answer.reply
        assert reply.exchange.finish_reason == FINISH_REASONS[answer.ending]

    @pytest.mark.parametrize(("answer", "failure"), ORDERED)
    async def test_the_first_failure_that_applies_is_the_one_returned(
        self, answer: Answer, failure: ReplyFailure
    ) -> None:
        async with self.world(answer) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
        assert reply.failure is failure
        assert reply.value is None

    async def test_a_refusal_is_returned_with_the_providers_statement(self) -> None:
        async with self.world(Answer("", ending="refused", refusal=REFUSAL)) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
        assert reply.failure is ReplyFailure.REFUSED
        assert reply.exchange.refusal == REFUSAL

    @pytest.mark.parametrize(("answer", "failure"), EVERY_KIND)
    async def test_one_call_is_one_request_whatever_comes_back(
        self, answer: Answer, failure: ReplyFailure | None
    ) -> None:
        """§4:1: no second request to repair, re-ask or validate, for any response.

        An invalid or empty reply is one pydantic-ai's ``Agent`` would have retried.
        """
        async with self.world(answer) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
            assert scripted.attempts == 1
        assert reply.failure is failure

    async def test_the_exchange_carries_the_usage_the_model_and_the_shape(self) -> None:
        async with self.world(Answer(VALID_REPLY)) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
            answered_by, mode = scripted.answered_by, scripted.mode
        exchange = reply.exchange
        assert exchange.usage == self.reported_usage(SCRIPTED_USAGE)
        assert exchange.model == answered_by
        assert exchange.mode is mode
        assert exchange.shape == "Verdict"
        assert exchange.shape_version == reply_shape_version(Verdict)

    async def test_a_failure_carries_the_exchange_too(self) -> None:
        async with self.world(Answer("not json")) as scripted:
            reply = await scripted.completer.complete_structured(request(), Verdict)
            answered_by = scripted.answered_by
        assert reply.failure is ReplyFailure.INVALID
        assert reply.exchange.usage == self.reported_usage(SCRIPTED_USAGE)
        assert reply.exchange.model == answered_by

    # --- input observation (§2:4; ADR-0065, ADR-0069) -----------------------

    #: Whether the subject performs no ``await`` between reading its conversation and
    #: answering. The case then reduces to the coherent post-call assertion, as
    #: ``ModelProviderContract``'s does (ADR-0069 §3). Left ``False``, a binding opens
    #: the window by overriding :meth:`completer_suspended_at_its_first_await`.
    completes_without_suspending: bool = False

    def completer_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[StructuredCompleter, SuspendedCall, ConversationLog]]:
        """Supply a subject whose next call stops at **its own first ``await``**.

        Override unless :attr:`completes_without_suspending` is set. The context
        manager yields the subject, the gate holding its next call there, and a log of
        the conversation each request observed. Whatever answers writes
        :func:`seen_reply` of the one observation it took, so the value names the
        version it rests on. A wrapper wires :class:`SuspendingStructuredRecorder` in
        through :meth:`_suspended_through_a_recording_inner`.
        """
        raise NotImplementedError

    @contextlib.asynccontextmanager
    async def _suspended_through_a_recording_inner(
        self,
        wrap: Callable[
            [SuspendingStructuredRecorder, SuspendingStructuredRecorder], StructuredCompleter
        ],
    ) -> AsyncIterator[tuple[StructuredCompleter, SuspendedCall, ConversationLog]]:
        """A wrapper over a primary that suspends and fails once, and a secondary."""
        log = ConversationLog()
        gate = FirstAwaitGate()
        primary = SuspendingStructuredRecorder(log, gate=gate, fail_times=1)
        secondary = SuspendingStructuredRecorder(log)
        yield wrap(primary, secondary), gate, log

    @pytest.mark.parametrize("mutate", _MUTATIONS)
    async def test_the_value_rests_on_one_observation_of_the_conversation(
        self, completer: StructuredCompleter, mutate: Callable[[list[Message]], None]
    ) -> None:
        if self.completes_without_suspending:
            conversation = [Message(role=Role.USER, content="hi")]
            async with self.world(Answer(seen_reply(["hi"]))) as scripted:
                reply = await scripted.completer.complete_structured(conversation, Seen)
            mutate(conversation)
            assert reply.value == Seen(seen=["hi"])
            return

        async with self.completer_suspended_at_its_first_await() as (subject, gate, log):
            conversation = [Message(role=Role.USER, content="hi")]
            task = asyncio.ensure_future(subject.complete_structured(conversation, Seen))
            try:
                await gate.reached()
                assert not task.done(), "the call finished before it could be mutated"
                mutate(conversation)
            finally:
                gate.release()
            reply = await task

        assert log.observed, "the subject's model was never reached"
        assert log.observed[0] == ((Role.USER, "hi", None),)
        assert len(set(log.observed)) == 1, _TORN_INPUT
        assert reply.value == Seen(seen=["hi"]), _TORN_INPUT

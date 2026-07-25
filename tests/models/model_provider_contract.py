"""Shared conformance suite for the ModelProvider Protocol.

Every ``ModelProvider`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`ModelProviderContract` and overrides the ``provider`` fixture; the suite
asserts only behaviour that is *universal* to the contract — that a completion
comes back as an assistant :class:`~ai_assistant.core.types.Message`, and which
conversations ``complete()`` will answer at all (ADR-0066) — not what any one
model actually says, which stays in the per-implementation test modules.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ModelError, ModelUnavailableError
from ai_assistant.core.protocols import ModelProvider
from ai_assistant.core.types import Message, Role

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
    from contextlib import AbstractAsyncContextManager
    from typing import Any

    from ai_assistant.testing.cancellation import SuspendedCall

#: The shapes ADR-0066 §1's precondition refuses, as role sequences.
#:
#: The lone assistant turn is not a redundant copy of the two-message case: a
#: plausible ``len(messages) > 1 and messages[-1].role is Role.ASSISTANT`` guard
#: passes the two-message case and leaves this one live, and ADR-0066's Context
#: verified it echoes on its own.
_REFUSED_SHAPES = [
    pytest.param([], id="empty"),
    pytest.param([Role.USER, Role.ASSISTANT], id="ends-on-assistant"),
    pytest.param([Role.ASSISTANT], id="lone-assistant"),
]


def _history(roles: list[Role]) -> list[Message]:
    """Build a conversation of ``roles``, one message per role, in order."""
    return [Message(role=role, content=f"{role.name.lower()} turn") for role in roles]


def _conversation() -> list[Message]:
    """A multi-turn history of the system/user/assistant roles.

    Tool-role handling is intentionally excluded: the Protocol does not mandate
    it and support is implementation-specific (``PydanticAIProvider`` cannot yet
    represent a tool exchange), so it is asserted per implementation, not here.
    """
    return [
        Message(role=Role.SYSTEM, content="be terse"),
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content="hello"),
        Message(role=Role.USER, content="how are you?"),
    ]


#: What a failure of the input-observation case below means, in one place
#: (ADR-0065/ADR-0069): ``complete`` derived its outcome from more than one
#: observation of the caller's conversation, so the reply and the attempts do
#: not all describe a single version of the input.
_TORN_INPUT = (
    "the completion derived its outcome from more than one observation of its "
    "conversation: a caller's mid-flight mutation reached one attempt (or the "
    "reply) and not another, so no single version of the input describes the "
    "result"
)

#: A ``_WAIT_SECONDS``-style ceiling on how long the case waits for the subject
#: to reach its first await before declaring the scenario hung.
_REACHED_TIMEOUT = 5.0


def encode_conversation(contents: tuple[str, ...]) -> str:
    """Encode one observed conversation as a reply that names the version it saw.

    The collaborators below answer with this, so the single ``Message`` a
    completion returns *carries* the version of the conversation the answering
    attempt observed — otherwise a reply is opaque about which observation it
    rests on, and the case cannot assert the clause on it. Plain strings, joined:
    a recorded ``Message`` would be re-read at assertion time, hiding a tear.
    """
    return "|".join(contents)


class FirstAwaitGate:
    """A :class:`~ai_assistant.testing.cancellation.SuspendedCall` over a call held
    at its first ``await``.

    The input-observation analogue of the cancellation suites' suspension
    mechanisms, and deliberately the same two-lever shape ``SuspendedCall``
    documents: the collaborator a subject suspends on calls :meth:`hold` at the
    method's first suspension point; the case awaits :meth:`reached`, mutates the
    caller's conversation, then :meth:`release`\\ s it. Positioned there and not at
    method entry (ADR-0065 §3): a hook at entry would let the mutation land before
    the subject had taken its one observation, so a conforming subject would see a
    single coherent mutated version and a tear at the real window would survive.
    """

    def __init__(self) -> None:
        """Create an unreached, unreleased gate."""
        self._reached = asyncio.Event()
        self._released = asyncio.Event()

    async def hold(self) -> None:
        """Announce arrival at the first await and suspend until released."""
        self._reached.set()
        await self._released.wait()

    async def reached(self) -> None:
        """Wait until the suspended call has arrived at its first await."""
        async with asyncio.timeout(_REACHED_TIMEOUT):
            await self._reached.wait()

    def release(self) -> None:
        """Let the suspended call finish (idempotent)."""
        self._released.set()


class ConversationLog:
    """What conversation each collaborator invocation was handed, as content tuples.

    Recorded as plain strings at the instant the collaborator is handed the
    conversation, never as ``Message`` objects: a recorded object would be re-read
    at assertion time and show the *final* state of a list mutated mid-flight,
    hiding the very tear the case exists to catch. Read once, after the scenario
    is over.
    """

    def __init__(self) -> None:
        """Create an empty log."""
        self.observed: list[tuple[str, ...]] = []

    def record(self, contents: Sequence[str]) -> None:
        """Record one invocation's observed conversation."""
        self.observed.append(tuple(contents))


class SuspendingRecorder:
    """A suite-owned ``ModelProvider`` a wrapper suspends inside and observes through.

    The collaborator the injected-inner-provider hook wires into a wrapper
    (ADR-0069 §3): it records the conversation each attempt hands it, answers with
    :func:`encode_conversation` of that one observation, and — for its first call —
    suspends at its own first ``await`` behind a :class:`FirstAwaitGate`, so the
    wrapping ``complete`` is itself suspended while the case mutates the caller's
    list. ``fail_times`` failures come first (a routable, retryable
    ``ModelUnavailableError``) so a retry loop takes a second attempt and a router
    falls through to the next route — the windows where a wrapper re-reads the
    caller's ``Sequence`` after a suspension.
    """

    def __init__(
        self,
        log: ConversationLog,
        *,
        gate: FirstAwaitGate | None = None,
        fail_times: int = 0,
    ) -> None:
        """Record into ``log``; suspend the first call on ``gate``; fail ``fail_times``."""
        self._log = log
        self._gate = gate
        self._fail_times = fail_times
        self._calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Record the conversation observed, then suspend/fail/answer as configured."""
        self._calls += 1
        observed = tuple(m.content for m in messages)
        self._log.record(observed)
        if self._gate is not None and self._calls == 1:
            await self._gate.hold()
        if self._calls <= self._fail_times:
            raise ModelUnavailableError("503")
        return Message(role=Role.ASSISTANT, content=encode_conversation(observed))


async def _no_sleep(_delay: float) -> None:
    """Stand in for a wrapper's backoff, so the case never waits in real time."""


@contextlib.asynccontextmanager
async def _held_at_its_first_await(
    gate: SuspendedCall | None, call: Coroutine[Any, Any, Message]
) -> AsyncIterator[asyncio.Task[Message]]:
    """Run ``call`` and hold it at its first ``await`` for the body of the block.

    The body is where the case mutates the caller's conversation; leaving the
    block releases the call. ``gate`` of ``None`` is the reduction for a subject
    that declares no suspension window (ADR-0069 §3): the call is run to
    completion first, so the body's mutation is a post-call one — the right
    weakening, because a completion with no window has none to tear in.
    """
    task = asyncio.ensure_future(call)
    try:
        if gate is None:
            await asyncio.wait([task])
        else:
            await gate.reached()
        yield task
    finally:
        if gate is not None:
            gate.release()


class ModelProviderContract:
    """The behavioural contract every ``ModelProvider`` implementation must satisfy."""

    @pytest.fixture
    def provider(self) -> ModelProvider:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def test_conforms_to_protocol(self, provider: ModelProvider) -> None:
        assert isinstance(provider, ModelProvider)

    async def test_complete_returns_an_assistant_message(self, provider: ModelProvider) -> None:
        reply = await provider.complete([Message(role=Role.USER, content="hello")])

        assert isinstance(reply, Message)
        assert reply.role is Role.ASSISTANT
        assert isinstance(reply.content, str)

    async def test_complete_handles_a_multi_turn_conversation(
        self, provider: ModelProvider
    ) -> None:
        # The provider must accept a full system/user/assistant history, not just
        # a single user turn.
        reply = await provider.complete(_conversation())

        assert reply.role is Role.ASSISTANT
        assert isinstance(reply.content, str)

    async def test_complete_accepts_the_model_keyword(self, provider: ModelProvider) -> None:
        # The ``model`` override is part of the contract's surface; passing it
        # explicitly (here as ``None``, the "use the default" value) must be
        # accepted without resolving a real model. That an override is actually
        # *honoured* can only be checked offline per implementation (a real
        # ``"provider:model"`` string would force network resolution), so those
        # assertions live in the per-implementation test modules.
        reply = await provider.complete([Message(role=Role.USER, content="hi")], model=None)

        assert reply.role is Role.ASSISTANT

    # ADR-0066 §1: ``complete()`` takes a conversation *awaiting an assistant
    # reply*. The two cases below pin both sides of that boundary — every shape
    # the rule refuses is refused, and the shape it admits is admitted. The
    # boundary is emptiness and the terminal turn, and only those: ``Role.TOOL``
    # is refused by both implementations for reasons prior to this ADR and
    # unchanged by it, so it stays out of the shared suite (§6).

    @pytest.mark.parametrize("roles", _REFUSED_SHAPES)
    async def test_complete_refuses_a_conversation_awaiting_nothing(
        self, provider: ModelProvider, roles: list[Role]
    ) -> None:
        # Asserted by the *raise*, deliberately, and never by an absent request:
        # "nothing went on the wire" is equally true of the defect this rule
        # exists to close (the echo made no request either), so a recorder-based
        # case here would certify the bug rather than the fix (ADR-0066 §6).
        with pytest.raises(ModelError) as caught:
            await provider.complete(_history(roles))

        # The *disposition*, not the class. ``pytest.raises(ModelError)`` alone is
        # satisfied by ModelUnavailableError, which is retryable and routable — so
        # an implementation could pass this case while RetryingProvider burned its
        # whole attempt budget and RoutingProvider walked a malformed conversation
        # down every fallback route. Identity is not asserted either: that would
        # forbid a future implementation from raising a well-behaved subclass, and
        # the flag pair was always the property (ADR-0066 §6).
        assert caught.value.retryable is False
        assert caught.value.routable is False

    async def test_complete_accepts_a_history_ending_on_a_system_turn(
        self, provider: ModelProvider
    ) -> None:
        # The other side of the boundary, and the reason it is worth a case: the
        # rule is "does not end on an assistant turn", *not* "ends on a user
        # turn". Every other positive case in this suite ends on a user turn, so
        # an implementation that wrote the over-broad ``if messages[-1].role is
        # not Role.USER: raise`` would satisfy the refusals and the conversation
        # cases alike while rejecting a call that works today — verified against
        # both real vendor stacks, which issue a request for this history
        # (ADR-0066 §1).
        reply = await provider.complete(_history([Role.USER, Role.SYSTEM]))

        assert reply.role is Role.ASSISTANT
        assert isinstance(reply.content, str)

    # --- input observation (ADR-0065, enforced here by ADR-0069) -------------

    #: Whether this implementation performs no ``await`` between reading its
    #: conversation and answering — no suspension window for a caller's mutation
    #: to land in. ``core.protocols``' input clause is then discharged by "do not
    #: suspend" and the case below reduces to the coherent post-call assertion,
    #: correctly: a completion with no window has none to tear in (ADR-0069 §3).
    #: ``FakeModelProvider`` takes this escape — its ``complete`` has no such
    #: await. Left ``False``, the suite requires the implementation to open that
    #: window by overriding :meth:`provider_suspended_at_its_first_await` — so a
    #: fourth provider that re-reads the caller's ``Sequence`` after suspending
    #: fails here rather than passing a suite that never looked.
    completes_without_suspending: bool = False

    def provider_suspended_at_its_first_await(
        self,
    ) -> AbstractAsyncContextManager[tuple[ModelProvider, SuspendedCall, ConversationLog]]:
        """Supply a subject whose next ``complete`` stops at **its own first ``await``**.

        Override unless :attr:`completes_without_suspending` is set. The context
        manager yields the subject, the gate holding its next ``complete`` at that
        first ``await``, and a :class:`ConversationLog` recording the conversation
        each inner attempt (or the transport) observed. The case suspends the call
        there, mutates the caller's conversation, releases it, then asserts the
        reply and every recorded observation describe one version of the input.

        What the subject suspends *on* is implementation-specific and not owned by
        the suite (ADR-0069 §3): a **wrapper** suspends inside its **inner
        provider** — wire :class:`SuspendingRecorder` in through
        :meth:`_suspended_through_a_recording_inner` — and a **direct provider**
        suspends on its **transport**, which its own test module stands up. Either
        way the recorder/transport answers with :func:`encode_conversation` of the
        one observation it took, so the returned ``Message`` names the version it
        rests on.
        """
        raise NotImplementedError

    @contextlib.asynccontextmanager
    async def _suspended_through_a_recording_inner(
        self, wrap: Callable[[ModelProvider, ModelProvider], ModelProvider]
    ) -> AsyncIterator[tuple[ModelProvider, SuspendedCall, ConversationLog]]:
        """Build a wrapper subject over suite-owned inner providers that suspend and record.

        The general, injected-inner-provider form ADR-0069 §3 points wrappers to:
        the suite owns the collaborator, so ``wrap`` only has to compose the
        production wrapper around a ``primary`` that suspends at its first await
        and fails once — driving a retry to a second attempt, or a router to its
        second route — and a ``secondary`` that succeeds. Both record into one
        :class:`ConversationLog`, so the case sees every version any attempt was
        handed.
        """
        log = ConversationLog()
        gate = FirstAwaitGate()
        primary = SuspendingRecorder(log, gate=gate, fail_times=1)
        secondary = SuspendingRecorder(log)
        yield wrap(primary, secondary), gate, log

    async def test_complete_rests_its_reply_on_one_observation_of_the_conversation(
        self, provider: ModelProvider
    ) -> None:
        """``core.protocols``' input clause, on ``complete`` (ADR-0065, ADR-0069).

        The mutation vector is **container mutation of the caller's ``Sequence``**
        — appending a turn — because ADR-0068's deep-freeze of ``Message`` closed
        the element-rewrite vector: a turn's own fields can no longer change under
        an observation, so the case need not (and cannot) parametrise over a
        rewritten turn. With ``complete`` suspended at its first ``await``, the
        case grows the caller's list, then asserts the reply and every inner
        attempt describe one version — never a mix, which is the tear a wrapper
        that re-reads the caller's ``Sequence`` after a suspension would commit
        (#380/#384). Mid-flight, not post-call: a post-call assertion cannot tell a
        subject that snapshots from one that re-reads, the failure ADR-0065
        §"The suite already appears to cover this, and does not" documents.
        """
        if self.completes_without_suspending:
            # The reduction for a subject with no suspension window (ADR-0069 §3):
            # run it to completion, mutate the caller's list afterwards, and assert
            # the reply is a single coherent assistant message. A completion that
            # never suspended between reading its conversation and answering has no
            # window for the mutation to reach — so, exactly as for a store that
            # commits without suspending, there is nothing mid-flight left to tear.
            conversation = [Message(role=Role.USER, content="hi")]
            reply = await provider.complete(conversation)
            conversation.append(Message(role=Role.USER, content="wait, actually"))
            assert reply.role is Role.ASSISTANT
            assert isinstance(reply.content, str)
            return

        async with self.provider_suspended_at_its_first_await() as (subject, gate, log):
            conversation = [Message(role=Role.USER, content="hi")]
            async with _held_at_its_first_await(gate, subject.complete(conversation)) as call:
                # The subject is genuinely suspended in flight here — not yet done —
                # so the mutation lands *inside* `complete`, the only window the
                # clause is about, and not after it (the post-call assertion that
                # certified the MemoryStore bug, ADR-0065). Its collaborator has
                # already taken its first observation (asserted below), so this
                # exercises the re-read window after that observation.
                assert not call.done(), "complete finished before it could be mutated mid-flight"
                # Grow the caller's own list while `complete` is suspended.
                conversation.append(Message(role=Role.USER, content="wait, actually"))
            reply = await call

            assert log.observed, "the subject's collaborator was never reached"
            # What the case forbids is a *two-version* result (the assertions
            # below), which is ADR-0065's actual obligation: "everything one call
            # derives ... comes from one observation" and "must never make one
            # result describe two different versions". It does not additionally
            # require that the one observation be taken at entry — ADR-0065 lists
            # "do not read an argument again after suspending" as a discharge and
            # says the caller is owed a coherent result, "not that it reflects any
            # chosen version" — so a provider that took its single observation after
            # a benign suspension is conforming and passes here.
            # The first observation was taken before the mutation, so the case
            # tests the re-read window rather than the initial read — a subject
            # that read only at entry would already have "hi" here regardless.
            assert log.observed[0] == ("hi",)
            # One version across every attempt: a wrapper that re-read the caller's
            # list after suspending would have handed a later attempt the grown one.
            assert len(set(log.observed)) == 1, _TORN_INPUT
            # ...and the single reply rests on that same one observation.
            assert reply.content == encode_conversation(log.observed[-1]), _TORN_INPUT
            # The list really was mutated mid-flight, so the case is not vacuously
            # green on a mutation that never happened.
            assert [m.content for m in conversation] != ["hi"]

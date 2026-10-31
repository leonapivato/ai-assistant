"""A canonical :class:`~ai_assistant.core.protocols.ToolCallingCompleter` fake.

The shared test double for the ``ToolCallingCompleter`` contract (ADR-0307 §10), so
orchestration's planning stage can test a round against a real, contract-correct seam
*without importing the models subsystem's internals* (CLAUDE.md golden rule 1) and
without touching the network. It lives in ``ai_assistant.testing`` so it is importable
from any test while staying out of production code paths (``lint-imports`` forbids
production modules from importing it).

It never calls a model. The response is a constant
:class:`~ai_assistant.core.types.RoundResponse` or a callable over the exchange and the
offered tools, and every accepted call is recorded so a test can assert what planning
sent. It hands back no continuation of its own: a scripted response is returned as
scripted (ADR-0356 §6:1). For a scripted
sequence of rounds use :meth:`FakeToolCallingCompleter.scripted`. Only the behaviour
the shared conformance suite asserts is part of the contract; the recording and
scripting helpers are conveniences on top.
"""

from __future__ import annotations

from collections import deque

# At runtime, not under TYPE_CHECKING: `RoundReply` is a PEP 695 alias, whose value is
# read lazily and must resolve when it is (#1706).
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import OfferedTool, PlanningExchange, RoundResponse

#: What an unscripted fake answers: a round whose text is this and that proposes nothing.
DEFAULT_ROUND_TEXT: Final = "fake planning round"

#: A response computed from the round's request: its exchange and offered tools.
type RoundReply = Callable[[PlanningExchange, Sequence[OfferedTool]], RoundResponse]


class _ScriptExhaustedError(AssertionError):
    """A :meth:`FakeToolCallingCompleter.scripted` fake ran out of responses.

    An ``AssertionError``, so it reads as a test-authoring error, and a distinct type,
    so ``respond`` lets it through while wrapping every other reply failure in
    ``ModelError``.
    """


@dataclass(frozen=True)
class RoundCall:
    """One recorded call to a :class:`FakeToolCallingCompleter`.

    Attributes:
        exchange: The exchange passed to ``respond``. It is frozen all the way down, so
            what was passed is what was observed.
        tools: The tools offered, as an independent snapshot.
        model: The per-call ``"provider:model"`` override, or ``None``.
    """

    exchange: PlanningExchange
    tools: tuple[OfferedTool, ...]
    model: str | None


class FakeToolCallingCompleter:
    """A deterministic, offline ``ToolCallingCompleter`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ToolCallingCompleter`. Each accepted call is
    appended to :attr:`calls`, and its response is produced by ``response``.
    """

    def __init__(self, response: RoundResponse | RoundReply | None = None) -> None:
        """Create a fake answering with ``response``.

        Args:
            response: A constant response for every call, or a callable given the
                exchange and the offered tools that returns one. Defaults to a
                round writing :data:`DEFAULT_ROUND_TEXT` and proposing nothing.
        """
        self._response = RoundResponse(text=DEFAULT_ROUND_TEXT) if response is None else response
        self.calls: list[RoundCall] = []

    @classmethod
    def scripted(cls, *responses: RoundResponse) -> FakeToolCallingCompleter:
        """A fake that returns each of ``responses`` in turn, then raises.

        Calling ``respond`` more times than there are responses is a test-authoring
        error and raises :class:`AssertionError`.

        Args:
            responses: The rounds to return, in call order.

        Returns:
            The scripted fake.
        """
        queue: deque[RoundResponse] = deque(responses)

        def next_response(
            _exchange: PlanningExchange, _tools: Sequence[OfferedTool]
        ) -> RoundResponse:
            if not queue:
                msg = "FakeToolCallingCompleter.scripted ran out of responses"
                raise _ScriptExhaustedError(msg)
            return queue.popleft()

        return cls(response=next_response)

    async def respond(
        self,
        exchange: PlanningExchange,
        tools: Sequence[OfferedTool],
        *,
        model: str | None = None,
    ) -> RoundResponse:
        """Record the call and return the configured response.

        Every refusal happens **before** the call is recorded and before ``response``
        is evaluated, so a refused call is inert: it records nothing and does not
        advance a :meth:`scripted` queue (ADR-0066 §6).

        Args:
            exchange: The work's exchange, oldest first.
            tools: The capabilities offered for this round.
            model: Optional ``"provider:model"`` override; recorded and otherwise
                ignored.

        Returns:
            The configured response, detached from the fake's own copy.

        Raises:
            ModelError: If two tools share a name, or if a callable ``response`` fails —
                each matching the provider-backed implementation's boundary. No tool
                name is reserved (ADR-0356 §7:4).
            AssertionError: If a :meth:`scripted` fake runs out of responses.
        """
        offered = tuple(OfferedTool.model_validate(tool.model_dump()) for tool in tools)
        _refuse_malformed(offered)
        self.calls.append(RoundCall(exchange=exchange, tools=offered, model=model))
        response = self._response
        if callable(response):
            try:
                answer = response(exchange, offered)
            except _ScriptExhaustedError:
                raise
            except Exception as exc:
                msg = f"model response failed: {exc}"
                raise ModelError(msg) from exc
        else:
            answer = response
        return RoundResponse.model_validate(answer.model_dump())

    @property
    def call_count(self) -> int:
        """How many calls ``respond`` has accepted."""
        return len(self.calls)

    @property
    def last_call(self) -> RoundCall:
        """The most recent accepted call.

        Raises:
            IndexError: If ``respond`` has accepted no call yet.
        """
        return self.calls[-1]


def _refuse_malformed(tools: tuple[OfferedTool, ...]) -> None:
    """Distinct tool names, the one shape a round's request is refused for.

    Raises:
        ModelError: The bare class, neither retryable nor routable.
    """
    names = [tool.name for tool in tools]
    if len(set(names)) != len(names):
        msg = "respond() requires distinct tool names"
        raise ModelError(msg)

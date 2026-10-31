"""The follow-up question: its prompt, and the seam that asks it of a planning round (ADR-0337 §6).

The **follow-up** is a second request about a model call that has completed: the
followed call's request as it was sent, its system message and its offered tools
included, then the followed call's response, then this prompt's template rendered as
one user message (§6:3). It asks after the answer, so it cannot change the answer.

**The prompt.** The template ships beside the module in ``models/`` that sends it on the
hub (§6:1), which is this one: the hub-side asker of ADR-0337 §8:5 is to live here.

**A planning round's follow-up** goes through :func:`follow_up_round`, the follow-up's
sibling of the completer's seam for the owner's replay tool (ADR-0335 §4:8), which
ADR-0337 §7:3 sends it through. Its request is the round's own whole exchange, built
exactly as :class:`~ai_assistant.models.tool_calling.PydanticAIToolCallingCompleter`
builds a round with the record on, summarised thinking included, so the offered tools
stay in it (ADR-0356 §13); then the followed response whole, its thinking and the
thinking's signatures included, so that the provider accepts the request (§6:6); then
one request closing each call the response proposed with a result saying it was not run
because the request is for review only (§6:4), and holding the question last. Under a
candidate's instruction, earlier responses go back without their continuations
(ADR-0356 §13). It is
sent once to the one model it is named, which may not fall back to another, and it
returns the answer as text (§6:5): no call the answer proposes is run or returned. It
writes no entry, binds no activation and is on no Protocol, and no stage calls it
(ADR-0335 §4:9).

**A completion's follow-up needs no seam**: the provider's ``complete`` takes the
request, the reply as an assistant turn and the question as the last user turn.

**On the owner's hub, the asker** (ADR-0337 §8). :class:`FollowUpAsker` is a
:class:`~ai_assistant.core.protocols.DiagnosticSink` the composition root wraps, where
``Settings.follow_up_question`` is true, around the sink it hands every emitter (§8:5).
It passes each entry on unchanged, and reads it only as it is handed it, never from a
file of the record (§8:6). From what it is handed it pairs a recorded call's given entry
with the returned entry its source writes for the same call, and asks nothing about a
call it cannot pair unambiguously (§8:5). A recorded call is one whose given entry
carries ``prompt`` and whose returned entry holds the model's response rather than a
failure alone (§8:4). Each is asked the follow-up as the daily budget admits (§8:3), off
the activation's path and one at a time (§8:7), of the model that answered it where its
returned entry names one and otherwise of the first model of its stage's route, with no
fallback and no retry (§8:8, §8:15). The answer, or the failure, is written through the
sink it wraps as one ``follow_up`` returned entry under each activation the call was
written under (§8:9-§8:11), and the store puts it in the activation's follow-up file
(§8:12). Nothing else reads it (§8:14), and a follow-up not sent when the hub stops is
not sent (§8:16).
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, override

import structlog
from pydantic import ValidationError
from pydantic_ai.direct import model_request
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import infer_model
from pydantic_ai.models.wrapper import WrapperModel

from ai_assistant.core.diagnostics import DIAGNOSTIC_NOT_WRITTEN, failure_body
from ai_assistant.core.errors import ModelError
from ai_assistant.core.prompts import PromptDeclaration
from ai_assistant.core.types import (
    DiagnosticEntry,
    DiagnosticKind,
    DiagnosticSource,
    Message,
    OfferedTool,
    PlanningExchange,
    Role,
    fault_class_of,
)
from ai_assistant.models.provider import PydanticAIProvider, _classify
from ai_assistant.models.tool_calling import (
    DEFAULT_THINKING,
    _falls_back,
    _round_parameters,
    _settings,
    candidate_exchange,
    exchange_history,
    model_id,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from pydantic_ai import RunContext, models
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import ModelRequestParameters, StreamedResponse
    from pydantic_ai.settings import ModelSettings, ThinkingLevel

    from ai_assistant.core.prompts import PromptTemplate
    from ai_assistant.core.protocols import DiagnosticSink

_log = structlog.get_logger(__name__)


#: The follow-up's prompt (ADR-0337 §6:1), the ninth: it declares no flag and no value.
#:
#: **What the instruction must say**, which binds the default and every override alike
#: (ADR-0334 §7:1), and which a promotion's review reads it against (§7:3): that it asks
#: what the model had to guess, what it needed and was not given, and which rules or
#: instructions pulled against each other, and asks it to name for each the passage of
#: the instruction or of the data that it is about (ADR-0337 §6:2).
FOLLOW_UP_PROMPT: Final = PromptDeclaration(name="follow_up", package="ai_assistant.models")

#: The result closing each call a followed response proposed (ADR-0337 §6:4).
NOT_RUN: Final = "Not run: this request is for review only."


async def follow_up_round(  # noqa: PLR0913 — the round's exchange, its response and the question; keyword-only, the model, the thinking and a candidate's instruction
    exchange: PlanningExchange,
    tools: Sequence[OfferedTool],
    response: Mapping[str, object],
    question: str,
    *,
    model: models.Model | str,
    thinking: ThinkingLevel = DEFAULT_THINKING,
    instruction: str | None = None,
) -> str:
    """Ask the follow-up of a planning round that has completed (ADR-0337 §6:3-§6:6).

    Args:
        exchange: The followed round's exchange as it was sent, oldest first.
        tools: The capabilities it offered, as planning's given entry records them.
        response: The followed round's whole response, as pydantic-ai serialises it to
            JSON: the form planning's returned entry keeps it in.
        question: The ``follow_up`` template, rendered.
        model: The one model the follow-up goes to, which may not be a fallback model,
            wrapped or not.
        thinking: The thinking the request asks for, as the completer's own.
        instruction: A candidate's instruction, sent in place of the exchange's own;
            where it differs, earlier responses go back without their continuations.

    Returns:
        The answer's text, its text parts joined; empty where it wrote none.

    Raises:
        ModelError: The bare class, before any model is contacted, where the round's
            tools would be refused, ``instruction`` is blank, ``response`` is not one
            model response, the question is blank, or ``model`` is a fallback model. A
            failure sending the request is narrowed as a round's is.
    """
    parameters = _round_parameters(tools, caller="follow_up_round()")
    sent = candidate_exchange(exchange, instruction, caller="follow_up_round()")
    followed = _followed(response)
    if not question.strip():
        msg = "a follow-up asks a question"
        raise ModelError(msg)
    closing: list[ToolReturnPart | UserPromptPart] = [
        ToolReturnPart(tool_name=part.tool_name, content=NOT_RUN, tool_call_id=part.tool_call_id)
        for part in followed.parts
        if isinstance(part, ToolCallPart)
    ]
    closing.append(UserPromptPart(content=question))
    try:
        chosen = infer_model(model)
    except Exception as exc:
        # As a round's: resolving a string model may fail, and is classified.
        raise _classify(exc) from exc
    # The follow-up's request ends on its question, so no report of it is the newest.
    history = [
        *exchange_history(sent, model_id(chosen), cache_point=False),
        followed,
        ModelRequest(parts=closing),
    ]
    if _falls_back(chosen):
        msg = "a follow-up goes to the one model it names, which a fallback model may not be"
        raise ModelError(msg)
    try:
        settings = _settings(thinking, chosen, summarised=True)
        answer = await model_request(
            chosen, history, model_settings=settings, model_request_parameters=parameters
        )
    except Exception as exc:
        # Broad on purpose, as a round's: `_classify` is the taxonomy (ADR-0063).
        raise _classify(exc) from exc
    return answer.text or ""


def _followed(response: Mapping[str, object]) -> ModelResponse:
    """The followed response, rebuilt whole from its JSON.

    Raises:
        ModelError: The bare class, if it is not one model response.
    """
    try:
        rebuilt = ModelMessagesTypeAdapter.validate_python([dict(response)])
    except ValidationError, TypeError, ValueError:
        rebuilt = []
    if len(rebuilt) != 1 or not isinstance(rebuilt[0], ModelResponse):
        msg = "the followed response is not one model response"
        raise ModelError(msg)
    return rebuilt[0]


# --- the asker on the owner's hub (ADR-0337 §8) -------------------------------------

#: The routes a follow-up goes to, one for each kind of recorded call (§8:8): each
#: stage's own, and each of the observer's steps apart (ADR-0329 §9:9): the scout's, and
#: framing's and placement's, which ADR-0346 §10:1 cuts the commit step into. The
#: composition root names each one's model, framing's and placement's the commit route
#: both ride (§10:2).
FOLLOW_UP_ROUTES: Final = frozenset(
    {
        "understanding",
        "planning",
        "digesting",
        "observer.scout",
        "observer.framing",
        "observer.placement",
    }
)

#: The event a recorded call the asker did not ask about is logged under: by activation,
#: source and reason alone, never anything an entry holds (§8:14).
FOLLOW_UP_NOT_ASKED: Final = "follow_up_not_asked"

#: A day of the budget (§8:3).
_DAY_SECONDS: Final = 86_400.0

#: The most calls whose given entry waits for its returned one, and the most calls the
#: asker remembers it could not pair. Past either the oldest is forgotten; a call whose
#: given entry was forgotten is never asked about, since its returned entry can no longer
#: be paired unambiguously (§8:5).
_PENDING_CALLS: Final = 256
_SPOILED_CALLS: Final = 1024

#: The most observer calls whose copies may still be joined, before any copy's returned
#: entry has come back; past it the oldest is forgotten, and a copy written after is a
#: call of its own.
_OPEN_COPIES: Final = 256

#: Why a follow-up's second request is refused: it is sent once and never retried (§8:15).
_ONCE: Final = "a follow-up sends one request and is never retried (ADR-0337 §8:15)"

#: The sources whose given and returned entries record a model call (ADR-0334 §8:2).
_CALLING: Final = frozenset(
    {
        DiagnosticSource.UNDERSTANDING,
        DiagnosticSource.PLANNING,
        DiagnosticSource.DIGESTING,
        DiagnosticSource.OBSERVER,
    }
)

#: The observer's steps that make a model call (ADR-0333 §2:2, ADR-0346 §10:1).
_OBSERVER_CALLS: Final = frozenset({"scout", "framing", "placement"})

#: What tells one call's entries from another's of the same source in one activation's
#: file, where two may be outstanding at once: a digest's parts are sent together
#: (ADR-0308 §4:9), and the observer names each attempt's episode and step (ADR-0333
#: §2:3). Every other source sends one call at a time.
_IDENTITY: Final[dict[DiagnosticSource, tuple[str, ...]]] = {
    DiagnosticSource.DIGESTING: ("result", "question", "part", "parts"),
    DiagnosticSource.OBSERVER: ("stage", "episode", "attempt_started_at"),
}

#: What names the followed given entry in a follow-up entry, beside its source and its
#: instant, where its body names it: the observer's step, or a digest's result and part
#: (§8:10).
_NAMING: Final = ("stage", "result", "part", "parts")

type _CallKey = tuple[str, str, str]


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _Call:
    """One recorded call to ask about, and every activation it was written under (§8:11).

    Attributes:
        route: The route its follow-up goes to.
        model: The ``provider:model`` spec its follow-up is sent to (§8:8).
        given: Its given entry, as the first activation's file has it.
        returned: Its returned entry.
        targets: Its given entry under each activation it was written under, the first's
            included; the follow-up's entry is written under each.
        outcome: The answer or the failure, once the follow-up has been asked.
    """

    route: str
    model: str
    given: DiagnosticEntry
    returned: DiagnosticEntry
    targets: list[DiagnosticEntry]
    outcome: dict[str, object] | None = None


@dataclass(slots=True)
class _Copies:
    """The given entries of one observer call, one under each activation it read for.

    The observer writes a call's given entry under each activation in turn, sends the
    call once, then writes its returned entry under each (ADR-0333 §2:9). So a given
    entry holding what an open group's do, under an activation the group does not yet
    hold, is a copy of the group's call; the group closes once any copy's returned entry
    comes back, and a given entry after that is another call. No clock decides it.

    Attributes:
        key: What every copy's given entry holds the same.
        activations: The activations it holds a copy under.
        call: The call, once its first copy has been paired and admitted.
        settled: Whether its first copy has been paired, so that a later copy is joined
            to ``call``, or asked nothing where ``call`` is ``None``.
    """

    key: str
    activations: set[str] = field(default_factory=set)
    call: _Call | None = None
    settled: bool = False


@dataclass(frozen=True, slots=True)
class _Held:
    """A given entry waiting for its returned one, and the copies it is one of, if any."""

    entry: DiagnosticEntry
    copies: _Copies | None


@dataclass(frozen=True, slots=True)
class _Copy:
    """A copy of a call already asked about, under another activation: written, not asked."""

    call: _Call
    target: DiagnosticEntry


@dataclass(slots=True)
class _Budget:
    """The follow-up calls the budget has admitted: sent in the last day, and queued (§8:3)."""

    limit: int
    sent: deque[float] = field(default_factory=deque)
    queued: int = 0

    def admits(self, now: float) -> bool:
        """Whether one more follow-up may be queued, as ``now`` stands."""
        while self.sent and self.sent[0] <= now - _DAY_SECONDS:
            self.sent.popleft()
        return len(self.sent) + self.queued < self.limit


class _Once(WrapperModel):
    """A model that sends one request, and refuses a second (§8:15).

    A completion's agent may send a request of its own after an empty reply; for a
    follow-up that would be a retry, so it is refused and the follow-up recorded as
    failed. The vendor client's own retries are turned off where the model is built
    (:func:`_without_sdk_retries`), so the one request is one request on the wire.
    """

    def __init__(self, wrapped: models.Model) -> None:
        super().__init__(wrapped)
        self._sent = False

    def _take(self) -> None:
        if self._sent:
            raise ModelError(_ONCE)
        self._sent = True

    @override
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Send the one request."""
        self._take()
        return await super().request(messages, model_settings, model_request_parameters)

    @override
    @contextlib.asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        """Stream the one request."""
        self._take()
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as streamed:
            yield streamed


class FollowUpAsker:
    """The follow-up asked of every recorded call on the owner's hub (ADR-0337 §8).

    Structurally implements :class:`~ai_assistant.core.protocols.DiagnosticSink`: the
    composition root wraps it around the sink it hands every emitter, where
    ``Settings.follow_up_question`` is true (§8:5). See the module's docstring for what
    it asks and when; the methods below say how it holds to it.
    """

    def __init__(  # noqa: PLR0913 — the sink and the prompt, then keyword-only routes, budget, deadline, thinking, clocks and the models' seam
        self,
        sink: DiagnosticSink,
        *,
        prompt: PromptTemplate,
        routes: Mapping[str, str],
        daily_calls: int,
        timeout: float,
        thinking: ThinkingLevel = DEFAULT_THINKING,
        now: Callable[[], datetime] = _utcnow,
        clock: Callable[[], float] = time.monotonic,
        build: Callable[[str], models.Model] = infer_model,
    ) -> None:
        """Wrap ``sink``, and hold what a follow-up is sent with.

        Args:
            sink: The sink every entry is passed on to, and each follow-up's entry
                written through (§8:9).
            prompt: The ``follow_up`` template, as read at start (§6:1).
            routes: The ``provider:model`` spec of the first model of each route's
                stage (§8:8), one for each of :data:`FOLLOW_UP_ROUTES`. A follow-up
                goes to it, or, where the followed response names the model that
                answered, to that model of the same provider.
            daily_calls: ``Settings.follow_up_daily_calls`` (§8:3).
            timeout: Seconds a follow-up may take before it is recorded as failed: the
                stage's own deadline, ``Settings.model_timeout_seconds``.
            thinking: The thinking a planning round's follow-up asks for, the
                completer's own.
            now: The clock each follow-up's entry is stamped from.
            clock: The monotonic clock the budget's day is measured on.
            build: Builds the model a spec names: pydantic-ai's own resolution, and a
                test's seam. Each spec's model is built once, at its first follow-up,
                owned by the asker and closed with it.

        Raises:
            ValueError: If ``prompt`` is not the ``follow_up`` prompt's, ``routes``
                names other routes than :data:`FOLLOW_UP_ROUTES`, ``daily_calls`` is
                below zero or ``timeout`` is not above it.
            TypeError: If ``daily_calls`` is not an exact ``int``.
        """
        if prompt.declaration != FOLLOW_UP_PROMPT:
            msg = "the follow-up asker asks the follow_up prompt (ADR-0337 §6:1)"
            raise ValueError(msg)
        if set(routes) != FOLLOW_UP_ROUTES or not all(
            isinstance(spec, str) and spec.partition(":")[2] for spec in routes.values()
        ):
            msg = "the follow-up asker is given one provider:model spec for each route"
            raise ValueError(msg)
        if type(daily_calls) is not int:
            msg = "the follow-up's daily budget must be an integer"
            raise TypeError(msg)
        if daily_calls < 0:
            msg = "the follow-up's daily budget must be at least zero"
            raise ValueError(msg)
        if not timeout > 0:
            msg = "a follow-up's deadline must be above zero"
            raise ValueError(msg)
        rendered = prompt.rendered()
        self._sink = sink
        self._question = rendered.text
        self._follow_up_prompt = rendered.provenance()
        self._routes = dict(routes)
        self._build = build
        # The models built so far, by spec, each entered once and closed with the asker,
        # so a follow-up opens no client of its own (its pool is the model's).
        self._models: dict[str, models.Model] = {}
        self._owned = contextlib.AsyncExitStack()
        self._timeout = timeout
        self._thinking: ThinkingLevel = thinking
        self._now = now
        self._clock = clock
        self._budget = _Budget(daily_calls)
        # Given entries waiting for their returned ones, by call; and the calls that can
        # no longer be paired unambiguously, as an ordered set.
        self._pending: dict[_CallKey, list[_Held]] = {}
        self._spoiled: dict[_CallKey, None] = {}
        # The observer calls whose copies may still be joined, by what they hold the same.
        self._open: dict[str, _Copies] = {}
        self._queue: deque[_Call | _Copy] = deque()
        self._worker: asyncio.Task[None] | None = None
        self._closed = False

    # --- the sink ---------------------------------------------------------------

    async def write(self, entry: DiagnosticEntry) -> None:
        """Pass ``entry`` on unchanged, then read it for a call to ask about (§8:5-§8:7).

        Returns once the entry is passed on: reading it sends nothing and waits on
        nothing, and a follow-up it admits is sent later, off the activation's path.

        Args:
            entry: The entry, as its emitter wrote it.

        Raises:
            CancelledError: Whatever the wrapped sink re-raises (ADR-0314 §2:5).
        """
        try:
            await self._sink.write(entry)
        finally:
            self._observe(entry)

    async def aclose(self) -> None:
        """Stop: a follow-up not yet sent is not sent, and one in flight is abandoned (§8:16).

        Nothing keeps the queue, and the client of every model the asker built is closed.
        Idempotent; an entry handed on afterwards is passed on and asked about no more.
        """
        self._closed = True
        self._queue.clear()
        self._budget.queued = 0
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done():
            worker.cancel()
            # Waited without raising, so the worker's cancellation is not this caller's.
            await asyncio.wait({worker})
        # Then each model's client, once nothing can be sending on it.
        self._models.clear()
        await self._owned.aclose()

    # --- pairing (§8:4, §8:5) ---------------------------------------------------

    def _observe(self, entry: DiagnosticEntry) -> None:
        """Read one entry as it is handed on; nothing it finds raises (§8:7)."""
        if self._closed:
            return
        try:
            self._read(entry)
        except Exception as exc:  # the follow-up is subordinate to the work it follows
            _log.warning(
                FOLLOW_UP_NOT_ASKED,
                activation_id=entry.activation_id,
                source=entry.source.value,
                reason="unread",
                error_class=fault_class_of(exc),
            )

    def _read(self, entry: DiagnosticEntry) -> None:
        key = _call_key(entry)
        if key is None or key in self._spoiled:
            return
        if entry.kind is DiagnosticKind.GIVEN:
            copies = self._copies(entry) if entry.source is DiagnosticSource.OBSERVER else None
            self._pending.setdefault(key, []).append(_Held(entry, copies))
            while len(self._pending) > _PENDING_CALLS:
                forgotten = next(iter(self._pending))
                del self._pending[forgotten]
                self._spoil(forgotten)
        elif entry.kind is DiagnosticKind.RETURNED:
            self._paired(key, entry)

    def _copies(self, given: DiagnosticEntry) -> _Copies:
        """The open copies ``given`` is one more of, or a new group it is the first of."""
        key = _copies_key(given)
        group = self._open.get(key)
        if group is None or given.activation_id in group.activations:
            # None open, or this activation already holds one: another call (§8:11).
            group = _Copies(key)
            self._open[key] = group
            while len(self._open) > _OPEN_COPIES:
                del self._open[next(iter(self._open))]
        group.activations.add(given.activation_id)
        return group

    def _spoil(self, key: _CallKey) -> None:
        self._spoiled[key] = None
        while len(self._spoiled) > _SPOILED_CALLS:
            del self._spoiled[next(iter(self._spoiled))]

    def _paired(self, key: _CallKey, returned: DiagnosticEntry) -> None:
        """Pair a returned entry with the one given entry waiting for it, or with none.

        Where two given entries of one call's key wait, the returned entry could be
        either's, and neither call is asked about, nor any later one of that key in that
        activation, since a returned entry still to come could be either's too (§8:5).
        """
        held = self._pending.pop(key, None)
        if not held:
            return
        if len(held) > 1:
            self._spoil(key)
            self._skipped(returned, "unpaired")
            return
        given, copies = held[0].entry, held[0].copies
        if copies is None:
            call = self._call(given, returned)
            if call is not None:
                self._admit(call)
            return
        # The first copy back closes the group: a given entry after it is another call.
        if self._open.get(copies.key) is copies:
            del self._open[copies.key]
        if copies.settled:
            # §8:11: one call written under several activations is asked once.
            if copies.call is None:
                return
            if copies.call.outcome is None:
                copies.call.targets.append(given)
            else:
                self._enqueue(_Copy(copies.call, given))
            return
        copies.settled = True
        call = self._call(given, returned)
        if call is not None and self._admit(call):
            copies.call = call

    def _call(self, given: DiagnosticEntry, returned: DiagnosticEntry) -> _Call | None:
        """The call to ask about, or ``None`` where it is no recorded call (§8:4, §8:8)."""
        prompt = given.body.get("prompt")
        if not isinstance(prompt, Mapping) or not isinstance(prompt.get("name"), str):
            return None
        source = given.source
        stage = given.body.get("stage") if source is DiagnosticSource.OBSERVER else None
        route = source.value if stage is None else f"{source.value}.{stage}"
        model = self._routes[route]
        if source is DiagnosticSource.PLANNING:
            response = returned.body.get("response")
            if not isinstance(response, Mapping):
                return None
            named = response.get("model_name")
            if isinstance(named, str) and named:
                # §8:8: the model that answered, as the provider named it, through the
                # route's own provider, the one the call itself went to.
                model = f"{model.partition(':')[0]}:{named}"
        elif not isinstance(returned.body.get("reply"), str):
            return None
        return _Call(route=route, model=model, given=given, returned=returned, targets=[given])

    def _admit(self, call: _Call) -> bool:
        """Queue the call's follow-up where the budget admits it; say whether it did."""
        if not self._budget.admits(self._clock()):
            self._skipped(call.returned, "budget")
            return False
        self._budget.queued += 1
        self._enqueue(call)
        return True

    def _skipped(self, entry: DiagnosticEntry, reason: str) -> None:
        _log.info(
            FOLLOW_UP_NOT_ASKED,
            activation_id=entry.activation_id,
            source=entry.source.value,
            reason=reason,
        )

    # --- asking, off the activation's path (§8:7, §8:8) ---------------------------

    def _enqueue(self, item: _Call | _Copy) -> None:
        self._queue.append(item)
        if self._worker is None or self._worker.done():
            # In a context of its own, so nothing the activation bound — its diagnostic
            # run, its correlation — is the follow-up's.
            self._worker = asyncio.get_running_loop().create_task(
                self._drain(), context=contextvars.Context()
            )

    async def _drain(self) -> None:
        """Ask each queued follow-up in turn, and write each copy's entry."""
        while self._queue:
            item = self._queue.popleft()
            try:
                if isinstance(item, _Call):
                    self._budget.queued -= 1
                    await self._ask(item)
                else:
                    await self._write(item.call, item.target)
            except asyncio.CancelledError as exc:
                if _cancelled():
                    raise  # the asker is closing: nothing more is sent (§8:16)
                _log.warning(
                    FOLLOW_UP_NOT_ASKED,
                    activation_id=item.target.activation_id
                    if isinstance(item, _Copy)
                    else item.given.activation_id,
                    source=DiagnosticSource.FOLLOW_UP.value,
                    reason="fault",
                    error_class=type(exc).__name__,
                )
            except Exception as exc:  # one follow-up's fault never stops the next
                _log.warning(
                    FOLLOW_UP_NOT_ASKED,
                    activation_id=item.target.activation_id
                    if isinstance(item, _Copy)
                    else item.given.activation_id,
                    source=DiagnosticSource.FOLLOW_UP.value,
                    reason="fault",
                    error_class=fault_class_of(exc),
                )

    async def _ask(self, call: _Call) -> None:
        """Send the follow-up once, then write its entry under each activation (§8:9-§8:11)."""
        self._budget.sent.append(self._clock())
        try:
            answer = await self._send(call)
        except asyncio.CancelledError as exc:
            if _cancelled():
                raise  # the asker is closing: the follow-up is not sent (§8:16)
            # A cancellation the model raised of its own, not the asker's: a failure.
            call.outcome = {"failure": failure_body(exc)}
        except Exception as exc:  # recorded, never retried (§8:15)
            call.outcome = {"failure": failure_body(exc)}
        else:
            call.outcome = {"answer": answer}
        index = 0
        # By index: a copy paired while the follow-up was out joins the list, and is
        # written here too.
        while index < len(call.targets):
            await self._write(call, call.targets[index])
            index += 1

    async def _send(self, call: _Call) -> str:
        """The follow-up's one request, to the route's one model (§6:3-§6:6, §8:8)."""
        given = call.given.model_dump(mode="json")["body"]
        returned = call.returned.model_dump(mode="json")["body"]
        once = _Once(await self._model(call.model))
        async with asyncio.timeout(self._timeout) as deadline:
            if call.given.source is DiagnosticSource.PLANNING:
                # ADR-0356 §13:6: planning's given entry records the work's exchange.
                exchange = PlanningExchange.model_validate(given["exchange"])
                tools = [OfferedTool.model_validate(one) for one in given["tools"]]
                answer = await follow_up_round(
                    exchange,
                    tools,
                    returned["response"],
                    self._question,
                    model=once,
                    thinking=self._thinking,
                )
            else:
                messages = [Message.model_validate(one) for one in given["messages"]]
                reply = await PydanticAIProvider(once).complete(
                    [
                        *messages,
                        Message(role=Role.ASSISTANT, content=returned["reply"]),
                        Message(role=Role.USER, content=self._question),
                    ]
                )
                answer = reply.content
        if deadline.expired():
            # A model that swallowed the deadline's cancellation and answered anyway
            # answered past it: the follow-up failed, whatever came back.
            raise TimeoutError
        return answer

    async def _model(self, spec: str) -> models.Model:
        """The model ``spec`` names: built at its first follow-up, then kept until closed.

        Its vendor client's own retries are turned off, and its context entered once, so
        its client is closed by :meth:`aclose` and by nothing a follow-up does.

        Raises:
            Exception: Whatever building it raises, a missing credential included; the
                follow-up is recorded as failed, and the next one builds it again.
        """
        held = self._models.get(spec)
        if held is None:
            held = self._build(spec)
            _without_sdk_retries(held)
            await self._owned.enter_async_context(held)
            self._models[spec] = held
        return held

    async def _write(self, call: _Call, target: DiagnosticEntry) -> None:
        """Write the follow-up's entry under ``target``'s activation; no failure escapes."""
        given = target.model_dump(mode="json")
        body = given["body"]
        follows: dict[str, object] = {
            "source": given["source"],
            "recorded_at": given["recorded_at"],
            **{name: body[name] for name in _NAMING if name in body},
        }
        try:
            entry = DiagnosticEntry.model_validate(
                {
                    "activation_id": target.activation_id,
                    "source": DiagnosticSource.FOLLOW_UP,
                    "kind": DiagnosticKind.RETURNED,
                    "recorded_at": self._now(),
                    "body": {
                        "follows": follows,
                        "prompt": body["prompt"],
                        "follow_up_prompt": self._follow_up_prompt,
                        "model": call.model,
                        **(call.outcome or {}),
                    },
                }
            )
            await self._sink.write(entry)
        except Exception as exc:  # handled as ADR-0314 §2:4 has it; never retried (§8:15)
            _log.warning(
                DIAGNOSTIC_NOT_WRITTEN,
                activation_id=target.activation_id,
                source=DiagnosticSource.FOLLOW_UP.value,
                error_class=fault_class_of(exc),
            )


def _cancelled() -> bool:
    """Whether the running task itself is being cancelled, not merely handed a cancellation."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


def _call_key(entry: DiagnosticEntry) -> _CallKey | None:
    """Which call an entry is of, as far as pairing needs: activation, source, identity."""
    if entry.source not in _CALLING:
        return None
    body = entry.body
    if entry.source is DiagnosticSource.OBSERVER and body.get("stage") not in _OBSERVER_CALLS:
        return None
    identity = json.dumps([body.get(name) for name in _IDENTITY.get(entry.source, ())], default=str)
    return entry.activation_id, entry.source.value, identity


def _copies_key(given: DiagnosticEntry) -> str:
    """What every activation's copy of one observer call's given entry holds the same.

    Its body but the two fields naming the episode it was written for (ADR-0333 §2:3,
    §2:9): the step, the request, the finding a framing or a placement call decides and
    the prompt key.
    """
    held = {
        name: value
        for name, value in given.model_dump(mode="json")["body"].items()
        if name not in {"episode", "attempt_started_at"}
    }
    return json.dumps(held, sort_keys=True, ensure_ascii=True)


def _without_sdk_retries(model: models.Model) -> None:
    """Turn off the retries a vendor's own client makes inside one request (§8:15).

    Anthropic's and OpenAI's clients each retry a 429 or a 5xx twice by default
    (ADR-0061 §3), inside one request of the model's: the follow-up's one request
    would be three on the wire, and its budget would count one. The client is the
    model's own, built for the asker alone, so nothing else's retries change. A
    client without the setting retries as it does.
    """
    inner = model
    while isinstance(inner, WrapperModel):
        inner = inner.wrapped
    client: Any = getattr(inner, "client", None)
    retries = getattr(client, "max_retries", None)
    if type(retries) is int:
        client.max_retries = 0

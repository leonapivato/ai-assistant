"""Planning's three calls on running work: the stop, the look-up, and the answer (ADR-0349).

- **The stop call** (§4:6-§4:12), :data:`STOP_ACTIVATION`: the Task Manager's stop, by the
  one implementation ``AssistantEngine.stop_activation`` runs, which stops exactly the
  activation it names and nothing below it (ADR-0352 §2:1). Offered where the
  activation's input carries the user's authority. It names one
  running activation by the label planning was shown it under as running: in a list
  pull's running part, an offer or a wait. It is refused whole, as *not done* with the
  reason, and stops nothing, where the input does not carry the user's authority, where
  the label was not shown for a running activation, and where the activation named was
  absorbed since it was shown, naming its absorber. Where it stopped the activation, or
  found it ended, its result shows that activation's finished work through the peer view,
  and what that activation set up that is still live below it, or that nothing is
  (ADR-0352 §3:1-§3:6). It writes the plan store's stop record, so it is an act, and
  commits its activation.
- **The findings look-up** (§6:1, §6:4-§6:6), :data:`LOOK_UP_ACTIVATION`: a pure read of
  a running activation's findings, by the same label, through the peer view; where it has
  ended since, its finished work, saying so.
- **The answer call** (§7:20), :data:`ANSWER_OFFER`: take an offer open to this
  activation, or decline it with a short reason, naming it by the offering activation's
  label. Refused whole where the label names no offer open to it. Whether it came to
  what it asked is held for acting, which dispatches the rest of the round only where
  every answer did (ADR-0352 §4), and, where it did not, why: the offering activation
  stopped or ended, the take refused at ``held_input_limit``, or no offer open. A
  withdrawal and a refusal at the limit are shown to planning beside the answer's result
  (ADR-0349 §7:23).

Each is declared as ADR-0350 §4:1 declares the cancel of a scheduled task: the
assistant's own records, never leaving the hub, an outcome never unknown, safe to repeat,
a result with no outside text; the stop and the answer write the person's tier, and the
look-up writes nothing (§4:7, §6:4, §7:20). Acting runs each directly, awaited to its end
and never through ``ToolInvoker``. Who calls, and what it was shown, is read from
:func:`current_caller`, which the phases open around acting, never from what a call
carries.

What a call came back with reaches planning under labels: the peer view of the activation
it named, read fresh (:class:`PeerShown`), with, for a stop, what it set up that is still
live, held by the call's decision in the caller's scope for the phases to show under the
call's result.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActivationStop,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.matters import (
    ANSWER_OFFER_CAPABILITY,
    LOOK_UP_ACTIVATION_CAPABILITY,
    STOP_ACTIVATION_CAPABILITY,
    NotAsAsked,
    TakeAnswer,
)
from ai_assistant.orchestration.person_calls import NotDone
from ai_assistant.orchestration.planning import PeerShown

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from ai_assistant.core.types import FrozenJson, ToolCall
    from ai_assistant.orchestration.acting import OwnRecordsAnswer
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.matters import Matters

__all__ = [
    "ACTIVATION_ARGUMENT",
    "ANSWER_OFFER",
    "ANSWER_OFFER_CAPABILITY",
    "LOOK_UP_ACTIVATION",
    "LOOK_UP_ACTIVATION_CAPABILITY",
    "MATTER_CALLS",
    "MATTER_CAPABILITIES",
    "MATTER_LABEL_ARGUMENTS",
    "OFFER_ARGUMENT",
    "REASON_ARGUMENT",
    "STOP_ACTIVATION",
    "STOP_ACTIVATION_CAPABILITY",
    "TAKE_ARGUMENT",
    "MatterCaller",
    "MatterCalls",
    "calling",
    "current_caller",
]

_log = structlog.get_logger(__name__)

#: Every capability this module declares.
MATTER_CAPABILITIES: Final = frozenset(
    {STOP_ACTIVATION_CAPABILITY, LOOK_UP_ACTIVATION_CAPABILITY, ANSWER_OFFER_CAPABILITY}
)

#: The stop's and the look-up's one argument: the running activation, by its ``E`` label.
ACTIVATION_ARGUMENT: Final = "activation"
#: The answer's arguments: the offer, by the offering activation's ``E`` label; whether it
#: is taken; and a decline's short reason.
OFFER_ARGUMENT: Final = "offer"
TAKE_ARGUMENT: Final = "take"
REASON_ARGUMENT: Final = "reason"

_EPISODE: Final = "activation:"


def _declared(
    capability: str, description: str, schema: dict[str, FrozenJson], *, writes: bool
) -> ToolDefinition:
    """One call's declaration, as ADR-0350 §4:1 declares the cancel of a scheduled task."""
    return ToolDefinition(
        id=capability,
        capability=capability,
        description=description,
        risk_level=RiskLevel.LOW,
        # As the cancel of a scheduled task declares it (ADR-0350 §4:1).
        reversibility=Reversibility.RECOVERABLE if writes else Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(DataTier.PERSONAL,),
        writes=(DataTier.PERSONAL,) if writes else (),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
        effect=CapabilityEffect.OWN_RECORDS,
        leaves_hub=False,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=False,
        safe_to_repeat=True,
        parameters_schema=schema,
    )


def _naming(description: str) -> dict[str, FrozenJson]:
    return {
        "type": "object",
        "properties": {
            ACTIVATION_ARGUMENT: {"type": "string", "minLength": 1, "description": description}
        },
        "required": [ACTIVATION_ARGUMENT],
        "additionalProperties": False,
    }


STOP_ACTIVATION: Final = _declared(
    STOP_ACTIVATION_CAPABILITY,
    (
        "Stop running work you were shown as running, and that work alone. Nothing it "
        "already did is undone, and what it set up stays. The result shows what it had "
        "finished and what it set up that is still live."
    ),
    _naming("The running work, by its E label."),
    writes=True,
)
"""``stop_activation``: planning's stop call (ADR-0349 §4:6-§4:7, ADR-0352 §3:9).

Its description is the prompts front's words, as routed for ADR-0352 §3:10."""

LOOK_UP_ACTIVATION: Final = _declared(
    LOOK_UP_ACTIVATION_CAPABILITY,
    "See what running work you were shown as running has found and done so far.",
    _naming("The running work, by its E label."),
    writes=False,
)
"""``look_up_activation``: the findings look-up, a pure read (ADR-0349 §6:1, §6:4)."""

ANSWER_OFFER: Final = _declared(
    ANSWER_OFFER_CAPABILITY,
    (
        "Answer newer input offered to this work: take it, and it becomes part of this "
        "work; or decline it, with a short reason, and it is done after this work ends."
    ),
    {
        "type": "object",
        "properties": {
            OFFER_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "description": "The offer, by its E label.",
            },
            TAKE_ARGUMENT: {"type": "boolean", "description": "Whether you take it."},
            REASON_ARGUMENT: {
                "type": "string",
                "minLength": 1,
                "maxLength": 300,
                "description": "Why you decline it, in a few words.",
            },
        },
        "required": [OFFER_ARGUMENT, TAKE_ARGUMENT],
        "additionalProperties": False,
    },
    writes=True,
)
"""``answer_offer``: the answer call (ADR-0349 §7:20)."""

#: The three declarations, in the order they are offered.
MATTER_CALLS: Final = (STOP_ACTIVATION, LOOK_UP_ACTIVATION, ANSWER_OFFER)

#: Which of the calls' arguments name a running activation by its episode's label
#: (ADR-0307 §5:2): planning maps each to its episode's id, and refuses whole a call
#: naming a label it was never shown (§5:3).
MATTER_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    STOP_ACTIVATION_CAPABILITY: {ACTIVATION_ARGUMENT: LabelKind.EPISODE},
    LOOK_UP_ACTIVATION_CAPABILITY: {ACTIVATION_ARGUMENT: LabelKind.EPISODE},
    ANSWER_OFFER_CAPABILITY: {OFFER_ARGUMENT: LabelKind.EPISODE},
}

#: The code-owned reasons a call is not done for.
_NO_AUTHORITY: Final = "this input does not carry the person's authority, so it stops nothing"
_NOT_SHOWN_RUNNING: Final = (
    "that label was not shown as running work, in a list, an offer or a wait"
)
_NOT_WAITED_ON: Final = "this round may stop only the work it waits on"
_ABSORBED: Final = "newer work absorbed it since it was shown, so nothing was stopped"
_NO_OFFER: Final = "that label names no offer open to this work"
_MALFORMED: Final = "the call's arguments are malformed"
_STORE_FAULT: Final = "the hub's records could not be read or written"
_NOT_OFFERED: Final = "this call is not offered to this activation"
_STOP_UNRECORDED: Final = (
    "only in part: the work is stopped, but its stop could not be recorded; asking again records it"
)


@dataclass(slots=True)
class MatterCaller:
    """What the phases know of the activation whose round's calls are running.

    Attributes:
        state: The calling activation's state.
        users_authority: Whether its input carries the user's authority (§4:6).
        owner_records: Whether a record placed for the owner alone may be shown to it,
            which decides a peer view's notes and evidence.
        running: Each activation it was shown as running: in a list pull's running
            part, an offer or a wait (§4:6, §6:1).
        waiting: Where its round is a waiting round, the activations it waits on, the
            only ones its stop call may name (§7:26); ``None`` otherwise.
        supply: Its audience posture, which what a stopped activation set up that is
            running is shown under, as the list pull's running part is (ADR-0352 §3:4).
        shown: What each call came back with, by its decision's id, for the phases to
            show under its result.
        as_asked: Each answer call that came to what it asked, by its decision's id: a
            take to a take, or a decline to the decline (ADR-0352 §4:2-§4:3). An answer
            refused whole, withdrawn, or refused at ``held_input_limit`` is not here.
        not_as_asked: Why each answer call that ran and did not come to what it asked
            did not, by its decision's id, for acting's held-back reason (§4:2). An
            answer whose arguments or records failed is in neither.
    """

    state: ActivationState
    users_authority: bool
    owner_records: bool
    running: frozenset[str]
    waiting: frozenset[str] | None = None
    supply: TurnSupply | None = None
    shown: dict[str, PeerShown] = field(default_factory=dict)
    as_asked: set[str] = field(default_factory=set)
    not_as_asked: dict[str, NotAsAsked] = field(default_factory=dict)


_CALLING: Final[contextvars.ContextVar[MatterCaller | None]] = contextvars.ContextVar(
    "matter_calling", default=None
)


@contextlib.contextmanager
def calling(caller: MatterCaller | None) -> Iterator[None]:
    """Hand ``caller`` to the calls on running work run inside this scope.

    Yields:
        Nothing: the scope is the context it runs in.
    """
    token = _CALLING.set(caller)
    try:
        yield
    finally:
        _CALLING.reset(token)


def current_caller() -> MatterCaller | None:
    """The caller :func:`calling` holds, or ``None`` outside such a scope."""
    return _CALLING.get()


def _named(arguments: Mapping[str, FrozenJson], key: str) -> str | None:
    """The activation an argument names, by the episode id its label mapped to."""
    value = arguments.get(key)
    if not isinstance(value, str) or not value.startswith(_EPISODE):
        return None
    named = value.removeprefix(_EPISODE)
    return named or None


class MatterCalls:
    """Acting's runner for the stop, the look-up and the answer (ADR-0349 §4, §6, §7).

    Structurally acting's ``OwnRecordsCalls``: each call runs directly, awaited to its
    end, over the one :class:`~ai_assistant.orchestration.matters.Matters`.
    """

    def __init__(self, *, matters: Matters) -> None:
        """Wire the runner.

        Args:
            matters: What crosses the engine's activations, whose stop is the Task
                Manager's.
        """
        self._matters = matters

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """Run a stop, a look-up or an answer for the activation :func:`calling` holds."""
        caller = current_caller()
        if caller is None:
            return NotDone(reason=_NOT_OFFERED)
        capability = str(call.request.tool.capability)
        arguments = call.request.parameters
        try:
            if capability == STOP_ACTIVATION_CAPABILITY:
                return await self._stop(caller, call.decision.id, arguments)
            if capability == LOOK_UP_ACTIVATION_CAPABILITY:
                return await self._look_up(caller, call.decision.id, arguments)
            if capability == ANSWER_OFFER_CAPABILITY:
                return await self._answer(caller, call.decision.id, arguments)
        except PlanningError, MemoryStoreError:
            _log.warning("matter_call_not_done", stage="acting", reason="store_failed")
            return NotDone(reason=_STORE_FAULT)
        return NotDone(reason=_MALFORMED)

    async def _stop(
        self, caller: MatterCaller, decision: str, arguments: Mapping[str, FrozenJson]
    ) -> OwnRecordsAnswer:
        """§4:6-§4:11: stop the activation named, or refuse whole and stop nothing."""
        named = _named(arguments, ACTIVATION_ARGUMENT)
        refused = self._refused_stop(caller, decision, named)
        if refused is not None:
            return refused
        assert named is not None  # noqa: S101 — a call naming nothing is refused above
        running = self._matters.state_of(named)
        if running is None:
            # §4:10: it has ended since it was shown, so this call stops nothing, and its
            # result says so.
            _log.info("matter_stop", stage="acting", stopped="ended")
            await self._show(caller, decision, named, stopped=False)
            return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"kind": "matter_stop"})
        # One stopped since it was shown is stopped again all the same, which stops
        # nothing new but writes its stop record where an earlier stop's write failed
        # (ADR-0297 §3:7); its result says this call did not stop it.
        already = running.stopped
        try:
            stopped = await self._matters.stop(named)
        except PlanningError:
            if not running.stopped:
                raise
            # §4:1, ADR-0297 §3:7: the mark is set and holds the activation, but its
            # records are not written; asking again writes them.
            _log.warning("matter_stop_unrecorded", stage="acting", reason="store_failed")
            return NotDone(reason=_STOP_UNRECORDED)
        _log.info("matter_stop", stage="acting", stopped=stopped.value)
        await self._show(
            caller, decision, named, stopped=stopped is ActivationStop.STOPPED and not already
        )
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"kind": "matter_stop"})

    def _refused_stop(
        self, caller: MatterCaller, decision: str, named: str | None
    ) -> NotDone | None:
        """§4:8-§4:9: why a stop call is refused whole, stopping nothing, or ``None``."""
        if not caller.users_authority:
            _log.info("matter_call_not_done", stage="acting", reason="no_authority")
            return NotDone(reason=_NO_AUTHORITY)
        if named is None:
            return NotDone(reason=_MALFORMED)
        if named not in caller.running:
            _log.info("matter_call_not_done", stage="acting", reason="not_shown_running")
            return NotDone(reason=_NOT_SHOWN_RUNNING)
        if caller.waiting is not None and named not in caller.waiting:
            _log.info("matter_call_not_done", stage="acting", reason="not_waited_on")
            return NotDone(reason=_NOT_WAITED_ON)
        absorber = self._matters.absorbed_by(named)
        if absorber is not None:
            # §4:9: refused, naming the absorber; it is not followed forward.
            _log.info("matter_call_not_done", stage="acting", reason="absorbed")
            caller.shown[decision] = PeerShown(activation_id=named, absorbed_by=absorber)
            return NotDone(reason=_ABSORBED)
        return None

    async def _look_up(
        self, caller: MatterCaller, decision: str, arguments: Mapping[str, FrozenJson]
    ) -> OwnRecordsAnswer:
        """§6:1, §6:5-§6:6: the activation's findings, read fresh, or a refusal whole."""
        named = _named(arguments, ACTIVATION_ARGUMENT)
        if named is None:
            return NotDone(reason=_MALFORMED)
        if named not in caller.running:
            _log.info("matter_call_not_done", stage="acting", reason="not_shown_running")
            return NotDone(reason=_NOT_SHOWN_RUNNING)
        await self._show(caller, decision, named, stopped=None)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"kind": "matter_look_up"})

    async def _answer(
        self, caller: MatterCaller, decision: str, arguments: Mapping[str, FrozenJson]
    ) -> OwnRecordsAnswer:
        """§7:20-§7:23: take or decline an offer open to the caller, by its label."""
        named = _named(arguments, OFFER_ARGUMENT)
        take = arguments.get(TAKE_ARGUMENT)
        reason = arguments.get(REASON_ARGUMENT)
        if named is None or not isinstance(take, bool):
            return NotDone(reason=_MALFORMED)
        if reason is not None and not isinstance(reason, str):
            return NotDone(reason=_MALFORMED)
        answer = self._matters.answer(caller.state, named, take=take, reason=reason)
        answered, short = answer.came_to, answer.not_as_asked
        if answered is TakeAnswer.NO_OFFER:
            _log.info("matter_call_not_done", stage="acting", reason="no_offer")
            caller.not_as_asked[decision] = NotAsAsked.NO_OFFER
            return NotDone(reason=_NO_OFFER)
        _log.info(
            "matter_answer",
            stage="acting",
            answered=answered.value,
            not_as_asked=None if short is None else short.value,
        )
        if short is None:
            # ADR-0352 §4:3: settled as planning asked, so the rest of its round may run.
            caller.as_asked.add(decision)
        else:
            caller.not_as_asked[decision] = short
        if answered is TakeAnswer.TAKEN:
            # §7:21: after the step, as an absorption's is; awaited to its end.
            await self._matters.record_stop(named, deadline=None, stage="acting")
        caller.shown[decision] = PeerShown(
            activation_id=named,
            answered=answered.value,
            not_as_asked=short,
            meaning=answer.meaning,
        )
        output: dict[str, FrozenJson] = {"kind": "matter_answer", "answered": answered.value}
        if answer.reason is not None:
            output["reason"] = answer.reason
        if short is not None:
            output["not_as_asked"] = short.value
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=output)

    async def _show(
        self, caller: MatterCaller, decision: str, named: str, *, stopped: bool | None
    ) -> None:
        """Hold the named activation's work, read fresh through the peer view (§6:7).

        After a stop, a read that fails leaves the stop done, its work shown as not read:
        what the call did happened, whatever the read after it found (§4:11). For a
        look-up the read is the call, so its failure is the call's.

        After a stop, what the activation set up that is still live is read too, once
        the stop's record is written or the activation was found ended (ADR-0352 §3:1-
        §3:2); a read of it that fails is shown as not read, and the stop stands.
        """
        try:
            view = await self._matters.peer(named, owner_records=caller.owner_records)
        except PlanningError, MemoryStoreError:
            if stopped is None:
                raise
            _log.warning("matter_stop_work_unread", stage="acting", reason="store_failed")
            view = None
        left = (
            None
            if stopped is None
            else await self._matters.still_live(named, viewer=caller.state, supply=caller.supply)
        )
        running = self._matters.state_of(named)
        caller.shown[decision] = PeerShown(
            activation_id=named,
            view=view,
            ended=running is None or running.stopped,
            stopped=stopped,
            set_up=left,
        )

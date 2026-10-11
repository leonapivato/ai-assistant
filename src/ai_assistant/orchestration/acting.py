"""The acting stage: a round's allowed calls run, claimed and recorded (ADR-0306 §5).

One orchestration-local phase module, of the kind
:class:`~ai_assistant.orchestration.recall.RecallStage` is (ADR-0309 §2:2). It holds an
injected ``PlanStore`` and ``ToolInvoker``, a seam onto the assistant's own records,
and the composition root's call deadline, and it is **not a Protocol**. It calls no
model and decides nothing about whether a call should run: authorizing has done that,
and acting is handed only the calls it allowed.

**In parallel, with no model** (§5:1). Every call of the round starts at once, and each
comes back done, not done with its reason, or unknown.

**Claimed before it runs** (§5:2 to §5:4). A call to a capability whose effect is the
world, and a call to one that is not safe to repeat, gets an effect record. Acting
claims it through :meth:`~ai_assistant.core.protocols.PlanStore.claim_activation_effect`
before the call runs, and the store decides the stop, the duplicate backstop and the
write in one indivisible step. ``match`` is supplied here and never read from a story
by the store (§6:3): for a call that is not safe to repeat, the round's activation and
the activations of the episodes in its stories as they stood when the round was
authorized; for every other claim, ``None``. A stopped activation's claim raises
``ClaimStopped`` and the call is not done; an ``already_done`` answer refuses it the
same way, and nothing runs.

**Two routes to run** (§3:3, §5:7). A call whose effect is the assistant's own records
runs directly against the store it reaches, through :class:`OwnRecordsCalls`, and is
awaited to its end: no deadline and no cancellation cuts it short. Every other call goes
through ``ToolInvoker``, whose invocation ledger claim and completion are its attempt
(ADR-0192 §3); where the call also has an effect record, that record was claimed before
the invocation and names the deciding decision, which names it.

**Finished as it happens** (§5:5). The outcome the call ended with is written onto its
record: ``succeeded`` is done, ``failed`` not done with a code-owned reason, and
``indeterminate`` unknown. **An unknown outcome is never retried, done another way, or
reported as done** (§5:13); nothing here retries anything. A call cancelled mid-flight
leaves its record unfinished: acting cannot read what the invocation ledger recorded,
and an unfinished record is never resolved by guessing (§5:6).

**Where a result goes** (§5:14 to §5:15). Acting mints an id for every result a done
call brings, which the result's R label names (ADR-0307 §5:1, ADR-0308 §6:1). A result
declared to carry no outside text goes to planning whole. A result that may carry
outside text and came back through ``ToolInvoker`` is one record whose writer is not
known, so it goes to a digest: acting holds it in its part of the working episode,
:class:`~ai_assistant.orchestration.held_results.HeldResults`, as it arrived and under
its id, as soon as it records it, and the :class:`ActedCall` carries the id and never
the content (ADR-0308 §6:1, §6:3, §6:5).

**What is left to later lanes, as seams.** Writing the round's message, which needs
ADR-0307's round (the message's record is already an :class:`ActivationEffect` shape);
and a memory search's record-by-record routing by stored provenance, with its outside
records held by id (ADR-0306 §5:16, ADR-0308 §6:2): until then a result of the
assistant's own records that may carry outside text is held whole as it arrived and
routed to a digest, the conservative direction. No controller rule runs this stage yet
(ADR-0309 §2:6).

**It logs stage and code-owned reason only**, never arguments or results (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, cast
from uuid import uuid4

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import (
    AuditError,
    ClaimStopped,
    SpendError,
    ToolBindingError,
)
from ai_assistant.core.types import (
    ActivationEffect,
    ActivationEffectClaim,
    CapabilityEffect,
    CapabilityResult,
    EgressBinding,
    ToolCall,
    ToolOutcome,
    ToolResult,
    canonical_json_bytes,
)
from ai_assistant.orchestration.activation_cleanup import drain_registered
from ai_assistant.orchestration.held_results import HeldResult

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import PlanStore, ToolInvoker
    from ai_assistant.core.types import (
        FrozenJson,
        FrozenJsonValue,
        ToolDefinition,
    )
    from ai_assistant.orchestration.held_results import HeldResults

__all__ = [
    "ActedCall",
    "ActedOutcome",
    "ActedRound",
    "ActingStage",
    "AuthorizedCall",
    "AuthorizedRound",
    "OwnRecordsCalls",
    "ResultRoute",
    "gets_effect_record",
    "values_digest",
]

_log = structlog.get_logger(__name__)

#: The invocation seam's refusals before the callable is reached (ADR-0029 §2,
#: ADR-0192 §1, ADR-0194 §4). Each means the call did not run, so it is not done.
_REFUSED_BEFORE_THE_CALL: Final = (ToolBindingError, SpendError, AuditError)


class ActedOutcome(StrEnum):
    """What came of one call, as planning reads it (ADR-0306 §5:1)."""

    DONE = "done"
    NOT_DONE = "not_done"
    UNKNOWN = "unknown"


class ResultRoute(StrEnum):
    """Where a done call's result goes (ADR-0306 §5:14)."""

    PLANNING = "planning"
    """Declared to carry no outside text: planning reads it whole."""

    DIGEST = "digest"
    """May carry text someone other than the user or the assistant wrote."""


#: Each ``ToolOutcome`` as an outcome planning reads (ADR-0306 §6's table).
_OUTCOMES: Final = {
    ToolOutcome.SUCCEEDED: ActedOutcome.DONE,
    ToolOutcome.FAILED: ActedOutcome.NOT_DONE,
    ToolOutcome.INDETERMINATE: ActedOutcome.UNKNOWN,
}

_STOPPED: Final = "the activation was stopped before this call was claimed"
_ALREADY_DONE: Final = "already done: an equal call was made in this matter"
_REFUSED: Final = "refused before the call was made"


def gets_effect_record(tool: ToolDefinition) -> bool:
    """Whether a call under ``tool`` gets an effect record (ADR-0306 §5:3).

    A call in the world, and a call to a capability that is not safe to repeat. A
    message gets one too, but is not a tool call.

    Args:
        tool: The declaration the call was ruled on.

    Returns:
        Whether acting claims the call before it runs.
    """
    return tool.effect is CapabilityEffect.WORLD or not tool.safe_to_repeat


def values_digest(call: ToolCall) -> str:
    """The digest of a call's values the duplicate backstop compares (ADR-0306 §5).

    Taken over the call's arguments without those its declaration names in
    ``system_supplied`` (§2:10), and, for a call that leaves the hub, its binding's
    account, transport endpoint and canonical destination set (§5:12), in the one
    canonical JSON form :func:`~ai_assistant.core.types.canonical_json_bytes` renders.
    The *looking for* argument and the *deliberate repeat* mark are removed before the
    call reaches acting, so neither is in it.

    Args:
        call: The authorized call, as it will be invoked.

    Returns:
        A lowercase SHA-256 hex digest.
    """
    tool = call.request.tool
    excluded = set(tool.system_supplied)
    arguments = {
        key: value for key, value in call.request.parameters.items() if key not in excluded
    }
    binding = call.request.egress_binding
    bound: dict[str, object] | None = None
    if isinstance(binding, EgressBinding):
        bound = {
            "account": binding.account.model_dump(mode="json"),
            "transport_endpoint": binding.transport_endpoint,
            "canonical_destination_set": [
                member.model_dump(mode="json") for member in binding.canonical_destination_set
            ],
        }
    document = cast("FrozenJson", {"arguments": arguments, "binding": bound})
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


class OwnRecordsCalls(Protocol):
    """The seam onto the assistant's own records, for a call acting runs directly.

    ADR-0306 §3:3: a call whose effect is the assistant's own records, and a read of
    them, runs against the store it reaches (ADR-0292 §12:1, §12:3), not through
    ``ToolInvoker``. Orchestration-local: the composition root wires the capabilities
    behind it once they exist; none does yet.
    """

    async def run(self, call: ToolCall) -> ToolResult:
        """Run ``call`` against the store it reaches and say what that store answered.

        Args:
            call: The authorized call.

        Returns:
            The store's answer as a result: ``succeeded`` with what it returned, or
            ``failed`` with why. Never ``indeterminate``, since a call to the
            assistant's own records is awaited to its end.
        """
        ...


@dataclass(frozen=True, slots=True)
class AuthorizedCall:
    """One call authorizing allowed, as acting takes it (ADR-0306 §4, §5).

    Attributes:
        call: The call as it will be invoked: its request, with the *looking for*
            argument and the *deliberate repeat* mark removed (§2:10), and the
            ``ALLOW`` decision that authorises it. The decision's ``effect`` names the
            record the call is claimed under, and is set exactly where the call gets
            one.
        deliberate_repeat: Whether planning marked the call a deliberate repeat.

    Raises:
        ValueError: If the decision's ``effect`` is set on a call that gets no record
            or missing on one that does, or a call to a capability safe to repeat is
            marked a deliberate repeat, which §2:9 offers only where it is not.
    """

    call: ToolCall
    deliberate_repeat: bool = False

    def __post_init__(self) -> None:
        """Check the call against its declaration."""
        tool = self.call.request.tool
        if gets_effect_record(tool) != (self.call.decision.effect is not None):
            msg = (
                "a call's decision names an effect record exactly where the call gets "
                "one (ADR-0306 §5:3, §5:8)"
            )
            raise ValueError(msg)
        if self.deliberate_repeat and tool.safe_to_repeat:
            msg = "only a call to a capability not safe to repeat is a deliberate repeat"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AuthorizedRound:
    """A round's allowed calls, as authorizing hands them to acting (ADR-0306 §5).

    The working-set type authorizing produces (ADR-0309 §3:1); defined here until
    authorizing is built.

    Attributes:
        activation_id: The activation the round belongs to.
        round_id: The planning round whose calls these are.
        calls: The calls authorizing allowed, in the round's order.
        story_activations: The activations of the episodes in this activation's
            stories, taken when the round was authorized (§5:10).
    """

    activation_id: str
    round_id: str
    calls: tuple[AuthorizedCall, ...]
    story_activations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Each call runs under its own decision, which names it (ADR-0306 §4)."""
        _distinct_decisions(self.calls)

    @property
    def match(self) -> tuple[str, ...]:
        """What a call not safe to repeat is matched against (ADR-0306 §5:9, §6:3).

        This activation's id and its stories' activations, each once. An activation
        in no story is matched against its own effects alone.
        """
        return tuple(dict.fromkeys((self.activation_id, *self.story_activations)))


@dataclass(frozen=True, slots=True)
class ActedCall:
    """What came of one call (ADR-0306 §5:1).

    Attributes:
        call: The call.
        outcome: Done, not done or unknown.
        reason: Why it was not done, in code-owned words; ``None`` otherwise.
        output: What a done call returned, where its result goes to planning whole;
            ``None`` otherwise. A result going to a digest is held instead, and never
            carried here (ADR-0308 §6:5).
        route: Where a done call's result goes; ``None`` where there is none.
        result_id: The id acting minted for a done call's result, which its R label
            names; ``None`` where there is none.
        effect_id: The effect record the call was claimed under, where it was.
    """

    call: AuthorizedCall
    outcome: ActedOutcome
    reason: str | None = None
    output: FrozenJsonValue = None
    route: ResultRoute | None = None
    result_id: str | None = None
    effect_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActedRound:
    """Acting's decision for one round: every call's outcome, in the round's order.

    Attributes:
        round_id: The planning round.
        calls: What came of each call.
    """

    round_id: str
    calls: tuple[ActedCall, ...] = field(default=())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_result_id() -> str:
    return f"result:{uuid4().hex}"


class ActingStage:
    """Run a round's allowed calls, claiming and recording their effects (ADR-0306 §5)."""

    def __init__(  # noqa: PLR0913 — the three seams, the deadline, the clock and the id source
        self,
        *,
        plans: PlanStore,
        invoker: ToolInvoker,
        own_records: OwnRecordsCalls,
        timeout: timedelta,
        now: Callable[[], datetime] = _utcnow,
        new_result_id: Callable[[], str] = _new_result_id,
    ) -> None:
        """Wire the stage to its seams, and to the deadline the composition root sets.

        Args:
            plans: The plan store the effect records are claimed in.
            invoker: The invocation seam a call not on the assistant's own records
                goes through.
            own_records: The seam a call on the assistant's own records runs through.
            timeout: Each invoked call's deadline. A call on the assistant's own
                records has none (§3:3).
            now: The clock a record's ``claimed_at`` is read from.
            new_result_id: Mints a result's id (ADR-0308 §6:1).

        Raises:
            ValueError: If ``timeout`` is not positive.
        """
        if timeout <= timedelta(0):
            msg = "acting's call deadline must be positive (ADR-0029 §4)"
            raise ValueError(msg)
        self._plans = plans
        self._invoker = invoker
        self._own_records = own_records
        self._timeout = timeout
        self._now = checked_clock(now, owner="ActingStage")
        self._new_result_id = new_result_id

    async def act(self, authorized: AuthorizedRound, *, held: HeldResults) -> ActedRound:
        """Run every call of ``authorized`` in parallel and say what came of each.

        Every call is let finish before this returns or raises, so a claimed call is
        never abandoned because a sibling failed.

        **Each call is revalidated and detached before the first ``await``**, and the
        claim, the invocation and the record all read that one snapshot. A caller's
        object can be rewritten past ``frozen=True`` while a claim is in flight, and a
        call claimed as one set of values and invoked as another would let the
        duplicate backstop check values that never ran (§5:9).

        Each result going to a digest is held in ``held`` as soon as its call is
        recorded, before the round's other calls have finished (ADR-0308 §4:2).

        Args:
            authorized: The round's allowed calls.
            held: The activation's held results, acting's part of its working
                episode.

        Returns:
            Each call's outcome, in the round's order.

        Raises:
            ToolBindingError: If a call does not survive revalidation. Raised before
                anything is claimed or run.
            ValueError: If two calls run under one decision, so that a held result
                could not name its call. Raised before anything is claimed or run.
            Exception: Whatever a call's seam raised beyond the refusals handled here,
                alone where one call raised and as an ``ExceptionGroup`` where several
                did.
        """
        activation_id = str(authorized.activation_id)
        round_id = str(authorized.round_id)
        match = tuple(str(one) for one in authorized.match)
        snapshots = [_snapshot(one) for one in authorized.calls]
        _distinct_decisions(snapshots)
        answers = await asyncio.gather(
            *(self._act(activation_id, round_id, match, one, held) for one in snapshots),
            return_exceptions=True,
        )
        acted: list[ActedCall] = []
        errors: list[Exception] = []
        for answer in answers:
            if isinstance(answer, ActedCall):
                acted.append(answer)
            elif isinstance(answer, Exception):
                errors.append(answer)
            else:
                raise answer
        if len(errors) == 1:
            raise errors[0]
        if errors:
            msg = "acting: several calls raised"
            raise ExceptionGroup(msg, errors)
        return ActedRound(round_id=round_id, calls=tuple(acted))

    async def _act(
        self,
        activation_id: str,
        round_id: str,
        match: tuple[str, ...],
        one: AuthorizedCall,
        held: HeldResults,
    ) -> ActedCall:
        """Claim one detached call where it gets a record, run it, and finish the record."""
        call = one.call
        tool = call.request.tool
        effect_id = call.decision.effect
        if effect_id is not None:
            record = ActivationEffect(
                id=effect_id,
                activation_id=activation_id,
                round=round_id,
                capability=tool.capability,
                values_digest=values_digest(call),
                decision_id=call.decision.id,
                claimed_at=self._now(),
            )
            try:
                answer = await self._plans.claim_activation_effect(
                    record,
                    match=None if tool.safe_to_repeat else match,
                    deliberate_repeat=one.deliberate_repeat,
                )
            except ClaimStopped:
                _log.info("acting_call_not_done", stage="acting", reason="stopped")
                return ActedCall(one, ActedOutcome.NOT_DONE, reason=_STOPPED)
            if answer is ActivationEffectClaim.ALREADY_DONE:
                _log.info("acting_call_not_done", stage="acting", reason="already_done")
                return ActedCall(one, ActedOutcome.NOT_DONE, reason=_ALREADY_DONE)
        if tool.effect is CapabilityEffect.OWN_RECORDS:
            # §3:3: awaited to its end, finish included, whatever cancels this task.
            work = asyncio.ensure_future(self._on_own_records(one, effect_id, round_id, held))
            return await drain_registered(work, cancel_on_interrupt=False)
        return await self._through_invoker(one, effect_id, round_id, held)

    async def _on_own_records(
        self, one: AuthorizedCall, effect_id: str | None, round_id: str, held: HeldResults
    ) -> ActedCall:
        """Run a call against the assistant's own records, then finish its record."""
        result = _detached_result(await self._own_records.run(one.call))
        if effect_id is not None:
            await self._finish(effect_id, result)
        return self._acted(one, result, effect_id, round_id, held)

    async def _through_invoker(
        self, one: AuthorizedCall, effect_id: str | None, round_id: str, held: HeldResults
    ) -> ActedCall:
        """Send a call through ``ToolInvoker``, under its ledger claim (ADR-0306 §5:7).

        **A cancellation leaves the record unfinished.** The invocation seam may have
        completed its ledger row with any outcome before the cancellation reached
        this frame, and acting holds no read of that row, so it cannot know what the
        call did. Writing the declaration's ``interrupted_outcome`` would contradict
        a ``succeeded`` the ledger holds, and the finish is written once. An
        unfinished record is never resolved by guessing and counts as done for the
        backstop (§5:6, §5:11); its recovery is #2584's.
        """
        try:
            result = _detached_result(await self._invoker.invoke(one.call, timeout=self._timeout))
        except _REFUSED_BEFORE_THE_CALL:
            # A code-owned reason and never the exception's class name, which a
            # collaborator can make carry content (ADR-0004 §5, ADR-0192 §3).
            _log.info("acting_call_not_done", stage="acting", reason="refused_before_the_call")
            if effect_id is not None:
                await self._plans.finish_activation_effect(
                    effect_id, ToolOutcome.FAILED, reason=_REFUSED
                )
            return ActedCall(one, ActedOutcome.NOT_DONE, reason=_REFUSED, effect_id=effect_id)
        if effect_id is not None:
            await self._finish(effect_id, result)
        return self._acted(one, result, effect_id, round_id, held)

    async def _finish(self, effect_id: str, result: ToolResult) -> None:
        """Write the outcome the call ended with onto its record (ADR-0306 §5:5)."""
        await self._plans.finish_activation_effect(
            effect_id, result.outcome, reason=_reason(result)
        )

    def _acted(
        self,
        one: AuthorizedCall,
        result: ToolResult,
        effect_id: str | None,
        round_id: str,
        held: HeldResults,
    ) -> ActedCall:
        """What came of a call that ran, routed by its declaration (§5:14 to §5:15).

        A done call's result takes a minted id. One going to a digest is held under it
        as it arrived, and the outcome carries the id alone (ADR-0308 §6:1, §6:5).
        """
        outcome = _OUTCOMES[result.outcome]
        if outcome is not ActedOutcome.DONE:
            return ActedCall(one, outcome, reason=_reason(result), effect_id=effect_id)
        declared = one.call.request.tool.result
        if declared is CapabilityResult.NONE:
            return ActedCall(one, outcome, effect_id=effect_id)
        result_id = str(self._new_result_id())
        if declared is CapabilityResult.NO_OUTSIDE_TEXT:
            return ActedCall(
                one,
                outcome,
                output=result.output,
                route=ResultRoute.PLANNING,
                result_id=result_id,
                effect_id=effect_id,
            )
        held.hold(
            HeldResult(
                result_id=result_id,
                round_id=round_id,
                decision_id=one.call.decision.id,
                content=result.output,
            )
        )
        return ActedCall(
            one, outcome, route=ResultRoute.DIGEST, result_id=result_id, effect_id=effect_id
        )


def _distinct_decisions(calls: Sequence[AuthorizedCall]) -> None:
    """Refuse a round in which two calls run under one decision.

    Raises:
        ValueError: If two calls share a decision id.
    """
    ids = [one.call.decision.id for one in calls]
    if len(set(ids)) != len(ids):
        msg = "each call of a round runs under its own decision, which names it"
        raise ValueError(msg)


def _snapshot(one: AuthorizedCall) -> AuthorizedCall:
    """Revalidate and detach one call, as the executor does before its claim.

    Rebuilt through validation, so nothing the caller still holds reaches what is
    claimed or invoked, and the call's own checks run again on the copy.

    Raises:
        ToolBindingError: If the call does not survive revalidation.
    """
    try:
        call = ToolCall.model_validate(one.call.model_dump())
        return AuthorizedCall(call, deliberate_repeat=bool(one.deliberate_repeat))
    except (ValidationError, ValueError) as exc:
        msg = "the call did not survive revalidation, so it is not the call that was authorised"
        raise ToolBindingError(msg) from exc


def _detached_result(result: ToolResult) -> ToolResult:
    """The seam's result, revalidated and detached before it is recorded or routed."""
    return ToolResult.model_validate(result.model_dump())


def _reason(result: ToolResult) -> str | None:
    """A code-owned reason for a call not done, or ``None`` for any other outcome.

    The failure's kind and never its message: the message is the integration's
    operator-facing text (ADR-0029 §3), and planning reads this.
    """
    if result.outcome is not ToolOutcome.FAILED:
        return None
    if result.failure is None:
        return "the call failed"
    return f"the call failed ({result.failure.kind.value})"

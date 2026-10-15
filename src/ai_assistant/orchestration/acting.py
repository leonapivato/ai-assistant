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

**A call that runs under an approval spends it** (ADR-0321 §4:9, §4:10). Acting knows
one by its decision's ``approval``. It gets an effect record whatever its capability,
and the record carries the decision's ``approved_part``, the asking round's id and the
part number, so the claim spends the part in the same indivisible step. A part some
record already carries comes back ``already_used``, and the call is not done, with the
reason, and never run: two yeses to one part cannot both run. A call whose approval
was given to another activation is not done either, before anything is claimed: the
yes's activation alone uses its approval (§4:1). A deliberate repeat under an approval
is claimed with both marks, which is how the store admits §6:2's retry.

**A call that comes back needing you** (ADR-0321 §5:5, #2845). A runner on the
own-records seam may answer :class:`~ai_assistant.orchestration.remembering.NeedsYou`:
nothing was written, and what the call would write needs the user's yes first, as a
remember's does where the memory writer's own policy asks at write time. Acting
finishes its record not done, with a code-owned reason, and reports it as
``needs_you``, carrying the assertions its question will show it replacing
(:attr:`ActedCall.replaces`).

**A call that runs under a yes reaches its runner with the asked call** (ADR-0321
§4:2, §5:2). Where the call was rebuilt from a question's asked call
(:attr:`AuthorizedCall.asked`) and the own-records seam takes one
(:class:`ApprovedOwnRecordsCalls`), the runner is handed it beside the call, so a
remember bounds what the yes retires by what the question showed. A seam that takes
none runs the call as any other.

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

**A result of the assistant's own records** (ADR-0306 §5:14, §5:16, ADR-0308 §6:2). A
runner on the own-records seam that reads records whose sources differ, such as a memory
search, answers :class:`HeldByIds`: what goes to planning, and the ids of the records
whose stored source is outside, which acting holds by id under the result's id for a
digest to fetch (ADR-0282 §2:3-§2:4). Any other result of the assistant's own records
that may carry outside text is held whole as it arrived and routed to a digest, the
conservative direction.

**The follow-up** (ADR-0308 §6:6-§6:7). Its runner answers :class:`NamedResult`, the
result the call names. Acting looks it up in the held results and offers that result, as
held, to a digest again under the follow-up's own decision, so the digest answers the
follow-up's *looking for*. It mints no result and holds nothing again, and the outcome
carries the named result's id. A follow-up naming a result with nothing held is not
done, with the reason.

**It logs stage and code-owned reason only**, never arguments or results (ADR-0275 §8).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, cast, runtime_checkable
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
    AskedCall,
    CapabilityEffect,
    CapabilityResult,
    EgressBinding,
    SemanticMemory,
    ToolCall,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    canonical_json_bytes,
)
from ai_assistant.orchestration.activation_cleanup import drain_registered
from ai_assistant.orchestration.held_results import HeldResult
from ai_assistant.orchestration.remembering import NeedsYou

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

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
    "ApprovedOwnRecordsCalls",
    "AuthorizedCall",
    "AuthorizedRound",
    "HeldByIds",
    "NamedResult",
    "OwnRecordsAnswer",
    "OwnRecordsByCapability",
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
    NEEDS_YOU = "needs_you"
    """Nothing ran or was written, and the call needs the user's yes (ADR-0321 §5:5)."""


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
_NOTHING_HELD: Final = "nothing is held under the result it names in this activation"
_ALREADY_DONE: Final = "already done: an equal call was made in this matter"
_ALREADY_USED: Final = "already used: the yes that approved this call has let it run once"
_ANOTHER_ACTIVATIONS: Final = (
    "not run: the yes that approved this call was given to another activation"
)
_REFUSED: Final = "refused before the call was made"
_NEEDS_YOU: Final = "needs you: nothing was written, and this needs your yes first"


def gets_effect_record(tool: ToolDefinition) -> bool:
    """Whether a call under ``tool`` gets an effect record (ADR-0306 §5:3).

    A call in the world, and a call to a capability that is not safe to repeat. A
    message gets one too, but is not a tool call. A call that runs under an approval
    gets one whatever its capability (ADR-0321 §4:10), which :class:`AuthorizedCall`
    reads off its decision.

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


@dataclass(frozen=True, slots=True)
class HeldByIds:
    """A done read of the assistant's own records, routed record by record (ADR-0306 §5:16).

    What a runner on the own-records seam answers for a capability whose result may carry
    outside text, such as a memory search, where it reads each record's stored source.

    Attributes:
        output: What goes to planning: the records whose source is not outside, as the
            runner gives them, JSON ``null`` included.
        outside: The ids of the records whose source is outside, in the order read.
            Acting holds them by id, never their contents, and a digest fetches them
            (ADR-0308 §6:2, ADR-0282 §2:3-§2:4).
    """

    output: FrozenJsonValue
    outside: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NamedResult:
    """A follow-up's answer: the held result it names (ADR-0308 §6:6-§6:7).

    Attributes:
        result_id: The id of the result the call names, as acting minted it.
    """

    result_id: str


#: What a runner on the own-records seam answers: the store's answer as a result; for a
#: read routed record by record or a follow-up, what acting holds or offers again; or,
#: where nothing was written because it needs the user's yes first, :class:`NeedsYou`.
type OwnRecordsAnswer = ToolResult | HeldByIds | NamedResult | NeedsYou


class OwnRecordsCalls(Protocol):
    """The seam onto the assistant's own records, for a call acting runs directly.

    ADR-0306 §3:3: a call whose effect is the assistant's own records, and a read of
    them, runs against the store it reaches (ADR-0292 §12:1, §12:3), not through
    ``ToolInvoker``. Orchestration-local: the composition root wires the capabilities
    behind it once they exist; none does yet.
    """

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """Run ``call`` against the store it reaches and say what that store answered.

        Args:
            call: The authorized call.

        Returns:
            The store's answer as a result: ``succeeded`` with what it returned, or
            ``failed`` with why. Never ``indeterminate``, since a call to the
            assistant's own records is awaited to its end. A done read routed record by
            record answers :class:`HeldByIds`, and a follow-up :class:`NamedResult`.
        """
        ...


class OwnRecordsByCapability:
    """The own-records seam, filled: each capability's runner, by capability name.

    ADR-0306 §3:3. Structurally :class:`OwnRecordsCalls`. The composition root hands
    it one runner per capability whose effect is the assistant's own records, such as
    :class:`~ai_assistant.orchestration.remembering.RememberCalls`, and acting hands
    every such call to it. A call to a capability it holds no runner for is not done,
    and nothing runs.
    """

    def __init__(self, runners: Mapping[str, OwnRecordsCalls]) -> None:
        """Hold a snapshot of ``runners``, so a caller's later change reaches nothing.

        Args:
            runners: The runner for each capability, by the capability's name.
        """
        self._runners: dict[str, OwnRecordsCalls] = dict(runners)

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        """Run ``call`` through its capability's runner, or say none holds it.

        Args:
            call: The authorized call.

        Returns:
            The runner's answer, or ``failed`` where no runner is held for the
            call's capability.
        """
        runner = self._runners.get(str(call.request.tool.capability))
        if runner is None:
            _log.info("acting_call_not_done", stage="acting", reason="no_own_records_runner")
            return ToolResult(
                outcome=ToolOutcome.FAILED,
                failure=ToolFailure(
                    kind=ToolFailureKind.INVALID_REQUEST,
                    message="no runner is held for this capability on the assistant's records",
                ),
            )
        return await runner.run(call)

    async def run_approved(self, call: ToolCall, asked: AskedCall) -> OwnRecordsAnswer:
        """Run a call under a yes through its runner, with the asked call where it takes one.

        A runner that takes no asked call runs ``call`` as any other.

        Args:
            call: The authorized call, rebuilt from ``asked``.
            asked: The asked call the yes approved.

        Returns:
            The runner's answer, or ``failed`` where no runner is held for the
            call's capability.
        """
        runner: object = self._runners.get(str(call.request.tool.capability))
        if isinstance(runner, ApprovedOwnRecordsCalls):
            return await runner.run_approved(call, asked)
        return await self.run(call)


@runtime_checkable
class ApprovedOwnRecordsCalls(Protocol):
    """An own-records runner that takes the asked call a yes approved (ADR-0321 §5:2).

    Orchestration-local, beside :class:`OwnRecordsCalls`. A call that runs under a yes
    was rebuilt from the question's asked call (§4:2), and a runner whose write the
    question bounds, as a remember's retirements are bounded by the assertions its
    question showed (§5:5), reads that asked call here. Acting hands it only the asked
    call :attr:`AuthorizedCall.asked` names.
    """

    async def run_approved(self, call: ToolCall, asked: AskedCall) -> OwnRecordsAnswer:
        """Run ``call``, approved by a yes to ``asked``, and say what the store answered.

        Args:
            call: The authorized call, its decision naming the approval.
            asked: The asked call the yes approved, which ``call`` was rebuilt from.

        Returns:
            What :meth:`OwnRecordsCalls.run` answers.
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
            one: where its capability's calls get one, and wherever the decision names
            an approval (ADR-0321 §4:10).
        deliberate_repeat: Whether planning marked the call a deliberate repeat.
        asked: The asked call an approved call was rebuilt from (ADR-0321 §4:2), as
            the round that asked recorded it; ``None`` for a call that does not run
            under a yes. A remember reads from it the assertions its question showed
            replaced (§5:2, §5:5).

    Raises:
        ValueError: If the decision's ``effect`` is set on a call that gets no record
            or missing on one that does; a call to a capability safe to repeat is
            marked a deliberate repeat, which §2:9 offers only where it is not; or an
            asked call rides on a call whose decision names no approved part, or
            another part than the asked call's.
    """

    call: ToolCall
    deliberate_repeat: bool = False
    asked: AskedCall | None = None

    def __post_init__(self) -> None:
        """Check the call against its declaration and its approval."""
        tool = self.call.request.tool
        decision = self.call.decision
        gets_one = gets_effect_record(tool) or decision.approval is not None
        if gets_one != (decision.effect is not None):
            msg = (
                "a call's decision names an effect record exactly where the call gets "
                "one (ADR-0306 §5:3, §5:8, ADR-0321 §4:10)"
            )
            raise ValueError(msg)
        if self.deliberate_repeat and tool.safe_to_repeat:
            msg = "only a call to a capability not safe to repeat is a deliberate repeat"
            raise ValueError(msg)
        if self.asked is not None:
            part = decision.approved_part
            if part is None or part.part != self.asked.part:
                msg = (
                    "an asked call rides only on the call its yes approved: the decision's "
                    "approved part is the asked call's (ADR-0321 §4:2, §4:9)"
                )
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
        outcome: Done, not done, unknown, or needs you.
        reason: Why it was not done, or why it needs you, in code-owned words; ``None``
            otherwise.
        output: What a done call returned for planning: its whole result, where it goes
            to planning whole, or what goes to planning of a read of the assistant's own
            records routed record by record (:class:`HeldByIds`); ``None`` otherwise.
            What goes to a digest is held instead, and never carried here (ADR-0308
            §6:5).
        route: Where a done call's result goes; ``None`` where there is none. A result
            a digest reads any part of is ``digest``.
        result_id: The id acting minted for a done call's result, which its R label
            names, or, for a follow-up, the id of the result it named; ``None`` where
            there is none.
        effect_id: The effect record the call was claimed under, where it was.
        replaces: For a call that needs you, the assertions its question shows it
            replacing, as stored (ADR-0321 §5:5); empty otherwise.

    Raises:
        ValueError: If ``replaces`` names an assertion on a call that does not need
            you.
    """

    call: AuthorizedCall
    outcome: ActedOutcome
    reason: str | None = None
    output: FrozenJsonValue = None
    route: ResultRoute | None = None
    result_id: str | None = None
    effect_id: str | None = None
    replaces: tuple[SemanticMemory, ...] = ()

    def __post_init__(self) -> None:
        """Only a call that needs you shows what it replaces (ADR-0321 §5:5)."""
        if self.replaces and self.outcome is not ActedOutcome.NEEDS_YOU:
            msg = "only a call that needs you carries the assertions it would replace"
            raise ValueError(msg)


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
        """Claim one detached call where it gets a record, run it, and finish the record.

        A call under an approval given to another activation is not done, and nothing is
        claimed or run: the yes's activation runs the calls it approved, and no other
        activation uses that approval (ADR-0321 §4:1).
        """
        call = one.call
        tool = call.request.tool
        effect_id = call.decision.effect
        approval = call.decision.approval
        if approval is not None and approval.given.activation_id != activation_id:
            _log.info("acting_call_not_done", stage="acting", reason="another_activations_yes")
            return ActedCall(one, ActedOutcome.NOT_DONE, reason=_ANOTHER_ACTIVATIONS)
        if effect_id is not None:
            record = ActivationEffect(
                id=effect_id,
                activation_id=activation_id,
                round=round_id,
                capability=tool.capability,
                values_digest=values_digest(call),
                decision_id=call.decision.id,
                claimed_at=self._now(),
                part=call.decision.approved_part,
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
            if answer is ActivationEffectClaim.ALREADY_USED:
                _log.info("acting_call_not_done", stage="acting", reason="already_used")
                return ActedCall(one, ActedOutcome.NOT_DONE, reason=_ALREADY_USED)
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
        """Run a call against the assistant's own records, then finish its record.

        A call rebuilt from an asked call reaches a seam that takes one with it.
        """
        if one.asked is not None and isinstance(self._own_records, ApprovedOwnRecordsCalls):
            answer = await self._own_records.run_approved(one.call, one.asked)
        else:
            answer = await self._own_records.run(one.call)
        if isinstance(answer, NeedsYou):
            return await self._needs_you(one, answer, effect_id)
        if isinstance(answer, NamedResult):
            return await self._followed_up(one, answer, effect_id, round_id, held)
        if isinstance(answer, HeldByIds):
            outside = tuple(str(one_id) for one_id in answer.outside)
            result = _detached_result(
                ToolResult(outcome=ToolOutcome.SUCCEEDED, output=answer.output)
            )
        else:
            outside = ()
            result = _detached_result(answer)
        if effect_id is not None:
            await self._finish(effect_id, result)
        if isinstance(answer, HeldByIds):
            return self._held_by_ids(one, result, outside, effect_id, round_id, held)
        return self._acted(one, result, effect_id, round_id, held)

    def _held_by_ids(  # noqa: PLR0913 — the call, what goes to planning, the ids held, and acting's three
        self,
        one: AuthorizedCall,
        result: ToolResult,
        outside: tuple[str, ...],
        effect_id: str | None,
        round_id: str,
        held: HeldResults,
    ) -> ActedCall:
        """A read of the assistant's own records, routed record by record (§5:14, §5:16).

        The result takes a minted id. What goes to planning is ``output``; the ids of the
        records whose source is outside are held under the result's id, for a digest to
        fetch, and never their contents (ADR-0308 §6:2). A capability not declared to
        carry outside text holds nothing: its result goes to planning whole, as any
        other result declared so does.
        """
        if one.call.request.tool.result is not CapabilityResult.MAY_CARRY_OUTSIDE_TEXT:
            return self._acted(one, result, effect_id, round_id, held)
        result_id = str(self._new_result_id())
        route = ResultRoute.PLANNING
        if outside:
            held.hold(
                HeldResult(
                    result_id=result_id,
                    round_id=round_id,
                    decision_id=one.call.decision.id,
                    content=None,
                    records=outside,
                )
            )
            route = ResultRoute.DIGEST
        return ActedCall(
            one,
            ActedOutcome.DONE,
            output=result.output,
            route=route,
            result_id=result_id,
            effect_id=effect_id,
        )

    async def _needs_you(
        self, one: AuthorizedCall, answer: NeedsYou, effect_id: str | None
    ) -> ActedCall:
        """A call that wrote nothing because it needs the user's yes (ADR-0321 §5:5).

        Its record is finished not done, since nothing happened, and the call is
        reported as needing you, with the assertions its question will show replaced.
        """
        replaces = tuple(
            SemanticMemory.model_validate(record.model_dump()) for record in answer.replaces
        )
        _log.info("acting_call_needs_you", stage="acting", reason="needs_you")
        if effect_id is not None:
            await self._plans.finish_activation_effect(
                effect_id, ToolOutcome.FAILED, reason=_NEEDS_YOU
            )
        return ActedCall(
            one,
            ActedOutcome.NEEDS_YOU,
            reason=_NEEDS_YOU,
            effect_id=effect_id,
            replaces=replaces,
        )

    async def _followed_up(
        self,
        one: AuthorizedCall,
        named: NamedResult,
        effect_id: str | None,
        round_id: str,
        held: HeldResults,
    ) -> ActedCall:
        """A follow-up, run against the held results (ADR-0308 §6:6-§6:7).

        The result it names, as held, is offered to a digest again under this call's
        decision, which answers the follow-up's *looking for*. Nothing is minted or held
        again, and the outcome names that result. Naming a result with nothing held is
        not done, with the reason.
        """
        result_id = str(named.result_id)
        offered = held.offer_again(result_id, round_id=round_id, decision_id=one.call.decision.id)
        if offered is None:
            _log.info("acting_call_not_done", stage="acting", reason="nothing_held")
            if effect_id is not None:
                await self._plans.finish_activation_effect(
                    effect_id, ToolOutcome.FAILED, reason=_NOTHING_HELD
                )
            return ActedCall(one, ActedOutcome.NOT_DONE, reason=_NOTHING_HELD, effect_id=effect_id)
        if effect_id is not None:
            await self._plans.finish_activation_effect(effect_id, ToolOutcome.SUCCEEDED)
        return ActedCall(
            one,
            ActedOutcome.DONE,
            route=ResultRoute.DIGEST,
            result_id=result_id,
            effect_id=effect_id,
        )

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
    """Revalidate and detach one call, as the old path's executor did before its claim.

    Rebuilt through validation, so nothing the caller still holds reaches what is
    claimed or invoked, and the call's own checks run again on the copy.

    Raises:
        ToolBindingError: If the call does not survive revalidation.
    """
    try:
        call = ToolCall.model_validate(one.call.model_dump())
        asked = None if one.asked is None else AskedCall.model_validate(one.asked.model_dump())
        return AuthorizedCall(call, deliberate_repeat=bool(one.deliberate_repeat), asked=asked)
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

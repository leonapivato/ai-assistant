"""The acting stage (ADR-0306 §5), driven directly over fakes.

Nothing runs it yet (ADR-0309 §2:6), so every case builds an
:class:`~ai_assistant.orchestration.acting.AuthorizedRound` by hand, as authorizing
will, and reads what came back and what the canonical ``FakePlanStore`` holds.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import AuditError, AuthorisationSpentError
from ai_assistant.core.types import (
    ActionRequest,
    ActivationEffect,
    ActivationEffectClaim,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import (
    ActedOutcome,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    ResultRoute,
    gets_effect_record,
    values_digest,
)
from ai_assistant.testing import FakePlanStore

if TYPE_CHECKING:
    from collections.abc import Callable

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def _now() -> datetime:
    return _AT


def _tool(name: str, **overrides: Any) -> ToolDefinition:
    """A declaration of one of the thin path's three kinds, by ``name``."""
    kinds: dict[str, dict[str, Any]] = {
        # A read that leaves the hub and may carry outside text; changes nothing.
        "lookup": {
            "side_effecting": False,
            "reversibility": Reversibility.REVERSIBLE,
            "idempotency": Idempotency.NATURAL,
            "effect": CapabilityEffect.NONE,
            "leaves_hub": True,
            "result": CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
            "outcome_can_be_unknown": False,
            "safe_to_repeat": True,
        },
        # A booking: in the world, not safe to repeat, its outcome can be unknown.
        "book": {
            "side_effecting": True,
            "reversibility": Reversibility.IRREVERSIBLE,
            "idempotency": Idempotency.NONE,
            "writes": (DataTier.PERSONAL,),
            "effect": CapabilityEffect.WORLD,
            "leaves_hub": True,
            "result": CapabilityResult.NO_OUTSIDE_TEXT,
            "outcome_can_be_unknown": True,
            "safe_to_repeat": False,
        },
        # Remembering: the assistant's own records, not safe to repeat, never unknown.
        "remember": {
            "side_effecting": True,
            "reversibility": Reversibility.RECOVERABLE,
            "idempotency": Idempotency.NONE,
            "writes": (DataTier.PERSONAL,),
            "effect": CapabilityEffect.OWN_RECORDS,
            "leaves_hub": False,
            "result": CapabilityResult.NONE,
            "outcome_can_be_unknown": False,
            "safe_to_repeat": False,
        },
    }
    fields: dict[str, Any] = {
        "id": name,
        "capability": name,
        "description": f"The {name} capability.",
        "risk_level": RiskLevel.LOW,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        **kinds[name],
    }
    fields.update(overrides)
    return ToolDefinition(**fields)


def _authorized(
    name: str,
    *,
    decision: str = "d1",
    effect: str | None = None,
    parameters: dict[str, Any] | None = None,
    deliberate_repeat: bool = False,
    **overrides: Any,
) -> AuthorizedCall:
    """One allowed call, with its decision naming ``effect`` where it gets a record."""
    tool = _tool(name, **overrides)
    request = ActionRequest(tool=tool, parameters=parameters or {"date": "2026-11-01"})
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    allowed = PermissionDecision.from_request(
        request, ruling, id=decision, decided_at=_AT, effect=effect
    )
    return AuthorizedCall(
        ToolCall(request=request, decision=allowed), deliberate_repeat=deliberate_repeat
    )


def _round(*calls: AuthorizedCall, stories: tuple[str, ...] = ()) -> AuthorizedRound:
    return AuthorizedRound(
        activation_id="act-1", round_id="r1", calls=calls, story_activations=stories
    )


class _Invoker:
    """A ``ToolInvoker`` stub answering each call with what ``answer`` returns."""

    def __init__(self, answer: Callable[[ToolCall], ToolResult] | None = None) -> None:
        self.calls: list[ToolCall] = []
        self._answer = answer or (lambda _: ToolResult(outcome=ToolOutcome.SUCCEEDED))
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
        assert timeout > timedelta(0)
        self.calls.append(call)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return self._answer(call)


class _OwnRecords:
    """An ``OwnRecordsCalls`` stub that can be held open mid-call."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self.release: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def run(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


def _stage(
    plans: FakePlanStore, invoker: _Invoker | None = None, own: _OwnRecords | None = None
) -> ActingStage:
    return ActingStage(
        plans=plans,
        invoker=invoker or _Invoker(),
        own_records=own or _OwnRecords(),
        timeout=timedelta(seconds=5),
        now=_now,
    )


# --- which calls get a record ------------------------------------------------------


def test_a_call_in_the_world_or_not_safe_to_repeat_gets_a_record() -> None:
    """§5:3: the world, and anything not safe to repeat; nothing else."""
    assert gets_effect_record(_tool("book"))
    assert gets_effect_record(_tool("remember"))
    assert not gets_effect_record(_tool("lookup"))


def test_a_decision_names_an_effect_exactly_where_the_call_gets_one() -> None:
    """§5:8: the record and the decision name each other, and only there."""
    with pytest.raises(ValueError, match="effect record"):
        _authorized("book")
    with pytest.raises(ValueError, match="effect record"):
        _authorized("lookup", effect="e1")


def test_only_a_call_not_safe_to_repeat_is_a_deliberate_repeat() -> None:
    """§2:9 offers the mark only where the capability is not safe to repeat."""
    with pytest.raises(ValueError, match="deliberate repeat"):
        _authorized("lookup", deliberate_repeat=True)


def test_the_values_digest_leaves_out_what_the_system_supplied() -> None:
    """§2:10: a ``system_supplied`` argument is not among the values compared."""
    plain = _authorized("book", effect="e1", parameters={"date": "2026-11-01"})
    keyed = _authorized(
        "book",
        effect="e1",
        parameters={"date": "2026-11-01", "client_ref": "x-1"},
        system_supplied=("client_ref",),
    )
    other = _authorized("book", effect="e1", parameters={"date": "2026-11-02"})

    assert values_digest(plain.call) == values_digest(keyed.call)
    assert values_digest(plain.call) != values_digest(other.call)


# --- running and recording -------------------------------------------------------


async def test_a_call_that_changes_nothing_runs_unclaimed_and_goes_to_a_digest() -> None:
    """§5:3, §5:14: no record; a result through the invoker is digested."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"a": 1}))

    acted = await _stage(plans, invoker).act(_round(_authorized("lookup")))

    (call,) = acted.calls
    assert (call.outcome, call.route, call.effect_id) == (
        ActedOutcome.DONE,
        ResultRoute.DIGEST,
        None,
    )
    assert call.output == {"a": 1}
    assert len(invoker.calls) == 1
    assert (await plans.export()).activation_effects == ()


async def test_a_call_in_the_world_is_claimed_and_finished() -> None:
    """§5:4, §5:5, §5:8: claimed before the invocation, finished with its outcome."""
    plans = FakePlanStore(now=_now)
    booking = _authorized("book", effect="e1")

    acted = await _stage(plans).act(_round(booking))

    (call,) = acted.calls
    assert (call.outcome, call.route, call.effect_id) == (
        ActedOutcome.DONE,
        ResultRoute.PLANNING,
        "e1",
    )
    (record,) = await plans.activation_effects(["act-1"])
    assert (record.id, record.decision_id, record.round) == ("e1", "d1", "r1")
    assert record.capability == "book"
    assert record.values_digest == values_digest(booking.call)
    assert record.outcome is ToolOutcome.SUCCEEDED


async def test_two_equal_calls_in_one_round_run_once() -> None:
    """§5's backstop: an unfinished claim counts as done, so the second is refused."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker()

    acted = await _stage(plans, invoker).act(
        _round(_authorized("book", effect="e1"), _authorized("book", decision="d2", effect="e2"))
    )

    assert sorted(one.outcome for one in acted.calls) == sorted(
        [ActedOutcome.DONE, ActedOutcome.NOT_DONE]
    )
    refused = next(one for one in acted.calls if one.outcome is ActedOutcome.NOT_DONE)
    assert refused.reason is not None
    assert "already done" in refused.reason
    assert len(invoker.calls) == 1


async def test_an_effect_done_in_the_matter_refuses_a_repeat_unless_deliberate() -> None:
    """§5:9: matched against the stories' activations; a deliberate repeat passes done."""
    plans = FakePlanStore(now=_now)
    earlier = AuthorizedRound(
        activation_id="act-0", round_id="r0", calls=(_authorized("book", effect="e0"),)
    )
    await _stage(plans).act(earlier)

    refused = await _stage(plans).act(
        _round(_authorized("book", decision="d1", effect="e1"), stories=("act-0",))
    )
    repeated = await _stage(plans).act(
        _round(
            _authorized("book", decision="d2", effect="e2", deliberate_repeat=True),
            stories=("act-0",),
        )
    )

    assert refused.calls[0].outcome is ActedOutcome.NOT_DONE
    assert repeated.calls[0].outcome is ActedOutcome.DONE


async def test_an_activation_in_no_story_is_matched_against_its_own_effects() -> None:
    """§5:9: another activation's effect, outside every story, does not refuse it."""
    plans = FakePlanStore(now=_now)
    await _stage(plans).act(
        AuthorizedRound(
            activation_id="act-0", round_id="r0", calls=(_authorized("book", effect="e0"),)
        )
    )

    acted = await _stage(plans).act(_round(_authorized("book", effect="e1")))

    assert acted.calls[0].outcome is ActedOutcome.DONE


async def test_a_stopped_activation_starts_nothing_it_must_claim() -> None:
    """§5:2: the stop refuses what is not yet claimed; an unclaimed call still runs."""
    plans = FakePlanStore(now=_now)
    await plans.record_stop("act-1")
    invoker = _Invoker()

    acted = await _stage(plans, invoker).act(
        _round(_authorized("book", effect="e1"), _authorized("lookup", decision="d2"))
    )

    booking, lookup = acted.calls
    assert booking.outcome is ActedOutcome.NOT_DONE
    assert booking.reason is not None
    assert "stopped" in booking.reason
    assert lookup.outcome is ActedOutcome.DONE
    assert [call.request.tool.id for call in invoker.calls] == ["lookup"]
    assert await plans.activation_effects(["act-1"]) == ()


async def test_a_failed_call_is_not_done_with_a_code_owned_reason() -> None:
    """§5:1: not done with its reason, which is the failure's kind and never its text."""
    plans = FakePlanStore(now=_now)
    failure = ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="provider said: secret")
    invoker = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.FAILED, failure=failure))

    acted = await _stage(plans, invoker).act(_round(_authorized("book", effect="e1")))

    (call,) = acted.calls
    assert call.outcome is ActedOutcome.NOT_DONE
    assert call.reason == "the call failed (unavailable)"
    (record,) = await plans.activation_effects(["act-1"])
    assert (record.outcome, record.reason) == (ToolOutcome.FAILED, call.reason)


async def test_an_unknown_outcome_is_recorded_and_never_retried() -> None:
    """§5:13: unknown is never retried, done another way, or reported as done."""
    plans = FakePlanStore(now=_now)
    failure = ToolFailure(kind=ToolFailureKind.TIMED_OUT, message="deadline")
    invoker = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.INDETERMINATE, failure=failure))

    acted = await _stage(plans, invoker).act(_round(_authorized("book", effect="e1")))

    assert acted.calls[0].outcome is ActedOutcome.UNKNOWN
    assert acted.calls[0].output is None
    assert len(invoker.calls) == 1
    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.INDETERMINATE


async def test_a_refusal_before_the_call_is_not_done() -> None:
    """The invocation seam's pre-callable refusals ran nothing, so the call is not done."""
    plans = FakePlanStore(now=_now)

    def spent(_: ToolCall) -> ToolResult:
        raise AuthorisationSpentError("spent")

    acted = await _stage(plans, _Invoker(spent)).act(_round(_authorized("book", effect="e1")))

    assert acted.calls[0].outcome is ActedOutcome.NOT_DONE
    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.FAILED


async def test_a_refusal_logs_no_class_name_it_did_not_author() -> None:
    """ADR-0004 §5, ADR-0192 §3: a collaborator's class name may carry content.

    A ledger can raise a dynamically named ``AuditError``; acting logs a code-owned
    reason and never that name.
    """
    leaking = type("recipient@example.com", (AuditError,), {})

    def refuse(_: ToolCall) -> ToolResult:
        raise leaking

    with capture_logs() as logs:
        acted = await _stage(FakePlanStore(now=_now), _Invoker(refuse)).act(
            _round(_authorized("book", effect="e1"))
        )

    assert acted.calls[0].outcome is ActedOutcome.NOT_DONE
    assert logs
    assert "recipient@example.com" not in repr(logs)


async def test_a_call_on_the_assistants_own_records_runs_directly() -> None:
    """§3:3: not through ``ToolInvoker``; claimed and finished like any other record."""
    plans = FakePlanStore(now=_now)
    invoker, own = _Invoker(), _OwnRecords()

    acted = await _stage(plans, invoker, own).act(_round(_authorized("remember", effect="e1")))

    (call,) = acted.calls
    assert (call.outcome, call.route, call.output) == (ActedOutcome.DONE, None, None)
    assert invoker.calls == []
    assert len(own.calls) == 1
    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.SUCCEEDED


async def test_a_call_on_the_assistants_own_records_is_awaited_to_its_end() -> None:
    """§3:3: no cancellation cuts it short; its record is finished before acting ends."""
    plans = FakePlanStore(now=_now)
    own = _OwnRecords()
    own.release = asyncio.Event()
    task = asyncio.ensure_future(
        _stage(plans, own=own).act(_round(_authorized("remember", effect="e1")))
    )
    await own.entered.wait()

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done(), "the call is still running, so acting has not ended"
    own.release.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.SUCCEEDED


async def test_a_cancelled_invocation_leaves_its_record_unfinished() -> None:
    """§5:6: acting cannot read what the ledger recorded, so it guesses nothing.

    The seam may have completed the call ``succeeded`` before the cancellation reached
    acting; writing an interrupted outcome would contradict it, and the finish is
    written once. The unfinished record counts as done for the backstop (§5:11).
    """
    plans = FakePlanStore(now=_now)
    invoker = _Invoker()
    invoker.release = asyncio.Event()
    task = asyncio.ensure_future(
        _stage(plans, invoker).act(_round(_authorized("book", effect="e1")))
    )
    await invoker.entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is None
    repeat = await _stage(plans).act(
        _round(_authorized("book", decision="d2", effect="e2", deliberate_repeat=True))
    )
    assert repeat.calls[0].outcome is ActedOutcome.NOT_DONE


class _RewritingPlanStore(FakePlanStore):
    """A plan store that runs ``during_claim`` while a claim is in flight."""

    def __init__(self, during_claim: Callable[[], None]) -> None:
        super().__init__(now=_now)
        self._during_claim = during_claim

    async def claim_activation_effect(
        self, effect: ActivationEffect, /, *, match: tuple[str, ...] | None, **rest: Any
    ) -> ActivationEffectClaim:
        self._during_claim()
        return await super().claim_activation_effect(effect, match=match, **rest)


async def test_the_call_claimed_is_the_call_invoked_whatever_the_caller_rewrites() -> None:
    """§5:8, §5:9: one detached snapshot is claimed, invoked and recorded.

    The caller's object is rewritten past ``frozen=True`` while the claim is in
    flight, as ADR-0018 §3 puts in the threat model; the invoker still receives the
    values the record's digest was taken over.
    """
    original = _authorized("book", effect="e1", parameters={"date": "2026-11-01"})
    other = _authorized("book", effect="e1", parameters={"date": "2026-11-02"})

    def rewrite() -> None:
        original.call.__dict__["request"] = other.call.request
        original.call.__dict__["decision"] = other.call.decision

    plans = _RewritingPlanStore(rewrite)
    invoker = _Invoker()
    expected = values_digest(original.call)

    await _stage(plans, invoker).act(_round(original))

    (invoked,) = invoker.calls
    assert invoked.request.parameters["date"] == "2026-11-01"
    (record,) = await plans.activation_effects(["act-1"])
    assert record.values_digest == expected == values_digest(invoked)


async def test_a_sibling_that_raises_does_not_abandon_a_claimed_call() -> None:
    """Every call finishes before the error leaves, so no claim is left behind."""
    plans = FakePlanStore(now=_now)

    def answer(call: ToolCall) -> ToolResult:
        if call.request.tool.id == "lookup":
            msg = "unexpected"
            raise RuntimeError(msg)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)

    with pytest.raises(RuntimeError, match="unexpected"):
        await _stage(plans, _Invoker(answer)).act(
            _round(_authorized("book", effect="e1"), _authorized("lookup", decision="d2"))
        )

    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.SUCCEEDED


def test_the_deadline_must_be_positive() -> None:
    """A zero deadline is no deadline the invocation seam accepts (ADR-0029 §4)."""
    with pytest.raises(ValueError, match="positive"):
        ActingStage(
            plans=FakePlanStore(),
            invoker=_Invoker(),
            own_records=_OwnRecords(),
            timeout=timedelta(0),
        )

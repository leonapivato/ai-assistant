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
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    Memory,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    QuestionPart,
    Reversibility,
    RiskLevel,
    ToolCall,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    YesToQuestion,
)
from ai_assistant.orchestration.acting import (
    ActedCall,
    ActedOutcome,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    HeldByIds,
    NamedResult,
    ResultRoute,
    gets_effect_record,
    values_digest,
)
from ai_assistant.orchestration.held_results import HeldResult, HeldResults
from ai_assistant.orchestration.remembering import NeedsYou
from ai_assistant.testing import FakePlanStore
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.orchestration.acting import OwnRecordsAnswer, OwnRecordsCalls

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


def _ids() -> Callable[[], str]:
    """Result ids minted in order: ``result:1``, ``result:2``…"""
    minted = iter(range(1, 1000))
    return lambda: f"result:{next(minted)}"


def _stage(
    plans: FakePlanStore, invoker: _Invoker | None = None, own: _OwnRecords | None = None
) -> ActingStage:
    return ActingStage(
        plans=plans,
        invoker=invoker or _Invoker(),
        own_records=own or _OwnRecords(),
        timeout=timedelta(seconds=5),
        now=_now,
        new_result_id=_ids(),
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
    """§5:3, §5:14: no record; a result through the invoker is held for its digest.

    ADR-0308 §6:1, §6:5: held under the id acting minted, as it arrived, and the outcome
    carries the id and never the content.
    """
    plans = FakePlanStore(now=_now)
    invoker = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.SUCCEEDED, output={"a": 1}))
    held = HeldResults()

    acted = await _stage(plans, invoker).act(held=held, authorized=_round(_authorized("lookup")))

    (call,) = acted.calls
    assert (call.outcome, call.route, call.effect_id, call.result_id) == (
        ActedOutcome.DONE,
        ResultRoute.DIGEST,
        None,
        "result:1",
    )
    assert call.output is None
    assert held.get("result:1") == HeldResult(
        result_id="result:1", round_id="r1", decision_id="d1", content={"a": 1}
    )
    assert len(invoker.calls) == 1
    assert (await plans.export()).activation_effects == ()


async def test_a_call_in_the_world_is_claimed_and_finished() -> None:
    """§5:4, §5:5, §5:8: claimed before the invocation, finished with its outcome."""
    plans = FakePlanStore(now=_now)
    booking = _authorized("book", effect="e1")

    acted = await _stage(plans).act(held=HeldResults(), authorized=_round(booking))

    (call,) = acted.calls
    assert (call.outcome, call.route, call.effect_id, call.result_id) == (
        ActedOutcome.DONE,
        ResultRoute.PLANNING,
        "e1",
        "result:1",
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
        held=HeldResults(),
        authorized=_round(
            _authorized("book", effect="e1"), _authorized("book", decision="d2", effect="e2")
        ),
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
    await _stage(plans).act(held=HeldResults(), authorized=earlier)

    refused = await _stage(plans).act(
        held=HeldResults(),
        authorized=_round(_authorized("book", decision="d1", effect="e1"), stories=("act-0",)),
    )
    repeated = await _stage(plans).act(
        held=HeldResults(),
        authorized=_round(
            _authorized("book", decision="d2", effect="e2", deliberate_repeat=True),
            stories=("act-0",),
        ),
    )

    assert refused.calls[0].outcome is ActedOutcome.NOT_DONE
    assert repeated.calls[0].outcome is ActedOutcome.DONE


async def test_an_activation_in_no_story_is_matched_against_its_own_effects() -> None:
    """§5:9: another activation's effect, outside every story, does not refuse it."""
    plans = FakePlanStore(now=_now)
    await _stage(plans).act(
        held=HeldResults(),
        authorized=AuthorizedRound(
            activation_id="act-0", round_id="r0", calls=(_authorized("book", effect="e0"),)
        ),
    )

    acted = await _stage(plans).act(
        held=HeldResults(), authorized=_round(_authorized("book", effect="e1"))
    )

    assert acted.calls[0].outcome is ActedOutcome.DONE


async def test_a_stopped_activation_starts_nothing_it_must_claim() -> None:
    """§5:2: the stop refuses what is not yet claimed; an unclaimed call still runs."""
    plans = FakePlanStore(now=_now)
    await plans.record_stop("act-1")
    invoker = _Invoker()

    acted = await _stage(plans, invoker).act(
        held=HeldResults(),
        authorized=_round(_authorized("book", effect="e1"), _authorized("lookup", decision="d2")),
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

    acted = await _stage(plans, invoker).act(
        held=HeldResults(), authorized=_round(_authorized("book", effect="e1"))
    )

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

    acted = await _stage(plans, invoker).act(
        held=HeldResults(), authorized=_round(_authorized("book", effect="e1"))
    )

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

    acted = await _stage(plans, _Invoker(spent)).act(
        held=HeldResults(), authorized=_round(_authorized("book", effect="e1"))
    )

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
            held=HeldResults(), authorized=_round(_authorized("book", effect="e1"))
        )

    assert acted.calls[0].outcome is ActedOutcome.NOT_DONE
    assert logs
    assert "recipient@example.com" not in repr(logs)


async def test_a_call_on_the_assistants_own_records_runs_directly() -> None:
    """§3:3: not through ``ToolInvoker``; claimed and finished like any other record."""
    plans = FakePlanStore(now=_now)
    invoker, own = _Invoker(), _OwnRecords()

    acted = await _stage(plans, invoker, own).act(
        held=HeldResults(), authorized=_round(_authorized("remember", effect="e1"))
    )

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
        _stage(plans, own=own).act(
            held=HeldResults(), authorized=_round(_authorized("remember", effect="e1"))
        )
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
        _stage(plans, invoker).act(
            held=HeldResults(), authorized=_round(_authorized("book", effect="e1"))
        )
    )
    await invoker.entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is None
    repeat = await _stage(plans).act(
        held=HeldResults(),
        authorized=_round(_authorized("book", decision="d2", effect="e2", deliberate_repeat=True)),
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

    await _stage(plans, invoker).act(held=HeldResults(), authorized=_round(original))

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
            held=HeldResults(),
            authorized=_round(
                _authorized("book", effect="e1"), _authorized("lookup", decision="d2")
            ),
        )

    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.SUCCEEDED


async def test_each_call_is_handed_back_as_it_finishes_where_a_sibling_raises() -> None:
    """ADR-0356 §8:6 (#3539): a call with no effect record that finished is handed back
    with what came of it, its route included, though its sibling made acting raise."""
    plans = FakePlanStore(now=_now)

    def answer(call: ToolCall) -> ToolResult:
        if call.request.tool.id == "book":
            msg = "unexpected"
            raise RuntimeError(msg)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED, output="page")

    handed: list[ActedCall] = []
    with pytest.raises(RuntimeError, match="unexpected"):
        await _stage(plans, _Invoker(answer)).act(
            held=HeldResults(),
            authorized=_round(
                _authorized("lookup"), _authorized("book", decision="d2", effect="e1")
            ),
            on_acted=handed.append,
        )

    (looked,) = handed
    assert looked.call.call.decision.id == "d1"
    assert (looked.outcome, looked.route) == (ActedOutcome.DONE, ResultRoute.DIGEST)


async def test_a_call_finished_before_a_cancellation_is_handed_back_once() -> None:
    """ADR-0356 §8:6 (#3539): a cancelled round still hands back each call that finished,
    and a call on the assistant's own records, awaited to its end through the
    cancellation, from inside that wait; each once."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.SUCCEEDED, output="page"))
    own = _OwnRecords()
    own.release = asyncio.Event()
    handed: list[ActedCall] = []
    task = asyncio.ensure_future(
        _stage(plans, invoker, own).act(
            held=HeldResults(),
            authorized=_round(
                _authorized("lookup"), _authorized("remember", decision="d2", effect="e1")
            ),
            on_acted=handed.append,
        )
    )
    await own.entered.wait()
    for _ in range(10):
        if handed:
            break
        await asyncio.sleep(0)
    assert [one.call.call.decision.id for one in handed] == ["d1"]

    task.cancel()
    await asyncio.sleep(0)
    own.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [(one.call.call.decision.id, one.outcome) for one in handed] == [
        ("d1", ActedOutcome.DONE),
        ("d2", ActedOutcome.DONE),
    ]


async def test_each_call_is_handed_back_once_on_a_round_that_returns() -> None:
    """Every call, the drained one included, is handed back once, beside the round."""
    plans = FakePlanStore(now=_now)
    handed: list[ActedCall] = []

    acted = await _stage(plans).act(
        held=HeldResults(),
        authorized=_round(
            _authorized("lookup"), _authorized("remember", decision="d2", effect="e1")
        ),
        on_acted=handed.append,
    )

    assert sorted(one.call.call.decision.id for one in handed) == ["d1", "d2"]
    by_decision = {one.call.call.decision.id: one for one in acted.calls}
    assert all(one is by_decision[one.call.call.decision.id] for one in handed)


# --- holding results (ADR-0308 §6) ------------------------------------------------


async def test_a_result_is_held_as_soon_as_its_call_is_recorded() -> None:
    """ADR-0308 §4:2, ADR-0309 §3:3: a digest may start before the round ends.

    The first call's result is held, and the holder told of it, while a sibling call
    of the same round is still running.
    """
    plans = FakePlanStore(now=_now)
    release = asyncio.Event()
    told: list[HeldResult] = []
    own = _OwnRecords()
    own.release = release
    held = HeldResults(on_hold=told.append)
    invoker = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.SUCCEEDED, output="page"))
    stage = _stage(plans, invoker, own)

    task = asyncio.create_task(
        stage.act(
            held=held,
            authorized=_round(
                _authorized("lookup"), _authorized("remember", decision="d2", effect="e1")
            ),
        )
    )
    await own.entered.wait()
    for _ in range(10):
        if told:
            break
        await asyncio.sleep(0)

    # The held result names its call, so its digest's question is found at once.
    assert [(one.content, one.decision_id) for one in told] == [("page", "d1")]
    assert not task.done()
    release.set()
    acted = await task
    assert [call.result_id for call in acted.calls] == ["result:1", None]


async def test_each_result_takes_its_own_id() -> None:
    """ADR-0308 §6:1: one id per result, each held under its own."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker(
        lambda call: ToolResult(outcome=ToolOutcome.SUCCEEDED, output=call.request.parameters["q"])
    )
    held = HeldResults()

    acted = await _stage(plans, invoker).act(
        held=held,
        authorized=_round(
            _authorized("lookup", parameters={"q": "first"}),
            _authorized("lookup", decision="d2", parameters={"q": "second"}),
        ),
    )

    ids = [call.result_id for call in acted.calls]
    assert sorted(str(one) for one in ids) == ["result:1", "result:2"]
    assert len(held) == 2
    assert {held.get(str(one)).content for one in ids if held.get(str(one))} == {  # type: ignore[union-attr]
        "first",
        "second",
    }


async def test_a_null_result_is_held_as_it_arrived() -> None:
    """§6:3: a result is held as its value came back, JSON ``null`` included."""
    plans = FakePlanStore(now=_now)
    held = HeldResults()

    acted = await _stage(plans).act(held=held, authorized=_round(_authorized("lookup")))

    assert acted.calls[0].route is ResultRoute.DIGEST
    assert held.get("result:1") == HeldResult(
        result_id="result:1", round_id="r1", decision_id="d1", content=None
    )


async def test_a_call_not_done_brings_no_result_and_holds_nothing() -> None:
    """A failed call is not done: no id is minted and nothing is held."""
    plans = FakePlanStore(now=_now)
    failed = ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="down"),
    )
    held = HeldResults()

    acted = await _stage(plans, _Invoker(lambda _: failed)).act(
        held=held, authorized=_round(_authorized("lookup"))
    )

    assert (acted.calls[0].outcome, acted.calls[0].result_id) == (ActedOutcome.NOT_DONE, None)
    assert len(held) == 0


async def test_a_capability_with_no_result_mints_no_id() -> None:
    """A result declared none brings nothing to name."""
    plans = FakePlanStore(now=_now)

    acted = await _stage(plans).act(
        held=HeldResults(), authorized=_round(_authorized("remember", effect="e1"))
    )

    assert acted.calls[0].result_id is None


async def test_an_own_records_result_that_may_carry_outside_text_is_held_whole() -> None:
    """§6:2's seam: no capability reports its outside records by id yet, so it is held whole."""
    plans = FakePlanStore(now=_now)
    held = HeldResults()

    acted = await _stage(plans).act(
        held=held,
        authorized=_round(
            _authorized(
                "remember",
                effect="e1",
                result=CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
            )
        ),
    )

    assert (acted.calls[0].route, acted.calls[0].output) == (ResultRoute.DIGEST, None)
    assert held.get("result:1") is not None


# --- a read of the assistant's own records, and the follow-up (ADR-0308 §6:2, §6:6-§6:7) ---


class _Answers:
    """An ``OwnRecordsCalls`` stub answering every call with ``answer``."""

    def __init__(self, answer: OwnRecordsAnswer) -> None:
        self.answer = answer
        self.calls: list[ToolCall] = []

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        self.calls.append(call)
        return self.answer


def _read(*, decision: str = "d1", result: CapabilityResult | None = None) -> AuthorizedCall:
    """A read of the assistant's own records, safe to repeat, that may carry outside text."""
    return _authorized(
        "remember",
        decision=decision,
        parameters={"query": "dentist"},
        safe_to_repeat=True,
        idempotency=Idempotency.NATURAL,
        result=result or CapabilityResult.MAY_CARRY_OUTSIDE_TEXT,
    )


def _acting(answer: OwnRecordsAnswer) -> ActingStage:
    return ActingStage(
        plans=FakePlanStore(now=_now),
        invoker=_Invoker(),
        own_records=_Answers(answer),
        timeout=timedelta(seconds=5),
        now=_now,
        new_result_id=_ids(),
    )


async def test_a_read_of_own_records_holds_its_outside_records_by_id() -> None:
    """ADR-0306 §5:16, ADR-0308 §6:2: what goes to planning, and the outside ids held.

    The result takes one minted id; the records whose source is outside are held by id
    under it, never their contents, and the holder is told of it for its digest.
    """
    told: list[HeldResult] = []
    held = HeldResults(on_hold=told.append)
    answer = HeldByIds(output={"records": ["said"]}, outside=("reported", "mailed"))

    acted = await _acting(answer).act(held=held, authorized=_round(_read()))

    (one,) = acted.calls
    assert (one.outcome, one.route, one.result_id) == (
        ActedOutcome.DONE,
        ResultRoute.DIGEST,
        "result:1",
    )
    assert one.output == {"records": ("said",)}
    expected = HeldResult(
        result_id="result:1",
        round_id="r1",
        decision_id="d1",
        content=None,
        records=("reported", "mailed"),
    )
    assert held.get("result:1") == expected
    assert told == [expected]


async def test_a_read_of_own_records_with_no_outside_record_goes_to_planning() -> None:
    """Nothing outside: nothing is held, and the whole answer goes to planning."""
    held = HeldResults()

    acted = await _acting(HeldByIds(output={"records": ["said"]})).act(
        held=held, authorized=_round(_read())
    )

    (one,) = acted.calls
    assert (one.route, one.result_id, one.output) == (
        ResultRoute.PLANNING,
        "result:1",
        {"records": ("said",)},
    )
    assert len(held) == 0


async def test_a_read_declared_to_carry_no_outside_text_holds_nothing() -> None:
    """Only a result declared to carry outside text is held by id (§5:14)."""
    held = HeldResults()
    answer = HeldByIds(output={"story": "s1"}, outside=("reported",))

    acted = await _acting(answer).act(
        held=held, authorized=_round(_read(result=CapabilityResult.NO_OUTSIDE_TEXT))
    )

    (one,) = acted.calls
    assert (one.route, one.output) == (ResultRoute.PLANNING, {"story": "s1"})
    assert len(held) == 0


async def test_a_follow_up_offers_the_result_it_names_again_as_held() -> None:
    """ADR-0308 §6:6-§6:7: the named result, as held, under the follow-up's decision.

    No id is minted and nothing is held again; the holder is told of the held result
    under the follow-up's round and decision, so its digest answers the new question.
    """
    told: list[HeldResult] = []
    held = HeldResults(on_hold=told.append)
    first = HeldResult(result_id="result:9", round_id="r0", decision_id="d0", content="page")
    held.hold(first)
    told.clear()

    acted = await _acting(NamedResult(result_id="result:9")).act(
        held=held, authorized=_round(_read())
    )

    (one,) = acted.calls
    assert (one.outcome, one.route, one.result_id, one.output) == (
        ActedOutcome.DONE,
        ResultRoute.DIGEST,
        "result:9",
        None,
    )
    assert told == [
        HeldResult(result_id="result:9", round_id="r1", decision_id="d1", content="page")
    ]
    assert len(held) == 1
    assert held.get("result:9") == first


async def test_a_follow_up_naming_a_result_with_nothing_held_is_not_done() -> None:
    """§6:7: not done, with the reason, and nothing offered to a digest."""
    told: list[HeldResult] = []
    held = HeldResults(on_hold=told.append)

    acted = await _acting(NamedResult(result_id="result:9")).act(
        held=held, authorized=_round(_read())
    )

    (one,) = acted.calls
    assert one.outcome is ActedOutcome.NOT_DONE
    assert one.reason is not None
    assert "nothing is held" in one.reason
    assert (one.route, one.result_id) == (None, None)
    assert told == []


def test_two_calls_of_a_round_never_share_a_decision() -> None:
    """A held result names its call by its decision, so a round's decisions are distinct."""
    with pytest.raises(ValueError, match="its own decision"):
        _round(_authorized("lookup"), _authorized("lookup", parameters={"q": "other"}))


async def test_a_round_rewritten_to_share_a_decision_runs_nothing() -> None:
    """The check runs again on the snapshot acting runs, before anything is claimed."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker()
    authorized = _round(_authorized("lookup"), _authorized("lookup", decision="d2"))
    object.__setattr__(authorized, "calls", (authorized.calls[0], authorized.calls[0]))

    with pytest.raises(ValueError, match="its own decision"):
        await _stage(plans, invoker).act(held=HeldResults(), authorized=authorized)

    assert invoker.calls == []


def test_a_result_id_is_held_once() -> None:
    """An id names one result for the whole activation."""
    held = HeldResults()
    held.hold(HeldResult(result_id="result:1", round_id="r1", decision_id="d1", content="a"))
    with pytest.raises(ValueError, match="one result"):
        held.hold(HeldResult(result_id="result:1", round_id="r2", decision_id="d1", content="b"))
    assert held.get("result:1") == HeldResult(
        result_id="result:1", round_id="r1", decision_id="d1", content="a"
    )
    assert held.get("result:2") is None


def test_the_deadline_must_be_positive() -> None:
    """A zero deadline is no deadline the invocation seam accepts (ADR-0029 §4)."""
    with pytest.raises(ValueError, match="positive"):
        ActingStage(
            plans=FakePlanStore(),
            invoker=_Invoker(),
            own_records=_OwnRecords(),
            timeout=timedelta(0),
        )


# --- ADR-0321 §4:9, §4:10, §6:2: a call that runs under an approval spends it -------


def _approval(*parts: int, yes: str = "act-1") -> Approval:
    """The approval a yes in activation ``yes`` made to the question round ``q1`` asked."""
    return Approval(
        who=ApprovalGiver.USER_THROUGH_HUB_CHAT,
        how=YesToQuestion(activation_id="act-0", round="q1"),
        covers=tuple(QuestionPart(round="q1", part=part) for part in parts or (1,)),
        given=ApprovalGiven(activation_id=yes, at=_AT),
        ends=ApprovalEnd.WHEN_USED,
    )


def _approved(  # noqa: PLR0913 — the call's name, its two ids, its part, its yes and its mark
    name: str,
    *,
    decision: str = "d1",
    effect: str | None = "e1",
    part: int = 1,
    yes: str = "act-1",
    deliberate_repeat: bool = False,
    **overrides: Any,
) -> AuthorizedCall:
    """One call allowed under an approval, its decision naming the approval and its part."""
    tool = _tool(name, **overrides)
    request = ActionRequest(tool=tool, parameters={"date": "2026-11-01"})
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    allowed = PermissionDecision.from_request(
        request,
        ruling,
        id=decision,
        decided_at=_AT,
        effect=effect,
        approval=_approval(part, yes=yes),
        approved_part=QuestionPart(round="q1", part=part),
    )
    return AuthorizedCall(
        ToolCall(request=request, decision=allowed), deliberate_repeat=deliberate_repeat
    )


async def test_a_call_under_an_approval_is_claimed_with_its_part_key() -> None:
    """§4:9: the record carries the asking round's id and the part number."""
    plans = FakePlanStore(now=_now)

    acted = await _stage(plans).act(held=HeldResults(), authorized=_round(_approved("book")))

    assert acted.calls[0].outcome is ActedOutcome.DONE
    (record,) = await plans.part_effects([QuestionPart(round="q1", part=1)])
    assert (record.id, record.decision_id) == ("e1", "d1")
    assert record.part == QuestionPart(round="q1", part=1)
    assert record.outcome is ToolOutcome.SUCCEEDED


async def test_every_call_under_an_approval_gets_a_record_whatever_its_capability() -> None:
    """§4:10: a read safe to repeat, which gets no record of its own, gets one here."""
    plans = FakePlanStore(now=_now)
    assert not gets_effect_record(_tool("lookup"))

    acted = await _stage(plans).act(held=HeldResults(), authorized=_round(_approved("lookup")))

    assert acted.calls[0].effect_id == "e1"
    (record,) = await plans.activation_effects(["act-1"])
    assert record.part == QuestionPart(round="q1", part=1)


def test_a_call_under_an_approval_naming_no_record_is_refused() -> None:
    """§4:10: an approval's decision names the record its call is claimed under."""
    with pytest.raises(ValueError, match="effect"):
        _approved("lookup", effect=None)


async def test_an_approval_given_to_another_activation_runs_nothing() -> None:
    """§4:1: no activation but the yes's own uses its approval; nothing is claimed."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker()

    acted = await _stage(plans, invoker).act(
        held=HeldResults(),
        authorized=AuthorizedRound(
            activation_id="act-2", round_id="r2", calls=(_approved("book"),)
        ),
    )

    assert acted.calls[0].outcome is ActedOutcome.NOT_DONE
    assert acted.calls[0].reason is not None
    assert "another activation" in acted.calls[0].reason
    assert invoker.calls == []
    assert await plans.activation_effects(["act-1", "act-2"]) == ()
    assert await plans.part_effects([QuestionPart(round="q1", part=1)]) == ()


async def test_a_second_yes_to_one_part_does_not_run_it_again() -> None:
    """§4:9, §8:1: a part is spent once, and its second claim comes back not done."""
    plans = FakePlanStore(now=_now)
    invoker = _Invoker()
    await _stage(plans, invoker).act(held=HeldResults(), authorized=_round(_approved("book")))

    again = await _stage(plans, invoker).act(
        held=HeldResults(),
        authorized=AuthorizedRound(
            activation_id="act-2",
            round_id="r2",
            calls=(_approved("book", decision="d2", effect="e2", yes="act-2"),),
        ),
    )

    assert again.calls[0].outcome is ActedOutcome.NOT_DONE
    assert again.calls[0].reason is not None
    assert again.calls[0].reason.startswith("already used")
    assert len(invoker.calls) == 1
    assert await plans.activation_effects(["act-2"]) == ()


async def test_a_deliberate_retry_under_an_approval_passes_an_unknown_outcome() -> None:
    """§6:2: the retry the user said yes to runs; the same retry with no yes does not."""
    plans = FakePlanStore(now=_now)
    failure = ToolFailure(kind=ToolFailureKind.TIMED_OUT, message="deadline")
    unknown = _Invoker(lambda _: ToolResult(outcome=ToolOutcome.INDETERMINATE, failure=failure))
    earlier = AuthorizedRound(
        activation_id="act-0", round_id="r0", calls=(_authorized("book", effect="e0"),)
    )
    await _stage(plans, unknown).act(held=HeldResults(), authorized=earlier)

    unapproved = await _stage(plans).act(
        held=HeldResults(),
        authorized=_round(
            _authorized("book", decision="d1", effect="e1", deliberate_repeat=True),
            stories=("act-0",),
        ),
    )
    approved = await _stage(plans).act(
        held=HeldResults(),
        authorized=_round(
            _approved("book", decision="d2", effect="e2", deliberate_repeat=True),
            stories=("act-0",),
        ),
    )

    assert unapproved.calls[0].outcome is ActedOutcome.NOT_DONE
    assert approved.calls[0].outcome is ActedOutcome.DONE


# --- ADR-0321 §5:5, #2845: a call that needs you --------------------------------------------


def _assertion() -> Memory:
    """An assertion a remember's question shows it replacing."""
    return memory("assertion:1", "never drinks coffee", said_support(when=_AT, added_at=_AT))


class _Approving:
    """An own-records seam answering ``answer``."""

    def __init__(self, answer: OwnRecordsAnswer | None = None) -> None:
        self.answer = answer or ToolResult(outcome=ToolOutcome.SUCCEEDED)
        self.run_calls: list[ToolCall] = []

    async def run(self, call: ToolCall) -> OwnRecordsAnswer:
        self.run_calls.append(call)
        return self.answer


def _over(plans: FakePlanStore, seam: OwnRecordsCalls) -> ActingStage:
    return ActingStage(
        plans=plans,
        invoker=_Invoker(),
        own_records=seam,
        timeout=timedelta(seconds=5),
        now=_now,
        new_result_id=_ids(),
    )


async def test_a_call_that_needs_you_is_reported_so_with_what_it_replaces() -> None:
    """§5:5: nothing was written, its record is finished not done, and it needs you."""
    plans = FakePlanStore(now=_now)
    seam = _Approving(NeedsYou(replaces=(_assertion(),)))

    acted = await _over(plans, seam).act(
        held=HeldResults(), authorized=_round(_authorized("remember", effect="e1"))
    )

    (one,) = acted.calls
    assert one.outcome is ActedOutcome.NEEDS_YOU
    assert one.replaces == (_assertion(),)
    assert one.reason is not None
    assert one.reason.startswith("needs you")
    assert (one.effect_id, one.result_id, one.route) == ("e1", None, None)
    (record,) = await plans.activation_effects(["act-1"])
    assert record.outcome is ToolOutcome.FAILED
    assert record.reason == one.reason


async def test_a_call_that_needs_you_carries_detached_records() -> None:
    """What the runner answered reaches planning revalidated, not as the runner's objects."""
    assertion = _assertion()
    seam = _Approving(NeedsYou(replaces=(assertion,)))

    acted = await _over(FakePlanStore(now=_now), seam).act(
        held=HeldResults(), authorized=_round(_authorized("remember", effect="e1"))
    )

    (shown,) = acted.calls[0].replaces
    assert shown == assertion
    assert shown is not assertion


async def test_an_approved_call_runs_through_the_seams_plain_run() -> None:
    """ADR-0361 §8:5: no asked call rides with an approved call; the seam runs it."""
    seam = _Approving()

    await _over(FakePlanStore(now=_now), seam).act(
        held=HeldResults(), authorized=_round(_approved("remember"))
    )

    assert len(seam.run_calls) == 1


def test_only_a_call_that_needs_you_carries_what_it_replaces() -> None:
    with pytest.raises(ValueError, match="needs you"):
        ActedCall(_authorized("remember", effect="e1"), ActedOutcome.DONE, replaces=(_assertion(),))

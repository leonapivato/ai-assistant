"""The engine's use of the composing stage: which passes owe an answer, and what fails.

ADR-0170 §10's obligations that are about the *engine* rather than the stage. The
stage's own — §5's rendering, §5a's attribution and exclusions, §8's closed set —
are in ``test_composing.py``; §6's rendering floor and its contradictory-provider
test are in ``tests/interfaces/test_cli.py``, where both halves of §6's guarantee
(the outcome and the rendered account) are reachable in one test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from test_engine import (
    CAPABILITY,
    PARAMETERS,
    PATIENT,
    Harness,
    OneStepPlanner,
    confirmable,
    tool,
)

from ai_assistant.core.errors import ModelUnavailableError
from ai_assistant.core.types import (
    ActionPlan,
    Disposition,
    Idempotency,
    PlanStep,
    Role,
    StepStatus,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import CurrentContext, Goal, MemoryRecord, Message

_ANSWER = "You prefer hiking, and I have not sent anything."


def _refusing(_messages: Sequence[Message]) -> str:
    """A provider whose call raises a ``ModelError`` — §8's first closed-set member."""
    msg = "the route is exhausted"
    raise ModelUnavailableError(msg)


def _wired(model: FakeModelProvider, **knobs: object) -> Harness:
    """A harness whose composing stage runs over ``model``."""
    return Harness(composing=ComposingStage(model=model), **knobs)  # type: ignore[arg-type]  # heterogeneous harness knobs


class _TwoStepPlanner(OneStepPlanner):
    """A planner producing two steps, so one of them is never driven (#242)."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        first = await super().plan(goal, context=context, memories=memories)
        later = PlanStep(
            id="step-2", intent="file the reply", capability="file_note", parameters=PARAMETERS
        )
        return first.model_copy(update={"steps": (*first.steps, later)})


def _prompt(model: FakeModelProvider) -> str:
    return next(one.content for one in model.calls[0].messages if one.role is Role.USER)


# --- the milestone shape: a request that needs no tool gets an answer ---------


async def test_a_turn_that_needs_no_tool_comes_back_with_an_answer() -> None:
    """Milestone 17's exit shape, at the engine boundary (ADR-0170 §1, §3).

    Before this the pipeline terminated in tool execution, so a request whose whole
    point was an answer had nowhere to land. ``reply`` is where it lands now.
    """
    harness = _wired(FakeModelProvider(_ANSWER), tools=(tool(),))

    outcome = await harness.engine.converse("what do you know about me?", timeout=PATIENT)

    assert outcome.reply == _ANSWER
    assert outcome.reply_degraded is False
    # And the step account is untouched by it: §6's floor is that the answer is
    # carried *beside* what happened, never in place of it.
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED


async def test_a_turn_whose_plan_had_no_step_still_owes_an_answer() -> None:
    """§4: ``step`` being ``None`` is not one of the three shapes that owe none."""
    harness = _wired(FakeModelProvider(_ANSWER), planner=_NoStep())

    outcome = await harness.engine.converse("hello", timeout=PATIENT)

    assert outcome.step is None
    assert outcome.reply == _ANSWER
    assert outcome.reply_degraded is False


class _NoStep(OneStepPlanner):
    """A planner producing an empty plan — a fake's shape, never production's."""

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        built = await super().plan(goal, context=context, memories=memories)
        return built.model_copy(update={"steps": ()})


# --- §5: the engine hands over what the stage may not infer ------------------


async def test_the_engine_hands_the_stage_the_steps_it_did_not_drive() -> None:
    """§5: "the stage is told which of the plan's steps were not driven".

    Computed by the engine from the step it actually drove, not worked out by the
    stage from the plan — which is the shape §5 refuses, and the one that would
    silently become wrong the day #242 lands and more than one step is driven.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, planner=_TwoStepPlanner(), tools=(tool(),))

    await harness.engine.converse("send it", timeout=PATIENT)

    lines = _prompt(model).splitlines()
    driven = next(line for line in lines if CAPABILITY in line)
    later = next(line for line in lines if "file_note" in line)
    assert "NOT DRIVEN AT ALL" not in driven
    assert "NOT DRIVEN AT ALL" in later


# --- §8: the passes that owe no answer originate no call at all --------------


async def test_a_park_originates_no_completion_at_all() -> None:
    """§4 and §8: a park owes no answer, so no prompt is assembled and none is spent.

    The provider double asserts it was **not called**, which is the whole of the
    obligation: a stage reached and then told not to answer would still have paid
    for the prompt, and ``reply_degraded`` would be the flag it set on the way out.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, tools=(confirmable(),))

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.AWAITING_CONFIRMATION
    assert model.calls == []
    assert outcome.reply is None
    assert outcome.reply_degraded is False


async def test_a_recovered_resume_originates_no_completion_at_all() -> None:
    """§4's second ``None`` shape: nothing was persisted to compose from.

    A confirmation reconstructed from durable state after a restart has no live
    turn — context and retrieved memories are ephemeral — so there is no material
    for a prompt. The park before it owes no answer either, so the double stays
    unused across the whole round trip.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, tools=(confirmable(),))
    await harness.engine.converse("send it", timeout=PATIENT)
    # The token is lost before it reached the adapter; the step is still durably
    # parked, so recovery re-mints one with no live turn behind it.
    harness.engine._parked.clear()
    pending = await harness.engine.pending_confirmations()

    resumed = await harness.engine.resume(pending[0].token, approved=True, timeout=PATIENT)

    assert resumed.turn is None
    assert model.calls == []
    assert resumed.reply is None
    assert resumed.reply_degraded is False


async def test_a_live_resume_composes_in_the_ordinary_way() -> None:
    """§4: "The resume that follows composes an answer in the ordinary way"."""
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert resumed.turn is not None
    assert len(model.calls) == 1
    assert resumed.reply == _ANSWER
    assert resumed.reply_degraded is False


async def test_one_completion_per_turn_and_no_more() -> None:
    """§8: the stage does not loop, does not re-call and does not re-plan."""
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, tools=(tool(),))

    await harness.engine.converse("send it", timeout=PATIENT)

    assert len(model.calls) == 1


# --- §8: degradation, and the side effect that has already happened ----------


async def test_a_model_error_degrades_the_turn_rather_than_raising() -> None:
    """§8: the two turn calls do not raise for a classified composition failure."""
    harness = _wired(FakeModelProvider(_refusing), tools=(tool(),))

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.reply_degraded is True
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED


async def test_a_blank_completion_degrades_rather_than_raising_a_validation_error() -> None:
    """§8: "The two turn calls never surface a pydantic ``ValidationError``".

    ``NonBlankEncodableText`` cannot hold a blank completion, so a naive
    implementation would raise one straight out of the engine. The stage classifies
    it instead.
    """
    harness = _wired(FakeModelProvider("   "), tools=(tool(),))

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.reply is None
    assert outcome.reply_degraded is True


async def test_a_committed_non_idempotent_send_survives_a_failing_composer() -> None:
    """§10's second marked obligation, and §8's whole argument for degrading.

    A turn can approve a non-idempotent tool, execute it successfully, commit its
    ``StepExecution`` durably — and only *then* have composition fail. Raising there
    would hand the caller an error and no outcome: no ``conversation_id``, no step
    account, no record of the send in the value they were given. The natural
    recovery from an error is to ask again, which re-plans and can perform the
    effect a second time; ``resume`` is no way back either, because the continuation
    is consumed once the step resolved. So the call **returns**.
    """
    harness = _wired(FakeModelProvider(_refusing), tools=(tool(idempotency=Idempotency.NONE),))

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    # It returned rather than raising, and it carries the whole account of the send.
    assert outcome.step is not None
    assert outcome.step.disposition is Disposition.EXECUTED
    named = next(one for one in outcome.step.state.steps if one.step_id == outcome.step.step_id)
    assert named.status is StepStatus.SUCCEEDED
    assert outcome.conversation_id is not None
    assert outcome.reply_degraded is True
    assert outcome.reply is None
    # And nothing re-executed: the effect happened exactly once.
    assert len(harness.invoker.invocations) == 1


async def test_a_degraded_composition_does_not_degrade_the_capture() -> None:
    """The three flags name three stages, and one failing says nothing about another."""
    harness = _wired(FakeModelProvider(_refusing), tools=(tool(),))

    outcome = await harness.engine.converse("send it", timeout=PATIENT)

    assert outcome.reply_degraded is True
    assert outcome.capture_degraded is False
    assert outcome.turn is not None
    assert outcome.turn.memory_degraded is False


async def test_a_defect_in_the_stage_propagates_out_of_the_turn_call() -> None:
    """§8's residual, at the engine boundary: a defect is not a degradation.

    "An unexpected exception raised by the stage's own code is a defect, not a
    composition failure, and it propagates." ADR-0170 §8 accepts the cost on the
    record — a defect landing after a committed step hands the caller an exception
    rather than the outcome — because a defect that surfaces is fixed, where a
    defect that degrades is paid for on every turn.
    """
    monkeypatched = _wired(FakeModelProvider(_ANSWER), tools=(tool(),))

    class _Broken:
        """A stage whose own code raises, standing in for a bug inside it."""

        async def compose(self, **_knobs: object) -> None:
            msg = "stance"
            raise KeyError(msg)

    monkeypatched.engine._composing = _Broken()  # type: ignore[assignment]  # a defect is being injected

    with pytest.raises(KeyError):
        await monkeypatched.engine.converse("send it", timeout=PATIENT)


# --- the engine's own inputs reach the stage ---------------------------------


async def test_the_turns_own_memories_and_context_reach_the_stage() -> None:
    """§2: the stage consumes no ``ContextProvider`` and no ``MemoryStore``.

    Its context and its memories are the ones the turn already assembled, reaching
    it as the ``TurnResult`` the turn produced. It performs no second assembly and
    no second retrieval, so what is in the prompt is what the turn saw.
    """
    model = FakeModelProvider(_ANSWER)
    harness = _wired(model, tools=(tool(),))

    outcome = await harness.engine.converse("what do you know about me?", timeout=PATIENT)

    assert outcome.turn is not None
    prompt = _prompt(model)
    assert "what do you know about me?" in prompt
    assert outcome.turn.context.now.isoformat() in prompt

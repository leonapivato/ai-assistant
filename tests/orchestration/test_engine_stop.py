"""ADR-0297 at the engine: a stop is a mark, then a record, and the pass ends stopped.

§6:6's engine arms, over the real :class:`~ai_assistant.orchestration.engine.Engine`
wired with seeded fakes. **Every stop here lands at a fixed point rather than in a
race**: a hook inside a fake store or seam calls ``stop_activation`` at exactly the
instant the arm is about — inside the claim's write before it applies, after it has
landed, inside the admission write, inside a stage — so the store's ordering decides
each case, as §2:10 has it, and nothing depends on scheduling.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from test_chat_reader import _answered as chat_answered
from test_chat_reader import _conversation as chat_conversation
from test_chat_reader import _GatedModel
from test_chat_reader import _harness as chat_harness
from test_chat_reader import _messages as chat_messages
from test_chat_reader import _said as chat_said
from test_chat_reader import _until as chat_until
from test_engine import (
    AT,
    PATIENT,
    Harness,
    OneStepPlanner,
    bound_binder,
    egress_confirmable,
    tool,
)

from ai_assistant.core.errors import (
    ActivationStoppedError,
    AuditError,
    ClassifiedToolError,
    ConversationStoreError,
    PermissionDeniedError,
    PlanningError,
)
from ai_assistant.core.types import (
    ActivationEnding,
    ActivationStop,
    AttemptPhase,
    AttemptState,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    Disposition,
    EpisodicMemory,
    MessageAuthor,
    NewConversation,
    PermissionDecision,
    PermissionOutcome,
    ProcessingReason,
    ProcessingStatus,
    StageOutcome,
    StepStatus,
    StepTransition,
    TextChannelPayload,
    ToolFailure,
    ToolFailureKind,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import active_state, admit_channel, admit_resume
from ai_assistant.orchestration.conversations import activation_ending
from ai_assistant.orchestration.engine import _stopped_failure
from ai_assistant.testing import (
    FakeMemoryStore,
    FakePlanStore,
    FakeRecipientGrantStore,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import ActionPlan, Conversation, ExecutionState, MemoryWrite

_ASKED: Final = "send the note"

#: When the recipient-grant store reads its clock, inside the grant the resume asks for.
_NOW: Final = AT + timedelta(hours=1)
_UNTIL: Final = AT + timedelta(days=1)


class _Stopping(FakePlanStore):
    """A plan store that stops the claiming activation at a fixed point of its claim.

    ``before`` stops it inside the claim's write, before the write applies — so the stop
    record lands first and the store refuses the claim. ``after`` stops it once the claim
    has landed — so the claim stands and the effect proceeds. Either way the stop names
    the id **the claim itself carries**, which is what proves the claim names its
    activation (ADR-0297 §2:2).
    """

    def __init__(self, *, before: bool = False, after: bool = False) -> None:
        super().__init__(now=lambda: AT)
        self.engine: Any = None
        self.before = before
        self.after = after
        self.answers: list[ActivationStop] = []
        self.named: list[str | None] = []
        self.claims = 0
        #: Once a claim has landed the plan can no longer be read, so the comparison a
        #: resume runs after its step was driven raises.
        self.unreadable_after_claim = False
        self.landed = False
        #: The claim's write faults — not a refusal — once the stop is given.
        self.fault_claim = False

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        if self.unreadable_after_claim and self.landed:
            msg = "the plan cannot be read"
            raise PlanningError(msg)
        return await super().get_plan(plan_id)

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        claiming = transition.to_status is StepStatus.RUNNING
        if claiming:
            self.claims += 1
            self.named.append(transition.activation_id)
        if claiming and self.before and transition.activation_id is not None:
            self.before = False
            self.answers.append(await self.engine.stop_activation(transition.activation_id))
            if self.fault_claim:
                msg = "the store cannot be written"
                raise PlanningError(msg)
        landed = await super().commit_transition(transition)
        if claiming:
            self.landed = True
        if claiming and self.after and transition.activation_id is not None:
            self.after = False
            self.answers.append(await self.engine.stop_activation(transition.activation_id))
        return landed


class _Counting:
    """A tool implementation that counts its calls and succeeds."""

    def __init__(self, *, takes: float = 0.0) -> None:
        self.calls = 0
        self.takes = takes
        self.finished_at: float | None = None

    async def __call__(self, parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        self.calls += 1
        if self.takes:
            await asyncio.sleep(self.takes)
        self.finished_at = asyncio.get_running_loop().time()


async def _episodes(memory: FakeMemoryStore) -> list[EpisodicMemory]:
    return [one for one in await memory.export() if isinstance(one, EpisodicMemory)]


def _ends(episode: EpisodicMemory) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    assert episode.processing_record is not None
    return [(e.stage, e.due, e.outcome) for e in episode.processing_record.stages]


def _stopped(episode: EpisodicMemory) -> None:
    """The record says a stop ended it: its reason, its status and its end entry."""
    record = episode.processing_record
    assert record is not None
    assert (record.status, record.reason) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.STOPPED,
    )
    assert record.stages[-1].stage is ControllerStage.END
    assert record.stages[-1].due is ControllerRule.STOPPED
    assert activation_ending(episode) is ActivationEnding.STOPPED


async def _only_episode(harness: Harness) -> EpisodicMemory:
    (episode,) = await _episodes(harness.memory)
    return episode


def _conversation_of(episode: EpisodicMemory) -> str:
    assert episode.processing_record is not None
    channel = episode.processing_record.trigger.channel
    assert channel is not None
    return channel.instance_id


async def _step_status(plans: FakePlanStore) -> StepStatus:
    export = await plans.export()
    (execution,) = export.executions
    (step,) = execution.steps
    return step.status


# --- §2: a stop during the drive refuses the next claim --------------------------------


async def test_a_stop_during_the_drive_refuses_the_claim_and_the_pass_ends_stopped() -> None:
    """§2:5, §2:10, §4:4, §4:9: the record lands first, so nothing is invoked."""
    plans = _Stopping(before=True)
    tool_handler = _Counting()
    harness = Harness(
        planner=OneStepPlanner(), plans=plans, tools=(tool(),), tool_handler=tool_handler
    )
    plans.engine = harness.engine

    with pytest.raises(ActivationStoppedError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert plans.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 0
    # The step keeps its entry status (ADR-0255 §3:22), and the claim was not retried.
    assert await _step_status(plans) is StepStatus.PENDING
    assert plans.claims == 1
    episode = await _only_episode(harness)
    _stopped(episode)
    assert episode.processing_record is not None
    # The claim named the activation the episode records (§2:2), and only it is fenced.
    assert plans.named == [episode.processing_record.activation_id]
    assert (await plans.export()).stopped_activations == (episode.processing_record.activation_id,)
    # The drive met `ClaimStopped` and failed after the mark; the stop's entry ends it.
    assert _ends(episode)[-2:] == [
        (ControllerStage.DRIVE, ControllerRule.PLAN_HAS_STEPS, StageOutcome.FAILED),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]
    # Nothing composed: no stage ran after the drive.
    assert ControllerStage.COMPOSE not in [stage for stage, _, _ in _ends(episode)]
    digest = await harness.engine.conversation(_conversation_of(episode))
    assert digest is not None
    assert not digest.state.working
    assert digest.state.last_ended is ActivationEnding.STOPPED


async def test_an_effect_claimed_before_the_stop_completes_and_records_its_outcome() -> None:
    """§2:10, §4:10-§4:11: the claim landed first, so the effect runs to its own end.

    **And it outlasts the pass's budget.** The planner spends the whole of it — the pass's
    deadline is moved to the instant the plan is returned, which is a controlled stand-in
    for a slow planner rather than a race against the clock — so the drive's claim, the
    stop and the call all come after the pass's deadline. The call still runs to its own
    end under its own per-attempt budget (ADR-0029 §4): a stop neither shortens nor
    lengthens any deadline, and what the effect owes — its disposal, the attempt's
    ``EXECUTE`` stamp — is written before the stage returns.
    """
    passes: list[Any] = []

    class _SpendsTheBudget(OneStepPlanner):
        async def plan(self, *args: Any, **kwargs: Any) -> Any:
            planned = await super().plan(*args, **kwargs)
            state = active_state()
            assert state is not None
            working = state.working
            working.deadline = asyncio.get_running_loop().time()  # type: ignore[attr-defined]  # the engine's own pass, typed object on the state
            passes.append(working)
            return planned

    plans = _Stopping(after=True)
    tool_handler = _Counting()
    harness = Harness(
        planner=_SpendsTheBudget(), plans=plans, tools=(tool(),), tool_handler=tool_handler
    )
    plans.engine = harness.engine

    with pytest.raises(ActivationStoppedError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    (working,) = passes
    deadline = working.deadline
    assert plans.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 1
    assert tool_handler.finished_at is not None
    assert tool_handler.finished_at >= deadline
    assert await _step_status(plans) is StepStatus.SUCCEEDED
    export = await plans.export()
    (attempt,) = export.attempts
    # The stop itself wrote nothing to the attempt: it stands where the drive left it.
    assert attempt.state is AttemptState.RUNNING
    assert attempt.phase is AttemptPhase.EXECUTE
    episode = await _only_episode(harness)
    _stopped(episode)
    assert _ends(episode)[-2:] == [
        (ControllerStage.DRIVE, ControllerRule.PLAN_HAS_STEPS, StageOutcome.DONE),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]


# --- §4: before the controller, and during a stage that then fails ---------------------


class _StopAtAdmission(FakeMemoryStore):
    """A memory store that stops the activation inside its episode's admission write."""

    def __init__(self) -> None:
        super().__init__(now=lambda: AT)
        self.engine: Any = None
        self.answers: list[ActivationStop] = []

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        state = active_state()
        if not self.answers and state is not None and state.activation_id is not None:
            self.answers.append(await self.engine.stop_activation(state.activation_id))
        return await super().write_atomic(writes)


async def test_a_stop_before_the_controller_is_entered_runs_no_stage_and_ends_stopped() -> None:
    """§4:1-§4:3: the mark is read before the rules, so no stage begins."""
    memory = _StopAtAdmission()
    planner = OneStepPlanner()
    harness = Harness(planner=planner, memory=memory, tools=(tool(),))
    memory.engine = harness.engine

    with pytest.raises(ActivationStoppedError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert memory.answers == [ActivationStop.STOPPED]
    episode = await _only_episode(harness)
    _stopped(episode)
    assert _ends(episode) == [(ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE)]
    assert (await harness.plans.export()).goals == ()


async def test_a_stop_during_a_stage_that_then_fails_ends_stopped_and_is_not_reraised() -> None:
    """§4:4: the stage's error is not re-raised; the turn call raises the stop instead."""
    harness = Harness(planner=OneStepPlanner())
    answers: list[ActivationStop] = []

    async def stops_then_fails(conversation_id: str | None) -> Conversation:
        del conversation_id
        state = active_state()
        assert state is not None
        assert state.activation_id is not None
        answers.append(await harness.engine.stop_activation(state.activation_id))
        msg = "the index cannot be written"
        raise ConversationStoreError(msg)

    harness.conversations.begin = stops_then_fails  # type: ignore[method-assign]

    with pytest.raises(ActivationStoppedError) as caught:
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    # Not re-raised: neither as itself nor as the cause of what the call raised.
    assert not isinstance(caught.value, ConversationStoreError)
    assert not isinstance(caught.value.__cause__, ConversationStoreError)
    assert answers == [ActivationStop.STOPPED]
    episode = await _only_episode(harness)
    _stopped(episode)
    assert _ends(episode) == [
        (
            ControllerStage.BEGIN_CONVERSATION,
            ControllerRule.CONVERSATION_UNRESOLVED,
            StageOutcome.FAILED,
        ),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]


# --- §3:7: a record that cannot be written --------------------------------------------


class _RefusingStops(_Stopping):
    async def record_stop(self, activation_id: str, /) -> None:
        del activation_id
        msg = "the plan store cannot be written"
        raise PlanningError(msg)

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        try:
            return await super().commit_transition(transition)
        except PlanningError as exc:
            if "cannot be written" not in str(exc):
                raise
            self.refused = True
            # §3:7: the stop raised; the claim is decided as though no stop were made.
            return await FakePlanStore.commit_transition(self, transition)


async def test_a_stop_whose_record_fails_raises_and_its_mark_stays_set() -> None:
    """§3:7: the stop raises the store's error, and the activation still ends stopped.

    The claim the walk was making is decided by the store as though no stop had been
    made — it lands — and the pass still ends with the stop's entry once the stage
    returns, the mark having been set first.
    """
    plans = _RefusingStops(before=True)
    plans.refused = False
    tool_handler = _Counting()
    harness = Harness(
        planner=OneStepPlanner(), plans=plans, tools=(tool(),), tool_handler=tool_handler
    )
    plans.engine = harness.engine

    with pytest.raises(ActivationStoppedError):
        await harness.engine.converse(_ASKED, timeout=PATIENT)

    assert plans.refused
    assert (await plans.export()).stopped_activations == ()
    assert tool_handler.calls == 1
    _stopped(await _only_episode(harness))


# --- §5: the two answers that write nothing --------------------------------------------


async def test_already_ended_and_no_such_activation_each_write_nothing() -> None:
    """§5:4-§5:5: neither marks, neither writes a stop record, neither moves an episode."""
    harness = Harness(planner=OneStepPlanner(), tools=(tool(),))
    await harness.engine.converse(_ASKED, timeout=PATIENT)
    before = await _episodes(harness.memory)
    (episode,) = before
    assert episode.processing_record is not None
    plans_before = await harness.plans.export()

    ended = await harness.engine.stop_activation(episode.processing_record.activation_id)
    unknown = await harness.engine.stop_activation("0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11")

    assert (ended, unknown) == (ActivationStop.ALREADY_ENDED, ActivationStop.NO_SUCH_ACTIVATION)
    assert await _episodes(harness.memory) == before
    after = await harness.plans.export()
    assert after.stopped_activations == ()
    assert after.model_dump(exclude={"exported_at"}) == plans_before.model_dump(
        exclude={"exported_at"}
    )


# --- §4: a resume stopped after its answer was recorded --------------------------------


def _resuming(plans: _Stopping) -> tuple[Harness, _Counting]:
    definition = egress_confirmable()
    tool_handler = _Counting()
    harness = Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        recipient_grants=FakeRecipientGrantStore(now=lambda: _NOW),
        plans=plans,
        tool_handler=tool_handler,
    )
    plans.engine = harness.engine
    return harness, tool_handler


async def _answered(harness: Harness) -> list[PermissionOutcome]:
    return [
        row.ruling.outcome
        for row in reversed(await harness.trail.export())
        if row.resolves is not None
    ]


async def test_a_resume_stopped_after_its_answer_returns_stopped_with_its_grant() -> None:
    """§4:14-§4:15: the answer was recorded, so the resume returns — no reply, its grant.

    The stop lands inside the resumed claim's write, so the store refuses the claim
    (``ClaimStopped``): nothing is invoked, the step stays parked, and the outcome
    carries what the answer established.
    """
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    plans.before = True

    resumed = await harness.engine.resume(
        parked.step.confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )

    assert plans.answers == [ActivationStop.STOPPED]
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.reply_degraded is False
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None
    assert await _answered(harness) == [PermissionOutcome.ALLOW]
    assert tool_handler.calls == 0
    assert await _step_status(plans) is StepStatus.AWAITING_APPROVAL
    resume_episode = [
        one
        for one in await _episodes(harness.memory)
        if one.processing_record is not None
        and one.processing_record.activation_id == plans.named[-1]
    ]
    (episode,) = resume_episode
    _stopped(episode)


async def test_a_resume_stopped_after_its_claim_landed_returns_the_executed_step() -> None:
    """§4:15: every other member as the resume established it, the step's outcome included."""
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    plans.after = True

    resumed = await harness.engine.resume(
        parked.step.confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )

    assert plans.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 1
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.reply_degraded is False
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is not None
    # No answer was delivered, so the attempt is not ended as answered.
    assert resumed.attempt_report is None
    export = await plans.export()
    (attempt,) = export.attempts
    assert attempt.state is not AttemptState.ENDED


class _StoppedWhileFailing:
    """A naturally idempotent tool whose first call is stopped and fails retryably.

    The stop names the id the resumed claim carried, so ADR-0029 §5 would retry the
    call and the retry's re-claim is the one the store refuses.
    """

    def __init__(self, plans: _Stopping) -> None:
        self.plans = plans
        self.calls = 0
        self.answers: list[ActivationStop] = []

    async def __call__(self, parameters: object, *, idempotency_key: str | None) -> None:
        del parameters, idempotency_key
        self.calls += 1
        if self.calls == 1:
            self.answers.append(await self.plans.engine.stop_activation(self.plans.named[-1]))
        raise ClassifiedToolError(
            ToolFailure(kind=ToolFailureKind.UNAVAILABLE, message="the upstream is down"),
            effect_may_have_committed=False,
        )


async def test_a_resume_whose_retry_reclaim_is_stopped_returns_the_failed_step() -> None:
    """§4:15: a refused **re-claim** keeps the step the first invocation committed.

    The stop lands during the first invocation, which fails retryably; the retry's
    re-claim names the stopped activation and is refused. The step ran once and is
    durably ``FAILED``, so the stopped resume reports it rather than ``step=None``.
    """
    plans = _Stopping()
    definition = egress_confirmable()
    tool_handler = _StoppedWhileFailing(plans)
    harness = Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        recipient_grants=FakeRecipientGrantStore(now=lambda: _NOW),
        plans=plans,
        tool_handler=tool_handler,
    )
    plans.engine = harness.engine
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    resumed = await harness.engine.resume(
        parked.step.confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )

    assert tool_handler.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 1, "the refused re-claim invoked nothing"
    assert plans.claims == 2, "the resumed claim, then the refused re-claim"
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is not None
    assert await _step_status(plans) is StepStatus.FAILED


class _FaultingReclaim(_Stopping):
    """A plan store whose second ``→ RUNNING`` write — a retry's re-claim — faults."""

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        if transition.to_status is StepStatus.RUNNING and self.claims == 1:
            self.claims += 1
            msg = "the store cannot be written"
            raise PlanningError(msg)
        return await super().commit_transition(transition)


async def test_a_stopped_resume_whose_retry_reclaim_faults_raises_and_never_says_nothing_ran() -> (
    None
):
    """§4 under reading B: past a landed claim, "acted on nothing" is not the engine's to say.

    The first invocation ran and committed a retryable failure, and the stop landed
    during it; the retry's re-claim then faults. The runner assembled no disposition, so
    the resume cannot say what the step did — and it ran once, so the resolution that
    acted on nothing would misstate an effect. The raise propagates, exactly as it does
    for an unstopped resume (#2711 owns whether either should return).
    """
    plans = _FaultingReclaim()
    definition = egress_confirmable()
    tool_handler = _StoppedWhileFailing(plans)
    harness = Harness(
        tools=(definition,),
        binder=bound_binder(definition),
        recipient_grants=FakeRecipientGrantStore(now=lambda: _NOW),
        plans=plans,
        tool_handler=tool_handler,
    )
    plans.engine = harness.engine
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None

    with pytest.raises(PlanningError, match="cannot be written"):
        await harness.engine.resume(
            parked.step.confirmation.token,
            approved=True,
            timeout=PATIENT,
            remember_recipients_until=_UNTIL,
        )

    assert tool_handler.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 1
    assert await _step_status(plans) is StepStatus.FAILED


# --- ADR-0295 §3, ADR-0297 §4: the conversation a stopped activation started from -------


async def _working(harness: Harness, conversation_id: str) -> str:
    """Wait for the conversation to show "working…" with an id, and return the id."""
    found: list[str] = []

    async def shown() -> bool:
        digest = await harness.engine.conversation(conversation_id)
        if digest is None or digest.state.activation_id is None:
            return False
        found.append(digest.state.activation_id)
        return True

    await chat_until(shown, what="the running activation's id")
    return found[-1]


async def test_a_stopped_chat_activation_writes_nothing_and_shows_stopped() -> None:
    """ADR-0295 §3:3-§3:4: no reply — even one already composed — and no *couldn't finish*.

    The stop lands while the composing stage runs, so the reply is composed; the
    controller reads the mark once that stage's result is in hand, ends the pass, and the
    adapter writes nothing at all. The current state then shows *stopped*.
    """
    composer = _GatedModel("Done.")
    harness = chat_harness(composer=composer)
    conversation = await chat_conversation(harness)
    await harness.engine.write_message(conversation, message=chat_said("m-1", "hi"))
    await asyncio.wait_for(composer.entered.wait(), timeout=5)
    running = await _working(harness, conversation)

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    composer.gate.set()

    async def idle() -> bool:
        digest = await harness.engine.conversation(conversation)
        return digest is not None and not digest.state.working

    await chat_until(idle, what="the stopped activation to end")
    written = await chat_messages(harness.conversation_store, conversation)
    assert [(one.author, one.text) for one in written] == [(MessageAuthor.USER, "hi")]
    digest = await harness.engine.conversation(conversation)
    assert digest is not None
    assert digest.state.last_ended is ActivationEnding.STOPPED
    (episode,) = await _episodes(harness.memory)
    _stopped(episode)
    assert episode.processing_record is not None
    assert episode.processing_record.activation_id == running


async def test_what_waited_behind_a_stopped_activation_is_then_taken_in() -> None:
    """ADR-0295 §3:6: a stop holds nothing back; the correction is answered after it."""
    composer = _GatedModel("Sunday it is.")
    harness = chat_harness(composer=composer)
    conversation = await chat_conversation(harness)
    await harness.engine.write_message(conversation, message=chat_said("m-1", "book it Saturday"))
    await asyncio.wait_for(composer.entered.wait(), timeout=5)
    running = await _working(harness, conversation)
    await harness.engine.write_message(conversation, message=chat_said("m-2", "actually Sunday"))

    assert await harness.engine.stop_activation(running) is ActivationStop.STOPPED
    composer.gate.set()

    written = await chat_answered(harness, conversation, 1)
    assert [(one.author, one.text) for one in written] == [
        (MessageAuthor.USER, "book it Saturday"),
        (MessageAuthor.USER, "actually Sunday"),
        (MessageAuthor.ASSISTANT, "Sunday it is."),
    ]
    episodes = await _episodes(harness.memory)
    stopped = [
        one
        for one in episodes
        if one.processing_record is not None and (one.processing_record.activation_id == running)
    ]
    (first,) = stopped
    _stopped(first)
    (second,) = [one for one in episodes if one is not first]
    assert activation_ending(second) is ActivationEnding.DONE
    # Each message was taken in by the activation that ran on it, and nothing waits.
    taken = await harness.conversation_store.taken_in(conversation, positions=[1, 2])
    assert taken[1] == running
    assert taken[2] == second.id.removeprefix("activation:")
    assert await harness.conversation_store.untaken_messages(conversation) == ()


async def test_a_stopped_resume_keeps_what_it_established_when_later_work_raises() -> None:
    """§4:15 over ADR-0235 §6:10: the answer was recorded, the step executed and the grant
    established, so a raise from the work the stop kept the resume from finishing — here
    the comparison's plan read — does not discard them: the resume returns them, stopped.
    """
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    plans.after = True
    plans.unreadable_after_claim = True

    resumed = await harness.engine.resume(
        parked.step.confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )

    assert plans.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 1
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None
    assert resumed.capture_degraded is True


async def test_a_resume_no_stop_reached_still_raises_what_its_later_work_raised() -> None:
    """The keep is the stop's alone: an unstopped resume raises as it always has."""
    plans = _Stopping()
    harness, _ = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    plans.unreadable_after_claim = True

    with pytest.raises(PlanningError, match="cannot be read"):
        await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)


def test_only_a_turn_call_is_answered_with_the_stop_and_a_resume_keeps_its_raise() -> None:
    """§4:9 is stated over a turn call; a resume's own raise stays intact (ADR-0275 §5:6).

    A resume raising before any answer was recorded raises what it raised — which is what
    tells its caller the park still stands — whether or not its activation was stopped.
    """
    channel = admit_channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi")),
        WholeTextReply(),
        clock=lambda: AT,
        id_factory=lambda: "0b8f8f0e-2a5c-4c55-9a6c-6a2c1f0b0d11",
    )
    control = admit_resume(
        approved=True,
        remember_recipients_until=None,
        clock=lambda: AT,
        id_factory=lambda: "5d1c7a3e-9b0f-4f6a-8c2d-1e3f5a7b9c0d",
    )
    raised = PlanningError("refused before any answer")
    cancelled = asyncio.CancelledError()
    for state in (channel, control):
        assert _stopped_failure(state, raised) is raised
        assert state.stop()
        assert _stopped_failure(state, cancelled) is cancelled
    assert isinstance(_stopped_failure(channel, raised), ActivationStoppedError)
    assert isinstance(_stopped_failure(channel, None), ActivationStoppedError)
    assert _stopped_failure(control, raised) is raised
    assert _stopped_failure(control, None) is None


async def test_a_stopped_resume_whose_claim_write_faults_returns_with_the_park_standing() -> None:
    """ADR-0297 §4 past the recorded answer, inside the resolution: the claim's write
    faults after the stop, so nothing executed — the resume returns stopped, no step, the
    grant it established, and the drive's failure recorded before the stop's end entry.
    """
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    plans.before = True
    plans.fault_claim = True

    resumed = await harness.engine.resume(
        parked.step.confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )

    assert plans.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 0
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.step is None
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None
    assert await _step_status(plans) is StepStatus.AWAITING_APPROVAL
    (episode,) = [
        one
        for one in await _episodes(harness.memory)
        if one.processing_record is not None
        and one.processing_record.activation_id == plans.named[-1]
    ]
    _stopped(episode)
    assert _ends(episode) == [
        (ControllerStage.DRIVE, ControllerRule.PARK_ANSWERED, StageOutcome.FAILED),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]


async def test_a_stopped_resume_whose_bookkeeping_faults_after_executing_keeps_the_step() -> None:
    """The step executed and its disposition was assembled; the bookkeeping after it — the
    quote mint — then raised. The resume returns the executed step, stopped, its grant
    established, and the write that faulted is not retried.
    """
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    plans.after = True
    mints: list[object] = []

    async def faulting(*args: object) -> None:
        mints.append(args)
        msg = "the quote cannot be recorded"
        raise PlanningError(msg)

    harness.engine._runner._mint_quote = faulting  # type: ignore[method-assign,assignment]

    resumed = await harness.engine.resume(
        parked.step.confirmation.token,
        approved=True,
        timeout=PATIENT,
        remember_recipients_until=_UNTIL,
    )

    assert plans.answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 1
    assert len(mints) == 1
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.step is not None
    assert resumed.step.disposition is Disposition.EXECUTED
    assert resumed.recipient_grant is not None
    assert resumed.recipient_grant.established is not None
    assert await _step_status(plans) is StepStatus.SUCCEEDED
    (episode,) = [
        one
        for one in await _episodes(harness.memory)
        if one.processing_record is not None
        and one.processing_record.activation_id == plans.named[-1]
    ]
    _stopped(episode)
    assert _ends(episode) == [
        (ControllerStage.DRIVE, ControllerRule.PARK_ANSWERED, StageOutcome.FAILED),
        (ControllerStage.END, ControllerRule.STOPPED, StageOutcome.DONE),
    ]
    # ADR-0198 §3: the runner raised, so the park was not settled — the token is not
    # restated as a settled answer; presenting it again meets the step it no longer parks.
    with pytest.raises(PermissionDeniedError):
        await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)
    assert tool_handler.calls == 1


def _unread_answers(harness: Harness, answers: list[ActivationStop]) -> list[str]:
    """Make the trail accept the resolving answer and fail its read-back, stopping first.

    Returns the ids of the resolving answers the trail accepted.
    """
    record, get = harness.trail.record, harness.trail.get
    resolving: list[str] = []

    async def recording(decision: PermissionDecision) -> Any:
        if decision.resolves is not None:
            resolving.append(decision.id)
        return await record(decision)

    async def reading(decision_id: str) -> PermissionDecision | None:
        if decision_id in resolving:
            state = active_state()
            assert state is not None
            assert state.activation_id is not None
            answers.append(await harness.engine.stop_activation(state.activation_id))
            msg = "the trail cannot be read"
            raise AuditError(msg)
        return await get(decision_id)

    harness.trail.record = recording  # type: ignore[method-assign]
    harness.trail.get = reading  # type: ignore[method-assign]
    return resolving


async def test_a_stopped_resume_whose_answer_was_written_and_not_read_back_returns() -> None:
    """The answer's append returned, so the user's answer is spent (ADR-0044 §2b); the
    trail's read-back then failed, so nothing is acted on under it (ADR-0037 §3). A
    stopped resume that collected no standing request returns — no step, nothing
    executed, no reply, and no carrier, which is true: none was asked for.
    """
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    answers: list[ActivationStop] = []
    resolving = _unread_answers(harness, answers)

    resumed = await harness.engine.resume(
        parked.step.confirmation.token, approved=True, timeout=PATIENT
    )

    assert answers == [ActivationStop.STOPPED]
    assert len(resolving) == 1
    assert tool_handler.calls == 0
    assert resumed.stopped is True
    assert resumed.reply is None
    assert resumed.step is None
    assert resumed.recipient_grant is None
    assert await _step_status(plans) is StepStatus.AWAITING_APPROVAL


async def test_a_stopped_resume_that_cannot_say_what_became_of_its_request_raises() -> None:
    """Where a standing request was collected and its answer was not read back, no
    carrier ADR-0235 §4 admits is true — the grant may only be transcribed from the
    trail's read-back, and no member names this end — so the resume raises as an
    unstopped one does rather than returning silent about the request (§6).
    """
    plans = _Stopping()
    harness, tool_handler = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    answers: list[ActivationStop] = []
    _unread_answers(harness, answers)

    with pytest.raises(AuditError, match="cannot be read"):
        await harness.engine.resume(
            parked.step.confirmation.token,
            approved=True,
            timeout=PATIENT,
            remember_recipients_until=_UNTIL,
        )

    assert answers == [ActivationStop.STOPPED]
    assert tool_handler.calls == 0
    assert await harness.recipient_grants.export() == []


async def test_a_resume_no_stop_reached_still_raises_a_failed_read_back() -> None:
    """The keep is the stop's alone: unstopped, a failed read-back raises as it always has."""
    plans = _Stopping()
    harness, _ = _resuming(plans)
    parked = await harness.engine.converse("send it to the address in the invite", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    get = harness.trail.get

    async def reading(decision_id: str) -> PermissionDecision | None:
        found = await get(decision_id)
        if found is not None and found.resolves is not None:
            msg = "the trail cannot be read"
            raise AuditError(msg)
        return found

    harness.trail.get = reading  # type: ignore[method-assign]

    with pytest.raises(AuditError, match="cannot be read"):
        await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)

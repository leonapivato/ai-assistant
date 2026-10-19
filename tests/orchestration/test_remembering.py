"""The remember capability (ADR-0306 §3:2, §3:3) and acting's own-records seam, filled."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from test_activation_state import _admitted

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionRequest,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    AskedCall,
    CapabilityEffect,
    CapabilityResult,
    ConfirmationPart,
    ConflictRelation,
    EpisodicMemory,
    Memory,
    MemoryChange,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemoryOperationKind,
    MemoryRecord,
    MemorySource,
    MemoryStanding,
    MemoryUpdateProposal,
    MemoryWriterName,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    QuestionPart,
    ReadingCertainty,
    RememberCallPart,
    SupportDirection,
    SupportOrigin,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    UserConfirmation,
    YesToQuestion,
)
from ai_assistant.memory import DefaultMemoryPolicy
from ai_assistant.orchestration.acting import OwnRecordsByCapability
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    EpisodeProgress,
)
from ai_assistant.orchestration.planning import DELIBERATE_REPEAT, offered_tools
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER,
    STATEMENT_ARGUMENT,
    NeedsYou,
    RememberCalls,
    remembered_proposal,
    remembered_record_id,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter
from ai_assistant.testing.memories import memory, remembered_support, said_support

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_EPISODE: Final = "activation:act-1"


def _now() -> datetime:
    return _AT


def _arguments(statement: str = "likes green tea", *, outside: bool = False) -> dict[str, Any]:
    return {
        STATEMENT_ARGUMENT: statement,
        EPISODE_ARGUMENT: _EPISODE,
        OUTSIDE_CONTENT_ARGUMENT: outside,
    }


def _call(
    arguments: dict[str, Any] | None = None,
    *,
    effect: str | None = "effect:1",
    tool: Any = REMEMBER,
) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=arguments or _arguments())
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request, ruling, id="decision:1", decided_at=_AT, effect=effect
    )
    return ToolCall(request=request, decision=decision)


# --- the declaration ------------------------------------------------------------------------


def test_remembering_is_declared_as_ruled() -> None:
    """§3:2: own records, never leaves the hub, returns none, never unknown, not repeatable."""
    assert REMEMBER.effect is CapabilityEffect.OWN_RECORDS
    assert REMEMBER.leaves_hub is False
    assert REMEMBER.result is CapabilityResult.NONE
    assert REMEMBER.outcome_can_be_unknown is False
    assert REMEMBER.safe_to_repeat is False
    assert REMEMBER.system_supplied == (EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT)


def test_planning_is_offered_the_statement_and_the_mark_and_never_what_the_hub_fills() -> None:
    """ADR-0306 §2:9 to §2:10, ADR-0254 §3."""
    (offered,) = offered_tools([REMEMBER])

    properties = offered.parameters["properties"]
    assert isinstance(properties, Mapping)
    assert set(properties) == {STATEMENT_ARGUMENT, DELIBERATE_REPEAT}
    assert list(offered.parameters["required"]) == [STATEMENT_ARGUMENT]  # type: ignore[arg-type]  # a JSON array


# --- the proposal ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outside", "origin"),
    [(False, SupportOrigin.REMEMBERED), (True, SupportOrigin.REMEMBERED_OVER_OUTSIDE)],
)
def test_the_proposal_is_an_inference_resting_on_the_remember_call(
    *, outside: bool, origin: SupportOrigin
) -> None:
    """ADR-0328 §13:2: one support on the call, set by rule, never the user's word."""
    proposal = remembered_proposal(
        _arguments(outside=outside), record_id="remembered:effect:1", at=_AT
    )

    record = proposal.proposed
    assert record.id == "remembered:effect:1"
    assert record.content == "likes green tea"
    (support,) = record.supports
    assert support.points_at == RememberCallPart(episode=_EPISODE, effect="effect:1")
    assert support.origin is origin
    assert support.direction is SupportDirection.FOR
    assert support.backs_as_worded is True
    assert support.how_sure is None
    assert support.added_at == _AT
    assert support.added_by is MemoryWriterName.REMEMBER
    # No activation is current, so the episode's `occurred_at` is not to hand.
    assert support.when is None
    (create,) = record.operations
    assert (create.kind, create.cites, create.by) == (
        MemoryOperationKind.CREATE,
        support.points_at,
        MemoryWriterName.REMEMBER,
    )
    assert record.standing is MemoryStanding.INFERENCE
    assert record.rests_on_outside_content is outside


def test_the_support_is_dated_at_the_episode_s_occurred_at() -> None:
    """ADR-0328 §13:2: its ``when`` is the episode's ``occurred_at``, the capture's instant."""
    state = _admitted()
    occurred = datetime(2026, 10, 11, 11, 59, tzinfo=UTC)
    state.capture = EpisodeProgress(address=_EPISODE, captured_at=occurred)
    token = CURRENT_ACTIVATION.set(ActivationScope(state))
    try:
        proposal = remembered_proposal(_arguments(), record_id="remembered:effect:1", at=_AT)
        elsewhere = remembered_proposal(
            {**_arguments(), EPISODE_ARGUMENT: "activation:other"},
            record_id="remembered:effect:1",
            at=_AT,
        )
    finally:
        CURRENT_ACTIVATION.reset(token)

    assert proposal.proposed.supports[0].when == occurred
    assert elsewhere.proposed.supports[0].when is None


@pytest.mark.parametrize(
    "arguments",
    [
        {**_arguments(), STATEMENT_ARGUMENT: "  "},
        {**_arguments(), STATEMENT_ARGUMENT: 3},
        {STATEMENT_ARGUMENT: "x", OUTSIDE_CONTENT_ARGUMENT: False},
        {STATEMENT_ARGUMENT: "x", EPISODE_ARGUMENT: _EPISODE, OUTSIDE_CONTENT_ARGUMENT: "no"},
    ],
)
def test_a_malformed_call_makes_no_proposal(arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="remember call"):
        remembered_proposal(arguments, record_id="r", at=_AT)


# --- the runner -----------------------------------------------------------------------------


async def _runner(
    kind: MemoryDecisionKind = MemoryDecisionKind.ACCEPT,
) -> tuple[RememberCalls, FakeMemoryStore]:
    """The runner over a real fake writer, with the episode the belief cites in its store."""
    store = FakeMemoryStore(now=_now)
    await store.add(
        EpisodicMemory(
            id=_EPISODE,
            content="",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
            occurred_at=_AT,
        )
    )
    writer = FakeMemoryWriter(store=store, policy=FakeMemoryPolicy(kind), now=_now)
    return RememberCalls(writer=writer, now=_now), store


async def test_a_remember_call_writes_its_belief_at_the_derived_id() -> None:
    runner, store = await _runner()

    result = await runner.run(_call())

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output is None
    written = await store.get(remembered_record_id("effect:1"))
    assert isinstance(written, Memory)
    assert written.content == "likes green tea"


@pytest.mark.parametrize(
    ("planned_over_withheld", "placed"),
    [
        pytest.param(False, Placement(), id="a clean supply: anyone"),
        pytest.param(
            True,
            Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT),
            id="a supply holding withheld content: the owner",
        ),
    ],
)
async def test_the_belief_is_placed_by_the_supply_its_round_was_planned_over(
    *, planned_over_withheld: bool, placed: Placement
) -> None:
    """ADR-0217 §3:12, ADR-0204 §5:2: the current activation's round decides the reach."""
    runner, store = await _runner()
    state = _admitted()
    state.planned_over_withheld = planned_over_withheld
    token = CURRENT_ACTIVATION.set(ActivationScope(state))
    try:
        result = await runner.run(_call())
    finally:
        CURRENT_ACTIVATION.reset(token)

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.SUCCEEDED
    written = await store.get(remembered_record_id("effect:1"))
    assert written is not None
    assert written.placement == placed


async def test_a_belief_remembered_with_no_current_activation_has_the_default_placement() -> None:
    """No activation is current, so no supply was given: the default (ADR-0204 §1:3)."""
    runner, store = await _runner()

    await runner.run(_call())

    written = await store.get(remembered_record_id("effect:1"))
    assert written is not None
    assert written.placement == Placement()


def test_the_proposal_carries_the_placement_it_is_given_and_the_default_otherwise() -> None:
    """The placement is the runner's, set by rule; authorizing's proposal carries none."""
    narrowed = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT)

    given = remembered_proposal(_arguments(), record_id="r", at=_AT, placement=narrowed)
    default = remembered_proposal(_arguments(), record_id="r", at=_AT)

    assert given.proposed.placement == narrowed
    assert default.proposed.placement == Placement()


async def test_a_writer_that_rejects_writes_nothing_and_is_not_done() -> None:
    """ADR-0306 §4:3: a reject is not done, and nothing is written."""
    runner, store = await _runner(MemoryDecisionKind.REJECT)

    result = await runner.run(_call())

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.REFUSED
    assert await store.get(remembered_record_id("effect:1")) is None


async def test_a_writer_that_asks_writes_nothing_and_the_call_needs_you() -> None:
    """ADR-0321 §5:5, #2845: an ask at write time needs you, never not done."""
    runner, store = await _runner(MemoryDecisionKind.ASK_USER)

    result = await runner.run(_call())

    assert result == NeedsYou(replaces=())
    assert await store.get(remembered_record_id("effect:1")) is None


async def test_a_tainted_statement_is_not_written_unconfirmed() -> None:
    """ADR-0106 §6, at the writer's ruling as at authorizing's: it needs you."""
    runner, store = await _runner()

    result = await runner.run(_call(_arguments(outside=True)))

    assert result == NeedsYou(replaces=())
    assert await store.get(remembered_record_id("effect:1")) is None


async def test_a_call_that_is_not_a_claimed_remember_call_is_not_done() -> None:
    runner, _ = await _runner()
    other = REMEMBER.model_copy(update={"id": "other", "capability": "other"})

    unclaimed = await runner.run(_call(effect=None))
    misrouted = await runner.run(_call(tool=other))

    for result in (unclaimed, misrouted):
        assert isinstance(result, ToolResult)
        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INVALID_REQUEST


class _FailingWriter:
    """A ``MemoryWriter`` whose store is gone."""

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        del proposal
        msg = "the store is gone"
        raise MemoryStoreError(msg)

    async def apply(self, change: MemoryChange) -> None:
        del change
        msg = "the store is gone"
        raise MemoryStoreError(msg)


async def test_a_write_that_fails_is_not_done() -> None:
    """§3:3: the outcome is what the store answered, and never unknown."""
    result = await RememberCalls(writer=_FailingWriter(), now=_now).run(_call())

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INTERNAL


# --- acting's own-records seam, filled ------------------------------------------------------


class _Runner:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def run(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


async def test_each_call_reaches_its_capabilitys_runner_and_no_other() -> None:
    runner = _Runner()
    runners = {"remember": runner}
    seam = OwnRecordsByCapability(runners)
    runners.clear()

    held = await seam.run(_call())
    other = REMEMBER.model_copy(update={"id": "other", "capability": "other"})
    unheld = await seam.run(_call(tool=other))

    assert isinstance(held, ToolResult)
    assert isinstance(unheld, ToolResult)
    assert held.outcome is ToolOutcome.SUCCEEDED
    assert len(runner.calls) == 1
    assert unheld.outcome is ToolOutcome.FAILED
    assert unheld.failure is not None
    assert unheld.failure.kind is ToolFailureKind.INVALID_REQUEST


class _Approving:
    """An own-records runner that takes the asked call a yes approved."""

    def __init__(self) -> None:
        self.approved: list[tuple[ToolCall, AskedCall]] = []

    async def run(self, call: ToolCall) -> ToolResult:
        del call
        return ToolResult(outcome=ToolOutcome.FAILED)

    async def run_approved(self, call: ToolCall, asked: AskedCall) -> ToolResult:
        self.approved.append((call, asked))
        return ToolResult(outcome=ToolOutcome.SUCCEEDED)


async def test_an_approved_call_reaches_a_runner_that_takes_its_asked_call() -> None:
    """ADR-0321 §5:2: the asked call reaches the runner that bounds its write by it."""
    approving = _Approving()
    plain = _Runner()
    other = REMEMBER.model_copy(update={"id": "other", "capability": "other"})
    seam = OwnRecordsByCapability({"remember": approving, "other": plain})
    asked = _asked()

    taken = await seam.run_approved(_approved_call(), asked)
    run = await seam.run_approved(_call(tool=other), asked)

    assert isinstance(taken, ToolResult)
    assert taken.outcome is ToolOutcome.SUCCEEDED
    assert [one for _, one in approving.approved] == [asked]
    assert isinstance(run, ToolResult)
    assert run.outcome is ToolOutcome.SUCCEEDED
    assert len(plain.calls) == 1


# --- a yes keeps a memory, and a conflict found at write time needs you (ADR-0321 §5) -------

_STATEMENT: Final = "drinks coffee every morning"
_ASSERTED: Final = "assertion:1"
_YES_AT: Final = datetime(2026, 10, 12, 14, 15, tzinfo=UTC)
_QUESTION: Final = QuestionPart(round="round:asked", part=1)


def _assertion(record_id: str = _ASSERTED, *, said: bool = True) -> Memory:
    """A stored memory the statement contradicts, which the writer finds as a conflict.

    The user's own word where ``said``, and a remembered inference otherwise.
    """
    support = (
        said_support(_EPISODE, when=_AT, added_at=_AT)
        if said
        else remembered_support(_EPISODE, effect=f"effect:{record_id}", when=_AT, added_at=_AT)
    )
    return memory(record_id, f"never {_STATEMENT}", support)


def _approval(part: int = 1) -> Approval:
    """The approval a yes in ``act-1`` made to the question round ``round:asked`` asked."""
    return Approval(
        who=ApprovalGiver.USER_THROUGH_HUB_CHAT,
        how=YesToQuestion(activation_id="act-0", round=_QUESTION.round),
        covers=(QuestionPart(round=_QUESTION.round, part=part),),
        given=ApprovalGiven(activation_id="act-1", at=_YES_AT),
        ends=ApprovalEnd.WHEN_USED,
    )


def _approved_call(arguments: dict[str, Any] | None = None, *, part: int = 1) -> ToolCall:
    """A remember allowed under a yes: its decision names the approval and its part."""
    request = ActionRequest(tool=REMEMBER, parameters=arguments or _arguments(_STATEMENT))
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    decision = PermissionDecision.from_request(
        request,
        ruling,
        id="decision:1",
        decided_at=_AT,
        effect="effect:1",
        approval=_approval(part),
        approved_part=QuestionPart(round=_QUESTION.round, part=part),
    )
    return ToolCall(request=request, decision=decision)


def _asked(
    arguments: dict[str, Any] | None = None, *, part: int = 1, replaces: tuple[str, ...] = ()
) -> AskedCall:
    """The asked call a round recorded for the remember its message asked about."""
    return AskedCall(
        part=part, tool=REMEMBER, values=arguments or _arguments(_STATEMENT), replaces=replaces
    )


class _Recording:
    """The built ``MemoryPolicy``, recording each proposal the writer hands it."""

    def __init__(self) -> None:
        self._policy = DefaultMemoryPolicy()
        self.proposals: list[MemoryUpdateProposal] = []

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
        relations: Mapping[str, ConflictRelation] | None = None,
    ) -> MemoryDecision:
        self.proposals.append(proposal)
        return await self._policy.decide(proposal, conflicts=conflicts, relations=relations)


async def _over(
    *stored: Memory, wired: bool = True
) -> tuple[RememberCalls, FakeMemoryStore, _Recording]:
    """The runner over the built policy, a store holding ``stored``, and its read wired."""
    _, store = await _runner()
    for record in stored:
        await store.add(record)
    policy = _Recording()
    writer = FakeMemoryWriter(store=store, policy=policy, now=_now)
    return RememberCalls(writer=writer, memory=store if wired else None, now=_now), store, policy


async def _live(store: FakeMemoryStore, record_id: str) -> bool:
    """Whether the stored record is still live, its window open; ``False`` once retired."""
    (record,) = [one for one in await store.export() if one.id == record_id]
    return record.validity.valid_until is None


async def _written(store: FakeMemoryStore) -> list[Memory]:
    """The live memories stating the statement."""
    return [
        record
        for record in await store.export()
        if isinstance(record, Memory)
        and record.content == _STATEMENT
        and record.validity.valid_until is None
    ]


async def test_a_conflict_found_at_write_time_needs_you_showing_what_it_replaces() -> None:
    """§5:5, #2845: the writer's ask comes back needing you, with the assertion shown."""
    runner, store, _ = await _over(_assertion())

    result = await runner.run(_call(_arguments(_STATEMENT)))

    assert isinstance(result, NeedsYou)
    assert [(one.id, one.content) for one in result.replaces] == [
        (_ASSERTED, f"never {_STATEMENT}")
    ]
    assert await _written(store) == []
    assert await _live(store, _ASSERTED)


async def test_only_the_assertions_among_the_conflicts_are_shown_replaced() -> None:
    """§5:5: the question shows the assertions a yes retires, not every conflict found."""
    inferred = _assertion("inferred:1", said=False)
    runner, _, _ = await _over(_assertion(), inferred)

    result = await runner.run(_call(_arguments(_STATEMENT)))

    assert isinstance(result, NeedsYou)
    assert [one.id for one in result.replaces] == [_ASSERTED]


async def test_a_conflict_no_question_could_show_is_not_done() -> None:
    """With no store to read the assertion from, a question could not show it."""
    runner, store, _ = await _over(_assertion(), wired=False)

    result = await runner.run(_call(_arguments(_STATEMENT)))

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.REFUSED
    assert await _written(store) == []


async def test_a_yes_writes_the_statement_and_retires_the_assertion_it_showed() -> None:
    """§5:2, §5:5: the confirmation is the yes's, and retires exactly what was shown."""
    runner, store, policy = await _over(_assertion())

    result = await runner.run_approved(_approved_call(), _asked(replaces=(_ASSERTED,)))

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert len(await _written(store)) == 1
    assert not await _live(store, _ASSERTED)
    (ruled,) = policy.proposals
    shown = MemoryUpdateProposal(
        proposed=ruled.proposed, rationale=ruled.rationale, conflicts=(_ASSERTED,)
    )
    assert ruled.confirmation == UserConfirmation(
        question=_QUESTION,
        question_key=shown.question_key,
        confirmed_at=_YES_AT,
        retires=(_ASSERTED,),
    )


async def test_an_assertion_the_question_did_not_show_is_not_retired_on_that_yes() -> None:
    """§5:5: the policy asks again, and the call needs you again, showing both."""
    unshown = _assertion("assertion:2")
    runner, store, policy = await _over(_assertion(), unshown)

    result = await runner.run_approved(_approved_call(), _asked(replaces=(_ASSERTED,)))

    assert isinstance(result, NeedsYou)
    assert {one.id for one in result.replaces} == {_ASSERTED, "assertion:2"}
    (ruled,) = policy.proposals
    assert ruled.confirmation is not None
    assert ruled.confirmation.retires == (_ASSERTED,)
    assert await _written(store) == []
    assert await _live(store, _ASSERTED)
    assert await _live(store, "assertion:2")


async def test_a_confirmed_memory_rests_on_the_yes() -> None:
    """ADR-0328 §13:3: a statement saved on a yes stands at "you confirmed this wording".

    It rests on one ``confirmation`` support pointing at the yes's episode and the
    approved part, ``sure``, dated at the approval's ``given.at`` — even where the
    activation that asked had read outside content.
    """
    runner, store, _ = await _over()
    tainted = _arguments(_STATEMENT, outside=True)

    result = await runner.run_approved(_approved_call(tainted), _asked(tainted))

    assert isinstance(result, ToolResult)
    assert result.outcome is ToolOutcome.SUCCEEDED
    written = await store.get(remembered_record_id("effect:1"))
    assert isinstance(written, Memory)
    (support,) = written.supports
    assert support.points_at == ConfirmationPart(
        episode="activation:act-1", asking_activation="act-0", question=_QUESTION
    )
    assert support.origin is SupportOrigin.CONFIRMATION
    assert support.how_sure is ReadingCertainty.SURE
    assert support.when == _YES_AT
    assert written.standing is MemoryStanding.CONFIRMED
    assert written.rests_on_outside_content is False


@pytest.mark.parametrize(
    ("call", "asked"),
    [
        pytest.param(
            _approved_call(_arguments(_STATEMENT, outside=True)),
            _asked(_arguments("drinks tea every morning", outside=True)),
            id="the question stated something else",
        ),
        pytest.param(
            _approved_call(_arguments(_STATEMENT, outside=True)),
            _asked(_arguments(_STATEMENT, outside=True), part=2),
            id="another part of the question",
        ),
        pytest.param(
            _call(_arguments(_STATEMENT, outside=True)),
            _asked(_arguments(_STATEMENT, outside=True)),
            id="no approval",
        ),
    ],
)
async def test_no_confirmation_is_made_for_a_call_the_yes_did_not_approve(
    call: ToolCall, asked: AskedCall
) -> None:
    """§5:2: a confirmation only from the approval and the asked call it approved."""
    runner, store, policy = await _over()

    result = await runner.run_approved(call, asked)

    assert result == NeedsYou(replaces=())
    (ruled,) = policy.proposals
    assert ruled.confirmation is None
    assert await _written(store) == []

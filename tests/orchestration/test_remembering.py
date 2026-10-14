"""The remember capability (ADR-0306 §3:2, §3:3) and acting's own-records seam, filled."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from test_activation_state import _admitted

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionRequest,
    CapabilityEffect,
    CapabilityResult,
    EpisodicMemory,
    MemoryDecisionKind,
    MemoryIngestResult,
    MemorySource,
    MemoryUpdateProposal,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import OwnRecordsByCapability
from ai_assistant.orchestration.activation_state import CURRENT_ACTIVATION, ActivationScope
from ai_assistant.orchestration.planning import DELIBERATE_REPEAT, offered_tools
from ai_assistant.orchestration.remembering import (
    EPISODE_ARGUMENT,
    OUTSIDE_CONTENT_ARGUMENT,
    REMEMBER,
    REMEMBERED_CONFIDENCE,
    STATEMENT_ARGUMENT,
    RememberCalls,
    remembered_proposal,
    remembered_record_id,
)
from ai_assistant.testing import FakeMemoryPolicy, FakeMemoryStore, FakeMemoryWriter

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


@pytest.mark.parametrize("outside", [False, True])
def test_the_proposal_is_a_derived_belief_citing_the_episode(*, outside: bool) -> None:
    """ADR-0106 §1: provenance by rule, never by the model, and never the user's word."""
    proposal = remembered_proposal(
        _arguments(outside=outside), record_id="remembered:effect:1", at=_AT
    )

    record = proposal.proposed
    assert isinstance(record, SemanticMemory)
    assert record.id == "remembered:effect:1"
    assert record.fact == "likes green tea"
    assert record.provenance.source is MemorySource.INFERRED
    assert record.provenance.confidence == REMEMBERED_CONFIDENCE
    assert record.provenance.evidence == (_EPISODE,)
    assert record.provenance.derived_from_external is outside
    assert record.provenance.last_updated == _AT


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

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.output is None
    written = await store.get(remembered_record_id("effect:1"))
    assert isinstance(written, SemanticMemory)
    assert written.fact == "likes green tea"


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


@pytest.mark.parametrize("kind", [MemoryDecisionKind.ASK_USER, MemoryDecisionKind.REJECT])
async def test_a_writer_that_asks_or_rejects_writes_nothing_and_is_not_done(
    kind: MemoryDecisionKind,
) -> None:
    """ADR-0306 §4:3: memory ruled to ask about is not written until the authority milestone."""
    runner, store = await _runner(kind)

    result = await runner.run(_call())

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.REFUSED
    assert await store.get(remembered_record_id("effect:1")) is None


async def test_a_tainted_statement_is_not_written_unconfirmed() -> None:
    """ADR-0106 §6, at the writer's ruling as at authorizing's."""
    runner, store = await _runner()

    result = await runner.run(_call(_arguments(outside=True)))

    assert result.outcome is ToolOutcome.FAILED
    assert await store.get(remembered_record_id("effect:1")) is None


async def test_a_call_that_is_not_a_claimed_remember_call_is_not_done() -> None:
    runner, _ = await _runner()
    other = REMEMBER.model_copy(update={"id": "other", "capability": "other"})

    unclaimed = await runner.run(_call(effect=None))
    misrouted = await runner.run(_call(tool=other))

    for result in (unclaimed, misrouted):
        assert result.outcome is ToolOutcome.FAILED
        assert result.failure is not None
        assert result.failure.kind is ToolFailureKind.INVALID_REQUEST


class _FailingWriter:
    """A ``MemoryWriter`` whose store is gone."""

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        del proposal
        msg = "the store is gone"
        raise MemoryStoreError(msg)


async def test_a_write_that_fails_is_not_done() -> None:
    """§3:3: the outcome is what the store answered, and never unknown."""
    result = await RememberCalls(writer=_FailingWriter(), now=_now).run(_call())

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

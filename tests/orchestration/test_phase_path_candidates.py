"""The phases' glue for a recorded candidate, apart from any engine (ADR-0329 §4, §6:5).

A remember a tap approved is run under ``run_approved``'s name (ADR-0361 §5:2) and runs
as ``remember``, so what came of it is rendered from the capability it ran as: its
lookup's memories, as fetched, or that its lookup failed. The whole path, switch on,
runs in ``test_engine_phases_candidates``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.types import (
    ActionRequest,
    FrozenJson,
    FrozenJsonValue,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    ProposedCall,
    ToolCall,
)
from ai_assistant.orchestration.acting import (
    ActedCall,
    ActedOutcome,
    ActedRound,
    AuthorizedCall,
    ResultRoute,
)
from ai_assistant.orchestration.approvals import RUN_APPROVED_LABEL, RUN_APPROVED_TOOL
from ai_assistant.orchestration.authorizer import CallVerdict, RoundAuthorization, Verdict
from ai_assistant.orchestration.phase_path import PhaseWorking
from ai_assistant.orchestration.planning import (
    CallOutcomeKind,
    PlaceWindow,
    PlannedCall,
    PlannedRound,
    RecordedCandidate,
)
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE, SIMILAR_KEY
from ai_assistant.testing.memories import memory, said_support

_AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
_VALUES: Final[dict[str, FrozenJson]] = {
    "fact": "prefers window seats",
    "why": "travel",
    "rests_on_this_stimulus": True,
    "confirm": True,
    "episode": "activation:asking",
    "rests_on_outside_content": False,
}


def _working(output: FrozenJsonValue, *, proposed_as: str) -> PhaseWorking:
    """A working set whose one round ran a remember proposed under ``proposed_as``."""
    working = PhaseWorking(
        activation_id="yes",
        place=PlaceWindow(takes_message=True),
        conversation_id=None,
        trigger=None,
        owner_records=False,
        round_limit=3,
    )
    proposed = ProposedCall(call_id="c1", name=proposed_as, arguments={RUN_APPROVED_LABEL: "A1"})
    working.planned(
        PlannedRound(
            round=PlanningRound(id="round:1", recorded_at=_AT, calls=(proposed,)),
            labels=(),
            recorded=True,
            calls=(
                PlannedCall(ProposedCall(call_id="c1", name="remember_fact", arguments=_VALUES)),
            ),
        )
    )
    request = ActionRequest(tool=REMEMBER_CANDIDATE, parameters=_VALUES)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id="decision-1",
        decided_at=_AT,
        effect="effect-1",
    )
    working.latest.authorization = RoundAuthorization(
        activation_id="yes",
        round_id="round:1",
        verdicts=(
            CallVerdict("c1", Verdict.ALLOWED, decision_id="decision-1", effect_id="effect-1"),
        ),
    )
    working.latest.acted = ActedRound(
        round_id="round:1",
        calls=(
            ActedCall(
                call=AuthorizedCall(ToolCall(request=request, decision=decision)),
                outcome=ActedOutcome.DONE,
                output=output,
                route=ResultRoute.PLANNING,
                result_id="result:1",
                effect_id="effect-1",
            ),
        ),
    )
    return working


def test_an_approved_candidate_is_shown_its_lookup_as_fetched() -> None:
    """§4:1, §6:5: by the capability it ran as, not the tool it was proposed under."""
    working = _working({SIMILAR_KEY: ["aisle"]}, proposed_as=RUN_APPROVED_TOOL)
    assert working.unfetched_searches() == {"result:1": ("aisle",)}
    aisle = memory("aisle", "prefers aisle seats", said_support())
    working.searched["result:1"] = (aisle,)

    (outcome,) = working.outcomes()

    assert outcome.kind is CallOutcomeKind.DONE
    assert outcome.result is None
    assert outcome.candidate == RecordedCandidate(similar=(aisle,))


def test_an_approved_candidate_whose_lookup_failed_says_so() -> None:
    """§4:4: never a raw ``null``; the candidate is recorded and its lookup unread."""
    working = _working({SIMILAR_KEY: None}, proposed_as=RUN_APPROVED_TOOL)
    assert working.unfetched_searches() == {}

    (outcome,) = working.outcomes()

    assert outcome.result is None
    assert outcome.candidate == RecordedCandidate(similar=None)


def test_a_candidate_proposed_directly_is_shown_the_same_way() -> None:
    working = _working({SIMILAR_KEY: []}, proposed_as="remember_fact")
    working.searched["result:1"] = ()

    (outcome,) = working.outcomes()

    assert outcome.candidate == RecordedCandidate(similar=())

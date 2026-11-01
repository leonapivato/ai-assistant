"""The conversational question path is retired, and what stored records hold still reads.

ADR-0361 §8:5: nothing produces ``text``'s ``asks``, the exact lines a message carried, a
round's asked calls, or the question marks the windows carried (#3495, which moots
#3547). §8:6: a type only that path used leaves ``core`` where no stored record holds it,
and one a stored record holds stays and is read as it was. §11: the code of the clauses
it retires goes, ``run_approved_action`` and the runners' ``run_approved(call, asked)``
among them.
"""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from story_support import episode

from ai_assistant.core import types as core_types
from ai_assistant.core.types import (
    ActionRequest,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    AskedCall,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    EpisodicMemory,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningRound,
    QuestionPart,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    YesToQuestion,
)
from ai_assistant.orchestration import acting, authorizer, person_calls, planning, remembering
from ai_assistant.orchestration.message_tools import TEXT_CALL, TextArguments, text_arguments
from ai_assistant.orchestration.understanding import TranscriptWindow, WrittenBy
from ai_assistant.testing import FakeAuditTrail, FakeMemoryStore

_AT: Final = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
_SOURCE: Final = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"
#: The canonical fakes build stored records for tests, a confirmation support's question
#: form among them, and produce nothing a hub runs.
_TEST_ONLY: Final = _SOURCE / "testing"

_BOOK: Final = ToolDefinition(
    id="book",
    capability="book",
    description="Book a table.",
    risk_level=RiskLevel.MEDIUM,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=False,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
    parameters_schema={
        "type": "object",
        "properties": {"date": {"type": "string"}},
        "required": ["date"],
        "additionalProperties": False,
    },
)


def _producers() -> list[str]:
    """Each place under ``src`` that builds a question path's record, outside the fakes."""
    found: list[str] = []
    retired = {"AskedCall", "YesToQuestion", "QuestionPart", "AnsweredQuestion", "AskedIn"}
    for path in sorted(_SOURCE.rglob("*.py")):
        if path.is_relative_to(_TEST_ONLY):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            asked = any(one.arg == "asked" for one in node.keywords)
            if name in retired or (name in {"PlanningRound", "WrittenBy"} and asked):
                found.append(f"{path.relative_to(_SOURCE)}:{node.lineno} {name}")
    return found


# --- nothing produces the question path (§8:5) ------------------------------------------


def test_no_module_the_hub_runs_builds_a_question_an_asked_call_or_a_yes_to_one() -> None:
    """§8:5: no round records an asked call, no approval is a yes to a question."""
    assert _producers() == []


def test_text_takes_no_asks_and_its_check_refuses_one() -> None:
    """ADR-0357 §8 retires whole: ``asks`` is no argument of ``text``."""
    assert "asks" not in TEXT_CALL.model_dump(mode="json")["parameters_schema"]["properties"]
    assert "asks" not in {one.name for one in dataclasses.fields(TextArguments)}
    refused = text_arguments({"to": "the user", "words": "Shall I?", "asks": ["1.1"]})
    assert isinstance(refused, str)


def test_no_window_carries_a_question_mark() -> None:
    """#3495: ``TranscriptWindow.asked`` and ``WrittenBy.asked`` are gone, with ``AskedIn``."""
    assert "asked" not in {one.name for one in dataclasses.fields(TranscriptWindow)}
    assert "asked" not in {one.name for one in dataclasses.fields(WrittenBy)}


def test_the_retired_clauses_code_is_gone() -> None:
    """§11: the approved-action tool, the yes's context, the runners' asked-call path."""
    assert not hasattr(planning, "APPROVED_ACTION_TOOL")
    assert not hasattr(planning, "ApprovedAction")
    assert not hasattr(authorizer, "YesContext")
    assert not hasattr(acting, "ApprovedOwnRecordsCalls")
    assert not hasattr(person_calls.PersonModelCalls, "run_approved")
    assert not hasattr(remembering.CandidateCalls, "run_approved")
    assert "approved_part" not in {one.name for one in dataclasses.fields(planning.PlannedCall)}
    assert "asked" not in {one.name for one in dataclasses.fields(acting.AuthorizedCall)}


def test_the_answer_pointer_leaves_core_and_the_types_stored_records_hold_stay() -> None:
    """§8:6: no stored record holds an answer pointer; a part, an asked call and a yes's
    form are held by effect records, rounds and decisions, so they stay."""
    assert not hasattr(core_types, "AnsweredQuestion")
    for kept in ("QuestionPart", "AskedCall", "YesToQuestion", "ConfirmationPart"):
        assert hasattr(core_types, kept), kept


# --- a stored record holding a kept type still reads (§8:6) ------------------------------


async def test_a_stored_round_that_asked_reads_back_as_it_was() -> None:
    """A round recorded before the retirement, its asked calls held, reads unchanged."""
    asked = (AskedCall(part=1, tool=_BOOK, values={"date": "Friday"}),)
    stored = episode("act-asked")
    processing = stored.processing_record
    assert processing is not None
    planned = PlanningRound(id="round:1", recorded_at=_AT, text="Shall I?", asked=asked)
    stored = stored.model_copy(
        update={"processing_record": processing.model_copy(update={"rounds": (planned,)})}
    )
    memory = FakeMemoryStore(now=lambda: _AT)

    await memory.add(stored)
    held = await memory.get(stored.id)

    assert isinstance(held, EpisodicMemory)
    assert held.processing_record is not None
    (round_,) = held.processing_record.rounds
    assert round_.asked == asked
    assert EpisodicMemory.model_validate_json(held.model_dump_json()) == held


async def test_a_recorded_decision_under_a_yes_to_a_question_reads_back_as_it_was() -> None:
    """A decision the trail holds, naming the question's form of approval, reads unchanged."""
    part = QuestionPart(round="round:q", part=1)
    request = ActionRequest(tool=_BOOK, parameters={"date": "Friday"})
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id="decision:1",
        decided_at=_AT,
        effect="effect:1",
        approval=Approval(
            who=ApprovalGiver.USER_THROUGH_HUB_CHAT,
            how=YesToQuestion(activation_id="act-asked", round=part.round),
            covers=(part,),
            given=ApprovalGiven(activation_id="act-yes", at=_AT),
            ends=ApprovalEnd.WHEN_USED,
        ),
        approved_part=part,
    )
    trail = FakeAuditTrail(now=lambda: _AT)

    await trail.record(decision)
    held = await trail.get(decision.id)

    assert held == decision
    assert held is not None
    assert held.approval is not None
    assert isinstance(held.approval.how, YesToQuestion)
    assert PermissionDecision.model_validate_json(held.model_dump_json()) == held

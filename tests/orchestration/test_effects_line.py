"""ADR-0364 §7 and §14:2: each offered description's effects line is generated.

The generator writes the line from the tool's declaration (§7:2-§7:5), and planning's
offer adds it after the declared parts. Lane B wrote each line by hand to the agreed
text; :data:`_AGREED` holds those lines byte for byte, so the offer is pinned to what
the model was offered before the generator (§14:2): a difference is the template's or a
declaration's, and never a line adjusted here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.types import (
    ActionRequest,
    CapabilityEffect,
    DataTier,
    Reversibility,
    RoundResponse,
)
from ai_assistant.orchestration.approval_rules import ALWAYS_NEEDS_APPROVAL, approval_rule
from ai_assistant.orchestration.approvals import (
    REQUEST_APPROVAL,
    RUN_APPROVED_DESCRIPTION,
    RUN_APPROVED_TOOL,
)
from ai_assistant.orchestration.authorizer import _needs_you_by_rule
from ai_assistant.orchestration.lookups import LOOK_UPS
from ai_assistant.orchestration.matter_calls import MATTER_CALLS
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CALLS
from ai_assistant.orchestration.planning import (
    PLANNING_PROMPT,
    RUN_APPROVED_OFFERED,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
    effects_line,
    offered_tools,
)
from ai_assistant.orchestration.reliance import NOTE_RELIANCE
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.story_calls import STORY_CALLS
from ai_assistant.orchestration.task_scheduler import TASK_SCHEDULER_CALLS
from ai_assistant.testing import FakeToolCallingCompleter, default_prompt
from ai_assistant.testing.forecasting import FAKE_FORECAST_READ
from ai_assistant.testing.searching import FAKE_WEB_SEARCH
from ai_assistant.tools.forecast import FORECAST_READ
from ai_assistant.tools.send_email import EMAIL
from ai_assistant.tools.web_search import WEB_SEARCH

if TYPE_CHECKING:
    from ai_assistant.core.types import PlanningLabel, PlanningRound, ToolDefinition

#: Every declaration planning is offered from in production, bar ``run_approved``, which
#: is no declaration (§7:6).
_OFFERED: Final[tuple[ToolDefinition, ...]] = (
    TEXT_CALL,
    EMAIL,
    WEB_SEARCH,
    FORECAST_READ,
    REQUEST_APPROVAL,
    REMEMBER_CANDIDATE,
    NOTE_RELIANCE,
    *PERSON_MODEL_CALLS,
    *LOOK_UPS,
    *STORY_CALLS,
    *TASK_SCHEDULER_CALLS,
    *MATTER_CALLS,
)

_OWN: Final = "It changes only the system's own records."
_NOTHING: Final = "It changes nothing."
_ASK: Final = "Always needs approval first: ask for it with request_approval."

#: §14:2: each capability's effects line as lane B wrote it by hand, the agreed text.
_AGREED: Final[dict[str, str]] = {
    "send_text": "It acts outside the system and can't be undone. Safe to repeat.",
    "send_email": f"It acts outside the system and can't be undone. Not safe to repeat. {_ASK}",
    "search_web": "It changes nothing, but what it sends leaves the system.",
    "read_forecast": "It changes nothing, but what it sends leaves the system.",
    "request_approval": f"{_OWN} Not safe to repeat.",
    "remember_fact": f"{_OWN} Not safe to repeat.",
    "note_reliance": _NOTHING,
    "set_profile_field": f"{_OWN} Safe to repeat. {_ASK}",
    "pin_memory": f"{_OWN} Safe to repeat. {_ASK}",
    "unpin_memory": f"{_OWN} Safe to repeat. {_ASK}",
    "search_memories": _NOTHING,
    "read_matter": _NOTHING,
    "reread_result": _NOTHING,
    "search_episodes": _NOTHING,
    "read_episode": _NOTHING,
    "read_origin_history": _NOTHING,
    "search_connections": _NOTHING,
    "start_matter": f"{_OWN} Not safe to repeat.",
    "note_matter": f"{_OWN} Safe to repeat.",
    "add_to_matter": f"{_OWN} Safe to repeat.",
    "remove_from_matter": f"{_OWN} Safe to repeat.",
    "tidy_matter": f"{_OWN} Safe to repeat.",
    "move_to_matter": f"{_OWN} Safe to repeat.",
    "merge_matters": f"{_OWN} Safe to repeat.",
    "split_matter": f"{_OWN} Safe to repeat.",
    "group_matters": f"{_OWN} Not safe to repeat.",
    "spawn_task": (
        "It changes only the system's own records, and can be undone. Not safe to repeat."
    ),
    "cancel_task": f"{_OWN} Safe to repeat.",
    "list_tasks": _NOTHING,
    "stop_work": f"{_OWN} Safe to repeat.",
    "answer_offer": f"{_OWN} Safe to repeat.",
}


def test_every_tool_offered_has_an_agreed_line() -> None:
    """The 31 declarations and ``run_approved`` are the 32 the owner walked (§5)."""
    assert len(_OFFERED) == len(_AGREED) == 31
    assert {str(one.capability) for one in _OFFERED} == set(_AGREED)
    assert RUN_APPROVED_TOOL not in _AGREED


@pytest.mark.parametrize("tool", _OFFERED, ids=lambda tool: str(tool.capability))
def test_each_offered_description_ends_with_the_line_its_declaration_generates(
    tool: ToolDefinition,
) -> None:
    """§7:1, §14:2: the generated line, after the declared parts, is the agreed one."""
    (offered,) = offered_tools((tool,))

    assert effects_line(tool) == _AGREED[str(tool.capability)]
    assert offered.description == f"{tool.description}\n\n{effects_line(tool)}"


@pytest.mark.parametrize("tool", _OFFERED, ids=lambda tool: str(tool.capability))
def test_no_declaration_writes_its_effects_line_by_hand(tool: ToolDefinition) -> None:
    """§7:1: once the generator is built, the line is never written in a declaration."""
    assert "\n\nIt changes" not in tool.description
    assert "\n\nIt acts" not in tool.description
    assert "Safe to repeat" not in tool.description
    assert "Always needs approval" not in tool.description


@pytest.mark.parametrize("fake", [FAKE_WEB_SEARCH, FAKE_FORECAST_READ], ids=str)
def test_the_canonical_fakes_are_offered_as_their_tools_are(fake: ToolDefinition) -> None:
    """A fake's declared parts are its own; its line is generated as the real tool's is."""
    (offered,) = offered_tools((fake,))
    assert offered.description == f"{fake.description}\n\n{_AGREED[str(fake.capability)]}"


def test_run_approved_takes_no_generated_line() -> None:
    """§7:6: its effects are its ticket's call's, which its description says."""
    assert RUN_APPROVED_OFFERED.description == RUN_APPROVED_DESCRIPTION
    assert "It changes" not in RUN_APPROVED_DESCRIPTION
    assert "It acts" not in RUN_APPROVED_DESCRIPTION


class _Recorder:
    async def record(
        self, planning_round: PlanningRound, labels: tuple[PlanningLabel, ...]
    ) -> None:
        del planning_round, labels


async def test_the_model_is_offered_each_tool_with_its_generated_line() -> None:
    """§14:2: what the completer is handed, every tool of the offer, run_approved too."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse())
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
    )
    await stage.plan(
        PlanningInputs(
            activation_id="a1",
            place=PlaceWindow(takes_message=True),
            capabilities=_OFFERED,
            approvals=True,
        )
    )

    declared = {str(one.capability): one for one in _OFFERED}
    shown = {one.name: one.description for one in completer.last_call.tools}
    assert shown.pop(RUN_APPROVED_TOOL) == RUN_APPROVED_DESCRIPTION
    assert shown == {
        name: f"{declared[name].description}\n\n{line}" for name, line in _AGREED.items()
    }


# --- the template (§7:2-§7:5) ----------------------------------------------------------------


def _declared(**fields: Any) -> ToolDefinition:
    """A declaration with ``fields`` changed, on a capability no rule asks approval of."""
    return TEXT_CALL.model_copy(update={"capability": "a_tool", **fields})


@pytest.mark.parametrize(
    ("fields", "line"),
    [
        pytest.param(
            {"effect": CapabilityEffect.WORLD, "reversibility": Reversibility.REVERSIBLE},
            "It acts outside the system and can be undone. Safe to repeat.",
            id="world-reversible",
        ),
        pytest.param(
            {"effect": CapabilityEffect.WORLD, "reversibility": Reversibility.RECOVERABLE},
            "It acts outside the system. Safe to repeat.",
            id="world-recoverable",
        ),
        pytest.param(
            {
                "effect": CapabilityEffect.WORLD,
                "leaves_hub": True,
                "safe_to_repeat": False,
            },
            "It acts outside the system and can't be undone. Not safe to repeat.",
            id="world-leaving-says-nothing-of-leaving",
        ),
        pytest.param(
            {
                "effect": CapabilityEffect.OWN_RECORDS,
                "writes": (DataTier.PERSONAL,),
                "reversibility": Reversibility.IRREVERSIBLE,
            },
            "It changes only the system's own records, and can't be undone. Safe to repeat.",
            id="own-irreversible",
        ),
        pytest.param(
            {
                "effect": CapabilityEffect.OWN_RECORDS,
                "writes": (),
                "reversibility": Reversibility.IRREVERSIBLE,
                "safe_to_repeat": False,
            },
            "It changes nothing.",
            id="own-writing-nothing-changes-nothing",
        ),
        pytest.param(
            {
                "effect": CapabilityEffect.NONE,
                "reversibility": Reversibility.IRREVERSIBLE,
                "safe_to_repeat": False,
            },
            "It changes nothing.",
            id="nothing-says-nothing-of-undoing-or-repeating",
        ),
    ],
)
def test_the_line_is_read_from_the_declaration(fields: dict[str, Any], line: str) -> None:
    assert effects_line(_declared(**fields)) == line


def test_a_tool_that_changes_nothing_and_always_needs_approval_says_both() -> None:
    """§7:5: the approval sentence follows whatever the call changes."""
    tool = _declared(effect=CapabilityEffect.NONE, capability="send_email")
    assert effects_line(tool) == f"It changes nothing. {_ASK}"


# --- the register (§7:5) ---------------------------------------------------------------------


@pytest.mark.parametrize("tool", _OFFERED, ids=lambda tool: str(tool.capability))
def test_the_line_and_authorizing_read_one_register(tool: ToolDefinition) -> None:
    """§7:5: a tool's line says it always needs approval exactly where authorizing rules
    its every call needs the person, so the two cannot disagree."""
    says = effects_line(tool).endswith(_ASK)
    rules = _needs_you_by_rule(ActionRequest.model_construct(tool=tool, parameters={}))
    assert says == (approval_rule(str(tool.capability)) is not None) == (rules is not None)


def test_the_register_holds_email_and_the_person_models_calls() -> None:
    """§7:5: today that is ``send_email`` and the person model's three calls."""
    assert set(ALWAYS_NEEDS_APPROVAL) == {
        "send_email",
        *(str(one.capability) for one in PERSON_MODEL_CALLS),
    }

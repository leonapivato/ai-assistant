"""The plan block on a turn that did not service a search (#2213).

ADR-0242 §7's eight fragments are asserted where they are produced — the system-prompt
side, in ``test_search_not_serviced.py``, and through the engine's own forwarding in
``test_engine_search_not_serviced.py``. What is asserted **here** is the other half of
the assembled prompt: the *user* turn's plan block, and the one line of the assembler's
own text #2213 adds to it.

The defect this module pins is a reply that named a cause the system never had. On the
deployed hub a turn whose search was ruled on and refused answered "no capability
available to me actually performs web retrieval" — false, since the servicing ran
through admission and was refused — while :data:`~ai_assistant.orchestration.composing.
_UNAVAILABLE_PROMPT` was already telling the model not to guess at a reason. The model
was not guessing. ``ActionPlan.rationale`` is planner-authored text rendered verbatim
two lines above, and ``_render_plan``'s "Nothing" line names it as the one thing that
"says why" — so the block handed the model an authoritative cause for a lookup the
block knows nothing about.

**What can be asserted, and what cannot.** The rationale is the planning model's own
output, so no case here searches the whole prompt for the false sentence and calls its
absence a fix: a decline may legitimately say a capability was needed, and
``test_composing.py``'s own ADR-0211 §9 arm records why a prompt-wide search is the
wrong instrument. What is checkable is that the sentence reaches the stage **only as an
attributed span**, and that the assembler's own text beside it says what the block is
about — which is the whole of the change.
"""

from __future__ import annotations

import json
from typing import Final

import pytest
from test_composing import _plan, _prompt, _step, _turn

from ai_assistant.core.types import PlanStep, SearchNotServiced
from ai_assistant.orchestration import composing
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.reads import SearchDisposition
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter

#: The scope line, read from the module rather than quoted, because every case below is
#: about *where the assembler puts it* rather than about its wording — the bar ADR-0176
#: §4's fourth clause sets for a prompt clause, and the reason
#: :func:`test_the_scope_line_carries_none_of_adr_0242_s_forbidden_items` asserts over
#: its content structurally instead of matching prose.
_SCOPE: Final = composing._PLAN_IS_ABOUT_ACTING

#: The sentence #2213 recorded off the deployed hub, put in the planner's mouth here
#: because that is where it came from: a decline whose rationale explained the turn by
#: the absence of a capability, on a turn whose search had in fact been ruled on.
_FALSE_CAUSE: Final = "no capability available to me actually performs web retrieval"

#: The three members #2213's brief names, and the three the walkthrough could have hit:
#: ``UNAVAILABLE`` is what the observed run carried, and the other two are the members a
#: deployment one act away from that run produces.
_REPORTED: Final = (
    SearchNotServiced.UNAVAILABLE,
    SearchNotServiced.TRUST_MISSING,
    SearchNotServiced.NOT_ADMITTED,
)

_HEADING: Final = "What the assistant decided to do:"


def _stage(model: FakeModelProvider) -> ComposingStage:
    return ComposingStage(model=model, streaming=FakeStreamingCompleter())


def _plan_block(prompt: str) -> list[str]:
    """The plan block's lines, from its heading to the blank line that ends it."""
    lines = prompt.splitlines()
    start = lines.index(_HEADING)
    end = lines.index("", start)
    return lines[start:end]


async def _composed(
    *,
    member: SearchNotServiced | None,
    rationale: str | None = _FALSE_CAUSE,
    steps: tuple[PlanStep, ...] = (),
) -> str:
    """One composition's user-turn prompt, over a plan of the given shape."""
    model = FakeModelProvider("answer")
    await _stage(model).compose(
        turn=_turn(plan=_plan(*steps, rationale=rationale)),
        step=None,
        undriven=(),
        search_not_serviced=member,
    )
    return _prompt(model)


# --- the line is there exactly on the turns that carry a member ---------------


@pytest.mark.parametrize("member", _REPORTED, ids=lambda one: one.value)
async def test_a_turn_that_did_not_service_a_search_is_told_the_plan_accounts_for_none(
    member: SearchNotServiced,
) -> None:
    """#2213 over the three members the walkthrough's own condition can produce.

    The block closes on the assembler's own line, so the last thing the model reads
    before the step account is what the plan block is *about* — rather than the
    planner's rationale, which is what it read before.
    """
    block = _plan_block(await _composed(member=member))

    assert block[-1] == _SCOPE
    assert block[-2].startswith("  the planner's stated rationale: "), (
        "the scope line follows the rationale rather than displacing it (#1355)"
    )


@pytest.mark.parametrize("member", tuple(SearchNotServiced), ids=lambda one: one.value)
async def test_every_member_of_the_vocabulary_gets_the_line(member: SearchNotServiced) -> None:
    """The condition is the member's presence and never which member it is.

    ADR-0242 §7 keeps the *choice* of fragment at one site. This block is told the bare
    fact, so a ninth member reaching §8's table can never reach a second, divergent
    table here — there is none to reach.
    """
    assert _SCOPE in await _composed(member=member)


async def test_a_stepped_plan_gets_the_line_too() -> None:
    """A plan with steps names capabilities as well, so the same reading is available.

    The line is about the whole block rather than about the decline's "Nothing"
    sentence, and it is appended last on both shapes for that reason.
    """
    block = _plan_block(
        await _composed(member=SearchNotServiced.UNAVAILABLE, steps=(_step("s-1"),))
    )

    assert block[-1] == _SCOPE
    assert 'capability "send_email"' in block[-2], "the step lines are still last of the block"


async def test_a_turn_carrying_no_member_renders_the_block_it_always_did() -> None:
    """ADR-0242 §6's guarantee, unweakened by a second consumer of the same condition.

    "On every other turn it is given nothing, and the assembled prompt is
    byte-identical to what it is today." The condition #2213 adds is the same one §6
    already states, so a turn outside it gains nothing at all — asserted here as the
    exact three lines the block has always had on a decline carrying a rationale.
    """
    block = _plan_block(await _composed(member=None))

    assert block == [
        _HEADING,
        "  Nothing: the planner named no capability for this turn, so no action was "
        "taken. Only the planner's own rationale says why — do not supply a reason "
        "it did not state.",
        f"  the planner's stated rationale: {json.dumps(_FALSE_CAUSE)}",
    ]


async def test_the_streamed_twin_carries_it_too() -> None:
    """The two composing entry points assemble one prompt, so both call sites pass it.

    ADR-0242 §7's carrier already reaches ``compose_streaming``; a lane threading the
    fact to one of the two would leave a browser turn — the surface #2213 was observed
    on — with the block unqualified.
    """
    streaming = FakeStreamingCompleter.yielding("an", " answer")
    produced = ComposingStage(
        model=FakeModelProvider("answer"), streaming=streaming
    ).compose_streaming(
        turn=_turn(plan=_plan(rationale=_FALSE_CAUSE)),
        step=None,
        undriven=(),
        room=4096,
        search_not_serviced=SearchNotServiced.UNAVAILABLE,
    )
    async for _value in produced:
        pass

    [call] = streaming.calls
    assert _SCOPE in next(one.content for one in call.messages if one.role.value == "user")


# --- what the line says, and what it must not say -----------------------------


@pytest.mark.parametrize("member", _REPORTED, ids=lambda one: one.value)
async def test_the_false_cause_reaches_the_stage_only_as_the_planners_own_span(
    member: SearchNotServiced,
) -> None:
    """The assembler asserts the sentence nowhere; it renders it, attributed, once.

    This is the arm that would fail on a fix that merely added prose while leaving the
    rationale to be read as the turn's cause, and it is also the arm that records what
    the fix does **not** do: the planner's own words are still there, still the sole
    record of why no capability was named (ADR-0176 §3), and still rendered verbatim
    to the user beside the reply. What changed is what the block says they are about.
    """
    prompt = await _composed(member=member)

    assert prompt.count(_FALSE_CAUSE) == 1, "rendered once, and by one line"
    assert json.dumps(_FALSE_CAUSE) in prompt, "and rendered as a quoted span (ADR-0098 §2)"


def test_the_scope_line_carries_none_of_adr_0242_s_forbidden_items() -> None:
    """§7's bar on a prompt text about a search that did not happen, applied here.

    "No fragment carries … a destination, a host, an origin, a provider name, a
    connection reference, an account identity, a query or any fragment of one, a
    record, a count, a monetary figure, a duration, a budget, a ``Settings`` field
    name, a ``SearchDisposition`` value, a record id, a decision id, or a command
    name." The scope line is not one of the eight, but it is text this decision puts
    in the prompt on exactly the turns §6 governs, so it is held to the same bar —
    checked the way ``test_search_not_serviced.py`` checks the fragments.

    **The command-name arm is spelled as command names and not as the bare word.**
    That module screens the eight fragments for ``"assistant "``, which is a sound
    proxy there because every command §9 keeps out of the reply is spelled
    ``assistant <verb>`` and no fragment has cause to name the assistant at all. This
    line does: it says what the plan block is about, and the block is about what *this
    assistant* was offered. So the three commands are named here instead, which is the
    clause rather than the proxy for it.
    """
    assert not any(character.isdigit() for character in _SCOPE)
    for forbidden in ("http", "@", "$", "search_calls_per_conversation"):
        assert forbidden not in _SCOPE
    for command in ("remember-recipients", "trust-destinations", "assistant decisions"):
        assert command not in _SCOPE
    for stage in SearchDisposition:
        assert stage.value not in _SCOPE
    for member in SearchNotServiced:
        assert member.value not in _SCOPE


def test_the_scope_line_states_no_cause_and_promises_no_outcome() -> None:
    """ADR-0242 §9 and ADR-0235 §8's third clause, which §16 keeps binding entire.

    "No statement says that no request was made, and none promises what an act will
    change." The line says what the *plan block* is about; a sentence saying a lookup
    was or was not made, or that anything would follow from an act, would be a second
    statement about the search on a decision that admits exactly one.
    """
    assert "your instruction accounts for that" in _SCOPE, (
        "it points at the one account rather than giving a second"
    )
    for promise in ("would have", "will work", "try again", "ask again", "instead"):
        assert promise not in _SCOPE


def test_the_line_forbids_a_reading_and_not_a_true_statement() -> None:
    """It must not contradict ``SEARCH_DISABLED``'s own fragment.

    That fragment tells the model to say "this installation does not make them at
    all" — a true statement about lookups on such a deployment. A blanket prohibition
    on saying that this assistant does not look things up would put the two texts in
    conflict and leave the model to pick, which is the shape #1155 calls a deadlock
    rather than a finding. So the line forbids *reading the plan block* that way and
    leaves the instruction's own statement standing.
    """
    assert "Do not read it as saying" in _SCOPE
    disabled = composing._SEARCH_NOT_SERVICED_PROMPTS[SearchNotServiced.SEARCH_DISABLED]
    assert "this installation does not make them at all" in disabled, (
        "the fragment this line must not contradict is unchanged by #2213"
    )

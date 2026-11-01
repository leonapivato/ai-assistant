"""Planning's three calls on the person model, run under the person's yes (ADR-0338 §8:4-§8:8).

The declarations, and :class:`PersonModelCalls` over the canonical fakes: each call runs
only under a yes, as the person's act by that yes (§3:5, §4:1); a ``set_profile`` the
store refuses and a ``pin`` of a memory that is not current, or past the slot's budget,
are not done with the reason (§8:7); a pending suggestion is accepted in the same write
(§8:8); and an ``unpin`` finds the pin its memory is shown by, through the chain (§4:8).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from test_activation_state import _admitted
from test_person_block import NOW, _ended, _fact, _World

from ai_assistant.core.errors import PersonModelStoreError, PlanningError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    Approval,
    ApprovalEnd,
    ApprovalGiven,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CapabilityEffect,
    CapabilityResult,
    InputPart,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PersonActHow,
    PersonModelAct,
    PersonModelWriteKind,
    ProfileField,
    ProposedSuggestion,
    QuestionPart,
    RequestedCall,
    SuggestionKind,
    SupportOrigin,
    TapOnCard,
    TicketState,
    ToolCall,
    ToolOutcome,
    YesToQuestion,
)
from ai_assistant.orchestration.activation_state import CURRENT_ACTIVATION, ActivationScope
from ai_assistant.orchestration.person_block import PersonBlocks, PinRefusal
from ai_assistant.orchestration.person_calls import (
    PERSON_MODEL_CALLS,
    PIN,
    SET_PROFILE,
    UNPIN,
    NotDone,
    PersonModelCalls,
    worded_argument,
)
from ai_assistant.testing import FakePersonModelStore
from ai_assistant.testing.memories import memory, remembered_support

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import (
        PersonModel,
        PersonModelWrite,
        ToolDefinition,
        ToolResult,
    )

pytestmark = pytest.mark.anyio

_YES_AT: Final = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
_PART: Final = QuestionPart(round="round:asked", part=1)
_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)


def _under_a_question(tool: ToolDefinition, **arguments: Any) -> ToolCall:
    """A call allowed under the retired form of approval, a yes to a question.

    No such approval is made since ADR-0361 §8:5; a decision recorded with one still
    reads (§8:6), and a call carrying one runs nothing.
    """
    request = ActionRequest(tool=tool, parameters=arguments)
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id="decision:1",
        decided_at=_YES_AT,
        effect="effect:1",
        approval=Approval(
            who=ApprovalGiver.USER_THROUGH_HUB_CHAT,
            how=YesToQuestion(activation_id="act-0", round=_PART.round),
            covers=(_PART,),
            given=ApprovalGiven(activation_id="act-1", at=_YES_AT),
            ends=ApprovalEnd.WHEN_USED,
        ),
        approved_part=_PART,
    )
    return ToolCall(request=request, decision=decision)


class _Owners:
    """An activation of the owner's is current: the hub chat's, as the yes's is."""

    def __enter__(self) -> None:
        self._token = CURRENT_ACTIVATION.set(ActivationScope(_admitted()))

    def __exit__(self, *_: object) -> None:
        CURRENT_ACTIVATION.reset(self._token)


@pytest.fixture
def owners() -> Iterator[None]:
    with _Owners():
        yield


async def _run(world: _World, tool: ToolDefinition, **arguments: Any) -> ToolResult | NotDone:
    """Run ``tool``'s call under a ticket, as acting hands it on (ADR-0362 §2:4)."""
    request = _request(tool, **arguments)
    calls = PersonModelCalls(blocks=world.blocks, requests=_Requests(request))
    return await calls.run(_ticketed(request))


def _done(answer: ToolResult | NotDone) -> object:
    assert not isinstance(answer, NotDone), answer
    assert answer.outcome is ToolOutcome.SUCCEEDED
    return answer.output


def _reason(answer: ToolResult | NotDone) -> str:
    assert isinstance(answer, NotDone), answer
    return answer.reason


# --- the declarations (§8:4) ----------------------------------------------------------


@pytest.mark.parametrize("tool", PERSON_MODEL_CALLS, ids=lambda tool: str(tool.capability))
def test_each_call_declares_the_five_properties_as_ruled(tool: ToolDefinition) -> None:
    """Own records, safe to repeat, never leaving the hub, never unknown, no outside text."""
    assert tool.effect is CapabilityEffect.OWN_RECORDS
    assert tool.safe_to_repeat is True
    assert tool.leaves_hub is False
    assert tool.outcome_can_be_unknown is False
    assert tool.result is CapabilityResult.NO_OUTSIDE_TEXT
    assert tool.system_supplied == ()


def test_a_pin_and_an_unpin_show_their_memory_by_its_wording() -> None:
    """§8:6: the one argument whose memory the exact line shows by its wording."""
    assert worded_argument(str(PIN.capability)) == "memory"
    assert worded_argument(str(UNPIN.capability)) == "memory"
    assert worded_argument(str(SET_PROFILE.capability)) is None


# --- only under the person's yes, a ticket (§8:5, ADR-0362 §2:4) -----------------------------


async def test_a_call_under_a_yes_to_a_question_is_not_done() -> None:
    """ADR-0361 §5:1, §11: a yes is a ticket alone; a question's approval runs nothing."""
    world = _World()
    call = _under_a_question(SET_PROFILE, field="address", value="Robin")

    answer = await PersonModelCalls(blocks=world.blocks).run(call)

    assert "only on their yes" in _reason(answer)
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.address is None


async def test_with_no_activation_current_there_is_no_person_and_nothing_runs() -> None:
    world = _World()

    answer = await _run(world, SET_PROFILE, field="address", value="Robin")

    assert "no person's" in _reason(answer)


# --- set_profile (§3:2-§3:5, §8:7, §8:8) ------------------------------------------------


async def test_a_field_is_set_by_the_yes_and_logged_as_its_act(owners: None) -> None:
    world = _World()

    answer = await _run(world, SET_PROFILE, field="address", value="Robin")

    assert _done(answer) == "set"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.address == "Robin"
    (change,) = model.changes
    assert (change.field, change.old, change.new, change.act) == (
        ProfileField.ADDRESS,
        None,
        "Robin",
        _BY_TICKET,
    )


async def test_a_field_is_cleared_with_null_and_set_again_to_its_value_changes_nothing(
    owners: None,
) -> None:
    world = _World()
    await world.people.set_field(OWNER_PERSON_ID, ProfileField.LANGUAGE, "English", act=_PANEL)

    again = await _run(world, SET_PROFILE, field="language", value="English")
    cleared = await _run(world, SET_PROFILE, field="language", value=None)

    assert _done(again) == "already so"
    assert _done(cleared) == "cleared"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.language is None
    assert [one.new for one in model.changes] == ["English", None]


async def test_a_value_the_store_refuses_is_not_done_with_the_reason(owners: None) -> None:
    """§8:7: a zone ``zoneinfo`` does not resolve fails §3:2, and nothing is written."""
    world = _World()

    answer = await _run(world, SET_PROFILE, field="time_zone", value="Mars/Olympus")

    assert _reason(answer) == "the value is not valid: a time zone is a name zoneinfo resolves"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.time_zone is None
    assert model.changes == ()


async def test_a_field_suggestion_is_accepted_in_the_same_write(owners: None) -> None:
    """§8:8: the field takes the suggestion's value by the yes, so it is no longer pending."""
    world = _World()
    await world.people.record_suggestion(
        OWNER_PERSON_ID,
        ProposedSuggestion(
            kind=SuggestionKind.FIELD,
            field=ProfileField.TIME_ZONE,
            value="Europe/Lisbon",
            episode_id="activation:a1",
            part=InputPart(episode="activation:a1"),
            origin=SupportOrigin.USER_MESSAGE,
        ),
    )

    answer = await _run(world, SET_PROFILE, field="time_zone", value="Europe/Lisbon")

    assert _done(answer) == "set"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.suggestions == ()


@pytest.mark.parametrize(
    "arguments",
    [{"field": "pronouns", "value": "they"}, {"field": "name", "value": 7}],
    ids=["no-such-field", "not-text"],
)
async def test_a_malformed_set_profile_is_not_done(owners: None, arguments: dict[str, Any]) -> None:
    world = _World()
    request = _request(SET_PROFILE, field="name", value="Robin")
    call = _ticketed(request)
    malformed = call.model_copy(
        update={"request": call.request.model_copy(update={"parameters": arguments})}
    )

    answer = await PersonModelCalls(blocks=world.blocks, requests=_Requests(request)).run(malformed)

    assert _reason(answer) == "the call's arguments are malformed"


async def test_a_store_that_fails_leaves_the_call_not_done(owners: None) -> None:
    world = _World()
    world.people.fail_next()

    answer = await _run(world, SET_PROFILE, field="address", value="Robin")

    assert _reason(answer) == "the person model could not be read or written"


# --- pin (§4:1-§4:2, §6:3, §8:7, §8:8) --------------------------------------------------


async def test_a_current_memory_is_pinned_by_the_yes(owners: None) -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))

    answer = await _run(world, PIN, memory="m:diet")

    assert _done(answer) == "pinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    (pin,) = model.standing_pins
    assert (pin.memory_id, pin.act) == ("m:diet", _BY_TICKET)


async def test_pinning_a_pinned_memory_changes_nothing(owners: None) -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")

    answer = await _run(world, PIN, memory="m:diet")

    assert _done(answer) == "already pinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert len(model.pins) == 1


@pytest.mark.parametrize("held", [True, False], ids=["retired", "not-held"])
async def test_only_a_current_memory_is_pinned(owners: None, *, held: bool) -> None:
    """§4:2, §8:7: an ended memory, or one the store does not hold, is not done."""
    world = _World()
    if held:
        await world.held(_ended("m:old", "Lives in Porto.", successor=None))

    answer = await _run(world, PIN, memory="m:old")

    assert _reason(answer) == "only a current memory can be pinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.pins == ()


async def test_a_pin_past_the_budget_is_refused_with_nothing_written(owners: None) -> None:
    """§6:3: the pins' wordings, with the new one's, would exceed the slot's budget."""
    world = _World(budget=30)
    await world.held(_fact("m:diet", "Eats no meat."), _fact("m:sister", "Has a sister, Ada."))
    await world.pin("m:diet")

    answer = await _run(world, PIN, memory="m:sister")

    assert "past its budget" in _reason(answer)
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert [pin.memory_id for pin in model.pins] == ["m:diet"]


async def test_the_budget_counts_each_memory_the_pins_show_once_at_its_chains_end(
    owners: None,
) -> None:
    """§4:8, §6:3: a pin on a retired memory shows its successor, and that one counts.

    The retired memory's longer wording is not what the slot shows, so the new pin fits;
    and pinning the successor itself adds nothing to what the pins show.
    """
    world = _World(budget=40)
    await world.held(
        _ended("m:old", "Lives in Porto, by the river, since 2019.", successor="m:new"),
        _fact("m:new", "Lives in Lisbon."),
        _fact("m:diet", "Eats no meat."),
    )
    await world.pin("m:old")

    successor = await _run(world, PIN, memory="m:new")
    diet = await _run(world, PIN, memory="m:diet")

    assert _done(successor) == "pinned"
    assert _done(diet) == "pinned"


async def test_a_pin_suggestion_is_accepted_in_the_same_write(owners: None) -> None:
    """§8:8: its memory is pinned by the yes, so it is no longer pending."""
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.people.record_suggestion(
        OWNER_PERSON_ID,
        ProposedSuggestion(kind=SuggestionKind.PIN, memory_id="m:diet", episode_id="activation:a1"),
    )

    await _run(world, PIN, memory="m:diet")

    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.suggestions == ()


# --- unpin (§4:7, §4:8) -------------------------------------------------------------------


async def test_an_unpin_marks_the_pin_removed_and_keeps_the_memory(owners: None) -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")

    answer = await _run(world, UNPIN, memory="m:diet")

    assert _done(answer) == "unpinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.standing_pins == ()
    assert len(model.pins) == 1, "the store keeps the pin, marked removed"
    assert "m:diet" in await world.memory.get_many(["m:diet"])


async def test_an_unpin_names_the_successor_the_pin_is_shown_by(owners: None) -> None:
    """§4:8: planning is shown a pin's chain's current end, and unpins by that one."""
    world = _World()
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:new"), _fact("m:new", "Lives in Lisbon.")
    )
    await world.pin("m:old")

    answer = await _run(world, UNPIN, memory="m:new")

    assert _done(answer) == "unpinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.standing_pins == ()


async def test_unpinning_a_memory_no_pin_shows_changes_nothing(owners: None) -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."), _fact("m:tea", "Drinks green tea."))
    await world.pin("m:diet")

    answer = await _run(world, UNPIN, memory="m:tea")

    assert _done(answer) == "not pinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert [pin.memory_id for pin in model.standing_pins] == ["m:diet"]


# --- two calls at once (§6:3) and an unpin left part done (§4:7) ------------------------


class _Wrapped:
    """The canonical fake, every member it does not override delegated to it."""

    def __init__(self) -> None:
        self.store = FakePersonModelStore(now=lambda: NOW)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)


class _Yielding(_Wrapped):
    """Yielding to the loop after each read, as a store's I/O does."""

    async def read(self, person_id: str) -> PersonModel | None:
        model = await self.store.read(person_id)
        for _ in range(5):
            await asyncio.sleep(0)
        return model


def _over(world: _World, store: _Wrapped, *, budget: int = 1600) -> None:
    world.people = store.store
    world.blocks = PersonBlocks(
        store=cast("PersonModelStore", store), memory=world.memory, budget_chars=budget
    )


async def test_two_pins_at_once_never_pass_a_budget_only_one_fits(owners: None) -> None:
    """§6:3: acting runs a round's calls at once; each pin's check and write hold the lock."""
    world = _World()
    _over(world, _Yielding(), budget=30)
    await world.held(_fact("m:diet", "Eats no meat, ever."), _fact("m:tea", "Drinks green tea."))

    first, second = await asyncio.gather(
        _run(world, PIN, memory="m:diet"), _run(world, PIN, memory="m:tea")
    )

    assert _done(first) == "pinned"
    assert "past its budget" in _reason(second)
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert [pin.memory_id for pin in model.standing_pins] == ["m:diet"]


class _FailingSecondRemoval(_Wrapped):
    """The second pin removal a store fault."""

    removals = 0

    async def remove_pin(self, person_id: str, pin_id: str) -> PersonModelWrite:
        self.removals += 1
        if self.removals == 2:
            msg = "test: the store failed"
            raise PersonModelStoreError(msg)
        return await self.store.remove_pin(person_id, pin_id)


async def test_an_unpin_left_part_done_says_so_and_is_not_done(owners: None) -> None:
    """Two pins show the memory; the second's removal fails after the first's is written."""
    world = _World()
    _over(world, _FailingSecondRemoval())
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:new"), _fact("m:new", "Lives in Lisbon.")
    )
    await world.pin("m:old", "m:new")

    answer = await _run(world, UNPIN, memory="m:new")

    assert _reason(answer) == (
        "1 of the 2 pins showing it were removed and the rest could not be, so it is "
        "still pinned; unpinning it again finishes it"
    )
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert len(model.standing_pins) == 1
    again = await _run(world, UNPIN, memory="m:new")
    assert _done(again) == "unpinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.standing_pins == ()


async def test_a_successor_the_slot_does_not_show_takes_none_of_the_budget(owners: None) -> None:
    """§6:3-§6:4: a pin's successor resting on outside content is shown in no slot."""
    world = _World(budget=30)
    await world.held(
        _ended("m:old", "Listens to jazz.", successor="m:new"),
        memory("m:new", "The newsletter says they love jazz.", remembered_support(outside=True)),
        _fact("m:diet", "Eats meat."),
    )
    await world.pin("m:old")

    answer = await _run(world, PIN, memory="m:diet")

    assert _done(answer) == "pinned"


async def test_the_panel_pins_through_the_same_checks() -> None:
    """One place checks and writes a pin, for planning's call and the panel's alike (§8:2)."""
    world = _World(budget=20)
    await world.held(_fact("m:diet", "Eats no meat."), _fact("m:sister", "Has a sister, Ada."))

    first = await world.blocks.pin(OWNER_PERSON_ID, "m:diet", act=_PANEL)
    second = await world.blocks.pin(OWNER_PERSON_ID, "m:sister", act=_PANEL)
    gone = await world.blocks.pin(OWNER_PERSON_ID, "m:none", act=_PANEL)

    assert first.write is not None
    assert first.write.kind is PersonModelWriteKind.WRITTEN
    assert (second.write, second.refused) == (None, PinRefusal.OVER_BUDGET)
    assert gone.refused is PinRefusal.NOT_CURRENT


# --- under a ticket (ADR-0362 §2:1, §2:4-§2:5) ---------------------------------------------

_ASKED_AT: Final = _YES_AT - timedelta(hours=1)
#: The approval's own activation, the one its outcome was pushed to (ADR-0361 §3:4).
_APPROVALS_OWN: Final = "act-approval"


def _request(tool: ToolDefinition, **arguments: Any) -> ApprovalRequest:
    """A request for ``tool``'s call, approved by a tap, its ticket spent, its outcome pushed."""
    return ApprovalRequest(
        id="request:1",
        person=OWNER_PERSON_ID,
        activation_id="act-ask",
        round="round:ask",
        call=RequestedCall(tool=tool, values=arguments),
        why="You asked me to.",
        written_at=_ASKED_AT,
        expires_at=_ASKED_AT + timedelta(hours=24),
        state=ApprovalRequestState.APPROVED,
        answer=ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_YES_AT),
        ticket=TicketState.USED,
        spent_by="effect:1",
        pushed_to=_APPROVALS_OWN,
    )


def _ticketed(request: ApprovalRequest, *, held_by: str = "act-taken") -> ToolCall:
    """The call ``request``'s ticket holds, allowed under the tap, in the work ``held_by``.

    By default a work the approval's input joined by a take, so that the episode an act
    names is told from the work that ran the ticket.
    """
    held = request.call
    call = ActionRequest(tool=held.tool, parameters=held.values)
    decision = PermissionDecision.from_request(
        call,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id="decision:1",
        decided_at=_YES_AT,
        effect="effect:1",
        approval=Approval(
            who=ApprovalGiver.USER_TAP_ON_HUB_PANEL,
            how=TapOnCard(
                request=request.id,
                activation_id=request.activation_id,
                round=request.round,
                expires_at=request.expires_at,
            ),
            given=ApprovalGiven(activation_id=held_by, at=_YES_AT),
            ends=ApprovalEnd.WHEN_USED_OR_EXPIRED,
        ),
    )
    return ToolCall(request=call, decision=decision)


class _Requests:
    """The plan store's read of approval requests, holding ``held``, or failing."""

    def __init__(self, *held: ApprovalRequest, fails: bool = False) -> None:
        self.held = {one.id: one for one in held}
        self.fails = fails
        self.read: list[str] = []

    async def __call__(self, request_ids: Sequence[str]) -> tuple[ApprovalRequest, ...]:
        if self.fails:
            msg = "test: the plan store failed"
            raise PlanningError(msg)
        self.read.extend(request_ids)
        return tuple(self.held[one] for one in request_ids if one in self.held)


#: The act a ticket's call makes: the request, and the approval's own episode (§2:1).
_BY_TICKET: Final = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    request="request:1",
    episode_id=f"activation:{_APPROVALS_OWN}",
)


async def test_a_set_profile_under_a_ticket_names_the_request_and_the_approvals_episode(
    owners: None,
) -> None:
    """§2:1, §2:4: the approval's own episode, not the work that ran the ticket after a take."""
    world = _World()
    request = _request(SET_PROFILE, field="address", value="Robin")
    requests = _Requests(request)

    answer = await PersonModelCalls(blocks=world.blocks, requests=requests).run(_ticketed(request))

    assert _done(answer) == "set"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.address == "Robin"
    (change,) = model.changes
    assert change.act == _BY_TICKET
    assert requests.read == ["request:1"]


async def test_a_pin_under_a_ticket_names_the_request_and_the_approvals_episode(
    owners: None,
) -> None:
    """§2:4: a pin is made with the request form's act, through the same checks (§4:2)."""
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    request = _request(PIN, memory="m:diet")

    answer = await PersonModelCalls(blocks=world.blocks, requests=_Requests(request)).run(
        _ticketed(request)
    )

    assert _done(answer) == "pinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    (pin,) = model.standing_pins
    assert (pin.memory_id, pin.act) == ("m:diet", _BY_TICKET)


async def test_an_unpin_under_a_ticket_records_no_act_and_reads_no_request(owners: None) -> None:
    """§2:5: the pin is marked removed, keeping the act that made it."""
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")
    requests = _Requests()

    answer = await PersonModelCalls(blocks=world.blocks, requests=requests).run(
        _ticketed(_request(UNPIN, memory="m:diet"))
    )

    assert _done(answer) == "unpinned"
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    (pin,) = model.pins
    assert pin.removed_at is not None
    assert pin.act.how is PersonActHow.PANEL
    assert requests.read == []


@pytest.mark.parametrize(
    "held",
    [
        pytest.param({}, id="not-held"),
        pytest.param({"person": "person:someone-else"}, id="another-persons"),
        pytest.param({"call": RequestedCall(tool=PIN, values={"memory": "m:x"})}, id="other-call"),
    ],
)
async def test_a_ticket_whose_request_does_not_hold_the_call_changes_nothing(
    owners: None, held: dict[str, Any]
) -> None:
    """§2:4: the call is the request's person's, by that ticket, and none other."""
    world = _World()
    request = _request(SET_PROFILE, field="address", value="Robin")
    requests = _Requests(request.model_copy(update=held)) if held else _Requests()

    answer = await PersonModelCalls(blocks=world.blocks, requests=requests).run(_ticketed(request))

    assert "only on their yes" in _reason(answer)
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.address is None


async def test_a_ticket_with_no_request_reader_or_a_failing_one_changes_nothing(
    owners: None,
) -> None:
    """§2:1: with no request read, no act can name the approval's episode, so none is made."""
    world = _World()
    request = _request(SET_PROFILE, field="address", value="Robin")

    unread = await PersonModelCalls(blocks=world.blocks).run(_ticketed(request))
    failed = await PersonModelCalls(blocks=world.blocks, requests=_Requests(fails=True)).run(
        _ticketed(request)
    )

    assert "only on their yes" in _reason(unread)
    assert "could not be read or written" in _reason(failed)
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.address is None

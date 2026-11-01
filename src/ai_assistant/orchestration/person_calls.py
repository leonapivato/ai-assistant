"""Planning's three calls on the person model: ``set_profile``, ``pin`` and ``unpin``.

ADR-0338 §8:4-§8:8, ADR-0306 §2-§3. Planning proposes each of these calls, authorizing
rules by rule and with no model that every one needs the person's yes (§8:5), and acting
runs one only under that yes, directly against
:class:`~ai_assistant.core.protocols.PersonModelStore` and never through ``ToolInvoker``
(ADR-0306 §3:3). Each is an **inside action** (ADR-0292 §12:1): its effect is the
assistant's own records, it is safe to repeat, it never leaves the hub, its outcome is
never unknown and its result carries no outside text (§8:4).

**Three parts, one module**, as :mod:`~ai_assistant.orchestration.remembering` is: the
declarations (:data:`PERSON_MODEL_CALLS`), which of their arguments name a memory by its
``M`` label (:data:`PERSON_MODEL_LABEL_ARGUMENTS`, ADR-0307 §5:2), and the runner,
:class:`PersonModelCalls`.

| Call | Takes | Writes |
| --- | --- | --- |
| :data:`SET_PROFILE` | one of the five fields, and its value or ``null`` | one field |
| :data:`PIN` | one memory, by its ``M`` label | one pin |
| :data:`UNPIN` | one memory, by its ``M`` label | the pins showing it, marked removed |

**Inert where no store is wired** (ADR-0338 §11:2). Nothing here is offered until the
phases are attached to a person-model store, which the engine does exactly where it is
handed the person block's assembly; with none, no declaration is offered, no call names
one, and nothing changes.

**Only under the person's yes.** A call runs where it was rebuilt from a question the
person said yes to (ADR-0321 §4:2), and is recorded as their act by that yes: the
approval's part and the episode the yes was given in (ADR-0338 §3:5, §4:1). **Or under a
ticket** (ADR-0362 §2:4-§2:5): acting has claimed it by ``claim_ticket_call``, spending the
ticket, and a ``set_profile`` or a ``pin`` is recorded with the request form's act, naming
the request and the approval's own episode, where the yes was given, whichever work ran
the ticket (§2:1). An ``unpin`` records no act, as none is recorded for one: its ticket is
on its effect record, keyed by the request. A call that reaches the runner any other way
is not done. The person is the activation's, read from its recorded trigger (§2:2), never
from what the call carries.

**Not done, with the reason** (§8:7). A ``set_profile`` whose value the store refuses
(§3:2) and a ``pin`` of a memory that is not current (§4:2), or that would take the
wordings the person's pins show past the kept-in-mind slot's budget (§6:3), each come
back :class:`NotDone`, which acting reports with its reason; the budget is checked
against the memory store before the write, as the contract leaves it to the caller.

**A pending suggestion is accepted in the same write** (§8:8): the store's contract marks
a field suggestion accepted where its field takes its value, and a pin suggestion where
its memory is pinned, in the write's own step, so the runner writes nothing else.

**What a pin or an unpin shows in its question** (§8:6). Its exact line shows the
memory's wording in place of its label: :func:`worded_argument` names the argument whose
memory is shown by its wording, and the phases' glue reads that wording from the memory
store for the round that asks.

**It logs stage and code-owned reason only**, never a field's value or a memory's words
(ADR-0275 §8).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.errors import MemoryStoreError, PersonModelStoreError, PlanningError
from ai_assistant.core.types import (
    WORDED_CAPABILITIES,
    ApprovalRequest,
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    LabelKind,
    PersonActHow,
    PersonModelAct,
    PersonModelRefusal,
    PersonModelWriteKind,
    ProfileField,
    Reversibility,
    RiskLevel,
    TapOnCard,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.person_block import PinRefusal, activation_person
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import (
        AskedCall,
        FrozenJson,
        PersonModelWrite,
        RequestedCall,
        ToolCall,
    )
    from ai_assistant.orchestration.person_block import PersonBlocks

__all__ = [
    "FIELD_ARGUMENT",
    "MEMORY_ARGUMENT",
    "PERSON_MODEL_CALLS",
    "PERSON_MODEL_CAPABILITIES",
    "PERSON_MODEL_LABEL_ARGUMENTS",
    "PIN",
    "PIN_CAPABILITY",
    "SET_PROFILE",
    "SET_PROFILE_CAPABILITY",
    "UNPIN",
    "UNPIN_CAPABILITY",
    "VALUE_ARGUMENT",
    "NotDone",
    "PersonModelCalls",
    "recorded_wording",
    "worded_argument",
]

_log = structlog.get_logger(__name__)

#: The three capabilities, each its declaration's id (ADR-0338 §8:4).
SET_PROFILE_CAPABILITY: Final = "set_profile"
PIN_CAPABILITY: Final = "pin"
UNPIN_CAPABILITY: Final = "unpin"

#: Every capability this module declares: authorizing's rule needs the person's yes for
#: each (ADR-0338 §8:5).
PERSON_MODEL_CAPABILITIES: Final = frozenset(
    {SET_PROFILE_CAPABILITY, PIN_CAPABILITY, UNPIN_CAPABILITY}
)

#: ``set_profile``'s arguments: the field, and its new value or ``null`` to clear it.
FIELD_ARGUMENT: Final = "field"
VALUE_ARGUMENT: Final = "value"

#: ``pin``'s and ``unpin``'s one argument: the memory, by its ``M`` label.
MEMORY_ARGUMENT: Final = "memory"


def _declared(capability: str, description: str, schema: dict[str, FrozenJson]) -> ToolDefinition:
    """One call's declaration, the five properties as ADR-0338 §8:4 rules them.

    - ``effect=OWN_RECORDS``, ``leaves_hub=False``, ``outcome_can_be_unknown=False``,
      ``safe_to_repeat=True`` and ``result=NO_OUTSIDE_TEXT``: §8:4, for each of the three.
      A done call's result is a code-owned word saying what it did.
    - ``side_effecting=True`` with ``writes=(PERSONAL,)``: it writes the person's own
      model, which ADR-0306 §2:5 requires of an effect that is not none;
      ``reads=(PERSONAL,)`` for the model and the memory it reads first.
    - ``idempotency=NATURAL``: setting a field to the value it holds, pinning a pinned
      memory and unpinning an unpinned one each change nothing (§3:3, §4:2, §4:7).
    - ``reversibility=RECOVERABLE``: a field can be set back, and a pin removed or made
      again; the change log and a removed pin are kept.
    - ``risk_level=LOW``, ``discloses=()``, ``cost=FREE``: nothing leaves the device and
      nothing is spent.
    """
    return ToolDefinition(
        id=capability,
        capability=capability,
        description=description,
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.RECOVERABLE,
        side_effecting=True,
        reads=(DataTier.PERSONAL,),
        writes=(DataTier.PERSONAL,),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NATURAL,
        effect=CapabilityEffect.OWN_RECORDS,
        leaves_hub=False,
        result=CapabilityResult.NO_OUTSIDE_TEXT,
        outcome_can_be_unknown=False,
        safe_to_repeat=True,
        parameters_schema=schema,
    )


def _memory_schema(description: str) -> dict[str, FrozenJson]:
    return {
        "type": "object",
        "properties": {
            MEMORY_ARGUMENT: {"type": "string", "minLength": 1, "description": description}
        },
        "required": [MEMORY_ARGUMENT],
        "additionalProperties": False,
    }


SET_PROFILE: Final = _declared(
    SET_PROFILE_CAPABILITY,
    (
        "Set one field of the person's profile to a value, or clear it. It runs only "
        "once they say yes to the question that shows it. Raise a suggestion the "
        "system noticed only where it bears on what is being done, and only by asking "
        "with this call, never as a change already made."
    ),
    {
        "type": "object",
        "properties": {
            FIELD_ARGUMENT: {
                "type": "string",
                "enum": [field.value for field in ProfileField],
                "description": "The field to set.",
            },
            VALUE_ARGUMENT: {
                "anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}],
                "description": "Its new value, as the person gave it; null clears it.",
            },
        },
        "required": [FIELD_ARGUMENT, VALUE_ARGUMENT],
        "additionalProperties": False,
    },
)
"""``set_profile``: one field set to a value, or cleared (ADR-0338 §8:4)."""

PIN: Final = _declared(
    PIN_CAPABILITY,
    (
        "Pin one memory, so it is kept in mind in every conversation with the person; "
        "pinning confirms its wording. It runs only once they say yes to the question "
        "that shows it. Raise a suggestion the system noticed only where it bears on "
        "what is being done, and only by asking with this call, never as a change "
        "already made."
    ),
    _memory_schema("The memory to pin, by its M label."),
)
"""``pin``: one memory, named by its ``M`` label (ADR-0338 §8:4)."""

UNPIN: Final = _declared(
    UNPIN_CAPABILITY,
    (
        "Unpin one memory the person keeps in mind; the memory itself stays as it is. "
        "It runs only once they say yes to the question that shows it."
    ),
    _memory_schema("The pinned memory, by its M label."),
)
"""``unpin``: one pinned memory, named by its ``M`` label (ADR-0338 §8:4)."""

#: The three declarations, in the order they are offered.
PERSON_MODEL_CALLS: Final = (SET_PROFILE, PIN, UNPIN)

#: Which of the calls' arguments name a memory by label (ADR-0307 §5:2): planning maps
#: each to the memory's id, and refuses whole a call naming a label it was never shown
#: (§5:3).
PERSON_MODEL_LABEL_ARGUMENTS: Final[Mapping[str, Mapping[str, LabelKind]]] = {
    PIN_CAPABILITY: {MEMORY_ARGUMENT: LabelKind.MEMORY},
    UNPIN_CAPABILITY: {MEMORY_ARGUMENT: LabelKind.MEMORY},
}


def worded_argument(capability: str, /) -> str | None:
    """The argument a call's exact line shows by its memory's wording (ADR-0338 §8:6).

    Args:
        capability: The asked call's capability.

    Returns:
        ``memory`` for a ``pin`` or an ``unpin``; ``None`` for any other capability,
        whose exact line shows every value as it is sent.
    """
    if capability in WORDED_CAPABILITIES:
        return MEMORY_ARGUMENT
    return None


def recorded_wording(call: RequestedCall) -> dict[str, str] | None:
    """What a request's exact line shows in place of its memory (ADR-0338 §8:6).

    The memory's wording as the asking round read it, recorded with the request, so the
    card, the panel and the ticket line show the call as it was asked (ADR-0361 §2:11).

    Args:
        call: The call a request holds.

    Returns:
        The worded argument and its wording, for :func:`exact_line`'s ``worded``; ``None``
        for a call that shows no memory by its wording, or records none.
    """
    argument = worded_argument(str(call.tool.capability))
    if argument is None or call.wording is None:
        return None
    return {argument: call.wording}


#: Reads the approval requests named, from the plan store, as
#: ``PlanStore.approval_requests`` does.
type RequestsReader = Callable[[Sequence[str]], Awaitable[Sequence[ApprovalRequest]]]


@dataclass(frozen=True, slots=True)
class NotDone:
    """A call on the assistant's own records refused, with its reason (ADR-0338 §8:7).

    What a runner on acting's own-records seam answers where it wrote nothing and
    planning is owed why: acting finishes the call's record not done and reports this
    reason, in code-owned words, never a value or a memory's words. Declared here,
    beside its one producer, as :class:`~ai_assistant.orchestration.remembering.NeedsYou`
    is beside its own, since acting may import this module and this module may not
    import acting (ADR-0309 §2:3).

    Attributes:
        reason: Why it was not done.
    """

    reason: str


#: The code-owned reasons a call is not done for, each with the word it is logged by.
_UNAPPROVED: Final = "a change to the person's profile or pins runs only on their yes"
_NO_PERSON: Final = "this activation is no person's, so there is no profile to change"
_UNKNOWN_PERSON: Final = "the person-model store holds no such person"
_MALFORMED: Final = "the call's arguments are malformed"
_STORE_FAULT: Final = "the person model could not be read or written"
_NOT_CURRENT: Final = "only a current memory can be pinned"
_OVER_BUDGET: Final = (
    "pinning it would take what the person keeps in mind past its budget; another pin "
    "would have to be removed first"
)

#: What a done call returns: a code-owned word saying what it did.
_SET: Final = "set"
_CLEARED: Final = "cleared"
_ALREADY_SET: Final = "already so"
_PINNED: Final = "pinned"
_ALREADY_PINNED: Final = "already pinned"
_UNPINNED: Final = "unpinned"
_NOT_PINNED: Final = "not pinned"


def _done(output: str) -> ToolResult:
    return ToolResult(outcome=ToolOutcome.SUCCEEDED, output=output)


def _not_done(reason: str, word: str) -> NotDone:
    _log.info("person_model_call_not_done", stage="acting", reason=word)
    return NotDone(reason=reason)


def _refused(written: PersonModelWrite) -> NotDone:
    """A write the store refused, as the call's reason (ADR-0338 §3:2)."""
    refusal = written.refusal
    if refusal is PersonModelRefusal.INVALID_VALUE:
        why = written.reason or "it is not a valid value"
        return _not_done(f"the value is not valid: {why}", "invalid_value")
    if refusal is PersonModelRefusal.UNKNOWN_PERSON:
        return _not_done(_UNKNOWN_PERSON, "unknown_person")
    word = "refused" if refusal is None else refusal.value
    return _not_done(f"the person-model store refused it ({word})", word)


class PersonModelCalls:
    """Run a ``set_profile``, ``pin`` or ``unpin`` call under the person's yes (ADR-0306 §3:3).

    Structurally acting's ``OwnRecordsCalls`` and its ``ApprovedOwnRecordsCalls``: acting
    awaits it to its end, with no deadline and no cancellation, and its outcome is what
    the person-model store answered. It answers ``succeeded`` with a code-owned word
    where the call was done or changed nothing, and :class:`NotDone` with the reason
    otherwise: never ``indeterminate``.
    """

    def __init__(self, *, blocks: PersonBlocks, requests: RequestsReader | None = None) -> None:
        """Wire the runner to the stores the person block is assembled from.

        Args:
            blocks: The person block's assembly: its person-model store, the memory store
                a pin's memory is read from, and the slot's budget a pin is checked
                against (ADR-0338 §6:3), walked as the block walks a pin (§4:8).
            requests: Reads the approval requests a ticket's call names, from the plan
                store, for the approval's own episode its act names (ADR-0362 §2:1);
                ``None`` where no Approvals channel is wired, and a ``set_profile`` or a
                ``pin`` under a ticket is then not done.
        """
        self._blocks = blocks
        self._requests = requests

    async def run(self, call: ToolCall) -> ToolResult | NotDone:
        """Run a call under a ticket; refuse any other, which changes nothing without a yes.

        Args:
            call: The authorized call. Under a ticket its decision names the tap's
                approval, and acting has claimed it, spending the ticket (ADR-0362 §2:4).

        Returns:
            ``succeeded`` with what it did, or :class:`NotDone` with the reason. A call
            reaching here under no ticket is not done: authorizing needs the person's yes
            for every one of these calls (ADR-0338 §8:5), and a question's yes reaches
            :meth:`run_approved`.
        """
        approval = call.decision.approval
        if approval is None or not isinstance(approval.how, TapOnCard):
            return _not_done(_UNAPPROVED, "unapproved")
        try:
            return await self._ticketed(call, approval.how)
        except ValueError:
            return _not_done(_MALFORMED, "malformed")
        except PersonModelStoreError, MemoryStoreError, PlanningError:
            _log.warning("person_model_call_not_done", stage="acting", reason="store_fault")
            return NotDone(reason=_STORE_FAULT)

    async def _ticketed(self, call: ToolCall, tap: TapOnCard) -> ToolResult | NotDone:
        """The call its ticket holds, as the request's person's (ADR-0362 §2:4-§2:5).

        An ``unpin`` records no act. A ``set_profile`` and a ``pin`` are recorded with the
        request form's act: the request, and the approval's own episode, the activation
        its outcome was pushed to (ADR-0361 §3:4), read from the request as the plan store
        holds it.
        """
        state = active_state()
        person = None if state is None else activation_person(state.trigger)
        if person is None:
            return _not_done(_NO_PERSON, "no_person")
        capability = str(call.request.tool.capability)
        if capability == UNPIN_CAPABILITY:
            return await self._unpin(person, _memory_id(call.request.parameters))
        if self._requests is None:
            return _not_done(_UNAPPROVED, "no_request_reader")
        found = await self._requests([str(tap.request)])
        request = found[0] if found else None
        if (
            request is None
            or request.id != tap.request
            or request.person != person
            or request.pushed_to is None
            or str(request.call.tool.capability) != capability
        ):
            return _not_done(_UNAPPROVED, "unapproved_ticket")
        act = PersonModelAct(
            how=PersonActHow.APPROVAL,
            by=person,
            request=request.id,
            episode_id=episode_address(str(request.pushed_to)),
        )
        return await self._ran(call, person, act)

    async def run_approved(self, call: ToolCall, asked: AskedCall) -> ToolResult | NotDone:
        """Run the call a yes approved, as the person's act by that yes (ADR-0338 §8:5).

        Args:
            call: The authorized call, its decision naming the approval.
            asked: The asked call the yes approved, which ``call`` was rebuilt from.

        Returns:
            ``succeeded`` with what it did, or :class:`NotDone` with the reason.
        """
        acted = _approved_act(call, asked)
        if isinstance(acted, NotDone):
            return acted
        person, act = acted
        try:
            return await self._ran(call, person, act)
        except ValueError:
            return _not_done(_MALFORMED, "malformed")
        except PersonModelStoreError, MemoryStoreError:
            _log.warning("person_model_call_not_done", stage="acting", reason="store_fault")
            return NotDone(reason=_STORE_FAULT)

    async def _ran(self, call: ToolCall, person: str, act: PersonModelAct) -> ToolResult | NotDone:
        """The call run against the store, by its capability."""
        capability = str(call.request.tool.capability)
        parameters = call.request.parameters
        if capability == SET_PROFILE_CAPABILITY:
            return await self._set(person, parameters, act)
        if capability == PIN_CAPABILITY:
            return await self._pin(person, _memory_id(parameters), act)
        if capability == UNPIN_CAPABILITY:
            return await self._unpin(person, _memory_id(parameters))
        return _not_done(_MALFORMED, "not_a_person_model_call")

    async def _set(
        self, person: str, parameters: Mapping[str, FrozenJson], act: PersonModelAct
    ) -> ToolResult | NotDone:
        """Set one field, or clear it; the store validates the value (ADR-0338 §3:2-§3:3)."""
        field = ProfileField(str(parameters.get(FIELD_ARGUMENT)))
        value = parameters.get(VALUE_ARGUMENT)
        if value is not None and not isinstance(value, str):
            msg = "a field's value is text, or null to clear it"
            raise ValueError(msg)
        written = await self._blocks.store.set_field(person, field, value, act=act)
        if written.kind is PersonModelWriteKind.REFUSED:
            return _refused(written)
        if written.kind is PersonModelWriteKind.UNCHANGED:
            return _done(_ALREADY_SET)
        return _done(_CLEARED if value is None else _SET)

    async def _pin(self, person: str, memory_id: str, act: PersonModelAct) -> ToolResult | NotDone:
        """Pin through the person block's assembly, which checks and writes it (§4:2, §6:3)."""
        pinned = await self._blocks.pin(person, memory_id, act=act)
        if pinned.refused is PinRefusal.NOT_CURRENT:
            return _not_done(_NOT_CURRENT, "not_current")
        if pinned.refused is PinRefusal.OVER_BUDGET:
            return _not_done(_OVER_BUDGET, "over_budget")
        written = pinned.write
        if written is None:
            return _not_done(_UNKNOWN_PERSON, "unknown_person")
        if written.kind is PersonModelWriteKind.REFUSED:
            return _refused(written)
        if written.kind is PersonModelWriteKind.UNCHANGED:
            return _done(_ALREADY_PINNED)
        return _done(_PINNED)

    async def _unpin(self, person: str, memory_id: str) -> ToolResult | NotDone:
        """Unpin through the person block's assembly, which finds every pin showing it (§4:7).

        Where more than one pin shows it and one cannot be removed after another was, the
        call is not done, since a pin still shows the memory, and its reason says that
        some were removed; an unpin is safe to repeat, so asking again finishes it.
        """
        unpinned = await self._blocks.unpin(person, memory_id)
        if unpinned.unknown_person:
            return _not_done(_UNKNOWN_PERSON, "unknown_person")
        if unpinned.removed < unpinned.showing:
            if unpinned.removed:
                return _partly(unpinned.removed, unpinned.showing)
            if unpinned.refused is not None:
                return _refused(unpinned.refused)
        if not unpinned.showing:
            return _done(_NOT_PINNED)
        return _done(_UNPINNED)


def _partly(removed: int, showing: int) -> NotDone:
    """An unpin that removed some of the pins showing its memory, and not the rest."""
    _log.warning("person_model_call_not_done", stage="acting", reason="partly_unpinned")
    return NotDone(
        reason=(
            f"{removed} of the {showing} pins showing it were removed and the rest could "
            "not be, so it is still pinned; unpinning it again finishes it"
        )
    )


def _approved_act(call: ToolCall, asked: AskedCall) -> tuple[str, PersonModelAct] | NotDone:
    """Whose act the call is, and how: the person's, by the yes it runs under (§3:5, §4:1).

    The call runs under an approval whose approved part is ``asked``'s, of the same
    capability; the person is the activation's, read from its recorded trigger (§2:2).
    The act names the approval by the part it spends, and the episode the yes was given
    in. Otherwise the call is not done.
    """
    decision = call.decision
    approval = decision.approval
    part = decision.approved_part
    if (
        approval is None
        or part is None
        or part.part != asked.part
        or str(asked.tool.capability) != str(call.request.tool.capability)
    ):
        return _not_done(_UNAPPROVED, "unapproved")
    state = active_state()
    person = None if state is None else activation_person(state.trigger)
    if person is None:
        return _not_done(_NO_PERSON, "no_person")
    act = PersonModelAct(
        how=PersonActHow.APPROVAL,
        by=person,
        approval=part,
        episode_id=episode_address(approval.given.activation_id),
    )
    return person, act


def _memory_id(parameters: Mapping[str, FrozenJson]) -> str:
    """The memory a ``pin`` or ``unpin`` names, its label already mapped to its id."""
    memory_id = parameters.get(MEMORY_ARGUMENT)
    if not isinstance(memory_id, str) or not memory_id.strip():
        msg = "a pin or an unpin names one memory"
        raise ValueError(msg)
    return memory_id

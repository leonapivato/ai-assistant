"""The remember capability: one statement written to memory (ADR-0306 §3:2, §3:3).

Planning remembers by calling this capability. It is an **inside action** (ADR-0292
§12:1): its effect is the assistant's own records, it never leaves the hub, its outcome
is never unknown and it returns nothing. It is **not safe to repeat**, so acting's
duplicate backstop refuses the same statement twice in one matter (ADR-0306 §5:9).

**Three parts, one module.** The declaration, :data:`REMEMBER`; the proposal a call
makes, :func:`remembered_proposal`, which authorizing hands ``MemoryPolicy`` before
anything runs and the runner hands the writer when the call runs, so what was ruled on
and what is written are one record; and the runner, :class:`RememberCalls`, which acting
reaches through its own-records seam and never through ``ToolInvoker`` (ADR-0306 §3:3).

**What a call takes.** Planning writes one argument, ``statement``: the one thing to
remember, in its own words. The hub fills the other two, which the declaration names in
``system_supplied`` (ADR-0254 §3), so planning is never offered them and the duplicate
backstop never compares them (ADR-0306 §2:10): ``episode``, the address of the
activation's episode, and ``rests_on_outside_content``, whether that activation's record
says it has read outside content (ADR-0306 §4:5). Authorizing fills both before the
candidate fit test, and the decision's parameters digest binds them.

**The written memory's support is set by rule** (ADR-0328 §13:2, ADR-0106 §1), never
by the model. The statement is planning's own wording, so it is a memory this system
worked out: one support pointing at the remember call, with the origin ``remembered``,
or ``remembered_over_outside`` exactly where the activation had read outside content,
``for``, backing it as worded, its reading not judged, its ``when`` the episode's
``occurred_at``, added by ``remember``; and a create citing it. It stands at
inference, in the ``DERIVED`` band, never at "you said it": a model's paraphrase
claiming the user's own standing is the laundering ADR-0098 §4 forbids. A derived
proposal resting on outside content is then never committed unconfirmed (ADR-0106 §6),
so in an activation that read outside content ``MemoryPolicy`` asks or rejects, and
authorizing turns that into *needs you* or *not done* (ADR-0306 §4:3, §4:8 to §4:9).

**The written belief's placement is set by rule too** (ADR-0217 §3:12, ADR-0204 §2,
§5:2). The statement is produced by planning over what the activation had been given
when it planned the round, so where ADR-0204 §2's disjunction over that supply is
``True`` the belief is written reach ``OWNER`` with setter ``DERIVED``, and otherwise
with the default. The runner reads that value off the activation's state, where the
phases' glue sets it before each round is planned (ADR-0309 §5:10); a call run where no
activation is current has no supply and is written with the default. ``MemoryPolicy``
reads no placement, so the proposal authorizing rules on, which carries the default,
is ruled exactly as the one written.

**The writer rules again.** ``MemoryWriter.ingest`` finds the proposal's conflicts and
asks its own policy over them (ADR-0028). A reject is a call not done, and nothing is
written. An ask writes nothing either, and **comes back needing you**, not not done
(ADR-0321 §5:5, #2845): the runner answers :class:`NeedsYou` carrying the assertions among the
conflicts the writer ruled against, as stored, so the question can show the statement
*replacing* them. Where it cannot show every one of them, because no memory store was
wired to read them, one is gone, or one is not a statement, the call is not done
instead: a question that could not show what a yes retires would only be asked again.

**A yes keeps it** (ADR-0321 §5:2, §5:3). A remember that runs under a yes reaches the
runner with the asked call the yes approved (:meth:`RememberCalls.run_approved`), and
code builds a :class:`~ai_assistant.core.types.UserConfirmation` from the approval and
that asked call. The proposal carries it to the writer and so to ``MemoryPolicy``, which
honours it as ADR-0106 §6:1-§6:3 and ADR-0214 §3:2 decide. This is the confirmation's
only production producer: the user's assent to text they were shown, never a model's
paraphrase claiming their standing (ADR-0098 §4).

- ``question`` is the part the decision's approval approved, and ``confirmed_at`` is
  when the yes was given.
- ``retires`` is exactly the asked call's ``replaces``, the assertions the question
  showed, and nothing else. The proposal's frozen ``conflicts`` are those same ids, and
  ``question_key`` is the proposal's key over them, so the confirmation binds what is
  written against what was shown (ADR-0078 §5, §7). An assertion the question did not
  show is not retired on that yes: the policy asks again, and the call needs you again.
- The memory rests instead on one support with the origin ``confirmation``, pointing at
  the yes's episode and the approved question part, ``sure``, its ``when`` the
  approval's ``given.at`` (ADR-0328 §13:3), so it stands at "you confirmed this
  wording". The decision naming the approval is authorizing's.
- A confirmation is built only where the decision names an approval whose approved part
  is the asked call's, and the asked call is a remember stating exactly the call's
  statement. Otherwise none is, and the writer rules as it would on any call.

**It logs stage and code-owned reason only**, never the statement (ADR-0275 §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    BeliefBand,
    CapabilityEffect,
    CapabilityResult,
    ConfirmationPart,
    CostBasis,
    DataTier,
    Idempotency,
    Memory,
    MemoryDecisionKind,
    MemoryOperation,
    MemoryOperationKind,
    MemorySupport,
    MemoryUpdateProposal,
    MemoryWriterName,
    Placement,
    PlacementReach,
    PlacementSetter,
    ReadingCertainty,
    RememberCallPart,
    Reversibility,
    RiskLevel,
    SupportDirection,
    SupportOrigin,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    UserConfirmation,
    record_band,
)
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.protocols import MemoryStore, MemoryWriter
    from ai_assistant.core.types import AskedCall, FrozenJson, ToolCall

__all__ = [
    "EPISODE_ARGUMENT",
    "OUTSIDE_CONTENT_ARGUMENT",
    "REMEMBER",
    "REMEMBER_CAPABILITY",
    "STATEMENT_ARGUMENT",
    "STATEMENT_MAX_CHARS",
    "NeedsYou",
    "RememberCalls",
    "remembered_proposal",
    "remembered_record_id",
]

_log = structlog.get_logger(__name__)

#: The capability planning is offered, and the declaration's id.
REMEMBER_CAPABILITY: Final = "remember"

#: The one argument planning writes: the statement to remember.
STATEMENT_ARGUMENT: Final = "statement"

#: The hub-filled argument naming the activation's episode, the belief's evidence.
EPISODE_ARGUMENT: Final = "episode"

#: The hub-filled argument saying whether the activation had read outside content.
OUTSIDE_CONTENT_ARGUMENT: Final = "rests_on_outside_content"

#: The longest statement a call may carry.
STATEMENT_MAX_CHARS: Final = 2000

_RATIONALE: Final = "planning remembered this statement during an activation"

#: What a remembered memory's id is its effect record's id prefixed with.
_RECORD_PREFIX: Final = "remembered:"

_PARAMETERS_SCHEMA: Final[dict[str, FrozenJson]] = {
    "type": "object",
    "properties": {
        STATEMENT_ARGUMENT: {
            "type": "string",
            "minLength": 1,
            "maxLength": STATEMENT_MAX_CHARS,
            "description": (
                "The one thing to remember, as a statement that will still make sense "
                "on its own later."
            ),
        },
        EPISODE_ARGUMENT: {"type": "string", "minLength": 1},
        OUTSIDE_CONTENT_ARGUMENT: {"type": "boolean"},
    },
    "required": [STATEMENT_ARGUMENT, EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT],
    "additionalProperties": False,
}

REMEMBER: Final = ToolDefinition(
    id=REMEMBER_CAPABILITY,
    capability=REMEMBER_CAPABILITY,
    description="Remember one statement about the user or their world, for later.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.RECOVERABLE,
    side_effecting=True,
    reads=(DataTier.PERSONAL,),
    writes=(DataTier.PERSONAL,),
    discloses=(),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.OWN_RECORDS,
    leaves_hub=False,
    result=CapabilityResult.NONE,
    outcome_can_be_unknown=False,
    safe_to_repeat=False,
    system_supplied=(EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT),
    parameters_schema=_PARAMETERS_SCHEMA,
)
"""The remember capability's declaration (ADR-0306 §2, §3:2).

- ``effect=OWN_RECORDS``, ``leaves_hub=False``, ``result=NONE``,
  ``outcome_can_be_unknown=False`` and ``safe_to_repeat=False``: §3:2, each as ruled.
- ``side_effecting=True`` with ``writes=(PERSONAL,)``: it writes a belief about the user,
  which ADR-0016's consistency rules make side-effecting, and ADR-0306 §2:5 (as ADR-0312
  §2 leaves it) requires of an effect that is not none.
- ``reads=(PERSONAL,)``: the write path reads the beliefs a proposal conflicts with.
- ``reversibility=RECOVERABLE``: a remembered belief can be forgotten, but the write is
  not undone by a symmetric call.
- ``idempotency=NONE``: writing one statement twice proposes it twice; whether the
  second folds into the first is the writer's ruling, not a guarantee.
- ``risk_level=LOW``, ``discloses=()``, ``cost=FREE``: nothing leaves the device and
  nothing is spent.
- ``system_supplied`` names the two arguments the hub fills (module docstring).
"""


def remembered_record_id(effect_id: str, /) -> str:
    """The id a remembered belief is written at, derived from its effect record's id.

    One remember call is claimed under one effect record (ADR-0306 §5:3), whose id is
    minted before the ruling, so authorizing and the runner derive the same id without
    passing it between them.

    Args:
        effect_id: The id of the effect record the call is claimed under.

    Returns:
        The belief's id.
    """
    return f"{_RECORD_PREFIX}{effect_id}"


def remembered_proposal(
    parameters: Mapping[str, FrozenJson],
    /,
    *,
    record_id: str,
    at: datetime,
    placement: Placement | None = None,
) -> MemoryUpdateProposal:
    """The proposal one remember call makes, its support set by rule (ADR-0328 §13:2).

    Args:
        parameters: The call's arguments, the hub-filled ones included.
        record_id: The id the memory is written at (:func:`remembered_record_id`),
            whose effect record the support points at.
        at: Transaction time: when the memory is proposed (ADR-0045 §3).
        placement: Who may receive the memory, as the runner sets it by rule
            (ADR-0217 §3:12); the default where ``None``.

    Returns:
        The proposal: one memory stating ``statement``, resting on one support that
        points at the call, ``remembered_over_outside`` where the activation had read
        outside content and ``remembered`` otherwise, its ``when`` the episode's
        ``occurred_at`` where the current activation's capture holds it, and unknown
        where it does not.

    Raises:
        ValueError: If an argument is missing, of the wrong type or blank.
    """
    statement = parameters.get(STATEMENT_ARGUMENT)
    episode = parameters.get(EPISODE_ARGUMENT)
    outside = parameters.get(OUTSIDE_CONTENT_ARGUMENT)
    if not isinstance(statement, str) or not statement.strip():
        msg = "a remember call states one non-blank statement"
        raise ValueError(msg)
    if not isinstance(episode, str) or not episode.strip():
        msg = "a remember call names the activation's episode"
        raise ValueError(msg)
    if not isinstance(outside, bool):
        msg = "a remember call says whether its activation read outside content"
        raise ValueError(msg)
    support = MemorySupport(
        points_at=RememberCallPart(episode=episode, effect=_effect_of(record_id)),
        origin=SupportOrigin.REMEMBERED_OVER_OUTSIDE if outside else SupportOrigin.REMEMBERED,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        when=_occurred_at(episode),
        added_at=at,
        added_by=MemoryWriterName.REMEMBER,
    )
    record = _resting_on(record_id, statement, support, placement=placement)
    return MemoryUpdateProposal(proposed=record, rationale=_RATIONALE)


def _resting_on(
    record_id: str, statement: str, support: MemorySupport, *, placement: Placement | None
) -> Memory:
    """A memory stating ``statement`` on ``support`` alone, created citing it by ``remember``."""
    return Memory(
        id=record_id,
        content=statement,
        supports=(support,),
        operations=(
            MemoryOperation(
                kind=MemoryOperationKind.CREATE,
                cites=support.points_at,
                at=support.added_at,
                by=MemoryWriterName.REMEMBER,
            ),
        ),
        placement=Placement() if placement is None else placement,
    )


def _effect_of(record_id: str) -> str:
    """The effect record id a remembered memory's id was derived from."""
    return record_id.removeprefix(_RECORD_PREFIX)


def _occurred_at(episode: str) -> datetime | None:
    """The episode's ``occurred_at``, where the current activation's capture holds it.

    The admission write's one capture timestamp is the episode's ``occurred_at``
    (ADR-0286 §2:2), held on the activation's state; a call run where no activation is
    current, or whose episode is not the current capture's, has none to read, and the
    support's ``when`` is then unknown (ADR-0328 §4).
    """
    state = active_state()
    capture = None if state is None else state.capture
    if capture is None or capture.address != episode:
        return None
    return capture.captured_at


def _utcnow() -> datetime:
    return datetime.now(UTC)


#: The writer's rulings that write the memory. ``STORE_TEMPORARY`` rules on nothing
#: since ADR-0328 §10, and a writer refuses it.
_WRITTEN: Final = frozenset(
    {
        MemoryDecisionKind.ACCEPT,
        MemoryDecisionKind.REINFORCE,
        MemoryDecisionKind.SUPERSEDE,
    }
)


@dataclass(frozen=True, slots=True)
class NeedsYou:
    """A call on the assistant's own records that needs the user's yes (ADR-0321 §5:5).

    What a runner on acting's own-records seam answers where nothing was written
    because what the call would write needs the user first: a remember whose statement
    the memory writer's own policy asks about at write time (#2845). Acting reports it
    as ``needs_you``, never as done or not done.

    Declared here, beside its one producer, rather than in acting, whose seam it is
    an answer of: acting may import this module, and this module may not import acting,
    because the authorizing phase imports it and the phase modules are independent of
    each other (ADR-0309 §2:3).

    Attributes:
        replaces: The assertions the question shows the call replacing, as stored:
            what a yes retires, and nothing else. Empty where it replaces none.
    """

    replaces: tuple[Memory, ...] = ()


def _not_done(kind: ToolFailureKind, message: str) -> ToolResult:
    return ToolResult(outcome=ToolOutcome.FAILED, failure=ToolFailure(kind=kind, message=message))


def _placement(at: datetime) -> Placement:
    """The belief's placement: ADR-0204 §2's value over its producing round's supply.

    Reach ``OWNER`` with setter ``DERIVED``, stamped ``at``, where the current
    activation's latest round was planned over a supply that value is ``True`` of
    (ADR-0217 §3:12); the default otherwise, and where no activation is current.
    """
    state = active_state()
    if state is None or not state.planned_over_withheld:
        return Placement()
    return Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=at)


def _shown_values(values: Mapping[str, FrozenJson]) -> dict[str, FrozenJson]:
    """A remember's values as its question shows them: those the hub fills left out."""
    return {key: value for key, value in values.items() if key not in REMEMBER.system_supplied}


def _confirmed(
    proposal: MemoryUpdateProposal, call: ToolCall, asked: AskedCall
) -> MemoryUpdateProposal:
    """``proposal`` carrying the confirmation a yes to ``asked`` makes (ADR-0321 §5:2).

    Built only where the call runs under an approval whose approved part is
    ``asked``'s, and ``asked`` is a remember stating exactly what the call states;
    otherwise ``proposal`` is returned as it is, and the writer rules on it as on any
    call. ``retires`` and the frozen ``conflicts`` are exactly ``asked.replaces``, the
    assertions the question showed (§5:5), and ``question_key`` is the key of the
    proposal over them (ADR-0078 §7). The memory rests on the yes instead of the call
    (ADR-0328 §13:3): one ``confirmation`` support pointing at the yes's episode and the
    approved part, ``sure``, its ``when`` the approval's ``given.at``.
    """
    decision = call.decision
    approval = decision.approval
    part = decision.approved_part
    if (
        approval is None
        or part is None
        or part.part != asked.part
        or asked.tool.capability != REMEMBER_CAPABILITY
        or _shown_values(asked.values) != _shown_values(call.request.parameters)
    ):
        _log.info("remember_unconfirmed", stage="acting", reason="not_the_call_approved")
        return proposal
    shown = tuple(str(record_id) for record_id in asked.replaces)
    remembered = proposal.proposed
    support = MemorySupport(
        points_at=ConfirmationPart(
            episode=episode_address(approval.given.activation_id),
            asking_activation=approval.how.activation_id,
            question=part,
        ),
        origin=SupportOrigin.CONFIRMATION,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=approval.given.at,
        added_at=remembered.supports[0].added_at,
        added_by=MemoryWriterName.REMEMBER,
    )
    confirmed = _resting_on(
        remembered.id, remembered.content, support, placement=remembered.placement
    )
    asked_against = MemoryUpdateProposal(
        proposed=confirmed,
        rationale=proposal.rationale,
        sensitivity=proposal.sensitivity,
        conflicts=shown,
    )
    confirmation = UserConfirmation(
        question=part,
        question_key=asked_against.question_key,
        confirmed_at=approval.given.at,
        retires=shown,
    )
    return MemoryUpdateProposal(
        proposed=confirmed,
        rationale=proposal.rationale,
        sensitivity=proposal.sensitivity,
        conflicts=shown,
        confirmation=confirmation,
    )


class RememberCalls:
    """Run a remember call against the memory writer (ADR-0306 §3:3).

    Structurally acting's ``OwnRecordsCalls``, and its ``ApprovedOwnRecordsCalls`` for
    a remember that runs under a yes: acting awaits it to its end, with no deadline and
    no cancellation, and its outcome is what the writer answered. It answers
    ``succeeded`` where the writer wrote the belief; :class:`NeedsYou` where the writer
    asked and every assertion the question would show replaced could be read; and
    ``failed`` with a code-owned kind otherwise: never ``indeterminate``.
    """

    def __init__(
        self,
        *,
        writer: MemoryWriter,
        memory: MemoryStore | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Wire the runner to the memory write path.

        Args:
            writer: The memory writer, which finds conflicts, rules and persists.
            memory: The store the writer writes to, read for the assertions a call
                that needs you would replace (ADR-0321 §5:5). With none, a call whose
                writer asked over any conflict is not done, as no question could show
                what it replaces.
            now: The clock a proposal's transaction time is read from.
        """
        self._writer = writer
        self._memory = memory
        self._now = checked_clock(now, owner="RememberCalls")

    async def run(self, call: ToolCall) -> ToolResult | NeedsYou:
        """Write the statement ``call`` carries, and say what the writer answered.

        Args:
            call: The authorized remember call.

        Returns:
            ``succeeded`` with no output where the belief was written;
            :class:`NeedsYou` where the writer asked (ADR-0321 §5:5); ``failed``
            where the call is not a remember call, carries no effect record, is
            malformed, or the writer rejected it, could not write, or asked over an
            assertion no question could show.
        """
        return await self._run(call, None)

    async def run_approved(self, call: ToolCall, asked: AskedCall) -> ToolResult | NeedsYou:
        """Write the statement a yes approved, confirmed by that yes (ADR-0321 §5:2).

        Args:
            call: The authorized remember call, its decision naming the approval.
            asked: The asked call the yes approved, which ``call`` was rebuilt from.

        Returns:
            What :meth:`run` answers. The proposal carries the confirmation the yes
            makes, where the call is the one the yes approved.
        """
        return await self._run(call, asked)

    async def _run(self, call: ToolCall, asked: AskedCall | None) -> ToolResult | NeedsYou:
        tool = call.request.tool
        effect_id = call.decision.effect
        if tool.capability != REMEMBER_CAPABILITY or effect_id is None:
            _log.info("remember_not_done", stage="acting", reason="not_a_remember_call")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "not a claimed remember call")
        # Read before the refusal below: a clock fault is a `ValueError` too, and it is
        # this process's fault, never a malformed call (ADR-0026 §2).
        at = self._now()
        try:
            proposal = remembered_proposal(
                call.request.parameters,
                record_id=remembered_record_id(effect_id),
                at=at,
                placement=_placement(at),
            )
        except ValueError:
            _log.info("remember_not_done", stage="acting", reason="malformed")
            return _not_done(ToolFailureKind.INVALID_REQUEST, "the call's arguments are malformed")
        if asked is not None:
            proposal = _confirmed(proposal, call, asked)
        try:
            ingested = await self._writer.ingest(proposal)
        except MemoryStoreError:
            _log.warning("remember_not_done", stage="acting", reason="write_failed")
            return _not_done(ToolFailureKind.INTERNAL, "the memory write failed")
        kind = ingested.decision.kind
        if kind in _WRITTEN:
            return ToolResult(outcome=ToolOutcome.SUCCEEDED)
        if kind is MemoryDecisionKind.ASK_USER:
            return await self._asked(ingested.conflicts)
        _log.info("remember_not_done", stage="acting", reason=kind.value)
        return _not_done(ToolFailureKind.REFUSED, f"the memory policy ruled {kind.value}")

    async def _asked(self, conflicts: Sequence[str]) -> ToolResult | NeedsYou:
        """The writer asked: the call needs you, where the question can show what it replaces."""
        replaced = await self._replaced(conflicts)
        if replaced is None:
            _log.info("remember_not_done", stage="acting", reason="replaced_not_shown")
            return _not_done(
                ToolFailureKind.REFUSED,
                "the memory policy asked, over an assertion no question could show",
            )
        _log.info("remember_needs_you", stage="acting", reason="ask_user")
        return NeedsYou(replaces=replaced)

    async def _replaced(self, conflicts: Sequence[str]) -> tuple[Memory, ...] | None:
        """The assertions among ``conflicts`` a question shows replaced, as stored (§5:5).

        Every conflict the writer ruled against is read, and those the user asserted
        are kept, in the writer's order. ``None`` where one cannot be shown: no store is
        wired, the read fails, a conflict is gone so that whether it is an assertion is
        unknown, or an assertion is not a statement.
        """
        ids = tuple(dict.fromkeys(str(record_id) for record_id in conflicts))
        if not ids:
            return ()
        if self._memory is None:
            return None
        try:
            found = await self._memory.get_many(ids)
        except MemoryStoreError:
            return None
        replaced: list[Memory] = []
        for record_id in ids:
            record = found.get(record_id)
            if record is None:
                return None
            if not isinstance(record, Memory):
                # An episode is never an assertion, and never shown replaced.
                if record_band(record) is BeliefBand.ASSERTED:
                    return None
                continue
            if record.band is not BeliefBand.ASSERTED:
                continue
            replaced.append(record)
        return tuple(replaced)

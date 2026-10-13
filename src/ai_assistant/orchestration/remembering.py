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

**The written belief's provenance is set by rule** (ADR-0106 §1), never by the model.
The statement is planning's own wording, so it is a belief this system worked out:
``INFERRED``, in the ``DERIVED`` band, at :data:`REMEMBERED_CONFIDENCE`, citing the
activation's episode as its evidence, and carrying ``derived_from_external`` exactly
where the activation had read outside content. It is never ``USER_ASSERTED``: a model's
paraphrase claiming the user's own standing is the laundering ADR-0098 §4 forbids. A
tainted derived proposal is then never committed unconfirmed (ADR-0106 §6), so in an
activation that read outside content ``MemoryPolicy`` asks or rejects, and authorizing
turns that into *needs you* or *not done* (ADR-0306 §4:3, §4:8 to §4:9).

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
asks its own policy over them (ADR-0028). A ruling there that writes nothing, an ask or a
reject, is a call not done, and nothing is written: ADR-0306 §4:3's *memory it rules to
ask about is not written* holds at both rulings.

**It logs stage and code-owned reason only**, never the statement (ADR-0275 §8).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    ToolCost,
    ToolDefinition,
    ToolFailure,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.activation_state import active_state

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ai_assistant.core.protocols import MemoryWriter
    from ai_assistant.core.types import FrozenJson, ToolCall

__all__ = [
    "EPISODE_ARGUMENT",
    "OUTSIDE_CONTENT_ARGUMENT",
    "REMEMBER",
    "REMEMBERED_CONFIDENCE",
    "REMEMBER_CAPABILITY",
    "STATEMENT_ARGUMENT",
    "STATEMENT_MAX_CHARS",
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

#: The confidence a remembered statement is written at. Below 1.0, because a derived
#: belief is never certain (ADR-0072 §3), and above every default floor below which a
#: policy stores a belief only tentatively.
REMEMBERED_CONFIDENCE: Final = 0.8

_RATIONALE: Final = "planning remembered this statement during an activation"

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
    return f"remembered:{effect_id}"


def remembered_proposal(
    parameters: Mapping[str, FrozenJson],
    /,
    *,
    record_id: str,
    at: datetime,
    placement: Placement | None = None,
) -> MemoryUpdateProposal:
    """The proposal one remember call makes, with its provenance set by rule.

    Args:
        parameters: The call's arguments, the hub-filled ones included.
        record_id: The id the belief is written at (:func:`remembered_record_id`).
        at: Transaction time: when the belief is proposed (ADR-0045 §3).
        placement: Who may receive the belief, as the runner sets it by rule
            (ADR-0217 §3:12); the default where ``None``.

    Returns:
        The proposal: one ``SemanticMemory`` stating ``statement``, ``INFERRED`` at
        :data:`REMEMBERED_CONFIDENCE`, citing the episode, marked where the activation
        had read outside content.

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
    provenance = Provenance(
        source=MemorySource.INFERRED,
        confidence=REMEMBERED_CONFIDENCE,
        evidence=(episode,),
        last_updated=at,
        derived_from_external=outside,
    )
    record = SemanticMemory(
        id=record_id,
        content=statement,
        fact=statement,
        provenance=provenance,
        placement=Placement() if placement is None else placement,
    )
    return MemoryUpdateProposal(proposed=record, rationale=_RATIONALE)


def _utcnow() -> datetime:
    return datetime.now(UTC)


#: The writer's rulings that write the belief, at once or tentatively.
_WRITTEN: Final = frozenset(
    {
        MemoryDecisionKind.ACCEPT,
        MemoryDecisionKind.REINFORCE,
        MemoryDecisionKind.SUPERSEDE,
        MemoryDecisionKind.STORE_TEMPORARY,
    }
)


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


class RememberCalls:
    """Run a remember call against the memory writer (ADR-0306 §3:3).

    Structurally acting's ``OwnRecordsCalls``: acting awaits it to its end, with no
    deadline and no cancellation, and its outcome is what the writer answered. It
    answers ``succeeded`` where the writer wrote the belief, and ``failed`` with a
    code-owned kind otherwise: never ``indeterminate``.
    """

    def __init__(self, *, writer: MemoryWriter, now: Callable[[], datetime] = _utcnow) -> None:
        """Wire the runner to the memory write path.

        Args:
            writer: The memory writer, which finds conflicts, rules and persists.
            now: The clock a proposal's transaction time is read from.
        """
        self._writer = writer
        self._now = checked_clock(now, owner="RememberCalls")

    async def run(self, call: ToolCall) -> ToolResult:
        """Write the statement ``call`` carries, and say what the writer answered.

        Args:
            call: The authorized remember call.

        Returns:
            ``succeeded`` with no output where the belief was written; ``failed``
            where the call is not a remember call, carries no effect record, is
            malformed, or the writer wrote nothing or could not write.
        """
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
        try:
            ingested = await self._writer.ingest(proposal)
        except MemoryStoreError:
            _log.warning("remember_not_done", stage="acting", reason="write_failed")
            return _not_done(ToolFailureKind.INTERNAL, "the memory write failed")
        kind = ingested.decision.kind
        if kind in _WRITTEN:
            return ToolResult(outcome=ToolOutcome.SUCCEEDED)
        _log.info("remember_not_done", stage="acting", reason=kind.value)
        return _not_done(ToolFailureKind.REFUSED, f"the memory policy ruled {kind.value}")

"""Shared domain types used across subsystem boundaries.

These are deliberately small, immutable-ish pydantic models that flow *between*
subsystems. They belong to no single subsystem, so they live in `core` where
everyone can depend on them. Keep this module free of behaviour — data only.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import AfterValidator

# A user-asserted memory is, by definition, fully trusted.
_FULL_CONFIDENCE = 1.0

Embedding = Sequence[float]
"""A dense vector embedding of a piece of text (see ADR-0006)."""


class Role(StrEnum):
    """Who authored a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single turn in a conversation, provider-independent."""

    role: Role
    content: str
    name: str | None = Field(default=None, description="Optional author/tool name.")


class MemorySource(StrEnum):
    """Where a memory came from — the basis for how much to trust it."""

    USER_ASSERTED = "user_asserted"
    OBSERVED = "observed"
    INFERRED = "inferred"
    EXTERNAL = "external"


class MemoryKind(StrEnum):
    """The category of a memory record (the discriminated-union tag)."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"


class Provenance(BaseModel):
    """Where a memory came from and how much it should be trusted.

    Attaching this to every record is what distinguishes user-asserted facts
    (the profile) from inferred beliefs (the user model), and what stops one
    unusual interaction from hardening into a permanent, wrong "preference".
    """

    source: MemorySource
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Belief strength in [0, 1]; user-asserted records are 1.0.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="References (e.g. episode ids) supporting this record.",
    )
    last_updated: datetime = Field(description="When this belief was last revised (tz-aware).")

    @model_validator(mode="after")
    def _user_asserted_is_certain(self) -> Provenance:
        """User-asserted memories must carry full confidence."""
        if self.source is MemorySource.USER_ASSERTED and self.confidence != _FULL_CONFIDENCE:
            msg = "USER_ASSERTED provenance must have confidence 1.0"
            raise ValueError(msg)
        return self


class MemoryBase(BaseModel):
    """Fields shared by every memory record, regardless of kind."""

    id: str
    content: str = Field(description="Canonical text rendering, used for retrieval.")
    provenance: Provenance
    score: float | None = Field(
        default=None,
        description="Relevance score, populated by retrieval; None when stored.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Retention deadline after which the record is forgotten (ADR-0004); "
            "a naive datetime is interpreted as UTC."
        ),
    )

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_utc_aware(cls, value: datetime | None) -> datetime | None:
        """Normalise the retention deadline to a UTC-aware datetime.

        Retention is enforced by comparing ``expires_at`` against a UTC clock, so
        a naive value would either crash the comparison or be read in host-local
        time. Assuming UTC keeps every store consistent.
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class EpisodicMemory(MemoryBase):
    """Something that happened: an event, with who and how it turned out."""

    kind: Literal["episodic"] = "episodic"
    occurred_at: datetime
    participants: list[str] = Field(default_factory=list)
    outcome: str | None = None
    importance: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticMemory(MemoryBase):
    """A durable fact about the user or their world."""

    kind: Literal["semantic"] = "semantic"
    fact: str
    valid_until: datetime | None = Field(
        default=None,
        description="Optional expiry after which the fact is no longer assumed true.",
    )


class PreferenceMemory(MemoryBase):
    """A user preference, optionally scoped to a context."""

    kind: Literal["preference"] = "preference"
    preference: str
    context: str | None = None
    strength: float = Field(default=0.5, ge=0.0, le=1.0)


class ProceduralMemory(MemoryBase):
    """A learned workflow: how the user likes a situation handled."""

    kind: Literal["procedural"] = "procedural"
    situation: str
    steps: list[str] = Field(default_factory=list)


MemoryRecord = Annotated[
    EpisodicMemory | SemanticMemory | PreferenceMemory | ProceduralMemory,
    Field(discriminator="kind"),
]
"""A unit of long-term memory: one of the four typed kinds, tagged by ``kind``."""


class DataTier(StrEnum):
    """Sensitivity classification of stored data (see ADR-0004)."""

    SECRET = "secret"  # noqa: S105  # Tier 0 tier name, not a credential value.
    PERSONAL = "personal"  # Tier 1: PII, memories, user-model facts.
    OPERATIONAL = "operational"  # Tier 2: non-sensitive settings, caches.


class MemoryUpdateProposal(BaseModel):
    """A proposed change to memory, awaiting a policy decision.

    The model never writes memory directly: it emits a proposal that a
    deterministic :class:`~ai_assistant.core.protocols.MemoryPolicy` disposes of.
    """

    proposed: MemoryRecord
    rationale: str = Field(description="Why this memory is being proposed.")
    sensitivity: DataTier = Field(
        default=DataTier.PERSONAL,
        description="How sensitive the proposed memory is.",
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="Ids of existing records this proposal contradicts (from the conflict check).",
    )


class MemoryDecisionKind(StrEnum):
    """The possible rulings a memory policy can make on a proposal."""

    ACCEPT = "accept"
    REJECT = "reject"
    MERGE = "merge"
    ASK_USER = "ask_user"
    STORE_TEMPORARY = "store_temporary"


class MemoryDecision(BaseModel):
    """A policy's ruling on a :class:`MemoryUpdateProposal`."""

    kind: MemoryDecisionKind
    reason: str = Field(description="Human-readable justification, for transparency.")
    merge_into: str | None = Field(
        default=None,
        description="Target record id; required when ``kind`` is MERGE.",
    )
    ttl: timedelta | None = Field(
        default=None,
        description="Retention window; required when ``kind`` is STORE_TEMPORARY.",
    )

    @model_validator(mode="after")
    def _outcome_fields_are_consistent(self) -> MemoryDecision:
        """Ensure outcome-specific fields match the decision kind.

        Each kind requires its own field and forbids the other's, so a decision
        cannot carry contradictory state (e.g. an ``ACCEPT`` with a ``ttl``). A
        temporary store's ``ttl`` must be positive, since a non-positive window
        would produce an already-expired record.
        """
        if self.kind is MemoryDecisionKind.MERGE:
            if self.merge_into is None:
                msg = "MERGE decision requires merge_into"
                raise ValueError(msg)
        elif self.merge_into is not None:
            msg = "merge_into is only valid for a MERGE decision"
            raise ValueError(msg)

        if self.kind is MemoryDecisionKind.STORE_TEMPORARY:
            if self.ttl is None:
                msg = "STORE_TEMPORARY decision requires ttl"
                raise ValueError(msg)
            if self.ttl <= timedelta(0):
                msg = "STORE_TEMPORARY decision requires a positive ttl"
                raise ValueError(msg)
        elif self.ttl is not None:
            msg = "ttl is only valid for a STORE_TEMPORARY decision"
            raise ValueError(msg)

        return self


class MemoryIngestResult(BaseModel):
    """The outcome of ingesting a :class:`MemoryUpdateProposal`."""

    decision: MemoryDecision
    record_id: str | None = Field(
        default=None,
        description="Id of the record written or merged, or None if nothing was stored.",
    )


class TimeOfDay(StrEnum):
    """A coarse bucket of the local time of day."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class CurrentContext(BaseModel):
    """The situational "right now" that shapes a response (see ADR-0008).

    A temporal core today; future facets (calendar, tasks, device, ...) are added
    as optional fields when their source subsystems exist. Advisory, not durable
    state: it is assembled fresh per request and never stored.
    """

    model_config = ConfigDict(extra="forbid")

    now: datetime = Field(description="The tz-aware reference instant for this context.")
    time_of_day: TimeOfDay
    is_weekend: bool
    within_working_hours: bool = Field(
        description="Whether the local time falls in the configured working-hours window.",
    )

    @field_validator("now")
    @classmethod
    def _now_is_utc_aware(cls, value: datetime) -> datetime:
        """Normalise the reference instant to UTC-aware (a naive value is UTC).

        The context is compared against UTC-aware timestamps downstream, so a
        naive ``now`` would risk a naive-vs-aware ``TypeError``; assuming UTC
        keeps it consistent with the rest of the system.
        """
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class FeedbackKind(StrEnum):
    """The kind of explicit feedback the user gave (see ADR-0009)."""

    CORRECTION = "correction"
    PREFERENCE = "preference"


class FeedbackEvent(BaseModel):
    """A unit of explicit, memory-affecting feedback (see ADR-0009).

    The learning subsystem turns this into a :class:`MemoryUpdateProposal`. It
    carries ``memory_kind`` so a correction lands in the right typed record (a
    fact becomes a :class:`SemanticMemory`, not a preference).
    """

    kind: FeedbackKind
    memory_kind: MemoryKind = Field(description="The typed memory this feedback establishes.")
    content: str = Field(description="Canonical text of the feedback, e.g. 'office is in Boston'.")
    subject: str | None = Field(
        default=None, description="Optional scope/context, e.g. 'email tone'."
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Interaction/episode ids supporting this, carried into provenance.",
    )
    created_at: datetime = Field(description="When the feedback was given (tz-aware).")

    @field_validator("content")
    @classmethod
    def _content_is_present(cls, value: str) -> str:
        """Require non-empty content, so feedback cannot become a blank memory."""
        stripped = value.strip()
        if not stripped:
            msg = "feedback content must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        """Normalise the timestamp to UTC (a naive value is assumed UTC)."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


type FrozenJson = str | int | float | bool | None | Sequence[FrozenJson] | Mapping[str, FrozenJson]
"""A JSON value that is immutable all the way down (see ADR-0014 §2).

Plan parameters and step outputs are persisted and exported, so they must be
serialisable; they are also part of an audit record, so they must not be
editable after the fact. ``JsonValue`` alone gives the first property but not
the second — pydantic's ``frozen=True`` stops field *reassignment* and does
nothing about mutating a ``dict`` a field holds.
"""


class FrozenDict(Mapping[str, "FrozenJson"]):
    """An immutable, hashable, copyable string-keyed mapping.

    ``MappingProxyType`` is the obvious way to make a mapping read-only, but it
    can be neither pickled nor deep-copied, which would make any model holding
    one fail ``model_copy(deep=True)`` — too sharp an edge for a type this
    widely shared.

    The contents are held as a **tuple of pairs**, not a dict, and attribute
    assignment is refused. A private ``dict`` would still be a mutable object
    reachable as ``parameters._data``, which is a real bypass of an audit
    record's immutability, not merely a rude one. Lookup is therefore a linear
    scan; plan parameters are a handful of keys, so that is cheaper than
    carrying a mutable index alongside the immutable truth.
    """

    __slots__ = ("_items",)

    _items: tuple[tuple[str, FrozenJson], ...]

    def __init__(self, data: Mapping[str, FrozenJson] | None = None, /) -> None:
        """Store ``data``'s pairs, detached from whatever the caller keeps."""
        object.__setattr__(self, "_items", tuple((data or {}).items()))

    def __setattr__(self, name: str, value: object) -> None:
        """Refuse attribute assignment, including rebinding the backing tuple."""
        msg = f"{type(self).__name__} is immutable"
        raise AttributeError(msg)

    def __delattr__(self, name: str) -> None:
        """Refuse attribute deletion, for the same reason as assignment."""
        msg = f"{type(self).__name__} is immutable"
        raise AttributeError(msg)

    def __getitem__(self, key: str) -> FrozenJson:
        """Return the value for ``key``, raising ``KeyError`` if absent."""
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        """Iterate over the keys, in insertion order."""
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        """Return the number of keys."""
        return len(self._items)

    def __repr__(self) -> str:
        """Return a dict-like representation of the contents."""
        return f"FrozenDict({dict(self._items)!r})"

    def __eq__(self, other: object) -> bool:
        """Compare equal to any mapping with the same contents."""
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        """Hash by contents; possible only because every value is itself frozen."""
        return hash(frozenset(self._items))

    def __reduce__(self) -> tuple[type[FrozenDict], tuple[dict[str, FrozenJson]]]:
        """Support pickling (and, via it, ``copy.deepcopy``)."""
        return (FrozenDict, (dict(self._items),))


def _freeze_json(value: FrozenJson) -> FrozenJson:
    """Convert a JSON value into an immutable one, recursively.

    Mappings become :class:`FrozenDict` and lists become tuples, so the
    immutability guarantee is depth-independent rather than true only at the top
    level.

    Raises:
        ValueError: If a non-finite float is encountered. ``NaN`` and the
            infinities satisfy ``float`` but have no JSON representation, so
            they would silently change value on the way through the store or an
            export — exactly the unportable-value problem this type exists to
            prevent, just further down.
    """
    if isinstance(value, Mapping):
        return FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not isfinite(value):
        msg = f"{value!r} has no JSON representation, so it cannot be stored or exported"
        raise ValueError(msg)
    return value


def _thaw_json(value: Any) -> Any:
    """Convert a frozen JSON value back to plain containers for serialisation.

    ``mappingproxy`` is not serialisable by pydantic-core, so the immutable
    representation is undone on the way out. The frozen form is how the value is
    *held*; plain JSON is how it is *written*.
    """
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thaw_json(item) for item in value]
    return value


type FrozenJsonValue = Annotated[
    FrozenJson, AfterValidator(_freeze_json), PlainSerializer(_thaw_json)
]
"""A single :data:`FrozenJson` value, frozen on validation and thawed on dump."""

type FrozenJsonMapping = Annotated[
    Mapping[str, FrozenJson], AfterValidator(_freeze_json), PlainSerializer(_thaw_json)
]
"""A string-keyed mapping of :data:`FrozenJson` values, frozen on validation."""

_EMPTY_PARAMS: Mapping[str, FrozenJson] = FrozenDict()


def _non_blank(value: str) -> str:
    """Reject a blank identifier, returning it stripped.

    An empty ``approval_ref`` or ``bound_tool`` is worse than a missing one: it
    satisfies "a reference is present" while identifying nothing, so a step
    could look authorised and audited while being neither.
    """
    stripped = value.strip()
    if not stripped:
        msg = "identifier must not be blank"
        raise ValueError(msg)
    return stripped


type Identifier = Annotated[str, AfterValidator(_non_blank)]
"""A non-blank, stripped identifier."""


class GoalStatus(StrEnum):
    """Where a goal stands (see ADR-0014 §1)."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"
    BLOCKED = "blocked"


class Goal(BaseModel):
    """A durable objective the assistant is working toward (see ADR-0014 §1).

    Deliberately not the same thing as a user utterance: a request is transient,
    a goal outlives any one conversation and is what makes a plan resumable and
    a notification justifiable. It carries :class:`Provenance` for the same
    reason every memory does — a goal the system *inferred* must never be
    indistinguishable from one the user *stated*.
    """

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    statement: str = Field(description="Canonical text rendering of the objective.")
    status: GoalStatus = GoalStatus.ACTIVE
    provenance: Provenance
    created_at: datetime = Field(description="When the goal was recorded (tz-aware).")
    deadline: datetime | None = Field(
        default=None,
        description="Optional target date; a naive datetime is interpreted as UTC.",
    )

    @field_validator("statement")
    @classmethod
    def _statement_is_present(cls, value: str) -> str:
        """Require a non-empty statement, so a goal cannot be a blank objective."""
        stripped = value.strip()
        if not stripped:
            msg = "goal statement must not be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("created_at", "deadline")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        """Normalise timestamps to UTC (a naive value is assumed UTC)."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class PlanStep(BaseModel):
    """One step of an :class:`ActionPlan` (see ADR-0014 §2).

    A step names a **capability** — what must be done — rather than a tool. That
    keeps the pipeline's ``planning → tool selection`` boundary intact: the
    selection stage still gets to weigh a tool's risk and reversibility, instead
    of ratifying a choice the planner already made.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    intent: str = Field(description="Human-readable purpose of this step.")
    capability: Identifier = Field(description="What must be done, e.g. 'send_email'.")
    parameters: FrozenJsonMapping = Field(
        default=_EMPTY_PARAMS,
        description="Capability arguments; frozen, and validated against the tool at selection.",
    )


class ActionPlan(BaseModel):
    """A frozen record of what the assistant decided to do (see ADR-0014 §2).

    ``frozen=True`` is not decoration: it is what makes the plan an auditable
    record of a decision. Re-planning produces a *new* plan with a new ``id``
    rather than mutating one out from under an in-flight execution, so "what did
    the system decide to do, and when" stays answerable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    goal_id: Identifier
    steps: tuple[PlanStep, ...]
    created_at: datetime = Field(description="When the plan was produced (tz-aware).")
    rationale: str | None = Field(
        default=None, description="Why the planner chose these steps, for transparency."
    )

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: datetime) -> datetime:
        """Normalise the timestamp to UTC (a naive value is assumed UTC)."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("steps")
    @classmethod
    def _step_ids_are_unique(cls, value: tuple[PlanStep, ...]) -> tuple[PlanStep, ...]:
        """Reject duplicate step ids.

        Execution state addresses steps by id, so two steps sharing one would
        make a transition ambiguous about which step it ruled on.
        """
        seen = {step.id for step in value}
        if len(seen) != len(value):
            msg = "plan step ids must be unique within a plan"
            raise ValueError(msg)
        return value


class StepStatus(StrEnum):
    """Where one step of an execution stands (see ADR-0014 §4)."""

    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    INDETERMINATE = "indeterminate"


class SkipReason(StrEnum):
    """Why a step was skipped rather than run (see ADR-0014 §4)."""

    APPROVAL_DENIED = "approval_denied"
    UNMET_DEPENDENCY = "unmet_dependency"
    NO_CAPABLE_TOOL = "no_capable_tool"
    SUPERSEDED = "superseded"


#: Statuses that mean the step was claimed and a tool call may have happened.
_CLAIMED_STATUSES = frozenset(
    {
        StepStatus.RUNNING,
        StepStatus.SUCCEEDED,
        StepStatus.FAILED,
        StepStatus.INDETERMINATE,
    }
)

#: Statuses that need nothing further — the step is done (see ADR-0014 §4).
#: ``FAILED`` is not among them (it may still be retried) and neither is
#: ``INDETERMINATE`` (it awaits explicit resolution).
TERMINAL_STEP_STATUSES = frozenset({StepStatus.SUCCEEDED, StepStatus.SKIPPED})

#: Statuses that mean a tool call may be in progress *right now*, so erasing the
#: record would orphan a side effect (see ADR-0014 §5).
_LIVE_STATUSES = frozenset({StepStatus.RUNNING})

#: Statuses whose record must say when the step stopped.
_FINISHED_STATUSES = frozenset({StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE})


class StepExecution(BaseModel):
    """What actually happened to one :class:`PlanStep` (see ADR-0014 §3).

    Kept separate from the plan so the audit record does not mutate as execution
    proceeds, and so recovery is *loading* state rather than reconstructing
    intent. Carries what a restarted executor needs in order not to redo work:
    the step's ``output``, the ``approval_ref`` for the permission decision that
    cleared it, and the tool that actually ran.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: Identifier
    status: StepStatus = StepStatus.PENDING
    attempts: int = Field(default=0, ge=0, description="How many times this step has been claimed.")
    bound_tool: Identifier | None = Field(
        default=None, description="The tool the selection stage chose, once it has."
    )
    output: FrozenJsonValue = Field(
        default=None, description="The tool's result; only meaningful once SUCCEEDED."
    )
    approval_ref: Identifier | None = Field(
        default=None,
        description="Id of the permissions/ decision that cleared this step (ADR-0004 §7).",
    )
    skip_reason: SkipReason | None = Field(
        default=None, description="Why the step was skipped; required when SKIPPED."
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = Field(default=None, description="Failure detail; required when FAILED.")

    @model_validator(mode="after")
    def _claimed_step_is_authorised(self) -> StepExecution:
        """Require the marks of a claim on any step that may have caused an effect.

        The important one is ``approval_ref``: a claimed step must be
        correlatable with the permission decision that authorised it, including
        when that decision was an automatic grant with no prompt shown — which
        is precisely the case ADR-0004 §7 most needs covered, since a silent
        action is the one a user is least able to recall consenting to.
        """
        if self.status not in _CLAIMED_STATUSES:
            return self

        required = {
            "approval_ref": self.approval_ref,
            "bound_tool": self.bound_tool,
            "started_at": self.started_at,
        }
        for name, value in required.items():
            if value is None:
                msg = f"a {self.status} step requires {name}"
                raise ValueError(msg)

        if self.attempts < 1:
            msg = f"a {self.status} step requires at least one attempt"
            raise ValueError(msg)

        return self

    @model_validator(mode="after")
    def _unclaimed_step_carries_no_history(self) -> StepExecution:
        """Forbid the marks of a claim on a step that has not been claimed.

        Without this a ``PENDING`` step could be built with ``attempts=1000``
        and a ``started_at``, and since the retry ceiling is only consulted on
        the way out of ``FAILED``, that fabricated history would sail past it.
        A status that has never run must look like it.
        """
        if self.status in _CLAIMED_STATUSES:
            return self

        if self.attempts != 0:
            msg = f"a {self.status} step has not run, so it cannot have attempts"
            raise ValueError(msg)
        if self.started_at is not None:
            msg = f"a {self.status} step has not run, so it cannot have started_at"
            raise ValueError(msg)

        if self.status is StepStatus.PENDING and (
            self.approval_ref is not None or self.bound_tool is not None
        ):
            msg = "a PENDING step predates tool selection and approval"
            raise ValueError(msg)

        if self.status is StepStatus.AWAITING_APPROVAL:
            if self.bound_tool is None:
                msg = "an AWAITING_APPROVAL step requires the bound_tool being approved"
                raise ValueError(msg)
            if self.approval_ref is not None:
                msg = "an AWAITING_APPROVAL step is undecided, so it has no approval_ref"
                raise ValueError(msg)

        return self

    @model_validator(mode="after")
    def _outcome_fields_match_status(self) -> StepExecution:
        """Ensure the outcome fields are consistent with the status.

        Makes the contradictory combinations unrepresentable rather than merely
        undocumented — a SKIPPED step carrying an error, say, or an output on a
        step that never ran.
        """
        if self.status is StepStatus.SKIPPED:
            if self.skip_reason is None:
                msg = "a SKIPPED step requires a skip_reason"
                raise ValueError(msg)
        elif self.skip_reason is not None:
            msg = "skip_reason is only valid for a SKIPPED step"
            raise ValueError(msg)

        if self.status is StepStatus.FAILED:
            if self.error is None:
                msg = "a FAILED step requires an error"
                raise ValueError(msg)
        elif self.error is not None:
            msg = "error is only valid for a FAILED step"
            raise ValueError(msg)

        if self.output is not None and self.status is not StepStatus.SUCCEEDED:
            msg = "output is only valid for a SUCCEEDED step"
            raise ValueError(msg)

        return self

    @model_validator(mode="after")
    def _finished_at_matches_status(self) -> StepExecution:
        """Require a stop time on exactly the statuses that have stopped.

        Both directions matter: a completed step without ``finished_at`` is an
        incomplete audit record, and a ``PENDING`` or ``RUNNING`` step *with*
        one claims to have finished while still outstanding.
        """
        if self.status in _FINISHED_STATUSES:
            if self.finished_at is None:
                msg = f"a {self.status} step requires finished_at"
                raise ValueError(msg)
        elif self.finished_at is not None:
            msg = f"a {self.status} step has not finished, so it cannot have finished_at"
            raise ValueError(msg)

        return self

    @field_validator("started_at", "finished_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None) -> datetime | None:
        """Normalise timestamps to UTC (a naive value is assumed UTC)."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ExecutionState(BaseModel):
    """The durable, resumable state of one run of an :class:`ActionPlan`.

    Positionally one-to-one with the plan's steps. ``version`` is the
    optimistic-concurrency token: a write succeeds only if the stored version
    still matches the one the writer read, so two workers cannot both claim the
    same step and run a non-idempotent tool twice (ADR-0014 §5).
    """

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    plan_id: Identifier
    steps: tuple[StepExecution, ...]
    version: int = Field(default=0, ge=0, description="Optimistic-concurrency token.")
    updated_at: datetime = Field(description="When this state was last written (tz-aware).")

    @property
    def is_active(self) -> bool:
        """Whether any step still needs something done to it.

        True for a ``FAILED`` step (it may be retried) and an ``INDETERMINATE``
        one (it awaits resolution), so a restarting system finds them via
        ``active_executions``. This is *outstanding work*, which is a wider
        question than :attr:`has_live_step`.
        """
        return any(step.status not in TERMINAL_STEP_STATUSES for step in self.steps)

    @property
    def has_live_step(self) -> bool:
        """Whether a tool call may be in progress right now.

        This — not :attr:`is_active` — is what makes erasure unsafe, because the
        hazard is destroying the record a running executor is about to commit
        against. Blocking deletion on ``is_active`` instead would be a trap: a
        step that failed permanently, or one left ``INDETERMINATE``, is never
        going to become inactive on its own, so the goal could never be deleted.
        """
        return any(step.status in _LIVE_STATUSES for step in self.steps)

    def step(self, step_id: str) -> StepExecution | None:
        """Return the execution record for ``step_id``, or ``None`` if absent."""
        return next((step for step in self.steps if step.step_id == step_id), None)

    @field_validator("steps")
    @classmethod
    def _step_ids_are_unique(cls, value: tuple[StepExecution, ...]) -> tuple[StepExecution, ...]:
        """Reject duplicate step ids, which would make a transition ambiguous."""
        seen = {step.step_id for step in value}
        if len(seen) != len(value):
            msg = "execution step ids must be unique within an execution"
            raise ValueError(msg)
        return value

    @field_validator("updated_at")
    @classmethod
    def _updated_at_is_utc(cls, value: datetime) -> datetime:
        """Normalise the timestamp to UTC (a naive value is assumed UTC)."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class StepTransition(BaseModel):
    """A request to move one step to a new status (see ADR-0014 §5).

    The store's only write path. Taking a command rather than a caller-built
    :class:`ExecutionState` is what makes the transition graph *authoritative*:
    there is no Protocol-level way to persist a state the tracker would have
    rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: Identifier
    step_id: Identifier
    to_status: StepStatus
    expected_version: int = Field(ge=0, description="Version the caller computed this against.")
    bound_tool: Identifier | None = None
    approval_ref: Identifier | None = None
    output: FrozenJsonValue = None
    skip_reason: SkipReason | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _fields_match_target_status(self) -> StepTransition:
        """Reject a transition whose payload cannot belong to its target status.

        Only the payload is checked here — whether the move is legal *from the
        step's current status* needs the stored state, so it belongs to the
        tracker, not to the type.
        """
        if self.to_status is StepStatus.SKIPPED:
            if self.skip_reason is None:
                msg = "a transition to SKIPPED requires a skip_reason"
                raise ValueError(msg)
        elif self.skip_reason is not None:
            msg = "skip_reason is only valid for a transition to SKIPPED"
            raise ValueError(msg)

        if self.to_status is StepStatus.FAILED:
            if self.error is None:
                msg = "a transition to FAILED requires an error"
                raise ValueError(msg)
        elif self.error is not None:
            msg = "error is only valid for a transition to FAILED"
            raise ValueError(msg)

        if self.output is not None and self.to_status is not StepStatus.SUCCEEDED:
            msg = "output is only valid for a transition to SUCCEEDED"
            raise ValueError(msg)

        return self


class GoalDeletion(BaseModel):
    """The outcome of deleting a goal and its plan history (see ADR-0014 §5).

    Structured rather than a bare ``bool`` because the contract has two things
    to report that a boolean cannot carry: that deletion was refused because
    work is in flight, and that it erased a step whose side effect may have
    completed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    deleted: bool
    plans_removed: int = Field(default=0, ge=0)
    executions_removed: int = Field(default=0, ge=0)
    blocked_by: tuple[str, ...] = Field(
        default=(),
        description="Ids of still-active executions; non-empty exactly when refused.",
    )
    indeterminate_steps: tuple[str, ...] = Field(
        default=(),
        description="Erased steps whose side effect may have landed — surface these to the user.",
    )

    @model_validator(mode="after")
    def _refusal_is_explained(self) -> GoalDeletion:
        """Tie ``deleted`` to ``blocked_by`` so a refusal always names its cause."""
        if self.deleted and self.blocked_by:
            msg = "a successful deletion cannot be blocked_by anything"
            raise ValueError(msg)
        if not self.deleted and not self.blocked_by:
            msg = "a refused deletion must name the executions that blocked it"
            raise ValueError(msg)
        return self


class PlanExport(BaseModel):
    """A portable snapshot of planning state (see ADR-0014 §5, ADR-0004 §6).

    Flat, not nested: relationships travel as the ids already on the records, so
    a plan whose goal has been deleted stays representable. Complete and
    internally consistent — every ``goal_id``/``plan_id`` referenced by an
    included record resolves within the same export.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(
        default=1,
        ge=1,
        description="Shape of this export; explicit because an export outlives the code.",
    )
    exported_at: datetime
    goals: tuple[Goal, ...] = ()
    plans: tuple[ActionPlan, ...] = ()
    executions: tuple[ExecutionState, ...] = ()

    @field_validator("exported_at")
    @classmethod
    def _exported_at_is_utc(cls, value: datetime) -> datetime:
        """Normalise the timestamp to UTC (a naive value is assumed UTC)."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _references_resolve_within_the_export(self) -> PlanExport:
        """Enforce the completeness this export documents rather than assuming it.

        An export is the artifact a user takes elsewhere, so a dangling
        ``goal_id`` is not a detail — it is a plan whose purpose has been lost,
        discovered only by whoever tries to read it back. Ids must also be
        unique, since a duplicate makes a reference ambiguous.
        """
        goal_ids = {goal.id for goal in self.goals}
        plan_ids = {plan.id for plan in self.plans}
        execution_ids = {execution.id for execution in self.executions}

        for label, records, ids in (
            ("goal", self.goals, goal_ids),
            ("plan", self.plans, plan_ids),
            ("execution", self.executions, execution_ids),
        ):
            if len(ids) != len(records):
                msg = f"export contains duplicate {label} ids"
                raise ValueError(msg)

        dangling_plans = sorted(plan.id for plan in self.plans if plan.goal_id not in goal_ids)
        if dangling_plans:
            msg = f"export has plans whose goal is missing: {', '.join(dangling_plans)}"
            raise ValueError(msg)

        dangling_executions = sorted(
            execution.id for execution in self.executions if execution.plan_id not in plan_ids
        )
        if dangling_executions:
            msg = f"export has executions whose plan is missing: {', '.join(dangling_executions)}"
            raise ValueError(msg)

        return self

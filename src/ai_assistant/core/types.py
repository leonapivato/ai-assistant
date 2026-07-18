"""Shared domain types used across subsystem boundaries.

These are deliberately small, immutable-ish pydantic models that flow *between*
subsystems. They belong to no single subsystem, so they live in `core` where
everyone can depend on them. Keep this module free of behaviour — data only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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

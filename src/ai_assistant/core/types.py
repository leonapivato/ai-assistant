"""Shared domain types used across subsystem boundaries.

These are deliberately small, immutable-ish pydantic models that flow *between*
subsystems. They belong to no single subsystem, so they live in `core` where
everyone can depend on them.

This module holds no **subsystem logic**; it may hold semantics **intrinsic** to
a type it defines — computable from the type's own declaration, independent of
policy, configuration, context or a clock, and the same answer for every
consumer (ADR-0016 §2, amending ADR-0014 §4). Severity ordering qualifies; a
state-transition graph does not, which is why that one lives in ``planning``.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import AfterValidator

# A user-asserted memory is, by definition, fully trusted.
_FULL_CONFIDENCE = 1.0

Embedding = Sequence[float]
"""A dense vector embedding of a piece of text (see ADR-0006)."""


def describe_untrusted(value: object) -> str:
    """``repr`` of an untrusted value, for an error message, never raising.

    ``datetime.__repr__`` embeds ``repr(tzinfo)``, so a hostile ``tzinfo`` can
    raise from inside the very message that reports it — turning the
    field-naming ``ValueError`` this module promises into whatever that
    ``__repr__`` threw, from inside an ``except`` block. The diagnostic must not
    be able to destroy the diagnosis.

    Shared with :func:`ai_assistant.core.clock.checked_clock`, which owes the
    same promise about its own owner-labelled ``ValueError`` (ADR-0026 §2).

    Args:
        value: Anything at all, including a value that cannot describe itself.

    Returns:
        ``repr(value)``, or a fixed placeholder if that raised.
    """
    try:
        return repr(value)
    except Exception:  # the value cannot describe itself; say so and move on
        return "<a value whose repr() failed>"


#: What a value expressed in UTC must report as its offset.
_NO_OFFSET = timedelta(0)


def canonical_utc(value: object) -> datetime | None:
    """Rebuild ``value`` as a plain ``datetime`` in UTC, or ``None`` if it is not one.

    **This is `core`'s one canonicaliser** (ADR-0030 §4). Both validating instant
    seams reach it and neither carries its own: :data:`UtcInstant`'s validator
    below, and :func:`ai_assistant.core.clock.checked_clock`. A second
    implementation of this test anywhere in `core` or a subsystem is forbidden —
    a rule in two places with two test suites is two rules waiting to diverge,
    which is the condition issues #174 and #152 exist to prevent. It stays in
    this module because it calls nothing injected: it is a pure function of one
    value, identical for every consumer, which is ADR-0016 §2's "semantics
    intrinsic to a type it defines". The import runs ``core/clock.py`` →
    ``core/types.py``, never the reverse.

    Rebuilding rather than returning what ``astimezone`` handed back is what
    makes "stored as UTC" a property of the stored object instead of a claim it
    makes about itself. ``datetime.utcoffset()`` is overridable on a *subclass*,
    so a value can carry ``tzinfo is UTC``, answer zero while being validated,
    and answer ``+02:00`` afterwards — and Python compares datetimes by
    ``utcoffset()``, so the validated model would then sort and compare as
    something other than what it was checked as. A base ``datetime`` with
    ``timezone.utc`` cannot: its offset comes from an immutable singleton.

    **Only an exact ``datetime`` is canonicalised — never a subclass.** That is
    what ends the problem rather than deferring it. A subclass can override
    ``utcoffset()``, ``astimezone()``, the component properties, and
    ``__getattribute__`` itself, so every check performed on one is a check its
    subject can invalidate a moment later: verify the offset and it flips while
    the components are read; verify it again during the read and it flips
    between two of them. There is no ordering of checks that wins, because the
    value under inspection is executing code between them. Requiring
    ``type(value) is datetime`` makes every subsequent read the C
    implementation, which cannot be intercepted, so the components and the
    offset are necessarily one consistent snapshot.

    Be exact about the cost, because it is not zero: ``astimezone`` *preserves*
    the subclass, so this refuses every ``datetime`` subclass, not only a hostile
    one. That is the intended trade. A stored instant is a value, and something
    that can run code when its digits are read is not one; pydantic produces a
    base ``datetime`` for every parsed input, and no ``datetime`` subclass is
    used anywhere in this project, so nothing legitimate is affected today. A
    caller that later needs one converts it at its own boundary — one explicit
    call — rather than ``core`` holding open a hole it has no sound way to close.

    Args:
        value: The candidate, typed ``object`` deliberately — every caller
            reaches here with the result of an overridable ``astimezone``, which
            is *annotated* to return a ``datetime`` and is not obliged to.

    Returns:
        A fresh base ``datetime`` in UTC, or ``None`` if ``value`` is not
        exactly a ``datetime`` carrying ``tzinfo is UTC`` and a zero offset.
    """
    if type(value) is not datetime or value.tzinfo is not UTC:
        return None
    if value.utcoffset() != _NO_OFFSET:
        return None
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=UTC,
    )


def _utc_instant(value: datetime, info: ValidationInfo) -> datetime:
    """Reject a value with no determinate offset; return the instant in UTC.

    The two halves of ADR-0023 §§2-3, carried by one function so no field can
    opt out of either.

    **Rejection (§3).** ``core/types.py`` is the one layer that cannot know a
    value's provenance. A naive value may be a UTC timestamp read back through a
    format that dropped its offset, or a wall-clock time a user typed;
    ``replace(tzinfo=UTC)`` *restores* a fact in the first case and *fabricates*
    one in the second, and the two are indistinguishable here. Coercing resolves
    that ambiguity in the fabricating direction, silently, every time — and a
    stable-and-wrong instant is unfalsifiable afterwards, where a
    ``ValidationError`` names its cause at entry. Attribution stays legitimate in
    the adapter that decoded the value and therefore knows what it wrote.

    "Aware" means what Python means (ADR-0023 §5, issue #36): ``utcoffset()``
    returns a value. A ``tzinfo`` that is *set* but indeterminate is not aware,
    so ``tzinfo is not None`` was always the wrong spelling.

    **Conversion (§2).** Python compares two aware datetimes sharing a
    ``tzinfo`` by their naive wall-clock values, ignoring ``fold`` — so during a
    DST repeated hour ``01:15 fold=1`` (the later instant) compares as *earlier*
    than ``01:45 fold=0``. A durable, ordered record holding such values is
    internally consistent and chronologically false, for one hour a year.
    Converting makes same-``tzinfo`` comparison identical to instant comparison,
    once, for every field rather than per implementation.

    **The converted value is re-checked, which is the only step that can check
    itself.** ``astimezone`` is overridable: a ``datetime`` *subclass* can carry
    a perfectly valid ``utcoffset()``, pass every test above, and return a naive
    or non-UTC value from its own ``astimezone``. Pydantic does not re-validate
    what an ``AfterValidator`` returns, so trusting the conversion would let this
    type certify precisely the value it exists to reject — and the naive expiry
    would then raise ``TypeError`` at the first comparison in a store, far from
    here. Verifying the result costs one comparison and removes the assumption.

    The result must **be a datetime** carrying ``tzinfo is UTC``, and what is
    stored is a plain ``datetime`` rebuilt from it (:func:`canonical_utc`).
    Each part answers a way the check could otherwise be talked out of: a
    conversion returning an object that merely exposes a ``tzinfo`` attribute
    would be stored in a field annotated ``datetime``; one returning ``None``
    would leak an ``AttributeError`` from the check itself; and one returning a
    subclass that overrides ``utcoffset()`` would answer zero while being
    validated and ``+02:00`` afterwards. Identity rather than a zero offset
    because ``utcoffset()`` need not answer the same way twice; identity is also
    exact rather than merely strict, since ``astimezone(tz)`` sets the result's
    ``tzinfo`` to the ``tz`` it was given, so every genuine conversion returns
    ``UTC`` itself.

    The failure path is total because the annotation is not: a custom ``tzinfo``
    whose ``utcoffset()`` raises, a value near ``datetime.min``/``max`` at a
    non-UTC offset that overflows ``astimezone``, and a conversion that returns
    something unusable all reach here. Each becomes the same field-naming
    ``ValueError`` rather than escaping as a crash pydantic would not report as a
    validation failure — the "accepted, then unusable" shape a validator exists
    to close. That is also why the messages describe the value through
    :func:`describe_untrusted` rather than ``!r``.

    Args:
        value: The candidate instant.
        info: Pydantic's field context; supplies the field name for the message.

    Returns:
        ``value`` expressed in UTC.

    Raises:
        ValueError: If the value has no determinate UTC offset, its ``tzinfo``
            fails, or it has no usable UTC representation.
    """
    field = info.field_name or "instant"
    try:
        offset = value.utcoffset()
    except Exception as exc:  # any tzinfo failure is one rejection, not a leaked crash
        msg = f"{field} must be timezone-aware, but its tzinfo failed: {describe_untrusted(value)}"
        raise ValueError(msg) from exc
    if offset is None:
        described = describe_untrusted(value)
        msg = f"{field} must be timezone-aware with a determinate offset, got {described}"
        raise ValueError(msg)
    try:
        # Deliberately typed `object`: `astimezone` is *annotated* to return a
        # datetime and is not obliged to, so the check in `canonical_utc` has to
        # be a real one rather than one the type checker folds away as always-true.
        converted: object = value.astimezone(UTC)
        canonical = canonical_utc(converted)
    except Exception as exc:  # incl. OverflowError, which is not a ValueError
        msg = f"{field} has no UTC representation, got {describe_untrusted(value)}"
        raise ValueError(msg) from exc
    if canonical is None:
        msg = f"{field} did not convert to UTC, got {describe_untrusted(converted)}"
        raise ValueError(msg)
    return canonical


type UtcInstant = Annotated[datetime, AfterValidator(_utc_instant)]
"""An absolute point in time, stored as UTC and never guessed at (ADR-0023).

Every ``datetime`` field in this module is typed with this rather than carrying
its own validator, because a per-field validator is *opt-in*: the three fields
that had none — ``Provenance.last_updated``, ``EpisodicMemory.occurred_at``,
``SemanticMemory.valid_until`` — are exactly how naive values got in. Using the
type is the enforcement, and ``tests/core/test_instant_coverage.py`` fails the
gate on a bare ``datetime`` annotation so the omission cannot recur.

Scoped to **instants**. A *civil* time — a recurring "09:00 ``Europe/Berlin``",
whose meaning is the wall clock rather than a point on the timeline — must not
be UTC-converted, since that shifts its hour across DST. That would be a
distinct type with its own decision, which this one neither covers nor pre-empts.

**Every ``datetime`` field in this module now uses it.** The five clock-fed
``planning`` fields ADR-0023 §6 held back — ``ActionPlan.created_at``,
``StepExecution.started_at``/``finished_at``, ``ExecutionState.updated_at``,
``PlanExport.exported_at`` — followed once ADR-0026's ``checked_clock`` guarded
their producers, per ADR-0026 §5's ordering: the producer leads, the field
follows. The exemption set that enumerated them is gone, and
``tests/core/test_instant_coverage.py`` now asserts no field is exempt at all.
"""


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
    last_updated: UtcInstant = Field(
        description=(
            "Transaction time: when the system last *revised* this belief (tz-aware). "
            "This is the clock of the store changing its mind, not the clock of when the "
            "belief holds — the latter is ``MemoryBase.validity`` (ADR-0045 §3)."
        ),
    )

    @model_validator(mode="after")
    def _user_asserted_is_certain(self) -> Provenance:
        """User-asserted memories must carry full confidence."""
        if self.source is MemorySource.USER_ASSERTED and self.confidence != _FULL_CONFIDENCE:
            msg = "USER_ASSERTED provenance must have confidence 1.0"
            raise ValueError(msg)
        return self


class Validity(BaseModel):
    """The interval during which a record is the system's live belief (ADR-0045 §2).

    ``valid_from``/``valid_until`` bound a **half-open** window
    ``[valid_from, valid_until)``: a record is *live at* an instant when
    ``valid_from <= instant`` (or ``valid_from`` is unset) **and**
    ``instant < valid_until`` (or ``valid_until`` is unset). ``None`` at either end
    means unbounded, so the default — both ends open — is a record that is live
    forever until something retires it by closing ``valid_until``.

    This is the *valid-time* axis ("is this the live belief now?"), orthogonal to
    ``expires_at`` retention: a window-closed record is off the read path but still
    retained and returned by ``export``, whereas an expired one is gone from
    everything (ADR-0045 §6). The window is set *operationally* (by supersession),
    not by the producer of the belief, which is why it sits on
    :class:`MemoryBase` beside ``expires_at`` rather than on :class:`Provenance`.
    """

    valid_from: UtcInstant | None = Field(
        default=None,
        description="Inclusive start of the window; None means unbounded in the past.",
    )
    valid_until: UtcInstant | None = Field(
        default=None,
        description="Exclusive end of the window; None means unbounded in the future.",
    )

    @model_validator(mode="after")
    def _window_is_ordered(self) -> Validity:
        """Reject an inverted or empty window: when both ends are set, end > start.

        A ``valid_until`` at or before ``valid_from`` describes a window that is
        never live — never what a producer means — so making it unrepresentable
        here is better than storing a record that is silently invisible forever.
        """
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            msg = "valid_until must be after valid_from"
            raise ValueError(msg)
        return self

    def live_at(self, now: datetime) -> bool:
        """Whether a record carrying this window is the live belief at ``now``.

        The half-open predicate of ADR-0045 §2, defined once here so every
        ``MemoryStore`` read path enforces *both* ends identically instead of each
        re-deriving it — the "one rule, one place" discipline ``core`` keeps to
        stop a predicate diverging between implementations (ADR-0016 §2). It is a
        pure function of the window and the instant handed in (no clock, no
        policy, the same answer for every caller), so it is a semantic intrinsic
        to the type rather than subsystem logic.

        Args:
            now: The instant to test the window against; the caller reads its own
                (guarded) clock and passes the reading.

        Returns:
            ``True`` iff ``valid_from <= now < valid_until``, treating an unset
            end as unbounded.
        """
        if self.valid_from is not None and now < self.valid_from:
            return False
        return self.valid_until is None or now < self.valid_until


class MemoryBase(BaseModel):
    """Fields shared by every memory record, regardless of kind."""

    id: str
    content: str = Field(description="Canonical text rendering, used for retrieval.")
    provenance: Provenance
    score: float | None = Field(
        default=None,
        description="Relevance score, populated by retrieval; None when stored.",
    )
    expires_at: UtcInstant | None = Field(
        default=None,
        description=(
            "Retention deadline after which the record is forgotten (ADR-0004); "
            "timezone-aware, stored as UTC."
        ),
    )
    validity: Validity = Field(
        default_factory=Validity,
        description=(
            "The valid-time window during which this record is the live belief "
            "(ADR-0045 §2). Defaults to fully open — live forever until retired. "
            "Read-time filters hide a record not live at ``now`` from ``get``/``search`` "
            "while ``export`` still returns it; distinct from ``expires_at`` retention."
        ),
    )


class EpisodicMemory(MemoryBase):
    """Something that happened: an event, with who and how it turned out."""

    kind: Literal["episodic"] = "episodic"
    occurred_at: UtcInstant
    participants: list[str] = Field(default_factory=list)
    outcome: str | None = None
    importance: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticMemory(MemoryBase):
    """A durable fact about the user or their world."""

    kind: Literal["semantic"] = "semantic"
    fact: str
    valid_until: UtcInstant | None = Field(
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
    """The possible rulings a memory policy can make on a proposal.

    ``REINFORCE`` and ``SUPERSEDE`` each name the *relation* between the incoming
    record and the target it names, never the write that relation causes
    (ADR-0040 §1):

    - ``REINFORCE`` — the incoming record agrees with the target and strengthens
      it. The applier folds the two, and the surviving record carries **both**
      records' ``evidence``.
    - ``SUPERSEDE`` — the incoming record overturns the belief the target holds.
      The applier retires what the target held and carries **nothing** of it
      across.

    Both carry a target id and both commit. How content and confidence combine
    is the applier's semantics, not this ruling's (ADR-0028 §8, ADR-0040 §5a).
    """

    ACCEPT = "accept"
    REJECT = "reject"
    REINFORCE = "reinforce"
    SUPERSEDE = "supersede"
    ASK_USER = "ask_user"
    STORE_TEMPORARY = "store_temporary"


#: Rulings that name an existing target record and fold the proposal against it.
_TARGET_CARRYING_KINDS = frozenset({MemoryDecisionKind.REINFORCE, MemoryDecisionKind.SUPERSEDE})


class MemoryDecision(BaseModel):
    """A policy's ruling on a :class:`MemoryUpdateProposal`."""

    kind: MemoryDecisionKind
    reason: str = Field(description="Human-readable justification, for transparency.")
    target_id: str | None = Field(
        default=None,
        description="Target record id; required when ``kind`` is REINFORCE or SUPERSEDE.",
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
        if self.kind in _TARGET_CARRYING_KINDS:
            if self.target_id is None:
                msg = f"a {self.kind} decision requires target_id"
                raise ValueError(msg)
        elif self.target_id is not None:
            msg = "target_id is only valid for a REINFORCE or SUPERSEDE decision"
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
        description=(
            "Id of the record left live by the write, or None if nothing was stored. "
            "For a REINFORCE it is the reinforced record's id; for a SUPERSEDE, the id "
            "of the record now holding the live belief (ADR-0045 §4)."
        ),
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

    now: UtcInstant = Field(description="The tz-aware reference instant for this context.")
    time_of_day: TimeOfDay
    is_weekend: bool
    within_working_hours: bool = Field(
        description="Whether the local time falls in the configured working-hours window.",
    )


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
    created_at: UtcInstant = Field(description="When the feedback was given (tz-aware).")

    @field_validator("content")
    @classmethod
    def _content_is_present(cls, value: str) -> str:
        """Require non-empty content, so feedback cannot become a blank memory."""
        stripped = value.strip()
        if not stripped:
            msg = "feedback content must not be empty"
            raise ValueError(msg)
        return stripped


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
    created_at: UtcInstant = Field(description="When the goal was recorded (tz-aware).")
    deadline: UtcInstant | None = Field(
        default=None,
        description="Optional target date; timezone-aware, stored as UTC.",
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
    created_at: UtcInstant = Field(description="When the plan was produced (tz-aware).")
    rationale: str | None = Field(
        default=None, description="Why the planner chose these steps, for transparency."
    )

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

#: Statuses whose record must carry an account of why the step did not succeed
#: (ADR-0039 §2). Redrawn over ``INDETERMINATE`` as well as ``FAILED``: both are
#: finished, non-successful outcomes, and ``INDETERMINATE`` — the state ADR-0014
#: §4 makes durable *because* it must be resolved explicitly — was the one
#: finished status left with no durable diagnostic.
_FAILURE_STATUSES = frozenset({StepStatus.FAILED, StepStatus.INDETERMINATE})


class ToolFailureKind(StrEnum):
    """Why an invocation did not succeed (ADR-0029 §3).

    Defined here, above the planning types, because :class:`StepFailure` and
    :class:`StepExecution` record it: a finished step keeps the tool's own
    classification of how its call failed, not a planning-owned mirror of it
    (ADR-0039 §3, ADR-0031 §1). Shared with :class:`ToolFailure` below, which is
    the seam-facing form the executor reads it from.
    """

    INVALID_REQUEST = "invalid_request"
    """The arguments were unacceptable to the tool."""

    NOT_AUTHORISED = "not_authorised"
    """The tool's own upstream refused its credential."""

    UNAVAILABLE = "unavailable"
    """The upstream is unreachable or failing."""

    RATE_LIMITED = "rate_limited"
    """The upstream throttled us."""

    TIMED_OUT = "timed_out"
    """The seam's own deadline passed (ADR-0029 §4)."""

    CANCELLED = "cancelled"
    """Cancelled before completing (ADR-0029 §4)."""

    REFUSED = "refused"
    """Attempted, and the upstream declined it."""

    INTERNAL = "internal"
    """The tool implementation is broken."""

    @property
    def retryable(self) -> bool:
        """Whether a repeat of this same call could plausibly succeed.

        Not whether repeating is *safe* — that is
        :attr:`ToolDefinition.idempotency`'s answer, and ADR-0029 §5 requires
        both. An executor that read this alone would double a charge on the
        first ``TIMED_OUT`` send it saw.

        Declared once here rather than per consumer, copying the shape
        ``core/errors.py`` already ratified for ``ModelError.retryable``: it is
        computable from the enum's own declaration and is the same answer for
        every consumer, which is ADR-0016 §2's test for a semantic intrinsic to
        a type.

        Raises:
            KeyError: If a member was added without a value in
                ``_RETRYABLE_BY_KIND``. Loud by construction — a default would
                let a new kind acquire a retry policy nobody chose.
        """
        return _RETRYABLE_BY_KIND[self]


#: Exhaustive over :class:`ToolFailureKind`; a missing member raises rather than
#: defaulting, which is what makes ``retryable`` a declaration rather than a guess.
_RETRYABLE_BY_KIND: Mapping[ToolFailureKind, bool] = {
    ToolFailureKind.INVALID_REQUEST: False,
    ToolFailureKind.NOT_AUTHORISED: False,
    ToolFailureKind.UNAVAILABLE: True,
    ToolFailureKind.RATE_LIMITED: True,
    ToolFailureKind.TIMED_OUT: True,
    # True because the cancellation was ours: nothing about the call itself
    # failed, so the same call could be issued again.
    ToolFailureKind.CANCELLED: True,
    ToolFailureKind.REFUSED: False,
    ToolFailureKind.INTERNAL: False,
}


class StepFailure(BaseModel):
    """Why a step finished without succeeding (see ADR-0039).

    The durable account a finished-unsuccessfully step keeps: an operator-facing
    ``message`` that is always present, and the tool's own ``kind`` when a tool
    produced one. That asymmetry is the whole design — every such step has
    something to say, not every one has a tool's classification to say it with.

    ``frozen=True`` because it is a record of something that already happened:
    what an operator reads while resolving an ``INDETERMINATE`` step must not be
    editable after the fact, the same argument ADR-0014 makes for freezing the
    plan. (:class:`StepExecution` itself stays mutable — a different change.)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(
        description="Operator-facing Tier 2 explanation; visible characters required."
    )
    kind: ToolFailureKind | None = Field(
        default=None,
        description="The tool's own classification, when a tool produced one; None otherwise.",
    )

    @field_validator("message")
    @classmethod
    def _message_is_present(cls, value: str) -> str:
        """Reject a message with nothing visible in it, returning it stripped.

        The ``_has_visible_text`` test ADR-0018 §1 applies to a tool's
        description, ADR-0021 §1 to a ruling's reason and ADR-0029 §3 to a
        ``ToolFailure``'s message, for the same reason one layer up: a failure
        that renders as nothing leaves the operator resolving the step with
        nothing to read.
        """
        stripped = value.strip()
        if not _has_visible_text(stripped):
            msg = "step failure message must contain visible text"
            raise ValueError(msg)
        return stripped


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
    started_at: UtcInstant | None = None
    finished_at: UtcInstant | None = None
    failure: StepFailure | None = Field(
        default=None,
        description="Why the step finished unsuccessfully; required when FAILED or INDETERMINATE.",
    )

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
        undocumented — a SKIPPED step carrying a failure, say, or an output on a
        step that never ran.

        The ``failure`` rule is drawn over ``{FAILED, INDETERMINATE}`` rather
        than ``FAILED`` alone (ADR-0039 §2): both are finished, non-successful
        outcomes, so both must carry an account of why, and every other status
        forbids one — a step that carries a diagnostic is a step that did not
        succeed, still readable off the type.
        """
        if self.status is StepStatus.SKIPPED:
            if self.skip_reason is None:
                msg = "a SKIPPED step requires a skip_reason"
                raise ValueError(msg)
        elif self.skip_reason is not None:
            msg = "skip_reason is only valid for a SKIPPED step"
            raise ValueError(msg)

        if self.status in _FAILURE_STATUSES:
            if self.failure is None:
                msg = f"a {self.status} step requires a failure"
                raise ValueError(msg)
        elif self.failure is not None:
            msg = "failure is only valid for a FAILED or INDETERMINATE step"
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

        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            msg = "a step cannot finish before it started"
            raise ValueError(msg)

        return self


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
    updated_at: UtcInstant = Field(description="When this state was last written (tz-aware).")

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
    failure: StepFailure | None = None

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

        if self.to_status in _FAILURE_STATUSES:
            if self.failure is None:
                msg = f"a transition to {self.to_status} requires a failure"
                raise ValueError(msg)
        elif self.failure is not None:
            msg = "failure is only valid for a transition to FAILED or INDETERMINATE"
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

    schema_version: Literal[2] = Field(
        default=2,
        description=(
            "Shape of this export, pinned to exactly 2 (ADR-0039 §10): an export "
            "outlives the code that wrote it, so the label must be a fact about the "
            "document rather than a producer's unchecked claim. ``Literal[2]`` refuses "
            "every other value — a v1 document does not validate against this contract "
            "at all — so the advertised version cannot be mislabelled."
        ),
    )
    exported_at: UtcInstant
    goals: tuple[Goal, ...] = ()
    plans: tuple[ActionPlan, ...] = ()
    executions: tuple[ExecutionState, ...] = ()

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

        steps_by_plan = {plan.id: [step.id for step in plan.steps] for plan in self.plans}
        for execution in self.executions:
            expected = steps_by_plan[execution.plan_id]
            actual = [step.step_id for step in execution.steps]
            if actual != expected:
                msg = (
                    f"execution {execution.id} does not line up with plan "
                    f"{execution.plan_id}: expected steps {expected}, found {actual}"
                )
                raise ValueError(msg)

        return self


class _SeverityScale(StrEnum):
    """A ``StrEnum`` ordered by declaration, least severe first (ADR-0016 §2).

    Comparison is by severity rank rather than by the member's string value.
    This is not a convenience: ``StrEnum`` members *are* strings, so without the
    overrides below they would compare lexicographically, and
    ``RiskLevel.CRITICAL < RiskLevel.LOW`` would be ``True`` — a threshold
    policy written the obvious way would invert on the most dangerous value.

    All four operators are overridden. ``functools.total_ordering`` fills in
    only the operators a class lacks, and ``str`` supplies every one of them, so
    deriving three from ``__lt__`` would silently leave them lexicographic.
    """

    @property
    def severity(self) -> int:
        """Rank within the scale, least severe first.

        Taken from declaration order rather than a parallel table, so a member
        inserted in the middle cannot be given a rank contradicting where it
        reads.
        """
        return list(type(self)).index(self)

    def _rank_of(self, other: object) -> int:
        """Return ``other``'s rank, refusing anything but a sibling member.

        Raises:
            TypeError: If ``other`` is not a member of the same scale. This
                *raises* rather than returning ``NotImplemented`` on purpose:
                these are ``str`` subclasses, so declining would send Python to
                the reflected ``str`` comparison, which answers
                lexicographically — the exact trap the overrides exist to
                close, surviving in the mixed-type case that a policy reading a
                threshold from configuration produces.
        """
        if not isinstance(other, _SeverityScale) or type(other) is not type(self):
            msg = (
                f"cannot order {type(self).__name__} against {type(other).__name__!s}: "
                f"compare two {type(self).__name__} members"
            )
            raise TypeError(msg)
        return other.severity

    def __lt__(self, other: object) -> bool:
        """Whether this member is strictly less severe than ``other``."""
        return self.severity < self._rank_of(other)

    def __le__(self, other: object) -> bool:
        """Whether this member is no more severe than ``other``."""
        return self.severity <= self._rank_of(other)

    def __gt__(self, other: object) -> bool:
        """Whether this member is strictly more severe than ``other``."""
        return self.severity > self._rank_of(other)

    def __ge__(self, other: object) -> bool:
        """Whether this member is no less severe than ``other``."""
        return self.severity >= self._rank_of(other)


class RiskLevel(_SeverityScale):
    """How much damage invoking a tool could do (see ADR-0016 §2).

    Declared least severe first; ordered by severity, not alphabetically.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Reversibility(_SeverityScale):
    """Whether a tool's effect on the system it acts upon can be undone.

    Deliberately *not* about the reversibility of disclosure, which
    :attr:`ToolDefinition.discloses` tracks separately: creating an event in a
    hosted calendar is ``REVERSIBLE`` — the tool deletes it — while the
    provider having seen the contents is permanent. Both are true, and neither
    implies the other, so a policy must read both fields (ADR-0016 §2).
    """

    REVERSIBLE = "reversible"
    RECOVERABLE = "recoverable"
    IRREVERSIBLE = "irreversible"


class CostBasis(StrEnum):
    """How a tool's per-invocation price is known (see ADR-0016 §4)."""

    FREE = "free"
    PER_CALL = "per_call"
    UNKNOWN = "unknown"


#: Unicode major categories that carry standalone visible content: letters,
#: numbers, punctuation and symbols. Deliberately a **whitelist**. The first
#: attempt enumerated the invisible categories instead and missed the combining
#: marks (``Mn``/``Me``) — a variation selector or a combining grapheme joiner
#: with no base character renders as nothing, so a description made of them
#: passed. Listing what counts as visible cannot be defeated by a category
#: nobody thought of; listing what does not, can.
_VISIBLE_CATEGORIES = ("L", "N", "P", "S")

#: Characters that sit in a visible category yet display as nothing, so the
#: whitelist above would otherwise accept them (ADR-0018 §1). A short exception
#: list layered on a whitelist is not the blocklist that failed before: the
#: whitelist still carries the burden, and this narrows a known, enumerable gap
#: on top of it, where being incomplete makes it weaker rather than wrong.
#:
#: Deliberately not deferred to a canonical identifier syntax (issue #62): that
#: governs identifiers, and a ``description`` is free text no syntax rule will
#: ever constrain, so parking these there would park them somewhere that never
#: arrives.
_BLANK_RENDERING = frozenset(
    {
        "\u2800",  # BRAILLE PATTERN BLANK (So)
        "\u115f",  # HANGUL CHOSEONG FILLER (Lo)
        "\u1160",  # HANGUL JUNGSEONG FILLER (Lo)
        "\u3164",  # HANGUL FILLER (Lo)
        "\uffa0",  # HALFWIDTH HANGUL FILLER (Lo)
    }
)


def _is_encodable(text: str) -> bool:
    r"""Whether ``text`` has a UTF-8 encoding.

    A lone surrogate (``"\ud800"``) is a ``str`` Python is happy to hold but
    that no UTF-8 encoder will accept, because it is half of a character rather
    than a character.
    """
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _has_visible_text(value: str) -> bool:
    """Whether ``value`` contains at least one character that renders.

    Not a complete test, and cannot be: without a font and a shaping engine
    there is no general "renders as something" oracle, so a determined author
    can likely find a codepoint this misses. It covers the known cases.
    """
    return any(
        char not in _BLANK_RENDERING and unicodedata.category(char).startswith(_VISIBLE_CATEGORIES)
        for char in value
    )


def _visible_identifier(value: str) -> str:
    """Reject an identifier with nothing visible in it, returning it stripped.

    Stricter than :data:`Identifier`, which only refuses a blank. A tool's id
    and capability are shown to the user in an approval prompt and written into
    audit records beside the description, so an id of nothing but zero-width
    spaces would render as blank in exactly the places
    :meth:`ToolDefinition._description_is_present` exists to keep meaningful —
    and would be indistinguishable from any other invisible id.

    Applied to tool identifiers rather than to :data:`Identifier` itself
    because that type is shared with ``planning`` (ADR-0014), where tightening
    it is a cross-lane change; see issue #62.
    """
    stripped = value.strip()
    if not _has_visible_text(stripped):
        msg = "identifier must contain visible text"
        raise ValueError(msg)
    return stripped


type VisibleIdentifier = Annotated[str, AfterValidator(_visible_identifier)]
"""An identifier that renders as something — for ids a user is shown."""

_CURRENCY_CODE_LENGTH = 3


class ToolCost(BaseModel):
    """What one invocation of a tool costs (see ADR-0016 §4).

    Structured rather than an optional number because the distinction a spend
    policy needs is *free* versus *unknown* — the first is a fact it can add to
    a running total, the second an absence of information it must fail closed
    on. An optional field defaulting to ``None`` collapses those two.

    Frozen in its own right, and that is load-bearing:
    :class:`ToolDefinition`'s ``frozen=True`` blocks reassigning the ``cost``
    *field* and does nothing about mutating the object it holds, which would
    let a registered definition and a permission decision keep pointing at one
    instance while the number inside it changed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    basis: CostBasis
    amount: Decimal | None = Field(
        default=None, description="Price per invocation; required iff basis is PER_CALL."
    )
    currency: str | None = Field(
        default=None, description="ISO-4217 alphabetic code; required iff basis is PER_CALL."
    )

    @field_validator("currency")
    @classmethod
    def _currency_is_iso_4217_shaped(cls, value: str | None) -> str | None:
        """Require exactly three uppercase ASCII letters, without normalising.

        Shape only. Validating against the live ISO-4217 register would make a
        definition's loading depend on a table that changes when currencies are
        withdrawn, so a tool that loaded last year would stop; and silently
        upcasing ``"usd"`` would treat a lowercase code and a typo'd one
        differently for no reason a caller can see.
        """
        if value is None:
            return None
        if len(value) != _CURRENCY_CODE_LENGTH or not (value.isascii() and value.isupper()):
            msg = f"currency must be three uppercase ASCII letters (ISO-4217), got {value!r}"
            raise ValueError(msg)
        if not value.isalpha():
            msg = f"currency must be three uppercase ASCII letters (ISO-4217), got {value!r}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _amount_matches_basis(self) -> ToolCost:
        """Require a priced amount for PER_CALL and forbid one otherwise.

        The finiteness check comes before the sign check deliberately:
        ``Decimal`` admits ``Infinity`` and ``NaN``, neither of which has a JSON
        representation or survives arithmetic in a running total, and comparing
        ``NaN`` with ``<`` raises rather than answering.
        """
        if self.basis is CostBasis.PER_CALL:
            if self.amount is None or self.currency is None:
                msg = "a PER_CALL cost requires both amount and currency"
                raise ValueError(msg)
            if not self.amount.is_finite():
                msg = f"cost amount must be finite, got {self.amount!r}"
                raise ValueError(msg)
            if self.amount < 0:
                msg = f"cost amount must not be negative, got {self.amount!r}"
                raise ValueError(msg)
        elif self.amount is not None or self.currency is not None:
            msg = f"a {self.basis} cost carries no amount or currency"
            raise ValueError(msg)
        return self


class Idempotency(StrEnum):
    """The retry guarantee a tool offers (see ADR-0016 §4).

    A *guarantee*, not the presence of a parameter: accepting an idempotency key
    is syntax, and a tool may accept one and ignore it. ``KEYED`` additionally
    fixes the scope — the tool, identified by :attr:`ToolDefinition.id` — and
    the lifetime, via :attr:`ToolDefinition.idempotency_window`.
    """

    NONE = "none"
    NATURAL = "natural"
    KEYED = "keyed"


#: Data tiers whose ordering is by sensitivity (declaration order), not by value.
_TIER_ORDER: Mapping[DataTier, int] = {tier: index for index, tier in enumerate(DataTier)}


def _ordered_tiers(value: tuple[DataTier, ...]) -> tuple[DataTier, ...]:
    """Sort and de-duplicate data tiers, most sensitive first.

    ``sorted`` on the raw members would order by string value —
    ``OPERATIONAL, PERSONAL, SECRET`` — which reads as though sensitivity ran
    the other way. Declaration order is used instead, matching how
    :class:`_SeverityScale` takes its rank, so ``core`` has one convention.
    These tuples are serialised into permission decisions and audit records, so
    a stable order is what makes two registries agree on the same definition.
    """
    return tuple(sorted(set(value), key=lambda tier: _TIER_ORDER[tier]))


type TierReach = Annotated[tuple[DataTier, ...], AfterValidator(_ordered_tiers)]
"""Data tiers a tool may touch: sorted most-sensitive-first, de-duplicated."""


class ToolDefinition(BaseModel):
    """A declaration of what a tool is and what invoking it risks (ADR-0016 §1).

    Every field a permission decision depends on is **required**. A default is a
    claim, and the natural-looking default for the reach tuples — empty — is the
    claim "this tool touches no data", which is exactly the false statement a
    forgetful integration author would ship. A tool that does not declare its
    reach does not load.

    Nothing here decides whether the permission gate is consulted: every
    invocation is gated, the definition states facts, and ``permissions`` draws
    conclusions (ADR-0016 §3).

    Frozen for the same reason :class:`ActionPlan` is: a permission decision is
    recorded against the definition in force, and one that can be edited
    afterwards makes the audit trail a description of the present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: VisibleIdentifier
    capability: VisibleIdentifier = Field(
        description="The single capability this tool satisfies, e.g. 'send_email'."
    )
    description: str = Field(description="What the tool does; shown to the model and the user.")
    risk_level: RiskLevel
    reversibility: Reversibility
    side_effecting: bool = Field(description="Whether invoking it changes anything outside itself.")
    reads: TierReach = Field(description="Tiers it may read; a ceiling, not a per-call measure.")
    writes: TierReach = Field(description="Tiers it may modify; a ceiling.")
    discloses: TierReach = Field(description="Tiers it may transmit off-device; a ceiling.")
    cost: ToolCost
    idempotency: Idempotency
    idempotency_window: timedelta | None = Field(
        default=None,
        description="How long a repeated key is deduplicated; required iff idempotency is KEYED.",
    )
    latency: timedelta | None = Field(
        default=None, description="Expected duration of a typical call; advisory, not a timeout."
    )
    parameters_schema: FrozenJsonMapping = Field(
        default=_EMPTY_PARAMS,
        description="JSON Schema for the call's arguments; carried, not yet enforced.",
    )

    @field_validator("description")
    @classmethod
    def _description_is_present(cls, value: str) -> str:
        """Reject a description with nothing visible in it, returning it stripped.

        A description that renders as nothing passes every other check while
        leaving the approval prompt with nothing to say about the action — the
        one moment this design exists to serve, and the one where a user is most
        likely to approve out of confusion.

        ``strip()`` alone is not enough. It removes whitespace, but a zero-width
        space, a byte-order mark and a variation selector are *format* and
        *combining-mark* characters, not whitespace, so a description made of
        them survives stripping while rendering as nothing. The requirement is
        therefore at least one character carrying visible content of its own —
        a letter, number, punctuation mark or symbol.
        """
        stripped = value.strip()
        if not _has_visible_text(stripped):
            msg = "tool description must contain visible text"
            raise ValueError(msg)
        return stripped

    @model_validator(mode="after")
    def _effects_are_consistent(self) -> ToolDefinition:
        """Make the self-contradictory declarations unrepresentable.

        A tool that modifies stored data, or transmits any off-device, is
        side-effecting whatever it claims — transmitting to a third party has
        consequences outside this system even when nothing local changes, and it
        is the class ADR-0004 §2 governs. Conversely a tool with no side effect
        has nothing to reverse.

        Disclosure says nothing about ``reversibility``: that describes the
        effect on the system acted upon, and the two are independent (ADR-0016
        §2).
        """
        if self.writes and not self.side_effecting:
            msg = "a tool that writes is side-effecting"
            raise ValueError(msg)
        if self.discloses and not self.side_effecting:
            msg = "a tool that discloses data off-device is side-effecting"
            raise ValueError(msg)
        if not self.side_effecting and self.reversibility is not Reversibility.REVERSIBLE:
            msg = "a tool with no side effect has nothing to reverse, so it is REVERSIBLE"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _idempotency_window_matches_guarantee(self) -> ToolDefinition:
        """Tie the window to ``KEYED``, and require it to be strictly positive.

        Zero or negative is rejected rather than merely discouraged: no retry
        can fall inside such a window, so the definition would advertise a
        guarantee unsatisfiable by construction — worse than declaring ``NONE``,
        which at least tells the executor the truth.
        """
        if self.idempotency is Idempotency.KEYED:
            if self.idempotency_window is None:
                msg = "a KEYED tool requires an idempotency_window"
                raise ValueError(msg)
            if self.idempotency_window <= timedelta(0):
                msg = "idempotency_window must be strictly positive"
                raise ValueError(msg)
        elif self.idempotency_window is not None:
            msg = f"idempotency_window is only valid for a KEYED tool, not {self.idempotency}"
            raise ValueError(msg)
        return self

    @field_validator("latency")
    @classmethod
    def _latency_is_not_negative(cls, value: timedelta | None) -> timedelta | None:
        """Reject a negative latency estimate.

        Accuracy is advisory — nothing enforces it — but a negative duration is
        not a wrong guess, it is a nonsense one, and it would invert any
        selection that sorts on it.
        """
        if value is not None and value < timedelta(0):
            msg = f"latency must not be negative, got {value!r}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _is_storable(self) -> ToolDefinition:
        r"""Refuse a declaration that has no JSON encoding (issue #156).

        A lone surrogate — a ``str`` Python holds happily and no UTF-8 encoder
        accepts — satisfies every other rule here. ``id`` and ``capability`` are
        :data:`VisibleIdentifier`, which asks only that something renders;
        ``description`` asks the same; ``parameters_schema`` is
        :data:`FrozenJsonMapping`, which refuses a non-finite float and says
        nothing about text. So ``ToolDefinition(description="Send \ud800 mail.")``
        is a *valid model that cannot be serialised*, and the failure arrives as
        a ``PydanticSerializationError`` from whatever tries to store it.

        **Why the constraint sits on the type rather than on each holder.**
        ADR-0016 §6 keeps the registry in memory and rebuilds it each run, so
        nothing forced the question while the registry was the only holder.
        ADR-0021 §4 made the audit trail the first durable one and PR #119
        closed the gap at the permissions boundary; ADR-0029 then embedded a
        definition in :class:`ToolCall` and had the seam revalidate it, which is
        the same work a second time. A holder-by-holder rule is a list someone
        has to keep complete as holders are added, and the property being
        protected — "this value can be written down" — is intrinsic to the
        declaration rather than to who is holding it (ADR-0016 §2's test).
        Checked here, every present and future holder gets it for nothing, and
        an integration author learns at registration rather than at the trail.

        **The predicate is the serialisation itself, not an enumeration of the
        strings a definition reaches.** That is what makes it depth-independent:
        ``parameters_schema`` is a JSON Schema of arbitrary shape and a
        surrogate can sit in a key or a value at any nesting, so a rule written
        against the top level, or against the text fields, would be complete
        only until the next schema. Running the real encoding cannot be
        incomplete, and it keeps "accepted" and "storable" the same predicate as
        the model grows fields — the reason :func:`_canonical_json` is shared
        with the digest rather than restated.

        A ``model_validator`` specifically, and that is load-bearing rather than
        stylistic: pydantic re-runs an ``after`` model validator when an
        existing instance is assigned to a model-typed field, and does *not*
        re-run field validators. So this also catches a definition tampered past
        ``frozen=True`` with ``object.__setattr__`` on its way into a
        :class:`PermissionDecision` — the bypass ADR-0018 §3 and ADR-0021 §4 put
        inside this repository's threat model — which is what lets the
        permissions boundary drop its own copy of this check.

        Every way the render can fail is caught, not only the surrogate that
        prompted the issue, and that is the same clause :func:`_digestible`
        writes for the same reason: a surrogate is one of *two* values reachable
        here that satisfy their Python type and have no JSON rendering, and the
        other is a very large integer, which ``json.dumps`` renders through
        ``str()`` and CPython refuses past its integer-string conversion limit.
        A definition tampered past ``frozen=True`` supplies a third — a value
        pydantic cannot serialise at all, which surfaces as a
        ``PydanticSerializationError``. All three are ``ValueError``, so one
        clause covers them and the definition is refused with the same
        diagnostic rather than with a runtime-specific one.

        Raises:
            ValueError: If the definition has no JSON encoding.
        """
        try:
            rendered = json.dumps(self.model_dump(mode="json"), ensure_ascii=False)
        except ValueError as exc:
            # An unencodable *key* fails inside the render rather than after it,
            # because pydantic encodes a mapping key on the way to JSON. Caught
            # here so every half of the same defect raises the same error rather
            # than one arriving as a bare codec or limit failure.
            raise ValueError(self._unstorable(exc)) from exc
        if not _is_encodable(rendered):
            raise ValueError(self._unstorable(None))
        return self

    @property
    def interrupted_outcome(self) -> ToolOutcome:
        """What a call of this tool, cut short by a deadline or a cancellation, means.

        ``FAILED`` when the tool is not :attr:`side_effecting`, **or** its
        :attr:`idempotency` is ``NATURAL``; otherwise ``INDETERMINATE``
        (ADR-0029 §4).

        A read that timed out changed nothing, and a ``NATURAL`` tool is
        idempotent by nature (ADR-0016 §4), so whether it acted does not change
        what a repeat does. Everything else is exactly ADR-0014 §4's case — "a
        crash between a tool's side effect and the commit … cannot be
        distinguished from a crash *before* the effect" — reached through a
        deadline rather than through a crash, and it gets the same answer,
        because guessing in either direction is what that ADR refused.

        Declared once here rather than per consumer, on the same three-part test
        :attr:`ToolFailureKind.retryable` passes (ADR-0016 §2, ADR-0031 §1): it
        reads two of this type's own fields and nothing else, consults no policy,
        settings, context or clock, and gives one answer for every consumer. It
        has three readers — the seam on a deadline expiry, the seam again when a
        tool reports its effect may have committed, and the executor on a
        cancellation — and two of them are in subsystems that cannot import each
        other, so a second copy could only be one free to disagree.

        **Read it from the registry's declaration for the committed
        ``bound_tool``, never from ``call.request.tool``.** The seam's binding
        checks all ran *before* the callable started, so a declaration mutated
        mid-flight is re-examined by nothing: a side-effecting, non-``NATURAL``
        call whose definition were flipped to read-only would then classify as
        ``FAILED`` — a possible side effect recorded as
        certainly-nothing-happened, the one direction ADR-0014 §4 refuses to
        guess in. Written as a property, the wrong version is visible in the
        expression, on the object, at the point of use.

        A plain ``property`` and specifically **not** a ``computed_field``: a
        computed field enters ``model_dump()``, and ADR-0018 §4's registration
        rebuild is ``model_validate(tool.model_dump())`` against
        ``extra="forbid"``, so every registration would fail (ADR-0031 §1).
        """
        if not self.side_effecting or self.idempotency is Idempotency.NATURAL:
            return ToolOutcome.FAILED
        return ToolOutcome.INDETERMINATE

    def _unstorable(self, cause: ValueError | None) -> str:
        """Say which declaration could not be rendered, without raising.

        ``id`` is a ``str`` on any definition that was *constructed*, and the
        values that reach the caller above got there past ``frozen=True`` — so
        it can be an arbitrary object with a hostile ``__repr__``, and so can
        whatever pydantic put inside ``cause``. Interpolating either directly
        would let the diagnostic destroy the diagnosis, raising that object's
        exception out of an ``except`` block instead of the ``ValueError`` this
        method promises. :func:`describe_untrusted` is the helper this module already
        keeps for exactly that, and this is the second place it is needed.
        """
        detail = "" if cause is None else f" ({describe_untrusted(cause)})"
        described = describe_untrusted(self.id)
        return f"tool has no JSON encoding, so it could not be stored: {described}{detail}"


class PermissionOutcome(_SeverityScale):
    """What a policy ruled about an action (ADR-0021 §2).

    Declared least restrictive first: ``ALLOW`` proceeds, ``CONFIRM`` requires a
    user decision before proceeding, ``DENY`` refuses.

    A :class:`_SeverityScale` rather than a plain ``StrEnum``, and the reason is
    the trap ADR-0016 §2 documented. ``StrEnum`` members *are* strings, so an
    un-overridden scale compares lexicographically — and today
    ``"allow" < "confirm" < "deny"`` happens to be correct alphabetically, which
    is worse than being wrong. The ordering appears to work, nothing fails, and
    the first member inserted out of alphabetical order silently inverts every
    threshold comparison written against it.
    """

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


def _durable_identifier(value: str) -> str:
    """Reject an identifier with no UTF-8 encoding.

    ADR-0021 §4 requires a recorded decision to survive a
    ``model_dump(mode="json")`` round trip, because a decision that could not be
    reloaded would make the embedded definition worthless across exactly the
    restart issue #54 is about. An identifier holding a lone surrogate satisfies
    :data:`Identifier` — which only strips and refuses a blank — and then fails
    at the store or export boundary, which is the durability guarantee broken
    one field family short of complete.

    Layered on the permission types rather than folded into :data:`Identifier`
    itself, which ``planning`` shares (ADR-0014): tightening it there is a
    cross-lane change, and issue #62 already holds the identifier-syntax
    question. The same boundary :func:`_visible_identifier` drew for tool ids.

    Raises:
        ValueError: If the identifier cannot be encoded as UTF-8.
    """
    if not _is_encodable(value):
        msg = f"identifier has no UTF-8 encoding, so the record could not be stored: {value!r}"
        raise ValueError(msg)
    return value


type DurableIdentifier = Annotated[Identifier, AfterValidator(_durable_identifier)]
"""An :data:`Identifier` that survives serialisation — for fields a record keeps."""


#: A SHA-256 digest rendered as lowercase hex is exactly this long.
_SHA256_HEX_LENGTH = 64

_HEX_DIGITS = frozenset("0123456789abcdef")


def _sha256_hex(value: str) -> str:
    """Require a lowercase SHA-256 hex digest.

    :attr:`PermissionDecision.parameters_digest` is filled by
    :meth:`PermissionDecision.from_request` from
    :attr:`ActionRequest.parameters_digest`, which always produces this shape —
    but the field is a plain ``str``, so a hand-constructed decision could carry
    anything, including text with no UTF-8 encoding. That is the last field of a
    decision that could break ADR-0021 §4's requirement that a record reload,
    and unlike the others it has an exact form to check rather than merely a
    property.

    Lowercase specifically: ``hexdigest()`` emits lowercase, so accepting
    uppercase would admit a second spelling of the same digest that compares
    unequal — a false mismatch at execution, which reads as an attack rather
    than as a bug.

    Raises:
        ValueError: If the value is not 64 lowercase hex digits.
    """
    if len(value) != _SHA256_HEX_LENGTH or not _HEX_DIGITS.issuperset(value):
        msg = f"parameters_digest must be {_SHA256_HEX_LENGTH} lowercase hex digits, got {value!r}"
        raise ValueError(msg)
    return value


type Sha256Hex = Annotated[str, AfterValidator(_sha256_hex)]
"""A lowercase SHA-256 digest in hex — the form :func:`hashlib.sha256` emits."""


def _detached_tool(value: ToolDefinition) -> ToolDefinition:
    """Take the request's own copy of the declaration it is about.

    Pydantic passes an already-valid model instance through without copying, so
    an :class:`ActionRequest` would otherwise share the caller's
    ``ToolDefinition`` — and ``object.__setattr__`` on that original would
    change what the request *is about* after a policy had already ruled on it,
    with :meth:`PermissionDecision.from_request` then transcribing the mutated
    version faithfully.

    Rebuilt through validation rather than merely deep-copied, so the request's
    copy is *valid* as well as its own. A definition corrupted past its frozen
    model's guard — ``risk_level`` written back as a bare string is the sharp
    case — would otherwise reach a policy, which compares that field on a
    severity scale and would raise ``TypeError`` mid-decision. A policy should
    be able to trust the request it is handed; this is what makes that true.

    This is the first of the three detachments that make ADR-0021 §1's binding
    hold end to end, and each closes a different window: the request takes its
    own subject here, ``from_request`` takes the decision's, and
    ``AuditTrail.record`` revalidates what it stores. Between them no reference
    a caller still holds reaches recorded state.

    Rebuilt as a :class:`ToolDefinition` specifically, not as ``type(value)``. A
    subclass carrying extra fields would survive on the request and then be
    flattened to the declared base type when the decision is serialised, so the
    trail would reload a definition that no longer equals the one approved and
    :meth:`PermissionDecision.authorises` would answer ``False`` for the very
    request it was made about. ``extra="forbid"`` turns that into a refusal at
    construction instead — the divergence surfaces where it can be fixed rather
    than after a restart.

    Rebuilding is also what makes the request's copy *storable*, and no separate
    durability validator is layered here for it: ADR-0021 §4 requires a recorded
    decision to survive a ``model_dump(mode="json")`` round trip, and
    :meth:`ToolDefinition._is_storable` refuses a definition with no JSON
    encoding on every path into that type — including an already-built instance
    handed straight to :class:`PermissionDecision` (issue #156).
    """
    return ToolDefinition.model_validate(value.model_dump())


def _canonical_json(parameters: Mapping[str, FrozenJson]) -> bytes:
    """Render ``parameters`` in the exact form ADR-0021 §1 pins for the digest.

    One definition, used by both the validator below and
    :attr:`ActionRequest.parameters_digest`. That sharing is the point: it makes
    "the payload validates" and "the payload can be digested" the *same*
    predicate by construction, rather than two enumerations that can disagree —
    and disagreeing means a request a policy can rule on but no decision can be
    recorded about.
    """
    text = json.dumps(
        _thaw_json(parameters), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return text.encode("utf-8")


def _digestible(parameters: Mapping[str, FrozenJson]) -> Mapping[str, FrozenJson]:
    """Reject a payload the canonical encoding cannot render.

    The same rule, for the same reason, as :func:`_freeze_json`'s refusal of
    non-finite floats (ADR-0014 §2): a value that satisfies its Python type but
    has no transportable representation would fail on the way through a digest,
    a store, or an export. Two such values are reachable here and neither is
    exotic —

    - a **lone surrogate**, which satisfies ``str`` and has no UTF-8 encoding;
    - a **very large integer**, which ``json.dumps`` renders through ``str()``
      and CPython refuses past its integer-string conversion limit.

    Checked by *attempting the encoding* rather than by enumerating the value
    types that can fail. An enumeration is a list someone has to keep complete,
    and the two cases above are what a first attempt at one missed; running the
    real operation cannot be incomplete. It also means the rule automatically
    tracks the encoding if the ADR ever pins a different one.

    Applied to :attr:`ActionRequest.parameters` rather than inside
    ``_freeze_json``, which would tighten ADR-0014's plan parameters and step
    outputs at the same time. Those have the identical latent hole, filed as its
    own issue rather than folded into this change, because that type is another
    lane's contract.

    Raises:
        ValueError: If the payload has no canonical encoding. ``UnicodeError``
            is a ``ValueError``, so one clause covers both causes.
    """
    try:
        _canonical_json(parameters)
    except ValueError as exc:
        msg = f"parameters have no canonical JSON encoding, so they cannot be digested: {exc}"
        raise ValueError(msg) from exc
    return parameters


class ActionRequest(BaseModel):
    """A self-contained proposal to invoke a tool, for a policy to rule on (ADR-0021 §3).

    It carries the **definition** rather than an id, so a policy never consults a
    registry. That is what makes :class:`PermissionDecision`'s guarantee
    available at all — a policy that resolved an id would reintroduce the
    rebinding hazard (issue #54) inside the very subsystem meant to close it —
    and it keeps ``permissions`` free of any dependency on ``tools`` beyond this
    shared ``core`` type.

    ``parameters`` may **not** carry a Tier 0 credential value. That is a
    pre-existing rule rather than one invented here: ADR-0004 §3 puts secrets in
    the OS keyring and has ``tools/`` read them through ``SecretStore``, so a
    tool fetches its own credential and is never handed one. It is restated
    because a digest is *not* an adequate remedy if a secret ever gets in —
    SHA-256 of a low-entropy secret is brute-forceable offline, so a hash of a
    credential is a weakened copy of it, not an absence of one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: Annotated[ToolDefinition, AfterValidator(_detached_tool)] = Field(
        description="The declaration being ruled on, by value."
    )
    parameters: Annotated[FrozenJsonMapping, AfterValidator(_digestible)] = Field(
        default=_EMPTY_PARAMS,
        description="The arguments the call proposes; bound by digest, never stored.",
    )
    step_id: DurableIdentifier | None = Field(
        default=None, description="The plan step this action belongs to, if any."
    )

    @property
    def parameters_digest(self) -> str:
        """A stable SHA-256 hex digest of :attr:`parameters`.

        Computed **here** rather than supplied by a caller, and that placement
        matters as much as the encoding: a ``str`` field each caller filled in
        would be a canonicalisation per caller, and two that disagreed would
        produce a false mismatch at execution — which reads as an attack rather
        than as a bug.

        The payload is bound but never stored. Arguments carry Tier 1 data
        routinely (a recipient, a message body, a calendar entry), and a durable
        record holding them verbatim would make the audit trail a second copy of
        the user's most sensitive material, growing forever, for no purpose the
        trail actually has. "Were *these* the arguments approved" is what the
        trail must answer, and a digest answers it exactly.

        **Total on every payload the model accepts**, which is a property of how
        the two are wired rather than a claim. :func:`_digestible` validates by
        running :func:`_canonical_json` — the same function this hashes — so
        "accepted" and "digestible" cannot come apart. The ADR justified
        well-definedness by pointing at ``FrozenJson`` rejecting non-finite
        floats (ADR-0014 §2); that was necessary and not sufficient, and a
        digest raising on a payload the model had already accepted would make
        every decision about that request unconstructable, at the gate.
        """
        return sha256(_canonical_json(self.parameters)).hexdigest()


class PermissionRuling(BaseModel):
    """What a policy said about an :class:`ActionRequest` (ADR-0021 §3).

    A ruling is ``outcome`` and ``reason`` — the only two things a policy is
    entitled to author — and **it has no field naming a tool, a payload, or a
    step**. That absence is the security property, not an economy. An earlier
    draft had a policy return a whole :class:`PermissionDecision`, which has a
    ``tool`` field, so a conforming implementation could have returned ``ALLOW``
    for a *different* tool than the one it was handed, and
    :meth:`PermissionDecision.authorises` would then have approved it. Splitting
    the types removes the capability rather than forbidding it, and does so for
    every implementation, including one written by someone who never read the
    ADR.

    The policy also does not mint an ``id`` or read a clock; the caller that
    records supplies both. That leaves ``decide`` a genuine function of its
    argument, which is in turn what makes the monotonicity obligations in
    ADR-0021 §5 checkable at all.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: PermissionOutcome
    reason: str = Field(description="Why, in text shown to the user at the moment they decide.")
    authorised_by: DurableIdentifier | None = Field(
        default=None, description="The recorded user decision this ALLOW rests on, if any."
    )

    @field_validator("reason")
    @classmethod
    def _reason_is_present(cls, value: str) -> str:
        """Reject a reason with nothing visible in it, returning it stripped.

        The same ``_has_visible_text`` test ADR-0018 §1 applies to a tool's
        description, and for the same reason: this is shown to the user at the
        moment they are deciding, and a reason that renders as nothing leaves
        the prompt with nothing to say.
        """
        stripped = value.strip()
        if not _has_visible_text(stripped):
            msg = "ruling reason must contain visible text"
            raise ValueError(msg)
        if not _is_encodable(stripped):
            msg = f"ruling reason has no UTF-8 encoding, so it could not be stored: {stripped!r}"
            raise ValueError(msg)
        return stripped

    @model_validator(mode="after")
    def _only_an_allow_cites_an_authorisation(self) -> PermissionRuling:
        """Permit ``authorised_by`` only on an ``ALLOW``.

        A refusal rests on no authorisation, and a ``DENY`` — or a ``CONFIRM``,
        which is a question rather than an answer — citing one is incoherent.
        """
        if self.authorised_by is not None and self.outcome is not PermissionOutcome.ALLOW:
            msg = f"a {self.outcome} ruling cites no authorisation, got {self.authorised_by!r}"
            raise ValueError(msg)
        return self


class PermissionDecision(BaseModel):
    """A ruling bound to the request it was made about (ADR-0021 §1).

    ``tool`` is the **whole** :class:`ToolDefinition`, embedded by value, and
    that is the clause everything else here rests on. A decision does not say "I
    approved ``send_message``"; it says "I approved *this declaration*, which
    happens to call itself ``send_message``, is ``REVERSIBLE``, discloses
    ``PERSONAL``, and costs nothing". There is no name left to rebind, so a
    process that restarts and registers a different definition under the same id
    has not altered any decision, and the mismatch is a value comparison away
    (issue #54).

    Not a digest of the definition, deliberately. A digest is what you reach for
    when the thing is too large or too sensitive to keep, and a
    ``ToolDefinition`` is neither — it is a few hundred bytes of Tier 2
    configuration declared by code (ADR-0016 §6). Storing it buys three things a
    digest does not: the trail stays **readable without the registry**, which
    ADR-0016 §6 rebuilds in memory each run; there is **no canonicalisation to
    get wrong**, so two implementations cannot produce false mismatches on
    identical definitions; and it **composes with detachment** (ADR-0018 §3)
    rather than adding a parallel mechanism.

    Every field is serialisable, and that is load-bearing rather than
    incidental: a decision that could not survive a ``model_dump(mode="json")``
    round-trip would make the pin worthless across exactly the restart issue #54
    is about. The identifiers carry that as :data:`DurableIdentifier` and the
    digest as :data:`Sha256Hex`; ``tool`` needs no annotation of its own because
    :meth:`ToolDefinition._is_storable` makes it a property of the declaration
    rather than of this record (issue #156).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier
    ruling: PermissionRuling = Field(description="What the policy said.")
    tool: ToolDefinition = Field(description="The declaration ruled on, verbatim.")
    parameters_digest: Sha256Hex = Field(description="Binds the payload without storing it.")
    decided_at: UtcInstant = Field(
        description=(
            "When the ruling was made; timezone-aware, stored as UTC. The trail "
            "is durable *and ordered* (ADR-0021 §4), which is why a naive value "
            "is refused rather than assumed — see :data:`UtcInstant`."
        )
    )
    step_id: DurableIdentifier | None = None
    resolves: DurableIdentifier | None = Field(
        default=None, description="The CONFIRM decision this one answers, if any."
    )

    @classmethod
    def from_request(
        cls,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        id: Identifier,  # noqa: A002 — names the field it fills; the ADR fixes the signature
        decided_at: datetime,
        resolves: Identifier | None = None,
    ) -> PermissionDecision:
        """Bind a ruling to the request it was made about.

        **The only construction path a caller should use**, and it exists so the
        binding is *transcribed* rather than asserted. Every field describing
        what was ruled on — ``tool``, ``parameters_digest``, ``step_id`` — is
        copied from the request by ``core``, so a decision naming a different
        tool than the one the policy saw cannot be produced by following the
        contract.

        A factory rather than a validator because the request is not a field of
        the decision: embedding it whole would store the parameters this design
        is careful not to store. What remains open is a caller hand-constructing
        a decision field by field — that is a caller falsifying its own audit
        trail rather than a policy subverting a gate, and no producer can
        prevent it (the boundary ADR-0018 §3 drew for detachment).

        **The tool and the ruling are deep-copied, which is what makes "by
        value" true rather than nominal.** Pydantic passes an already-valid
        model instance through without copying it, so the decision would
        otherwise hold the *same* ``ToolDefinition`` object the request does —
        and ``object.__setattr__(request.tool, "risk_level", CRITICAL)`` would
        then rewrite what the policy is recorded as having approved, while
        ``authorises`` went on answering ``True`` because both sides moved
        together. Copying here is the same discipline ADR-0018 §3 applied to
        registry queries, at the moment the value stops being the caller's and
        becomes the record's.

        Args:
            request: The action ruled on; its subject is copied across.
            ruling: What the policy said about it.
            id: Identifier for this decision, minted by the caller that records.
            decided_at: When the ruling was made; must be timezone-aware.
            resolves: The recorded ``CONFIRM`` this decision answers, if any.

        Returns:
            The decision, ready to record.
        """
        return cls(
            id=id,
            ruling=ruling.model_copy(deep=True),
            tool=request.tool.model_copy(deep=True),
            parameters_digest=request.parameters_digest,
            decided_at=decided_at,
            step_id=request.step_id,
            resolves=resolves,
        )

    def authorises(self, request: ActionRequest) -> bool:
        """Whether this decision authorises performing ``request``.

        Takes a **request** rather than a bare definition, and that is what makes
        it discharge ADR-0017 §3's "what is transmitted is bound to what was
        authorised, immutably, and consumed unchanged". A signature taking only a
        definition would have checked the tool and silently ignored the
        arguments — authorising an email to one recipient and executing it to
        another, with every record still reading as consistent. That is the same
        failure shape as issue #54, one level down.

        This lives in ``core`` because it **compares; it does not decide**.
        Whether an action *should* be allowed is
        :class:`~ai_assistant.core.protocols.ActionPolicy`'s, in ``permissions``,
        and none of that reasoning is here — this asks only whether a record
        already in hand is a record of *this* request being allowed. It is
        therefore computable from the two values alone, independent of policy,
        configuration, context and clock, and the same answer for every
        consumer: ADR-0016 §2's three-part test for a semantic intrinsic to a
        type. Putting it in ``permissions`` instead would fail for the reason
        ADR-0016 §2 gave when it declined to put the severity ordering in a
        subsystem — both ``permissions`` and the future invocation path need it,
        golden rule 1 forbids either importing the other, so it would become two
        copies of a safety-critical comparison free to disagree.

        The authorisation pointer is deliberately *not* re-checked here: it is
        validated once, by ``AuditTrail.record``, at the boundary where the
        referenced record is in hand, rather than at every later read where it
        is not.
        """
        return (
            self.ruling.outcome is PermissionOutcome.ALLOW
            and request.tool == self.tool
            and request.parameters_digest == self.parameters_digest
            and request.step_id == self.step_id
        )

    @model_validator(mode="after")
    def _a_resolution_is_not_itself_a_question(self) -> PermissionDecision:
        """Refuse a resolving decision whose own ruling is ``CONFIRM``.

        Keeps the chain one link long, so it cannot loop. Asking twice about one
        request is a flow ADR-0021 does not offer; a policy that wants to is
        issuing a *new* request.

        The rest of the resolution invariant is enforced by ``AuditTrail.record``
        rather than here, because it is the only place both records are in hand:
        a decision in isolation cannot see the decision it names, which is
        exactly why leaving that half to a model validator would have been
        leaving it undone.
        """
        if self.resolves is not None and self.ruling.outcome is PermissionOutcome.CONFIRM:
            msg = "a resolving decision may not itself be a CONFIRM"
            raise ValueError(msg)
        return self


class ToolOutcome(StrEnum):
    """How an invocation finished (ADR-0029 §3).

    Three members, one for each :class:`StepStatus` a finished invocation can
    produce, so an executor's mapping is total and needs no default branch. A
    separate enum rather than reusing :class:`StepStatus` because that type also
    spells ``RUNNING`` and ``AWAITING_APPROVAL``, which a *result* must not be
    able to say.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    """The call may or may not have taken effect; ADR-0014 §4's durable ignorance."""


class ToolFailure(BaseModel):
    """Why an invocation failed, in a form an executor can record (ADR-0029 §3).

    :attr:`message` is **operator-facing Tier 2 text and must not carry Tier 0 or
    Tier 1 data**. It is bound for a log and for ``StepFailure.message`` on a
    finished step (ADR-0039), and ADR-0004 §5 forbids Tier 1 data in both. There
    is no safety net under it:
    ``core/logging.py`` redacts by *key*, and its own docstring names
    ``error=str(exc)`` — "where the provider quoted the user's prompt" — as the
    leak it cannot see. So the rule holds at the producer: an integration
    *authors* its message rather than copying an upstream error body, and a
    message the seam generates carries no content the seam did not author.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ToolFailureKind
    message: str = Field(description="Operator-facing explanation; Tier 2 only.")

    @field_validator("message")
    @classmethod
    def _message_is_present(cls, value: str) -> str:
        """Reject a message with nothing visible in it, returning it stripped.

        The ``_has_visible_text`` test ADR-0018 §1 applies to a tool's
        description and ADR-0021 §1 to a ruling's reason, for the same reason: a
        failure that renders as nothing leaves the executor and the user with
        nothing to say about it.
        """
        stripped = value.strip()
        if not _has_visible_text(stripped):
            msg = "tool failure message must contain visible text"
            raise ValueError(msg)
        return stripped


class ToolResult(BaseModel):
    """What an invocation produced, as data rather than as an exception (ADR-0029 §3).

    Failure is *returned* because ``INDETERMINATE`` cannot be an exception: an
    executor that learned "we do not know whether the effect happened" by
    catching something would be one ``except Exception:`` away from recording a
    completed action as failed.

    :attr:`output` is :data:`FrozenJsonValue`, matching ``StepExecution.output``
    exactly, so a result is recordable without translation and a tool cannot
    return a live object that mutates after the step recorded it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: ToolOutcome
    output: FrozenJsonValue = Field(default=None, description="Only meaningful when SUCCEEDED.")
    failure: ToolFailure | None = Field(default=None, description="Required unless SUCCEEDED.")

    @model_validator(mode="after")
    def _outcome_fields_match(self) -> ToolResult:
        """Refuse a result that half-says two things.

        Every combination refused here has a wrong state that reads as
        plausible. A ``FAILED`` result with no failure leaves the executor
        writing ``StepExecution.failure`` — required when ``FAILED`` (ADR-0014
        §3, ADR-0039) — with nothing to write. A ``SUCCEEDED`` result carrying one is a
        contradiction a caller reads whichever half it looks at first. And a
        non-``SUCCEEDED`` result carrying an output is a *partial* result an
        executor could record as a whole one, which is worse than an absent one.
        """
        succeeded = self.outcome is ToolOutcome.SUCCEEDED
        if succeeded and self.failure is not None:
            msg = "a SUCCEEDED result carries no failure"
            raise ValueError(msg)
        if not succeeded and self.failure is None:
            msg = f"a {self.outcome} result requires a failure"
            raise ValueError(msg)
        if not succeeded and self.output is not None:
            # The value itself is never interpolated: a tool's output carries
            # Tier 1 data routinely, and a ValidationError message is bound for
            # a log the redactor cannot see into (ADR-0029 §3).
            msg = f"a {self.outcome} result carries no output, got a {type(self.output).__name__}"
            raise ValueError(msg)
        return self


class ToolCall(BaseModel):
    """An authorised invocation: the request, and the authority for making it (ADR-0029 §2).

    **An unauthorised call is unconstructable.** The validator below runs
    ADR-0021 §1's ``authorises`` — the one call that ADR said "belongs to the
    invocation contract" — at construction, so no conforming caller can hand a
    seam a call it was not authorised to make, because the value does not exist.
    A ``DENY`` or an unanswered ``CONFIRM`` cannot construct one; nor can altered
    arguments, a substituted definition, or a different step.

    **Construction is the first line, not the only one.** ``frozen=True`` refuses
    ``call.request = ...`` and does nothing about ``call.__dict__["request"]``,
    and that bypass is inside this repository's threat model (ADR-0018 §3,
    ADR-0021 §4). :meth:`~ai_assistant.core.protocols.ToolInvoker.invoke`
    therefore re-runs the same check against a revalidated, detached copy. The
    validator stays because it catches the honest mistake at the point it is
    made, with a better message and no I/O; the seam's checks are what hold
    against a deliberate one.

    **It carries no third field, and the absences are the design**: no credential
    (ADR-0029 §6), no timeout (it is not part of what was authorised), no
    idempotency key as data (it is derived, below), and no tool id — the
    definition is carried by value, so there is no name left to rebind.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: ActionRequest = Field(description="What to do.")
    decision: PermissionDecision = Field(description="The authority for doing it.")

    @model_validator(mode="after")
    def _authorised(self) -> ToolCall:
        """Refuse a call the decision does not authorise.

        Delegates wholly to :meth:`PermissionDecision.authorises`, which is why
        this can live in ``core``: the validator compares two values it is given
        and introduces no new comparison. Whether an action *should* be allowed
        stays ``ActionPolicy``'s, in ``permissions``.
        """
        if not self.decision.authorises(self.request):
            msg = (
                f"decision {self.decision.id!r} does not authorise this request: it must be an "
                "ALLOW for the same tool, the same parameters and the same step"
            )
            raise ValueError(msg)
        return self

    @property
    def idempotency_key(self) -> str | None:
        """The key a ``KEYED`` tool is called with, or ``None`` (ADR-0029 §5).

        Derived rather than minted, and that is what gives it the three
        properties a key needs without asking a caller for any of them. It is
        **stable across retries**, because every retry of an authorised call
        reuses this same :class:`ToolCall` and hence the same decision — there is
        deliberately no attempt counter in it. It is **distinct for a distinct
        intent**, because asking to send the same message again produces a new
        request and a new decision. And it is **recoverable across a restart**,
        which is the property that makes it worth anything: a restarted executor
        reads ``StepExecution.approval_ref``, loads the decision from the durable
        trail, and derives the identical key.

        Read from the *decision's* copy of the declaration rather than the
        request's. The two are equal — ``authorises`` compares them — so this
        changes no answer for a valid call, but the decision's copy is the one
        the trail holds, which is the copy a restart reconstructs from.
        """
        if self.decision.tool.idempotency is not Idempotency.KEYED:
            return None
        return self.decision.id

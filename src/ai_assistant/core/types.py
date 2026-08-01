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
from typing import Annotated, Any, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import AfterValidator

# --- preamble: shared values, and the helper that never raises ---------------
# `_FULL_CONFIDENCE` belongs to `Provenance` below, `Embedding` to ADR-0006's
# retrieval seam. `describe_untrusted` is module-wide, and `core/clock.py`
# shares it because it owes the same never-raise promise (ADR-0026 §2).


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


# --- instants: one canonicaliser, one field type (ADR-0023, ADR-0030) --------
# `core`'s only UTC canonicaliser, and the `UtcInstant` annotation every
# `datetime` field in this module carries rather than validating per field.
# A second implementation of this test is forbidden (ADR-0030 §4).


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


# --- the other scalar refinements, and the one canonical encoding -------------
# ``EncodableText``, ``Identifier``, ``Sha256Hex`` and the canonical-JSON
# encoding sit **here**, beside :data:`UtcInstant`, because they are the same
# kind of thing: pure refinements of a scalar that every section of this module
# may reach for. They used to live further down, next to their first consumer in
# `permissions`, which was fine while there was one consumer. ADR-0078 gives the
# memory section a second: a deferred question is identified, digested and
# keyed, and :class:`MemoryUpdateProposal` is declared long before the permission
# types. A forward reference plus ``model_rebuild`` would have kept the old
# positions at the cost of making two `core` types depend on an import-order side
# effect, so the primitives moved instead of the models. Nothing about them
# changed. ``_is_encodable`` joined them for the same reason: :data:`Identifier`
# is now built on it, and it is declared before its first use rather than relying
# on a ``type`` alias's lazy evaluation to reach forwards.


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


def encodable_text(value: str) -> str:
    r"""Reject text that has no UTF-8 encoding.

    **The predicate is exactly "``value.encode('utf-8')`` succeeds", and nothing
    wider.** ADR-0087 §2b names one ``str`` that has no wire form — a surrogate
    code point, which is half of a character rather than a character — and
    positively *permits* everything a reader might expect to see refused
    alongside it: a C0 control character takes an escape, U+007F is emitted raw,
    and so are U+2028 and U+2029. Refusing those would contradict §2b rather
    than implement it. The set is also exactly the surrogates: any code point in
    U+D800 to U+DFFF makes a ``str`` unencodable, paired or not, and no other code
    point does. A real supplementary character such as U+1F600 is four UTF-8
    bytes and is accepted, which is what a check written against the surrogate
    *range* would get wrong (issue #121).

    **Why the type and not the boundary.** ADR-0084 §4 obliges *every*
    implementation of the engine Protocol to enforce the same limits, so a wire
    client is never less capable than the in-process engine; ADR-0087 §7 then
    argues against re-validating one value at each boundary it crosses, and fixes
    that "the place a non-encodable value is refused is the type, not the frame".
    A plain ``str`` field made the two implementations disagree: ``learn(
    FeedbackEvent(content="\ud800"))`` constructed, the in-process engine
    accepted it, and no encoder could put it on the socket (issue #565).
    Refusing at construction is what makes the two agree *by default* rather
    than by discipline, and it is the shape :func:`_freeze_json` already uses for
    the values a :data:`FrozenJson` holder carries.

    **The message names the offending code point and its position, and does not
    echo the value.** The value may be megabytes of untrusted text, and — the
    sharper reason — interpolating it raw would build an error message that is
    itself unencodable, so reporting the fault would fail the same way the fault
    does. A code point and an index are what a caller needs to find it.

    Raises:
        ValueError: If the value has no UTF-8 encoding.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        msg = (
            f"text must have a UTF-8 encoding, so it can cross the wire and reach the store; "
            f"U+{ord(exc.object[exc.start]):04X} at position {exc.start} has none"
        )
        raise ValueError(msg) from exc
    return value


type EncodableText = Annotated[str, AfterValidator(encodable_text)]
"""Text that can actually be written down: a ``str`` with a UTF-8 encoding.

**Every ``str`` a model in this module holds is typed with this, or with a
refinement layered on it.** ``tests/core/test_text_encodability_coverage.py``
fails the gate on a bare ``str`` field, so the property is total over the file
rather than true of the fields someone remembered — the shape
``tests/core/test_instant_coverage.py`` uses for :data:`UtcInstant`, and for the
same reason: ADR-0068 §1 records that ``core/types.py`` "holds only
boundary-crossing types", so a field that opts out is a field on the wire.

Applied even where a stricter rule already refuses the same values —
:data:`Sha256Hex`, :attr:`ToolCost.currency` — deliberately. The point is that
the *type* carries the property, so the coverage check needs no exemption list
and a later relaxation of the stricter rule cannot silently reopen the gap.
"""


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


type Identifier = Annotated[EncodableText, AfterValidator(_non_blank)]
"""A non-blank, stripped identifier that has a UTF-8 encoding.

**The encodability half is not the tightening ADR-0018 §2 deferred, and does not
prejudge it.** That clause declined to fold the *visible-text* rule into this
type, and issue #62 holds the *canonical syntax* question — internal whitespace,
control characters, case. Neither is this property: an identifier with no UTF-8
encoding is not loosely spelled, it cannot be written down at all, and ADR-0087
§7 puts that refusal on the type. Both clauses stay true; :data:`VisibleIdentifier`
is still a separate type and #62 is still open.
"""


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

    :attr:`UserConfirmation.question_key` is the second field of this shape
    (ADR-0078 §2), and it is the sharper case: the key is *authority*, so a value
    that is not a digest at all would be compared against one that is and refuse
    every honest answer.

    Lowercase specifically: ``hexdigest()`` emits lowercase, so accepting
    uppercase would admit a second spelling of the same digest that compares
    unequal — a false mismatch at execution, which reads as an attack rather
    than as a bug.

    Raises:
        ValueError: If the value is not 64 lowercase hex digits.
    """
    if len(value) != _SHA256_HEX_LENGTH or not _HEX_DIGITS.issuperset(value):
        described = describe_untrusted(value)
        msg = f"a sha-256 digest must be {_SHA256_HEX_LENGTH} lowercase hex digits, got {described}"
        raise ValueError(msg)
    return value


type Sha256Hex = Annotated[EncodableText, AfterValidator(_sha256_hex)]
"""A lowercase SHA-256 digest in hex — the form :func:`hashlib.sha256` emits.

Layered on :data:`EncodableText` even though :func:`_sha256_hex` already refuses
everything it would: see that alias's note on why no ``str`` field opts out.
"""


def _canonical_bytes(payload: object) -> bytes:
    """Render ``payload`` in the exact JSON form ADR-0021 §1 pins for a digest.

    ``ensure_ascii=False``, UTF-8, keys ordered, no incidental whitespace — the
    one encoding every digest in this module hashes, so two digests over the same
    facts cannot disagree because they were spelled differently.
    :func:`_canonical_json` narrows this to a validated parameter payload; ADR-0078
    §7's proposal fingerprint hashes a projection of a memory record through it.

    ``payload`` must already be JSON-encodable — a ``model_dump(mode="json")``
    result, or a value :func:`_thaw_json` has flattened. Anything else raises out
    of :func:`json.dumps`, at the boundary that produced it.
    """
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


# --- conversation: the provider-independent turn -----------------------------
# `models/` maps these onto whatever an SDK wants; no SDK's own vocabulary
# crosses into `core` (golden rule 4).


class Role(StrEnum):
    """Who authored a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single turn in a conversation, provider-independent."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: EncodableText
    name: EncodableText | None = Field(default=None, description="Optional author/tool name.")


# --- memory: a record, where it came from, when it is believed (ADR-0005) ----
# The four typed kinds and their discriminated union, plus the two axes every
# record carries: `Provenance` (how it was learnt, and how much to trust it)
# and `Validity` (the valid-time window it is the live belief in, ADR-0045 §2).


class MemorySource(StrEnum):
    """Where a memory came from — the basis for how much to trust it."""

    USER_ASSERTED = "user_asserted"
    OBSERVED = "observed"
    INFERRED = "inferred"
    EXTERNAL = "external"


class BeliefBand(StrEnum):
    """The standing a belief is held with — how far it is from the user's word.

    The three bands partition :class:`MemorySource` (ADR-0072 §2). They name what
    ADR-0005 §2 expressed only as source membership: the *user profile* is the
    ``ASSERTED`` band of the one store, the *inferred user model* is its
    ``DERIVED`` band, and there is no second store and no materialised profile
    (ADR-0072 §1). The word "model" is deliberately absent — in this codebase it
    means the language model (``ModelProvider``, ``models/``).

    Attributes:
        ASSERTED: The user told us; their own word, confidence 1.0. Not
            re-derivable, and losing one is unrecoverable (ADR-0038 §2).
        DERIVED: We worked it out from evidence; provisional, sub-1.0 confidence,
            and re-derivable while the observations behind it are retained.
        ATTESTED: A source the user connected reported it. Neither the user's
            word nor our inference, so it is neither entitled to the standing the
            supersession law protects nor re-derivable by observing harder.
    """

    ASSERTED = "asserted"
    DERIVED = "derived"
    ATTESTED = "attested"


def band_of(source: MemorySource) -> BeliefBand:
    """The band a provenance source places a belief in (ADR-0072 §2).

    The mapping is **total**, and its totality is mechanically enforced: every
    arm names a member and the wildcard does nothing but ``assert_never``, so a
    :class:`MemorySource` added without choosing its band narrows to a
    non-``Never`` type under ``mypy --strict`` and fails the gate rather than
    being silently classified (ADR-0072 §2, the shape of ADR-0038 §2a's
    allow-list argument applied to classification).

    Classification is keyed on ``source`` and never on ``confidence``, so no
    producer can promote a belief into the asserted band by claiming certainty
    (ADR-0072 §4). It applies wherever :class:`Provenance` does — including
    :class:`Goal` — but ADR-0072 §3's obligations on derived beliefs do **not**
    generalise with it; they are scoped to memory proposals.

    Args:
        source: The provenance source of the belief being classified.

    Returns:
        The band that source places the belief in.
    """
    match source:
        case MemorySource.USER_ASSERTED:
            return BeliefBand.ASSERTED
        case MemorySource.OBSERVED | MemorySource.INFERRED:
            return BeliefBand.DERIVED
        case MemorySource.EXTERNAL:
            return BeliefBand.ATTESTED
        case _:  # pragma: no cover - exhaustive
            assert_never(source)


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

    model_config = ConfigDict(frozen=True)

    source: MemorySource
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Belief strength in [0, 1]; user-asserted records are 1.0.",
    )
    evidence: tuple[EncodableText, ...] = Field(
        default=(),
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

    @model_validator(mode="after")
    def _derived_is_never_certain(self) -> Provenance:
        """A belief in the ``DERIVED`` band may not claim certainty (ADR-0077 §7).

        The mirror of the clause above, and the reason both are on the *type*
        rather than in a policy: 1.0 is the standing the user's own word carries
        (ADR-0072 §3), so a value that claims it while naming a source we worked
        out ourselves is incoherent wherever it appears. ``EXTERNAL`` is
        deliberately untouched — a connected source may legitimately report a fact
        it is certain of (ADR-0038 §2a) — and it is not in this band.

        ADR-0072 §3 declined this validator and said exactly when to revisit:
        "there is no producer yet that could violate the rule". ADR-0077's
        observer is that producer, so the condition it named is met.

        Enforcing it here rather than at the ``MemoryPolicy`` gate is what closes
        the confidence half of #432: the gate is not the only path a
        :class:`Provenance` takes — :class:`Goal` carries one and reaches no
        propose/dispose gate at all — and a validator on the value needs no gate.
        The *evidence* obligation #432 also describes stays open, and cannot be a
        validator: an assertion legitimately cites nothing.
        """
        if band_of(self.source) is BeliefBand.DERIVED and self.confidence == _FULL_CONFIDENCE:
            msg = (
                f"{self.source.name} provenance is in the DERIVED band and must "
                f"have confidence below 1.0"
            )
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

    model_config = ConfigDict(frozen=True)

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

    model_config = ConfigDict(frozen=True)

    id: EncodableText
    content: EncodableText = Field(description="Canonical text rendering, used for retrieval.")
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
    participants: tuple[EncodableText, ...] = Field(default=())
    outcome: EncodableText | None = None
    importance: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticMemory(MemoryBase):
    """A durable fact about the user or their world."""

    kind: Literal["semantic"] = "semantic"
    fact: EncodableText
    valid_until: UtcInstant | None = Field(
        default=None,
        description="Optional expiry after which the fact is no longer assumed true.",
    )


class PreferenceMemory(MemoryBase):
    """A user preference, optionally scoped to a context."""

    kind: Literal["preference"] = "preference"
    preference: EncodableText
    context: EncodableText | None = None
    strength: float = Field(default=0.5, ge=0.0, le=1.0)


class ProceduralMemory(MemoryBase):
    """A learned workflow: how the user likes a situation handled."""

    kind: Literal["procedural"] = "procedural"
    situation: EncodableText
    steps: tuple[EncodableText, ...] = Field(default=())


MemoryRecord = Annotated[
    EpisodicMemory | SemanticMemory | PreferenceMemory | ProceduralMemory,
    Field(discriminator="kind"),
]
"""A unit of long-term memory: one of the four typed kinds, tagged by ``kind``."""


# --- memory: one write inside an atomic batch (ADR-0046 §2) ------------------


class MemoryWriteMode(StrEnum):
    """How one write in an atomic batch treats a colliding id (ADR-0046 §2).

    The two modes are exactly the two the supersession applier needs and no more:
    an ``UPSERT`` window-close of the retained target, and an
    ``INSERT_IF_ABSENT`` of the freshly-minted correction whose probabilistic id
    must not clobber an existing record (ADR-0045 §4).
    """

    UPSERT = "upsert"
    """Overwrite the record if its id is present, insert it if absent.

    Reproduces :meth:`~ai_assistant.core.protocols.MemoryStore.add`'s upsert
    semantics — what a window-close is, since the target already exists and is
    overwritten with its retired form.
    """

    INSERT_IF_ABSENT = "insert_if_absent"
    """Insert the record only if its id names no stored record.

    Otherwise the **whole batch** fails with
    :class:`~ai_assistant.core.errors.MemoryStoreConflictError` and nothing is
    committed. "Absent" is *physical presence*, not read-visibility: a stored row
    blocks the insert even when expired or window-closed (ADR-0046 §3).
    """


class MemoryWrite(BaseModel):
    """One write within an atomic ``MemoryStore`` batch (ADR-0046 §2).

    A record paired with the mode that governs how a collision on its id is
    handled. Crosses subsystem boundaries — the applier in `memory` constructs
    it, the store consumes it, the contract in `core` names it — so it is a
    `core` type.

    **Frozen**, so ``mode`` cannot be reassigned after construction. The store
    selects collision behaviour by enum identity (``is
    MemoryWriteMode.INSERT_IF_ABSENT``); without this, ``write.mode = "insert_if_absent"``
    would store a raw string that no backend recognises as the enum, silently
    downgrading an insert-if-absent to an upsert that clobbers a colliding record
    — the exact loss ADR-0046 §3 and §4 exist to prevent. Freezing keeps ``mode`` an
    enum member (pydantic coerces a valid string at construction, then locks it).
    """

    model_config = ConfigDict(frozen=True)

    record: MemoryRecord
    mode: MemoryWriteMode = MemoryWriteMode.UPSERT


# --- data sensitivity tiers (ADR-0004) ---------------------------------------
# Sits inside the memory run, but is not memory's alone: `tools` and
# `permissions` read it through `TierReach` further down, which is what a
# tool's reads/writes/discloses ceilings are expressed in.


class DataTier(StrEnum):
    """Sensitivity classification of stored data (see ADR-0004)."""

    SECRET = "secret"  # noqa: S105  # Tier 0 tier name, not a credential value.
    PERSONAL = "personal"  # Tier 1: PII, memories, user-model facts.
    OPERATIONAL = "operational"  # Tier 2: non-sensitive settings, caches.


# --- memory: proposal -> policy ruling -> ingest result (ADR-0028) -----------
# The write path the model never takes directly: it proposes, a deterministic
# `MemoryPolicy` disposes. `REINFORCE` and `SUPERSEDE` name the *relation* to
# the target record, never the write that relation causes (ADR-0040 §1).


#: The record fields ADR-0078 §7 excludes from the proposal fingerprint: each is
#: bookkeeping *about* the record rather than part of the belief it states, and
#: including any of them would make a question's identity change without the
#: question changing. ``provenance.last_updated`` is the third and is removed one
#: level in, inside the nested projection.
_FINGERPRINT_EXCLUDED_RECORD_FIELDS: frozenset[str] = frozenset({"id", "score"})


def _canonical_members(values: Sequence[str]) -> list[str]:
    """Normalise a collection that is a *set in meaning* (ADR-0078 §7).

    Sorted **and deduplicated**, because for a bag of references membership is the
    content and position is an artefact of how they were gathered. Deduplication
    is the same argument rather than an extra one: ``("e1",)`` and ``("e1", "e1")``
    state the same support, and sorting without deduplicating would let a repeated
    id admit a second question for a set the user has already been asked about.
    """
    return sorted(set(values))


class UserConfirmation(BaseModel):
    """The authority a user's answer to a deferred question carries (ADR-0078 §2, §5).

    A value rather than a naked field on the proposal, **because it is authority,
    and authority that can be inspected is authority that can be bounded**. It
    says three things and no more: which question was answered, what that question
    *was*, and exactly which records the answer authorises retiring.

    ``retires`` is the whole of that authority. It is set to the conflict ids the
    question froze and the surface actually showed (ADR-0078 §5), so the answer
    can never reach a record the user was not shown — which is what turns "explicit
    user confirmation" (ADR-0045 §7) into a bound rather than a blanket.

    ``question_key`` is what **binds the authority to the question it was given
    for**. Without it a confirmation is a bearer token any proposal presenting it
    could spend: two questions can share a proposal exactly and be shown different
    conflicts, and a confirmation bound only to the proposal would carry one
    question's broader ``retires`` into the other's apply, retiring an assertion
    that user never saw. It is :attr:`MemoryUpdateProposal.question_key`, so it
    covers *what was proposed* and *what it was proposed against* together — and it
    binds to what was asked rather than to a minted id, which a caller invents and
    which is unique only once stored.

    **The answer path is its only legitimate producer**, and only from a deferral
    it has claimed (ADR-0078 §3). No type expresses that; it is a
    composition-root obligation with a structural test behind it, and it is the
    obligation this value's whole bound rests on.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    deferral_id: Identifier = Field(
        description="The deferred question this answer is for (ADR-0078 §2)."
    )
    question_key: Sha256Hex = Field(
        description=(
            "The answered question's ``MemoryUpdateProposal.question_key`` — what binds "
            "this authority to that question rather than to any proposal presenting it."
        ),
    )
    confirmed_at: UtcInstant = Field(description="When the user's answer was given (tz-aware).")
    retires: tuple[EncodableText, ...] = Field(
        default=(),
        description=(
            "Record ids this answer authorises retiring: exactly the conflicts the "
            "question froze and the surface showed (ADR-0078 §5). Nothing else."
        ),
    )


class MemoryUpdateProposal(BaseModel):
    """A proposed change to memory, awaiting a policy decision.

    The model never writes memory directly: it emits a proposal that a
    deterministic :class:`~ai_assistant.core.protocols.MemoryPolicy` disposes of.
    """

    model_config = ConfigDict(frozen=True)

    proposed: MemoryRecord
    rationale: EncodableText = Field(description="Why this memory is being proposed.")
    sensitivity: DataTier = Field(
        default=DataTier.PERSONAL,
        description="How sensitive the proposed memory is.",
    )
    conflicts: tuple[EncodableText, ...] = Field(
        default=(),
        description="Ids of existing records this proposal contradicts (from the conflict check).",
    )
    confirmation: UserConfirmation | None = Field(
        default=None,
        description=(
            "The authority a user's answer to a deferred question carries, when this "
            "proposal is one being re-submitted under it (ADR-0078 §2, §5); None otherwise."
        ),
    )

    @model_validator(mode="after")
    def _secret_data_carries_no_confirmation(self) -> MemoryUpdateProposal:
        """Refuse a confirmation on a ``DataTier.SECRET`` proposal (ADR-0078 §1, §5a).

        A confirmation exists only because a question was queued, claimed and
        answered — and a secret-tier proposal is **never queued**: ADR-0004 §3 puts
        Tier 0 content in the OS keyring and forbids it a committed file, so
        :class:`DeferredProposal` refuses one and the write stage never offers it
        one. There is therefore no deferral for such a proposal, no claim over it,
        and no answer to it. The pairing is a *contradiction*, not a case the
        applier should be left to rule on, so it is unconstructable rather than
        merely refused downstream — the one half of ADR-0078's belt-and-braces
        that a bypass cannot get past.
        """
        if self.confirmation is not None and self.sensitivity is DataTier.SECRET:
            msg = (
                "a DataTier.SECRET proposal cannot carry a confirmation: secret-tier data is "
                "never queued as a question, so no answer to one can exist (ADR-0078 §1)"
            )
            raise ValueError(msg)
        return self

    @property
    def proposal_fingerprint(self) -> Sha256Hex:
        """A stable digest of *what is being proposed* (ADR-0078 §7).

        SHA-256 over :func:`_canonical_bytes`' ADR-0021 §1 encoding of a
        **canonical projection** of :attr:`proposed`, plus :attr:`sensitivity`.
        A property on the model that owns the data rather than a field each caller
        filled in, for the reason :attr:`ActionRequest.parameters_digest` is one:
        two callers' canonicalisations that disagreed would produce a false
        mismatch, and here the symptom is that **no asserted conflict is ever
        confirmable** — the coordinator digests at admission and the writer
        recomputes at answer time, so a digest that can come apart from itself
        refuses every honest answer.

        **The projection is the whole record minus the three fields that are
        bookkeeping about the record rather than the belief it states**, and the
        criterion decides the next one rather than an inventory having to be
        extended by whoever adds it:

        * ``id`` — identity, minted per proposal, so including it makes the key
          match nothing at all.
        * ``score`` — populated only by retrieval (ADR-0005 §1); it says how a
          search ranked something, not what is believed.
        * ``provenance.last_updated`` — **transaction time** (ADR-0045 §3): when
          the record was written, not what it says. Two identical observations a
          minute apart would otherwise be two questions, and the user would be
          nagged by the mechanism whose job is to stop that.

        Everything else stays in, including ``validity`` (a belief expiring
        tomorrow and an open-ended one are different things to be asked to accept),
        ``confidence`` (weakly and strongly offered are different offers,
        ADR-0072 §6) and ``provenance.source``. :attr:`rationale` is out because
        the projection is over the record and the tier; :attr:`confirmation` is out
        because it is authority rather than content, which is also what lets the
        writer recompute the key of a proposal it has just attached one to.

        **Collections that are *sets in meaning* are sorted and deduplicated;
        every other order is preserved.** The criterion is whether reordering the
        members changes what the record says. ``Provenance.evidence`` is a bag of
        references — "references (e.g. episode ids) supporting this record" — where
        membership is the content, and conflict detection ranks by score, so two
        equal-scored gatherings come back in either order; digesting the raw
        sequence would mint two keys for one question. ``ProceduralMemory.steps``
        is the opposite: a workflow *is* its order, and "back up the database, then
        delete it" must never suppress "delete the database, then back it up". For
        a genuinely ambiguous field ADR-0078 §7 decides the tie explicitly —
        **preserve the order** — because the cost of preserving it is a duplicate
        question the user can dismiss, and the cost of normalising it wrongly is a
        question they never see. ``EpisodicMemory.participants`` is that case and
        keeps its order.
        """
        return sha256(_canonical_bytes(self._fingerprint_projection())).hexdigest()

    @property
    def question_key(self) -> Sha256Hex:
        """A stable digest of *what is being proposed, against what* (ADR-0078 §7).

        ``digest(proposal_fingerprint, canonical conflict ids)`` — the outer of the
        two layers, and the one the deferral queue dedups on and a
        :class:`UserConfirmation` binds to. A question is not merely a proposal: it
        is a proposal shown **against a particular conflict set**, so two questions
        can share a fingerprint exactly and still be different questions. The
        conflict ids are canonicalised the way ``evidence`` is — sorted and
        deduplicated — because membership is the content there too, and a repeated
        or reordered id would otherwise admit a second question for a set the user
        has already been asked about.

        A property, not a field, so the question's identity is a function of the
        proposal that holds it and the two cannot disagree — which is why
        :class:`DeferredProposal` carries no key of its own.
        """
        payload = {
            "proposal_fingerprint": self.proposal_fingerprint,
            "conflicts": _canonical_members(self.conflicts),
        }
        return sha256(_canonical_bytes(payload)).hexdigest()

    def _fingerprint_projection(self) -> dict[str, object]:
        """The canonical projection :attr:`proposal_fingerprint` digests.

        Built from ``model_dump(mode="json")`` rather than from the live objects,
        so a record reconstructed field-by-field from a serialised form projects
        identically to the one it was serialised from (ADR-0078 §10's parity
        clause) — the failure that clause guards is not a mismatch on some input
        but a mismatch on *every* input.
        """
        record: dict[str, Any] = self.proposed.model_dump(mode="json")
        for excluded in _FINGERPRINT_EXCLUDED_RECORD_FIELDS:
            record.pop(excluded, None)
        provenance: dict[str, Any] = dict(record["provenance"])
        provenance.pop("last_updated", None)
        provenance["evidence"] = _canonical_members(provenance.get("evidence") or ())
        record["provenance"] = provenance
        return {"proposed": record, "sensitivity": self.sensitivity.value}


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

    model_config = ConfigDict(frozen=True)

    kind: MemoryDecisionKind
    reason: EncodableText = Field(description="Human-readable justification, for transparency.")
    target_id: EncodableText | None = Field(
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
    """The outcome of ingesting a :class:`MemoryUpdateProposal`.

    ``conflicts`` is what the ruling was ruled **against** (ADR-0078 §4). ADR-0028
    §3 declined it and named the exact condition for revisiting — "if a consumer
    ever needs to *show* a user what a proposal contradicted, that is a change to
    the result type, decided then, with a use case in hand" — and a deferred
    question is that consumer. It is stronger than presentation: the shown set is
    the **bound on what an answer authorises** (ADR-0078 §5), so the ids are
    load-bearing for correctness rather than decoration.

    Nothing new is computed for it. The writer already resolves conflicts onto its
    own copy of the proposal before the policy rules; the value simply now crosses
    the writer seam as well as the policy one, which is what lets a coordinator
    enqueue a question showing the conflicts the policy actually saw instead of
    re-deriving them (the duplication ADR-0028 §4 deleted) or re-detecting them at
    answer time, by which point the set has moved.
    """

    model_config = ConfigDict(frozen=True)

    decision: MemoryDecision
    record_id: EncodableText | None = Field(
        default=None,
        description=(
            "Id of the record left live by the write, or None if nothing was stored. "
            "For a REINFORCE it is the reinforced record's id; for a SUPERSEDE, the id "
            "of the record now holding the live belief (ADR-0045 §4)."
        ),
    )
    conflicts: tuple[EncodableText, ...] = Field(
        default=(),
        description=(
            "Ids of the existing records this ingest resolved and the policy ruled "
            "against, on every ruling (ADR-0078 §4). Empty when nothing conflicted."
        ),
    )


# --- memory: the deferred question, and the answer that resolves it (ADR-0078) -
# An `ASK_USER` ruling produces a *question about a candidate belief*, not a
# belief of any band: it is never returned by retrieval, never listed as a
# belief, and contributes no confidence and no evidence to anything (§1). These
# are the types the durable queue that holds one exchanges.


class DeferralState(StrEnum):
    """Where a deferred question stands (ADR-0078 §2).

    **There is no ``EXPIRED`` member, and its absence is the decision.** Expiry is
    read-time-relative and never stamped, exactly as ``MemoryRecord.expires_at``
    is (ADR-0007 §3, ADR-0045 §6): past its deadline a question is simply not
    presented and not claimable, so nothing has to run for it to stop being
    answerable and there is no sweep whose failure re-opens one. ``STALE`` *is*
    stored, because it records something that happened — a person answered and the
    system declined to act — where a question nobody answered records nothing.
    """

    PENDING = "pending"
    """Answerable: nobody has begun an answer, and the deadline has not passed."""

    APPLYING = "applying"
    """An answer was claimed and may be committing right now (ADR-0078 §9).

    One-way: there is no ``release``, no lease and no timeout, because anything
    that could re-open a *stranded* claim could re-open a **live** one, and the
    second apply is the duplicate correction the claim exists to prevent. A row
    left here by a crash is disposed of by the user, never swept.
    """

    ACCEPTED = "accepted"
    """The answer was applied; the record it left live is named on the deferral."""

    REJECTED = "rejected"
    """The user declined. Nothing was written, and the record is **retained**.

    Retention is what makes dedup honest (ADR-0078 §6, §7): without it a chatty
    producer re-proposes tomorrow and the user is asked something they already
    declined. Asking again is not honesty, it is nagging.
    """

    STALE = "stale"
    """The answer arrived, and the belief it was about no longer applied.

    The proposal's own validity window was closed at the answer instant, so
    accepting would have written a record every later read hides — a belief born
    dead. Distinct from a lapsed deadline: that says *the question* went
    unanswered too long, and telling a user who answered promptly they were too
    slow would be the wrong sentence (ADR-0078 §6).
    """

    REDEFERRED = "redeferred"
    """The answer was used, and raised a further question the record names.

    Reached when re-ingesting the answered proposal surfaced an assertion the user
    was never shown: nothing was written, a successor question was admitted, and
    this record names it so the chain is walkable. A completed answer, not a
    failed one — without this state a re-deferred answer has no legal transition
    out of ``APPLYING`` and strands forever (ADR-0078 §5a, §9).
    """


#: The states a deferred question can finish in. Every one of them requires
#: ``answered_at``: reaching any means an answer arrived and was recorded.
TERMINAL_DEFERRAL_STATES: frozenset[DeferralState] = frozenset(
    {
        DeferralState.ACCEPTED,
        DeferralState.REJECTED,
        DeferralState.STALE,
        DeferralState.REDEFERRED,
    }
)


class DeferralAdmissionOutcome(StrEnum):
    """What happened when a question was offered to the queue (ADR-0078 §2, §7).

    A closed set with a name rather than three strings described in prose,
    because the coordinator branches on it **exhaustively** and an exhaustive
    ``match`` needs a type that can be exhausted. Left as free-form text, two
    conforming stores spell the same outcome differently and no consumer can
    depend on either.
    """

    ADMITTED = "admitted"
    """The question was parked, and the admission carries the new deferral."""

    SUPPRESSED = "suppressed"
    """An existing question the key still speaks for stands in the way.

    Nothing was inserted and the admission carries **that** deferral, so a caller
    can say which question it was and in what state — a rejected one to forget, or
    an interrupted answer to dispose of. Both this and ``ADMITTED`` are successes,
    and a caller must be able to tell them apart to say anything honest at all.
    """

    REFUSED = "refused"
    """The answerable queue was at its cap; nothing was admitted and there is no
    deferral to read.

    A cap that refuses the *new* question rather than evicting an old one: the
    producer still holds what it proposed and can re-propose, whereas an evicted
    question is gone with nobody left to notice (ADR-0078 §7).
    """


class DeferredProposal(BaseModel):
    """A memory proposal the policy deferred, held as a durable question (ADR-0078 §2).

    **It is a question, not a belief.** ``band_of`` applied to its proposal says
    only which band the record *would* enter if accepted, never what the system
    holds — so a pending question is absent from retrieval, absent from belief
    inspection, and contributes no confidence and no evidence to anything (§1).

    **A record the store produces, never one a caller hands in.** Every instant on
    it is stamped by the store from its own injected clock and ``retention`` from
    the lifetime it was constructed with, because each of those instants decides
    something a caller would otherwise be deciding for itself: ``answered_at`` is
    a retention anchor, so a caller supplying it chooses how long its own rejection
    suppresses the next honest proposal, and ``deferred_at``/``expires_at`` are the
    lifetime, so a caller supplying them admits a question already lapsed or one
    that holds the queue and its Tier 1 content for decades. Neither is caught by
    a validator that only checks the fields agree with each other — 1970 and 2100
    are both perfectly self-consistent. Likewise **every state after ``PENDING``
    is reached by a transition the ``DeferralStore`` Protocol owns**, never by
    being handed in.

    The validator below still enforces the whole record, because the type crosses
    the Protocol boundary on every read: its invariants belong on the model rather
    than in one implementation's care, the same reason
    :meth:`MemoryDecision._outcome_fields_are_consistent` is a validator and not a
    comment.

    **The duration is stored as well as the instant, and that is not redundancy.**
    ``expires_at`` answers "is this still answerable?" and is fixed at admission
    (ADR-0059 §1's ruling that a confirmation's lifetime rides on the record
    rather than being recomputed from a live setting). The *other* deadline — how
    long a resolved question's record is kept — is anchored on ``answered_at``,
    which is not known until the answer arrives, so it can only be computed later:
    defer under a 30-day lifetime, reject tomorrow, shorten the setting to a day,
    and a live-setting computation drops the rejected key 29 days early and re-asks
    a question the user already declined. So the duration rides on the record and
    the sweep reads it there. Live configuration governs questions admitted from
    now on; it never reaches back.

    ``None`` in ``retention`` and ``expires_at`` is the user's deliberate "ask me
    forever" (§6): the question never lapses and its record is never purged, the
    way ``episode_retention`` reads ``None`` as "keep forever… the user's
    deliberate choice".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The question's own id, minted by the coordinator.")
    proposal: MemoryUpdateProposal = Field(
        description=(
            "The deferred proposal verbatim, *including* the ``conflicts`` ids resolved at "
            "ruling time — the frozen set the question was asked about (ADR-0078 §3, §4)."
        ),
    )
    decision: MemoryDecision = Field(
        description=(
            "The ``ASK_USER`` ruling that deferred it; its non-optional ``reason`` is what "
            "a surface renders as why the user is being asked."
        ),
    )
    state: DeferralState = Field(description="Where the question stands (ADR-0078 §2).")
    deferred_at: UtcInstant = Field(description="When the question was admitted (tz-aware).")
    retention: timedelta | None = Field(
        description=(
            "The lifetime in force *at admission*, stamped once and never recomputed; "
            "None is the deliberate 'ask me forever' (ADR-0078 §2, §6)."
        ),
    )
    expires_at: UtcInstant | None = Field(
        description=(
            "The answerability deadline: ``deferred_at + retention``, or None when the "
            "question never lapses. Half-open — answerable while ``now < expires_at``."
        ),
    )
    claimed_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When an answer was begun, once claimed. The claim **token** is deliberately "
            "not a field here: no read may republish a capability (ADR-0078 §2)."
        ),
    )
    predecessor_id: Identifier | None = Field(
        default=None,
        description=(
            "The question this one succeeds, when it was raised by a re-deferral; None "
            "otherwise. The child names its parent so a token authorises rather than "
            "identifies (ADR-0078 §2)."
        ),
    )
    answered_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the answer was recorded, once resolved. A retention anchor, which is "
            "why the store stamps it and no call can supply it."
        ),
    )
    outcome_record_id: Identifier | None = Field(
        default=None,
        description="The record an accepted apply left live; set on ACCEPTED and nothing else.",
    )
    successor_id: Identifier | None = Field(
        default=None,
        description=(
            "The question a REDEFERRED answer raised — or the already-open one it "
            "collapsed onto. Set on REDEFERRED, and stamped on a parent when its "
            "successor is admitted (ADR-0078 §2)."
        ),
    )

    @model_validator(mode="after")
    def _is_a_coherent_question(self) -> DeferredProposal:
        """Enforce the whole record: its tier, its ruling, its deadlines, its lifecycle.

        Four groups, each of which admits a perfectly well-typed record that
        defeats something this queue promises (ADR-0078 §2):

        * **The sensitivity.** A ``DataTier.SECRET`` proposal is refused. ADR-0004
          §3 is unconditional — Tier 0 secrets live in the OS keyring, "never in
          the memory database, never in a committed file" — and a durable queue is
          a file. Today the secret-tier arm of the policy is precisely what keeps
          such content *out* of storage, so persisting it here would open a gap
          rather than close one. The write stage filters those out before it calls
          ``defer``; this is the rule that holds however the store is called.
        * **The ruling.** ``decision.kind`` **is** ``ASK_USER``. A record built
          around an ``ACCEPT`` or a ``SUPERSEDE`` is not a question at all — it is
          a durable pending entry for a proposal nobody deferred, which a surface
          would present and an answer path would re-ingest as though a user had
          been asked. A public type may not rely on its one honest caller.
        * **The deadlines.** ``retention`` is positive or ``None``; ``retention``
          and ``expires_at`` are ``None`` together or not at all; and when both are
          set, ``expires_at`` is exactly ``deferred_at + retention``. Without this a
          question is admissible with a one-day ``retention`` and no
          ``expires_at``, and a literal implementation keeps it answerable forever
          and never purges it — §1's finite exposure cap defeated by a record the
          contract accepted.
        * **The lifecycle.** Each state requires its own stamps and forbids the
          others'. ``REJECTED`` is the one terminal state legal both with and
          without ``claimed_at``, because an unclaimed rejection writes nothing and
          so needs no claim; every other terminal state requires one, or an apply
          would be recorded as claim-protected when no claim ever covered it.

        Raises:
            ValueError: If any of the four groups is violated.
        """
        self._check_sensitivity()
        self._check_ruling()
        self._check_deadlines()
        self._check_lifecycle()
        return self

    def _check_sensitivity(self) -> None:
        """Refuse a Tier 0 proposal: ADR-0004 §3 forbids it a committed file."""
        if self.proposal.sensitivity is DataTier.SECRET:
            msg = (
                "a DataTier.SECRET proposal may not be deferred: Tier 0 secrets live in the OS "
                "keyring, never in a database or a committed file (ADR-0004 §3, ADR-0078 §1)"
            )
            raise ValueError(msg)

    def _check_ruling(self) -> None:
        """Refuse a record built around a ruling that is not a question."""
        if self.decision.kind is not MemoryDecisionKind.ASK_USER:
            msg = (
                f"a deferred proposal must carry an ASK_USER ruling, got "
                f"{self.decision.kind}: nothing else is a question the user can answer "
                f"(ADR-0078 §2)"
            )
            raise ValueError(msg)

    def _check_deadlines(self) -> None:
        """Refuse a lifetime that is non-positive, half-set, or inconsistent."""
        if self.retention is not None and self.retention <= timedelta(0):
            msg = f"retention must be a strictly positive duration or None, got {self.retention}"
            raise ValueError(msg)
        if (self.retention is None) != (self.expires_at is None):
            msg = (
                "retention and expires_at are None together or not at all: a half-set "
                "lifetime keeps a question answerable forever and never purges it "
                "(ADR-0078 §2)"
            )
            raise ValueError(msg)
        if (
            self.retention is not None
            and self.expires_at is not None
            and self.expires_at != self.deferred_at + self.retention
        ):
            msg = (
                f"expires_at must be exactly deferred_at + retention, got {self.expires_at} "
                f"for {self.deferred_at} + {self.retention}"
            )
            raise ValueError(msg)

    def _check_lifecycle(self) -> None:
        """Refuse stamps and payload that do not belong to the state.

        ``successor_id`` is deliberately **not** treated as terminal payload on an
        ``APPLYING`` row: the store stamps it when it admits the successor, in the
        same commit, so a parent legitimately carries one while its own answer is
        still in flight — that is the state a cancellation caught after the
        successor's admission leaves behind, and ADR-0078 §9 names it explicitly.
        What ``APPLYING`` forbids is an *outcome*: ``answered_at`` and
        ``outcome_record_id``, neither of which exists until the answer is recorded.
        """
        if self.state is DeferralState.PENDING:
            if self.claimed_at is not None or self.answered_at is not None:
                msg = "a PENDING deferral carries neither claimed_at nor answered_at"
                raise ValueError(msg)
            if self.outcome_record_id is not None or self.successor_id is not None:
                msg = "a PENDING deferral carries no terminal payload"
                raise ValueError(msg)
            return
        if self.state is DeferralState.APPLYING:
            if self.claimed_at is None:
                msg = "an APPLYING deferral requires claimed_at: it is a claim in flight"
                raise ValueError(msg)
            if self.answered_at is not None or self.outcome_record_id is not None:
                msg = "an APPLYING deferral records no outcome: no answer has been recorded yet"
                raise ValueError(msg)
            return
        self._check_terminal()

    def _check_terminal(self) -> None:
        """Refuse a terminal record whose stamps or ids are not that state's."""
        if self.answered_at is None:
            msg = f"a {self.state} deferral requires answered_at: an answer was recorded"
            raise ValueError(msg)
        # `REJECTED` is the one terminal state reachable without a claim (an
        # unclaimed rejection writes nothing, so it needs no claim); every other
        # terminal state means an apply ran under one.
        if self.claimed_at is None and self.state is not DeferralState.REJECTED:
            msg = (
                f"a {self.state} deferral requires claimed_at: only an unclaimed REJECTED "
                f"resolution reaches a terminal state without a claim (ADR-0078 §2)"
            )
            raise ValueError(msg)
        if self.state is DeferralState.ACCEPTED:
            if self.outcome_record_id is None:
                msg = "an ACCEPTED deferral requires outcome_record_id: it names what was written"
                raise ValueError(msg)
            if self.successor_id is not None:
                msg = "an ACCEPTED deferral raised no successor question"
                raise ValueError(msg)
            return
        if self.state is DeferralState.REDEFERRED:
            if self.successor_id is None:
                msg = "a REDEFERRED deferral requires successor_id: it names the question it raised"
                raise ValueError(msg)
            if self.outcome_record_id is not None:
                msg = "a REDEFERRED deferral wrote no record"
                raise ValueError(msg)
            return
        if self.outcome_record_id is not None or self.successor_id is not None:
            msg = f"a {self.state} deferral carries neither a record id nor a successor id"
            raise ValueError(msg)

    def is_answerable_at(self, now: datetime) -> bool:
        """Whether this question can still be answered at ``now`` (ADR-0078 §2).

        ``PENDING`` **and** before ``expires_at``. The comparison is **half-open**
        — answerable while ``now < expires_at``, and **at** ``expires_at`` it is
        not — which is ``Validity.live_at``'s own convention, adopted for
        consistency rather than preference: two deadline notions in one memory
        system that disagree at the instant they name is a defect waiting for the
        first test that lands exactly on it. Defined once here, on the type, so
        every operation that consults the deadline spells it the same way rather
        than one backend writing ``<=`` and another ``<``.

        A question whose ``expires_at`` is ``None`` never lapses out of this.

        Args:
            now: The instant to judge against; the caller reads its own guarded
                clock and passes the reading.

        Returns:
            ``True`` iff the question is ``PENDING`` and ``now < expires_at``.
        """
        return self.state is DeferralState.PENDING and (
            self.expires_at is None or now < self.expires_at
        )

    def speaks_for_its_key_at(self, now: datetime) -> bool:
        """Whether this record still holds its ``question_key`` at ``now`` (ADR-0078 §2, §7).

        A key "still speaks for" a deferral that is **answerable** (``PENDING``,
        before its deadline), **being applied** (``APPLYING``), or **``REJECTED``
        within its retention** — the three states in which a fresh arrival of the
        same question deserves no new entry. Each is a different sentence to the
        user: "you can answer this", "an answer to that may be committing right
        now", and "we asked and you declined".

        A key whose only match is *lapsed-and-unanswered*, ``ACCEPTED``, ``STALE``
        or ``REDEFERRED`` does **not** speak: the question lapsed, was settled, or
        was replaced by the successor it names, and a fresh proposal deserves a
        fresh question. A lapsed row in particular must not suppress anything —
        it is the one outcome a question nobody could answer must not have.

        Args:
            now: The instant to judge against.

        Returns:
            ``True`` iff a fresh arrival of the same question would be suppressed.
        """
        if self.state is DeferralState.APPLYING:
            return True
        if self.state is DeferralState.REJECTED:
            return not self._retention_elapsed_at(now)
        return self.is_answerable_at(now)

    def is_purgeable_at(self, now: datetime) -> bool:
        """Whether a sweep may destroy this record at ``now`` (ADR-0078 §2).

        **Two anchors, and the asymmetry is the decision.** A *terminal* row is
        retained for one further lifetime because something depends on it
        surviving: a ``REJECTED`` key is read to refuse re-asking, and that is the
        whole retention argument. A *lapsed* ``PENDING`` row has no such dependant
        — its key stopped speaking the instant it lapsed, so nothing reads it —
        and giving it the same grace would hold an unanswered Tier 1 proposal for
        **twice** the configured lifetime, while ADR-0078 §1 calls that lifetime
        the cap on how long unresolved sensitive content sits. So:

        * terminal, ``retention`` is not ``None``, and ``answered_at + retention
          <= now``; or
        * ``PENDING``, ``expires_at`` is not ``None``, and ``expires_at <= now``.

        Both are inclusive at the instant they name — answerability seen from the
        other side. ``retention is None`` is a complete answer rather than an
        undefined expression: **a row admitted under "ask me forever" is never
        purged**, in either half, which is the same choice the user made.

        **An ``APPLYING`` row is never purgeable, at any age.** It is the only
        durable record that an answer was begun, and destroying it while its
        ingest may still be running would let the memory write commit against a
        question that no longer exists, so the bookkeeping fails and the fact that
        an answer was given survives nowhere. A sweep may not make that decision; a
        user may, and does, through ``delete``.

        Args:
            now: The instant to judge against.

        Returns:
            ``True`` iff a sweep may remove this record.
        """
        if self.state in TERMINAL_DEFERRAL_STATES:
            return self._retention_elapsed_at(now)
        return (
            self.state is DeferralState.PENDING
            and self.expires_at is not None
            and self.expires_at <= now
        )

    def _retention_elapsed_at(self, now: datetime) -> bool:
        """Whether a terminal row's post-answer retention has run out at ``now``.

        ``False`` when ``retention`` is ``None`` ("keep forever") or when no answer
        has been recorded, so the two halves of :meth:`is_purgeable_at` and
        :meth:`speaks_for_its_key_at` read one definition of the anchor.
        """
        if self.retention is None or self.answered_at is None:
            return False
        return self.answered_at + self.retention <= now


class DeferralClaim(BaseModel):
    """A claimed deferral and the token that authorises acting on it (ADR-0078 §2).

    One value rather than two strings a caller could swap, the reason
    :class:`ParkedBinding` is one. The token is **the capability**: minted by
    ``claim``, returned to that caller alone, and — the part that makes it worth
    anything — **on no other read**. ``get``, ``pending``, ``interrupted`` and
    ``export`` return :class:`DeferredProposal`s, which carry ``claimed_at`` so a
    surface can say *when* an answer was begun, and never the token. Holding the
    token is holding the claim, and an export that carried one would hand the
    ability to resolve a live claim to anything that reads the file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    deferral: DeferredProposal = Field(description="The deferral, now APPLYING.")
    claim_id: Identifier = Field(
        description=(
            "The freshly minted, cryptographically unpredictable token that authorises "
            "resolving this claim and spending its successor exemption (ADR-0078 §2)."
        ),
    )


class DeferralAdmission(BaseModel):
    """What offering a question to the queue produced (ADR-0078 §2, §7).

    **Exactly three shapes, one per outcome**, pinned by the validator the way
    :meth:`MemoryDecision._outcome_fields_are_consistent` pins a ruling's:
    ``ADMITTED`` carries the new deferral, ``SUPPRESSED`` carries the existing one
    the key spoke for, and ``REFUSED`` carries nothing and means the answerable
    queue was at its cap. A physical id collision is not among them — it raises,
    rather than returning a fourth shape nobody would check for.

    The disposition is carried **explicitly** rather than left to be inferred. Two
    weaker shapes were tried and both are wrong: a bare id makes an admission and
    a suppression indistinguishable, and comparing the returned id to the one the
    caller minted fails the moment a caller *retries with the same id* — a
    legitimate pattern after an uncertain failure — because the key-idempotent path
    then returns a row whose id equals the supplied one while being ``REJECTED`` or
    ``APPLYING``, and the caller would announce a newly parked question over a
    suppressed one.

    Reaching for :attr:`deferral` on a ``REFUSED`` admission is the dereference
    the validator exists to make impossible to write by accident.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: DeferralAdmissionOutcome = Field(description="What the store did with the question.")
    deferral: DeferredProposal | None = Field(
        default=None,
        description=(
            "The admitted question, or the existing one that suppressed it; None when "
            "the queue refused it, because there is no question to read."
        ),
    )

    @model_validator(mode="after")
    def _outcome_carries_its_own_shape(self) -> DeferralAdmission:
        """Require a deferral on the two successes and forbid one on the refusal.

        Raises:
            ValueError: If ``ADMITTED``/``SUPPRESSED`` carries no deferral, or
                ``REFUSED`` carries one.
        """
        if self.outcome is DeferralAdmissionOutcome.REFUSED:
            if self.deferral is not None:
                msg = (
                    "a REFUSED admission carries no deferral: the queue was full, so no "
                    "question stands in the way and none was created (ADR-0078 §7)"
                )
                raise ValueError(msg)
            return self
        if self.deferral is None:
            msg = f"a {self.outcome} admission requires the deferral it is about"
            raise ValueError(msg)
        return self


# --- observation: what one pass over a batch of episodes produced (ADR-0077) --
# The producer's return value, and the reason it is a value rather than a bare
# sequence: five proposals could be five good entries, or ten of which five were
# unusable, and only the producer can tell those apart (§4).


class ObservationOutcome(BaseModel):
    """What one :class:`~ai_assistant.core.protocols.Observer` pass produced.

    The proposals an observer distilled from the batch it was handed, plus what
    it threw away getting there. It is a value rather than a
    ``Sequence[MemoryUpdateProposal]`` because a bare sequence cannot distinguish
    "five good beliefs" from "ten entries, five of them unusable" — and silence
    would then read as success, which is the failure ``memory_degraded`` exists to
    prevent (ADR-0022 §3, ADR-0077 §4). It follows
    :class:`MemoryIngestResult`'s precedent that a seam returning more than one
    fact returns a named value rather than a tuple.

    **The two counts are exhaustive and disjoint over what the model emitted**
    (ADR-0077 §4). ``len(proposals) + discarded_unusable + discarded_over_limit``
    equals the number of entries the model emitted, an undecodable response
    counting as exactly one entry — so ``"I cannot help"`` reports one unusable
    discard rather than being indistinguishable from a model that read the batch
    and honestly proposed nothing. No entry is counted in both.

    That invariant is **not** enforced here, and deliberately not: it is a
    statement about a *model response*, which a conforming ``Observer`` need not
    have. An observer with no model emits no entries, and this type would have to
    invent one to check anything. The invariant is held by the tests of each
    model-backed implementation (ADR-0077 §9.3).

    Counts of what the *writer* later refused do not belong here either: a
    proposal the producer legitimately made and the write path then dropped is a
    different fact, and folding it into either count would misreport the model's
    output. That count is the ingesting stage's (ADR-0077 §5).

    Attributes:
        proposals: The beliefs to put through the write path, in the producer's
            own order. Empty is a normal outcome, not an error (ADR-0022 §4).
        discarded_unusable: Entries the producer refused for a reason of its own
            — unparseable, failing validation, citing evidence it was never
            handed, below its evidence floor, or naming a kind an observer may
            not propose.
        discarded_over_limit: Otherwise-usable proposals dropped to meet the
            producer's configured maximum. Discarded rather than queued: a queue
            is durable state nothing here ratifies, and the episodes remain in the
            store for a later pass to read again (ADR-0077 §2).
    """

    model_config = ConfigDict(frozen=True)

    proposals: tuple[MemoryUpdateProposal, ...] = Field(
        default=(),
        description="The beliefs distilled from the batch, in the producer's order.",
    )
    discarded_unusable: int = Field(
        default=0,
        ge=0,
        description="Model entries the producer refused for a reason of its own.",
    )
    discarded_over_limit: int = Field(
        default=0,
        ge=0,
        description="Usable proposals dropped to meet the producer's configured maximum.",
    )


# --- situational context: the assembled "right now" (ADR-0008) ---------------
# Advisory and assembled per request, never durable state.


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

    model_config = ConfigDict(extra="forbid", frozen=True)

    now: UtcInstant = Field(description="The tz-aware reference instant for this context.")
    time_of_day: TimeOfDay
    is_weekend: bool
    within_working_hours: bool = Field(
        description="Whether the local time falls in the configured working-hours window.",
    )


# --- learning: explicit, memory-affecting feedback (ADR-0009) ----------------
# `learning` turns one of these into a `MemoryUpdateProposal` above.


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

    model_config = ConfigDict(frozen=True)

    kind: FeedbackKind
    memory_kind: MemoryKind = Field(description="The typed memory this feedback establishes.")
    content: EncodableText = Field(
        description="Canonical text of the feedback, e.g. 'office is in Boston'."
    )
    subject: EncodableText | None = Field(
        default=None, description="Optional scope/context, e.g. 'email tone'."
    )
    evidence: tuple[EncodableText, ...] = Field(
        default=(),
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


# --- frozen JSON, and the identifier primitive (ADR-0014 §2) -----------------
# Introduced for plan parameters and step outputs, but shared much wider: tool
# schemas, action payloads and audit records all hold `FrozenJson`.
# `Identifier` only refuses a blank — the stricter `VisibleIdentifier` and
# `DurableIdentifier` are layered on it further down.


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


def _deep_freeze(value: FrozenJson) -> FrozenJson:
    """Convert a JSON value into an immutable one, recursively.

    Mappings become :class:`FrozenDict` and lists become tuples, so the
    immutability guarantee is depth-independent rather than true only at the top
    level.

    Raises:
        ValueError: If a non-finite float is encountered. ``NaN`` and the
            infinities satisfy ``float`` but have no JSON representation, so
            they would silently change value on the way through the store or an
            export. This one is refused here structurally rather than by the
            encoding check in :func:`_freeze_json`, because ``json.dumps``
            renders it to a non-JSON token (``NaN``/``Infinity``) instead of
            raising — so running the encoder would let it through.
    """
    if isinstance(value, Mapping):
        return FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, float) and not isfinite(value):
        msg = f"{value!r} has no JSON representation, so it cannot be stored or exported"
        raise ValueError(msg)
    return value


def _freeze_json(value: FrozenJson) -> FrozenJson:
    """Freeze a JSON value, refusing any value that has no JSON encoding.

    Two refusals ride on this one validator, for a single reason: a value that
    satisfies its Python type but has no portable JSON form would validate here
    and then fail far away — on the way through a digest, the store, or an
    export, the "accepted, then unusable" shape ADR-0014 §2 exists to close:

    - a **non-finite float**, refused structurally in :func:`_deep_freeze`
      (``json.dumps`` renders it rather than raising, so the encoder cannot
      catch it);
    - **anything the encoder itself rejects** — a lone surrogate ``str`` with no
      UTF-8 encoding, or an integer past CPython's integer-string conversion
      limit — caught by *running the real encoder* (``json.dumps(...,
      ensure_ascii=False)`` then UTF-8, ADR-0021 §1's pinned form) rather than
      by enumerating the value types that can fail. The surrogate and
      big-integer cases are exactly what an enumeration misses (issues #121,
      #127), and running the encoding encodes keys too, so a surrogate at any
      depth in a key or a value is caught rather than only one in a top-level
      value.

    Every :data:`FrozenJson` holder — plan parameters, step outputs, a tool's
    ``parameters_schema`` — inherits this without a per-holder validator: the
    property protected ("this value can be written down") is intrinsic to the
    value, not to who holds it (ADR-0016 §2). Running the encoder rather than
    enumerating is also what keeps "accepted" and "storable" the same predicate
    as a holder grows fields.

    Raises:
        ValueError: If a non-finite float is present, or the frozen value has no
            JSON encoding.
    """
    frozen = _deep_freeze(value)
    try:
        json.dumps(_thaw_json(frozen), ensure_ascii=False).encode("utf-8")
    except ValueError as exc:
        # UnicodeError is a ValueError, so this one clause covers the lone
        # surrogate and the oversized integer both.
        msg = f"this value has no JSON encoding, so it cannot be stored or exported: {exc}"
        raise ValueError(msg) from exc
    return frozen


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


# --- planning: goals, and the frozen plan (ADR-0014 §§1-2) -------------------
# A step names a capability rather than a tool, which is what keeps tool
# selection a later stage of the pipeline than planning.


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

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    statement: EncodableText = Field(description="Canonical text rendering of the objective.")
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
    intent: EncodableText = Field(description="Human-readable purpose of this step.")
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
    rationale: EncodableText | None = Field(
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


# --- planning: the step-status vocabulary (ADR-0014 §4) ----------------------
# The statuses, and the sets drawn over them. Only the sets live here: the
# transition *graph* is `planning`'s, because it is not intrinsic to the type
# (module docstring, ADR-0016 §2).


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


# --- tools: why an invocation did not succeed (ADR-0029 §3) ------------------
# Declared here, mid-planning, on purpose: `StepFailure` and `StepExecution`
# just below record the tool's own classification rather than a planning-owned
# mirror of it (ADR-0039 §3, ADR-0031 §1). `ToolFailure`, at the end of the
# module, is the seam-facing form the executor reads it from.


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


# --- planning: what actually happened to a step (ADR-0014 §3, ADR-0039) ------
# Kept apart from the plan so the audit record does not mutate as execution
# proceeds, and so recovery is *loading* state rather than reconstructing it.


class StepFailure(BaseModel):
    """Why a step finished without succeeding (see ADR-0039).

    The durable account a finished-unsuccessfully step keeps: an operator-facing
    ``message`` that is always present, and the tool's own ``kind`` when a tool
    produced one. That asymmetry is the whole design — every such step has
    something to say, not every one has a tool's classification to say it with.

    ``frozen=True`` because it is a record of something that already happened:
    what an operator reads while resolving an ``INDETERMINATE`` step must not be
    editable after the fact, the same argument ADR-0014 makes for freezing the
    plan. (:class:`StepExecution` is now frozen too, under ADR-0068.)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: EncodableText = Field(
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

    model_config = ConfigDict(extra="forbid", frozen=True)

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

    model_config = ConfigDict(extra="forbid", frozen=True)

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


# --- planning: the write path, deletion, export (ADR-0014 §5, ADR-0004 §6) ---
# A transition is a command rather than a caller-built state, which is what
# keeps the transition graph authoritative. `PlanExport` is the portable
# snapshot ADR-0004 §6's data rights require.


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
    blocked_by: tuple[EncodableText, ...] = Field(
        default=(),
        description="Ids of still-active executions; non-empty exactly when refused.",
    )
    indeterminate_steps: tuple[EncodableText, ...] = Field(
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


# --- conversations: the durable thread, and the turns indexed under it -------
# ADR-0074's four values. A conversation is durable, server-side state with an
# identity of its own; a turn is the *index entry* that names the episode
# recording it, never the episode itself. All frozen (ADR-0068), every instant a
# `UtcInstant` (ADR-0023, ADR-0030).


#: The ordinal of a conversation's first turn. Ordinals are dense, unique and
#: monotonic per conversation (ADR-0074 §9.2), so "dense from here" is the whole
#: of the numbering rule and both traversals terminate because of it. Public
#: because every ``ConversationStore`` implementation and its conformance suite
#: need the same starting point; a constant one of them re-derived is a numbering
#: two stores could disagree about.
FIRST_TURN_ORDINAL = 1


class Conversation(BaseModel):
    """A durable, device-agnostic conversation (ADR-0074 §1).

    Not a session, not a process, and not a terminal: the record lives in the
    hub, and a client holds nothing but the ``id`` it was given. The id is
    **opaque** — minted server-side by the store's injected id factory, encoding
    no device, path or timestamp — so nothing a future spoke would have to forge
    is baked into it, and no consumer can start relying on it as an ordering.

    **``last_active_at`` and ``last_turn_at`` are two different facts** (§2).
    Activity is "someone was here": set at creation and refreshed whenever a turn
    *begins*, so it is always present and is the key every listing and the
    retention reclaim read. ``last_turn_at`` is "a turn was **recorded**", set by
    the append that writes a turn into the index and unset until one lands — which
    is what tells an empty conversation from one whose first turn landed at once.

    ``deleted_at`` is §8's tombstone stamp rather than a status: a stamped
    conversation is absent from every read that presents it, refuses every later
    append, and survives only so the deletion sweep can still name the episodes it
    must destroy.

    No cross-field ordering is validated. ``started_at``, ``last_active_at`` and
    ``last_turn_at`` all come from an injected clock, which this project never
    promises is monotonic (``core/clock.py``), so a rule like
    ``last_active_at >= started_at`` would make a legitimate clock adjustment
    unrepresentable rather than catching a bug.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="Opaque, random, server-minted (ADR-0074 §1).")
    started_at: UtcInstant = Field(description="When the conversation record was created.")
    last_active_at: UtcInstant = Field(
        description="When someone was last here; set at creation, refreshed as a turn begins."
    )
    last_turn_at: UtcInstant | None = Field(
        default=None,
        description="When a turn was last recorded; unset until one is (ADR-0074 §2).",
    )
    deleted_at: UtcInstant | None = Field(
        default=None,
        description="Tombstone stamp: when the user's deletion was recorded (ADR-0074 §8).",
    )


class ParkedBinding(BaseModel):
    """The ``(execution_id, step_id)`` a parked confirmation is recovered by.

    One value rather than two positional strings, so the pair a recovered resume
    is keyed on (ADR-0044 §3) cannot be swapped in transit. A turn that parked
    records the binding it parked on, and the conversation store resolves that
    binding back to the turn — and so to the conversation the resumption belongs
    in (ADR-0074 §3).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: Identifier
    step_id: Identifier


class ConversationTurn(BaseModel):
    """One turn's entry in a conversation's index (ADR-0074 §3).

    **The index entry, not the content.** The turn's content is exactly one
    ``EpisodicMemory`` in the ``MemoryStore``, named here by ``episode_id`` and
    written immediately *after* this row lands — which is what makes the index an
    intent log: no episode can exist for a conversation without its id having been
    recorded here first (§8). An ``episode_id`` that no longer resolves is
    therefore an ordinary state, not a fault: the episode may have expired, been
    deleted, or never been written at all, and every reader renders that as a gap.

    ``ordinal`` is allocated by the store, dense from :data:`FIRST_TURN_ORDINAL`
    and monotonic within its conversation; ``episode_id`` is *derived* by the same
    store from the conversation and that ordinal, so two captured episodes cannot
    collide by construction rather than by probability.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: Identifier
    ordinal: int = Field(
        ge=FIRST_TURN_ORDINAL,
        description="Position in the conversation; dense, unique and store-allocated.",
    )
    episode_id: Identifier = Field(
        description="Id of the episode recording this turn; derived, and may not resolve."
    )
    occurred_at: UtcInstant = Field(description="When the exchange this turn records happened.")
    parked: ParkedBinding | None = Field(
        default=None,
        description="The binding this turn parked on, where it parked (ADR-0074 §3).",
    )


class ConversationExport(BaseModel):
    """A portable snapshot of conversation state (ADR-0074 §9, ADR-0004 §6).

    Flat, like :class:`PlanExport` and for the same reason: a turn names its
    conversation by id, so the two collections travel side by side rather than
    nested. It carries **no episode content** — episodes are ``MemoryStore``
    records and that store's own export carries them, so repeating them here would
    put the same Tier 1 text in two exports under two retention rules.

    **This is the store's raw snapshot.** A conversation stamped deleted is absent
    from it (that is what the validator below enforces), but a turn whose episode
    no longer resolves is *present*: the store has no way to ask whether an episode
    is live and no business asking (golden rule 1). The user-facing export is
    composed in `orchestration`, which drops those turns and with them any
    conversation left with nothing to show.

    Order is part of the contract and is the order each read uses (ADR-0074 §9.3):
    ``conversations`` by ``last_active_at`` descending with ``id`` ascending as the
    tie-break, ``turns`` by ``conversation_id`` then ``ordinal`` ascending. It is
    asserted by the conformance suite rather than validated here, so that filtering
    an export down — which preserves order — stays a total operation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = Field(
        default=1,
        description=(
            "Shape of this export, pinned to exactly 1 (ADR-0039 §10, ADR-0014 §5): an "
            "export outlives the code that wrote it, so the label must be a fact about "
            "the document rather than a producer's unchecked claim."
        ),
    )
    exported_at: UtcInstant
    conversations: tuple[Conversation, ...] = ()
    turns: tuple[ConversationTurn, ...] = ()

    @model_validator(mode="after")
    def _the_index_is_internally_consistent(self) -> ConversationExport:
        """Enforce what this export documents rather than assuming it.

        An export is the artifact a user takes elsewhere, so a turn whose
        conversation is missing is a fragment of a thread with nothing to place it
        in. The uniqueness rules are the store's own invariants seen from the
        outside — a repeated ordinal or episode id would make the same turn
        addressable two ways — and the deleted-conversation rule is §9's "a
        conversation stamped deleted but not yet reclaimed is **not** exported",
        made unrepresentable rather than left to each producer.
        """
        stamped = sorted(one.id for one in self.conversations if one.deleted_at is not None)
        if stamped:
            msg = f"export must not carry conversations stamped deleted: {', '.join(stamped)}"
            raise ValueError(msg)

        known = {one.id for one in self.conversations}
        if len(known) != len(self.conversations):
            msg = "export contains duplicate conversation ids"
            raise ValueError(msg)

        dangling = sorted(
            {turn.conversation_id for turn in self.turns if turn.conversation_id not in known}
        )
        if dangling:
            msg = f"export has turns whose conversation is missing: {', '.join(dangling)}"
            raise ValueError(msg)

        positions = {(turn.conversation_id, turn.ordinal) for turn in self.turns}
        if len(positions) != len(self.turns):
            msg = "export contains two turns at one position in a conversation"
            raise ValueError(msg)

        episodes = {turn.episode_id for turn in self.turns}
        if len(episodes) != len(self.turns):
            msg = "export contains duplicate episode ids"
            raise ValueError(msg)

        bindings = [turn.parked for turn in self.turns if turn.parked is not None]
        if len(set(bindings)) != len(bindings):
            msg = "export contains two turns claiming one parked binding"
            raise ValueError(msg)

        return self


# --- severity scales: ordered by declaration, not by value (ADR-0016 §2) -----
# `StrEnum` members *are* strings, so an un-overridden scale compares
# lexicographically. `PermissionOutcome`, far below, is the fourth member of
# this family and is one for exactly that reason.


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


# --- text that renders, and text that encodes (ADR-0018 §1) ------------------
# The shared predicates behind every "must contain visible text" validator in
# this module — a tool's id and description, a ruling's reason, a step's and a
# tool's failure message — plus the UTF-8 test the durable fields reuse.


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


type VisibleIdentifier = Annotated[EncodableText, AfterValidator(_visible_identifier)]
"""An identifier that renders as something — for ids a user is shown.

Layered on :data:`EncodableText` rather than on :data:`str`, because visible and
encodable are independent: ``_has_visible_text`` sees the letters in
``"smtp_\\ud800"`` and passes it.
"""


# --- tools: what a call costs, and what it may touch (ADR-0016 §4) -----------
# Cost is structured so a spend policy can tell *free* from *unknown* and fail
# closed on the second. `TierReach` orders `DataTier` by sensitivity, so two
# registries serialise the same declaration identically.


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
    currency: EncodableText | None = Field(
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


# --- tools: the declaration a permission decision rules on (ADR-0016 §1) -----
# States facts and draws no conclusions — `permissions` does that (ADR-0016
# §3). Every field a decision depends on is required, because a default is a
# claim, and the natural default for a reach tuple is a false one.


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
    description: EncodableText = Field(
        description="What the tool does; shown to the model and the user."
    )
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
        prompted the issue, and that is the same clause :func:`_freeze_json`
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


# --- permissions: what a policy may rule (ADR-0021 §2) -----------------------


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


# --- durability: a recorded decision must reload (ADR-0021 §4) ---------------
# The check this section used to carry now sits on `Identifier` itself; the name
# survives because it is what the fields ADR-0044 spells are annotated with.


type DurableIdentifier = Identifier
"""An :data:`Identifier` that survives serialisation — for fields a record keeps.

ADR-0021 §4 requires a recorded decision to reload, because a decision that could
not be would make the embedded definition worthless across exactly the restart
issue #54 is about. This type used to carry its own encodability validator,
layered here rather than folded into :data:`Identifier` because tightening a type
``planning`` shares was a cross-lane change a permissions lane would not make.
Issue #565 made that change from `core`, so :data:`Identifier` now refuses text
with no UTF-8 encoding and the separate validator was **provably unreachable** —
it ran on an already-validated :data:`Identifier`, and stripping cannot turn
encodable text unencodable. It is gone rather than left as a dead branch.

**The name is kept, and the guarantee is unchanged or stronger.** ADR-0044 §1
annotates :attr:`PermissionDecision.execution_id` and :attr:`~.step_id` with this
spelling, and it still says at the field which fields ADR-0021 §4 singles out.
Every value this type accepted before, it accepts now; every value it refused, it
still refuses.
"""


# --- the binding: detachment, and the canonical digest (ADR-0021 §1) ---------
# What makes "by value" true rather than nominal. `_canonical_json` is shared
# by the validator and by the digest, so "accepted" and "digestible" are one
# predicate by construction rather than two that can disagree.


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

    The encoding itself is :func:`_canonical_bytes`; this is the thaw that gets a
    validated payload into a shape ``json.dumps`` accepts. Delegating rather than
    repeating the ``dumps`` call is what keeps ADR-0078 §7's fingerprint hashing
    the *same* form this one does — two spellings of "canonical" is precisely the
    hazard that section is written about.
    """
    return _canonical_bytes(_thaw_json(parameters))


# --- permissions: the request, the ruling, their binding (ADR-0021) ----------
# Three types rather than one (§3): a policy authors only the ruling, so it has
# no field with which to name a tool it was not handed. `authorises` lives in
# `core` because it compares; it does not decide (ADR-0016 §2).


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
    parameters: FrozenJsonMapping = Field(
        default=_EMPTY_PARAMS,
        description="The arguments the call proposes; bound by digest, never stored.",
    )
    step_id: DurableIdentifier | None = Field(
        default=None, description="The plan step this action belongs to, if any."
    )
    execution_id: DurableIdentifier | None = Field(
        default=None, description="The execution this action belongs to, if any."
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
        the two are wired rather than a claim. :data:`FrozenJsonMapping`
        validates the payload by running the real JSON encoding in
        :func:`_freeze_json`, and this hashes :func:`_canonical_json`; both pin
        ADR-0021 §1's ``ensure_ascii=False`` UTF-8 form and differ only in the
        key ordering a digest needs, which cannot change whether a value
        encodes — so "accepted" and "digestible" cannot come apart. The ADR
        justified
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
    reason: EncodableText = Field(
        description="Why, in text shown to the user at the moment they decide."
    )
    authorised_by: DurableIdentifier | None = Field(
        default=None, description="The recorded user decision this ALLOW rests on, if any."
    )

    @field_validator("reason")
    @classmethod
    def _reason_is_present(cls, value: str) -> str:
        r"""Reject a reason with nothing visible in it, returning it stripped.

        The same ``_has_visible_text`` test ADR-0018 §1 applies to a tool's
        description, and for the same reason: this is shown to the user at the
        moment they are deciding, and a reason that renders as nothing leaves
        the prompt with nothing to say.

        Encodability is no longer checked here. It used to be, because visible
        and encodable are independent — ``_has_visible_text`` sees the letters in
        ``"approve \ud800"`` — but the field's annotation is now
        :data:`EncodableText` (issue #565), which runs first, so the clause was
        unreachable: stripping cannot turn encodable text unencodable.
        """
        stripped = value.strip()
        if not _has_visible_text(stripped):
            msg = "ruling reason must contain visible text"
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
    execution_id: DurableIdentifier | None = Field(
        default=None,
        description=(
            "The execution this decision belongs to, if any (ADR-0044 §1). "
            "Transcribed from the request by :meth:`from_request`, never asserted "
            "by a caller, so a decision cannot name an execution the policy did "
            "not see. ``None`` for a direct ruling outside a plan execution, "
            "exactly as ``step_id`` is."
        ),
    )
    resolves: DurableIdentifier | None = Field(
        default=None, description="The CONFIRM decision this one answers, if any."
    )
    expires_at: UtcInstant | None = Field(
        default=None,
        description=(
            "The instant past which this CONFIRM is no longer answerable, fixed "
            "when the question was asked (ADR-0059 §1). None for a decision with no "
            "lifetime — every non-CONFIRM decision, and a CONFIRM parked by a "
            "deployment that set no confirmation lifetime."
        ),
    )

    @classmethod
    def from_request(  # noqa: PLR0913 — the ADR-0059 §1 signature: recorder-supplied id, decided_at, resolves, expires_at
        cls,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        id: Identifier,  # noqa: A002 — names the field it fills; the ADR fixes the signature
        decided_at: datetime,
        resolves: Identifier | None = None,
        expires_at: datetime | None = None,
    ) -> PermissionDecision:
        """Bind a ruling to the request it was made about.

        **The only construction path a caller should use**, and it exists so the
        binding is *transcribed* rather than asserted. Every field describing
        what was ruled on — ``tool``, ``parameters_digest``, ``step_id`` and
        ``execution_id`` (ADR-0044 §1) — is copied from the request by ``core``,
        so a decision naming a different tool, or a different execution, than the
        one the policy saw cannot be produced by following the contract.

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
            expires_at: The instant past which a ``CONFIRM`` stops being
                answerable, fixed here at ask time (ADR-0059 §1). Supplied by the
                *recorder* like ``decided_at`` and ``resolves``, not transcribed
                from the request, because the deadline is the recorder's concern
                (its deployment lifetime), not a fact the policy authored. The
                recorder derives it — ``decided_at + confirmation_ttl`` under
                bounded arithmetic, resolving an unrepresentable sum to ``None``
                — before calling this; no deadline is computed here. ``None`` for
                a decision with no lifetime. Permitted only on a ``CONFIRM`` and
                only strictly after ``decided_at`` (both checked at construction).

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
            execution_id=request.execution_id,
            resolves=resolves,
            expires_at=expires_at,
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

        **``execution_id`` is the fourth conjunct, and it is load-bearing rather
        than symmetry** (ADR-0044 §1). This is the check the executor runs before
        it claims a step, so it is where a decision is bound to *what it may run*.
        Without it, a decision resolved (or auto-granted) for execution A — same
        tool, same digest, same step id as B's — would answer ``True`` for a
        request naming execution B, and an executor handed B's state and that
        decision would run B under A's approval, never resolving B's own parked
        question. That is the cross-execution substitutability #253 closes, at the
        seam that runs the tool rather than the one that records a resolution. It
        still meets ADR-0016 §2's test for living on the type — computable from
        the two values alone, independent of policy, config, context and clock —
        because an execution id is a value on both records, not a decision.
        """
        return (
            self.ruling.outcome is PermissionOutcome.ALLOW
            and request.tool == self.tool
            and request.parameters_digest == self.parameters_digest
            and request.step_id == self.step_id
            and request.execution_id == self.execution_id
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

    @model_validator(mode="after")
    def _a_lifetime_belongs_only_to_an_open_question(self) -> PermissionDecision:
        """Permit ``expires_at`` only on a ``CONFIRM``, and only after ``decided_at`` (ADR-0059 §1).

        A lifetime is a property of an *open question*: a resolving ``ALLOW`` or
        ``DENY``, or a direct grant, carries none — the same "only the coherent
        outcome may carry this" shape :meth:`PermissionRuling._only_an_allow_cites_an_authorisation`
        uses for ``authorised_by``.

        And a deadline at or before the ask instant would expire the question the
        moment it is recorded, so ``expires_at`` must fall *strictly after*
        ``decided_at`` — the same shape as ``confirmation_ttl``'s strictly-positive
        check. Both comparands are :data:`UtcInstant`, already normalised to UTC,
        so the comparison is by instant.

        ``None`` — no lifetime — is always permitted; there is deliberately no
        answer-time recompute, which is what keeps ``None`` unambiguous.
        """
        if self.expires_at is None:
            return self
        if self.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = f"a {self.ruling.outcome} decision carries no lifetime, got {self.expires_at!r}"
            raise ValueError(msg)
        if self.expires_at <= self.decided_at:
            msg = (
                f"expires_at must fall strictly after decided_at, got "
                f"expires_at={self.expires_at!r}, decided_at={self.decided_at!r}"
            )
            raise ValueError(msg)
        return self


# --- the invocation seam: result, failure, authorised call (ADR-0029) --------
# Failure is *returned* as data, never raised, because `INDETERMINATE` cannot
# be an exception. An unauthorised `ToolCall` is unconstructable.


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
    message: EncodableText = Field(description="Operator-facing explanation; Tier 2 only.")

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


# --- the promoted engine surface (ADR-0084 §4, ADR-0085) ---------------------
# The twenty-four types :class:`~ai_assistant.core.protocols.AssistantEngine`'s
# fifteen methods name, and the complete transitive closure of what their fields
# reach (ADR-0085 §5). They lived in `orchestration` while one concrete engine
# and one class of consumer was the whole story (ADR-0042 §1); ADR-0084 §5 rules
# that a client satisfying the same surface over a transport *is* the second
# implementation ADR-0042's own revisit clause named, so the surface is a
# Protocol and its types are `core`'s.
#
# **The closure is why this block is large.** Promote a type while something its
# fields reach stays in `orchestration` and `core` imports `orchestration`, which
# golden rule 2 forbids and `lint-imports` fails. The walk follows *declared
# field types*, stops at anything already here, and never follows a method — which
# is what makes it terminate, and what keeps the projection helpers behind
# (ADR-0085 §6a: the promoted models carry their fields, not their constructors).
#
# Every model below is frozen under ADR-0068 §1, every collection is a tuple, and
# every string is :data:`EncodableText` (ADR-0085 §4c) — the last held
# mechanically by ``tests/core/test_text_encodability_coverage.py`` rather than by
# anyone remembering.


#: The page size every enumerating method on the engine surface returns when it
#: is called without ``limit`` (ADR-0085 §3a). One public constant rather than the
#: three private ones that carried the figure in two `orchestration` modules, so
#: the Protocol's stated defaults have a name to refer to. ADR-0073 §2's bounded
#: default, matching ``AuditTrail.recent``.
#:
#: **The default is normative, not decorative.** A default written in a
#: ``Protocol`` method signature binds nobody — each implementation writes its own
#: — so a client defaulting to 100 against an engine defaulting to 50 would return
#: a different page for the same call. ADR-0085 §3a therefore makes it a contract
#: clause: an implementation called without ``limit`` behaves as though this had
#: been passed.
DEFAULT_PAGE_SIZE: Final[int] = 50


class ContinuationToken(BaseModel):
    """An opaque handle to a parked step (ADR-0042 §4).

    The adapter stores this and relays it back on ``AssistantEngine.resume``. It
    **must not** interpret, construct, or re-derive its contents: an adapter that
    branched on the token to decide allow/deny would be authoring a permission
    outcome in `interfaces/`, exactly what ADR-0042 §4 forbids. The ``handle`` is
    deliberately meaningless outside the engine instance that minted it — it names
    an entry in that instance's private table, nothing more.

    **Lifetime is process-scoped.** The table lives in the engine object, so a
    handle does not survive a restart. A token presented to an engine that cannot
    resolve it yields
    :class:`~ai_assistant.core.errors.UnknownContinuationError` and never a denial
    (ADR-0084 §7); recovering an answerable confirmation across a restart is
    ``pending_confirmations`` (ADR-0052 §1).

    Attributes:
        handle: The opaque handle itself. :data:`Identifier` rather than a bare
            ``str`` because a blank handle satisfies "a token is present" while
            naming nothing, which is the failure that type exists to refuse.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: Identifier = Field(description="The engine-private handle, opaque to every caller.")


class Confirmation(BaseModel):
    """What a person needs to judge a parked action (ADR-0042 §4).

    The engine assembles this because the adapter may not read the audit trail or
    a :class:`PermissionDecision` to recover it (ADR-0042 §6). The values are
    carried **as data, not pre-formatted**: "safe" is target-specific — a parameter
    value holding an ANSI escape or Rich markup is valid data a terminal would
    interpret as a control sequence, but an HTTP front end encodes differently — so
    escaping is each adapter's own job on render.

    Attributes:
        tool_id: The selected tool's id, human-readable and shown to the user.
        tool_description: What the tool does, from the declaration ruled on.
        parameters: The arguments it would run with, as structured data.
        reason: The recorded ``CONFIRM`` ruling's own ``reason`` — the policy's
            explanation of *why* confirmation is required (an off-device
            disclosure, an unknown cost). Not optional:
            :attr:`PermissionRuling.reason` is "text shown to the user at the
            moment they decide", so a prompt omitting it would drop what the user
            most needs.
        token: The opaque continuation to relay back on ``resume``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: Identifier = Field(description="The selected tool's id, shown to the user.")
    tool_description: EncodableText = Field(
        description="What the tool does, from the declaration that was ruled on."
    )
    parameters: FrozenJsonMapping = Field(
        description="The arguments the tool would run with, as structured data."
    )
    reason: EncodableText = Field(
        description="The policy's stated reason confirmation is required."
    )
    token: ContinuationToken = Field(description="The opaque continuation to relay back.")


class Disposition(StrEnum):
    """What became of one plan step at the runner stage (ADR-0037 §1, §4, §5).

    Five members, and the two that commit nothing are as much a result as the
    three that do: a step the stage declines to act on is a fact its caller has to
    be told, not an error.

    **Relocating an enum is not redefining it** (ADR-0084 §4). It keeps its five
    members and everything ADR-0037 ratified about them, including §8's refusal of
    a ``FAILED`` member, and the ``StrEnum`` base is unchanged so every existing
    value string is byte-identical on the wire.
    """

    EXECUTED = "executed"
    """The call was authorised and handed to the executor; ``state`` carries the
    outcome the executor committed."""

    DENIED = "denied"
    """The policy refused. The step is ``SKIPPED``/``APPROVAL_DENIED``, naming
    the recorded decision."""

    AWAITING_CONFIRMATION = "awaiting_confirmation"
    """The policy wants a human answer. The step is durably
    ``AWAITING_APPROVAL``; ``AssistantEngine.resume`` continues it."""

    NO_CAPABLE_TOOL = "no_capable_tool"
    """Nothing advertises the step's capability. The step is
    ``SKIPPED``/``NO_CAPABLE_TOOL`` (ADR-0014 §4)."""

    AMBIGUOUS_CAPABILITY = "ambiguous_capability"
    """Several tools advertise it and no rule chooses between them (ADR-0037 §1,
    #241). Nothing is committed and the step stays ``PENDING``."""


class StepOutcome(BaseModel):
    """What became of the one step a turn drove (ADR-0042 §3, §4; ADR-0084 §8).

    **The disposition is the gate's verdict; the named step's ``status`` and
    ``failure`` are the outcome.** A client that renders success from
    :attr:`disposition` alone is wrong — ``EXECUTED`` says the permission gate
    let the call through and the executor committed *something*, not that the
    something succeeded. :attr:`step_id` is what turns "read ``state`` too" from
    advice into an addressable operation::

        next(s for s in outcome.state.steps if s.step_id == outcome.step_id)

    That rule is a contract clause on the Protocol rather than commentary here,
    because #531's defect was an adapter reading the disposition and discarding
    the state, and every future spoke will have the same two fields in front of
    it.

    Attributes:
        disposition: Which of the five outcomes the step reached — the gate's
            verdict, and not the step's own result.
        state: The durable execution state after the last transition committed.
        step_id: The plan step this pass drove. Required and never ``None``: a
            turn whose plan had no step returns ``TurnOutcome(step=None)`` and
            constructs no :class:`StepOutcome` at all, so an optional field would
            be an optionality nothing can produce and every client would carry a
            ``None`` branch it can never reach. It is the key that addresses
            :attr:`ExecutionState.steps`, whose elements carry
            :attr:`StepExecution.step_id`, so it is the same
            :data:`Identifier` type a client compares it against.
        tool_id: The tool selected, or ``None`` where none was. **Not an
            alternative to** :attr:`step_id`: two steps may bind the same tool, so
            a tool id cannot identify a step (ADR-0084 §8).
        confirmation: Present **iff** :attr:`disposition` is
            :attr:`Disposition.AWAITING_CONFIRMATION` — the content and token the
            adapter renders and relays.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Disposition = Field(description="Which of the five outcomes the step reached.")
    state: ExecutionState = Field(
        description="Durable execution state after the last transition committed."
    )
    step_id: Identifier = Field(description="The plan step this pass drove.")
    tool_id: Identifier | None = Field(
        default=None, description="The tool selected, or ``None`` where none was."
    )
    confirmation: Confirmation | None = Field(
        default=None,
        description="Present iff the disposition is AWAITING_CONFIRMATION.",
    )

    @model_validator(mode="after")
    def _confirmation_matches_disposition(self) -> StepOutcome:
        """A parked step carries its confirmation, and nothing else does (ADR-0085 §4b).

        **This is the invariant a wire client cannot work around.** ADR-0042 §4
        obliges a parked step's result to carry the confirmation content and the
        opaque token the adapter renders and relays; a nullable field with no
        invariant permits an ``AWAITING_CONFIRMATION`` outcome carrying neither,
        and a client handed one has nothing to resume with and no contract
        violation to point at. Stated in both directions, because a confirmation
        on a disposition that did not park is a prompt for an action nobody is
        waiting on.
        """
        parked = self.disposition is Disposition.AWAITING_CONFIRMATION
        if parked and self.confirmation is None:
            msg = "an AWAITING_CONFIRMATION outcome must carry the confirmation to resume with"
            raise ValueError(msg)
        if not parked and self.confirmation is not None:
            msg = (
                f"a {self.disposition.name} outcome must not carry a confirmation: "
                "nothing is waiting on an answer"
            )
            raise ValueError(msg)
        return self


class TurnResult(BaseModel):
    """What one conversational turn produced (ADR-0022 §2).

    Attributes:
        goal: The objective this turn was planned against, minted from the
            utterance.
        context: The situational context assembled for the turn.
        memories: What the pipeline assembled for this turn, in the order the
            planner is handed it (ADR-0074 §5): the conversation's recent turns
            **first**, in order, then the records retrieved as relevant, best first
            within that group. Empty on the first turn of a fresh conversation, and
            empty for whichever half degraded.
        plan: What the planner decided to do.
        memory_degraded: Whether assembling those records failed — retrieval, or
            the conversation's history, or both — making :attr:`plan` a *generic*
            answer rather than a personal one. Reported rather than swallowed: an
            unpersonalised answer is the one failure a user of this system most
            deserves to be told about.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: Goal = Field(description="The objective this turn was planned against.")
    context: CurrentContext = Field(description="The situational context assembled for the turn.")
    memories: tuple[MemoryRecord, ...] = Field(
        description="History first, then relevance — the order the planner is handed them in."
    )
    plan: ActionPlan = Field(description="What the planner decided to do.")
    memory_degraded: bool = Field(
        default=False, description="Whether assembling those records failed."
    )


class TurnOutcome(BaseModel):
    """One unit of what a turn call produced (ADR-0042 §3).

    Attributes:
        turn: The turn's goal, context, retrieved memories, plan, and — obliged to
            be surfaced, not swallowed — whether retrieval degraded. ``None`` on a
            resume driven from a **recovered** park (ADR-0052 §3): a confirmation
            reconstructed from durable state after a restart has no live turn —
            context and retrieved memories are ephemeral and were never persisted —
            so a fabricated :class:`TurnResult` would misrepresent what the turn
            saw. The :attr:`step` — the resolution — is what a resume is for and is
            always present.
        step: The disposition of the step the engine drove, or ``None`` when the
            plan had no step to drive. On a resumption this is the resolved step.
        conversation_id: The conversation this turn ran under (ADR-0074 §2), which
            a client keeps and presents to continue. ``None`` only on a resumption
            whose parked binding no longer resolves to a turn — a park predating
            capture, or one whose conversation the user deleted — which ADR-0074 §3
            ratifies as "not captured at all, and no conversation invented".
        capture_degraded: Whether the exchange went **unrecorded** (ADR-0074 §9
            item 6). The answer is still the answer: capture failure degrades a
            turn rather than failing it, because failing would throw away an answer
            the user already has because the record of it could not be written. But
            it is reported beside :attr:`TurnResult.memory_degraded` and not
            swallowed, because a user whose turns are silently not being recorded
            will not find out until they try to continue.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn: TurnResult | None = Field(
        description="What the turn produced, or ``None`` on a recovered resume."
    )
    step: StepOutcome | None = Field(
        default=None, description="The step the engine drove, or ``None`` where there was none."
    )
    conversation_id: Identifier | None = Field(
        default=None, description="The conversation this turn ran under."
    )
    capture_degraded: bool = Field(
        default=False, description="Whether the exchange went unrecorded."
    )


class LearnDecision(StrEnum):
    """How memory folded one piece of feedback — the surface's echo of a ruling.

    One member per :class:`MemoryDecisionKind`, named for the effect on memory
    rather than the relation the policy names, so a client can render what became
    of the feedback without holding the policy's own vocabulary.
    """

    STORED = "stored"
    """A new memory was written (``ACCEPT``)."""

    REJECTED = "rejected"
    """The proposal was refused; nothing was written (``REJECT``)."""

    REINFORCED = "reinforced"
    """An existing memory was strengthened by folding the proposal into it
    (``REINFORCE``)."""

    SUPERSEDED = "superseded"
    """A prior belief was retired and the correction written in its place
    (``SUPERSEDE``)."""

    DEFERRED = "deferred"
    """The policy wants a human answer before acting; nothing was written yet
    (``ASK_USER``)."""

    STORED_TEMPORARILY = "stored_temporarily"
    """A memory was written with a retention window (``STORE_TEMPORARY``)."""


class QueueOutcome(StrEnum):
    """What became of the question a deferred ruling raised (ADR-0078 §7, §10 item 9).

    The surface's echo of :class:`DeferralAdmissionOutcome`, plus the one arm
    ADR-0078 deliberately does **not** close. A closed set with a name because the
    surface must say a *different sentence* for each — a single "not stored, go
    answer it" line covering all four would tell a user to answer a question that
    was never queued.
    """

    QUEUED = "queued"
    """The question was parked, and ``question_id`` names it."""

    ALREADY_ASKED = "already_asked"
    """An existing question the key still speaks for stands in the way, and
    ``question_id`` and ``question_state`` say **which and in what state** — a
    declined one to forget, an interrupted answer to dispose of, or one still
    waiting (ADR-0078 §7)."""

    QUEUE_FULL = "queue_full"
    """The answerable queue was at its cap, so nothing was queued and there is no
    question to read. The refusal is **reported, not swallowed**: the cap refuses
    the *new* question rather than evicting an old one, which is safe only because
    the producer still holds what it proposed and can re-propose."""

    NOT_QUEUABLE = "not_queuable"
    """Secret-tier data, which is never queued at all (ADR-0078 §1). ADR-0004 §3
    puts Tier 0 content in the OS keyring and forbids it a committed file, and a
    durable queue is a file — so today's deferral is precisely what keeps such
    content out of storage."""


class QuestionState(StrEnum):
    """Where a deferred question stands, as a surface says it (ADR-0078 §8).

    The surface's echo of :class:`DeferralState`, one member per state, named for
    what the user can *do* rather than for the row's internal label.
    """

    OPEN = "open"
    """Answerable: nobody has begun an answer (``PENDING``)."""

    INTERRUPTED = "interrupted"
    """An answer was begun and its outcome is not recorded (``APPLYING``).

    Not "failed" and not "retryable": the system does **not** know whether the
    memory write landed, which is the actual epistemic situation (ADR-0078 §9).
    """

    DECLINED = "declined"
    """The user said no, and the record is retained so they are not re-asked."""

    APPLIED = "applied"
    """The answer was applied and a record is live (``ACCEPTED``)."""

    STALE = "stale"
    """The answer arrived and the belief it was about no longer applied."""

    REDEFERRED = "redeferred"
    """The answer was used and raised a further question the record names."""


class QueuedQuestion(BaseModel):
    """Where a deferred proposal's question went (ADR-0078 §7, §8 reach 1).

    Carried on :class:`IngestSummary` so ``learn`` can point the user at the
    question in the moment they submitted the correction.

    Attributes:
        outcome: Which of the four things happened.
        question_id: The question parked, or the existing one standing in the way.
            ``None`` for ``QUEUE_FULL`` and ``NOT_QUEUABLE``, where there is no
            question to name.
        question_state: The state of the question :attr:`question_id` names, for
            the same reason :class:`SuccessorLink` carries one: "you declined this"
            and "an answer to this may be committing right now" are different
            sentences, and naming a question without its state would render one as
            the other.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: QueueOutcome = Field(description="Which of the four things happened.")
    question_id: Identifier | None = Field(
        default=None, description="The question parked, or the one standing in the way."
    )
    question_state: QuestionState | None = Field(
        default=None, description="The state of the question ``question_id`` names."
    )

    @model_validator(mode="after")
    def _unqueued_names_no_question(self) -> QueuedQuestion:
        """An outcome that queued nothing names nothing (ADR-0078 §7, ADR-0085 §4b).

        **Stated in one direction only, deliberately.** The converse — that a
        ``QUEUED`` or ``ALREADY_ASKED`` outcome always names a question — is
        *nearly* true and is not asserted, because the projection keeps a defensive
        branch for an admission whose deferral is absent, which
        :class:`DeferralAdmission`'s own validator is supposed to make unreachable.
        Asserting an invariant that a defensive branch can violate would turn a
        store-conformance fault into an unconstructable DTO.
        """
        if self.outcome in (QueueOutcome.QUEUE_FULL, QueueOutcome.NOT_QUEUABLE) and (
            self.question_id is not None or self.question_state is not None
        ):
            msg = (
                f"a {self.outcome.name} outcome queued nothing, so it names no question: "
                "question_id and question_state must both be None"
            )
            raise ValueError(msg)
        return self


class IngestSummary(BaseModel):
    """What became of one proposal folded from a piece of feedback.

    Attributes:
        decision: How memory folded the proposal.
        record_id: The id of the record left live by the write, or ``None`` when
            nothing was stored (a rejection, or a deferral). Carried as opaque data
            an adapter may echo, never interpret.
        reason: The policy's own human-readable justification for the ruling,
            surfaced for transparency.
        queued: Where the question a ``DEFERRED`` ruling raised went, and ``None``
            on every other ruling. Present on **every** deferral, including the
            secret-tier one nothing queues, because the distinguishing fact has to
            reach the adapter for it to say anything honest (ADR-0078 §10 item 9).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: LearnDecision = Field(description="How memory folded the proposal.")
    record_id: Identifier | None = Field(
        description="The record left live by the write, or ``None`` where nothing was stored."
    )
    reason: EncodableText = Field(description="The policy's own justification for the ruling.")
    queued: QueuedQuestion | None = Field(
        default=None, description="Where a deferred ruling's question went."
    )

    @model_validator(mode="after")
    def _queued_iff_deferred(self) -> IngestSummary:
        """A queued question accompanies a deferral and nothing else (ADR-0085 §4b).

        ADR-0078 §10 item 9 obliges every deferral to say where its question went,
        including the secret-tier one nothing queues. A ruling that wrote or
        refused raised no question at all, so carrying one would name a question
        the user cannot act on.
        """
        deferred = self.decision is LearnDecision.DEFERRED
        if deferred and self.queued is None:
            msg = "a DEFERRED ruling must say where its question went"
            raise ValueError(msg)
        if not deferred and self.queued is not None:
            msg = f"a {self.decision.name} ruling raised no question, so it queues none"
            raise ValueError(msg)
        return self

    @property
    def stored(self) -> bool:
        """Whether the write left a record live in memory."""
        return self.record_id is not None


class LearnOutcome(BaseModel):
    """What one piece of feedback did to memory (ADR-0042 §1, §3).

    Attributes:
        results: One :class:`IngestSummary` per proposal the feedback produced, in
            the order they were applied — empty when the feedback proposed no
            update at all.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    results: tuple[IngestSummary, ...] = Field(
        description="One summary per proposal, in the order they were applied."
    )

    @property
    def stored(self) -> int:
        """How many proposals left a record live in memory."""
        return sum(1 for summary in self.results if summary.stored)


class Evidence(BaseModel):
    """One citation behind a belief, as a person reads it (ADR-0077 §6).

    **It carries no id, deliberately.** ADR-0073 §4's floor is that "a citation the
    surface cannot render as evidence is never rendered *as* evidence — not as a
    reassuring id, not silently dropped", and an adapter that never receives the id
    cannot render one as though it were the warrant.

    Attributes:
        content: The cited record's own canonical text, or ``None`` where the
            citation no longer resolves — a **tombstone**. The tombstone says an
            evidence item stood here and is gone, and deliberately does not say
            what it was, nor whether it was *deleted* or merely *expired*: the read
            cannot tell those apart, and the user's question — "is there still
            something behind this?" — is answered by absence either way.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: EncodableText | None = Field(
        default=None, description="The cited record's text, or ``None`` for a tombstone."
    )

    @property
    def lost(self) -> bool:
        """Whether this citation no longer resolves."""
        return self.content is None


class BeliefSummary(BaseModel):
    """One live belief on the **listing**, which ships counts and not citations.

    ADR-0077 §6 divides the inspection surface in as many words — the listing
    "resolves *existence* and renders the count, the lost count, and the adjusted
    confidence", the single-belief view "renders the surviving citations as
    readable evidence and the lost ones as tombstones" — and this is the type that
    makes the split expressible (ADR-0085 §4a).

    **The wrong behaviour is unrepresentable here rather than merely detectable.**
    :class:`Evidence` carries ``content: str | None`` and a lost citation is one
    whose content is ``None``, so a listing that derived its counts from an
    evidence tuple would have to ship every cited episode's full text on every page
    or misreport every citation as a tombstone. This type has nowhere to put a
    content, so a conforming listing cannot over-deliver — which is also what
    removes the ``beliefs * citations * content`` term from the frame arithmetic
    ADR-0085 §8f works through.

    **ADR-0073 §4's floor becomes a static guarantee rather than a convention**: a
    client holding one of these cannot render a citation as evidence, because it
    holds no citations. It holds how many there are and how many are gone, which is
    what §4 asked the listing to convey.

    Attributes:
        id: The record's id, opaque, and what ``forget`` names.
        band: The standing the belief is held with (ADR-0072 §2), projected from
            its provenance source. Never omitted, and never left to be implied by
            position.
        kind: Which of the four typed memories this is.
        content: The canonical text rendering of the belief.
        confidence: How strongly it is held, in ``[0, 1]`` — **the presented
            value**, already adjusted for lost support (ADR-0077 §6).
        last_updated: The transaction stamp — when *the assistant* last revised
            this belief (ADR-0045 §3) — which is also the enumeration's sort key.
            It is **our** clock and not a source's.
        evidence_count: How many citations stand behind it, resolved or not. A
            **field** here rather than a property, because this type carries no
            evidence to derive it from.
        lost_evidence: How many of those citations no longer resolve. A field for
            the same reason.
        valid_until: The end of the belief's validity window, where one is set;
            ``None`` where the window is open. Every listed belief is live by
            construction, so an open window carries no information and a set end
            does.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The record's id, opaque, and what ``forget`` names.")
    band: BeliefBand = Field(description="The standing the belief is held with.")
    kind: MemoryKind = Field(description="Which of the four typed memories this is.")
    content: EncodableText = Field(description="The canonical text rendering of the belief.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="The presented confidence, adjusted for lost support."
    )
    last_updated: UtcInstant = Field(
        description="When the assistant last revised this belief (ADR-0045 §3)."
    )
    evidence_count: int = Field(
        default=0, ge=0, description="How many citations stand behind it, resolved or not."
    )
    lost_evidence: int = Field(
        default=0, ge=0, description="How many of those citations no longer resolve."
    )
    valid_until: UtcInstant | None = Field(
        default=None, description="The end of the belief's validity window, where one is set."
    )

    @model_validator(mode="after")
    def _lost_within_cited(self) -> BeliefSummary:
        """More citations cannot be gone than were ever made (ADR-0085 §4b).

        **The price of counts-as-fields.** On :class:`Belief` the two counts cannot
        disagree with the evidence because they are computed from it; moving them
        to fields buys the listing its shape at the cost of the one constraint the
        model must now assert for itself.
        """
        if self.lost_evidence > self.evidence_count:
            msg = (
                f"lost_evidence ({self.lost_evidence}) exceeds evidence_count "
                f"({self.evidence_count}): more citations cannot be gone than were made"
            )
            raise ValueError(msg)
        return self

    @property
    def unsupported(self) -> bool:
        """Whether every citation behind it has gone (ADR-0077 §6).

        A belief in this state is **held, marked and answerable — not
        auto-retired**: retiring it would be the cascade under a softer name, and
        it may be perfectly true.

        ``False`` for a belief that cites nothing at all: an assertion is not
        unsupported, it is supported by the user's own word (ADR-0038 §1a). Derived
        rather than stored, because the two count fields already determine it — a
        third field would be a second source of truth for a fact a client can
        compute exactly, and two implementations could then measure the same call
        at two sizes.
        """
        return self.evidence_count > 0 and self.lost_evidence == self.evidence_count


class Belief(BaseModel):
    """One live belief on the **single-belief view**, with its citations resolved.

    The other half of ADR-0077 §6's split (:class:`BeliefSummary` is the listing).
    Deliberately **not** a raw :class:`MemoryRecord`: :func:`band_of` is applied
    once, by the engine, because an adapter doing it would put ADR-0072 §1's
    projection into `interfaces/`. It also flattens the four-member discriminated
    union an adapter would otherwise branch over, and drops ``score``, which is
    meaningless on a path where nothing was ranked.

    **The evidence citations are carried as resolved values and never as ids**,
    which is ADR-0073 §4's floor made structural.

    Attributes:
        id: The record's id, opaque, and what ``forget`` names.
        band: The standing the belief is held with (ADR-0072 §2).
        kind: Which of the four typed memories this is.
        content: The canonical text rendering of the belief.
        confidence: How strongly it is held, in ``[0, 1]`` — **the presented
            value**, already adjusted for lost support (ADR-0077 §6). The stored
            number is not carried, and that is the point: a DTO offering both would
            let two surfaces quote different numbers for one belief.
        evidence: One entry per citation, in the order the record wrote them —
            resolved to readable content, or a tombstone where it no longer
            resolves. Empty for an assertion, whose warrant is the user's own word
            (ADR-0038 §1a) and needs no citation.
        last_updated: The transaction stamp (ADR-0045 §3), our clock and not a
            source's.
        valid_until: The end of the belief's validity window, where one is set.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The record's id, opaque, and what ``forget`` names.")
    band: BeliefBand = Field(description="The standing the belief is held with.")
    kind: MemoryKind = Field(description="Which of the four typed memories this is.")
    content: EncodableText = Field(description="The canonical text rendering of the belief.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="The presented confidence, adjusted for lost support."
    )
    last_updated: UtcInstant = Field(
        description="When the assistant last revised this belief (ADR-0045 §3)."
    )
    evidence: tuple[Evidence, ...] = Field(
        default=(), description="One entry per citation, resolved or a tombstone."
    )
    valid_until: UtcInstant | None = Field(
        default=None, description="The end of the belief's validity window, where one is set."
    )

    @property
    def evidence_count(self) -> int:
        """How many citations stand behind it, resolved or not."""
        return len(self.evidence)

    @property
    def lost_evidence(self) -> int:
        """How many of its citations no longer resolve."""
        return sum(1 for item in self.evidence if item.lost)

    @property
    def unsupported(self) -> bool:
        """Whether every citation behind it has gone (ADR-0077 §6).

        One definition everywhere, and it reads identically on
        :class:`BeliefSummary`: ``evidence_count > 0 and lost_evidence ==
        evidence_count``. A belief citing nothing at all is not "unsupported", it
        is supported by the user's own word (ADR-0038 §1a).
        """
        return self.evidence_count > 0 and self.lost_evidence == self.evidence_count


class ConversationSummary(BaseModel):
    """One conversation, as a person choosing which to continue reads it (ADR-0074 §2).

    Attributes:
        id: The opaque id a turn call takes to continue this conversation.
            Server-minted, encoding nothing; a client holds this and nothing else.
        started_at: When the conversation record was created.
        last_active_at: When someone was last here — set at creation and refreshed
            whenever a turn begins. **This is the listing's sort key**, and never
            :attr:`last_turn_at`: ordering by "has a turn landed" would sink a
            conversation the user opened a minute ago below one they abandoned last
            week.
        last_turn_at: When a turn was last *recorded*, or ``None`` if none has
            been. A different fact from activity, and the one that tells an empty
            conversation from one whose first turn landed instantly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The opaque id a client presents to continue.")
    started_at: UtcInstant = Field(description="When the conversation record was created.")
    last_active_at: UtcInstant = Field(description="When someone was last here — the sort key.")
    last_turn_at: UtcInstant | None = Field(
        default=None, description="When a turn was last recorded, or ``None`` if none has been."
    )


class ConversationDigest(BaseModel):
    """What a person is shown before consenting to destroy a conversation (ADR-0074 §8).

    ADR-0073 §5's show-then-confirm, at the unit the user thinks in: "what will be
    destroyed is shown before consent is taken, in a form a human can judge — for a
    conversation, **the count and span** rather than every turn". Printing every
    turn would be a transcript nobody can read at a prompt, and printing nothing
    would be consent to destroy something unseen.

    Attributes:
        id: The conversation's id.
        started_at: When it began.
        last_turn_at: When a turn was last recorded in it, or ``None`` if none ever
            was — the span's other end.
        recorded_turns: How many turns its index holds. It counts **recorded
            turns**, not surviving episodes: a turn whose episode expired or was
            destroyed still happened, and this is the ceremony for destroying the
            conversation rather than a report on its content.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The conversation's id.")
    started_at: UtcInstant = Field(description="When it began.")
    last_turn_at: UtcInstant | None = Field(
        description="When a turn was last recorded, or ``None`` if none ever was."
    )
    recorded_turns: int = Field(ge=0, description="How many turns its index holds.")


class Retirement(BaseModel):
    """One record a question's answer would retire (ADR-0078 §8).

    **Not decoration: this is the exact scope the answer authorises.** The content
    is resolved through the ratified ``MemoryStore.get``, which hides a closed
    window (ADR-0045 §6) — so a conflict retired since the question was asked does
    not resolve, and renders as *no longer held* rather than being omitted. The
    user should be told that the thing they would be overruling is already gone.

    Attributes:
        record_id: The conflict's id, opaque data an adapter may echo.
        content: What that record says, or ``None`` when it is no longer held.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: Identifier = Field(description="The conflict's id.")
    content: EncodableText | None = Field(
        description="What that record says, or ``None`` when it is no longer held."
    )


class SuccessorLink(BaseModel):
    """A question raised by an answer, and the state it is in (ADR-0078 §7, §9).

    The state is carried because **naming it without its state would be the failure
    §9 names**: an ``OPEN`` successor is a question the user can go and answer, a
    ``DECLINED`` one means they already declined this and must forget it to be
    asked again, and an ``INTERRUPTED`` one is another interrupted answer. Calling
    any of those "the follow-on question" would tell a user their answer raised
    something askable when it raised nothing they can act on.

    Attributes:
        id: The successor question's id.
        state: Where that question stands, and therefore what can be said about it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The successor question's id.")
    state: QuestionState = Field(description="Where that question stands.")


class Question(BaseModel):
    """A deferred memory decision, as the user is shown it (ADR-0078 §8).

    Attributes:
        id: The question's id, which ``answer`` and ``forget_question`` take.
        state: Where it stands, and therefore what the user can do about it.
        content: What accepting would have the assistant believe.
        kind: Which typed memory it would establish.
        band: The band the record **would** enter if accepted — a conditional,
            never a belief held. A pending question is not a belief of any band:
            :func:`band_of` applied to its proposal says only where it would land.
        rationale: Why the proposal was made, in its producer's words.
        reason: **Why the user is being asked** — the ``ASK_USER`` ruling's own
            non-optional ``reason``.
        retires: What accepting would retire, resolved to content.
        asked_at: When the question was admitted.
        expires_at: When it stops being answerable, or ``None`` under the user's
            deliberate "ask me forever".
        successor: The question this one's answer already raised, when it has one —
            the state a cancellation caught after a re-deferral admitted a
            successor leaves behind (ADR-0078 §9).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The question's id.")
    state: QuestionState = Field(description="Where it stands.")
    content: EncodableText = Field(description="What accepting would have the assistant believe.")
    kind: MemoryKind = Field(description="Which typed memory it would establish.")
    band: BeliefBand = Field(description="The band the record would enter if accepted.")
    rationale: EncodableText = Field(description="Why the proposal was made, in its own words.")
    reason: EncodableText = Field(description="Why the user is being asked.")
    retires: tuple[Retirement, ...] = Field(description="What accepting would retire.")
    asked_at: UtcInstant = Field(description="When the question was admitted.")
    expires_at: UtcInstant | None = Field(
        description="When it stops being answerable, or ``None`` for 'ask me forever'."
    )
    successor: SuccessorLink | None = Field(
        default=None, description="The question this one's answer already raised."
    )


class AnswerKind(StrEnum):
    """What answering a question produced (ADR-0078 §8).

    Four outcomes the ADR names — *applied*, *rejected*, *stale* and *re-deferred*
    — plus the one an answer to a question that is not open produces. Rendering a
    re-deferral as a failure would be a lie in a small place, so it is its own
    member and carries the successor.
    """

    APPLIED = "applied"
    """The correction landed; ``record_id`` names what is now live."""

    REJECTED = "rejected"
    """Nothing was written. Either the user declined, or the policy ruled
    ``REJECT`` on the re-submitted proposal (ADR-0078 §2)."""

    STALE = "stale"
    """The proposal's own validity window had closed by the answer instant, so
    accepting would have written a belief born dead (ADR-0078 §6). Distinct from a
    lapsed deadline: telling a user who answered promptly they were too slow would
    be the wrong sentence."""

    REDEFERRED = "redeferred"
    """The answer was **used** and raised a further question, because re-ingesting
    surfaced an assertion the user was never shown (ADR-0078 §5a). A completed
    answer, not a failed one."""

    NOT_OPEN = "not_open"
    """That question is not open — absent, lapsed, already being answered, or
    already answered. Nothing was written."""


class AnswerOutcome(BaseModel):
    """What one answer did (ADR-0078 §8, §9).

    Attributes:
        kind: Which of the five outcomes happened.
        question_id: The question that was answered, echoed back.
        record_id: What an applied answer left live; ``None`` otherwise.
        successor: The question a re-deferred answer raised — newly admitted, or
            the already-open one it collapsed onto — with the state that decides
            what to say about it. ``None`` when no successor could be queued.
        successor_refused: Whether a re-deferral could queue **no** follow-on
            question at all, because the queue was full and this admission had no
            exemption to spend. Reporting it as an ordinary re-deferral would claim
            a question was asked when none was.
        disposed: Whether the question was **destroyed while its answer was being
            applied**, so the bookkeeping found nothing. A true statement the
            caller reports; what it reports *about the answer* comes from the
            ingest, which it still holds, and never from the failed bookkeeping
            (ADR-0078 §9).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AnswerKind = Field(description="Which of the five outcomes happened.")
    question_id: Identifier = Field(description="The question that was answered.")
    record_id: Identifier | None = Field(
        default=None, description="What an applied answer left live."
    )
    successor: SuccessorLink | None = Field(
        default=None, description="The question a re-deferred answer raised."
    )
    successor_refused: bool = Field(
        default=False, description="Whether a re-deferral could queue no follow-on at all."
    )
    disposed: bool = Field(
        default=False, description="Whether the question was destroyed mid-apply."
    )

    @model_validator(mode="after")
    def _outcome_carries_only_its_own_fields(self) -> AnswerOutcome:
        """Each outcome carries what it produced, and nothing another one would (§4b).

        Two ratified rules, both from ADR-0078 §8: a record is left live **iff**
        the answer applied, and a successor — or the refusal to queue one — belongs
        to a re-deferral alone. Without them an ``APPLIED`` outcome could name no
        record while claiming a correction landed, and a ``REJECTED`` one could
        carry a follow-on question nobody raised.
        """
        applied = self.kind is AnswerKind.APPLIED
        if applied and self.record_id is None:
            msg = "an APPLIED answer must name the record it left live"
            raise ValueError(msg)
        if not applied and self.record_id is not None:
            msg = f"a {self.kind.name} answer wrote nothing, so it names no record"
            raise ValueError(msg)
        if self.kind is not AnswerKind.REDEFERRED and (
            self.successor is not None or self.successor_refused
        ):
            msg = (
                f"a {self.kind.name} answer raised no further question: "
                "successor and successor_refused belong to a re-deferral"
            )
            raise ValueError(msg)
        return self


class ObservedProposal(BaseModel):
    """One belief the observer proposed, and what the write path did with it.

    **It pairs the proposal with its ruling, and that pairing is the decision**
    (ADR-0077 §9.7). A :class:`MemoryIngestResult` carries a ruling and a record id
    and nothing else, and for an ``ASK_USER`` that id is ``None`` — so an entry
    built from the result alone would render a deferral as a bare ruling with
    nothing to show.

    **The citations travel with it, resolved, and not as a count**, because
    **nothing persists a deferred proposal**: there is no later belief-detail view
    through which its warrant could ever be inspected, so a count here would be the
    last word on a belief the user is being asked to act on.

    Attributes:
        content: The canonical text rendering of the belief that was proposed.
        kind: Which typed memory it is. Never ``EPISODIC``: an observer distils
            evidence, it does not manufacture it (ADR-0077 §2).
        step: The epistemic step the producer took — ``OBSERVED`` where the cited
            evidence entails the belief, ``INFERRED`` where it merely supports it
            (ADR-0072 §3). Both land in the ``DERIVED`` band, so the band carries
            no information here and the *step* is the informative half.
        confidence: How strongly the producer proposed holding it. Unadjusted,
            unlike a presented belief's. Bounded ``[0, 1]`` and **not** ``[0, 1)``,
            though a conforming producer is always strictly below 1.0: encoding
            the producer's rule as a validation constraint would convert a producer
            bug into an unreadable report, and the entry that most needs to reach a
            human — a proposal something got wrong — would fail to construct, with
            the whole :class:`ObservationReport` behind it.
        rationale: The producer's own statement of why the batch justifies it.
        decision: How memory folded it, or ``None`` when **no ruling was ever
            sought** — the write path refused it because the evidence it cited no
            longer resolves (ADR-0077 §5). ``None`` is not a sixth ruling: a
            refusal is not a decision, and fabricating one would put a ruling
            nobody made into the report.
        record_id: The id of the record left live by the write, or ``None`` when
            nothing was stored. This is the id the belief listing shows and
            ``forget`` takes, so an observed belief is immediately inspectable.
        reason: The policy's own justification for the ruling — or, where
            :attr:`decision` is ``None``, the stage's statement of why the proposal
            was dropped before any policy saw it.
        evidence: The episodes it cites, in the order the proposal wrote them, each
            resolved to readable content — or a tombstone where that citation is
            the one that stopped resolving.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: EncodableText = Field(description="The text of the belief that was proposed.")
    kind: MemoryKind = Field(description="Which typed memory it is; never EPISODIC.")
    step: MemorySource = Field(description="OBSERVED where entailed, INFERRED where supported.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="How strongly the producer proposed holding it."
    )
    rationale: EncodableText = Field(description="Why the producer says the batch justifies it.")
    decision: LearnDecision | None = Field(
        description="How memory folded it, or ``None`` where no ruling was sought."
    )
    record_id: Identifier | None = Field(
        description="The record left live by the write, or ``None``."
    )
    reason: EncodableText = Field(description="The ruling's justification, or why it was dropped.")
    evidence: tuple[Evidence, ...] = Field(
        default=(), description="The episodes it cites, resolved or tombstoned."
    )

    @property
    def stored(self) -> bool:
        """Whether the write left a record live in memory."""
        return self.record_id is not None

    @property
    def evidence_count(self) -> int:
        """How many episodes it cites."""
        return len(self.evidence)

    @property
    def inspectable(self) -> bool:
        """Whether a later read can still show this belief and its warrant.

        ``False`` for everything the write path did not leave a record for — a
        deferral, a rejection, a drop. Those have **no** later belief-detail view
        (nothing persists a deferred proposal, ADR-0077 §4), so the report is the
        only place their evidence is ever shown, and a surface renders it there or
        nowhere.
        """
        return self.record_id is not None


class ObservationReport(BaseModel):
    """What one observation pass did (ADR-0077 §9.7).

    **The counts are kept apart on purpose.** :class:`ObservationOutcome`'s two are
    exhaustive over the entries the *model* emitted, so a proposal the producer
    legitimately made and the writer then refused is a different fact: folding it
    into either would make that invariant a lie (ADR-0077 §5, §9.7). It gets a
    count of its own.

    Attributes:
        proposals: One entry per proposal the observer returned, in the producer's
            order, each paired with its ruling — or with the unresolved-evidence
            drop that replaced it. Empty is a normal outcome, not an error.
        discarded_unusable: Relayed **unchanged** from the producer: entries it
            refused for a reason of its own — unparseable, failing validation,
            citing evidence it was never handed, below its evidence floor, or
            naming a kind an observer may not propose.
        discarded_over_limit: Relayed unchanged: otherwise-usable proposals the
            producer dropped to meet its configured maximum.
        dropped_unsupported: The stage's own count of proposals the **write path**
            refused because every episode they cited had stopped resolving between
            selection and the write. An ordinary consequence of a finite retention
            horizon, never a producer fault — a fault propagates instead.
        route: The model route that read the episodes, **absent when none did**. A
            window whose turns have all lost their episodes selects an empty batch
            and the observer is not called at all, so naming a route would claim a
            read that never happened. It stays plain text rather than an
            :data:`Identifier`: it is a model route label whose shape belongs to
            `models/`, and a `core` model is not the place to start constraining
            it.
        conversation_id: The conversation whose turns were read, or ``None`` when
            the store held none to read. Carried because the operation *selects*
            when it is given no id — "the most recently active" — and a report that
            did not say which conversation was read would leave the user unable to
            tell what the model was shown.
        episodes_read: How many episodes the batch held. At most the configured
            batch size, and **short** where a turn's episode no longer resolves.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: tuple[ObservedProposal, ...] = Field(
        default=(), description="One entry per proposal, in the producer's order."
    )
    discarded_unusable: int = Field(
        default=0, ge=0, description="Entries the producer refused for a reason of its own."
    )
    discarded_over_limit: int = Field(
        default=0, ge=0, description="Usable proposals the producer dropped to meet its maximum."
    )
    dropped_unsupported: int = Field(
        default=0, ge=0, description="Proposals the write path refused for unresolved evidence."
    )
    route: EncodableText | None = Field(
        default=None, description="The model route that read the episodes, or ``None``."
    )
    conversation_id: Identifier | None = Field(
        default=None, description="The conversation whose turns were read."
    )
    episodes_read: int = Field(default=0, ge=0, description="How many episodes the batch held.")

    @property
    def stored(self) -> int:
        """How many proposals left a record live in memory."""
        return sum(1 for proposal in self.proposals if proposal.stored)

    @property
    def discarded(self) -> int:
        """How much was thrown away in total, by the producer and by the write path."""
        return self.discarded_unusable + self.discarded_over_limit + self.dropped_unsupported

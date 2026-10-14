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

import base64
import binascii
import heapq
import json
import re
import string
import unicodedata
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from hashlib import sha256
from itertools import pairwise
from math import isfinite
from threading import Lock
from typing import Annotated, Any, Final, Literal, Self, assert_never
from urllib.parse import unquote
from uuid import uuid4

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import Draft202012Validator
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    SecretStr,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import AfterValidator, BeforeValidator

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


def _rejecting_non_blank(value: str) -> str:
    """Reject a blank value, returning it **unchanged** (ADR-0096 §2).

    The rejecting half of :func:`_non_blank` without its normalising half, and the
    asymmetry is the decision rather than an oversight. A facet's ``source`` is a
    *faithful copy* of the reading's, which is :data:`EncodableText` and does not
    strip — so stripping here would make a conforming reader named ``"  calendar
    "`` produce a reading whose ``source`` keeps the spaces and a facet whose
    ``source`` loses them, and :class:`SourceReading`'s stamp-equality validator
    would then refuse a reading every other rule permits. Tightening by
    *normalising* is how two spellings of one value drift, silently, until
    something compares them.

    The general rule ADR-0096 §2 draws from it: **a faithful copy takes the type
    of the field it copies, and may tighten only in ways that reject.**

    **The message names no field**, because three unrelated ones now reach this
    validator: a facet's ``source``, a grant's, and :attr:`MemoryBase.about_person`
    (ADR-0100 §1). Pydantic reports the location it refused, so a message naming
    one of them would contradict the other two on every second failure.

    Raises:
        ValueError: If the value is blank after stripping.
    """
    if not value.strip():
        msg = "must not be blank"
        raise ValueError(msg)
    return value


type NonBlankEncodableText = Annotated[EncodableText, AfterValidator(_rejecting_non_blank)]
"""Text that is neither blank nor unwritable, and is **never normalised**.

:data:`Identifier` refuses a blank value *and* strips the one it accepts;
:data:`EncodableText` does neither. This is the third combination, and ADR-0096 §2
needs it because a value copied between two fields must compare equal to its
original: it refuses ``"   "`` while returning ``"  calendar  "`` byte-for-byte.

**It does not close #667**, which proposes one identifier contract across
:attr:`Reader.name <ai_assistant.core.protocols.Reader.name>`,
:attr:`SourceReading.source` and :attr:`Attestation.reported_by` at once. What it
does is keep a *facet* from carrying an identity that names nothing legible, on
the construction paths a conformance suite cannot reach — a fixture, a fake, or a
producer that is not a ``Reader`` at all.

**Declared here rather than beside its first consumer**, for the reason the
comment above this block gives of :data:`Identifier` and :data:`EncodableText`: it
is a pure refinement of a scalar that every section of the module may reach for,
and ADR-0100 §1 gave it a second consumer — :class:`MemoryBase`, which is declared
far ahead of :class:`ContextFacet`. A forward reference plus ``model_rebuild``
would have kept the old position at the cost of making a `core` type depend on an
import-order side effect, so the primitive moved rather than the model.
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


# --- bulk inference: the batch, and the handle the caller holds (ADR-0143) ---
# The eight public names ADR-0143 §9 fixes, declared beside :class:`Message`
# because every one of them either carries a conversation or answers one. They
# serve a **second** seam rather than a widening of :class:`ModelProvider`
# (ADR-0143 §1): a batch is submitted, polled and fetched across hours, so the
# value that names it is the caller's to keep and to write down.
#
# Nothing here reaches the promoted engine surface, and that is structural rather
# than incidental: ADR-0143 §8 gives no subsystem a ``BatchCompleter``, and §11
# leaves wiring one into `app` or the hub deferred.


class BatchRequest(BaseModel):
    """One item of a batch: a conversation awaiting a reply, under the caller's id.

    ``messages`` is a request on :meth:`ModelProvider.complete
    <ai_assistant.core.protocols.ModelProvider.complete>`'s own terms (ADR-0143
    §3) — the same **necessary** condition, read as that docstring states it and
    admitting nothing by omission. ``item_id`` is minted by the caller, is unique
    within its batch, and is what an outcome is matched back by (ADR-0143 §4); no
    implementation mints, rewrites or normalises one, which is why it is
    :data:`NonBlankEncodableText` and not :data:`Identifier` — the latter strips
    the value it accepts, and a normalisation on one side of the round trip
    quietly breaks the match.

    **Not frozen, and that is the decision rather than an omission.** ADR-0143
    §3's observation clause is discharged by ``submit`` taking a snapshot deep
    enough to cover everything the call goes on to read, never by the argument
    being immutable: ADR-0065 says in as many words that "a frozen argument is not
    a discharge on its own", and ADR-0143 §12 records that reading a batch's items
    as immune because they are frozen was this ADR's own corrected error. Freezing
    would also only have moved the hole — ``messages`` is a ``Sequence`` field, so
    pydantic holds it as a mutable ``list`` beneath a frozen model exactly as
    :class:`MemoryWrite` holds a mutable :class:`MemoryRecord`.

    **Mutable therefore means mutable-and-validated**, which is what
    ``validate_assignment`` buys: without it a caller could assign a blank
    ``item_id`` after construction and hold a model that no longer satisfies its
    own annotation, and ``submit``'s deep copy would faithfully carry the invalid
    value to the provider. Being unfrozen is a decision about *when* the value may
    change, never about whether the type's rules apply to what it changes to. It is
    not a complete guard and does not pretend to be — ``model_construct`` bypasses
    validation by design — which is why ``submit`` re-checks each snapshotted
    ``item_id`` on the near side of the acceptance window rather than trusting the
    type alone (ADR-0143 §2, §3).

    Attributes:
        item_id: The caller's own id for this item, unique within its batch and
            carried back unchanged on the item's outcome.
        messages: Conversation history, oldest first. Non-empty, not ending on a
            ``Role.ASSISTANT`` turn, and — like every history at the model seam —
            containing no ``Role.TOOL`` turn (ADR-0143 §10).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    item_id: NonBlankEncodableText = Field(
        description="The caller's id for this item, unique within its batch, never rewritten."
    )
    messages: Sequence[Message] = Field(
        description="Conversation history, oldest first, awaiting an assistant reply."
    )


class BatchHandle(BaseModel):
    """What names a submitted batch, and the account it is reachable from.

    An **address, not a capability** (ADR-0143 §2). It carries what names the
    batch — ``batch_id`` and ``issuer`` — together with the caller's own
    ``batch_key`` and the ``submitted_at`` record, neither of which an
    implementation reads back. It carries **no field a later ``poll`` or ``fetch``
    would have to agree with**, in particular no count: this is a public `core`
    model, so anyone can build one, and a handle carrying an ``item_count`` its
    author invented would put ``poll`` in an impossible position — report the
    provider's true ``settled`` and breach the bound, or agree with a number the
    caller made up. Counts live on :class:`BatchStatus` instead, read from the
    provider on every poll.

    A handle a caller assembles by hand, naming a real batch under its own
    ``issuer``, is a valid address for that batch and is answered for it. The seam
    neither authenticates handles nor pretends to; holding one confers nothing the
    caller's own credential did not already confer.

    **Validity is scoped to the ``issuer``, never to the object.** A handle
    persisted to disk and presented to a freshly constructed ``BatchCompleter`` of
    equal ``issuer`` is valid — that is what makes resumption across a process
    restart possible, and object identity would reject exactly the case the shape
    exists to support.

    Attributes:
        batch_key: The caller's own key for the batch, carried unchanged and
            **never interpreted**. It correlates a caller's durable record of an
            intended batch with the handle it got back. It is *not* an idempotency
            key: two ``submit`` calls under one key create two batches.
        batch_id: The provider's identifier for the accepted batch.
        issuer: A **non-secret** label naming the provider account or workspace the
            batch is reachable from, supplied to the implementation by the
            composition root that constructs it and never derived from the
            credential — so it survives a key rotation, which a credential
            fingerprint would not (ADR-0143 §2).
        submitted_at: When the batch was accepted, as the submitting implementation
            observed it. A record for the caller; no implementation reads it back.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_key: NonBlankEncodableText = Field(
        description="The caller's own key for the batch, carried unchanged and never interpreted."
    )
    batch_id: NonBlankEncodableText = Field(
        description="The provider's identifier for the accepted batch."
    )
    issuer: NonBlankEncodableText = Field(
        description="Non-secret label for the account the batch is reachable from."
    )
    submitted_at: UtcInstant = Field(description="When the batch was accepted (tz-aware).")


class BatchState(StrEnum):
    """Whether a batch has finished, as :class:`BatchStatus` reports it (ADR-0143 §9)."""

    PENDING = "pending"
    """Some item has not settled. ``fetch`` is not defined for a batch in this state."""

    COMPLETE = "complete"
    """Every item has settled — succeeded, failed, expired or been cancelled."""


class BatchStatus(BaseModel):
    """What one ``poll`` learnt about a batch (ADR-0143 §9).

    ``total`` is the provider's count of the batch's items, read on **every**
    poll rather than carried on the handle, and ``settled`` is how many of them
    have reached one of the four outcomes. The two are bound to ``state``:
    ``0 <= settled <= total``, and ``state`` is ``COMPLETE`` if and only if
    ``settled == total``.

    **An implementation whose provider reports no in-flight progress reports
    ``settled`` as ``0`` until the batch completes.** That satisfies the invariant
    and is not a defect — the seam asks for a count it can stand behind, not for a
    progress bar.

    ``results_expire_at`` is the **results retention**, and it is a different bound
    from the processing window: the window is per item and surfaces as the
    ``EXPIRED`` outcome of :class:`BatchOutcomeKind`, while retention is per batch
    and bounds how long a settled batch's outcomes stay fetchable. Conflating them
    is the failure ADR-0143 §6 exists to prevent, and the dangerous direction is a
    ``fetch`` that quietly short-returns after retention lapsed: 900 outcomes for a
    1,986-item batch would read as 1,086 expired items and score a run that never
    happened. So a lapsed ``fetch`` raises instead (ADR-0143 §6).

    Attributes:
        handle: The batch this status is about.
        state: Whether every item has settled.
        total: The provider's count of the batch's items, read on this poll.
        settled: How many of them have reached an outcome.
        results_expire_at: When the settled outcomes stop being fetchable, or
            ``None`` where the implementation cannot state one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: BatchHandle = Field(description="The batch this status is about.")
    state: BatchState = Field(description="Whether every item has settled.")
    total: int = Field(ge=1, description="The provider's count of the batch's items.")
    settled: int = Field(ge=0, description="How many items have reached an outcome.")
    results_expire_at: UtcInstant | None = Field(
        default=None,
        description="When the outcomes stop being fetchable; None where none can be stated.",
    )

    @model_validator(mode="after")
    def _settled_is_within_the_total_and_fixes_the_state(self) -> BatchStatus:
        """Bind ``state`` to the counts, in both directions (ADR-0143 §9).

        A status reporting ``COMPLETE`` while items are outstanding would send a
        caller to a ``fetch`` the seam refuses; one reporting ``PENDING`` on a
        fully settled batch would make the caller poll forever. Both are
        constructible without this, on every path a conformance suite cannot reach
        — a fixture, a fake, or a hand-built status — so the binding is on the type.
        """
        if self.settled > self.total:
            msg = f"settled ({self.settled}) may not exceed total ({self.total})"
            raise ValueError(msg)
        complete = self.state is BatchState.COMPLETE
        if complete != (self.settled == self.total):
            msg = (
                f"state must be COMPLETE if and only if every item has settled; got "
                f"{self.state.name} with settled={self.settled} of total={self.total}"
            )
            raise ValueError(msg)
        return self


class BatchOutcomeKind(StrEnum):
    """How one item of a batch ended — exactly one of four (ADR-0143 §4).

    The taxonomy is the seam's own, and is justified by what a caller must *do*
    differently with each: read a result, decide on a disposition, resubmit the
    item in a new batch, or stop. That it agrees with what the vendor surfaces
    report is convergence on the same four facts about a unit of work, not a
    vendor shape crossing the seam — nothing on :class:`BatchItemOutcome` carries a
    vendor status string, error code or response envelope.
    """

    SUCCEEDED = "succeeded"
    """The model answered. The outcome carries that reply as a :class:`Message`."""

    FAILED = "failed"
    """The item was attempted and did not produce an answer. The outcome carries a
    :class:`BatchItemFailure` and no message."""

    EXPIRED = "expired"
    """The provider's processing window closed before the item ran (ADR-0143 §6).
    Carries neither payload. Resubmitting it is a new batch, not a retry of this
    one, which is why there is no ``TIMED_OUT`` failure kind for it to be."""

    CANCELLED = "cancelled"
    """The batch stopped by an act outside this seam — an operator in a vendor
    console, an account action. Carries neither payload. It exists although
    ADR-0143 §10 gives the seam no ``cancel``: an outcome vocabulary with nowhere
    to put the fact would force an implementation to report it as ``FAILED`` or
    ``EXPIRED``, both false, and one of them carrying a disposition a caller would
    act on."""


class BatchFailureKind(StrEnum):
    """Why one item of a batch failed, in ``ModelError``'s own vocabulary (ADR-0143 §5).

    Seven members, each corresponding to a class in ``core/errors.py`` and taking
    that class's two flags, so a caller that already reasons about
    ``retryable``/``routable`` needs no second vocabulary whether an answer came
    through ``complete`` or through a batch.

    The correspondence is deliberately **not** a bijection, and both gaps are
    decisions. There is no counterpart to ``ModelTimeoutError``: a batch item has
    no per-request deadline of its own, and the only clock over it is the
    processing window, whose exhaustion is
    :attr:`BatchOutcomeKind.EXPIRED` rather than a failure. And
    :attr:`INVALID_REQUEST` corresponds to no class at all, because at the
    ``complete`` seam a malformed request is *raised* under ADR-0066 §3 and never
    returned — here the whole-batch refusal of ADR-0143 §3 covers the malformed
    items ``submit`` can see, and this kind is what remains for an item a provider
    rejects for a reason ``submit`` could not check.
    """

    AUTHENTICATION = "authentication"
    """The provider refused the credential — ``ModelAuthError``'s disposition."""

    RATE_LIMITED = "rate_limited"
    """The provider throttled the item — ``ModelRateLimitError``'s disposition."""

    UNAVAILABLE = "unavailable"
    """The provider was unreachable or failing — ``ModelUnavailableError``'s."""

    CONTENT_FILTER = "content_filter"
    """The provider's safety filter refused it — ``ModelContentFilterError``'s."""

    UNUSABLE_RESPONSE = "unusable_response"
    """An answer came back that could not be used — ``ModelResponseError``'s."""

    UNKNOWN = "unknown"
    """Nothing above matched — a bare ``ModelError``'s conservative disposition."""

    INVALID_REQUEST = "invalid_request"
    """The provider rejected the request itself, for a reason ``submit`` could not
    check ahead of it. Takes ADR-0066 §3's disposition for a malformed request:
    neither retryable nor routable, because it reproduces identically on every
    attempt from every route."""

    @property
    def retryable(self) -> bool:
        """Whether a repeat of this same item, to this same provider, could succeed.

        Declared once here rather than per consumer, the shape ``core/errors.py``
        ratified for ``ModelError.retryable`` and :class:`ToolFailureKind` already
        copies: it is computable from the enum's own declaration and is the same
        answer for every consumer, which is ADR-0016 §2's test for a semantic
        intrinsic to a type.

        Raises:
            KeyError: If a member was added without a value in
                ``_BATCH_RETRYABLE_BY_KIND``. Loud by construction — a default
                would let a new kind acquire a retry policy nobody chose.
        """
        return _BATCH_RETRYABLE_BY_KIND[self]

    @property
    def routable(self) -> bool:
        """Whether a *different* provider could plausibly succeed at this item.

        Raises:
            KeyError: If a member was added without a value in
                ``_BATCH_ROUTABLE_BY_KIND``, for the reason above. Note that
                routing a *batch* is incoherent — a handle issued by one provider
                is meaningless to another (ADR-0143 §2) — so this flag is advice to
                a caller assembling the **next** batch, not a promise the seam
                will re-route this one.
        """
        return _BATCH_ROUTABLE_BY_KIND[self]


#: Exhaustive over :class:`BatchFailureKind`; a missing member raises rather than
#: defaulting, so adding a kind without choosing its disposition fails loudly.
#: Each value is the ``retryable`` flag ``core/errors.py`` declares for the class
#: ADR-0143 §5 pairs the kind with.
_BATCH_RETRYABLE_BY_KIND: Mapping[BatchFailureKind, bool] = {
    BatchFailureKind.AUTHENTICATION: False,
    BatchFailureKind.RATE_LIMITED: True,
    BatchFailureKind.UNAVAILABLE: True,
    BatchFailureKind.CONTENT_FILTER: False,
    BatchFailureKind.UNUSABLE_RESPONSE: False,
    BatchFailureKind.UNKNOWN: False,
    BatchFailureKind.INVALID_REQUEST: False,
}

#: The ``routable`` half of the same correspondence, on the same terms.
_BATCH_ROUTABLE_BY_KIND: Mapping[BatchFailureKind, bool] = {
    BatchFailureKind.AUTHENTICATION: True,
    BatchFailureKind.RATE_LIMITED: True,
    BatchFailureKind.UNAVAILABLE: True,
    BatchFailureKind.CONTENT_FILTER: False,
    BatchFailureKind.UNUSABLE_RESPONSE: True,
    BatchFailureKind.UNKNOWN: False,
    BatchFailureKind.INVALID_REQUEST: False,
}


class BatchItemFailure(BaseModel):
    """Why one item failed, as a **value** rather than as an exception (ADR-0143 §5).

    Returned, never raised, for the reason ADR-0029 §8 gives and
    :class:`ToolBindingError`'s docstring quotes: "an exception has no
    ``failure.kind.retryable`` to read, so there is nothing for a retry decision to
    be made from". A batch's whole point is that one item's refusal must not
    destroy the other 1,985 results, and an exception is not a container that can
    hold 1,986 answers.

    Attributes:
        kind: The disposition-carrying classification a caller decides from.
        detail: Operator-facing text saying what the provider reported. Free-form
            and never parsed; the decision is ``kind``'s.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: BatchFailureKind = Field(description="The classification a retry decision reads.")
    detail: EncodableText = Field(description="Operator-facing account of what went wrong.")


class BatchItemOutcome(BaseModel):
    """How one submitted item ended, matched to its request by ``item_id``.

    ``fetch`` returns exactly one of these per submitted item — no more, no fewer,
    and none for an ``item_id`` that was not submitted (ADR-0143 §4). **The order
    is unspecified**, and an implementation is not required to make it stable: the
    vendor's results arrive unordered, so a caller matches by ``item_id`` and never
    by position.

    The optional pair is bound to ``kind`` by the type rather than left to the
    caller: a ``message`` is present if and only if the kind is ``SUCCEEDED``, and a
    ``failure`` if and only if it is ``FAILED``. The two payload-free kinds carry
    neither.

    Attributes:
        item_id: The caller's own id, byte-for-byte as it was submitted.
        kind: Which of the four ways this item ended.
        message: The assistant's reply, present exactly on ``SUCCEEDED``.
        failure: The classification and detail, present exactly on ``FAILED``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: NonBlankEncodableText = Field(
        description="The caller's id, byte-for-byte as it was submitted."
    )
    kind: BatchOutcomeKind = Field(description="Which of the four ways this item ended.")
    message: Message | None = Field(
        default=None, description="The assistant's reply; present exactly on SUCCEEDED."
    )
    failure: BatchItemFailure | None = Field(
        default=None, description="Why it failed; present exactly on FAILED."
    )

    @model_validator(mode="after")
    def _payload_matches_the_kind(self) -> BatchItemOutcome:
        """Bind the two optional fields to ``kind``, in both directions (ADR-0143 §9).

        Both directions, because each mis-reads differently: a ``SUCCEEDED``
        outcome with no message is an answer a caller cannot read, and a
        ``FAILED`` one with no failure is a refusal carrying no disposition to
        decide from — which is precisely what returning the failure as a value was
        meant to avoid.
        """
        wants_message = self.kind is BatchOutcomeKind.SUCCEEDED
        if (self.message is not None) != wants_message:
            msg = (
                f"a message is carried if and only if the outcome is SUCCEEDED, "
                f"not {self.kind.name}"
            )
            raise ValueError(msg)
        wants_failure = self.kind is BatchOutcomeKind.FAILED
        if (self.failure is not None) != wants_failure:
            msg = f"a failure is carried if and only if the outcome is FAILED, not {self.kind.name}"
            raise ValueError(msg)
        return self


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


def rests_on_recorded_external_content(provenance: Provenance) -> bool:
    """Whether a record's warrant traces to recorded external content (ADR-0106 §1).

    Not a claim about influence: it reports what was **recorded**, never what a
    model may have read. Text whose recorded origin is not external can still
    have reached a belief — through a plan rationale our own model authored over
    an attacker's sentence, say — and no field on the record says so (ADR-0098
    §5). A ``False`` here is therefore *nothing external is recorded in this
    belief's warrant*, and never *nothing external influenced it*. No consumer,
    surface or ADR may state or imply otherwise.

    **Two-part, because the two bands record externality differently.** In the
    ``ATTESTED`` band it is already recorded — the band is reached only through
    :attr:`MemorySource.EXTERNAL`, whose whole meaning is that a connected source
    reported the belief — so a marker there would be a second spelling of a fact
    :func:`band_of` gives for free, and a second spelling is a second thing that
    can disagree. In the ``ASSERTED`` band it is false by ADR-0098 §1: the user's
    own utterance is not external "however it was composed — a user who pastes an
    email into a turn is exercising judgement". Only in ``DERIVED`` does nothing
    on the record answer the question, and :attr:`Provenance.derived_from_external`
    is the field that fills that gap.

    **The band guard is load-bearing, not tidiness.** ADR-0106 §7 forbids a
    band-keyed validator on that field, so a ``USER_ASSERTED`` provenance carrying
    ``derived_from_external=True`` stays constructible; an unguarded disjunction
    would report a user's own assertion as resting on external content, which
    ADR-0098 §1 forbids in principle. Such a record is malformed rather than
    adversarial, and the honest response is to honour the classifier the corpus
    keys everything else on — ADR-0072 §4's "the standing is keyed on ``source``"
    — rather than a boolean ADR-0106 §2 says means nothing in that band.

    **It takes a :class:`Provenance` rather than a :class:`MemorySource`**, which
    is the one place it departs from :func:`band_of`, and the departure is forced:
    the predicate needs both the source and the field, and ``Provenance`` is the
    object that holds them. It stays a pure function of an immutable value, so it
    disturbs ADR-0068 exactly as little as ``band_of`` does.

    **Every consumer asking "does this rest on recorded external content?" calls
    this**, and none reads ``derived_from_external`` directly for that question
    (ADR-0106 §2). The hand-rolled version is short enough that every consumer
    would write it and one of them would write only its second half — which is
    the defect the function exists to make unwritable. It is *not* the ceiling
    ADR-0106 §6 states on the ``MemoryPolicy`` gate: that ceiling is band-scoped
    on purpose, because an ``ATTESTED`` proposal satisfies this predicate and must
    still be allowed to commit.

    Args:
        provenance: The provenance of the record being classified.

    Returns:
        ``True`` exactly when :func:`band_of` places the record in the
        ``ATTESTED`` band, or places it in the ``DERIVED`` band **and** its
        ``derived_from_external`` is set.
    """
    band = band_of(provenance.source)
    return band is BeliefBand.ATTESTED or (
        band is BeliefBand.DERIVED and provenance.derived_from_external
    )


class MemoryKind(StrEnum):
    """The category of a memory record (the discriminated-union tag)."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"


MAX_EVIDENCE_CITATIONS = 64
"""How many citations a :class:`MemoryRecord` this system **installs** may carry.

A fixed constant and deliberately **not** a ``Settings`` field (ADR-0086 §1): a
bound a deployment can raise is not a bound, and ``export`` crosses deployments,
so a record written under one ceiling and imported under a lower one would be a
record the receiving system's own contract refuses for a reason its user cannot
see and did not cause.

**It is enforced at the ``MemoryWriter`` seam and nowhere on this type** — see
:attr:`Provenance.evidence` for why a ``max_length`` here would be the wrong
mechanism, and :meth:`~ai_assistant.core.protocols.MemoryWriter.ingest` for the
obligation itself. The scope is a ``MemoryRecord`` *install*: :class:`Goal`
carries a :class:`Provenance` too and is not reached, because nothing accumulates
on the goal write path and ADR-0077 §11 already assigns that seam to the lane
that adds an inferred-goal producer.

64 was set comfortably above the observation batch's default of 20, a setting
ADR-0285 §5 has since removed — more than three whole batches, so accumulation
was real before the bound bit — and is small enough to keep the
contract-mandated resolution cost of a listing page legible (ADR-0086 §1).
"""


MAX_TOPIC_LABEL_LENGTH: Final[int] = 64
"""How many characters a :data:`TopicLabel` may carry (ADR-0213 §4).

A label is a filing word the owner reads in a listing, not a sentence: 64 is
generous for the longest ordinary compound and short enough that a producer
writing prose into the field is refused rather than accommodated. It is the same
figure :data:`MAX_EVIDENCE_CITATIONS` takes for the adjacent kind of bound.

A fixed constant and deliberately **not** a ``Settings`` field (§4): the axis's
whole value is that a record's topic set is small enough for the owner to read,
and a deployment that raised this could not be seen to have done so from the data.
"""

MAX_TOPICS_PER_PROPOSAL: Final[int] = 4
"""How many labels one producer may propose for one record (ADR-0213 §4).

Four is the number at which a topic set stays readable at a glance and a
topic-scoped act stays meaningful; a record that is genuinely about five things is
a record that is about one thing the vocabulary has not learned to name.

**This bounds a producer's suggestion, and :data:`MAX_TOPICS_PER_RECORD` bounds an
installed record** (§1). The two are one rule at two seams over two different
objects, and neither is a second enforcement point for the other. A response
naming more than this yields **no topics on that record** — the entry is ignored,
never truncated to the bound and never repaired (§4).
"""

MAX_TOPICS_PER_RECORD: Final[int] = 16
"""How many labels a :class:`MemoryBase` this system **installs** may carry (ADR-0213 §1).

**It is enforced at the ``MemoryWriter`` seam and nowhere on this type**, which is
:data:`MAX_EVIDENCE_CITATIONS`'s placement and is taken for that bound's reasons
plus one of this field's own. ADR-0086 §2's test — "does it refuse something that
already worked" — is answered *no* here, so a ``max_length`` on
:attr:`MemoryBase.topics` would be available; what rules it out is the direction
this field will be changed in. A later ADR raising this constant would, with a
``max_length`` in force, make a record written at the new bound unreadable to a
peer at the old one — taking back exactly the compatibility ADR-0213 §11 relies on
when it declines to move ``PROTOCOL_VERSION``. The writer seam has no such edge: it
decides what this deployment *writes*, never what it may *read*. And §8's union is
a ratchet whose overflow must yield a *bounded record* rather than a raised write,
which only the seam computing the union can arrange; a bound above it would enforce
nothing that seam does not and would add a way for the two to disagree.

So a longer tuple is admissible on the type, a record decoded from storage carrying
one is read rather than refused, and such a record converges downward on its next
install (§8) rather than being repaired on the read path.

**16, and the arithmetic is §1's.** It is four times
:data:`MAX_TOPICS_PER_PROPOSAL`, so a record accumulates through several disjoint
folds before the bound can bite at all — a bound at or near the per-proposal cap
would make ordinary reinforcement displace. It is small enough that a record's topic
set stays readable at a glance and a topic-scoped act over such a record still means
something. It is a ceiling nobody should reach, not a quota to fill.
"""


def _topic_label(value: str) -> str:
    r"""Require ADR-0213 §3's canonical form, refusing anything else unchanged.

    Admissible exactly when the value is non-empty, is at most
    :data:`MAX_TOPIC_LABEL_LENGTH` characters, equals its own ``str.casefold()``,
    contains no whitespace character other than ``U+0020 SPACE``, has no leading or
    trailing space, and contains no run of two consecutive spaces.

    **Refused rather than folded**, on ADR-0100 §6's reasoning: "a value that is
    *nearly* right is harder to spot than one that is missing. A normalised name is
    nearly right." One step stronger here — a label arriving non-canonical means a
    producer did not fold its model's output, and folding it under them hides that in
    the one place nobody looks. Refusing puts the failure at the producer, which is
    where ADR-0213 §4 puts the obligation. Nothing anywhere in this system
    case-folds, strips, stems, singularises, transliterates, aliases or
    de-duplicates a label on the way in or on the way out (§3).

    **The whitespace test is ``str.isspace()`` and not a list of the characters
    someone remembered.** ``U+00A0`` is the case that separates the two: it is
    whitespace, it survives ``casefold()``, it is not ``U+0020``, and a check written
    against ``{" ", "\\t"}`` admits it. A rule over "every whitespace character" does
    not rot the way an enumeration does (ADR-0085 §4c).

    **A validator that refuses on decode is available here and is not available
    everywhere**, and the difference is ADR-0086 §2's test: no record in any store
    carries a topic today, so this refuses nothing that already worked. That stops
    being true the moment records carry topics, so **widening this form later must
    answer the same test on the data of that day** — a wider form admits values an
    older peer refuses, which is the direction that breaks. Narrowing it is worse.

    **The message carries the value as given**, through
    :func:`describe_untrusted`, because the whole point of refusing is that the
    producer can see what it actually emitted; a message quoting a folded form would
    report a value nobody wrote.

    Raises:
        ValueError: If the value is not already in the canonical form.
    """
    fault = _topic_label_fault(value)
    if fault is not None:
        msg = f"a topic label {fault} (ADR-0213 §3), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _topic_label_fault(value: str) -> str | None:
    """Which clause of ADR-0213 §3 ``value`` breaks, or ``None`` if it breaks none.

    Split from :func:`_topic_label` so the clause a value broke is available to a
    caller that does not want an exception — the producers of ADR-0213 §4, which
    **ignore** a topics entry they cannot use rather than letting a
    ``ValidationError`` discard the belief that carried it. One implementation of
    the form, read two ways, so a producer's check and the type's cannot drift.
    """
    clauses: tuple[tuple[bool, str], ...] = (
        (not value, "must not be empty"),
        (
            len(value) > MAX_TOPIC_LABEL_LENGTH,
            f"must be at most {MAX_TOPIC_LABEL_LENGTH} characters",
        ),
        (value != value.casefold(), "must equal its own str.casefold()"),
        (
            any(character.isspace() and character != " " for character in value),
            "must carry no whitespace other than U+0020 SPACE",
        ),
        (value[:1] == " " or value[-1:] == " ", "must have no leading or trailing space"),
        ("  " in value, "must carry no run of two consecutive spaces"),
    )
    return next((fault for broken, fault in clauses if broken), None)


type TopicLabel = Annotated[EncodableText, AfterValidator(_topic_label)]
"""What a record is about, as one canonical filing word (ADR-0213 §3).

**Equality of the stored characters is the only relation this type has.** Nothing
treats two unequal labels as one topic, nothing treats one label as narrower or
broader than another, and no hierarchy, synonym set, stem, embedding or model
judgement is a topic relation. Any wider matching rule — case-insensitivity beyond
the canonical form, prefixes, hierarchy, synonymy, or a similarity measure — is
reserved to a later ADR, which is the only instrument that may lift that; no lane
reaches it by implementing one (§3).

The canonical form is deliberately thin, and it is the whole of what buys
convergence at the type level: it makes ``"Health"`` and ``"health"`` the same
value and ``"health"`` and ``"wellbeing"`` different ones. The first is a spelling,
the second is a judgement, and a type that tried to decide the second would be the
classifier ADR-0199 §2 forbids, moved to construction time.

**A label is not an identifier** (§14). It names no entity, resolves to nothing, is
not a key into anything, and is not usable as a cross-hub or cross-store reference.

Layered on :data:`EncodableText` rather than on ``str``: see that alias's note on
why no ``str`` field in this module opts out.
"""


def _strictly_increasing_topics(value: tuple[str, ...]) -> tuple[str, ...]:
    """Require ADR-0213 §1's order: strictly increasing by code point.

    A tuple that is unsorted, or that repeats a label, is refused at construction.
    Order carries no meaning on this field, so **fixing** one is what makes two
    equal sets one value: serialise-and-reconstruct parity, digest stability and a
    store comparison all follow from it, and none of them survives a field where
    ``("health", "sleep")`` and ``("sleep", "health")`` are different bytes.

    Refused rather than sorted, for :func:`_topic_label`'s reason read over a set:
    a producer that did not put its labels in order is a producer whose output
    nobody folded, and quietly folding it here hides that. ADR-0213 §8 states the
    same separation from the other side — an admission order decides *which* labels
    survive a bounded install, and this order decides how the tuple is **stored**.

    Raises:
        ValueError: If the tuple is not strictly increasing by code point.
    """
    for earlier, later in pairwise(value):
        if earlier >= later:
            fault = "repeats a label" if earlier == later else "is not sorted"
            msg = (
                f"topics must be strictly increasing by code point (ADR-0213 §1); "
                f"this one {fault}: {describe_untrusted(value)}"
            )
            raise ValueError(msg)
    return value


class ReportedExtent(BaseModel):
    """Where a reported entry lies in the reporting source's world (ADR-0117 §2).

    A half-open ``[extends_from, extends_until)`` pair, ``None`` at either end
    meaning unbounded — :class:`Validity`'s shape, its endpoint type and its
    invariant, mirrored and deliberately **not** reused, for the reason ADR-0110
    §2 declined to name coverage with ``Validity`` too. Three subjects, three
    types: a ``Validity`` is *our* window on a belief we hold, a
    :class:`ReadCoverage` is a claim about **the read we performed**, and an
    extent is the source's claim about **where the entry it reported lies**.
    Naming two of them with one type would put a record's operational window and
    its source's testimony in one annotation, one field apart, on one record.

    **It is producer testimony, and only about the entry actually reported**
    (§2). A producer declares one only where it can truthfully say where the
    reported entry sits: it is never trimmed to fit a coverage, never widened
    past what the source says, and never derived from the read's own bound or
    from the reader's configuration. Trimming manufactures the containment
    :meth:`ReadCoverage.contains` is asked about, and widening is the same fault
    from the other side — which is why ADR-0110 §2's never-widened discipline for
    coverage is restated here for the extent.

    **Declaring none is always available and always safe** (§2). A producer that
    cannot express an entry's extent — a source whose entries have no position at
    all, or an occurrence whose span is not expressible as a half-open interval —
    declares none, and the belief is then proposed, retrievable and folded
    exactly as it would be otherwise. Only its absence-demotability is withheld
    (ADR-0117 §3). No source shape may make *stating* an extent raise, and no
    producer constructs a degenerate or inverted one to avoid declining.

    **Why this is not the envelope validity window.** ADR-0110 §3 originally
    asked a producer to bound that window to say where an entry sits, and
    ADR-0117 §1 found the two jobs incompatible for a forward-looking source:
    ``Validity.live_at`` gates retrieval, the absence enumeration *and* conflict
    detection, so a window stating "this meeting is on Thursday" makes the record
    unreadable, un-demotable and invisible to the fold until Thursday arrives.
    The extent carries the position; the envelope window keeps its one operational
    job (ADR-0045 §2).

    Attributes:
        extends_from: Inclusive start of the reported entry's span; ``None``
            means the source states no lower bound for it.
        extends_until: Exclusive end of that span; ``None`` means the source
            states no upper bound for it.
    """

    model_config = ConfigDict(frozen=True)

    extends_from: UtcInstant | None = Field(
        default=None,
        description="Inclusive start of the reported entry's span; None means unbounded.",
    )
    extends_until: UtcInstant | None = Field(
        default=None,
        description="Exclusive end of the reported entry's span; None means unbounded.",
    )

    @model_validator(mode="after")
    def _extent_is_ordered(self) -> ReportedExtent:
        """Reject an inverted or empty extent: when both ends are set, end > start.

        :class:`Validity`'s invariant and :class:`ReadCoverage`'s, for a reason of
        this type's own (ADR-0117 §2, §6). An extent admitting no instant would be
        contained by *every* coverage, so a record carrying one would be
        absence-demotable by any reading at all — the unsound direction, and the
        exact opposite of what a zero-width span means. The honest value for an
        entry whose span cannot be expressed is **no extent**, which is why
        declining is always available and why nothing widens a degenerate span by
        an invented epsilon to make it representable.
        """
        if (
            self.extends_from is not None
            and self.extends_until is not None
            and self.extends_until <= self.extends_from
        ):
            msg = "extends_until must be after extends_from"
            raise ValueError(msg)
        return self


class Attestation(BaseModel):
    """What reported a belief, and when that source said so (ADR-0073 §4).

    The two halves of an attested belief's answer to "why is this held?", carried
    as **one value object rather than two nullable fields** (ADR-0092 §2). Two
    independent ``| None`` fields admit four states, of which two are half-answers:
    a record naming a source but not when it spoke renders "your calendar had this
    as of …" with a blank, and one naming a time but not a source attributes it to
    nobody. Both fields required inside one optional slot makes the half-states
    **unconstructable** instead of merely discouraged — the shape :class:`Validity`
    already uses on :class:`MemoryBase` for the same reason.

    Attributes:
        reported_by: The connected source **instance** — "the user's work
            calendar", not "iCalendar" — stable across syncs, because ADR-0092 §6
            leaves it as the only durable handle the record keeps on where it came
            from (an import's id is ours and is minted per sync). It is rendered to
            the user and survives into ``export``, so it is not a place for a
            credential or a filesystem path that discloses more than the source's
            identity. Whether a human-facing display label is configured alongside
            it is the reader seam's question and is **not** this field; a surface
            with no label falls back to this value. Typed :data:`Identifier` — the
            "required, non-empty" ADR-0092 §1 asks for — rather than
            :data:`VisibleIdentifier`, whose tightening is issue #62's for every
            identifier at once.
        reported_at: The instant the reporting source asserts the fact was current,
            **on that source's own clock** (ADR-0092 §3). Not when we read the file,
            not when we wrote the record, and never a local substitute — in
            particular not the file's mtime, which is a property of the last local
            write and moves under a copy, a restore or a ``touch`` while the
            source's claim stays where it was. A source that says nothing about
            when it spoke has no attestation to make, and :class:`Provenance`'s
            validator then settles the outcome structurally: no attestation means no
            ``EXTERNAL`` provenance, so the record is not proposed as an attested
            belief at all.
        extent: Where the reported entry lies in the reporting source's own world,
            or ``None`` where this producer states no position for it (ADR-0117
            §2). A different fact about a different thing from ``reported_at``,
            and neither is derived from the other: an entry reported on Monday
            about a meeting on Thursday has both, and they disagree by design.

            **Optional, and the ``None`` is meaningful rather than a gap.** Most
            sources have no position to state — a settings export, a contact list
            — and are not thereby deficient; a record whose attestation declares
            no extent is simply never absence-demotable (ADR-0117 §3). Every
            record stored before this field existed decodes with ``None``, which
            is the safe default and needs no migration (ADR-0093 §3's additive
            pattern). ADR-0092 §2's half-state argument does not reach it: an
            extent is not half of the "who said so, and when" answer that section
            made unconstructable-in-halves, but a separable third fact nothing
            renders.

            **Here rather than on :class:`Provenance` or the envelope**, so that
            ADR-0110 §3's condition 1 (which keys on ``reported_by``) and its
            condition 3 (which reads this) sit on one object. Since an attestation
            is present exactly when the band is ``ATTESTED``, that placement makes
            the absence close **structurally unreachable** outside the attested
            band rather than excluded by a rule (ADR-0117 §2).

    Two consequences of ``reported_at`` being someone else's clock, both rulings
    rather than observations (ADR-0092 §3):

    * **``reported_at`` earlier than ``Provenance.last_updated`` is the normal
      case**, not an anomaly — Monday's report, revised into the store on Tuesday.
      A consumer treating the pair as an ordering invariant has misunderstood which
      clock each belongs to.
    * **A ``reported_at`` in our future is not refused.** Source clocks skew, and a
      validator comparing the two would refuse a record that is perfectly
      encodable, perfectly readable and merely early — inventing a read-path
      failure, which is what ADR-0086 §3's admissibility test exists to avoid. Skew
      is a *rendering* concern: a surface may say so, and must still not present our
      clock as the source's. Nothing in ``core`` compares them.
    """

    model_config = ConfigDict(frozen=True)

    reported_by: Identifier = Field(
        description=(
            "The connected source instance that reported this belief, stable "
            "across syncs (ADR-0092 §3)."
        ),
    )
    reported_at: UtcInstant = Field(
        description=(
            "When that source asserts the fact was current, on the source's own "
            "clock — never ours, and never a local proxy (ADR-0092 §3)."
        ),
    )
    extent: ReportedExtent | None = Field(
        default=None,
        description=(
            "Where the reported entry lies in the source's own world; None where "
            "this producer states no position for it (ADR-0117 §2)."
        ),
    )


class Provenance(BaseModel):
    """Where a memory came from and how much it should be trusted.

    Attaching this to every record is what distinguishes user-asserted facts
    (the profile) from inferred beliefs (the user model), and what stops one
    unusual interaction from hardening into a permanent, wrong "preference".

    **An ``attestation`` is present exactly when the band is ``ATTESTED``**
    (ADR-0092 §1), and the ``if and only if`` is deliberate in both directions.
    *Set when ``ATTESTED``* makes ADR-0073 §4's gate structural rather than
    procedural: a precondition a producer satisfies by remembering is one it can
    fail by forgetting, and the failure is silent — an attested record with no
    attestation renders exactly the misleading answer that gate forbids. *Absent
    otherwise* keeps ``source`` the single classifier: ADR-0072 §4 rules that
    classification is keyed on ``source`` and never on ``confidence``, so no
    producer can promote a belief by claiming certainty, and an attestation on an
    ``INFERRED`` record would be the same laundering by a different field — a
    derived guess wearing a citation to a system that never reported it. Nothing
    may acquire the standing of a band it is not in by decorating itself.

    **On this class rather than on :class:`MemoryBase`**, where ``validity`` sits.
    ADR-0045 §2 argued that placement in a way that decides this one the other way:
    the window is a lifecycle property of the record's life *in the store*, set
    operationally by the applier, and putting it here — "whose every other field is
    set by the *producer* of the belief" — would mix two authorships. An
    attestation is the pure case of the other kind. Who reported a belief and when
    they said so are producer-set facts about trust and source, which is what
    ADR-0045 §2 says this class stays about.

    **``evidence`` is ordered oldest-accumulated first, and carries no
    ``max_length``** (ADR-0086 §2, §3). The order is what lets a fold displace by
    age; the absence of a length bound is the decision, not an omission. A
    validator runs on *deserialisation* as well as on construction, so a
    ``max_length`` would take a belief a running deployment already holds above
    :data:`MAX_EVIDENCE_CITATIONS` — perfectly encodable, perfectly readable,
    merely large — and make ``get``, ``list_beliefs`` and ``export`` fail on it:
    a strictly new failure invented on the read path, which is exactly what the
    bound exists to make unreachable. The test is not "is it a validator on a
    ``core`` type" but "does it refuse something that already worked":
    :data:`EncodableText` does not, because a string with no UTF-8 encoding never
    round-tripped, and a cardinality bound would. So the bound lives at the
    ``MemoryWriter`` seam, on *installs*, and this type admits a longer tuple.

    **``evidence_elided`` is an elision, not a tombstone, and the two are
    different facts** (ADR-0086 §4). ADR-0077 §6's tombstone says a cited episode
    stood here and *went away* — deleted or expired. An elision says it stood here
    and **we stopped carrying the reference**: the episode may be perfectly
    intact, so a surface must not render the two alike or it tells the user their
    data was lost when it was not. It is a count and never an id, because the ids
    are the payload the bound exists to stop carrying, and it is an **upper
    bound** rather than a total: a displaced citation that is later re-cited, or
    two elided histories folded together, both double-count, and making it exact
    would need the ids back.

    **``last_updated`` and ``last_confirmed_at`` are two clocks, and reading one
    for the other is the confusion this pairing exists to prevent** (ADR-0109 §2).
    ``last_updated`` is transaction time — when *we* last revised the belief
    (ADR-0045 §3) — so a calendar's months-old report imported this morning has a
    ``last_updated`` of this morning and a currency read off it would call that
    belief perfectly fresh. ``last_confirmed_at`` is when the *world* last
    confirmed the belief: the user stating it, the reporting source's own
    ``reported_at``, or the latest ``occurred_at`` among the episodes cited
    (ADR-0103 §9). The two legitimately disagree in **both** directions — a
    ``reported_at`` in our future is stored unchanged (ADR-0092 §3), so an attested
    record's confirming instant may sit after the write that stored it.

    **``last_confirmed_at`` of ``None`` is ADR-0103 §9's *unknown*, which is
    neither stale nor fresh.** It is the state of a record whose confirming instant
    the store does not hold: every record written before ADR-0109 (the field is
    additive with a default, so nothing migrates and nothing fabricates a decline
    that was never measured), every episode — an episode cites nothing, nothing
    retires one, and "is this still true?" is not a question about it — and every
    :class:`Goal`, which is not a belief whose currency lapses. No surface,
    consumer or writer renders, treats or ranks an unknown as a confirmed one, and
    none reads it as stale either.

    **Currency itself — the elapsed interval — is never stored** (ADR-0109 §1,
    §3). It is computed at read, from this instant and the reading component's own
    clock, and is *unknown* both where the field is ``None`` and where the instant
    is in that component's future. A stored interval would be stale before it was
    committed; the instant is a measurement made once, when the confirming event
    was in hand, and no later retention or displacement can unmake it.

    **``derived_from_external`` is a marker for the ``DERIVED`` band and speaks
    nowhere else** (ADR-0106 §2). It answers, for a belief this system worked out,
    whether the material it was worked out *from* included recorded external
    content — the fact ADR-0098 §5 said the ruling point had no field to read. It
    is narrower than :func:`rests_on_recorded_external_content`, deliberately: a
    calendar import carries ``source=EXTERNAL`` and leaves this field at its
    default, so reading the field alone would call the most plainly external
    record in the store untainted. The **predicate** is what any consumer asks;
    this field is one of its two inputs.

    **It never clears, and a user's assertion is the only exit** (ADR-0106 §4). No
    fold, merge, reinforcement or supersession removes it: a fold's value is the
    **disjunction** of both sides, so a tainted belief reinforced by a clean
    observation stays tainted. Without that, the laundering the marker exists to
    stop simply moves one step along — consolidate tainted material, then reinforce
    it once from a clean source and watch the marker clear. It is the same ratchet
    ADR-0103 §3 puts on evidence-strength, from the other direction: evidence is
    never unseen, and a warrant is never un-received. The exit is ADR-0072 §4's
    supersession by the user, which writes the user's own word at a fresh id — not
    external by ADR-0098 §1, and never obliged to inherit taint from what it
    retires.

    **No validator conditions it on the band, and that absence is the decision**
    (ADR-0106 §7). A validator asserting ``ATTESTED ⟹ True`` would refuse, on
    *decode*, every attested record ``readers.calendar`` has already written —
    ADR-0086 §3's "does it refuse something that already worked", answered yes.
    ADR-0092 §1 could land such a validator because ADR-0092 §2 had verified the
    band was empty; that verification has expired, and on this axis the answer to
    "now or never" is **never**. So the rule is stated over producers and callers
    and checked at the seams that write, and a stray flag outside the ``DERIVED``
    band stays constructible and means nothing — which is why both the predicate
    above and ADR-0106 §6's gate ceiling are band-guarded rather than trusting it.

    **The default is ``False`` and nothing is backfilled** (ADR-0106 §2). A
    pre-field *derived* record decodes ``False``, and that is true of it: no
    ``EXTERNAL`` citation exists to have been recorded. A pre-field *attested*
    record decodes ``False`` too and that says nothing about it at all — its
    externality is :func:`band_of`'s to report. The only conservative migration
    available would mark every legacy derived record tainted, since no migration
    can distinguish the influenced ones, putting every belief a deployment holds
    behind a user question forever on no evidence; that asserts a taint the system
    cannot know in the same breath as refusing to assert a cleanliness it cannot
    know. Both directions are unavailable for one reason, and the honest position
    is to state what is recorded and name what is not.

    **``supplied_withheld_content`` was here and is not any more** (ADR-0217 §1,
    §9). ADR-0204 §1 placed it on this class correctly, under
    :class:`MemoryBase`'s own placement rule: *what material stood in front of the
    producer* is where a record came from, which is this class's question. What
    changed is not that the answer was wrong but that the **question moved**. Two
    further setters now write the same slot — the owner's explicit act and a model's
    proposal — so the slot asks *who may receive this record*, of which the
    derivation's answer is one input, and that question is the envelope's rather than
    this class's. The field is therefore removed rather than kept beside a second
    one: :attr:`MemoryBase.placement` carries it, ``True`` becoming reach ``OWNER``
    with setter ``DERIVED``, and :class:`Placement` states the whole rule — both
    routes, ADR-0210 §1's narrowed evaluation set, and the ratchet. Nothing about
    ADR-0204's evaluation, its site, its producer or its withholding moved with it.

    **No validator constrains ``last_confirmed_at``, and that absence is the
    decision** (ADR-0109 §8). Not required, because a required instant would refuse
    every record already in a store, on the *read* path, at deserialisation — the
    same failure the missing ``max_length`` above avoids, at its widest scope. Not
    ordered against ``last_updated``, because the paragraph above makes the
    later-than case ordinary rather than pathological. And not pinned to
    ``attestation.reported_at``, because a corroborating fold keeps the *target's*
    attestation while the survivor's instant may be the incoming derived record's
    (ADR-0103 §6): the two fields are not redundant, and their disagreement after a
    fold is meaningful rather than drift.
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
        description=(
            "References (e.g. episode ids) supporting this record, oldest "
            "accumulated first (ADR-0086 §3)."
        ),
    )
    evidence_elided: int = Field(
        default=0,
        ge=0,
        description=(
            "How many displacements this record's history has performed, and "
            "therefore an upper bound — never a total — on the citations it no "
            "longer carries (ADR-0086 §4)."
        ),
    )
    last_updated: UtcInstant = Field(
        description=(
            "Transaction time: when the system last *revised* this belief (tz-aware). "
            "This is the clock of the store changing its mind, not the clock of when the "
            "belief holds — the latter is ``MemoryBase.validity`` (ADR-0045 §3)."
        ),
    )
    attestation: Attestation | None = Field(
        default=None,
        description=(
            "What reported this belief and when that source said so; set if and "
            "only if ``band_of(source)`` is ``ATTESTED`` (ADR-0092 §1)."
        ),
    )
    derived_from_external: bool = Field(
        default=False,
        description=(
            "Whether a **derived** belief's warrant traces to recorded external "
            "content (ADR-0106 §2). No meaning outside the ``DERIVED`` band, where "
            "``band_of`` already answers the question; ask "
            "``rests_on_recorded_external_content`` rather than reading this."
        ),
    )
    last_confirmed_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the *world* last confirmed this belief, on the clock of whatever "
            "confirmed it — the user's utterance, the source's ``reported_at``, or "
            "the latest ``occurred_at`` among the episodes cited (ADR-0103 §9). "
            "``None`` is *unknown*, never stale and never fresh. Not transaction "
            "time: that is ``last_updated`` (ADR-0109 §2)."
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

    @model_validator(mode="after")
    def _attested_iff_attestation(self) -> Provenance:
        """An ``attestation`` is carried exactly by the ``ATTESTED`` band (ADR-0092 §1).

        The third band-keyed validator on this class, and it is here for the reason
        the two above it are: the gate is not the only path a :class:`Provenance`
        takes — :class:`Goal` carries one and reaches no propose/dispose gate at
        all — and a validator on the value needs no gate. An attested ``Goal`` would
        owe the same disclosure as an attested belief, and only a validator reaches
        it (:meth:`_derived_is_never_certain` states that argument in full).

        **Admissible on ADR-0086 §3's own test**, which is "not 'is it a validator on
        a ``core`` type' but 'does it refuse something that already worked'". Nothing
        has ever produced an ``EXTERNAL`` record: the only mention of the member
        anywhere under ``src/`` is :func:`band_of`'s arm, no module constructs one,
        and ADR-0092 §9 made a store scan a precondition of this validator landing —
        the implementing lane confirmed through ``export`` (which returns
        window-closed records too, ADR-0045 §6) that the deployment's store holds
        none. So this refuses nothing a running deployment can already decode, which
        is exactly the condition ADR-0072 §3 named when it *declined*
        :meth:`_derived_is_never_certain` ("there is no producer yet that could
        violate the rule") and ADR-0077's observer later met. This is that precedent
        one band over.

        **And the timing is the argument, not an accident of it.** The first import
        makes the band permanently non-empty, after which this rule is a data
        migration rather than a validator — and the band whose entire warrant is
        someone else's would have acquired the ability to say nothing about whose.
        """
        attested = band_of(self.source) is BeliefBand.ATTESTED
        if attested and self.attestation is None:
            msg = (
                f"{self.source.name} provenance is in the ATTESTED band and must carry an "
                f"attestation naming what reported it and when that source said so "
                f"(ADR-0073 §4, ADR-0092 §1)"
            )
            raise ValueError(msg)
        if not attested and self.attestation is not None:
            msg = (
                f"{self.source.name} provenance is not in the ATTESTED band and must not carry "
                f"an attestation: a belief may not acquire the standing of a band it is not in "
                f"by citing a source that never reported it (ADR-0072 §4, ADR-0092 §1)"
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


class PlacementReach(StrEnum):
    """The set of people a record may be received by (ADR-0217 §1).

    A **denotation of a set of people**, and the two members below are the two sets
    this system can denote today: ``ANYONE`` denotes every person, ``OWNER`` the set
    whose one member is the owner. The enumeration is *the vocabulary as it stands,
    not a cardinality* ADR-0217 fixes — a later decision giving it further
    denotations (named people, circles, #1718) **adds** them under ADR-0082 §1 and
    changes no clause of §1, because every clause there is written over *a* reach
    rather than over the pair.

    **Ordered by narrowness, and the order is total today** (§1). ``OWNER`` is the
    narrower, so the meet of the pair is ``OWNER`` wherever either side carries
    it — which is ADR-0204 §5's disjunction member for member, so no producer's
    arithmetic changed when the boolean became this. A later ADR adding denotations
    **not** totally ordered with these two owes the meet for every pair it makes
    reachable, and a representation for a meet that is empty, before either can be
    folded.

    **Never read as a channel placement** (§1's vocabulary clause). ADR-0199 §3
    *places a class* as speakable **on a channel**; this *places a record* **for a
    set of people**, and §2's read rule is the conjunction of the two. Neither
    renames the other and neither is read as the other.
    """

    ANYONE = "anyone"
    OWNER = "owner"


class PlacementSetter(StrEnum):
    """Who narrowed a record's placement (ADR-0217 §3).

    **Exactly three, and that enumeration is exhaustive** — unlike
    :class:`PlacementReach`, whose members are the vocabulary of the day. No
    implementation or later ADR adds a fourth without superseding §3's first
    clause.

    They carry a **total order, strongest first: ``DERIVED``, then ``OWNER_ACT``,
    then ``PROPOSED``** (§3). Where two setters would write the same reach the
    stronger is recorded, which is what makes the owner's act final over a model's
    in the same-reach case as well as the differing-reach one, and what keeps a
    derivation's narrowing — the one §3's closing clause forbids an act to lift —
    from being laundered into an act's.

    Attributes:
        OWNER_ACT: The owner said so, at write or after the fact. Final over a
            model's proposal in both directions; it may narrow a placement whose
            setter is ``None`` or ``PROPOSED`` and widen one whose setter is
            ``PROPOSED`` or ``OWNER_ACT``, and it never widens a ``DERIVED`` one.
        DERIVED: ADR-0204 §2's evaluation or §5's inheritance, unchanged in every
            respect except what they write into. No user act, configuration,
            setting or later lane widens one in place; a supersession is the only
            route by which a live record stops carrying it.
        PROPOSED: A model's proposal (§4). The weakest: it may only narrow, only
            where the placement is reach ``ANYONE`` with no setter, and never on a
            record already in the store.
    """

    OWNER_ACT = "owner_act"
    DERIVED = "derived"
    PROPOSED = "proposed"


#: Narrowness order on :class:`PlacementReach` — higher is narrower (ADR-0217 §1).
#: The meet is the maximum of this, which on the two members shipped is ``OWNER``
#: wherever either side carries it.
_REACH_NARROWNESS: Final[dict[PlacementReach, int]] = {
    PlacementReach.ANYONE: 0,
    PlacementReach.OWNER: 1,
}

#: ADR-0217 §3's total order over the setters, strongest first, with the absent
#: setter weakest of all: a placement nothing narrowed supplies no narrowing, so it
#: can never out-rank one that did.
_SETTER_STRENGTH: Final[dict[PlacementSetter | None, int]] = {
    PlacementSetter.DERIVED: 3,
    PlacementSetter.OWNER_ACT: 2,
    PlacementSetter.PROPOSED: 1,
    None: 0,
}

#: The two setters ADR-0217 §3 calls final against a proposal: a ``PROPOSED``
#: placement is not a *side* of a fold against either of them.
_FINAL_SETTERS: Final[frozenset[PlacementSetter]] = frozenset(
    {PlacementSetter.OWNER_ACT, PlacementSetter.DERIVED}
)


class Placement(BaseModel):
    """Who may receive this record, and who narrowed it (ADR-0217 §1).

    ADR-0204 put the question "did content this system may not say aloud stand in
    this record's warrant?" on a boolean of :class:`Provenance`. ADR-0217 §1 widens
    that mark rather than adding a second field beside it: the slot now answers *who
    may receive this record*, of which the derivation's answer is one input, and two
    further setters may write it. A record ADR-0204 §2 or §5 would have stamped
    ``True`` carries reach ``OWNER`` with setter ``DERIVED``; one it would have
    stamped ``False`` carries the default.

    **One field rather than two, which is the safer shape** (§1). Two recorded
    values in front of one read invite the failure where one is written and the
    other is not — a supply site consulting the placement and not the mark would
    speak a record ADR-0204 withholds, silently. One slot, three setters, one read.

    **The derivation records what stood in a record's warrant, and never what its
    text says** (ADR-0204 §1, ADR-0217 §3). It writes reach ``OWNER`` with setter
    ``DERIVED`` by exactly two routes and no third: **directly**, where the supply
    the turn that produced this record ran over held content ADR-0199 §3 withholds
    from a channel of unbounded audience — whether or not a subtraction then kept
    that content from the stages that produced it, and whether or not the produced
    text drew on it — or **inherited**, where the record was derived from a record
    whose own reach is narrower (ADR-0204 §5). Deciding "did this text actually use
    that belief?" would mean reading ``MemoryBase.content`` or asking a model what a
    passage is about, which ADR-0199 §2 forbids as a decision procedure; this is the
    one stage upstream that is decidable from recorded origin, and it
    over-approximates deliberately.

    **One exception, on one class of record** (ADR-0210 §1, §8, as ADR-0217 §2
    carries it forward by field name alone). On an episode captured from an
    operation whose **output channel's audience is unbounded**, both routes above
    range over less than the whole supply: over the members of that turn's supply a
    relevance read taken with the turn's own goal statement returned — the belief
    composition and ADR-0158's episodic supplement, ADR-0074 §5's second and third
    groups — together with the turn's context facets, and never over a member the
    supply holds only because it stands in ADR-0074 §5's first group, the
    conversation's own recent turns. Both routes survive and neither is dropped;
    what narrows is the set they range over. The **withholding is not narrowed with
    it**: an ``OWNER``-placed record is removed from that turn's supply wherever in
    it it stood, so what a member of the first group loses is the power to narrow a
    placement and nothing else. On every **other** record — an episode of a
    bounded-channel turn, a belief, a record written before either decision — the
    derivation is exactly what ADR-0204 §1 says.

    **And that exception is why the derivation stops being monotone** (#1775). A
    conversation tail is in the supply because it is *the conversation* and not
    because it answered the question (ADR-0074 §5), so before ADR-0210 one spoken
    turn's withholding narrowed its episode, the next turn's tail carried that
    episode, ADR-0204 §3 withheld it, and the narrowing propagated through the
    episodic record for as long as the conversation ran — on any store, whatever was
    asked.

    **A derivation never clears** (ADR-0204 §5, ADR-0217 §3). No fold, merge,
    reinforcement or consolidation writes a wider reach over a narrower one: a
    fold's reach is the **meet** of both sides (:meth:`folded_with`), and a producer
    deriving a record from records of this store takes the narrowest over **every
    record it was supplied** (:meth:`narrowest_of`) — never over the subset it cited,
    so ``Provenance.evidence`` is not the input set. No user act, configuration,
    setting or later lane widens in place a placement whose setter is ``DERIVED``; a
    supersession is the only route by which a live record stops carrying one, and a
    ``SUPERSEDE`` neither clears nor inherits it — ADR-0040 §5a carries nothing of
    the target onto the correction, so the correction carries its own producer's
    placement and the retained target keeps its own.

    **The legal states are enumerated and refused at construction**, so no producer,
    decode or later lane can represent a combination ADR-0217 does not mean. The
    table is total:

    ==============  ====================  ==============
    ``set_by``      permitted ``reach``   ``set_at``
    ==============  ====================  ==============
    ``None``        ``ANYONE`` only       ``None`` only
    ``DERIVED``     ``OWNER`` only        set, or ``None``
    ``PROPOSED``    ``OWNER`` only        **required**
    ``OWNER_ACT``   ``ANYONE`` or ``OWNER``  **required**
    ==============  ====================  ==============

    **Of the five refusals the two that matter most are the two that are otherwise
    silent** (§1). ``reach=ANYONE`` with ``set_by=DERIVED`` would be a record the
    derivation narrowed rendered speakable on a channel of unbounded audience — the
    laundering ADR-0204 §5 exists to stop, reachable by construction rather than by
    a mistake in any rule. ``reach=OWNER`` with ``set_by=None`` would be a narrowing
    no setter is accountable for, which §3's precedence could not rule on. Neither
    is a state any clause of ADR-0217 produces, so refusing them costs nothing and
    closes two routes by which a bug elsewhere becomes a disclosure.

    **A ``set_at`` of ``None`` beside a setter is *unknown*, never
    unrecorded-therefore-recent** (§1). By the table that is a ``DERIVED`` setter
    and no other, and it **originates** on exactly one path: ADR-0217 §9's decode of
    a record written before this field existed, which carries no instant for an act
    nobody timed. It reaches a second record only by a fold carrying it forward,
    which mints no instant and makes no second narrowing. No consumer reads such a
    ``None`` as evidence about when the narrowing was made and no surface renders it
    as one — ADR-0109's reading of ``last_confirmed_at`` and ADR-0204 §1's fourth
    clause, applied to the one place this type inherits the same gap.

    **The obligation that closes that residue is a *producer* obligation** (§1), and
    it is stated there rather than here because **a validator cannot see which path
    constructed the value**: this type carries ``reach``, ``set_by`` and ``set_at``
    and nothing else, so a decode of a pre-field record and a fresh derivation are
    indistinguishable to it. Every derivation this system performs writes the
    instant of the narrowing it makes, so an untimed ``DERIVED`` placement in a
    store this decision's implementation wrote *descends from* a pre-field record
    and nothing else.

    **A setter of ``None`` states that nothing has narrowed this record**, and on a
    record written after this field landed that is a measurement rather than merely
    a default — exactly as ADR-0204 §1's third clause says of its ``False``. On a
    record written **before** it landed it is a decode default and not a
    measurement, which is why §9's decode rule exists.
    """

    model_config = ConfigDict(frozen=True)

    reach: PlacementReach = Field(
        default=PlacementReach.ANYONE,
        description=(
            "Who may receive this record (ADR-0217 §1). A record is emitted on an "
            "output channel only if every person who can perceive that channel's "
            "emission is a member of this set (§2) — which today reduces to "
            "ADR-0199 §1's two audiences: an ``OWNER`` record is withheld from a "
            "channel of unbounded audience and nothing is withheld from a bounded "
            "one. A conjunct beside ADR-0199 §3's placements, never a replacement "
            "for them: no reach makes speakable anything §3 withholds."
        ),
    )
    set_by: PlacementSetter | None = Field(
        default=None,
        description=(
            "Who narrowed this record, or ``None`` where nothing has (ADR-0217 §3). "
            "``None`` is a measurement on a record written after this field landed "
            "and a decode default on one written before it (§1, §9)."
        ),
    )
    set_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the narrowing this placement records was made (ADR-0217 §1), "
            "tz-aware. ``None`` beside a ``DERIVED`` setter is **unknown** — the "
            "decode of a record written before this field existed (§9), carried "
            "forward by a fold that minted no instant — and is never read as "
            "unrecorded-therefore-recent."
        ),
    )

    @model_validator(mode="after")
    def _states_are_enumerated(self) -> Placement:
        """Refuse every combination outside ADR-0217 §1's table.

        On the type rather than at the producers, because §1 puts it there: "so no
        producer, decode or later lane can represent a combination this ADR does not
        mean". A validator runs on *deserialisation* as well as on construction,
        which is what closes the second route in — and it refuses nothing that
        already worked (ADR-0086 §3's test), because no store holds this field until
        the change that adds it and §9's decode maps every legacy record onto a row
        of the table.
        """
        if self.set_by is None:
            if self.reach is not PlacementReach.ANYONE:
                msg = (
                    f"a placement of reach {self.reach.name} carries no setter: a narrowing "
                    f"nobody is accountable for is a state ADR-0217 §3's precedence cannot "
                    f"rule on (ADR-0217 §1)"
                )
                raise ValueError(msg)
            if self.set_at is not None:
                msg = (
                    "a placement carries an instant with no setter: the instant names when a "
                    "narrowing was made, and nothing narrowed this record (ADR-0217 §1)"
                )
                raise ValueError(msg)
            return self
        if self.reach is PlacementReach.ANYONE and self.set_by is not PlacementSetter.OWNER_ACT:
            msg = (
                f"a placement set by {self.set_by.name} carries reach ANYONE: a record the "
                f"derivation or a model narrowed would be speakable on a channel of unbounded "
                f"audience, which is the laundering ADR-0204 §5 exists to stop (ADR-0217 §1)"
            )
            raise ValueError(msg)
        if self.set_at is None and self.set_by is not PlacementSetter.DERIVED:
            msg = (
                f"a placement set by {self.set_by.name} carries no instant: only a DERIVED "
                f"placement may, and only as ADR-0217 §9's decode of a record written before "
                f"the field existed (ADR-0217 §1)"
            )
            raise ValueError(msg)
        return self

    def folded_with(self, other: Placement) -> Placement:
        """ADR-0217 §3's meet over two placements **of one belief**.

        The survivor's reach is the narrower of the eligible sides'; its setter is
        the strongest, in :class:`PlacementSetter`'s order, among the eligible sides
        that carry that reach — a side whose reach is wider supplies no setter,
        having supplied none of the narrowing — and its instant is that side's,
        never the instant of the fold, because the stamp names when the placement
        was set and not when a duplicate was merged.

        **Eligibility is decided before the meet** (§3): a placement whose setter is
        ``PROPOSED`` is **not a side** of a meet against one whose setter is
        ``OWNER_ACT`` or ``DERIVED``. It is discarded before the arithmetic runs
        rather than weighed in it, because §4 already forbids a proposal to overwrite
        either — and weighing it here would let a model undo an owner's act by
        duplication, §3's finality defeated without ever writing to the owner's
        record. Nothing else is ever discarded.

        **This filter is bounded to the fold and does not reach a derivation.** A
        derivation's inputs are *different records*, the derived record carries no
        act of the owner's for a proposal to override, and an ``OWNER`` input
        discarded there is an ``OWNER`` input laundered — so
        :meth:`narrowest_of` takes every supplied placement as a side, whatever its
        setter.

        **Ties are broken on the instant deterministically** (§3). Where two eligible
        sides carry the same reach *and* the same setter the survivor carries the
        **earlier** instant, and where either carries none it carries none. That rule
        is total, commutative and associative — an absent instant absorbs, a known
        one takes the minimum — so a fold's result does not depend on which side an
        implementation calls the stored one, nor on the order three duplicates are
        merged in. An absent instant is §9's decoded legacy placement, and keeping it
        unknown is better than adopting a known instant that would assert a first
        narrowing this system cannot vouch for.

        Args:
            other: The placement being folded in.

        Returns:
            The survivor's placement.
        """
        if self.set_by is PlacementSetter.PROPOSED and other.set_by in _FINAL_SETTERS:
            return other
        if other.set_by is PlacementSetter.PROPOSED and self.set_by in _FINAL_SETTERS:
            return self
        return _meet((self, other))

    @classmethod
    def narrowest_of(cls, placements: Iterable[Placement]) -> Placement:
        """ADR-0217 §3's meet over the placements a derivation was **supplied**.

        A producer deriving a record from records of this store writes the narrowest
        reach over **every record it was supplied** — never over the subset it cited,
        selected, ranked or judged relevant — which is ADR-0204 §5's
        all-inputs rule generalised from a disjunction to a meet. The derived
        record's setter follows :class:`PlacementSetter`'s order over the supplied
        placements that carry the surviving reach, and its instant follows the same
        rule the fold's does, so a narrowing that **only** a ``PROPOSED`` placement
        supplied is recorded ``PROPOSED`` and the owner still lifts in one act what a
        model proposed.

        **No supplied placement is discarded on this path** (§3), which is the one
        way it differs from :meth:`folded_with`: the eligibility clause is about two
        placements of one belief and what it protects is an act on that belief. A
        consolidation supplied a record placed reach ``ANYONE`` setter ``OWNER_ACT``
        **and** one placed reach ``OWNER`` setter ``PROPOSED`` therefore derives
        reach ``OWNER``, not ``ANYONE``.

        **It is not ADR-0204 §2's own evaluation and does not stand in for it** (§3).
        Where that disjunction is ``True`` of *this* record's production the record
        is reach ``OWNER`` setter ``DERIVED`` on that ground alone, whatever its
        inputs carried — a fact about this record's warrant rather than an
        inheritance of another record's stamp.

        Args:
            placements: The placement of every record the producer was supplied.

        Returns:
            The meet over all of them; the default placement over none.
        """
        return _meet(tuple(placements))


def _meet(sides: Sequence[Placement]) -> Placement:
    """ADR-0217 §3's meet over already-eligible sides, in one place.

    The narrowest reach; among the sides carrying it, the strongest setter; among
    those, the earliest instant with an absent one absorbing. Written once and
    called by both :meth:`Placement.folded_with` and :meth:`Placement.narrowest_of`,
    because a meet stated in two places is a meet that can drift between them.

    Args:
        sides: The eligible placements. Empty yields the default.

    Returns:
        The meet.
    """
    if not sides:
        return Placement()
    reach = max((side.reach for side in sides), key=_REACH_NARROWNESS.__getitem__)
    narrowing = [side for side in sides if side.reach is reach]
    setter = max((side.set_by for side in narrowing), key=_SETTER_STRENGTH.__getitem__)
    winners = [side for side in narrowing if side.set_by is setter]
    instants = [side.set_at for side in winners]
    set_at = None if any(instant is None for instant in instants) else min(filter(None, instants))
    return Placement(reach=reach, set_by=setter, set_at=set_at)


class MemoryBase(BaseModel):
    """Fields shared by every memory record, regardless of kind.

    **``about_person`` is the subject axis** (ADR-0100): whom the belief is
    *about*, which ADR-0099 §2 rules orthogonal to whose hub this is. It is on the
    envelope rather than on :class:`Provenance` because ``Provenance`` answers *why
    this should be believed* and the envelope answers *what is held, about what,
    and for how long* — a field is placed by which question it answers, not by who
    sets it (§2). Four rules govern it, and each is a clause rather than a
    convention:

    * **Two states, never three** (§1). It is stated, or it is ``None``. A blank
      or whitespace-only label is refused at construction — a record saying ``""``
      is a producer that meant to speak and said nothing — which is why the
      annotation is :data:`NonBlankEncodableText` and not the bare
      :data:`EncodableText` of ADR-0100 §1's illustrative snippet. The same type
      supplies the *other* half §6 needs: it refuses a blank without stripping the
      value it accepts.
    * **``None`` means no subject is stated, and is read as the owner's** (§3). It
      is not "unknown", and no reader, store or surface may exclude a ``None``
      record from an answer about the owner on the ground that it says nothing.
      **The owner is never named here** — there is no user identity anywhere in
      this system (ADR-0036 §3, ADR-0097 §1), so a label naming the owner would be
      a second spelling of a subject that already has one: the absence.
    * **A label, resolving to nothing** (§6). Not an identifier, not a key, not a
      reference. Nothing here treats two equal labels as one person or two unequal
      ones as different people; whether labels may be matched at all is ADR-0101's,
      which is the only instrument that may lift that. It is stored and returned
      byte for byte: nothing normalises, case-folds, aliases or de-duplicates it.
    * **Whom, not what** (§6). A belief about a company, a project, a device or a
      topic states no subject, and a belief about two people is two beliefs.

    **Stating one is not licence to propose one** (§4). A producer fills it only
    from a subject it actually received — an explicit user act, or a structured
    field of a source that names whom an entry is about — and never by inferring a
    person from content. The field widens no producer's warrant, and its existence
    may not be cited as though it did.

    **``topics`` is the *about what* axis beside it** (ADR-0213 §2), placed on the
    envelope by the same ADR-0100 §2 test and landing here for the same reason:
    the two together are the *about* half of the envelope's question, one asking
    *whom* and the other *what*. ADR-0100 §6 reserved this ground by name — "The
    axis is *whom*, not *what*. A belief about a company, a project, a device or a
    topic states no subject" — so the field occupies ground the corpus explicitly
    left empty. **The two are never read for each other**, no validator ties them,
    and a record may carry both, either or neither (ADR-0213 §14). Four rules
    govern it:

    * **Proposed once, at write, by the record's own producer** (§4). No consumer,
      surface, store, retrieval path, scheduler job, migration or later ADR derives
      a record's topics at read time, and none derives them from ``content``, from
      a rendered facet, from a composed reply or from any other span of content
      after the write. Exactly one producer proposes any:
      ``ConsolidationStage`` (§6, narrowed by ADR-0285 §1). Every other writes
      the empty tuple, and no producer labels a record another producer wrote.
    * **Empty means "no topic was recorded"** (§7). Not "about nothing" and not
      "about everything". No consumer reads an empty tuple as matching a
      topic-scoped query, and none reads it as excluded from a query naming no
      topic: an act reaches a record if and only if the record carries the label
      the act names. A surface performing such an act owes the owner the
      disclosure that unlabelled records were not reached, and that the act's reach
      is the labels recorded rather than the subject they have in mind.
    * **Set once, revised by two routes** (§8). A fold takes the **union** of both
      sides — a label the target carried is never dropped, which is ADR-0106 §4's
      ratchet in this currency — and the owner's own act (§9) writes at the
      record's id. A ``SUPERSEDE`` carries nothing across. Nothing else revises
      them: no re-observation, retrieval, re-embedding, reconciliation, scheduler
      job, migration or backfill.
    * **Not a retrieval axis, not a tier, not a sensitivity, not a subject and not
      an identifier** (§14). A label carries no posture, no permission, no band and
      no disclosure consequence, and no read here filters on it. Each is stated as
      a prohibition rather than left as an omission because each is a plausible next
      step a lane could take without noticing it was a decision.

    **``revision`` is the store's concurrency token** (ADR-0219 §1), and it is the
    one field on this envelope no producer authors. A store issues it for the write
    that stored the row; a submitted value is discarded and never persisted, so a
    record a caller constructed carries the default ``0`` and a record a store
    returned carries the stamp that row held when the read observed it. Four rules
    govern it:

    * **Store-authored, never producer-set** (§1). ``add`` and every
      :class:`MemoryWrite` element discard whatever ``revision`` the record they are
      handed carries. No producer, applier, policy, writer or client sets one, and
      no implementation reads a submitted one for any purpose.
    * **Never reissued within the store** (§1). Every write that stores a row —
      ``add`` and each of ``write_atomic``'s modes alike — stamps it with a value
      that store has never issued and will never issue again, whatever id it is
      stored at and whatever was stored there before. It is not a per-id count, and
      a row stored again at a deleted id takes a fresh stamp rather than resuming
      one. ``0`` is issued by no store and every issued value is positive, so a
      caller-constructed default can never equal a stored value.
    * **Compared, never ordered** (§1). The operative property is *inequality*: two
      records carry equal revisions only where they are the same stored row,
      unrewritten, between the two reads that observed them. No caller compares two
      with ``<``, infers an interval, an age or a count from them, or derives which
      of two writes happened first. That an implementation reaches never-reissued by
      counting is mechanism, not promise.
    * **Read back from every record-returning read** (§1). ``get``, ``get_many``,
      ``search``, ``list_beliefs``, ``export`` and ``walk_records`` all return the
      revision the store holds for the row.

    **Placed here rather than on** :class:`Provenance`, by ADR-0045 §2's own rule:
    ``Provenance``'s every field is set by the *producer* of the belief, and this is
    a property of the record's life in the store. It is the mirror image of
    ``score`` — supplied by the machinery on one path, meaningless on the other.

    **``placement`` is the *to whom* axis** (ADR-0217 §1), and it lands here by the
    same ADR-0100 §2 test the two above land by. *Who may receive this record* is
    not a fact about the material the producer saw — which is what
    :class:`Provenance` answers — but a fact about the record's disposition, and it
    belongs to the family this envelope already holds: **about whom**
    (``about_person``), **about what** (``topics``), **for how long**
    (``expires_at``, ``validity``), and now **to whom**. ADR-0045 §2's authorship
    argument agrees, and where the question test and the authorship test agree the
    placement is not close: a placement the owner revises after the fact, on a
    record already in the store, is exactly the shape that section put ``validity``
    here for.

    **It carries the question ADR-0204 put on ``Provenance``, widened rather than
    replaced** (ADR-0217 §1). ``Provenance.supplied_withheld_content`` is removed and
    this field answers what it answered: a record ADR-0204 §2's evaluation or §5's
    inheritance would have stamped ``True`` is written reach ``OWNER`` with setter
    ``DERIVED``, and one it would have stamped ``False`` carries the default. Every
    record ADR-0204 caused to be withheld is withheld after ADR-0217, on the same
    evidence, at the same site, by the same producer; what changed is that two
    further setters may write the same slot and that the slot is no longer a
    boolean. ADR-0210 §1's narrowed evaluation set is untouched by the move.

    **A record already in a store is decoded, never defaulted**
    (:meth:`_decode_legacy_withheld_mark`, ADR-0217 §9). Without that mapping every
    record ADR-0204 narrowed would decode as unnarrowed on the day the field landed
    — ADR-0204 §1's fourth clause hazard, a decode default read as a measurement,
    with a disclosure consequence.
    """

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
    about_person: NonBlankEncodableText | None = Field(
        default=None,
        description=(
            "Whom this belief is about, when that is someone other than the owner "
            "(ADR-0100 §2). None means no subject is stated, which is read as the "
            "owner's. A label as given, resolving to nothing (§6)."
        ),
    )
    topics: Annotated[tuple[TopicLabel, ...], AfterValidator(_strictly_increasing_topics)] = Field(
        default=(),
        description=(
            "What this record is about, as canonical labels proposed at write "
            "(ADR-0213 §4). Empty means no topic was recorded, which is neither "
            "'no topic' nor 'every topic' (§7). Strictly increasing by code point "
            "(§1). No record this system installs carries more than "
            "MAX_TOPICS_PER_RECORD labels; the bound is enforced at the "
            "MemoryWriter seam and not here, so a longer tuple is admissible and "
            "a record stored with one stays readable (§1)."
        ),
    )
    revision: int = Field(
        default=0,
        ge=0,
        description=(
            "The store's concurrency token for this row: the stamp issued for the "
            "write that stored it (ADR-0219 §1). Store-authored — a submitted value "
            "is discarded — never reissued within a store, and 0 on a record no "
            "store has stored. Compared for equality only, never ordered."
        ),
    )
    placement: Placement = Field(
        default_factory=Placement,
        description=(
            "Who may receive this record (ADR-0217 §1), and who narrowed it. "
            "Defaults to reach ANYONE with no setter, which is ADR-0199 §3's own "
            "placement of the record's class and subtracts nothing (§6). A record "
            "whose reach is OWNER is withheld from a channel of unbounded audience "
            "wherever in a turn's supply it stood, and from a bounded channel "
            "nothing is withheld on this field's account (§2)."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _decode_legacy_withheld_mark(cls, data: Any) -> Any:
        """Decode a record written before ``placement`` existed (ADR-0217 §9).

        ``provenance.supplied_withheld_content`` of ``true``, on a record carrying no
        placement of its own, decodes to reach ``OWNER`` with setter ``DERIVED`` and
        **no** ``set_at`` — nothing timed an act that predates the field, and §1
        reads that absence as *unknown* rather than as recent. ``false`` or absent
        decodes to the default. The mapping is **total and one-directional**: it
        never writes the legacy member back, never widens a placement a record
        already carries, and never maps a ``false`` onto anything.

        **Here rather than in a migration pass**, because §9 puts it "wherever a
        record carrying the legacy member is decoded" and names the load-bearing site
        as the persistent store, which holds records written under ADR-0204 and is
        read on the first turn after the upgrade. A validator on this envelope is
        that site and the wire both, in one place, with no store rewritten before it
        is read. :class:`Provenance` does not set ``extra="forbid"``, so the member
        itself is dropped by the decode that follows.

        Args:
            data: Whatever is being validated — a mapping on the decode path, and
                anything else (a constructed model, most often) on the paths this
                rule has nothing to say about.

        Returns:
            ``data``, with the decoded placement added where the legacy member
            called for one.
        """
        if not isinstance(data, Mapping) or "placement" in data:
            return data
        provenance = data.get("provenance")
        if not isinstance(provenance, Mapping) or not provenance.get(
            "supplied_withheld_content", False
        ):
            return data
        return {
            **data,
            "placement": Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED),
        }


# --- memory: how an episode's turn was captured (ADR-0221) --------------------


class Modality(StrEnum):
    """How material reached this system (ADR-0221 §5).

    Two members as ADR-0221 ships it, and a vocabulary that is **added to and never
    renamed** (§5): a later decision admitting a further input modality adds a
    member; no member of it is renamed, removed or given a second spelling, and no
    later ADR replaces this enum with a differently-named one for the same question.
    §2's rule on serialised values binds here too — both values are fixed by
    ADR-0221 and no later lane changes them, and a member added later takes a value
    of the same form, the member name lower-cased.

    **This enum names a modality and nothing more.** *Whose* material a value
    belongs to, and what may not be read off it, are :attr:`Capture.modality`'s to
    state, and §5 is where both are decided.
    """

    TEXT = "text"
    """The material did not reach this system as speech: true of a typed turn, and
    true of an episode carrying no user material at all (§5). The default."""

    SPEECH = "speech"
    """The material reached this system as speech, and the text standing for it in
    the record is a derivation of that speech (§5)."""


class Capture(BaseModel):
    """How the user material an episode renders reached this system (ADR-0221 §5).

    **A record rather than a bare field, and the shape is the decision.** A two-valued
    flag would have to be *superseded* the day a second modality arrives, and it has
    nowhere to put the two facts a later archive decision needs. A record grows by
    addition; a field does not. It carries one field as ADR-0221 ships it, and it is
    on :class:`EpisodicMemory` alone and not on :class:`MemoryBase` (§5).

    §5's meaning is **quoted rather than restated**, because three lanes restating
    one rule is how the two drift apart:

        ``modality`` names how **the material the user supplied, whose rendering
        this episode carries**, reached this system — and nothing else. ``SPEECH``
        says it reached this system as speech and that the text standing for it in
        the record is a derivation of that speech. ``TEXT`` is the default and says
        it did not: true of a typed turn, and true of an episode carrying no user
        material at all.

        ``modality`` says nothing about the assistant's own contributions to the
        record, and no consumer reads it as saying anything about them. The plan
        rationale rendered into ``content`` and the composed reply in ``outcome``
        are text this system produced on every pass, whatever the utterance's
        modality, and this ADR records no modality for either.

        The value belongs to **the user material the episode renders**, not to the
        pass that performs the capture and not to the conversation. Every capture
        site falls in exactly one of the three cases below, and no implementation,
        setting or later lane adds a fourth without the ADR that decides it.

    **The three capture cases are decided in §5, and a producer reads them there**
    rather than here. The one worth naming in this docstring is the one a capture
    site gets wrong by defaulting: on the resolution of a parked step, the value is
    *the parked turn's own*, "retained with the parked turn and applied unchanged.
    No implementation re-evaluates, recomputes or defaults it at the second capture"
    (§5) — never the resuming pass's.

    **This record is where §5's two deferred facts land**, and neither is decided by
    ADR-0221: which derivation produced the text, and whether and where the source
    material is retained. Each is "an additive, defaulted field a later ADR adds to
    this record; adding one supersedes no clause of this ADR, and this ADR names
    neither field's type, spelling nor semantics" (§5). Neither ships as a
    ``None``-only slot, on ADR-0073 §4's standing test: neither has a producer in
    hand, and one of the two is blocked behind a ``core/protocols.py`` change.

    **Nothing here retains source material, authorises retaining it, or is cited
    toward doing so** (§5). ADR-0200 §8's clause that no audio is written to any
    store, index, trace, audit trail, routing trail, outbox or log stands whole.
    """

    model_config = ConfigDict(frozen=True)

    modality: Modality = Field(
        default=Modality.TEXT,
        description=(
            "How the material the user supplied, whose rendering this episode "
            "carries, reached this system — and nothing else (ADR-0221 §5). "
            "SPEECH says it reached this system as speech and that the text "
            "standing for it in the record is a derivation of that speech; TEXT "
            "is the default and says it did not, which is true of a typed turn "
            "and true of an episode carrying no user material at all. It says "
            "nothing about the assistant's own contributions — not the plan "
            "rationale in content, not the composed reply in outcome — and no "
            "consumer reads it as though it did."
        ),
    )


# Channel envelope dependencies precede episode records (ADR-0275).
class SpokenAudioFormat(StrEnum):
    """A container-and-codec one recording or rendering is carried in (ADR-0200 §9).

    **A closed vocabulary of IANA media types a browser can produce with
    ``MediaRecorder`` without transcoding**, which is what ties the two members
    to a measurement rather than to taste: between them they cover the browsers
    milestone 19's exit test can be run on. ADR-0200 §9 permits a lane to add a
    member "only on a measurement it records"; removing one is a change to what
    was decided and takes a superseding ADR.

    **It carries no sample rate, no channel count, no bitrate and no duration.**
    The first three are stated by the container, and a second answer to a
    question the payload already answers is the redundancy ADR-0084 §3 refuses. A
    duration would be worse than redundant: the hub cannot verify one without
    decoding the audio, so a declared duration is an unverified claim — which is
    why ADR-0200 §6's bound is on bytes, the thing a hub can measure.

    **The string value is the media type itself**, parameters included, so a
    value that reaches an HTTP header or a ``MediaRecorder`` constructor is the
    member rather than a mapping of it. ``"audio/webm;codecs=opus"`` carries its
    codec parameter for the reason ``MediaRecorder`` requires one: ``audio/webm``
    alone names a container two codecs can fill, and a transcriber that decoded
    only Opus would be declaring support for recordings it cannot read.
    """

    WEBM_OPUS = "audio/webm;codecs=opus"
    MP4 = "audio/mp4"


class ChannelIdentity(BaseModel):
    """A channel policy and its source-local instance identifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["channel"] = "channel"
    channel_type: Identifier
    instance_id: Identifier


class NewConversation(BaseModel):
    """Request a conversation identifier allocated by the store."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["new_conversation"] = "new_conversation"


class ChannelContextItem(BaseModel):
    """Supplied channel-local text or a reference; neither grants authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: NonBlankEncodableText | None = None
    item_id: Identifier | None = None
    source: NonBlankEncodableText | None = None

    @model_validator(mode="after")
    def _has_content(self) -> Self:
        if self.text is None and self.item_id is None:
            msg = "a channel context item requires text or an item identifier"
            raise ValueError(msg)
        return self


class ChannelContext(BaseModel):
    """Optional local history and replied-to material, in supplied order."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    history: tuple[ChannelContextItem, ...] = ()
    reply_to: ChannelContextItem | None = None

    @model_validator(mode="after")
    def _history_has_text(self) -> Self:
        if any(item.text is None for item in self.history):
            msg = "each channel history item requires text"
            raise ValueError(msg)
        return self


class WholeTextReply(BaseModel):
    """Return a whole textual outcome on the originating request."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["whole_text"] = "whole_text"


class StreamingTextReply(BaseModel):
    """Stream textual chunks and the final result on the originating request.

    **A recorded value and no longer an offered one.** ADR-0293 §11 retired
    ``receive_streaming`` and ``converse_streaming``, which offered it, so no entry
    point admits it; it stays a member of :data:`ReplyCapability` because a
    :class:`RecordedChannelTrigger` an episode already holds may carry it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["streaming_text"] = "streaming_text"


class SpokenReply(BaseModel):
    """Speak using the caller's nonempty format preference order."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["spoken"] = "spoken"
    plays: tuple[SpokenAudioFormat, ...] = Field(min_length=1)


ChannelTarget = Annotated[ChannelIdentity | NewConversation, Field(discriminator="kind")]


ReplyCapability = Annotated[
    WholeTextReply | StreamingTextReply | SpokenReply, Field(discriminator="kind")
]


# --- post-processing activation records (ADR-0275) -------------------------


class ProcessingStatus(StrEnum):
    """How one admitted processing pass ended, independently of goal success.

    ``waiting`` left with the old path's parks and questions (ADR-0318 §5:1), a
    recorded exception to *added to and never renamed*: the data directory is fresh,
    so nothing stored names it (§5:5).
    """

    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ProcessingReason(StrEnum):
    """Code-owned reasons for the terminal processing classification.

    ``confirmation``, ``clarification``, ``disambiguation`` and ``composition_failed``
    left with the old path that produced them (ADR-0318 §5:1), a recorded exception
    to *added to and never renamed*: the data directory is fresh (§5:5).
    """

    RETURNED = "returned"
    NO_CONTENT = "no_content"
    TIMEOUT = "timeout"
    TRANSCRIPTION_FAILED = "transcription_failed"
    UNDERSTANDING_FAILED = "understanding_failed"
    OUTPUT_OVERSIZED = "output_oversized"
    PROCESSING_FAILED = "processing_failed"
    INTERNAL_ERROR = "internal_error"
    CANCELLED = "cancelled"
    HUB_STOPPED = "hub_stopped"
    """The process ended while the pass was open, and a restart closed its episode
    (ADR-0286 §7). It is paired with :attr:`ProcessingStatus.INTERRUPTED` and with
    the end entry's :attr:`ControllerRule.HUB_STOPPED`, and says nothing about how
    far processing got: nothing recorded when it stopped."""
    STOPPED = "stopped"
    """The user stopped the activation (ADR-0297 §4, ADR-0295 §3). It is paired with
    :attr:`ProcessingStatus.INTERRUPTED` and with the end entry's
    :attr:`ControllerRule.STOPPED`, and it is classified ahead of every other row of
    ADR-0275 §5:3's table, a cancellation's included: a pass the user stopped is
    told apart from a crash, a restart and an interruption."""


class RecordedTextInput(BaseModel):
    """Exact admitted text, separate from its processing rendering."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    modality: Literal[Modality.TEXT] = Modality.TEXT
    text: EncodableText


class RecordedSpeechInput(BaseModel):
    """A recording's format and transcript, with no retained audio."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    modality: Literal[Modality.SPEECH] = Modality.SPEECH
    media_type: SpokenAudioFormat
    transcript: EncodableText | None


RecordedChannelPayload = Annotated[
    RecordedTextInput | RecordedSpeechInput, Field(discriminator="modality")
]


class InputOrigin(StrEnum):
    """Who an activation's input came from (ADR-0284 §2:1).

    A **closed** enumeration, **added to and never renamed**. Admission sets it on
    the recorded trigger from what the channel declares about its input, and the
    value is fixed on the episode (§2:2). A reader that needs to know who the input
    came from reads it, and never the channel type (§2:3).

    It is not :attr:`Provenance.derived_from_external`: that says whether processing
    read material resting on external content, this says who sent the input, and
    no renderer derives one from the other (§8:4).
    """

    USER = "user"
    """The user's own words, typed or spoken."""

    OUTSIDE = "outside"
    """Something the world reported, never something the user said."""


class RecordedChannelTrigger(BaseModel):
    """One admitted channel envelope after transient audio has been discarded.

    It records how the input arrived (ADR-0284 §3): the target, the channel it
    resolved to, the payload, its context, the reply capability it was offered, and
    ``origin``, who the input came from (§2), set at admission from the channel's
    declaration and fixed on the episode.

    **It checks no combination per channel type** (§3:2). Which payloads, reply
    shapes and options a channel accepts is checked at admission, by
    :mod:`ai_assistant.core.channel_validation`'s one dispatch table; the trigger
    holds only that, where its target is a :class:`ChannelIdentity` and its
    ``channel`` is set, the two are equal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["channel_input"] = "channel_input"
    target: ChannelTarget
    channel: ChannelIdentity | None
    payload: RecordedChannelPayload
    context: ChannelContext
    reply: ReplyCapability | None
    origin: InputOrigin

    @model_validator(mode="after")
    def _channel_is_the_target(self) -> Self:
        # ADR-0284 §3:2: the one rule the trigger itself holds.
        if (
            isinstance(self.target, ChannelIdentity)
            and self.channel is not None
            and self.channel != self.target
        ):
            msg = "a recorded trigger's channel is its target where the target names one"
            raise ValueError(msg)
        return self


# --- frozen JSON, and the identifier primitive (ADR-0014 §2) -----------------
# Declared here, ahead of the episode record, because ADR-0307 §10 records a
# planning round's calls with the episode, and a call's arguments are frozen JSON.
# The block used to sit with the planning types far below; the rule above
# :data:`Identifier` decides the move — a forward reference plus ``model_rebuild``
# would have made a `core` type depend on an import-order side effect, so the block
# moved instead of the model. Relocating a type is not redefining it (ADR-0084 §4):
# nothing in it changed.
#
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


_MAX_JSON_DEPTH: Final = 128
"""How deeply a :data:`FrozenJson` value may nest containers (ADR-0196 §3).

One constant in ``core``, applied to every :data:`FrozenJson` value alike: not
configurable, not per-holder, and **never derived from**
``sys.getrecursionlimit()``. What a shared ingress accepts has to be a fact about
the type rather than about the process, or two processes reading the same store
disagree about whether a persisted record is loadable (ADR-0196 §3, ADR-0145 §2
clause (b)).

Counted in the vocabulary of :func:`_json_depth`, in which a scalar is depth 0
and ``{}`` is depth 1. The number sits between two bounds and the room between
them is why it is a judgement rather than a derivation: it must exceed
:data:`_MAX_SCHEMA_DEPTH` strictly, so that ADR-0145 §6's own refusal stays
reachable for a schema between the two (ADR-0196 §4), and it must sit well below
the tightest mechanism that walks such a value — 255 containers, where a model
holding one stops serialising. Tool schemas and tool arguments here nest well
under ten containers, so the ceiling is headroom rather than a bound anyone meets.

Before this constant existed the acceptance set was decided by pydantic-core's
own cycle detector: an unpinned upstream number, undocumented here, asserted by
no test, and one that moves with the interpreter's recursion limit.
"""


def _canonical_children(value: object) -> list[object] | None:
    """Return ``value``'s children, or ``None`` if it is not a container.

    "Children" means *the contents validation will use*, obtained without
    invoking any method the value's type could have overridden — which is what
    ADR-0196 §1's third clause requires of the front measurement and what makes
    the set below so narrow:

    - **any ``dict``, subclass included, read through ``dict.values``.** A
      subclass is safe here and only here, because pydantic-core enumerates any
      dict instance through the concrete ``dict`` too, so the two agree by
      construction. A subclass whose own ``values()`` raises, or returns nothing,
      is measured on what it really holds.
    - **exactly ``list``, ``tuple`` and :class:`FrozenDict`** — subclasses
      refused rather than measured. :class:`FrozenDict` looks safe and is not: a
      subclass whose concrete ``_items`` holds one pair while its ``items()``,
      ``keys()`` and ``__getitem__`` report a 201-container mapping validates to
      depth 201, because pydantic reads it through the mapping protocol, which is
      the half a subclass can rewrite. There is no concrete access that makes the
      two agree, so the only faithful answer for a non-``dict`` mapping is the
      exact type; ``list`` and ``tuple`` are held to the same rule at no cost,
      since nothing in ``core`` produces a subclass of either.

    A ``str`` is a leaf, and so are ``bytes`` and ``bytearray``: pydantic
    validates all three against the ``str`` member of :data:`FrozenJson` — it
    never enumerates them as sequences — so reading them as containers would be
    unfaithful in the other direction.
    """
    if isinstance(value, dict):
        return list(dict.values(value))
    if type(value) is list or type(value) is tuple:
        return list(value)
    if type(value) is FrozenDict:
        return [item for _key, item in value._items]
    return None


def _presents_as_container(value: object) -> bool:
    """Whether ``value`` offers itself as a JSON container of some other kind.

    Everything :func:`_canonical_children` cannot read the way validation will —
    a custom :class:`~collections.abc.Mapping`, a :class:`FrozenDict`, ``list``
    or ``tuple`` subclass — but which still presents as a mapping or a non-``str``
    sequence. ADR-0196 §1 refuses these rather than measuring them on an
    enumeration they supplied themselves.
    """
    if isinstance(value, Mapping):
        return True
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _faithful_json_depth(value: object, limit: int) -> int | None:
    """Return how deeply ``value`` nests containers, or ``None`` if it cannot be read.

    Breadth-first with an explicit frontier, stopping once past ``limit``: the
    measurement allocates no Python stack frame per level, so it holds at any
    ``sys.getrecursionlimit()`` and completes before anything recursive is
    entered (ADR-0196 §2).

    ``None`` means ``value``, or something nested in it, presents as a mapping or
    a non-``str`` sequence whose contents cannot be obtained the way validation
    will obtain them. Guessing at such a value is what lets an input choose the
    depth it is measured at, so it is reported as unmeasurable rather than
    measured — and reported by a **return** rather than by an exception, so that
    :func:`_refuse_deep_json` can treat every exception raised anywhere in here as
    foreign (see its own note).
    """
    depth = 0
    frontier: list[object] = [value]
    while frontier and depth <= limit:
        children: list[object] = []
        holds_container = False
        for item in frontier:
            nested = _canonical_children(item)
            if nested is not None:
                holds_container = True
                children.extend(nested)
            elif _presents_as_container(item):
                return None
        if not holds_container:
            break
        depth += 1
        frontier = children
    return depth


def _refuse_deep_json(value: object, measure: Callable[[object, int], int | None]) -> None:
    """Refuse ``value`` if ``measure`` finds it nested past :data:`_MAX_JSON_DEPTH`.

    The refusal is a plain ``ValueError`` and not a named error, for the reason
    ADR-0196 §1 gives: the two refusals already on this ingress are plain
    ``ValueError`` refusals, pydantic turns each into a ``ValidationError`` on the
    field, and every holder already handles that. A named error would give
    callers a second shape to catch for a refusal they already catch.

    **No ``Exception`` other than one of these three refusals escapes a
    measurement**, which is stronger than "no exception other than a
    ``ValueError``" and is what §1's fourth clause needs. A measurement touches
    caller-controlled code at exactly one point — ``isinstance`` against
    :class:`~collections.abc.Mapping` and :class:`~collections.abc.Sequence`
    reads the instance's ``__class__``, which a hostile value can make raise —
    and re-raising a ``ValueError`` raised there would let a foreign one
    through. That is not academic: an exception whose own ``__str__`` raises
    escapes as *that* exception when pydantic renders the error, so a
    ``RuntimeError`` arrives out of a validator. Hence a constant message and no
    interpolation of anything the value supplied. The original is kept as
    ``__cause__``, where nothing renders it.

    A ``BaseException`` propagates unchanged, as everywhere else in this
    repository (ADR-0029 §3).

    Raises:
        ValueError: If ``value`` nests past the ceiling, if its contents cannot be
            read the way validation reads them, or if measuring it raised.
    """
    try:
        depth = measure(value, _MAX_JSON_DEPTH)
    except Exception as exc:
        msg = "this value's nesting depth could not be measured, so it cannot be stored"
        raise ValueError(msg) from exc
    if depth is None:
        msg = (
            "this value nests a mapping or sequence whose contents cannot be read "
            "the way they are validated, so its nesting depth cannot be measured"
        )
        raise ValueError(msg)
    if depth > _MAX_JSON_DEPTH:
        msg = (
            f"this value nests containers deeper than {_MAX_JSON_DEPTH}, "
            "so it cannot be stored or exported"
        )
        raise ValueError(msg)


def _depth_bounded_json(value: object) -> object:
    """Return ``value`` unchanged unless it nests past the ceiling (ADR-0196 §1).

    The front half of the ceiling, and a ``BeforeValidator`` rather than an
    ``AfterValidator`` for one reason: pydantic-core validates the recursive
    :data:`FrozenJson` alias *before* an ``AfterValidator`` runs, and that walk
    costs Python stack per level. A check placed after it would hold only for a
    range of ``sys.getrecursionlimit()`` — set the limit under the ceiling and
    the alias refuses first, with 1276 errors headed "Input should be a valid
    string" about a value whose only defect is its depth. Running first is what
    makes the refusal independent of a process-global.
    """
    _refuse_deep_json(value, _faithful_json_depth)
    return value


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
    - **a value nested past :data:`_MAX_JSON_DEPTH`**, measured here a second
      time (ADR-0196 §1). :func:`_depth_bounded_json` has already measured the
      *raw* input ahead of everything else; this one measures the **validated**
      structure, in which nothing can lie about its own depth because pydantic
      built it out of plain containers. Two positions, two jobs: the front one
      is what makes the refusal independent of ``sys.getrecursionlimit()``, and
      this one is defence in depth against the front's canonical set falling
      behind a pydantic version that built a container form it measured as a
      leaf. One constant, checked twice;
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
        ValueError: If the value nests past :data:`_MAX_JSON_DEPTH`, if a
            non-finite float is present, or if the frozen value has no JSON
            encoding.
    """
    _refuse_deep_json(value, _json_depth)
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
    FrozenJson,
    BeforeValidator(_depth_bounded_json),
    AfterValidator(_freeze_json),
    PlainSerializer(_thaw_json),
]
"""A single :data:`FrozenJson` value, frozen on validation and thawed on dump."""

type FrozenJsonMapping = Annotated[
    Mapping[str, FrozenJson],
    BeforeValidator(_depth_bounded_json),
    AfterValidator(_freeze_json),
    PlainSerializer(_thaw_json),
]
"""A string-keyed mapping of :data:`FrozenJson` values, frozen on validation."""

_EMPTY_PARAMS: Mapping[str, FrozenJson] = FrozenDict()


# --- a story's member (ADR-0289 §2) ------------------------------------------
#
# Declared here, ahead of :class:`ActivationUnderstanding`, because ADR-0300 §6:7
# records an understanding's story links as story members. They used to sit in the
# stories section far below; the rule above :data:`Identifier` decides the move — a
# forward reference plus ``model_rebuild`` would have made a `core` type depend on
# an import-order side effect, so the two types moved instead of the model.
# Relocating a type is not redefining it (ADR-0084 §4): nothing about either changed.


class StoryMemberKind(StrEnum):
    """Which of the two kinds of thing a story member is (ADR-0289 §2).

    A **closed** enumeration: members are activations' episodes and other stories,
    and nothing else. The kind is carried with the id and never inferred from it.
    """

    ACTIVATION = "activation"
    """An activation, named by its activation id; its episode is the record at
    ``activation:<activation_id>``."""

    STORY = "story"
    """Another story, named by its story id: a smaller matter inside a larger one."""


class StoryMember(BaseModel):
    """One member of a story: its kind and its id, carried together (ADR-0289 §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: StoryMemberKind
    id: Identifier


# --- activation understanding (ADR-0276) -------------------------------------


class UnderstandingGround(StrEnum):
    """How an element of an activation's understanding came to be known (ADR-0276 §2).

    A **closed** enumeration, **added to and never renamed** on :class:`Ground`'s
    own rule (ADR-0249 §1): no later ADR removes a member, renames one, gives one a
    second spelling, or replaces this enum with a differently named one for the
    same question.
    """

    STATED = "stated"
    """The input says it."""

    SUPPLIED = "supplied"
    """A supplied item the reading names says it."""

    INFERRED = "inferred"
    """Neither: the understanding stage judged it."""


class UnderstandingOmission(StrEnum):
    """Why a processing record carries no understanding (ADR-0276 §2, §5, §6).

    Closed and never renamed, on :class:`UnderstandingGround`'s rule. ``routed`` and
    ``no_input`` left with the route and the resume they classified (ADR-0318 §5:4),
    a recorded exception to that rule: the data directory is fresh (§5:5).
    """

    NO_TEXT = "no_text"
    """Speech yielded no words, or transcription failed."""

    FAILED = "failed"
    """The understanding stage raised."""

    NOT_REACHED = "not_reached"
    """The pass ended before the stage was entered for any other reason."""


class UnderstandingProducer(StrEnum):
    """Which stage recorded a version of an understanding (ADR-0276 §2).

    One member because ADR-0276 ships one producer; a later decision adds members
    rather than reusing this one. Closed and never renamed, on
    :class:`UnderstandingGround`'s rule.
    """

    INTERPRETATION = "interpretation"
    """The understanding stage of ADR-0276."""


class ProposedReference(BaseModel):
    """A phrase in the input and the labels the model says it refers to."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    phrase: NonBlankEncodableText
    labels: tuple[EncodableText, ...] = ()


class ProposedRelationship(BaseModel):
    """A relationship the model states, with the labels it rests on and its ground."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    statement: NonBlankEncodableText
    labels: tuple[EncodableText, ...] = ()
    ground: UnderstandingGround


class UnresolvedMatter(BaseModel):
    """Something the understanding could not settle and why that matters."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    matter: NonBlankEncodableText
    why_it_matters: NonBlankEncodableText


class ProposedActivationUnderstanding(BaseModel):
    """What the model produces, and the whole of what it produces (ADR-0276 §2).

    It carries **no identifier, no timestamp, no version and no producer**: a label
    is a string of ADR-0276 §3's scheme, meaningful only within the call that
    rendered it. A ``supplied`` ground with no label is a grounding defect the
    stage repairs and then records as ``inferred`` (§6), never a parse failure —
    so this type validates nothing about it.

    ``story_labels`` (ADR-0300 §6:6) are the labels of the candidate stories, and of
    earlier episodes, that the input belongs with as one matter. A label naming
    nothing a story link can be made from is a label defect the stage repairs and
    then drops (§6:8), so this type validates nothing about them either.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    meaning: NonBlankEncodableText
    meaning_ground: UnderstandingGround
    meaning_labels: tuple[EncodableText, ...] = ()
    references: tuple[ProposedReference, ...] = ()
    relationships: tuple[ProposedRelationship, ...] = ()
    unresolved: tuple[UnresolvedMatter, ...] = ()
    story_labels: tuple[EncodableText, ...] = ()


#: ADR-0276 §2: an excerpt is a bounded prefix of the referent's rendered text.
UNDERSTANDING_REFERENT_EXCERPT_CHARS: Final[int] = 240


class UnderstandingReferent(BaseModel):
    """What a label resolved to, intelligible after restart from these fields alone.

    ``id`` is an :data:`EncodableText` and not an :data:`Identifier` because an
    episode's ``id`` is carried **exactly as stored** (ADR-0275 §10), a blank or
    whitespace-distinct address included; nothing resolves it on read, and a
    dangling ``id`` is an ordinary state (ADR-0276 §2).

    ``story`` (ADR-0304 §8) names the matter an ``S`` label stands for: ``id`` the
    story's id as the story store gave it, ``source`` the text ``story``, and
    ``excerpt`` the first line of its summary as its short view rendered it, or empty
    where the view rendered none. A story since merged is a dangling ``id`` like any
    other, and a record written before the kind validates unchanged.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["input", "channel_item", "episode", "memory", "story"]
    id: EncodableText | None = None
    source: NonBlankEncodableText | None = None
    excerpt: EncodableText = Field(max_length=UNDERSTANDING_REFERENT_EXCERPT_CHARS)


class UnderstandingReference(BaseModel):
    """A phrase and the referents its labels resolved to."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    phrase: NonBlankEncodableText
    referents: tuple[UnderstandingReferent, ...] = ()


class UnderstandingRelationship(BaseModel):
    """A stated relationship, the referents it rests on and its ground.

    ``supplied`` names its source: the enclosing :class:`ActivationUnderstanding`
    refuses a ``supplied`` relationship whose ``referents`` are empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    statement: NonBlankEncodableText
    referents: tuple[UnderstandingReferent, ...] = ()
    ground: UnderstandingGround


class ActivationUnderstanding(BaseModel):
    """One recorded version of what the assistant understood an activation to mean.

    The recorded form of :class:`ProposedActivationUnderstanding` (ADR-0276 §2):
    ``orchestration`` assigns ``version``, ``recorded_at`` and ``producer``,
    resolves every label into an :class:`UnderstandingReferent`, and copies the
    texts and grounds unchanged. It carries no goal id, no attempt id, no plan id
    and no label, and it crosses no model-facing seam under ADR-0276. It grants no
    authority and establishes no fact; it is what the assistant understood.

    ``story_links`` (ADR-0300 §6:7) are the matters the input was understood to
    belong to, in proposal order with no member twice: a candidate story as a story
    member, and an earlier episode as its activation. A link says the input belongs
    to that matter and nothing more; the story-links stage records it in the story
    store (§6:12), and a record written before the field validates unchanged
    (§12:1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: int = Field(strict=True, ge=1, lt=2**31)
    recorded_at: UtcInstant
    producer: UnderstandingProducer
    meaning: NonBlankEncodableText
    meaning_ground: UnderstandingGround
    meaning_referents: tuple[UnderstandingReferent, ...] = ()
    references: tuple[UnderstandingReference, ...] = ()
    relationships: tuple[UnderstandingRelationship, ...] = ()
    unresolved: tuple[UnresolvedMatter, ...] = ()
    grounding_dropped: int = Field(default=0, strict=True, ge=0, lt=2**31)
    story_links: tuple[StoryMember, ...] = ()

    @model_validator(mode="after")
    def _no_story_link_twice(self) -> Self:
        if len(set(self.story_links)) != len(self.story_links):
            msg = "an understanding links to each story member at most once (ADR-0300 §6:7)"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _supplied_names_its_source(self) -> Self:
        if self.meaning_ground is UnderstandingGround.SUPPLIED and not self.meaning_referents:
            msg = "a supplied meaning names at least one referent"
            raise ValueError(msg)
        if any(
            relationship.ground is UnderstandingGround.SUPPLIED and not relationship.referents
            for relationship in self.relationships
        ):
            msg = "a supplied relationship names at least one referent"
            raise ValueError(msg)
        return self


class ControllerStage(StrEnum):
    """A unit of processing the activation controller runs (ADR-0280 §4).

    Closed, **added to and never renamed**. A stage is not a phase: the two do
    not map one to one (ADR-0280 §1). :attr:`END` names the record's final entry,
    which ran nothing. The old path's stages left at the cutover (ADR-0309 §3:6), a
    recorded exception to that rule: the data directory is fresh, so nothing stored
    names them.
    """

    BEGIN_CONVERSATION = "begin_conversation"
    UNDERSTANDING = "understanding"
    END = "end"
    RECALL = "recall"
    WINDOWS = "windows"
    STORY_LINKS = "story_links"
    """Record the understanding's story links in the story store (ADR-0300 §6:10)."""
    PLANNING = "planning"
    """One planning round: one model response, recorded with the episode (ADR-0307 §2,
    §10)."""
    AUTHORIZING = "authorizing"
    """Every call of the latest round checked by rule, and its message by its place
    (ADR-0306 §4, ADR-0309 §3:2)."""
    ACTING = "acting"
    """The latest round's allowed calls run, claimed and recorded, and its message
    written (ADR-0306 §5, ADR-0309 §3:2)."""
    DIGESTING = "digesting"
    """Outside text read for planning as marked evidence, beside acting (ADR-0308 §4:5,
    ADR-0309 §3:3)."""


class ControllerRule(StrEnum):
    """Why a stage was due, or why the pass ended (ADR-0280 §2, §4, §5).

    Closed, **added to and never renamed**. The members in
    :data:`ENDING_CONTROLLER_RULES` end a pass; every other member makes a stage
    due. The old path's rules left at the cutover (ADR-0309 §3:6), a recorded
    exception to that rule: the data directory is fresh, so nothing stored names
    them.
    """

    CONVERSATION_UNRESOLVED = "conversation_unresolved"
    NOT_UNDERSTOOD = "not_understood"
    NOTHING_DUE = "nothing_due"
    STAGE_REPEATED = "stage_repeated"
    NO_TEXT_INPUT = "no_text_input"
    STAGE_FAILED = "stage_failed"
    STAGE_TIMED_OUT = "stage_timed_out"
    INTERRUPTED = "interrupted"
    ENDED_BEFORE_CONTROLLER = "ended_before_controller"
    NOT_RECALLED = "not_recalled"
    WINDOWS_UNASSEMBLED = "windows_unassembled"
    HUB_STOPPED = "hub_stopped"
    """The process ended while the pass was open, and a restart's close appended the
    end entry (ADR-0286 §7). It ends a pass, so it is in
    :data:`ENDING_CONTROLLER_RULES`."""
    STOPPED = "stopped"
    """The user stopped the activation (ADR-0297 §4): the end entry of a stop, which
    ADR-0295 §3:1 added and left unnamed. Appended where ``interrupted`` would be
    (ADR-0280 §5:3, §5:4) for a pass whose stop mark is set. It ends a pass, so it is
    in :data:`ENDING_CONTROLLER_RULES`."""
    STORY_LINKS_UNRECORDED = "story_links_unrecorded"
    """The story-links stage is wired, the understanding outcome is a recorded
    version, and there is no story-links decision (ADR-0300 §6:11): ``story_links``
    is due. It makes a stage due, so it is not among the ending rules."""
    FIRST_ROUND_DUE = "first_round_due"
    """Understanding has recorded and no planning round has run (ADR-0307 §8:6,
    ADR-0309 §3): ``planning`` is due."""
    ROUND_UNAUTHORIZED = "round_unauthorized"
    """The latest round has a call or text, and there is no authorizing decision for
    it (ADR-0309 §3): ``authorizing`` is due."""
    ROUND_AUTHORIZED = "round_authorized"
    """The latest round's authorizing decision allows a call or its message, and there
    is no acting decision for that round (ADR-0309 §3): ``acting`` is due, with
    ``digesting`` beside it (§3:3)."""
    ROUND_LIMIT_REACHED = "round_limit_reached"
    """Another round would be due, and the round limit has been reached (ADR-0307 §8:4,
    ADR-0309 §3). It ends a pass, so it is in :data:`ENDING_CONTROLLER_RULES`."""
    ROUND_DUE = "round_due"
    """The latest round made a call other than a tidy-up, and every call of it has
    finished, whatever its calls brought back (ADR-0315 §2:1): ``planning`` is due."""
    UNDERSTOOD_NOT_RECALLED = "understood_not_recalled"
    """An understanding is recorded on the pass and there is no second-run decision
    (ADR-0308 §2:9, ADR-0309 §3): ``recall`` is due, its second run."""
    RECALL_UNDIGESTED = "recall_undigested"
    """The second-run decision is made, either run kept a memory record whose source is
    outside, and there is no recall digest (ADR-0308 §4:5, ADR-0309 §3):
    ``digesting`` is due, for recall's digest."""


#: The rules that end a pass rather than make a stage due (ADR-0280 §4, §5).
ENDING_CONTROLLER_RULES: Final[frozenset[ControllerRule]] = frozenset(
    {
        ControllerRule.NOTHING_DUE,
        ControllerRule.STAGE_REPEATED,
        ControllerRule.NO_TEXT_INPUT,
        ControllerRule.STAGE_FAILED,
        ControllerRule.STAGE_TIMED_OUT,
        ControllerRule.INTERRUPTED,
        ControllerRule.ENDED_BEFORE_CONTROLLER,
        ControllerRule.HUB_STOPPED,
        ControllerRule.STOPPED,
        ControllerRule.ROUND_LIMIT_REACHED,
    }
)


class StageOutcome(StrEnum):
    """How a stage the controller ran ended (ADR-0280 §5).

    A serializable classification only: the error a failed stage raised never
    enters a :class:`StageEntry`.
    """

    DONE = "done"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class StageEntry(BaseModel):
    """One choice the activation controller made (ADR-0280 §6).

    It names which stage ran, the rule that made it due and how it ended, or, for
    the final :attr:`ControllerStage.END` entry, the rule that ended the pass. It
    carries no stage result (ADR-0280 §6:3): the two verdicts the old path's
    ``drive`` and ``routing`` stages recorded left with those stages (ADR-0309 §3:7).
    Every result stays where the episode already keeps it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    stage: ControllerStage
    due: ControllerRule
    started_at: UtcInstant
    ended_at: UtcInstant
    outcome: StageOutcome

    @model_validator(mode="after")
    def _end_entry_is_an_ending(self) -> Self:
        ending = self.due in ENDING_CONTROLLER_RULES
        if (self.stage is ControllerStage.END) != ending:
            msg = "the end entry, and only it, is due to a rule that ends the pass"
            raise ValueError(msg)
        if self.stage is ControllerStage.END and (
            self.outcome is not StageOutcome.DONE or self.started_at != self.ended_at
        ):
            msg = "an end entry records outcome done at one instant"
            raise ValueError(msg)
        return self


class RecallOutcome(StrEnum):
    """What recall's decision was (ADR-0281 §6).

    Closed, **added to and never renamed**. A recall that kept nothing, failed or
    ran out of its own budget is still a decision, distinct from one never made.
    """

    FOUND = "found"
    NOTHING_FOUND = "nothing_found"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class RecallCue(StrEnum):
    """What recall searched with (ADR-0281 §3, §6).

    Closed, **added to and never renamed**. The first run's one cue, and the second
    run's two kinds (ADR-0308 §2:2, §7); later sources, such as candidate stories, add
    members rather than reshape the record.
    """

    ACTIVATION_INPUT = "activation_input"
    UNDERSTOOD_MEANING = "understood_meaning"
    """Recall's second run, cued by the latest understanding's ``meaning`` (ADR-0308 §2:2)."""
    UNDERSTOOD_PHRASE = "understood_phrase"
    """Recall's second run, cued by the ``phrase`` of one of the latest understanding's
    ``references``, resolved or not (ADR-0308 §2:2)."""


class RecallProvenance(StrEnum):
    """Recall's basic provenance label for a kept record (ADR-0281 §4).

    Closed, **added to and never renamed**. It is not the record's structured
    origin, which :class:`RecalledItem` carries separately as stored: an
    informational event's episode is ``outside`` while its
    ``derived_from_external`` is ``False`` (ADR-0275 §9).
    """

    USER = "user"
    OUTSIDE = "outside"


#: ADR-0281 §6: the type's ceiling on a recall result's items. It sits above the
#: composition root's ``RECALL_ITEM_LIMIT`` so that later sources add to the same
#: record without a change to this type.
RECALLED_ITEMS_MAX: Final[int] = 16

_RECALLABLE_KINDS: Final[frozenset[MemoryKind]] = frozenset(
    {MemoryKind.EPISODIC, MemoryKind.SEMANTIC}
)


class RecalledItem(BaseModel):
    """One long-term memory recall kept for an activation (ADR-0281 §6).

    Readable after restart, and after the memory itself is deleted, from these
    fields alone. ``id`` is the record's stored ``MemoryBase.id`` exactly as
    stored, an :data:`EncodableText` for the reason :class:`UnderstandingReferent`
    gives. ``standing``, ``rests_on_recorded_external_content`` and
    ``attestation`` are the record's structured origin as it holds them, which
    ADR-0189 §1 requires of a projection shown to the owner.

    ``stories`` are the stories the item's episode belongs to directly, in the order
    the story store returned them (ADR-0300 §7:2). A semantic item carries none,
    enforced here. It defaults to empty, so a record written before it validates
    unchanged (§12:1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: MemoryKind
    id: EncodableText
    excerpt: EncodableText = Field(max_length=UNDERSTANDING_REFERENT_EXCERPT_CHARS)
    provenance: RecallProvenance
    standing: BeliefBand
    rests_on_recorded_external_content: bool
    attestation: Attestation | None = None
    found_by: tuple[RecallCue, ...] = Field(min_length=1)
    stories: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _recallable_kind(self) -> Self:
        if self.kind not in _RECALLABLE_KINDS:
            msg = "recall keeps episodic and semantic records only"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _no_stories_on_a_semantic_item(self) -> Self:
        # ADR-0300 §7:2: only an episode belongs to a story.
        if self.kind is MemoryKind.SEMANTIC and self.stories:
            msg = "a semantic item carries no stories"
            raise ValueError(msg)
        return self


class ActivationRecall(BaseModel):
    """What recall found for one activation, or why it found nothing (ADR-0281 §6).

    ``items`` is non-empty exactly when ``outcome`` is ``found``: a recall that
    kept nothing says ``nothing_found``, and one that failed or timed out says so
    rather than reporting an empty success.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    outcome: RecallOutcome
    cues: tuple[RecallCue, ...] = Field(min_length=1)
    items: tuple[RecalledItem, ...] = Field(default=(), max_length=RECALLED_ITEMS_MAX)

    @model_validator(mode="after")
    def _items_exactly_when_found(self) -> Self:
        if bool(self.items) != (self.outcome is RecallOutcome.FOUND):
            msg = "a recall result carries items exactly when its outcome is found"
            raise ValueError(msg)
        return self


# --- planning's round (ADR-0307 §2, §5, §10) -----------------------------------
#
# What a planning round asks a model for and what it gets back, in the provider's
# native tool-calling shape, and what the episode keeps of it. Declared here, ahead
# of :class:`EpisodeProcessingRecord`, which records the rounds and the labels.


class OfferedTool(BaseModel):
    """One capability as a planning round offers it to the model (ADR-0307 §10).

    The capability's ``name`` and ``description``, and ``parameters``, its JSON
    schema with ADR-0306 §2:9's added arguments. It is what
    :meth:`~ai_assistant.core.protocols.ToolCallingCompleter.respond` hands the
    provider as a native tool, and nothing about who may run it.

    Raises:
        ValueError: If ``parameters`` is not a JSON schema of an object, the one shape
            a native tool's arguments take.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Identifier
    description: NonBlankEncodableText
    parameters: FrozenJsonMapping

    @model_validator(mode="after")
    def _an_object_schema(self) -> Self:
        if self.parameters.get("type") != "object":
            msg = "an offered tool's parameters are the JSON schema of an object"
            raise ValueError(msg)
        return self


class ProposedCall(BaseModel):
    """One call a planning round proposed, as the provider returned it (ADR-0307 §10).

    ``call_id`` is the provider's id for the call, ``name`` the capability it names,
    and ``arguments`` the JSON object it carries. Nothing here says the name was
    offered or the arguments fit its schema: planning and authorizing judge that.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    call_id: Identifier
    name: NonBlankEncodableText
    arguments: FrozenJsonMapping = Field(default_factory=FrozenDict, validate_default=True)


def _distinct_call_ids(calls: tuple[ProposedCall, ...]) -> None:
    """Refuse two calls of one response under one provider id."""
    ids = [call.call_id for call in calls]
    if len(set(ids)) != len(ids):
        msg = "a round's calls carry distinct call ids"
        raise ValueError(msg)


class RoundResponse(BaseModel):
    """One model response of a planning round, in its three parts (ADR-0315 §3:1).

    ``text`` is the round's message, possibly empty; ``calls`` the calls it proposes;
    and ``notes`` its episode notes, or ``None`` where it wrote none. The notes are a
    part of the response and never a call (§3:2, §3:3). No part asks for a round: the
    controller's rule alone decides whether one runs (§2, §3:4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: EncodableText = Field(default="", validate_default=True)
    calls: tuple[ProposedCall, ...] = ()
    notes: NonBlankEncodableText | None = None

    @model_validator(mode="after")
    def _calls_distinct(self) -> Self:
        _distinct_call_ids(self.calls)
        return self


class LabelKind(StrEnum):
    """What a planning label names (ADR-0307 §5:1).

    Closed, **added to and never renamed**. Episode notes take no label.
    """

    STORY = "story"
    EPISODE = "episode"
    NOTE = "note"
    MEMORY = "memory"
    RESULT = "result"


#: Each kind's label prefix (ADR-0307 §5:1): S1…, E1…, N1…, M1… and R1….
_LABEL_PREFIXES: Final[dict[LabelKind, str]] = {
    LabelKind.STORY: "S",
    LabelKind.EPISODE: "E",
    LabelKind.NOTE: "N",
    LabelKind.MEMORY: "M",
    LabelKind.RESULT: "R",
}

_LABEL_SHAPE: Final = re.compile(r"[SENMR][1-9][0-9]{0,8}")


def label_prefix(kind: LabelKind) -> str:
    """The prefix a label of ``kind`` carries (ADR-0307 §5:1).

    Args:
        kind: What the label names.

    Returns:
        ``S``, ``E``, ``N``, ``M`` or ``R``.
    """
    return _LABEL_PREFIXES[kind]


class PlanningLabel(BaseModel):
    """One label planning was shown, and the id it names (ADR-0307 §5:2, §5:7).

    ``label`` is its kind's prefix and a decimal number with no padding. ``id`` is
    the thing's id exactly as held, never normalised, and an :data:`EncodableText`
    rather than an :data:`Identifier` for :class:`UnderstandingReferent`'s reason: an
    episode's id is carried exactly as stored, a blank or whitespace-distinct address
    included (ADR-0275 §10).

    Raises:
        ValueError: If ``label`` is not of that shape, or its prefix is not its
            kind's.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    label: EncodableText
    kind: LabelKind
    id: EncodableText

    @model_validator(mode="after")
    def _the_kinds_label(self) -> Self:
        if _LABEL_SHAPE.fullmatch(self.label) is None:
            msg = "a planning label is a kind's prefix and a number with no padding"
            raise ValueError(msg)
        if self.label[0] != _LABEL_PREFIXES[self.kind]:
            msg = "a planning label carries its kind's prefix"
            raise ValueError(msg)
        return self


class PlanningRound(BaseModel):
    """One planning round as the episode records it (ADR-0307 §2:3, §10).

    Its ``id``; ``follows``, the round before it, or ``None`` for the first;
    ``recorded_at``; the three parts of its :class:`RoundResponse` (ADR-0315 §5), the
    calls as proposed, labels and all; and ``notes_marked``, which the hub sets where the
    activation had read outside content when the notes were written (ADR-0307 §4:3,
    ADR-0303 §3:1), never from the model's output. A round is never edited.

    Raises:
        ValueError: If it follows itself, marks notes it does not carry, or carries
            two calls under one id.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: Identifier
    follows: Identifier | None = None
    recorded_at: UtcInstant
    text: EncodableText = Field(default="", validate_default=True)
    calls: tuple[ProposedCall, ...] = ()
    notes: NonBlankEncodableText | None = None
    notes_marked: bool = False

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if self.follows == self.id:
            msg = "a round follows the round before it, never itself"
            raise ValueError(msg)
        if self.notes_marked and self.notes is None:
            msg = "only a round carrying notes marks them"
            raise ValueError(msg)
        _distinct_call_ids(self.calls)
        return self


# --- digesting's evidence (ADR-0308 §4, §5, §7) --------------------------------
#
# A digest is one tool-less model call over a result's outside records that answers
# one question with a list of marked evidence, which is all of that content planning
# ever sees. Declared here, ahead of :class:`EpisodeProcessingRecord`, which records
# the digests.


class EvidenceItem(BaseModel):
    """One item of a digest's evidence (ADR-0308 §5:1).

    Its ``text``; ``source``, the planning label of the record it rests on (§4:15),
    which names a thing only in the activation that recorded it; and ``outside``, the
    mark that it came from outside content, which is always set. Nothing more.

    Raises:
        ValueError: If ``source`` is not a planning label's shape.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: NonBlankEncodableText
    source: EncodableText
    outside: Literal[True] = True

    @model_validator(mode="after")
    def _a_label(self) -> Self:
        if _LABEL_SHAPE.fullmatch(self.source) is None:
            msg = "an evidence item's source is a planning label"
            raise ValueError(msg)
        return self


class DigestOutcome(StrEnum):
    """What came of one digest (ADR-0308 §7).

    Closed, **added to and never renamed**. A digest that found nothing answering its
    question has ``answered``, with no evidence (§4:8).
    """

    ANSWERED = "answered"
    FAILED = "failed"


class ActivationDigest(BaseModel):
    """One digest, as the episode records it (ADR-0308 §5:2, §7).

    ``result`` is the R label of the result digested, or ``None`` for recall's digest;
    ``question`` what the digest answered; ``outcome`` whether it answered; ``evidence``
    its items, in part order, empty where it failed (§4:12); and ``recorded_at``. A
    digest is never edited.

    Raises:
        ValueError: If ``result`` is not a result's label, or a failed digest carries
            evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    result: EncodableText | None = None
    question: NonBlankEncodableText
    outcome: DigestOutcome
    evidence: tuple[EvidenceItem, ...] = ()
    recorded_at: UtcInstant

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if self.result is not None and (
            _LABEL_SHAPE.fullmatch(self.result) is None
            or self.result[0] != _LABEL_PREFIXES[LabelKind.RESULT]
        ):
            msg = "a digest names the result it read by its R label"
            raise ValueError(msg)
        if self.outcome is DigestOutcome.FAILED and self.evidence:
            msg = "a failed digest records no evidence"
            raise ValueError(msg)
        return self


class EpisodeProcessingRecord(BaseModel):
    """The facts about one activation's processing, open while it runs (ADR-0286 §1).

    A record is **open** while its ``status`` is ``None`` and **frozen** once it is
    set; ``status``, ``reason`` and ``ended_at`` are all ``None`` or all set. An open
    record's stages carry no end entry and it carries no ``understanding_omitted``. A
    frozen record ends its stages in exactly one end entry, last, and carries exactly
    one of a non-empty understanding and an omission. Openness is read off
    ``status``, never off the absence of an end entry (ADR-0280 §6:2).

    A frozen record is immutable. An open one is replaced only by a record that
    extends it, which :func:`~ai_assistant.core.episode_encoding.episode_extends`
    decides (ADR-0286 §3).

    ``rounds`` are planning's rounds, oldest first, each naming the one before it, and
    ``labels`` the labels planning was shown, each naming one thing and each thing
    named once, in the order they were assigned (ADR-0307 §2:3, §5:7). ``digests`` are
    the activation's digests, in the order they were recorded (ADR-0308 §5:2). All
    three are appended to as the episode is extended and default to empty.

    ``recall_second_run`` is recall's second decision, made on what understanding
    found (ADR-0308 §2, §7), held beside the first's ``recall``. It is ``None`` where
    no second run was decided.

    ``schema_version`` is 11 because the record loses the old path's links, resume
    trigger and compose-stage degradation, and its stages their verdicts (ADR-0318
    §4, §5:3, §7:1; ADR-0309 §3:7): a version-10 record carries them and does not
    validate here.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[11] = 11
    activation_id: Identifier
    started_at: UtcInstant
    ended_at: UtcInstant | None = None
    trigger: RecordedChannelTrigger
    status: ProcessingStatus | None = None
    reason: ProcessingReason | None = None
    output_degraded: bool = False
    understanding: tuple[ActivationUnderstanding, ...] = ()
    understanding_omitted: UnderstandingOmission | None = None
    understanding_elided: int = Field(default=0, strict=True, ge=0, lt=2**31)
    stages: tuple[StageEntry, ...] = ()
    stages_elided: int = Field(default=0, strict=True, ge=0, lt=2**31)
    recall: ActivationRecall | None = None
    rounds: tuple[PlanningRound, ...] = ()
    labels: tuple[PlanningLabel, ...] = ()
    digests: tuple[ActivationDigest, ...] = ()
    recall_second_run: ActivationRecall | None = None

    @property
    def is_open(self) -> bool:
        """Whether the record is open: its pass has not ended (ADR-0286 §1)."""
        return self.status is None

    @model_validator(mode="after")
    def _rounds_follow_each_other(self) -> Self:
        # ADR-0307 §2:3: each round names the round it follows; the first follows none.
        previous: str | None = None
        for one in self.rounds:
            if one.follows != previous:
                msg = "each round follows the round recorded before it, and the first none"
                raise ValueError(msg)
            previous = one.id
        if len({one.id for one in self.rounds}) != len(self.rounds):
            msg = "a processing record's rounds carry distinct ids"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _one_label_one_thing(self) -> Self:
        # ADR-0307 §5:1: each thing gets one label, which holds for the whole activation.
        if len({one.label for one in self.labels}) != len(self.labels):
            msg = "a label names one thing"
            raise ValueError(msg)
        if len({(one.kind, one.id) for one in self.labels}) != len(self.labels):
            msg = "a thing takes one label"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _open_or_frozen(self) -> Self:
        # ADR-0286 §1: all three are None while open, and all three are set once frozen.
        unset = [field is None for field in (self.status, self.reason, self.ended_at)]
        if any(unset) and not all(unset):
            msg = "a processing record sets its status, reason and end time together"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _understood_or_omitted(self) -> Self:
        # ADR-0286 §1: an open record carries no omission; ADR-0276 §7: a frozen one
        # carries exactly one of a non-empty history and an omission value.
        if self.is_open:
            if self.understanding_omitted is not None:
                msg = "an open processing record carries no understanding omission"
                raise ValueError(msg)
        elif bool(self.understanding) == (self.understanding_omitted is not None):
            msg = "a processing record carries either its understanding or why it has none"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _stages_follow_the_trigger(self) -> Self:
        # ADR-0280 §7: an activation records its stages ending in exactly one end entry,
        # last. ADR-0286 §1: an open record's stages carry no end entry.
        ends = [entry.stage is ControllerStage.END for entry in self.stages]
        if self.is_open:
            if any(ends):
                msg = "an open stage record carries no end entry"
                raise ValueError(msg)
        elif not ends or not ends[-1] or any(ends[:-1]):
            msg = "a stage record ends in exactly one end entry, last"
            raise ValueError(msg)
        return self


class EpisodeCaptureReport(BaseModel):
    """Capture durability, independent of the processing outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    activation_id: Identifier | None
    episode_id: Identifier | None
    state: Literal["recorded", "degraded"]

    @model_validator(mode="after")
    def _recorded_has_addresses(self) -> Self:
        if self.state == "recorded" and (self.activation_id is None or self.episode_id is None):
            msg = "a recorded capture requires both activation and episode identifiers"
            raise ValueError(msg)
        return self


class EpisodePosition(BaseModel):
    """A total-order position preserving the exact store address."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    occurred_at: UtcInstant
    episode_id: EncodableText


class EpisodeCursor(BaseModel):
    """The validated contents of a filter-bound opaque inspection cursor."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    after: EpisodePosition
    channel: ChannelIdentity | None
    status: ProcessingStatus | None


class EpisodeSummary(BaseModel):
    """A bounded inspection row; absent activation facts are never invented."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    position: EpisodePosition
    activation_id: Identifier | None
    channel: ChannelIdentity | None
    modality: Modality
    status: ProcessingStatus | None
    has_processing_record: bool


class EpisodePage(BaseModel):
    """A page of episode summaries and its optional continuation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[EpisodeSummary, ...]
    next_cursor: NonBlankEncodableText | None


class EpisodeChunk(BaseModel):
    """An ASCII-safe slice of canonical detail, bound to its content digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    episode_id: EncodableText
    version: NonBlankEncodableText
    offset: int = Field(strict=True, ge=0, lt=2**63)
    text: EncodableText
    next_offset: int | None = Field(strict=True, ge=0, lt=2**63)
    total_bytes: int = Field(strict=True, ge=0, lt=2**63)


class EpisodicMemory(MemoryBase):
    """Something that happened: an event, with who and how it turned out.

    ``processing_record`` (ADR-0275) records an activation: the experience of
    processing it (ADR-0284). Its absence supports other current producers.
    Fresh-state startup does not import historical records.

    With a processing record, ``outcome`` is the response — the text the activation
    sent back on its channel, nonblank, or ``None`` where it sent none (ADR-0284
    §4:1) — ``content`` is the search text one rule derives from the record (§7),
    and what became of a step or a route is on the stage entry that reached it
    (§5:2). ADR-0221 §2's ``disposition`` field is removed (§5:3).

    An episode is **open** or **frozen** as its processing record is (ADR-0286 §1).
    An open episode carries an empty ``content`` and reach ``OWNER`` with setter
    ``DERIVED``: the freezing write derives its search text and its placement.
    """

    kind: Literal["episodic"] = "episodic"
    occurred_at: UtcInstant
    participants: tuple[EncodableText, ...] = Field(default=())
    outcome: EncodableText | None = Field(
        default=None,
        description=(
            "What the assistant said, on a record this system captured after "
            "ADR-0221 §1: the composed reply, whole. No implementation, setting or "
            "later lane stores a prefix, a summary, an elision or any other lossy "
            "rendering of it here. On a record carrying a processing record it is "
            "the response the activation sent back on its channel, nonblank, or "
            "None where it sent none (ADR-0284 §4:1). A record carrying none may "
            "carry an assistant text a benchmark harness supplied, on a row it "
            "built (ADR-0221 §3)."
        ),
    )
    capture: Capture = Field(
        default_factory=Capture,
        description=(
            "How the user material this episode renders reached this system "
            "(ADR-0221 §5). Defaults to a Capture with every field at its default, "
            "whose modality is TEXT — true of a typed turn and true of an episode "
            "carrying no user material at all. It says nothing about the "
            "assistant's own contributions to the record, and no read returning "
            "records is filtered on it (§14)."
        ),
    )
    processing_record: EpisodeProcessingRecord | None = None
    importance: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _processing_response(self) -> Self:
        # ADR-0284 §4:1: the response is nonblank, or there is none.
        if (
            self.processing_record is not None
            and self.outcome is not None
            and not self.outcome.strip()
        ):
            msg = "a recorded response requires nonblank outcome text"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _open_episode_is_bare_and_owner_only(self) -> Self:
        # ADR-0286 §1, §6: until it freezes, an episode carries no search text and is
        # placed owner-only by derivation, whatever the evaluation will find.
        processing = self.processing_record
        if processing is None or not processing.is_open:
            return self
        if self.content:
            msg = "an open episode carries an empty content"
            raise ValueError(msg)
        if (
            self.placement.reach is not PlacementReach.OWNER
            or self.placement.set_by is not PlacementSetter.DERIVED
        ):
            msg = "an open episode is placed reach owner, set by derivation"
            raise ValueError(msg)
        return self


# --- the episode as a model is shown it (ADR-0284 §8) --------------------------


class ProjectedText(BaseModel):
    """A text cut to a projection's excerpt bound, carrying the length it was cut from.

    ADR-0284 §8:1 carries the cut in the projection. It is carried as the whole
    text's length rather than as a flag, because a site that applies its own, tighter
    ceiling afterwards (ADR-0222 §4) states how much it kept of how much (§5), and
    the projection is the only thing that still knows the second number.

    Attributes:
        text: A prefix of the whole text, at most the projection's ``excerpt_chars``
            characters long.
        full_chars: The whole text's length, in characters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: EncodableText
    full_chars: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def _a_prefix_of_the_whole(self) -> Self:
        if len(self.text) > self.full_chars:
            msg = "a projected text is no longer than the text it was cut from"
            raise ValueError(msg)
        return self

    @property
    def cut(self) -> bool:
        """Whether the excerpt bound cut the text."""
        return len(self.text) < self.full_chars


class ProjectedRound(BaseModel):
    """One planning round of an episode, as a model is shown it (ADR-0307 §10).

    The round's message and its episode notes, each cut to the projection's excerpt
    bound. ``notes`` is ``None`` where the round wrote none or the reader may not be
    shown them: episode notes are placed for the owner alone (ADR-0307 §4:4), and a
    later reader keeps that placement (ADR-0312 §4:3).

    Attributes:
        message: The round's text, where it wrote any: the message it wrote into its
            place, or the text kept in the episode where the place took none
            (ADR-0307 §3:8).
        notes: Its episode notes, where it wrote any and the reader may be shown them.
        notes_marked: Whether those notes rest on outside content (ADR-0307 §4:3).
            Never set without ``notes``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    message: ProjectedText | None = None
    notes: ProjectedText | None = None
    notes_marked: bool = False

    @model_validator(mode="after")
    def _marked_with_notes(self) -> Self:
        if self.notes_marked and self.notes is None:
            msg = "a projected round marks only notes it carries"
            raise ValueError(msg)
        if self.message is None and self.notes is None:
            msg = "a projected round shows its message, its notes or both"
            raise ValueError(msg)
        return self


class ProjectedEvidence(BaseModel):
    """One item of an episode's evidence, as a later reader is shown it (ADR-0308 §5:5).

    The item's text, cut to the projection's excerpt bound, and its mark. Never its
    source label, which names a thing only in the activation that recorded it.

    Attributes:
        text: What the item says.
        outside: The mark that it came from outside content, always set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: ProjectedText
    outside: Literal[True] = True


class EpisodeProjection(BaseModel):
    """What every model-facing rendering of a stored episode reads (ADR-0284 §8).

    :func:`~ai_assistant.core.episode_encoding.project_episode` is its one
    producer, and a renderer shows no other field of the episode it came from
    (§8:3). It is never stored and crosses no wire.

    **An episode with a processing record** carries its ``channel``, the trigger's
    ``origin``, its input text where ``origin`` is ``user`` (or ``outside``, for the
    two renderings that admit it, §8:5), the latest understanding's ``meaning``,
    ``meaning_ground`` and ``unresolved``, its ``status`` and ``reason``, and no stage
    verdict (ADR-0318 §3:1). **An episode without one** (§8:2) carries its
    ``capture_modality`` instead of a channel and its ``content`` as its input, and no
    origin, no understanding and no status; ``status`` is ``None`` exactly there.
    Both carry ``occurred_at``, ``response`` and ``derived_from_external``. Only an
    episode with a processing record carries ``rounds`` (ADR-0307 §10) and
    ``evidence`` (ADR-0308 §5:5).

    Attributes:
        occurred_at: When the episode happened.
        channel: The channel its trigger names, where it has a processing record.
        capture_modality: Its capture modality, where it has no processing record.
        origin: Who the trigger's input came from; ``None`` on an episode with no
            processing record.
        input: The input text or transcript, cut to the excerpt bound, or ``None``
            where none is shown.
        meaning: The latest understanding's meaning, or ``None`` where there is none.
        meaning_ground: Its ground, present exactly with ``meaning``.
        unresolved: The latest understanding's unresolved matters.
        response: What the episode records the assistant sent back (``outcome``),
            cut to the excerpt bound.
        status: How processing ended, or ``None`` where there is no processing record.
        reason: Why, present exactly with ``status``.
        derived_from_external: Whether processing read material resting on recorded
            external content, as :func:`rests_on_recorded_external_content` answers
            it of the episode's provenance (ADR-0106 §2). Not ``origin`` (§8:4).
        rounds: The episode's planning rounds that show a message or notes, in
            order, under the reader's audience (ADR-0307 §10).
        evidence: The items of the episode's digests, in the order they were
            recorded, where the reader may be shown a record placed for the owner
            alone (ADR-0308 §5:5 to §5:6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    occurred_at: UtcInstant
    channel: ChannelIdentity | None = None
    capture_modality: Modality | None = None
    origin: InputOrigin | None = None
    input: ProjectedText | None = None
    meaning: NonBlankEncodableText | None = None
    meaning_ground: UnderstandingGround | None = None
    unresolved: tuple[UnresolvedMatter, ...] = ()
    response: ProjectedText | None = None
    status: ProcessingStatus | None = None
    reason: ProcessingReason | None = None
    derived_from_external: bool = False
    rounds: tuple[ProjectedRound, ...] = ()
    evidence: tuple[ProjectedEvidence, ...] = ()

    @model_validator(mode="after")
    def _one_of_the_two_shapes(self) -> Self:
        if (self.status is None) != (self.reason is None):
            msg = "a projection carries a status exactly with its reason"
            raise ValueError(msg)
        if (self.meaning is None) != (self.meaning_ground is None):
            msg = "a projection carries a meaning exactly with its ground"
            raise ValueError(msg)
        if self.meaning is None and self.unresolved:
            msg = "a projection carries unresolved matters only with a meaning"
            raise ValueError(msg)
        if self.status is None:
            # §8:2: no origin, no understanding and no status.
            if (
                self.channel is not None
                or self.capture_modality is None
                or self.origin is not None
                or self.meaning is not None
                or self.rounds
                or self.evidence
            ):
                msg = "a projection without a processing record carries its content alone"
                raise ValueError(msg)
        elif self.capture_modality is not None:
            msg = "a projection with a processing record carries its channel, not a modality"
            raise ValueError(msg)
        return self

    @property
    def has_processing_record(self) -> bool:
        """Whether the episode had a processing record (§8:2's other path)."""
        return self.status is not None


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


# --- memory: a channel's episodes, in number order (ADR-0283 §1, §3) ---------

#: One past the largest episode number a store can issue: the signed 64-bit
#: ceiling a SQLite ``rowid`` tops out at (ADR-0283 §1).
_EPISODE_NUMBER_BOUND: Final = 2**63


class ChannelEpisode(BaseModel):
    """One episode with the number its store gave it (ADR-0283 §3:2, ADR-0286 §12:1).

    What :meth:`~ai_assistant.core.protocols.MemoryStore.channel_episodes` returns for
    a live episode on a channel, and what
    :meth:`~ai_assistant.core.protocols.MemoryStore.open_episodes` returns for an open
    episode, on a channel or none, live or not.

    Attributes:
        number: The store-wide number the episode was given when it was inserted —
            positive, greater than every number issued before it, never reissued and
            never changed (§1). A channel's order is its episodes' numbers.
        record: The episode, a detached snapshot like every ``MemoryStore`` read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    number: int = Field(strict=True, ge=1, lt=_EPISODE_NUMBER_BOUND)
    record: EpisodicMemory


class ChannelEpisodePage(BaseModel):
    """What one :meth:`~ai_assistant.core.protocols.MemoryStore.channel_episodes` returned.

    Attributes:
        entries: The page's episodes in number order, ascending (ADR-0283 §3:1).
        total: The count of every live episode on the channel, not the page's
            (§3:2; ADR-0284 §6:1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    entries: tuple[ChannelEpisode, ...]
    total: int = Field(strict=True, ge=0, lt=_EPISODE_NUMBER_BOUND)


class ChannelEpisodeId(BaseModel):
    """The number and id of one episode a store physically holds on a channel (ADR-0283 §3:5).

    Identifiers alone, never a record's content: it is what
    :meth:`~ai_assistant.core.protocols.MemoryStore.channel_episode_ids` returns, the
    enumeration a deletion walks.

    Attributes:
        number: The episode's store-wide number (§1).
        episode_id: The episode's id, its exact stored characters.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    number: int = Field(strict=True, ge=1, lt=_EPISODE_NUMBER_BOUND)
    episode_id: EncodableText


# --- memory: what one relevance read returned (ADR-0128 §2) ------------------


class MemorySearchResult(BaseModel):
    """What one :meth:`~ai_assistant.core.protocols.MemoryStore.search` returned.

    The ranked records, and one boolean saying whether the store's own candidate
    ceiling cut the read short (ADR-0128 §2). It exists because a bare list leaves
    a caller unable to tell a sparse answer from a truncated one — the silence
    issue #457 is about — and a return type that cannot be consumed without naming
    the field makes forgetting the signal a type error rather than a wrong answer.

    **One boolean and nothing else.** No exclusion count, no coverage estimate, no
    escalation hint: each would be an upper-layer quantity on a surface whose whole
    design invariant is that it stays mechanical, and each would be a number three
    implementations would have to agree on. ``capped`` has one meaning and two
    states, and :meth:`~ai_assistant.core.protocols.MemoryStore.search` enumerates
    both.

    Attributes:
        records: The matching records, most relevant first, each carrying its
            relevance ``score``. Detached snapshots, as with every ``MemoryStore``
            read.
        capped: Whether the store's own candidate ceiling bound the read. See
            :meth:`~ai_assistant.core.protocols.MemoryStore.search` for what each
            state certifies — the contract is stated there, once, because it is a
            statement about a *read* rather than about this container.
    """

    model_config = ConfigDict(frozen=True)

    records: tuple[MemoryRecord, ...]
    capped: bool = False


def caseless_key(label: str) -> str:
    """``label`` as ADR-0101 §2's subject comparison sees it: ``NFD(toCasefold(NFD(x)))``.

    **Unicode canonical caseless equality, definition D145**, and the one relation
    the corpus grants a person label. Two labels are canonically caseless-equal
    exactly when this function returns the same string for both, so a comparison
    is an equality of two keys and every implementation computes it identically —
    which is the whole reason ADR-0101 §3 took an external standard rather than a
    rule of its own devising.

    **Nothing else is applied.** No trimming, no diacritic stripping, no
    punctuation removal, no tokenising, splitting or truncation. ``"Marta"`` and
    ``"marta"`` share a key; ``"Marta"`` and ``"Márta"`` do not; ``"Straße"`` and
    ``"STRASSE"`` do, which is *full* case folding and not lowercasing; and
    ``"Márta"`` and the same name written with a combining acute do, which is the
    canonical equivalence the outer and inner ``NFD`` supply.

    **The inner ``NFD`` is not redundant with the outer one.** Case folding is
    defined over a decomposed form, and folding a composed string can leave a
    result the outer normalisation has to fix; applying it on both sides of the
    fold is what D145 specifies and what makes the composed and decomposed
    spellings of one name a single key.

    Defined in ``core`` rather than in each store because it is the *contract's*
    comparison and not one implementation's: ADR-0237 §3 applies it to both the
    ``about_person`` and the ``participants`` axis, on three implementations, and
    a fold that drifted between them would make the same call answer differently
    per backend. It is a pure function of the string handed in, so it is intrinsic
    to the types this module defines rather than subsystem logic (ADR-0016 §2).

    Args:
        label: The label to fold, exactly as it was given. Never mutated and never
            stripped: the value a caller passes reaches the comparison as it is.

    Returns:
        Its canonical caseless key. Equal keys mean canonically caseless-equal
        labels and nothing more — no resolution, no aliasing, no identity
        (ADR-0100 §6).
    """
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", label).casefold())


# --- memory: one write inside an atomic batch (ADR-0046 §2) ------------------


class MemoryWriteMode(StrEnum):
    """How one write in an atomic batch treats a colliding id (ADR-0046 §2).

    Two of the three are exactly what the supersession applier needs and no more:
    an ``UPSERT`` window-close of the retained target, and an
    ``INSERT_IF_ABSENT`` of the freshly-minted correction whose probabilistic id
    must not clobber an existing record (ADR-0045 §4).

    The third is the **conditional replacement** ADR-0219 §2 adds: ``IF_UNCHANGED``
    applies its record only where the id names a stored row still carrying the
    revision the caller read. Three modes and not a fourth — ``IF_UNCHANGED``
    requires the row present, ``INSERT_IF_ABSENT`` requires it absent and
    ``UPSERT`` requires nothing, so there is no gap an "insert-or-swap" would fill
    and no consumer that wants one (§2).
    """

    UPSERT = "upsert"
    """Overwrite the record if its id is present, insert it if absent.

    Reproduces :meth:`~ai_assistant.core.protocols.MemoryStore.add`'s upsert
    semantics — what a window-close is, since the target already exists and is
    overwritten with its retired form.

    A cross-kind collision is the one exception, and it is refused rather than
    overwritten (ADR-0108 §4): where the id names a stored record of a different
    ``kind``, nothing is written.
    :meth:`~ai_assistant.core.protocols.MemoryStore.write_atomic` carries the full
    statement. The sentence above stays true of a window-close, which writes the
    retired form of the very record it lands on and so is same-kind by
    construction.
    """

    INSERT_IF_ABSENT = "insert_if_absent"
    """Insert the record only if its id names no stored record.

    Otherwise the **whole batch** fails with
    :class:`~ai_assistant.core.errors.MemoryStoreConflictError` and nothing is
    committed. "Absent" is *physical presence*, not read-visibility: a stored row
    blocks the insert even when expired or window-closed (ADR-0046 §3).
    """

    IF_UNCHANGED = "if_unchanged"
    """Replace the stored record only if its ``revision`` is the one expected.

    A conditional replacement (ADR-0219 §2). The element carries the expectation on
    :attr:`MemoryWrite.expected_revision` — never read off the record's own
    ``revision`` — and it is applied only where the id names a stored row whose
    revision equals it. Otherwise the **whole batch** fails with
    :class:`~ai_assistant.core.errors.MemoryStoreStaleError` and nothing is
    committed, including where the id names **no** stored row at all: a row deleted
    between the caller's read and its write is a lost update, not a silent no-op
    (§3).

    "Names a stored row" is *physical presence*, in ``INSERT_IF_ABSENT``'s sense: an
    expired or window-closed row is present and its revision is the one compared, so
    a window-close can be made conditional (§4). The cross-kind refusal binds this
    door as it binds the other two (ADR-0108 §4).
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
    It now governs a second field whose absence changes the write's meaning
    (ADR-0219 §2), which is the same reason applied twice.

    **The expectation rides the element, not the record** (ADR-0219 §2). A caller
    assembling an ``IF_UNCHANGED`` write from a record it *built* — which is what a
    fold does — would carry :attr:`MemoryBase.revision`'s default of ``0`` and
    silently expect "never rewritten", a fail-open expectation on the exact path
    this mode guards. A separate field a validator requires makes that unreachable,
    and it is the ratified shape:
    :class:`~ai_assistant.core.types.ExecutionState` carries ``version`` and
    :class:`~ai_assistant.core.types.StepTransition` carries ``expected_version``
    for this reason.
    """

    model_config = ConfigDict(frozen=True)

    record: MemoryRecord
    mode: MemoryWriteMode = MemoryWriteMode.UPSERT
    expected_revision: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The revision of the record the caller read and computed this write "
            "against (ADR-0219 §2). Required in IF_UNCHANGED mode and refused in "
            "every other; None everywhere else."
        ),
    )

    @model_validator(mode="after")
    def _expectation_matches_the_mode(self) -> Self:
        """Refuse the two states neither of which is answerable at write time.

        An ``IF_UNCHANGED`` element with no expectation reaches a store with nothing
        to compare; a non-``IF_UNCHANGED`` element carrying one states a condition no
        mode honours. ADR-0219 §2 makes both construction-time refusals so the
        caller's mistake is diagnosable where it is made, rather than at a write that
        mysteriously always refuses — §1's reservation of ``0`` closes the first case
        a second time from the other side, and the two are stated as two because
        neither should be the only one.

        Raises:
            ValueError: If the mode and the expectation disagree.
        """
        conditional = self.mode is MemoryWriteMode.IF_UNCHANGED
        if conditional and self.expected_revision is None:
            msg = "an IF_UNCHANGED write must carry the expected_revision it was computed against"
            raise ValueError(msg)
        if not conditional and self.expected_revision is not None:
            msg = f"a {self.mode.value} write must not carry an expected_revision"
            raise ValueError(msg)
        return self


# --- memory: the resumable walk's position and its chunk (ADR-0114 §2) -------
# Two frozen models rather than a ``str`` alias and a tuple, for the reason
# :class:`MemoryWrite` is frozen: a value that governs whether records are
# *skipped* must not be reconstructible by accident from something that happens
# to be a string. A record id and a walk position are both text and mean
# entirely different things, and a seam accepting either accepts the wrong one
# silently.


class WalkPosition(BaseModel):
    """How far a named walk over a store has reached (ADR-0114 §2).

    **Opaque to its caller.** No caller may parse, order, compare,
    arithmetically derive, persist or synthesise one: the only admissible source
    is the :class:`RecordChunk` that carried it, and the only admissible use is
    passing it to
    :meth:`~ai_assistant.core.protocols.MemoryStore.advance_walk` for the walk it
    came from. The token is the *store's* own order key — a ``rowid`` in a SQLite
    store, an insertion index elsewhere — and nothing about that key is on a
    :data:`MemoryRecord`, so a caller deriving a position from a record it read
    would be inventing one. A caller that could compose a position could compose
    a wrong one, which silently skips every record at or below it and reports
    success while it happens (ADR-0104 §2).

    **A position is bound to the walk it was issued for**, and the store refuses
    one presented to a different walk (ADR-0114 §2). That is a check rather than
    an obligation because the store issued the token itself and holds the walk
    name in the same call, so refusing the mismatch costs it nothing. What the
    binding does **not** do is authenticate issuance: a well-formed token naming
    the right walk that no chunk read ever issued is a breach of opacity by the
    caller, and no implementation is obliged to detect one.

    **A position is a bound, not a reference.** Deleting, purging or retiring
    records below a recorded position does not disturb it — the position says
    where the walk has *reached*, and the next chunk is whatever the store now
    holds after it. That holds because a store never reissues a key it has
    already issued (ADR-0114 §1); without that guarantee the sentence would be
    false in the one case that matters.
    """

    model_config = ConfigDict(frozen=True)

    token: NonBlankEncodableText = Field(
        description="The store's opaque encoding of this position. Never parsed by a caller.",
    )


class RecordChunk(BaseModel):
    """One chunk of a resumable walk over a store (ADR-0114 §1).

    Carries the *eligible* records of the chunk together with the position of
    the last record the chunk **examined** — which are different sets, because
    the read's work is bounded by records examined rather than by records
    returned (ADR-0111 §4).

    **An absent ``position`` means the walk is exhausted, and nothing else.**
    That — never an empty ``records`` — is how a caller learns there was nothing
    left to examine. A chunk may legitimately carry a position and *no* records,
    meaning the range it examined held nothing eligible, and a caller advances on
    it exactly as on any other. Reading an empty ``records`` as exhaustion stops
    a walk short forever at the first dead range; re-reading without advancing
    rescans that range every run and never progresses.
    """

    model_config = ConfigDict(frozen=True)

    records: tuple[MemoryRecord, ...] = Field(
        default=(),
        description="The retained, live records among those this chunk examined, in walk order.",
    )
    position: WalkPosition | None = Field(
        default=None,
        description="Position of the last record examined; absent exactly when none was.",
    )


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
_FINGERPRINT_EXCLUDED_RECORD_FIELDS: frozenset[str] = frozenset({"id", "score", "topics"})

#: The serializer the proposal fingerprint's projection is taken by, resolved
#: once on the **declared** :data:`MemoryRecord` union and never reached through
#: ``self.proposed.model_dump``. That method is an ordinary attribute: a subclass
#: can override it and an instance can shadow it through ``__dict__``, and either
#: can return a valid-but-false mapping for the record it is asked about.
#: ``ai_assistant.orchestration.executor``, ``ai_assistant.permissions._detachment``
#: and :meth:`RecipientGrant._digest_projection` state that rule about that method
#: on a single class, resolving its ``__pydantic_serializer__``; a discriminated
#: union has no class to resolve it on, and this adapter is what stands in its
#: place — the union's own serializer, which reads the instance's field values and
#: consults no instance attribute.
_MEMORY_RECORD_PROJECTION: Final[TypeAdapter[MemoryRecord]] = TypeAdapter(MemoryRecord)


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

        **The projection is the whole record minus the fields that are
        bookkeeping about the record rather than the belief it states**, and the
        criterion decides the next one rather than an inventory having to be
        extended by whoever adds it — ``topics`` is the field it has since decided
        (ADR-0213 §10), which is the clause working rather than being amended:

        * ``id`` — identity, minted per proposal, so including it makes the key
          match nothing at all.
        * ``score`` — populated only by retrieval (ADR-0005 §1); it says how a
          search ranked something, not what is believed.
        * ``provenance.last_updated`` — **transaction time** (ADR-0045 §3): when
          the record was written, not what it says. Two identical observations a
          minute apart would otherwise be two questions, and the user would be
          nagged by the mechanism whose job is to stop that.
        * ``topics`` — how the record is **filed**, not what is believed
          (ADR-0213 §10). The owner asked to accept "you dislike early meetings" is
          being asked about the proposition, and whether the proposer filed it
          under ``"work"`` or ``"routine"`` is not part of the offer. The
          operational reason is ``last_updated``'s: a model-proposed label is not a
          deterministic function of the material, so re-observing it can yield
          ``("health",)`` on one pass and ``("health", "sleep")`` on the next, and
          including the field would mint a fresh question for a proposal the user
          has already answered, on a difference they were never shown. Excluding it
          is also what makes ADR-0213 §8's union reachable: if two labellings of one
          belief were two questions they would rarely reach a fold at all.

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

        Built in JSON mode rather than from the live objects, so a record
        reconstructed field-by-field from a serialised form projects identically
        to the one it was serialised from (ADR-0078 §10's parity clause) — the
        failure that clause guards is not a mismatch on some input but a mismatch
        on *every* input.

        **Serialised by :data:`_MEMORY_RECORD_PROJECTION`, the declared union's
        own serializer, never through ``self.proposed.model_dump``.** That method
        is an ordinary attribute, so an instance can shadow it through
        ``__dict__`` and a subclass can override it, and a record that nominates
        its own dump nominates its own fingerprint — which is a record able to
        collide with a question the user has already answered, or to escape one
        they have not. The projection is also taken under the *declared* type's
        field set rather than ``type(self.proposed)``'s, for the reason
        :func:`_detached_tool` rebuilds as a :class:`ToolDefinition` and not as
        ``type(value)``: a subclass's extra fields would otherwise be silently
        inside the digest's schema, so two records equal in everything
        :data:`MemoryRecord` declares would fingerprint apart. ``warnings=False``
        because serialising a subclass through the union's schema warns, and the
        warning is noise here.
        """
        record: dict[str, Any] = _MEMORY_RECORD_PROJECTION.dump_python(
            self.proposed, mode="json", warnings=False
        )
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
      records' ``evidence`` — up to :data:`MAX_EVIDENCE_CITATIONS`, beyond which
      the oldest are displaced and counted (ADR-0086 §3, partially superseding
      ADR-0040 §1's unqualified "both").
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


class ConflictRelation(StrEnum):
    """How a proposed record stands to **one named record** of the conflict set.

    ADR-0159 §1's vocabulary, and the input a policy reads before choosing a
    ruling. Exactly three values, and the middle one carries the finding the whole
    ADR rests on:

    - ``RESTATES`` — the proposed record says what the named record already says.
    - ``ADDS`` — the proposed record says something the named record does not say
      and does not deny. Two dated facts about one person's employment are this —
      neither a restatement nor a contradiction — and naming the case explicitly is
      what lets a policy do the correct thing with them, which is nothing at all.
    - ``CONTRADICTS`` — the two cannot both be true of the same subject at the
      same time.

    **A member for which no relation was determined is *unlabelled*, and that is
    the absence of a statement rather than a fourth value** (§1). It is never
    asserted, it supplies ground for nothing, and it deliberately has no name here:
    a name invites a rule written over it, at which point a reconciler failure
    starts changing rulings — which ADR-0159 §6 forbids.

    **A relation is a property of the two records' ``kind`` and ``content`` and of
    nothing else** (§1). Never a retrieval score, a rank, a :class:`Provenance`
    field, a band, a validity window or an embedding distance. A relation derived
    from any of those is not one, whatever it is called.

    **This is not a :class:`MemoryDecisionKind` and does not become one** (§1).
    ADR-0040 §1 fixed that a ruling "names the relation the policy asserts, never
    the write it causes"; this vocabulary sits one layer below that — a statement
    about a *pair of records*, made before any ruling exists. Two proposals with
    identical relations may still be ruled differently, by confidence, by the taint
    ceiling or by the secret gate, so collapsing the two would lose the distinction
    between what is true of the records and what we have decided to do.
    """

    RESTATES = "restates"
    ADDS = "adds"
    CONTRADICTS = "contradicts"


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


# --- context facets: a source's situational "right now" (ADR-0096) -----------
# Declared here, ahead of `SourceReading`, because a reading *carries* one (§5)
# and `CurrentContext` *receives* one (§1) — the two consumers of one read, at
# their own cadences (ADR-0093 §3). A facet is a third party's report read at an
# instant, so it carries its own provenance rather than being rendered beside
# `is_weekend` as a bare value: the temporal core is bare because a clock reading
# has no provenance to lose, and a facet has.


class ContextFacet(BaseModel):
    """One source's situational contribution, stamped with who said it and when.

    The base every non-temporal :class:`CurrentContext` facet extends (ADR-0096
    §1). It carries the source's identity and the two instants that say when its
    content was true, so a facet reaching a prompt can never be rendered as a bare
    fact of the system's own — which is the laundering ADR-0072 §6 refuses: "a
    wrong record laundered into a fact by flat prose, restated back to the user
    with the assistant's authority, and never questioned because it did not arrive
    looking questionable".

    **A base class rather than a convention**, because a convention here fails
    silently: a rule saying "every facet carries its source and its instants",
    held by review, lasts exactly until the tenth facet author does not read
    ADR-0096 — and the failure is a facet rendered as a bare value.
    ``tests/core/test_facet_coverage.py`` makes it a property of the file rather
    than of the fields someone remembered.

    **Never itself a field annotation** (ADR-0096 §1). Pydantic serialises by the
    *declared* annotation and says nothing when that loses data: a field annotated
    with this base but holding a :class:`CalendarFacet` dumps the three fields
    below and drops the payload, with no warning emitted at all. Every field
    carrying a facet — on :class:`CurrentContext`, on :class:`SourceReading`, or
    anywhere else — is annotated with concrete facet types.

    **``source``, ``read_at`` and ``as_of`` are reserved on every subclass.** Flat
    fields share one namespace with a subclass's payload, so a future facet whose
    own vocabulary includes "source" would shadow the stamp. The coverage test
    refuses the redefinition rather than a ``stamp:`` sub-object costing every
    consumer a second indirection.

    **Shaped after :class:`Attestation` and deliberately not reusing it.** The
    kinship is real — that is the corpus's answer to "who said so, and when" — and
    reuse fails on both its fields. ``reported_at`` is required and admits no
    substitute (ADR-0092 §3), so an ``Attestation`` on a calendar facet is
    unconstructable for the one producer that exists; and ``Attestation`` carries
    no our-clock field at all, because on a stored belief that role is
    :attr:`Provenance.last_updated` — which a facet, having no store and no
    transaction time, does not have.

    Attributes:
        source: The producing reading's ``source``, unchanged — the reader's
            declared, Tier 2 identity (ADR-0093 §7). It must never embed Tier 0/1
            data: a source that wraps personal data names *itself*
            (``"calendar"``), never the data it holds and never its location.
            Refused when blank and **never normalised**, so it stays byte-equal to
            the reading's own (see :data:`NonBlankEncodableText`).
        read_at: The instant **this system** performed the read this facet was
            built from. Always present, because it is our own clock and there is
            no source that can fail to supply it.
        as_of: The instant **the source itself declares** for that reading, and
            ``None`` where it declares none.

            **It may never be filled from the filesystem, from the clock, from
            ``read_at``, or from one entry's stamp applied to the rest**
            (ADR-0096 §2). The mtime is the specific temptation: a reader is
            usually looking at a *mirror*, and "when did the mirror last sync" has
            an answer sitting right there in ``st_mtime`` — which is the last
            local write, moving under a copy, a restore, an ``rsync`` preserving
            times, or a ``touch``. ADR-0092 §3 already refuses it for
            ``reported_at``, and a facet is a **weaker** record than a belief, not
            a stronger one, so it does not get a licence a belief is denied.

    **Staleness is computed by a consumer, never carried here** (ADR-0096 §3). No
    facet carries a staleness verdict — no boolean, no freshness class, no expiry
    — and no ``Settings`` figure defines when one becomes stale: a ``stale: bool``
    is not a description but a switch, and the first consumer to find it would use
    it to drop the facet, which is the one outcome the owner's ruling
    ("present-but-stale, understood from its source") forbids. A consumer computes
    two different figures: :attr:`CurrentContext.now` minus ``read_at`` is *how
    long ago we looked*, and ``now`` minus ``as_of`` — where the source declares
    one — is *how old the source says its picture is*.

    **Those two instants are captured independently within one concurrent
    assembly**, so their difference is bounded by that assembly's duration and
    **may be of either sign**: ``AssemblingContextProvider`` runs its sources as
    concurrent tasks, so a clock source stamps ``now`` when it runs while a reader
    stamps ``read_at`` at byte acquisition (ADR-0093 §7b). No consumer may present
    a negative age, and none may read the sign as information.
    """

    model_config = ConfigDict(frozen=True)

    source: NonBlankEncodableText = Field(
        description=(
            "The producing reading's declared identity, byte-for-byte — Tier 2, "
            "never a path and never the data it holds (ADR-0093 §7)."
        ),
    )
    read_at: UtcInstant = Field(
        description="When this system performed the read this facet was built from (tz-aware).",
    )
    as_of: UtcInstant | None = Field(
        default=None,
        description=(
            "Any reading-wide instant the source itself declares (tz-aware); None "
            "where it declares none. Never our clock and never the file's mtime."
        ),
    )


class CalendarFacet(ContextFacet):
    """What the calendar says is happening now and what is next (ADR-0096 §6).

    Three scalars and an instant. **It carries no entry text** — no summary,
    location, description, organiser, attendee or identifier, and no per-entry
    report time — and that is a decision twice over.

    The same read's *proposals* already carry the in-window occurrences into
    memory as ``ATTESTED`` beliefs, where retrieval surfaces them and ADR-0072 §5
    ranks them. Putting them here as well would ship the same content into the
    same prompt by two routes carrying two different stamps, which is precisely
    the "neither is mistaken for the other" hazard ADR-0093 §3 names — manufactured
    by us rather than found. And a calendar's titles and locations are the most
    disclosing thing it holds: ``CalendarReader`` already refuses ``DESCRIPTION``
    for a *durable* belief, and the advisory path does not get a weaker rule. The
    facet's job is the one thing the beliefs cannot answer at request time without
    a scan: *is something happening right now, and when is the next thing*.

    **A count rather than a boolean**, because ``busy: bool`` has to decide what
    counts as busy and the first case breaks it — an all-day "Holiday" covers the
    instant and is not a meeting. Choosing is a judgement about the user's day, and
    ADR-0093 §2 rules that "A reader infers nothing: it reads a file and reports
    what the file says". A count is a fact about the parsed occurrences.

    **The payload is additive.** A later ADR may add ``entries`` as an optional
    field the day a consumer needs them, and every producer and fixture that
    predates it stays valid; shipping them now and removing them later would be a
    breaking change. The asymmetry decides it (ADR-0096 §10).

    Attributes:
        kind: This type's own literal tag, the discriminator
            :data:`ReadingFacet` resolves on (ADR-0140 §6). **Defaulted**, so
            every construction site that predates the union stays valid — which
            is ADR-0008 §1's pattern and the property ADR-0096 §5 was counting on
            when it called this "one more line in the change that ADR authorises".
        entries_in_progress: How many occurrences were in progress at
            :attr:`~ContextFacet.read_at`. An occurrence with a non-zero duration
            is in progress when ``start <= read_at < end``; a zero-duration one
            when ``start == read_at``. That is ADR-0093 §7b's half-open membership
            evaluated at an instant rather than over a window, and the two arms
            exist for §7b's reason.
        next_starts_at: The earliest in-window occurrence starting **strictly
            after** ``read_at``, and ``None`` where the window holds none.

            **``None`` states that the reading found no later occurrence within
            its window, and never that none exists.** No consumer may read it as
            an absence and no surface may present it as one — which is what
            :attr:`covers_until` is carried to make interpretable.
        covers_until: The **exclusive** upper edge of the window this reading
            covered. It travels with the value because a consumer of
            :class:`CurrentContext` does not read ``Settings``, so the horizon has
            to be here or not exist at all.

            The backward edge is deliberately not carried: nothing a consumer
            reads is bounded by it, since ``entries_in_progress`` is anchored at
            ``read_at`` and §7b's overlap membership already guarantees that an
            occurrence which began before the window and is still running is in
            the reading. Both edges saturate under §7b, so this is always a
            representable instant.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["calendar"] = "calendar"
    entries_in_progress: int = Field(
        ge=0,
        description="Occurrences in progress at read_at (ADR-0096 §6's membership rule).",
    )
    next_starts_at: UtcInstant | None = Field(
        default=None,
        description=(
            "The earliest in-window occurrence starting strictly after read_at; "
            "None when the window held none — never 'there is none'."
        ),
    )
    covers_until: UtcInstant = Field(
        description="The exclusive upper edge of the window the reading covered (tz-aware).",
    )


class EmailFacet(ContextFacet):
    """How much mail arrived in the window the reading covered (ADR-0140 §6).

    Two scalars, and **no span of any message** — no sender, address, display
    name, subject, body, identifier or per-message instant. That rule is stronger
    here than ADR-0096 §6 needed it to be for the calendar. ``CurrentContext``
    reaches every prompt, and a subject line is not merely disclosing: it is
    *attacker-chosen text* on the advisory path, where a failure is silent and
    where ADR-0098 §2's escaping obligation falls on an assembler that does not
    yet exist (#672). Two scalars need no content budget, no truncation rule and
    no escaping at all, which is what makes this facet safe to ship before that
    assembler lands.

    **A count rather than a boolean**, for ADR-0096 §6's ``busy: bool`` reason
    exactly: deciding what counts as *new* is a judgement about the user's
    attention, and the reader holds no read/unread state and may not infer one
    (ADR-0093 §2). A count is a fact about what was parsed.

    **The facet's job is what the beliefs cannot answer at request time, and for
    email that is volume rather than presence.** "You have had two messages
    today" and "you have had ninety" are different situations, and neither is
    legible from a belief the retrieval budget may not have selected.

    Attributes:
        kind: This type's own literal tag, the discriminator
            :data:`ReadingFacet` resolves on (ADR-0140 §6).
        arrived_in_window: How many messages the read **proposed from**.

            **A count of what this reader parsed from its store, and never a
            claim about the mail account** (ADR-0140 §6). The store is written by
            a fetcher outside this system whose completeness the reader cannot
            verify (§1), so no consumer may read this as a count of mail
            received, and no surface may present it as one. A stopped fetcher
            reads as a quiet week and nothing here can tell the difference —
            which is why the reading declares no coverage at all (§7).
        covers_from: The **inclusive** lower edge of the arrival window this
            reading covered.

            :attr:`CalendarFacet.covers_until`'s mirror, carried for the
            identical reason (ADR-0096 §6): a count of zero means nothing to a
            consumer who does not know how long an interval it counted over, and
            a consumer of :class:`CurrentContext` does not read ``Settings``, so
            the horizon has to travel with the value or not exist. Only the one
            edge is carried, because a mailbox has no future and the window's
            upper edge is ``read_at`` itself (ADR-0140 §3). Saturated under §3, so
            it is always a representable instant.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["email"] = "email"
    arrived_in_window: int = Field(
        ge=0,
        description=(
            "Messages this read proposed from — what the reader parsed from the "
            "store, never a count of mail the account received (ADR-0140 §6)."
        ),
    )
    covers_from: UtcInstant = Field(
        description=(
            "The inclusive lower edge of the arrival window the reading covered (tz-aware)."
        ),
    )


ReadingFacet = Annotated[
    CalendarFacet | EmailFacet,
    Field(discriminator="kind"),
]
"""One reading's situational half: a concrete facet type, tagged by ``kind``.

**Explicitly discriminated rather than a plain union**, which ADR-0096 §5
required of the second concrete facet to join the annotation and ADR-0140 §6
discharges: without the tag, pydantic's smart union picks a member by fit, so
"two facets that differ only in a scalar could parse as each other, quietly".

**``kind`` rather than ``source``, and the reason is the validator on
:class:`SourceReading`.** ``source`` looks like a free discriminator — it already
carries the reader's declared identity and the two values agree — but ADR-0096
§5's model validator cross-checks ``facet.source`` against the *reading's*
``source``, which is free text carrying ``Reader.name``. Constraining it by type
would make a mismatch surface as a union-resolution failure naming the wrong
fact. The two are different facts and stay two fields: ``source`` says who
produced the value, ``kind`` says which payload shape it is.

**The name is reserved for the discriminator across the facet hierarchy**
(ADR-0140 §6). Declaring it as a ``Literal`` tag is what a concrete facet type is
*required* to do — which is why it is not reserved against redefinition the way
:class:`ContextFacet`'s three stamp fields are, a rule that would make this union
unsatisfiable. What no facet may do is give the name a payload meaning, and no
type below a concrete facet may redefine it.
``tests/core/test_facet_coverage.py`` holds both halves.

**The tag's default does not make a serialised payload lacking ``kind``
loadable**, and no reading of it may claim otherwise: a discriminated union
extracts its tag from the input *before* it selects a member, so the field's
default never runs. Nothing persists or wire-carries one of these types today —
both are in-process values passed from a reader to ``orchestration`` and to the
ingest — so there is no legacy payload to invalidate. A lane that gives
:class:`SourceReading` or :class:`CurrentContext` a persisted or wire-carried
form owes the compatibility step with it, in a shape that cannot mask a genuinely
invalid payload (ADR-0140 §6).
"""


# --- reading: what one pass over a source produced (ADR-0093, ADR-0095) ------
# The read-only seam's return value. Two instants rather than one, because the
# clock that read a source and the clock that source reports on are different
# clocks (ADR-0073 §4), and a value rather than a bare sequence of proposals —
# which is what let the facet half land additively above, exactly as ADR-0093 §3
# said it would.


class ReadCoverage(BaseModel):
    """The interval of a source's world one reading **exhausted** (ADR-0110 §2).

    A half-open ``[covers_from, covers_until)`` pair, ``None`` at either end
    meaning unbounded — :class:`Validity`'s shape, its endpoint type and its
    invariant, deliberately mirrored rather than reused. The two say different
    things about different subjects: a ``Validity`` is *our* window on a belief we
    hold, and a coverage is a claim about **the read we performed**. Naming one
    with the other would put a record's live window and a reading's exhausted
    slice in one type, and §3 compares them *against each other*.

    **Why a reading carries this at all.** An entry absent from a reading either
    was deleted from the source or was never inside the slice the reader looked
    at, and ADR-0093 §4 refuses to let a reader distinguish them — correctly,
    since "a bounded read, a truncated file, a permission error and a genuinely
    deleted entry are indistinguishable from the reading". ADR-0093 §5 and §8
    removed the middle two from the seam by making a read that cannot complete
    **raise** rather than return a short reading, leaving exactly one pair for
    coverage to separate: a bounded read and a genuine deletion. Coverage is what
    says which region the reader is *entitled* to have found something in.

    **It states what the read exhausted, and a reader may declare it only where
    that is true of the read it performed** (ADR-0110 §2). It is never widened to
    what the reader was configured to cover, to what the source is presumed to
    hold, or to the reader's whole bound where the read stopped short of it — a
    read that stopped short raises under ADR-0093 §8 and declares nothing.

    **A fact about the read, not a claim about the source.** It is the same class
    of fact as :attr:`SourceReading.read_at` — our own account of what we did —
    and deliberately not the class ADR-0093 §10 protects ``as_of`` from becoming,
    which is a claim only the source may make. A reader knows what it exhausted
    because it chose the bound; it does not know, and may not assert, what the
    source contains.

    Attributes:
        covers_from: Inclusive start of the exhausted interval; ``None`` means
            unbounded in the past.
        covers_until: Exclusive end of the exhausted interval; ``None`` means
            unbounded in the future.
    """

    model_config = ConfigDict(frozen=True)

    covers_from: UtcInstant | None = Field(
        default=None,
        description="Inclusive start of the interval the read exhausted; None means unbounded.",
    )
    covers_until: UtcInstant | None = Field(
        default=None,
        description="Exclusive end of the interval the read exhausted; None means unbounded.",
    )

    @model_validator(mode="after")
    def _coverage_is_ordered(self) -> ReadCoverage:
        """Reject an inverted or empty coverage: when both ends are set, end > start.

        :class:`Validity`'s invariant, for the same reason and with the same
        force. A coverage whose end is at or before its start exhausted no
        instant, so a reading declaring one asserts that it looked at nothing and
        would still warrant an absence over every record it contains — which is
        none, but only accidentally. Making it unrepresentable is better than
        reasoning about it at every use.
        """
        if (
            self.covers_from is not None
            and self.covers_until is not None
            and self.covers_until <= self.covers_from
        ):
            msg = "covers_until must be after covers_from"
            raise ValueError(msg)
        return self

    def contains(self, extent: ReportedExtent) -> bool:
        """Whether ``extent`` lies **wholly within** this coverage (ADR-0117 §3).

        Containment of one half-open interval in another with unbounded ends,
        defined once here rather than at each use — the "one rule, one place"
        discipline :meth:`Validity.live_at` keeps, and for the same reason: it is
        a pure function of the two intervals, with no clock and no policy, so it
        is a semantic intrinsic to the type rather than subsystem logic. ADR-0110
        §3 states the rule "so no lane has to derive it", and this is where it
        stops being derived.

        **The rule is ADR-0110 §3's, unchanged; only its operand moved.** §3 asked
        this question of the record's *envelope validity window*, and ADR-0117 §3
        asks it of the reported entry's :class:`ReportedExtent` instead — because
        that window has an operational job (ADR-0045 §6) which a forward-looking
        source's position would break, taking retrieval, the absence enumeration
        and conflict detection with it (ADR-0117 §1). Everything §3 argued for the
        rule survives the change of carrier, which was the test of it.

        **An unbounded extent end is contained only by an unbounded coverage end
        on the same side.** So an extent open at either end is contained only by a
        coverage open at that end, and a bounded reading contains none — which is
        ADR-0110 §3's decisive property rather than a gap in it. A source that
        states no position for an entry has told a bounded reading nothing about
        the region that entry occupies, and an absence therefore proves nothing;
        one that states where the entry lies has said something a reading which
        exhausted that region and did not find it has genuinely observed. A record
        whose attestation declares *no* extent at all satisfies the condition for
        no reading, which its consumers decide before reaching here.

        Args:
            extent: The reported entry's own span, as its producer declared it.

        Returns:
            Whether every instant the extent admits lies inside this coverage.
        """
        starts_inside = self.covers_from is None or (
            extent.extends_from is not None and extent.extends_from >= self.covers_from
        )
        ends_inside = self.covers_until is None or (
            extent.extends_until is not None and extent.extends_until <= self.covers_until
        )
        return starts_inside and ends_inside


class SourceReading(BaseModel):
    """What one :class:`~ai_assistant.core.protocols.Reader` pass produced.

    The proposals a reader drew from its source in one bounded read, with the
    identity of the reader that produced them and the instants that say *when*
    they were true. It follows :class:`MemoryIngestResult`'s precedent that a seam
    returning more than one fact returns a named value rather than a tuple — and
    here that shape is load-bearing for a second reason: ADR-0093 §3 defers the
    **facet half** of this type, which lands later as an *optional* field, and a
    reading that predates that field stays valid. A Protocol returning a bare
    sequence of proposals would make the facet's arrival a signature change, which
    is a breaking ``core`` change owing its own ADR (golden rule 5), bought purely
    to avoid naming a model now.

    **``read_at`` and ``as_of`` are two different clocks and are never merged**
    (ADR-0093 §10). Collapsing them is the exact defect ADR-0073 §4 describes: "a
    record synced on Tuesday from a calendar that said so on Monday renders
    'Tuesday', which is a true statement about us and a false one about the
    source."

    **Per-proposal report time is not carried here.** Where a source's report time
    is per-entry — as a calendar's is — it belongs on the proposal, in
    :class:`Attestation`, and a reader sets it when constructing the proposal
    (ADR-0093 §10, ADR-0092 §1). ``as_of`` is the reading-wide claim and nothing
    else.

    **An empty ``proposals`` tuple is a successful reading**, and means the source
    had nothing to propose within the bound. It is not a failure signal and no
    caller may treat it as one: a read that cannot complete **raises**
    :class:`~ai_assistant.core.errors.ReaderError` and constructs no reading at all
    (ADR-0093 §8).

    Attributes:
        source: The producing reader's ``name`` — the reading's stable, Tier 2
            identity (ADR-0004 §1). Carried on the reading rather than left to the
            caller so the value that reaches
            :attr:`Attestation.reported_by` is the producer's own. It must never
            embed Tier 0/1 data: a reader that wraps personal data names *itself*
            (``"calendar"``), never the data it holds, and never its source's
            location — an identity is what lands in :class:`Provenance`, in every
            export and in every log line (ADR-0093 §7).
        read_at: The instant **this system** performed the read. Always present,
            because it is always knowable and always true — it is our own clock —
            and captured **once, at the moment the source's bytes are acquired**,
            so it is the single anchor every window and recurrence decision uses.
        as_of: The instant **the source declares for the reading as a whole**,
            where it declares one, and ``None`` where it does not.

            **Optional by decision rather than by laxity, and the ``None`` is
            load-bearing.** A local ``.ics`` file declares no reading-level as-of:
            the format's report times are per-``VEVENT`` (``DTSTAMP``,
            ``LAST-MODIFIED``), and the file's mtime is a fact about our filesystem
            rather than a claim the source made. So the only two values a
            *required* field could take for the first source are a filesystem
            observation — which collapses the very distinction ADR-0073 §4 draws —
            or one entry's stamp applied to all of them, which is false for every
            other entry. A source that *does* declare one (a feed's
            ``Last-Modified``, a sync API's server instant) has an honest home for
            it. **It carries only an instant the source itself declares for the
            whole reading, and may never be filled from the filesystem, from the
            clock, or from one entry's stamp applied to the rest** (ADR-0093 §10).
        proposals: What the source said, as records to put through the write path,
            in the reader's own order. Possibly empty (above). Every one of them is
            in the ``ATTESTED`` band and none is an ``EpisodicMemory``, which the
            shared ``Reader`` conformance suite pins rather than this type: a
            producer-side obligation about what a *reader* may emit, not a property
            of every reading-shaped value (ADR-0093 §4).
        coverage: The interval of the source's world this read **exhausted**, and
            ``None`` where the reading declares none (ADR-0110 §2).

            **Optional, and the ``None`` is the safe default rather than a gap.**
            Its absence means the reading declares no coverage and **warrants no
            absence**, so ADR-0093 §4's refusal — a reader never proposes that
            anything was withdrawn — remains the operative behaviour of every
            reader that does not opt in. Making it required would break every
            existing construction site and every stored reading to avoid a
            ``None``, the trade ADR-0093 §3 already refused for the facet half and
            ADR-0109 §2 refused for ``last_confirmed_at``.

            **Declaring it is half of an opt-in, never the whole of one.** A
            reader that wants a covered absence to demote a belief owes *both*
            halves (ADR-0110 §3 as ADR-0117 §3 reads it): this declaration, and a
            declared :class:`ReportedExtent` on the proposals whose absence should
            count. Neither alone does anything — a record whose attestation states
            no extent is contained by no coverage, so it is never
            absence-demotable. The cost is deliberate: it makes opting in an
            explicit act by the lane that holds the source, which is the lane that
            can say whether "absent" means anything for that source at all.

            **It is never a bounded envelope validity window.** ADR-0110 §3 asked
            for one and ADR-0117 §4 rules the opposite: a producer does not bound
            a record's operational window in order to obtain a demotion, and no
            implementation may make a belief's presence on the read path depend on
            when it was last read.
        facet: The situational half of this reading — the other consumer's
            (ADR-0093 §3, ADR-0096 §5). ``None`` is valid and means this reader's
            source has no situational reading to contribute.

            **Annotated with the concrete facet types a reader may produce**, and
            widened by each later ADR that adds a facet, because the base
            annotation loses the payload silently (see :class:`ContextFacet`). A
            second concrete type has joined it, so the union is now explicitly
            **discriminated** on ``kind`` — see :data:`ReadingFacet`, which
            carries that clause and what its tag's default does and does not buy
            (ADR-0096 §5, ADR-0140 §6).

            **Both halves are computed on every read and they may legitimately
            contain different things.** ``CalendarReader`` skips an occurrence
            whose ``DTSTAMP`` is absent — it must, since ADR-0092 §3 permits no
            substitute for a report time the source did not make — but the facet
            has no attestation to construct, so that occurrence is counted in the
            facet and missing from the proposals. ADR-0093 §3 already rules that
            this is the design rather than an error: "What matters is not that they
            agree but that neither is mistaken for the other." Nobody should "fix"
            it by making the facet skip the same entries.
    """

    model_config = ConfigDict(frozen=True)

    source: EncodableText = Field(
        description=(
            "The producing reader's declared identity — Tier 2, stable, and never "
            "derived from the source's location or contents (ADR-0093 §7)."
        ),
    )
    read_at: UtcInstant = Field(
        description=(
            "When this system performed the read (tz-aware), captured once as the "
            "source's bytes were acquired."
        ),
    )
    as_of: UtcInstant | None = Field(
        default=None,
        description=(
            "Any reading-wide instant the source itself declares (tz-aware); None "
            "where it declares none. Never our clock and never the file's mtime."
        ),
    )
    proposals: tuple[MemoryUpdateProposal, ...] = Field(
        default=(),
        description=(
            "The beliefs the source reported, in the reader's order. Empty is a "
            "successful reading, not a failure signal (ADR-0093 §8)."
        ),
    )
    coverage: ReadCoverage | None = Field(
        default=None,
        description=(
            "The interval of the source's world this read exhausted; None means "
            "the reading declares none and warrants no absence (ADR-0110 §2)."
        ),
    )
    facet: ReadingFacet | None = Field(
        default=None,
        description=(
            "The situational half of this reading, stamped identically to it; "
            "None where the source has no situational reading (ADR-0096 §5)."
        ),
    )

    @model_validator(mode="after")
    def _facet_is_stamped_from_this_reading(self) -> SourceReading:
        """A carried facet's stamp is this reading's, unchanged (ADR-0096 §5).

        **The duplication is intentional, which this validator can make look
        accidental.** If the facet's stamp must always equal the reading's, it
        looks redundant *on the reading* — and it is, for as long as the two travel
        together. They do not: the ``context/`` adapter lifts the facet out and
        puts it in :class:`CurrentContext`, where the reading is gone and the stamp
        is the only thing left saying who produced the value and when. This
        validator's job is to keep the copy faithful, not to argue it away.

        **On the type rather than in the ``Reader`` conformance suite**, on two
        grounds. It is *stronger*: the suite binds implementations of ``Reader``,
        while a validator reaches every construction path — a fixture, a fake, a
        library consumer — the same reason ADR-0092 §2 put its rule on
        :class:`Provenance` rather than at the ``MemoryPolicy`` gate. And it keeps
        the rule additive on a type ADR-0096 already touches instead of adding an
        item to another ADR's enumerated suite.

        Admissible under ADR-0086 §3's test — "does it refuse something that
        already worked" — because ``facet`` is a new field: no persisted or
        in-flight reading can fail it, and it is vacuous when ``facet`` is
        ``None``.

        Raises:
            ValueError: If the facet's ``source``, ``read_at`` or ``as_of``
                differs from this reading's. Each is checked and reported
                separately: a facet stamped with a different source than the
                reading that carried it attributes content and freshness to the
                wrong system.
        """
        if self.facet is None:
            return self
        mismatches = [
            f"{field} ({getattr(self.facet, field)!r} != {getattr(self, field)!r})"
            for field in ("source", "read_at", "as_of")
            if getattr(self.facet, field) != getattr(self, field)
        ]
        if mismatches:
            msg = (
                f"a reading's facet carries that reading's own stamp, unchanged; "
                f"these differ: {', '.join(mismatches)} (ADR-0096 §5)"
            )
            raise ValueError(msg)
        return self


# --- learning: explicit, memory-affecting feedback (ADR-0009) ----------------
# `learning` turns one of these into a `MemoryUpdateProposal` above.


class FeedbackKind(StrEnum):
    """The kind of explicit feedback the user gave (see ADR-0009)."""

    CORRECTION = "correction"
    PREFERENCE = "preference"


class FeedbackEvent(BaseModel):
    """A unit of explicit, memory-affecting feedback (see ADR-0009).

    The learning subsystem turns this into a :class:`MemoryUpdateProposal`.
    ``memory_kind`` says which typed record it establishes, and it is **optional**
    (ADR-0122 §1): ``None`` means the feedback does not name a record type and one
    is to be resolved from the belief the feedback touches — by `orchestration`,
    before the :class:`~ai_assistant.core.protocols.FeedbackProcessor` is called.

    **Absent never means "unknowable", and it is never stored.** A producer that
    cannot know the drawer — a correction's target is a property of the belief it
    corrects, which the producer has not read — reports what it knows by leaving
    the field ``None``. A value present is the caller's **pin**: it is honoured
    unchanged, and it suppresses the resolution's store read entirely (ADR-0122
    §6). That distinction is the whole point of the field's domain: an invented
    default and a user's deliberate choice were indistinguishable once the field
    was filled, so a fixed table in ``interfaces/cli.py`` filed every correction as
    a :class:`SemanticMemory` and the one command named for corrections could not
    correct a preference (#864).

    **A ``FeedbackEvent`` reaching a ``FeedbackProcessor`` carries a resolved
    kind** (ADR-0122 §7); establishing that is the calling stage's obligation, and
    :class:`~ai_assistant.learning.processor.RuleBasedFeedbackProcessor` raises on
    an unresolved event rather than answering it with the silence it owes a
    deferred target.

    **``subject`` and ``about_person`` are two different axes, side by side on
    purpose** (ADR-0100 §7). ``subject`` is the older field and keeps its meaning
    exactly: an optional *scope* for a preference — "email tone", "units" — which
    :class:`~ai_assistant.learning.processor.RuleBasedFeedbackProcessor` lands as
    :attr:`PreferenceMemory.context`. ``about_person`` is whom the belief is
    *about*, with :class:`MemoryBase`'s semantics unchanged. The word "subject" is
    taken at least five times over in this corpus and none of its senses is a
    person, so the person axis does not get it: two fields called ``subject`` on
    one type is not available, and their standing side by side is the clearest
    statement that they are not one thing. Whether the older field would be better
    named ``scope`` is a decision of ADR-0009's that no lane may change on
    ADR-0100's authority (issue #688).

    **This is the only route by which a non-owner subject enters the store**
    (ADR-0100 §4): a user states one, or nothing does. It shipped *with* the route —
    ``assistant learn --about-person`` — because a field with no route would leave
    every third-party belief constructing ``about_person=None``, which §3 reads as
    the owner's, making a false record of the exact case the field was added for.
    ADR-0293 §11 retired ``learn`` from the engine surface, a reply in the
    conversation being its replacement, so no surface constructs this event.

    **``guarded`` is the owner's explicit placement act at write** (ADR-0217 §7),
    and it is on this event rather than encoded by an adapter because deciding a
    record's placement is not adapter work: golden rule 3 keeps business logic out
    of `interfaces/`, and an adapter translating a flag into a :class:`Placement`
    would be deciding disclosure in the thinnest layer in the system. The adapter
    sets a field; `learning` reads it. The
    :class:`~ai_assistant.core.protocols.FeedbackProcessor` that builds the record
    honours it. It is a **narrowing only**, and ``False`` is not an act of any
    kind: it leaves the record with ADR-0217 §6's default, which is ADR-0199 §3's
    placement of its class. It is not a widening act, not an unguard, and not a
    record that the owner considered this belief and declined to guard it.

    **Honouring it is a change to the ``FeedbackProcessor`` Protocol's behavioural
    contract, not to one implementation** (§7). An implementation that built its
    normal proposal and ignored this member would be structurally conformant and
    would silently discard an explicit owner act, so the obligation is pinned by
    the shared ``FeedbackProcessorContract`` and every implementation bound to that
    suite — the canonical fake in ``ai_assistant.testing`` included — is held to
    it. That suite, and not this docstring, is what makes the obligation enforced
    rather than assumed.
    """

    model_config = ConfigDict(frozen=True)

    kind: FeedbackKind
    memory_kind: MemoryKind | None = Field(
        default=None,
        description=(
            "The typed memory this feedback establishes, or ``None`` to have it "
            "resolved from the belief the feedback touches (ADR-0122 §1). A value "
            "present is the caller's pin and is honoured unchanged."
        ),
    )
    content: EncodableText = Field(
        description="Canonical text of the feedback, e.g. 'office is in Boston'."
    )
    subject: EncodableText | None = Field(
        default=None, description="Optional scope/context, e.g. 'email tone'."
    )
    about_person: NonBlankEncodableText | None = Field(
        default=None,
        description=(
            "Whom this feedback is about, when that is someone other than the owner "
            "(ADR-0100 §7). Carried onto the record the processor builds. Distinct "
            "from ``subject``, which is a preference scope."
        ),
    )
    evidence: tuple[EncodableText, ...] = Field(
        default=(),
        description="Interaction/episode ids supporting this, carried into provenance.",
    )
    created_at: UtcInstant = Field(description="When the feedback was given (tz-aware).")
    guarded: bool = Field(
        default=False,
        description=(
            "The owner's explicit act placing what this feedback establishes for "
            "themselves alone (ADR-0217 §7). ``True`` writes every record this event "
            "produces with reach ``OWNER`` and setter ``OWNER_ACT``; ``False`` — the "
            "default — is not an act of any kind and leaves ADR-0217 §6's default "
            "placement. A narrowing only: there is no widening act at write."
        ),
    )

    @field_validator("content")
    @classmethod
    def _content_is_present(cls, value: str) -> str:
        """Require non-empty content, so feedback cannot become a blank memory."""
        stripped = value.strip()
        if not stripped:
            msg = "feedback content must not be empty"
            raise ValueError(msg)
        return stripped


#: An ISO-4217 alphabetic code is exactly this long.
#:
#: **Declared here rather than beside** :class:`ToolCost`, which is where it used to
#: sit, on the ground :data:`Identifier`'s own comment states: ADR-0267 §1 gives it a
#: second consumer in :func:`_iso_4217_shaped`, which :class:`ActionQuote` is built on
#: and which is declared far above that position. Nothing about it changed.
_CURRENCY_CODE_LENGTH = 3


# --- the fetch seam: a listing of a configured root, and one file from it ------
# ADR-0230 §4. The values and their one enumeration are all frozen and all refuse
# unknown fields. The pair that carries a **capability** — `SourceListingEntry`
# and `SourceListing` — is fetcher-facing and never crosses into `planning`.
#
# **What a token and a handle *are* is deliberately not stated here.** §4 fixes
# four properties of the mechanism — unforgeable without state private to the
# fetcher, a handle bound to the listing that minted it, a token committing to
# its listing's ordered entry names, and verification that retains nothing — and
# leaves the construction to the fetcher. So `core` carries the values and the
# concrete fetcher owns what makes them unforgeable, exactly as §13 divides them.


class FetchRefusal(StrEnum):
    """Why a fetch produced no record (ADR-0230 §6).

    A **closed** enumeration with exactly five members, and no lane adds a sixth
    without the ADR that decides it. A refusal names a **class** and carries no
    path, no name, no excerpt and no message from an underlying library: the
    whole value is one of these members, so there is nowhere for one to sit.

    **Every member is reachable over a real filesystem from an authentic entry**
    (§6), which is why §6 re-applies every bound at ``fetch`` and carries none
    from the listing. The clause is stated on the enumeration because an
    enumeration is where a decision most easily acquires a member that only its
    own prose can reach.

    **There is no ``UNSUPPORTED_TYPE`` member and its absence is a decision**
    (§6). The type allow-list is applied where the listing is built, so the only
    caller who can name an unsupported file is one presenting an entry the
    fetcher never minted — and §4 rules that refusal :attr:`NOT_FOUND`,
    "deliberately the same class an absent file yields, so that it discloses
    nothing about whether a guessed name exists under the root". A distinct class
    would restore exactly that disclosure.
    """

    NOT_FOUND = "not_found"
    """The named file is not one this fetcher can resolve **now**.

    An absent file, an entry or listing this fetcher did not mint, an authentic
    token carried onto an altered listing, a handle minted for a different
    listing, a listing past either of §4's deadlines, and a ``name`` that is not a
    single path component all land here — deliberately one class, so that a
    caller holding nothing but a guess learns nothing about what the root holds
    (ADR-0230 §4)."""

    NOT_A_FILE = "not_a_file"
    """The named object is not a regular file.

    **Decided by what the object is, never by which step discovered it** (§4). A
    directory, a named pipe, a socket, a block or character device, and a
    symbolic link at the final component are all this class — including the kinds
    that cannot be opened at all, where the open itself refuses because of the
    object's kind. An implementation that classified only what it managed to open
    and folded every open *failure* into :attr:`UNREADABLE` would pass the
    directory and FIFO cases and mis-class the socket."""

    UNREADABLE = "unreadable"
    """The open or the read failed for a reason that is **not** about the
    object's kind — a permission denial, an I/O error, a resource limit (§4)."""

    TOO_LARGE = "too_large"
    """The file exceeded ``fetch_max_file_bytes``, its extracted text exceeded
    ``fetch_max_content_bytes`` (§6), its extraction's decoded bytes exceeded
    ``fetch_max_decoded_bytes`` (ADR-0232 §2, §4), or the ``/ToUnicode``
    character mappings its extraction builds exceeded
    ``fetch_max_character_mappings`` (ADR-0234 §1, §2, §4).

    All four bounds refuse rather than truncate: "No implementation returns a
    prefix, a first page, a first *n* bytes, an abridgement or a 'first part of'
    record, and none records a truncation flag in place of refusing." A file that
    *grew* past the size bound between the listing and the fetch lands here too,
    because the read is itself bounded and no bound is carried from the listing.

    **Which of the four refused is not disclosed**, and ADR-0232 §4 — whose
    ruling ADR-0234 §4 extends rather than replaces, adding no member — keeps
    one class for all of them rather than adding a sixth: which bound a document
    passed is a fact about that document's contents, and a member meaning *small
    on disk and large once decompressed* would be the disclosure §6 declines to
    make about a file's type, one property over. The cost is real and is named —
    ADR-0230 §9's refusal rate tells an operator that *a* bound is set below
    their documents and not which — and §10 defers the finer statement."""

    EXTRACTION_FAILED = "extraction_failed"
    """The file is of a supported format and its text could not be decoded (§6).

    Extraction is a **decoding** — a deterministic, library-performed
    transformation of bytes into the text they encode (§5) — and a failure of it
    is a refusal rather than a raise, because there is no failure a caller would
    handle differently from a refusal it must already handle (§4)."""


class SourceListingEntry(BaseModel):
    """One file a :class:`~ai_assistant.core.protocols.Fetcher` showed (ADR-0230 §4).

    The **fetcher-facing** value: held by `orchestration`, handed back to
    ``fetch``, and never crossing into `planning`.

    **It carries no path, no root and no directory component.** :attr:`name` is
    what a person calls the file — one path component, rendered into a prompt
    beside its label — and the address is the :attr:`handle`, which is rendered
    nowhere.

    **Display fields are not authority** (§4). Neither :attr:`size_bytes` nor
    :attr:`modified_at` is consulted by any fetch decision: the file is named by
    :attr:`name`, which a handle is bound over, and the size is decided against
    the object ``fetch`` opens. So a copy carrying an altered ``size_bytes`` or
    ``modified_at`` widens nothing and reaches nothing — it edits a rendering that
    has already happened.

    **A faithful copy is the same authority.** §4 forbids the fetcher retaining
    anything, so a byte-identical copy of a minted entry is indistinguishable from
    what was minted and is accepted; an implementation refusing one would be
    deciding from retained object identity, which §4 rejects.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: NonBlankEncodableText = Field(
        description=(
            "What a person calls the file — one path component, never a path "
            "(ADR-0230 §4). This is what a handle is bound over."
        ),
    )
    size_bytes: int = Field(
        ge=0,
        description=(
            "The file's size when it was listed. A **display** field: no fetch "
            "decision consults it, and the bound is decided against the object "
            "``fetch`` opens (ADR-0230 §4)."
        ),
    )
    modified_at: UtcInstant = Field(
        description=(
            "When the filesystem last recorded a write (tz-aware). A **display** "
            "field, offered so a person or a planner can tell one file from "
            "another; it never reaches a ``Provenance`` or an ``Attestation``, "
            "which ADR-0092 §3 forbids and ADR-0230 §5 leaves untouched."
        ),
    )
    handle: EncodableText = Field(
        description=(
            "The opaque capability this entry is addressed by (ADR-0230 §4). "
            "Minted by the fetcher for this listing, over this entry's name and "
            "position; unforgeable without state private to the fetcher. Rendered "
            "to no model, written to no log, and carried on no record."
        ),
    )


class SourceListing(BaseModel):
    """What a fetcher's configured root currently holds (ADR-0230 §4, §6).

    The root's **direct children only** — no recursion, no subdirectory
    traversal, no following of symbolic links out of the root — ordered most
    recently modified first, capped at ``fetch_listing_max_entries``, and
    restricted to the supported formats. The truncation and the ordering are both
    **declared**, which is why the cap is not the indistinguishable truncation
    ADR-0093 §5 refuses: a listing proposes no belief and mints no record.

    **An empty listing is a valid, successful listing** and every clause here
    holds on it. A root that cannot be read and an empty root both produce one,
    and no consumer distinguishes them (§6).

    **:attr:`read_at` is not the expiry's input** (§4). It is the tz-aware
    instant this system listed, which §3 renders and ADR-0026 §1 governs; the two
    deadlines are bound into the authenticated :attr:`token`, are rendered
    nowhere, and outlive no process.

    **The token commits to the ordered entry names**, which is what makes an
    authentic token useless over an altered listing: an entries tuple that was
    emptied, shortened, reordered, or had an entry's ``name`` changed is not the
    sequence that was signed, and every fetch against it is refused
    :attr:`FetchRefusal.NOT_FOUND`. The tuple a caller hands in is untrusted
    input rather than evidence — it is read, and never believed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: EncodableText = Field(
        description=(
            "The producing fetcher's declared identity, equal to its ``name`` — "
            "Tier 2, stable, and never derived from the root's location "
            "(ADR-0230 §4, ADR-0189, ADR-0190)."
        ),
    )
    read_at: UtcInstant = Field(
        description=(
            "When **this system** listed (tz-aware), captured once at acquisition. "
            "Not the expiry's input, which lives inside ``token`` (ADR-0230 §4)."
        ),
    )
    entries: tuple[SourceListingEntry, ...] = Field(
        default=(),
        description=(
            "The root's supported direct children, most recently modified first "
            "and capped. Empty is a **successful** listing (ADR-0230 §4, §6)."
        ),
    )
    token: EncodableText = Field(
        description=(
            "The opaque authority this listing is verified by (ADR-0230 §4). "
            "Minted by the fetcher, committing to the ordered entry names and to "
            "both expiry deadlines. Rendered to no model and written to no log."
        ),
    )


class FetchOutcome(BaseModel):
    """What one fetch produced: a record, or a refusal (ADR-0230 §4).

    **Exactly one of the two, enforced here rather than by a caller.** Neither
    both nor neither: a value carrying both would be two answers wearing one
    outcome's name, and one carrying neither would be the one outcome §6 says a
    fetch never has — "neither succeeding nor failing".

    **A refusal is a resolved outcome and never a failure** (§6). It adds no
    record, fails no turn, degrades no servicing and discards no other kind's
    records. Neither ``Fetcher`` member raises for a source reason, and ADR-0230
    adds no error class to ``core/errors.py``, because there is no failure a
    caller would handle differently from a refusal it must already handle.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: MemoryRecord | None = Field(
        default=None,
        description=(
            "The one record a successful fetch minted — ``SEMANTIC``, "
            "``EXTERNAL``-sourced, carrying the file's text verbatim "
            "(ADR-0230 §5). ``None`` where the fetch was refused."
        ),
    )
    refusal: FetchRefusal | None = Field(
        default=None,
        description=(
            "Why no record was produced (ADR-0230 §6). ``None`` where one was. A "
            "**class** and nothing else: no path, no name, no excerpt, no message."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_of_a_record_and_a_refusal(self) -> FetchOutcome:
        """Refuse an outcome carrying both answers, and one carrying neither.

        ADR-0230 §4 states the invariant on the model rather than on its
        producers, so a fetcher cannot emit an unreadable outcome and a consumer
        never has to decide which half to believe.
        """
        if self.record is not None and self.refusal is not None:
            msg = "a fetch outcome carries a record or a refusal, never both"
            raise ValueError(msg)
        if self.record is None and self.refusal is None:
            msg = "a fetch outcome carries a record or a refusal, never neither"
            raise ValueError(msg)
        return self


def _own_vocabularys_member(value: object, vocabulary: type[Enum], *, cited: str) -> object:
    """Refuse a member of some *other* enumeration, however its value compares.

    Pydantic validates a :class:`~enum.StrEnum` field **by value**, so a member of a
    different vocabulary that happens to share a spelling is accepted and silently
    converted into the annotated one. Where two vocabularies in this module describe
    different acts and overlap on a value, that conversion turns one fact into another
    with no error — the defect issue #2320 records, and the hazard ADR-0258 §3 names,
    files and expressly declines to rule on ("a guard is code, and the clause that would
    demand one is a decision this lane is not fenced for"). This is that code.

    **Run before pydantic's own coercion**, which is the only point at which the
    incoming member's own type is still visible: by the time an ``after`` validator
    sees it, the foreign member has already become a native one and the evidence is
    gone.

    **A bare** ``str`` **is left alone**, exactly as pydantic takes it today. A stored
    row, a wire frame and a ``model_validate`` of a dumped mapping all present the value
    as a string, there is no second vocabulary for a string to have come from, and
    refusing one would narrow a decoding path this guard has no quarrel with (ADR-0087).
    What it refuses is the one thing a JSON document cannot express: an enum member of
    the wrong type, which only in-process code can pass.

    Args:
        value: The value as it arrived, before coercion.
        vocabulary: The enumeration the field is annotated with.
        cited: Where that annotation is decided, for the refusal's message.

    Returns:
        ``value`` unchanged, for pydantic to validate as it otherwise would.

    Raises:
        ValueError: If ``value`` is an enum member of any other enumeration.
    """
    if isinstance(value, Enum) and not isinstance(value, vocabulary):
        msg = (
            f"expected a {vocabulary.__name__} member ({cited}); got "
            f"{type(value).__name__}.{value.name}, which is a different vocabulary about "
            f"a different act. The two overlap on at least one value, so pydantic would "
            f"convert it silently rather than refuse it (#2320, ADR-0258 §3)"
        )
        raise ValueError(msg)
    return value


# --- tools: what one web search produced (ADR-0231 §10, §17) -----------------
# The `WebSearcher` seam's return value and its refusal vocabulary. `core`'s
# because they cross that seam (ADR-0231 §13); the mapping from a refusal to the
# servicer's own disposition is `orchestration`'s and lives there.


class SearchRefusal(StrEnum):
    """Why a search produced no record (ADR-0231 §10, §17; ADR-0241 §4).

    A **closed** enumeration with exactly seven members, each valued by its
    lower-cased name — ADR-0231 §17's six and ADR-0241 §4's
    :attr:`DEADLINE_EXPIRED`, which supersedes that closure *"in that count
    alone"* and leaves every other clause of it standing. The vocabulary is
    **added to and never renamed**, and no later lane adds an eighth without the
    ADR that decides it — ADR-0221 §5's pattern for its own reason: a vocabulary
    that grows by implementation grows without anyone having decided what the new
    member means.

    **Every member is returned and none is raised.**
    :meth:`~ai_assistant.core.protocols.WebSearcher.search` raises for no source
    reason, so a non-yield is a value the audit can count and the turn can ignore
    rather than an exception every call site must catch correctly. That is
    ADR-0230 §4's posture on the fetch seam and ADR-0231 §3's on the composing
    one, and neither ADR-0231 nor ADR-0241 adds an error class to
    ``core/errors.py`` for it. That holds for :attr:`DEADLINE_EXPIRED` too
    (ADR-0241 §4): ``search``'s ``ValueError`` guard is about a ``timeout`` an
    implementation could not run under and fires before anything is read, where an
    expiry of a *valid* bound is an outcome.

    **Six of the seven are carried across one for one into the servicer's own
    disposition** (ADR-0231 §13, ADR-0241 §4), and :attr:`NO_RESULT` deliberately
    is not: a search that reached the provider and yielded nothing is a
    *completed* servicing whose returned count is zero, which ADR-0226 §9 already
    records, and calling it a disposition would double-count it.

    **A refusal names a class and carries nothing else** — no query, no fragment
    of one, no origin, no address, no provider message, no exception type. The
    whole value is one of these members, so there is nowhere for one to sit.
    """

    SPEND_REFUSED = "spend_refused"
    """A configured ceiling would have been crossed (ADR-0231 §15, ADR-0194 §4).

    The gate is consulted after ADR-0231 §6's three checks and **before** the
    ledger claim, so this outcome reads no credential, opens no channel, appends
    no claim and appends no completion. It is a disposition and never a retry."""

    TRANSPORT_FAILED = "transport_failed"
    """The channel could not be opened, verified or continued (ADR-0191 §1).

    A statement about this system's own reach — a refused connection, a TLS
    failure, a channel closed mid-response — and never about
    what the provider said, which is :attr:`PROVIDER_REFUSED`. A redirect belongs
    here too: ADR-0231 §5 makes one a refusal and never a second request.

    **It stopped covering an expiry of the seam's own deadline, and that is the
    whole of what moved** (ADR-0241 §4). Its other conditions keep this member,
    keep the meaning ADR-0231 §5 and ADR-0191 §1 gave them and keep the
    ``ToolOutcome`` a completion records for them; no implementation returns this
    for a deadline and no lane collapses the two back together. An **upstream**
    ``TimeoutError`` raised inside the bound for the transport's own reasons is
    still this member and never :attr:`DEADLINE_EXPIRED` (ADR-0241 §7).

    **Nothing here asserts that any of those conditions disclosed nothing**
    (ADR-0241 §4). A channel closed mid-response may well have carried the whole
    query; what a completion should record for that is a separate question
    ADR-0241 §13 files rather than answers."""

    DEADLINE_EXPIRED = "deadline_expired"
    """The bound the caller handed this call expired before it answered (§4).

    ADR-0241 §1's ``timeout`` covers the seam's own work — the revalidation, the
    spend admission, the credential read, the channel, the response read and the
    transcription — and **not** either ledger append, which ADR-0192 §3 pins
    unbounded by this seam. So this member says the seam stopped waiting on the
    stages it owns; it does not say the provider stopped working, and **no caller
    assumes the query did not leave** (ADR-0029 §4's cooperative limit).

    **That is why it is a member and not a nicer label for
    :attr:`TRANSPORT_FAILED`** (ADR-0241 §5). ADR-0029 §4's
    ``FAILED``-or-``INDETERMINATE`` rule attaches to a deadline expiry or a
    cancellation and to nothing else, and the seam is the only party that can
    establish that its *own* deadline expired — so while one member carried both
    an expiry and a refused connection, no mapping from it could apply that rule
    to the first without applying it to the second. Where the expiry lands after
    the ledger claim, the completion carries the declaration's
    ``interrupted_outcome`` and an ``UNKNOWN`` incurred cost; where it lands
    before one, there is no claim and no completion row is written.

    **A disposition and never a retry** (ADR-0241 §6). An interrupted search is not
    re-run on the turn that asked for it, because a retry would hand a stalling
    provider the ability to make its own stalls free."""

    PROVIDER_REFUSED = "provider_refused"
    """The provider answered, and its answer is not one a search can be read from.

    A non-success status, a body that is not the shape the provider documents
    (ADR-0231 §10), or a bound account that moved under the credential read —
    ADR-0148 §6's discard limb, whose refusal ADR-0231 §5 names as this member."""

    RESPONSE_TOO_LARGE = "response_too_large"
    """The response passed ``search_max_response_bytes`` (ADR-0231 §5).

    The read stopped one byte past the bound, the channel was closed, **nothing
    was parsed** and no record was minted. Distinct from
    :attr:`PROVIDER_REFUSED` because the provider may have answered perfectly
    well: what happened is that this system declined to buy the answer."""

    UNATTESTED = "unattested"
    """The response declared no report instant, or none that can be read (§10).

    ADR-0092 §3 binds as written: ``reported_at`` is the instant the provider's
    own response declares, and there is **no substitute** — not the instant we
    sent, not the instant we received, not a clock this system read. A value in
    that position which cannot be read as an instant is not a declared one, so it
    lands here rather than licensing a fallback."""

    NO_RESULT = "no_result"
    """The response carried no result, or ADR-0231 §10 dropped every one it did.

    One member for both, because an operator acts on neither: the search reached
    the provider, was attested, and yielded nothing this system will carry. The
    drops §10 states — a result over ``search_max_result_chars``, one whose
    address is absent, one whose title, address or snippet carries an ASCII line
    break, and one whose span the provider supplied as a non-string — all end
    here where they take the last result with them."""


def _check_minted_by_a_search(record: MemoryRecord, *, reported_at: datetime | None) -> None:
    """Refuse a record ADR-0231 §10's minting clause would not have produced.

    Written out here rather than inside :class:`SearchOutcome`'s validator so that
    each condition is one branch a reader can find, and so that the validator
    itself stays one statement of the exactly-one rule.

    Args:
        record: One record the outcome carries.
        reported_at: The outcome's own report instant.

    Raises:
        ValueError: If the record is not ``SEMANTIC``, is not ``EXTERNAL``-sourced,
            carries evidence, or is attested to another instant.
    """
    if record.kind != "semantic":
        msg = f"a search mints SEMANTIC records; got a {record.kind!r} one"
        raise ValueError(msg)
    provenance = record.provenance
    if provenance.source is not MemorySource.EXTERNAL:
        msg = f"a search mints EXTERNAL-sourced records; got {provenance.source}"
        raise ValueError(msg)
    if provenance.evidence:
        # ADR-0231 §10: `evidence` is empty. A minted record is supply for one turn
        # and resolves in no store (§16), so a citation on it would point at nothing
        # a later reader could reach.
        msg = "a search mints records carrying no evidence"
        raise ValueError(msg)
    attestation = provenance.attestation
    if attestation is None or reported_at is None or attestation.reported_at != reported_at:
        # The clause ADR-0092 §3 rests on: the record's instant is *the response's*,
        # so a producer that reached for a clock of its own cannot construct the
        # value at all.
        msg = (
            "every record a search mints is attested to the outcome's own report "
            "instant (ADR-0231 §10, ADR-0092 §3)"
        )
        raise ValueError(msg)


class SearchOutcome(BaseModel):
    """What one search produced: records, or a refusal (ADR-0231 §10, §17).

    **Exactly one of the two, enforced here rather than by a caller.** Neither
    both nor neither: a value carrying both would be two answers wearing one
    outcome's name, and one carrying neither would be the outcome ADR-0231 §10
    says a search never has. Stating the conditions on the model rather than on
    its producers is what makes them decidable in any process and true of every
    ``WebSearcher`` this system ever wires, the canonical fake included.

    **Every condition below is *structural* — over this value's own fields** — so
    none of them reaches for a bound, a clock, a store or a configuration.
    ``search_max_results`` and ``search_max_result_chars`` are ``Settings`` fields
    the *configured searcher* enforces (ADR-0231 §17): this model carries neither
    and validates identically in every deployment, which is what makes the type
    shareable by two searchers configured differently in one process.

    **The attestation equality is the load-bearing one.** A record whose
    ``Attestation.reported_at`` is not the outcome's own is a record attested to
    an instant this response did not declare, which is exactly the substitute
    ADR-0092 §3 forbids — so a ``SearchOutcome`` carrying one is
    **unconstructable** rather than merely irregular, and an implementation that
    reached for a local clock fails at the value rather than at a review.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reported_at: UtcInstant | None = Field(
        default=None,
        description=(
            "The instant the provider's own response declared, on the provider's "
            "own clock (ADR-0231 §10, ADR-0092 §3). Never the instant we sent, the "
            "instant we received, or any clock this system read. ``None`` where the "
            "search was refused."
        ),
    )
    records: tuple[MemoryRecord, ...] = Field(
        default=(),
        description=(
            "The records this search minted, in the order the provider returned "
            "the results they transcribe (ADR-0231 §10). Empty where the search "
            "was refused."
        ),
    )
    refusal: SearchRefusal | None = Field(
        default=None,
        description=(
            "Why no record was produced (ADR-0231 §10). ``None`` where records "
            "were. A **class** and nothing else: no query, no origin, no address, "
            "no provider message."
        ),
    )

    @model_validator(mode="after")
    def _records_or_a_refusal(self) -> SearchOutcome:
        """Refuse an outcome that half-says two things (ADR-0231 §17).

        Raises:
            ValueError: If a refusal is paired with a record or a report instant,
                or if no refusal is paired with no report instant or no record.
        """
        if self.refusal is not None:
            if self.records:
                msg = "a search outcome carries records or a refusal, never both"
                raise ValueError(msg)
            if self.reported_at is not None:
                msg = "a refused search declares no report instant"
                raise ValueError(msg)
            return self
        if self.reported_at is None:
            msg = "a search outcome that carries no refusal declares a report instant"
            raise ValueError(msg)
        if not self.records:
            msg = "a search outcome carries records or a refusal, never neither"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _every_record_is_an_attested_external_semantic(self) -> SearchOutcome:
        """Refuse a record ADR-0231 §10 would not have minted.

        Raises:
            ValueError: If any record is not ``SEMANTIC``, is not
                ``EXTERNAL``-sourced, carries evidence, or is attested to an
                instant other than this outcome's own.
        """
        for record in self.records:
            _check_minted_by_a_search(record, reported_at=self.reported_at)
        return self


# --- tools: what one forecast read produced (ADR-0260 §4, §5) ----------------
# The `Forecaster` seam's return value and its refusal vocabulary, and the
# user-facing fold of the servicing's disposition. `core`'s because all three cross
# that seam (ADR-0260 §8); `ForecastDisposition` — the servicer's own account — is
# `orchestration`'s and lives there.


class ForecastRefusal(StrEnum):
    """Why a forecast read produced no record (ADR-0260 §4, §5).

    A **closed** enumeration with exactly six members, each valued by its
    lower-cased name. The vocabulary is **added to and never renamed**, and no
    implementation, setting or later lane adds a seventh without the ADR that
    decides it — ADR-0221 §5's pattern for its own reason: a vocabulary that grows
    by implementation grows without anyone having decided what the new member
    means.

    **Every member is returned and none is raised** (§4).
    :meth:`~ai_assistant.core.protocols.Forecaster.read` raises for no source
    reason, so a non-yield is a value the audit can count and the turn can ignore
    rather than an exception every call site must catch correctly. That is
    :class:`SearchRefusal`'s posture at a second seam, and ADR-0260 adds **no**
    error class to ``core/errors.py`` for it.

    **There is no member for a spend refusal, and that is deliberate** (§4, §6).
    This vocabulary names what a *read* produced; the stages the seam never sees —
    no registration, no budget, no derivable binding, no ``ALLOW``, no admission —
    are the servicing's own account, which ADR-0260 §8 puts in
    ``ai_assistant.orchestration.reads``.

    **A refusal names a class and carries nothing else** — no place, no coordinate,
    no origin, no provider message, no day, no exception type. The whole value is
    one of these members, so there is nowhere for one to sit.
    """

    TRANSPORT_FAILED = "transport_failed"
    """The channel could not be opened, verified or continued (ADR-0191 §1).

    A statement about this system's own reach — a refused connection, a TLS
    failure, a channel closed mid-response — and never about what the provider
    said, which is :attr:`PROVIDER_REFUSED`. A redirect belongs here too: a
    forecast read follows none and makes no second request (ADR-0260 §3).

    An **upstream** ``TimeoutError`` raised inside the bound for the transport's
    own reasons is this member and never :attr:`DEADLINE_EXPIRED` (ADR-0241 §7)."""

    DEADLINE_EXPIRED = "deadline_expired"
    """The bound the caller handed this call expired before it answered (§4).

    ADR-0241 §1's ``timeout`` covers the seam's own work — the revalidation, the
    credential read, the channel, the response read and the transcription. So this
    member says the seam stopped waiting on the stages it owns; it does not say the
    provider stopped working, and **no caller assumes the request did not leave**
    (ADR-0029 §4's cooperative limit).

    **A disposition and never a retry** (ADR-0260 §3). An interrupted read is not
    re-run on the turn that asked for it: *one ask is one read*, absolutely."""

    RESPONSE_TOO_LARGE = "response_too_large"
    """The response passed ``forecast_max_response_bytes`` (ADR-0260 §11).

    The read stopped one octet past the bound, the channel was closed, **nothing
    was parsed** and no record was minted. Distinct from
    :attr:`PROVIDER_REFUSED` because the provider may have answered perfectly
    well: what happened is that this system declined to buy the answer. It
    **establishes a contact** all the same (§10), because the octets it was decided
    from had already arrived."""

    PROVIDER_REFUSED = "provider_refused"
    """The provider answered something a forecast cannot be read from, **or**
    ADR-0148 §6 refused before a byte was transmitted (ADR-0260 §6).

    Two causes under one member, and no value separates them: a non-success
    status, a body that is not the shape the provider documents, and each of
    ADR-0148 §6's four pre-transmit conditions — an unconnectable reference, a
    record recorded for another identity, a record that moved across the
    credential read, and a slot the keyring holds nothing under.

    **It therefore establishes nothing either way about a contact** (§10, ADR-0264
    §13's third arm read at this seam): a site holding this member cannot tell
    whether octets arrived, and ADR-0264 §1 ranks silence above a false claim."""

    UNATTESTED = "unattested"
    """The response declared no report instant, or none that can be read (§5).

    ADR-0092 §3 binds as written: ``reported_at`` is the instant the provider's own
    response declares, and there is **no substitute** — not the instant we sent,
    not the instant we received, not a clock this system read. A value in that
    position which cannot be read as one is not a declared instant, so it lands
    here rather than licensing a fallback.

    **It establishes a contact** (§10): this system reaches it only from octets the
    provider's channel had already returned."""

    NO_RESULT = "no_result"
    """The response described no day, or ADR-0260 §5 dropped every one it did.

    One member for both, because an operator acts on neither: the read reached the
    provider, was attested, and yielded nothing this system will carry. §5's drops
    — a day missing a documented field, supplying one as ``null`` or as a type the
    documented format does not admit; a day whose transcription passes
    ``forecast_max_day_chars``; a day whose declared offset is absent or
    unreadable; and a day the response names more than once, dropped in every one
    of its rows — all end here where they take the last day with them.

    **It maps to no ``ForecastDisposition``** (§8): a read that reached the provider
    and was answered is a completed servicing whose returned count is zero, which
    ADR-0226 §9 already records."""


def _check_minted_by_a_forecast(
    record: MemoryRecord, *, reported_at: datetime | None, reported_by: str
) -> None:
    """Refuse a record ADR-0260 §5's minting clause would not have produced.

    Written out here rather than inside :class:`ForecastOutcome`'s validator so that
    each condition is one branch a reader can find, and so that the validator itself
    stays one statement of the exactly-one rule — which is
    :func:`_check_minted_by_a_search`'s own division and not a second one.

    **Every condition is decidable over this record's own fields.** None reaches for
    a bound, a clock, a store or a configuration: ``forecast_max_days``,
    ``forecast_max_day_chars`` and ``forecast_max_response_bytes`` are ``Settings``
    the *configured* forecaster enforces (ADR-0260 §4), so this model carries none of
    them and validates identically in every deployment.

    Args:
        record: One record the outcome carries.
        reported_at: The outcome's own report instant.
        reported_by: The ``reported_by`` the outcome's **first** record carried,
            which every later one must equal — a shared value rather than the
            forecaster's own ``name``, which this value cannot check, holding no
            forecaster (ADR-0260 §4).

    Raises:
        ValueError: If the record is not ``SEMANTIC``, is not ``EXTERNAL``-sourced,
            carries evidence, carries topics, carries an ``about_person``, carries a
            validity window that is not fully open, is attested to another instant,
            is attested to another source, or declares no bounded extent.
    """
    if record.kind != "semantic":
        msg = f"a forecast read mints SEMANTIC records; got a {record.kind!r} one"
        raise ValueError(msg)
    provenance = record.provenance
    if provenance.source is not MemorySource.EXTERNAL:
        msg = f"a forecast read mints EXTERNAL-sourced records; got {provenance.source}"
        raise ValueError(msg)
    if provenance.evidence:
        # ADR-0260 §5: `evidence` is empty. A minted record is supply for one turn and
        # resolves in no store (§11), so a citation on it would point at nothing a
        # later reader could reach.
        msg = "a forecast read mints records carrying no evidence"
        raise ValueError(msg)
    if record.topics:
        msg = "a forecast read mints records carrying no topics (ADR-0260 §5)"
        raise ValueError(msg)
    if record.about_person is not None:
        msg = "a forecast read mints records carrying no about_person (ADR-0260 §5)"
        raise ValueError(msg)
    if record.validity.valid_from is not None or record.validity.valid_until is not None:
        # ADR-0260 §5: "`validity` is fully open and no lane sets it to the day the
        # record is about." ADR-0045 §2 makes the envelope window an operational
        # property, and ADR-0252 §3 forbids reading it as coverage on any kind; a
        # producer setting it to the forecast's own day would hand the prohibited
        # fallback exactly the value it was written to refuse.
        msg = (
            "a forecast record's validity is fully open, and never the day it is "
            "about (ADR-0260 §5, ADR-0045 §2)"
        )
        raise ValueError(msg)
    attestation = provenance.attestation
    if attestation is None or reported_at is None or attestation.reported_at != reported_at:
        # The clause ADR-0092 §3 rests on: the record's instant is *the response's*,
        # so a producer that reached for a clock of its own cannot construct the value
        # at all. A record disagreeing with its outcome about when the source spoke is
        # two answers in one value.
        msg = (
            "every record a forecast read mints is attested to the outcome's own "
            "report instant (ADR-0260 §4, ADR-0092 §3)"
        )
        raise ValueError(msg)
    if attestation.reported_by != reported_by:
        msg = (
            "every record a forecast read mints carries one shared reported_by "
            f"(ADR-0260 §4); got {attestation.reported_by!r} beside {reported_by!r}"
        )
        raise ValueError(msg)
    extent = attestation.extent
    if extent is None or extent.extends_from is None or extent.extends_until is None:
        # ADR-0260 §4: "carries an `extent` that is a constructible half-open
        # interval". A day is bounded at both ends, so a ray is not one — and a record
        # with no extent at all is the value ADR-0252 §3 would find nothing to compose
        # a `supported` window from, which is the whole reason this decision was
        # bought.
        msg = (
            "every record a forecast read mints declares a bounded half-open extent "
            "over the day it is about (ADR-0260 §4, §5; ADR-0117 §2)"
        )
        raise ValueError(msg)


class ForecastOutcome(BaseModel):
    """What one forecast read produced: records, or a refusal (ADR-0260 §4).

    **Exactly one of the two, enforced here rather than by a caller.** Neither both
    nor neither: a value carrying both would be two answers wearing one outcome's
    name, and one carrying neither would be an outcome a servicing could read as an
    answered read — and would then report a provider the turn never reached.

    **Every condition below is *structural* — over this value's own fields** — so
    none of them reaches for a bound, a clock, a store or a configuration. That is
    :class:`SearchOutcome`'s own shape and for its stated reason: conditions on the
    model are decidable in any process and true of every ``Forecaster`` this system
    ever wires, **the canonical fake included**.

    **What is deliberately *not* enforced here is the producer's** (§4), not being
    decidable over this value's own fields: ``confidence``'s figure,
    ``derived_from_external``, ``placement``, the transcription, the extent's
    agreement with the day the provider named, and ``reported_by``'s **equality with
    the forecaster's own** ``name`` — which this outcome cannot check, holding no
    forecaster. What it *can* check is that every record agrees with every other
    about who reported them, and it does.

    **It carries no count of the days §5 dropped** (§7). A drop count is a
    within-ask fidelity fact, and ADR-0226 §9 refuses that class in terms; the
    honest consequence — that a response this system thinned is not distinguishable
    from one the provider gave thin — is ADR-0260 §14's deferral rather than a gap
    this type fills.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reported_at: UtcInstant | None = Field(
        default=None,
        description=(
            "The instant the provider's own response declared, on the provider's "
            "own clock (ADR-0260 §5, ADR-0092 §3). Never the instant we sent, the "
            "instant we received, or any clock this system read. ``None`` where the "
            "read was refused."
        ),
    )
    records: tuple[MemoryRecord, ...] = Field(
        default=(),
        description=(
            "One record per day the provider's answer covered and §5 kept, in the "
            "order the provider returned them (ADR-0260 §5). Empty where the read "
            "was refused."
        ),
    )
    refusal: ForecastRefusal | None = Field(
        default=None,
        description=(
            "Why no record was produced (ADR-0260 §4). ``None`` where records "
            "were. A **class** and nothing else: no place, no coordinate, no "
            "origin, no day, no provider message."
        ),
    )

    @model_validator(mode="after")
    def _records_or_a_refusal(self) -> ForecastOutcome:
        """Refuse an outcome that half-says two things (ADR-0260 §4).

        Raises:
            ValueError: If a refusal is paired with a record or a report instant,
                or if no refusal is paired with no report instant or no record.
        """
        if self.refusal is not None:
            if self.records:
                msg = "a forecast outcome carries records or a refusal, never both"
                raise ValueError(msg)
            if self.reported_at is not None:
                msg = "a refused forecast read declares no report instant"
                raise ValueError(msg)
            return self
        if not self.records:
            # **The *neither* case first, and that ordering is the decision** (ADR-0260
            # §13's arm (j)): an outcome accepted while empty and unrefused is one a
            # servicing can read as an answered read, so the refusal a bare
            # `ForecastOutcome()` earns should name *that* mistake rather than the
            # missing instant it also has.
            msg = "a forecast outcome carries records or a refusal, never neither"
            raise ValueError(msg)
        if self.reported_at is None:
            msg = "a forecast outcome that carries no refusal declares a report instant"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _every_record_is_an_attested_external_semantic(self) -> ForecastOutcome:
        """Refuse a record ADR-0260 §5 would not have minted.

        Raises:
            ValueError: If any record fails one of
                :func:`_check_minted_by_a_forecast`'s conditions.
        """
        if not self.records:
            return self
        first = self.records[0].provenance.attestation
        # The first record's own attestation is what the rest are compared against.
        # `None` is refused by the check below with every other half-answer, so the
        # fallback here is a value that cannot equal a well-formed `Identifier`
        # rather than a second refusal path.
        shared = "" if first is None else first.reported_by
        for record in self.records:
            _check_minted_by_a_forecast(record, reported_at=self.reported_at, reported_by=shared)
        return self


# --- egress identity, ahead of the planning types (ADR-0259 §1) -------------
# The visible-text refinements and the three egress declarations an effect key is
# built from, declared **here** rather than beside the egress binding where
# ADR-0150's own lane put them. ADR-0259 §1 builds :class:`EffectKey` out of a
# tool id, a parameters digest, a :class:`BoundAccount`, a transport endpoint and
# a tuple of :class:`CanonicalDestination`, and that key is a field of
# :class:`StepTransition` and — through :class:`EffectRecord` — of
# :class:`PlanExport`, both declared far above the old positions. That is the case
# the comment above :data:`Identifier` already rules on and the ADR-0252 evidence
# block already took one level up from a scalar: "a forward reference plus
# ``model_rebuild`` would have kept the old positions at the cost of making two
# `core` types depend on an import-order side effect, so the primitives moved
# instead of the models". Nothing about any of them changed.


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


def _rejecting_invisible(value: str) -> str:
    """Reject text that renders as nothing, returning it **unchanged**.

    :func:`_visible_identifier` is the same test with a normalising half; this is
    the rejecting half alone, and the asymmetry is the decision. Every string in
    this surface is compared against something outside it — a supplied form
    against an argument the callable will transmit, an account identity against
    the identity a connection record currently holds — so stripping one here
    would be `core` rewriting a bound value, which is exactly what ADR-0148 §4's
    third clause forbids between the ruling and transmission. ADR-0096 §2 states
    the general rule this follows: **a faithful copy may tighten only in ways
    that reject.**

    **The message names no value**, which is ADR-0150 §8's second clause: a
    refusal message reaches a log, and the values here are recipient addresses.

    Raises:
        ValueError: If nothing in the value renders.
    """
    if not _has_visible_text(value):
        msg = "must contain visible text"
        raise ValueError(msg)
    return value


type _VisibleUnchangedText = Annotated[EncodableText, AfterValidator(_rejecting_invisible)]
"""Text that renders as something, byte-for-byte as supplied (ADR-0150 §3, §7)."""


class DestinationProtocol(StrEnum):
    """The protocol under whose rules a destination's canonical form was computed.

    A member is a **safety claim**, not a label: its whole content is a ruling
    about which two supplied forms denote one recipient (ADR-0148 §2's second
    clause). ADR-0150 §3 therefore fixes this membership and requires a ratified
    contract ADR for every further member, stating which equivalences that
    protocol establishes and which it does not.

    An enum rather than a ``str`` for ADR-0021 §1's canonicalisation-per-caller
    reason: a string field admits ``"smtp"`` and ``"SMTP"`` as two protocols, and
    two integrations that disagreed would produce a false mismatch at execution.

    ``SMTP`` asserts exactly the equivalences ADR-0150 §3 states — local parts
    byte-identical, domains equal after ASCII lowercasing — and **authorises
    nothing**: it neither implies a canonicaliser exists, nor registers a tool,
    nor permits any transmission. The canonicaliser itself lives at the seam
    (ADR-0148 §2's sixth clause), never here; a copy of the rule in `core` would
    be the second canonicaliser that clause exists to forbid.

    ``HTTPS`` is ADR-0231 §8's member, and the same two sentences hold of it. Its
    ratified contract ADR is that section: the canonical form is the **origin** —
    ``https://host:port``, the scheme, the host and the port and nothing below
    them — and the equivalences it establishes are **exactly three**: the scheme
    differs only by ASCII case, the host differs only by ASCII case, and one form
    omits the port where the other states ``443``. Six are stated as *not*
    established and are written down there so no lane infers one: a name against
    an address it resolves to, a trailing dot against none, a percent-encoded
    octet against its decoded form, an internationalised host against any
    ASCII-compatible encoding, ``http`` against ``https``, and anything at all
    involving a path, a query or a fragment. It **authorises nothing** either: it
    registers no tool, permits no transmission, and implies no canonicaliser
    beyond the one §8 fixes at the seam.
    """

    SMTP = "smtp"
    HTTPS = "https"


class BoundAccount(BaseModel):
    """The connected account a call is made through, as the ruling fixed it.

    **Not** ADR-0151 §4's ``ConnectedAccount``, and not a narrowing of it. That
    model is the *live connection record* and carries ``revision`` and ``state``,
    both of which move while a parked ruling stands; this one is the **snapshot
    the ruling was taken over**, which ADR-0148 §1 requires not to move after the
    ruling at all. Carrying the live record here would put a ``revision`` inside
    the value :meth:`PermissionDecision.authorises` compares, so a
    re-provisioning between the confirmation and the answer would make a parked
    ``CONFIRM`` unanswerable (ADR-0150 §7).

    **Two facts, not one.** ADR-0148 §6 binds an account by its identity *and*
    its connection reference. Two connectable records can hold one identity, so
    an identity-only account compares equal across them and a standing grant
    would cover a record the user never granted; a reference is stable across a
    rotation by design, which is what makes it survive a re-provisioning to a
    *different* account. Either alone is a destination two different accounts
    satisfy.

    **No credential slot.** A :class:`SecretName`, its ``name``, and any string
    identifying a keyring entry are forbidden here and everywhere in this surface
    (ADR-0150 §7). `core` cannot distinguish a slot name from a reference — both
    are strings — so that is a rule checked where the connection record is read,
    not a type, and this docstring claims no protection it does not have.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    identity: _VisibleUnchangedText = Field(
        description=(
            "The durable, user-recognisable name recorded when the account was "
            "connected. Visible text because ADR-0148 §8's fourth clause shows it "
            "to the user at the moment they decide, and an identity that rendered "
            "as nothing would leave the confirmation with nothing to say about "
            "whose account this is."
        )
    )
    reference: DurableIdentifier = Field(
        description=(
            "Names the account's connection record (ADR-0149 §3). Never shown to "
            "the user — ADR-0148 §6 says it is not something an account can be "
            "recognised by, and §8's fourth clause bars it from the confirmation."
        )
    )


class CanonicalDestination(BaseModel):
    """One member of ADR-0148 §2's canonical destination set (ADR-0150 §3).

    **Exactly two well-formed shapes, and it refuses at construction to depart
    from either**: a *selected recipient*, carrying a protocol and a canonical
    form and no account; or *the connected account* the call is made to,
    carrying an account and neither of the other two. No member carries all
    three, none carries neither shape, and there is no third kind.

    The account is a **member** rather than an alternative to the members, and
    two earlier drafts failing in opposite directions are why. One defined the
    derived set to be empty exactly where ADR-0148 §2's third clause says that
    set *is* the connected account, so a policy reading ADR-0148 §8's third floor
    literally would refuse every resolution call. The other split the name in two
    and left the set with no value shape at all, so every consumer would branch
    and invent its own comparison — this document's own title failing on the
    document. One type, total for a consumer that never has to ask which case it
    is in before comparing.

    The account case states no protocol deliberately: an account is not named
    under any protocol that establishes equivalences between supplied forms, and
    minting a member for "the account" would require stating which equivalences
    it establishes, of which it has none.

    **Equality is over every field.** A canonical form is never compared across
    protocols, and an account member never equals a selected recipient, whatever
    strings the two hold.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    protocol: DestinationProtocol | None = Field(
        default=None, description="Set on a selected recipient; absent on the account."
    )
    canonical: _VisibleUnchangedText | None = Field(
        default=None, description="Set on a selected recipient; absent on the account."
    )
    account: BoundAccount | None = Field(
        default=None, description="Set on the connected account; absent on a recipient."
    )

    @model_validator(mode="after")
    def _is_one_of_the_two_shapes(self) -> CanonicalDestination:
        """Refuse every combination ADR-0150 §3's two-shape clause excludes.

        A bag of optional fields would admit eight combinations of which six are
        meaningless. The distinction ADR-0150 §1 draws against partial states is
        about facts that are only meaningful together and can arrive apart; here
        the variants are exactly two and a validator makes every other
        combination unconstructable.

        **The message names no value**, per ADR-0150 §8: which fields are present
        is what names the defect, and the strings are recipient addresses.

        Raises:
            ValueError: If the member is neither a selected recipient nor the
                connected account.
        """
        recipient = self.protocol is not None and self.canonical is not None
        if recipient and self.account is None:
            return self
        if self.account is not None and self.protocol is None and self.canonical is None:
            return self
        msg = (
            "a canonical destination is either a selected recipient (a protocol and a "
            "canonical form, no account) or the connected account (an account, neither "
            "of the other two)"
        )
        raise ValueError(msg)


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
    """The tool's own upstream cancelled or aborted the operation (ADR-0031 §3).

    A remote job the provider stopped, a batch the service abandoned. **The seam
    never synthesises it**: a cancellation the seam observes propagates as a
    ``CancelledError`` and never becomes a result, and a deadline the seam owns is
    :attr:`TIMED_OUT`. Retargeted from ADR-0029 §4's "cancelled before completing",
    which described a seam branch no conforming ``invoke`` can construct.
    """

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
    # True on ADR-0029 §3's general test, which is the only ground left for it:
    # a repeat of the same call could plausibly succeed. The value is unchanged,
    # but ADR-0029's "because the cancellation was ours" is not — under ADR-0031
    # §3 the cancellation is the tool's upstream's, never the seam's.
    ToolFailureKind.CANCELLED: True,
    ToolFailureKind.REFUSED: False,
    ToolFailureKind.INTERNAL: False,
}


# --- planning: the write path, deletion, export (ADR-0014 §5, ADR-0004 §6) ---
# A transition is a command rather than a caller-built state, which is what
# keeps the transition graph authoritative. `PlanExport` is the portable
# snapshot ADR-0004 §6's data rights require.


class PlanExport(BaseModel):
    """A portable snapshot of planning state (see ADR-0014 §5, ADR-0004 §6).

    **``schema_version`` is 19 because the document lost the old path's members**
    (ADR-0309 §5): ``goals``, ``plans``, ``executions``, ``attempts``, ``questions``,
    ``evidence`` and ``effects`` retired with the goal, plan, attempt, question,
    evidence and goal-scoped effect families they carried. What is left is the
    phases' planning state: the stop records and acting's effect records. One ground,
    and sufficient on its own: a reader of 18 expects members this document no longer
    has. **No reader for 18 exists or is written** (ADR-0309 §6:4): the cutover starts
    on a fresh data directory, so no store holds a document of an earlier shape.

    **It was 18 because the document gained ``activation_effects``** (ADR-0306 §6):
    acting's effect records, each pointing at the activation that made it, in the order
    they were claimed. A record names an activation and a decision, neither of which
    the document carries, so ADR-0014 §5's closure rule is **extended by nothing**; the
    only constraint stated over the member is that no record id appears twice.

    **It was 17 because the document gained ``stopped_activations``**
    (ADR-0297 §1): the activation ids the store holds a stop record for, carried so
    that ADR-0004 §6's view and export limbs reach the one datum that decision adds
    rather than taking a scope on them. A stop record names no other record, so
    ADR-0014 §5's closure rule is extended by nothing here either, and the only
    constraint stated over it is that no id appears twice.

    **A stored-record version and not a wire ground**: ``PlanExport`` crosses no frame
    and is emitted by no peer.

    **No migration is owed.** ``PlanStore`` offers ``export`` and no ``import``,
    ``restore`` or ``load``, so nothing in this system ever validates a ``PlanExport``
    it did not just construct. ADR-0039 §10's rule carries forward unchanged: an export
    of an earlier shape is not readable by this contract at any version, and if an
    import path is ever contracted, accepting or refusing one is that ADR's decision and
    is not settled here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[19] = Field(
        default=19,
        description=(
            "Shape of this export, pinned to exactly 19 (ADR-0039 §10, ADR-0309 §5): an "
            "export outlives the code that wrote it, so the label must be a fact about "
            "the document rather than a producer's unchecked claim. ``Literal[19]`` "
            "refuses every other value — a document of any earlier shape does not "
            "validate against this contract at all — so the advertised version cannot "
            "be mislabelled."
        ),
    )
    exported_at: UtcInstant
    stopped_activations: tuple[Identifier, ...] = Field(
        default=(),
        description=(
            "The activation ids the store holds a stop record for (ADR-0297 §1). A "
            "record carries the id alone: no instant, no reason, no conversation and "
            "no content."
        ),
    )
    activation_effects: tuple[ActivationEffect, ...] = Field(
        default=(),
        description=(
            "Acting's effect records, finished or not, in the order they were claimed "
            "(ADR-0306 §6)."
        ),
    )

    @model_validator(mode="after")
    def _an_activation_effect_appears_once(self) -> PlanExport:
        """Refuse a document carrying one effect record id twice (ADR-0306 §6:2).

        A store refuses a claim of an id it already holds, so a duplicate states a
        record the store cannot hold.

        Raises:
            ValueError: If an effect record id appears more than once.
        """
        ids = [record.id for record in self.activation_effects]
        if len(set(ids)) != len(ids):
            msg = "export contains duplicate activation effect ids"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _a_stop_record_appears_once(self) -> PlanExport:
        """Refuse a document naming one stopped activation twice (ADR-0297 §1).

        A store holds at most one stop record per activation — ``record_stop`` is
        idempotent — so a document carrying a duplicate states a record the store
        cannot hold.

        Raises:
            ValueError: If an activation id appears more than once.
        """
        if len(set(self.stopped_activations)) != len(self.stopped_activations):
            msg = "export contains duplicate stopped activation ids"
            raise ValueError(msg)
        return self


# --- a spoken answer's delivery: what a device reports having played --------
# ADR-0205's three values. Declared **here**, above the conversation block,
# rather than in the speech block at the foot of this module: §3 put the fact on
# the turn index's row, so the type it is spelled with had to exist by the time
# that model was built, and ADR-0283 §6's delivery rows keep the placement. The
# three depend on nothing but `timedelta`, `StrEnum` and
# `Identifier`, so nothing about the speech block's own ordering rule is weakened
# by the split — what is below stays below because `SpokenAudio` and `SpokenTurn`
# depend on `TurnOutcome`, and none of these three does.


# --- speech: the recording and the rendering (ADR-0200 §9) -------------------
# The one shape audio takes on a boundary-crossing type, and the one place the
# base64 convention is written down. Nothing here knows what a codec is:
# `models/` decodes the container and encodes the rendering, and this module
# holds only what is intrinsic to the value (ADR-0016 §2).
#
# **Declared here rather than at the foot of this module** (ADR-0206 §6). It used
# to sit last, "because nothing above it depends on it", and something above it now
# does: §6 gives `NotificationDelivery` a `SpokenAudio | None`, so the type that
# member is spelled with has to exist by the time that model is built. This is
# ADR-0205's split repeated one block up — these six declarations depend on nothing
# but `NonBlankEncodableText`, and what stays at the foot stays there because
# `SpokenTurn` depends on `TurnOutcome` and these do not.


#: The base64 alphabet RFC 4648 §4 fixes, without its padding character — which
#: is admitted separately below, because where it may appear is positional and
#: membership alone would accept ``"=QQ="``.
_BASE64_ALPHABET: Final = frozenset(string.ascii_letters + string.digits + "+/")

#: How many base64 characters encode one group of three octets. A padded encoding
#: is a whole number of these, which is the first thing a malformed value fails.
_BASE64_GROUP: Final = 4


def _base64_audio(value: str) -> str:
    """Require standard, padded, canonical base64 (ADR-0200 §9).

    Four properties, checked in the order that lets each message name a defect
    the reader can act on: the value is over RFC 4648 §4's 64-character alphabet
    plus ``=``; its length is a whole number of four-character groups; it decodes
    without error; and re-encoding what it decodes to **reproduces it byte for
    byte**.

    **Canonicality is not decoration.** Base64 admits distinct spellings of one
    byte string — a final group whose unused bits are non-zero, and RFC 4648 §5's
    URL-safe alphabet among them. Without this clause :class:`SpokenAudio` would
    have two values for one recording, ``wire/codec.py``'s canonical encoding
    would faithfully preserve the difference, and ADR-0087 §4's normalises-nothing
    rule would make them two values all the way down. Refusing the non-canonical
    spelling is what makes one recording one value. It is also what makes a
    decoder that quietly ignores stray characters unable to admit a payload a
    stricter peer refuses.

    **The value is never normalised**: what a caller passed is what crosses the
    wire and what :meth:`SpokenAudio.decoded` reverses. That is
    :data:`NonBlankEncodableText`'s own posture and ADR-0096 §2's rule for a value
    a later comparison may be made against — and here it is stronger than a
    convention, because a rewritten spelling would be a *different recording's*
    encoding of the same octets.

    **The message names the class of defect and the position, and never echoes
    the value** (ADR-0200 §9). This is :func:`encodable_text`'s stated ground and
    it bites harder here: the value is a recording of the owner's voice, and an
    error message is the one place ADR-0200 §8's retention rule cannot see.

    Raises:
        ValueError: If the value is not padded, canonical, standard base64.
    """
    offender = next(
        (
            index
            for index, character in enumerate(value)
            if character not in _BASE64_ALPHABET and character != "="
        ),
        None,
    )
    if offender is not None:
        msg = (
            f"base64 audio must use RFC 4648 §4's alphabet with padding; "
            f"the character at position {offender} is outside it"
        )
        raise ValueError(msg)
    if len(value) % _BASE64_GROUP:
        msg = (
            f"base64 audio must be padded to a multiple of {_BASE64_GROUP} characters, "
            f"and this value is {len(value)} long"
        )
        raise ValueError(msg)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        msg = "base64 audio must decode; this value does not"
        raise ValueError(msg) from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        msg = (
            "base64 audio must be canonical, so that one recording has one spelling; "
            "re-encoding this value's octets does not reproduce it"
        )
        raise ValueError(msg)
    return value


type Base64Audio = Annotated[NonBlankEncodableText, AfterValidator(_base64_audio)]
"""Standard, padded, canonical RFC 4648 §4 base64, never normalised (ADR-0200 §9).

Layered on :data:`NonBlankEncodableText` rather than on :data:`EncodableText`,
and the blank half is not redundant with the group-length check: ``""`` has a
length that is a multiple of four and decodes to ``b""``, so without the
non-blank refinement an empty recording would be a well-formed value. A
recording carrying no octets is not a recording.

**Why base64 text rather than a ``bytes`` field.** ``bytes`` is the more truthful
Python type and ADR-0200 §9 declines it deliberately: ADR-0087 §2c's scalar table
has no ``bytes`` row, ``wire/codec.py``'s ``project`` has no branch for one, and
adding both would put the base64 convention in two places that must agree
forever — a hand-written projection branch and a far-side decoder — where a
silent disagreement corrupts audio rather than failing. Here the convention is
one validator on one type. The row stays available under ADR-0200 §11's named
condition.
"""


class SpokenAudio(BaseModel):
    """One recording or one rendering, and the container it is in (ADR-0200 §9).

    **Exactly two members.** What the octets are, and what they are encoded as —
    the second being what tells a decoder how to read the first, and what
    ADR-0200 §1 makes a transcriber and a synthesizer declare their support for
    before either is called.

    Frozen, because it is the value ADR-0200 §6's bound is measured on and
    ADR-0200 §1's ``formats`` check is made against: a holder that could reassign
    ``media_type`` after the check would be holding a different recording from
    the one that was admitted.

    **Nothing here retains it and nothing here logs it** (ADR-0200 §8). The type
    carries no rendering of itself for a log: ``BaseModel.__repr__`` would put a
    recording into any message that interpolated the model, so a component on
    this path writes ``media_type`` and a length, or nothing.

    Attributes:
        content: The octets, base64 as :data:`Base64Audio` fixes it. Never
            normalised, so what a caller passed is what :meth:`decoded` reverses.
        media_type: The container-and-codec ``content`` is encoded in. Refused by
            a transcriber or a synthesizer whose ``formats`` does not name it,
            rather than guessed at (ADR-0200 §1, §9).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: Base64Audio = Field(
        description="The audio's octets, as padded canonical RFC 4648 §4 base64.",
    )
    media_type: SpokenAudioFormat = Field(
        description="The container-and-codec the octets are encoded in.",
    )

    def decoded(self) -> bytes:
        """Return the octets :attr:`content` encodes.

        The decoding convention is written **once**, here, so no consumer
        re-derives it and no two consumers can disagree about it (ADR-0200 §9).
        Validation already established that this succeeds and that it round-trips,
        so this raises nothing a caller must handle.

        Returns:
            The decoded audio.
        """
        return base64.b64decode(self.content, validate=True)


# --- conversations: the durable thread -------------------------------------
# ADR-0074's conversation and its portable snapshot. A conversation is durable,
# server-side state with an identity of its own; its history is the episodes on
# its channel in the ``MemoryStore``, in number order, and nothing here indexes
# them (ADR-0283 §1, §4, §6). Both frozen (ADR-0068), every instant a
# `UtcInstant` (ADR-0023, ADR-0030).


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
    ``ConversationStore.record_turn`` once a conversational episode has landed on
    the conversation's channel (ADR-0283 §6:2), and unset until one does — which is
    what tells an empty conversation from one whose first turn landed at once.

    ``deleted_at`` is §8's tombstone stamp rather than a status: a stamped
    conversation is absent from every read that presents it, makes every later
    ``record_turn`` write nothing, and survives so the deletion sweep can find it
    and delete every episode on its channel (ADR-0283 §8).

    No cross-field ordering is validated. ``started_at``, ``last_active_at`` and
    ``last_turn_at`` all come from an injected clock, which this project never
    promises is monotonic (``core/clock.py``), so a rule like
    ``last_active_at >= started_at`` would make a legitimate clock adjustment
    unrepresentable rather than catching a bug.

    **There is no observation watermark** (ADR-0285 §4). The member ADR-0212 §1
    gave the conversation is removed with the observer that wrote it, and nothing
    replaces it.
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


# --- the chat space: transcripts, devices and the change stream --------------
# ADR-0293's hosted medium. A conversation keeps its own transcript of messages
# (§5), the chat space keeps "my devices" and each conversation its own devices
# (§3), every change to the chat space gets a sequence number (§5), and the chat's
# reader keeps its bookkeeping beside them (§6). All frozen (ADR-0068), every
# instant a `UtcInstant` (ADR-0023, ADR-0030). Devices are opaque identifiers here:
# registering a device and its roles are the device session's.

#: The size bound on a message's text (ADR-0293 §4:7, §7:2, §7:3), in characters. The
#: ADR names a bound and leaves its figure to the implementation; it is carried on the
#: type, so a message over it cannot be constructed and the refusal is the send's own
#: error (§4:7) rather than something each store re-derives.
TRANSCRIPT_MESSAGE_MAX_CHARS: Final = 16_000

#: How many options a question message may carry (ADR-0293 §5:2's *Options* row), and
#: how long each may be. Options are shown as buttons, so both are small.
MESSAGE_OPTIONS_MAX: Final = 12
MESSAGE_OPTION_MAX_CHARS: Final = 200

#: How many devices one set of devices may name, "my devices" or a conversation's.
CHAT_DEVICES_MAX: Final = 64

#: How many entries the snapshot a device-scoped change carries holds at most
#: (ADR-0298 §7:7): the newest of the messages recorded at or before the change. The
#: snapshot size ADR-0293 leaves open (What stays open), the figure a transcript read's
#: own snapshot defaults to; the engine shortens it further to fit (§7:8).
CHAT_SNAPSHOT_ENTRIES: Final = 50

#: One past the largest position or sequence number: the signed 64-bit ceiling a
#: SQLite ``INTEGER`` holds (ADR-0073 §2's bound, inherited).
_CHAT_INT_BOUND: Final = 2**63

type _OptionText = Annotated[NonBlankEncodableText, Field(max_length=MESSAGE_OPTION_MAX_CHARS)]


class MessageAuthor(StrEnum):
    """Who wrote a transcript message (ADR-0293 §5:2, the *Author* row).

    Only the user's messages start activations and can carry the user's authority
    (ADR-0293 §4:8, §6:1); the assistant's own messages never start one.

    Attributes:
        USER: The user, established, writing from one of the conversation's devices.
        ASSISTANT: The assistant, writing through the chat's writer.
    """

    USER = "user"
    ASSISTANT = "assistant"


class DeviceAccess(StrEnum):
    """What a device may do as one of a conversation's ends (ADR-0293 §3:5).

    A device may be an end for writing, for reading, or for both. A watch may only
    read.

    Attributes:
        READ: The device reads the conversation and may not write in it.
        WRITE: The device writes in the conversation and is not shown it.
        READ_WRITE: The device does both.
    """

    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"

    @property
    def writes(self) -> bool:
        """Whether this access lets a device write in the conversation."""
        return self is not DeviceAccess.READ

    @property
    def reads(self) -> bool:
        """Whether this access lets a device be shown the conversation."""
        return self is not DeviceAccess.WRITE


class ChatDevice(BaseModel):
    """One device in a set of devices: "my devices", or a conversation's (ADR-0293 §3).

    The device is an opaque identifier here. What a device is, how it is registered and
    which roles it holds are the device session's; this record says only that the user
    chose it, and for what.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: Identifier = Field(description="The device, as the device session names it.")
    access: DeviceAccess = Field(description="Writing, reading, or both (ADR-0293 §3:5).")


def checked_chat_devices(devices: object) -> tuple[ChatDevice, ...]:
    """Check a set of devices and return it in its one order, ``device_id`` ascending.

    Shared by every ``ConversationStore`` implementation, so each refuses exactly the
    same sets (ADR-0293 §3). A bare ``str`` is refused by name rather than read as its
    characters, and the sequence is read **once**, before anything else, so a caller's
    later edit cannot reach the result (ADR-0065).

    Returns:
        The devices, ``device_id`` ascending.

    Raises:
        ValueError: If ``devices`` is not a sequence of :class:`ChatDevice`, names one
            device twice, or holds more than :data:`CHAT_DEVICES_MAX` devices.
    """
    if isinstance(devices, (str, bytes)) or not isinstance(devices, Sequence):
        msg = f"devices must be a sequence of ChatDevice, got {describe_untrusted(devices)}"
        raise ValueError(msg)
    held = tuple(devices)
    if len(held) > CHAT_DEVICES_MAX:
        msg = f"a set of devices holds at most {CHAT_DEVICES_MAX}, got {len(held)}"
        raise ValueError(msg)
    for one in held:
        if not isinstance(one, ChatDevice):
            msg = f"devices holds something that is not a ChatDevice: {describe_untrusted(one)}"
            raise ValueError(msg)
    ids = [one.device_id for one in held]
    if len(set(ids)) != len(ids):
        msg = "a set of devices names one device more than once"
        raise ValueError(msg)
    return tuple(sorted(held, key=lambda one: one.device_id))


# --- the device session (ADR-0298) -------------------------------------------

#: The hub's own machine as a device, in every configuration and whether or not the
#: hub has an overlay identity (ADR-0298 §3:1). A stable id keeps "my devices" and a
#: conversation's devices unchanged when the remote listener is turned on or off.
HUB_DEVICE_ID: Final = "hub"


class DeviceRole(StrEnum):
    """A role the device roster records for a device (ADR-0298 §4:1, §10:1).

    Two of ADR-0296 §2's three roles. The third, the user's end of conversations, is
    no roster entry: it is a device's membership of "my devices" and of
    conversations, which the conversation store keeps (ADR-0293 §3), so it is not a
    member here.

    Attributes:
        COMMANDS: The role of source of commands and queries.
        SPOKES: The role of host of spokes, which no device holds until the first
            device-hosted spoke (ADR-0296 §3:4).
    """

    COMMANDS = "commands"
    SPOKES = "spokes"


class RequestingDevice(BaseModel):
    """The device a request is served for, decided by the wire server (ADR-0298 §2:3).

    The device ``acting_for`` names where a request carries the member and the hub
    accepts the name, and otherwise the connecting device (§2:1). It reaches the
    engine through :mod:`ai_assistant.core.device_context` rather than through any
    ``AssistantEngine`` argument (§2:2).

    Attributes:
        device_id: The device's id: an overlay identity, or :data:`HUB_DEVICE_ID`
            for the hub's own machine (§3:1).
        roles: The roles the roster records for it at dispatch (§4:1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: Identifier
    roles: frozenset[DeviceRole] = frozenset()

    @property
    def is_hub(self) -> bool:
        """Whether this is the hub's own machine (ADR-0298 §3:1)."""
        return self.device_id == HUB_DEVICE_ID


#: The hub's own machine as a requesting device, holding every role (ADR-0298 §3:2).
#: It is the requesting device of a request on the local socket with no
#: ``acting_for``, of a caller inside the hub's own process (§2:5), and of every
#: request until the cutover (§9:2).
HUB_REQUESTING_DEVICE: Final = RequestingDevice(
    device_id=HUB_DEVICE_ID, roles=frozenset(DeviceRole)
)


def _check_message_shape(
    author: MessageAuthor,
    *,
    cut_off: bool,
    device_id: str | None,
    message_id: str | None,
    options: tuple[str, ...],
) -> None:
    """ADR-0293 §5:2's table, row by row, for a message new or recorded.

    *Cut off* is the assistant's only, and *message id, device* the user's only and
    then both required (§4:1). Options may not repeat, since an answer names one
    (§6:14).

    Raises:
        ValueError: If a property is present on the author that may not carry it, or
            absent on the one that must.
    """
    if author is MessageAuthor.USER:
        if device_id is None or message_id is None:
            msg = "a user's message carries the device it came from and that device's message id"
            raise ValueError(msg)
        if cut_off:
            msg = "only the assistant's message can be cut off (ADR-0293 §5:2)"
            raise ValueError(msg)
    elif device_id is not None or message_id is not None:
        msg = "an assistant message carries no device and no message id (ADR-0293 §5:2)"
        raise ValueError(msg)
    if len(set(options)) != len(options):
        msg = "a question's options must be distinct, since an answer names one"
        raise ValueError(msg)


class NewMessage(BaseModel):
    """A message to be written into a conversation's transcript (ADR-0293 §4, §6).

    What a write carries: every property of ADR-0293 §5:2's table and nothing the store
    decides — the position, the instant and the conversation are the store's. The
    author is the hub's statement, never the content's (ADR-0292 §5:1).

    **The size bound is on the type** (ADR-0293 §4:7): a message over
    :data:`TRANSCRIPT_MESSAGE_MAX_CHARS` cannot be constructed, so it is refused with
    the error on the send and nothing is recorded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    author: MessageAuthor
    text: NonBlankEncodableText = Field(max_length=TRANSCRIPT_MESSAGE_MAX_CHARS)
    replies_to: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        lt=_CHAT_INT_BOUND,
        description="The position of an earlier message in the same conversation (§4:5).",
    )
    options: tuple[_OptionText, ...] = Field(
        default=(),
        max_length=MESSAGE_OPTIONS_MAX,
        description="For a question, the options devices show as buttons (§5:2).",
    )
    cut_off: bool = Field(
        default=False, strict=True, description="The assistant's only (§5:2, §6:16)."
    )
    device_id: Identifier | None = Field(
        default=None, description="The user's only: the device the message came from."
    )
    message_id: Identifier | None = Field(
        default=None,
        description="The user's only: the id the device chose, unique per device (§4:1).",
    )

    @model_validator(mode="after")
    def _the_shape_is_its_authors(self) -> Self:
        _check_message_shape(
            self.author,
            cut_off=self.cut_off,
            device_id=self.device_id,
            message_id=self.message_id,
            options=self.options,
        )
        return self


class TranscriptMessage(BaseModel):
    """One entry of a conversation's transcript (ADR-0293 §5:1, §5:2).

    Exactly the properties §5:2's table lists, beside what places the message: the
    conversation, its position, which is what *received* answers (§4:4), and when it
    was written, which lets an activation tell that a message was written before the
    reply it follows (§6). A position is assigned once and never reused, so a reply's
    reference stays meaningful after what it names is deleted (§5:8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: Identifier
    position: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    written_at: UtcInstant
    author: MessageAuthor
    text: NonBlankEncodableText = Field(max_length=TRANSCRIPT_MESSAGE_MAX_CHARS)
    replies_to: int | None = Field(default=None, strict=True, ge=1, lt=_CHAT_INT_BOUND)
    options: tuple[_OptionText, ...] = Field(default=(), max_length=MESSAGE_OPTIONS_MAX)
    cut_off: bool = Field(default=False, strict=True)
    device_id: Identifier | None = None
    message_id: Identifier | None = None

    @model_validator(mode="after")
    def _the_shape_is_its_authors(self) -> Self:
        _check_message_shape(
            self.author,
            cut_off=self.cut_off,
            device_id=self.device_id,
            message_id=self.message_id,
            options=self.options,
        )
        if self.replies_to is not None and self.replies_to >= self.position:
            msg = "a message replies only to an earlier message (ADR-0293 §4:5)"
            raise ValueError(msg)
        return self


class DeletedMessage(BaseModel):
    """The marker a deleted message leaves: its id and that it was deleted (ADR-0293 §5:12).

    It carries no text and nothing else of the message. A reply to the message stays,
    and its reference names this position (§5:8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: Identifier
    position: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    deleted: Literal[True] = True


class TranscriptPage(BaseModel):
    """Part of a conversation's transcript, as read at one point of the change stream.

    A snapshot of a conversation's recent messages, or an older range loaded as the
    user scrolls back (ADR-0293 §5:13). ``as_of`` is the chat space's latest sequence
    number when the page was read, so a device that takes a snapshot follows the
    change stream from there.

    A deleted message appears as its :class:`DeletedMessage` marker, so a device can
    show a reply's reference as naming a deleted message (§5:8).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: Identifier
    entries: tuple[TranscriptMessage | DeletedMessage, ...] = ()
    as_of: int = Field(strict=True, ge=0, lt=_CHAT_INT_BOUND)

    @model_validator(mode="after")
    def _the_page_is_one_conversation_in_order(self) -> Self:
        positions = [one.position for one in self.entries]
        if any(later <= earlier for earlier, later in pairwise(positions)):
            msg = "a transcript page's entries are in strictly ascending position"
            raise ValueError(msg)
        if any(one.conversation_id != self.conversation_id for one in self.entries):
            msg = "a transcript page holds one conversation's entries only"
            raise ValueError(msg)
        return self


class SendOutcome(StrEnum):
    """What became of a message written into a conversation (ADR-0293 §4).

    Attributes:
        RECORDED: The conversation recorded it; the receipt's position is *received*.
        REPEATED: The same device had already sent a message with this id to this
            conversation, so this is that message (§4:2), deleted or not (§4:3), and
            nothing was written.
        NOT_AN_END: The device is not one of the conversation's ends for writing, so
            nothing was written (§7:2).
        NO_SUCH_REPLY: The message names, as the one it replies to, a position the
            conversation never held, so nothing was written (§4:5).
    """

    RECORDED = "recorded"
    REPEATED = "repeated"
    NOT_AN_END = "not_an_end"
    NO_SUCH_REPLY = "no_such_reply"


class MessageReceipt(BaseModel):
    """The answer to writing a message: its position where it is in the conversation.

    A position is present exactly where the message is recorded, newly or before
    (``RECORDED``, ``REPEATED``): that is *received* (ADR-0293 §4:4), and its absence
    tells a device the message is not in the conversation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: Identifier
    outcome: SendOutcome
    position: int | None = Field(default=None, strict=True, ge=1, lt=_CHAT_INT_BOUND)

    @model_validator(mode="after")
    def _a_position_exactly_where_recorded(self) -> Self:
        recorded = self.outcome in {SendOutcome.RECORDED, SendOutcome.REPEATED}
        if recorded != (self.position is not None):
            msg = "a receipt carries a position exactly where the message is recorded"
            raise ValueError(msg)
        return self


class MessageAddedChange(BaseModel):
    """A message was added to a conversation (ADR-0293 §5:10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["message_added"] = "message_added"
    seq: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    message: TranscriptMessage

    @property
    def conversation_id(self) -> str:
        """The conversation the message was added to."""
        return self.message.conversation_id


class MessageDeletedChange(BaseModel):
    """A message was deleted, leaving its marker (ADR-0293 §5:10, §5:12)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["message_deleted"] = "message_deleted"
    seq: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    marker: DeletedMessage

    @property
    def conversation_id(self) -> str:
        """The conversation the message was deleted from."""
        return self.marker.conversation_id


class ConversationStartedChange(BaseModel):
    """A conversation was started, shown on the devices it began with (ADR-0293 §2:1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conversation_started"] = "conversation_started"
    seq: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    conversation_id: Identifier
    devices: tuple[ChatDevice, ...] = Field(default=(), max_length=CHAT_DEVICES_MAX)


class ConversationDeletedChange(BaseModel):
    """A conversation was deleted, its transcript with it (ADR-0293 §2:3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conversation_deleted"] = "conversation_deleted"
    seq: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    conversation_id: Identifier


class DevicesChangedChange(BaseModel):
    """A set of devices changed: "my devices" or one conversation's (ADR-0293 §5:10).

    ``conversation_id`` is ``None`` for "my devices", the chat space's own set. The
    change carries the whole set as it now stands, so a device added, a device removed
    and a device's access changed are one shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["devices_changed"] = "devices_changed"
    seq: int = Field(strict=True, ge=1, lt=_CHAT_INT_BOUND)
    conversation_id: Identifier | None = None
    devices: tuple[ChatDevice, ...] = Field(default=(), max_length=CHAT_DEVICES_MAX)


#: One change to the chat space, told apart by its ``kind`` (ADR-0293 §5:10).
type ChatChange = Annotated[
    MessageAddedChange
    | MessageDeletedChange
    | ConversationStartedChange
    | ConversationDeletedChange
    | DevicesChangedChange,
    Field(discriminator="kind"),
]


class ChatChanges(BaseModel):
    """The changes after a cursor, and the cursor to ask from next (ADR-0293 §5:10, §5:11).

    ``next_after`` is where the next read starts: the last change returned where the
    page is full, and otherwise the chat space's latest sequence number as read with
    the page, so a reader whose filter matched nothing still moves forward. A
    ``next_after`` below the cursor asked from means the chat space has fewer changes
    than that cursor claims — a store started afresh — and the reader resynchronises
    from snapshots.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    changes: tuple[ChatChange, ...] = ()
    next_after: int = Field(strict=True, ge=0, lt=_CHAT_INT_BOUND)

    @model_validator(mode="after")
    def _the_changes_are_in_sequence(self) -> Self:
        seqs = [one.seq for one in self.changes]
        if any(later <= earlier for earlier, later in pairwise(seqs)):
            msg = "changes are in strictly ascending sequence"
            raise ValueError(msg)
        if seqs and self.next_after < seqs[-1]:
            msg = "the next cursor is never before the last change returned"
            raise ValueError(msg)
        return self


class UserMessage(BaseModel):
    """A message the user writes into a conversation from one of its devices (ADR-0293 §4).

    What ``AssistantEngine.write_message`` takes: the text, the device it came from and
    the message id that device chose (§4:1), and optionally the earlier message it
    replies to (§4:5). **It names no author**, because the author is the hub's
    statement, never the content's (ADR-0292 §5:1): every message arriving on this
    route is the user's (ADR-0293 §4:8), and the assistant's own messages are written
    only through the chat's writer. A caller of the surface therefore cannot write an
    assistant's message, rather than being refused one.

    **The size bound is on the type**, as on :class:`NewMessage`: a message over
    :data:`TRANSCRIPT_MESSAGE_MAX_CHARS` cannot be constructed, so it is refused with
    the error on the send and nothing is recorded (§4:7).

    A message answering a question names the question and its option (§4:6); question
    messages and their answers are not built (ADR-0293 §11:5), so this carries neither.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    device_id: Identifier = Field(description="The device the message is sent from.")
    message_id: Identifier = Field(
        description="The id the device chose, unique per device; a repeat is the same message."
    )
    text: NonBlankEncodableText = Field(max_length=TRANSCRIPT_MESSAGE_MAX_CHARS)
    replies_to: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        lt=_CHAT_INT_BOUND,
        description="The position of an earlier message in the same conversation (§4:5).",
    )

    def as_new_message(self) -> NewMessage:
        """The message as the conversation store writes it: the user's, from its device."""
        return NewMessage(
            author=MessageAuthor.USER,
            text=self.text,
            replies_to=self.replies_to,
            device_id=self.device_id,
            message_id=self.message_id,
        )


#: How many conversations one read of the chat space's changes may name (ADR-0293
#: §5:11), the bound the conversation store's ``changes`` puts on its filter.
CHAT_CHANGES_CONVERSATIONS_MAX: Final = 1000

_IDENTIFIER_ADAPTER: Final[TypeAdapter[str]] = TypeAdapter(Identifier)


def check_chat_position(value: object, *, name: str) -> int:
    """Refuse a transcript position that is not an exact ``int`` in ``[1, 2**63)``.

    Shared by every ``AssistantEngine`` implementation, so each refuses the same
    positions before any I/O (ADR-0085 §9). A ``bool`` is refused: a flag is not a
    position.

    Raises:
        ValueError: If ``value`` is not such an ``int``.
    """
    if type(value) is not int or not 1 <= value < _CHAT_INT_BOUND:
        msg = f"{name} must be an integer in [1, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def check_chat_cursor(value: object, *, name: str) -> int:
    """Refuse a change-stream cursor that is not an exact ``int`` in ``[0, 2**63)``.

    Raises:
        ValueError: If ``value`` is not such an ``int``.
    """
    if type(value) is not int or not 0 <= value < _CHAT_INT_BOUND:
        msg = f"{name} must be an integer in [0, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def chat_conversation_ids(value: object) -> tuple[str, ...] | None:
    """Snapshot a changes read's conversation filter, each id an ``Identifier``.

    ``None`` stays ``None`` (every change). A sequence is read **once**, before
    anything else (ADR-0065), each element validated as an
    :data:`Identifier` — refused where blank and stripped where padded, as every
    identifier argument on the surface is (ADR-0085 §3c). A bare ``str`` is refused
    rather than read as its characters.

    Raises:
        ValueError: If ``value`` is a ``str``, not a sequence, holds more than
            :data:`CHAT_CHANGES_CONVERSATIONS_MAX` ids, or holds one that is not a
            non-blank ``str``.
    """
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        msg = f"conversation_ids must be a sequence of ids, got {describe_untrusted(value)}"
        raise ValueError(msg)
    held = tuple(value)
    if len(held) > CHAT_CHANGES_CONVERSATIONS_MAX:
        msg = (
            f"conversation_ids names at most {CHAT_CHANGES_CONVERSATIONS_MAX} conversations, "
            f"got {len(held)}"
        )
        raise ValueError(msg)
    checked: list[str] = []
    for one in held:
        if not isinstance(one, str):
            msg = f"conversation_ids holds something that is not an id: {describe_untrusted(one)}"
            raise ValueError(msg)
        try:
            checked.append(_IDENTIFIER_ADAPTER.validate_python(one))
        except ValueError as exc:  # pydantic's refusal is a ValueError
            msg = "conversation_ids holds a blank id"
            raise ValueError(msg) from exc
    return tuple(checked)


def user_message(value: object) -> UserMessage:
    """Refuse a ``write_message`` argument that is not a :class:`UserMessage`.

    Shared by every ``AssistantEngine`` implementation, so each refuses the same
    value before any I/O (ADR-0085 §9).

    Raises:
        ValueError: If ``value`` is not a ``UserMessage``.
    """
    if not isinstance(value, UserMessage):
        msg = f"message must be a UserMessage, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


class ActivationEnding(StrEnum):
    """How the last activation started from a conversation ended (ADR-0293 §8:3).

    The current state's account of the assistant, never written into the transcript
    (§8:1). A **closed** enumeration, added to and never renamed.

    Attributes:
        DONE: It ended having answered, asked or noticed, as an activation should.
        COULDNT_FINISH: It ended without finishing — the case ADR-0293 §9:1 has the
            fixed *couldn't finish* message written for.
        INTERRUPTED: It was cut short, a restart closing it among them (§9:2), so a
            device can offer "interrupted; send again?".
        STOPPED: The user stopped it (ADR-0295 §3:4). Nothing produces it until a
            stop is built.
    """

    DONE = "done"
    COULDNT_FINISH = "couldnt_finish"
    INTERRUPTED = "interrupted"
    STOPPED = "stopped"


class ActivationStop(StrEnum):
    """What a stop of one activation found (ADR-0297 §5, ADR-0295 §1).

    A **closed** enumeration, valued by lower-cased member name, added to and never
    renamed.

    Attributes:
        STOPPED: The activation was running and its end entry was not yet appended:
            its stop mark is set (or was already) and its stop record is written.
        ALREADY_ENDED: The activation had already ended — its end entry was
            appended, or the engine holds no running activation by that id but an
            episode stands at its address — and nothing was written.
        NO_SUCH_ACTIVATION: The engine holds no running activation by that id and no
            episode stands at its address, and nothing was written.
    """

    STOPPED = "stopped"
    ALREADY_ENDED = "already_ended"
    NO_SUCH_ACTIVATION = "no_such_activation"


class ConversationState(BaseModel):
    """What a conversation's devices are shown about the assistant (ADR-0293 §8).

    Read with the conversation and never written into its transcript (§8:1); it is the
    assistant's, not the conversation's (§1:6). Two facts, each independent of the
    other:

    * **working** — an activation started from the conversation is running (§8:2).
      It is informational: the user's input stays open (§6:2). ``activation_id`` names
      that activation where its id is known, which is what a stop control beside
      "working…" names (ADR-0295 §1:2); it is absent while nothing runs.
    * **last_ended** — how the last activation started from the conversation that has
      ended, ended (§8:3, as ADR-0295 §3:4 adds *stopped*), or ``None`` where none has.

    Nothing running and nothing ended is the idle conversation, and the default.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    working: bool = Field(default=False, strict=True)
    activation_id: Identifier | None = Field(
        default=None, description="The running activation, where one runs and its id is known."
    )
    last_ended: ActivationEnding | None = None

    @model_validator(mode="after")
    def _an_activation_only_while_working(self) -> Self:
        if self.activation_id is not None and not self.working:
            msg = "a conversation's state names a running activation only while working"
            raise ValueError(msg)
        return self


class DeviceConversation(BaseModel):
    """A conversation one device reads, with the access it holds there (ADR-0296 §2, §4).

    What a device's listing of its conversations answers with: the conversation, and
    whether the device only reads it or also writes in it (ADR-0293 §3:5), as the
    conversation's devices hold that now. A device that only writes in a conversation
    is not shown it (ADR-0296 §4:5), so ``access`` always reads, and a conversation
    stamped deleted is listed to no device.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation: Conversation
    access: DeviceAccess

    @model_validator(mode="after")
    def _the_device_reads_a_standing_conversation(self) -> Self:
        if not self.access.reads:
            msg = "a device is listed only the conversations it reads (ADR-0296 §4:5)"
            raise ValueError(msg)
        if self.conversation.deleted_at is not None:
            msg = "a conversation stamped deleted is listed to no device"
            raise ValueError(msg)
        return self


def _members_held(handler: SerializerFunctionWrapHandler, value: BaseModel) -> dict[str, Any]:
    """``value``'s members with each absent one — ``None``, or a flag not raised — left out.

    The change stream's chunk holds exactly one of several members, so writing every
    other one as ``null`` would put a member name and a ``null`` on the wire for each,
    on every chunk. Leaving them out makes a chunk carrying a change no wider than the
    one-change page of ``chat_changes``, so a message recorded within the limit before
    the stream existed is one a chunk can still carry. Decoding is unchanged: an
    absent member takes its default.
    """
    dumped: dict[str, Any] = handler(value)
    return {name: held for name, held in dumped.items() if held is not None and held is not False}


class DeviceChange(BaseModel):
    """One change a device may see, with its snapshot where it adds the device (ADR-0298 §7).

    ``snapshot`` is present exactly on the change that makes the device one of the
    conversation's ends for reading — the conversation's start, or a change to its
    devices — and holds the conversation's entries **as it stood at that change**
    (§7:7): the newest of the messages recorded at or before the change's sequence
    number, ascending, a message deleted since shown as its marker, and nothing
    recorded after it. The conversation and the instant it is read at are the
    change's own, so the snapshot is its entries alone, and a device that applies the
    change has the snapshot with it (§7:6). A "my devices" change belongs to no
    conversation and never carries one.

    The entries alone, rather than a ``TranscriptPage``, so that a chunk carrying a
    change with its snapshot cut to none (§7:8) is no wider than the one-change page of
    ``chat_changes``: every change the chat space records within the limit travels.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    change: ChatChange
    snapshot: tuple[TranscriptMessage | DeletedMessage, ...] | None = Field(
        default=None, max_length=CHAT_SNAPSHOT_ENTRIES
    )

    @model_validator(mode="after")
    def _a_snapshot_only_with_the_change_that_adds(self) -> Self:
        snapshot = self.snapshot
        if snapshot is None:
            return self
        change = self.change
        if (
            not isinstance(change, (ConversationStartedChange, DevicesChangedChange))
            or change.conversation_id is None
        ):
            msg = "a snapshot travels only with a change setting a conversation's devices"
            raise ValueError(msg)
        if any(one.conversation_id != change.conversation_id for one in snapshot):
            msg = "a change's snapshot is of the conversation the change sets"
            raise ValueError(msg)
        positions = [one.position for one in snapshot]
        if any(later <= earlier for earlier, later in pairwise(positions)):
            msg = "a snapshot's entries are in strictly ascending position"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _without_absent_members(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return _members_held(handler, self)

    @property
    def seq(self) -> int:
        """The change's sequence number, which is the device's cursor once applied."""
        return self.change.seq

    @property
    def conversation_id(self) -> str | None:
        """The conversation the change belongs to, ``None`` for "my devices"."""
        return self.change.conversation_id


class DeviceChanges(BaseModel):
    """The changes after a cursor one device may see, and the cursor to ask from next.

    :class:`ChatChanges` for one device (ADR-0298 §10:4): the same order, page and
    ``next_after``, each change carried as a :class:`DeviceChange` so the change that
    adds the device to a conversation brings that conversation's snapshot with it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    changes: tuple[DeviceChange, ...] = ()
    next_after: int = Field(strict=True, ge=0, lt=_CHAT_INT_BOUND)

    @model_validator(mode="after")
    def _the_changes_are_in_sequence(self) -> Self:
        seqs = [one.seq for one in self.changes]
        if any(later <= earlier for earlier, later in pairwise(seqs)):
            msg = "changes are in strictly ascending sequence"
            raise ValueError(msg)
        if seqs and self.next_after < seqs[-1]:
            msg = "the next cursor is never before the last change returned"
            raise ValueError(msg)
        return self

    def without_snapshots(self) -> ChatChanges:
        """The same page as :class:`ChatChanges`, each change without its snapshot."""
        return ChatChanges(
            changes=tuple(one.change for one in self.changes), next_after=self.next_after
        )


class CurrentState(BaseModel):
    """A conversation's current state, as the change stream pushes it (ADR-0296 §4:9).

    The state is not history, so it carries no sequence number: it is pushed when it
    changes and read with the conversation on catch-up.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: Identifier
    state: ConversationState


class ChatStreamChunk(BaseModel):
    """One chunk of the change stream: exactly one of four things (ADR-0298 §7:3).

    * ``change`` — a change to the chat space the device may see, with its sequence
      number, and the conversation's snapshot where the change adds the device (§7:1,
      §7:6);
    * ``state`` — a conversation's current state, pushed when it changes (§7:2);
    * ``roles`` — the device's own roles, sent when the stream opens and whenever they
      change (§7:9), written by the hub's session layer;
    * ``heartbeat`` — nothing but the stream being alive, written by the session layer
      whenever 15 seconds pass without a chunk (§7:12).

    Only a ``change`` moves a device's cursor; the other three carry no sequence number.
    One concrete class, so the wire tells a chunk from the stream's end by type, as it
    does for a reply stream (§7:3). **The members it does not hold are left out of its
    encoding** rather than written as ``null`` (:func:`_members_held`), which is what
    lets a chunk carry every change ``chat_changes`` can.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    change: DeviceChange | None = None
    state: CurrentState | None = None
    roles: tuple[DeviceRole, ...] | None = None
    heartbeat: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        held = sum(
            (
                self.change is not None,
                self.state is not None,
                self.roles is not None,
                self.heartbeat,
            )
        )
        if held != 1:
            msg = "a change stream chunk holds exactly one change, state, roles or heartbeat"
            raise ValueError(msg)
        if self.roles is not None and list(self.roles) != sorted(set(self.roles)):
            msg = "a device's roles are distinct and in their one order, ascending"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _without_absent_members(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return _members_held(handler, self)


class ChatStreamEnd(BaseModel):
    """How a change stream ends when the hub ends it: the cursor to reopen it from.

    A change stream is ended by revocation, by the dead-peer timeout or by its device
    (ADR-0298 §7:15), none of which writes this. The hub writes it only when its engine
    is shutting down, so a device reopens the stream from ``next_after`` once the hub
    is back rather than waiting out the dead-peer timeout.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    next_after: int = Field(strict=True, ge=0, lt=_CHAT_INT_BOUND)


class ConversationExport(BaseModel):
    """A portable snapshot of the conversation store's own state (ADR-0074 §9, ADR-0004 §6).

    **The conversations and their transcripts** (ADR-0293 §5:3, ADR-0292 §3:11): a
    transcript is the hosted medium's content and the user's data, so it is exported
    here — every message that stands, in ``messages``, and no deleted message's
    marker, which carries nothing of the user's. **No episode** (ADR-0283 §4:3): an
    episode is a ``MemoryStore`` record and that store's own export carries it, and
    the transcript and the episodes are never kept in step (ADR-0293 §5:5). "My
    devices", a conversation's devices and the reader's bookkeeping are the store's
    bookkeeping rather than a record of what was said, and are not exported.

    **This is the store's raw snapshot.** A conversation stamped deleted is absent
    from it (that is what the validator below enforces), but a conversation whose
    channel holds no live episode is *present*: this store has no way to ask
    whether one is live and no business asking (golden rule 1).

    Order is part of the contract and is the order the store's reads use (ADR-0074
    §9.3): ``conversations`` by ``last_active_at`` descending with ``id`` ascending
    as the tie-break; ``messages`` grouped by conversation in that order, each
    conversation's in ascending position. It is asserted by the conformance suite
    rather than validated here, so that filtering an export down — which preserves
    order — stays a total operation.

    ``schema_version`` is 6 because the document gains the transcripts (ADR-0293 §5,
    ADR-0014 §5); it was 5 when the :class:`Conversation` it carries lost its
    observation watermark (ADR-0285 §4), and 4 when the turns left the document
    (ADR-0275 §7:9 as ADR-0283 §4:3 reads it). Exports have no import operation and
    no historical conversion path, so an earlier document is not read here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[6] = Field(
        default=6,
        description=(
            "Shape of this export, pinned to exactly 6 (ADR-0039 §10, ADR-0014 §5, "
            "ADR-0293 §5): an export outlives the code that wrote it, so the label must "
            "be a fact about the document rather than a producer's unchecked claim."
        ),
    )
    exported_at: UtcInstant
    conversations: tuple[Conversation, ...] = ()
    messages: tuple[TranscriptMessage, ...] = ()

    @model_validator(mode="after")
    def _the_snapshot_is_internally_consistent(self) -> ConversationExport:
        """Enforce what this export documents rather than assuming it.

        A repeated id would make one conversation addressable twice, and the
        deleted-conversation rule is §9's "a conversation stamped deleted but not
        yet reclaimed is **not** exported", made unrepresentable rather than left to
        each producer.
        """
        stamped = sorted(one.id for one in self.conversations if one.deleted_at is not None)
        if stamped:
            msg = f"export must not carry conversations stamped deleted: {', '.join(stamped)}"
            raise ValueError(msg)

        known = {one.id for one in self.conversations}
        if len(known) != len(self.conversations):
            msg = "export contains duplicate conversation ids"
            raise ValueError(msg)

        # A message belongs to a conversation the export carries, and names one
        # position of it once: a transcript without its conversation would be text
        # whose deletion the export no longer shows.
        placed = [(one.conversation_id, one.position) for one in self.messages]
        if len(set(placed)) != len(placed):
            msg = "export carries one message twice"
            raise ValueError(msg)
        orphaned = sorted({one.conversation_id for one in self.messages} - known)
        if orphaned:
            msg = f"export carries messages of conversations it does not: {', '.join(orphaned)}"
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


# --- tools: what a call costs, and what it may touch (ADR-0016 §4) -----------
# Cost is structured so a spend policy can tell *free* from *unknown* and fail
# closed on the second. `TierReach` orders `DataTier` by sensitivity, so two
# registries serialise the same declaration identically.


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


# --- tool argument schemas: one dialect, read once (ADR-0145) ----------------
# `ToolDefinition.parameters_schema` is the only schema this system reads, and
# ADR-0145 §5 fixes its dialect at JSON Schema draft 2020-12. Both halves of the
# rule live here on ADR-0016 §2's intrinsic test: the answer is computable from
# the schema and the arguments alone, independent of policy, configuration,
# context and clock, and the same for every consumer. `orchestration` needs it to
# decide whether to ask for a ruling at all and `tools` needs it to hold at the
# seam; golden rule 1 forbids either importing the other, so one implementation
# here is the only one that cannot become two free to disagree.
#
# Every walk below is **iterative**. The documents are authored by whoever wrote
# the tool — under leg 12, by a server this repository does not control — and a
# recursive walk is the first thing a deeply nested one exhausts, before the
# bound that exists to refuse it has been measured (ADR-0145 §6).


_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
"""The one dialect read, and the ``$schema`` value that may declare it.

ADR-0145 §5: a schema carrying no ``$schema`` is read as 2020-12, and one naming
any other dialect is refused rather than reinterpreted. The empty-fragment
spelling is accepted alongside the bare URI because it is the *same* URI and so
declares the same dialect — accepting it reinterprets nothing.
"""

_MAX_SCHEMA_DEPTH: Final = 64
"""How deeply a ``parameters_schema`` may nest (ADR-0145 §6).

One constant, not configurable and not per-tool, fixed low enough that a schema
at the bound evaluated against an instance of comparable depth completes well
inside the interpreter's recursion limit — evaluation costs roughly two Python
frames per level against a limit of 1000, and
``test_a_schema_at_the_depth_bound_evaluates_within_the_recursion_limit`` is what
keeps that a measurement rather than a claim. Real tool schemas nest well under
ten levels, so the bound is headroom rather than a ceiling anyone meets.

The **instance** half is bounded separately and more loosely, by
:data:`_MAX_JSON_DEPTH` at the frozen-JSON ingress (ADR-0196). This constant must
stay strictly below that one, or ADR-0145 §6's refusal here becomes unreachable —
the ingress would already have refused every schema this bound means to refuse,
and a tool author would be told about the wrong bound (ADR-0196 §4).
``test_the_schema_bound_sits_strictly_inside_the_frozen_json_ceiling`` is what
keeps the ordering a measurement rather than a comment.

ADR-0145 §6 argued the instance half was *unbounded* on the grounds that "a
payload deep enough to matter exhausts the stack in :func:`_deep_freeze` on the
way in". That was measured false on 2026-08-26 and ADR-0196 §7 amends it: nothing
reaches :func:`_deep_freeze` except through the recursive :data:`FrozenJson`
alias, which pydantic-core refuses at 257 containers, and the walk itself
survives 997 (issue #1107, ADR-0145 §14).
"""

_MAX_REPORTED_VIOLATIONS: Final = 100
"""How many violations :func:`parameter_violations` reports before truncating."""

_TRUNCATION_KEYWORD: Final = "<truncated>"
"""The reserved :attr:`ParameterViolation.keyword` that states a truncation.

ADR-0145 §8 requires that "any truncation is stated in what is reported rather
than performed silently", so the report says so in its own vocabulary. No JSON
Schema keyword can collide with it: keywords are bare identifiers and this is
not one.
"""

_ELIDED_SEGMENT: Final = "<elided>"
"""What stands in a violation path for a key the schema does not name (§8)."""

_REFUSAL_DETAIL_LIMIT: Final = 3
"""How many violations a construction refusal names before saying "and N more"."""


def _json_nodes(value: object) -> Iterator[tuple[tuple[str | int, ...], object]]:
    """Yield every node of a JSON document with its location, without recursing.

    The location is a tuple of mapping keys and sequence indices, in the same
    form :func:`_resolve_local_reference` produces, so a resolved reference and a
    walked node are comparable without a second spelling of "where".
    """
    stack: list[tuple[tuple[str | int, ...], object]] = [((), value)]
    while stack:
        path, item = stack.pop()
        yield path, item
        if isinstance(item, Mapping):
            stack.extend(((*path, str(key)), child) for key, child in item.items())
        elif isinstance(item, Sequence) and not isinstance(item, str):
            stack.extend(((*path, index), child) for index, child in enumerate(item))


def _json_depth(value: object, limit: int) -> int:
    """Return how deeply ``value`` nests containers, stopping once past ``limit``.

    A scalar is depth 0 and ``{}`` is depth 1, so the figure counts containers
    rather than levels of anything else. Breadth-first with an explicit frontier,
    for the reason the section header gives.
    """
    depth = 0
    frontier: list[object] = [value]
    while frontier and depth <= limit:
        children: list[object] = []
        holds_container = False
        for item in frontier:
            if isinstance(item, Mapping):
                holds_container = True
                children.extend(item.values())
            elif isinstance(item, Sequence) and not isinstance(item, str):
                holds_container = True
                children.extend(item)
        if not holds_container:
            break
        depth += 1
        frontier = children
    return depth


def _pointer_step(current: object, token: str) -> tuple[str | int, object] | None:
    """Take one RFC 6901 step through ``current``, or ``None`` if it does not exist."""
    if isinstance(current, Mapping):
        if token in current:
            return token, current[token]
        return None
    if isinstance(current, Sequence) and not isinstance(current, str):
        if token.isascii() and token.isdigit() and int(token) < len(current):
            return int(token), current[int(token)]
        return None
    return None


def _resolve_local_reference(
    document: Mapping[str, FrozenJson],
    reference: str,
    anchors: Mapping[str, tuple[str | int, ...]],
) -> tuple[str | int, ...] | None:
    """Resolve a same-document ``$ref`` to the location it names, or ``None``.

    This *is* ADR-0145 §6's "registry containing that one document and nothing
    else": the only thing a reference can name is a location in ``document``, so
    resolution has no reachable path that could retrieve anything (§7). A
    reference naming a location that does not exist, or one holding something
    that is not a schema, returns ``None`` — which §6 turns into a definition
    that does not load rather than a call that fails.
    """
    fragment = unquote(reference[1:])
    if not fragment:
        return ()
    if not fragment.startswith("/"):
        return anchors.get(fragment)
    path: list[str | int] = []
    current: object = document
    for raw in fragment.split("/")[1:]:
        step = _pointer_step(current, raw.replace("~1", "/").replace("~0", "~"))
        if step is None:
            return None
        key, current = step
        path.append(key)
    if not isinstance(current, Mapping | bool):
        return None
    return tuple(path)


def _reference_cycle(
    targets: Mapping[tuple[str | int, ...], tuple[str | int, ...]],
) -> bool:
    """Report whether the reference graph contains a cycle (ADR-0145 §6).

    A plain reachability walk over ``$ref`` targets, which is what §6 chose over
    classifying keywords as instance-consuming or not: it is decidable, total and
    has no subtle case to get wrong, at the cost of refusing a genuinely
    recursive argument along with the divergent ones.

    The nodes are the root and every reference *target*; there is an edge from a
    node to every target named by a ``$ref`` lying at or below it. The root lies
    above everything, so every node is reachable from it and one walk sees the
    whole graph.
    """
    nodes = {(), *targets.values()}
    edges = {
        node: {target for location, target in targets.items() if location[: len(node)] == node}
        for node in nodes
    }
    grey: set[tuple[str | int, ...]] = set()
    black: set[tuple[str | int, ...]] = set()
    for start in nodes:
        if start in black:
            continue
        stack = [(start, iter(edges[start]))]
        grey.add(start)
        while stack:
            node, remaining = stack[-1]
            child = next(remaining, None)
            if child is None:
                stack.pop()
                grey.discard(node)
                black.add(node)
            elif child in grey:
                return True
            elif child not in black:
                grey.add(child)
                stack.append((child, iter(edges[child])))
    return False


def _keyword_placement_defect(
    path: tuple[str | int, ...],
    item: Mapping[str, object],
    anchors: dict[str, tuple[str | int, ...]],
) -> str | None:
    """Check one subschema's identity keywords, recording any ``$anchor`` it declares.

    Each exclusion is a case where a ``#``-prefixed reference stops meaning
    "somewhere in this document" (ADR-0145 §6): a subschema ``$id`` re-bases
    resolution, so a reference that reads local resolves elsewhere, and a dynamic
    reference is resolved against the dynamic scope at evaluation time, so what it
    points at is not a property of the document a reviewer is reading. Neither is
    needed to describe a tool's arguments, and refusing both keeps
    "self-contained" a fact a reader can check by looking.

    A repeated ``$anchor`` is refused for a different reason: nothing decides
    which of the two a reference names, and an ambiguous resolution is not a
    resolution.
    """
    if "$dynamicRef" in item or "$dynamicAnchor" in item:
        return "a dynamic reference is resolved against the evaluation scope, so it is refused"
    if "$id" in item and path != ():
        return "a subschema $id re-bases resolution, so $id is permitted only at the root"
    anchor = item.get("$anchor")
    if isinstance(anchor, str):
        if anchor in anchors:
            return "two subschemas declare the same $anchor, so a reference to it is ambiguous"
        anchors[anchor] = path
    return None


def _reference_model_defect(document: Mapping[str, FrozenJson]) -> str | None:
    """Return how ``document`` breaches ADR-0145 §6's reference model, or ``None``.

    Every ``$ref`` begins with ``#`` and resolves inside the document, ``$id``
    appears at the root or not at all, ``$dynamicRef``/``$dynamicAnchor`` do not
    appear, ``$anchor`` is permitted, and the reference graph is acyclic.

    **The scan treats these keys as keywords wherever they appear**, including
    inside a ``const`` or an ``enum`` value that happens to be shaped like a
    schema. Telling the two apart means implementing 2020-12's keyword structure
    inside the very check whose job is to be trustworthy about documents from
    untrusted servers, and the over-approximation fails closed: the cost is that
    a tool whose ``const`` contains a ``$ref``-shaped object does not load, and
    §9's rule for an adapter meeting one is to restate the schema or refuse it.
    """
    anchors: dict[str, tuple[str | int, ...]] = {}
    references: list[tuple[tuple[str | int, ...], str]] = []
    for path, item in _json_nodes(document):
        if not isinstance(item, Mapping):
            continue
        placement = _keyword_placement_defect(path, item, anchors)
        if placement is not None:
            return placement
        reference = item.get("$ref")
        if reference is None:
            continue
        if not isinstance(reference, str) or not reference.startswith("#"):
            return "every $ref must begin with '#', so nothing outside this document is named"
        references.append((path, reference))
    targets: dict[tuple[str | int, ...], tuple[str | int, ...]] = {}
    for location, reference in references:
        target = _resolve_local_reference(document, reference, anchors)
        if target is None:
            return "a $ref names no schema in this document"
        targets[location] = target
    if _reference_cycle(targets):
        return "the reference graph contains a cycle, so evaluating it would not terminate"
    return None


def _root_type_defect(document: Mapping[str, FrozenJson]) -> str | None:
    """Return why the root ``type`` excludes an object, or ``None`` (ADR-0145 §6).

    Deliberately syntactic, and deliberately not a satisfiability rule.
    :attr:`ActionRequest.parameters` is a mapping, so a root saying
    ``"type": "string"`` is a definition no call could ever satisfy — the mistake
    an adapter makes by pasting the wrong schema, caught by one keyword lookup at
    the moment the definition is built. What it does not decide is whether *some*
    object satisfies the schema, which no construction check can answer in
    general: ``{"not": {}}`` — the object spelling of ``false`` — loads, and fails
    visibly on the first call.
    """
    declared = document.get("type")
    if declared is None:
        return None
    if isinstance(declared, str):
        admits_object = declared == "object"
    elif isinstance(declared, Sequence):
        admits_object = "object" in declared
    else:  # pragma: no cover - meta-validation has already refused this shape
        admits_object = False
    if admits_object:
        return None
    return "its root `type` does not admit an object, so no call could satisfy it"


_MAX_CACHED_SCHEMAS: Final = 128
"""How many digests :data:`_readable_schemas` keeps before it starts over.

Bounded rather than unbounded, because under ADR-0145 §7's threat model the
documents are chosen by a server this repository does not control: an unbounded
memo would let a discovery loop publishing a fresh schema each pass grow `core`'s
footprint without limit. Small rather than generous, because a registry's whole
tool set fits inside it several times over and the cost of a miss is one
meta-validation, not a failure.
"""

_readable_schemas: set[bytes] = set()
"""Digests of schema documents ADR-0145 §6 has already found readable.

**The memo holds digests and nothing else, and it remembers only the readable
answer.** Both halves are the memory bound rather than decoration on it. A digest
is 32 bytes whatever it is taken over, which is what lets
:data:`_MAX_CACHED_SCHEMAS` be an entry count: a ``parameters_schema`` is bounded
in depth (§6) and in neither breadth nor bytes, so a memo retaining documents
would bound entries without bounding memory. And a *defect* is not a fixed size
either — ``SchemaError.json_path`` names the failing keyword's location, so a
property name a provider made 200 kB long comes back inside the reason — so
refusals are recomputed rather than remembered, and no §7-untrusted byte is kept
anywhere. The refusal is unchanged either way: it is rendered from the document
in hand every time, which is also the fail-closed direction, since the memo can
say a document was readable and can never say one was refused.

**The digest is over ADR-0021 §1's canonical encoding**, which is the identity
this module already stakes an authorisation on:
:attr:`ActionRequest.parameters_digest` is ``sha256`` over the same encoding of a
call's arguments, and a permission decision is recorded against it. Two documents
with one digest are one document on exactly that assumption, and no weaker one.

**Not the frozen value's own hash**, and the difference is not cosmetic.
``FrozenDict`` hashes and compares as Python values, where ``True == 1`` and
``hash(True) == hash(1)``; ``{"minLength": 1}`` is a valid draft 2020-12 schema
and ``{"minLength": True}`` is not, because jsonschema's ``integer`` type check
excludes ``bool``. A Python-equality key would answer the second from the first's
entry and load a schema §6 refuses. The canonical encoding spells them ``1`` and
``true``.

Nothing that has an answer loses it: what the memo forgets, the next construction
recomputes, at the price the whole check cost before there was a memo.
"""

_schema_memo_lock: Final = Lock()
"""Makes :data:`_readable_schemas`'s bound true rather than typical.

Testing the capacity and adding are one critical section, because separately they
are not: several threads observing 127 entries each add a distinct digest and the
set ends above the bound — and this repository runs store work in threads
(``_run_to_completion``), so a bound that only holds single-threaded is not the
bound the docstring above claims. The lock is never held across the
meta-validation itself, which is pure: two threads that race on the same unseen
document both compute the same answer, and one of them adds a digest the other
was about to.
"""


def _schema_defect(schema: Mapping[str, FrozenJson], /) -> str | None:
    """Return ADR-0145 §6's defect in ``schema`` below the depth bound, or ``None``.

    Split out of :func:`_unreadable_schema_reason` so that everything expensive
    sits behind one memo and the depth bound, which is the stack guard the memo
    must not sit in front of, does not. Nothing else moved: the order below and
    every reason are that function's, unchanged.

    **The order is load-bearing.** The declared dialect comes first, because a
    draft-07 schema must be *refused* rather than meta-validated as 2020-12 and
    silently read under semantics its author did not use. Only then is the
    document meta-validated, which is what lets the reference and root-type checks
    assume a well-formed ``$ref``, ``$anchor`` and ``type``.
    """
    declared = schema.get("$schema")
    if declared is not None and declared not in (_SCHEMA_DIALECT, f"{_SCHEMA_DIALECT}#"):
        return "it declares a $schema other than JSON Schema draft 2020-12"
    try:
        Draft202012Validator.check_schema(_thaw_json(schema))
    except SchemaError as exc:
        return f"it is not a valid draft 2020-12 schema (at {exc.json_path})"
    return _reference_model_defect(schema) or _root_type_defect(schema)


def _unreadable_schema_reason(schema: Mapping[str, FrozenJson], /) -> str | None:
    """Return why ``schema`` cannot be read as draft 2020-12, or ``None`` if it can.

    ADR-0145 §6's construction check, in one place: schema validity "is a
    ``ToolDefinition`` construction check and nothing else", so it runs wherever a
    definition is constructed — including the defensive rebuilds ADR-0018 §4,
    :func:`_detached_tool` and ADR-0029 §2's step 1 already perform — and no later
    stage adds a schema check of its own.

    **The order is load-bearing.** Depth is measured first, iteratively, because
    every check after it walks the document recursively and would exhaust the
    stack on a document deep enough to matter — the canonical encoding below
    included, which is why the memo begins after the bound rather than in front of
    it. :func:`_schema_defect` carries the order of everything after.

    **A readable answer is memoised** in :data:`_readable_schemas`, because
    meta-validating the same document again yields the same answer at a price that
    dominates construction: walking the draft 2020-12 metaschema costs roughly
    fifty times what encoding the document does, and the shape it is charged for
    most often is ``{}``, the default every tool that declares no arguments
    carries. The memo is sound because :func:`_schema_defect` is a pure function
    of the document — it reads no setting, no clock and no state, and the depth
    bound and the dialect are module constants.

    **What the memo changes is that the answer is computed once, not that it is
    given once.** §6 requires the check to run "wherever a ``ToolDefinition`` is
    constructed … including every defensive revalidation and detachment already
    required of a registry, of a request and at the seam", and it still does:
    every construction asks and every construction is answered, ADR-0018 §4's
    rebuild, :func:`_detached_tool` and ADR-0029 §2's step 1 included. §6's clause
    fixes which stages the refusal reaches, not how many times a metaschema is
    walked. The corruption route it closes is untouched — a definition mutated
    through ``object.__setattr__`` carries a different document, so it digests
    differently, misses the memo and is meta-validated afresh.

    **The memo is emptied wholesale rather than evicted entry by entry**, because
    the working set is a registry's declarations — a handful, fixed for the life of
    a process — so a 129th distinct document says the working set is not what this
    memo is for. An eviction order is state that can be wrong; starting over
    cannot be, and what is forgotten is recomputed at the price it cost before
    there was a memo.

    Every reason returned describes the *schema*, which is Tier 2 configuration
    authored by the tool's provider; nothing here reads a call's arguments, so
    §8's rule about rendering them is not in play.

    Args:
        schema: A candidate ``parameters_schema``, frozen or plain.

    Returns:
        A short reason, or ``None`` when the schema is readable.
    """
    if _json_depth(schema, _MAX_SCHEMA_DEPTH) > _MAX_SCHEMA_DEPTH:
        return f"it nests deeper than {_MAX_SCHEMA_DEPTH} levels"
    try:
        digest = sha256(_canonical_bytes(_thaw_json(schema))).digest()
    except TypeError, ValueError:
        # A value with no canonical encoding has no digest, so it is answered
        # unmemoised rather than answered differently. Pydantic refuses such a
        # `parameters_schema` before this validator sees it; what reaches here is
        # the corrupted instance ADR-0145 §6's revalidation clause exists for, and
        # it must still get the answer it got before there was a memo.
        return _schema_defect(schema)
    with _schema_memo_lock:
        if digest in _readable_schemas:
            return None
    reason = _schema_defect(schema)
    if reason is not None:
        # Deliberately not remembered: the reason is rendered from a
        # provider-authored document and is not a bounded string, so keeping it
        # would bound entries without bounding memory.
        return reason
    with _schema_memo_lock:
        if len(_readable_schemas) >= _MAX_CACHED_SCHEMAS:
            _readable_schemas.clear()
        _readable_schemas.add(digest)
    return None


class ParameterViolation(BaseModel):
    """One way a call's arguments fail the tool's declared schema (ADR-0145 §2).

    **It carries no field that could hold an argument value, and that is the
    enforcement of ADR-0145 §8 rather than a description of it.** A renderer that
    wanted to interpolate the instance would have to obtain it from somewhere
    other than a violation. The reference implementation puts the instance into
    its own message text — ``'alice@example.com' is not of type 'integer'``, and
    ``Additional properties are not allowed ('X-Secret' was unexpected)`` — and
    ``core/logging.py`` redacts by *key*, so a rendered message is a leak with no
    downstream catcher (ADR-0029 §3). Nothing derived from that text reaches this
    type.

    The accepted cost is a thinner diagnostic: an ``additionalProperties``
    violation says *where* and *which keyword*, not which key. The producer of the
    arguments already holds them; what it lacked was the constraint, which the
    three fields below supply exactly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: EncodableText = Field(
        description="RFC 6901 JSON Pointer to the failing location; '' is the root.",
    )
    keyword: EncodableText = Field(description="The schema keyword that failed.")
    schema_value: FrozenJsonValue = Field(
        description="The schema's own value for that keyword.",
    )


def _schema_named_properties(document: object) -> frozenset[str]:
    """Collect the property names the schema itself names (ADR-0145 §8).

    §8 permits a violation path to carry "property names the schema itself
    names", and requires a key the schema does not name to be elided rather than
    reproduced — because a mapping the schema does not describe can be keyed by an
    address or an identifier. This is the positive half of that rule, and it is
    stated as a property rather than as an enumeration: **a path segment is
    rendered only when the string occurs in the schema document**, so whatever
    reaches a log was already Tier 2 configuration.

    ``patternProperties`` keys are deliberately absent: they are regular
    expressions, and a key matching one is not a key the schema named.
    """
    names: set[str] = set()
    for _path, item in _json_nodes(document):
        if not isinstance(item, Mapping):
            continue
        for keyword in ("properties", "dependentSchemas", "dependentRequired"):
            named = item.get(keyword)
            if isinstance(named, Mapping):
                names.update(key for key in named if isinstance(key, str))
        required = item.get("required")
        if isinstance(required, Sequence) and not isinstance(required, str):
            names.update(entry for entry in required if isinstance(entry, str))
        dependent = item.get("dependentRequired")
        if isinstance(dependent, Mapping):
            for listed in dependent.values():
                if isinstance(listed, Sequence) and not isinstance(listed, str):
                    names.update(entry for entry in listed if isinstance(entry, str))
    return frozenset(names)


def _violation_path(location: Sequence[str | int], named: frozenset[str]) -> str:
    """Compose ADR-0145 §8's path: indices, named properties, and elisions."""
    segments: list[str] = []
    for part in location:
        if isinstance(part, int):
            segments.append(str(part))
        elif part in named:
            segments.append(part.replace("~", "~0").replace("/", "~1"))
        else:
            segments.append(_ELIDED_SEGMENT)
    return "".join(f"/{segment}" for segment in segments)


def _violation_facts(error: ValidationError, named: frozenset[str]) -> tuple[str, str, FrozenJson]:
    """Reduce one library error to the three schema-side facts §8 permits.

    A plain tuple rather than a :class:`ParameterViolation`, and that is what
    keeps the cap in :func:`parameter_violations` a real bound. A schema with an
    array of a million failing items yields a million errors, so building a
    validated model for each one before truncating would exhaust memory on the
    way to a refusal — the report would be capped and the work reaching it would
    not. Models are built for the violations actually reported and for nothing
    else.
    """
    keyword = error.validator if isinstance(error.validator, str) else "schema"
    # `validator_value` is the schema's own value for the failing keyword, and it
    # came out of the thawed document — so it is JSON by construction. The one
    # exception is the library's "unset" sentinel, carried by an error synthesised
    # without a keyword; that is not a schema value and is reported as `None`
    # rather than guessed at or rendered.
    declared: object = error.validator_value
    schema_value: FrozenJson = (
        declared if isinstance(declared, str | bool | int | float | Mapping | Sequence) else None
    )
    return (_violation_path(list(error.absolute_path), named), keyword, schema_value)


def _facts_order(facts: tuple[str, str, FrozenJson]) -> tuple[str, str, bytes]:
    """Order violations totally, so the same call reports the same list twice.

    The library yields errors in whatever order it walked the instance, and for
    ``additionalProperties`` that walk is over a set. ADR-0145 §8 requires a
    deterministic order, so one is imposed here rather than inherited — and it is
    imposed over the *whole* set of errors rather than over the ones that happen
    to arrive first, which is what makes the truncated report a stable prefix
    instead of a sample.
    """
    path, keyword, schema_value = facts
    return (path, keyword, _canonical_bytes(_thaw_json(schema_value)))


def parameter_violations(
    schema: Mapping[str, FrozenJson], parameters: Mapping[str, FrozenJson], /
) -> tuple[ParameterViolation, ...]:
    """Report every way ``parameters`` fails ``schema`` (ADR-0145 §2).

    The ordinary path: a stage computes the violations *before* it constructs an
    :class:`ActionRequest` and before it requests a permission ruling, so it gets
    a structured answer rather than an exception it would have to classify
    (ADR-0145 §2, §4). :meth:`ActionRequest.parameters_satisfy_the_schema` is the
    backstop for a caller that does not; it is never a substitute for the
    obligation on the stage.

    **An empty schema declares no constraint** and every mapping satisfies it
    (ADR-0145 §9). That is today's behaviour for a tool that declares nothing, it
    is not an error, and it is not a claim that the arguments were checked.

    **Nothing is modified and nothing is retrieved.** No ``default`` is applied
    and no value is coerced, so the mapping evaluated is the same canonical form
    :attr:`ActionRequest.parameters_digest` is taken over — filling a default
    would change the arguments after the caller chose them and before the digest
    binds them. The evaluator is built with no retriever, which is the library's
    own default, so a reference outside the document raises rather than fetching:
    a validator that fetched would be an unauthorised egress performed from
    ``core`` (ADR-0004 §2, ADR-0017 §1) and would make what a call may contain
    depend on a document a third party can change between one call and the next.

    **The schema is assumed readable, and its validity is never re-established
    here** (ADR-0145 §6): a :class:`ToolDefinition` in hand was built by some
    construction, and every construction runs
    :func:`_unreadable_schema_reason`. Handed an unreadable schema anyway, this
    raises rather than reporting — which ADR-0145 §7 makes a refusal of the step
    at the selection stage, never a pass.

    Args:
        schema: The tool's declared ``parameters_schema``.
        parameters: The arguments proposed for the call.

    Returns:
        The violations, in a deterministic order, capped at
        ``_MAX_REPORTED_VIOLATIONS``. Where the cap bit, a final violation whose
        :attr:`~ParameterViolation.keyword` is ``"<truncated>"`` carries the total
        number found, so a truncation is stated rather than performed silently
        (ADR-0145 §8).

    Raises:
        Exception: Whatever the evaluation raised. Callers must treat that as a
            refusal and may name the exception's **type** and nothing else —
            ADR-0145 §7 forbids rendering, logging or storing its ``str()``,
            ``args``, ``__cause__`` or ``__notes__``, because a schema that raises
            on demand would otherwise be the one path on which an untrusted
            document makes the argument values arrive in the log.
    """
    if not schema:
        return ()
    document = _thaw_json(schema)
    named = _schema_named_properties(document)
    validator = Draft202012Validator(document)
    instance = _thaw_json(parameters)

    total = 0

    def _streamed() -> Iterator[tuple[str, str, FrozenJson]]:
        nonlocal total
        for error in validator.iter_errors(instance):
            total += 1
            yield _violation_facts(error, named)

    # `nsmallest` over a generator holds one bounded heap, so the peak cost is the
    # cap and not the error count. The alternative — sort everything, then slice —
    # made the advertised cap a property of the *report* while the work reaching
    # it still scaled with the instance, which is the wrong half to bound on a
    # path every tool call takes. The evaluation's own O(n) cost is untouched and
    # deliberately so: ADR-0145 §14 parks a cost budget for it as #1108.
    kept = heapq.nsmallest(_MAX_REPORTED_VIOLATIONS + 1, _streamed(), key=_facts_order)
    reported = tuple(
        ParameterViolation(path=path, keyword=keyword, schema_value=schema_value)
        for path, keyword, schema_value in kept[:_MAX_REPORTED_VIOLATIONS]
    )
    if total <= _MAX_REPORTED_VIOLATIONS:
        return reported
    truncation = ParameterViolation(path="", keyword=_TRUNCATION_KEYWORD, schema_value=total)
    return (*reported, truncation)


def _refused_parameters(violations: Sequence[ParameterViolation]) -> str:
    """Say which constraints the arguments missed, naming no argument (§8).

    Only the schema-side facts a :class:`ParameterViolation` carries reach this
    string, and only the first few of them: the message is a refusal, not a
    report, and the caller that wants the whole list calls
    :func:`parameter_violations` for it.
    """
    limit = _REFUSAL_DETAIL_LIMIT
    shown = ", ".join(f"{one.keyword} at {one.path or '/'}" for one in violations[:limit])
    more = "" if len(violations) <= limit else f", and {len(violations) - limit} more"
    return f"parameters do not satisfy the tool's parameters_schema: {shown}{more}"


def _system_supplied(value: tuple[str, ...]) -> tuple[str, ...]:
    """Require ADR-0254 §3's duplicate-free set of key names.

    Possibly **empty**, which is the default and is the one exception to
    :class:`ToolDefinition`'s required-field rule (§3, §18): the empty tuple makes
    the claim *"nothing here is system-supplied"*, so every argument is user-facing
    and needs coverage — a question rather than a widening.

    A duplicate is refused because a key named twice is a second spelling of one
    classification. **The order is the declaration's own** and is not sorted:
    nothing compares this tuple by value, and §3's two readers ask it only for
    membership.

    Raises:
        ValueError: If the tuple names a key twice.
    """
    if len(set(value)) != len(value):
        msg = (
            "a declaration classifies each key system-supplied once; a duplicate is a "
            "second spelling of one classification (ADR-0254 §3)"
        )
        raise ValueError(msg)
    return value


# --- tools: the declaration a permission decision rules on (ADR-0016 §1) -----
# States facts and draws no conclusions — `permissions` does that (ADR-0016
# §3). Every field a decision depends on is required, because a default is a
# claim, and the natural default for a reach tuple is a false one.
#
# :class:`BoundKind` is declared here rather than beside :class:`ValueBound`: it
# had a second consumer on the declaration, which left with ADR-0313 §5:4.


class CapabilityEffect(StrEnum):
    """What a capability's calls change (ADR-0306 §2).

    **Three members, closed.** Every rule about a phases call reads this: it decides
    which calls are claimed, which get an effect record, and what is reported as done
    in the world (ADR-0306 §5).
    """

    NONE = "none"
    """The call changes nothing: a read, or a disclosure with nothing written."""

    OWN_RECORDS = "own_records"
    """The call changes the assistant's own records, such as a story or a memory
    (ADR-0306 §3). It runs directly against the store it reaches."""

    WORLD = "world"
    """The call changes something outside the hub, such as a booking or a sent
    message."""


class CapabilityResult(StrEnum):
    """What a capability's calls return, by who may have written it (ADR-0306 §2).

    **Three members, closed.** It decides the *looking for* argument and where a
    result goes: a result that may carry outside text is routed record by record by
    who wrote it, and one declared to carry none goes to planning whole (ADR-0306 §5).
    """

    NONE = "none"
    """The call returns nothing planning reads."""

    NO_OUTSIDE_TEXT = "no_outside_text"
    """The call returns only what the user or the assistant wrote, or no text at all."""

    MAY_CARRY_OUTSIDE_TEXT = "may_carry_outside_text"
    """The call may return text someone other than the user or the assistant wrote."""


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
    effect: CapabilityEffect = Field(
        description=(
            "What the tool's calls change: nothing, the assistant's own records, or the "
            "world (ADR-0306 §2). Required, with no default."
        )
    )
    leaves_hub: bool = Field(
        description="Whether a call leaves the hub (ADR-0306 §2). Required, with no default."
    )
    result: CapabilityResult = Field(
        description=(
            "What a call returns, by who may have written it (ADR-0306 §2). Required, "
            "with no default."
        )
    )
    outcome_can_be_unknown: bool = Field(
        description=(
            "Whether a call's outcome can be unknown (ADR-0306 §2). An unknown outcome "
            "is never retried. Required, with no default."
        )
    )
    safe_to_repeat: bool = Field(
        description=(
            "Whether a call may be made again with the same values (ADR-0306 §2). Its "
            "own property, never read from ``idempotency``, which governs retrying one "
            "call. Required, with no default."
        )
    )
    idempotency_window: timedelta | None = Field(
        default=None,
        description="How long a repeated key is deduplicated; required iff idempotency is KEYED.",
    )
    latency: timedelta | None = Field(
        default=None, description="Expected duration of a typical call; advisory, not a timeout."
    )
    system_supplied: Annotated[tuple[EncodableText, ...], AfterValidator(_system_supplied)] = Field(
        default=(),
        description=(
            "The keys of ``parameters`` the **system** fills — an idempotency key, a "
            "client reference, a locale — possibly empty and duplicate-free, each a "
            "key name at depth **one** (ADR-0266 §7). "
            "**Every key it does not name is user-facing**, and only a user-facing "
            "argument needs coverage: §3's condition 6 and §6's argument-authority bar "
            "each read this field, so a system-supplied key neither needs a coverage "
            'member nor ever fires the bar — which is the whole of *"implementation '
            'choices must not become user-facing questions"*. '
            "``orchestration`` supplies the value for every key named here, **before** "
            "the candidate fit test, and refuses to build a request whose plan step's "
            "own arguments name one: a user is never asked to approve an idempotency "
            "key, and a model that reached for one is a fault and not a question. "
            "``ActionRequest.parameters_digest`` is still taken over **every** "
            "argument, so a system-supplied value cannot move between the ruling and "
            "the dispatch. **This is the one exception to this class's "
            "required-field rule** and it is recorded rather than argued away "
            "(ADR-0254 §18): the empty default makes the **opposite** claim to the "
            "one ADR-0016 §1 refuses — an unclassified argument is user-facing, so a "
            "declaration that says nothing needs coverage for every argument and asks "
            "where it has none. It costs a question and can never authorise a call."
        ),
    )
    parameters_schema: FrozenJsonMapping = Field(
        default=_EMPTY_PARAMS,
        description="JSON Schema (draft 2020-12) for the call's arguments; enforced by ADR-0145.",
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
    def _the_effect_agrees_with_side_effecting(self) -> ToolDefinition:
        """Refuse an effect that ``side_effecting`` contradicts (ADR-0306 §2:5, ADR-0312 §2).

        A call that changes the assistant's own records or the world is
        side-effecting. A side-effecting call may declare no effect only where its one
        side effect is disclosure: it writes nothing and discloses something, as the
        web search and the forecast do. ADR-0016's consistency rules in
        :meth:`_effects_are_consistent` run beside this one.

        Raises:
            ValueError: If the effect is not none while ``side_effecting`` is false, or
                none while ``side_effecting`` is true and the declaration writes, or
                discloses nothing.
        """
        if self.effect is not CapabilityEffect.NONE and not self.side_effecting:
            msg = "a tool whose calls change records or the world is side-effecting"
            raise ValueError(msg)
        if (
            self.effect is CapabilityEffect.NONE
            and self.side_effecting
            and (self.writes or not self.discloses)
        ):
            msg = (
                "a side-effecting tool declares no effect only where its one side effect "
                "is disclosure: it writes nothing and discloses something (ADR-0312 §2)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _an_unknown_outcome_is_declared(self) -> ToolDefinition:
        """Refuse a declaration that says its outcome is never unknown when it can be.

        ADR-0306 §2:6. A call the invocation seam cuts short is classified by
        :attr:`interrupted_outcome`, and a call to the assistant's own records is
        never such a call: it runs directly against its store and is awaited to its
        end (§3:3). Every other declaration whose interrupted call is
        ``INDETERMINATE`` can have an unknown outcome, and saying otherwise would let
        acting report as not done a call that may have run.

        Raises:
            ValueError: If the outcome is declared never unknown, the effect is not
                the assistant's own records, and an interrupted call is
                ``INDETERMINATE``.
        """
        if (
            not self.outcome_can_be_unknown
            and self.effect is not CapabilityEffect.OWN_RECORDS
            and self.interrupted_outcome is ToolOutcome.INDETERMINATE
        ):
            msg = (
                "a tool whose interrupted call is indeterminate can have an unknown "
                "outcome, unless its effect is the assistant's own records (ADR-0306 §2)"
            )
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

        **Rendered by this class's own serializer, never through
        ``self.model_dump``** (issue #1992). That method is an ordinary
        attribute: an instance shadows it through ``__dict__`` and a subclass
        overrides it, and either can answer with a mapping that is not this
        definition's field state — so the check would be *nominated by the value
        it is checking*. That is not a hypothetical here but the other half of
        the bypass the paragraph above relies on: the ``object.__setattr__``
        route ADR-0018 §3 and ADR-0021 §4 keep inside the threat model reaches
        the method as easily as it reaches the field, and a nominated dump would
        walk an unstorable declaration into a :class:`PermissionDecision` —
        issue #156's failure, through the one re-check that exists to stop it.
        ``ai_assistant.orchestration.executor``,
        ``ai_assistant.permissions._detachment``,
        :meth:`RecipientGrant._digest_projection` and
        :data:`_MEMORY_RECORD_PROJECTION` state the same rule about the same
        method; the serializer is resolved on the class, reads the instance's
        field values, and consults no instance attribute.

        **``ToolDefinition``'s schema is the authoritative one, and a subclass's
        own is checked as well as it — never instead of it.** The declared type
        is what every holder stores this value through
        (:attr:`PermissionDecision.tool` is a ``ToolDefinition``, and
        :func:`_detached_tool` rebuilds as one), and it is the one schema the
        value cannot choose: ``type(self)`` *is* chosen by the value, so resolving
        only there would re-open through the class exactly what the paragraph
        above closed at the attribute. Rendering under the base schema
        unconditionally is what makes that impossible, because a subtype render
        can then only *add* refusals and never withdraw one — whatever a hostile
        subclass does to its own serializer, the base render has already run on
        the instance's true field values.

        The subtype render is then pure gain, and it is why this change costs no
        coverage: ``self.model_dump`` used to include a subclass's extra fields,
        so a subclass declaring an unstorable field of its own was refused here,
        and it still is. Skipped when there is no subclass, which is every
        definition this repository builds.

        The refusal clause is unchanged by the move, which is the second thing
        issue #1992 asked to be established rather than assumed: the serializer
        raises ``PydanticSerializationError`` for a value it cannot render and
        ``UnicodeEncodeError`` for an unencodable mapping key, and both are
        ``ValueError`` subclasses — the same single clause the ``model_dump``
        form was written with, because ``model_dump`` was only ever a wrapper
        around this serializer. ``warnings=False`` because serialising a subclass
        through the base's schema warns, and the warning is noise here.

        Raises:
            ValueError: If the definition has no JSON encoding.
        """
        renders: list[str] = []
        # The base schema first and always; ``type(self)`` as well when it is a
        # subclass. Deduplicated by *identity* rather than through a set or
        # ``dict.fromkeys``, because those hash the class object and a subclass
        # is free to make its own unhashable through its metaclass — which would
        # turn an otherwise storable declaration into a raw ``TypeError`` from
        # inside this validator, a failure the ``model_dump`` form did not have.
        schemas: list[type[ToolDefinition]] = [ToolDefinition]
        if type(self) is not ToolDefinition:
            schemas.append(type(self))
        for schema in schemas:
            try:
                projection = schema.__pydantic_serializer__.to_python(
                    self, mode="json", warnings=False
                )
                renders.append(json.dumps(projection, ensure_ascii=False))
            except ValueError as exc:
                # An unencodable *key* fails inside the render rather than after
                # it, because pydantic encodes a mapping key on the way to JSON.
                # Caught here so every half of the same defect raises the same
                # error rather than one arriving as a bare codec or limit failure.
                raise ValueError(self._unstorable(exc)) from exc
        if not all(_is_encodable(rendered) for rendered in renders):
            raise ValueError(self._unstorable(None))
        return self

    @model_validator(mode="after")
    def _schema_is_readable(self) -> ToolDefinition:
        """Refuse a ``parameters_schema`` this repository cannot read (ADR-0145 §6).

        Fail-closed, in ADR-0016 §1's direction: "a tool that does not declare its
        reach does not load", because a construction error beats a silent
        under-protection. A schema nobody can evaluate is a declaration nobody can
        check, and it gets the same answer.

        **One check on the type, inherited by every stage that rebuilds one.** The
        repository already revalidates a definition wherever it could have been
        tampered with — ADR-0018 §4's registry rebuild, :func:`_detached_tool` on
        the way into an :class:`ActionRequest`, and ADR-0029 §2's step 1 at the
        seam — so putting it here places it at all of them at once, with no
        per-stage rule to keep in step and no ``ToolRegistrationError`` case added.
        That is also what closes the corruption route: a definition mutated through
        ``object.__setattr__`` into carrying a remote ``$ref`` is refused by the
        revalidation those clauses already mandate rather than surviving to
        evaluation. A ``model_validator`` specifically, for the reason
        :meth:`_is_storable` gives — pydantic re-runs an ``after`` model validator
        when an existing instance is assigned to a model-typed field, and does not
        re-run field validators.

        What follows for every later stage is that it may assume a readable schema:
        evaluating a call's arguments never re-establishes the validity of the
        document it evaluates against.

        Raises:
            ValueError: If the schema is not a readable draft 2020-12 schema.
        """
        reason = _unreadable_schema_reason(self.parameters_schema)
        if reason is not None:
            msg = f"parameters_schema cannot be read: {reason}"
            raise ValueError(msg)
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


def canonical_json_bytes(value: FrozenJson) -> bytes:
    """Render one JSON value in the exact form ADR-0021 §1 pins for the digest.

    **The encoding**, and never a second one. ADR-0254 §3 states the coverage
    comparison for a fixed value over *"the canonical JSON encoding
    ``ActionRequest.parameters_digest`` is taken over, so there is one canonical
    form in this system and not a second"* — and a comparison written by hand at
    the policy would be exactly that second form. Two canonicalisations that
    disagree *"produce a false mismatch at one end and a false match at the
    other"*, which is :attr:`ActionRequest.parameters_digest`'s own stated reason
    for computing its form here rather than accepting one from a caller.

    So this is public where :func:`_canonical_json` is not: it is the one thing
    ADR-0254 §3's per-argument rule needs from outside ``core``, and it is a
    **delegation** rather than an implementation, so the encoding it renders is
    the digest's by construction rather than by agreement.

    **Why ``==`` on the values will not do**, stated because it is the obvious
    alternative and it is wrong in the permissive direction: Python compares ``1``
    equal to ``1.0`` and ``True`` equal to ``1``, while their canonical encodings
    are ``1``, ``1.0`` and ``true``. A comparison over ``==`` would therefore
    cover a call the user's act did not, which is the one direction ADR-0254 §4
    refuses.

    Args:
        value: A JSON value that has already been validated — a member of a
            :data:`FrozenJsonMapping`, or a :data:`FrozenJsonValue`. Anything else
            raises out of :func:`json.dumps`, at the boundary that produced it.

    Returns:
        The UTF-8 bytes of its one canonical rendering.
    """
    return _canonical_bytes(_thaw_json(value))


# --- egress: the binding a ruling is taken over (ADR-0150) -------------------
# Surface (a) of ADR-0148 §11: the canonical destination set, the connected
# account, the transport endpoint and the payload description, as **one**
# validating value that is carried whole, compared whole and transcribed whole.
#
# Every fact is carried once. The canonical destination set is a *derived
# property* rather than a stored field, because two representations of one fact
# admit disagreement and this is a surface where a disagreement is authoritative
# (ADR-0150 §3). The occurrences are what is stored, for the reason
# `parameters_digest` is computed rather than supplied: a value each caller
# filled in is a canonicalisation per caller, and two that disagreed produce a
# false mismatch at execution, which reads as an attack rather than as a bug.
#
# `_rejecting_invisible`, `_VisibleUnchangedText`, `DestinationProtocol`,
# `BoundAccount` and `CanonicalDestination` are declared **ahead of the planning
# types** rather than here, because :class:`EffectKey` is built from three of them
# and is reached by :class:`StepTransition` and :class:`PlanExport` (ADR-0259 §1);
# the block above :class:`StepStatus` carries the reason. Nothing about them
# changed in the move.


class DiscloserProvenance(StrEnum):
    """Who disclosed a span of an outbound payload (ADR-0146 §1).

    ADR-0146 §8 deferred "the marker that carries a span's discloser provenance
    to an egress boundary"; ADR-0150 §5 decides that the marker **is** this
    field on :class:`EgressSpan`, with no separate type and no second carriage.
    A marker riding anywhere else would have to be joined to the description by
    something, and the join is a second shape that must agree.

    **Carried, never derived.** No component decides a span's provenance by
    reading its value, its field, its shape, or by matching it against what the
    user wrote (ADR-0146 §2). ADR-0146 §2's fail-closed rule is discharged by the
    component building the span *writing* ``SYSTEM_SELECTED``, which is why
    :attr:`EgressSpan.provenance` has **no default**: a defaulted field is what a
    lane forgets, and an implementation that never wired provenance through would
    get the safe answer for free and its payloads would look correct.
    """

    #: The user composed this span into the exchange being served.
    USER_AUTHORED = "user_authored"
    #: Every other case, including a span this system's model authored and one
    #: retrieved from this system's own stores (ADR-0146 §1).
    SYSTEM_SELECTED = "system_selected"


class SpanCoverage(StrEnum):
    """Which of ADR-0155 §3's two prohibitions governs what a call would carry (ADR-0233 §4).

    One three-valued fact about the **call**, over every span it would transmit.
    ADR-0155 §3's first clause defines *covered content* — everything this
    system's stores touch, and everything any operation supplied with it produces
    — and makes the character of each *covered path* three-valued at every supply
    site: covered with a model call on the path, covered with none, or not
    covered. These are those three states and no others. This type restates,
    narrows and widens **nothing** of that clause; it is the recorded answer to
    it, and every member below means what that clause means (ADR-0233 §3).

    **Three members rather than a boolean, because the two prohibitions are
    different prohibitions.** A boolean "is this covered" cannot tell the
    absolutely forbidden case from the approvable one, and a boolean "is this
    approvable" would put the partition's own reasoning inside a field name where
    no reviewer can check it against ADR-0155 §3. The members are named for the
    quantifier each clause carries — *every* path versus *some* path — because the
    quantifiers are what make the partition exhaustive. No lane adds a fourth
    member, an "unknown" member or a ``None``-valued absence.

    **Carried, never derived, and never weakened.** The value is computed by the
    component that composed the call's arguments, from the membership and path
    character of what it supplied (ADR-0233 §5). Nothing derives it by inspecting
    an argument's value, its name, its field, its shape or its resemblance to
    anything — that is ADR-0146 §2's forbidden inference and ADR-0098 §5's
    unrecoverable relation, read on this axis. Where several components composed
    over several supplies the value is the **strongest** of their states under the
    total order below, and no re-composition, re-planning, re-rendering,
    translation, summarisation, excerpting or round trip through a model improves
    one. ADR-0155 §3 already forecloses the laundering route: the overlap "falls to
    the absolute clause", because one non-model path keeps content under it
    **forever**.

    **A third axis, and not a reading of either of the other two.** It is not
    :class:`DiscloserProvenance`, not a :class:`DataTier`, and not
    ``planned_with_external_content`` — which answers a different question, whether
    the material *selected into the planning call* carried the external mark. No
    lane reads one of the three off another, at any site, and no surface renders
    one as the other (ADR-0233 §4, §8).

    **The order is total and is ADR-0155 §3's own, not this type's invention**:
    ``NOT_COVERED`` < ``MODEL_ON_EVERY_PATH`` < ``PATH_WITHOUT_MODEL``. A call is
    governed by the most restrictive clause any part of it reaches, which is
    strictly conservative and is the direction §3 already chose. The member order
    below is that order; nothing compares two members by their values, because
    ``StrEnum`` compares as text and ``"model_on_every_path" < "not_covered"``
    lexically — a lane needing the order writes it out rather than reading it off
    the strings.
    """

    #: No covered path, so nothing the call would carry is covered content at all
    #: (ADR-0233 §4). **Never rendered as an assurance**: it states that no covered
    #: path was recorded for this call, never that nothing in it relates to
    #: anything the user has told this system, and never that the send is safe
    #: (ADR-0233 §8).
    NOT_COVERED = "not_covered"
    #: Covered, and every covered path of everything the call would carry contains
    #: a model call — ADR-0155 §3's **third** clause's subject, and the only class
    #: this system may carry, under the four conjunctive conditions ADR-0233 §9
    #: states.
    MODEL_ON_EVERY_PATH = "model_on_every_path"
    #: Covered, and at least one covered path of something the call would carry
    #: contains **no** model call — ADR-0155 §3's **second** clause's subject,
    #: which is absolute and which no authorisation, user act, policy or grant
    #: cures. :class:`EgressBinding` refuses it at construction (ADR-0233 §6), so a
    #: call carrying it is unconstructable rather than merely forbidden. It is also
    #: the **fail-closed** value: a component holding no recorded origin answers it,
    #: because a component that wrongly says this gets its call refused and someone
    #: notices immediately, while one that wrongly says ``NOT_COVERED`` sends the
    #: user's accumulated model to a third party and nobody notices at all
    #: (ADR-0233 §4, ADR-0146 §2's fail-closed rule read on this axis).
    PATH_WITHOUT_MODEL = "path_without_model"


class EgressDestination(BaseModel):
    """One **occurrence** of a recipient, in both the forms ADR-0148 §2 requires.

    The binding carries occurrences and derives the set, never the reverse, and
    only one of the two directions is available: occurrences yield the set by
    deduplication, while the set yields nothing, because an alias pair collapses
    on the way in and ADR-0148 §14 names reconstruction of a supplied form from a
    canonical one as a failure in terms.

    The span this rides on carries which argument and which position it came
    from, so no occurrence repeats them (ADR-0150 §3).

    **`core` does not check `canonical` against `supplied`, and that absence is
    not licence.** ADR-0148 §2's sixth clause puts that computation in one place
    at the seam, so the rule relating the two forms is not a thing this value
    holds; ADR-0150 §11 obliges surface (b) to check that every occurrence
    carries the form that seam's own canonicaliser computes. Until it lands, no
    lane states that a carried canonical form has been verified against anything.
    What `core` *can* see it does refuse: :class:`EgressBinding` rejects two
    occurrences that canonicalise one supplied form two ways.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    protocol: DestinationProtocol = Field(
        description="Under whose rules the canonical form was computed (ADR-0148 §2)."
    )
    supplied: EncodableText = Field(description="The form the arguments carry, unchanged.")
    canonical: _VisibleUnchangedText = Field(
        description="The form ADR-0148 §2 computed from the supplied one, at the seam."
    )


class EgressSpan(BaseModel):
    """One described span of an outbound payload (ADR-0150 §4, §5, §6).

    A span is identified by the pair ``(argument, index)``: ``argument`` is a
    top-level key of the request's ``parameters``, and ``index`` is the
    zero-based position within an ordered decomposition of that argument's value,
    **absent** exactly where the span's value is the argument's whole value.

    **The decomposition goes at most one array level deep and never further.**
    Where an argument's value is a JSON array its elements are its spans,
    whatever those elements are; where it is any other JSON value it is one span.
    A span's own value is never decomposed, so a span whose value is a JSON
    object or a nested array is one span and the extent, provenance and tier it
    states are that whole value's. An earlier draft made the depth a property of
    the *value* rather than of the decomposition, and ``[["a"], ["b"]]``
    satisfied two antecedents whose consequents no binding could satisfy at once.

    **``argument`` is a locator and asserts nothing about what the span
    contains.** No lane reads an argument name as a payload value, infers a tier
    or a provenance from it, matches a destination against it, or treats it as
    authored by the tool rather than supplied by the caller — a schema that does
    not describe a key still admits it (ADR-0145 §9, §11). What a span says about
    its content is ``provenance`` and ``tier``, and nothing else.

    **A span carries at most one destination**, which is the type-level half of
    ADR-0150 §4's cardinality clause. The other half is a *builder* obligation
    and is not `core`'s: a builder holding two or more recipients inside one
    undecomposable value refuses rather than carrying one and omitting the rest,
    and `core`, which cannot see inside such a value, can neither perform that
    check nor read a structured span's single occurrence as evidence that the
    value selected one recipient. ADR-0150 §11 routes it, with the
    mixed-provenance refusal, to the seam that holds the values.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    argument: EncodableText = Field(
        description="The top-level parameters key this span came from; a locator only."
    )
    index: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Zero-based position within the argument's decomposition; absent "
            "exactly where the span's value is the argument's whole value."
        ),
    )
    provenance: DiscloserProvenance = Field(
        description=(
            "Who disclosed this span (ADR-0146 §1). Required with **no default**: "
            "a defaulted field is what a lane forgets, and a builder holding no "
            "recorded origin answers SYSTEM_SELECTED in code a reviewer can see."
        )
    )
    extent: int = Field(
        ge=0,
        description=(
            "The number of **Unicode code points** in the span's value where that "
            "value is a JSON string, and otherwise in that value's canonical JSON "
            "encoding — the same encoding ``parameters_digest`` is taken over. "
            "Never bytes, UTF-16 units, grapheme clusters or rendered columns, and "
            "no configuration selects between them: two components that measured "
            "differently would build unequal bindings for one request and "
            "``authorises`` would answer False, which reads as an attack."
        ),
    )
    tier: DataTier | None = Field(
        default=None,
        description=(
            "The tier of this span's value where the field it occupies "
            "**establishes** one in ADR-0146 §5's sense, and absent otherwise — "
            "which includes every user-authored free-text span. `core` does not "
            "check it against the declaration, because ADR-0150 §6 defers that "
            "vocabulary to surface (b), and that absence is not licence to leave "
            "the check unbuilt. A stated tier states nothing about "
            "``ToolDefinition.discloses``, which remains ADR-0016 §3's ceiling."
        ),
    )
    destination: EgressDestination | None = Field(
        default=None,
        description="The recipient this span selects, where it selects one.",
    )


class _EgressBindingBase(BaseModel):
    """The members every egress binding carries, whatever epoch recorded it (ADR-0184 §2).

    The root of a private **chain** with three public leaves, which is the shape
    this file already uses for ``_SeverityScale``, ``MemoryBase`` and
    ``ContextFacet``. :class:`EgressBinding` is the whole binding a live call
    carries; :class:`CoverageUnrecordedBinding` is a row recorded between
    ``planned_with_external_content``'s arrival and ``coverage``'s;
    :class:`OriginUnrecordedBinding` is these three facts alone, read back out of a
    row recorded before ADR-0181 §3 added ``planned_with_external_content``. The
    three members declared here, their validators and the derived
    :attr:`canonical_destination_set` are declared **once**, here, and no leaf
    restates any of them (ADR-0233 §14).

    **A chain rather than a matrix, because the epochs are totally ordered in
    time.** A row lacking ``planned_with_external_content`` necessarily lacks
    ``coverage`` too, so each shape is the next one minus a field and no fourth
    combination exists to represent: this base carries what every epoch recorded,
    :class:`_OriginRecordedBindingBase` beneath it adds the member the second
    epoch began recording, and :class:`EgressBinding` adds the third's. Each
    member is therefore still declared exactly once, which is ADR-0184 §2's rule
    obeyed rather than narrowed.

    **Declaring them once is what makes "the same three facts" true by
    construction** rather than by review, and ADR-0184 §2 names what a second
    declaration would be: the "second shape that must agree" ADR-0150 is named
    after, arriving one level down. It matters most for the derived set, because
    that is what a surface renders — a history row whose recipients were computed
    by a second copy of the derivation could disagree with the set the user was
    shown when the ruling was made.

    **The inheritance runs this way round and not the other.** Making
    :class:`EgressBinding` inherit from :class:`OriginUnrecordedBinding` would mint
    one name instead of two and is wrong twice: it reads as "a binding with a
    recorded origin is a kind of binding whose origin was never recorded", and it
    would make ``isinstance(binding, OriginUnrecordedBinding)`` answer ``True`` for
    every live binding, so the one narrowing every consumer performs would silently
    misfire (ADR-0184 §2).

    **Not a value in its own right.** Nothing constructs this base or the one
    beneath it, no field is annotated with either, and no lane widens a field to
    one to avoid narrowing a union. ``extra="forbid"`` is declared here and
    inherited by all three leaves, which is what makes that union total and
    mutually exclusive with no discriminator field (ADR-0184 §3, ADR-0233 §14): a
    stored object carrying **both** ``planned_with_external_content`` and
    ``coverage`` validates as :class:`EgressBinding` and as nothing else; one
    carrying ``planned_with_external_content`` but **not** ``coverage`` validates
    as :class:`CoverageUnrecordedBinding` and as nothing else; one carrying
    **neither** validates as :class:`OriginUnrecordedBinding` and as nothing else;
    and one faulty in any further way — including a row carrying ``coverage``
    without ``planned_with_external_content``, a shape no epoch wrote — still
    raises. The tolerance stays exactly as many shapes wide as there are epochs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    spans: tuple[EgressSpan, ...] = Field(
        description=(
            "The payload description: one span per described value, ordered by "
            "argument and then by index. Empty only where the call's arguments are "
            "empty or hold nothing but empty JSON arrays (ADR-0150 §4). "
            "**Required with no default**, like every field §2 names: ADR-0150 §1 "
            "makes a binding whole or absent, and a defaulted description would let "
            "a producer omit the field and get an empty payload description rather "
            "than having to state that the payload has no spans."
        )
    )
    account: BoundAccount = Field(
        description="The connected account the call is made through, as the ruling fixed it."
    )
    transport_endpoint: _VisibleUnchangedText = Field(
        description=(
            "Where the call is transmitted. ADR-0150 §7 constrains its scheme, "
            "host, port and path **not at all**, and that absence is not "
            "permission: what the endpoint must be, and what a redirect may do, is "
            "issue #83's and is decided neither here nor by ADR-0148 §6."
        )
    )

    @property
    def canonical_destination_set(self) -> tuple[CanonicalDestination, ...]:
        """ADR-0148 §2's canonical destination set, **derived** and never stored.

        One member per distinct destination the spans carry — and, where the
        spans carry **none**, exactly one member: this binding's own connected
        account, which is ADR-0148 §2's third clause. It is therefore **never
        empty**, and no policy refuses on ADR-0148 §8's third floor on the ground
        that a binding's spans carry no destination.

        **Derived rather than stored satisfies ADR-0148 §6's last sentence; a
        stored field is the shape that would breach it.** That sentence forbids
        two things. *Derived after the ruling*: the value is fixed before the
        ruling because everything it reads is — the occurrences and the account
        are fixed in the request, this model is frozen with ``extra="forbid"``,
        and the deduplication and a **total** order are fixed here, so the
        function is single-valued, total and settled at construction. Computing a
        value on access is not determining it later; nothing that could change
        the answer survives construction. *Re-derived at the seam*: this runs in
        `core` over the value's own fields — no seam call, no store read, no
        clock, no network.

        **Materialising it is what would create the drift.**
        :meth:`PermissionDecision.authorises` compares whole values, so a stored
        set that disagreed with the occurrences it was computed from would be
        compared as written. A decision read back from the record rebuilds the
        occurrences and recomputes an *identical* set, because the order and the
        deduplication are fixed here; a stored set could be read back disagreeing
        with its own occurrences and nothing downstream would catch it.

        **The account substitution is conditional on the spans being complete.**
        ADR-0148 §2's third clause states its antecedent as a call whose
        *arguments* select no recipient, and "the spans carry none" stands for
        that faithfully only where every destination-bearing argument has already
        yielded its occurrences. `core` cannot check that — which arguments are
        destination-bearing is the declaration vocabulary ADR-0150 §6 defers — so
        ADR-0150 §11 obliges surface (b) to refuse the binding that would defeat
        it. No lane reads an account-only set as evidence that a call selected no
        recipient.

        **Total, never raising.** ADR-0150 §8's first bullet: a derived property
        that raises rather than returns is a gate that fails by exception, and an
        exception is caught somewhere. Every occurrence's ``protocol`` is
        required and its ``canonical`` form is already visible text, so every
        member this builds is well-formed by construction.

        Returns:
            The deduplicated, totally ordered set: account members first, then
            selected recipients by protocol and then by canonical form, each
            string compared by Unicode code point.
        """
        members = {
            CanonicalDestination(
                protocol=span.destination.protocol, canonical=span.destination.canonical
            )
            for span in self.spans
            if span.destination is not None
        }
        if not members:
            return (CanonicalDestination(account=self.account),)
        return tuple(sorted(members, key=_destination_order))

    @model_validator(mode="after")
    def _spans_describe_one_decomposition(self) -> Self:
        """Refuse ADR-0150 §4's three **structural** span invariants.

        Exactly those three, and they are not the whole of what this value
        refuses: :meth:`_one_supplied_form_canonicalises_one_way` is a further
        binding-visible refusal and nothing here narrows it.

        The invariants a binding *can* discharge are facts about its own span
        tuple. A binding holding a span for ``"body"`` cannot tell whether
        ``"body"`` is a key at all, whether its value is an array, or how many
        code points it carries, so requiring it to refuse on those grounds would
        be an obligation no implementation could discharge, and the first lane to
        meet it would reach for a copy of ``parameters``.

        **The messages name an argument's position in the tuple rather than its
        name.** ADR-0150 §8 permits naming an argument; this declines to, because
        ADR-0150 §13's residue records that a caller — or a model composing the
        call — can put content of its own choosing into a *key*, and `core`
        cannot tell an author's key from a caller's. Declining is strictly
        stronger than the clause requires and cannot breach ADR-0145 §8 either.

        Raises:
            ValueError: If two spans share an ``(argument, index)`` pair, if an
                argument's spans are not one indexless span or a contiguous
                ``0..k-1`` run, or if the tuple is not in order.
        """
        keys = [(span.argument, span.index) for span in self.spans]
        if len(set(keys)) != len(keys):
            msg = "two spans share an (argument, index) pair, so one span is described twice"
            raise ValueError(msg)

        by_argument: dict[str, list[int | None]] = {}
        for argument, index in keys:
            by_argument.setdefault(argument, []).append(index)
        for indices in by_argument.values():
            if indices == [None]:
                continue
            positions = [index for index in indices if index is not None]
            if len(positions) != len(indices) or sorted(positions) != list(range(len(positions))):
                msg = (
                    "an argument's spans are either exactly one indexless span or spans "
                    "indexed 0 through k-1; this argument's are neither"
                )
                raise ValueError(msg)

        if keys != sorted(keys, key=lambda key: (key[0], key[1] is not None, key[1] or 0)):
            msg = (
                "spans are ordered by argument and then by index, absent first, with "
                "arguments compared by Unicode code point"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _one_supplied_form_canonicalises_one_way(self) -> Self:
        """Refuse two occurrences that canonicalise one supplied form two ways (ADR-0150 §3).

        A canonicaliser is a **function** of the supplied form, so two
        occurrences sharing a protocol and a supplied form and differing in their
        canonical form are two derivations of one form disagreeing. This is the
        part of ADR-0148 §2's sixth clause that is visible from inside one value,
        and it is checked here rather than assumed.

        It is *not* the correspondence check: whether a carried canonical form is
        what the seam's own canonicaliser computes is ADR-0150 §11's obligation on
        surface (b), because ADR-0148 §2 puts that rule at the seam and a copy of
        it here would be the second canonicaliser that clause forbids.

        Raises:
            ValueError: If two occurrences share a protocol and a supplied form
                and differ in their canonical form.
        """
        derived: dict[tuple[DestinationProtocol, str], str] = {}
        for span in self.spans:
            occurrence = span.destination
            if occurrence is None:
                continue
            key = (occurrence.protocol, occurrence.supplied)
            if derived.setdefault(key, occurrence.canonical) != occurrence.canonical:
                msg = (
                    "two occurrences share a protocol and a supplied form and carry "
                    "different canonical forms, so one supplied form canonicalised two ways"
                )
                raise ValueError(msg)
        return self


class _OriginRecordedBindingBase(_EgressBindingBase):
    """The members a binding recorded from ADR-0181 §3 onwards carries (ADR-0233 §14).

    The chain's second rung: :class:`_EgressBindingBase`'s three members plus
    ``planned_with_external_content``, shared by :class:`EgressBinding` and
    :class:`CoverageUnrecordedBinding` and by nothing else. It exists so that
    ``planned_with_external_content`` is declared **once** across the two shapes
    that carry it, which is ADR-0184 §2's declare-each-member-once rule obeyed at
    the rung the second epoch begins.

    **Not a value in its own right**, exactly as its own base is not: nothing
    constructs it, no field is annotated with it, and no lane widens a field to it
    to avoid narrowing a union. A consumer that must tell the shapes apart narrows
    with ``isinstance`` against a **leaf**; ``isinstance(binding,
    _OriginRecordedBindingBase)`` is not a discrimination this corpus performs, and
    a private name is not one an adapter may reach for at all.
    """

    planned_with_external_content: bool = Field(
        description=(
            "The value the seam was handed on "
            ":attr:`CarriedProvenance.planned_with_external_content`, unchanged "
            "(ADR-0181 §3). Fixed in the :class:`ActionRequest` before the ruling "
            "and transcribed verbatim into the recorded decision, exactly as every "
            "other member of the binding is (ADR-0148 §6). **Required with no "
            "default**, like every field ADR-0150 §2 names, and for the reason "
            "ADR-0181 §3 gives: a defaulted False would state that no external "
            "material was selected, on behalf of a lane that made no selection. "
            "``rebind`` **transcribes** it from the approved binding rather than "
            "re-deriving it, which is the second of the three things ADR-0152 §7's "
            "count now admits (ADR-0181 §3's fifth clause, ADR-0233 §4)."
        )
    )


class EgressBinding(_OriginRecordedBindingBase):
    """The whole egress binding: surface (a) of ADR-0148 §11 (ADR-0150 §1).

    One value rather than several fields, for three reasons and the third is the
    one that would be hard to recover from. :meth:`PermissionDecision.authorises`
    gains one conjunct rather than four, and it is an explicit conjunction rather
    than a total field comparison, so every field added to it is a line someone
    has to remember. Four independent optional fields admit fifteen partial
    states, of which fourteen name a destination set and no account or an account
    and no description — and ADR-0148 §8's third clause makes those a *floor*,
    which means an implementation that gets it wrong is the thing the floor
    defends against. And the facts are only meaningful together: a canonical
    destination set with no connected account is not authorisable, and a payload
    description with no destinations is ADR-0146 §5's "your words, to this
    recipient" with the second half missing.

    A binding is **either whole or absent**. Every field here is required; there
    is no partially populated binding, and ``None`` on a request or a decision
    means the request is not an egress call.

    **``planned_with_external_content`` rides here rather than beside the binding**
    (ADR-0181 §3). One carriage, for ADR-0150 §1's reason: the binding is the thing
    bound, the thing :meth:`PermissionDecision.authorises` compares and the thing
    transcribed into the record, and a second carriage would have to be joined to it
    by something. It is on the binding rather than on a span because ADR-0181 §2
    rules the fact a property of the **call**; a call-level fact on a span would look
    like a span-level claim, which that section's third clause refuses to mint.

    **This value does not carry ``parameters``, and no lane gives it a copy so
    that it can check them here.** That is the state stated twice this decision
    is named against. The three structural invariants below are facts about this
    value's own span tuple, so they stay with the value that holds them; every
    parameter-relative invariant is :class:`ActionRequest`'s alone (ADR-0150 §4),
    checked by its validator against its own arguments, where both sides are in
    hand.

    **Four of its five members are declared on the private chain it shares with**
    :class:`CoverageUnrecordedBinding` and :class:`OriginUnrecordedBinding`
    (ADR-0184 §2, ADR-0233 §14). Nothing about the members themselves moves:
    ``planned_with_external_content`` stays ``bool``, required, with no default;
    none is removed or re-typed; and every ADR-0181 §10 invariant over a binding
    that has the field holds exactly as ratified. What changed is only where four
    of the five are written down.

    **``coverage`` rides here rather than on a span**, for
    ``planned_with_external_content``'s own reason one axis over (ADR-0233 §4).
    The fact is about the **call** — ADR-0155 §3's two prohibitions are about what
    an egress call may carry, and a call carrying one forbidden span is a forbidden
    call — so a per-span field would look like a span-level claim, would cost two
    amendments to ratified clauses (ADR-0150 §10's per-span enumeration and
    ADR-0148 §6's three determinism inputs), and would half-build the per-span
    classification ADR-0150 §6 reserves to the ADR that closes the **tier** axis.
    :class:`EgressSpan` gains nothing, so ADR-0150 §5's marker, ADR-0150 §10's
    enumeration and ADR-0148 §6's three inputs are untouched at the fields they
    govern.
    """

    coverage: SpanCoverage = Field(
        description=(
            "Which of ADR-0155 §3's two prohibitions governs what this call would "
            "carry, over **every** span it would transmit, taken from "
            ":attr:`CarriedProvenance.coverage` unchanged (ADR-0233 §4). Where the "
            "spans differ the value is the **strongest** of their states under "
            ":class:`SpanCoverage`'s total order, because ADR-0155 §3 rules that "
            '"the overlap falls to the absolute clause". **Required with no '
            "default**, for ADR-0181 §3's reason read one axis over: the "
            "safe-looking default is ``NOT_COVERED``, which asserts that nothing in "
            "the call came from anywhere near this system's stores — the exact claim "
            "§3's partition exists to stop anyone making by accident. "
            "``PATH_WITHOUT_MODEL`` is refused at construction (ADR-0233 §6), and "
            "``rebind`` **transcribes** the value from the approved binding rather "
            "than re-deriving it, which is the third of the three things ADR-0152 "
            "§7's count now admits."
        )
    )
    closed_loop: bool = Field(
        default=False,
        description=(
            "Whether this request is **closed-loop** (ADR-0238 §5, as ADR-0247 §4 "
            "restates it): its kind is ``WEB_SEARCH`` and its binding is at the "
            "destination this deployment configured a search provider at, which "
            "ADR-0247 §1 makes the destination the owner chose. A request failing "
            "either of the two is not closed-loop, and every clause ADR-0238 "
            "supersedes binds on it exactly as it does today. **The third and "
            "fourth conditions retire** (ADR-0247 §4): the lineage of the "
            "conversation's recorded external spans no longer decides this, and "
            "there is no per-conversation admission left to hold (ADR-0247 §5). "
            "**Written by `orchestration` alone**, at the moment "
            "the request is built, from values it holds as data it fetched; "
            "**discarded, never merged**, if any producer emitted one; and no model "
            "output, request content or search result contributes to it (§12). "
            "**Defaulting to ``False``, and that is a decision rather than a "
            "convenience** (§5): it keeps ADR-0152 §7's transcription count "
            "untouched — ``rebind`` takes from ``approved`` exactly one thing, "
            "already narrowed twice, and a fourth transcription would supersede that "
            "clause a third time — and ``False`` is the correct value for every "
            "request that can resume, because a ``CONFIRM`` on a ``WEB_SEARCH`` "
            "decision resolves in no turn (ADR-0231 §9). **The default is safe in "
            "the direction a default is usually unsafe**: ``False`` is the "
            "*restrictive* value, so a composition site that fails to compute it "
            "yields a request that is not closed-loop and rules exactly as "
            "``origin/main`` rules today, and the failure mode of the omission is "
            "that milestone 31 does not work, which is loud. It is **not** a floor "
            "bypassed by a missing field, which is what ADR-0233 §4's "
            "required-with-no-default guards for a three-valued fact whose safe "
            "member is not its first."
            " Taken from :attr:`CarriedProvenance.closed_loop` unchanged, which is "
            "ADR-0181 §3's carriage and ADR-0233 §4's shape stated over the same two "
            "types for the same reason. **It is not widened by ADR-0260 §6's second "
            "configured provider**, which rides beside it as "
            ":attr:`forecast_reach`: this field still means *this deployment's own "
            "search* and nothing else, and a forecast read never sets it."
        ),
    )
    forecast_reach: bool = Field(
        default=False,
        description=(
            "Whether this request is a **forecast read at the configured forecast "
            "provider** (ADR-0260 §6, §11), in :attr:`closed_loop`'s own shape and "
            "for its own reason. Taken from "
            ":attr:`CarriedProvenance.forecast_reach` unchanged, and **compared "
            "inside** :meth:`PermissionDecision.authorises` by the whole-value "
            "binding conjunct that already compares ``closed_loop`` — so a ruling "
            "authorises only a request carrying the fact it was taken over, and no "
            "lane compares this member separately or exempts it from that "
            "comparison. **``False`` is the restrictive value and is what "
            "``rebind`` leaves behind**: ADR-0260 §11 mints no park for a forecast "
            "read, so no forecast binding is ever rebound and the default is the "
            "correct value on that path."
        ),
    )

    @model_validator(mode="after")
    def _refuses_a_path_without_a_model_call(self) -> Self:
        """Refuse ``PATH_WITHOUT_MODEL`` at construction, unconditionally (ADR-0233 §6).

        ADR-0155 §3's **second** clause — a span may not carry covered content some
        covered path of which contains no model call — gets its first mechanism
        here. The refusal admits no argument, no tool, no account, no
        configuration, no policy and no user act, and no lane adds a parameter, a
        flag or a subclass through which one could be admitted.

        **At construction rather than at the ruling**, because ADR-0155 §3's fourth
        clause makes authorisation irrelevant to it: "No authorisation makes a
        transmission either prohibition above forbids lawful." A refusal a policy
        could be replaced out of is not the refusal that clause asks for, which is
        also why ADR-0233 §6 adds no ``ActionPolicy`` floor for this case — a
        request carrying the value is unconstructable, so a policy clause would be a
        second statement of one invariant with nothing to rule on.

        **The whole call is refused rather than the span, and that is the
        conservative direction.** ADR-0155 §3's clauses are stated over a span, so a
        per-span refusal would let the rest of a call through; refusing the call
        refuses a superset and never admits a span either clause forbids. It also
        matches what the seam can do — ADR-0150 §4 makes the spans the arguments,
        and a send missing an argument is not a narrower send but a different one.

        **This discharges ADR-0155 §4's marked clause only to the extent the value
        was honestly recorded**, and no lane states or implies more. Nothing here
        detects a component that records ``NOT_COVERED`` for a call carrying a store
        value, and nothing inspects content to check a recorded state against it.

        **The message names no value** (ADR-0150 §8): the state is what names the
        defect, and it is a recorded classification rather than any part of the
        payload.

        Raises:
            ValueError: If ``coverage`` is ``PATH_WITHOUT_MODEL``.
        """
        if self.coverage is SpanCoverage.PATH_WITHOUT_MODEL:
            msg = (
                "an egress call carrying covered content some covered path of which "
                "contains no model call is forbidden absolutely, whatever any "
                "authorisation, policy, grant or user answer says, so no binding "
                "describes one (ADR-0155 §3, ADR-0233 §6)"
            )
            raise ValueError(msg)
        return self


class CoverageUnrecordedBinding(_OriginRecordedBindingBase):
    """A recorded egress binding from before the coverage field existed (ADR-0233 §14).

    Read out of the permission trail and **never** minted, exactly as
    :class:`OriginUnrecordedBinding` is. It represents a decision row written
    between ``planned_with_external_content``'s arrival on :class:`EgressBinding`
    (ADR-0181 §3) and ``coverage``'s (ADR-0233 §4): a stored binding carrying every
    member ``EgressBinding`` requires **but** ``coverage``, each required with no
    default and each satisfying every invariant ``EgressBinding`` enforces over
    those members. A row failing in any other way, in any additional way, or at any
    other position is a corrupted or downgraded store exactly as it was before
    (ADR-0184 §1).

    **This is ADR-0184 §9's deferral answered, and answered the other way.** §9
    deferred a stored payload version for the trail's ``data`` column and named its
    firing condition — the next member added required-with-no-default to a model
    the trail stores — obliging the ADR adding that member to choose between a
    second sibling and a version. ADR-0233 §14 chooses the sibling, because **a
    version key names a schema and supplies no representable value for a row
    lacking a required field**: a stored binding missing one still decodes into no
    type, so a row at an older version would be neither typed nor legible, which is
    the failure ADR-0184 is titled against. §9's objection to accumulating siblings
    does not bite either, and the reason is structural: six pairwise discriminations
    is the cost of *unordered* variants, and these are **ordered**, so each shape is
    the next one minus a field and the discrimination is two field-presence tests
    taken in one direction. No lane adds a further member to this union on the
    strength of this ADR; an ADR adding another member required with no default to a
    model the trail stores makes §9's choice again, in its own text, with three data
    points.

    **The shape of the stored value is the whole of the condition.** No lane
    recognises such a row by ``decided_at``, by a date range, by a schema-version
    marker, by a table column or by a deployment identifier (ADR-0184 §1).

    **It carries the facts the row recorded rather than standing for their
    absence.** A user reading their exported trail sees the connected account, every
    occurrence in both forms, the payload description, the transport endpoint and
    the recorded origin of the call — everything the row actually holds — and learns
    exactly one thing more: that the coverage of this call was never recorded.

    **Nothing is fabricated, in either direction.** ``coverage`` is required with no
    default and ADR-0233 §5 forbids a seam inventing one, so every member of
    :class:`SpanCoverage` is out; this model does not carry the member at all, so
    ``model_dump`` emits no key for it and an export is a faithful copy of what the
    row says. Nothing is written back either: no migration rewrites, backfills,
    annotates, versions, re-keys or deletes such a row, and
    :meth:`~ai_assistant.core.protocols.AuditTrail.record` refuses a decision
    carrying this shape, so it is only ever read out of a store and never minted
    into one (ADR-0184 §4, ADR-0233 §14).

    **A decision carrying one authorises nothing.**
    :meth:`PermissionDecision.authorises` answers ``False`` for it against every
    request, and no conjunct was added to make that true: the binding is compared
    whole and by value (ADR-0150 §9, ADR-0181 §3), pydantic's equality is per class,
    so a model of this class never equals an :class:`EgressBinding` whatever its
    members hold, and ``None`` equals neither (ADR-0184 §6).
    :meth:`~ai_assistant.core.protocols.ActionPolicy.resolve` returns no ``ALLOW``
    on a ``confirmed`` carrying one, whatever ``approved`` says, for ADR-0184 §7's
    own reason extended by cause: the fact the ruling would rest on was never
    recorded.

    **Unconstructable from any live path.** :attr:`ActionRequest.egress_binding`
    stays ``EgressBinding | None`` and :meth:`PermissionDecision.from_request`
    transcribes the binding from the request, so no builder can mint this shape and
    no request can carry one (ADR-0184 §2, §4). No lane composes a
    :class:`ConfirmationEgress` from one either — that model's ``coverage`` is
    required with no default, so composing one would demand the fabrication this
    representation exists to avoid, at the surface where a user is being asked to
    approve something (ADR-0233 §14).

    **The origin guard does not catch this epoch, which is why every refusal for it
    is stated rather than inherited.** Such a row **has**
    ``planned_with_external_content``, so it is not an
    :class:`OriginUnrecordedBinding` and trips no ``isinstance`` written for that
    class; it falls past every origin guard and reaches the site regardless.

    **A consumer tells the three apart with** ``isinstance`` **and nothing else.**
    No tag, no version key, no ``Literal`` member and no ``Field(discriminator=...)``
    is added to any of the three — ``extra="forbid"`` on the shared chain already
    does the job — and no convenience is minted for the narrowing (ADR-0184 §2, §3).
    """


class OriginUnrecordedBinding(_EgressBindingBase):
    """A recorded egress binding from before the origin field existed (ADR-0184 §2).

    Read out of the permission trail and **never** minted. It represents a decision
    row written between ``egress_binding``'s arrival on
    :class:`PermissionDecision` (ADR-0150 §1) and
    ``planned_with_external_content``'s (ADR-0181 §3): a stored binding carrying
    every member :class:`EgressBinding` requires **except** that one **and**
    ``coverage`` — a genuine pre-origin row lacks both, because the epochs are
    totally ordered and it predates each (ADR-0233 §14) — each satisfying its own
    constraint, and carrying no member ``EgressBinding`` does not declare. A row
    failing in any other way, in any additional way, or at any other position is a
    corrupted or downgraded store exactly as it was before (ADR-0184 §1). ADR-0184
    §9 authorised exactly this one sibling for exactly that one epoch and obliged
    the next such member to decide its own history representation in its own text;
    ADR-0233 §14 is that decision, and :class:`CoverageUnrecordedBinding` is the
    shape it mints for the epoch after this one.

    **The shape of the stored value is the whole of the condition.** No lane
    recognises such a row by ``decided_at``, by a date range, by a schema-version
    marker, by a table column or by a deployment identifier (ADR-0184 §1). The trail
    is append-only and ordered but carries no record of which code wrote a row, and
    a restored backup or a copied data directory carries rows whose timestamps say
    nothing about the schema they were written under.

    **It carries the facts the row recorded rather than standing for their
    absence.** A user reading their exported trail sees the connected account, every
    occurrence in both its supplied and its canonical form, the payload description
    and the transport endpoint — everything the row actually holds — and learns
    exactly one thing more: that the origin of this call was never recorded. A
    marker type saying only "this row is old" would have thrown the rest away to say
    it.

    **Nothing is fabricated, in either direction.** ADR-0181 §3 makes
    ``planned_with_external_content`` required with no default and §4's second
    clause forbids a seam inventing it, so ``False`` and ``True`` are both out; this
    model carries neither that member nor ``coverage``, so ``model_dump`` emits no
    key for either
    and an export is a faithful copy of what the row says. Nothing is written back
    either: no migration rewrites, backfills, annotates, versions, re-keys or
    deletes such a row, and
    :meth:`~ai_assistant.core.protocols.AuditTrail.record` refuses a decision
    carrying this shape, so it is only ever read out of a store and never minted
    into one (ADR-0184 §4).

    **A decision carrying one authorises nothing.**
    :meth:`PermissionDecision.authorises` answers ``False`` for it against every
    request, and no conjunct was added to make that true: the binding is compared
    whole and by value (ADR-0150 §9, ADR-0181 §3), pydantic's equality is per class,
    so a model of this class never equals an :class:`EgressBinding` whatever its
    members hold, and ``None`` equals neither (ADR-0184 §6).
    :meth:`~ai_assistant.core.protocols.ActionPolicy.resolve` returns no ``ALLOW``
    on a ``confirmed`` carrying one, whatever ``approved`` says (ADR-0184 §7).

    **Unconstructable from any live path.** :attr:`ActionRequest.egress_binding`
    stays ``EgressBinding | None`` and :meth:`PermissionDecision.from_request`
    transcribes the binding from the request, so no builder can mint this shape and
    no request can carry one (ADR-0184 §2, §4). No lane composes a
    ``ConfirmationEgress`` from one — that model's
    ``planned_with_external_content`` is required with no default, so composing one
    would demand the fabrication this whole representation exists to avoid, at the
    surface where a user is being asked to approve something (ADR-0184 §8).

    **A consumer tells the three apart with** ``isinstance`` **and nothing else.**
    No tag, no version key, no ``Literal`` member and no ``Field(discriminator=...)``
    is added to any of the three — ``extra="forbid"`` on the shared chain already
    does the job — and ADR-0184 §2 declines to mint a convenience for the narrowing.
    """


def _destination_order(member: CanonicalDestination) -> tuple[int, str, str]:
    """Order the derived set: account members first, then by protocol and form.

    Total over every well-formed member, and total is what it must be — the
    ordering is part of what makes the derived property single-valued, so a
    decision read back from the record recomputes an identical tuple. Strings
    compare by Unicode code point, which is what Python's ``str`` ordering is.
    """
    if member.account is not None:
        return (0, member.account.reference, member.account.identity)
    protocol = member.protocol.value if member.protocol is not None else ""
    return (1, protocol, member.canonical or "")


def _detached_binding(value: EgressBinding | None) -> EgressBinding | None:
    """Take the request's own copy of the binding, rebuilt through validation.

    The discipline :func:`_detached_tool` already carries for the declaration
    (ADR-0018 §3), applied to the one field whose rewrite ADR-0148 §4's third
    clause exists to make impossible. Pydantic passes an already-valid model
    instance through without copying, so an :class:`ActionRequest` would
    otherwise share the caller's binding — and ``object.__setattr__`` on that
    original would change which recipients the request is *about* after a policy
    had ruled on it.

    Rebuilt through ``model_validate`` rather than merely deep-copied, for the
    same reason the declaration is: a binding assembled by ``model_construct``
    skips every validator, and revalidating here means the request's own copy has
    passed them whatever the caller handed over.
    """
    if value is None:
        return None
    return EgressBinding.model_validate(value.model_dump())


def _span_extent(value: FrozenJson) -> int:
    """Count a span's value in Unicode code points, the way ADR-0150 §4 fixes it.

    A JSON string is counted directly — Python's ``len`` over a ``str`` *is* a
    code-point count — and every other value in its canonical JSON encoding,
    which is the encoding :func:`_canonical_bytes` pins and ``parameters_digest``
    is taken over. Reusing that encoding rather than inventing a second one is
    the point: the codebase already has exactly one canonical encoding, and a
    second would be a second thing to get wrong.
    """
    if isinstance(value, str):
        return len(value)
    return len(_canonical_bytes(_thaw_json(value)).decode("utf-8"))


def _decomposition_defect(value: FrozenJson, spans: Sequence[EgressSpan]) -> str | None:
    """Why ``spans`` are not the decomposition of ``value``, or ``None`` (ADR-0150 §4).

    A frozen JSON array is a ``tuple`` — :func:`_deep_freeze` makes it one — and
    a ``str`` is not, so "is this argument's value a JSON array" is exactly that
    test and nothing subtler.

    The clause requiring a **non-array** argument to carry exactly one indexless
    span is what makes the pair of locatable shapes *exhaustive rather than
    merely usual*: without it an indexed span on a string-valued argument would
    be constructable and unlocatable, and :func:`_span_defect` would have a
    residue this surface would have had to invent an owner for.

    Returns:
        The defect, phrased without naming the argument or rendering any part of
        its value (ADR-0150 §8), or ``None`` where the spans decompose it.
    """
    elements = value if isinstance(value, tuple) else None
    if elements is not None and not elements:
        if spans:
            return "an argument whose value is an empty JSON array is described by no span"
        return None
    if not spans:
        return "every argument this call carries is described by at least one span"
    if elements is not None:
        positions = sorted(span.index for span in spans if span.index is not None)
        if len(positions) != len(spans) or positions != list(range(len(elements))):
            return (
                "an argument whose value is a JSON array of length n is described by "
                "spans indexed exactly 0 through n-1"
            )
    elif len(spans) != 1 or spans[0].index is not None:
        return (
            "an argument whose value is not a JSON array is described by exactly one "
            "span, whose index is absent"
        )
    return None


def _span_defect(value: FrozenJson, span: EgressSpan) -> str | None:
    """Why ``span`` misstates the argument value it locates, or ``None`` (ADR-0150 §4).

    Called only after :func:`_decomposition_defect` has cleared, so a span with
    an ``index`` locates an element of a JSON array of at least that length and
    one without locates the argument's whole value. Both are what make the
    recomputation total.

    The supplied-form check is the one that closes at the type level a
    description "naming a recipient the arguments never selected". It is stated
    over *a destination on that span* and is therefore vacuous where the span
    carries none — ADR-0150 §11 obliges surface (b) to refuse the omission,
    because only the tool's declaration says which arguments are
    destination-bearing. It is also silent where the located value is not a JSON
    string, because a supplied form extracted from inside a structured value is
    something `core` cannot see into; that residue is (b)'s too, and this
    function claims no check it does not perform.

    The extent, by contrast, leaves no residue: it is stated over the span's
    **whole** value, and both locatable shapes are reachable from here.

    Returns:
        The defect, naming no value (ADR-0150 §8), or ``None``.
    """
    held: FrozenJson = value if span.index is None else value[span.index]  # type: ignore[index]  # an indexed span locates an array element, checked above
    occurrence = span.destination
    if isinstance(held, str) and occurrence is not None and occurrence.supplied != held:
        return "a span's destination states a supplied form the argument's own value does not hold"
    if span.extent != _span_extent(held):
        return "a span's stated extent is not its value's Unicode code-point count"
    return None


class EgressSpanLocator(BaseModel):
    """A span's key on the binding seam (ADR-0152 §1).

    ADR-0150 §4 identifies a span by the pair ``(argument, index)``. Where that
    pair has to be a **mapping key** — the carried provenance
    :class:`CarriedProvenance` holds — it needs a hashable value that validates
    its own fields, and this is it.

    **Each field has the same type and the same validation as the field of the
    same name on** :class:`EgressSpan`, and this ADR fixes no type for either
    beyond that identity: ``EgressSpan`` owns them, and a locator that could be
    well-formed where the span it names could not would be a second answer to one
    question. ``index`` is optional and absent by default in the same way.

    **Two locators are equal exactly when both fields are equal**, and a locator
    names the span of an :class:`EgressBinding` whose ``argument`` and ``index``
    equal its own.

    **It is not a span, and it is durable nowhere.** It carries no provenance, no
    extent, no tier and no destination, holds no reference to a binding or a span,
    and enters no :class:`ActionRequest` and no :class:`PermissionDecision`. That
    is what answers the objection that it restates ``EgressSpan``'s first two
    fields: no record can hold a locator that disagrees with the span it names, so
    this is unlike the duplications ADR-0150 is named against, every one of which
    was two *stored* shapes.

    ``revalidate_instances="always"`` for :class:`SecretName`'s reason:
    ``model_construct`` builds an instance without running validators, and it is
    public (ADR-0152 §1).
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    argument: EncodableText = Field(
        description="The top-level parameters key the span it names came from."
    )
    index: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Zero-based position within the argument's decomposition; absent "
            "exactly where the named span's value is the argument's whole value."
        ),
    )


class _FrozenProvenance(Mapping[EgressSpanLocator, DiscloserProvenance]):
    """An immutable, hashable mapping from a span locator to its provenance.

    :class:`FrozenDict`'s idiom for the one other key type this module needs.
    The contents are a **tuple of pairs** and attribute assignment is refused, so
    there is no mutable object reachable through an instance — which is what
    ADR-0152 §1's detachment clause needs of the carrier: the value it holds
    cannot be rewritten after validation, whatever the caller kept.

    ``MappingProxyType`` is refused for :class:`FrozenDict`'s reason: it can be
    neither pickled nor deep-copied, so any model holding one would fail
    ``model_copy(deep=True)``.
    """

    __slots__ = ("_items",)

    _items: tuple[tuple[EgressSpanLocator, DiscloserProvenance], ...]

    def __init__(
        self, data: Mapping[EgressSpanLocator, DiscloserProvenance] | None = None, /
    ) -> None:
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

    def __getitem__(self, key: EgressSpanLocator) -> DiscloserProvenance:
        """Return the provenance recorded for ``key``, raising ``KeyError`` if absent."""
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[EgressSpanLocator]:
        """Iterate over the locators, in insertion order."""
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        """Return the number of locators."""
        return len(self._items)

    def __repr__(self) -> str:
        """Return a dict-like representation of the contents."""
        return f"_FrozenProvenance({dict(self._items)!r})"

    def __eq__(self, other: object) -> bool:
        """Compare equal to any mapping with the same contents."""
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        """Hash by contents; possible because both the keys and the values are frozen."""
        return hash(frozenset(self._items))

    def __reduce__(
        self,
    ) -> tuple[type[_FrozenProvenance], tuple[dict[EgressSpanLocator, DiscloserProvenance]]]:
        """Support pickling (and, via it, ``copy.deepcopy``)."""
        return (_FrozenProvenance, (dict(self._items),))


def _detached_provenance(
    value: Mapping[EgressSpanLocator, DiscloserProvenance],
) -> Mapping[EgressSpanLocator, DiscloserProvenance]:
    """Take the carrier's own copy of the caller's mapping (ADR-0152 §1).

    ``frozen=True`` protects the field, not the object the field points at
    (ADR-0018 §3), so a carrier validated over a caller's ``dict`` would leave the
    caller able to rewrite what the seam then reads. Detaching at validation is
    what makes the carrier's contents fixed at construction.
    """
    return _FrozenProvenance(value)


def _thaw_provenance(
    value: Mapping[EgressSpanLocator, DiscloserProvenance],
) -> list[dict[str, object]]:
    """Render the carrier's mapping as a list of pairs, for serialisation.

    A pydantic model is not a JSON object key, so the mapping is dumped as an
    ordered list of ``{"span": …, "provenance": …}`` entries. Nothing durable
    holds a :class:`CarriedProvenance` — ADR-0152 §1 makes it an argument and
    nothing else — so this exists to keep ``model_dump`` total rather than to
    define a storage form.
    """
    return [
        {"span": locator.model_dump(), "provenance": provenance.value}
        for locator, provenance in value.items()
    ]


class CarriedProvenance(BaseModel):
    """The recorded origins crossing the binding seam, as one validating value.

    ADR-0152 §1's carrier. ADR-0146 §2 makes a span's provenance **carried, never
    derived**, so it is the one thing the seam cannot compute — and the one thing
    a caller therefore hands over. What it hands over is this, not a bare mapping.

    **An annotation is not a constructor, and that is why this type exists.** An
    earlier draft of ADR-0152 annotated the argument
    ``Mapping[EgressSpanLocator, DiscloserProvenance]`` and architecture review
    found on round 2 that Python builds no locator for a mapping key: ``{object():
    object()}`` crosses the boundary exactly as before, and the seam must either
    re-check by hand or raise something it never declared. ADR-0150 §8 settles it
    in terms — the shape that ends the class "is making these values pydantic
    models in ``core/types.py``, which validate their own fields on construction".
    A mapping cannot be such a model; a model holding the mapping can.

    **It validates every key and every value on construction**, refusing a key
    that is not a well-formed locator and a value that is not one of ADR-0146 §1's
    two members, and it **detaches** the caller's mapping so the value it holds
    cannot be rewritten afterwards (ADR-0018 §3).

    **``spans`` has no default**, and neither has the ``provenance`` argument on
    :meth:`~ai_assistant.core.protocols.EgressBinder.bind`: a caller holding no
    recorded origin constructs one over an empty mapping and passes it
    deliberately. This is ADR-0150 §5's no-default reasoning applied at the seam
    that would otherwise inherit the permissive answer for free.

    **``coverage`` rides here beside ``planned_with_external_content`` and
    ``spans`` is untouched** (ADR-0233 §4). Its key type, its value type, its
    detachment validator and its serializer all stand: ``coverage`` is a fact about
    the **call** rather than about a span, so it is a member of this carrier and not
    an entry in its mapping, and the seam writes the binding's value from it
    unchanged exactly as ADR-0181 §3 makes it write
    ``planned_with_external_content``.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    spans: Annotated[
        Mapping[EgressSpanLocator, DiscloserProvenance],
        AfterValidator(_detached_provenance),
        PlainSerializer(_thaw_provenance),
    ] = Field(
        description=(
            "The recorded origin of each span the caller holds one for. A span "
            "absent from it is SYSTEM_SELECTED, written by the seam that builds "
            "the span rather than defaulted by a field (ADR-0146 §2). Required "
            "with no default."
        )
    )
    coverage: SpanCoverage = Field(
        description=(
            "Which of ADR-0155 §3's two prohibitions governs what this call would "
            "carry, over every span it would transmit (ADR-0233 §4, §5). Computed "
            "by the component that **composed the call's arguments**, from the "
            "membership and path character of what it supplied to the operations "
            "that produced them, and written here before the request reaches "
            ":meth:`~ai_assistant.core.protocols.EgressBinder.bind`. A value a "
            "model, a tool, a declaration or a plan emitted for it is **discarded, "
            "not merged**, and nothing derives it by inspecting an argument's value, "
            "its name, its field, its shape or its resemblance to anything — that is "
            "ADR-0146 §2's forbidden inference and ADR-0098 §5's unrecoverable "
            "relation read on this axis. Where several components composed over "
            "several supplies the value is the **strongest** of their states under "
            ":class:`SpanCoverage`'s total order, and no re-composition, "
            "re-planning, re-rendering, translation, summarisation, excerpting or "
            "round trip through a model improves one. **Required with no default**: "
            "the safe-looking default is ``NOT_COVERED``, which asserts that nothing "
            "in the call came from anywhere near this system's stores, so a caller "
            "holding no recorded origin passes ``PATH_WITHOUT_MODEL`` deliberately "
            "and has its call refused at construction, in code a reviewer can see."
        )
    )
    planned_with_external_content: bool = Field(
        description=(
            "Whether the material the caller **selected** into the model call that "
            "produced this request's arguments included a record satisfying "
            "``rests_on_recorded_external_content`` (ADR-0181 §2, §3) — the "
            "disjunction of that predicate over the selected records, computed by "
            "whoever made the selection. A value a model, a tool, a declaration or "
            "a plan emitted for it is discarded rather than merged (ADR-0181 §4). "
            "**Required with no default**: the safe-looking default is False, which "
            "reads as *nothing external was in front of the model* — a claim about "
            "a selection the defaulting lane never made — so a caller holding no "
            "selection passes False deliberately, in code a reviewer can see. It is "
            "**not** a claim that any argument, destination or span was influenced "
            "by external content, nor that any was not (ADR-0098 §5, ADR-0106 §1)."
        )
    )
    closed_loop: bool = Field(
        default=False,
        description=(
            "Whether this request is **closed-loop** (ADR-0238 §5, as ADR-0247 §4 "
            "restates it): its kind is ``WEB_SEARCH`` and its binding is at the "
            "destination this deployment configured a search provider at, which "
            "ADR-0247 §1 makes the destination the owner chose. A request failing "
            "either of the two is not closed-loop, and every clause ADR-0238 "
            "supersedes binds on it exactly as it does today. **The third and "
            "fourth conditions retire** (ADR-0247 §4): the lineage of the "
            "conversation's recorded external spans no longer decides this, and "
            "there is no per-conversation admission left to hold (ADR-0247 §5). "
            "**Written by `orchestration` alone**, at the moment "
            "the request is built, from values it holds as data it fetched; "
            "**discarded, never merged**, if any producer emitted one; and no model "
            "output, request content or search result contributes to it (§12). "
            "**Defaulting to ``False``, and that is a decision rather than a "
            "convenience** (§5): it keeps ADR-0152 §7's transcription count "
            "untouched — ``rebind`` takes from ``approved`` exactly one thing, "
            "already narrowed twice, and a fourth transcription would supersede that "
            "clause a third time — and ``False`` is the correct value for every "
            "request that can resume, because a ``CONFIRM`` on a ``WEB_SEARCH`` "
            "decision resolves in no turn (ADR-0231 §9). **The default is safe in "
            "the direction a default is usually unsafe**: ``False`` is the "
            "*restrictive* value, so a composition site that fails to compute it "
            "yields a request that is not closed-loop and rules exactly as "
            "``origin/main`` rules today, and the failure mode of the omission is "
            "that milestone 31 does not work, which is loud. It is **not** a floor "
            "bypassed by a missing field, which is what ADR-0233 §4's "
            "required-with-no-default guards for a three-valued fact whose safe "
            "member is not its first."
            " The seam writes :attr:`EgressBinding.closed_loop` from this value "
            "unchanged. **It is not widened by ADR-0260 §6's second configured "
            "provider**: that decision gives this carrier one more boolean, "
            ":attr:`forecast_reach`, in this field's own shape, because a widening "
            "would rewrite what stored rows assert and would supersede a clause "
            "ADR-0247 §4 states as unchanged. This field still means *this "
            "deployment's own search* and nothing else, and a forecast read never "
            "sets it."
        ),
    )
    forecast_reach: bool = Field(
        default=False,
        description=(
            "Whether this request is a **forecast read at the configured forecast "
            "provider** (ADR-0260 §6, §11): its kind is a forecast read and this "
            "deployment holds a forecast registration, which ``orchestration`` "
            "knows because ``Forecaster.request`` answered a proposal rather than "
            "``None``. It is ``closed_loop``'s own shape one field along and is "
            "**not** a widening of it — ``closed_loop`` keeps meaning *this "
            "deployment's own search* and nothing else, because widening it would "
            "rewrite what every stored row asserts (ADR-0247 §4). **Written by "
            "``orchestration`` alone**, at the moment the request is built, from "
            "values it holds as data it fetched; **discarded, never merged**, if "
            "any producer emitted one; and no model output, request content or "
            "provider answer contributes to it. **``False`` is the restrictive "
            "value**, so a composition site that fails to compute it yields a "
            "request that is not at the configured forecast provider and rules "
            "exactly as ``origin/main`` rules today. The seam writes "
            ":attr:`EgressBinding.forecast_reach` from this value unchanged, and "
            "``EgressBinder.rebind`` transcribes nothing new for it — ADR-0260 §11 "
            "mints **no park** for a forecast read, so no forecast binding is ever "
            "rebound and ADR-0152 §7's closed transcription count is untouched."
        ),
    )


class BoundEgressCall(BaseModel):
    """The binding and the call it describes, returned together (ADR-0152 §1).

    What both members of :class:`~ai_assistant.core.protocols.EgressBinder`
    return. The caller builds its :class:`ActionRequest` from **these three
    fields** and never from objects it retained across the call.

    **Why the pair rather than a bare binding.** Adversarial review of ADR-0152
    found that a seam which detaches its arguments derives from its own copies
    while the caller builds the request from *its* objects — so a mutation across
    the seam's one await produces exactly the mismatched pair ADR-0152 §1 says
    must not exist. Three shapes answer it and only one is sound. Passing a
    pre-detached call snapshot *in* is unsound: a snapshot the caller constructs
    stays caller-reachable across the await, reproducing the divergence one level
    up. Obliging the caller by rule is a rule where a type will do — the objection
    ADR-0150 §1's fifteen partial states are the corpus's worked instance of. What
    makes this shape sound is that the seam's detached copies are created **before**
    the await and are unreachable from outside the seam until they are returned: a
    mutation bypass needs a reference, and during the suspension nothing outside
    holds one.

    **Exactly three fields and no others.** There is **no** provenance field: a
    span's provenance is already inside :attr:`binding`, and a second copy beside
    it would be two shapes of one fact — the duplication ADR-0150 is named
    against. ``rebind`` has no ``provenance`` argument at all, so such a field
    would also be filled from a different source per member, for no consumer.

    **It carries an** :class:`EgressBinding` **without touching one**: no field is
    added to that model, none is reinterpreted, no second copy of one is stored
    and no alternative to it is minted (ADR-0152 §15). A type that *holds* another
    is not a change to the held one.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    binding: EgressBinding = Field(
        description="The binding the seam derived, whole and accepted from nobody."
    )
    tool: Annotated[ToolDefinition, AfterValidator(_detached_tool)] = Field(
        description=(
            "The detached declaration the derivation read. Detached for "
            "ActionRequest's own reason (ADR-0018 §3): a caller's definition "
            "rewritten through ``object.__setattr__`` would otherwise change what "
            "the returned pair says the binding was derived under."
        )
    )
    parameters: FrozenJsonMapping = Field(
        description=(
            "The detached arguments the derivation read — the same mapping the "
            "binding was derived under, carried here rather than left for the "
            "caller to supply again. Required with no default: a defaulted empty "
            "mapping would let a producer return a binding beside no payload."
        )
    )


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

    # `hide_input_in_errors` is ADR-0145 §8's rule applied to the envelope rather
    # than only to the message inside it: "no message ... renders any part of the
    # parameters — neither a value nor a key", and pydantic otherwise appends
    # `input_value=` to every validation error it raises about this model, which
    # is the whole payload. That exposure pre-dates this decision — a non-finite
    # float in `parameters` already renders them — but ADR-0145 puts a refusal
    # that reads the arguments on a path that runs constantly, so a clean message
    # inside a leaking envelope would be no rule at all. What is lost is the
    # input echo on this model's *other* errors; what is kept is the field name,
    # the error type and the message, which is what names the defect anyway.
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    tool: Annotated[ToolDefinition, AfterValidator(_detached_tool)] = Field(
        description="The declaration being ruled on, by value."
    )
    parameters: FrozenJsonMapping = Field(
        default=_EMPTY_PARAMS,
        description="The arguments the call proposes; bound by digest, never stored.",
    )
    egress_binding: Annotated[EgressBinding | None, AfterValidator(_detached_binding)] = Field(
        default=None,
        description=(
            "The egress binding this call is ruled on with (ADR-0150 §1), or "
            "``None`` where the request is not an egress call. Exactly one field, "
            "never several: four independent optional fields would admit fifteen "
            "partial states that ADR-0148 §8's third floor exists to refuse."
        ),
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

    @model_validator(mode="after")
    def _parameters_satisfy_the_schema(self) -> ActionRequest:
        """Refuse arguments the tool's declared schema rejects (ADR-0145 §1).

        **Before the ruling, not after it, and the ordering is the substance.**
        ``tool.parameters_schema`` and ``parameters`` first sit on one object here,
        and that is not a coincidence of layout: an :class:`ActionRequest` *is* the
        pairing of a chosen tool with the arguments proposed for it, and everything
        downstream of it is either a ruling on those arguments or an execution of
        them. Four things happen between the request and the call, and each spends
        something a later check cannot take back — the user is asked, the
        append-only Tier 1 trail is written, the step is claimed ``RUNNING``, and
        :attr:`PermissionDecision.parameters_digest` binds the payload as given. A
        request that was never built cannot be ruled on, recorded, claimed or
        digested, so checking at construction reaches all four *without anything
        being sequenced correctly*.

        **This holds for every validated construction**, with no exception for a
        confirmation resume, a replay or a test.

        **The bypass is inside the threat model and this clause does not claim
        otherwise.** ``model_construct`` skips every validator and ``frozen=True``
        does not survive a ``__dict__`` write, exactly as ADR-0029 §2 records — and
        the answer is the same one that ADR gives: the validator "catches the honest
        mistake at the point it is made", and the seam holds against a deliberate
        one, because ADR-0029 §2's step 1 revalidates the whole call through
        ADR-0018 §4's dump/validate idiom and therefore re-runs this validator. So
        ``invoke`` gains no fourth check; a call reaching a callable with arguments
        its schema rejects is unreachable without defeating both.

        **This is the backstop, not the obligation.** ADR-0145 §2 puts the duty on
        the stage that binds a tool to a step's arguments: it computes the
        violations first and requests no ruling when there are any (as ADR-0144 §7's
        eligibility filter, ahead of any ordering key). This makes §1's refusal true
        of every request built through validation rather than of the ones a caller
        remembered to check.

        **An evaluation that raises is a refusal, and may say only the exception's
        type.** ADR-0145 §7 forbids rendering, logging or storing anything else
        derived from it — not ``str()``, not ``args``, not ``__cause__``, not
        ``__notes__`` — because a ``ValidationError``'s text carries the instance
        fragments the walk was holding, and a schema that raises on demand would
        otherwise be the one path on which an untrusted document makes the argument
        values arrive in the log. Hence ``from None``: the chain is dropped
        deliberately, not lost.

        Raises:
            ValueError: If the arguments violate the schema, or the evaluation
                raised rather than reporting.
        """
        try:
            violations = parameter_violations(self.tool.parameters_schema, self.parameters)
        except Exception as exc:
            msg = (
                "the tool's parameters_schema could not be evaluated, so the arguments are "
                f"refused ({type(exc).__name__})"
            )
            raise ValueError(msg) from None
        if violations:
            raise ValueError(_refused_parameters(violations))
        return self

    @model_validator(mode="after")
    def _the_binding_covers_the_arguments(self) -> ActionRequest:
        """Refuse a binding that does not describe this call's own arguments (ADR-0150 §4).

        **The split from :class:`EgressBinding`'s own three invariants is where
        the inputs are, not a softening of either check.** The binding does not
        carry ``parameters`` and no lane gives it a copy so that it can check them
        there — that is the state stated twice ADR-0150 is named against. Here both
        sides sit on one object, so `core` **recomputes rather than believes**, and
        an invariant it *can* check is not left to a component further out.

        **Coverage is over the arguments, not over "what the call transmits".**
        `core` cannot know which arguments a callable transmits and which merely
        steer it — a ``draft: true`` flag goes nowhere — and the only way to teach
        it would be a per-argument declaration a tool could get wrong and nothing
        could detect. Requiring coverage of every argument *over-describes* in that
        case, which is the conservative direction: the alternative is a description
        narrower than the payload, the one outcome ADR-0148 §6 forbids in terms.

        **An empty JSON array carries no span**, because a span for it would have
        to state an extent and a provenance for a thing that does not exist, and
        ``SYSTEM_SELECTED`` would be a disclosure record for nothing disclosed. An
        indexless span standing for an absent element would also make ``to: []``
        and ``to: ""`` indistinguishable in the record.

        This is what makes two of ADR-0148 §14's mandated cases **unconstructable
        rather than merely forbidden**: an argument with no span is not a request
        that gets ruled on, it is a request that does not exist — ADR-0029 §2's
        answer to the same problem shape, where a ``DENY`` produces no
        ``ToolCall``.

        **What is left over is routed, not pretended away.** Where a supplied form
        is extracted from *inside* a structured value — a ``{"email": …, "name":
        …}`` recipient — `core` cannot see into it, so ADR-0150 §11 owes that check
        to surface (b). An extent has no such case: a span's value is either the
        argument's whole value or an element of a JSON array, and both are
        locatable from here.

        **No message names an argument**, for the reason
        :meth:`EgressBinding._spans_describe_one_decomposition` gives: a caller can
        write content of its own choosing into a *key*, and `core` cannot tell an
        author's key from a caller's. That also keeps ADR-0145 §8's rule — no
        message renders any part of the parameters, neither a value nor a key —
        true of every message this model raises.

        Raises:
            ValueError: If any span names an argument the call does not carry, if
                an argument is undescribed or an empty array is described, if an
                array's spans are not exactly its elements' positions, if a
                non-array argument is described by anything but one indexless span,
                if a destination's supplied form is not the string the argument
                holds, or if a span's extent is not its value's code-point count.
        """
        binding = self.egress_binding
        if binding is None:
            return self

        described: dict[str, list[EgressSpan]] = {}
        for span in binding.spans:
            described.setdefault(span.argument, []).append(span)

        if not set(described) <= set(self.parameters):
            msg = "a span names an argument this call's parameters do not carry"
            raise ValueError(msg)

        for argument, value in self.parameters.items():
            spans = described.get(argument) or []
            defect = _decomposition_defect(value, spans)
            if defect is not None:
                raise ValueError(defect)
            for span in spans:
                defect = _span_defect(value, span)
                if defect is not None:
                    raise ValueError(defect)
        return self


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
    authorised_subject: Sha256Hex | None = Field(
        default=None,
        description=(
            "The ``subject_digest`` of the :class:`RecipientGrant` this ALLOW was "
            "sourced by, where it was sourced by one (ADR-0193 §6). Set **only** "
            "to the digest of the record the policy's ``covering`` read returned, "
            "recomputed from that record and never carried from anywhere else; a "
            "policy constructed with no authorisation source leaves it unset, as "
            "it leaves ``authorised_by`` unset. Nothing about the grant travels by "
            "value: a digest is sixty-four hex characters whatever the grant's "
            "size, so a grant naming ten thousand recipients adds sixty-four "
            "characters to a decision rather than ten thousand destination entries "
            "(ADR-0004 §7's minimisation)."
        ),
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

    @model_validator(mode="after")
    def _a_fingerprint_needs_the_authorisation_it_fingerprints(self) -> PermissionRuling:
        """Refuse an ``authorised_subject`` where ``authorised_by`` is unset (ADR-0193 §6).

        The same shape as the refusal above and for the same reason: a
        fingerprint of the authorisation is incoherent on a ruling that names
        none.

        **It does not require the converse**, and the asymmetry is the whole of
        what this type can state. A route-(a) ``ALLOW`` sets ``authorised_by`` to
        the confirmation it answers and has no grant to fingerprint, so a pointer
        without a digest is the ordinary shape. Which of the two shapes is *owed*
        is decided at :meth:`~ai_assistant.core.protocols.AuditTrail.record`, the
        only component that can see ``resolves`` and ``egress_binding``.

        Raises:
            ValueError: If ``authorised_subject`` is set and ``authorised_by`` is
                not.
        """
        if self.authorised_subject is not None and self.authorised_by is None:
            msg = (
                f"a ruling that names no authorisation fingerprints none, got "
                f"authorised_subject={self.authorised_subject!r} (ADR-0193 §6)"
            )
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
    egress_binding: EgressBinding | CoverageUnrecordedBinding | OriginUnrecordedBinding | None = (
        Field(
            default=None,
            description=(
                "The binding the ruling was taken over, transcribed verbatim from the "
                "request by :meth:`from_request` and never supplied by a caller "
                "(ADR-0150 §9). ``None`` for every decision about a non-egress call, "
                "and it continues to mean exactly that and nothing else (ADR-0150 §1). "
                "The two unrecorded arms arrive by **one** route only: a store decoding "
                "a row from an epoch that ended — before ADR-0181 §3 added "
                "``planned_with_external_content`` (ADR-0184 §2), or before ADR-0233 §4 "
                "added ``coverage`` (ADR-0233 §14). It is one field still, with that "
                "name and that default; a consumer that must tell the three bindings "
                "apart narrows with ``isinstance``, and no convenience is minted for it."
            ),
        )
    )
    effect: DurableIdentifier | None = Field(
        default=None,
        description=(
            "The id of the :class:`ActivationEffect` a phases call is claimed under "
            "(ADR-0306 §5:8, §6). Minted before the ruling and supplied by the recorder "
            "through :meth:`from_request`, like ``id``; set on every decision about a call "
            "that gets an effect record, and ``None`` on every other decision. "
            ":meth:`authorises` does not compare it."
        ),
    )

    @classmethod
    def from_request(  # noqa: PLR0913 — the ADR-0059 §1 signature: recorder-supplied id, decided_at, resolves, expires_at, and ADR-0306 §6's effect
        cls,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        id: Identifier,  # noqa: A002 — names the field it fills; the ADR fixes the signature
        decided_at: datetime,
        resolves: Identifier | None = None,
        expires_at: datetime | None = None,
        effect: Identifier | None = None,
    ) -> PermissionDecision:
        """Bind a ruling to the request it was made about.

        **The only construction path a caller should use**, and it exists so the
        binding is *transcribed* rather than asserted. Every field describing
        what was ruled on — ``tool``, ``parameters_digest`` and the egress binding
        — is copied from the request by ``core``, so a decision
        naming a different tool than the one the policy saw cannot be produced by
        following the contract.

        A factory rather than a validator because the request is not a field of
        the decision: embedding it whole would store the parameters this design
        is careful not to store. What remains open is a caller hand-constructing
        a decision field by field — that is a caller falsifying its own audit
        trail rather than a policy subverting a gate, and no producer can
        prevent it (the boundary ADR-0018 §3 drew for detachment).

        **The tool, the ruling and the egress binding are deep-copied, which is
        what makes "by value" true rather than nominal.** Pydantic passes an
        already-valid model instance through without copying it, so the decision
        would otherwise hold the *same* ``ToolDefinition`` object the request
        does — and ``object.__setattr__(request.tool, "risk_level", CRITICAL)``
        would then rewrite what the policy is recorded as having approved, while
        ``authorises`` went on answering ``True`` because both sides moved
        together. Copying here is the same discipline ADR-0018 §3 applied to
        registry queries, at the moment the value stops being the caller's and
        becomes the record's.

        **This cannot produce an** :class:`OriginUnrecordedBinding` **and gains no
        route to** (ADR-0184 §4). It transcribes the binding from
        :attr:`ActionRequest.egress_binding`, which stays ``EgressBinding | None``,
        so the origin-unrecorded shape is unreachable from every live path by
        construction rather than by a check — there is no branch here to forget.

        **The binding is a nested model reached the same way, and copying it is
        ADR-0148 §4's third clause enforced rather than restated** (ADR-0150 §9).
        That clause forbids any component from adding to, removing from,
        substituting within or reordering the canonical destination set between
        the ruling and transmission; the binding holds the recipients, so its
        rewrite is precisely what that clause exists to make impossible. It is
        **transcribed, never supplied** — the signature gains no parameter for it
        — so a decision cannot name a binding the policy did not see.

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
            effect: The id of the ``ActivationEffect`` a phases call is claimed
                under, minted before the ruling (ADR-0306 §5:8, §6). Supplied by
                the recorder like ``id``, because the record is acting's and not a
                fact the policy authored. ``None`` for a call that gets no effect
                record, and for every call of the old path.

        Returns:
            The decision, ready to record.
        """
        binding = request.egress_binding
        return cls(
            id=id,
            ruling=ruling.model_copy(deep=True),
            tool=request.tool.model_copy(deep=True),
            parameters_digest=request.parameters_digest,
            decided_at=decided_at,
            resolves=resolves,
            expires_at=expires_at,
            egress_binding=None if binding is None else binding.model_copy(deep=True),
            effect=effect,
        )

    @classmethod
    def from_confirmation(
        cls,
        confirmed: PermissionDecision,
        ruling: PermissionRuling,
        *,
        id: DurableIdentifier,  # noqa: A002 — names the field it fills; ADR-0235 §4's signature
        decided_at: UtcInstant,
    ) -> PermissionDecision:
        """Bind ``ruling`` to a recorded ``CONFIRM`` no park holds (ADR-0235 §4).

        **A pure transcribing constructor**, and it is :meth:`from_request`'s shape
        for the same reason: everything describing *what was ruled on* is copied by
        ``core`` rather than asserted by whoever collected the act. It reads no
        clock, no store and no seam, and performs no I/O.

        It exists because the resuming constructor needs a request no trail row can
        supply. :meth:`from_request` transcribes ``tool`` and ``parameters_digest`` from
        an :class:`ActionRequest`, which carries the call's ``parameters``; a recorded
        decision carries a ``parameters_digest`` and nothing to rebuild them from, so a
        caller holding a trail row and nothing else has no route through that
        constructor (ADR-0235 §3).

        **It accepts no ``tool``, no ``parameters_digest``, no ``egress_binding``
        and no ``resolves`` from its caller**, so
        a caller has no parameter through which to substitute a subject or point the
        answer at a different question. That removes the capability rather than
        forbidding it, which is ADR-0021 §3's move and ADR-0193 §2's after it — and
        it is what closes the ``AuditTrail.record`` "answered about a different
        subject" ground *by construction* on the one operation that reaches here
        (ADR-0235 §3).

        **``expires_at`` is set to ``None``**, which is the only value this record's
        existing lifetime validator admits on a decision that is not a ``CONFIRM``:
        a lifetime belongs to an open question, and this decision answers one.

        **It authors no ruling.** The :class:`PermissionRuling` it is handed comes
        from ``ActionPolicy.resolve`` and from nowhere else, so ADR-0021 §3's split
        — only a policy may author a ruling — is untouched. The ruling, the tool and
        the binding are deep-copied for :meth:`from_request`'s reason exactly: an
        already-valid model instance passes through pydantic uncopied, so the
        decision would otherwise hold the *same* objects the confirmation does.

        **It lives on** :class:`PermissionDecision` **and nowhere else** (ADR-0235
        §4). No lane moves it into ``permissions``, ``orchestration`` or
        ``interfaces``, and none adds a second construction path beside it.

        Args:
            confirmed: The recorded ``CONFIRM`` being answered. Its ``tool``,
                ``parameters_digest`` and ``egress_binding`` are transcribed by
                value, and its ``id`` becomes
                this decision's ``resolves``.
            ruling: What the policy said, from ``ActionPolicy.resolve``.
            id: This decision's own id, minted by the caller that records.
            decided_at: When the answer was decided; timezone-aware, and at or after
                ``confirmed``'s own ``decided_at`` — which is the ordering
                ``AuditTrail.record`` enforces between a resolution and the question
                it answers, checked here so a caller does not meet it at the store.

        Returns:
            The resolving decision, ready to record.

        Raises:
            ValueError: If ``confirmed``'s ruling was not a ``CONFIRM``; if
                ``decided_at`` is before ``confirmed.decided_at``; or if the record
                the transcription produces fails any of this model's own validators.
        """
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"a resolving decision answers a recorded CONFIRM; decision "
                f"{confirmed.id!r} ruled {confirmed.ruling.outcome} (ADR-0235 §4)"
            )
            raise ValueError(msg)
        if decided_at < confirmed.decided_at:
            msg = (
                f"a resolution is decided at or after the confirmation it answers, got "
                f"decided_at={decided_at!r} for a confirmation decided at "
                f"{confirmed.decided_at!r} (ADR-0235 §4)"
            )
            raise ValueError(msg)
        binding = confirmed.egress_binding
        return cls(
            id=id,
            ruling=ruling.model_copy(deep=True),
            tool=confirmed.tool.model_copy(deep=True),
            parameters_digest=confirmed.parameters_digest,
            decided_at=decided_at,
            resolves=confirmed.id,
            expires_at=None,
            egress_binding=None if binding is None else binding.model_copy(deep=True),
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

        **No step and no execution is compared** (ADR-0318 §6:1): plan executions
        retired with the old path (ADR-0309 §5), so neither record carries one.

        **``egress_binding`` is compared whole and by value**
        (ADR-0150 §9). Not field by field, not by its derived canonical
        destination set, not by its account, and by nothing weaker than equality
        of the whole value. Comparing the whole value is strictly stronger than
        comparing the set, and the strength is where ADR-0148 §4's third clause is
        cashed: comparing occurrences refuses adding to, removing from,
        substituting within and reordering the set *and* refuses a change of
        supplied form that leaves the canonical set identical — the alias case
        moving from ``Alice@Example.com`` to ``alice@example.com`` after the user
        approved the first. ADR-0148 §2's fourth clause requires both forms in the
        record precisely because they are different facts; a comparison that saw
        only the set would record one and bind the other.

        **``planned_with_external_content`` is compared by that same conjunct and
        by nothing added for it** (ADR-0181 §3's fourth clause). It is a member of
        the binding, the comparison is of the whole value, and no lane compares it
        separately, exempts it from the comparison, or re-derives it after the
        ruling: a resumed call whose rebuilt binding disagrees on it is refused
        exactly as one disagreeing on any other member is. That is also why
        ``EgressBinder.rebind`` **transcribes** the field from the approved binding
        (ADR-0181 §3's fifth and sixth clauses) — a ``rebind`` that re-derived it
        would receive no selection set, answer ``False``, and refuse every resumed
        egress call the user was asked about and approved.

        **An** :class:`OriginUnrecordedBinding` **answers** ``False`` **through
        that same conjunct, and nothing was added for it** (ADR-0184 §6). The
        binding is compared whole and by value; pydantic's equality is per class,
        so a model of that class never equals an :class:`EgressBinding` whatever
        its members hold, and ``None`` equals neither. Two independent grounds
        meet at the same answer and it is worth stating rather than economising
        on: a request can never carry that class at all
        (:attr:`ActionRequest.egress_binding` stays narrow), so a future lane that
        changed the comparison would have to break both to make such a decision
        authorise anything. No lane compares the binding's members separately or
        exempts any of them.

        The conjunct is ``None``-safe in **both** directions and neither is an
        exemption. Only one of the two is obvious: a request with a binding
        meeting a decision without one is plainly a mismatch, while the reverse —
        a decision recorded for an egress call offered a request with no binding —
        is the substitution that would let an approval for a described, destined
        send authorise a call that describes and destines nothing. ``None ==
        None`` is ``True``, so every request and decision in the tree today
        compares exactly as it did before this conjunct existed.

        **``effect`` is not compared** (ADR-0306 §6). It names acting's record of the
        call, which the recorder mints and the request never carries, so it says
        nothing about which request was ruled on.
        """
        return (
            self.ruling.outcome is PermissionOutcome.ALLOW
            and request.tool == self.tool
            and request.parameters_digest == self.parameters_digest
            and request.egress_binding == self.egress_binding
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


# --- permissions: what the user granted a source, and what they withdrew -----
# ADR-0004 §7 charters `permissions/` for two things — "Access to Tier 0/1 data
# **and** every side-effecting tool call" — and only the second was ever built.
# These two types are the first half arriving (ADR-0097). They govern *reading*,
# which `VISION.md` keeps governed separately from acting rather than collapsed
# into one notion of "integration"; nothing here touches `ActionPolicy`,
# `ActionRequest`, `PermissionRuling` or `PermissionDecision` (ADR-0097 §3).


class GrantScope(StrEnum):
    """A use of a source that a grant authorises (ADR-0097 §2, ADR-0133 §1).

    **Two members, and none is speculative.** The axis is ADR-0093 §3's,
    promoted to something the user can answer — one scope per consumer of a
    reading — and each member is a sentence a person actually means. ``INGEST``
    writes durable beliefs that outlive the turn and reach ``export``; ``NOTIFY``
    is reading the source so that a producer may conclude a
    :class:`NotificationCandidate` about what it read (ADR-0133 §1), which for a
    kept candidate is a durable, exportable record proposing to tell the user
    something they did not ask for (ADR-0130 §1, §7, §8).

    **``facet`` left** (ADR-0318 §6:2): no read is gated on it since the request
    path's facets left, so a grant naming it promised a use nothing honours. A new
    grant names ``NOTIFY`` alone, ``INGEST`` staying for the grants that name it
    (ADR-0294 §4:4). Its removal is a recorded exception to *added to and never
    renamed*: the data directory is fresh, so nothing stored names it (§5:5).

    **ADR-0133 partially supersedes ADR-0097 §2 — its enumeration of the uses,
    and nothing else of it.** This docstring used to say "exactly two members",
    justifying the pair as "the only scope distinction the ratified surfaces can
    honour today"; a notification surface exists now, so that rationale's own
    condition has fired. Everything §2 keeps governs every member alike: a use a
    grant does not name is not authorised by it, a scope is non-empty, and a
    revocation revokes a grant whole.

    **No member implies, ranks or subsumes another** (ADR-0133 §2). A scope names
    any non-empty subset of the members and authorises exactly the uses it names;
    nothing may infer one from another. ``NOTIFY`` in particular authorises a
    **read** and no contact, disposition, delivery or channel — it names the use
    a reading is put to, exactly as ``INGEST`` authorises *proposing* beliefs
    that a memory policy may still reject. A source grant is not an action
    authorisation (ADR-0097 §7), and a third member does not make it one.

    **Not ordered**, and that is a decision rather than an omission (ADR-0097
    §10). :class:`PermissionOutcome` is a :class:`_SeverityScale` because outcomes
    are *ranked* by severity and that scale combines them; uses of a source are
    not comparable, and an order would invite a ``max()`` that means nothing —
    which ADR-0133 §2 holds at three, since "a third use is not more comparable
    than the second was". So this is a plain ``StrEnum``, :class:`DataTier`'s
    shape. Where a canonical order over the members is needed —
    :attr:`SourceGrant.scope`, so two implementations serialise one grant
    identically — it is **declaration** order, read off the declaration rather
    than off the member values. That order is a serialisation convention and
    **not a rank**: nothing may read a precedence, a severity or an authority
    relation off it (ADR-0133 §2).

    **Content-level scope is deliberately absent** — which entries, which fields,
    which of several calendars. Nothing today can express a sub-source selector:
    ADR-0093 §7 configures exactly one source with no registry, and ADR-0096 §6
    gives the calendar facet three scalars. A member enumerating entry kinds would
    be a schema with no reader on either side of it, so ADR-0097 §12 defers it
    with the condition that fires it, to land as an optional field under ADR-0008
    §1's additive pattern. ADR-0133 §7 leaves that deferral unnarrowed: a third
    *use* is not a step toward a sub-source selector.
    """

    INGEST = "ingest"
    NOTIFY = "notify"


#: Grant scopes ranked by declaration, for the reason ``_TIER_ORDER`` exists on
#: :class:`DataTier`: ``sorted`` on the raw members orders by *string value*,
#: which is only coincidentally declaration order today and stops being so the
#: moment a member is added out of alphabetical sequence. One convention in
#: ``core`` for "declaration order", rather than two spellings that can disagree.
_SCOPE_ORDER: Mapping[GrantScope, int] = {use: index for index, use in enumerate(GrantScope)}


def _grant_scope(value: tuple[GrantScope, ...]) -> tuple[GrantScope, ...]:
    """Refuse an empty or duplicated scope, and put the rest in declaration order.

    The three properties ADR-0097 §10 fixes on :attr:`SourceGrant.scope`, and the
    two halves are deliberately different kinds of rule:

    * **Empty is refused.** A grant naming no use authorises nothing and would
      still *read* as a grant — and worse, it would occupy ADR-0097 §4's
      one-live-grant-per-source slot, so the real grant could not be recorded
      until it was revoked. ADR-0097 §2 refuses it at construction for that
      reason.
    * **A repeated member is refused**, not silently folded away. ``(NOTIFY,
      NOTIFY)`` is a caller that has lost track of what it is asking for, and
      ADR-0097 §10 spells the outcome as a refusal.
    * **Order is normalised** rather than refused. ADR-0097 §10 gives one reason
      for the ordering — "so two implementations serialise one grant
      identically", under ADR-0087's canonical wire encoding, which is why the
      field is a tuple and not a ``frozenset`` — and normalising delivers that
      reason for every caller instead of only for the ones that already sorted.
      §10 enumerates the refusals it wants (empty, duplicated) and does not
      enumerate this one.

    Args:
        value: The uses as the caller supplied them.

    Returns:
        The same uses, in declaration order.

    Raises:
        ValueError: If ``value`` is empty or names a use twice.
    """
    if not value:
        msg = (
            "a grant's scope must name at least one use: a grant authorising "
            "nothing still reads as a grant, and still occupies the source's one "
            "live-grant slot (ADR-0097 §2)"
        )
        raise ValueError(msg)
    if len(set(value)) != len(value):
        msg = f"a grant's scope names each use at most once, got {value!r} (ADR-0097 §10)"
        raise ValueError(msg)
    return tuple(sorted(value, key=lambda use: _SCOPE_ORDER[use]))


class SourceGrant(BaseModel):
    """One recorded user act about one source — a grant, or its revocation (ADR-0097 §1).

    The record a :class:`~ai_assistant.core.protocols.SourceGrantStore` appends
    and a :class:`~ai_assistant.core.protocols.SourceGrants` answers with. A
    grant says the user connected a source and named what may be read from it; a
    revocation is a **second record** naming the first, never a mutation of it,
    which is what keeps the store's history equal to what actually happened
    (ADR-0097 §4).

    **One type for both acts**, on :attr:`PermissionDecision.resolves`'s shape and
    for its reason: it keeps the store's rows homogeneous and its wire encoding
    undiscriminated, where a separate ``GrantRevocation`` would make every query
    return a union ADR-0096 §5 would then require to be explicitly discriminated
    on the wire (ADR-0097 §10).

    **A revoking record transcribes what it withdraws.** It carries the
    :attr:`source` and :attr:`scope` of the grant it revokes, verbatim, so the
    record says what was withdrawn without a join — ADR-0021 §1's reason for
    embedding a whole declaration rather than a name. The store verifies the
    transcription; nothing here can, because a record in isolation cannot see the
    record it names (ADR-0097 §4).

    **Frozen and boundary-crossing** (ADR-0068). ``frozen=True`` refuses
    ``grant.scope = …`` and does *not* refuse ``grant.__dict__["scope"] = …``,
    which is why the store's obligation is a detached, validated snapshot on both
    the read and the write path rather than a reliance on this config.

    **A grant is keyed to a source, and to nothing else.** Not to a user — there
    is no user identity anywhere in this system (ADR-0036 §3, #113) — and not to a
    belief: ADR-0097 §1 rules that no belief carries the id of the grant that
    authorised the read that produced it, and the resolvable relation is belief →
    source → that source's grant history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier = Field(
        description=(
            "This record's own id, minted by the caller that records it, as "
            ":attr:`PermissionDecision.id` is — a store neither mints ids nor "
            "reads a clock (ADR-0021 §3)."
        )
    )
    source: Identifier = Field(
        description=(
            "The reader's declared identity — the value "
            ":attr:`~ai_assistant.core.protocols.Reader.name` returns, which "
            ":attr:`SourceReading.source` equals and which reaches a stored belief "
            "as :attr:`Attestation.reported_by` (ADR-0097 §1). It is **Tier 2 / "
            "operational** and must stay that way: this record is rendered to the "
            "user, kept forever, and survives into ``export``, so a path, "
            "filename, address or account identifier may never be used as one "
            "(ADR-0093 §7). :data:`Identifier` refuses only a blank string, so "
            "that rule is held where it can be — the grant surface admits a "
            "``source`` only when it equals the ``name`` of a ``Reader`` the hub "
            "actually holds, which makes the admissible set the set of declared "
            "constants (ADR-0097 §9)."
        )
    )
    scope: Annotated[tuple[GrantScope, ...], AfterValidator(_grant_scope)] = Field(
        description=(
            "The uses this record authorises, or — on a revoking record — the "
            "uses the grant it revokes authorised, transcribed verbatim. "
            "Non-empty, without duplicates, and in declaration order (see "
            ":func:`_grant_scope`). A tuple rather than a ``frozenset`` because "
            "ADR-0087 fixes a canonical wire encoding and a set has no canonical "
            "order. A use this does not name is not authorised by it "
            "(ADR-0097 §2)."
        )
    )
    decided_at: UtcInstant = Field(
        description=(
            "When the user decided; timezone-aware, stored as UTC. Naive is "
            "refused for :attr:`PermissionDecision.decided_at`'s reason — the "
            "store is durable *and* ordered. It is **not** an ordering invariant "
            "between records: ADR-0097 §4 derives liveness from ``revokes`` alone "
            "and never refuses a revocation for its timestamp, including one that "
            "predates the grant it revokes."
        )
    )
    revokes: DurableIdentifier | None = Field(
        default=None,
        description=(
            "The grant this record revokes; ``None`` on a granting record. "
            ":attr:`PermissionDecision.resolves`'s shape, chosen for its reason. "
            "A revocation revokes a grant **whole** — there is no partial "
            "revocation and no in-place narrowing, and changing a grant's scope is "
            "a revocation followed by a new grant, both kept (ADR-0097 §2)."
        ),
    )


def _canonical_destination_tuple(
    value: tuple[CanonicalDestination, ...],
) -> tuple[CanonicalDestination, ...]:
    """Require ADR-0193 §1's non-empty, duplicate-free, canonically ordered set.

    **Two records take this rule, through this one function.**
    :attr:`RecipientGrant.destinations` is the first;
    :attr:`DestinationTrustRecord.destinations` is the second, and ADR-0238 §1 says
    in terms that it takes "ADR-0193 §1's canonical destination tuple, **by the same
    validator and not a second one**". The messages below therefore name the *set*
    rather than either record: a second copy of this function, or a second wording of
    its rule, would be exactly the drift the paragraph after this one is about.

    The order is not this ADR's invention: it is the total order
    :attr:`EgressBinding.canonical_destination_set` already produces — account
    members first, then selected recipients by ``protocol`` and then by
    ``canonical`` form, every string compared by Unicode code point
    (:func:`_destination_order`). Pinning one spelling **at construction** is what
    lets three separate rules stated over *identity* — the store's duplicate
    refusal, ``AuditTrail.record``'s subject match, and
    :attr:`RecipientGrant.subject_digest` — each be written as tuple equality and
    each mean set equality. Stating the duplicate rule over membership instead
    was the other available repair and is the weaker one: it leaves all three
    free to drift back into tuple equality without a test noticing, where this
    fixes them at once.

    **It costs an honest caller nothing**, because the value a grant is built
    from is already in that order: ADR-0193 §2 admits one construction path and
    it takes ``destinations`` from the confirmed decision's binding's derived
    set. What this refuses is a hand-built tuple, and ``(Bob, Alice)`` is the
    case the rule is about — it covers exactly the calls ``(Alice, Bob)`` does,
    so a duplicate refusal over ordinary tuple equality would admit both, and
    revoking one would leave the other standing.

    **The order check runs first and the duplicate check reads adjacency**, which
    is sound because :func:`_destination_order`'s key is injective over
    well-formed members: two members sharing a key are equal, so duplicates are
    adjacent in any canonically ordered tuple.

    Raises:
        ValueError: If the tuple is empty, carries a duplicate, or is in any
            order but the canonical one.
    """
    if not value:
        msg = "a recorded act names at least one canonical destination (ADR-0193 §1)"
        raise ValueError(msg)
    if tuple(sorted(value, key=_destination_order)) != value:
        msg = (
            "a recorded act's destinations are held in the one canonical order "
            "EgressBinding.canonical_destination_set produces — account members first, "
            "then selected recipients by protocol and then by canonical form "
            "(ADR-0193 §1)"
        )
        raise ValueError(msg)
    if any(earlier == later for earlier, later in pairwise(value)):
        msg = (
            "a recorded act names each canonical destination once; a duplicate is a "
            "second spelling of one authorisation (ADR-0193 §1)"
        )
        raise ValueError(msg)
    return value


class RecipientGrant(BaseModel):
    """One recorded user act about one canonical destination set (ADR-0193 §1).

    A **standing recipient grant**, or the revocation of one: the record a
    :class:`~ai_assistant.core.protocols.RecipientGrantStore` appends, a
    :class:`~ai_assistant.core.protocols.RecipientGrants` answers with, and a
    :class:`~ai_assistant.core.protocols.RecipientGrantResolution` resolves. It
    says the user answered a confirmation about an egress call and asked, in the
    same act, that that call's recipients be remembered until a stated instant.

    **It authorises the recipient and never the payload** (ADR-0193 §3, §5). A
    grant does not widen ``discloses``, does not raise or lower any ceiling
    ADR-0016 §3 states, does not satisfy ADR-0148 §8's floor about the payload
    description, and does not exempt a call from any other floor a policy owes.
    Its only effect on an outcome is to discharge the recipient-authorisation
    ground of ADR-0148 §3's first clause for a request it covers wholly.

    **One type for both acts**, on :class:`SourceGrant`'s shape and for its
    reason: it keeps the store's rows homogeneous and its wire encoding
    undiscriminated. A revoking record transcribes verbatim every field of the
    grant it withdraws except ``id``, ``decided_at``, ``established_by`` and
    ``revokes``; the store verifies the transcription, because a record in
    isolation cannot see the record it names.

    **The declaration is embedded by value rather than named by id**, which is
    ADR-0021 §1's ruling applied to a record that outlives the call. An id can be
    rebound (#54), and a standing grant is exposed to that hazard for as long as
    it is live rather than for one invocation — so a grant keyed on ``tool_id``
    would be strictly worse than a decision keyed the same way. The cost is
    accepted in the safe direction: because coverage compares the declaration by
    value, any edit to a registered declaration — including one that only rewords
    a description — leaves every grant established about the previous declaration
    covering nothing, and the user is asked again.

    **The account is compared because a destination set alone is a key with a
    duplicate.** :class:`BoundAccount` says so in terms: two connectable records
    can hold one identity, so "a standing grant would cover a record the user
    never granted". A grant over ``alice@example.com`` established against the
    user's work account does not cover a send to the same address through a
    personal one.

    **No credential value and no payload**, here or anywhere in this surface, and
    the field list is closed: ADR-0193 §1 states the record's members exactly, and
    a lane adding one is changing that decision rather than implementing it.

    **Frozen and boundary-crossing** (ADR-0068). ``frozen=True`` refuses
    ``grant.destinations = …`` and does *not* refuse
    ``grant.__dict__["destinations"] = …``, which is why the store's obligation is
    a detached, validated snapshot on both the read and the write path rather
    than a reliance on this config.

    **Two non-field members and a lane adds no third** (ADR-0193 §1):
    :attr:`subject_digest`, derived, and :meth:`established_from`, the
    establishing act's one construction path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier = Field(
        description=(
            "This record's own id, minted by the caller that records it, as "
            ":attr:`PermissionDecision.id` and :attr:`SourceGrant.id` are — a "
            "store neither mints ids nor reads a clock (ADR-0021 §3)."
        )
    )
    tool: ToolDefinition = Field(
        description=(
            "The declaration this grant was established about, verbatim and by "
            "value (ADR-0021 §1's rule on a record that outlives the call). "
            "Coverage compares it whole, so a declaration edit re-prompts rather "
            "than silently widening what the user authorised (ADR-0193 §1, §3)."
        )
    )
    account: BoundAccount = Field(
        description=(
            "The connected account this grant was established against, by value "
            "— **both** facts, identity and connection reference, never one "
            "(ADR-0148 §6, ADR-0193 §3)."
        )
    )
    destinations: Annotated[
        tuple[CanonicalDestination, ...], AfterValidator(_canonical_destination_tuple)
    ] = Field(
        description=(
            "The canonical destination set this record names, or — on a revoking "
            "record — the set the grant it revokes named, transcribed verbatim. "
            "Non-empty, duplicate-free, and in the one canonical order "
            ":attr:`EgressBinding.canonical_destination_set` produces (see "
            ":func:`_canonical_destination_tuple`). Coverage is **set membership** "
            "and is not restated over the order (ADR-0193 §1, §3)."
        )
    )
    decided_at: UtcInstant = Field(
        description=(
            "When the user decided; timezone-aware, stored as UTC. On a granting "
            "record it is the instant the answering decision carries, read off a "
            "recorded decision rather than supplied (ADR-0193 §2). Naive is "
            "refused for :attr:`PermissionDecision.decided_at`'s reason — the "
            "store is durable *and* ordered."
        )
    )
    expires_at: UtcInstant = Field(
        description=(
            "The instant this grant ceases to be live. **Required, with no "
            "unbounded spelling** — no null, no sentinel, no 'forever' — and the "
            "user chooses it in the establishing act (ADR-0193 §9). On a granting "
            "record it is **strictly after** ``decided_at``; a revoking record is "
            "unaffected, because it is never live and its instants are ordered by "
            "no rule."
        )
    )
    established_by: DurableIdentifier | None = Field(
        default=None,
        description=(
            "The recorded ``CONFIRM`` decision the establishing act rode, by id. "
            "Set on a granting record and unset on a revoking one, refused either "
            "way round. It is a **pointer into the audit trail** this store "
            "validates against nothing and nothing ever re-resolves; what it is "
            "for is the digest, and the digest is a comparison between two records "
            "rather than a resolution of either (ADR-0193 §1)."
        ),
    )
    revokes: DurableIdentifier | None = Field(
        default=None,
        description=(
            "The grant this record revokes; ``None`` on a granting record. "
            ":attr:`SourceGrant.revokes`'s shape, chosen for its reason. "
            "Revocation is **whole** — there is no partial revocation and no "
            "in-place narrowing, and changing what a user has authorised is a "
            "revocation followed by a new grant, both kept (ADR-0193 §1, §9)."
        ),
    )

    @model_validator(mode="after")
    def _the_establishing_act_is_named_on_a_granting_record(self) -> RecipientGrant:
        """Require ``established_by`` on a granting record and refuse it on a revoking one.

        A granting record without it names no act; a revoking record with it
        claims an establishment it is not (ADR-0193 §1). The two are one rule
        because they are one field's meaning, and stating it here is what makes a
        grant say **which** user act made it rather than merely that one did.

        Raises:
            ValueError: If the pairing does not hold.
        """
        if self.revokes is None and self.established_by is None:
            msg = (
                "a granting recipient grant names the recorded CONFIRM its establishing act "
                "rode, in established_by (ADR-0193 §1)"
            )
            raise ValueError(msg)
        if self.revokes is not None and self.established_by is not None:
            msg = (
                "a revoking recipient grant establishes nothing, so it names no act: "
                f"established_by={self.established_by!r} (ADR-0193 §1)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _a_granting_record_is_live_for_some_duration(self) -> RecipientGrant:
        """Require ``expires_at`` strictly after ``decided_at`` on a granting record.

        A record expiring at or before the instant it was decided is never live
        for any duration, so it authorises nothing while still occupying an
        outstanding slot against the store's count ceiling and blocking an
        identical new grant until the user performs a revocation they had no
        reason to expect. It is a grant in shape and nothing in effect, and
        refusing it here is cheaper than every clause that would otherwise have to
        tolerate it (ADR-0193 §9).

        **A revoking record is unaffected**, at any ordering, including an
        ``expires_at`` transcribed from a grant that has since expired: it is
        never live, and ADR-0193 §1 orders its instants by no rule.

        Raises:
            ValueError: If a granting record's ``expires_at`` is at or before its
                ``decided_at``.
        """
        if self.revokes is None and self.expires_at <= self.decided_at:
            msg = (
                "a granting recipient grant expires strictly after it was decided; "
                "one that does not is live for no duration (ADR-0193 §9)"
            )
            raise ValueError(msg)
        return self

    @property
    def subject_digest(self) -> Sha256Hex:
        """A fingerprint of this record under one schema (ADR-0193 §1, §6).

        SHA-256 over :func:`_canonical_bytes`' ADR-0021 §1 encoding of this
        record's own JSON-mode field state — taken by this class's serializer,
        never through ``self.model_dump`` (:meth:`_digest_projection`) — with
        **exactly one key removed**, ``id``. Every other field is in it, and a field added to
        :class:`RecipientGrant` by a later ADR is in it too unless that ADR
        removes it by name.

        **The rule is a removal from the whole dump rather than a list of
        members**, and an implementation that hand-wrote the list has not
        implemented it: a list goes stale silently the first time a field is
        added, and a removal cannot. ``tests/core`` pins the roster off
        ``model_fields`` so a field added later without deciding its place is a
        red test rather than a silent exclusion.

        **``id`` is the one removal**, because the digest exists to be checked
        *against* an id: a fingerprint that included its own pointer would match
        only where the pointer already matched, which is the comparison it is
        meant to be independent of.

        **A property and never a stored field**, for the reason
        :attr:`EgressBinding.canonical_destination_set` is one: a stored digest
        can be read back disagreeing with the fields it was computed from, and
        nothing downstream would catch it. It reads no clock, no store and no
        seam; it is total and never raises.

        **What it is for, stated at the strength the evidence carries**
        (ADR-0193 §6). A route-(b) ``ALLOW`` carries this value in
        :attr:`PermissionRuling.authorised_subject`, so a pointer whose id was
        recycled after a ``clear`` resolves to a record that fails the
        comparison. The guarantee is **one-directional**: a mismatch is
        conclusive — this record is not the one the row rested on — and a match
        establishes only that this record agrees with the row in every field a
        grant carries but its ``id``. The report for a match is *consistent*,
        never "verified" or "proven".

        **And it is a fingerprint under one record schema.** This is computed
        under the field set of :class:`RecipientGrant` and of every value it
        embeds as they stand when it is computed; no scheme is fixed here for
        comparing across a change to that field set. A check that cannot
        establish that both sides stand under one schema reports **not
        comparable** and never "mismatch".
        """
        return sha256(_canonical_bytes(self._digest_projection())).hexdigest()

    def _digest_projection(self) -> dict[str, Any]:
        """The canonical projection :attr:`subject_digest` digests.

        Built from ``model_dump(mode="json")`` rather than from the live objects,
        so a record reconstructed from a serialised form projects identically to
        the one it was serialised from — the parity :attr:`subject_digest`'s whole
        use depends on, since the two sides of the comparison are a decision read
        back out of a trail and a grant read back out of a store.

        The removal is by ``pop`` over the whole dump rather than by rebuilding
        from a list, which is ADR-0193 §1's clause as code: there is no inventory
        here for a later field to be missing from.

        **Serialised by this class's own serializer, never through
        ``self.model_dump``.** That method is an ordinary attribute: a subclass can
        override it and an instance can shadow it through ``__dict__``, and either
        can return a valid-but-false mapping. This digest is the value ADR-0193 §6
        has ``AuditTrail.record`` *recompute* on the grant the resolution seam
        returns, so a record whose dump described a different grant would let a
        route-(b) row rest on a subject the record does not carry — the one check
        that comparison exists to be. ``ai_assistant.orchestration.executor`` and
        the trail's own ``field_state`` state the same reasoning about the same
        method; the serializer is resolved on the class, reads the instance's field
        values, and consults no instance attribute.

        ``RecipientGrant``'s serializer and not ``type(self)``'s, which is the
        docstring above as code: the projection is under *this* class's field set,
        so a subclass's own fields are outside the schema the digest is taken under
        rather than silently inside it. ``warnings=False`` because serialising a
        subclass through the base's schema warns, and the warning is noise here.
        """
        projection: dict[str, Any] = RecipientGrant.__pydantic_serializer__.to_python(
            self, mode="json", warnings=False
        )
        projection.pop("id")
        return projection

    @classmethod
    def established_from(
        cls,
        confirmed: PermissionDecision,
        answer: PermissionDecision,
        *,
        id: DurableIdentifier,  # noqa: A002 — names the field it fills; ADR-0193 §1's signature
        expires_at: UtcInstant,
    ) -> RecipientGrant:
        """Build the grant a user's answer to ``confirmed`` establishes (ADR-0193 §2).

        **The one construction path**, and the only thing that creates a
        :class:`RecipientGrant`: a user answering a recorded ``CONFIRM`` about an
        egress call and, in the same act, asking that that call's recipients be
        remembered. Every surface that offers the act obtains its grant from here
        and **mints none of its own** — it builds no record field by field and
        passes no granting record to a store that this function did not return.
        That is ADR-0152 §5's discipline (the seam derives the binding whole and
        accepts no part of it) read on this act rather than on a binding.

        **A pure function**: it reads no clock, no store and no seam, and performs
        no I/O. It is :meth:`PermissionDecision.from_request`'s shape for the same
        reason — the subject is **transcribed by** ``core`` rather than asserted
        by whoever collected the act.

        **It accepts no ``tool``, no ``account``, no ``destinations``, no
        ``established_by`` and no ``decided_at`` from its caller**, so a surface
        has no parameter through which to substitute a subject, stamp an invented
        act, or backdate one. That removes the capability rather than forbidding
        it, which is the move ADR-0021 §3 made when it split
        :class:`PermissionRuling` off :class:`PermissionDecision`.

        **Nothing is typed, parsed, canonicalised or reordered here.**
        ``destinations`` is ``confirmed``'s binding's own derived
        ``canonical_destination_set``, which ``core`` already returns in the one
        canonical order, so the value reaches
        :func:`_canonical_destination_tuple` already sorted and no sort runs
        inside this function. A surface that rebuilt the tuple in the order it
        happened to render it in would be minting a grant this record's own
        validator refuses.

        **The answer is recorded before the grant is**, and that is an obligation
        on the caller rather than something checked here: a pure function is
        handed a record and cannot ask a trail whether the record is there. What
        it *can* check, and does, is that ``answer`` resolves **this**
        confirmation with an ``ALLOW`` — so an unanswered ``CONFIRM`` on its own
        no longer reaches the constructor.

        **It raises ``ValueError`` rather than the store's refusal class**, and
        the reason is a boundary rather than a taste: ``core.errors`` imports
        ``core.types`` at module scope, so this type cannot raise
        ``InvalidRecipientGrantError`` without a deferred import, and every other
        refusal a :class:`RecipientGrant` states is a construction refusal of
        exactly this kind. ``InvalidRecipientGrantError`` stays what ADR-0193 §1
        says it is: the store's refusal at ``record``.

        **A refusal mints nothing looser in its place** — not a grant over the
        supplied form, not one over the account, not one over a subset. This is
        the discipline #1548 records OpenClaw stating for a different binding:
        refuse to mint an approval-backed run rather than pretend full coverage.

        Args:
            confirmed: The recorded ``CONFIRM`` the user was asked. Its ``tool``,
                its binding's ``account`` and that binding's derived canonical
                destination set are transcribed by value and unchanged, and its
                ``id`` becomes the grant's ``established_by``.
            answer: The recorded resolving ``ALLOW`` that records the user's
                answer to ``confirmed``. Its ``decided_at`` — the instant the user
                decided — becomes the grant's, and nothing else is read from it.
            id: The grant's own id, minted by the caller that records.
            expires_at: The instant the user chose, past which the grant is no
                longer live. Strictly after ``decided_at``, checked at
                construction (ADR-0193 §9).

        Returns:
            The grant, ready to record.

        Raises:
            ValueError: If ``confirmed``'s ruling was not a ``CONFIRM``; if
                ``answer``'s ruling is not an ``ALLOW``; if ``answer``'s
                ``resolves`` is unset or is not ``confirmed``'s ``id``; if
                ``confirmed`` carries no ``egress_binding``; if that binding is an
                :class:`OriginUnrecordedBinding`; if it carries
                ``planned_with_external_content``; or if the record the
                transcription produces fails any of this model's own validators.
        """
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"a recipient grant rides an answer to a recorded CONFIRM; decision "
                f"{confirmed.id!r} ruled {confirmed.ruling.outcome} (ADR-0193 §2)"
            )
            raise ValueError(msg)
        if answer.ruling.outcome is not PermissionOutcome.ALLOW:
            msg = (
                f"a recipient grant rides an approving answer; decision {answer.id!r} "
                f"ruled {answer.ruling.outcome} (ADR-0193 §2)"
            )
            raise ValueError(msg)
        if answer.resolves != confirmed.id:
            msg = (
                f"decision {answer.id!r} resolves {answer.resolves!r}, not the confirmation "
                f"{confirmed.id!r} this grant would be established from; an unanswered CONFIRM "
                f"establishes nothing (ADR-0193 §2)"
            )
            raise ValueError(msg)
        binding = confirmed.egress_binding
        if binding is None:
            msg = (
                f"decision {confirmed.id!r} records no egress call, so it names no account and "
                f"no destination set to transcribe (ADR-0193 §2)"
            )
            raise ValueError(msg)
        if isinstance(binding, OriginUnrecordedBinding):
            msg = (
                f"decision {confirmed.id!r} records an egress call whose origin was never "
                f"recorded; a user answering such a confirmation may approve the call, and may "
                f"not make its recipients standing (ADR-0193 §2)"
            )
            raise ValueError(msg)
        if binding.planned_with_external_content:
            msg = (
                f"decision {confirmed.id!r} records a call planned over external content; a user "
                f"answering such a confirmation may approve the call, and may not make its "
                f"recipients standing (ADR-0193 §2, §4)"
            )
            raise ValueError(msg)
        return cls(
            id=id,
            tool=confirmed.tool.model_copy(deep=True),
            account=binding.account.model_copy(deep=True),
            destinations=tuple(
                member.model_copy(deep=True) for member in binding.canonical_destination_set
            ),
            decided_at=answer.decided_at,
            expires_at=expires_at,
            established_by=confirmed.id,
        )


# --- destination trust: what the user said about a destination (ADR-0238 §1) --
# The **mirror** of the source side #2096 records. That note keeps one fact per
# *source* — who may write here — and this is the same rule read on the other axis:
# who the user picked to be told about. One rule, two milestones — milestone 31's
# provider and milestone 32's returned site are two values of it rather than two
# boundaries.


class DestinationTrust(StrEnum):
    """Whether the user picked this destination by name (ADR-0238 §1).

    **Closed at exactly two members**, and the vocabulary is *added to and never
    renamed*: no implementation and no later ADR adds a third without the ADR that
    decides it. That is :class:`DestinationProtocol`'s discipline (ADR-0150) applied
    to the fact rather than to the protocol.

    **Two values and not three, unlike the source side** (§1). The source set is
    three-valued because policy there needs two boundaries — a value may fill an
    unbounded blank alone, only inside a confirmed flow, or only under a per-call
    confirmation. The destination side needs one boundary, because the question is
    binary at every seam this corpus has: either the user picked this party or
    nobody did. A third member would be a guess about a mechanism no ADR has
    designed, and the enumeration is extended by ADR precisely so that a later
    milestone may add one *when it has a policy that reads it*.

    **Never inferred, and absence is not an inference** (§1). Reading a total
    function over a partial store is not inference in ADR-0098 §1's sense; inference
    is deciding a fact by inspecting content. Nothing here inspects anything: a
    record either exists and is live, or it does not.
    """

    USER_CHOSEN = "user_chosen"
    """The user picked this destination by name and said it may be told about them.

    Set by a **recorded act of the user and by nothing else** (§1). No
    configuration sets it, no connected account sets it, no operator setting sets
    it, no tool declaration sets it, no :class:`RecipientGrant` sets it, and **no
    model output ever sets it, raises it, or is consulted about it**."""

    UNCHOSEN = "unchosen"
    """Every other destination, which is what absence means (§1).

    The fail-closed direction, and it covers **more than "no record"**: no record
    exists, a record was revoked, or a record cannot be read. Stated as ADR-0146 §2
    states its own — "a span for which no origin was recorded is
    **system-selected**" — and for the same reason: the permissive default is what
    makes an unimplemented path work, and is therefore precisely the state in which
    the rule would be false.

    **What may be done to an `UNCHOSEN` destination is not decided here.** ADR-0238
    defines the member; milestone 32's bounded fetch is what reads it (§16)."""


class DestinationTrustRecord(BaseModel):
    """One recorded user act about one canonical destination set (ADR-0238 §1).

    The record a :class:`~ai_assistant.core.protocols.DestinationTrustStore` appends.
    It says *the user picked these parties by name and told this system it may be
    told about them* — and it says nothing else.

    **It is not a field on a** :class:`RecipientGrant`, **and two reasons each
    suffice** (§1). A destination nobody chose has no grant to carry a field —
    milestone 32's subject is a site a provider returned, for which no grant exists
    or ever will — so a grant-carried field could not express the value that
    milestone reads. And ADR-0193 §5 is correct and is left standing: "a grant
    states nothing about the payload and authorises no content", so deriving a
    payload permission from a recipient grant would be the shape ADR-0097 §7 refuses
    and ADR-0155 §3 quotes against itself — "the floor satisfied by a consent the
    user gave about something else entirely".

    **The two acts are separate and neither implies the other** (§1). A
    ``RecipientGrant`` authorises *whether this system may talk to this party*; this
    record authorises *what class of payload this system may compose for it*. A
    grant established before this decision, or after it without the second act,
    leaves its destination reading :attr:`DestinationTrust.UNCHOSEN`, and no
    component reads the existence, breadth, age or liveness of a grant as evidence
    of trust.

    **It carries no tool, no account, no payload, no description and no content.**
    It is a fact about a destination set and nothing else, which is what makes it
    readable for a destination no grant covers — the property milestone 32 needs and
    a grant-shaped record could not have.

    **Prospective and revocable**, on ADR-0193 §9's shape (§1): a revocation takes
    effect for every later request and rewrites no recorded decision, and a
    destination whose record is revoked reads ``UNCHOSEN`` from that moment.

    **Frozen and boundary-crossing** (ADR-0068). ``frozen=True`` refuses
    ``record.destinations = …`` and does *not* refuse
    ``record.__dict__["destinations"] = …``, which is why the store's obligation is
    a detached, validated snapshot on both the read and the write path rather than a
    reliance on this config — :class:`RecipientGrant`'s own note, one store over.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier = Field(
        description=(
            "This record's own id, **minted by the caller that constructs the "
            "record**, as :attr:`RecipientGrant.id` is (ADR-0193 §1) — so the record "
            "is a complete value before it reaches any store and the store's refusal "
            "of a duplicate is a comparison rather than an allocation (ADR-0238 §1). "
            "ADR-0238 §1 spells the annotation ``Identifier``; "
            ":data:`DurableIdentifier` **is** that alias, spelled the way this file "
            "spells an id a record keeps."
        )
    )
    destinations: Annotated[
        tuple[CanonicalDestination, ...], AfterValidator(_canonical_destination_tuple)
    ] = Field(
        description=(
            "The canonical destination set this record is over. Non-empty, "
            "duplicate-free, and in the one canonical order "
            ":attr:`EgressBinding.canonical_destination_set` produces — ADR-0193 §1's "
            "rule, **by the same validator and not a second one** (ADR-0238 §1). "
            "**Without it §1's revocation clause is false**: ``(Alice, Bob)`` and "
            "``(Bob, Alice)`` are unequal tuples over one logical set, both would be "
            "admitted as live, and revoking the record the user was shown would leave "
            "the other standing with the destination still reading ``USER_CHOSEN``. "
            ":meth:`~ai_assistant.core.protocols.DestinationTrustStore.trust_of` is "
            "unaffected, its rule being membership rather than order."
        )
    )
    trust: DestinationTrust = Field(
        description=(
            "What the user said. Only :attr:`DestinationTrust.USER_CHOSEN` is "
            "recordable: a record asserting ``UNCHOSEN`` is refused at construction "
            "below (ADR-0238 §1)."
        )
    )
    established_at: UtcInstant = Field(
        description=(
            "The instant of the user's act; timezone-aware, stored as UTC. Naive is "
            "refused for :attr:`RecipientGrant.decided_at`'s reason — the store is "
            "durable *and* ordered."
        )
    )
    revoked_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the user withdrew this record, or ``None`` while it stands. "
            "Revocation is **prospective**: it takes effect for every later read and "
            "rewrites no recorded decision (ADR-0238 §1, on ADR-0193 §9's shape)."
        ),
    )

    @model_validator(mode="after")
    def _an_unchosen_record_is_a_second_spelling_of_nothing(self) -> DestinationTrustRecord:
        """Refuse a record whose ``trust`` is ``UNCHOSEN`` (ADR-0238 §1).

        ``UNCHOSEN`` is what *absence* means, so a record asserting it would be a
        second spelling of nothing — and two spellings of one state is the shape
        ADR-0217 §1's refusal table exists to prevent. Refused here rather than in
        the store, so no producer, decode, test double or later lane can build one.

        Raises:
            ValueError: If ``trust`` is not :attr:`DestinationTrust.USER_CHOSEN`.
        """
        if self.trust is not DestinationTrust.USER_CHOSEN:
            msg = (
                "a destination trust record states what the user chose; UNCHOSEN is what "
                "absence already means, so a record asserting it is a second spelling of "
                "nothing (ADR-0238 §1)"
            )
            raise ValueError(msg)
        return self


class ReadOutcome(StrEnum):
    """How one attempt to read a source ended (ADR-0185 §1).

    **Six members, and they are total over the outcomes the ratified gate can
    produce.** ADR-0097 §5 and ADR-0093 §8 between them decide every way a gated
    read can end, and each member below is pinned to one of those clauses: two are
    decided at the check *before* the read and open nothing, and four follow a call
    to :meth:`~ai_assistant.core.protocols.Reader.read`. No implementation invents
    a seventh, and no attempt is recorded with no outcome.

    **Whether the source was opened is a function of this field and is not
    recorded a second time** (ADR-0185 §1). :attr:`REFUSED` and :attr:`UNANSWERED`
    mean the driver never called ``read()``, so "the source is not resolved, not
    opened and not parsed"; :attr:`COMPLETED`, :attr:`DISCARDED` and
    :attr:`UNCONFIRMED` mean a reading exists, so it was. On :attr:`FAILED` it is
    **not determinable**, and no consumer may infer it in either direction — a
    reader can refuse before starting work at all (``OneWorker``'s outstanding
    reservation: "Nothing is started") or fail with the bytes already in hand, and
    both cross the seam as ``ReaderError`` because ADR-0093 §8 requires it. A
    boolean ``opened`` beside this field was refused for that reason and for
    ADR-0106 §2's: it would be the second spelling of a fact already recorded.

    **Not ordered**, for :class:`GrantScope`'s reason (ADR-0097 §10): six outcomes
    of a read are not ranked, and an order would invite a comparison that means
    nothing. So this is a plain ``StrEnum``, :class:`DataTier`'s shape.

    **The two unanswerable outcomes are separate from their answered twins**
    (ADR-0185 §1). "There was no live grant" and "we could not find out whether
    there was one" are different facts about the user's authorisation, and ADR-0097
    §5 already requires that distinction to survive elsewhere: "A store fault and a
    withdrawn grant are different facts and an operator must be able to tell them
    apart." Folding :attr:`UNANSWERED` into :attr:`REFUSED` would put the claim
    *there was no live grant* into a store whose premise is that its records are
    not fabricated.

    **A cancellation delivered from outside is not a member and never becomes
    one** (ADR-0185 §1). It ends an attempt without an outcome, is delivered onward
    unchanged, and the driver starts no recorder call on that path — this module's
    cancellation clause and ADR-0093 §8's carve-out applied to the recording seam.
    """

    COMPLETED = "completed"
    """The read returned and the re-check confirmed the grant.

    The reading was **admitted** for its use. It claims nothing whatever about the
    use itself — not that the use ran, and not that the reading reached it. ADR-0185
    §5 requires the row to be written *before* the use runs, so an outcome defined
    by the handoff could not be known when the row is written; what the use then did
    is ``MemoryPolicy``'s subject or the facet adapter's, and their own records
    answer it.
    """

    REFUSED = "refused"
    """The first ``live()`` answered ``None``, so nothing was opened (ADR-0097 §5)."""

    UNANSWERED = "unanswered"
    """The first ``live()`` raised ``GrantError``, so the driver failed closed.

    The read was not attempted: the driver could not tell whether a grant existed
    (ADR-0097 §5). Nothing was opened.
    """

    FAILED = "failed"
    """The read was attempted and raised (ADR-0093 §8).

    "A read that cannot complete may not return what it managed to gather", so no
    reading exists. Whether the source was opened is not determinable from the
    record; see the class docstring.
    """

    DISCARDED = "discarded"
    """The read returned and the re-check answered ``None``.

    The reading was "discarded whole" (ADR-0097 §5). Together with
    :attr:`UNCONFIRMED` this is the row ADR-0185 most exists for: ADR-0097 §5a's
    residual — "a read already in flight completes" — stops being invisible.
    """

    UNCONFIRMED = "unconfirmed"
    """The read returned and the re-check raised ``GrantError``.

    The reading was discarded "exactly as a withdrawn grant is" (ADR-0097 §5), which
    is why this member's ``grant`` and ``produced`` invariants are
    :attr:`DISCARDED`'s exactly. It is a separate member because the sentence after
    that one is the one about telling the two apart.
    """


#: The outcomes decided at the first grant check, before anything is opened. A
#: record carries no ``grant`` on exactly these two and carries one on every other
#: (ADR-0185 §2), which is what lets a reader of the trail partition a row without
#: trusting the writer's discipline.
_UNGRANTED_OUTCOMES: frozenset[ReadOutcome] = frozenset(
    {ReadOutcome.REFUSED, ReadOutcome.UNANSWERED}
)

#: The outcomes on which no reading exists, so nothing was produced (ADR-0185 §2).
#: The two above, plus :attr:`ReadOutcome.FAILED`, where ADR-0093 §8 forbids
#: returning "what it managed to gather".
_READINGLESS_OUTCOMES: frozenset[ReadOutcome] = _UNGRANTED_OUTCOMES | {ReadOutcome.FAILED}


class SourceReadRecord(BaseModel):
    """One recorded attempt to read one source for one use (ADR-0185 §1, §2).

    The row a :class:`~ai_assistant.core.protocols.SourceReadRecorder` appends and a
    :class:`~ai_assistant.core.protocols.SourceReadTrail` hands back. The unit is an
    **attempt** — the act that begins when a driver asks ``SourceGrants.live`` and
    ends when it has taken one of :class:`ReadOutcome`'s six outcomes — so a
    refusal, a failure and a discarded reading each leave exactly one row, as a
    completed read does. A driver writes one record per attempt it takes to an
    outcome and never a second.

    **It carries no source content, no entry, no path and no configured location**,
    and no string derived from any of them (ADR-0004 §5, ADR-0093 §8, ADR-0139 §6).
    :attr:`source` is the reader's *declared identity* and nothing else, and
    :attr:`produced` is a count rather than a thing. That prohibition is the kind a
    diff satisfies and a later field quietly breaks — a failure class stringified
    into a record, a path arriving inside an exception message — so ADR-0185 §11
    arm (c) searches every exported field for a marker seeded into the source rather
    than leaving it to review.

    **Frozen and boundary-crossing** (ADR-0068, ``CLAUDE.md``). ``frozen=True``
    refuses ``record.outcome = …`` and does *not* refuse
    ``record.__dict__["outcome"] = …``, which is why the store's obligation is a
    detached, validated snapshot on both paths rather than a reliance on this
    config — :class:`SourceGrant`'s posture exactly.

    **Two construction invariants rather than prose**, checked here for
    :class:`SourceGrant`'s reason: a record corrupted past its own model would be
    stored and then make every later read of the trail incoherent. Together with
    :class:`ReadOutcome`'s opened-ness rule they let a reader of the trail place a
    row without trusting the writer — ``grant is None`` partitions ``{REFUSED,
    UNANSWERED}`` from the rest, and a non-zero :attr:`produced` is available only
    to the three outcomes in which a reading exists.

    **No ``finished_at`` and no duration.** One instant is what makes an attempt
    reconstructible against a grant history; how long a read took is a performance
    fact with no consumer today, and ADR-0045 §1 and ADR-0028 §7 rule that a field
    with no consumer is surface. ADR-0185 §14 defers it.

    **Any field a later ADR adds is optional with a default** (ADR-0185 §12), on
    ADR-0008 §1's additive pattern: a required addition would make every stored row
    fail validation, which is the failure ADR-0184 records and repairs.

    **A member of** :class:`ReadOutcomeKind` **is refused for** :attr:`outcome`
    **rather than converted** (#2320). That vocabulary is the planner's, about an ask
    a planner composed, and it shares the values ``refused`` and ``failed`` with this
    one; see :meth:`_outcome_is_this_vocabularys_member` for why a conversion here
    would be a fabricated authorisation fact rather than a mislabelled one. A bare
    ``str`` of a member's value is still accepted, so decoding a stored row is
    untouched.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier = Field(
        description=(
            "This record's own id, minted by the caller that records it, as "
            ":attr:`PermissionDecision.id` and :attr:`SourceGrant.id` are — a store "
            "neither mints ids nor reads a clock (ADR-0021 §3)."
        )
    )
    source: NonBlankEncodableText = Field(
        description=(
            "The reader's declared identity — the value "
            ":attr:`~ai_assistant.core.protocols.Reader.name` returns, stored **byte "
            "for byte** (ADR-0185 §2). It is **Tier 2 / operational** and must stay "
            "that way: ADR-0093 §7 makes a reader's identity declared rather than "
            "configured, so a path, filename, address or account identifier may never "
            "be used as one. :data:`NonBlankEncodableText` and deliberately **not** "
            ":data:`Identifier`: this is a *faithful copy*, and ADR-0096 §2 rules that "
            'one "may tighten only in ways that reject". A stripping type would let '
            "the trail name a source the reader is not called, which is the one thing "
            "an audit record may not do. The divergence from "
            ":attr:`SourceGrant.source`, which does strip, is #667's to close."
        )
    )
    use: GrantScope = Field(
        description=(
            "Which of the three uses the attempt was for. A read is attempted for one "
            "use at a time and the three are independent (ADR-0133 §2), so this names "
            "the use the gate was asked about rather than what the grant covered."
        )
    )
    checked_at: UtcInstant = Field(
        description=(
            "The instant the **first grant check resolved** — by answering or by "
            "raising — read from the driver's injected clock immediately after that "
            "and before ``Reader.read()`` (ADR-0185 §12). ADR-0097 §5 makes the answer "
            "and the start of the read one synchronous step, so one instant is "
            "truthful for the resolution and for the read's start alike. **Named for "
            "what it records rather than for the attempt**: an attempt begins when the "
            "driver asks, ``live()`` may suspend, and a field called ``started_at`` "
            "would be a claim about a moment this record does not hold. It is never "
            "derived from :attr:`SourceReading.read_at`, which ADR-0093 §10 captures "
            "later and which a refused attempt has no reading to take from at all. "
            "Timezone-aware, stored as UTC; naive is refused."
        )
    )
    outcome: ReadOutcome = Field(
        description=(
            "How the attempt ended — one of six, mutually exclusive and total "
            "(ADR-0185 §1). It also determines whether the source was opened for five "
            "of the six; see :class:`ReadOutcome`."
        )
    )
    grant: DurableIdentifier | None = Field(
        description=(
            "The :attr:`SourceGrant.id` the attempt ran under, or ``None`` exactly on "
            "``REFUSED`` and ``UNANSWERED`` (ADR-0185 §2). **Required with no "
            "default**, so a caller states it rather than inheriting a value it did "
            "not mean. This is the consumer ADR-0097 §10 wrote ``live`` for — it "
            'returns the record rather than a boolean "so a caller can name what '
            'authorised the read" — and the driver already holds it, so the pointer '
            "costs no second query. **The pointer is one-way**: nothing joins back, "
            "and a ``grant`` that no longer resolves after a ``clear()`` is legible "
            "history in ADR-0184's sense rather than corruption. No implementation may "
            "treat it as a defect, repair it, or drop the row (ADR-0185 §8)."
        )
    )
    produced: int = Field(
        ge=0,
        description=(
            "How many items the **reading** carried — its proposals, and its facet "
            "where it carried one. A count and never a thing: no field names, "
            "identifies or describes any of them (ADR-0185 §2). It is a property of "
            "what the source returned and states nothing about what the use did with "
            "it. **Required with no default**, and zero on ``REFUSED``, ``UNANSWERED`` "
            "and ``FAILED`` because no reading exists in any of the three. A "
            "``COMPLETED`` zero means the read succeeded and the source had nothing, "
            "which ADR-0093 §8 makes a **successful** reading; a non-zero count on a "
            "``DISCARDED`` or ``UNCONFIRMED`` row is the point rather than an "
            'oversight, because "this read across your revocation carried fourteen '
            'proposals that were dropped" is a materially different audit fact from '
            '"it carried none".'
        ),
    )

    @field_validator("outcome", mode="before")
    @classmethod
    def _outcome_is_this_vocabularys_member(cls, value: object) -> object:
        """Refuse :class:`ReadOutcomeKind`'s member here — #2320's reciprocal seam.

        The same overlap, read the other way. ``ReadOutcomeKind.REFUSED`` says *the
        source decided not to answer, on a ground it owns* (ADR-0251 §2); accepted
        here it would become :attr:`ReadOutcome.REFUSED`, whose meaning is *the first
        grant check answered ``None``, so the source is not resolved, not opened and
        not parsed* (ADR-0097 §5, ADR-0185 §1) — and, through
        :meth:`_grant_matches_outcome`, would then be a row asserting that no live
        grant was found. **That is a fabricated authorisation fact in the permission
        trail**, which ADR-0185 §1 forbids in terms over the neighbouring
        :attr:`ReadOutcome.UNANSWERED`: folding one outcome into another "would put the
        claim *there was no live grant* into a store whose premise is that its records
        are not fabricated". The trail is durable, exported and rendered to an operator
        (:attr:`source`), so this direction is the costlier of the two.

        Only the two shared values could ever arrive; the remaining five members of the
        planner's vocabulary carry no value of these six and were refused already.
        """
        return _own_vocabularys_member(value, ReadOutcome, cited="ADR-0185 §1")

    @model_validator(mode="after")
    def _grant_matches_outcome(self) -> SourceReadRecord:
        """Refuse a record whose ``grant`` disagrees with its ``outcome`` (ADR-0185 §2).

        The correspondence is exact in both directions: a grant was found at the
        first check on four of the six outcomes and was not found on the other two,
        so a ``REFUSED`` row citing a grant claims an authorisation the driver never
        had, and a ``COMPLETED`` row citing none loses the pointer the whole field
        exists for.
        """
        ungranted = self.outcome in _UNGRANTED_OUTCOMES
        if ungranted and self.grant is not None:
            msg = (
                f"a {self.outcome.value!r} attempt found no live grant at its first "
                f"check, so it names none; got grant={self.grant!r} (ADR-0185 §2)"
            )
            raise ValueError(msg)
        if not ungranted and self.grant is None:
            msg = (
                f"a {self.outcome.value!r} attempt ran under a live grant and must name "
                f"it; got grant=None (ADR-0185 §2)"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _produced_matches_outcome(self) -> SourceReadRecord:
        """Refuse a non-zero ``produced`` where no reading exists (ADR-0185 §2).

        ``REFUSED`` and ``UNANSWERED`` never called ``read()`` and ``FAILED``'s read
        raised, so on all three there is nothing a count could be *of*. The other
        three carry a reading and may state any count from zero up.
        """
        if self.outcome in _READINGLESS_OUTCOMES and self.produced != 0:
            msg = (
                f"a {self.outcome.value!r} attempt carries no reading, so it produced "
                f"nothing; got produced={self.produced} (ADR-0185 §2)"
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


# --- acting's effect records (ADR-0306 §5, §6) --------------------------------
# One record per call in the world, per message, and per call to a capability that
# is not safe to repeat, pointing at the activation that made it. Written by
# `PlanStore.claim_activation_effect` before the call runs and finished by
# `finish_activation_effect` once its outcome is known.


class ActivationEffectClaim(StrEnum):
    """What a store answered when asked to claim one activation effect (ADR-0306 §6:2).

    **Two members, closed.** A stopped activation is not an answer: the claim raises
    ``ClaimStopped`` instead.
    """

    CLAIMED = "claimed"
    """The record was written, carrying no outcome; the call or message may run."""

    ALREADY_DONE = "already_done"
    """A matching effect of a named activation is done, unknown or not yet written,
    so nothing was written and the call does not run (ADR-0306 §5:9 to §5:11)."""


class ActivationEffect(BaseModel):
    """One effect an activation made or is making, as acting records it (ADR-0306 §6).

    **A call or a message, never both.** A call carries its capability, a digest of
    its values and the id of the ``PermissionDecision`` that allowed it; a message
    carries its place and, once the medium has recorded it, its position. The outcome
    is ``None`` from the claim until the effect happens, and is then written once:
    ``succeeded`` is done, ``failed`` not done and ``indeterminate`` unknown.

    The record points at the activation and never at a story, so a split, a merge or a
    move carries it with its episode (ADR-0306 §5). It names the round whose call or
    message it claims, and only the *couldn't finish* message names none (ADR-0307
    §10).

    Attributes:
        id: The record's id, minted before the ruling and named by the deciding
            decision's ``effect``.
        activation_id: The activation that made the effect.
        round: The planning round whose call or message this claims; ``None`` only on
            the *couldn't finish* message.
        capability: For a call, the capability called.
        values_digest: For a call, the digest of the values the duplicate backstop
            compares (ADR-0306 §2:10, §5:12).
        decision_id: For a call, the ``PermissionDecision`` that allowed it.
        place: For a message, the place it goes into.
        position: For a message done, the position the medium recorded it at.
        outcome: The outcome, once known.
        reason: Why the effect was not done, where it was not.
        claimed_at: When the record was claimed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier
    activation_id: DurableIdentifier
    round: DurableIdentifier | None = None
    capability: VisibleIdentifier | None = None
    values_digest: Sha256Hex | None = None
    decision_id: DurableIdentifier | None = None
    place: DurableIdentifier | None = None
    position: int | None = Field(default=None, ge=0)
    outcome: ToolOutcome | None = None
    reason: NonBlankEncodableText | None = None
    claimed_at: UtcInstant

    @property
    def is_call(self) -> bool:
        """Whether this records a call, rather than a message."""
        return self.capability is not None

    @model_validator(mode="after")
    def _a_call_or_a_message(self) -> ActivationEffect:
        """Refuse a record that is neither a whole call nor a whole message (ADR-0306 §6).

        Raises:
            ValueError: If a call lacks its values digest or deciding decision, carries a
                place or a position, or names no round; or a message lacks its place or
                carries a call's fields.
        """
        call_fields = (self.capability, self.values_digest, self.decision_id)
        if self.capability is not None:
            if None in call_fields:
                msg = "a call's effect carries its capability, values digest and decision"
                raise ValueError(msg)
            if self.place is not None or self.position is not None:
                msg = "a call's effect carries no place and no position"
                raise ValueError(msg)
            if self.round is None:
                msg = "a call's effect names the round that proposed it (ADR-0307 §10)"
                raise ValueError(msg)
            return self
        if any(field is not None for field in call_fields):
            msg = "a message's effect carries no capability, values digest or decision"
            raise ValueError(msg)
        if self.place is None:
            msg = "an effect is a call, with its capability, or a message, with its place"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _outcome_fields_match(self) -> ActivationEffect:
        """Tie the reason and the position to the outcome they belong to (ADR-0306 §5:5).

        Raises:
            ValueError: If a reason rides on an outcome other than not done, or a
                position on anything but a message done.
        """
        if self.reason is not None and self.outcome is not ToolOutcome.FAILED:
            msg = "only an effect not done carries a reason"
            raise ValueError(msg)
        if self.position is not None and self.outcome is not ToolOutcome.SUCCEEDED:
            msg = "only a message done carries a position"
            raise ValueError(msg)
        return self


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

    :attr:`incurred_cost` is ADR-0192 §5's, and it partially supersedes ADR-0029
    §3's "``ToolResult`` carries no cost". That section's reason — billing is
    asynchronous, so a ``spent`` field would hold a number the tool made up — is
    answered rather than waived: the field is a :class:`ToolCost`, so a tool that
    cannot know reports ``UNKNOWN`` and an accumulator fails closed on it, which
    is ADR-0016 §4's own distinction between *free* and *unknown*. **A tool
    populates it on an exit it composes itself** (ADR-0195, which answered
    #1558): a successful call returns a :class:`ReportedOutput`, which the
    invocation seam unwraps and revalidates onto this field, and a classified
    failure carries one on
    :class:`~ai_assistant.core.errors.ClassifiedToolError`, which that seam
    revalidates onto it the same way. On the two exits a tool does **not** compose —
    an exception escaping, and this seam's deadline expiring or a cancellation
    being delivered — it reports nothing and the row records an ``UNKNOWN``
    basis, because that is the truth (ADR-0195 §1). The disclosure-report half of
    §3's sentence stands and issue #57 is untouched.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: ToolOutcome
    output: FrozenJsonValue = Field(default=None, description="Only meaningful when SUCCEEDED.")
    failure: ToolFailure | None = Field(default=None, description="Required unless SUCCEEDED.")
    incurred_cost: ToolCost | None = Field(
        default=None,
        description=(
            "What *this* invocation cost, as the tool reports it (ADR-0192 §5). "
            "``None`` states that the tool reported no figure, and the row then "
            "records a ``ToolCost`` whose basis is ``UNKNOWN``. Named apart from "
            "``ToolDefinition.cost`` so that a declaration and a measurement are "
            "never one word: no lane copies the declaration into it, and a tool "
            "whose price is settled asynchronously reports ``UNKNOWN`` rather than "
            "a number it constructed to fill the field."
        ),
    )

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


class ReportedOutput(BaseModel):
    """A successful call's output together with what that call cost (ADR-0195 §2).

    The carrier for the **success exit** — one of the two exits a tool composes
    itself, the other being the
    :class:`~ai_assistant.core.errors.ClassifiedToolError` ADR-0032 specifies and
    ADR-0195 §3 gives a matching field to. A tool that
    knows what its call cost returns one of these in place of its bare output;
    the invocation seam discriminates the two by ``isinstance`` and by no other
    test, revalidates the figure, and records it on
    :attr:`ToolResult.incurred_cost`.

    **The envelope is unwrapped at that seam and travels no further.** No
    ``ToolResult``, ``StepExecution``, audit row, wire message or consumer of
    ``ToolInvoker`` ever holds one, so ADR-0087's encoding is untouched.

    :attr:`incurred_cost` is **required**. A tool with nothing to report returns
    its output bare, which is what every registered tool in this system does
    today, and an envelope whose cost was optional would be a second spelling of
    that bare return — the shape ADR-0031 §1 exists to remove. Reporting an
    ``UNKNOWN`` basis is permitted and lands identically to reporting nothing
    (ADR-0195 §5), so an integration computing a figure from a tariff table that
    sometimes yields ``UNKNOWN`` need not branch at its return statement.

    :attr:`output` carries :data:`FrozenJsonValue`, the same annotation
    :attr:`ToolResult.output` carries, so the envelope opens **no** route by
    which content reaches a result that a bare return does not already reach. A
    value that annotation refuses raises here, at the envelope's own
    construction, in the tool's own frame, and escapes as an ordinary exception —
    which the seam classifies ``INTERNAL``, exactly where the same value lands
    when it is returned bare (ADR-0029 §3). It cannot nest either:
    :data:`FrozenJsonValue` admits no ``BaseModel``, so :attr:`output` can never
    hold another envelope and there is no unwrapping loop to get wrong.

    **It states a price and never an outcome.** There is no field here for a
    ``ToolOutcome``, a ``ToolFailure`` or anything else the seam rules, and
    ``extra="forbid"`` stops one being smuggled in: a callable's own account of
    what happened to it is not evidence (ADR-0031 §2), while a price is the one
    thing about the call that only the integration can know (ADR-0195 §1, §5).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    output: FrozenJsonValue = Field(
        default=None, description="What the call produced, exactly as a bare return would carry it."
    )
    incurred_cost: ToolCost = Field(
        description=(
            "What *this* call cost, as the integration itself learned it: a charge "
            "the upstream returned, a metered quantity its response carried, or a "
            "tariff the integration's provider publishes. Never "
            "``ToolDefinition.cost``, never a configured allowance and never a "
            "number constructed to fill the field (ADR-0192 §5, ADR-0195 §5) — a "
            "tool that cannot price the call returns its output bare or reports an "
            "``UNKNOWN`` basis, which land identically."
        )
    )


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


# --- what a call spent, and what it did (ADR-0192 §§1-2) ---------------------
# --- the promoted engine surface (ADR-0084 §4, ADR-0085) ---------------------
# The types :class:`~ai_assistant.core.protocols.AssistantEngine`'s methods name,
# and the complete transitive closure of what their fields reach (ADR-0085 §5).
# **Neither count is written here, and that is the durable form** (#1125,
# `CONTRIBUTING.md` -> "No state claims in living documents"): both are owned by
# `tests/core/test_engine_surface_closure.py`, which walks the declared field graph
# out from every signature on the surface and fails when the promoted set and the
# reachable set disagree. A figure in a comment goes stale silently at the next
# method; a figure a check owns cannot. This block carried "twenty-five types …
# nineteen methods" against a Protocol that had grown past both, which is the drift
# ADR-0151 §16 assigned to its implementing lane to correct. ADR-0102
# §3 adds `GrantableSource` for the four grant operations, and §13 records why
# ADR-0085 §1's "and nothing else" is not thereby falsified — what that exclusion
# excludes is *lifecycle*, and the closed graph its title claims is preserved
# rather than moved. They lived in `orchestration` while one concrete engine
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


# The trail's second row kind. A `ToolInvocation` is appended twice per attempt —
# a **claim** immediately before the callable is entered, and a **completion**
# pointing back at it — so the record says an act was begun even where the process
# died mid-effect, and so the claim can be the atomic consume ADR-0021 §4 deferred
# to "the invocation contract". A `RecordedInvocation` is that row joined to the
# decision it names, which is the shape every reader gets: the tool's identity
# lives on the decision, and a bounded page can hold a completion whose claim and
# whose decision are not on it (ADR-0192 §2).
#
# **Declared inside the promoted block, and not ahead of it, although nothing on
# the surface names them yet.** ADR-0192 §9 says they "join the promoted set
# `tests/core/test_engine_surface_closure.py` walks", and where they are declared
# is what decides whether that can ever happen: `_declared_by_this_change()` sorts
# everything ahead of :data:`DEFAULT_PAGE_SIZE` as a pre-existing leaf the walk
# terminates at, so a type declared there is invisible to
# `test_the_promoted_set_is_the_one_the_adrs_gathered` **forever** — including on
# the day the surface group lands ADR-0192 §4's two operations and the walk starts
# reaching it. That is the treatment `SourceReadRecord` and `ReadOutcome` get, and
# it is right for them: they predate the block (ADR-0185 §12) and were inside the
# closure the day they landed. These two are new here, so it would be a check
# switched off rather than a check already satisfied.
#
# They are **not** added to `PROMOTED` in this lane, because that set is also
# asserted from the other side: `test_the_walk_reaches_every_promoted_type` fails
# on a promoted type no signature reaches, and no signature reaches these until
# §4's operations exist. Landing them here and leaving `PROMOTED` alone is what
# makes the surface group's lane *have* to add them — the closure check fails the
# moment the walk arrives — which is §9's clause enforced rather than remembered.


class ToolInvocation(BaseModel):
    """One append to the trail's record of an act (ADR-0192 §2).

    **Exactly two well-formed shapes, and a validator refuses every other
    combination at construction.** A *claim* carries :attr:`completes`,
    :attr:`outcome`, :attr:`incurred_cost` and :attr:`failure_kind` all unset. A
    *completion* carries the first three set, and :attr:`failure_kind` only where
    the outcome is not ``SUCCEEDED`` — where it may be set and may be absent.
    :attr:`completes` is the discriminator. Two shapes inside one model is what
    :class:`CanonicalDestination` already does and for the same reason: the
    variants are exactly two and a validator makes every other combination
    unconstructable.

    **A claim carrying no completion states that the act may have executed**,
    positively and as its own state (ADR-0192 §3). No lane, store or surface reads
    it as ``SUCCEEDED``, as ``FAILED``, as "did not run", as an omission, or as a
    row still being written — ADR-0184's third state, one store over.

    **It restates nothing its decision already fixes.** No ``ToolDefinition``, no
    ``parameters_digest``, no ``step_id``, no ``execution_id``, no account, no
    transport endpoint and no destination: what a call transmitted to is the
    decision's own ``EgressBinding.canonical_destination_set``, reached through
    :attr:`decision_id`, and copying it here would be the second shape that must
    agree ADR-0184 §2 refused. It carries **no content** — not an argument value,
    not a payload, not an output, not a failure message, and not a digest of any of
    them (ADR-0004 §5). And it carries **no ordinal**: how many acts a decision has
    backed is read from the claims themselves, in the ledger's own order.

    Both row kinds are Tier 1 and persist locally only (ADR-0004 §2, §7).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: DurableIdentifier = Field(
        description=(
            "The row's own id, minted by the ledger from an injected factory and "
            "never supplied by a caller (ADR-0192 §2). It names nothing outside the "
            "store: it is learned from the returned row and used once, to point a "
            "completion at its claim."
        )
    )
    decision_id: DurableIdentifier = Field(
        description=(
            "The authorisation this act ran under. On a completion the ledger sets "
            "it from the claim being completed, so the two cannot disagree."
        )
    )
    recorded_at: UtcInstant = Field(
        description=(
            "When the append happened, stamped by the ledger from a guarded clock "
            "and never supplied by a caller. **Not** the order any rule is decided "
            "on: that is the ledger's own durable append order, so a wall clock "
            "that steps backwards cannot make a completed act stop being the most "
            "recent one (ADR-0192 §1)."
        )
    )
    completes: DurableIdentifier | None = Field(
        default=None, description="The claim this row completes; unset on a claim."
    )
    outcome: ToolOutcome | None = Field(
        default=None, description="How the act finished; set on a completion only."
    )
    incurred_cost: ToolCost | None = Field(
        default=None,
        description=(
            "What this invocation cost, as the tool reported it — a ``ToolCost`` "
            "whose basis is ``UNKNOWN`` where it reported none (ADR-0192 §5). Set "
            "on a completion only, and never derived from ``ToolDefinition.cost``."
        ),
    )
    failure_kind: ToolFailureKind | None = Field(
        default=None,
        description=(
            "Transcribed from the ``ToolResult`` that carried one, never "
            "synthesised. Absent on a completion derived from an exception, "
            "because no result was produced to transcribe from."
        ),
    )

    @model_validator(mode="after")
    def _is_a_claim_or_a_completion(self) -> ToolInvocation:
        """Refuse every combination but the two shapes ADR-0192 §2 declares.

        ``INDETERMINATE`` carries a kind on the same terms as ``FAILED`` and the
        row does not drop it: ADR-0029 §3's ``ToolResult`` validator *requires* a
        ``ToolFailure`` on every result that is not ``SUCCEEDED``, so a keyed
        side-effecting call that timed out arrives at this seam carrying
        ``TIMED_OUT``. A ``SUCCEEDED`` completion carries none, because a
        ``SUCCEEDED`` result carries no failure to transcribe.

        A completion with :attr:`incurred_cost` unset is refused here rather than
        left to a validator checking :attr:`completes` against :attr:`outcome`
        alone: such a row reaches a spend accumulator and ADR-0192 §4's rendering
        floor as a completion with no cost, which is the absence §5 exists to make
        unrepresentable.
        """
        if self.completes is None:
            unset = {
                "outcome": self.outcome,
                "incurred_cost": self.incurred_cost,
                "failure_kind": self.failure_kind,
            }
            carried = sorted(name for name, value in unset.items() if value is not None)
            if carried:
                msg = f"a claim carries no {', '.join(carried)}"
                raise ValueError(msg)
            return self
        if self.outcome is None:
            msg = "a completion requires an outcome"
            raise ValueError(msg)
        if self.incurred_cost is None:
            msg = "a completion requires an incurred_cost"
            raise ValueError(msg)
        if self.failure_kind is not None and self.outcome is ToolOutcome.SUCCEEDED:
            msg = "a SUCCEEDED completion carries no failure_kind"
            raise ValueError(msg)
        return self


class RecordedInvocation(BaseModel):
    """An invocation row joined to the decision it names (ADR-0192 §2).

    **The join is the store's**, taken inside one atomic operation, so every value
    a reader is handed is complete. An engine reading rows and then reading their
    decisions has an ``await`` between the two, and a ``clear()`` landing in that
    gap leaves it holding rows whose decisions are gone — with nothing to do but
    drop them, fabricate the identifiers, or fail.

    **It carries a boolean and not the binding.** Who received the bytes is
    ``recent_decisions``' to render from the binding itself (ADR-0186 §7); putting
    a second copy of the destination set here would be the drift ADR-0184 §2
    refuses, in service of a rendering another operation already owes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation: ToolInvocation = Field(description="The row, verbatim.")
    tool: VisibleIdentifier = Field(
        description="``ToolDefinition.id`` from the decision this row names."
    )
    capability: VisibleIdentifier = Field(
        description="``ToolDefinition.capability`` from that same decision."
    )
    egress_call: bool = Field(
        description=(
            "True when and only when the named decision's ``egress_binding`` is "
            "not ``None``. It states that the call was an egress call and states "
            "nothing about whose bytes went where."
        )
    )


# --- the world's price: what a period cost, and what it may still cost ---------
# ADR-0194. A ceiling is decided before the act, over calendar periods in the
# user's zone, and an unknown price is never zero. Three names here and no more:
# the enum, the total, and the opaque handle a reservation is retired by.


#: The magnitude bound on a **source** amount (ADR-0194 §1), strict. Ten to the
#: fifteenth in any real currency's major unit exceeds any plausible monthly
#: ceiling by orders of magnitude, and bounding it is what makes §2's exact
#: arithmetic computable rather than aspirational: unbounded, two amounts a
#: validator would accept have an exact sum needing more coefficient digits than
#: ``decimal.MAX_PREC`` admits, so the computation exhausts memory instead of
#: trapping and the outcome depends on the machine.
_SPEND_AMOUNT_CEILING: Final = Decimal("1E15")

#: The scale bound on a **source** amount (ADR-0194 §1): at most this many
#: fractional digits *of value*. Nine carries every currency's minor unit and
#: every nano-unit price a metered API quotes.
_SPEND_AMOUNT_SCALE: Final = 9

#: The strict bound on a ``SpendTotal`` offset (ADR-0194 §5). The widest offsets
#: the tz database carries are well inside it; a whole day is not.
_A_DAY: Final = timedelta(hours=24)

#: Neither bound governs a computed **total** (ADR-0194 §1, §5): the predicate is
#: over inputs, and a sum over rows nothing bounds may honestly exceed either.


def _effective_exponent(amount: Decimal) -> int:
    """Return the scale ``amount``'s *value* needs, ignoring trailing zeros.

    ADR-0194 §1 makes countability "a test on the number and not on its
    representation", and §2 carries the same rule into the arithmetic: a zero
    coefficient contributes nothing whatever its exponent, and a value's trailing
    zeros below its last significant digit do not enlarge the context that must be
    sized to hold it. Without this ``Decimal("0E-999999999999999999")`` — countable,
    numerically zero — would demand a precision no machine can allocate.

    Read from ``as_tuple()`` and never from ``decimal.getcontext()``: no ambient
    precision, rounding mode or trap setting changes the answer or makes this
    raise (ADR-0194 §1).
    """
    sign, digits, exponent = amount.as_tuple()
    del sign
    if not isinstance(exponent, int):  # 'n', 'N' or 'F' — a non-finite value
        msg = f"a non-finite Decimal has no effective exponent, got {amount!r}"
        raise ValueError(msg)
    if not any(digits):
        return 0
    trailing = 0
    for digit in reversed(digits):
        if digit:
            break
        trailing += 1
    return exponent + trailing


def _is_countable_spend_amount(amount: Decimal) -> bool:
    """Report whether ``amount`` is countable under ADR-0194 §1.

    All three of: finite; absolute value **strictly** below
    :data:`_SPEND_AMOUNT_CEILING`; and a value expressible with at most
    :data:`_SPEND_AMOUNT_SCALE` fractional digits. ``Decimal("1.0000000000")`` is
    countable because its *value* is ``1``.

    **Context-independent by construction.** Everything it reads comes from the
    amount's own ``as_tuple()``, so an implementation calling it inside a hostile
    ambient context — a precision of ten, with traps armed — gets the same answer
    and no ``decimal`` exception (ADR-0194 §1).

    This governs every amount the mechanism *reads*: a configured ceiling, the
    allowance, a declared ``ToolCost.amount`` and a reported one. It governs no
    result: a computed total is a sum over rows nothing bounds and is never
    refused on it.
    """
    if not amount.is_finite():
        return False
    if _effective_exponent(amount) < -_SPEND_AMOUNT_SCALE:
        return False
    # ``copy_abs`` and not ``abs``: the latter is an arithmetic operation that
    # rounds to the ambient precision and traps under a hostile context, which
    # is exactly what this predicate is required not to depend on. Comparison
    # between two finite ``Decimal``s is itself exact and context-free.
    return amount.copy_abs() < _SPEND_AMOUNT_CEILING


def _is_canonical_spend_total(amount: Decimal) -> bool:
    """Report whether ``amount`` is ADR-0194 §2's **one** representation of a total.

    The exact value at its minimal non-negative scale, with a sign that is never
    negative: as many fractional digits as the value needs and no more, never a
    positive exponent, and ``Decimal("0")`` rather than ``Decimal("-0")`` for a
    zero total. Stated over ``as_tuple()``: the sign is 0, the exponent is between
    ``-_SPEND_AMOUNT_SCALE`` and 0 inclusive, and where the exponent is negative the
    last digit is non-zero.

    So ``Decimal("2")`` and ``Decimal("20")`` pass while ``Decimal("2.0")``,
    ``Decimal("2E+1")`` and ``Decimal("-0")`` do not. ``Decimal("2E+0")`` is not a
    case: it and ``Decimal("2")`` are one representation — ``as_tuple()`` returns
    ``(0, (2,), 0)`` for both — so no rule can separate them and this one does not
    try.

    It exists because two conforming implementations summing the same rows in any
    order must state the same **bytes** on the wire: ADR-0087 §4's relation is
    indistinguishability rather than ``==``, and ``Decimal("2.0")`` and
    ``Decimal("2")`` compare equal while ``as_tuple()`` tells them apart.
    """
    if not amount.is_finite():
        return False
    sign, digits, exponent = amount.as_tuple()
    if sign != 0 or not isinstance(exponent, int):
        return False
    if exponent > 0 or exponent < -_SPEND_AMOUNT_SCALE:
        return False
    return exponent == 0 or digits[-1] != 0


class SpendPeriod(StrEnum):
    """The calendar periods a spend ceiling is stated over (ADR-0194 §1).

    Exactly two, and **no ordering semantics**: neither takes precedence over the
    other, both bind independently and simultaneously where both are configured,
    and a call is refused where it would cross either. The declaration order here
    is the fixed order every surface states them in — ``SpendLedger.spend_totals``'
    tuple, a refusal naming two periods, and the CLI's rendering — so that two
    conforming implementations state the same facts in the same sequence.

    A rolling window is the more precise instrument and the wrong one for this
    quantity: what a user has in mind when they cap spend is a bill, and bills
    arrive on calendar boundaries. The cost of the calendar is exactly one thing —
    a month ceiling admits a spike on the last day of a month and the same spike on
    the first day of the next — and :attr:`CALENDAR_DAY` is the rate limit that
    pays for it.
    """

    CALENDAR_DAY = "calendar_day"
    CALENDAR_MONTH = "calendar_month"


class SpendAdmissionHandle(BaseModel):
    """The opaque key to one admission's reservation (ADR-0194 §5).

    ``SpendGate.admit_invocation`` returns one on every grant and
    ``SpendGate.release_admission`` retires the reservation it names. It is
    **opaque**: a caller neither parses it, orders it, nor derives a period, an
    amount or a tool from it, and no implementation encodes one in it.

    **It reaches no record, no surface and no wire frame** — it lives between the
    invoker and the gate for the duration of one call — so nothing here promotes a
    new value onto ADR-0085's surface, and no adapter, engine or client ever holds
    one.

    A model and not a bare ``str`` because it crosses a subsystem boundary —
    ``tools/`` holds it, ``permissions/`` mints and resolves it — and because
    :data:`Identifier` refuses the blank string that would satisfy "a handle is
    present" while naming nothing. :class:`ContinuationToken` is the same shape for
    the same reasons one seam over, and this copies it rather than inventing a
    second convention.

    **Distinctness is tested on the validated value, not on what a factory
    returned** (ADR-0194 §3). :data:`Identifier` strips, so ``"h"`` and ``" h "``
    are two raw strings and one handle; a holder checking uniqueness before
    construction would hold two reservations under one key.

    Attributes:
        handle: The gate-private handle, opaque to every caller.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    handle: Identifier = Field(description="The gate-private handle, opaque to every caller.")


class SpendTotal(BaseModel):
    """What one calendar period has cost, and what it was allowed to (ADR-0194 §5).

    One of these per :class:`SpendPeriod`, returned by
    ``SpendLedger.spend_totals`` in that enum's fixed order, whatever is
    configured.

    **No zone name crosses this boundary, and that is the decision rather than an
    omission.** Carrying the IANA zone the boundaries were computed in would make
    acceptance and rendering depend on the *consumer's* installed ``tzdata``: the
    value would carry a zone *name* and not the rule-set that named it, so a hub on
    one revision and a client on another — over a zone whose transitions were
    revised, of which ``Asia/Gaza`` is the live example — would disagree about the
    boundaries of the same civil day. ADR-0016 §2 forbids exactly that of a
    ``core/types.py`` semantic. The resolved **offsets** are the whole of what a
    renderer needs: it prints each bound as that bound plus that bound's own
    offset and labels it with that offset, resolving no zone and reading no
    ``tzdata``. Two offsets rather than one because a period containing a
    transition has different offsets at its two ends.

    What is given up is stated: a reader of a ``SpendTotal`` alone cannot name the
    zone, only the offsets. The surface that wants the name has it —
    ``Settings.timezone`` is the producer's own configuration — and no lane infers
    a zone back out of an offset, which is many-to-one and would be a guess.

    **Every invariant below is decidable from the value alone** (ADR-0016 §2's
    intrinsic test: computable from the type's own declaration, the same answer for
    every consumer). In particular this model does **not** re-derive ADR-0194 §1's
    period boundaries and compare: the tempting stronger validator would reject a
    ``CALENDAR_DAY`` carrying a month's bounds, which this one admits, and the
    correspondence to §1's rule is checked at the **producer**, which is the only
    place that can compare against the rule rather than against a second
    implementation of it.

    **The two amounts carry different numeric invariants and they are not one
    rule.** A :attr:`ceiling` is an *input* — exactly what §1 admits as a
    configured ceiling — so it keeps whatever scale the user wrote. An
    :attr:`accounted` total is a *result*, so it carries §2's one representation
    rather than merely a value compatible with it, and is deliberately unbounded in
    magnitude.

    Attributes:
        period: Which calendar period this states.
        period_start: The period's inclusive start instant.
        period_end: The period's **exclusive** end instant. Equal to
            :attr:`period_start` on a zero-length period, which ADR-0194 §1's
            skipped-civil-date case produces and this model must accept.
        start_offset: The UTC offset in force at :attr:`period_start`, as the
            producer resolved it.
        end_offset: The UTC offset in force at :attr:`period_end`. Different from
            :attr:`start_offset` on a period containing a transition, which is the
            case a single offset would have misrendered.
        ceiling: The configured ceiling for this period, or ``None`` where none is
            configured. Non-``None`` only where :attr:`currency` is.
        currency: The configured reporting currency, or ``None`` where none is.
            It is the discriminator for :attr:`accounted`'s absence.
        accounted: The sum of the reported per-invocation costs on the completion
            rows falling in this period, or ``None``. ``None`` in exactly two
            states, which :attr:`currency` tells apart: with ``currency`` absent no
            currency is configured and no total was computed; with ``currency``
            present the period is **indeterminate** — an open claim in it, or a
            reported cost this mechanism may not add. No third meaning is assigned
            to the absence, and "the total is zero" never reaches it, because zero
            spend is ``Decimal("0")`` and is representable.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    period: SpendPeriod = Field(description="Which calendar period this states.")
    period_start: UtcInstant = Field(description="The period's inclusive start instant.")
    period_end: UtcInstant = Field(description="The period's exclusive end instant.")
    start_offset: timedelta = Field(
        description="The UTC offset in force at ``period_start``, as the producer resolved it."
    )
    end_offset: timedelta = Field(
        description="The UTC offset in force at ``period_end``, as the producer resolved it."
    )
    ceiling: Decimal | None = Field(
        default=None, description="The configured ceiling for this period; None where unset."
    )
    currency: EncodableText | None = Field(
        default=None, description="ISO-4217 alphabetic code; None where none is configured."
    )
    accounted: Decimal | None = Field(
        default=None,
        description=(
            "The sum of the reported costs in this period; None where no currency "
            "is configured or the period is indeterminate."
        ),
    )

    @field_validator("currency")
    @classmethod
    def _currency_is_iso_4217_shaped(cls, value: str | None) -> str | None:
        """Require exactly three uppercase ASCII letters, without normalising.

        ``ToolCost.currency``'s rule and not a second one (ADR-0194 §1, §5).
        :data:`EncodableText` is the base this layers on and is **not** the whole of
        it: that admits ``""`` and ``"usd"``, and a ``SpendTotal`` carrying either
        would state a currency §1 refuses as configuration and a renderer would
        print it.
        """
        if value is None:
            return None
        if len(value) != _CURRENCY_CODE_LENGTH or not (
            value.isascii() and value.isupper() and value.isalpha()
        ):
            msg = f"currency must be three uppercase ASCII letters (ISO-4217), got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("ceiling")
    @classmethod
    def _ceiling_is_a_configurable_amount(cls, value: Decimal | None) -> Decimal | None:
        """Require exactly what ADR-0194 §1 admits as a configured ceiling.

        Finite, greater than or equal to zero, and **countable**. It is the value
        the user configured and nothing computes it, so §2's one-representation
        rule — which governs results — does not reach it: a configured
        ``Decimal("2.0")`` ceiling is admitted and carried as written.
        """
        if value is None:
            return None
        if not value.is_finite():
            msg = f"a ceiling must be finite, got {value!r}"
            raise ValueError(msg)
        if value < 0:
            msg = f"a ceiling must not be negative, got {value!r}"
            raise ValueError(msg)
        if not _is_countable_spend_amount(value):
            msg = (
                f"a ceiling must be countable — below {_SPEND_AMOUNT_CEILING} and to at most "
                f"{_SPEND_AMOUNT_SCALE} fractional digits (ADR-0194 §1), got {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("accounted")
    @classmethod
    def _accounted_is_a_canonical_total(cls, value: Decimal | None) -> Decimal | None:
        """Require ADR-0194 §2's one representation of a computed total.

        A model accepting a second spelling would accept a value this mechanism
        cannot produce and would put bytes on the wire no conforming implementation
        states. This subsumes the two invariants a reader would otherwise reach for
        — non-negativity, and at most :data:`_SPEND_AMOUNT_SCALE` fractional digits,
        which holds because every row contributing to it carries at most that many
        — and it is deliberately **not** bounded in magnitude, because §1's
        predicate governs inputs and a total is a result.
        """
        if value is None:
            return None
        if not value.is_finite():
            msg = f"an accounted total must be finite, got {value!r}"
            raise ValueError(msg)
        if not _is_canonical_spend_total(value):
            msg = (
                "an accounted total must carry ADR-0194 §2's one representation — "
                f"non-negative, at its minimal non-negative scale, got {value!r}"
            )
            raise ValueError(msg)
        return value

    @field_validator("start_offset", "end_offset")
    @classmethod
    def _offset_is_within_a_day(cls, value: timedelta) -> timedelta:
        """Require an offset strictly within ±24 hours, at whatever resolution it has.

        **Seconds included, and not rounded to a minute.** ``core/clock.py``
        already accounts for the historical offsets the tz database carries, naming
        ``Asia/Manila``'s ``-15:56:08`` and ``America/Metlakatla``'s ``+15:13:42``
        as the widest; a whole-minute rule would make a ``SpendTotal`` unable to
        state the offset actually in force for a reading ``checked_clock`` accepts,
        leaving the producer to leak a validation failure, round the offset, or
        fail to return the value it owes.
        """
        if not -_A_DAY < value < _A_DAY:
            msg = f"a UTC offset must be strictly within ±24 hours, got {value!r}"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _bounds_and_absences_agree(self) -> SpendTotal:
        """Check the cross-field rules, each decidable from the value alone.

        The bounds are ordered — ``period_start`` strictly before ``period_end``,
        or equal on ADR-0194 §1's zero-length period, which is a value this model
        must accept. Each bound **plus its own offset** lands inside ``datetime``'s
        range, which is what makes the required rendering total: a renderer performs
        exactly those two additions, and without this the range and ordering rules
        admit a value it cannot print. And ``currency`` discriminates both
        absences, so neither amount may stand without it.
        """
        if self.period_start > self.period_end:
            msg = f"a period ends before it starts: {self.period_start!r} > {self.period_end!r}"
            raise ValueError(msg)
        for name, bound, offset in (
            ("period_start", self.period_start, self.start_offset),
            ("period_end", self.period_end, self.end_offset),
        ):
            try:
                bound + offset
            except (OverflowError, ValueError) as exc:
                msg = f"{name} plus its own offset is not representable: {exc}"
                raise ValueError(msg) from exc
        if self.currency is None:
            if self.ceiling is not None:
                msg = "a ceiling states an amount in a currency, so it needs one"
                raise ValueError(msg)
            if self.accounted is not None:
                msg = "an accounted total states an amount in a currency, so it needs one"
                raise ValueError(msg)
        return self


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
    holds no citations. What it holds is how many it *carries*, how many of those
    are gone, and — since ADR-0107 §3 — an upper bound on how many further ones
    stood behind the belief and are no longer carried. **§4's question is answered
    by the pair** ``evidence_count`` and ``evidence_elided``, never by
    ``evidence_count`` alone (ADR-0107 §6): before ADR-0086 §1's bound the two
    numbers could not differ, and after it they can.

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
        evidence_count: How many citations the belief **carries**, resolved or not.
            A **field** here rather than a property, because this type carries no
            evidence to derive it from. Not on its own the answer to "how many
            stand behind it" — read it with ``evidence_elided`` (ADR-0107 §6).
        lost_evidence: How many of those citations no longer resolve. A field for
            the same reason.
        valid_until: The end of the belief's validity window, where one is set;
            ``None`` where the window is open. Every listed belief is live by
            construction, so an open window carries no information and a set end
            does.
        evidence_elided: :attr:`Provenance.evidence_elided` **as stored** — an
            upper bound on how many further citations stood behind the belief and
            are no longer carried. Carried on **every** band, never zeroed or
            clamped by band, because the DTO reports what the record holds
            (ADR-0107 §3); whether a *rendering* is owed is a separate question
            §2 scopes to ``DERIVED``.
        attestation: The record's :attr:`Provenance.attestation` as stored,
            projected whole (ADR-0189 §2) — what reported the belief and when that
            source said so — or ``None`` outside the ``ATTESTED`` band. **The
            listing carries it as well as the single-belief view**, and ADR-0107 §3
            is the precedent for that being one decision rather than two: it refused
            both "put the field on ``BeliefSummary`` only" and "put it on ``Belief``
            only" and required both DTOs to carry it under one name, because a
            listing row that answered less than the row it links to is the same
            projection defective in one place.
        rests_on_recorded_external_content: The value of
            :func:`rests_on_recorded_external_content` (ADR-0106 §2) applied to the
            record's :class:`Provenance`, computed by the engine at projection time.
            Never recomputed by a surface from ``band``, and never read off
            :attr:`Provenance.derived_from_external` in its place. See
            :class:`Warrant` for what the value does and does not claim.
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
        default=0, ge=0, description="How many citations the belief carries, resolved or not."
    )
    lost_evidence: int = Field(
        default=0, ge=0, description="How many of those citations no longer resolve."
    )
    valid_until: UtcInstant | None = Field(
        default=None, description="The end of the belief's validity window, where one is set."
    )
    evidence_elided: int = Field(
        default=0,
        ge=0,
        description=(
            "An upper bound on how many further citations stood behind it and are "
            "no longer carried, as stored (ADR-0107 §3)."
        ),
    )
    attestation: Attestation | None = Field(
        default=None,
        description=(
            "What reported this belief and when that source said so, as stored; "
            "``None`` outside the ``ATTESTED`` band (ADR-0189 §2)."
        ),
    )
    rests_on_recorded_external_content: bool = Field(
        default=False,
        description=(
            "Whether this belief's warrant rests on recorded external content — "
            "``rests_on_recorded_external_content(provenance)`` as the engine "
            "computed it (ADR-0106 §2, ADR-0189 §2)."
        ),
    )

    @model_validator(mode="after")
    def _lost_within_cited(self) -> BeliefSummary:
        """More citations cannot be gone than were ever made (ADR-0085 §4b).

        **The price of counts-as-fields.** On :class:`Belief` the two counts cannot
        disagree with the evidence because they are computed from it; moving them
        to fields buys the listing its shape at the cost of the one constraint the
        model must now assert for itself.

        **``evidence_elided`` is deliberately outside this rule, and no validator
        relates it to either count** (ADR-0107 §4). There is no true relation to
        assert: it counts displacements over the record's whole history, over a
        different population than the retained tuple and double-counting in the two
        cases ADR-0086 §4 names, so it may exceed ``evidence_count`` and may be
        non-zero while ``evidence_count`` is zero. Asserting one anyway would invent
        a *read-path* failure — the same argument :class:`Provenance` makes for
        refusing a ``max_length`` on ``evidence`` — turning a legitimately-held
        belief into an unconstructable DTO. This invariant is safe precisely because
        both of its counts are taken over one tuple at one instant.
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
        evidence_elided: :attr:`Provenance.evidence_elided` **as stored** — an
            upper bound on how many further citations stood behind the belief and
            are no longer carried. **A field and not a property**, unlike the two
            counts below: an elision counts citations ``evidence`` no longer
            contains, so no function of that tuple yields it (ADR-0107 §3). Carried
            on **every** band, never zeroed or clamped by band.
        attestation: The record's :attr:`Provenance.attestation` as stored,
            projected whole (ADR-0189 §2) — what reported the belief and when that
            source said so — or ``None`` outside the ``ATTESTED`` band. **Both
            halves or neither**: ADR-0073 §4's gate asks for the reporting source's
            identity *and* its report time, and ADR-0092 §2 made the half-answers
            unconstructable by carrying them as one value object, so splitting them
            here would reintroduce on the surface's side of the seam exactly the
            states that section closed on the record's.

            ``Attestation.extent`` rides along and nothing renders it, deliberately
            (ADR-0189 §2): splitting the object to leave one bounded optional value
            behind would mint a second, near-identical spelling of
            :class:`Attestation`.
        rests_on_recorded_external_content: The value of
            :func:`rests_on_recorded_external_content` (ADR-0106 §2) applied to the
            record's :class:`Provenance`, computed by the engine at projection time.
            The one fact nothing else on this projection supplies for a ``DERIVED``
            belief, and what #746 exists for: a structured marker a client can
            style, filter and order on, where before it could only pass through a
            sentence. Never recomputed by a surface from ``band``, and never read
            off :attr:`Provenance.derived_from_external` in its place — see
            :class:`Warrant` for what the value does and does not claim.
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
    evidence_elided: int = Field(
        default=0,
        ge=0,
        description=(
            "An upper bound on how many further citations stood behind it and are "
            "no longer carried, as stored (ADR-0107 §3)."
        ),
    )
    attestation: Attestation | None = Field(
        default=None,
        description=(
            "What reported this belief and when that source said so, as stored; "
            "``None`` outside the ``ATTESTED`` band (ADR-0189 §2)."
        ),
    )
    rests_on_recorded_external_content: bool = Field(
        default=False,
        description=(
            "Whether this belief's warrant rests on recorded external content — "
            "``rests_on_recorded_external_content(provenance)`` as the engine "
            "computed it (ADR-0106 §2, ADR-0189 §2)."
        ),
    )

    @property
    def evidence_count(self) -> int:
        """How many citations it **carries**, resolved or not.

        Its value is unchanged and every consumer of it is correct — the presented
        confidence is a function of how many *carried* citations resolved
        (ADR-0077 §6). What it is not is the whole of ADR-0073 §4's "how many stand
        behind it": after a displacement more stand behind the belief than it
        carries, and the pair with :attr:`evidence_elided` is what answers the floor
        (ADR-0107 §6).
        """
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
        state: What its devices are shown about the assistant (ADR-0293 §8): whether
            an activation started from it is running, and how the last one ended.
            Read with the conversation, as §8:1 has it, and never part of its
            transcript.
        devices: Its devices, ``device_id`` ascending (ADR-0293 §3:3) — the ends a
            device catching up from a snapshot has no change to learn from.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The conversation's id.")
    started_at: UtcInstant = Field(description="When it began.")
    last_turn_at: UtcInstant | None = Field(
        description="When a turn was last recorded, or ``None`` if none ever was."
    )
    recorded_turns: int = Field(ge=0, description="How many turns its index holds.")
    state: ConversationState = Field(
        default_factory=ConversationState,
        description="What its devices are shown about the assistant (ADR-0293 §8).",
    )
    devices: tuple[ChatDevice, ...] = Field(
        default=(),
        max_length=CHAT_DEVICES_MAX,
        description="Its devices, device_id ascending (ADR-0293 §3:3).",
    )


"""The arms a routed listing may take (ADR-0197 §8).

Homogeneous tuples of types the promoted surface **already carries**, and this alias
mints no payload type of its own. That is what keeps a widening under
:class:`RoutableOperation`'s own rule cheap: a new read-only member adds an enum
member and, at most, one arm — not a wrapper model, a schema and a renderer — and a
client rendering a routed ``recent_reads`` uses the renderer it already has for
``recent_reads``.

**:class:`RoutableOperation` is the discriminator, never pydantic's structural union
resolution.** A lane reads the arm off ``operation``; an implementation that infers
it from the value's shape does not conform, because an **empty** tuple is a legal
value of every arm and the shape therefore decides nothing on exactly the case a
listing is most likely to take. :func:`routed_listing_arm` is that mapping, and the
validators below are what make the claim checkable rather than asserted.

**A wrapper model per operation was weighed and declined** (ADR-0197, Alternatives):
eight wrapper models now and one per widening later, each with a schema, a docstring
and a test, to carry a discriminator :attr:`RoutedOperation.operation` already
carries.
"""


# --- what a turn did instead of driving, when a store refused its claim (ADR-0261 §7)


class GrantableSource(BaseModel):
    """One source a user may grant, and what is currently true of it (ADR-0102 §3).

    What ``AssistantEngine.grantable_sources`` returns one of per held reader, so a
    client "offers a choice among declared identities rather than a free-text field"
    (ADR-0097 §9). Three fields and no fourth.

    **:attr:`live` is computed hub-side, from the store, and no client may derive a
    grant's liveness from ``recent_grants``** (§3). The derivation is *unsound*
    rather than merely redundant: ADR-0097 §4 derives liveness from the ``revokes``
    relation alone and never refuses a revocation for its timestamp, "including one
    that predates the grant it revokes". ``recent`` orders newest-first by
    ``decided_at``, so after a clock correction a revoking record can sort *below*
    the grant it revokes and fall outside a page that contains it — and a client
    walking that page would report a withdrawn grant as live, on the one question
    this contract exists to get right, only on the deployment where a clock moved.

    **A fourth field was considered and refused.** An earlier draft carried
    ``grantable: bool`` so a reader whose declared name is inadmissible (§4) could
    be listed as unavailable rather than absent. It is surface with no consumer —
    the refusal ADR-0045 §1, ADR-0028 §7 and ADR-0092 §10 each made: a
    non-admissible declared name is a defect in a reader, not a state a user can act
    on, and every user-visible consequence is already carried by the enumeration
    omitting it and by §4's refusal naming it. The diagnosis goes to the operator
    log, where ADR-0097 §8's refusal line already goes.

    **The closure stays closed** (ADR-0085 §5). Walking the declared field types:
    :data:`Identifier` and :data:`EncodableText` are `core` aliases, and
    :class:`SourceGrant` is a `core` model whose own fields reach
    :data:`DurableIdentifier`, :data:`Identifier`, :class:`GrantScope` and
    :data:`UtcInstant` — all `core`. Nothing new leaves `core` and ``lint-imports``
    sees no new edge.

    Attributes:
        source: The reader's declared identity, and the only value ``grant`` admits
            for this source (§4). :data:`Identifier` rather than
            :data:`NonBlankEncodableText` because this is constructed **hub-side**
            from a name §4 has already required to equal its own ``str.strip()``, so
            the normalising validator is a no-op on every value that can reach it —
            unlike ``grant``'s *argument*, where normalising one layer below the
            comparison is what ADR-0102 §2 refuses.
        location: The source's current configured location, or ``None``. **This
            field is the only place in the system that carries it** (§6): it is
            computed per call, never written to a :class:`SourceGrant`, never
            returned by ``recent_grants``, never written to a log record and never
            persisted. ``None`` means the source has **no** configured location at
            all — a location that exists and cannot be encoded makes the source
            ungrantable rather than making this ``None``, because the alternative
            offers a source no conforming client may grant (§6).
        live: The grant covering this source at the moment the response was
            computed, or ``None``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Identifier = Field(
        description=(
            "The reader's declared identity — the value "
            ":attr:`~ai_assistant.core.protocols.Reader.name` returns, and the only "
            "value ``grant`` admits for this source (ADR-0102 §4)."
        )
    )
    location: EncodableText | None = Field(
        default=None,
        description=(
            "Where this source currently reads from, for the user to see before "
            "they grant, and ``None`` only where nothing is configured. Held by no "
            "durable record anywhere (ADR-0097 §9a, ADR-0102 §6)."
        ),
    )
    live: SourceGrant | None = Field(
        default=None,
        description=(
            "The grant covering this source when the response was computed, or "
            "``None``. Computed hub-side from the store; never derived by a client "
            "from ``recent_grants`` (ADR-0102 §3)."
        ),
    )


# --- evaluation: the Tier 2 trace family (ADR-0119) --------------------------
# One envelope, four closed enumerations, and numbers keyed by constants. The
# whole shape falls out of ADR-0004 §1: everything a trace is *about* is Tier 1,
# so a trace **references** it — ids, counts, scores, durations — and never
# contains it. §2 makes that a property of the type rather than a review
# checklist: every string reachable from an `EvaluationTrace` is an identifier,
# an enum member, a literal the emitting module wrote, or an exception's
# `__name__`, and nothing else can be spelled. `tests/core/test_trace_string_
# closure.py` walks the graph and proves the closure holds.


#: ``fullmatch``, never ``match``: ``$`` also matches *before* a trailing
#: newline, so ``match(r"^[a-z]+$", "seam\n")`` succeeds and the bound these
#: patterns exist to impose would not hold.
_TRACE_LABEL = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FAULT_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _trace_label(value: str) -> str:
    """A seam name or metric key: lowercase, bounded, a literal in its module (§2).

    Args:
        value: The candidate label.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If it does not match the label pattern.
    """
    if not _TRACE_LABEL.fullmatch(value):
        msg = f"{value!r} is not a trace label"
        raise ValueError(msg)
    return value


#: What ``fault_class`` carries when an exception's own ``__name__`` will not fit
#: the pattern — a dynamically built class, an over-long or non-ASCII name
#: (ADR-0119 §3).
UNREPRESENTABLE_FAULT_CLASS: Final = "UnrepresentableFaultClass"


def _fault_class_name(value: str) -> str:
    """An exception class's ``__name__`` — never its message (ADR-0119 §2).

    Args:
        value: The candidate class name.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If it does not match the class-name pattern.
    """
    if not _FAULT_CLASS.fullmatch(value):
        msg = f"{value!r} is not an exception class name"
        raise ValueError(msg)
    return value


def fault_class_of(error: Exception) -> str:
    """``type(error).__name__``, or the reserved literal when it will not fit.

    The one string on a trace that is neither a literal nor an enum member and
    is *not* under the emitter's control: a provider may raise
    ``type("X" * 65, (Exception,), {})``, and nothing stops a dynamic class name
    from carrying content. So the conversion is total — an unrepresentable name
    becomes :data:`UNREPRESENTABLE_FAULT_CLASS` — rather than raising and
    destroying the very trace ADR-0119 §8 requires (§3).

    The rejected name is **dropped here and goes nowhere**, log included: it was
    refused precisely because it may carry Tier 1 content, and ADR-0004 §5 rules
    that logs are Tier 2 only.

    **Reading the name is itself guarded**, because "total" has to mean it: a
    metaclass may override ``__getattribute__`` for ``"__name__"`` and raise, or
    return something that is not a ``str``, and either would take the trace down
    with the fault it was recording. The guard catches ``Exception`` and not
    ``BaseException``, so a ``CancelledError`` raised *by the name read* is
    delivered onward as ADR-0060 §1 requires.

    **The parameter is ``Exception``, not ``BaseException``**, for the same rule
    one level out: a cancellation is not a fault and must never be classified as
    one. An emitter re-raises it before it reaches here, so no ``FAULT`` trace
    can ever name it.

    Args:
        error: The exception whose class decided the outcome.

    Returns:
        The class name, or :data:`UNREPRESENTABLE_FAULT_CLASS`.
    """
    try:
        name = type(error).__name__
        representable = isinstance(name, str) and bool(_FAULT_CLASS.fullmatch(name))
    # A blind `except Exception` on purpose — see the docstring. `BaseException`
    # is deliberately *not* caught, so a `CancelledError` raised by the name read
    # is delivered onward (ADR-0060 §1). ADR-0119 §13a spells this line with a
    # `noqa: BLE001`; this tree does not enable `BLE`, and `RUF100` fails the
    # gate on the unused directive, so the reason stays as a comment.
    except Exception:
        return UNREPRESENTABLE_FAULT_CLASS
    return name if representable else UNREPRESENTABLE_FAULT_CLASS


_TRACE_ID = re.compile(r"[0-9a-f]{32}")


def _trace_id(value: str) -> str:
    """A trace's own id: the hex form of a random UUID, and nothing else (§3).

    Args:
        value: The candidate id.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If it is not 32 lowercase hex characters.
    """
    if not _TRACE_ID.fullmatch(value):
        msg = f"{value!r} is not a minted trace id"
        raise ValueError(msg)
    return value


def _finite(value: int | float | bool) -> int | float | bool:
    """Refuse ``NaN`` and the infinities (ADR-0119 §3).

    Args:
        value: The observed quantity.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If it is a non-finite float.
    """
    if isinstance(value, float) and not isfinite(value):
        msg = f"{value!r} has no JSON representation, so it cannot be stored"
        raise ValueError(msg)
    return value


class FrozenMapping[K: Hashable, V: Hashable](Mapping[K, V]):
    """An immutable, hashable, copyable mapping — :class:`FrozenDict`, generic.

    Every design point is ``FrozenDict``'s and is taken for its stated reasons.
    ``MappingProxyType`` is refused because it "can be neither pickled nor
    deep-copied, which would make any model holding one fail
    ``model_copy(deep=True)``". The contents are a **tuple of pairs**, never a
    ``dict``, because "a private ``dict`` would still be a mutable object
    reachable as ``parameters._data``, which is a real bypass".

    **Both parameters are bound to ``Hashable``**, because ``__hash__`` is part
    of what this type promises and ``FrozenDict`` can only promise it for the
    reason its own docstring gives — hashing by contents is "possible only
    because every value is itself frozen". Unbounded,
    ``FrozenMapping[str, list[int]]`` would construct happily and raise at
    ``hash(...)``, making the guarantee false everywhere but the fields that
    happen to be safe. The bound is satisfied by all three trace mappings:
    :class:`TraceRef` and :class:`TraceRecordSet` are ``StrEnum``,
    :data:`Identifier` and :data:`TraceLabel` are ``str``,
    :data:`TraceMetricValue` is ``int | float | bool``, and :class:`RecordIdSet`
    is a frozen model.

    ``FrozenDict`` is left exactly as it is; folding the two together is #849.
    """

    __slots__ = ("_items",)

    _items: tuple[tuple[K, V], ...]

    def __init__(self, data: Mapping[K, V] | None = None, /) -> None:
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

    def __getitem__(self, key: K) -> V:
        """Return the value for ``key``, raising ``KeyError`` if absent."""
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[K]:
        """Iterate over the keys, in insertion order."""
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        """Return the number of keys."""
        return len(self._items)

    def __repr__(self) -> str:
        """Return a dict-like representation of the contents."""
        return f"{type(self).__name__}({dict(self._items)!r})"

    def __eq__(self, other: object) -> bool:
        """Compare equal to any mapping with the same contents."""
        if isinstance(other, Mapping):
            return dict(self._items) == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        """Hash by contents; possible only because every value is itself frozen."""
        return hash(frozenset(self._items))

    def __reduce__(self) -> tuple[type[FrozenMapping[K, V]], tuple[dict[K, V]]]:
        """Support pickling (and, via it, ``copy.deepcopy``)."""
        return (type(self), (dict(self._items),))


def _frozen_mapping[K: Hashable, V: Hashable](value: Mapping[K, V]) -> FrozenMapping[K, V]:
    """Detach and freeze — the model owns a copy no caller can reach.

    ``frozen=True`` refuses ``trace.metrics = ...`` and not
    ``trace.metrics["k"] = ...``; ADR-0018 §3's rule is about the second.

    Args:
        value: The validated mapping pydantic produced.

    Returns:
        An immutable, hashable copy of it.
    """
    return FrozenMapping(value)


def _thaw_mapping(value: Mapping[Any, Any]) -> dict[Any, Any]:
    """Convert a frozen trace mapping back to a plain ``dict`` for serialisation.

    The mirror of :func:`_thaw_json`, and needed for the same mechanical reason:
    pydantic-core serialises a ``dict`` and does not know how to write a
    :class:`FrozenMapping`, so a trace holding one could not reach the store at
    all. The frozen form is how the value is *held*; a plain mapping is how it is
    *written*.

    ADR-0119 §13a elides this along with the imports, but the store §13d ratifies
    cannot round-trip a trace without it — and this is the shape
    :data:`FrozenJsonMapping` already uses for exactly this problem.

    Args:
        value: The frozen mapping a trace field holds.

    Returns:
        A plain ``dict`` with the same pairs; pydantic then serialises each value
        in the ordinary way.
    """
    return dict(value)


type TraceId = Annotated[EncodableText, AfterValidator(_trace_id)]
type TraceLabel = Annotated[EncodableText, AfterValidator(_trace_label)]
type FaultClassName = Annotated[EncodableText, AfterValidator(_fault_class_name)]
type TraceMetricValue = Annotated[int | float | bool, AfterValidator(_finite)]

#: The per-set ceiling on ids a trace stores (ADR-0119 §3).
TRACE_RECORD_SET_CAP: Final = 256


class TraceKind(StrEnum):
    """What kind of event a trace records (ADR-0119 §3, ADR-0141 §2).

    Exactly five members, and §13e makes a sixth an ADR's to add: these are the
    axis along which the tier discipline is stated, so membership is contract.
    ``NOTIFICATION`` is that clause's first exercise — ADR-0141 §2 adds it,
    ratified ahead of any emitter, because a notification ruling happens many
    times *within* one engine call rather than once per call, so recording it as
    an ``OPERATION`` would break ADR-0120 §3's one-trace-per-correlation
    attribution rather than merely read oddly.
    """

    OPERATION = "operation"
    RETRIEVAL = "retrieval"
    MEMORY_WRITE = "memory_write"
    CONFIGURATION = "configuration"
    NOTIFICATION = "notification"


class TraceOutcome(StrEnum):
    """How the traced crossing of a seam ended (ADR-0119 §3).

    ``REFUSED`` and ``FAULT`` are drawn from the exception's **class** and never
    from its message text — the same discriminator ADR-0111 §9 binds the
    scheduler's log record to, so the two records about one event cannot
    disagree. ``INCOMPLETE`` is ADR-0111 §9's third clause given a value: a run
    that halted without exhausting its work is neither a success nor a failure.
    """

    OK = "ok"
    REFUSED = "refused"
    FAULT = "fault"
    INCOMPLETE = "incomplete"


class TraceRef(StrEnum):
    """Singular relations: at most one id each."""

    CORRELATION = "correlation"
    CONVERSATION = "conversation"
    TURN = "turn"
    EXECUTION = "execution"


class TraceRecordSet(StrEnum):
    """Plural id sets, each naming the disposition its ids had."""

    RETURNED = "returned"
    WRITTEN = "written"
    REINFORCED = "reinforced"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class RecordIdSet(BaseModel):
    """Ids the operation produced under one disposition, and how many there were.

    Truncated exactly when ``total`` exceeds ``len(ids)`` — equivalently, when it
    exceeds :data:`TRACE_RECORD_SET_CAP` — so there is no separate flag to
    disagree with.

    Attributes:
        ids: The ids, in the order the observed operation produced them, each at
            most once, capped at :data:`TRACE_RECORD_SET_CAP`.
        total: How many the operation actually produced, cap or no cap.
    """

    model_config = ConfigDict(frozen=True)

    ids: tuple[Identifier, ...] = Field(max_length=TRACE_RECORD_SET_CAP)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def _ids_are_a_set_and_are_the_total_up_to_the_cap(self) -> RecordIdSet:
        """Distinct ids, and every one produced, dropping only at the cap.

        Duplicates are refused **first**, because the length invariant cannot see
        them: ``ids=("a", "a"), total=2`` satisfies it while double-counting one
        record and crowding out a real one at the cap.

        ``len(ids) == min(total, CAP)`` is then the whole of the rest, and it is
        tighter than ``total >= len(ids)`` in the direction that matters: the
        looser form admits ``ids=(), total=1``, which reports a truncation
        ADR-0119 §3 reserves for cap overflow and would have a measure exclude a
        trace that lost nothing.

        Returns:
            ``self``, unchanged.

        Raises:
            ValueError: If an id repeats, or if the count does not match.
        """
        if len(set(self.ids)) != len(self.ids):
            msg = "a record id set carries each id at most once"
            raise ValueError(msg)
        expected = min(self.total, TRACE_RECORD_SET_CAP)
        if len(self.ids) != expected:
            msg = f"a total of {self.total} carries {expected} ids, not {len(self.ids)}"
            raise ValueError(msg)
        return self


type TraceRefs = Annotated[
    Mapping[TraceRef, Identifier], AfterValidator(_frozen_mapping), PlainSerializer(_thaw_mapping)
]
type TraceRecords = Annotated[
    Mapping[TraceRecordSet, RecordIdSet],
    AfterValidator(_frozen_mapping),
    PlainSerializer(_thaw_mapping),
]
type TraceMetrics = Annotated[
    Mapping[TraceLabel, TraceMetricValue],
    AfterValidator(_frozen_mapping),
    PlainSerializer(_thaw_mapping),
]


class EvaluationTrace(BaseModel):
    """One event at one seam: what happened, when, how it ended, what it was about.

    **Tier 2 under ADR-0004 §1, at every depth** (ADR-0119 §2). It references
    Tier 0/1 content and never contains it: every string reachable from here is
    an identifier minted by this system, a member of an enumeration in this
    module, a literal constant written in the emitting module, or an exception
    class's ``__name__``. Every other observation is a number or a boolean —
    there is no free-text field, no serialised payload and no open-value-type
    mapping anywhere in the family.

    **It is not a measurement** (§1). No trace carries a rate, ratio, average or
    threshold verdict over more than the one event it records; a measure is a
    query over the stream, computed where its denominator can be stated.

    **Frozen at both levels.** ``ConfigDict(frozen=True)`` refuses
    ``trace.metrics = …`` and not ``trace.metrics["k"] = …``, and the second is
    the one that matters: a caller mutating a validated trace's ``metrics`` in
    place could put a free-form string past §2's containment rule *after*
    validation ran. So each mapping field detaches into a copy the model owns and
    exposes as an immutable view (ADR-0018 §3).

    Attributes:
        id: The trace's own id, **minted by the type** — 32 lowercase hex
            characters of a random UUID, so no caller can supply one from data
            (§3). A store hydrating a row that carries no readable id raises
            :class:`~ai_assistant.core.errors.TraceStoreError` rather than
            letting this default stand in for the id the row was supposed to
            have.
        kind: Which kind of event this is.
        seam: Where it happened, as a literal label the emitting module wrote.
        occurred_at: When it happened, stamped by the **emitter** from the
            ``Clock`` it already holds — never by the store on append, which
            would measure the write rather than the event.
        elapsed: How long it took, or ``None`` where no duration was observed.
        outcome: How it ended.
        fault_class: The exception class that decided a ``REFUSED`` or ``FAULT``
            outcome, present exactly when one did, and never its message.
        refs: Singular relations this trace is about, by :class:`TraceRef`.
        records: Plural id sets, each under the disposition its ids had. An
            **absent** key means that set was not observed; a key present with an
            empty :class:`RecordIdSet` means it was observed and was empty.
        metrics: Numbers and booleans this event observed, keyed by literal
            constants. A key appears only when the quantity it names was
            observed: an absent key means *not observed*, never zero.
    """

    #: ``validate_default`` because pydantic skips defaults otherwise, and an
    #: unvalidated ``{}`` is a *mutable* mapping ``frozen=True`` does not protect.
    model_config = ConfigDict(frozen=True, validate_default=True)

    id: TraceId = Field(default_factory=lambda: uuid4().hex)
    kind: TraceKind
    seam: TraceLabel
    occurred_at: UtcInstant  # emitter-stamped, from its Clock (§3)
    elapsed: timedelta | None = Field(default=None, ge=timedelta(0))
    outcome: TraceOutcome
    fault_class: FaultClassName | None = None
    refs: TraceRefs = Field(default_factory=dict)
    records: TraceRecords = Field(default_factory=dict)
    metrics: TraceMetrics = Field(default_factory=dict)

    @model_validator(mode="after")
    def _a_fault_class_accompanies_a_failure(self) -> EvaluationTrace:
        """``fault_class`` is present exactly when an exception decided the outcome.

        ``REFUSED`` and ``FAULT`` are drawn *from* an exception's class (§3), so
        one without a class names no discriminator; ``OK`` and ``INCOMPLETE``
        reached no exception, so one with a class reports a failure that did not
        happen.

        Returns:
            ``self``, unchanged.

        Raises:
            ValueError: If the outcome and the fault class disagree.
        """
        failed = self.outcome in (TraceOutcome.REFUSED, TraceOutcome.FAULT)
        if failed != (self.fault_class is not None):
            msg = f"outcome {self.outcome} and fault_class {self.fault_class!r} disagree"
            raise ValueError(msg)
        return self


# --- evaluation: the trace walk's position and its chunk (ADR-0119 §7a) ------
# Beside :class:`WalkPosition` and :class:`RecordChunk` above, and a *separate*
# type from them rather than a reuse: a key issued by one store is meaningless
# in another, and a shared type is an invitation to hand a memory walk's
# position to the trace store and be answered rather than refused. They live
# here rather than in `core/protocols.py`, where ADR-0119 §13b's second code
# block prints them, because that module declares Protocols and no pydantic
# models — every model those Protocols exchange is defined in this one, the two
# ADR-0114 analogues above included.


class TracePosition(BaseModel):
    """How far a walk over the trace store has reached (ADR-0119 §7a).

    Opaque to its caller: no caller parses, orders, compares, derives or
    synthesises one, and the only admissible source is the :class:`TraceChunk`
    that carried it (ADR-0114 §2). The token is the store's own order key — a
    ``rowid`` in a SQLite store, an insertion index elsewhere.

    A **bound, not a reference**: ADR-0119 §10's purge deleting traces below a
    held position does not disturb it, because the store never reissues a key.
    The store issues a floor position for a walk that has seen nothing, so there
    is no state in which a caller holds none (§7a).

    Attributes:
        token: The store's opaque encoding of this position.
    """

    model_config = ConfigDict(frozen=True)

    token: NonBlankEncodableText = Field(
        description="The store's opaque encoding of this position. Never parsed by a caller.",
    )


class TraceChunk(BaseModel):
    """One chunk of a walk over the trace store, and where it reached (§7a).

    Attributes:
        traces: The traces this chunk returned, in the store's total insertion
            order.
        position: Always present — after the last trace returned, or the
            resumed-from position when ``traces`` is empty. A chunk shorter than
            the requested bound means "nothing further yet", never "this walk is
            over".
    """

    model_config = ConfigDict(frozen=True)

    traces: tuple[EvaluationTrace, ...]
    position: TracePosition


# --- secrets: what names a keyring entry, and what one holds (ADR-0125) ------
# The three types the two keyring Protocols exchange. They sit in `core` for the
# ordinary reason (ADR-0068 §1: boundary-crossing types) and are declared last
# because they depend on the scalar refinements above and on nothing else here.
#
# The concrete keyring-backed implementation is a later lane's, in a leaf package
# no subsystem imports (ADR-0125 §8). Nothing below reaches a keyring, or knows
# that one exists.


class SecretScope(StrEnum):
    """Which kind of Tier 0 secret an entry holds (ADR-0125 §2).

    **Closed at three members, and the closure is the mechanism rather than a
    limit nobody got round to raising.** ADR-0004 §3's discipline — one
    contracted path to the keyring, not a bespoke one per layer — was a sentence
    a lane could overlook for as long as it stayed prose. As an enum it is a
    question that has to be answered at the point a subsystem holds a secret: if
    none of these three fits, the mechanical answer is the ratified one, which is
    that a fourth member is `core` surface and owes its own ADR (ADR-0125 §2,
    §10). ADR-0004 §4's application-level encryption key is the standing example
    — held in the OS keyring by a ratified clause, covered by no member here.

    An instance of :class:`~ai_assistant.core.protocols.Secrets` is bound to
    exactly one of these, so the member is a property of the object a consumer
    holds rather than a rule the consumer is trusted to follow (§2, §8).
    """

    PROVIDER = "provider"
    """A model provider credential, read on the way to a completion."""

    INTEGRATION = "integration"
    """A tool's credential for the external service it integrates."""

    ENROLMENT = "enrolment"
    """The device credential, and the enrolled hub identity beside it (ADR-0124 §6)."""


#: The longest a :attr:`SecretName.key` may be. Bounded so a name composes into
#: a backend coordinate every mainstream keyring accepts, rather than into one
#: that stores on the developer's platform and fails on the owner's.
SECRET_KEY_MAX_LENGTH: Final = 64

#: The characters a key may contain: lowercase ASCII letters, digits, and the
#: three joining punctuation marks that no keyring backend treats specially.
_SECRET_KEY_CHARACTERS: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

#: The characters a key may begin and end with — no leading or trailing
#: punctuation, so a key is never mistaken for a fragment of a composed one.
_SECRET_KEY_EDGES: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def _secret_key(value: str) -> str:
    """Require ADR-0125 §2's key grammar, returning the key unchanged.

    One to sixty-four characters drawn from lowercase ASCII letters, digits,
    ``.``, ``_`` and ``-``, beginning and ending with a letter or a digit. No
    uppercase, no whitespace, no control character, no non-ASCII character, no
    ``:`` and no ``/``.

    **This is a portability rule and every exclusion earns its place.** The
    concrete implementation composes the backend's own coordinates out of an
    installation namespace, the scope and the key, and that composition must be
    injective — two distinct :class:`SecretName` values that collide on the
    backend are one secret silently overwriting another. Two things break
    injectivity. A component containing the joining character, which is why
    ``:`` and ``/`` are refused rather than discouraged. And case, which is the
    subtler one: at least one mainstream backend matches its target names
    case-insensitively, so ``github`` and ``GitHub`` would be one entry there and
    two elsewhere — a credential stored on Linux that cannot be found on Windows,
    or worse, that finds a different one.

    **Refused, never normalised.** Case-folding a key here would produce exactly
    the collision the rule exists to prevent, silently, at the one layer that
    could still have reported it (ADR-0096 §2's rule: a tightening may reject,
    and may not rewrite).

    **The message echoes the key**, which is safe and is meant to be: a
    ``SecretName`` is not a secret and may be logged, carried in an error and
    shown to the owner (ADR-0125 §2). A caller may therefore never encode a
    secret value into a key, and that prohibition is what makes this echo safe.

    Raises:
        ValueError: If the value is not a key under ADR-0125 §2's grammar.
    """
    described = describe_untrusted(value)
    if not 1 <= len(value) <= SECRET_KEY_MAX_LENGTH:
        msg = (
            f"a secret key must be 1 to {SECRET_KEY_MAX_LENGTH} characters, "
            f"got {len(value)}: {described}"
        )
        raise ValueError(msg)
    if not _SECRET_KEY_CHARACTERS.issuperset(value):
        msg = (
            "a secret key must be lowercase ASCII letters, digits, '.', '_' or '-', "
            f"so that it composes into a backend coordinate injectively; got {described}"
        )
        raise ValueError(msg)
    if value[0] not in _SECRET_KEY_EDGES or value[-1] not in _SECRET_KEY_EDGES:
        msg = f"a secret key must begin and end with a letter or a digit, got {described}"
        raise ValueError(msg)
    return value


type _SecretKey = Annotated[EncodableText, AfterValidator(_secret_key)]
"""The bounded token half of a :class:`SecretName` (ADR-0125 §2).

**Private, deliberately.** ADR-0125 decides three types in this module, and this
is not one of them: it is the field's annotation, and a caller builds a
:class:`SecretName` rather than a key. Layered on :data:`EncodableText` like
every other ``str`` refinement here, even though :func:`_secret_key` already
refuses everything that alias would — see that alias's note on why no ``str``
field in this module opts out.
"""


class SecretName(BaseModel):
    """Which entry, inside one installation's keyring (ADR-0125 §2).

    Two names address the same entry when and only when both fields are equal.
    The installation is **not** here and is bound to the object a consumer holds
    instead (§2), which is what keeps a caller from naming another
    installation's entries: a second data directory on one machine would
    otherwise overwrite the first's credential at enrolment and delete it at
    unenrolment, a data loss produced by a namespace nobody chose.

    **A name is not a secret.** It may be logged, held in a Tier 1 store, carried
    in an error and shown to the owner — diagnosing "the keyring has no entry for
    this" requires saying which entry. The permission and its prohibition are one
    rule: because a name is disclosable, **a caller may never encode a secret
    value into a key**. What makes the permission safe is that the name is chosen
    by the code and not by the secret.

    **Revalidated at every seam method** rather than trusted (ADR-0125 §4).
    ``model_construct`` is public and yields a well-typed object carrying a key
    §2 forbids, so ``revalidate_instances`` is set to ``"always"`` here: an
    implementation revalidates the object **as a whole**, before reading any
    attribute of it, and the model itself is what makes that one call.

    Attributes:
        scope: Which kind of secret this is, and — since an instance is bound to
            one scope — which instance may address it at all.
        key: The entry's name inside that scope, under §2's grammar.
    """

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    scope: SecretScope = Field(description="Which kind of secret this entry holds.")
    key: _SecretKey = Field(description="The entry's name within its scope. Never a secret value.")


#: The most a secret's plaintext may encode to, in UTF-8 bytes (ADR-0125 §3).
#:
#: **The arithmetic is the reason.** The tightest limit among the backends a
#: cross-platform keyring selects is a credential blob of a few kilobytes stored
#: UTF-16, where a character of value costs two bytes of storage. A UTF-8 budget
#: of 1024 converts to at most 2048 UTF-16 bytes — a character costing k UTF-8
#: bytes costs at most 2 when k <= 3 and exactly 4 when k = 4, so twice the UTF-8
#: budget bounds it in every case — which clears every mainstream backend with
#: margin. Above it, a value stores on one platform and fails on another, and the
#: failure arrives on the owner's machine rather than in CI.
#:
#: Every credential this system holds or plans to hold sits far below it:
#: ADR-0124 §6's is 128 bits of ``urandom`` in an encoded form of a few tens of
#: bytes, a provider API key is around a hundred, an OAuth refresh token a few
#: hundred. A scheme that does not fit is refused here rather than discovered
#: later, and raising the bound is an amendment somebody argues for.
SECRET_VALUE_MAX_BYTES: Final = 1024


def secret_value(value: SecretStr) -> SecretStr:
    r"""Validate a secret's plaintext, returning the value unchanged (ADR-0125 §3).

    Non-blank, UTF-8 encodable, and at most :data:`SECRET_VALUE_MAX_BYTES` bytes
    once encoded — :data:`NonBlankEncodableText`'s obligations, including that
    type's refusal to *normalise* what it accepts, plus the byte bound. **The
    value is returned byte-for-byte**: two spellings of a secret are two
    different secrets, and a store that helpfully stripped a trailing newline
    would produce an authentication failure nobody could reproduce by inspection.

    **This callable is the only supported way to build one**, and it is not
    decoration. :data:`SecretValue` is an ``Annotated`` alias, which is a *field*
    annotation: pydantic runs its ``AfterValidator`` when a model carrying the
    field is validated, and constructing the origin directly — ``SecretStr("")``,
    or a 2 KB one — satisfies every static check while the validator never runs.
    So a seam revalidates through this function rather than trusting the
    annotation (ADR-0125 §4), exactly as
    :class:`~ai_assistant.core.errors.AssistantError` calls
    :func:`encodable_text` instead of trusting :data:`EncodableText`.

    **The checks are ordered, and the order is load-bearing.** Encodability comes
    first because measuring an unencodable ``str`` *is* encoding it: a budget
    check written as ``len(text.encode())`` over ``"\ud800"`` raises
    ``UnicodeEncodeError`` rather than the ``ValueError`` this contract promises,
    and the surrogate is the case that survives every other check — non-blank,
    one character, and with no byte length at all (ADR-0087 §2b).

    **No message here names the value, any part of it, or its length.** ADR-0125
    §6 forbids a prefix, a suffix, a truncation, a digest *or a length* in any
    exception this seam raises, and a refusal is the likeliest leak of the two:
    "secret length is 1025" is what a size check naturally reports, and it hands
    over a derivation from the seam's own code rather than from a backend it was
    wrapping. The bound is a constant and may be named; the rejected value's
    measurement may not.

    Args:
        value: The secret to validate, still wrapped in its redacting holder.

    Returns:
        The same value, unchanged and unnormalised.

    Raises:
        ValueError: If the plaintext is blank, has no UTF-8 encoding, or encodes
            to more than :data:`SECRET_VALUE_MAX_BYTES` bytes.
    """
    plaintext = value.get_secret_value()
    if not _is_encodable(plaintext):
        msg = "a secret value must have a UTF-8 encoding, so a keyring backend can store it"
        raise ValueError(msg)
    if not plaintext.strip():
        msg = "a secret value must not be blank"
        raise ValueError(msg)
    if len(plaintext.encode("utf-8")) > SECRET_VALUE_MAX_BYTES:
        msg = f"a secret value must encode to at most {SECRET_VALUE_MAX_BYTES} UTF-8 bytes"
        raise ValueError(msg)
    return value


type SecretValue = Annotated[SecretStr, AfterValidator(secret_value)]
"""A Tier 0 secret's plaintext, bounded and self-redacting (ADR-0125 §3).

Built on :class:`pydantic.SecretStr`, so its ``repr`` and its ``str`` disclose no
part of the plaintext and the plaintext is reached only through that class's own
accessor, ``get_secret_value``. No implementation may define a value type whose
default rendering is the secret, and no lane may reimplement the redaction or the
accessor under another name.

**The redacting type is the mechanism, not a convenience.** ``core/logging.py``
redacts by *key name*, and ADR-0124 §6 leans on exactly that when it requires an
implementation not to "give it a name that redaction misses". A plain ``str``
keeps that promise only for as long as every call site chooses a covered key, and
the whole history of credential leaks is call sites that did not. A type whose
default rendering is ``**********`` inverts the default: a disclosure requires
somebody to write the unwrapping call, which makes it deliberate and reviewable
rather than accidental. The claim is exactly that and no more — an unwrapped
value can still be logged, and this type does not pretend otherwise. ADR-0124 §7
is where the one authorised unwrap lives: the client unwraps immediately before
encoding the connect frame's credential member, and nowhere else.

**Both spellings are real, and :func:`secret_value` is the second one.** A model
field annotated with this alias validates through pydantic; a hand-built value
validates through the callable. That is :data:`EncodableText`'s arrangement with
:func:`encodable_text`, taken deliberately.
"""


# ---------------------------------------------------------------------------
# Proactive notification (ADR-0130)
# ---------------------------------------------------------------------------
# The propose/dispose chassis reaches the other end of the system here. Every
# artifact below is a *proposal* or a *ruling on one*: producing a candidate
# reaches nobody (§1), and holding one confers no authority to contact anyone.
#
# **No type here carries delivery state.** ADR-0078 §8 refused to put "was it
# sent? seen?" on a memory decision, and §2 keeps that refusal rather than
# reversing it: whether contact was attempted, reached a device, or was seen is
# not a field of a candidate, a disposition or a held record, and no clause may
# be read as placing one there. What this block mints is the record a delivery
# seam attaches to.


class NotificationReach(StrEnum):
    """How far a notification class may reach the user (ADR-0130 §6).

    The one standing setting that is *per class*, and the only one whose lowest
    value stops a candidate before any other condition is weighed.
    """

    OFF = "off"
    """Never tell me this. A candidate of this class is dropped (§5)."""

    HOLD = "hold"
    """Hold it for the user's next arrival. **The shipped default for every
    class**, including one no preference names (§6), which is why a producer
    cannot interrupt on the day it ships."""

    INTERRUPT = "interrupt"
    """Reach me at the earliest instant a channel permits, if the candidate also
    satisfies every other condition of §5."""


class NotificationDispositionKind(StrEnum):
    """What a ruling decided (ADR-0130 §5).

    Exactly three, and there is deliberately no fourth for "tell them later at
    instant X": ``HOLD`` with a ``reconsider_at`` covers it with one field and
    keeps every disposition a statement about *now* (§11).
    """

    INTERRUPT = "interrupt"
    """Reach the user at the earliest instant a channel permits. **It is not an
    assertion that a channel exists, and it binds no transport** (§5)."""

    HOLD = "hold"
    """Withhold the interruption, not the notification: a held record is
    readable through §7's enumeration. The outcome whenever no clause of §5
    selects another."""

    DROP = "drop"
    """Rule it out. On an offer this writes no durable record (§8); on a
    reconsideration it is recorded and the record ceases to be actionable."""


class NotificationCondition(StrEnum):
    """One condition §5 weighs, named so a ruling can be explained (ADR-0130 §5).

    **Every disposition names one of these**, which is what makes "why did you
    tell me that?" and "why didn't you?" answerable without a model in the loop.
    The members fall into two groups that never mix: :data:`DROP_CONDITIONS` are
    the four evaluated first, each yielding ``DROP`` naming itself, and
    :data:`INTERRUPT_CONDITIONS` are the four that must **all** hold for
    ``INTERRUPT``.
    """

    EXPIRED = "expired"
    """The candidate declares an expiry not later than the ruling instant. A
    candidate that has already perished is not a proposal (§2, §5)."""

    REACH_OFF = "reach_off"
    """The reach level for its class is :attr:`NotificationReach.OFF`."""

    DUPLICATE = "duplicate"
    """Its key matches an actionable record (§8). Re-noticing is expected, and
    this is what makes it safe."""

    AT_CAP = "at_cap"
    """The store holds its cap of actionable records (§7). The cap **refuses**;
    it never displaces an existing record."""

    PERISHABLE = "perishable"
    """The candidate declares an expiry later than the ruling instant.

    **This is the whole of the escalation test** (§5). A producer that declares
    "this expires at 14:00" has committed to something falsifiable; one that
    declares "this is urgent" has committed to nothing. A candidate declaring no
    expiry at all fails *this* condition, which is why it is held rather than
    dropped, and why no setting can make it due.
    """

    REACH_INTERRUPT = "reach_interrupt"
    """The reach level for its class is :attr:`NotificationReach.INTERRUPT`."""

    QUIET_WINDOW = "quiet_window"
    """No quiet window covers the ruling instant."""

    BUDGET = "budget"
    """§6's interruption budget for the window containing the ruling instant is
    not exhausted."""


#: The four conditions §5 evaluates first, **in this order**, each yielding
#: ``DROP`` naming itself as the reason. The order is normative: a candidate that
#: has perished and also duplicates a record still speaking for its key
#: (ADR-0215 §§1-2) is dropped as expired, and a conformance suite can only check
#: "the ordering selects the reason it names" against a stated sequence.
DROP_CONDITIONS: Final[tuple[NotificationCondition, ...]] = (
    NotificationCondition.EXPIRED,
    NotificationCondition.REACH_OFF,
    NotificationCondition.DUPLICATE,
    NotificationCondition.AT_CAP,
)

#: The four that must **all** hold for ``INTERRUPT``, in the order §5 states
#: them. A ``HOLD`` names the first of these it fails and carries the whole set.
INTERRUPT_CONDITIONS: Final[tuple[NotificationCondition, ...]] = (
    NotificationCondition.PERISHABLE,
    NotificationCondition.REACH_INTERRUPT,
    NotificationCondition.QUIET_WINDOW,
    NotificationCondition.BUDGET,
)

#: The two failing conditions **time alone resolves** (§5): a quiet window ends,
#: and a rolling budget window frees a unit. The reach level and an absent expiry
#: are each a condition time does not resolve, so a ``HOLD`` whose failed set
#: holds either carries no ``reconsider_at`` from its ruling.
TIME_RESOLVED_CONDITIONS: Final[frozenset[NotificationCondition]] = frozenset(
    {NotificationCondition.QUIET_WINDOW, NotificationCondition.BUDGET}
)

#: The reach a class takes when no preference names it (ADR-0130 §6). **Hold,
#: deliberately**: out of the box nothing interrupts, and raising a class is an
#: act the user performs.
DEFAULT_NOTIFICATION_REACH: Final[NotificationReach] = NotificationReach.HOLD

#: The shipped interruption budget: three per rolling window (ADR-0130 §6).
DEFAULT_INTERRUPTION_BUDGET: Final[int] = 3

#: The window that budget is counted over: a rolling twenty-four hours (§6).
DEFAULT_INTERRUPTION_WINDOW: Final[timedelta] = timedelta(hours=24)


#: Minutes in a day, and the exclusive bound on a local time-of-day (ADR-0130 §6).
MINUTES_IN_A_DAY: Final[int] = 24 * 60


def minute_of_day(moment: time) -> int:
    """A local time-of-day as minutes since midnight.

    The spelling half of :class:`QuietWindow`'s decision: a caller thinks in
    ``22:00`` and the type holds ``1320``, so this is what turns one into the
    other rather than every call site doing the arithmetic.

    **Seconds are truncated, not rounded**, which is the half-open convention the
    window itself takes: a window ending at ``13:00`` covers ``12:59:59`` and does
    not cover ``13:00:00``.

    Args:
        moment: The local time-of-day, naive.

    Returns:
        Minutes since local midnight, in ``[0, 1440)``.

    Raises:
        ValueError: If ``moment`` carries a timezone. Quiet windows are read in
            ``Settings.timezone`` and no second timezone source is introduced
            (ADR-0130 §6).
    """
    if moment.tzinfo is not None:
        msg = (
            "a local time-of-day must be naive: quiet windows are read in "
            "Settings.timezone and no second timezone source is introduced (ADR-0130 §6)"
        )
        raise ValueError(msg)
    return moment.hour * 60 + moment.minute


class QuietWindow(BaseModel):
    """A local time-of-day interval during which nothing may interrupt (§6).

    **Half-open, and it may cross midnight.** ``[start, end)`` when ``start <
    end``; when ``start > end`` the window wraps, so ``22:00`` to ``07:00`` is the
    ordinary overnight case and is expressed directly rather than as two rows.
    ``start == end`` is refused: it is unreadable as either "nothing" or
    "everything", and a setting whose meaning a reader has to guess is one that
    silently stops the assistant interrupting at all.

    **Both endpoints are minutes since local midnight, and that is a spelling
    decision this type makes rather than one the ADR made.** §9 ratifies these
    names as "shape, not spelling", and §6 asks only for "a half-open
    local-time-of-day interval": minutes satisfy it exactly. A
    :class:`datetime.time` would not have travelled — ADR-0087 gives it no
    canonical wire form, and :func:`ai_assistant.wire.codec.project` fails closed
    on a type nobody has spelled a form for, "because guessing one would be the
    divergence this module exists to prevent". Minting that form is ADR-0087's
    decision and not this lane's; an integer already has one. Use
    :func:`minute_of_day` and :meth:`between` to write one in the units a person
    thinks in, and :attr:`start_time` / :attr:`end_time` to render one back.

    **The endpoints carry no zone, and cannot.** A quiet window is a statement
    about the user's day, read in ``Settings.timezone`` — the same value ADR-0008
    §5 gives the temporal context and ADR-0093 §7b binds the calendar reader to,
    and no second timezone source is introduced (§6). An integer cannot smuggle
    one in, which is the one thing this spelling gets for free.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: int = Field(
        ge=0,
        lt=MINUTES_IN_A_DAY,
        description="When quiet begins, local minutes since midnight, inclusive.",
    )
    end: int = Field(
        ge=0,
        lt=MINUTES_IN_A_DAY,
        description="When quiet ends, local minutes since midnight, exclusive.",
    )

    @classmethod
    def between(cls, start: time, end: time) -> QuietWindow:
        """Build a window from the units a person writes it in.

        Args:
            start: When quiet begins, local and naive.
            end: When quiet ends, local and naive.

        Returns:
            The window.

        Raises:
            ValueError: If either endpoint carries a timezone, or the two name
                the same minute.
        """
        return cls(start=minute_of_day(start), end=minute_of_day(end))

    @model_validator(mode="after")
    def _is_a_readable_window(self) -> QuietWindow:
        """Refuse a window with no readable extent.

        Raises:
            ValueError: If the two endpoints name the same minute.
        """
        if self.start == self.end:
            msg = (
                "start and end must differ: an empty window and an all-day one are not "
                "distinguishable, and a setting a reader has to guess at silently stops "
                "every interruption (ADR-0130 §6)"
            )
            raise ValueError(msg)
        return self

    @property
    def start_time(self) -> time:
        """When quiet begins, as a naive local ``time`` a surface can render."""
        return time(self.start // 60, self.start % 60)

    @property
    def end_time(self) -> time:
        """When quiet ends, as a naive local ``time`` a surface can render."""
        return time(self.end // 60, self.end % 60)

    def covers(self, minute: int) -> bool:
        """Report whether a local minute-of-day falls inside this window.

        Args:
            minute: Minutes since local midnight, as :func:`minute_of_day` gives
                them.

        Returns:
            ``True`` while ``start <= minute < end``, and for a window that
            crosses midnight, while ``minute >= start`` or ``minute < end``.
        """
        if self.start < self.end:
            return self.start <= minute < self.end
        return minute >= self.start or minute < self.end


class ClassReach(BaseModel):
    """One class's reach level, as a standing preference holds it (§6).

    A row rather than a mapping entry, because a notification class is **not a
    closed enumeration** (§6): adding a producer is not a contract change, so the
    preference value has to carry whatever names the deployment's producers
    declare, and a row serialises over the wire without a mapping key's encoding
    questions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_class: NonBlankEncodableText = Field(
        description="The producer-declared class this reach applies to (ADR-0130 §6)."
    )
    reach: NotificationReach = Field(description="How far this class may reach the user.")


class NotificationPreferences(BaseModel):
    """The three standing settings that tune what reaches the user (ADR-0130 §6).

    **Durable user state, not ``Settings``.** These are the user's own choices,
    written through the engine surface, and §9 is explicit that no standing
    setting of §6 becomes a ``Settings`` field. The three ``Settings`` fields this
    ADR does add — the cap, the retention duration and the reconsideration
    interval — are deployment tunings and are not here.

    **Every field has a shipped default, so an empty store is a working policy**
    and no setting is a precondition of the system running (§6). The defaults are
    exactly the ADR's: reach ``hold`` for every class including one no preference
    names, no quiet windows, and three interruptions per rolling twenty-four
    hours.

    **Nothing here is derived from observed behaviour.** §6 forbids inferring a
    reach level from what a user ignored; VISION §5's feedback-based adaptation
    stays a promise and is not this type's mechanism.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reaches: tuple[ClassReach, ...] = Field(
        default=(),
        description=(
            "The classes whose reach the user has set. A class absent from this tuple "
            "takes DEFAULT_NOTIFICATION_REACH (ADR-0130 §6)."
        ),
    )
    quiet_windows: tuple[QuietWindow, ...] = Field(
        default=(),
        description="Local time-of-day intervals during which nothing interrupts.",
    )
    interruption_budget: int = Field(
        default=DEFAULT_INTERRUPTION_BUDGET,
        ge=0,
        lt=2**63,
        description=(
            "How many INTERRUPT rulings may be recorded per rolling window. Zero is a "
            "legible 'never interrupt' rather than a defect (ADR-0130 §6)."
        ),
    )
    budget_window: timedelta = Field(
        default=DEFAULT_INTERRUPTION_WINDOW,
        gt=timedelta(0),
        description="The rolling window the budget is counted over (ADR-0130 §6).",
    )

    @model_validator(mode="after")
    def _names_each_class_once(self) -> NotificationPreferences:
        """Refuse two reach levels for one class.

        Two rows for one class make the setting's meaning depend on which the
        reader looks at first, and a class whose reach is ambiguous is one whose
        ``off`` may silently not hold.

        Raises:
            ValueError: If a notification class appears more than once.
        """
        names = [row.notification_class for row in self.reaches]
        if len(set(names)) != len(names):
            duplicated = sorted({name for name in names if names.count(name) > 1})
            msg = f"each notification class may carry one reach level, got two for {duplicated}"
            raise ValueError(msg)
        return self

    def reach_for(self, notification_class: str) -> NotificationReach:
        """The reach level in force for one class.

        Args:
            notification_class: The producer-declared class.

        Returns:
            The user's setting, or :data:`DEFAULT_NOTIFICATION_REACH` where no
            preference names the class (§6).
        """
        for row in self.reaches:
            if row.notification_class == notification_class:
                return row.reach
        return DEFAULT_NOTIFICATION_REACH

    def is_quiet_at(self, minute: int) -> bool:
        """Report whether any quiet window covers a local minute-of-day.

        Args:
            minute: Minutes since local midnight, as
                :func:`minute_of_day` gives them.

        Returns:
            Whether the instant it stands for is inside a quiet window.
        """
        return any(window.covers(minute) for window in self.quiet_windows)


class NotificationCandidate(BaseModel):
    """A producer's assertion that the user may be worth telling something (§1, §2).

    **It is a proposal, not a decision to tell them.** Producing one reaches
    nobody: a producer holds no channel, no delivery seam and no client
    connection, and its only outcome is the :class:`NotificationDisposition` the
    seam of §3 hands back. It may not select its own disposition, exempt itself
    from §5, or write to the store other than through that seam (§1).

    **It references what it is about and does not contain it** (§2). A reference
    is an identifier resolved through an existing ratified read; ``summary`` and
    ``detail`` are the only free text, and they are what the *user* would be
    shown rather than a copy of a record.

    **Two refusals live on the type rather than in a store's care**, both in the
    shape :class:`DeferredProposal`'s coherence validator takes:

    * a ``DataTier.SECRET`` candidate is refused outright rather than gated, so
      Tier 0 never reaches the notification store **in any disposition and under
      any setting** (§2). ADR-0004 §3 is unconditional that a Tier 0 value lives
      in the OS keyring, "never in the memory database, never in a committed
      file", and this store is a database holding free text a producer wrote to
      be shown to a person. A rule that only stopped Tier 0 *interrupting* would
      still have written it down;
    * a candidate whose expiry is not later than the instant it was noticed is
      refused, because a candidate that has already perished is not a proposal,
      it is a defect (§2).

    **Sensitivity is chosen by the producer and never defaulted**, on ADR-0093
    §4's rule for an attested proposal — which is why the field carries no
    default and a producer that wants to notify about a credential learns so at
    the point it proposes.

    **The confidence, the summary and the class are evidence, not authority**
    (§4). The policy may read them; no clause of §5 is satisfied by a producer
    asserting that it should be.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_key: NonBlankEncodableText = Field(
        description=(
            "A digest over the producer's declared name and a canonical projection of "
            "what was noticed. It holds no clock reading, no random value and nothing "
            "derived from the run that produced it, so the same observation yields the "
            "same key across ticks and across process lives (ADR-0130 §8)."
        ),
    )
    producer: NonBlankEncodableText = Field(
        description=(
            "The producer's declared name — a stable Tier 2 name, on ADR-0093 §7's rule "
            "for a reader's identity."
        ),
    )
    notification_class: NonBlankEncodableText = Field(
        description=(
            "The class §6 tunes, declared by the producer and not a configurable value. "
            "Not a closed enumeration: adding a producer is not a contract change, and a "
            "class no preference names takes the default reach (ADR-0130 §6)."
        ),
    )
    summary: NonBlankEncodableText = Field(
        description="The one line the user would be told. Free text a producer wrote."
    )
    detail: EncodableText | None = Field(
        default=None,
        description="What the user would be told beyond the summary, or None.",
    )
    noticed_at: UtcInstant = Field(description="When the producer noticed it (tz-aware).")
    expires_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the opportunity perishes, or None where the producer will not commit to "
            "one. **Declaring one is the whole of the escalation test** (ADR-0130 §5): a "
            "candidate with no expiry is held, never interrupted."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How strongly the producer proposes that this is worth telling.",
    )
    sensitivity: DataTier = Field(
        description=(
            "The producer's chosen sensitivity, never defaulted (ADR-0093 §4). "
            "DataTier.SECRET is refused at validation (ADR-0130 §2)."
        ),
    )
    references: tuple[Identifier, ...] = Field(
        default=(),
        description=(
            "The records this is about, by identifier. A candidate references and does "
            "not contain (ADR-0130 §2)."
        ),
    )

    @model_validator(mode="after")
    def _is_a_coherent_candidate(self) -> NotificationCandidate:
        """Enforce the two refusals §2 puts on the type.

        Raises:
            ValueError: If the sensitivity is Tier 0, or the expiry is not later
                than the instant it was noticed.
        """
        if self.sensitivity is DataTier.SECRET:
            msg = (
                "a DataTier.SECRET candidate may not be proposed: Tier 0 secrets live in "
                "the OS keyring, never in a database or a committed file, and this refusal "
                "is at validation so it holds in every disposition (ADR-0004 §3, "
                "ADR-0130 §2)"
            )
            raise ValueError(msg)
        if self.expires_at is not None and self.expires_at <= self.noticed_at:
            msg = (
                f"expires_at must be later than noticed_at, got {self.expires_at} for "
                f"{self.noticed_at}: a candidate that has already perished is not a "
                f"proposal, it is a defect (ADR-0130 §2)"
            )
            raise ValueError(msg)
        return self

    def is_perishable_at(self, moment: datetime) -> bool:
        """Report whether this still declares an expiry ahead of an instant.

        The :attr:`NotificationCondition.PERISHABLE` test, spelled once so that a
        policy, a store and a suite cannot disagree about the boundary. Half-open
        in the direction §5 fixes: **at** ``expires_at`` the candidate has
        perished.

        Args:
            moment: The ruling instant, tz-aware.

        Returns:
            Whether an expiry is declared and is strictly later than ``moment``.
        """
        return self.expires_at is not None and moment < self.expires_at


class NotificationDisposition(BaseModel):
    """What §5 ruled about one candidate, and why (ADR-0130 §5).

    **The ruling is mechanical and no model makes it** (§4). Every field here is
    a function of the candidate, the standing preferences, the durable record and
    the instant — which is what makes an interruption explainable after the fact,
    testable before it, and cheap enough to run on every scheduler tick with no
    provider reachable.

    **A ``HOLD`` carries the whole failed set, not the first alone** (§5). The
    ``reason`` names the first for rendering; ``failed`` is what §6 reads when a
    setting changes, and a rule that read the reason instead would miss a record
    whose *second* failure is the one a setting change removes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: NotificationDispositionKind = Field(description="What was decided (ADR-0130 §5).")
    notification_id: Identifier | None = Field(
        default=None,
        description=(
            "The durable record this ruling produced or updated. Always set for HOLD and "
            "INTERRUPT; set on a DROP only where a reconsideration recorded it against an "
            "existing record, since an offer ruled DROP writes none (ADR-0130 §8)."
        ),
    )
    notification_class: NonBlankEncodableText = Field(
        description=(
            "The candidate's class, carried on every disposition so a surface rendering an "
            "interruption can offer the two acts that tune it in one step — dismissing it, "
            "and lowering that class's reach (ADR-0130 §6)."
        ),
    )
    ruled_at: UtcInstant = Field(description="The instant the ruling was made (tz-aware).")
    reason: NotificationCondition = Field(
        description="The condition that decided it, named so the ruling can be explained."
    )
    failed: tuple[NotificationCondition, ...] = Field(
        default=(),
        description=(
            "Every condition of INTERRUPT_CONDITIONS that failed, as an ordered "
            "subsequence of that tuple. Non-empty exactly for HOLD; the reason is its "
            "first member, so the order is what makes the reason true (ADR-0130 §5)."
        ),
    )
    reconsider_at: UtcInstant | None = Field(
        default=None,
        description=(
            "The earliest instant at which every failing condition could next hold, or "
            "None where any of them is not one time alone resolves. A floor, never a "
            "deadline: a late reconsideration is not a fault (ADR-0130 §5)."
        ),
    )

    @model_validator(mode="after")
    def _is_a_coherent_ruling(self) -> NotificationDisposition:
        """Refuse a ruling whose parts do not agree, in the shape §5 fixes.

        Three groups, each admitting a well-typed ruling that defeats something
        §5 or §6 promises: an ``INTERRUPT`` carrying failures would spend a unit
        of budget it did not earn; a ``HOLD`` with an empty set gives §6's
        setting-change rule nothing to read, so a record the user's act should
        have freed sits until it expires; and a ``reconsider_at`` on a set
        holding a condition time does not resolve promises a re-ruling that will
        change nothing.

        Raises:
            ValueError: If any group is violated.
        """
        self._check_failed_set()
        self._check_reconsideration()
        self._check_reason()
        return self

    def _check_failed_set(self) -> None:
        """Refuse a failed set that does not belong to the kind that carries it.

        **The set is ordered, not merely a set.** ``reason`` is defined as its
        first member, so an unordered ``failed`` would let a well-formed ruling
        name the wrong deciding condition: ``(BUDGET, QUIET_WINDOW)`` with
        ``reason=BUDGET`` is two true facts arranged into a false answer to "why
        did you not tell me?", when §5's order makes the quiet window the first to
        fail. Checking the order is what makes ``reason`` mean what §5 says it
        means — and it matters most for a value that arrived over the wire, which
        no producing implementation vouched for.

        Raises:
            ValueError: If a HOLD names no failures or names a first one that is
                not its reason, if any other kind names failures at all, or if
                the set is not an ordered subsequence of INTERRUPT_CONDITIONS.
        """
        if self.kind is NotificationDispositionKind.HOLD:
            if not self.failed:
                msg = (
                    "a HOLD must name every condition that failed at its ruling: §6 reads "
                    "the set, and an empty one leaves a record no setting change can free "
                    "(ADR-0130 §5)"
                )
                raise ValueError(msg)
            if self.reason is not self.failed[0]:
                msg = (
                    f"a HOLD's reason names the first unsatisfied condition, got "
                    f"{self.reason} for a failed set beginning {self.failed[0]} "
                    f"(ADR-0130 §5)"
                )
                raise ValueError(msg)
        elif self.failed:
            msg = f"only a HOLD carries a failed set, got {self.failed} on {self.kind}"
            raise ValueError(msg)
        ordered = tuple(
            condition for condition in INTERRUPT_CONDITIONS if condition in set(self.failed)
        )
        if self.failed != ordered:
            msg = (
                f"a failed set is an ordered subsequence of INTERRUPT_CONDITIONS, each "
                f"condition at most once, got {self.failed} where {ordered} is the order §5 "
                f"states — otherwise the reason names a condition that was not the first to "
                f"fail, and a surface renders the wrong answer to 'why not?' (ADR-0130 §5)"
            )
            raise ValueError(msg)

    def _check_reconsideration(self) -> None:
        """Refuse a due instant on a ruling that cannot fall due.

        Raises:
            ValueError: If a kind other than HOLD carries a ``reconsider_at``, or
                a HOLD carries one while some failing condition is not one time
                alone resolves.
        """
        if self.kind is not NotificationDispositionKind.HOLD and self.reconsider_at is not None:
            msg = (
                f"only a HOLD falls due for reconsideration, got a reconsider_at on "
                f"{self.kind}: no setting change reaches a record already ruled INTERRUPT "
                f"(ADR-0130 §6)"
            )
            raise ValueError(msg)
        if self.reconsider_at is not None and not set(self.failed) <= TIME_RESOLVED_CONDITIONS:
            msg = (
                f"a reconsider_at is set only where time alone resolves every failing "
                f"condition, got {self.failed}: the reach level and an absent expiry are "
                f"each a condition it does not resolve (ADR-0130 §5)"
            )
            raise ValueError(msg)

    def _check_reason(self) -> None:
        """Refuse a reason drawn from the wrong group, or a record left unnamed.

        Raises:
            ValueError: If a DROP names a condition outside DROP_CONDITIONS, an
                INTERRUPT names one outside INTERRUPT_CONDITIONS, or a HOLD or an
                INTERRUPT names no durable record.
        """
        if self.kind is NotificationDispositionKind.DROP and self.reason not in DROP_CONDITIONS:
            msg = (
                f"a DROP names one of the four conditions of DROP_CONDITIONS, got "
                f"{self.reason} (ADR-0130 §5)"
            )
            raise ValueError(msg)
        if (
            self.kind is NotificationDispositionKind.INTERRUPT
            and self.reason not in INTERRUPT_CONDITIONS
        ):
            msg = (
                f"an INTERRUPT names one of the four conditions of INTERRUPT_CONDITIONS, "
                f"got {self.reason} (ADR-0130 §5)"
            )
            raise ValueError(msg)
        if self.kind is not NotificationDispositionKind.DROP and self.notification_id is None:
            msg = f"a {self.kind} names the durable record it produced (ADR-0130 §8)"
            raise ValueError(msg)


class HeldNotification(BaseModel):
    """The durable record a ``HOLD`` or an ``INTERRUPT`` writes (ADR-0130 §7, §8).

    **This is the bookkeeping ADR-0078 §8 refused to put on a memory decision.**
    Delivery state — "was it sent? seen?" — is still not here: it differs per
    spoke and belongs to the delivery seam. What this record is, is the thing
    that seam attaches to.

    **Actionable and retained are different states, and the difference is the
    whole of §7.** A record is *actionable* while it is neither dismissed, nor
    expired, nor ruled ``DROP`` by a reconsideration; it is *retained* until
    retention removes it. Expiry ends interruptibility and actionability and
    **deletes nothing** — an expired record stays enumerable and renders as
    expired. The cap counts the actionable set and no other (ADR-0215 §3), so
    dismissing frees capacity at once and an expired record holds none.

    **Suppressing is a third state, and it is the one §8's duplicate rule reads**
    (ADR-0215 §§1-2, replacing ADR-0130 §7's "the same population"). A record
    *speaks for its key* while it is actionable, **and** on past a dismissal — no
    reconsideration ``DROP`` having reached it — until the expiry its own
    candidate declared. So a fact that recurs after its notification **expired**
    is a new candidate and not a duplicate, exactly as before; a fact that recurs
    after its notification was **dismissed** is still a duplicate until it
    perishes. That asymmetry is the decision in one line: expiry is the fact
    perishing, and a dismissal is not — it is a statement about the record, and
    #1372 is what tying the fact's lifetime to it cost. :meth:`is_actionable_at`
    and :meth:`speaks_for_its_key_at` are therefore two predicates and two reads,
    and an implementation may not compute one population and use it for both.

    **Retention runs from the instant the record ceased to be actionable, not
    from admission** (§7), and that is a correction to the obvious form. Measured
    from admission, a record whose expiry sits beyond the horizon is purged while
    still actionable — at which point its key suppresses nothing, a cursorless
    producer re-notices the same fact, and the same observation interrupts again
    on a schedule set by the retention figure. §8's guarantee is stated
    unconditionally, so retention is the clause that yields — and ADR-0215 §4
    makes it yield again, to the *suppressing* set this time.

    **The duration rides on the record and is never consulted from the setting
    afterwards** (§7), which is :class:`DeferredProposal`'s arrangement and for
    its reason: live configuration governs records admitted from now on and never
    reaches back.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier = Field(description="The record's own id, minted by the store.")
    candidate: NotificationCandidate = Field(
        description="The proposal verbatim — what the user would be told, and what it is about."
    )
    kind: NotificationDispositionKind = Field(
        description=(
            "The record's current ruling: INTERRUPT or HOLD as admitted, or DROP once a "
            "reconsideration ruled it so (ADR-0130 §5)."
        ),
    )
    reason: NotificationCondition = Field(description="The condition that decided the ruling.")
    failed: tuple[NotificationCondition, ...] = Field(
        default=(),
        description="The whole set §6 reads when a standing setting changes (ADR-0130 §5).",
    )
    ruled_at: UtcInstant = Field(description="When the current ruling was made (tz-aware).")
    reconsider_at: UtcInstant | None = Field(
        default=None,
        description=(
            "The floor before which this may not be reconsidered, or None where no "
            "condition it failed is one time resolves. Two writers: the ruling that "
            "produced the record, and a standing-setting write (ADR-0130 §5, §6)."
        ),
    )
    admitted_at: UtcInstant = Field(description="When the record was first written (tz-aware).")
    retention: timedelta | None = Field(
        description=(
            "The retention in force *at admission*, stamped once and never recomputed; "
            "None means this record is never purged (ADR-0130 §7)."
        ),
    )
    dismissed_at: UtcInstant | None = Field(
        default=None,
        description=(
            "When the user dismissed it. **A dismissal is not a deletion** (ADR-0130 §9): "
            "it ends actionability and leaves the record readable."
        ),
    )
    dropped_at: UtcInstant | None = Field(
        default=None,
        description="When a reconsideration ruled it DROP, if one did (ADR-0130 §5).",
    )

    @model_validator(mode="after")
    def _is_a_coherent_record(self) -> HeldNotification:
        """Enforce the record's ruling, its stamps and its retention.

        The ruling half is :class:`NotificationDisposition`'s, restated on the
        record because the record is what a store hands back on every read and a
        type may not rely on its one honest caller.

        **The record's ``reconsider_at`` is checked more loosely than a
        ruling's, and the difference is §6's second writer.** A *ruling* sets one
        only where time alone resolves every failing condition; a
        *standing-setting write* stamps one onto a record whose failed set holds
        the reach condition, which time never resolves — that is exactly what
        makes "the user raises the class and is then actually interrupted" work
        (§6). So the ruling-shaped constraint is asserted on the disposition and
        not here, and what is asserted here is the half that holds for both
        writers: only a held record falls due at all.

        Raises:
            ValueError: If the ruling is incoherent, a stamp does not belong to
                the state, or the retention is not positive.
        """
        self._check_ruling()
        if self.retention is not None and self.retention <= timedelta(0):
            msg = f"retention must be a strictly positive duration or None, got {self.retention}"
            raise ValueError(msg)
        if (self.kind is NotificationDispositionKind.DROP) != (self.dropped_at is not None):
            msg = (
                "dropped_at is stamped exactly where a reconsideration ruled DROP: a DROP "
                "without one has no cessation instant for retention to run from, and one "
                "without a DROP claims a cessation that never happened (ADR-0130 §5, §7)"
            )
            raise ValueError(msg)
        if self.admitted_at > self.ruled_at:
            msg = (
                f"ruled_at must not precede admitted_at, got {self.ruled_at} for a record "
                f"admitted {self.admitted_at}"
            )
            raise ValueError(msg)
        return self

    def _check_ruling(self) -> None:
        """Refuse a ruling whose kind, reason and failed set do not agree.

        Raises:
            ValueError: If the three disagree, in the shape §5 fixes.
        """
        NotificationDisposition(
            kind=self.kind,
            notification_id=self.id,
            notification_class=self.candidate.notification_class,
            ruled_at=self.ruled_at,
            reason=self.reason,
            failed=self.failed,
            reconsider_at=None,
        )
        if self.kind is not NotificationDispositionKind.HOLD and self.reconsider_at is not None:
            msg = (
                f"only a held record falls due for reconsideration, got a reconsider_at on "
                f"{self.kind}: no setting change reaches a record already ruled INTERRUPT "
                f"(ADR-0130 §6)"
            )
            raise ValueError(msg)

    def ceased_at(self) -> datetime | None:
        """The instant this record ceases — or ceased — to be actionable (§7).

        The earliest of the three ways actionability ends: a dismissal, the
        candidate's own expiry, and a reconsideration's ``DROP``. It may lie in
        the future, in which case the record is actionable now and this is when
        it stops being so.

        Returns:
            The cessation instant, or ``None`` where the record has no expiry and
            was neither dismissed nor dropped.
        """
        instants = [
            instant
            for instant in (self.dismissed_at, self.candidate.expires_at, self.dropped_at)
            if instant is not None
        ]
        return min(instants) if instants else None

    def is_actionable_at(self, moment: datetime) -> bool:
        """Report whether this record is actionable at an instant (§7).

        Args:
            moment: The instant to judge at, tz-aware.

        Returns:
            Whether it is neither dismissed, nor expired, nor dropped, as of
            ``moment``. Half-open in the same direction §5's expiry test is: at
            the cessation instant the record is no longer actionable.
        """
        ceased = self.ceased_at()
        return ceased is None or moment < ceased

    def speaks_for_its_key_at(self, moment: datetime) -> bool:
        """Report whether this record suppresses its key at an instant (ADR-0215 §1).

        The population §8's duplicate lookup reads, which is **not** the
        actionable one: a record speaks for its key while it is actionable, or
        while it carries a dismissal, carries no reconsideration ``DROP``, and its
        candidate declares an expiry later than ``moment``. The horizon is that
        declared expiry and nothing else — no instant is stored for it, no
        duration is configured, and a candidate declaring **no** expiry yields a
        record whose speech ends exactly where its actionability does.

        **A dismissal is a statement about the record and never about the fact.**
        It ends actionability, frees a slot under the cap at once and takes the
        record off the list a person reads (§7, §9) — and ADR-0131 §3b reuses it
        for "the outbox is done with these bytes". None of those three is a reason
        for the same fact to be proposed afresh on the next tick, which is what
        #1372 measured: one event, three interruptions, and a day's budget spent.
        The lifetime that governs suppression is the fact's own, and the corpus
        already carries it as the candidate's declared expiry.

        **Where a record carries both stamps the ``DROP`` decides**, and it speaks
        for nothing after it ceased. The pair is unreachable through a conforming
        store — ``dismiss`` refuses a record that is not actionable and a
        reconsideration never reaches a dismissed one — but this record's
        validator does not forbid it, so the precedence is stated rather than
        assumed. It is deliberate as well as defensive: a ``DROP`` comes from an
        expiry or from a class lowered to ``off`` (§5), suppression while a class
        is ``off`` buys nothing — the reach condition is evaluated first and every
        offer of the key is dropped naming it — and it would cost the case that
        matters, an owner turning the class back up inside the candidate's
        lifetime and needing to be reachable.

        **Speech is monotone**: a record that does not speak at some instant
        speaks at no later one. Each disjunct is an upper bound on the instant —
        :meth:`ceased_at` takes the *earliest* cessation, so a stamp added later
        never moves the first bound outward, and the candidate is frozen, so the
        second cannot move at all — and a ``DROP`` removes the second disjunct
        rather than extending it.

        **It is the same predicate as**
        :meth:`DeferredProposal.speaks_for_its_key_at`, and takes its name for
        that reason: a ``REJECTED`` deferral goes on refusing a re-ask for the
        whole of its retention on exactly this reasoning, ADR-0130 §8 borrowed the
        deduplication from it and left that half behind, and two names for one
        predicate is how the two stores would drift.

        Args:
            moment: The instant to judge at, tz-aware.

        Returns:
            Whether a candidate carrying this record's key, offered at ``moment``,
            would be ruled ``DROP`` as a duplicate of it.
        """
        expires_at = self.candidate.expires_at
        return self.is_actionable_at(moment) or (
            self.dismissed_at is not None
            and self.dropped_at is None
            and expires_at is not None
            and moment < expires_at
        )

    def is_due_at(self, moment: datetime) -> bool:
        """Report whether this record falls due for reconsideration (§5).

        Args:
            moment: The instant to judge at, tz-aware.

        Returns:
            Whether it is neither dismissed nor already dropped, carries a
            ``reconsider_at``, and that instant has arrived. ``reconsider_at`` is
            the instant **before** which a record may not be reconsidered, so the
            boundary is inclusive and a late run is not a fault.

        **Expiry is deliberately not part of this test, where it is part of
        :meth:`is_actionable_at`.** §5 lists expiry as one of the two ways a
        reconsideration reaches ``DROP``, and a due record that perished before
        its run is precisely that case: excluding it here would make the clause
        unreachable and leave the record's ruling reading ``HOLD`` forever.
        Recording the ``DROP`` moves nothing a retention horizon depends on —
        :meth:`ceased_at` takes the *earliest* cessation, which for such a record
        is the expiry that already happened.
        """
        return (
            self.dismissed_at is None
            and self.dropped_at is None
            and self.reconsider_at is not None
            and self.reconsider_at <= moment
        )

    def is_purgeable_at(self, moment: datetime) -> bool:
        """Report whether retention has removed this record (§7, ADR-0215 §4).

        **No record is purged while it still speaks for its key, whatever its
        retention**, so a record's key suppresses duplicates for the whole time
        §8 says it does. That is §7's own guard with §7's own reason, reading
        :meth:`speaks_for_its_key_at` where it read :meth:`is_actionable_at`: the
        new population *subsumes* the old one — every actionable record speaks —
        so the condition joins by replacing the first rather than standing beside
        it, and without the move a short retention would reproduce #1372 on a
        slower schedule. ``retention is None`` is a complete answer rather than an
        undefined expression: such a record is never purged.

        **Both conditions are answered here and nowhere else** (ADR-0215 §4). A
        store asks the record whether it is purgeable and purges what says yes; a
        backend composing the speaking test around this predicate would be exactly
        the drift putting it on the type prevents, and would satisfy every
        store-level conformance case while breaking the rule.

        **Neither boundary direction moves, and this lengthens nothing that was
        already there.** For a record dismissed at ``D``, not reached by a
        ``DROP``, with retention ``R`` and a candidate expiring at ``E``: where
        ``E`` is later than ``D + R`` it is not purgeable before ``E`` and is
        purgeable **at** it, speech ending there while retention elapsed strictly
        earlier; where ``E`` is not later than ``D + R`` it is purgeable exactly
        where §7 already put it, strictly after ``D + R``. A record a ``DROP`` did
        reach is in the second case whatever its expiry says, and one that simply
        expired, or whose candidate declared no expiry, likewise: this clause
        reaches them not at all.

        Args:
            moment: The instant to judge at, tz-aware.

        Returns:
            Whether the record has stopped speaking for its key and its retention
            has elapsed **strictly** — at the horizon it is still held, and past
            it it is not, which is the boundary §9's conformance clause states.

        **The elapsed time is measured against the span, rather than the horizon
        being materialized as an instant**, and that is what makes the far edge of
        §7's retention range answerable at all. §7 puts no ceiling on a retention —
        the deliberate escape is ``None`` — so ``ceased + self.retention`` leaves
        the representable ``datetime`` range for a record that ceased recently
        under a retention of a few hundred thousand years, and raises
        ``OverflowError`` rather than answering. ``moment - ceased`` cannot
        overflow, both operands being instants already in range, and the two
        spellings agree everywhere the sum is representable: this changes no
        in-range answer, it only gives the out-of-range ones. **``False`` is the
        true answer there and not a shrug** — a horizon past the end of
        representable time has not elapsed and will not — and it is the same shape
        :meth:`ceased_at` and :meth:`is_actionable_at` already take, where an
        absent cessation is a complete answer rather than an undefined expression.

        Raising instead is not a local defect: ADR-0083 §7's retention job is
        **shared**, sweeping ``MemoryStore`` and ``DeferralStore`` in the same
        operation, so one such record would stop every store's retention being
        enforced while the scheduler logged a failure and retried forever — and
        ADR-0078 §1's exposure cap is measured by exactly that job running.

        ADR-0135 §2 fixes this same mechanism for ADR-0131's delivery seam and is
        deliberately scoped to it ("this clause binds this seam, not the tree",
        §5), so it is cited here as precedent and not as authority: what obliges
        the answer is §7's own "a record is purgeable only once ... its retention
        has elapsed". #974 holds the general question.
        """
        ceased = self.ceased_at()
        if self.retention is None or ceased is None or self.speaks_for_its_key_at(moment):
            return False
        return moment - ceased > self.retention


class NotificationEnqueue(StrEnum):
    """What became of one offer to the delivery outbox (ADR-0131 §3, §3b).

    **Four members, because §3 gives the enqueue four outcomes and each has its
    own producer remedy.** A committed enqueue, a no-op retry, a key collision
    and an outright refusal are what a producer branches on; a store that could
    not commit at all is not among them, because reaching no decision is an
    exception rather than a result. §3b draws that line in as many words — "a
    store's inability to commit is a ``*StoreError``, not a result value" — and
    :class:`~ai_assistant.core.errors.NotificationOutboxError` is where it lands.

    **An enumeration rather than a model, because none of the four carries
    anything** (§3b). An entry has no identity this seam exposes — ADR-0131 §4's
    identifier is per *delivery* and not per entry — and the byte figures a
    refusal turns on are the hub's own settings rather than news. The bare return
    is the shape ``forget``'s ``bool`` already takes on the promoted surface.

    **The values are contract values and are spelled out in §3b**, not left to an
    implementation: ADR-0085 §3 spells out every signature because "this block is
    what an implementation is generated from", and a ``StrEnum``'s values cross
    the same boundary. §3b's conformance clause requires a suite to branch on
    these exact members.
    """

    ENQUEUED = "enqueued"
    """The entry was made and the seam has taken custody of the candidate."""

    ALREADY_HELD = "already_held"
    """An identical entry was already held under this key, and none was made.
    The offer is a **retry** rather than a coincidence: §3 matches on the key
    *and* the candidate, so a differing candidate takes ``KEY_COLLISION``."""

    KEY_COLLISION = "key_collision"
    """The key matched a held entry carrying a different candidate. The offer is
    refused, the held entry is not replaced, and the offered candidate is not
    enqueued under another key (§3)."""

    TOO_LARGE = "too_large"
    """The candidate exceeds one of the hub's size ceilings — ADR-0131 §4's
    delivery ceiling, or the entry's own byte cost against
    ``hub_notification_outbox_bytes`` (§3). The offer is refused, and it is never
    satisfied by evicting other entries."""


#: ADR-0131 §4's delivery reserve: how many bytes a ``NotificationDelivery``
#: wrapper is allowed to add around the candidate inside it. **The reserve exists
#: because what ADR-0085 §8 measures is the result, and the result is the
#: wrapper** — a candidate sized at exactly the contract limit is one the hub could
#: accept and could never deliver, since wrapping it puts the *result* over the
#: limit and the hub must then either refuse what it took or write a frame the
#: client is obliged to reject. §8b's 512-byte reserve does not cover this: it is
#: reserved for the **envelope**, outside the payload, and these members are inside
#: it.
#:
#: **256 is a reserve rather than an exact figure, in §8b's own shape.** The exact
#: overhead is at most 130 bytes — 34 structural, being the braces, the two quoted
#: member names, the two colons and the comma in ADR-0087 §2's canonical form, plus
#: at most 96 for the identifier. The margin is what stops a later member on this
#: model from being a silent overflow instead of a recomputation.
#:
#: **ADR-0206 §6's two members spend part of that margin and the reserve stands.**
#: In ADR-0087 §2's canonical form they add ``,"spoken":null`` — 14 bytes — and
#: ``,"spoken_rendering":"not_requested"`` — 35 bytes, taking the longest of the
#: four values :class:`SpokenRendering` fixes, which is what makes the figure a
#: bound rather than an example. That is 49, for a worst case of 179 against 256,
#: with 77 bytes still in hand; so this constant is **not** superseded and
#: ``offer``'s refusal is unchanged. What does not fit in a reserve of any size is
#: the rendering itself — ``hub_max_spoken_audio_bytes`` defaults to 512 KiB of
#: decoded audio, about 683 KiB base64-encoded — which is why ADR-0206 §6 measures
#: the whole projected delivery and **degrades** rather than widening this figure.
DELIVERY_RESERVE_BYTES: Final[int] = 256


class SpokenRendering(StrEnum):
    """Why a delivery does or does not carry audio (ADR-0206 §6).

    **A closed vocabulary of exactly four, whose serialized values ADR-0206 §6
    fixes here rather than leaving to the member names.** This enumeration crosses
    the wire inside a :class:`NotificationDelivery`, so two implementations
    choosing ``"withheld"`` and ``"WITHHELD"`` would both conform to a clause that
    named only the members and would not interoperate — "the interoperability
    failure ADR-0084 §3 made framing and codec normative to prevent, arriving one
    layer up". Fixing them is also what makes §6's reserve arithmetic checkable:
    without them the longest value is unbounded, and a conforming implementation
    could spend the margin ADR-0131 §4 left. The spelling is
    :class:`SpokenAudioFormat`'s and :class:`DataTier`'s — the member name
    lowercased — so nothing new is invented. A lane adds a member only with an ADR
    deciding it; removing one, or changing one's value, is a change to what was
    decided and takes a superseding ADR.

    **The four are exhaustive and mutually exclusive, and each names one cause**
    (§6). They are read together with :attr:`NotificationDelivery.spoken`, which is
    not ``None`` **exactly when** this is :attr:`RENDERED`.

    **A withholding is never reported as a degradation and a degradation is never
    reported as a withholding** (§6). No implementation collapses the two, and none
    retries a :attr:`WITHHELD` delivery into speech on a later poll: the placement
    ADR-0206 §3 decides is a property of the candidate and not of the attempt. A
    fault invites a retry, and a withholding retried is a disclosure rule defeated
    by a loop — which is why this is a closed enumeration rather than the boolean
    pair ADR-0200 §4 carries one surface over.

    It is what the *hub produced* for a delivery, never what a device reports about
    a spoken answer it played (ADR-0206 §6): :attr:`RENDERED` says the audio left
    the hub and says nothing about whether it was heard.

    Attributes:
        NOT_REQUESTED: ``plays`` was empty, so no placement was decided and no
            synthesizer was called. What a caller that cannot play audio gets, and
            the state in which nothing about the poll's behaviour differs from what
            ADR-0131 §4 already fixes (ADR-0206 §1).
        RENDERED: The rendering is in :attr:`NotificationDelivery.spoken`.
        WITHHELD: ``plays`` was non-empty and ADR-0206 §3 withheld the candidate, so
            no synthesizer was called and nothing was spent. The delivery still
            travels and is still acknowledgeable, and nothing audible marks it (§5).
        DEGRADED: ``plays`` was non-empty and §3 placed the candidate, and speaking
            it did not complete — in exactly the four cases §6 fixes: synthesis
            raised a ``SpeechError``; the intersection of ``plays`` with the
            synthesizer's ``formats`` was empty; the rendering breached ADR-0200
            §6's ``hub_max_spoken_audio_bytes``; or the whole projected delivery
            carrying it would have breached ADR-0085 §8c. **An elapsed budget is not
            among them** (§7).
    """

    NOT_REQUESTED = "not_requested"
    RENDERED = "rendered"
    WITHHELD = "withheld"
    DEGRADED = "degraded"


class NotificationDelivery(BaseModel):
    """One notification handed to one device, with the token that retires it (§4).

    The result payload of ``next_notification`` and the only shape in which a
    notification crosses the wire (ADR-0131 §1). It carries the artifact ADR-0130
    decides and one value this seam mints: the identifier of *this delivery
    attempt*, which the device names on its next poll to acknowledge it.

    **The identifier is per delivery and not per entry**, which is what stops a
    stale holder retiring someone else's notification (§4). An entry redelivered
    after a lease expiry carries a *new* one, and minting it makes the previous
    one no longer that entry's current outstanding delivery — so an
    acknowledgement arriving from a device whose lease has lapsed lands on the
    no-op arm rather than retiring the delivery a second device is holding.

    **It is also a capability, and that is why half of it is random** (§4). The
    engine honours an acknowledgement without knowing who is asking, because the
    token went to exactly one device; possession stands in for the
    connection-scoped identity §4 deliberately keeps out of the engine. A bare
    counter would let a device that has seen ``41`` retire ``42``.

    **``extra="forbid"`` is load-bearing here rather than the house default**
    (§4). ``core/types.py`` carries both shapes, and this one must forbid:
    :mod:`ai_assistant.wire.client` validates and *then* measures (ADR-0087 §7's
    order, correctly applied), so under pydantic's default an unknown member
    would be dropped by the validation before the measurement ever saw it — and a
    peer could send a conforming delivery plus a large unknown member, under the
    frame ceiling and over the contract limit. Forbidding extras makes the frame
    refuse at validation instead.

    **Four members since ADR-0206 §6**, which adds ``spoken`` and
    ``spoken_rendering`` and adds no more. The rendering is produced **inside the
    call that answers the poll** and is retained nowhere: no store, index, trail,
    trace, audit trail or log holds one, in either tier, and a redelivery of the
    same entry renders afresh (ADR-0206 §1). ``model_config`` is unchanged, and
    ADR-0131 §4's reason for ``extra="forbid"`` binds unchanged.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery_id: Identifier = Field(
        description=(
            "This delivery attempt's identifier, minted once in the indivisible step "
            "ADR-0131 §2a fixes and unique over the outbox's whole life. A strictly "
            "increasing decimal counter joined by '.' to 128 bits of lowercase hex from a "
            "cryptographically secure source; at most 96 bytes in UTF-8. The value a "
            "device names as ``acknowledging`` on its next poll (ADR-0131 §4)."
        ),
    )
    notification: NotificationCandidate = Field(
        description=(
            "The candidate whose disposition ADR-0130 §5 ruled INTERRUPT. This seam "
            "decides nothing about its meaning (ADR-0131 §8)."
        ),
    )
    spoken: SpokenAudio | None = Field(
        default=None,
        description=(
            "The rendering of the candidate's summary, or None where there is none. "
            "Not None exactly when spoken_rendering is RENDERED (ADR-0206 §6)."
        ),
    )
    spoken_rendering: SpokenRendering = Field(
        default=SpokenRendering.NOT_REQUESTED,
        description="Why this delivery does or does not carry audio (ADR-0206 §6).",
    )

    @model_validator(mode="after")
    def _audio_is_present_exactly_when_it_was_rendered(self) -> Self:
        """State ADR-0206 §6's invariant **in both directions**.

        "``spoken`` is not ``None`` **exactly when** ``spoken_rendering`` is
        ``RENDERED``, and a validator states that invariant in both directions."
        Each direction rules out a different lie. A rendering beside
        :attr:`SpokenRendering.WITHHELD` would be audio of a candidate a disclosure
        rule refused to speak — the one shape ADR-0206 §5 exists to make
        unconstructible — and it would say the same of :attr:`SpokenRendering.DEGRADED`
        and :attr:`SpokenRendering.NOT_REQUESTED`. A :attr:`SpokenRendering.RENDERED`
        with no audio would report a rendering that is not there, which is the state
        §6 keeps separate from all three of the others.

        Returns:
            This delivery, where its two members agree.

        Raises:
            ValueError: If they do not.
        """
        rendered = self.spoken_rendering is SpokenRendering.RENDERED
        if (self.spoken is not None) != rendered:
            msg = (
                f"a delivery carries audio exactly when its rendering is "
                f"{SpokenRendering.RENDERED.value!r}: this one is "
                f"{self.spoken_rendering.value!r} and "
                f"{'carries' if self.spoken is not None else 'carries no'} audio "
                f"(ADR-0206 §6)"
            )
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Connections: what the owner connected, and what was done to it (ADR-0151)
# ---------------------------------------------------------------------------
# Three types and two constants, promoted because ADR-0151 §1's five engine
# operations exchange them and ADR-0151 §10's `ConnectionProvisioner` carries
# them across the `orchestration`/`tools` boundary (ADR-0068 §1).
#
# **No credential value, and nothing derived from one, appears anywhere below**
# (ADR-0149 §9, ADR-0151 §6). A connection's credential travels only in the two
# requests that write it and comes to rest only in the keyring; what these types
# carry is the non-secret half of ADR-0148 §6's record — the reference, the
# identity, the revision and the provisioning state. In particular no model here
# carries a :class:`SecretName`: a credential slot is `tools/`-internal
# (ADR-0149 §3), and a caller holding one could reach the keyring by another
# route (ADR-0149 §10).
#
# **There is no timestamp, and that is a consequence rather than an omission.**
# ADR-0149 §3 fixes what a connection record carries and an instant is not among
# it, so `recent_connection_acts` answers in the store's own append order and
# makes no timing claim (ADR-0151 §4, §9). Giving a record a recorded instant is
# a change to ADR-0149 §3 and owes its own ADR.


class ProvisioningState(StrEnum):
    """How far the act that wrote a connection record got (ADR-0148 §6).

    **Exactly two members, and the closure is ADR-0148 §6's own rule expressed
    as a type.** §6 gives a connection record one of two provisioning states and
    ADR-0149 §5 forbids a third: a disconnection appends a *removal entry*, and a
    reference whose latest entry is a removal has no live connection record at
    all rather than a record in a third state. So there is no member here for a
    removal, none for an unknown state, and none for a failure — a removal is
    read off :attr:`ConnectionAct.account` being absent, and a failure is a class
    the caller catches (ADR-0151 §2a).

    **Both members are reachable without anyone doing anything wrong**, which is
    why :attr:`PENDING` is on the surface at all rather than hidden as an
    implementation detail. ADR-0148 §6 rules an interrupted act's state "refused
    rather than reconciled": nothing repairs it, and a listing that showed only
    active records would leave a user whose hub was killed mid-act with a
    reference that exists, is refused at every call, and appears nowhere they can
    see (ADR-0151 §4).
    """

    PENDING = "pending"
    """The record was written and its act has not activated it.

    The reference is **not connectable** (ADR-0148 §6): no ``ActionRequest`` is
    built against it, no ruling is sought for one, and no callable transmits
    under it. Nothing is in progress — the act that wrote it is gone — so no
    surface may render this as a connection being established, and the remedy is
    for the user to run the act again (ADR-0151 §4).
    """

    ACTIVE = "active"
    """The act's third write landed and the reference is connectable.

    That is a statement about the *record*, not about the keyring: ADR-0149 §6
    rules that an active record over an empty slot is refused at the credential
    read and repaired by nothing, which is the state a restored data directory
    produces (ADR-0123, ADR-0125 §12).
    """


#: The most an account identity may encode to, in UTF-8 bytes (ADR-0151 §5).
#:
#: **ADR-0149 §4 left the value to this lane and ADR-0151 §5 fixed its
#: location**, which is the half that matters: enforcement in the store alone
#: would put the refusal on the far side of a round trip, and a bound each
#: implementation chose for itself would make the wire client and the in-process
#: engine disagree about a value both are handed (ADR-0085 §9). Every
#: implementation of ``connect_account`` and ``reprovision_account``, the wire
#: client included, refuses against this one constant.
#:
#: **In bytes rather than characters**, because ADR-0085 §8c bounds a serialised
#: payload, :data:`EncodableText` is defined by having a UTF-8 encoding, and
#: :data:`SECRET_VALUE_MAX_BYTES` is already stated in bytes — a character bound
#: would be the only measurement on this surface that does not compose with the
#: frame arithmetic (ADR-0151 §5).
#:
#: **256 is chosen against the frame floor rather than against a taxonomy of
#: account names.** ADR-0151 §11 does the arithmetic: the payload budget at
#: ``hub_max_frame_bytes``' 1024-byte floor is 512 bytes, and a
#: :class:`ConnectedAccount` spends roughly 60 on its member names and JSON
#: punctuation plus at most :data:`CONNECTION_REFERENCE_MAX_BYTES` on the
#: reference — so 256 leaves a maximal single record inside the smallest frame an
#: operator can configure, with room left for the revision and the state. It is
#: also far above every account name this system expects: an email address is
#: bounded at 254 octets by RFC 5321, and a service handle is shorter still.
ACCOUNT_IDENTITY_MAX_BYTES: Final[int] = 256

#: The most a minted connection reference may encode to, in UTF-8 bytes
#: (ADR-0151 §11).
#:
#: **Its ceiling is fixed by ADR-0151 §11 at 64 rather than left to this lane**,
#: and the asymmetry with :data:`ACCOUNT_IDENTITY_MAX_BYTES` is the mint. An
#: oversized *identity* refuses the request the caller sent, and the caller still
#: holds the value and can send a shorter one. An oversized *reference* refuses a
#: response carrying a value that exists only in the hub, so the act has landed
#: and its handle is unreachable — recoverable only by matching on an identity
#: nothing makes unique. A bound wide enough to bust a frame would produce a
#: handle the hub can write and the caller can never receive.
#:
#: A version 4 UUID in its canonical hyphenated form is 36 bytes, so the ceiling
#: is taken whole and leaves a conforming factory room for a prefix.
CONNECTION_REFERENCE_MAX_BYTES: Final[int] = 64


class ConnectedAccount(BaseModel):
    """One reference's live connection record, as the store holds it (ADR-0151 §4).

    Exactly four fields, and the three that are *not* here are the point:

    - **no credential slot and no** :class:`SecretName`. The slot is
      `tools/`-internal (ADR-0149 §3) and a caller holding one could reach the
      keyring by a route the seam was built to close (ADR-0149 §10).
    - **no endpoint.** Nothing in the tree says what an integration *is* yet, so
      a listing shows an identity and a minted reference with nothing saying
      which service the account is on (ADR-0151 §18).
    - **no timestamp**, for the reason this block's header gives.

    **A pending record is a value of this type**, not an absence. ``connected``
    returns one for every reference whose live record is pending, with
    :attr:`ProvisioningState.PENDING`; it does not omit the reference and does
    not substitute the previous act's record for it (ADR-0151 §4).

    Attributes:
        reference: The minted handle naming this connection record and nothing
            else (ADR-0148 §6). Stable across a re-provisioning, which is what
            keeps a parked ``CONFIRM`` answerable after one.
        identity: The account identity the user supplied, byte-for-byte.
        revision: ADR-0148 §6's monotonic revision, reported as the store holds
            it.
        state: How far the act that wrote this record got.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: DurableIdentifier = Field(
        description=(
            "The connection reference: a non-secret handle minted by the provisioner "
            "and never authored by a caller (ADR-0151 §3). It may be logged, which is "
            "the half of ADR-0149 §3's split that makes the identity beside it "
            "loggable by nobody. At most CONNECTION_REFERENCE_MAX_BYTES in UTF-8."
        ),
    )
    identity: NonBlankEncodableText = Field(
        description=(
            "The user-recognisable name of the account, recorded and returned "
            "byte-for-byte as it was supplied (ADR-0149 §4, ADR-0151 §5). Nothing "
            "strips, case-folds, case-normalises or Unicode-normalises it, at any "
            "layer. Tier 1 personal data: it reaches no log line, no error message "
            "and no operator diagnostic (ADR-0149 §3)."
        ),
    )
    revision: int = Field(
        gt=0,
        description=(
            "ADR-0148 §6's monotonic revision, incremented by every provisioning act "
            "on this reference and never reused, never decreasing, and never reset by "
            "a disconnection (ADR-0149 §5). Reported as the store holds it: nothing "
            "renumbers, compacts, offsets or resets it, and no surface presents it as "
            "a count of anything."
        ),
    )
    state: ProvisioningState = Field(
        description=(
            "Whether the act that wrote this record activated it. A PENDING record is "
            "not connectable and nothing repairs it (ADR-0148 §6)."
        ),
    )


class ConnectionAct(BaseModel):
    """One act on one reference, as the store recorded it (ADR-0151 §4, §9).

    The row ``recent_connection_acts`` returns: one per ``(reference, revision)``
    pair, carrying the furthest provisioning state that act reached, in the
    store's own append order. It answers *what was done*, where
    :class:`ConnectedAccount` through ``connected_accounts`` answers *what is
    connected now* — and neither is derivable from the other, because this
    listing is bounded by a ``limit`` and a reference whose latest act falls
    outside the page would be reported by an earlier one (ADR-0139 §1, ADR-0151
    §9).

    **A removal is the absence of** :attr:`account`, **and not a third
    provisioning state**, which ADR-0149 §5 forbids in terms. An earlier draft of
    ADR-0151 §4 gave this model a ``kind`` discriminator over ``PROVISIONING``
    and ``REMOVAL``; it was refused as a fourth promoted type encoding a
    distinction one optional field already carries unambiguously — and the
    optional is the safer of the two shapes, because an enum invites a third
    member where ADR-0149 §5 has ruled there may not be one.

    **This row carries no instant**, so its position in the sequence is the order
    the store recorded the acts in and nothing more. No client presents that
    order as a timing claim, an interval, or a statement about when anything
    happened (ADR-0151 §9).

    Attributes:
        reference: The reference this act was on.
        revision: The revision this act took.
        account: The record this act wrote, or ``None`` where the act was a
            disconnection.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: DurableIdentifier = Field(
        description="The connection reference this act was performed on.",
    )
    revision: int = Field(
        gt=0,
        description=(
            "The revision this act took. Strictly greater than every revision the "
            "reference has ever held, a disconnection included (ADR-0149 §5)."
        ),
    )
    account: ConnectedAccount | None = Field(
        description=(
            "The record this act wrote, present exactly when the act was a "
            "provisioning act and absent exactly when it was a disconnection "
            "(ADR-0149 §5's removal entry). Where present, its reference and "
            "revision equal this act's own."
        ),
    )

    @model_validator(mode="after")
    def _account_transcribes_the_act(self) -> ConnectionAct:
        """Refuse a row whose nested record disagrees with the act it belongs to.

        ADR-0151 §4's equality clause, enforced here rather than left to a reader
        to check. The nesting is a redundancy the ADR accepted deliberately —
        an optional record rather than a discriminator over two — and a value in
        which the two halves disagree describes no act the store could have
        recorded, so it is unconstructible rather than merely unusual.

        Raises:
            ValueError: If ``account`` is present and names a different reference
                or a different revision.
        """
        if self.account is None:
            return self
        if self.account.reference != self.reference or self.account.revision != self.revision:
            msg = (
                "a connection act's record must transcribe the act's own reference and "
                "revision (ADR-0151 §4); got a record for "
                f"{self.account.reference!r} at revision {self.account.revision} on an act "
                f"for {self.reference!r} at revision {self.revision}"
            )
            raise ValueError(msg)
        return self


# --- transport: the endpoint an injected capability opens to (ADR-0191) ------
# ADR-0191 §1 makes reaching the world an injected capability whose one method
# takes an endpoint and returns an open duplex channel. This is that endpoint,
# and the ceiling both halves of the contract refuse against.


#: The most octets a :class:`~ai_assistant.core.protocols.ByteChannel` will
#: buffer for one line, and the largest ``limit`` its ``read`` accepts
#: (ADR-0191 §1).
#:
#: **One constant in `core` rather than a number chosen per implementation**, so
#: the canonical fake and the production implementation refuse the same inputs
#: and a consumer tested against one behaves against the other. It is the bound
#: ``ai_assistant.tools.egress`` already opened its connections with, so nothing
#: about what that seam accepts moves; changing it is a change to `core` surface
#: and takes an ADR.
#:
#: For ``read_line`` it bounds the octets **before** the terminator and not the
#: returned value: a line of exactly this many octets is accepted and comes back
#: one octet longer, and a line one octet past it is refused.
TRANSPORT_OCTET_CEILING: Final = 4096

#: The largest TCP port number, which is what makes a port field's upper bound a
#: fact about the protocol rather than a choice.
_MAX_TCP_PORT: Final = 65535


class TransportEndpoint(BaseModel):
    """One host and port an outbound channel may be opened to (ADR-0191 §1).

    **Exactly three fields and no others** — no scheme, no path, no query, no
    fragment, no userinfo, no credential and no recipient. An implementation is
    handed one already parsed and parses no string of its own, which is what
    stops a permissive endpoint grammar from becoming a second place a
    connection's destination is decided (#83).

    Frozen, because it is the value a pin is compared against: a holder that
    could reassign ``host`` after the comparison would be holding a different
    endpoint from the one that was checked.

    **Its construction rules are ADR-0191 §1's, and no others.** §1 fixes them —
    a host that is neither empty nor only whitespace, a port in ``1..65535`` — and
    settling this type is that document's job (golden rule 5), so a refusal it did
    not write does not belong here however sensible it reads: a narrower accepted
    domain binds every future holder and no ADR decided it. The host a resolver
    would truncate at a ``NUL`` is refused where a resolver is actually reached,
    at ADR-0154 §1's designated seam —
    ``ai_assistant.tools.egress._truncating_character``, applied by both
    ``parse_smtp_endpoint`` and ``StreamOutboundTransport.open_channel``, which
    between them are the only constructor and the only route to ``getaddrinfo``
    under ``src/``. Architecture review found the rule sitting here on round 12.

    Attributes:
        host: The host the connection is opened to, and the name a certificate is
            verified against. Never derived from a recipient's domain.
        port: The TCP port, in ``1..65535`` inclusive.
        implicit_tls: ``True`` where TLS is established before the far end's
            greeting; ``False`` where the holder must upgrade the channel itself.
            There is no third value and in particular no cleartext one — a
            capability that could be asked for a connection it would never
            secure is a capability whose shape admits the failure ADR-0017 §3's
            transport conditions exist to prevent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: NonBlankEncodableText = Field(
        description="The host connected to and verified against; never blank.",
    )
    port: int = Field(ge=1, le=_MAX_TCP_PORT, description="The TCP port, 1..65535 inclusive.")
    implicit_tls: bool = Field(
        description="Whether TLS is established before the greeting, or must be upgraded to.",
    )


# --- speech: what a failure is called ------------------------------------------
# The half of ADR-0200 §9's block that stayed at the foot of this module beside
# `SpokenTurn`, which ADR-0313 §3:1 retired with `converse_spoken`. The recording and
# the rendering themselves moved up to the speech block above.


class SpeechFailure(StrEnum):
    """Why a transcription failed, in this project's own vocabulary (ADR-0200 §4).

    **One member per class of the** :class:`~ai_assistant.core.errors.SpeechError`
    **taxonomy, and the bijection is the point.** ADR-0200 §1 fixes that taxonomy
    at two classes — the base and ``SpeechTimeoutError`` — so this enum has exactly
    two members, and a lane that adds a third ``SpeechError`` subclass adds its
    member here in the same change. The two vocabularies do not drift apart, and
    ``tests/core/test_speech_errors.py`` is what stops one landing
    without the other.

    **It is what is logged in place of the seam's exception.** A speech
    implementation takes arbitrary text and could have interpolated the recording
    into its message, which is the one place ADR-0200 §8's retention rule cannot
    see, so the classification is recorded and the message is not. It crossed the
    promoted surface inside ``TranscriptionFailedError`` until ADR-0313 §3:1 retired
    ``converse_spoken``, the one member that declared that error.

    **The member is chosen by an identity-matched walk of the caught exception's
    MRO** over a mapping frozen at import, never from the exception's ``__name__``,
    its module or its message, each of which an implementation controls. That is
    ``models/routing.py``'s ``_classify`` applied one boundary further out, and for
    its reason: a speech implementation is a stranger, and a class it happens to
    name ``SpeechTimeoutError`` is not the one this build declares.

    Attributes:
        UNCLASSIFIED: A bare :class:`~ai_assistant.core.errors.SpeechError`, or a
            subclass this build's mapping does not name.
        TIMED_OUT: A :class:`~ai_assistant.core.errors.SpeechTimeoutError` — the
            deadline decorator's, since no seam takes a timeout (ADR-0200 §1).
    """

    UNCLASSIFIED = "unclassified"
    TIMED_OUT = "timed_out"


# ADR-0274 §3: channel identity and modality are independent values.


class TextChannelPayload(BaseModel):
    """Text retained byte for byte at the channel boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    modality: Literal[Modality.TEXT] = Modality.TEXT
    text: EncodableText


class SpeechChannelPayload(BaseModel):
    """A transient recording, with its original modality."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    modality: Literal[Modality.SPEECH] = Modality.SPEECH
    audio: SpokenAudio


ChannelPayload = Annotated[
    TextChannelPayload | SpeechChannelPayload, Field(discriminator="modality")
]


class ChannelInput(BaseModel):
    """One supplied input with channel identity, modality, and local context.

    It carries no conversation options: ADR-0313 §4:2 took ``conversation`` off it with
    spoken conversation, whose report and whose goal or question reference were all
    it held.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: ChannelTarget
    payload: ChannelPayload
    context: ChannelContext = Field(default_factory=ChannelContext)


class InformationalEventResult(BaseModel):
    """How an event's activation ended, and nothing it wrote (ADR-0313 §4:3-§4:5).

    An event's place takes no message: what its rounds wrote is kept with its episode
    and written nowhere, so none of it is returned. An activation that could not
    finish — a phase's failure, the round limit, or the event's budget running out —
    is a result reading *couldn't finish*, not a raise (§4:5).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["informational_event"] = "informational_event"
    ended: ActivationEnding = Field(
        description="How the event's activation ended (ADR-0293 §8:3, ADR-0295 §3:4)."
    )


#: What a channel's operation returns. ADR-0313 §4:6 makes it
#: :class:`InformationalEventResult` alone: ``TextChannelResult`` and
#: ``SpokenChannelResult`` left with ``converse`` and ``converse_spoken``.
ChannelOutcome = InformationalEventResult


class ChannelResult(BaseModel):
    """An operation's result and its resolved channel, when one exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    channel: ChannelIdentity | None
    result: ChannelOutcome
    capture: EpisodeCaptureReport

    @model_validator(mode="after")
    def _consistent_channel(self) -> Self:
        # A conversational result's check left with ``converse`` (ADR-0313 §4:6).
        if self.channel is None or self.channel.channel_type != "informational_event":
            msg = "an informational result requires an informational_event channel"
            raise ValueError(msg)
        return self


# --- stories (ADR-0289) --------------------------------------------------------

#: The prefix of every story id the story store mints (ADR-0289 §2). Carried so a
#: reader can tell a story id when it sees one; the kind of a *member* is never
#: inferred from it, because a member carries its kind beside its id (§2).
STORY_ID_PREFIX: Final[str] = "story:"

#: The largest page any story read returns, and the bound a ``limit`` is checked
#: against: the same ceiling episode inspection pages to (ADR-0275).
MAX_STORY_PAGE: Final[int] = 100

#: One past the largest position or sequence number a story cursor may carry: the
#: signed 64-bit ceiling a SQLite bind parameter tops out at (ADR-0073 §2).
_STORY_POSITION_BOUND: Final[int] = 2**63


class StoryActor(StrEnum):
    """Who made a change to a story (ADR-0289 §2).

    A **closed** enumeration, added to and never renamed. ADR-0289 gives it one
    member; a later decision that builds a producer adds that producer's member,
    and ADR-0300 §3:15 adds the three that write stories outside the engine surface.
    Who wrote a note on a story is :class:`StoryNoteAuthor`, not this.
    """

    OWNER = "owner"
    """The owner, through the engine surface (ADR-0289 §4)."""

    UNDERSTANDING = "understanding"
    """The hub, recording understanding's links and the stories its rule starts
    (ADR-0300 §6)."""

    PLANNING = "planning"
    """Planning, through its story calls (ADR-0300 §10)."""

    MATTERS_PASS = "matters_pass"  # noqa: S105  # an actor's name, not a credential.
    """The background matters pass (ADR-0300 §9)."""


class StoryChange(StrEnum):
    """What one line of a story's change log records (ADR-0289 §2).

    A **closed** enumeration, added to and never renamed.
    """

    CREATED = "created"
    """The story was minted, by a create or as the new story of a split."""

    ADDED = "added"
    """A member was added to the story; the line names the member."""

    REMOVED = "removed"
    """A member was removed from the story; the line names the member."""

    MERGED_INTO = "merged_into"
    """The story was merged into another, which the line names."""

    ABSORBED = "absorbed"
    """The story absorbed another by a merge; the line names the absorbed story."""

    SPLIT_OFF = "split_off"
    """A split moved members between this story and the one the line names."""

    DECIDED = "decided"
    """The matters pass decided a flag concerning this story (ADR-0302 §3); the line
    names the flag it answers and the outcome, and no member or other story."""

    NOTE_MOVED_OUT = "note_moved_out"
    """A split or a move carried a note off this story (ADR-0304 §9:6); the line names
    the note and the story it went to. A merge writes none."""

    NOTE_MOVED_IN = "note_moved_in"
    """A split or a move carried a note onto this story (ADR-0304 §9:6); the line names
    the note and the story it came from. A merge writes none."""


class StoryDecision(StrEnum):
    """What a decision on a flag was (ADR-0302 §3:3), one for each of ADR-0300 §9:3's answers.

    A **closed** enumeration, added to and never renamed. The outcome is tied to the
    operation that makes the change (§4:2), so a line cannot record a merge where
    nothing was merged.
    """

    MERGED = "merged"
    """The stories were merged, by a merge answering the flag."""

    SPLIT = "split"
    """The story was split, by a split answering the flag."""

    MOVED = "moved"
    """Members or notes were moved between stories, by a move answering the flag
    (ADR-0304 §9:1)."""

    GROUPED = "grouped"
    """The stories were grouped under a larger one, by a create or a link answering
    the flag."""

    LEFT = "left"
    """The decider changed no story (``StoryStore.leave_flag``)."""

    NOT_APPLIED = "not_applied"
    """The decider chose a change the store refused, and no story changed
    (``StoryStore.leave_flag``, ADR-0303 §8)."""


class StoryRefusalReason(StrEnum):
    """Why a write to the story store was refused (ADR-0289 §3).

    A **closed** enumeration, added to and never renamed. A refused write writes
    nothing; a refusal is an outcome, never a :class:`~ai_assistant.core.errors.
    StoryStoreError`, which is reserved for a store that could not read or write
    its file.
    """

    NO_MEMBERS = "no_members"
    """The write named no member: a create, a link, an unlink or a split with an
    empty member list, or a move naming no member and no note (ADR-0304 §9:2)."""

    UNKNOWN_STORY = "unknown_story"
    """The write named a story the store does not hold, as the story written to or
    as a member. The refusal names it."""

    MERGED_STORY = "merged_story"
    """The write was to a merged story, or named one as a member. The refusal names
    the story and the story it was merged into."""

    SELF_MERGE = "self_merge"
    """A merge named the same story on both sides."""

    LOOP = "loop"
    """The write would make a story contain itself through some chain of stories.
    The refusal names the stories forming the loop; the store never merges,
    re-links or drops a link to resolve one."""

    NOT_A_MEMBER = "not_a_member"
    """A split named a member the story does not currently hold. The refusal names
    the member."""

    UNKNOWN_ACTIVATION = "unknown_activation"
    """A create or a link through the engine named an activation with no record at
    ``activation:<activation_id>`` (ADR-0289 §4). The refusal names the member.
    The store itself never answers this: it reads no other store (§1)."""

    UNKNOWN_FLAG = "unknown_flag"
    """A write answering a flag named no flag the store's records hold (ADR-0302
    §4:4): no version of the story named recorded it. A flag named by an activation
    is always one, since understanding raises none (ADR-0303 §8). The refusal names
    the flag."""

    ALREADY_DECIDED = "already_decided"
    """A write answering a flag named one a ``decided`` line already answers
    (ADR-0302 §4:4). The refusal names the flag."""

    NO_NOTES = "no_notes"
    """A note move, naming no member and one or more notes, named none the story moved
    from holds (ADR-0304 §9:3). The refusal names the story moved from."""

    NOTE_NOT_HELD = "note_not_held"
    """A split or a move whose actor is ``planning`` named a note the story it moves
    from does not hold when it runs, so it is refused whole (ADR-0307 §5:4): a note
    moved away meanwhile, by another call or by the matters pass, refuses it too. Every
    other actor's split or move passes such a note over (ADR-0303 §6:2). The refusal
    names the story moved from."""


class StoryHeader(BaseModel):
    """What a story carries of its own: its id, when it was made, and where it went.

    A story holds no title, summary, state, owner or text of any kind (ADR-0289
    §2). ``merged_into`` names the story it was merged into, once it has been,
    which is how a reader of a merged story follows it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story_id: Identifier
    created_at: UtcInstant
    merged_into: Identifier | None


class StoryEntry(BaseModel):
    """One member in a story's clean view, with when and by whom it was linked.

    ``position`` is the sequence number of the change-log line that added the entry,
    so it is unique across the store and ascending in link order, and a page of the
    view resumes after it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    position: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)
    member: StoryMember
    linked_at: UtcInstant
    actor: StoryActor


class StoryViewPage(BaseModel):
    """A page of a story's clean view, in link order (ADR-0289 §3).

    ``member_count`` is the story's current member count, whatever the page holds.
    ``next_cursor`` is the position to resume after, or ``None`` on the last page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    member_count: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)
    entries: tuple[StoryEntry, ...]
    next_cursor: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


#: The changes whose line names a member, those whose line names another story, and
#: those whose line names a note (ADR-0304 §9:6).
_STORY_MEMBER_CHANGES: Final = frozenset({StoryChange.ADDED, StoryChange.REMOVED})
_STORY_NOTE_CHANGES: Final = frozenset({StoryChange.NOTE_MOVED_OUT, StoryChange.NOTE_MOVED_IN})
_STORY_OTHER_CHANGES: Final = frozenset(
    {StoryChange.MERGED_INTO, StoryChange.ABSORBED, StoryChange.SPLIT_OFF, *_STORY_NOTE_CHANGES}
)

# :data:`StoryNoteId` is declared here, ahead of :class:`StoryLogLine`, because
# ADR-0304 §9:7 has a line recording a carried note name it. It used to sit in the
# notes' section below; the rule above :data:`Identifier` decides the move, as for
# :class:`StoryFlagKind` and :class:`StoryFlag`. Relocating a type is not redefining
# it (ADR-0084 §4): nothing about it changed.

type StoryNoteId = Annotated[PositiveInt, Field(strict=True, lt=_STORY_POSITION_BOUND)]
"""A note's identity: a number the story store assigns, unique across the store and
ascending in the order notes are written, so a story's notes in identity order are
its notes in the order they were written (ADR-0300 §3:1)."""


# --- a flag, and the name a decision answers it by (ADR-0300 §9:2, ADR-0302 §2) ----
#
# :class:`StoryFlagKind` and :class:`StoryFlag` are declared here, ahead of
# :class:`StoryLogLine`, because ADR-0302 §3 has a ``decided`` line name the flag it
# answers. They used to sit in the summary's section below; the rule above
# :data:`Identifier` decides the move — a forward reference plus ``model_rebuild``
# would have made a `core` type depend on an import-order side effect. Relocating a
# type is not redefining it (ADR-0084 §4): nothing about either changed.


class StoryFlagKind(StrEnum):
    """What a tidy-up's flag says of the summary it wrote (ADR-0300 §9:2).

    A **closed** enumeration, added to and never renamed.
    """

    TWO_MATTERS = "two_matters"
    """The summary looks like two matters."""

    LIKE_ANOTHER = "like_another"
    """The summary looks like another story, which the flag names."""


class StoryFlag(BaseModel):
    """A flag a tidy-up raised, by identity only (ADR-0300 §9:2).

    ``story`` names the other story exactly on a ``like_another`` flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: StoryFlagKind
    story: Identifier | None = None

    @model_validator(mode="after")
    def _names_a_story_when_it_says_like_another(self) -> Self:
        if (self.kind is StoryFlagKind.LIKE_ANOTHER) != (self.story is not None):
            msg = "a flag names another story exactly when it says the summary looks like one"
            raise ValueError(msg)
        return self


class StoryFlagName(BaseModel):
    """What names a flag, by identity only (ADR-0302 §2).

    A flag a tidy-up raised is named by ``story``, the story whose summary version
    recorded it, ``version``, that version's number, and ``flag``, the flag as the
    version records it. The shape named by ``activation`` alone was understanding's
    flag (ADR-0302 §2:2), which ADR-0303 §8 retires: the store holds no such flag and
    refuses a write answering one ``unknown_flag``, and the shape stays so that a
    ``decided`` line already answering one still reads as it was written. Exactly one
    of the two shapes is set. A flag raised in a later version is a different flag
    from one raised in an earlier version, though its kind and the story it names are
    the same (§2:4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: Identifier | None = None
    version: int | None = Field(default=None, strict=True, ge=1, lt=_STORY_POSITION_BOUND)
    flag: StoryFlag | None = None
    activation: Identifier | None = None

    @model_validator(mode="after")
    def _names_one_flag(self) -> Self:
        tidy_up = (self.story, self.version, self.flag)
        if self.activation is not None:
            if any(part is not None for part in tidy_up):
                msg = "a flag is named by its activation alone, or by its story's version"
                raise ValueError(msg)
        elif any(part is None for part in tidy_up):
            msg = "a tidy-up's flag is named by its story, the version and the flag"
            raise ValueError(msg)
        return self


class StoryLogLine(BaseModel):
    """One line of a story's change log: identities only (ADR-0289 §2).

    ``sequence`` is unique across the store. ``member`` is present exactly on an
    ``added`` or ``removed`` line, and ``other_story`` exactly on a ``merged_into``,
    ``absorbed``, ``split_off``, ``note_moved_out`` or ``note_moved_in`` line.
    ``note`` is present exactly on a ``note_moved_out`` or ``note_moved_in`` line
    (ADR-0304 §9:7): the note a split or a move carried, the line's other story
    being the one it went to or came from. ``trigger`` is the activation that
    triggered the change, where there was one. ``answers`` and ``outcome`` are
    present exactly on a ``decided`` line (ADR-0302 §3:2): the flag it answers, by
    the name §2 gives it, and what the decision was; a ``decided`` line names no
    member and no other story and carries no trigger. No field holds free text, and
    no line is ever rewritten or removed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)
    story_id: Identifier
    change: StoryChange
    member: StoryMember | None
    other_story: Identifier | None
    actor: StoryActor
    trigger: Identifier | None
    at: UtcInstant
    answers: StoryFlagName | None = None
    outcome: StoryDecision | None = None
    note: StoryNoteId | None = None

    @model_validator(mode="after")
    def _names_what_its_change_names(self) -> Self:
        if (self.member is not None) != (self.change in _STORY_MEMBER_CHANGES):
            msg = "a story log line names a member exactly when it adds or removes one"
            raise ValueError(msg)
        if (self.other_story is not None) != (self.change in _STORY_OTHER_CHANGES):
            msg = (
                "a story log line names another story exactly on a merge, a split or a carried note"
            )
            raise ValueError(msg)
        if (self.note is not None) != (self.change in _STORY_NOTE_CHANGES):
            msg = "a story log line names a note exactly when it records a carried note"
            raise ValueError(msg)
        decided = self.change is StoryChange.DECIDED
        if (self.answers is not None) != decided or (self.outcome is not None) != decided:
            msg = "a story log line names a flag and an outcome exactly when it records a decision"
            raise ValueError(msg)
        if decided and self.trigger is not None:
            msg = "a decision's line carries no trigger"
            raise ValueError(msg)
        return self


class StoryLogPage(BaseModel):
    """A page of a story's change log, in sequence order (ADR-0289 §3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    lines: tuple[StoryLogLine, ...]
    next_cursor: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


class StoryPage(BaseModel):
    """A page of every story the store holds, newest first (ADR-0289 §3).

    ``next_cursor`` is an opaque-to-the-caller position to pass back for the next
    page, or ``None`` on the last.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    stories: tuple[StoryHeader, ...]
    next_cursor: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


class StoryRefusal(BaseModel):
    """Why a write to a story was refused, and what it was refused over (ADR-0289 §3).

    ``story_id`` names the story the refusal is about where there is one — the
    unknown or merged story, the story merged into itself, the story a loop
    starts from, the story a note move found none of its notes on, or the story a
    planning split or move named a note it does not hold — and
    ``merged_into`` names where a merged one went. ``member``
    names the member at fault for ``not_a_member`` and ``unknown_activation``.
    ``loop`` names the stories forming the loop, in containment order starting at
    the story that would have contained itself, and is empty for every other reason.
    ``flag`` names the flag a write answering one was refused over, set exactly on
    ``unknown_flag`` and ``already_decided`` (ADR-0302 §4:4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    reason: StoryRefusalReason
    story_id: Identifier | None = None
    merged_into: Identifier | None = None
    member: StoryMember | None = None
    loop: tuple[Identifier, ...] = ()
    flag: StoryFlagName | None = None

    @model_validator(mode="after")
    def _names_what_its_reason_needs(self) -> Self:
        reason = self.reason
        if (reason is StoryRefusalReason.LOOP) != bool(self.loop):
            msg = "a story refusal names a loop exactly when it refuses one"
            raise ValueError(msg)
        if (reason is StoryRefusalReason.MERGED_STORY) != (self.merged_into is not None):
            msg = "a story refusal names a merge target exactly when it refuses a merged story"
            raise ValueError(msg)
        needs_story = reason in {
            StoryRefusalReason.UNKNOWN_STORY,
            StoryRefusalReason.MERGED_STORY,
            StoryRefusalReason.SELF_MERGE,
            StoryRefusalReason.NO_NOTES,
            StoryRefusalReason.NOTE_NOT_HELD,
        }
        if needs_story and self.story_id is None:
            msg = f"a {reason.value} refusal names the story it is about"
            raise ValueError(msg)
        needs_member = reason in {
            StoryRefusalReason.NOT_A_MEMBER,
            StoryRefusalReason.UNKNOWN_ACTIVATION,
        }
        if needs_member != (self.member is not None):
            msg = "a story refusal names a member exactly when the member is at fault"
            raise ValueError(msg)
        needs_flag = reason in {
            StoryRefusalReason.UNKNOWN_FLAG,
            StoryRefusalReason.ALREADY_DECIDED,
        }
        if needs_flag != (self.flag is not None):
            msg = "a story refusal names a flag exactly when the flag is at fault"
            raise ValueError(msg)
        return self


class StoryOutcome(BaseModel):
    """What a write to the story store did (ADR-0289 §3).

    Exactly one of ``story_id`` and ``refusal`` is set. An applied write names the
    story it leaves standing — the one minted by a create or a split, the one
    written by a link or an unlink, the one merged into by a merge, and the one moved
    to by a move (ADR-0300 §3:14) — and says
    how many change-log lines it appended, which is ``0`` where every member it
    named was passed over. A split or a move counts the two lines each note it
    carries writes (ADR-0304 §9:6). A write answering a flag counts its ``decided``
    lines among them, and a ``leave_flag`` names the first story it wrote a line on
    (ADR-0302 §4:1). A refused write appended nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story_id: Identifier | None = None
    logged: int = Field(default=0, strict=True, ge=0, lt=_STORY_POSITION_BOUND)
    refusal: StoryRefusal | None = None

    @model_validator(mode="after")
    def _applied_or_refused(self) -> Self:
        if (self.story_id is None) == (self.refusal is None):
            msg = "a story outcome is either applied, naming its story, or refused"
            raise ValueError(msg)
        if self.refusal is not None and self.logged:
            msg = "a refused story write appended nothing"
            raise ValueError(msg)
        return self


class StoryMemberView(BaseModel):
    """One member of a story as the engine's view resolves it (ADR-0289 §4).

    An activation member carries its episode's :class:`EpisodeSummary`, or is
    marked ``forgotten`` where no record is there any more. A story member carries
    its current ``member_count``, one level deep.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    position: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)
    member: StoryMember
    linked_at: UtcInstant
    actor: StoryActor
    episode: EpisodeSummary | None
    forgotten: bool
    member_count: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)

    @model_validator(mode="after")
    def _resolved_by_its_kind(self) -> Self:
        if self.member.kind is StoryMemberKind.ACTIVATION:
            if self.member_count is not None or self.forgotten == (self.episode is not None):
                msg = "an activation member carries its episode, or is marked forgotten"
                raise ValueError(msg)
        elif self.member_count is None or self.episode is not None or self.forgotten:
            msg = "a story member carries its member count and nothing else"
            raise ValueError(msg)
        return self


class StoryView(BaseModel):
    """A page of a story's members, resolved by the engine (ADR-0289 §4).

    A merged story's view carries its header, which names the story it was merged
    into, and no members.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    member_count: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)
    members: tuple[StoryMemberView, ...]
    next_cursor: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


def check_story_page(cursor: object, limit: object) -> None:
    """Refuse a story read's paging arguments before any store is read.

    Args:
        cursor: ``None``, or the position a previous page returned to resume after.
        limit: How many items the page may hold, in ``[1, MAX_STORY_PAGE]``.

    Raises:
        ValueError: If either is out of range or not an exact ``int``.
    """
    if cursor is not None and (type(cursor) is not int or not 0 <= cursor < _STORY_POSITION_BOUND):
        msg = "a story cursor must be an integer in [0, 2**63)"
        raise ValueError(msg)
    if type(limit) is not int or not 1 <= limit <= MAX_STORY_PAGE:
        msg = f"a story page limit must be an integer in [1, {MAX_STORY_PAGE}]"
        raise ValueError(msg)


def story_members(members: object) -> tuple[StoryMember, ...]:
    """Snapshot a write's members, refusing anything that is not one.

    The snapshot is taken by revalidation, so a caller mutating its sequence after
    the call cannot change what the store writes. An empty sequence is returned as
    it is: whether no members is a refusal is the operation's to say (ADR-0289 §3).

    Args:
        members: The members a write names.

    Returns:
        The members, as a tuple of fresh values.

    Raises:
        ValueError: If ``members`` is a string or not a sequence, or holds anything
            that is not a :class:`StoryMember`.
    """
    if isinstance(members, str | bytes) or not isinstance(members, Sequence):
        msg = "story members must be a sequence of StoryMember"
        raise ValueError(msg)
    snapshot: list[StoryMember] = []
    for member in members:
        if not isinstance(member, StoryMember):
            msg = f"a story member must be a StoryMember, got {type(member).__name__}"
            raise ValueError(msg)
        snapshot.append(StoryMember.model_validate(member.model_dump()))
    return tuple(snapshot)


# --- a story's notes and summary (ADR-0300 §3, ADR-0303 §§2-4, ADR-0304 §2) -------
#
# The story store keeps two records beside each story: its **notes**, here
# :class:`StoryNote`, and its **summary**, here :class:`StorySummary`, with a
# **version log** of :class:`StorySummaryVersion` recording the summary's history by
# identity. ADR-0303 §2 makes the notes free: nothing ties the two records together
# except that the tidy-up reads the notes and writes the summary, so a line cites
# nothing and a note rests on nothing. ADR-0304 §2 renamed what ADR-0300 to ADR-0303
# call the story's page its summary. ADR-0300 §3:6 keeps ``StoryEntry`` (a member in
# a story's clean view) and ``StoryPage`` (a page of the list of stories) for what
# ADR-0289 made them, so an entry is a *note* here, and ``StoryPage``,
# ``StoryViewPage`` and ``StoryLogPage`` keep *page* in its paged-read sense.

#: The longest text a note may carry, and the longest any line of a summary may
#: carry, in characters (ADR-0300 §3:1, §3:17). Chosen from the episode excerpt the
#: prompts that render an episode already bound it by, 2,000 characters
#: (``UNDERSTANDING_EXCERPT_CHARS`` at the composition root, and the planner's and
#: composer's own excerpts): a note can say as much as an excerpt of an episode, and a
#: line is bounded the same.
STORY_NOTE_MAX_CHARS: Final[int] = 2_000

#: The summary's size cap, in characters, summed over every line (ADR-0300 §3:9,
#: ADR-0303 §4:5): four of those excerpts, so planning, which is given the whole summary
#: of every story its activation belongs to (ADR-0300 §8), can hold a few summaries beside
#: its episodes.
STORY_SUMMARY_CAP_CHARS: Final[int] = 8_000

type _StoryText = Annotated[NonBlankEncodableText, Field(max_length=STORY_NOTE_MAX_CHARS)]


class StoryNoteAuthor(StrEnum):
    """Who wrote a note on a story (ADR-0300 §3:2, ADR-0303 §4:6).

    A **closed** enumeration, added to and never renamed, and a separate one from
    :class:`StoryActor`: who made a membership change is not who wrote a note.
    """

    PLANNING = "planning"
    """Planning, through its note, start and grouping calls (ADR-0303 §2:1)."""

    TIDY_UP = "tidy_up"
    """The tidy-up, as a safety-net note written with its summary under ADR-0300 §5:5.
    Nothing writes a note as ``tidy_up`` from ADR-0303 on, and one written so before
    stays a note like any other (§4:6)."""

    OWNER = "owner"
    """The user writing directly, by the name ADR-0289 §2:6 gives the user's actor."""


class StoryNote(BaseModel):
    """One note on a story (ADR-0303 §2:3-§2:6, §3:1).

    ``text`` is anything at all within :data:`STORY_NOTE_MAX_CHARS`.
    ``written_during`` names the activation the note was written during, and is
    ``None`` exactly for a note ``owner`` wrote directly (§2:5); it is history, and no
    rule reads it (§2:4). ``outside`` is the note's mark: set where the activation its
    writer wrote it during read outside content, by the hub's record of what that
    activation read, and never on a note ``owner`` wrote (§3:1). ``written_at`` is the
    store's clock reading when it was written. None of these changes once it is
    written, and no note is removed; a merge, a split or a move changes only which
    story holds it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    note_id: StoryNoteId
    text: _StoryText
    author: StoryNoteAuthor
    written_during: Identifier | None
    outside: bool = Field(strict=True)
    written_at: UtcInstant

    @model_validator(mode="after")
    def _records_an_activation_as_its_author_does(self) -> Self:
        owner = self.author is StoryNoteAuthor.OWNER
        if owner == (self.written_during is not None):
            msg = "a note records an activation exactly when the user did not write it directly"
            raise ValueError(msg)
        if owner and self.outside:
            msg = "a note the user wrote directly is never marked as outside content"
            raise ValueError(msg)
        return self


class StorySummaryLine(BaseModel):
    """One line of a story's summary: its text, and nothing else (ADR-0303 §2:7).

    A line cites nothing. That some line came from outside content is the summary's mark
    (:attr:`StorySummary.outside`), and the line's own words say which (§3:5).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: _StoryText


class StorySummary(BaseModel):
    """A story's summary: zero or more lines, the first saying what the matter is.

    Only the summary is kept as text: writing a new one discards the old one's
    (ADR-0300 §3:6). ``version`` is the version that wrote it, and ``written_at`` when,
    which is when the summary was last tidied. ``lines`` may be empty: a tidy-up may write
    no line (ADR-0303 §5:3). ``outside`` is the summary's mark, as the version that wrote
    it records it (§3:4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: int = Field(strict=True, ge=1, lt=_STORY_POSITION_BOUND)
    written_at: UtcInstant
    lines: tuple[StorySummaryLine, ...]
    outside: bool = Field(strict=True)


class StorySummaryVersionName(BaseModel):
    """Another story's summary version a tidy-up's run read, by identity (ADR-0303 §3:3).

    ``story`` is the story whose summary the run was shown, and ``version`` the version
    that wrote that summary. It is never a member of the story whose version records it,
    so whether that story holds it is never asked (§4:2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: Identifier
    version: int = Field(strict=True, ge=1, lt=_STORY_POSITION_BOUND)


class StorySummaryVersion(BaseModel):
    """One version of a story's summary, in the append-only version log (ADR-0303 §4:3).

    Identities, instants and enumerations only, and no field holds free text: when it
    was written; the notes and the episodes, by activation id, it took in; the other
    stories' summary versions its run read (§3:3); the flags it raised; and ``outside``,
    whether the summary it wrote is marked (§3:4). ``read_pages`` keeps its name: it is
    a key of the record the version log stores, which ADR-0304 §2 lets keep it rather
    than migrate the store.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: int = Field(strict=True, ge=1, lt=_STORY_POSITION_BOUND)
    written_at: UtcInstant
    took_in_notes: tuple[StoryNoteId, ...] = ()
    took_in_episodes: tuple[Identifier, ...] = ()
    read_pages: tuple[StorySummaryVersionName, ...] = ()
    flags: tuple[StoryFlag, ...] = ()
    outside: bool = Field(strict=True)


class StorySummaryState(BaseModel):
    """A story's summary with everything pending on it (ADR-0300 §3:8, §3:10).

    ``summary`` is ``None`` where no version has been written. ``pending_notes`` are
    the notes the story holds that no version of its summary has taken in since they
    came to it, in the order they were written; ``pending_episodes`` are its
    activation members likewise, by activation id, in link order. ``as_of`` names
    this read: a summary built on it is written with it, which refuses the write where
    a version has been written since and takes in only what was pending at it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    summary: StorySummary | None
    pending_notes: tuple[StoryNote, ...]
    pending_episodes: tuple[Identifier, ...]
    as_of: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


class StoryNoteList(BaseModel):
    """A page of a story's notes, in the order they were written (ADR-0300 §3:10).

    ``next_cursor`` is the note id to resume after, or ``None`` on the last page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    notes: tuple[StoryNote, ...]
    next_cursor: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


class StorySummaryVersionList(BaseModel):
    """A page of a story's version log, oldest first (ADR-0300 §3:10).

    ``next_cursor`` is the version to resume after, or ``None`` on the last page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    versions: tuple[StorySummaryVersion, ...]
    next_cursor: int | None = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


class StorySummaryDraft(BaseModel):
    """A new summary, with what the store records beside it (ADR-0303 §4:1).

    Its lines, first line first, which may be none (§5:3); the pending notes and
    episodes, by activation id, its run read and so takes in; the other stories' summary
    versions its run read (§3:3); the flags it raises; and ``outside``, its mark, which
    the hub sets by §3:4's rule and never from a model's output. It writes no note.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    lines: tuple[StorySummaryLine, ...] = ()
    took_in_notes: tuple[StoryNoteId, ...] = ()
    took_in_episodes: tuple[Identifier, ...] = ()
    read_pages: tuple[StorySummaryVersionName, ...] = ()
    flags: tuple[StoryFlag, ...] = ()
    outside: bool = Field(strict=True)


class StorySummaryRefusalReason(StrEnum):
    """Why a write to a story's summary was refused (ADR-0300 §3, ADR-0303 §4).

    A **closed** enumeration, added to and never renamed, kept apart from
    :class:`StoryRefusalReason`, whose members a membership write answers. A
    refused summary write writes nothing.
    """

    UNKNOWN_STORY = "unknown_story"
    """The write named a story the store does not hold: the story written to, the
    story a flag names, or the story of another story's summary version the run read
    (ADR-0303 §4:2). The refusal names it."""

    MERGED_STORY = "merged_story"
    """The write was to a merged story. The refusal names it and the story it was
    merged into."""

    SUMMARY_MOVED_ON = "summary_moved_on"
    """A version of the story's summary has been written since the read the summary was
    built on, so the version it was built on is no longer the current one. Named
    ``page_moved_on`` until ADR-0304 §2 renamed the page its summary, the one rename
    this enumeration has had, made with a protocol step."""

    UNKNOWN_NOTE = "unknown_note"
    """Answered by no write since ADR-0303 §4:4: a line cites no note and nothing
    marks one superseded, and a note named as taken in that the story does not hold is
    ``not_held``. Kept, since the enumeration is never renamed or narrowed."""

    OVER_CAP = "over_cap"
    """The summary's lines together exceed :data:`STORY_SUMMARY_CAP_CHARS`, every line
    counted (ADR-0303 §4:5)."""

    NOT_HELD = "not_held"
    """The write named as taken in an episode or a note the story does not hold when
    the write ran (ADR-0302 §7, ADR-0303 §4:4). The refusal names the activation or
    the note."""


class StorySummaryRefusal(BaseModel):
    """Why a write to a story's summary was refused, and what over (ADR-0300 §3).

    ``story_id`` names the story the refusal is about: the story written to, or the
    unknown story a flag or a summary version the run read names. ``merged_into`` is set
    exactly on ``merged_story``. ``note`` is set on ``unknown_note`` and on a
    ``not_held`` naming a note, and ``activation`` exactly on a ``not_held`` naming an
    activation; a ``not_held`` names one of the two, never both (ADR-0302 §7:3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    reason: StorySummaryRefusalReason
    story_id: Identifier
    merged_into: Identifier | None = None
    note: StoryNoteId | None = None
    activation: Identifier | None = None

    @model_validator(mode="after")
    def _names_what_its_reason_needs(self) -> Self:
        reason = self.reason
        if (reason is StorySummaryRefusalReason.MERGED_STORY) != (self.merged_into is not None):
            msg = "a summary refusal names a merge target exactly when it refuses a merged story"
            raise ValueError(msg)
        if reason is StorySummaryRefusalReason.NOT_HELD:
            if (self.note is None) == (self.activation is None):
                msg = "a not_held refusal names the activation or the note, never both"
                raise ValueError(msg)
            return self
        if (reason is StorySummaryRefusalReason.UNKNOWN_NOTE) != (self.note is not None):
            msg = "a summary refusal names a note exactly when it refuses an unknown one"
            raise ValueError(msg)
        if self.activation is not None:
            msg = "a summary refusal names an activation only when the story does not hold it"
            raise ValueError(msg)
        return self


class StoryNoteOutcome(BaseModel):
    """What appending a note did: the note as written, or why it was refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    note: StoryNote | None = None
    refusal: StorySummaryRefusal | None = None

    @model_validator(mode="after")
    def _written_or_refused(self) -> Self:
        if (self.note is None) == (self.refusal is None):
            msg = "a note outcome is either written, carrying the note, or refused"
            raise ValueError(msg)
        return self


class StorySummaryOutcome(BaseModel):
    """What a summary write did: the version it appended, or why it was refused.

    The version names the notes and episodes the write took in, the other stories'
    summary versions it read, its flags and its mark.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: StorySummaryVersion | None = None
    refusal: StorySummaryRefusal | None = None

    @model_validator(mode="after")
    def _written_or_refused(self) -> Self:
        if (self.version is None) == (self.refusal is None):
            msg = "a summary outcome is either written, carrying its version, or refused"
            raise ValueError(msg)
        return self


class StorySummaryViewNote(BaseModel):
    """One of a story's notes as its summary view lists it (ADR-0303 §10:2).

    ``note`` carries its id, its text, who wrote it and its mark; ``pending`` says
    whether no version of the story's summary has taken it in since it came to the story.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    note: StoryNote
    pending: bool = Field(strict=True)


class StorySummaryView(BaseModel):
    """A story's summary as the owner is shown it (ADR-0303 §10:2).

    What the story commands answer the owner. ``version`` is the version that wrote
    the summary and ``tidied_at`` when, which is when the summary was last tidied,
    both ``None`` where no version has been written. ``lines`` are the summary's
    lines, in order, and ``outside`` its mark (§3:4), which every view shows
    (§3:8); unless ``withheld`` says the summary was withheld from this reader (§3:11),
    when neither is carried: a flag, never the text, so a reader knows a summary exists
    that it is not shown. ``notes`` are the story's notes, newest first, up to the
    view's bound, each with its id, its mark and whether it is pending, and
    ``more_notes`` counts the notes beyond it.

    A merged story's summary carries its header alone, naming where it went, as its
    view and its standing do (ADR-0289 §3): its notes went with the merge.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    version: int | None = Field(default=None, strict=True, ge=1, lt=_STORY_POSITION_BOUND)
    tidied_at: UtcInstant | None = None
    lines: tuple[StorySummaryLine, ...] = ()
    outside: bool = Field(default=False, strict=True)
    withheld: bool = Field(default=False, strict=True)
    notes: tuple[StorySummaryViewNote, ...] = ()
    more_notes: int = Field(default=0, strict=True, ge=0, lt=_STORY_POSITION_BOUND)

    @model_validator(mode="after")
    def _a_summary_only_where_one_was_written(self) -> Self:
        if (self.version is None) != (self.tidied_at is None):
            msg = "a summary view names its version exactly when it says when it was tidied"
            raise ValueError(msg)
        if self.version is None and (self.lines or self.outside or self.withheld):
            msg = "a story whose summary was never written shows no summary"
            raise ValueError(msg)
        if self.withheld and (self.lines or self.outside):
            msg = "a withheld summary carries neither its lines nor its mark"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _notes_newest_first(self) -> Self:
        ids = [shown.note.note_id for shown in self.notes]
        if any(newer <= older for newer, older in pairwise(ids)):
            msg = "a summary view lists its notes newest first, each once"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _a_merged_story_shows_no_summary(self) -> Self:
        if self.story.merged_into is not None and (
            self.version is not None or self.notes or self.more_notes
        ):
            msg = "a merged story's summary view carries its header and nothing else"
            raise ValueError(msg)
        return self


#: The check a note's text passes: non-blank, encodable, within its bound (§3:1).
_STORY_NOTE_TEXT: Final[TypeAdapter[str]] = TypeAdapter(_StoryText)


def story_note_text(text: object) -> str:
    """Refuse a note's text that no story could hold (ADR-0300 §3:1).

    Shared by every ``AssistantEngine`` implementation, so each refuses the same
    text before any I/O (ADR-0085 §9); the story store refuses it again.

    Args:
        text: The text an owner's note carries.

    Returns:
        It, checked.

    Raises:
        ValueError: If it is not a string, or is blank, not encodable, or longer
            than :data:`STORY_NOTE_MAX_CHARS`.
    """
    if not isinstance(text, str):
        msg = f"a note's text must be a string, got {describe_untrusted(text)}"
        raise ValueError(msg)
    try:
        return _STORY_NOTE_TEXT.validate_python(text)
    except ValueError as exc:
        msg = (
            "a note's text must be non-blank, encodable and at most "
            f"{STORY_NOTE_MAX_CHARS} characters"
        )
        raise ValueError(msg) from exc


def story_move_members(story_id: str, to: str, members: object) -> tuple[StoryMember, ...]:
    """Snapshot a move's members, refusing what no move takes (ADR-0300 §3:14).

    Shared by every ``AssistantEngine`` implementation, so each refuses the same
    move before any I/O (ADR-0085 §9): a move is between two stories and carries
    activation members only. Whether it names any, and whether the first story
    holds them, the store answers as a refusal.

    Args:
        story_id: The story moved from, already checked as an identifier.
        to: The story moved to, already checked as an identifier.
        members: The members the move names.

    Returns:
        The members, as a tuple of fresh values.

    Raises:
        ValueError: If the two stories are the same, or ``members`` is malformed or
            names a story member.
    """
    if story_id == to:
        msg = "a move is from one story to another"
        raise ValueError(msg)
    named = story_members(members)
    if any(member.kind is not StoryMemberKind.ACTIVATION for member in named):
        msg = "a move carries activation members only"
        raise ValueError(msg)
    return named


def check_story_as_of(as_of: object) -> int:
    """Refuse an ``as_of`` no summary read could have returned.

    Args:
        as_of: The ``as_of`` of the summary read a summary was built on.

    Returns:
        It, checked.

    Raises:
        ValueError: If it is not an exact ``int`` in ``[0, 2**63)``.
    """
    if type(as_of) is not int or not 0 <= as_of < _STORY_POSITION_BOUND:
        msg = "a summary's as_of must be an integer in [0, 2**63)"
        raise ValueError(msg)
    return as_of


def story_note_ids(notes: object) -> tuple[int, ...]:
    """Snapshot the note identities a write names, refusing anything that is not one.

    Args:
        notes: The note ids a split or a move names (ADR-0303 §6:2).

    Returns:
        The ids, as a tuple.

    Raises:
        ValueError: If ``notes`` is a string or not a sequence, or holds anything
            that is not an exact ``int`` in ``[1, 2**63)``.
    """
    if isinstance(notes, str | bytes) or not isinstance(notes, Sequence):
        msg = "story notes must be a sequence of note ids"
        raise ValueError(msg)
    snapshot = tuple(notes)
    for note in snapshot:
        if type(note) is not int or not 1 <= note < _STORY_POSITION_BOUND:
            msg = "a story note id must be an integer in [1, 2**63)"
            raise ValueError(msg)
    return snapshot


# --- where a matter stands (ADR-0300 §8) ---------------------------------------
#
# Worked out from the records each time a reader needs it, and never stored
# (ADR-0300 §2:1, §8:1): what was done, when things happened, and the related
# matters. Assembled per reader, so what one reader is shown need not be what another
# is (§8, §11). No field holds a note or a line of the summary; the one text is an
# episode's understood meaning, read from the episode itself.

#: How many of a matter's episodes its timeline shows one by one, most recent first;
#: the older ones are summarised as counts (ADR-0300 §8:1). Chosen from the
#: understanding stage's episode window, which renders ten episodes by recency
#: (``UNDERSTANDING_EPISODE_LIMIT``, the owner's first guess in #2544): a reader asking
#: where a matter stands sees as many of its moments one by one as understanding sees
#: of what happened recently. It also bounds the view's size on the wire, since each
#: moment carries an understood meaning.
STORY_STANDING_RECENT: Final[int] = 10


class StoryEffectState(StrEnum):
    """Where one thing done stands, in the order the view lists them (ADR-0300 §8:1).

    A **closed** enumeration, added to and never renamed. What was done is listed
    unknown first, then not done, then done.
    """

    UNKNOWN = "unknown"
    """Whether it took effect is not known."""

    NOT_DONE = "not_done"
    """It did not take effect."""

    DONE = "done"
    """It took effect."""


#: The order ADR-0300 §8:1 lists what was done in, by state.
_STORY_EFFECT_ORDER: Final = {
    StoryEffectState.UNKNOWN: 0,
    StoryEffectState.NOT_DONE: 1,
    StoryEffectState.DONE: 2,
}


class StoryStandingEffect(BaseModel):
    """One thing done, as where the matter stands lists it (ADR-0300 §8:1-§8:2).

    It names the activation that made it, never a story, so a split, a merge, a move
    and a corrected link carry it with its episode (§8:2). Effect records come with
    the phases' acting (§8); the decision that builds them fills this slot and may
    add to what it carries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    activation_id: Identifier
    state: StoryEffectState
    at: UtcInstant


class StoryStandingEpisode(BaseModel):
    """One member episode on a matter's timeline (ADR-0300 §8:1).

    ``occurred_at`` is the episode's own instant, so the timeline runs in when things
    happened rather than in link order (ADR-0289, *What stays open*). ``meaning`` is
    the episode's latest understood meaning, or ``None`` where it has none.
    ``in_progress`` marks an open episode (ADR-0286 §1), which a reader feeding a
    model is never shown (§6). ``outside`` marks an episode resting on outside
    content, by the rule ADR-0300 §4:3 marks a note resting on an episode: its
    trigger's ``origin`` is ``outside``, or the hub's record of what its activation
    read shows outside content.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    activation_id: Identifier
    occurred_at: UtcInstant
    meaning: NonBlankEncodableText | None
    in_progress: bool = Field(strict=True)
    outside: bool = Field(strict=True)


class StoryStandingEarlier(BaseModel):
    """The timeline's older episodes, summarised as counts (ADR-0300 §8:1).

    ``episodes`` is how many episodes are older than the ones shown one by one, and
    ``first_at`` and ``last_at`` the instants of the oldest and the newest of them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    episodes: int = Field(strict=True, ge=1, lt=_STORY_POSITION_BOUND)
    first_at: UtcInstant
    last_at: UtcInstant

    @model_validator(mode="after")
    def _spans_forward(self) -> Self:
        if self.first_at > self.last_at:
            msg = "the earlier episodes' first instant is not after their last"
            raise ValueError(msg)
        return self


class StoryRelation(StrEnum):
    """How a related matter relates to the one being read (ADR-0300 §8:1).

    A **closed** enumeration, added to and never renamed.
    """

    PART_OF = "part_of"
    """The story read is a member of this one: the larger matter it is part of."""

    CONTAINS = "contains"
    """This one is a member of the story read: a smaller matter inside it."""


class StoryRelated(BaseModel):
    """A related matter: a story one membership away, and how (ADR-0300 §8:1).

    Named by its id and its current member count, one level deep, as ADR-0289 §4:5
    resolves a story member. A matter related but separate is a note on the story,
    not a link, so it is not here (ADR-0300 §8).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    relation: StoryRelation
    story_id: Identifier
    member_count: int = Field(strict=True, ge=0, lt=_STORY_POSITION_BOUND)


class StoryStanding(BaseModel):
    """Where a matter stands, assembled from the records for one reader (ADR-0300 §8:1).

    ``done`` is what was done, from the effect records of the story's current
    episodes, unknown first, then not done, then done. ``recent`` is the timeline's
    newest episodes, most recent first, at most :data:`STORY_STANDING_RECENT`;
    ``earlier`` summarises the older ones as counts, and is set only where ``recent``
    is full. ``related`` is the stories the story read is part of, then the stories
    it contains. Each episode is one the reader may be shown (§11).

    A merged story stands nowhere of its own: its standing carries its header, which
    names the story it was merged into, and nothing else, so a reader follows it as
    it follows a merged story's view (ADR-0289 §3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    story: StoryHeader
    done: tuple[StoryStandingEffect, ...] = ()
    recent: tuple[StoryStandingEpisode, ...] = Field(default=(), max_length=STORY_STANDING_RECENT)
    earlier: StoryStandingEarlier | None = None
    related: tuple[StoryRelated, ...] = ()

    @model_validator(mode="after")
    def _a_merged_story_stands_nowhere(self) -> Self:
        if self.story.merged_into is not None and (
            self.done or self.recent or self.earlier is not None or self.related
        ):
            msg = "a merged story's standing carries its header and nothing else"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _done_in_state_order(self) -> Self:
        ranks = [_STORY_EFFECT_ORDER[effect.state] for effect in self.done]
        if ranks != sorted(ranks):
            msg = "what was done is listed unknown first, then not done, then done"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _recent_first(self) -> Self:
        instants = [episode.occurred_at for episode in self.recent]
        if instants != sorted(instants, reverse=True):
            msg = "the timeline lists its episodes most recent first"
            raise ValueError(msg)
        earlier = self.earlier
        if earlier is None:
            return self
        if len(self.recent) < STORY_STANDING_RECENT:
            msg = "older episodes are summarised only once the recent ones are full"
            raise ValueError(msg)
        if earlier.last_at > self.recent[-1].occurred_at:
            msg = "the earlier episodes are no newer than the oldest one shown"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _each_related_once(self) -> Self:
        named = [related.story_id for related in self.related]
        if len(set(named)) != len(named) or self.story.story_id in named:
            msg = "a related matter is another story, named once"
            raise ValueError(msg)
        contains = [related.relation is StoryRelation.CONTAINS for related in self.related]
        if contains != sorted(contains):
            msg = "the stories it is part of come before the stories it contains"
            raise ValueError(msg)
        return self


# --- the diagnostic record (ADR-0314) ------------------------------------------


class DiagnosticSource(StrEnum):
    """Which part of the pipeline wrote a diagnostic entry (ADR-0314 §4, §8).

    A **closed** enumeration, added to and never renamed: a member names the lines
    of files an owner reads with the server's own tools, and a renamed member would
    leave older files speaking a word nothing writes any more.
    """

    CONTROLLER = "controller"
    UNDERSTANDING = "understanding"
    RECALL = "recall"
    PLANNING = "planning"
    AUTHORIZING = "authorizing"
    DIGESTING = "digesting"


class DiagnosticKind(StrEnum):
    """Whether an entry is what a source was given, what it returned, or a step (§4)."""

    GIVEN = "given"
    RETURNED = "returned"
    STEP = "step"


class DiagnosticEntry(BaseModel):
    """One line of an activation's diagnostic record (ADR-0314 §6, §8).

    **Tier 1 under ADR-0004 §1** (§2:3), and the opposite of an
    :class:`EvaluationTrace` in the one way that matters: its ``body`` holds what a
    phase was given and returned, raw outside text and planning's thinking
    included. That is safe only because nothing reads an entry back (§3): no
    Protocol carries a read of the record, and no body, nor anything taken from
    one, reaches a prompt, a message, a memory, an episode, a story, a trace or a
    log.

    Frozen at both levels, as every mapping-holding record here is: the body
    detaches into a copy the model owns and exposes as an immutable view.

    Attributes:
        activation_id: The activation the entry is written for, which names its file.
        source: Which part of the pipeline wrote it.
        kind: Given, returned, or a controller step.
        recorded_at: When it was written, from the activation's clock.
        body: What the source gives the record (§4's table).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    activation_id: Identifier
    source: DiagnosticSource
    kind: DiagnosticKind
    recorded_at: UtcInstant
    body: FrozenJsonMapping

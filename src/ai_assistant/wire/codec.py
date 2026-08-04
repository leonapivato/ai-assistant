"""The canonical wire encoding, and the contract limit measured on it.

ADR-0087 ratifies **the exact byte string a payload serialises to**, with five
properties over the value space (§2) and ~67 normative vectors (§5). This module
is that encoding for the transport: what the client writes into a request frame,
what the server writes into a result frame, and — because ADR-0084 §4 makes the
size limit a clause of the *contract* rather than a property of the transport —
what both of them measure before sending.

**One encoding serves both jobs.** ADR-0087 §2a's context-freedom is what makes
that sound: "the bytes a sender measures are the bytes it transmits", so
measurement and transmission cannot disagree and a payload does not grow on its
way into the envelope.

**Why this is a second encoder rather than an import** (#571). ADR-0084 §6 rules
that `wire` "depends on ``core`` and nothing else", which forecloses importing
:mod:`ai_assistant.orchestration.payloads`; and ADR-0087 §9 records that
``orchestration`` cannot import `wire` concretely "without engaging golden rule
1", which forecloses the other direction. ADR-0085 §8c forecloses a ``core``-owned
codec, and ``core/types.py`` is contract floor this lane may not widen. So two
encoders is what the ratified placements leave, and ADR-0087 §7 anticipated
exactly this:

    **Two encoders may exist without the contract weakening.** … because
    conformance is defined by output, an encoder inside `wire` and an encoder the
    in-process engine reaches for are byte-identical if both pass §5, whether or
    not they share a line of code.

That is a claim a test can hold rather than a hope: ``tests/wire/test_codec.py``
asserts §5's vectors against *this* encoder and then asserts, vector by vector,
that :func:`ai_assistant.orchestration.payloads.canonical_payload` agrees byte for
byte. A divergence fails the gate on the round it is introduced.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    GrantScope,
    Identifier,
    NonBlankEncodableText,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: The bytes ADR-0085 §8b reserves for the frame envelope, so a payload at the
#: contract limit still fits inside ``hub_max_frame_bytes``. §8b computes today's
#: worst case at 110 bytes — the member names, the punctuation, an 11-byte
#: ``kind``, a 36-byte correlation id and a 21-byte method name — and fixes the
#: reserve at 512 anyway: "a later protocol version may add a member to the
#: envelope (ADR-0084 §3 permits it), and a reserve derived from today's exact
#: worst case would silently become wrong the day it does".
ENVELOPE_RESERVE_BYTES: Final[int] = 512

#: ADR-0085 §8d's bound on **either** connect-exchange payload, request and reply
#: alike. Stated over the payload rather than member by member deliberately: "two
#: separate members turned out to be unbounded on inspection, which is evidence
#: that inspection is not a reliable way to enumerate them", and a later protocol
#: version may add a fifth that no per-member sentence would reach.
CONNECT_PAYLOAD_BYTES: Final[int] = 256

#: The exclusive upper bound on a page argument (ADR-0073 §2). Refused rather than
#: clamped, and refused **locally, before any I/O** (ADR-0085 §9), so the client
#: and the in-process engine refuse the same values without a round trip.
_PAGE_ARGUMENT_BOUND: Final[int] = 2**63

_SECONDS_PER_MINUTE: Final[int] = 60
_MINUTES_PER_HOUR: Final[int] = 60

_IDENTIFIER: Final = TypeAdapter[str](Identifier)
_NON_BLANK_TEXT: Final = TypeAdapter[str](NonBlankEncodableText)


def _instant(value: datetime) -> str:
    """Spell one instant as ADR-0087 §2d fixes it.

    ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z`` — the UTC designator is ``Z`` and never
    ``+00:00``, and the fractional part is absent when the microsecond field is
    zero and otherwise exactly six digits with trailing zeros kept. Six digits is
    "the library's behaviour and it is ratified rather than trimmed", because a
    value-dependent width is a second thing to get right at the boundary for no
    benefit a 16 MiB budget can notice.

    The components are formatted explicitly rather than through ``strftime``,
    whose ``%Y`` zero-padding is platform-dependent below the year 1000.
    """
    fraction = f".{value.microsecond:06d}" if value.microsecond else ""
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}{fraction}Z"
    )


def _duration(value: timedelta) -> str:
    """Spell one duration as ADR-0087 §2e fixes it.

    ``[-]P[nD][T[nH][nM][n[.ffffff]S]]``, with **the decomposition fixed rather
    than merely the alphabet**: ``0 <= H < 24``, ``0 <= M < 60``, ``0 <= S < 60``.
    Without the ranges the grammar admits ``"PT61S"`` and ``"PT1M1S"`` for one
    value — the failure a canonical encoding exists to close, reproduced inside its
    own rule.

    **The magnitude is taken first.** Python stores a negative duration with a
    negative day field — ``timedelta(days=-1, seconds=1)`` is ``(-1, 1, 0)`` — so
    an encoder reading those fields directly would emit ``"-P1DT1S"``, which is
    -86401 seconds rather than the -86399 it was given.

    **No nominal component is ever emitted.** ``Y`` is forbidden outright: it does
    not denote a fixed elapsed time, so ``"P1Y"`` round-trips only because both
    halves privately agree a year is 365 days — and ADR-0084 §3 freezes this codec
    permanently, which is the worst possible place to embed a private convention
    that reads as a standard one.
    """
    sign = "-" if value < timedelta(0) else ""
    magnitude = abs(value)
    seconds = magnitude.seconds
    minutes, seconds = divmod(seconds, _SECONDS_PER_MINUTE)
    hours, minutes = divmod(minutes, _MINUTES_PER_HOUR)
    fraction = f".{magnitude.microseconds:06d}".rstrip("0") if magnitude.microseconds else ""

    date_part = f"{magnitude.days}D" if magnitude.days else ""
    time_part = ""
    if hours:
        time_part += f"{hours}H"
    if minutes:
        time_part += f"{minutes}M"
    if seconds or fraction:
        time_part += f"{seconds}{fraction}S"
    if not date_part and not time_part:
        return "PT0S"
    return f"{sign}P{date_part}" + (f"T{time_part}" if time_part else "")


# One total dispatch over the value space, kept as a single chain deliberately: a
# reader checking that every type this surface can carry has a form — and that the
# two ADR-0087 §2 gives *no* form are refused rather than guessed — has one place
# to look. Splitting it to satisfy the branch counters would move half the answer.
def project(value: object) -> Any:  # noqa: C901, PLR0911
    """Render one value into the plain JSON types ADR-0087 §2's recipe encodes.

    The first half of the canonical encoding: ``json.dumps`` cannot render a
    ``datetime``, a ``timedelta`` or a ``StrEnum``, so a projection runs first and
    produces the scalars' spellings. The second half is :func:`canonical_payload`.

    **The projection is written out rather than delegated to
    ``model_dump(mode="json")``**, and the reason is ADR-0087 §3's second row: that
    projection renders a duration of 365 days or more with a nominal ``Y``
    component, which §2e forbids.

    Args:
        value: Any value the promoted surface can carry.

    Returns:
        The same value as plain JSON types: ``dict``, ``list``, ``str``, ``int``,
        ``float``, ``bool`` or ``None``.

    Raises:
        ValueError: If a string has no UTF-8 encoding, or a float is not finite.
            Both are values ADR-0087 §2 gives no wire form, and §7 fixes that they
            are refused **before** measurement rather than substituted.
        TypeError: If the value is of a type this surface does not carry. Fail
            closed: a type nobody has spelled a form for has no canonical bytes,
            and guessing one would be the divergence this module exists to prevent.
    """
    if isinstance(value, BaseModel):
        return project(value.model_dump())
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return project(value.value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            msg = f"a non-finite float has no canonical encoding, so {value!r} cannot be measured"
            raise ValueError(msg)
        return value
    if isinstance(value, str):
        return encodable_text(value)
    if isinstance(value, datetime):
        return _instant(value)
    if isinstance(value, timedelta):
        return _duration(value)
    if isinstance(value, dict) or hasattr(value, "keys"):
        mapping: Mapping[str, object] = value  # type: ignore[assignment]
        return {encodable_text(key): project(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        items: Sequence[object] = value
        return [project(item) for item in items]
    msg = f"{type(value).__name__} has no canonical wire form on this surface"
    raise TypeError(msg)


def encode_projection(projection: Any) -> bytes:
    """Run ADR-0087 §2's recipe over an already-projected value.

    ``allow_nan=False`` is load-bearing rather than decorative (ADR-0087 §3 row 3):
    without it ``json.dumps`` writes the non-JSON tokens ``NaN`` and ``Infinity``.
    :func:`project` has already refused those, so this is the second of two guards
    on the same value rather than the only one.

    Args:
        projection: A value already rendered into plain JSON types.

    Returns:
        Its canonical UTF-8 bytes.
    """
    text = json.dumps(
        projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def canonical_payload(value: object) -> bytes:
    """Encode one payload as ADR-0087 ratifies it.

    ADR-0021 §1's canonical JSON form — sorted members, no insignificant
    whitespace, UTF-8 unescaped — applied to :func:`project`'s output. **The
    payload is any JSON value**: there is no wrapper object and no distinction in
    the encoding between a model and anything else, so a ``forget`` result is the
    four bytes ``true`` and an empty page is the two bytes ``[]`` (ADR-0087 §5e).

    Args:
        value: The payload — a request's argument object, a result value, or an
            error body.

    Returns:
        The canonical UTF-8 bytes, which are both what is measured against the
        contract limit and what the transport writes.
    """
    return encode_projection(project(value))


def largest_member(projection: Any) -> str | None:
    """Name the top-level member that contributed most to the payload's size.

    ADR-0085 §9 makes this a rule rather than a judgement, because ``details`` is
    reconstructed on the far side and must match: two implementations naming
    different members for one payload would break the round-trip contract. The
    rule is the member whose **own** canonical encoding is longest, ties broken by
    the member name's bytes in ascending order, and ``None`` where the payload has
    no named members — a listing result is a bare array, a ``forget`` result a bare
    ``true``.

    Args:
        projection: The payload, already rendered by :func:`project`.

    Returns:
        The member's name, or ``None`` where the payload has no named members.
    """
    if not isinstance(projection, dict) or not projection:
        return None
    largest: str | None = None
    largest_size = -1
    for name in sorted(projection):
        size = len(encode_projection(projection[name]))
        if size > largest_size:
            largest, largest_size = name, size
    return largest


def check_payload(value: object, *, max_bytes: int, subject: str) -> None:
    """Refuse a payload the contract does not admit (ADR-0085 §8c).

    **The byte bound is spelled ``max_bytes`` and not ``limit``** so that
    :func:`check_arguments` can carry an argument *named* ``limit`` — which four
    methods on this surface have.

    Args:
        value: The payload to measure.
        max_bytes: The contract limit in bytes.
        subject: What is being measured, for the message.

    Raises:
        OversizedValueError: If the payload's canonical encoding exceeds
            ``max_bytes``.
        ValueError: If the payload holds a value with no canonical encoding, which
            is refused **before** measurement rather than measured (ADR-0087 §7).
    """
    projection = project(value)
    size = len(encode_projection(projection))
    if size <= max_bytes:
        return
    field = largest_member(projection)
    largest = "" if field is None else f"; the largest member is {field!r}"
    msg = f"{subject} encodes to {size} bytes, over the {max_bytes}-byte contract limit{largest}"
    raise OversizedValueError(msg, limit=max_bytes, size=size, field=field)


def check_arguments(method: str, *, max_bytes: int, **arguments: object) -> None:
    """Refuse a call whose argument payload the contract does not admit.

    **An argument the caller did not pass is absent, not ``null``** (ADR-0085 §10),
    and on this surface every argument whose absence is expressible has ``None`` for
    its declared default — so a ``None`` here *is* "not passed" and is dropped from
    the object. Everything else is present, including a paging ``limit`` whose value
    came from the default: ADR-0087 §7 fixes the order as decode, validate, **then**
    measure, and a validated call has its defaults applied.

    Args:
        method: The method being called, for the message.
        max_bytes: The contract limit in bytes.
        **arguments: The call's arguments, named exactly as the Python parameters
            are. Members are sorted by the encoding, so the caller's keyword order
            is not observable — ``f(b=…, a=…)`` and ``f(a=…, b=…)`` are one call
            and one byte string (ADR-0087 §5e).

    Raises:
        OversizedValueError: If the argument object's canonical encoding exceeds
            ``max_bytes``.
    """
    check_payload(
        arguments_object(**arguments), max_bytes=max_bytes, subject=f"the arguments to {method}()"
    )


def arguments_object(**arguments: object) -> dict[str, object]:
    """Build a request's argument object, dropping what the caller did not pass.

    Args:
        **arguments: The call's arguments, named as the Python parameters are.

    Returns:
        The members the request payload carries.
    """
    return {name: value for name, value in arguments.items() if value is not None}


def identifier(value: str, *, name: str) -> str:
    """Validate and normalise one identifier argument (ADR-0085 §3c).

    **The clause carries the whole of :data:`~ai_assistant.core.types.Identifier`,
    not half of it**: it both *rejects* a blank value and *strips* surrounding
    whitespace from the value the implementation then uses. Optional normalisation
    on an *identity* argument would make the answer to ``belief(" rec-1 ")`` a
    property of which implementation you are holding.

    Args:
        value: The identifier as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The identifier stripped, which is what is then sent.

    Raises:
        ValueError: If the identifier is blank, or has no UTF-8 encoding. Refused
            **locally, before any I/O**, so the client refuses the same values the
            in-process engine does without a round trip (ADR-0085 §9).
    """
    try:
        return _IDENTIFIER.validate_python(value)
    except ValidationError as exc:
        msg = f"{name} must be a non-blank identifier"
        raise ValueError(msg) from exc


def page_argument(value: int, *, name: str) -> int:
    """Refuse a malformed page argument, locally (ADR-0073 §2, ADR-0085 §9).

    **The type is checked before the range, and a ``bool`` is excluded.** Neither
    half is pedantry: ``0 <= 1.5 < 2**63`` is *true*, so a range check alone admits
    a float, which would then travel and fail on the far side after I/O has begun;
    and ``True`` is an ``int`` that would silently mean a page size of one, which
    is a wrong answer rather than a refusal.

    Args:
        value: The page argument as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The value, unchanged.

    Raises:
        TypeError: If the value is not an integer, or is a ``bool``.
        ValueError: If the value falls outside ``[0, 2**63)``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{name} must be an integer, got {value!r}"
        raise TypeError(msg)
    if not 0 <= value < _PAGE_ARGUMENT_BOUND:
        msg = f"{name} must be in [0, 2**63), got {value}"
        raise ValueError(msg)
    return value


def positive_page_argument(value: int, *, name: str) -> int:
    """Refuse a page argument that is not strictly positive (ADR-0102 §10).

    :func:`page_argument`'s stricter sibling, for the one argument on the promoted
    surface whose range and its store's do not coincide: ADR-0085 §9 admits
    ``[0, 2**63)`` and ``SourceGrantStore.recent`` requires a strictly positive
    ``limit``, so ``recent_grants(limit=0)`` is well-formed under the surface rule
    and refused by the store. ADR-0102 §10 refuses it locally in every
    implementation instead, so neither is silently more permissive.

    Args:
        value: The page argument as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The value, unchanged.

    Raises:
        TypeError: If the value is not an integer, or is a ``bool``.
        ValueError: If the value is not in ``[1, 2**63)``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{name} must be an integer, got {value!r}"
        raise TypeError(msg)
    if not 1 <= value < _PAGE_ARGUMENT_BOUND:
        msg = f"{name} must be strictly positive and below 2**63, got {value}"
        raise ValueError(msg)
    return value


def non_blank_text(value: str, *, name: str) -> str:
    """Validate one :data:`~ai_assistant.core.types.NonBlankEncodableText` argument.

    :func:`identifier`'s deliberate opposite number, and the asymmetry is the whole
    of ADR-0102 §2. ``identifier`` carries the *whole* of ``Identifier`` — it
    rejects a blank value **and strips** the one it accepts — because an identity
    argument compared against a stored id must normalise the same way in every
    implementation. A grant's ``source`` is compared against a **declared
    constant**, and there the strengthening inverts: stripping one layer below the
    comparison would make ``grant(" calendar ")`` match a reader named
    ``"calendar"`` over the wire, where ADR-0097 §10 requires in as many words that
    "a source differing from a held reader's ``name`` only by surrounding
    whitespace is refused rather than matched" — while the in-process engine, handed
    the string unvalidated, refused it. That is ADR-0084 §4's substitutability
    failure arriving through an annotation.

    So this refuses and returns **byte for byte** what it was given. ADR-0096 §2
    drew the general rule when it needed the same property one field away: "a
    faithful copy takes the type of the field it copies, and may tighten only in
    ways that reject", because "tightening by *normalising* is how two spellings of
    one value drift, silently, until something compares them".

    Args:
        value: The text as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The value, unchanged — never stripped, never case-folded.

    Raises:
        ValueError: If the value is blank, or has no UTF-8 encoding. Refused
            locally, before any I/O (ADR-0085 §9).
    """
    try:
        return _NON_BLANK_TEXT.validate_python(value)
    except ValidationError as exc:
        msg = f"{name} must be non-blank text with a UTF-8 encoding"
        raise ValueError(msg) from exc


def grant_scope(value: Sequence[GrantScope], *, name: str) -> tuple[GrantScope, ...]:
    """Materialise and refuse a malformed ``scope`` argument (ADR-0102 §2a).

    Three things, in this order, all before any I/O:

    * **Materialised first**, which is this module's input-observation obligation
      (ADR-0065, and the surface's own restatement of it): a caller that mutates the
      sequence it passed cannot change the grant that is recorded.
    * **Every member is a** :class:`~ai_assistant.core.types.GrantScope`. A wire
      client decoding an unknown string for a scope member meets the same value, so
      this is a contract clause rather than one implementation's input hygiene.
    * **Empty and duplicated are refused**, which is ADR-0097 §2 and §10 one step
      earlier than the record's own validator. Refusing here is what makes ADR-0085
      §9's "refused locally, before any I/O" true of the argument: without it a
      ``grant`` with an empty scope would mint an id and read a clock before the
      model refused it, and the refusal would arrive from inside a constructor
      rather than from the call.

    The order is **not** normalised here. That is the record's validator's job
    (:func:`ai_assistant.core.types._grant_scope`), which puts the members in
    declaration order so two implementations serialise one grant identically; doing
    it twice would be two places to keep agreeing.

    Args:
        value: The uses as the caller supplied them.
        name: The parameter's name, for the message.

    Returns:
        The same uses, materialised, in the caller's order.

    Raises:
        TypeError: If a member is not a ``GrantScope``.
        ValueError: If the scope is empty or names a use twice.
    """
    # Widened to ``object`` so the member check below is a *runtime* guard rather
    # than a statement mypy proves unreachable. The annotation says what a
    # conforming caller passes; this says what happens when one does not, which is
    # the same split :func:`page_argument` makes for ``1.5`` and ``True``.
    unchecked: tuple[object, ...] = tuple(value)
    snapshot: list[GrantScope] = []
    for use in unchecked:
        if not isinstance(use, GrantScope):
            msg = f"every member of {name} must be a GrantScope, got {use!r}"
            raise TypeError(msg)
        snapshot.append(use)
    if not snapshot:
        msg = (
            f"{name} must name at least one use: a grant authorising nothing still "
            f"reads as a grant, and still occupies the source's one live-grant slot "
            f"(ADR-0097 §2)"
        )
        raise ValueError(msg)
    if len(set(snapshot)) != len(snapshot):
        msg = f"{name} names each use at most once, got {tuple(snapshot)!r} (ADR-0097 §10)"
        raise ValueError(msg)
    return tuple(snapshot)

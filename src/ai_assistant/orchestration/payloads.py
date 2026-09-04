"""The engine surface's payload rules: canonical bytes, and the contract limit.

ADR-0084 §4 rules that the size limit is "part of the promoted Protocol's declared
contract, not a property of the transport, and *every* implementation enforces
it" — the in-process engine included — so that a client is never silently less
capable than the engine it stands in for, in **either** direction. ADR-0085 §8c
fixes what is measured and against what; **ADR-0087 fixes the bytes**, with
normative test vectors, because a limit is only one limit if both implementations
measure the same byte string.

This module is that measurement, and three placement facts decide where it sits.

* **`core` is foreclosed.** ADR-0084 §6 places "the envelope, the framing, the
  codec, the error mapping, and the client" in the `wire` package, and ADR-0085
  §8c states in as many words that "a ``core``-owned codec is the obvious
  alternative and ADR-0084 §6 forecloses it".
* **`wire` does not exist yet.** It is ADR-0084 §5's change 4; this is change 3,
  and ADR-0087 §6 is explicit that change 3 is where two implementations are first
  held to the limit, which is the whole reason the encoding was ratified ahead of
  it.
* **Sharing one encoder is permitted, and is the honest choice.** ADR-0087 §7
  rules that "two encoders may exist without the contract weakening", because
  conformance is defined by *output*: an encoder here and an encoder in `wire`
  that both pass §5's vectors are byte-identical whether or not they share a line
  of code. The converse also holds — one encoder cannot make two implementations
  disagree — so the canonical fake reaches for this one rather than growing a
  second copy to keep in step by hand. Where the in-process engine's encoder
  finally lives is ADR-0087 §9's open question, filed as change 4's; this is the
  answer change 3 needs, and it is deliberately a module the wire lane can move
  from rather than a `core` API it would have to keep.

**What is ratified elsewhere and merely obeyed here** is the encoding: ADR-0087
§2's five properties and §5's vectors. ``tests/orchestration/test_payloads.py``
asserts the vectors verbatim, which is what makes "conforming" a fact rather than
a claim.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.errors import OversizedValueError, UnusableIdentityError
from ai_assistant.core.types import (
    ACCOUNT_IDENTITY_MAX_BYTES,
    GrantScope,
    Identifier,
    NonBlankEncodableText,
    UtcInstant,
    describe_untrusted,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import SecretValue

#: The bytes ADR-0085 §8b reserves for the frame envelope, so a payload at the
#: contract limit still fits inside ``hub_max_frame_bytes``. The worst case ADR-0085
#: computes is 110 bytes — the member names, the punctuation, an 11-byte ``kind``, a
#: 36-byte correlation id and a 21-byte method name — and the slack is deliberate: a
#: later protocol version may add an envelope member (ADR-0084 §3 permits it), and a
#: reserve derived from today's exact worst case would silently become wrong the day
#: it does.
ENVELOPE_RESERVE_BYTES: Final[int] = 512

#: ADR-0085 §8d's floor on ``hub_max_frame_bytes``: 512 for the envelope reserve
#: plus 256 for either connect payload is 768, and 1024 leaves room for both
#: handshake frames and a small request besides. Stated here so the figure has one
#: home; the setting it bounds is ADR-0084 §3's and arrives with the hub.
MIN_FRAME_BYTES: Final[int] = 1024

#: ADR-0084 §3's named default for ``hub_max_frame_bytes``. That setting does not
#: exist in ``Settings`` yet — it arrives with the hub, and ADR-0085 §12 records
#: that the surface ADR "adds no setting" — so the default the engine and the
#: canonical fake carry is derived from the figure ADR-0084 already ratified.
DEFAULT_MAX_FRAME_BYTES: Final[int] = 16 * 1024 * 1024

#: The contract limit, ``hub_max_frame_bytes - 512`` (ADR-0085 §8c), at the frame
#: size ADR-0084 §3 defaults to. An implementation takes it as a constructor
#: argument so a deployment — and a conformance test — can set it; this is what it
#: gets by saying nothing.
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = DEFAULT_MAX_FRAME_BYTES - ENVELOPE_RESERVE_BYTES

#: The exclusive upper bound on a page argument (ADR-0073 §2). Refused rather than
#: clamped, and refused **locally, before any I/O** (ADR-0085 §9), so both
#: implementations refuse the same values without a round trip.
_PAGE_ARGUMENT_BOUND: Final[int] = 2**63

_SECONDS_PER_MINUTE: Final[int] = 60
_MINUTES_PER_HOUR: Final[int] = 60

_IDENTIFIER: Final = TypeAdapter[str](Identifier)
_NON_BLANK_TEXT: Final = TypeAdapter[str](NonBlankEncodableText)
_UTC_INSTANT: Final = TypeAdapter[datetime](UtcInstant)


def _instant(value: datetime) -> str:
    """Spell one instant as ADR-0087 §2d fixes it.

    ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z`` — the UTC designator is ``Z`` and never
    ``+00:00``, and the fractional part is absent when the microsecond field is
    zero and otherwise exactly six digits with trailing zeros kept.
    :data:`~ai_assistant.core.types.UtcInstant`'s validator has already converted
    any offset to UTC before this sees it, so an instant constructed at ``-05:00``
    and the same instant constructed at UTC are one value and one byte string.

    The components are formatted explicitly rather than through ``strftime``,
    whose ``%Y`` zero-padding is platform-dependent below the year 1000.
    """
    fraction = f".{value.microsecond:06d}" if value.microsecond else ""
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
        f"T{value.hour:02d}:{value.minute:02d}:{value.second:02d}{fraction}Z"
    )


#: ADR-0194 §5's plain/exponential boundary: below an adjusted exponent of -6 the
#: form is exponential, which is where ``Decimal("0.0000000001")`` becomes
#: ``"1E-10"`` rather than being spelled out.
_PLAIN_FORM_FLOOR: Final = -6


def _duration(value: timedelta) -> str:
    """Spell one duration as ADR-0087 §2e fixes it.

    ``[-]P[nD][T[nH][nM][n[.ffffff]S]]``, with the decomposition fixed rather than
    merely the alphabet: ``0 <= H < 24``, ``0 <= M < 60``, ``0 <= S < 60``. Without
    the ranges the grammar admits ``"PT61S"`` and ``"PT1M1S"`` for one value, which
    is the failure a canonical encoding exists to close reproduced inside its own
    rule. A zero component is omitted, the zero duration is ``PT0S``, and the
    seconds' fraction is present only when non-zero with trailing zeros trimmed.

    **The magnitude is taken first, and that is a trap worth naming.** Python
    stores a negative duration with a negative day field —
    ``timedelta(days=-1, seconds=1)`` is ``(-1, 1, 0)`` — so an encoder reading
    those fields directly would emit ``"-P1DT1S"``, which is -86401 seconds rather
    than the -86399 it was given.

    **No nominal component is ever emitted.** ``Y`` is forbidden outright: it does
    not denote a fixed elapsed time, so ``"P1Y"`` round-trips only because both
    halves privately agree a year is 365 days — and ADR-0084 §3 freezes this codec
    permanently, which is the worst possible place to embed a private convention
    that reads as a standard one. This is the one rule that moves a byte count, and
    the growth is at most three bytes (ADR-0087 §2e proves the bound).
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
# two ADR-0087 §2 gives *no* form are refused rather than guessed — has one place to
# look. Splitting it to satisfy the branch counters would move half the answer.
def _decimal(value: Decimal) -> str:
    """Spell one exact decimal as ADR-0194 §5 fixes it.

    The **to-scientific-string** form of the General Decimal Arithmetic
    specification, written out rather than delegated to ``str`` for ADR-0087 §1's
    reason: "whatever ``repr`` does" is not a wire contract, and a library's ``str``
    is the same objection. CPython 3.14's ``str`` reproduces this on every vector
    ADR-0194 §5 states and on 200,000 pseudo-random finite decimals, so an
    implementation *may* call ``str`` today and conform; what is ratified is the
    grammar, and this is what would catch an interpreter that stopped agreeing.

    **A JSON string and never a JSON number.** A number would be read back through
    a binary float on the far side, which is the one thing ADR-0194 §2's exact
    arithmetic forbids, and ADR-0087 §2c's ``float`` grammar is about a value that
    *is* a binary64 — this one is not.

    **The scale is carried and never normalised**, which follows from ADR-0087 §4
    rather than from taste: §4's relation is indistinguishability, and
    ``Decimal("1.0")`` and ``Decimal("1")`` differ under ``as_tuple()``, so they are
    two values and a spelling mapping both onto one would normalise. Nothing here
    consults ``decimal.getcontext()`` and nothing here performs arithmetic, so
    ADR-0194 §1's context-independence holds on the wire as it holds in the
    predicate.
    """
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover — the caller checks finiteness
        msg = f"a non-finite Decimal has no canonical encoding, so {value!r} cannot be measured"
        raise ValueError(msg)
    spelled = "".join(str(digit) for digit in digits)
    adjusted = exponent + len(digits) - 1
    if exponent <= 0 and adjusted >= _PLAIN_FORM_FLOOR:
        if exponent == 0:
            body = spelled
        elif adjusted >= 0:
            point = len(spelled) + exponent
            body = f"{spelled[:point]}.{spelled[point:]}"
        else:
            body = "0." + "0" * (-adjusted - 1) + spelled
    else:
        head, rest = spelled[0], spelled[1:]
        coefficient = f"{head}.{rest}" if rest else head
        body = f"{coefficient}E{'+' if adjusted >= 0 else '-'}{abs(adjusted)}"
    return f"-{body}" if sign else body


def project(value: object) -> Any:  # noqa: C901, PLR0911, PLR0912
    """Render one value into the plain JSON types ADR-0087 §2's recipe encodes.

    The first half of the canonical encoding: ``json.dumps`` cannot render a
    ``datetime``, a ``timedelta``, a ``Decimal`` or a ``StrEnum``, so a projection runs first and
    produces the scalars' spellings. The second half is :func:`canonical_payload`.

    **The projection is written out rather than delegated to
    ``model_dump(mode="json")``**, and the reason is ADR-0087 §3's second row: that
    projection renders a duration of 365 days or more with a nominal ``Y``
    component, which §2e forbids. Handling every scalar in one place is also what
    makes the two values with no encoding — a lone surrogate ``str`` and a
    non-finite ``float`` — refused here rather than at three different depths.

    Args:
        value: Any value the promoted surface can carry.

    Returns:
        The same value as plain JSON types: ``dict``, ``list``, ``str``, ``int``,
        ``float``, ``bool`` or ``None``.

    Raises:
        ValueError: If a string has no UTF-8 encoding, or a ``float`` or a
            ``Decimal`` is not finite.
            Both are values ADR-0087 §2 gives no wire form, and §7 fixes that they
            are refused before measurement rather than substituted.
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
    if isinstance(value, Decimal):
        # **A string, not a number** (ADR-0194 §5). Spelled here as well as in
        # ``wire/codec.py`` for this module's standing reason: ADR-0087 §7 defines
        # conformance by *output*, so "two encoders may exist without the contract
        # weakening" — and `orchestration` may not import `wire`. What is ratified is
        # the grammar, and both spell it.
        if not value.is_finite():
            msg = f"a non-finite Decimal has no canonical encoding, so {value!r} cannot be measured"
            raise ValueError(msg)
        return _decimal(value)
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


def _encode(projection: Any) -> bytes:
    """Run ADR-0087 §2's recipe over an already-projected value.

    ``allow_nan=False`` is load-bearing rather than decorative (ADR-0087 §3 row 3):
    without it ``json.dumps`` writes the non-JSON tokens ``NaN`` and ``Infinity``.
    :func:`project` has already refused those, so this is the second of two
    guards on the same value rather than the only one.
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
        contract limit and what a transport writes. One encoding serves both jobs,
        so measurement and transmission can never disagree.
    """
    return _encode(project(value))


#: What a JSON string costs before any of its characters do — the two quotes
#: :func:`encoded_text_bytes` counts. Named so that a caller accumulating a value's
#: cost can add *bodies* rather than whole encodings, which is what makes that
#: arithmetic additive over concatenation (ADR-0173 §3).
JSON_STRING_QUOTE_BYTES: Final[int] = 2


def encoded_text_bytes(text: str) -> int:
    """How many bytes ``text`` occupies as a JSON string in the canonical encoding.

    The quotes included, so it is exactly what one string member's *value*
    contributes to :func:`canonical_payload`'s output at whatever position it sits.

    **It is additive over concatenation, and that is what it is for** (ADR-0173 §3).
    ADR-0087 §2's recipe escapes a JSON string character by character and
    ``ensure_ascii=False`` leaves every other code point as its own UTF-8 bytes, so
    the escaped body of ``a + b`` is the escaped body of ``a`` followed by that of
    ``b``. A caller bounding a value it is accumulating can therefore keep a running
    total instead of re-encoding the whole of it on every step, which is the
    difference between the composing stage's ceiling costing linear work and
    quadratic.

    Args:
        text: The string to measure.

    Returns:
        The byte length of its canonical JSON form, ``2`` for the empty string.
    """
    return len(_encode(text))


def _largest_member(projection: Any) -> str | None:
    """Name the top-level member that contributed most to the payload's size.

    ADR-0085 §9 makes this a rule rather than a judgement, because ``details`` is
    reconstructed on the far side and must match: two implementations naming
    different members for one payload would break the round-trip contract. The
    rule is the member whose **own** canonical encoding is longest, ties broken by
    the member name's bytes in ascending order, and ``None`` where the payload has
    no named members — a listing result is a bare array, a ``forget`` result a bare
    ``true``.

    Iterating in sorted order and keeping a strict improvement is what implements
    the tie-break: the first member reached wins, and sorted order is ascending by
    the name's code points, which for the ASCII parameter and field names on this
    surface is ascending by its bytes.
    """
    if not isinstance(projection, dict) or not projection:
        return None
    largest: str | None = None
    largest_size = -1
    for name in sorted(projection):
        size = len(_encode(projection[name]))
        if size > largest_size:
            largest, largest_size = name, size
    return largest


def check_payload(value: object, *, max_bytes: int, subject: str) -> None:
    """Refuse a payload the contract does not admit (ADR-0085 §8c).

    **The byte bound is spelled ``max_bytes`` and not ``limit``** so that
    :func:`check_arguments` can carry an argument *named* ``limit`` — which four
    methods on this surface have. A member the wire would call ``limit`` and this
    module called something else would put a name in
    :attr:`~ai_assistant.core.errors.OversizedValueError.field` that no parameter
    has, and ADR-0085 §9 makes that field a value the far side reconstructs.

    Args:
        value: The payload to measure.
        max_bytes: The contract limit in bytes.
        subject: What is being measured, for the message — ``"the arguments to
            converse()"``, ``"the result of beliefs()"``.

    Raises:
        OversizedValueError: If the payload's canonical encoding exceeds
            ``max_bytes``.
        ValueError: If the payload holds a value with no canonical encoding, which
            is refused **before** measurement rather than measured (ADR-0087 §7).
    """
    projection = project(value)
    size = len(_encode(projection))
    if size <= max_bytes:
        return
    field = _largest_member(projection)
    largest = "" if field is None else f"; the largest member is {field!r}"
    msg = f"{subject} encodes to {size} bytes, over the {max_bytes}-byte contract limit{largest}"
    raise OversizedValueError(msg, limit=max_bytes, size=size, field=field)


def check_arguments(method: str, *, max_bytes: int, **arguments: object) -> None:
    """Refuse a call whose argument payload the contract does not admit.

    **An argument the caller did not pass is absent, not ``null``** (ADR-0085 §10),
    and on this surface every argument whose absence is expressible has ``None`` for
    its declared default — so a ``None`` here *is* "not passed" and is dropped from
    the object.

    **Everything else is present, including a paging ``limit`` whose value came from
    the default.** ADR-0087 §7 fixes the order as decode, validate, **then** measure
    — "the receiver decodes, validates into the declared type, and measures the
    canonical encoding of the validated value" — and a validated call has its
    defaults applied. Measuring the applied value is also the conservative
    direction: it can never admit a payload the receiver would go on to refuse.

    Args:
        method: The method being called, for the message.
        max_bytes: The contract limit in bytes, spelled so that an argument may be
            called ``limit`` (:func:`check_payload`).
        **arguments: The call's arguments, named exactly as the Python parameters
            are. Members are sorted by the encoding, so the caller's keyword order
            is not observable — ``f(b=…, a=…)`` and ``f(a=…, b=…)`` are one call
            and one byte string.

    Raises:
        OversizedValueError: If the argument object's canonical encoding exceeds
            ``max_bytes``.
    """
    passed = {name: value for name, value in arguments.items() if value is not None}
    check_payload(passed, max_bytes=max_bytes, subject=f"the arguments to {method}()")


def utc_instant(value: object, *, name: str) -> datetime:
    """Validate one timezone-aware instant argument, before any I/O (ADR-0085 §9).

    :func:`identifier`'s shape for the surface's first
    :data:`~ai_assistant.core.types.UtcInstant` **arguments** (ADR-0235 §1, §4), and
    it exists because the annotation alone enforces nothing in process.
    ``UtcInstant`` is a pydantic ``Annotated`` alias: a wire request is validated
    against it by ``wire/surface.py`` before dispatch, and an in-process caller hands
    the value straight through. Without this the two implementations refuse different
    values, which is exactly what §9 forbids.

    **Two failures it closes, and the second is the quiet one.** A naive
    ``datetime`` reaches a comparison against an aware one and raises a bare
    ``TypeError`` — not an :class:`~ai_assistant.core.errors.AssistantError`, so it
    escapes a command's error boundary as an uncaught traceback, the failure ADR-0042
    §7 forbids. And ADR-0087 §2d's encoder spells every instant with a ``Z``, so a
    naive value that reached the wire would be **relabelled as UTC** rather than
    refused: an expiry an hour or eight wrong, recorded as though the user had chosen
    it. ADR-0023 §3 is the clause both rest on — ``core`` cannot tell a dropped offset
    from a wall-clock time, so it refuses rather than attributing one.

    **The value is returned normalised**, which is the load-bearing half:
    ``UtcInstant`` converts an aware value to UTC, and ADR-0023 §2's reason for that
    is comparison — two aware datetimes sharing a ``tzinfo`` compare by wall clock and
    ignore ``fold``, so an unconverted value is orderable and chronologically false
    for one hour a year. Every comparison this argument reaches is an ordering one.

    Args:
        value: The instant as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The instant, in UTC.

    Raises:
        TypeError: If the value is not a ``datetime``. Checked before the offset,
            for :func:`page_argument`'s reason: a ``str`` that pydantic would parse
            is a caller passing the wrong thing, and parsing it would make the
            in-process surface accept what no annotation declares.
        ValueError: If it carries no determinate offset (ADR-0023 §3).
    """
    if not isinstance(value, datetime):
        msg = f"{name} must be a timezone-aware datetime, got {describe_untrusted(value)}"
        raise TypeError(msg)
    try:
        return _UTC_INSTANT.validate_python(value)
    except ValidationError as exc:
        msg = (
            f"{name} must carry a determinate UTC offset: a naive instant is a "
            f"wall-clock time or a dropped offset and this layer cannot tell them "
            f"apart, so it refuses rather than attributing one (ADR-0023 §3)"
        )
        raise ValueError(msg) from exc


def identifier(value: str, *, name: str) -> str:
    """Validate and normalise one identifier argument (ADR-0085 §3c).

    **The clause carries the whole of :data:`~ai_assistant.core.types.Identifier`,
    not half of it**: it both *rejects* a blank value and *strips* surrounding
    whitespace from the value the implementation then uses. Stating the
    normalisation is the load-bearing half — a rule that said only "reject blank"
    would leave stripping optional, and optional normalisation on an *identity*
    argument makes the answer to ``belief(" rec-1 ")`` a property of which
    implementation you are holding: a wire client deserialising through
    ``Identifier`` would find the record, and an in-process engine handed the raw
    ``str`` would answer ``None``.

    Args:
        value: The identifier as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The identifier stripped, which is what the implementation then uses.

    Raises:
        ValueError: If the identifier is blank, or has no UTF-8 encoding. Refused
            locally, before any I/O, so both implementations refuse the same values
            without a round trip.
    """
    try:
        return _IDENTIFIER.validate_python(value)
    except ValidationError as exc:
        msg = f"{name} must be a non-blank identifier"
        raise ValueError(msg) from exc


def page_argument(value: int, *, name: str) -> int:
    """Refuse a malformed page argument, locally (ADR-0073 §2, ADR-0085 §9).

    The store refuses rather than clamps, and this refuses at the same values one
    step earlier so neither implementation is silently more permissive than the
    other. A ``ValueError`` and deliberately **not** an
    :class:`~ai_assistant.core.errors.AssistantError`: it is a caller programming
    error rather than a condition of the system, so an adapter that lets a user
    supply either should refuse an out-of-range value at its own parse boundary.

    **The type is checked before the range, and a ``bool`` is excluded**, in the
    guard shape :class:`~ai_assistant.orchestration.engine.Engine`'s own
    ``max_outstanding_confirmations`` and ``LearningLoop``'s retrieval limit
    already use. Neither half is pedantry:

    * ``0 <= 1.5 < 2**63`` is *true*, so a range check alone admits a float — which
      then reaches the store and fails inside slice arithmetic, after I/O has begun
      and as a ``TypeError`` from somewhere the caller cannot place. That is exactly
      what the "refused locally, before any I/O" clause exists to stop.
    * ``True`` is an ``int`` and would silently mean a page size of one. A flag is
      not a count, and a page of one returned for ``limit=True`` is a wrong answer
      rather than a refusal.

    A wrong *type* is a ``TypeError`` and a wrong *value* a ``ValueError``, which is
    also what keeps ADR-0085 §9's declaration honest: the clause declares
    ``ValueError`` for a limit or offset "outside ``[0, 2**63)``", and ``1.5`` is
    not outside that interval — it is not a page argument at all.

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
    surface whose range and its store's do not coincide. ADR-0085 §9 admits a page
    argument in ``[0, 2**63)``; ``SourceGrantStore.recent`` requires a **strictly
    positive** ``limit``, for ``AuditTrail.recent``'s reason — a store issuing
    ``LIMIT ?`` against SQLite turns ``limit=-1`` into no limit at all. So
    ``recent_grants(limit=0)`` is well-formed under the surface rule and refused by
    the store, and ADR-0102 §10 resolves that by refusing it locally in **every**
    implementation, which is ADR-0085 §9's own clause: "so both implementations
    refuse the same values without a round trip and neither is silently more
    permissive".

    The type guard is :func:`page_argument`'s unchanged, including the ``bool``
    exclusion — ``True`` is an ``int`` that would silently mean a page of one, and
    that is a wrong answer rather than a refusal.

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


#: The Unicode general categories ADR-0149 §4's "no control character, no line
#: break" excludes. ``Cc`` is every C0 and C1 control; ``Zl`` and ``Zp`` are the
#: two separators that are line breaks without being controls; and ``Cf`` is the
#: **format** controls, which are controls by function even though the name
#: "control character" is often read as ``Cc`` alone.
#:
#: **``Cf`` is here because ADR-0151 §5's display clause depends on it.** That
#: clause requires every client accepting an identity to display it to the user as
#: part of the act, and ADR-0149 §4's third answer to a credential pasted into the
#: identity field is precisely that the value is *seen*. ``U+202E`` RIGHT-TO-LEFT
#: OVERRIDE and its siblings (``U+202A`` to ``U+202E``, ``U+2066`` to ``U+2069``) exist to
#: reorder what is rendered, so an identity carrying one is displayed as something
#: other than what is recorded — which defeats the one ingredient that failure
#: needs. ``U+FEFF``, ``U+200B`` and ``U+00AD`` are the same class of invisible
#: differences between two identities that read alike.
#:
#: **The cost is named rather than discovered**: an identity containing a zero-width
#: joiner — an emoji sequence, or some Indic and Persian spellings — is refused too.
#: That is accepted. An account identity is a handle in a field ADR-0149 §4 already
#: strips of controls and line breaks, and a rendering that cannot be trusted is
#: worse than a spelling that cannot be used.
_UNPRINTABLE_CATEGORIES: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})


def _refuse_unusable_identity(identity: str, *, plaintext: str) -> None:
    """ADR-0151 §5's three refusals, over a plaintext the caller already holds.

    **Private, and takes the plaintext rather than the holder**, so that the one
    site in this package materialising a credential is
    :func:`check_provisioning_call` and nothing else. `wire/codec.py` carries its
    own public ``usable_identity`` for the client, which unwraps under ADR-0151
    §6's explicit authorisation and measures in ``_call`` against the limit the hub
    published — a different shape for a different layer, and the duplication
    ``pyproject.toml`` explains for every other validator in these two modules.

    **It is an ``AssistantError`` rather than ADR-0085 §9's ``ValueError``, and the
    distinction is §9's own** (ADR-0151 §2a). §9's ``ValueError`` is "a caller
    programming error rather than a condition of the system"; an identity is a
    value the **user typed**, and a person pasting a token into the wrong field has
    not made a programming error. ``wire/server.py`` converts an ``AssistantError``
    into an error frame and lets anything else close the connection — and a dropped
    socket is the worst available outcome on a call that carries a credential,
    because the natural response to one is to retry it.

    **One class for all three refusals**, on ADR-0151 §2a's test: in every case the
    recourse is to supply a different identity, so one class is right and three
    would be surface with no consumer. **Nothing is normalised** — ADR-0149 §4
    forbids stripping, case-folding, case-normalising or Unicode-normalising a
    caller-supplied identity "at the surface", and this is the surface.

    Args:
        identity: The account identity as the caller passed it.
        plaintext: The credential supplied in the same call, already unwrapped by
            whoever is entitled to. It is compared and discarded; no branch below
            names it, any part of it, or its length.

    Raises:
        UnusableIdentityError: On :func:`usable_identity`'s terms.
    """
    if any(unicodedata.category(char) in _UNPRINTABLE_CATEGORIES for char in identity):
        msg = (
            "an account identity is single-line printable text: no control character "
            "and no line break (ADR-0149 §4). Nothing was written and no credential "
            "was sent"
        )
        raise UnusableIdentityError(msg)
    # **Exact equality, and nothing else** (ADR-0151 §5): not a hash, not a prefix,
    # and never after a write. Reading the plaintext here is the comparison ADR-0149
    # §4 requires; it is compared and discarded, and the branch below names neither
    # side of it.
    if identity == plaintext:
        msg = (
            "the account identity is the same value as the credential, so the "
            "credential was very likely pasted into the identity field. Nothing was "
            "written and no credential was sent (ADR-0149 §4)"
        )
        raise UnusableIdentityError(msg)
    if len(identity.encode("utf-8")) > ACCOUNT_IDENTITY_MAX_BYTES:
        msg = (
            f"an account identity encodes to at most {ACCOUNT_IDENTITY_MAX_BYTES} "
            f"UTF-8 bytes (ADR-0149 §4, ADR-0151 §5). Nothing was written and no "
            f"credential was sent"
        )
        raise UnusableIdentityError(msg)


def check_provisioning_call(
    method: str, *, max_bytes: int, identity: str, credential: SecretValue, **arguments: object
) -> None:
    """Every local refusal a provisioning call owes, over **one** read of the secret.

    ADR-0151 §5's three identity refusals and §11's frame measurement, in one
    function because they need the same value and `orchestration` may hold it once.

    **One plaintext site in this package, and it is the one ADR-0151 §5
    mandates.** §5 requires the identity to be compared "as an exact string
    comparison, to the plaintext of the ``credential`` supplied in the same call",
    "before the first of ADR-0148 §6's three writes", "in every implementation" —
    so the in-process engine reads the plaintext whether or not anything else
    does. §11 then requires that "where a provisioning call's arguments do not fit
    the configured frame, the call raises ``OversizedValueError`` and nothing is
    written", and ADR-0085 §9 makes a local refusal every implementation's, which
    is the only way ADR-0084 §4's substitutability survives a credential-carrying
    call: measured any other way, the in-process engine carries out a request the
    wire client refuses, having written a credential into the keyring.

    Doing both here is what keeps the count at one. An earlier shape measured in a
    second function and gave `orchestration` two plaintext-handling sites where §5
    obliges one — which adversarial review reported, correctly, as a widening of
    ADR-0151 §6's relay clause rather than an application of §11.

    **§6's relay clause stays true of everything else.** The plaintext is a local
    that is compared, encoded for its length, and dropped: it is not logged, not
    retained beyond the call, not copied into any other value, not returned, and
    never read back. ``project`` stays closed to ``SecretStr`` (ADR-0151 §6), so
    nothing here gives the codec, a pydantic serialiser or any other general
    mechanism an automatic unwrap.

    **No message names the credential or its length** (ADR-0125 §6).
    :func:`check_payload` reports the whole payload's size and names its largest
    *member*, and the member is spelled ``credential`` — which ADR-0151 §6 requires
    anyway, so ``core/logging.py``'s key-name redaction covers it wherever a
    payload mapping is logged.

    Args:
        method: The method being called, for the message.
        max_bytes: The contract limit in bytes.
        identity: The account identity, already refused blank or unwritable by
            :func:`non_blank_text`.
        credential: The secret this call carries, still wrapped.
        **arguments: The call's other arguments, named as the parameters are.

    Raises:
        UnusableIdentityError: If the identity is one ADR-0149 §4 does not admit.
            Raised **before** the measurement, so an unusable identity is refused
            on its own terms rather than reported as an oversized payload.
        OversizedValueError: If the argument object's canonical encoding exceeds
            ``max_bytes``. Nothing is written, nothing is truncated, and raising
            ``hub_max_frame_bytes`` is the operator's only remedy (ADR-0151 §11).
    """
    plaintext = credential.get_secret_value()
    _refuse_unusable_identity(identity, plaintext=plaintext)
    check_arguments(
        method, max_bytes=max_bytes, credential=plaintext, identity=identity, **arguments
    )

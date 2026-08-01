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
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import Identifier, encodable_text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
def project(value: object) -> Any:  # noqa: C901, PLR0911
    """Render one value into the plain JSON types ADR-0087 §2's recipe encodes.

    The first half of the canonical encoding: ``json.dumps`` cannot render a
    ``datetime``, a ``timedelta`` or a ``StrEnum``, so a projection runs first and
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
        ValueError: If a string has no UTF-8 encoding, or a float is not finite.
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

    Args:
        value: The page argument as the caller passed it.
        name: The parameter's name, for the message.

    Returns:
        The value, unchanged.

    Raises:
        ValueError: If the value falls outside ``[0, 2**63)``.
    """
    if not 0 <= value < _PAGE_ARGUMENT_BOUND:
        msg = f"{name} must be in [0, 2**63), got {value}"
        raise ValueError(msg)
    return value

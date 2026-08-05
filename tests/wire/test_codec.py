"""ADR-0087's normative vectors, asserted against the wire's own encoder.

    **Every byte string below is normative.** A conforming encoder reproduces it
    exactly. … They are not documentation. Each one is a line of a conformance test
    the wire lane writes: encode the input, compare to the byte string, compare the
    length. (ADR-0087 §5, §5f)

This is that test. Two things are asserted of every vector and the second is the
one that makes #571's answer safe:

1. the wire encoder reproduces the ratified bytes, and their count;
2. :func:`ai_assistant.orchestration.payloads.canonical_payload` — the encoder the
   *in-process* engine measures with — produces the same bytes.

**The second assertion is the whole of what licenses two encoders.** ADR-0087 §7
rules that "two encoders may exist without the contract weakening… because
conformance is defined by output, an encoder inside `wire` and an encoder the
in-process engine reaches for are byte-identical if both pass §5, whether or not
they share a line of code". The ratified placements leave no third option — `wire`
may import only `core`, `orchestration` importing `wire` engages golden rule 1
(ADR-0087 §9), and a `core`-owned codec is foreclosed by ADR-0085 §8c — so the
guarantee has to be a *test*, and this is it. A divergence fails the gate on the
round it is introduced rather than on the day a client and a hub disagree about
which calls are refused.

Together the vectors "discriminate the encoding from every near-miss measured
while writing this ADR — ``model_dump_json()``, ``json.dumps`` without
``sort_keys``, ``ensure_ascii=True``, a trimmed fractional second, a ``-0.0``
normalised away, and a duration with a year component" (§5f). The last section
below runs exactly those six near-misses and watches each one fail.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter

from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    Confirmation,
    ContinuationToken,
    Evidence,
    MemoryKind,
)
from ai_assistant.orchestration.payloads import canonical_payload as engine_encode
from ai_assistant.wire.codec import canonical_payload


def _both(value: object) -> bytes:
    """Encode with the wire's encoder, and assert the engine's agrees.

    Every vector goes through here rather than asserting the wire alone, so ADR-0087
    §7's "byte-identical if both pass §5" is checked on each case rather than
    inferred from the two suites happening to hold the same table.
    """
    encoded = canonical_payload(value)
    assert engine_encode(value) == encoded, (
        "the wire's encoder and the in-process engine's disagree; ADR-0087 §7 permits "
        "two encoders only because conformance is defined by output"
    )
    return encoded


# --- §5a. Strings ----------------------------------------------------------

_STRINGS: list[tuple[str, bytes, int]] = [
    ("a/b", b'"a/b"', 5),
    ("a\\b", b'"a\\\\b"', 6),
    ('say "hi"', b'"say \\"hi\\""', 12),
    ("a\tb\nc", b'"a\\tb\\nc"', 9),
    ("\r\b\f", b'"\\r\\b\\f"', 8),
    ("\x00\x1f", b'"\\u0000\\u001f"', 14),
    ("\x7f", b'"\x7f"', 3),
    ("café", b'"caf\xc3\xa9"', 7),
    ("日本語", b'"\xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e"', 11),
    ("\U0001f600", b'"\xf0\x9f\x98\x80"', 6),
    ("\u2028", b'"\xe2\x80\xa8"', 5),
    ("", b'""', 2),
]


@pytest.mark.parametrize(("value", "expected", "size"), _STRINGS)
def test_a_string_takes_its_ratified_bytes(value: str, expected: bytes, size: int) -> None:
    """§5a, verbatim.

    The U+0000/U+001F row fixes the escape *case* — ``\\u001f``, lowercase hex —
    and the U+007F and U+2028 rows fix that the escaping stops at U+0020 and does
    not resume: both are emitted raw, because they are "only a hazard for a consumer
    that evaluates JSON as JavaScript source, which nothing here does" (§2b).
    """
    assert _both(value) == expected
    assert len(expected) == size


def test_a_lone_surrogate_has_no_wire_form() -> None:
    """§2b: refused rather than substituted with U+FFFD or escaped through.

    Refusing is what keeps ADR-0087 §7's ordering meaningful — a value with no
    canonical form must not reach the measurement step — and it is the *encoder*
    that refuses rather than the frame, because "the place a non-encodable value is
    refused is the type, not the frame".
    """
    with pytest.raises(ValueError, match="UTF-8"):
        canonical_payload("\ud800")


# --- §5b. Numbers ----------------------------------------------------------

_NUMBERS: list[tuple[object, bytes, int]] = [
    (0.0, b"0.0", 3),
    (-0.0, b"-0.0", 4),
    (1.0, b"1.0", 3),
    (0.1, b"0.1", 3),
    (0.1 + 0.2, b"0.30000000000000004", 19),
    (1e-4, b"0.0001", 6),
    (1e-5, b"1e-05", 5),
    (1e-7, b"1e-07", 5),
    (1e15, b"1000000000000000.0", 18),
    (1e16, b"1e+16", 5),
    (0, b"0", 1),
    (2**63, b"9223372036854775808", 19),
    (-1.5670905694168156e-99, b"-1.5670905694168156e-99", 23),
]


@pytest.mark.parametrize(("value", "expected", "size"), _NUMBERS)
def test_a_number_takes_its_ratified_bytes(value: object, expected: bytes, size: int) -> None:
    """§5b, verbatim.

    The ``1e-4``/``1e-5`` and ``1e15``/``1e16`` pairs are the two thresholds where
    the exponent form begins, and ``1e-05``/``1e-07`` fix the two-digit exponent
    padding. Those four are the vectors ``pydantic-core``'s own formatter does not
    satisfy — it writes ``0.00001`` and ``1e-7`` — which is §1's worked example of
    why "the shortest decimal that round-trips" is a property and not a
    specification. ``-1.5670905694168156e-99`` is the tie-break witness: ``…155`` is
    equally short and round-trips too, and is not chosen.
    """
    assert _both(value) == expected
    assert len(expected) == size


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_a_non_finite_float_has_no_wire_form(value: float) -> None:
    """§2c: neither of the two things a library does by default is acceptable.

    ``json.dumps`` emits the non-JSON tokens ``NaN`` and ``Infinity``; pydantic
    emits ``null``, "which turns a value into a different value silently".
    """
    with pytest.raises(ValueError, match="non-finite"):
        canonical_payload(value)


_EQUAL_BUT_DISTINCT: list[tuple[object, bytes, int]] = [
    ({"x": 1}, b'{"x":1}', 7),
    ({"x": True}, b'{"x":true}', 10),
    ({"x": 1.0}, b'{"x":1.0}', 9),
    ({"x": 0.0}, b'{"x":0.0}', 9),
    ({"x": -0.0}, b'{"x":-0.0}', 10),
]


@pytest.mark.parametrize(("value", "expected", "size"), _EQUAL_BUT_DISTINCT)
def test_five_equal_values_keep_five_spellings(value: object, expected: bytes, size: int) -> None:
    """§5b's witness that §4's equivalence is indistinguishability, not ``==``.

    All five compare equal in Python — ``1 == True == 1.0`` and ``0.0 == -0.0`` —
    and all five are distinct *values*: each decodes back to the Python object it
    came from, and collapsing any of them "would destroy information rather than
    canonicalise it". Signed zero makes the point sharpest: the sign is observable
    with one call to ``math.copysign``, so an implementation that normalised it
    "would hand a wire client different data from the one the in-process engine
    returns, which is precisely ADR-0084 §4's divergence, committed in the name of
    preventing it".
    """
    assert _both(value) == expected
    assert len(expected) == size


def test_the_five_spellings_are_five_distinct_byte_strings() -> None:
    """The discriminating half: a normalising encoder would collapse some of them."""
    assert len({expected for _value, expected, _size in _EQUAL_BUT_DISTINCT}) == 5


def test_a_float_keeps_a_decimal_point_so_its_type_survives() -> None:
    """§4a: "``2.0`` would encode as ``2`` and come back an ``int``".

    Load-bearing rather than cosmetic, and only inside ``FrozenJson`` — the one
    deliberately untyped holder, where "the JSON form itself carries the type"
    because six arms map onto six distinct JSON productions.
    """
    assert json.loads(canonical_payload({"x": 2.0})) == {"x": 2.0}
    assert isinstance(json.loads(canonical_payload({"x": 2.0}))["x"], float)
    assert isinstance(json.loads(canonical_payload({"x": 2}))["x"], int)


# --- §5c. Instants ---------------------------------------------------------

_AT = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

_INSTANTS: list[tuple[datetime, bytes, int]] = [
    (_AT, b'{"d":"2026-08-01T12:00:00Z"}', 28),
    (
        datetime(2026, 8, 1, 7, 0, 0, tzinfo=UTC).astimezone(UTC),
        b'{"d":"2026-08-01T07:00:00Z"}',
        28,
    ),
    (_AT.replace(microsecond=123456), b'{"d":"2026-08-01T12:00:00.123456Z"}', 35),
    (_AT.replace(microsecond=100000), b'{"d":"2026-08-01T12:00:00.100000Z"}', 35),
    (_AT.replace(microsecond=1), b'{"d":"2026-08-01T12:00:00.000001Z"}', 35),
]


@pytest.mark.parametrize(("value", "expected", "size"), _INSTANTS)
def test_an_instant_takes_its_ratified_bytes(value: datetime, expected: bytes, size: int) -> None:
    """§5c: ``Z`` and never ``+00:00``, six digits with trailing zeros kept.

    Fixed width is ratified rather than trimmed "deliberately and against the
    symmetry with §2e": trimming would make the fractional part's *width* depend on
    the value, "which is a second thing to get right for no benefit a 16 MiB budget
    can notice".
    """
    assert _both({"d": value}) == expected
    assert len(expected) == size


def test_an_offset_instant_and_a_utc_one_are_one_byte_string() -> None:
    """§4(ii)'s witness: the *type* normalised, so the encoder did not have to.

    A ``UtcInstant``'s validator converts any offset to UTC before the encoder sees
    it, so this is "the encoding inheriting a property the type already enforces
    rather than establishing one".
    """
    elsewhere = datetime(2026, 8, 1, 7, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _both({"d": elsewhere.astimezone(UTC)}) == b'{"d":"2026-08-01T11:00:00Z"}'


# --- §5d. Durations --------------------------------------------------------

_DURATIONS: list[tuple[timedelta, bytes, int]] = [
    (timedelta(0), b'"PT0S"', 6),
    (timedelta(seconds=30), b'"PT30S"', 7),
    (timedelta(days=2, seconds=3), b'"P2DT3S"', 8),
    (timedelta(seconds=172803), b'"P2DT3S"', 8),
    (timedelta(hours=24), b'"P1D"', 5),
    (timedelta(minutes=90), b'"PT1H30M"', 9),
    (timedelta(seconds=61), b'"PT1M1S"', 8),
    (timedelta(minutes=60), b'"PT1H"', 6),
    (timedelta(microseconds=500000), b'"PT0.5S"', 8),
    (timedelta(microseconds=1), b'"PT0.000001S"', 13),
    (timedelta(seconds=-30), b'"-PT30S"', 8),
    (timedelta(days=-1, seconds=1), b'"-PT23H59M59S"', 14),
    (timedelta(days=365), b'"P365D"', 7),
    (timedelta(days=1095), b'"P1095D"', 8),
    (timedelta(days=360991935), b'"P360991935D"', 13),
    (timedelta.max, b'"P999999999DT23H59M59.999999S"', 30),
]


@pytest.mark.parametrize(("value", "expected", "size"), _DURATIONS)
def test_a_duration_takes_its_ratified_bytes(value: timedelta, expected: bytes, size: int) -> None:
    """§5d, verbatim — including the four rows the library gets wrong.

    ``timedelta(days=365)`` is ``"P1Y"`` under pydantic and ``"P365D"`` here,
    because ISO-8601's ``Y`` is a *nominal* component that "does not denote a fixed
    elapsed time", and ADR-0084 §3 freezes this codec permanently — "the worst
    possible place to embed a private convention that reads as a standard one".

    ``timedelta(seconds=61)`` and ``timedelta(minutes=60)`` are the range rule:
    without ``0 <= M < 60`` the grammar admits ``"PT61S"`` and ``"PT1M1S"`` for one
    value, "which is the whole failure this ADR exists to close, reproduced inside
    its own rule". ``timedelta(days=-1, seconds=1)`` is the sign trap: Python stores
    it as ``(-1, 1, 0)``, so an encoder reading those fields directly emits
    ``"-P1DT1S"`` — -86401 seconds rather than the -86399 it was given.
    """
    assert _both(value) == expected
    assert len(expected) == size


def test_two_spellings_of_one_duration_are_one_encoding() -> None:
    """§5d rows 3 and 4: the *type* answers this, not a decision.

    ``timedelta`` normalises on construction, so ``timedelta(seconds=172803)`` and
    ``timedelta(days=2, seconds=3)`` "are the same object state, ``==``, with the
    same ``.days``/``.seconds``/``.microseconds``". Worth a test because it "reads
    like a live fork and is not one".
    """
    assert canonical_payload(timedelta(seconds=172803)) == canonical_payload(
        timedelta(days=2, seconds=3)
    )
    assert canonical_payload(timedelta(hours=24)) == canonical_payload(timedelta(days=1))


@pytest.mark.parametrize(
    ("value", "growth"),
    [
        (timedelta(days=1095), 3),
        (timedelta(days=360991935), 3),
        (timedelta(days=365), 2),
        (timedelta(days=1000), -1),
        (timedelta(days=4000), -2),
        (timedelta.max, 0),
        (timedelta(days=364), 0),
    ],
)
def test_the_canonical_duration_never_grows_by_more_than_three_bytes(
    value: timedelta, growth: int
) -> None:
    """§2e's proved bound, checked at both ends of its range and below it.

    The bound is *proved* rather than sampled — "an earlier draft of this ADR
    sampled it, got two bytes, and was wrong" — and it is the one rule in §2 that
    moves a byte count, which is why ADR-0085 §8 re-checked every figure it derives
    against it. Asserting the exact delta rather than ``<= 3`` is what makes this a
    witness of the proof rather than of a bound nobody would notice loosening.
    """
    library = TypeAdapter(timedelta).dump_json(value)
    assert len(canonical_payload(value)) - len(library) == growth


def test_no_duration_carries_a_nominal_component() -> None:
    """§2e's outright refusal, over the whole range rather than the vectors.

    Stated over a walk because the rule is over the type: a ``Y`` that appeared for
    some day count no vector happens to name would be exactly the "private
    convention that reads as a standard one" the refusal exists to prevent.
    """
    for days in (0, 1, 364, 365, 366, 730, 1095, 100_000, 999_999_999):
        assert b"Y" not in canonical_payload(timedelta(days=days))


# --- §5e. Composite payloads ------------------------------------------------


def test_a_payload_that_is_not_a_model_needs_no_wrapper() -> None:
    """§5e: "The payload is any JSON value, encoded by §2."

    No wrapper object, no envelope inside the envelope, and no distinction between
    a model and anything else — which is why a ``forget`` result is four bytes and
    an empty page is two.
    """
    assert _both(True) == b"true"
    assert _both(None) == b"null"
    assert _both(()) == b"[]"


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            {"utterance": "hi", "timeout": timedelta(seconds=30)},
            b'{"timeout":"PT30S","utterance":"hi"}',
        ),
        ({"record_id": "r-1"}, b'{"record_id":"r-1"}'),
        ({"bands": [BeliefBand.ASSERTED], "limit": 50}, b'{"bands":["asserted"],"limit":50}'),
    ],
)
def test_a_request_argument_object_sorts_rather_than_keeping_keyword_order(
    arguments: dict[str, Any], expected: bytes
) -> None:
    """§5e: ``f(b=…, a=…)`` and ``f(a=…, b=…)`` are one call and one byte string.

    "That is construction-dependence on the *request* path, structurally identical
    to §4(i) and closed by the same rule."
    """
    assert _both(arguments) == expected
    assert _both(dict(reversed(list(arguments.items())))) == expected


def test_a_belief_shaped_model_takes_its_ratified_bytes() -> None:
    """§5e's composite: nested models, an optional inside a tuple, an enum, an
    instant, a float and a ``null`` field together.

    Built over the real promoted :class:`~ai_assistant.core.types.Belief` rather
    than over a fixture, so it is both the ADR's vector and a live check on the
    promoted type's byte shape. The type's field set has since moved past the one
    §5e states inline, twice, and the arithmetic below walks back to §5e's own
    figure rather than leaving the divergence to be rediscovered.

    Left at ``evidence_elided``'s default ``0``, unlike every case ADR-0107 §8 item
    6 governs: this vector is about the byte shape, and the field appearing *at* its
    default is the stronger witness that the codec projects generically over the
    whole model. What proves the *value* survives is
    :func:`test_a_belief_carries_its_elision_across_the_wire_unchanged`.
    """
    belief = Belief(
        id="b-1",
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.PREFERENCE,
        content="prefers dark mode",
        confidence=0.9,
        last_updated=_AT,
        evidence=(Evidence(content="said so"), Evidence()),
        valid_until=None,
    )
    expected = (
        b'{"band":"asserted","confidence":0.9,"content":"prefers dark mode",'
        b'"evidence":[{"content":"said so"},{"content":null}],"evidence_elided":0,'
        b'"id":"b-1","kind":"preference","last_updated":"2026-08-01T12:00:00Z",'
        b'"valid_until":null}'
    )
    assert _both(belief) == expected
    # 226, not §5e's 204, and the two later field-set changes are subtracted in turn
    # rather than the difference being asserted as a bare number. ADR-0087 §5
    # anticipates exactly this and rules on it twice: §5e's composite vectors "state
    # the field set they were built over inline, so that a vector remains verifiable
    # whatever the surface ADR settles", and they "stay verifiable if a field is
    # later selected differently". What the row exists to witness is unmoved: sorted
    # members, a nested model, an optional inside a tuple, an enum as its member
    # value, an instant, a float, and a ``null`` field.
    assert len(expected) == 226
    # ADR-0107 §3 appended ``evidence_elided``, which §2's member sort places between
    # ``evidence`` and ``id``. ADR-0107 §11 finds no record owed on ADR-0087, because
    # it "fixes the encoding an integer already had" — as this arithmetic shows.
    without_elision = len(expected) - len(b'"evidence_elided":0,')
    assert without_elision == 206
    # And 206 rather than 204 because the vector was measured against
    # ``BeliefBand.STATED`` at ``main`` @ 89e0cfe, while the member is spelled
    # ``asserted`` here — two bytes wider.
    assert without_elision - len(b'"asserted"') + len(b'"stated"') == 204


def test_a_page_of_beliefs_is_the_same_bytes_comma_separated() -> None:
    """§2a's context-freedom, stated as a vector.

    "The bytes a sender measures are the bytes it transmits", which is what makes
    measure-then-send sound and what lets ADR-0085 §8b's reserve be *sufficient*
    rather than hopeful.
    """
    belief = Belief(
        id="b-1",
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.PREFERENCE,
        content="prefers dark mode",
        confidence=0.9,
        last_updated=_AT,
        evidence=(Evidence(content="said so"), Evidence()),
        valid_until=None,
    )
    alone = canonical_payload(belief)
    assert canonical_payload((belief, belief)) == b"[" + alone + b"," + alone + b"]"


@pytest.mark.parametrize("order", [("to", "body", "Z"), ("Z", "body", "to"), ("body", "Z", "to")])
def test_a_confirmation_sorts_its_parameters_however_it_was_built(
    order: tuple[str, str, str],
) -> None:
    """§5e's ``FrozenJsonMapping`` vector, and §4(i)'s one genuine violation.

    ``FrozenDict.__eq__`` compares as a ``dict`` and ``__hash__`` uses a
    ``frozenset``, so key order is invisible to equality — but ``__iter__`` yields
    insertion order and the encoder sees it. Two ``==``-equal ``Confirmation``
    values therefore get two byte strings under ``model_dump_json()`` and one here.

    ``"Z"`` sorting before ``"body"`` is the code-point rule showing it is not
    case-insensitive.
    """
    values: dict[str, Any] = {"to": "a@b", "body": "hi", "Z": 1}
    confirmation = Confirmation(
        tool_id="t-1",
        tool_description="send",
        parameters={name: values[name] for name in order},
        reason="external",
        token=ContinuationToken(handle="h-1"),
    )
    expected = (
        b'{"parameters":{"Z":1,"body":"hi","to":"a@b"},"reason":"external",'
        b'"token":{"handle":"h-1"},"tool_description":"send","tool_id":"t-1"}'
    )
    assert _both(confirmation) == expected


# --- §5f. The near-misses the vectors exist to discriminate -----------------


def test_the_vectors_reject_every_near_miss_measured_while_writing_the_adr() -> None:
    """§5f: "A test suite that passes all of §5 and none of those is what 'one
    canonical encoding' means operationally."

    Each near-miss below is an encoder a reasonable implementer could write, and
    each is run against the vector it breaks. Without this the vector tables above
    would be a table of values that agree with whatever they are run against — the
    thing ADR-0087's Context refuses to accept from an enumeration.
    """
    belief_input: dict[str, Any] = {"b": 1, "a": 2}
    # 1. `model_dump_json()`: insertion order, `P1Y`, `null` for a non-finite float.
    assert Confirmation(
        tool_id="t-1",
        tool_description="send",
        parameters={"to": "a@b", "Z": 1},
        reason="external",
        token=ContinuationToken(handle="h-1"),
    ).model_dump_json().encode() != canonical_payload(
        Confirmation(
            tool_id="t-1",
            tool_description="send",
            parameters={"to": "a@b", "Z": 1},
            reason="external",
            token=ContinuationToken(handle="h-1"),
        )
    )
    # 2. `json.dumps` without `sort_keys`.
    assert json.dumps(belief_input, separators=(",", ":")).encode() != canonical_payload(
        belief_input
    )
    # 3. `ensure_ascii=True`.
    assert json.dumps("café", separators=(",", ":")).encode() != canonical_payload("café")
    # 4. A trimmed fractional second.
    assert canonical_payload({"d": _AT.replace(microsecond=100000)}).endswith(b'.100000Z"}')
    # 5. A `-0.0` normalised away.
    assert canonical_payload(-0.0) != canonical_payload(0.0)
    # 6. A duration with a year component.
    assert TypeAdapter(timedelta).dump_json(timedelta(days=365)) == b'"P1Y"'
    assert canonical_payload(timedelta(days=365)) == b'"P365D"'

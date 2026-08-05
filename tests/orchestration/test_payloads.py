"""ADR-0087's normative vectors, asserted against this tree's encoder.

ADR-0087 §5f says what these are for: "not documentation… each one is a line of a
conformance test — encode the input, compare to the byte string, compare the
length. Together they discriminate the encoding from every near-miss measured
while writing this ADR — ``model_dump_json()``, ``json.dumps`` without
``sort_keys``, ``ensure_ascii=True``, a trimmed fractional second, a ``-0.0``
normalised away, and a duration with a year component."

So the near-misses are asserted too (:class:`TestTheVectorsDiscriminate`). A
vector set that only ever sees the right answer proves the encoder agrees with
itself; what makes it evidence is that each named near-miss is *caught* by at
least one vector.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    Belief,
    BeliefBand,
    Confirmation,
    ContinuationToken,
    Evidence,
    MemoryKind,
)
from ai_assistant.orchestration.payloads import (
    canonical_payload,
    check_arguments,
    check_payload,
    identifier,
    page_argument,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _encoded(value: object) -> str:
    """The canonical bytes as text, so a failure message is readable."""
    return canonical_payload(value).decode("utf-8")


class TestStrings:
    """ADR-0087 §5a."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("a/b", '"a/b"'),
            ("a\\b", '"a\\\\b"'),
            ('say "hi"', '"say \\"hi\\""'),
            ("a\tb\nc", '"a\\tb\\nc"'),
            ("\r\b\f", '"\\r\\b\\f"'),
            ("\x00\x1f", '"\\u0000\\u001f"'),
            ("\x7f", '"\x7f"'),
            ("café", '"café"'),
            ("日本語", '"日本語"'),
            ("\U0001f600", '"\U0001f600"'),
            ("\u2028", '"\u2028"'),
            ("", '""'),
        ],
    )
    def test_the_vector(self, value: str, expected: str) -> None:
        """Each §5a row encodes exactly as ratified."""
        assert _encoded(value) == expected

    @pytest.mark.parametrize(
        ("value", "size"),
        [
            ("a/b", 5),
            ("a\\b", 6),
            ('say "hi"', 12),
            ("a\tb\nc", 9),
            ("\r\b\f", 8),
            ("\x00\x1f", 14),
            ("\x7f", 3),
            ("café", 7),
            ("日本語", 11),
            ("\U0001f600", 6),
            ("\u2028", 5),
            ("", 2),
        ],
    )
    def test_the_byte_count(self, value: str, size: int) -> None:
        """The limit is measured in bytes, so each vector's length is ratified too."""
        assert len(canonical_payload(value)) == size

    def test_a_lone_surrogate_has_no_encoding(self) -> None:
        """§5a's last row: refused rather than substituted or escaped through."""
        with pytest.raises(ValueError, match="UTF-8 encoding"):
            canonical_payload("\ud800")


class TestNumbers:
    """ADR-0087 §5b."""

    @pytest.mark.parametrize(
        ("value", "expected", "size"),
        [
            (0.0, "0.0", 3),
            (-0.0, "-0.0", 4),
            (1.0, "1.0", 3),
            (0.1, "0.1", 3),
            (0.1 + 0.2, "0.30000000000000004", 19),
            (1e-4, "0.0001", 6),
            (1e-5, "1e-05", 5),
            (1e-7, "1e-07", 5),
            (1e15, "1000000000000000.0", 18),
            (1e16, "1e+16", 5),
            (0, "0", 1),
            (2**63, "9223372036854775808", 19),
            (-1.5670905694168156e-99, "-1.5670905694168156e-99", 23),
        ],
    )
    def test_the_vector(self, value: float, expected: str, size: int) -> None:
        """Each §5b row encodes exactly as ratified, at the ratified length."""
        assert _encoded(value) == expected
        assert len(canonical_payload(value)) == size

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_a_non_finite_float_has_no_encoding(self, value: float) -> None:
        """§2c: raise, rather than pydantic's silent ``null`` or json's ``Infinity``."""
        with pytest.raises(ValueError, match="non-finite"):
            canonical_payload(value)

    @pytest.mark.parametrize(
        ("parameters", "expected", "size"),
        [
            ({"x": 1}, '{"x":1}', 7),
            ({"x": True}, '{"x":true}', 10),
            ({"x": 1.0}, '{"x":1.0}', 9),
            ({"x": 0.0}, '{"x":0.0}', 9),
            ({"x": -0.0}, '{"x":-0.0}', 10),
        ],
    )
    def test_equal_values_that_must_stay_apart(
        self, parameters: Mapping[str, Any], expected: str, size: int
    ) -> None:
        """§5b's five ``==``-equal values, inside the promoted holder that reaches them.

        ``1``, ``True`` and ``1.0`` are all ``==``; so are ``0.0`` and ``-0.0``.
        §4's equivalence is indistinguishability rather than ``==``, so each keeps
        its own bytes and the encoding normalises nothing.
        """
        confirmation = Confirmation(
            tool_id="t-1",
            tool_description="send",
            parameters=parameters,
            reason="external",
            token=ContinuationToken(handle="h-1"),
        )
        assert _encoded(confirmation.parameters) == expected
        assert len(canonical_payload(confirmation.parameters)) == size


class TestInstants:
    """ADR-0087 §5c, shown as ``{"d": <instant>}`` so the member framing is visible."""

    @pytest.mark.parametrize(
        ("value", "expected", "size"),
        [
            (
                datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
                '{"d":"2026-08-01T12:00:00Z"}',
                28,
            ),
            (
                datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=UTC),
                '{"d":"2026-08-01T12:00:00.123456Z"}',
                35,
            ),
            (
                datetime(2026, 8, 1, 12, 0, 0, 100000, tzinfo=UTC),
                '{"d":"2026-08-01T12:00:00.100000Z"}',
                35,
            ),
            (
                datetime(2026, 8, 1, 12, 0, 0, 1, tzinfo=UTC),
                '{"d":"2026-08-01T12:00:00.000001Z"}',
                35,
            ),
        ],
    )
    def test_the_vector(self, value: datetime, expected: str, size: int) -> None:
        """Six digits with trailing zeros kept, absent when the field is zero."""
        assert _encoded({"d": value}) == expected
        assert len(canonical_payload({"d": value})) == size

    def test_an_offset_instant_is_the_same_value_and_the_same_bytes(self) -> None:
        """§5c rows 1-2, the §4(ii) witness: the *type* normalised, not the encoder.

        The instant is validated through a promoted model's
        :data:`~ai_assistant.core.types.UtcInstant` field, which is where the
        conversion happens — an encoder handed the raw ``-05:00`` value would have
        to do it itself, and this shows it does not have to.
        """
        offset = datetime.fromisoformat("2026-08-01T07:00:00-05:00")
        utc = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
        as_offset = Belief(
            id="b-1",
            band=BeliefBand.ASSERTED,
            kind=MemoryKind.PREFERENCE,
            content="x",
            confidence=1.0,
            last_updated=offset,
        )
        as_utc = as_offset.model_copy(update={"last_updated": utc})
        assert canonical_payload(as_offset) == canonical_payload(as_utc)
        assert b'"last_updated":"2026-08-01T12:00:00Z"' in canonical_payload(as_offset)


class TestDurations:
    """ADR-0087 §5d — including the four rows the library gets wrong."""

    @pytest.mark.parametrize(
        ("value", "expected", "size"),
        [
            (timedelta(0), '"PT0S"', 6),
            (timedelta(seconds=30), '"PT30S"', 7),
            (timedelta(days=2, seconds=3), '"P2DT3S"', 8),
            (timedelta(seconds=172803), '"P2DT3S"', 8),
            (timedelta(hours=24), '"P1D"', 5),
            (timedelta(minutes=90), '"PT1H30M"', 9),
            (timedelta(seconds=61), '"PT1M1S"', 8),
            (timedelta(minutes=60), '"PT1H"', 6),
            (timedelta(microseconds=500000), '"PT0.5S"', 8),
            (timedelta(microseconds=1), '"PT0.000001S"', 13),
            (timedelta(seconds=-30), '"-PT30S"', 8),
            (timedelta(days=-1, seconds=1), '"-PT23H59M59S"', 14),
            (timedelta(days=365), '"P365D"', 7),
            (timedelta(days=1095), '"P1095D"', 8),
            (timedelta(days=360991935), '"P360991935D"', 13),
            (timedelta.max, '"P999999999DT23H59M59.999999S"', 30),
        ],
    )
    def test_the_vector(self, value: timedelta, expected: str, size: int) -> None:
        """Each §5d row, including the range rule and the nominal-component refusal."""
        assert _encoded(value) == expected
        assert len(canonical_payload(value)) == size


class TestComposites:
    """ADR-0087 §5e — the payload is any JSON value, and there is no wrapper."""

    @pytest.mark.parametrize(
        ("value", "expected", "size"),
        [(True, "true", 4), (None, "null", 4), ((), "[]", 2)],
    )
    def test_a_payload_that_is_not_a_model(self, value: object, expected: str, size: int) -> None:
        """A ``forget`` result, an optional getter's ``None``, an empty page."""
        assert _encoded(value) == expected
        assert len(canonical_payload(value)) == size

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            (
                {"utterance": "hi", "timeout": timedelta(seconds=30)},
                '{"timeout":"PT30S","utterance":"hi"}',
            ),
            ({"record_id": "r-1"}, '{"record_id":"r-1"}'),
            ({"bands": [BeliefBand.ASSERTED], "limit": 50}, '{"bands":["asserted"],"limit":50}'),
        ],
    )
    def test_a_request_argument_object(self, arguments: Mapping[str, Any], expected: str) -> None:
        """§5e's argument-object vectors, with members sorted rather than in call order.

        The band value differs from the ADR's illustration because that vector was
        written against a placeholder name; §5e says in as many words that "a vector
        whose names change stays a correct witness of the rule it demonstrates", and
        the rule here is the member sort plus the enum's own ``value``.
        """
        assert _encoded(dict(arguments)) == expected

    def test_the_caller_s_keyword_order_is_not_observable(self) -> None:
        """§5e: ``f(b=…, a=…)`` and ``f(a=…, b=…)`` are one call and one byte string."""
        one = canonical_payload({"utterance": "hi", "timeout": timedelta(seconds=30)})
        other = canonical_payload({"timeout": timedelta(seconds=30), "utterance": "hi"})
        assert one == other

    def test_a_belief_shaped_model(self) -> None:
        """§5e's composite vector: nested models, an optional in a tuple, an enum, a float.

        ``evidence_elided`` is in the bytes because ADR-0107 §3 put it on the type,
        and it sorts between ``evidence`` and ``id`` — §2's member sort doing its job
        on a field nobody chose the position of. **ADR-0087 §5 wrote this case's
        disposition in advance**: §5e's composite vectors "state the field set they
        were built over inline, so that a vector remains verifiable whatever the
        surface ADR settles", and they "stay verifiable if a field is later selected
        differently". The vector witnesses the *encoding rules*, not a frozen field
        list, and every rule it was built for still shows here. ADR-0107 §11 reaches
        the same place from the other side, finding no record owed on ADR-0087
        because it "fixes the encoding an integer already had".

        Left at the default ``0`` deliberately, unlike every case ADR-0107 §8 item 6
        governs: what this vector is for is the byte shape, and the field appearing
        *at* its default is the stronger witness that the codec projects generically
        over the whole model rather than over a chosen subset.
        """
        belief = Belief(
            id="b-1",
            band=BeliefBand.ASSERTED,
            kind=MemoryKind.PREFERENCE,
            content="prefers dark mode",
            confidence=0.9,
            last_updated=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
            evidence=(Evidence(content="said so"), Evidence()),
        )
        assert _encoded(belief) == (
            '{"band":"asserted","confidence":0.9,"content":"prefers dark mode",'
            '"evidence":[{"content":"said so"},{"content":null}],"evidence_elided":0,'
            '"id":"b-1","kind":"preference","last_updated":"2026-08-01T12:00:00Z",'
            '"valid_until":null}'
        )

    def test_a_confirmation_shaped_model_sorts_a_frozen_mapping_s_keys(self) -> None:
        """§5e's confirmation vector, the §4(i) witness.

        Two ``==`` values built with the mapping in opposite orders encode to the
        same bytes; ``model_dump_json()`` gives them two.
        """
        expected = (
            '{"parameters":{"Z":1,"body":"hi","to":"a@b"},"reason":"external",'
            '"token":{"handle":"h-1"},"tool_description":"send","tool_id":"t-1"}'
        )
        one = Confirmation(
            tool_id="t-1",
            tool_description="send",
            parameters={"to": "a@b", "body": "hi", "Z": 1},
            reason="external",
            token=ContinuationToken(handle="h-1"),
        )
        other = one.model_copy(update={"parameters": one.parameters})
        reordered = Confirmation(
            tool_id="t-1",
            tool_description="send",
            parameters={"Z": 1, "body": "hi", "to": "a@b"},
            reason="external",
            token=ContinuationToken(handle="h-1"),
        )
        assert _encoded(one) == expected
        assert canonical_payload(one) == canonical_payload(reordered) == canonical_payload(other)

    def test_a_page_is_the_elements_comma_separated(self) -> None:
        """§5e: a page of models is a JSON array of exactly those bytes, no whitespace."""
        first = Evidence(content="a")
        second = Evidence()
        assert _encoded((first, second)) == '[{"content":"a"},{"content":null}]'


class TestTheVectorsDiscriminate:
    """Each near-miss ADR-0087 §5f names is caught by at least one vector above.

    Written as a test rather than asserted in prose: a vector set nobody has tried
    to break is a set that agrees with the encoder it was read off.
    """

    def test_model_dump_json_is_caught(self) -> None:
        """It leaves members in declaration order and spells a year duration ``P1Y``."""
        belief = Belief(
            id="b-1",
            band=BeliefBand.ASSERTED,
            kind=MemoryKind.PREFERENCE,
            content="prefers dark mode",
            confidence=0.9,
            last_updated=datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC),
            evidence=(Evidence(content="said so"), Evidence()),
        )
        assert belief.model_dump_json().encode("utf-8") != canonical_payload(belief)

    def test_unsorted_keys_are_caught(self) -> None:
        """Dropping ``sort_keys`` changes the confirmation vector's bytes."""
        value = {"to": "a@b", "body": "hi", "Z": 1}
        naive = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        assert naive != canonical_payload(value)

    def test_ensure_ascii_is_caught(self) -> None:
        """``café`` is seven bytes, not eleven."""
        naive = json.dumps("café", separators=(",", ":")).encode("utf-8")
        assert naive != canonical_payload("café")
        assert len(canonical_payload("café")) == 7

    def test_a_trimmed_fractional_second_is_caught(self) -> None:
        """``.100000Z`` is ratified; ``.1Z`` is not."""
        value = {"d": datetime(2026, 8, 1, 12, 0, 0, 100000, tzinfo=UTC)}
        assert b".100000Z" in canonical_payload(value)
        assert b".1Z" not in canonical_payload(value)

    def test_a_normalised_negative_zero_is_caught(self) -> None:
        """An encoder that dropped the sign would give these one byte string."""
        assert canonical_payload({"x": -0.0}) != canonical_payload({"x": 0.0})

    def test_a_year_component_is_caught(self) -> None:
        """The four rows §3 row 2 corrects."""
        for value in (
            timedelta(days=365),
            timedelta(days=1095),
            timedelta(days=360991935),
            timedelta.max,
        ):
            assert b"Y" not in canonical_payload(value)


class TestTheContractLimit:
    """ADR-0085 §8c's refusal, and §9's rule for naming the largest member."""

    def test_a_payload_inside_the_limit_is_admitted(self) -> None:
        """The boundary is inclusive: a payload *at* the limit is not over it."""
        payload = "x" * 8
        size = len(canonical_payload(payload))
        check_payload(payload, max_bytes=size, subject="the result of belief()")

    def test_a_payload_over_the_limit_is_refused_with_the_number(self) -> None:
        """ "Too large" without a number is not actionable (ADR-0085 §9)."""
        payload = "x" * 64
        size = len(canonical_payload(payload))
        with pytest.raises(OversizedValueError) as caught:
            check_payload(payload, max_bytes=size - 1, subject="the result of belief()")
        assert caught.value.limit == size - 1
        assert caught.value.size == size

    def test_a_bare_payload_names_no_field(self) -> None:
        """§9: the ``None`` case is reachable, not defensive — a page is a bare array."""
        page = tuple(Evidence(content="x" * 32) for _ in range(4))
        with pytest.raises(OversizedValueError) as caught:
            check_payload(page, max_bytes=8, subject="the result of beliefs()")
        assert caught.value.field is None

    def test_the_largest_member_is_named(self) -> None:
        """The member whose own canonical encoding is longest."""
        with pytest.raises(OversizedValueError) as caught:
            check_arguments("converse", max_bytes=8, utterance="x" * 64, conversation_id="c-1")
        assert caught.value.field == "utterance"

    def test_a_tie_is_broken_by_the_member_name_ascending(self) -> None:
        """Two members of equal encoded length: the lower name wins, every time."""
        with pytest.raises(OversizedValueError) as caught:
            check_arguments("converse", max_bytes=4, beta="xx", alpha="xx")
        assert caught.value.field == "alpha"

    def test_an_argument_the_caller_did_not_pass_is_absent(self) -> None:
        """ADR-0085 §10: absent, not ``null`` — so it contributes no bytes."""
        with pytest.raises(OversizedValueError) as caught:
            check_arguments("observe", max_bytes=1, conversation_id=None, other="x")
        assert caught.value.size == len(canonical_payload({"other": "x"}))


class TestArgumentClauses:
    """ADR-0085 §3c and §9's local refusals."""

    def test_an_identifier_is_stripped_and_not_merely_checked(self) -> None:
        """§3c's load-bearing half: the value the implementation uses is normalised."""
        assert identifier("  rec-1  ", name="record_id") == "rec-1"

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_a_blank_identifier_is_refused(self, value: str) -> None:
        """A blank id satisfies "an id is present" while naming nothing."""
        with pytest.raises(ValueError, match="record_id"):
            identifier(value, name="record_id")

    def test_an_unencodable_identifier_is_refused(self) -> None:
        """:data:`~ai_assistant.core.types.Identifier` layers on ``EncodableText``."""
        with pytest.raises(ValueError, match="record_id"):
            identifier("\ud800", name="record_id")

    @pytest.mark.parametrize("value", [-1, 2**63, 2**64])
    def test_a_malformed_page_argument_is_refused(self, value: int) -> None:
        """Refused rather than clamped (ADR-0073 §2), and locally (ADR-0085 §9)."""
        with pytest.raises(ValueError, match="limit"):
            page_argument(value, name="limit")

    @pytest.mark.parametrize("value", [0, 1, 50, 2**63 - 1])
    def test_a_well_formed_page_argument_passes_through(self, value: int) -> None:
        """The bound is ``[0, 2**63)`` — both ends checked, so neither is guessed."""
        assert page_argument(value, name="limit") == value


class TestThePagingArguments:
    """An explicitly-supplied paging argument is part of the payload (ADR-0085 §8c)."""

    def test_a_paging_limit_contributes_bytes(self) -> None:
        """The bound is on the **whole** argument object, so no member is exempt.

        An earlier draft measured ``offset`` and not ``limit``, on the ground that
        ``limit`` is what a caller omits to get the default. That reading fails on
        ADR-0087 §7's stated order — "decode, then validate, then measure", where
        "the receiver … measures the canonical encoding of the *validated* value"
        and a validated call has its defaults applied — and it fails conservatively
        in the wrong direction: it admits a payload the receiver would go on to
        refuse. Including it can only refuse earlier, never later.
        """
        with_limit = canonical_payload({"limit": 2**63 - 1, "offset": 0})
        without = canonical_payload({"offset": 0})
        assert len(with_limit) > len(without)
        check_arguments("beliefs", max_bytes=len(with_limit), limit=2**63 - 1, offset=0)
        with pytest.raises(OversizedValueError) as caught:
            check_arguments("beliefs", max_bytes=len(with_limit) - 1, limit=2**63 - 1, offset=0)
        assert caught.value.field == "limit"

    def test_the_member_is_named_for_the_parameter(self) -> None:
        """``field`` names something a caller can act on.

        ADR-0085 §9 makes it a value the far side reconstructs, so a member this
        module called ``page_size`` while the wire called it ``limit`` would name a
        parameter that does not exist. That is why the byte bound is spelled
        ``max_bytes`` here rather than ``limit``.
        """
        with pytest.raises(OversizedValueError) as caught:
            check_arguments("beliefs", max_bytes=4, limit=2**63 - 1, offset=0)
        assert caught.value.field in {"limit", "offset"}
        assert caught.value.field == "limit"

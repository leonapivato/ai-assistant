"""The records a structured call returns (ADR-0354 §5:1, §5:3, §11)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import (
    ReplyExchange,
    ReplyFailure,
    ReplyMode,
    ReplyUsage,
    StructuredReply,
)


class _Shape(BaseModel):
    answer: str


def _exchange(**overrides: object) -> ReplyExchange:
    fields: dict[str, object] = {
        "reply": '{"answer": "yes"}',
        "model": "anthropic:claude-sonnet-5-5",
        "mode": ReplyMode.NATIVE,
        "finish_reason": "stop",
        "usage": ReplyUsage(input_tokens=3, output_tokens=2),
        "shape": "_Shape",
        "shape_version": "0123456789ab",
    }
    fields.update(overrides)
    return ReplyExchange.model_validate(fields)


def test_the_failures_are_closed_and_in_their_order() -> None:
    assert [member.value for member in ReplyFailure] == ["refused", "cut", "empty", "invalid"]


def test_the_modes_are_closed() -> None:
    assert [member.value for member in ReplyMode] == ["native", "prompted"]


def test_a_reply_holds_the_value_or_the_failure() -> None:
    value = StructuredReply(value=_Shape(answer="yes"), exchange=_exchange())
    failure: StructuredReply[_Shape] = StructuredReply(
        failure=ReplyFailure.INVALID, exchange=_exchange()
    )
    assert value.value == _Shape(answer="yes")
    assert value.failure is None
    assert failure.value is None
    assert failure.failure is ReplyFailure.INVALID


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="neither"),
        pytest.param({"value": _Shape(answer="yes"), "failure": ReplyFailure.EMPTY}, id="both"),
    ],
)
def test_a_reply_holding_both_or_neither_is_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        StructuredReply.model_validate({**fields, "exchange": _exchange()})


def test_a_reply_always_holds_its_exchange() -> None:
    with pytest.raises(ValidationError):
        StructuredReply.model_validate({"failure": ReplyFailure.CUT})


def test_the_records_are_frozen() -> None:
    reply = StructuredReply(value=_Shape(answer="yes"), exchange=_exchange())
    with pytest.raises(ValidationError):
        reply.failure = ReplyFailure.INVALID
    with pytest.raises(ValidationError):
        reply.exchange.reply = "changed"
    with pytest.raises(ValidationError):
        reply.exchange.usage.input_tokens = 9


@pytest.mark.parametrize("version", ["", "0123456789a", "0123456789abc", "0123456789AB", "xyz"])
def test_a_version_is_twelve_lower_case_hexadecimal_digits(version: str) -> None:
    with pytest.raises(ValidationError):
        _exchange(shape_version=version)


@pytest.mark.parametrize(
    "field", ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"]
)
def test_a_usage_count_is_never_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        ReplyUsage.model_validate({field: -1})


def test_an_exchange_names_no_key_it_does_not_declare() -> None:
    with pytest.raises(ValidationError):
        _exchange(value='{"answer": "yes"}')


def test_an_exchange_holds_an_empty_reply_and_no_refusal_by_default() -> None:
    exchange = _exchange(reply="")
    assert exchange.reply == ""
    assert exchange.refusal is None
    assert exchange.refusal_category is None


def test_a_reply_that_cannot_be_written_down_is_refused() -> None:
    with pytest.raises(ValidationError):
        _exchange(reply="\ud800")

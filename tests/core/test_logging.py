"""Tests for the ADR-0004 §5 log redaction safety net."""

from __future__ import annotations

import subprocess
import sys
from collections import ChainMap, UserDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import PurePath
from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
import structlog
from pydantic import BaseModel

from ai_assistant.core.config import Settings
from ai_assistant.core.logging import (
    REDACTED,
    configure_logging,
    redact_sensitive,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def _redact(**event: object) -> dict[str, object]:
    return dict(redact_sensitive(None, "info", dict(event)))


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "token",
        "refresh_token",
        "password",
        "secret",
        "authorization",
        "session_id",
        "cookie",
        "credentials",
    ],
)
def test_tier_0_keys_are_masked(key: str) -> None:
    assert _redact(**{key: "sk-live-abc123"})[key] == REDACTED


@pytest.mark.parametrize(
    "key",
    [
        # Conversation content.
        "prompt",
        "message",
        "messages",
        "content",
        "reply",
        "completion",
        "answer",
        "body",
        "query",
        "transcript",
        "memory",
        # Personal data. ADR-0004 §5 names "message bodies, PII fields"; an
        # earlier list covered the former and barely touched the latter.
        "email",
        "first_name",
        "last_name",
        "full_name",
        "surname",
        "username",
        "user_name",
        "phone",
        "address",
        "postcode",
        "dob",
        "date_of_birth",
        "latitude",
        "longitude",
        "ssn",
    ],
)
def test_tier_1_keys_are_masked(key: str) -> None:
    assert _redact(**{key: "the user's private text"})[key] == REDACTED


def test_a_bare_name_key_is_not_over_matched() -> None:
    # Deliberate limit on the PII list: matching bare "name" would swallow
    # model_name, source_name, field_name and every other diagnostic identifier.
    # A net that hides the diagnostics is not safer, just less useful — so the
    # list carries compound person-name keys instead.
    redacted = _redact(model_name="claude-opus-4-8", source_name="clock")

    assert redacted == {"model_name": "claude-opus-4-8", "source_name": "clock"}


def test_matching_is_case_insensitive_and_substring_based() -> None:
    # Compound names are what people actually write, so exact-match would be a
    # net with holes the size of `ANTHROPIC_API_KEY`.
    redacted = _redact(ANTHROPIC_API_KEY="sk-1", userToken="t", chat_messages=["hi"])

    assert redacted["ANTHROPIC_API_KEY"] == REDACTED
    assert redacted["userToken"] == REDACTED
    assert redacted["chat_messages"] == REDACTED


def test_operational_keys_pass_through() -> None:
    # Tier 2 is what logs are *for*; over-redaction that hid diagnostics would
    # make the net worse than useless.
    redacted = _redact(route="primary", error="ModelUnavailableError", routes=2, elapsed=1.5)

    assert redacted == {
        "route": "primary",
        "error": "ModelUnavailableError",
        "routes": 2,
        "elapsed": 1.5,
    }


def test_nested_structures_are_scrubbed() -> None:
    # Structured logs nest — routing reports a list of per-route dicts — so a
    # top-level-only pass would miss most of what it exists to catch.
    redacted = _redact(
        failures=[{"route": "primary", "api_key": "sk-1"}],
        request={"headers": {"authorization": "Bearer x"}, "status": 500},
    )

    assert redacted["failures"] == [{"route": "primary", "api_key": REDACTED}]
    assert redacted["request"] == {"headers": {"authorization": REDACTED}, "status": 500}


@pytest.mark.parametrize(
    "wrap",
    [
        UserDict,
        MappingProxyType,
        lambda d: ChainMap(d, {}),
    ],
    ids=["UserDict", "MappingProxyType", "ChainMap"],
)
def test_non_dict_mappings_are_scrubbed(
    wrap: Callable[[dict[str, str]], Mapping[str, str]],
) -> None:
    # Regression (adversarial review): matching on the concrete `dict` type let
    # any other mapping through with its secrets intact. Custom and immutable
    # mappings are ordinary things to log, so the check is on the Mapping
    # protocol.
    redacted = _redact(payload=wrap({"api_key": "sk-live-SECRET"}))

    assert redacted["payload"] == {"api_key": REDACTED}


def test_non_list_sequences_and_sets_are_scrubbed() -> None:
    # Same defect, other half of the protocol split.
    redacted = _redact(
        rows=deque([{"token": "t"}]),
        seen=frozenset({"harmless"}),
    )

    assert redacted["rows"] == [{"token": REDACTED}]
    assert redacted["seen"] == ["harmless"]


def test_strings_are_not_walked_character_by_character() -> None:
    # str is a Sequence; recursing into it would shred every message.
    assert _redact(route="primary")["route"] == "primary"
    assert _redact(payload=b"bytes")["payload"] == b"bytes"


def test_there_is_no_allow_list_exemption() -> None:
    # Regression (adversarial review): `content_type` was exempted as inert MIME
    # metadata, but a MIME string carries a `name=` parameter — so the exemption
    # leaked whatever was in it. An exemption is a permanent hole justified by an
    # assumption about the value, and the assumption is what fails. Over-matching
    # is fixed by renaming the key, which is local; an exemption is global.
    redacted = _redact(content_type='text/plain; name="PATIENT SSN 123-45-6789"')

    assert redacted["content_type"] == REDACTED


def test_sensitive_data_in_a_mapping_key_is_masked() -> None:
    # Regression (adversarial review): only values were examined, so a mapping
    # keyed by data — a parsed query string, a per-user counter — put Tier 0/1
    # content in the key position where masking the value achieved nothing.
    redacted = _redact(payload={"api_key=sk-live-SECRET": True})

    assert "api_key=sk-live-SECRET" not in repr(redacted)


def test_masked_keys_do_not_collide_and_lose_entries() -> None:
    # Masking two data keys would map both to "[redacted]" and silently drop
    # one. A redactor that quietly discards diagnostics is its own failure.
    redacted = _redact(payload={"a@example.com": 1, "b@example.com": 2, "route": "primary"})

    payload = redacted["payload"]
    assert isinstance(payload, dict)
    assert len(payload) == 3
    assert sorted(payload.values(), key=repr) == sorted([1, 2, "primary"], key=repr)


def test_a_field_name_is_not_mistaken_for_data() -> None:
    # The @/= heuristic must not fire on ordinary keys, or every log turns to
    # mush.
    redacted = _redact(payload={"route": "primary", "model_name": "opus", "count": 3})

    assert redacted["payload"] == {"route": "primary", "model_name": "opus", "count": 3}


def test_dataclasses_are_unwrapped_and_scrubbed() -> None:
    # Regression (adversarial review): an unrecognised object reached the
    # renderer as its repr — `Cfg(api_key='sk-live-…')` — which is the leak in
    # its most convenient form.
    @dataclass
    class Cfg:
        api_key: str
        region: str

    redacted = _redact(payload=Cfg(api_key="sk-live-SECRET", region="eu"))

    assert redacted["payload"] == {"api_key": REDACTED, "region": "eu"}


def test_pydantic_models_are_unwrapped_and_scrubbed() -> None:
    # core/types.py is entirely pydantic models, so this is the shape data
    # actually travels in here.
    class Person(BaseModel):
        email: str
        count: int

    redacted = _redact(payload=Person(email="alice@example.com", count=3))

    assert redacted["payload"] == {"email": REDACTED, "count": 3}


def test_unknown_object_types_fail_closed() -> None:
    # "Unknown" has to mean "masked", not "hope it is harmless": an object we
    # cannot look inside reaches the renderer as a repr showing whatever it
    # holds.
    class Opaque:
        def __repr__(self) -> str:
            return "Opaque(api_key='sk-live-SECRET')"

    assert _redact(payload=Opaque())["payload"] == REDACTED


@pytest.mark.parametrize(
    "value",
    [
        42,
        3.14,
        True,
        None,
        Decimal("1.5"),
        UUID("12345678-1234-5678-1234-567812345678"),
        PurePath("/var/data/x"),
        datetime(2026, 1, 1, tzinfo=UTC),
    ],
    ids=["int", "float", "bool", "none", "decimal", "uuid", "path", "datetime"],
)
def test_safe_scalars_render_as_themselves(value: object) -> None:
    # The fail-closed default must not swallow ordinary diagnostic values; these
    # types are their own value, with no nested fields to hide anything in.
    assert _redact(measurement=value)["measurement"] == value


def test_redaction_failure_drops_the_event() -> None:
    # "Fail closed" (ADR-0004 §5): an event that cannot be scrubbed is dropped
    # rather than emitted unscrubbed. Losing a log line beats leaking one.
    class ExplodingKey:
        def lower(self) -> str:
            raise RuntimeError("boom")

        def __hash__(self) -> int:
            return 0

    with pytest.raises(structlog.DropEvent):
        redact_sensitive(None, "info", {ExplodingKey(): "value"})  # type: ignore[dict-item]


def test_redaction_is_installed_on_import_without_any_bootstrap_call() -> None:
    # Regression (adversarial review): redaction was installed only by the Typer
    # callback, so every non-CLI use — a test, a script, an embedding
    # application, orchestration wired up directly — logged through structlog's
    # default, unredacted chain. A safety net that depends on the caller
    # remembering to install it is not a safety net.
    #
    # Deliberately does NOT call configure_logging: importing the package must
    # be sufficient. Run in a subprocess so this process's own configuration
    # cannot mask the result.
    script = (
        "import structlog, ai_assistant\n"
        "structlog.get_logger('x').warning('boom', api_key='sk-live-SECRET')\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert "sk-live-SECRET" not in result.stdout
    assert REDACTED in result.stdout


def test_the_processor_is_installed_by_configure_logging() -> None:
    # The net only works if it is actually wired in; ADR-0004 §5 claimed a
    # configured processor for months while none existed.
    configure_logging(Settings())

    processors = structlog.get_config()["processors"]

    assert redact_sensitive in processors


def test_configure_logging_does_not_stack_processors() -> None:
    configure_logging(Settings())
    first = len(structlog.get_config()["processors"])
    configure_logging(Settings())

    # An adapter calling it twice must not stack processors.
    assert len(structlog.get_config()["processors"]) == first


def test_reconfiguring_affects_a_logger_already_in_use(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Regression (adversarial review): with cache_logger_on_first_use=True a
    # logger bound to the first configuration and kept it forever, so a later
    # configure_logging() silently did nothing to it. Comparing processor-list
    # lengths — as the previous "idempotent" test did — cannot see this.
    #
    # It is a privacy bug, not just a tidiness one: a module-level logger that
    # ran before configure_logging() would keep emitting through a chain with no
    # redaction processor in it.
    configure_logging(Settings(log_level="INFO"))
    log = structlog.get_logger("reconfig-demo")
    log.info("bound at INFO")
    capsys.readouterr()

    configure_logging(Settings(log_level="ERROR"))
    log.info("must not be emitted")

    assert capsys.readouterr().out == ""


def test_a_logger_created_before_configuration_still_gets_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The realistic shape of the bug above: modules do
    # `_log = structlog.get_logger(__name__)` at import time, long before the
    # CLI callback configures anything.
    log = structlog.get_logger("early-demo")

    configure_logging(Settings())
    log.warning("late configuration", api_key="sk-live-SECRET")

    out = capsys.readouterr().out
    assert "sk-live-SECRET" not in out
    assert REDACTED in out


def test_redaction_applies_on_the_real_emission_path(capsys: pytest.CaptureFixture[str]) -> None:
    # Asserted against actual rendered output, not structlog.testing.capture_logs
    # — that fixture *replaces* the processor chain, so redaction never runs
    # under it and a test written that way would pass while leaking in
    # production. See test_capture_logs_bypasses_redaction below.
    configure_logging(Settings())

    structlog.get_logger(__name__).warning("call failed", prompt="hunter2", route="primary")

    out = capsys.readouterr().out
    assert "hunter2" not in out
    assert REDACTED in out
    assert "primary" in out


def test_capture_logs_bypasses_redaction() -> None:
    # Pinned deliberately, as a warning to the next person: capture_logs swaps
    # in its own processor list, so an assertion of the form
    # `assert secret not in repr(logs)` proves nothing about what the
    # application would really emit. Any "does not leak" test must go through
    # the rendered output instead.
    configure_logging(Settings())

    with structlog.testing.capture_logs() as logs:
        structlog.get_logger(__name__).warning("call failed", prompt="hunter2")

    assert logs[0]["prompt"] == "hunter2"

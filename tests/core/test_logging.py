"""Tests for the ADR-0004 §5 log redaction safety net."""

from __future__ import annotations

import asyncio
import io
import logging
import logging.handlers
import subprocess
import sys
import threading
from collections import ChainMap, UserDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import PurePath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
import structlog
from pydantic import BaseModel

import conftest
from ai_assistant.core.config import Settings
from ai_assistant.core.logging import (
    REDACTED,
    configure_logging,
    install_redaction,
    redact_sensitive,
    scrub_exceptions,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, MutableMapping
    from types import TracebackType


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


@pytest.mark.parametrize(
    "key",
    ["123-45-6789", "Alice Smith", "a@example.com", "token=secret", "+44 7700 900000"],
    ids=["ssn", "full-name", "email", "query-fragment", "phone"],
)
def test_data_shaped_keys_are_masked(key: str) -> None:
    # Regression (CI adversarial review): the previous test was for `@` or `=`,
    # so an SSN or a person's name used as a key was emitted intact. Enumerating
    # the shapes *data* can take is unwinnable; asking whether a key looks like a
    # *field name* has one answer.
    redacted = _redact(payload={key: 1})

    assert key not in repr(redacted["payload"])


def test_a_bare_token_key_is_a_known_limit() -> None:
    # Stated rather than hidden: "Alice" is a valid identifier and nothing
    # distinguishes it from a field name without knowing what the value means,
    # which a key-based net by definition does not.
    assert _redact(payload={"Alice": 1})["payload"] == {"Alice": 1}


def test_an_enum_renders_by_name_never_by_value() -> None:
    # Regression (CI adversarial review): an Enum's *value* can be a secret, and
    # its repr shows it — `<ApiKey.VALUE: 'sk-live-...'>`.
    class ApiKey(Enum):
        VALUE = "sk-live-SECRET"

    assert _redact(k=ApiKey.VALUE)["k"] == "ApiKey.VALUE"


def test_a_subclass_of_a_safe_type_is_not_trusted() -> None:
    # Regression (CI adversarial review): membership was isinstance-based, so
    # inheriting from a trusted type was taken as evidence of being safe. A
    # subclass can render as anything it likes.
    class Sneaky(int):
        def __repr__(self) -> str:
            return "sk-live-SECRET"

    assert _redact(k=Sneaky(5))["k"] == REDACTED


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


def test_a_hosts_existing_configuration_is_composed_with_not_replaced() -> None:
    # Regression (CI adversarial review): importing the package replaced the
    # whole processor chain, so an embedding application that had installed a
    # *stricter* processor lost it on import and the next such event went out
    # unredacted — strictly worse than doing nothing, since the host had already
    # solved the problem.
    def host_mask(
        _logger: Any, _name: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        if "medical_record" in event:
            event["medical_record"] = "<HOST-MASKED>"
        return event

    renderer = structlog.processors.KeyValueRenderer()
    structlog.configure(processors=[host_mask, renderer])

    install_redaction()

    processors = structlog.get_config()["processors"]
    assert host_mask in processors, "the host's own processor must survive"
    assert redact_sensitive in processors, "ours must be added"
    # Ours goes before the renderer — after it there is no structured event left.
    assert processors.index(redact_sensitive) < processors.index(renderer)


def test_composition_applies_both_maskings(capsys: pytest.CaptureFixture[str]) -> None:
    def host_mask(
        _logger: Any, _name: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        if "medical_record" in event:
            event["medical_record"] = "<HOST-MASKED>"
        return event

    structlog.configure(
        processors=[host_mask, structlog.dev.ConsoleRenderer(colors=False)],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    install_redaction()

    structlog.get_logger("compose").warning("e", medical_record="PRIVATE", api_key="sk-live-X")

    out = capsys.readouterr().out
    # Strictly more redacted than either configuration was alone.
    assert "PRIVATE" not in out
    assert "sk-live-X" not in out
    assert "<HOST-MASKED>" in out


def test_a_logger_cached_before_installation_is_still_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Regression (CI adversarial review): with cache_logger_on_first_use=True —
    # structlog's own production recommendation — a host's logger binds its
    # processor chain on first use and never consults the configuration again.
    # Replacing the list therefore protected only loggers created afterwards,
    # while every already-used one kept emitting unredacted. The cached logger
    # holds a reference to the list itself, so it is mutated in place.
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer(colors=False)],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    log = structlog.get_logger("cached-host")
    log.warning("first use binds and caches the chain")
    capsys.readouterr()

    install_redaction()
    log.warning("after installation", api_key="sk-live-SECRET")

    out = capsys.readouterr().out
    assert "sk-live-SECRET" not in out
    assert REDACTED in out


def test_installing_twice_does_not_duplicate_the_processor() -> None:
    configure_logging(Settings())
    install_redaction()
    install_redaction()

    processors = structlog.get_config()["processors"]

    assert processors.count(redact_sensitive) == 1
    assert processors.count(scrub_exceptions) == 1


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


# --- An exception is logged by its class and frames, never its words (#2926) ---
#
# Every assertion below is over the **rendered** output or the processor's own
# result, never over ``capture_logs``, for test_capture_logs_bypasses_redaction's
# reason. The markers are kept off every line a frame shows — a frame prints its
# source line, which is code — so a marker in the output can only have come from a
# message, a note or a local.

_MESSAGE = "MARKER-MESSAGE-7f3a"
_LOCAL = "MARKER-LOCAL-9c1e"
_CHAINED = "MARKER-CHAINED-2b8d"
_MARKERS = (_MESSAGE, _LOCAL, _CHAINED)


class _ReadFailedError(Exception):
    """A failure raised where the conversation's text is in scope."""


def _raise_with_content() -> None:
    conversation = _LOCAL
    words = f"{_MESSAGE}: could not read {conversation!r}"
    raise _ReadFailedError(words)


def _raise_chained() -> None:
    try:
        _raise_with_content()
    except _ReadFailedError as failure:
        detail = _CHAINED
        raise RuntimeError(detail) from failure


def _raise_in_handler() -> None:
    try:
        _raise_with_content()
    except _ReadFailedError:
        detail = _CHAINED
        raise LookupError(detail)  # noqa: B904 — the implicit context is the case


def _caught(raiser: Callable[[], None]) -> Exception:
    try:
        raiser()
    except Exception as failure:
        return failure
    raise AssertionError("the raiser did not raise")


def _assert_no_content(out: str) -> None:
    for marker in _MARKERS:
        assert marker not in out, f"{marker} reached the log"


def test_the_default_renderer_is_the_hazard() -> None:
    # The premise, pinned: structlog's own renderer prints the message, which is why
    # the chain renders an exception before the renderer sees it.
    failure = _caught(_raise_with_content)

    out = structlog.dev.ConsoleRenderer(colors=False)(None, "warning", {"exc_info": failure})

    assert _MESSAGE in out


def test_an_exc_info_line_carries_the_class_and_frames_and_never_the_words(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(Settings())

    try:
        _raise_with_content()
    except _ReadFailedError:
        structlog.get_logger(__name__).warning("read_failed", stage="reader", exc_info=True)

    out = capsys.readouterr().out
    _assert_no_content(out)
    assert "read_failed" in out
    assert "_ReadFailedError" in out, "the class says what happened"
    assert "test_logging.py" in out, "the frames say where"
    assert "in _raise_with_content" in out
    assert "raise _ReadFailedError(words)" in out, "a frame keeps its source line"


def test_log_exception_carries_no_words(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings())

    try:
        _raise_with_content()
    except _ReadFailedError:
        structlog.get_logger(__name__).exception("read_failed")

    out = capsys.readouterr().out
    _assert_no_content(out)
    assert "_ReadFailedError" in out


@pytest.mark.parametrize("shape", ["exception", "tuple"])
def test_an_exception_passed_as_exc_info_is_rendered_by_its_class(
    shape: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Outside any handler, so it can only be the value passed that is rendered.
    # Before this net, the redactor masked an exception object to a string, which
    # the renderer then read as "the exception being handled".
    configure_logging(Settings())
    failure = _caught(_raise_with_content)
    exc_info = failure if shape == "exception" else (type(failure), failure, failure.__traceback__)

    structlog.get_logger(__name__).warning("streamed_turn_failed", exc_info=exc_info)

    out = capsys.readouterr().out
    _assert_no_content(out)
    assert "_ReadFailedError" in out
    assert "in _raise_with_content" in out


def test_a_group_renders_its_member_classes_and_none_of_their_words(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(Settings())
    member = _caught(_raise_with_content)
    nested = ExceptionGroup(_CHAINED, [KeyError(_LOCAL)])
    group = ExceptionGroup(_MESSAGE, [member, ValueError(_LOCAL), nested])

    structlog.get_logger(__name__).error("pass_failed", exc_info=group)

    out = capsys.readouterr().out
    _assert_no_content(out)
    for cls in ("ExceptionGroup", "_ReadFailedError", "ValueError", "KeyError"):
        assert cls in out, f"the member class {cls} is named"
    assert "+ 1/3" in out
    assert "in _raise_with_content" in out, "a member keeps the frames it was raised in"


@pytest.mark.parametrize("raiser", [_raise_chained, _raise_in_handler], ids=["cause", "context"])
def test_a_chained_exceptions_words_do_not_appear(
    raiser: Callable[[], None], capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(Settings())
    failure = _caught(raiser)

    structlog.get_logger(__name__).warning("read_failed", exc_info=failure)

    out = capsys.readouterr().out
    _assert_no_content(out)
    assert "_ReadFailedError" in out, "the chained class is named"
    assert type(failure).__name__ in out
    assert "the above exception" in out.lower()


def test_an_exceptions_notes_do_not_appear(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(Settings())
    failure = _caught(_raise_with_content)
    failure.add_note(_CHAINED)

    structlog.get_logger(__name__).warning("read_failed", exc_info=failure)

    _assert_no_content(capsys.readouterr().out)


def test_a_cycle_through_a_group_ends() -> None:
    member = ValueError(_LOCAL)
    group = ExceptionGroup(_MESSAGE, [member])
    member.__context__ = group

    event = scrub_exceptions(None, "error", {"event": "e", "exc_info": group})

    _assert_no_content(str(event["exception"]))
    assert "ValueError" in str(event["exception"])


def test_groups_sharing_members_render_each_exception_once() -> None:
    # Adversarial review, round 1: seventeen exceptions, each group holding the one
    # before it twice, expanded to 65,536 leaves. Each is expanded once, and one met
    # again is named by its class.
    shared: Exception = ValueError(_MESSAGE)
    for _ in range(16):
        shared = ExceptionGroup(_MESSAGE, [shared, shared])

    event = scrub_exceptions(None, "error", {"event": "e", "exc_info": shared})

    rendered = str(event["exception"])
    _assert_no_content(rendered)
    assert rendered.count("ValueError") == 2, "expanded once, then named as shown above"
    assert "shown above" in rendered
    assert len(rendered) < 10_000


def test_a_long_context_chain_renders_rather_than_dropping() -> None:
    # A retry loop raising inside its own handler builds a chain as long as its
    # retries; walking it by recursion would overflow and lose the line.
    newest = ValueError(_MESSAGE)
    for _ in range(sys.getrecursionlimit() * 2):
        earlier = newest
        newest = ValueError(_MESSAGE)
        newest.__context__ = earlier

    event = scrub_exceptions(None, "error", {"event": "e", "exc_info": newest})

    _assert_no_content(str(event["exception"]))
    assert "ValueError" in str(event["exception"])


def test_exc_info_with_nothing_being_handled_renders_nothing() -> None:
    event = scrub_exceptions(None, "warning", {"event": "e", "exc_info": True})

    assert event == {"event": "e"}


def test_an_event_without_an_exception_is_untouched() -> None:
    event = scrub_exceptions(None, "info", {"event": "e", "route": "primary"})

    assert event == {"event": "e", "route": "primary"}


def test_an_exception_object_under_exception_is_rendered_by_its_class() -> None:
    event = scrub_exceptions(None, "warning", {"event": "e", "exception": ValueError(_MESSAGE)})

    _assert_no_content(str(event["exception"]))
    assert "ValueError" in str(event["exception"])


def test_a_traceback_rendered_before_the_net_is_masked() -> None:
    # A string under ``exception`` — a host's format_exc_info upstream, or a call
    # site's str(exc) — is a rendering whose words cannot be told from its frames.
    event = scrub_exceptions(None, "warning", {"event": "e", "exception": f"ValueError: {_LOCAL}"})

    assert event["exception"] == REDACTED


def test_a_second_pass_keeps_what_the_first_rendered() -> None:
    once = scrub_exceptions(None, "warning", {"event": "e", "exc_info": _caught(_raise_chained)})
    rendered = once["exception"]

    twice = scrub_exceptions(None, "warning", dict(once))

    assert twice["exception"] == rendered
    assert "RuntimeError" in str(twice["exception"])


def test_formatting_failure_drops_the_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Fail closed, as redaction does: an exception that cannot be rendered without
    # its words is not rendered at all, and neither is its line.
    def explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("formatting failed")

    configure_logging(Settings())
    failure = _caught(_raise_with_content)
    monkeypatch.setattr("traceback.extract_tb", explode)

    with pytest.raises(structlog.DropEvent):
        scrub_exceptions(None, "warning", {"event": "e", "exc_info": failure})

    structlog.get_logger(__name__).warning("read_failed", exc_info=failure)

    assert capsys.readouterr().out == ""


def _installed_renderer() -> structlog.dev.ConsoleRenderer:
    renderer = structlog.get_config()["processors"][-1]
    assert isinstance(renderer, structlog.dev.ConsoleRenderer)
    return renderer


def test_the_renderers_exception_formatter_is_the_second_net() -> None:
    # Were an ``exc_info`` to reach the renderer — a processor reordered — it is
    # written without its words or locals, where the default prints both.
    configure_logging(Settings())
    failure = _caught(_raise_chained)

    out = _installed_renderer()(None, "warning", {"event": "e", "exc_info": failure})

    _assert_no_content(out)
    assert "RuntimeError" in out
    assert "_ReadFailedError" in out


def test_the_second_nets_failure_drops_the_event(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("formatting failed")

    configure_logging(Settings())
    failure = _caught(_raise_with_content)
    monkeypatch.setattr("traceback.extract_tb", explode)

    with pytest.raises(structlog.DropEvent):
        _installed_renderer()(None, "warning", {"event": "e", "exc_info": failure})


def test_a_hosts_chain_gains_the_scrubber_ahead_of_the_redactor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    renderer = structlog.dev.ConsoleRenderer(colors=False)
    structlog.configure(processors=[renderer], logger_factory=structlog.PrintLoggerFactory())

    install_redaction()

    processors = structlog.get_config()["processors"]
    assert processors.index(scrub_exceptions) < processors.index(redact_sensitive)
    assert processors.index(redact_sensitive) < processors.index(renderer)

    try:
        _raise_with_content()
    except _ReadFailedError:
        structlog.get_logger("host").warning("read_failed", exc_info=True)

    out = capsys.readouterr().out
    _assert_no_content(out)
    assert "_ReadFailedError" in out


def test_a_host_chain_already_redacted_gains_the_scrubber_before_the_redactor() -> None:
    # A chain composed before this net existed already holds the redactor; the
    # scrubber goes ahead of it, where an exception object is still an exception.
    renderer = structlog.processors.KeyValueRenderer()
    structlog.configure(processors=[redact_sensitive, renderer])

    install_redaction()

    assert structlog.get_config()["processors"] == [scrub_exceptions, redact_sensitive, renderer]


def test_a_host_that_formats_exceptions_upstream_has_the_rendering_masked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    structlog.configure(
        processors=[
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    install_redaction()

    try:
        _raise_with_content()
    except _ReadFailedError:
        structlog.get_logger("host").warning("read_failed", exc_info=True)

    out = capsys.readouterr().out
    _assert_no_content(out)
    assert REDACTED in out


# --- A standard-library record carries no exception's words either (#2928) ---
#
# Records from the ``logging`` module — a third-party library's, asyncio's — never
# pass through structlog's chain. The rule is F7's: a record that carries an
# exception is replaced by a fresh one that prints its logger's name, its level, a
# fixed marker, and each exception's class and frames, never its message, its
# arguments or its extras. "Carries" is shallow: ``exc_info``, or an exception passed
# directly as the message, an argument or an extra. Every assertion is over what a
# handler writes. The root logger and its handlers are given back after each test by
# ``tests/conftest.py``'s ``root_logging_is_this_test_s_own``.

_WITHHELD = "[message withheld: the record carries an exception]"


def _ours() -> logging.StreamHandler[io.StringIO]:
    """This module's handler on the root logger, now writing to a fresh buffer."""
    ours = [
        one for one in logging.getLogger().handlers if type(one).__name__ == "_ContentFreeHandler"
    ]
    assert len(ours) == 1, "exactly one of this module's handlers is installed"
    handler = ours[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(io.StringIO())
    return handler


def _configured_on_a_bare_root() -> io.StringIO:
    """Configure logging where the root logger has no handler, as the hub's has none.

    Done in the test body: pytest attaches its capture handlers to the root for each
    phase, so a root emptied by a fixture would be filled again before the test ran.
    """
    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    configure_logging(Settings())
    return _ours().stream


def _configured_under_a_hosts_handler(fmt: str) -> io.StringIO:
    """Configure logging where a host's handler, with its own format, is already on the root."""
    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    stream = io.StringIO()
    hosts = logging.StreamHandler(stream)
    hosts.setFormatter(logging.Formatter(fmt))
    root.addHandler(hosts)
    configure_logging(Settings())
    return stream


def _record(msg: str, args: tuple[object, ...], failure: BaseException) -> logging.LogRecord:
    return logging.LogRecord(
        "thirdparty",
        logging.ERROR,
        __file__,
        1,
        msg,
        args,
        (type(failure), failure, failure.__traceback__),
    )


def test_a_stdlib_exception_line_carries_the_class_and_frames_and_never_the_words() -> None:
    # The marker is in the exception's message, an argument, the format string, an
    # extra and a raising frame's local.
    stream = _configured_on_a_bare_root()

    try:
        _raise_with_content()
    except _ReadFailedError:
        logging.getLogger("thirdparty").exception(
            f"read failed ({_CHAINED}): %s", _LOCAL, extra={"detail": _MESSAGE}
        )

    out = stream.getvalue()
    _assert_no_content(out)
    assert out.startswith(_WITHHELD + "\n"), "a fixed marker stands for the message"
    assert "_ReadFailedError" in out, "the class says what happened"
    assert "test_logging.py" in out, "the frames say where"
    assert "in _raise_with_content" in out


def test_a_hosts_format_keeps_the_logger_and_level() -> None:
    stream = _configured_under_a_hosts_handler("%(levelname)s %(name)s %(funcName)s %(message)s")
    failure = _caught(_raise_with_content)

    logging.getLogger("thirdparty").error("read failed", exc_info=failure)

    out = stream.getvalue()
    _assert_no_content(out)
    where = "test_a_hosts_format_keeps_the_logger_and_level"
    assert out.startswith(f"ERROR thirdparty {where} {_WITHHELD}\n")
    assert out.endswith("_ReadFailedError\n")


def test_no_extra_rides_a_replaced_record_so_a_host_format_naming_one_fails_without_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Adversarial review, round 4 under the second holder: an extra kept because it
    # was a number printed an SSN. No extra is copied — none masked, none kept — so a
    # host format naming one fails in the host's own handler.
    stream = _configured_under_a_hosts_handler("%(ssn)09d %(message)s")

    logging.getLogger("thirdparty").error(
        "lookup failed", exc_info=ValueError(123456789), extra={"ssn": 123456789}
    )

    err = capsys.readouterr().err
    out = stream.getvalue() + err
    assert "123456789" not in out
    _assert_no_content(out)
    assert "--- Logging error ---" in err, "the host's handler reports its own failure"
    assert f"Message: {_WITHHELD + chr(10) + 'ValueError'!r}" in err
    assert "Arguments: ()" in err


def test_a_host_handlers_failure_inside_an_except_block_reports_none_of_the_handled_words(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Adversarial review, round 1 under the third holder: ``logger.exception`` inside
    # an ``except`` block, and a host format naming an extra. The formatting failure
    # chains the exception being handled, and the stdlib's report prints that chain
    # with its words; this net's report prints its classes and frames alone.
    stream = _configured_under_a_hosts_handler("%(request_id)s %(message)s")

    try:
        _raise_with_content()
    except _ReadFailedError:
        logging.getLogger("thirdparty").exception("request failed", extra={"request_id": "safe-id"})

    err = capsys.readouterr().err
    _assert_no_content(stream.getvalue() + err)
    assert "--- Logging error ---" in err, "the stdlib's own report"
    assert "Formatting field not found in record: 'request_id'" in err
    assert "During handling" not in err, "cut from the exception being handled"
    assert "Arguments: ()" in err


def test_a_forwarding_handlers_targets_failure_reports_none_of_the_handled_words(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Adversarial review, round 2 under the third holder: a ``MemoryHandler`` on the
    # root forwards the replaced record to a target the net never attached to, which
    # fails on the same format inside the same ``except`` block.
    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    stream = io.StringIO()
    target = logging.StreamHandler(stream)
    target.setFormatter(logging.Formatter("%(request_id)s %(message)s"))
    root.addHandler(logging.handlers.MemoryHandler(capacity=1, target=target))
    configure_logging(Settings())

    try:
        _raise_with_content()
    except _ReadFailedError:
        logging.getLogger("thirdparty").exception("request failed", extra={"request_id": "safe-id"})

    err = capsys.readouterr().err
    _assert_no_content(stream.getvalue() + err)
    assert "--- Logging error ---" in err
    assert "During handling" not in err


def test_a_socket_handlers_recovery_still_runs_on_a_replaced_records_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Adversarial review, round 4 under the third holder: a root handler's own
    # ``handleError`` was bypassed for a replaced record, so a socket handler kept a
    # failed socket instead of closing it to reconnect.
    class FailedSocket:
        closed = False

        def sendto(self, *_args: object) -> None:
            raise OSError("send failed")

        def close(self) -> None:
            self.closed = True

    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    handler = logging.handlers.DatagramHandler("localhost", 9)
    handler.closeOnError = True
    sock = FailedSocket()
    handler.sock = sock  # type: ignore[assignment]  # a fake socket that fails to send
    root.addHandler(handler)
    configure_logging(Settings())

    try:
        _raise_with_content()
    except _ReadFailedError:
        logging.getLogger("thirdparty").exception("read failed")

    assert sock.closed, "the handler's own recovery ran"
    assert handler.sock is None
    _assert_no_content(capsys.readouterr().err)


def test_a_processor_formatter_hosts_failure_on_a_wrapped_event_reports_no_words(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The same failure, on a structlog event a host formats through
    # ``ProcessorFormatter`` with a format naming an extra.
    stream = _hosted_by_processor_formatter("%(message)s|%(detail)s")

    try:
        _raise_with_content()
    except _ReadFailedError as failure:
        structlog.get_logger("host").warning("read_failed", exc_info=failure)

    err = capsys.readouterr().err
    _assert_no_content(stream.getvalue() + err)
    assert "--- Logging error ---" in err
    assert "read_failed" in err, "the message is the event, put through the structlog net"


def test_a_host_handlers_failure_on_its_own_record_is_reported_by_the_host(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Only a record this net built is reported this way; a host's own failure on a
    # record that carries no exception is the stdlib's to report, as before the net.
    _configured_under_a_hosts_handler("%(request_id)s %(message)s")

    logging.getLogger("thirdparty").error("plain")

    err = capsys.readouterr().err
    assert "--- Logging error ---" in err
    assert "Message: 'plain'" in err
    assert "Call stack:" in err, "the stdlib's own report"


@pytest.mark.parametrize(
    "logged",
    [
        pytest.param(lambda log, failure: log.error("read failed: %s", failure), id="argument"),
        pytest.param(lambda log, failure: log.error("read failed: %r", failure), id="%r"),
        pytest.param(
            lambda log, failure: log.error(f"read failed: {failure!r}", exc_info=failure),
            id="f-string",
        ),
        pytest.param(lambda log, failure: log.error(failure), id="message"),
        pytest.param(
            lambda log, failure: log.error("read %(what)s", {"what": failure}),
            id="sole mapping argument",
        ),
        pytest.param(
            lambda log, failure: log.error("read failed", extra={"failure": failure}), id="extra"
        ),
    ],
)
def test_a_record_carrying_an_exception_directly_prints_neither_message_nor_arguments(
    logged: Callable[[logging.Logger, BaseException], None],
) -> None:
    stream = _configured_on_a_bare_root()
    failure = _caught(_raise_chained)

    logged(logging.getLogger("thirdparty"), failure)

    out = stream.getvalue()
    _assert_no_content(out)
    assert out.startswith(_WITHHELD + "\n")
    assert "RuntimeError" in out, "the exception is shown by its class"
    assert "in _raise_chained" in out, "and its frames"


def test_words_rebuilt_from_an_exception_are_not_printed() -> None:
    # Adversarial review, round 7 under the first holder: a message that rebuilds an
    # exception's text from its parts, or from two overlapping ones, after any check
    # of the words. No string is printed, so no shape of the words is.
    stream = _configured_on_a_bare_root()
    log = logging.getLogger("thirdparty")
    rebuilt = ValueError({"detail": _MESSAGE})
    overlapping = ValueError(f"user={_LOCAL}", f"{_LOCAL} {_CHAINED}")

    log.error("%s", rebuilt.args[0], exc_info=rebuilt)
    log.error("%s", f"user={_LOCAL} {_CHAINED}", exc_info=overlapping)

    out = stream.getvalue()
    _assert_no_content(out)
    assert out.count(_WITHHELD) == len(("rebuilt", "overlapping"))


def test_a_record_carrying_no_exception_prints_byte_for_byte_as_it_did() -> None:
    # Content a call site puts into a record with no exception is the call site's
    # convention (ADR-0004 §5), not this net's. Compared with the same host format
    # on a handler the net never reached.
    fmt = "%(levelname)s %(name)s %(message)s|%(detail)s %(elapsed).3f"
    stream = _configured_under_a_hosts_handler(fmt)
    bare = io.StringIO()
    unscrubbed = logging.StreamHandler(bare)
    unscrubbed.setFormatter(logging.Formatter(fmt))
    logging.getLogger().addHandler(unscrubbed)

    logging.getLogger("thirdparty").error(
        "header %r, read %s of %s",
        b"raw",
        {"count": 2},
        PurePath("/data/x"),
        extra={"detail": "the call site's", "elapsed": 1.25},
    )

    expected = (
        "ERROR thirdparty header b'raw', read {'count': 2} of /data/x|the call site's 1.250\n"
    )
    assert bare.getvalue() == expected
    assert stream.getvalue() == expected


def test_an_exception_nested_one_level_down_is_left_to_the_call_site_by_the_shallow_rule() -> None:
    # The shallow rule, pinned: "carries" is an exception passed directly. One held
    # inside a container is the call site's to keep out of a log (ADR-0004 §5), and
    # the record prints as it was logged.
    stream = _configured_on_a_bare_root()
    failure = ValueError("held inside")

    logging.getLogger("thirdparty").error("failures: %s", [failure])

    assert stream.getvalue() == "failures: [ValueError('held inside')]\n"


def test_an_exception_passed_twice_is_shown_once() -> None:
    stream = _configured_on_a_bare_root()
    failure = _caught(_raise_chained)

    logging.getLogger("thirdparty").error("failed: %s", failure.__cause__, exc_info=failure)

    out = stream.getvalue()
    _assert_no_content(out)
    assert out.count("_ReadFailedError\n") == 1, "the cause is shown in the chain, once"


def test_an_exception_whose_arguments_share_values_is_never_rendered_to_text() -> None:
    # ``str(failure)`` over ``[shared, shared]`` nested sixteen times calls the leaf's
    # repr 65,536 times. No exception's text or repr is built.
    calls = 0

    class Leaf:
        def __repr__(self) -> str:
            nonlocal calls
            calls += 1
            return _MESSAGE

    stream = _configured_on_a_bare_root()
    shared: object = Leaf()
    for _ in range(16):
        shared = [shared, shared]

    logging.getLogger("thirdparty").error("operation failed", exc_info=ValueError(shared))

    assert calls == 0
    out = stream.getvalue()
    _assert_no_content(out)
    assert out.rstrip().endswith("ValueError")


def test_groups_sharing_members_are_logged_at_a_bounded_length() -> None:
    # Seventeen exceptions, each group holding the one before it twice, have a repr of
    # millions of characters; each is shown once.
    stream = _configured_on_a_bare_root()
    shared: Exception = ValueError(_MESSAGE)
    for _ in range(16):
        shared = ExceptionGroup(_CHAINED, [shared, shared])

    logging.getLogger("thirdparty").error("pass failed: %s", shared, exc_info=shared)
    logging.getLogger("thirdparty").error("pass failed: %r", shared)

    out = stream.getvalue()
    _assert_no_content(out)
    assert len(out) < 10_000


def test_a_field_a_hosts_record_factory_adds_is_not_carried_over() -> None:
    # The standard fields are read off a record built directly, and the fresh record
    # is built by the ``LogRecord`` class, never through the factory a host installed
    # before importing this package. The host's format names the field, so the host's
    # handler reports its own failure, with the fixed message and ``()`` alone.
    script = (
        "import io, logging\n"
        "made = logging.getLogRecordFactory()\n"
        "def factory(*args, **kwargs):\n"
        "    record = made(*args, **kwargs)\n"
        f"    record.failure = ValueError({_MESSAGE!r})\n"
        "    return record\n"
        "logging.setLogRecordFactory(factory)\n"
        "stream = io.StringIO()\n"
        "hosts = logging.StreamHandler(stream)\n"
        "hosts.setFormatter(logging.Formatter('%(message)s|%(failure)s'))\n"
        "logging.getLogger().addHandler(hosts)\n"
        "import ai_assistant.core.logging\n"
        "logging.getLogger('thirdparty').error('read failed')\n"
        "print(stream.getvalue())\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    _assert_no_content(result.stdout + result.stderr)
    assert result.stdout == "\n", "the host's handler wrote nothing"
    assert "--- Logging error ---" in result.stderr
    assert f"Message: {_WITHHELD + chr(10) + 'ValueError'!r}" in result.stderr
    assert "Arguments: ()" in result.stderr


def test_a_message_another_handler_cached_is_not_handed_on() -> None:
    # A formatter caches ``message`` on the record it formats.
    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    first = logging.StreamHandler(io.StringIO())
    root.addHandler(first)
    stream = io.StringIO()
    root.addHandler(logging.StreamHandler(stream))
    configure_logging(Settings())
    first.filters.clear()  # a handler the net never reached formats the record first

    logging.getLogger("thirdparty").error("read failed: %s", ValueError(_MESSAGE))

    assert stream.getvalue() == f"{_WITHHELD}\nValueError\n"


async def _fail_with_content() -> None:
    _raise_with_content()


def test_asyncios_unretrieved_task_line_carries_no_words() -> None:
    # asyncio's own message embeds the task's repr, and that holds the exception's:
    # ``exception=_ReadFailedError('MARKER…')``. It sets ``exc_info``, so the message
    # is withheld. Emitted by the loop's real default handler, over a real finished
    # task.
    stream = _configured_on_a_bare_root()

    async def run() -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_fail_with_content())
        await asyncio.wait([task])
        failure = task.exception()
        assert failure is not None
        loop.default_exception_handler(
            {"message": "Task exception was never retrieved", "exception": failure, "future": task}
        )

    asyncio.run(run())

    out = stream.getvalue()
    _assert_no_content(out)
    assert out.startswith(_WITHHELD + "\n")
    assert "_ReadFailedError" in out
    assert "in _raise_with_content" in out


def _raise_it(failure: BaseException) -> None:
    raise failure


def test_asyncios_debug_callback_line_carries_no_words() -> None:
    # asyncio's debug mode prints a callback's arguments through reprlib, which cuts
    # a long repr to ``ValueError('M…<end>')``.
    stream = _configured_on_a_bare_root()
    failure = ValueError(_MESSAGE + "x" * 100 + _CHAINED)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        loop.set_debug(True)
        loop.call_soon(_raise_it, failure)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run())

    out = stream.getvalue()
    _assert_no_content(out)
    assert _WITHHELD in out
    assert "in _raise_it" in out


def test_the_net_holds_where_the_root_already_has_a_handler() -> None:
    # ``basicConfig`` does nothing at all where the root has a handler, so under
    # pytest, or in a host that configured logging first, the stdlib's formatter
    # went on printing the exception's message.
    stream = _configured_under_a_hosts_handler("HOST %(levelname)s %(message)s")
    root = logging.getLogger()

    assert len(root.handlers) == 1, "a host's handler is composed with, not joined"
    try:
        _raise_with_content()
    except _ReadFailedError:
        logging.getLogger("thirdparty").exception("read failed: %s", _caught(_raise_chained))

    out = stream.getvalue()
    _assert_no_content(out)
    assert out.startswith(f"HOST ERROR {_WITHHELD}\n"), "the host's format is kept"
    assert "_ReadFailedError" in out
    assert "RuntimeError" in out, "an argument's exception is shown by its class too"


def test_a_host_that_configured_structlog_has_its_root_handlers_scrubbed() -> None:
    stream = io.StringIO()
    logging.getLogger().addHandler(logging.StreamHandler(stream))
    structlog.configure(processors=[structlog.processors.KeyValueRenderer()])

    install_redaction()

    logging.getLogger("thirdparty").error("read failed", exc_info=_caught(_raise_with_content))
    _assert_no_content(stream.getvalue())
    assert "_ReadFailedError" in stream.getvalue()


def _hosted_by_processor_formatter(fmt: str = "%(message)s") -> io.StringIO:
    """A host that formats every record through structlog's ``ProcessorFormatter``."""
    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    root.setLevel(logging.INFO)
    stream = io.StringIO()
    hosts = logging.StreamHandler(stream)
    hosts.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            fmt=fmt,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=False),
            ],
        )
    )
    root.addHandler(hosts)
    structlog.configure(
        processors=[structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    install_redaction()
    return stream


def test_a_structlog_event_formatted_by_a_hosts_processor_formatter_keeps_working() -> None:
    # A structlog event wrapped for ProcessorFormatter carries its event dict as the
    # record's message; made a string, the formatter fails on it and the event is
    # lost. It is put through this module's structlog net instead.
    stream = _hosted_by_processor_formatter()
    failure = _caught(_raise_with_content)

    structlog.get_logger("host").warning(
        "read_failed", api_key="sk-live-SECRET", held=failure, exc_info=failure
    )

    out = stream.getvalue()
    _assert_no_content(out)
    assert "sk-live-SECRET" not in out
    assert "read_failed" in out
    assert "_ReadFailedError" in out


def test_a_foreign_record_formatted_by_a_hosts_processor_formatter_keeps_its_class() -> None:
    # Adversarial review, round 1 under this holder: ``ProcessorFormatter`` drops a
    # record's ``exc_text`` by default, so the description travels in the message.
    stream = _hosted_by_processor_formatter()

    try:
        _raise_with_content()
    except _ReadFailedError:
        logging.getLogger("thirdparty").exception("foreign failed: %s", _LOCAL)

    out = stream.getvalue()
    _assert_no_content(out)
    assert _WITHHELD in out
    assert "_ReadFailedError" in out, "the class"
    assert "in _raise_with_content" in out, "and the frames"


def test_a_wrapped_structlog_event_carrying_an_exception_is_handed_on_with_no_extra() -> None:
    # Adversarial review, rounds 1 and 2 under the second holder: a host record
    # factory's field — an exception, or an exception's text — rode a wrapped
    # structlog event. An event that carries an exception is handed on as a fresh
    # record holding only ``ProcessorFormatter``'s plumbing. (A host formatter that
    # calls the host's factory again is the host's own: brief F8c, rule 2.)
    made = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = made(*args, **kwargs)
        record.failure = ValueError(_MESSAGE)
        record.detail = str(sys.exc_info()[1])
        return record

    _hosted_by_processor_formatter()
    root = logging.getLogger()
    (host,) = root.handlers
    root.removeHandler(host)
    logged: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logged.append(record)

    root.addHandler(Keep())
    logging.setLogRecordFactory(factory)
    try:
        structlog.get_logger("host").warning("plain")
        try:
            _raise_with_content()
        except _ReadFailedError as failure:
            structlog.get_logger("host").warning("read_failed", exc_info=failure)
    finally:
        logging.setLogRecordFactory(made)

    handed = [host.filter(one) for one in logged]
    for one in handed:
        assert isinstance(one, logging.LogRecord)
        assert not hasattr(one, "failure"), "no extra is carried over"
        assert not hasattr(one, "detail")
        assert hasattr(one, "_logger"), "ProcessorFormatter's plumbing is"
    formatter = host.formatter
    assert formatter is not None
    out = "\n".join(formatter.format(one) for one in handed if isinstance(one, logging.LogRecord))
    _assert_no_content(out)
    assert "plain" in out
    assert "read_failed" in out
    assert "_ReadFailedError" in out


def test_the_last_resort_handler_is_scrubbed_too() -> None:
    # With no handler anywhere, the logging module writes through ``lastResort``,
    # whose formatter is the stdlib's default.
    configure_logging(Settings())
    last = logging.lastResort
    assert last is not None

    scrubbed = last.filter(_record("read failed", (), _caught(_raise_with_content)))

    assert isinstance(scrubbed, logging.LogRecord)
    out = logging.Formatter().format(scrubbed)
    _assert_no_content(out)
    assert "_ReadFailedError" in out


def test_other_handlers_are_handed_the_record_as_logged() -> None:
    _configured_on_a_bare_root()
    seen: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    logging.getLogger().addHandler(Keep())
    failure = _caught(_raise_with_content)

    logging.getLogger("thirdparty").error("read failed: %s", failure, exc_info=failure)

    assert seen[0].args == (failure,), "the scrubbing is a copy, not the record itself"


def test_configuring_twice_installs_one_handler_and_one_filter() -> None:
    _configured_on_a_bare_root()
    configure_logging(Settings())
    install_redaction()

    _ours()
    for handler in logging.getLogger().handlers:
        assert sum(type(one).__name__ == "_ScrubRecords" for one in handler.filters) == 1


def test_a_stdlib_formatting_failure_drops_the_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Fail closed, as the structlog chain does. The stdlib's own reaction to a
    # handler's failure prints the record's message and arguments to stderr, so that
    # path is closed too.
    def explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("formatting failed")

    stream = _configured_on_a_bare_root()
    failure = _caught(_raise_with_content)
    monkeypatch.setattr("traceback.extract_tb", explode)

    logging.getLogger("thirdparty").error("read failed: %s", failure, exc_info=failure)
    assert stream.getvalue() == "", "the filter drops it"

    handler = _ours()
    handler.emit(_record("read failed: %s", (failure,), failure))
    assert handler.stream.getvalue() == "", "and so does the formatter, past the filter"

    captured = capsys.readouterr()
    _assert_no_content(captured.out + captured.err)
    assert "Logging error" not in captured.err


def test_the_formatter_is_the_second_net() -> None:
    # Were a record to reach the handler past its filter (``emit`` called directly),
    # the formatter scrubs it itself.
    _configured_on_a_bare_root()
    formatter = _ours().formatter
    assert formatter is not None
    failure = _caught(_raise_chained)

    out = formatter.format(_record("read failed: %r", (failure,), failure))

    _assert_no_content(out)
    assert "RuntimeError" in out
    _assert_no_content(formatter.formatException((type(failure), failure, None)))


def test_a_traceback_formatted_before_the_net_is_masked() -> None:
    # A record sent over a socket carries its traceback as text alone, with no
    # exception left to render; its words cannot be told from its frames.
    stream = _configured_on_a_bare_root()
    record = logging.makeLogRecord(
        {"name": "remote", "levelno": logging.ERROR, "levelname": "ERROR", "msg": "read failed"}
    )
    record.exc_text = f"Traceback (most recent call last):\n_ReadFailedError: {_MESSAGE}"

    logging.getLogger("remote").handle(record)

    assert stream.getvalue() == f"{_WITHHELD}\n{REDACTED}\n"


# --- Follow-ups to F7 and F8: #2930, #2976, #2977, #2980 ---


def _shortened() -> tuple[type[BaseException], BaseException, TracebackType]:
    """An ``exc_info`` tuple whose traceback is not its exception's current one.

    The exception's own traceback starts in ``_caught``; the tuple's starts in the
    raiser, as a caller that saved or shortened it would hand it on.
    """
    failure = _caught(_raise_with_content)
    whole = failure.__traceback__
    assert whole is not None
    assert whole.tb_next is not None
    return type(failure), failure, whole.tb_next


@pytest.mark.parametrize("path", ["chain", "renderer", "stdlib", "formatter"])
def test_an_exc_info_tuples_own_traceback_is_the_one_shown(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Issue #2930: the frames shown were the exception's current ones, not the
    # tuple's, in the structlog chain and the renderer's formatter, and in the
    # stdlib's handler and formatter.
    exc_info = _shortened()
    if path == "chain":
        configure_logging(Settings())
        structlog.get_logger(__name__).warning("read_failed", exc_info=exc_info)
        out = capsys.readouterr().out
    elif path == "renderer":
        configure_logging(Settings())
        out = _installed_renderer()(None, "warning", {"event": "e", "exc_info": exc_info})
    elif path == "stdlib":
        stream = _configured_on_a_bare_root()
        logging.getLogger("thirdparty").error("read failed", exc_info=exc_info)
        out = stream.getvalue()
    else:
        _configured_on_a_bare_root()
        formatter = _ours().formatter
        assert formatter is not None
        out = formatter.formatException(exc_info)

    _assert_no_content(out)
    assert "_ReadFailedError" in out
    assert "in _raise_with_content" in out, "the tuple's frames"
    assert "in _caught" not in out, "and not the exception's own"


def test_a_wrapped_events_record_exc_info_a_factory_set_keeps_its_class_and_frames() -> None:
    # Issue #2976: structlog's ``wrap_for_formatter`` passes no ``exc_info``, but a
    # host's record factory may set one. Described in ``exc_text`` alone, it was
    # cleared by ``ProcessorFormatter`` before it rendered.
    made = logging.getLogRecordFactory()
    failure = _caught(_raise_with_content)

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = made(*args, **kwargs)
        record.exc_info = (type(failure), failure, failure.__traceback__)
        return record

    stream = _hosted_by_processor_formatter()
    logging.setLogRecordFactory(factory)
    try:
        structlog.get_logger("host").warning("read_failed")
    finally:
        logging.setLogRecordFactory(made)

    out = stream.getvalue()
    _assert_no_content(out)
    assert "read_failed" in out
    assert out.count("._ReadFailedError\n") == 1, "the class, once"
    assert "in _raise_with_content" in out, "and the frames"


def test_the_root_handlers_come_back_in_their_order() -> None:
    # Issue #2977: removed handlers were re-appended, so removing the first of
    # ``[A, B]`` handed on ``[B, A]``.
    root = logging.getLogger()
    first, second = logging.NullHandler(), logging.NullHandler()
    root.handlers[:] = [first, second]

    with conftest.root_logging_restored():
        root.removeHandler(first)

    assert root.handlers == [first, second]


def test_concurrent_configuration_on_a_bare_root_installs_one_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Issue #2980: the first caller is held between finding no handler and adding
    # its own while a second caller runs as far as it can. Unlocked, the second
    # also finds none and adds one; under the logging module's lock it waits, then
    # finds the first's.
    root = logging.getLogger()
    for one in list(root.handlers):
        root.removeHandler(one)
    settings = Settings()
    add = logging.Logger.addHandler
    second: list[threading.Thread] = []
    failures: list[BaseException] = []

    def configure() -> None:
        try:
            configure_logging(settings)
        except BaseException as exc:
            failures.append(exc)

    def adding(self: logging.Logger, handler: logging.Handler) -> None:
        if not second:
            other = threading.Thread(target=configure)
            second.append(other)
            other.start()
            other.join(timeout=0.5)
        add(self, handler)

    monkeypatch.setattr(logging.Logger, "addHandler", adding)
    configure_logging(settings)
    second[0].join(timeout=10)

    assert not second[0].is_alive()
    assert not failures
    _ours()
    for handler in root.handlers:
        assert sum(type(one).__name__ == "_ScrubRecords" for one in handler.filters) == 1

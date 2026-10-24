"""The CLI adapter: thin rendering and the relay to the engine (ADR-0042 §4, §6, §7).

Rendering is checked against captured Rich output; commands are driven against
a real :class:`Engine` assembled from canonical fakes (the adapter cannot tell it
from the production engine — that is the point of the façade). Nothing here builds
the production, model-backed engine, so no network or key is needed.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import re
import shlex
import socket
import sys
from datetime import UTC, datetime, timedelta
from inspect import getsource, isfunction, unwrap
from io import StringIO
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
import typer.main
from cli_open_recorder import wire_recording_opens
from rich.console import Console
from typer.core import TyperGroup
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConfigurationError,
    GrantError,
    InvalidGrantError,
    MemoryStoreError,
    OversizedValueError,
    PlanningError,
    UngrantableSourceError,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    ClassReach,
    DataTier,
    EpisodicMemory,
    GrantScope,
    HeldNotification,
    Memory,
    MemoryKind,
    MemoryMark,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    NotificationCandidate,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    Provenance,
    QuietWindow,
    ReadingCertainty,
    StatementCitation,
    SupportDirection,
    SupportHolder,
    SupportPart,
    TrackRecordSummary,
    Validity,
    belief_view,
    episode_view,
)
from ai_assistant.interfaces import cli
from ai_assistant.orchestration import (
    ConnectionOperations,
    ConversationLifecycle,
    Engine,
    GrantOperations,
    HeldSource,
)
from ai_assistant.orchestration.upcoming import NOTIFICATION_CLASS
from ai_assistant.readers.calendar import CALENDAR_READER_NAME
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeAuditTrail,
    FakeConnectionProvisioner,
    FakeConversationStore,
    FakeMemoryStore,
    FakePlanStore,
    FakeSourceGrantStore,
    FakeSourceReadTrail,
    FakeTraceRetention,
    FakeTraceSink,
)
from ai_assistant.testing.memories import (
    confirmed_support,
    legacy_support,
    memory,
    memory_in_band,
    message_support,
    remembered_support,
    said_support,
    sourced_support,
)
from ai_assistant.wire import GRANTABLE_SCOPES, TransportError
from ai_assistant.wire.address import sun_path_limit

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import SourceGrant


AT = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)


def _grant_ids() -> Callable[[], str]:
    """Ids that differ per call, so a second record is never a duplicate."""
    numbers = count(1)
    return lambda: f"grant-{next(numbers)}"


def _grant_operations(sources: Sequence[HeldSource] = ()) -> GrantOperations:
    """The grant collaborator every ``Engine`` needs (ADR-0102 §7).

    Required rather than optional on the façade, like ``questions`` and
    ``observation``: the four grant methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. Empty
    ``sources`` is the ordinary deployment — a reader ships disabled, so nothing is
    grantable until one is configured (ADR-0093 §7).
    """
    return GrantOperations(
        store=FakeSourceGrantStore(),
        sources=sources,
        id_factory=_grant_ids(),
        clock=lambda: AT,
    )


def _connection_operations() -> ConnectionOperations:
    """The connection collaborator every ``Engine`` needs (ADR-0151 §10).

    Required rather than optional on the façade, on ``_grant_operations``' reason
    exactly: the five connection methods are on the Protocol, so an engine that
    could be built without them is one whose surface is conditionally present. The
    canonical fake is the subject, so a case that wants a live record, a pending
    one, or a keyring that raises scripts it through the provisioner's own switches
    rather than through a second double.
    """
    return ConnectionOperations(provisioner=FakeConnectionProvisioner())


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _engine(
    *,
    closers: Sequence[Callable[[], Awaitable[None]]] = (),
    memory: FakeMemoryStore | None = None,
) -> Engine:
    """A real ``Engine`` over canonical fakes."""
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    memory = FakeMemoryStore(now=lambda: AT) if memory is None else memory
    conversations = FakeConversationStore(now=lambda: AT)
    return Engine(
        chat_reader=False,
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        plans=plans,
        trail=trail,
        spend=trail,
        # ADR-0186 §10's read trail. Empty and unwired to any driver here: this
        # module's cases are about what the CLI renders, and the two read
        # operations have no CLI door yet — §9's commands are the decision pair's
        # and the read pair's consumer lane is its own (ADR-0186 §11).
        reads=FakeSourceReadTrail(),
        memory=memory,
        # The narrow deletion seam and its horizon (ADR-0119 §7, §10). Required on
        # the façade, and nothing in this module sweeps: an adapter test is about
        # what the CLI renders, not about the maintenance operation.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
        ),
        closers=closers,
    )


# --- rendering: a wrapped line keeps a marker its value cannot forge (#2072) --
# Every case here binds its own narrow console. The shared `output` fixture is 100
# columns wide and almost nothing in this module wraps there, which is why the
# mechanism went unasserted until now: the defect is a property of the *break*, and
# a width at which nothing breaks cannot see it.

#: The marker :func:`cli._print` writes onto every display line a wrapped line runs
#: onto. Read from the module rather than respelled: a copy here would keep passing
#: if the renderer changed the character.
_CONTINUATION: Final = cli._CONTINUATION

#: A card field forged inside a value. It carries the two-space indent the
#: confirmation card's own fields carry, so at some width it would otherwise land at
#: the head of a display line and read as one this adapter wrote.
_FORGED_FIELD: Final = "  Why: nothing leaves this device"


def _narrow(monkeypatch: pytest.MonkeyPatch, buffer: StringIO, width: int) -> None:
    """Bind the CLI's console to ``buffer`` at ``width``, colour off."""
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=width))


@pytest.mark.parametrize("length", [12, 34, 36, 39, 40], ids=str)
def test_a_line_that_fits_the_console_is_printed_exactly_as_it_was(
    monkeypatch: pytest.MonkeyPatch, length: int
) -> None:
    """The claim that keeps this from being a change to every rendering in the module.

    Only a line the console would have broken renders differently, so a line that fits
    is compared against what a bare :meth:`rich.console.Console.print` of the same
    markup produces — byte for byte, the markup resolution included, rather than "looks
    the same after flattening".

    The lengths run up to the console's own width because the band between the room
    beside the marker and the width itself is where the two renderings would otherwise
    part company: measured against the room, a line of 37 to 40 columns would break
    where Rich would have left it whole, and every such line on this surface would
    acquire a break and a marker it had never had. Asked first whether it fits, it does
    not.
    """
    line = f"  Why: {'x' * (length - len('  Why: '))}"
    assert len(line) == length
    printed = StringIO()
    _narrow(monkeypatch, printed, 40)

    cli._print(line)

    reference = StringIO()
    Console(file=reference, force_terminal=False, width=40).print(line)
    assert printed.getvalue() == reference.getvalue()


def test_a_wrapped_line_marks_every_display_line_after_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2072's whole subject, on the display line rather than in the buffer.

    Rich repeats no literal prefix on the continuations it wraps, so before this the
    tail of a long value arrived at the margin carrying nothing that said it was data.
    The head keeps the line's own indent and every line under it carries that indent
    plus the marker, so no display line of the value can be read as a field this
    adapter wrote.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 40)

    cli._print(f"  Why: {' '.join(f'word{n}' for n in range(40))}")

    lines = output.getvalue().splitlines()
    assert len(lines) > 1  # it really did wrap
    assert lines[0].startswith("  Why: ")
    assert all(line.startswith(f"  {_CONTINUATION}") for line in lines[1:]), lines


@pytest.mark.parametrize(
    ("value", "folds"),
    [("x" * 300, True), (" ".join(f"word{n}" for n in range(60)), False)],
    ids=["an unbroken run", "ordinary words"],
)
def test_a_wrapped_line_loses_no_character_and_no_word(
    monkeypatch: pytest.MonkeyPatch, value: str, folds: bool
) -> None:
    """What the wrapping costs is one space per break and nothing else.

    Both shapes, because they take different paths through Rich's wrapper: an unbroken
    run has nowhere to break and is folded, so its pieces concatenate back to it
    character for character; a run of words breaks at a space and consumes it, because
    on a screen the break *is* that space. Nothing is truncated, elided or summarised
    either way, which is the property a marker would be worthless without — a reader
    who cannot trust the text has no use for knowing it is data.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 40)

    cli._print(f"  {value}")

    lines = output.getvalue().splitlines()
    gutter = f"  {_CONTINUATION}"
    pieces = [lines[0][len("  ") :], *(line[len(gutter) :] for line in lines[1:])]
    assert len(pieces) > 1
    if folds:
        assert "".join(pieces) == value
    else:
        assert " ".join(pieces).split() == value.split()


def test_a_blank_line_the_composed_string_carries_is_a_blank_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leading or trailing newline spaces a block; it does not continue one.

    Every ``\\n`` a composed line in this module carries sits ahead of the content or
    after it — none separates two pieces of content — so reproducing them as the blank
    lines they are keeps the marker for breaks that actually continue something. A
    renderer that marked the line after a leading newline would put the marker on the
    head of every spaced block on this surface.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 40)

    cli._print("\n  [bold cyan]rec-1[/]")
    cli._print("About to connect.\n")

    assert output.getvalue() == "\n  rec-1\nAbout to connect.\n\n"


def test_a_break_a_prose_value_keeps_after_the_head_is_marked_as_a_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where the break is the *value's*, the line under it is still marked as data.

    :func:`cli._safe_prose` keeps a value's newlines, because prose is legitimately more
    than one line, so a line interpolating it is the one shape here where a break sits
    between two pieces of content rather than ahead of or after them. :func:`cli._print`
    reads a break after a line's head as a continuation of it wherever the break came
    from, so a value that spells a field on its second line puts it behind the marker
    and never at the head of a display line of its own.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 200)
    forged = "  Conversation: c9"
    value = cli._safe_prose(f"where did I put the lease\n{forged}")

    cli._print(f"  [bold]You:[/] {value}")

    lines = output.getvalue().splitlines()
    assert lines == ["  You: where did I put the lease", f"  {_CONTINUATION}{forged}"]


def test_a_wrapped_listing_row_carries_the_marker_though_its_content_is_one_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """:func:`cli._render_content`'s single-line arm was itself a #2072 site.

    That renderer takes the wrapping and writes a gutter onto every piece **where the
    content is more than one line**; a single-line content is "printed exactly as it
    was", which is right about the forgery a newline opens and silent about the one a
    wrap opens. So the row's own arm goes through :func:`cli._print` like every other
    authored line, and a long single-line content no longer runs to the margin
    unmarked.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 40)

    cli._render_belief_summary(_summary(content=f"{'padding ' * 20}{_FORGED_FIELD}"))

    body = [line for line in output.getvalue().splitlines() if "padding" in line]
    assert len(body) > 1
    assert all(line.startswith(f"  {_CONTINUATION}") for line in body[1:]), body
    assert "│" not in "".join(body)  # the block gutter still means the other thing


def test_a_wrapped_error_line_carries_the_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error boundary, which writes at column 0 and takes a message from the hub.

    ADR-0042 §7 makes rendering the failure the adapter's, and the message is the
    engine's own text on a line this adapter authored — so it wraps like any other and
    is marked like any other. At column 0 the gutter is the marker alone, since there
    is no indent to keep.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 40)

    cli._render_error(MemoryStoreError(f"{'padding ' * 20}{_FORGED_FIELD}"))

    lines = output.getvalue().splitlines()
    assert lines[0].startswith("Error: ")
    assert all(line.startswith(_CONTINUATION) for line in lines[1:]), lines


def test_the_marker_reaches_a_real_command_through_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end, on the console a command actually prints through.

    Every other case here calls a renderer; this one drives ``assistant beliefs`` to a
    failure whose message is longer than the console, so the marker is asserted on what
    the command wrote rather than on what a helper returns.

    The console is bound with ``force_terminal=False``, so no SGR sequence reaches the
    buffer and the assertion is about the text rather than about the colour — the
    normalisation ``_help_text`` performs for Typer's own console, taken here by
    construction rather than after the fact.
    """
    output = StringIO()
    _narrow(monkeypatch, output, 40)
    _wire(monkeypatch, _UnavailableBeliefEngine())

    result = CliRunner().invoke(cli.app, ["beliefs"])

    assert result.exit_code == 1
    lines = output.getvalue().splitlines()
    assert "\x1b" not in output.getvalue()  # colour off: the assertion is about text
    assert lines[0].startswith("Error: ")
    assert len(lines) > 1
    assert all(line.startswith(_CONTINUATION) for line in lines[1:]), lines


class _UnavailableBeliefEngine:
    """A façade whose listing fails with a message longer than a narrow console."""

    async def beliefs(self, **_kwargs: object) -> tuple[Belief, ...]:
        """Fail the way the hub's store failure reaches this adapter."""
        raise MemoryStoreError(f"the store is unavailable {'and stays unavailable ' * 6}")

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


# --- the adapter mints no ruling (ADR-0042 §6, ADR-0186 §1) -----------------


def test_the_cli_mints_no_ruling_and_authorises_nothing(output: StringIO) -> None:
    """ADR-0042 §6, narrowed by ADR-0186 §1 rather than dropped.

    This case used to forbid the *name* ``PermissionDecision`` in this module
    outright, together with ``ActionRequest``, ``EgressBinding`` and ``ToolCall``.
    ADR-0186 §1 promotes two operations that **return**
    ``tuple[PermissionDecision, ...]`` and §9 obliges this module to render what they
    return, so the blanket form is now false: a ruling reaches this adapter the way a
    ``Confirmation`` does, handed over the engine surface, and §7's floor cannot be
    paid without naming the value it is stated over.

    What ADR-0042 §6 actually forbids survives intact, in the two forms it can take.
    **This adapter never mints a ruling**: it constructs no ``PermissionDecision``, no
    binding, and reaches no ``from_request`` — the fabrication ADR-0184 §4 closed the
    last route to. And **it never computes an authorisation**, which is ADR-0186 §8's
    second clause, "no surface computes, displays or implies
    ``PermissionDecision.authorises``".

    Call shapes are what is scanned for rather than bare words, because
    ``_render_decision``'s own docstring cites the bars it is written against, and a
    module forbidden to *name* the rule it obeys is a module whose reasoning has to
    live somewhere else.
    """
    source = getsource(cli)
    for forbidden in ("ActionRequest", "ToolCall", "from_request", "authorises("):
        assert forbidden not in source, f"interfaces/cli.py names {forbidden}"
    for minted in ("PermissionDecision(", "EgressBinding(", "OriginUnrecordedBinding("):
        assert minted not in source, f"interfaces/cli.py constructs {minted}"


def test_a_recorded_ruling_reaches_the_audit_surface_and_nothing_else() -> None:
    """ADR-0178 §5's third clause, pinned where a source scan can no longer pin it.

    §5 built a ``ConfirmationEgress`` from the recorded decision *in `core`*, so the
    card's facts reached this adapter as a member of ``Confirmation`` and the
    confirmation path, until it retired (ADR-0309 §5), never held a ruling. That used
    to be guaranteed by the module naming no decision at all; since ADR-0186 §9 it has
    to be guaranteed by **where** the decision goes instead.

    So the walk asserts the whole set rather than spot-checking: a decision, or either
    binding it may carry, is annotated on exactly the audit surface's functions and on
    no others. Any other entry fails here, which is the route around ADR-0042 §6 that
    ADR-0178 exists to close and that ADR-0186 §8's last clause bars from the other
    direction.

    ``_authorisation_line`` and ``_refuse_a_page_this_surface_cannot_state`` are the
    sixth and seventh, added by ADR-0193 §11: the first renders what authorised an
    ``ALLOW`` from the row alone, the second runs that same dispatch over a page
    before a byte of it is printed, and both therefore take the decision and belong
    on this surface. The set is **extended** rather than relaxed to a superset test,
    because a membership check would stop catching the entry this case exists for.

    ``_rests_on_the_configuration`` is the eighth, added by ADR-0247 §2 (#2256): a
    standing ``ALLOW``'s route is read off the row — ``authorised_subject`` unset and
    the binding's ``closed_loop`` — so that route (c) is rendered as its basis and the
    connection reference ADR-0148 §6 bars from every surface is rendered to nobody. It
    takes the decision for the same reason :func:`_authorisation_line` does, which is
    its one caller, and it is on this surface for the same reason.
    """
    holders = {
        name
        for name, member in vars(cli).items()
        if isfunction(member)
        and member.__module__ == cli.__name__
        and any(
            recorded in str(member.__annotations__)
            for recorded in ("PermissionDecision", "EgressBinding", "OriginUnrecordedBinding")
        )
    }
    assert holders == {
        "_authorisation_line",
        "_decisions_artifact",
        "_recorded_origin_line",
        "_render_decision",
        "_refuse_a_page_this_surface_cannot_state",
        "_render_decisions",
        "_render_recorded_egress",
        "_rests_on_the_configuration",
    }


def test_error_render_shows_no_traceback(output: StringIO) -> None:
    """An error is a one-line message, not a stack trace."""
    cli._render_error(PlanningError("a turn needs a non-empty utterance"))
    rendered = output.getvalue()
    assert "non-empty utterance" in rendered
    assert "Traceback" not in rendered


# --- startup and input error boundaries (ADR-0042 §7) -------------------


async def test_a_config_failure_at_startup_is_rendered_and_exits_nonzero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A settings failure at startup is rendered, not dumped as a traceback (§7)."""

    def _bad_settings() -> object:
        msg = "invalid configuration: unknown timezone"
        raise ConfigurationError(msg)

    monkeypatch.setattr(cli, "load_settings", _bad_settings)
    code = await cli._list_conversations(limit=10, offset=0)
    assert code == 1
    assert "Error" in output.getvalue()
    assert "unknown timezone" in output.getvalue()


async def test_a_closed_door_is_reported_as_an_instruction_and_exits_nonzero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No hub, no fallback: an instruction and a non-zero exit (ADR-0084 §9).

    The whole of ruling 3 and ruling 5 at the adapter, and the assertions are
    written so that a fallback could not pass them: the message must name the
    socket it tried *and* how to start the hub, and the exit code must be non-zero.
    An in-process fallback would render a listing and exit ``0``.

    It is driven through the real client against a directory with no socket in it,
    rather than through a stubbed one, so what is exercised is the actual
    ``connect`` failure rather than a test double's idea of it.
    """
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    code = await cli._list_conversations(limit=10, offset=0)
    assert code == 1
    rendered = output.getvalue()
    assert "hub.sock" in rendered
    assert "ai-assistant-hub" in rendered
    assert "not reachable" in rendered


async def test_a_data_directory_too_long_for_the_socket_is_reported_as_itself(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The client gives the hub's own diagnosis rather than a bare errno (#554).

    One setting locates both the data and the door (ADR-0084 §9), so both halves
    reach the same verdict about it. Without this the user reads
    ``AF_UNIX path too long`` out of ``connect`` and has to work out for themselves
    that ``ASSISTANT_DATA_DIR`` is what to move; with it they read the limit, the
    encoded length, and what to do.
    """
    deep = tmp_path
    while len(str(deep).encode()) < sun_path_limit():
        deep = deep / "aaaaaaaaaa"
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(data_dir=deep))
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    code = await cli._list_conversations(limit=10, offset=0)
    assert code == 1
    rendered = output.getvalue()
    assert "sun_path" in rendered
    assert "ASSISTANT_DATA_DIR" in rendered


# --- a failed credential read is not a refused credential (#1940) ------------


class _FailingStdin:
    """A standard input whose descriptor fails at the read (#1940).

    The failure ``_credential_from_stdin``'s bounded ``readline`` is exposed to and
    that no refusal describes: a stream that errors mid-read, a pipe whose peer died
    in a way the platform reports as ``EIO``, a closed stream. It answers with a
    real ``OSError`` rather than a stand-in exception, because the whole question
    the three cases below settle is which ``except`` arm that class lands in.

    ``isatty`` is answered rather than inherited so the same stub serves the hidden
    prompt, whose guard is a question about the terminal and not about the read.
    """

    def __init__(self, *, tty: bool = False) -> None:
        """Create the stub, optionally claiming to be a terminal."""
        self._tty = tty
        self.buffer = self

    def isatty(self) -> bool:
        """Whether ``_prompt_for_credential`` sees a terminal here."""
        return self._tty

    def readline(self, limit: int | None = None) -> bytes:
        """Fail the way a descriptor does, having read nothing."""
        raise OSError(errno.EIO, "Input/output error")


def test_a_credential_read_that_fails_is_not_translated_into_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reader lets an ``OSError`` through as itself, and that is the design.

    Translating it into the ``ValueError`` the three surfaces already catch would
    make this one change instead of three — and would route ``connect`` and
    ``reconnect`` through ``_render_unusable_credential``, whose sentence asserts
    that a credential cannot be used. Nothing was read, so there is no credential to
    say that about, and the renderer's own safety argument is ADR-0125 §6's
    guarantee about the refusal *of a value*, which has nothing to reach here.

    So the class the boundaries branch on is the class the platform raised, and this
    pins the reader against a well-meant later translation.
    """
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    with pytest.raises(OSError, match="Input/output error"):
        cli._credential_from_stdin()


async def test_connect_renders_a_failed_credential_read_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``connect``'s read failure is a rendered line and a non-zero exit (#1940).

    ADR-0042 §7 makes surfacing errors and setting a meaningful exit code the
    adapter's own responsibility, and before this the ``OSError`` walked out of
    ``_drive_connect`` past a boundary that caught only ``ValueError``.

    The two negative assertions are the finding's actual content. Nothing may be
    sent, because the credential never arrived; and the rendering may not be
    ``_render_unusable_credential``'s, because "that credential cannot be used"
    would attribute a descriptor fault to a value nobody read.
    """
    engine = FakeAssistantEngine()
    _wire_recording_opens(monkeypatch, engine)
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    code = await cli._connect_account("me@example.com", credential_stdin=True)

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "Input/output error" in rendered
    assert "cannot be used" not in rendered
    assert engine.calls == []


async def test_reconnect_renders_a_failed_credential_read_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reconnect``'s read failure lands the same way, on the same reasoning.

    It is the third surface of #1940's finding and it is asserted separately rather
    than parametrised with ``connect``, because the two boundaries are separate
    code: ADR-0151 §1 refused to fold the operations into one method, and the
    duplication of the arm is the thing a test has to see.
    """
    engine = FakeAssistantEngine()
    _wire_recording_opens(monkeypatch, engine)
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    code = await cli._reprovision_account(
        "conn-1", identity="me@example.com", credential_stdin=True
    )

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "Input/output error" in rendered
    assert "cannot be used" not in rendered
    assert engine.calls == []


async def test_device_enrol_renders_a_failed_credential_read_rather_than_a_traceback(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enrolment boundary catches it too, and it already had the vocabulary.

    ``device enrol`` renders every failure it catches through ``_render_error``, so
    the one message the three surfaces settle on is the one this command was already
    giving for a refused value — no fourth sentence was invented for the case.

    Nothing is wired: the read is the first statement inside the boundary, so a
    failing one is answered before any setting is loaded or any keyring is opened,
    and asserting that requires providing neither.
    """
    monkeypatch.setattr(sys, "stdin", _FailingStdin())

    code = await cli._store_device_enrolment("hub-abcdefgh", cli._credential_from_stdin)

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "Input/output error" in rendered
    assert "Enrolled" not in rendered


async def test_a_terminal_that_fails_at_the_hidden_prompt_takes_the_same_arm(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other reader's ``OSError`` is the same event and takes the same arm.

    ``_prompt_for_credential`` reaches ``getpass``, which opens the controlling
    terminal and reads from it; neither is guaranteed to succeed, and a container or
    a revoked ``/dev/tty`` produces an ``OSError`` from a reader that never touches
    ``sys.stdin.buffer``. The arm is on the exception's class rather than on which
    reader was chosen, which is what makes one test of that claim enough.

    The terminal is stubbed at ``typer.prompt`` — the read itself — rather than at
    ``_prompt_for_credential``, so the reader's own non-terminal guard still runs and
    the case remains the one where a terminal exists and fails.
    """
    engine = FakeAssistantEngine()
    _wire_recording_opens(monkeypatch, engine)
    monkeypatch.setattr(sys, "stdin", _FailingStdin(tty=True))

    def _no_terminal(*_args: object, **_kwargs: object) -> str:
        raise OSError(errno.ENXIO, "No such device or address")

    monkeypatch.setattr(typer, "prompt", _no_terminal)

    code = await cli._connect_account("me@example.com", credential_stdin=False)

    assert code == 1
    rendered = _flat(output.getvalue())
    assert "Error:" in rendered
    assert "No such device or address" in rendered
    assert "cannot be used" not in rendered
    assert engine.calls == []


# --- the startup seam every command is wired through (ADR-0042 §6) --------


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point a command's startup at ``engine``.

    The seam is :func:`~ai_assistant.interfaces.cli._open_engine` rather than
    ``build_engine``, because after ADR-0084 §6 the CLI has no composition root to
    reach: it obtains a *client*, and the one function that obtains it is the one
    place a test substitutes.
    """

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)
    monkeypatch.setattr(cli, "_utcnow", lambda: AT)


def _wire_recording_opens(monkeypatch: pytest.MonkeyPatch, engine: object) -> list[None]:
    """Wire ``engine`` as :func:`_wire` does, and record every open of a client.

    The seam every parse-boundary refusal in this module is actually about.
    ``_wire``'s stub answers with the engine and keeps no record, so a test using
    it can assert the *exit code* of a refusal but not the claim its own name or
    docstring makes — that the refusal landed **before any client was built**
    (ADR-0085 §3c's "before any I/O", #728). A regression that opened the hub,
    probed it, and only then converted a malformed argument into an exit-2 usage
    error would keep every assertion those cases held.

    The observation itself is :func:`cli_open_recorder.wire_recording_opens`, which
    three sibling modules make the same claim through (#1973); this binds it to
    *this* module's wiring. The cases making the claim here are spread the length of
    the module — ``--timeout``, ``--limit``, ``--offset`` and ``--band``, a grant's
    ``source``, a repeated ``--scope``, a quiet window, and the id arguments
    themselves.

    Args:
        monkeypatch: The patcher whose lifetime the substitution follows.
        engine: The engine a client, if one were opened, would be.

    Returns:
        One entry per :func:`~ai_assistant.interfaces.cli._open_engine` awaited.
    """
    return wire_recording_opens(_wire, monkeypatch, engine)


def test_the_open_recorder_sees_the_client_an_accepted_invocation_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recorder is non-vacuous, which is what makes every ``opened == []`` evidence.

    An absence only says something if the observer would have seen the thing. A
    helper that patched the wrong name, or whose stub a later ``_wire`` overwrote,
    would make every refusal case below pass for a reason unrelated to when the
    refusal happened — and go on passing through exactly the regression #728 is
    about. So one *accepted* invocation is pinned here: it opens a client, and the
    list has to show it.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["conversations"])

    assert result.exit_code == 0
    assert opened == [None]


# --- beliefs / forget: the inspection surface (ADR-0073 §4, §5, §7) -----


#: The instant a source says a fact was current — **its** clock, not ours, and
#: deliberately nowhere near ``AT``. ADR-0073 §4's floor is that a surface must not
#: offer our clock as the source's (ADR-0092 §3: a ``reported_at`` earlier than ours is
#: the normal case, not an anomaly).
REPORTED_AT: Final = datetime(2026, 3, 2, 8, 30, tzinfo=UTC)

#: What reported an attested memory, as its support holds it (ADR-0328 §4:13).
ATTESTED_BY: Final = Attestation(reported_by="work-calendar", reported_at=REPORTED_AT)

#: When a held memory's support happened, as this module renders it.
LEARNED: Final = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)

#: What a resolved support part reads as, in the single view.
_SUPPORT_TEXT: Final = "The user said: the office is in Boston."


def _held_memory(  # noqa: PLR0913 — one knob per fact a memory's projection shows; that is the point
    band: BeliefBand = BeliefBand.ASSERTED,
    *,
    belief_id: str = "rec-1",
    content: str = "the office is in Boston",
    valid_until: datetime | None = None,
    outside: bool = False,
    attestation: Attestation | None = None,
    when: datetime | None = LEARNED,
) -> Memory:
    """One memory standing in ``band``, its one support dated ``when`` (ADR-0328 §6:4)."""
    return memory_in_band(
        belief_id,
        content,
        band,
        outside=outside,
        attestation=attestation,
        when=when,
        validity=Validity(valid_until=valid_until),
    )


def _view(held: Memory, *, gone: bool = False) -> Belief:
    """``held`` on the single view, its supports resolved (or gone), as the engine projects."""
    contents: dict[SupportPart, str | None] = {
        support.points_at: None if gone else _SUPPORT_TEXT for support in held.supports
    }
    return belief_view(held, now=AT, contents=contents)


def _belief(band: BeliefBand = BeliefBand.ASSERTED, **knobs: Any) -> Belief:
    """One projected memory, as the façade hands it to the adapter (ADR-0328 §15:2)."""
    return _view(_held_memory(band, **knobs))


def _summary(band: BeliefBand = BeliefBand.ASSERTED, **knobs: Any) -> BeliefSummary:
    """The same memory on the listing (ADR-0328 §15:1): every field but the supports."""
    return BeliefSummary.model_validate(_belief(band, **knobs).model_dump(exclude={"supports"}))


def _flat(rendered: str) -> str:
    """Collapse Rich's line wrapping, so an assertion is about words and not width.

    The continuation marker goes with it (#2072). It is written *by* the wrapping —
    :func:`cli._print` marks every display line a line runs onto — so a helper that
    removed the break and kept the marker would leave a ``↳`` between two words of one
    sentence, which is the failure this helper exists to prevent. It is not the ``│``
    :func:`_help_text` drops: that one is Typer's own panel border.
    """
    return " ".join(rendered.replace("↳", " ").split())


class _RecordingBeliefEngine:
    """A stand-in façade recording the inspection calls the commands make."""

    def __init__(self, page: tuple[Belief, ...] = (), *, one: Belief | None = None) -> None:
        self._page = page
        self._one = one
        self.listed: list[tuple[object, object, int, int]] = []
        self.forgotten: list[str] = []

    async def beliefs(
        self,
        *,
        bands: object = None,
        kinds: object = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Belief, ...]:
        self.listed.append((bands, kinds, limit, offset))
        return self._page

    async def belief(self, record_id: str) -> Belief | None:
        return self._one

    async def forget(self, record_id: str) -> bool:
        self.forgotten.append(record_id)
        return True

    async def start(self) -> None:
        """The start-up sweeps, which this stand-in has no stores to sweep."""

    async def aclose(self) -> None:
        """Nothing to release: this stand-in owns no resource."""


def test_render_belief_conveys_everything_the_surface_owes(output: StringIO) -> None:
    """ADR-0328 §15:4's minimum, and ADR-0073 §4's band and id beside it.

    The standing in plain words, its age (learned and as of), why it is held, and the
    id ``forget`` takes. **No confidence**: a memory carries none (§15:3).
    """
    cli._render_belief(_belief())
    rendered = _flat(output.getvalue())
    assert "asserted" in rendered  # the band, stated and not implied by position
    assert "you said it" in rendered  # the standing, in plain words
    assert "the office is in Boston" in rendered
    assert "you told me" in rendered  # why it is held
    assert "Learned: 2026-07-20 18:00 UTC" in rendered
    assert "As of: 2026-07-20 18:00 UTC" in rendered
    assert "rec-1" in rendered
    assert "confidence" not in rendered


def test_an_age_nothing_dates_is_said_as_unknown(output: StringIO) -> None:
    """ADR-0328 §7:3: unknown is neither fresh nor stale, and is said as such."""
    cli._render_belief(_belief(when=None))
    rendered = _flat(output.getvalue())
    assert "Learned: unknown" in rendered
    assert "As of: unknown" in rendered


def test_a_memory_held_by_someone_else_says_whose_it_is(output: StringIO) -> None:
    """ADR-0345 §12:1: its holders, wherever they are not the owner alone."""
    cli._render_belief(_belief())
    assert "Held by" not in output.getvalue()

    tom = SupportHolder.person("tom")
    cli._render_belief(_belief().model_copy(update={"holders": (tom,)}))
    assert "Held by: another person (tom)" in _flat(output.getvalue())


def test_an_assistant_statement_is_said_to_be_what_i_said(output: StringIO) -> None:
    """ADR-0345 §12:4: never as the user's word, citing the message, and who kept it."""
    said = _belief().model_copy(
        update={
            "marks": (MemoryMark.ASSISTANT_STATEMENT,),
            "holders": (SupportHolder.person(OWNER_PERSON_ID),),
            "statements": (
                StatementCitation(
                    episode="activation:said",
                    round="round-1",
                    when=datetime(2026, 7, 20, 18, tzinfo=UTC),
                ),
            ),
        }
    )

    cli._render_belief(said)

    rendered = _flat(output.getvalue())
    assert "what I said" in rendered
    assert "you said it" not in rendered
    assert "I said this, in my message of 2026-07-20 18:00 UTC" in rendered
    assert "you kept it" in rendered


def test_render_belief_shows_a_window_end_only_when_one_is_set(output: StringIO) -> None:
    """Every listed memory is live, so an open window carries nothing to render."""
    cli._render_belief(_belief())
    assert "Believed until" not in output.getvalue()

    cli._render_belief(_belief(valid_until=datetime(2026, 8, 1, tzinfo=UTC)))
    assert "Believed until: 2026-08-01 00:00 UTC" in output.getvalue()


def test_render_belief_neutralises_engine_supplied_text(output: StringIO) -> None:
    """A wording carrying terminal escapes or markup prints inert (ADR-0042 §4)."""
    cli._render_belief(_belief(content="wipe\x1b[2J and [red]shout[/red]"))
    rendered = output.getvalue()
    assert "\x1b[2J" not in rendered
    assert "[red]shout[/red]" in rendered


def test_an_inference_says_its_evidence_summary(output: StringIO) -> None:
    """ADR-0328 §15:4: the evidence summary, where the standing is inference."""
    held = memory(
        "rec-1",
        "the user runs on Tuesdays",
        remembered_support("activation:a", when=LEARNED),
        remembered_support("activation:b", effect="effect-2", when=LEARNED),
        said_support("activation:c", direction=SupportDirection.AGAINST),
    )
    cli._render_belief(_view(held))
    rendered = _flat(output.getvalue())
    assert "my inference" in rendered
    assert "2 piece(s) of support across 3 exchange(s), 1 against it" in rendered


def test_no_evidence_summary_is_owed_where_the_standing_is_not_inference(
    output: StringIO,
) -> None:
    """§15:4 asks for it where the standing is inference, and the row stays short otherwise."""
    cli._render_belief_summary(_summary())
    assert "piece(s) of support" not in _flat(output.getvalue())


def test_a_reading_certainty_short_of_sure_is_said(output: StringIO) -> None:
    """§15:4: its reading certainty where that is not ``sure``; silent where it is."""
    likely = memory(
        "rec-1",
        "the standup is at 09:30",
        sourced_support(ATTESTED_BY, how_sure=ReadingCertainty.LIKELY),
    )
    cli._render_belief(_view(likely))
    assert "How sure the reading was: likely" in _flat(output.getvalue())

    output.truncate(0)
    output.seek(0)
    sure = memory("rec-1", "the standup is at 09:30", sourced_support(ATTESTED_BY))
    cli._render_belief(_view(sure))
    assert "How sure the reading was" not in _flat(output.getvalue())


def test_a_reading_nobody_judged_is_said_as_not_judged(output: StringIO) -> None:
    """Not judged is not ``sure`` (ADR-0328 §7:5), so §15:4 shows it."""
    cli._render_belief_summary(_summary())
    assert "How sure the reading was: not judged" in _flat(output.getvalue())


def test_every_let_down_is_shown(output: StringIO) -> None:
    """§15:4: every let-down — counted, beside how often it was relied on."""
    summary = _summary(BeliefBand.DERIVED).model_copy(
        update={"track_record": TrackRecordSummary(relied_on=3, held_up=1, let_down=2)}
    )
    cli._render_belief_summary(summary)
    assert "Let you down 2 time(s) of the 3 I relied on it." in _flat(output.getvalue())


def test_a_legacy_memory_carries_the_legacy_mark(output: StringIO) -> None:
    """§15:4 and §16:10: a memory kept before supports is marked legacy."""
    held = memory(
        "rec-1",
        "the office is in Boston",
        legacy_support({"id": "rec-1", "kind": "semantic", "content": "the office is in Boston"}),
    )
    cli._render_belief(_view(held))
    rendered = _flat(output.getvalue())
    assert "Legacy: kept before memories had supports" in rendered
    assert "my inference" in rendered  # a legacy memory stands at inference (§16:10)
    assert "a record kept before memories had supports" in rendered  # its one support
    assert "I worked it out from 1 piece(s) of support." in rendered  # no exchange to count
    assert "exchange(s)" not in rendered


def test_a_memory_whose_supports_are_all_gone_is_held_and_says_so(output: StringIO) -> None:
    """ADR-0328 §15:7: held, marked, answerable — and every gone part is a tombstone."""
    cli._render_belief(_view(_held_memory(BeliefBand.DERIVED), gone=True))
    rendered = _flat(output.getvalue())
    assert "Everything it rested on is gone. I still hold it" in rendered
    assert "what it pointed at is gone" in rendered
    assert _SUPPORT_TEXT not in rendered


def test_the_single_view_shows_each_support_resolved(output: StringIO) -> None:
    """§15:2: each support's origin, ``when`` and part resolved to readable content."""
    cli._render_belief(_belief())
    rendered = _flat(output.getvalue())
    assert "Rests on:" in rendered
    assert "your message · 2026-07-20 18:00 UTC" in rendered
    assert _SUPPORT_TEXT in rendered


def test_the_listing_shows_no_support(output: StringIO) -> None:
    """ADR-0085 §4a's split: a listing row carries no support, so prints none."""
    cli._render_belief_summary(_summary())
    rendered = _flat(output.getvalue())
    assert "Rests on:" not in rendered
    assert _SUPPORT_TEXT not in rendered


def test_a_confirmed_memory_says_the_user_confirmed_the_wording(output: StringIO) -> None:
    """The highest standing, in its own words (ADR-0328 §6:1)."""
    cli._render_belief(_view(memory("rec-1", "Sam prefers email", confirmed_support())))
    rendered = _flat(output.getvalue())
    assert "you confirmed this wording" in rendered
    assert "your yes to my question" in rendered


def test_a_sourced_memory_names_the_source_on_its_support(output: StringIO) -> None:
    """ADR-0189 §4 on a memory: the source is named where its source details are (§15:2).

    At source granularity and no finer, and apposed to the origin's words so it cannot
    be read as a person (ADR-0098 §8, ADR-0093 §7).
    """
    cli._render_belief(_belief(BeliefBand.ATTESTED, attestation=ATTESTED_BY))
    rendered = _flat(output.getvalue())
    assert "from a source" in rendered
    assert "neither your word nor my inference" in rendered
    assert "outside content I read · work-calendar" in rendered


def test_each_sources_report_time_is_shown_as_its_own_clock(output: StringIO) -> None:
    """ADR-0189 §4 on every support: the source's reporting instant, said as its clock.

    Two sources reporting at instants distinct from when each part was read: both report
    times are shown, each beside its source, and neither is the encounter time.
    """
    early = Attestation(reported_by="work-calendar", reported_at=REPORTED_AT)
    late = Attestation(reported_by="home-calendar", reported_at=REPORTED_AT + timedelta(days=2))
    held = memory(
        "rec-1",
        "the office is in Boston",
        sourced_support(early, episode="activation:a", when=LEARNED),
        sourced_support(late, episode="activation:b", when=LEARNED + timedelta(days=5)),
    )
    cli._render_belief(_view(held))
    rendered = _flat(output.getvalue())
    assert f"work-calendar, which said so as of {cli._when(REPORTED_AT)} on its own clock" in (
        rendered
    )
    assert (
        f"home-calendar, which said so as of {cli._when(REPORTED_AT + timedelta(days=2))} "
        "on its own clock"
    ) in rendered


def test_a_sourced_memory_on_the_listing_names_its_source_and_its_clock(
    output: StringIO,
) -> None:
    """ADR-0189 §1, §4 on the listing: which source its standing rests on, and when."""
    cli._render_belief_summary(_summary(BeliefBand.ATTESTED, attestation=ATTESTED_BY))
    rendered = _flat(output.getvalue())
    assert (
        f"Reported by: work-calendar, as of {cli._when(REPORTED_AT)} on its own clock" in rendered
    )


def test_an_inference_says_when_its_latest_piece_is_from(output: StringIO) -> None:
    """§7:2's latest `when` is said, so a newer piece against it is not lost (§15:4)."""
    later = LEARNED + timedelta(days=30)
    held = memory(
        "rec-1",
        "the user runs on Tuesdays",
        remembered_support(when=LEARNED, added_at=LEARNED),
        said_support("activation:no", direction=SupportDirection.AGAINST, when=later),
    )
    cli._render_belief(_view(held))
    rendered = _flat(output.getvalue())
    assert f"The latest piece is from {cli._when(later)}." in rendered
    assert f"As of: {cli._when(LEARNED)}" in rendered


def test_an_attested_episode_names_its_source_and_its_clock(output: StringIO) -> None:
    """ADR-0189 §4 on an episode's projection: what reported it, and when, on its clock."""
    episode = EpisodicMemory(
        id="activation:a",
        content="a source's report",
        occurred_at=LEARNED,
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=LEARNED,
            attestation=ATTESTED_BY,
        ),
    )
    cli._render_belief(episode_view(episode))
    rendered = _flat(output.getvalue())
    assert (
        f"Reported by: work-calendar, as of {cli._when(REPORTED_AT)} on its own clock" in rendered
    )


def test_a_memory_resting_on_my_own_message_is_not_attributed_to_a_connected_source(
    output: StringIO,
) -> None:
    """ADR-0328 §4: an assistant message ranks at source, and no integration reported it."""
    held = memory("rec-1", "the office is in Boston", message_support())
    cli._render_belief(_view(held))
    rendered = _flat(output.getvalue())
    assert "from a source" in rendered
    assert "connected source" not in rendered
    assert "my own message" in rendered


def test_an_inference_resting_on_outside_content_says_so_without_reattributing_the_words(
    output: StringIO,
) -> None:
    """ADR-0189 §4's third clause, read through ADR-0328 §12 on rests-on-outside-content.

    It names the warrant and affirms the words are ours in one breath (ADR-0098 §1).
    """
    cli._render_belief_summary(_summary(BeliefBand.DERIVED, outside=True))
    rendered = _flat(output.getvalue())
    assert "came from outside rather than from you" in rendered
    assert "the wording is still my own sentence" in rendered


def test_nothing_is_said_about_the_outside_where_nothing_outside_is_recorded(
    output: StringIO,
) -> None:
    """Silent on ``False`` rather than negative (ADR-0328 §7:7)."""
    cli._render_belief_summary(_summary(BeliefBand.DERIVED))
    rendered = _flat(output.getvalue())
    assert "outside" not in rendered


def test_a_records_content_with_a_line_break_keeps_it(output: StringIO) -> None:
    """#1890: a break inside a wording is a break, not ``�``."""
    cli._render_belief_summary(_summary(content="first line\nsecond line"))
    rendered = output.getvalue()

    assert "�" not in rendered
    assert "  │ first line\n  │ second line\n" in rendered


def test_a_forged_field_line_in_a_records_content_is_marked_as_content(
    output: StringIO,
) -> None:
    """ADR-0042 §4's threat, arriving without a control character.

    :data:`~ai_assistant.core.types.EncodableText` asks only that a value be writable,
    so a wording may carry a newline — and printed as plain indented lines,
    ``fact\nWhy: …\nid: …`` is three fields of this row in the reader's own vocabulary.
    The gutter closes it: every line of a multi-line content is behind a marker no line
    this adapter writes ever carries. Asserted in both directions.
    """
    cli._render_belief_summary(
        _summary(content="the office is in Boston\nWhy: you told me this\nid: rec-9")
    )
    rendered = output.getvalue()

    assert "\n  Why: you told me this" not in rendered
    assert "\n  id: rec-9" not in rendered
    assert "  │ Why: you told me this\n" in rendered
    assert "  │ id: rec-9\n" in rendered
    assert rendered.count("  id: rec-1\n") == 1, "and the row's own id is still its own"


def test_the_gutter_reaches_the_lines_the_console_wraps_for_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker's promise is about display lines, not about logical ones.

    Rich does not repeat a literal prefix on the continuations it wraps, so a crafted
    ``… Why: forged`` becomes a second display line the marker never reached unless the
    wrapping is taken here. Driven at a **40-column** console.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=40))

    cli._render_belief_summary(
        _summary(content="the office is in Boston\n" + "x " * 18 + "Why: forged")
    )
    lines = buffer.getvalue().splitlines()

    forged = [one for one in lines if "Why: forged" in one]
    assert forged, "the crafted text reached the screen at all"
    assert all(one.startswith("  │ ") for one in forged), (
        "and every display line it landed on carries the gutter"
    )
    assert len([one for one in lines if one.startswith("  │ ")]) > 2, (
        "the content really did wrap, so the case is exercising what it claims to"
    )


def test_a_single_line_content_is_printed_exactly_as_it_always_was(output: StringIO) -> None:
    """The marker is bought only by the value that creates the risk."""
    cli._render_belief_summary(_summary())
    rendered = output.getvalue()

    assert "\n  the office is in Boston\n" in rendered
    assert "│" not in rendered


def test_a_carriage_return_in_a_records_content_is_a_break_and_not_a_scribble(
    output: StringIO,
) -> None:
    """A carriage return overwrites what came before, so it becomes the break it meant."""
    cli._render_belief_summary(_summary(content="first\r\nsecond\rthird"))
    rendered = output.getvalue()

    assert "\r" not in rendered
    assert "�" not in rendered
    assert "  │ first\n  │ second\n  │ third\n" in rendered


def test_markup_split_across_a_break_in_a_records_content_is_still_escaped(
    output: StringIO,
) -> None:
    """Rich's tag pattern matches across a newline, so the escape is over the whole value."""
    cli._render_belief_summary(_summary(content="[red\nbold] hello"))
    rendered = output.getvalue()

    assert "[red" in rendered
    assert "bold] hello" in rendered


def test_render_beliefs_reports_an_empty_page_plainly(output: StringIO) -> None:
    """Nothing matching is said, not shown as an empty success."""
    cli._render_beliefs((), limit=50, offset=0)
    assert "No live belief matches" in output.getvalue()


def test_render_beliefs_offers_the_next_page_without_claiming_a_total(
    output: StringIO,
) -> None:
    """A full page names the offset that would fetch the next; no count is shown (§7)."""
    cli._render_beliefs((_summary(belief_id="a"), _summary(belief_id="b")), limit=2, offset=4)
    rendered = _flat(output.getvalue())
    assert "--offset 6" in rendered
    assert "there may be more" in rendered


def test_render_beliefs_does_not_offer_a_next_page_for_a_short_one(output: StringIO) -> None:
    """A page shorter than the limit is the end of the enumeration."""
    cli._render_beliefs((_summary(),), limit=50, offset=0)
    assert "--offset" not in output.getvalue()


@pytest.mark.parametrize(
    ("band", "expected"),
    [
        (BeliefBand.ASSERTED, "permanent"),
        (BeliefBand.DERIVED, "may reach it again"),
        (BeliefBand.ATTESTED, "may come across it again"),
    ],
)
def test_forget_prompt_warns_by_band_because_the_consequence_differs(
    band: BeliefBand, expected: str, output: StringIO
) -> None:
    """A deletion is represented as neither more final than it is nor less (§5)."""
    cli._render_forget_prompt(_belief(band, attestation=ATTESTED_BY))
    assert expected in _flat(output.getvalue())


def test_forget_prompt_shows_the_belief_and_scopes_the_consent(output: StringIO) -> None:
    """It renders what is about to go, and says what agreeing actually covers (§5, §6)."""
    cli._render_forget_prompt(_belief())
    rendered = _flat(output.getvalue())
    assert "the office is in Boston" in rendered  # shown before it can be destroyed
    assert "rec-1" in rendered
    assert _SUPPORT_TEXT in rendered  # and the warrant being judged with it
    assert "not even in an export" in rendered  # destroyed, not retired (§6)
    assert "correct me in assistant chat" in rendered  # the route that keeps it instead


async def _holding(content: str) -> FakeMemoryStore:
    """A store holding one memory the user said, and one episode beside it.

    Written into the store, because no call on the engine writes a memory since
    ADR-0293 §11 retired ``learn``. The episode is there so the listing's exclusion of
    episodes (ADR-0328 §11:2, #3143) is exercised by every case that lists.
    """
    store = FakeMemoryStore(now=lambda: AT)
    episode = EpisodicMemory(
        id="activation:held",
        content="The user asked: where is the office?",
        occurred_at=LEARNED,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )
    await store.write_atomic(
        [
            MemoryWrite(record=episode, mode=MemoryWriteMode.INSERT_IF_ABSENT),
            MemoryWrite(
                record=memory("rec-held", content, said_support(when=LEARNED, added_at=AT)),
                mode=MemoryWriteMode.INSERT_IF_ABSENT,
            ),
        ]
    )
    return store


async def test_drive_beliefs_lists_what_the_engine_holds(output: StringIO) -> None:
    """Against a real engine over fakes, a stored memory is listed with its standing."""
    engine = _engine(memory=await _holding("the office is in Boston"))
    code = await cli._drive_beliefs(engine, bands=None, kinds=None, limit=50, offset=0)
    assert code == 0
    rendered = _flat(output.getvalue())
    assert "the office is in Boston" in rendered
    assert "asserted · you said it" in rendered  # what the user said lands in their band
    assert "1 belief(s)" in rendered
    assert "where is the office?" not in rendered  # not listed by default (§11:2)
    await engine.aclose()


async def test_drive_beliefs_lists_episodes_where_the_episodic_kind_is_named(
    output: StringIO,
) -> None:
    """ADR-0074 §6: ``--kind episodic`` still lists episodes, in their own words."""
    engine = _engine(memory=await _holding("the office is in Boston"))
    code = await cli._drive_beliefs(
        engine, bands=None, kinds=[MemoryKind.EPISODIC], limit=50, offset=0
    )
    assert code == 0
    rendered = _flat(output.getvalue())
    assert "where is the office?" in rendered
    assert "a captured exchange" in rendered
    assert "this records an exchange that happened" in rendered
    assert "Happened:" in rendered
    assert "activation:held" in rendered  # the id forget takes
    assert "the office is in Boston" not in rendered
    await engine.aclose()


async def test_forget_on_an_episodes_id_shows_it_then_destroys_it(output: StringIO) -> None:
    """ADR-0074 §6: ``forget <id>`` destroys an episode exactly as it destroys a belief.

    The ceremony's read (ADR-0073 §5) resolves the episode, shows it, and the yes
    destroys it.
    """
    store = await _holding("the office is in Boston")
    engine = _engine(memory=store)
    code = await cli._drive_forget(engine, "activation:held", confirm=lambda _b: True)
    assert code == 0
    rendered = _flat(output.getvalue())
    assert "About to forget" in rendered
    assert "where is the office?" in rendered
    assert "Forgotten" in rendered
    assert await store.get("activation:held") is None
    await engine.aclose()


async def test_drive_beliefs_surfaces_a_read_failure_with_a_nonzero_exit(
    output: StringIO,
) -> None:
    """A MemoryStoreError from the read is rendered, not dumped, exit 1 (ADR-0042 §7)."""

    class _FailingEngine:
        async def beliefs(self, **_kwargs: object) -> tuple[Belief, ...]:
            msg = "the memory store would not read"
            raise MemoryStoreError(msg)

    code = await cli._drive_beliefs(
        _FailingEngine(),  # type: ignore[arg-type]  # the adapter needs only this call
        bands=None,
        kinds=None,
        limit=50,
        offset=0,
    )
    assert code == 1
    assert "would not read" in output.getvalue()


async def test_drive_forget_shows_the_belief_before_it_asks(output: StringIO) -> None:
    """Show, then confirm: the approver never runs before the render (§5)."""
    engine = _RecordingBeliefEngine(one=_belief())
    shown_before_asking = False

    def approve(_belief_shown: Belief) -> bool:
        nonlocal shown_before_asking
        shown_before_asking = "the office is in Boston" in output.getvalue()
        return True

    code = await cli._drive_forget(engine, "rec-1", confirm=approve)  # type: ignore[arg-type]
    assert code == 0
    assert shown_before_asking
    assert engine.forgotten == ["rec-1"]
    assert "Forgotten" in output.getvalue()


async def test_drive_forget_destroys_nothing_when_the_answer_is_no(output: StringIO) -> None:
    """A refusal is a valid outcome: nothing is deleted and the exit code is 0."""
    engine = _RecordingBeliefEngine(one=_belief())
    code = await cli._drive_forget(engine, "rec-1", confirm=lambda _b: False)  # type: ignore[arg-type]
    assert code == 0
    assert engine.forgotten == []
    assert "Left alone" in output.getvalue()


async def test_drive_forget_declines_an_id_naming_no_live_belief(output: StringIO) -> None:
    """A retired or unknown id is declined rather than deleted blind, exit 1 (§5)."""
    engine = _RecordingBeliefEngine(one=None)
    asked = False

    def approve(_belief_shown: Belief) -> bool:
        nonlocal asked
        asked = True
        return True

    code = await cli._drive_forget(engine, "gone", confirm=approve)  # type: ignore[arg-type]
    assert code == 1
    assert asked is False  # nothing was shown, so nothing could be consented to
    assert engine.forgotten == []
    assert "No live belief has the id" in _flat(output.getvalue())


async def test_drive_forget_reports_a_belief_that_vanished_before_the_delete(
    output: StringIO,
) -> None:
    """``forget`` returning False is rendered and mapped to a non-zero exit (§7)."""

    class _VanishingEngine(_RecordingBeliefEngine):
        async def forget(self, record_id: str) -> bool:
            self.forgotten.append(record_id)
            return False

    engine = _VanishingEngine(one=_belief())
    code = await cli._drive_forget(engine, "rec-1", confirm=lambda _b: True)  # type: ignore[arg-type]
    assert code == 1
    assert "already gone" in output.getvalue()


async def test_drive_forget_end_to_end_against_a_real_engine(output: StringIO) -> None:
    """A memory the engine holds is shown, agreed to, and gone from the listing (§5)."""
    engine = _engine(memory=await _holding("the office is in Boston"))
    page = await engine.beliefs()
    assert len(page) == 1

    code = await cli._drive_forget(engine, page[0].id, confirm=lambda _b: True)
    assert code == 0
    rendered = _flat(output.getvalue())
    assert "Forgotten" in rendered
    assert "The user asked: where is the office?" in rendered  # its support, resolved
    assert await engine.beliefs() == ()
    await engine.aclose()


def test_beliefs_command_relays_its_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated --band reaches the façade; --limit/--offset are relayed as given."""
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app,
        ["beliefs", "--band", "derived", "--band", "attested", "--limit", "5", "--offset", "10"],
    )
    assert result.exit_code == 0
    assert engine.listed == [([BeliefBand.DERIVED, BeliefBand.ATTESTED], None, 5, 10)]


def test_beliefs_command_asks_for_every_band_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent ``--band`` means "every", and an absent ``--kind`` the engine's default.

    An empty filter selects nothing, so absence is relayed as ``None``: every band, and
    memories alone (ADR-0328 §11:2).
    """
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["beliefs"])
    assert result.exit_code == 0
    assert engine.listed == [(None, None, 50, 0)]


def test_beliefs_command_relays_kind_episodic(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0074 §6: ``--kind episodic`` still lists episodes, relayed as the kind."""
    engine = _RecordingBeliefEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["beliefs", "--kind", "episodic"])

    assert result.exit_code == 0
    assert engine.listed == [(None, [MemoryKind.EPISODIC], 50, 0)]


@pytest.mark.parametrize("bad", ["-1", str(2**63)])
def test_beliefs_command_rejects_a_page_the_store_would_refuse(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An out-of-range --limit is a usage error, not an uncaught ValueError (§2, §7).

    ``list_beliefs`` raises ``ValueError`` outside ``[0, 2**63)``, and a ``ValueError``
    is not an ``AssistantError``, so it would escape the command's error boundary as
    a traceback. The parse-time check turns it into exit code 2 before any engine is
    built — and the recorded opens are what say so (#1970).
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    for flag in ("--limit", "--offset"):
        result = CliRunner().invoke(cli.app, ["beliefs", flag, bad])
        assert result.exit_code == 2, flag
        assert result.exception is None or isinstance(result.exception, SystemExit), flag
        assert opened == [], flag


def test_beliefs_command_rejects_an_unknown_band(monkeypatch: pytest.MonkeyPatch) -> None:
    """A band outside the ratified vocabulary is a usage error, before any engine (#1970)."""
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["beliefs", "--band", "guessed"])

    assert result.exit_code == 2
    assert opened == []


def test_forget_command_renders_before_acting_under_yes(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--yes`` skips the question, not the rendering (ADR-0073 §5, ADR-0052 §4)."""
    engine = _RecordingBeliefEngine(one=_belief())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget", "rec-1", "--yes"])
    assert result.exit_code == 0
    assert engine.forgotten == ["rec-1"]
    rendered = _flat(output.getvalue())
    assert "the office is in Boston" in rendered  # the belief was still displayed
    assert "About to forget" in rendered


def test_forget_command_defaults_to_keeping_the_belief(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare Enter at the prompt does not destroy anything: the default is no."""
    engine = _RecordingBeliefEngine(one=_belief())
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget", "rec-1"], input="\n")
    assert result.exit_code == 0
    assert engine.forgotten == []
    assert "Left alone" in output.getvalue()


# --- conversations: continuity, the listing, and the deletion (ADR-0074) ---


def _conversation_engine() -> tuple[Engine, FakeConversationStore]:
    """A real ``Engine`` over canonical fakes, plus the conversation index behind it.

    The store is handed back so a case can assert what capture actually recorded,
    rather than inferring it from what the terminal printed.
    """
    plans = FakePlanStore(now=lambda: AT)
    trail = FakeAuditTrail()
    memory = FakeMemoryStore(now=lambda: AT)
    conversations = FakeConversationStore(now=lambda: AT)
    engine = Engine(
        chat_reader=False,
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        plans=plans,
        trail=trail,
        spend=trail,
        # ADR-0186 §10's read trail, on the sibling builder's terms above.
        reads=FakeSourceReadTrail(),
        memory=memory,
        # The narrow deletion seam and its horizon (ADR-0119 §7, §10). Required on
        # the façade, and nothing in this module sweeps: an adapter test is about
        # what the CLI renders, not about the maintenance operation.
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=timedelta(days=365),
        conversations=ConversationLifecycle(
            conversations=conversations,
            memory=memory,
            retention=timedelta(days=30),
            now=lambda: AT,
        ),
    )
    return engine, conversations


# --- the composed answer, beside the account and never in place of it --------
# ADR-0170 §6's rendering floor and §8's neutralisation, plus §10's
# contradictory-provider test, which needs both the outcome and the rendered
# account and so lives here rather than in ``tests/orchestration``.


def test_a_value_sharing_a_line_with_the_adapters_own_text_still_loses_its_newline() -> None:
    """The default stays as it was, because eating the break is what it is for (#1336).

    Every surface but the reply interpolates a value into a line this adapter wrote,
    where a newline lets the value forge a second line indistinguishable from the
    CLI's own — ``_safe``'s reason for replacing it, and untouched by the reply's
    carve-out. Pinned against ``_safe`` directly rather than one calling surface,
    since it is the shared default that the carve-out could regress.
    """
    forged = "harmless\n  [dim]Why:[/] fabricated"

    assert cli._safe(forged) == "harmless�  \\[dim]Why:\\[/] fabricated"
    assert "\n" not in cli._safe(forged)


async def test_the_conversations_listing_says_so_when_there_are_none(output: StringIO) -> None:
    """An empty listing is an answer, not a blank screen."""
    engine, _ = _conversation_engine()

    assert await cli._drive_conversations(engine, limit=50, offset=0) == 0
    assert "No conversations yet" in output.getvalue()


async def test_forget_conversation_declines_an_id_it_cannot_show(output: StringIO) -> None:
    """Unknown, deleted, or reclaimed all look the same here, on purpose.

    A surface that distinguished them would report on conversations it is meant to
    have forgotten.
    """
    engine, _ = _conversation_engine()

    code = await cli._drive_forget_conversation(engine, "nobody", confirm=lambda _digest: True)

    assert code == cli._EXIT_ERROR
    assert "No conversation has the id" in output.getvalue()


# --- the observe command is retired (ADR-0285 §6) -------------------------


def test_the_observe_command_is_gone_and_reaches_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0285 §6: "The CLI's ``observe`` command ... is removed."

    Asserted over the registered commands, so a hidden command or an alias that kept
    the name fails here, and by invoking it: a usage error, with no client opened, so
    nothing that still answers ``observe`` behind the façade is reached through this
    surface.
    """
    group = typer.main.get_command(cli.app)
    assert isinstance(group, TyperGroup)
    assert "observe" not in group.commands

    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())
    result = CliRunner().invoke(cli.app, ["observe"])

    assert result.exit_code == 2
    assert opened == []


# --- the old path's commands are retired (ADR-0309 §5, ADR-0313 §5:1) -------

#: ADR-0309 §5's CLI list, ADR-0313 §5:1's ``remember-recipients``, and ADR-0321
#: §7:1's and §7:2's recipient-grant and destination-trust commands.
_RETIRED_COMMANDS = (
    "ask",
    "resume",
    "cancel-read",
    "goals",
    "withdraw-clarification",
    "abandon-goal",
    "questions",
    "answer",
    "forget-question",
    "authorizations",
    "revoke-authorization",
    "remember-recipients",
    "recipient-grants",
    "recipient-grant-log",
    "revoke-recipient-grant",
    "trust-destinations",
    "destination-trust",
    "revoke-destination-trust",
)


@pytest.mark.parametrize("name", _RETIRED_COMMANDS)
def test_a_retired_command_is_gone_and_reaches_no_client(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0309 §5, ADR-0313 §5:1 and ADR-0321 §7:1-§7:2 retire these.

    Asserted over the registered commands, so a hidden command or an alias that kept
    the name fails here, and by invoking it: an unknown command is a usage error, with
    no client opened.
    """
    group = typer.main.get_command(cli.app)
    assert isinstance(group, TyperGroup)
    assert name not in group.commands

    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())
    result = CliRunner().invoke(cli.app, [name])

    assert result.exit_code == 2
    assert "No such command" in result.output
    assert opened == []


# --- lost support, rendered (ADR-0077 §6, ADR-0328 §15:7) -----------------------


def _half_gone() -> Belief:
    """An inference on two supports, one whose episode resolves and one whose is gone."""
    held = memory(
        "rec-1",
        "the user prefers metric units",
        remembered_support("activation:kept", when=LEARNED),
        remembered_support("activation:lost", effect="effect-2", when=LEARNED),
    )
    kept, lost = (support.points_at for support in held.supports)
    return belief_view(held, now=AT, contents={kept: "they asked for metric units", lost: None})


def test_the_single_view_shows_a_surviving_support_and_tombstones_the_gone_one(
    output: StringIO,
) -> None:
    """A gone support is an explicit tombstone — never an id, never a gap (§15:7).

    It still counts, and is shown as gone and never as evidence; it deliberately does not
    say what it was, nor whether it was deleted or merely expired.
    """
    cli._render_belief(_half_gone())
    rendered = _flat(output.getvalue())
    assert "they asked for metric units" in rendered
    assert "what it pointed at is gone" in rendered
    assert "activation:" not in rendered, "no episode id reaches the terminal"
    assert "Everything it rested on is gone" not in rendered, "one support still resolves"


def test_the_forget_prompt_shows_the_warrant_the_user_is_judging(output: StringIO) -> None:
    """Show-then-confirm includes the supports, tombstones and all (ADR-0073 §5, §6)."""
    cli._render_forget_prompt(_half_gone())
    rendered = _flat(output.getvalue())
    assert "About to forget this belief" in rendered
    assert "they asked for metric units" in rendered
    assert "what it pointed at is gone" in rendered


# --- the grant surface (ADR-0102 §1, §6, §9) --------------------------------
# Two of these clauses are the *client's* and are unenforceable from the hub's
# side (ADR-0098 §5): §6's disclosure-before-grant, and §9's rule about what a
# revocation may be said to have done. ADR-0102 §12's client lane owes exactly
# these tests, and they can live nowhere else.


def _granting_engine(*, location: str | None = "/srv/calendar.ics") -> FakeAssistantEngine:
    """A fake hub holding one grantable source, granted by nothing yet."""
    engine = FakeAssistantEngine()
    engine.hold_source("calendar", location=location)
    return engine


def test_sources_lists_each_source_with_where_it_reads_from(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0097 §9: a client offers a choice among declared identities.

    And the location is rendered, because this response is the only place it exists
    (ADR-0102 §6) — a listing that hid it would leave the user choosing between
    names with nothing to judge.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["sources"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "calendar" in rendered
    assert "/srv/calendar.ics" in rendered
    assert "not granted" in rendered


def test_grant_renders_the_location_before_it_asks(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §6's third clause, and **the ordering is the whole of it**.

    "A client renders ``location`` to the user, and takes an explicit act from the
    user, **before** it sends ``grant``." A client that prompted first and rendered
    the path afterwards would satisfy every "the path appears somewhere" check and
    breach the clause outright — the user would be answering about a source they
    had not been shown, which is the uninformed grant ADR-0097 §9a exists to
    prevent.

    So the console is read **at the moment the confirmation is requested**, from
    inside the approver itself, rather than after the command has returned. That is
    the only vantage point from which "before" is observable at all: nothing on the
    wire distinguishes the two orders (ADR-0098 §5), and neither does the final
    output.
    """
    engine = _granting_engine()
    _wire(monkeypatch, engine)
    seen_at_prompt: list[str] = []

    def _watching(_source: object) -> bool:
        seen_at_prompt.append(output.getvalue())
        return False

    monkeypatch.setattr(cli, "_confirm_grant", _watching)
    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "notify"])

    assert result.exit_code == 0
    assert len(seen_at_prompt) == 1, "the user must be asked exactly once"
    assert "/srv/calendar.ics" in seen_at_prompt[0]
    # And the refusal is honoured: nothing is sent at all.
    assert not [call for call in engine.calls if call[0] == "grant"]
    assert not engine.grants_recorded


def test_a_blank_source_is_a_usage_error_and_never_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0042 §7: an adapter maps every failure to a controlled exit code.

    ``NonBlankEncodableText`` refuses a blank ``source`` with a ``ValueError``,
    which is **not** an :class:`AssistantError` — so without a parse-time refusal it
    escapes the command's error boundary as an uncaught traceback. ``revoke`` is the
    case that reached the client at all: ``grant`` enumerates first and happens to
    report the value as unofferable, which is the right answer by accident of
    ordering rather than by a rule, so both are pinned here.

    Exit code 2, because it is a usage error caught before any client is built —
    the treatment ``--limit`` and blank ``learn`` content already get. **And that
    second clause is asserted rather than asserted-about** (#1970): ``grant``'s
    right answer here is right "by accident of ordering rather than by a rule", as
    above, and an ordering is the one thing an exit code cannot show.
    """
    opened = _wire_recording_opens(monkeypatch, _granting_engine())

    assert CliRunner().invoke(cli.app, ["revoke", "   "]).exit_code == 2
    assert CliRunner().invoke(cli.app, ["grant", "   ", "--scope", "notify"]).exit_code == 2
    assert opened == []


def test_a_repeated_scope_is_a_usage_error_and_never_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0097 §10 spells a duplicated scope as a refusal, not something to fold away.

    Both the client and the engine raise ``ValueError`` for it, which is again not
    an :class:`AssistantError`, so ``--scope notify --scope notify`` escaped as a
    traceback for the same reason a blank source did.

    **Refused at the parse boundary, which is asserted rather than asserted-about**
    (#1973): ``_distinct_scope`` is a Typer callback, and the two places that would
    otherwise raise are both *past* a client — so a refusal that had drifted behind
    the open would be answering the same argument with the same exit code, from the
    far side of the I/O this one precedes.
    """
    opened = _wire_recording_opens(monkeypatch, _granting_engine())

    result = CliRunner().invoke(
        cli.app, ["grant", "calendar", "--scope", "notify", "--scope", "notify", "--yes"]
    )
    assert result.exit_code == 2
    assert opened == []


def test_a_source_with_no_utf8_encoding_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""ADR-0102 §6's encoding hazard, one argument over from the path it names.

    Linux passes argv as bytes and Python decodes it with ``surrogateescape``, so
    ``assistant revoke $'\xe9'`` arrives as a lone surrogate — a value
    ``EncodableText`` refuses and ADR-0087's encoder has no form for. Refused at the
    parse boundary, so it is a usage error rather than the uncaught ``ValueError``
    the client would otherwise raise past the command's error boundary.

    **The refusal does not echo the value**, which is both ADR-0097 §9's rule about
    a caller-supplied source and a practical necessity: the process may not be able
    to write it down at all.

    **And "at the parse boundary" is observed rather than named** (#1973), for the
    reason the blank-source case one over states: ``grant`` reaches the right answer
    for a bad source partly by accident of ordering, so where the refusal falls
    relative to the client is exactly what wants pinning.
    """
    opened = _wire_recording_opens(monkeypatch, _granting_engine())
    unwritable = "\udce9"

    result = CliRunner().invoke(cli.app, ["revoke", unwritable])
    assert result.exit_code == 2
    assert unwritable not in result.output
    assert CliRunner().invoke(cli.app, ["grant", unwritable, "--scope", "notify"]).exit_code == 2
    assert opened == []


def test_the_source_reaches_the_hub_exactly_as_it_was_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0102 §2: the adapter refuses a blank source and **normalises nothing**.

    The refusal above is a parse-time callback, and a callback is exactly where an
    author reaches for ``.strip()``. Doing so would make ``revoke " calendar "``
    arrive at the hub as ``calendar`` and *match* a held reader, where ADR-0097 §10
    requires it be refused rather than matched — §2's substitutability failure,
    arriving one layer further out than the annotation it was argued about.
    """
    engine = _granting_engine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["revoke", "  calendar  "])
    assert [call for call in engine.calls if call[0] == "revoke"] == [
        ("revoke", {"source": "  calendar  "})
    ]


def test_grant_records_the_grant_once_the_user_agrees(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The discriminating half: the refusal above is about the answer, not the flow."""
    engine = _granting_engine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "notify"], input="y\n")
    assert result.exit_code == 0
    assert [record.scope for record in engine.grants_recorded] == [(GrantScope.NOTIFY,)]
    assert "Granted" in output.getvalue()


def test_a_pasted_revoke_hint_withdraws_the_source_it_was_printed_for(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both revoke hints have to survive being pasted (#984).

    A source name with an interior space is admissible rather than exotic: ADR-0102 §2
    keeps a reader's declared name byte-exact precisely because it is compared without
    normalisation, and ``NonBlankEncodableText`` never normalises. Unquoted, the hint
    for ``my calendar`` reads as ``assistant revoke my calendar`` — a valid command
    that revokes ``my``, with ``calendar`` left over.

    Both hints are exercised in one run because the second only exists after the
    first: granting once produces the confirmation's hint, and granting again finds
    the source already granted and produces the prompt's. Each sentence wraps its
    command in quotes of its own, so the slice each assertion reads back closes at
    that closing quote.
    """
    engine = FakeAssistantEngine()
    engine.hold_source("my calendar", location="/srv/calendar.ics")
    _wire(monkeypatch, engine)

    granted = CliRunner().invoke(
        cli.app, ["grant", "my calendar", "--scope", "notify"], input="y\n"
    )
    assert granted.exit_code == 0
    confirmation = _flowed(output.getvalue())
    assert "Granted." in confirmation
    assert _pasted(confirmation, "assistant revoke", "'.") == ["assistant", "revoke", "my calendar"]

    already = len(output.getvalue())
    again = CliRunner().invoke(cli.app, ["grant", "my calendar", "--scope", "notify"], input="n\n")
    assert again.exit_code == 0
    prompt = _flowed(output.getvalue()[already:])
    assert "It is already granted" in prompt
    assert _pasted(prompt, "assistant revoke", "'.") == ["assistant", "revoke", "my calendar"]


@pytest.mark.parametrize("unshowable", ["\n", "\t"], ids=["replaced", "expanded"])
def test_a_revoke_hint_is_withheld_where_the_source_name_cannot_be_shown(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, unshowable: str
) -> None:
    """A declared name a terminal cannot show costs the hint, not the grant (#1013).

    ADR-0102 §4 admits any declared identity equal to its own ``strip()`` that validates
    as an ``Identifier``, and neither an interior newline nor an interior tab is
    stripped — so both names below are enumerated and grantable, and both reach the
    screen as a *different* source: the newline is replaced by ``_safe`` and the tab is
    expanded by Rich.

    The act still happens and is still recorded byte-exact; what goes is the line
    offering to undo it. Which is the point of separating the two — an unshowable name
    must not become an ungrantable one.
    """
    named = f"my{unshowable}calendar"
    engine = FakeAssistantEngine()
    engine.hold_source(named, location="/srv/calendar.ics")
    _wire(monkeypatch, engine)

    granted = CliRunner().invoke(cli.app, ["grant", named, "--scope", "notify"], input="y\n")
    assert granted.exit_code == 0
    assert [record.source for record in engine.grants_recorded] == [named], (
        "the grant is recorded byte-exact; only the printed hint is affected"
    )
    confirmation = _flowed(output.getvalue())
    assert "Granted." in confirmation
    assert "cannot show" in confirmation
    assert "assistant revoke '" not in confirmation, "no argument is offered at all"

    already = len(output.getvalue())
    again = CliRunner().invoke(cli.app, ["grant", named, "--scope", "notify"], input="n\n")
    assert again.exit_code == 0
    prompt = _flowed(output.getvalue()[already:])
    assert "It is already granted" in prompt
    assert "cannot show" in prompt
    assert "assistant revoke '" not in prompt


def test_every_scope_a_new_grant_may_name_is_accepted_and_rendered_in_words(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0133 §6, as ADR-0294 §4 narrows it: the surface offers what the hub grants.

    "No lane may suppress the member from that surface while it is in the enum: an
    option that silently refuses a member of its own type, or a help string
    enumerating two of three uses, is a surface disagreeing with the vocabulary."
    ADR-0294 §4 takes ``INGEST`` out of what a new grant may name, so the vocabulary
    a new grant is offered is :data:`~ai_assistant.wire.GRANTABLE_SCOPES` — and the
    refusal of ``INGEST`` is loud, never silent (the case below).

    Written over that set rather than per member, so it is the *offer* that is
    asserted rather than today's names — a member added without a phrase fails here
    as well as at the type check, and a member accepted by the option but rendered
    as nothing cannot pass at all.

    **Both halves matter and neither implies the other.** The value must reach the
    hub as the user's chosen scope, and the confirmation must say what that scope
    allows *in words*: ADR-0102 §6 shows the user what they are consenting to
    before it is recorded, and a phrase that silently rendered empty would ask
    them to agree to a blank. That is why the rendered text is asserted to be
    non-trivial rather than merely present.
    """
    for use in GRANTABLE_SCOPES:
        engine = _granting_engine()
        _wire(monkeypatch, engine)

        result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", use.value, "--yes"])

        assert result.exit_code == 0, use
        assert [record.scope for record in engine.grants_recorded] == [(use,)], use
        rendered = output.getvalue()
        assert cli._scope_phrase([use]) in rendered, use
        assert len(cli._scope_phrase([use])) > len(use.value), use


def test_the_scope_options_help_names_every_use_a_new_grant_may_name(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0133 §6 again, on the surface a user reads *before* choosing.

    The confirmation above is shown once a scope has been named; this is what
    tells them the scope exists at all. A help string enumerating fewer uses than
    the hub grants leaves one undiscoverable, which is the "surface disagreeing with
    the vocabulary" §6 forbids — and it is the failure the type checker cannot see,
    because the help is a string. **And it offers no use the hub refuses**
    (ADR-0294 §4): ``ingest`` appears nowhere, choices included.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["grant", "--help"])

    assert result.exit_code == 0
    rendered = " ".join(result.output.split())
    for use in GRANTABLE_SCOPES:
        assert f"'{use.value}'" in rendered, use
    assert GrantScope.INGEST.value not in rendered


@pytest.mark.parametrize("command", ["grant", "amend"])
def test_a_mistyped_scope_is_answered_with_the_new_grant_offer_alone(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """ADR-0294 §4 reaches the refusal of a typo as well as the help text.

    A diagnostic that lists the choices is an offer too: Typer's own enum conversion
    would answer ``--scope facets`` with every member of ``GrantScope``, ``ingest``
    among them, and following that suggestion would meet a second refusal. So the
    refusal names exactly the uses a new grant may name, on both commands.
    """
    engine = _amendable_engine() if command == "amend" else _granting_engine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, [command, "calendar", "--scope", "facets", "--yes"])

    assert result.exit_code == 2
    refusal = " ".join(result.output.split())
    for use in GRANTABLE_SCOPES:
        assert f"'{use.value}'" in refusal, use
    assert GrantScope.INGEST.value not in refusal
    assert engine.calls == []


@pytest.mark.parametrize("command", ["grant", "amend"])
def test_a_typed_ingest_scope_is_refused_at_the_door_and_nothing_is_sent(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """ADR-0294 §4: a new grant may not name ``INGEST``, and the CLI says so legibly.

    The option's type still parses the word — ``GrantScope`` keeps the member so a
    recorded grant still renders — so the refusal is the parameter callback's, and it
    lands before the command body runs: nothing reaches the hub, not even the
    enumeration a grant begins with. Without it the hub's ``ValueError`` would
    surface as a traceback.
    """
    engine = _amendable_engine() if command == "amend" else _granting_engine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, [command, "calendar", "--scope", "notify", "--scope", "ingest", "--yes"]
    )

    assert result.exit_code == 2
    assert "can no longer be granted" in " ".join(result.output.split())
    assert engine.calls == []


def test_yes_supplies_the_answer_and_never_the_rendering(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0073 §5's rule, applied to consent for a *read* rather than a deletion.

    A non-interactive approval must not connect a source the user never saw: `--yes`
    answers the question, and ADR-0102 §6's disclosure happens either way. This is
    the case a "skip the prompt" flag gets wrong by skipping the render with it.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 0
    assert "/srv/calendar.ics" in output.getvalue()


def test_a_source_the_enumeration_does_not_carry_is_never_granted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §6: "a client that cannot show the user the location does not send grant".

    The hub would refuse this call anyway — that is §4, and the shared conformance
    suite holds it. What is asserted here is the *client's* half: nothing is sent at
    all, so the rule holds for the case where the hub's refusal is not what stops
    it — a reader whose configured location has no UTF-8 encoding, which is absent
    from the enumeration for a reason the client cannot see and must not guess at.
    """
    engine = _granting_engine()
    # Held, and **not grantable**: its configured location has no UTF-8 encoding, so
    # the hub omits it from the enumeration (ADR-0102 §6). That is the real cause
    # rather than a name nobody holds, and it is the one the client cannot see: from
    # here "absent" is all there is, which is why §6 fails closed rather than asking
    # the client to reason about why.
    engine.hold_source("notes", location="/srv/\udce9notes.md")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grant", "notes", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    assert not [call for call in engine.calls if call[0] == "grant"]
    rendered = output.getvalue()
    assert "cannot offer" in rendered
    assert "calendar" in rendered  # the remedy is the list, not an echo
    assert "/srv/" not in rendered  # and never the path it could not show


def test_a_source_with_no_configured_location_says_so_and_is_still_grantable(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §6: ``None`` means nothing is configured, so the obligation is vacuous.

    Said plainly rather than rendered as a blank, because "reads from:" followed by
    nothing is the shape a user reads as a bug — and this is the case a client must
    distinguish from a source that is absent altogether.
    """
    engine = _granting_engine(location=None)
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grant", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 0
    assert "no configured location" in output.getvalue()
    assert len(engine.grants_recorded) == 1


def test_revoke_neither_prompts_nor_enumerates_first(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §4: nothing may stand between the user and their remedy.

    **No prompt**, because revoking destroys nothing and is not the ceremony
    ADR-0073 §5 requires of a deletion. **No enumeration**, because that would
    reintroduce client-side exactly the admission check §4 removed — and would fail
    for the one case the removal exists for: a grant whose reader has since been
    unconfigured, which is unrevokable the moment anything checks.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.NOTIFY])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["revoke", "calendar"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == ["revoke"]
    assert "Withdrawn" in output.getvalue()


def test_revoke_never_claims_to_have_stopped_a_read(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §9, and the sentence a person writes is the one being refused.

    "Your calendar is no longer being read" overclaims: ADR-0097 §5a guarantees
    every read is authorised at the instant it *starts*, and a read already running
    completes on a worker nothing can stop. What is true is that no further read
    starts and nothing a running read produces is used, and the corpus explicitly
    declines to promise more — so the client may not either.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.NOTIFY])
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["revoke", "calendar"])
    rendered = output.getvalue().lower()
    assert "no further read" in rendered
    assert "still running" in rendered
    assert "no longer being read" not in rendered


def test_revoking_what_is_not_granted_says_so_without_claiming_anything_about_reads(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0102 §9: ``None`` is not silence about reads either.

    It means the source had no live grant at the moment the operation ran, and says
    nothing about what was or was not happening — so "nothing was happening" would
    invent the same overclaim from the other side.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["revoke", "calendar"])
    assert result.exit_code == 1
    rendered = output.getvalue().lower()
    assert "nothing to withdraw" in rendered
    assert "nothing was happening" not in rendered


def test_grants_lists_both_acts_and_points_liveness_elsewhere(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0097 §6 and ADR-0102 §3.

    Both acts are on the record because revoking is an **append**, and the listing
    must not be read as a standing: ADR-0097 §4 permits a revocation timestamped
    before the grant it revokes, so a page ordered by ``decided_at`` can put the two
    out of order. Pointing elsewhere is what keeps that a display oddity rather than
    a wrong answer, and ADR-0139 §3's last clause is why the pointer is now
    ``assistant granted``: ``sources`` answers what *may* be granted, so it misses a
    live grant on a source the hub holds no reader for — exactly the record a reader
    of this page most needs to be sent to.
    """
    engine = _granting_engine()
    granted = engine.hold_grant("calendar", scope=[GrantScope.NOTIFY])
    engine.hold_grant("calendar", scope=[GrantScope.NOTIFY], revokes=granted.id)
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["grants"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "granted" in rendered
    assert "withdrew" in rendered
    assert "assistant granted" in rendered


def test_a_non_positive_grants_limit_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0102 §10: the store requires a strictly positive limit.

    Caught at Typer's parse boundary, so it is exit code 2 rather than a
    ``ValueError`` escaping the command's error boundary as a traceback — the same
    treatment ``--limit 0`` gets nowhere else on this surface, because nowhere else
    is 0 illegal.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["grants", "--limit", "0"])
    assert result.exit_code == 2


# --- what is authorised, and amending it (ADR-0139 §3, §4, §5) ---------------
# ADR-0139's client lane. Every case below is deterministic rather than a timing
# test, which is worth saying because "lose the response" and "cancel mid-call"
# both read like flakes: the scripted engine below *records* the act and then
# raises, which is the stub-hub shape one layer in — the ADR's own note that "what
# is being tested throughout is the client's report, not the socket".


class _ScriptedGrantEngine(FakeAssistantEngine):
    """A hub whose grant acts can be made to fail in each way ADR-0139 §4 names.

    Three arms, because three outcomes have to be reachable and the canonical fake
    reaches only two on its own. ``commit_then_lose`` is the one that could not be
    written any other way: the record lands and the answer does not, which is
    ADR-0085 §8e's residual (#570) and the whole reason the third outcome exists.

    A fourth arm, ``standing_raises``, covers the **read** rather than an act: the
    canonical fake answers ``standing_grants`` from its recorded history and has no
    way to refuse, so the branch ``_drive_standing`` keeps for a store fault and an
    oversized set was reachable from no test at all (#1047).
    """

    def __init__(self) -> None:
        """Create the engine with nothing scripted."""
        super().__init__()
        #: Raised instead of answering ``revoke``, after nothing has been recorded.
        self.revoke_raises: BaseException | None = None
        #: Raised instead of answering ``standing_grants``, having read nothing.
        self.standing_raises: BaseException | None = None
        #: Raised instead of answering ``grant``.
        self.grant_raises: BaseException | None = None
        #: Whether ``grant`` records its grant *before* raising — the hub having
        #: committed and the client having lost the answer.
        self.commit_then_lose = False
        #: Run on the hub once ``revoke`` has done its work, which is where a
        #: **second connected client**'s act lands: between our two calls, on the
        #: hub's side, exactly as ADR-0102 §5 says two clients may.
        self.after_revoke: Callable[[], None] | None = None

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """Answer the live set, or refuse it — never answer it partly.

        The call is recorded before the refusal, so a case can tell "asked and was
        refused" from "never asked", which is the difference between the client
        rendering an error and the client having quietly skipped the read.
        """
        if self.standing_raises is not None:
            self.calls.append(("standing_grants", {}))
            raise self.standing_raises
        return await super().standing_grants()

    async def revoke(self, source: str) -> SourceGrant | None:
        """Withdraw, or raise what was scripted before touching anything."""
        if self.revoke_raises is not None:
            self.calls.append(("revoke", {"source": source}))
            raise self.revoke_raises
        withdrawn = await super().revoke(source)
        if self.after_revoke is not None:
            self.after_revoke()
        return withdrawn

    async def grant(self, source: str, *, scope: Sequence[GrantScope]) -> SourceGrant:
        """Record and answer, record and lose the answer, or refuse outright."""
        if self.grant_raises is not None:
            self.calls.append(("grant", {"source": source}))
            if self.commit_then_lose:
                self.hold_grant(source, scope=scope)
            raise self.grant_raises
        return await super().grant(source, scope=scope)


def _amendable_engine() -> _ScriptedGrantEngine:
    """A hub holding one grantable source, already granted for one use."""
    engine = _ScriptedGrantEngine()
    engine.hold_source("calendar", location="/srv/calendar.ics")
    engine.hold_grant("calendar", scope=[GrantScope.INGEST, GrantScope.NOTIFY])
    return engine


def test_granted_lists_a_grant_whose_source_the_hub_no_longer_holds(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §1 and §3: the set is presented whole, from the store.

    The whole point of the command in one case. ``journal`` has a live grant and no
    held reader — an operator unset its path — so it is absent from
    ``grantable_sources`` and was reported by nothing. A client that annotated this
    list against the enumeration, or dropped what the enumeration did not carry,
    would hide it again, so the assertion is that **one** call goes out and the
    unheld source is in what comes back.
    """
    engine = _granting_engine()
    engine.hold_grant("journal", scope=[GrantScope.INGEST])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == ["standing_grants"]
    rendered = output.getvalue()
    assert "journal" in rendered
    assert "durably remembering what it says" in rendered


def test_granted_renders_exactly_the_uses_a_grant_names(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §3's third clause, which is the half a well-meaning view gets wrong.

    A ``NOTIFY``-only grant renders as ``NOTIFY`` and **nothing else**: adding the
    members it leaves out — greyed out, or listed as not yet allowed — presents the
    user's decision as a half-filled form, which is a nudge toward a wider grant on
    the one surface whose subject is what they actually decided. The whole
    vocabulary belongs in the *choice* context, which is ``--scope``'s help, and
    that is asserted separately below.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.NOTIFY])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "raise things with you unprompted" in rendered
    assert "durably remembering" not in rendered


def test_granted_says_nothing_about_configuration_or_about_reads(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §3's fourth clause and §6's second.

    "Your calendar is not being read" is the sentence a person writes and it is a
    true sentence about the wrong axis — the source's *configuration* state
    presented where consent is being decided, which ADR-0093 §7 exists to keep
    apart. So no configured location appears here at all, and nothing claims a read
    happened or did not. Both are asserted negatively because both are what an
    author adds when the list looks sparse.
    """
    engine = _granting_engine()
    engine.hold_grant("calendar", scope=[GrantScope.NOTIFY])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "/srv/calendar.ics" not in rendered
    assert "not being read" not in rendered
    assert "last read" not in rendered


def test_granted_on_an_empty_store_offers_nothing_as_already_granted(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty set is an answer, and it is not the other question's answer.

    ADR-0139 §3 forbids presenting a standing grant as a source the user may grant;
    the mirror error on an empty set is to fill the space with the grantable list,
    which would answer "what may I grant" under a heading that asked something else.
    Pointing at the command that does answer it is the whole of what is offered.
    """
    _wire(monkeypatch, _granting_engine())

    result = CliRunner().invoke(cli.app, ["granted"])
    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "have not granted anything" in rendered
    assert "assistant sources" in rendered
    assert "calendar" not in rendered


def test_granted_reports_a_store_that_could_not_answer_and_lists_nothing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that failed is a failure, not an empty authorization set (#1047).

    ``GrantError`` is the store fault, and ADR-0097 §5a's "a driver that cannot get
    an answer fails closed" is stated on the error itself because the tempting
    reading is the other one. Here the tempting reading has a second face: a client
    that caught the refusal and fell through to the renderer would print the empty
    set's wording — telling a user who authorises three sources that they have
    authorised none, on the one surface whose subject is what they decided.
    """
    engine = _amendable_engine()
    engine.standing_raises = GrantError("the grant store could not be opened")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])

    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "the grant store could not be opened" in rendered
    assert "have not granted anything" not in rendered
    assert "calendar" not in rendered
    assert [call[0] for call in engine.calls] == ["standing_grants"]


def test_granted_reports_a_set_too_large_to_carry_rather_than_a_page_of_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §2's refusal has to survive as far as the terminal (#1047).

    The clause is that a frame too small for the live set reaches the user as a
    **refusal**, never as an empty or partial list, because "a page of what you
    authorise reads as complete while omitting an authorisation". The engine half
    is pinned against all three implementations by the shared conformance suite
    (``test_standing_grants_refuses_an_oversized_set_rather_than_truncating_it``);
    what had no test is the last hop, where a client that swallowed
    ``OversizedValueError`` would invert the clause exactly — and would invert it
    with a green suite, because the exit code is not what is wrong in that world.

    So the assertion that carries this case is the **absence** of the empty-set
    wording, not the presence of the exit code.
    """
    engine = _amendable_engine()
    engine.standing_raises = OversizedValueError(
        "the live set does not fit in one frame",
        limit=65024,
        size=70112,
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["granted"])

    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "does not fit in one frame" in rendered
    assert "have not granted anything" not in rendered
    assert "calendar" not in rendered
    assert [call[0] for call in engine.calls] == ["standing_grants"]


def test_amend_renders_the_location_before_it_asks_and_before_it_revokes(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §5 over ADR-0102 §6, and §4's sixth clause in the same case.

    Two orderings are asserted at once and both are the point. The **location** is
    on screen when the question is asked, because the granting half of an amendment
    is a ``grant`` and §6's disclosure applies to it unchanged — an amendment is
    exactly where a client author reasons that the user already consented and skips
    it. And **nothing has been withdrawn** at that moment: a surface that revoked
    first and then asked would put the interactive part of the flow inside the
    ungranted window, so a user who hesitates has withdrawn their grant by starting
    to think.

    Read from inside the approver, which is the only vantage point from which
    "before" is observable at all.
    """
    engine = _amendable_engine()
    _wire(monkeypatch, engine)
    seen: list[tuple[str, list[str]]] = []

    def approve(source: object) -> bool:
        seen.append((output.getvalue(), [call[0] for call in engine.calls]))
        return True

    monkeypatch.setattr(cli, "_confirm_amendment", approve)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify"])
    assert result.exit_code == 0
    assert len(seen) == 1
    at_prompt, calls_so_far = seen[0]
    assert "/srv/calendar.ics" in at_prompt
    assert "revoke" not in calls_so_far
    assert "grant" not in calls_so_far


def test_amend_issues_the_two_acts_in_order_and_reports_each(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's first two clauses: two acts, two records, two reports.

    No compound operation is sent — ADR-0102 §1 refuses one and §4 re-refuses it —
    and the state between them is reported rather than hidden, which is the reason
    the composition is the client's in the first place. The closing statement of
    what the source is now allowed comes from ``standing_grants``, never from
    either act's return value (§4's third clause).
    """
    engine = _amendable_engine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == [
        "grantable_sources",
        "revoke",
        "grant",
        "standing_grants",
    ]
    rendered = output.getvalue()
    assert "withdrawal landed" in rendered
    assert "grant landed" in rendered
    assert "raise things with you unprompted" in rendered


def test_amend_reports_a_refused_grant_as_failed_and_reads_the_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's second and third clauses, on the branch that is *known*.

    A hub that answered with a refusal wrote nothing, so the act is known not to
    have landed — and that is still not a statement about the **source**. The user
    is in the state the whole section exists for: their grant is gone and the new
    one did not arrive, and being told so is what makes it recoverable in one
    command.
    """
    engine = _amendable_engine()
    engine.grant_raises = UngrantableSourceError("no source by that name can be granted")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == [
        "grantable_sources",
        "revoke",
        "grant",
        "standing_grants",
    ]
    rendered = output.getvalue()
    assert "known not to have landed" in rendered
    assert "allowed nothing" in rendered  # read, not inferred


def test_amend_states_the_source_from_the_re_read_when_another_client_raced_it(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's third clause, on the case that makes the inference false.

    An earlier draft of that ADR said a grant known not to have landed means the
    source is ungranted. It does not: ADR-0102 §5 lets two clients be connected at
    once and makes the store the arbiter, so an ``InvalidGrantError`` is raised
    *because another client's grant is live* — and "the source is now ungranted" is
    false in the one case that produced the refusal.

    Here the other client's grant is already in the store when ours is refused, so
    a client reasoning from the refusal says the wrong thing and a client that reads
    says the right one.
    """
    engine = _amendable_engine()
    engine.grant_raises = InvalidGrantError("the source already has a live grant")

    # The competing act lands **between** our two calls, which is the only placement
    # that produces the case: earlier and our own revocation withdraws it again.
    def another_client_grants() -> None:
        engine.hold_grant("calendar", scope=[GrantScope.INGEST])

    engine.after_revoke = another_client_grants
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "known not to have landed" in rendered
    assert "durably remembering what it says" in rendered
    assert "nothing is granted on it" not in rendered


def test_amend_reports_a_lost_grant_response_as_not_known(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's second clause, and the outcome a two-outcome report cannot say.

    The hub commits the record and the answer is lost on the way back — ADR-0085
    §8e's residual, tracked as #570. "It failed" is false and "it worked" is
    unknowable, so the honest report is that the outcome is not known, and the
    re-read is what resolves it. The re-read is asserted to find the grant, because
    a report that said "not known" and then stopped would leave the user exactly
    where the clause is trying to get them out of.
    """
    engine = _amendable_engine()
    engine.grant_raises = TransportError("the hub closed the connection")
    engine.commit_then_lose = True
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    rendered = output.getvalue()
    assert "not known" in rendered
    assert "known not to have landed" not in rendered
    assert "raise things with you unprompted" in rendered  # the committed grant, read back


def test_amend_sends_no_grant_when_the_revocations_outcome_is_not_known(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §4's fourth clause: stop, and resolve by reading rather than writing.

    A client whose revocation is unresolved could send the grant anyway and reason
    backwards — refused means the revocation did not land, accepted means it did.
    That is the inference the third clause forbids and for the same reason: a
    refusal is equally consistent with another client having granted in between. One
    read settles it; a second write does not.
    """
    engine = _amendable_engine()
    engine.revoke_raises = TransportError("the hub closed the connection")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == [
        "grantable_sources",
        "revoke",
        "standing_grants",
    ]
    rendered = output.getvalue()
    assert "not known" in rendered
    assert "sent no new grant" in rendered


@pytest.mark.parametrize("act", ["revoke", "grant"])
def test_a_cancelled_amendment_reports_the_act_starts_nothing_and_propagates(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, act: str
) -> None:
    """ADR-0139 §4's fifth clause, written once per act as §8 requires.

    Three assertions rather than one, because the clause has three limbs and the
    natural implementations breach a different one each. ``CancelledError`` is a
    ``BaseException``, so an ``except Exception`` around the two calls does not see
    it and the client exits reporting nothing — the limb the **report** covers.
    Catching it and carrying on to print leaves a task the caller believes it
    cancelled, which ADR-0060 forbids — the limb the **propagation** covers. And
    reaching for the state in order to report it is the same breach by a kinder
    route: ADR-0060 permits deferring a cancellation only while a method makes its
    resources safe, and a read performed to present a state is not that — the limb
    **no further call** covers.
    """
    engine = _amendable_engine()
    setattr(engine, f"{act}_raises", asyncio.CancelledError())
    _wire(monkeypatch, engine)

    # It reaches the caller rather than being reported and swallowed. ``CliRunner``
    # catches ``Exception`` and nothing wider, so a ``BaseException`` arriving here
    # *is* the propagation ADR-0060 requires — and a client that caught it in order
    # to print would fail this line rather than the ones below.
    with pytest.raises(asyncio.CancelledError):
        CliRunner().invoke(cli.app, ["amend", "calendar", "--scope", "notify", "--yes"])

    assert "standing_grants" not in [call[0] for call in engine.calls]
    rendered = output.getvalue()
    assert "not known" in rendered
    assert "not read what" in rendered


def test_amend_is_refused_for_a_source_the_enumeration_does_not_carry(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §5: a client that cannot show the location does not send ``grant``.

    And therefore does not revoke either, because revoking here would leave the
    user strictly worse off than not running the command: the old grant gone and
    no new one possible. The remedy is named instead — ``revoke`` applies no
    admission check (ADR-0102 §4), so the user's whole remedy is untouched by a
    source having stopped being offered.
    """
    engine = _ScriptedGrantEngine()
    engine.hold_source("calendar", location="/srv/calendar.ics")
    engine.hold_grant("journal", scope=[GrantScope.INGEST])
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["amend", "journal", "--scope", "notify", "--yes"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == ["grantable_sources"]
    rendered = output.getvalue()
    assert "cannot amend" in rendered
    assert "assistant revoke journal" in rendered


def test_the_amend_scope_option_names_every_use_a_new_grant_may_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0139 §3's second clause, over ADR-0133 §6's CLI obligation.

    Wherever a surface offers, enumerates or explains the uses a user may choose
    among, it carries every use the hub grants, named in words. An amendment is a
    choice context, and a help string enumerating fewer is a surface disagreeing
    with the vocabulary — deciding on the user's behalf what they may permit, which
    is what ADR-0097 §8 forbids. ADR-0294 §4 takes ``INGEST`` out of that offer,
    since the amendment's new scope is a new grant.
    """
    _wire(monkeypatch, _amendable_engine())

    result = CliRunner().invoke(cli.app, ["amend", "--help"])
    assert result.exit_code == 0
    help_text = re.sub(r"\s+", " ", result.output)
    # ADR-0318 §6:2: the offer is NOTIFY alone, named in words.
    assert "facet" not in help_text
    assert "notify" in help_text
    # ADR-0294 §4: an amendment's new scope is a new grant, offered without INGEST.
    assert "ingest" not in help_text


# --- id arguments refuse at the parse boundary (ADR-0042 §7, ADR-0085 §3c) ---
# ADR-0085 §3c binds *every* engine implementation to ``Identifier`` validation
# "before any I/O", and its refusal is a ``ValueError`` — neither an
# ``AssistantError`` nor a ``TransportError``, so on each parameter below it escaped
# the command's error boundary as a traceback with exit 1 (#705). The subject here is
# ``FakeAssistantEngine`` rather than a permissive stand-in precisely because the fake
# enforces that clause through the same ``orchestration.payloads.identifier`` a hub
# client does: these cases reproduce the traceback, they do not merely assert a nicer
# exit code against a double that would have accepted anything.


def _id_invocations(value: str) -> tuple[tuple[str, list[str]], ...]:
    """Every parameter on this surface that carries an identifier, invoked with ``value``.

    Named so a failure says which command failed.
    """
    return (
        ("forget", ["forget", value, "--yes"]),
        ("forget-conversation", ["forget-conversation", value, "--yes"]),
        ("dismiss", ["dismiss", value]),
        ("forget-notification", ["forget-notification", value]),
        # `tune --class` is the second id-shaped parameter spelled without an `_id`
        # suffix, so the walk below cannot see it and this list is where it is held
        # — the residual that walk's own docstring names.
        ("tune --class", ["tune", "--class", value, "--reach", "interrupt"]),
        # ADR-0293's chat space. `--device`, `--add` and `--remove` name devices
        # without an `_id` suffix, so they are held here for the same reason.
        ("chat --conversation", ["chat", "--conversation", value]),
        ("chat --device", ["chat", "--device", value]),
        ("conversation", ["conversation", value]),
        ("delete-message", ["delete-message", value, "1", "--yes"]),
        ("delete-conversation", ["delete-conversation", value, "--yes"]),
        ("my-devices --add", ["my-devices", "--add", value, "--yes"]),
        ("my-devices --remove", ["my-devices", "--remove", value]),
        ("conversation-devices", ["conversation-devices", value]),
        ("conversation-devices --add", ["conversation-devices", "c-1", "--add", value]),
        # ADR-0297 §5:8's stop, naming the activation the current state named.
        ("stop", ["stop", value]),
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_every_id_argument_refuses_a_blank_before_any_client_is_built(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank id is a usage error (exit 2), never a traceback (ADR-0042 §7).

    ``_non_blank`` rejects it with a ``ValueError``, which every implementation
    raises before any I/O — so it arrives *inside* the command's
    ``except (AssistantError, TransportError)`` boundary and is caught by neither.
    Refusing during Typer's parameter parsing makes it a usage error instead, the
    treatment a blank ``source`` already gets.

    **And no client is opened**, which is the half this case's name promised and did
    not check (#728). Exit 2 alone is passed by a refusal that first built a client
    and probed the hub; the recorded opens are what say the refusal happened at the
    parse boundary, where ADR-0085 §3c's "before any I/O" puts it.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())

    for name, argv in _id_invocations(blank):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 2, name
        assert result.exception is None or isinstance(result.exception, SystemExit), name
        assert opened == [], name


def test_every_id_argument_refuses_a_value_with_no_utf8_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""A lone surrogate is refused at the parse boundary, and is not echoed back.

    Linux passes argv as bytes and Python decodes it with ``surrogateescape``, so
    ``assistant forget $'\xe9'`` arrives as half a character — a value
    ``EncodableText`` refuses and ADR-0087's encoder has no form for. Without the
    callback that refusal lands as the same uncaught ``ValueError`` a blank does.

    **The message does not echo the value**, which is a practical necessity rather
    than a policy borrowed from ``_present_source``: a value with no UTF-8 encoding
    is one this process may not be able to write down, so reporting the fault would
    fail the same way the fault does.

    **And, as with a blank, no client is opened** (#728): the value has no UTF-8
    encoding, so a command that reached the hub with it would have to write it down
    somewhere on the way — which is the failure, not the report of it.
    """
    opened = _wire_recording_opens(monkeypatch, FakeAssistantEngine())
    unwritable = "\udce9"

    for name, argv in _id_invocations(unwritable):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 2, name
        assert unwritable not in result.output, name
        assert opened == [], name


def test_an_id_is_stripped_before_it_is_looked_up_or_reported(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0085 §3c normalises an identity argument; this adapter does it too.

    The asymmetry with ``_present_source`` is the decision rather than an
    inconsistency. §3c makes stripping *contractual* for an identity argument,
    because "optional normalisation on an identity argument is worse than none: it
    makes the answer to ``belief(" rec-1 ")`` a property of which implementation you
    are holding" — where ADR-0102 §2 keeps a grant's ``source`` byte-exact so a name
    differing only by surrounding whitespace is refused rather than matched.

    Doing it here rather than leaving it to the implementation is what keeps the
    report honest: the id this module holds is the one it prints back, so an
    adapter that relayed ``"  no-such  "`` would report the lookup against a string
    the engine never used.
    """
    _wire(monkeypatch, FakeAssistantEngine())

    result = CliRunner().invoke(cli.app, ["forget", "  no-such  ", "--yes"])

    assert result.exit_code == 1  # an id naming no live belief, not a usage error
    assert "the id no-such." in output.getvalue()


def test_an_omitted_optional_id_still_means_no_conversation_was_named() -> None:
    """``None`` is the "no conversation named" state and must survive the callback.

    The one thing ``_present_optional_id`` must not do is turn an absent id into a
    blank one — which would leave ``assistant chat`` unable to start a conversation at
    all.
    """
    assert cli._present_optional_id(None) is None


def test_every_id_parameter_on_the_surface_carries_an_id_callback() -> None:
    """The obligation is stated over the app rather than over a list someone kept.

    #705 happened because five parameters were given a bare ``typer.Argument`` and
    nothing said a sixth existed. Walking the registered commands closes both halves
    of that: a parameter that loses its callback fails here rather than in a user's
    terminal, and a *seventh* fails too — deliberately, because the list
    :func:`_id_invocations` keeps is the one that goes stale, and this is what sends
    its author to it.

    **It catches the naming convention this surface follows, not every conceivable
    parameter.** An id spelled without an ``_id`` suffix — as ``chat``'s
    ``--conversation`` is — has to be recognised by name here, and a second such
    spelling would slip the walk. That residual is why the behavioural cases above
    enumerate them explicitly rather than deriving them from this.
    """
    group = typer.main.get_command(cli.app)
    assert isinstance(group, TyperGroup)
    id_callbacks = {cli._present_id, cli._present_optional_id}

    # Typer wraps a parameter callback in a click-shaped adapter, so the function
    # itself is reached through ``__wrapped__`` rather than compared directly. A
    # parameter with no callback at all — #705's state — unwraps to nothing and is
    # recorded as False rather than skipped.
    carried = {
        f"{name}:{param.name}": param.callback is not None
        and unwrap(param.callback) in id_callbacks
        for name, command in sorted(group.commands.items())
        for param in command.params
        if str(param.name).endswith("_id") or param.name == "conversation"
    }

    # Asserted as a mapping rather than with `all(...)`, so a failure names the
    # parameter that is missing its callback instead of reporting `False`.
    assert carried == {
        # ADR-0293's chat space: `chat --conversation` is an id spelled without an
        # `_id` suffix, named here for the reason above.
        "chat:conversation": True,
        "conversation:conversation_id": True,
        "conversation-devices:conversation_id": True,
        "delete-conversation:conversation_id": True,
        "delete-message:conversation_id": True,
        # ADR-0275 preserves exact store-valid episode addresses, including blanks.
        "episode:episode_id": False,
        "dismiss:notification_id": True,
        "forget:belief_id": True,
        "forget-conversation:conversation_id": True,
        "forget-notification:notification_id": True,
        "stop:activation_id": True,
    }


# --- the notification surface (ADR-0130 §6, §7, §9) -------------------------
# The five operations §9 ratifies, and the door #979 found missing: every clause
# below was implemented and conformance-tested on the contract, and none of it
# was reachable, so the tuning act §6 requires of the user could not be performed
# and — every class defaulting to `hold` — nothing could ever interrupt.


def _flowed(rendered: str) -> str:
    """Rich wraps at the fixture's console width, so an assertion reads the flowed text.

    A command line printed as a hint is exactly the sort of string that straddles a
    wrap, and a test matching only what fits on one line pins the console width
    rather than the message. The continuation marker :func:`cli._print` writes onto a
    wrapped line is dropped with the break that produced it, for :func:`_flat`'s
    reason (#2072).
    """
    return " ".join(rendered.replace("\u21b3", " ").split())


def _pasted(rendered: str, start: str, until: str) -> list[str]:
    """One printed command hint, read back the way a shell would read it (#984).

    The check every quoting case here wants: not "are there quote characters", which
    would pin whichever form ``shlex.quote`` happens to pick, but "does pasting this
    line name the thing it was printed for". A hint whose argument is unquoted parses
    into *more* words than it should, which is the failure — a valid command against
    the wrong argument rather than an error.

    Bounded at both ends rather than run to the end of the buffer, because the flowed
    text that follows a hint is prose: an apostrophe in it would leave ``shlex`` with
    an unterminated quote and fail every test for the wrong reason.

    Args:
        rendered: The console text, already flowed by :func:`_flowed`.
        start: The first word of the hint, where the slice opens.
        until: The first text after the hint, where the slice closes.

    Returns:
        The hint's words, as a shell would split them.
    """
    opened = rendered.index(start)
    return shlex.split(rendered[opened : rendered.index(until, opened)])


def _candidate(**overrides: object) -> NotificationCandidate:
    """A producer's proposal, with the fields a surface renders already set."""
    fields: dict[str, object] = {
        "candidate_key": "key-1",
        "producer": "calendar-upcoming",
        "notification_class": "upcoming_event",
        "summary": "Standup starts in ten minutes",
        "noticed_at": AT,
        "confidence": 0.9,
        "sensitivity": DataTier.PERSONAL,
    }
    return NotificationCandidate(**(fields | overrides))  # type: ignore[arg-type]


def _held(**overrides: object) -> HeldNotification:
    """A record held because its class is not set to interrupt — #979's own case.

    **The candidate declares an expiry, and that is not decoration.** ADR-0130 §5
    makes declaring one the whole of the escalation test, so a record with none fails
    ``PERISHABLE`` as well and the engine could never produce a failed set of
    ``(REACH_INTERRUPT,)`` alone. Building the fixture without an expiry made every
    case here a state no policy emits — and hid the one where the reach hint is a
    promise nothing can keep (:func:`_perishing`'s sibling below).

    ``reconsider_at`` stays ``None`` and that *is* the point of the example: reach is
    not a condition time resolves, so this record cannot free itself and the user's
    act is the only thing that moves it.
    """
    fields: dict[str, object] = {
        "id": "ntf-1",
        "candidate": _candidate(expires_at=AT + timedelta(hours=1)),
        "kind": NotificationDispositionKind.HOLD,
        "reason": NotificationCondition.REACH_INTERRUPT,
        "failed": (NotificationCondition.REACH_INTERRUPT,),
        "ruled_at": AT,
        "admitted_at": AT,
        "retention": timedelta(days=7),
    }
    return HeldNotification(**(fields | overrides))  # type: ignore[arg-type]


def _never_urgent(**overrides: object) -> HeldNotification:
    """The state an engine actually emits for a candidate that declares no expiry.

    Two failing conditions in ``INTERRUPT_CONDITIONS`` order, ``PERISHABLE`` first and
    therefore the reason — verified against ``FakeNotificationPolicy``, which is the
    conformance-tested ruling. No reach setting removes the first of them (§5, §6).
    """
    fields: dict[str, object] = {
        "candidate": _candidate(expires_at=None),
        "reason": NotificationCondition.PERISHABLE,
        "failed": (
            NotificationCondition.PERISHABLE,
            NotificationCondition.REACH_INTERRUPT,
        ),
    }
    return _held(**(fields | overrides))


def test_a_held_notification_renders_what_it_says_and_what_it_belongs_to(
    output: StringIO,
) -> None:
    """ADR-0130 §7: the explicit enumeration is the only way a held record reaches a user.

    So it has to carry everything the act needs: the words the producer wrote, the
    class ``assistant tune`` takes, and the id the two disposing verbs take. A
    listing missing the class is the one #978 drove around with a throwaway wire
    driver, because there was nothing on screen to type.
    """
    cli._render_notifications((_held(),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered
    assert "Standup starts in ten minutes" in rendered
    assert "upcoming_event" in rendered
    assert "calendar-upcoming" in rendered


def test_a_hold_is_explained_by_its_whole_failed_set_and_not_by_its_reason_alone(
    output: StringIO,
) -> None:
    """ADR-0130 §5: ``reason`` is the failed set's *first* member, not its only one.

    A record held behind a quiet window whose budget is also spent has two answers
    to "why did you not tell me?", and both are things the user would have to
    change. Rendering the first alone is a true answer arranged into a misleading
    one — the same failure §6 names when it makes the setting-change rule read the
    whole set rather than the recorded first reason.
    """
    cli._render_notifications(
        (
            _held(
                reason=NotificationCondition.QUIET_WINDOW,
                failed=(NotificationCondition.QUIET_WINDOW, NotificationCondition.BUDGET),
                reconsider_at=AT + timedelta(hours=2),
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "quiet hours" in rendered
    assert "budget" in rendered


def test_an_expired_record_is_still_listed_and_renders_as_expired(output: StringIO) -> None:
    """ADR-0130 §7: expiry ends a notification's actionability and **deletes nothing**.

    So the record stays enumerable — and the listing has to say which side of that
    line it is on, because "renders as expired" is the clause and no field on the
    record answers it. What the surface supplies is the clock reading; the boundary
    itself is ``NotificationCandidate.is_perishable_at``'s, spelled once in ``core``
    so a policy, a store and a listing cannot disagree about it.

    Both halves are asserted: the row is present (a listing that hid it would breach
    "stays enumerable"), and it is marked (a listing that showed only the timestamp
    would leave a person reading a live-looking notification about a moment that has
    gone — which is the state #978 found the record sitting in).
    """
    long_past = AT - timedelta(days=400)
    cli._render_notifications(
        (
            _held(
                candidate=_candidate(
                    noticed_at=long_past - timedelta(hours=1), expires_at=long_past
                )
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered
    assert "Expired" in rendered
    assert cli._when(long_past) in rendered


def test_a_record_whose_moment_is_still_ahead_is_not_called_expired(output: StringIO) -> None:
    """The other side of the same boundary, at the instant §5 fixes it.

    ``is_perishable_at`` is half-open in the direction §5 states — **at**
    ``expires_at`` the candidate has perished — so a record judged one moment before
    its expiry is live and one judged at it is not. Pinning both sides is what stops
    an off-by-one that would label every notification expired the moment it arrives.
    """
    expires = AT + timedelta(minutes=10)
    live = _held(candidate=_candidate(expires_at=expires))

    cli._render_notifications((live,), now=AT, limit=50, offset=0)
    ahead = _flowed(output.getvalue())

    assert "Expires:" in ahead
    assert "Expired" not in ahead


def test_an_expired_record_is_offered_no_act_because_the_engine_would_decline_it(
    output: StringIO,
) -> None:
    """ADR-0130 §7 makes expiry one of the three ways actionability ends.

    ``dismiss_notification`` answers ``False`` for an expired record, so a hint beside
    one is a surface promising what the engine will not do. The check asks the record
    (``is_actionable_at``) rather than reading the two stamps: a version testing only
    ``dismissed_at`` and ``dropped_at`` passes every other case here and fails exactly
    this one.
    """
    long_past = AT - timedelta(days=400)
    cli._render_notifications(
        (
            _held(
                candidate=_candidate(
                    noticed_at=long_past - timedelta(hours=1), expires_at=long_past
                )
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "assistant dismiss" not in rendered
    assert "assistant tune --class" not in rendered


@pytest.mark.parametrize(
    ("name", "overrides"),
    [
        ("dismissed", {"dismissed_at": AT + timedelta(minutes=5)}),
        (
            "ruled out",
            {
                "kind": NotificationDispositionKind.DROP,
                "reason": NotificationCondition.REACH_OFF,
                "failed": (),
                "dropped_at": AT + timedelta(minutes=5),
            },
        ),
    ],
)
def test_a_stamped_cessation_ends_the_offer_whatever_this_devices_clock_reads(
    name: str, overrides: dict[str, object], output: StringIO
) -> None:
    """A client behind the hub must not offer an act on a record the hub already closed.

    Dismissal and a reconsideration's ``DROP`` are **persisted**: the hub stamped
    them, so that they happened is not something this device's clock has a view on.
    Judging them against the local reading — which one ``is_actionable_at(now)`` call
    for all three limbs would do — makes a client running five minutes behind render
    the "Dismissed:" stamp *and*, two lines under it, offer ``assistant dismiss``,
    which the engine answers ``False`` for.

    The stamps here are deliberately **after** ``now``, which is exactly the skew this
    is about and a state the equal-timestamp cases elsewhere cannot reach.
    """
    cli._render_notifications((_held(**overrides),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered, name
    assert "assistant dismiss" not in rendered, name
    assert "assistant tune --class" not in rendered, name


def test_a_pasted_hint_sets_the_class_it_names_even_when_that_class_has_a_space(
    output: StringIO,
) -> None:
    """A hint meant to be pasted has to survive being pasted.

    Neither ``Identifier`` nor ``NonBlankEncodableText`` forbids an interior space, so
    an unquoted hint for a class named ``calendar upcoming`` reads as a *valid*
    command that sets a different class — a wrong action, not an error. ``_safe``
    answers a different question (Rich markup and control characters), so quoting
    happens first and the escaped text is the quoted form.

    Asserted by parsing the rendered line the way a shell would, rather than by
    matching quote characters, so it holds whichever quoting form ``shlex`` picks.
    """
    spaced = _held(id="ntf 1", candidate=_candidate(notification_class="calendar upcoming"))

    cli._render_notifications((spaced,), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    dismiss = shlex.split(rendered[rendered.index("assistant dismiss") :].split("  ")[0])
    assert dismiss[:3] == ["assistant", "dismiss", "ntf 1"]
    tune = shlex.split(rendered[rendered.index("assistant tune") :])
    assert tune[:5] == ["assistant", "tune", "--class", "calendar upcoming", "--reach"]


def test_a_long_command_hint_is_not_folded_at_the_console_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1023: Rich folds by inserting a real newline, so a folded hint pastes as two.

    Rich wraps at the console's width by writing an actual line break into the
    output rather than leaving the terminal to fold the line, so at a narrow width
    ``assistant dismiss <long id>`` arrives on screen as ``assistant dismiss`` and
    then the id — and copying it runs a dismissal with no argument followed by the
    id as a command of its own. Where the argument is quoted the break lands *inside*
    the quotes instead, and the command then names a value with a newline in it.
    Nothing bounds these values: ``Identifier`` and ``NonBlankEncodableText`` require
    non-blankness and encodability and nothing else.

    Read off the **raw** buffer at a deliberately narrow width, because
    :func:`_flowed` re-joins wrapped output and a test written through it cannot see
    this at any width. The prose is asserted in the same breath and in the opposite
    direction: what is turned off is the wrapping of the lines carrying commands, not
    the console's wrapping, and a fix that stopped wrapping everything would pass a
    test that only looked at the hint.
    """
    width = 40
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=width))
    identifier = f"ntf-{'a' * 60}"

    cli._render_notifications((_held(id=identifier),), now=AT, limit=50, offset=0)

    lines = buffer.getvalue().splitlines()
    hints = [line for line in lines if "assistant " in line]
    assert [shlex.split(line[line.index("assistant ") :]) for line in hints] == [
        ["assistant", "dismiss", identifier],
        ["assistant", "tune", "--class", "upcoming_event", "--reach", "interrupt"],
    ], "each hint is one whole line, and pastes as the one command it names"
    assert max(len(line) for line in lines if line not in hints) <= width, (
        "the prose around them still wraps to the console"
    )


def test_the_hint_printer_leaves_the_line_for_the_terminal_to_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decision #1023 asks to be taken once, asserted where it is taken.

    Twelve sites print a copyable command and all of them go through
    :func:`~ai_assistant.interfaces.cli._print_hint`; this is what that function
    promises them. ``soft_wrap`` rather than an ``overflow`` or ``crop`` setting is
    the load-bearing half — those **truncate** a line too long for the console, which
    would turn a command that pastes wrongly into one that pastes silently short, and
    a truncated hint is the one failure mode worse than a folded one.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=20))
    line = "assistant dismiss " + "x" * 200

    cli._print_hint(line)

    assert buffer.getvalue() == f"{line}\n", "neither folded nor truncated"


def test_every_renderer_that_builds_a_command_prints_it_through_the_hint_printer() -> None:
    """The other half of #1023's "deciding once", which no rendering case can reach.

    Twelve prints carry a copyable command and the two cases above exercise two of
    them; a lane that reverted any of the other ten to a bare ``console.print``
    would leave both of them green and would restore the fold on that surface. So
    the routing is asserted structurally instead, over the module's own syntax
    tree — the only vantage point from which "every site" is a statement rather
    than a list somebody keeps up to date.

    The rule is read off what a function *does* rather than off a roster of names:
    a renderer that composes a shell argument (:func:`~ai_assistant.interfaces.cli
    ._argument`) or a reference hint and then prints anything at all is offering a
    command to copy, and has to offer it unfolded. :func:`~ai_assistant.interfaces
    .cli._reference_hint` composes one and prints nothing, so it is not a renderer
    and is excluded by that same test rather than by an exemption.

    It cannot see a renderer that prints the *prose around* a hint through
    ``console.print`` — which is correct, and is what those calls are for — so the
    two rendering cases above stay the pin on what reaches the buffer.
    """
    source = Path(cli.__file__).read_text(encoding="utf-8")

    def _called(node: ast.AST) -> set[str]:
        names: set[str] = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            called = inner.func
            if isinstance(called, ast.Name):
                names.add(called.id)
            elif isinstance(called, ast.Attribute) and isinstance(called.value, ast.Name):
                names.add(f"{called.value.id}.{called.attr}")
        return names

    unfolded: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        calls = _called(node)
        composes = {"_argument", "_reference_hint"} & calls
        prints = {"console.print", "_print_hint"} & calls
        if composes and prints and "_print_hint" not in calls:
            unfolded.append(f"{node.name} (line {node.lineno})")

    assert not unfolded, f"builds a command and prints it folded: {unfolded}"


def test_a_candidate_with_no_expiry_says_why_that_makes_it_unurgent(output: StringIO) -> None:
    """ADR-0130 §5: declaring an expiry **is** the escalation test.

    A candidate that commits to no moment fails ``PERISHABLE``, which is why it is
    held rather than dropped and why no setting can make it due. Rendering the
    absence as a blank would leave the user tuning a class that was never going to
    interrupt whatever they set.
    """
    cli._render_notifications((_never_urgent(),), now=AT, limit=50, offset=0)

    assert "never" in _flowed(output.getvalue())


def test_a_record_no_setting_can_free_is_not_offered_a_reach_raise(
    output: StringIO,
) -> None:
    """ADR-0130 §6: "a record whose set holds only the expiry condition is reached by
    no setting", and §5 is why.

    The engine's own ruling for a candidate with no expiry fails ``PERISHABLE`` *and*
    ``REACH_INTERRUPT``, so a hint reading only the second offers a raise that re-arms
    the record, runs a reconsideration, and re-holds it on the condition nothing can
    remove — an interruption promised and never delivered, which is #979's failure
    wearing the opposite face.

    What is offered instead: dismissal, the lowering act (which still does something),
    and the reason in words, because a user who performed the act and heard nothing
    would reasonably conclude the act had failed.
    """
    cli._render_notifications((_never_urgent(),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "assistant dismiss ntf-1" in rendered
    assert "--reach interrupt" not in rendered
    assert "assistant tune --class upcoming_event --reach off" in rendered
    assert "No reach setting can make this one interrupt" in rendered


def test_a_record_held_behind_its_reach_is_offered_the_raise_that_frees_it(
    output: StringIO,
) -> None:
    """ADR-0130 §6: the two acts a surface rendering one should offer, in one step.

    Which direction to offer is read off the failed set: this record is held by the
    user's own reach setting, so raising that class is the act that changes its
    outcome. Offering ``--reach off`` here would be a correct-looking suggestion
    that does the opposite of what the person reading it wants.
    """
    cli._render_notifications((_held(),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "assistant dismiss ntf-1" in rendered
    assert "assistant tune --class upcoming_event --reach interrupt" in rendered


def test_a_record_that_is_already_allowed_through_is_offered_the_lowering_act(
    output: StringIO,
) -> None:
    """§6 names *lowering* as the second act, and an ``INTERRUPT`` is where it applies.

    Nothing about this record's reach is holding it back, so "raise the class" would
    suggest a change with no effect; what a person reading an interruption may want
    is to stop that class reaching them.
    """
    cli._render_notifications(
        (
            _held(
                kind=NotificationDispositionKind.INTERRUPT,
                reason=NotificationCondition.BUDGET,
                failed=(),
            ),
        ),
        now=AT,
        limit=50,
        offset=0,
    )

    rendered = _flowed(output.getvalue())
    assert "assistant tune --class upcoming_event --reach off" in rendered
    assert "--reach interrupt" not in rendered


@pytest.mark.parametrize(
    ("name", "overrides"),
    [
        (
            "dropped",
            {
                "kind": NotificationDispositionKind.DROP,
                "reason": NotificationCondition.REACH_OFF,
                "failed": (),
                "dropped_at": AT,
            },
        ),
        ("dismissed", {"dismissed_at": AT}),
    ],
)
def test_a_record_that_can_no_longer_act_is_offered_no_act(
    name: str, overrides: dict[str, object], output: StringIO
) -> None:
    """A surface may not offer a verb the engine will decline (ADR-0130 §7).

    Both states are still *enumerated* — a dismissal is not a deletion and a DROP
    leaves the record readable — so the row is rendered either way. What is withheld
    is the invitation: ``dismiss`` on either returns ``False``, and printing it
    beside the record would advertise an act that does nothing.
    """
    cli._render_notifications((_held(**overrides),), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "ntf-1" in rendered, name
    assert "assistant dismiss" not in rendered, name
    assert "assistant tune --class" not in rendered, name


def test_an_empty_listing_names_the_chain_that_arms_unprompted_contact(
    output: StringIO,
) -> None:
    """#979 and #981 meet here: nothing held is the state an unarmed hub sits in.

    Out of the box every class holds, so an empty page is both the ordinary first-day
    state and what an operator sees when one link of the arming chain is missing —
    and it is the one moment they are certainly looking. Saying only "nothing here"
    would leave them where #978 was, reading ADR bodies to find the acts.
    """
    cli._render_notifications((), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "assistant tune --help" in rendered
    assert "assistant notification-settings" in rendered


def test_a_hint_is_withheld_where_showing_it_would_change_what_it_says(
    output: StringIO,
) -> None:
    """A wrong command is worse than no command, and quoting alone does not stop one.

    ``_safe`` **replaces** a character a terminal must not be handed, so a class
    carrying a newline renders as ``calendar\ufffdupcoming`` — inside correct shell
    quotes, and naming a class that does not exist. That is the exact failure quoting
    was added to prevent, arriving one step later and looking like a working
    instruction rather than a mistake.

    The record still renders: what is withheld is the copyable line, and the
    replacement says so rather than leaving a gap the reader has to notice.
    """
    unshowable = _held(candidate=_candidate(notification_class="calendar\nupcoming"))

    cli._render_notifications((unshowable,), now=AT, limit=50, offset=0)

    rendered = _flowed(output.getvalue())
    assert "Standup starts in ten minutes" in rendered
    assert "assistant tune --class" not in rendered
    assert "assistant dismiss ntf-1" not in rendered
    assert "cannot show" in rendered


def test_a_tab_is_uncopyable_even_though_safe_keeps_it(output: StringIO) -> None:
    """``_safe`` is not the only lossy step between a value and the screen (#1013).

    A tab is the case the "ask ``_safe`` itself" construction misses: ``_safe`` keeps it
    on purpose — a tab inside displayed prose is legitimate, and replacing it would
    corrupt what a producer wrote — but **Rich expands it to the next tab stop** when it
    renders, before any terminal is involved. So a hint carrying one is displayed
    correctly quoted and naming a different value, which is precisely the failure
    ``_is_pasteable`` exists to catch.

    The expansion is read off Rich rather than asserted from this docstring, and the
    consequence is stated as a round trip: what is on screen, split as a shell splits
    it, is not the value it was printed for.
    """
    tabbed = "my\tcalendar"
    assert cli._safe(tabbed) == tabbed, "_safe keeps it, which is why asking _safe is not enough"

    cli.console.print(shlex.quote(tabbed))

    shown = output.getvalue().rstrip("\n")
    assert "\t" not in shown, "Rich expanded it on the way to the screen"
    assert shlex.split(shown) != [tabbed], "so reading the screen back names something else"
    assert not cli._is_pasteable(tabbed)


def test_tune_sends_a_class_byte_for_byte_so_the_listing_round_trips(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NonBlankEncodableText`` preserves surrounding whitespace, and ``reach_for``
    compares exactly — so normalising here would guarantee the unreachable setting it
    looks like it prevents.

    A producer may declare ``" upcoming_event "``; a record carries it and the listing
    prints it. Were ``--class`` to strip, the row written would be for
    ``"upcoming_event"``, the record would stay governed by the padded name, and the
    class the user was looking at could not be tuned at all — the failure ADR-0102 §2
    keeps a grant's ``source`` byte-exact to avoid, one argument over.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["tune", "--class", " upcoming_event ", "--reach", "interrupt"]
    )

    assert result.exit_code == 0
    written = _written(engine)
    assert [row.notification_class for row in written.reaches] == [" upcoming_event "]
    assert written.reach_for(" upcoming_event ") is NotificationReach.INTERRUPT
    # And it is emphatically *not* the stripped name, which governs nothing here.
    assert written.reach_for("upcoming_event") is NotificationReach.HOLD


@pytest.mark.parametrize(
    ("name", "limit", "offset"),
    [("a zero limit", 0, 0), ("a page past the end", 50, 100)],
)
def test_an_empty_page_that_proves_nothing_does_not_claim_the_store_is_empty(
    name: str, limit: int, offset: int, output: StringIO
) -> None:
    """An empty *page* and an empty store are different claims, and only one is checkable.

    ``--limit 0`` is accepted here exactly as it is on every other listing — the
    engine refuses only outside ``[0, 2**63)`` — and it returns nothing whatever the
    store holds; so does any offset past the end. Answering either with "I am holding
    nothing for you" is a confident false absence, and it is worse on this surface
    than on the others, because the same message goes on to explain how to arm a
    thing that may already be armed.
    """
    cli._render_notifications((), now=AT, limit=limit, offset=offset)

    rendered = _flowed(output.getvalue())
    assert "holding nothing" not in rendered, name
    assert "assistant tune --help" not in rendered, name
    assert "this page" in rendered, name


def test_notifications_relays_the_page_and_renders_what_the_engine_returned(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §6: the adapter relays the paging arguments and renders the result.

    It re-filters nothing and re-orders nothing — membership and order are the
    store's contract (ADR-0130 §7, oldest first).
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["notifications", "--limit", "5", "--offset", "2"])

    assert result.exit_code == 0
    assert [call for call in engine.calls if call[0] == "notifications"] == [
        ("notifications", {"limit": 5, "offset": 2})
    ]


def test_a_full_page_of_notifications_offers_the_next_offset(output: StringIO) -> None:
    """No total is available, so "is there more" is answered by asking (ADR-0130 §7).

    The belief, conversation and question listings all answer it this way; a count
    here would be a number nothing on the contract can supply.
    """
    cli._render_notifications((_held(),), now=AT, limit=1, offset=0)

    assert "--offset 1" in _flowed(output.getvalue())


@pytest.mark.parametrize("bad", ["-1", "9223372036854775808"])
def test_a_notification_page_outside_the_stores_range_is_a_usage_error(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §7: the engine refuses these with ``ValueError``, not ``AssistantError``.

    So without a parse-time refusal it escapes the command's error boundary as a
    traceback with no controlled exit code — the treatment ``beliefs`` and
    ``conversations`` already give the same argument.
    """
    _wire(monkeypatch, FakeAssistantEngine())

    for flag in ("--limit", "--offset"):
        result = CliRunner().invoke(cli.app, ["notifications", flag, bad])
        assert result.exit_code == 2, flag
        assert result.exception is None or isinstance(result.exception, SystemExit), flag


def test_dismiss_relays_the_id_and_says_the_record_survives(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §9: a dismissal is not a deletion, and the wording is load-bearing.

    What ends is actionability — which frees a slot under the cap at once and stops
    the key suppressing duplicates, so the same fact recurring afterwards is a new
    candidate. A message reading "destroyed" would misstate all three.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    held = asyncio.run(_admit(engine))

    # Padded, so the strip `_present_id` performs is exercised on the way through:
    # the engine is asked about the id the user meant, not about the spaces.
    result = CliRunner().invoke(cli.app, ["dismiss", f"  {held}  "])

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "Dismissed" in rendered
    assert "still there" in rendered
    assert "forget-notification" in rendered


def test_dismiss_reports_nothing_outstanding_without_guessing_which_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``False`` covers four states and the façade returns one boolean (ADR-0130 §9).

    No such id, and one already dismissed, expired or dropped, are indistinguishable
    from here. Naming one of them would be a diagnosis this process cannot make —
    ``_render_no_such_source`` declines the same guess for the same reason.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["dismiss", "ntf-missing"])

    assert result.exit_code == 1
    assert "Nothing to dismiss" in _flowed(output.getvalue())
    assert [call for call in engine.calls if call[0] == "dismiss_notification"] == [
        ("dismiss_notification", {"notification_id": "ntf-missing"})
    ]


def test_forget_notification_says_the_same_thing_can_be_raised_again(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §8: the record is what stops a cursorless producer re-raising a fact.

    Destroying it therefore has a consequence a user should be told about rather
    than discover — re-noticing is the *normal* case, and the record is the whole of
    what makes it safe.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    held = asyncio.run(_admit(engine))

    result = CliRunner().invoke(cli.app, ["forget-notification", held])

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "Forgotten" in rendered
    assert "no export" in rendered


def test_forget_notification_reports_an_id_that_names_nothing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shape ``forget_question`` takes, exit code included (ADR-0130 §9)."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["forget-notification", "ntf-missing"])

    assert result.exit_code == 1
    assert "Nothing to forget" in _flowed(output.getvalue())


def test_neither_disposing_verb_asks_a_question_before_it_acts(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0130 §9 puts the delete "in the shape ``forget_question`` takes", and that
    shape has no ceremony.

    ADR-0073 §5 requires show-then-confirm before destroying a **belief**; a
    notification is not one, any more than a question is — nothing is being
    un-believed, and ``assistant notifications`` has already rendered the record
    together with both verbs. A dismissal destroys nothing at all.

    Pinned by driving both with **no** ``--yes`` and no interactive input: a command
    that grew a prompt would hang or abort here instead of acting.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    def _never(*_args: object, **_kwargs: object) -> bool:
        message = "a disposing verb on this surface asks nothing"
        raise AssertionError(message)

    monkeypatch.setattr(typer, "confirm", _never)
    for argv in (["dismiss", "ntf-1"], ["forget-notification", "ntf-1"]):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exception is None or isinstance(result.exception, SystemExit), argv
        assert result.exit_code == 1, argv


def test_notification_settings_renders_all_three_from_an_empty_store(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: every standing setting has a shipped default, so an empty store
    is a working policy.

    All three are therefore shown whether or not the user has touched any — and the
    **default reach is named beside the classes**, because it governs every class no
    row mentions, which on a fresh installation is all of them. Rendering only what
    was set would present "I have decided nothing" as "nothing governs this", which
    is precisely the misreading that leaves someone waiting for an interruption that
    was never going to come.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["notification-settings"])

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "hold" in rendered
    assert "every other class" in rendered
    assert "none" in rendered  # no quiet windows
    assert "3 per 24 hours" in rendered


async def _admit(engine: FakeAssistantEngine) -> str:
    """Put one held record in the fake's store and return the id it minted."""
    ruling = await engine.notification_store.admit(_candidate(), policy=engine.notification_policy)
    assert ruling.notification_id is not None
    engine.calls.clear()
    return ruling.notification_id


def _seeded() -> NotificationPreferences:
    """Standing settings with something on every axis, so a write can lose one."""
    return NotificationPreferences(
        reaches=(
            ClassReach(notification_class="upcoming_event", reach=NotificationReach.HOLD),
            ClassReach(notification_class="inbox", reach=NotificationReach.OFF),
        ),
        quiet_windows=(QuietWindow(start=22 * 60, end=7 * 60),),
        interruption_budget=5,
        budget_window=timedelta(hours=12),
    )


def _written(engine: FakeAssistantEngine) -> NotificationPreferences:
    """The value the last ``set_notification_preferences`` carried."""
    sent = [call for call in engine.calls if call[0] == "set_notification_preferences"]
    assert len(sent) == 1, sent
    value = sent[0][1]["preferences"]
    assert isinstance(value, NotificationPreferences)
    return value


async def _seed(engine: FakeAssistantEngine) -> None:
    """Put :func:`_seeded` into the fake's store."""
    await engine.notification_store.set_preferences(_seeded())


def test_tune_reads_adjusts_and_writes_back_leaving_every_other_axis_alone(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6, and the flow ``set_notification_preferences`` prescribes in terms.

    The surface writes the **whole** value, so a command that sent only what the user
    named would silently discard their quiet hours and their budget the first time
    they raised a class. That is not a hypothetical: raising a class is the one act
    §6 requires of every user, so it is the act most likely to be performed by
    someone who has already tuned the other two.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(
        cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"]
    )

    assert result.exit_code == 0
    written = _written(engine)
    assert written.reach_for("upcoming_event") is NotificationReach.INTERRUPT
    assert written.reach_for("inbox") is NotificationReach.OFF
    assert written.quiet_windows == _seeded().quiet_windows
    assert written.interruption_budget == 5
    assert written.budget_window == timedelta(hours=12)


def test_tune_replaces_a_classs_row_rather_than_adding_a_second(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NotificationPreferences`` refuses two rows for one class, and this is why.

    A second row would make the setting's meaning depend on which the reader looks at
    first — so an ``off`` might silently not hold. Substituting rather than appending
    keeps that refusal unreachable from here rather than merely unlikely; the type
    would raise, but at a point where the user has already been told what would
    happen.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(cli.app, ["tune", "--class", "inbox", "--reach", "hold"])

    assert result.exit_code == 0
    written = _written(engine)
    assert [row.notification_class for row in written.reaches].count("inbox") == 1
    assert written.reach_for("inbox") is NotificationReach.HOLD


def test_repeating_quiet_window_replaces_the_whole_set(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one legible reading of a repeated flag against a whole-value write.

    "Add to what is there" and "these are now the windows" cannot both be true of one
    flag, and the second is what a user typing two windows means. It also gives the
    only way to *shrink* the set to more than one member.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(
        cli.app,
        ["tune", "--quiet-window", "23:00-06:30", "--quiet-window", "13:00-14:00"],
    )

    assert result.exit_code == 0
    assert _written(engine).quiet_windows == (
        QuietWindow(start=23 * 60, end=6 * 60 + 30),
        QuietWindow(start=13 * 60, end=14 * 60),
    )


def test_no_quiet_windows_removes_every_one(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeated flag cannot express the empty set, so the empty case needs a name."""
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    asyncio.run(_seed(engine))

    result = CliRunner().invoke(cli.app, ["tune", "--no-quiet-windows"])

    assert result.exit_code == 0
    assert _written(engine).quiet_windows == ()


def test_a_quiet_window_may_cross_midnight_and_is_read_as_local(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: the overnight case is expressed directly, not as two rows.

    And the endpoints carry no zone and cannot: quiet windows are read in
    ``Settings.timezone`` and no second timezone source is introduced, which the
    parse refuses to smuggle one past.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["tune", "--quiet-window", "22:00-07:00"]).exit_code == 0
    assert _written(engine).quiet_windows == (QuietWindow(start=22 * 60, end=7 * 60),)


@pytest.mark.parametrize(
    "spec",
    [
        "22:00",
        "22:00-",
        "not-a-time",
        "22:00-22:00",
        "22:00+01:00-07:00",
        "25:00-07:00",
        # Accepted by `time.fromisoformat` and then **silently truncated** by
        # `minute_of_day`, which is the one input that would otherwise be taken and
        # acted on differently — a window asked for at 22:00:59 and set at 22:00.
        "22:00:59-07:00",
        "22:00-07:00:30",
    ],
)
def test_an_unparseable_quiet_window_is_a_usage_error_before_any_client_is_built(
    spec: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §7: every refusal on this path is a ``ValueError``, which the command's
    ``except (AssistantError, TransportError)`` boundary does not catch.

    Eight shapes, and each is a different refusal rather than a variation on one: no
    separator, an empty endpoint, unparseable text, the equal endpoints
    ``QuietWindow`` declines as unreadable, a zoned endpoint ADR-0130 §6 forbids, an
    hour outside the day, and — on either side — an endpoint finer than the minute
    the setting holds.

    **The last pair is the one a lenient parser would swallow.**
    ``time.fromisoformat`` takes ``22:00:59`` and ``minute_of_day`` truncates it by
    design, so without the grammar check the user asks for one window and is given
    another 59 seconds wide of it, with nothing said. Every one becomes exit code 2,
    and none reaches a hub.

    **"None reaches a hub" is two claims, and the calls list only carries one.** An
    engine with no ``set_notification_preferences`` call recorded is also what a
    command that opened a client, held it, and refused afterwards would leave — so
    the recorded opens are what make this case's own name true (#1970).
    """
    engine = FakeAssistantEngine()
    opened = _wire_recording_opens(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["tune", "--quiet-window", spec])

    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert not [call for call in engine.calls if call[0] == "set_notification_preferences"]
    assert opened == []


def test_tune_sets_the_interruption_budget_and_accepts_zero(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: zero is a legible "never interrupt" rather than a defect.

    So the floor is 0 and not 1 — the opposite of the grant record's ``--limit``,
    whose floor **is** 1. A parse-time refusal copied from that argument would take
    away the one way to say "not right now, at all" without turning every class off
    one by one.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["tune", "--budget", "0"]).exit_code == 0
    assert _written(engine).interruption_budget == 0
    assert "never interrupt" in _flowed(output.getvalue())


@pytest.mark.parametrize("bad", ["-1", "9223372036854775808"])
def test_a_budget_the_type_would_refuse_is_a_usage_error(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NotificationPreferences`` bounds it in ``[0, 2**63)`` with a ``ValidationError``.

    Which is not an :class:`AssistantError`, so it would escape the command's error
    boundary — ``_page_argument``'s case exactly, one field over.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["tune", "--budget", bad])

    assert result.exit_code == 2
    assert not [call for call in engine.calls if call[0] == "set_notification_preferences"]


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        ("class without reach", ["tune", "--class", "upcoming_event"]),
        ("reach without class", ["tune", "--reach", "interrupt"]),
        (
            "both quiet-window forms",
            ["tune", "--quiet-window", "22:00-07:00", "--no-quiet-windows"],
        ),
        ("nothing at all", ["tune"]),
    ],
)
def test_tune_refuses_a_request_it_cannot_read_and_sends_nothing(
    name: str, argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three refusals, each decidable from what was typed, and none costing a round trip.

    ``--class`` and ``--reach`` are one setting: either alone names half of "this
    class may reach me this far", and supplying the other half would be this adapter
    deciding what the user permitted (ADR-0097 §8's posture, ADR-0042 §6's boundary).
    The two quiet-window forms contradict each other, and a precedence rule is a
    decision the user cannot see in what they typed.

    **An invocation naming nothing is refused rather than treated as a no-op**, and
    that one is not cosmetic: ADR-0130 §6 has the write stamp a reconsideration
    instant onto every held record the change could reach, so "write back exactly
    what I read" would re-arm the store with nothing to show for it.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 2, name
    assert result.exception is None or isinstance(result.exception, SystemExit), name
    assert not [call for call in engine.calls if call[0] == "set_notification_preferences"], name


def test_tune_renders_the_settings_the_store_handed_back(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What is shown is what is in force, not what was sent (ADR-0130 §6).

    The two can differ — the surface has no version token and no conflict detection,
    so a racing writer's value is what a later read returns — and echoing the request
    would tell the user their edit stuck when it may not have.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    async def _returning_something_else(
        _self: object, _preferences: NotificationPreferences
    ) -> NotificationPreferences:
        return NotificationPreferences(
            reaches=(ClassReach(notification_class="somebody_elses", reach=NotificationReach.OFF),)
        )

    monkeypatch.setattr(
        type(engine), "set_notification_preferences", _returning_something_else, raising=True
    )

    result = CliRunner().invoke(
        cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"]
    )

    assert result.exit_code == 0
    rendered = _flowed(output.getvalue())
    assert "somebody_elses" in rendered
    assert "upcoming_event" not in rendered


def test_raising_a_class_says_it_reaches_what_is_already_held(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: a setting change re-rules what is already held, and that is the
    whole reason the act works.

    Reach is not a condition time resolves, so a record held at ``hold`` carries no
    due instant and would otherwise sit there until it expired — "the user raises the
    class, agrees to be interrupted, and is not". A surface silent about it invites
    exactly that misreading.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"])

    rendered = _flowed(output.getvalue())
    assert "looked at again" in rendered
    # **Due, not done.** §6 stamps `reconsider_at` and stops — "the existing job picks
    # them up on its next run", and §5 makes that floor a floor. The record is still
    # HOLD as this prints, so a message in the past tense would have the user read the
    # silence that follows as the act having failed.
    assert "due to be" in rendered
    assert "next sweep" in rendered
    # **And the promise is qualified**, because reach is not the only condition (§5):
    # a held record that named no moment it stops mattering re-holds on PERISHABLE,
    # so an unqualified "can now reach you" would mislead in the other direction.
    assert "stays held" in rendered


def test_turning_a_class_off_says_what_it_reaches_and_what_it_does_not(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0130 §6: ``off`` runs the other way and stops at held records.

    It reaches **every** actionable held record of the class, whatever it was held
    for — "never tell me this" is about what is waiting as well as what comes next —
    and it reaches nothing already ruled ``INTERRUPT``, because whether contact
    handed to a channel can be recalled is the delivery seam's question and not this
    ADR's. Both halves are said, because a message giving only the first would read
    as a promise to unsend.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    CliRunner().invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "off"])

    rendered = _flowed(output.getvalue())
    assert "already holding" in rendered
    assert "recalled" in rendered
    # `off` is deferred by the same clause and says so: §6 makes every actionable held
    # record *due* at the instant of the write, and the ruling is the sweep's.
    assert "due to be ruled out" in rendered
    assert "next sweep" in rendered


@pytest.mark.parametrize("reach", ["interrupt", "off"])
def test_restating_the_reach_already_in_force_announces_no_re_arming(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, reach: str
) -> None:
    """ADR-0130 §6 re-arms on a *removed* condition, so a repeat re-arms nothing (#985).

    §6 stamps ``reconsider_at`` on held records whose failed-condition set holds "a
    condition that change could remove". Where the class already reaches that far the
    write removes nothing, so a record held only on ``QUIET_WINDOW`` or ``BUDGET`` sits
    exactly where it was — and the re-arming sentence would be a claim about the store
    that is false. The user who repeats the command is told what is true instead.

    Two invocations rather than a scripted read, so the "already" is one the surface's
    own first write established.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)
    argv = ["tune", "--class", "upcoming_event", "--reach", reach]

    assert CliRunner().invoke(cli.app, argv).exit_code == 0
    first = _flowed(output.getvalue())
    assert "already holding" in first, "the transition still announces the re-arming"

    repeated = len(output.getvalue())
    assert CliRunner().invoke(cli.app, argv).exit_code == 0

    again = _flowed(output.getvalue()[repeated:])
    assert "Tuned." in again, "the write still happens and the settings are still shown"
    assert "already reaching you exactly that far in the settings I read" in again
    # And the claim it replaces is gone rather than merely softened: the two sentences
    # that promise a sweep are the whole of what #985 says must not be printed here.
    assert "due to be" not in again
    assert "next sweep" not in again
    # **And what replaces it claims nothing about the store.** ``current`` is a
    # pre-write read taken under a contract with no version token (#1019), so a second
    # client can write between the read and the write and make any statement about held
    # records wrong. The two things this process knows for certain are what its own read
    # held and what it therefore asked for, and those are the only two it states.
    assert "I am already holding" not in again
    assert "re-considered" not in again


def test_lowering_a_class_to_hold_announces_nothing_either_way(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``hold`` is the silent one, and it is silent whether or not it moved (#985).

    Lowering a class can only *add* a failed condition, never remove one, so §6 re-arms
    nothing on account of it and there is no consequence to announce. Which makes it
    the case that distinguishes "announce what changed" from "announce whether
    anything changed": a surface reporting the second would print a no-op notice here,
    for a write whose reach genuinely did move.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert (
        CliRunner()
        .invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "interrupt"])
        .exit_code
        == 0
    )
    lowered = len(output.getvalue())
    assert (
        CliRunner()
        .invoke(cli.app, ["tune", "--class", "upcoming_event", "--reach", "hold"])
        .exit_code
        == 0
    )

    rendered = _flowed(output.getvalue()[lowered:])
    assert "Tuned." in rendered
    assert "already reaching you" not in rendered
    assert "next sweep" not in rendered


def test_tuning_only_the_budget_says_nothing_about_any_class_reach(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invocation naming no class makes no claim about a class (#985).

    ``--class`` and ``--reach`` are one setting given together or not at all, so a
    budget-only write has no reach to compare against and no sentence to print. Pinned
    because the no-op notice is reached by an *absence* of change, which is exactly the
    condition a call that changed no reach at all also satisfies.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["tune", "--budget", "2"]).exit_code == 0

    rendered = _flowed(output.getvalue())
    assert "Tuned." in rendered
    assert "already reaching you" not in rendered
    assert "next sweep" not in rendered


def test_every_condition_a_ruling_can_name_has_a_phrase() -> None:
    """A ruling explained with a missing clause answers "why not?" with silence.

    Totality is held by ``assert_never`` at type-check time; this pins that the
    phrases are also *distinct*, which the type check cannot see — two conditions
    sharing wording would render a ruling that names the wrong one.
    """
    phrases = [cli._condition_phrase(condition) for condition in NotificationCondition]

    assert len(set(phrases)) == len(list(NotificationCondition))
    assert all(phrase.strip() for phrase in phrases)


def test_every_reach_level_has_a_distinct_phrase() -> None:
    """The same obligation on the settings rendering (ADR-0130 §6)."""
    phrases = [cli._reach_phrase(reach) for reach in NotificationReach]

    assert len(set(phrases)) == len(list(NotificationReach))


#: Rich's SGR colour sequences, which appear in help output only where colour is
#: enabled — which the terminal decides, so it differs between a developer's shell
#: and CI (#983). Stripped before any assertion about help text, together with the
#: panel's box-drawing borders, so what is matched is the *words* rather than a
#: rendering that a `TERM` or a `FORCE_COLOR` can change underneath it.
_SGR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _help_text(rendered: str) -> str:
    """Help output as flowing words: no colour, no borders, no wrapping."""
    return " ".join(_SGR.sub("", rendered).replace("\u2502", " ").split())


def test_the_arming_acts_in_tunes_help_name_what_the_code_actually_calls_them() -> None:
    """#981: PR #977's body recorded ``assistant grant --source calendar``, which does
    not exist, and the next operator copies the record.

    So the record is pinned against the code it describes rather than kept by hand:
    the source name comes from the reader's own declared identity, the class from the
    producer that declares it, and the environment variable from ``Settings``' prefix
    and field name. A rename that leaves the help behind fails here instead of in
    somebody's terminal a year later.

    The imports reach into two subsystems, which a **test** may do and this module
    may not (golden rule 3, and ``lint-imports`` enforces it on ``interfaces``) —
    which is exactly why the help carries literals and this carries the check.
    """
    result = CliRunner().invoke(cli.app, ["tune", "--help"])
    assert result.exit_code == 0
    rendered = _help_text(result.output)

    prefix = Settings.model_config["env_prefix"]
    assert f"{prefix}calendar_upcoming_interval".upper() in rendered
    assert f"assistant grant {CALENDAR_READER_NAME} --scope notify" in rendered
    assert f"assistant tune --class {NOTIFICATION_CLASS} --reach interrupt" in rendered
    # The wrong form is named as wrong, so a reader copying from here cannot take it.
    assert "there is no --source option" in rendered
    # And the duration is given in the form the parser accepts; '15' is refused.
    assert "'PT15M'" in rendered


def test_the_notification_commands_reach_exactly_the_five_operations_adr_0130_ratifies(
    monkeypatch: pytest.MonkeyPatch, output: StringIO
) -> None:
    """ADR-0130 §9 enumerates five, and this surface adds no sixth.

    Driving all five and reading back the engine calls is what makes "thin" checkable
    rather than asserted: a command that grew a second call — a listing that fetched
    the settings to decide a hint, say — would be this adapter composing behaviour
    the contract did not put on one operation, and it would show up here as an extra
    name.

    ``next_notification`` is deliberately absent: it is the *device's* door
    (ADR-0131), polled by a spoke, and putting it on a person's command line would
    let a human consume the delivery a device is owed.
    """
    engine = FakeAssistantEngine()
    _wire(monkeypatch, engine)

    for argv in (
        ["notifications"],
        ["dismiss", "ntf-1"],
        ["forget-notification", "ntf-1"],
        ["notification-settings"],
        ["tune", "--budget", "2"],
    ):
        CliRunner().invoke(cli.app, argv)

    assert [name for name, _ in engine.calls] == [
        "notifications",
        "dismiss_notification",
        "forget_notification",
        "notification_preferences",
        # `tune` is the read-adjust-write the contract prescribes, so it is two.
        "notification_preferences",
        "set_notification_preferences",
    ]


@pytest.mark.integration
def test_a_gateway_whose_port_is_taken_renders_one_line_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """#1436: the bind failure a stranger hits at step 6 of the first-run guide.

    ``asyncio.start_server`` raises a plain ``OSError``, which is neither an
    ``AssistantError`` nor a ``TransportError`` — so it used to escape
    :func:`cli._serve_gateway`'s boundary and reach the terminal as about a hundred
    lines of Rich traceback with the one useful sentence at the bottom. That is the
    failure ADR-0042 §7 exists to prevent: a fault "is rendered, not dumped".

    The gateway is right to raise it raw (``server.py``: "the raw errno
    distinguishes a stay-down fault from a transient one"), so the errno's own text
    is carried into the rendered line rather than replaced by it — which is also
    where the *address* comes from, since this adapter cannot tell which of the two
    listeners refused.
    """
    monkeypatch.setenv("ASSISTANT_DATA_DIR", str(tmp_path))
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = int(held.getsockname()[1])
        monkeypatch.setenv("ASSISTANT_GATEWAY_PORT", str(port))

        result = CliRunner().invoke(cli.app, ["gateway"])

    # Unwrapped before it is read: the console wraps at its width, so a phrase this
    # case is about can arrive with a newline through the middle of it.
    rendered = _flat(output.getvalue())

    assert result.exit_code == 1
    assert "Traceback" not in rendered
    assert f"could not bind port {port}" in rendered
    assert "127.0.0.1" in rendered  # the address, from the errno's own text
    assert "in use" in rendered
    assert "ASSISTANT_GATEWAY_PORT" in rendered
    # The value printed a moment earlier went with the process, and #1436 records
    # that a reader otherwise has no way to tell.
    assert "already dead" in rendered


def test_a_start_failure_that_is_not_a_taken_port_claims_no_port_and_no_remedy() -> None:
    """Every other errno gets the kernel's refusal and nothing made up on top of it.

    The boundary is wide because it has to be — ``run_gateway`` reads the front-end
    bundle off the installed distribution and may stat an overlay agent's socket
    before either listener binds, and the remote listener probes an *ephemeral* port
    before it goes near ``gateway_port``. Adversarial review found on the first round
    that calling all of those "could not bind port 8422" points an operator at the
    wrong subsystem and at a setting that is not the cause. Narrowing the catch takes
    a distinction only ``interfaces/gateway/server.py`` can draw, so the claim is
    narrowed instead: the port and its remedy belong to ``EADDRINUSE`` alone.
    """
    refused = cli._gateway_did_not_start(
        OSError(errno.EIO, "input/output error"), port=8422, probes_an_address=False
    )

    assert "could not start" in str(refused)
    assert "operating system's own refusal" in str(refused)
    assert "8422" not in str(refused)
    assert "ASSISTANT_GATEWAY_PORT" not in str(refused)
    # The half that is true whatever failed: nothing is serving, and the value the
    # gateway printed before it tried to bind went with the process (#1436).
    assert "already dead" in str(refused)


def test_a_taken_address_is_pinned_on_the_port_only_where_nothing_else_could_be_it() -> None:
    """``EADDRINUSE`` is not always ``gateway_port``, and the flat claim is conditional.

    ``start_remote`` probes the configured overlay address by binding an *ephemeral*
    port, and an exhausted ephemeral range raises ``EADDRINUSE`` — on a gateway whose
    loopback listener has already bound ``gateway_port`` successfully, since ``serve``
    binds that one first. Adversarial review found on the second round that the flat
    claim sends that operator to free a port that is not the problem.

    The probe exists only where a remote listener is configured, and that is a fact
    this adapter holds. So without one the flat claim is sound — which is every reader
    of ``docs/guide/first-run.md`` — and with one the message stops naming a single
    port as the cause.
    """
    taken = OSError(errno.EADDRINUSE, "address already in use")

    alone = str(cli._gateway_did_not_start(taken, port=8422, probes_an_address=False))
    with_overlay = str(cli._gateway_did_not_start(taken, port=8422, probes_an_address=True))

    assert "could not bind port 8422" in alone
    assert "ASSISTANT_GATEWAY_REMOTE_ADDRESS" not in alone

    assert "could not bind port 8422" not in with_overlay
    assert "could not bind an address it needed" in with_overlay
    # Both settings named, because either listener could be the one holding it, and
    # the ephemeral case named as the one that is about neither.
    assert "ASSISTANT_GATEWAY_PORT" in with_overlay
    assert "ASSISTANT_GATEWAY_REMOTE_ADDRESS" in with_overlay
    assert "ephemeral port" in with_overlay


def test_a_pre_bind_failure_is_rendered_without_being_called_a_bind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: StringIO
) -> None:
    """The same boundary, driven end to end on the half that is not about the port.

    ``run_gateway`` reads the front-end bundle off the installed distribution before
    either listener starts, so an unreadable installation arrives at this adapter as
    an ``OSError`` indistinguishable from a bind — the case adversarial review raised
    against the first draft. It still has to be rendered rather than dumped, and it
    still has to exit non-zero; what it must not do is send the operator to
    ``ASSISTANT_GATEWAY_PORT``.
    """
    monkeypatch.setenv("ASSISTANT_DATA_DIR", str(tmp_path))

    async def unreadable(**_kwargs: object) -> None:
        """Fail the way a bundle read off a broken installation would."""
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(cli, "run_gateway", unreadable)

    result = CliRunner().invoke(cli.app, ["gateway"])
    rendered = _flat(output.getvalue())

    assert result.exit_code == 1
    assert "Traceback" not in rendered
    assert "could not start" in rendered
    assert "input/output error" in rendered
    assert "ASSISTANT_GATEWAY_PORT" not in rendered

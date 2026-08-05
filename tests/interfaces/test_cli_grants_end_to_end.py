"""The grant commands a user types, against the store their grant lands in (#706).

Every other test of this surface holds one half. ``tests/interfaces/test_cli.py``
drives ``sources``/``grant``/``revoke``/``grants`` against
:class:`~ai_assistant.testing.FakeAssistantEngine`, which records the calls and
believes whatever it is told; ``tests/app/test_composition.py`` runs the real
``build_engine``, the real ``SqliteSourceGrantStore`` and the real gate, but
reaches the engine by calling its methods. **Both pass while the join between them
is broken**, and the join is where ADR-0102 §6's client-side obligations live —
they are unenforceable from the hub's side (ADR-0098 §5), so the only evidence
that they hold is a test that types the command.

**The whole path is real, and the seam substituted is the one the CLI itself
names.** A hub runs on its own event loop in a background thread, holding a real
engine behind a real ``AF_UNIX`` socket; the commands run in this thread and open
their own :class:`~ai_assistant.wire.HubEngineClient` per invocation, exactly as
:func:`~ai_assistant.interfaces.cli._open_engine` does in production —
``check_socket_path``, the client, and the probe all execute unmocked. Only
``load_settings`` and ``configure_logging`` are replaced, which is what points the
process at the temporary deployment; nothing else about the flow is faked.

**The thread is a requirement rather than a convenience.** Each command calls
``asyncio.run``, so the calling thread has no loop of its own to lend the hub, and
the stores serialise their connection behind an :class:`asyncio.Lock` bound to the
first loop that uses it — the engine must therefore live on one loop for the life
of the test while the commands come and go on theirs. Which is also what the
deployment does: the hub is a resident process and the CLI is a visitor
(ADR-0084 §6).

There is no ``ingest`` on the wire, deliberately — ingestion is the hub's
scheduled job (ADR-0093 §6), not a request a client makes — so it is driven on the
hub's own loop, where the scheduler drives it.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import TYPE_CHECKING, Any, TypeVar

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import SourceNotGrantedError
from ai_assistant.interfaces import cli
from ai_assistant.readers import CALENDAR_READER_NAME
from ai_assistant.service.transport import Listener

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterator
    from pathlib import Path

    from ai_assistant.orchestration import Engine

#: Relays whatever the submitted coroutine returns, so a caller keeps its type.
_T = TypeVar("_T")

#: The whole module opens SQLite databases, writes an ``.ics`` and binds a socket.
pytestmark = pytest.mark.integration

#: Long enough that a loaded machine does not fail a test about permissions, short
#: enough that a genuinely wedged hub fails rather than hangs the suite.
_PATIENT = timedelta(seconds=10)


class _Hub:
    """A running hub: a real engine behind a real socket, on its own loop.

    The engine is built *inside* the background loop and every later call to it is
    submitted there, so the one-loop rule its stores depend on holds by
    construction rather than by the caller remembering it.
    """

    def __init__(self, settings: Settings, data_dir: Path) -> None:
        self._settings = settings
        self._data_dir = data_dir
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._engine: Engine | None = None
        self._listener: Listener | None = None

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run one coroutine on the hub's loop and wait for it, from this thread."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(
            timeout=_PATIENT.total_seconds()
        )

    @property
    def engine(self) -> Engine:
        """The engine the hub is serving. Only ever touched through :meth:`run`."""
        assert self._engine is not None
        return self._engine

    def start(self) -> None:
        """Bring the loop, the engine and the door up, in the hub's own order."""
        self._thread.start()

        async def _build() -> Engine:
            return build_engine(self._settings, data_dir=self._data_dir)

        self._engine = self.run(_build())
        self.run(self.engine.start())
        self._listener = Listener(self.engine, self._settings, data_dir=self._data_dir)
        self.run(self._listener.start(build="test"))

    def stop(self) -> None:
        """Close the door, then the engine, then the loop — ADR-0083 §4's order."""
        try:
            if self._listener is not None:
                self.run(self._listener.stop_accepting())
                self.run(self._listener.aclose())
            if self._engine is not None:
                self.run(self._engine.aclose())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=_PATIENT.total_seconds())
            self._loop.close()


def _calendar(directory: Path) -> Path:
    """One ``.ics`` holding a single event an hour from now, and its path.

    Against the real clock for ``tests/app/test_composition.py``'s reason: the
    composition root leaves the reader's clock at its default, and inventing a
    second one here is the second timezone source ADR-0093 §7b refuses. An hour
    ahead is comfortably inside the seven-day default window (§7a).
    """
    begins = datetime.now(UTC) + timedelta(hours=1)
    ends = begins + timedelta(minutes=30)
    stamp = "%Y%m%dT%H%M%SZ"
    path = directory / "calendar.ics"
    path.write_bytes(
        (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ai-assistant tests//EN\r\n"
            "BEGIN:VEVENT\r\nUID:e1\r\nDTSTAMP:20260101T000000Z\r\n"
            f"DTSTART:{begins.strftime(stamp)}\r\nDTEND:{ends.strftime(stamp)}\r\n"
            "SUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()
    )
    return path


@pytest.fixture
def console_output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Hub]:
    """A hub over a real socket, with the CLI in this process pointed at it.

    ``load_settings`` is the substitution rather than ``_open_engine``: replacing
    the latter would skip ``check_socket_path``, the client construction and the
    probe, which are the parts of the path this module exists to exercise.
    """
    settings = Settings(
        data_dir=tmp_path,
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_calendar(tmp_path),
        hub_read_timeout=_PATIENT,
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)

    running = _Hub(settings, tmp_path)
    running.start()
    try:
        yield running
    finally:
        running.stop()


def _flat(rendered: str) -> str:
    """Collapse Rich's line wrapping, so an assertion is about words and not width."""
    return " ".join(rendered.split())


def test_sources_reads_the_real_readers_and_their_real_locations(
    hub: _Hub, console_output: StringIO, tmp_path: Path
) -> None:
    """ADR-0102 §6: the enumeration is the only place ``location`` exists.

    The fake-backed suite asserts the same rendering against a location a test
    handed it. What is new here is that the string came off a reader the
    composition root registered from ``Settings``, travelled the wire, and arrived
    intact — a path on which an encoding or a serialisation fault would present as
    a *missing* source, which the client cannot tell from one that was never
    configured and must not guess at.
    """
    result = CliRunner().invoke(cli.app, ["sources"])

    assert result.exit_code == 0
    rendered = _flat(console_output.getvalue())
    assert CALENDAR_READER_NAME in rendered
    assert str(tmp_path / "calendar.ics") in rendered
    assert "not granted" in rendered


def test_a_typed_grant_is_what_the_ingest_gate_reads(hub: _Hub, console_output: StringIO) -> None:
    """The join, in one test: the command a user types, the store the gate reads.

    Leg 6's exit test asserts this loop over the engine's own methods (#684); this
    asserts it over the *commands*, which is the surface a person has. The
    discriminating step is the ingest between them — it runs on the hub's loop,
    where the scheduler runs it, and it consults ``SqliteSourceGrantStore``. A
    ``grant`` that rendered "Granted" without reaching that store passes every
    assertion in the fake-backed suite and fails here.

    **The revocation half is asserted the same way and for a stronger reason**: it
    is a remedy, and a remedy that is reported as done without being done is worse
    than one that is refused out loud.
    """
    with pytest.raises(SourceNotGrantedError):
        hub.run(hub.engine.ingest())

    granted = CliRunner().invoke(
        cli.app, ["grant", CALENDAR_READER_NAME, "--scope", "facet", "--scope", "ingest", "--yes"]
    )
    assert granted.exit_code == 0
    assert "Granted" in console_output.getvalue()
    assert hub.run(hub.engine.ingest()).stored == 1

    # No `--yes`, and none is accepted: ADR-0102 §4 puts nothing between a user and
    # their remedy, so a revocation that prompted would hang here rather than pass.
    withdrawn = CliRunner().invoke(cli.app, ["revoke", CALENDAR_READER_NAME])
    assert withdrawn.exit_code == 0
    assert "Withdrawn" in console_output.getvalue()
    with pytest.raises(SourceNotGrantedError):
        hub.run(hub.engine.ingest())


def test_revoking_retires_nothing_the_granted_read_produced(
    hub: _Hub, console_output: StringIO
) -> None:
    """ADR-0097 §6: revocation is prospective, and the CLI must not imply otherwise.

    Asserted through ``beliefs`` rather than through the store, because the claim is
    about what a user is told after they revoke. A surface that deleted what it had
    ingested — or a ``revoke`` that read as though it had — would satisfy the
    refusal above and still be wrong, and this is the only page a person would
    check.
    """
    CliRunner().invoke(
        cli.app, ["grant", CALENDAR_READER_NAME, "--scope", "facet", "--scope", "ingest", "--yes"]
    )
    assert hub.run(hub.engine.ingest()).stored == 1
    CliRunner().invoke(cli.app, ["revoke", CALENDAR_READER_NAME])

    console_output.truncate(0)
    console_output.seek(0)
    result = CliRunner().invoke(cli.app, ["beliefs"])

    assert result.exit_code == 0
    rendered = _flat(console_output.getvalue())
    assert "Dentist" in rendered
    assert "attested" in rendered
    # ADR-0102 §9: nothing here may claim the read was stopped retroactively.
    assert "no longer being read" not in rendered


def test_the_grant_record_holds_both_acts_after_the_commands_run(
    hub: _Hub, console_output: StringIO
) -> None:
    """ADR-0102 §3: withdrawing adds a record, and never deletes one.

    Over the durable store rather than a fake's list, which is where the claim
    means anything: "nothing is ever edited or removed from this list" is a
    property of the table the two commands wrote to, and a fake that appends to a
    list satisfies it by having no other option.
    """
    CliRunner().invoke(cli.app, ["grant", CALENDAR_READER_NAME, "--scope", "facet", "--yes"])
    CliRunner().invoke(cli.app, ["revoke", CALENDAR_READER_NAME])

    console_output.truncate(0)
    console_output.seek(0)
    result = CliRunner().invoke(cli.app, ["grants"])

    assert result.exit_code == 0
    rendered = _flat(console_output.getvalue())
    assert "2 record(s)" in rendered
    assert "granted" in rendered
    assert "withdrew" in rendered


def test_a_source_nobody_configured_is_refused_before_anything_is_sent(
    hub: _Hub, console_output: StringIO
) -> None:
    """ADR-0102 §6: "a client that cannot show the user the location does not send grant".

    The hub would refuse this too (§4), which is exactly why the fake-backed suite
    cannot settle it: both a client that asked and a client that did not produce the
    same refusal on the wire (ADR-0098 §5). What is asserted here is that the
    *remedy* rendered is the real enumeration — the list this deployment actually
    holds — rather than an echo of what the user typed.
    """
    result = CliRunner().invoke(cli.app, ["grant", "notes", "--scope", "facet", "--yes"])

    assert result.exit_code == 1
    rendered = _flat(console_output.getvalue())
    assert "cannot offer" in rendered
    assert CALENDAR_READER_NAME in rendered

    # And nothing landed: the record is empty, which is the durable half of "does
    # not send". A client that sent and swallowed the refusal would render the same
    # message as one that never sent.
    assert hub.run(hub.engine.recent_grants()) == ()


def test_a_closed_door_is_reported_rather_than_worked_around(
    tmp_path: Path, console_output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0084 §9: no hub means an instruction, never an in-process fallback.

    Deliberately without the ``hub`` fixture — the point is the socket that is not
    there. This is the one client-side obligation with a *destructive* failure mode
    behind it: a CLI that fell back to building its own engine would open the six
    databases the resident hub owns exclusively (ADR-0083 ruling 4), so "it printed
    an error" and "it did not open memory.db" are separate claims and both are made.
    """
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)

    result = CliRunner().invoke(cli.app, ["sources"])

    assert result.exit_code == 1
    assert "ai-assistant-hub" in _flat(console_output.getvalue())
    with contextlib.suppress(FileNotFoundError):
        assert not list(tmp_path.glob("*.db"))

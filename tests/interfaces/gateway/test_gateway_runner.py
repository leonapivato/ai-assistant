"""Composing the gateway process: mint, disclose, then bind (ADR-0168 §1, §5).

The order is the subject. §5 requires that "a gateway that cannot disclose its
bootstrap value does not start, and reports why", which is only a rule if the
disclosure happens *before* the listener — a gateway that bound first and then
failed to print would be answering a port with a value nobody can present.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from typing import TYPE_CHECKING

import pytest
import structlog
from gateway_ports import free_port
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.interfaces import cli
from ai_assistant.interfaces.gateway import Disclosure, MintAct, Note, run_gateway
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("hermetic_assistant_env")]


#: The act a case names when it is not about how the disposition was installed.
_ACT = MintAct(signal="SIGUSR1", pid=4242)

#: :func:`signal.signal` as it was before any case replaced it. Bound at import so
#: that the fixture restoring a disposition and the case that refused one cannot
#: depend on which of them ``monkeypatch`` unwinds first.
_REAL_SIGNAL = signal.signal


def _disclosure(value: str, *, act: MintAct | None = _ACT) -> Disclosure:
    """One disclosure to hand the CLI's own renderer."""
    return Disclosure(
        value=value,
        origins=("http://127.0.0.1:8422",),
        live_sessions=0,
        max_sessions=8,
        mint_act=act,
    )


async def _is_listening(port: int) -> bool:
    """Whether anything answers on that loopback port."""
    try:
        _, writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def _wait_until_listening(port: int) -> None:
    """Give the bind a bounded number of turns to happen, then give up.

    Bounded rather than open-ended so a gateway that never binds fails the case
    instead of hanging it.
    """
    for _ in range(200):
        if await _is_listening(port):
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"nothing bound {port}")


@contextlib.asynccontextmanager
async def _running(
    settings: Settings, *, disclose: Callable[[Disclosure], None] | None = None
) -> AsyncIterator[tuple[list[Disclosure], list[Note]]]:
    """Run one gateway until the body is done with it, then stop it.

    Args:
        settings: What to compose it from.
        disclose: A discloser of the case's own, where the case is about what
            disclosure does. The default records.

    Yields:
        Every disclosure and every note, in the order they were made.
    """
    disclosed: list[Disclosure] = []
    reported: list[Note] = []
    task = asyncio.create_task(
        run_gateway(
            settings=settings,
            engine=FakeAssistantEngine(),
            disclose=disclose if disclose is not None else disclosed.append,
            report=reported.append,
        )
    )
    try:
        await _wait_until_listening(settings.gateway_port)
        yield disclosed, reported
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _run_until_listening(settings: Settings) -> list[Disclosure]:
    """Start a gateway, wait for its listener, stop it, and return its disclosures."""
    async with _running(settings) as (disclosed, _):
        return list(disclosed)


async def _exchange(port: int, value: str) -> int:
    """Present one bootstrap value at the loopback listener and read the status."""
    body = json.dumps({"bootstrap_value": value}).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(
            f"POST /session HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        return int((await reader.readuntil(b"\r\n")).decode().split(" ")[1])
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


async def _disclosed_within(disclosed: list[Disclosure], count: int) -> None:
    """Give the loop a bounded number of turns to deliver a signal, then give up."""
    for _ in range(200):
        if len(disclosed) >= count:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"only {len(disclosed)} disclosures, wanted {count}")


@pytest.fixture
def restored_mint_signal() -> Iterator[None]:
    """Put ``SIGUSR1``'s disposition back after a case that moved it.

    The degradation cases below drive :func:`signal.signal` for real — that is the
    point of them — and a disposition left as ``SIG_IGN`` would leak into every
    case that ran afterwards in this process.
    """
    before = signal.getsignal(signal.SIGUSR1)
    yield
    if before is not None:
        _REAL_SIGNAL(signal.SIGUSR1, before)


async def test_a_gateway_that_cannot_disclose_its_bootstrap_value_does_not_start() -> None:
    """§5's refusal, and the check that it fires *before* the bind.

    ADR-0182 §1 keeps this clause exactly where it was — it "binds the value minted
    at start and is untouched; it does not reach a later mint".
    """
    settings = Settings(gateway_port=free_port())

    def refuse(_disclosure: Disclosure) -> None:
        msg = "standard output is not writable"
        raise ConfigurationError(msg)

    with pytest.raises(ConfigurationError, match="not writable"):
        await run_gateway(
            settings=settings,
            engine=FakeAssistantEngine(),
            disclose=refuse,
            report=lambda _note: None,
        )

    assert not await _is_listening(settings.gateway_port)


async def test_the_value_is_disclosed_once_with_the_origin_before_the_listener_binds() -> None:
    """What the owner is handed: one value, where to present it, and how to get another.

    ADR-0182 §1 puts the act and this process's id in every disclosure "so that the
    act is discoverable from the disclosure rather than from a document", and §4
    puts the live count and the ceiling there "as **information and not a
    refusal**".
    """
    settings = Settings(gateway_port=free_port())

    disclosed = await _run_until_listening(settings)

    assert len(disclosed) == 1
    one = disclosed[0]
    assert one.origins == (f"http://127.0.0.1:{settings.gateway_port}",)
    assert one.value
    assert one.live_sessions == 0
    assert one.max_sessions == settings.gateway_max_sessions
    assert one.mint_act == MintAct(signal="SIGUSR1", pid=os.getpid())


# --- ADR-0182 §1: the mint act, its ordering, and the two ways it degrades ---


async def test_the_mint_act_discloses_a_further_value_that_admits_a_browser() -> None:
    """§1's act end to end: ``SIGUSR1`` in, a second value out, and it works.

    "A gateway process mints a bootstrap value at start… and mints a further one
    whenever the owner performs the **mint act** at the machine that runs it."
    """
    settings = Settings(gateway_port=free_port())

    async with _running(settings) as (disclosed, reported):
        await _disclosed_within(disclosed, 1)
        # Never signalled unless the disposition is in place: without it the default
        # action for `SIGUSR1` terminates, and the process it would terminate is
        # this test run.
        assert disclosed[0].mint_act == MintAct(signal="SIGUSR1", pid=os.getpid())
        os.kill(os.getpid(), signal.SIGUSR1)
        await _disclosed_within(disclosed, 2)
        admitted = await _exchange(settings.gateway_port, disclosed[1].value)

    assert disclosed[0].value != disclosed[1].value
    assert admitted == 200
    assert reported == []


async def test_the_mint_act_is_not_refused_at_the_ceiling_and_discloses_the_count() -> None:
    """§4: the act "makes **no** decision that depends on the live session count".

    "It is not refused at the ceiling, it mints and discloses exactly as §1 requires
    whatever the count is" — what the owner gets instead is the count "printed
    beside every value, which tells them the same thing without deciding anything".
    """
    settings = Settings(gateway_port=free_port(), gateway_max_sessions=1)

    async with _running(settings) as (disclosed, reported):
        await _disclosed_within(disclosed, 1)
        assert await _exchange(settings.gateway_port, disclosed[0].value) == 200
        os.kill(os.getpid(), signal.SIGUSR1)
        await _disclosed_within(disclosed, 2)

    assert disclosed[1].live_sessions == 1
    assert disclosed[1].max_sessions == 1
    assert disclosed[1].mint_act is not None
    assert reported == []


async def test_a_later_mint_that_cannot_be_disclosed_leaves_the_previous_value_admitting() -> None:
    """§1's order, in the case it was fixed on the third round to survive.

    "A value the gateway cannot disclose is **not minted**: the gateway destroys the
    candidate, reports the failure, leaves any previously outstanding value exactly
    as it was — still outstanding, still on its own clock — and keeps every live
    session and keeps serving."
    """
    settings = Settings(gateway_port=free_port())
    disclosed: list[Disclosure] = []

    def disclose_once(one: Disclosure) -> None:
        if disclosed:
            msg = "standard output is not writable"
            raise ConfigurationError(msg)
        disclosed.append(one)

    async with _running(settings, disclose=disclose_once) as (_, reported):
        await _disclosed_within(disclosed, 1)
        os.kill(os.getpid(), signal.SIGUSR1)
        for _ in range(200):
            if reported:
                break
            await asyncio.sleep(0.01)
        still_listening = await _is_listening(settings.gateway_port)
        admitted = await _exchange(settings.gateway_port, disclosed[0].value)

    assert reported == [Note.MINT_NOT_DISCLOSED]
    assert still_listening
    assert admitted == 200


async def test_no_disclosure_names_the_act_before_the_disposition_is_installed() -> None:
    """§1's ordering against the *disclosure* rather than against the listener.

    "``run_gateway`` mints and discloses before it serves, so a disposition
    installed when the listener starts would leave a window in which the start
    disclosure has already named a process id and a signal the gateway would still
    die of." The reading is taken inside the discloser, which is the only place
    that window is observable.
    """
    settings = Settings(gateway_port=free_port())
    seen: list[tuple[Disclosure, object]] = []

    def watch(one: Disclosure) -> None:
        seen.append((one, signal.getsignal(signal.SIGUSR1)))

    async with _running(settings, disclose=watch):
        await _disclosed_within([one for one, _ in seen], 1)

    assert len(seen) == 1
    disclosure, disposition = seen[0]
    assert disclosure.mint_act is not None
    assert disposition is not signal.SIG_DFL


async def test_sighup_is_not_the_mint_act() -> None:
    """§1 names ``SIGUSR1`` and §8 leaves every other disposition alone.

    ``SIGHUP`` is "not available — ``service/hub.py`` already installs it as the
    ignored signal on ADR-0083 §13's 'a restart is the reload', and a terminal
    hangup delivers it, which would mint a live admission ticket every time an
    owner closed a window". Read rather than delivered: this process's own default
    action for it is to terminate, and the point is that the gateway did not change
    that.
    """
    settings = Settings(gateway_port=free_port())
    before = signal.getsignal(signal.SIGHUP)

    async with _running(settings) as (disclosed, _):
        await _disclosed_within(disclosed, 1)
        during = signal.getsignal(signal.SIGHUP)

    assert during is before
    assert disclosed[0].mint_act is not None
    assert disclosed[0].mint_act.signal == "SIGUSR1"


@pytest.mark.usefixtures("restored_mint_signal")
async def test_a_gateway_that_cannot_install_the_disposition_leaves_the_signal_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1's first degradation, and the reason it is not just "start anyway".

    "The default action for ``SIGUSR1`` is to terminate", so a gateway that only
    reported the act unavailable would leave its own first-run guide naming "a
    process id and a signal, and delivering that signal ends every live session".
    It sets the signal to ignored "if it can", reports which state it is in, and
    names the act in no disclosure.
    """
    loop = asyncio.get_running_loop()

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "no signal handling on this loop"
        raise RuntimeError(msg)

    monkeypatch.setattr(type(loop), "add_signal_handler", refuse)
    settings = Settings(gateway_port=free_port())

    async with _running(settings) as (disclosed, reported):
        await _disclosed_within(disclosed, 1)
        disposition = signal.getsignal(signal.SIGUSR1)
        still_listening = await _is_listening(settings.gateway_port)

    assert reported == [Note.MINT_ACT_IGNORED]
    assert disposition is signal.SIG_IGN
    assert still_listening
    assert disclosed[0].mint_act is None


@pytest.mark.usefixtures("restored_mint_signal")
async def test_a_gateway_that_can_do_neither_names_the_act_in_no_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§1's second degradation: the act is unavailable *and* the signal is unsafe.

    "No lane may read the disclosure clause below as obliging a gateway to advertise
    a signal that would end every live session."
    """
    loop = asyncio.get_running_loop()

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "not here"
        raise RuntimeError(msg)

    def refuse_disposition(number: int, handler: object) -> object:
        """Refuse the mint signal alone, and leave every other one alone.

        Refusing them all would reach the interrupt handler ``asyncio`` restores on
        the way out of its own run, which is a disposition this case is not about.
        """
        if number == signal.SIGUSR1:
            msg = "not here either"
            raise OSError(msg)
        return _REAL_SIGNAL(number, handler)  # type: ignore[arg-type] # a pass-through

    monkeypatch.setattr(type(loop), "add_signal_handler", refuse)
    monkeypatch.setattr(signal, "signal", refuse_disposition)
    settings = Settings(gateway_port=free_port())

    async with _running(settings) as (disclosed, reported):
        await _disclosed_within(disclosed, 1)
        still_listening = await _is_listening(settings.gateway_port)

    assert reported == [Note.MINT_ACT_UNSAFE]
    assert still_listening
    assert disclosed[0].mint_act is None


def test_the_two_unavailable_act_notes_say_which_state_the_signal_is_in(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§1: the report at start "naming which of the two states the signal is in".

    A note that said only "unavailable" would leave an owner unable to tell a
    gateway they may safely signal from one they may not, which is the difference
    between a no-op and every live session ending.
    """
    cli._report_gateway_note(Note.MINT_ACT_IGNORED)
    # Unwrapped before it is read: the console wraps at the terminal's width, so a
    # phrase this case is about can arrive with a newline through the middle of it.
    ignored = " ".join(capsys.readouterr().out.split())
    cli._report_gateway_note(Note.MINT_ACT_UNSAFE)
    unsafe = " ".join(capsys.readouterr().out.split())

    assert "ignored" in ignored
    assert "not stop" in ignored
    assert "Do not send" in unsafe
    assert "end" in unsafe


def test_a_disclosure_names_the_act_the_process_id_and_the_advisory_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """What §1 and §4 put on the owner's screen beside the value."""
    cli._disclose_bootstrap(
        Disclosure(
            value="the-value",
            origins=("http://127.0.0.1:8422",),
            live_sessions=3,
            max_sessions=8,
            mint_act=MintAct(signal="SIGUSR1", pid=4242),
        )
    )

    written = capsys.readouterr().out

    assert "the-value" in written
    assert "3 of 8" in written
    assert "kill -SIGUSR1 4242" in written


def test_a_disclosure_of_a_gateway_without_the_act_names_neither_it_nor_the_pid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§1: such a gateway "names the act in no disclosure".

    The count still travels, because §4 puts it there unconditionally and it is
    information rather than an instruction.
    """
    cli._disclose_bootstrap(_disclosure("the-value", act=None))

    written = capsys.readouterr().out

    assert "the-value" in written
    assert "0 of 8" in written
    assert "SIGUSR1" not in written
    assert "kill" not in written


def test_the_origin_line_names_the_address_without_claiming_a_live_listener(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#1460: the disclosure is written before anything is bound, so it says so.

    ``run_gateway`` mints and discloses before it serves — ADR-0168 §5's "a gateway
    that cannot disclose its bootstrap value does not start" puts the disclosure
    ahead of the bind — so a first line reading "listening on http://…" was a claim
    about a listener that, on a failed bind, never came to exist: the owner read it
    directly above the error saying the port could not be bound.

    Asserted as a negative on the verb *and* a positive on the origin together,
    because either alone is passed by the wrong fix: dropping the address satisfies
    the first and loses what ADR-0182 §1 requires the disclosure to name, and the
    old line satisfies the second.
    """
    cli._disclose_bootstrap(_disclosure("the-value"))

    written = capsys.readouterr().out

    assert "http://127.0.0.1:8422" in written
    assert "listening" not in written
    assert "serving" not in written


def test_the_bootstrap_value_is_written_to_standard_output_and_not_logged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§5: disclosed "on its own standard output… not in a log record".

    The clause "buys less than it looks like, and saying so is better than letting
    a later reader over-read it" — the structured records go to standard output
    too, so what it keeps the value out of is the *structured* stream, "out of
    anything that parses those records, and out of the redaction chain's reach
    where a missed key would be the failure".
    """
    with structlog.testing.capture_logs() as records:
        cli._disclose_bootstrap(_disclosure("the-value"))

    written = capsys.readouterr().out
    assert "the-value" in written
    assert "http://127.0.0.1:8422" in written
    assert not [record for record in records if "the-value" in str(record)]


def test_a_disclosure_that_cannot_be_written_reports_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of §5's clause: it "reports why" rather than failing bare.

    A process whose standard output cannot be written to cannot hand the owner the
    one value that admits a browser, so it does not go on to bind a port nobody
    can use.
    """

    class _Closed:
        """A stream that refuses every write, as a closed one does."""

        def write(self, _text: str) -> int:
            """Refuse."""
            msg = "closed"
            raise OSError(msg)

        def flush(self) -> None:
            """Never reached."""

    monkeypatch.setattr(sys, "stdout", _Closed())

    with pytest.raises(ConfigurationError, match="standard output"):
        cli._disclose_bootstrap(_disclosure("value"))


def test_the_gateway_is_a_subcommand_of_the_assistant_script() -> None:
    """ADR-0168 §1: "a subcommand of the existing ``assistant`` console script, not
    a new one" — the first time ADR-0084 §6's rule has been found not to fire."""
    result = CliRunner().invoke(cli.app, ["gateway", "--help"])

    assert result.exit_code == 0
    assert "browsers" in result.stdout

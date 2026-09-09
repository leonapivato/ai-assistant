"""The layer's harness on the two paths a working browser cannot reach (#1808).

Every case in ``test_browser_page.py`` and ``test_browser_playback.py`` needs a
browser that launched and a context that opened, so two of the harness's own
decisions are unreachable from inside the layer: what a launch refusal *means*
(ADR-0216 §6 — an absent build skips, anything else fails), and what a drive that
never opens leaves behind. A third subject joined them with issue #2139: the wait
the second of those is asserted through, which no case that drives a page exercises
either, because a gateway torn down by a passing drive is released long before
anything asks.

**No browser is taken here, and that is the point rather than a shortcut.** A
module that requested ``gateway_browser`` in order to test what happens when
``gateway_browser`` cannot launch could not be run in the condition it is about;
and a case that drives the page cannot also be the case where opening the page
fails. So the subjects here are the harness's own functions, called directly, over
values a real Playwright hands them.

**This module is deliberately not part of the layer.** It declares neither of
ADR-0216 §3's markers, because it launches nothing and needs no worker of its
own — and ``test_browser_scheduling.py``'s audit, which identifies the layer by
which cases request the browser fixture rather than by which carry its marker,
therefore does not count it. It is beside the layer, not in it.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from typing import TYPE_CHECKING, Any, cast

import browser_drive
import gateway_ports
import pytest
from playwright.async_api import Error as BrowserError

import conftest

if TYPE_CHECKING:
    from pathlib import Path

    from playwright.async_api import Browser

# Playwright's `Browser` is a concrete class rather than a Protocol, so the two
# stand-ins below are cast at the call rather than declared to implement it. What
# `driving()` asks of a browser is one method, and each fake answers exactly that
# one -- a subclass would have to be constructed through a live connection, which
# is the thing these cases exist to do without.


class _RefusingBrowser:
    """A browser that will not open a context at all.

    The realistic failure rather than an invented one: the browser is session-scoped
    and shared by every case in the layer (ADR-0216 §3), so by the time a later case
    asks for a context an earlier one may have crashed it, and Playwright reports
    that with the same ``Error`` class it reports everything with.
    """

    def __init__(self) -> None:
        self.refusal = BrowserError("Target page, context or browser has been closed")

    async def new_context(self, **_: Any) -> Any:
        raise self.refusal


class _UncloseableContext:
    """A context that opens, fails the drive, and then will not close."""

    def __init__(self) -> None:
        self.close_attempted = False

    async def add_init_script(self, script: str) -> None:
        raise BrowserError(f"the frame was detached before {len(script)} bytes ran")

    async def close(self) -> None:
        self.close_attempted = True
        raise BrowserError("the context is already gone")


class _BadlyClosingBrowser:
    """A browser handing out one :class:`_UncloseableContext`."""

    def __init__(self) -> None:
        self.context = _UncloseableContext()

    async def new_context(self, **_: Any) -> Any:
        return self.context


#: How long :func:`_becomes_free` keeps asking. Read the way ``test_gateway_ports.py``
#: reads its own ``_PATIENCE``: long enough that a loaded machine cannot fail a case
#: that is going to pass, and bounded so that a gateway which never lets go fails its
#: case rather than hanging the run.
#:
#: It is generous because it is never actually spent by a passing run -- a released
#: port answers the very first probe -- so the only run that waits it out is one that
#: was going to fail anyway, and there are two such cases.
_RELEASE_PATIENCE = 5.0

#: How long to wait between probes. Short enough that the wait costs a failing case
#: nothing it would notice, and long enough that the loop is not a spin.
_PROBE_INTERVAL = 0.02


def _is_free(port: int) -> bool:
    """Report whether nothing is listening on ``port`` at this instant.

    Binding is the question rather than connecting: a listening socket refuses a
    second ``bind`` even with ``SO_REUSEADDR``, so a bind that succeeds is a port the
    gateway really let go of.

    Args:
        port: The port to probe.

    Returns:
        Whether the bind succeeded.
    """
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


async def _becomes_free(port: int, *, within: float = _RELEASE_PATIENCE) -> bool:
    """Report whether ``port`` is free, waiting a bounded interval for it to become so.

    :func:`_is_free` asks the right question at the wrong moment. What the two cases
    below assert is that the harness *released* the gateway's listening socket -- not
    that the kernel had finished releasing it by the time the next syscall ran, which
    is a different and stronger claim, and one no reader of those cases is making. On
    a loaded runner the two come apart: issue #2139 records both cases failing
    together on CI, on a docs-only pull request whose diff cannot reach the gateway,
    on a tree that had passed the same two cases locally, after five green runs of
    `main`. Sampling once turns that gap into a red gate.

    So the property is asked over an interval rather than at an instant, and the
    interval is bounded rather than open: a gateway that really strands its socket --
    the regression these cases exist for -- still fails, ``within`` seconds later than
    it used to. That delay is the whole price, and only a failing run pays it: a port
    that was released answers the first probe, before anything sleeps, so a passing
    case costs the one ``bind`` it always cost.

    Args:
        port: The port to probe.
        within: How long to keep probing for, in seconds. A parameter rather than a
            constant read straight off the module, so that the case pinning the busy
            answer need not hold a port for the shipped window to state it.

    Returns:
        Whether some probe inside the window found the port free.
    """
    deadline = time.monotonic() + within
    while True:
        if _is_free(port):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_PROBE_INTERVAL)


@pytest.mark.integration
async def test_a_drive_whose_context_never_opens_leaves_no_gateway_listening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused context does not strand the gateway ``driving()`` has already bound.

    ``gateway.start()`` binds a listening socket before there is anything to drive,
    so every statement after it owes that socket a close. Creating the context
    outside the ``try`` did not: the refusal propagated past a ``finally`` that never
    ran, and because the browser is shared, one crashed browser leaked a gateway per
    remaining case (adversarial review, round 7, ``major``).
    """
    port = gateway_ports.free_port()
    monkeypatch.setattr(gateway_ports, "free_port", lambda: port)
    browser = _RefusingBrowser()

    with pytest.raises(BrowserError) as raised:
        async with browser_drive.driving(cast("Browser", browser), tmp_path):
            pytest.fail("the drive must not be entered when its context was refused")

    assert raised.value is browser.refusal
    assert await _becomes_free(port), (
        f"the gateway is still listening on {port} after {_RELEASE_PATIENCE:g}s"
    )


@pytest.mark.integration
async def test_a_context_that_will_not_close_still_releases_the_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raising ``context.close()`` does not skip the gateway's own teardown.

    The same defect one line over from the one above, and the reason the teardown is
    nested rather than a sequence of statements: ``close()`` was the unguarded first
    thing in the ``finally``, so a context that would not close took ``gateway.close()``
    and ``server.close()`` with it. The close is still attempted first and its failure
    still propagates -- what changed is that it no longer costs the run a live port.
    """
    port = gateway_ports.free_port()
    monkeypatch.setattr(gateway_ports, "free_port", lambda: port)
    browser = _BadlyClosingBrowser()

    with pytest.raises(BrowserError):
        async with browser_drive.driving(cast("Browser", browser), tmp_path):
            pytest.fail("the drive must not be entered when its probe was refused")

    assert browser.context.close_attempted
    assert await _becomes_free(port), (
        f"the gateway is still listening on {port} after {_RELEASE_PATIENCE:g}s"
    )


# --- The wait the two cases above lean on (#2139) ---


@pytest.mark.integration
async def test_a_port_released_after_the_first_probe_is_reported_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wait is what answers, which is the whole of issue #2139's fix.

    The port is held when the helper takes its first sample and let go only once
    that sample has answered, so the single probe the two cases above used to take
    reports it busy: this case fails against the version it replaced and passes
    against this one. A wait that never waits is otherwise indistinguishable from
    one that does, because a port free all along is reported free either way.

    **The release rides on the probe rather than on a clock.** Closing the socket
    from a timer would have put a scheduling race into the one module that exists
    to take a scheduling race out: a pause before the first sample releases the port
    early and fails a correct helper, and a pause after it hands the helper a port
    that was already free and pins nothing at all (adversarial review, round 1,
    ``major``). Ordering the release *inside* the first probe's return leaves no
    pause anywhere that can reorder the two.
    """
    port = gateway_ports.free_port()
    holder = socket.socket()
    holder.bind(("127.0.0.1", port))
    holder.listen(1)
    answers: list[bool] = []
    sample = _is_free

    def releasing_probe(asked: int) -> bool:
        answer = sample(asked)
        answers.append(answer)
        if len(answers) == 1:
            holder.close()
        return answer

    # Substituted on this module, which is where :func:`_becomes_free` looks its
    # probe up -- it is a module global, so a case can reach it without a parameter
    # neither production call site would ever pass.
    monkeypatch.setattr(sys.modules[__name__], "_is_free", releasing_probe)
    try:
        assert await _becomes_free(port)
    finally:
        holder.close()
    assert answers == [False, True], "the port was not held across the first probe"


@pytest.mark.integration
async def test_a_port_held_for_the_whole_window_is_reported_busy() -> None:
    """The bound is a bound: a gateway that never let go still fails its case.

    The half that keeps the wait honest. A helper that answered ``True`` on a timeout
    would turn both cases above green against exactly the stranded socket they were
    written to catch, and nothing else in this module would notice.
    """
    port = gateway_ports.free_port()
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        assert not await _becomes_free(port, within=0.05)


@pytest.mark.integration
async def test_a_port_that_is_already_free_is_answered_without_waiting() -> None:
    """The passing path still costs one ``bind`` and no wait at all.

    Asserted by what the event loop did *not* get to run. A coroutine scheduled
    immediately before the call runs at the first point this one yields, so a helper
    that slept -- before its first probe or after it -- lets it run, and one that
    answers straight out of that first bind cannot.

    A window of no length does not reach that claim on its own, which is why it is
    not what this asserts: the probe is ordered before the deadline check, so a
    ``within`` of zero is satisfied by a helper that slept first (adversarial review,
    round 1, ``minor``). Keeping the zero window as well costs nothing and states
    the other half -- that no length of window is needed to answer.
    """
    yielded = False

    async def watch() -> None:
        nonlocal yielded
        yielded = True

    watcher = asyncio.create_task(watch())
    free = await _becomes_free(gateway_ports.free_port(), within=0.0)
    # Read before the loop is given a turn, so that awaiting the watcher below --
    # which is what keeps a pending task out of the run -- cannot set it first.
    slept = yielded
    await watcher

    assert free
    assert not slept, "the helper yielded to the loop on a port that was already free"


def test_an_absent_browser_build_skips_naming_the_command_that_installs_it() -> None:
    """ADR-0216 §6's skip, which no clone that can run the layer can reach.

    §6: "Where the browser build the installed ``playwright`` pins is not present, the
    layer skips, with a message naming the command that installs it." Both halves are
    asserted, because a skip that says only "no browser" leaves the reader to find the
    command themselves -- and the message is the whole of what a fresh clone gets.
    """
    refusal = BrowserError(
        "BrowserType.launch: Executable doesn't exist at "
        "/home/dev/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
    )

    with pytest.raises(pytest.skip.Exception) as skipped:
        conftest.classify_launch_refusal(refusal)

    assert "uv run playwright install chromium" in str(skipped.value)


def test_a_browser_that_is_present_and_will_not_start_is_a_failure() -> None:
    """Everything but an absent build is reported rather than skipped past.

    The half that makes the skip safe. A refused sandbox is a machine that *has* the
    build and cannot run it, and turning that into a skip would let ADR-0216's layer
    go green having executed nothing -- silently, on exactly the runner where it
    matters. The refusal is re-raised unchanged, so what Playwright said is what the
    report carries, and it is the same object: nothing here interprets a refusal it
    does not recognise.

    This case used to be written over a *shared-library* message. It is a sandbox
    refusal now because the shared-library one has an arm of its own below (#2143),
    and a case meant to pin "unrecognised refusals pass straight through" cannot be
    written over a message the code recognises. The property it asserts is unchanged.
    """
    refusal = BrowserError(
        "BrowserType.launch: Failed to launch the browser process.\n"
        "Browser logs:\n"
        "Failed to move to new namespace: "
        "PID namespaces supported, Network namespace supported, "
        "but failed: errno = Operation not permitted"
    )

    with pytest.raises(BrowserError) as raised:
        conftest.classify_launch_refusal(refusal)

    assert raised.value is refusal


#: One realistic refusal per route Playwright reaches a missing system library by,
#: keyed by the substring `tests/conftest.py` matches. The loader form is what issue
#: #2143 observed on a fresh Ubuntu box; the validation form is what Playwright
#: raises itself before it spawns anything, on the ordinary path where its
#: `DEPENDENCIES_VALIDATED` marker has not suppressed the check.
_UNLAUNCHABLE_BUILDS = {
    "the loader kills the spawned browser": (
        "BrowserType.launch: Failed to launch the browser process.\n"
        "Browser logs:\n"
        "/home/dev/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome: "
        "error while loading shared libraries: libasound.so.2: "
        "cannot open shared object file: No such file or directory"
    ),
    "playwright validates the build before spawning it": (
        "BrowserType.launch: Host system is missing dependencies to run browsers.\n"
        "Please install them with the following command:\n"
        "    sudo playwright install-deps\n"
        "Full list of missing libraries:\n"
        "    libasound.so.2"
    ),
}


@pytest.mark.parametrize("refusal_text", _UNLAUNCHABLE_BUILDS.values(), ids=_UNLAUNCHABLE_BUILDS)
def test_an_unlaunchable_build_fails_naming_the_command_that_installs_its_libraries(
    refusal_text: str,
) -> None:
    """Issue #2143: the failure stays a failure, and it names its remedy.

    The gap #2143 records is that a build which is *present and unlaunchable* takes
    neither of ADR-0216 §6's paths legibly: the files exist so the skip does not fire,
    and every case in the layer errors with a loader message that says nothing about
    `playwright install-deps` -- which needs root, so `just setup` cannot have run it.
    A new contributor reads 65 errors and no cause.

    So both halves are asserted, and the first is the one that matters most: this
    **raises**. Routing it to the skip path would widen §6's condition, which that
    section forbids in its own last paragraph ("skipped for any *other* reason" does
    not discharge an anchor), and would let the layer certify a page it never
    executed. Only the message changed.
    """
    refusal = BrowserError(refusal_text)

    with pytest.raises(BrowserError) as raised:
        conftest.classify_launch_refusal(refusal)

    reported = str(raised.value)
    assert "uv run playwright install-deps chromium" in reported
    assert "root" in reported
    assert "just setup" in reported
    # What Playwright said survives, and is reachable both ways: quoted into the new
    # message, and chained, so a traceback shows the original refusal underneath.
    assert refusal_text in reported
    assert raised.value.__cause__ is refusal


def test_an_unlaunchable_build_is_never_skipped_past() -> None:
    """The half of #2143's arm that a `pytest.raises(BrowserError)` cannot state.

    `pytest.skip.Exception` inherits from `BaseException`, not `Exception`, so a
    `classify_launch_refusal` that skipped here would not be caught by the case above
    -- it would propagate and skip *that* case, which pytest reports as a skip rather
    than a failure. The one assertion that catches a regression into the skip path has
    to be written outside `pytest.raises`, so it is.
    """
    for refusal_text in _UNLAUNCHABLE_BUILDS.values():
        try:
            conftest.classify_launch_refusal(BrowserError(refusal_text))
        except pytest.skip.Exception:  # pragma: no cover - the regression this pins
            pytest.fail(f"a present-but-unlaunchable build was skipped past: {refusal_text!r}")
        except BrowserError:
            pass

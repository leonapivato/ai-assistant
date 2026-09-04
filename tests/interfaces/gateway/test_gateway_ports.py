"""The port allocator, on the property issue #1894 is about.

The flake that motivates ``gateway_ports`` is a collision between two *processes* —
two workers of one distributed run, or two runs side by side — so the case that
matters here drives a second interpreter rather than a second call. Its other
claims are checked the same way: by asking the kernel, never by reading the code
back.

Marked ``integration`` because binding loopback sockets is the whole of what they do.
"""

from __future__ import annotations

import contextlib
import os
import queue
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import gateway_ports
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

#: How long to wait for a thing that should happen at once. Long enough that a
#: loaded machine cannot fail the case, and bounded so a thing that never happens
#: fails it rather than hanging the run.
_PATIENCE = 10.0

#: What the child interpreter below prints: the block it claimed for itself and one
#: port out of it. Two integers on one line, so the parent parses no format.
_REPORT = "import gateway_ports;print(gateway_ports.claimed_block(), gateway_ports.free_port())"


class _WatchedGate:
    """A ``_Block``'s own lock, with a caller *finding it held* made observable.

    The case at the bottom of this module has to know that its second caller
    reached the allocator's mutual exclusion, and no clock can tell it that: a
    thread the scheduler has not run yet is indistinguishable from one queued on a
    lock, which is what let the previous version of that case pass vacuously
    (#1915). A lock offers no way to ask who is waiting on it, so the arrival is
    announced from *inside* the wait. The announcement is made only after a
    non-blocking attempt has failed, which it can do for one reason — another
    caller holds the gate — so it means "the gate is held and I am now blocking on
    it" rather than the weaker "I got this far".

    Substituted onto a ``_Block`` the case builds for itself, so no other caller in
    this process allocates through it. It is a bare stand-in for the ``Lock`` that
    class constructs, not a subclass: ``threading.Lock`` is a factory for a type
    that cannot be subclassed.
    """

    def __init__(self, queued: threading.Event) -> None:
        """Wrap a fresh lock.

        Args:
            queued: Set by the first caller that finds this gate already held.
        """
        self._lock = threading.Lock()
        self._queued = queued

    def __enter__(self) -> None:
        """Take the gate, announcing the wait where another caller holds it."""
        if not self._lock.acquire(blocking=False):
            self._queued.set()
            self._lock.acquire()

    def __exit__(self, *_: object) -> None:
        """Release the gate."""
        self._lock.release()


@contextlib.contextmanager
def _listening(port: int) -> Iterator[socket.socket]:
    """Hold a listener on ``port`` for the length of the block.

    Args:
        port: The port to take.

    Yields:
        The listening socket, closed on the way out.
    """
    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        held.bind(("", port))
        held.listen(1)
        yield held
    finally:
        held.close()


def test_two_holders_are_never_handed_the_same_port() -> None:
    """The property every caller here depends on, over a whole block's worth.

    Each port is *held* — bound and listening — before the next is asked for, which
    is what the gateway harnesses do with theirs and the only version of the
    question worth asking. A block's worth of them, so this also pins that the
    allocator walks the whole of one rather than circling a few of its ports.
    """
    with contextlib.ExitStack() as held:
        ports = []
        for _ in range(gateway_ports.BLOCK_SIZE - 1):
            port = gateway_ports.free_port()
            held.enter_context(_listening(port))
            ports.append(port)

    assert len(set(ports)) == len(ports)


def test_a_port_it_hands_out_is_one_a_listener_can_take() -> None:
    """The other half: free is asserted by binding, not by the absence of a refusal."""
    port = gateway_ports.free_port()

    with _listening(port) as taken:
        assert taken.getsockname()[1] == port


def test_the_ports_it_hands_out_sit_below_the_kernels_ephemeral_range() -> None:
    """Nothing the kernel assigns of its own accord can collide with one of these.

    The second half of the fix, and the one the observed failure is consistent with:
    34317 is inside this machine's ephemeral range, so the number handed out as a
    listener's was simultaneously assignable as some client connection's source
    port.
    """
    base = gateway_ports.claimed_block()
    if base is None:
        pytest.skip("no block could be claimed here, so the fallback is an ephemeral probe")

    port = gateway_ports.free_port()

    published = Path("/proc/sys/net/ipv4/ip_local_port_range").read_text(encoding="ascii")
    assert port < int(published.split()[0])
    assert base < port < base + gateway_ports.BLOCK_SIZE


def test_another_process_is_handed_nothing_out_of_this_ones_block() -> None:
    """Issue #1894 itself: two processes allocating at once collide over nothing.

    Driven as a real subprocess because that is the shape of the failure — an xdist
    worker, or a second ``just test-fast`` run, importing this same module while
    this one holds its block. What makes the answer deterministic rather than lucky
    is the claim socket: it is *listening*, so the child's attempt on this process's
    block is refused by the kernel and it walks on to another.
    """
    base = gateway_ports.claimed_block()
    if base is None:
        pytest.skip("no block could be claimed here, so the fallback is an ephemeral probe")
    beside = Path(gateway_ports.__file__).parent

    reported = subprocess.run(  # noqa: S603 — this interpreter, on a literal argument
        [sys.executable, "-c", _REPORT],
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(beside)},
    )

    theirs, port = (int(field) for field in reported.stdout.split())
    assert theirs != base
    assert not base < port < base + gateway_ports.BLOCK_SIZE


def test_a_forked_child_is_handed_nothing_out_of_its_parents_block() -> None:
    """The one door a claim does not close by itself (adversarial review, round 1).

    The case above execs a fresh interpreter, which imports the module and claims
    for itself; a ``fork`` does neither. The child starts holding a *copy* of the
    parent's base, the parent's offset and a descriptor onto the parent's own claim
    socket, so an allocator that trusted what it was holding would hand parent and
    child the same port — this module's collision, arriving by inheritance.

    Three modules of this suite fork already, so this is a property to hold rather
    than a hypothetical to note. The child reports through a pipe and leaves by
    ``os._exit``, so it runs none of the parent's teardown.
    """
    base = gateway_ports.claimed_block()
    if base is None:
        pytest.skip("no block could be claimed here, so the fallback is an ephemeral probe")
    ours = gateway_ports.free_port()
    read_fd, write_fd = os.pipe()

    child = os.fork()
    if child == 0:  # pragma: no cover - the child never reports coverage
        os.close(read_fd)
        with os.fdopen(write_fd, "w") as pipe:
            pipe.write(f"{gateway_ports.claimed_block()} {gateway_ports.free_port()}")
        os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd) as pipe:
        theirs, port = (int(field) for field in pipe.read().split())
    os.waitpid(child, 0)

    assert theirs != base
    assert port != ours
    assert not base < port < base + gateway_ports.BLOCK_SIZE


def test_a_second_caller_waits_for_a_claim_in_progress_rather_than_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim in progress is not the same as no claim (adversarial review, round 2).

    Without the gate, a caller arriving while the first is still inside
    ``_claim_a_block`` takes the ephemeral fallback — the probe-and-release this
    module exists to replace, on a run that had a block all along. The claim is
    recorded against this process *before* it is made, so the second caller does not
    reach ``_claim_a_block`` at all on either allocator: it reads a base of ``None``
    and falls back. Which is to say the defect is not a second claim, it is a second
    caller that gets an answer while there is no answer yet.

    **Driven rather than timed** (#1915). The previous version of this case started
    the second caller and asserted it was still alive a fifth of a second later,
    which a thread the scheduler had not yet run satisfied without ever reaching the
    allocator — vacuously, and on the broken allocator just as well. Nothing here
    waits out a clock for a thing that must not happen. Both of the two things that
    *can* happen are instrumented instead: the gate announces a caller that finds it
    held (:class:`_WatchedGate`), and the fallback records a caller that takes it. One
    of the two arrives on either allocator, and which one it is decides the case.
    """
    claimed = gateway_ports._claim_a_block()
    if claimed is None:
        pytest.skip("no block could be claimed here, so the fallback is an ephemeral probe")
    claim, base = claimed
    probe = gateway_ports._an_ephemeral_port
    inside, may_finish, arrived = threading.Event(), threading.Event(), threading.Event()
    # Appended to from whichever caller gets there, and read once it is over:
    # ``list.append`` is atomic, and every read below happens after the event that
    # guards it has been set.
    claims: list[int] = []
    fallbacks: list[int] = []

    def held() -> tuple[socket.socket, int] | None:
        claims.append(base)
        inside.set()
        may_finish.wait(_PATIENCE)
        return claimed

    def fallen_back() -> int:
        port = probe()
        fallbacks.append(port)
        arrived.set()
        return port

    monkeypatch.setattr(gateway_ports, "_claim_a_block", held)
    monkeypatch.setattr(gateway_ports, "_an_ephemeral_port", fallen_back)
    block = gateway_ports._Block()
    monkeypatch.setattr(block, "_gate", _WatchedGate(arrived))
    drawn: queue.Queue[int] = queue.Queue()
    callers = [threading.Thread(target=lambda: drawn.put(block.next_port())) for _ in range(2)]
    try:
        callers[0].start()
        assert inside.wait(_PATIENCE), "the first caller never reached the claim"
        callers[1].start()
        assert arrived.wait(_PATIENCE), "the second caller never reached the allocator at all"
        assert not fallbacks, "the second caller took the ephemeral fallback mid-claim"
        assert drawn.empty(), "a caller was answered while the claim was still in progress"
        may_finish.set()
        for caller in callers:
            caller.join(_PATIENCE)
            assert not caller.is_alive(), "a caller never finished"
    finally:
        may_finish.set()
        claim.close()

    assert claims == [base], "the block was claimed other than exactly once"
    ports = [drawn.get_nowait(), drawn.get_nowait()]
    assert len(set(ports)) == 2
    assert all(base < port < base + gateway_ports.BLOCK_SIZE for port in ports)

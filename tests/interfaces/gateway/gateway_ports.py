"""One port allocator for every gateway this package binds (issue #1894).

Every module here that starts a gateway needs a TCP port nothing else is using,
and the obvious way to get one has a hole in it. Bind a probe on port 0, read the
number the kernel chose, close the probe, hand the number to the listener: between
the close and the real bind the kernel is free to hand the same number to somebody
else's probe, and under ``just test-fast`` somebody else is one of the other
workers of this same run. That is issue #1894 — twice observed as ``[Errno 98]
address already in use`` in modules whose diffs had nothing to do with ports, once
locally and once on CI, where it costs a rerun of the whole gate. Nothing under
test is wrong when it fires, which is what makes it expensive: it is
indistinguishable at a glance from a gateway that really refused to bind.

**What this module does instead: the process claims a block of ports and allocates
only inside it.** At first use it binds *and listens* on one port — the block's
first — and holds that socket for the rest of the process's life. A listening
socket refuses every other bind of that port, on any address and with any
``SO_REUSEADDR``: that is the property ``test_browser_harness.py`` already leans on
one function over, and it is checked here rather than assumed
(``test_gateway_ports.py``). So the claim is exclusive against every other process
on this machine, and every port handed out afterwards comes from inside the claimed
block. Two workers of one distributed run cannot be handed the same number, and
neither can two concurrent runs — ``just test-fast`` admits three at once. Nor can
a **forked** child, which inherits a claim instead of making one and is therefore
the one door a claim does not close by itself: the claim is remembered against the
process that made it, and a child that finds a stranger's claim lets it go and
claims its own (:meth:`_Block.base`).

**Claimed rather than computed from ``PYTEST_XDIST_WORKER``.** Deriving the block
from the worker id is the shape issue #1894 names third, and it closes the
collision *within* a run while leaving it between runs: two concurrent runs both
have a ``gw0``, and this machine's recipe permits three of them. A claim is decided
by the kernel and needs to know nothing about who is asking, so it covers a serial
run, a distributed one and any number of them side by side with one rule.

**The blocks sit below the kernel's ephemeral range**, which closes a second
collision rather than narrowing it. A probe on port 0 returns an ephemeral port,
and an ephemeral port is also what the kernel assigns as the *source* port of every
loopback connection these tests open — so a number handed out as a listener's was
simultaneously reachable as some client's. The port issue #1894 recorded, 34317,
sits inside this machine's range. Allocating below it takes the kernel's automatic
assignment out of the question.

**Not the shapes issue #1894 names first and second.** Holding the probe socket
open until the real listener takes over cannot work: a bound socket refuses a
second bind even with ``SO_REUSEADDR`` (again ``test_browser_harness.py``), so the
listener would have to be handed the probe's own descriptor, and nothing in
``Gateway.start()`` accepts one. Binding on port 0 for real and reading the port
back off the listener needs two things from ``src/`` that are not there:
``Settings.gateway_port`` is refused below 1024 (ADR-0168 §8), and ``Gateway``
computes the authority its ``Host`` check compares against from ``gateway_port`` at
construction, so a gateway bound on 0 would refuse every request to the port it
actually took. Both are changes to the gateway, not to its tests.

**What is left.** A foreign program on this machine can still bind one of our
block's ports in the window between this module's probe and the listener's bind.
Nothing inside a test package can close that. What a test package can close is
every collision this suite causes itself, and that is what is closed here.
"""

from __future__ import annotations

import atexit
import os
import socket
from pathlib import Path
from typing import Final

#: Where Linux publishes the range it draws ephemeral ports from — the ports it
#: assigns to a ``bind`` on port 0 and to the source of an outgoing connection.
#: Read rather than assumed, because a machine that has moved it would otherwise
#: get blocks *inside* its own ephemeral range and the second collision back.
_EPHEMERAL_RANGE: Final = Path("/proc/sys/net/ipv4/ip_local_port_range")

#: The bottom of that range where the file above cannot be read — Linux's own
#: default, and the value this project's machines and CI runners publish.
_DEFAULT_EPHEMERAL_LOW: Final = 32768

#: How far below the ephemeral range the blocks reach. Eight thousand ports is a
#: hundred and twenty-eight blocks, which is more processes than any plausible
#: number of concurrent runs times their workers.
_REGION_SPAN: Final = 8192

#: The lowest port a block may start at, so that a machine with an unusually low
#: ephemeral range gets no blocks rather than blocks among the registered services.
_LOWEST_BLOCK_PORT: Final = 10000

#: Ports per block: one for the claim and sixty-three to hand out. Cycled rather
#: than reused immediately, so a port comes back only after the sixty-two others
#: have — which keeps a just-released listener's ``TIME_WAIT`` out of the way.
#: Public because ``test_gateway_ports.py`` asserts over a whole block.
BLOCK_SIZE: Final = 64


def _ephemeral_low() -> int:
    """The lowest port the kernel assigns automatically.

    Returns:
        The published bottom of the ephemeral range, or Linux's default where this
        machine publishes nothing readable there.
    """
    try:
        published = _EPHEMERAL_RANGE.read_text(encoding="ascii").split()
    except OSError:
        return _DEFAULT_EPHEMERAL_LOW
    try:
        return int(published[0])
    except IndexError, ValueError:
        return _DEFAULT_EPHEMERAL_LOW


def _region() -> tuple[int, int]:
    """The half-open span of ports the blocks are cut from.

    Returns:
        The first port of the span and the first port past it. The span is empty
        where the ephemeral range starts too low to leave room below it.
    """
    past = _ephemeral_low()
    return max(_LOWEST_BLOCK_PORT, past - _REGION_SPAN), past


def _is_bindable(port: int) -> bool:
    """Whether a listener could take ``port`` on every local address as this returns.

    Asked with ``SO_REUSEADDR`` set, because that is what ``asyncio.start_server``
    sets on POSIX and the question worth asking is the one the real bind will ask:
    a port carrying nothing but a closed connection's ``TIME_WAIT`` is one a server
    can still take, and skipping it would only shrink the block for no reason.

    Asked on the wildcard address rather than on loopback, because
    ``test_gateway_remote_listener.py`` binds one port on two addresses at once and
    needs it free on both. A wildcard probe answers the stronger question, so one
    helper serves every caller here.

    Args:
        port: The port to ask about.

    Returns:
        Whether the bind succeeded.
    """
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("", port))
        except OSError:
            return False
    return True


def _claim_a_block() -> tuple[socket.socket, int] | None:
    """Take one block of ports for this process, for as long as it runs.

    The search starts at a block chosen from this process's id, so that the workers
    of a distributed run spread out instead of contending for the first block one
    after another; the linear walk from there is what actually decides, so a shared
    starting point would cost time and never correctness.

    Returns:
        The held claim socket and the first port of the block it claims, or ``None``
        where no block could be claimed at all — an ephemeral range starting too
        low to leave a region, or every block on this machine already claimed.
    """
    start, past = _region()
    blocks = (past - start) // BLOCK_SIZE
    if blocks <= 0:
        return None
    first = os.getpid() % blocks
    for step in range(blocks):
        base = start + ((first + step) % blocks) * BLOCK_SIZE
        claim = socket.socket()
        try:
            claim.bind(("", base))
            # Listening, not merely bound: a listening socket is refused to every
            # other bind of the port whatever options that bind carries, which is
            # what makes the claim exclusive rather than merely likely. Nothing
            # ever connects to it, so the backlog is never used.
            claim.listen(1)
        except OSError:
            claim.close()
            continue
        atexit.register(claim.close)
        return claim, base
    return None


def _an_ephemeral_port() -> int:
    """Probe on port 0 and release it — the shape this module exists to replace.

    Kept as the fallback for a machine no block could be claimed on, because a
    gateway package that could not bind at all would be worse than one carrying
    issue #1894's window. It is the fallback and not the rule, and
    :func:`claimed_block` reports which of the two a run is on.

    Returns:
        A port that was free a moment ago.
    """
    with socket.socket() as probe:
        probe.bind(("", 0))
        return int(probe.getsockname()[1])


class _Block:
    """The block this process claimed, and where in it the next port comes from."""

    def __init__(self) -> None:
        self._claim: socket.socket | None = None
        self._base: int | None = None
        self._claimed_by: int | None = None
        self._offset = 0

    @property
    def base(self) -> int | None:
        """The first port of this process's block, claiming one if none is held yet.

        **Keyed on the process id, so a fork does not inherit a claim.** A child of
        ``os.fork()`` starts with a copy of everything below — the same base, the
        same offset, and a descriptor onto the *parent's* claim socket — and would
        therefore hand out the parent's next port as if it were its own. That is the
        collision this module exists to remove, arriving through the one door a
        claim does not close, and this suite already forks in three modules. So the
        claim is remembered against the process that made it: a mismatch means this
        process inherited it rather than made it, and it claims afresh.
        """
        here = os.getpid()
        if self._claimed_by != here:
            self._let_go_of_what_was_inherited()
            self._claimed_by = here
            claimed = _claim_a_block()
            if claimed is not None:
                self._claim, self._base = claimed
        return self._base

    def _let_go_of_what_was_inherited(self) -> None:
        """Drop a parent's claim, so this process starts from nothing held.

        Closing the descriptor releases *this* process's copy and leaves the parent
        listening on its own, which is what keeps the block the parent claimed
        unavailable to the fresh claim made a moment later.
        """
        if self._claim is not None:
            self._claim.close()
        self._claim = None
        self._base = None
        self._offset = 0

    def next_port(self) -> int:
        """The next free port of the block, or an ephemeral one where there is none.

        Returns:
            A port free on every local address as this returns.

        Raises:
            RuntimeError: If every port of the claimed block is taken, which would
                mean something outside this process has bound the whole block.
        """
        base = self.base
        if base is None:
            return _an_ephemeral_port()
        span = BLOCK_SIZE - 1
        for _ in range(span):
            candidate = base + 1 + self._offset % span
            self._offset = (self._offset + 1) % span
            if _is_bindable(candidate):
                return candidate
        msg = (
            f"every port of this process's block ({base + 1}-{base + span}) is bound; "
            "something outside this test run is holding them"
        )
        raise RuntimeError(msg)


_THIS_PROCESS = _Block()


def free_port() -> int:
    """A TCP port free on every local address, from this process's own block.

    The replacement for the probe-and-release helper each module here used to carry
    its own copy of. Two callers holding what they were handed are never handed the
    same port, and neither is a caller in another process — see the module
    docstring for what makes that true and what it leaves open.

    Returns:
        The port number, free as this returns.
    """
    return _THIS_PROCESS.next_port()


def claimed_block() -> int | None:
    """The first port of this process's block, claiming one if none is held yet.

    Exposed for ``test_gateway_ports.py``, which has no other way to ask whether the
    exclusivity this module is for is actually in force on the machine it is running
    on, or whether the run has fallen back to an ephemeral probe.

    Returns:
        The block's first port, or ``None`` where no block could be claimed.
    """
    return _THIS_PROCESS.base

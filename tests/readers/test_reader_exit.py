"""A blocked read does not keep the process alive (ADR-0093 §7).

The obligation is the **exit**, and the mechanism is named in the ADR only because
the obvious one fails it. "Owned, and not the default executor" is not sufficient
and an earlier draft stopped there: a dedicated ``ThreadPoolExecutor`` satisfies
both words and still hangs, because ``concurrent.futures.thread`` registers an
interpreter-exit hook that joins its workers — so ``serve()`` returns,
``asyncio.run`` finishes, and the process then waits on the same stalled syscall
one layer lower down. That is precisely the outcome ADR-0083 §4 builds a two-phase
shutdown to avoid, reached around it rather than through it, and the operator's
only recourse is ``SIGKILL``.

**The subprocess is not incidental**, and §7b says why an earlier draft's
in-process version was wrong: it asserted that the worker is released after
shutdown completes, "which no exited process can be around to observe. Only an
external observer can watch a process die."

So this case watches from outside: the child announces that its read is blocked,
lets its event loop finish, and must terminate — while a marker file the blocking
call would write *if it ever returned* stays absent.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

#: Far longer than the child needs and far shorter than a suite should wait on a
#: process that is never going to exit. A failure here is a hang, so it has to be
#: reported as a failure rather than as a suite that stops.
_EXIT_BUDGET_SECONDS = 30

_CHILD = textwrap.dedent(
    """
    import asyncio
    import sys
    import threading
    from datetime import timedelta
    from pathlib import Path

    import ai_assistant.readers.calendar as calendar_module

    returned_marker = Path(sys.argv[1])
    entered = threading.Event()
    never = threading.Event()


    def blocked(path, *, max_bytes):
        # Stands in for a read on a stalled NFS or FUSE mount: a perfectly
        # ordinary regular file whose every syscall hangs. The kernel would not
        # give this thread back, so neither does the test.
        entered.set()
        never.wait()
        returned_marker.write_text("the worker returned")
        return b""


    calendar_module.acquire = blocked


    async def serve():
        reader = calendar_module.CalendarReader(
            Path("/nonexistent/calendar.ics"), read_timeout=timedelta(hours=1)
        )
        asyncio.ensure_future(reader.read())
        while not entered.is_set():
            await asyncio.sleep(0.01)
        print("BLOCKED", flush=True)
        # The hub's `serve()` coroutine returning *is* the shutdown.


    asyncio.run(serve())
    print("EXITED", flush=True)
    """
)


@pytest.mark.integration
def test_a_hub_shut_down_mid_read_exits_while_the_read_is_still_blocked(
    tmp_path: Path,
) -> None:
    """The child exits within a bounded time, and its worker never returned."""
    script = tmp_path / "child.py"
    script.write_text(_CHILD)
    marker = tmp_path / "worker-returned"

    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 — this interpreter, a file this test wrote
            [sys.executable, str(script), str(marker)],
            capture_output=True,
            text=True,
            timeout=_EXIT_BUDGET_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:  # pragma: no cover - only on a regression
        msg = (
            "the process did not exit while a read was blocked; a joining worker "
            "leaves SIGKILL as the operator's only recourse (ADR-0093 §7)"
        )
        raise AssertionError(msg) from expired
    elapsed = time.monotonic() - started

    assert completed.returncode == 0, completed.stderr
    assert "BLOCKED" in completed.stdout, completed.stderr
    assert "EXITED" in completed.stdout, completed.stderr
    assert elapsed < _EXIT_BUDGET_SECONDS
    # The whole point: it exited *with the read still blocked*, not because the
    # read happened to finish first.
    assert not marker.exists()

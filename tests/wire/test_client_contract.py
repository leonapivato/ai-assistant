"""The wire client passes the shared AssistantEngine suite, over a real socket.

**This is the deliverable that makes substitutability a fact rather than a
design.** ADR-0084 §5 promotes the engine surface to a Protocol on the ground that
a client satisfying it over a transport *is* the second implementation ADR-0042
§1's revisit trigger named, and §4 makes the conformance suite "what holds them to
it". Three implementations now run the same file: the concrete ``Engine``
(``tests/orchestration/test_engine_contract.py``), the canonical fake
(``test_fake_engine.py``), and this one.

**Nothing here is stubbed between the two halves.** Each subject is a client
talking to a real ``AF_UNIX`` socket, served by :func:`serve_connection` against a
:class:`~ai_assistant.testing.FakeAssistantEngine` in the same process — so every
call in the suite is really encoded to ADR-0087's bytes, framed, read back with a
length prefix, dispatched by name, and validated into its declared return type.
A double in the middle would let the suite pass over a path the wire never takes,
which is the failure the suite exists to catch in the direction nobody looks.

**The suite is imported rather than copied**, which is the whole point of a
*shared* suite: a clause either binds every implementation or binds none. It lives
beside the Protocol's first implementation, at
``tests/orchestration/assistant_engine_contract.py``, and pytest puts only a test
module's *own* directory on the path — hence the one line of ``sys.path`` below.
The tidier fix is to move the suite to ``tests/``, which ``tests/conftest.py``
already puts on the path, and it is filed rather than taken here: it would edit
``tests/orchestration/**`` and break two existing bindings while another lane holds
that directory.

**The size clause is held in both directions**, which is the one ADR-0084 §4
insisted on: an oversized *argument* is refused in the client, locally, against the
limit the hub published in the handshake, and an oversized *result* comes back as
the hub's own :class:`~ai_assistant.core.errors.OversizedValueError`, reconstructed
through ADR-0085 §10a's error frame with its ``limit``, ``size`` and ``field``
intact. ``tiny_engine`` below is what reaches both: the hub's frame size is set so
that ``hub_max_frame_bytes - 512`` is exactly the suite's own tiny limit, so the
number the client enforces is the number the backing engine enforces, by
derivation rather than by two constants agreeing.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import timedelta
from pathlib import Path as _Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "orchestration"))

from assistant_engine_contract import (
    _SOURCE,
    _TINY_LIMIT,
    AssistantEngineContract,
)

from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import (
    ENVELOPE_RESERVE_BYTES,
    HubEngineClient,
    serve_connection,
)
from ai_assistant.wire.server import ConnectionLimits

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.protocols import AssistantEngine

#: Generous, because nothing in the suite is about a deadline and a tight one
#: would turn a slow machine into a flaky protocol failure.
_PATIENT = timedelta(seconds=30)

#: The frame size whose contract limit is exactly the suite's tiny limit. Derived
#: rather than written twice, so the hub and the client cannot drift apart here in
#: the one test that is about them agreeing.
_TINY_FRAME = _TINY_LIMIT + ENVELOPE_RESERVE_BYTES

#: The ordinary frame size: ADR-0084 §3's 16 MiB default.
_ORDINARY_FRAME = 16 * 1024 * 1024


class ServedHub:
    """A hub on a real socket, and the clients that talk to it.

    A small harness rather than a fixture body, because three fixtures below need
    the same three things — bind, serve, tear down — and a hub that outlived its
    test would leave a socket behind for the next one to connect to.
    """

    def __init__(self, backing: AssistantEngine, path: Path, *, max_frame_bytes: int) -> None:
        self.backing = backing
        self.path = path
        self._limits = ConnectionLimits(
            max_frame_bytes=max_frame_bytes, read_timeout=_PATIENT, build="test"
        )
        self._server: asyncio.Server | None = None

    async def start(self) -> HubEngineClient:
        """Bind and begin accepting, and return a client pointed at the socket."""
        self._server = await asyncio.start_unix_server(self._serve, path=str(self.path))
        return HubEngineClient(self.path, read_timeout=_PATIENT)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(self.backing, reader, writer, limits=self._limits)

    async def aclose(self) -> None:
        """Stop accepting and remove the socket."""
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
        self.path.unlink(missing_ok=True)


@contextlib.asynccontextmanager
async def serving(
    backing: AssistantEngine, path: Path, *, max_frame_bytes: int = _ORDINARY_FRAME
) -> AsyncIterator[HubEngineClient]:
    """Run one hub for the body of a ``with``, yielding a client of it."""
    hub = ServedHub(backing, path, max_frame_bytes=max_frame_bytes)
    try:
        yield await hub.start()
    finally:
        await hub.aclose()


class TestHubEngineClientContract(AssistantEngineContract):
    """The client, held to the shared contract over a real socket."""

    @pytest.fixture
    async def engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub at the ordinary contract limit."""
        async with serving(FakeAssistantEngine(), tmp_path / "hub.sock") as client:
            yield client

    @pytest.fixture
    async def tiny_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub whose published limit is small enough to reach.

        **The backing engine is given the same limit the hub publishes**, which is
        what makes this subject test the clause rather than half of it: the client
        refuses an oversized argument locally against the number it was told, and
        the engine refuses an oversized result against the same number one frame
        further in. If the two were configured independently the suite could pass
        with the client enforcing nothing.
        """
        backing = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        async with serving(backing, tmp_path / "hub.sock", max_frame_bytes=_TINY_FRAME) as client:
            yield client

    @pytest.fixture
    async def granting_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub holding a single grantable source with a location.

        **This is the subject that makes ADR-0102 §2's argument real.** The suite's
        whitespace clause — a ``source`` differing from a held reader's name only by
        surrounding whitespace is refused rather than matched — is the one clause
        the wire implementation alone could have failed, because ``wire/surface.py``
        validates each argument against the Protocol's own annotation *before*
        ``wire/server.py`` dispatches. Had ``source`` been annotated ``Identifier``,
        that validation would have stripped the value and the hub would have matched
        it, while the in-process engine refused the same call.
        """
        backing = FakeAssistantEngine()
        backing.hold_source(_SOURCE, location="/srv/calendar.ics")
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield client

    @pytest.fixture
    async def parked_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub holding a single answerable park.

        The park lives in the *hub's* engine and the token crosses the wire, which
        is ADR-0084 §7's whole subject: the client is stateless with respect to
        tokens, so the one it resumes with is the one ``pending_confirmations()``
        just handed it over a connection that has since closed.
        """
        backing = FakeAssistantEngine()
        backing.park("h-1")
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield client

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
    _DECISION_LIMIT,
    _INVOCATION_LIMIT,
    _NOT_CANONICAL,
    _OVERFULL_DECISIONS,
    _OVERFULL_GRANTS,
    _OVERFULL_READS,
    _SOURCE,
    _TINY_LIMIT,
    _UNHELD_SOURCE,
    _UNWRITABLE_LOCATION,
    _UNWRITABLE_SOURCE,
    AssistantEngineContract,
    ConnectionSubject,
    DecisionSubject,
    InvocationSubject,
    ReadSubject,
    backwards_clock,
    overfull_invocation_rows,
    seeded_invocation_trail,
    seeded_read_trail,
    seeded_trail,
)

from ai_assistant.core.types import (
    BoundAccount,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    GrantScope,
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


def _binding() -> EgressBinding:
    """One whole egress binding, for a park the shared suite's ADR-0178 clauses reach.

    A destination-bearing occurrence and a description-only one, so the derived set
    has a recipient member rather than falling back to the account. Built here
    rather than shared with the in-process suite's copy: this one has to survive
    the *frame* as well as the reduction, which is the thing this subject adds.
    """
    return EgressBinding(
        spans=(
            EgressSpan(
                argument="body",
                provenance=DiscloserProvenance.USER_AUTHORED,
                extent=5,
            ),
            EgressSpan(
                argument="to",
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=17,
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="Alice@Example.ORG",
                    canonical="alice@example.org",
                ),
            ),
        ),
        account=BoundAccount(identity="work@example.com", reference="conn-0001"),
        transport_endpoint="test://endpoint/one",
        planned_with_external_content=False,
    )


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
    async def connections(self, tmp_path: Path) -> AsyncIterator[ConnectionSubject]:
        """A client of a hub, and the provisioner on the hub's side of the socket.

        **This is the binding the connection clauses were written for.** Two of
        them can only fail here: the identity's byte-for-byte crossing, which an
        ``Identifier`` annotation would have silently stripped in
        ``wire/surface.py``'s argument validation before ``wire/server.py``
        dispatched; and the local refusals, which the client owes in its own right
        so that no credential is put on a socket for a call the hub would refuse
        (ADR-0085 §9, ADR-0151 §5).

        The provisioner read here is the hub's, reached from the test process
        rather than over the wire — which is the point: a negative control has to
        be read from where the writes would have landed.
        """
        backing = FakeAssistantEngine()
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield ConnectionSubject(engine=client, provisioner=backing.connections)

    @pytest.fixture
    async def tiny_connections(self, tmp_path: Path) -> AsyncIterator[ConnectionSubject]:
        """A client of a hub whose published limit is small enough to reach.

        **The binding that proves the other two are enforcing anything.** This one
        really serialises, so it would refuse an oversized credential even if the
        clause were never implemented in-process — which is exactly why the clause
        is in the shared suite rather than here: what it catches is the *other* two
        agreeing with each other and not with this one.
        """
        backing = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        async with serving(backing, tmp_path / "hub.sock", max_frame_bytes=_TINY_FRAME) as client:
            yield ConnectionSubject(engine=client, provisioner=backing.connections)

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
    async def defective_source_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub holding a grantable source and two that are not.

        **This binding is why the clause belongs in the shared suite**: the wire is
        where an unshowable location would otherwise surface as a dropped socket
        rather than a typed answer, since ``wire/server.py`` turns an
        ``AssistantError`` into an error frame and lets anything else close the
        connection. Hub-side filtering is what keeps the value out of the encoder,
        and only a bound client proves it.
        """
        backing = FakeAssistantEngine()
        backing.hold_source(_SOURCE, location="/srv/calendar.ics")
        backing.hold_source(_UNWRITABLE_SOURCE, location=_UNWRITABLE_LOCATION)
        backing.hold_source(_NOT_CANONICAL, location="/srv/mail")
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield client

    @pytest.fixture
    async def back_dated_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub whose clock steps **backwards** on every reading.

        The clock lives entirely hub-side, which is ADR-0102 §5's whole point — a
        client supplies no ``decided_at`` — so this fixture arranges the state on the
        backing engine and the client observes it through the wire like any other.
        """
        backing = FakeAssistantEngine()
        backing.hold_source(_SOURCE, location="/srv/calendar.ics")
        backing.grant_clock = backwards_clock()
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield client

    @pytest.fixture
    async def disagreeing_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub whose two grant answers disagree (ADR-0139 §1).

        Arranged entirely hub-side, as it arises: the store is the hub's and a
        client has no way to put a grant in it for a source no reader declares.
        What the binding proves is that the disagreement survives the wire — that
        ``standing_grants`` carries a record whose source is absent from the
        enumeration, rather than being filtered on its way out.
        """
        backing = FakeAssistantEngine()
        backing.hold_source(_SOURCE, location="/srv/calendar.ics")
        backing.hold_grant(_UNHELD_SOURCE, scope=(GrantScope.INGEST,))
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield client

    @pytest.fixture
    async def overfull_granting_engine(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a tiny-framed hub whose live set does not fit the frame.

        **ADR-0139 §8 requires this case against the wire implementation as well**,
        and this is why: the refusal has to arrive as a typed error frame a client
        renders as a refusal. An unmeasured result here would be a set too large for
        the frame, which the transport turns into a dropped connection rather than
        into an answer — a client left unable to distinguish "too big to say" from
        "the hub went away", which is the same failure the no-paging clause refuses
        one layer down.
        """
        backing = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        for index in range(_OVERFULL_GRANTS):
            backing.hold_grant(f"source-{index}", scope=(GrantScope.FACET,))
        async with serving(backing, tmp_path / "hub.sock", max_frame_bytes=_TINY_FRAME) as client:
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
        backing.park("h-1", egress=_binding())
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield client

    @pytest.fixture
    async def decisions(self, tmp_path: Path) -> AsyncIterator[DecisionSubject]:
        """A client of a hub whose engine reads a seeded trail, and that trail.

        Arranged entirely hub-side, as it arises: the trail is the hub's and a
        client has no way to put a ruling in one — ADR-0186 §4 refuses a promoted
        ``record`` precisely so that it cannot. The trail is read from the test
        process rather than over the wire, which is what makes it a negative
        control: §3's refusals must happen **before a frame is sent**, and only a
        log read from where the read would have landed says so.
        """
        trail = await seeded_trail()
        backing = FakeAssistantEngine()
        backing.trail = trail
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield DecisionSubject(engine=client, trail=trail)

    @pytest.fixture
    async def unordered_decisions(self, tmp_path: Path) -> AsyncIterator[DecisionSubject]:
        """A client of a hub whose trail hands back an unordered ``export``.

        **What this binding proves is that the sort happens hub-side**, where
        ADR-0186 §2 puts it, rather than in whichever implementation the suite
        happened to reach first. A client that sorted a relayed export of its own
        would pass the in-process bindings' version of this case and would still be
        wrong: the artifact a second consumer of the same hub reads is the one the
        engine produced.
        """
        trail = await seeded_trail(ordered_export=False)
        backing = FakeAssistantEngine()
        backing.trail = trail
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield DecisionSubject(engine=client, trail=trail)

    @pytest.fixture
    async def overfull_decisions(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub whose published limit the whole trail exceeds.

        **The binding that proves the other two are enforcing anything.** This one
        really serialises, so the frame is the bound rather than an in-process
        measurement of a payload nobody will encode — and the hub publishes the same
        number the backing engine measures against, so the refusal the client
        renders is the refusal the engine made.
        """
        trail = await seeded_trail(
            rows=tuple((f"d-{index}", index) for index in range(_OVERFULL_DECISIONS))
        )
        backing = FakeAssistantEngine(max_payload_bytes=_DECISION_LIMIT)
        backing.trail = trail
        async with serving(
            backing,
            tmp_path / "hub.sock",
            max_frame_bytes=_DECISION_LIMIT + ENVELOPE_RESERVE_BYTES,
        ) as client:
            yield client

    @pytest.fixture
    async def reads(self, tmp_path: Path) -> AsyncIterator[ReadSubject]:
        """A client of a hub whose engine reads a seeded read trail, and that trail.

        Arranged hub-side on :attr:`decisions`' terms, and here it is not even a
        refusal that keeps a client out of the store: ADR-0186 §10's pair is two
        reads and no writer, because a read row is authored on the seam that gated
        it (ADR-0185 §5). The trail is read from the test process rather than over
        the wire, which is what makes it a negative control: §3's refusals must
        happen **before a frame is sent**, and only a log read from where the read
        would have landed says so.
        """
        trail = await seeded_read_trail()
        backing = FakeAssistantEngine()
        backing.reads = trail
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield ReadSubject(engine=client, trail=trail)

    @pytest.fixture
    async def invocations(self, tmp_path: Path) -> AsyncIterator[InvocationSubject]:
        """A client of a hub whose engine reads a seeded invocation trail, and that trail.

        Arranged entirely hub-side on :attr:`decisions`' terms, and it arises that
        way for a reason of ADR-0192's own: a client has no way to put an
        invocation row in one either, because both appends are on
        ``InvocationLedger`` behind the tool seam and ``open_invocations`` is
        deliberately unpromoted. The trail is read from the test process rather than
        over the wire, which is what makes it a negative control: §4's refusals must
        happen **before a frame is sent**, and only a log read from where the read
        would have landed says so.
        """
        trail = await seeded_invocation_trail()
        backing = FakeAssistantEngine()
        backing.trail = trail
        async with serving(backing, tmp_path / "hub.sock") as client:
            yield InvocationSubject(engine=client, trail=trail)

    @pytest.fixture
    async def overfull_invocations(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub whose published limit the whole invocation trail exceeds.

        :attr:`overfull_decisions`' binding, one row kind over: this one really
        serialises, so the frame is the bound rather than an in-process measurement,
        and the hub publishes the same number the backing engine measures against.
        """
        trail = await seeded_invocation_trail(rows=overfull_invocation_rows())
        backing = FakeAssistantEngine(max_payload_bytes=_INVOCATION_LIMIT)
        backing.trail = trail
        async with serving(
            backing,
            tmp_path / "hub.sock",
            max_frame_bytes=_INVOCATION_LIMIT + ENVELOPE_RESERVE_BYTES,
        ) as client:
            yield client

    @pytest.fixture
    async def overfull_reads(self, tmp_path: Path) -> AsyncIterator[AssistantEngine]:
        """A client of a hub whose published limit the whole read trail exceeds.

        :attr:`overfull_decisions`' binding, one store over: this one really
        serialises, so the frame is the bound rather than an in-process measurement,
        and the hub publishes the same number the backing engine measures against.
        """
        trail = await seeded_read_trail(
            rows=tuple((f"r-{index}", index) for index in range(_OVERFULL_READS))
        )
        backing = FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)
        backing.reads = trail
        async with serving(
            backing,
            tmp_path / "hub.sock",
            max_frame_bytes=_TINY_LIMIT + ENVELOPE_RESERVE_BYTES,
        ) as client:
            yield client

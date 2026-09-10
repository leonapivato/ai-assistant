"""A real origin that never answers, and the bound that has to survive it (#2207).

Every other case about ``StreamOutboundTransport``'s cancellation path
substitutes ``asyncio.open_connection`` (:mod:`test_egress_channel`), which is the
right instrument for the *release* clauses — a substitute is the only thing that
can report what was handed out and never given back. It is the wrong instrument
for the *bound*, because the component whose behaviour decides the bound is the one
being substituted. That is how a five-second ``search_call_deadline`` came back at
sixty seconds through a green suite (#2207, and ADR-0241 §12 Arm 1's in-tree arm).

So these cases open a real socket to a real listening origin that answers nothing,
and measure the wall clock. What they assert is ADR-0241 §1's promise read at the
seam it was escaping through: the caller's cancellation — which is how §1 delivers
the deadline — is passed on to the opening rather than deferred behind it.

**No transport-level bound is under test here and none exists.** ADR-0241 §13
defers "a connect timeout, a read timeout or a socket timeout in
``tools/egress.py``", and nothing in these cases would notice one: with the
cancellation removed, every arm below hangs for ``asyncio``'s own default handshake
timeout, and with the cancellation present none of them reaches any timeout at all.

The last case is ADR-0241 §12's **Arm 1** driven end to end over this origin, which
is why a servicing arm sits in a file otherwise about the transport: the property is
one and the two readings of it belong beside each other. ``test_web_search`` keeps
the arm over the substituted transport, because a double is still the only thing
that can report a stall at a *cancellable await* — and the pair is the point, since
agreement between them is what was missing when the defect shipped.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from stalled_origin_harness import stalled_origin
from web_search_harness import authorised_search, built, request

from ai_assistant.core.types import CostBasis, SearchRefusal, ToolOutcome
from ai_assistant.tools.egress import StreamOutboundTransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: Tests that bind a listening socket, in the corpus' own sense of the marker.
pytestmark = pytest.mark.integration

#: The bound a case sets. Short, because what is being measured is whether the
#: cancellation arrives at all rather than how precise the deadline is.
_BOUND: Final = timedelta(milliseconds=500)

#: ADR-0241 §12's "stated slack", stated here. It is wide — a loopback connect,
#: a TLS context built off the trust store and a task cancellation are all quick,
#: and none of them is what this measures. What it has to be narrower than is the
#: shape it exists to refuse: ``asyncio``'s 60-second default
#: ``ssl_handshake_timeout``, which is what the seam waited out before, so any
#: slack under a minute makes the same case bite.
_SLACK: Final = timedelta(seconds=5)


@pytest.fixture
async def reports() -> AsyncIterator[list[dict[str, Any]]]:
    """Everything the running loop's exception handler was asked to report.

    ``asyncio.shield`` swaps a logging callback onto the inner future once the
    outer has been cancelled, so an open that is left running and later fails on
    its own arrives here as "``ConnectionResetError`` exception in shielded
    future" — a report that names no caller, no endpoint and nothing an operator
    could act on. #2207's recheck saw exactly that, and an open the seam cancels
    produces none of it.

    Yields:
        The list, filled as the loop reports.
    """
    loop = asyncio.get_running_loop()
    recorded: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, context: recorded.append(context))
    try:
        yield recorded
    finally:
        loop.set_exception_handler(None)


async def _settled() -> None:
    """Let every callback the loop already holds run before the assertions."""
    for _ in range(10):
        await asyncio.sleep(0)


async def test_a_deadline_bounds_an_open_stalled_in_the_handshake(
    reports: list[dict[str, Any]],
) -> None:
    """ADR-0241 §1's bound reaches the one stage that was outliving it.

    §1 delivers the deadline as a cancellation reaching the seam, and the seam
    used to take it and then wait for the opening to finish anyway — so the expiry
    fired at the bound and the frame returned when the far end gave up. Against
    the origin #2207 measured that was ``asyncio``'s 60-second default handshake
    timeout: twelve times the operator's five seconds.

    The elapsed time is the assertion, and the accepted connection is what says
    the arrangement really did reach the handshake rather than failing earlier.
    """
    async with stalled_origin() as origin:
        started = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(_BOUND.total_seconds()):
                await StreamOutboundTransport().open_channel(origin.endpoint)
        elapsed = asyncio.get_running_loop().time() - started

        assert origin.accepted.is_set(), "the origin was actually reached"
        assert origin.connections == 1, "and reached once, by the one open"

    assert elapsed < (_BOUND + _SLACK).total_seconds(), (
        "a deliberately stalled open is terminated within the declared bound"
    )
    await _settled()
    assert reports == []


async def test_a_cancellation_bounds_an_open_stalled_in_the_handshake(
    reports: list[dict[str, Any]],
) -> None:
    """ADR-0241 §7 and ADR-0060 §1: a cancellation from outside, delivered on time.

    A deadline is one way this seam is cancelled and a client hanging up is the
    other, and #2207 recorded both outliving their cause: "a cancellation issued
    after connect is likewise delivered only when the server closes". The
    cancellation still leaves — ADR-0060 §1's second clause, and the ``pytest.raises``
    below is what says it was not absorbed — but it now leaves promptly.
    """
    async with stalled_origin() as origin:
        opening = asyncio.ensure_future(StreamOutboundTransport().open_channel(origin.endpoint))
        async with asyncio.timeout(_SLACK.total_seconds()):
            await origin.accepted.wait()

        started = asyncio.get_running_loop().time()
        opening.cancel()
        with pytest.raises(asyncio.CancelledError):
            await opening
        elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < _SLACK.total_seconds(), (
        "the cancellation is passed on to the opening rather than deferred behind it"
    )
    await _settled()
    assert reports == []


async def test_a_stalled_real_origin_ends_the_search_within_its_bound(
    reports: list[dict[str, Any]],
) -> None:
    """ADR-0241 §12's **Arm 1**, with nothing standing in for the transport.

    §12's preamble asks for each arm "over the production servicing path, the
    production searcher and the production ``Settings``, and not over a double
    standing in for one of them". The transport is not on that list, and #2207 is
    what the omission cost: the arm passed over ``StallingTransport`` — whose stall
    sits at a plain cancellable ``sleep`` — while the real seam held a five-second
    ``search_call_deadline`` open for sixty seconds against an origin that accepted
    the connection and stopped.

    So this is the same arm over the production ``StreamOutboundTransport`` and a
    real listening origin. The classification half was never the defect and is
    asserted anyway, because an arm that measured only the clock would pass an
    implementation that returned promptly with the wrong refusal.

    **The ledger is prompt here for §12's own reason** — §1's third clause puts
    neither append inside the bound — and it is a fake, which §12's preamble
    permits: what it forbids is a double standing in for the servicing path, the
    searcher or the settings.
    """
    async with stalled_origin() as origin:
        subject = await built(transport=StreamOutboundTransport(), origin=origin.origin)
        proposal = await request(subject, origin=origin.origin)
        call = await authorised_search(subject.trail, proposal=proposal)

        started = asyncio.get_running_loop().time()
        outcome = await subject.searcher.search(call, timeout=_BOUND)
        elapsed = asyncio.get_running_loop().time() - started

        assert origin.accepted.is_set(), "the search really did reach the origin"
        assert origin.connections == 1, "over one connection, opened once"

    assert outcome.refusal is SearchRefusal.DEADLINE_EXPIRED
    assert outcome.records == ()
    assert elapsed < (_BOUND + _SLACK).total_seconds(), (
        "a deliberately stalled search is terminated within the declared bound"
    )

    rows = [row.invocation for row in await subject.trail.export_invocations()]
    completions = [row for row in rows if row.completes is not None]
    assert [row.outcome for row in completions] == [ToolOutcome.INDETERMINATE]
    assert completions[0].incurred_cost is not None
    assert completions[0].incurred_cost.basis is CostBasis.UNKNOWN
    await _settled()
    assert reports == []

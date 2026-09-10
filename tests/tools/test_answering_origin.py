"""An origin that answers, and then one that stops answering (#2218).

:mod:`test_stalled_origin` drives ADR-0241 §12's **Arm 1** against an origin that
never speaks, which bounds the *open*. These cases drive the stage past it. The
origin here completes TLS against a certificate the production transport actually
verified, reads the request, answers it, and then — on the next connection — holds
the response back. That is where a second turn's search spends its deadline, and it
is a stage no arm in this tree reached before: the shield in ``open_channel`` is
long since past, and what has to arrive is ADR-0241 §1's cancellation reaching a
read.

**What is asserted here, and what is not.** ADR-0241 §12's Arm 4 is a conjunction:
the second turn's reply *"still answers from what the conversation actually
retains"* **and** *"states the interruption"*. Both halves are properties of the
loop, over a conversation's tail and its captured episode — and §12 is explicit that
*"no lane satisfies this arm by keeping turn one's minted records alive"*, because
ADR-0231 §16 forbids retention. So neither half is here. What is here is the arm's
**shape at the seam**: that a first search over a real origin mints real records,
that a second search against the same origin stalled past its handshake expires as
``DEADLINE_EXPIRED`` under a real bound, and that the expiry did nothing to the
first call's outcome. The loop's half belongs to the QA re-drive, and
:mod:`answering_origin_harness`'s module docstring is the runbook for it.

**No transport-level bound is under test here and none exists** — ADR-0241 §13
defers one. What ends the stalled read is the searcher's own deadline, delivered as
a cancellation, and the elapsed time is what says so: it is at least the bound,
because the read really was held, and nowhere near the unbounded hold the origin
would otherwise have kept.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import pytest
from answering_origin_harness import SEARCH_PATH, AnsweringOrigin, answering_origin
from web_search_harness import REPORTED_AT, authorised_search, built, request

from ai_assistant.core.types import CostBasis, SearchRefusal, ToolOutcome
from ai_assistant.tools.egress import StreamOutboundTransport

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from web_search_harness import Built

    from ai_assistant.core.types import SearchOutcome

#: Tests that bind a listening socket, in the corpus' own sense of the marker.
pytestmark = pytest.mark.integration

#: The bound every call below runs under. Real, because ADR-0241 §12 asks for one —
#: *"the bound is a real duration and the stall is a real one, because a fake clock
#: would assert nothing about the property the acceptance sentence names"* — and two
#: seconds rather than the operator's five, because what is measured is whether the
#: cancellation arrives at all rather than how precise the deadline is.
_BOUND: Final = timedelta(seconds=2)

#: ADR-0241 §12's "stated slack", stated here. Wide, because none of what it covers
#: is what these cases measure: a loopback connect, a TLS handshake against a freshly
#: minted certificate, a request write and a task cancellation. What it has to be
#: narrower than is the shape it refuses — an origin that holds the read for as long
#: as the block lives, which is unbounded.
_SLACK: Final = timedelta(seconds=5)

#: How much early the stalled call may return and still count as having waited its
#: bound out. ``asyncio`` fires a deadline no earlier than its deadline; the elapsed
#: time here is measured around the whole call rather than around the read, so this
#: is slack against the measurement rather than against the bound.
_EARLY: Final = timedelta(milliseconds=100)

#: A bound no run of the case that uses it reaches. Ten minutes, so that what ends
#: that search is provably the release and not the deadline — which is the whole
#: claim, and which a bound of any plausible size would leave arguable.
_UNREACHABLE: Final = timedelta(minutes=10)

#: What the origin's default result transcribes to under ADR-0231 §10's fixed form —
#: title, address, snippet, one per line. Spelled out rather than rebuilt from
#: ``result()``, because a case that rebuilt it from the same call the origin served
#: from would assert that two copies of one value are equal.
_TRANSCRIBED: Final = (
    "Torre dos Clérigos\nhttps://example.invalid/clerigos\nA baroque bell tower in Porto."
)


async def _searched(
    subject: Built,
    *,
    origin: str,
    decision_id: str,
    timeout: timedelta = _BOUND,  # noqa: ASYNC109 — the seam owns the deadline (ADR-0241 §1, §2)
) -> SearchOutcome:
    """Drive one authorised search over ``subject``.

    Args:
        subject: The configured integration, already pointed at a live origin.
        origin: The origin the request names, which is the account's own.
        decision_id: The decision this call is authorised by. Distinct per call:
            ADR-0192 §1 admits one claim per decision, so a second search under a
            spent decision is refused before it reaches the origin.
        timeout: The bound to pass the seam (ADR-0241 §1). Defaults to
            :data:`_BOUND`; one case names a figure no run of it reaches, so that
            what ends the search is provably not the deadline.

    Returns:
        The outcome.
    """
    proposal = await request(subject, origin=origin)
    call = await authorised_search(subject.trail, proposal=proposal, decision_id=decision_id)
    outcome: SearchOutcome = await subject.searcher.search(call, timeout=timeout)
    return outcome


def _paths(targets: list[str]) -> list[str]:
    """The path half of each request target the origin read.

    Args:
        targets: The origin-form targets, each a path and a query.

    Returns:
        The paths, without the query the composed request carries.
    """
    return [urlsplit(target).path for target in targets]


async def _under_watchdog(
    searching: Coroutine[Any, Any, SearchOutcome], *, origin: AnsweringOrigin
) -> SearchOutcome:
    """Await one search against a stalled origin, or fail — never hang.

    **The upper bound is a watchdog rather than an assertion, and it releases the
    origin rather than only cancelling.** Two things make that necessary, and the
    second is what a plain ``asyncio.timeout`` around the call gets wrong.

    First, an assertion *after* the call is unreachable where the call never
    returns: the origin holds the connection for as long as its block lives, so a
    regression that stopped delivering the deadline would hang the run rather than
    fail it. Nothing else bounds it — this corpus configures no per-test timeout and
    CI's job has none either.

    Second, a bound that only cancels is a bound the very regression this case is
    written over can outlive. ``asyncio.timeout`` cancels the *current task*, which
    is the same task the search is running in; an implementation that defers or
    absorbs cancellations (ADR-0241 §4 and §7 distinguish exactly those) takes both
    the deadline's cancellation at two seconds and the watchdog's at seven and keeps
    waiting for octets that are not coming. So the search runs in a task of its own,
    the wait is ``asyncio.wait``'s — which returns rather than cancelling — and the
    escape is :meth:`AnsweringOrigin.release`, which closes the connection. A read
    ends when there is nothing left to read from whether or not the reader can be
    cancelled, which is the property ``test_releasing_the_origin_ends_a_stalled_search``
    pins.

    Args:
        searching: The search to drive.
        origin: The origin holding it, to release if the bound is reached.

    Returns:
        The outcome, where the search returned inside the bound.
    """
    task = asyncio.ensure_future(searching)
    done, _ = await asyncio.wait({task}, timeout=(_BOUND + _SLACK).total_seconds())
    if not done:  # pragma: no cover — the failure path this bound exists for
        origin.release()
        with suppress(BaseException):
            async with asyncio.timeout(_SLACK.total_seconds()):
                await task
        task.cancel()
        pytest.fail(
            "the stalled search did not return within the bound plus ADR-0241 §12's "
            "stated slack, so the deadline is no longer reaching the response read"
        )
    return task.result()


async def test_a_real_origin_that_answers_mints_records_from_what_it_served() -> None:
    """The other half of #2207's pair: a production transport that gets an answer.

    Every case in ``test_web_search`` that mints a record serves its response over
    :class:`~ai_assistant.testing.FakeByteChannel`, which is the right instrument
    for ADR-0231 §10's transcription clauses and says nothing about whether the
    production transport can obtain a response at all. ``test_stalled_origin``
    closed the half where it cannot; this closes the half where it can.

    The certificate is why this case can exist: the transport verifies it under
    ``check_hostname`` against ``localhost``, so an arrangement that got the trust
    anchor wrong fails here rather than producing a record out of nowhere.
    """
    async with answering_origin(answer=1) as origin:
        subject = await built(transport=StreamOutboundTransport(), origin=origin.origin)
        outcome = await _searched(subject, origin=origin.origin, decision_id="d-answering-1")

        assert origin.answered == 1, "the origin served the one request"
        assert _paths(origin.requests) == [SEARCH_PATH]

    assert outcome.refusal is None
    assert outcome.reported_at == REPORTED_AT
    (record,) = outcome.records
    assert record.content == _TRANSCRIBED
    # ADR-0231 §10 and ADR-0092 §3: the record is attested to the instant the
    # provider's own response declared, which here is an instant a socket carried
    # rather than one a fake channel was handed.
    assert record.provenance.attestation is not None
    assert record.provenance.attestation.reported_at == REPORTED_AT

    rows = [row.invocation for row in await subject.trail.export_invocations()]
    completions = [row for row in rows if row.completes is not None]
    assert [row.outcome for row in completions] == [ToolOutcome.SUCCEEDED]


async def test_a_second_search_against_a_stalled_answer_expires_and_leaves_the_first() -> None:
    """ADR-0241 §12 **Arm 4**'s shape at the seam, over a real origin.

    The origin answers the first request and holds the second past its handshake,
    which is the fault Arm 4 is written over: a conversation whose first turn
    searched and answered and whose second turn's search expires. Three things are
    asserted, and the third is the one a weaker implementation would fail.

    1. The first search produced records from what the origin served.
    2. The second returned ``DEADLINE_EXPIRED`` — **not** ``TRANSPORT_FAILED``,
       which is what a read that failed on its own would be, and which is the
       misclassification Arm 1 names in terms — within the bound plus §12's stated
       slack, and no earlier than the bound, because the read really was held.
    3. The first outcome is untouched. §12 warns that Arm 4 *"asserts no retained
       minted record"*; nothing here retains anything, and this clause is the
       converse — an expiry on a later call may not reach back into an outcome an
       earlier one already returned.

    **Two connections, one request each**, which is ADR-0191 §3's channel per call
    read from the far end rather than from the seam: a transport that pooled would
    show the second request arriving on the first connection.
    """
    async with answering_origin(answer=1, then="stall") as origin:
        subject = await built(transport=StreamOutboundTransport(), origin=origin.origin)

        answered = await _searched(subject, origin=origin.origin, decision_id="d-answering-first")
        assert answered.refusal is None
        assert [record.content for record in answered.records] == [_TRANSCRIBED]

        started = asyncio.get_running_loop().time()
        expired = await _under_watchdog(
            _searched(subject, origin=origin.origin, decision_id="d-answering-second"),
            origin=origin,
        )
        elapsed = asyncio.get_running_loop().time() - started

        assert origin.exhausted.is_set(), "the second request really was held, not failed"
        assert origin.answered == 1, "and the script answered only the first"
        assert origin.connections == 2, "one request per connection, two calls"
        assert _paths(origin.requests) == [SEARCH_PATH, SEARCH_PATH]

    assert expired.refusal is SearchRefusal.DEADLINE_EXPIRED
    assert expired.records == ()
    # The upper bound is the watchdog above; what is left to assert is the *lower*
    # one, which no watchdog can express — a call that returned early would be
    # failing for some reason other than the deadline, and would still be inside it.
    assert elapsed >= (_BOUND - _EARLY).total_seconds(), (
        "and it really waited on the stall rather than failing early for another reason"
    )

    assert answered.refusal is None
    assert [record.content for record in answered.records] == [_TRANSCRIBED], (
        "the expiry left the first call's records alone"
    )

    # ADR-0241 §12 Arm 2's members, over the two calls together: the answered one
    # completed ``SUCCEEDED`` and the expired one ``INDETERMINATE`` with an
    # ``unknown_cost()``. Matched by outcome rather than by position, because the
    # ledger's export order is its own business and a case that assumed one would be
    # asserting about the trail rather than about the seam.
    rows = [row.invocation for row in await subject.trail.export_invocations()]
    completions = [row for row in rows if row.completes is not None]
    assert sorted(row.outcome.value for row in completions if row.outcome is not None) == [
        ToolOutcome.INDETERMINATE.value,
        ToolOutcome.SUCCEEDED.value,
    ]
    interrupted = next(row for row in completions if row.outcome is ToolOutcome.INDETERMINATE)
    assert interrupted.incurred_cost is not None
    assert interrupted.incurred_cost.basis is CostBasis.UNKNOWN


async def test_an_origin_that_hangs_up_is_not_read_as_an_expiry() -> None:
    """The neighbouring fault, so that the arm above is not passing by accident.

    ``then="close"`` is the same script with the stall replaced by a hang-up, and
    the classification has to move with it: a connection the far end closed before
    it answered is a failure of the exchange, and reading it as an expiry would mean
    ``DEADLINE_EXPIRED`` had become this seam's answer for "something went wrong"
    rather than for "the bound fired". Returning promptly is the other half of the
    distinction, and is what says the clock was not what ended it.

    It is also what keeps the harness' second branch driven: a script arm no case
    exercises is a fixture nobody has checked works.
    """
    async with answering_origin(answer=0, then="close") as origin:
        subject = await built(transport=StreamOutboundTransport(), origin=origin.origin)

        started = asyncio.get_running_loop().time()
        outcome = await _searched(subject, origin=origin.origin, decision_id="d-answering-closed")
        elapsed = asyncio.get_running_loop().time() - started

        assert origin.exhausted.is_set(), "the origin reached the end of its script"
        assert origin.answered == 0, "and answered nothing"
        assert _paths(origin.requests) == [SEARCH_PATH], "having read the request first"

    assert outcome.refusal is SearchRefusal.TRANSPORT_FAILED
    assert outcome.records == ()
    assert elapsed < _BOUND.total_seconds(), "a hang-up is answered without waiting out the bound"


async def test_releasing_the_origin_ends_a_stalled_search() -> None:
    """The property every watchdog above rests on, pinned on its own.

    ``_under_watchdog`` escapes a search that outlives its bound by releasing the
    origin rather than by cancelling the search, on the reasoning that a read ends
    when there is nothing left to read from whether or not the reader can be
    cancelled — and that a bound which can only cancel is one that a
    cancellation-deferring regression outlives. That reasoning is load-bearing for
    the arm above, so it is asserted rather than described.

    The deadline is put out of reach — :data:`_UNREACHABLE` is ten minutes — so
    that what ends this search is provably :meth:`AnsweringOrigin.release` and not
    ADR-0241 §1's expiry. The refusal is ``TRANSPORT_FAILED`` for the same reason:
    the connection went away under the read, which is a transport failure and not
    an expiry, and reading ``DEADLINE_EXPIRED`` here would mean the deadline had
    fired after all.
    """
    async with answering_origin(answer=0, then="stall") as origin:
        subject = await built(transport=StreamOutboundTransport(), origin=origin.origin)
        searching = asyncio.ensure_future(
            _searched(
                subject,
                origin=origin.origin,
                decision_id="d-answering-released",
                timeout=_UNREACHABLE,
            )
        )
        async with asyncio.timeout(_SLACK.total_seconds()):
            await origin.exhausted.wait()
        assert not searching.done(), "the search is held in its response read"

        origin.release()
        async with asyncio.timeout(_SLACK.total_seconds()):
            outcome = await searching

    assert outcome.refusal is SearchRefusal.TRANSPORT_FAILED
    assert outcome.records == ()

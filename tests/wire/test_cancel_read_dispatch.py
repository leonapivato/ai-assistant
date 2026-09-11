"""``cancel_read`` crosses the wire, and every promoted method binds to its signature.

**The defect this module exists for (#2243) was invisible to every suite in the
tree**, and the reason is worth stating because it decides where the regression
belongs. ``AssistantEngine.cancel_read`` declares its token **positional-only** —
``async def cancel_read(self, token: ContinuationToken, /)``, as ADR-0244 §11
states the signature — and ``wire/server.py``'s one dispatch site called every
promoted method by keyword splat. So the CLI's ``assistant cancel-read`` and the
browser's "Cancel this lookup" both raised ``TypeError`` inside the hub, which is
not an ``AssistantError``, so it escaped the error handler and **the connection
dropped with no reply**. Both surfaces ADR-0244 §13 names for this kind offered
the act; neither could perform it.

Nine modules mention ``cancel_read`` and every one of them called an engine **in
process**, where Python binds the token positionally and the ``/`` is satisfied.
The single wire-level test asserted that the *name* is in the promoted set, which
was true and said nothing about whether dispatching it binds. So what is pinned
here is the seam itself: a real client, a real ``AF_UNIX`` socket, a real
``serve_connection``, and the canonical fake behind it — the level at which the
bug is reachable and below which it is not.

**Two kinds of binding, and the second is what keeps this from recurring.** The
first drives ADR-0244 §11's three states and its unknown-token refusal over the
socket, which is the defect itself. The second is signature-shaped rather than
method-shaped: it holds that *every* promoted method's declared arguments reach
its declared parameters, so a future operation that lands with a positional-only
parameter is covered on the day it lands rather than on the day a QA run finds it
on a live hub. That is ``wire/surface.py``'s own principle — read the mapping off
the Protocol rather than transcribing a table — applied to the test that guards it.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import UnknownContinuationError
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import ContinuationToken, ReadCancellation
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import HubEngineClient, serve_connection
from ai_assistant.wire.server import ConnectionLimits
from ai_assistant.wire.surface import METHODS, call_shape, parameters, positional_only

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

#: Generous, because nothing here is about a deadline and a tight one would turn a
#: slow machine into a flaky protocol failure.
_PATIENT: Final = timedelta(seconds=30)

#: ADR-0084 §3's default frame size.
_ORDINARY_FRAME: Final = 16 * 1024 * 1024

#: The handle the park under test is answered by.
_HANDLE: Final = "read-park-1"


class _DeliverySlots:
    """A ``DeliveryRegistry`` that admits everyone.

    The slot arithmetic is ``tests/wire/test_server_delivery.py``'s subject; a
    listener handed no registry closes every ``next_notification`` rather than
    serving it, so one is supplied and it records nothing.
    """

    def claim(self, device: str | None) -> bool:
        """Admit every claimant."""
        del device
        return True

    def release(self, device: str | None) -> None:
        """Nothing is held, so nothing is given back."""
        del device


@contextlib.asynccontextmanager
async def _serving(backing: FakeAssistantEngine, path: Path) -> AsyncIterator[HubEngineClient]:
    """Run one hub over ``backing`` for the body of a ``with``, yielding a client of it.

    **Nothing is stubbed between the two halves**, which is the whole point: the
    call under test is really encoded to ADR-0087's bytes, framed, read back with a
    length prefix, dispatched by name against the engine, and validated into its
    declared return type. A double in the middle would let this pass over a path the
    wire never takes, which is exactly how #2243 stayed hidden.
    """
    limits = ConnectionLimits(max_frame_bytes=_ORDINARY_FRAME, read_timeout=_PATIENT, build="test")

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await serve_connection(backing, reader, writer, limits=limits, delivery=_DeliverySlots())

    server = await asyncio.start_unix_server(serve, path=str(path))
    try:
        yield HubEngineClient(path, read_timeout=_PATIENT)
    finally:
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()
        _unlink(path)


def _unlink(path: Path) -> None:
    """Remove the socket, off the async path so the checkers stay happy."""
    path.unlink(missing_ok=True)


def _parked() -> FakeAssistantEngine:
    """An engine holding one ``OPEN`` read park, at :data:`_HANDLE`."""
    engine = FakeAssistantEngine()
    engine.park_read(_HANDLE, query="what is the tide at noon")
    return engine


async def test_cancelling_an_open_park_over_the_wire_withdraws_it(tmp_path: Path) -> None:
    """#2243's reproduction, and ADR-0244 §11's first state.

    Before the fix this did not return ``WITHDRAWN``; it did not return at all. The
    hub raised ``TypeError: Engine.cancel_read() got some positional-only arguments
    passed as keyword arguments: 'token'``, which is not an ``AssistantError``, so
    the handler did not catch it and the connection closed unanswered — what a user
    saw was a transport fault rather than the act they performed.
    """
    backing = _parked()

    async with _serving(backing, tmp_path / "hub.sock") as client:
        assert await client.cancel_read(ContinuationToken(handle=_HANDLE)) is (
            ReadCancellation.WITHDRAWN
        )

    assert ("cancel_read", {"token": _HANDLE}) in backing.calls, (
        "the token reached the engine rather than dying in the dispatcher's splat"
    )


async def test_cancelling_a_dispatched_read_over_the_wire_interrupts_it(tmp_path: Path) -> None:
    """ADR-0244 §11's second state: "cancelling a dispatched read cancels the task".

    Unreachable over the wire before the fix for the same one reason as the other
    two — the token never got as far as discriminating anything, so no disposition
    was reachable and the member's own clause could not be exercised on a hub.
    """
    backing = _parked()
    backing.read_dispatching.add(_HANDLE)

    async with _serving(backing, tmp_path / "hub.sock") as client:
        assert await client.cancel_read(ContinuationToken(handle=_HANDLE)) is (
            ReadCancellation.INTERRUPTED
        )


async def test_cancelling_a_settled_park_over_the_wire_reports_nothing_to_cancel(
    tmp_path: Path,
) -> None:
    """ADR-0244 §11's third state, reached over one connection by cancelling twice.

    **The second call is the subject and the first is the arrangement**, which also
    makes this the binding that shows the connection survives a ``cancel_read`` at
    all: a hub that dropped the socket on the first could not answer a second.
    """
    async with _serving(_parked(), tmp_path / "hub.sock") as client:
        token = ContinuationToken(handle=_HANDLE)

        assert await client.cancel_read(token) is ReadCancellation.WITHDRAWN
        assert await client.cancel_read(token) is ReadCancellation.NOTHING_TO_CANCEL


async def test_an_unknown_token_comes_back_as_a_refusal_and_not_a_dropped_socket(
    tmp_path: Path,
) -> None:
    """ADR-0084 §7's refusal, over the wire, at the operation #2243 made unreachable.

    ``UnknownContinuationError`` at ``cancel_read`` could not be raised before the
    fix, because nothing got as far as the handle table. It is an ``AssistantError``,
    so it crosses as an ADR-0085 §10a error frame and is reconstructed here — which
    is the distinction the defect erased: a *refusal* the caller can render, rather
    than a transport fault that says nothing about what happened.
    """
    async with _serving(_parked(), tmp_path / "hub.sock") as client:
        with pytest.raises(UnknownContinuationError):
            await client.cancel_read(ContinuationToken(handle="no-such-park"))

        assert await client.cancel_read(ContinuationToken(handle=_HANDLE)) is (
            ReadCancellation.WITHDRAWN
        ), "and the connection carried on, which a dropped socket would not have"


@pytest.mark.parametrize("method", sorted(METHODS))
def test_every_promoted_methods_arguments_reach_their_declared_parameters(method: str) -> None:
    """The general guard: no promoted method is dispatchable only by luck of its kinds.

    **This is the binding #2243 lacked.** ``cancel_read`` was the first method on the
    surface with a positional-only parameter and the dispatcher's keyword splat had
    never met one, so the defect was a property of a *signature kind* rather than of
    a method — and the test that catches it has to be shaped that way too. Every
    method here is asked the question the hub asks at dispatch: given the arguments
    the surface declares, does the call shape the server builds actually bind to the
    signature, with every argument arriving at its own parameter?

    The sentinels are distinct objects and each is asserted **by identity** against
    the parameter it was sent under, so an argument that bound to the wrong
    parameter — the failure a positional pass can introduce where a keyword one
    cannot — fails here rather than confusing an engine at run time.
    """
    signature = inspect.signature(getattr(AssistantEngine, method))
    sentinels: dict[str, Any] = {name: object() for name in parameters(method)}

    positional, keyword = call_shape(method, sentinels)
    bound = signature.bind(object(), *positional, **keyword)

    assert {name: value for name, value in bound.arguments.items() if name != "self"} == sentinels


@pytest.mark.parametrize("method", sorted(METHODS))
def test_no_promoted_method_declares_an_optional_positional_only_parameter(method: str) -> None:
    """The invariant the server's call shaping is allowed to rest on.

    The dispatcher fills positional-only parameters from the payload **in
    declaration order**, and an argument the client did not send is absent rather
    than ``null`` (ADR-0085 §10) — so a positional-only parameter that could be
    omitted would strand every positional-only parameter after it, which would be
    the same class of defect as #2243 wearing different clothes.

    No such parameter exists today, and this says so out loud rather than leaving it
    as an assumption the dispatcher makes silently. A lane that adds one is told
    here, at the seam that would have to grow a rule for it, rather than by a hub
    that answers a request with the wrong argument in it.
    """
    declared = inspect.signature(getattr(AssistantEngine, method)).parameters

    assert not [
        name
        for name in positional_only(method)
        if declared[name].default is not inspect.Parameter.empty
    ]

"""A positional-only parameter crosses the wire, and every promoted method binds.

**The defect this module was written for (#2243) was invisible to every suite in the
tree.** ``AssistantEngine.cancel_read`` declared its token **positional-only**, and
``wire/server.py``'s one dispatch site called every promoted method by keyword splat,
so the hub raised ``TypeError`` — not an ``AssistantError`` — and **the connection
dropped with no reply**. ``cancel_read`` left the surface with the old path's turn
(ADR-0309 §5:1); the kind of parameter that broke it did not. ``stop_activation``
takes its subject the same way, and ``wire/surface.py`` cites this module as the pin
on the call shape, so it keeps its name and its subject moves to ``stop_activation``.

**Two kinds of binding, and the second is what keeps this from recurring.** The
first drives a positional-only method over a real client, a real ``AF_UNIX`` socket
and a real ``serve_connection``, with the canonical fake behind it — the level at
which the defect was reachable and below which it was not. The second is
signature-shaped rather than method-shaped: it holds that *every* promoted method's
declared arguments reach its declared parameters, so a future operation that lands
with a positional-only parameter is covered on the day it lands. That is
``wire/surface.py``'s own principle — read the mapping off the Protocol rather than
transcribing a table — applied to the test that guards it.

**The socket case is marked ``integration`` and the two signature ones are not**,
which is ``CONTRIBUTING.md`` → "Testing" applied as ``tests/wire/test_client_overlay.py``
reads it: "a Unix socket is the filesystem".
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import ActivationStop
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

#: The activation the stop under test names, which no running activation holds.
_ACTIVATION: Final = "00000000-0000-4000-8000-0000000000cc"


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


@pytest.mark.integration
async def test_a_positional_only_argument_reaches_the_engine_over_the_wire(
    tmp_path: Path,
) -> None:
    """#2243's shape, on a method that still carries it.

    ``stop_activation`` declares its activation id positional-only, as ``cancel_read``
    declared its token. A dispatcher that splatted it by keyword would raise
    ``TypeError`` inside the hub and drop the connection, and the client would report
    the hub hung up rather than return one of ADR-0297 §5's answers.
    """
    backing = FakeAssistantEngine()

    async with _serving(backing, tmp_path / "hub.sock") as client:
        assert await client.stop_activation(_ACTIVATION) is ActivationStop.NO_SUCH_ACTIVATION

    assert ("stop_activation", {"activation_id": _ACTIVATION}) in backing.calls, (
        "the id reached the engine rather than dying in the dispatcher's splat"
    )


@pytest.mark.parametrize("method", sorted(METHODS))
def test_every_promoted_methods_arguments_reach_their_declared_parameters(method: str) -> None:
    """The general guard: no promoted method is dispatchable only by luck of its kinds.

    **This is the binding #2243 lacked.** ``cancel_read``, since retired, was the first
    method on the surface with a positional-only parameter and the dispatcher's keyword
    splat had never met one, so the defect was a property of a *signature kind* rather
    than of a method — and the test that catches it has to be shaped that way too. Every
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

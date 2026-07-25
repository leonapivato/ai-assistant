"""Two real vendor SDK stacks, driven offline (ADR-0061 §4).

The point of these is *not* to check that Anthropic's or OpenAI's API works — it
is to check that our seam is provider-shaped rather than Anthropic-shaped with a
general name. Nothing in ``models/`` is exercised meaningfully by a pydantic-ai
``TestModel``: that double replaces the vendor SDK entirely, so the request
serialisation, the response parsing and above all the **exception hierarchy**
that ``_classify`` dispatches on are all pydantic-ai's own, never a vendor's.

So each stack here is the *real* thing down to the socket:

``PydanticAIProvider`` → pydantic-ai ``AnthropicModel``/``OpenAIChatModel``
→ the real ``anthropic``/``openai`` SDK client → ``httpx``

and only the transport is replaced, by :class:`httpx.MockTransport`. The vendor
SDK really serialises our message history to its own wire format, really parses
the canned response, and really raises its own exception type for a canned HTTP
status — which is precisely the assumption
``docs/review/architecture-validation-2026-07-24.md`` (C6) recorded as untested:
that a second SDK's failures land in pydantic-ai's ``ModelHTTPError``/
``ModelAPIError`` hierarchy the way Anthropic's do.

**No credentials, no network.** Each client is constructed with a literal dummy
key, so nothing is read from the environment and a developer's real key can
never be picked up; and every test runs under
:func:`tests.models.network_guard.network_denied`, which turns "offline" from an
assumption into an assertion.

``max_retries=0`` on both clients: each vendor SDK retries 429s and 5xx
*internally* by default, so one canned failure would arrive as three requests
and what got classified would be the SDK's last attempt rather than the failure.
Nothing here wraps a ``RetryingProvider`` — our own retry semantics sit above
this seam, never touch a vendor type, and are exercised over a fake in
``tests/models/test_retry.py``. The vendor's retry behaviour is removed here, not
measured.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from pydantic_ai.models import Model

#: What stands in for the network: a callable answering one request.
type Handler = Callable[[httpx.Request], httpx.Response]

#: A dummy key, so no vendor client ever reads one from the environment.
_DUMMY_KEY: Final = "test-key-not-a-credential"

_ANTHROPIC_MODEL_NAME: Final = "claude-sonnet-4-5"
_OPENAI_MODEL_NAME: Final = "gpt-5"

#: What each vendor's mock transport answers with on the success path. Minimal
#: but wire-accurate: the vendor SDK parses these with its own response models,
#: so a shape it does not recognise fails the test rather than being ignored.
_ANTHROPIC_REPLY: Final = "anthropic reply"
_OPENAI_REPLY: Final = "openai reply"


def anthropic_success(request: httpx.Request) -> httpx.Response:
    """Answer any Anthropic Messages request with a minimal successful reply."""
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": _ANTHROPIC_MODEL_NAME,
            "content": [{"type": "text", "text": _ANTHROPIC_REPLY}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )


def openai_success(request: httpx.Request) -> httpx.Response:
    """Answer any OpenAI chat-completions request with a minimal successful reply."""
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": _OPENAI_MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": _OPENAI_REPLY},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def failing_status(status_code: int) -> Handler:
    """Return a handler answering every request with ``status_code``.

    Args:
        status_code: The HTTP status the vendor SDK should see.

    Returns:
        A handler suitable for :class:`httpx.MockTransport`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"type": "test", "message": "denied"}})

    return handler


#: What an intermediary substitutes for the model's answer when it fails: its own
#: error page, in HTML.
_GATEWAY_ERROR_PAGE: Final = "<html><head><title>502 Bad Gateway</title></head><body></body></html>"


def non_json_body(request: httpx.Request) -> httpx.Response:
    """Answer ``200`` with a body that is not JSON, under a JSON content type.

    The failure a load balancer, proxy or captive portal produces: the request
    reached *something*, which answered with its own error page instead of
    forwarding to the model. The content type is deliberately the JSON one the
    vendor SDK expects, so the SDK commits to decoding the body and fails —
    which is the shape ``#352`` reproduced on both vendors.
    """
    return httpx.Response(
        200,
        text=_GATEWAY_ERROR_PAGE,
        headers={"content-type": "application/json"},
    )


def truncated_json_body(request: httpx.Request) -> httpx.Response:
    """Answer ``200`` with a JSON body cut off mid-object.

    The same decode failure arrived at by the other common route — a connection
    dropped or a response truncated partway — rather than by an intermediary
    substituting a whole page. Pinned separately so the classification is known
    to follow from *the body not decoding*, not from it starting with ``<``.
    """
    return httpx.Response(
        200,
        text='{"id": "msg_test", "type": "mess',
        headers={"content-type": "application/json"},
    )


def connection_refused(request: httpx.Request) -> httpx.Response:
    """Fail at the transport, the way an unreachable provider does.

    Raises:
        httpx.ConnectError: Always — this handler never answers.
    """
    msg = "connection refused"
    raise httpx.ConnectError(msg)


def _anthropic_model(http_client: httpx.AsyncClient) -> Model:
    """Build a real ``AnthropicModel`` sending over ``http_client``."""
    client = AsyncAnthropic(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
    return AnthropicModel(
        _ANTHROPIC_MODEL_NAME, provider=AnthropicProvider(anthropic_client=client)
    )


def _openai_model(http_client: httpx.AsyncClient) -> Model:
    """Build a real ``OpenAIChatModel`` sending over ``http_client``."""
    client = AsyncOpenAI(api_key=_DUMMY_KEY, http_client=http_client, max_retries=0)
    return OpenAIChatModel(_OPENAI_MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def _anthropic_turn_text(turn: Mapping[str, Any]) -> str:
    """Read one serialised Anthropic turn's text out of its content blocks."""
    blocks: Sequence[Mapping[str, Any]] = turn["content"]
    return "".join(block["text"] for block in blocks)


def _openai_turn_text(turn: Mapping[str, Any]) -> str:
    """Read one serialised OpenAI turn's text, which is a bare string."""
    text: str = turn["content"]
    return text


@dataclass(frozen=True, slots=True)
class VendorStack:
    """One vendor's real SDK, wired to a replaceable transport.

    Attributes:
        name: The vendor, for test ids and failure messages.
        bind: Wraps an :class:`httpx.AsyncClient` in that vendor's real SDK and
            returns a pydantic-ai ``Model`` over it. Not called directly — go
            through :meth:`opened`, which owns the client's lifetime.
        success: The handler that answers with that vendor's success shape.
        reply: The assistant text ``success`` returns, so a test can assert the
            reply came back through the vendor's own response parsing.
        turn_text: Reads the text out of one serialised turn in that vendor's
            request body. The two vendors disagree about the shape — Anthropic
            sends a list of typed content blocks, OpenAI a bare string — so a
            test that wants to assert *what was said* (not merely who said it)
            has to go through the vendor to get at it.
    """

    name: str
    bind: Callable[[httpx.AsyncClient], Model]
    success: Handler
    reply: str
    turn_text: Callable[[Mapping[str, Any]], str]

    def __str__(self) -> str:
        """Name the vendor, so parametrised test ids read as the vendor name."""
        return self.name

    @asynccontextmanager
    async def opened(self, handler: Handler) -> AsyncIterator[Model]:
        """Yield a model over this vendor's real SDK, closing its client on exit.

        The transport client is built here rather than inside ``bind`` so that
        *something* owns it: a stack that hands back a bare ``Model`` leaves the
        client reachable only through two layers of vendor internals, and closing
        it becomes nobody's job. ``MockTransport`` allocates no pool and opens no
        socket, so nothing leaks today (#354) — but the value of this harness is
        that it is the real stack down to the transport, and the moment the
        transport is swapped for one that allocates, ~34 clients a run would go
        unclosed and present as exhausted descriptors late in a suite.

        Args:
            handler: What stands in for the network for this model's lifetime.

        Yields:
            A pydantic-ai ``Model`` over the vendor's real SDK.
        """
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            yield self.bind(http_client)

    def transcript(self, body: Mapping[str, Any]) -> list[tuple[str, str]]:
        """Return ``(role, text)`` for every turn in a serialised request body.

        The pair, not the role alone: a vendor adapter that dropped or rewrote a
        turn's *content* while keeping the role sequence intact would send a
        materially different prompt, and a canned response would hide it.

        Args:
            body: One request body the vendor SDK put on the wire.

        Returns:
            Each turn as ``(role, text)``, in the order sent.
        """
        turns: Sequence[Mapping[str, Any]] = body["messages"]
        return [(turn["role"], self.turn_text(turn)) for turn in turns]


ANTHROPIC = VendorStack(
    name="anthropic",
    bind=_anthropic_model,
    success=anthropic_success,
    reply=_ANTHROPIC_REPLY,
    turn_text=_anthropic_turn_text,
)
OPENAI = VendorStack(
    name="openai",
    bind=_openai_model,
    success=openai_success,
    reply=_OPENAI_REPLY,
    turn_text=_openai_turn_text,
)

#: Every vendor stack the conformance suite is run against.
VENDORS: Final[tuple[VendorStack, ...]] = (ANTHROPIC, OPENAI)


class RequestRecorder:
    """Records the request bodies a vendor SDK actually put on the wire.

    What each vendor *sends* is the only place message mapping can be checked
    honestly: ``_to_model_messages`` produces pydantic-ai's intermediate form,
    and how that lands in a vendor's own schema is the vendor adapter's decision,
    not ours. Two vendors disagreeing about it is exactly the finding worth
    having.
    """

    def __init__(self, inner: Handler) -> None:
        """Wrap ``inner``, recording each request before delegating to it."""
        self._inner = inner
        self.bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Record ``request``'s JSON body, then answer it via the wrapped handler."""
        body: dict[str, object] = json.loads(request.content)
        self.bodies.append(body)
        return self._inner(request)

    @property
    def only(self) -> dict[str, object]:
        """The single recorded request body.

        Returns:
            The one body recorded.

        Raises:
            AssertionError: If the number of requests was not exactly one — a
                silent second call would otherwise be read as the first.
        """
        assert len(self.bodies) == 1, f"expected exactly one request, got {len(self.bodies)}"
        return self.bodies[0]

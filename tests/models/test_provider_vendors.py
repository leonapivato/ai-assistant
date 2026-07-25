"""The seam, run against two real vendor SDKs offline (ADR-0061).

``docs/review/architecture-validation-2026-07-24.md`` (C6) found model-agnosticism
"structurally real, empirically unexercised": one vendor extra was installed, and
every provider test drove pydantic-ai's own ``TestModel``/``FunctionModel``
doubles, which stand *in place of* a vendor SDK. So the claim rested on
inspection, and three things had never been checked against a second vendor at
all — that the shared ``ModelProvider`` conformance suite passes over it, that
its exceptions land where ``_classify`` dispatches, and what our flat message
list becomes on its wire.

This module checks all three, with no credentials and no network: see
``tests/models/vendor_stacks.py`` for how the real ``anthropic`` and ``openai``
SDKs are driven over :class:`httpx.MockTransport`, and why that (rather than
recorded cassettes or a live key) is the shape that proves what needs proving.

The divergences the message-mapping tests pin are the load-bearing part. They
are asserted, not merely observed, because a change in either vendor adapter that
silently alters where a system instruction lands is a change to what the user's
prompt *means* — and no other test in this repository would see it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from model_provider_contract import ModelProviderContract
from network_guard import network_denied
from vendor_stacks import (
    ANTHROPIC,
    OPENAI,
    VENDORS,
    RequestRecorder,
    VendorStack,
    connection_refused,
    failing_status,
)

from ai_assistant.core.errors import (
    ModelAuthError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.models import PydanticAIProvider

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ai_assistant.core.protocols import ModelProvider


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """Deny egress for every test in this module.

    A mock transport does not connect, so nothing here *should* reach a socket —
    but "should not" is the claim under test. The guard turns it into an
    assertion: if a vendor SDK ever resolves a name or opens a connection while
    building a client or a request, that test fails and says so, rather than
    quietly depending on the machine having network and a key.
    """
    with network_denied():
        yield


def _provider(vendor: VendorStack) -> PydanticAIProvider:
    """A provider whose model is ``vendor``'s real SDK, answering successfully."""
    return PydanticAIProvider(vendor.build(vendor.success))


class _VendorContract(ModelProviderContract):
    """The shared conformance suite, bound to one real vendor stack.

    Subclassed once per vendor below rather than parametrised, because the
    Protocol-triad check (``tests/core/test_protocol_triad.py``) records honoured
    obligations per *test class*: one class per implementation is what makes
    "this implementation passed the suite" a fact about a named binding.
    """

    vendor: VendorStack

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return _provider(self.vendor)


class TestAnthropicStackContract(_VendorContract):
    """``PydanticAIProvider`` over the real ``anthropic`` SDK passes the contract."""

    vendor = ANTHROPIC


class TestOpenAIStackContract(_VendorContract):
    """``PydanticAIProvider`` over the real ``openai`` SDK passes the contract."""

    vendor = OPENAI


@pytest.mark.parametrize("vendor", VENDORS, ids=str)
async def test_a_reply_comes_back_through_the_vendors_own_response_parsing(
    vendor: VendorStack,
) -> None:
    # Not just "an assistant message" (the shared suite covers that) but *this
    # vendor's* text, which only arrives if its SDK parsed its own response shape.
    reply = await _provider(vendor).complete([Message(role=Role.USER, content="hi")])

    assert reply.role is Role.ASSISTANT
    assert reply.content == vendor.reply


# The assumption C6 recorded as untested, stated as a table: a vendor SDK's HTTP
# failure must reach `_classify` as pydantic-ai's `ModelHTTPError`, carrying the
# status, for the status-based dispatch to mean anything. Both vendors are held
# to the identical mapping — that identity *is* the agnosticism claim.
_STATUS_TAXONOMY = [
    (401, ModelAuthError, False),
    (403, ModelAuthError, False),
    (408, ModelTimeoutError, True),
    (429, ModelRateLimitError, True),
    (500, ModelUnavailableError, True),
    (503, ModelUnavailableError, True),
]


@pytest.mark.parametrize("vendor", VENDORS, ids=str)
@pytest.mark.parametrize(("status_code", "expected", "retryable"), _STATUS_TAXONOMY)
async def test_an_http_failure_classifies_identically_across_vendors(
    vendor: VendorStack,
    status_code: int,
    expected: type[ModelError],
    retryable: bool,
) -> None:
    provider = PydanticAIProvider(vendor.build(failing_status(status_code)))

    with pytest.raises(ModelError) as caught:
        await provider.complete([Message(role=Role.USER, content="hi")])

    assert type(caught.value) is expected
    assert caught.value.retryable is retryable


@pytest.mark.parametrize("vendor", VENDORS, ids=str)
async def test_a_malformed_request_is_not_retryable_on_either_vendor(vendor: VendorStack) -> None:
    # A 4xx that is not auth, timeout or throttling is our bug, and retrying or
    # re-routing it would fail identically. Pinned per vendor because it is the
    # one status arm that falls through to the conservative default.
    provider = PydanticAIProvider(vendor.build(failing_status(400)))

    with pytest.raises(ModelError) as caught:
        await provider.complete([Message(role=Role.USER, content="hi")])

    assert type(caught.value) is ModelError
    assert not caught.value.retryable
    assert not caught.value.routable


@pytest.mark.parametrize("vendor", VENDORS, ids=str)
async def test_a_transport_failure_is_unavailable_on_either_vendor(vendor: VendorStack) -> None:
    # No status code was ever produced, so this exercises the `ModelAPIError`
    # arm rather than the status table — the arm a genuinely unreachable
    # provider lands on, and the one routing most needs classified right.
    provider = PydanticAIProvider(vendor.build(connection_refused))

    with pytest.raises(ModelError) as caught:
        await provider.complete([Message(role=Role.USER, content="hi")])

    assert type(caught.value) is ModelUnavailableError
    assert caught.value.retryable
    assert caught.value.routable


async def _record(vendor: VendorStack, messages: list[Message]) -> dict[str, Any]:
    """Complete ``messages`` against ``vendor`` and return the body it put on the wire."""
    recorder = RequestRecorder(vendor.success)
    await PydanticAIProvider(vendor.build(recorder)).complete(messages)
    return recorder.only


_LEADING_SYSTEM = [
    Message(role=Role.SYSTEM, content="be terse"),
    Message(role=Role.USER, content="hi"),
    Message(role=Role.ASSISTANT, content="hello"),
    Message(role=Role.USER, content="how are you?"),
]


async def test_a_leading_system_prompt_becomes_anthropics_top_level_system_field() -> None:
    body = await _record(ANTHROPIC, _LEADING_SYSTEM)

    # Anthropic takes the system instruction *out* of the message array and into
    # a sibling field; the three conversational turns keep their order.
    assert body["system"] == "be terse"
    assert [turn["role"] for turn in body["messages"]] == ["user", "assistant", "user"]


async def test_a_leading_system_prompt_stays_a_system_role_message_for_openai() -> None:
    body = await _record(OPENAI, _LEADING_SYSTEM)

    # OpenAI keeps it inline as a fourth message with its own role — the same
    # `_to_model_messages` output, a materially different request.
    assert "system" not in body
    assert [turn["role"] for turn in body["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


_LATE_SYSTEM = [
    Message(role=Role.USER, content="u1"),
    Message(role=Role.ASSISTANT, content="a1"),
    Message(role=Role.SYSTEM, content="now be terse"),
    Message(role=Role.USER, content="u2"),
]


async def test_a_late_system_prompt_is_inlined_into_a_user_turn_for_anthropic() -> None:
    # The sharpest divergence, and the reason these are asserted rather than
    # left to inspection. Anthropic's API has exactly one system slot, at the
    # top, so a system message that arrives *after* an assistant turn cannot go
    # there: pydantic-ai demotes it into the following user turn, wrapped in
    # literal `<system>` tags. The instruction survives as text but loses its
    # privileged role, landing in the same channel as user-supplied content.
    body = await _record(ANTHROPIC, _LATE_SYSTEM)

    assert "system" not in body
    last_turn = body["messages"][-1]
    assert last_turn["role"] == "user"
    assert [block["text"] for block in last_turn["content"]] == [
        "<system>now be terse</system>",
        "u2",
    ]


async def test_a_late_system_prompt_keeps_its_role_for_openai() -> None:
    # The same input, on OpenAI, keeps full system authority mid-conversation.
    # A caller that reads one of these behaviours as "the" behaviour of the seam
    # has read a vendor's, not ours: `ModelProvider` promises neither.
    body = await _record(OPENAI, _LATE_SYSTEM)

    assert [turn["role"] for turn in body["messages"]] == ["user", "assistant", "system", "user"]
    assert body["messages"][2]["content"] == "now be terse"


@pytest.mark.parametrize("vendor", VENDORS, ids=str)
async def test_conversational_turns_survive_in_order_on_either_vendor(
    vendor: VendorStack,
) -> None:
    # Whatever each vendor does with the system slot, the user/assistant
    # alternation and its order is the part `_to_model_messages` is actually
    # responsible for, and it must be vendor-independent.
    body = await _record(vendor, _LEADING_SYSTEM)

    conversational = [turn for turn in body["messages"] if turn["role"] != "system"]
    assert [turn["role"] for turn in conversational] == ["user", "assistant", "user"]


@pytest.mark.parametrize("vendor", VENDORS, ids=str)
async def test_a_tool_role_message_is_refused_before_any_vendor_is_reached(
    vendor: VendorStack,
) -> None:
    # `provider.py` rejects `Role.TOOL` unconditionally, so this is a limit of
    # *our* seam and not of either vendor — both of which support tool results.
    # Pinned per vendor so the gap stays visible as a capability we owe, rather
    # than reading as one vendor's restriction.
    recorder = RequestRecorder(vendor.success)
    provider = PydanticAIProvider(vendor.build(recorder))

    with pytest.raises(ModelError, match="tool-role"):
        await provider.complete([Message(role=Role.TOOL, content="result")])

    assert recorder.bodies == [], "the request must not reach the vendor at all"

"""``build_anthropic_batch_completer``: the composition root's one line, tested.

**What is under test is a claim about what does *not* happen.** ADR-0143 §8 gives a
consumer outside ``ai_assistant`` a composition root of its own, and the builder is
what makes that reachable without the consumer naming a vendor type golden rule 4
confines to ``models/``. Everything worth asserting about it is therefore negative:
it reads no credential, opens no socket, and hands back an object that behaves
exactly as one built through the constructor does. So the whole module runs inside
:func:`network_guard.network_denied`, and the environment is stripped of every
variable the SDK could resolve a credential from — an assertion rather than an
assumption, which is the technique ADR-0143 §13's closing clause already requires of
this seam's vendor binding.

**The threading of the four arguments is asserted where they are observable, and
that is the wire.** ``issuer`` is public on the completer; the other three are not,
and reading them off private attributes would assert that the builder passes what it
passes — a tautology that would keep passing if the constructor stopped honouring
them. Two of them refuse before the provider is contacted, so they are asserted by
the refusal (``default_model`` through a spec naming another vendor, ``max_items``
through an over-large batch). ``max_tokens`` is observable only in the request body,
so :class:`TestTheBuiltCompleterWorksOverTheWire` drives a built completer over the
scripted endpoint of :mod:`anthropic_batch_stack` and reads it back out of what the
provider received — which also exercises ``submit`` → ``poll`` → ``fetch`` on an
object the builder made, rather than on one the tests wired by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from anthropic import AsyncAnthropic
from anthropic_batch_stack import DUMMY_KEY, BatchServer
from batch_completer_contract import a_batch, a_request
from network_guard import network_denied

from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.core.types import BatchOutcomeKind, BatchState
from ai_assistant.models import batch as batch_module
from ai_assistant.models.batch import (
    DEFAULT_MAX_TOKENS,
    AnthropicBatchCompleter,
    build_anthropic_batch_completer,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The account label these tests build with. A label and never a credential —
#: ADR-0143 §2's reason is that handles are written to disk.
ISSUER = "acct-builder-tests"

MODEL = "anthropic:claude-sonnet-4-5"

#: Every variable the ``anthropic`` SDK resolves a credential from. Deleted for the
#: whole module, so "reads no credential" is checked against a process that has none
#: to read rather than against one that happened to be configured.
_CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BEARER_TOKEN",
)


@pytest.fixture(autouse=True)
def _offline_and_uncredentialed(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Deny egress and remove every credential variable, for every test here."""
    for name in _CREDENTIAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    with network_denied():
        yield


class TestItBuildsWithoutReachingAnythingOrReadingACredential:
    """The negative claims: no socket, no credential, no wiring."""

    def test_it_returns_a_completer_stamped_with_the_configured_issuer(self) -> None:
        completer = build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL)

        assert isinstance(completer, AnthropicBatchCompleter)
        assert completer.issuer == ISSUER

    def test_it_builds_with_no_credential_configured_at_all(self) -> None:
        # The SDK resolves `ANTHROPIC_API_KEY` when a request is made, not when a
        # client is constructed, and the builder deliberately does not pre-empt that
        # (`provider.ensure_credential_available` is where a caller asks early). A
        # build that raised here would make the harness's `plan` command need a key.
        assert build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) is not None

    def test_a_blank_issuer_is_refused_as_a_configuration_fault(self) -> None:
        # Delegated to the constructor, and asserted through the builder because the
        # builder is now the front door: an operator mistyping the label must still
        # meet it here rather than at the first submission.
        with pytest.raises(ConfigurationError, match="issuer"):
            build_anthropic_batch_completer(issuer="   ", default_model=MODEL)


class TestTheArgumentsThatRefuseBeforeTheProviderIsContacted:
    """``default_model`` and ``max_items``, asserted by the refusals they cause."""

    async def test_the_configured_default_model_is_what_an_unoverridden_submit_resolves(
        self,
    ) -> None:
        completer = build_anthropic_batch_completer(
            issuer=ISSUER, default_model="openai:gpt-5-mini"
        )

        # A spec naming another provider is refused on the near side of the
        # acceptance window (ADR-0143 §2), so this reaches no socket — which the
        # module's `network_denied` would otherwise have reported instead.
        with pytest.raises(ModelError, match="openai"):
            await completer.submit("k", a_batch("q1"))

    async def test_the_declared_item_bound_is_the_one_the_builder_was_given(self) -> None:
        completer = build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL, max_items=2)

        with pytest.raises(ModelError, match="exceeds this completer's declared bound of 2"):
            await completer.submit("k", a_batch("q1", "q2", "q3"))


class TestTheBuiltCompleterWorksOverTheWire:
    """A completer the builder made, driven end to end against a scripted endpoint.

    The client the builder constructs is replaced by one over
    :class:`httpx.MockTransport` — the *only* substitution, and the one thing a test
    cannot avoid here, since the builder owns the client precisely so that its caller
    need not name it. Everything downstream of that is the real SDK and the real
    implementation, which is what makes the request body a fair reading of what the
    builder configured.
    """

    @pytest.fixture
    def server(self) -> BatchServer:
        return BatchServer()

    @pytest.fixture
    def transport(self, server: BatchServer, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
        """Point the builder's own client at ``server``, and hand back what closes it.

        Returned rather than torn down here because closing an ``httpx.AsyncClient``
        is a coroutine and this fixture is not one; each test owns the client for the
        length of its own ``async with``, which is also the window the completer is
        used in.
        """
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(server))

        def _client_over_the_scripted_endpoint(**_: Any) -> AsyncAnthropic:
            return AsyncAnthropic(api_key=DUMMY_KEY, http_client=http_client, max_retries=0)

        monkeypatch.setattr(batch_module, "AsyncAnthropic", _client_over_the_scripted_endpoint)
        return http_client

    async def test_it_submits_with_the_configured_model_and_token_bound(
        self, server: BatchServer, transport: httpx.AsyncClient
    ) -> None:
        async with transport:
            completer = build_anthropic_batch_completer(
                issuer=ISSUER, default_model=MODEL, max_tokens=77
            )

            handle = await completer.submit("run-1", [a_request("q1")])

            params = server.batches[handle.batch_id].body["requests"][0]["params"]
            assert params["max_tokens"] == 77
            # The vendor's own model name, with the provider half of the spec
            # resolved away — the builder threaded the spec, the implementation
            # split it.
            assert params["model"] == "claude-sonnet-4-5"

    async def test_the_default_token_bound_is_the_module_constant(
        self, server: BatchServer, transport: httpx.AsyncClient
    ) -> None:
        async with transport:
            completer = build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL)

            handle = await completer.submit("run-1", [a_request("q1")])

            params = server.batches[handle.batch_id].body["requests"][0]["params"]
            assert params["max_tokens"] == DEFAULT_MAX_TOKENS

    async def test_a_caller_submits_polls_and_fetches_through_a_built_completer(
        self, server: BatchServer, transport: httpx.AsyncClient
    ) -> None:
        async with transport:
            completer = build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL)

            handle = await completer.submit("run-1", a_batch("q1", "q2"))
            assert handle.issuer == ISSUER
            assert handle.batch_key == "run-1"

            pending = await completer.poll(handle)
            assert pending.state is BatchState.PENDING

            server.batches[handle.batch_id].settled = True
            settled = await completer.poll(handle)
            assert settled.state is BatchState.COMPLETE

            outcomes = await completer.fetch(handle)
            # Matched by id and never by position: the scripted endpoint returns
            # its results jumbled, exactly as the vendor's do (ADR-0143 §4).
            by_id = {outcome.item_id: outcome for outcome in outcomes}
            assert set(by_id) == {"q1", "q2"}
            assert all(outcome.kind is BatchOutcomeKind.SUCCEEDED for outcome in outcomes)

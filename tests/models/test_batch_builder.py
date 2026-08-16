"""``build_anthropic_batch_completer``: the composition root's one line, tested.

**The claim under test is narrower than "it touches nothing", because the SDK makes
the wider one false.** ADR-0143 §8 gives a consumer outside ``ai_assistant`` a
composition root of its own, and the builder is what makes that reachable without the
consumer naming a vendor type golden rule 4 confines to ``models/``. But
``AsyncAnthropic()`` resolves a credential *in its constructor* — the two environment
variables, then a named profile or workload-identity federation, the first of which
reads the SDK's config directory from disk. So what is asserted here is what is
actually true: the builder opens **no socket**, it succeeds with nothing configured,
and a credential *configuration* that is broken comes back as our own
``ConfigurationError`` rather than as a vendor exception.

Holding that honestly needs a hermetic environment rather than a hopeful one. Every
variable in the SDK's resolution chain is deleted, and ``HOME`` and
``XDG_CONFIG_HOME`` are pointed at an empty directory so the on-disk fallback profile
finds nothing either — otherwise a developer machine with a profile configured would
be testing a different chain from CI. ``ANTHROPIC_CONFIG_DIR`` is deliberately *not*
used for that: setting it makes profile selection **explicit**, which turns a missing
config file from a fall-through into a raise, and that is a different case — the one
:class:`TestABrokenCredentialConfigurationIsTranslated` exercises on purpose.

The whole module additionally runs inside :func:`network_guard.network_denied`, which
is the technique ADR-0143 §13's closing clause already requires of this seam's vendor
binding: "offline" asserted rather than assumed.

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
from anthropic import AnthropicError, AsyncAnthropic
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
    from pathlib import Path

#: The account label these tests build with. A label and never a credential —
#: ADR-0143 §2's reason is that handles are written to disk.
ISSUER = "acct-builder-tests"

MODEL = "anthropic:claude-sonnet-4-5"

#: Every variable in the SDK's credential-resolution chain, in its own order: the
#: two static credentials, explicit profile selection, and the workload-identity
#: federation group. Read off ``anthropic.lib.credentials._chain.default_credentials``
#: rather than remembered, and deleted whole — a chain tested with one link cut is a
#: chain whose other links were never exercised.
_CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
)


@pytest.fixture(autouse=True)
def _offline_and_uncredentialed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Deny egress, and leave the SDK nothing to resolve a credential from.

    The home directory is redirected as well as the variables cleared, because the
    chain's last step reads ``~/.config/anthropic/`` and a machine with a profile
    configured would otherwise run a different resolution from CI's.
    """
    for name in _CREDENTIAL_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with network_denied():
        yield


class TestItBuildsWithoutReachingAnything:
    """No socket, and no credential needed to get an object back."""

    def test_it_returns_a_completer_stamped_with_the_configured_issuer(self) -> None:
        completer = build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL)

        assert isinstance(completer, AnthropicBatchCompleter)
        assert completer.issuer == ISSUER

    def test_it_builds_with_no_credential_configured_at_all(self) -> None:
        # Not a claim that the credential is unread — the SDK's chain runs in the
        # constructor and finds nothing here. The claim is that finding nothing is
        # not an error at build time: the builder deliberately does not pre-empt
        # `ensure_credential_available`, so a caller that has not configured a key
        # still gets an object and fails on the exchange instead.
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


class TestABrokenCredentialConfigurationIsTranslated:
    """A vendor exception from the SDK's constructor must not reach the caller.

    The whole point of the builder is that a consumer outside this package never
    names a vendor type; a raw ``anthropic.AnthropicError`` travelling out of it
    would defeat that one level up from the import, and hand that consumer an
    exception class it cannot catch without the import golden rule 4 denies it.
    """

    def test_a_profile_with_no_config_behind_it_raises_our_own_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Setting the config dir is *explicit* profile selection, which is the one
        # branch of the chain where a missing file propagates instead of falling
        # through — so this is the real failure an operator with a half-configured
        # machine hits, not a contrived one.
        monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))

        with pytest.raises(ConfigurationError) as caught:
            build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL)

        # The SDK's own message is quoted rather than paraphrased, as `provider.py`
        # quotes pydantic-ai's, because it names the variable to set.
        assert "ANTHROPIC_PROFILE" in str(caught.value)
        assert not isinstance(caught.value, AnthropicError)


class TestAMissingCredentialFailsAtTheExchangeAndNotAtTheBuild:
    """Where the absence surfaces, asserted rather than asserted about."""

    async def test_submitting_without_a_credential_is_a_model_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server = BatchServer()
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(server))

        def _uncredentialed_client_over_the_scripted_endpoint(**_: Any) -> AsyncAnthropic:
            return AsyncAnthropic(http_client=http_client, max_retries=0)

        monkeypatch.setattr(
            batch_module, "AsyncAnthropic", _uncredentialed_client_over_the_scripted_endpoint
        )

        async with http_client:
            completer = build_anthropic_batch_completer(issuer=ISSUER, default_model=MODEL)

            # Built, not raised — which is the half of the contract the builder owns.
            with pytest.raises(ModelError):
                await completer.submit("run-1", [a_request("q1")])

        # And it never got as far as a request, which is what makes the failure a
        # configuration fault rather than a refused call.
        assert server.calls == 0

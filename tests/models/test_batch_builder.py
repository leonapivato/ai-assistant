"""``anthropic_batch_completer``: the composition root's one line, tested.

**The claim under test is narrower than "it touches nothing", because the SDK makes
the wider one false.** ADR-0143 §8 gives a consumer outside ``ai_assistant`` a
composition root of its own, and this is what makes that reachable without the
consumer naming a vendor type golden rule 4 confines to ``models/``. But
``AsyncAnthropic()`` resolves a credential *in its constructor* — the two environment
variables, then a named profile or workload-identity federation, the first of which
reads the SDK's config directory from disk. So what is asserted here is what is
actually true: it opens **no socket**, it succeeds with nothing configured, a
configuration it cannot build a client from comes back as our own
``ConfigurationError`` rather than as a third-party exception, and it closes the
connection pool it owns on the way out.

Holding that honestly needs a hermetic environment rather than a hopeful one. Every
variable in the SDK's resolution chain is deleted, and ``HOME`` and
``XDG_CONFIG_HOME`` are pointed at an empty directory so the on-disk fallback profile
finds nothing either — otherwise a developer machine with a profile configured would
be testing a different chain from CI. ``ANTHROPIC_CONFIG_DIR`` is deliberately *not*
used for that: setting it makes profile selection **explicit**, which turns a missing
config file from a fall-through into a raise, and that is a different case — the one
:class:`TestAConfigurationItCannotBuildAClientFromIsTranslated` exercises on purpose.

The whole module additionally runs inside :func:`network_guard.network_denied`, which
is the technique ADR-0143 §13's closing clause already requires of this seam's vendor
binding: "offline" asserted rather than assumed.

**Where the arguments are asserted is where they are observable.** ``issuer`` is
public on the completer; the other three are not, and reading them off private
attributes would assert only that the function passes what it passes — a tautology
that would keep passing if the constructor stopped honouring them. Two of them refuse
before the provider is contacted, so they are asserted by the refusal
(``default_model`` through a spec naming another vendor, ``max_items`` through an
over-large batch). ``max_tokens`` is observable only in the request body, so
:class:`TestTheCompleterWorksOverTheWire` drives one over the scripted endpoint of
:mod:`anthropic_batch_stack` and reads it back out of what the provider received —
which also exercises ``submit`` → ``poll`` → ``fetch`` on an object this produced,
rather than on one the tests wired by hand.
"""

from __future__ import annotations

import asyncio
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
from ai_assistant.models.batch import DEFAULT_MAX_TOKENS, anthropic_batch_completer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
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
    configured would otherwise run a different resolution from CI's. Also
    ``ANTHROPIC_BASE_URL``, which is not a credential but is the other input the
    client's constructor can be broken by.
    """
    for name in (*_CREDENTIAL_VARIABLES, "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with network_denied():
        yield


class TestItYieldsACompleterWithoutReachingAnything:
    """No socket, and no credential needed to get an object back."""

    async def test_it_yields_a_completer_stamped_with_the_configured_issuer(self) -> None:
        async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) as completer:
            assert completer.issuer == ISSUER

    async def test_it_builds_with_no_credential_configured_at_all(self) -> None:
        # Not a claim that the credential is unread — the SDK's chain runs in the
        # constructor and finds nothing here. The claim is that finding nothing is
        # not an error at build time: this deliberately does not pre-empt
        # `ensure_credential_available`, so a caller that has not configured a key
        # still gets an object and fails on the exchange instead.
        async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) as completer:
            assert completer is not None

    async def test_a_blank_issuer_is_refused_as_a_configuration_fault(self) -> None:
        # Delegated to the constructor, and asserted through this because this is now
        # the front door: an operator mistyping the label must still meet it here
        # rather than at the first submission.
        with pytest.raises(ConfigurationError, match="issuer"):
            async with anthropic_batch_completer(issuer="   ", default_model=MODEL):
                pass  # pragma: no cover - the refusal is the point


class TestTheArgumentsThatRefuseBeforeTheProviderIsContacted:
    """``default_model`` and ``max_items``, asserted by the refusals they cause."""

    async def test_the_configured_default_model_is_what_an_unoverridden_submit_resolves(
        self,
    ) -> None:
        async with anthropic_batch_completer(
            issuer=ISSUER, default_model="openai:gpt-5-mini"
        ) as completer:
            # A spec naming another provider is refused on the near side of the
            # acceptance window (ADR-0143 §2), so this reaches no socket — which the
            # module's `network_denied` would otherwise have reported instead.
            with pytest.raises(ModelError, match="openai"):
                await completer.submit("k", a_batch("q1"))

    async def test_the_declared_item_bound_is_the_one_it_was_given(self) -> None:
        async with anthropic_batch_completer(
            issuer=ISSUER, default_model=MODEL, max_items=2
        ) as completer:
            with pytest.raises(ModelError, match="exceeds this completer's declared bound of 2"):
                await completer.submit("k", a_batch("q1", "q2", "q3"))


class TestAConfigurationItCannotBuildAClientFromIsTranslated:
    """A third-party exception from the client's constructor must not reach the caller.

    The whole point is that a consumer outside this package never names a vendor
    type; a raw ``anthropic.AnthropicError`` or ``httpx.InvalidURL`` travelling out
    would defeat that one level up from the import, and hand that consumer an
    exception class it cannot catch without the import golden rule 4 denies it. The
    two cases are different third-party packages on purpose — that is what makes the
    catch-by-position in the implementation the right shape rather than a shortcut.
    """

    async def test_a_profile_with_no_config_behind_it_raises_our_own_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Setting the config dir is *explicit* profile selection, which is the one
        # branch of the chain where a missing file propagates instead of falling
        # through — so this is the real failure an operator with a half-configured
        # machine hits, not a contrived one.
        monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "anthropic"))

        with pytest.raises(ConfigurationError) as caught:
            async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL):
                pass  # pragma: no cover - the refusal is the point

        # The third party's own message is quoted rather than paraphrased, as
        # `provider.py` quotes pydantic-ai's, because it names the variable to set.
        assert "ANTHROPIC_PROFILE" in str(caught.value)
        assert not isinstance(caught.value, AnthropicError)

    async def test_a_malformed_base_url_raises_our_own_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Raised by `httpx` from inside the transport the client builds, not by the
        # vendor SDK at all — a second package whose exceptions would otherwise
        # escape.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://[bad]")

        with pytest.raises(ConfigurationError) as caught:
            async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL):
                pass  # pragma: no cover - the refusal is the point

        assert not isinstance(caught.value, httpx.InvalidURL)


class TestTheCompleterWorksOverTheWire:
    """A completer this produced, driven end to end against a scripted endpoint.

    The client it constructs is replaced by one over :class:`httpx.MockTransport` —
    the *only* substitution, and the one thing a test cannot avoid here, since the
    point of the function is that its caller need not name the client. Everything
    downstream of that is the real SDK and the real implementation, which is what
    makes the request body a fair reading of what was configured.
    """

    @pytest.fixture
    def server(self) -> BatchServer:
        return BatchServer()

    @pytest.fixture
    def scripted(self, server: BatchServer, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
        """Point the built client at ``server``, and hand back the transport it uses.

        Returned rather than torn down here because closing an ``httpx.AsyncClient``
        is a coroutine and this fixture is not one. Nothing is leaked by that: the
        context manager under test closes the ``AsyncAnthropic`` wrapping it, which
        is the ownership this fixture exists to observe.
        """
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(server))

        def _client_over_the_scripted_endpoint(**configured: Any) -> AsyncAnthropic:
            # `**configured`, never discarded: a substitution that dropped the
            # builder's own arguments would be testing a client the builder never
            # asks for, and would conceal exactly the configuration these tests
            # exist to pin (round 4's blocker, which a kwarg-discarding double hid).
            return AsyncAnthropic(api_key=DUMMY_KEY, http_client=http_client, **configured)

        monkeypatch.setattr(batch_module, "AsyncAnthropic", _client_over_the_scripted_endpoint)
        return http_client

    async def test_it_submits_with_the_configured_model_and_token_bound(
        self, server: BatchServer, scripted: httpx.AsyncClient
    ) -> None:
        async with anthropic_batch_completer(
            issuer=ISSUER, default_model=MODEL, max_tokens=77
        ) as completer:
            handle = await completer.submit("run-1", [a_request("q1")])

        params = server.batches[handle.batch_id].body["requests"][0]["params"]
        assert params["max_tokens"] == 77
        # The vendor's own model name, with the provider half of the spec resolved
        # away — this threaded the spec, the implementation split it.
        assert params["model"] == "claude-sonnet-4-5"

    async def test_the_default_token_bound_is_the_module_constant(
        self, server: BatchServer, scripted: httpx.AsyncClient
    ) -> None:
        async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) as completer:
            handle = await completer.submit("run-1", [a_request("q1")])

        params = server.batches[handle.batch_id].body["requests"][0]["params"]
        assert params["max_tokens"] == DEFAULT_MAX_TOKENS

    async def test_a_caller_submits_polls_and_fetches_through_it(
        self, server: BatchServer, scripted: httpx.AsyncClient
    ) -> None:
        async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) as completer:
            handle = await completer.submit("run-1", a_batch("q1", "q2"))
            assert handle.issuer == ISSUER
            assert handle.batch_key == "run-1"

            pending = await completer.poll(handle)
            assert pending.state is BatchState.PENDING

            server.batches[handle.batch_id].settled = True
            settled = await completer.poll(handle)
            assert settled.state is BatchState.COMPLETE

            outcomes = await completer.fetch(handle)
            # Matched by id and never by position: the scripted endpoint returns its
            # results jumbled, exactly as the vendor's do (ADR-0143 §4).
            by_id = {outcome.item_id: outcome for outcome in outcomes}
            assert set(by_id) == {"q1", "q2"}
            assert all(outcome.kind is BatchOutcomeKind.SUCCEEDED for outcome in outcomes)


class _ParkedClose:
    """A ``close()`` held open, so a test can cancel the task that is awaiting it.

    ``entered`` fires once the close has begun and suspended; ``release`` lets it
    finish. Between the two, the exiting task sits in the only window where a
    cancellation can orphan the pool, which is the window ADR-0060 §1 is about.
    """

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.clients: list[AsyncAnthropic] = []


def _recording(
    clients: list[AsyncAnthropic], build: Callable[..., AsyncAnthropic]
) -> Callable[..., AsyncAnthropic]:
    """Stand in for ``AsyncAnthropic``, recording every client ``build`` returns.

    The transport is the scripted stack, so what the builder gets is a *real* client
    owning a real connection pool — ``is_closed()`` is then the SDK's own answer
    rather than a double's record of a call — while reaching no socket.
    """

    def _recorded(**configured: Any) -> AsyncAnthropic:
        client = build(
            api_key=DUMMY_KEY,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(BatchServer())),
            **configured,
        )
        clients.append(client)
        return client

    return _recorded


class TestItClosesTheClientItOwns:
    """The reason this is a context manager rather than a builder.

    ``AnthropicBatchCompleter`` exposes no accessor for its client and states that
    the client's lifetime is its caller's, so a consumer handed a completer built
    elsewhere has no way to release the pool. These assert that leaving the block
    does release it — on the ordinary path, when the body raises, and when the block
    is cancelled with the close already in flight.

    That last one is the case a plain ``finally: await client.close()`` fails, and it
    fails silently: the cancellation interrupts the close, the caller holds no
    reference to the client, and nothing is left running that would release the pool.
    ADR-0060 §1 is where the obligation is written.
    """

    class _SuspendsItsClose(AsyncAnthropic):
        """A real client whose ``close()`` parks until the test releases it.

        A subclass rather than a stand-in, so what the assertion reads afterwards is
        the SDK's own ``is_closed()`` over a real pool — the claim is that the pool
        was released, not that a double recorded the attempt.
        """

        def __init__(self, *, parked: _ParkedClose, **configured: Any) -> None:
            super().__init__(**configured)
            self._parked = parked

        async def close(self) -> None:
            self._parked.entered.set()
            await self._parked.release.wait()
            await super().close()

    class _FailsItsClose(AsyncAnthropic):
        """A real client whose ``close()`` refuses, to pin what that does to the body."""

        async def close(self) -> None:
            msg = "the pool would not close"
            raise RuntimeError(msg)

    @pytest.fixture
    def built(self, monkeypatch: pytest.MonkeyPatch) -> list[AsyncAnthropic]:
        """Record every client constructed, so the test can ask whether it closed."""
        clients: list[AsyncAnthropic] = []
        monkeypatch.setattr(batch_module, "AsyncAnthropic", _recording(clients, AsyncAnthropic))
        return clients

    @pytest.fixture
    def parked(self, monkeypatch: pytest.MonkeyPatch) -> _ParkedClose:
        """The same recording, over a client whose ``close()`` suspends on demand."""
        held = _ParkedClose()

        def _suspending(**configured: Any) -> AsyncAnthropic:
            return self._SuspendsItsClose(parked=held, **configured)

        monkeypatch.setattr(batch_module, "AsyncAnthropic", _recording(held.clients, _suspending))
        return held

    @pytest.fixture
    def refusing(self, monkeypatch: pytest.MonkeyPatch) -> list[AsyncAnthropic]:
        """The same recording, over a client that raises out of its ``close()``."""
        clients: list[AsyncAnthropic] = []
        monkeypatch.setattr(
            batch_module, "AsyncAnthropic", _recording(clients, self._FailsItsClose)
        )
        return clients

    async def test_leaving_the_block_closes_the_pool(self, built: list[AsyncAnthropic]) -> None:
        async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) as completer:
            await completer.submit("run-1", [a_request("q1")])
            assert not built[0].is_closed()

        assert built[0].is_closed()

    async def test_a_raising_body_closes_the_pool_too(self, built: list[AsyncAnthropic]) -> None:
        sentinel = RuntimeError("the caller's own failure")

        with pytest.raises(RuntimeError, match="the caller's own failure"):
            async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL):
                raise sentinel

        assert built[0].is_closed()

    async def test_a_refused_issuer_closes_the_pool_it_had_already_built(
        self, built: list[AsyncAnthropic]
    ) -> None:
        # The one failure path a naive `try` around the yield would leave leaking:
        # the client exists by the time the completer's own constructor refuses.
        with pytest.raises(ConfigurationError):
            async with anthropic_batch_completer(issuer=" ", default_model=MODEL):
                pass  # pragma: no cover - the refusal is the point

        assert built[0].is_closed()

    async def test_a_cancellation_mid_close_does_not_take_the_pool_with_it(
        self, parked: _ParkedClose
    ) -> None:
        async def use_the_block() -> None:
            async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL):
                pass

        task = asyncio.create_task(use_the_block())
        # The body is done and the close is suspended: the caller now holds nothing
        # that could release this pool, so an interrupted close orphans it outright.
        await parked.entered.wait()
        task.cancel()
        await asyncio.sleep(0)  # delivered, into the close that is in flight
        parked.release.set()

        # Both halves of §1, and the second is why this is not just `except
        # CancelledError: pass`: the resource ends up safe, *and* the cancellation
        # still arrives rather than being absorbed into an ordinary return.
        with pytest.raises(asyncio.CancelledError):
            await task
        assert parked.clients[0].is_closed()

    async def test_a_close_that_fails_is_reported_over_the_bodys_own_failure(
        self, refusing: list[AsyncAnthropic]
    ) -> None:
        # A deliberate choice rather than an accident of `finally`, so it is pinned:
        # a pool that would not close is the news this block exists to deliver, and
        # the body's failure is kept as the context rather than lost.
        sentinel = ValueError("the caller's own failure")

        with pytest.raises(RuntimeError, match="the pool would not close") as raised:
            async with anthropic_batch_completer(issuer=ISSUER, default_model=MODEL):
                raise sentinel

        assert raised.value.__context__ is sentinel


class TestItDoesNotLetTheSdkRepeatAPaidSubmission:
    """The client is built with the vendor's own retries **off**, and that is checked.

    ``messages.batches.create`` is a ``POST`` that mints a billable job, and the SDK
    sends no idempotency key with it — the base client generates one but only
    transmits it where ``_idempotency_header`` names a header, which this vendor
    leaves ``None``. So a retry of an accepted create is a *second batch*, paid for
    and never named to the caller, which is a worse residue than the one ADR-0143 §2
    states and accepts.

    Asserted by counting requests rather than by reading ``max_retries`` off the
    client, because the count is the thing that costs money.
    """

    class _AcceptsThenLosesTheResponse:
        """A transport that fails *after* the provider would have taken the job.

        From the client's side this is indistinguishable from a create the provider
        accepted and whose response never arrived — which is the case that makes a
        retry expensive rather than merely wasteful.
        """

        def __init__(self) -> None:
            self.posts = 0

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.posts += 1
            msg = "the response never came back"
            raise httpx.ConnectError(msg)

    async def test_a_response_lost_after_acceptance_sends_exactly_one_create(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transport = self._AcceptsThenLosesTheResponse()
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))

        def _client(**configured: Any) -> AsyncAnthropic:
            return AsyncAnthropic(api_key=DUMMY_KEY, http_client=http_client, **configured)

        monkeypatch.setattr(batch_module, "AsyncAnthropic", _client)

        async with (
            http_client,
            anthropic_batch_completer(issuer=ISSUER, default_model=MODEL) as completer,
        ):
            with pytest.raises(ModelError):
                await completer.submit("run-1", [a_request("q1")])

        # One, not three. At the SDK's own default this is 3, and two of them would
        # be batches the caller holds no handle for.
        assert transport.posts == 1

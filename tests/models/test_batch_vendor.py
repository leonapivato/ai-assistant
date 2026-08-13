"""``AnthropicBatchCompleter`` over the real vendor SDK, offline.

The suite binding ADR-0143 §13 requires — "the suite runs against both the fake
and the real implementation" — plus what only a vendor-backed subject can show:
that the seven failure kinds round-trip through the SDK's own result schema, that
a status maps from the vendor's own tallies, and that the two expiries ADR-0143 §6
separates really are two fields meaning two different things.

This module is also the **end-to-end caller exercise** §9's second-to-last clause
makes a deliverable: :class:`TestACallerDrivesTheSeamEndToEnd` drives
``submit`` → ``poll`` → ``fetch`` to a settled batch over the vendor binding,
reads outcomes back by ``item_id``, and covers non-``SUCCEEDED`` kinds. The
conformance suite alone does not discharge it, because a suite run against
``FakeBatchCompleter`` agrees with the contract by construction.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
from anthropic import AsyncAnthropic
from anthropic_batch_stack import (
    DUMMY_KEY,
    MAX_ITEMS,
    VENDOR_ISSUER,
    VENDOR_MODEL,
    BatchServer,
    VendorBatchWorld,
    _completer,
)
from batch_completer_contract import BatchCompleterContract, a_batch, a_request
from network_guard import network_denied

from ai_assistant.core.errors import ConfigurationError, ModelError, ModelResponseError
from ai_assistant.core.types import (
    BatchFailureKind,
    BatchOutcomeKind,
    BatchRequest,
    BatchState,
    Message,
    Role,
)
from ai_assistant.models.batch import AnthropicBatchCompleter
from ai_assistant.testing import ProgrammedOutcome

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.protocols import BatchCompleter


@pytest.fixture(autouse=True)
def _no_network() -> Iterator[None]:
    """Deny egress for every test in this module.

    A mock transport does not connect, so nothing here *should* reach a socket —
    but "should not" is the claim under test. The guard turns it into an
    assertion, and it is the guard ADR-0143 §13's closing clause names.
    """
    with network_denied():
        yield


@asynccontextmanager
async def vendor_world() -> AsyncIterator[VendorBatchWorld]:
    """A completer over the real SDK, answering from a scripted endpoint."""
    server = BatchServer()
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as http_client:
        client = AsyncAnthropic(api_key=DUMMY_KEY, http_client=http_client, max_retries=0)
        yield VendorBatchWorld(
            server=server,
            client=client,
            http_client=http_client,
            subject=_completer(client),
        )


class TestAnthropicBatchCompleterContract(BatchCompleterContract):
    """``AnthropicBatchCompleter`` over the real ``anthropic`` SDK passes the contract."""

    @pytest.fixture
    def completer(self) -> BatchCompleter:
        # The one place this binding cannot use the world: the triad check
        # evaluates a subject fixture taking only `self`, so this builds a client
        # over a transport nothing will ever send on. Every other test goes
        # through `world()`, which owns the client's lifetime.
        return _completer(
            AsyncAnthropic(
                api_key=DUMMY_KEY,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(BatchServer())),
                max_retries=0,
            )
        )

    def world(self) -> AbstractAsyncContextManager[VendorBatchWorld]:
        return vendor_world()


class TestACallerDrivesTheSeamEndToEnd:
    """ADR-0015 §5's implementation contact, made a deliverable by ADR-0143 §9."""

    async def test_a_caller_submits_polls_and_fetches_a_mixed_batch(self) -> None:
        async with vendor_world() as world:
            world.program("q2", ProgrammedOutcome(kind=BatchOutcomeKind.EXPIRED))
            world.program(
                "q3",
                ProgrammedOutcome(
                    kind=BatchOutcomeKind.FAILED, failure_kind=BatchFailureKind.RATE_LIMITED
                ),
            )
            items = a_batch("q1", "q2", "q3")

            # The caller's own record of an intended batch, correlated by a key it
            # minted. The seam never interprets it (ADR-0143 §2).
            handle = await world.completer.submit("run-2026-03-01", items)
            assert handle.batch_key == "run-2026-03-01"
            assert handle.issuer == VENDOR_ISSUER

            first = await world.completer.poll(handle)
            assert first.state is BatchState.PENDING

            # The wait is the caller's loop, and this is that loop's body. Nothing
            # in the seam sleeps: ADR-0143 §2 forbids satisfying `poll` by waiting.
            world.settle(handle)
            settled = await world.completer.poll(handle)
            assert settled.state is BatchState.COMPLETE
            assert settled.settled == settled.total == 3

            outcomes = {outcome.item_id: outcome for outcome in await world.completer.fetch(handle)}

            assert set(outcomes) == {"q1", "q2", "q3"}
            assert outcomes["q1"].kind is BatchOutcomeKind.SUCCEEDED
            assert outcomes["q2"].kind is BatchOutcomeKind.EXPIRED
            failure = outcomes["q3"].failure
            assert failure is not None
            assert failure.kind is BatchFailureKind.RATE_LIMITED
            assert failure.kind.retryable
            assert failure.kind.routable

    async def test_a_run_resumes_across_a_process_restart_from_a_persisted_handle(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("run-2026-03-01", a_batch("q1"))
            world.settle(handle)

            # What surviving a restart means concretely: the handle is rebuilt from
            # its serialised form and handed to a completer constructed afresh.
            revived = type(handle).model_validate_json(handle.model_dump_json())
            resumed = world.rebuilt()

            outcomes = await resumed.fetch(revived)

            assert [outcome.item_id for outcome in outcomes] == ["q1"]


class TestTheVendorMappingBeyondTheContract:
    """What the vendor binding shows that a fake cannot."""

    @pytest.mark.parametrize("kind", list(BatchFailureKind))
    async def test_every_failure_kind_round_trips_through_the_vendor_schema(
        self, kind: BatchFailureKind
    ) -> None:
        async with vendor_world() as world:
            world.program(
                "only", ProgrammedOutcome(kind=BatchOutcomeKind.FAILED, failure_kind=kind)
            )
            handle = await world.completer.submit("key-1", [a_request("only")])
            world.settle(handle)

            outcome = (await world.completer.fetch(handle))[0]

            assert outcome.kind is BatchOutcomeKind.FAILED
            assert outcome.failure is not None
            assert outcome.failure.kind is kind, (
                "each of ADR-0143 §5's seven kinds must survive the vendor's own "
                "result schema — including the two that arrive as *successes*"
            )

    async def test_a_system_turn_is_transmitted_as_the_vendors_system_field(self) -> None:
        async with vendor_world() as world:
            item = BatchRequest(
                item_id="only",
                messages=[
                    Message(role=Role.SYSTEM, content="be terse"),
                    Message(role=Role.USER, content="and answer this"),
                ],
            )

            handle = await world.completer.submit("key-1", [item])

            body = world.server.batches[handle.batch_id].body
            params = body["requests"][0]["params"]
            assert params["system"] == "be terse"
            assert [turn["role"] for turn in params["messages"]] == ["user"]

    async def test_the_model_override_is_stripped_of_its_provider_half(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit(
                "key-1", [a_request("only")], model="anthropic:claude-opus-4-8"
            )

            body = world.server.batches[handle.batch_id].body
            assert body["requests"][0]["params"]["model"] == "claude-opus-4-8"

    async def test_the_default_model_is_used_when_no_override_is_given(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("key-1", [a_request("only")])

            body = world.server.batches[handle.batch_id].body
            assert body["requests"][0]["params"]["model"] == VENDOR_MODEL.split(":", 1)[1]

    async def test_a_spec_naming_another_provider_is_refused_uncontacted(self) -> None:
        async with vendor_world() as world:
            before = world.provider_calls

            with pytest.raises(ModelError) as caught:
                await world.completer.submit("key-1", [a_request("only")], model="openai:gpt-5")

            assert not caught.value.retryable
            assert not caught.value.routable
            assert world.provider_calls == before, (
                "a handle issued by one provider is meaningless to another "
                "(ADR-0143 §2), so this is a caller error and not a route to try"
            )

    async def test_the_two_expiries_are_two_different_fields(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("key-1", a_batch("q1"))
            world.settle(handle)

            before_archiving = await world.completer.poll(handle)
            assert before_archiving.results_expire_at is None, (
                "`expires_at` is the *processing* window and must not be reported "
                "as the results retention; the SDK exposes no forward-looking "
                "retention field, so ADR-0143 §6's None is the honest answer"
            )

            archived = world.server.now
            world.set_results_expiry(handle, archived)
            after = await world.completer.poll(handle)

            assert after.results_expire_at == archived

    async def test_an_archived_batch_refuses_the_fetch_rather_than_short_returning(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("key-1", a_batch("q1", "q2"))
            world.settle(handle)
            world.lapse_retention(handle)

            with pytest.raises(ModelError, match="archived"):
                await world.completer.fetch(handle)

    async def test_a_results_ids_file_is_refused_rather_than_read_as_expiries(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("key-1", a_batch("q1", "q2", "q3"))
            world.settle(handle)
            # The provider now reports three items and offers two, which is the
            # exact silent mis-scoring ADR-0143 §6 exists to prevent.
            world.server.batches[handle.batch_id].results_ids = ("q1", "q2")

            with pytest.raises(ModelResponseError, match="short read"):
                await world.completer.fetch(handle)

    async def test_a_results_file_answering_one_item_twice_is_refused(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("key-1", a_batch("q1", "q2", "q3"))
            world.settle(handle)
            # Three lines for a three-item batch, so a count check alone is
            # satisfied — while "q2" has no answer at all.
            world.server.batches[handle.batch_id].results_ids = ("q1", "q1", "q3")

            with pytest.raises(ModelResponseError, match="distinct"):
                await world.completer.fetch(handle)

    def test_an_issuer_no_handle_could_carry_is_refused_at_construction(self) -> None:
        with pytest.raises(ConfigurationError, match="issuer"):
            AnthropicBatchCompleter(
                client=AsyncAnthropic(api_key=DUMMY_KEY, max_retries=0),
                issuer="   ",
                default_model=VENDOR_MODEL,
            )

    async def test_a_provider_status_failure_is_narrowed_to_its_disposition(self) -> None:
        async with vendor_world() as world:
            handle = await world.completer.submit("key-1", a_batch("q1"))
            world.server.batches.clear()

            with pytest.raises(ModelError) as caught:
                await world.completer.poll(handle)

            assert not caught.value.retryable, "a 404 for a batch that is gone stays a caller error"

    async def test_the_seam_never_sends_the_batch_key_to_the_provider(self) -> None:
        async with vendor_world() as world:
            key = "a key the vendor has nowhere to put"

            handle = await world.completer.submit(key, [a_request("only")])

            body = world.server.batches[handle.batch_id].body
            assert key not in str(body), (
                "ADR-0143 §11 records that nothing ties a caller's key to an "
                "accepted batch on this vendor surface; the key lives on the "
                "handle and nowhere else"
            )
            assert handle.batch_key == key

    async def test_an_over_large_batch_names_the_bound_it_applied(self) -> None:
        async with vendor_world() as world:
            with pytest.raises(ModelError, match=str(MAX_ITEMS)):
                await world.completer.submit(
                    "key-1", a_batch(*(f"i{n}" for n in range(MAX_ITEMS + 1)))
                )

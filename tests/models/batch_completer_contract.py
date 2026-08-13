"""The shared conformance suite for ``BatchCompleter`` (ADR-0143).

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-
prefixed subclass, never the abstract base directly — the shape
``model_provider_contract.py`` and ``embedder_contract.py`` already use, and the
location ADR-0143 §9 points at for exactly that reason.

**A batch seam cannot be conformance-tested against a bare subject.** Every clause
worth checking is about what happens *between* three calls — what the provider was
told, when it was told, what it later reports — so the suite is written against a
:class:`BatchWorld`: the subject, plus enough control over the provider behind it
to settle a batch, expire one, lapse its retention, and hold an exchange open. A
binding supplies that world; the suite never reaches past it.

ADR-0143 §13's table is what this file is measured against. Each test names the
clause it discharges, so a reviewer can walk the table rather than the file.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import BatchCompleter
from ai_assistant.core.types import (
    BatchFailureKind,
    BatchHandle,
    BatchOutcomeKind,
    BatchRequest,
    BatchState,
    Message,
    Role,
)
from ai_assistant.testing import ExchangeGate, ProgrammedOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractAsyncContextManager

    from ai_assistant.core.types import BatchItemOutcome

#: How long a scenario may take before the suite calls it a hang. Every wait in
#: this file is on something an implementation is contractually obliged to
#: complete without waiting for a batch, so a timeout here is a failure and not a
#: slow machine: the alternative is a suite that hangs a CI run instead of
#: reporting which clause was breached.
_SCENARIO_TIMEOUT = 10.0


def a_request(item_id: str, text: str = "what is the capital of France?") -> BatchRequest:
    """One well-formed item: a single user turn awaiting a reply."""
    return BatchRequest(item_id=item_id, messages=[Message(role=Role.USER, content=text)])


def a_batch(*item_ids: str) -> list[BatchRequest]:
    """A mutable list of well-formed items — the caller-owned container ADR-0065 names."""
    return [a_request(item_id) for item_id in item_ids]


@dataclass(frozen=True, slots=True)
class TransmittedItem:
    """One item as the provider actually received it.

    Rendered to primitives rather than handed back as a
    :class:`~ai_assistant.core.types.BatchRequest`, because a vendor binding
    reconstructs it from a JSON request body and must not be obliged to round-trip
    through the very type the observation clause is about.

    Attributes:
        item_id: The id the provider was given for this item.
        turns: ``(role, content)`` for each turn transmitted, in order.
    """

    item_id: str
    turns: tuple[tuple[str, str], ...]


@runtime_checkable
class BatchWorld(Protocol):
    """A subject, plus control over the provider it talks to, for one scenario."""

    @property
    def completer(self) -> BatchCompleter:
        """The subject under test."""
        ...

    @property
    def issuer(self) -> str:
        """The account label this subject was configured with."""
        ...

    @property
    def credential(self) -> str:
        """The credential this subject reaches its provider with.

        Exposed only so the suite can assert that none of it leaked into
        :attr:`issuer` (ADR-0143 §2).
        """
        ...

    @property
    def provider_calls(self) -> int:
        """How many exchanges with the provider have happened so far."""
        ...

    @property
    def over_large(self) -> Sequence[BatchRequest] | None:
        """A batch refused as over-large, or ``None`` where no bound is declared."""
        ...

    def rebuilt(self) -> BatchCompleter:
        """A freshly constructed completer of equal issuer, over the same provider."""
        ...

    def with_credential_rotated(self) -> BatchCompleter:
        """A completer whose credential changed and whose issuer did not."""
        ...

    def with_issuer(self, issuer: str) -> BatchCompleter:
        """A completer configured for a different account, over the same provider."""
        ...

    def program(self, item_id: str, outcome: ProgrammedOutcome) -> None:
        """Fix how ``item_id`` will end once its batch settles."""
        ...

    def settle(self, handle: BatchHandle) -> None:
        """Settle every item of the batch, as a real provider eventually would."""
        ...

    def lapse_retention(self, handle: BatchHandle) -> None:
        """Put the batch past its results retention, so a fetch must refuse."""
        ...

    def set_results_expiry(self, handle: BatchHandle, when: datetime | None) -> None:
        """Fix what ``poll`` reports as this batch's results retention."""
        ...

    def transmitted(self, handle: BatchHandle) -> tuple[TransmittedItem, ...]:
        """What the provider actually received for this batch."""
        ...

    def hold_next_exchange(self) -> ExchangeGate:
        """Hold the provider's next exchange open, returning the gate to release it."""
        ...


#: Histories that are never a request, each refused whole with nothing submitted
#: (ADR-0143 §3). The tool-role turn is the one that makes ``complete``'s
#: "necessary condition, not a sufficient one" bite: the precondition does not
#: name it, and it is refused anyway.
_REFUSED_HISTORIES = [
    pytest.param([], id="empty-history"),
    pytest.param(
        [Message(role=Role.USER, content="hi"), Message(role=Role.ASSISTANT, content="hello")],
        id="ends-on-assistant",
    ),
    pytest.param(
        [Message(role=Role.USER, content="hi"), Message(role=Role.TOOL, content="{}", name="t")],
        id="holds-a-tool-turn",
    ),
]

#: One case per outcome kind, with the payload ADR-0143 §4 binds to it.
_OUTCOME_KINDS = [
    pytest.param(ProgrammedOutcome(kind=BatchOutcomeKind.SUCCEEDED), id="succeeded"),
    pytest.param(
        ProgrammedOutcome(kind=BatchOutcomeKind.FAILED, failure_kind=BatchFailureKind.RATE_LIMITED),
        id="failed",
    ),
    pytest.param(ProgrammedOutcome(kind=BatchOutcomeKind.EXPIRED), id="expired"),
    pytest.param(ProgrammedOutcome(kind=BatchOutcomeKind.CANCELLED), id="cancelled"),
]


def _by_id(outcomes: Sequence[BatchItemOutcome]) -> dict[str, BatchItemOutcome]:
    """Index outcomes the way ADR-0143 §4 obliges a caller to: by ``item_id``, never by position."""
    return {outcome.item_id: outcome for outcome in outcomes}


def _assert_caller_error(error: ModelError) -> None:
    """Assert the disposition ADR-0066 §3 fixes for a malformed argument."""
    assert not error.retryable, "a malformed argument reproduces on every attempt"
    assert not error.routable, "a malformed argument reproduces from every route"


class BatchCompleterContract:
    """The behavioural contract every ``BatchCompleter`` implementation must satisfy."""

    @pytest.fixture
    def completer(self) -> BatchCompleter:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def world(self) -> AbstractAsyncContextManager[BatchWorld]:
        """Override in a subclass: the subject plus control over its provider."""
        raise NotImplementedError

    # --- §1, §2: the shape of the seam ---------------------------------------

    def test_conforms_to_protocol(self, completer: BatchCompleter) -> None:
        assert isinstance(completer, BatchCompleter)

    def test_the_protocol_declares_exactly_submit_poll_and_fetch(self) -> None:
        declared = {
            name
            for name in vars(BatchCompleter)
            if not name.startswith("_") and callable(getattr(BatchCompleter, name, None))
        }
        assert declared == {"submit", "poll", "fetch"}, (
            "ADR-0143 §2 declares three members and no fourth; a `cancel` in particular "
            "is refused by §10 because its only honest guarantee would be that we asked"
        )

    def test_every_member_is_a_coroutine_function(self, completer: BatchCompleter) -> None:
        for name in ("submit", "poll", "fetch"):
            assert inspect.iscoroutinefunction(getattr(completer, name)), name

    # --- §3, §2: every refusable check lands before the provider is contacted --

    @pytest.mark.parametrize("messages", _REFUSED_HISTORIES)
    async def test_a_malformed_item_refuses_the_whole_batch_uncontacted(
        self, messages: list[Message]
    ) -> None:
        async with self.world() as world:
            before = world.provider_calls
            items = [a_request("good-one"), BatchRequest(item_id="bad-one", messages=messages)]

            with pytest.raises(ModelError) as caught:
                await world.completer.submit("key-1", items)

            _assert_caller_error(caught.value)
            assert world.provider_calls == before, (
                "ADR-0143 §3 refuses the whole batch before contacting any provider, "
                "and never submits the well-formed subset"
            )

    async def test_an_empty_batch_is_refused_uncontacted(self) -> None:
        async with self.world() as world:
            before = world.provider_calls

            with pytest.raises(ModelError) as caught:
                await world.completer.submit("key-1", [])

            _assert_caller_error(caught.value)
            assert world.provider_calls == before

    async def test_a_duplicate_item_id_is_refused_uncontacted(self) -> None:
        async with self.world() as world:
            before = world.provider_calls
            items = [a_request("twice"), a_request("other"), a_request("twice")]

            with pytest.raises(ModelError) as caught:
                await world.completer.submit("key-1", items)

            _assert_caller_error(caught.value)
            assert world.provider_calls == before

    @pytest.mark.parametrize(
        "key", [pytest.param("   ", id="blank"), pytest.param("\ud800", id="unencodable")]
    )
    async def test_a_batch_key_the_handle_cannot_carry_is_refused_uncontacted(
        self, key: str
    ) -> None:
        async with self.world() as world:
            before = world.provider_calls

            with pytest.raises(ModelError) as caught:
                await world.completer.submit(key, a_batch("one"))

            _assert_caller_error(caught.value)
            assert world.provider_calls == before, (
                "ADR-0143 §2 puts every refusable check on the near side of the "
                "acceptance window. A key `BatchHandle` would reject is such a "
                "check, and discovering it *after* the provider accepted leaves a "
                "paid batch whose only identifier never came back — and the key is "
                "deliberately not sent to the provider, so nothing could find it"
            )

    @pytest.mark.optional_obligation
    async def test_an_over_large_batch_is_refused_and_names_its_bound(self) -> None:
        async with self.world() as world:
            over_large = world.over_large
            if over_large is None:
                pytest.skip("this implementation declares no size bound, which ADR-0143 §7 permits")
            before = world.provider_calls

            with pytest.raises(ModelError) as caught:
                await world.completer.submit("key-1", over_large)

            _assert_caller_error(caught.value)
            assert world.provider_calls == before
            assert any(char.isdigit() for char in str(caught.value)), (
                "ADR-0143 §7 requires the refusal to state the bound it applied, so a "
                "caller obliged to split knows what to split to"
            )

    # --- §2: the handle, and what it is and is not ----------------------------

    async def test_the_handle_echoes_the_batch_key_byte_for_byte(self) -> None:
        async with self.world() as world:
            key = "  spaced key  "

            handle = await world.completer.submit(key, a_batch("one"))

            assert handle.batch_key == key, (
                "ADR-0143 §9 types batch_key NonBlankEncodableText and not Identifier "
                "precisely so the value survives unstripped"
            )

    async def test_two_submits_under_one_key_are_two_batches(self) -> None:
        async with self.world() as world:
            first = await world.completer.submit("same-key", a_batch("one"))
            second = await world.completer.submit("same-key", a_batch("two"))

            assert first.batch_id != second.batch_id, (
                "batch_key is not an idempotency key: ADR-0143 §2 says two submits "
                "under one key create two batches, and nothing deduplicates on it"
            )

    async def test_the_handle_carries_the_configured_issuer_and_no_credential(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one"))

            assert handle.issuer == world.issuer
            assert world.credential not in handle.issuer, (
                "ADR-0143 §2 requires issuer to be non-secret and never derived from "
                "the credential; handles are written to disk by the consumers this "
                "shape exists for"
            )

    async def test_a_rotated_credential_leaves_earlier_handles_valid(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one"))

            rotated = world.with_credential_rotated()
            status = await rotated.poll(handle)

            assert status.handle == handle, (
                "an issuer configured by the composition root survives a key rotation, "
                "which is the whole reason ADR-0143 §2 refuses to derive it from the "
                "credential"
            )

    async def test_a_freshly_constructed_completer_of_equal_issuer_accepts_the_handle(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one"))

            fresh = world.rebuilt()
            status = await fresh.poll(handle)

            assert status.handle == handle, (
                "object identity is not the test (ADR-0143 §2): a restarted process "
                "necessarily builds a new completer, and that is the case the shape exists for"
            )

    async def test_a_handle_from_another_issuer_is_a_caller_error(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one"))
            foreign = handle.model_copy(update={"issuer": f"{world.issuer}-elsewhere"})

            with pytest.raises(ModelError) as caught:
                await world.completer.poll(foreign)

            _assert_caller_error(caught.value)

    async def test_a_hand_built_handle_addresses_the_account_s_own_batch(self) -> None:
        async with self.world() as world:
            first = await world.completer.submit("key-1", a_batch("one"))
            second = await world.completer.submit("key-2", a_batch("two", "three"))
            world.settle(second)

            assembled = BatchHandle(
                batch_key="a key the caller never submitted under",
                batch_id=second.batch_id,
                issuer=world.issuer,
                submitted_at=first.submitted_at,
            )

            status = await world.completer.poll(assembled)
            outcomes = await world.completer.fetch(assembled)

            assert status.total == 2
            assert set(_by_id(outcomes)) == {"two", "three"}, (
                "ADR-0143 §2: a handle is an address, and one naming a real batch under "
                "its own issuer is answered for that batch. The seam neither "
                "authenticates handles nor pretends to"
            )

    def test_no_handle_field_is_a_count(self) -> None:
        assert set(BatchHandle.model_fields) == {
            "batch_key",
            "batch_id",
            "issuer",
            "submitted_at",
        }, (
            "ADR-0143 §2 limits the handle to what addresses the batch and forbids any "
            "field a later poll or fetch would have to agree with — in particular a "
            "count, which a hand-built handle could then contradict"
        )

    # --- §2: no member waits for the batch to settle --------------------------

    async def test_poll_returns_pending_rather_than_waiting(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one", "two"))

            async with asyncio.timeout(_SCENARIO_TIMEOUT):
                status = await world.completer.poll(handle)

            assert status.state is BatchState.PENDING
            assert status.settled < status.total

    async def test_fetch_refuses_a_pending_batch_rather_than_waiting(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one", "two"))

            async with asyncio.timeout(_SCENARIO_TIMEOUT):
                with pytest.raises(ModelError):
                    await world.completer.fetch(handle)

    # --- §3: one observation, deep enough to cover what the call reads --------

    async def test_appending_mid_flight_cannot_make_one_batch_describe_two(self) -> None:
        async with self.world() as world:
            items = a_batch("one", "two")
            handle = await self._submit_while(world, items, lambda: items.append(a_request("late")))

            transmitted = world.transmitted(handle)
            assert [item.item_id for item in transmitted] == ["one", "two"], (
                "ADR-0065's snapshot is taken on submit's first executed line, so an "
                "append while it is suspended reaches neither validation nor the wire"
            )

    async def test_mutating_a_request_mid_flight_cannot_make_one_batch_describe_two(self) -> None:
        async with self.world() as world:
            items = a_batch("one", "two")

            def rewrite() -> None:
                items[1].item_id = "renamed-mid-flight"

            handle = await self._submit_while(world, items, rewrite)

            transmitted = world.transmitted(handle)
            assert [item.item_id for item in transmitted] == ["one", "two"], (
                "a shallow copy of the outer sequence would leave the caller free to "
                "mutate a BatchRequest still in it; ADR-0143 §3 requires the snapshot "
                "to be deep enough to cover everything the call goes on to read"
            )

    async def test_mutating_a_requests_messages_mid_flight_cannot_make_one_batch_describe_two(
        self,
    ) -> None:
        async with self.world() as world:
            items = a_batch("one", "two")

            def append_a_turn() -> None:
                # The cast is the hazard, stated rather than hidden: ADR-0143 §9
                # fixes the annotation as ``Sequence[Message]``, and pydantic holds
                # such a field as a mutable ``list``. A caller writing this line
                # needs no cast at runtime — the field simply is a list — so an
                # implementation that trusted the annotation would be trusting a
                # promise the object does not make. This is the ``MemoryWrite``
                # holding a mutable ``MemoryRecord`` case ADR-0065 names by name.
                held = cast("list[Message]", items[0].messages)
                held.append(Message(role=Role.USER, content="and also this"))

            handle = await self._submit_while(world, items, append_a_turn)

            transmitted = world.transmitted(handle)
            first = next(item for item in transmitted if item.item_id == "one")
            assert len(first.turns) == 1, (
                "the same divergence one level down: freezing BatchRequest would not "
                "have closed it, because a Sequence field is held as a mutable list"
            )

    async def _submit_while(
        self,
        world: BatchWorld,
        items: list[BatchRequest],
        mutate: Callable[[], None],
    ) -> BatchHandle:
        """Submit ``items``, running ``mutate`` while the provider exchange is held.

        The mutation lands strictly after ``submit``'s first executed line and
        strictly before the provider is told anything, which is the only window in
        which ADR-0065's clause has content.
        """
        gate = world.hold_next_exchange()
        submitting = asyncio.ensure_future(world.completer.submit("key-1", items))
        async with asyncio.timeout(_SCENARIO_TIMEOUT):
            await gate.reached()
            mutate()
            gate.release()
            return await submitting

    # --- §4, §5: what fetch returns, and how it is matched --------------------

    async def test_fetch_returns_exactly_one_outcome_per_submitted_item(self) -> None:
        async with self.world() as world:
            world.program("two", ProgrammedOutcome(kind=BatchOutcomeKind.EXPIRED))
            handle = await world.completer.submit("key-1", a_batch("one", "two", "three"))
            world.settle(handle)

            outcomes = await world.completer.fetch(handle)

            assert len(outcomes) == 3
            assert set(_by_id(outcomes)) == {"one", "two", "three"}

    @pytest.mark.parametrize("programmed", _OUTCOME_KINDS)
    async def test_each_outcome_kind_carries_the_payload_bound_to_it(
        self, programmed: ProgrammedOutcome
    ) -> None:
        async with self.world() as world:
            world.program("only", programmed)
            handle = await world.completer.submit("key-1", a_batch("only"))
            world.settle(handle)

            outcome = _by_id(await world.completer.fetch(handle))["only"]

            assert outcome.kind is programmed.kind
            assert (outcome.message is not None) == (programmed.kind is BatchOutcomeKind.SUCCEEDED)
            assert (outcome.failure is not None) == (programmed.kind is BatchOutcomeKind.FAILED)
            if outcome.failure is not None:
                assert outcome.failure.kind is programmed.failure_kind

    async def test_outcomes_are_matched_by_id_and_never_by_position(self) -> None:
        async with self.world() as world:
            ids = ("alpha", "beta", "gamma", "delta")
            for index, item_id in enumerate(ids):
                world.program(item_id, ProgrammedOutcome(content=f"answer to {index}"))
            handle = await world.completer.submit("key-1", a_batch(*ids))
            world.settle(handle)

            outcomes = await world.completer.fetch(handle)

            indexed = _by_id(outcomes)
            for index, item_id in enumerate(ids):
                message = indexed[item_id].message
                assert message is not None
                assert message.content == f"answer to {index}", (
                    "ADR-0143 §4 leaves the order unspecified; a caller matches by "
                    "item_id, and this assertion is written so that it fails rather "
                    "than passes if an implementation happens to return submission order"
                )

    async def test_a_failing_item_does_not_destroy_the_others(self) -> None:
        async with self.world() as world:
            world.program(
                "bad",
                ProgrammedOutcome(
                    kind=BatchOutcomeKind.FAILED, failure_kind=BatchFailureKind.CONTENT_FILTER
                ),
            )
            handle = await world.completer.submit("key-1", a_batch("good", "bad", "also-good"))
            world.settle(handle)

            outcomes = _by_id(await world.completer.fetch(handle))

            assert outcomes["good"].kind is BatchOutcomeKind.SUCCEEDED
            assert outcomes["also-good"].kind is BatchOutcomeKind.SUCCEEDED
            failure = outcomes["bad"].failure
            assert failure is not None
            assert failure.kind is BatchFailureKind.CONTENT_FILTER
            assert not failure.kind.retryable, (
                "ADR-0029 §8's reason for returning rather than raising: an exception "
                "has no failure.kind.retryable for a retry decision to be made from"
            )

    async def test_an_expired_item_is_expired_and_never_failed(self) -> None:
        async with self.world() as world:
            world.program("timed-out", ProgrammedOutcome(kind=BatchOutcomeKind.EXPIRED))
            handle = await world.completer.submit("key-1", a_batch("timed-out"))
            world.settle(handle)

            outcome = _by_id(await world.completer.fetch(handle))["timed-out"]

            assert outcome.kind is BatchOutcomeKind.EXPIRED, (
                "the processing window closing is ADR-0143 §6's EXPIRED outcome and not "
                "a failure; there is deliberately no counterpart to ModelTimeoutError"
            )
            assert outcome.failure is None

    async def test_an_item_id_survives_the_round_trip_byte_for_byte(self) -> None:
        async with self.world() as world:
            spaced = "  padded id  "
            handle = await world.completer.submit("key-1", [a_request(spaced)])
            world.settle(handle)

            outcomes = await world.completer.fetch(handle)

            assert [outcome.item_id for outcome in outcomes] == [spaced], (
                "ADR-0143 §3 forbids an implementation minting, rewriting or "
                "normalising an item_id, and §4 has the caller matching on it"
            )

    # --- §6, §9: retention, and the counts a status carries -------------------

    async def test_the_results_retention_is_surfaced_when_the_provider_states_one(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one"))
            world.settle(handle)
            when = datetime.fromisoformat("2099-01-01T00:00:00+00:00")
            world.set_results_expiry(handle, when)

            status = await world.completer.poll(handle)

            assert status.results_expire_at == when

    async def test_a_lapsed_fetch_raises_and_never_short_returns(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one", "two"))
            world.settle(handle)
            world.lapse_retention(handle)

            with pytest.raises(ModelError):
                await world.completer.fetch(handle)

    async def test_a_pending_batch_reports_counts_within_bounds(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one", "two", "three"))

            status = await world.completer.poll(handle)

            assert status.total == 3
            assert 0 <= status.settled <= status.total
            assert status.state is BatchState.PENDING, (
                "an implementation whose provider reports no in-flight progress reports "
                "settled as 0 until the batch completes; ADR-0143 §9 accepts that"
            )

    async def test_a_settled_batch_is_complete_and_its_total_matches_the_outcomes(self) -> None:
        async with self.world() as world:
            handle = await world.completer.submit("key-1", a_batch("one", "two", "three"))
            world.settle(handle)

            status = await world.completer.poll(handle)
            outcomes = await world.completer.fetch(handle)

            assert status.state is BatchState.COMPLETE
            assert status.settled == status.total == len(outcomes)

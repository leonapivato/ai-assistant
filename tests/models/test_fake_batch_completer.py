"""``FakeBatchCompleter`` through the shared ``BatchCompleter`` conformance suite.

The canonical fake's binding, and the one the Protocol-triad check
(``tests/core/test_protocol_triad.py``) reads: without a ``Test…Contract``
subclass whose subject fixture supplies the fake and whose inherited obligations
actually ran, the fake is unverified however many files exist.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from batch_completer_contract import BatchCompleterContract, TransmittedItem, a_batch, a_request

from ai_assistant.testing import (
    DEFAULT_BATCH_ISSUER,
    BatchProvider,
    ExchangeGate,
    FakeBatchCompleter,
    ProgrammedOutcome,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import datetime

    from ai_assistant.core.protocols import BatchCompleter
    from ai_assistant.core.types import BatchHandle, BatchRequest

#: Small enough that the over-large case is one line rather than a vendor-sized
#: batch, which is the whole reason `max_items` is a constructor argument.
_MAX_ITEMS = 8

#: What the fake stands in for a credential with. It is never sent anywhere; the
#: suite reads it only to assert none of it leaked into `issuer`.
_FAKE_CREDENTIAL = "fake-batch-credential-not-a-key"


@dataclass
class _FakeWorld:
    """The suite's world over a :class:`FakeBatchCompleter` and its provider."""

    subject: FakeBatchCompleter
    provider: BatchProvider
    issuer_label: str
    credential_value: str = _FAKE_CREDENTIAL

    @property
    def completer(self) -> BatchCompleter:
        return self.subject

    @property
    def issuer(self) -> str:
        return self.issuer_label

    @property
    def credential(self) -> str:
        return self.credential_value

    @property
    def provider_calls(self) -> int:
        return self.provider.calls

    @property
    def over_large(self) -> Sequence[BatchRequest] | None:
        return a_batch(*(f"item-{n}" for n in range(_MAX_ITEMS + 1)))

    def rebuilt(self) -> BatchCompleter:
        return FakeBatchCompleter(
            issuer=self.issuer_label, provider=self.provider, max_items=_MAX_ITEMS
        )

    def with_credential_rotated(self) -> BatchCompleter:
        # The fake reaches its provider by reference rather than by credential, so
        # a rotation is exactly a fresh completer of equal issuer over the same
        # provider — which is the property ADR-0143 §2 asks to hold.
        self.credential_value = f"{_FAKE_CREDENTIAL}-rotated"
        return self.rebuilt()

    def with_issuer(self, issuer: str) -> BatchCompleter:
        return FakeBatchCompleter(issuer=issuer, provider=self.provider, max_items=_MAX_ITEMS)

    def program(self, item_id: str, outcome: ProgrammedOutcome) -> None:
        self.provider.program(item_id, outcome)

    def settle(self, handle: BatchHandle) -> None:
        self.provider.settle(handle.batch_id)

    def lapse_retention(self, handle: BatchHandle) -> None:
        self.provider.lapse_retention(handle.batch_id)

    def set_results_expiry(self, handle: BatchHandle, when: datetime | None) -> None:
        self.provider.set_results_expiry(handle.batch_id, when)

    def transmitted(self, handle: BatchHandle) -> tuple[TransmittedItem, ...]:
        return tuple(
            TransmittedItem(
                item_id=item.item_id,
                turns=tuple((message.role.value, message.content) for message in item.messages),
            )
            for item in self.provider.batches[handle.batch_id].items
        )

    def hold_next_exchange(self) -> ExchangeGate:
        gate = ExchangeGate()
        self.provider.gate = gate
        return gate


class TestFakeBatchCompleterContract(BatchCompleterContract):
    """``FakeBatchCompleter`` passes the shared ``BatchCompleter`` contract."""

    @pytest.fixture
    def completer(self) -> BatchCompleter:
        return FakeBatchCompleter()

    @asynccontextmanager
    async def world(self) -> AsyncIterator[_FakeWorld]:
        provider = BatchProvider()
        subject = FakeBatchCompleter(
            issuer=DEFAULT_BATCH_ISSUER, provider=provider, max_items=_MAX_ITEMS
        )
        yield _FakeWorld(subject=subject, provider=provider, issuer_label=DEFAULT_BATCH_ISSUER)


class TestTheFakeBeyondTheContract:
    """What the fake promises its own users, over and above the shared contract."""

    async def test_a_held_gate_only_releases_the_call_it_caught(self) -> None:
        provider = BatchProvider()
        completer = FakeBatchCompleter(provider=provider)

        handle = await completer.submit("key-1", [a_request("one")])

        assert provider.calls == 1
        assert completer.submitted_items(handle)[0].item_id == "one"

    async def test_outcomes_come_back_in_neither_submission_nor_reverse_order(self) -> None:
        completer = FakeBatchCompleter()
        ids = ("a", "b", "c", "d")
        handle = await completer.submit("key-1", a_batch(*ids))
        completer.settle(handle)

        returned = tuple(outcome.item_id for outcome in await completer.fetch(handle))

        assert returned != ids
        assert returned != tuple(reversed(ids)), (
            "a consumer that assumed *any* fixed relation to submission order should "
            "fail here rather than against a real provider (ADR-0143 §4)"
        )
        assert set(returned) == set(ids)

    async def test_a_second_completer_over_one_provider_reaches_the_same_batch(self) -> None:
        provider = BatchProvider()
        first = FakeBatchCompleter(provider=provider)
        handle = await first.submit("key-1", [a_request("one")])

        second = FakeBatchCompleter(provider=provider)
        status = await second.poll(handle)

        assert status.handle == handle
        assert status.total == 1

    async def test_a_programmed_success_carries_its_own_reply(self) -> None:
        completer = FakeBatchCompleter()
        completer.program("one", ProgrammedOutcome(content="a specific answer"))
        handle = await completer.submit("key-1", [a_request("one")])
        completer.settle(handle)

        outcome = (await completer.fetch(handle))[0]

        assert outcome.message is not None
        assert outcome.message.content == "a specific answer"

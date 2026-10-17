"""The canonical FakeTelegramIntakeRecord passes the shared conformance suite.

This is what lets the line's reader and writer trust
``ai_assistant.testing.FakeTelegramIntakeRecord`` as a stand-in for the store: it is
held to the same contract as ``SqliteTelegramIntakeRecord``. Below the binding, what
only the fake has: the fault it can be told to raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from telegram_intake_record_contract import (
    ACTIVATION,
    POLLED,
    TelegramIntakeRecordContract,
    TelegramIntakeRecordFactory,
)

from ai_assistant.core.errors import TelegramIntakeRecordError
from ai_assistant.testing import FakeTelegramIntakeRecord

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.protocols import TelegramIntakeRecord

pytestmark = pytest.mark.anyio

#: The fake's default bound, restated rather than imported: a default changed without
#: this test noticing is the drift worth failing on.
_KEPT_CALLS_DEFAULT = 1000


class TestFakeTelegramIntakeRecordContract(TelegramIntakeRecordContract):
    """Runs FakeTelegramIntakeRecord through the shared TelegramIntakeRecord suite."""

    @pytest.fixture
    def record(self) -> TelegramIntakeRecord:
        return FakeTelegramIntakeRecord()

    @pytest.fixture
    def factory(self) -> TelegramIntakeRecordFactory:
        def build(
            *, kept_calls: int = _KEPT_CALLS_DEFAULT, new_id: Callable[[], str] | None = None
        ) -> TelegramIntakeRecord:
            if new_id is None:
                return FakeTelegramIntakeRecord(kept_calls=kept_calls)
            return FakeTelegramIntakeRecord(kept_calls=kept_calls, new_id=new_id)

        return build


async def test_an_arranged_fault_fails_the_next_member_and_touches_nothing() -> None:
    record = FakeTelegramIntakeRecord()
    record.fail_next()

    with pytest.raises(TelegramIntakeRecordError):
        await record.take_in([10], activation_id=ACTIVATION)

    assert await record.recorded([10]) == {}
    assert await record.take_in([10], activation_id=ACTIVATION) == (10,)


async def test_a_malformed_argument_is_refused_before_an_arranged_fault() -> None:
    record = FakeTelegramIntakeRecord()
    record.fail_next()

    with pytest.raises(ValueError, match="update id"):
        await record.claim_reply(-1)
    with pytest.raises(TelegramIntakeRecordError):
        await record.claim_poll()


async def test_the_default_bound_keeps_a_thousand_finished_polls() -> None:
    record = FakeTelegramIntakeRecord()
    claims = [await record.claim_poll() for _ in range(_KEPT_CALLS_DEFAULT + 1)]
    for claim in claims:
        await record.finish(claim.attempt, POLLED)

    assert await record.call(claims[0].attempt) is None
    assert await record.call(claims[1].attempt) is not None


@pytest.mark.parametrize("kept_calls", [0, -1, 2**63, True, 1.5], ids=repr)
def test_a_bound_below_one_is_refused(kept_calls: object) -> None:
    with pytest.raises(ValueError, match="kept_calls"):
        FakeTelegramIntakeRecord(kept_calls=kept_calls)  # type: ignore[arg-type]

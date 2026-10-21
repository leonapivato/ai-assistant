"""Shared conformance suite for the TelegramIntakeRecord Protocol (ADR-0323 §5, §13:2).

Every ``TelegramIntakeRecord`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`TelegramIntakeRecordContract` and supplies two fixtures: ``record``, the
subject at its defaults, and ``factory``, which builds one with a chosen retention
bound and attempt id factory.

The cases follow the contract's own order: the intake (§5:8 to §5:10), the offset and
the confirm rule (§5:6), the line's own call records and their once-only rules (§5:9,
§6:3, §6:10, §13:2), what the record keeps, and the data rights (ADR-0004 §6). What
only a persistent store owes — the file's mode, surviving a reopen, a backend fault —
is the store's own test.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Final, Protocol

import pytest

from ai_assistant.core.errors import TelegramIntakeRecordError
from ai_assistant.core.protocols import TelegramIntakeRecord
from ai_assistant.core.types import (
    TelegramCallKind,
    TelegramCallOutcome,
    TelegramFailure,
    TelegramIntake,
    TelegramIntakeKind,
    TelegramOutcome,
    TelegramPollOutcome,
    TelegramSendOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.anyio

#: The activation most cases take updates in under.
ACTIVATION: Final = "activation-0001"

DONE: Final = TelegramOutcome()
SENT: Final = TelegramSendOutcome(message_id=7)
POLLED: Final = TelegramPollOutcome()


def failed(failure: TelegramFailure) -> TelegramOutcome:
    """An outcome carrying ``failure``.

    Args:
        failure: Why the call was not done.

    Returns:
        The outcome.
    """
    return TelegramOutcome(failure=failure)


#: Every failure Telegram's answer, or its silence, can end a call with, by whether a
#: retry is allowed (§6:3 to §6:5).
RETRYABLE: Final = (TelegramFailure.NOT_WRITTEN, TelegramFailure.RATE_LIMITED)
FINAL: Final = (
    TelegramFailure.UNAVAILABLE,
    TelegramFailure.OTHER_CHAT,
    TelegramFailure.REFUSED,
    TelegramFailure.UNKNOWN,
)


class TelegramIntakeRecordFactory(Protocol):
    """Builds a subject with a chosen retention bound and attempt id factory."""

    def __call__(
        self, *, kept_calls: int = ..., new_id: Callable[[], str] | None = ...
    ) -> TelegramIntakeRecord:
        """Build a subject.

        Args:
            kept_calls: How many finished polls and typing indicators it keeps.
            new_id: The attempt id factory, or ``None`` for the implementation's own.
        """
        ...


def sequential_ids(prefix: str = "attempt") -> Callable[[], str]:
    """An attempt id factory minting ``prefix-1``, ``prefix-2`` and on.

    Args:
        prefix: What every id starts with.

    Returns:
        The factory.
    """
    numbers = count(1)
    return lambda: f"{prefix}-{next(numbers)}"


class TelegramIntakeRecordContract:
    """Behaviour every ``TelegramIntakeRecord`` implementation must exhibit (ADR-0323)."""

    @pytest.fixture
    def record(self) -> TelegramIntakeRecord:
        """Override in a subclass with any conforming subject at its defaults."""
        raise NotImplementedError

    @pytest.fixture
    def factory(self) -> TelegramIntakeRecordFactory:
        """Override in a subclass with a builder of conforming subjects."""
        raise NotImplementedError

    # --- the intake (§5:8 to §5:10) -----------------------------------------------

    async def test_the_subject_is_a_telegram_intake_record(
        self, record: TelegramIntakeRecord
    ) -> None:
        assert isinstance(record, TelegramIntakeRecord)

    async def test_take_in_marks_each_new_update_once_ascending(
        self, record: TelegramIntakeRecord
    ) -> None:
        marked = await record.take_in([12, 10, 12, 11], activation_id=ACTIVATION)

        assert marked == (10, 11, 12)
        held = await record.recorded([10, 11, 12])
        assert held == {
            one: TelegramIntake(
                update_id=one, kind=TelegramIntakeKind.TAKEN_IN, activation_id=ACTIVATION
            )
            for one in (10, 11, 12)
        }

    async def test_an_update_taken_in_keeps_the_activation_that_took_it_first(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.take_in([10], activation_id=ACTIVATION)

        marked = await record.take_in([10, 11], activation_id="activation-0002")

        assert marked == (11,)
        held = await record.recorded([10, 11])
        assert held[10].activation_id == ACTIVATION
        assert held[11].activation_id == "activation-0002"

    async def test_a_duplicate_fetch_after_a_restart_takes_nothing_in_again(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        # §5:10 over one subject: an interrupted activation's updates stay its own.
        record = factory()
        await record.take_in([10, 11], activation_id=ACTIVATION)

        assert await record.take_in([10, 11], activation_id="activation-0002") == ()

    async def test_an_answered_update_is_never_taken_in(self, record: TelegramIntakeRecord) -> None:
        assert await record.claim_reply(10) is not None

        assert await record.take_in([10], activation_id=ACTIVATION) == ()
        held = await record.recorded([10])
        assert held == {10: TelegramIntake(update_id=10, kind=TelegramIntakeKind.ANSWERED)}

    async def test_recorded_leaves_out_what_it_does_not_hold(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.take_in([10], activation_id=ACTIVATION)

        held = await record.recorded([9, 10, 11])

        assert set(held) == {10}

    async def test_recorded_hands_back_a_fresh_mapping(self, record: TelegramIntakeRecord) -> None:
        await record.take_in([10], activation_id=ACTIVATION)
        first = await record.recorded([10])
        if isinstance(first, dict):
            first.clear()

        assert set(await record.recorded([10])) == {10}

    async def test_taking_in_nothing_marks_nothing(self, record: TelegramIntakeRecord) -> None:
        assert await record.take_in([], activation_id=ACTIVATION) == ()
        assert await record.recorded([]) == {}

    @pytest.mark.parametrize(
        "update_ids",
        [
            "10",
            b"10",
            {10},
            (one for one in [10]),
            [-1],
            [2**63],
            [True],
            [10.0],
            ["10"],
            list(range(1001)),
        ],
        ids=[
            "str",
            "bytes",
            "set",
            "generator",
            "negative",
            "past-the-ceiling",
            "bool",
            "float",
            "str-id",
            "too-many",
        ],
    )
    async def test_malformed_update_ids_are_refused_before_anything_is_written(
        self, record: TelegramIntakeRecord, update_ids: object
    ) -> None:
        with pytest.raises(ValueError, match="update"):
            await record.take_in(update_ids, activation_id=ACTIVATION)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="update"):
            await record.recorded(update_ids)  # type: ignore[arg-type]

        assert (await record.export()).intake == ()

    async def test_an_enormous_sequence_is_refused_without_being_read_whole(
        self, record: TelegramIntakeRecord
    ) -> None:
        enormous = range(10**15)

        with pytest.raises(ValueError, match="update_ids"):
            await record.take_in(enormous, activation_id=ACTIVATION)
        with pytest.raises(ValueError, match="update_ids"):
            await record.recorded(enormous)

        assert (await record.export()).intake == ()

    async def test_a_thousand_update_ids_are_accepted(self, record: TelegramIntakeRecord) -> None:
        marked = await record.take_in(range(1000), activation_id=ACTIVATION)

        assert marked == tuple(range(1000))

    @pytest.mark.parametrize("activation_id", ["", "   ", None, 7], ids=str)
    async def test_a_malformed_activation_is_refused(
        self, record: TelegramIntakeRecord, activation_id: object
    ) -> None:
        with pytest.raises(ValueError, match="activation_id"):
            await record.take_in([10], activation_id=activation_id)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="activation_id"):
            await record.claim_typing(activation_id)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="activation_id"):
            await record.claim_interrupted(activation_id)  # type: ignore[arg-type]

        exported = await record.export()
        assert (exported.intake, exported.calls) == ((), ())

    # --- the offset and the confirm rule (§5:6, §11:11) ------------------------------

    async def test_a_fresh_record_owes_no_confirmation(self, record: TelegramIntakeRecord) -> None:
        claim = await record.claim_poll()

        assert claim.offset is None
        held = await record.call(claim.attempt)
        assert held is not None
        assert held.kind is TelegramCallKind.POLL
        assert held.offset is None

    async def test_a_poll_carries_the_offset_after_what_was_dealt_with(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.confirm_through(5)

        claim = await record.claim_poll()

        assert claim.offset == 6
        held = await record.call(claim.attempt)
        assert held is not None
        assert held.offset == 6

    async def test_what_is_owed_is_never_lowered(self, record: TelegramIntakeRecord) -> None:
        await record.confirm_through(9)
        await record.confirm_through(3)

        assert (await record.claim_poll()).offset == 10
        await record.confirm_through(12)
        assert (await record.claim_poll()).offset == 13

    async def test_a_done_poll_settles_what_it_confirmed(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.confirm_through(5)
        claim = await record.claim_poll()

        await record.finish(claim.attempt, POLLED)

        assert (await record.claim_poll()).offset is None
        assert (await record.export()).offset is None

    @pytest.mark.parametrize("failure", [*RETRYABLE, *FINAL], ids=str)
    async def test_a_poll_not_done_leaves_the_confirmation_owed(
        self, record: TelegramIntakeRecord, failure: TelegramFailure
    ) -> None:
        await record.take_in([5], activation_id=ACTIVATION)
        await record.confirm_through(5)
        claim = await record.claim_poll()

        await record.finish(claim.attempt, TelegramPollOutcome(failure=failure))

        assert (await record.claim_poll()).offset == 6
        assert set(await record.recorded([5])) == {5}

    async def test_a_done_poll_drops_the_updates_telegram_has_forgotten(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.take_in([4, 5], activation_id=ACTIVATION)
        await record.confirm_through(4)
        claim = await record.claim_poll()
        await record.take_in([6], activation_id=ACTIVATION)

        await record.finish(claim.attempt, POLLED)

        assert set(await record.recorded([4, 5, 6])) == {5, 6}

    async def test_a_done_poll_keeps_a_confirmation_owed_since_it_was_claimed(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.confirm_through(4)
        claim = await record.claim_poll()
        await record.confirm_through(8)

        await record.finish(claim.attempt, POLLED)

        assert (await record.claim_poll()).offset == 9

    async def test_a_done_poll_with_no_offset_drops_nothing(
        self, record: TelegramIntakeRecord
    ) -> None:
        claim = await record.claim_poll()
        await record.take_in([4], activation_id=ACTIVATION)

        await record.finish(claim.attempt, POLLED)

        assert set(await record.recorded([4])) == {4}

    async def test_the_largest_update_can_be_dealt_with(self, record: TelegramIntakeRecord) -> None:
        await record.confirm_through(2**63 - 2)

        assert (await record.claim_poll()).offset == 2**63 - 1

    @pytest.mark.parametrize("update_id", [-1, 2**63 - 1, True, 4.0, "4", None], ids=repr)
    async def test_a_malformed_confirmation_is_refused(
        self, record: TelegramIntakeRecord, update_id: object
    ) -> None:
        with pytest.raises(ValueError, match="update id"):
            await record.confirm_through(update_id)  # type: ignore[arg-type]

        assert (await record.claim_poll()).offset is None

    # --- the line's own call records (§13:2) -----------------------------------------

    async def test_a_typing_indicator_is_claimed_with_no_outcome(
        self, record: TelegramIntakeRecord
    ) -> None:
        attempt = await record.claim_typing(ACTIVATION)

        held = await record.call(attempt)
        assert held is not None
        assert held.kind is TelegramCallKind.TYPING
        assert held.activation_id == ACTIVATION
        assert not held.finished
        assert held.outcome is None

    async def test_every_renewal_of_the_indicator_is_a_call_of_its_own(
        self, record: TelegramIntakeRecord
    ) -> None:
        first = await record.claim_typing(ACTIVATION)
        second = await record.claim_typing(ACTIVATION)

        assert first != second

    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            (DONE, TelegramCallOutcome.DONE),
            (SENT, TelegramCallOutcome.DONE),
            (failed(TelegramFailure.UNKNOWN), TelegramCallOutcome.UNKNOWN),
            (failed(TelegramFailure.REFUSED), TelegramCallOutcome.NOT_DONE),
            (failed(TelegramFailure.NOT_WRITTEN), TelegramCallOutcome.NOT_DONE),
            (
                TelegramOutcome(failure=TelegramFailure.RATE_LIMITED, retry_after_seconds=3),
                TelegramCallOutcome.NOT_DONE,
            ),
            (failed(TelegramFailure.UNAVAILABLE), TelegramCallOutcome.NOT_DONE),
            (failed(TelegramFailure.OTHER_CHAT), TelegramCallOutcome.NOT_DONE),
        ],
        ids=str,
    )
    async def test_finish_writes_the_outcome_in_section_13s_words(
        self,
        record: TelegramIntakeRecord,
        outcome: TelegramOutcome,
        expected: TelegramCallOutcome,
    ) -> None:
        attempt = await record.claim_typing(ACTIVATION)

        await record.finish(attempt, outcome)

        held = await record.call(attempt)
        assert held is not None
        assert held.finished
        assert held.failure is outcome.failure
        assert held.outcome is expected

    async def test_a_call_is_finished_once(self, record: TelegramIntakeRecord) -> None:
        attempt = await record.claim_typing(ACTIVATION)
        await record.finish(attempt, failed(TelegramFailure.UNKNOWN))

        with pytest.raises(TelegramIntakeRecordError):
            await record.finish(attempt, DONE)

        held = await record.call(attempt)
        assert held is not None
        assert held.outcome is TelegramCallOutcome.UNKNOWN

    async def test_finishing_an_attempt_never_claimed_is_refused(
        self, record: TelegramIntakeRecord
    ) -> None:
        with pytest.raises(TelegramIntakeRecordError):
            await record.finish("never-claimed", DONE)

        assert await record.call("never-claimed") is None

    @pytest.mark.parametrize(
        ("attempt", "outcome"),
        [("", DONE), ("  ", DONE), (None, DONE), ("attempt-1", None), ("attempt-1", "done")],
        ids=["blank", "spaces", "none", "no-outcome", "str-outcome"],
    )
    async def test_a_malformed_finish_is_refused_before_anything_is_written(
        self, factory: TelegramIntakeRecordFactory, attempt: object, outcome: object
    ) -> None:
        record = factory(new_id=sequential_ids())
        assert await record.claim_typing(ACTIVATION) == "attempt-1"

        with pytest.raises(ValueError, match=r"attempt|outcome"):
            await record.finish(attempt, outcome)  # type: ignore[arg-type]

        held = await record.call("attempt-1")
        assert held is not None
        assert not held.finished

    @pytest.mark.parametrize("attempt", ["", None, 3], ids=str)
    async def test_a_malformed_attempt_is_refused_by_the_read(
        self, record: TelegramIntakeRecord, attempt: object
    ) -> None:
        with pytest.raises(ValueError, match="attempt"):
            await record.call(attempt)  # type: ignore[arg-type]

    async def test_attempts_are_the_factorys_and_never_repeat(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        minted = iter(["same", "same", "same", "other"])
        record = factory(new_id=lambda: next(minted))

        first = await record.claim_typing(ACTIVATION)
        second = (await record.claim_poll()).attempt

        assert (first, second) == ("same", "other")

    async def test_a_factory_that_keeps_repeating_itself_claims_nothing(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        record = factory(new_id=lambda: "same")
        await record.claim_typing(ACTIVATION)

        with pytest.raises(TelegramIntakeRecordError):
            await record.claim_reply(10)

        assert await record.recorded([10]) == {}
        assert len((await record.export()).calls) == 1

    # --- the once-only rules (§5:9, §6:3, §6:10) ------------------------------------

    async def test_answering_a_non_text_message_claims_its_fixed_reply(
        self, record: TelegramIntakeRecord
    ) -> None:
        attempt = await record.claim_reply(10)

        assert attempt is not None
        held = await record.call(attempt)
        assert held is not None
        assert held.kind is TelegramCallKind.FIXED_REPLY
        assert held.update_id == 10
        assert held.outcome is None
        assert (await record.recorded([10]))[10].kind is TelegramIntakeKind.ANSWERED

    async def test_a_stop_command_answered_is_told_from_a_new_one_and_never_taken_in(
        self, record: TelegramIntakeRecord
    ) -> None:
        """ADR-0332 §8:6: a stop is recorded as an update answered, before it is acted on.

        The reader reads :meth:`recorded` before its claim: nothing there is a new stop,
        and an update held as answered is a repeat, which stops nothing and is never
        taken in as input (§8:3).
        """
        assert await record.recorded([10]) == {}

        assert await record.claim_reply(10) is not None

        assert await record.recorded([10]) == {
            10: TelegramIntake(update_id=10, kind=TelegramIntakeKind.ANSWERED)
        }
        assert await record.claim_reply(10) is None
        assert await record.take_in([10], activation_id=ACTIVATION) == ()

    @pytest.mark.parametrize(
        "earlier",
        [None, DONE, SENT, *(failed(one) for one in FINAL)],
        ids=["open", "done", "sent", *(str(one) for one in FINAL)],
    )
    async def test_a_fixed_reply_is_never_sent_twice(
        self, record: TelegramIntakeRecord, earlier: TelegramOutcome | None
    ) -> None:
        attempt = await record.claim_reply(10)
        assert attempt is not None
        if earlier is not None:
            await record.finish(attempt, earlier)

        assert await record.claim_reply(10) is None
        assert len((await record.export()).calls) == 1

    @pytest.mark.parametrize("failure", RETRYABLE, ids=str)
    async def test_a_fixed_reply_telegram_did_not_take_may_be_tried_again(
        self, record: TelegramIntakeRecord, failure: TelegramFailure
    ) -> None:
        first = await record.claim_reply(10)
        assert first is not None
        await record.finish(first, failed(failure))

        second = await record.claim_reply(10)

        assert second is not None
        assert second != first
        assert await record.claim_reply(10) is None

    async def test_an_update_taken_in_is_never_answered(self, record: TelegramIntakeRecord) -> None:
        await record.take_in([10], activation_id=ACTIVATION)

        assert await record.claim_reply(10) is None
        assert (await record.export()).calls == ()

    async def test_each_update_is_answered_on_its_own(self, record: TelegramIntakeRecord) -> None:
        assert await record.claim_reply(10) is not None

        assert await record.claim_reply(11) is not None

    @pytest.mark.parametrize("update_id", [-1, 2**63, True, "10", None], ids=repr)
    async def test_a_malformed_reply_is_refused(
        self, record: TelegramIntakeRecord, update_id: object
    ) -> None:
        with pytest.raises(ValueError, match="update id"):
            await record.claim_reply(update_id)  # type: ignore[arg-type]

        assert (await record.export()).calls == ()

    @pytest.mark.parametrize(
        "earlier",
        [None, DONE, *(failed(one) for one in FINAL)],
        ids=["open", "done", *(str(one) for one in FINAL)],
    )
    async def test_a_restarts_message_is_sent_once_per_activation(
        self, record: TelegramIntakeRecord, earlier: TelegramOutcome | None
    ) -> None:
        attempt = await record.claim_interrupted(ACTIVATION)
        assert attempt is not None
        held = await record.call(attempt)
        assert held is not None
        assert held.kind is TelegramCallKind.INTERRUPTED
        assert held.activation_id == ACTIVATION
        if earlier is not None:
            await record.finish(attempt, earlier)

        assert await record.claim_interrupted(ACTIVATION) is None
        assert await record.claim_interrupted("activation-0002") is not None

    @pytest.mark.parametrize("failure", RETRYABLE, ids=str)
    async def test_a_restarts_message_telegram_did_not_take_may_be_tried_again(
        self, record: TelegramIntakeRecord, failure: TelegramFailure
    ) -> None:
        first = await record.claim_interrupted(ACTIVATION)
        assert first is not None
        await record.finish(first, failed(failure))

        assert await record.claim_interrupted(ACTIVATION) is not None

    # --- what the record keeps ------------------------------------------------------

    async def test_only_the_newest_finished_polls_and_indicators_are_kept(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        record = factory(kept_calls=2, new_id=sequential_ids())
        for _ in range(2):
            await record.finish((await record.claim_poll()).attempt, POLLED)
        typing = await record.claim_typing(ACTIVATION)

        await record.finish(typing, DONE)

        assert await record.call("attempt-1") is None
        assert [one.attempt for one in (await record.export()).calls] == ["attempt-2", "attempt-3"]

    async def test_the_largest_bound_accepted_still_lets_every_call_finish(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        record = factory(kept_calls=2**63 - 1)
        typing = await record.claim_typing(ACTIVATION)
        poll = await record.claim_poll()

        await record.finish(typing, DONE)
        await record.finish(poll.attempt, POLLED)

        assert [one.outcome for one in (await record.export()).calls] == [
            TelegramCallOutcome.DONE,
            TelegramCallOutcome.DONE,
        ]

    async def test_a_claim_with_no_outcome_is_never_dropped(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        record = factory(kept_calls=1, new_id=sequential_ids())
        open_poll = await record.claim_poll()
        open_typing = await record.claim_typing(ACTIVATION)
        for _ in range(3):
            await record.finish((await record.claim_poll()).attempt, POLLED)

        assert await record.call(open_poll.attempt) is not None
        assert await record.call(open_typing) is not None
        await record.finish(open_typing, failed(TelegramFailure.UNKNOWN))

    async def test_the_bound_never_reaches_a_fixed_reply_or_a_restarts_message(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        record = factory(kept_calls=1)
        reply = await record.claim_reply(10)
        interrupted = await record.claim_interrupted(ACTIVATION)
        assert reply is not None
        assert interrupted is not None
        await record.finish(reply, SENT)
        await record.finish(interrupted, SENT)
        for _ in range(3):
            await record.finish((await record.claim_poll()).attempt, POLLED)

        assert await record.call(reply) is not None
        assert await record.call(interrupted) is not None

    async def test_a_done_poll_drops_the_finished_replies_to_what_it_confirmed(
        self, record: TelegramIntakeRecord
    ) -> None:
        finished = await record.claim_reply(4)
        still_open = await record.claim_reply(5)
        later = await record.claim_reply(9)
        assert finished is not None
        assert still_open is not None
        assert later is not None
        await record.finish(finished, SENT)
        await record.finish(later, SENT)
        await record.confirm_through(8)

        await record.finish((await record.claim_poll()).attempt, POLLED)

        assert await record.call(finished) is None
        assert await record.call(still_open) is not None
        assert await record.call(later) is not None
        assert set(await record.recorded([4, 5, 9])) == {9}
        # The reply still open forbids another, whatever Telegram has forgotten.
        assert await record.claim_reply(5) is None

    # --- the data rights (ADR-0004 §6) ----------------------------------------------

    async def test_export_carries_everything_in_its_order(
        self, factory: TelegramIntakeRecordFactory
    ) -> None:
        record = factory(new_id=sequential_ids())
        await record.take_in([12, 11], activation_id=ACTIVATION)
        reply = await record.claim_reply(13)
        typing = await record.claim_typing(ACTIVATION)
        assert reply is not None
        await record.finish(typing, DONE)
        await record.confirm_through(13)

        exported = await record.export()

        assert exported.offset == 14
        assert [(one.update_id, one.kind) for one in exported.intake] == [
            (11, TelegramIntakeKind.TAKEN_IN),
            (12, TelegramIntakeKind.TAKEN_IN),
            (13, TelegramIntakeKind.ANSWERED),
        ]
        assert [(one.attempt, one.kind, one.outcome) for one in exported.calls] == [
            ("attempt-1", TelegramCallKind.FIXED_REPLY, None),
            ("attempt-2", TelegramCallKind.TYPING, TelegramCallOutcome.DONE),
        ]

    async def test_clear_erases_everything_and_counts_it(
        self, record: TelegramIntakeRecord
    ) -> None:
        await record.take_in([10, 11], activation_id=ACTIVATION)
        await record.claim_reply(12)
        await record.claim_poll()
        await record.confirm_through(12)

        removed = await record.clear()

        assert removed == 5
        exported = await record.export()
        assert (exported.offset, exported.intake, exported.calls) == (None, (), ())
        assert await record.take_in([10], activation_id=ACTIVATION) == (10,)
        assert await record.claim_reply(12) is not None

    async def test_clearing_an_empty_record_removes_nothing(
        self, record: TelegramIntakeRecord
    ) -> None:
        assert await record.clear() == 0

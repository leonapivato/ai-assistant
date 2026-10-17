"""A canonical :class:`~ai_assistant.core.protocols.TelegramIntakeRecord` fake (ADR-0323 §15).

The shared test double for the Telegram line's own record — its intake (§5:8 to §5:10)
and its own call records (§13:2) — so the line's reader and writer in
``orchestration`` can exercise a duplicate fetch, a restart over an interrupted
activation, a fixed reply that came back retryable and a store that fails, without a
file. It keeps everything in memory and follows the contract's every rule, the
retention rule included, so a consumer's test sees what the store would do.

**It checks its arguments exactly as the store does**, written out rather than
imported — ``ai_assistant.testing`` imports ``core`` and nothing else — because a fake
that accepted what the store refuses would let a consumer's test pass over a call no
deployment can make. The shared suite holds both to the same refusals.

**It can be told to fail**: :meth:`FakeTelegramIntakeRecord.fail_next` makes the next
member called raise :class:`~ai_assistant.core.errors.TelegramIntakeRecordError`
before it reads or writes anything, as a store fault would.

Every member runs to its end without awaiting, so on one event loop each is one
indivisible step, which is the exclusion the contract asks of it.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import islice
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import TelegramIntakeRecordError
from ai_assistant.core.types import (
    Identifier,
    TelegramCallKind,
    TelegramCallRecord,
    TelegramIntake,
    TelegramIntakeExport,
    TelegramIntakeKind,
    TelegramOutcome,
    TelegramPollClaim,
    describe_untrusted,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

#: How many update ids one call names at most, as ``ConversationStore``'s positions.
_MAX_NAMED: Final = 1000

#: One past the largest update id: the signed 64-bit ceiling SQLite stores.
_ID_CEILING: Final = 2**63

#: How many finished polls and typing indicators the record keeps by default, the
#: newest, restated from the store rather than imported (see the module docstring).
DEFAULT_KEPT_CALLS: Final = 1000

#: How many times a claim re-mints an attempt id that is already held before it fails.
_MINT_BUDGET: Final = 8

#: The two kinds the retention bound reaches: routine, renewed or repeated, and the
#: subject of no once-only rule.
_ROUTINE: Final = frozenset({TelegramCallKind.POLL, TelegramCallKind.TYPING})

_IDENTIFIER: Final[TypeAdapter[str]] = TypeAdapter(Identifier)


def _random_attempt() -> str:
    """A fresh attempt id: 128 random bits, as lowercase hex."""
    return uuid4().hex


def _checked_update_id(value: object, *, ceiling: int = _ID_CEILING) -> int:
    """Check one update id before any I/O.

    Args:
        value: The candidate.
        ceiling: One past the largest id accepted.

    Returns:
        The id.

    Raises:
        ValueError: If ``value`` is not an ``int`` (a ``bool`` is not one) in
            ``[0, ceiling)``.
    """
    if type(value) is not int or not 0 <= value < ceiling:
        msg = f"an update id must be an int in [0, {ceiling}), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _checked_update_ids(values: object) -> tuple[int, ...]:
    """Check a caller's sequence of update ids once, before any I/O (ADR-0065).

    Args:
        values: The candidate sequence.

    Returns:
        The ids, read once.

    Raises:
        ValueError: If ``values`` is a ``str`` or not a sequence, holds more than
            1000 ids, or holds one that is not an update id.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        msg = f"update_ids must be a sequence of int, got {describe_untrusted(values)}"
        raise ValueError(msg)
    # Read at most one past the limit, so an enormous sequence is refused without
    # being materialized: the limit is what bounds the work, not the caller's length.
    held = tuple(islice(values, _MAX_NAMED + 1))
    if len(held) > _MAX_NAMED:
        msg = f"update_ids holds more than {_MAX_NAMED}; at most {_MAX_NAMED} are named at once"
        raise ValueError(msg)
    for one in held:
        _checked_update_id(one)
    return held


def _checked_identifier(value: object, *, name: str) -> str:
    """Check an activation id or an attempt through ``core``'s own identifier type.

    Args:
        value: The candidate.
        name: The argument's name, for the message.

    Returns:
        The identifier.

    Raises:
        ValueError: If ``value`` is not a non-blank ``str``.
    """
    try:
        return _IDENTIFIER.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"{name} must be a non-blank str, got {describe_untrusted(value)}"
        raise ValueError(msg) from exc


def _checked_outcome(value: object) -> TelegramOutcome:
    """Check :meth:`finish`'s outcome before any I/O.

    Args:
        value: The candidate.

    Returns:
        The outcome.

    Raises:
        ValueError: If ``value`` is not a ``TelegramOutcome``.
    """
    if not isinstance(value, TelegramOutcome):
        msg = f"outcome must be a TelegramOutcome, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _blocks_another(record: TelegramCallRecord) -> bool:
    """Whether an earlier claim on the same subject forbids a new one (§5:9, §6:3).

    Only a call that came back with a failure Telegram did not get or said it did not
    send leaves room for another; one claimed with no outcome, done, unknown or
    refused for good does not.

    Args:
        record: An earlier fixed reply or restart message on the subject.

    Returns:
        ``True`` where it forbids a new claim.
    """
    return not (record.finished and record.failure is not None and record.failure.retryable)


@final
class FakeTelegramIntakeRecord:
    """An in-memory :class:`~ai_assistant.core.protocols.TelegramIntakeRecord`."""

    def __init__(
        self,
        *,
        kept_calls: int = DEFAULT_KEPT_CALLS,
        new_id: Callable[[], str] = _random_attempt,
    ) -> None:
        """Start an empty record.

        Args:
            kept_calls: How many finished polls and typing indicators are kept, the
                newest; in ``[1, 2**63)``, the range a SQLite integer binds.
            new_id: The attempt id factory every claim mints through.

        Raises:
            ValueError: If ``kept_calls`` is not an ``int`` in ``[1, 2**63)``.
        """
        if type(kept_calls) is not int or not 1 <= kept_calls < _ID_CEILING:
            described = describe_untrusted(kept_calls)
            msg = f"kept_calls must be an int in [1, {_ID_CEILING}), got {described}"
            raise ValueError(msg)
        self._kept_calls = kept_calls
        self._new_id = new_id
        self._intake: dict[int, TelegramIntake] = {}
        #: Every call record, in claim order: a ``dict`` keeps insertion order.
        self._calls: dict[str, TelegramCallRecord] = {}
        self._offset: int | None = None
        self._failing = False

    def fail_next(self) -> None:
        """Make the next member called raise ``TelegramIntakeRecordError``, touching nothing."""
        self._failing = True

    def _fault(self) -> None:
        """Raise the arranged store fault, once.

        Raises:
            TelegramIntakeRecordError: Where :meth:`fail_next` arranged one.
        """
        if self._failing:
            self._failing = False
            msg = "the intake record failed, as the test arranged"
            raise TelegramIntakeRecordError(msg)

    # --- the intake record ---------------------------------------------------------

    async def take_in(self, update_ids: Sequence[int], *, activation_id: str) -> tuple[int, ...]:
        """Mark each named update the record does not hold taken in by ``activation_id``.

        Raises:
            ValueError: If an argument is malformed.
            TelegramIntakeRecordError: Where a fault was arranged.
        """
        named = _checked_update_ids(update_ids)
        activation = _checked_identifier(activation_id, name="activation_id")
        self._fault()
        marked = sorted({one for one in named if one not in self._intake})
        for one in marked:
            self._intake[one] = TelegramIntake(
                update_id=one, kind=TelegramIntakeKind.TAKEN_IN, activation_id=activation
            )
        return tuple(marked)

    async def recorded(self, update_ids: Sequence[int]) -> Mapping[int, TelegramIntake]:
        """Return what the record holds of each named update.

        Raises:
            ValueError: If ``update_ids`` is malformed.
            TelegramIntakeRecordError: Where a fault was arranged.
        """
        named = _checked_update_ids(update_ids)
        self._fault()
        return {one: self._intake[one] for one in sorted(set(named)) if one in self._intake}

    async def confirm_through(self, update_id: int) -> None:
        """Owe Telegram the confirmation of every update up to ``update_id``.

        Raises:
            ValueError: If ``update_id`` is malformed.
            TelegramIntakeRecordError: Where a fault was arranged.
        """
        through = _checked_update_id(update_id, ceiling=_ID_CEILING - 1)
        self._fault()
        owed = through + 1
        if self._offset is None or owed > self._offset:
            self._offset = owed

    # --- the line's own call records -----------------------------------------------

    def _mint(self) -> str:
        """Mint an attempt id the record does not hold.

        Raises:
            TelegramIntakeRecordError: If the factory kept minting one it holds.
        """
        for _ in range(_MINT_BUDGET):
            minted = _checked_identifier(self._new_id(), name="a minted attempt")
            if minted not in self._calls:
                return minted
        msg = f"the attempt id factory minted a held id {_MINT_BUDGET} times running"
        raise TelegramIntakeRecordError(msg)

    def _claim(self, record: Callable[[str], TelegramCallRecord]) -> str:
        attempt = self._mint()
        self._calls[attempt] = record(attempt)
        return attempt

    async def claim_poll(self) -> TelegramPollClaim:
        """Claim a poll's record with the offset owed.

        Raises:
            TelegramIntakeRecordError: Where a fault was arranged, or minting failed.
        """
        self._fault()
        offset = self._offset
        attempt = self._claim(
            lambda minted: TelegramCallRecord(
                attempt=minted, kind=TelegramCallKind.POLL, offset=offset
            )
        )
        return TelegramPollClaim(attempt=attempt, offset=offset)

    async def claim_typing(self, activation_id: str) -> str:
        """Claim one typing indicator's record.

        Raises:
            ValueError: If ``activation_id`` is malformed.
            TelegramIntakeRecordError: Where a fault was arranged, or minting failed.
        """
        activation = _checked_identifier(activation_id, name="activation_id")
        self._fault()
        return self._claim(
            lambda minted: TelegramCallRecord(
                attempt=minted, kind=TelegramCallKind.TYPING, activation_id=activation
            )
        )

    async def claim_reply(self, update_id: int) -> str | None:
        """Answer a non-text message by claiming its fixed reply, where one may be sent.

        Raises:
            ValueError: If ``update_id`` is malformed.
            TelegramIntakeRecordError: Where a fault was arranged, or minting failed.
        """
        update = _checked_update_id(update_id)
        self._fault()
        held = self._intake.get(update)
        if held is not None and held.kind is TelegramIntakeKind.TAKEN_IN:
            return None
        if any(
            _blocks_another(one)
            for one in self._calls.values()
            if one.kind is TelegramCallKind.FIXED_REPLY and one.update_id == update
        ):
            return None
        attempt = self._claim(
            lambda minted: TelegramCallRecord(
                attempt=minted, kind=TelegramCallKind.FIXED_REPLY, update_id=update
            )
        )
        self._intake[update] = TelegramIntake(update_id=update, kind=TelegramIntakeKind.ANSWERED)
        return attempt

    async def claim_interrupted(self, activation_id: str) -> str | None:
        """Claim the restart's fixed message for ``activation_id``, where one may be sent.

        Raises:
            ValueError: If ``activation_id`` is malformed.
            TelegramIntakeRecordError: Where a fault was arranged, or minting failed.
        """
        activation = _checked_identifier(activation_id, name="activation_id")
        self._fault()
        if any(
            _blocks_another(one)
            for one in self._calls.values()
            if one.kind is TelegramCallKind.INTERRUPTED and one.activation_id == activation
        ):
            return None
        return self._claim(
            lambda minted: TelegramCallRecord(
                attempt=minted, kind=TelegramCallKind.INTERRUPTED, activation_id=activation
            )
        )

    async def finish(self, attempt: str, outcome: TelegramOutcome) -> None:
        """Write a claimed call's outcome, once, and apply what it lets go.

        Raises:
            ValueError: If an argument is malformed.
            TelegramIntakeRecordError: If no call is held under ``attempt``, it is
                already finished, or a fault was arranged.
        """
        named = _checked_identifier(attempt, name="attempt")
        result = _checked_outcome(outcome)
        self._fault()
        held = self._calls.get(named)
        if held is None:
            msg = "the intake record holds no call under that attempt"
            raise TelegramIntakeRecordError(msg)
        if held.finished:
            msg = "that call is already finished"
            raise TelegramIntakeRecordError(msg)
        self._calls[named] = held.model_copy(update={"finished": True, "failure": result.failure})
        if held.kind is TelegramCallKind.POLL and result.done and held.offset is not None:
            self._confirmed(held.offset)
        if held.kind in _ROUTINE:
            self._keep_newest_routine()

    def _confirmed(self, offset: int) -> None:
        """Let go of what a done poll carrying ``offset`` confirmed to Telegram."""
        if self._offset is not None and self._offset <= offset:
            self._offset = None
        for one in [held for held in self._intake if held < offset]:
            del self._intake[one]
        for attempt in [
            key
            for key, one in self._calls.items()
            if one.kind is TelegramCallKind.FIXED_REPLY
            and one.finished
            and one.update_id is not None
            and one.update_id < offset
        ]:
            del self._calls[attempt]

    def _keep_newest_routine(self) -> None:
        """Drop the finished polls and typing indicators beyond the newest kept."""
        finished = [
            key for key, one in self._calls.items() if one.kind in _ROUTINE and one.finished
        ]
        for attempt in finished[: max(0, len(finished) - self._kept_calls)]:
            del self._calls[attempt]

    async def call(self, attempt: str) -> TelegramCallRecord | None:
        """Return the call record held under ``attempt``, or ``None``.

        Raises:
            ValueError: If ``attempt`` is malformed.
            TelegramIntakeRecordError: Where a fault was arranged.
        """
        named = _checked_identifier(attempt, name="attempt")
        self._fault()
        return self._calls.get(named)

    # --- the user's data rights ----------------------------------------------------

    async def export(self) -> TelegramIntakeExport:
        """Return everything the record holds.

        Raises:
            TelegramIntakeRecordError: Where a fault was arranged.
        """
        self._fault()
        return TelegramIntakeExport(
            offset=self._offset,
            intake=tuple(self._intake[one] for one in sorted(self._intake)),
            calls=tuple(self._calls.values()),
        )

    async def clear(self) -> int:
        """Erase everything, returning how many records went.

        Raises:
            TelegramIntakeRecordError: Where a fault was arranged.
        """
        self._fault()
        removed = len(self._intake) + len(self._calls)
        self._intake.clear()
        self._calls.clear()
        self._offset = None
        return removed

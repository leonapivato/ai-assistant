"""A canonical :class:`~ai_assistant.core.protocols.BatchCompleter` fake.

The shared test double for the ``BatchCompleter`` contract (ADR-0143), so anything
that drives bulk inference can be tested against a real, contract-correct
implementation *without importing the models subsystem's internals* (CLAUDE.md
golden rule 1), without a vendor SDK, and without touching the network. It lives
in ``ai_assistant.testing`` so it is importable from any test while staying out of
production code paths (``lint-imports`` forbids production modules importing it).

**It models a provider, not just a subject.** A batch seam cannot be faked by a
stateless stub: the contract is about what happens *between* three calls, so the
fake keeps its remote state in a :class:`BatchProvider` it talks to. Two
``FakeBatchCompleter``s built over one provider are two implementations reaching
one account — which is exactly the shape ADR-0143 §2's "a handle presented to a
**freshly constructed** ``BatchCompleter`` of equal ``issuer``" clause is about,
and there is no other way to exercise it.

Only the behaviour asserted by the shared ``BatchCompleter`` conformance suite is
part of the contract. :meth:`FakeBatchCompleter.program`,
:meth:`FakeBatchCompleter.settle` and the rest of the provider's control surface
are conveniences on top: they stand in for things a real provider does on its own
schedule, and no production caller may depend on them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import ModelError
from ai_assistant.core.types import (
    BatchFailureKind,
    BatchHandle,
    BatchItemFailure,
    BatchItemOutcome,
    BatchOutcomeKind,
    BatchRequest,
    BatchState,
    BatchStatus,
    Message,
    NonBlankEncodableText,
    Role,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

#: A fixed, timezone-aware instant, so a fake's stamps are deterministic.
_EPOCH_STAMP: Final = datetime(2026, 1, 1, tzinfo=UTC)

#: The account label a fake carries unless a test configures another. A label,
#: never a credential — ADR-0143 §2 requires ``issuer`` to be non-secret.
DEFAULT_BATCH_ISSUER: Final = "fake-batch-account"

#: What a programmed ``SUCCEEDED`` item answers with, unless a test says otherwise.
DEFAULT_BATCH_REPLY: Final = "fake batch reply"

_DEFAULT_FAILURE_DETAIL: Final = "fake batch failure"

#: The handle's own rule for its identity fields, reached as the type rather than
#: re-implemented — see ``models/batch.py`` for why the check has to happen before
#: the exchange rather than at handle construction.
_HANDLE_TEXT: Final[TypeAdapter[str]] = TypeAdapter(NonBlankEncodableText)


@dataclass(frozen=True, slots=True)
class ProgrammedOutcome:
    """How the provider will answer one item once its batch settles.

    Attributes:
        kind: Which of ADR-0143 §4's four ways the item ends.
        content: The assistant's reply, read only when ``kind`` is ``SUCCEEDED``.
        failure_kind: The classification, read only when ``kind`` is ``FAILED``.
        detail: The failure's operator-facing text, read only on ``FAILED``.
    """

    kind: BatchOutcomeKind = BatchOutcomeKind.SUCCEEDED
    content: str = DEFAULT_BATCH_REPLY
    failure_kind: BatchFailureKind = BatchFailureKind.UNKNOWN
    detail: str = _DEFAULT_FAILURE_DETAIL

    def as_outcome(self, item_id: str) -> BatchItemOutcome:
        """Render this programmed answer as the outcome ``item_id`` ends with.

        Args:
            item_id: The caller's id, carried through byte-for-byte.

        Returns:
            The outcome, with the payload ADR-0143 §9 binds to the kind.
        """
        message = (
            Message(role=Role.ASSISTANT, content=self.content)
            if self.kind is BatchOutcomeKind.SUCCEEDED
            else None
        )
        failure = (
            BatchItemFailure(kind=self.failure_kind, detail=self.detail)
            if self.kind is BatchOutcomeKind.FAILED
            else None
        )
        return BatchItemOutcome(item_id=item_id, kind=self.kind, message=message, failure=failure)


class ExchangeGate:
    """Holds the provider's next exchange open, so a test can act mid-flight.

    ADR-0143 §3's observation clause is only testable against a call that is
    genuinely suspended, so this is the seam's equivalent of the model layer's
    first-await gate: a scenario arms it, waits for the call to reach the
    exchange, mutates what it passed, and then lets the call proceed.
    """

    def __init__(self) -> None:
        """Create a gate that has not yet been reached and is still holding."""
        self._reached = asyncio.Event()
        self._released = asyncio.Event()

    async def hold(self) -> None:
        """Announce that the exchange was reached, then wait to be released."""
        self._reached.set()
        await self._released.wait()

    async def reached(self) -> None:
        """Wait until a call has arrived at the held exchange."""
        await self._reached.wait()

    def release(self) -> None:
        """Let the held call proceed."""
        self._released.set()


@dataclass
class _Batch:
    """One batch as the fake provider holds it."""

    batch_id: str
    items: tuple[BatchRequest, ...]
    model: str | None
    created_at: datetime
    settled: int = 0
    results_expire_at: datetime | None = None
    retention_lapsed: bool = False


@dataclass
class BatchProvider:
    """The in-memory provider a :class:`FakeBatchCompleter` talks to. Test-only.

    Holds the state that outlives a call — the batches, what each item will answer
    with, and how many exchanges have happened. Share one between two completers
    to model two processes reaching one account.

    Attributes:
        batches: Accepted batches, by provider id.
        programmed: What each ``item_id`` will answer with once its batch settles.
        calls: How many exchanges with this provider have happened. A refusal that
            never reaches the provider must leave this untouched (ADR-0143 §2).
        gate: When set, the next exchange holds here until released.
        now: The instant the provider stamps a batch's ``created_at`` with. Fixed
            by default, because a test double reading a real clock is a test that
            fails on a different day.
    """

    now: datetime = _EPOCH_STAMP
    batches: dict[str, _Batch] = field(default_factory=dict)
    programmed: dict[str, ProgrammedOutcome] = field(default_factory=dict)
    calls: int = 0
    gate: ExchangeGate | None = None
    _minted: int = 0

    async def exchange(self) -> None:
        """Record one exchange and suspend, holding at :attr:`gate` if one is armed.

        Always suspends, gate or no gate. A fake that never yielded would let an
        implementation read its arguments after what *looks* like a network call
        and still pass ADR-0065's clause, which is the one thing this fake must not
        make easy.
        """
        self.calls += 1
        if self.gate is not None:
            await self.gate.hold()
        else:
            await asyncio.sleep(0)

    def mint_id(self) -> str:
        """A fresh provider-side batch id, distinct from every earlier one."""
        self._minted += 1
        return f"fake-batch-{self._minted:04d}"

    def program(self, item_id: str, outcome: ProgrammedOutcome) -> None:
        """Fix how ``item_id`` will end once its batch settles."""
        self.programmed[item_id] = outcome

    def outcome_for(self, item_id: str) -> ProgrammedOutcome:
        """What ``item_id`` ends with — a plain success unless a test said otherwise."""
        return self.programmed.get(item_id, ProgrammedOutcome())

    def settle(self, batch_id: str) -> None:
        """Settle every item of ``batch_id``, as a real provider eventually would."""
        batch = self.batches[batch_id]
        batch.settled = len(batch.items)

    def lapse_retention(self, batch_id: str) -> None:
        """Put ``batch_id`` past its results retention, so a fetch must refuse."""
        self.batches[batch_id].retention_lapsed = True

    def set_results_expiry(self, batch_id: str, when: datetime | None) -> None:
        """Fix what ``poll`` reports as this batch's results retention."""
        self.batches[batch_id].results_expire_at = when


class FakeBatchCompleter:
    """A deterministic, offline ``BatchCompleter`` test double.

    Structurally implements
    :class:`~ai_assistant.core.protocols.BatchCompleter`. It performs every refusal
    ADR-0143 §2, §3 and §7 place on the near side of the acceptance window before
    it touches its :class:`BatchProvider`, snapshots its items deeply on
    ``submit``'s first executed line, and refuses a handle whose ``issuer`` is not
    its own.

    **Outcomes come back in a deliberately jumbled order.** ADR-0143 §4 leaves the
    order unspecified and §13 asks the canonical fake to prove it: a consumer that
    quietly assumed submission order would pass against a tidy fake and then read
    the wrong answers against a real provider, whose results genuinely arrive
    unordered. The permutation is fixed rather than random, because a test double
    that shuffles differently each run trades one silent bug for a flaky suite.
    """

    def __init__(
        self,
        *,
        issuer: str = DEFAULT_BATCH_ISSUER,
        provider: BatchProvider | None = None,
        max_items: int | None = None,
    ) -> None:
        """Create a completer over ``provider``, answering for ``issuer``.

        Args:
            issuer: The account label stamped on every handle this mints and
                compared against every handle it is handed. Supplied by whoever
                constructs it, exactly as ADR-0143 §2 requires of the real thing.
            provider: The provider state to talk to. Pass one another completer
                already holds to model two processes reaching a single account;
                a fresh one is created when omitted.
            max_items: An optional size bound to refuse above, so ADR-0143 §7's
                clause can be exercised without building a vendor-sized batch.
                ``None`` — the default — declares no bound, which §7 permits.
        """
        self._issuer = issuer
        self._max_items = max_items
        self.provider = provider if provider is not None else BatchProvider()

    @property
    def issuer(self) -> str:
        """The account label this completer stamps on and compares handles against."""
        return self._issuer

    async def submit(
        self,
        batch_key: NonBlankEncodableText,
        items: Sequence[BatchRequest],
        *,
        model: str | None = None,
    ) -> BatchHandle:
        """Validate the whole batch, hand it to the provider, and return its handle.

        The snapshot on the first line is ADR-0065's third discharge, taken deep
        enough to cover everything the call goes on to read: the outer sequence,
        each :class:`~ai_assistant.core.types.BatchRequest` in it, and each
        request's own ``messages``. Everything below reads the snapshot and never
        ``items`` again.

        Args:
            batch_key: The caller's key, carried unchanged onto the handle.
            items: The batch's items.
            model: Optional ``"provider:model"`` override, recorded and otherwise
                ignored — the fake has no real route to switch.

        Returns:
            The handle naming the accepted batch.

        Raises:
            ModelError: For every refusal ADR-0143 §2's window clause puts ahead of
                the provider call. Neither retryable nor routable (ADR-0066 §3).
        """
        snapshot = tuple(item.model_copy(deep=True) for item in items)
        _refuse_unusable_handle_text(batch_key, what=f"batch_key {batch_key!r}")
        _refuse_unusable_handle_text(self._issuer, what=f"issuer {self._issuer!r}")
        self._refuse_unacceptable(snapshot)

        await self.provider.exchange()

        batch_id = self.provider.mint_id()
        self.provider.batches[batch_id] = _Batch(
            batch_id=batch_id,
            items=snapshot,
            model=model,
            created_at=self.provider.now,
        )
        return BatchHandle(
            batch_key=batch_key,
            batch_id=batch_id,
            issuer=self._issuer,
            submitted_at=self.provider.now,
        )

    async def poll(self, handle: BatchHandle) -> BatchStatus:
        """Report where ``handle``'s batch has got to, without waiting for it."""
        batch = self._resolve(handle)
        await self.provider.exchange()
        total = len(batch.items)
        return BatchStatus(
            handle=handle,
            state=BatchState.COMPLETE if batch.settled == total else BatchState.PENDING,
            total=total,
            settled=batch.settled,
            results_expire_at=batch.results_expire_at,
        )

    async def fetch(self, handle: BatchHandle) -> Sequence[BatchItemOutcome]:
        """Return one outcome per submitted item, in an order nothing may rely on.

        Raises:
            ModelError: If the handle is not this issuer's, if the batch has not
                settled, or if its results retention has lapsed. The last is
                refused rather than short-returned: a fetch that quietly returned
                fewer outcomes than the batch has items would be read as a run of
                expired items and scored as though it had happened (ADR-0143 §6).
        """
        batch = self._resolve(handle)
        if batch.settled != len(batch.items):
            msg = (
                f"batch {handle.batch_id!r} has settled {batch.settled} of "
                f"{len(batch.items)} items; fetch is defined only for a COMPLETE batch"
            )
            raise ModelError(msg)
        if batch.retention_lapsed:
            msg = f"batch {handle.batch_id!r} is past its results retention and cannot be fetched"
            raise ModelError(msg)

        await self.provider.exchange()
        outcomes = [
            self.provider.outcome_for(item.item_id).as_outcome(item.item_id) for item in batch.items
        ]
        return _jumbled(outcomes)

    def program(self, item_id: str, outcome: ProgrammedOutcome) -> None:
        """Fix how ``item_id`` will end. A convenience onto the provider."""
        self.provider.program(item_id, outcome)

    def settle(self, handle: BatchHandle) -> None:
        """Settle every item of ``handle``'s batch. A convenience onto the provider."""
        self.provider.settle(handle.batch_id)

    def lapse_retention(self, handle: BatchHandle) -> None:
        """Put ``handle``'s batch past its results retention."""
        self.provider.lapse_retention(handle.batch_id)

    def set_results_expiry(self, handle: BatchHandle, when: datetime | None) -> None:
        """Fix what ``poll`` reports as this batch's results retention."""
        self.provider.set_results_expiry(handle.batch_id, when)

    def submitted_items(self, handle: BatchHandle) -> tuple[BatchRequest, ...]:
        """What the provider actually received for ``handle``'s batch."""
        return self.provider.batches[handle.batch_id].items

    def _resolve(self, handle: BatchHandle) -> _Batch:
        """Check the handle against this issuer, then find the batch it names.

        Raises:
            ModelError: If the issuer does not match, or the batch is unknown to
                this provider.
        """
        if handle.issuer != self._issuer:
            msg = (
                f"handle names issuer {handle.issuer!r}; this completer answers only "
                f"for {self._issuer!r}"
            )
            raise ModelError(msg)
        batch = self.provider.batches.get(handle.batch_id)
        if batch is None:
            msg = f"no batch {handle.batch_id!r} under issuer {self._issuer!r}"
            raise ModelError(msg)
        return batch

    def _refuse_unacceptable(self, items: tuple[BatchRequest, ...]) -> None:
        """Apply every refusal that must land before the provider is contacted.

        Raises:
            ModelError: Neither retryable nor routable — a malformed argument
                reproduces identically on every attempt from every route
                (ADR-0066 §3).
        """
        if not items:
            msg = "submit() requires at least one item; a batch of nothing has no outcome"
            raise ModelError(msg)
        if self._max_items is not None and len(items) > self._max_items:
            msg = (
                f"batch of {len(items)} items exceeds this completer's declared bound "
                f"of {self._max_items}; split it"
            )
            raise ModelError(msg)
        seen: set[str] = set()
        for item in items:
            if item.item_id in seen:
                msg = f"item_id {item.item_id!r} appears twice; ids must be unique within a batch"
                raise ModelError(msg)
            seen.add(item.item_id)
            _refuse_unusable_handle_text(item.item_id, what=f"item_id {item.item_id!r}")
            _refuse_malformed_history(item)


def _refuse_unusable_handle_text(value: str, *, what: str) -> None:
    """Refuse a value the handle would reject, before anything is submitted.

    Mirrors ``AnthropicBatchCompleter``'s own check, and for the reason the fake
    mirrors every other refusal: a value that this fake accepts and the real
    implementation rejects lets a consumer built against the fake behave in a way
    production does not (ADR-0143 §2's acceptance window).

    Raises:
        ModelError: If ``value`` is blank or has no UTF-8 encoding.
    """
    try:
        _HANDLE_TEXT.validate_python(value)
    except ValidationError as exc:
        msg = f"{what} cannot be carried on a BatchHandle: {exc.errors()[0]['msg']}"
        raise ModelError(msg) from exc


def _refuse_malformed_history(item: BatchRequest) -> None:
    """Hold one item's messages to ``ModelProvider.complete``'s precondition.

    Read as that docstring states it — a necessary condition admitting nothing by
    omission — which is why the tool-role turn is refused although the clause names
    only the other two shapes (ADR-0143 §3, §10).

    Raises:
        ModelError: If the history is empty, ends on an assistant turn, or holds a
            tool-role turn.
    """
    if not item.messages:
        msg = f"item {item.item_id!r} has an empty conversation; there is nothing to answer"
        raise ModelError(msg)
    if item.messages[-1].role is Role.ASSISTANT:
        msg = (
            f"item {item.item_id!r} requires a conversation awaiting a reply; this "
            f"history already ends with an assistant turn"
        )
        raise ModelError(msg)
    if any(message.role is Role.TOOL for message in item.messages):
        msg = f"item {item.item_id!r} carries a tool-role message, which this seam cannot represent"
        raise ModelError(msg)


def _jumbled(outcomes: list[BatchItemOutcome]) -> tuple[BatchItemOutcome, ...]:
    """Return ``outcomes`` in a fixed order that is neither submission nor reverse.

    Odd positions first, then even. For anything longer than two items that is
    demonstrably a third order, which is the point: a consumer keying by position
    fails here rather than against a real provider.
    """
    return (*outcomes[1::2], *outcomes[::2])

"""The real ``anthropic`` SDK over a scripted Message Batches endpoint.

    ``AnthropicBatchCompleter`` → the real ``anthropic`` SDK client → ``httpx``

and only the transport is replaced, by :class:`httpx.MockTransport` — the
technique ADR-0061 §3 established for the per-request seam and ADR-0143 §13's
closing clause requires of this one: "The vendor binding of the
``BatchCompleterContract`` suite runs offline against the real vendor SDK with
only the transport replaced, inside ``network_denied()`` and with a literal dummy
credential."

**Why a stateful server rather than canned responses.** The per-request seam can
be exercised with one handler answering one request, because ``complete`` is one
exchange. A batch is not: the contract is about what the provider says on the
*third* call given what it was told on the first, so the thing behind the
transport has to remember. :class:`BatchServer` is that memory, and it is
deliberately the smallest server that can be wrong in the ways ADR-0143 §13 asks
about — it settles on command, archives on command, and returns its results file
in an order that is not submission order.

**No credentials, no network.** The client is constructed with a literal dummy
key, so nothing is read from the environment, from a profile, or from disk; every
test runs under :func:`network_guard.network_denied`. ``max_retries=0`` because
the SDK retries 429s and 5xx internally, so one canned failure would arrive as
three requests and what got classified would be the SDK's last attempt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import httpx
from anthropic import AsyncAnthropic
from batch_completer_contract import TransmittedItem, a_batch

from ai_assistant.core.types import BatchFailureKind, BatchOutcomeKind
from ai_assistant.models.batch import AnthropicBatchCompleter
from ai_assistant.testing import ExchangeGate, ProgrammedOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import BatchCompleter
    from ai_assistant.core.types import BatchHandle, BatchRequest

#: A dummy key, so no vendor client ever reads one from the environment, a
#: profile, or an on-disk credential store — every discovery path in
#: ``AsyncAnthropic.__init__`` is short-circuited by an explicit ``api_key``.
DUMMY_KEY: Final = "test-key-not-a-credential"

#: The account label the vendor binding is configured with. A label, never a
#: credential: ADR-0143 §2 requires ``issuer`` to be non-secret because handles
#: are written to disk.
VENDOR_ISSUER: Final = "acct-vendor-binding"

VENDOR_MODEL: Final = "anthropic:claude-sonnet-4-5"

#: Small enough that the over-large case is one line rather than a 100,001-item
#: batch, which is the whole reason ``max_items`` is a constructor argument.
MAX_ITEMS: Final = 8

_BATCHES_PATH: Final = "/v1/messages/batches"

#: Which vendor error type stands in for each of ADR-0143 §5's seven kinds. Two
#: of them have no error type at all, and that is the point rather than a gap:
#: ``CONTENT_FILTER`` and ``UNUSABLE_RESPONSE`` reach the seam through results the
#: vendor calls *successes*, so they are scripted on that arm instead (see
#: :func:`_result_for`) and the implementation has to classify them itself.
_ERROR_TYPE_BY_KIND: Final[dict[BatchFailureKind, str]] = {
    BatchFailureKind.AUTHENTICATION: "authentication_error",
    BatchFailureKind.RATE_LIMITED: "rate_limit_error",
    BatchFailureKind.UNAVAILABLE: "overloaded_error",
    BatchFailureKind.INVALID_REQUEST: "invalid_request_error",
    BatchFailureKind.UNKNOWN: "an_error_type_this_sdk_has_never_heard_of",
}


def _stamp(moment: datetime) -> str:
    """An RFC 3339 rendering, which is what the vendor's wire format carries."""
    return moment.isoformat().replace("+00:00", "Z")


def _a_message(text: str, *, stop_reason: str = "end_turn") -> dict[str, Any]:
    """A wire-accurate Messages response carrying ``text``."""
    content = [{"type": "text", "text": text}] if text else []
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _result_for(outcome: ProgrammedOutcome) -> dict[str, Any]:
    """One result object, as the vendor's results file would carry it."""
    match outcome.kind:
        case BatchOutcomeKind.SUCCEEDED:
            return {"type": "succeeded", "message": _a_message(outcome.content)}
        case BatchOutcomeKind.EXPIRED:
            return {"type": "expired"}
        case BatchOutcomeKind.CANCELLED:
            return {"type": "canceled"}
        case BatchOutcomeKind.FAILED:
            return _failed_result(outcome)


def _failed_result(outcome: ProgrammedOutcome) -> dict[str, Any]:
    """The vendor shape a failure of this kind actually arrives in.

    Two of ADR-0143 §5's kinds do not arrive as vendor errors at all: a safety
    refusal is a *succeeded* message whose ``stop_reason`` is ``"refusal"``, and an
    unusable response is a *succeeded* message carrying no text block. Scripting
    them here rather than as errors is what makes the vendor binding test the
    classification the implementation actually has to do.
    """
    if outcome.failure_kind is BatchFailureKind.CONTENT_FILTER:
        return {"type": "succeeded", "message": _a_message("", stop_reason="refusal")}
    if outcome.failure_kind is BatchFailureKind.UNUSABLE_RESPONSE:
        return {"type": "succeeded", "message": _a_message("")}
    return {
        "type": "errored",
        "error": {
            "type": "error",
            "error": {
                "type": _ERROR_TYPE_BY_KIND[outcome.failure_kind],
                "message": outcome.detail,
            },
        },
    }


@dataclass
class _ServerBatch:
    """One batch as the scripted endpoint holds it."""

    batch_id: str
    custom_ids: tuple[str, ...]
    body: dict[str, Any]
    created_at: datetime
    settled: bool = False
    archived_at: datetime | None = None
    #: When set, the results file carries only these ids while the batch's own
    #: tallies still count every submitted item — the short read ADR-0143 §6
    #: forbids being answered with silently, which nothing else can script.
    short_results: tuple[str, ...] | None = None


@dataclass
class BatchServer:
    """A scripted Message Batches endpoint, answering the real SDK over ``httpx``.

    Attributes:
        batches: Accepted batches, by provider id.
        programmed: What each ``custom_id`` will answer with once its batch settles.
        calls: How many requests have reached this endpoint.
        gate: When armed, the next request holds here until released.
        now: The instant a created batch is stamped with.
    """

    now: datetime = datetime(2026, 3, 1, tzinfo=UTC)
    batches: dict[str, _ServerBatch] = field(default_factory=dict)
    programmed: dict[str, ProgrammedOutcome] = field(default_factory=dict)
    calls: int = 0
    gate: ExchangeGate | None = None
    _minted: int = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        """Answer one request, holding at :attr:`gate` first if one is armed."""
        self.calls += 1
        gate, self.gate = self.gate, None
        if gate is not None:
            await gate.hold()

        path = request.url.path
        if request.method == "POST" and path == _BATCHES_PATH:
            return self._create(request)
        if request.method == "GET" and path.endswith("/results"):
            return self._results(path.removesuffix("/results").rsplit("/", 1)[-1])
        if request.method == "GET" and path.startswith(f"{_BATCHES_PATH}/"):
            return self._retrieve(path.rsplit("/", 1)[-1])
        return httpx.Response(404, json={"type": "error", "error": {"type": "not_found_error"}})

    def _create(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        self._minted += 1
        batch_id = f"msgbatch_{self._minted:04d}"
        self.batches[batch_id] = _ServerBatch(
            batch_id=batch_id,
            custom_ids=tuple(item["custom_id"] for item in body["requests"]),
            body=body,
            created_at=self.now,
        )
        return httpx.Response(200, json=self._rendered(batch_id))

    def _retrieve(self, batch_id: str) -> httpx.Response:
        if batch_id not in self.batches:
            return httpx.Response(404, json={"type": "error", "error": {"type": "not_found_error"}})
        return httpx.Response(200, json=self._rendered(batch_id))

    def _results(self, batch_id: str) -> httpx.Response:
        batch = self.batches[batch_id]
        lines = [
            json.dumps(
                {
                    "custom_id": custom_id,
                    "result": _result_for(self.programmed.get(custom_id, ProgrammedOutcome())),
                }
            )
            for custom_id in _jumbled(batch.short_results or batch.custom_ids)
        ]
        # Every line is newline-terminated, including the last: the SDK's JSONL
        # decoder only emits a line once it has seen the terminator, so a trailing
        # partial line is silently dropped rather than reported.
        payload = "".join(f"{line}\n" for line in lines).encode("utf-8")
        return httpx.Response(200, content=payload, headers={"content-type": "application/x-jsonl"})

    def _rendered(self, batch_id: str) -> dict[str, Any]:
        """The batch as the vendor's ``MessageBatch`` schema carries it."""
        batch = self.batches[batch_id]
        kinds = [self.programmed.get(cid, ProgrammedOutcome()).kind for cid in batch.custom_ids]
        settled_counts = {
            "succeeded": sum(k is BatchOutcomeKind.SUCCEEDED for k in kinds),
            "errored": sum(k is BatchOutcomeKind.FAILED for k in kinds),
            "canceled": sum(k is BatchOutcomeKind.CANCELLED for k in kinds),
            "expired": sum(k is BatchOutcomeKind.EXPIRED for k in kinds),
        }
        counts = (
            {"processing": 0, **settled_counts}
            if batch.settled
            else {
                "processing": len(batch.custom_ids),
                "succeeded": 0,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            }
        )
        return {
            "id": batch_id,
            "type": "message_batch",
            "created_at": _stamp(batch.created_at),
            "expires_at": _stamp(batch.created_at + timedelta(hours=24)),
            "ended_at": _stamp(batch.created_at) if batch.settled else None,
            "cancel_initiated_at": None,
            "archived_at": _stamp(batch.archived_at) if batch.archived_at else None,
            "processing_status": "ended" if batch.settled else "in_progress",
            "request_counts": counts,
            "results_url": f"{_BATCHES_PATH}/{batch_id}/results" if batch.settled else None,
        }


def _jumbled(ids: tuple[str, ...]) -> tuple[str, ...]:
    """Odd positions first, then even — never submission order for three or more.

    The vendor's own ``results_url`` docstring says results "are not guaranteed to
    be in the same order as requests"; a scripted endpoint that returned them in
    order would let a positional assumption pass here and fail in production.
    """
    return (*ids[1::2], *ids[::2])


@dataclass
class VendorBatchWorld:
    """The suite's world over ``AnthropicBatchCompleter`` and a scripted endpoint."""

    server: BatchServer
    client: AsyncAnthropic
    http_client: httpx.AsyncClient
    subject: AnthropicBatchCompleter
    credential_value: str = DUMMY_KEY

    @property
    def completer(self) -> BatchCompleter:
        return self.subject

    @property
    def issuer(self) -> str:
        return VENDOR_ISSUER

    @property
    def credential(self) -> str:
        return self.credential_value

    @property
    def provider_calls(self) -> int:
        return self.server.calls

    @property
    def over_large(self) -> Sequence[BatchRequest] | None:
        return a_batch(*(f"item-{n}" for n in range(MAX_ITEMS + 1)))

    def rebuilt(self) -> BatchCompleter:
        return _completer(self.client)

    def with_credential_rotated(self) -> BatchCompleter:
        self.credential_value = f"{DUMMY_KEY}-rotated"
        rotated = AsyncAnthropic(
            api_key=self.credential_value, http_client=self.http_client, max_retries=0
        )
        return _completer(rotated)

    def with_issuer(self, issuer: str) -> BatchCompleter:
        return _completer(self.client, issuer=issuer)

    def program(self, item_id: str, outcome: ProgrammedOutcome) -> None:
        self.server.programmed[item_id] = outcome

    def settle(self, handle: BatchHandle) -> None:
        self.server.batches[handle.batch_id].settled = True

    def lapse_retention(self, handle: BatchHandle) -> None:
        self.server.batches[handle.batch_id].archived_at = self.server.now + timedelta(days=29)

    def set_results_expiry(self, handle: BatchHandle, when: datetime | None) -> None:
        self.server.batches[handle.batch_id].archived_at = when

    def transmitted(self, handle: BatchHandle) -> tuple[TransmittedItem, ...]:
        body = self.server.batches[handle.batch_id].body
        return tuple(
            TransmittedItem(
                item_id=item["custom_id"],
                turns=tuple((turn["role"], turn["content"]) for turn in item["params"]["messages"]),
            )
            for item in body["requests"]
        )

    def hold_next_exchange(self) -> ExchangeGate:
        gate = ExchangeGate()
        self.server.gate = gate
        return gate


def _completer(client: AsyncAnthropic, *, issuer: str = VENDOR_ISSUER) -> AnthropicBatchCompleter:
    """Build a completer over ``client``, answering for ``issuer``."""
    return AnthropicBatchCompleter(
        client=client, issuer=issuer, default_model=VENDOR_MODEL, max_items=MAX_ITEMS
    )

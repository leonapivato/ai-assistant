"""Bulk completion over Anthropic's Message Batches API (ADR-0143).

The primary production implementation of
:class:`~ai_assistant.core.protocols.BatchCompleter`, and the first module in this
package to import a vendor SDK **directly**. That is permitted by construction
rather than by exception: golden rule 4 confines provider SDKs to `models/`, and
`ai_assistant.models` is already absent from the ``provider SDKs are confined to
the models layer`` contract's ``source_modules``, so nothing in
``[tool.importlinter]`` changes for this file to exist (ADR-0143 §8).

**Why not through pydantic-ai, like every other module here.** There is no route:
the installed ``pydantic-ai-slim`` has no message-batch surface at all, and its
only "batch" vocabulary is about tool batching and embedding batches. The library
this package is built on cannot reach the endpoint, so the endpoint is reached
directly. ADR-0143's Consequences records the cost — a vendor-SDK upgrade can now
break a second surface — and accepts it.

**Nothing here is wired into the hub, and that is structural.** ADR-0143 §8's
third clause keeps a batch in the process that submits it; §11 leaves wiring a
``BatchCompleter`` into ``ai_assistant.app`` or any subsystem deferred until a
subsystem — not a harness — asks for bulk inference. A consumer constructs this
class in a composition root it owns.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from anthropic import APIConnectionError, APIStatusError, APITimeoutError
from anthropic.types import TextBlock

from ai_assistant.core.errors import (
    ModelError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
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

# The disposition table is *one* table, deliberately shared rather than copied.
# ADR-0143 §5's whole argument for mirroring ``ModelError``'s vocabulary is that a
# caller's retry logic is the same whether an answer came through ``complete`` or
# through a batch — which is only true if the two seams classify a status the same
# way. A private name reached across two modules of one package is the cheap way
# to make that a fact instead of a convention.
from ai_assistant.models.provider import _classify_status

if TYPE_CHECKING:
    from collections.abc import Sequence

    from anthropic import AsyncAnthropic
    from anthropic.types import MessageParam
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages import (
        MessageBatch,
        MessageBatchIndividualResponse,
        batch_create_params,
    )

#: The provider half of a ``"provider:model"`` spec this implementation answers
#: for. A spec naming any other provider is a caller error: a handle issued by one
#: provider is meaningless to another (ADR-0143 §2), so silently accepting the
#: string and sending it somewhere else is the one thing that must not happen.
_PROVIDER_NAME: Final = "anthropic"

#: The vendor's documented ceiling on requests in one Message Batch. ADR-0143 §7
#: fixes no bound in the *contract* — a number there would be one vendor's limit
#: written into a model-agnostic seam — and permits an implementation to declare
#: one, which this does. The byte ceiling that accompanies it is **not** enforced
#: here: it is a property of the serialised payload rather than of the item count,
#: and an implementation that guessed at it would refuse batches the provider
#: would have accepted. A batch over that ceiling is refused by the provider and
#: surfaces from :meth:`AnthropicBatchCompleter.submit` as a ``ModelError``.
DEFAULT_MAX_BATCH_ITEMS: Final = 100_000

#: What each item is allowed to generate, unless a caller configures otherwise.
#: The Messages API requires the field and the batch seam has no parameter for it
#: (ADR-0143 §9 caps the contract's surface), so it is configuration of *this*
#: implementation rather than of the seam.
DEFAULT_MAX_TOKENS: Final = 4096

#: How the vendor's per-item error types map onto ADR-0143 §5's seven kinds.
#: Exhaustive over what the SDK's ``ErrorObject`` union can discriminate to; a
#: type outside it is deliberately ``UNKNOWN`` rather than guessed at, because
#: misclassifying something as retryable is worse than not classifying it.
_FAILURE_KIND_BY_ERROR_TYPE: Final[dict[str, BatchFailureKind]] = {
    "authentication_error": BatchFailureKind.AUTHENTICATION,
    "permission_error": BatchFailureKind.AUTHENTICATION,
    "billing_error": BatchFailureKind.AUTHENTICATION,
    "rate_limit_error": BatchFailureKind.RATE_LIMITED,
    "overloaded_error": BatchFailureKind.UNAVAILABLE,
    "api_error": BatchFailureKind.UNAVAILABLE,
    "timeout_error": BatchFailureKind.UNAVAILABLE,
    "invalid_request_error": BatchFailureKind.INVALID_REQUEST,
    "not_found_error": BatchFailureKind.INVALID_REQUEST,
}


def _classify(exc: Exception) -> ModelError:
    """Translate a vendor SDK failure into our own error taxonomy.

    Every failure is still a :class:`ModelError`, so the contract that these three
    members raise only ``ModelError`` is unchanged; this narrows the subclass.
    Unrecognised failures stay a bare, non-retryable ``ModelError`` — the same
    conservative default ``provider.py`` takes, and for the same reason.

    Args:
        exc: The exception the SDK raised during an exchange.

    Returns:
        The most specific :class:`ModelError` subclass for ``exc``.
    """
    message = f"batch exchange failed: {exc}"
    # Ordering matters: each pattern must precede its own base class, and
    # ``APITimeoutError`` is a subclass of ``APIConnectionError``.
    match exc:
        case APIStatusError():
            return _classify_status(exc.status_code, message)
        case APITimeoutError():
            return ModelTimeoutError(message)
        case APIConnectionError():
            return ModelUnavailableError(message)
        case json.JSONDecodeError():
            # ADR-0063's narrow allowlist: an intermediary substituted its own
            # error page, or the body was cut off. Both say the *path* failed and
            # nothing about our request, which is what makes it retryable and
            # routable.
            return ModelUnavailableError(message)
        case _:
            return ModelError(message)


def _to_message_params(item: BatchRequest) -> tuple[str | None, list[MessageParam]]:
    """Split one item's turns into the vendor's ``system`` and ``messages`` halves.

    Args:
        item: The item to translate. Already validated, so no ``Role.TOOL`` turn
            reaches here.

    Returns:
        The joined system prompt (or ``None`` where there was none) and the
        conversation turns.
    """
    system: list[str] = []
    turns: list[MessageParam] = []
    for message in item.messages:
        match message.role:
            case Role.SYSTEM:
                system.append(message.content)
            case Role.USER:
                turns.append({"role": "user", "content": message.content})
            case Role.ASSISTANT:
                turns.append({"role": "assistant", "content": message.content})
            case Role.TOOL:  # pragma: no cover - refused before translation
                msg = f"item {item.item_id!r} carries a tool-role message"
                raise ModelError(msg)
    return ("\n\n".join(system) if system else None), turns


def _text_of(message: object) -> str | None:
    """The assistant's text from a vendor message, or ``None`` if it carries none.

    A batch answer with no text block is not a reply a caller can read, and
    ADR-0143 §5 has a kind for exactly that — ``UNUSABLE_RESPONSE``, mirroring
    ``ModelResponseError``. Returning ``None`` is what routes it there.
    """
    blocks = getattr(message, "content", None)
    if not isinstance(blocks, list):
        return None
    parts = [block.text for block in blocks if isinstance(block, TextBlock)]
    return "".join(parts) if parts else None


def _outcome_of(response: MessageBatchIndividualResponse) -> BatchItemOutcome:
    """Map one vendor result line onto ADR-0143 §4's four kinds.

    Args:
        response: One line of the batch's results file.

    Returns:
        The outcome for that item, with the payload §9 binds to its kind.
    """
    result = response.result
    match result.type:
        case "canceled":
            return BatchItemOutcome(item_id=response.custom_id, kind=BatchOutcomeKind.CANCELLED)
        case "expired":
            return BatchItemOutcome(item_id=response.custom_id, kind=BatchOutcomeKind.EXPIRED)
        case "errored":
            error = result.error.error
            kind = _FAILURE_KIND_BY_ERROR_TYPE.get(error.type, BatchFailureKind.UNKNOWN)
            return BatchItemOutcome(
                item_id=response.custom_id,
                kind=BatchOutcomeKind.FAILED,
                failure=BatchItemFailure(kind=kind, detail=f"{error.type}: {error.message}"),
            )
        case "succeeded":
            return _succeeded_outcome(response.custom_id, result.message)


def _succeeded_outcome(item_id: str, message: object) -> BatchItemOutcome:
    """Turn a vendor-succeeded result into an outcome, or into the failure it really is.

    Two answers the vendor calls a success are not one at this seam, and both are
    classified rather than passed through, so that a caller's retry logic reads the
    same as it would after ``complete`` (ADR-0143 §5):

    * ``stop_reason == "refusal"`` is the safety filter, which the per-request seam
      surfaces as ``ModelContentFilterError``. Handing it back as a ``SUCCEEDED``
      reply would make a refusal indistinguishable from an answer.
    * a message carrying no text block has nothing a caller can read, which is
      ``ModelResponseError``'s case.
    """
    if getattr(message, "stop_reason", None) == "refusal":
        return BatchItemOutcome(
            item_id=item_id,
            kind=BatchOutcomeKind.FAILED,
            failure=BatchItemFailure(
                kind=BatchFailureKind.CONTENT_FILTER,
                detail="the provider's safety filter refused this item",
            ),
        )
    text = _text_of(message)
    if text is None:
        return BatchItemOutcome(
            item_id=item_id,
            kind=BatchOutcomeKind.FAILED,
            failure=BatchItemFailure(
                kind=BatchFailureKind.UNUSABLE_RESPONSE,
                detail="the provider returned a message carrying no readable text",
            ),
        )
    return BatchItemOutcome(
        item_id=item_id,
        kind=BatchOutcomeKind.SUCCEEDED,
        message=Message(role=Role.ASSISTANT, content=text),
    )


class AnthropicBatchCompleter:
    """Bulk completion against Anthropic's Message Batches API.

    Structurally implements
    :class:`~ai_assistant.core.protocols.BatchCompleter`. The client is injected
    rather than built here, for the reason ADR-0143 §2 gives about ``issuer``: the
    composition root is where the knowledge about *which account* lives, so it is
    also where the credential belongs. It is what makes the class testable against
    a replaced transport without a credential and without a socket.

    **``issuer`` is an assertion this class cannot check, and says so.** It is a
    non-secret label naming the account the credential reaches, supplied by whoever
    configured that credential. A deployment that mislabels two accounts alike gets
    a handle accepted against the wrong one. The alternative on offer was not a
    stronger guarantee but a weaker one dressed as a proof: the client exposes no
    account identity to derive a label from, and a credential fingerprint would
    reject a handle that is still perfectly reachable the moment a key is rotated.
    """

    def __init__(
        self,
        *,
        client: AsyncAnthropic,
        issuer: str,
        default_model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_items: int | None = DEFAULT_MAX_BATCH_ITEMS,
    ) -> None:
        """Wire this completer to a client and an account.

        Args:
            client: The vendor client to send over. Its lifetime is the caller's;
                nothing here closes it.
            issuer: The non-secret account label stamped on every handle this mints
                and compared against every handle it is handed. **Never** a
                credential or any part of one — handles are written to disk.
            default_model: The ``"provider:model"`` spec used when a call does not
                override it. A bare vendor model name is also accepted.
            max_tokens: What each item may generate. Configuration of this
                implementation; the seam has no such parameter.
            max_items: The item count to refuse above, or ``None`` to declare no
                bound, which ADR-0143 §7 permits.
        """
        self._client = client
        self._issuer = issuer
        self._default_model = default_model
        self._max_tokens = max_tokens
        self._max_items = max_items

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
        """Validate the whole batch, create it, and return the handle naming it.

        Everything that can refuse happens on the near side of the provider call,
        and nothing happens after the provider accepts except returning — so the
        window in which a cancellation can leave a batch created but unreported is
        exactly one round trip (ADR-0143 §2). That window is **not** closed here,
        and no idempotency promise is made on ``batch_key``: the vendor transmits
        no idempotency key, carries no caller-supplied field on the batch, and
        filters no list by one, so a promise to recover an accepted batch by the
        caller's key could only have been kept by guessing.

        Args:
            batch_key: The caller's key, carried unchanged onto the handle and
                never sent to the provider — there is nowhere on the vendor's batch
                object to put it.
            items: The batch's items. Non-empty, ids unique, each conversation
                awaiting a reply.
            model: Optional ``"provider:model"`` override for the whole batch.

        Returns:
            The handle naming the accepted batch.

        Raises:
            ModelError: For each refusal on the near side of the provider call —
                an empty batch, a malformed item, a duplicate ``item_id``, an
                over-large batch, or a spec naming another provider — carrying
                ADR-0066 §3's disposition. A provider failure is narrowed to the
                most specific subclass.
        """
        snapshot = tuple(item.model_copy(deep=True) for item in items)
        vendor_model = self._vendor_model(model)
        self._refuse_unacceptable(snapshot)
        requests = [self._request_for(item, vendor_model) for item in snapshot]

        try:
            batch = await self._client.messages.batches.create(requests=requests)
        except Exception as exc:
            raise _classify(exc) from exc

        return BatchHandle(
            batch_key=batch_key,
            batch_id=batch.id,
            issuer=self._issuer,
            submitted_at=batch.created_at,
        )

    async def poll(self, handle: BatchHandle) -> BatchStatus:
        """Retrieve the batch's counts and report them, without waiting for it."""
        self._refuse_foreign(handle)
        batch = await self._retrieve(handle)
        total, settled = self._counts(batch)
        return BatchStatus(
            handle=handle,
            state=BatchState.COMPLETE if settled == total else BatchState.PENDING,
            total=total,
            settled=settled,
            # `archived_at` is the vendor's own words for "the time at which the
            # Message Batch was archived and its results became unavailable" — the
            # results retention of ADR-0143 §6, and a different field from
            # `expires_at`, which is the *processing* window and surfaces per item
            # as an EXPIRED outcome instead. The SDK exposes no forward-looking
            # retention field, so before the provider archives a batch this
            # implementation cannot state one, and §6's `None` is the honest answer
            # rather than a duration guessed from documentation.
            results_expire_at=batch.archived_at,
        )

    async def fetch(self, handle: BatchHandle) -> Sequence[BatchItemOutcome]:
        """Read a settled batch's results file: one outcome per submitted item.

        Raises:
            ModelError: If the handle is not this issuer's, if the batch has not
                settled, if its results retention has lapsed, or if the exchange
                fails. A short results file raises too, and that is the clause
                worth its own sentence: a fetch that quietly returned 900 outcomes
                for a 1,986-item batch would be read as 1,086 expired items, and a
                benchmark built on it would report a score for a run that never
                happened (ADR-0143 §6).
        """
        self._refuse_foreign(handle)
        batch = await self._retrieve(handle)
        total, settled = self._counts(batch)
        if settled != total:
            msg = (
                f"batch {handle.batch_id!r} has settled {settled} of {total} items; "
                f"fetch is defined only for a COMPLETE batch"
            )
            raise ModelError(msg)
        if batch.archived_at is not None:
            msg = (
                f"batch {handle.batch_id!r} was archived at {batch.archived_at.isoformat()} "
                f"and its results are no longer available"
            )
            raise ModelError(msg)
        if batch.results_url is None:
            msg = f"batch {handle.batch_id!r} has settled but the provider offers no results file"
            raise ModelResponseError(msg)

        outcomes = await self._read_results(handle)
        if len(outcomes) != total:
            msg = (
                f"batch {handle.batch_id!r} reports {total} items but its results file "
                f"holds {len(outcomes)}; a short read would be scored as expired items"
            )
            raise ModelResponseError(msg)
        return outcomes

    async def _read_results(self, handle: BatchHandle) -> tuple[BatchItemOutcome, ...]:
        """Stream the results file and map each line onto an outcome."""
        try:
            decoder = await self._client.messages.batches.results(handle.batch_id)
            try:
                return tuple([_outcome_of(response) async for response in decoder])
            finally:
                await decoder.close()
        except ModelError:
            raise
        except Exception as exc:
            raise _classify(exc) from exc

    async def _retrieve(self, handle: BatchHandle) -> MessageBatch:
        """One bounded exchange: what the provider currently says about this batch."""
        try:
            return await self._client.messages.batches.retrieve(handle.batch_id)
        except Exception as exc:
            raise _classify(exc) from exc

    def _counts(self, batch: MessageBatch) -> tuple[int, int]:
        """The batch's ``total`` and ``settled``, read from the provider's tallies.

        ``state`` is derived from these and never from ``processing_status``: the
        type binds ``COMPLETE`` to ``settled == total`` in both directions
        (ADR-0143 §9), so a status assembled from two sources that momentarily
        disagreed would not construct at all.

        Raises:
            ModelResponseError: If the provider reports a batch of no items, which
                ``BatchStatus`` cannot represent and ``submit`` cannot have created.
        """
        counts = batch.request_counts
        total = (
            counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired
        )
        if total < 1:
            msg = f"provider reports batch {batch.id!r} as holding no items"
            raise ModelResponseError(msg)
        return total, total - counts.processing

    def _request_for(self, item: BatchRequest, model: str) -> batch_create_params.Request:
        """Render one validated item as the vendor's per-request payload."""
        system, turns = _to_message_params(item)
        params: MessageCreateParamsNonStreaming = {
            "model": model,
            "max_tokens": self._max_tokens,
            "messages": turns,
        }
        if system is not None:
            params["system"] = system
        return {"custom_id": item.item_id, "params": params}

    def _vendor_model(self, override: str | None) -> str:
        """Resolve a ``"provider:model"`` spec to the vendor's own model name.

        Raises:
            ModelError: If the spec names a provider this implementation does not
                answer for. A caller error with ADR-0066 §3's disposition, refused
                before the provider is contacted: sending one vendor's batch under
                another vendor's name is not a failure a retry or a reroute fixes.
        """
        spec = override if override is not None else self._default_model
        provider, separator, name = spec.partition(":")
        if not separator:
            return spec
        if provider != _PROVIDER_NAME:
            msg = (
                f"model spec {spec!r} names provider {provider!r}; this completer "
                f"answers only for {_PROVIDER_NAME!r}"
            )
            raise ModelError(msg)
        return name

    def _refuse_foreign(self, handle: BatchHandle) -> None:
        """Reject a handle issued against another account.

        Object identity is deliberately not the test: a restarted process builds a
        new completer, and rejecting a handle it persisted would defeat the one
        thing the three-member shape exists to make possible (ADR-0143 §2).

        Raises:
            ModelError: If the handle's ``issuer`` is not this completer's.
        """
        if handle.issuer != self._issuer:
            msg = (
                f"handle names issuer {handle.issuer!r}; this completer answers only "
                f"for {self._issuer!r}"
            )
            raise ModelError(msg)

    def _refuse_unacceptable(self, items: tuple[BatchRequest, ...]) -> None:
        """Apply every refusal that must land before the provider is contacted.

        Raises:
            ModelError: Neither retryable nor routable, because a malformed
                argument reproduces identically on every attempt from every route
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
            _refuse_malformed_history(item)


def _refuse_malformed_history(item: BatchRequest) -> None:
    """Hold one item's messages to ``ModelProvider.complete``'s precondition.

    Read as that docstring states it — a **necessary** condition admitting nothing
    by omission — which is why a tool-role turn is refused although the clause
    names only the other two shapes (ADR-0143 §3, §10).

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

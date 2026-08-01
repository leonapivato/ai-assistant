"""A :class:`~ai_assistant.core.protocols.ModelProvider` backed by pydantic-ai.

This is the one place a provider SDK is reached (indirectly, via pydantic-ai),
so the rest of the system stays model-agnostic. The adapter's only jobs are to
translate our provider-independent :class:`~ai_assistant.core.types.Message`
list into pydantic-ai's message history, drive a single completion, and
translate the result (and any failure) back into our own types.

It also owns the one question about a model spec that cannot be answered
anywhere else: whether the vendor it names is actually importable
(:func:`ensure_vendor_available`, ADR-0062 §2), and whether the deployment holds a
credential for it (:func:`ensure_credential_available`, issue #530). Answering
either means reaching pydantic-ai's provider registry, which only this layer may
do.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from pydantic_ai import Agent, models
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UserError,
)
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.providers import infer_provider, infer_provider_class

from ai_assistant.core.errors import (
    ConfigurationError,
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role

_HTTP_UNAUTHORIZED: Final = 401
_HTTP_FORBIDDEN: Final = 403
_HTTP_REQUEST_TIMEOUT: Final = 408
_HTTP_TOO_MANY_REQUESTS: Final = 429
_HTTP_SERVER_ERROR: Final = 500

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.messages import ModelMessage, ModelRequestPart


def ensure_vendor_available(spec: str) -> None:
    """Fail now if ``spec``'s vendor package is missing or unknown (ADR-0062 §2).

    ADR-0062 §1 and §3 moved three model-spec mistakes from a user's request to
    startup; this closes the fourth, the one that ADR-0062 §2 decided in
    principle and deferred in mechanism because the mechanism lives here.

    Why it is worth a check at all: such a spec fails at the first
    completion as a bare, **non-routable** ``ModelError`` (:func:`_classify` has
    nothing better to say about an ``ImportError``, and deliberately keeps it
    that way — see :func:`_classify_unwrapped`). ``RoutingProvider`` re-raises a
    non-routable failure without trying the next route (ADR-0013 §5), so one bad
    spec does not degrade the router, it **truncates** it: an unresolvable
    primary kills the whole configured fallback order, on every request. And a
    fallback is only ever reached once the primary has already failed, so the
    mistake surfaces at the exact moment it was being relied on.

    **This is deliberately key-free and offline.** It calls pydantic-ai's
    :func:`~pydantic_ai.providers.infer_provider_class`, which performs the
    vendor import and nothing else — it returns the provider *class* rather than
    an instance, so no API key is read and no client is built. That is why the
    check exists in this shape at all: the two obvious alternatives, flipping
    ``PydanticAIProvider``'s ``defer_model_check`` or calling
    ``models.infer_model``, both construct the vendor provider and therefore
    demand live credentials of anything that merely wires the system together
    (ADR-0062 §2 verified this: ``UserError: Set the ANTHROPIC_API_KEY …``).

    **What it does not promise.** It asks one question — is the package behind
    the spec's provider half importable — and a "yes" is not a promise that a
    completion will resolve. Three things stay late failures, all of them because
    answering them needs a credential, which is the boundary ADR-0062 §2 drew
    rather than an oversight:

    * whether the vendor offers the *named model*, which only a live call knows;
    * whether the deployment holds that vendor's API key;
    * for a ``gateway/…`` spec, whether the Pydantic AI Gateway exposes that
      upstream. Only six ``gateway/`` prefixes are in pydantic-ai's own
      vocabulary, and this resolves every one of them correctly; but a
      hand-written ``gateway/openrouter:…`` passes here — ``openrouter``'s
      package really is importable — and then fails in ``gateway_provider``,
      which refuses to answer anything at all before it has read
      ``PYDANTIC_AI_GATEWAY_API_KEY``. No load-time check reaches past that, so
      closing the corner would not make a gateway spec safe (issue #371).

    **It raises ``ConfigurationError``, never a ``ModelError``**, and the choice
    is load-bearing rather than cosmetic. A ``ModelError`` carries a routing
    disposition — ``retryable`` and ``routable`` — which only means something to
    a caller deciding whether to *try again*; there is nothing to try again here,
    because a missing package reproduces identically on every attempt from every
    route. Putting a completion-time type on a wiring failure is exactly the
    confusion ADR-0063's allowlist keeps out of :func:`_classify_unwrapped`.
    ``ConfigurationError`` is also where ADR-0062 §§1, 3 put the other three
    spec mistakes, and what ``RoutingProvider`` raises for an empty route list,
    so an adapter's ``AssistantError`` boundary already reports it as a startup
    misconfiguration rather than a failed request. The raw ``ImportError`` is
    chained but does not cross the subsystem boundary on its own.

    Args:
        spec: A pydantic-ai ``"provider:model"`` spec, e.g.
            ``"anthropic:claude-opus-4-8"``.

    Raises:
        ConfigurationError: If ``spec`` names no provider, names one pydantic-ai
            does not know, or names one whose optional package is not installed.
    """
    # pydantic-ai's own split, so this can never disagree with `infer_model`
    # about where the provider half ends (the model half may contain colons).
    provider_name, _ = models.parse_model_id(spec)
    if provider_name is None:
        msg = (
            f"model spec {spec!r} names no provider; expected pydantic-ai's "
            f"'provider:model' form, e.g. 'anthropic:claude-opus-4-8'"
        )
        raise ConfigurationError(msg)

    try:
        infer_provider_class(provider_name)
    except ImportError as exc:
        # The vendor is one pydantic-ai knows, but its optional package was never
        # installed (ADR-0061 §1 installs two). pydantic-ai's own message names
        # the extra to install, so it is quoted rather than paraphrased.
        msg = (
            f"model spec {spec!r} names provider {provider_name!r}, whose package "
            f"is not installed: {exc}"
        )
        raise ConfigurationError(msg) from exc
    except ValueError as exc:
        # Well-formed (ADR-0062 §1 checked that) but naming a vendor pydantic-ai
        # has never heard of — a typo, or a provider from a different release.
        msg = f"model spec {spec!r} names an unknown provider {provider_name!r}: {exc}"
        raise ConfigurationError(msg) from exc


def ensure_credential_available(spec: str) -> None:
    """Fail now if ``spec``'s vendor holds no credential (issue #530).

    The sibling of :func:`ensure_vendor_available`, answering the next question
    along: that function asks whether the vendor's *package* is importable, and
    a "yes" is explicitly not a promise that a completion will resolve — its own
    docstring lists "whether the deployment holds that vendor's API key" as a
    late failure, "the boundary ADR-0062 §2 drew rather than an oversight".

    **What moved the boundary is the process model, not a new opinion about
    credentials.** For a one-shot CLI, late is correct: the failure lands on the
    command that needed a key and the commands that did not are not blocked by
    its absence (#530 is explicit that nothing here is a defect in the shipped
    application). For a resident hub it inverts. ADR-0083 §3 signals readiness
    last and §5/§6 make a fault that cannot clear a stay-down exit, on the
    owner's ruling that "if the hub is not running, there is a reason, and the
    reason is legible". A hub with no credential would start, signal ready, look
    healthy to every supervisor and monitor, and fail hours later on a user's
    first real request. So the hub asks this at startup; **nothing else does**,
    which is why this is a separate function rather than a line inside its
    sibling or inside ``build_engine``.

    **It is a presence check and never a validity check, and the line is
    ADR-0083 §3's**: "nothing in startup may block indefinitely on a network".
    :func:`~pydantic_ai.providers.infer_provider` *constructs* the vendor
    provider — which is what reads the credential out of the environment, and is
    exactly what :func:`ensure_vendor_available` avoids doing for that reason —
    but it performs no completion and no round trip, so startup stays local-only
    and the supervisor's start timeout keeps its meaning. A key that is present
    but revoked, wrong or rate-limited therefore still fails at request time, as
    a :class:`~ai_assistant.core.errors.ModelAuthError` carrying a completion-time
    routing disposition. Promising more than presence would mean egress on every
    boot, against ADR-0004's residency posture and §3's clause alike.

    **Call it after :func:`ensure_vendor_available`, not instead of it.** This
    presumes the vendor resolved: an uninstalled package surfaces here as a bare
    ``ImportError`` with a worse message than its sibling's.

    Args:
        spec: A pydantic-ai ``"provider:model"`` spec, e.g.
            ``"anthropic:claude-opus-4-8"``.

    Raises:
        ConfigurationError: If the deployment holds no credential for ``spec``'s
            vendor. The same class its sibling raises, and for the same reason —
            there is nothing to try again, so a ``ModelError``'s ``retryable``
            and ``routable`` would be meaningless on it. It is also what lets the
            hub map this to a stay-down exit through one type check, since every
            other startup misconfiguration already arrives as this class.
    """
    provider_name, _ = models.parse_model_id(spec)
    if provider_name is None:
        msg = (
            f"model spec {spec!r} names no provider; expected pydantic-ai's "
            f"'provider:model' form, e.g. 'anthropic:claude-opus-4-8'"
        )
        raise ConfigurationError(msg)

    try:
        infer_provider(provider_name)
    except UserError as exc:
        # pydantic-ai's own message names the exact variable to set — the whole
        # value of asking it rather than keeping a per-vendor table of variable
        # names outside `models/`, which would go stale silently. Quoted rather
        # than paraphrased, as the sibling quotes its own.
        msg = (
            f"model spec {spec!r} names provider {provider_name!r}, for which this "
            f"deployment holds no credential: {exc}"
        )
        raise ConfigurationError(msg) from exc


def _to_model_messages(messages: Sequence[Message]) -> list[ModelMessage]:
    """Translate our flat message list into pydantic-ai message history.

    Consecutive request-side turns (system, user) are grouped into a single
    :class:`ModelRequest`; each assistant turn becomes a :class:`ModelResponse`.

    Args:
        messages: Conversation history in our provider-independent form.

    Returns:
        The equivalent pydantic-ai ``ModelMessage`` history.

    Raises:
        ModelError: If a tool-role message is encountered; tool exchanges are
            not yet representable at this layer (they need a tool-call id).
    """
    history: list[ModelMessage] = []
    pending: list[ModelRequestPart] = []

    def flush() -> None:
        if pending:
            history.append(ModelRequest(parts=list(pending)))
            pending.clear()

    for message in messages:
        match message.role:
            case Role.SYSTEM:
                pending.append(SystemPromptPart(content=message.content))
            case Role.USER:
                pending.append(UserPromptPart(content=message.content))
            case Role.ASSISTANT:
                flush()
                history.append(ModelResponse(parts=[TextPart(content=message.content)]))
            case Role.TOOL:
                msg = "tool-role messages are not yet supported by PydanticAIProvider"
                raise ModelError(msg)

    flush()
    return history


def _classify_status(status_code: int, message: str) -> ModelError:
    """Map an HTTP status from the provider onto the error taxonomy.

    Args:
        status_code: The status code the provider returned.
        message: The already-formatted message for the resulting error.

    Returns:
        The most specific :class:`ModelError` subclass for ``status_code``.
    """
    if status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
        return ModelAuthError(message)
    if status_code == _HTTP_TOO_MANY_REQUESTS:
        return ModelRateLimitError(message)
    if status_code == _HTTP_REQUEST_TIMEOUT:
        return ModelTimeoutError(message)
    if status_code >= _HTTP_SERVER_ERROR:
        return ModelUnavailableError(message)
    # Any other 4xx is a malformed request on our side: retrying is pointless.
    return ModelError(message)


def _classify_unwrapped(exc: Exception, message: str) -> ModelError:
    """Classify a failure that never entered pydantic-ai's exception hierarchy.

    An exception raised by the vendor SDK — or by pydantic-ai's adapter for it —
    that pydantic-ai does not wrap arrives at the seam as whatever the vendor
    raised, which is usually a bare builtin. ADR-0063 admits those into the
    taxonomy by **allowlist**, never by a blanket "unrecognised means transient",
    and the admission rule is deliberately narrow: the type must be unambiguous
    evidence that *the response body was not the wire format*. Such a failure can
    only have happened after bytes came back, so it says nothing about our
    request — the fault is in the path, which is what makes it both retryable and
    routable.

    Everything else keeps the conservative default, because the alternative
    retries and re-routes failures that reproduce identically on every attempt
    from every route: a provider extra that was never installed surfaces here as
    ``ImportError`` (ADR-0061 §1), and a model spec naming an unknown provider as
    ``ValueError``. Both would burn the whole retry budget and every fallback
    before failing anyway.

    Args:
        exc: The unwrapped exception raised during a completion.
        message: The already-formatted message for the resulting error.

    Returns:
        The most specific :class:`ModelError` subclass for ``exc``.
    """
    match exc:
        case json.JSONDecodeError():
            # An intermediary (load balancer, proxy, captive portal) substituted
            # its own HTML error page for the model's answer, or the response was
            # cut off partway. Both vendor SDKs let this escape as a bare
            # JSONDecodeError, so before ADR-0063 it fell through as neither
            # retryable nor routable — wrong on both counts for the most
            # transient failure there is.
            #
            # Matched on JSONDecodeError itself and never on its ValueError base:
            # the unknown-provider ValueError above is the exact thing the base
            # would over-match, and a typo in configuration must stay permanent.
            #
            # ModelUnavailableError for its disposition, which is the part that
            # matters: retryable, because the next attempt may not meet the
            # broken hop, and routable, because a different provider is a
            # different path. Its "unreachable or failing" reads correctly here —
            # a 200 carrying someone else's error page is the provider's path
            # failing, whatever status the failing hop chose to put on it.
            return ModelUnavailableError(message)
        case _:
            return ModelError(message)


def _classify(exc: Exception) -> ModelError:
    """Translate a pydantic-ai failure into our own error taxonomy.

    Every failure is still wrapped as a :class:`ModelError`, so the contract
    that ``complete`` raises only ``ModelError`` is unchanged; this only narrows
    the subclass. Unrecognised failures stay a bare, non-retryable
    ``ModelError`` — misclassifying something as retryable is worse than not
    classifying it at all.

    This function handles pydantic-ai's own hierarchy. Anything else the vendor
    SDK raised falls through to :func:`_classify_unwrapped`, which holds the
    narrow allowlist ADR-0063 admits from outside it.

    Args:
        exc: The exception pydantic-ai raised during a completion.

    Returns:
        The most specific :class:`ModelError` subclass for ``exc``.
    """
    message = f"model completion failed: {exc}"
    # Ordering matters: each pattern must precede its own base class.
    match exc:
        case ModelHTTPError():
            return _classify_status(exc.status_code, message)
        case ContentFilterError():
            return ModelContentFilterError(message)
        case UnexpectedModelBehavior():
            return ModelResponseError(message)
        case ModelAPIError():
            # Reached the provider layer but never got a status code — i.e. a
            # connection-level failure. A transport *timeout* also lands here,
            # not on the arm below: an SDK wraps it (e.g. anthropic's
            # APITimeoutError, a subclass of APIConnectionError) and pydantic-ai
            # re-raises it as ModelAPIError. Retryable either way, so the
            # behaviour is right; only the label is coarse. Classifying it as a
            # timeout would mean importing httpx here and depending on it
            # directly — deferred until streaming, where pydantic-ai does let
            # bare httpx errors escape from chunk reads.
            return ModelUnavailableError(message)
        case TimeoutError():
            # Defensive: a deadline raised *inside* the call, e.g. an http
            # client configured with its own. RetryingProvider's deadline is
            # applied outside this adapter, so it never reaches here.
            return ModelTimeoutError(message)
        case _:
            # Nothing in pydantic-ai's hierarchy matched, so this is whatever the
            # vendor SDK itself raised. ADR-0063 decides which of those, if any,
            # are transient.
            return _classify_unwrapped(exc, message)


class PydanticAIProvider:
    """Model-agnostic completion client implemented on top of pydantic-ai.

    Structurally implements :class:`~ai_assistant.core.protocols.ModelProvider`.
    The default model may be a ``"provider:model"`` string (the production path)
    or a pydantic-ai :class:`~pydantic_ai.models.Model` instance (used by tests
    to inject a deterministic fake without network access).
    """

    def __init__(self, default_model: models.Model | str) -> None:
        """Initialise the provider.

        Args:
            default_model: The model used when a call does not override it,
                either as a pydantic-ai ``"provider:model"`` name or a
                pre-built ``Model`` instance.
        """
        self._default_model = default_model
        # ``defer_model_check`` keeps construction offline: a string model is
        # only resolved (and credentials required) at first completion.
        self._agent: Agent[None, str] = Agent(model=default_model, defer_model_check=True)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        """Produce the assistant's next message given the conversation so far.

        Both malformed-argument shapes the Protocol's precondition names are
        refused here, before :class:`Agent` is reached (ADR-0066 §6). The
        trailing-assistant case is the one with teeth: ``Agent.run`` resolves a
        history whose last entry is already a response as a *finished* run, so it
        would return that assistant turn's text without a round trip — an echo
        indistinguishable from a real answer, which no wrapper above this seam
        could see (ADR-0066 §2, issue #351).

        Args:
            messages: Conversation history, oldest first. Must be non-empty, and
                must not end on a ``Role.ASSISTANT`` turn.
            model: Optional ``"provider:model"`` override; falls back to the
                configured default when ``None``.

        Returns:
            The assistant's reply as a :class:`~ai_assistant.core.types.Message`.

        Raises:
            ModelError: If ``messages`` is empty, ends on a ``Role.ASSISTANT``
                turn, or the provider call fails. The two malformed-argument
                cases raise the bare class — neither retryable nor routable,
                which is the disposition the Protocol requires — because a caller
                fixes them at the call site rather than by trying again. A
                provider failure is narrowed to the most specific subclass
                (e.g. :class:`~ai_assistant.core.errors.ModelRateLimitError`),
                whose ``retryable`` attribute says whether another attempt could
                succeed.
        """
        if not messages:
            msg = "complete() requires at least one message"
            raise ModelError(msg)
        if messages[-1].role is Role.ASSISTANT:
            msg = (
                "complete() requires a conversation awaiting a reply; this "
                "history already ends with an assistant turn"
            )
            raise ModelError(msg)

        history = _to_model_messages(messages)

        try:
            result = await self._agent.run(
                user_prompt=None,
                message_history=history,
                model=model,
            )
        except Exception as exc:
            raise _classify(exc) from exc

        return Message(role=Role.ASSISTANT, content=result.output)

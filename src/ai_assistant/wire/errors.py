"""How a failure crosses the wire, and how a transport failure is told apart.

Two vocabularies meet here and ADR-0085 §9 keeps them apart deliberately:

* **A declared failure of the engine surface** is an
  :class:`~ai_assistant.core.errors.AssistantError`. It travels as an ``error``
  frame carrying "a typed code and a message" (ADR-0084 §3) and is *reconstructed*
  on the far side, so ``answer()`` raises the same type in-process and over the
  wire. That is the substitutability ADR-0084 §4-§5 promote the surface for.
* **A transport failure** is not an engine failure at all. ADR-0085 §9: "ADR-0084
  §3's undecodable-frame close, version mismatch, credential refusal and
  second-concurrent-request close are all transport conditions… They are not
  ``AssistantEngine`` failures and no Protocol method declares them." They are
  :class:`TransportError`, a hierarchy of this package's own, and the client
  renders them differently on purpose — "a connection-level close is a **transport**
  failure, which is not the same event as a request the hub received and declined,
  and ruling 4's legibility is the reason the difference survives to the user
  rather than being flattened into one message" (ADR-0084 §3).
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Final, NoReturn

from ai_assistant.core import errors as core_errors
from ai_assistant.core.errors import AssistantError
from ai_assistant.wire.codec import encode_projection, project

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The envelope member names of an error payload (ADR-0085 §10a). **Every member
#: is always present**, deliberately: a conditional member would be a second thing
#: two implementations could do differently, and ``"details":null`` costs fifteen
#: bytes to remove the question.
_CODE: Final = "code"
_MESSAGE: Final = "message"
_DETAILS: Final = "details"
_REDUCED: Final = "reduced"

#: Constructor parameters that are never structured state: ``self`` and the
#: message the wire carries separately.
_NOT_DETAILS: Final = frozenset({"self", "message"})


class TransportError(Exception):
    """A failure of the connection, not of the request (ADR-0085 §9).

    Deliberately **not** an :class:`~ai_assistant.core.errors.AssistantError`: no
    Protocol method declares one, and a caller that catches ``AssistantError`` is
    catching the engine's failures rather than the wire's. An adapter renders the
    two differently because they mean different things to a user — one is "the hub
    said no", the other is "there was no hub, or it stopped talking".
    """


class HubUnavailableError(TransportError):
    """No hub is listening, or the connection went away mid-request.

    ADR-0084 §9: "When no hub is listening, the client fails with a message naming
    the socket path it tried and how to start the hub, and **exits non-zero**. It
    does not spawn the hub (ruling 3) and does not build an in-process engine
    (ruling 5)."
    """


class ConnectionClosedError(TransportError):
    """The peer closed the connection where a frame was expected.

    Distinct from :class:`ProtocolError` because it is not a violation: a clean
    close between frames is how a stateless client finishes, and the server sees
    one on every command. It becomes a *failure* only when a reply was outstanding,
    which is where ADR-0084 §3's rule bites — "a close with no response is reported
    as what the client was attempting when the connection went away".
    """


class ProtocolError(TransportError):
    """A peer broke the protocol's own rules.

    A version mismatch, a credential this transport does not carry, a correlation
    id that does not match the outstanding request, an error code the client does
    not know. ADR-0085 §10a is explicit that the last of these is "a protocol
    violation, not a widening": a client meeting an unknown code "does **not** fall
    back to the nearest ancestor it recognises", because that would manufacture a
    typed refusal the server never sent.
    """


class CredentialNotSupportedError(ProtocolError):
    """A connect frame carried a credential this transport does not check.

    **A type of its own rather than a plain ``ProtocolError``, and the reason is a
    bug this once caused.** ADR-0084 §3 sorts a connect frame's faults into two
    answers — a credential is "a member of an envelope that parsed", so it is
    "reported properly and only then does the connection close", while an
    undecodable frame closes with no response at all. The server has to tell those
    apart, and telling them apart by catching ``ProtocolError`` silently caught
    :class:`UndecodableFrameError` too (it is a subclass), so an oversized handshake
    was answered with a credential refusal instead of being closed on. Naming the
    one case that earns a typed error is what makes the distinction unmissable
    rather than a matter of which ``except`` clause comes first.
    """


class UndecodableFrameError(ProtocolError):
    """No envelope decoded, so there is nothing to answer and nothing to quote.

    ADR-0084 §3 fixes the whole class rather than a list that would go stale: "a
    malformed or oversized length prefix, a read deadline expiring mid-frame, bytes
    that are not valid UTF-8, text that is not valid JSON, JSON that is not an
    object, and an object missing a required member". The server's response is to
    **close the connection without a response** — "there is no correlation id to
    quote and **no agreed encoding to reply in**".
    """


def details_of(exc: AssistantError) -> dict[str, Any] | None:
    """The exception's structured state, as ADR-0085 §10a defines it.

    "An ``AssistantError`` subtype that carries structured state declares it as
    **public attributes whose names match its constructor's keyword parameters**,
    and ``details`` is exactly those attributes." Reading the constructor rather
    than a per-error table is what makes the schema mechanical: a hand-kept table
    "would go stale the first time a structured error is added".

    **``details_elided`` is excluded**, because it is transport metadata rather
    than exception state — it says something about *this delivery*, not about the
    failure, and it is carried by the frame's own ``reduced`` member. Without the
    exclusion "every exception would carry structured state, ``details: null``
    could never be sent, and no subtype's constructor would accept the member back".

    Args:
        exc: The failure being sent.

    Returns:
        The members ``details`` carries, or ``None`` where the type carries none.
    """
    initialiser = type(exc).__init__
    if initialiser in (AssistantError.__init__, object.__init__):
        return None
    names = [
        parameter.name
        for parameter in inspect.signature(initialiser).parameters.values()
        if parameter.name not in _NOT_DETAILS
        and parameter.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        and parameter.name != "details_elided"
    ]
    if not names:
        return None
    return {name: getattr(exc, name) for name in names}


def error_payload(exc: AssistantError, *, max_bytes: int) -> dict[str, Any]:
    """Render one declared failure as ADR-0085 §10a's error payload.

    ``code`` is **the exception type's own class name**, which "makes the mapping
    total by construction rather than by a registry someone maintains" — and one
    code per *concrete* type, never flattened to a declared base, because encoding
    a ``ModelRateLimitError`` as ``"ModelError"`` would hand a client "a
    classification the server did not make" (ADR-0077 §3).

    **An oversized error payload has a fixed reduction rather than a refusal**, and
    the reason is worth keeping in view: answering a too-large error with
    :class:`~ai_assistant.core.errors.OversizedValueError` "is not available"
    because "the response to a failed error delivery would itself be an error
    frame, so the rule would recurse, and it would mislabel — the value the caller
    sent was not oversized, the diagnosis of it was". So ``details`` is set to
    ``null`` and ``message`` is truncated until the payload fits, and ``reduced``
    becomes ``true``.

    Truncating a *message* is acceptable where truncating a payload is not
    (ADR-0085 §10a): ADR-0073 §4's no-silent-truncation rule protects a citation
    rendered as evidence — a warrant a user is judging — and an error message is a
    diagnostic string. Nothing about the user's data is dropped: the ids that would
    have travelled in ``details`` are still in the hub's own state and its logs.

    Args:
        exc: The failure being sent.
        max_bytes: The contract limit the payload must fit inside.

    Returns:
        The error payload's members.

    Raises:
        ValueError: If even a payload with an empty message exceeds ``max_bytes``.
            ADR-0085 §10a states the reduction "is always satisfiable: §8d's floor
            leaves room for a code, the member names and a non-empty message at the
            smallest legal ``hub_max_frame_bytes``", so reaching this is a bound
            that was configured below its own floor.
    """
    payload: dict[str, Any] = {
        _CODE: type(exc).__name__,
        _MESSAGE: str(exc),
        _DETAILS: details_of(exc),
        _REDUCED: False,
    }
    if _payload_size(payload) <= max_bytes:
        return payload

    payload[_DETAILS] = None
    payload[_REDUCED] = True
    message = payload[_MESSAGE]
    while _payload_size(payload) > max_bytes and message:
        # Shrink geometrically rather than by one character: a message is bounded
        # only by the limit itself, so a linear walk would be quadratic in it.
        message = message[: len(message) * 3 // 4]
        payload[_MESSAGE] = message
    if _payload_size(payload) > max_bytes:
        msg = (
            f"an error payload does not fit inside {max_bytes} bytes even with no message; "
            f"hub_max_frame_bytes is below ADR-0085 §8d's floor"
        )
        raise ValueError(msg)
    return payload


def _payload_size(payload: Mapping[str, Any]) -> int:
    """The canonical byte length of an error payload."""
    return len(encode_projection(project(payload)))


def raise_from_payload(payload: object) -> NoReturn:
    """Rebuild the declared failure an error frame carries, and raise it.

    ADR-0085 §10a: "A client reconstructs by calling the named type with the
    message positionally and the ``details`` members as keyword arguments."

    **A client that receives ``reduced: true`` raises the declared exception, with
    its structured state absent and *marked* absent.** An earlier draft of that
    clause had the client raise a transport-level failure instead, "which meant one
    ``answer()`` call raised ``UnresolvedEvidenceError`` in-process and something
    undeclared over the wire. Two observable failure contracts for one call is
    precisely what ADR-0084 §4-§5 promote this surface to prevent."

    Args:
        payload: The error frame's payload, as decoded.

    Raises:
        AssistantError: The declared failure, reconstructed.
        ProtocolError: If the payload is not an error payload, names a code this
            build does not know, or carries ``details`` the named type will not
            accept. Every one of those is a bug rather than a version skew to
            tolerate — ADR-0084 §3's exact version match means the two halves ship
            together — and raising "a half-populated exception whose empty field a
            caller would read as 'no ids were unresolved'" is the failure being
            refused.
    """
    if not isinstance(payload, dict):
        msg = f"an error frame's payload must be an object, got {type(payload).__name__}"
        raise ProtocolError(msg)
    try:
        code = payload[_CODE]
        message = payload[_MESSAGE]
        details = payload[_DETAILS]
        reduced = payload[_REDUCED]
    except KeyError as exc:
        msg = f"an error payload is missing its {exc.args[0]!r} member"
        raise ProtocolError(msg) from exc
    if not isinstance(code, str) or not isinstance(message, str) or not isinstance(reduced, bool):
        msg = "an error payload's code and message must be strings and reduced a boolean"
        raise ProtocolError(msg)

    kind = getattr(core_errors, code, None)
    if not (isinstance(kind, type) and issubclass(kind, AssistantError)):
        msg = (
            f"the hub reported error code {code!r}, which this build does not know; "
            f"the two halves are meant to ship together, so this is a protocol fault "
            f"rather than a version to tolerate"
        )
        raise ProtocolError(msg)
    if details is not None and not isinstance(details, dict):
        msg = f"an error payload's details must be an object or null, got {type(details).__name__}"
        raise ProtocolError(msg)

    try:
        failure = kind(message, **(details or {}))
    except (TypeError, ValueError) as exc:
        msg = (
            f"the hub's {code} details do not fit its own constructor ({exc}); refusing rather "
            f"than raising a half-populated exception a caller would read as an empty answer"
        )
        raise ProtocolError(msg) from exc
    failure.details_elided = reduced
    raise failure

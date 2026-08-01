"""A declared failure survives the wire, or is marked where it could not.

ADR-0085 §10a exists because "a typed failure that cannot be reconstructed on the
far side is not a contract". The clause it establishes is that ``answer()`` raises
:class:`~ai_assistant.core.errors.UnresolvedEvidenceError` in-process **and** over
the wire, with the same ids — and where the ids genuinely cannot fit, that the
shortfall is machine-detectable rather than silent.
"""

from __future__ import annotations

import json

import pytest

from ai_assistant.core.errors import (
    AssistantError,
    MemoryStoreError,
    ModelRateLimitError,
    OversizedValueError,
    UnknownContinuationError,
    UnresolvedEvidenceError,
)
from ai_assistant.wire.codec import canonical_payload
from ai_assistant.wire.errors import (
    ProtocolError,
    details_of,
    error_payload,
    raise_from_payload,
)

_ROOM = 4096


def _round_trip(exc: AssistantError, *, max_bytes: int = _ROOM) -> AssistantError:
    """Send one failure and rebuild it, **through the bytes**.

    The payload is encoded to ADR-0087's canonical form and decoded back before it
    is reconstructed, rather than being handed over as Python objects. That is the
    difference between testing the mapping and testing the delivery: a tuple of ids
    becomes a JSON array and comes back a ``list``, which the constructor must
    accept — and a test that skipped the encoding would never find out.
    """
    payload = json.loads(canonical_payload(error_payload(exc, max_bytes=max_bytes)))
    with pytest.raises(AssistantError) as caught:
        raise_from_payload(payload)
    return caught.value


def test_a_failure_with_no_structured_state_carries_a_code_and_a_message() -> None:
    """Every member is always present, ``details`` as ``null``.

    "A conditional member would be a second thing two implementations could do
    differently, and ``"details":null`` costs fifteen bytes to remove the question."
    """
    payload = error_payload(MemoryStoreError("the store would not write"), max_bytes=_ROOM)
    assert payload == {
        "code": "MemoryStoreError",
        "message": "the store would not write",
        "details": None,
        "reduced": False,
    }


def test_the_code_names_the_concrete_type_and_never_a_declared_base() -> None:
    """§10a: "One code per *concrete* type, never flattened to a declared base."

    "Encoding a ``ModelRateLimitError`` as ``"ModelError"`` would destroy exactly
    what ADR-0077 §3 requires to survive: it obliges a failed observing call to
    surface 'unwrapped and with its classification intact', and a client that
    received the base class has been handed a classification the server did not
    make."
    """
    rebuilt = _round_trip(ModelRateLimitError("slow down"))
    assert type(rebuilt) is ModelRateLimitError


@pytest.mark.parametrize(
    "exc",
    [
        UnresolvedEvidenceError("two are gone", ["a", "b"]),
        OversizedValueError("too big", limit=10, size=99, field="utterance"),
        OversizedValueError("too big", limit=10, size=99, field=None),
        UnknownContinuationError("that handle is from a previous process life"),
    ],
)
def test_a_declared_failure_round_trips_with_its_structured_state(exc: AssistantError) -> None:
    """The substitutability clause, on the two types that carry state and two that do not.

    "A client reconstructs by calling the named type with the message positionally
    and the ``details`` members as keyword arguments", and ``details`` is the
    exception's public attributes whose names match its constructor's keyword
    parameters — mechanical, so it cannot go stale "the first time a structured
    error is added".
    """
    rebuilt = _round_trip(exc)
    assert type(rebuilt) is type(exc)
    assert str(rebuilt) == str(exc)
    assert details_of(rebuilt) == details_of(exc)
    assert rebuilt.details_elided is False


def test_details_elided_is_never_sent_as_exception_state() -> None:
    """§10a: it is "transport metadata rather than exception state".

    "Without the exclusion every exception would carry structured state,
    ``details: null`` could never be sent, and no subtype's constructor would accept
    the member back."
    """
    payload = error_payload(UnresolvedEvidenceError("gone", ["a"]), max_bytes=_ROOM)
    assert payload["details"] == {"unresolved_ids": ("a",)}
    assert "details_elided" not in (payload["details"] or {})


def test_an_oversized_error_is_reduced_rather_than_refused() -> None:
    """§10a's reduction, and the reason a refusal is not available.

    "The response to a failed error delivery would itself be an error frame, so the
    rule would recurse, and it would mislabel — the value the caller sent was not
    oversized, the diagnosis of it was."

    The subject is ``unresolved_ids``, which is unbounded: "a refusal citing enough
    unresolved records is a *typed error that cannot be sent*".
    """
    huge = UnresolvedEvidenceError("could not resolve", [f"rec-{n}" for n in range(500)])
    payload = error_payload(huge, max_bytes=256)
    assert payload["details"] is None
    assert payload["reduced"] is True
    assert payload["message"]
    assert len(canonical_payload(payload)) <= 256


def test_a_reduced_payload_raises_the_declared_type_with_the_loss_marked() -> None:
    """§10a's substitutability requirement, and the draft that got it wrong.

    "An earlier draft had the client raise a *transport-level* failure instead,
    which meant one ``answer()`` call raised ``UnresolvedEvidenceError`` in-process
    and something undeclared over the wire. Two observable failure contracts for one
    call is precisely what ADR-0084 §4-§5 promote this surface to prevent."

    And the marker is what keeps the reconstruction honest: ``unresolved_ids``
    defaults to ``()``, so without it "a caller would be told that **nothing** was
    unresolved at the exact moment that too much was".
    """
    huge = UnresolvedEvidenceError("could not resolve", [f"rec-{n}" for n in range(500)])
    rebuilt = _round_trip(huge, max_bytes=256)
    assert type(rebuilt) is UnresolvedEvidenceError
    assert isinstance(rebuilt, UnresolvedEvidenceError)
    assert rebuilt.unresolved_ids == ()
    assert rebuilt.details_elided is True


def test_an_error_that_fits_is_not_marked_reduced() -> None:
    """The discriminating half: an implementation that always reduced would pass
    the case above and destroy every set of ids that did fit."""
    small = UnresolvedEvidenceError("could not resolve", ["rec-1"])
    rebuilt = _round_trip(small, max_bytes=_ROOM)
    assert isinstance(rebuilt, UnresolvedEvidenceError)
    assert rebuilt.unresolved_ids == ("rec-1",)
    assert rebuilt.details_elided is False


def test_an_unknown_code_is_a_protocol_violation_and_not_a_nearest_ancestor() -> None:
    """§10a: "An unknown code is a protocol violation, not a widening."

    "Falling back would manufacture a typed refusal the server never sent, and
    ADR-0084 §3's exact version match means the two halves ship together, so an
    unknown code is a bug rather than a version skew to tolerate."
    """
    with pytest.raises(ProtocolError, match="does not know"):
        raise_from_payload(
            {"code": "SomethingFromTheFuture", "message": "?", "details": None, "reduced": False}
        )


def test_a_code_naming_something_that_is_not_an_error_is_refused() -> None:
    """The code is looked up in ``core.errors``, so the lookup must not be naive.

    ``core.errors`` holds more than exception classes, and a payload naming one of
    them would otherwise be called and raised. Fail closed on anything that is not
    an ``AssistantError`` subtype.
    """
    with pytest.raises(ProtocolError, match="does not know"):
        raise_from_payload(
            {"code": "annotations", "message": "?", "details": None, "reduced": False}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "MemoryStoreError", "message": "x", "details": {"nope": 1}, "reduced": False},
        {"code": "OversizedValueError", "message": "x", "details": {}, "reduced": False},
    ],
)
def test_details_the_named_type_will_not_accept_are_refused(payload: dict[str, object]) -> None:
    """§10a: refused "closed, rather than raising a half-populated exception whose
    empty field a caller would read as 'no ids were unresolved'".

    A member the type does not take, and a missing member its constructor requires,
    fail the same way.
    """
    with pytest.raises(ProtocolError, match="constructor"):
        raise_from_payload(payload)


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        {"message": "x", "details": None, "reduced": False},
        {"code": 1, "message": "x", "details": None, "reduced": False},
        {"code": "MemoryStoreError", "message": "x", "details": 5, "reduced": False},
    ],
)
def test_a_malformed_error_payload_is_a_protocol_violation(payload: object) -> None:
    """Nothing about an error frame is inferred; a frame that is not one is refused."""
    with pytest.raises(ProtocolError):
        raise_from_payload(payload)

"""The reflected surface, and ADR-0173 §4's second adaptation rule.

``wire/surface.py`` reads the method set, the argument types and the result type off
:class:`~ai_assistant.core.protocols.AssistantEngine` rather than transcribing them,
"so a method the Protocol grows is a method this module already knows about". ADR-0173
§4 adds a *rule* to that reflection rather than an exception — "a method whose return
annotation is an async iterator is adapted by **one adapter per member of the yielded
union**, selected by the frame kind being decoded… No method is adapted by both
rules" — and what is checked here is that the rule really is derived and really is
exclusive.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ai_assistant.core.types import (
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EgressDestination,
    EgressSpan,
    ExecutionState,
    ReplyChunk,
    StepOutcome,
    TurnOutcome,
)
from ai_assistant.wire.codec import canonical_payload, project
from ai_assistant.wire.surface import (
    METHODS,
    STREAMING_METHODS,
    chunk_adapter,
    chunk_type,
    parameters,
    return_adapter,
    terminal_adapter,
)

_AT = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def test_the_streaming_set_is_read_off_the_protocol() -> None:
    """Derived rather than listed, which is what makes it total by construction.

    A second streaming method is one this module already knows about; a table here
    would be a second vocabulary to keep in step with the first, which is the
    objection the module opens with.
    """
    assert STREAMING_METHODS <= METHODS
    assert "converse_streaming" in STREAMING_METHODS
    assert "converse" not in STREAMING_METHODS


def test_a_streaming_method_takes_exactly_the_arguments_the_whole_one_takes() -> None:
    """§4: "exactly ``converse``'s arguments in exactly its shape".

    A wire-visible fact rather than a Python nicety: ``_decode_arguments`` refuses an
    argument a method does not declare, so a surface whose twin diverged by one name
    would fail on the first call rather than at the handshake.
    """
    assert parameters("converse_streaming") == parameters("converse")


def test_a_streaming_method_has_one_adapter_per_member_of_its_union() -> None:
    """§4's rule, both halves, selected by the frame kind rather than the payload."""
    assert chunk_adapter("converse_streaming").validate_python({"text": "half an"}) == ReplyChunk(
        text="half an"
    )
    assert chunk_type("converse_streaming") is ReplyChunk
    outcome = terminal_adapter("converse_streaming").validate_python({"turn": None})
    assert isinstance(outcome, TurnOutcome)


def test_no_method_is_adapted_by_both_rules() -> None:
    """§4 in terms, and the refusal is what keeps the two rules from overlapping.

    A single result adapter over an async-iterator annotation is a value nothing can
    validate, so returning one would be worse than refusing: the failure would
    surface as a decode error inside a call rather than as a build-time mistake.
    """
    with pytest.raises(KeyError):
        return_adapter("converse_streaming")
    for name in ("converse", "resume"):
        with pytest.raises(KeyError):
            chunk_adapter(name)
        with pytest.raises(KeyError):
            terminal_adapter(name)
        with pytest.raises(KeyError):
            chunk_type(name)


def test_a_non_streaming_method_keeps_its_single_result_adapter() -> None:
    """§4: "a non-streaming method keeps its single result adapter"."""
    outcome = return_adapter("converse").validate_python({"turn": None})
    assert isinstance(outcome, TurnOutcome)


def test_an_unknown_method_is_refused_by_every_adapter() -> None:
    """The reflection's existing contract, extended to the two new accessors."""
    for accessor in (return_adapter, chunk_adapter, terminal_adapter, chunk_type):
        with pytest.raises(KeyError):
            accessor("no_such_method")


# --- ADR-0178 §6: an egress confirmation crosses with every member intact ----


def test_an_egress_confirmation_survives_the_round_trip_a_client_actually_makes() -> None:
    """ADR-0178 §6: ``project`` -> canonical JSON -> ``return_adapter`` validation.

    The route a confirmation really takes to a client: the hub renders the result
    through :func:`~ai_assistant.wire.codec.project` and the canonical encoding,
    and the client validates the decoded payload against the method's **own
    declared return annotation** (ADR-0085 §10) — which is why the new member
    crosses without a second declaration and nothing under ``wire/`` transcribes
    it into a schema.

    ``tier`` of ``None`` and ``index`` of ``None`` are in the vector deliberately:
    both are optional on :class:`~ai_assistant.core.types.EgressSpan`, and an
    encoder that dropped an absent member rather than emitting ``null`` would
    round-trip them by accident here and lose the discrimination elsewhere.

    The derived canonical destination set is **not** in the frame, and this is
    where that is visible: ``ConfirmationDestination`` is the member type of a
    property, so no peer receives one and ``PROTOCOL_VERSION`` 10 does not
    describe it. The far side derives its own set from the occurrences it decoded,
    and the two cannot disagree because there is only one rule.
    """
    confirmation = Confirmation(
        tool_id="smtp",
        tool_description="Send an email.",
        parameters={"to": "Alice@Example.ORG", "body": "hello"},
        reason="this discloses data off-device",
        token=ContinuationToken(handle="tok"),
        egress=ConfirmationEgress(
            planned_with_external_content=False,
            account_identity="work@example.com",
            spans=(
                EgressSpan(
                    argument="body",
                    provenance=DiscloserProvenance.USER_AUTHORED,
                    extent=5,
                    tier=None,
                    destination=None,
                ),
                EgressSpan(
                    argument="to",
                    index=None,
                    provenance=DiscloserProvenance.SYSTEM_SELECTED,
                    extent=17,
                    tier=DataTier.PERSONAL,
                    destination=EgressDestination(
                        protocol=DestinationProtocol.SMTP,
                        supplied="Alice@Example.ORG",
                        canonical="alice@example.org",
                    ),
                ),
            ),
        ),
    )
    outcome = TurnOutcome(
        turn=None,
        step=StepOutcome(
            disposition=Disposition.AWAITING_CONFIRMATION,
            state=ExecutionState(id="e-1", plan_id="p-1", steps=(), updated_at=_AT),
            step_id="step-1",
            tool_id="smtp",
            confirmation=confirmation,
        ),
    )

    payload = json.loads(canonical_payload(project(outcome)))
    decoded = return_adapter("converse").validate_python(payload)

    assert decoded == outcome
    assert decoded.step is not None
    assert decoded.step.confirmation == confirmation
    # Present as ``null`` rather than omitted, which is what makes the bump bite:
    # a version 9 client fails ``extra_forbidden`` on this member.
    assert "egress" in payload["step"]["confirmation"]
    assert "canonical_destination_set" not in payload["step"]["confirmation"]["egress"]


def test_a_non_egress_confirmation_crosses_as_an_explicit_null() -> None:
    """ADR-0178 §6: ``project`` renders a model by ``model_dump()``, which keeps ``None``.

    So a version 10 hub emits ``"egress": null`` on **every** confirmation, egress
    or not — which is why ADR-0124 §9's second limb bites here rather than merely
    applying, and why no compatibility shim is offered for it.
    """
    confirmation = Confirmation(
        tool_id="notes",
        tool_description="Write a note.",
        parameters={},
        reason="an unknown cost",
        token=ContinuationToken(handle="tok"),
        egress=None,
    )
    payload = json.loads(canonical_payload(project(confirmation)))
    assert payload["egress"] is None
    assert return_adapter("pending_confirmations").validate_python([payload]) == (confirmation,)

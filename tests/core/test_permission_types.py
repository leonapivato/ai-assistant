"""The permission types in ``core`` (ADR-0021 §§1-3).

The Protocols' behaviour is pinned by the shared conformance suites under
``tests/permissions/``. This module covers what the *types* guarantee on their
own — the properties every implementation inherits without doing anything, and
which several of the ADR's security claims rest on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    CostBasis,
    DataTier,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def tool(tool_id: str = "smtp", **overrides: Any) -> ToolDefinition:
    """Build a valid definition, overriding whichever field a test is about."""
    fields: dict[str, Any] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)


# --- PermissionOutcome ------------------------------------------------------


def test_outcome_orders_by_restrictiveness() -> None:
    assert PermissionOutcome.ALLOW < PermissionOutcome.CONFIRM < PermissionOutcome.DENY
    assert PermissionOutcome.DENY >= PermissionOutcome.ALLOW


def test_outcome_refuses_to_be_compared_with_a_bare_string() -> None:
    """The behaviour reusing ``_SeverityScale`` was for.

    ``StrEnum`` members are strings, so declining would send Python to the
    reflected ``str`` comparison, which answers lexicographically — surviving in
    exactly the mixed-type case a policy reading a threshold from configuration
    produces.
    """
    with pytest.raises(TypeError):
        _ = PermissionOutcome.ALLOW < "deny"


def test_outcome_ranks_by_declaration_not_alphabet() -> None:
    """Today the two agree, which is why the scale is load-bearing rather than idle.

    ``"allow" < "confirm" < "deny"`` is correct alphabetically, so a plain
    ``StrEnum`` would appear to work until the first member inserted out of
    alphabetical order silently inverted every threshold written against it.
    """
    assert [outcome.severity for outcome in PermissionOutcome] == [0, 1, 2]


# --- ActionRequest.parameters_digest ---------------------------------------


def test_digest_is_stable_across_key_order() -> None:
    """Canonicalisation is the whole point: two orderings must not read as tampering."""
    one = ActionRequest(tool=tool(), parameters={"to": "a@example.com", "subject": "hi"})
    other = ActionRequest(tool=tool(), parameters={"subject": "hi", "to": "a@example.com"})

    assert one.parameters_digest == other.parameters_digest


def test_digest_is_stable_across_nested_key_order() -> None:
    """Sorting only the top level would leave a nested reordering looking like a change."""
    one = ActionRequest(tool=tool(), parameters={"headers": {"b": 2, "a": 1}})
    other = ActionRequest(tool=tool(), parameters={"headers": {"a": 1, "b": 2}})

    assert one.parameters_digest == other.parameters_digest


@pytest.mark.parametrize(
    "parameters",
    [
        {"to": "b@example.com"},
        {"to": "a@example.com", "cc": "c@example.com"},
        {"to": "a@example.com "},
        {"to": ["a@example.com"]},
    ],
    ids=["a different value", "an extra key", "trailing whitespace", "a list not a string"],
)
def test_digest_changes_when_the_payload_changes(parameters: dict[str, Any]) -> None:
    baseline = ActionRequest(tool=tool(), parameters={"to": "a@example.com"})

    assert ActionRequest(tool=tool(), parameters=parameters).parameters_digest != (
        baseline.parameters_digest
    )


def test_digest_does_not_depend_on_the_tool_or_the_step() -> None:
    """It binds the payload; the tool and step are compared as themselves."""
    one = ActionRequest(tool=tool("smtp"), parameters={"to": "a"}, step_id="step-1")
    other = ActionRequest(tool=tool("gmail"), parameters={"to": "a"}, step_id="step-2")

    assert one.parameters_digest == other.parameters_digest


def test_a_request_with_no_parameters_still_has_a_digest() -> None:
    assert ActionRequest(tool=tool()).parameters_digest == (
        ActionRequest(tool=tool(), parameters={}).parameters_digest
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {"body": "\ud800"},
        {"\ud800": "body"},
        {"nested": {"body": "\udfff"}},
        {"items": ["fine", "\ud800"]},
    ],
    ids=["a value", "a key", "nested in a mapping", "inside a sequence"],
)
def test_a_payload_with_no_utf8_encoding_is_refused(parameters: dict[str, Any]) -> None:
    """A lone surrogate is a ``str`` with no transportable form.

    The same rule ADR-0014 §2 applies to non-finite floats, one character-set
    down. Without it the payload validates and then ``parameters_digest`` raises
    ``UnicodeEncodeError``, so every decision about the request becomes
    unconstructable — a crash rather than a refusal, at the gate.
    """
    with pytest.raises(ValidationError, match="UTF-8"):
        ActionRequest(tool=tool(), parameters=parameters)


def test_an_astral_character_is_still_accepted() -> None:
    """Only *lone* surrogates are refused; a real supplementary character is fine.

    Worth pinning: a check written against the surrogate *range* rather than
    against encodability would reject emoji, which arrive in tool arguments
    routinely.
    """
    request = ActionRequest(tool=tool(), parameters={"body": "\U0001f389 done"})

    assert request.parameters_digest


def test_parameters_are_frozen_all_the_way_down() -> None:
    """Inherited from ``FrozenJsonMapping``, and relied on: a mutable payload would
    let the digest a decision pinned describe something the caller has since changed.
    """
    request = ActionRequest(tool=tool(), parameters={"headers": {"a": 1}})

    with pytest.raises(TypeError):
        request.parameters["headers"]["a"] = 2  # type: ignore[index]  # proving it refuses


# --- PermissionRuling -------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    ["", "   ", "\u200b\u200b", "\u2800", "\ufe0f"],
    ids=["empty", "whitespace", "zero-width spaces", "braille blank", "variation selector"],
)
def test_a_ruling_reason_must_render_as_something(reason: str) -> None:
    """It is shown to the user at the moment they decide (ADR-0018 §1's test)."""
    with pytest.raises(ValidationError, match="visible text"):
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason=reason)


def test_a_ruling_reason_is_stripped() -> None:
    assert PermissionRuling(outcome=PermissionOutcome.DENY, reason="  no  ").reason == "no"


@pytest.mark.parametrize("outcome", [PermissionOutcome.CONFIRM, PermissionOutcome.DENY])
def test_only_an_allow_may_cite_an_authorisation(outcome: PermissionOutcome) -> None:
    """A refusal rests on no authorisation, and a question is not an answer."""
    with pytest.raises(ValidationError, match="authorisation"):
        PermissionRuling(outcome=outcome, reason="because", authorised_by="d-1")


def test_an_allow_may_cite_an_authorisation() -> None:
    ruling = PermissionRuling(
        outcome=PermissionOutcome.ALLOW, reason="the user approved", authorised_by="d-1"
    )

    assert ruling.authorised_by == "d-1"


def test_a_ruling_has_no_field_naming_a_subject() -> None:
    """The security property of splitting the ruling from the decision.

    A policy returning a whole ``PermissionDecision`` could have ruled ``ALLOW``
    for a *different* tool than the one it was handed. A ruling has nowhere to
    put one, which is true of every implementation including one written by
    someone who never read the ADR.
    """
    assert set(PermissionRuling.model_fields) == {"outcome", "reason", "authorised_by"}


# --- PermissionDecision -----------------------------------------------------


def test_from_request_transcribes_the_subject() -> None:
    """The caller supplies the id, the clock and the ruling; ``core`` copies the rest."""
    request = ActionRequest(tool=tool(), parameters={"to": "a"}, step_id="step-1")
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine")

    made = PermissionDecision.from_request(request, ruling, id="d-1", decided_at=AT)

    assert made.tool == request.tool
    assert made.parameters_digest == request.parameters_digest
    assert made.step_id == request.step_id
    assert made.id == "d-1"
    assert made.decided_at == AT
    assert made.resolves is None


def test_a_decision_embeds_the_definition_by_value_not_by_reference() -> None:
    """The clause that closes issue #54's permissions half.

    A process that restarts and registers a different definition under the same
    id has not altered any decision — there is no name left to rebind.
    """
    made = PermissionDecision.from_request(
        ActionRequest(tool=tool(risk_level=RiskLevel.CRITICAL)),
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="risky"),
        id="d-1",
        decided_at=AT,
    )

    assert made.tool.risk_level is RiskLevel.CRITICAL
    assert made.tool.id == "smtp"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda request, ruling: object.__setattr__(request.tool, "risk_level", RiskLevel.CRITICAL),
        lambda request, ruling: object.__setattr__(request.tool, "id", "something-else"),
        lambda request, ruling: object.__setattr__(request.tool.cost, "basis", CostBasis.UNKNOWN),
        lambda request, ruling: object.__setattr__(ruling, "outcome", PermissionOutcome.ALLOW),
        lambda request, ruling: object.__setattr__(ruling, "reason", "rewritten"),
    ],
    ids=["the risk level", "the tool id", "the nested cost", "the outcome", "the reason"],
)
def test_a_decision_is_detached_from_the_request_it_was_built_from(
    tamper: Any,
) -> None:
    """ "By value" has to mean a copy, or the pin moves with what it pinned.

    Pydantic passes an already-valid model instance through without copying, so
    a decision built from a request would otherwise hold the *same*
    `ToolDefinition` object — and `frozen=True` stops `x.risk_level = ...` but
    not `x.__dict__["risk_level"] = ...`. Both sides would then move together
    and `authorises` would go on answering `True`, which is the substitution
    ADR-0021 §1 exists to make detectable.
    """
    request = ActionRequest(tool=tool(), parameters={"to": "a"}, step_id="step-1")
    ruling = PermissionRuling(outcome=PermissionOutcome.DENY, reason="no")
    made = PermissionDecision.from_request(request, ruling, id="d-1", decided_at=AT)
    before = made.model_dump(mode="json")

    tamper(request, ruling)

    assert made.model_dump(mode="json") == before


def test_a_substituted_definition_stops_a_decision_authorising_the_request() -> None:
    """The detachment above is what turns tampering into a refusal.

    The decision keeps the declaration the policy actually ruled on, so a
    request whose tool has since been rewritten no longer matches it.
    """
    request = ActionRequest(tool=tool(), parameters={"to": "a"}, step_id="step-1")
    made = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="d-1",
        decided_at=AT,
    )
    assert made.authorises(request)

    object.__setattr__(request.tool, "risk_level", RiskLevel.CRITICAL)

    assert not made.authorises(request)


def test_a_decision_authorises_the_request_it_was_made_about() -> None:
    request = ActionRequest(tool=tool(), parameters={"to": "a"}, step_id="step-1")
    made = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="d-1",
        decided_at=AT,
    )

    assert made.authorises(request)


@pytest.mark.parametrize(
    "substituted",
    [
        ActionRequest(tool=tool("gmail"), parameters={"to": "a"}, step_id="step-1"),
        ActionRequest(
            tool=tool(risk_level=RiskLevel.CRITICAL), parameters={"to": "a"}, step_id="step-1"
        ),
        ActionRequest(
            tool=tool(discloses=(DataTier.SECRET,)), parameters={"to": "a"}, step_id="step-1"
        ),
        ActionRequest(tool=tool(), parameters={"to": "b"}, step_id="step-1"),
        ActionRequest(tool=tool(), parameters={"to": "a"}, step_id="step-2"),
        ActionRequest(tool=tool(), parameters={"to": "a"}),
    ],
    ids=[
        "a rebound id",
        "a tampered risk level",
        "a widened disclosure",
        "different arguments",
        "another step",
        "no step at all",
    ],
)
def test_a_decision_does_not_authorise_a_substituted_request(substituted: ActionRequest) -> None:
    """Three substitutions closed by the shape of the types rather than by prose.

    Taking the *request* is what makes this discharge ADR-0017 §3: a signature
    taking only a definition would have checked the tool and silently ignored
    the arguments — authorising an email to one recipient and executing it to
    another, with every record still reading as consistent.
    """
    approved = ActionRequest(tool=tool(), parameters={"to": "a"}, step_id="step-1")
    made = PermissionDecision.from_request(
        approved,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="d-1",
        decided_at=AT,
    )

    assert not made.authorises(substituted)


@pytest.mark.parametrize("outcome", [PermissionOutcome.CONFIRM, PermissionOutcome.DENY])
def test_only_an_allow_authorises_anything(outcome: PermissionOutcome) -> None:
    request = ActionRequest(tool=tool())
    made = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=outcome, reason="not yet"),
        id="d-1",
        decided_at=AT,
    )

    assert not made.authorises(request)


def test_a_naive_decision_timestamp_is_refused() -> None:
    """Rejected rather than assumed UTC, unlike the other instants in ``core``.

    The trail is durable *and ordered*, so a naive value is reinterpreted
    against whatever the host's local zone happens to be at read time and sorts
    incoherently against the aware values beside it.
    """
    with pytest.raises(ValidationError, match="timezone-aware"):
        PermissionDecision.from_request(
            ActionRequest(tool=tool()),
            PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
            id="d-1",
            decided_at=datetime(2026, 7, 20, 12, 0),  # noqa: DTZ001 — a naive value is the subject
        )


def test_a_non_utc_timestamp_is_kept_as_given() -> None:
    """Aware is the requirement; the offset is preserved rather than normalised.

    Ordering is by instant, so two zones compare correctly without rewriting
    what the recorder actually observed.
    """
    elsewhere = datetime(2026, 7, 20, 14, 0, tzinfo=timezone(timedelta(hours=2)))

    made = PermissionDecision.from_request(
        ActionRequest(tool=tool()),
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="d-1",
        decided_at=elsewhere,
    )

    assert made.decided_at == elsewhere
    assert made.decided_at == AT


def test_a_resolving_decision_may_not_itself_be_a_confirmation() -> None:
    """Keeps the chain one link long, so it cannot loop."""
    with pytest.raises(ValidationError, match="resolving decision"):
        PermissionDecision.from_request(
            ActionRequest(tool=tool()),
            PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="again?"),
            id="d-2",
            decided_at=AT,
            resolves="d-1",
        )


def test_a_decision_survives_a_json_round_trip_with_its_definition_intact() -> None:
    """Durability is what forces this, and the pin is worthless without it."""
    request = ActionRequest(
        tool=tool(
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.5"), currency="USD"),
            idempotency=Idempotency.KEYED,
            idempotency_window=timedelta(hours=1),
            discloses=(DataTier.PERSONAL, DataTier.OPERATIONAL),
        ),
        parameters={"to": "a@example.com", "attachments": [{"name": "x"}]},
        step_id="step-1",
    )
    made = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine", authorised_by="d-0"),
        id="d-1",
        decided_at=AT,
    )

    reloaded = PermissionDecision.model_validate(made.model_dump(mode="json"))

    assert reloaded == made
    assert reloaded.authorises(request)


def test_a_decision_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PermissionDecision.model_validate(
            {
                "id": "d-1",
                "ruling": {"outcome": "allow", "reason": "fine"},
                "tool": tool().model_dump(mode="json"),
                "parameters_digest": "x",
                "decided_at": AT.isoformat(),
                "surprise": True,
            }
        )

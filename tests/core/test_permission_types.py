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
from zoneinfo import ZoneInfo

import pytest
from pydantic import ConfigDict, ValidationError

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
    with pytest.raises(ValidationError, match="canonical JSON encoding"):
        ActionRequest(tool=tool(), parameters=parameters)


@pytest.mark.parametrize(
    "parameters",
    [{"n": 10**5000}, {"nested": {"n": -(10**5000)}}, {"items": [10**5000]}],
    ids=["a value", "nested in a mapping", "inside a sequence"],
)
def test_a_payload_with_an_unrenderable_integer_is_refused(
    parameters: dict[str, Any],
) -> None:
    """The same class as the surrogate, reached through a different type.

    ``json.dumps`` renders an ``int`` through ``str()``, and CPython refuses
    that past its integer-string conversion limit — so a payload the model
    accepted would raise ``ValueError`` at digest time. Caught because
    validation runs the real encoder rather than enumerating the types that can
    fail; an enumeration is a list someone has to keep complete, and this is the
    case a first attempt at one missed.
    """
    with pytest.raises(ValidationError, match="canonical JSON encoding"):
        ActionRequest(tool=tool(), parameters=parameters)


def test_a_large_but_renderable_integer_is_accepted() -> None:
    """The bound is "can it be encoded", not "is it big"."""
    assert ActionRequest(tool=tool(), parameters={"n": 10**100}).parameters_digest


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


def test_a_ruling_reason_with_no_utf8_encoding_is_refused() -> None:
    r"""Visible text is not the only thing a reason has to be.

    ``_has_visible_text`` sees the ordinary letters in ``"approve \ud800"`` and
    passes it, but the reason is carried into a durable record ADR-0021 §4
    requires to survive serialisation — so an unpaired surrogate beside real
    text would fail at the write rather than at the gate.
    """
    with pytest.raises(ValidationError, match="UTF-8"):
        PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="approve \ud800")


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


def test_a_request_is_detached_from_the_definition_it_was_built_from() -> None:
    """The window between `decide()` returning and `from_request()` being called.

    A caller holds the `ToolDefinition` it built the request from. If the
    request shared it, mutating that original after the policy had ruled would
    change what the request is *about*, and `from_request` would transcribe the
    mutated version faithfully — recording that the policy approved a
    declaration it never saw.
    """
    declared = tool()
    request = ActionRequest(tool=declared, step_id="step-1")

    object.__setattr__(declared, "risk_level", RiskLevel.CRITICAL)
    object.__setattr__(declared.cost, "basis", CostBasis.UNKNOWN)

    assert request.tool.risk_level is RiskLevel.LOW
    assert request.tool.cost.basis is CostBasis.FREE


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


def test_an_aware_timestamp_is_normalised_to_utc() -> None:
    """The instant is preserved; the offset it was expressed in is not.

    Normalising is what makes ``decided_at`` orderable by *instant*. Python
    compares two aware datetimes sharing a ``tzinfo`` by wall clock, ignoring
    ``fold``, so leaving mixed zones in the field would misorder a DST repeated
    hour — see the fold test below.
    """
    elsewhere = datetime(2026, 7, 20, 14, 0, tzinfo=timezone(timedelta(hours=2)))

    made = PermissionDecision.from_request(
        ActionRequest(tool=tool()),
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="d-1",
        decided_at=elsewhere,
    )

    assert made.decided_at == elsewhere  # the same instant
    assert made.decided_at == AT
    assert made.decided_at.tzinfo is UTC


@pytest.mark.parametrize(
    "boundary",
    [
        datetime.min.replace(tzinfo=timezone(timedelta(hours=14))),
        datetime.max.replace(tzinfo=timezone(timedelta(hours=-12))),
    ],
    ids=["under year 1", "over year 9999"],
)
def test_a_timestamp_with_no_utc_representation_is_refused(boundary: datetime) -> None:
    """Aware is necessary and not sufficient: normalising it must also work.

    A datetime within a day of `datetime.min`/`max` at a large offset carries a
    `tzinfo` and still has no UTC form. `astimezone` raises `OverflowError`,
    which is not a `ValueError`, so without translation pydantic lets it escape
    as a crash rather than a validation failure — accepted at the type and
    unusable after it, the shape the payload rules close at the other end.
    """
    with pytest.raises(ValidationError, match="UTC representation"):
        PermissionDecision.from_request(
            ActionRequest(tool=tool()),
            PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
            id="d-1",
            decided_at=boundary,
        )


def test_a_dst_repeated_hour_orders_by_instant_not_wall_clock() -> None:
    """The trap normalisation exists to close.

    ``01:15 fold=1`` is EST and ``01:45 fold=0`` is EDT, so the first is the
    *later* instant — but compared as stored aware values sharing a ``tzinfo``
    Python reads only the wall clock and calls it earlier. In an audit trail
    that is an answer timestamped before its own question, once a year.
    """
    ny = ZoneInfo("America/New_York")
    question = datetime(2026, 11, 1, 1, 15, tzinfo=ny, fold=1)
    answer = datetime(2026, 11, 1, 1, 45, tzinfo=ny, fold=0)
    assert answer > question, "wall-clock comparison disagrees with the instants"

    asked, answered = (
        PermissionDecision.from_request(
            ActionRequest(tool=tool()),
            PermissionRuling(outcome=PermissionOutcome.CONFIRM, reason="?"),
            id="d",
            decided_at=when,
        ).decided_at
        for when in (question, answer)
    )

    assert answered < asked


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


@pytest.mark.parametrize("field", ["id", "step_id", "resolves"])
def test_a_decision_identifier_with_no_utf8_encoding_is_refused(field: str) -> None:
    """The last field family that could break the round-trip guarantee.

    ADR-0021 §4 requires a recorded decision to reload, so every field has to
    survive serialisation — not just the payload and the reason. `Identifier`
    only strips and refuses a blank, so a lone surrogate reaches the store.
    """
    bad = "d-" + chr(0xD800)
    fields: dict[str, Any] = {"id": "d-1", "resolves": None}
    request = ActionRequest(tool=tool(), step_id="step-1")
    if field == "step_id":
        with pytest.raises(ValidationError, match="UTF-8"):
            ActionRequest(tool=tool(), step_id=bad)
        return
    fields[field] = bad

    with pytest.raises(ValidationError, match="UTF-8"):
        PermissionDecision.from_request(
            request,
            PermissionRuling(outcome=PermissionOutcome.DENY, reason="no"),
            id=fields["id"],
            decided_at=AT,
            resolves=fields["resolves"],
        )


def _unstorable_tool(**overrides: Any) -> ToolDefinition:
    r"""A definition holding a lone surrogate, built past the type's own guard.

    ``ToolDefinition`` refuses one at construction since issue #156, so the only
    way to obtain such a value is the ``object.__setattr__`` bypass ADR-0018 §3
    and ADR-0021 §4 keep inside this repository's threat model. That is exactly
    the input these boundary tests need: it lets them pin the *permissions*
    boundary's refusal (PR #119) on its own, rather than passing because the
    definition could never be built in the first place.
    """
    definition = tool()
    for field, value in overrides.items():
        object.__setattr__(definition, field, value)
    return definition


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"description": "Send \ud800 mail."}, id="description"),
        pytest.param({"capability": "send_\ud800"}, id="capability"),
        pytest.param({"parameters_schema": {"to": "\ud800"}}, id="schema-value"),
        pytest.param({"parameters_schema": {"\ud800": "string"}}, id="schema-key"),
    ],
)
def test_a_request_whose_definition_has_no_utf8_encoding_is_refused(
    override: dict[str, Any],
) -> None:
    """The embedded declaration is stored too, so it has to survive the trip.

    ADR-0016 §6 keeps the registry in memory, so nothing ever forced a
    definition to be serialisable; ADR-0021 §4 makes the trail the first durable
    holder of one. A lone surrogate anywhere the definition reaches would be
    accepted here and fail at the store — the round-trip guarantee broken
    through the one field a decision copies verbatim rather than authors.

    Stronger than the version PR #119 shipped: the definition is tampered past
    ``frozen=True`` rather than honestly constructed, so this still exercises
    *this* boundary now that ``ToolDefinition`` itself would have refused an
    honestly built one first.
    """
    with pytest.raises(ValidationError, match="JSON encoding"):
        ActionRequest(tool=_unstorable_tool(**override))


def test_a_hand_built_decision_with_an_unencodable_definition_is_refused() -> None:
    """The request is not the only construction path, so the decision checks too.

    ADR-0021 §1 leaves hand construction open — it is a caller falsifying its own
    trail, not a policy subverting a gate — but an unstorable record is a
    different failure from a false one, and it is the store that would break.

    A ``PermissionDecision`` receives an already-built ``ToolDefinition``, which
    pydantic passes through without re-running its *field* validators. This is
    the test that proves the refusal survives issue #156 dropping this field's
    own ``_durable_tool`` annotation: what catches it now is the type's ``after``
    model validator, which pydantic *does* re-run on an instance.
    """
    with pytest.raises(ValidationError, match="JSON encoding"):
        PermissionDecision(
            id="d-1",
            ruling=PermissionRuling(outcome=PermissionOutcome.DENY, reason="no"),
            tool=_unstorable_tool(description="Send \ud800 mail."),
            parameters_digest="0" * 64,
            decided_at=AT,
        )


def test_a_decision_transcribed_from_a_tampered_request_is_refused() -> None:
    """The factory path, not only the hand-built one.

    ``from_request`` deep-copies the request's definition, and a deep copy of an
    unstorable value is still unstorable — so the refusal has to happen when the
    copy lands on the field, not when the copy was made.
    """
    request = ActionRequest(tool=tool())
    object.__setattr__(request.tool, "parameters_schema", {"to": "\ud800"})

    with pytest.raises(ValidationError, match="JSON encoding"):
        PermissionDecision.from_request(
            request,
            PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
            id="d-1",
            decided_at=AT,
        )


def test_an_authorisation_pointer_with_no_utf8_encoding_is_refused() -> None:
    """`authorised_by` is stored beside the rest and binds the disclosure floor."""
    with pytest.raises(ValidationError, match="UTF-8"):
        PermissionRuling(
            outcome=PermissionOutcome.ALLOW, reason="ok", authorised_by="d-" + chr(0xD800)
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


@pytest.mark.parametrize(
    "digest",
    ["", "x", "abc", "A" * 64, "g" * 64, "0" * 63, "0" * 65, "0" * 63 + chr(0xD800)],
    ids=[
        "empty",
        "too short",
        "not a digest",
        "uppercase",
        "not hex",
        "one short",
        "one long",
        "an unencodable character",
    ],
)
def test_a_decision_rejects_a_digest_that_is_not_one(digest: str) -> None:
    """The last field of a decision that could break the reload guarantee.

    `from_request` always fills it correctly, but the field is a plain string,
    so a hand-built decision could carry anything — including text with no UTF-8
    encoding, which would make the record unserialisable. Uppercase is rejected
    too: `hexdigest()` emits lowercase, so admitting a second spelling of the
    same digest would compare unequal and read as tampering.
    """
    with pytest.raises(ValidationError, match="parameters_digest"):
        PermissionDecision(
            id="d-1",
            ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
            tool=tool(),
            parameters_digest=digest,
            decided_at=AT,
        )


def test_a_request_refuses_a_definition_subclass_carrying_extra_fields() -> None:
    """A subclass would be flattened on the way into the record, and diverge.

    `PermissionDecision.tool` is declared as `ToolDefinition`, so dumping it
    serialises the base schema and drops a subclass's extra fields. The trail
    would reload a definition no longer equal to the one approved, and
    `authorises` would answer `False` for the very request it was made about —
    after a restart, which is exactly when issue #54's failure bites. Refused at
    construction instead.
    """

    class TenantScopedTool(ToolDefinition):
        tenant: str

        model_config = ConfigDict(extra="forbid", frozen=True)

    extended = TenantScopedTool(**tool().model_dump(), tenant="acme")

    with pytest.raises(ValidationError):
        ActionRequest(tool=extended)


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings:UserWarning")
def test_a_request_rebuilds_a_corrupted_definition_rather_than_carrying_it() -> None:
    """A policy should be able to trust the declaration it is handed.

    `frozen=True` refuses `tool.risk_level = ...` and not
    `object.__setattr__`, so a corrupted definition could otherwise reach a
    policy — which compares that field on a severity scale and would raise
    `TypeError` mid-decision, from inside the gate.

    The serializer warning is expected and filtered: dumping the deliberately
    corrupted model is how the rebuild detects it, and the warning is the
    mechanism working rather than a problem with the test.
    """
    corrupted = tool()
    object.__setattr__(corrupted, "risk_level", "garbage")

    with pytest.raises(ValidationError):
        ActionRequest(tool=corrupted)


def test_a_decision_refuses_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PermissionDecision.model_validate(
            {
                "id": "d-1",
                "ruling": {"outcome": "allow", "reason": "fine"},
                "tool": tool().model_dump(mode="json"),
                "parameters_digest": ActionRequest(tool=tool()).parameters_digest,
                "decided_at": AT.isoformat(),
                "surprise": True,
            }
        )

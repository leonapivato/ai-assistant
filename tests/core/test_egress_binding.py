"""ADR-0150's egress binding: surface (a) of ADR-0148 §11, from the `core` side.

Most of these pin a **refusal at construction**, and that is the decision rather
than a testing style. ADR-0150 §8 makes every value in this surface a validating
pydantic model precisely so that the class of finding issue #1122 records — a
caller reaching a function with values its annotations forbid — stops being
something a seam checks and starts being something the type refuses. So the
evidence is that an ill-formed span, destination or binding cannot be built, not
that something raised later when it was used.

**What is deliberately absent, because ADR-0150 assigns it elsewhere.** §4's
mixed-provenance and cardinality clauses are *builder* refusals — a component
holding two provenances, or two recipients, inside one undecomposable value
refuses rather than describing it — and §12 ships their tests with surface (b)'s
lane. `core` cannot see inside such a value and holds one provenance and at most
one destination per span by construction; the type-level half is pinned below and
the rest is (b)'s. So is §3's forged-canonical correspondence check, §11's
omitted-destination refusal, and the `SMTP` canonicaliser's own equivalence and
refusal cases (§12), each for the reason ADR-0150 gives: the fact that would
trigger the check lives in a declaration `core` does not read.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from inspect import signature
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.logging import redact_sensitive
from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CanonicalDestination,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_AT = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
_FREE = ToolCost(basis=CostBasis.FREE)

_ENDPOINT = "smtp://mail.example.com:587"

# The strings this module proves never reach a message, a rendering or a log.
# The first two are ADR-0145 §8's own fixtures for the leak it closes, reused
# here because ADR-0150 §8 states the same rule one surface further in; the last
# two are what this surface adds — a recipient address and an account identity.
_ARGUMENT_VALUE = "alice@example.com"
_ARGUMENT_KEY = "X-Secret"
_RECIPIENT = "Alice@Example.com"
_IDENTITY = "alice's work mail"

_SECRETS = (_ARGUMENT_VALUE, _ARGUMENT_KEY, _RECIPIENT, _IDENTITY)

_ACCOUNT = BoundAccount(identity=_IDENTITY, reference="connection-1")
_REPROVISIONED = BoundAccount(identity=_IDENTITY, reference="connection-2")
_RENAMED = BoundAccount(identity="alice's personal mail", reference="connection-1")


def _definition(**overrides: object) -> ToolDefinition:
    """A valid, schemaless declaration with ``overrides`` applied.

    Schemaless deliberately: ADR-0145 §9 admits an empty schema over a parameter
    mapping with keys, so every argument shape below reaches ADR-0150's validator
    rather than being refused one stage earlier for an unrelated reason.
    """
    fields: dict[str, object] = {
        "id": "smtp",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (DataTier.PERSONAL,),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": _FREE,
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _destination(supplied: str, canonical: str | None = None) -> EgressDestination:
    """One occurrence, canonicalised the way ADR-0150 §3 says ``SMTP`` does."""
    if canonical is None:
        local, _, domain = supplied.rpartition("@")
        canonical = f"{local}@{domain.lower()}"
    return EgressDestination(
        protocol=DestinationProtocol.SMTP, supplied=supplied, canonical=canonical
    )


def _span(argument: str, **overrides: object) -> EgressSpan:
    """A span with a stated provenance and an extent the caller must mean."""
    fields: dict[str, object] = {
        "argument": argument,
        "provenance": DiscloserProvenance.SYSTEM_SELECTED,
        "extent": 0,
    }
    fields.update(overrides)
    return EgressSpan(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _binding(*spans: EgressSpan, account: BoundAccount = _ACCOUNT) -> EgressBinding:
    """A binding over ``spans``, bound to ``account`` and one endpoint."""
    return EgressBinding(spans=spans, account=account, transport_endpoint=_ENDPOINT)


def _request(
    parameters: Mapping[str, Any] | None = None,
    binding: EgressBinding | None = None,
    **overrides: object,
) -> ActionRequest:
    """A request over ``parameters``, carrying ``binding`` where one is given."""
    fields: dict[str, object] = {
        "tool": _definition(),
        "parameters": {} if parameters is None else parameters,
        "egress_binding": binding,
    }
    fields.update(overrides)
    return ActionRequest(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _allow() -> PermissionRuling:
    """The ruling every authorisation case below is taken over."""
    return PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine")


def _decide(request: ActionRequest, **overrides: object) -> PermissionDecision:
    """Record an ``ALLOW`` about ``request`` through the only construction path."""
    fields: dict[str, object] = {"id": "decision-1", "decided_at": _AT}
    fields.update(overrides)
    return PermissionDecision.from_request(request, _allow(), **fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _one_body_binding() -> EgressBinding:
    """The smallest well-formed binding: one described, undestined span."""
    return _binding(_span("body", extent=2, provenance=DiscloserProvenance.USER_AUTHORED))


# --- §1: one field, defaulting to None, changing behaviour for nothing -------


def test_a_request_and_a_decision_carrying_no_binding_compare_exactly_as_before() -> None:
    """§12's regression pin: the ``None`` default is demonstrated, not asserted.

    ADR-0150 §1 rests the whole "breaking surface, unchanged behaviour" claim on
    ``None == None`` being ``True``, and §12 requires that to be a test rather
    than a sentence. Every request and decision in the tree today carries no
    binding, so this is the path everything existing takes.
    """
    request = _request({"n": 1})
    decision = _decide(request)

    assert request.egress_binding is None
    assert decision.egress_binding is None
    assert decision.authorises(request)
    assert decision.authorises(_request({"n": 1}))
    assert not decision.authorises(_request({"n": 2}))


def test_a_request_carries_exactly_one_field_for_the_binding() -> None:
    """§1's "one value, not several fields", stated over the models themselves.

    Four independent optional fields would admit fifteen partial states, of which
    fourteen are the shape ADR-0148 §8's third floor exists to refuse. One field
    means the state does not exist to be ruled on.
    """
    binding_fields = {
        name
        for name in (*ActionRequest.model_fields, *PermissionDecision.model_fields)
        if "egress" in name or "destination" in name or "span" in name
    }
    assert binding_fields == {"egress_binding"}


# --- §8: validating models, and no message renders a value -------------------


@pytest.mark.parametrize(
    "model",
    [EgressBinding, EgressSpan, EgressDestination, CanonicalDestination, BoundAccount],
    ids=lambda model: model.__name__,
)
def test_every_value_in_this_surface_is_a_frozen_validating_model(
    model: type[BaseModel],
) -> None:
    """§8's first two clauses, over the whole surface rather than model by model.

    ``hide_input_in_errors`` is **per model** in pydantic, so setting it on the
    outer value and not the inner ones would be the leak wearing the fix's
    clothes: a nested model that omits it appends ``input_value=`` to its own
    errors, and the value it would append is a recipient address.
    """
    assert issubclass(model, BaseModel)
    assert model.model_config.get("frozen") is True
    assert model.model_config.get("extra") == "forbid"
    assert model.model_config.get("hide_input_in_errors") is True


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda: EgressDestination(
                protocol=DestinationProtocol.SMTP, supplied=_RECIPIENT, canonical="\u200b"
            ),
            id="destination-with-an-invisible-canonical-form",
        ),
        pytest.param(
            lambda: CanonicalDestination(
                protocol=DestinationProtocol.SMTP, canonical=_RECIPIENT, account=_ACCOUNT
            ),
            id="member-carrying-all-three-fields",
        ),
        pytest.param(
            lambda: BoundAccount(identity="\u200b", reference="connection-1"),
            id="account-with-an-invisible-identity",
        ),
        pytest.param(
            lambda: _binding(
                _span("to", extent=17, destination=_destination(_RECIPIENT)),
                _span("to", extent=17, destination=_destination(_RECIPIENT)),
            ),
            id="binding-describing-one-span-twice",
        ),
        pytest.param(
            lambda: _request(
                {"n": _ARGUMENT_VALUE, _ARGUMENT_KEY: "x"},
                _binding(_span("n", extent=len(_ARGUMENT_VALUE))),
            ),
            id="request-whose-binding-leaves-a-caller-chosen-key-undescribed",
        ),
    ],
)
def test_no_refusal_in_this_surface_renders_a_value_or_a_key(build: Any) -> None:
    """§8's second clause, in the shape ``test_parameter_schema.py`` established.

    A refusal message reaches a log, so an address, an identity or a caller-chosen
    key surviving into one is a Tier 1 disclosure on the error path. This module
    goes one step beyond what §8 requires and names **no argument name** either:
    §8 permits it, but ADR-0150 §13's residue records that a caller — or a model
    composing the call — can put content of its own choosing into a key, and
    `core` cannot tell an author's key from a caller's.
    """
    with pytest.raises(ValidationError) as raised:
        build()

    rendered = str(raised.value)
    logged = repr(
        dict(redact_sensitive(None, "error", {"event": "binding refused", "detail": rendered}))
    )
    for secret in _SECRETS:
        assert secret not in rendered
        assert secret not in logged


def test_a_binding_survives_a_json_round_trip_as_an_equal_value() -> None:
    """§12's round-trip case, and §8's serialisability clause behind it.

    A binding that could not be read back would make the decision that carries it
    worthless across exactly the restart ADR-0021 §1 and issue #54 are about.
    """
    binding = _binding(
        _span("body", extent=2, provenance=DiscloserProvenance.USER_AUTHORED),
        _span(
            "to",
            index=0,
            extent=17,
            tier=DataTier.PERSONAL,
            destination=_destination(_RECIPIENT),
        ),
    )
    dumped = binding.model_dump(mode="json")

    assert json.loads(json.dumps(dumped)) == dumped
    assert EgressBinding.model_validate(dumped) == binding


# --- §3: the canonical destination set is derived, and has two member shapes --


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(
            {"protocol": DestinationProtocol.SMTP, "canonical": "a@b.example", "account": _ACCOUNT},
            id="all-three",
        ),
        pytest.param(
            {"protocol": DestinationProtocol.SMTP, "account": _ACCOUNT}, id="account-and-protocol"
        ),
        pytest.param({"canonical": "a@b.example", "account": _ACCOUNT}, id="account-and-form"),
        pytest.param({"protocol": DestinationProtocol.SMTP}, id="protocol-and-no-form"),
        pytest.param({"canonical": "a@b.example"}, id="form-and-no-protocol"),
        pytest.param({}, id="none-of-the-three"),
    ],
)
def test_every_ill_formed_canonical_destination_is_refused(fields: Mapping[str, Any]) -> None:
    """§12's clause: every shape §3's two-shape rule excludes, one case each.

    "A test exercising only the two well-formed shapes satisfies none of these."
    """
    with pytest.raises(ValidationError):
        CanonicalDestination(**fields)


def test_the_two_well_formed_canonical_destination_shapes_construct() -> None:
    """The positive half, so the refusals above discriminate rather than blanket."""
    recipient = CanonicalDestination(
        protocol=DestinationProtocol.SMTP, canonical="alice@example.com"
    )
    account = CanonicalDestination(account=_ACCOUNT)

    assert recipient.account is None
    assert account.protocol is None
    assert recipient != account


def test_an_alias_pair_is_two_occurrences_and_one_member() -> None:
    """§12's alias pair, at the `core` level.

    Two supplied forms differing only in domain case are **one** member of the
    derived set and **two** occurrences, with both supplied forms surviving on the
    binding. ADR-0148 §14 names reconstruction of a supplied form from a canonical
    one as a failure in terms, which is why the occurrences are what is stored.
    """
    binding = _binding(
        _span("cc", index=0, extent=17, destination=_destination("alice@example.com")),
        _span("to", index=0, extent=17, destination=_destination("alice@Example.com")),
    )

    assert binding.canonical_destination_set == (
        CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical="alice@example.com"),
    )
    supplied = {span.destination.supplied for span in binding.spans if span.destination}
    assert supplied == {"alice@example.com", "alice@Example.com"}


def test_one_supplied_form_canonicalised_two_ways_is_refused_at_construction() -> None:
    """§12's disagreeing-derivation case, at :class:`EgressBinding`'s constructor.

    A canonicaliser is a function of the supplied form, so two occurrences sharing
    a protocol and a supplied form and differing in their canonical form are two
    derivations of one form disagreeing. "A case whose two occurrences differ in
    their supplied forms as well demonstrates nothing", which is why the alias
    case above is a separate, *accepted* one.
    """
    with pytest.raises(ValidationError) as raised:
        _binding(
            _span("cc", index=0, extent=17, destination=_destination(_RECIPIENT)),
            _span(
                "to",
                index=0,
                extent=17,
                destination=_destination(_RECIPIENT, canonical="mallory@example.com"),
            ),
        )

    assert "canonicalised two ways" in str(raised.value)


def test_the_derived_set_is_totally_ordered_and_deduplicated() -> None:
    """§3's total order, which is what makes the derived property single-valued.

    A decision read back from the record rebuilds the occurrences and recomputes
    an *identical* tuple only if the order and the deduplication are fixed. Two
    spans naming one recipient collapse; the rest sort by canonical form, compared
    by Unicode code point.
    """
    binding = _binding(
        _span("to", index=0, extent=15, destination=_destination("zoe@example.com")),
        _span("to", index=1, extent=17, destination=_destination("alice@example.com")),
        _span("to", index=2, extent=17, destination=_destination("alice@example.com")),
    )

    assert [member.canonical for member in binding.canonical_destination_set] == [
        "alice@example.com",
        "zoe@example.com",
    ]


def test_a_binding_whose_spans_carry_no_destination_derives_the_account_alone() -> None:
    """§12's account-only case, which ADR-0149 made expressible at all.

    ADR-0148 §2's third clause: a call whose arguments select no recipient has the
    connected account as its canonical destination set. The set is therefore never
    empty, and no policy refuses on ADR-0148 §8's third floor for this shape.
    """
    binding = _one_body_binding()
    member = CanonicalDestination(account=_ACCOUNT)

    assert binding.canonical_destination_set == (member,)
    assert member != CanonicalDestination(
        protocol=DestinationProtocol.SMTP, canonical="alice@example.com"
    )


@pytest.mark.parametrize(
    "other",
    [pytest.param(_REPROVISIONED, id="same-identity"), pytest.param(_RENAMED, id="same-reference")],
)
def test_two_accounts_agreeing_on_one_fact_derive_unequal_sets(other: BoundAccount) -> None:
    """§12's account-member pair, both directions.

    An implementation whose account member held one of the two facts passes one of
    these and fails the other. Two connectable records can hold one identity, and
    a reference survives its own re-provisioning to a different account — so
    either alone is a destination two different accounts satisfy.
    """
    mine = _one_body_binding()
    theirs = _binding(*mine.spans, account=other)

    assert mine.canonical_destination_set != theirs.canonical_destination_set


def test_the_derived_property_is_total_over_every_binding_that_constructs() -> None:
    """§8's first bullet: a gate that fails by exception is a gate that is caught.

    ``sorted()`` over members of mixed shape is what issue #1122's finding turns
    into a ``TypeError`` when the values are unvalidated dataclasses. Here every
    member is well-formed by construction, so the property returns for the
    account-only case, the single-recipient case and the many-recipient case
    alike.
    """
    for binding in (
        _one_body_binding(),
        _binding(_span("to", extent=17, destination=_destination(_RECIPIENT))),
        _binding(
            _span("to", index=0, extent=17, destination=_destination("alice@example.com")),
            _span("to", index=1, extent=15, destination=_destination("zoe@example.com")),
        ),
    ):
        assert binding.canonical_destination_set


# --- §4: the three structural invariants, on the binding's own constructor ----


def test_a_duplicate_argument_index_pair_is_refused_by_the_binding() -> None:
    """§12's duplicate case, exercised at the type §4 assigns it to.

    "A case asserting a refusal at the wrong one of those two satisfies neither",
    so this one never builds an :class:`ActionRequest` at all.
    """
    with pytest.raises(ValidationError) as raised:
        _binding(_span("to", index=0, extent=1), _span("to", index=0, extent=1))

    assert "share an (argument, index) pair" in str(raised.value)


def test_a_mis_ordered_span_tuple_is_refused_by_the_binding() -> None:
    """§12's ordering case. Arguments compare by Unicode code point, so ``b`` > ``a``."""
    with pytest.raises(ValidationError) as raised:
        _binding(_span("b", extent=1), _span("a", extent=1))

    assert "ordered by argument" in str(raised.value)


@pytest.mark.parametrize(
    "spans",
    [
        pytest.param(({"index": 0}, {"index": 2}), id="a-gap-in-the-run"),
        pytest.param(({"index": 1}, {"index": 2}), id="a-run-not-starting-at-zero"),
        pytest.param(({}, {"index": 0}), id="an-indexless-span-beside-an-indexed-one"),
    ],
)
def test_a_non_contiguous_run_of_indices_is_refused_by_the_binding(
    spans: tuple[Mapping[str, Any], ...],
) -> None:
    """§4's contiguity invariant: one indexless span, or exactly ``0..k-1``."""
    with pytest.raises(ValidationError) as raised:
        _binding(*(_span("to", extent=1, **dict(overrides)) for overrides in spans))

    assert "0 through k-1" in str(raised.value)


# --- §4: the parameter-relative rest, on ActionRequest's own validator --------


def test_an_argument_with_no_span_is_refused_by_the_request() -> None:
    """§12's coverage case, and one of two ADR-0148 §14 cases it makes unconstructable.

    An argument with no span is not a request that gets ruled on, it is a request
    that does not exist — ADR-0029 §2's shape, where a ``DENY`` produces no
    ``ToolCall``. Coverage is over the *arguments* rather than over what the call
    transmits: `core` cannot know which arguments a callable transmits, so it
    over-describes rather than risking a description narrower than the payload.
    """
    binding = _binding(_span("body", extent=2))
    with pytest.raises(ValidationError) as raised:
        _request({"body": "hi", "draft": True}, binding)

    assert "described by at least one span" in str(raised.value)


def test_a_span_naming_an_argument_the_call_does_not_carry_is_refused_by_the_request() -> None:
    """§12's second coverage case: the binding is well-formed, the pairing is not."""
    binding = _binding(_span("subject", extent=2))
    with pytest.raises(ValidationError) as raised:
        _request({"body": "hi"}, binding)

    assert "do not carry" in str(raised.value)


def test_an_array_of_length_n_described_by_k_spans_is_refused_by_the_request() -> None:
    """§12's ``k ≠ n`` case, with ``k = 1`` so the coverage clause is not what fires."""
    binding = _binding(_span("to", index=0, extent=17, destination=_destination(_RECIPIENT)))
    with pytest.raises(ValidationError) as raised:
        _request({"to": [_RECIPIENT, "zoe@example.com"]}, binding)

    assert "0 through n-1" in str(raised.value)


def test_a_non_array_argument_described_by_an_indexed_span_is_refused_by_the_request() -> None:
    """§12's non-array case, which is what makes the two locatable shapes exhaustive.

    Without it an indexed span on a string-valued argument would be constructable,
    unlocatable, and a residue this surface would have had to find an owner for.
    """
    binding = _binding(_span("body", index=0, extent=2))
    with pytest.raises(ValidationError) as raised:
        _request({"body": "hi"}, binding)

    assert "exactly one span, whose index is absent" in str(raised.value)


def test_a_destination_naming_a_form_the_arguments_never_selected_is_refused() -> None:
    """§12's supplied-form case — PR #1120's first blocker, closed at the type level.

    A description "naming a recipient the arguments never selected" is refused
    where the argument's own value is a string, because `core` holds both sides.
    Where the form is extracted from inside a structured value it cannot, and
    ADR-0150 §11 records that as surface (b)'s rather than pretending the check is
    total.
    """
    binding = _binding(
        _span("to", extent=17, destination=_destination("mallory@example.com")),
    )
    with pytest.raises(ValidationError) as raised:
        _request({"to": "alice@example.com"}, binding)

    assert "supplied form the argument's own value does not hold" in str(raised.value)


def test_a_stated_extent_over_a_string_is_recomputed_rather_than_believed() -> None:
    """§12's first extent case, on a binding that is **otherwise well-formed**.

    "A case whose extent is wrong *and* whose coverage or ordering is wrong
    demonstrates neither check", so the binding here covers its one argument
    exactly once and differs from the accepted request only in the integer.
    """
    assert _request({"body": "hi"}, _binding(_span("body", extent=2)))

    with pytest.raises(ValidationError) as raised:
        _request({"body": "hi"}, _binding(_span("body", extent=0)))

    assert "Unicode code-point count" in str(raised.value)


def test_a_stated_extent_over_a_non_string_is_recomputed_from_the_canonical_json() -> None:
    """§12's second extent case: the non-string branch of §4's unit rule.

    ``{"a":1}`` is seven code points in the canonical encoding ADR-0021 §1 pins —
    ``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=False`` — which
    is the same encoding ``parameters_digest`` is taken over, reused rather than
    invented because a second canonical encoding is a second thing to get wrong.
    """
    assert _request({"headers": {"a": 1}}, _binding(_span("headers", extent=7)))

    with pytest.raises(ValidationError) as raised:
        _request({"headers": {"a": 1}}, _binding(_span("headers", extent=6)))

    assert "Unicode code-point count" in str(raised.value)


@pytest.mark.parametrize(
    ("value", "extent"),
    [
        pytest.param("\U0001f600", 1, id="outside-the-basic-multilingual-plane"),
        pytest.param("é", 2, id="a-combining-sequence"),
        pytest.param("é", 1, id="the-same-character-composed"),
    ],
)
def test_extent_is_code_points_and_not_any_neighbouring_unit(value: str, extent: int) -> None:
    """§12's boundary cases. "A test whose only string is ASCII distinguishes no unit."

    U+1F600 is one code point, two UTF-16 units and four UTF-8 bytes; ``é``
    decomposed is two code points and one grapheme cluster, composed is one of
    each. Two components that measured differently would build unequal bindings
    for one request and ``authorises`` would answer ``False`` — a false mismatch,
    which ADR-0021 §1 records "reads as an attack rather than as a bug".
    """
    assert _request({"body": value}, _binding(_span("body", extent=extent)))

    with pytest.raises(ValidationError):
        _request({"body": value}, _binding(_span("body", extent=len(value.encode("utf-8")))))


def test_an_empty_array_argument_carries_no_span_and_the_binding_is_well_formed() -> None:
    """§12's empty-array case, in both directions.

    A span for ``[]`` would have to state an extent and a provenance for a thing
    that does not exist, and ``SYSTEM_SELECTED`` would be a disclosure record for
    nothing disclosed. An indexless span standing for an absent element would also
    make ``to: []`` and ``to: ""`` indistinguishable in the record.
    """
    request = _request({"to": [], "body": "hi"}, _binding(_span("body", extent=2)))
    assert request.egress_binding is not None
    assert request.egress_binding.canonical_destination_set == (
        CanonicalDestination(account=_ACCOUNT),
    )

    with pytest.raises(ValidationError) as raised:
        _request({"to": [], "body": "hi"}, _binding(_span("body", extent=2), _span("to", extent=2)))

    assert "empty JSON array is described by no span" in str(raised.value)


@pytest.mark.parametrize(
    ("value", "spans", "accepted"),
    [
        pytest.param(
            [["a"], ["b"]],
            ({"index": 0, "extent": 5}, {"index": 1, "extent": 5}),
            True,
            id="an-array-of-arrays-is-one-span-per-top-level-element",
        ),
        pytest.param(
            {"a": 1},
            ({"extent": 7},),
            True,
            id="a-json-object-is-one-indexless-span",
        ),
        pytest.param(
            [["a"], ["b"]],
            (
                {"index": 0, "extent": 1},
                {"index": 1, "extent": 1},
                {"index": 2, "extent": 1},
            ),
            False,
            id="decomposing-a-nested-array-further-is-refused",
        ),
    ],
)
def test_the_decomposition_goes_one_array_level_and_never_further(
    value: Any, spans: tuple[Mapping[str, Any], ...], accepted: bool
) -> None:
    """§12's nested cases, and the depth rule §4 fixes to close a round-2 finding.

    An earlier draft stated the per-element rule for arrays and, separately, that a
    value nesting more deeply was one span at its argument — and
    ``{"recipients": [["a"], ["b"]]}`` satisfied both antecedents while no binding
    satisfied both consequents. The repair makes the depth a property of the
    *decomposition*: an argument decomposes if it is an array, and a span never
    decomposes at all.
    """
    binding = _binding(*(_span("payload", **dict(overrides)) for overrides in spans))
    if accepted:
        assert _request({"payload": value}, binding)
        return
    with pytest.raises(ValidationError):
        _request({"payload": value}, binding)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"extent": -1}, id="a-negative-extent"),
        pytest.param({"index": -1}, id="a-negative-index"),
    ],
)
def test_a_span_counting_below_zero_is_refused(overrides: Mapping[str, Any]) -> None:
    """§4's "non-negative integer", and issue #755's rule that a floor is enforced.

    A count that fails open is the direction ADR-0073 §4 forgives least: a negative
    extent would state a payload smaller than nothing to an approver.
    """
    with pytest.raises(ValidationError):
        _span("body", **dict(overrides))


def test_a_span_carries_one_provenance_and_at_most_one_destination() -> None:
    """The `core` half of §4's cardinality and mixed-provenance clauses.

    Both clauses proper are **builder** refusals and ADR-0150 §12 ships their
    tests with surface (b)'s lane: a builder holding two recipients, or two
    provenances, inside one undecomposable value refuses rather than describing
    it, and `core` — which reads no declaration and cannot see inside such a
    value — can perform neither check. What `core` supplies is the shape that
    makes the under-representation unstateable rather than merely refused: a span
    has exactly one provenance, required, and one optional destination slot, so no
    binding can *carry* two of either and no lane can read a structured span's
    single occurrence as evidence that the value selected one recipient.
    """
    assert EgressSpan.model_fields["provenance"].is_required()
    assert not EgressSpan.model_fields["destination"].is_required()
    assert EgressSpan.model_fields["destination"].annotation == EgressDestination | None


def test_a_span_omitting_its_provenance_raises() -> None:
    """§12's clause, and what §5's no-default rule is worth.

    A defaulted field is what a lane forgets: an implementation that never wired
    provenance through would get ``SYSTEM_SELECTED`` for free and its payloads
    would look correct. Requiring the field forces every builder to answer.
    """
    with pytest.raises(ValidationError) as raised:
        EgressSpan(argument="body", extent=2)  # type: ignore[call-arg]  # the omission is the case

    assert "provenance" in str(raised.value)


# --- §9: the conjunct, and the transcription -------------------------------


def test_a_decision_transcribes_the_binding_without_the_signature_growing() -> None:
    """§9's transcription clause: carried by `core`, never supplied by a caller.

    A caller with no parameter for it cannot make a decision name a binding the
    policy did not see, which is the same property ``tool`` and ``execution_id``
    already have.
    """
    binding = _binding(_span("to", extent=17, destination=_destination(_RECIPIENT)))
    request = _request({"to": _RECIPIENT}, binding)
    decision = _decide(request)

    assert decision.egress_binding == request.egress_binding
    assert "egress_binding" not in signature(PermissionDecision.from_request).parameters


def test_rewriting_the_requests_binding_after_the_ruling_changes_nothing_recorded() -> None:
    """§12's rewrite case, on the request's **own** binding rather than on a copy.

    Pydantic passes an already-valid model instance through without copying, so
    without the deep copy the decision would hold the same object the request does
    and ``authorises`` would go on answering ``True`` because both sides moved
    together. That is ADR-0148 §4's third clause enforced rather than restated.
    """
    request = _request({"to": _RECIPIENT}, _binding(_span("to", extent=17)))
    decision = _decide(request)
    assert decision.authorises(request)

    assert request.egress_binding is not None
    object.__setattr__(request.egress_binding, "transport_endpoint", "smtp://evil.example.com:25")

    assert decision.egress_binding is not None
    assert decision.egress_binding.transport_endpoint == _ENDPOINT
    assert not decision.authorises(request)


def test_the_request_does_not_hold_the_callers_binding_object() -> None:
    """§9's detachment clause, the discipline ``tool`` already carries (ADR-0018 §3)."""
    binding = _binding(_span("to", extent=17))
    request = _request({"to": _RECIPIENT}, binding)

    assert request.egress_binding == binding
    assert request.egress_binding is not binding


def test_a_binding_and_no_binding_do_not_authorise_each_other_in_either_direction() -> None:
    """§12's ``None``-asymmetry pair. Only one of the two directions is obvious.

    A request with a binding meeting a decision without one is plainly a mismatch.
    The reverse — a decision recorded for an egress call offered a request with no
    binding — is the substitution that would let an approval for a described,
    destined send authorise a call that describes and destines nothing.
    """
    bound = _request({"to": _RECIPIENT}, _binding(_span("to", extent=17)))
    unbound = _request({"to": _RECIPIENT})

    assert not _decide(bound).authorises(unbound)
    assert not _decide(unbound).authorises(bound)


def test_two_bindings_with_identical_derived_sets_and_one_changed_supplied_form_are_unequal() -> (
    None
):
    """§12's substitution pair: the alias case moving *after* the user approved it.

    Comparing the whole value refuses a change of supplied form that leaves the
    canonical set identical. ADR-0148 §2's fourth clause requires both forms in
    the record precisely because they are different facts; a comparison that saw
    only the set would record one and bind the other.
    """
    approved = _request(
        {"to": "alice@Example.com"},
        _binding(_span("to", extent=17, destination=_destination("alice@Example.com"))),
    )
    substituted = _request(
        {"to": "alice@example.com"},
        _binding(_span("to", extent=17, destination=_destination("alice@example.com"))),
    )

    assert approved.egress_binding is not None
    assert substituted.egress_binding is not None
    assert (
        approved.egress_binding.canonical_destination_set
        == substituted.egress_binding.canonical_destination_set
    )
    assert approved.egress_binding != substituted.egress_binding
    assert not _decide(approved).authorises(substituted)
    assert not _decide(substituted).authorises(approved)


def test_two_bindings_differing_only_in_a_spans_provenance_are_unequal() -> None:
    """ADR-0148 §14's carried-provenance pair, reaching ``authorises``.

    Same arguments, same definition, same destinations — and a different answer to
    "did the user write this, or did we choose it". §12 requires that difference to
    reach the comparison rather than only the description builder.
    """
    authored = _request(
        {"body": "hi"},
        _binding(_span("body", extent=2, provenance=DiscloserProvenance.USER_AUTHORED)),
    )
    selected = _request(
        {"body": "hi"},
        _binding(_span("body", extent=2, provenance=DiscloserProvenance.SYSTEM_SELECTED)),
    )

    assert authored.egress_binding != selected.egress_binding
    assert not _decide(authored).authorises(selected)
    assert not _decide(selected).authorises(authored)


def test_a_decision_about_an_egress_call_still_authorises_its_own_request() -> None:
    """The positive half, so the four refusals above discriminate rather than blanket."""
    binding = _binding(
        _span("body", extent=2, provenance=DiscloserProvenance.USER_AUTHORED),
        _span("to", index=0, extent=17, destination=_destination(_RECIPIENT)),
    )
    request = _request({"body": "hi", "to": [_RECIPIENT]}, binding)
    decision = _decide(request)

    assert decision.authorises(request)
    assert decision.authorises(_request({"body": "hi", "to": [_RECIPIENT]}, binding))


def test_a_recorded_decision_reads_back_and_still_authorises() -> None:
    """ADR-0021 §4's durability, over the widened record (§8's serialisability clause).

    The occurrences are rebuilt and the derived set is recomputed identically,
    which is the property §3 spends its total order on.
    """
    binding = _binding(_span("to", extent=17, destination=_destination(_RECIPIENT)))
    request = _request({"to": _RECIPIENT}, binding)
    decision = _decide(request)

    reloaded = PermissionDecision.model_validate(decision.model_dump(mode="json"))

    assert reloaded == decision
    assert reloaded.authorises(request)
    assert reloaded.egress_binding is not None
    assert reloaded.egress_binding.canonical_destination_set == (
        CanonicalDestination(protocol=DestinationProtocol.SMTP, canonical="Alice@example.com"),
    )

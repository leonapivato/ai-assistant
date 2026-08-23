"""What a confirmation carries about an egress call (ADR-0178 §1, §2, §3, §4).

ADR-0148 §8's fourth clause is the content rule for an egress confirmation — the
connected account's **identity**, the canonical destination set **in both
forms**, the **payload description** — and until ADR-0178 no member of
:class:`~ai_assistant.core.types.Confirmation` carried any of the three. These
are the type-level obligations ADR-0178 §10 enumerates; the engine's two
assembly sites are pinned in ``tests/orchestration/test_engine.py``, the shared
clause binding every producer in
``tests/orchestration/assistant_engine_contract.py``, and the rendering floor in
``tests/interfaces/test_cli.py``.

**The correspondence cases are the ones that would otherwise rot.** ADR-0178 §3
puts a second derived property of the same shape on a second type and requires
the two to agree member for member and in order; nothing mechanical relates the
two implementations, so these cases are what make the drift detectable rather
than silent (its own Consequences say so).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core import types as core_types
from ai_assistant.core.types import (
    BoundAccount,
    Confirmation,
    ConfirmationDestination,
    ConfirmationEgress,
    ContinuationToken,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

IDENTITY = "work@example.com"
REFERENCE = "conn-0001"
ENDPOINT = "test://endpoint/one"

#: The names ADR-0178 §2 bars from either new type, and the annotations that
#: would carry them. Spelled here rather than derived: the clause is a
#: prohibition, and a check that computed the forbidden set from the types under
#: test would agree with whatever those types happened to declare.
_BARRED_ANNOTATIONS = ("BoundAccount", "SecretName", "DurableIdentifier")
_BARRED_NAME_PARTS = ("reference", "endpoint", "credential", "secret", "slot")


def _account() -> BoundAccount:
    """The connected account every binding here is made through."""
    return BoundAccount(identity=IDENTITY, reference=REFERENCE)


def _span(  # noqa: PLR0913 — one keyword per field of the span being built
    argument: str,
    *,
    index: int | None = None,
    extent: int = 5,
    canonical: str | None = None,
    supplied: str | None = None,
    tier: DataTier | None = None,
    provenance: DiscloserProvenance = DiscloserProvenance.SYSTEM_SELECTED,
) -> EgressSpan:
    """One span, with a destination exactly where ``canonical`` is given."""
    destination = (
        None
        if canonical is None
        else EgressDestination(
            protocol=DestinationProtocol.SMTP,
            supplied=supplied if supplied is not None else canonical,
            canonical=canonical,
        )
    )
    return EgressSpan(
        argument=argument,
        index=index,
        provenance=provenance,
        extent=extent,
        tier=tier,
        destination=destination,
    )


def _binding(*spans: EgressSpan, planned_with_external_content: bool = False) -> EgressBinding:
    """A whole binding over ``spans``, against one active account."""
    return EgressBinding(
        spans=spans,
        account=_account(),
        transport_endpoint=ENDPOINT,
        planned_with_external_content=planned_with_external_content,
    )


def _reduced(binding: EgressBinding) -> ConfirmationEgress:
    """The member the engine builds from ``binding`` — the three fields, nothing else."""
    return ConfirmationEgress(
        account_identity=binding.account.identity,
        spans=binding.spans,
        planned_with_external_content=binding.planned_with_external_content,
    )


# --- §1: the sixth member, required ------------------------------------------


def test_confirmation_carries_exactly_six_fields_and_still_forbids_extras() -> None:
    """ADR-0178 §1: one field added, none removed, ``extra="forbid"`` unchanged."""
    assert set(Confirmation.model_fields) == {
        "tool_id",
        "tool_description",
        "parameters",
        "reason",
        "token",
        "egress",
    }
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        Confirmation(
            tool_id="t-1",
            tool_description="send",
            parameters={},
            reason="external",
            token=ContinuationToken(handle="h-1"),
            egress=None,
            recipients=(),  # type: ignore[call-arg]  # the point of the case
        )


def test_the_egress_member_carries_no_default_so_every_site_states_it() -> None:
    """ADR-0178 §1: a defaulted field is what a lane forgets.

    An implementation that never wired the binding through would get a
    well-formed *non-egress* confirmation for free, and its egress prompts would
    look correct — ADR-0150 §5's argument for a defaultless ``provenance``, at the
    same distance from a reviewer.
    """
    assert Confirmation.model_fields["egress"].is_required()
    with pytest.raises(ValidationError, match="egress"):
        Confirmation(  # type: ignore[call-arg]  # the omission is the case
            tool_id="t-1",
            tool_description="send",
            parameters={},
            reason="external",
            token=ContinuationToken(handle="h-1"),
        )


# --- §2: what the member carries, and the three things it must not -----------


def test_confirmation_egress_refuses_an_extra_member_and_a_missing_one() -> None:
    """ADR-0178 §2: exactly two fields, both required with no default."""
    assert set(ConfirmationEgress.model_fields) == {"account_identity", "spans"}
    assert all(field.is_required() for field in ConfirmationEgress.model_fields.values())
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        ConfirmationEgress(
            account_identity=IDENTITY,
            spans=(),
            transport_endpoint=ENDPOINT,  # type: ignore[call-arg]  # the point of the case
        )
    with pytest.raises(ValidationError, match="spans"):
        ConfirmationEgress(account_identity=IDENTITY)  # type: ignore[call-arg]  # ditto
    with pytest.raises(ValidationError, match="account_identity"):
        ConfirmationEgress(spans=())  # type: ignore[call-arg]  # ditto


def test_the_spans_are_the_bindings_own_value_member_for_member() -> None:
    """ADR-0178 §2: reuse, not a second description derived beside it.

    Several arguments and several array elements, because ADR-0150 §10's third
    clause is stated over *occurrences*: one recipient named twice is one member
    of the set and two disclosures here, and a member that filtered, reordered,
    truncated or summarised the tuple would have understated the call.
    """
    binding = _binding(
        _span("body", extent=11),
        _span("cc", canonical="carol@example.org", extent=17),
        _span("to", index=0, canonical="alice@example.org", extent=17),
        _span("to", index=1, canonical="bob@example.org", extent=15),
    )
    egress = _reduced(binding)
    assert egress.spans == binding.spans
    assert len(egress.spans) == 4
    assert [span.argument for span in egress.spans] == ["body", "cc", "to", "to"]


def test_neither_new_type_names_or_types_a_barred_value() -> None:
    """ADR-0178 §2, over ``model_fields``, so a seventh field cannot arrive unnoticed.

    A connection reference, a credential slot, a ``SecretName``, a keyring string
    and a transport endpoint are barred, and **no field is added through which
    one could travel** — so this walks the whole reachable field graph rather
    than the two declarations' own fields. ``BoundAccount`` is barred as a whole
    because it carries the reference; ADR-0148 §8's fourth clause bars that in
    terms, and ``BoundAccount``'s own field description says it is never shown.
    """
    for model in (ConfirmationEgress, ConfirmationDestination):
        for name, field in model.model_fields.items():
            rendered = str(field.annotation)
            for barred in _BARRED_ANNOTATIONS:
                assert barred not in rendered, f"{model.__name__}.{name} is typed for {barred}"
            for part in _BARRED_NAME_PARTS:
                assert part not in name, f"{model.__name__}.{name} names a barred value"
    reachable = {kind.__name__ for kind in _reachable_from(ConfirmationEgress)}
    assert reachable.isdisjoint(set(_BARRED_ANNOTATIONS))
    assert "transport_endpoint" not in {
        name for model in _reachable_from(ConfirmationEgress) for name in model.model_fields
    }


def _reachable_from(root: type[BaseModel]) -> Iterator[type[BaseModel]]:
    """Every model the field graph out of ``root`` reaches, ``root`` included."""
    seen: set[type[BaseModel]] = set()
    pending: list[Any] = [root]
    while pending:
        annotation = pending.pop()
        if get_args(annotation) or get_origin(annotation) is not None:
            pending.extend(get_args(annotation))
            continue
        if not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
            continue
        if annotation in seen:
            continue
        seen.add(annotation)
        pending.extend(get_type_hints(annotation, globalns=vars(core_types)).values())
    return iter(seen)


def test_the_account_identity_must_render_as_something() -> None:
    """ADR-0178 §2: the identity's own type refuses text that renders as nothing.

    ``BoundAccount`` states the reason and it is this surface's: "an identity that
    rendered as nothing would leave the confirmation with nothing to say about
    whose account this is."
    """
    for invisible in ("", "   ", "\u200b"):
        with pytest.raises(ValidationError):
            ConfirmationEgress(
                account_identity=invisible, spans=(), planned_with_external_content=False
            )


def test_the_account_identity_survives_byte_for_byte() -> None:
    """ADR-0178 §2: nothing normalises, trims, truncates or case-folds it.

    A faithful copy may tighten only in ways that *reject* (ADR-0096 §2): the
    value is compared against the identity a connection record holds, so `core`
    rewriting it would be exactly what ADR-0148 §4's third clause forbids between
    the ruling and transmission.
    """
    awkward = " \u00a0Work Account\t(Personal)  "
    reduced = ConfirmationEgress(
        account_identity=awkward, spans=(), planned_with_external_content=False
    )
    assert reduced.account_identity == awkward


# --- §3: the derived set, and the correspondence that would otherwise rot -----


def _cases() -> list[tuple[str, EgressBinding]]:
    """The five binding shapes ADR-0178 §10's §3 bullet names."""
    return [
        ("no destination", _binding(_span("body", extent=11))),
        ("one destination", _binding(_span("to", canonical="alice@example.org", extent=17))),
        (
            "several destinations",
            _binding(
                _span("to", index=0, canonical="alice@example.org", extent=17),
                _span("to", index=1, canonical="bob@example.org", extent=15),
            ),
        ),
        (
            "an aliased pair that deduplicates",
            _binding(
                _span("cc", canonical="alice@example.org", supplied="Alice@Example.ORG", extent=17),
                _span("to", canonical="alice@example.org", supplied="alice@example.org", extent=17),
            ),
        ),
        (
            "destinations across the ordering boundary",
            _binding(
                # Written in span order, which is *not* the derived order: "Z" is
                # U+005A and "a" is U+0061, so a set ordered by anything but code
                # point — a case-folding sort, say — would come back the other way.
                _span("to", index=0, canonical="a@example.org", extent=13),
                _span("to", index=1, canonical="Z@example.org", extent=13),
            ),
        ),
    ]


@pytest.mark.parametrize(("label", "binding"), _cases(), ids=[name for name, _ in _cases()])
def test_the_derived_set_corresponds_to_the_bindings_own(
    label: str, binding: EgressBinding
) -> None:
    """ADR-0178 §3: member for member, in order, differing only on the account arm.

    Two computations of one rule and no second rule. The account member carries
    the identity here and the whole ``BoundAccount`` there, and nothing else about
    the two sets may differ — a set that disagreed would put a recipient on screen
    the call does not send to, or hide one it does.
    """
    theirs = binding.canonical_destination_set
    ours = _reduced(binding).canonical_destination_set
    assert len(ours) == len(theirs), label
    for mine, other in zip(ours, theirs, strict=True):
        assert mine.protocol == other.protocol
        assert mine.canonical == other.canonical
        if other.account is None:
            assert mine.account_identity is None
        else:
            assert mine.account_identity == other.account.identity


def test_the_derived_set_is_never_empty_and_an_empty_description_is_the_account() -> None:
    """ADR-0178 §3: exactly one member — the account — where the spans carry none."""
    for _, binding in _cases():
        assert _reduced(binding).canonical_destination_set
    account_only = _reduced(_binding(_span("body", extent=11))).canonical_destination_set
    assert account_only == (ConfirmationDestination(account_identity=IDENTITY),)
    assert _reduced(_binding()).canonical_destination_set == account_only


def test_the_derived_set_is_a_property_and_never_a_field() -> None:
    """ADR-0178 §3: never stored, never transmitted, never accepted from a caller.

    A stored set is a second representation of one fact, and because a property is
    not a pydantic field nothing about it reaches a frame either — which is what
    keeps ``PROTOCOL_VERSION`` a statement about ``Confirmation.egress`` alone.
    """
    assert "canonical_destination_set" not in ConfirmationEgress.model_fields
    assert "canonical_destination_set" not in _reduced(_binding()).model_dump()
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        ConfirmationEgress(
            account_identity=IDENTITY,
            spans=(),
            planned_with_external_content=False,
            canonical_destination_set=(),  # type: ignore[call-arg]  # the point of the case
        )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"protocol": DestinationProtocol.SMTP},
        {"canonical": "alice@example.org"},
        {"account_identity": IDENTITY, "protocol": DestinationProtocol.SMTP},
        {"account_identity": IDENTITY, "canonical": "alice@example.org"},
        {
            "account_identity": IDENTITY,
            "protocol": DestinationProtocol.SMTP,
            "canonical": "alice@example.org",
        },
    ],
)
def test_a_confirmation_destination_refuses_every_combination_but_the_two(
    fields: dict[str, object],
) -> None:
    """ADR-0178 §3: two shapes and no third, refused at construction.

    A bag of optional fields admits eight combinations; six are meaningless, and a
    validator makes every one of them unconstructable rather than merely
    undocumented.
    """
    with pytest.raises(ValidationError):
        ConfirmationDestination(**fields)  # type: ignore[arg-type]  # the point of the case


def test_the_two_shapes_construct_and_never_compare_equal() -> None:
    """ADR-0178 §3: equality is over every field, so the arms cannot collide."""
    recipient = ConfirmationDestination(
        protocol=DestinationProtocol.SMTP, canonical="alice@example.org"
    )
    account = ConfirmationDestination(account_identity="alice@example.org")
    assert recipient != account


# --- §4: absent, not empty ---------------------------------------------------


def test_an_empty_span_tuple_is_a_description_and_not_a_non_egress_marker() -> None:
    """ADR-0178 §4: absence is the state, and the type is what expresses it.

    An empty span tuple is a well-formed payload description meaning "this call's
    arguments are empty or hold nothing but empty JSON arrays" (ADR-0150 §4) — a
    statement about a call that *is* an egress call. It is constructible here, and
    what makes it not a non-egress marker is that it still names an account and
    still derives a non-empty set.
    """
    egress = ConfirmationEgress(
        account_identity=IDENTITY, spans=(), planned_with_external_content=False
    )
    assert egress.canonical_destination_set == (ConfirmationDestination(account_identity=IDENTITY),)
    assert egress is not None

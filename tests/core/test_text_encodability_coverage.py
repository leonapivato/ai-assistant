r"""No `core` string field may accept text with no UTF-8 encoding (issue #565).

ADR-0084 §4 obliges **every** implementation of the promoted engine Protocol to
enforce the same limits, so a wire client is never silently less capable than the
in-process engine, and ADR-0087 fixed the encoding as canonical JSON over UTF-8.
A lone surrogate is a ``str`` Python holds happily and UTF-8 cannot express, so a
plain ``str`` field made the two implementations disagree about which calls they
accept: ``FeedbackEvent(content="\ud800")`` constructed, the in-process engine
took it, and no encoder could put it on the socket.

ADR-0087 §7 puts the refusal on the **type** rather than at each boundary, and
:data:`~ai_assistant.core.types.EncodableText` is that type. This module is what
makes it stick, in the shape ``test_instant_coverage.py`` uses for
:data:`~ai_assistant.core.types.UtcInstant` and for the same reason: a per-field
validator is opt-in, so the field nobody remembered is exactly how the gap gets
in. It discovers every ``str`` leaf on every model in ``core.types`` and fails on
one that is not wrapped, so the omission fails the gate rather than depending on
a reviewer noticing.

**Scoped to ``core.types``, deliberately.** ADR-0068 §1 records that
``core/types.py`` "holds only boundary-crossing types", which makes the whole
module's string surface the wire's string surface. ``core.config``'s
:class:`~ai_assistant.core.config.Settings` is read from the environment by one
process and never serialised into a frame, so it is a different question and not
this one.

**There is no exemption list**, and that is a decision rather than a happy
accident: :data:`~ai_assistant.core.types.Sha256Hex` and
:attr:`~ai_assistant.core.types.ToolCost.currency` already refuse every value
:data:`~ai_assistant.core.types.EncodableText` would, and are typed with it
anyway so that the check below stays total and a later relaxation of the stricter
rule cannot silently reopen the gap.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, TypeAliasType, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ai_assistant.core import types as core_types
from ai_assistant.core.types import (
    ActionPlan,
    EncodableText,
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    FrozenJsonMapping,
    FrozenJsonValue,
    Goal,
    GoalStatus,
    Identifier,
    MemoryKind,
    MemorySource,
    Message,
    PlanStep,
    Provenance,
    Role,
    SemanticMemory,
    Sha256Hex,
    VisibleIdentifier,
)

#: A ``str`` with no UTF-8 encoding: half of a character rather than a character.
SURROGATE = "\ud800"

#: A real supplementary character, four UTF-8 bytes — accepted, and pinned as such.
SUPPLEMENTARY = "\U0001f600"

#: The aliases that carry the encodability guarantee, by identity.
#:
#: :data:`EncodableText` carries it directly. The two ``FrozenJson`` holders carry
#: the same property by a different mechanism — ``_freeze_json`` runs the real
#: encoder over the thawed value at validation time, so a surrogate at any depth,
#: in a key or a value, is refused (ADR-0087 §9 names this as the shape of the
#: fix). Both are listed rather than assumed: the behavioural tests below pin
#: that each really does refuse.
GUARDING_ALIASES = (EncodableText, FrozenJsonValue, FrozenJsonMapping)


def _str_leaves(
    annotation: object, *, guarded: bool, seen: frozenset[int] = frozenset()
) -> list[bool]:
    """For every ``str`` in ``annotation``, whether a guarding alias wraps it.

    Walks unions, ``Annotated``, generic parameters and type aliases, so
    ``EncodableText | None`` and ``tuple[EncodableText, ...]`` are recognised
    while a bare ``str | None`` is not. ``seen`` breaks the cycle in a recursive
    alias such as ``FrozenJson``, which refers to itself.

    A ``Literal["episodic"]`` argument is the *string* ``"episodic"`` rather than
    the type ``str``, and a ``StrEnum`` subclass is not ``str`` either, so
    neither is reported — both have a closed set of constant members.
    """
    if id(annotation) in seen:
        return []
    if isinstance(annotation, TypeAliasType):
        return _str_leaves(
            annotation.__value__,
            guarded=guarded or any(annotation is alias for alias in GUARDING_ALIASES),
            seen=seen | {id(annotation)},
        )
    origin = get_origin(annotation)
    if origin is Annotated:
        return _str_leaves(get_args(annotation)[0], guarded=guarded, seen=seen)
    if origin is not None:
        return [
            leaf
            for arg in get_args(annotation)
            for leaf in _str_leaves(arg, guarded=guarded, seen=seen | {id(annotation)})
        ]
    if annotation is str:
        return [guarded]
    return []


def bare_str_fields(model: type[BaseModel]) -> list[str]:
    """Names of ``model``'s fields holding a ``str`` no guarding alias wraps."""
    hints = get_type_hints(model, include_extras=True)
    return [
        name for name in model.model_fields if not all(_str_leaves(hints.get(name), guarded=False))
    ]


def _core_type_models() -> list[type[BaseModel]]:
    """Every pydantic model declared in ``ai_assistant.core.types``."""
    found: dict[str, type[BaseModel]] = {}
    for value in vars(core_types).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
            found[value.__qualname__] = value
    return list(found.values())


def test_the_scan_actually_finds_the_core_models() -> None:
    """A discovery check that silently found nothing would pass forever."""
    names = {model.__name__ for model in _core_type_models()}
    assert {
        "Message",
        "Provenance",
        "MemoryBase",
        "FeedbackEvent",
        "Goal",
        "ToolDefinition",
    } <= names


def test_the_walk_reports_an_unguarded_str() -> None:
    """The check discriminates: a bare annotation is reported, a wrapped one is not.

    Without this the walk could return ``[]`` for everything — every field would
    pass ``all([])`` and the gate would be green while enforcing nothing.
    """
    assert _str_leaves(str, guarded=False) == [False]
    assert _str_leaves(str | None, guarded=False) == [False]
    assert _str_leaves(tuple[str, ...], guarded=False) == [False]
    assert _str_leaves(EncodableText, guarded=False) == [True]
    assert _str_leaves(EncodableText | None, guarded=False) == [True]
    assert _str_leaves(tuple[EncodableText, ...], guarded=False) == [True]
    assert _str_leaves(Identifier, guarded=False) == [True]
    assert _str_leaves(int, guarded=False) == []


@pytest.mark.parametrize("model", _core_type_models(), ids=lambda model: model.__name__)
def test_every_core_str_field_refuses_unencodable_text(model: type[BaseModel]) -> None:
    """A bare ``str`` on a ``core.types`` field fails the gate (issue #565)."""
    offenders = set(bare_str_fields(model))
    assert not offenders, f"{model.__name__} has unguarded str field(s) {sorted(offenders)}"


def test_no_core_str_field_is_exempt() -> None:
    """Stated once over the whole module, not model by model.

    The per-model check above fails on the offending model; this one asserts the
    property with no exemption set at all, which is what stops a future field
    from re-appearing as an exemption argument threaded back through it.
    """
    bare = {
        (model.__name__, name) for model in _core_type_models() for name in bare_str_fields(model)
    }
    assert bare == set()


# --- the divergence itself, pinned on the sites issue #565 names -------------
# The coverage check above is structural. These construct the offending value and
# assert the refusal, so a walk that silently stopped finding leaves would still
# leave these failing.

AT = datetime(2026, 1, 1, tzinfo=UTC)


def _provenance() -> Provenance:
    return Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT)


@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"content": SURROGATE}, id="content"),
        pytest.param({"subject": SURROGATE}, id="subject"),
        pytest.param({"evidence": (SURROGATE,)}, id="evidence"),
    ],
)
def test_feedback_with_no_utf8_encoding_is_refused(field: dict[str, Any]) -> None:
    r"""The exact call issue #565 opens on.

    ``learn(FeedbackEvent(content="\ud800"))`` constructed before this, the
    in-process engine accepted it, and the wire client could not encode it —
    two implementations of one Protocol disagreeing about which calls they take,
    which is what ADR-0084 §4 exists to prevent.
    """
    payload: dict[str, Any] = {
        "kind": FeedbackKind.CORRECTION,
        "memory_kind": MemoryKind.SEMANTIC,
        "content": "the office is in Boston",
        "created_at": AT,
        **field,
    }
    with pytest.raises(ValidationError, match="UTF-8"):
        FeedbackEvent(**payload)


def test_a_goal_statement_with_no_utf8_encoding_is_refused() -> None:
    with pytest.raises(ValidationError, match="UTF-8"):
        Goal(
            id="g-1",
            statement=SURROGATE,
            status=GoalStatus.ACTIVE,
            provenance=_provenance(),
            created_at=AT,
        )


def test_a_memory_record_with_no_utf8_encoding_is_refused() -> None:
    with pytest.raises(ValidationError, match="UTF-8"):
        SemanticMemory(id="m-1", content="fine", fact=SURROGATE, provenance=_provenance())


def test_a_memory_participant_with_no_utf8_encoding_is_refused() -> None:
    """Inside a collection, not only at the top level."""
    with pytest.raises(ValidationError, match="UTF-8"):
        EpisodicMemory(
            id="m-1",
            content="fine",
            occurred_at=AT,
            participants=("ana", SURROGATE),
            provenance=_provenance(),
        )


def test_a_plan_rationale_with_no_utf8_encoding_is_refused() -> None:
    with pytest.raises(ValidationError, match="UTF-8"):
        ActionPlan(
            id="p-1",
            goal_id="g-1",
            steps=(PlanStep(id="s-1", intent="do it", capability="send_email"),),
            rationale=SURROGATE,
            created_at=AT,
        )


def test_a_message_with_no_utf8_encoding_is_refused() -> None:
    with pytest.raises(ValidationError, match="UTF-8"):
        Message(role=Role.USER, content=SURROGATE)


@pytest.mark.parametrize(
    "alias",
    [
        pytest.param(Identifier, id="Identifier"),
        pytest.param(VisibleIdentifier, id="VisibleIdentifier"),
        pytest.param(core_types.DurableIdentifier, id="DurableIdentifier"),
        pytest.param(EncodableText, id="EncodableText"),
    ],
)
def test_every_identifier_alias_refuses_unencodable_text(alias: Any) -> None:
    r"""``"g-\ud800"`` strips to something non-blank and renders as something.

    So neither ``_non_blank`` nor ``_has_visible_text`` catches it: the letters
    are real and only the surrogate is not. Each alias has to carry the
    encodability check itself, and each one now does.
    """
    with pytest.raises(ValidationError, match="UTF-8"):
        TypeAdapter(alias).validate_python("g-" + SURROGATE)


def test_the_digest_alias_refuses_unencodable_text() -> None:
    """:data:`Sha256Hex` is stricter and is typed on the alias anyway."""
    with pytest.raises(ValidationError):
        TypeAdapter(Sha256Hex).validate_python("a" * 63 + SURROGATE)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({"body": SURROGATE}, id="a value"),
        pytest.param({SURROGATE: "body"}, id="a key"),
        pytest.param({"nested": {"items": ["fine", SURROGATE]}}, id="at depth"),
    ],
)
def test_the_frozen_json_aliases_refuse_unencodable_text(value: dict[str, Any]) -> None:
    """The second guarding mechanism, pinned rather than assumed.

    ``GUARDING_ALIASES`` treats the ``FrozenJson`` holders as carrying the same
    property through ``_freeze_json``. That claim is only worth making if it is
    checked, because the structural walk would otherwise wave through every
    ``FrozenJsonMapping`` field on the strength of a comment.
    """
    with pytest.raises(ValidationError, match="no JSON encoding"):
        TypeAdapter(FrozenJsonMapping).validate_python(value)


# --- the other half: an accepted value survives the canonical encoding -------


def _canonical(value: object) -> bytes:
    """ADR-0087 §2's normative form, spelled out rather than imported.

    Written here in full so the test does not pass by agreeing with whatever
    ``core`` happens to do; it asserts against the ADR's own expression.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def test_an_accepted_feedback_event_round_trips_through_the_canonical_encoding() -> None:
    """The refusal is narrow: everything with an encoding still goes through.

    A supplementary character, an accented letter, a C0 control and U+2028 are
    all things ADR-0087 §2b positively spells rather than refuses, so a validator
    written against "looks dangerous" rather than against "has an encoding" would
    fail here.
    """
    event = FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content="tone: caf\u00e9 " + SUPPLEMENTARY + " \u0007 \u007f \u2028 ",
        subject=f"email {SUPPLEMENTARY}",
        evidence=(f"turn-{SUPPLEMENTARY}",),
        created_at=AT,
    )
    encoded = _canonical(event.model_dump(mode="json"))
    assert FeedbackEvent.model_validate(json.loads(encoded.decode("utf-8"))) == event


def test_a_supplementary_character_is_not_mistaken_for_a_surrogate() -> None:
    """U+1F600 is a surrogate *pair* in UTF-16 and four bytes in UTF-8.

    A check written against the surrogate code-point range rather than against
    the encoder would refuse it (issue #121). The alias runs the encoder.
    """
    assert TypeAdapter(EncodableText).validate_python(SUPPLEMENTARY) == SUPPLEMENTARY


# --- the refusal has to be actionable, and has to survive being reported -----


def test_the_refusal_names_the_code_point_and_its_position() -> None:
    """A refusal a caller cannot act on is a bad refusal."""
    with pytest.raises(ValidationError) as raised:
        TypeAdapter(EncodableText).validate_python("hello " + SURROGATE + " world")
    message = str(raised.value)
    assert "U+D800" in message
    assert "position 6" in message


def test_the_refusal_does_not_echo_the_value_and_is_itself_encodable() -> None:
    """The sharper of the two reasons not to interpolate the offending text.

    A message built by pasting the value in would itself have no UTF-8 encoding,
    so reporting the fault would fail exactly the way the fault does — the
    diagnostic destroying the diagnosis that :func:`describe_untrusted` exists to
    prevent one type over. Megabytes of untrusted text in a log line is the other.

    **Asserted on the validator's own message, because pydantic's rendering is
    not this validator's to decide.** ``str(ValidationError)`` appends
    ``input_value=`` for every error it carries, so the value does appear there;
    what it appears as is ``repr``, which escapes a surrogate to ``\\ud800``, so
    the rendered error still has a UTF-8 encoding. Both halves are checked.
    """
    body = "correct-horse-battery-staple"
    with pytest.raises(ValidationError) as raised:
        TypeAdapter(EncodableText).validate_python(body + SURROGATE)
    message = raised.value.errors()[0]["msg"]
    assert body not in message
    assert message.encode("utf-8")  # would raise if the message carried the surrogate
    assert str(raised.value).encode("utf-8")  # pydantic's own rendering survives too

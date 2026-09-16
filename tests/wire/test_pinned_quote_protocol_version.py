"""``PROTOCOL_VERSION`` moved for the pin and the charged declaration, and the log says why.

ADR-0271 §8 states the move up front — *"``PermissionRuling`` and ``ToolDefinition`` each
cross the wire inside a ``PermissionDecision`` a client decodes, so P1 widens a decoded
shape and **owes the bump and its ``wire/envelope.py`` log entry in the same change**"* —
and ADR-0178 §6 is the precedent it cites for stating the bump in the deciding ADR at all.
``tests/wire/test_attempt_report_protocol_version.py`` is this file's precedent and it is
written to its shape.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.core.types import (
    ActionQuote,
    ChargedOutput,
    ConversationExport,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanExport,
    Reversibility,
    RiskLevel,
    ToolDefinition,
    VerificationKind,
)
from ai_assistant.wire import client, envelope, server, surface

#: The version ADR-0271's P1 moves to, and the one it moves from.
_MOVED_TO: Final = 52
_MOVED_FROM: Final = 51

#: The two grounds §8 gives, one field each.
_GROUNDS: Final = ((PermissionRuling, "proved_quote"), (ToolDefinition, "charged_output"))

#: The enumerations §8 leaves alone, which is why no third ground exists.
_UNMOVED_ENUMS: Final = (
    PermissionOutcome,
    RiskLevel,
    Reversibility,
    Idempotency,
    VerificationKind,
)


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§8: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0271 — the failure ``CONTRIBUTING.md`` → "No state claims in
    living documents" is about. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_names_this_decision_and_both_of_its_grounds() -> None:
    """§8: two grounds at once, and the entry names each with what it rides on.

    Enumerating them is what tells a later reader that neither one alone is the bump's
    whole reason, so removing either from this lane would not make the move
    unnecessary. The entry also names what earns **no** ground, which is the half a
    reader would otherwise have to reconstruct.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0271 §8**" in entry
    assert "PermissionRuling" in entry, "the ruling that gained proved_quote"
    assert "ToolDefinition" in entry, "the declaration that gained charged_output"
    assert "PermissionDecision" in entry, "and the record both of them cross inside"
    assert "ActionRequest" in entry, "and why the declaration crosses: it embeds one whole"
    assert "recent_decisions" in entry, "named, so the crossing is checkable and not asserted"
    assert "ChargedOutput" in entry, "minted, and riding the second ground rather than adding"
    assert "ActionQuote" in entry, "and the shape that reaches a frame for the first time"
    assert "ADR-0084 §3" in entry, "the handshake that makes the refusal the outcome"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_records_what_did_not_move() -> None:
    """§8, stated as not reached rather than left silent.

    The audit trail's marker **does** move for both widened shapes and moved in **P0**,
    the ``permissions`` lane before this one — *"P1 carries no part of it"* — so it is
    not this bump's to claim; the plan store's marker and ``PlanExport.schema_version``
    do not move at all, because neither the export nor any shape that store persists
    carries either widened record.
    """
    entry = _entry_for(_MOVED_TO)

    assert "audit trail" in entry, "the marker that did move for both shapes"
    assert "P0" in entry, "and the lane before this one is where it moved"
    assert "PlanExport" in entry, "the export version that does not move"
    assert "plan store" in entry, "nor the store's own marker"
    assert "Settings" in entry, "and nothing is configurable"
    assert "no compatibility shim" in entry.lower(), "ADR-0084 §3 is the mechanism"
    assert "lenient decode" in entry, "§8 names four refusals, not one"
    assert "back-filled" in entry, "and no record is rewritten or re-decided"


def test_each_ground_is_true_of_the_types_themselves() -> None:
    """The entry's two claims, checked against the tree rather than the prose.

    ``wire/codec.py`` renders a model by ``model_dump()`` and both models set
    ``extra="forbid"``, so the new member on every ruling a decision carries, and the
    new member on every definition it embeds, are what make a decision undecodable by a
    client at the previous version.
    """
    for model, field in _GROUNDS:
        assert field in model.model_fields
        assert model.model_config.get("extra") == "forbid"

    dumped = PermissionRuling(outcome=PermissionOutcome.DENY, reason="no").model_dump()
    assert "proved_quote" in dumped, "emitted on every ruling, not only a populated one"


def test_the_decision_is_what_carries_both_members_across_a_frame() -> None:
    """§8's stated ground: *"each cross the wire inside a ``PermissionDecision``"*.

    Asserted where it could stop being true. If a later lane stopped promoting every
    method that returns a decision, the two grounds would need restating rather than
    inheriting — and the check is over the promoted set rather than over one name.
    """
    returning = {"recent_decisions", "grantable_decisions", "export_decisions"}

    assert returning <= surface.METHODS
    assert PermissionDecision.model_fields["ruling"].annotation is PermissionRuling
    assert PermissionDecision.model_fields["tool"].annotation is ToolDefinition
    assert "proved_quote" not in PermissionDecision.model_fields, "§1: it gains no field"


def test_the_minted_record_reaches_a_frame_only_inside_the_declaration() -> None:
    """§8: :class:`ChargedOutput` rides the second ground rather than adding to it.

    It is carried by one field of one model, so ``ToolDefinition`` is the one promoted
    shape annotated with it, and the assertion is over every model this lane could have
    put it on.
    """
    carrying = [
        f"{model.__name__}.{field}"
        for model in (ToolDefinition, PermissionDecision, PermissionRuling, PlanExport)
        for field, info in model.model_fields.items()
        if info.annotation in {ChargedOutput, ChargedOutput | None}
    ]

    assert carrying == ["ToolDefinition.charged_output"]


def test_no_enumeration_gained_a_member_so_there_is_no_third_ground() -> None:
    """§8: no ``StrEnum`` value a peer at the previous version refuses.

    This is the ground this lane does **not** have, asserted because it is the one a
    reader would expect: an older peer's failure here is ``extra_forbidden`` on a
    member and never a refused value inside one. Both new members are typed by models
    rather than by vocabularies, which is why.
    """
    assert len(set(PermissionOutcome)) == 3, "ADR-0021 §3's three, and this decision adds none"
    assert len(set(VerificationKind)) == 3, "ADR-0253 §4's three, untouched here"
    for enumeration in _UNMOVED_ENUMS:
        assert set(enumeration), "read, so a removal fails here too"


def test_no_stored_record_version_moved_with_this_lane() -> None:
    """§8: *"P1 carries no part of it"*, the audit marker having moved in P0.

    Both widened shapes **are** stored shapes, which is exactly why §8 puts the marker
    in a ``permissions`` lane of its own that lands first; asserted as a floor here,
    because this lane must not be read as the one that moved it. The plan store's
    marker and ``PlanExport.schema_version`` do not move: neither the export nor any
    shape that store persists carries a ``ToolDefinition``, a ``PermissionRuling`` or a
    ``PermissionDecision`` at any depth.
    """
    from ai_assistant.permissions.audit import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _AUDIT_SCHEMA,
    )
    from ai_assistant.planning.sqlite_store import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PLAN_SCHEMA,
    )

    assert _AUDIT_SCHEMA >= 4, "P0's move, which this lane neither makes nor repeats"
    assert PlanExport.model_fields["schema_version"].default >= 16
    assert _PLAN_SCHEMA >= 8
    assert ConversationExport.model_fields["schema_version"].default == 2


def test_the_promoted_method_set_did_not_move() -> None:
    """§8: *"the promoted method set does not move, no gateway route is added"*.

    ADR-0124 §9's **first** limb is not what this bump is under, and saying so is what
    keeps the two limbs from blurring: the entry's own reading is the second limb alone,
    a wire-carried ``core`` type making a value one peer emits invalid for the other.
    The absolute count is pinned in ``tests/core/test_engine_surface_closure.py``
    beside the version, which is the one place either figure lives.
    """
    assert "converse" in surface.METHODS
    assert not any(method.startswith("charge") for method in surface.METHODS)
    assert not any("quote" in method for method in surface.METHODS)


def test_a_peer_at_the_previous_version_and_one_at_this_refuse_each_other() -> None:
    """§8: ADR-0084 §3's exact-match handshake, and the refusal names both versions.

    *"No compatibility shim, optional-member negotiation, per-member capability flag or
    lenient decode is added"* — so a peer at 51 and a peer at 52 do not interoperate,
    and what they do instead is say so. Each message is read here for **both** numerals:
    one naming only its own version leaves an operator unable to tell which half is
    behind.
    """
    for source in (inspect.getsource(server), inspect.getsource(client)):
        assert "!= env.PROTOCOL_VERSION" in source, "an exact match, never a range"
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(server)
    assert "version {version}" in inspect.getsource(server)
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(client)
    assert "version {version}" in inspect.getsource(client)
    assert envelope.VERSION_MISMATCH, "and the refusal carries its own code (ADR-0124 §6)"


def test_the_quote_reaches_a_frame_only_by_the_pin() -> None:
    """§8's *"for the first time"* claim, checked rather than recited.

    ``AuthorizationProjection.quote`` carries a three-field ``QuoteView`` and not a
    quote, and ``Authorization`` crosses whole in no frame (the entry at 48's own
    reading), so before this lane an ``ActionQuote`` reached no frame at all. The arm
    that fails a later lane putting one somewhere else and leaving this entry's reading
    stale.
    """
    carrying = [
        f"{model.__name__}.{field}"
        for model in (PermissionRuling, PermissionDecision, ToolDefinition)
        for field, info in model.model_fields.items()
        if info.annotation in {ActionQuote, ActionQuote | None}
    ]

    assert carrying == ["PermissionRuling.proved_quote"]


def test_nothing_of_this_decision_is_configurable() -> None:
    """§8: *"``core/config.py`` gains nothing"*.

    Asserted by name rather than by a count, because a count would fail on every
    unrelated setting a later lane adds. What this decision must not have is a knob for
    where a charge is read or whether a pin is kept: both are declared on the record,
    and a deployment that could turn either off would make the fail-closed default
    configurable.
    """
    from ai_assistant.core.config import Settings  # noqa: PLC0415 — asserted about

    assert not [
        name
        for name in Settings.model_fields
        if "charge" in name or "quote" in name or "proved" in name
    ]


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    ``tests/wire/test_attempt_report_protocol_version.py``'s helper, and for its reason:
    a phrase asserted across a line break is a test that fails on ``ruff format``
    rewrapping a paragraph.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)

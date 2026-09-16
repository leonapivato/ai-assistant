"""``PROTOCOL_VERSION`` moved for the report and the declaration, and the log says why.

ADR-0262 §8 states the move up front — "``PROTOCOL_VERSION`` therefore moves by exactly
one, in the lane that lands the ``core`` change, with ``wire/envelope.py``'s log entry
naming this ADR" — and ADR-0178 §6 is the precedent it cites for stating the bump in the
deciding ADR at all. ``tests/wire/test_goal_association_protocol_version.py`` is this
file's precedent and it is written to its shape.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.core.types import (
    AttemptOutcome,
    AttemptPhase,
    AttemptReport,
    AttemptState,
    AttemptTransition,
    ConversationExport,
    GoalStatus,
    PlanExport,
    ToolDefinition,
    TurnOutcome,
    VerificationKind,
)
from ai_assistant.wire import client, envelope, server, surface

#: The version ADR-0262's L1 moves to, and the one it moves from.
_MOVED_TO: Final = 51
_MOVED_FROM: Final = 50

#: The two grounds §8 gives, one field each.
_GROUNDS: Final = ((TurnOutcome, "attempt_report"), (ToolDefinition, "postconditions"))

#: The enumerations §8 says gain no member, which is why no third ground exists.
_UNMOVED_ENUMS: Final = (
    AttemptOutcome,
    GoalStatus,
    AttemptState,
    AttemptPhase,
    VerificationKind,
)


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§8: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0262 — the failure ``CONTRIBUTING.md`` → "No state claims in
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

    assert f"**{_MOVED_TO} since ADR-0262 §8**" in entry
    assert "TurnOutcome" in entry, "the outcome that gained attempt_report"
    assert "ToolDefinition" in entry, "the declaration that gained postconditions"
    assert "ActionRequest" in entry, "and why the declaration crosses: it embeds one whole"
    assert "PermissionDecision" in entry, "and so does the record the trail keeps"
    assert "AttemptReport" in entry, "minted, and riding the first ground rather than adding"
    assert "execution_versions" in entry, "and the field that crosses nowhere at all"
    assert "ADR-0124 §9" in entry, "the rule it is read under"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_records_what_did_not_move() -> None:
    """§8, stated as not reached rather than left silent.

    The audit trail's marker **does** move for ``postconditions`` and moved in LA, the
    lane before this one, so it is not this bump's to claim; the plan store's marker and
    ``PlanExport.schema_version`` do not move at all, because no shape that store
    persists changes.
    """
    entry = _entry_for(_MOVED_TO)

    assert "audit trail" in entry, "the marker that did move for postconditions"
    assert "LA" in entry, "and the lane before this one is where it moved"
    assert "PlanExport" in entry, "the export version that does not move"
    assert "plan store" in entry, "nor the store's own marker"
    assert "Settings" in entry, "and nothing is configurable"
    assert "no compatibility shim" in entry.lower(), "ADR-0084 §3 is the mechanism"


def test_each_ground_is_true_of_the_types_themselves() -> None:
    """The entry's two claims, checked against the tree rather than the prose.

    ``wire/codec.py`` renders a model by ``model_dump()`` and both models set
    ``extra="forbid"``, so the new member on every outcome a hub sends, and the new
    tuple on every definition a decision embeds, are what make a turn undecodable by a
    client at the previous version.
    """
    for model, field in _GROUNDS:
        assert field in model.model_fields
        assert model.model_config.get("extra") == "forbid"

    dumped = TurnOutcome(turn=None, step=None).model_dump()
    assert "attempt_report" in dumped, "emitted on every outcome, not only a populated one"


def test_no_enumeration_gained_a_member_so_there_is_no_third_ground() -> None:
    """§8: *"**no new enumeration**"*, and no member added to the five it names.

    This is the ground this lane does **not** have, asserted because it is the one a
    reader would expect: every bump since 5 that was not a method-set change has had at
    least one ``StrEnum`` value a peer at the previous version refuses. This one has
    none — ``AttemptReport.outcome`` is typed by a vocabulary ADR-0249 and ADR-0261
    already fixed at seven, which is why an older peer's failure is
    ``extra_forbidden`` on the member and never a refused value inside it.
    """
    assert len(set(AttemptOutcome)) == 7, "ADR-0249 §5's six as ADR-0261 §3 made them seven"
    assert len(set(VerificationKind)) == 3, "ADR-0253 §4's three, and this decision adds none"
    for enumeration in _UNMOVED_ENUMS:
        assert set(enumeration), "read, so a removal fails here too"


def test_the_write_command_reaches_no_frame_at_all() -> None:
    """§8: ``execution_versions`` is not a third ground, and the reason is structural.

    ``AttemptTransition`` is ``PlanStore``'s write command; ``PlanStore`` is not
    promoted (ADR-0255 §11) and no wire operation takes one. Asserted where it could
    stop being true — a lane that promoted an operation taking one would fail here and
    have to move this number rather than discover the mismatch at a handshake that
    passed.
    """
    assert "execution_versions" in AttemptTransition.model_fields
    assert not any("attempt" in method and "commit" in method for method in surface.METHODS)


def test_the_minted_model_reaches_a_frame_only_inside_the_outcome() -> None:
    """§8: :class:`AttemptReport` rides the first ground rather than adding to it.

    It is carried by no stored record and by no export — *"riding ``TurnOutcome``
    alone"* — so ``TurnOutcome`` is the one promoted model annotated with it, and the
    assertion is over every promoted model this lane could have put it on.
    """
    carrying = [
        f"{model.__name__}.{field}"
        for model in (TurnOutcome, PlanExport, ConversationExport, AttemptTransition)
        for field, info in model.model_fields.items()
        if info.annotation in {AttemptReport, AttemptReport | None}
    ]

    assert carrying == ["TurnOutcome.attempt_report"]


def test_no_stored_record_version_moved_with_this_lane() -> None:
    """§8: *"the plan store's ``schema_version`` does not move, ``PlanExport.
    schema_version`` does not move, no migration is owed in either"*.

    No shape that store persists changes — ``AttemptTransition`` is a **command** rather
    than a stored record (ADR-0249 §12) — so a document written after this decision
    decodes for a reader at the previous version. The **audit trail's** marker is the
    one that did move, and it moved in LA: asserted as a floor here, because this lane
    must not be read as the one that moved it.
    """
    from ai_assistant.permissions.audit import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _AUDIT_SCHEMA,
    )
    from ai_assistant.planning.sqlite_store import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PLAN_SCHEMA,
    )

    assert _AUDIT_SCHEMA >= 4, "LA's move, which this lane neither makes nor repeats"
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
    assert not any(method.startswith("attempt") for method in surface.METHODS)


def test_a_peer_at_the_previous_version_and_one_at_this_refuse_each_other() -> None:
    """§8: ADR-0084 §3's exact-match handshake, and the refusal names both versions.

    *"No compatibility shim, negotiation or lenient decode is added"* — so a peer at 50
    and a peer at 51 do not interoperate, and what they do instead is say so. Each
    message is read here for **both** numerals: one naming only its own version leaves
    an operator unable to tell which half is behind.
    """
    for source in (inspect.getsource(server), inspect.getsource(client)):
        assert "!= env.PROTOCOL_VERSION" in source, "an exact match, never a range"
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(server)
    assert "version {version}" in inspect.getsource(server)
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(client)
    assert "version {version}" in inspect.getsource(client)
    assert envelope.VERSION_MISMATCH, "and the refusal carries its own code (ADR-0124 §6)"


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    ``tests/wire/test_closed_loop_protocol_version.py``'s helper, and for its reason: a
    phrase asserted across a line break is a test that fails on ``ruff format``
    rewrapping a paragraph.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)

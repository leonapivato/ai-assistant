"""``PROTOCOL_VERSION`` moved for the goal's interpretation, and the log says why.

ADR-0249 §12 asks that the constant "moves by exactly one, in the same change that
makes a wire-carried value one peer emits invalid for the other", and that
``wire/envelope.py``'s log gain an entry naming this ADR and the reason.
``tests/wire/test_closed_loop_protocol_version.py`` is this file's precedent and it is
written to its shape.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.core.types import (
    ActionPlan,
    ConversationExport,
    Goal,
    ParkedRead,
    PlanExport,
    TurnResult,
)
from ai_assistant.wire import client, envelope, server

#: The version ADR-0249's L1 moves to, and the one it moves from.
_MOVED_TO: Final = 38
_MOVED_FROM: Final = 37


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§12: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0249 — the failure ``CONTRIBUTING.md`` → "No state claims
    in living documents" is about. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_names_this_decision_and_all_three_of_its_grounds() -> None:
    """§12: "three changes of this decision are each independently that ground".

    The entry has to name all three, because the singular bump is a property of §15's
    lane cut and not of only one value having moved: a reader who saw one ground named
    would have no way to tell a considered cut from an overlooked value.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0249 §12**" in entry
    assert "Goal" in entry, "the first ground: required fields, and statement out of the dump"
    assert "targets_revision" in entry, "the second"
    assert "GoalBrief" in entry, "the third: TurnResult.goal changes type"
    assert "ADR-0124 §9" in entry, "the rule the three are read under"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_records_what_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    ADR-0249 changes two Protocols and three stored-record versions, and none of them
    is a ground for this bump: ``Planner`` and ``PlanStore`` are on neither promoted
    surface, ``ParkedRead`` is a store record no peer emits, and ``PlanExport`` crosses
    no frame (§12).
    """
    entry = _entry_for(_MOVED_TO)

    assert "fifty-eight" in entry
    assert "thirty-one" in entry
    assert "ParkedRead" in entry, "the store record that is not a fourth ground"
    assert "PlanExport" in entry, "the stored-record version that is not a second wire one"
    assert "no compatibility shim" in entry.lower(), "ADR-0084 §3 is the mechanism (§12)"


def test_each_of_the_three_grounds_is_true_of_the_types_themselves() -> None:
    """The entry's three claims, checked against the models rather than the prose.

    ``wire/codec.py`` renders a model by ``model_dump()`` and all three set
    ``extra="forbid"``, so each of these on its own makes a hub's turn undecodable by a
    client at the previous version.
    """
    assert "interpretation" in Goal.model_fields, "a required field an older reader has none for"
    assert "statement" not in Goal.model_fields, "and one it expects that is no longer emitted"
    assert "targets_revision" in ActionPlan.model_fields
    assert TurnResult.model_fields["goal"].annotation is not Goal
    for model in (Goal, ActionPlan, TurnResult):
        assert model.model_config.get("extra") == "forbid"


def test_the_two_halves_of_the_handshake_name_both_versions_when_they_disagree() -> None:
    """§12: ADR-0084 §3's exact-match handshake, and the refusal names both versions.

    "No lane adds a compatibility shim, an optional-member negotiation, a per-member
    capability flag or a lenient decode to let two versions interoperate" — so a peer
    at 37 and a peer at 38 do not interoperate, and what they do instead is say so.
    The refusal is one comparison on each side, and each message is read here for both
    numerals: a message naming only its own version leaves an operator unable to tell
    which half is behind.
    """
    for source in (inspect.getsource(server), inspect.getsource(client)):
        assert "!= env.PROTOCOL_VERSION" in source, "an exact match, never a range"
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(server)
    assert "version {version}" in inspect.getsource(server)
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(client)
    assert "version {version}" in inspect.getsource(client)
    assert envelope.VERSION_MISMATCH, "and the refusal carries its own code (ADR-0124 §6)"


def test_the_stored_record_versions_moved_and_the_conversation_export_did_not() -> None:
    """§12: two store markers and one document version move; the third stays put.

    ``PlanExport`` is a stored-record version rather than a second wire ground — it
    crosses no frame and is emitted by no peer — and ``ConversationExport`` is
    untouched, so ADR-0212 §8 stands.
    """
    from ai_assistant.permissions.parked_reads import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PARKED_SCHEMA,
    )
    from ai_assistant.planning.sqlite_store import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PLAN_SCHEMA,
    )

    assert PlanExport.model_fields["schema_version"].default >= 8, (
        "ADR-0249 §12 moved it to 8; a later decision moving it again is not a violation "
        "of this one, and the absolute figure has its home in tests/core/test_planning_types.py"
    )
    assert _PLAN_SCHEMA == 2, "this store's first migration (ADR-0049 §1, ADR-0249 §12)"
    assert _PARKED_SCHEMA == 3
    assert ConversationExport.model_fields["schema_version"].default == 2
    assert "goal_id" in ParkedRead.model_fields, "and the record gained its identifier"


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

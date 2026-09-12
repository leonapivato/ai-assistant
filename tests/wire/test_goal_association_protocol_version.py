"""``PROTOCOL_VERSION`` moved for the goal-association contract, and the log says why.

ADR-0250 §19 states the move up front — "**M1 moves ``PROTOCOL_VERSION``, the plan
store's ``schema_version`` and ``PlanExport.schema_version``, and it is the only lane
that moves any of them**" — and gives the reason the four grounds ride one lane:
"splitting them across lanes would leave two peers passing the exact-match handshake
and then failing to decode a turn — the failure ADR-0124 §9 exists to prevent".
``tests/wire/test_read_outcome_protocol_version.py`` is this file's precedent and it is
written to its shape.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import (
    Clarification,
    ClarificationWithdrawal,
    ConversationExport,
    Goal,
    GoalAbandonment,
    GoalDisambiguation,
    GoalEngagement,
    GoalQuestion,
    GoalSummary,
    PlanExport,
    ReferenceOutcome,
    TurnOutcome,
    TurnReference,
)
from ai_assistant.wire import client, envelope, server, surface

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The version ADR-0250's M1 moves to, and the one it moves from.
_MOVED_TO: Final = 40
_MOVED_FROM: Final = 39

#: The four members §5 puts on ``TurnOutcome``, which is the first of the four grounds.
_OUTCOME_MEMBERS: Final = ("goal_engagement", "clarification", "reference", "disambiguation")

#: The three operations §§12 and 15 promote.
_OPERATIONS: Final = ("goals", "withdraw_clarification", "abandon_goal")


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§19: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0250 — the failure ``CONTRIBUTING.md`` → "No state claims
    in living documents" is about. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_names_this_decision_and_each_of_its_four_grounds() -> None:
    """§19: four grounds at once, and the entry names each.

    Where ADR-0251's entry had exactly one and said so, this one has four — and
    enumerating them is what tells a later reader that no single one of them is the
    bump's whole reason, so removing any one from this lane would not make the move
    unnecessary.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0250 §19**" in entry
    assert "TurnOutcome" in entry, "the outcome that gained four members"
    assert "last_engaged_in" in entry, "the Goal field that rides TurnResult"
    assert "reference" in entry, "converse's new keyword"
    for operation in _OPERATIONS:
        assert operation in entry, f"the promoted operation {operation}"
    assert "ADR-0124 §9" in entry, "the rule it is read under"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_records_what_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    Two stored-record versions move with this lane and neither is a wire ground; the
    parked-read store's does not move at all, because ADR-0250 §17 leaves ADR-0244 §3
    untouched.
    """
    entry = _entry_for(_MOVED_TO)

    assert "sixty-one" in entry
    assert "thirty-three" in entry
    assert "PlanExport" in entry, "the document version that is not a second wire one"
    assert "goal_questions" in entry, "the store migration that is not one either"
    assert "parked-read store" in entry, "and the marker that does not move at all"
    assert "ConversationExport" in entry
    assert "no compatibility shim" in entry.lower(), "ADR-0084 §3 is the mechanism"


def test_each_ground_is_true_of_the_types_and_the_surface_themselves() -> None:
    """The entry's four claims, checked against the tree rather than the prose.

    ``wire/codec.py`` renders a model by ``model_dump()`` and both models set
    ``extra="forbid"``, so the four new members on every turn a hub sends and the new
    field on every goal are what make a turn undecodable by a client at 39 — and a
    method a hub at 39 does not have is an unknown method to it.
    """
    for member in _OUTCOME_MEMBERS:
        assert member in TurnOutcome.model_fields
    assert "last_engaged_in" in Goal.model_fields
    for model in (TurnOutcome, Goal):
        assert model.model_config.get("extra") == "forbid"

    dumped = TurnOutcome(turn=None, step=None).model_dump()
    for member in _OUTCOME_MEMBERS:
        assert member in dumped, "emitted on every outcome, not only a populated one"

    for method in ("converse", "converse_streaming"):
        assert "reference" in surface.parameters(method)
    assert set(_OPERATIONS) <= surface.METHODS


def test_a_peer_at_the_previous_version_and_one_at_this_refuse_each_other() -> None:
    """§19: ADR-0084 §3's exact-match handshake, and the refusal names both versions.

    No lane adds a compatibility shim, an optional-member negotiation, a per-member
    capability flag or a lenient decode to let two versions interoperate — so a peer at
    39 and a peer at 40 do not interoperate, and what they do instead is say so. The
    refusal is one comparison on each side, and each message is read here for **both**
    numerals: a message naming only its own version leaves an operator unable to tell
    which half is behind.

    **It is the whole reason the four grounds ride one lane.** Two peers that passed a
    handshake and then failed to decode a turn is the state §19 splits nothing across
    lanes to avoid, and this is the mechanism that makes the mismatch legible instead.
    """
    for source in (inspect.getsource(server), inspect.getsource(client)):
        assert "!= env.PROTOCOL_VERSION" in source, "an exact match, never a range"
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(server)
    assert "version {version}" in inspect.getsource(server)
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(client)
    assert "version {version}" in inspect.getsource(client)
    assert envelope.VERSION_MISMATCH, "and the refusal carries its own code (ADR-0124 §6)"


def test_the_stored_record_versions_moved_and_the_others_did_not() -> None:
    """§9, §19: two store markers move with this lane, and two do not.

    ``PlanExport`` is a stored-record version rather than a second wire ground — it
    crosses no frame and is emitted by no peer — the plan store's own marker takes its
    **second** migration, and the parked-read store's and ``ConversationExport``'s are
    untouched, so ADR-0244 §3 and ADR-0212 §8 both stand.

    Every figure is a **floor**, for the reason the move above is: a later decision
    moving any of them again is not a violation of this one, and the absolute figures
    have one home each.
    """
    from ai_assistant.permissions.parked_reads import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PARKED_SCHEMA,
    )
    from ai_assistant.planning.sqlite_store import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PLAN_SCHEMA,
    )

    assert PlanExport.model_fields["schema_version"].default >= 10
    assert _PLAN_SCHEMA >= 3, "this store's second migration (ADR-0250 §9)"
    assert _PARKED_SCHEMA == 3, "ADR-0250 §17 leaves ADR-0244 §3 untouched"
    assert ConversationExport.model_fields["schema_version"].default == 2


def test_the_records_the_seams_hold_reach_no_promoted_surface() -> None:
    """§19: what M1 lands in ``core`` and deliberately does not promote.

    ``GoalQuestion`` is ``PlanStore``'s record and reaches a client only as the
    :class:`Clarification` §10 assembles from it — the id, the text and the deadline,
    and nothing else. Asserted where it could stop being true: no field of any promoted
    model is annotated with the record itself, so a lane that put one on
    ``TurnOutcome`` fails here and has to read ADR-0250 §10 rather than discover it in
    review.
    """
    promoted = (
        TurnOutcome,
        GoalEngagement,
        GoalDisambiguation,
        GoalSummary,
        Clarification,
        TurnReference,
    )
    carrying = [
        f"{model.__name__}.{field}"
        for model in promoted
        for field, info in model.model_fields.items()
        if info.annotation in {GoalQuestion, GoalQuestion | None}
    ]

    assert carrying == [], "the record is the store's; a surface is handed a Clarification"


def test_the_three_operations_are_on_the_protocol_and_reach_the_wire() -> None:
    """§§12, 15: three operations, promoted by being ``AssistantEngine`` members.

    ADR-0130 §9's own reading — "These are contract surface, because
    ``AssistantEngine`` is a Protocol in ``core/protocols.py``" — so the walk that
    reaches them is ``wire/surface.py``'s derivation rather than a table anyone kept in
    step. Each returns a value ``core`` declares, which is ADR-0085 §5's closed graph.
    """
    for operation in _OPERATIONS:
        assert hasattr(AssistantEngine, operation)
        assert operation in surface.METHODS
        assert operation not in surface.STREAMING_METHODS
    assert surface.positional_only("withdraw_clarification") == ("question_id",)
    assert surface.positional_only("abandon_goal") == ("goal_id",)
    assert surface.parameters("goals") == ("limit", "offset")
    assert {
        ClarificationWithdrawal.WITHDRAWN,
        ClarificationWithdrawal.NOTHING_TO_WITHDRAW,
    } == set(ClarificationWithdrawal)
    assert {
        GoalAbandonment.ABANDONED,
        GoalAbandonment.ALREADY_CLOSED,
        GoalAbandonment.NO_SUCH_GOAL,
    } == set(GoalAbandonment)
    assert len(set(ReferenceOutcome)) == 4


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

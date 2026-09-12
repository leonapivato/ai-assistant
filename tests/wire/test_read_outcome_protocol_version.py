"""``PROTOCOL_VERSION`` moved for the attempt's kind, and the log says why.

ADR-0251 §16 states the move up front — "``AttemptEffort`` gains a field and it is
reachable through ``GoalAttempt`` on the wire and in ``PlanExport``, so L1 moves
``PROTOCOL_VERSION`` from 38 and ``PlanExport.schema_version`` from 8" — under ADR-0124
§9's rule that the bump rides the change that makes a peer's value invalid.
``tests/wire/test_goal_interpretation_protocol_version.py`` is this file's precedent and
it is written to its shape.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Final

from ai_assistant.core.types import (
    AttemptEffort,
    AttemptKind,
    ConversationExport,
    GoalAttempt,
    PlanExport,
    ReadAskOutcome,
    ReadOutcomeKind,
)
from ai_assistant.wire import client, envelope, server

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: The version ADR-0251's L1 moves to, and the one it moves from.
_MOVED_TO: Final = 39
_MOVED_FROM: Final = 38


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§16: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look like
    a violation of ADR-0251 — the failure ``CONTRIBUTING.md`` → "No state claims in
    living documents" is about. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_names_this_decision_and_its_one_ground() -> None:
    """§16: one ground, and the entry says it is one.

    Where ADR-0249's entry had to name three because §15's lane cut made the singular
    bump a property of the cut, this one has exactly one — and saying so is what tells a
    later reader that the other two values this decision mints were **considered** and
    are not wire grounds, rather than overlooked.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0251 §16**" in entry
    assert "AttemptEffort" in entry, "the type that gained the member"
    assert "kind" in entry, "and the member"
    assert "GoalAttempt" in entry, "the promoted-surface value it rides"
    assert "ADR-0124 §9" in entry, "the rule it is read under"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_records_what_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    ADR-0251's L1 mints two further types and changes a Protocol, and none of them is a
    ground for this bump: ``ReadOutcomeKind`` and the outcome model exist only as an
    in-process argument to ``Planner.plan``, and ``Planner`` is on neither promoted
    surface. The plan store's own ``schema_version`` does not move either, and the entry
    says why — a version 2 ``attempts`` row decodes under this contract unchanged.
    """
    entry = _entry_for(_MOVED_TO)

    assert "fifty-eight" in entry
    assert "thirty-one" in entry
    assert "ReadOutcomeKind" in entry, "the vocabulary that is not a second ground"
    assert "Planner" in entry, "the Protocol that is not a wire surface"
    assert "PlanExport" in entry, "the stored-record version that is not a second wire one"
    assert "no compatibility shim" in entry.lower(), "ADR-0084 §3 is the mechanism"


def test_the_ground_is_true_of_the_types_themselves() -> None:
    """The entry's claim, checked against the models rather than the prose.

    ``wire/codec.py`` renders a model by ``model_dump()`` and both set
    ``extra="forbid"``, so the new member on every attempt a hub sends is what makes a
    turn undecodable by a client at the previous version.
    """
    assert "kind" in AttemptEffort.model_fields
    assert AttemptEffort.model_fields["kind"].annotation == AttemptKind | None
    assert GoalAttempt.model_fields["effort"].annotation is AttemptEffort
    for model in (AttemptEffort, GoalAttempt):
        assert model.model_config.get("extra") == "forbid"
    dumped = GoalAttempt(
        id="a1",
        goal_id="g1",
        opened_at=_WHEN,
        effort=AttemptEffort(kind=AttemptKind.SPOKEN),
    ).model_dump()
    assert dumped["effort"]["kind"] == "spoken", "emitted on every attempt, not only a set one"


def test_the_new_vocabularies_reach_no_wire_carried_field() -> None:
    """§16: "``ReadOutcomeKind`` and ``ReadAskOutcome`` are not a second ground".

    Both exist only as an argument to ``Planner.plan``. Asserted where it could stop
    being true: no field of any model in ``core.types`` is annotated with either, so a
    later lane putting one on a wire-carried record fails here and has to read ADR-0124
    §9 rather than discover it in review.
    """
    from ai_assistant.core import types  # noqa: PLC0415 — the module is the subject

    carrying = [
        f"{name}.{field}"
        for name, model in vars(types).items()
        if isinstance(model, type) and hasattr(model, "model_fields")
        for field, info in model.model_fields.items()
        if info.annotation in {ReadOutcomeKind, ReadAskOutcome} and model is not ReadAskOutcome
    ]

    assert carrying == [], "the carrier is an in-process argument and lives on no record"


def test_the_two_halves_of_the_handshake_name_both_versions_when_they_disagree() -> None:
    """§16: ADR-0084 §3's exact-match handshake, and the refusal names both versions.

    No lane adds a compatibility shim, an optional-member negotiation, a per-member
    capability flag or a lenient decode to let two versions interoperate — so a peer at
    38 and a peer at 39 do not interoperate, and what they do instead is say so. The
    refusal is one comparison on each side, and each message is read here for **both**
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


def test_the_document_version_moved_and_the_two_store_markers_did_not() -> None:
    """§16: one stored-record version moves, and it is not one of this wire's.

    ``PlanExport`` carries ``tuple[GoalAttempt, ...]`` and every attempt in it now emits
    ``kind``. The **plan store's** own marker did not move *for this decision*: ADR-0249
    §12 moved it 1 → 2 because a version 1 ``goals`` row "no longer decodes", and a
    version 2 ``attempts`` row decodes under this contract unchanged — ``kind`` defaults
    to ``None``, which is what makes no migration owed rather than merely convenient.

    **The two figures are floors rather than equalities**, and that is what keeps this
    a statement about ADR-0251 rather than about whatever landed after it: a later
    decision that moves either marker has not falsified anything this one claimed, and
    would falsify an equality (`CONTRIBUTING.md` -> "No state claims in living
    documents"). The absolute figures have exactly one home each.
    """
    from ai_assistant.permissions.parked_reads import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PARKED_SCHEMA,
    )
    from ai_assistant.planning.sqlite_store import (  # noqa: PLC0415 — asserted about
        _SCHEMA_VERSION as _PLAN_SCHEMA,
    )

    assert PlanExport.model_fields["schema_version"].default >= 9, (
        "ADR-0251 §16 moved it to 9; a later decision moving it again is not a "
        "violation of this one, and the absolute figure has its home in "
        "tests/core/test_planning_types.py"
    )
    assert _PLAN_SCHEMA >= 2, (
        "a version 2 attempts row decodes under *this* contract, which is why "
        "ADR-0251 owed no migration; a later decision owing one is not a violation of "
        "that, and the absolute figure lives in tests/planning/test_sqlite_plan_store.py"
    )
    assert _PARKED_SCHEMA == 3
    assert ConversationExport.model_fields["schema_version"].default == 2


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

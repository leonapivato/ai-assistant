"""``PROTOCOL_VERSION`` moved for the plan's shape, and the log says why (ADR-0253 §10).

§10 states the move up front — "``PROTOCOL_VERSION`` moves by exactly one, in the same
change that makes a wire-carried value one peer emits invalid for the other" — and §12
cuts the lanes "so that exactly one satisfies it, which is what makes the bump singular
rather than a property of the cut". ``tests/wire/test_goal_association_protocol_version.py``
is this file's precedent and it is written to its shape.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.core.types import (
    ActionPlan,
    BriefElement,
    GoalBrief,
    PlanExport,
    PlanStep,
    TurnResult,
)
from ai_assistant.wire import client, envelope, server

#: The version ADR-0253's L1 moves to, and the one it moves from.
_MOVED_TO: Final = 41
_MOVED_FROM: Final = 40

#: The five members §§1, 4, 5 and 6 put on ``PlanStep``, which with ``ActionPlan``'s one
#: is the whole of the ground.
_STEP_MEMBERS: Final = ("depends_on", "resolves", "when", "verifies", "evidence_recency")


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    ``tests/wire/test_goal_association_protocol_version.py``'s helper, and for its
    reason: a phrase asserted across a line break is a test that fails on ``ruff
    format`` rewrapping a paragraph.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split(f"#: **{version - 1} since")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§10: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0253 — the failure ``CONTRIBUTING.md`` → "No state claims
    in living documents" is about. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_it_moved_by_exactly_one_and_the_log_is_appended_to() -> None:
    """§10: "moves by **exactly one**", and §12's "and it moves it once".

    The entry this move follows still stands, which is what makes the block a log
    rather than a statement of the current version: "the log is appended to and never
    rewritten".
    """
    assert _MOVED_TO - _MOVED_FROM == 1
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope)


def test_the_log_names_this_decision_and_the_one_ground_it_rests_on() -> None:
    """§10: one ground, named — ``PlanStep``'s five fields and ``ActionPlan``'s one.

    Where ADR-0250's entry had four grounds and enumerated each, this one has a single
    ground and says so, because a reader who thought ``GoalElement``'s two fields were
    a second would look for a wire surface that does not exist.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0253 §10**" in entry
    assert "ADR-0124 §9" in entry, "the rule it is read under"
    for member in _STEP_MEMBERS:
        assert member in entry, f"the PlanStep member {member}"
    assert "interpretations" in entry, "the ActionPlan member"
    assert "TurnResult" in entry, "how a plan reaches a peer"
    assert "TurnOutcome" in entry, "and what carries it there"
    assert "no compatibility shim" in entry.lower(), "ADR-0084 §3 is the mechanism"


def test_the_entry_records_what_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, and §10's own list of near-grounds it declines.

    ``GoalElement`` gaining two fields "is not a second wire ground", ``GoalEvidence``
    gaining ``interpreted_output`` moves no wire version of its own (ADR-0252 §12), the
    method set does not move, and the **plan store's** ``schema_version`` does not move
    either — the one version that does is ``PlanExport``'s, which is a stored-record
    version and not a peer's.
    """
    entry = _entry_for(_MOVED_TO)

    assert "GoalElement" in entry, "the element that gained two fields"
    assert "not a second" in entry, "and the entry declining it as a ground"
    assert "GoalEvidence" in entry, "and the row's own widening, declined as a ground"
    assert "sixty-one" in entry, "the promoted method set, which does not move"
    assert "PlanExport" in entry, "the document version that is not a second wire one"
    assert "plan store's own" in entry, "the store version named"
    assert "stays at 4" in entry, "and named as not moving"
    assert "no migration is owed" in entry
    assert "parked-read store" in entry, "and the marker that does not move at all"
    assert "ConversationExport" in entry


def test_the_ground_is_true_of_the_types_themselves() -> None:
    """The entry's claim, checked against the tree rather than the prose.

    ``wire/codec.py`` renders a model by ``model_dump()`` and all three models set
    ``extra="forbid"``, so the six new members on every plan a hub sends are what make
    a turn undecodable by a client at 40. **A defaulted member is still a shape
    change**: the arm dumps a plan that declares none of them and finds all six.
    """
    for member in _STEP_MEMBERS:
        assert member in PlanStep.model_fields
    assert "interpretations" in ActionPlan.model_fields
    for model in (PlanStep, ActionPlan, TurnResult):
        assert model.model_config.get("extra") == "forbid"

    plain = PlanStep(id="s1", intent="do it", capability="cap")
    dumped = plain.model_dump()
    for member in _STEP_MEMBERS:
        assert member in dumped, "emitted on every step, not only a declaring one"


def test_the_brief_the_planner_sees_gains_nothing() -> None:
    """§10: "``GoalBrief`` and ``BriefElement`` gain nothing".

    The brief carries an element's text and the **kind** of its ground and nothing
    else; it does not carry an element's ``id``, its ``applicability``, or any
    reference, and a planner names an element by its ``D`` label (ADR-0249 §9) — "which
    is what makes the resolvable set exactly what the loop chose to render". Whether a
    brief ever renders an applicability is **not decided** and is fired by a measured
    planner failure (§11).
    """
    assert set(BriefElement.model_fields) == {"text", "ground"}
    for absent in ("id", "applicability", "conditions_ids"):
        assert absent not in BriefElement.model_fields
    assert "revision" not in GoalBrief.model_fields, "ADR-0249 §8's own containment"


def test_the_stored_record_version_moved_by_exactly_one_too() -> None:
    """§10: "``PlanExport.schema_version`` moves by exactly one", on ADR-0039 §10.

    Asserted as a move, for the reason the protocol arm above is. The absolute figure
    has one home, ``tests/core/test_planning_types.py``'s pin.
    """
    assert PlanExport.model_fields["schema_version"].default >= 12


def test_a_peer_at_the_previous_version_and_one_at_this_refuse_each_other() -> None:
    """§10: ADR-0084 §3's exact-match handshake, "and the refusal naming both versions
    is the intended user-visible outcome".

    No lane adds a compatibility shim, an optional-member negotiation, a per-member
    capability flag or a lenient decode, so a peer at 40 and a peer at 41 do not
    interoperate and what they do instead is say so.
    """
    for source in (inspect.getsource(server), inspect.getsource(client)):
        assert "!= env.PROTOCOL_VERSION" in source, "an exact match, never a range"
    assert "version {env.PROTOCOL_VERSION}" in inspect.getsource(server)
    assert "version {version}" in inspect.getsource(server)

"""ADR-0251 §2, §3 and §5 at the types: the vocabularies, the carrier and the ledger.

The seam-shaped half of §16's L1 arms. What lives here is what a reader can check
against the models themselves — that :class:`ReadOutcomeKind` is closed at seven and
valued as the ADR spells it, that the outcome model carries exactly two fields and
refuses a third, that :class:`AttemptKind` is closed at two, and that
:class:`AttemptEffort` gained one member and kept everything ADR-0249 §5 fixed. The
classifier's arms are turn-shaped and live in
``tests/orchestration/test_read_outcomes.py``, because what they assert happens at the
servicing site and reaches the planner.

**The name is this lane's, and it is recorded here rather than left to a reader to
notice** (issue #2281). ADR-0251 §3 mints ``ReadOutcome``; ``core/types.py`` has held
that name since ADR-0185 §1 for the permission trail's record of how a gated source
read ended. The two are different facts, so this lane spells the new one
``ReadAskOutcome`` and leaves the old one where it stands — asserted below, so a later
lane that "tidied" one into the other would fail here rather than in production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    AttemptEffort,
    AttemptKind,
    GoalAttempt,
    ReadAsk,
    ReadAskOutcome,
    ReadKind,
    ReadOutcome,
    ReadOutcomeKind,
    StructuredAsk,
    TimeWindow,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)

#: One ask of each kind, so an arm over the carrier is not written about one shape.
_ASKS = (
    ReadAsk(kind=ReadKind.WEB_SEARCH),
    ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="the boiler"),
    ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),
    ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"),
    ReadAsk(
        kind=ReadKind.STRUCTURED_READ,
        structure=StructuredAsk(window=TimeWindow(start=_WHEN)),
    ),
)


# --- §2: ReadOutcomeKind ------------------------------------------------------


def test_the_vocabulary_is_closed_at_exactly_seven_members_in_the_order_stated() -> None:
    """§2: "closed at exactly seven members", each valued by its lower-cased name.

    The membership is asserted as an **equality** rather than a superset, because §2's
    whole claim is closure: "no implementation, setting or later lane adds an eighth
    without the ADR that decides it". A superset assertion would pass on the eighth.
    """
    assert [member.value for member in ReadOutcomeKind] == [
        "returned_records",
        "empty",
        "duplicate",
        "truncated",
        "refused",
        "failed",
        "expired",
    ]
    for member in ReadOutcomeKind:
        assert member.value == member.name.lower(), "valued by lower-cased member name"


def test_an_expiry_is_its_own_member_and_is_not_a_failure() -> None:
    """§2: "``EXPIRED`` is its own member and is not folded into ``FAILED``".

    ADR-0241 §4 made an expiry *an outcome of its own* rather than a failure, and this
    vocabulary keeps that distinction at the seam where it can be acted on. A lane that
    aliased one to the other would undo a ratified distinction one seam over — and the
    identity form of that check is one ``mypy`` rejects as statically impossible, which
    is a stronger guarantee than an assertion — and so, it turns out, is the value form,
    which ``mypy`` also refuses over two ``Literal`` strings. So what is asserted is the
    property those two forms are each one instance of: **no two members share a value**,
    which is what makes none of the seven an alias for another and which a lane folding
    the expiry into the failure would break.
    """
    assert len({member.value for member in ReadOutcomeKind}) == len(ReadOutcomeKind)
    assert {"expired", "failed"} <= {member.value for member in ReadOutcomeKind}


def test_no_member_carries_a_ground_a_figure_or_a_field_name() -> None:
    """§2: ADR-0242 §9's bar, held over the vocabulary's own spelling.

    "No member carries a message, a ground, a provider name, a query, a destination, a
    monetary figure, a duration, a count or a ``Settings`` field name." A ``StrEnum``
    member's whole content is its value, so the check is that each value is a bare
    lower-cased word or two and carries no digit, no currency mark and no separator a
    structured payload would need.
    """
    for member in ReadOutcomeKind:
        assert member.value.replace("_", "").isalpha(), f"{member.value} carries no figure"
        for forbidden in ("$", ":", "=", ".", "/", "settings"):
            assert forbidden not in member.value


def test_it_is_a_different_type_from_the_gated_reads_outcome() -> None:
    """#2281: the two names, kept apart deliberately.

    :class:`ReadOutcome` (ADR-0185 §1) records how one **gated source read** ended, for
    the permission trail; :class:`ReadOutcomeKind` records what became of one **ask a
    planner composed**. Neither is derivable from the other, and no value of one is a
    value of the other — asserted so that a later lane merging them has to argue with a
    test rather than with a docstring.
    """
    assert not issubclass(ReadOutcomeKind, ReadOutcome)
    assert not issubclass(ReadOutcome, ReadOutcomeKind)
    # **The overlap is exactly two words, and it is the hazard rather than the
    # reassurance.** Both are ``StrEnum``s, so ``ReadOutcomeKind.REFUSED ==
    # ReadOutcome.REFUSED`` is ``True`` at run time and a ``set`` membership test cannot
    # tell them apart — which is precisely why this lane declined to shadow the name
    # (#2281): a gated read ``REFUSED`` says the grant check answered ``None`` and
    # nothing was opened (ADR-0097 §5), where an ask ``REFUSED`` says a source decided
    # not to answer on a ground it owns (ADR-0251 §2). Two facts one ``==`` conflates
    # silently, and the annotation is the only thing that keeps them apart.
    assert {member.value for member in ReadOutcome} & {
        member.value for member in ReadOutcomeKind
    } == {"refused", "failed"}


# --- §3: the carrier's member -------------------------------------------------


def test_it_carries_exactly_two_fields_and_refuses_a_third() -> None:
    """§3: "a frozen model with ``extra="forbid"`` carrying exactly two fields".

    "It carries nothing else" — so a lane adding a message, a count, an instant of the
    read or a ``capped`` value fails here. That is the clause that makes ADR-0240 §7's
    "nothing the store said crosses on it" a property of the **type** rather than a
    rule a caller is trusted to keep.
    """
    assert set(ReadAskOutcome.model_fields) == {"ask", "outcome"}
    assert ReadAskOutcome.model_config.get("extra") == "forbid"
    assert ReadAskOutcome.model_config.get("frozen") is True
    with pytest.raises(ValidationError):
        ReadAskOutcome(
            ask=_ASKS[0],
            outcome=ReadOutcomeKind.EMPTY,
            reason="the provider was busy",  # type: ignore[call-arg]
        )


def test_it_is_frozen_so_the_ask_cannot_be_edited_on_the_way() -> None:
    """§3: "the ask is carried back unaltered and is never edited on the way".

    ADR-0240 §7, verbatim over the wider carrier: "No implementation widens a window,
    drops an axis, rewrites a label or composes a suggested ask to put in its place."
    A frozen model is what makes the clause mechanical at this seam.
    """
    carried = ReadAskOutcome(ask=_ASKS[4], outcome=ReadOutcomeKind.EMPTY)
    with pytest.raises(ValidationError):
        carried.ask = _ASKS[1]
    with pytest.raises(ValidationError):
        carried.outcome = ReadOutcomeKind.REFUSED


def test_every_kind_of_ask_and_every_member_compose() -> None:
    """§3: the carrier takes one entry per ask **of any kind**, not a structured one.

    ADR-0240 §6 admitted only an empty ``STRUCTURED_READ``; §3 widens the range and
    narrows nothing, so every pair of a kind and a member is a value this type admits —
    thirty-five of them, driven rather than argued.
    """
    for ask in _ASKS:
        for member in ReadOutcomeKind:
            carried = ReadAskOutcome(ask=ask, outcome=member)
            assert carried.ask is ask, "carried back byte for byte, never rebuilt"
            assert carried.outcome is member


def test_the_ask_is_carried_as_the_model_and_never_as_its_projection() -> None:
    """§3: ``ask`` is a :class:`ReadAsk`, so the block's renderer sees the whole ask."""
    assert ReadAskOutcome.model_fields["ask"].annotation is ReadAsk
    assert ReadAskOutcome.model_fields["outcome"].annotation is ReadOutcomeKind


# --- §5: AttemptKind and the ledger's new member ------------------------------


def test_the_attempt_kind_is_closed_at_exactly_two_members() -> None:
    """§5: "a ``StrEnum`` valued by lower-cased member name and closed at exactly two".

    ``SPOKEN``'s **absence from the allowance mapping** is itself a decision (§5), and
    that mapping is L2's; what is fixed here is that the vocabulary has a member for it
    to be absent under, so a later lane cannot read "no member" as "no decision".
    """
    assert [member.value for member in AttemptKind] == ["conversational", "spoken"]
    for member in AttemptKind:
        assert member.value == member.name.lower()


def test_the_ledger_gained_exactly_one_member_and_kept_the_other_two() -> None:
    """§5: "``AttemptEffort`` gains exactly one further member", under ADR-0249 §5's licence.

    "``AttemptEffort``'s other two fields, their types, their ``ge=0`` bounds and their
    monotonicity are ADR-0249 §5's and are unchanged", and "``GoalAttempt``'s field
    enumeration is not touched, and no field is added to it".
    """
    assert set(AttemptEffort.model_fields) == {"planner_calls", "working", "kind"}
    assert AttemptEffort.model_config.get("extra") == "forbid"
    assert AttemptEffort.model_config.get("frozen") is True
    assert "kind" not in GoalAttempt.model_fields, "the licence is the ledger's, not the attempt's"
    with pytest.raises(ValidationError):
        AttemptEffort(planner_calls=-1)
    with pytest.raises(ValidationError):
        AttemptEffort(working=timedelta(seconds=-1))


def test_the_kind_defaults_to_none_which_means_the_opening_turn_named_no_operation() -> None:
    """§5: ``None`` means "the turn that opened this attempt declared no operation".

    It is also what a row written before this decision decodes to, which is the reason
    no migration is owed: a stored attempt whose JSON carries no ``kind`` validates and
    reads as a turn that named no operation, which is what it was.
    """
    assert AttemptEffort().kind is None
    assert AttemptEffort.model_fields["kind"].default is None
    decoded = AttemptEffort.model_validate({"planner_calls": 2, "working": "PT30S"})
    assert decoded.kind is None, "a pre-ADR-0251 ledger decodes without a migration"
    assert decoded.planner_calls == 2


def test_the_ledger_carries_no_figure_of_any_allowance() -> None:
    """§5: "what crosses the seam is the kind, never a figure".

    ADR-0228 §4's construction one level up: "a ``timedelta`` or an ``int`` limit stored
    beside the consumed figure would be *a figure a caller can contradict*". So the
    model has a member for **which** allowance and none for what it is, and a lane
    adding ``planner_call_allowance`` or ``reserve`` fails here.
    """
    assert set(AttemptEffort.model_fields) == {"planner_calls", "working", "kind"}
    assert AttemptEffort.model_fields["kind"].annotation == AttemptKind | None


def test_the_kind_survives_a_round_trip_through_the_attempt_it_rides() -> None:
    """§5, ADR-0251 §16: the member is reachable through ``GoalAttempt``, so it is dumped.

    This is the fact ADR-0124 §9's second limb is read against for
    ``PROTOCOL_VERSION``'s move: ``model_dump()`` emits ``kind`` on **every** attempt a
    peer sends, and a reader at the previous version refuses it with
    ``extra_forbidden``.
    """
    attempt = GoalAttempt(
        id="a1",
        goal_id="g1",
        opened_at=_WHEN,
        effort=AttemptEffort(planner_calls=1, kind=AttemptKind.CONVERSATIONAL),
    )

    dumped = attempt.model_dump()

    assert dumped["effort"]["kind"] == "conversational"
    assert GoalAttempt.model_validate_json(attempt.model_dump_json()) == attempt

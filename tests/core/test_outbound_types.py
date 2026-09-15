"""ADR-0264 §13 item 6: ``OutboundStatement``'s own construction invariants.

**Asserted on the model and not on its producer**, which is what §13 item 6 asks for
in terms: "because it is a boundary-crossing value a wire decode also builds". A rule
stated only at the assembly site in ``orchestration`` is a rule a decoded frame is not
held to, and ``TurnOutcome`` crosses the promoted surface on every turn call.

The vocabularies' closures are here too, for the reason ADR-0242 §13 gives for its own:
a member added without the ADR that decides it is exactly what §4 and §5 forbid, and a
test over the enumeration itself is what makes that checkable rather than asserted.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import OutboundDestination, OutboundReach, OutboundStatement

# --- the two vocabularies, closed where their sections close them ------------


def test_the_reach_vocabulary_is_closed_at_three_members_spelled_by_name() -> None:
    """ADR-0264 §4: exactly three, each valued by its lower-cased member name.

    "``OutboundReach``, a ``StrEnum`` valued by lower-cased member name and **closed at
    exactly three members** — ``REACHED``, ``NOT_REACHED`` and ``INDETERMINATE`` — which
    are §2's three groups folded to the turn and nothing else. The vocabulary is added to
    and never renamed, and no fourth member arrives without its ADR."

    **The value spelling is load-bearing rather than cosmetic**: the member crosses the
    wire inside a ``TurnOutcome`` and ``project`` renders every ``Enum`` as its
    ``value``, so a renamed value is a value an older peer cannot read.
    """
    assert [one.name for one in OutboundReach] == ["REACHED", "NOT_REACHED", "INDETERMINATE"]
    assert [one.value for one in OutboundReach] == ["reached", "not_reached", "indeterminate"]


def test_the_destination_vocabulary_is_closed_at_two_members() -> None:
    """ADR-0264 §5 as ADR-0260 §10 amends it: two, in declaration order.

    ADR-0264 §5 closed the vocabulary at one member and required in terms that "a later
    outbound seam adds its own member with its own ADR. It does **not** render as
    ``SEARCH_PROVIDER`` and does not render as nothing" — so ADR-0260 §10's
    ``FORECAST_PROVIDER`` is that section working rather than a departure from it, and
    ADR-0260's header records the amendment to §5's closure at one.

    **The keeping of the ordered tuple is what that bought** (§5): the next seam's
    addition was a member rather than a second carrier minted from scratch, and a turn
    that reached both providers carries one statement naming both classes, neither
    displacing the other.

    **The order is asserted and not only the membership**: it is the order
    ``destinations`` renders in, so an *inserted* member would change what every existing
    statement renders. The value spelling is load-bearing for the same reason the reach
    vocabulary's is — the member crosses the wire inside a ``TurnOutcome``.
    """
    assert [one.name for one in OutboundDestination] == ["SEARCH_PROVIDER", "FORECAST_PROVIDER"]
    assert [one.value for one in OutboundDestination] == ["search_provider", "forecast_provider"]


# --- §13 item 6: what the model accepts ---------------------------------------


def test_the_two_empty_shapes_the_section_requires_are_accepted() -> None:
    """ADR-0264 §13 item 6's **Accepted** half, and it is stated first deliberately.

    "**Accepted:** the two empty-``destinations``, zero-``records`` shapes §4 requires
    for ``NOT_REACHED`` and ``INDETERMINATE``, so a lane that refuses emptiness outright
    fails this arm."

    §4 couples the three fields in one direction only: emptiness is refused **beside**
    ``REACHED`` and never on its own, because a turn that reached nothing is the
    ordinary turn and #2365 is the case it exists for.
    """
    for reach in (OutboundReach.NOT_REACHED, OutboundReach.INDETERMINATE):
        statement = OutboundStatement(reach=reach)

        assert statement.reach is reach
        assert statement.destinations == ()
        assert statement.records == 0


def test_a_reach_naming_its_class_is_accepted_with_a_count_of_none() -> None:
    """ADR-0264 §4: a ``0`` never suppresses the statement.

    "``records`` is ``0`` on a search that reached the provider and was answered with
    nothing. **A ``0`` means this turn's supply holds no record its contacts brought
    in**, and it means nothing else." §4 states the consequence in terms: the fact is
    the contact, "and a turn that reached outside itself and brought nothing into its
    supply is the case this decision most needs to state — it is the one a user cannot
    tell from a turn that did not look".
    """
    statement = OutboundStatement(
        reach=OutboundReach.REACHED, destinations=(OutboundDestination.SEARCH_PROVIDER,)
    )

    assert statement.records == 0


# --- §13 item 6: what the model refuses ---------------------------------------


def test_a_reach_naming_no_class_is_refused() -> None:
    """ADR-0264 §13 item 6: an **empty** ``destinations`` paired with ``REACHED``.

    §5's own reason: "a contact class with no member is a contact this system made and
    did not state, which is the defect this decision exists to close".
    """
    with pytest.raises(ValidationError, match="destinations must be non-empty"):
        OutboundStatement(reach=OutboundReach.REACHED)


@pytest.mark.parametrize("reach", [OutboundReach.NOT_REACHED, OutboundReach.INDETERMINATE])
def test_a_class_beside_a_reach_that_established_nothing_is_refused(reach: OutboundReach) -> None:
    """ADR-0264 §13 item 6: a **non-empty** one paired with either of the other two.

    §4: "A value carrying a destination beside a ``NOT_REACHED``, or a count beside an
    ``INDETERMINATE``, is refused rather than accepted and rendered as a reach nothing
    established."
    """
    with pytest.raises(ValidationError, match="names no destination class"):
        OutboundStatement(reach=reach, destinations=(OutboundDestination.SEARCH_PROVIDER,))


@pytest.mark.parametrize("reach", [OutboundReach.NOT_REACHED, OutboundReach.INDETERMINATE])
def test_a_count_beside_a_reach_that_established_nothing_is_refused(reach: OutboundReach) -> None:
    """ADR-0264 §13 item 6: a **non-zero** ``records`` paired with either of those two.

    The count is defined over the records **this turn's established contacts** put into
    the supply (§4), so a figure beside a reach that established none is a count of a
    population that cannot exist.
    """
    with pytest.raises(ValidationError, match="no record entered"):
        OutboundStatement(reach=reach, records=1)


def test_a_class_named_twice_is_refused() -> None:
    """ADR-0264 §13 item 6: one carrying a class **twice**.

    §4: "``destinations`` holds each class contacted once, in ``OutboundDestination``'s
    declared order and never in encounter order", and the model "**refuses** one that
    carries a class twice rather than accepting one a surface would then render as a
    contact naming nothing". A turn that contacted one class through three servicings
    carries that class once — it is not an enumeration of a turn's servicings.
    """
    with pytest.raises(ValidationError, match="repeats a class"):
        OutboundStatement(
            reach=OutboundReach.REACHED,
            destinations=(
                OutboundDestination.SEARCH_PROVIDER,
                OutboundDestination.SEARCH_PROVIDER,
            ),
        )


def test_a_negative_count_is_refused() -> None:
    """ADR-0264 §13 item 6: a **negative** ``records``.

    §4 declares the field with ``ge=0`` and says in terms that what validation it carries
    **beyond** that is this module's to settle — #2362 holds that question for every
    bounded ``int`` the module declares, and this field takes whatever answer it gets
    rather than being given a stricter posture than its neighbours inside one ADR.
    """
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        OutboundStatement(
            reach=OutboundReach.REACHED,
            destinations=(OutboundDestination.SEARCH_PROVIDER,),
            records=-1,
        )


def test_an_unknown_field_is_refused() -> None:
    """ADR-0264 §13 item 6: an **unknown field**.

    ``extra="forbid"`` is what makes §4's bar structural rather than documentary: "no
    destination, no host, no origin, no provider name, no connection reference, no
    account identity, no tool identifier, no query and no fragment of one, no record, no
    title, no snippet, no monetary figure, no duration, no ``Settings`` field name, no
    ``SearchDisposition`` value, no record id, no decision id and no instant" — and a
    fourth field is unconstructable rather than merely undocumented.
    """
    with pytest.raises(ValidationError, match="extra_forbidden"):
        OutboundStatement(reach=OutboundReach.NOT_REACHED, provider="brave")  # type: ignore[call-arg]


def test_the_value_is_frozen() -> None:
    """ADR-0264 §6: assembled once per turn and **never recomputed downstream**.

    Frozen is what stops a render site editing the value it was handed — §7's statement
    "stands where the reply contradicts it", and a mutable carrier is one a later stage
    could soften on the reply's behalf.
    """
    statement = OutboundStatement(reach=OutboundReach.NOT_REACHED)

    with pytest.raises(ValidationError):
        statement.records = 1

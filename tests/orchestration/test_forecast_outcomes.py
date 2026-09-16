"""ADR-0260 §13's arm (k): three total rules, each walked over its whole domain.

"A rule stated totally and tested selectively is one an implementation can leave
partial while passing every other arm." So §8's classifier entries, §10's fold and
§10's establishment partition are each enumerated **over the enum itself** rather than
over a chosen few — a member added to either vocabulary without a placement fails here,
and at import, rather than falling to a default.

**The subject is production**: the two vocabularies, the one classifier ADR-0251 §2
states, and the two mappings ADR-0260 §10 states. Nothing here wires a seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    ForecastNotRead,
    ForecastRefusal,
    OutboundReach,
    ReadAsk,
    ReadKind,
    ReadOutcomeKind,
)
from ai_assistant.orchestration.reads import (
    FORECAST_CONTACTS,
    FORECAST_DISPOSITIONS,
    FORECAST_NOT_READ,
    AskFacts,
    ForecastDisposition,
    classify_read_outcome,
    forecast_contact_of,
    forecast_not_read,
)

if TYPE_CHECKING:
    from ai_assistant.orchestration.reads import _NonYield

#: §8's classifier entry per ``ForecastDisposition`` member, **stated here member by
#: member** so that the assertion is over the ADR's own table rather than over the
#: implementation's. ``NO_BUDGET`` is absent deliberately: §8 makes it the one member
#: that earns **no entry at all**, and it is asserted as itself below.
_DISPOSITION_OUTCOMES: Final[dict[ForecastDisposition, ReadOutcomeKind]] = {
    ForecastDisposition.NOT_CONFIGURED: ReadOutcomeKind.REFUSED,
    ForecastDisposition.BINDING_FAILED: ReadOutcomeKind.FAILED,
    ForecastDisposition.RULING_CONFIRM: ReadOutcomeKind.REFUSED,
    ForecastDisposition.RULING_DENY: ReadOutcomeKind.REFUSED,
    ForecastDisposition.RULING_UNAVAILABLE: ReadOutcomeKind.REFUSED,
    ForecastDisposition.SPEND_REFUSED: ReadOutcomeKind.REFUSED,
    ForecastDisposition.TRANSPORT_FAILED: ReadOutcomeKind.FAILED,
    ForecastDisposition.DEADLINE_EXPIRED: ReadOutcomeKind.EXPIRED,
    ForecastDisposition.RESPONSE_TOO_LARGE: ReadOutcomeKind.FAILED,
    ForecastDisposition.PROVIDER_REFUSED: ReadOutcomeKind.REFUSED,
    ForecastDisposition.UNATTESTED: ReadOutcomeKind.REFUSED,
}

#: §8's classifier entry per ``ForecastRefusal`` member. ``NO_RESULT`` is "the provider
#: answering with nothing this read could use", which §8 places under ``EMPTY`` — where
#: the counts put it, the read having returned no record at all.
_REFUSAL_OUTCOMES: Final[dict[ForecastRefusal, ReadOutcomeKind]] = {
    ForecastRefusal.TRANSPORT_FAILED: ReadOutcomeKind.FAILED,
    ForecastRefusal.DEADLINE_EXPIRED: ReadOutcomeKind.EXPIRED,
    ForecastRefusal.RESPONSE_TOO_LARGE: ReadOutcomeKind.FAILED,
    ForecastRefusal.PROVIDER_REFUSED: ReadOutcomeKind.REFUSED,
    ForecastRefusal.UNATTESTED: ReadOutcomeKind.REFUSED,
    ForecastRefusal.NO_RESULT: ReadOutcomeKind.EMPTY,
}

#: §10's fold, stated here over all twelve for the reason §10 states it over all twelve:
#: "a fold whose domain is not enumerated is a fold two implementations will disagree
#: about".
_FOLD: Final[dict[ForecastDisposition, ForecastNotRead]] = {
    ForecastDisposition.NOT_CONFIGURED: ForecastNotRead.NOT_CONFIGURED,
    ForecastDisposition.RULING_CONFIRM: ForecastNotRead.AUTHORISATION_AWAITED,
    ForecastDisposition.SPEND_REFUSED: ForecastNotRead.SPEND_EXHAUSTED,
    ForecastDisposition.RULING_DENY: ForecastNotRead.DECLINED,
    ForecastDisposition.DEADLINE_EXPIRED: ForecastNotRead.INTERRUPTED,
    ForecastDisposition.NO_BUDGET: ForecastNotRead.UNAVAILABLE,
    ForecastDisposition.BINDING_FAILED: ForecastNotRead.UNAVAILABLE,
    ForecastDisposition.RULING_UNAVAILABLE: ForecastNotRead.UNAVAILABLE,
    ForecastDisposition.TRANSPORT_FAILED: ForecastNotRead.UNAVAILABLE,
    ForecastDisposition.RESPONSE_TOO_LARGE: ForecastNotRead.UNAVAILABLE,
    ForecastDisposition.PROVIDER_REFUSED: ForecastNotRead.UNAVAILABLE,
    ForecastDisposition.UNATTESTED: ForecastNotRead.UNAVAILABLE,
}

#: §10's establishment partition, over the same twelve.
_PARTITION: Final[dict[ForecastDisposition, OutboundReach]] = {
    ForecastDisposition.NOT_CONFIGURED: OutboundReach.NOT_REACHED,
    ForecastDisposition.NO_BUDGET: OutboundReach.NOT_REACHED,
    ForecastDisposition.BINDING_FAILED: OutboundReach.NOT_REACHED,
    ForecastDisposition.RULING_CONFIRM: OutboundReach.NOT_REACHED,
    ForecastDisposition.RULING_DENY: OutboundReach.NOT_REACHED,
    ForecastDisposition.RULING_UNAVAILABLE: OutboundReach.NOT_REACHED,
    ForecastDisposition.SPEND_REFUSED: OutboundReach.NOT_REACHED,
    ForecastDisposition.RESPONSE_TOO_LARGE: OutboundReach.REACHED,
    ForecastDisposition.UNATTESTED: OutboundReach.REACHED,
    ForecastDisposition.TRANSPORT_FAILED: OutboundReach.INDETERMINATE,
    ForecastDisposition.DEADLINE_EXPIRED: OutboundReach.INDETERMINATE,
    ForecastDisposition.PROVIDER_REFUSED: OutboundReach.INDETERMINATE,
}


def _facts(non_yield: _NonYield | None, *, certified: bool = True) -> AskFacts:
    """One ask's four facts, over a forecast ask that returned nothing.

    Args:
        non_yield: The typed non-yield the source or the servicing produced.
        certified: Whether completeness was certified — ``False`` is ADR-0226 §6's cut.

    Returns:
        The facts ADR-0251 §2's classifier decides from.
    """
    return AskFacts(
        ask=ReadAsk(kind=ReadKind.FORECAST_READ),
        reached=True,
        non_yield=non_yield,
        records=(),
        admitted=0,
        certified=certified,
    )


# --------------------------------------------------------------------------- #
# (k) The classifier, enumerated exhaustively over both types                  #
# --------------------------------------------------------------------------- #


def test_every_disposition_the_adr_maps_is_enumerated_here() -> None:
    """The table this module asserts against is total over §8's mapped members.

    ``ForecastDisposition.NO_BUDGET`` is §8's one stated exception and is deliberately
    absent from :data:`_DISPOSITION_OUTCOMES`; every other member is present. So a
    thirteenth member added without a row here fails **this** case, and the per-member
    cases below cannot quietly stop covering the vocabulary.
    """
    assert set(_DISPOSITION_OUTCOMES) | {ForecastDisposition.NO_BUDGET} == set(ForecastDisposition)
    assert len(list(ForecastDisposition)) == 12, (
        "§8 closes the vocabulary at twelve; a change to that count is a change to §8"
    )
    assert set(_REFUSAL_OUTCOMES) == set(ForecastRefusal)
    assert set(_FOLD) == set(ForecastDisposition)
    assert set(_PARTITION) == set(ForecastDisposition)


@pytest.mark.parametrize("member", list(ForecastDisposition))
def test_each_disposition_reaches_the_outcome_member_the_adr_gives_it(
    member: ForecastDisposition,
) -> None:
    """§13's arm (k)'s first limb, over **every** ``ForecastDisposition``.

    "Every member of ``ForecastRefusal``, and every member of ``ForecastDisposition``
    §8 maps, is asserted against the ``ReadOutcomeKind`` member §8 gives it, enumerated
    exhaustively over both types so that a member added without a mapping fails the arm
    rather than passing silently."

    **``NO_BUDGET`` is asserted as itself**: it "names a read the servicing did not
    reach", so the arm asserts **no outcome entry at all** and asserts no
    ``ReadOutcomeKind`` — "an assertion demanding one being unsatisfiable against §8 as
    written".

    Args:
        member: The disposition under test.
    """
    reached = classify_read_outcome(_facts(member))

    if member is ForecastDisposition.NO_BUDGET:
        assert reached is None, "a read the budget did not reach is not in it"
        return
    assert reached is _DISPOSITION_OUTCOMES[member]


@pytest.mark.parametrize("member", list(ForecastRefusal))
def test_each_refusal_reaches_the_outcome_member_the_adr_gives_it(
    member: ForecastRefusal,
) -> None:
    """§13's arm (k)'s first limb, over **every** ``ForecastRefusal``.

    ``NO_RESULT`` reaches ``EMPTY`` through the counts rather than through a table
    entry, which is §8's own construction: it "maps to no disposition", so what the
    classifier is given is a source that **answered** and returned nothing — and
    ADR-0251 §2's fifth limb is what says ``EMPTY``. An implementation short-circuiting
    it to ``EMPTY`` by name would report a read that returned records and deduplicated
    out as empty too.

    Args:
        member: The refusal under test.
    """
    assert classify_read_outcome(_facts(member)) is _REFUSAL_OUTCOMES[member]


def test_no_result_maps_to_no_disposition_at_all() -> None:
    """§8: "a read that reached the provider and was answered records *no* disposition".

    Asserted over the carry-across itself so that a lane adding an arm for it fails:
    §8 makes the absence the thing §10's contact rule is computed from, and a mapping
    that carried ``NO_RESULT`` across would make an answered read indistinguishable
    from a refused one at every site downstream.
    """
    assert ForecastRefusal.NO_RESULT not in FORECAST_DISPOSITIONS
    assert set(FORECAST_DISPOSITIONS) == set(ForecastRefusal) - {ForecastRefusal.NO_RESULT}
    assert len(set(FORECAST_DISPOSITIONS.values())) == len(FORECAST_DISPOSITIONS), (
        "the carry-across is injective, so no two causes are collapsed"
    )


@pytest.mark.parametrize(
    "non_yield",
    [None, ForecastRefusal.NO_RESULT],
)
def test_truncated_displaces_the_counting_members_where_the_budget_cut_the_yield(
    non_yield: ForecastRefusal | None,
) -> None:
    """§13's arm (k)'s last first-limb clause, and ADR-0251 §2's own precedence.

    "``TRUNCATED`` displaces ``EMPTY``, ``DUPLICATE`` and ``RETURNED_RECORDS`` where
    ADR-0226 §6's budget cut this kind's yield" — and only those three, which is why an
    uncertified answer whose source *refused* is still ``REFUSED``.

    Args:
        non_yield: An answered read, either way §8 spells one.
    """
    assert classify_read_outcome(_facts(non_yield, certified=False)) is ReadOutcomeKind.TRUNCATED
    assert (
        classify_read_outcome(_facts(ForecastRefusal.PROVIDER_REFUSED, certified=False))
        is ReadOutcomeKind.REFUSED
    ), "a refused answer is not truncated: the source answered about the ask"


# --------------------------------------------------------------------------- #
# (k) The fold and the partition, each walked over all twelve                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("member", list(ForecastDisposition))
def test_each_disposition_folds_onto_the_member_the_adr_declares(
    member: ForecastDisposition,
) -> None:
    """§13's arm (k)'s second limb: §10's fold, over **all twelve**.

    "The seven that fold onto ``UNAVAILABLE`` named individually, so that an omitted
    member cannot pass as a default." The fold is non-injective by design (ADR-0242 §8):
    the surface is told a class, never a cause.

    Args:
        member: The disposition under test.
    """
    assert forecast_not_read(member) is _FOLD[member]
    assert FORECAST_NOT_READ[member] is _FOLD[member]


def test_the_fold_is_non_injective_in_exactly_the_way_the_adr_says() -> None:
    """§10: "seven dispositions the user has no act for fold onto the one member that
    names none".

    Asserted as a count rather than as a shape, because the count is the clause: a lane
    that gave one of the seven a member of its own would be naming an act the user does
    not have, and a lane that folded an eighth would be withholding one they do.
    """
    unavailable = [
        member for member, folded in _FOLD.items() if folded is ForecastNotRead.UNAVAILABLE
    ]

    assert len(unavailable) == 7
    assert set(_FOLD.values()) == set(ForecastNotRead), "every member has a producer"


@pytest.mark.parametrize("member", list(ForecastDisposition))
def test_each_disposition_lands_on_the_side_of_the_partition_the_adr_places_it(
    member: ForecastDisposition,
) -> None:
    """§13's arm (k)'s third limb: §10's establishment partition, over **all twelve**.

    "``PROVIDER_REFUSED`` on the nothing-either-way side beside the two before it",
    which is ADR-0264 §13's third arm taken at its word rather than one member read two
    ways at two seams.

    Args:
        member: The disposition under test.
    """
    assert forecast_contact_of(member) is _PARTITION[member]
    assert FORECAST_CONTACTS[member] is _PARTITION[member]


def test_the_absent_disposition_is_the_thirteenth_case_and_is_a_contact() -> None:
    """§10: "the partition is total over the twelve members and the absence of one is
    the thirteenth case".

    A call that completed and recorded no ``ForecastDisposition`` reached the provider
    and was answered, records or none — which is what makes :func:`forecast_contact_of`
    a function of the **call** and never of the servicing's completion.
    """
    assert forecast_contact_of(None) is OutboundReach.REACHED


def test_the_partition_and_the_fold_are_computed_from_one_another_in_neither_direction() -> None:
    """§10: "the fact is never derived from ``ForecastNotRead``", which is non-injective.

    A site holding only the folded member cannot compute the contact, and this is what
    that looks like as a property: ``UNAVAILABLE`` covers members on **two** sides of
    the partition, so no total function from the folded member to a reach exists.
    """
    reaches = {
        _PARTITION[member]
        for member, folded in _FOLD.items()
        if folded is ForecastNotRead.UNAVAILABLE
    }

    assert reaches == {
        OutboundReach.NOT_REACHED,
        OutboundReach.REACHED,
        OutboundReach.INDETERMINATE,
    }, "one folded member spans all three sides, so the contact is not derivable from it"

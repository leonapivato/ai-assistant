"""The levels, each kind's declared most, and the identity and link types (ADR-0366 §5).

Four levels, closed and ordered from least to most (§5:1); each kind's declared most,
beside how it establishes authors, with none for a kind that declares nothing (§5:2); a
link's level, its kind's most or its lowest standing lowering, whichever is lower (§5:3,
§5:5); and the shapes an identity, a link and a write take.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import (
    establishes_the_user,
    link_level,
    most_sureness,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    Identity,
    Link,
    LinkAct,
    LinkActHow,
    LinkRefusal,
    LinkWrite,
    LinkWriteKind,
    Lowering,
    Sureness,
)

_AT: Final = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
_ACT: Final = LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)


def _lowering(level: Sureness, *, withdrawn: bool = False, number: int = 1) -> Lowering:
    return Lowering(
        id=f"lowering:{number}",
        level=level,
        by=OWNER_PERSON_ID,
        made_at=_AT,
        withdrawn_at=_AT + timedelta(minutes=1) if withdrawn else None,
    )


def _link(kind: str, *lowerings: Lowering) -> Link:
    return Link(
        id="link:1",
        person_id=OWNER_PERSON_ID,
        account=Account(kind=kind, identifier="424242"),
        act=_ACT,
        made_at=_AT,
        lowerings=lowerings,
    )


# --- the four levels (§5:1) -----------------------------------------------------------


def test_the_levels_are_four_from_least_to_most() -> None:
    assert list(Sureness) == [Sureness.NONE, Sureness.WEAK, Sureness.NORMAL, Sureness.STRONG]
    assert [one.value for one in Sureness] == ["none", "weak", "normal", "strong"]
    assert [one.rank for one in Sureness] == [0, 1, 2, 3]


def test_levels_compare_by_their_order_and_not_their_spelling() -> None:
    # Alphabetically "none" < "normal" < "strong" < "weak"; the order is the levels'.
    assert Sureness.WEAK < Sureness.NORMAL < Sureness.STRONG
    assert Sureness.NONE < Sureness.WEAK
    assert Sureness.NORMAL <= Sureness.NORMAL
    assert Sureness.STRONG > Sureness.WEAK
    assert Sureness.WEAK >= Sureness.NONE
    assert not Sureness.WEAK > Sureness.NORMAL
    assert min(Sureness.STRONG, Sureness.WEAK, Sureness.NORMAL) is Sureness.WEAK
    assert max(Sureness.NONE, Sureness.WEAK) is Sureness.WEAK
    assert sorted([Sureness.WEAK, Sureness.STRONG, Sureness.NONE]) == [
        Sureness.NONE,
        Sureness.WEAK,
        Sureness.STRONG,
    ]


@pytest.mark.parametrize("other", ["normal", "zzz", 1, None])
def test_a_level_compares_only_with_a_level(other: object) -> None:
    # Either way round: a level is a ``str``, so ``"normal" > level`` asks the level first.
    with pytest.raises(TypeError, match="only with a level"):
        _ = other > Sureness.WEAK
    with pytest.raises(TypeError, match="only with a level"):
        _ = other <= Sureness.WEAK
    with pytest.raises(TypeError, match="only with a level"):
        _ = Sureness.WEAK.__lt__(other)


def test_a_level_is_still_its_value_for_equality_and_storage() -> None:
    stored: str = "normal"
    assert stored == Sureness.NORMAL
    assert Sureness("weak") is Sureness.WEAK
    assert hash(Sureness.NONE) == hash("none")


# --- each kind's declared most (§5:2) -------------------------------------------------


@pytest.mark.parametrize("kind", ["conversation", "telegram"])
def test_the_hub_chat_and_the_line_give_normal(kind: str) -> None:
    assert most_sureness(kind) is Sureness.NORMAL


@pytest.mark.parametrize(
    "kind", ["email", "informational_event", "task_scheduler", "approvals", "unheard-of"]
)
def test_a_kind_that_declares_no_most_gives_none(kind: str) -> None:
    assert most_sureness(kind) is Sureness.NONE


@pytest.mark.parametrize(
    "kind", ["conversation", "telegram", "email", "informational_event", "task_scheduler"]
)
def test_a_kind_gives_more_than_none_exactly_where_it_establishes_the_user(kind: str) -> None:
    """ADR-0368 §9:4: an author established under ADR-0292 §5:3 is at weak or above."""
    assert (most_sureness(kind) > Sureness.NONE) is establishes_the_user(kind)


def test_no_kind_gives_strong_yet() -> None:
    """ADR-0366 §5:4: strong waits on combining several signals, which nothing builds."""
    kinds = ["conversation", "telegram", "email", "informational_event"]
    assert all(most_sureness(kind) < Sureness.STRONG for kind in kinds)


# --- a link's level (§5:3, §5:5) ------------------------------------------------------


def test_a_link_with_no_lowering_is_at_its_kinds_most() -> None:
    assert link_level(_link("telegram")) is Sureness.NORMAL
    assert link_level(_link("email")) is Sureness.NONE


def test_a_standing_lowering_lowers_a_link_and_a_withdrawn_one_does_not() -> None:
    assert link_level(_link("telegram", _lowering(Sureness.WEAK))) is Sureness.WEAK
    withdrawn = _link("telegram", _lowering(Sureness.NONE, withdrawn=True))
    assert link_level(withdrawn) is Sureness.NORMAL
    assert withdrawn.standing_lowerings == ()


def test_the_lowest_standing_lowering_sets_the_level() -> None:
    link = _link(
        "telegram",
        _lowering(Sureness.WEAK, number=1),
        _lowering(Sureness.NONE, withdrawn=True, number=2),
        _lowering(Sureness.STRONG, number=3),
    )

    assert link_level(link) is Sureness.WEAK
    assert [one.id for one in link.standing_lowerings] == ["lowering:1", "lowering:3"]


def test_nothing_raises_a_link_above_its_kinds_most() -> None:
    assert link_level(_link("telegram", _lowering(Sureness.STRONG))) is Sureness.NORMAL
    assert link_level(_link("email", _lowering(Sureness.STRONG))) is Sureness.NONE
    assert _link("telegram").level(Sureness.STRONG) is Sureness.STRONG


# --- the shapes -----------------------------------------------------------------------


def test_an_identity_holds_only_the_links_tied_to_it() -> None:
    link = _link("telegram")

    assert Identity(id=OWNER_PERSON_ID, created_at=_AT, links=(link,)).links == (link,)
    with pytest.raises(ValidationError, match="only the links tied to it"):
        Identity(id="person:someone-else", created_at=_AT, links=(link,))


def test_an_account_is_held_verbatim_and_refuses_blank_parts() -> None:
    assert Account(kind="conversation", identifier=" phone ").identifier == " phone "
    with pytest.raises(ValidationError):
        Account(kind=" ", identifier="phone")
    with pytest.raises(ValidationError):
        Account(kind="conversation", identifier="")


def test_a_write_names_its_refusal_exactly_when_it_was_refused() -> None:
    LinkWrite(kind=LinkWriteKind.REFUSED, refusal=LinkRefusal.NOT_ALLOWED)
    LinkWrite(kind=LinkWriteKind.WRITTEN, record_id="link:1")
    with pytest.raises(ValidationError, match="exactly when"):
        LinkWrite(kind=LinkWriteKind.REFUSED)
    with pytest.raises(ValidationError, match="exactly when"):
        LinkWrite(kind=LinkWriteKind.UNCHANGED, refusal=LinkRefusal.UNKNOWN_RECORD)


def test_the_closed_enumerations_name_what_they_name() -> None:
    assert [one.value for one in LinkActHow] == ["configured", "device"]
    assert [one.value for one in LinkWriteKind] == ["written", "unchanged", "refused"]
    assert [one.value for one in LinkRefusal] == [
        "unknown_person",
        "unknown_record",
        "already_linked",
        "not_allowed",
        "not_a_lowering",
    ]

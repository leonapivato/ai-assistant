"""The owner's sight: the domains an owner's act may name, and the sight made for one.

ADR-0385 §2:1 and §2:2 (the one function naming the two domains, and the refusal of any
other from the value alone), §3:3 (the one constructor, from the domain the act names or
from none), §3:4 (no activation, so nothing is an act's own) and §3:5 (a store bound to
it withholds whatever mode it was built in: :meth:`Sight.answered_in`).
"""

from __future__ import annotations

from typing import Final, cast

import pytest

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    InputSender,
    RecordHome,
    RecordHomeKind,
    Sight,
    SightBound,
    SightMode,
    SightReader,
    Sureness,
    WithheldReason,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    owners_act_may_name,
)

_OWNERS: Final = RecordHome.owners()
_SHARED: Final = RecordHome.shared()
_THEIRS: Final = RecordHome.person("person:other")
_GROUPS: Final = RecordHome.group("group:house")
#: Every kind of home, the ones no act may name included.
_HOMES: Final = (_OWNERS, _SHARED, _THEIRS, _GROUPS)

#: Values of the home type no validation made, and a value of no home type at all: each
#: is refused from the value alone (ADR-0385 §2:2, §6:9's "malformed").
_MALFORMED: Final = (
    RecordHome.model_construct(kind=RecordHomeKind.SHARED, id=OWNER_PERSON_ID),
    RecordHome.model_construct(kind=RecordHomeKind.PERSON, id=None),
    RecordHome.model_construct(kind=RecordHomeKind.PERSON, id=f" {OWNER_PERSON_ID}"),
    RecordHome.model_construct(kind=RecordHomeKind.GROUP, id=OWNER_PERSON_ID),
    cast("RecordHome", "shared"),
    cast("RecordHome", {"kind": "shared"}),
)


def _seen(sight: Sight) -> set[RecordHome]:
    return {home for home in _HOMES if sight.sees(home)}


# --- the domains an act may name (ADR-0385 §2) ------------------------------------


def test_an_owners_act_may_name_the_owners_domain_and_the_shared_things() -> None:
    """§2:1: the person home of the owner and the hub's shared things."""
    assert owners_act_may_name(_OWNERS)
    assert owners_act_may_name(_SHARED)
    assert owners_act_may_name(RecordHome.person(OWNER_PERSON_ID))


@pytest.mark.parametrize(
    "domain",
    [_THEIRS, _GROUPS, RecordHome.group(OWNER_PERSON_ID)],
    ids=["anothers", "a-groups", "a-group-named-like-the-owner"],
)
def test_an_owners_act_may_name_no_other_domain(domain: RecordHome) -> None:
    """§2:1, §2:2: another person's domain and a group's are refused, from the value alone."""
    assert not owners_act_may_name(domain)
    with pytest.raises(ValueError, match="owner's domain or the hub's shared things"):
        Sight.of_owners_act(domain)


@pytest.mark.parametrize("domain", _MALFORMED)
def test_a_malformed_domain_is_refused_from_the_value_alone(domain: RecordHome) -> None:
    """§2:2: a value no validation made, or no home at all, is neither of the two."""
    assert not owners_act_may_name(domain)
    with pytest.raises(ValueError, match="owner's domain or the hub's shared things"):
        Sight.of_owners_act(domain)


# --- the owner's sight (ADR-0385 §3:3, §3:4) ----------------------------------------


def test_the_owners_sight_from_none_is_a_person_bound_for_the_owner_alone() -> None:
    """§3:3: from none, the owner's domain and the shared things, and nothing else."""
    sight = Sight.of_owners_act(None)
    assert sight.reader is SightReader.OWNERS_ACT
    assert sight.bounds == (SightBound.person(OWNER_PERSON_ID),)
    assert _seen(sight) == {_OWNERS, _SHARED}


@pytest.mark.parametrize("domain", [_OWNERS, _SHARED], ids=["owners", "shared"])
def test_the_owners_sight_from_a_domain_sees_that_domain_alone(domain: RecordHome) -> None:
    """§3:3: from a domain §2:1 allows, the owner's person bound and a one-domain bound."""
    sight = Sight.of_owners_act(domain)
    assert sight.reader is SightReader.OWNERS_ACT
    assert set(sight.bounds) == {SightBound.person(OWNER_PERSON_ID), SightBound.one_domain(domain)}
    assert _seen(sight) == {domain}


@pytest.mark.parametrize("domain", [None, _OWNERS, _SHARED], ids=["none", "owners", "shared"])
def test_the_owners_sight_carries_no_activation_and_holds_nothing_as_its_own(
    domain: RecordHome | None,
) -> None:
    """§3:4: nothing is an act's own, and a record with no home is seen by none of them.

    A record the store records as made by an activation is seen by its home alone, and
    one with no home is withheld whoever made it (ADR-0383 §5:3, §7:4).
    """
    sight = Sight.of_owners_act(domain)
    assert sight.activation is None
    assert sight.withheld(None) is WithheldReason.NO_HOME
    assert sight.withheld(None, made_by="a") is WithheldReason.NO_HOME
    assert sight.withheld(_THEIRS, made_by="a") is WithheldReason.OTHER_HOME
    assert sight.withheld(_GROUPS) is WithheldReason.OTHER_HOME
    with pytest.raises(ValueError, match="activation"):
        Sight(reader=SightReader.OWNERS_ACT, bounds=sight.bounds, activation="a")


def test_no_level_link_or_line_enters_the_owners_sight() -> None:
    """§3:4, ADR-0383 §6:9: the constructor takes the domain alone, so one value a domain."""
    assert Sight.of_owners_act(None) == Sight.of_owners_act(None)
    assert Sight.of_owners_act(_SHARED) == Sight.of_owners_act(RecordHome.shared())


# --- meeting another sight (ADR-0383 §6:6) ------------------------------------------


def test_two_owners_sights_meet_as_the_homes_both_see() -> None:
    """``Sight.meet`` admits two sights of one reader and no activation, as it is.

    Binding a store bound to the owner's sight again binds the meet, which never widens:
    from none and the owner's domain, the owner's domain; the owner's domain and the
    shared things, nothing.
    """
    from_none = Sight.of_owners_act(None)
    owners = Sight.of_owners_act(_OWNERS)
    shared = Sight.of_owners_act(_SHARED)
    assert _seen(from_none.meet(owners)) == {_OWNERS}
    assert _seen(from_none.meet(shared)) == {_SHARED}
    assert _seen(owners.meet(shared)) == set()
    assert from_none.meet(owners).reader is SightReader.OWNERS_ACT


def test_the_owners_sight_meets_no_other_readers() -> None:
    """``Sight.meet`` refuses a sight of another reader, so no binding mixes the two."""
    facts = WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=Sureness.NORMAL,
    )
    sender = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
    others = (
        Sight.of_work(facts, (sender,), activation="a"),
        Sight.of_producer(facts, (sender,)),
        Sight.of_run(_OWNERS),
    )
    owners = Sight.of_owners_act(None)
    for other in others:
        with pytest.raises(ValueError, match="meet"):
            owners.meet(other)
        with pytest.raises(ValueError, match="meet"):
            other.meet(owners)


# --- the mode a store answers it in (ADR-0385 §3:5) ---------------------------------


@pytest.mark.parametrize("built", list(SightMode))
@pytest.mark.parametrize("domain", [None, _OWNERS, _SHARED], ids=["none", "owners", "shared"])
def test_the_owners_sight_is_answered_withholding_whatever_the_build(
    built: SightMode, domain: RecordHome | None
) -> None:
    """§3:5: a store built to count answers the owner's sight withholding too."""
    assert Sight.of_owners_act(domain).answered_in(built) is SightMode.WITHHOLD


@pytest.mark.parametrize("built", list(SightMode))
def test_every_other_sight_is_answered_in_the_mode_the_store_was_built_in(
    built: SightMode,
) -> None:
    """ADR-0383 §7:10 stands for every other reader."""
    sender = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
    facts = WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=Sureness.NORMAL,
    )
    work = Sight.of_work(facts, (sender,), activation="a")
    for sight in (
        work,
        Sight.of_producer(facts, (sender,)),
        Sight.of_producer(None, ()),
        Sight.of_run(_SHARED),
        Sight.of_tidy_up(work, _SHARED),
    ):
        assert sight.answered_in(built) is built, sight.reader


def test_the_reader_code_is_added_and_none_renamed() -> None:
    """``SightReader`` is added to and never renamed: the new code beside the three."""
    assert {reader.value for reader in SightReader} == {"work", "producer", "run", "owners_act"}

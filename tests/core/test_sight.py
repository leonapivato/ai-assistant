"""The sight a read is bounded by: its bounds, its predicate and its constructors.

ADR-0383 §6 (the value and how recorded facts make it), §7:3 (the one predicate) and
§11:1 to §11:3 (the count, in numbers and codes alone).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    AuthorityKind,
    InputSender,
    RecordHome,
    Sight,
    SightBound,
    SightBoundKind,
    SightCount,
    SightReader,
    Sureness,
    WithheldReason,
    WorkAuthority,
    WorkFacts,
    WorkFor,
    WorkForKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_OTHER: Final = "person:other"
_OWNERS: Final = RecordHome.owners()
_SHARED: Final = RecordHome.shared()
_THEIRS: Final = RecordHome.person(_OTHER)
_GROUPS: Final = RecordHome.group("group:house")
#: Every kind of home, the ones no write may carry in this milestone included.
_HOMES: Final = (_OWNERS, _SHARED, _THEIRS, _GROUPS)

_OWNER_SENDS: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_NO_ONE_SENDS: Final = InputSender(person=None, level=Sureness.NONE)
#: A link the owner lowered to none: the person is named, and the sender is unidentified.
_LOWERED: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NONE)


def _owners_message(level: Sureness = Sureness.NORMAL) -> WorkFacts:
    return WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=level,
    )


def _unidentifieds_message() -> WorkFacts:
    return WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, unidentified=True),
        level=Sureness.NONE,
    )


def _owners_task(author: str = OWNER_PERSON_ID) -> WorkFacts:
    return WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.IN_ADVANCE, persons=(author,)),
        level=Sureness.NORMAL,
    )


def _seen(sight: Sight) -> set[RecordHome]:
    return {home for home in _HOMES if sight.sees(home)}


# --- the bounds (§6:2) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("bound", "homes"),
    [
        (SightBound.person(OWNER_PERSON_ID), {_OWNERS, _SHARED}),
        (SightBound.person(_OTHER), {_THEIRS}),
        (SightBound.no_one(), {_SHARED}),
        (SightBound.anyone(), set()),
        (SightBound.group("group:house"), set()),
        (SightBound.one_domain(_SHARED), {_SHARED}),
        (SightBound.one_domain(_GROUPS), {_GROUPS}),
    ],
)
def test_each_bound_sees_the_homes_its_kind_names(
    bound: SightBound, homes: set[RecordHome]
) -> None:
    """§6:2: a person their own domain and the owner the shared things; no one the
    shared things; anyone and a group nothing; one domain that domain alone."""
    assert set(bound.homes_seen) == homes
    assert bound.sees_nothing is (not homes)


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": SightBoundKind.PERSON},
        {"kind": SightBoundKind.GROUP},
        {"kind": SightBoundKind.DOMAIN},
        {"kind": SightBoundKind.NO_ONE, "id": OWNER_PERSON_ID},
        {"kind": SightBoundKind.ANYONE, "domain": _OWNERS},
        {"kind": SightBoundKind.PERSON, "id": OWNER_PERSON_ID, "domain": _OWNERS},
    ],
)
def test_a_bound_names_whom_its_kind_names_and_nothing_else(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SightBound.model_validate(fields)


def test_a_bound_codes_its_kind_and_whether_a_person_is_the_owner() -> None:
    """§11:2: codes carry no identifier."""
    assert SightBound.person(OWNER_PERSON_ID).code == "person_owner"
    assert SightBound.person(_OTHER).code == "person_other"
    assert SightBound.group("group:house").code == "group"
    assert SightBound.one_domain(_OWNERS).code == "domain"


# --- the value (§6:1, §6:3, §6:9) ----------------------------------------------


def test_a_sight_with_no_bound_is_refused_where_it_is_made() -> None:
    """§6:3: there is no value that sees every record."""
    with pytest.raises(ValidationError):
        Sight(reader=SightReader.RUN, bounds=())


def test_a_works_sight_names_its_activation_and_no_other_sight_does() -> None:
    with pytest.raises(ValidationError):
        Sight(reader=SightReader.WORK, bounds=(SightBound.no_one(),))
    with pytest.raises(ValidationError):
        Sight(reader=SightReader.RUN, bounds=(SightBound.no_one(),), activation="a")


def test_a_sight_holds_each_bound_once_in_one_order() -> None:
    one = Sight(
        reader=SightReader.RUN,
        bounds=(SightBound.person(OWNER_PERSON_ID), SightBound.anyone(), SightBound.anyone()),
    )
    other = Sight(
        reader=SightReader.RUN, bounds=(SightBound.anyone(), SightBound.person(OWNER_PERSON_ID))
    )
    assert one == other
    assert one.bounds == (SightBound.anyone(), SightBound.person(OWNER_PERSON_ID))


def test_a_sight_carries_no_level_bar_or_sureness() -> None:
    """§6:9: a person bound sees the same records at every level its person is at."""
    assert set(Sight.model_fields) == {"reader", "bounds", "activation"}
    weak = Sight.of_work(
        _owners_message(Sureness.WEAK),
        (InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK),),
        activation="a",
    )
    strong = Sight.of_work(_owners_message(Sureness.STRONG), (_OWNER_SENDS,), activation="a")
    assert weak == strong


# --- the predicate (§7:3, §5:3, §7:4) ------------------------------------------


@pytest.mark.parametrize(
    "bounds",
    [
        (SightBound.person(OWNER_PERSON_ID),),
        (SightBound.person(OWNER_PERSON_ID), SightBound.anyone()),
        (SightBound.no_one(), SightBound.person(OWNER_PERSON_ID)),
        (SightBound.one_domain(_OWNERS), SightBound.person(OWNER_PERSON_ID)),
        (SightBound.person(_OTHER), SightBound.group("group:house")),
        (SightBound.one_domain(_GROUPS),),
    ],
)
def test_a_sight_sees_a_home_exactly_where_every_bound_does(bounds: tuple[SightBound, ...]) -> None:
    """§6:1, §7:3: ``homes_seen`` and the predicate answer alike on every home."""
    sight = Sight(reader=SightReader.RUN, bounds=bounds)
    for home in _HOMES:
        every = all(home in bound.homes_seen for bound in bounds)
        assert sight.sees(home) is every
        assert (home in sight.homes_seen) is every


def test_a_record_with_no_home_is_seen_by_no_sight() -> None:
    """§5:3: the home of no one, whatever the sight."""
    owners = Sight(reader=SightReader.RUN, bounds=(SightBound.person(OWNER_PERSON_ID),))
    assert owners.withheld(None) is WithheldReason.NO_HOME


def test_a_works_own_records_are_seen_whatever_home_they_carry() -> None:
    """§7:4: a work's sight holds what its activation made, and no other sight does.

    Only where it carries a home: a record with none, its own included, is withheld
    from every sight (§5:3).
    """
    sight = Sight.of_work(_unidentifieds_message(), (_NO_ONE_SENDS,), activation="a")
    assert sight.sees(_OWNERS, made_by="a")
    assert sight.sees(_THEIRS, made_by="a")
    assert sight.withheld(None, made_by="a") is WithheldReason.NO_HOME
    assert not sight.sees(_OWNERS, made_by="b")
    assert not sight.sees(_OWNERS)
    producer = Sight.of_producer(_unidentifieds_message(), (_NO_ONE_SENDS,))
    assert not producer.sees(_OWNERS, made_by="a")


def test_a_withheld_record_says_why_in_one_of_three_codes() -> None:
    """§11:2: another home, no home, or a bound that sees nothing."""
    unidentified = Sight.of_work(_unidentifieds_message(), (_NO_ONE_SENDS,), activation="a")
    assert unidentified.withheld(_OWNERS) is WithheldReason.SEES_NOTHING
    assert unidentified.withheld(_THEIRS) is WithheldReason.OTHER_HOME
    no_one = Sight(reader=SightReader.RUN, bounds=(SightBound.no_one(),))
    assert no_one.withheld(_OWNERS) is WithheldReason.OTHER_HOME
    assert no_one.withheld(_SHARED) is None


# --- the constructors (§6:4 to §6:8) -------------------------------------------


def test_the_owners_message_reads_the_owners_domain_and_the_shared_things() -> None:
    """§6's first case."""
    sight = Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="a")
    assert sight.bounds == (SightBound.person(OWNER_PERSON_ID),)
    assert _seen(sight) == {_OWNERS, _SHARED}
    assert sight.reader is SightReader.WORK
    assert sight.activation == "a"


@pytest.mark.parametrize("sender", [_NO_ONE_SENDS, _LOWERED])
def test_an_unidentified_senders_work_reads_nothing_but_its_own(sender: InputSender) -> None:
    """§6's second case: a sender by no link, or by a link lowered to none."""
    sight = Sight.of_work(_unidentifieds_message(), (sender,), activation="a")
    assert sight.bounds == (SightBound.anyone(), SightBound.person(OWNER_PERSON_ID))
    assert _seen(sight) == set()


def test_a_task_carries_its_authors_bound_and_no_sender_bound() -> None:
    """§6's third case and §6:5; an author other than whom it is for narrows it."""
    assert Sight.of_work(_owners_task(), (), activation="a").bounds == (
        SightBound.person(OWNER_PERSON_ID),
    )
    sight = Sight.of_work(_owners_task(_OTHER), (), activation="a")
    assert _seen(sight) == set()


def test_the_senders_come_from_the_inputs_never_from_the_authority() -> None:
    """§6:4: a forward carrying no authority still bounds the work by its sender."""
    facts = WorkFacts(
        for_whom=WorkFor.for_person(OWNER_PERSON_ID),
        authority=WorkAuthority(kind=AuthorityKind.SENDERS, persons=(OWNER_PERSON_ID,)),
        level=Sureness.WEAK,
    )
    sight = Sight.of_work(facts, (_OWNER_SENDS, _NO_ONE_SENDS), activation="a")
    assert SightBound.anyone() in sight.bounds


@pytest.mark.parametrize(
    ("for_whom", "bound"),
    [
        (WorkFor.no_one(), SightBound.no_one()),
        (WorkFor(kind=WorkForKind.GROUP, id="group:house"), SightBound.group("group:house")),
    ],
)
def test_whom_a_work_is_for_is_one_bound(for_whom: WorkFor, bound: SightBound) -> None:
    facts = WorkFacts(for_whom=for_whom, authority=WorkAuthority.none(), level=Sureness.NONE)
    assert Sight.of_work(facts, (), activation="a").bounds == (bound,)


def test_a_work_remade_meets_the_sight_it_had_so_it_never_widens() -> None:
    """§6:6: a join of an unidentified sender narrows; nothing later widens it back."""
    had = Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="a")
    joined = Sight.of_work(
        _unidentifieds_message(), (_OWNER_SENDS, _NO_ONE_SENDS), activation="a", had=had
    )
    assert _seen(joined) == set()
    again = Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="a", had=joined)
    assert again == joined


# --- a work whose facts were not recorded (ADR-0388 §5) -------------------------------


def test_a_work_with_no_facts_is_an_anyone_bound_alone_and_its_activation() -> None:
    """ADR-0388 §5:1, §5:3: a work's sight, seeing its own records and nothing else."""
    sight = Sight.of_work(None, (), activation="a")
    assert sight.reader is SightReader.WORK
    assert sight.bounds == (SightBound.anyone(),)
    assert sight.activation == "a"
    assert _seen(sight) == set()
    for home in _HOMES:
        assert sight.sees(home, made_by="a")
        assert not sight.sees(home, made_by="b")
        assert sight.withheld(home) is WithheldReason.SEES_NOTHING
    # A record with no home is withheld from its own activation too (ADR-0383 §5:3).
    assert sight.withheld(None, made_by="a") is WithheldReason.NO_HOME


class _Unread:
    """Senders that fail the test if anything iterates them."""

    def __iter__(self) -> Iterator[InputSender]:
        pytest.fail("a work with no facts reads no sender")


def test_a_work_with_no_facts_reads_no_sender() -> None:
    """ADR-0388 §5:3: given none, the senders are not read, whoever they would name."""
    sight = Sight.of_work(None, _Unread(), activation="a")
    assert sight == Sight.of_work(None, (_OWNER_SENDS,), activation="a")


def test_a_work_with_no_facts_is_not_a_producers_sight() -> None:
    """Its activation's records are its own, which a producer's never are (§6:7)."""
    work = Sight.of_work(None, (), activation="a")
    producer = Sight.of_producer(None, ())
    assert work.bounds == producer.bounds
    assert producer.activation is None
    assert not producer.sees(_OWNERS, made_by="a")
    assert work.sees(_OWNERS, made_by="a")


@pytest.mark.parametrize(
    ("facts", "senders"),
    [
        (_owners_message(), (_OWNER_SENDS,)),
        (_owners_task(), ()),
        (
            WorkFacts(
                for_whom=WorkFor.no_one(), authority=WorkAuthority.none(), level=Sureness.NONE
            ),
            (),
        ),
    ],
    ids=["owners-message", "owners-task", "for-no-one"],
)
def test_a_work_with_no_facts_never_widens_once_its_facts_are_recorded(
    facts: WorkFacts, senders: tuple[InputSender, ...]
) -> None:
    """ADR-0388 §5:2, ADR-0383 §6:6: remade from recorded facts, it is the meet of the two."""
    had = Sight.of_work(None, (), activation="a")
    remade = Sight.of_work(facts, senders, activation="a", had=had)
    assert SightBound.anyone() in remade.bounds
    assert remade.activation == "a"
    assert _seen(remade) == set()
    assert remade.sees(_OWNERS, made_by="a")
    assert remade == had.meet(Sight.of_work(facts, senders, activation="a"))


def test_a_work_whose_facts_are_lost_is_narrowed_by_the_sight_it_had() -> None:
    """ADR-0383 §6:6: made from none with the sight it had, it keeps that sight's bounds."""
    had = Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="a")
    narrowed = Sight.of_work(None, (_OWNER_SENDS,), activation="a", had=had)
    assert narrowed.bounds == (SightBound.anyone(), SightBound.person(OWNER_PERSON_ID))
    assert _seen(narrowed) == set()
    with pytest.raises(ValueError, match="meet"):
        Sight.of_work(None, (), activation="b", had=had)


def test_two_sights_of_other_readers_or_activations_do_not_meet() -> None:
    had = Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="a")
    with pytest.raises(ValueError, match="meet"):
        Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="b", had=had)
    with pytest.raises(ValueError, match="meet"):
        had.meet(Sight.of_run(_SHARED))


def test_a_producer_reads_by_the_episodes_facts_with_nothing_its_own() -> None:
    """§6:7: and an episode that records no facts gives an anyone bound alone."""
    sight = Sight.of_producer(_owners_message(), (_OWNER_SENDS,))
    assert sight.activation is None
    assert sight.reader is SightReader.PRODUCER
    assert _seen(sight) == {_OWNERS, _SHARED}
    nothing = Sight.of_producer(None, (_OWNER_SENDS,))
    assert nothing.bounds == (SightBound.anyone(),)
    assert _seen(nothing) == set()


def test_a_run_reads_the_domain_it_tends_by_that_domains_person() -> None:
    """§6:8, ADR-0384 §3:1, §3:2: the owner's person bound for the shared things."""
    shared = Sight.of_run(_SHARED)
    assert shared.bounds == (SightBound.one_domain(_SHARED), SightBound.person(OWNER_PERSON_ID))
    assert _seen(shared) == {_SHARED}
    assert _seen(Sight.of_run(_OWNERS)) == {_OWNERS}
    assert _seen(Sight.of_run(_THEIRS)) == {_THEIRS}
    with pytest.raises(ValueError, match="tends"):
        Sight.of_run(_GROUPS)


def test_a_tidy_up_reads_as_its_work_of_the_storys_domain_alone() -> None:
    """§6:8, ADR-0384 §6:1: the work's activation is kept."""
    work = Sight.of_work(_owners_message(), (_OWNER_SENDS,), activation="a")
    tidy = Sight.of_tidy_up(work, _SHARED)
    assert tidy.activation == "a"
    assert _seen(tidy) == {_SHARED}
    with pytest.raises(ValueError, match="work"):
        Sight.of_tidy_up(Sight.of_run(_SHARED), _SHARED)


# --- the count (§11:1 to §11:3) ------------------------------------------------


def test_a_count_carries_numbers_and_codes_and_no_identifier() -> None:
    sight = Sight.of_work(_unidentifieds_message(), (_NO_ONE_SENDS,), activation="a")
    count = sight.count(
        store="memory",
        member="search",
        given=[(_OWNERS, None), (_THEIRS, None), (None, None), (_OWNERS, "a")],
    )
    assert count == SightCount(
        store="memory",
        member="search",
        given=4,
        other_home=1,
        no_home=1,
        sees_nothing=1,
        reader=SightReader.WORK,
        bounds=("anyone", "person_owner"),
    )
    assert set(SightCount.model_fields) == {
        "store",
        "member",
        "given",
        "other_home",
        "no_home",
        "sees_nothing",
        "reader",
        "bounds",
    }

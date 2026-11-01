"""Shared conformance suite for the PersonModelStore Protocol (ADR-0338 §10).

Every ``PersonModelStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PersonModelStoreContract` and
supplies one fixture, ``factory``, which builds a subject as first created: holding the
owner, with a chosen bound on a text field's length and a chosen clock.

The cases follow the contract: one person, the owner (§2:1); a field's write, validated
and logged in the same step (§3:2-§3:5, §10:2); pins and style marks, each a pointer kept
when removed (§4:1-§4:2, §4:7, §5:3); suggestions, and their acceptance by any route
(§8:9, §9:2, §9:5); pointers only (§10:3); and the export and the clear (§10:5). What only
a persistent store owes — the file's mode, surviving a reopen, its upgrade under
ADR-0326, a backend fault — is the store's own test.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final, Protocol
from zoneinfo import ZoneInfo

import pytest

from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.protocols import PersonModelStore
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    InputPart,
    PersonActHow,
    PersonModelAct,
    PersonModelRefusal,
    PersonModelWrite,
    PersonModelWriteKind,
    PersonRole,
    ProfileField,
    ProposedSuggestion,
    QuestionPart,
    SuggestionKind,
    SuggestionState,
    SupportOrigin,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import PersonModel

pytestmark = pytest.mark.anyio

#: The bound on a text field's length every case builds its subject with.
FIELD_CHARS: Final = 40

#: A person the store does not hold.
STRANGER: Final = "person:someone-else"

MEMORY: Final = "memory:diet"
OTHER_MEMORY: Final = "memory:sister"
EPISODE: Final = "activation:act-1"

PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
SEED: Final = PersonModelAct(how=PersonActHow.SEED)
BY_A_YES: Final = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    approval=QuestionPart(round="round:r1", part=1),
    episode_id=EPISODE,
)

#: A yes on a card, run by its ticket: the act names the request, and the episode is the
#: approval's own, where the yes was given (ADR-0362 §2:1).
APPROVAL_EPISODE: Final = "activation:act-approval"
BY_A_TICKET: Final = PersonModelAct(
    how=PersonActHow.APPROVAL,
    by=OWNER_PERSON_ID,
    request="q-1",
    episode_id=APPROVAL_EPISODE,
)

WRITTEN: Final = PersonModelWriteKind.WRITTEN
UNCHANGED: Final = PersonModelWriteKind.UNCHANGED
REFUSED: Final = PersonModelWriteKind.REFUSED


def field_suggestion(
    field: ProfileField, value: str, *, episode: str = EPISODE
) -> ProposedSuggestion:
    """A field suggestion resting on the user's own message in ``episode``.

    Args:
        field: The field.
        value: Its value.
        episode: The episode it rests on.

    Returns:
        The suggestion.
    """
    return ProposedSuggestion(
        kind=SuggestionKind.FIELD,
        field=field,
        value=value,
        episode_id=episode,
        part=InputPart(episode=episode),
        origin=SupportOrigin.USER_MESSAGE,
    )


def pin_suggestion(memory_id: str) -> ProposedSuggestion:
    """A pin suggestion for ``memory_id``.

    Args:
        memory_id: The memory.

    Returns:
        The suggestion.
    """
    return ProposedSuggestion(kind=SuggestionKind.PIN, memory_id=memory_id, episode_id=EPISODE)


def ticking(start: datetime | None = None) -> Callable[[], datetime]:
    """A clock that reads one second later each time.

    Args:
        start: Its first reading.

    Returns:
        The clock.
    """
    first = start or datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
    seconds = count()
    return lambda: first + timedelta(seconds=next(seconds))


class PersonModelStoreFactory(Protocol):
    """Builds a subject as first created, holding the owner."""

    def __call__(
        self, *, field_chars: int = ..., now: Callable[[], datetime] | None = ...
    ) -> PersonModelStore:
        """Build a subject.

        Args:
            field_chars: The bound on a text field's length.
            now: The clock it records instants from, or ``None`` for its own.
        """
        ...


async def owner(store: PersonModelStore) -> PersonModel:
    """The owner's model, which every case's subject holds.

    Args:
        store: The subject.

    Returns:
        The owner's model.
    """
    model = await store.read(OWNER_PERSON_ID)
    assert model is not None
    return model


class PersonModelStoreContract:
    """Behaviour every ``PersonModelStore`` implementation must exhibit (ADR-0338 §10)."""

    @pytest.fixture
    def factory(self) -> PersonModelStoreFactory:
        """Override in a subclass with a builder of conforming subjects."""
        raise NotImplementedError

    @pytest.fixture
    def store(self, factory: PersonModelStoreFactory) -> PersonModelStore:
        """The subject, with the suite's bound and a ticking clock."""
        return factory(field_chars=FIELD_CHARS, now=ticking())

    async def test_the_subject_is_a_person_model_store(self, store: PersonModelStore) -> None:
        assert isinstance(store, PersonModelStore)

    # --- one person, the owner (§2:1) -----------------------------------------------

    async def test_it_holds_the_owner_alone_with_an_empty_profile(
        self, store: PersonModelStore
    ) -> None:
        model = await owner(store)

        assert model.person.id == OWNER_PERSON_ID
        assert model.person.role is PersonRole.OWNER
        assert all(model.profile.value(field) is None for field in ProfileField)
        assert (model.changes, model.pins, model.style_marks, model.suggestions) == (
            (),
            (),
            (),
            (),
        )
        exported = await store.export()
        assert [one.id for one in exported.persons] == [OWNER_PERSON_ID]

    async def test_no_other_person_is_read(self, store: PersonModelStore) -> None:
        assert await store.read(STRANGER) is None

    async def test_every_write_naming_another_person_is_refused_and_writes_nothing(
        self, store: PersonModelStore
    ) -> None:
        before = await store.export()

        writes = [
            await store.set_field(STRANGER, ProfileField.NAME, "Robin", act=PANEL),
            await store.add_pin(STRANGER, MEMORY, act=PANEL),
            await store.remove_pin(STRANGER, "pin:1"),
            await store.add_style_mark(STRANGER, MEMORY),
            await store.remove_style_mark(STRANGER, "mark:1"),
            await store.record_suggestion(STRANGER, pin_suggestion(MEMORY)),
            await store.accept_suggestion(STRANGER, "suggestion:1", by=OWNER_PERSON_ID),
            await store.dismiss_suggestion(STRANGER, "suggestion:1"),
        ]

        assert {one.kind for one in writes} == {REFUSED}
        assert {one.refusal for one in writes} == {PersonModelRefusal.UNKNOWN_PERSON}
        assert await store.export() == before

    async def test_a_blank_id_is_a_value_error(self, store: PersonModelStore) -> None:
        with pytest.raises(ValueError, match="person_id"):
            await store.read("  ")
        with pytest.raises(ValueError, match="memory_id"):
            await store.add_pin(OWNER_PERSON_ID, "", act=PANEL)

    # --- a field's write, in one step (§3:2-§3:5, §10:2) ----------------------------

    async def test_a_field_write_records_its_change_in_the_same_step(
        self, store: PersonModelStore
    ) -> None:
        written = await store.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)

        assert written == PersonModelWrite(kind=WRITTEN)
        model = await owner(store)
        assert model.profile.address == "Robin"
        [change] = model.changes
        assert (change.person_id, change.field, change.old, change.new, change.act) == (
            OWNER_PERSON_ID,
            ProfileField.ADDRESS,
            None,
            "Robin",
            PANEL,
        )

    async def test_each_change_logs_its_old_value_and_the_act_that_made_it(
        self, store: PersonModelStore
    ) -> None:
        await store.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, "Europe/Lisbon", act=SEED)
        await store.set_field(
            OWNER_PERSON_ID, ProfileField.TIME_ZONE, "America/New_York", act=BY_A_YES
        )
        await store.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, None, act=PANEL)

        model = await owner(store)
        assert model.profile.time_zone is None
        assert [(one.old, one.new, one.act) for one in model.changes] == [
            (None, "Europe/Lisbon", SEED),
            ("Europe/Lisbon", "America/New_York", BY_A_YES),
            ("America/New_York", None, PANEL),
        ]
        assert [one.at for one in model.changes] == sorted(one.at for one in model.changes)

    async def test_a_change_made_under_a_ticket_logs_its_request_and_the_approvals_episode(
        self, store: PersonModelStore
    ) -> None:
        """ADR-0362 §2:1, §2:4: the request form's act, held as it was handed."""
        written = await store.set_field(
            OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=BY_A_TICKET
        )

        assert written == PersonModelWrite(kind=WRITTEN)
        [change] = (await owner(store)).changes
        assert change.act == BY_A_TICKET
        assert (change.act.request, change.act.episode_id, change.act.approval) == (
            "q-1",
            APPROVAL_EPISODE,
            None,
        )

    async def test_a_write_of_the_value_held_changes_and_logs_nothing(
        self, store: PersonModelStore
    ) -> None:
        await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
        before = await store.export()

        again = await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
        cleared = await store.set_field(OWNER_PERSON_ID, ProfileField.LANGUAGE, None, act=PANEL)

        assert again.kind is UNCHANGED
        assert cleared.kind is UNCHANGED
        assert await store.export() == before

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            (ProfileField.TIME_ZONE, "Mars/Olympus_Mons"),
            (ProfileField.TIME_ZONE, "../etc/passwd"),
            (ProfileField.NAME, "x" * (FIELD_CHARS + 1)),
            (ProfileField.LANGUAGE, "   "),
        ],
    )
    async def test_a_value_that_fails_validation_is_refused_and_nothing_is_written(
        self, store: PersonModelStore, field: ProfileField, value: str
    ) -> None:
        before = await store.export()

        refused = await store.set_field(OWNER_PERSON_ID, field, value, act=PANEL)

        assert refused.kind is REFUSED
        assert refused.refusal is PersonModelRefusal.INVALID_VALUE
        assert refused.reason
        assert await store.export() == before

    async def test_a_value_at_the_bound_is_taken(self, store: PersonModelStore) -> None:
        value = "x" * FIELD_CHARS

        written = await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, value, act=PANEL)

        assert written.kind is WRITTEN
        assert (await owner(store)).profile.name == value

    async def test_the_bound_is_the_one_the_store_was_built_with(
        self, factory: PersonModelStoreFactory
    ) -> None:
        store = factory(field_chars=FIELD_CHARS + 10)

        written = await store.set_field(
            OWNER_PERSON_ID, ProfileField.NAME, "x" * (FIELD_CHARS + 10), act=PANEL
        )

        assert written.kind is WRITTEN

    @pytest.mark.parametrize("zone", ["é" * 200, "a" * 256], ids=["non-ascii", "ascii"])
    async def test_a_zone_name_the_file_system_refuses_is_an_invalid_value(
        self, factory: PersonModelStoreFactory, zone: str
    ) -> None:
        """§3:2: a name too long for a path is refused as a value, never raised as OSError.

        Built with a bound the name is within, so the zone lookup is what refuses it
        (#3328). Where the file system's ``NAME_MAX`` is 255 bytes, as on Linux and
        macOS, that lookup raises ``OSError`` (ENAMETOOLONG); where it admits the name,
        ``ZoneInfoNotFoundError``. Either way the refusal is the same, so the case
        pins the refusal rather than the platform.
        """
        store = factory(field_chars=len(zone))
        before = await store.export()

        written = await store.set_field(OWNER_PERSON_ID, ProfileField.TIME_ZONE, zone, act=PANEL)
        suggested = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.TIME_ZONE, zone)
        )

        assert written.refusal is PersonModelRefusal.INVALID_VALUE
        assert suggested.refusal is PersonModelRefusal.INVALID_VALUE
        assert await store.export() == before

    async def test_only_accepting_a_suggestion_writes_a_field_as_a_suggestion(
        self, store: PersonModelStore
    ) -> None:
        act = PersonModelAct(how=PersonActHow.SUGGESTION, by=OWNER_PERSON_ID, episode_id=EPISODE)

        refused = await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin", act=act)

        assert refused.refusal is PersonModelRefusal.INVALID_ACT
        assert (await owner(store)).changes == ()

    async def test_a_clock_reading_it_cannot_record_fails_the_write_and_changes_nothing(
        self, factory: PersonModelStoreFactory
    ) -> None:
        """§10:2's one step: a refused reading is a store fault raised before any write."""
        readings = iter([datetime(2026, 10, 21, 9, 0, tzinfo=UTC)] * 2)
        store = factory(
            field_chars=FIELD_CHARS,
            now=lambda: next(readings, datetime(2026, 10, 21, 9, 5)),  # noqa: DTZ001 — the naive reading under test
        )
        await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.NAME, "Robin Vale")
        )
        before = await store.export()

        with pytest.raises(PersonModelStoreError):
            await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)

        assert await store.export() == before

    async def test_an_aware_reading_in_another_zone_is_recorded_in_utc(
        self, factory: PersonModelStoreFactory
    ) -> None:
        lisbon = datetime(2026, 10, 21, 10, 0, tzinfo=ZoneInfo("Europe/Lisbon"))
        store = factory(field_chars=FIELD_CHARS, now=lambda: lisbon)

        await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)

        [change] = (await owner(store)).changes
        assert change.at == lisbon
        assert change.at.utcoffset() == timedelta(0)

    # --- pins (§4:1-§4:2, §4:7) ------------------------------------------------------

    async def test_a_pin_points_at_its_memory_and_records_who_and_how(
        self, store: PersonModelStore
    ) -> None:
        written = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=BY_A_YES)

        assert written.kind is WRITTEN
        [pin] = (await owner(store)).pins
        assert (pin.id, pin.person_id, pin.memory_id, pin.act, pin.removed_at) == (
            written.record_id,
            OWNER_PERSON_ID,
            MEMORY,
            BY_A_YES,
            None,
        )

    async def test_a_pin_made_under_a_ticket_records_its_request(
        self, store: PersonModelStore
    ) -> None:
        """ADR-0362 §2:4: a pin by a yes on a card names the request whose ticket ran it."""
        written = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=BY_A_TICKET)

        assert written.kind is WRITTEN
        [pin] = (await owner(store)).pins
        assert pin.act == BY_A_TICKET

    async def test_unpinning_leaves_the_act_that_made_the_pin(
        self, store: PersonModelStore
    ) -> None:
        """ADR-0362 §2:5, ADR-0338 §4:7: a removed pin gains only when it was removed."""
        for act, memory in ((BY_A_TICKET, MEMORY), (BY_A_YES, OTHER_MEMORY)):
            pinned = await store.add_pin(OWNER_PERSON_ID, memory, act=act)
            assert pinned.record_id is not None
            await store.remove_pin(OWNER_PERSON_ID, pinned.record_id)

        pins = (await owner(store)).pins
        assert [pin.act for pin in pins] == [BY_A_TICKET, BY_A_YES]
        assert all(pin.removed_at is not None for pin in pins)

    async def test_pinning_a_memory_already_pinned_changes_nothing(
        self, store: PersonModelStore
    ) -> None:
        first = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)

        again = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=BY_A_YES)

        assert again == PersonModelWrite(kind=UNCHANGED, record_id=first.record_id)
        assert len((await owner(store)).pins) == 1

    @pytest.mark.parametrize("how", [PersonActHow.SEED, PersonActHow.SUGGESTION])
    async def test_a_pin_is_made_only_on_the_panel_or_by_a_yes(
        self, store: PersonModelStore, how: PersonActHow
    ) -> None:
        act = (
            SEED
            if how is PersonActHow.SEED
            else PersonModelAct(how=how, by=OWNER_PERSON_ID, episode_id=EPISODE)
        )

        refused = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=act)

        assert refused.refusal is PersonModelRefusal.INVALID_ACT
        assert (await owner(store)).pins == ()

    async def test_unpinning_keeps_the_pin_marked_removed(self, store: PersonModelStore) -> None:
        pinned = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        assert pinned.record_id is not None

        removed = await store.remove_pin(OWNER_PERSON_ID, pinned.record_id)
        again = await store.remove_pin(OWNER_PERSON_ID, pinned.record_id)

        assert removed.kind is WRITTEN
        assert again.kind is UNCHANGED
        model = await owner(store)
        [pin] = model.pins
        assert pin.id == pinned.record_id
        assert pin.removed_at is not None
        assert model.standing_pins == ()

    async def test_a_memory_unpinned_is_pinned_again_by_a_new_pin(
        self, store: PersonModelStore
    ) -> None:
        first = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        assert first.record_id is not None
        await store.remove_pin(OWNER_PERSON_ID, first.record_id)

        second = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)

        assert second.kind is WRITTEN
        assert second.record_id != first.record_id
        assert [pin.id for pin in (await owner(store)).standing_pins] == [second.record_id]

    async def test_every_pointer_is_held_verbatim_and_compared_as_given(
        self, store: PersonModelStore
    ) -> None:
        """Two ids that differ only in surrounding space name two memories (§4:1-§4:2)."""
        spaced = f" {MEMORY} "

        first = await store.add_pin(OWNER_PERSON_ID, spaced, act=PANEL)
        again = await store.add_pin(OWNER_PERSON_ID, spaced, act=PANEL)
        other = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        marked = await store.add_style_mark(OWNER_PERSON_ID, spaced)
        suggested = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(MEMORY))

        assert again == PersonModelWrite(kind=UNCHANGED, record_id=first.record_id)
        assert other.kind is WRITTEN
        assert other.record_id != first.record_id
        assert marked.kind is WRITTEN
        # A pin on the spaced id does not stand for the other memory's suggestion.
        assert suggested.kind is UNCHANGED
        model = await owner(store)
        assert [pin.memory_id for pin in model.pins] == [spaced, MEMORY]
        assert [mark.memory_id for mark in model.style_marks] == [spaced]

    async def test_removing_a_pin_not_held_is_refused(self, store: PersonModelStore) -> None:
        refused = await store.remove_pin(OWNER_PERSON_ID, "pin:never")

        assert refused.refusal is PersonModelRefusal.UNKNOWN_RECORD

    async def test_pins_read_in_the_order_made(self, store: PersonModelStore) -> None:
        await store.add_pin(OWNER_PERSON_ID, OTHER_MEMORY, act=PANEL)
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)

        pins = (await owner(store)).pins

        assert [pin.memory_id for pin in pins] == [OTHER_MEMORY, MEMORY]
        assert pins[0].pinned_at < pins[1].pinned_at

    # --- style marks (§5:3, §9:4) ----------------------------------------------------

    async def test_a_style_mark_points_at_its_memory_and_is_made_once(
        self, store: PersonModelStore
    ) -> None:
        written = await store.add_style_mark(OWNER_PERSON_ID, MEMORY)
        again = await store.add_style_mark(OWNER_PERSON_ID, MEMORY)

        assert written.kind is WRITTEN
        assert again == PersonModelWrite(kind=UNCHANGED, record_id=written.record_id)
        [mark] = (await owner(store)).style_marks
        assert (mark.id, mark.memory_id, mark.removed_at) == (written.record_id, MEMORY, None)

    async def test_a_memory_whose_mark_was_removed_is_not_marked_again(
        self, store: PersonModelStore
    ) -> None:
        marked = await store.add_style_mark(OWNER_PERSON_ID, MEMORY)
        assert marked.record_id is not None
        removed = await store.remove_style_mark(OWNER_PERSON_ID, marked.record_id)

        again = await store.add_style_mark(OWNER_PERSON_ID, MEMORY)

        assert removed.kind is WRITTEN
        assert again.kind is UNCHANGED
        model = await owner(store)
        assert len(model.style_marks) == 1
        assert model.standing_marks == ()

    async def test_removing_a_mark_not_held_is_refused(self, store: PersonModelStore) -> None:
        refused = await store.remove_style_mark(OWNER_PERSON_ID, "mark:never")

        assert refused.refusal is PersonModelRefusal.UNKNOWN_RECORD

    # --- suggestions (§8:9, §9:2, §9:5) ----------------------------------------------

    async def test_a_suggestion_is_recorded_pending_and_changes_nothing_in_the_profile(
        self, store: PersonModelStore
    ) -> None:
        proposed = field_suggestion(ProfileField.ADDRESS, "Robin")

        written = await store.record_suggestion(OWNER_PERSON_ID, proposed)

        assert written.kind is WRITTEN
        model = await owner(store)
        [suggestion] = model.suggestions
        assert (suggestion.id, suggestion.proposed, suggestion.state) == (
            written.record_id,
            proposed,
            SuggestionState.PENDING,
        )
        assert model.profile.address is None
        assert model.changes == ()

    async def test_a_suggestion_the_profile_already_holds_is_not_recorded(
        self, store: PersonModelStore
    ) -> None:
        await store.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)

        again = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )

        assert again.kind is UNCHANGED
        assert (await owner(store)).suggestions == ()

    async def test_an_equal_suggestion_pending_or_dismissed_stops_another(
        self, store: PersonModelStore
    ) -> None:
        first = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )
        assert first.record_id is not None
        pending = await store.record_suggestion(
            OWNER_PERSON_ID,
            field_suggestion(ProfileField.ADDRESS, "Robin", episode="activation:act-2"),
        )
        await store.dismiss_suggestion(OWNER_PERSON_ID, first.record_id)
        dismissed = await store.record_suggestion(
            OWNER_PERSON_ID,
            field_suggestion(ProfileField.ADDRESS, "Robin", episode="activation:act-3"),
        )

        assert pending == PersonModelWrite(kind=UNCHANGED, record_id=first.record_id)
        assert dismissed == PersonModelWrite(kind=UNCHANGED, record_id=first.record_id)
        assert (await owner(store)).suggestions == ()

    async def test_a_pin_suggestion_for_a_memory_pinned_is_not_recorded(
        self, store: PersonModelStore
    ) -> None:
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)

        again = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(MEMORY))

        assert again.kind is UNCHANGED

    async def test_a_field_suggestion_with_an_invalid_value_is_refused(
        self, store: PersonModelStore
    ) -> None:
        refused = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.TIME_ZONE, "Atlantis/Central")
        )

        assert refused.refusal is PersonModelRefusal.INVALID_VALUE
        assert (await owner(store)).suggestions == ()

    async def test_a_field_taking_a_suggestions_value_by_any_route_accepts_it(
        self, store: PersonModelStore
    ) -> None:
        recorded = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )

        await store.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)

        model = await owner(store)
        assert model.suggestions == ()
        [suggestion] = (await store.export()).suggestions
        assert (suggestion.id, suggestion.state) == (recorded.record_id, SuggestionState.ACCEPTED)
        assert suggestion.decided_at is not None

    async def test_pinning_a_suggested_memory_by_any_route_accepts_the_suggestion(
        self, store: PersonModelStore
    ) -> None:
        await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(MEMORY))

        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=BY_A_YES)

        [suggestion] = (await store.export()).suggestions
        assert suggestion.state is SuggestionState.ACCEPTED

    async def test_accepting_a_field_suggestion_writes_and_logs_it_as_one(
        self, store: PersonModelStore
    ) -> None:
        recorded = await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.LANGUAGE, "Português")
        )
        assert recorded.record_id is not None

        accepted = await store.accept_suggestion(
            OWNER_PERSON_ID, recorded.record_id, by=OWNER_PERSON_ID
        )

        assert accepted == PersonModelWrite(kind=WRITTEN, record_id=recorded.record_id)
        model = await owner(store)
        assert model.profile.language == "Português"
        assert model.suggestions == ()
        [change] = model.changes
        assert change.act == PersonModelAct(
            how=PersonActHow.SUGGESTION, by=OWNER_PERSON_ID, episode_id=EPISODE
        )
        assert change.suggestion_id == recorded.record_id

    async def test_accepting_a_pin_suggestion_pins_its_memory_as_on_the_panel(
        self, store: PersonModelStore
    ) -> None:
        recorded = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(MEMORY))
        assert recorded.record_id is not None

        accepted = await store.accept_suggestion(
            OWNER_PERSON_ID, recorded.record_id, by=OWNER_PERSON_ID
        )

        assert accepted.kind is WRITTEN
        [pin] = (await owner(store)).pins
        assert (pin.memory_id, pin.act) == (MEMORY, PANEL)

    async def test_a_suggestion_decided_is_not_decided_again(self, store: PersonModelStore) -> None:
        recorded = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(MEMORY))
        assert recorded.record_id is not None
        await store.dismiss_suggestion(OWNER_PERSON_ID, recorded.record_id)
        before = await store.export()

        accepted = await store.accept_suggestion(
            OWNER_PERSON_ID, recorded.record_id, by=OWNER_PERSON_ID
        )
        dismissed = await store.dismiss_suggestion(OWNER_PERSON_ID, recorded.record_id)

        assert accepted.refusal is PersonModelRefusal.ALREADY_DECIDED
        assert dismissed.refusal is PersonModelRefusal.ALREADY_DECIDED
        assert await store.export() == before

    async def test_deciding_a_suggestion_not_held_is_refused(self, store: PersonModelStore) -> None:
        accepted = await store.accept_suggestion(
            OWNER_PERSON_ID, "suggestion:never", by=OWNER_PERSON_ID
        )
        dismissed = await store.dismiss_suggestion(OWNER_PERSON_ID, "suggestion:never")

        assert accepted.refusal is PersonModelRefusal.UNKNOWN_RECORD
        assert dismissed.refusal is PersonModelRefusal.UNKNOWN_RECORD

    # --- pointers only (§10:3) --------------------------------------------------------

    async def test_it_holds_only_what_it_was_handed_and_its_own_ids_and_instants(
        self, factory: PersonModelStoreFactory
    ) -> None:
        clock = ticking()
        readings: list[datetime] = []

        def now() -> datetime:
            readings.append(clock())
            return readings[-1]

        store = factory(field_chars=FIELD_CHARS, now=now)
        written = [
            await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=BY_A_YES),
            await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL),
            await store.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY),
            await store.record_suggestion(
                OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
            ),
            await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY)),
        ]
        handed = {
            OWNER_PERSON_ID,
            "Robin Vale",
            "Robin",
            MEMORY,
            OTHER_MEMORY,
            EPISODE,
            "round:r1",
        }
        minted = {one.record_id for one in written if one.record_id is not None}
        instants = {one.isoformat().replace("+00:00", "Z") for one in readings} | {
            one.isoformat() for one in readings
        }
        vocabulary = {
            str(member.value)
            for enum in (PersonActHow, PersonRole, ProfileField, SuggestionKind, SuggestionState)
            for member in enum
        } | {"input", SupportOrigin.USER_MESSAGE.value}

        exported = (await store.export()).model_dump(mode="json")

        held = set(_strings(exported))
        assert held <= handed | minted | instants | vocabulary, held - (
            handed | minted | instants | vocabulary
        )

    # --- the export and the clear (§10:5) --------------------------------------------

    async def test_the_export_carries_every_record(self, store: PersonModelStore) -> None:
        await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
        await store.set_field(OWNER_PERSON_ID, ProfileField.LANGUAGE, "Portuguese", act=BY_A_TICKET)
        await store.add_pin(OWNER_PERSON_ID, "memory:tea", act=BY_A_TICKET)
        pinned = await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        assert pinned.record_id is not None
        await store.remove_pin(OWNER_PERSON_ID, pinned.record_id)
        await store.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY)
        dismissed = await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY))
        assert dismissed.record_id is not None
        await store.dismiss_suggestion(OWNER_PERSON_ID, dismissed.record_id)
        await store.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )

        exported = await store.export()
        model = await owner(store)

        assert exported.persons == (model.person,)
        assert exported.profiles == ((OWNER_PERSON_ID, model.profile),)
        assert exported.changes == model.changes
        assert exported.pins == model.pins
        assert [one.act for one in exported.changes][-1] == BY_A_TICKET
        assert exported.pins[0].act == BY_A_TICKET
        assert exported.style_marks == model.style_marks
        assert [one.state for one in exported.suggestions] == [
            SuggestionState.DISMISSED,
            SuggestionState.PENDING,
        ]

    async def test_clear_erases_every_record_the_owner_included(
        self, store: PersonModelStore
    ) -> None:
        await store.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
        await store.add_pin(OWNER_PERSON_ID, MEMORY, act=PANEL)
        await store.add_style_mark(OWNER_PERSON_ID, OTHER_MEMORY)
        await store.record_suggestion(OWNER_PERSON_ID, pin_suggestion(OTHER_MEMORY))

        erased = await store.clear()

        assert erased >= 5  # the person and the four records written
        exported = await store.export()
        assert exported.model_dump() == type(exported)().model_dump()
        assert await store.read(OWNER_PERSON_ID) is None


def _strings(value: object) -> list[str]:
    """Every string in a JSON value, keys excepted."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [one for item in value.values() for one in _strings(item)]
    if isinstance(value, list):
        return [one for item in value for one in _strings(item)]
    return []

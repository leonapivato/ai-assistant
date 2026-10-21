"""Shared obligations of ``AssistantEngine``'s person-model members (ADR-0338 §8:1-§8:3).

Every implementation answers the About you panel's read and the panels' writes from the
same two stores — the person-model store and the memory store — and every one refuses
them alike where the hub keeps no person model (§11:2). A subject is handed to the suite
built one way or the other, since whether a store is wired is the composition root's,
and no call on the surface changes it.

The engine and the canonical fake answer through orchestration's person-panel module
over the person block's assembly, and the wire client through a hub serving the fake,
so a clause here holds the slot's composition, the checked pin and the switch's refusal
against three surfaces.

A mixin, as ``pending_candidates_contract`` is, so the engine, the canonical fake and
the wire client each bind it in the file that binds the rest of the suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import OversizedValueError, PersonModelOffError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    InputPart,
    LeftOutMemory,
    LeftOutReason,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemoryWriterName,
    PersonActHow,
    PersonModelEdit,
    PersonModelEditRefusal,
    PersonModelRefusal,
    PersonModelWriteKind,
    ProfileField,
    ProposedSuggestion,
    SuggestionKind,
    SupportOrigin,
    Validity,
)
from ai_assistant.orchestration.person_panel import PANEL_ACT
from ai_assistant.testing import FakeMemoryStore, FakePersonModelStore
from ai_assistant.testing.memories import memory, remembered_support, said_support

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import Memory, PersonModelView

#: The contract limit each subject is built at: room for a person's model with a few
#: records, and small enough that an argument can be made past it.
PERSON_LIMIT: Final = 8192

#: The kept-in-mind slot's budget each subject is built with: small, so a pin or a
#: style memory reaches past it cheaply. The deployment's is lane 1's 1,600 (§6:1).
PERSON_BUDGET: Final = 60

#: The instant each subject's memory store reads, after every memory here was made.
PERSON_AT: Final = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)

_WRITTEN: Final = PersonModelWriteKind.WRITTEN
_UNCHANGED: Final = PersonModelWriteKind.UNCHANGED
_REFUSED: Final = PersonModelWriteKind.REFUSED


@dataclass(frozen=True, slots=True)
class PersonModelSubject:
    """An engine and the two stores its person-model members read, seeded from the test.

    Attributes:
        engine: The subject under test.
        people: The person-model store, holding the owner as first created.
        memory: The memory store the pins and marks point into.
    """

    engine: AssistantEngine
    people: FakePersonModelStore
    memory: FakeMemoryStore


def person_model_stores() -> tuple[FakePersonModelStore, FakeMemoryStore]:
    """The two stores a subject is built over: the person-model store's clock ticks a
    second per reading from :data:`PERSON_AT`, and the memory store reads that instant."""
    seconds = count()
    people = FakePersonModelStore(now=lambda: PERSON_AT + timedelta(seconds=next(seconds)))
    return people, FakeMemoryStore(now=lambda: PERSON_AT)


def fact(record_id: str, content: str, **envelope: object) -> Memory:
    """A current memory the user said."""
    return memory(record_id, content, said_support(), **envelope)


def outside(record_id: str, content: str) -> Memory:
    """A current memory resting on outside content (ADR-0328 §7:6)."""
    return memory(record_id, content, remembered_support(outside=True))


def ended(record_id: str, content: str, *, successor: str | None) -> Memory:
    """A memory ended, naming ``successor`` or none, its window closed as the writer leaves it."""
    support = said_support()
    at = support.added_at
    return memory(
        record_id,
        content,
        support,
        operations=(
            MemoryOperation(
                kind=MemoryOperationKind.CREATE, cites=support.points_at, at=at, by=support.added_by
            ),
            MemoryOperation(
                kind=MemoryOperationKind.END,
                cites=support.points_at,
                at=at,
                by=MemoryWriterName.OBSERVER,
                successor=successor,
            ),
        ),
        status=MemoryStatus.ENDED,
        validity=Validity(valid_until=at),
    )


def field_suggestion(
    field: ProfileField, value: str, origin: SupportOrigin = SupportOrigin.USER_MESSAGE
) -> ProposedSuggestion:
    """A field suggestion resting on an episode's input, with ``origin``."""
    return ProposedSuggestion(
        kind=SuggestionKind.FIELD,
        field=field,
        value=value,
        episode_id="activation:a1",
        part=InputPart(episode="activation:a1"),
        origin=origin,
    )


def pin_suggestion(memory_id: str) -> ProposedSuggestion:
    """A pin suggestion of ``memory_id``."""
    return ProposedSuggestion(
        kind=SuggestionKind.PIN, memory_id=memory_id, episode_id="activation:a1"
    )


async def _held(subject: PersonModelSubject, *records: Memory) -> None:
    for record in records:
        await subject.memory.add(record)


async def _read(subject: PersonModelSubject) -> PersonModelView:
    view = await subject.engine.person_model(OWNER_PERSON_ID)
    assert view is not None
    return view


def _write(edit: PersonModelEdit) -> tuple[PersonModelWriteKind, PersonModelRefusal | None]:
    assert edit.write is not None, edit
    return edit.write.kind, edit.write.refusal


#: Each member, called once with ids of the owner's and well-formed arguments, by name.
_MEMBERS: Final[dict[str, Callable[[AssistantEngine], Awaitable[Any]]]] = {
    "person_model": lambda engine: engine.person_model(OWNER_PERSON_ID),
    "profile_changes": lambda engine: engine.profile_changes(OWNER_PERSON_ID),
    "set_profile_field": lambda engine: engine.set_profile_field(
        OWNER_PERSON_ID, field=ProfileField.NAME, value="Robin"
    ),
    "pin_memory": lambda engine: engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet"),
    "unpin_memory": lambda engine: engine.unpin_memory(OWNER_PERSON_ID, memory_id="m:diet"),
    "remove_style_mark": lambda engine: engine.remove_style_mark(OWNER_PERSON_ID, mark_id="mark:1"),
    "accept_person_suggestion": lambda engine: engine.accept_person_suggestion(
        OWNER_PERSON_ID, suggestion_id="suggestion:1"
    ),
    "dismiss_person_suggestion": lambda engine: engine.dismiss_person_suggestion(
        OWNER_PERSON_ID, suggestion_id="suggestion:1"
    ),
}

#: Each member, called with a blank person id.
_BLANK: Final[dict[str, Callable[[AssistantEngine], Awaitable[Any]]]] = {
    "person_model": lambda engine: engine.person_model("  "),
    "profile_changes": lambda engine: engine.profile_changes("  "),
    "set_profile_field": lambda engine: engine.set_profile_field(
        "  ", field=ProfileField.NAME, value="Robin"
    ),
    "pin_memory": lambda engine: engine.pin_memory("  ", memory_id="m:diet"),
    "unpin_memory": lambda engine: engine.unpin_memory("  ", memory_id="m:diet"),
    "remove_style_mark": lambda engine: engine.remove_style_mark("  ", mark_id="mark:1"),
    "accept_person_suggestion": lambda engine: engine.accept_person_suggestion(
        "  ", suggestion_id="suggestion:1"
    ),
    "dismiss_person_suggestion": lambda engine: engine.dismiss_person_suggestion(
        "  ", suggestion_id="suggestion:1"
    ),
}


class PersonModelContract:
    """The panels' members through the engine, the fake and the wire client alike."""

    @pytest.fixture
    def person_model_subject(self) -> PersonModelSubject:
        """Override with an implementation whose person-model store is wired.

        Built at :data:`PERSON_LIMIT`, its slot's budget :data:`PERSON_BUDGET`, its
        memory store clocked at :data:`PERSON_AT`.
        """
        raise NotImplementedError

    @pytest.fixture
    def person_model_off(self) -> PersonModelSubject:
        """Override with the same, built with no person-model store wired (§11:2)."""
        raise NotImplementedError

    # --- the switch (§11:2) ------------------------------------------------------

    @pytest.mark.parametrize("member", sorted(_MEMBERS))
    async def test_with_no_store_wired_each_member_refuses_as_not_switched_on(
        self, person_model_off: PersonModelSubject, member: str
    ) -> None:
        """A typed refusal a client shows as "not switched on", and nothing is written."""
        subject = person_model_off
        await _held(subject, fact("m:diet", "Eats no meat."))

        with pytest.raises(PersonModelOffError):
            await _MEMBERS[member](subject.engine)

        held = await subject.people.read(OWNER_PERSON_ID)
        assert held is not None
        assert (held.changes, held.pins) == ((), ())

    @pytest.mark.parametrize("member", sorted(_BLANK))
    @pytest.mark.parametrize("wired", [True, False], ids=["on", "off"])
    async def test_a_blank_person_id_is_refused_locally_whether_or_not_it_is_on(
        self,
        person_model_subject: PersonModelSubject,
        person_model_off: PersonModelSubject,
        member: str,
        *,
        wired: bool,
    ) -> None:
        """ADR-0085 §9: a malformed argument is refused first, by every implementation."""
        subject = person_model_subject if wired else person_model_off

        with pytest.raises(ValueError, match="person_id"):
            await _BLANK[member](subject.engine)

    # --- the read (§8:1) ---------------------------------------------------------

    async def test_the_owner_as_first_created_reads_empty(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        view = await _read(person_model_subject)

        assert view.person.id == OWNER_PERSON_ID
        assert view.profile.name is None
        assert view.budget_chars == PERSON_BUDGET
        assert (view.kept, view.left_out) == ((), ())
        assert await person_model_subject.engine.profile_changes(OWNER_PERSON_ID) == ()
        assert (view.no_longer_current, view.style_marks, view.suggestions) == ((), (), ())

    async def test_a_person_the_hub_does_not_hold_reads_none(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        assert await person_model_subject.engine.person_model("person:someone") is None

    async def test_an_id_is_never_stripped(self, person_model_subject: PersonModelSubject) -> None:
        """§10:4: an id is held verbatim, so a padded one names no person."""
        assert await person_model_subject.engine.person_model(f" {OWNER_PERSON_ID} ") is None

    async def test_the_slot_is_pins_oldest_first_then_style_newest_marked_first(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§6:2: pinned first, then style; each memory once; with its wording and fill."""
        subject = person_model_subject
        await _held(
            subject,
            fact("m:diet", "Eats no meat."),
            fact("m:ada", "Sister Ada."),
            fact("m:brief", "Short answers."),
            fact("m:dry", "Dry jokes."),
        )
        for one in ("m:diet", "m:ada"):
            assert _write(await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id=one)) == (
                _WRITTEN,
                None,
            )
        for one in ("m:brief", "m:dry", "m:diet"):
            await subject.people.add_style_mark(OWNER_PERSON_ID, one)

        view = await _read(subject)

        assert [(one.memory_id, one.content, one.pinned) for one in view.kept] == [
            ("m:diet", "Eats no meat.", True),
            ("m:ada", "Sister Ada.", True),
            ("m:dry", "Dry jokes.", False),
            ("m:brief", "Short answers.", False),
        ]
        assert view.kept_chars == sum(len(one.content) for one in view.kept)
        assert [(one.mark.memory_id, one.shows) for one in view.style_marks] == [
            ("m:brief", "m:brief"),
            ("m:dry", "m:dry"),
            ("m:diet", "m:diet"),
        ]

    async def test_the_slot_stops_at_the_budget_and_says_what_it_left_out(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§6:2: it stops before the first wording past the budget; the rest is left out."""
        subject = person_model_subject
        await _held(
            subject,
            fact("m:long", "x" * (PERSON_BUDGET - 10)),
            fact("m:wide", "y" * 20),
            fact("m:tiny", "z"),
        )
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:long")
        for one in ("m:tiny", "m:wide"):
            await subject.people.add_style_mark(OWNER_PERSON_ID, one)

        view = await _read(subject)

        assert [one.memory_id for one in view.kept] == ["m:long"]
        assert view.left_out == (
            LeftOutMemory(memory_id="m:wide", pinned=False, reason=LeftOutReason.BUDGET),
            LeftOutMemory(memory_id="m:tiny", pinned=False, reason=LeftOutReason.BUDGET),
        )

    async def test_a_memory_resting_on_outside_content_is_left_out_for_it(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§6:4: no slot shows it, and the panel says why; it costs the budget nothing."""
        subject = person_model_subject
        await _held(
            subject,
            outside("m:out", "The shop closes at six, its page says."),
            fact("m:diet", "Eats no meat."),
        )
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:out")
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")

        view = await _read(subject)

        assert [one.memory_id for one in view.kept] == ["m:diet"]
        assert view.left_out == (
            LeftOutMemory(memory_id="m:out", pinned=True, reason=LeftOutReason.OUTSIDE_CONTENT),
        )

    async def test_a_pin_shows_its_memorys_current_successor(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§4:8: a pin on an ended memory naming a successor shows the successor."""
        subject = person_model_subject
        await _held(
            subject,
            ended("m:old", "Lives in Porto.", successor="m:new"),
            fact("m:new", "Lives in Lisbon."),
        )
        # Pinned while current, and ended since: the pin is seeded as it stands then.
        await subject.people.add_pin(OWNER_PERSON_ID, "m:old", act=PANEL_ACT)

        view = await _read(subject)

        assert [(one.memory_id, one.content) for one in view.kept] == [
            ("m:new", "Lives in Lisbon.")
        ]
        assert view.no_longer_current == ()

    async def test_a_style_mark_names_the_memory_it_shows_or_words_the_one_it_was_on(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§5:3: a mark follows its memory's successor; the panel ties each to its control."""
        subject = person_model_subject
        await _held(
            subject,
            ended("m:long", "Likes long answers.", successor="m:short"),
            fact("m:short", "Likes short answers."),
            ended("m:jokes", "Likes puns.", successor=None),
        )
        followed = await subject.people.add_style_mark(OWNER_PERSON_ID, "m:long")
        ended_mark = await subject.people.add_style_mark(OWNER_PERSON_ID, "m:jokes")

        view = await _read(subject)

        assert [(one.mark.id, one.shows, one.content) for one in view.style_marks] == [
            (followed.record_id, "m:short", None),
            (ended_mark.record_id, None, "Likes puns."),
        ]
        assert [(one.memory_id, one.pinned) for one in view.kept] == [("m:short", False)]

    async def test_a_pin_reaching_no_current_memory_is_no_longer_current_until_removed(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§4:8: shown in no block, and on the panel as no longer current; unpin removes it."""
        subject = person_model_subject
        await _held(subject, ended("m:old", "Lives in Porto.", successor=None))
        await subject.people.add_pin(OWNER_PERSON_ID, "m:old", act=PANEL_ACT)

        view = await _read(subject)

        assert view.kept == ()
        assert view.left_out == ()
        assert [(one.pin.memory_id, one.content) for one in view.no_longer_current] == [
            ("m:old", "Lives in Porto.")
        ]

        unpinned = await subject.engine.unpin_memory(OWNER_PERSON_ID, memory_id="m:old")

        assert _write(unpinned) == (_WRITTEN, None)
        assert (await _read(subject)).no_longer_current == ()

    async def test_a_pin_or_mark_whose_memory_is_gone_is_shown_nowhere(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§4:10: not in the slot, not left out, not stale, not among the marks."""
        subject = person_model_subject
        await _held(subject, fact("m:diet", "Eats no meat."), fact("m:brief", "Short answers."))
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")
        await subject.people.add_style_mark(OWNER_PERSON_ID, "m:brief")
        await subject.memory.delete("m:diet")
        await subject.memory.delete("m:brief")

        view = await _read(subject)

        assert (view.kept, view.left_out, view.no_longer_current, view.style_marks) == (
            (),
            (),
            (),
            (),
        )

    async def test_suggestions_are_newest_first_each_marked_where_it_rests_on_outside_content(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§7:9: the panel shows every pending one, marked; §9:5: a pin's only while current."""
        subject = person_model_subject
        await _held(
            subject,
            fact("m:diet", "Eats no meat."),
            outside("m:out", "The newsletter says Robin likes jazz."),
            ended("m:old", "Lives in Porto.", successor=None),
        )
        for proposed in (
            field_suggestion(ProfileField.ADDRESS, "Robin"),
            field_suggestion(ProfileField.NAME, "Rob", SupportOrigin.OUTSIDE_INPUT),
            pin_suggestion("m:diet"),
            pin_suggestion("m:out"),
            pin_suggestion("m:old"),
            pin_suggestion("m:gone"),
        ):
            await subject.people.record_suggestion(OWNER_PERSON_ID, proposed)

        view = await _read(subject)

        assert [
            (
                one.suggestion.proposed.field or one.suggestion.proposed.memory_id,
                one.rests_on_outside_content,
            )
            for one in view.suggestions
        ] == [
            ("m:out", True),
            ("m:diet", False),
            (ProfileField.NAME, True),
            (ProfileField.ADDRESS, False),
        ]

    # --- the fields (§3) ---------------------------------------------------------

    async def test_setting_a_field_writes_it_and_logs_a_panel_act_by_the_owner(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        subject = person_model_subject
        edit = await subject.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.TIME_ZONE, value="Europe/Lisbon"
        )

        assert _write(edit) == (_WRITTEN, None)
        view = await _read(subject)
        assert view.profile.time_zone == "Europe/Lisbon"
        (change,) = await subject.engine.profile_changes(OWNER_PERSON_ID)
        assert (change.field, change.old, change.new) == (
            ProfileField.TIME_ZONE,
            None,
            "Europe/Lisbon",
        )
        assert (change.act.how, change.act.by) == (PersonActHow.PANEL, OWNER_PERSON_ID)

    async def test_a_field_named_by_its_value_is_the_same_field(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        subject = person_model_subject
        edit = await subject.engine.set_profile_field(
            OWNER_PERSON_ID,
            field="address",  # type: ignore[arg-type]  # a client's spelling, refused or read
            value="Robin",
        )

        assert _write(edit) == (_WRITTEN, None)
        assert (await _read(subject)).profile.address == "Robin"

    async def test_a_field_that_is_none_of_the_five_is_refused_locally(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        with pytest.raises(ValueError, match="field"):
            await person_model_subject.engine.set_profile_field(
                OWNER_PERSON_ID,
                field="pronouns",  # type: ignore[arg-type]  # §12: not a field
                value="they",
            )

    async def test_an_invalid_value_is_refused_with_its_reason_and_nothing_written(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§3:2: a zone ``zoneinfo`` does not resolve is refused by the store."""
        subject = person_model_subject
        edit = await subject.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.TIME_ZONE, value="Mars/Olympus"
        )

        assert edit.write is not None
        assert (edit.write.kind, edit.write.refusal) == (
            _REFUSED,
            PersonModelRefusal.INVALID_VALUE,
        )
        assert edit.write.reason
        assert await subject.engine.profile_changes(OWNER_PERSON_ID) == ()

    async def test_setting_the_value_held_changes_nothing_and_clearing_logs_it(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§3:3: the same value logs nothing; ``None`` clears, logged."""
        subject = person_model_subject
        await subject.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.NAME, value="Rob"
        )

        again = await subject.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.NAME, value="Rob"
        )
        cleared = await subject.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.NAME, value=None
        )

        assert _write(again) == (_UNCHANGED, None)
        assert _write(cleared) == (_WRITTEN, None)
        view = await _read(subject)
        assert view.profile.name is None
        changes = await subject.engine.profile_changes(OWNER_PERSON_ID)
        assert [(one.old, one.new) for one in changes] == [("Rob", None), (None, "Rob")]

    async def test_a_field_of_a_person_the_hub_does_not_hold_is_refused(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        edit = await person_model_subject.engine.set_profile_field(
            "person:someone", field=ProfileField.NAME, value="Rob"
        )

        assert _write(edit) == (_REFUSED, PersonModelRefusal.UNKNOWN_PERSON)

    async def test_the_change_log_is_paged_most_recent_first(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§3:5: every change, a page at a time, the most recent first."""
        subject = person_model_subject
        for index in range(5):
            await subject.engine.set_profile_field(
                OWNER_PERSON_ID, field=ProfileField.NAME, value=f"Robin {index}"
            )

        first = await subject.engine.profile_changes(OWNER_PERSON_ID, limit=2)
        second = await subject.engine.profile_changes(OWNER_PERSON_ID, limit=2, offset=2)
        rest = await subject.engine.profile_changes(OWNER_PERSON_ID, offset=4)
        past = await subject.engine.profile_changes(OWNER_PERSON_ID, offset=1000)

        assert [one.new for one in first] == ["Robin 4", "Robin 3"]
        assert [one.new for one in second] == ["Robin 2", "Robin 1"]
        assert [(one.old, one.new) for one in rest] == [(None, "Robin 0")]
        assert past == ()

    async def test_a_long_change_log_never_makes_the_model_unreadable(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """The log grows without bound, and the model's read does not carry it."""
        subject = person_model_subject
        value = "R" * 150
        for index in range(PERSON_LIMIT // len(value) + 5):
            await subject.engine.set_profile_field(
                OWNER_PERSON_ID, field=ProfileField.NAME, value=f"{value}{index}"
            )

        view = await _read(subject)

        assert view.profile.name is not None
        assert view.profile.name.startswith(value)

    async def test_a_change_log_page_of_a_person_the_hub_does_not_hold_is_empty(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        assert await person_model_subject.engine.profile_changes("person:someone") == ()

    @pytest.mark.parametrize(("limit", "offset"), [(-1, 0), (0, -1)])
    async def test_a_malformed_change_log_page_is_refused_locally(
        self, person_model_subject: PersonModelSubject, limit: int, offset: int
    ) -> None:
        """ADR-0085 §9, as every paged read on the surface refuses one."""
        with pytest.raises(ValueError, match=r"limit|offset"):
            await person_model_subject.engine.profile_changes(
                OWNER_PERSON_ID, limit=limit, offset=offset
            )

    # --- pins (§4) ---------------------------------------------------------------

    async def test_pinning_a_current_memory_writes_once(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§4:2: a memory already pinned changes nothing; the pin is the panel's."""
        subject = person_model_subject
        await _held(subject, fact("m:diet", "Eats no meat."))

        first = await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")
        again = await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")

        assert _write(first) == (_WRITTEN, None)
        assert _write(again) == (_UNCHANGED, None)
        assert first.write is not None
        assert again.write is not None
        assert first.write.record_id == again.write.record_id
        held = await subject.people.read(OWNER_PERSON_ID)
        assert held is not None
        (pin,) = held.pins
        assert (pin.act.how, pin.act.by) == (PersonActHow.PANEL, OWNER_PERSON_ID)

    @pytest.mark.parametrize("which", ["missing", "ended"])
    async def test_only_a_current_memory_is_pinned(
        self, person_model_subject: PersonModelSubject, which: str
    ) -> None:
        """§4:2: refused before any write."""
        subject = person_model_subject
        await _held(subject, ended("m:ended", "Lives in Porto.", successor=None))

        edit = await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id=f"m:{which}")

        assert edit == PersonModelEdit(refused=PersonModelEditRefusal.NOT_CURRENT)
        held = await subject.people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.pins == ()

    async def test_a_pin_past_the_budget_is_refused_and_nothing_written(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§6:3: the pins' wordings with the new one's must stay within the budget."""
        subject = person_model_subject
        await _held(subject, fact("m:long", "x" * (PERSON_BUDGET - 5)), fact("m:more", "y" * 10))
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:long")

        edit = await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:more")

        assert edit == PersonModelEdit(refused=PersonModelEditRefusal.OVER_BUDGET)
        assert [one.memory_id for one in (await _read(subject)).kept] == ["m:long"]

    async def test_a_pin_for_a_person_the_hub_does_not_hold_is_refused(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        subject = person_model_subject
        await _held(subject, fact("m:diet", "Eats no meat."))

        edit = await subject.engine.pin_memory("person:someone", memory_id="m:diet")

        assert _write(edit) == (_REFUSED, PersonModelRefusal.UNKNOWN_PERSON)

    async def test_unpinning_removes_the_pin_and_erases_nothing(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§4:7: the pin is kept, marked removed, and the memory stays."""
        subject = person_model_subject
        await _held(subject, fact("m:diet", "Eats no meat."))
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:diet")

        removed = await subject.engine.unpin_memory(OWNER_PERSON_ID, memory_id="m:diet")
        again = await subject.engine.unpin_memory(OWNER_PERSON_ID, memory_id="m:diet")

        assert _write(removed) == (_WRITTEN, None)
        assert _write(again) == (_UNCHANGED, None)
        assert (await _read(subject)).kept == ()
        held = await subject.people.read(OWNER_PERSON_ID)
        assert held is not None
        (pin,) = held.pins
        assert pin.removed_at is not None
        assert "m:diet" in await subject.memory.get_many(["m:diet"])

    async def test_unpinning_a_successor_removes_the_pin_that_shows_it(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§4:8: a pin shows its chain's current end, so naming that end unpins it."""
        subject = person_model_subject
        await _held(
            subject,
            ended("m:old", "Lives in Porto.", successor="m:new"),
            fact("m:new", "Lives in Lisbon."),
        )
        # Pinned while current, and ended since: the pin is seeded as it stands then.
        await subject.people.add_pin(OWNER_PERSON_ID, "m:old", act=PANEL_ACT)

        edit = await subject.engine.unpin_memory(OWNER_PERSON_ID, memory_id="m:new")

        assert _write(edit) == (_WRITTEN, None)
        assert (await _read(subject)).kept == ()

    async def test_a_pin_id_past_the_limit_is_refused_before_anything_is_written(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """ADR-0085 §8c: the size limit binds these arguments as every other's."""
        subject = person_model_subject

        with pytest.raises(OversizedValueError):
            await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m" * PERSON_LIMIT)

        held = await subject.people.read(OWNER_PERSON_ID)
        assert held is not None
        assert held.pins == ()

    # --- style marks (§5:3) ------------------------------------------------------

    async def test_removing_a_style_mark_keeps_it_removed(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        subject = person_model_subject
        await _held(subject, fact("m:brief", "Short answers."))
        marked = await subject.people.add_style_mark(OWNER_PERSON_ID, "m:brief")
        assert marked.record_id is not None

        removed = await subject.engine.remove_style_mark(OWNER_PERSON_ID, mark_id=marked.record_id)
        again = await subject.engine.remove_style_mark(OWNER_PERSON_ID, mark_id=marked.record_id)
        unknown = await subject.engine.remove_style_mark(OWNER_PERSON_ID, mark_id="mark:none")

        assert _write(removed) == (_WRITTEN, None)
        assert _write(again) == (_UNCHANGED, None)
        assert _write(unknown) == (_REFUSED, PersonModelRefusal.UNKNOWN_RECORD)
        view = await _read(subject)
        assert (view.kept, view.style_marks) == ((), ())

    # --- suggestions (§8:8, §9:2, §9:5) ------------------------------------------

    async def test_accepting_a_field_suggestion_writes_it_as_the_suggestions(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§3:5: logged as an accepted suggestion, naming the episode it rests on."""
        subject = person_model_subject
        recorded = await subject.people.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )
        assert recorded.record_id is not None

        edit = await subject.engine.accept_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=recorded.record_id
        )

        assert _write(edit) == (_WRITTEN, None)
        view = await _read(subject)
        assert view.profile.address == "Robin"
        (change,) = await subject.engine.profile_changes(OWNER_PERSON_ID)
        assert (change.act.how, change.act.episode_id, change.suggestion_id) == (
            PersonActHow.SUGGESTION,
            "activation:a1",
            recorded.record_id,
        )
        assert view.suggestions == ()

    async def test_accepting_a_pin_suggestion_pins_its_memory_and_accepts_it(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§8:8: the pin accepts the suggestion in the same write; the pin is the panel's."""
        subject = person_model_subject
        await _held(subject, fact("m:diet", "Eats no meat."))
        recorded = await subject.people.record_suggestion(OWNER_PERSON_ID, pin_suggestion("m:diet"))
        assert recorded.record_id is not None

        edit = await subject.engine.accept_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=recorded.record_id
        )

        assert _write(edit) == (_WRITTEN, None)
        view = await _read(subject)
        assert [(one.memory_id, one.pinned) for one in view.kept] == [("m:diet", True)]
        assert view.suggestions == ()

    async def test_a_pin_suggestion_past_the_budget_is_refused_and_stays_pending(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§6:3: accepting pins as the panel pins, checked the same way."""
        subject = person_model_subject
        await _held(subject, fact("m:long", "x" * (PERSON_BUDGET - 5)), fact("m:more", "y" * 10))
        await subject.engine.pin_memory(OWNER_PERSON_ID, memory_id="m:long")
        recorded = await subject.people.record_suggestion(OWNER_PERSON_ID, pin_suggestion("m:more"))
        assert recorded.record_id is not None

        edit = await subject.engine.accept_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=recorded.record_id
        )

        assert edit == PersonModelEdit(refused=PersonModelEditRefusal.OVER_BUDGET)
        view = await _read(subject)
        assert [one.suggestion.id for one in view.suggestions] == [recorded.record_id]

    async def test_dismissing_a_suggestion_decides_it(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§9:2, §12: dismissed, it is no longer shown, and neither act can decide it again."""
        subject = person_model_subject
        recorded = await subject.people.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.NAME, "Rob")
        )
        assert recorded.record_id is not None
        engine = subject.engine

        dismissed = await engine.dismiss_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=recorded.record_id
        )
        dismissed_again = await engine.dismiss_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=recorded.record_id
        )
        accepted = await engine.accept_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=recorded.record_id
        )

        assert _write(dismissed) == (_WRITTEN, None)
        assert _write(dismissed_again) == (_REFUSED, PersonModelRefusal.ALREADY_DECIDED)
        assert _write(accepted) == (_REFUSED, PersonModelRefusal.ALREADY_DECIDED)
        view = await _read(subject)
        assert (view.suggestions, view.profile.name) == ((), None)

    async def test_a_suggestion_the_hub_does_not_hold_is_refused(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        engine = person_model_subject.engine

        accepted = await engine.accept_person_suggestion(
            OWNER_PERSON_ID, suggestion_id="suggestion:none"
        )
        dismissed = await engine.dismiss_person_suggestion(
            OWNER_PERSON_ID, suggestion_id="suggestion:none"
        )

        assert _write(accepted) == (_REFUSED, PersonModelRefusal.UNKNOWN_RECORD)
        assert _write(dismissed) == (_REFUSED, PersonModelRefusal.UNKNOWN_RECORD)

    async def test_setting_a_field_to_a_suggestions_value_accepts_it(
        self, person_model_subject: PersonModelSubject
    ) -> None:
        """§8:8: accepted by any route, in the same write."""
        subject = person_model_subject
        await subject.people.record_suggestion(
            OWNER_PERSON_ID, field_suggestion(ProfileField.ADDRESS, "Robin")
        )

        await subject.engine.set_profile_field(
            OWNER_PERSON_ID, field=ProfileField.ADDRESS, value="Robin"
        )

        assert (await _read(subject)).suggestions == ()

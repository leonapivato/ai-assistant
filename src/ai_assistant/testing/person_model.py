"""A canonical :class:`~ai_assistant.core.protocols.PersonModelStore` fake (ADR-0338 §10).

The shared test double for the person model, so orchestration's person block, and the
lanes after it, can exercise a profile, its change log, pins through successors, style
marks, suggestions and a store that fails, without a file. It keeps everything in
memory and follows the contract's every rule, so a consumer's test sees what the store
would do.

**It holds the owner from the start** (§2:1): built, it holds the one person
:data:`~ai_assistant.core.types.OWNER_PERSON_ID`, created at its clock's first reading,
with an empty profile, as the store is when first created. The hub's seed (§3:7) is a
write a test makes, as the composition root makes it.

**It checks a field's value exactly as the contract says every store does** (ADR-0338
§3:2), in :func:`profile_value_fault`: the bound on a text field is the composition
root's, so the check is each store's own and the shared suite holds them to one answer,
and a consumer's test cannot pass over a write no deployment would take.

**It can be told to fail**: :meth:`FakePersonModelStore.fail_next` makes the next
member called raise :class:`~ai_assistant.core.errors.PersonModelStoreError` before it
reads or writes anything, as a store fault would.

Every member runs to its end without awaiting, so on one event loop each is one
indivisible step, which is the exclusion the contract asks of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING, Final, final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Person,
    PersonActHow,
    PersonModel,
    PersonModelAct,
    PersonModelExport,
    PersonModelRefusal,
    PersonModelWrite,
    PersonModelWriteKind,
    PersonRole,
    PersonSuggestion,
    Pin,
    Profile,
    ProfileChange,
    ProfileField,
    StyleMark,
    SuggestionKind,
    SuggestionState,
    encodable_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import ProposedSuggestion

__all__ = ["DEFAULT_PROFILE_FIELD_CHARS", "FakePersonModelStore", "profile_value_fault"]

#: The fake's bound on a text field's length, where a test names none. The deployment's
#: is a composition-root constant (ADR-0338 §3:2); this is only the fake's default.
DEFAULT_PROFILE_FIELD_CHARS: Final = 200

_WRITTEN: Final = PersonModelWriteKind.WRITTEN
_UNCHANGED: Final = PersonModelWriteKind.UNCHANGED

#: The acts that may make a pin (ADR-0338 §4:1).
_PIN_ACTS: Final = frozenset({PersonActHow.PANEL, PersonActHow.APPROVAL})


def profile_value_fault(field: ProfileField, value: str | None, *, chars: int) -> str | None:
    """Why ``value`` is no valid value of ``field``, or ``None`` where it is (ADR-0338 §3:2).

    The contract's rule, as ``PersonModelStore.set_field`` states it: ``None`` clears the
    field; any other value is text, not blank, within ``chars`` characters, the bound a
    composition-root constant holds; and a time zone is a name ``zoneinfo`` resolves.

    Args:
        field: The field written.
        value: The value written, or ``None`` to clear it.
        chars: The bound on a text field's length.

    Returns:
        A code-owned reason, or ``None``.
    """
    if value is None:
        return None
    if not value.strip():
        return "a field is cleared, never set to blank text"
    if len(value) > chars:
        return f"a field's value is at most {chars} characters"
    try:
        encodable_text(value)
    except ValueError:
        return "a field's value is text with a UTF-8 encoding"
    if field is ProfileField.TIME_ZONE:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError, ValueError:
            return "a time zone is a name zoneinfo resolves"
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _refused(
    refusal: PersonModelRefusal, *, reason: str | None = None, record_id: str | None = None
) -> PersonModelWrite:
    return PersonModelWrite(
        kind=PersonModelWriteKind.REFUSED, refusal=refusal, reason=reason, record_id=record_id
    )


def _checked(value: object, *, name: str) -> str:
    """A non-blank ``str`` argument, or a ``ValueError`` before anything is read."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-blank str"
        raise ValueError(msg)
    return value


@dataclass
class _Held:
    """One person's records, in the order written."""

    person: Person
    profile: Profile = field(default_factory=Profile)
    changes: list[ProfileChange] = field(default_factory=list)
    pins: list[Pin] = field(default_factory=list)
    marks: list[StyleMark] = field(default_factory=list)
    suggestions: list[PersonSuggestion] = field(default_factory=list)


@final
class FakePersonModelStore:
    """An in-memory person-model store holding the owner (ADR-0338 §2:1, §10)."""

    def __init__(
        self,
        *,
        field_chars: int = DEFAULT_PROFILE_FIELD_CHARS,
        now: Callable[[], datetime] = _utcnow,
        new_id: Callable[[str], str] | None = None,
    ) -> None:
        """Build the store as first created: the owner, with an empty profile.

        Args:
            field_chars: The bound on a text field's length (§3:2).
            now: The clock every instant the store records is read from.
            new_id: Mints a record's id from its kind (``pin``, ``mark`` or
                ``suggestion``); sequential per kind where ``None``.

        Raises:
            ValueError: If ``field_chars`` is below 1, or the clock's first reading is not
                an aware instant.
        """
        if field_chars < 1:
            msg = "a field's bound is at least one character"
            raise ValueError(msg)
        self._chars = field_chars
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="FakePersonModelStore")
        numbers = count(1)
        self._new_id = new_id or (lambda kind: f"{kind}:{next(numbers)}")
        owner = Person(id=OWNER_PERSON_ID, role=PersonRole.OWNER, created_at=self._clock())
        self._people: dict[str, _Held] = {owner.id: _Held(person=owner)}
        self._fail = False

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        A reading the clock check refuses is a store fault, raised before any record is
        touched, as the store's own refusal would be (ADR-0026 §4).

        Raises:
            PersonModelStoreError: If the reading is not an aware instant.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = "the fake person-model store's clock gave a reading it cannot record"
            raise PersonModelStoreError(msg) from exc

    def fail_next(self) -> None:
        """Make the next member called raise ``PersonModelStoreError``, touching nothing."""
        self._fail = True

    def _fault(self) -> None:
        if self._fail:
            self._fail = False
            msg = "the fake person-model store was told to fail"
            raise PersonModelStoreError(msg)

    # --- reads ------------------------------------------------------------------------

    async def read(self, person_id: str) -> PersonModel | None:
        """Read one person's model (ADR-0338 §10:2)."""
        _checked(person_id, name="person_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return None
        return PersonModel(
            person=held.person,
            profile=held.profile,
            changes=tuple(held.changes),
            pins=tuple(held.pins),
            style_marks=tuple(held.marks),
            suggestions=tuple(
                one for one in held.suggestions if one.state is SuggestionState.PENDING
            ),
        )

    async def export(self) -> PersonModelExport:
        """Every record held (ADR-0338 §10:5)."""
        self._fault()
        people = list(self._people.values())
        return PersonModelExport(
            persons=tuple(one.person for one in people),
            profiles=tuple((one.person.id, one.profile) for one in people),
            changes=tuple(change for one in people for change in one.changes),
            pins=tuple(pin for one in people for pin in one.pins),
            style_marks=tuple(mark for one in people for mark in one.marks),
            suggestions=tuple(suggestion for one in people for suggestion in one.suggestions),
        )

    async def clear(self) -> int:
        """Erase every record, the owner included (ADR-0338 §10:5)."""
        self._fault()
        erased = sum(
            2 + len(one.changes) + len(one.pins) + len(one.marks) + len(one.suggestions)
            for one in self._people.values()
        )
        self._people.clear()
        return erased

    # --- the profile (§3) -------------------------------------------------------------

    async def set_field(
        self,
        person_id: str,
        field: ProfileField,
        value: str | None,
        *,
        act: PersonModelAct,
    ) -> PersonModelWrite:
        """Set or clear one field, logging the change in the same step (§3:2-§3:5)."""
        _checked(person_id, name="person_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        if act.how is PersonActHow.SUGGESTION:
            return _refused(PersonModelRefusal.INVALID_ACT)
        if (fault := profile_value_fault(field, value, chars=self._chars)) is not None:
            return _refused(PersonModelRefusal.INVALID_VALUE, reason=fault)
        return self._write_field(held, field, value, act, suggestion_id=None)

    def _write_field(
        self,
        held: _Held,
        field: ProfileField,
        value: str | None,
        act: PersonModelAct,
        *,
        suggestion_id: str | None,
    ) -> PersonModelWrite:
        old = held.profile.value(field)
        at = self._now()
        if value is not None:
            self._accept_equal(held, lambda one: one.field is field and one.value == value, at=at)
        if old == value:
            return PersonModelWrite(kind=_UNCHANGED)
        held.profile = held.profile.with_value(field, value)
        held.changes.append(
            ProfileChange(
                person_id=held.person.id,
                field=field,
                old=old,
                new=value,
                at=at,
                act=act,
                suggestion_id=suggestion_id,
            )
        )
        return PersonModelWrite(kind=_WRITTEN)

    def _accept_equal(
        self, held: _Held, matches: Callable[[ProposedSuggestion], bool], *, at: datetime
    ) -> None:
        """Mark every pending suggestion ``matches`` holds accepted (ADR-0338 §8:9)."""
        for index, one in enumerate(held.suggestions):
            if one.state is SuggestionState.PENDING and matches(one.proposed):
                held.suggestions[index] = one.model_copy(
                    update={"state": SuggestionState.ACCEPTED, "decided_at": at}
                )

    # --- pins (§4) --------------------------------------------------------------------

    async def add_pin(
        self, person_id: str, memory_id: str, *, act: PersonModelAct
    ) -> PersonModelWrite:
        """Pin a memory; a standing pin on it changes nothing (§4:1-§4:2)."""
        _checked(person_id, name="person_id")
        _checked(memory_id, name="memory_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        if act.how not in _PIN_ACTS:
            return _refused(PersonModelRefusal.INVALID_ACT)
        return self._pin(held, memory_id, act)

    def _pin(self, held: _Held, memory_id: str, act: PersonModelAct) -> PersonModelWrite:
        at = self._now()
        self._accept_equal(
            held,
            lambda one: one.kind is SuggestionKind.PIN and one.memory_id == memory_id,
            at=at,
        )
        standing = next(
            (pin for pin in held.pins if pin.memory_id == memory_id and pin.removed_at is None),
            None,
        )
        if standing is not None:
            return PersonModelWrite(kind=_UNCHANGED, record_id=standing.id)
        pin = Pin(
            id=self._new_id("pin"),
            person_id=held.person.id,
            memory_id=memory_id,
            pinned_at=at,
            act=act,
        )
        held.pins.append(pin)
        return PersonModelWrite(kind=_WRITTEN, record_id=pin.id)

    async def remove_pin(self, person_id: str, pin_id: str) -> PersonModelWrite:
        """Mark a pin removed, erasing nothing (§4:7)."""
        _checked(person_id, name="person_id")
        _checked(pin_id, name="pin_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        for index, pin in enumerate(held.pins):
            if pin.id == pin_id:
                if pin.removed_at is not None:
                    return PersonModelWrite(kind=_UNCHANGED, record_id=pin.id)
                held.pins[index] = pin.model_copy(update={"removed_at": self._now()})
                return PersonModelWrite(kind=_WRITTEN, record_id=pin.id)
        return _refused(PersonModelRefusal.UNKNOWN_RECORD)

    # --- style marks (§5:3) -----------------------------------------------------------

    async def add_style_mark(self, person_id: str, memory_id: str) -> PersonModelWrite:
        """Mark a memory, unless it is marked or its mark was removed (§5:3, §9:4)."""
        _checked(person_id, name="person_id")
        _checked(memory_id, name="memory_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        existing = next((mark for mark in held.marks if mark.memory_id == memory_id), None)
        if existing is not None:
            return PersonModelWrite(kind=_UNCHANGED, record_id=existing.id)
        mark = StyleMark(
            id=self._new_id("mark"),
            person_id=held.person.id,
            memory_id=memory_id,
            marked_at=self._now(),
        )
        held.marks.append(mark)
        return PersonModelWrite(kind=_WRITTEN, record_id=mark.id)

    async def remove_style_mark(self, person_id: str, mark_id: str) -> PersonModelWrite:
        """Remove a mark, keeping it as removed (§5:3)."""
        _checked(person_id, name="person_id")
        _checked(mark_id, name="mark_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        for index, mark in enumerate(held.marks):
            if mark.id == mark_id:
                if mark.removed_at is not None:
                    return PersonModelWrite(kind=_UNCHANGED, record_id=mark.id)
                held.marks[index] = mark.model_copy(update={"removed_at": self._now()})
                return PersonModelWrite(kind=_WRITTEN, record_id=mark.id)
        return _refused(PersonModelRefusal.UNKNOWN_RECORD)

    # --- suggestions (§9:2, §9:5) -----------------------------------------------------

    async def record_suggestion(
        self, person_id: str, suggestion: ProposedSuggestion
    ) -> PersonModelWrite:
        """Record a pending suggestion, unless held, pending or dismissed (§9:2, §9:5)."""
        _checked(person_id, name="person_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        if suggestion.kind is SuggestionKind.FIELD:
            assert suggestion.field is not None  # noqa: S101 — the type requires it
            fault = profile_value_fault(suggestion.field, suggestion.value, chars=self._chars)
            if fault is not None:
                return _refused(PersonModelRefusal.INVALID_VALUE, reason=fault)
            if held.profile.value(suggestion.field) == suggestion.value:
                return PersonModelWrite(kind=_UNCHANGED)
        elif any(
            pin.memory_id == suggestion.memory_id and pin.removed_at is None for pin in held.pins
        ):
            return PersonModelWrite(kind=_UNCHANGED)
        equal = next(
            (
                one
                for one in held.suggestions
                if one.state is not SuggestionState.ACCEPTED and one.proposed.equals(suggestion)
            ),
            None,
        )
        if equal is not None:
            return PersonModelWrite(kind=_UNCHANGED, record_id=equal.id)
        recorded = PersonSuggestion(
            id=self._new_id("suggestion"),
            person_id=held.person.id,
            proposed=suggestion,
            recorded_at=self._now(),
        )
        held.suggestions.append(recorded)
        return PersonModelWrite(kind=_WRITTEN, record_id=recorded.id)

    def _pending(self, held: _Held, suggestion_id: str) -> PersonSuggestion | PersonModelWrite:
        found = next((one for one in held.suggestions if one.id == suggestion_id), None)
        if found is None:
            return _refused(PersonModelRefusal.UNKNOWN_RECORD)
        if found.state is not SuggestionState.PENDING:
            return _refused(PersonModelRefusal.ALREADY_DECIDED, record_id=found.id)
        return found

    async def accept_suggestion(
        self, person_id: str, suggestion_id: str, *, by: str
    ) -> PersonModelWrite:
        """Take a suggestion's field to its value, or pin its memory, in one step."""
        _checked(person_id, name="person_id")
        _checked(suggestion_id, name="suggestion_id")
        _checked(by, name="by")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        found = self._pending(held, suggestion_id)
        if isinstance(found, PersonModelWrite):
            return found
        proposed = found.proposed
        if proposed.kind is SuggestionKind.FIELD:
            assert proposed.field is not None  # noqa: S101 — the type requires it
            act = PersonModelAct(how=PersonActHow.SUGGESTION, by=by, episode_id=proposed.episode_id)
            self._write_field(held, proposed.field, proposed.value, act, suggestion_id=found.id)
        else:
            assert proposed.memory_id is not None  # noqa: S101 — the type requires it
            self._pin(held, proposed.memory_id, PersonModelAct(how=PersonActHow.PANEL, by=by))
        return PersonModelWrite(kind=_WRITTEN, record_id=found.id)

    async def dismiss_suggestion(self, person_id: str, suggestion_id: str) -> PersonModelWrite:
        """Dismiss a pending suggestion (§9:2)."""
        _checked(person_id, name="person_id")
        _checked(suggestion_id, name="suggestion_id")
        self._fault()
        held = self._people.get(person_id)
        if held is None:
            return _refused(PersonModelRefusal.UNKNOWN_PERSON)
        found = self._pending(held, suggestion_id)
        if isinstance(found, PersonModelWrite):
            return found
        index = held.suggestions.index(found)
        held.suggestions[index] = found.model_copy(
            update={"state": SuggestionState.DISMISSED, "decided_at": self._now()}
        )
        return PersonModelWrite(kind=_WRITTEN, record_id=found.id)

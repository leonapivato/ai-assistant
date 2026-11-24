"""Shared conformance suite for the PermissionLineStore Protocol (ADR-0367 §3:5, §3:6).

Every ``PermissionLineStore`` implementation must pass this suite (CONTRIBUTING, "Protocol
conformance suites"). A concrete test subclasses :class:`PermissionLineStoreContract` and
supplies one fixture, ``factory``, which builds an empty subject on a chosen clock.

The cases follow the contract: a store that starts empty (ADR-0376 §3:3); a making
recorded with its parts, its maker and its instant, under an identifier never reused
(ADR-0367 §3:6); the standing lines listed in the order made; a making that repeats a
standing line of the same kind with exactly the same parts making no second line, and
every other making a line of its own (ADR-0376 §4:5), concurrent ones included; a removal
recorded and kept, its line still read by its identifier (§4:6, §4:8); a removal of
nothing writing nothing; and malformed arguments refused before anything is read. What
only one implementation owes — a persistent store's file, what survives its reopening, its
schema label, a backend fault; the fake's arranged fault — is that implementation's own
test.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a ``Test``-prefixed
subclass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final, Protocol

import pytest

from ai_assistant.core.protocols import PermissionLineStore
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    GrantHow,
    LineMaking,
    LineMakingKind,
    LineParts,
    LineRemoval,
    LineRemovalKind,
    PermissionLineKind,
    Sureness,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.types import PermissionLine

pytestmark = pytest.mark.anyio

#: The first reading of the clock :func:`ticking` hands out, and its step.
START: Final = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
STEP: Final = timedelta(seconds=1)

#: Someone other than the owner, as a maker or a remover: the store records whoever the
#: caller names, and which person may act is the caller's (ADR-0376 §6).
SOMEONE: Final = "person:someone-else"

#: A grant with every part a grant may carry.
FULL_GRANT: Final = LineParts(
    kind=PermissionLineKind.GRANT,
    who=OWNER_PERSON_ID,
    action="send_text",
    thing="telegram:line",
    how=GrantHow.WITH_APPROVAL,
    bar=Sureness.NORMAL,
    condition=OWN_CHAT_CONNECTION,
)
#: The look-up grant ADR-0376 §2's worked example gives anyone, as a made line.
LOOKUP_GRANT: Final = LineParts(
    kind=PermissionLineKind.GRANT,
    who=ANYONE_GROUP_ID,
    action="search_memories",
    how=GrantHow.ALLOWED,
    bar=Sureness.WEAK,
)
#: DO-02's limit on one email account (ADR-0376 §2's worked example).
MAIL_LIMIT: Final = LineParts(
    kind=PermissionLineKind.LIMIT,
    who=OWNER_PERSON_ID,
    action="send_email",
    thing="account:conn-mail",
)

#: Each a line differing from :data:`FULL_GRANT` in exactly one part, so none repeats it.
ONE_PART_OTHER: Final = {
    "kind": MAIL_LIMIT.model_copy(update={"action": "send_text", "thing": "telegram:line"}),
    "who": FULL_GRANT.model_copy(update={"who": ANYONE_GROUP_ID}),
    "action": FULL_GRANT.model_copy(update={"action": "send_email"}),
    "thing": FULL_GRANT.model_copy(update={"thing": "account:conn-mail"}),
    "no thing": FULL_GRANT.model_copy(update={"thing": None}),
    "how": FULL_GRANT.model_copy(update={"how": GrantHow.ALLOWED}),
    "bar": FULL_GRANT.model_copy(update={"bar": Sureness.WEAK}),
    "condition": FULL_GRANT.model_copy(update={"condition": "telegram:line"}),
    "no condition": FULL_GRANT.model_copy(update={"condition": None}),
}


def ticking() -> Callable[[], datetime]:
    """A clock that reads :data:`START`, then one :data:`STEP` later on each reading.

    Returns:
        The clock.
    """
    seconds = count()
    return lambda: START + next(seconds) * STEP


class PermissionLineStoreFactory(Protocol):
    """Builds an empty subject on the clock given."""

    def __call__(self, *, now: Callable[[], datetime]) -> PermissionLineStore: ...


def made(making: LineMaking) -> PermissionLine:
    """The line a making made, asserting that it made one.

    Args:
        making: What a making returned.

    Returns:
        Its new line.
    """
    assert making.kind is LineMakingKind.MADE, making
    return making.line


def removed(removal: LineRemoval) -> PermissionLine:
    """The line a removal removed, asserting that it removed one.

    Args:
        removal: What a removal returned.

    Returns:
        The line as now kept.
    """
    assert removal.kind is LineRemovalKind.REMOVED, removal
    assert removal.line is not None
    return removal.line


class PermissionLineStoreContract:
    """Behaviour every PermissionLineStore implementation must exhibit."""

    @pytest.fixture
    def factory(self) -> PermissionLineStoreFactory:
        """Build an empty subject. Overridden per implementation."""
        raise NotImplementedError

    @pytest.fixture
    def store(self, factory: PermissionLineStoreFactory) -> PermissionLineStore:
        """An empty subject on a ticking clock from :data:`START`."""
        return factory(now=ticking())

    def test_it_satisfies_the_protocol(self, store: PermissionLineStore) -> None:
        assert isinstance(store, PermissionLineStore)

    # --- empty from the start (ADR-0376 §3:3) ----------------------------------------

    async def test_it_starts_empty(self, store: PermissionLineStore) -> None:
        assert await store.standing() == ()
        assert await store.line("line:1") is None

    # --- a making (ADR-0376 §4:3, §4:4, §4:8) ------------------------------------------

    async def test_a_grant_is_recorded_with_its_parts_its_maker_and_its_instant(
        self, store: PermissionLineStore
    ) -> None:
        line = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))

        assert line.parts == FULL_GRANT
        assert line.made_by == OWNER_PERSON_ID
        assert line.made_at == START
        assert line.standing
        assert (line.removed_by, line.removed_at) == (None, None)
        assert await store.standing() == (line,)
        assert await store.line(line.id) == line

    async def test_a_limit_is_recorded_with_no_how_no_bar_and_no_condition(
        self, store: PermissionLineStore
    ) -> None:
        line = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        assert line.kind is PermissionLineKind.LIMIT
        assert (line.how, line.bar, line.condition) == (None, None, None)
        assert line.thing == "account:conn-mail"
        assert await store.line(line.id) == line

    async def test_the_maker_is_whoever_the_caller_names(self, store: PermissionLineStore) -> None:
        line = made(await store.record_making(LOOKUP_GRANT, by=SOMEONE))

        assert line.made_by == SOMEONE

    async def test_the_standing_lines_are_listed_in_the_order_made(
        self, store: PermissionLineStore
    ) -> None:
        first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        second = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))
        third = made(await store.record_making(LOOKUP_GRANT, by=OWNER_PERSON_ID))

        assert await store.standing() == (first, second, third)
        assert [first.made_at, second.made_at, third.made_at] == sorted(
            {first.made_at, second.made_at, third.made_at}
        )

    async def test_every_line_has_an_identifier_of_its_own(
        self, store: PermissionLineStore
    ) -> None:
        lines = [
            made(await store.record_making(one, by=OWNER_PERSON_ID))
            for one in (FULL_GRANT, LOOKUP_GRANT, MAIL_LIMIT, *ONE_PART_OTHER.values())
        ]

        assert len({one.id for one in lines}) == len(lines)

    # --- a making that repeats a standing line (ADR-0376 §4:5) --------------------------

    async def test_a_making_that_repeats_a_standing_line_makes_no_second(
        self, store: PermissionLineStore
    ) -> None:
        first = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))

        again = await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID)

        assert again == LineMaking(kind=LineMakingKind.UNCHANGED, line=first)
        assert await store.standing() == (first,)

    async def test_a_repeat_by_another_maker_is_still_a_repeat(
        self, store: PermissionLineStore
    ) -> None:
        """Who made a line is not one of its parts, so it does not tell two lines apart."""
        first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        again = await store.record_making(MAIL_LIMIT, by=SOMEONE)

        assert again == LineMaking(kind=LineMakingKind.UNCHANGED, line=first)
        assert await store.standing() == (first,)

    @pytest.mark.parametrize("differs_in", list(ONE_PART_OTHER))
    async def test_a_making_differing_in_any_part_is_a_line_of_its_own(
        self, store: PermissionLineStore, differs_in: str
    ) -> None:
        first = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))
        other = ONE_PART_OTHER[differs_in]

        second = made(await store.record_making(other, by=OWNER_PERSON_ID))

        assert second.id != first.id
        assert second.parts == other
        assert await store.standing() == (first, second)

    async def test_concurrent_identical_makings_make_one_line(
        self, store: PermissionLineStore
    ) -> None:
        makings = await asyncio.gather(
            *(store.record_making(LOOKUP_GRANT, by=OWNER_PERSON_ID) for _ in range(8))
        )

        standing = await store.standing()
        assert len(standing) == 1
        assert [one.kind for one in makings].count(LineMakingKind.MADE) == 1
        assert {one.line for one in makings} == {standing[0]}

    # --- a removal (ADR-0376 §4:6, §4:8) -----------------------------------------------

    async def test_a_removal_is_recorded_and_the_line_is_kept(
        self, store: PermissionLineStore
    ) -> None:
        line = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))

        gone = removed(await store.record_removal(line.id, by=OWNER_PERSON_ID))

        assert gone.id == line.id
        assert gone.parts == line.parts
        assert (gone.made_by, gone.made_at) == (line.made_by, line.made_at)
        assert gone.removed_by == OWNER_PERSON_ID
        assert gone.removed_at is not None
        assert gone.removed_at > line.made_at
        assert not gone.standing
        assert await store.standing() == ()
        assert await store.line(line.id) == gone

    async def test_the_remover_is_whoever_the_caller_names(
        self, store: PermissionLineStore
    ) -> None:
        line = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        gone = removed(await store.record_removal(line.id, by=SOMEONE))

        assert gone.removed_by == SOMEONE
        assert gone.made_by == OWNER_PERSON_ID

    async def test_a_removal_leaves_every_other_line_standing(
        self, store: PermissionLineStore
    ) -> None:
        first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        second = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))
        third = made(await store.record_making(LOOKUP_GRANT, by=OWNER_PERSON_ID))

        removed(await store.record_removal(second.id, by=OWNER_PERSON_ID))

        assert await store.standing() == (first, third)

    async def test_a_line_already_removed_is_not_standing_and_nothing_changes(
        self, store: PermissionLineStore
    ) -> None:
        line = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))
        gone = removed(await store.record_removal(line.id, by=OWNER_PERSON_ID))

        again = await store.record_removal(line.id, by=SOMEONE)

        assert again == LineRemoval(kind=LineRemovalKind.NOT_STANDING)
        assert await store.line(line.id) == gone

    async def test_a_line_never_made_is_not_standing_and_nothing_changes(
        self, store: PermissionLineStore
    ) -> None:
        line = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))

        refused = await store.record_removal("line:never-made", by=OWNER_PERSON_ID)

        assert refused == LineRemoval(kind=LineRemovalKind.NOT_STANDING)
        assert await store.standing() == (line,)
        assert await store.line("line:never-made") is None

    async def test_an_identifier_is_matched_exactly(self, store: PermissionLineStore) -> None:
        line = made(await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))

        assert await store.line(f" {line.id}") is None
        assert await store.line(f"{line.id}x") is None
        refused = await store.record_removal(f"{line.id} ", by=OWNER_PERSON_ID)

        assert refused.kind is LineRemovalKind.NOT_STANDING
        assert await store.standing() == (line,)

    # --- an identifier never reused (ADR-0367 §3:6) -------------------------------------

    async def test_a_line_made_again_after_its_removal_is_a_new_line(
        self, store: PermissionLineStore
    ) -> None:
        first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        gone = removed(await store.record_removal(first.id, by=OWNER_PERSON_ID))

        second = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        assert second.id != first.id
        assert second.parts == first.parts
        assert await store.standing() == (second,)
        assert await store.line(first.id) == gone
        assert await store.line(second.id) == second

    async def test_the_clock_dates_each_making_and_removal(
        self, factory: PermissionLineStoreFactory
    ) -> None:
        readings = iter(START + number * timedelta(hours=1) for number in range(10))
        store = factory(now=lambda: next(readings))

        line = made(await store.record_making(LOOKUP_GRANT, by=OWNER_PERSON_ID))
        gone = removed(await store.record_removal(line.id, by=OWNER_PERSON_ID))

        assert line.made_at == START
        assert gone.removed_at == START + timedelta(hours=1)

    # --- malformed arguments, refused before anything is read ----------------------------

    @pytest.mark.parametrize("parts", [None, "grant", FULL_GRANT.model_dump()])
    async def test_parts_that_are_not_line_parts_are_a_value_error(
        self, store: PermissionLineStore, parts: object
    ) -> None:
        with pytest.raises(ValueError, match="LineParts"):
            await store.record_making(parts, by=OWNER_PERSON_ID)  # type: ignore[arg-type]  # the malformed argument under test

        assert await store.standing() == ()

    @pytest.mark.parametrize(
        "update",
        [
            {"bar": Sureness.NORMAL},
            {"how": GrantHow.ALLOWED},
            {"condition": "telegram:line"},
            {"who": "person:sam"},
            {"thing": "conversation:chat-1"},
        ],
    )
    async def test_parts_that_skipped_validation_are_a_value_error(
        self, store: PermissionLineStore, update: dict[str, object]
    ) -> None:
        """``model_copy`` skips validation, so the parts are validated again, whole."""
        broken = MAIL_LIMIT.model_copy(update=update)

        with pytest.raises(ValueError, match="LineParts"):
            await store.record_making(broken, by=OWNER_PERSON_ID)

        assert await store.standing() == ()

    @pytest.mark.parametrize("by", ["", "   ", None, 7])
    async def test_a_malformed_maker_or_remover_is_a_value_error(
        self, store: PermissionLineStore, by: object
    ) -> None:
        line = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        with pytest.raises(ValueError, match="by"):
            await store.record_making(FULL_GRANT, by=by)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="by"):
            await store.record_removal(line.id, by=by)  # type: ignore[arg-type]  # the malformed argument under test

        assert await store.standing() == (line,)

    @pytest.mark.parametrize("line_id", ["", "   ", None, 7])
    async def test_a_malformed_identifier_is_a_value_error(
        self, store: PermissionLineStore, line_id: object
    ) -> None:
        with pytest.raises(ValueError, match="line_id"):
            await store.line(line_id)  # type: ignore[arg-type]  # the malformed argument under test
        with pytest.raises(ValueError, match="line_id"):
            await store.record_removal(line_id, by=OWNER_PERSON_ID)  # type: ignore[arg-type]  # the malformed argument under test

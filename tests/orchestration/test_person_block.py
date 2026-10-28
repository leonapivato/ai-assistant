"""The person block: whose activation it is, and what the models are shown (ADR-0338 §2, §6, §7).

Built against the canonical fakes, ``FakePersonModelStore`` and ``FakeMemoryStore``: the
person resolved from the recorded trigger alone (§2:2-§2:4); the kept-in-mind slot's
order, its budget and its count of what it left out (§6:1-§6:2); what it leaves out for
resting on outside content (§6:4) and for the record rule (§6:5); a pin or mark followed
through its memory's successors to its chain's current end, live read first and the
history read only where the live read misses (§4:8; ADR-0342 §5:2-§5:5), and shown
nowhere where its memory is gone (§4:10); the suggestions planning is shown (§7:3,
§7:9); the drop before each planning round, of what the history read no longer returns
(§7:10; ADR-0342 §5:4); and a store that cannot be read, which gives no block.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ChannelContext,
    ChannelIdentity,
    InputPart,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemoryWriterName,
    NewConversation,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    ProposedSuggestion,
    RecordedChannelTrigger,
    RecordedTextInput,
    SuggestionKind,
    SupportOrigin,
    Validity,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.person_block import (
    KEPT_IN_MIND_CHARS,
    PLANNING_SUGGESTIONS,
    PersonBlocks,
    activation_person,
    still_held,
)
from ai_assistant.testing import FakeMemoryStore, FakePersonModelStore
from ai_assistant.testing.memories import (
    AT,
    memory,
    remembered_support,
    said_support,
)
from ai_assistant.testing.parties import OWNERS_WORDS, UNIDENTIFIED_WORDS

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.types import (
        ChannelTarget,
        Memory,
        MemoryRecord,
        PersonModel,
        SupportHolder,
    )

pytestmark = pytest.mark.anyio

NOW: Final = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _trigger(
    target: ChannelTarget, *, parties: tuple[SupportHolder, ...] = OWNERS_WORDS
) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=target,
        channel=target if isinstance(target, ChannelIdentity) else None,
        payload=RecordedTextInput(text="hello"),
        context=ChannelContext(),
        reply=None,
        parties=parties,
    )


# --- whose activation it is (§2:2-§2:4) ---------------------------------------------


@pytest.mark.parametrize(
    ("trigger", "person"),
    [
        (_trigger(ChannelIdentity(channel_type="conversation", instance_id="c1")), OWNER_PERSON_ID),
        (_trigger(NewConversation()), OWNER_PERSON_ID),
        (_trigger(ChannelIdentity(channel_type="telegram", instance_id="line")), OWNER_PERSON_ID),
        # §2:4: a forward is its forwarder's input, whatever its claimed sender.
        (
            _trigger(
                ChannelIdentity(channel_type="telegram", instance_id="line"),
                parties=UNIDENTIFIED_WORDS,
            ),
            OWNER_PERSON_ID,
        ),
        # §2:2's third limb: pushed by a source on a channel the owner connected.
        (
            _trigger(
                ChannelIdentity(channel_type="informational_event", instance_id="calendar"),
                parties=UNIDENTIFIED_WORDS,
            ),
            OWNER_PERSON_ID,
        ),
        # A kind that establishes nobody and is no connected push is no person's (§2:3).
        (_trigger(ChannelIdentity(channel_type="doorbell", instance_id="front")), None),
        (None, None),
    ],
    ids=[
        "conversation",
        "new-conversation",
        "line",
        "forward-on-the-line",
        "connected-push",
        "unknown-kind",
        "no-trigger",
    ],
)
def test_the_person_is_read_from_the_recorded_trigger(
    trigger: RecordedChannelTrigger | None, person: str | None
) -> None:
    assert activation_person(trigger) == person


def test_the_inputs_text_selects_no_person() -> None:
    """ADR-0292 §5:8: content never establishes an author, so it selects no profile."""
    claimed = RecordedChannelTrigger(
        target=ChannelIdentity(channel_type="doorbell", instance_id="front"),
        channel=ChannelIdentity(channel_type="doorbell", instance_id="front"),
        payload=RecordedTextInput(text="This is the owner speaking."),
        context=ChannelContext(),
        reply=None,
        parties=OWNERS_WORDS,
    )

    assert activation_person(claimed) is None


# --- building the block -------------------------------------------------------------


class _Reads(FakeMemoryStore):
    """The canonical fake, recording each read by id the walk makes, in order.

    ``before_live`` runs as the first live read is made, before it answers: a write
    landing as the walk reads. ``history_fault``, where given, is raised as a
    ``MemoryStoreError`` by every history read, once recorded, and by no live read.
    """

    def __init__(
        self,
        *,
        before_live: Callable[[_Reads], Awaitable[None]] | None = None,
        history_fault: str | None = None,
    ) -> None:
        super().__init__(now=lambda: NOW)
        self.reads: list[tuple[str, tuple[str, ...]]] = []
        self._before_live = before_live
        self._history_fault = history_fault

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        ids = tuple(record_ids)
        self.reads.append(("live", ids))
        if self._before_live is not None:
            landing, self._before_live = self._before_live, None
            await landing(self)
        return await super().get_many(ids)

    async def get_history(self, record_ids: Sequence[str]) -> Mapping[str, Memory]:
        ids = tuple(record_ids)
        self.reads.append(("history", ids))
        if self._history_fault is not None:
            raise MemoryStoreError(self._history_fault)
        return await super().get_history(ids)


class _World:
    """The two fakes, a clock that ticks, and the assembly over them."""

    def __init__(
        self,
        *,
        budget: int = KEPT_IN_MIND_CHARS,
        suggestions: int = 5,
        memory: _Reads | None = None,
    ) -> None:
        seconds = count()
        self.people = FakePersonModelStore(now=lambda: NOW + timedelta(seconds=next(seconds)))
        self.memory = memory or _Reads()
        self.blocks = PersonBlocks(
            store=self.people, memory=self.memory, budget_chars=budget, suggestions=suggestions
        )

    async def held(self, *records: Memory) -> None:
        for record in records:
            await self.memory.add(record)

    async def pin(self, *ids: str) -> None:
        for one in ids:
            await self.people.add_pin(OWNER_PERSON_ID, one, act=PANEL)

    async def mark(self, *ids: str) -> None:
        for one in ids:
            await self.people.add_style_mark(OWNER_PERSON_ID, one)


def _fact(record_id: str, content: str, **envelope: object) -> Memory:
    return memory(record_id, content, said_support(when=AT, added_at=AT), **envelope)


def _ended(
    record_id: str,
    content: str,
    *,
    successor: str | None,
    then_wrong: tuple[str | None] | None = None,
    live: bool = False,
    **envelope: object,
) -> Memory:
    """A memory ended at ``AT``, naming ``successor``, its window closed there, as the writer
    leaves it (ADR-0328 §3:4, §5:9).

    ``then_wrong`` marks it wrong an hour later too, naming the one successor it holds
    or none (ADR-0328 §5:7). ``live`` keeps its window open instead: a retired memory a
    live read still returns, a state the writer never builds.
    """
    support = said_support(when=AT, added_at=AT)
    create = MemoryOperation(
        kind=MemoryOperationKind.CREATE, cites=support.points_at, at=AT, by=support.added_by
    )
    end = MemoryOperation(
        kind=MemoryOperationKind.END,
        cites=support.points_at,
        at=AT,
        by=MemoryWriterName.OBSERVER,
        successor=successor,
    )
    operations: tuple[MemoryOperation, ...] = (create, end)
    status = MemoryStatus.ENDED
    if then_wrong is not None:
        wrong = MemoryOperation(
            kind=MemoryOperationKind.MARK_WRONG,
            cites=support.points_at,
            at=AT + timedelta(hours=1),
            by=MemoryWriterName.OBSERVER,
            successor=then_wrong[0],
        )
        operations = (create, end, wrong)
        status = MemoryStatus.WRONG
    until = NOW + timedelta(days=30) if live else AT
    return memory(
        record_id,
        content,
        support,
        operations=operations,
        status=status,
        validity=Validity(valid_until=until),
        **envelope,
    )


async def test_no_person_is_given_no_block() -> None:
    world = _World()

    assert await world.blocks.assemble(None, supply=BOUNDED) is None


async def test_a_person_the_store_does_not_hold_is_given_no_block() -> None:
    world = _World()

    assert await world.blocks.assemble("person:someone", supply=BOUNDED) is None


async def test_the_block_carries_the_profile_as_set() -> None:
    world = _World()
    await world.people.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert block.person_id == OWNER_PERSON_ID
    assert block.profile.address == "Robin"
    assert block.profile.name is None
    assert (block.kept, block.left_out, block.suggestions) == ((), 0, ())


async def test_the_slot_shows_pins_oldest_first_then_style_newest_marked_first_each_once() -> None:
    world = _World()
    await world.held(
        _fact("m:diet", "Eats no meat."),
        _fact("m:sister", "Has a sister called Ada."),
        _fact("m:brief", "Likes short answers."),
        _fact("m:jokes", "Enjoys a dry joke."),
    )
    await world.pin("m:sister", "m:diet")
    await world.mark("m:brief", "m:diet", "m:jokes")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [(one.memory.id, one.pinned) for one in block.kept] == [
        ("m:sister", True),
        ("m:diet", True),
        ("m:jokes", False),
        ("m:brief", False),
    ]
    assert [one.id for one in block.pinned] == ["m:sister", "m:diet"]


async def test_a_removed_pin_or_mark_is_not_shown() -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."), _fact("m:brief", "Likes short answers."))
    pinned = await world.people.add_pin(OWNER_PERSON_ID, "m:diet", act=PANEL)
    marked = await world.people.add_style_mark(OWNER_PERSON_ID, "m:brief")
    assert pinned.record_id is not None
    assert marked.record_id is not None
    await world.people.remove_pin(OWNER_PERSON_ID, pinned.record_id)
    await world.people.remove_style_mark(OWNER_PERSON_ID, marked.record_id)

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert block.kept == ()


async def test_the_budget_stops_before_the_first_memory_that_would_exceed_it() -> None:
    world = _World(budget=30)
    await world.held(
        _fact("m:a", "a" * 12),
        _fact("m:b", "b" * 12),
        _fact("m:c", "c" * 12),
        # Short enough to fit what is left, and still left out: the slot stops.
        _fact("m:d", "d"),
    )
    await world.pin("m:a", "m:b", "m:c", "m:d")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:a", "m:b"]
    assert block.left_out == 2


async def test_a_wording_exactly_at_the_budget_is_shown() -> None:
    world = _World(budget=12)
    await world.held(_fact("m:a", "a" * 12))
    await world.pin("m:a")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:a"]
    assert block.left_out == 0


async def test_a_memory_resting_on_outside_content_never_enters_the_slot() -> None:
    world = _World()
    outside = memory("m:out", "The shop says it closes at six.", remembered_support(outside=True))
    await world.held(outside, _fact("m:diet", "Eats no meat."))
    await world.pin("m:out", "m:diet")
    await world.mark("m:out")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert outside.rests_on_outside_content
    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:diet"]
    assert block.left_out == 0


async def test_the_record_rule_is_applied_to_the_slot() -> None:
    """§6:5: a memory the audience may not be shown is not in the slot, as recall's is not."""
    world = _World()
    await world.held(
        _fact("m:about-ada", "Ada is allergic to nuts.", subjects=("Ada",)),
        _fact("m:diet", "Eats no meat."),
    )
    await world.pin("m:about-ada", "m:diet")

    unbounded = await world.blocks.assemble(OWNER_PERSON_ID, supply=UNBOUNDED)
    bounded = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert unbounded is not None
    assert bounded is not None
    assert [one.memory.id for one in unbounded.kept] == ["m:diet"]
    assert [one.memory.id for one in bounded.kept] == ["m:about-ada", "m:diet"]


async def test_a_pin_on_a_current_memory_is_read_live_alone() -> None:
    """ADR-0342 §5:3: the live read returns it, so the walk ends there, with no history read."""
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:diet"]
    assert world.memory.reads == [("live", ("m:diet",))]


async def test_a_pin_follows_two_retirements_to_its_chains_current_end() -> None:
    """#3308: retired memories, their windows closed, reached through the history read.

    Each hop asks the live read first and the history read only for what it missed
    (ADR-0342 §5:3), and the block shows the current end alone (§5:5).
    """
    world = _World()
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:mid"),
        _ended("m:mid", "Lives in Lisbon.", successor="m:new"),
        _fact("m:new", "Lives in Coimbra."),
    )
    await world.pin("m:old")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:new"]
    assert block.memory_ids == {"m:new"}
    assert block.kept[0].memory.status is MemoryStatus.CURRENT
    assert world.memory.reads == [
        ("live", ("m:old",)),
        ("history", ("m:old",)),
        ("live", ("m:mid",)),
        ("history", ("m:mid",)),
        ("live", ("m:new",)),
    ]
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert [pin.memory_id for pin in model.pins] == ["m:old"]


async def test_a_chain_is_followed_to_its_current_end_however_long() -> None:
    """ADR-0342 §5:3 ends a walk only where its history read omits, names no successor or
    loops, so no count of retirements stops it short."""
    world = _World()
    hops = 40
    await world.held(
        *(
            _ended(f"m:{at}", f"Lives at number {at}.", successor=f"m:{at + 1}")
            for at in range(hops)
        ),
        _fact(f"m:{hops}", "Lives at the end of the road."),
    )
    await world.pin("m:0")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == [f"m:{hops}"]


async def test_a_retirement_landing_as_the_live_read_is_made_is_followed() -> None:
    """ADR-0342 §5:3's order: the live read misses, and the history read made after it
    names a successor that is current.

    The pinned memory is current until the walk's first live read, which the retirement
    beats. A history read made before the live read would have found it current naming
    no successor, and the live read missing it would then have shown nothing.
    """

    async def retire(store: _Reads) -> None:
        await store.add(_fact("m:new", "Lives in Coimbra."))
        await store.add(_ended("m:old", "Lives in Porto.", successor="m:new"))

    world = _World(memory=_Reads(before_live=retire))
    await world.held(_fact("m:old", "Lives in Porto."))
    await world.pin("m:old")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:new"]
    assert world.memory.reads[:2] == [("live", ("m:old",)), ("history", ("m:old",))]


@pytest.mark.parametrize(
    ("then_wrong", "shown"),
    [(("m:wrong-fix",), "m:wrong-fix"), ((None,), "m:end-fix")],
    ids=["the-later-names-one", "the-later-names-none"],
)
async def test_the_latest_operation_naming_a_successor_governs(
    then_wrong: tuple[str | None], shown: str
) -> None:
    """ADR-0342 §5:2: ended naming one successor, then marked wrong naming another or none."""
    world = _World()
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:end-fix", then_wrong=then_wrong),
        _fact("m:end-fix", "Lives in Lisbon."),
        _fact("m:wrong-fix", "Lives in Coimbra."),
    )
    await world.pin("m:old")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == [shown]


async def test_a_retired_memory_a_live_read_returns_is_never_shown_as_current() -> None:
    """ADR-0342 §5:1, against a state the writer never builds: retired, its window open."""
    world = _World()
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:new", live=True),
        _ended("m:stuck", "Lives in Faro.", successor=None, live=True),
        _fact("m:new", "Lives in Coimbra."),
    )
    await world.pin("m:old", "m:stuck")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:new"]


async def test_two_pins_reaching_one_memory_show_it_once() -> None:
    world = _World()
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:new"), _fact("m:new", "Lives in Coimbra.")
    )
    await world.pin("m:old", "m:new")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:new"]


@pytest.mark.parametrize(
    "records",
    [
        (_ended("m:old", "Lives in Porto.", successor=None),),
        (_ended("m:old", "Lives in Porto.", successor="m:gone"),),
        (
            _ended("m:old", "Lives in Porto.", successor="m:loop"),
            _ended("m:loop", "Lives in Lisbon.", successor="m:old"),
        ),
        # Retired and past its expiry: the history read omits it (ADR-0342 §3).
        (_ended("m:old", "Lives in Porto.", successor="m:new", expires_at=AT),),
        # The successor itself retired, naming none: the chain ends retired.
        (
            _ended("m:old", "Lives in Porto.", successor="m:mid"),
            _ended("m:mid", "Lives in Lisbon.", successor=None),
        ),
        (),
    ],
    ids=["no-successor", "successor-not-held", "loop", "expired", "ends-retired", "not-held"],
)
async def test_a_pin_whose_chain_reaches_no_current_memory_is_shown_in_no_block(
    records: tuple[Memory, ...],
) -> None:
    world = _World()
    await world.held(*records)
    await world.held(_fact("m:new", "Lives in Coimbra."))
    await world.pin("m:old")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert block.kept == ()


async def test_a_style_mark_follows_successors_as_a_pin_does() -> None:
    world = _World()
    await world.held(
        _ended("m:old", "Likes long answers.", successor="m:new"),
        _fact("m:new", "Likes short answers."),
    )
    await world.mark("m:old")

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [(one.memory.id, one.pinned) for one in block.kept] == [("m:new", False)]


# --- the suggestions (§7:3, §7:9) ---------------------------------------------------


def _field(field: ProfileField, value: str, origin: SupportOrigin) -> ProposedSuggestion:
    return ProposedSuggestion(
        kind=SuggestionKind.FIELD,
        field=field,
        value=value,
        episode_id="activation:a1",
        part=InputPart(episode="activation:a1"),
        origin=origin,
    )


def _pin(memory_id: str) -> ProposedSuggestion:
    return ProposedSuggestion(
        kind=SuggestionKind.PIN, memory_id=memory_id, episode_id="activation:a1"
    )


async def test_suggestions_resting_on_outside_content_never_reach_planning() -> None:
    world = _World()
    outside = memory(
        "m:out", "The newsletter says Robin likes jazz.", remembered_support(outside=True)
    )
    await world.held(outside, _fact("m:diet", "Eats no meat."))
    await world.people.record_suggestion(
        OWNER_PERSON_ID, _field(ProfileField.ADDRESS, "Robin", SupportOrigin.USER_MESSAGE)
    )
    await world.people.record_suggestion(
        OWNER_PERSON_ID, _field(ProfileField.NAME, "Rob", SupportOrigin.OUTSIDE_INPUT)
    )
    await world.people.record_suggestion(OWNER_PERSON_ID, _pin("m:out"))
    await world.people.record_suggestion(OWNER_PERSON_ID, _pin("m:diet"))

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [(one.kind, one.field, one.value) for one in block.suggestions] == [
        (SuggestionKind.PIN, None, None),
        (SuggestionKind.FIELD, ProfileField.ADDRESS, "Robin"),
    ]
    assert block.suggestions[0].memory is not None
    assert block.suggestions[0].memory.id == "m:diet"


async def test_a_pin_suggestions_memory_must_be_current_and_pass_the_record_rule() -> None:
    world = _World()
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:new"),
        _fact("m:new", "Lives in Coimbra."),
        _fact("m:about-ada", "Ada is allergic to nuts.", subjects=("Ada",)),
    )
    for one in ("m:old", "m:about-ada", "m:gone"):
        await world.people.record_suggestion(OWNER_PERSON_ID, _pin(one))

    unbounded = await world.blocks.assemble(OWNER_PERSON_ID, supply=UNBOUNDED)
    bounded = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert unbounded is not None
    assert bounded is not None
    assert unbounded.suggestions == ()
    assert [one.memory.id for one in bounded.suggestions if one.memory is not None] == [
        "m:about-ada"
    ]


async def test_suggestions_are_newest_first_up_to_the_count() -> None:
    world = _World(suggestions=2)
    for value in ("Robin", "Rob", "Bobbin"):
        await world.people.record_suggestion(
            OWNER_PERSON_ID, _field(ProfileField.ADDRESS, value, SupportOrigin.USER_MESSAGE)
        )

    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is not None
    assert [one.value for one in block.suggestions] == ["Bobbin", "Rob"]


async def test_equal_instants_keep_the_order_the_store_made_them_in() -> None:
    """§6:2, §7:3: newest first even where the clock read the same for each."""
    people = FakePersonModelStore(now=lambda: NOW)
    memory_store = FakeMemoryStore(now=lambda: NOW)
    blocks = PersonBlocks(store=people, memory=memory_store, budget_chars=20, suggestions=1)
    for record in (
        _fact("m:a", "a" * 10),
        _fact("m:b", "b" * 10),
        _fact("m:older", "o" * 15),
        _fact("m:newer", "n" * 15),
    ):
        await memory_store.add(record)
    for one in ("m:a", "m:b"):
        await people.add_pin(OWNER_PERSON_ID, one, act=PANEL)
    pins_only = await blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)
    for one in ("m:a", "m:b"):
        pin = next(pin for pin in (await _model(people)).standing_pins if pin.memory_id == one)
        await people.remove_pin(OWNER_PERSON_ID, pin.id)
    for one in ("m:older", "m:newer"):
        await people.add_style_mark(OWNER_PERSON_ID, one)
    for value in ("first", "second"):
        await people.record_suggestion(
            OWNER_PERSON_ID, _field(ProfileField.ADDRESS, value, SupportOrigin.USER_MESSAGE)
        )

    block = await blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert pins_only is not None
    assert [one.memory.id for one in pins_only.kept] == ["m:a", "m:b"]
    assert block is not None
    assert [one.memory.id for one in block.kept] == ["m:newer"]
    assert block.left_out == 1
    assert [one.value for one in block.suggestions] == ["second"]


async def _model(people: FakePersonModelStore) -> PersonModel:
    model = await people.read(OWNER_PERSON_ID)
    assert model is not None
    return model


def test_the_composition_root_constants() -> None:
    assert KEPT_IN_MIND_CHARS == 1600  # §6:1: about 400 tokens
    assert PLANNING_SUGGESTIONS >= 1


@pytest.mark.parametrize(("budget", "suggestions"), [(0, 5), (10, -1)])
def test_bounds_that_cannot_bind_are_refused(budget: int, suggestions: int) -> None:
    with pytest.raises(ValueError, match="ADR-0338"):
        PersonBlocks(
            store=FakePersonModelStore(),
            memory=FakeMemoryStore(),
            budget_chars=budget,
            suggestions=suggestions,
        )


# --- before each planning round (§7:10) ---------------------------------------------


async def test_a_memory_forgotten_while_the_activation_runs_is_dropped_before_a_round() -> None:
    world = _World()
    await world.held(
        _fact("m:diet", "Eats no meat."),
        _fact("m:brief", "Likes short answers."),
        _fact("m:sister", "Has a sister called Ada."),
    )
    await world.pin("m:diet")
    await world.mark("m:brief")
    await world.people.record_suggestion(OWNER_PERSON_ID, _pin("m:sister"))
    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)
    assert block is not None
    assert block.memory_ids == {"m:diet", "m:brief", "m:sister"}

    await world.memory.delete("m:diet")
    await world.memory.delete("m:sister")
    kept = await still_held(block, world.memory)

    assert [one.memory.id for one in kept.kept] == ["m:brief"]
    assert kept.suggestions == ()
    assert kept.profile == block.profile


async def test_a_memory_retired_while_the_activation_runs_is_still_held() -> None:
    """ADR-0342 §5:4: the store holds a memory exactly where the history read returns it.

    The block is assembled once (§7:1), so the check before a round walks no chain:
    the retired memory stays, and its successor is not brought in.
    """
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")
    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)
    assert block is not None

    await world.held(
        _ended("m:diet", "Eats no meat.", successor="m:fish"),
        _fact("m:fish", "Eats fish, not meat."),
    )
    world.memory.reads.clear()
    kept = await still_held(block, world.memory)

    assert kept is block
    assert world.memory.reads == [("history", ("m:diet",))]


async def test_a_block_whose_memories_are_all_held_is_kept_as_it_is() -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")
    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)
    assert block is not None

    assert await still_held(block, world.memory) is block


async def test_a_memory_store_that_cannot_be_read_before_a_round_leaves_no_memory() -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")
    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)
    assert block is not None

    with capture_logs() as logs:
        kept = await still_held(block, FakeMemoryStore(failure="down"))

    assert kept.kept == ()
    assert kept.profile == block.profile
    assert [one["reason"] for one in logs if one["event"] == "person_block_unread"] == [
        "memory_fault"
    ]


# --- a store that cannot be read ----------------------------------------------------


async def test_a_person_model_store_fault_gives_no_block_and_says_so_without_values() -> None:
    world = _World()
    await world.people.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=PANEL)
    world.people.fail_next()

    with capture_logs() as logs:
        block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is None
    [logged] = [one for one in logs if one["event"] == "person_block_unread"]
    assert logged["reason"] == "store_fault"
    assert "Robin Vale" not in repr(logs)


async def test_a_memory_store_fault_gives_no_block() -> None:
    people = FakePersonModelStore()
    await people.add_pin(OWNER_PERSON_ID, "m:diet", act=PANEL)
    blocks = PersonBlocks(store=people, memory=FakeMemoryStore(failure="down"))

    with capture_logs() as logs:
        block = await blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is None
    assert [one["reason"] for one in logs if one["event"] == "person_block_unread"] == [
        "memory_fault"
    ]


async def test_a_history_read_fault_on_a_mixed_batch_gives_no_block() -> None:
    """#3330: one pin resolves on the live read, the other misses it, and the history read
    made for the miss fails (ADR-0342 §5:3): no block, and one fault logged without words.

    The reads pin where the fault fired: the one live read answered both pins, so the
    walk reached the history read, for the missed pin alone, and it raised there.
    """
    wordings = ("Eats no meat.", "Lives in Porto.", "Lives in Coimbra.")
    world = _World(memory=_Reads(history_fault="history down"))
    await world.held(
        _fact("m:diet", wordings[0]),
        _ended("m:old", wordings[1], successor="m:new"),
        _fact("m:new", wordings[2]),
    )
    await world.pin("m:diet", "m:old")

    with capture_logs() as logs:
        block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert block is None
    assert world.memory.reads == [("live", ("m:diet", "m:old")), ("history", ("m:old",))]
    [logged] = [one for one in logs if one["event"] == "person_block_unread"]
    assert logged["reason"] == "memory_fault"
    assert not [one for one in logs if one["event"] == "person_block"]
    assert not [wording for wording in wordings if wording in repr(logs)]


async def test_an_assembled_block_is_logged_by_its_counts_alone() -> None:
    world = _World()
    await world.held(_fact("m:diet", "Eats no meat."))
    await world.pin("m:diet")

    with capture_logs() as logs:
        await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    [logged] = [one for one in logs if one["event"] == "person_block"]
    assert (logged["pinned"], logged["kept"], logged["left_out"], logged["suggestions"]) == (
        1,
        1,
        0,
        0,
    )
    assert "Eats no meat." not in repr(logs)

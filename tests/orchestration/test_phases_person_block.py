"""The person block through the engine and the phases (ADR-0338 §7:1, §7:3, §11:2).

An engine with the phases wired, over the canonical fakes: where no person-model store is
wired, as on every hub until lane 2, nothing of the person model reaches understanding or
planning, and neither template is handed a person flag set. Wired, an activation that is
the owner's is given its block, assembled once before understanding, and the same block
reaches its planning round, first in the request, with the flags set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from exchange_support import section, tags
from phases_support import chat_turn, event, phases_harness
from test_activation_state import _admitted
from test_engine import AT as HARNESS_AT
from test_engine import Harness
from understanding_support import (
    EXCERPT_CHARS,
    STATED_PROPOSAL,
    Rendered,
    TextAsStructured,
    rendered,
    understanding_stage,
)

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    DiagnosticKind,
    DiagnosticSource,
    PersonActHow,
    PersonModelAct,
    PlacementReach,
    ProfileField,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.understanding import UNDERSTANDING_PROMPT, UnderstandingStage
from ai_assistant.testing import (
    FakeDiagnosticSink,
    FakeMemoryStore,
    FakeModelProvider,
    FakePersonModelStore,
    FakeToolCallingCompleter,
    default_prompt,
)
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import Memory, Message, PersonModel

pytestmark = pytest.mark.anyio

AT: Final = datetime(2026, 1, 1, 12, tzinfo=UTC)
PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))


class _Counting:
    """The person-model store, counting its reads: the block is assembled once."""

    def __init__(self, store: FakePersonModelStore) -> None:
        self.store = store
        self.reads = 0

    async def read(self, person_id: str) -> PersonModel | None:
        self.reads += 1
        return await self.store.read(person_id)


async def _wired(pinned: Memory = DIET) -> tuple[FakeMemoryStore, _Counting, PersonBlocks]:
    # The harness's own clock, which its episodes are captured at.
    memory_store = FakeMemoryStore(now=lambda: HARNESS_AT)
    await memory_store.add(pinned)
    people = FakePersonModelStore()
    await people.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)
    await people.add_pin(OWNER_PERSON_ID, pinned.id, act=PANEL)
    counting = _Counting(people)
    blocks = PersonBlocks(store=cast("PersonModelStore", counting), memory=memory_store)
    return memory_store, counting, blocks


def _understood(model: FakeModelProvider) -> str:
    """What understanding was shown as always in mind (ADR-0353 §2, §4:5)."""
    return rendered(model.calls[0].messages).section("Always in mind")


def _planned(completer: FakeToolCallingCompleter) -> str:
    """What planning was shown as always in mind (ADR-0356 §3:1)."""
    return section(completer.calls[0].exchange.briefing, "## Always in mind")


def _recorded(
    model: FakeModelProvider, completer: FakeToolCallingCompleter, **knobs: Any
) -> tuple[Harness, FakeDiagnosticSink]:
    """The phases harness with the diagnostic record on, which records each call's flags."""
    sink = FakeDiagnosticSink()
    understanding = UnderstandingStage(
        model=TextAsStructured(model),
        excerpt_chars=EXCERPT_CHARS,
        prompt=default_prompt(UNDERSTANDING_PROMPT),
        diagnostics=sink,
    )
    harness = phases_harness(
        completer,
        understanding=understanding,
        phases={"diagnostics": sink},
        diagnostics=sink,
        **knobs,
    )
    return harness, sink


def _flags(sink: FakeDiagnosticSink, source: DiagnosticSource) -> dict[str, bool]:
    """The person flags the code handed the stage's template (ADR-0335 §9:1).

    Understanding's declares none (ADR-0353 §8:3), so it is handed none.
    """
    given = sink.of(source, DiagnosticKind.GIVEN)[-1]
    flags: dict[str, bool] = given.model_dump(mode="json")["body"]["prompt"]["flags"]
    return {name: flags[name] for name in ("person", "suggestions") if name in flags}


async def test_with_no_store_wired_nothing_of_the_person_model_reaches_a_model() -> None:
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    completer = FakeToolCallingCompleter()
    harness, sink = _recorded(model, completer)

    await chat_turn(harness, "What should I cook tonight?")

    # ADR-0353 §8:1: always in mind is rendered, and says the system does not have it.
    assert _understood(model).startswith("The system does not have it")
    assert _planned(completer).startswith("The system does not have it")
    # Neither stage's template takes a flag (ADR-0353 §8:3, ADR-0356 §4:2).
    assert _flags(sink, DiagnosticSource.UNDERSTANDING) == {}
    assert _flags(sink, DiagnosticSource.PLANNING) == {}


async def test_an_owners_turn_is_given_its_block_in_understanding_and_planning() -> None:
    memory_store, counting, blocks = await _wired()
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    completer = FakeToolCallingCompleter()
    harness, sink = _recorded(model, completer, memory=memory_store, person_blocks=blocks)

    await chat_turn(harness, "What should I cook tonight?")

    understood = _understood(model)
    assert "- How the owner likes to be addressed: Robin." in understood.split("\n")
    (kept,) = Rendered(model.calls[0].messages[1].content).tags("Always in mind", "memory")
    assert (kept.get("label"), kept.get("pinned"), kept.text) == ("M1", "yes", "Eats no meat.")
    planned = _planned(completer)
    assert "- How the owner likes to be addressed: Robin." in planned.split("\n")
    (pinned,) = tags(planned, "memory")
    assert (pinned.get("pinned"), pinned.text) == ("yes", "Eats no meat.")
    assert _flags(sink, DiagnosticSource.UNDERSTANDING) == {}
    assert _flags(sink, DiagnosticSource.PLANNING) == {}
    assert counting.reads == 1


async def test_a_connected_sources_event_is_the_owners_too() -> None:
    memory_store, counting, blocks = await _wired()
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    # One round, which takes no message: a later round's news would read the person
    # model again for what changed (ADR-0360 §4:4).
    harness = phases_harness(
        FakeToolCallingCompleter(),
        memory=memory_store,
        understanding=understanding_stage(model=model),
        person_blocks=blocks,
    )

    await event(harness)

    assert "- How the owner likes to be addressed: Robin." in _understood(model).split("\n")
    assert counting.reads == 1


#: A pin placed for the owner alone: a memory about someone else (ADR-0199 §3).
ABOUT_ADA: Final = memory(
    "m:ada", "Ada is allergic to nuts.", said_support(when=AT, added_at=AT), subjects=("Ada",)
)


@pytest.mark.parametrize(
    ("pinned", "reach"),
    [(DIET, PlacementReach.ANYONE), (ABOUT_ADA, PlacementReach.OWNER)],
    ids=["unrestricted-pin", "restricted-pin"],
)
async def test_the_episode_inherits_the_placement_of_what_the_block_gave_it(
    pinned: Memory, reach: PlacementReach
) -> None:
    """ADR-0309 §5:10, ADR-0217 §3: a pin is a record the activation was given."""
    memory_store, _, blocks = await _wired(pinned)
    harness = phases_harness(memory=memory_store, person_blocks=blocks)

    _, episode = await chat_turn(harness, "What should I cook tonight?")

    assert episode.placement.reach is reach


async def test_an_understanding_run_again_is_given_no_memory_forgotten_since() -> None:
    """§7:10: joined input runs understanding again over the block less what is gone."""
    memory_store, counting, blocks = await _wired()
    harness = phases_harness(memory=memory_store, person_blocks=blocks)
    state = _admitted()
    working = SimpleNamespace(supply=BoundedAudienceSupply(speakable_attested_sources=frozenset()))
    first = await harness.engine._person_block(state, working)  # type: ignore[arg-type]

    await memory_store.delete(DIET.id)
    again = await harness.engine._person_block(state, working)  # type: ignore[arg-type]

    assert first is not None
    assert [one.memory.id for one in first.kept] == [DIET.id]
    assert again is not None
    assert again.kept == ()
    assert again.profile == first.profile
    assert counting.reads == 1
    assert state.person_block is again


async def test_a_pin_understanding_was_shown_is_inherited_though_dropped_before_planning() -> None:
    """ADR-0309 §5:10: forgotten before the first round, it was still given to understanding."""
    memory_store, _, blocks = await _wired(ABOUT_ADA)

    def forgets_while_understanding(messages: Sequence[Message]) -> str:
        # The memory is forgotten after understanding was shown it, before planning: the
        # fake's own record and its walk key, as its delete removes them.
        memory_store._records.pop(ABOUT_ADA.id, None)
        memory_store._keys.pop(ABOUT_ADA.id, None)
        return STATED_PROPOSAL

    completer = FakeToolCallingCompleter()
    harness = phases_harness(
        completer,
        memory=memory_store,
        understanding=understanding_stage(model=FakeModelProvider(forgets_while_understanding)),
        person_blocks=blocks,
    )

    _, episode = await chat_turn(harness, "What should I cook tonight?")

    always = _planned(completer)
    assert tags(always, "memory") == []
    assert "- The owner keeps nothing in mind for the system yet." in always.split("\n")
    assert episode.placement.reach is PlacementReach.OWNER


async def test_a_pin_understanding_was_shown_is_inherited_where_no_round_is_planned() -> None:
    memory_store, _, blocks = await _wired(ABOUT_ADA)
    completer = FakeToolCallingCompleter()
    harness = phases_harness(
        completer,
        memory=memory_store,
        understanding=understanding_stage(model=FakeModelProvider("not json")),
        person_blocks=blocks,
    )

    _, episode = await chat_turn(harness, "What should I cook tonight?")

    assert completer.calls == []
    assert episode.placement.reach is PlacementReach.OWNER

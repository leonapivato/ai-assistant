"""Shared obligations of ``AssistantEngine.export_domain`` (ADR-0385 §6).

Every implementation answers ``export_domain`` from the same stores, each part exactly that
store's own export bound to the owner's sight from the domain named (§6:3 to §6:5), with
the same refusal of a domain no owner's act may name, from the value alone (§6:2, §2:2),
the same ``ValueError`` for a malformed one before any I/O (§6:9), and the same whole or
``OversizedValueError`` (§6:7). A subject is handed to the suite with its six stores empty
but for the owner the person-model store holds as first created.

A mixin, as ``permission_lines_contract`` is, so the engine, the canonical fake and the wire
client each bind it in the file that binds the rest of the suite. What each production
store's bound export holds over another person's rows and rows with no home, in both
builds, is ``test_export_domain.py``'s.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_surface_contract import act, episode

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    DataTier,
    DomainExport,
    DomainExportOutcome,
    DomainExportRefusal,
    DomainExportResult,
    NotificationCandidate,
    RecordHome,
    RecordHomeKind,
    Sight,
    StoryActor,
)
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeConversationStore,
    FakeMemoryStore,
    FakeNotificationPolicy,
    FakePersonModelStore,
    FakePlanStore,
    FakeStoryStore,
)
from ai_assistant.testing.memories import memory

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakeNotificationStore

#: The instant each subject's stores are clocked at.
EXPORT_AT: Final = datetime(2026, 11, 26, 12, tzinfo=UTC)

#: The contract limit each subject is built at: room for a small seeded export.
EXPORT_LIMIT: Final = 256 * 1024

#: The limit the small subject is built at: an empty export fits, a few dozen memories do
#: not.
SMALL_EXPORT_LIMIT: Final = 8 * 1024

_OWNERS: Final = RecordHome.owners()
_SHARED: Final = RecordHome.shared()


@dataclass(frozen=True, slots=True)
class DomainExportSubject:
    """An engine and the six stores its export reads, seeded from the test process.

    Attributes:
        engine: The subject under test.
        memory: The memory store.
        stories: The story store.
        chat: The conversation store.
        plans: The plan store.
        people: The person-model store, holding the owner as first created.
        notifications: The notification store.
    """

    engine: AssistantEngine
    memory: FakeMemoryStore
    stories: FakeStoryStore
    chat: FakeConversationStore
    plans: FakePlanStore
    people: FakePersonModelStore
    notifications: FakeNotificationStore


def fake_domain_export(limit: int) -> DomainExportSubject:
    """The canonical fake over its own six stores, the person model wired, at ``limit``.

    The canonical fake's own subject, and the backing engine of the wire client's.
    """
    built = FakeAssistantEngine(max_payload_bytes=limit)
    built.episode_memory = FakeMemoryStore(now=lambda: EXPORT_AT)
    built.story_store = FakeStoryStore(now=lambda: EXPORT_AT)
    built.plan_store = FakePlanStore(now=lambda: EXPORT_AT)
    # The fake's own chat space mints only for a conversation joining through it; the
    # suite seeds conversations into the store directly.
    built.chat = FakeConversationStore(now=lambda: EXPORT_AT)
    people = FakePersonModelStore(now=lambda: EXPORT_AT)
    built.person_blocks = PersonBlocks(store=people, memory=built.episode_memory)
    return DomainExportSubject(
        engine=built,
        memory=built.episode_memory,
        stories=built.story_store,
        chat=built.chat,
        plans=built.plan_store,
        people=people,
        notifications=built.notification_store,
    )


def _candidate(key: str) -> NotificationCandidate:
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class="calendar",
        summary=f"something about {key}",
        noticed_at=EXPORT_AT - timedelta(minutes=5),
        # Far ahead: the notification stores read their own clocks.
        expires_at=EXPORT_AT + timedelta(days=36500),
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


async def seed(subject: DomainExportSubject) -> None:
    """Records of the owner's domain and of the shared things in each store with homes.

    The owner's: an episode and a memory, a story, a conversation, a held notification,
    and the owner's person model. The shared things': a memory, a story, a conversation
    and a held notification.
    """
    await subject.memory.add(episode("a-own"))
    await subject.memory.add(memory("m-own", "they like the window seat", home=_OWNERS))
    await subject.memory.add(memory("m-shared", "the hall light is on a timer", home=_SHARED))
    for activation, home in (("a-own", _OWNERS), ("a-shared", _SHARED)):
        made = await subject.stories.create([act(activation)], home=home, actor=StoryActor.OWNER)
        assert made.story_id is not None
    await subject.chat.start(home=_OWNERS)
    await subject.chat.start(home=_SHARED)
    for key, home in (("k-own", _OWNERS), ("k-shared", _SHARED)):
        ruled = await subject.notifications.admit(
            _candidate(key), home=home, policy=FakeNotificationPolicy()
        )
        assert ruled.notification_id is not None


def _without_instants(part: Any) -> dict[str, Any]:
    """A part's JSON projection, its export instant left out: the stores stamp their own."""
    dumped: dict[str, Any] = part.model_dump(mode="json")
    dumped.pop("exported_at", None)
    return dumped


async def _as_bound(subject: DomainExportSubject, domain: RecordHome) -> dict[str, Any]:
    """Each store's own export, bound to the owner's sight from ``domain`` (§6:3, §6:5)."""
    sight = Sight.of_owners_act(domain)
    return {
        "memory": tuple(await subject.memory.bound(sight).export()),
        "stories": await subject.stories.bound(sight).export(),
        "conversations": _without_instants(await subject.chat.bound(sight).export()),
        "plans": _without_instants(await subject.plans.bound(sight).export()),
        "person_model": await subject.people.bound(sight).export(),
        "notifications": tuple(await subject.notifications.bound(sight).export()),
    }


def _parts(export: DomainExport) -> dict[str, Any]:
    return {
        "memory": export.memory,
        "stories": export.stories,
        "conversations": _without_instants(export.conversations),
        "plans": _without_instants(export.plans),
        "person_model": export.person_model,
        "notifications": export.notifications,
    }


def _homes(export: DomainExport) -> set[RecordHome]:
    """Every home a record of the export carries."""
    return {
        *(one.home for one in export.memory),
        *(one.story.home for one in export.stories.stories),
        *(one.home for one in export.conversations.conversations),
        *(one.home for one in export.notifications),
    }


def _exported(result: DomainExportResult, domain: RecordHome) -> DomainExport:
    assert result.outcome is DomainExportOutcome.EXPORTED
    assert result.refusal is None
    assert result.export is not None
    assert result.export.domain == domain
    assert result.export.exported_at.tzinfo is not None
    return result.export


#: Values that are no well-formed home, each refused with ``ValueError`` (§6:9).
MALFORMED: Final[tuple[object, ...]] = (
    "mine",
    None,
    {"kind": "shared"},
    RecordHome.model_construct(kind="shared"),
    RecordHome.model_construct(kind=RecordHomeKind.SHARED, id="x"),
    RecordHome.model_construct(kind=RecordHomeKind.PERSON),
    RecordHome.model_construct(kind=RecordHomeKind.PERSON, id=""),
)

#: Well-formed homes no owner's act may name (§2:2).
NOT_OFFERED: Final = (
    RecordHome.person("person:sam"),
    RecordHome.group("group:house"),
    RecordHome.group(OWNER_PERSON_ID),
)


class DomainExportContract:
    """``export_domain`` through the engine, the fake and the wire client alike."""

    @pytest.fixture
    def domain_export_subject(self) -> DomainExportSubject:
        """Override with an implementation over the six stores, at :data:`EXPORT_LIMIT`."""
        raise NotImplementedError

    @pytest.fixture
    def domain_export_small(self) -> DomainExportSubject:
        """Override with the same, built at :data:`SMALL_EXPORT_LIMIT`."""
        raise NotImplementedError

    @pytest.mark.parametrize("domain", [_OWNERS, _SHARED], ids=["owners", "shared"])
    async def test_each_part_is_its_stores_own_export_bound_to_the_owners_sight(
        self, domain_export_subject: DomainExportSubject, domain: RecordHome
    ) -> None:
        """§6:3 to §6:5: each part is exactly that store's export, nothing filtered."""
        subject = domain_export_subject
        await seed(subject)

        result = await subject.engine.export_domain(domain)

        export = _exported(result, domain)
        assert _parts(export) == await _as_bound(subject, domain)
        assert _homes(export) == {domain}
        assert export.plans.stopped_activations == ()

    async def test_the_owners_domain_holds_the_owners_records_and_none_of_the_shared(
        self, domain_export_subject: DomainExportSubject
    ) -> None:
        """§6:4: of the domain named and of nothing else."""
        subject = domain_export_subject
        await seed(subject)

        export = _exported(await subject.engine.export_domain(_OWNERS), _OWNERS)

        assert {one.id for one in export.memory} == {"activation:a-own", "m-own"}
        assert len(export.stories.stories) == 1
        assert len(export.conversations.conversations) == 1
        assert [one.candidate.candidate_key for one in export.notifications] == ["k-own"]
        assert [one.id for one in export.person_model.persons] == [OWNER_PERSON_ID]

    async def test_the_shared_things_hold_theirs_and_none_of_the_owners(
        self, domain_export_subject: DomainExportSubject
    ) -> None:
        """§6:4, the reverse; the person model holds no record of the shared things."""
        subject = domain_export_subject
        await seed(subject)

        export = _exported(await subject.engine.export_domain(_SHARED), _SHARED)

        assert {one.id for one in export.memory} == {"m-shared"}
        assert len(export.stories.stories) == 1
        assert len(export.conversations.conversations) == 1
        assert [one.candidate.candidate_key for one in export.notifications] == ["k-shared"]
        assert export.person_model.persons == ()
        assert export.person_model.profiles == ()

    async def test_a_domain_the_stores_hold_nothing_of_is_exported_with_every_part_empty(
        self, domain_export_subject: DomainExportSubject
    ) -> None:
        """§6:7's last sentence."""
        subject = domain_export_subject

        export = _exported(await subject.engine.export_domain(_SHARED), _SHARED)

        assert export.memory == ()
        assert export.stories.stories == ()
        assert export.conversations.conversations == ()
        assert export.conversations.messages == ()
        assert _without_instants(export.plans) == _without_instants(
            await subject.plans.bound(Sight.of_owners_act(_SHARED)).export()
        )
        assert export.plans.activation_effects == ()
        assert export.plans.observations == ()
        assert export.plans.scheduled_tasks == ()
        assert export.plans.approval_requests == ()
        assert export.person_model.persons == ()
        assert export.notifications == ()

    @pytest.mark.parametrize("domain", NOT_OFFERED, ids=["a-person", "a-group", "owners-name"])
    async def test_a_domain_no_owners_act_may_name_is_refused_alike_whatever_is_held(
        self, domain_export_subject: DomainExportSubject, domain: RecordHome
    ) -> None:
        """§6:2, §2:2: refused ``not_offered`` from the value alone, the same answer over
        empty stores and seeded ones."""
        subject = domain_export_subject
        empty = await subject.engine.export_domain(domain)
        await seed(subject)

        seeded = await subject.engine.export_domain(domain)

        assert empty == seeded == DomainExportResult.not_offered()
        assert seeded.refusal is DomainExportRefusal.NOT_OFFERED
        assert seeded.export is None

    @pytest.mark.parametrize("domain", MALFORMED, ids=lambda one: type(one).__name__)
    async def test_a_malformed_domain_is_refused_with_value_error(
        self, domain_export_subject: DomainExportSubject, domain: object
    ) -> None:
        """§6:9: before any I/O."""
        with pytest.raises(ValueError, match="a domain is a record home"):
            await domain_export_subject.engine.export_domain(domain)  # type: ignore[arg-type]

    async def test_an_export_past_the_limit_is_refused_whole(
        self, domain_export_small: DomainExportSubject
    ) -> None:
        """§6:7: whole, or ``OversizedValueError``; never truncated or split."""
        subject = domain_export_small
        assert (await subject.engine.export_domain(_OWNERS)).export is not None
        for index in range(60):
            await subject.memory.add(
                memory(f"m-{index:03d}", f"a fact about the window seat, number {index}")
            )

        with pytest.raises(OversizedValueError):
            await subject.engine.export_domain(_OWNERS)
        shared = await subject.engine.export_domain(_SHARED)
        assert shared.export is not None
        assert shared.export.memory == ()

    async def test_the_result_round_trips_through_its_json(
        self, domain_export_subject: DomainExportSubject
    ) -> None:
        """§6:8, §6:10: frozen models in ``core``, so the document validates back."""
        subject = domain_export_subject
        await seed(subject)

        result = await subject.engine.export_domain(_OWNERS)

        assert DomainExportResult.model_validate_json(result.model_dump_json()) == result

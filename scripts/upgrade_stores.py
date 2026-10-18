"""Every store a person's hub keeps, as ADR-0326 §7's upgrade check writes and reads it.

The upgrade check (``scripts/upgrade_check.py``) writes a data directory with the build
at a pull request's base and opens it with the build at its head. This module is the
half of it that knows the stores: for each one, which files it keeps under
``Settings.data_dir``, how to write records into it through its own API, and how to read
every record back as plain JSON. It is run by **both** builds: the base's copy of this
file writes and reads under the base's code, and the head's copy reads under the head's.

**A pull request that adds a store adds it here** (ADR-0326 §7:3). The check makes
forgetting hard twice over: a file the head's composition leaves under the data
directory that no entry of :data:`STORES` claims fails the check, and
``tests/upgrade/test_upgrade_stores.py`` fails on any ``*.db`` file name in the package
that no entry claims, a store only a setting opens included.

**A pull request that changes what a store reads back** — a field renamed, a value
reshaped, a record dropped by its upgrade under the owner's ruling (ADR-0326 §4:4) —
says so here, by raising that store's :attr:`Store.shape` and adding a carry from the
old shape (:attr:`Store.carries`). The carry is what "carried as the head's upgrades
carry it" (§7:2) means in the check: it turns what the base build read back into what
the head build must read back. A field *added* to a stored model needs no carry, since
the comparison lets the head read back more than the base did; anything else that
differs fails until a carry says it should.

**Writes go through each store's public API, never hand-built SQLite** (the brief for
#3136), with records shaped the way the package's own contract suites shape them. Every
store is opened at the path :func:`ai_assistant.app.build_composition` (or, for the
device roster, ``service/hub.py``) opens it at, with the tuning
:func:`check_settings` gives the composition.

**The diagnostic record is not here** (ADR-0326 §8): the check neither writes nor opens
it, and the coverage rule ignores ``diagnostics/``. Nor are the instance lock and the
sockets (§2:2).
"""

from __future__ import annotations

import dataclasses
import enum
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from pydantic import BaseModel

from ai_assistant.app.composition import telegram_intake_path
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ActionRequest,
    ActivationEffect,
    Attestation,
    ChannelContext,
    ChannelIdentity,
    ChatDevice,
    CostBasis,
    DataTier,
    DeviceAccess,
    DeviceRole,
    EpisodeProcessingRecord,
    EpisodicMemory,
    EvaluationTrace,
    GrantScope,
    Idempotency,
    InputOrigin,
    MemorySource,
    MessageAuthor,
    NewMessage,
    NotificationCandidate,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PreferenceMemory,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    ProvisioningState,
    ReadOutcome,
    RecordedChannelTrigger,
    RecordedTextInput,
    Reversibility,
    RiskLevel,
    SecretName,
    SecretScope,
    SemanticMemory,
    SourceGrant,
    SourceReadRecord,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
    TelegramOutcome,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    TraceKind,
    TraceOutcome,
    UnderstandingOmission,
)
from ai_assistant.evaluation import SqliteTraceStore
from ai_assistant.memory import (
    DefaultNotificationPolicy,
    SqliteMemoryStore,
    SqliteNotificationOutbox,
    SqliteNotificationStore,
    SqliteStoryStore,
    SqliteTelegramIntakeRecord,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.permissions import (
    SqliteAuditTrail,
    SqliteSourceGrantStore,
    SqliteSourceReadTrail,
)
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.service.enrolment import ENROLMENTS_FILENAME, EnrolmentStore
from ai_assistant.testing import with_phase_declaration
from ai_assistant.testing.activation import ended_pass
from ai_assistant.tools.booking import (
    CHARGED_AMOUNT_KEY,
    CHARGED_CURRENCY_KEY,
    DATE_ARGUMENT,
    ORIGIN_ARGUMENT,
    SqliteBookingStore,
)
from ai_assistant.tools.connection_store import ConnectionEntry, SqliteConnectionStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import TraceSink

#: A JSON value, as a snapshot holds one.
type Json = None | bool | int | float | str | list[Json] | dict[str, Json]

#: One store's records as read back: a stable key per record, its value as JSON.
type Records = dict[str, Json]

#: The Telegram line the check configures, so the composition opens its intake record.
TELEGRAM_CONNECTION: Final = "conn-telegram-upgrade"
TELEGRAM_CHAT_ID: Final = 424242

#: The booking provider the check configures, so the composition opens its store.
BOOKING_CONNECTION: Final = "conn-booking-upgrade"
BOOKING_ENDPOINT: Final = "https://bookings.example.invalid"
BOOKING_RETAINED: Final = 5

#: The walk the memory writer advances, so a recorded position is read back.
_WALK: Final = "upgrade-check"

#: How many items a listing read asks for: far more than any writer here writes, so a
#: read-back is whole.
_PAGE: Final = 500


def check_settings(directory: Path) -> Settings:
    """The settings both builds compose the data directory with.

    Every store the composition opens only on a setting is switched on: the Telegram
    line's intake record and the booking provider's store. The hashing embedder keeps
    the check offline and quick; the memory store's schema and its upgrades are the
    same code whichever embedder fills the vectors.

    Args:
        directory: The data directory, absolute and canonical.

    Returns:
        The settings. Nothing is read from the environment file; the caller runs with no
        ``ASSISTANT_*`` variable set (``scripts/upgrade_check.py`` clears them).
    """
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings' init-only switch
        data_dir=directory,
        embedder=EmbedderKind.HASHING,
        telegram_connection=TELEGRAM_CONNECTION,
        telegram_user_id=TELEGRAM_CHAT_ID,
        booking_connection=BOOKING_CONNECTION,
        booking_endpoint=BOOKING_ENDPOINT,
        booking_available_from=date(2026, 10, 1),
        booking_available_to=date(2099, 12, 31),
        booking_price_amount=Decimal("120.00"),
        booking_price_currency="EUR",
        booking_billed_amount=Decimal("120.00"),
        booking_billed_currency="EUR",
        booking_retained_records=BOOKING_RETAINED,
    )


#: The values :func:`to_json` spells as text, each by its own conversion.
_AS_TEXT: Final[tuple[tuple[type, Callable[[object], Json]], ...]] = (
    (datetime, lambda value: cast("datetime", value).isoformat()),
    (date, lambda value: cast("date", value).isoformat()),
    (Decimal, str),
    (timedelta, lambda value: cast("timedelta", value).total_seconds()),
)


def to_json(value: object) -> Json:
    """``value`` as plain JSON: models dumped, dataclasses walked, instants as text.

    Args:
        value: What a store's read returned.

    Returns:
        The JSON value. Sets are sorted, so two reads of one set compare equal.

    Raises:
        TypeError: If ``value`` holds something this function has no spelling for.
    """
    if isinstance(value, enum.Enum):
        value = value.value
    if value is None or isinstance(value, bool | int | float | str):
        return value
    for kind, spell in _AS_TEXT:
        if isinstance(value, kind):
            return spell(value)
    if isinstance(value, BaseModel):
        return to_json(value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return _compound(value)


def _compound(value: object) -> Json:
    """A mapping, set or sequence as JSON, for :func:`to_json`."""
    if isinstance(value, Mapping):
        return {str(key): to_json(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((to_json(item) for item in value), key=json.dumps)
    if isinstance(value, Sequence):
        return [to_json(item) for item in value]
    msg = f"no JSON spelling for {type(value).__name__}"
    raise TypeError(msg)


def _keyed(prefix: str, items: Sequence[object], key: Callable[[Json], str]) -> Records:
    """``items`` as JSON, each under ``prefix`` and the key ``key`` reads off it."""
    records: Records = {}
    for item in items:
        value = to_json(item)
        records[f"{prefix}/{key(value)}"] = value
    return records


def _field(name: str) -> Callable[[Json], str]:
    """A key function reading one top-level field of a record."""

    def read(value: Json) -> str:
        assert isinstance(value, dict)  # noqa: S101  # every keyed read is a model
        return str(value[name])

    return read


@dataclass(frozen=True, slots=True)
class Moment:
    """The instant a write is stamped from, so every record is recent and none expires.

    Attributes:
        now: When the writer started, to the second.
    """

    now: datetime

    def ago(self, **delta: float) -> datetime:
        """An instant ``delta`` before :attr:`now`.

        Args:
            **delta: :class:`~datetime.timedelta`'s keywords.

        Returns:
            The instant.
        """
        return self.now - timedelta(**delta)


#: Writes one store's records into the data directory.
type Writer = Callable[[Path, Moment], Awaitable[None]]
#: Reads every record of one store back from the data directory.
type Reader = Callable[[Path], Awaitable[Records]]
#: Turns a store's read-back at one shape into what it reads back at the next.
type Carry = Callable[[Records], Records]


@dataclass(frozen=True, slots=True)
class Store:
    """One store a person's hub keeps, as the upgrade check covers it.

    Attributes:
        name: The store's name in a snapshot.
        files: The file names it keeps directly under the data directory, as
            :func:`fnmatch.fnmatch` patterns. Each also covers its SQLite sidecars.
        write: Writes its records through its own API.
        read: Reads every record back.
        shape: What its read-back looks like. Raised by a pull request whose head reads
            back something other than its base did, with a carry from the old value.
        carries: For each shape below :attr:`shape`, the carry to the next one.
    """

    name: str
    files: tuple[str, ...]
    write: Writer
    read: Reader
    shape: int = 1
    carries: Mapping[int, Carry] = field(default_factory=dict)


# --- traces.db ------------------------------------------------------------------------


def _traces(directory: Path) -> SqliteTraceStore:
    return SqliteTraceStore(path=directory / "traces.db")


async def _write_traces(directory: Path, moment: Moment) -> None:
    store = _traces(directory)
    try:
        await store.emit(
            EvaluationTrace(
                kind=TraceKind.OPERATION,
                seam="upgrade_check",
                occurred_at=moment.ago(minutes=5),
                outcome=TraceOutcome.OK,
            )
        )
    finally:
        store.close()


async def _read_traces(directory: Path) -> Records:
    store = _traces(directory)
    try:
        traces: list[EvaluationTrace] = []
        chunk = await store.walk(limit=_PAGE)
        while chunk.traces:
            traces.extend(chunk.traces)
            chunk = await store.walk(after=chunk.position, limit=_PAGE)
        return _keyed("trace", traces, _field("id"))
    finally:
        store.close()


# --- memory.db ------------------------------------------------------------------------


def _memory(directory: Path, traces: TraceSink) -> SqliteMemoryStore:
    return SqliteMemoryStore(
        path=directory / "memory.db", embedder=HashingEmbedder(), traces_sink=traces
    )


def _provenance(moment: Moment, source: MemorySource = MemorySource.OBSERVED) -> Provenance:
    certain = source is MemorySource.USER_ASSERTED
    return Provenance(
        source=source,
        confidence=1.0 if certain else 0.6,
        last_updated=moment.ago(minutes=30),
        attestation=(
            Attestation(reported_by="calendar", reported_at=moment.ago(minutes=30))
            if source is MemorySource.EXTERNAL
            else None
        ),
    )


def _activation_episode(moment: Moment) -> EpisodicMemory:
    """An ended activation's episode, with its processing record (ADR-0275)."""
    channel = ChannelIdentity(channel_type="conversation", instance_id="upgrade-chat")
    ended = moment.ago(minutes=20)
    return EpisodicMemory(
        id="mem-episode-activation",
        content="The user asked when the dentist appointment is.",
        provenance=_provenance(moment),
        occurred_at=ended,
        processing_record=EpisodeProcessingRecord(
            activation_id="act-upgrade-1",
            started_at=moment.ago(minutes=21),
            ended_at=ended,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel,
                payload=RecordedTextInput(text="When is the dentist?"),
                context=ChannelContext(),
                reply=None,
                origin=InputOrigin.USER,
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(ended),
        ),
    )


async def _write_memory(directory: Path, moment: Moment) -> None:
    traces = _traces(directory)
    store = _memory(directory, traces)
    try:
        await store.add(
            SemanticMemory(
                id="mem-semantic",
                content="The user's sister is called Ada.",
                fact="The user's sister is called Ada.",
                provenance=_provenance(moment, MemorySource.USER_ASSERTED),
                topics=("family",),
                about_person="Ada",
            )
        )
        await store.add(
            PreferenceMemory(
                id="mem-preference",
                content="The user prefers mornings for appointments.",
                preference="The user prefers mornings for appointments.",
                provenance=_provenance(moment),
            )
        )
        await store.add(
            EpisodicMemory(
                id="mem-episode",
                content="The user moved to Lisbon.",
                provenance=_provenance(moment),
                occurred_at=moment.ago(days=2),
            )
        )
        await store.add(_activation_episode(moment))
        chunk = await store.walk_records(_WALK, limit=2)
        if chunk.position is not None:
            await store.advance_walk(_WALK, position=chunk.position)
    finally:
        store.close()
        traces.close()


async def _read_memory(directory: Path) -> Records:
    """Every record, the walk's resumption, and whether each record's vector finds it.

    The records alone would miss an upgrade that kept every row and lost the vector
    index ``search`` reads, so each record is searched for by its own content: the
    hashing embedder maps that text onto the record's own vector, so a record whose
    vector survived finds itself.
    """
    traces = _traces(directory)
    store = _memory(directory, traces)
    try:
        exported = await store.export()
        records = _keyed("record", exported, _field("id"))
        rest = await store.walk_records(_WALK, limit=_PAGE)
        records["walk"] = [record.id for record in rest.records]
        for record in exported:
            if record.content:
                found = await store.search(record.content, limit=len(exported))
                records[f"found/{record.id}"] = record.id in {hit.id for hit in found.records}
        return records
    finally:
        store.close()
        traces.close()


# --- stories.db -----------------------------------------------------------------------


def _stories(directory: Path) -> SqliteStoryStore:
    return SqliteStoryStore(path=directory / "stories.db")


async def _write_stories(directory: Path, moment: Moment) -> None:
    del moment  # the store stamps every change with its own clock
    store = _stories(directory)
    try:
        made = await store.create(
            (StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-upgrade-1"),),
            actor=StoryActor.OWNER,
        )
        story = made.story_id
        assert story is not None, made  # noqa: S101  # a refusal is the writer's bug
        await store.link(
            story,
            (StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-upgrade-2"),),
            actor=StoryActor.PLANNING,
            trigger="act-upgrade-2",
        )
        await store.append_note(
            story,
            "The appointment moved to Thursday.",
            author=StoryNoteAuthor.PLANNING,
            written_during="act-upgrade-2",
        )
        await store.append_note(story, "Ask about the bill.", author=StoryNoteAuthor.OWNER)
        state = await store.current_summary(story)
        assert state is not None  # noqa: S101  # the story was just made
        await store.write_summary(
            story,
            StorySummaryDraft(
                lines=(StorySummaryLine(text="The dentist appointment, now Thursday."),),
                outside=False,
            ),
            as_of=state.as_of,
        )
        second = await store.create(
            (StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-upgrade-3"),),
            actor=StoryActor.UNDERSTANDING,
            trigger="act-upgrade-3",
        )
        assert second.story_id is not None, second  # noqa: S101
    finally:
        store.close()


async def _read_stories(directory: Path) -> Records:
    store = _stories(directory)
    try:
        records: Records = {}
        page = await store.stories(limit=MAX_STORY_PAGE)
        for header in page.stories:
            story = header.story_id
            records[f"story/{story}"] = to_json(header)
            records[f"view/{story}"] = to_json(await store.view(story, limit=MAX_STORY_PAGE))
            records[f"log/{story}"] = to_json(await store.log(story, limit=MAX_STORY_PAGE))
            records[f"notes/{story}"] = to_json(await store.notes(story, limit=MAX_STORY_PAGE))
            records[f"summaries/{story}"] = to_json(
                await store.summary_versions(story, limit=MAX_STORY_PAGE)
            )
            records[f"summary/{story}"] = to_json(await store.current_summary(story))
        return records
    finally:
        store.close()


# --- audit.db -------------------------------------------------------------------------


def _audit(directory: Path) -> SqliteAuditTrail:
    return SqliteAuditTrail(path=directory / "audit.db")


def _tool(**overrides: object) -> ToolDefinition:
    fields: dict[str, object] = {
        "id": "send_email",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**with_phase_declaration(fields))  # type: ignore[arg-type]


def _decision(
    decision_id: str, outcome: PermissionOutcome, at: datetime, tool: ToolDefinition
) -> PermissionDecision:
    return PermissionDecision.from_request(
        ActionRequest(tool=tool),
        PermissionRuling(outcome=outcome, reason=f"ruled {outcome}"),
        id=decision_id,
        decided_at=at,
    )


async def _write_audit(directory: Path, moment: Moment) -> None:
    store = _audit(directory)
    try:
        await store.record(
            _decision("d-upgrade-confirm", PermissionOutcome.CONFIRM, moment.ago(hours=2), _tool())
        )
        allowed = _decision(
            "d-upgrade-allow", PermissionOutcome.ALLOW, moment.ago(hours=1), _tool()
        )
        await store.record(allowed)
        claim = await store.claim_invocation(decision=allowed)
        await store.complete_invocation(
            claim_id=claim.id,
            outcome=ToolOutcome.SUCCEEDED,
            incurred_cost=ToolCost(basis=CostBasis.FREE),
        )
    finally:
        store.close()


async def _read_audit(directory: Path) -> Records:
    store = _audit(directory)
    try:
        records = _keyed("decision", await store.export(), _field("id"))
        for recorded in await store.export_invocations():
            records[f"invocation/{recorded.invocation.id}"] = to_json(recorded)
        return records
    finally:
        store.close()


# --- plans.db -------------------------------------------------------------------------


def _plans(directory: Path) -> SqlitePlanStore:
    return SqlitePlanStore(path=directory / "plans.db")


async def _write_plans(directory: Path, moment: Moment) -> None:
    store = _plans(directory)
    try:
        await store.record_stop("act-upgrade-stopped")
        await store.claim_activation_effect(
            ActivationEffect(
                id="effect-upgrade-1",
                activation_id="act-upgrade-1",
                round="r1",
                capability="book_stay",
                values_digest="a" * 64,
                decision_id="d-upgrade-allow",
                claimed_at=moment.ago(minutes=15),
            ),
            match=None,
        )
        await store.finish_activation_effect("effect-upgrade-1", ToolOutcome.SUCCEEDED)
        await store.claim_activation_effect(
            ActivationEffect(
                id="effect-upgrade-2",
                activation_id="act-upgrade-1",
                round="r1",
                place="c-1",
                claimed_at=moment.ago(minutes=14),
            ),
            match=None,
        )
    finally:
        store.close()


async def _read_plans(directory: Path) -> Records:
    store = _plans(directory)
    try:
        exported = await store.export()
        return {
            "stopped": to_json(exported.stopped_activations),
            **_keyed("effect", exported.activation_effects, _field("id")),
        }
    finally:
        store.close()


# --- conversations.db -----------------------------------------------------------------


def _conversations(directory: Path) -> SqliteConversationStore:
    settings = check_settings(directory)
    return SqliteConversationStore(
        path=directory / "conversations.db",
        retention=settings.episode_retention,
        tombstone_grace=settings.conversation_tombstone_grace,
    )


async def _write_conversations(directory: Path, moment: Moment) -> None:
    store = _conversations(directory)
    phone = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
    try:
        await store.set_my_devices((phone,))
        conversation = await store.start()
        await store.set_conversation_devices(
            conversation.id, (phone, ChatDevice(device_id="laptop", access=DeviceAccess.READ))
        )
        await store.record_turn(
            conversation.id, episode_id="mem-episode-activation", occurred_at=moment.ago(minutes=20)
        )
        await store.append_message(
            conversation.id,
            NewMessage(
                author=MessageAuthor.USER,
                text="When is the dentist?",
                device_id="phone",
                message_id="phone-msg-1",
            ),
        )
        await store.append_message(
            conversation.id,
            NewMessage(
                author=MessageAuthor.ASSISTANT,
                text="Thursday at nine.",
                replies_to=1,
                options=("Thanks", "Move it"),
            ),
        )
        await store.append_message(
            conversation.id,
            NewMessage(
                author=MessageAuthor.USER,
                text="Thanks",
                device_id="phone",
                message_id="phone-msg-2",
                replies_to=2,
            ),
        )
        await store.take_in(conversation.id, positions=(1,), activation_id="act-upgrade-1")
        removed = await store.start()
        await store.set_conversation_devices(removed.id, (phone,))
        await store.append_message(
            removed.id,
            NewMessage(
                author=MessageAuthor.USER,
                text="Never mind.",
                device_id="phone",
                message_id="phone-msg-3",
            ),
        )
        await store.stamp_deleted(removed.id)
    finally:
        store.close()


async def _read_conversations(directory: Path) -> Records:
    store = _conversations(directory)
    try:
        exported = await store.export()
        records = _keyed("conversation", exported.conversations, _field("id"))
        for message in exported.messages:
            records[f"message/{message.conversation_id}/{message.position}"] = to_json(message)
        for conversation in exported.conversations:
            records[f"devices/{conversation.id}"] = to_json(
                await store.conversation_devices(conversation.id)
            )
            records[f"untaken/{conversation.id}"] = to_json(
                await store.untaken_messages(conversation.id)
            )
        records["my_devices"] = to_json(await store.my_devices())
        # A conversation stamped deleted is absent from the export and held until its
        # grace runs out; that it is still held is what this reads.
        records["stamped"] = to_json(await store.stamped_conversation_ids())
        return records
    finally:
        store.close()


# --- grants.db ------------------------------------------------------------------------


def _grants(directory: Path) -> SqliteSourceGrantStore:
    return SqliteSourceGrantStore(path=directory / "grants.db")


async def _write_grants(directory: Path, moment: Moment) -> None:
    store = _grants(directory)
    try:
        await store.record(
            SourceGrant(
                id="grant-upgrade-1",
                source="calendar",
                scope=(GrantScope.INGEST, GrantScope.NOTIFY),
                decided_at=moment.ago(days=1),
            )
        )
        await store.record(
            SourceGrant(
                id="grant-upgrade-2",
                source="calendar",
                scope=(GrantScope.INGEST, GrantScope.NOTIFY),
                decided_at=moment.ago(hours=3),
                revokes="grant-upgrade-1",
            )
        )
    finally:
        store.close()


async def _read_grants(directory: Path) -> Records:
    store = _grants(directory)
    try:
        return _keyed("grant", await store.export(), _field("id"))
    finally:
        store.close()


# --- reads.db -------------------------------------------------------------------------


def _reads(directory: Path) -> SqliteSourceReadTrail:
    return SqliteSourceReadTrail(
        path=directory / "reads.db",
        max_rows=check_settings(directory).source_read_trail_max_rows,
    )


async def _write_reads(directory: Path, moment: Moment) -> None:
    store = _reads(directory)
    try:
        await store.record(
            SourceReadRecord(
                id="read-upgrade-1",
                source="calendar",
                use=GrantScope.NOTIFY,
                checked_at=moment.ago(minutes=40),
                outcome=ReadOutcome.COMPLETED,
                grant="grant-upgrade-1",
                produced=3,
            )
        )
        await store.record(
            SourceReadRecord(
                id="read-upgrade-2",
                source="calendar",
                use=GrantScope.INGEST,
                checked_at=moment.ago(minutes=10),
                outcome=ReadOutcome.REFUSED,
                grant=None,
                produced=0,
            )
        )
    finally:
        store.close()


async def _read_reads(directory: Path) -> Records:
    store = _reads(directory)
    try:
        return _keyed("read", await store.export(), _field("id"))
    finally:
        store.close()


# --- notifications.db and outbox.db ---------------------------------------------------


def _notifications(directory: Path, traces: TraceSink) -> SqliteNotificationStore:
    settings = check_settings(directory)
    return SqliteNotificationStore(
        path=directory / "notifications.db",
        traces_sink=traces,
        retention=settings.notification_retention,
        cap=settings.notification_queue_limit,
    )


def _candidate(key: str, moment: Moment) -> NotificationCandidate:
    return NotificationCandidate(
        candidate_key=key,
        producer="upcoming",
        notification_class="calendar",
        summary="The dentist is on Thursday at nine.",
        noticed_at=moment.ago(minutes=3),
        confidence=0.8,
        sensitivity=DataTier.PERSONAL,
    )


async def _write_notifications(directory: Path, moment: Moment) -> None:
    traces = _traces(directory)
    store = _notifications(directory, traces)
    try:
        policy = DefaultNotificationPolicy(timezone=check_settings(directory).timezone)
        await store.admit(_candidate("upgrade-held", moment), policy=policy)
    finally:
        store.close()
        traces.close()


async def _read_notifications(directory: Path) -> Records:
    traces = _traces(directory)
    store = _notifications(directory, traces)
    try:
        records = _keyed("held", await store.export(), _field("id"))
        records["preferences"] = to_json(await store.preferences())
        return records
    finally:
        store.close()
        traces.close()


def _outbox(directory: Path, records: SqliteNotificationStore) -> SqliteNotificationOutbox:
    settings = check_settings(directory)
    return SqliteNotificationOutbox(
        path=directory / "outbox.db",
        records=records,
        lease=settings.hub_notification_lease,
        max_entries=settings.hub_notification_outbox_entries,
        max_bytes=settings.hub_notification_outbox_bytes,
        candidate_ceiling=settings.hub_max_frame_bytes // 2,
    )


async def _write_outbox(directory: Path, moment: Moment) -> None:
    traces = _traces(directory)
    records = _notifications(directory, traces)
    store = _outbox(directory, records)
    try:
        await store.offer(_candidate("upgrade-queued", moment))
    finally:
        store.close()
        records.close()
        traces.close()


async def _read_outbox(directory: Path) -> Records:
    """The queued entries, by claiming each — a read that leases, on a throwaway copy.

    The outbox has no listing read: an entry is seen only by claiming it. The check
    reads every store from a copy of the directory it checks (``upgrade_check.py``),
    so the lease this takes is never in the directory under test.
    """
    traces = _traces(directory)
    records = _notifications(directory, traces)
    store = _outbox(directory, records)
    try:
        await store.recover_leases()
        claimed: Records = {}
        while (delivery := await store.claim()) is not None:
            value = to_json(delivery)
            assert isinstance(value, dict)  # noqa: S101  # a model dumps to an object
            value.pop("delivery_id", None)  # minted fresh by each claim
            claimed[f"entry/{delivery.notification.candidate_key}"] = value
        return claimed
    finally:
        store.close()
        records.close()
        traces.close()


# --- connections.db -------------------------------------------------------------------


def _connections(directory: Path) -> SqliteConnectionStore:
    return SqliteConnectionStore(path=directory / "connections.db")


def _slot(key: str) -> SecretName:
    return SecretName(scope=SecretScope.INTEGRATION, key=key)


async def _write_connections(directory: Path, moment: Moment) -> None:
    del moment  # the store stamps nothing
    store = _connections(directory)
    try:
        for reference in (TELEGRAM_CONNECTION, "conn-mail-upgrade"):
            await store.append(
                ConnectionEntry(
                    reference=reference,
                    revision=1,
                    identity="owner@example.com",
                    state=ProvisioningState.PENDING,
                    slot=_slot(f"{reference}-1"),
                ),
                expected_latest=None,
            )
            latest = await store.latest(reference)
            assert latest is not None  # noqa: S101  # just appended
            await store.append(
                ConnectionEntry(
                    reference=reference,
                    revision=2,
                    identity="owner@example.com",
                    state=ProvisioningState.ACTIVE,
                    slot=_slot(f"{reference}-2"),
                ),
                expected_latest=latest.sequence,
            )
        removed = await store.latest("conn-mail-upgrade")
        assert removed is not None  # noqa: S101
        await store.append(
            ConnectionEntry(
                reference="conn-mail-upgrade", revision=3, identity=None, state=None, slot=None
            ),
            expected_latest=removed.sequence,
        )
    finally:
        store.close()


async def _read_connections(directory: Path) -> Records:
    store = _connections(directory)
    try:
        acts = await store.recent(limit=_PAGE)
        records: Records = {
            "live": to_json(await store.live()),
            "slots": to_json(await store.slots()),
        }
        for act in acts:
            records[f"act/{act.reference}/{act.revision}"] = to_json(act)
        for reference in sorted({act.reference for act in acts}):
            records[f"entries/{reference}"] = to_json(await store.entries_for(reference))
        return records
    finally:
        store.close()


# --- telegram-<…>.db ------------------------------------------------------------------


def _telegram(directory: Path) -> SqliteTelegramIntakeRecord:
    return SqliteTelegramIntakeRecord(
        path=telegram_intake_path(
            directory, reference=TELEGRAM_CONNECTION, chat_id=TELEGRAM_CHAT_ID
        )
    )


async def _write_telegram(directory: Path, moment: Moment) -> None:
    del moment  # the record stamps nothing
    store = _telegram(directory)
    try:
        poll = await store.claim_poll()
        await store.finish(poll.attempt, TelegramOutcome())
        await store.take_in((101, 102), activation_id="act-upgrade-1")
        await store.confirm_through(101)
        typing = await store.claim_typing("act-upgrade-1")
        await store.finish(typing, TelegramOutcome())
        reply = await store.claim_reply(101)
        if reply is not None:
            await store.finish(reply, TelegramOutcome())
    finally:
        store.close()


async def _read_telegram(directory: Path) -> Records:
    store = _telegram(directory)
    try:
        exported = to_json(await store.export())
        assert isinstance(exported, dict)  # noqa: S101  # a model dumps to an object
        return {f"export/{name}": value for name, value in exported.items()}
    finally:
        store.close()


# --- bookings.db ----------------------------------------------------------------------


def _bookings(directory: Path) -> SqliteBookingStore:
    return SqliteBookingStore(path=directory / "bookings.db", retained=BOOKING_RETAINED)


async def _write_bookings(directory: Path, moment: Moment) -> None:
    store = _bookings(directory)
    try:
        for days in (3, 4):
            await store.commit(
                {
                    ORIGIN_ARGUMENT: BOOKING_ENDPOINT,
                    DATE_ARGUMENT: (moment.now + timedelta(days=days)).date().isoformat(),
                    CHARGED_AMOUNT_KEY: "120.00",
                    CHARGED_CURRENCY_KEY: "EUR",
                }
            )
    finally:
        store.close()


async def _read_bookings(directory: Path) -> Records:
    store = _bookings(directory)
    try:
        records: Records = {"count": await store.commit_count()}
        for record in await store.records():
            records[f"record/{record[DATE_ARGUMENT]}"] = to_json(record)
        return records
    finally:
        store.close()


# --- devices.db -----------------------------------------------------------------------


def _devices(directory: Path) -> EnrolmentStore:
    return EnrolmentStore(directory / ENROLMENTS_FILENAME)


async def _write_devices(directory: Path, moment: Moment) -> None:
    store = _devices(directory)
    try:
        store.enrol("phone.tailnet.example", verifier="v" * 64, now=moment.ago(days=3))
        store.enrol("laptop.tailnet.example", verifier="w" * 64, now=moment.ago(days=2))
        store.revoke("laptop.tailnet.example", now=moment.ago(days=1))
        store.register("phone-gateway", gateway="phone.tailnet.example", now=moment.ago(hours=5))
        store.assign_role("phone.tailnet.example", DeviceRole.SPOKES)
    finally:
        store.close()


async def _read_devices(directory: Path) -> Records:
    store = _devices(directory)
    try:
        enrolments, _ = store.recent_enrolments(limit=_PAGE)
        devices, _ = store.recent_devices(limit=_PAGE)
        registrations, _ = store.recent_registrations(limit=_PAGE)
        records: Records = {}
        records.update(_keyed("enrolment", enrolments, _field("enrolment_id")))
        records.update(_keyed("device", devices, _field("device_id")))
        records.update(_keyed("registration", registrations, _field("registration_id")))
        return records
    finally:
        store.close()


#: Every store a person's hub keeps, in the order the writer fills them.
STORES: Final[tuple[Store, ...]] = (
    Store("traces", ("traces.db",), _write_traces, _read_traces),
    Store("memory", ("memory.db",), _write_memory, _read_memory),
    Store("stories", ("stories.db",), _write_stories, _read_stories),
    Store("audit", ("audit.db",), _write_audit, _read_audit),
    Store("plans", ("plans.db",), _write_plans, _read_plans),
    Store("conversations", ("conversations.db",), _write_conversations, _read_conversations),
    Store("grants", ("grants.db",), _write_grants, _read_grants),
    Store("reads", ("reads.db",), _write_reads, _read_reads),
    Store("notifications", ("notifications.db",), _write_notifications, _read_notifications),
    Store("outbox", ("outbox.db",), _write_outbox, _read_outbox),
    Store("connections", ("connections.db",), _write_connections, _read_connections),
    Store("telegram", ("telegram-*.db",), _write_telegram, _read_telegram),
    Store("bookings", ("bookings.db",), _write_bookings, _read_bookings),
    Store("devices", (ENROLMENTS_FILENAME,), _write_devices, _read_devices),
)

#: What the data directory holds that is not a store (ADR-0326 §2:2, §8): the instance
#: lock, the two sockets, and the diagnostic record's directory.
NOT_STORES: Final = frozenset({"hub.lock", "hub.sock", "admin.sock", "diagnostics"})


def cast_records(value: object) -> Records:
    """``value`` as a store's records, as a snapshot file holds them.

    Args:
        value: One store's ``records`` from a decoded snapshot.

    Returns:
        The same object, typed.

    Raises:
        TypeError: If it is not an object.
    """
    if not isinstance(value, dict):
        msg = "a store's records are an object"
        raise TypeError(msg)
    return cast("Records", value)


__all__ = [
    "NOT_STORES",
    "STORES",
    "Json",
    "Moment",
    "Records",
    "Store",
    "cast_records",
    "check_settings",
    "to_json",
]
